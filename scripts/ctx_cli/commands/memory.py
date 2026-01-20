#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Memory command for Context-Engine CLI.

Usage:
    ctx memory store "This is important information" [--tags key=value]
    ctx memory find "search query" [--kind snippet] [--limit 10]

Examples:
    ctx memory store "The auth system uses JWT tokens" --tags topic=auth kind=explanation
    ctx memory find "authentication" --kind explanation --limit 5
    ctx memory find "database connection" --json
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


def call_memory_store(
    information: str,
    metadata: Optional[Dict[str, Any]] = None,
    collection: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Store a memory entry via MCP memory_store tool."""
    params = {"information": information}
    
    if metadata:
        params["metadata"] = metadata
    
    try:
        client = MCPClient(server="memory", timeout=timeout)
        if collection:
            params["collection"] = collection
        else:
            env_collection = os.environ.get("COLLECTION_NAME")
            if env_collection:
                params["collection"] = env_collection
            else:
                cfg_collection = client.config.get_default_collection()
                if cfg_collection:
                    params["collection"] = cfg_collection
        return client.call_tool("memory_store", **params)
    except MCPError as e:
        return {"error": {"code": e.code, "message": str(e), "data": e.data}}
    except Exception as e:
        return {"error": {"code": -1, "message": f"Request failed: {type(e).__name__}: {str(e)}"}}


def call_memory_find(
    query: str,
    limit: int = 10,
    kind: Optional[str] = None,
    language: Optional[str] = None,
    tags: Optional[List[str]] = None,
    priority_min: Optional[int] = None,
    collection: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Search memory entries via MCP memory_find tool."""
    params = {"query": query, "limit": limit}
    
    if kind:
        params["kind"] = kind
    if language:
        params["language"] = language
    if tags:
        params["tags"] = tags
    if priority_min is not None:
        params["priority_min"] = priority_min
    
    try:
        client = MCPClient(server="memory", timeout=timeout)
        if collection:
            params["collection"] = collection
        else:
            env_collection = os.environ.get("COLLECTION_NAME")
            if env_collection:
                params["collection"] = env_collection
            else:
                cfg_collection = client.config.get_default_collection()
                if cfg_collection:
                    params["collection"] = cfg_collection
        return client.call_tool("memory_find", **params)
    except MCPError as e:
        return {"error": {"code": e.code, "message": str(e), "data": e.data}}
    except Exception as e:
        return {"error": {"code": -1, "message": f"Request failed: {type(e).__name__}: {str(e)}"}}


def format_memory_results(results: List[Dict[str, Any]], query: str) -> None:
    """Format and print memory search results."""
    console = Console() if RICH_AVAILABLE else None
    
    if not results:
        if console:
            console.print(Panel("[yellow]No memories found[/yellow]", title="Memory Search"))
        else:
            print(f"No memories found for: {query}")
        return
    
    if console:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=3)
        table.add_column("Content", style="cyan", max_width=60)
        table.add_column("Kind", style="yellow", width=12)
        table.add_column("Score", style="green", width=8)
        
        for idx, result in enumerate(results, 1):
            content = result.get("text", result.get("content", ""))[:60]
            kind = result.get("kind", "-")
            score = result.get("score", 0.0)
            table.add_row(str(idx), content, kind, f"{score:.2f}")
        
        console.print(Panel(table, title=f"[bold magenta]Memory Results[/bold magenta] ({len(results)} found)"))
    else:
        print(f"Found {len(results)} memories for: {query}")
        for idx, result in enumerate(results, 1):
            content = result.get("text", result.get("content", ""))[:80]
            print(f"  {idx}. {content}")


def store_command(args) -> int:
    """Execute memory store command."""
    metadata = {}
    if args.tags:
        for tag in args.tags:
            if "=" in tag:
                k, v = tag.split("=", 1)
                metadata[k] = v
    
    if args.kind:
        metadata["kind"] = args.kind
    if args.priority:
        metadata["priority"] = args.priority
    
    result = call_memory_store(
        information=args.information,
        metadata=metadata if metadata else None,
        collection=args.collection,
        timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    console = Console() if RICH_AVAILABLE else None

    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        if console:
            console.print(Panel(f"[red]{msg}[/red]", title="[bold red]Error[/bold red]"))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return 1

    if console:
        console.print(Panel(f"[green]Memory stored successfully[/green]\nID: {result.get('id', 'N/A')}",
                           title="[bold green]Success[/bold green]"))
    else:
        print(f"Memory stored. ID: {result.get('id', 'N/A')}")
    return 0


def find_command(args) -> int:
    """Execute memory find command."""
    tags = args.tags if hasattr(args, 'tags') and args.tags else None

    result = call_memory_find(
        query=args.query,
        limit=args.limit,
        kind=args.kind,
        language=args.language,
        tags=tags,
        priority_min=args.priority_min,
        collection=args.collection,
        timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if "error" in result:
        console = Console() if RICH_AVAILABLE else None
        msg = result["error"].get("message", "Unknown error")
        if console:
            console.print(Panel(f"[red]{msg}[/red]", title="[bold red]Error[/bold red]"))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return 1

    results = result.get("results", [])
    format_memory_results(results, args.query)
    return 0


def register_command(subparsers):
    """Register memory command and subcommands."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Store and search memory entries",
        description="Manage knowledge store - save and retrieve information",
    )

    memory_subs = memory_parser.add_subparsers(dest="memory_cmd", help="Memory operations")

    # store subcommand
    store_parser = memory_subs.add_parser("store", help="Store information in memory")
    store_parser.add_argument("information", help="Information to store")
    store_parser.add_argument("--tags", "-t", nargs="*", help="Metadata tags (key=value)")
    store_parser.add_argument("--kind", "-k", help="Entry kind (snippet, explanation, note)")
    store_parser.add_argument("--priority", "-p", type=int, help="Priority 1-10 (higher=more important)")
    store_parser.add_argument("--collection", "-c", help="Collection name")
    store_parser.add_argument("--timeout", type=int, default=30, help="Request timeout")
    store_parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    store_parser.set_defaults(func=store_command)

    # find subcommand
    find_parser = memory_subs.add_parser("find", help="Search memories")
    find_parser.add_argument("query", help="Search query")
    find_parser.add_argument("--limit", "-l", type=int, default=10, help="Max results")
    find_parser.add_argument("--kind", "-k", help="Filter by kind")
    find_parser.add_argument("--language", help="Filter by language")
    find_parser.add_argument("--tags", "-t", nargs="*", help="Filter by tags")
    find_parser.add_argument("--priority-min", type=int, help="Minimum priority")
    find_parser.add_argument("--collection", "-c", help="Collection name")
    find_parser.add_argument("--timeout", type=int, default=30, help="Request timeout")
    find_parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    find_parser.set_defaults(func=find_command)

    # Default behavior when no subcommand
    memory_parser.set_defaults(func=lambda args: memory_parser.print_help() or 0)

