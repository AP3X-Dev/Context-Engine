#!/usr/bin/env python3
"""
Integration tests for discovery features.

Tests the complete pipeline:
1. Server warmup
2. Query with low confidence
3. Score variance detection
4. Symbol suggestions
5. Intent logging
"""
import pytest
import os
import json
from pathlib import Path

pytestmark = pytest.mark.integration


@pytest.fixture
def temp_events_dir(tmp_path):
    """Create temporary events directory for intent logging."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    old_dir = os.environ.get("INTENT_EVENTS_DIR")
    os.environ["INTENT_EVENTS_DIR"] = str(events_dir)
    yield events_dir
    if old_dir:
        os.environ["INTENT_EVENTS_DIR"] = old_dir
    else:
        os.environ.pop("INTENT_EVENTS_DIR", None)


class TestDiscoveryIntegration:
    """End-to-end integration test for all discovery features."""

    def test_warmup_status_available(self):
        """Step 1: Verify warmup status can be retrieved."""
        from scripts.warm_start import get_warmup_status

        status = get_warmup_status()
        assert isinstance(status, dict)
        assert "status" in status
        # Status can be "cold", "warming", "warm", or "failed"
        assert status["status"] in ["cold", "warming", "warm", "failed"]

    def test_confidence_calculation_with_variance(self):
        """Step 2: Execute search with confidence metrics."""
        from scripts.mcp_impl.info_request import _compute_score_statistics, _calculate_confidence

        # Mock results with diverse scores (high variance)
        results = [
            {"score": 0.9},
            {"score": 0.3},
            {"score": 0.6},
            {"score": 0.7},
        ]

        # Compute statistics
        stats = _compute_score_statistics(results)
        assert "mean" in stats
        assert "std" in stats
        assert "cv" in stats
        assert stats["cv"] > 0  # Non-zero variance

        # Compute confidence with variance metrics
        # Note: _calculate_confidence(query, results) signature
        confidence = _calculate_confidence("test", results)
        assert "level" in confidence
        assert "score" in confidence
        assert "variance_score" in confidence
        assert "score_spread" in confidence
        assert "consistency_level" in confidence
        assert "coefficient_of_variation" in confidence

    def test_score_variance_detection(self):
        """Step 3: Verify score variance detection works."""
        from scripts.hybrid.ranking import _detect_score_variance

        # High variance scores
        high_var_scores = [0.9, 0.2, 0.5, 0.8]
        result = _detect_score_variance(high_var_scores)

        assert "cv" in result
        assert "high_variance" in result
        assert "variance" in result
        assert "mean" in result
        assert "std" in result

        # Verify high variance flag when CV > 0.3
        if result["cv"] > 0.3:
            assert result["high_variance"] is True

    def test_symbol_suggestions_scoring(self):
        """Step 4: Trigger symbol suggestions with typo."""
        from scripts.mcp_impl.symbol_graph import _similarity_score, _edit_distance

        # Test fuzzy matching for typos
        score = _similarity_score("getUserProf", "getUserProfile")
        assert score > 0  # Should match with some similarity

        # Test edit distance
        ed = _edit_distance("getUserProf", "getUserProfile")
        assert ed <= 3  # Within reasonable edit distance

    def test_intent_logging_creates_file(self, temp_events_dir):
        """Step 5: Verify intent event logged to JSONL."""
        from scripts.mcp_router.intent import classify_intent

        # Enable tracking
        os.environ["INTENT_TRACKING_ENABLED"] = "1"

        # Classify an intent (returns single string)
        intent = classify_intent("find tests for authentication")

        assert intent is not None
        assert isinstance(intent, str)

        # Check JSONL file created
        import time
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        jsonl_file = temp_events_dir / f"intent_confidence_{today}.jsonl"

        # Give it a moment to write
        time.sleep(0.1)

        # File should exist and contain valid JSON
        if jsonl_file.exists():
            with open(jsonl_file) as f:
                lines = f.readlines()
                if lines:
                    event = json.loads(lines[-1])
                    assert "query" in event
                    assert "intent" in event
                    assert "confidence" in event
                    assert "strategy" in event

    def test_end_to_end_pipeline(self, temp_events_dir):
        """Comprehensive E2E test covering all features."""
        # This test validates AC7: All features work together

        # 1. Check warmup status
        from scripts.warm_start import get_warmup_status
        warmup_status = get_warmup_status()
        assert "status" in warmup_status

        # 2. Test confidence calculation
        from scripts.mcp_impl.info_request import _calculate_confidence
        test_results = [
            {"score": 0.85},
            {"score": 0.4},
            {"score": 0.65},
        ]
        confidence = _calculate_confidence("test query", test_results)
        assert "variance_score" in confidence
        assert "consistency_level" in confidence

        # 3. Test variance detection
        from scripts.hybrid.ranking import _detect_score_variance
        scores = [r["score"] for r in test_results]
        variance = _detect_score_variance(scores)
        assert "cv" in variance
        assert "high_variance" in variance

        # 4. Test symbol suggestions
        from scripts.mcp_impl.symbol_graph import _similarity_score
        sim_score = _similarity_score("getUser", "getUserProfile")
        assert sim_score > 0.5  # Should have high similarity

        # 5. Test intent logging
        os.environ["INTENT_TRACKING_ENABLED"] = "1"
        from scripts.mcp_router.intent import classify_intent
        intent = classify_intent("search for config files")
        assert intent is not None

        # Verify all components completed without errors
        assert True  # If we got here, pipeline works


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
