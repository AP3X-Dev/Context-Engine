"""
Centralized UI helpers for ctx CLI.

Provides consistent Rich/plain text output across all commands.
"""

import re
import sys
from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Singleton console instance
_console: Optional["Console"] = None


def get_console() -> Optional["Console"]:
    """Get the Rich console instance (or None if Rich is unavailable)."""
    global _console
    if RICH_AVAILABLE and _console is None:
        _console = Console()
    return _console


def strip_rich_markup(text: str) -> str:
    """Remove Rich markup tags from text for plain output."""
    return re.sub(r'\[/?[^\]]+\]', '', text)


def print_msg(msg: str, error: bool = False) -> None:
    """Print a message with Rich formatting if available, otherwise plain."""
    console = get_console()
    if console:
        console.print(msg, file=sys.stderr if error else sys.stdout)
    else:
        plain = strip_rich_markup(msg)
        print(plain, file=sys.stderr if error else sys.stdout)


def print_error(msg: str) -> None:
    """Print an error message."""
    print_msg(f"[red]Error:[/red] {msg}", error=True)


def print_warning(msg: str) -> None:
    """Print a warning message."""
    print_msg(f"[yellow]Warning:[/yellow] {msg}")


def print_success(msg: str) -> None:
    """Print a success message."""
    print_msg(f"[green]✓[/green] {msg}")


def print_info(msg: str) -> None:
    """Print an info message."""
    print_msg(f"[cyan]{msg}[/cyan]")


def print_dim(msg: str) -> None:
    """Print a dimmed/secondary message."""
    print_msg(f"[dim]{msg}[/dim]")


def print_panel(
    content: str,
    title: str = "",
    border_style: str = "cyan"
) -> None:
    """Print a panel with Rich if available, otherwise ASCII box."""
    console = get_console()
    if console and RICH_AVAILABLE:
        console.print(Panel(content, title=title, border_style=border_style))
    else:
        plain = strip_rich_markup(content)
        width = 50
        print("")
        if title:
            print(f"┌─ {title} " + "─" * (width - len(title) - 4) + "┐")
        else:
            print("┌" + "─" * width + "┐")
        for line in plain.split("\n"):
            # Truncate long lines
            if len(line) > width - 4:
                line = line[:width - 7] + "..."
            print(f"│ {line.ljust(width - 2)} │")
        print("└" + "─" * width + "┘")
        print("")


def print_syntax(
    code: str,
    language: str = "text",
    line_numbers: bool = False
) -> None:
    """Print code with syntax highlighting if Rich is available."""
    console = get_console()
    if console and RICH_AVAILABLE:
        syntax = Syntax(
            code,
            language,
            theme="monokai",
            line_numbers=line_numbers,
            word_wrap=True
        )
        console.print(syntax)
    else:
        # Plain output with indentation
        for line in code.split("\n"):
            print(f"  {line}")


def create_table(title: str = "", show_header: bool = True) -> Optional["Table"]:
    """Create a Rich table if available, otherwise return None."""
    if RICH_AVAILABLE:
        return Table(title=title, show_header=show_header)
    return None


def print_table(table: Optional["Table"]) -> None:
    """Print a Rich table if available."""
    console = get_console()
    if console and table:
        console.print(table)
