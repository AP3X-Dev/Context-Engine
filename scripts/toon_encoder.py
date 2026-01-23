"""
TOON (Token-Oriented Object Notation) encoder for Context-Engine.

Uses the official python-toon library for spec-compliant encoding.

Feature flag:
- TOON_ENABLED=1  Enable TOON encoding (default: 0)

Reference: https://github.com/toon-format/toon
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

# Use official python-toon library
from toon import encode as toon_encode


# -----------------------------------------------------------------------------
# Feature Flag
# -----------------------------------------------------------------------------

def is_toon_enabled() -> bool:
    """Check if TOON encoding is enabled via environment variable."""
    return os.environ.get("TOON_ENABLED", "0").lower() in ("1", "true", "yes")


# -----------------------------------------------------------------------------
# Core Encoding (delegates to python-toon)
# -----------------------------------------------------------------------------

def encode(data: Any, delimiter: str = ",") -> str:
    """Encode any JSON-compatible data to TOON format using official library."""
    return toon_encode(data, {"delimiter": delimiter})


# -----------------------------------------------------------------------------
# Search Results Formatting
# -----------------------------------------------------------------------------

def encode_search_results(
    results: List[Dict[str, Any]],
    delimiter: str = ",",
    compact: bool = True,
) -> str:
    """Encode search results to TOON format.

    Args:
        results: List of search result dicts
        delimiter: Field delimiter (default: ",")
        compact: If True, only include core location fields (path/lines)

    Returns:
        TOON-formatted search results
    """
    if compact:
        core_fields = {"path", "start_line", "end_line", "symbol"}
        filtered = [{k: v for k, v in r.items() if k in core_fields} for r in results]
    else:
        filtered = results
    return toon_encode({"results": filtered}, {"delimiter": delimiter})


def encode_context_results(
    results: List[Dict[str, Any]],
    delimiter: str = ",",
    compact: bool = True,
) -> str:
    """Encode context_search results (code + memory) to TOON format.

    Args:
        results: List of mixed search result dicts
        delimiter: Field delimiter (default: ",")
        compact: If True, use minimal core fields only

    Returns:
        TOON-formatted context results
    """
    if not results:
        return toon_encode({"results": []}, {"delimiter": delimiter})

    # Separate code and memory results
    code_results = [r for r in results if r.get("source") != "memory"]
    memory_results = [r for r in results if r.get("source") == "memory"]

    # Filter fields if compact mode
    if compact:
        code_fields = {"path", "start_line", "end_line", "symbol"}
        mem_fields = {"content", "score"}
        code_results = [{k: v for k, v in r.items() if k in code_fields} for r in code_results]
        memory_results = [{k: v for k, v in r.items() if k in mem_fields} for r in memory_results]

    # Build output dict
    output: Dict[str, Any] = {}
    if code_results:
        output["code"] = code_results
    if memory_results:
        output["memory"] = memory_results
    if not output:
        output = {"results": results}

    return toon_encode(output, {"delimiter": delimiter})


# -----------------------------------------------------------------------------
# Token Estimation
# -----------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars/4 heuristic, good enough for comparison)."""
    return len(text) // 4


def compare_formats(data: Any) -> Dict[str, Any]:
    """Compare TOON vs JSON token counts for given data.

    Returns:
        {
            "json_tokens": int,
            "json_compact_tokens": int,
            "toon_tokens": int,
            "toon_tab_tokens": int,
            "savings_vs_json": float,  # percentage
            "savings_vs_compact": float,
        }
    """
    import json

    json_pretty = json.dumps(data, indent=2)
    json_compact = json.dumps(data, separators=(",", ":"))
    toon_comma = encode(data, delimiter=",")
    toon_tab = encode(data, delimiter="\t")

    json_tokens = estimate_tokens(json_pretty)
    json_compact_tokens = estimate_tokens(json_compact)
    toon_tokens = estimate_tokens(toon_comma)
    toon_tab_tokens = estimate_tokens(toon_tab)

    return {
        "json_tokens": json_tokens,
        "json_compact_tokens": json_compact_tokens,
        "toon_tokens": toon_tokens,
        "toon_tab_tokens": toon_tab_tokens,
        "savings_vs_json": round((1 - toon_tokens / json_tokens) * 100, 1) if json_tokens else 0,
        "savings_vs_compact": round((1 - toon_tokens / json_compact_tokens) * 100, 1) if json_compact_tokens else 0,
    }

