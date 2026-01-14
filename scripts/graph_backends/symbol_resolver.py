# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Symbol resolver for cross-file and cross-repo edge linking.

Resolves callee symbols to their actual file paths by querying the
configured graph backend (Qdrant or Neo4j) via the abstraction layer.

This enables linking imports like 'from scripts.hybrid_search import run_hybrid_search'
to the actual file path where run_hybrid_search is defined.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import QdrantClient
    from .base import GraphBackend

logger = logging.getLogger(__name__)


class SymbolResolver:
    """Resolves symbol names to their definition file paths.

    Uses the graph backend abstraction layer - no direct Neo4j/Qdrant access.
    """

    def __init__(self, collection: str, qdrant_client: Optional["QdrantClient"] = None):
        self.collection = collection
        self._qdrant = qdrant_client
        self._backend: Optional["GraphBackend"] = None
        self._cache: Dict[str, Optional[str]] = {}

    def _get_backend(self) -> Optional["GraphBackend"]:
        """Get the graph backend (lazy-loaded)."""
        if self._backend is not None:
            return self._backend
        try:
            from . import get_graph_backend
            self._backend = get_graph_backend()
            return self._backend
        except Exception as e:
            logger.debug(f"Graph backend not available: {e}")
            return None

    def resolve_symbol(self, symbol_name: str, repo: Optional[str] = None) -> Optional[str]:
        """Resolve a symbol name to its definition file path.

        Args:
            symbol_name: The symbol to resolve (e.g., "run_hybrid_search")
            repo: Optional repo filter

        Returns:
            The file path where the symbol is defined, or None if not found.
        """
        cache_key = f"{repo or '*'}:{symbol_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Try graph backend first
        path = self._resolve_via_backend(symbol_name, repo)

        # Fall back to Qdrant scroll if backend doesn't support resolution
        if not path and self._qdrant:
            path = self._resolve_from_qdrant(symbol_name, repo)

        self._cache[cache_key] = path
        return path

    def _resolve_via_backend(self, symbol_name: str, repo: Optional[str]) -> Optional[str]:
        """Resolve via the graph backend abstraction."""
        backend = self._get_backend()
        if not backend:
            return None

        try:
            return backend.resolve_symbol(self.collection, symbol_name, repo)
        except Exception as e:
            logger.debug(f"Backend symbol lookup failed: {e}")
            return None

    def _resolve_from_qdrant(self, symbol_name: str, repo: Optional[str]) -> Optional[str]:
        """Fallback: query Qdrant payload for symbol definition."""
        if not self._qdrant:
            return None

        try:
            from qdrant_client import models as qmodels

            # Search for chunks with matching symbol_path
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

            result, _ = self._qdrant.scroll(
                collection_name=self.collection,
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

    def resolve_import(self, import_name: str, repo: Optional[str] = None) -> Optional[str]:
        """Resolve an import to its source file.

        Args:
            import_name: The imported module name
            repo: Optional repo filter

        Returns:
            The file path of the module, or None if external/not found.
        """
        backend = self._get_backend()
        if not backend:
            return None

        try:
            return backend.resolve_import(self.collection, import_name, repo)
        except Exception as e:
            logger.debug(f"Backend import lookup failed: {e}")
            return None


# Singleton resolver per collection
_RESOLVERS: Dict[str, SymbolResolver] = {}


def get_symbol_resolver(
    collection: str,
    qdrant_client: Optional["QdrantClient"] = None,
) -> SymbolResolver:
    """Get or create a symbol resolver for a collection."""
    if collection not in _RESOLVERS:
        _RESOLVERS[collection] = SymbolResolver(collection, qdrant_client)
    return _RESOLVERS[collection]

