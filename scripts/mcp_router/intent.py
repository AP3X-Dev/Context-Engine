"""
mcp_router/intent.py - Intent classification for MCP tool routing.

Classifies user queries into specific tool intents (12+ categories) using
rules-first with ML fallback. Returns a string intent constant.

NOTE: This module handles TOOL-LEVEL intent for MCP tool dispatch.
For RETRIEVAL-LEVEL intent (4 categories: GRAPH, SEMANTIC, IDENTIFIER, HYBRID),
see scripts/intent_classifier.py which tunes search strategy in QueryOptimizer.

The split is intentional:
- Router intent (this file): fine-grained tool selection → returns str
- Retrieval intent: broad search strategy → returns Tuple[QueryIntent, float, bool]

Intents handled here:
  answer, search, search_tests, search_config, search_callers, search_importers,
  memory_store, memory_find, symbol_graph, index, prune, status, list
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import fcntl
import threading
from pathlib import Path
from typing import Any, Dict, List

# Intent constants

logger = logging.getLogger(__name__)
INTENT_ANSWER = "answer"
INTENT_SEARCH = "search"
INTENT_SEARCH_TESTS = "search_tests"
INTENT_SEARCH_CONFIG = "search_config"
INTENT_SEARCH_CALLERS = "search_callers"
INTENT_SEARCH_IMPORTERS = "search_importers"
INTENT_MEMORY_STORE = "memory_store"
INTENT_MEMORY_FIND = "memory_find"
INTENT_SYMBOL_GRAPH = "symbol_graph"
INTENT_INDEX = "index"
INTENT_PRUNE = "prune"
INTENT_STATUS = "status"
INTENT_LIST = "list"

# Default ML confidence threshold (fallback to SEARCH if below)
_DEFAULT_ML_THRESHOLD = float(os.environ.get("INTENT_ML_THRESHOLD", "0.25"))

# Per-intent confidence thresholds (override default)
# Lower = more permissive, higher = stricter classification
# Rationale:
#   - symbol_graph: very distinctive queries ("who calls X"), lower threshold
#   - answer: expensive LLM call, require higher confidence
#   - memory_store: irreversible action, require higher confidence
#   - search: default fallback, moderate threshold
_INTENT_THRESHOLDS: Dict[str, float] = {
    INTENT_SYMBOL_GRAPH: float(os.environ.get("INTENT_THRESHOLD_SYMBOL_GRAPH", "0.20")),
    INTENT_SEARCH_CALLERS: float(os.environ.get("INTENT_THRESHOLD_SEARCH_CALLERS", "0.20")),
    INTENT_SEARCH_IMPORTERS: float(os.environ.get("INTENT_THRESHOLD_SEARCH_IMPORTERS", "0.22")),
    INTENT_SEARCH_TESTS: float(os.environ.get("INTENT_THRESHOLD_SEARCH_TESTS", "0.22")),
    INTENT_SEARCH_CONFIG: float(os.environ.get("INTENT_THRESHOLD_SEARCH_CONFIG", "0.22")),
    INTENT_ANSWER: float(os.environ.get("INTENT_THRESHOLD_ANSWER", "0.30")),
    INTENT_MEMORY_STORE: float(os.environ.get("INTENT_THRESHOLD_MEMORY_STORE", "0.35")),
    INTENT_MEMORY_FIND: float(os.environ.get("INTENT_THRESHOLD_MEMORY_FIND", "0.25")),
    INTENT_SEARCH: float(os.environ.get("INTENT_THRESHOLD_SEARCH", "0.25")),
}


def get_intent_threshold(intent: str) -> float:
    """Get the confidence threshold for a specific intent."""
    return _INTENT_THRESHOLDS.get(intent, _DEFAULT_ML_THRESHOLD)

# Debug state
_LAST_INTENT_DEBUG: Dict[str, Any] = {}


def get_last_intent_debug() -> Dict[str, Any]:
    """Get the last intent debug info."""
    return _LAST_INTENT_DEBUG


def _classify_intent_rules(q: str) -> str | None:
    s = q.lower()
    # Admin / maintenance first
    if any(w in s for w in ["reindex", "reset", "recreate", "index now", "fresh index"]):
        return INTENT_INDEX
    if any(w in s for w in ["prune", "pruning", "cleanup", "clean up"]):
        return INTENT_PRUNE
    if any(w in s for w in ["status", "health", "points", "stats"]):
        return INTENT_STATUS
    if any(w in s for w in ["list collections", "collections", "list qdrant"]):
        return INTENT_LIST

    # Search importers - check BEFORE tests to avoid "import" in test queries
    if any(w in s for w in ["import", "imports", "importers", "who imports", "imports this", "importing modules", "files that import"]):
        # Make sure it's not about "important" or similar
        if not any(w in s for w in ["important", "importance"]):
            return INTENT_SEARCH_IMPORTERS

    # Intent wrappers
    if any(w in s for w in ["tests", "pytest", "unit test", "test file", "where are tests"]):
        return INTENT_SEARCH_TESTS
    
    # Memory intents - be more specific to avoid false positives on "memory store implementation"
    # Check for actual user-intent memory storage, not code references
    memory_store_triggers = [
        "remember this", "save memory", "store memory", "remember that", 
        "save preference", "remember preference", "store a note", "save a note", "remember note"
    ]
    # IMPORTANT: "memory store" as a phrase often refers to code, not user intent
    if any(w in s for w in memory_store_triggers):
        # Exclude if it looks like a code search (has "implementation", "code", "function", etc)
        if not any(exc in s for exc in ["implementation", "code", "function", "class", "module", "file", "search for"]):
            return INTENT_MEMORY_STORE
    if any(w in s for w in [
        "find memory", "recall", "retrieve memory", "memory search", "what did we save",
        "recall notes", "find notes", "retrieve notes"
    ]):
        return INTENT_MEMORY_FIND

    # Symbol graph for callers - check BEFORE config to avoid false positives
    if any(w in s for w in ["who calls", "callers of", "call sites", "function calls"]):
        return INTENT_SYMBOL_GRAPH
    if re.search(r"calls?\s+(the\s+)?\w+\s*(function|method)?", s):
        return INTENT_SYMBOL_GRAPH

    # Config search - after callers check
    if any(w in s for w in ["config", "yaml", "toml", "ini", "settings file", "configuration"]):
        return INTENT_SEARCH_CONFIG
    
    # Fallback callers intent (used by search_callers_for)
    if any(w in s for w in ["used by", "usage sites", "references this function"]):
        return INTENT_SEARCH_CALLERS

    # Q&A-like prompts
    if re.match(r"^(what|how|why|explain|describe|summarize)(\b|\s)", s):
        return INTENT_ANSWER
    if any(w in s for w in ["recap", "design doc", "architecture", "adr", "retrospective", "postmortem", "summary of", "summarize the design"]):
        return INTENT_ANSWER
    return None


def _intent_prototypes() -> Dict[str, List[str]]:
    return {
        INTENT_ANSWER: [
            "explain, describe, summarize, recap, design, architecture, ADR, why/how",
            "summarize design decisions and architecture rationale",
        ],
        INTENT_SEARCH: [
            "find code references, search repository, locate files, find implementation",
            "code search in repo, general lookup, search for implementation",
            "find module, search function, locate class definition",
            "search for memory store implementation",  # Explicit example
        ],
        INTENT_MEMORY_STORE: [
            "remember this preference, save this note for later, store this memory",
            "save my preference, remember that for next time",
            # NOT: search for, find, implementation, code
        ],
        INTENT_MEMORY_FIND: [
            "what did we save, recall saved notes, retrieve memory, find my saved notes",
        ],
        INTENT_SEARCH_TESTS: [
            "find unit tests, test files, pytest, testing modules",
        ],
        INTENT_SEARCH_CONFIG: [
            "config files, configuration changes, yaml toml ini settings",
        ],
        INTENT_SEARCH_CALLERS: [
            "who calls this function, callers, usage sites, where is it used",
        ],
        INTENT_SEARCH_IMPORTERS: [
            "who imports this module, importers, importing modules, files that import",
        ],
        INTENT_SYMBOL_GRAPH: [
            "who calls this function, callers of, call graph, symbol callers",
        ],
    }


def _cosine(a: list[float], b: list[float]) -> float:
    """Lightweight cosine similarity."""
    try:
        s = 0.0
        na = 0.0
        nb = 0.0
        for i in range(min(len(a), len(b))):
            va = float(a[i])
            vb = float(b[i])
            s += va * vb
            na += va * va
            nb += vb * vb
        na = (na or 1.0) ** 0.5
        nb = (nb or 1.0) ** 0.5
        return s / (na * nb)
    except Exception:
        return 0.0


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts using available embedding model."""
    if not texts:
        return []

    # Try centralized embedder factory first
    try:
        from scripts.embedder import get_embedding_model
        model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
        em = get_embedding_model(model_name)
        raw = list(em.embed(texts))
        return [v.tolist() if hasattr(v, "tolist") else list(v) for v in raw]
    except ImportError:
        pass

    # Try fastembed directly
    try:
        from fastembed import TextEmbedding
        model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
        em = TextEmbedding(model_name=model_name)
        raw = list(em.embed(texts))
        return [v.tolist() if hasattr(v, "tolist") else list(v) for v in raw]
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Fallback to lexical
    try:
        from scripts.utils import lex_hash_vector_text
        return [lex_hash_vector_text(t, dim=4096) for t in texts]
    except Exception:
        return [[float(len(t))] for t in texts]


def _classify_intent_ml(q: str) -> str:
    global _LAST_INTENT_DEBUG
    protos = _intent_prototypes()
    labels = list(protos.keys())
    texts = [q] + ["\n".join(protos[l]) for l in labels]
    vecs = _embed_texts(texts)
    if not vecs or len(vecs) < len(texts):
        _LAST_INTENT_DEBUG = {
            "strategy": "ml",
            "intent": INTENT_SEARCH,
            "confidence": 0.0,
            "query": q,
            "top_candidate": INTENT_SEARCH,
            "top_score": 0.0,
            "threshold": _DEFAULT_ML_THRESHOLD,
            "candidates": [],
            "reason": "embed_failed",
            "timestamp": time.time(),
        }
        return INTENT_SEARCH
    qv = vecs[0]
    sims = []
    for i, lab in enumerate(labels):
        sims.append((lab, _cosine(qv, vecs[1 + i])))
    sims.sort(key=lambda x: x[1], reverse=True)
    top, score = sims[0]

    # Use per-intent threshold instead of hard-coded 0.25
    threshold = get_intent_threshold(top)
    picked = top if score >= threshold else INTENT_SEARCH

    _LAST_INTENT_DEBUG = {
        "strategy": "ml",
        "intent": picked,
        "confidence": float(score),
        "query": q,
        "top_candidate": top,
        "top_score": float(score),
        "threshold": threshold,
        "candidates": [(name, float(val)) for name, val in sims[:5]],
        "fallback": picked == INTENT_SEARCH and top != INTENT_SEARCH,
        "timestamp": time.time(),
    }
    return picked


# Thread-safe event buffer for high-throughput logging
_EVENT_BUFFER: List[dict] = []
_EVENT_BUFFER_LOCK = threading.Lock()
_EVENT_BUFFER_MAX = 100  # Flush when buffer reaches this size
_EVENT_FLUSH_INTERVAL = 5.0  # Flush every N seconds
_EVENT_LAST_FLUSH = 0.0


def _flush_event_buffer() -> None:
    """Flush buffered events to disk (called periodically or when buffer is full)."""
    global _EVENT_LAST_FLUSH

    with _EVENT_BUFFER_LOCK:
        if not _EVENT_BUFFER:
            return
        events_to_write = _EVENT_BUFFER.copy()
        _EVENT_BUFFER.clear()
        _EVENT_LAST_FLUSH = time.time()

    try:
        log_dir = Path(os.environ.get("INTENT_EVENTS_DIR", "./events"))
        log_dir.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"intent_confidence_{date_str}.jsonl"

        # Check file size for rotation
        max_size_mb = int(os.environ.get("INTENT_LOG_ROTATE_MB", "100") or 100)
        if log_file.exists():
            size_mb = log_file.stat().st_size / (1024 * 1024)
            if size_mb >= max_size_mb:
                for i in range(9, 0, -1):
                    old_file = log_dir / f"intent_confidence_{date_str}.jsonl.{i}"
                    new_file = log_dir / f"intent_confidence_{date_str}.jsonl.{i+1}"
                    if old_file.exists():
                        old_file.rename(new_file)
                log_file.rename(log_dir / f"intent_confidence_{date_str}.jsonl.1")

        # Write all buffered events at once (single lock acquisition)
        with open(log_file, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                for event in events_to_write:
                    f.write(json.dumps(event) + "\n")
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Intent flush error: {e}", file=sys.stderr)


def _log_intent_event(event: dict) -> None:
    """Buffer intent classification event for batched writing.

    Uses in-memory buffer with periodic flush for high-throughput scenarios.
    At 1000 repos / high QPS, this avoids per-event file lock contention.

    Args:
        event: Event dict with timestamp, query, intent, confidence, strategy, etc.
    """
    global _EVENT_LAST_FLUSH

    tracking_enabled = os.environ.get("INTENT_TRACKING_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
    if not tracking_enabled:
        return

    try:
        with _EVENT_BUFFER_LOCK:
            _EVENT_BUFFER.append(event)
            buffer_full = len(_EVENT_BUFFER) >= _EVENT_BUFFER_MAX
            time_to_flush = (time.time() - _EVENT_LAST_FLUSH) > _EVENT_FLUSH_INTERVAL

        # Flush if buffer full or interval elapsed
        if buffer_full or time_to_flush:
            # Use a thread to avoid blocking the request path
            # NOTE: For tests, call _flush_event_buffer() directly after _log_intent_event()
            t = threading.Thread(target=_flush_event_buffer, daemon=True)
            t.start()
            # Give the thread a brief moment to start (non-blocking for production)
            # This ensures test assertions find the file
            if os.environ.get("INTENT_FLUSH_SYNC"):
                t.join(timeout=1.0)

    except Exception as e:
        # Never fail the request due to logging
        print(f"Intent logging error: {e}", file=sys.stderr)


def classify_intent(q: str) -> str:
    """Classify user query into an intent and log the event."""
    global _LAST_INTENT_DEBUG
    ruled = _classify_intent_rules(q)

    if ruled is not None:
        _LAST_INTENT_DEBUG = {
            "strategy": "rules",
            "intent": ruled,
            "confidence": 1.0,
            "query": q,
            "timestamp": time.time(),
        }
        # Log event
        _log_intent_event({
            "timestamp": _LAST_INTENT_DEBUG["timestamp"],
            "query": q,
            "intent": ruled,
            "confidence": 1.0,
            "strategy": "rules",
            "threshold": None,
            "candidates": [],
        })
        return ruled

    picked = _classify_intent_ml(q)

    # Log ML classification event
    if isinstance(_LAST_INTENT_DEBUG, dict):
        event = {
            "timestamp": _LAST_INTENT_DEBUG.get("timestamp", time.time()),
            "query": q,
            "intent": picked,
            "confidence": _LAST_INTENT_DEBUG.get("confidence", 0.0),
            "strategy": _LAST_INTENT_DEBUG.get("strategy", "ml"),
            "threshold": _LAST_INTENT_DEBUG.get("threshold", 0.25),
            "candidates": _LAST_INTENT_DEBUG.get("candidates", [])[:5],  # Top 5 only
        }
        _log_intent_event(event)

        # Debug output
        try:
            if os.environ.get("DEBUG_ROUTER") and _LAST_INTENT_DEBUG.get("fallback"):
                print(json.dumps({"router": {"intent_fallback": _LAST_INTENT_DEBUG}}), file=sys.stderr)
        except Exception as e:
            logger.debug(f"Suppressed exception: {e}")

    return picked
