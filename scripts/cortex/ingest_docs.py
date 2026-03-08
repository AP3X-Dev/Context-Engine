"""Document ingestion pipelines for non-code data types.

Chunking strategies for markdown, plain text, and JSON content.
Each public function returns List[Dict[str, Any]] where each dict
has "text" (str) and "metadata" (dict).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1.3 tokens per whitespace-delimited word."""
    return int(len(text.split()) * 1.3)


def _split_into_token_chunks(text: str, max_tokens: int) -> List[str]:
    """Split *text* into consecutive chunks that each fit within *max_tokens*.

    The split boundary is on whitespace so words are never broken.
    """
    words = text.split()
    chunks: List[str] = []
    current: List[str] = []
    for word in words:
        candidate = current + [word]
        if _estimate_tokens(" ".join(candidate)) > max_tokens and current:
            chunks.append(" ".join(current))
            current = [word]
        else:
            current = candidate
    if current:
        chunks.append(" ".join(current))
    return chunks


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"(?m)^(#{1,6}\s+.+)$")


def chunk_markdown(content: str, max_tokens: int = 512) -> List[Dict[str, Any]]:
    """Split markdown by headings, sub-splitting oversized sections."""
    parts = _HEADING_RE.split(content)
    # parts alternates between text-before/between headings and heading lines.
    # Index 0 is text before the first heading (if any), then pairs of
    # (heading, body) follow.

    sections: List[tuple] = []  # (heading | None, body)
    idx = 0
    # Text before the first heading
    if parts and not _HEADING_RE.match(parts[0]):
        preamble = parts[0].strip()
        if preamble:
            sections.append((None, preamble))
        idx = 1

    while idx < len(parts):
        heading = parts[idx].strip() if idx < len(parts) else None
        body = parts[idx + 1].strip() if idx + 1 < len(parts) else ""
        sections.append((heading, body))
        idx += 2

    chunks: List[Dict[str, Any]] = []
    for heading, body in sections:
        heading_label = heading if heading else "(no heading)"
        section_text = f"{heading}\n\n{body}" if heading else body
        section_text = section_text.strip()

        if not section_text:
            continue

        if _estimate_tokens(section_text) <= max_tokens:
            chunks.append({
                "text": section_text,
                "metadata": {"heading": heading_label, "type": "markdown"},
            })
        else:
            sub_chunks = _split_into_token_chunks(section_text, max_tokens)
            for part_idx, sub in enumerate(sub_chunks, start=1):
                chunks.append({
                    "text": sub,
                    "metadata": {
                        "heading": heading_label,
                        "type": "markdown",
                        "part": part_idx,
                    },
                })

    return chunks


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def chunk_text(content: str, max_tokens: int = 512) -> List[Dict[str, Any]]:
    """Split plain text by paragraphs (double newline), sub-splitting if needed."""
    paragraphs = [p.strip() for p in re.split(r"\n\n+", content) if p.strip()]

    chunks: List[Dict[str, Any]] = []
    para_num = 0
    for para in paragraphs:
        para_num += 1
        if _estimate_tokens(para) <= max_tokens:
            chunks.append({
                "text": para,
                "metadata": {"paragraph": para_num, "type": "text"},
            })
        else:
            sub_chunks = _split_into_token_chunks(para, max_tokens)
            for sub in sub_chunks:
                chunks.append({
                    "text": sub,
                    "metadata": {"paragraph": para_num, "type": "text"},
                })

    return chunks


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def chunk_json(content: str, max_tokens: int = 512) -> List[Dict[str, Any]]:
    """Split JSON by top-level keys; fall back to chunk_text on parse failure."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return chunk_text(content, max_tokens)

    if not isinstance(data, dict):
        # Non-object JSON (e.g. array) — serialize and treat as text
        return chunk_text(json.dumps(data, indent=2), max_tokens)

    chunks: List[Dict[str, Any]] = []
    for key, value in data.items():
        fragment = json.dumps({key: value}, indent=2)
        key_path = f"$.{key}"

        if _estimate_tokens(fragment) <= max_tokens:
            chunks.append({
                "text": fragment,
                "metadata": {"key_path": key_path, "type": "json"},
            })
        else:
            sub_chunks = _split_into_token_chunks(fragment, max_tokens)
            for sub in sub_chunks:
                chunks.append({
                    "text": sub,
                    "metadata": {"key_path": key_path, "type": "json"},
                })

    return chunks
