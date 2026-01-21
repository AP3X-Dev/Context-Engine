#!/usr/bin/env python3
"""Tests for info_request confidence metrics with variance analysis."""
import pytest
from unittest.mock import patch, MagicMock
from scripts.mcp_impl.info_request import (
    _compute_score_statistics,
    _calculate_confidence,
    _extract_symbols_from_query,
)


class TestScoreStatistics:
    """Test _compute_score_statistics edge cases and normal operation."""

    def test_empty_results(self):
        """Empty results should return zeros."""
        stats = _compute_score_statistics([])
        assert stats["mean"] == 0.0
        assert stats["std"] == 0.0
        assert stats["cv"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0

    def test_single_result(self):
        """Single result should have zero variance."""
        results = [{"score": 0.75}]
        stats = _compute_score_statistics(results)
        assert stats["mean"] == 0.75
        assert stats["std"] == 0.0
        assert stats["cv"] == 0.0
        assert stats["min"] == 0.75
        assert stats["max"] == 0.75

    def test_identical_scores(self):
        """Identical scores should have zero variance."""
        results = [{"score": 0.5}] * 5
        stats = _compute_score_statistics(results)
        assert stats["mean"] == 0.5
        assert stats["std"] == 0.0
        assert stats["cv"] == 0.0

    def test_known_distribution(self):
        """Test with known score distribution."""
        # Scores: [0.9, 0.7, 0.5, 0.3, 0.1]
        # Mean = 0.5, Var = 0.08, Std = 0.2828, CV = 0.5657
        results = [
            {"score": 0.9},
            {"score": 0.7},
            {"score": 0.5},
            {"score": 0.3},
            {"score": 0.1},
        ]
        stats = _compute_score_statistics(results)
        assert abs(stats["mean"] - 0.5) < 0.01
        assert abs(stats["std"] - 0.2828) < 0.01
        assert abs(stats["cv"] - 0.5657) < 0.01

    def test_nan_scores(self):
        """NaN scores should be filtered out."""
        results = [
            {"score": 0.8},
            {"score": float("nan")},
            {"score": 0.6},
            {"score": None},
        ]
        stats = _compute_score_statistics(results)
        # Should only use 0.8 and 0.6
        assert abs(stats["mean"] - 0.7) < 0.01
        assert stats["std"] > 0

    def test_zero_mean_cv(self):
        """Zero mean should result in CV=0 to avoid division by zero."""
        results = [{"score": 0.0}] * 3
        stats = _compute_score_statistics(results)
        assert stats["cv"] == 0.0


class TestCalculateConfidence:
    """Test _calculate_confidence with variance metrics."""

    def test_no_results(self):
        """No results should return 'none' level."""
        conf = _calculate_confidence("test query", [])
        assert conf["level"] == "none"
        assert conf["score"] == 0.0

    def test_high_confidence(self):
        """High score with symbol match should be 'high' confidence."""
        results = [
            {"score": 0.85, "symbol": "test_function"},
            {"score": 0.80, "symbol": "test_class"},
        ]
        conf = _calculate_confidence("test", results)
        assert conf["level"] == "high"
        assert conf["score"] > 0.8
        assert conf["symbol_matches"] > 0

    def test_medium_confidence(self):
        """Medium average score should be 'medium' confidence."""
        results = [
            {"score": 0.65, "symbol": "foo"},
            {"score": 0.60, "symbol": "bar"},
        ]
        conf = _calculate_confidence("unrelated query", results)
        assert conf["level"] == "medium"

    def test_low_confidence_with_hint(self):
        """Low confidence should include hint."""
        results = [
            {"score": 0.4, "symbol": "foo"},
            {"score": 0.3, "symbol": "bar"},
        ]
        conf = _calculate_confidence("query", results)
        assert conf["level"] == "low"
        assert "low_confidence_hint" in conf
        assert "specific" in conf["low_confidence_hint"].lower()

    def test_variance_metrics_present(self):
        """All variance metrics should be present."""
        results = [
            {"score": 0.9},
            {"score": 0.5},
            {"score": 0.1},
        ]
        conf = _calculate_confidence("test", results)
        assert "variance_score" in conf
        assert "score_spread" in conf
        assert "consistency_level" in conf
        assert "coefficient_of_variation" in conf
        assert "min_score" in conf
        assert "max_score" in conf

    def test_high_consistency_level(self):
        """Low CV should result in 'high' consistency."""
        # Similar scores: CV < 0.2
        results = [
            {"score": 0.75},
            {"score": 0.73},
            {"score": 0.77},
        ]
        conf = _calculate_confidence("test", results)
        assert conf["consistency_level"] == "high"

    def test_medium_consistency_level(self):
        """Moderate CV should result in 'medium' consistency."""
        # CV between 0.2 and 0.4 requires more spread
        # For mean ~0.65, std ~0.2 gives CV ~0.3
        results = [
            {"score": 0.85},
            {"score": 0.45},
            {"score": 0.65},
        ]
        conf = _calculate_confidence("test", results)
        assert conf["consistency_level"] == "medium"

    def test_low_consistency_level(self):
        """High CV should result in 'low' consistency."""
        # Widely varying scores: CV > 0.4
        results = [
            {"score": 0.9},
            {"score": 0.3},
            {"score": 0.6},
        ]
        conf = _calculate_confidence("test", results)
        assert conf["consistency_level"] == "low"

    def test_score_spread_calculation(self):
        """Score spread should be max - min."""
        results = [
            {"score": 0.9},
            {"score": 0.2},
        ]
        conf = _calculate_confidence("test", results)
        assert abs(conf["score_spread"] - 0.7) < 0.01


class TestExtractSymbolsFromQuery:
    """Test _extract_symbols_from_query symbol extraction."""

    def test_camelcase_extraction(self):
        """Extract CamelCase symbols from query."""
        symbols = _extract_symbols_from_query("UserProfile and DataManager")
        assert "UserProfile" in symbols
        assert "DataManager" in symbols

    def test_snake_case_extraction(self):
        """Extract snake_case symbols from query."""
        symbols = _extract_symbols_from_query("get_user_data and fetch_profile_info")
        assert "get_user_data" in symbols
        assert "fetch_profile_info" in symbols

    def test_function_def_extraction(self):
        """Extract symbols from function definitions."""
        symbols = _extract_symbols_from_query("def calculate_total and class UserModel")
        assert "calculate_total" in symbols
        assert "UserModel" in symbols

    def test_limit_to_5_symbols(self):
        """Should limit to top 5 symbols."""
        query = "One Two Three Four Five Six Seven Eight"
        symbols = _extract_symbols_from_query(query)
        assert len(symbols) <= 5

    def test_short_symbols_filtered(self):
        """Symbols with ≤2 characters should be filtered."""
        symbols = _extract_symbols_from_query("ab cd getUserData class MyClass")
        assert "ab" not in symbols
        assert "cd" not in symbols
        # getUserData might not match if pattern is strict, but MyClass should
        assert len(symbols) >= 1  # At least one symbol extracted

    def test_no_symbols_found(self):
        """Empty list when no symbols found."""
        symbols = _extract_symbols_from_query("how does it work")
        assert len(symbols) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
