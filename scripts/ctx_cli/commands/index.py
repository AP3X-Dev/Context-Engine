"""
Index command for ctx CLI - Index codebase into Qdrant.

Supports:
- Normal indexing: Index the mounted workspace root (/work)
- Subdirectory indexing: Index a subdirectory within the mounted workspace
- Watch mode: Monitor for changes and reindex automatically
- Recreate: Drop and recreate collection
"""

import logging
import os
import sys
import time
import signal
import shutil
import subprocess
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)
try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError
from scripts.ctx_cli.utils.env import find_env_file, load_env_file
from scripts.workspace_state import ensure_logical_repo_reuse_for_cli

console = Console() if RICH_AVAILABLE else None


def clear_caches(target_path: Path) -> int:
    """
    Clear all indexing caches (local and container).

    Clears:
    - .codebase/cache.json files
    - .codebase/symbols directories

    Args:
        target_path: Root path to clear caches from

    Returns:
        Number of items cleared
    """
    cleared = 0

    # Clear local caches
    _print("[dim]Clearing local caches...[/dim]")

    # Find and remove cache.json files
    for cache_file in target_path.rglob(".codebase/cache.json"):
        try:
            cache_file.unlink()
            cleared += 1
            _print(f"  [dim]Removed: {cache_file}[/dim]")
        except Exception as e:
            _print(f"  [yellow]Warning:[/yellow] Could not remove {cache_file}: {e}")

    # Find and remove symbols directories
    for symbols_dir in target_path.rglob(".codebase/symbols"):
        if symbols_dir.is_dir():
            try:
                shutil.rmtree(symbols_dir)
                cleared += 1
                _print(f"  [dim]Removed: {symbols_dir}[/dim]")
            except Exception as e:
                _print(f"  [yellow]Warning:[/yellow] Could not remove {symbols_dir}: {e}")

    # Also clear dev-workspace if it exists
    dev_workspace = target_path / "dev-workspace"
    if dev_workspace.exists():
        for cache_file in dev_workspace.rglob(".codebase/cache.json"):
            try:
                cache_file.unlink()
                cleared += 1
            except Exception as e:
                logger.debug(f"Suppressed exception: {e}")
        for symbols_dir in dev_workspace.rglob(".codebase/symbols"):
            if symbols_dir.is_dir():
                try:
                    import shutil
                    shutil.rmtree(symbols_dir)
                    cleared += 1
                except Exception as e:
                    logger.debug(f"Suppressed exception: {e}")

    # Clear container caches via docker exec
    _print("[dim]Clearing container caches...[/dim]")
    containers = ["indexer", "watcher", "mcp_indexer"]
    for container in containers:
        try:
            result = subprocess.run(
                [
                    "docker", "compose", "exec", "-T", container,
                    "sh", "-c",
                    "find /work -path '*/.codebase/cache.json' -delete 2>/dev/null; "
                    "find /work -path '*/.codebase/symbols' -type d -exec rm -rf {} + 2>/dev/null || true"
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                _print(f"  [dim]Cleared caches in container: {container}[/dim]")
        except subprocess.TimeoutExpired:
            _print(f"  [yellow]Warning:[/yellow] Timeout clearing {container} caches")
        except FileNotFoundError:
            # docker not available
            break
        except Exception:
            # Container might not be running, that's fine
            pass

    return cleared


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


# Configuration
WATCH_SCRIPT = Path(__file__).resolve().parent.parent.parent / "watch_index.py"


def _detect_host_index_root() -> Optional[Path]:
    """
    Best-effort detection of the host path mounted into the indexer container as `/work`.

    Prefers:
      1) `HOST_INDEX_PATH` from the current process environment
      2) `HOST_INDEX_PATH` from a nearby `.env` file
    """
    raw = os.environ.get("HOST_INDEX_PATH", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return (p if p.is_absolute() else (Path.cwd() / p)).resolve()

    env_path = find_env_file()
    if not env_path:
        return None
    env_vars = load_env_file(env_path)
    raw = str(env_vars.get("HOST_INDEX_PATH", "")).strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    return (p if p.is_absolute() else (env_path.parent / p)).resolve()


def _index_tool_for_path(
    *,
    target_path: Path,
    recreate: bool,
    explicit_path: bool,
) -> tuple[str, dict, str]:
    """
    Resolve which MCP tool to call for indexing and construct its params.

    Returns:
      (tool_name, params, display_path)
    """
    cwd = Path.cwd().resolve()

    # Backwards-compatible behavior: `ctx index` (no explicit path) indexes `/work`.
    # Also treat `ctx index .` the same way.
    if (not explicit_path) or (target_path == cwd):
        return "qdrant_index_root", {"recreate": recreate}, str(target_path)

    host_root = _detect_host_index_root() or cwd
    try:
        rel = target_path.resolve().relative_to(host_root)
    except ValueError as e:
        raise ValueError(
            f"Path is outside the mounted workspace.\n"
            f"Target: {target_path}\n"
            f"Mounted root (HOST_INDEX_PATH): {host_root}\n\n"
            f"To index that path, update your docker-compose mount (HOST_INDEX_PATH) or pass a path under the mounted root."
        ) from e

    if str(rel) in (".", ""):
        return "qdrant_index_root", {"recreate": recreate}, str(target_path)

    return "qdrant_index", {"subdir": rel.as_posix(), "recreate": recreate}, str(target_path)


def check_services_running() -> tuple[bool, str]:
    """
    Check if MCP indexer service is running.

    Returns:
        (is_running, error_message)
    """
    try:
        # Try to initialize a session with the indexer
        client = MCPClient(server="indexer", timeout=5)
        client._ensure_session()
        return True, ""
    except MCPError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def call_mcp_tool(tool_name: str, params: dict, timeout: int = 300) -> dict:
    """
    Call MCP tool via MCPClient with session handshake.

    Args:
        tool_name: Name of the tool to call
        params: Tool parameters
        timeout: Request timeout in seconds

    Returns:
        Parsed result dictionary
    """
    try:
        client = MCPClient(server="indexer", timeout=timeout)
        return client.call_tool(tool_name, **params)
    except MCPError as e:
        return {"error": f"MCP call failed: {str(e)}"}
    except Exception as e:
        return {"error": f"MCP call failed: {str(e)}"}


def index(
    path: Optional[str] = None,
    watch: bool = False,
    recreate: bool = False,
    hard: bool = False,
    collection: Optional[str] = None,
    repo: Optional[str] = None,
):
    """
    Index codebase into Qdrant.

    By default, indexes the current directory. Use --watch to monitor
    for changes and reindex automatically.

    Examples:
        ctx index                       # Index current directory
        ctx index /path/to/repo         # Index specific directory
        ctx index --recreate            # Drop and recreate collection
        ctx index --hard                # Clear all caches and recreate
        ctx index --watch               # Watch mode with auto-reindex
        ctx index --collection myrepo   # Use specific collection
    """
    # Enable logical repo reuse for CLI indexing operations
    ensure_logical_repo_reuse_for_cli()

    explicit_path = path is not None

    # Resolve target path early for cache clearing
    target_path = Path(path if path else os.getcwd()).resolve()

    # Hard mode: clear all caches first, then force recreate
    if hard:
        _print_panel(
            "[yellow]Hard reindex mode[/yellow]\n"
            "Clearing all caches before reindexing...",
            title="Cache Clear",
            border_style="yellow"
        )
        cleared = clear_caches(target_path)
        _print(f"[green]✓[/green] Cleared {cleared} cache items")
        recreate = True  # Hard mode implies recreate

    # Check if services are running
    is_running, error_msg = check_services_running()
    if not is_running:
        _print_panel(
            "[red]MCP Indexer service is not running![/red]\n\n"
            f"Error: {error_msg}\n\n"
            "Please start the services first:\n"
            "  [cyan]ctx up[/cyan]  # Start services with docker-compose\n"
            "  [cyan]docker-compose up -d[/cyan]  # Or start manually",
            title="Service Not Available",
            border_style="red"
        )
        return 1

    # Validate target path
    if not target_path.exists():
        _print(f"[red]Error:[/red] Path does not exist: {target_path}", error=True)
        return 1

    if not target_path.is_dir():
        _print(f"[red]Error:[/red] Path is not a directory: {target_path}", error=True)
        return 1

    # Watch mode uses subprocess
    if watch:
        return run_watch_mode(target_path, collection, repo)

    # Normal indexing mode
    return run_indexing(target_path, recreate, collection, repo, explicit_path=explicit_path)


def run_indexing(
    target_path: Path,
    recreate: bool,
    collection: Optional[str],
    repo: Optional[str],
    *,
    explicit_path: bool,
):
    """
    Run one-time indexing operation.

    Args:
        target_path: Directory to index
        recreate: Whether to drop and recreate collection
        collection: Collection name (optional)
        repo: Repository name (optional)
    """
    try:
        tool_name, params, display_path = _index_tool_for_path(
            target_path=target_path,
            recreate=recreate,
            explicit_path=explicit_path,
        )
    except ValueError as e:
        _print_panel(str(e), title="Invalid Path", border_style="red")
        return 1

    # Add optional parameters
    if collection:
        params["collection"] = collection
    if repo:
        params["repo"] = repo

    # Show start message
    _print_panel(
        f"[cyan]Indexing:[/cyan] {display_path}\n"
        f"[cyan]Collection:[/cyan] {collection or 'auto-detect'}\n"
        f"[cyan]Recreate:[/cyan] {recreate}",
        title="Starting Indexing",
        border_style="cyan"
    )

    # Call MCP tool with progress display
    start_time = time.time()

    if RICH_AVAILABLE:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Indexing...", total=None)
            result = call_mcp_tool(tool_name, params, timeout=600)
            progress.update(task, completed=True)
    else:
        print("Indexing...")
        result = call_mcp_tool(tool_name, params, timeout=600)

    elapsed = time.time() - start_time

    # MCPClient returns already-parsed results
    data = result

    # Check for error
    if "error" in data:
        _print(f"[red]Error:[/red] {data['error']}", error=True)
        return 1

    # Check if operation succeeded
    if not data.get("ok", False):
        error_msg = data.get("error", "Unknown error")
        _print(f"[red]Indexing failed:[/red] {error_msg}", error=True)
        return 1

    # Extract statistics
    total_files = data.get("total_files", 0)
    changed_files = data.get("changed", 0)
    deleted_files = data.get("deleted", 0)
    skipped_files = data.get("skipped", 0)

    # Display results
    _print_panel(
        f"[green]✓[/green] Indexed [cyan]{total_files:,}[/cyan] files in [cyan]{elapsed:.1f}s[/cyan]\n"
        f"  Changed: [yellow]{changed_files}[/yellow]\n"
        f"  Deleted: [red]{deleted_files}[/red]\n"
        f"  Skipped: [dim]{skipped_files}[/dim]",
        title="Indexing Complete",
        border_style="green"
    )
    return 0


def run_watch_mode(
    target_path: Path,
    collection: Optional[str],
    repo: Optional[str]
):
    """
    Run watch mode by launching watch_index.py subprocess.

    Args:
        target_path: Directory to watch
        collection: Collection name (optional)
        repo: Repository name (optional)
    """
    if not WATCH_SCRIPT.exists():
        _print(f"[red]Error:[/red] Watch script not found: {WATCH_SCRIPT}", error=True)
        return 1

    # Build environment for watch script
    env = os.environ.copy()
    if collection:
        env["COLLECTION_NAME"] = collection
    if repo:
        env["REPO_NAME"] = repo

    _print_panel(
        f"[cyan]Watching:[/cyan] {target_path}\n"
        f"[cyan]Collection:[/cyan] {collection or 'auto-detect'}\n"
        "[dim]Press Ctrl+C to stop[/dim]",
        title="Watch Mode",
        border_style="cyan"
    )

    # Launch subprocess
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, str(WATCH_SCRIPT)],
            cwd=str(target_path),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # Stream output
        if proc.stdout:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                # Parse watch output for file events
                line = line.rstrip()
                if "✓" in line or "Reindexed" in line.lower():
                    _print(f"[green]✓[/green] {line}")
                elif "error" in line.lower():
                    _print(f"[red]Error:[/red] {line}", error=True)
                elif "warn" in line.lower():
                    _print(f"[yellow]Warning:[/yellow] {line}")
                else:
                    _print(f"[dim]{line}[/dim]")

        proc.wait()

    except KeyboardInterrupt:
        _print("\n[yellow]Stopping watch mode...[/yellow]")
        if proc:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        _print("[green]Watch mode stopped[/green]")
        return 0
    except Exception as e:
        _print(f"[red]Error running watch mode:[/red] {e}", error=True)
        if proc:
            proc.kill()
        return 1
    return int(proc.returncode or 0) if proc else 0


def register_command(subparsers):
    """Register the index command with the CLI argument parser.

    Args:
        subparsers: argparse subparsers object
    """
    parser = subparsers.add_parser(
        "index",
        help="Index codebase into Qdrant",
        description="Index codebase into Qdrant vector database for semantic search"
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Directory to index (default: current directory)"
    )

    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Watch for changes and reindex automatically"
    )

    parser.add_argument(
        "--recreate", "-r",
        action="store_true",
        help="Drop and recreate collection before indexing"
    )

    parser.add_argument(
        "--hard",
        action="store_true",
        help="Clear all caches (local + container) then recreate and reindex"
    )

    parser.add_argument(
        "--collection", "-c",
        help="Target collection name (default: auto-detect from workspace)"
    )

    parser.add_argument(
        "--repo",
        help="Logical repository name"
    )

    # Set the function to be called when this command is invoked
    def run_index(args):
        """Wrapper to call index function with argparse args."""
        return index(
            path=args.path,
            watch=args.watch,
            recreate=args.recreate,
            hard=args.hard,
            collection=args.collection,
            repo=args.repo
        )

    parser.set_defaults(func=run_index)
