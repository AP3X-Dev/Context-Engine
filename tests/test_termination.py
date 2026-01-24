"""Tests for scripts/hybrid/termination.py - Smart termination conditions."""

import time
import pytest
from scripts.hybrid.termination import TerminationConfig, TerminationChecker


class TestTerminationConfig:
    """Tests for TerminationConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = TerminationConfig()
        assert config.time_limit == 5.0
        assert config.result_limit == 500
        assert config.min_candidates_for_expansion == 5
        assert config.score_degradation_threshold == 0.15
        assert config.min_relevance_score == 0.3
        assert config.top_n_to_track == 5

    def test_custom_values(self):
        """Test custom configuration values."""
        config = TerminationConfig(
            time_limit=10.0,
            result_limit=1000,
            min_candidates_for_expansion=10,
        )
        assert config.time_limit == 10.0
        assert config.result_limit == 1000
        assert config.min_candidates_for_expansion == 10


class TestTerminationChecker:
    """Tests for TerminationChecker class."""

    def test_initialization(self):
        """Test checker initialization."""
        checker = TerminationChecker()
        assert checker.iteration == 0
        assert checker.tracked_chunk_scores == {}
        assert checker.elapsed() >= 0

    def test_reset(self):
        """Test reset clears state."""
        checker = TerminationChecker()
        checker.iteration = 5
        checker.tracked_chunk_scores = {"a": 0.9}
        checker.reset()
        assert checker.iteration == 0
        assert checker.tracked_chunk_scores == {}

    def test_time_limit_termination(self):
        """Test termination on time limit."""
        config = TerminationConfig(time_limit=0.01)  # 10ms
        checker = TerminationChecker(config)
        
        # Wait for time limit
        time.sleep(0.02)
        
        results = [{"chunk_id": "a", "score": 0.9} for _ in range(10)]
        should_terminate, reason = checker.check(results)
        
        assert should_terminate is True
        assert reason == "time_limit"

    def test_result_limit_termination(self):
        """Test termination on result limit."""
        config = TerminationConfig(result_limit=5)
        checker = TerminationChecker(config)
        
        results = [{"chunk_id": f"c{i}", "score": 0.9} for i in range(10)]
        should_terminate, reason = checker.check(results)
        
        assert should_terminate is True
        assert reason == "result_limit"

    def test_insufficient_candidates_termination(self):
        """Test termination when not enough high-scoring candidates."""
        config = TerminationConfig(min_candidates_for_expansion=5)
        checker = TerminationChecker(config)
        
        # Only 3 results with positive scores
        results = [
            {"chunk_id": "a", "score": 0.9},
            {"chunk_id": "b", "score": 0.8},
            {"chunk_id": "c", "score": 0.7},
        ]
        should_terminate, reason = checker.check(results)
        
        assert should_terminate is True
        assert reason == "insufficient_candidates"

    def test_score_degradation_termination(self):
        """Test termination on score degradation."""
        config = TerminationConfig(
            score_degradation_threshold=0.1,
            top_n_to_track=3,
            min_candidates_for_expansion=1,
            min_relevance_score=0.0,
        )
        checker = TerminationChecker(config)
        
        # First iteration - establish baseline
        results1 = [
            {"chunk_id": "a", "score": 0.9},
            {"chunk_id": "b", "score": 0.8},
            {"chunk_id": "c", "score": 0.7},
        ]
        should_terminate, reason = checker.check(results1)
        assert should_terminate is False
        
        # Second iteration - scores dropped significantly
        results2 = [
            {"chunk_id": "a", "score": 0.7},  # Dropped 0.2
            {"chunk_id": "b", "score": 0.6},
            {"chunk_id": "c", "score": 0.5},
        ]
        should_terminate, reason = checker.check(results2)
        
        assert should_terminate is True
        assert reason == "score_degradation"

    def test_min_relevance_termination(self):
        """Test termination when min relevance score is too low."""
        config = TerminationConfig(
            min_relevance_score=0.5,
            top_n_to_track=3,
            min_candidates_for_expansion=1,
        )
        checker = TerminationChecker(config)
        
        # Results with low minimum score in top-N
        results = [
            {"chunk_id": "a", "score": 0.9},
            {"chunk_id": "b", "score": 0.6},
            {"chunk_id": "c", "score": 0.3},  # Below min_relevance_score
        ]
        should_terminate, reason = checker.check(results)
        
        assert should_terminate is True
        assert reason == "min_relevance"

    def test_no_termination_when_conditions_not_met(self):
        """Test that checker continues when no conditions are met."""
        config = TerminationConfig(
            time_limit=60.0,
            result_limit=1000,
            min_candidates_for_expansion=3,
            min_relevance_score=0.3,
        )
        checker = TerminationChecker(config)
        
        results = [
            {"chunk_id": "a", "score": 0.9},
            {"chunk_id": "b", "score": 0.8},
            {"chunk_id": "c", "score": 0.7},
            {"chunk_id": "d", "score": 0.6},
            {"chunk_id": "e", "score": 0.5},
        ]
        should_terminate, reason = checker.check(results)
        
        assert should_terminate is False
        assert reason == ""

    def test_get_stats(self):
        """Test get_stats returns correct information."""
        checker = TerminationChecker()
        results = [{"chunk_id": "a", "score": 0.9} for _ in range(10)]
        checker.check(results)
        checker.check(results)
        
        stats = checker.get_stats()
        assert stats["iterations"] == 2
        assert "elapsed_seconds" in stats
        assert stats["elapsed_seconds"] >= 0

    def test_iteration_counter_increments(self):
        """Test that iteration counter increments on each check."""
        checker = TerminationChecker()
        results = [{"chunk_id": f"c{i}", "score": 0.9} for i in range(10)]
        
        checker.check(results)
        assert checker.iteration == 1
        
        checker.check(results)
        assert checker.iteration == 2

