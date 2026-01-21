#!/usr/bin/env python3
"""
Tests for scripts/hybrid/embed.py - cached query embedding helper.

Focus:
- Batch embedding of missing queries in one call
- Cache hits avoid repeated embedding
- One-by-one fallback when batch embed fails
- ASYMMETRIC_EMBEDDING uses query_embed when available
"""

from __future__ import annotations

import importlib
from typing import Iterable, List

import pytest

pytestmark = pytest.mark.unit


class _DummyVec:
    def __init__(self, value: float):
        self._value = float(value)

    def tolist(self) -> List[float]:
        return [self._value]


class _DummyCache:
    def __init__(self):
        self._store = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value):
        self._store[key] = value

    def clear(self):
        self._store.clear()


class _RecordingModel:
    model_name = "stub-model"

    def __init__(self):
        self.embed_calls: list[list[str]] = []
        self.query_embed_calls: list[list[str]] = []

    def embed(self, texts: Iterable[str]):
        items = list(texts)
        self.embed_calls.append(items)
        for t in items:
            yield _DummyVec(len(str(t)))

    def query_embed(self, texts: Iterable[str]):
        items = list(texts)
        self.query_embed_calls.append(items)
        for t in items:
            yield _DummyVec(100 + len(str(t)))


def _load_embed_module(monkeypatch, *, asymmetric: bool):
    monkeypatch.setenv("ASYMMETRIC_EMBEDDING", "1" if asymmetric else "0")
    mod = importlib.import_module("scripts.hybrid.embed")
    return importlib.reload(mod)


def test_embed_queries_cached_batches_and_caches(monkeypatch):
    emb = _load_embed_module(monkeypatch, asymmetric=False)
    cache = _DummyCache()
    monkeypatch.setattr(emb, "get_embedding_cache", lambda: cache)
    monkeypatch.setattr(emb, "UNIFIED_CACHE_AVAILABLE", True)
    emb._EMBED_CACHE = None  # force re-init with our stub cache

    model = _RecordingModel()
    out1 = emb.embed_queries_cached(model, ["alpha", "beta", "gamma"])
    out2 = emb.embed_queries_cached(model, ["alpha", "beta", "gamma"])

    # First call embeds all queries once; second call is cache hit (no new embed calls)
    assert model.embed_calls == [["alpha", "beta", "gamma"]]
    assert out1 == out2


def test_embed_queries_cached_falls_back_to_one_by_one(monkeypatch):
    emb = _load_embed_module(monkeypatch, asymmetric=False)
    cache = _DummyCache()
    monkeypatch.setattr(emb, "get_embedding_cache", lambda: cache)
    monkeypatch.setattr(emb, "UNIFIED_CACHE_AVAILABLE", True)
    emb._EMBED_CACHE = None

    class _FlakyBatchModel:
        model_name = "stub-model"

        def __init__(self):
            self.calls: list[list[str]] = []

        def embed(self, texts: Iterable[str]):
            items = list(texts)
            self.calls.append(items)
            if len(items) > 1:
                raise RuntimeError("batch embed not supported")
            for t in items:
                yield _DummyVec(len(str(t)))

    model = _FlakyBatchModel()
    out = emb.embed_queries_cached(model, ["a", "bb"])

    # One failing batch attempt + one call per query for fallback
    assert model.calls[0] == ["a", "bb"]
    assert ["a"] in model.calls
    assert ["bb"] in model.calls
    assert out == [[1.0], [2.0]]


def test_embed_queries_cached_uses_query_embed_when_asymmetric(monkeypatch):
    emb = _load_embed_module(monkeypatch, asymmetric=True)
    cache = _DummyCache()
    monkeypatch.setattr(emb, "get_embedding_cache", lambda: cache)
    monkeypatch.setattr(emb, "UNIFIED_CACHE_AVAILABLE", True)
    emb._EMBED_CACHE = None

    model = _RecordingModel()
    out = emb.embed_queries_cached(model, ["x", "yy"])

    assert model.query_embed_calls == [["x", "yy"]]
    assert model.embed_calls == []
    assert out == [[101.0], [102.0]]


def test_embed_queries_cached_rejects_empty_queries(monkeypatch):
    emb = _load_embed_module(monkeypatch, asymmetric=False)
    cache = _DummyCache()
    monkeypatch.setattr(emb, "get_embedding_cache", lambda: cache)
    monkeypatch.setattr(emb, "UNIFIED_CACHE_AVAILABLE", True)
    emb._EMBED_CACHE = None

    model = _RecordingModel()
    with pytest.raises(ValueError):
        emb.embed_queries_cached(model, ["", "  "])
