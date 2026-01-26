#!/usr/bin/env python3
"""
Tests for scripts/qdrant_client_manager.py - QdrantClient pooling behavior.

These tests are pure unit tests (no network) and validate:
- Client reuse after return
- Pool-full behavior returns a temporary (unpooled) client
- Expired clients are closed and removed
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit


class _DummyQdrantClient:
    def __init__(self, url=None, api_key=None, **kwargs):
        self.url = url
        self.api_key = api_key
        self.closed = False

    def close(self):
        self.closed = True


def test_pool_reuses_client_after_return(monkeypatch):
    qcm = importlib.import_module("scripts.qdrant_client_manager")
    monkeypatch.setattr(qcm, "QdrantClient", _DummyQdrantClient)

    pool = qcm.QdrantConnectionPool(max_size=1, max_lifetime=9999.0)
    c1 = pool.get_client(url="http://example", api_key=None)
    pool.return_client(c1)
    c2 = pool.get_client(url="http://example", api_key=None)

    assert c1 is c2
    stats = pool.get_stats()
    assert stats["pool_size"] == 1
    assert stats["created_count"] == 1
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1


def test_pool_full_returns_temporary_client(monkeypatch):
    qcm = importlib.import_module("scripts.qdrant_client_manager")
    monkeypatch.setattr(qcm, "QdrantClient", _DummyQdrantClient)

    pool = qcm.QdrantConnectionPool(max_size=1, max_lifetime=9999.0)
    pooled = pool.get_client(url="http://example", api_key=None)
    temp = pool.get_client(url="http://example", api_key=None)

    assert temp is not pooled
    # Returning a temporary client should not change pool accounting.
    pool.return_client(temp)
    stats = pool.get_stats()
    assert stats["pool_size"] == 1
    assert stats["created_count"] == 1

    pool.return_client(pooled)
    pooled2 = pool.get_client(url="http://example", api_key=None)
    assert pooled2 is pooled


def test_pool_cleanup_expired_closes_clients(monkeypatch):
    qcm = importlib.import_module("scripts.qdrant_client_manager")
    monkeypatch.setattr(qcm, "QdrantClient", _DummyQdrantClient)

    now = {"t": 1000.0}

    def fake_time():
        return now["t"]

    monkeypatch.setattr(qcm.time, "time", fake_time)

    pool = qcm.QdrantConnectionPool(max_size=1, max_lifetime=10.0)
    c1 = pool.get_client(url="http://example", api_key=None)
    pool.return_client(c1)

    # Advance time past max_lifetime; next get_client triggers cleanup.
    now["t"] = 2000.0
    c2 = pool.get_client(url="http://example", api_key=None)

    assert c1.closed is True
    assert c2 is not c1
