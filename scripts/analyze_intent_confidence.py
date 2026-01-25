#!/usr/bin/env python3
"""
Analyze intent classification confidence from event logs.

Parses JSONL logs from ./events/intent_confidence_*.jsonl and generates
reports on strategy distribution, intent breakdown, and low-confidence queries.

Usage:
    python scripts/analyze_intent_confidence.py --days 7
    python scripts/analyze_intent_confidence.py --days 30 --output-format json
    python scripts/analyze_intent_confidence.py --low-confidence-threshold 0.5
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class IntentEvent:
    """Parsed intent classification event."""
    timestamp: float
    query: str
    intent: str
    confidence: float
    strategy: str
    threshold: Optional[float] = None
    candidates: List[Any] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IntentEvent":
        return cls(
            timestamp=d.get("timestamp", 0.0),
            query=d.get("query", ""),
            intent=d.get("intent", "unknown"),
            confidence=d.get("confidence", 0.0),
            strategy=d.get("strategy", "unknown"),
            threshold=d.get("threshold"),
            candidates=d.get("candidates", []),
        )


@dataclass
class AnalysisReport:
    """Analysis report for intent classification."""
    total_events: int = 0
    strategy_distribution: Dict[str, int] = field(default_factory=dict)
    intent_distribution: Dict[str, int] = field(default_factory=dict)
    avg_confidence: float = 0.0
    fallback_rate: float = 0.0
    low_confidence_queries: List[Dict[str, Any]] = field(default_factory=list)
    confidence_by_intent: Dict[str, float] = field(default_factory=dict)
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_events(
    events_dir: Path,
    days: int = 7,
    min_timestamp: Optional[float] = None,
) -> List[IntentEvent]:
    """Parse intent events from JSONL log files."""
    events = []

    if min_timestamp is None:
        cutoff = datetime.now() - timedelta(days=days)
        min_timestamp = cutoff.timestamp()

    # Find all intent log files
    log_files = sorted(events_dir.glob("intent_confidence_*.jsonl"))

    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        event = IntentEvent.from_dict(data)
                        if event.timestamp >= min_timestamp:
                            events.append(event)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"Warning: Could not read {log_file}: {e}", file=sys.stderr)

    return events


def analyze_events(
    events: List[IntentEvent],
    low_confidence_threshold: float = 0.4,
    top_low_confidence: int = 10,
) -> AnalysisReport:
    """Analyze intent events and generate report."""
    if not events:
        return AnalysisReport()

    report = AnalysisReport()
    report.total_events = len(events)

    # Strategy distribution
    strategy_counts = Counter(e.strategy for e in events)
    report.strategy_distribution = dict(strategy_counts)

    # Intent distribution
    intent_counts = Counter(e.intent for e in events)
    report.intent_distribution = dict(intent_counts)

    # Average confidence
    confidences = [e.confidence for e in events]
    report.avg_confidence = sum(confidences) / len(confidences)

    # Confidence by intent
    intent_confidences: Dict[str, List[float]] = defaultdict(list)
    for e in events:
        intent_confidences[e.intent].append(e.confidence)
    report.confidence_by_intent = {
        intent: sum(confs) / len(confs)
        for intent, confs in intent_confidences.items()
    }

    # Fallback rate (ML classifications that fell back to 'search')
    ml_events = [e for e in events if e.strategy == "ml"]
    if ml_events:
        fallbacks = sum(1 for e in ml_events if e.intent == "search")
        report.fallback_rate = fallbacks / len(ml_events)

    # Low confidence queries
    low_conf_events = sorted(
        [e for e in events if e.confidence < low_confidence_threshold],
        key=lambda e: e.confidence,
    )[:top_low_confidence]

    report.low_confidence_queries = [
        {
            "confidence": round(e.confidence, 2),
            "query": e.query[:80] + ("..." if len(e.query) > 80 else ""),
            "intent": e.intent,
            "strategy": e.strategy,
            "top_candidate": e.candidates[0] if e.candidates else None,
        }
        for e in low_conf_events
    ]

    # Time range
    timestamps = [e.timestamp for e in events]
    report.time_range_start = datetime.fromtimestamp(min(timestamps)).isoformat()
    report.time_range_end = datetime.fromtimestamp(max(timestamps)).isoformat()

    return report


def format_report_text(report: AnalysisReport) -> str:
    """Format report as human-readable text."""
    lines = []

    lines.append("=" * 80)
    lines.append("INTENT CONFIDENCE ANALYSIS")
    lines.append("=" * 80)
    lines.append("")

    if report.time_range_start and report.time_range_end:
        lines.append(f"Time Range: {report.time_range_start} to {report.time_range_end}")
        lines.append("")

    lines.append(f"Total Events: {report.total_events:,}")
    lines.append("")

    # Strategy distribution
    lines.append("Strategy Distribution:")
    total = sum(report.strategy_distribution.values()) or 1
    for strategy, count in sorted(report.strategy_distribution.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        lines.append(f"  {strategy:10s}: {count:5,} ({pct:5.1f}%)")
    lines.append("")

    # Intent distribution
    lines.append("Intent Distribution:")
    total = sum(report.intent_distribution.values()) or 1
    for intent, count in sorted(report.intent_distribution.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        lines.append(f"  {intent:18s}: {count:5,} ({pct:5.1f}%)")
    lines.append("")

    # Summary stats
    lines.append(f"Average Confidence: {report.avg_confidence:.2f}")
    lines.append(f"Fallback Rate (ML -> search): {report.fallback_rate * 100:.1f}%")
    lines.append("")

    # Confidence by intent
    lines.append("Average Confidence by Intent:")
    for intent, conf in sorted(report.confidence_by_intent.items(), key=lambda x: -x[1]):
        lines.append(f"  {intent:18s}: {conf:.2f}")
    lines.append("")

    # Low confidence queries
    if report.low_confidence_queries:
        lines.append(f"Top {len(report.low_confidence_queries)} Low-Confidence Queries:")
        for i, q in enumerate(report.low_confidence_queries, 1):
            top = f" (top: {q['top_candidate'][0]})" if q.get("top_candidate") else ""
            lines.append(f"  {i:2}. [{q['confidence']:.2f}] \"{q['query']}\" -> {q['intent']}{top}")
        lines.append("")

    lines.append("=" * 80)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze intent classification confidence from event logs."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to analyze (default: 7)",
    )
    parser.add_argument(
        "--events-dir",
        type=str,
        default=os.environ.get("INTENT_EVENTS_DIR", "./events"),
        help="Directory containing event logs (default: ./events)",
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--low-confidence-threshold",
        type=float,
        default=0.4,
        help="Threshold for low confidence queries (default: 0.4)",
    )
    parser.add_argument(
        "--top-low-confidence",
        type=int,
        default=10,
        help="Number of low confidence queries to show (default: 10)",
    )

    args = parser.parse_args()

    events_dir = Path(args.events_dir)
    if not events_dir.exists():
        print(f"Error: Events directory not found: {events_dir}", file=sys.stderr)
        print("Hint: Set INTENT_TRACKING_ENABLED=1 to enable event logging.", file=sys.stderr)
        sys.exit(1)

    # Parse events
    events = parse_events(events_dir, days=args.days)

    if not events:
        print(f"No events found in {events_dir} for the last {args.days} days.", file=sys.stderr)
        print("Hint: Ensure INTENT_TRACKING_ENABLED=1 and queries are being made.", file=sys.stderr)
        sys.exit(0)

    # Analyze
    report = analyze_events(
        events,
        low_confidence_threshold=args.low_confidence_threshold,
        top_low_confidence=args.top_low_confidence,
    )

    # Output
    if args.output_format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report_text(report))


if __name__ == "__main__":
    main()
