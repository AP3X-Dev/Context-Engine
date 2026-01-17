"""
Prune command for ctx CLI - Remove stale entries from Qdrant index.

Removes entries for:
- Deleted files (no longer exist on disk)
- Hash mismatches (file content changed since last index)
"""

import re
import sys
import time
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError

console = Console()


def prune(
    collection: Optional[str] = None,
    dry_run: bool = False,
):
    """
    Remove stale entries from index (deleted files, hash mismatches).

    Scans the collection and removes entries for:
    - Files that no longer exist on disk
    - Files with content changes (hash mismatches)
    - Associated graph edges for removed files

    Examples:
        ctx prune                 # Prune default collection
        ctx prune -c my-repo      # Prune specific collection
        ctx prune --dry-run       # Preview without removing
    """
    # Note: dry-run is not currently supported by the MCP tool
    # but we accept the flag for future compatibility
    if dry_run:
        console.print(
            Panel(
                "[yellow]Warning:[/yellow] --dry-run is not yet implemented by the backend.\n"
                "The command will run normally and remove stale entries.",
                title="Dry Run Not Available",
                border_style="yellow",
            )
        )
        # Ask for confirmation
        response = console.input("[bold]Continue with actual pruning?[/bold] [dim](y/N)[/dim] ")
        if response.lower() not in ("y", "yes"):
            console.print("[dim]Cancelled[/dim]")
            sys.exit(0)

    # Create MCP client
    try:
        client = MCPClient(server="indexer")
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to initialize MCP client: {e}")
        sys.exit(1)

    # Build parameters
    params = {}
    if collection:
        params["collection"] = collection

    # Show start message
    console.print(
        Panel(
            f"[cyan]Collection:[/cyan] {collection or 'auto-detect'}\n"
            f"[dim]Scanning for stale entries...[/dim]",
            title="Pruning Index",
            border_style="cyan",
        )
    )

    # Call MCP tool with progress display
    start_time = time.time()

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Scanning index...", total=None)

            result = client.call_tool("qdrant_prune", **params)

            progress.update(task, completed=True)

    except MCPError as e:
        console.print(f"[red]Error:[/red] MCP call failed: {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Unexpected error: {e}")
        sys.exit(1)

    elapsed = time.time() - start_time

    # Check if operation succeeded
    if not result.get("ok", False):
        error_msg = result.get("stderr", result.get("error", "Unknown error"))
        console.print(f"[red]Pruning failed:[/red] {error_msg}")
        sys.exit(1)

    # Parse output from prune.py
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")

    # Extract statistics from stdout
    # Looking for lines like:
    # [prune] removed missing file points: /work/path/to/file.py
    # [prune] removed outdated points (hash mismatch): /work/path/to/file.py
    # Prune complete. removed_missing=15, removed_mismatch=3, removed_graph_edges=42

    removed_files = []
    removed_missing = 0
    removed_mismatch = 0
    removed_graph_edges = 0

    # Parse individual file removals
    for line in stdout.split("\n"):
        if "[prune] removed missing file points:" in line:
            # Extract file path
            match = re.search(r"points: (.+)$", line)
            if match:
                removed_files.append(("deleted", match.group(1).strip()))
        elif "[prune] removed outdated points (hash mismatch):" in line:
            # Extract file path
            match = re.search(r"mismatch\): (.+)$", line)
            if match:
                removed_files.append(("hash mismatch", match.group(1).strip()))

    # Parse summary line
    summary_match = re.search(
        r"removed_missing=(\d+), removed_mismatch=(\d+), removed_graph_edges=(\d+)",
        stdout,
    )
    if summary_match:
        removed_missing = int(summary_match.group(1))
        removed_mismatch = int(summary_match.group(2))
        removed_graph_edges = int(summary_match.group(3))

    total_removed = removed_missing + removed_mismatch

    # Display results
    if total_removed == 0:
        console.print(
            Panel(
                "[green]✓[/green] No stale entries found\n"
                "[dim]Index is clean[/dim]",
                title="Pruning Complete",
                border_style="green",
            )
        )
    else:
        # Create summary table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Category", style="cyan")
        table.add_column("Count", justify="right", style="yellow")

        table.add_row("Deleted files", str(removed_missing))
        table.add_row("Hash mismatches", str(removed_mismatch))
        table.add_row("Graph edges", str(removed_graph_edges))
        table.add_row("[bold]Total entries", f"[bold]{total_removed}")

        console.print(
            Panel(
                table,
                title=f"[green]✓[/green] Pruned in {elapsed:.1f}s",
                border_style="green",
            )
        )

        # Show affected files if not too many
        if removed_files and len(removed_files) <= 20:
            console.print("\n[dim]Removed entries:[/dim]")
            for reason, path in removed_files:
                if reason == "deleted":
                    console.print(f"  [red]✗[/red] [dim]{path}[/dim] (deleted)")
                else:
                    console.print(f"  [yellow]△[/yellow] [dim]{path}[/dim] (outdated)")
        elif len(removed_files) > 20:
            console.print(
                f"\n[dim]Removed {len(removed_files)} entries (showing first 10):[/dim]"
            )
            for reason, path in removed_files[:10]:
                if reason == "deleted":
                    console.print(f"  [red]✗[/red] [dim]{path}[/dim] (deleted)")
                else:
                    console.print(f"  [yellow]△[/yellow] [dim]{path}[/dim] (outdated)")
            console.print(f"  [dim]... and {len(removed_files) - 10} more[/dim]")

    # Show any warnings/errors from stderr
    if stderr and stderr.strip():
        console.print(f"\n[yellow]Warnings:[/yellow]\n{stderr}")


def register_command(subparsers):
    """Register the prune command with the CLI argument parser.

    Args:
        subparsers: argparse subparsers object
    """
    parser = subparsers.add_parser(
        "prune",
        help="Remove stale entries from index",
        description="Remove stale index entries for deleted files and hash mismatches",
    )

    parser.add_argument(
        "--collection",
        "-c",
        help="Target collection name (default: auto-detect from workspace)",
    )

    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be pruned without removing (not yet implemented)",
    )

    # Set the function to be called when this command is invoked
    def run_prune(args):
        """Wrapper to call prune function with argparse args."""
        prune(collection=args.collection, dry_run=args.dry_run)
        return 0

    parser.set_defaults(func=run_prune)
