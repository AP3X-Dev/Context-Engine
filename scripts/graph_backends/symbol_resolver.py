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
import time
from typing import Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import GraphBackend

logger = logging.getLogger(__name__)

# Cache configuration (environment-configurable)
CACHE_MAX_SIZE = int(os.environ.get("SYMBOL_CACHE_MAX_SIZE", "10000") or 10000)
CACHE_TTL_SECONDS = int(os.environ.get("SYMBOL_CACHE_TTL_SECONDS", "300") or 300)  # 5 min default


class SymbolResolver:
    """Resolves symbol names to their definition file paths.

    Uses the graph backend abstraction layer. Both Qdrant and Neo4j
    backends implement resolve_symbol() and resolve_import() directly.

    Features:
    - LRU-style eviction when cache exceeds max size
    - TTL-based expiration for cache entries
    - Configurable via SYMBOL_CACHE_MAX_SIZE and SYMBOL_CACHE_TTL_SECONDS
    """

    def __init__(self, collection: str, max_size: int = CACHE_MAX_SIZE, ttl: int = CACHE_TTL_SECONDS):
        """Initialize the symbol resolver.

        Args:
            collection: Collection name
            max_size: Maximum cache entries before eviction
            ttl: Time-to-live in seconds for cache entries
        """
        self.collection = collection
        self._backend: Optional["GraphBackend"] = None
        # Cache stores (value, timestamp) tuples
        self._cache: Dict[str, Tuple[Optional[str], float]] = {}
        self._max_size = max_size
        self._ttl = ttl

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

    def _cache_get(self, key: str) -> Tuple[bool, Optional[str]]:
        """Get from cache with TTL check.

        Returns:
            (hit, value) - hit is True if valid cache entry exists
        """
        if key not in self._cache:
            return False, None

        value, timestamp = self._cache[key]
        if time.time() - timestamp > self._ttl:
            # Entry expired
            del self._cache[key]
            return False, None

        return True, value

    def _cache_set(self, key: str, value: Optional[str]) -> None:
        """Set cache entry with timestamp, evicting oldest if needed."""
        # Evict oldest entries if at max size
        if len(self._cache) >= self._max_size:
            # Remove oldest 10% of entries
            evict_count = max(1, self._max_size // 10)
            sorted_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k][1]  # Sort by timestamp
            )
            for k in sorted_keys[:evict_count]:
                del self._cache[k]

        self._cache[key] = (value, time.time())

    def clear_cache(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    def resolve_symbol(self, symbol_name: str, repo: Optional[str] = None) -> Optional[str]:
        """Resolve a symbol name to its definition file path.

        Args:
            symbol_name: The symbol to resolve (e.g., "run_hybrid_search")
            repo: Optional repo filter

        Returns:
            The file path where the symbol is defined, or None if not found.
        """
        cache_key = f"sym:{repo or '*'}:{symbol_name}"
        hit, cached_value = self._cache_get(cache_key)
        if hit:
            return cached_value

        backend = self._get_backend()
        if not backend:
            return None

        try:
            path = backend.resolve_symbol(self.collection, symbol_name, repo)
            self._cache_set(cache_key, path)
            return path
        except Exception as e:
            logger.debug(f"Backend symbol lookup failed: {e}")
            return None

    def resolve_import(self, import_name: str, repo: Optional[str] = None, language: Optional[str] = None) -> Optional[str]:
        """Resolve an import to its source file.

        Args:
            import_name: The imported module name
            repo: Optional repo filter
            language: Programming language for extension detection

        Returns:
            The file path of the module, or None if external/not found.
        """
        cache_key = f"imp:{repo or '*'}:{language or '*'}:{import_name}"
        hit, cached_value = self._cache_get(cache_key)
        if hit:
            return cached_value

        backend = self._get_backend()
        if not backend:
            return None

        try:
            path = backend.resolve_import(self.collection, import_name, repo, language)
            self._cache_set(cache_key, path)
            return path
        except Exception as e:
            logger.debug(f"Backend import lookup failed: {e}")
            return None


# Singleton resolver per collection
_RESOLVERS: Dict[str, SymbolResolver] = {}


def get_symbol_resolver(collection: str) -> SymbolResolver:
    """Get or create a symbol resolver for a collection."""
    if collection not in _RESOLVERS:
        _RESOLVERS[collection] = SymbolResolver(collection)
    return _RESOLVERS[collection]


def clear_all_resolver_caches() -> None:
    """Clear caches in all resolvers (useful for testing)."""
    for resolver in _RESOLVERS.values():
        resolver.clear_cache()

