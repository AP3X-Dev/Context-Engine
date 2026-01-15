# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Internal Graph RAG enhancement layer.

Provides transparent graph-enhanced retrieval when advanced graph backend is available.
This module is internal and should not be exposed to end users.

All functions gracefully fall back to basic behavior when the enhanced backend
is not available.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set

from . import ensure_plugins_path, is_neo4j_enabled

logger = logging.getLogger(__name__)

__all__ = [
    # Query functions
    "get_subgraph_context",
    "get_impact_analysis",
    "get_transitive_callers",
    "get_symbol_importance",
    "find_similar_symbols",
    "get_graph_distance",
    # Reranking and context
    "rerank_by_graph_distance",
    "get_connected_symbols",
    "get_k_hop_context",
]

# Internal flag - use shared utility
_ENHANCED_GRAPH_AVAILABLE = is_neo4j_enabled()

# Lazy-loaded knowledge graph instance
_KNOWLEDGE_GRAPH = None


def _get_knowledge_graph():
    """Get enhanced knowledge graph if available (internal only)."""
    global _KNOWLEDGE_GRAPH

    if not _ENHANCED_GRAPH_AVAILABLE:
        return None

    if _KNOWLEDGE_GRAPH is not None:
        return _KNOWLEDGE_GRAPH

    try:
        ensure_plugins_path()
        from neo4j_graph.knowledge_graph import get_knowledge_graph
        _KNOWLEDGE_GRAPH = get_knowledge_graph()
        return _KNOWLEDGE_GRAPH
    except ImportError:
        return None
    except Exception as e:
        logger.debug(f"Enhanced graph not available: {e}")
        return None


def get_subgraph_context(
    symbol_name: str,
    repo: Optional[str] = None,
    radius: int = 2,
) -> Optional[Dict[str, Any]]:
    """Get subgraph context around a symbol for RAG augmentation.
    
    Returns None if enhanced graph is not available.
    Falls back silently - callers should handle None gracefully.
    """
    kg = _get_knowledge_graph()
    if not kg:
        return None
    
    try:
        return kg.get_subgraph_context(symbol_name, repo=repo, radius=radius)
    except Exception as e:
        logger.debug(f"Subgraph context failed: {e}")
        return None


def get_impact_analysis(
    symbol_name: str,
    repo: Optional[str] = None,
    max_depth: int = 3,
) -> Optional[Dict[str, Any]]:
    """Analyze impact of changing a symbol.
    
    Returns None if enhanced graph is not available.
    """
    kg = _get_knowledge_graph()
    if not kg:
        return None
    
    try:
        return kg.impact_analysis(symbol_name, repo=repo, max_depth=max_depth)
    except Exception as e:
        logger.debug(f"Impact analysis failed: {e}")
        return None


def get_transitive_callers(
    symbol_name: str,
    repo: Optional[str] = None,
    depth: int = 2,
    limit: int = 50,
) -> Optional[List[Dict[str, Any]]]:
    """Get multi-hop callers of a symbol.
    
    Returns None if enhanced graph is not available.
    """
    kg = _get_knowledge_graph()
    if not kg:
        return None
    
    try:
        return kg.get_callers(symbol_name, repo=repo, depth=depth, limit=limit)
    except Exception as e:
        logger.debug(f"Transitive callers failed: {e}")
        return None


def get_symbol_importance(
    symbol_name: str,
    repo: Optional[str] = None,
) -> Optional[float]:
    """Get PageRank-based importance score for a symbol.
    
    Returns None if enhanced graph is not available or symbol not found.
    Higher values = more important (more things depend on it).
    """
    kg = _get_knowledge_graph()
    if not kg:
        return None
    
    try:
        results = kg.find_symbol(symbol_name, repo=repo)
        if results:
            return results[0].get("importance", 0.0)
        return None
    except Exception:
        return None


def find_similar_symbols(
    symbol_name: str,
    repo: Optional[str] = None,
    limit: int = 5,
) -> Optional[List[Dict[str, Any]]]:
    """Find symbols with similar call patterns.
    
    Returns None if enhanced graph is not available.
    """
    kg = _get_knowledge_graph()
    if not kg:
        return None
    
    try:
        return kg.find_similar(symbol_name, repo=repo, limit=limit)
    except Exception as e:
        logger.debug(f"Similar symbols failed: {e}")
        return None


def get_graph_distance(
    source_symbol: str,
    target_symbol: str,
    repo: Optional[str] = None,
    max_depth: int = 4,
) -> Optional[int]:
    """Get shortest path distance between two symbols in the graph.

    Returns None if enhanced graph is not available or no path exists.
    Returns 0 if source == target.
    """
    if source_symbol == target_symbol:
        return 0

    kg = _get_knowledge_graph()
    if not kg:
        return None

    try:
        return kg.get_shortest_path_length(source_symbol, target_symbol, repo=repo, max_depth=max_depth)
    except Exception as e:
        logger.debug(f"Graph distance failed: {e}")
        return None


def rerank_by_graph_distance(
    results: List[Dict[str, Any]],
    query_symbols: List[str],
    repo: Optional[str] = None,
    distance_weight: float = 0.15,
) -> List[Dict[str, Any]]:
    """Rerank search results by graph distance to query symbols.

    Boosts results that are closer in the call graph to the query symbols.
    Falls back to original ranking if graph is not available.

    Args:
        results: Search results with 'score' and 'metadata.symbol_path' fields
        query_symbols: Symbols extracted from the query
        repo: Optional repo filter
        distance_weight: How much to boost based on distance (0.0-1.0)

    Returns:
        Reranked results with updated scores
    """
    if not results or not query_symbols:
        return results

    kg = _get_knowledge_graph()
    if not kg:
        return results

    # Extract all target symbols from results
    result_symbols: List[str] = []
    symbol_to_results: Dict[str, List[Dict[str, Any]]] = {}

    for result in results:
        symbol_path = (
            result.get("metadata", {}).get("symbol_path") or
            result.get("symbol_path") or
            result.get("symbol") or
            ""
        )
        if symbol_path:
            result_symbols.append(symbol_path)
            if symbol_path not in symbol_to_results:
                symbol_to_results[symbol_path] = []
            symbol_to_results[symbol_path].append(result)

    if not result_symbols:
        return results

    # Limit query symbols for efficiency
    limited_query_symbols = query_symbols[:3]

    # Try batch query first (much more efficient)
    distances: Dict[tuple, int] = {}
    try:
        if hasattr(kg, 'get_batch_shortest_path_lengths'):
            distances = kg.get_batch_shortest_path_lengths(
                limited_query_symbols,
                result_symbols,
                repo=repo,
                max_depth=4
            )
    except Exception:
        pass

    # Fall back to individual queries only if batch failed and we have few results
    if not distances and len(results) <= 10:
        for result in results:
            symbol_path = (
                result.get("metadata", {}).get("symbol_path") or
                result.get("symbol_path") or
                result.get("symbol") or
                ""
            )
            if not symbol_path:
                continue

            for qs in limited_query_symbols:
                dist = get_graph_distance(qs, symbol_path, repo=repo)
                if dist is not None:
                    key = (qs, symbol_path)
                    if key not in distances or dist < distances[key]:
                        distances[key] = dist

    # Apply boosts based on distances
    for result in results:
        symbol_path = (
            result.get("metadata", {}).get("symbol_path") or
            result.get("symbol_path") or
            result.get("symbol") or
            ""
        )
        if not symbol_path:
            continue

        # Find minimum distance to any query symbol
        min_distance = None
        for qs in limited_query_symbols:
            dist = distances.get((qs, symbol_path))
            if dist is not None:
                if min_distance is None or dist < min_distance:
                    min_distance = dist

        if min_distance is not None:
            # Boost: closer = higher boost
            # Distance 0 = max boost, distance 4+ = no boost
            boost = max(0.0, (4 - min_distance) / 4.0) * distance_weight
            original_score = result.get("score", 0.5)
            result["score"] = original_score + boost
            result["_graph_distance"] = min_distance
            result["_graph_boost"] = boost

    # Re-sort by updated score
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results


def get_connected_symbols(
    symbol_name: str,
    repo: Optional[str] = None,
    depth: int = 1,
    limit: int = 20,
) -> Optional[List[str]]:
    """Get symbols connected to the given symbol within N hops.

    Returns None if enhanced graph is not available.
    """
    kg = _get_knowledge_graph()
    if not kg:
        return None

    try:
        ctx = kg.get_subgraph_context(symbol_name, repo=repo, radius=depth)
        if not ctx:
            return None

        symbols = []
        for node in ctx.get("nodes", [])[:limit]:
            name = node.get("name", "")
            if name and name != symbol_name:
                symbols.append(name)
        return symbols
    except Exception as e:
        logger.debug(f"Connected symbols failed: {e}")
        return None


def get_k_hop_context(
    symbols: List[str],
    repo: Optional[str] = None,
    k: int = 2,
    max_nodes: int = 30,
    include_paths: bool = True,
) -> Dict[str, Any]:
    """Get k-hop neighborhood context for RAG augmentation.

    Expands from multiple seed symbols to find related code context.
    Returns structured data suitable for LLM prompts.

    Args:
        symbols: Seed symbols to expand from
        repo: Optional repo filter
        k: Number of hops to expand
        max_nodes: Maximum nodes to return
        include_paths: Include file paths in results

    Returns:
        Dict with 'nodes', 'relationships', 'summary' for RAG context
    """
    kg = _get_knowledge_graph()
    if not kg:
        return {"nodes": [], "relationships": [], "summary": "Graph not available"}

    all_nodes: Dict[str, Dict[str, Any]] = {}
    all_rels: List[Dict[str, Any]] = []

    for sym in symbols[:5]:  # Limit seed symbols
        try:
            ctx = kg.get_subgraph_context(sym, repo=repo, radius=k)
            if not ctx:
                continue

            for node in ctx.get("nodes", []):
                name = node.get("name", "")
                if name and name not in all_nodes:
                    all_nodes[name] = {
                        "name": name,
                        "type": node.get("labels", ["Unknown"])[0] if node.get("labels") else "Unknown",
                        "path": node.get("path", "") if include_paths else None,
                        "start_line": node.get("start_line"),
                        "importance": node.get("pagerank", 0.0) or 0.0,
                    }

            for rel in ctx.get("relationships", []):
                all_rels.append({
                    "source": rel.get("source", ""),
                    "target": rel.get("target", ""),
                    "type": rel.get("type", ""),
                })
        except Exception:
            continue

    # Sort by importance and limit
    sorted_nodes = sorted(
        all_nodes.values(),
        key=lambda x: x.get("importance", 0),
        reverse=True
    )[:max_nodes]

    # Build summary for LLM
    node_names = [n["name"] for n in sorted_nodes[:10]]
    rel_types = list(set(r["type"] for r in all_rels))
    summary = f"Found {len(sorted_nodes)} related symbols connected via {', '.join(rel_types) or 'relationships'}. Key symbols: {', '.join(node_names)}"

    return {
        "nodes": sorted_nodes,
        "relationships": all_rels[:50],  # Limit relationships
        "summary": summary,
        "seed_symbols": symbols,
        "k": k,
    }

