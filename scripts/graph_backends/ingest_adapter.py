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
    symbol_paths: Optional[Dict[str, str]] = None,
    import_paths: Optional[Dict[str, str]] = None,
) -> List[GraphEdge]:
    """Extract call edge objects from a chunk's calls list.

    Args:
        symbol_path: The caller symbol's qualified path
        calls: List of callee symbol names
        path: File path of the caller
        repo: Repository name
        start_line: Starting line of the caller symbol
        end_line: Ending line of the caller symbol
        language: Programming language
        caller_point_id: Qdrant point ID of caller chunk
        symbol_paths: Dict mapping symbol names to their file paths (for same-file resolution)
        import_paths: Dict mapping imported names to their module paths (for import resolution)

    Returns GraphEdge objects for use with any backend.
    """
    if not symbol_path or not calls:
        return []

    norm_path = _normalize_path(path)
    edges = []
    symbol_paths = symbol_paths or {}
    import_paths = import_paths or {}

    for callee in calls:
        if not callee:
            continue

        # Resolve callee path: check same-file symbols first, then imports, then use stub
        callee_path: Optional[str] = None

        # 1. Check if callee is defined in the same file (by name or qualified path)
        if callee in symbol_paths:
            callee_path = symbol_paths[callee]
        else:
            # Check if callee matches end of a qualified path (e.g., "MyClass.method" -> "method")
            for sym_name, sym_path in symbol_paths.items():
                if sym_name.endswith(f".{callee}") or sym_name == callee:
                    callee_path = sym_path
                    break

        # 2. Check if callee is an imported symbol
        if not callee_path and callee in import_paths:
            callee_path = import_paths[callee]

        # 3. For unresolved callees, use a deterministic stub path
        # This ensures all references to "print" go to the same "<builtin>/print" node
        if not callee_path:
            # Categorize: builtins vs external vs unknown
            python_builtins = {
                "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
                "set", "tuple", "open", "type", "isinstance", "getattr", "setattr",
                "hasattr", "super", "property", "classmethod", "staticmethod", "enumerate",
                "zip", "map", "filter", "sorted", "reversed", "min", "max", "sum", "abs",
                "all", "any", "repr", "format", "input", "id", "hash", "iter", "next",
                "callable", "vars", "dir", "globals", "locals", "eval", "exec", "compile",
            }
            js_builtins = {
                "console", "log", "warn", "error", "setTimeout", "setInterval",
                "fetch", "Promise", "JSON", "Array", "Object", "String", "Number",
                "Boolean", "Date", "Math", "RegExp", "Error", "Map", "Set",
            }

            base_callee = callee.split(".")[-1] if "." in callee else callee
            if base_callee in python_builtins or base_callee in js_builtins:
                callee_path = f"<builtin>/{base_callee}"
            else:
                # External or unresolved - use module prefix if available
                callee_path = f"<external>/{callee}"

        edge_id = _edge_id(symbol_path, callee, norm_path, EDGE_TYPE_CALLS, repo)
        edges.append(GraphEdge(
            id=edge_id,
            caller_symbol=symbol_path,
            callee_symbol=callee,
            caller_path=norm_path,
            callee_path=callee_path,
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
        # For imports, callee_path is the module path itself (e.g., "os.path", "numpy")
        # This creates deterministic nodes for external modules
        callee_path = f"<module>/{imported}"

        edge_id = _edge_id(caller, imported, norm_path, EDGE_TYPE_IMPORTS, repo)
        edges.append(GraphEdge(
            id=edge_id,
            caller_symbol=caller,
            callee_symbol=imported,
            caller_path=norm_path,
            callee_path=callee_path,
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

