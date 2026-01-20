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

import logging
import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

from . import GRAPH_BACKEND_TYPE, get_graph_backend
from .base import GraphEdge

# Import shared utilities from graph_edges directly (avoid circular import via __init__.py)
# Using importlib to bypass scripts.ingest.__init__.py which imports pipeline.py
import importlib.util
_graph_edges_spec = importlib.util.spec_from_file_location(
    "graph_edges",
    os.path.join(os.path.dirname(__file__), "..", "ingest", "graph_edges.py")
)
_graph_edges = importlib.util.module_from_spec(_graph_edges_spec)
_graph_edges_spec.loader.exec_module(_graph_edges)

normalize_path = _graph_edges.normalize_path
edge_id = _graph_edges.edge_id
EDGE_TYPE_CALLS = _graph_edges.EDGE_TYPE_CALLS
EDGE_TYPE_IMPORTS = _graph_edges.EDGE_TYPE_IMPORTS
EDGE_TYPE_INHERITS_FROM = _graph_edges.EDGE_TYPE_INHERITS_FROM
GRAPH_COLLECTION_SUFFIX = _graph_edges.GRAPH_COLLECTION_SUFFIX

logger = logging.getLogger(__name__)

# AST-based builtin detection using tree-sitter (supports 16+ languages)
try:
    from scripts.ast_analyzer import is_builtin
    _AST_AVAILABLE = True
except ImportError:
    _AST_AVAILABLE = False

    def is_builtin(name: str, language: str) -> bool:
        """Fallback when ast_analyzer unavailable.

        Returns False - without tree-sitter, we can't detect builtins.
        Everything unresolved becomes <external>.
        """
        return False


# Backward compatibility aliases
_normalize_path = normalize_path
_edge_id = edge_id


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
    collection: Optional[str] = None,
    qdrant_client: Optional["QdrantClient"] = None,
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
        collection: Collection name for cross-file symbol resolution
        qdrant_client: Qdrant client for cross-file symbol resolution

    Returns GraphEdge objects for use with any backend.
    """
    if not symbol_path or not calls:
        return []

    norm_path = _normalize_path(path)
    edges = []
    symbol_paths = symbol_paths or {}
    import_paths = import_paths or {}

    # Get symbol resolver for cross-file resolution
    resolver = None
    if collection and os.environ.get("RESOLVE_CROSS_FILE_EDGES", "1").lower() in {"1", "true", "yes", "on"}:
        try:
            from .symbol_resolver import get_symbol_resolver
            resolver = get_symbol_resolver(collection)
        except Exception as e:
            logger.debug(f"Could not get symbol resolver for {collection}: {e}")

    for callee in calls:
        if not callee:
            continue

        # Resolve callee path: check same-file symbols first, then imports, then use stub
        callee_path: Optional[str] = None
        # Use qualified callee name for the edge (from import_map if available)
        qualified_callee = callee

        # 1. Check if callee is defined in the same file (by name or qualified path)
        if callee in symbol_paths:
            callee_path = symbol_paths[callee]
        else:
            # Check if callee matches end of a qualified path (e.g., "MyClass.method" -> "method")
            for sym_name, sym_path in symbol_paths.items():
                if sym_name.endswith(f".{callee}") or sym_name == callee:
                    callee_path = sym_path
                    qualified_callee = sym_name  # Use qualified name from symbol_paths
                    break

        # 2. Check if callee is an imported symbol - use import_paths (import_map)
        # import_paths maps local names to qualified module.symbol paths
        # e.g., {"QdrantClient": "qdrant_client.QdrantClient"}
        if not callee_path and callee in import_paths:
            qualified_callee = import_paths[callee]  # Use qualified path
            # Try to resolve the qualified path to a file
            if resolver:
                try:
                    resolved = resolver.resolve_symbol(qualified_callee, repo)
                    if resolved:
                        callee_path = resolved
                except Exception as e:
                    logger.debug(f"Failed to resolve qualified symbol {qualified_callee}: {e}")

        # 3. Try cross-file resolution via symbol resolver (for unqualified callees)
        if not callee_path and resolver:
            try:
                resolved = resolver.resolve_symbol(callee, repo)
                if resolved:
                    callee_path = resolved
            except Exception as e:
                logger.debug(f"Failed to resolve symbol {callee}: {e}")

        # 4. For unresolved callees, use a deterministic stub path
        # This ensures all references to "print" go to the same "<builtin>/print" node
        if not callee_path:
            base_callee = callee.split(".")[-1] if "." in callee else callee
            lang = language or "python"

            # Use tree-sitter based builtin detection (supports 16+ languages)
            if is_builtin(base_callee, lang):
                callee_path = f"<builtin>/{base_callee}"
            else:
                # External - use qualified name from import_map if available
                callee_path = f"<external>/{qualified_callee}"

        edge_id = _edge_id(symbol_path, qualified_callee, norm_path, EDGE_TYPE_CALLS, repo)
        edges.append(GraphEdge(
            id=edge_id,
            caller_symbol=symbol_path,
            callee_symbol=qualified_callee,  # Use qualified name
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
    collection: Optional[str] = None,
    qdrant_client: Optional["QdrantClient"] = None,
) -> List[GraphEdge]:
    """Extract import edge objects from a chunk's imports list."""
    if not imports:
        return []

    norm_path = _normalize_path(path)
    caller = symbol_path or norm_path
    edges = []

    # Get symbol resolver for cross-file resolution
    resolver = None
    if collection and os.environ.get("RESOLVE_CROSS_FILE_EDGES", "1").lower() in {"1", "true", "yes", "on"}:
        try:
            from .symbol_resolver import get_symbol_resolver
            resolver = get_symbol_resolver(collection)
        except Exception as e:
            logger.debug(f"Could not get symbol resolver for {collection}: {e}")

    for imported in imports:
        if not imported:
            continue

        # Try to resolve import to actual file path via symbol resolver
        callee_path = None
        if resolver:
            try:
                callee_path = resolver.resolve_import(imported, repo)
            except Exception as e:
                logger.debug(f"Failed to resolve import {imported}: {e}")

        # Fall back to external stub if not resolved
        # Symbol resolver handles cross-file resolution; unresolved = external
        if not callee_path:
            callee_path = f"<external>/{imported}"

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


def extract_inheritance_edges(
    class_name: str,
    base_classes: List[str],
    path: str,
    repo: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    language: Optional[str] = None,
    caller_point_id: Optional[str] = None,
    import_paths: Optional[Dict[str, str]] = None,
    collection: Optional[str] = None,
    qdrant_client: Optional["QdrantClient"] = None,
) -> List[GraphEdge]:
    """Extract inheritance edge objects from class definition.

    Args:
        class_name: The class name
        base_classes: List of base class names
        path: File path of the class definition
        repo: Repository name
        start_line: Starting line of the class definition
        end_line: Ending line of the class definition
        language: Programming language
        caller_point_id: Qdrant point ID of class chunk
        import_paths: Dict mapping imported names to their module paths
        collection: Collection name for cross-file resolution
        qdrant_client: Optional Qdrant client for cross-file resolution

    Returns GraphEdge objects representing INHERITS_FROM relationships.
    """
    if not class_name or not base_classes:
        return []

    norm_path = _normalize_path(path)
    edges = []
    import_paths = import_paths or {}

    # Get symbol resolver for cross-file resolution
    resolver = None
    if collection and os.environ.get("RESOLVE_CROSS_FILE_EDGES", "1").lower() in {"1", "true", "yes", "on"}:
        try:
            from .symbol_resolver import get_symbol_resolver
            resolver = get_symbol_resolver(collection)
        except Exception as e:
            logger.debug(f"Could not get symbol resolver for {collection}: {e}")

    for base_class in base_classes:
        if not base_class:
            continue

        # Resolve base class path
        callee_path: Optional[str] = None
        qualified_base = base_class

        # 1. Check import_paths for qualified name
        if base_class in import_paths:
            qualified_base = import_paths[base_class]
            if resolver:
                try:
                    resolved = resolver.resolve_symbol(qualified_base, repo)
                    if resolved:
                        callee_path = resolved
                except Exception as e:
                    logger.debug(f"Failed to resolve base class {qualified_base}: {e}")

        # 2. Try cross-file resolution
        if not callee_path and resolver:
            try:
                resolved = resolver.resolve_symbol(base_class, repo)
                if resolved:
                    callee_path = resolved
            except Exception as e:
                logger.debug(f"Failed to resolve base class {base_class}: {e}")

        # 3. Fall back to external stub
        if not callee_path:
            callee_path = f"<external>/{qualified_base}"

        eid = _edge_id(class_name, qualified_base, norm_path, EDGE_TYPE_INHERITS_FROM, repo)
        edges.append(GraphEdge(
            id=eid,
            caller_symbol=class_name,
            callee_symbol=qualified_base,
            caller_path=norm_path,
            callee_path=callee_path,
            edge_type=EDGE_TYPE_INHERITS_FROM,
            repo=repo,
            start_line=start_line,
            end_line=end_line,
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

