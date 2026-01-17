#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Quickstart command for Context-Engine CLI.

The ONE COMMAND to rule them all - sets up and starts everything.

Usage:
    ctx quickstart [OPTIONS]

This command orchestrates:
    1. Environment detection and configuration (init)
    2. Docker service startup (up)
    3. Service health checks
    4. Initial codebase indexing (index)
    5. Model warmup for optimal performance (warmup)
"""

import sys
import time
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.live import Live

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError
from scripts.ctx_cli.utils.docker import (
    run_docker_compose,
    wait_for_health_check,
)
from scripts.ctx_cli.commands.init import (
    check_existing_config,
    find_docker_compose,
    suggest_collection_name,
)

console = Console()

# Service health check configuration
HEALTH_CHECKS = [
    {"name": "Qdrant", "port": 6333, "host": "localhost"},
    {"name": "Indexer", "port": 8003, "host": "localhost"},
    {"name": "Memory", "port": 8002, "host": "localhost"},
]


def check_docker_available() -> tuple[bool, str]:
    """
    Check if Docker and Docker Compose are available.

    Returns:
        (is_available, error_message)
    """
    import subprocess

    try:
        # Check docker
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, "Docker is not installed or not running"

        # Check docker compose
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, "Docker Compose is not installed"

        return True, ""

    except subprocess.TimeoutExpired:
        return False, "Docker command timed out - is Docker running?"
    except FileNotFoundError:
        return False, "Docker is not installed"
    except Exception as e:
        return False, f"Error checking Docker: {str(e)}"


def check_docker_compose_file() -> tuple[bool, Optional[Path]]:
    """
    Check if docker-compose.yml exists.

    Returns:
        (exists, path)
    """
    compose_path = find_docker_compose()
    if compose_path:
        return True, compose_path
    return False, None


def load_env_file(env_path: Path) -> dict:
    """
    Load a .env file and return key-value pairs.

    Args:
        env_path: Path to .env file

    Returns:
        Dictionary of environment variables
    """
    env_vars = {}
    if not env_path.exists():
        return env_vars

    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Remove quotes if present
                    if value and value[0] in ('"', "'") and value[-1] == value[0]:
                        value = value[1:-1]
                    env_vars[key] = value
    except Exception:
        pass

    return env_vars


def step_init(force: bool, skip_interactive: bool) -> int:
    """
    Step 1: Initialize configuration.

    Args:
        force: Force overwrite of existing config
        skip_interactive: Skip interactive wizard if config exists

    Returns:
        Exit code (0 for success)
    """
    console.print(Panel(
        "[bold cyan]Step 1: Environment Setup[/bold cyan]",
        border_style="cyan"
    ))

    # Check if config already exists
    exists, config_path = check_existing_config(global_mode=False)

    if exists and not force:
        if skip_interactive:
            console.print(f"[green]✓[/green] Using existing configuration: {config_path}\n")
            return 0
        else:
            console.print(f"[yellow]![/yellow] Configuration already exists: {config_path}")
            console.print("[dim]Use --force to overwrite or skip this step[/dim]\n")
            return 0

    # For quickstart, we do a simplified non-interactive setup
    console.print("[dim]Detecting environment...[/dim]")

    # Check for docker-compose.yml
    has_compose, compose_path = check_docker_compose_file()

    if not has_compose:
        console.print("[red]✗[/red] docker-compose.yml not found in current or parent directories")
        console.print("\n[yellow]Please run this from the Context-Engine directory or run:[/yellow]")
        console.print("  [cyan]ctx init[/cyan]  # Interactive setup wizard")
        return 1

    console.print(f"[green]✓[/green] Found docker-compose.yml: {compose_path}")

    # Auto-detect workspace
    workspace_path = Path.cwd()

    # PRIORITY ORDER for COLLECTION_NAME:
    # 1. Already set in environment (from shell or parent process)
    # 2. From .env file in workspace
    # 3. Fall back to suggest_collection_name()
    collection_name = os.environ.get("COLLECTION_NAME")

    if not collection_name:
        # Try loading from .env file
        env_path = workspace_path / ".env"
        if env_path.exists():
            env_vars = load_env_file(env_path)
            collection_name = env_vars.get("COLLECTION_NAME")
            if collection_name:
                console.print(f"[green]✓[/green] Loaded COLLECTION_NAME from .env")

    if not collection_name:
        # Fall back to generating a name
        collection_name = suggest_collection_name(workspace_path)
        console.print(f"[yellow]![/yellow] No COLLECTION_NAME found, using: {collection_name}")

    console.print(f"[green]✓[/green] Workspace: {workspace_path}")
    console.print(f"[green]✓[/green] Collection: {collection_name}")

    # Set environment variables for this session
    os.environ["COLLECTION_NAME"] = collection_name
    os.environ["WORKSPACE_PATH"] = str(workspace_path)

    console.print("[green]✓[/green] Environment configured\n")
    return 0


def step_up(build: bool, wait_timeout: int) -> int:
    """
    Step 2: Start Docker services.

    Args:
        build: Rebuild containers
        wait_timeout: Health check timeout

    Returns:
        Exit code (0 for success)
    """
    console.print(Panel(
        "[bold cyan]Step 2: Starting Services[/bold cyan]",
        border_style="cyan"
    ))

    # Build docker compose command
    compose_args = ["-d"]
    if build:
        compose_args.append("--build")
        console.print("[dim]Rebuilding containers...[/dim]")

    try:
        # Start services (quiet=True suppresses docker compose warnings)
        run_docker_compose("up", *compose_args, quiet=True)

        # Wait for health checks with spinner
        console.print("[dim]Waiting for services to become healthy...[/dim]\n")

        start_time = time.time()
        results = {}

        def create_status_table(results: dict, current_service: str = None, current_port: int = None) -> Table:
            """Create a fresh status table with current results."""
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("Status", style="bold")
            table.add_column("Service", style="cyan")
            table.add_column("Info", style="dim")

            for name, result in results.items():
                status = "[green]✓[/green]" if result["success"] else "[red]✗[/red]"
                info = f"port {result['port']}"
                table.add_row(status, f"{name}:", info)

            if current_service:
                table.add_row("[yellow]◉[/yellow]", f"{current_service}:", f"checking port {current_port}")

            return table

        with Live(create_status_table(results), console=console, refresh_per_second=4) as live:
            for service in HEALTH_CHECKS:
                name = service["name"]
                port = service["port"]
                host = service["host"]

                # Update display with current service being checked
                live.update(create_status_table(results, name, port))

                # Perform health check
                success, elapsed = wait_for_health_check(
                    host=host,
                    port=port,
                    timeout=float(wait_timeout),
                    check_interval=0.5,
                )

                results[name] = {
                    "success": success,
                    "elapsed": elapsed,
                    "port": port,
                }

            # Final table update
            live.update(create_status_table(results))

        total_elapsed = time.time() - start_time

        # Check if all succeeded
        all_success = all(r["success"] for r in results.values())

        if all_success:
            console.print(f"\n[green]✓[/green] All services healthy in {total_elapsed:.1f}s\n")
            return 0
        else:
            console.print(f"\n[red]✗[/red] Some services failed to start\n")
            failed = [name for name, r in results.items() if not r["success"]]
            console.print(f"[red]Failed services:[/red] {', '.join(failed)}")
            console.print("\n[yellow]Try running:[/yellow]")
            console.print("  [cyan]docker compose logs[/cyan]  # View logs")
            console.print("  [cyan]ctx quickstart --build[/cyan]  # Rebuild containers")
            return 1

    except Exception as e:
        console.print(f"\n[red]Error starting services:[/red] {e}\n")
        return 1


def step_index(skip_index: bool, recreate: bool) -> int:
    """
    Step 3: Index the codebase.

    SAFE: Only indexes if collection is empty or --recreate is explicitly set.

    Args:
        skip_index: Skip indexing step
        recreate: Recreate collection (user explicitly requested)

    Returns:
        Exit code (0 for success)
    """
    if skip_index:
        console.print(Panel(
            "[bold cyan]Step 3: Indexing[/bold cyan]\n[yellow]Skipped (--no-index)[/yellow]",
            border_style="cyan"
        ))
        return 0

    console.print(Panel(
        "[bold cyan]Step 3: Indexing Codebase[/bold cyan]",
        border_style="cyan"
    ))

    workspace_path = Path.cwd()
    start_time = time.time()

    try:
        client = MCPClient(server="indexer", timeout=600)

        # SAFE: First check existing collections (READ-ONLY)
        console.print(f"[dim]Checking {workspace_path}...[/dim]\n")

        existing_collection = None
        existing_count = 0

        # Get the configured collection name from environment
        configured_collection = os.environ.get("COLLECTION_NAME")

        try:
            # PRIORITY: Check the configured collection FIRST (with retry for transient failures)
            if configured_collection:
                for attempt in range(3):
                    try:
                        stats = client.call_tool("qdrant_status", collection=configured_collection)
                        count = stats.get("count", 0)
                        if count > 0:
                            existing_collection = configured_collection
                            existing_count = count
                        break  # Success, exit retry loop
                    except Exception as e:
                        if attempt < 2:
                            time.sleep(1)  # Brief pause before retry
                            continue
                        pass  # Collection might not exist yet

            # Fallback: scan all collections if configured one is empty/missing
            if not existing_collection or existing_count == 0:
                collections_result = client.call_tool("qdrant_list")
                collections = collections_result.get("collections", [])

                # Find collection with data (skip _graph collections)
                for coll in collections:
                    if coll.endswith("_graph"):
                        continue
                    try:
                        stats = client.call_tool("qdrant_status", collection=coll)
                        count = stats.get("count", 0)
                        if count > existing_count:
                            existing_count = count
                            existing_collection = coll
                    except Exception:
                        continue
        except Exception:
            pass

        # If data exists and user didn't pass --recreate, just show stats
        if existing_collection and existing_count > 0 and not recreate:
            elapsed = time.time() - start_time
            console.print(
                f"[green]✓[/green] Codebase already indexed - [cyan]{existing_count:,}[/cyan] chunks"
            )
            console.print(f"  [dim]Collection: {existing_collection}[/dim]")
            console.print(f"  [dim]Use --recreate to reindex ({elapsed:.1f}s)[/dim]\n")
            return 0

        # Only index if collection is empty OR user explicitly requested --recreate
        if recreate:
            console.print("[yellow]Recreating index (--recreate)...[/yellow]\n")
        else:
            console.print("[dim]No existing index found, creating new index...[/dim]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Indexing files...", total=None)

            # Call MCP indexing tool - let indexer auto-detect collection
            result = client.call_tool(
                "qdrant_index_root",
                recreate=recreate,
            )

            progress.update(task, completed=True)

        elapsed = time.time() - start_time

        # Check for errors
        if "error" in result or not result.get("ok", False):
            error_msg = result.get("error", "Unknown error")
            console.print(f"\n[red]✗[/red] Indexing failed: {error_msg}\n")
            return 1

        # Extract statistics
        total_files = result.get("total_files", 0)
        changed_files = result.get("changed", 0)
        deleted_files = result.get("deleted", 0)
        skipped_files = result.get("skipped", 0)

        # Display results
        if total_files > 0 or changed_files > 0:
            console.print(
                f"[green]✓[/green] Indexed [cyan]{total_files:,}[/cyan] files in [cyan]{elapsed:.1f}s[/cyan]"
            )
            console.print(f"  Changed: [yellow]{changed_files}[/yellow]  "
                         f"Deleted: [red]{deleted_files}[/red]  "
                         f"Skipped: [dim]{skipped_files}[/dim]\n")
        else:
            console.print(
                f"[green]✓[/green] Index check complete in [cyan]{elapsed:.1f}s[/cyan]\n"
            )

        return 0

    except MCPError as e:
        console.print(f"\n[red]✗[/red] MCP error: {e.message}\n")
        console.print("[yellow]Services may not be fully ready. Try:[/yellow]")
        console.print("  [cyan]ctx status[/cyan]  # Check service status")
        return 1
    except Exception as e:
        console.print(f"\n[red]✗[/red] Indexing failed: {str(e)}\n")
        return 1


def step_warmup(skip_warmup: bool) -> int:
    """
    Step 4: Warm up models.

    Args:
        skip_warmup: Skip warmup step

    Returns:
        Exit code (0 for success)
    """
    if skip_warmup:
        console.print(Panel(
            "[bold cyan]Step 4: Model Warmup[/bold cyan]\n[yellow]Skipped (--no-warmup)[/yellow]",
            border_style="cyan"
        ))
        return 0

    console.print(Panel(
        "[bold cyan]Step 4: Model Warmup[/bold cyan]",
        border_style="cyan"
    ))

    console.print("[dim]Preloading embedding and reranking models...[/dim]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Warming up models...", total=None)

            # Call warmup status to check current state
            client = MCPClient(server="indexer", timeout=60)
            status = client.call_tool("warmup_status")

            progress.update(task, completed=True)

        # Check warmup status
        warmup_status = status.get("status", "unknown")
        latency_ms = status.get("latency_ms") or status.get("total_ms")

        if warmup_status == "warm":
            console.print(f"[green]✓[/green] Models already warm (latency: {latency_ms:.1f}ms)\n")
            return 0
        elif warmup_status == "warming":
            console.print("[yellow]![/yellow] Models are currently warming up...\n")
            # Wait a bit and check again
            time.sleep(2)
            status = client.call_tool("warmup_status")
            warmup_status = status.get("status", "unknown")
            latency_ms = status.get("latency_ms") or status.get("total_ms")

            if warmup_status == "warm":
                console.print(f"[green]✓[/green] Models warmed up (latency: {latency_ms:.1f}ms)\n")
                return 0

        # Models should be auto-warmed by the server on startup
        # If still cold, that's okay - they'll warm on first use
        if warmup_status == "cold":
            console.print("[yellow]![/yellow] Models will warm up on first use\n")
            return 0

        if warmup_status == "failed":
            error = status.get("error", "Unknown error")
            console.print(f"[yellow]![/yellow] Warmup failed: {error}")
            console.print("[dim]Models will still work, but first query may be slower[/dim]\n")
            return 0

        console.print(f"[green]✓[/green] Models ready\n")
        return 0

    except MCPError as e:
        console.print(f"[yellow]![/yellow] Could not check warmup status: {e.message}")
        console.print("[dim]Models will warm up on first use[/dim]\n")
        return 0
    except Exception as e:
        console.print(f"[yellow]![/yellow] Warmup check failed: {str(e)}")
        console.print("[dim]Models will warm up on first use[/dim]\n")
        return 0


def run_quickstart(args) -> int:
    """
    Run the quickstart command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Context-Engine Quickstart[/bold cyan]\n"
        "[dim]The ONE COMMAND to rule them all[/dim]",
        border_style="cyan"
    ))
    console.print()

    # Pre-flight checks
    console.print("[bold]Pre-flight Checks[/bold]")
    console.print()

    # Check Docker
    docker_ok, docker_error = check_docker_available()
    if not docker_ok:
        console.print(f"[red]✗[/red] Docker check failed: {docker_error}")
        console.print("\n[yellow]Please install Docker Desktop and ensure it's running:[/yellow]")
        console.print("  https://www.docker.com/products/docker-desktop")
        return 1
    console.print("[green]✓[/green] Docker available")

    # Check docker-compose.yml
    has_compose, compose_path = check_docker_compose_file()
    if not has_compose:
        console.print("[red]✗[/red] docker-compose.yml not found")
        console.print("\n[yellow]Please run this from the Context-Engine directory[/yellow]")
        return 1
    console.print(f"[green]✓[/green] Found {compose_path}")
    console.print()

    # Execute steps
    steps = [
        ("init", lambda: step_init(args.force, skip_interactive=True)),
        ("up", lambda: step_up(args.build, args.wait)),
        ("index", lambda: step_index(args.no_index, args.recreate)),
        ("warmup", lambda: step_warmup(args.no_warmup)),
    ]

    for step_name, step_func in steps:
        try:
            exit_code = step_func()
            if exit_code != 0:
                console.print(Panel(
                    f"[red]Quickstart failed at step: {step_name}[/red]\n\n"
                    f"You can continue from this point by running:\n"
                    f"  [cyan]ctx {step_name}[/cyan]  # Run this step manually\n\n"
                    f"Or debug with:\n"
                    f"  [cyan]ctx status[/cyan]  # Check service status\n"
                    f"  [cyan]docker compose logs[/cyan]  # View logs",
                    title=f"Failed at Step: {step_name}",
                    border_style="red"
                ))
                return exit_code
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Quickstart interrupted by user[/yellow]")
            return 1
        except Exception as e:
            console.print(f"\n[red]Unexpected error in step {step_name}:[/red] {e}")
            import traceback
            traceback.print_exc()
            return 1

    # Success!
    console.print()
    console.print(Panel.fit(
        "[bold green]✓ Quickstart Complete![/bold green]\n\n"
        "[cyan]Context-Engine is ready to use[/cyan]\n\n"
        "Try these commands:\n"
        "  [cyan]ctx search 'your query'[/cyan]  # Search your codebase\n"
        "  [cyan]ctx answer 'how does X work?'[/cyan]  # Ask questions\n"
        "  [cyan]ctx status[/cyan]  # Check system status\n"
        "  [cyan]ctx --help[/cyan]  # See all commands",
        border_style="green"
    ))
    console.print()

    return 0


def register_command(subparsers):
    """Register the quickstart command with the CLI parser."""
    parser = subparsers.add_parser(
        "quickstart",
        help="One command setup - init, start, index, and warmup",
        description=(
            "The ONE COMMAND to rule them all. Detects environment, starts services, "
            "indexes the codebase, and warms up models for optimal performance."
        )
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force overwrite of existing configuration"
    )

    parser.add_argument(
        "--build",
        action="store_true",
        help="Rebuild Docker containers before starting"
    )

    parser.add_argument(
        "--wait",
        type=int,
        default=30,
        help="Health check timeout in seconds (default: 30)"
    )

    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip initial indexing step"
    )

    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip model warmup step"
    )

    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate Qdrant collection (drops existing data)"
    )

    parser.set_defaults(func=run_quickstart)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Context-Engine Quickstart")

    parser.add_argument("--force", "-f", action="store_true",
                       help="Force overwrite of existing configuration")
    parser.add_argument("--build", action="store_true",
                       help="Rebuild Docker containers")
    parser.add_argument("--wait", type=int, default=30,
                       help="Health check timeout in seconds")
    parser.add_argument("--no-index", action="store_true",
                       help="Skip indexing step")
    parser.add_argument("--no-warmup", action="store_true",
                       help="Skip warmup step")
    parser.add_argument("--recreate", action="store_true",
                       help="Recreate collection")

    args = parser.parse_args()
    sys.exit(run_quickstart(args))
