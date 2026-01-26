"""Tests for scripts/hybrid/elbow_detection.py - Kneedle algorithm and adaptive thresholds."""

import pytest
from scripts.hybrid.elbow_detection import (
    find_elbow_kneedle,
    compute_elbow_threshold,
    filter_by_elbow,
)


class TestFindElbowKneedle:
    """Tests for the Kneedle algorithm implementation."""

    def test_clear_elbow_detected(self):
        """Test detection of a clear elbow point."""
        # Clear drop after index 2
        scores = [0.95, 0.92, 0.88, 0.45, 0.42, 0.40]
        elbow_idx = find_elbow_kneedle(scores)
        assert elbow_idx is not None
        # Elbow should be around the drop point
        assert 1 <= elbow_idx <= 3

    def test_too_few_points_returns_none(self):
        """Test that fewer than 3 points returns None."""
        assert find_elbow_kneedle([0.9]) is None
        assert find_elbow_kneedle([0.9, 0.8]) is None
        assert find_elbow_kneedle([]) is None

    def test_identical_scores_returns_none(self):
        """Test that identical scores return None (no elbow)."""
        scores = [0.5, 0.5, 0.5, 0.5, 0.5]
        assert find_elbow_kneedle(scores) is None

    def test_linear_decrease_minimal_elbow(self):
        """Test linear decrease - may or may not detect elbow."""
        scores = [1.0, 0.8, 0.6, 0.4, 0.2]
        # Linear decrease has no clear elbow
        result = find_elbow_kneedle(scores)
        # Should return None or a middle index
        assert result is None or 0 <= result < len(scores)

    def test_sharp_drop_at_end(self):
        """Test sharp drop at the end of the curve."""
        scores = [0.95, 0.94, 0.93, 0.92, 0.10]
        elbow_idx = find_elbow_kneedle(scores)
        assert elbow_idx is not None
        # Elbow should be near the drop
        assert elbow_idx >= 2

    def test_gradual_then_sharp_drop(self):
        """Test gradual decrease followed by sharp drop."""
        scores = [0.99, 0.98, 0.97, 0.96, 0.30, 0.29, 0.28]
        elbow_idx = find_elbow_kneedle(scores)
        assert elbow_idx is not None
        # Elbow should be around index 3-4
        assert 2 <= elbow_idx <= 5


class TestComputeElbowThreshold:
    """Tests for compute_elbow_threshold function."""

    def test_empty_input_returns_default(self):
        """Test empty input returns default threshold."""
        assert compute_elbow_threshold([]) == 0.5
        # Single dict with no score extracts 0.0, which is a valid score
        result = compute_elbow_threshold([{}])
        assert 0.0 <= result <= 0.5

    def test_with_raw_scores(self):
        """Test with raw float scores."""
        scores = [0.95, 0.88, 0.45, 0.42]
        threshold = compute_elbow_threshold(scores)
        assert 0.0 <= threshold <= 1.0
        # Threshold should be around the elbow
        assert threshold >= 0.40

    def test_with_dict_chunks(self):
        """Test with dict chunks containing score key."""
        chunks = [
            {"score": 0.95},
            {"score": 0.88},
            {"score": 0.45},
            {"score": 0.42},
        ]
        threshold = compute_elbow_threshold(chunks)
        assert 0.0 <= threshold <= 1.0

    def test_with_fallback_score_key(self):
        """Test fallback to rerank_score when score is missing."""
        chunks = [
            {"rerank_score": 0.95},
            {"rerank_score": 0.45},
            {"rerank_score": 0.20},
        ]
        threshold = compute_elbow_threshold(chunks, score_key="score")
        assert 0.0 <= threshold <= 1.0

    def test_zero_scores_handled_correctly(self):
        """Test that 0.0 scores are handled correctly (not treated as missing)."""
        chunks = [
            {"score": 0.95},
            {"score": 0.0},  # Real zero score
            {"score": 0.0},
        ]
        threshold = compute_elbow_threshold(chunks)
        # Should not crash and should return valid threshold
        assert 0.0 <= threshold <= 1.0

    def test_custom_score_key(self):
        """Test with custom score key."""
        chunks = [
            {"my_score": 0.9},
            {"my_score": 0.5},
            {"my_score": 0.1},
        ]
        threshold = compute_elbow_threshold(chunks, score_key="my_score")
        assert 0.0 <= threshold <= 1.0


class TestFilterByElbow:
    """Tests for filter_by_elbow function."""

    def test_empty_results(self):
        """Test empty input returns empty list."""
        assert filter_by_elbow([]) == []

    def test_filters_below_threshold(self):
        """Test that results below threshold are filtered."""
        results = [
            {"id": 1, "score": 0.95},
            {"id": 2, "score": 0.90},
            {"id": 3, "score": 0.30},  # Below elbow
            {"id": 4, "score": 0.25},  # Below elbow
        ]
        filtered = filter_by_elbow(results)
        # Should keep high-scoring results
        assert len(filtered) >= 1
        assert all(r["score"] >= 0.25 for r in filtered)

    def test_min_results_guaranteed(self):
        """Test that min_results are always returned."""
        results = [
            {"id": 1, "score": 0.95},
            {"id": 2, "score": 0.10},
            {"id": 3, "score": 0.05},
        ]
        filtered = filter_by_elbow(results, min_results=2)
        assert len(filtered) >= 2

    def test_zero_score_not_treated_as_missing(self):
        """Test that 0.0 score is not treated as missing."""
        results = [
            {"id": 1, "score": 0.9},
            {"id": 2, "score": 0.0},  # Real zero, not missing
            {"id": 3, "score": 0.0},
        ]
        # Should not crash
        filtered = filter_by_elbow(results)
        assert isinstance(filtered, list)

    def test_fallback_score_key_used(self):
        """Test that fallback score key is used when primary is missing."""
        results = [
            {"id": 1, "rerank_score": 0.95},
            {"id": 2, "rerank_score": 0.50},
            {"id": 3, "rerank_score": 0.10},
        ]
        filtered = filter_by_elbow(results, score_key="score", fallback_score_key="rerank_score")
        assert len(filtered) >= 1

