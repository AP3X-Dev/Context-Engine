#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Logs command for ctx CLI.

View service logs from Docker Compose containers.

Usage:
  ctx logs [SERVICE] [--follow] [--tail N] [--since DURATION] [--timestamps]

Examples:
  ctx logs                     # View all service logs (last 100 lines)
  ctx logs indexer -f          # Follow indexer logs
  ctx logs mcp --tail 50       # Show last 50 lines from mcp service
  ctx logs --since 10m         # Show logs from last 10 minutes
  ctx logs qdrant -f -t        # Follow qdrant logs with timestamps
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

try:
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def _print(msg: str, file=None) -> None:
    """Print with Rich if available, otherwise plain print."""
    if console:
        console.print(msg)
    else:
        # Strip Rich markup for plain output
        import re
        plain = re.sub(r'\[/?[^\]]+\]', '', msg)
        print(plain, file=file or sys.stdout)


# Known service aliases for better UX
SERVICE_ALIASES = {
    "memory": "mcp",
    "search": "mcp",
    "indexer": "mcp_indexer",
    "db": "qdrant",
    "vector": "qdrant",
    "decoder": "llamacpp",
    "llama": "llamacpp",
    "watcher": "watcher",
    "upload": "upload_service",
    "learning": "learning_worker",
}


def find_compose_file(project_root: Path) -> Optional[Path]:
    """
    Find the docker-compose file.

    Args:
        project_root: Project root directory

    Returns:
        Path to compose file or None if not found
    """
    # Check for compose.yaml first (newer convention)
    compose_yaml = project_root / "compose.yaml"
    if compose_yaml.exists():
        return compose_yaml

    # Check for docker-compose.yml (traditional)
    compose_yml = project_root / "docker-compose.yml"
    if compose_yml.exists():
        return compose_yml

    return None


def check_docker_compose_available() -> tuple[bool, str]:
    """
    Check if docker compose is available.

    Returns:
        Tuple of (is_available, command_to_use)
    """
    # Try 'docker compose' first (newer plugin-based approach)
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "docker compose"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Try 'docker-compose' (older standalone binary)
    try:
        result = subprocess.run(
            ["docker-compose", "version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "docker-compose"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return False, ""


def resolve_service_name(service: Optional[str]) -> Optional[str]:
    """
    Resolve service aliases to actual service names.

    Args:
        service: Service name or alias

    Returns:
        Resolved service name or None
    """
    if service is None:
        return None

    # Return exact match if not an alias
    if service not in SERVICE_ALIASES:
        return service

    return SERVICE_ALIASES[service]


def run_logs(args) -> int:
    """
    Run the logs command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    # Find project root (4 levels up from this file)
    project_root = Path(__file__).resolve().parent.parent.parent.parent

    # Check if docker-compose is available
    compose_available, compose_cmd = check_docker_compose_available()
    if not compose_available:
        _print("\n[red]Error:[/red] docker-compose not found\n", file=sys.stderr)
        _print("Please install Docker Compose:", file=sys.stderr)
        _print("  https://docs.docker.com/compose/install/\n", file=sys.stderr)
        return 1

    # Find compose file
    compose_file = find_compose_file(project_root)
    if compose_file is None:
        _print("\n[red]Error:[/red] No docker-compose.yml or compose.yaml found\n", file=sys.stderr)
        _print(f"Expected location: {project_root}\n", file=sys.stderr)
        return 1

    # Build docker compose logs command
    # Split compose_cmd (e.g., "docker compose" -> ["docker", "compose"])
    cmd_parts = compose_cmd.split()
    cmd: List[str] = [*cmd_parts, "logs"]

    # Add options
    if args.follow:
        cmd.append("-f")

    if args.timestamps:
        cmd.append("-t")

    if args.tail is not None:
        cmd.extend(["--tail", str(args.tail)])

    if args.since is not None:
        cmd.extend(["--since", args.since])

    # Add service name if specified
    if args.service is not None:
        resolved_service = resolve_service_name(args.service)
        cmd.append(resolved_service)

        # Show friendly message if using alias
        if resolved_service != args.service:
            _print(f"[dim]Viewing logs for {resolved_service} (alias: {args.service})[/dim]\n")

    # Run the command
    try:
        # Don't capture output - let it stream to terminal
        result = subprocess.run(
            cmd,
            cwd=project_root,
        )
        return result.returncode

    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully when following logs
        _print("\n[dim]Stopped following logs[/dim]\n")
        return 0

    except subprocess.CalledProcessError as e:
        _print(f"\n[red]Error running docker compose logs:[/red] {e}\n", file=sys.stderr)
        return 1

    except Exception as e:
        _print(f"\n[red]Unexpected error:[/red] {e}\n", file=sys.stderr)
        return 1


def register_command(subparsers):
    """Register the logs command with the CLI parser."""
    parser = subparsers.add_parser(
        "logs",
        help="View service logs",
        description="View logs from Docker Compose services. Supports filtering by service and common log viewing options."
    )

    parser.add_argument(
        "service",
        nargs="?",
        default=None,
        help="Service name to view logs from (optional, defaults to all services). "
             "Supported services: qdrant, mcp (memory), mcp_indexer (indexer), "
             "mcp_http, mcp_indexer_http, llamacpp (decoder), watcher, upload_service (upload), "
             "learning_worker (learning), indexer, init_payload"
    )

    parser.add_argument(
        "--follow", "-f",
        action="store_true",
        help="Follow log output (stream logs in real-time)"
    )

    parser.add_argument(
        "--tail",
        type=int,
        default=100,
        metavar="N",
        help="Number of lines to show from the end of logs (default: 100)"
    )

    parser.add_argument(
        "--since",
        type=str,
        metavar="DURATION",
        help="Show logs since timestamp or duration (e.g., '10m', '1h', '2023-01-02T13:23:37')"
    )

    parser.add_argument(
        "--timestamps", "-t",
        action="store_true",
        help="Show timestamps in log output"
    )

    parser.set_defaults(func=run_logs)
