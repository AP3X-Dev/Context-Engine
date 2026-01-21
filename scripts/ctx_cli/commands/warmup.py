#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Warmup command for Context-Engine CLI.

Preloads embedding and reranker models to reduce first-query latency.

Usage:
    ctx warmup                  # Check status and trigger warmup if needed
    ctx warmup --status         # Just show current cache status
    ctx warmup --force          # Force warmup even if already cached
"""

import sys
import time
from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


def get_warmup_status() -> dict:
    """
    Call the MCP warmup_status tool to check current cache state.

    Returns:
        Dict with warmup status info
    """
    try:
        client = MCPClient(server="indexer", timeout=10)
        return client.call_tool("warmup_status")
    except MCPError as e:
        return {
            "ok": False,
            "error": f"MCP call failed: {str(e)}",
            "status": "unknown"
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to get warmup status: {str(e)}",
            "status": "unknown"
        }


def trigger_warmup() -> dict:
    """
    Trigger warmup by calling a simple search query.

    This forces the models to load if they haven't already.
    Since there's no dedicated warmup trigger tool, we use a dummy search.

    Returns:
        Dict with warmup result
    """
    try:
        client = MCPClient(server="indexer", timeout=60)

        # Trigger warmup by making a simple search query
        # This forces the embedding model and reranker to load
        result = client.call_tool(
            "repo_search",
            query="warmup probe",
            limit=1,
            compact=True
        )

        return {
            "ok": True,
            "triggered": True
        }
    except MCPError as e:
        return {
            "ok": False,
            "error": f"Failed to trigger warmup: {str(e)}"
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to trigger warmup: {str(e)}"
        }


def format_status_rich(status: dict, console: Console) -> None:
    """
    Format and display warmup status using Rich.

    Args:
        status: Warmup status dict
        console: Rich Console instance
    """
    warmup_state = status.get("status", "unknown")

    # Determine status color and symbol
    if warmup_state == "warm":
        color = "green"
        symbol = "✓"
        title = "Models Warmed Up"
    elif warmup_state == "warming":
        color = "yellow"
        symbol = "⟳"
        title = "Models Warming"
    elif warmup_state == "cold":
        color = "blue"
        symbol = "○"
        title = "Models Cold"
    elif warmup_state == "failed":
        color = "red"
        symbol = "✗"
        title = "Warmup Failed"
    else:
        color = "dim"
        symbol = "?"
        title = "Status Unknown"

    # Create table with warmup metrics
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="cyan")
    table.add_column("Value")

    # Status
    table.add_row("Status", f"[{color}]{symbol} {warmup_state.upper()}[/{color}]")

    # Timing metrics
    if warmup_state == "warm":
        embedding_ms = status.get("embedding_ms")
        reranker_ms = status.get("reranker_ms")
        total_ms = status.get("total_ms") or status.get("latency_ms")

        if embedding_ms is not None:
            table.add_row("Embedding", f"{embedding_ms:.1f}ms")
        if reranker_ms is not None:
            table.add_row("Reranker", f"{reranker_ms:.1f}ms")
        if total_ms is not None:
            table.add_row("Total", f"[bold]{total_ms:.1f}ms[/bold]")

        # Add helpful context
        console.print(Panel(
            table,
            title=title,
            border_style=color,
            padding=(1, 2)
        ))

        # Show additional info about benefits
        console.print()
        console.print("[dim]First-query latency reduced by model preloading[/dim]")
    else:
        # Error message
        if warmup_state == "failed" and "error" in status:
            table.add_row("Error", f"[red]{status['error']}[/red]")

        console.print(Panel(
            table,
            title=title,
            border_style=color,
            padding=(1, 2)
        ))


def format_status_plain(status: dict) -> str:
    """
    Format warmup status as plain text.

    Args:
        status: Warmup status dict

    Returns:
        Formatted status string
    """
    lines = []
    separator = "=" * 50

    warmup_state = status.get("status", "unknown").upper()

    lines.append(separator)
    lines.append(f"Warmup Status: {warmup_state}")
    lines.append(separator)

    if warmup_state == "WARM":
        embedding_ms = status.get("embedding_ms")
        reranker_ms = status.get("reranker_ms")
        total_ms = status.get("total_ms") or status.get("latency_ms")

        if embedding_ms is not None:
            lines.append(f"  Embedding: {embedding_ms:.1f}ms")
        if reranker_ms is not None:
            lines.append(f"  Reranker:  {reranker_ms:.1f}ms")
        if total_ms is not None:
            lines.append(f"  Total:     {total_ms:.1f}ms")
    elif warmup_state == "FAILED" and "error" in status:
        lines.append(f"  Error: {status['error']}")

    lines.append(separator)

    return "\n".join(lines)


def warmup_command(
    status_only: bool = False,
    force: bool = False
) -> int:
    """
    Execute the warmup command.

    Args:
        status_only: Just show status without triggering warmup
        force: Force warmup even if already cached

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    console = Console() if RICH_AVAILABLE else None

    # Check current status
    if console and not status_only:
        console.print("[cyan]Checking warmup status...[/cyan]")

    status = get_warmup_status()

    # Handle errors
    if not status.get("ok", True) and "error" in status:
        if console:
            console.print(f"[red]Error:[/red] {status['error']}")
        else:
            print(f"Error: {status['error']}", file=sys.stderr)

        # Check if this is due to missing warmup endpoint
        if "warmup_status" in status.get("error", "").lower():
            msg = (
                "The warmup_status tool is not available.\n"
                "This may be an older server version.\n"
                "Try updating the server or checking if it's running."
            )
            if console:
                console.print(f"[yellow]{msg}[/yellow]")
            else:
                print(msg, file=sys.stderr)

        return 1

    warmup_state = status.get("status", "unknown")

    # If status-only mode, just display and exit
    if status_only:
        if console:
            format_status_rich(status, console)
        else:
            print(format_status_plain(status))
        return 0

    # Display current status
    if console:
        format_status_rich(status, console)
        console.print()
    else:
        print(format_status_plain(status))
        print()

    # Decide if we need to warmup
    needs_warmup = force or warmup_state in ("cold", "failed", "unknown")

    if not needs_warmup:
        if console:
            console.print("[green]Models already warmed up. Use --force to warmup again.[/green]")
        else:
            print("Models already warmed up. Use --force to warmup again.")
        return 0

    # Trigger warmup
    if console:
        console.print("[cyan]Triggering warmup...[/cyan]")
        console.print("[dim]This may take a few seconds on first run[/dim]")
        console.print()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Warming up models...", total=None)

            start_time = time.time()
            result = trigger_warmup()
            elapsed = time.time() - start_time

            progress.update(task, completed=True)
    else:
        print("Triggering warmup...")
        print("This may take a few seconds on first run")

        start_time = time.time()
        result = trigger_warmup()
        elapsed = time.time() - start_time

    # Check result
    if not result.get("ok", False):
        error_msg = result.get("error", "Unknown error")
        if console:
            console.print(f"[red]Warmup failed:[/red] {error_msg}")
        else:
            print(f"Warmup failed: {error_msg}", file=sys.stderr)
        return 1

    # Get updated status
    if console:
        console.print()
        console.print("[cyan]Checking final status...[/cyan]")

    time.sleep(0.5)  # Brief pause to let warmup complete
    final_status = get_warmup_status()

    if console:
        console.print()
        format_status_rich(final_status, console)

        if final_status.get("status") == "warm":
            console.print()
            console.print(f"[green]✓ Warmup completed in {elapsed:.1f}s[/green]")
    else:
        print()
        print(format_status_plain(final_status))

        if final_status.get("status") == "warm":
            print()
            print(f"✓ Warmup completed in {elapsed:.1f}s")

    return 0


def run_warmup(args):
    """
    Entry point for argparse command execution.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code
    """
    return warmup_command(
        status_only=args.status,
        force=args.force
    )


def register_command(subparsers):
    """Register the warmup command with the CLI parser."""
    parser = subparsers.add_parser(
        "warmup",
        help="Preload models to reduce first-query latency",
        description="Warm up embedding and reranker models by preloading them into memory. "
                    "This reduces the latency of the first query after server startup.",
        epilog="""
Examples:
  ctx warmup              # Check status and warmup if needed
  ctx warmup --status     # Just show current cache status
  ctx warmup --force      # Force warmup even if already cached
        """
    )

    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Just show warmup status without triggering warmup"
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force warmup even if models are already cached"
    )

    parser.set_defaults(func=run_warmup)
