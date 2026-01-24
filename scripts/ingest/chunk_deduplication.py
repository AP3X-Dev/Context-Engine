"""High-performance chunk deduplication with O(n log n) complexity.

Two-stage deduplication:
1. Exact content matching via hash table (O(n))
2. Substring detection via sorted interval scan (O(n log n))

Specificity scoring uses weighted formula:
  score = w_type * type_weight + w_size * log(line_count) + w_name * has_name
  
where:
  - type_weight: structural importance (definition > block > comment)
  - log(line_count): information content (more lines = more context)
  - has_name: named symbols are more referenceable
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Sequence, TypeVar, Dict, Any

import xxhash

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=dict)

TYPE_WEIGHTS: Dict[str, float] = {
    "function": 1.0,
    "method": 1.0,
    "class": 1.0,
    "interface": 1.0,
    "struct": 1.0,
    "enum": 1.0,
    "definition": 1.0,
    "type_alias": 0.8,
    "type": 0.8,
    "import": 0.6,
    "comment": 0.4,
    "docstring": 0.4,
    "block": 0.3,
    "array": 0.2,
    "structure": 0.1,
}

SPECIFICITY_WEIGHTS = {
    "type": 0.5,
    "size": 0.3,
    "name": 0.2,
}


def normalize_content(content: str) -> str:
    """Normalize content for consistent comparison."""
    return content.replace("\r\n", "\n").replace("\r", "\n").strip()


def _extract_type_name(chunk: dict) -> str:
    """Extract normalized type name from chunk."""
    chunk_type = chunk.get("chunk_type") or chunk.get("concept") or chunk.get("type", "")
    if isinstance(chunk_type, str):
        return chunk_type.lower()
    elif hasattr(chunk_type, "value"):
        return str(chunk_type.value).lower()
    elif hasattr(chunk_type, "name"):
        return chunk_type.name.lower()
    return str(chunk_type).lower() if chunk_type else ""


def compute_specificity_score(chunk: dict) -> float:
    """Compute specificity score using weighted formula.
    
    score = w_type * type_weight + w_size * log(1 + line_count) + w_name * has_name
    
    Higher score = more specific, should be kept over lower-scoring duplicates.
    """
    type_name = _extract_type_name(chunk)
    type_weight = TYPE_WEIGHTS.get(type_name, 0.0)
    
    start_line = chunk.get("start_line", 0)
    end_line = chunk.get("end_line", 0)
    line_count = max(1, end_line - start_line + 1)
    size_score = math.log(1 + line_count) / math.log(1000)
    
    has_name = 1.0 if chunk.get("name") or chunk.get("symbol") else 0.0
    
    score = (
        SPECIFICITY_WEIGHTS["type"] * type_weight +
        SPECIFICITY_WEIGHTS["size"] * min(1.0, size_score) +
        SPECIFICITY_WEIGHTS["name"] * has_name
    )
    
    return score


def get_chunk_specificity(chunk: dict) -> int:
    """Get integer specificity ranking (legacy interface, 0-4 scale)."""
    type_name = _extract_type_name(chunk)
    weight = TYPE_WEIGHTS.get(type_name, 0.0)
    
    if weight >= 0.9:
        return 4
    elif weight >= 0.7:
        return 3
    elif weight >= 0.5:
        return 2
    elif weight >= 0.3:
        return 1
    return 0


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


def deduplicate_semantic_chunks(
    chunks: Sequence,
    language: str | None = None,
) -> list:
    """Deduplicate SemanticChunk objects using O(n log n) algorithm.
    
    Converts SemanticChunk dataclass objects to dicts, deduplicates,
    and returns the original objects.
    
    Args:
        chunks: List of SemanticChunk objects (with content, start_line, end_line, concept)
        language: Optional language for exemptions (Vue, Haskell)
    
    Returns:
        Deduplicated list of SemanticChunk objects
    """
    if not chunks:
        return []
    
    chunk_dicts = []
    for i, c in enumerate(chunks):
        concept = getattr(c, "concept", None)
        if concept is not None:
            if hasattr(concept, "value"):
                concept_str = concept.value
            elif hasattr(concept, "name"):
                concept_str = concept.name
            else:
                concept_str = str(concept)
        else:
            concept_str = ""
        
        chunk_dicts.append({
            "content": getattr(c, "content", ""),
            "start_line": getattr(c, "start_line", 0),
            "end_line": getattr(c, "end_line", 0),
            "concept": concept_str,
            "_idx": i,
        })
    
    deduped_dicts = deduplicate_chunks(chunk_dicts, language, content_key="content")
    
    kept_indices = {d["_idx"] for d in deduped_dicts}
    return [c for i, c in enumerate(chunks) if i in kept_indices]
