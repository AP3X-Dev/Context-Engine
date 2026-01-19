#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
mcp_impl/symbol_graph.py - Symbol graph navigation for code understanding.

Provides Qdrant-native queries for:
- "who calls X" (callers)
- "where is X defined" (definition)
- "what imports Y" (importers)
- "who is called by X" (called_by - post-index computed)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "_symbol_graph_impl",
    "_format_symbol_graph_toon",
    "_compute_called_by",
    "clear_graph_collection_cache",
    "clear_symbol_suggestions_cache",
]


def _parse_int_or_default(value: Any, default: int = 0) -> int:
    """Defensive integer parser that returns default on failure.

    Args:
        value: Value to parse (can be str, int, or None)
        default: Default value if parsing fails

    Returns:
        Parsed integer or default value
    """
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    return default


# Environment - use same patterns as rest of engine
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")

# Graph collection suffix (matches graph_edges.py)
GRAPH_COLLECTION_SUFFIX = "_graph"

# Cache for graph collection existence checks
# Key: collection name, Value: (exists: bool, timestamp: float)
_GRAPH_COLLECTION_EXISTS: Dict[str, Tuple[bool, float]] = {}
_GRAPH_COLLECTION_CACHE_TTL = 300  # 5 minutes


def _check_graph_collection_exists(collection: str) -> Optional[bool]:
    """Check if graph collection exists (with TTL cache).

    Returns:
        True/False if cached and valid, None if cache miss/expired.
    """
    if collection not in _GRAPH_COLLECTION_EXISTS:
        return None
    exists, timestamp = _GRAPH_COLLECTION_EXISTS[collection]
    if time.time() - timestamp > _GRAPH_COLLECTION_CACHE_TTL:
        del _GRAPH_COLLECTION_EXISTS[collection]
        return None
    return exists


def _set_graph_collection_exists(collection: str, exists: bool) -> None:
    """Cache graph collection existence status."""
    _GRAPH_COLLECTION_EXISTS[collection] = (exists, time.time())


def clear_graph_collection_cache() -> None:
    """Clear the graph collection existence cache (useful for testing)."""
    _GRAPH_COLLECTION_EXISTS.clear()


def _get_graph_backend():
    """Return Neo4j graph backend when enabled, otherwise None."""
    try:
        from scripts.graph_backends import get_graph_backend
        backend = get_graph_backend()
        if backend.backend_type == "neo4j":
            return backend
    except Exception:
        return None
    return None


def _normalize_symbol(symbol: str) -> str:
    """Normalize a symbol name for robust matching.

    Handles:
    - Whitespace trimming
    - Qualified names (obj.method -> method for base match)
    - Common prefixes/suffixes
    """
    s = str(symbol).strip()
    if not s:
        return ""
    # Remove leading/trailing underscores for matching (but preserve for exact)
    return s


def _edit_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance using dynamic programming.

    Handles:
    - Case-insensitive comparison
    - Empty strings

    Returns:
        Edit distance (number of single-character edits)
    """
    s1 = s1.lower()
    s2 = s2.lower()

    if len(s1) < len(s2):
        return _edit_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _camel_split(s: str) -> List[str]:
    """Extract tokens from camelCase/PascalCase identifiers.

    Examples:
        "getUserProfile" -> ["get", "user", "profile"]
        "HTTPServer" -> ["HTTP", "Server"]
        "my_method" -> ["my", "method"]
    """
    if not s:
        return []

    # Handle snake_case first
    if "_" in s:
        return [t for t in s.split("_") if t]

    # Handle camelCase/PascalCase
    import re
    # Insert space before uppercase that follows lowercase or before uppercase followed by lowercase
    spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    spaced = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', spaced)
    tokens = [t for t in spaced.split() if t]
    return tokens


def _similarity_score(query: str, candidate: str) -> float:
    """Compute composite similarity score for symbol suggestions.

    Scoring:
    - Exact match: 1.0
    - Prefix match: 0.9
    - CamelCase token match: 0.8
    - Edit distance ≤2: 0.6 to 0.8 (scaled)
    - Otherwise: 0.0

    Returns:
        Similarity score in [0.0, 1.0]
    """
    q_lower = query.lower()
    c_lower = candidate.lower()

    # Exact match
    if q_lower == c_lower:
        return 1.0

    # Edit distance for typos (check before prefix to avoid over-scoring short typos)
    ed = _edit_distance(query, candidate)
    max_len = max(len(query), len(candidate))
    if ed <= 2 and max_len > 0:
        # Scale from 0.8 (ed=0, impossible since exact already checked) to 0.6 (ed=2)
        # ed=1 -> 0.7, ed=2 -> 0.6
        return 0.8 - (ed * 0.1)

    # Prefix match (only if not within edit distance threshold)
    if c_lower.startswith(q_lower) or q_lower.startswith(c_lower):
        return 0.9

    # CamelCase token matching (case-insensitive comparison for cross-case matching)
    q_tokens = set(t.lower() for t in _camel_split(query))
    c_tokens = set(t.lower() for t in _camel_split(candidate))
    if q_tokens and c_tokens:
        intersection = len(q_tokens & c_tokens)
        union = len(q_tokens | c_tokens)
        if union > 0:
            jaccard = intersection / union
            if jaccard >= 0.5:  # At least 50% token overlap
                return 0.8

    return 0.0


# Cache for symbol suggestions: {(collection, symbol): (timestamp, [(symbol, score), ...])}
_SYMBOL_SUGGESTIONS_CACHE: Dict[Tuple[str, str], Tuple[float, List[Tuple[str, float]]]] = {}
_SYMBOL_SUGGESTIONS_CACHE_MAX = int(os.environ.get("SYMBOL_SUGGESTIONS_CACHE_MAX", "100") or 100)
_SYMBOL_SUGGESTIONS_CACHE_TTL = int(os.environ.get("SYMBOL_SUGGESTIONS_CACHE_TTL", "60") or 60)


def clear_symbol_suggestions_cache() -> None:
    """Clear the symbol suggestions cache (useful for testing)."""
    _SYMBOL_SUGGESTIONS_CACHE.clear()


def _evict_expired_suggestions() -> None:
    """Remove expired entries from the suggestions cache."""
    now = time.time()
    expired = [
        k for k, (ts, _) in _SYMBOL_SUGGESTIONS_CACHE.items()
        if now - ts > _SYMBOL_SUGGESTIONS_CACHE_TTL
    ]
    for k in expired:
        _SYMBOL_SUGGESTIONS_CACHE.pop(k, None)


def _get_symbol_suggestions(
    symbol: str,
    collection: str,
    limit: int = 3,
) -> List[Tuple[str, float]]:
    """Get fuzzy symbol suggestions when exact match fails.

    Queries the graph collection with relaxed filters and scores candidates
    by similarity (edit distance, prefix match, camelCase tokens).

    Args:
        symbol: The symbol name to match
        collection: Qdrant collection to search
        limit: Maximum number of suggestions to return

    Returns:
        List of (symbol, score) tuples sorted by score descending
    """
    import time
    from qdrant_client import QdrantClient
    from qdrant_client import models

    # Check cache
    cache_key = (collection, symbol)
    now = time.time()
    if cache_key in _SYMBOL_SUGGESTIONS_CACHE:
        cache_time, cached_suggestions = _SYMBOL_SUGGESTIONS_CACHE[cache_key]
        if now - cache_time < _SYMBOL_SUGGESTIONS_CACHE_TTL:
            return cached_suggestions[:limit]

    try:
        client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
            timeout=float(os.environ.get("QDRANT_TIMEOUT", "5") or 5),
        )

        graph_coll = collection + GRAPH_COLLECTION_SUFFIX

        # Query for symbols that might be similar
        # Use scroll to get a sample of symbols from graph collection
        candidates: Dict[str, float] = {}

        # Strategy 1: Use keyword index with exact prefix variants
        # Note: MatchText requires text index which may not exist at scale.
        # Instead, generate plausible symbol variants and use keyword Match.
        try:
            # Generate prefix variants for keyword matching
            variants = _symbol_variants(symbol)

            max_scroll = int(os.environ.get("SYMBOL_SUGGESTION_MAX_SCROLL", "100") or 100)

            # Use keyword Match (indexed) instead of MatchText (full scan)
            # Query for each variant separately to use the keyword index
            for variant in variants[:6]:  # Increased from 3 to 6 variants
                try:
                    filter1 = models.Filter(
                        should=[
                            models.FieldCondition(
                                key="caller_symbol",
                                match=models.MatchValue(value=variant),
                            ),
                            models.FieldCondition(
                                key="callee_symbol",
                                match=models.MatchValue(value=variant),
                            ),
                        ]
                    )

                    points, _ = client.scroll(
                        collection_name=graph_coll,
                        scroll_filter=filter1,
                        limit=max_scroll,
                        with_payload=True,
                        with_vectors=False,
                    )

                    for pt in points:
                        payload = getattr(pt, "payload", {}) or {}
                        for key in ["caller_symbol", "callee_symbol"]:
                            candidate_sym = str(payload.get(key, ""))
                            if candidate_sym and candidate_sym.lower() != symbol.lower():
                                score = _similarity_score(symbol, candidate_sym)
                                if score > 0.5:
                                    candidates[candidate_sym] = max(candidates.get(candidate_sym, 0), score)
                except Exception as e:
                    logger.debug(f"Suppressed exception: {e}")  # Continue with other variants

            # If no results from exact match, try a bounded sample scroll (no filter)
            # This is expensive but capped - use only as fallback
            if not candidates:
                sample_limit = int(os.environ.get("SYMBOL_SUGGESTION_SAMPLE_LIMIT", "200") or 200)
                try:
                    sample_points, _ = client.scroll(
                        collection_name=graph_coll,
                        limit=sample_limit,
                        with_payload=True,
                        with_vectors=False,
                    )
                    for pt in sample_points:
                        payload = getattr(pt, "payload", {}) or {}
                        for key in ["caller_symbol", "callee_symbol"]:
                            candidate_sym = str(payload.get(key, ""))
                            if candidate_sym and candidate_sym.lower() != symbol.lower():
                                score = _similarity_score(symbol, candidate_sym)
                                if score > 0.5:
                                    candidates[candidate_sym] = max(candidates.get(candidate_sym, 0), score)
                except Exception as e:
                    logger.debug(f"Suppressed exception: {e}")  # Sample fallback failed, continue with empty candidates

        except Exception as e:
            logger.debug(f"Symbol suggestion query failed: {e}")

        # Sort by score and return top N
        suggestions = sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:limit]

        # Cache results with proper eviction
        # First, evict expired entries
        _evict_expired_suggestions()

        # If still at capacity, evict oldest 10%
        if len(_SYMBOL_SUGGESTIONS_CACHE) >= _SYMBOL_SUGGESTIONS_CACHE_MAX:
            evict_count = max(1, _SYMBOL_SUGGESTIONS_CACHE_MAX // 10)
            sorted_keys = sorted(
                _SYMBOL_SUGGESTIONS_CACHE.keys(),
                key=lambda k: _SYMBOL_SUGGESTIONS_CACHE[k][0]  # Sort by timestamp
            )
            for k in sorted_keys[:evict_count]:
                _SYMBOL_SUGGESTIONS_CACHE.pop(k, None)

        _SYMBOL_SUGGESTIONS_CACHE[cache_key] = (now, suggestions)
        return suggestions

    except Exception as e:
        logger.debug(f"Failed to get symbol suggestions: {e}")
        return []


def _symbol_variants(symbol: str) -> List[str]:
    """Generate symbol variants for fuzzy matching.

    Given "MyClass.my_method", returns:
    - "MyClass.my_method" (exact)
    - "my_method" (base name)
    - "MyClass" (container)
    """
    s = _normalize_symbol(symbol)
    if not s:
        return []

    variants = [s]

    # Handle qualified names: obj.method, Class.method, module.func
    if "." in s:
        parts = s.split(".")
        # Add base name (last part)
        if parts[-1]:
            variants.append(parts[-1])
        # Add container name (first part) for class lookups
        if len(parts) >= 2 and parts[0]:
            variants.append(parts[0])

    # Handle C++/Rust namespace paths: Namespace::Class::method
    if "::" in s:
        parts = s.split("::")
        if parts[-1]:
            variants.append(parts[-1])
        if len(parts) >= 2 and parts[-2]:
            variants.append(parts[-2])

    # Handle arrow notation: obj->method
    if "->" in s:
        parts = s.split("->")
        if parts[-1]:
            variants.append(parts[-1])

    return list(dict.fromkeys(variants))  # Dedupe preserving order

def _norm_under(u: Optional[str]) -> Optional[str]:
    """Normalize an `under` path for suffix matching against `metadata.path_prefix`.

    Ingest stores path_prefix as the full path like:
        /work/Context-Engine-41e67959950c8ab3/scripts

    For flexible matching, we normalize `under` to a suffix pattern that works
    with MatchText substring matching. E.g., "scripts" -> "/scripts" will match
    any path_prefix ending with "/scripts".

    Note: Use MatchText (not MatchValue) with this normalized value.
    """
    if not u:
        return None
    s = str(u).strip().replace("\\", "/")
    # Remove leading/trailing slashes and rejoin
    s = "/".join([p for p in s.split("/") if p])
    if not s:
        return None
    # Return as suffix pattern with leading slash for MatchText matching
    # e.g., "scripts" -> "/scripts", "scripts/hybrid" -> "/scripts/hybrid"
    return "/" + s


async def _hydrate_graph_results(
    client: Any,
    collection: str,
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Hydrate hollow graph results with actual code snippets and line ranges.

    Graph edges only store path/symbol references. This function fetches the
    actual code content from the main collection to populate:
    - start_line, end_line (accurate values)
    - snippet (actual code content)

    Uses a SINGLE batch query with OR filter across all unique paths for efficiency.
    Typical overhead: <5ms for up to 20 results.

    Args:
        client: Qdrant client
        collection: Main code collection (not _graph)
        results: List of hollow results from graph query

    Returns:
        Hydrated results with snippets and accurate line numbers
    """
    from qdrant_client import models

    if not results:
        return results

    # Collect unique paths and symbols
    unique_paths = list({r.get("path", "") for r in results if r.get("path")})
    unique_symbols = list({
        r.get("symbol_path") or r.get("symbol", "")
        for r in results
        if r.get("symbol_path") or r.get("symbol")
    })

    # If we have neither paths nor symbols, nothing to hydrate
    if not unique_paths and not unique_symbols:
        return results

    try:
        # Build filter conditions
        conditions = []

        # Add path conditions if we have paths
        if unique_paths:
            conditions.extend([
                models.FieldCondition(
                    key="metadata.path",
                    match=models.MatchValue(value=path)
                )
                for path in unique_paths
            ])

        # Add symbol conditions for results without paths (callees case)
        # This allows hydration by symbol lookup
        if unique_symbols:
            for sym in unique_symbols:
                # Try both symbol and symbol_path fields
                base_sym = sym.split(".")[-1] if "." in sym else sym
                conditions.append(
                    models.FieldCondition(
                        key="metadata.symbol",
                        match=models.MatchValue(value=base_sym)
                    )
                )
                if sym != base_sym:
                    conditions.append(
                        models.FieldCondition(
                            key="metadata.symbol_path",
                            match=models.MatchValue(value=sym)
                        )
                    )

        def do_scroll():
            # Calculate limit based on paths or symbols
            result_limit = max(len(unique_paths), len(unique_symbols), 1) * 10
            return client.scroll(
                collection_name=collection,
                scroll_filter=models.Filter(should=conditions),
                limit=result_limit,  # ~10 chunks per file/symbol max
                with_payload=True,
                with_vectors=False,  # Don't fetch vectors - saves bandwidth
            )

        scroll_result = await asyncio.to_thread(do_scroll)
        points, _ = scroll_result
        if not points:
            return results

        # Build lookup: (path, symbol) -> point data
        # Also index by path alone and symbol alone for fallback
        lookup: Dict[tuple, Any] = {}
        path_fallback: Dict[str, Any] = {}
        symbol_fallback: Dict[str, Any] = {}  # For callees without paths

        for p in points:
            payload = getattr(p, "payload", {}) or {}
            md = payload.get("metadata", {})
            path = str(md.get("path") or "")
            sym = str(md.get("symbol") or "")
            sym_path = str(md.get("symbol_path") or "")

            if path:
                # Index by (path, symbol) and (path, symbol_path)
                if sym:
                    lookup[(path, sym)] = (payload, md)
                if sym_path:
                    lookup[(path, sym_path)] = (payload, md)
                # First chunk per path as fallback
                if path not in path_fallback:
                    path_fallback[path] = (payload, md)

            # Also index by symbol alone for callees hydration
            if sym and sym not in symbol_fallback:
                symbol_fallback[sym] = (payload, md)
            if sym_path and sym_path not in symbol_fallback:
                symbol_fallback[sym_path] = (payload, md)

        # Hydrate each result
        for r in results:
            path = r.get("path", "")
            sym = r.get("symbol_path") or r.get("symbol", "")
            base_sym = sym.split(".")[-1] if "." in sym else sym

            # Try to match: (path, symbol_path), (path, base_sym), path fallback, or symbol fallback
            match = (
                lookup.get((path, sym)) or
                lookup.get((path, base_sym)) or
                path_fallback.get(path) or
                symbol_fallback.get(sym) or
                symbol_fallback.get(base_sym)
            )

            if match:
                payload, md = match
                info = payload.get("information", "") or payload.get("content", "")

                # Fill in path if missing (callees case - graph edges don't have callee_path)
                if not r.get("path"):
                    r["path"] = str(md.get("path") or "")

                # Update with hydrated data - use defensive parsing for line numbers
                r["start_line"] = _parse_int_or_default(
                    md.get("symbol_start_line")
                    or md.get("start_line")
                    or md.get("start")
                    or r.get("start_line"),
                    default=r.get("start_line", 0),
                )
                r["end_line"] = _parse_int_or_default(
                    md.get("symbol_end_line")
                    or md.get("end_line")
                    or md.get("end")
                    or r.get("end_line"),
                    default=r.get("end_line", 0),
                )
                r["language"] = str(md.get("language") or r.get("language", ""))

                # Extract snippet - prefer raw code from metadata
                # Truncate strictly to avoid context window bloat
                raw_code = md.get("code") or info
                if raw_code:
                    r["snippet"] = _extract_snippet(raw_code, max_chars=500)

                r["hydrated"] = True

    except Exception as e:
        logger.debug(f"Failed to hydrate graph results: {e}")

    return results


def _extract_snippet(info: str, max_chars: int = 500) -> str:
    """Extract snippet from content, truncating at line boundary.

    Handles markdown code blocks and ensures we don't cut mid-line.
    """
    if not info:
        return ""

    # Handle markdown code blocks
    if "```" in info:
        parts = info.split("```")
        if len(parts) > 1:
            code_block = parts[1]
            # Skip language identifier line
            lines = code_block.split("\n", 1)
            content = lines[1] if len(lines) > 1 else code_block
        else:
            content = info
    else:
        content = info

    # Truncate at line boundary
    if len(content) <= max_chars:
        return content.strip()

    # Find last newline before max_chars
    truncated = content[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:  # Only use if we keep at least half
        return truncated[:last_nl].strip()

    return truncated.strip()


async def _query_graph_collection(
    client: Any,
    collection: str,
    symbol: str,
    query_type: str,
    limit: int,
    repo: Optional[str] = None,
    depth: int = 1,  # Accepted for compatibility but not used (Qdrant doesn't support multi-hop)
) -> Optional[List[Dict[str, Any]]]:
    """
    Query the graph collection for fast indexed lookups.

    Returns None if graph collection doesn't exist, otherwise returns results.
    """
    from qdrant_client import models as qmodels

    graph_coll = collection + GRAPH_COLLECTION_SUFFIX
    cached_exists = _check_graph_collection_exists(graph_coll)
    if cached_exists is False:
        return None

    def _is_missing_collection_error(err: Exception) -> bool:
        # qdrant-client raises various exception types depending on transport/proto.
        status = getattr(err, "status_code", None)
        if status == 404:
            return True
        msg = str(err).lower()
        return ("not found" in msg and "collection" in msg) or ("does not exist" in msg)

    # Build filter based on query type
    try:
        if query_type == "callers":
            # Find edges where callee_symbol matches (who calls this symbol)
            edge_type = "calls"
            symbol_key = "callee_symbol"
        elif query_type == "callees":
            # Find edges where caller_symbol matches (what this symbol calls)
            edge_type = "calls"
            symbol_key = "caller_symbol"
        elif query_type == "importers":
            # Find edges where callee_symbol matches (who imports this module)
            edge_type = "imports"
            symbol_key = "callee_symbol"
        else:
            # Definition queries don't use graph collection
            return None

        variants = _symbol_variants(symbol) or [symbol]
        seen = set()
        edges_all: List[Any] = []

        for variant in variants:
            if len(edges_all) >= limit:
                break
            must = [
                qmodels.FieldCondition(
                    key=symbol_key,
                    match=qmodels.MatchValue(value=variant),
                ),
                qmodels.FieldCondition(
                    key="edge_type",
                    match=qmodels.MatchValue(value=edge_type),
                ),
            ]
            if repo and repo != "*":
                must.append(
                    qmodels.FieldCondition(
                        key="repo",
                        match=qmodels.MatchValue(value=repo),
                    )
                )

            def do_scroll():
                return client.scroll(
                    collection_name=graph_coll,
                    scroll_filter=qmodels.Filter(must=must),
                    limit=max(1, limit - len(edges_all)),
                    with_payload=True,
                    with_vectors=False,  # Graph edges don't need vectors
                )

            try:
                scroll_result = await asyncio.to_thread(do_scroll)
            except Exception as e:
                if _is_missing_collection_error(e):
                    _set_graph_collection_exists(graph_coll, False)
                    return None
                logger.debug(f"Graph scroll failed for variant '{variant}': {e}")
                continue

            edges = scroll_result[0] if scroll_result else []
            for edge in edges:
                edge_id = str(getattr(edge, "id", "")) or str(id(edge))
                if edge_id in seen:
                    continue
                seen.add(edge_id)
                edges_all.append(edge)

        _set_graph_collection_exists(graph_coll, True)
        if not edges_all:
            return []

        # Convert edges to result format.
        results: List[Dict[str, Any]] = []
        for edge in edges_all[:limit]:
            payload = getattr(edge, "payload", {}) or {}
            
            if query_type == "callees":
                target_symbol = payload.get("callee_symbol", "")
                target_path = payload.get("callee_path", "")
                # We don't have start_line for callee in the edge usually, 
                # but we'll try to find it or leave as 0 (hydration will fix it)
                start_line = 0 
            else:
                target_symbol = payload.get("caller_symbol", "")
                target_path = payload.get("caller_path", "")
                start_line = payload.get("start_line")

            language = payload.get("language", "")

            # Extract meaningful symbol name
            if "/" in target_symbol or target_symbol.endswith(".py"):
                symbol_name = Path(target_symbol).stem
            elif "." in target_symbol:
                symbol_name = target_symbol.split(".")[-1]
            else:
                symbol_name = target_symbol

            end_line = payload.get("end_line")
            results.append(
                {
                    "path": target_path,
                    "start_line": int(start_line) if start_line else 0,
                    "end_line": int(end_line) if end_line else 0,
                    "symbol": symbol_name,
                    "symbol_path": target_symbol,
                    "language": language or "",
                    "snippet": "",
                    "from_graph": True,
                }
            )

        return results

    except Exception as e:
        logger.debug(f"Graph collection query failed: {e}")
        return None


async def _query_graph_backend(
    backend: Any,
    client: Any,
    collection: str,
    symbol: str,
    query_type: str,
    limit: int,
    repo: Optional[str] = None,
    depth: int = 1,
) -> Optional[List[Dict[str, Any]]]:
    """
    Query graph backend and return results in graph-collection format.

    When enhanced graph backend is available and depth > 1, uses multi-hop
    traversal for richer results (transitive callers/callees).
    """
    if query_type not in ("callers", "callees", "importers"):
        return None

    graph_store = collection
    variants = _symbol_variants(symbol) or [symbol]

    # Try enhanced multi-hop traversal when depth > 1
    if depth > 1:
        enhanced_results = await _try_enhanced_multihop_query(
            symbol=symbol,
            query_type=query_type,
            depth=depth,
            limit=limit,
            repo=repo,
        )
        if enhanced_results is not None:
            return enhanced_results

    def do_query():
        edges_all: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for variant in variants:
            if query_type == "callers":
                edges = backend.get_callers(graph_store, variant, repo=repo, limit=limit)
            elif query_type == "callees":
                edges = backend.get_callees(graph_store, variant, repo=repo, limit=limit)
            else:
                edges = backend.get_importers(graph_store, variant, repo=repo, limit=limit)

            for edge in edges or []:
                edge_key = edge.get("edge_id") or f"{edge.get('caller_symbol')}|{edge.get('callee_symbol')}|{edge.get('caller_path')}"
                if edge_key in seen:
                    continue
                seen.add(edge_key)
                edges_all.append(edge)
                if len(edges_all) >= limit:
                    return edges_all

        return edges_all

    try:
        edges = await asyncio.to_thread(do_query)
    except Exception as e:
        logger.debug(f"Graph backend query failed: {e}")
        return None

    if not edges:
        return []

    results: List[Dict[str, Any]] = []
    for edge in edges:
        if query_type == "callees":
            target_symbol = edge.get("callee_symbol", "")
            target_path = edge.get("callee_path", "")
            start_line = 0
        else:
            target_symbol = edge.get("caller_symbol", "")
            target_path = edge.get("caller_path", "")
            start_line = edge.get("start_line")

        language = edge.get("language", "")

        if "/" in target_symbol or target_symbol.endswith(".py"):
            symbol_name = Path(target_symbol).stem
        elif "." in target_symbol:
            symbol_name = target_symbol.split(".")[-1]
        else:
            symbol_name = target_symbol

        end_line = edge.get("end_line")
        results.append(
            {
                "path": target_path,
                "start_line": int(start_line) if start_line else 0,
                "end_line": int(end_line) if end_line else 0,
                "symbol": symbol_name,
                "symbol_path": target_symbol,
                "language": language or "",
                "snippet": "",
                "from_graph": True,
            }
        )

    return results


async def _try_enhanced_multihop_query(
    symbol: str,
    query_type: str,
    depth: int,
    limit: int,
    repo: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Try enhanced multi-hop traversal using advanced graph backend.

    Returns None if enhanced backend is not available, allowing fallback.
    This is transparent to users - just provides richer results when available.
    """
    try:
        from scripts.graph_backends.graph_rag import get_transitive_callers
    except ImportError:
        return None

    if query_type not in ("callers", "callees"):
        return None  # Multi-hop only makes sense for callers/callees

    try:
        if query_type == "callers":
            results = get_transitive_callers(symbol, repo=repo, depth=depth, limit=limit)
        else:
            # For callees, use similar approach
            try:
                from scripts.graph_backends.graph_rag import _get_knowledge_graph
                kg = _get_knowledge_graph()
                if kg:
                    results = kg.get_callees(symbol, repo=repo, depth=depth, limit=limit)
                else:
                    return None
            except Exception:
                return None

        if not results:
            return None

        # Convert to standard format
        formatted = []
        for r in results:
            hop = r.get("distance", 1) or r.get("hop", 1) or 1
            formatted.append({
                "path": r.get("path", ""),
                "start_line": r.get("start_line", 0) or 0,
                "end_line": r.get("end_line", 0) or 0,
                "symbol": r.get("name", ""),
                "symbol_path": r.get("id", "") or r.get("name", ""),
                "language": r.get("language", ""),
                "snippet": "",
                "from_graph": True,
                "hop": hop,
                "via": symbol if hop == 1 else "",  # First hop is via the queried symbol
            })

        logger.debug(f"Enhanced multi-hop returned {len(formatted)} results (depth={depth})")
        return formatted

    except Exception as e:
        logger.debug(f"Enhanced multi-hop query failed: {e}")
        return None


def _path_proximity_score(caller_path: str, callee_path: str) -> int:
    """Score path proximity: same file > same dir > same parent > same repo.

    Returns:
        Score from 0-100. Higher = closer.
    """
    if not caller_path or not callee_path:
        return 0

    # Normalize paths
    caller_path = caller_path.replace("\\", "/")
    callee_path = callee_path.replace("\\", "/")

    # Same file = highest score
    if caller_path == callee_path:
        return 100

    caller_parts = caller_path.split("/")
    callee_parts = callee_path.split("/")

    # Same directory (parent path matches)
    if caller_parts[:-1] == callee_parts[:-1]:
        return 80

    # Count common path prefix
    common = 0
    for a, b in zip(caller_parts, callee_parts):
        if a == b:
            common += 1
        else:
            break

    # Score based on how many path segments match
    max_depth = max(len(caller_parts), len(callee_parts))
    if max_depth > 0:
        return int(60 * common / max_depth)

    return 0


async def _query_callees(
    client: Any,
    collection: str,
    symbol: str,
    limit: int,
    language: Optional[str] = None,
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Find what a symbol calls (callees) using the graph collection.

    1. Query graph edges where caller matches (indexed lookup)
    2. Batch hydrate unique callee symbols in a single query
    3. Rank by proximity to caller
    """
    from qdrant_client import models as qmodels

    graph_coll = collection + GRAPH_COLLECTION_SUFFIX

    try:
        # Find the caller's definition to get its file path
        def find_caller():
            return client.scroll(
                collection_name=collection,
                scroll_filter=qmodels.Filter(
                    should=[
                        qmodels.FieldCondition(
                            key="metadata.symbol_path",
                            match=qmodels.MatchValue(value=symbol),
                        ),
                        qmodels.FieldCondition(
                            key="metadata.symbol",
                            match=qmodels.MatchValue(value=symbol),
                        ),
                    ]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )

        caller_result = await asyncio.to_thread(find_caller)
        caller_points = caller_result[0] if caller_result else []

        if not caller_points:
            return []

        caller_payload = getattr(caller_points[0], "payload", {}) or {}
        caller_md = caller_payload.get("metadata", caller_payload)
        caller_path = caller_md.get("path", "")
        caller_imports = caller_md.get("imports") or []

        if not caller_path:
            return []

        # Query graph edges where caller_symbol matches (or fallback to caller_path)
        # Use symbol_path if available (e.g., "module.ClassName.method"), else use symbol
        caller_symbol_key = caller_md.get("symbol_path") or caller_md.get("symbol") or ""

        def query_edges():
            # Try matching by caller_symbol first (more precise)
            must_conditions = [
                qmodels.FieldCondition(
                    key="edge_type",
                    match=qmodels.MatchValue(value="calls"),
                ),
            ]

            # Prefer caller_symbol match (exact function), fallback to caller_path (all file calls)
            if caller_symbol_key:
                must_conditions.append(
                    qmodels.FieldCondition(
                        key="caller_symbol",
                        match=qmodels.MatchValue(value=caller_symbol_key),
                    )
                )
            else:
                must_conditions.append(
                    qmodels.FieldCondition(
                        key="caller_path",
                        match=qmodels.MatchValue(value=caller_path),
                    )
                )

            return client.scroll(
                collection_name=graph_coll,
                scroll_filter=qmodels.Filter(must=must_conditions),
                limit=limit * 3,  # Get more to allow filtering
                with_payload=True,
                with_vectors=False,
            )

        edge_result = await asyncio.to_thread(query_edges)
        edges = edge_result[0] if edge_result else []

        if not edges:
            # Fallback: use calls array from metadata (for repos without graph)
            calls = caller_md.get("calls") or []
            if not calls:
                return []

            # Batch hydrate: single query with should conditions
            unique_calls = list(dict.fromkeys(calls[:limit * 2]))  # Dedupe, preserve order

            def batch_hydrate():
                return client.scroll(
                    collection_name=collection,
                    scroll_filter=qmodels.Filter(
                        should=[
                            qmodels.FieldCondition(
                                key="metadata.symbol",
                                match=qmodels.MatchValue(value=c.split(".")[-1]),
                            )
                            for c in unique_calls[:50]  # Cap to avoid huge queries
                        ]
                    ),
                    limit=limit * 3,
                    with_payload=True,
                    with_vectors=False,
                )

            hydrate_result = await asyncio.to_thread(batch_hydrate)
            hydrate_points = hydrate_result[0] if hydrate_result else []

            # Score by proximity and match quality
            results = []
            seen_symbols: Set[str] = set()
            for pt in hydrate_points:
                payload = getattr(pt, "payload", {}) or {}
                md = payload.get("metadata", payload)
                sym = md.get("symbol", "")
                sym_path = md.get("symbol_path", "")
                callee_path = md.get("path", "")

                # Skip if not in our calls list
                if sym not in unique_calls and sym_path not in unique_calls:
                    # Check if base name matches any call
                    matched = False
                    for c in unique_calls:
                        if c.endswith("." + sym) or c == sym:
                            matched = True
                            break
                    if not matched:
                        continue

                # Dedupe by symbol
                if sym in seen_symbols:
                    continue
                seen_symbols.add(sym)

                # Calculate proximity score
                prox_score = _path_proximity_score(caller_path, callee_path)

                # Boost if imported
                callee_module = Path(callee_path).stem if callee_path else ""
                if callee_module and caller_imports:
                    for imp in caller_imports:
                        if callee_module in imp or imp in callee_module:
                            prox_score += 20
                            break

                results.append({
                    "path": callee_path,
                    "start_line": int(md.get("start_line", 0)),
                    "end_line": int(md.get("end_line", 0)),
                    "symbol": sym,
                    "symbol_path": sym_path,
                    "language": md.get("language", ""),
                    "snippet": md.get("code", "")[:200] if md.get("code") else "",
                    "kind": md.get("kind", ""),
                    "proximity_score": prox_score,
                })

            results.sort(key=lambda x: x.get("proximity_score", 0), reverse=True)
            return results[:limit]

        # Process graph edges - extract unique callees
        callee_symbols: List[str] = []
        seen: Set[str] = set()
        for edge in edges:
            payload = getattr(edge, "payload", {}) or {}
            callee = payload.get("callee_symbol", "")
            if callee and callee not in seen:
                seen.add(callee)
                callee_symbols.append(callee)

        if not callee_symbols:
            return []

        # Batch hydrate callees in single query
        def batch_hydrate_graph():
            return client.scroll(
                collection_name=collection,
                scroll_filter=qmodels.Filter(
                    should=[
                        qmodels.FieldCondition(
                            key="metadata.symbol",
                            match=qmodels.MatchValue(value=c.split(".")[-1]),
                        )
                        for c in callee_symbols[:50]
                    ]
                ),
                limit=limit * 3,
                with_payload=True,
                with_vectors=False,
            )

        hydrate_result = await asyncio.to_thread(batch_hydrate_graph)
        hydrate_points = hydrate_result[0] if hydrate_result else []

        # Build results with proximity scoring
        results = []
        seen_symbols: Set[str] = set()
        for pt in hydrate_points:
            payload = getattr(pt, "payload", {}) or {}
            md = payload.get("metadata", payload)
            sym = md.get("symbol", "")
            callee_path = md.get("path", "")

            if sym in seen_symbols:
                continue
            seen_symbols.add(sym)

            prox_score = _path_proximity_score(caller_path, callee_path)

            # Boost if imported
            callee_module = Path(callee_path).stem if callee_path else ""
            if callee_module and caller_imports:
                for imp in caller_imports:
                    if callee_module in imp or imp in callee_module:
                        prox_score += 20
                        break

            results.append({
                "path": callee_path,
                "start_line": int(md.get("start_line", 0)),
                "end_line": int(md.get("end_line", 0)),
                "symbol": sym,
                "symbol_path": md.get("symbol_path", ""),
                "language": md.get("language", ""),
                "snippet": md.get("code", "")[:200] if md.get("code") else "",
                "kind": md.get("kind", ""),
                "proximity_score": prox_score,
            })

        results.sort(key=lambda x: x.get("proximity_score", 0), reverse=True)
        return results[:limit]

    except Exception as e:
        logger.warning(f"_query_callees failed: {e}")
        return []


async def _symbol_graph_impl(
    symbol: str,
    query_type: str = "callers",
    limit: int = 20,
    language: Optional[str] = None,
    under: Optional[str] = None,
    repo: Optional[str] = None,
    collection: Optional[str] = None,
    session: Optional[str] = None,
    ctx: Any = None,
    depth: int = 1,
) -> Dict[str, Any]:
    """
    Query the symbol graph to find callers, definitions, or importers.

    Args:
        symbol: The symbol name to search for (function, class, module name)
        query_type: One of "callers", "definition", "importers"
        limit: Maximum number of results
        language: Optional language filter
        under: Optional path prefix filter
        repo: Optional repository filter (single repo name or "*" for all)
        collection: Optional collection override
        session: Optional session ID for collection routing
        ctx: MCP context (optional)
        depth: Number of hops for traversal (1=direct, 2=callers of callers, etc.)

    Returns:
        Dict with "results" list and metadata
    """
    from qdrant_client import QdrantClient
    from qdrant_client import models as qmodels

    # Get collection using engine's standard approach
    coll = str(collection or "").strip()
    if not coll:
        try:
            from scripts.mcp_impl.workspace import _default_collection
            coll = _default_collection() or ""
        except Exception:
            coll = os.environ.get("COLLECTION_NAME", "codebase")
    if not coll:
        coll = os.environ.get("COLLECTION_NAME", "codebase")
    if coll.endswith("_graph"):
        coll = coll[: -len("_graph")]

    # Connect to Qdrant using engine's standard env vars
    try:
        client = QdrantClient(
            url=QDRANT_URL,
            api_key=os.environ.get("QDRANT_API_KEY"),
            timeout=float(os.environ.get("QDRANT_TIMEOUT", "20") or 20),
        )
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant: {e}")
        return {
            "results": [],
            "error": f"Qdrant connection failed: {e}",
            "symbol": symbol,
            "query_type": query_type,
            "collection": coll,
        }

    graph_backend = _get_graph_backend()

    async def graph_query_fn(**kwargs):
        if graph_backend:
            return await _query_graph_backend(graph_backend, **kwargs)
        return await _query_graph_collection(**kwargs)

    # Validate query_type
    if query_type not in ("callers", "definition", "importers", "callees"):
        return {
            "results": [],
            "error": f"Invalid query_type: {query_type}. Use 'callers', 'definition', 'importers', or 'callees'",
            "symbol": symbol,
            "query_type": query_type,
            "collection": coll,
        }

    results: List[Dict[str, Any]] = []
    used_graph = False

    try:
        # Try graph collection first for callers/importers/callees (fast indexed query).
        # IMPORTANT: treat graph as an accelerator. If it's present-but-empty (e.g. freshly created
        # before a full reindex), optionally fall back to legacy array queries to avoid false negatives.
        if query_type in ("callers", "importers", "callees"):
            graph_results = await graph_query_fn(
                client=client,
                collection=coll,
                symbol=symbol,
                query_type=query_type,
                limit=limit,
                repo=repo,
                depth=depth,  # Pass depth for multi-hop traversal
            )
            if graph_results:
                # Hydrate hollow graph results with actual snippets and line numbers
                results = await _hydrate_graph_results(client, coll, graph_results)
                used_graph = True
                logger.debug(f"Graph collection returned {len(results)} results for {query_type}")
            elif graph_results is not None:
                fallback_on_empty = os.environ.get("GRAPH_FALLBACK_ON_EMPTY", "1").lower() in {
                    "1", "true", "yes", "on"
                }
                if not fallback_on_empty:
                    results = []
                    used_graph = True

        # Fallback for callees: use _query_callees which can use metadata.calls array
        if query_type == "callees" and not results and not used_graph and not graph_backend:
            results = await _query_callees(
                client=client,
                collection=coll,
                symbol=symbol,
                limit=limit,
                language=language,
                repo=repo,
            )
        # Fall back to legacy array field query if graph is unavailable or we opted to fallback on empty.
        elif not results and not used_graph:
            if query_type == "callers":
                # Find chunks where metadata.calls array contains the symbol (exact match)
                results = await _query_array_field(
                    client=client,
                    collection=coll,
                    field_key="metadata.calls",
                    value=symbol,
                    limit=limit,
                    language=language,
                    under=_norm_under(under),
                    repo=repo,
                )
            elif query_type == "importers":
                # Find chunks where metadata.imports array contains the symbol
                results = await _query_array_field(
                    client=client,
                    collection=coll,
                    field_key="metadata.imports",
                    value=symbol,
                    limit=limit,
                    language=language,
                    under=_norm_under(under),
                    repo=repo,
                )
            elif query_type == "definition":
                results = await _query_definition(
                    client=client,
                    collection=coll,
                    symbol=symbol,
                    limit=limit,
                    language=language,
                    under=_norm_under(under),
                    repo=repo,
                )

        # If no results, fall back to semantic search
        if not results:
            results = await _fallback_semantic_search(
                symbol=symbol,
                query_type=query_type,
                limit=limit,
                language=language,
                repo=repo,
                collection=coll,
                session=session,
            )

    except Exception as e:
        logger.warning(f"symbol_graph query failed: {e}")
        # Fall back to semantic search
        results = await _fallback_semantic_search(
            symbol=symbol,
            query_type=query_type,
            limit=limit,
            language=language,
            repo=repo,
            collection=coll,
            session=session,
        )

    # Multi-hop traversal: if depth > 1 and we have callers/importers results,
    # recursively find callers/importers of those results
    if depth > 1 and results and query_type in ("callers", "importers", "callees"):
        all_results = list(results)  # Copy initial results
        seen_symbols: Set[str] = {symbol}  # Track visited symbols
        current_hop_results = results

        for hop in range(2, depth + 1):
            next_hop_results: List[Dict[str, Any]] = []

            # Parallelize traversal across current hop symbols
            # Track (via_symbol, task) pairs to maintain correct attribution
            hop_tasks_with_via: List[Tuple[str, Any]] = []
            for r in current_hop_results:
                hop_symbol = r.get("symbol_path") or r.get("symbol", "")
                if not hop_symbol or hop_symbol in seen_symbols:
                    continue
                seen_symbols.add(hop_symbol)

                hop_tasks_with_via.append((
                    hop_symbol,  # via_symbol for attribution
                    graph_query_fn(
                        client=client,
                        collection=coll,
                        symbol=hop_symbol,
                        query_type=query_type,
                        limit=max(5, limit // hop),
                        repo=repo,
                    )
                ))

            if hop_tasks_with_via:
                # Extract just the tasks for gather
                hop_tasks = [task for _, task in hop_tasks_with_via]
                hop_results_batch = await asyncio.gather(*hop_tasks)

                for (via_symbol, _), hop_graph_results in zip(hop_tasks_with_via, hop_results_batch):
                    if hop_graph_results:
                        hydrated = await _hydrate_graph_results(client, coll, hop_graph_results)
                        for hr in hydrated:
                            hr["hop"] = hop
                            hr["via"] = via_symbol
                            if hr.get("symbol_path") not in seen_symbols:
                                next_hop_results.append(hr)
                                all_results.append(hr)

            current_hop_results = next_hop_results

            # Stop if no new results found
            if not next_hop_results:
                break

        # Mark first hop results
        for r in results:
            r["hop"] = 1

        # Sort by hop first (ascending), then by proximity_score within each hop (descending)
        # This ensures stable ordering: hop=1 results first, then hop=2, etc.
        all_results.sort(
            key=lambda x: (x.get("hop", 1), -x.get("proximity_score", 0)),
        )
        results = all_results[:limit]

    # Add suggestions if no results found
    suggestions = []
    hint = ""
    if not results:
        suggestions_limit = int(os.environ.get("SYMBOL_SUGGESTIONS_LIMIT", "3") or 3)
        suggestion_tuples = _get_symbol_suggestions(symbol, coll, limit=suggestions_limit)
        suggestions = [s[0] for s in suggestion_tuples]  # Extract symbol names only
        if suggestions:
            hint = f"Symbol '{symbol}' not found. Did you mean: {', '.join(suggestions)}?"

    response = {
        "results": results,
        "symbol": symbol,
        "query_type": query_type,
        "count": len(results),
        "collection": coll,
        "used_graph": used_graph,
        "depth": depth,
    }

    # Add suggestions and hint if applicable
    if suggestions:
        response["suggestions"] = suggestions
        response["hint"] = hint

    return response


async def _query_array_field(
    client: Any,
    collection: str,
    field_key: str,
    value: str,
    limit: int,
    language: Optional[str] = None,
    under: Optional[str] = None,
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Query for points where an array field contains a specific value.

    Uses a multi-strategy approach for robust matching:
    1. MatchAny for exact array element matching
    2. MatchAny with symbol variants (qualified names)
    3. MatchText for substring fallback
    """
    from qdrant_client import models as qmodels

    results: List[Any] = []
    seen_ids: Set[str] = set()

    # Build base conditions for optional filters
    base_conditions = []
    if language:
        base_conditions.append(
            qmodels.FieldCondition(
                key="metadata.language",
                match=qmodels.MatchValue(value=language.lower()),
            )
        )
    if under:
        # Use MatchText for substring matching - under is normalized to "/scripts"
        # which matches path_prefix like "/work/Context-Engine-xxx/scripts"
        base_conditions.append(
            qmodels.FieldCondition(
                key="metadata.path_prefix",
                match=qmodels.MatchText(text=under),
            )
        )
    if repo and repo != "*":
        base_conditions.append(
            qmodels.FieldCondition(
                key="metadata.repo",
                match=qmodels.MatchValue(value=repo),
            )
        )

    # Strategy 1: Exact match with MatchAny (most reliable for array fields)
    try:
        filter1 = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key=field_key,
                    match=qmodels.MatchAny(any=[value]),
                )
            ] + base_conditions
        )

        def scroll1():
            return client.scroll(
                collection_name=collection,
                scroll_filter=filter1,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )

        scroll_result = await asyncio.to_thread(scroll1)
        points = scroll_result[0] if scroll_result else []
        for pt in points:
            pt_id = str(getattr(pt, "id", id(pt)))
            if pt_id not in seen_ids:
                seen_ids.add(pt_id)
                results.append(pt)
    except Exception as e:
        logger.debug(f"Strategy 1 (MatchAny exact) failed: {e}")

    # Strategy 2: Try symbol variants (e.g., "MyClass.method" -> also try "method")
    if len(results) < limit:
        variants = _symbol_variants(value)
        for variant in variants[1:]:  # Skip first (exact match already tried)
            if len(results) >= limit:
                break
            try:
                filter2 = qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key=field_key,
                            match=qmodels.MatchAny(any=[variant]),
                        )
                    ] + base_conditions
                )

                def scroll2():
                    return client.scroll(
                        collection_name=collection,
                        scroll_filter=filter2,
                        limit=limit - len(results),
                        with_payload=True,
                        with_vectors=False,
                    )

                scroll_result = await asyncio.to_thread(scroll2)
                points = scroll_result[0] if scroll_result else []
                for pt in points:
                    pt_id = str(getattr(pt, "id", id(pt)))
                    if pt_id not in seen_ids:
                        seen_ids.add(pt_id)
                        results.append(pt)
            except Exception as e:
                logger.debug(f"Strategy 2 (variant '{variant}') failed: {e}")

    # Strategy 3: MatchText substring fallback for partial matches
    if len(results) < limit:
        try:
            filter3 = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key=field_key,
                        match=qmodels.MatchText(text=value),
                    )
                ] + base_conditions
            )

            def scroll3():
                return client.scroll(
                    collection_name=collection,
                    scroll_filter=filter3,
                    limit=limit - len(results),
                    with_payload=True,
                    with_vectors=False,
                )

            scroll_result = await asyncio.to_thread(scroll3)
            points = scroll_result[0] if scroll_result else []
            for pt in points:
                pt_id = str(getattr(pt, "id", id(pt)))
                if pt_id not in seen_ids:
                    seen_ids.add(pt_id)
                    results.append(pt)
        except Exception as e:
            # MatchText may not be supported on array fields in all Qdrant versions
            logger.debug(f"Strategy 3 (MatchText substring) failed: {e}")

    return [_format_point(pt) for pt in results[:limit]]


async def _query_definition(
    client: Any,
    collection: str,
    symbol: str,
    limit: int,
    language: Optional[str] = None,
    under: Optional[str] = None,
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Query for symbol definitions using symbol_path or symbol fields.
    """
    from qdrant_client import models as qmodels

    results = []

    # Build base conditions for optional filters
    base_conditions = []
    if language:
        base_conditions.append(
            qmodels.FieldCondition(
                key="metadata.language",
                match=qmodels.MatchValue(value=language.lower()),
            )
        )
    if under:
        # Use MatchText for substring matching - under is normalized to "/scripts"
        # which matches path_prefix like "/work/Context-Engine-xxx/scripts"
        base_conditions.append(
            qmodels.FieldCondition(
                key="metadata.path_prefix",
                match=qmodels.MatchText(text=under),
            )
        )
    if repo and repo != "*":
        base_conditions.append(
            qmodels.FieldCondition(
                key="metadata.repo",
                match=qmodels.MatchValue(value=repo),
            )
        )

    # For definition queries, we need to fetch enough chunks to find the one with
    # min(start_line). ReFRAG creates many micro-chunks per symbol, so use a higher
    # internal limit, then reduce to user's limit after grouping.
    internal_limit = max(limit * 20, 100)  # Fetch more to find true definition

    # Strategy 1: Exact match on symbol_path (e.g., "MyClass.my_method")
    try:
        filter1 = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="metadata.symbol_path",
                    match=qmodels.MatchValue(value=symbol),
                )
            ] + base_conditions
        )

        def scroll1():
            return client.scroll(
                collection_name=collection,
                scroll_filter=filter1,
                limit=internal_limit,
                with_payload=True,
                with_vectors=False,
            )

        scroll_result = await asyncio.to_thread(scroll1)
        points = scroll_result[0] if scroll_result else []
        results.extend(points)
    except Exception as e:
        logger.debug(f"symbol_path exact match failed: {e}")

    # Strategy 2: Exact match on symbol field
    if len(results) < internal_limit:
        try:
            filter2 = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="metadata.symbol",
                        match=qmodels.MatchValue(value=symbol),
                    )
                ] + base_conditions
            )

            def scroll2():
                return client.scroll(
                    collection_name=collection,
                    scroll_filter=filter2,
                    limit=internal_limit - len(results),
                    with_payload=True,
                    with_vectors=False,
                )

            scroll_result = await asyncio.to_thread(scroll2)
            points = scroll_result[0] if scroll_result else []
            results.extend(points)
        except Exception as e:
            logger.debug(f"symbol exact match failed: {e}")

    # Strategy 3: Text search on symbol_path for partial matches (e.g., "my_method" in "MyClass.my_method")
    # Skip for short symbols (< 6 chars) to avoid noisy substring matches like "embed" matching "get_embedding_model"
    min_len_for_text_match = 6
    if len(results) < internal_limit and len(symbol) >= min_len_for_text_match:
        try:
            filter3 = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="metadata.symbol_path",
                        match=qmodels.MatchText(text=symbol),
                    )
                ] + base_conditions
            )

            def scroll3():
                return client.scroll(
                    collection_name=collection,
                    scroll_filter=filter3,
                    limit=internal_limit - len(results),
                    with_payload=True,
                    with_vectors=False,
                )

            scroll_result = await asyncio.to_thread(scroll3)
            points = scroll_result[0] if scroll_result else []
            results.extend(points)
        except Exception as e:
            logger.debug(f"symbol_path text match failed: {e}")

    # Deduplicate by point ID
    seen_ids = set()
    unique_results = []
    for pt in results:
        pt_id = getattr(pt, "id", None)
        if pt_id not in seen_ids:
            seen_ids.add(pt_id)
            unique_results.append(pt)

    # ReFRAG-aware definition resolution:
    # Micro-chunks inherit their parent symbol's symbol_path, so multiple chunks
    # exist for each symbol. The actual definition is at min(start_line) per
    # (path, symbol_path) group - same logic as _get_symbol_extent in ranking.py.
    from collections import defaultdict

    def _pt_metadata(pt: Any) -> Dict[str, Any]:
        payload = getattr(pt, "payload", {}) or {}
        return payload.get("metadata", payload)

    def _pt_start_line(pt: Any) -> int:
        md = _pt_metadata(pt)
        try:
            return int(md.get("symbol_start_line") or md.get("start_line") or 999999)
        except (ValueError, TypeError):
            return 999999

    # Group by (path, symbol_path) to find the definition chunk for each symbol
    path_symbol_groups: Dict[Tuple[str, str], List[Any]] = defaultdict(list)
    for pt in unique_results:
        md = _pt_metadata(pt)
        path = str(md.get("path") or md.get("file_path") or "")
        sym_path = str(md.get("symbol_path") or md.get("symbol") or "")
        path_symbol_groups[(path, sym_path)].append(pt)

    # Code file extensions for definition filtering (exclude YAML, SQL, MD, etc.)
    CODE_EXTS = {
        "py", "js", "ts", "jsx", "tsx", "java", "c", "cpp", "cc", "h", "hpp",
        "go", "rs", "rb", "php", "swift", "kt", "kts", "scala", "cs", "fs",
        "lua", "r", "jl", "ex", "exs", "erl", "hs", "clj", "cljs", "ml", "mli",
    }

    def _is_code_file(pt: Any) -> bool:
        md = _pt_metadata(pt)
        ext = str(md.get("ext") or "").lower()
        return ext in CODE_EXTS

    # Pick the chunk with min(start_line) from each group - that's the definition
    definition_points = []
    for (path, sym_path), pts in path_symbol_groups.items():
        if pts:
            # Filter to code files first (if any), otherwise keep all
            code_pts = [p for p in pts if _is_code_file(p)]
            pts_to_use = code_pts if code_pts else pts
            # Find chunk with lowest start_line (closest to actual def/class line)
            best = min(pts_to_use, key=_pt_start_line)
            definition_points.append(best)

    # Filter out non-code file results for cleaner output (prefer code definitions)
    code_definitions = [p for p in definition_points if _is_code_file(p)]
    # Fall back to all if no code files found
    definition_points = code_definitions if code_definitions else definition_points

    # Sort by path then start_line for consistent ordering
    definition_points.sort(key=lambda p: (
        _pt_metadata(p).get("path", ""),
        _pt_start_line(p),
    ))

    return [_format_point(pt) for pt in definition_points[:limit]]


def _get_path(pt: Any) -> str:  # noqa: F811 - helper for deduplication
    """Extract path from point payload."""
    payload = getattr(pt, "payload", {}) or {}
    md = payload.get("metadata", payload)
    return str(md.get("path") or md.get("file_path") or "")


def _format_point(pt: Any) -> Dict[str, Any]:
    """Format a Qdrant point for the API response."""
    payload = getattr(pt, "payload", {}) or {}
    md = payload.get("metadata", payload)

    # Get code snippet - prefer raw code from metadata
    info = payload.get("information") or payload.get("document") or ""
    raw_code = md.get("code") or info
    snippet = _extract_snippet(raw_code, max_chars=500) if raw_code else ""

    result = {
        "path": str(md.get("path") or md.get("file_path") or ""),
        "start_line": int(md.get("symbol_start_line") or md.get("start_line") or md.get("start") or 0),
        "end_line": int(md.get("symbol_end_line") or md.get("end_line") or md.get("end") or 0),
        "symbol": str(md.get("symbol") or ""),
        "symbol_path": str(md.get("symbol_path") or ""),
        "language": str(md.get("language") or ""),
        "snippet": snippet,
        # NOTE: calls/imports arrays are NOT included in response to reduce token bloat.
        # They are used for querying (already done) but not needed in output.
        # The LLM already knows "this file calls/imports X" because that's why it matched.
    }

    return result


async def _fallback_semantic_search(
    symbol: str,
    query_type: str,
    limit: int = 20,
    language: Optional[str] = None,
    repo: Optional[str] = None,
    collection: Optional[str] = None,
    session: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fallback to semantic search when filter-based search returns no results.
    """
    # Construct a query based on what we're looking for
    query_prefixes = {
        "callers": f"code that calls {symbol}",
        "definition": f"definition of {symbol} function class",
        "importers": f"code that imports {symbol}",
    }
    query = query_prefixes.get(query_type, symbol)

    try:
        from scripts.mcp_impl.search import _repo_search_impl

        search_result = await _repo_search_impl(
            query=query,
            limit=limit,
            language=language,
            repo=repo,
            session=session,
            output_format="json",  # Avoid TOON encoding for internal calls
        )

        # Handle case where results might be TOON-encoded string (shouldn't happen with output_format="json")
        results = search_result.get("results", [])
        if isinstance(results, str):
            # If somehow still a string, return empty - TOON decoding is not worth it here
            logger.debug("Fallback search returned TOON-encoded results, skipping")
            return []
        return results

    except Exception as e:
        logger.warning(f"Fallback semantic search failed: {e}")
        return []


def _format_symbol_graph_toon(result: Dict[str, Any]) -> str:
    """Format symbol graph results in TOON format for token efficiency."""
    lines = []
    query_type = result.get("query_type", "")
    symbol = result.get("symbol", "")
    results = result.get("results", [])

    if not results:
        return f"≡ SYMBOL_GRAPH | {query_type} | {symbol}\n⚠ No results found"

    lines.append(f"≡ SYMBOL_GRAPH | {query_type} | {symbol} | {len(results)} results")

    for r in results:
        path = r.get("path", "")
        start = r.get("start_line", 0)
        end = r.get("end_line", 0)
        sym = r.get("symbol_path") or r.get("symbol") or ""

        line = f"→ {path}:{start}-{end}"
        if sym:
            line += f" | {sym}"

        lines.append(line)

    return "\n".join(lines)


async def _compute_called_by(
    symbol: str,
    limit: int = 50,
    language: Optional[str] = None,
    under: Optional[str] = None,
    collection: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute "called_by" - the inverse of what a symbol calls.

    Given a symbol (e.g., function or method), finds all functions that:
    1. Are defined in the codebase
    2. Have this symbol in their metadata.calls list

    This is the ego-graph concept simplified: "Who references me?"

    Args:
        symbol: The symbol name to find callers for
        limit: Maximum number of callers to return
        language: Optional language filter
        under: Optional path prefix filter
        collection: Optional collection override

    Returns:
        Dict with:
        - symbol: The queried symbol
        - called_by: List of {path, symbol, symbol_path, line} for callers
        - count: Number of callers found
    """
    from qdrant_client import QdrantClient
    from qdrant_client import models as qmodels

    # Get collection
    coll = str(collection or "").strip()
    if not coll:
        try:
            from scripts.mcp_impl.workspace import _default_collection
            coll = _default_collection() or ""
        except Exception:
            coll = os.environ.get("COLLECTION_NAME", "codebase")
    if not coll:
        coll = os.environ.get("COLLECTION_NAME", "codebase")

    try:
        client = QdrantClient(
            url=QDRANT_URL,
            api_key=os.environ.get("QDRANT_API_KEY"),
            timeout=float(os.environ.get("QDRANT_TIMEOUT", "20") or 20),
        )
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant: {e}")
        return {
            "symbol": symbol,
            "called_by": [],
            "count": 0,
            "error": f"Qdrant connection failed: {e}",
        }

    # Build filter: find chunks where metadata.calls contains symbol
    base_conditions = []
    if language:
        base_conditions.append(
            qmodels.FieldCondition(
                key="metadata.language",
                match=qmodels.MatchValue(value=language.lower()),
            )
        )
    norm_under = _norm_under(under)
    if norm_under:
        # Use MatchText for substring matching - norm_under is "/scripts"
        # which matches path_prefix like "/work/Context-Engine-xxx/scripts"
        base_conditions.append(
            qmodels.FieldCondition(
                key="metadata.path_prefix",
                match=qmodels.MatchText(text=norm_under),
            )
        )

    callers: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    # Try exact match first
    try:
        variants = _symbol_variants(symbol)
        for variant in variants:
            if len(callers) >= limit:
                break

            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="metadata.calls",
                        match=qmodels.MatchAny(any=[variant]),
                    )
                ] + base_conditions
            )

            def do_scroll():
                return client.scroll(
                    collection_name=coll,
                    scroll_filter=query_filter,
                    limit=limit - len(callers),
                    with_payload=True,
                    with_vectors=False,
                )

            scroll_result = await asyncio.to_thread(do_scroll)
            points = scroll_result[0] if scroll_result else []

            for pt in points:
                pt_id = str(getattr(pt, "id", id(pt)))
                if pt_id in seen_ids:
                    continue
                seen_ids.add(pt_id)

                payload = getattr(pt, "payload", {}) or {}
                md = payload.get("metadata", payload)

                # Only include if this chunk has a symbol (is a function/class definition)
                chunk_symbol = str(md.get("symbol") or "")
                if not chunk_symbol:
                    continue

                caller_info = {
                    "path": str(md.get("path") or ""),
                    "symbol": chunk_symbol,
                    "symbol_path": str(md.get("symbol_path") or ""),
                    "start_line": int(md.get("start_line") or md.get("start") or 0),
                    "end_line": int(md.get("end_line") or md.get("end") or 0),
                    "language": str(md.get("language") or ""),
                }
                callers.append(caller_info)

    except Exception as e:
        logger.warning(f"_compute_called_by query failed: {e}")

    return {
        "symbol": symbol,
        "called_by": callers[:limit],
        "count": len(callers[:limit]),
        "collection": coll,
    }


async def _get_symbol_calls(
    symbol_path: str,
    collection: Optional[str] = None,
) -> List[str]:
    """
    Get the list of calls made by a specific symbol.

    Useful for building call graphs: given a function, what does it call?

    Args:
        symbol_path: The symbol_path to look up (e.g., "MyClass.my_method")
        collection: Optional collection override

    Returns:
        List of function/method names called by this symbol
    """
    from qdrant_client import QdrantClient
    from qdrant_client import models as qmodels

    coll = str(collection or "").strip()
    if not coll:
        try:
            from scripts.mcp_impl.workspace import _default_collection
            coll = _default_collection() or ""
        except Exception:
            coll = os.environ.get("COLLECTION_NAME", "codebase")
    if not coll:
        coll = os.environ.get("COLLECTION_NAME", "codebase")

    try:
        client = QdrantClient(
            url=QDRANT_URL,
            api_key=os.environ.get("QDRANT_API_KEY"),
            timeout=float(os.environ.get("QDRANT_TIMEOUT", "20") or 20),
        )
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant: {e}")
        return []

    # Find the symbol definition
    try:
        query_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="metadata.symbol_path",
                    match=qmodels.MatchValue(value=symbol_path),
                )
            ]
        )

        def do_scroll():
            return client.scroll(
                collection_name=coll,
                scroll_filter=query_filter,
                limit=1,
                with_payload=True,
                with_vectors=False,
            )

        scroll_result = await asyncio.to_thread(do_scroll)
        points = scroll_result[0] if scroll_result else []

        if points:
            payload = getattr(points[0], "payload", {}) or {}
            md = payload.get("metadata", payload)
            return md.get("calls") or []

    except Exception as e:
        logger.warning(f"_get_symbol_calls failed: {e}")

    return []
# trigger
