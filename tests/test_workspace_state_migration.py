#!/usr/bin/env python3
"""
Tests for backend migration in workspace_state.py.

Tests cover:
- Backend detection (_get_current_backend)
- Marker file operations (_read_backend_marker, _write_backend_marker)
- File to Redis migration (_migrate_file_to_redis)
- Redis to file migration (_migrate_redis_to_file)
- Migration detection and orchestration (detect_and_migrate_backend)
- Skip migration flag
- Idempotency and edge cases
"""
import importlib
import json
import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ============================================================================
# Fixture: Isolated workspace_state import
# ============================================================================
@pytest.fixture
def ws_module(monkeypatch, tmp_path):
    """
    Import workspace_state with isolated environment and temp workspace.
    Returns the reloaded module.
    """
    ws_root = tmp_path / "work"
    ws_root.mkdir(parents=True, exist_ok=True)
    codebase_dir = ws_root / ".codebase"
    codebase_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("WORKSPACE_PATH", str(ws_root))
    monkeypatch.setenv("WATCH_ROOT", str(ws_root))
    monkeypatch.delenv("MULTI_REPO_MODE", raising=False)
    monkeypatch.delenv("CODEBASE_STATE_BACKEND", raising=False)
    monkeypatch.delenv("CODEBASE_STATE_REDIS_ENABLED", raising=False)
    monkeypatch.delenv("CODEBASE_STATE_SKIP_MIGRATION", raising=False)

    ws = importlib.import_module("scripts.workspace_state")
    ws = importlib.reload(ws)

    # Reset migration flag for each test
    ws._migration_done = False

    return ws


@pytest.fixture
def ws_root(tmp_path):
    """Create a temp workspace root."""
    ws_root = tmp_path / "work"
    ws_root.mkdir(parents=True, exist_ok=True)
    return ws_root


# ============================================================================
# Tests: Backend Detection
# ============================================================================
class TestGetCurrentBackend:
    """Tests for _get_current_backend function."""

    def test_default_is_file(self, ws_module, monkeypatch):
        """Default backend is 'file' when no env vars set."""
        monkeypatch.delenv("CODEBASE_STATE_BACKEND", raising=False)
        monkeypatch.delenv("CODEBASE_STATE_REDIS_ENABLED", raising=False)
        ws = importlib.reload(ws_module)
        assert ws._get_current_backend() == "file"

    def test_redis_backend_explicit(self, ws_module, monkeypatch):
        """Backend is 'redis' when explicitly set."""
        monkeypatch.setenv("CODEBASE_STATE_BACKEND", "redis")
        ws = importlib.reload(ws_module)
        assert ws._get_current_backend() == "redis"

    def test_redis_enabled_flag(self, ws_module, monkeypatch):
        """Backend is 'redis' when REDIS_ENABLED=1."""
        monkeypatch.delenv("CODEBASE_STATE_BACKEND", raising=False)
        monkeypatch.setenv("CODEBASE_STATE_REDIS_ENABLED", "1")
        ws = importlib.reload(ws_module)
        assert ws._get_current_backend() == "redis"

    def test_file_backend_explicit(self, ws_module, monkeypatch):
        """Backend is 'file' when explicitly set."""
        monkeypatch.setenv("CODEBASE_STATE_BACKEND", "file")
        ws = importlib.reload(ws_module)
        assert ws._get_current_backend() == "file"

    def test_filesystem_backend_alias(self, ws_module, monkeypatch):
        """Backend 'filesystem' is treated as 'file'."""
        monkeypatch.setenv("CODEBASE_STATE_BACKEND", "filesystem")
        ws = importlib.reload(ws_module)
        assert ws._get_current_backend() == "file"


# ============================================================================
# Tests: Marker File Operations
# ============================================================================
class TestBackendMarker:
    """Tests for backend marker file operations."""

    def test_get_marker_path(self, ws_module, ws_root):
        """Marker path is correct."""
        marker_path = ws_module._get_backend_marker_path(ws_root)
        expected = ws_root / ".codebase" / ".backend_marker"
        assert marker_path == expected

    def test_read_marker_missing(self, ws_module, ws_root):
        """Reading missing marker returns None."""
        result = ws_module._read_backend_marker(ws_root)
        assert result is None

    def test_write_and_read_marker(self, ws_module, ws_root):
        """Can write and read marker."""
        (ws_root / ".codebase").mkdir(parents=True, exist_ok=True)
        ws_module._write_backend_marker("redis", ws_root)
        result = ws_module._read_backend_marker(ws_root)
        assert result == "redis"

    def test_write_and_read_file_marker(self, ws_module, ws_root):
        """Can write and read 'file' marker."""
        (ws_root / ".codebase").mkdir(parents=True, exist_ok=True)
        ws_module._write_backend_marker("file", ws_root)
        result = ws_module._read_backend_marker(ws_root)
        assert result == "file"

    def test_invalid_marker_content(self, ws_module, ws_root):
        """Invalid marker content returns None."""
        codebase_dir = ws_root / ".codebase"
        codebase_dir.mkdir(parents=True, exist_ok=True)
        marker_path = codebase_dir / ".backend_marker"
        marker_path.write_text("invalid_backend\n")
        result = ws_module._read_backend_marker(ws_root)
        assert result is None

    def test_marker_creates_directory(self, ws_module, tmp_path):
        """Marker write creates .codebase directory if missing."""
        ws_root = tmp_path / "new_workspace"
        ws_root.mkdir()
        ws_module._write_backend_marker("redis", ws_root)
        marker_path = ws_root / ".codebase" / ".backend_marker"
        assert marker_path.exists()
        assert marker_path.read_text().strip() == "redis"


# ============================================================================
# Tests: detect_and_migrate_backend
# ============================================================================
class TestDetectAndMigrateBackend:
    """Tests for detect_and_migrate_backend orchestration."""

    def test_first_run_no_migration(self, ws_module, ws_root, monkeypatch):
        """First run (no marker) initializes marker, no migration."""
        monkeypatch.setenv("CODEBASE_STATE_BACKEND", "file")
        ws = importlib.reload(ws_module)
        ws._migration_done = False

        result = ws.detect_and_migrate_backend(ws_root)

        assert result is None  # No migration occurred
        # Marker should be created
        marker = ws._read_backend_marker(ws_root)
        assert marker == "file"

    def test_same_backend_no_migration(self, ws_module, ws_root, monkeypatch):
        """Same backend (no switch) returns None."""
        monkeypatch.setenv("CODEBASE_STATE_BACKEND", "file")
        ws = importlib.reload(ws_module)
        ws._migration_done = False

        # Set marker to current backend
        ws._write_backend_marker("file", ws_root)

        result = ws.detect_and_migrate_backend(ws_root)

        assert result is None  # No migration needed

    def test_skip_migration_flag(self, ws_module, ws_root, monkeypatch):
        """CODEBASE_STATE_SKIP_MIGRATION=1 skips migration."""
        monkeypatch.setenv("CODEBASE_STATE_SKIP_MIGRATION", "1")
        ws = importlib.reload(ws_module)
        ws._migration_done = False

        # Set marker to different backend to trigger migration
        ws._write_backend_marker("redis", ws_root)

        result = ws.detect_and_migrate_backend(ws_root)

        assert result is None  # Migration skipped

    def test_idempotency_same_process(self, ws_module, ws_root, monkeypatch):
        """Migration only runs once per process."""
        monkeypatch.setenv("CODEBASE_STATE_BACKEND", "file")
        ws = importlib.reload(ws_module)

        # First call
        ws._migration_done = False
        result1 = ws.detect_and_migrate_backend(ws_root)

        # Second call should skip (migration_done = True)
        result2 = ws.detect_and_migrate_backend(ws_root)

        assert result2 is None  # Skipped due to flag

    def test_file_to_redis_switch_detected(self, ws_module, ws_root, monkeypatch):
        """File to Redis switch is detected and triggers migration."""
        # Start with file backend marker
        codebase_dir = ws_root / ".codebase"
        codebase_dir.mkdir(parents=True, exist_ok=True)
        ws_module._write_backend_marker("file", ws_root)

        # Create a state.json file to migrate
        state_file = codebase_dir / "state.json"
        state_file.write_text(json.dumps({"collection": "test-coll"}))

        # Switch to Redis backend
        monkeypatch.setenv("CODEBASE_STATE_BACKEND", "redis")
        monkeypatch.setenv("CODEBASE_STATE_REDIS_URL", "redis://localhost:6379/0")
        ws = importlib.reload(ws_module)
        ws._migration_done = False

        # Mock Redis client
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.set.return_value = True

        with patch.object(ws, "_get_redis_client", return_value=mock_client):
            result = ws.detect_and_migrate_backend(ws_root)

        # Migration should occur (returns count of migrated items)
        assert result is not None
        assert result >= 1  # At least state.json migrated

    def test_redis_to_file_switch_detected(self, ws_module, ws_root, monkeypatch):
        """Redis to file switch is detected and triggers migration."""
        # Start with redis backend marker
        codebase_dir = ws_root / ".codebase"
        codebase_dir.mkdir(parents=True, exist_ok=True)
        ws_module._write_backend_marker("redis", ws_root)

        # Switch to file backend
        monkeypatch.setenv("CODEBASE_STATE_BACKEND", "file")
        ws = importlib.reload(ws_module)
        ws._migration_done = False

        # Mock Redis with some data
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.scan_iter.return_value = iter([
            "context-engine:codebase:state:abc123"
        ])
        mock_client.get.return_value = json.dumps({"collection": "test-coll"})

        with patch("redis.Redis.from_url", return_value=mock_client):
            result = ws.detect_and_migrate_backend(ws_root)

        # Migration should occur
        assert result is not None
        assert result >= 1

