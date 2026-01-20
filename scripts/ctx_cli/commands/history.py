"""
History command for ctx CLI - Ingest git commit history into Qdrant.

Indexes git commit messages and file lists for semantic search over
your repository's history. Useful for:
- Finding when/why code was changed
- Searching commit messages semantically
- Understanding code evolution
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

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


def _find_ingest_history_script() -> Optional[Path]:
    """Find the ingest_history.py script."""
    scripts_dir = Path(__file__).resolve().parent.parent.parent
    candidate = scripts_dir / "ingest_history.py"
    if candidate.exists():
        return candidate
    return None


def _check_docker_available() -> bool:
    """Check if docker compose is available."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def history(
    path: Optional[str] = None,
    max_commits: int = 200,
    since: Optional[str] = None,
    collection: Optional[str] = None,
    local: bool = False,
):
    """
    Ingest git commit history into Qdrant.

    Indexes commit messages and file lists for semantic search over
    your repository's history.

    Examples:
        ctx history                           # Ingest last 200 commits
        ctx history --max-commits 500         # Ingest last 500 commits
        ctx history --since "1 year ago"      # Ingest commits from last year
        ctx history --local                   # Run locally (no docker)
    """
    # Resolve target path
    target_path = Path(path if path else os.getcwd()).resolve()

    if not target_path.exists():
        _print(f"[red]Error:[/red] Path does not exist: {target_path}", error=True)
        return 1

    if not target_path.is_dir():
        _print(f"[red]Error:[/red] Path is not a directory: {target_path}", error=True)
        return 1

    # Check if it's a git repo
    git_dir = target_path / ".git"
    if not git_dir.exists():
        _print(f"[red]Error:[/red] Not a git repository: {target_path}", error=True)
        return 1

    # Find the ingest_history script
    script = _find_ingest_history_script()
    if not script:
        _print("[red]Error:[/red] ingest_history.py script not found", error=True)
        return 1

    # Build display info
    since_display = since or "all time"

    _print_panel(
        f"[cyan]Repository:[/cyan] {target_path}\n"
        f"[cyan]Max Commits:[/cyan] {max_commits}\n"
        f"[cyan]Since:[/cyan] {since_display}\n"
        f"[cyan]Collection:[/cyan] {collection or 'auto-detect'}",
        title="Ingesting Git History",
        border_style="cyan"
    )

    # Build environment
    env = os.environ.copy()
    if collection:
        env["COLLECTION_NAME"] = collection

    # Build command args
    cmd_args = ["--max-commits", str(max_commits)]
    if since:
        cmd_args.extend(["--since", since])

    # Determine execution mode
    if local or not _check_docker_available():
        # Run locally
        _print("[dim]Running locally...[/dim]")
        cmd = [sys.executable, str(script)] + cmd_args
        cwd = str(target_path)
    else:
        # Run via docker compose
        _print("[dim]Running via docker compose...[/dim]")
        cmd = [
            "docker", "compose", "run", "--rm",
            "--entrypoint", "python",
            "indexer",
            f"/work/scripts/ingest_history.py",
        ] + cmd_args
        cwd = None  # Use docker-compose directory

    # Execute
    try:
        if RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("[cyan]Ingesting history...", total=None)

                proc = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                output_lines = []
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ''):
                        if not line:
                            break
                        line = line.rstrip()
                        output_lines.append(line)
                        # Update progress description with last meaningful line
                        if "commit" in line.lower() or "ingest" in line.lower():
                            progress.update(task, description=f"[cyan]{line[:60]}...")

                proc.wait()
                progress.update(task, completed=True)
        else:
            print("Ingesting history...")
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
            )
            output_lines = proc.stdout.splitlines() if proc.stdout else []

        # Check result
        returncode = proc.returncode if hasattr(proc, 'returncode') else 0

        if returncode == 0:
            # Parse output for stats
            commits_ingested = 0
            for line in output_lines:
                if "ingested" in line.lower() and "commit" in line.lower():
                    # Try to extract number
                    import re
                    match = re.search(r'(\d+)\s*commit', line.lower())
                    if match:
                        commits_ingested = int(match.group(1))

            _print_panel(
                f"[green]✓[/green] Git history ingested successfully\n"
                f"  Commits processed: [cyan]{commits_ingested or 'unknown'}[/cyan]",
                title="History Ingestion Complete",
                border_style="green"
            )
            return 0
        else:
            _print(f"[red]Error:[/red] History ingestion failed (exit code {returncode})", error=True)
            if output_lines:
                _print("[dim]Last output:[/dim]")
                for line in output_lines[-10:]:
                    _print(f"  {line}")
            return 1

    except KeyboardInterrupt:
        _print("\n[yellow]Interrupted[/yellow]")
        return 130
    except Exception as e:
        _print(f"[red]Error:[/red] {e}", error=True)
        return 1


def register_command(subparsers):
    """Register the history command with the CLI argument parser."""
    parser = subparsers.add_parser(
        "history",
        help="Ingest git commit history into Qdrant",
        description="Index git commit messages and file lists for semantic search.\n\n"
                    "Enables searching your repository's history semantically to find\n"
                    "when and why code was changed.",
        epilog="""
Examples:
  ctx history                           # Ingest last 200 commits
  ctx history --max-commits 500         # Ingest last 500 commits
  ctx history --since "1 year ago"      # Commits from last year
  ctx history --since "2024-01-01"      # Commits since date
  ctx history /path/to/repo             # Specific repository
  ctx history --local                   # Run locally (no docker)
"""
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Git repository path (default: current directory)"
    )

    parser.add_argument(
        "--max-commits", "-n",
        type=int,
        default=200,
        help="Maximum number of commits to ingest (default: 200)"
    )

    parser.add_argument(
        "--since", "-s",
        help="Only commits after this date (e.g., '1 year ago', '2024-01-01')"
    )

    parser.add_argument(
        "--collection", "-c",
        help="Target collection name (default: auto-detect)"
    )

    parser.add_argument(
        "--local", "-l",
        action="store_true",
        help="Run locally instead of via docker compose"
    )

    def run_history(args):
        """Wrapper to call history function with argparse args."""
        return history(
            path=args.path,
            max_commits=args.max_commits,
            since=args.since,
            collection=args.collection,
            local=args.local,
        )

    parser.set_defaults(func=run_history)
