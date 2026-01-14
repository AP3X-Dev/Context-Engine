# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Abstract base class for graph backends.

Defines the interface that all graph storage backends must implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    callee_path: Optional[str] = None  # Resolved path of the callee symbol

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
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
        """Ensure the graph store exists for a collection.
        
        Args:
            base_collection: Base collection name (graph store may be derived)
            
        Returns:
            Graph store identifier, or None on failure
        """
        pass
    
    @abstractmethod
    def upsert_edges(
        self,
        graph_store: str,
        edges: List[GraphEdge],
        batch_size: int = 100,
    ) -> int:
        """Upsert edges to the graph store.
        
        Args:
            graph_store: Graph store identifier
            edges: List of edges to upsert
            batch_size: Batch size for bulk operations
            
        Returns:
            Number of edges upserted
        """
        pass
    
    @abstractmethod
    def delete_edges_by_path(
        self,
        graph_store: str,
        path: str,
        repo: Optional[str] = None,
    ) -> int:
        """Delete all edges from a file path.
        
        Args:
            graph_store: Graph store identifier
            path: File path to delete edges for
            repo: Optional repo filter
            
        Returns:
            1 if successful, 0 otherwise
        """
        pass
    
    @abstractmethod
    def get_callers(
        self,
        graph_store: str,
        symbol: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find all callers of a symbol.
        
        Args:
            graph_store: Graph store identifier
            symbol: Symbol to find callers for
            repo: Optional repo filter
            limit: Maximum results
            
        Returns:
            List of edge payloads
        """
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

