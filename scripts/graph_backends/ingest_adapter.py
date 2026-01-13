# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Ingest adapter for graph backends.

Provides unified functions for graph edge operations that route through
the configured backend (Qdrant or Neo4j). This adapter is used by the
ingest pipeline to store symbol relationships.

The adapter maintains backward compatibility - when NEO4J_GRAPH is not set,
it delegates directly to the existing graph_edges.py functions.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

from . import GRAPH_BACKEND_TYPE, get_graph_backend
from .base import GraphEdge

logger = logging.getLogger(__name__)

# Re-export constants for compatibility
EDGE_TYPE_CALLS = "calls"
EDGE_TYPE_IMPORTS = "imports"
GRAPH_COLLECTION_SUFFIX = "_graph"


def _normalize_path(path: str) -> str:
    """Normalize path for consistent edge matching."""
    if not path:
        return ""
    return os.path.normpath(path).replace("\\", "/")


def _edge_id(
    caller_symbol: str,
    callee_symbol: str,
    caller_path: str,
    edge_type: str,
    repo: str,
) -> str:
    """Generate deterministic edge ID."""
    norm_path = _normalize_path(caller_path)
    key = f"{edge_type}:{repo}:{caller_symbol}:{callee_symbol}:{norm_path}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def extract_call_edges(
    symbol_path: str,
    calls: List[str],
    path: str,
    repo: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    language: Optional[str] = None,
    caller_point_id: Optional[str] = None,
) -> List[GraphEdge]:
    """Extract call edge objects from a chunk's calls list.
    
    Returns GraphEdge objects for use with any backend.
    """
    if not symbol_path or not calls:
        return []
    
    norm_path = _normalize_path(path)
    edges = []
    
    for callee in calls:
        if not callee:
            continue
        edge_id = _edge_id(symbol_path, callee, norm_path, EDGE_TYPE_CALLS, repo)
        edges.append(GraphEdge(
            id=edge_id,
            caller_symbol=symbol_path,
            callee_symbol=callee,
            caller_path=norm_path,
            edge_type=EDGE_TYPE_CALLS,
            repo=repo,
            start_line=start_line,
            end_line=end_line,
            language=language,
            caller_point_id=caller_point_id,
        ))
    
    return edges


def extract_import_edges(
    symbol_path: str,
    imports: List[str],
    path: str,
    repo: str,
    language: Optional[str] = None,
    caller_point_id: Optional[str] = None,
) -> List[GraphEdge]:
    """Extract import edge objects from a chunk's imports list."""
    if not imports:
        return []
    
    norm_path = _normalize_path(path)
    caller = symbol_path or norm_path
    edges = []
    
    for imported in imports:
        if not imported:
            continue
        edge_id = _edge_id(caller, imported, norm_path, EDGE_TYPE_IMPORTS, repo)
        edges.append(GraphEdge(
            id=edge_id,
            caller_symbol=caller,
            callee_symbol=imported,
            caller_path=norm_path,
            edge_type=EDGE_TYPE_IMPORTS,
            repo=repo,
            language=language,
            caller_point_id=caller_point_id,
        ))
    
    return edges


def ensure_graph_store(client: "QdrantClient", base_collection: str) -> Optional[str]:
    """Ensure graph store exists using the configured backend.
    
    For Qdrant: Creates/returns the graph collection name
    For Neo4j: Initializes the database and returns the database name
    """
    backend = get_graph_backend()
    return backend.ensure_graph_store(base_collection)


def upsert_edges(
    client: "QdrantClient",  # Kept for API compatibility
    graph_store: str,
    edges: List[GraphEdge],
    batch_size: int = 100,
) -> int:
    """Upsert edges using the configured backend."""
    backend = get_graph_backend()
    return backend.upsert_edges(graph_store, edges, batch_size)


def delete_edges_by_path(
    client: "QdrantClient",  # Kept for API compatibility
    graph_store: str,
    path: str,
    repo: Optional[str] = None,
) -> int:
    """Delete edges by path using the configured backend."""
    backend = get_graph_backend()
    return backend.delete_edges_by_path(graph_store, path, repo)

