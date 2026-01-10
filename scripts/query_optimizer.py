#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Dynamic Query Performance Optimizer

Implements adaptive HNSW_EF tuning and intelligent query routing to optimize
retrieval performance based on query complexity and collection characteristics.
"""

import os
import re
import time
import math
import threading
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger("query_optimizer")


class QueryType(Enum):
    """Classification of query types for optimized routing."""
    SIMPLE = "simple"  # Simple keyword, exact match likely
    SEMANTIC = "semantic"  # Natural language, needs deep search
    COMPLEX = "complex"  # Multi-faceted, benefits from extensive search
    HYBRID = "hybrid"  # Mix of keywords and semantic
    GRAPH = "graph"  # NEW: Queries benefiting from graph navigation (call/importer)


@dataclass
class QueryProfile:
    """Profile of a query for optimization decisions."""
    query: str
    query_type: QueryType
    complexity_score: float
    recommended_ef: int
    use_dense_only: bool
    estimated_latency_ms: float
    suggested_mode: str = "hybrid"  # NEW: hybrid, graph_guided, semantic_only, multi_granular


@dataclass
class OptimizationStats:
    """Statistics for monitoring optimizer performance."""
    total_queries: int = 0
    simple_queries: int = 0
    semantic_queries: int = 0
    complex_queries: int = 0
    hybrid_queries: int = 0
    avg_ef_used: float = 0.0
    total_latency_ms: float = 0.0
    cache_hits: int = 0


class QueryOptimizer:
    """
    Adaptive query optimizer that dynamically tunes HNSW_EF and routing.
    
    Features:
    - Query complexity analysis
    - Dynamic HNSW_EF calculation based on query type
    - Intelligent routing between dense and hybrid search
    - Performance monitoring and adaptive learning
    """
    
    def __init__(
        self,
        base_ef: int = 128,
        min_ef: int = 64,
        max_ef: int = 512,
        collection_size: int = 10000,
        enable_adaptive: bool = True
    ):
        """
        Initialize the query optimizer.
        
        Args:
            base_ef: Default HNSW_EF value
            min_ef: Minimum allowed EF value
            max_ef: Maximum allowed EF value
            collection_size: Approximate collection size for scaling
            enable_adaptive: Enable adaptive EF tuning
        """
        self.base_ef = base_ef
        self.min_ef = min_ef
        self.max_ef = max_ef
        self.collection_size = collection_size
        self.enable_adaptive = enable_adaptive
        
        # Statistics tracking
        self.stats = OptimizationStats()
        self._query_cache: Dict[str, QueryProfile] = {}
        self._performance_history: List[Tuple[float, int, float]] = []  # (complexity, ef, latency)
        
        # Load configuration from environment
        self._load_config()
        
        logger.info(
            f"QueryOptimizer initialized: base_ef={base_ef}, range=[{min_ef}, {max_ef}], "
            f"adaptive={enable_adaptive}"
        )
    
    def _load_config(self):
        """Load optimizer configuration from environment variables."""
        self.enable_adaptive = os.environ.get("QUERY_OPTIMIZER_ADAPTIVE", "1").lower() in {
            "1", "true", "yes", "on"
        }
        
        # Complexity thresholds for query classification
        self.simple_threshold = float(os.environ.get("QUERY_OPTIMIZER_SIMPLE_THRESHOLD", "0.3") or 0.3)
        self.complex_threshold = float(os.environ.get("QUERY_OPTIMIZER_COMPLEX_THRESHOLD", "0.7") or 0.7)
        
        # EF scaling factors
        self.simple_ef_factor = float(os.environ.get("QUERY_OPTIMIZER_SIMPLE_FACTOR", "0.5") or 0.5)
        self.semantic_ef_factor = float(os.environ.get("QUERY_OPTIMIZER_SEMANTIC_FACTOR", "1.0") or 1.0)
        self.complex_ef_factor = float(os.environ.get("QUERY_OPTIMIZER_COMPLEX_FACTOR", "2.0") or 2.0)
        
        # Dense-only routing threshold (lower complexity = prefer dense)
        self.dense_only_threshold = float(os.environ.get("QUERY_OPTIMIZER_DENSE_THRESHOLD", "0.2") or 0.2)
        
        if os.environ.get("DEBUG_QUERY_OPTIMIZER"):
            logger.debug(f"Optimizer config loaded: adaptive={self.enable_adaptive}, thresholds=({self.simple_threshold}, {self.complex_threshold})")
    
    def analyze_query(self, query: str, language: Optional[str] = None) -> QueryProfile:
        """
        Analyze query and generate optimization profile.
        
        Args:
            query: Query string to analyze
            language: Optional programming language hint
        
        Returns:
            QueryProfile with optimization recommendations
        """
        # Check cache first
        cache_key = f"{query}:{language or ''}"
        if cache_key in self._query_cache:
            self.stats.cache_hits += 1
            return self._query_cache[cache_key]
        
        # Calculate complexity score
        complexity = self._calculate_complexity(query, language)
        
        # Classify query type
        query_type = self._classify_query(query, complexity)
        
        # Calculate optimal EF
        recommended_ef = self._calculate_optimal_ef(complexity, query_type)
        
        # Decide on routing
        use_dense_only = self._should_use_dense_only(query, complexity, query_type)
        
        # Decide on suggested mode (Unified Router logic)
        suggested_mode = "hybrid"
        if query_type == QueryType.GRAPH:
            suggested_mode = "graph_guided"
        elif query_type == QueryType.SEMANTIC and complexity > 0.8:
            suggested_mode = "multi_granular"
        elif use_dense_only:
            suggested_mode = "semantic_only"
        
        # Estimate latency (rough heuristic)
        estimated_latency = self._estimate_latency(complexity, recommended_ef, use_dense_only)
        
        profile = QueryProfile(
            query=query,
            query_type=query_type,
            complexity_score=complexity,
            recommended_ef=recommended_ef,
            use_dense_only=use_dense_only,
            estimated_latency_ms=estimated_latency,
            suggested_mode=suggested_mode
        )
        
        # Cache the profile
        if len(self._query_cache) < 1000:  # Limit cache size
            self._query_cache[cache_key] = profile
        
        # Update stats
        self.stats.total_queries += 1
        if query_type == QueryType.SIMPLE:
            self.stats.simple_queries += 1
        elif query_type == QueryType.SEMANTIC:
            self.stats.semantic_queries += 1
        elif query_type == QueryType.COMPLEX:
            self.stats.complex_queries += 1
        elif query_type == QueryType.GRAPH:
            # We don't have a stat for graph yet, use complex as proxy for now
            self.stats.complex_queries += 1
        else:
            self.stats.hybrid_queries += 1
        
        if os.environ.get("DEBUG_QUERY_OPTIMIZER"):
            logger.debug(
                f"Query analyzed: type={query_type.value}, complexity={complexity:.3f}, "
                f"ef={recommended_ef}, dense_only={use_dense_only}, suggested_mode={suggested_mode}"
            )
        
        return profile
    
    def _calculate_complexity(self, query: str, language: Optional[str] = None) -> float:
        """
        Calculate query complexity score (0.0 to 1.0).
        
        Higher scores indicate more complex queries needing deeper search.
        
        Factors:
        - Query length (longer = more complex)
        - Number of terms
        - Natural language indicators (questions, connectors)
        - Code-specific patterns (operators, symbols)
        - Language-specific keywords
        """
        score = 0.0
        query_lower = query.lower().strip()
        
        # 1. Length factor (normalize to ~100 chars)
        length_score = min(len(query) / 100.0, 1.0)
        score += length_score * 0.2
        
        # 2. Term count (more terms = more complex)
        terms = re.findall(r'\b\w+\b', query)
        term_score = min(len(terms) / 10.0, 1.0)
        score += term_score * 0.15
        
        # 3. Natural language indicators
        question_words = ['what', 'how', 'why', 'when', 'where', 'which', 'who', 'explain', 'describe']
        if any(word in query_lower for word in question_words):
            score += 0.2
        
        # Connectors indicate complex multi-part queries
        connectors = ['and', 'or', 'but', 'with', 'that', 'also', 'including']
        connector_count = sum(1 for word in connectors if f' {word} ' in f' {query_lower} ')
        score += min(connector_count * 0.1, 0.2)
        
        # 4. Code-specific complexity
        # Special characters often mean precise searches
        special_chars = len(re.findall(r'[(){}[\]<>.:;,]', query))
        if special_chars > 0:
            score -= 0.1  # Special chars = more specific = simpler
        
        # CamelCase or snake_case (likely looking for specific symbols)
        if re.search(r'[A-Z][a-z]+[A-Z]', query) or '_' in query:
            score -= 0.1
        
        # Quoted strings (exact matches)
        if '"' in query or "'" in query:
            score -= 0.15
        
        # 5. Language-specific adjustments
        if language:
            # If language specified, query is more focused
            score -= 0.1
        
        # 6. Regex patterns (very specific)
        if re.search(r'[*+?\\|^$]', query):
            score -= 0.15
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))
    
    def _classify_query(self, query: str, complexity: float) -> QueryType:
        """Classify query type based on complexity and patterns."""
        query_lower = query.lower().strip()

        # Simple: Low complexity, likely exact match
        if complexity < self.simple_threshold:
            # Extra checks for simple patterns
            if re.match(r'^[a-z_][a-z0-9_]*$', query_lower):  # Single identifier
                return QueryType.SIMPLE
            if len(query.split()) <= 2 and not any(c in query for c in '(){}[]'):
                return QueryType.SIMPLE

        # FIX: Check GRAPH intent BEFORE complexity threshold
        # Uses semantic classifier with fallback to keyword matching
        try:
            from scripts.intent_classifier import classify_intent, QueryIntent
            intent, confidence = classify_intent(query)
            if intent == QueryIntent.GRAPH and confidence >= 0.5:
                return QueryType.GRAPH
        except ImportError:
            # Fallback to simple keyword matching if classifier unavailable
            graph_indicators = ['who calls', 'what calls', 'called by', 'callers of',
                               'usages of', 'imports', 'imported by', 'dependencies of']
            if any(ind in query_lower for ind in graph_indicators):
                return QueryType.GRAPH

        # Complex: High complexity, multi-faceted (after graph check)
        if complexity > self.complex_threshold:
            return QueryType.COMPLEX

        # Semantic: Natural language questions
        question_indicators = ['what', 'how', 'why', 'explain', 'describe', 'show me', 'find all']
        if any(query_lower.startswith(ind) for ind in question_indicators):
            return QueryType.SEMANTIC

        # Hybrid: Everything else
        return QueryType.HYBRID
    
    def _calculate_optimal_ef(self, complexity: float, query_type: QueryType) -> int:
        """
        Calculate optimal HNSW_EF based on complexity and query type.
        
        Strategy:
        - Simple queries: Lower EF for speed
        - Complex queries: Higher EF for quality
        - Scale with collection size
        """
        if not self.enable_adaptive:
            return self.base_ef
        
        # Base factor by query type
        if query_type == QueryType.SIMPLE:
            factor = self.simple_ef_factor
        elif query_type == QueryType.SEMANTIC:
            factor = self.semantic_ef_factor
        elif query_type == QueryType.COMPLEX or query_type == QueryType.GRAPH:
            factor = self.complex_ef_factor
        else:  # HYBRID
            factor = (self.simple_ef_factor + self.semantic_ef_factor) / 2
        
        # Adjust by complexity within type
        complexity_adjustment = 0.5 + (complexity * 0.5)  # Range [0.5, 1.0]
        
        # Calculate EF
        calculated_ef = int(self.base_ef * factor * complexity_adjustment)
        
        # Collection size scaling (larger collections may benefit from higher EF)
        if self.collection_size > 50000:
            calculated_ef = int(calculated_ef * 1.5)
        
        # Clamp to range
        return max(self.min_ef, min(self.max_ef, calculated_ef))
    
    def _should_use_dense_only(self, query: str, complexity: float, query_type: QueryType) -> bool:
        """Decide if query can be effectively served by dense search only."""
        # Never for complex or hybrid queries
        if query_type in {QueryType.COMPLEX, QueryType.HYBRID, QueryType.GRAPH}:
            return False
            
        # Semantic queries usually do well with dense
        if query_type == QueryType.SEMANTIC and complexity < 0.6:
            return True
            
        # Very simple queries (identifiers) may prefer hybrid/lexical
        if query_type == QueryType.SIMPLE:
            return False
            
        return complexity < self.dense_only_threshold
    
    def _estimate_latency(self, complexity: float, ef: int, dense_only: bool) -> float:
        """Estimate retrieval latency in milliseconds."""
        base_latency = 50.0  # Base cost of embedding + Qdrant overhead
        
        # Complexity and EF cost
        ef_cost = (ef / 128.0) * 20.0
        
        # Hybrid search adds cost
        hybrid_cost = 0.0 if dense_only else 40.0
        
        return base_latency + ef_cost + hybrid_cost
    
    def record_performance(self, complexity: float, ef: int, latency_ms: float):
        """Record actual performance for adaptive learning."""
        self._performance_history.append((complexity, ef, latency_ms))
        self.stats.total_latency_ms += latency_ms
        self.stats.avg_ef_used = (
            (self.stats.avg_ef_used * (self.stats.total_queries - 1) + ef) / 
            self.stats.total_queries if self.stats.total_queries > 0 else ef
        )
        
        # In a real implementation, we would adjust ef_factors based on latency targets
        if len(self._performance_history) > 100:
            self._performance_history.pop(0)


# ---------------------------------------------------------------------------
# Singleton instance for efficient reuse across requests
# ---------------------------------------------------------------------------
_OPTIMIZER_INSTANCE: Optional[QueryOptimizer] = None
_OPTIMIZER_LOCK = threading.Lock()


def get_query_optimizer(collection_size: int = 10000) -> QueryOptimizer:
    """
    Get the singleton QueryOptimizer instance.

    Thread-safe lazy initialization. The collection_size is only used on first
    initialization; subsequent calls return the cached instance.

    Args:
        collection_size: Estimated collection size (used on first init only)

    Returns:
        The shared QueryOptimizer instance
    """
    global _OPTIMIZER_INSTANCE
    if _OPTIMIZER_INSTANCE is None:
        with _OPTIMIZER_LOCK:
            # Double-check after acquiring lock
            if _OPTIMIZER_INSTANCE is None:
                _OPTIMIZER_INSTANCE = QueryOptimizer(collection_size=collection_size)
                logger.debug(f"QueryOptimizer singleton initialized with collection_size={collection_size}")
    return _OPTIMIZER_INSTANCE


def reset_query_optimizer() -> None:
    """Reset the singleton instance (useful for testing or collection changes)."""
    global _OPTIMIZER_INSTANCE
    with _OPTIMIZER_LOCK:
        _OPTIMIZER_INSTANCE = None
