"""High-performance chunk deduplication with O(n log n) complexity.

Two-stage deduplication:
1. Exact content matching via hash table (O(n))
2. Substring detection via sorted interval scan (O(n log n))

Ported from ChunkHound to Context-Engine.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Sequence, TypeVar

import xxhash

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=dict)

# Specificity ranking (higher = more specific, keep over lower)
CONCEPT_SPECIFICITY = {
    # Context-Engine chunk types
    "function": 4,
    "method": 4,
    "class": 4,
    "interface": 4,
    "struct": 4,
    "enum": 4,
    "type_alias": 3,
    "import": 3,
    "comment": 2,
    "block": 1,
    "array": 1,
    "structure": 0,
    # CAST+ concept types (from concept_extractor)
    "DEFINITION": 4,
    "IMPORT": 3,
    "COMMENT": 2,
    "BLOCK": 1,
    "STRUCTURE": 0,
}


def normalize_content(content: str) -> str:
    """Normalize content for consistent comparison."""
    return content.replace("\r\n", "\n").replace("\r", "\n").strip()


def get_chunk_specificity(chunk: dict) -> int:
    """Get specificity ranking for chunk's type. Higher = more specific."""
    chunk_type = chunk.get("chunk_type") or chunk.get("concept") or chunk.get("type", "")
    if isinstance(chunk_type, str):
        type_name = chunk_type.lower()
    elif hasattr(chunk_type, "value"):
        type_name = str(chunk_type.value).lower()
    elif hasattr(chunk_type, "name"):
        type_name = chunk_type.name.lower()
    else:
        type_name = str(chunk_type).lower() if chunk_type else ""
    
    return CONCEPT_SPECIFICITY.get(type_name, -1)


def deduplicate_chunks(
    chunks: Sequence[T],
    language: str | None = None,
    content_key: str = "code",
) -> list[T]:
    """Deduplicate chunks using hash-based exact match + interval-based substring detection.

    Args:
        chunks: List of chunk dictionaries
        language: Optional language for language-specific exemptions
        content_key: Key to extract content from chunks (default: "code")

    Returns:
        Deduplicated list of chunks
    """
    if not chunks:
        return []

    # Language exemptions: Vue and Haskell preserve duplicates
    if language and language.lower() in ("vue", "vue_template", "haskell"):
        return list(chunks)

    # Stage 1: Exact content deduplication via hash table (O(n))
    exact_deduplicated = _deduplicate_exact_content(chunks, content_key)

    # Stage 2: Substring detection via interval scan (O(n log n))
    final = _remove_substring_overlaps(exact_deduplicated, content_key)

    logger.debug(
        f"Deduplication: {len(chunks)} -> {len(exact_deduplicated)} (exact) -> {len(final)} (substring)"
    )

    return final


def _deduplicate_exact_content(chunks: Sequence[T], content_key: str) -> list[T]:
    """Remove chunks with identical normalized content, keeping highest specificity."""
    hash_to_chunks: dict[int, list[T]] = defaultdict(list)

    for chunk in chunks:
        content = chunk.get(content_key, "")
        if not content:
            content = chunk.get("content", "") or chunk.get("text", "")
        
        normalized = normalize_content(content)
        if not normalized:
            continue

        content_hash = xxhash.xxh3_64(normalized.encode("utf-8")).intdigest()
        hash_to_chunks[content_hash].append(chunk)

    result = []
    for chunk_list in hash_to_chunks.values():
        if len(chunk_list) == 1:
            result.append(chunk_list[0])
        else:
            best = max(
                chunk_list,
                key=lambda c: (
                    get_chunk_specificity(c),
                    -(c.get("end_line", 0) - c.get("start_line", 0)),
                ),
            )
            result.append(best)

    return result


def _remove_substring_overlaps(chunks: Sequence[T], content_key: str) -> list[T]:
    """Remove BLOCK chunks that are substrings of DEFINITION/STRUCTURE chunks."""
    definitions = []
    blocks = []
    other = []

    for chunk in chunks:
        specificity = get_chunk_specificity(chunk)
        if specificity == 1:  # BLOCK-like
            blocks.append(chunk)
        elif specificity >= 3:  # DEFINITION-like
            definitions.append(chunk)
        else:
            other.append(chunk)

    definitions.sort(key=lambda c: c.get("start_line", 0))

    final = other + definitions

    for block in blocks:
        block_content = normalize_content(
            block.get(content_key, "") or block.get("content", "") or block.get("text", "")
        )
        block_start = block.get("start_line", 0)
        block_end = block.get("end_line", 0)

        is_substring = False
        for definition in _find_overlapping(definitions, block_start, block_end):
            def_content = normalize_content(
                definition.get(content_key, "") or definition.get("content", "") or definition.get("text", "")
            )
            if block_content in def_content and len(block_content) < len(def_content):
                is_substring = True
                break

        if not is_substring:
            final.append(block)

    return final


def _find_overlapping(sorted_chunks: list[T], query_start: int, query_end: int) -> list[T]:
    """Find chunks whose line ranges overlap with [query_start, query_end]."""
    overlapping = []
    for chunk in sorted_chunks:
        chunk_start = chunk.get("start_line", 0)
        chunk_end = chunk.get("end_line", 0)

        if chunk_end < query_start:
            continue
        if chunk_start > query_end:
            break

        overlapping.append(chunk)

    return overlapping
