#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Context-Engine CLI - Main entry point.

Usage:
  ctx status [--json] [--verbose]
  ctx --version
  ctx --help

Note: This module should be invoked via the installed `ctx` command
(see pyproject.toml entry points) or via `python -m scripts.ctx_cli`.
"""

# Suppress the runpy RuntimeWarning when invoked via `python -m`
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, module="runpy")

import os
import sys
import argparse

# Load .env file at startup so all commands have access to environment variables
def _load_dotenv():
    """Load .env file into environment if it exists."""
    from pathlib import Path
    cwd = Path.cwd()
    # Search current and up to 3 parent directories
    for _ in range(4):
        env_file = cwd / ".env"
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Remove quotes
                    if value and len(value) >= 2:
                        if (value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'"):
                            value = value[1:-1]
                    # Only set if not already in environment (env vars take precedence)
                    if key and key not in os.environ:
                        os.environ[key] = value
            except Exception:
                pass
            break
        if cwd.parent == cwd:
            break
        cwd = cwd.parent

_load_dotenv()

# Import CLI components - handle the case when running directly (not installed)
try:
    from scripts.ctx_cli.commands import register_all_commands
    from scripts.ctx_cli import __version__
    from scripts.ctx_cli.utils.mcp_client import MCPError
except ImportError:
    # When running directly as a script (not installed), add parent to path
    from pathlib import Path
    _project_root = Path(__file__).resolve().parent.parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    from scripts.ctx_cli.commands import register_all_commands
    from scripts.ctx_cli import __version__
    from scripts.ctx_cli.utils.mcp_client import MCPError


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
