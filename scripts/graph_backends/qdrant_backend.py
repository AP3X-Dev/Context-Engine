# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Qdrant graph backend implementation.

Wraps the existing graph_edges.py functionality in the GraphBackend interface.
This is the default backend - flat-file storage using Qdrant collections.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .base import GraphBackend, GraphEdge

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

# Re-use constants from graph_edges
GRAPH_COLLECTION_SUFFIX = "_graph"
EDGE_TYPE_CALLS = "calls"
EDGE_TYPE_IMPORTS = "imports"


class QdrantGraphBackend(GraphBackend):
    """Qdrant-based graph storage backend.

    Uses Qdrant collections with payload-only points (no vectors)
    to store graph edges with indexed lookups.
    """

    def __init__(self):
        """Initialize the Qdrant graph backend."""
        self._client: Optional["QdrantClient"] = None

    @property
    def backend_type(self) -> str:
        return "qdrant"

    def _get_client(self) -> "QdrantClient":
        """Get or create Qdrant client (lazy singleton per instance)."""
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(
                url=os.environ.get("QDRANT_URL", "http://qdrant:6333"),
                api_key=os.environ.get("QDRANT_API_KEY"),
                timeout=float(os.environ.get("QDRANT_TIMEOUT", "60") or 60),
            )
        return self._client

    def close(self) -> None:
        """Close the Qdrant client connection."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
    
    def ensure_graph_store(self, base_collection: str) -> Optional[str]:
        """Ensure graph collection exists in Qdrant."""
        from scripts.ingest.graph_edges import ensure_graph_collection
        return ensure_graph_collection(self._get_client(), base_collection)
    
    def upsert_edges(
        self,
        graph_store: str,
        edges: List[GraphEdge],
        batch_size: int = 100,
    ) -> int:
        """Upsert edges to Qdrant graph collection."""
        from scripts.ingest.graph_edges import upsert_edges as qdrant_upsert
        
        # Convert GraphEdge objects to dict format expected by graph_edges
        edge_dicts = [
            {"id": e.id, "payload": e.to_dict()}
            for e in edges
        ]
        return qdrant_upsert(self._get_client(), graph_store, edge_dicts, batch_size)
    
    def delete_edges_by_path(
        self,
        graph_store: str,
        path: str,
        repo: Optional[str] = None,
    ) -> int:
        """Delete edges by path from Qdrant."""
        from scripts.ingest.graph_edges import delete_edges_by_path as qdrant_delete
        return qdrant_delete(self._get_client(), graph_store, path, repo)
    
    def get_callers(
        self,
        graph_store: str,
        symbol: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find callers using Qdrant indexed lookup."""
        from scripts.ingest.graph_edges import get_callers as qdrant_get_callers
        return qdrant_get_callers(self._get_client(), graph_store, symbol, repo, limit)
    
    def get_callees(
        self,
        graph_store: str,
        symbol: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find callees using Qdrant indexed lookup."""
        from scripts.ingest.graph_edges import get_callees as qdrant_get_callees
        return qdrant_get_callees(self._get_client(), graph_store, symbol, repo, limit)
    
    def get_importers(
        self,
        graph_store: str,
        module: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find importers using Qdrant indexed lookup."""
        from scripts.ingest.graph_edges import get_importers as qdrant_get_importers
        return qdrant_get_importers(self._get_client(), graph_store, module, repo, limit)

    def resolve_symbol(
        self,
        graph_store: str,
        symbol_name: str,
        repo: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve a symbol name to its definition file path via Qdrant.
        
        Queries the main collection (not graph store) for chunks with
        matching symbol_path metadata.
        """
        # Extract base collection name from graph store
        collection = graph_store
        if collection.endswith(GRAPH_COLLECTION_SUFFIX):
            collection = collection[:-len(GRAPH_COLLECTION_SUFFIX)]

        try:
            from qdrant_client import models as qmodels

            must = [
                qmodels.FieldCondition(
                    key="symbol_path",
                    match=qmodels.MatchValue(value=symbol_name),
                )
            ]
            if repo:
                must.append(
                    qmodels.FieldCondition(
                        key="repo",
                        match=qmodels.MatchValue(value=repo),
                    )
                )

            result, _ = self._get_client().scroll(
                collection_name=collection,
                scroll_filter=qmodels.Filter(must=must),
                limit=1,
                with_payload=["path"],
                with_vectors=False,
            )
            if result:
                return result[0].payload.get("path")
        except Exception as e:
            logger.debug(f"Qdrant symbol lookup failed: {e}")
        return None

    def resolve_import(
        self,
        graph_store: str,
        import_name: str,
        repo: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve an import to its source file path via Qdrant.
        
        Converts dotted import names to file path patterns and searches
        the main collection.
        """
        # Extract base collection name from graph store
        collection = graph_store
        if collection.endswith(GRAPH_COLLECTION_SUFFIX):
            collection = collection[:-len(GRAPH_COLLECTION_SUFFIX)]

        # Convert dotted import to file path suffix
        module_path = import_name.replace(".", "/")

        try:
            from qdrant_client import models as qmodels

            # Search for files ending with the module path
            must = [
                qmodels.FieldCondition(
                    key="path",
                    match=qmodels.MatchText(text=f"/{module_path}.py"),
                )
            ]
            if repo:
                must.append(
                    qmodels.FieldCondition(
                        key="repo",
                        match=qmodels.MatchValue(value=repo),
                    )
                )

            result, _ = self._get_client().scroll(
                collection_name=collection,
                scroll_filter=qmodels.Filter(must=must),
                limit=1,
                with_payload=["path"],
                with_vectors=False,
            )
            if result:
                return result[0].payload.get("path")
        except Exception as e:
            logger.debug(f"Qdrant import lookup failed: {e}")
        return None

