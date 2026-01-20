#!/usr/bin/env python3
"""
Tests for scripts/rerank_tools/events.py - training event logging.

These tests validate:
- Events are written as NDJSON to disk
- Cleanup removes old event files
- Concurrent writers do not corrupt output
"""

from __future__ import annotations

import importlib
import json
import os
import threading

import pytest

pytestmark = pytest.mark.unit


def _load_events_module(monkeypatch, tmp_path):
    monkeypatch.setenv("RERANK_EVENTS_DIR", str(tmp_path))
    monkeypatch.setenv("RERANK_EVENTS_ENABLED", "1")
    monkeypatch.setenv("RERANK_EVENTS_SAMPLE_RATE", "1.0")
    monkeypatch.setenv("RERANK_EVENTS_RETENTION_DAYS", "0")
    mod = importlib.import_module("scripts.rerank_tools.events")
    return importlib.reload(mod)


def _candidate(path: str):
    return {"path": path, "symbol": "", "start_line": 1, "end_line": 2, "code": "x"}


def test_log_training_event_writes_ndjson(monkeypatch, tmp_path):
    events = _load_events_module(monkeypatch, tmp_path)
    monkeypatch.setattr(events, "_get_hour_suffix", lambda: "2000010101")

    ok = events.log_training_event(
        query="q",
        candidates=[_candidate("/work/a.py")],
        initial_scores=[0.1],
        teacher_scores=None,
        collection="codebase",
        metadata={"k": "v"},
        force=True,
    )
    assert ok is True

    files = events.list_event_files("codebase")
    assert len(files) == 1
    lines = files[0].read_text().splitlines()
    assert len(lines) == 1

    obj = json.loads(lines[0])
    assert obj["query"] == "q"
    assert obj["collection"] == "codebase"
    assert obj["metadata"]["k"] == "v"
    assert isinstance(obj["candidates"], list) and obj["candidates"]


def test_cleanup_old_events_deletes_old_files(monkeypatch, tmp_path):
    events = _load_events_module(monkeypatch, tmp_path)

    # Create a fake old event file for the collection.
    old = tmp_path / "events_codebase_2000010101.ndjson"
    old.write_text('{"ts": 0}\n')
    os.utime(old, (0, 0))

    # Make cutoff deterministic: now=100000 -> cutoff=100000-86400=13600, so mtime=0 is old.
    monkeypatch.setattr(events.time, "time", lambda: 100000.0)

    deleted = events.cleanup_old_events("codebase", max_age_days=1)
    assert deleted == 1
    assert not old.exists()


def test_log_training_event_thread_safe(monkeypatch, tmp_path):
    events = _load_events_module(monkeypatch, tmp_path)
    monkeypatch.setattr(events, "_get_hour_suffix", lambda: "2000010101")

    results: list[bool] = []
    lock = threading.Lock()

    def worker(i: int):
        ok = events.log_training_event(
            query=f"q{i}",
            candidates=[_candidate(f"/work/{i}.py")],
            initial_scores=[0.1],
            teacher_scores=None,
            collection="codebase",
            force=True,
        )
        with lock:
            results.append(bool(ok))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 10

    files = events.list_event_files("codebase")
    assert len(files) == 1
    lines = files[0].read_text().splitlines()
    assert len(lines) == 10
    for ln in lines:
        json.loads(ln)  # should not raise
