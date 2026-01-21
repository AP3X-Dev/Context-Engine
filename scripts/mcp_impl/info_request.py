#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
mcp/info_request.py - Info request helpers for MCP indexer server.

Extracted from mcp_indexer_server.py for better modularity.
Contains:
- Helper functions for info_request tool
"""

from __future__ import annotations

__all__ = [
    "_extract_symbols_from_query",
    "_extract_related_concepts",
    "_format_information_field",
    "_extract_relationships",
    "_calculate_confidence",
    "_compute_score_statistics",
]

import re
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Import _split_ident for tokenization
from scripts.mcp_impl.utils import _split_ident


def _extract_symbols_from_query(query: str) -> list[str]:
    """Extract potential symbol names from a query string."""
    # Match CamelCase, snake_case, or standalone words that look like identifiers
    patterns = [
        r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b',  # CamelCase
        r'\b[a-z_][a-z0-9_]*(?:_[a-z0-9]+)+\b',  # snake_case
        r'\b(?:def|class|function|method|async)\s+(\w+)',  # explicit mentions
    ]
    symbols = set()
    for pat in patterns:
        for m in re.finditer(pat, query):
            sym = m.group(1) if m.lastindex else m.group(0)
            if len(sym) > 2:
                symbols.add(sym)
    return list(symbols)[:5]  # Limit to top 5


def _extract_related_concepts(query: str, results: list) -> list[str]:
    """Extract related technical concepts dynamically from results (codebase-agnostic)."""
    concepts = set()

    # Extract from results - this works on any codebase
    for r in results[:10]:
        # From symbols: split CamelCase/snake_case into meaningful parts
        sym = r.get("symbol", "") or ""
        if sym and len(sym) > 2:
            parts = [p for p in re.split(r'(?=[A-Z])|_|-', sym) if p and len(p) > 2]
            for part in parts[:3]:
                concepts.add(part.lower())

        # From file paths: extract directory/module names
        path = r.get("path", "") or ""
        if path:
            path_parts = path.replace("\\", "/").split("/")
            for pp in path_parts[-3:]:  # Last 3 path segments
                # Remove extension and split
                name = pp.rsplit(".", 1)[0] if "." in pp else pp
                if name and len(name) > 2 and not name.startswith("_"):
                    concepts.add(name.lower())

        # From kind: function, class, method, etc.
        kind = r.get("kind", "") or ""
        if kind and len(kind) > 2:
            concepts.add(kind.lower())

    # From query: extract significant words (skip common words)
    skip_words = {"the", "is", "are", "how", "does", "what", "where", "find", "get", "set", "for", "and", "with"}
    query_parts = re.split(r'\W+', query.lower())
    for qp in query_parts:
        if qp and len(qp) > 2 and qp not in skip_words:
            concepts.add(qp)

    # Sort by frequency in results for relevance
    return list(concepts)[:10]


def _format_information_field(result: dict) -> str:
    """Generate human-readable information field for a result."""
    path = result.get("path", "")
    symbol = result.get("symbol", "")
    start = result.get("start_line", 0)
    end = result.get("end_line", 0)
    kind = result.get("kind", "")

    # Get just the filename
    filename = path.split("/")[-1] if "/" in path else path

    if symbol and kind:
        return f"Found {kind} '{symbol}' in {filename} (lines {start}-{end})"
    elif symbol:
        return f"Found '{symbol}' in {filename} (lines {start}-{end})"
    else:
        return f"Found match in {filename} (lines {start}-{end})"


def _extract_relationships(result: dict) -> dict:
    """Extract relationship metadata (imports, calls) from a result."""
    relations = result.get("relations") or {}
    # Get from relations object if present
    imports = relations.get("imports") or []
    calls = relations.get("calls") or []
    symbol_path = relations.get("symbol_path") or ""
    # Also check top-level metadata (fallback)
    if not imports:
        imports = result.get("imports") or []
    if not calls:
        calls = result.get("calls") or []
    # Get related paths if available
    related_paths = result.get("related_paths") or []

    return {
        "imports_from": imports[:10] if imports else [],  # Limit to 10
        "calls": calls[:10] if calls else [],
        "symbol_path": symbol_path,
        "related_paths": related_paths[:5] if related_paths else [],
    }


def _compute_score_statistics(results: list) -> dict:
    """Compute statistical metrics from result scores.

    Handles edge cases:
    - Empty results
    - Single result
    - Identical scores (zero variance)
    - Invalid scores (NaN)

    Returns:
        dict with mean, std, min, max, cv (coefficient of variation)
    """
    if not results:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "cv": 0.0}

    # Extract scores safely
    scores = []
    for r in results:
        try:
            score_val = r.get("score", 0)
            # Skip None values explicitly
            if score_val is None:
                continue
            s = float(score_val if score_val != 0 else 0)
            # Check for NaN using self-comparison
            if s == s:
                scores.append(s)
        except (ValueError, TypeError):
            continue

    if not scores:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "cv": 0.0}

    if len(scores) == 1:
        val = scores[0]
        return {"mean": val, "std": 0.0, "min": val, "max": val, "cv": 0.0}

    # Compute statistics
    mean_score = sum(scores) / len(scores)
    variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
    std_score = variance ** 0.5
    min_score = min(scores)
    max_score = max(scores)

    # Coefficient of variation (CV = std / mean)
    # Avoid division by zero
    if abs(mean_score) < 1e-9:
        cv = 0.0
    else:
        cv = std_score / abs(mean_score)

    return {
        "mean": round(mean_score, 4),
        "std": round(std_score, 4),
        "min": round(min_score, 4),
        "max": round(max_score, 4),
        "cv": round(cv, 4),
    }


def _calculate_confidence(query: str, results: list) -> dict:
    """Calculate confidence metrics for the search with variance analysis.

    Returns confidence dict with:
    - level: "high", "medium", "low", or "none"
    - score: average score
    - top_score: best score
    - symbol_matches: count of symbol matches
    - variance_score: variance of scores
    - score_spread: max - min score
    - consistency_level: "high", "medium", or "low"
    - coefficient_of_variation: CV metric
    - min_score, max_score: score range
    - low_confidence_hint: suggestion when confidence is low (optional)
    """
    if not results:
        return {"level": "none", "score": 0.0, "reason": "no_results"}

    # Compute base metrics
    avg_score = sum(r.get("score", 0) for r in results) / len(results)
    top_score = results[0].get("score", 0) if results else 0

    # Check if query terms match symbols
    query_tokens = set(_split_ident(query.lower()))
    symbol_matches = sum(
        1 for r in results[:5]
        if any(tok in _split_ident((r.get("symbol", "") or "").lower())
               for tok in query_tokens)
    )

    # Compute score variance metrics
    stats = _compute_score_statistics(results)
    variance_score = stats["std"] ** 2  # Variance from std
    score_spread = stats["max"] - stats["min"]
    cv = stats["cv"]

    # Determine consistency level based on CV thresholds
    # CV < 0.2: high consistency (scores are similar)
    # CV 0.2-0.4: medium consistency
    # CV > 0.4: low consistency (scores vary widely)
    if cv < 0.2:
        consistency_level = "high"
    elif cv < 0.4:
        consistency_level = "medium"
    else:
        consistency_level = "low"

    # Determine overall confidence level
    if top_score > 0.8 and symbol_matches > 0:
        level = "high"
    elif avg_score > 0.6:
        level = "medium"
    elif results:
        level = "low"
    else:
        level = "none"

    result = {
        "level": level,
        "score": round(avg_score, 3),
        "top_score": round(top_score, 3),
        "symbol_matches": symbol_matches,
        "variance_score": round(variance_score, 4),
        "score_spread": round(score_spread, 4),
        "consistency_level": consistency_level,
        "coefficient_of_variation": cv,
        "min_score": stats["min"],
        "max_score": stats["max"],
    }

    # Add hint for low confidence
    if level == "low":
        result["low_confidence_hint"] = (
            "Try more specific terms or include function/class names for better results"
        )

    return result

