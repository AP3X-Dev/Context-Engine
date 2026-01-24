"""Smart termination conditions for iterative search operations.

Implements 5 termination conditions from ChunkHound's multi-hop strategy:
1. Time limit (default 5 seconds)
2. Result limit (default 500 chunks)
3. Candidate quality (need N+ high-scoring for expansion)
4. Score degradation (stop if tracked scores drop by threshold)
5. Minimum relevance (stop if top-N min score below threshold)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Sequence

logger = logging.getLogger(__name__)


@dataclass
class TerminationConfig:
    time_limit: float = 5.0
    result_limit: int = 500
    min_candidates_for_expansion: int = 5
    score_degradation_threshold: float = 0.15
    min_relevance_score: float = 0.3
    top_n_to_track: int = 5


class TerminationChecker:
    """Checks 5 termination conditions for iterative search operations."""
    
    def __init__(self, config: TerminationConfig | None = None):
        self.config = config or TerminationConfig()
        self.start_time = time.perf_counter()
        self.tracked_chunk_scores: Dict[str, float] = {}
        self.iteration = 0
    
    def reset(self) -> None:
        self.start_time = time.perf_counter()
        self.tracked_chunk_scores.clear()
        self.iteration = 0
    
    def elapsed(self) -> float:
        return time.perf_counter() - self.start_time
    
    def check(
        self,
        results: Sequence[dict],
        score_key: str = "score",
        id_key: str = "chunk_id",
    ) -> Tuple[bool, str]:
        """Check all termination conditions.
        
        Returns:
            (should_terminate, reason) - reason is empty string if should continue
        """
        self.iteration += 1
        
        # 1. Time limit
        if self.elapsed() >= self.config.time_limit:
            logger.debug(f"Termination: time limit {self.config.time_limit}s reached")
            return True, "time_limit"
        
        # 2. Result limit
        if len(results) >= self.config.result_limit:
            logger.debug(f"Termination: result limit {self.config.result_limit} reached")
            return True, "result_limit"
        
        # 3. Insufficient high-scoring candidates
        high_scoring = [r for r in results if r.get(score_key, 0) > 0]
        if len(high_scoring) < self.config.min_candidates_for_expansion:
            logger.debug(
                f"Termination: insufficient candidates "
                f"({len(high_scoring)} < {self.config.min_candidates_for_expansion})"
            )
            return True, "insufficient_candidates"
        
        # Sort by score descending
        sorted_results = sorted(results, key=lambda x: -x.get(score_key, 0))
        top_n = sorted_results[:self.config.top_n_to_track]
        
        # 4. Score degradation - track specific chunks across iterations
        if self.tracked_chunk_scores:
            max_drop = 0.0
            for chunk_id, prev_score in self.tracked_chunk_scores.items():
                current_score = next(
                    (r.get(score_key, 0) for r in results if r.get(id_key) == chunk_id),
                    0.0
                )
                if current_score < prev_score:
                    max_drop = max(max_drop, prev_score - current_score)
            
            if max_drop >= self.config.score_degradation_threshold:
                logger.debug(
                    f"Termination: score degradation {max_drop:.3f} >= "
                    f"{self.config.score_degradation_threshold}"
                )
                return True, "score_degradation"
        
        # Update tracked scores for next iteration
        self.tracked_chunk_scores.clear()
        for r in top_n:
            chunk_id = r.get(id_key)
            if chunk_id:
                self.tracked_chunk_scores[chunk_id] = r.get(score_key, 0)
        
        # 5. Minimum relevance - stop if top-N min score too low
        if top_n:
            min_score = min(r.get(score_key, 0) for r in top_n)
            if min_score < self.config.min_relevance_score:
                logger.debug(
                    f"Termination: min relevance {min_score:.3f} < "
                    f"{self.config.min_relevance_score}"
                )
                return True, "min_relevance"
        
        return False, ""
    
    def get_stats(self) -> Dict[str, any]:
        return {
            "iterations": self.iteration,
            "elapsed_seconds": round(self.elapsed(), 3),
            "tracked_chunks": len(self.tracked_chunk_scores),
        }
