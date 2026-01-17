#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Config command for ctx CLI - View and edit configuration.

Usage:
    ctx config              Show current configuration
    ctx config --get KEY    Get specific value
    ctx config --set K=V    Set key=value
    ctx config --edit       Open in editor
    ctx config --path       Show config file path
"""

import os
import sys
import subprocess
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from scripts.ctx_cli.utils.config import ConfigManager


def run_config(args) -> int:
    """Execute the config command."""
    console = Console() if RICH_AVAILABLE else None
    config = ConfigManager()

    # Show config path
    if args.path:
        if config.config_path:
            print(str(config.config_path))
        else:
            print("No config file found")
            print("Create one with: ctx init")
        return 0

    # Get specific key
    if args.get:
        value = config.get(args.get)
        if value is not None:
            print(value)
            return 0
        else:
            print(f"Key not found: {args.get}", file=sys.stderr)
            return 1

    # Set key=value
    if args.set:
        for item in args.set:
            if "=" not in item:
                print(f"Invalid format: {item} (use KEY=VALUE)", file=sys.stderr)
                return 1
            key, value = item.split("=", 1)
            config.set(key.strip(), value.strip())
            if console:
                console.print(f"[green]✓[/green] Set {key} = {value}")
            else:
                print(f"Set {key} = {value}")
        return 0

    # Open in editor
    if args.edit:
        if not config.config_path:
            # Create default config
            config_path = Path.cwd() / ".ctxrc"
            config_path.write_text(config.get_default_config())
            config.config_path = config_path
            if console:
                console.print(f"[green]Created[/green] {config_path}")
            else:
                print(f"Created {config_path}")

        editor = os.environ.get("EDITOR", "vim")
        try:
            subprocess.run([editor, str(config.config_path)])
            return 0
        except FileNotFoundError:
            print(f"Editor not found: {editor}", file=sys.stderr)
            print("Set EDITOR environment variable", file=sys.stderr)
            return 1

    # Default: show all configuration
    if not config.config_path:
        if console:
            console.print(Panel(
                "[yellow]No configuration file found[/yellow]\n\n"
                "Create one with: [bold]ctx init[/bold]\n"
                "Or manually: [bold]ctx config --edit[/bold]",
                title="Configuration",
                border_style="yellow"
            ))
        else:
            print("No configuration file found")
            print("Create one with: ctx init")
            print("Or manually: ctx config --edit")
        return 0

    # Display configuration
    if console:
        console.print(f"\n[dim]Config file:[/dim] {config.config_path}\n")

        table = Table(title="Current Configuration", show_header=True)
        table.add_column("Section", style="cyan")
        table.add_column("Key", style="white")
        table.add_column("Value", style="green")

        for section in config.config.sections():
            for key, value in config.config.items(section):
                if key not in config.config.defaults():
                    table.add_row(section, key, value)

        # Show defaults
        for key, value in config.config.defaults().items():
            table.add_row("DEFAULT", key, value)

        console.print(table)
    else:
        print(f"Config file: {config.config_path}")
        print()
        for section in config.config.sections():
            print(f"[{section}]")
            for key, value in config.config.items(section):
                if key not in config.config.defaults():
                    print(f"  {key} = {value}")
        if config.config.defaults():
            print("[DEFAULT]")
            for key, value in config.config.defaults().items():
                print(f"  {key} = {value}")

    return 0


def register_command(subparsers):
    """Register the config command with the CLI parser."""
    parser = subparsers.add_parser(
        "config",
        help="View or edit configuration",
        description="View and manage ctx CLI configuration settings",
        epilog="""
Examples:
  ctx config                    Show all configuration
  ctx config --path             Show config file path
  ctx config --get indexer.url  Get specific value
  ctx config --set indexer.url=http://localhost:8003
  ctx config --edit             Open config in editor
        """
    )

    parser.add_argument(
        "--path",
        action="store_true",
        help="Show config file path"
    )

    parser.add_argument(
        "--get",
        metavar="KEY",
        help="Get value for KEY (e.g., indexer.url)"
    )

    parser.add_argument(
        "--set",
        metavar="KEY=VALUE",
        action="append",
        help="Set KEY=VALUE (can be used multiple times)"
    )

    parser.add_argument(
        "--edit",
        action="store_true",
        help="Open config file in editor ($EDITOR)"
    )

    parser.set_defaults(func=run_config)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    register_command(subparsers)
    args = parser.parse_args(["config"] + sys.argv[1:])
    sys.exit(run_config(args))
