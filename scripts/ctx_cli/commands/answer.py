#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Answer command for Context-Engine CLI.

Usage:
    ctx answer <query> [OPTIONS]

Examples:
    ctx answer "how does the indexing system work?"
    ctx answer "explain the embedding pipeline" --budget 6000
    ctx answer "what are the caching strategies" --temperature 0.3 --expand
    ctx answer "how are queries ranked" --collection codebase --json
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


def parse_mcp_response(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse MCP JSON-RPC response and extract tool result.

    Supports:
      - FastMCP wrapper: result.content[0].json or result.content[0].text
      - Direct result: result.answer/citations
      - Already-parsed tool result (no jsonrpc wrapper)

    Args:
        response: Raw MCP JSON-RPC response or already-parsed result

    Returns:
        Parsed result data or None if error/no data
    """
    if not isinstance(response, dict):
        return None

    # JSON-RPC error response
    if "error" in response:
        return None

    # If this already looks like a parsed tool output, accept it
    if any(k in response for k in ("answer", "citations", "raw", "ok")) and "result" not in response:
        return response

    result = response.get("result", {})
    if not isinstance(result, dict):
        return None

    # Direct result (no content wrapper)
    if any(k in result for k in ("answer", "citations", "raw", "ok")) and "content" not in result:
        return result

    content = result.get("content", [])
    if not content or not isinstance(content, list):
        return None

    item = content[0] if content else {}
    if isinstance(item, dict) and "json" in item:
        return item["json"]

    text = item.get("text", "") if isinstance(item, dict) else ""
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


# Default configuration
DEFAULT_TIMEOUT = 60  # context_answer may take longer than search
DEFAULT_BUDGET = 4000
DEFAULT_TEMPERATURE = 0.2


def call_mcp_context_answer(
    query: str,
    budget_tokens: int = DEFAULT_BUDGET,
    temperature: float = DEFAULT_TEMPERATURE,
    expand: bool = False,
    collection: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Call MCP context_answer tool via MCPClient with session handshake.

    Args:
        query: Question to answer
        budget_tokens: Token budget for context retrieval
        temperature: Temperature for answer generation (0.0-1.0)
        expand: Enable query expansion for better retrieval
        collection: Collection name (defaults to env COLLECTION_NAME or "codebase")
        timeout: Request timeout in seconds

    Returns:
        Dict containing the parsed result
    """
    # Build parameters
    params = {
        "query": query,
        "budget_tokens": budget_tokens,
        "temperature": temperature,
    }

    if expand:
        params["expand"] = True

    # Only set collection if explicitly provided or in environment
    if collection:
        params["collection"] = collection
    elif os.environ.get("COLLECTION_NAME"):
        params["collection"] = os.environ["COLLECTION_NAME"]
    # Otherwise let the server auto-detect from workspace

    try:
        client = MCPClient(server="indexer", timeout=timeout)
        return client.call_tool("context_answer", **params)
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




def format_citation_plain(idx: int, citation: Dict[str, Any]) -> str:
    """Format a single citation as plain text.

    Args:
        idx: Citation index (1-based)
        citation: Citation data

    Returns:
        Formatted citation string
    """
    path = citation.get("path", "unknown")
    start = citation.get("start_line", "?")
    end = citation.get("end_line", "?")
    score = citation.get("score", 0.0)

    result = f"  {idx}. {path}"
    if start != "?" and end != "?":
        result += f":{start}-{end}"
    if score > 0:
        result += f" ({score:.2f})"

    return result


def format_answer_rich(
    answer: str,
    citations: List[Dict[str, Any]],
    query: str,
    console: Optional[Any] = None
) -> None:
    """Format and display answer using Rich.

    Args:
        answer: Generated answer text
        citations: List of source citations
        query: Original query
        console: Rich Console instance
    """
    if console is None:
        console = Console()

    # Display answer in a panel
    if answer:
        # Try to render as markdown for better formatting
        try:
            md = Markdown(answer)
            console.print(Panel(
                md,
                title="Answer",
                border_style="cyan",
                padding=(1, 2)
            ))
        except Exception:
            # Fallback to plain text
            console.print(Panel(
                answer,
                title="Answer",
                border_style="cyan",
                padding=(1, 2)
            ))
    else:
        console.print("[yellow]No answer generated[/yellow]")

    console.print()

    # Display citations
    if citations:
        console.print("[bold]Sources:[/bold]")
        for idx, citation in enumerate(citations, 1):
            path = citation.get("path", "unknown")
            start = citation.get("start_line", "?")
            end = citation.get("end_line", "?")
            score = citation.get("score", 0.0)

            citation_text = f"  [bold]{idx}.[/bold] {path}"
            if start != "?" and end != "?":
                citation_text += f":{start}-{end}"
            if score > 0:
                citation_text += f" [dim]({score:.2f})[/dim]"

            console.print(citation_text)
    else:
        console.print("[dim]No sources cited[/dim]")


def format_answer_plain(
    answer: str,
    citations: List[Dict[str, Any]],
    query: str
) -> str:
    """Format answer as plain text.

    Args:
        answer: Generated answer text
        citations: List of source citations
        query: Original query

    Returns:
        Formatted answer string
    """
    lines = []

    # Header
    separator = "=" * 60
    lines.append(separator)
    lines.append(f"Answer: {query}")
    lines.append(separator)
    lines.append("")

    # Answer
    if answer:
        lines.append(answer)
    else:
        lines.append("No answer generated")

    lines.append("")
    lines.append(separator)

    # Citations
    if citations:
        lines.append("Sources:")
        lines.append("")
        for idx, citation in enumerate(citations, 1):
            lines.append(format_citation_plain(idx, citation))
    else:
        lines.append("No sources cited")

    lines.append(separator)

    return "\n".join(lines)


def answer_command(
    query: str,
    budget: int = DEFAULT_BUDGET,
    temperature: float = DEFAULT_TEMPERATURE,
    expand: bool = False,
    json_output: bool = False,
    collection: Optional[str] = None,
) -> int:
    """Execute the answer command.

    Args:
        query: Question to answer
        budget: Token budget for context retrieval
        temperature: Temperature for answer generation
        expand: Enable query expansion
        json_output: Output raw JSON
        collection: Collection name

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Call MCP context_answer (MCPClient handles session handshake and parsing)
    data = call_mcp_context_answer(
        query=query,
        budget_tokens=budget,
        temperature=temperature,
        expand=expand,
        collection=collection,
    )

    # Handle errors (error can be a string or dict)
    if "error" in data:
        error = data["error"]
        # Handle both string and dict error formats
        if isinstance(error, str):
            error_msg = error
        else:
            error_msg = error.get("message", "Unknown error") if isinstance(error, dict) else str(error)

        # Check for common errors
        if "Connection refused" in str(error_msg) or "Connection failed" in str(error_msg):
            print("Error: Cannot connect to MCP indexer", file=sys.stderr)
            print("Make sure the indexer service is running on port 8003", file=sys.stderr)
        elif "timed out" in str(error_msg).lower() or "timeout" in str(error_msg).lower():
            print(f"Error: Request timed out after {DEFAULT_TIMEOUT}s", file=sys.stderr)
            print("Try reducing --budget or waiting for indexer to finish processing", file=sys.stderr)
        else:
            print(f"Error: {error_msg}", file=sys.stderr)

        return 1

    # Handle raw JSON output
    if json_output:
        print(json.dumps(data, indent=2))
        return 0

    # Extract answer and citations
    answer = data.get("answer", "")
    citations = data.get("citations", [])

    # Handle special case: raw text response
    if not answer and "raw" in data:
        answer = data["raw"]

    # Handle no answer
    if not answer and not citations:
        if RICH_AVAILABLE:
            console = Console()
            console.print(f"[yellow]No answer could be generated for \"{query}\"[/yellow]")
            console.print("[dim]Try rephrasing your question or using --expand for query expansion[/dim]")
        else:
            print(f"No answer could be generated for \"{query}\"")
            print("Try rephrasing your question or using --expand for query expansion")
        return 0

    # Format and display results
    if RICH_AVAILABLE and not json_output:
        console = Console()
        format_answer_rich(answer, citations, query, console)
    else:
        output = format_answer_plain(answer, citations, query)
        print(output)

    return 0


def run_answer(args):
    """Entry point for argparse command execution.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code
    """
    return answer_command(
        query=args.query,
        budget=args.budget,
        temperature=args.temperature,
        expand=args.expand,
        json_output=args.json,
        collection=args.collection,
    )


def register_command(subparsers):
    """Register the answer command with the CLI parser."""
    parser = subparsers.add_parser(
        "answer",
        help="Get natural language answer with citations",
        description="Ask a question about the codebase and get an AI-generated answer with source citations",
        epilog="""
Examples:
  ctx answer "how does the indexing system work?"
  ctx answer "explain the embedding pipeline" --budget 6000
  ctx answer "what are the caching strategies" --temperature 0.3 --expand
  ctx answer "how are queries ranked" --collection codebase --json
        """
    )

    parser.add_argument(
        "query",
        help="Question to answer about the codebase"
    )

    parser.add_argument(
        "-b", "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help=f"Token budget for context retrieval (default: {DEFAULT_BUDGET})"
    )

    parser.add_argument(
        "-t", "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"Temperature for answer generation, 0.0-1.0 (default: {DEFAULT_TEMPERATURE})"
    )

    parser.add_argument(
        "-e", "--expand",
        action="store_true",
        help="Enable query expansion for better retrieval (uses local LLM, slower)"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON response"
    )

    parser.add_argument(
        "-c", "--collection",
        help="Collection name (default: env COLLECTION_NAME or 'codebase')"
    )

    parser.set_defaults(func=run_answer)


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for standalone execution.

    Args:
        args: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="ctx answer",
        description="Get natural language answer with citations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ctx answer "how does the indexing system work?"
  ctx answer "explain the embedding pipeline" --budget 6000
  ctx answer "what are the caching strategies" --temperature 0.3 --expand
  ctx answer "how are queries ranked" --collection codebase --json
        """
    )

    parser.add_argument("query", help="Question to answer about the codebase")
    parser.add_argument("-b", "--budget", type=int, default=DEFAULT_BUDGET,
                       help=f"Token budget for context retrieval (default: {DEFAULT_BUDGET})")
    parser.add_argument("-t", "--temperature", type=float, default=DEFAULT_TEMPERATURE,
                       help=f"Temperature for generation (default: {DEFAULT_TEMPERATURE})")
    parser.add_argument("-e", "--expand", action="store_true",
                       help="Enable query expansion")
    parser.add_argument("--json", action="store_true",
                       help="Output raw JSON")
    parser.add_argument("-c", "--collection", help="Collection name")

    parsed_args = parser.parse_args(args)

    return answer_command(
        query=parsed_args.query,
        budget=parsed_args.budget,
        temperature=parsed_args.temperature,
        expand=parsed_args.expand,
        json_output=parsed_args.json,
        collection=parsed_args.collection,
    )


if __name__ == "__main__":
    sys.exit(main())
