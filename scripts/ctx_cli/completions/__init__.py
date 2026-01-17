#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Shell completion support for ctx CLI.

Provides completion scripts for bash, zsh, and fish shells.
"""

from pathlib import Path

COMPLETIONS_DIR = Path(__file__).parent


def get_completion_script(shell: str) -> str:
    """
    Get completion script for the specified shell.

    Args:
        shell: Shell type (bash, zsh, or fish)

    Returns:
        Completion script content

    Raises:
        ValueError: If shell type is not supported
    """
    shell = shell.lower()

    if shell == "bash":
        script_path = COMPLETIONS_DIR / "bash.sh"
    elif shell == "zsh":
        script_path = COMPLETIONS_DIR / "zsh.sh"
    elif shell == "fish":
        script_path = COMPLETIONS_DIR / "fish.fish"
    else:
        raise ValueError(f"Unsupported shell: {shell}. Use bash, zsh, or fish.")

    if not script_path.exists():
        raise FileNotFoundError(f"Completion script not found: {script_path}")

    return script_path.read_text()
