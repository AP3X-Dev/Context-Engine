#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Graph command for Context-Engine CLI.

Usage:
    ctx graph callers <symbol> [--depth 2] [--limit 20]
    ctx graph definition <symbol>
    ctx graph importers <symbol>
    ctx graph callees <symbol>

Examples:
    ctx graph callers authenticate --depth 2
    ctx graph definition MCPClient --language python
    ctx graph importers qdrant_client --limit 15
    ctx graph callees main --under src/
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.tree import Tree
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


def call_symbol_graph(
    symbol: str,
    query_type: str = "callers",
    limit: int = 20,
    depth: int = 1,
    language: Optional[str] = None,
    under: Optional[str] = None,
    repo: Optional[str] = None,
    collection: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Call symbol_graph MCP tool."""
    params = {
        "symbol": symbol,
        "query_type": query_type,
        "limit": limit,
        "depth": depth,
    }
    
    if language:
        params["language"] = language
    if under:
        params["under"] = under
    if repo:
        params["repo"] = repo
    
    try:
        client = MCPClient(server="indexer", timeout=timeout)
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
        return client.call_tool("symbol_graph", **params)
    except MCPError as e:
        return {"error": {"code": e.code, "message": str(e), "data": e.data}}
    except Exception as e:
        return {"error": {"code": -1, "message": f"Request failed: {type(e).__name__}: {str(e)}"}}


def format_graph_results(results: List[Dict[str, Any]], symbol: str, query_type: str) -> None:
    """Format and print graph navigation results."""
    console = Console() if RICH_AVAILABLE else None
    
    if not results:
        msg = f"No {query_type} found for symbol: {symbol}"
        if console:
            console.print(Panel(f"[yellow]{msg}[/yellow]", title="Symbol Graph"))
        else:
            print(msg)
        return
    
    if console:
        # Create a rich table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=3)
        table.add_column("Symbol", style="yellow")
        table.add_column("Path", style="cyan")
        table.add_column("Lines", style="magenta", width=12)
        if query_type in ("callers", "callees"):
            table.add_column("Hop", style="green", width=4)
        
        for idx, r in enumerate(results, 1):
            sym = r.get("symbol_path") or r.get("symbol") or "-"
            path = r.get("path", "")
            start = r.get("start_line", "?")
            end = r.get("end_line", "?")
            lines = f"{start}-{end}"
            
            row = [str(idx), sym, path, lines]
            if query_type in ("callers", "callees"):
                row.append(str(r.get("hop", 1)))
            table.add_row(*row)
        
        title = f"[bold cyan]{query_type.title()}[/bold cyan] of [yellow]{symbol}[/yellow] ({len(results)} found)"
        console.print(Panel(table, title=title))
    else:
        print(f"{query_type.title()} of {symbol}: {len(results)} found")
        for idx, r in enumerate(results, 1):
            path = r.get("path", "")
            start = r.get("start_line", "?")
            sym = r.get("symbol_path") or r.get("symbol") or ""
            print(f"  {idx}. {path}:{start} ({sym})")


def graph_command(args) -> int:
    """Execute graph command."""
    result = call_symbol_graph(
        symbol=args.symbol,
        query_type=args.query_type,
        limit=args.limit,
        depth=args.depth,
        language=args.language,
        under=args.under,
        repo=args.repo,
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
    
    # Handle suggestions for typos
    if result.get("suggestions"):
        console = Console() if RICH_AVAILABLE else None
        hint = result.get("hint", f"Did you mean: {', '.join(result['suggestions'])}?")
        if console:
            console.print(Panel(f"[yellow]{hint}[/yellow]", title="[bold yellow]Suggestions[/bold yellow]"))
        else:
            print(f"Hint: {hint}")
    
    results = result.get("results", [])
    format_graph_results(results, args.symbol, args.query_type)
    return 0


def _add_common_args(parser):
    """Add common arguments to graph subcommand parsers."""
    parser.add_argument("symbol", help="Symbol name to query")
    parser.add_argument("--limit", "-l", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--depth", "-d", type=int, default=1, help="Traversal depth (default: 1)")
    parser.add_argument("--language", help="Filter by programming language")
    parser.add_argument("--under", "-u", help="Filter by path prefix")
    parser.add_argument("--repo", "-r", help="Filter by repository name")
    parser.add_argument("--collection", "-c", help="Collection name")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")


def register_command(subparsers):
    """Register graph command and subcommands."""
    graph_parser = subparsers.add_parser(
        "graph",
        help="Navigate symbol relationships (callers, definitions, imports)",
        description="Query the symbol graph for code navigation",
    )

    graph_subs = graph_parser.add_subparsers(dest="graph_cmd", help="Graph query types")

    # callers subcommand
    callers_parser = graph_subs.add_parser("callers", help="Find who calls this symbol")
    _add_common_args(callers_parser)
    callers_parser.set_defaults(func=graph_command, query_type="callers")

    # callees subcommand
    callees_parser = graph_subs.add_parser("callees", help="Find what this symbol calls")
    _add_common_args(callees_parser)
    callees_parser.set_defaults(func=graph_command, query_type="callees")

    # definition subcommand
    def_parser = graph_subs.add_parser("definition", help="Find where symbol is defined")
    _add_common_args(def_parser)
    def_parser.set_defaults(func=graph_command, query_type="definition")

    # importers subcommand
    imp_parser = graph_subs.add_parser("importers", help="Find what imports this module/symbol")
    _add_common_args(imp_parser)
    imp_parser.set_defaults(func=graph_command, query_type="importers")

    # Default behavior
    graph_parser.set_defaults(func=lambda args: graph_parser.print_help() or 0)

