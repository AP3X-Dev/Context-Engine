#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Pattern search command for Context-Engine CLI.

Usage:
    ctx pattern "for i in range(3): try: ... except: time.sleep(2**i)"
    ctx pattern "retry with exponential backoff" --mode description
    ctx pattern "if err != nil { return err }" --language go

Examples:
    ctx pattern "try: ... except Exception: pass" --snippet
    ctx pattern "error handling with retry" --mode description --limit 15
    ctx pattern "resource cleanup pattern" --target-languages python,go
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


def call_pattern_search(
    query: str,
    query_mode: str = "auto",
    limit: int = 10,
    min_score: float = 0.3,
    language: Optional[str] = None,
    target_languages: Optional[List[str]] = None,
    include_snippet: bool = False,
    collection: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Call pattern_search MCP tool."""
    params = {
        "query": query,
        "query_mode": query_mode,
        "limit": limit,
        "min_score": min_score,
        "include_snippet": include_snippet,
    }
    
    if language:
        params["language"] = language
    if target_languages:
        params["target_languages"] = target_languages
    
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
        return client.call_tool("pattern_search", **params)
    except MCPError as e:
        return {"error": {"code": e.code, "message": str(e), "data": e.data}}
    except Exception as e:
        return {"error": {"code": -1, "message": f"Request failed: {type(e).__name__}: {str(e)}"}}


def format_pattern_results(results: List[Dict[str, Any]], query: str, include_snippet: bool) -> None:
    """Format and print pattern search results."""
    console = Console() if RICH_AVAILABLE else None
    
    if not results:
        msg = f"No patterns found matching: {query[:50]}..."
        if console:
            console.print(Panel(f"[yellow]{msg}[/yellow]", title="Pattern Search"))
        else:
            print(msg)
        return
    
    if console:
        table = Table(show_header=True, header_style="bold green")
        table.add_column("#", style="dim", width=3)
        table.add_column("Path", style="cyan")
        table.add_column("Lines", style="magenta", width=12)
        table.add_column("Language", style="blue", width=12)
        table.add_column("Score", style="green", width=8)
        
        for idx, r in enumerate(results, 1):
            path = r.get("path", "")
            start = r.get("start_line", "?")
            end = r.get("end_line", "?")
            lang = r.get("language", "-")
            score = r.get("score", 0.0)
            table.add_row(str(idx), path, f"{start}-{end}", lang, f"{score:.2f}")
        
        console.print(Panel(table, title=f"[bold green]Pattern Matches[/bold green] ({len(results)} found)"))
        
        # Show snippets if requested
        if include_snippet:
            for idx, r in enumerate(results[:3], 1):  # Show top 3 snippets
                snippet = r.get("snippet", "")
                if snippet:
                    lang = r.get("language", "text")
                    path = r.get("path", "")
                    console.print(f"\n[dim]#{idx} {path}[/dim]")
                    console.print(Syntax(snippet, lang, theme="monokai", line_numbers=True))
    else:
        print(f"Found {len(results)} pattern matches")
        for idx, r in enumerate(results, 1):
            path = r.get("path", "")
            start = r.get("start_line", "?")
            score = r.get("score", 0.0)
            print(f"  {idx}. {path}:{start} (score: {score:.2f})")


def pattern_command(args) -> int:
    """Execute pattern search command."""
    target_langs = None
    if args.target_languages:
        target_langs = [l.strip() for l in args.target_languages.split(",")]
    
    result = call_pattern_search(
        query=args.query,
        query_mode=args.mode,
        limit=args.limit,
        min_score=args.min_score,
        language=args.language,
        target_languages=target_langs,
        include_snippet=args.snippet,
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
    format_pattern_results(results, args.query, args.snippet)
    return 0


def register_command(subparsers):
    """Register pattern search command."""
    parser = subparsers.add_parser(
        "pattern",
        help="Find structurally similar code patterns",
        description="Search for code patterns using structural similarity or natural language descriptions",
        epilog="""
Examples:
  ctx pattern "for i in range(3): try: ... except: time.sleep(2**i)"
  ctx pattern "retry with exponential backoff" --mode description
  ctx pattern "if err != nil { return err }" --language go --snippet
        """,
        formatter_class=__import__('argparse').RawDescriptionHelpFormatter,
    )

    parser.add_argument("query", help="Code pattern or natural language description")
    parser.add_argument(
        "--mode", "-m",
        choices=["auto", "code", "description"],
        default="auto",
        help="Query mode: auto (detect), code, or description (default: auto)"
    )
    parser.add_argument("--limit", "-l", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--min-score", type=float, default=0.3, help="Min similarity score (default: 0.3)")
    parser.add_argument("--language", help="Language hint for code patterns")
    parser.add_argument("--target-languages", help="Filter target languages (comma-separated)")
    parser.add_argument("--snippet", "-s", action="store_true", help="Include code snippets")
    parser.add_argument("--collection", "-c", help="Collection name")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    parser.set_defaults(func=pattern_command)

