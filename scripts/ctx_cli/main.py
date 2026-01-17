#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Context-Engine CLI - Main entry point.

Usage:
  ctx status [--json] [--verbose]
  ctx --version
  ctx --help
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.ctx_cli.commands import register_all_commands
from scripts.ctx_cli import __version__

try:
    from scripts.ctx_cli.utils.mcp_client import MCPError
except ImportError:
    class MCPError(Exception):  # type: ignore[no-redef]
        """Fallback MCPError type when ctx_cli utils are unavailable."""

        def __init__(self, message: str = "", code: int = -1, data=None):
            super().__init__(message)
            self.message = message
            self.code = code
            self.data = data


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ctx",
        description="Context-Engine CLI - Unified interface for MCP tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ctx status              Show stack status
  ctx status --json       Output status as JSON
  ctx status --verbose    Show detailed service information

For more information, visit: https://github.com/m1rl0k/context-engine
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

    # Execute the command with centralized error handling
    if hasattr(args, "func"):
        try:
            return args.func(args)
        except MCPError as e:
            msg = getattr(e, "message", str(e))
            data = getattr(e, "data", None)
            print(f"Error: {msg}", file=sys.stderr)
            if data:
                print(f"Details: {data}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nInterrupted", file=sys.stderr)
            return 130
        except Exception as e:
            print(f"Unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
