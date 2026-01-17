#!/usr/bin/env python3
"""
Tests for scripts/semantic_expansion.py - cache TTL expiry behavior.

This is a small integration test to ensure the semantic expansion cache
honors SEMANTIC_EXPANSION_CACHE_TTL without relying on real embeddings/Qdrant.
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit


def test_semantic_expansion_cache_ttl_expires(monkeypatch):
    # Configure a tiny TTL and ensure module reload picks it up.
    monkeypatch.setenv("SEMANTIC_EXPANSION_CACHE_SIZE", "10")
    monkeypatch.setenv("SEMANTIC_EXPANSION_CACHE_TTL", "1")

    cache_manager = importlib.import_module("scripts.cache_manager")

    now = {"t": 1000.0}

    def fake_time():
        return now["t"]

    # UnifiedCache/CacheEntry use scripts.cache_manager.time.time()
    monkeypatch.setattr(cache_manager.time, "time", fake_time)

    sem = importlib.import_module("scripts.semantic_expansion")
    sem = importlib.reload(sem)

    # Validate cache behavior via internal helpers (no Qdrant/embedding needed).
    key = sem._get_expansion_cache_key(["hello"])  # type: ignore[attr-defined]
    sem._cache_expansion(key, ["hi"])  # type: ignore[attr-defined]
    assert sem._get_cached_expansion(key) == ["hi"]  # type: ignore[attr-defined]

    now["t"] = 1002.0  # > 1s TTL
    assert sem._get_cached_expansion(key) is None  # type: ignore[attr-defined]
