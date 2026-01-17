#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Search command for Context-Engine CLI.

Usage:
    ctx search <query> [OPTIONS]

Examples:
    ctx search "database connection"
    ctx search "auth handler" --language python --limit 5
    ctx search "cache logic" --under src/ --snippet
    ctx search "error handling" --compact --json
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


def call_mcp_search(
    query: str,
    limit: int = 10,
    language: Optional[str] = None,
    under: Optional[str] = None,
    include_snippet: bool = False,
    compact: bool = False,
    collection: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Call MCP repo_search tool via MCPClient with session handshake.

    Args:
        query: Search query
        limit: Maximum number of results
        language: Filter by programming language
        under: Filter by path prefix
        include_snippet: Include code snippets in results
        compact: Use compact output format
        collection: Collection name (defaults to env COLLECTION_NAME or "codebase")
        timeout: Request timeout in seconds

    Returns:
        Dict containing the search results
    """
    # Build parameters
    params = {
        "query": query,
        "limit": limit,
        "include_snippet": include_snippet,
        "compact": compact,
    }

    if language:
        params["language"] = language
    if under:
        params["under"] = under

    try:
        client = MCPClient(server="indexer", timeout=timeout)
        # Collection resolution order:
        # 1) explicit flag, 2) env COLLECTION_NAME, 3) ~/.ctxrc or ./.ctxrc (search.default_collection)
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
        return client.call_tool("repo_search", **params)
    except MCPError as e:
        return {
            "error": {
                "code": e.code,
                "message": str(e),
                "data": e.data
            }
        }
    except Exception as e:
        return {
            "error": {
                "code": -1,
                "message": f"Request failed: {type(e).__name__}: {str(e)}",
                "data": str(e)
            }
        }


def format_result_plain(idx: int, hit: Dict[str, Any], include_snippet: bool = False) -> str:
    """Format a single search result as plain text.

    Args:
        idx: Result index (1-based)
        hit: Result data
        include_snippet: Whether to include code snippet

    Returns:
        Formatted result string
    """
    path = hit.get("path", "unknown")
    start = hit.get("start_line", "?")
    end = hit.get("end_line", "?")
    score = hit.get("score", 0.0)
    language = hit.get("language", "")
    symbol = hit.get("symbol", "")
    snippet = hit.get("snippet", "").strip()

    # Build header
    header = f"{idx}. {path}"
    if start != "?" and end != "?":
        header += f":{start}-{end}"
    header += f" ({score:.2f})"

    # Add metadata
    if language or symbol:
        meta_parts = []
        if language:
            meta_parts.append(language)
        if symbol:
            meta_parts.append(symbol)
        header += f" [{', '.join(meta_parts)}]"

    lines = [header]

    # Add snippet if requested
    if include_snippet and snippet:
        for line in snippet.splitlines()[:10]:  # Limit to 10 lines
            lines.append(f"   {line}")

    return "\n".join(lines)


def format_results_rich(
    results: List[Dict[str, Any]],
    query: str,
    total: int,
    include_snippet: bool = False,
    console: Optional[Any] = None
) -> None:
    """Format and display search results using Rich.

    Args:
        results: List of search results
        query: Original search query
        total: Total number of results
        include_snippet: Whether to include code snippets
        console: Rich Console instance
    """
    if console is None:
        console = Console()

    # Display header panel
    header_text = f"{total} result{'s' if total != 1 else ''} for \"{query}\""
    console.print(Panel(header_text, style="bold cyan"))
    console.print()

    # Display each result
    for idx, hit in enumerate(results, 1):
        path = hit.get("path", "unknown")
        start = hit.get("start_line", "?")
        end = hit.get("end_line", "?")
        score = hit.get("score", 0.0)
        language = hit.get("language", "")
        symbol = hit.get("symbol", "")
        snippet = hit.get("snippet", "").strip()

        # Build result header
        header = f"[bold]{idx}.[/bold] {path}"
        if start != "?" and end != "?":
            header += f":{start}-{end}"
        header += f" [dim]({score:.2f})[/dim]"

        if symbol:
            header += f" [yellow]{symbol}[/yellow]"

        console.print(header)

        # Display snippet with syntax highlighting if requested
        if include_snippet and snippet:
            # Limit snippet to reasonable size
            snippet_lines = snippet.splitlines()[:15]
            snippet_text = "\n".join(snippet_lines)

            # Use language for syntax highlighting
            lang = language.lower() if language else "text"
            try:
                syntax = Syntax(
                    snippet_text,
                    lang,
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=True,
                    padding=(0, 2)
                )
                console.print(syntax)
            except Exception:
                # Fallback to plain text if syntax highlighting fails
                for line in snippet_lines:
                    console.print(f"   [dim]{line}[/dim]")

        console.print()  # Blank line between results


def format_results_plain(
    results: List[Dict[str, Any]],
    query: str,
    total: int,
    include_snippet: bool = False
) -> str:
    """Format search results as plain text.

    Args:
        results: List of search results
        query: Original search query
        total: Total number of results
        include_snippet: Whether to include code snippets

    Returns:
        Formatted results string
    """
    lines = []

    # Header
    separator = "=" * 60
    lines.append(separator)
    lines.append(f"{total} result{'s' if total != 1 else ''} for \"{query}\"")
    lines.append(separator)
    lines.append("")

    # Results
    for idx, hit in enumerate(results, 1):
        lines.append(format_result_plain(idx, hit, include_snippet))
        lines.append("")

    return "\n".join(lines)


def search_command(
    query: str,
    limit: int = 10,
    language: Optional[str] = None,
    under: Optional[str] = None,
    snippet: bool = False,
    compact: bool = False,
    json_output: bool = False,
    collection: Optional[str] = None,
) -> int:
    """Execute the search command.

    Args:
        query: Search query
        limit: Maximum number of results
        language: Filter by programming language
        under: Filter by path prefix
        snippet: Include code snippets
        compact: Use compact output
        json_output: Output raw JSON
        collection: Collection name

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Call MCP search (MCPClient handles session handshake and parsing)
    data = call_mcp_search(
        query=query,
        limit=limit,
        language=language,
        under=under,
        include_snippet=snippet,
        compact=compact,
        collection=collection,
    )

    # Handle errors
    if "error" in data:
        error = data["error"]
        error_msg = error.get("message", "Unknown error")

        # Check for common errors
        if "Connection failed" in error_msg or "Connection refused" in str(error_msg):
            print("Error: Cannot connect to MCP indexer", file=sys.stderr)
            print("Hint: Run 'ctx up' to start services, or 'ctx status' to diagnose", file=sys.stderr)
        else:
            print(f"Error: {error_msg}", file=sys.stderr)

        return 1

    # Handle raw JSON output
    if json_output:
        print(json.dumps(data, indent=2))
        return 0

    # Extract results
    results = data.get("results", [])
    total = data.get("total", len(results))

    # Handle no results
    if not results:
        if RICH_AVAILABLE:
            console = Console()
            console.print(f"[yellow]No results found for \"{query}\"[/yellow]")
        else:
            print(f"No results found for \"{query}\"")
        return 0

    # Format and display results
    if RICH_AVAILABLE and not json_output:
        console = Console()
        format_results_rich(results, query, total, snippet, console)
    else:
        output = format_results_plain(results, query, total, snippet)
        print(output)

    return 0


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for search command.

    Args:
        args: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="ctx search",
        description="Search the codebase using semantic search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ctx search "database connection"
  ctx search "auth handler" --language python --limit 5
  ctx search "cache logic" --under src/ --snippet
  ctx search "error handling" --compact --json
        """
    )

    parser.add_argument("query", help="Search query")
    parser.add_argument("-l", "--limit", type=int, default=10,
                       help="Maximum number of results (default: 10)")
    parser.add_argument("-L", "--language", help="Filter by programming language")
    parser.add_argument("-u", "--under", help="Filter by path prefix")
    parser.add_argument("-s", "--snippet", action="store_true",
                       help="Show code snippets")
    parser.add_argument("-c", "--compact", action="store_true",
                       help="Use compact output format")
    parser.add_argument("--json", action="store_true", dest="json_output",
                       help="Output raw JSON")
    parser.add_argument("--collection", help="Collection name (default: env COLLECTION_NAME)")

    parsed_args = parser.parse_args(args)

    return search_command(
        query=parsed_args.query,
        limit=parsed_args.limit,
        language=parsed_args.language,
        under=parsed_args.under,
        snippet=parsed_args.snippet,
        compact=parsed_args.compact,
        json_output=parsed_args.json_output,
        collection=parsed_args.collection,
    )


def search(
    query: str,
    limit: int = 10,
    language: Optional[str] = None,
    under: Optional[str] = None,
    snippet: bool = False,
    compact: bool = False,
    json_output: bool = False,
    collection: Optional[str] = None,
) -> None:
    """Search the codebase using semantic search.

    This is the Typer-compatible entry point for the CLI.

    Args:
        query: Search query
        limit: Maximum number of results (default: 10)
        language: Filter by programming language
        under: Filter by path prefix
        snippet: Show code snippets
        compact: Use compact output format
        json_output: Output raw JSON
        collection: Collection name (default: env COLLECTION_NAME)
    """
    exit_code = search_command(
        query=query,
        limit=limit,
        language=language,
        under=under,
        snippet=snippet,
        compact=compact,
        json_output=json_output,
        collection=collection,
    )
    if exit_code != 0:
        sys.exit(exit_code)


def run_search(args) -> int:
    """Run search command from argparse args."""
    return search_command(
        query=args.query,
        limit=args.limit,
        language=args.language,
        under=args.under,
        snippet=args.snippet,
        compact=args.compact,
        json_output=args.json_output,
        collection=args.collection,
    )


def register_command(subparsers):
    """Register the search command with the CLI parser."""
    parser = subparsers.add_parser(
        "search",
        help="Search the codebase using semantic search",
        description="Search for code using semantic search with hybrid ranking",
        formatter_class=__import__('argparse').RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ctx search "database connection"
  ctx search "auth handler" --language python --limit 5
  ctx search "cache logic" --under src/ --snippet
  ctx search "error handling" --compact --json
        """
    )

    parser.add_argument("query", help="Search query")
    parser.add_argument("-l", "--limit", type=int, default=10,
                        help="Maximum number of results (default: 10)")
    parser.add_argument("-L", "--language",
                        help="Filter by programming language")
    parser.add_argument("-u", "--under",
                        help="Filter by path prefix")
    parser.add_argument("-s", "--snippet", action="store_true",
                        help="Show code snippets")
    parser.add_argument("-c", "--compact", action="store_true",
                        help="Use compact output format")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output raw JSON")
    parser.add_argument("--collection",
                        help="Collection name (default: env COLLECTION_NAME)")

    parser.set_defaults(func=run_search)


if __name__ == "__main__":
    sys.exit(main())
