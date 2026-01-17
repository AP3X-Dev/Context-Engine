"""
Index command for ctx CLI - Index codebase into Qdrant.

Supports:
- Normal indexing: Index a directory (default: current directory)
- Watch mode: Monitor for changes and reindex automatically
- Recreate: Drop and recreate collection
"""

import os
import sys
import json
import time
import signal
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError

console = Console()

# Configuration
WATCH_SCRIPT = Path(__file__).resolve().parent.parent.parent / "watch_index.py"


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
    path: Optional[str] = typer.Argument(
        None,
        help="Directory to index (default: current directory)",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        "-w",
        help="Watch for changes and reindex automatically",
    ),
    recreate: bool = typer.Option(
        False,
        "--recreate",
        "-r",
        help="Drop and recreate collection before indexing",
    ),
    collection: Optional[str] = typer.Option(
        None,
        "--collection",
        "-c",
        help="Target collection name (default: auto-detect from workspace)",
    ),
    repo: Optional[str] = typer.Option(
        None,
        "--repo",
        help="Logical repository name",
    ),
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
        raise typer.Exit(1)

    # Resolve target path
    target_path = Path(path if path else os.getcwd()).resolve()
    if not target_path.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {target_path}")
        raise typer.Exit(1)

    if not target_path.is_dir():
        console.print(f"[red]Error:[/red] Path is not a directory: {target_path}")
        raise typer.Exit(1)

    # Watch mode uses subprocess
    if watch:
        run_watch_mode(target_path, collection, repo)
        return

    # Normal indexing mode
    run_indexing(target_path, recreate, collection, repo)


def run_indexing(
    target_path: Path,
    recreate: bool,
    collection: Optional[str],
    repo: Optional[str]
):
    """
    Run one-time indexing operation.

    Args:
        target_path: Directory to index
        recreate: Whether to drop and recreate collection
        collection: Collection name (optional)
        repo: Repository name (optional)
    """
    # Determine if we're indexing root or subdirectory
    cwd = Path(os.getcwd()).resolve()

    # Decide which tool to call
    if target_path == cwd or str(target_path).endswith(str(cwd)):
        # Indexing workspace root
        tool_name = "qdrant_index_root"
        params = {"recreate": recreate}
    else:
        # Indexing subdirectory
        tool_name = "qdrant_index"
        params = {
            "subdir": str(target_path),
            "recreate": recreate
        }

    # Add optional parameters
    if collection:
        params["collection"] = collection
    if repo:
        params["repo"] = repo

    # Show start message
    console.print(Panel(
        f"[cyan]Indexing:[/cyan] {target_path}\n"
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
        raise typer.Exit(1)

    # Check if operation succeeded
    if not data.get("ok", False):
        error_msg = data.get("error", "Unknown error")
        console.print(f"[red]Indexing failed:[/red] {error_msg}")
        raise typer.Exit(1)

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
        raise typer.Exit(1)

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
    except Exception as e:
        console.print(f"[red]Error running watch mode:[/red] {e}")
        if proc:
            proc.kill()
        raise typer.Exit(1)


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
        index(
            path=args.path,
            watch=args.watch,
            recreate=args.recreate,
            collection=args.collection,
            repo=args.repo
        )
        return 0

    parser.set_defaults(func=run_index)
