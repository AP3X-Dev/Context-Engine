"""
Search commands.

Commands for semantic code search and natural language answers.
"""

import typer
from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from scripts.ctx_cli.utils.mcp_client import MCPClient
from scripts.ctx_cli.output.formatters import (
    format_error,
    format_success,
    format_search_results,
    format_answer_results,
)

console = Console()


def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(
        5,
        "--limit",
        "-n",
        help="Maximum number of results",
    ),
    language: Optional[str] = typer.Option(
        None,
        "--language",
        "-l",
        help="Filter by programming language",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Filter by file path prefix",
    ),
    symbol: Optional[str] = typer.Option(
        None,
        "--symbol",
        "-s",
        help="Filter by symbol name",
    ),
    compact: bool = typer.Option(
        False,
        "--compact",
        "-c",
        help="Compact output (less detail)",
    ),
    snippet: bool = typer.Option(
        True,
        "--snippet/--no-snippet",
        help="Include code snippets in results",
    ),
    output_format: str = typer.Option(
        "json",
        "--format",
        "-f",
        help="Output format: json or toon",
    ),
):
    """
    Search codebase semantically.

    Examples:
        ctx search "authentication patterns"
        ctx search "database connection" --limit 10
        ctx search "cache" -l python --compact
        ctx search "getUserProfile" --symbol
    """
    try:
        client = MCPClient(server="indexer")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Searching for '{query}'...", total=None)

            params = {
                "query": query,
                "limit": limit,
                "compact": compact,
                "include_snippet": snippet,
                "output_format": output_format,
            }

            if language:
                params["language"] = language
            if path:
                params["under"] = path
            if symbol:
                params["symbol"] = symbol

            result = client.call_tool("repo_search", **params)
            progress.update(task, completed=True)

        if result.get("ok"):
            results = result.get("results", [])
            console.print(
                format_search_results(
                    results=results,
                    query=query,
                    total=result.get("total", len(results)),
                    compact=compact,
                )
            )
        else:
            error_msg = result.get("error", "Unknown error")
            console.print(format_error(f"Search failed: {error_msg}"))
            raise typer.Exit(code=1)

    except Exception as e:
        console.print(format_error(f"Error: {e}"))
        raise typer.Exit(code=1)


def answer(
    query: str = typer.Argument(..., help="Question to answer"),
    budget: int = typer.Option(
        4000,
        "--budget",
        "-b",
        help="Token budget for context",
    ),
    temperature: float = typer.Option(
        0.2,
        "--temperature",
        "-t",
        help="LLM temperature (0.0-1.0)",
    ),
    expand: bool = typer.Option(
        False,
        "--expand",
        "-e",
        help="Use query expansion for better results",
    ),
    stream: bool = typer.Option(
        False,
        "--stream",
        "-s",
        help="Stream response in real-time",
    ),
):
    """
    Get natural language answer with citations.

    Examples:
        ctx answer "How does authentication work?"
        ctx answer "What are the main database models?" --budget 8000
        ctx answer "Explain the caching strategy" --expand
    """
    try:
        client = MCPClient(server="indexer")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Generating answer...", total=None)

            params = {
                "query": query,
                "budget_tokens": budget,
                "temperature": temperature,
                "expand": expand,
                "stream": stream,
            }

            result = client.call_tool("context_answer", **params)
            progress.update(task, completed=True)

        if result.get("ok"):
            console.print(
                format_answer_results(
                    answer=result.get("answer", ""),
                    citations=result.get("citations", []),
                    query=query,
                )
            )
        else:
            error_msg = result.get("error", "Unknown error")
            console.print(format_error(f"Answer generation failed: {error_msg}"))
            raise typer.Exit(code=1)

    except Exception as e:
        console.print(format_error(f"Error: {e}"))
        raise typer.Exit(code=1)
