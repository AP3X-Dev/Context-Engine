#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Context-Engine CLI commands package.

Available commands:
  - quickstart: One command setup - init, start, index, and warmup
  - up: Start services
  - down: Stop services
  - restart: Restart services
  - status: Show stack status
  - doctor: Comprehensive health check
  - logs: View service logs
  - init: Interactive setup wizard
  - search: Search the codebase
  - answer: Get natural language answer with citations
  - memory: Store and search knowledge entries
  - graph: Navigate symbol relationships (callers, definitions, imports)
  - pattern: Find structurally similar code patterns
  - index: Index codebase into Qdrant
  - sync: Upload/sync workspace to remote Context-Engine
  - prune: Remove stale entries from index
  - collections: Manage Qdrant collections
  - bridge: Manage MCP bridge and generate IDE configs
  - warmup: Preload models to reduce first-query latency
  - completion: Shell completion scripts
"""

from . import status, init, answer, index, prune, completion, lifecycle, search, config, logs, warmup, collections, bridge, quickstart, doctor, memory, graph, pattern, sync

# List of all command modules
COMMANDS = [
    quickstart,  # The ONE COMMAND to rule them all
    lifecycle,  # up, down, restart commands
    status,
    doctor,
    logs,
    init,
    search,
    answer,
    memory,      # Memory store/find
    graph,       # Symbol graph navigation
    pattern,     # Pattern search
    index,
    sync,        # Remote upload/sync (like VS Code extension)
    prune,
    collections,
    warmup,
    config,
    bridge,
    completion,
]


def register_all_commands(subparsers):
    """Register all available commands with the argument parser."""
    for command in COMMANDS:
        command.register_command(subparsers)
