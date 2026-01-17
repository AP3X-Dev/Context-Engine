#!/usr/bin/env python3
"""
Tests for scripts/ingest/qdrant.py - upsert_points retry behavior.

These tests are unit-level and use a fake client to validate:
- Retries with backoff on transient failures
- Sub-batch fallback after exhausting retries
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit


class _FlakyUpsertClient:
    def __init__(self, failures: int):
        self._failures = int(failures)
        self.calls: list[dict] = []

    def upsert(self, *, collection_name, points, wait=True):
        pts = list(points)
        self.calls.append({"collection": collection_name, "n": len(pts)})
        if self._failures > 0:
            self._failures -= 1
            raise RuntimeError("simulated upsert failure")


def test_upsert_points_retries_then_succeeds(monkeypatch):
    iq = importlib.import_module("scripts.ingest.qdrant")

    monkeypatch.setenv("INDEX_UPSERT_BATCH", "16")
    monkeypatch.setenv("INDEX_UPSERT_RETRIES", "3")
    monkeypatch.setenv("INDEX_UPSERT_BACKOFF", "0.01")

    sleeps: list[float] = []
    monkeypatch.setattr(iq.time, "sleep", lambda s: sleeps.append(float(s)))

    client = _FlakyUpsertClient(failures=2)
    iq.upsert_points(client, "codebase", [object(), object()])

    # 2 failures + 1 success
    assert len(client.calls) == 3
    assert sleeps == [pytest.approx(0.01), pytest.approx(0.02)]


def test_upsert_points_subbatches_after_exhausting_retries(monkeypatch):
    iq = importlib.import_module("scripts.ingest.qdrant")

    monkeypatch.setenv("INDEX_UPSERT_BATCH", "4")
    monkeypatch.setenv("INDEX_UPSERT_RETRIES", "1")  # fail fast -> sub-batch fallback
    monkeypatch.setenv("INDEX_UPSERT_BACKOFF", "0.01")

    # Should not sleep when retries are exhausted immediately.
    monkeypatch.setattr(
        iq.time,
        "sleep",
        lambda _s: (_ for _ in ()).throw(AssertionError("unexpected sleep")),
    )

    client = _FlakyUpsertClient(failures=999)
    iq.upsert_points(client, "codebase", [object(), object(), object(), object()])

    # 1 full-batch attempt + 4 single-point sub-batches (bsz=4 -> sub_size=1)
    assert [c["n"] for c in client.calls] == [4, 1, 1, 1, 1]
