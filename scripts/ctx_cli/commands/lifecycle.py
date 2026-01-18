#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Lifecycle management commands for Context-Engine services.

Commands for starting, stopping, and restarting MCP servers.
"""

import time
import sys

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None
    Table = None
    Live = None

from scripts.ctx_cli.utils.docker import (
    run_docker_compose,
    wait_for_health_check,
)
from scripts.ctx_cli.utils.config import get_health_checks

console = Console() if RICH_AVAILABLE else None


def _print(msg: str, style: str = None) -> None:
    """Print with Rich if available, otherwise plain print."""
    if console:
        console.print(msg)
    else:
        import re
        plain = re.sub(r'\[/?[^\]]+\]', '', msg)
        print(plain)


def run_up(args) -> int:
    """
    Start Context-Engine services.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    _print("\n[bold blue]Starting Context-Engine services...[/bold blue]\n")

    # Build docker compose command
    compose_args = ["-d"]
    if args.build:
        compose_args.append("--build")

    # Handle --no-llama flag
    no_llama = getattr(args, "no_llama", False)
    if no_llama:
        compose_args.extend(["--scale", "llamacpp=0"])
        _print("[dim]Skipping local LLM container (--no-llama)[/dim]\n")

    try:
        # Start services
        run_docker_compose("up", *compose_args)

        # Wait for health checks with spinner
        _print("[dim]Waiting for services to become healthy...[/dim]\n")

        start_time = time.time()
        results = {}

        if RICH_AVAILABLE and console:
            # Rich mode: use live table
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("Status", style="bold")
            table.add_column("Service", style="cyan")
            table.add_column("Info", style="dim")

            with Live(table, console=console, refresh_per_second=4) as live:
                for service in get_health_checks():
                    name = service["name"]
                    port = service["port"]
                    host = service["host"]

                    # Update table with spinner
                    table.rows.clear()
                    for prev_name, prev_result in results.items():
                        status = "[green]✓[/green]" if prev_result["success"] else "[red]✗[/red]"
                        info = f"port {prev_result['port']}"
                        table.add_row(status, f"{prev_name}:", info)

                    # Add current service with spinner
                    table.add_row("[yellow]◉[/yellow]", f"{name}:", f"checking port {port}")
                    live.update(table)

                    # Perform health check
                    success, elapsed = wait_for_health_check(
                        host=host,
                        port=port,
                        timeout=float(args.wait),
                        check_interval=0.5,
                    )

                    results[name] = {
                        "success": success,
                        "elapsed": elapsed,
                        "port": port,
                    }

                # Final table update
                table.rows.clear()
                for name, result in results.items():
                    status = "[green]✓[/green]" if result["success"] else "[red]✗[/red]"
                    info = f"port {result['port']}"
                    table.add_row(status, f"{name}:", info)
        else:
            # Plain mode: simple output
            for service in get_health_checks():
                name = service["name"]
                port = service["port"]
                host = service["host"]

                print(f"  Checking {name} (port {port})...", end=" ", flush=True)

                success, elapsed = wait_for_health_check(
                    host=host,
                    port=port,
                    timeout=float(args.wait),
                    check_interval=0.5,
                )

                results[name] = {
                    "success": success,
                    "elapsed": elapsed,
                    "port": port,
                }

                status_char = "OK" if success else "FAILED"
                print(status_char)

        total_elapsed = time.time() - start_time

        # Check if all succeeded
        all_success = all(r["success"] for r in results.values())

        if all_success:
            _print(f"\n[green]✓[/green] [bold green]Ready in {total_elapsed:.1f}s[/bold green]\n")
            return 0
        else:
            _print(f"\n[red]✗[/red] [bold red]Some services failed to start[/bold red]\n")
            failed = [name for name, r in results.items() if not r["success"]]
            _print(f"[red]Failed services:[/red] {', '.join(failed)}\n")
            return 1

    except Exception as e:
        _print(f"\n[red]Error starting services:[/red] {e}\n")
        return 1


def run_down(args) -> int:
    """
    Stop Context-Engine services.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    _print("\n[bold blue]Stopping Context-Engine services...[/bold blue]\n")

    compose_args = []
    if args.volumes:
        compose_args.append("-v")
        _print("[yellow]Warning:[/yellow] This will remove all data volumes\n")

    try:
        run_docker_compose("down", *compose_args)
        _print("[green]✓[/green] [bold green]Services stopped successfully[/bold green]\n")
        return 0

    except Exception as e:
        _print(f"\n[red]Error stopping services:[/red] {e}\n")
        return 1


def run_restart(args) -> int:
    """
    Restart Context-Engine services.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    _print("\n[bold blue]Restarting Context-Engine services...[/bold blue]\n")

    try:
        # Stop services
        _print("[dim]Stopping services...[/dim]")
        run_docker_compose("down")

        # Small delay to ensure clean shutdown
        time.sleep(1)

        # Start services
        _print("[dim]Starting services...[/dim]\n")
        return run_up(args)

    except Exception as e:
        _print(f"\n[red]Error restarting services:[/red] {e}\n")
        return 1


def register_command(subparsers):
    """Register lifecycle commands with the CLI parser."""

    # Up command
    parser_up = subparsers.add_parser(
        "up",
        help="Start Context-Engine services",
        description="Start all services using docker compose and wait for health checks"
    )
    parser_up.add_argument(
        "--build",
        action="store_true",
        help="Rebuild containers before starting"
    )
    parser_up.add_argument(
        "--wait",
        type=int,
        default=30,
        help="Health check timeout in seconds (default: 30)"
    )
    parser_up.add_argument(
        "--no-llama",
        action="store_true",
        help="Skip the local LLM container (llamacpp)"
    )
    parser_up.set_defaults(func=run_up)

    # Down command
    parser_down = subparsers.add_parser(
        "down",
        help="Stop Context-Engine services",
        description="Stop all services and optionally remove volumes"
    )
    parser_down.add_argument(
        "--volumes",
        action="store_true",
        help="Remove volumes too"
    )
    parser_down.set_defaults(func=run_down)

    # Restart command
    parser_restart = subparsers.add_parser(
        "restart",
        help="Restart Context-Engine services",
        description="Stop and then start all services"
    )
    parser_restart.add_argument(
        "--build",
        action="store_true",
        help="Rebuild containers"
    )
    parser_restart.add_argument(
        "--wait",
        type=int,
        default=30,
        help="Health check timeout in seconds (default: 30)"
    )
    parser_restart.add_argument(
        "--no-llama",
        action="store_true",
        help="Skip the local LLM container (llamacpp)"
    )
    parser_restart.set_defaults(func=run_restart)
