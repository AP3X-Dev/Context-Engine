"""Smart termination for iterative search operations.

Mathematical foundations:
1. Welford's algorithm - O(1) online variance for adaptive thresholds
2. Page-Hinkley test - detects mean shift in streaming data
3. Statistical termination - uses 2-sigma rule instead of fixed thresholds

Welford's update: δ = x - μ, μ' = μ + δ/n, M2' = M2 + δ(x - μ')
Page-Hinkley: cumsum of (x - μ - δ), detect when max deviation exceeds threshold
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Sequence, Optional
import math

logger = logging.getLogger(__name__)


@dataclass
class WelfordState:
    """Online variance computation using Welford's algorithm."""
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    
    def update(self, x: float) -> None:
        """O(1) update with new value."""
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2
    
    @property
    def variance(self) -> float:
        return self.m2 / self.n if self.n > 1 else 0.0
    
    @property
    def std(self) -> float:
        return math.sqrt(self.variance)
    
    def adaptive_threshold(self, sigma_multiplier: float = 2.0) -> float:
        """Return threshold as mean - sigma_multiplier * std."""
        return self.mean - sigma_multiplier * self.std


@dataclass 
class PageHinkleyState:
    """Page-Hinkley test for DOWNWARD mean shift detection (score degradation).
    
    Detects when scores drop significantly below the running mean.
    Cumsum formula: cumsum += (mean - x + delta)
    When x consistently falls below mean, cumsum grows and triggers detection.
    
    This is the inverse of the standard PH test (which detects upward drift).
    Optimized for search relevance degradation detection.
    """
    delta: float = 0.005
    threshold: float = 0.5
    n: int = 0
    mean: float = 0.0
    cumsum: float = 0.0
    cumsum_max: float = 0.0
    
    def update(self, x: float) -> bool:
        """Update and return True if downward drift detected."""
        self.n += 1
        
        if self.n == 1:
            self.mean = x
            return False
        
        self.mean = ((self.n - 1) * self.mean + x) / self.n
        
        # cumsum += (mean - x + delta): grows when x < mean
        self.cumsum += self.mean - x + self.delta
        self.cumsum_max = max(self.cumsum_max, self.cumsum)
        
        if self.cumsum > self.threshold:
            return True
        
        return False
    
    def reset(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.cumsum = 0.0
        self.cumsum_max = 0.0


@dataclass
class TerminationConfig:
    time_limit: float = 5.0
    result_limit: int = 500
    min_candidates_for_expansion: int = 5
    
    use_adaptive_threshold: bool = True
    sigma_multiplier: float = 2.0
    fixed_degradation_threshold: float = 0.15
    
    use_page_hinkley: bool = True
    page_hinkley_delta: float = 0.005
    page_hinkley_threshold: float = 0.5
    
    min_relevance_score: float = 0.3
    top_n_to_track: int = 5
    
    min_iterations_before_stop: int = 2


class TerminationChecker:
    """Statistically-grounded termination for iterative search."""
    
    def __init__(self, config: TerminationConfig | None = None):
        self.config = config or TerminationConfig()
        self.start_time = time.perf_counter()
        self.iteration = 0
        
        self.tracked_chunk_scores: Dict[str, float] = {}
        
        self.score_stats = WelfordState()
        self.page_hinkley = PageHinkleyState(
            delta=self.config.page_hinkley_delta,
            threshold=self.config.page_hinkley_threshold,
        )
        
        self.top_scores_history: List[float] = []
    
    def reset(self) -> None:
        self.start_time = time.perf_counter()
        self.iteration = 0
        self.tracked_chunk_scores.clear()
        self.score_stats = WelfordState()
        self.page_hinkley.reset()
        self.top_scores_history.clear()
    
    def elapsed(self) -> float:
        return time.perf_counter() - self.start_time
    
    def check(
        self,
        results: Sequence[dict],
        score_key: str = "score",
        id_key: str = "chunk_id",
    ) -> Tuple[bool, str]:
        """Check termination conditions with statistical methods.
        
        Returns:
            (should_terminate, reason)
        """
        self.iteration += 1
        
        if self.elapsed() >= self.config.time_limit:
            logger.debug(f"Termination: time limit {self.config.time_limit}s")
            return True, "time_limit"
        
        if len(results) >= self.config.result_limit:
            logger.debug(f"Termination: result limit {self.config.result_limit}")
            return True, "result_limit"

	        # Handle None/non-numeric scores gracefully
	        def get_numeric_score(r: dict) -> float:
	            score = r.get(score_key, 0)
	            if score is None or isinstance(score, bool):
	                return 0.0
	            try:
	                return float(score)
	            except (TypeError, ValueError):
	                return 0.0

        high_scoring = [r for r in results if get_numeric_score(r) > 0]
        if len(high_scoring) < self.config.min_candidates_for_expansion:
            logger.debug(f"Termination: insufficient candidates ({len(high_scoring)})")
            return True, "insufficient_candidates"

        sorted_results = sorted(results, key=lambda x: -get_numeric_score(x))
        top_n = sorted_results[:self.config.top_n_to_track]
        
	        if top_n:
	            top_score = get_numeric_score(top_n[0])
	            self.score_stats.update(top_score)
	            self.top_scores_history.append(top_score)
        
        if self.iteration >= self.config.min_iterations_before_stop:
            
	            if self.config.use_page_hinkley and top_n:
	                top_score = get_numeric_score(top_n[0])
	                if self.page_hinkley.update(top_score):
                    logger.debug("Termination: Page-Hinkley detected score drift")
                    return True, "score_drift_detected"
            
            if self.tracked_chunk_scores and self.iteration > 2:
                if self.config.use_adaptive_threshold:
                    threshold = self.score_stats.adaptive_threshold(
                        self.config.sigma_multiplier
                    )
                    if threshold <= 0:
                        threshold = self.config.fixed_degradation_threshold
                else:
                    threshold = self.config.fixed_degradation_threshold
                
                max_drop = 0.0
	                for chunk_id, prev_score in self.tracked_chunk_scores.items():
	                    current_score = next(
	                        (get_numeric_score(r) for r in results if r.get(id_key) == chunk_id),
	                        0.0
	                    )
                    if current_score < prev_score:
                        max_drop = max(max_drop, prev_score - current_score)
                
                if max_drop >= threshold:
                    logger.debug(
                        f"Termination: score degradation {max_drop:.3f} >= "
                        f"threshold {threshold:.3f}"
                    )
                    return True, "score_degradation"
        
	        self.tracked_chunk_scores.clear()
	        for r in top_n:
	            chunk_id = r.get(id_key)
	            if chunk_id:
	                self.tracked_chunk_scores[chunk_id] = get_numeric_score(r)
        
	        if top_n:
	            min_score = min(get_numeric_score(r) for r in top_n)
            if min_score < self.config.min_relevance_score:
                logger.debug(f"Termination: min relevance {min_score:.3f}")
                return True, "min_relevance"
        
        return False, ""
    
    def get_stats(self) -> Dict[str, float]:
        return {
            "iterations": self.iteration,
            "elapsed_seconds": round(self.elapsed(), 3),
            "tracked_chunks": len(self.tracked_chunk_scores),
            "score_mean": round(self.score_stats.mean, 4),
            "score_std": round(self.score_stats.std, 4),
            "adaptive_threshold": round(
                self.score_stats.adaptive_threshold(self.config.sigma_multiplier), 4
            ),
            "page_hinkley_cumsum": round(self.page_hinkley.cumsum, 4),
        }


def mann_whitney_u(x: Sequence[float], y: Sequence[float]) -> Tuple[float, float]:
    """Mann-Whitney U test for comparing two score distributions.
    
    Returns (U statistic, approximate p-value using normal approximation).
    Useful for comparing score quality across iterations.
    """
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 0.0, 1.0
    
    combined = [(v, 0) for v in x] + [(v, 1) for v in y]
    combined.sort(key=lambda t: t[0])
    
    ranks = {}
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0
        for k in range(i, j):
            val = combined[k][0]
            if val not in ranks:
                ranks[val] = []
            ranks[val].append(avg_rank)
        i = j
    
    r1 = sum(ranks[v][0] if len(ranks[v]) == 1 else ranks[v].pop(0) for v in x)
    
    u1 = r1 - nx * (nx + 1) / 2
    u2 = nx * ny - u1
    u = min(u1, u2)
    
    mu = nx * ny / 2
    sigma = math.sqrt(nx * ny * (nx + ny + 1) / 12)
    
    if sigma == 0:
        return u, 1.0
    
    z = (u - mu) / sigma
    
    p = 2 * (1 - _normal_cdf(abs(z)))
    
    return u, p


def _normal_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911
    
    sign = 1 if x >= 0 else -1
    x = abs(x)
    
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x / 2)
    
    return 0.5 * (1.0 + sign * y)
