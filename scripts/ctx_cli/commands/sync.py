"""
Sync command for ctx CLI - Upload and sync workspace to remote Context-Engine.

Triggers a one-time upload of files to a remote Context-Engine upload service.
Use this when:
- Your files are NOT mounted in the container (remote server scenario)
- You want to push local changes to a remote Context-Engine instance
- CI/CD pipelines pushing to a central indexer

If your files ARE already mounted (docker-compose with HOST_INDEX_PATH),
use `ctx index` instead - no upload needed.
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from scripts.workspace_state import ensure_logical_repo_reuse_for_cli
except ImportError:
    def ensure_logical_repo_reuse_for_cli() -> None:
        os.environ.setdefault("LOGICAL_REPO_REUSE", "1")

console = Console() if RICH_AVAILABLE else None


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


def _find_upload_client() -> Optional[Path]:
    """Find the standalone_upload_client.py script."""
    # Check in scripts/ directory (same level as ctx_cli)
    scripts_dir = Path(__file__).resolve().parent.parent.parent
    candidates = [
        scripts_dir / "standalone_upload_client.py",
        scripts_dir / "remote_upload_client.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _get_default_endpoint() -> str:
    """Get default upload endpoint from environment or default."""
    return os.environ.get("REMOTE_UPLOAD_ENDPOINT", "http://localhost:8004")


def _get_default_workspace() -> str:
    """Get default workspace path."""
    return os.environ.get("WORKSPACE_PATH") or os.environ.get("WATCH_ROOT") or os.getcwd()


def sync(
    path: Optional[str] = None,
    endpoint: Optional[str] = None,
    watch: bool = False,
    force: bool = False,
    interval: int = 5,
    git_history: bool = False,
    git_max_commits: int = 500,
    git_since: Optional[str] = None,
    host_root: Optional[str] = None,
    container_root: str = "/work",
    collection: Optional[str] = None,
    timeout: int = 300,
):
    """
    Trigger a one-time sync to remote Context-Engine server.

    Uploads files to a remote upload service which triggers indexing.
    Use when files are NOT mounted in the container.

    If files ARE mounted (docker-compose), use `ctx index` instead.

    Examples:
        ctx sync                              # Sync current directory
        ctx sync /path/to/repo                # Sync specific directory
        ctx sync --endpoint http://host:8004  # Use custom endpoint
        ctx sync --git-history                # Include git commit metadata
    """
    # Enable logical repo reuse for CLI sync operations
    ensure_logical_repo_reuse_for_cli()

    # Find upload client script
    client_script = _find_upload_client()
    if not client_script:
        _print_panel(
            "[red]Upload client not found![/red]\n\n"
            "The standalone_upload_client.py script is required.\n"
            "It should be in the scripts/ directory.",
            title="Missing Dependency",
            border_style="red"
        )
        return 1

    # Resolve paths and endpoint
    workspace_path = Path(path) if path else Path(_get_default_workspace())
    workspace_path = workspace_path.resolve()

    if not workspace_path.exists():
        _print(f"[red]Error:[/red] Path does not exist: {workspace_path}", error=True)
        return 1

    if not workspace_path.is_dir():
        _print(f"[red]Error:[/red] Path is not a directory: {workspace_path}", error=True)
        return 1

    upload_endpoint = endpoint or _get_default_endpoint()
    effective_host_root = host_root or str(workspace_path)

    # Determine mode
    mode_str = "Watch Sync" if watch else "One-shot Sync"

    # Build command arguments
    cmd = [sys.executable, str(client_script)]
    cmd.extend(["--path", str(workspace_path)])
    cmd.extend(["--endpoint", upload_endpoint])
    cmd.extend(["--timeout", str(timeout)])

    # Force upload: always for one-shot, or when explicitly requested
    if force or not watch:
        cmd.append("--force")

    # Build environment - path mapping and git history via env vars
    env = os.environ.copy()

    # Path mapping (HOST_ROOT → CONTAINER_ROOT)
    env["HOST_ROOT"] = effective_host_root
    env["CONTAINER_ROOT"] = container_root

    # Collection name if specified
    if collection:
        env["COLLECTION_NAME"] = collection

    # Git history options
    if git_history:
        env["REMOTE_UPLOAD_GIT_MAX_COMMITS"] = str(git_max_commits)
        if git_since:
            env["REMOTE_UPLOAD_GIT_SINCE"] = git_since

    # Determine mode
    mode_str = "Watch Sync" if watch else "One-shot Sync"

    # Display sync info
    _print_panel(
        f"[cyan]Mode:[/cyan] {mode_str}\n"
        f"[cyan]Path:[/cyan] {workspace_path}\n"
        f"[cyan]Endpoint:[/cyan] {upload_endpoint}\n"
        f"[cyan]Host Root:[/cyan] {effective_host_root}\n"
        f"[cyan]Container Root:[/cyan] {container_root}"
        + (f"\n[cyan]Git History:[/cyan] Enabled ({git_max_commits} commits)" if git_history else "")
        + (f"\n[dim]Press Ctrl+C to stop[/dim]" if watch else ""),
        title=f"Starting {mode_str}",
        border_style="cyan"
    )

    def _run_sync_once() -> int:
        """Run a single sync operation. Returns exit code."""
        proc = None
        start_time = time.time()
        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            if proc.stdout:
                for line in iter(proc.stdout.readline, ''):
                    if not line:
                        break
                    line = line.rstrip()

                    # Parse output for status updates
                    if "success" in line.lower() or "complete" in line.lower():
                        _print(f"[green]✓[/green] {line}")
                    elif "error" in line.lower():
                        _print(f"[red]Error:[/red] {line}", error=True)
                    elif "warning" in line.lower() or "warn" in line.lower():
                        _print(f"[yellow]Warning:[/yellow] {line}")
                    elif "scanning" in line.lower() or "detecting" in line.lower():
                        _print(f"[dim]{line}[/dim]")
                    elif "files" in line.lower() or "upload" in line.lower():
                        _print(f"[cyan]{line}[/cyan]")
                    else:
                        _print(f"[dim]{line}[/dim]")

            proc.wait()
            elapsed = time.time() - start_time

            if proc.returncode == 0:
                _print(f"[green]✓[/green] Sync completed in [cyan]{elapsed:.1f}s[/cyan]")
            else:
                _print(f"[red]✗[/red] Sync failed (exit code {proc.returncode})", error=True)

            return proc.returncode or 0

        except Exception as e:
            _print(f"[red]Error running sync:[/red] {e}", error=True)
            if proc:
                proc.kill()
            return 1

    # Execute sync
    try:
        if not watch:
            # One-shot mode
            result = _run_sync_once()
            if result == 0:
                _print_panel(
                    "[green]✓[/green] Sync complete",
                    title="Done",
                    border_style="green"
                )
            return result

        # Watch mode: run periodically
        effective_interval = max(interval, 2)  # Minimum 2s to avoid hammering
        _print(f"[dim]Watching for changes (interval: {effective_interval}s)...[/dim]")
        while True:
            result = _run_sync_once()
            if result != 0:
                _print(f"[yellow]Sync failed, will retry in {effective_interval}s...[/yellow]")
            time.sleep(effective_interval)

    except KeyboardInterrupt:
        _print("\n[yellow]Stopping sync...[/yellow]")
        _print("[green]Sync stopped[/green]")
        return 0


def register_command(subparsers):
    """Register the sync command with the CLI argument parser."""
    parser = subparsers.add_parser(
        "sync",
        help="Upload workspace to remote Context-Engine server",
        description="Trigger a one-time upload to a remote Context-Engine upload service.\n\n"
                    "Use when files are NOT mounted in the container (remote server scenario).\n"
                    "If files ARE already mounted (docker-compose), use `ctx index` instead.",
        formatter_class=lambda prog: __import__('argparse').RawDescriptionHelpFormatter(prog, max_help_position=40),
        epilog="""
Examples:
  ctx sync                                # Sync current directory
  ctx sync /path/to/repo                  # Sync specific directory
  ctx sync --watch                        # Watch mode with auto-sync
  ctx sync --watch --interval 10          # Watch with 10s interval
  ctx sync --endpoint http://host:8004    # Use custom upload endpoint
  ctx sync --git-history                  # Include git commit metadata
  ctx sync --git-history --git-since "1 year ago"

Environment Variables:
  REMOTE_UPLOAD_ENDPOINT     Default upload endpoint (default: http://localhost:8004)
  WORKSPACE_PATH             Default workspace path
"""
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Directory to sync (default: current directory)"
    )

    parser.add_argument(
        "--endpoint", "-e",
        help=f"Remote upload endpoint (default: {_get_default_endpoint()})"
    )

    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Watch for changes and sync automatically"
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force upload of all files (default for non-watch mode)"
    )

    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=5,
        help="Watch interval in seconds (default: 5, minimum: 2)"
    )

    parser.add_argument(
        "--git-history", "-g",
        action="store_true",
        help="Include git commit metadata in uploads"
    )

    parser.add_argument(
        "--git-max-commits",
        type=int,
        default=500,
        help="Maximum commits to include in git history (default: 500)"
    )

    parser.add_argument(
        "--git-since",
        help="Git log time constraint (e.g., '1 year ago', '2024-01-01')"
    )

    parser.add_argument(
        "--host-root",
        help="Host path prefix for path rewriting (default: same as path)"
    )

    parser.add_argument(
        "--container-root",
        default="/work",
        help="Container path for remote service (default: /work)"
    )

    parser.add_argument(
        "--collection", "-c",
        help="Target collection name"
    )

    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=300,
        help="Request timeout in seconds (default: 300)"
    )

    def run_sync(args):
        """Wrapper to call sync function with argparse args."""
        return sync(
            path=args.path,
            endpoint=args.endpoint,
            watch=args.watch,
            force=args.force,
            interval=args.interval,
            git_history=args.git_history,
            git_max_commits=args.git_max_commits,
            git_since=args.git_since,
            host_root=args.host_root,
            container_root=args.container_root,
            collection=args.collection,
            timeout=args.timeout,
        )

    parser.set_defaults(func=run_sync)

