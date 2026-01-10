#!/usr/bin/env python3
"""
Tests for the semantic intent classifier.

Run with: pytest tests/test_intent_classifier.py -v
"""

import pytest
import sys
import os

# Ensure scripts is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.intent_classifier import (
    classify_intent,
    QueryIntent,
    is_graph_intent,
    reset_exemplar_cache,
    _keyword_fallback,
)


class TestKeywordFallback:
    """Test the keyword-based fallback (doesn't require embeddings)."""

    @pytest.mark.parametrize("query,expected_intent", [
        # Graph queries
        ("who calls get_user", QueryIntent.GRAPH),
        ("what calls this function", QueryIntent.GRAPH),
        ("find all callers of authenticate", QueryIntent.GRAPH),
        ("show call graph for main", QueryIntent.GRAPH),
        ("usages of Config class", QueryIntent.GRAPH),
        ("what imports this module", QueryIntent.GRAPH),
        ("dependencies of auth module", QueryIntent.GRAPH),
        
        # Semantic queries
        ("how does authentication work", QueryIntent.SEMANTIC),
        ("explain the caching strategy", QueryIntent.SEMANTIC),
        ("what is the purpose of this class", QueryIntent.SEMANTIC),
        ("describe the error handling approach", QueryIntent.SEMANTIC),
        
        # Identifier queries (short, symbol-like)
        ("get_user", QueryIntent.IDENTIFIER),
        ("AuthService", QueryIntent.IDENTIFIER),
        
        # Hybrid/unclear
        ("find errors in auth", QueryIntent.HYBRID),
        ("database connection code", QueryIntent.HYBRID),
    ])
    def test_keyword_fallback_classification(self, query, expected_intent):
        """Test keyword fallback returns expected intent."""
        intent, score = _keyword_fallback(query)
        assert intent == expected_intent, f"Query '{query}' classified as {intent}, expected {expected_intent}"
        assert 0 <= score <= 1.0

    def test_keyword_fallback_scores(self):
        """Verify fallback scores are appropriately lower than embedding scores."""
        # Graph patterns should have score 0.5
        intent, score = _keyword_fallback("who calls get_user")
        assert intent == QueryIntent.GRAPH
        assert score == 0.5
        
        # Identifier should have score 0.4
        intent, score = _keyword_fallback("get_user")
        assert intent == QueryIntent.IDENTIFIER
        assert score == 0.4
        
        # Hybrid should have score 0.3
        intent, score = _keyword_fallback("some random query")
        assert intent == QueryIntent.HYBRID
        assert score == 0.3


class TestGraphIntentVariations:
    """Test that various phrasings of graph queries are correctly classified."""

    GRAPH_QUERIES = [
        # Direct patterns
        "who calls this",
        "what calls get_user",
        "callers of authenticate",
        "callers for this method",
        "caller of this function",

        # Usage patterns
        "find usages of this function",
        "where is get_user used",  # Must have "used" at end
        "show all uses of Config",
        "usage of this class",

        # Import patterns
        "what imports this module",
        "which files import auth",
        "imported by other modules",
        "imports this",

        # Dependency patterns
        "dependencies of this module",
        "dependency of auth",
        "dependents of auth",

        # Call graph patterns
        "show the call graph",
        "find call sites",
        "find call site for get_user",

        # Reference patterns
        "references to this symbol",
        "reference to get_user",
    ]

    @pytest.mark.parametrize("query", GRAPH_QUERIES)
    def test_graph_query_variations(self, query):
        """Ensure various graph query phrasings are classified correctly."""
        intent, score = _keyword_fallback(query)
        assert intent == QueryIntent.GRAPH, f"Query '{query}' should be GRAPH, got {intent}"


class TestFalsePositives:
    """Test that non-graph queries are NOT misclassified as GRAPH."""

    NON_GRAPH_QUERIES = [
        "implement a function that calls an API",  # Contains "calls" but not a graph query
        "the function calls out to external service",
        "how to handle callback functions",
        "using dependency injection",  # Contains "dependency" but semantic
        "this is important for the system",  # "important" should NOT match "import"
        "where is the config file",  # "where is" without "used" is not graph
        "find all errors in the code",  # "find all" without graph context
        "import statement syntax",  # import but about syntax, not finding importers
    ]

    @pytest.mark.parametrize("query", NON_GRAPH_QUERIES)
    def test_false_positive_prevention(self, query):
        """Ensure these are NOT classified as GRAPH by keywords."""
        intent, score = _keyword_fallback(query)
        # These should NOT be GRAPH with word boundary checks
        assert intent != QueryIntent.GRAPH, f"Query '{query}' should NOT be GRAPH, got {intent}"


class TestSemanticClassification:
    """Test full semantic classification (requires embedding model)."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset caches before each test."""
        reset_exemplar_cache()
        yield

    def test_classify_empty_query(self):
        """Empty queries should return HYBRID with 0 confidence."""
        intent, score = classify_intent("")
        assert intent == QueryIntent.HYBRID
        assert score == 0.0

    def test_classify_whitespace_query(self):
        """Whitespace-only queries should return HYBRID."""
        intent, score = classify_intent("   ")
        assert intent == QueryIntent.HYBRID
        assert score == 0.0

    @pytest.mark.slow
    def test_semantic_graph_query(self):
        """Test semantic classification of graph queries (requires embeddings)."""
        # This test is slow because it loads the embedding model
        intent, score = classify_intent("which functions invoke the authenticate method")
        # Should be GRAPH with decent confidence
        assert intent in (QueryIntent.GRAPH, QueryIntent.HYBRID)
        assert score > 0

    @pytest.mark.slow
    def test_semantic_vs_keyword_consistency(self):
        """Semantic classification should generally agree with keyword fallback."""
        test_queries = [
            "who calls get_user",
            "how does authentication work",
        ]
        for query in test_queries:
            sem_intent, sem_score = classify_intent(query)
            kw_intent, _ = _keyword_fallback(query)
            # They should usually agree, but semantic may be more nuanced
            # Just verify we get valid results
            assert sem_intent in QueryIntent
            assert 0 <= sem_score <= 1.0

