"""Cache for file discovery operations to reduce filesystem overhead.

Caches glob pattern matching results with TTL and directory mtime validation.
Useful for repeated directory scans during watch mode or incremental indexing.

Usage:
    cache = FileDiscoveryCache(max_entries=100, ttl_seconds=300)
    
    # Get files matching patterns (cached)
    files = cache.get_files(
        directory=Path("/project"),
        patterns=["**/*.py", "**/*.js"],
        exclude_patterns=["**/node_modules/**"]
    )
    
    # Invalidate when directory changes
    cache.invalidate_directory(Path("/project/src"))
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class FileDiscoveryCache:
    """LRU cache for file discovery operations with TTL and mtime validation."""

    def __init__(self, max_entries: int = 100, ttl_seconds: int = 300):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, Tuple[List[Path], float, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._invalidations = 0

    def get_files(
        self,
        directory: Path,
        patterns: List[str],
        exclude_patterns: Optional[List[str]] = None,
    ) -> List[Path]:
        """Get files matching patterns with caching."""
        cache_key = self._make_cache_key(directory, patterns, exclude_patterns)

        cached_result = self._get_from_cache(cache_key, directory)
        if cached_result is not None:
            self._hits += 1
            return cached_result

        self._misses += 1
        files = self._discover_files(directory, patterns, exclude_patterns)
        self._store_in_cache(cache_key, files, directory)
        return files

    def invalidate_directory(self, directory: Path) -> int:
        """Invalidate all cache entries for a directory. Returns count removed."""
        dir_str = str(directory)
        keys_to_remove = [key for key in self._cache if key.startswith(f"{dir_str}|")]

        for key in keys_to_remove:
            del self._cache[key]
            self._invalidations += 1

        return len(keys_to_remove)

    def clear(self) -> None:
        """Clear all cache entries."""
        count = len(self._cache)
        self._cache.clear()
        self._evictions += count

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "invalidations": self._invalidations,
            "cache_size": len(self._cache),
            "max_entries": self.max_entries,
            "ttl_seconds": self.ttl_seconds,
            "hit_rate_percent": round(hit_rate, 2),
        }

    def _make_cache_key(
        self, directory: Path, patterns: List[str], exclude_patterns: Optional[List[str]]
    ) -> str:
        """Create a cache key from directory and patterns."""
        patterns_str = "|".join(sorted(patterns))
        exclude_str = "|".join(sorted(exclude_patterns or []))
        return f"{directory}|{patterns_str}|{exclude_str}"

    def _get_from_cache(self, cache_key: str, directory: Path) -> Optional[List[Path]]:
        """Get entry from cache if valid (TTL and mtime)."""
        if cache_key not in self._cache:
            return None

        files, timestamp, cached_mtime = self._cache[cache_key]
        current_time = time.time()

        if current_time - timestamp > self.ttl_seconds:
            del self._cache[cache_key]
            self._evictions += 1
            return None

        try:
            current_mtime = directory.stat().st_mtime
            if current_mtime > cached_mtime:
                del self._cache[cache_key]
                self._invalidations += 1
                return None
        except OSError:
            del self._cache[cache_key]
            self._invalidations += 1
            return None

        self._cache.move_to_end(cache_key)
        return files

    def _store_in_cache(self, cache_key: str, files: List[Path], directory: Path) -> None:
        """Store files in cache with mtime tracking."""
        try:
            directory_mtime = directory.stat().st_mtime
        except OSError:
            return

        while len(self._cache) >= self.max_entries:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._evictions += 1

        self._cache[cache_key] = (files, time.time(), directory_mtime)

    def _discover_files(
        self, directory: Path, patterns: List[str], exclude_patterns: Optional[List[str]]
    ) -> List[Path]:
        """Perform actual file discovery via glob."""
        try:
            files: List[Path] = []
            for pattern in patterns:
                files.extend(directory.glob(pattern))

            seen = set()
            unique_files = []
            for file_path in files:
                if file_path not in seen:
                    seen.add(file_path)
                    unique_files.append(file_path)
            files = unique_files

            if exclude_patterns:
                filtered_files = []
                for file_path in files:
                    try:
                        rel_path = file_path.relative_to(directory)
                    except ValueError:
                        rel_path = file_path
                    excluded = any(
                        fnmatch(str(rel_path), ep) or fnmatch(str(file_path), ep)
                        for ep in exclude_patterns
                    )
                    if not excluded:
                        filtered_files.append(file_path)
                files = filtered_files

            return files

        except Exception as e:
            logger.debug(f"Failed to discover files in {directory}: {e}")
            return []


_default_cache: Optional[FileDiscoveryCache] = None


def get_default_file_discovery_cache() -> FileDiscoveryCache:
    """Get or create the default global file discovery cache instance."""
    global _default_cache
    if _default_cache is None:
        _default_cache = FileDiscoveryCache()
    return _default_cache


__all__ = [
    "FileDiscoveryCache",
    "get_default_file_discovery_cache",
]
