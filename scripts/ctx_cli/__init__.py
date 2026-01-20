#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Context-Engine CLI - Unified command-line interface for MCP tools.

This package provides a production-ready CLI for interacting with the
Context-Engine MCP servers (Memory and Indexer).
"""

__version__ = "0.1.0"
__author__ = "Context-Engine Team"

try:
    from scripts.ctx_cli.main import main
except ImportError:
    # Allow import to succeed even if dependencies aren't installed
    def main():
        """Placeholder main function when dependencies are missing."""
        print("Error: ctx_cli dependencies not installed. Run: pip install -e .")
        return 1

# For backward compatibility
app = main

__all__ = ["main", "app", "__version__"]
