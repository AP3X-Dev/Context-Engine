"""
Reset command for ctx CLI - Full development environment reset.

Orchestrates a complete rebuild of the development environment:
- Stops all services
- Rebuilds containers (optional)
- Downloads models/tokenizers
- Recreates indexes
- Starts services in specified mode (dual/mcp/sse)
"""

import logging
import os
import sys
import time
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

from scripts.ctx_cli.utils.env import (
    get_qdrant_url_for_host,
    find_env_file,
    load_env_file,
)

logger = logging.getLogger(__name__)

# Load .env file into os.environ (if not already set)
# This ensures NEO4J_GRAPH, REFRAG_RUNTIME, etc. are available
def _load_env_to_environ():
    """Load .env file values into os.environ if not already set."""
    # Check both project root .env and scripts/.env
    for env_path in [find_env_file(), Path("scripts/.env")]:
        if env_path and env_path.exists():
            env_vars = load_env_file(env_path)
            for key, value in env_vars.items():
                if key not in os.environ:
                    os.environ[key] = value

_load_env_to_environ()

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None

# Default model/tokenizer URLs (same as Makefile)
DEFAULT_MODEL_URL = "https://huggingface.co/ibm-granite/granite-4.0-micro-GGUF/resolve/main/granite-4.0-micro-Q4_K_M.gguf"
DEFAULT_MODEL_PATH = "models/model.gguf"
DEFAULT_TOKENIZER_URL = "https://huggingface.co/BAAI/bge-base-en-v1.5/resolve/main/tokenizer.json"
DEFAULT_TOKENIZER_PATH = "models/tokenizer.json"


def _print(msg: str, error: bool = False) -> None:
    """Print with Rich if available, otherwise plain print."""
    if console:
        console.print(msg)
    else:
        import re
        plain = re.sub(r'\[/?[^\]]+\]', '', msg)
        print(plain, file=sys.stderr if error else sys.stdout)


def _print_panel(content: str, title: str = "", border_style: str = "cyan") -> None:
    """Print a panel with Rich if available, otherwise plain print."""
    if console and RICH_AVAILABLE:
        console.print(Panel(content, title=title, border_style=border_style))
    else:
        import re
        plain = re.sub(r'\[/?[^\]]+\]', '', content)
        print(f"\n=== {title} ===" if title else "")
        print(plain)
        print("")


def _run_cmd(cmd: list, description: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command with status display."""
    _print(f"[dim]→ {description}[/dim]")
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=check,
        )
        return result
    except subprocess.CalledProcessError as e:
        if check:
            _print(f"[red]Error:[/red] Command failed: {' '.join(cmd)}", error=True)
            raise
        return e


def _wait_for_qdrant(url: str = "http://localhost:6333", timeout: int = 60) -> bool:
    """Wait for Qdrant to be ready."""
    _print(f"[dim]Waiting for Qdrant at {url}...[/dim]")
    start = time.time()

    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if getattr(r, "status", 200) < 500:
                    _print("[green]✓[/green] Qdrant is ready")
                    return True
        except Exception as e:
            logger.debug(f"Suppressed exception: {e}")
        time.sleep(1)

    _print(f"[red]Error:[/red] Qdrant not ready after {timeout}s", error=True)
    return False


def _download_file(url: str, dest: Path, description: str) -> bool:
    """Download a file with progress display."""
    _print(f"[dim]Downloading {description}...[/dim]")
    _print(f"[dim]  {url} → {dest}[/dim]")

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            ["curl", "-L", "--fail", "--retry", "3", "-C", "-", url, "-o", str(dest)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            _print(f"[green]✓[/green] Downloaded {description}")
            return True
        else:
            _print(f"[red]Error:[/red] Failed to download {description}", error=True)
            return False
    except FileNotFoundError:
        _print("[red]Error:[/red] curl not found, trying urllib...", error=True)
        try:
            urllib.request.urlretrieve(url, str(dest))
            _print(f"[green]✓[/green] Downloaded {description}")
            return True
        except Exception as e:
            _print(f"[red]Error:[/red] Download failed: {e}", error=True)
            return False


def reset(
    mode: str = "dual",
    skip_build: bool = False,
    skip_model: bool = False,
    skip_tokenizer: bool = False,
    model_url: Optional[str] = None,
    model_path: Optional[str] = None,
    tokenizer_url: Optional[str] = None,
    tokenizer_path: Optional[str] = None,
):
    """
    Full development environment reset.

    Stops all services, optionally rebuilds containers, downloads models,
    recreates indexes, and starts services in the specified mode.

    Modes:
        dual: Both SSE and HTTP MCPs (default, most comprehensive)
        mcp:  HTTP MCPs only (streamable, Codex compatible)
        sse:  SSE MCPs only (legacy)

    Examples:
        ctx reset                # Full reset with dual mode
        ctx reset --mcp          # HTTP MCPs only
        ctx reset --sse          # SSE MCPs only
        ctx reset --skip-model   # Skip model download
        ctx reset --skip-build   # Skip container rebuild
    """
    # Resolve paths
    model_url = model_url or os.environ.get("LLAMACPP_MODEL_URL", DEFAULT_MODEL_URL)
    model_path = Path(model_path or os.environ.get("LLAMACPP_MODEL_PATH", DEFAULT_MODEL_PATH))
    tokenizer_url = tokenizer_url or os.environ.get("TOKENIZER_URL", DEFAULT_TOKENIZER_URL)
    tokenizer_path = Path(tokenizer_path or os.environ.get("TOKENIZER_PATH", DEFAULT_TOKENIZER_PATH))

    # Check if Neo4j is enabled
    neo4j_enabled = os.environ.get("NEO4J_ENABLED", "").strip().lower() in ("1", "true", "yes") or \
                    os.environ.get("NEO4J_GRAPH", "").strip().lower() in ("1", "true", "yes")

    # Check if llamacpp is needed (only if REFRAG_RUNTIME is llamacpp or unset)
    refrag_runtime = os.environ.get("REFRAG_RUNTIME", "").strip().lower()
    llamacpp_needed = refrag_runtime in ("", "llamacpp")

    # Build docker compose command prefix (with optional neo4j compose file)
    compose_cmd = ["docker", "compose"]
    if neo4j_enabled:
        compose_cmd.extend(["-f", "docker-compose.yml", "-f", "docker-compose.neo4j.yml"])

    # Determine which containers to build/start based on mode
    if mode == "mcp":
        # HTTP MCPs only (Codex compatible) + upload_service for remote sync
        build_containers = ["indexer", "mcp_http", "mcp_indexer_http", "watcher", "upload_service"]
        start_containers = ["mcp_http", "mcp_indexer_http", "watcher", "upload_service"]
        mode_desc = "HTTP MCPs only (streamable)"
    elif mode == "sse":
        # SSE MCPs only (legacy)
        build_containers = ["indexer", "mcp", "mcp_indexer", "watcher"]
        start_containers = ["mcp", "mcp_indexer", "watcher"]
        mode_desc = "SSE MCPs only (legacy)"
    else:
        # Dual mode (default)
        build_containers = ["indexer", "mcp", "mcp_indexer", "mcp_http", "mcp_indexer_http", "watcher", "upload_service"]
        start_containers = ["mcp", "mcp_indexer", "mcp_http", "mcp_indexer_http", "watcher", "upload_service"]
        mode_desc = "Dual mode (SSE + HTTP)"

    # Add llamacpp container if needed
    if llamacpp_needed:
        build_containers.append("llamacpp")
        start_containers.append("llamacpp")
    else:
        mode_desc += f" (REFRAG_RUNTIME={refrag_runtime})"

    # Add neo4j container if enabled
    if neo4j_enabled:
        build_containers.append("neo4j")
        start_containers.insert(0, "neo4j")  # Start neo4j first (other services depend on it)
        mode_desc += " + Neo4j"

    _print_panel(
        f"[cyan]Mode:[/cyan] {mode_desc}\n"
        f"[cyan]Skip Build:[/cyan] {skip_build}\n"
        f"[cyan]Skip Model:[/cyan] {skip_model}\n"
        f"[cyan]Skip Tokenizer:[/cyan] {skip_tokenizer}",
        title="Development Environment Reset",
        border_style="yellow"
    )

    steps_total = 7
    step = 0

    try:
        # Step 1: Stop all services and remove volumes
        step += 1
        _print(f"\n[bold][{step}/{steps_total}] Stopping services...[/bold]")
        _run_cmd(compose_cmd + ["down", "-v", "--remove-orphans"], "Stopping all containers", check=False)
        _print("[green]✓[/green] Services stopped")

        # Step 2: Build containers (unless skipped)
        step += 1
        if not skip_build:
            _print(f"\n[bold][{step}/{steps_total}] Building containers...[/bold]")
            cmd = compose_cmd + ["build", "--no-cache"] + build_containers
            _run_cmd(cmd, f"Building: {', '.join(build_containers)}")
            _print("[green]✓[/green] Containers built")
        else:
            _print(f"\n[bold][{step}/{steps_total}] Skipping container build[/bold]")

        # Step 3: Start Qdrant (and Neo4j if enabled) and wait
        step += 1
        db_services = ["qdrant"]
        if neo4j_enabled:
            db_services.append("neo4j")
        _print(f"\n[bold][{step}/{steps_total}] Starting {', '.join(db_services)}...[/bold]")
        _run_cmd(compose_cmd + ["up", "-d"] + db_services, f"Starting {', '.join(db_services)}")

        # Use helper that normalizes Docker hostname to localhost for host CLI
        qdrant_url = get_qdrant_url_for_host()
        if not _wait_for_qdrant(qdrant_url):
            return 1

        # Step 4: Initialize payload indexes
        step += 1
        _print(f"\n[bold][{step}/{steps_total}] Initializing payload indexes...[/bold]")
        _run_cmd(
            compose_cmd + ["run", "--rm", "init_payload"],
            "Running init_payload",
            check=False  # May fail if collection doesn't exist yet
        )

        # Step 5: Download tokenizer
        step += 1
        if not skip_tokenizer:
            _print(f"\n[bold][{step}/{steps_total}] Downloading tokenizer...[/bold]")
            if not _download_file(tokenizer_url, tokenizer_path, "tokenizer"):
                _print("[yellow]Warning:[/yellow] Tokenizer download failed, continuing...")
        else:
            _print(f"\n[bold][{step}/{steps_total}] Skipping tokenizer download[/bold]")

        # Step 6: Clear caches and run indexer with recreate
        step += 1
        _print(f"\n[bold][{step}/{steps_total}] Clearing caches and running indexer...[/bold]")

        # Clear local caches (host side) - use rglob to find all cache files
        _print("[dim]Clearing local caches...[/dim]")
        import shutil
        cache_cleared = 0

        # Clear all cache.json files under .codebase (including repos subdirs)
        codebase_dir = Path(".codebase")
        if codebase_dir.exists():
            for cache_file in codebase_dir.rglob("cache.json"):
                try:
                    cache_file.unlink()
                    cache_cleared += 1
                except Exception as e:
                    logger.debug(f"Suppressed exception: {e}")
            # Clear all symbols directories
            for symbols_dir in codebase_dir.rglob("symbols"):
                if symbols_dir.is_dir():
                    try:
                        shutil.rmtree(symbols_dir, ignore_errors=True)
                        cache_cleared += 1
                    except Exception as e:
                        logger.debug(f"Suppressed exception: {e}")

        # Also clear dev-workspace caches (if present)
        dev_workspace = Path("dev-workspace")
        if dev_workspace.exists():
            for cache_file in dev_workspace.rglob(".codebase/cache.json"):
                try:
                    cache_file.unlink()
                    cache_cleared += 1
                except Exception as e:
                    logger.debug(f"Suppressed exception: {e}")
            for symbols_dir in dev_workspace.rglob(".codebase/symbols"):
                if symbols_dir.is_dir():
                    try:
                        shutil.rmtree(symbols_dir, ignore_errors=True)
                        cache_cleared += 1
                    except Exception as e:
                        logger.debug(f"Suppressed exception: {e}")

        _print(f"[dim]Cleared {cache_cleared} host cache entries[/dim]")

        # Also clear caches inside the container (critical for bind-mounted workspaces)
        _print("[dim]Clearing container caches...[/dim]")
        _run_cmd(
            compose_cmd + ["run", "--rm", "--entrypoint", "sh", "indexer", "-c",
             "find /work -path '*/.codebase/*/cache.json' -delete 2>/dev/null; "
             "find /work -path '*/.codebase/cache.json' -delete 2>/dev/null; "
             "find /work -path '*/.codebase/*/symbols' -type d -exec rm -rf {} + 2>/dev/null; "
             "find /work -path '*/.codebase/symbols' -type d -exec rm -rf {} + 2>/dev/null; "
             "echo 'Container caches cleared'"],
            "Clearing container caches",
            check=False,
        )

        # Build env vars for indexer
        indexer_env = {}
        for var in ["INDEX_MICRO_CHUNKS", "MAX_MICRO_CHUNKS_PER_FILE", "TOKENIZER_PATH", "TOKENIZER_URL"]:
            if var in os.environ:
                indexer_env[var] = os.environ[var]

        # Defer pseudo-describe to backfill worker for much faster initial indexing
        # The watch_index worker will backfill pseudo/tags after indexing completes
        indexer_env["PSEUDO_DEFER_TO_WORKER"] = "1"

        # Run indexer detached (-d) so CLI doesn't block
        # Use --rm to auto-remove container on exit; first remove any stale container with same name
        # to ensure idempotent operation across multiple runs
        subprocess.run(
            ["docker", "rm", "-f", "ctx-reset-indexer"],
            capture_output=True,
            check=False,  # Ignore error if container doesn't exist
        )
        indexer_cmd = compose_cmd + ["run", "-d", "--rm", "--name", "ctx-reset-indexer"]
        for k, v in indexer_env.items():
            indexer_cmd.extend(["-e", f"{k}={v}"])
        indexer_cmd.extend(["indexer", "--root", "/work", "--recreate"])

        _run_cmd(indexer_cmd, "Starting indexer (detached)")
        _print("[green]✓[/green] Indexer started in background (pseudo-tags deferred)")
        _print("[dim]  Monitor with: docker logs -f ctx-reset-indexer[/dim]")

        # Step 7: Download model and start services
        step += 1
        if not skip_model:
            _print(f"\n[bold][{step}/{steps_total}] Downloading model and starting services...[/bold]")
            if not _download_file(model_url, model_path, "llama model"):
                _print("[yellow]Warning:[/yellow] Model download failed, continuing...")
        else:
            _print(f"\n[bold][{step}/{steps_total}] Starting services...[/bold]")

        # Start services
        cmd = compose_cmd + ["up", "-d"] + start_containers
        _run_cmd(cmd, f"Starting: {', '.join(start_containers)}")
        _print("[green]✓[/green] Services started")

        _print_panel(
            f"[green]✓[/green] Development environment reset complete!\n\n"
            f"[cyan]Mode:[/cyan] {mode_desc}\n"
            f"[cyan]Services:[/cyan] {', '.join(start_containers)}\n\n"
            f"[dim]Run 'ctx status' to verify all services are healthy.[/dim]",
            title="Reset Complete",
            border_style="green"
        )
        return 0

    except subprocess.CalledProcessError as e:
        _print(f"[red]Error:[/red] Reset failed at step {step}", error=True)
        return 1
    except KeyboardInterrupt:
        _print("\n[yellow]Reset interrupted[/yellow]")
        return 130
    except Exception as e:
        _print(f"[red]Error:[/red] {e}", error=True)
        return 1


def register_command(subparsers):
    """Register the reset command with the CLI argument parser."""
    parser = subparsers.add_parser(
        "reset",
        help="Full development environment reset",
        description="Stop services, rebuild containers, download models, recreate indexes, and start services.\n\n"
                    "This is equivalent to the Makefile's reset-dev targets.",
        epilog="""
Modes:
  dual (default)  Both SSE and HTTP MCPs (most comprehensive)
  mcp             HTTP MCPs only (streamable, Codex compatible)
  sse             SSE MCPs only (legacy)

Examples:
  ctx reset                # Full reset with dual mode
  ctx reset --mcp          # HTTP MCPs only (streamable)
  ctx reset --sse          # SSE MCPs only (legacy)
  ctx reset --skip-model   # Skip llama model download
  ctx reset --skip-build   # Skip container rebuild (faster)
"""
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--mcp",
        action="store_true",
        help="HTTP MCPs only (streamable, Codex compatible)"
    )
    mode_group.add_argument(
        "--sse",
        action="store_true",
        help="SSE MCPs only (legacy)"
    )

    # Skip options
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip container rebuild (use existing images)"
    )
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Skip llama model download"
    )
    parser.add_argument(
        "--skip-tokenizer",
        action="store_true",
        help="Skip tokenizer download"
    )

    # Custom URLs/paths
    parser.add_argument(
        "--model-url",
        help=f"Custom model URL (default: {DEFAULT_MODEL_URL[:50]}...)"
    )
    parser.add_argument(
        "--model-path",
        help=f"Custom model path (default: {DEFAULT_MODEL_PATH})"
    )
    parser.add_argument(
        "--tokenizer-url",
        help=f"Custom tokenizer URL (default: {DEFAULT_TOKENIZER_URL[:50]}...)"
    )
    parser.add_argument(
        "--tokenizer-path",
        help=f"Custom tokenizer path (default: {DEFAULT_TOKENIZER_PATH})"
    )

    def run_reset(args):
        """Wrapper to call reset function with argparse args."""
        # Determine mode
        if args.mcp:
            mode = "mcp"
        elif args.sse:
            mode = "sse"
        else:
            mode = "dual"

        return reset(
            mode=mode,
            skip_build=args.skip_build,
            skip_model=args.skip_model,
            skip_tokenizer=args.skip_tokenizer,
            model_url=args.model_url,
            model_path=args.model_path,
            tokenizer_url=args.tokenizer_url,
            tokenizer_path=args.tokenizer_path,
        )

    parser.set_defaults(func=run_reset)
