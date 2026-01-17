"""
Rich console formatters for CLI output.

Provides consistent formatting functions for different types of output.
"""

from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table


def format_error(message: str) -> Panel:
    """
    Format an error message.

    Args:
        message: Error message text

    Returns:
        Rich Panel with error styling
    """
    return Panel(
        f"[red]{message}[/red]",
        title="[bold red]Error[/bold red]",
        border_style="red",
    )


def format_success(message: str) -> Panel:
    """
    Format a success message.

    Args:
        message: Success message text

    Returns:
        Rich Panel with success styling
    """
    return Panel(
        f"[green]{message}[/green]",
        title="[bold green]Success[/bold green]",
        border_style="green",
    )


def format_info(message: str) -> Panel:
    """
    Format an informational message.

    Args:
        message: Info message text

    Returns:
        Rich Panel with info styling
    """
    return Panel(
        f"[cyan]{message}[/cyan]",
        title="[bold cyan]Info[/bold cyan]",
        border_style="cyan",
    )


def format_warning(message: str) -> Panel:
    """
    Format a warning message.

    Args:
        message: Warning message text

    Returns:
        Rich Panel with warning styling
    """
    return Panel(
        f"[yellow]{message}[/yellow]",
        title="[bold yellow]Warning[/bold yellow]",
        border_style="yellow",
    )


def format_search_results(
    results: List[Dict[str, Any]],
    query: str,
    total: int,
    compact: bool = False,
) -> Panel:
    """
    Format search results with Rich styling.

    Args:
        results: List of search result dictionaries
        query: Original search query
        total: Total number of results
        compact: Use compact formatting

    Returns:
        Rich Panel containing formatted results
    """
    console = Console()

    if not results:
        return Panel(
            f"[yellow]No results found for query: {query}[/yellow]",
            title="[bold cyan]Search Results[/bold cyan]",
            border_style="cyan",
        )

    # Create table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("File", style="cyan")
    table.add_column("Lines", style="magenta", width=10)
    table.add_column("Score", style="green", width=6)

    if not compact:
        table.add_column("Symbol", style="yellow")
        table.add_column("Language", style="blue", width=10)

    # Add rows
    for idx, result in enumerate(results, 1):
        path = result.get("path", "unknown")
        start_line = result.get("start_line", "?")
        end_line = result.get("end_line", "?")
        score = result.get("score", 0.0)
        symbol = result.get("symbol", "")
        language = result.get("language", "")

        lines = f"{start_line}-{end_line}" if start_line != "?" else "?"

        row = [
            str(idx),
            path,
            lines,
            f"{score:.2f}",
        ]

        if not compact:
            row.extend([symbol or "-", language or "-"])

        table.add_row(*row)

    # Create panel with table
    from io import StringIO
    string_io = StringIO()
    temp_console = Console(file=string_io, force_terminal=True)
    temp_console.print(table)
    table_str = string_io.getvalue()

    return Panel(
        table_str,
        title=f"[bold cyan]Search Results[/bold cyan] [dim]({total} found for '{query}')[/dim]",
        border_style="cyan",
    )


def format_answer_results(
    answer: str,
    citations: List[Dict[str, Any]],
    query: str,
) -> Panel:
    """
    Format context_answer results with citations.

    Args:
        answer: Generated answer text
        citations: List of citation dictionaries
        query: Original query

    Returns:
        Rich Panel containing formatted answer and citations
    """
    console = Console()

    # Format answer
    content_parts = []

    if answer:
        content_parts.append("[bold]Answer:[/bold]\n")
        content_parts.append(answer)
        content_parts.append("\n")

    # Format citations
    if citations:
        content_parts.append("\n[bold]Citations:[/bold]\n")

        for idx, citation in enumerate(citations, 1):
            path = citation.get("path", "unknown")
            lines = citation.get("lines", "?")
            score = citation.get("score", 0.0)

            content_parts.append(
                f"[dim]{idx}.[/dim] [cyan]{path}[/cyan]:{lines} "
                f"[dim](score: {score:.2f})[/dim]\n"
            )

    content = "".join(content_parts)

    return Panel(
        content,
        title=f"[bold green]Answer[/bold green] [dim]for '{query}'[/dim]",
        border_style="green",
    )


def format_code_snippet(
    code: str,
    language: str = "python",
    line_numbers: bool = True,
) -> Syntax:
    """
    Format code snippet with syntax highlighting.

    Args:
        code: Code text
        language: Programming language for syntax highlighting
        line_numbers: Whether to show line numbers

    Returns:
        Rich Syntax object
    """
    return Syntax(
        code,
        language,
        theme="monokai",
        line_numbers=line_numbers,
        word_wrap=True,
    )


def format_table(
    headers: List[str],
    rows: List[List[str]],
    title: Optional[str] = None,
) -> Table:
    """
    Create a formatted Rich table.

    Args:
        headers: Column headers
        rows: Table rows
        title: Optional table title

    Returns:
        Rich Table object
    """
    table = Table(show_header=True, header_style="bold cyan", title=title)

    for header in headers:
        table.add_column(header)

    for row in rows:
        table.add_row(*row)

    return table
