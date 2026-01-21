#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Bridge command for ctx CLI - Manage MCP bridge and generate IDE configs.

Commands:
    ctx bridge status                   Show bridge connection status
    ctx bridge generate claude          Generate Claude Desktop config
    ctx bridge generate cursor          Generate Cursor config
    ctx bridge generate windsurf        Generate Windsurf config
    ctx bridge generate all             Generate all IDE configs

Options:
    --output DIR                        Custom output directory
    --force                             Overwrite existing configs without prompting
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import socket


logger = logging.getLogger(__name__)
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def get_service_urls() -> Dict[str, str]:
    """
    Get service URLs from environment or defaults.

    Priority: Environment variable > .env file > defaults
    """
    # Try to load from .env if not in environment
    env_file = Path.cwd() / ".env"
    env_vars = {}
    if env_file.exists():
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        env_vars[key.strip()] = value.strip().strip('"').strip("'")
        except Exception as e:
            logger.debug(f"Suppressed exception: {e}")

    def get_var(name: str, default: str) -> str:
        return os.environ.get(name) or env_vars.get(name) or default

    return {
        "indexer": get_var("MCP_INDEXER_URL", "http://localhost:8003/mcp"),
        "memory": get_var("MCP_MEMORY_URL", "http://localhost:8002/mcp"),
        "qdrant": get_var("QDRANT_HOST_URL", "http://localhost:6333"),
    }


def check_bridge_status() -> Dict[str, Any]:
    """
    Check MCP bridge and server status.

    Returns:
        Dictionary with status information
    """
    urls = get_service_urls()
    status = {
        "indexer": {"url": urls["indexer"], "healthy": False},
        "memory": {"url": urls["memory"], "healthy": False},
        "qdrant": {"url": urls["qdrant"], "healthy": False},
    }

    # Check each service
    for service_name, service_info in status.items():
        try:
            req = Request(service_info["url"], headers={"Accept": "application/json"})
            with urlopen(req, timeout=2) as response:
                # Any response means service is running
                status[service_name]["healthy"] = True
        except HTTPError as e:
            # HTTP errors like 405/406 still mean service is running
            # MCP servers often return errors for GET requests
            if e.code in (400, 405, 406, 415):
                status[service_name]["healthy"] = True
        except (URLError, socket.timeout):
            pass

    return status


def print_status(status: Dict[str, Any]) -> None:
    """Print bridge status."""
    if console:
        table = Table(title="MCP Bridge Status", show_header=True)
        table.add_column("Service", style="cyan")
        table.add_column("Endpoint", style="white")
        table.add_column("Status", style="bold")

        for service_name, service_info in status.items():
            status_str = "[green]✓ Healthy[/green]" if service_info["healthy"] else "[red]✗ Unavailable[/red]"
            table.add_row(
                service_name.capitalize(),
                service_info["url"],
                status_str
            )

        console.print()
        console.print(table)
        console.print()

        all_healthy = all(s["healthy"] for s in status.values())
        if all_healthy:
            console.print("[green]All services are healthy and ready to use.[/green]")
        else:
            console.print("[yellow]Some services are unavailable. Try running: ctx up[/yellow]")
    else:
        print("\nMCP Bridge Status:")
        print("-" * 60)
        for service_name, service_info in status.items():
            status_str = "✓ Healthy" if service_info["healthy"] else "✗ Unavailable"
            print(f"{service_name.capitalize():12} {service_info['url']:35} {status_str}")
        print()


def get_claude_desktop_config() -> Dict[str, Any]:
    """
    Generate Claude Desktop MCP configuration.

    Returns:
        Configuration dictionary
    """
    urls = get_service_urls()
    return {
        "mcpServers": {
            "memory": {
                "url": urls["memory"]
            },
            "qdrant-indexer": {
                "url": urls["indexer"]
            }
        }
    }


def get_cursor_config() -> Dict[str, Any]:
    """
    Generate Cursor IDE MCP configuration.

    Uses SSE endpoints. Falls back to converting HTTP URLs to SSE format.

    Returns:
        Configuration dictionary
    """
    urls = get_service_urls()

    # Convert HTTP MCP URLs to SSE format if needed
    # http://localhost:8003/mcp -> http://localhost:8001/sse
    # http://localhost:8002/mcp -> http://localhost:8000/sse
    memory_sse = os.environ.get("MCP_MEMORY_SSE_URL") or "http://localhost:8000/sse"
    indexer_sse = os.environ.get("MCP_INDEXER_SSE_URL") or "http://localhost:8001/sse"

    return {
        "mcpServers": {
            "memory": {
                "type": "sse",
                "url": memory_sse,
                "disabled": False
            },
            "qdrant-indexer": {
                "type": "sse",
                "url": indexer_sse,
                "disabled": False
            }
        }
    }


def get_windsurf_config() -> Dict[str, Any]:
    """
    Generate Windsurf IDE MCP configuration.

    Uses SSE endpoints (same as Cursor).

    Returns:
        Configuration dictionary
    """
    # Windsurf uses same SSE format as Cursor
    return get_cursor_config()


def get_default_config_path(ide: str, output_dir: Optional[Path] = None) -> Path:
    """
    Get default config file path for IDE.

    Args:
        ide: IDE name (claude, cursor, windsurf)
        output_dir: Optional custom output directory

    Returns:
        Path to config file
    """
    if output_dir:
        return output_dir / f"{ide}_config.json"

    home = Path.home()

    if ide == "claude":
        # Claude Desktop config location varies by OS
        if sys.platform == "darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        elif sys.platform == "win32":
            return home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
        else:
            return home / ".config" / "Claude" / "claude_desktop_config.json"
    elif ide == "cursor":
        return Path.cwd() / ".cursor" / "mcp.json"
    elif ide == "windsurf":
        # Windsurf config location (similar to Cursor)
        return Path.cwd() / ".windsurf" / "mcp.json"
    else:
        return Path.cwd() / f"{ide}_mcp_config.json"


def write_config(
    config: Dict[str, Any],
    path: Path,
    force: bool = False
) -> bool:
    """
    Write configuration to file.

    Args:
        config: Configuration dictionary
        path: Output file path
        force: Overwrite without prompting

    Returns:
        True if written successfully
    """
    # Check if file exists
    if path.exists() and not force:
        if console:
            console.print(f"\n[yellow]Config file already exists:[/yellow] {path}")
            response = input("Overwrite? [y/N]: ").strip().lower()
        else:
            print(f"\nConfig file already exists: {path}")
            response = input("Overwrite? [y/N]: ").strip().lower()

        if response not in ("y", "yes"):
            if console:
                console.print("[dim]Skipped.[/dim]")
            else:
                print("Skipped.")
            return False

    # Create parent directory if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write config
    with open(path, "w") as f:
        json.dump(config, f, indent=2)

    return True


def generate_config(ide: str, output_dir: Optional[Path] = None, force: bool = False) -> int:
    """
    Generate IDE configuration file.

    Args:
        ide: IDE name (claude, cursor, windsurf, all)
        output_dir: Optional custom output directory
        force: Overwrite without prompting

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    if ide == "all":
        # Generate all configs
        ides = ["claude", "cursor", "windsurf"]
        success_count = 0

        for ide_name in ides:
            result = generate_config(ide_name, output_dir, force)
            if result == 0:
                success_count += 1

        if console:
            console.print(f"\n[bold]Generated {success_count}/{len(ides)} configurations.[/bold]")
        else:
            print(f"\nGenerated {success_count}/{len(ides)} configurations.")

        return 0 if success_count == len(ides) else 1

    # Get config for specific IDE
    if ide == "claude":
        config = get_claude_desktop_config()
        config_name = "Claude Desktop"
    elif ide == "cursor":
        config = get_cursor_config()
        config_name = "Cursor"
    elif ide == "windsurf":
        config = get_windsurf_config()
        config_name = "Windsurf"
    else:
        if console:
            console.print(f"[red]Unknown IDE: {ide}[/red]")
        else:
            print(f"Unknown IDE: {ide}", file=sys.stderr)
        return 1

    # Get output path
    output_path = get_default_config_path(ide, output_dir)

    # Write config
    if write_config(config, output_path, force):
        if console:
            console.print(f"\n[green]✓[/green] Generated {config_name} config:")
            console.print(f"  [cyan]{output_path}[/cyan]")
            console.print()

            # Show config preview
            panel = Panel(
                json.dumps(config, indent=2),
                title=f"{config_name} MCP Configuration",
                border_style="green"
            )
            console.print(panel)
        else:
            print(f"\n✓ Generated {config_name} config: {output_path}")
            print("\nConfiguration:")
            print(json.dumps(config, indent=2))

        return 0
    else:
        return 1


def run_status(args) -> int:
    """Execute the bridge status command."""
    status = check_bridge_status()
    print_status(status)

    all_healthy = all(s["healthy"] for s in status.values())
    return 0 if all_healthy else 1


def run_generate(args) -> int:
    """Execute the bridge generate command."""
    return generate_config(
        ide=args.ide,
        output_dir=Path(args.output) if args.output else None,
        force=args.force
    )


def run_bridge(args) -> int:
    """
    Execute the bridge command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    # Dispatch to subcommand
    if hasattr(args, "bridge_func"):
        return args.bridge_func(args)
    else:
        # No subcommand - show status by default
        status = check_bridge_status()
        print_status(status)
        return 0


def register_command(subparsers):
    """Register the bridge command with the CLI parser."""
    parser = subparsers.add_parser(
        "bridge",
        help="Manage MCP bridge and generate IDE configs",
        description="Manage MCP bridge connections and generate IDE configuration files",
        epilog="""
Examples:
  ctx bridge                              Show bridge status
  ctx bridge status                       Show bridge status
  ctx bridge generate claude              Generate Claude Desktop config
  ctx bridge generate cursor              Generate Cursor config
  ctx bridge generate windsurf            Generate Windsurf config
  ctx bridge generate all                 Generate all IDE configs
  ctx bridge generate claude --output ~/  Custom output directory
        """
    )

    # Create subparsers for bridge subcommands
    bridge_subparsers = parser.add_subparsers(dest="bridge_command")

    # Status subcommand
    status_parser = bridge_subparsers.add_parser(
        "status",
        help="Show bridge connection status"
    )
    status_parser.set_defaults(bridge_func=run_status)

    # Generate subcommand
    generate_parser = bridge_subparsers.add_parser(
        "generate",
        help="Generate IDE configuration files"
    )

    generate_parser.add_argument(
        "ide",
        choices=["claude", "cursor", "windsurf", "all"],
        help="IDE to generate config for"
    )

    generate_parser.add_argument(
        "--output",
        metavar="DIR",
        help="Custom output directory"
    )

    generate_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configs without prompting"
    )

    generate_parser.set_defaults(bridge_func=run_generate)

    # Set default function for bridge command
    parser.set_defaults(func=run_bridge)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    register_command(subparsers)
    args = parser.parse_args()
    sys.exit(run_bridge(args))
