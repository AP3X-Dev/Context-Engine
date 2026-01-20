"""
Output formatting package.

Provides Rich console formatters for CLI output.
"""

from scripts.ctx_cli.output.formatters import (
    format_error,
    format_success,
    format_info,
    format_warning,
    format_search_results,
    format_answer_results,
)

__all__ = [
    "format_error",
    "format_success",
    "format_info",
    "format_warning",
    "format_search_results",
    "format_answer_results",
]
