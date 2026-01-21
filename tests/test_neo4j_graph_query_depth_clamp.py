#!/usr/bin/env python3
"""
Tests for scripts/mcp_impl/neo4j_graph.py - defensive depth clamping.

These are unit tests that avoid requiring a real Neo4j instance by stubbing
the backend + query functions.
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit


class _DummyBackend:
    backend_type = "neo4j"


@pytest.mark.anyio
async def test_neo4j_graph_query_clamps_depth_max(monkeypatch):
    mod = importlib.import_module("scripts.mcp_impl.neo4j_graph")
    monkeypatch.setattr(mod, "_get_neo4j_backend", lambda: _DummyBackend())

    captured = {}

    async def fake_transitive(backend, symbol, depth, repo, limit, include_paths, collection):
        captured["depth"] = depth
        return []

    monkeypatch.setattr(mod, "_query_transitive_callers_async", fake_transitive)

    res = await mod._neo4j_graph_query_impl(  # type: ignore[attr-defined]
        query_type="transitive_callers",
        symbol="X",
        depth=999,
        limit=10,
        collection="codebase",
    )

    assert res["ok"] is True
    assert res["query"]["depth"] == 10
    assert captured["depth"] == 10


@pytest.mark.anyio
async def test_neo4j_graph_query_clamps_depth_min(monkeypatch):
    mod = importlib.import_module("scripts.mcp_impl.neo4j_graph")
    monkeypatch.setattr(mod, "_get_neo4j_backend", lambda: _DummyBackend())

    captured = {}

    async def fake_transitive(backend, symbol, depth, repo, limit, include_paths, collection):
        captured["depth"] = depth
        return []

    monkeypatch.setattr(mod, "_query_transitive_callees_async", fake_transitive)

    res = await mod._neo4j_graph_query_impl(  # type: ignore[attr-defined]
        query_type="transitive_callees",
        symbol="X",
        depth=0,
        limit=10,
        collection="codebase",
    )

    assert res["ok"] is True
    assert res["query"]["depth"] == 1
    assert captured["depth"] == 1
