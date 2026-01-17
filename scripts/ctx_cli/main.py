#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Context-Engine CLI - Main entry point.

Usage:
  ctx-cli status [--json] [--verbose]
  ctx-cli --version
  ctx-cli --help
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.ctx_cli.commands import register_all_commands
from scripts.ctx_cli import __version__


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ctx-cli",
        description="Context-Engine CLI - Unified interface for MCP tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ctx-cli status              Show stack status
  ctx-cli status --json       Output status as JSON
  ctx-cli status --verbose    Show detailed service information

For more information, visit: https://github.com/context-engine/context-engine
        """
    )

    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    # Create subparsers for commands
    subparsers = parser.add_subparsers(
        title="commands",
        description="Available commands",
        dest="command",
        help="Command to run"
    )

    # Register all commands
    register_all_commands(subparsers)

    # Parse arguments
    args = parser.parse_args()

    # If no command specified, show help
    if not args.command:
        parser.print_help()
        return 0

    # Execute the command
    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
