#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Context-Engine CLI commands package.

Available commands:
  - up: Start services
  - down: Stop services
  - restart: Restart services
  - status: Show stack status
  - init: Interactive setup wizard
  - search: Search the codebase
  - answer: Get natural language answer with citations
  - index: Index codebase into Qdrant
  - prune: Remove stale entries from index
  - completion: Shell completion scripts
"""

from . import status, init, answer, index, prune, completion, lifecycle, search, config

# List of all command modules
COMMANDS = [
    lifecycle,  # up, down, restart commands
    status,
    init,
    search,
    answer,
    index,
    prune,
    config,
    completion,
]


def register_all_commands(subparsers):
    """Register all available commands with the argument parser."""
    for command in COMMANDS:
        command.register_command(subparsers)
