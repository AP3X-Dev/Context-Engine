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
from scripts.ctx_cli.utils.config import resolve_collection, is_neo4j_enabled

# Lazy import for graph backfill (avoids loading qdrant_client unless needed)
_graph_backfill_tick = None


def _get_graph_backfill_tick():
    """Lazy load graph_backfill_tick to avoid import overhead."""
    global _graph_backfill_tick
    if _graph_backfill_tick is None:
        from scripts.ingest.pipeline import graph_backfill_tick
        _graph_backfill_tick = graph_backfill_tick
    return _graph_backfill_tick


def call_graph_backfill(
    collection: Optional[str] = None,
    repo: Optional[str] = None,
    max_points: int = 1000,
) -> Dict[str, Any]:
    """Call graph_backfill_tick directly (no MCP, connects to Qdrant from host)."""
    import os

    try:
        from qdrant_client import QdrantClient

        # Resolve collection from env or arg
        coll = collection or os.environ.get("COLLECTION_NAME", "codebase")

        # Connect to Qdrant (localhost for CLI running on host)
        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        client = QdrantClient(url=qdrant_url)

        # Get the backfill function
        backfill_tick = _get_graph_backfill_tick()

        # Run backfill
        processed = backfill_tick(
            client=client,
            collection=coll,
            repo_name=repo,
            max_points=max_points,
        )

        return {
            "ok": True,
            "processed": processed,
            "collection": coll,
            "repo": repo,
        }

    except ImportError as e:
        return {"ok": False, "error": f"Missing dependency: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def backfill_command(args) -> int:
    """Execute graph backfill command."""
    console = Console() if RICH_AVAILABLE else None

    # Show graph backend status
    if is_neo4j_enabled():
        if console:
            console.print(Panel("[cyan]Neo4j graph backend enabled[/cyan]", title="Graph Backend"))
        else:
            print("Graph backend: Neo4j (NEO4J_GRAPH=1)")
    else:
        if console:
            console.print(Panel("[yellow]Using Qdrant graph backend[/yellow]\n[dim]Set NEO4J_GRAPH=1 to use Neo4j[/dim]", title="Graph Backend"))
        else:
            print("Graph backend: Qdrant (set NEO4J_GRAPH=1 for Neo4j)")

    total_processed = 0
    iterations = 0
    max_iterations = args.iterations if hasattr(args, 'iterations') else 10

    if console:
        console.print(f"\n[dim]Running backfill (max {args.max_points} points per iteration, up to {max_iterations} iterations)...[/dim]\n")
    else:
        print(f"Running backfill (max {args.max_points} points per iteration)...")

    while iterations < max_iterations:
        iterations += 1
        result = call_graph_backfill(
            collection=args.collection,
            repo=args.repo,
            max_points=args.max_points,
        )

        if args.json:
            print(json.dumps(result, indent=2))
            if not result.get("ok"):
                return 1
            if result.get("processed", 0) == 0:
                break
            total_processed += result.get("processed", 0)
            continue

        if "error" in result or not result.get("ok"):
            msg = result.get("error", {}).get("message") if isinstance(result.get("error"), dict) else result.get("error", "Unknown error")
            if console:
                console.print(Panel(f"[red]{msg}[/red]", title="[bold red]Error[/bold red]"))
            else:
                print(f"Error: {msg}", file=sys.stderr)
            return 1

        processed = result.get("processed", 0)
        total_processed += processed

        if console:
            console.print(f"  [green]✓[/green] Iteration {iterations}: processed {processed} points")
        else:
            print(f"  Iteration {iterations}: processed {processed} points")

        # Stop if no more points to process
        if processed == 0:
            break

    # Summary
    if console:
        console.print(Panel(
            f"[green]Backfill complete[/green]\n\n"
            f"Total processed: [cyan]{total_processed}[/cyan] points\n"
            f"Iterations: [cyan]{iterations}[/cyan]",
            title="[bold green]Summary[/bold green]"
        ))
    else:
        print(f"\nBackfill complete: {total_processed} points in {iterations} iterations")

    return 0


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
        # Use centralized collection resolution
        resolved = resolve_collection(explicit=collection, config=client.config)
        if resolved:
            params["collection"] = resolved
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

    # backfill subcommand
    backfill_parser = graph_subs.add_parser(
        "backfill",
        help="Populate graph edges from existing indexed code",
        description=(
            "Backfill graph edges from existing indexed points. "
            "Use after enabling NEO4J_GRAPH=1 or to rebuild graph from scratch."
        )
    )
    backfill_parser.add_argument("--collection", "-c", help="Collection name (default: COLLECTION_NAME)")
    backfill_parser.add_argument("--repo", "-r", help="Filter by repository name")
    backfill_parser.add_argument("--max-points", type=int, default=1000, help="Max points per iteration (default: 1000)")
    backfill_parser.add_argument("--iterations", type=int, default=10, help="Max iterations (default: 10)")
    backfill_parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    backfill_parser.set_defaults(func=backfill_command)

    # Default behavior
    graph_parser.set_defaults(func=lambda args: graph_parser.print_help() or 0)

