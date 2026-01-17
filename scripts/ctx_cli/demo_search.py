#!/usr/bin/env python3
"""
Demo script showing search command output formats.

This demonstrates what the output looks like without needing the MCP server running.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ctx_cli.commands.search import (
    format_results_rich,
    format_results_plain,
)

# Mock search results
MOCK_RESULTS = [
    {
        "path": "src/db/pool.py",
        "start_line": 45,
        "end_line": 67,
        "score": 0.92,
        "language": "python",
        "symbol": "create_connection_pool",
        "snippet": '''def create_connection_pool():
    """Create and configure connection pool."""
    return ConnectionPool(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=int(os.environ.get('DB_PORT', 5432)),
        database=os.environ.get('DB_NAME', 'app'),
        max_connections=10
    )'''
    },
    {
        "path": "src/db/config.py",
        "start_line": 12,
        "end_line": 28,
        "score": 0.85,
        "language": "python",
        "symbol": None,
        "snippet": '''POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', '10'))
MAX_OVERFLOW = int(os.environ.get('DB_MAX_OVERFLOW', '20'))

DATABASE_CONFIG = {
    'host': os.environ.get('DB_HOST'),
    'port': os.environ.get('DB_PORT'),
    'database': os.environ.get('DB_NAME'),
    'pool_size': POOL_SIZE,
    'max_overflow': MAX_OVERFLOW
}'''
    },
    {
        "path": "src/models/connection.py",
        "start_line": 89,
        "end_line": 104,
        "score": 0.78,
        "language": "python",
        "symbol": "get_db_connection",
        "snippet": '''def get_db_connection():
    """Get database connection from pool."""
    try:
        conn = pool.getconn()
        return conn
    except Exception as e:
        logger.error(f"Failed to get connection: {e}")
        raise'''
    }
]

def demo_rich_output():
    """Demonstrate Rich formatted output."""
    print("\n" + "="*60)
    print("DEMO: Rich Formatted Output (with snippets)")
    print("="*60 + "\n")

    try:
        from rich.console import Console
        console = Console()
        format_results_rich(
            results=MOCK_RESULTS,
            query="database connection",
            total=len(MOCK_RESULTS),
            include_snippet=True,
            console=console
        )
    except ImportError:
        print("Rich library not available - showing plain text instead")
        demo_plain_output()


def demo_plain_output():
    """Demonstrate plain text output."""
    print("\n" + "="*60)
    print("DEMO: Plain Text Output (with snippets)")
    print("="*60 + "\n")

    output = format_results_plain(
        results=MOCK_RESULTS,
        query="database connection",
        total=len(MOCK_RESULTS),
        include_snippet=True
    )
    print(output)


def demo_compact_output():
    """Demonstrate compact output (no snippets)."""
    print("\n" + "="*60)
    print("DEMO: Compact Output (no snippets)")
    print("="*60 + "\n")

    output = format_results_plain(
        results=MOCK_RESULTS,
        query="database connection",
        total=len(MOCK_RESULTS),
        include_snippet=False
    )
    print(output)


def demo_json_output():
    """Demonstrate JSON output."""
    import json

    print("\n" + "="*60)
    print("DEMO: JSON Output")
    print("="*60 + "\n")

    data = {
        "results": MOCK_RESULTS,
        "total": len(MOCK_RESULTS),
        "query": "database connection"
    }
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    print("Context-Engine CLI Search Command - Output Format Demos")
    print("="*60)

    demo_rich_output()
    demo_plain_output()
    demo_compact_output()
    demo_json_output()

    print("\n" + "="*60)
    print("Demo complete!")
    print("="*60 + "\n")
