"""
Index command for ctx CLI - Index codebase into Qdrant.

Supports:
- Normal indexing: Index the mounted workspace root (/work)
- Subdirectory indexing: Index a subdirectory within the mounted workspace
- Watch mode: Monitor for changes and reindex automatically
- Recreate: Drop and recreate collection
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError

console = Console()

# Configuration
WATCH_SCRIPT = Path(__file__).resolve().parent.parent.parent / "watch_index.py"

def _find_dotenv(start: Optional[Path] = None, max_parents: int = 3) -> Optional[Path]:
    """Find a `.env` file by searching current/parent directories."""
    current = (start or Path.cwd()).resolve()
    for _ in range(max_parents + 1):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _load_env_file(env_path: Path) -> dict:
    """Parse KEY=VALUE lines from a .env file (no interpolation)."""
    env_vars: dict = {}
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            if key:
                env_vars[key] = value
    except Exception:
        return {}
    return env_vars


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

    env_path = _find_dotenv()
    if not env_path:
        return None
    env_vars = _load_env_file(env_path)
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
        ctx index --watch               # Watch mode with auto-reindex
        ctx index --collection myrepo   # Use specific collection
    """
    explicit_path = path is not None

    # Check if services are running
    is_running, error_msg = check_services_running()
    if not is_running:
        console.print(Panel(
            "[red]MCP Indexer service is not running![/red]\n\n"
            f"Error: {error_msg}\n\n"
            "Please start the services first:\n"
            "  [cyan]ctx up[/cyan]  # Start services with docker-compose\n"
            "  [cyan]docker-compose up -d[/cyan]  # Or start manually",
            title="Service Not Available",
            border_style="red"
        ))
        return 1

    # Resolve target path
    target_path = Path(path if path else os.getcwd()).resolve()
    if not target_path.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {target_path}")
        return 1

    if not target_path.is_dir():
        console.print(f"[red]Error:[/red] Path is not a directory: {target_path}")
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
        console.print(Panel(str(e), title="Invalid Path", border_style="red"))
        return 1

    # Add optional parameters
    if collection:
        params["collection"] = collection
    if repo:
        params["repo"] = repo

    # Show start message
    console.print(Panel(
        f"[cyan]Indexing:[/cyan] {display_path}\n"
        f"[cyan]Collection:[/cyan] {collection or 'auto-detect'}\n"
        f"[cyan]Recreate:[/cyan] {recreate}",
        title="Starting Indexing",
        border_style="cyan"
    ))

    # Call MCP tool with progress display
    start_time = time.time()

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

    elapsed = time.time() - start_time

    # MCPClient returns already-parsed results
    data = result

    # Check for error
    if "error" in data:
        console.print(f"[red]Error:[/red] {data['error']}")
        return 1

    # Check if operation succeeded
    if not data.get("ok", False):
        error_msg = data.get("error", "Unknown error")
        console.print(f"[red]Indexing failed:[/red] {error_msg}")
        return 1

    # Extract statistics
    total_files = data.get("total_files", 0)
    changed_files = data.get("changed", 0)
    deleted_files = data.get("deleted", 0)
    skipped_files = data.get("skipped", 0)

    # Display results
    console.print(Panel(
        f"[green]✓[/green] Indexed [cyan]{total_files:,}[/cyan] files in [cyan]{elapsed:.1f}s[/cyan]\n"
        f"  Changed: [yellow]{changed_files}[/yellow]\n"
        f"  Deleted: [red]{deleted_files}[/red]\n"
        f"  Skipped: [dim]{skipped_files}[/dim]",
        title="Indexing Complete",
        border_style="green"
    ))
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
        console.print(f"[red]Error:[/red] Watch script not found: {WATCH_SCRIPT}")
        return 1

    # Build environment for watch script
    env = os.environ.copy()
    if collection:
        env["COLLECTION_NAME"] = collection
    if repo:
        env["REPO_NAME"] = repo

    console.print(Panel(
        f"[cyan]Watching:[/cyan] {target_path}\n"
        f"[cyan]Collection:[/cyan] {collection or 'auto-detect'}\n"
        "[dim]Press Ctrl+C to stop[/dim]",
        title="Watch Mode",
        border_style="cyan"
    ))

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
                    console.print(f"[green]✓[/green] {line}")
                elif "error" in line.lower():
                    console.print(f"[red]Error:[/red] {line}")
                elif "warn" in line.lower():
                    console.print(f"[yellow]Warning:[/yellow] {line}")
                else:
                    console.print(f"[dim]{line}[/dim]")

        proc.wait()

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping watch mode...[/yellow]")
        if proc:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        console.print("[green]Watch mode stopped[/green]")
        return 0
    except Exception as e:
        console.print(f"[red]Error running watch mode:[/red] {e}")
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
            collection=args.collection,
            repo=args.repo
        )

    parser.set_defaults(func=run_index)
