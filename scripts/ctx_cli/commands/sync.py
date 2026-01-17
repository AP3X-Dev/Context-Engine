"""
Sync command for ctx CLI - Upload and sync workspace to remote Context-Engine.

Supports:
- One-shot sync: Upload files once
- Daemon mode: Background process that syncs periodically

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
import signal
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

# Daemon PID file location
def _get_pid_file() -> Path:
    """Get the PID file path for the sync daemon."""
    ctx_dir = Path.home() / ".ctx"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    return ctx_dir / "sync-daemon.pid"


def _get_log_file() -> Path:
    """Get the log file path for the sync daemon."""
    ctx_dir = Path.home() / ".ctx"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    return ctx_dir / "sync-daemon.log"


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


# =============================================================================
# Daemon Management
# =============================================================================

def _read_pid() -> Optional[int]:
    """Read PID from pid file. Returns None if not found or invalid."""
    pid_file = _get_pid_file()
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # Invalid PID or process not running
        pid_file.unlink(missing_ok=True)
        return None


def _write_pid(pid: int) -> None:
    """Write PID to pid file."""
    _get_pid_file().write_text(str(pid))


def _remove_pid() -> None:
    """Remove PID file."""
    _get_pid_file().unlink(missing_ok=True)


def daemon_status() -> int:
    """Check daemon status. Returns 0 if running, 1 if not."""
    pid = _read_pid()
    if pid:
        _print(f"[green]✓[/green] Sync daemon is running (PID: {pid})")
        log_file = _get_log_file()
        if log_file.exists():
            _print(f"[dim]Log file: {log_file}[/dim]")
            # Show last few lines of log
            try:
                lines = log_file.read_text().strip().split('\n')[-5:]
                if lines:
                    _print("[dim]Recent log:[/dim]")
                    for line in lines:
                        _print(f"  [dim]{line}[/dim]")
            except Exception:
                pass
        return 0
    else:
        _print("[yellow]Sync daemon is not running[/yellow]")
        return 1


def daemon_stop() -> int:
    """Stop the sync daemon. Returns 0 on success, 1 on failure."""
    pid = _read_pid()
    if not pid:
        _print("[yellow]Sync daemon is not running[/yellow]")
        return 1

    _print(f"[dim]Stopping sync daemon (PID: {pid})...[/dim]")
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for process to terminate
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                _remove_pid()
                _print("[green]✓[/green] Sync daemon stopped")
                return 0
        # Force kill if still running
        os.kill(pid, signal.SIGKILL)
        _remove_pid()
        _print("[yellow]Sync daemon force killed[/yellow]")
        return 0
    except ProcessLookupError:
        _remove_pid()
        _print("[green]✓[/green] Sync daemon stopped")
        return 0
    except PermissionError:
        _print("[red]Error:[/red] Permission denied to stop daemon", error=True)
        return 1


def daemon_start(
    path: str,
    endpoint: str,
    interval: int,
    force: bool,
    git_history: bool,
    git_max_commits: int,
    git_since: Optional[str],
    host_root: str,
    container_root: str,
    collection: Optional[str],
    timeout: int,
) -> int:
    """Start the sync daemon. Returns 0 on success, 1 on failure."""
    # Check if already running
    existing_pid = _read_pid()
    if existing_pid:
        _print(f"[yellow]Sync daemon already running (PID: {existing_pid})[/yellow]")
        _print("[dim]Use 'ctx sync --stop' to stop it first[/dim]")
        return 1

    # Find upload client
    client_script = _find_upload_client()
    if not client_script:
        _print("[red]Error:[/red] Upload client script not found", error=True)
        return 1

    # Build the daemon command - run this script with --daemon-worker flag
    daemon_cmd = [
        sys.executable, "-m", "scripts.ctx_cli.commands.sync",
        "--daemon-worker",
        "--path", path,
        "--endpoint", endpoint,
        "--interval", str(interval),
        "--timeout", str(timeout),
        "--host-root", host_root,
        "--container-root", container_root,
    ]
    if force:
        daemon_cmd.append("--force")
    if git_history:
        daemon_cmd.append("--git-history")
        daemon_cmd.extend(["--git-max-commits", str(git_max_commits)])
        if git_since:
            daemon_cmd.extend(["--git-since", git_since])
    if collection:
        daemon_cmd.extend(["--collection", collection])

    # Start daemon process
    log_file = _get_log_file()
    _print(f"[dim]Starting sync daemon...[/dim]")
    _print(f"[dim]Log file: {log_file}[/dim]")

    try:
        with open(log_file, 'a') as log:
            log.write(f"\n{'='*60}\n")
            log.write(f"Daemon started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            log.write(f"Path: {path}\n")
            log.write(f"Endpoint: {endpoint}\n")
            log.write(f"Interval: {interval}s\n")
            log.write(f"{'='*60}\n")

        # Start detached process
        with open(log_file, 'a') as log:
            proc = subprocess.Popen(
                daemon_cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # Detach from terminal
            )

        _write_pid(proc.pid)
        _print(f"[green]✓[/green] Sync daemon started (PID: {proc.pid})")
        _print(f"[cyan]Path:[/cyan] {path}")
        _print(f"[cyan]Endpoint:[/cyan] {endpoint}")
        _print(f"[cyan]Interval:[/cyan] {interval}s")
        _print(f"\n[dim]Use 'ctx sync --status' to check status[/dim]")
        _print(f"[dim]Use 'ctx sync --stop' to stop the daemon[/dim]")
        return 0

    except Exception as e:
        _print(f"[red]Error starting daemon:[/red] {e}", error=True)
        return 1


def daemon_worker(
    path: str,
    endpoint: str,
    interval: int,
    force: bool,
    git_history: bool,
    git_max_commits: int,
    git_since: Optional[str],
    host_root: str,
    container_root: str,
    collection: Optional[str],
    timeout: int,
) -> int:
    """
    The actual daemon worker process. Runs sync in a loop.
    This is called by daemon_start via subprocess.
    """
    ensure_logical_repo_reuse_for_cli()

    client_script = _find_upload_client()
    if not client_script:
        print("Error: Upload client not found", file=sys.stderr)
        return 1

    workspace_path = Path(path).resolve()

    # Build command
    cmd = [sys.executable, str(client_script)]
    cmd.extend(["--path", str(workspace_path)])
    cmd.extend(["--endpoint", endpoint])
    cmd.extend(["--timeout", str(timeout)])
    if force:
        cmd.append("--force")

    # Build environment
    env = os.environ.copy()
    env["HOST_ROOT"] = host_root
    env["CONTAINER_ROOT"] = container_root
    if collection:
        env["COLLECTION_NAME"] = collection
    if git_history:
        env["REMOTE_UPLOAD_GIT_MAX_COMMITS"] = str(git_max_commits)
        if git_since:
            env["REMOTE_UPLOAD_GIT_SINCE"] = git_since

    effective_interval = max(interval, 2)

    print(f"Daemon worker starting: syncing {workspace_path} every {effective_interval}s")
    print(f"Endpoint: {endpoint}")

    def handle_signal(signum, frame):
        print(f"\nReceived signal {signum}, shutting down...")
        _remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while True:
        try:
            print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Running sync...")
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout + 60,
            )
            if result.returncode == 0:
                print(f"Sync completed successfully")
            else:
                print(f"Sync failed (exit code {result.returncode})")
                if result.stderr:
                    print(f"Error: {result.stderr[:500]}")
        except subprocess.TimeoutExpired:
            print(f"Sync timed out after {timeout + 60}s")
        except Exception as e:
            print(f"Sync error: {e}")

        time.sleep(effective_interval)


# =============================================================================
# Main Sync Function
# =============================================================================

def sync(
    path: Optional[str] = None,
    endpoint: Optional[str] = None,
    daemon: bool = False,
    stop: bool = False,
    status: bool = False,
    force: bool = False,
    interval: int = 30,
    git_history: bool = False,
    git_max_commits: int = 500,
    git_since: Optional[str] = None,
    host_root: Optional[str] = None,
    container_root: str = "/work",
    collection: Optional[str] = None,
    timeout: int = 300,
):
    """
    Sync workspace to remote Context-Engine server.

    Modes:
        One-shot (default): Upload files once and exit
        Daemon (--daemon):  Run in background, sync periodically

    Examples:
        ctx sync                              # One-shot sync
        ctx sync --daemon                     # Start background daemon
        ctx sync --daemon --interval 60       # Sync every 60s
        ctx sync --status                     # Check daemon status
        ctx sync --stop                       # Stop daemon
    """
    # Handle daemon control commands first
    if status:
        return daemon_status()

    if stop:
        return daemon_stop()

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

    # Daemon mode
    if daemon:
        return daemon_start(
            path=str(workspace_path),
            endpoint=upload_endpoint,
            interval=interval,
            force=force,
            git_history=git_history,
            git_max_commits=git_max_commits,
            git_since=git_since,
            host_root=effective_host_root,
            container_root=container_root,
            collection=collection,
            timeout=timeout,
        )

    # One-shot mode
    ensure_logical_repo_reuse_for_cli()

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

    # Build command
    cmd = [sys.executable, str(client_script)]
    cmd.extend(["--path", str(workspace_path)])
    cmd.extend(["--endpoint", upload_endpoint])
    cmd.extend(["--timeout", str(timeout)])
    cmd.append("--force")  # Always force for one-shot

    # Build environment
    env = os.environ.copy()
    env["HOST_ROOT"] = effective_host_root
    env["CONTAINER_ROOT"] = container_root
    if collection:
        env["COLLECTION_NAME"] = collection
    if git_history:
        env["REMOTE_UPLOAD_GIT_MAX_COMMITS"] = str(git_max_commits)
        if git_since:
            env["REMOTE_UPLOAD_GIT_SINCE"] = git_since

    _print_panel(
        f"[cyan]Path:[/cyan] {workspace_path}\n"
        f"[cyan]Endpoint:[/cyan] {upload_endpoint}\n"
        f"[cyan]Host Root:[/cyan] {effective_host_root}\n"
        f"[cyan]Container Root:[/cyan] {container_root}"
        + (f"\n[cyan]Git History:[/cyan] Enabled ({git_max_commits} commits)" if git_history else ""),
        title="One-shot Sync",
        border_style="cyan"
    )

    # Run sync
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
                if "success" in line.lower() or "complete" in line.lower():
                    _print(f"[green]✓[/green] {line}")
                elif "error" in line.lower():
                    _print(f"[red]Error:[/red] {line}", error=True)
                elif "warning" in line.lower():
                    _print(f"[yellow]Warning:[/yellow] {line}")
                else:
                    _print(f"[dim]{line}[/dim]")

        proc.wait()
        elapsed = time.time() - start_time

        if proc.returncode == 0:
            _print_panel(
                f"[green]✓[/green] Sync complete in [cyan]{elapsed:.1f}s[/cyan]",
                title="Done",
                border_style="green"
            )
            return 0
        else:
            _print(f"[red]✗[/red] Sync failed (exit code {proc.returncode})", error=True)
            return proc.returncode

    except KeyboardInterrupt:
        _print("\n[yellow]Sync interrupted[/yellow]")
        return 130
    except Exception as e:
        _print(f"[red]Error:[/red] {e}", error=True)
        return 1


def register_command(subparsers):
    """Register the sync command with the CLI argument parser."""
    parser = subparsers.add_parser(
        "sync",
        help="Upload workspace to remote Context-Engine server",
        description="Sync workspace to a remote Context-Engine upload service.\n\n"
                    "Use when files are NOT mounted in the container (remote server scenario).\n"
                    "If files ARE already mounted (docker-compose), use `ctx index` instead.",
        formatter_class=lambda prog: __import__('argparse').RawDescriptionHelpFormatter(prog, max_help_position=40),
        epilog="""
Examples:
  ctx sync                                # One-shot sync current directory
  ctx sync /path/to/repo                  # Sync specific directory
  ctx sync --daemon                       # Start background sync daemon
  ctx sync --daemon --interval 60         # Daemon syncing every 60 seconds
  ctx sync --status                       # Check if daemon is running
  ctx sync --stop                         # Stop the daemon
  ctx sync --endpoint http://host:8004    # Use custom upload endpoint
  ctx sync --git-history                  # Include git commit metadata

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

    # Daemon control
    daemon_group = parser.add_argument_group("daemon control")
    daemon_group.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="Run as background daemon (periodic sync)"
    )
    daemon_group.add_argument(
        "--stop",
        action="store_true",
        help="Stop the running daemon"
    )
    daemon_group.add_argument(
        "--status",
        action="store_true",
        help="Check daemon status"
    )

    # Sync options
    parser.add_argument(
        "--endpoint", "-e",
        help=f"Remote upload endpoint (default: {_get_default_endpoint()})"
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force upload of all files"
    )

    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=30,
        help="Sync interval in seconds for daemon mode (default: 30, minimum: 2)"
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
            daemon=args.daemon,
            stop=args.stop,
            status=args.status,
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


# =============================================================================
# Direct execution for daemon worker
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon-worker", action="store_true")
    parser.add_argument("--path", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--git-history", action="store_true")
    parser.add_argument("--git-max-commits", type=int, default=500)
    parser.add_argument("--git-since", default=None)
    parser.add_argument("--host-root", required=True)
    parser.add_argument("--container-root", default="/work")
    parser.add_argument("--collection", default=None)

    args = parser.parse_args()

    if args.daemon_worker:
        sys.exit(daemon_worker(
            path=args.path,
            endpoint=args.endpoint,
            interval=args.interval,
            force=args.force,
            git_history=args.git_history,
            git_max_commits=args.git_max_commits,
            git_since=args.git_since,
            host_root=args.host_root,
            container_root=args.container_root,
            collection=args.collection,
            timeout=args.timeout,
        ))
