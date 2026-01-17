# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Graph backend interface - imports from core when available.

This file provides a thin wrapper that imports from Context-Engine core
(scripts.graph_backends.base) when available, with a complete fallback
for standalone plugin use.
"""
from __future__ import annotations

# Try to import from Context-Engine core first
try:
    from scripts.graph_backends.base import (
        GRAPH_BACKEND_API_VERSION,
        EdgeType,
        GraphEdge,
        GraphQueryResult,
        GraphBackend,
    )
except ImportError:
    # Fallback: complete standalone definitions for plugin independence
    from abc import ABC, abstractmethod
    from dataclasses import dataclass, field
    from enum import Enum
    from typing import Any, Dict, List, Optional

    GRAPH_BACKEND_API_VERSION = "1.0.0"

    class EdgeType(str, Enum):
        """Edge types for graph relationships."""
        CALLS = "calls"
        IMPORTS = "imports"

        def __str__(self) -> str:
            return self.value

    @dataclass
    class GraphEdge:
        """Represents a graph edge (call or import relationship)."""
        id: str
        caller_symbol: str
        callee_symbol: str
        caller_path: str
        edge_type: str  # "calls" or "imports"
        repo: str
        start_line: Optional[int] = None
        end_line: Optional[int] = None
        language: Optional[str] = None
        caller_point_id: Optional[str] = None
        callee_path: Optional[str] = None  # Resolved path where callee is defined

        def to_dict(self) -> Dict[str, Any]:
            """Convert to dictionary for serialization.

            Note: Excludes 'id' (used for upsert keying) and includes
            'callee_path' only when resolved.
            """
            d = {
                "caller_symbol": self.caller_symbol,
                "callee_symbol": self.callee_symbol,
                "caller_path": self.caller_path,
                "edge_type": self.edge_type,
                "repo": self.repo,
            }
            if self.start_line is not None:
                d["start_line"] = self.start_line
            if self.end_line is not None:
                d["end_line"] = self.end_line
            if self.language:
                d["language"] = self.language
            if self.callee_path:
                d["callee_path"] = self.callee_path
            if self.caller_point_id:
                d["caller_point_id"] = self.caller_point_id
            return d

    @dataclass
    class GraphQueryResult:
        """Result from a graph query operation."""
        edges: List[Dict[str, Any]] = field(default_factory=list)
        total: int = 0
        backend: str = ""
        query_time_ms: float = 0.0

    class GraphBackend(ABC):
        """Abstract base class for graph storage backends.

        Implementations must support:
        - Storing call and import edges
        - Querying callers, callees, and importers
        - Deleting edges by path
        - Collection/database initialization
        """

        @property
        @abstractmethod
        def backend_type(self) -> str:
            """Return the backend type identifier (e.g., 'qdrant', 'neo4j')."""
            pass

        @abstractmethod
        def ensure_graph_store(self, base_collection: str) -> Optional[str]:
            """Ensure the graph store exists for a collection."""
            pass

        @abstractmethod
        def upsert_edges(
            self,
            graph_store: str,
            edges: List[GraphEdge],
            batch_size: int = 100,
        ) -> int:
            """Upsert edges to the graph store."""
            pass

        @abstractmethod
        def delete_edges_by_path(
            self,
            graph_store: str,
            path: str,
            repo: Optional[str] = None,
        ) -> int:
            """Delete all edges from a file path."""
            pass

        @abstractmethod
        def get_callers(
            self,
            graph_store: str,
            symbol: str,
            repo: Optional[str] = None,
            limit: int = 100,
        ) -> List[Dict[str, Any]]:
            """Find all callers of a symbol."""
            pass

        @abstractmethod
        def get_callees(
            self,
            graph_store: str,
            symbol: str,
            repo: Optional[str] = None,
            limit: int = 100,
        ) -> List[Dict[str, Any]]:
            """Find all symbols called by a symbol."""
            pass

        @abstractmethod
        def get_importers(
            self,
            graph_store: str,
            module: str,
            repo: Optional[str] = None,
            limit: int = 100,
        ) -> List[Dict[str, Any]]:
            """Find all files that import a module."""
            pass

        def resolve_symbol(
            self,
            graph_store: str,
            symbol_name: str,
            repo: Optional[str] = None,
        ) -> Optional[str]:
            """Resolve a symbol name to its definition file path."""
            return None

        def resolve_import(
            self,
            graph_store: str,
            import_name: str,
            repo: Optional[str] = None,
        ) -> Optional[str]:
            """Resolve an import to its source file path."""
            return None

        def close(self) -> None:
            """Close any open connections and release resources."""
            pass

