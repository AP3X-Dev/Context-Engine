"""
Enhance command for ctx CLI - Context-aware prompt enhancement.

Retrieves relevant code context and enhances prompts using a local LLM decoder.
Works with both questions and commands/instructions.

This is a CLI wrapper around scripts/ctx.py functionality.
"""

import sys
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def _print(msg: str, error: bool = False) -> None:
    """Print with Rich if available, otherwise plain print."""
    if console:
        console.print(msg)
    else:
        import re
        plain = re.sub(r'\[/?[^\]]+\]', '', msg)
        print(plain, file=sys.stderr if error else sys.stdout)


def _ensure_ctx_importable():
    """Ensure scripts/ctx.py is importable."""
    scripts_dir = Path(__file__).resolve().parent.parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def enhance(
    query: str,
    language: Optional[str] = None,
    under: Optional[str] = None,
    limit: int = 5,
    detail: bool = False,
    unicorn: bool = False,
    context_lines: int = 0,
    rewrite_max_tokens: int = 320,
    no_stream: bool = False,
    raw: bool = False,
):
    """
    Enhance a prompt with relevant code context.

    Retrieves code context from the indexed codebase and uses a local LLM
    to rewrite the prompt with specific details, file references, and
    implementation guidance.

    Modes:
        Normal (default): Fast, single-pass enhancement
        Detail (--detail): Includes code snippets (slower but richer)
        Unicorn (--unicorn): Multi-pass enhancement for highest quality

    Examples:
        ctx enhance "how does hybrid search work?"
        ctx enhance "refactor the caching logic" --detail
        ctx enhance "what is ReFRAG?" --unicorn
        ctx enhance "explain indexing" --language python --under scripts/
    """
    _ensure_ctx_importable()

    try:
        # Import the core ctx.py module
        import ctx as ctx_module
    except ImportError as e:
        _print(f"[red]Error:[/red] Could not import ctx module: {e}", error=True)
        _print("[dim]Make sure scripts/ctx.py exists[/dim]")
        return 1

    # Build filter kwargs
    filters = {}
    if language:
        filters["language"] = language
    if under:
        filters["under"] = under
    if limit:
        filters["limit"] = limit
    if context_lines or detail:
        filters["context_lines"] = context_lines if context_lines else 1

    # Override environment for parameters
    import os
    if rewrite_max_tokens != 320:
        os.environ["CTX_REWRITE_MAX_TOKENS"] = str(rewrite_max_tokens)

    try:
        if unicorn:
            # Multi-pass unicorn mode
            if not raw and RICH_AVAILABLE:
                console.print(Panel.fit(
                    f"[bold cyan]Unicorn Mode[/bold cyan]\n"
                    f"[dim]Multi-pass enhancement for highest quality[/dim]",
                    border_style="magenta"
                ))

            result = ctx_module.enhance_unicorn(query, **filters)
        else:
            # Normal or detail mode
            if detail:
                filters["context_lines"] = filters.get("context_lines", 1)

            if not raw and RICH_AVAILABLE:
                mode = "Detail" if detail else "Normal"
                console.print(Panel.fit(
                    f"[bold cyan]{mode} Mode[/bold cyan]\n"
                    f"[dim]Enhancing prompt with code context...[/dim]",
                    border_style="cyan"
                ))

            result = ctx_module.enhance_prompt(query, **filters)

        # Output the result
        if raw:
            print(result)
        else:
            if RICH_AVAILABLE:
                console.print()
                console.print(Panel(
                    result,
                    title="Enhanced Prompt",
                    border_style="green"
                ))
            else:
                print("\n=== Enhanced Prompt ===")
                print(result)
                print()

        return 0

    except Exception as e:
        _print(f"[red]Error:[/red] Enhancement failed: {e}", error=True)
        return 1


def register_command(subparsers):
    """Register the enhance command with the CLI argument parser."""
    parser = subparsers.add_parser(
        "enhance",
        help="Enhance prompts with code context using local LLM",
        description="Retrieve relevant code context and enhance prompts using a local LLM decoder.\n\n"
                    "Works with both questions and commands/instructions. Outputs detailed,\n"
                    "context-aware prompts with file references and implementation guidance.",
        epilog="""
Modes:
  Normal (default)    Fast, single-pass enhancement
  Detail (--detail)   Includes code snippets (slower but richer)
  Unicorn (--unicorn) Multi-pass (2-3 passes) for highest quality

Examples:
  ctx enhance "how does hybrid search work?"
  ctx enhance "refactor the caching logic" --detail
  ctx enhance "what is ReFRAG?" --unicorn
  ctx enhance "explain indexing" --language python
  ctx enhance "add error handling" --under scripts/ --limit 10
  ctx enhance "fix the bug" --raw | llm  # Pipe to another LLM

Environment Variables:
  MCP_INDEXER_URL        Indexer endpoint (default: http://localhost:8003/mcp)
  DECODER_URL            LLM decoder endpoint
  USE_GPU_DECODER        Use GPU decoder on port 8081 (0/1)
  CTX_REWRITE_MAX_TOKENS Max tokens for rewrite (default: 320)
"""
    )

    parser.add_argument(
        "query",
        help="The prompt/question to enhance"
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--detail", "-d",
        action="store_true",
        help="Include code snippets (slower but richer context)"
    )
    mode_group.add_argument(
        "--unicorn", "-u",
        action="store_true",
        help="Multi-pass enhancement for highest quality"
    )

    # Filters
    parser.add_argument(
        "--language", "-l",
        help="Filter by programming language (e.g., python, typescript)"
    )
    parser.add_argument(
        "--under",
        help="Filter by path prefix (e.g., scripts/, src/)"
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=5,
        help="Maximum search results (default: 5)"
    )
    parser.add_argument(
        "--context-lines", "-c",
        type=int,
        default=0,
        help="Lines of context around matches (default: 0, --detail sets to 1)"
    )

    # Output options
    parser.add_argument(
        "--rewrite-max-tokens",
        type=int,
        default=320,
        help="Max tokens for LLM rewrite (default: 320)"
    )
    parser.add_argument(
        "--raw", "-r",
        action="store_true",
        help="Output raw text only (no panels, for piping)"
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming output"
    )

    def run_enhance(args):
        """Wrapper to call enhance function with argparse args."""
        return enhance(
            query=args.query,
            language=args.language,
            under=args.under,
            limit=args.limit,
            detail=args.detail,
            unicorn=args.unicorn,
            context_lines=args.context_lines,
            rewrite_max_tokens=args.rewrite_max_tokens,
            no_stream=args.no_stream,
            raw=args.raw,
        )

    parser.set_defaults(func=run_enhance)
