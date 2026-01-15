#!/usr/bin/env python3
"""Tests for intent confidence tracking and logging."""
import pytest
import json
import tempfile
import os
from pathlib import Path
from scripts.mcp_router.intent import classify_intent, _log_intent_event, _flush_event_buffer


class TestIntentLogging:
    """Test intent event logging to JSONL files."""

    def test_logging_disabled(self):
        """Logging should be skippable via env flag."""
        old_val = os.environ.get("INTENT_TRACKING_ENABLED")
        try:
            os.environ["INTENT_TRACKING_ENABLED"] = "0"
            # Should not raise any errors
            _log_intent_event({"test": "event"})
        finally:
            if old_val is None:
                os.environ.pop("INTENT_TRACKING_ENABLED", None)
            else:
                os.environ["INTENT_TRACKING_ENABLED"] = old_val

    def test_event_file_creation(self):
        """Event file should be created with correct format."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            old_dir = os.environ.get("INTENT_EVENTS_DIR")
            try:
                os.environ["INTENT_EVENTS_DIR"] = tmpdir
                os.environ["INTENT_TRACKING_ENABLED"] = "1"
                os.environ["INTENT_FLUSH_SYNC"] = "1"  # Sync mode for tests

                event = {
                    "timestamp": 1234567890.0,
                    "query": "test query",
                    "intent": "search",
                    "confidence": 0.85,
                    "strategy": "ml",
                    "threshold": 0.25,
                    "candidates": [],
                }

                _log_intent_event(event)
                _flush_event_buffer()  # Force flush for test

                # Check file was created
                from datetime import datetime
                date_str = datetime.now().strftime("%Y-%m-%d")
                log_file = Path(tmpdir) / f"intent_confidence_{date_str}.jsonl"

                assert log_file.exists()

                # Check content - find our specific event (may have others from prior tests)
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    assert len(lines) >= 1
                    # Find our test event by unique query
                    our_events = [json.loads(l) for l in lines if "test query" in l]
                    assert len(our_events) == 1
                    logged_event = our_events[0]
                    assert logged_event["query"] == "test query"
                    assert logged_event["confidence"] == 0.85

            finally:
                os.environ.pop("INTENT_FLUSH_SYNC", None)
                if old_dir is None:
                    os.environ.pop("INTENT_EVENTS_DIR", None)
                else:
                    os.environ["INTENT_EVENTS_DIR"] = old_dir

    def test_file_rotation_on_size(self):
        """Files should rotate when exceeding size limit."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            old_dir = os.environ.get("INTENT_EVENTS_DIR")
            old_size = os.environ.get("INTENT_LOG_ROTATE_MB")
            try:
                os.environ["INTENT_EVENTS_DIR"] = tmpdir
                os.environ["INTENT_TRACKING_ENABLED"] = "1"
                os.environ["INTENT_FLUSH_SYNC"] = "1"
                os.environ["INTENT_LOG_ROTATE_MB"] = "0"  # Rotate immediately

                event = {"query": "test", "confidence": 0.5}

                # Log multiple events - should trigger rotation
                _log_intent_event(event)
                _log_intent_event(event)
                _flush_event_buffer()  # Force flush for test

                # At least one file should exist (rotation may create .1 file)
                from datetime import datetime
                date_str = datetime.now().strftime("%Y-%m-%d")

                files = list(Path(tmpdir).glob(f"intent_confidence_{date_str}.jsonl*"))
                assert len(files) >= 1

            finally:
                os.environ.pop("INTENT_FLUSH_SYNC", None)
                if old_dir is None:
                    os.environ.pop("INTENT_EVENTS_DIR", None)
                else:
                    os.environ["INTENT_EVENTS_DIR"] = old_dir
                if old_size is None:
                    os.environ.pop("INTENT_LOG_ROTATE_MB", None)
                else:
                    os.environ["INTENT_LOG_ROTATE_MB"] = old_size


class TestIntentRules:
    """Test rule-based intent classification."""

    def test_index_intent(self):
        """Test indexing keywords trigger INTENT_INDEX."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("reindex the codebase") == "index"
        assert _classify_intent_rules("reset and recreate index") == "index"

    def test_prune_intent(self):
        """Test prune keywords trigger INTENT_PRUNE."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("prune stale points") == "prune"
        assert _classify_intent_rules("cleanup old data") == "prune"

    def test_status_intent(self):
        """Test status keywords trigger INTENT_STATUS."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("check status") == "status"
        assert _classify_intent_rules("health check") == "status"

    def test_list_intent(self):
        """Test list keywords trigger INTENT_LIST."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("list collections") == "list"
        assert _classify_intent_rules("show all collections") == "list"

    def test_importers_intent_not_important(self):
        """Test importers intent excludes 'important'."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("who imports this module") == "search_importers"
        assert _classify_intent_rules("this is important") != "search_importers"  # Should not match

    def test_memory_store_intent_excludes_code_search(self):
        """Test memory_store excludes code implementation searches."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("remember this preference") == "memory_store"
        assert _classify_intent_rules("memory store implementation") != "memory_store"  # Code search

    def test_memory_find_intent(self):
        """Test memory_find intent."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("find memory about auth") == "memory_find"
        assert _classify_intent_rules("recall what we saved") == "memory_find"

    def test_symbol_graph_who_calls(self):
        """Test symbol_graph intent for 'who calls'."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("who calls getUserProfile") == "symbol_graph"
        assert _classify_intent_rules("show callers of login") == "symbol_graph"

    def test_symbol_graph_regex_calls(self):
        """Test symbol_graph regex for 'calls' pattern."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("what calls the function") == "symbol_graph"
        assert _classify_intent_rules("calls login function") == "symbol_graph"

    def test_config_intent(self):
        """Test config search intent."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("find config files") == "search_config"
        assert _classify_intent_rules("show yaml configuration") == "search_config"

    def test_search_callers_intent(self):
        """Test search_callers fallback intent."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("used by which functions") == "search_callers"
        assert _classify_intent_rules("usage sites for login") == "search_callers"

    def test_answer_intent_question_words(self):
        """Test answer intent for question words."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("what is authentication") == "answer"
        assert _classify_intent_rules("how does login work") == "answer"
        assert _classify_intent_rules("explain the design") == "answer"

    def test_answer_intent_keywords(self):
        """Test answer intent for specific keywords."""
        from scripts.mcp_router.intent import _classify_intent_rules
        assert _classify_intent_rules("show architecture") == "answer"
        assert _classify_intent_rules("design doc recap") == "answer"


class TestIntentClassification:
    """Test that classification logs events."""

    def test_rules_classification_logs(self):
        """Rule-based classification should log events."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            old_dir = os.environ.get("INTENT_EVENTS_DIR")
            try:
                os.environ["INTENT_EVENTS_DIR"] = tmpdir
                os.environ["INTENT_TRACKING_ENABLED"] = "1"
                os.environ["INTENT_FLUSH_SYNC"] = "1"

                # Classify a query that matches rules
                intent = classify_intent("find tests for authentication")
                _flush_event_buffer()  # Force flush for test

                assert intent == "search_tests"

                # Check event was logged
                from datetime import datetime
                date_str = datetime.now().strftime("%Y-%m-%d")
                log_file = Path(tmpdir) / f"intent_confidence_{date_str}.jsonl"

                assert log_file.exists()

                with open(log_file, "r") as f:
                    events = [json.loads(line) for line in f]
                    assert len(events) >= 1
                    assert events[-1]["intent"] == "search_tests"
                    assert events[-1]["strategy"] == "rules"
                    assert events[-1]["confidence"] == 1.0

            finally:
                os.environ.pop("INTENT_FLUSH_SYNC", None)
                if old_dir is None:
                    os.environ.pop("INTENT_EVENTS_DIR", None)
                else:
                    os.environ["INTENT_EVENTS_DIR"] = old_dir

    def test_ml_classification_logs(self):
        """ML classification should log events with candidates."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            old_dir = os.environ.get("INTENT_EVENTS_DIR")
            try:
                os.environ["INTENT_EVENTS_DIR"] = tmpdir
                os.environ["INTENT_TRACKING_ENABLED"] = "1"
                os.environ["INTENT_FLUSH_SYNC"] = "1"

                # Classify a query that uses ML (no rule match)
                classify_intent("show me the code")
                _flush_event_buffer()  # Force flush for test

                # Check event was logged
                from datetime import datetime
                date_str = datetime.now().strftime("%Y-%m-%d")
                log_file = Path(tmpdir) / f"intent_confidence_{date_str}.jsonl"

                assert log_file.exists()

                with open(log_file, "r") as f:
                    events = [json.loads(line) for line in f]
                    assert len(events) >= 1
                    last_event = events[-1]
                    assert last_event["strategy"] == "ml"
                    assert "confidence" in last_event
                    assert "candidates" in last_event
                    # Should have top 5 candidates
                    assert len(last_event["candidates"]) <= 5

            finally:
                os.environ.pop("INTENT_FLUSH_SYNC", None)
                if old_dir is None:
                    os.environ.pop("INTENT_EVENTS_DIR", None)
                else:
                    os.environ["INTENT_EVENTS_DIR"] = old_dir

    def test_get_last_intent_debug(self):
        """Test get_last_intent_debug returns recent classification info."""
        from scripts.mcp_router.intent import get_last_intent_debug

        # Classify a query to populate debug info
        classify_intent("find tests")

        debug_info = get_last_intent_debug()
        assert "query" in debug_info
        assert "intent" in debug_info


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
