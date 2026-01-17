#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Collections command for ctx CLI.

Manages Qdrant collections:
- List all collections with stats
- Create new collections
- Delete collections (with confirmation)
- Switch active collection
- Show detailed collection info

Usage:
  ctx collections list [--json]
  ctx collections create NAME [--recreate]
  ctx collections delete NAME [--force]
  ctx collections switch NAME
  ctx collections info NAME [--json]
"""

import json
import sys
from typing import Optional, Dict, Any, List

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


def format_size(bytes_count: int) -> str:
    """Format byte count as human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} PB"


def format_number(num: int) -> str:
    """Format number with thousands separator."""
    return f"{num:,}"


def print_table_row(columns: List[str], widths: List[int], border: bool = False):
    """Print a table row with proper formatting."""
    if border:
        print("├" + "┼".join("─" * (w + 2) for w in widths) + "┤")
    else:
        row = "│"
        for col, width in zip(columns, widths):
            row += f" {col.ljust(width)} │"
        print(row)


def print_table(headers: List[str], rows: List[List[str]], title: Optional[str] = None):
    """Print a formatted table with box drawing characters."""
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, col in enumerate(row):
            widths[i] = max(widths[i], len(str(col)))

    # Print title if provided
    if title:
        total_width = sum(widths) + len(widths) * 3 + 1
        print("┌" + "─" * (total_width - 2) + "┐")
        padding = (total_width - len(title) - 4) // 2
        print("│ " + " " * padding + title + " " * (total_width - len(title) - padding - 4) + " │")
        print("├" + "┼".join("─" * (w + 2) for w in widths) + "┤")
    else:
        print("┌" + "┬".join("─" * (w + 2) for w in widths) + "┐")

    # Print headers
    print_table_row(headers, widths)
    print("├" + "┼".join("─" * (w + 2) for w in widths) + "┤")

    # Print rows
    for row in rows:
        print_table_row([str(c) for c in row], widths)

    # Print footer
    print("└" + "┴".join("─" * (w + 2) for w in widths) + "┘")


def list_collections(args) -> int:
    """
    List all collections with stats.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    try:
        client = MCPClient(server="indexer")
    except Exception as e:
        print(f"Error: Failed to initialize MCP client: {e}", file=sys.stderr)
        return 1

    # Get list of collections
    try:
        list_result = client.call_tool("qdrant_list")
    except MCPError as e:
        print(f"Error: Failed to list collections: {e}", file=sys.stderr)
        return 1

    # Check for error
    if "error" in list_result:
        error_msg = list_result.get("error", "Unknown error")
        print(f"Error: Failed to list collections: {error_msg}", file=sys.stderr)
        return 1

    collections = list_result.get("collections", [])

    if not collections:
        print("No collections found.")
        return 0

    # Get detailed stats for each collection
    collection_stats = []
    for coll_name in collections:
        try:
            status_result = client.call_tool("qdrant_status", collection=coll_name)
            if "error" not in status_result:
                collection_stats.append({
                    "name": coll_name,
                    "count": status_result.get("count", 0),
                    "status": "active" if status_result.get("indexed", False) else "empty"
                })
            else:
                collection_stats.append({
                    "name": coll_name,
                    "count": 0,
                    "status": "unknown"
                })
        except MCPError:
            collection_stats.append({
                "name": coll_name,
                "count": 0,
                "status": "error"
            })

    # Output results
    if args.json:
        print(json.dumps({
            "ok": True,
            "collections": collection_stats,
            "total": len(collection_stats)
        }, indent=2))
    else:
        # Build table
        headers = ["Collection", "Documents", "Status"]
        rows = []

        for stats in collection_stats:
            rows.append([
                stats["name"],
                format_number(stats["count"]),
                stats["status"]
            ])

        print_table(headers, rows, title="Qdrant Collections")
        print(f"\nTotal: {len(collection_stats)} collection(s)")

    return 0


def create_collection(args) -> int:
    """
    Create a new collection.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    collection_name = args.name

    try:
        client = MCPClient(server="indexer")
    except Exception as e:
        print(f"Error: Failed to initialize MCP client: {e}", file=sys.stderr)
        return 1

    # Check if collection already exists
    try:
        list_result = client.call_tool("qdrant_list")
        if "error" not in list_result:
            existing = list_result.get("collections", [])
            if collection_name in existing and not args.recreate:
                print(f"Error: Collection '{collection_name}' already exists. Use --recreate to overwrite.", file=sys.stderr)
                return 1
    except MCPError as e:
        print(f"Warning: Could not check existing collections: {e}", file=sys.stderr)

    # Create collection
    print(f"Creating collection '{collection_name}'...")

    try:
        # Use qdrant_index_root with recreate flag to create collection
        result = client.call_tool(
            "qdrant_index_root",
            collection=collection_name,
            recreate=args.recreate
        )
    except MCPError as e:
        print(f"Error: Failed to create collection: {e}", file=sys.stderr)
        return 1

    if "error" in result:
        error_msg = result.get("error", "Unknown error")
        print(f"Error: Failed to create collection: {error_msg}", file=sys.stderr)
        return 1

    print(f"✓ Successfully created collection '{collection_name}'")
    return 0


def delete_collection(args) -> int:
    """
    Delete a collection.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    import os
    import urllib.request
    import urllib.error

    collection_name = args.name

    # Get Qdrant URL from environment or default
    qdrant_url = os.environ.get("QDRANT_HOST_URL", "http://localhost:6333")

    try:
        client = MCPClient(server="indexer")
    except Exception as e:
        print(f"Error: Failed to initialize MCP client: {e}", file=sys.stderr)
        return 1

    # Check if collection exists
    try:
        list_result = client.call_tool("qdrant_list")
        if "error" not in list_result:
            existing = list_result.get("collections", [])
            if collection_name not in existing:
                print(f"Error: Collection '{collection_name}' does not exist.", file=sys.stderr)
                return 1
    except MCPError as e:
        print(f"Warning: Could not check existing collections: {e}", file=sys.stderr)

    # Get collection stats before deletion
    count = 0
    try:
        status_result = client.call_tool("qdrant_status", collection=collection_name)
        if "error" not in status_result:
            count = status_result.get("count", 0)
            print(f"Collection '{collection_name}' contains {format_number(count)} document(s)")
    except MCPError:
        pass

    # Confirmation prompt unless --force
    if not args.force:
        try:
            if count > 0:
                response = input(f"⚠️  Delete '{collection_name}' with {format_number(count)} documents? [y/N]: ")
            else:
                response = input(f"Delete empty collection '{collection_name}'? [y/N]: ")
            if response.lower() not in ['y', 'yes']:
                print("Cancelled.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 0

    # Delete collection via Qdrant HTTP API
    print(f"Deleting collection '{collection_name}'...")

    try:
        url = f"{qdrant_url}/collections/{collection_name}"
        request = urllib.request.Request(url, method='DELETE')
        request.add_header('Content-Type', 'application/json')

        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode())

            if result.get("status") == "ok" or result.get("result") is True:
                print(f"✓ Deleted collection '{collection_name}'")
                return 0
            else:
                print(f"Error: Unexpected response: {result}", file=sys.stderr)
                return 1

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Error: Collection '{collection_name}' not found.", file=sys.stderr)
        else:
            print(f"Error: HTTP {e.code}: {e.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Error: Cannot connect to Qdrant at {qdrant_url}: {e.reason}", file=sys.stderr)
        print("Make sure Qdrant is running: ctx up", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: Failed to delete collection: {e}", file=sys.stderr)
        return 1


def switch_collection(args) -> int:
    """
    Switch active collection.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    collection_name = args.name

    try:
        client = MCPClient(server="indexer")
    except Exception as e:
        print(f"Error: Failed to initialize MCP client: {e}", file=sys.stderr)
        return 1

    # Check if collection exists
    try:
        list_result = client.call_tool("qdrant_list")
        if "error" not in list_result:
            existing = list_result.get("collections", [])
            if collection_name not in existing:
                print(f"Error: Collection '{collection_name}' does not exist.", file=sys.stderr)
                return 1
    except MCPError as e:
        print(f"Warning: Could not check existing collections: {e}", file=sys.stderr)

    # Switch collection using set_session_defaults
    try:
        result = client.call_tool("set_session_defaults", collection=collection_name)
    except MCPError as e:
        print(f"Error: Failed to switch collection: {e}", file=sys.stderr)
        return 1

    if "error" in result:
        error_msg = result.get("error", "Unknown error")
        print(f"Error: Failed to switch collection: {error_msg}", file=sys.stderr)
        return 1

    print(f"✓ Switched to collection '{collection_name}'")
    return 0


def info_collection(args) -> int:
    """
    Show detailed collection info.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    collection_name = args.name

    try:
        client = MCPClient(server="indexer")
    except Exception as e:
        print(f"Error: Failed to initialize MCP client: {e}", file=sys.stderr)
        return 1

    # Get collection status
    try:
        result = client.call_tool("qdrant_status", collection=collection_name)
    except MCPError as e:
        print(f"Error: Failed to get collection info: {e}", file=sys.stderr)
        return 1

    if "error" in result:
        error_msg = result.get("error", "Unknown error")
        print(f"Error: Failed to get collection info: {error_msg}", file=sys.stderr)
        return 1

    # Output results
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        # Build info display
        print(f"┌{'─' * 48}┐")
        print(f"│ Collection Info: {collection_name.ljust(48 - len('Collection Info: ') - 2)}│")
        print(f"├{'─' * 48}┤")

        count = result.get("count", 0)
        indexed = result.get("indexed", False)
        last_indexed = result.get("last_indexed", "Never")

        print(f"│ Documents:    {format_number(count).ljust(48 - len('Documents:    ') - 2)}│")
        print(f"│ Status:       {'Active' if indexed else 'Empty'.ljust(48 - len('Status:       ') - 2)}│")
        print(f"│ Last indexed: {str(last_indexed).ljust(48 - len('Last indexed: ') - 2)}│")
        print(f"└{'─' * 48}┘")

    return 0


def run_collections(args) -> int:
    """
    Run the collections command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    # Dispatch to subcommand handler
    if hasattr(args, 'collections_func'):
        return args.collections_func(args)
    else:
        # No subcommand specified, show help
        print("Error: No subcommand specified. Use 'ctx collections --help' for usage.", file=sys.stderr)
        return 1


def register_command(subparsers):
    """Register the collections command with the CLI parser."""
    parser = subparsers.add_parser(
        "collections",
        help="Manage Qdrant collections",
        description="List, create, delete, and switch between Qdrant collections"
    )

    # Create subparsers for collections subcommands
    collections_subparsers = parser.add_subparsers(
        dest="collections_subcommand",
        help="Collections subcommand"
    )

    # List subcommand
    list_parser = collections_subparsers.add_parser(
        "list",
        help="List all collections with stats"
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )
    list_parser.set_defaults(collections_func=list_collections)

    # Create subcommand
    create_parser = collections_subparsers.add_parser(
        "create",
        help="Create new collection"
    )
    create_parser.add_argument(
        "name",
        help="Collection name"
    )
    create_parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate collection if it already exists"
    )
    create_parser.set_defaults(collections_func=create_collection)

    # Delete subcommand
    delete_parser = collections_subparsers.add_parser(
        "delete",
        help="Delete collection"
    )
    delete_parser.add_argument(
        "name",
        help="Collection name"
    )
    delete_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt"
    )
    delete_parser.set_defaults(collections_func=delete_collection)

    # Switch subcommand
    switch_parser = collections_subparsers.add_parser(
        "switch",
        help="Set active collection"
    )
    switch_parser.add_argument(
        "name",
        help="Collection name"
    )
    switch_parser.set_defaults(collections_func=switch_collection)

    # Info subcommand
    info_parser = collections_subparsers.add_parser(
        "info",
        help="Show detailed collection stats"
    )
    info_parser.add_argument(
        "name",
        help="Collection name"
    )
    info_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )
    info_parser.set_defaults(collections_func=info_collection)

    # Set the main function
    parser.set_defaults(func=run_collections)
