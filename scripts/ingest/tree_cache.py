"""LRU cache for parsed syntax trees with automatic invalidation.

Provides significant performance improvement by caching parsed ASTs
and validating freshness via file mtime/size. Thread-safe for concurrent access.

Usage:
    cache = TreeCache(max_entries=1000)
    
    # Try to get cached tree
    tree = cache.get(file_path)
    if tree is None:
        tree = parser.parse(content)
        cache.put(file_path, tree)
    
    # Get statistics
    stats = cache.get_stats()
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)


class TreeCacheEntry:
    """Represents a cached syntax tree with metadata."""
    
    __slots__ = ("tree", "file_path", "mtime", "size", "access_time", "hit_count")

    def __init__(self, tree: Any, file_path: Path, mtime: float, size: int):
        self.tree = tree
        self.file_path = file_path
        self.mtime = mtime
        self.size = size
        self.access_time = time.time()
        self.hit_count = 0

    def is_valid(self) -> bool:
        """Check if cache entry is still valid based on file mtime and size."""
        try:
            stat = self.file_path.stat()
            return stat.st_mtime == self.mtime and stat.st_size == self.size
        except (OSError, FileNotFoundError):
            return False

    def touch(self) -> None:
        """Update access time and increment hit count."""
        self.access_time = time.time()
        self.hit_count += 1


class TreeCache:
    """LRU cache for parsed syntax trees with automatic invalidation."""

    def __init__(self, max_entries: int = 1000, max_memory_mb: int = 500):
        self.max_entries = max_entries
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self._cache: OrderedDict[str, TreeCacheEntry] = OrderedDict()
        self._lock = RLock()

        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._invalidations = 0

    def get(self, file_path: Path) -> Optional[Any]:
        """Get cached syntax tree for file, returning None if not cached or stale."""
        cache_key = str(file_path.resolve())

        with self._lock:
            if cache_key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[cache_key]

            if not entry.is_valid():
                del self._cache[cache_key]
                self._invalidations += 1
                self._misses += 1
                return None

            self._cache.move_to_end(cache_key)
            entry.touch()
            self._hits += 1
            return entry.tree

    def get_for_comparison(self, file_path: Path) -> Optional[Any]:
        """Get cached tree even if stale - useful for incremental parsing comparison."""
        cache_key = str(file_path.resolve())

        with self._lock:
            if cache_key not in self._cache:
                self._misses += 1
                return None
            return self._cache[cache_key].tree

    def put(self, file_path: Path, tree: Any) -> None:
        """Cache a parsed syntax tree."""
        if tree is None:
            return

        cache_key = str(file_path.resolve())

        try:
            stat = file_path.stat()
            mtime = stat.st_mtime
            size = stat.st_size
        except (OSError, FileNotFoundError):
            return

        with self._lock:
            entry = TreeCacheEntry(tree, file_path, mtime, size)

            if cache_key in self._cache:
                del self._cache[cache_key]

            self._cache[cache_key] = entry
            self._enforce_limits()

    def invalidate(self, file_path: Path) -> bool:
        """Invalidate cached entry for a file. Returns True if found and removed."""
        cache_key = str(file_path.resolve())

        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                self._invalidations += 1
                return True
            return False

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    def _enforce_limits(self) -> None:
        """Enforce cache size and memory limits using LRU eviction."""
        while len(self._cache) > self.max_entries:
            self._evict_lru()

        estimated_memory = sum(entry.size for entry in self._cache.values())
        while estimated_memory > self.max_memory_bytes and self._cache:
            evicted_entry = self._evict_lru()
            if evicted_entry:
                estimated_memory -= evicted_entry.size

    def _evict_lru(self) -> Optional[TreeCacheEntry]:
        """Evict least recently used entry."""
        if not self._cache:
            return None
        _, entry = self._cache.popitem(last=False)
        self._evictions += 1
        return entry

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0

            return {
                "entries": len(self._cache),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_percent": round(hit_rate, 2),
                "evictions": self._evictions,
                "invalidations": self._invalidations,
                "total_requests": total_requests,
                "estimated_memory_mb": round(
                    sum(entry.size for entry in self._cache.values()) / 1024 / 1024, 2
                ),
                "max_memory_mb": round(self.max_memory_bytes / 1024 / 1024, 2),
            }

    def cleanup_stale_entries(self) -> int:
        """Remove all stale entries. Returns number removed."""
        stale_keys = []

        with self._lock:
            for cache_key, entry in self._cache.items():
                if not entry.is_valid():
                    stale_keys.append(cache_key)

            for key in stale_keys:
                del self._cache[key]
                self._invalidations += 1

        return len(stale_keys)

    def get_cache_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Get detailed information about a cached entry."""
        cache_key = str(file_path.resolve())

        with self._lock:
            if cache_key not in self._cache:
                return None

            entry = self._cache[cache_key]
            return {
                "file_path": str(entry.file_path),
                "cached_mtime": entry.mtime,
                "cached_size": entry.size,
                "access_time": entry.access_time,
                "hit_count": entry.hit_count,
                "is_valid": entry.is_valid(),
                "age_seconds": time.time() - entry.access_time,
            }


_default_cache: Optional[TreeCache] = None


def get_default_cache() -> TreeCache:
    """Get or create the default global tree cache instance."""
    global _default_cache
    if _default_cache is None:
        _default_cache = TreeCache()
    return _default_cache


def configure_default_cache(max_entries: int = 1000, max_memory_mb: int = 500) -> TreeCache:
    """Configure the default global tree cache."""
    global _default_cache
    _default_cache = TreeCache(max_entries, max_memory_mb)
    return _default_cache


__all__ = [
    "TreeCache",
    "TreeCacheEntry",
    "get_default_cache",
    "configure_default_cache",
]
