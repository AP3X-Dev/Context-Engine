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
# Tokenizer for micro-chunking (token counting). BGE tokenizer works for any model.
# Override via TOKENIZER_URL env var if needed.
DEFAULT_TOKENIZER_URL = os.environ.get(
    "TOKENIZER_URL",
    "https://huggingface.co/BAAI/bge-base-en-v1.5/resolve/main/tokenizer.json"
)
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


def _wait_for_embedding(url: str = "http://localhost:8100", timeout: int = 90) -> bool:
    """Wait for embedding service to be ready."""
    _print(f"[dim]Waiting for embedding service at {url}...[/dim]")
    start = time.time()

    while time.time() - start < timeout:
        try:
            health_url = f"{url.rstrip('/')}/health"
            with urllib.request.urlopen(health_url, timeout=5) as r:
                if getattr(r, "status", 200) < 500:
                    _print("[green]✓[/green] Embedding service is ready")
                    return True
        except Exception as e:
            logger.debug(f"Suppressed exception: {e}")
        time.sleep(2)

    _print(f"[red]Error:[/red] Embedding service not ready after {timeout}s", error=True)
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
    mode: str = "mcp",
    skip_build: bool = False,
    skip_model: bool = False,
    skip_tokenizer: bool = False,
    db_reset: bool = False,
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
        (default): HTTP MCPs only (streamable, Codex compatible)
        --dual:    Both SSE and HTTP MCPs (most comprehensive)
        --sse:     SSE MCPs only (legacy)

    Examples:
        ctx reset                # Full reset with HTTP MCPs (default)
        ctx reset --dual         # Both SSE and HTTP MCPs
        ctx reset --sse          # SSE MCPs only (legacy)
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

    compose_cmd = ["docker", "compose"]
    if neo4j_enabled:
        compose_cmd.extend(["-f", "docker-compose.yml", "-f", "docker-compose.neo4j.yml"])

    # Check if Redis is enabled (CODEBASE_STATE_BACKEND=redis)
    redis_enabled = os.environ.get("CODEBASE_STATE_BACKEND", "").strip().lower() == "redis"

    # Check if learning reranker is enabled
    rerank_learning_enabled = os.environ.get("RERANK_LEARNING", "1").strip().lower() in ("1", "true", "yes")

    # Determine which containers to build/start based on mode
    # Default is HTTP-only; SSE only starts when explicitly requested with --sse
    # Embedding service is always included (shared ONNX model for all indexers)
    if mode == "sse":
        # SSE MCPs only (legacy, must be explicitly requested)
        build_containers = ["embedding", "indexer", "mcp", "mcp_indexer", "watcher"]
        start_containers = ["embedding", "mcp", "mcp_indexer", "watcher"]
        mode_desc = "SSE MCPs only (legacy)"
    elif mode == "dual":
        # Dual mode (both SSE and HTTP)
        build_containers = ["embedding", "indexer", "mcp", "mcp_indexer", "mcp_http", "mcp_indexer_http", "watcher", "upload_service"]
        start_containers = ["embedding", "mcp", "mcp_indexer", "mcp_http", "mcp_indexer_http", "watcher", "upload_service"]
        mode_desc = "Dual mode (SSE + HTTP)"
    else:
        # HTTP MCPs only (default, Codex compatible) + upload_service for remote sync
        build_containers = ["embedding", "indexer", "mcp_http", "mcp_indexer_http", "watcher", "upload_service"]
        start_containers = ["embedding", "mcp_http", "mcp_indexer_http", "watcher", "upload_service"]
        mode_desc = "HTTP MCPs (streamable)"

    # Add learning_worker if rerank learning is enabled
    if rerank_learning_enabled:
        build_containers.append("learning_worker")
        start_containers.append("learning_worker")
        mode_desc += " + Learning Reranker"

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

    # Add Redis indicator to mode description (Redis is a dependency, not a built container)
    if redis_enabled:
        mode_desc += " + Redis"

    _print_panel(
        f"[cyan]Mode:[/cyan] {mode_desc}\n"
        f"[cyan]Skip Build:[/cyan] {skip_build}\n"
        f"[cyan]Skip Model:[/cyan] {skip_model}\n"
        f"[cyan]Skip Tokenizer:[/cyan] {skip_tokenizer}\n"
        f"[cyan]DB Reset:[/cyan] {db_reset}",
        title="Development Environment Reset",
        border_style="yellow"
    )

    steps_total = 7
    step = 0

    try:
        # Step 1: Stop all services (and optionally reset database volumes)
        step += 1
        _print(f"\n[bold][{step}/{steps_total}] Stopping services...[/bold]")
        if db_reset:
            # Full reset including database volumes (qdrant, redis, neo4j, embedding cache)
            _run_cmd(compose_cmd + ["down", "-v", "--remove-orphans"], "Stopping all containers and removing volumes", check=False)
            _print("[green]✓[/green] Services stopped and database volumes removed")
        else:
            # Stop services but preserve database volumes
            _run_cmd(compose_cmd + ["down", "--remove-orphans"], "Stopping all containers", check=False)
            _print("[green]✓[/green] Services stopped (database volumes preserved)")

        # Step 2: Build containers (unless skipped)
        step += 1
        if not skip_build:
            _print(f"\n[bold][{step}/{steps_total}] Building containers...[/bold]")
            cmd = compose_cmd + ["build", "--no-cache"] + build_containers
            _run_cmd(cmd, f"Building: {', '.join(build_containers)}")
            _print("[green]✓[/green] Containers built")
        else:
            _print(f"\n[bold][{step}/{steps_total}] Skipping container build[/bold]")

        # Step 3: Start Qdrant, Redis (if enabled), Neo4j (if enabled), and Embedding service
        step += 1
        db_services = ["qdrant"]
        if redis_enabled:
            db_services.append("redis")
        if neo4j_enabled:
            db_services.append("neo4j")
        # Start embedding service early (indexer needs it)
        db_services.append("embedding")
        _print(f"\n[bold][{step}/{steps_total}] Starting {', '.join(db_services)}...[/bold]")
        # Use --scale for embedding to get 2 replicas (deploy.replicas is Swarm-only)
        _run_cmd(compose_cmd + ["up", "-d", "--scale", "embedding=2"] + db_services, f"Starting {', '.join(db_services)} (embedding×2)")

        # Use helper that normalizes Docker hostname to localhost for host CLI
        qdrant_url = get_qdrant_url_for_host()
        if not _wait_for_qdrant(qdrant_url):
            return 1

        # Wait for embedding service to be ready (indexer needs it)
        if not _wait_for_embedding("http://localhost:8100"):
            _print("[yellow]Warning:[/yellow] Embedding service not ready, indexer may have errors")

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
        for var in ["INDEX_MICRO_CHUNKS", "MAX_MICRO_CHUNKS_PER_FILE", "TOKENIZER_PATH", "TOKENIZER_URL", "INDEX_WORKERS"]:
            if var in os.environ:
                indexer_env[var] = os.environ[var]

        indexer_env["PSEUDO_DEFER_TO_WORKER"] = "1"
        if "INDEX_WORKERS" not in indexer_env:
            indexer_env["INDEX_WORKERS"] = "4"

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
        # Use --scale for embedding service to get multiple replicas (deploy.replicas is Swarm-only)
        cmd = compose_cmd + ["up", "-d", "--scale", "embedding=2"] + start_containers
        _run_cmd(cmd, f"Starting: {', '.join(start_containers)} (embedding×2)")
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
  (default)       HTTP MCPs only (streamable, Codex compatible)
  --dual          Both SSE and HTTP MCPs (most comprehensive)
  --sse           SSE MCPs only (legacy)

Examples:
  ctx reset                # Full reset with HTTP MCPs (default)
  ctx reset --dual         # Both SSE and HTTP MCPs
  ctx reset --sse          # SSE MCPs only (legacy)
  ctx reset --db-reset     # Reset database volumes (Qdrant, Redis, Neo4j, Embedding cache)
  ctx reset --skip-model   # Skip llama model download
  ctx reset --skip-build   # Skip container rebuild (faster)
"""
    )

    # Mode selection (mutually exclusive among modes)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--mcp",
        action="store_true",
        help="HTTP MCPs only (streamable, Codex compatible) - this is the default"
    )
    mode_group.add_argument(
        "--dual",
        action="store_true",
        help="Both SSE and HTTP MCPs (most comprehensive)"
    )
    mode_group.add_argument(
        "--sse",
        action="store_true",
        help="SSE MCPs only (legacy)"
    )

    # Database reset option (can be combined with any mode)
    parser.add_argument(
        "--db-reset",
        action="store_true",
        help="Reset database volumes (Qdrant, Redis, Neo4j, Embedding cache)"
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
        # Determine mode (default is HTTP-only, no SSE)
        if args.dual:
            mode = "dual"
        elif args.sse:
            mode = "sse"
        else:
            # --mcp or no flag = HTTP MCPs only (default)
            mode = "mcp"

        return reset(
            mode=mode,
            skip_build=args.skip_build,
            skip_model=args.skip_model,
            skip_tokenizer=args.skip_tokenizer,
            db_reset=args.db_reset,
            model_url=args.model_url,
            model_path=args.model_path,
            tokenizer_url=args.tokenizer_url,
            tokenizer_path=args.tokenizer_path,
        )

    parser.set_defaults(func=run_reset)
