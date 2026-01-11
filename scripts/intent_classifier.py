#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Semantic Intent Classifier for Query Routing

Uses embedding similarity to classify query intent, replacing brittle keyword matching.
Exemplar-based classification: embed query, compare to intent exemplars, pick best match.
"""

import os
import re
import logging
import threading
from typing import Dict, List, Optional, Tuple, Pattern
from enum import Enum

logger = logging.getLogger("intent_classifier")

# Try numpy for faster cosine similarity, fallback to pure Python
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


class QueryIntent(Enum):
    """Query intent categories for routing decisions."""
    GRAPH = "graph"           # Call graph, imports, dependencies
    SEMANTIC = "semantic"     # Conceptual, "how does X work"
    IDENTIFIER = "identifier" # Exact symbol lookup
    HYBRID = "hybrid"         # Mixed/unclear intent


# Exemplar queries for each intent - these define the semantic space
INTENT_EXEMPLARS: Dict[QueryIntent, List[str]] = {
    QueryIntent.GRAPH: [
        "who calls this function",
        "find all callers of this method",
        "what functions call get_user",
        "show me the call graph",
        "which modules import this",
        "find all usages of this symbol",
        "what are the dependencies of this module",
        "where is this function used",
        "show references to this class",
        "what imports this module",
        "find callers",
        "list all call sites",
        "which functions invoke this method",
        "what invokes the authenticate method",
    ],
    QueryIntent.SEMANTIC: [
        "how does authentication work",
        "explain the caching strategy",
        "what is the purpose of this module",
        "describe the error handling approach",
        "how are requests processed",
        "explain the architecture",
        "what design patterns are used",
        "why was this implemented this way",
    ],
    QueryIntent.IDENTIFIER: [
        "find function get_user",
        "where is AuthService defined",
        "locate the Config class",
        "find definition of parse_args",
        "show me the main function",
    ],
    QueryIntent.HYBRID: [
        "find error handling in auth module",
        "show database queries in user service",
        "find tests for login functionality",
    ],
}

# Confidence threshold - below this, fall back to HYBRID
CONFIDENCE_THRESHOLD = float(os.environ.get("INTENT_CONFIDENCE_THRESHOLD", "0.65"))

# Pre-compiled regex patterns for keyword fallback (compiled once at module load)
_GRAPH_PATTERNS: List[Pattern] = [
    re.compile(r"\bwho calls\b", re.IGNORECASE),
    re.compile(r"\bwhat calls\b", re.IGNORECASE),
    re.compile(r"\bcalled by\b", re.IGNORECASE),
    re.compile(r"\bcallers? of\b", re.IGNORECASE),
    re.compile(r"\bcallers? for\b", re.IGNORECASE),
    re.compile(r"\bcall graph\b", re.IGNORECASE),
    re.compile(r"\bcall sites?\b", re.IGNORECASE),
    re.compile(r"\busages? of\b", re.IGNORECASE),
    re.compile(r"\buses of\b", re.IGNORECASE),
    re.compile(r"\breferences? to\b", re.IGNORECASE),
    re.compile(r"\bimports?\b(?!\s+statement)", re.IGNORECASE),
    re.compile(r"\bimported by\b", re.IGNORECASE),
    re.compile(r"\bdependenc(?:y|ies) of\b", re.IGNORECASE),
    re.compile(r"\bdependents? of\b", re.IGNORECASE),
    re.compile(r"\bwhere is .+ used\b", re.IGNORECASE),
    re.compile(r"\bwhat imports\b", re.IGNORECASE),
    re.compile(r"\bwhich .+ imports?\b", re.IGNORECASE),
    re.compile(r"\binvokes?\b", re.IGNORECASE),  # "which functions invoke X"
    re.compile(r"\binvoked by\b", re.IGNORECASE),
    re.compile(r"\bwhich .+ (?:calls?|invokes?)\b", re.IGNORECASE),
]

_SEMANTIC_PATTERNS: List[Pattern] = [
    re.compile(r"\bhow does\b", re.IGNORECASE),
    re.compile(r"\bhow do\b", re.IGNORECASE),
    re.compile(r"\bexplain\b", re.IGNORECASE),
    re.compile(r"\bdescribe\b", re.IGNORECASE),
    re.compile(r"\bwhat is the purpose\b", re.IGNORECASE),
    re.compile(r"\bwhy is\b", re.IGNORECASE),
    re.compile(r"\bwhy does\b", re.IGNORECASE),
    re.compile(r"\barchitecture\b", re.IGNORECASE),
    re.compile(r"\bdesign pattern\b", re.IGNORECASE),
    re.compile(r"\bapproach\b", re.IGNORECASE),
]

# Cache for embedded exemplars with pre-computed norms
# Structure: {intent: [(embedding, norm), ...]}
_EXEMPLAR_EMBEDDINGS: Dict[QueryIntent, List[Tuple[List[float], float]]] = {}
_EXEMPLAR_LOCK = threading.Lock()
_EMBEDDER = None
_EMBEDDER_LOCK = threading.Lock()


def _get_embedder():
    """Lazy-load the embedding model."""
    global _EMBEDDER
    if _EMBEDDER is None:
        with _EMBEDDER_LOCK:
            if _EMBEDDER is None:
                try:
                    from scripts.embedder import get_embedding_model
                    _EMBEDDER = get_embedding_model()
                except Exception as e:
                    logger.warning(f"Failed to load embedder for intent classification: {e}")
                    return None
    return _EMBEDDER


def _embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts."""
    embedder = _get_embedder()
    if embedder is None:
        return []
    try:
        return [list(v) for v in embedder.embed(texts)]
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return []


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors. Uses numpy if available.

    Returns: float in [0.0, 1.0] (clamped from raw [-1, 1] range)
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    if _HAS_NUMPY:
        a_arr = np.array(a)
        b_arr = np.array(b)
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        raw = float(np.dot(a_arr, b_arr) / (norm_a * norm_b))
        return max(0.0, min(1.0, raw))  # Clamp to [0, 1]

    # Pure Python fallback
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    raw = dot / (norm_a * norm_b)
    return max(0.0, min(1.0, raw))  # Clamp to [0, 1]


def _compute_norm(vec: List[float]) -> float:
    """Compute L2 norm of a vector."""
    if _HAS_NUMPY:
        return float(np.linalg.norm(np.array(vec)))
    return sum(x * x for x in vec) ** 0.5


def _get_exemplar_embeddings() -> Dict[QueryIntent, List[Tuple[List[float], float]]]:
    """Get or compute cached exemplar embeddings with pre-computed norms.

    Returns: {intent: [(embedding, norm), ...]}
    Pre-computing norms eliminates ~50% of math per similarity comparison.
    """
    global _EXEMPLAR_EMBEDDINGS
    if not _EXEMPLAR_EMBEDDINGS:
        with _EXEMPLAR_LOCK:
            if not _EXEMPLAR_EMBEDDINGS:
                # Build a temporary dict first to avoid partial initialization on failure
                temp_embeddings: Dict[QueryIntent, List[Tuple[List[float], float]]] = {}
                failed_intents: List[QueryIntent] = []

                for intent, exemplars in INTENT_EXEMPLARS.items():
                    try:
                        embeddings = _embed_texts(exemplars)
                        if embeddings:
                            # Store (embedding, pre-computed norm) tuples
                            temp_embeddings[intent] = [
                                (emb, _compute_norm(emb)) for emb in embeddings
                            ]
                        else:
                            failed_intents.append(intent)
                            logger.warning(f"Failed to get embeddings for intent {intent.value}")
                    except Exception as e:
                        failed_intents.append(intent)
                        logger.warning(f"Error computing embeddings for intent {intent.value}: {e}")

                # Only assign if we got at least some embeddings
                if temp_embeddings:
                    _EXEMPLAR_EMBEDDINGS = temp_embeddings
                    total = sum(len(v) for v in _EXEMPLAR_EMBEDDINGS.values())
                    logger.info(f"Cached {total} intent exemplar embeddings with pre-computed norms")
                    if failed_intents:
                        failed_names = [i.value for i in failed_intents]
                        logger.warning(f"Failed to initialize embeddings for intents: {failed_names}")
                else:
                    logger.warning("Failed to initialize any exemplar embeddings")

    return _EXEMPLAR_EMBEDDINGS


def _cosine_similarity_prenorm(query_vec: List[float], query_norm: float,
                                exemplar_vec: List[float], exemplar_norm: float) -> float:
    """Compute cosine similarity using pre-computed norms for exemplar.

    Args:
        query_vec: Query embedding
        query_norm: Pre-computed L2 norm of query
        exemplar_vec: Exemplar embedding
        exemplar_norm: Pre-computed L2 norm of exemplar (from cache)

    Returns: float in [0.0, 1.0]
    """
    if query_norm == 0 or exemplar_norm == 0:
        return 0.0

    if _HAS_NUMPY:
        dot = float(np.dot(np.array(query_vec), np.array(exemplar_vec)))
    else:
        dot = sum(x * y for x, y in zip(query_vec, exemplar_vec))

    raw = dot / (query_norm * exemplar_norm)
    return max(0.0, min(1.0, raw))


def classify_intent(query: str) -> Tuple[QueryIntent, float, bool]:
    """
    Classify query intent using semantic similarity to exemplars.

    Args:
        query: The user's search query

    Returns:
        Tuple of (QueryIntent, confidence_score, fallback_used)
        - fallback_used: True if keyword fallback was used (embeddings unavailable)
        If confidence < threshold, returns (HYBRID, score, False)
    """
    if not query or not query.strip():
        return QueryIntent.HYBRID, 0.0, False

    # Embed the query
    query_embeddings = _embed_texts([query.strip()])
    if not query_embeddings:
        # Fallback to keyword matching if embedding fails
        intent, score = _keyword_fallback(query)
        return intent, score, True

    query_vec = query_embeddings[0]
    query_norm = _compute_norm(query_vec)  # Compute once for all comparisons

    exemplar_embeddings = _get_exemplar_embeddings()

    if not exemplar_embeddings:
        intent, score = _keyword_fallback(query)
        return intent, score, True

    # Find best matching intent using pre-computed exemplar norms
    best_intent = QueryIntent.HYBRID
    best_score = 0.0

    for intent, emb_norm_pairs in exemplar_embeddings.items():
        # Max similarity across exemplars for this intent
        for emb, emb_norm in emb_norm_pairs:
            sim = _cosine_similarity_prenorm(query_vec, query_norm, emb, emb_norm)
            if sim > best_score:
                best_score = sim
                best_intent = intent

    # Apply confidence threshold
    if best_score < CONFIDENCE_THRESHOLD:
        return QueryIntent.HYBRID, best_score, False

    return best_intent, best_score, False


def _keyword_fallback(query: str) -> Tuple[QueryIntent, float]:
    """
    Fallback to keyword matching when embeddings unavailable.
    Returns lower confidence scores to indicate fallback was used.
    Uses pre-compiled regex patterns for performance.
    """
    q = query  # Patterns are already case-insensitive

    # Graph indicators with word boundaries (most specific, check first)
    # Pre-compiled at module load for performance
    if any(p.search(q) for p in _GRAPH_PATTERNS):
        return QueryIntent.GRAPH, 0.5

    # Semantic indicators (pre-compiled)
    if any(p.search(q) for p in _SEMANTIC_PATTERNS):
        return QueryIntent.SEMANTIC, 0.5

    # Identifier patterns: must look like code symbols, not natural language
    # - Single word with underscores/dots: get_user, auth.config
    # - CamelCase: AuthService, UserManager
    # - NOT "login page" (two plain words)
    words = q.lower().split()
    if len(words) == 1:
        w = words[0]
        # Must contain underscore, dot, or be CamelCase-like
        if '_' in q or '.' in q or (q[0].isupper() and any(c.isupper() for c in q[1:])):
            if w.replace("_", "").replace(".", "").isalnum():
                return QueryIntent.IDENTIFIER, 0.4

    return QueryIntent.HYBRID, 0.3


def reset_exemplar_cache() -> None:
    """Reset cached embeddings (useful for testing or model changes)."""
    global _EXEMPLAR_EMBEDDINGS, _EMBEDDER
    with _EXEMPLAR_LOCK:
        _EXEMPLAR_EMBEDDINGS = {}
    with _EMBEDDER_LOCK:
        _EMBEDDER = None


def is_graph_intent(query: str, threshold: float = CONFIDENCE_THRESHOLD) -> bool:
    """Check if query has graph intent above threshold.

    When using keyword fallback (embedder unavailable), trusts the fallback
    result without applying the semantic threshold.
    """
    intent, score, fallback_used = classify_intent(query)

    # If keyword fallback was used, trust it directly
    # Fallback returns 0.5 for GRAPH which is below default 0.65 threshold
    if fallback_used:
        return intent == QueryIntent.GRAPH

    return intent == QueryIntent.GRAPH and score >= threshold

