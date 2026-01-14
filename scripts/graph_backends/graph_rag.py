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

logger = logging.getLogger(__name__)

# Internal flag - do not expose
_ENHANCED_GRAPH_AVAILABLE = str(os.environ.get("NEO4J_GRAPH", "")).strip().lower() in {
    "1", "true", "yes", "on"
}

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
        import sys
        from pathlib import Path
        plugins_dir = Path(__file__).parent.parent.parent / "plugins"
        if str(plugins_dir) not in sys.path:
            sys.path.insert(0, str(plugins_dir))
        
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

