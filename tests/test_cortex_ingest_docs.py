"""Tests for document ingestion pipelines (markdown, text, JSON)."""

import json

from scripts.cortex.ingest_docs import (
    _estimate_tokens,
    chunk_json,
    chunk_markdown,
    chunk_text,
)


# ------------------------------------------------------------------
# Markdown
# ------------------------------------------------------------------

def test_chunk_markdown_by_headings():
    """Markdown with 3 sections produces at least 3 chunks, each with heading."""
    md = (
        "# Introduction\n\nThis is the intro.\n\n"
        "## Details\n\nSome detail text here.\n\n"
        "### Sub-details\n\nEven more detail."
    )
    chunks = chunk_markdown(md)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert "heading" in chunk["metadata"]
        assert chunk["metadata"]["type"] == "markdown"


def test_chunk_markdown_respects_max_tokens():
    """A very long section is sub-split into multiple chunks."""
    long_body = " ".join(["word"] * 2000)
    md = f"# Big Section\n\n{long_body}"
    chunks = chunk_markdown(md, max_tokens=64)
    assert len(chunks) > 1
    for chunk in chunks:
        assert "part" in chunk["metadata"]
        assert chunk["metadata"]["heading"] == "# Big Section"


# ------------------------------------------------------------------
# Plain text
# ------------------------------------------------------------------

def test_chunk_text_by_paragraphs():
    """Three paragraphs produce exactly 3 chunks."""
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_text(text)
    assert len(chunks) == 3
    for i, chunk in enumerate(chunks, start=1):
        assert chunk["metadata"]["paragraph"] == i
        assert chunk["metadata"]["type"] == "text"


# ------------------------------------------------------------------
# JSON
# ------------------------------------------------------------------

def test_chunk_json_by_keys():
    """JSON with 2 top-level keys produces at least 2 chunks with key_path."""
    data = {"name": "Alice", "age": 30}
    chunks = chunk_json(json.dumps(data))
    assert len(chunks) >= 2
    key_paths = {c["metadata"]["key_path"] for c in chunks}
    assert "$.name" in key_paths
    assert "$.age" in key_paths
    for chunk in chunks:
        assert chunk["metadata"]["type"] == "json"


def test_chunk_json_invalid_falls_back():
    """Invalid JSON falls back to text chunking."""
    bad_json = "this is {not valid json at all"
    chunks = chunk_json(bad_json)
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk["metadata"]["type"] == "text"
