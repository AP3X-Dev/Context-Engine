#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Completion command for ctx CLI.

Outputs shell completion scripts for bash, zsh, and fish.

Usage:
  ctx completion bash  # Print bash completion script
  ctx completion zsh   # Print zsh completion script
  ctx completion fish  # Print fish completion script

To enable completions:

Bash:
  eval "$(ctx completion bash)"
  # Or add to ~/.bashrc

Zsh:
  eval "$(ctx completion zsh)"
  # Or add to ~/.zshrc

Fish:
  ctx completion fish | source
  # Or add to ~/.config/fish/config.fish
"""

import sys

from scripts.ctx_cli.completions import get_completion_script


def run_completion(args) -> int:
    """
    Run the completion command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    try:
        script = get_completion_script(args.shell)
        print(script, end='')
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("\nSupported shells: bash, zsh, fish", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def register_command(subparsers):
    """Register the completion command with the CLI parser."""
    parser = subparsers.add_parser(
        "completion",
        help="Print shell completion script",
        description="""
Output shell completion script for bash, zsh, or fish.

Examples:
  # Bash
  eval "$(ctx completion bash)"

  # Zsh
  eval "$(ctx completion zsh)"

  # Fish
  ctx completion fish | source

To make completions permanent, add the appropriate line to your shell's
configuration file (~/.bashrc, ~/.zshrc, or ~/.config/fish/config.fish).
        """,
    )

    parser.add_argument(
        "shell",
        choices=["bash", "zsh", "fish"],
        help="Shell type (bash, zsh, or fish)"
    )

    parser.set_defaults(func=run_completion)
