#!/usr/bin/env python3
"""
Test script for the search command.

This demonstrates the search command can be run standalone or via the CLI.
"""

import sys
import os

# Add parent directory to path so we can import commands
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ctx_cli.commands.search import main

if __name__ == "__main__":
    # Test with some sample arguments
    print("Testing search command...")
    print()

    # Example: search for "database connection" with limit 3
    test_args = ["database connection", "--limit", "3"]

    print(f"Running: ctx search {' '.join(test_args)}")
    print("-" * 60)

    sys.exit(main(test_args))
