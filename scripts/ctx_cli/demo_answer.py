#!/usr/bin/env python3
"""
Demo script showing answer command output formats.

This demonstrates what the output looks like without needing the MCP server running.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ctx_cli.commands.answer import (
    format_answer_rich,
    format_answer_plain,
)

# Mock answer and citations
MOCK_ANSWER = """The indexing system in Context-Engine works by:

1. **Scanning files** in the workspace using file system watchers
2. **Parsing code** into chunks using AST (Abstract Syntax Tree) analysis
3. **Generating embeddings** via the configured model (e.g., BAAI/bge-small-en-v1.5)
4. **Storing vectors** in Qdrant with metadata (file path, language, symbols)

Key components:
- `ingest_code.py` - Main entry point for indexing
- `embedder.py` - Handles embedding generation
- `chunk_processor.py` - Splits code into semantic chunks

The system uses **hybrid search** combining:
- Dense semantic vectors (cosine similarity)
- Lexical BM25 scoring
- Neural reranking (ONNX model)"""

MOCK_CITATIONS = [
    {
        "path": "scripts/ingest_code.py",
        "start_line": 45,
        "end_line": 89,
        "score": 0.94
    },
    {
        "path": "scripts/embedder.py",
        "start_line": 12,
        "end_line": 56,
        "score": 0.88
    },
    {
        "path": "docs/INDEXING.md",
        "start_line": 1,
        "end_line": 30,
        "score": 0.82
    },
    {
        "path": "scripts/chunk_processor.py",
        "start_line": 78,
        "end_line": 120,
        "score": 0.79
    }
]

def demo_rich_output():
    """Demonstrate Rich formatted output."""
    print("\n" + "="*60)
    print("DEMO: Rich Formatted Output")
    print("="*60 + "\n")

    try:
        from rich.console import Console
        console = Console()
        format_answer_rich(
            answer=MOCK_ANSWER,
            citations=MOCK_CITATIONS,
            query="how does the indexing system work?",
            console=console
        )
    except ImportError:
        print("Rich library not available - showing plain text instead")
        demo_plain_output()


def demo_plain_output():
    """Demonstrate plain text output."""
    print("\n" + "="*60)
    print("DEMO: Plain Text Output")
    print("="*60 + "\n")

    output = format_answer_plain(
        answer=MOCK_ANSWER,
        citations=MOCK_CITATIONS,
        query="how does the indexing system work?"
    )
    print(output)


def demo_json_output():
    """Demonstrate JSON output."""
    import json

    print("\n" + "="*60)
    print("DEMO: JSON Output")
    print("="*60 + "\n")

    data = {
        "answer": MOCK_ANSWER,
        "citations": MOCK_CITATIONS,
        "query": "how does the indexing system work?"
    }
    print(json.dumps(data, indent=2))


def demo_no_answer():
    """Demonstrate output when no answer is available."""
    print("\n" + "="*60)
    print("DEMO: No Answer Available")
    print("="*60 + "\n")

    try:
        from rich.console import Console
        console = Console()
        format_answer_rich(
            answer="",
            citations=[],
            query="how does the flux capacitor work?",
            console=console
        )
    except ImportError:
        output = format_answer_plain(
            answer="",
            citations=[],
            query="how does the flux capacitor work?"
        )
        print(output)


if __name__ == "__main__":
    print("Context-Engine CLI Answer Command - Output Format Demos")
    print("="*60)

    demo_rich_output()
    demo_plain_output()
    demo_json_output()
    demo_no_answer()

    print("\n" + "="*60)
    print("Demo complete!")
    print("="*60 + "\n")
