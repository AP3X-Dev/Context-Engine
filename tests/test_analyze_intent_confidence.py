#!/usr/bin/env python3
"""Tests for analyze_intent_confidence.py."""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.analyze_intent_confidence import (
    IntentEvent,
    AnalysisReport,
    parse_events,
    analyze_events,
    format_report_text,
)


@pytest.fixture
def sample_events():
    """Sample intent events for testing."""
    return [
        IntentEvent(
            timestamp=datetime.now().timestamp(),
            query="find tests for authentication",
            intent="search_tests",
            confidence=1.0,
            strategy="rules",
        ),
        IntentEvent(
            timestamp=datetime.now().timestamp(),
            query="explain the caching mechanism",
            intent="answer",
            confidence=0.85,
            strategy="ml",
            threshold=0.25,
            candidates=[["answer", 0.85], ["search", 0.45]],
        ),
        IntentEvent(
            timestamp=datetime.now().timestamp(),
            query="who calls authenticate",
            intent="symbol_graph",
            confidence=1.0,
            strategy="rules",
        ),
        IntentEvent(
            timestamp=datetime.now().timestamp(),
            query="something ambiguous",
            intent="search",
            confidence=0.3,
            strategy="ml",
            threshold=0.25,
            candidates=[["search", 0.3], ["answer", 0.28]],
        ),
    ]


@pytest.fixture
def events_dir(sample_events):
    """Create a temporary directory with sample event logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "intent_confidence_2026-01-24.jsonl"
        with open(log_file, "w") as f:
            for event in sample_events:
                f.write(json.dumps({
                    "timestamp": event.timestamp,
                    "query": event.query,
                    "intent": event.intent,
                    "confidence": event.confidence,
                    "strategy": event.strategy,
                    "threshold": event.threshold,
                    "candidates": event.candidates,
                }) + "\n")
        yield Path(tmpdir)


class TestIntentEvent:
    """Tests for IntentEvent dataclass."""

    def test_from_dict_complete(self):
        data = {
            "timestamp": 1234567890.0,
            "query": "test query",
            "intent": "search",
            "confidence": 0.95,
            "strategy": "rules",
            "threshold": None,
            "candidates": [],
        }
        event = IntentEvent.from_dict(data)
        assert event.timestamp == 1234567890.0
        assert event.query == "test query"
        assert event.intent == "search"
        assert event.confidence == 0.95
        assert event.strategy == "rules"

    def test_from_dict_partial(self):
        data = {"query": "test"}
        event = IntentEvent.from_dict(data)
        assert event.query == "test"
        assert event.intent == "unknown"
        assert event.confidence == 0.0


class TestParseEvents:
    """Tests for parse_events function."""

    def test_parse_events_basic(self, events_dir):
        events = parse_events(events_dir, days=7)
        assert len(events) == 4

    def test_parse_events_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            events = parse_events(Path(tmpdir), days=7)
            assert len(events) == 0


class TestAnalyzeEvents:
    """Tests for analyze_events function."""

    def test_analyze_events_basic(self, sample_events):
        report = analyze_events(sample_events)
        assert report.total_events == 4
        assert report.strategy_distribution["rules"] == 2
        assert report.strategy_distribution["ml"] == 2
        assert "search_tests" in report.intent_distribution
        assert "answer" in report.intent_distribution
        assert "symbol_graph" in report.intent_distribution
        assert "search" in report.intent_distribution

    def test_analyze_events_avg_confidence(self, sample_events):
        report = analyze_events(sample_events)
        # (1.0 + 0.85 + 1.0 + 0.3) / 4 = 0.7875
        assert abs(report.avg_confidence - 0.7875) < 0.01

    def test_analyze_events_fallback_rate(self, sample_events):
        report = analyze_events(sample_events)
        # 1 out of 2 ML events fell back to "search"
        assert report.fallback_rate == 0.5

    def test_analyze_events_low_confidence(self, sample_events):
        report = analyze_events(sample_events, low_confidence_threshold=0.5)
        # Only "something ambiguous" with confidence 0.3 should appear
        assert len(report.low_confidence_queries) == 1
        assert report.low_confidence_queries[0]["confidence"] == 0.3

    def test_analyze_events_empty(self):
        report = analyze_events([])
        assert report.total_events == 0
        assert report.avg_confidence == 0.0


class TestFormatReport:
    """Tests for format_report_text function."""

    def test_format_report_contains_sections(self, sample_events):
        report = analyze_events(sample_events)
        text = format_report_text(report)

        assert "INTENT CONFIDENCE ANALYSIS" in text
        assert "Total Events:" in text
        assert "Strategy Distribution:" in text
        assert "Intent Distribution:" in text
        assert "Average Confidence:" in text
        assert "Fallback Rate" in text

    def test_format_report_shows_percentages(self, sample_events):
        report = analyze_events(sample_events)
        text = format_report_text(report)

        # Should show percentages for strategy/intent distributions
        assert "%" in text


class TestIntegration:
    """Integration tests using file I/O."""

    def test_full_pipeline(self, events_dir):
        # Parse
        events = parse_events(events_dir, days=7)
        assert len(events) == 4

        # Analyze
        report = analyze_events(events)
        assert report.total_events == 4

        # Format
        text = format_report_text(report)
        assert "INTENT CONFIDENCE ANALYSIS" in text

        # JSON serialization
        report_dict = report.to_dict()
        json_str = json.dumps(report_dict)
        assert "total_events" in json_str
