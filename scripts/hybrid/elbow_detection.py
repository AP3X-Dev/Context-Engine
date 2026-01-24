"""Elbow detection for adaptive threshold computation.

Mathematical approaches:
1. Curvature-based detection - finds point of maximum bending (2nd derivative)
2. Multi-changepoint detection - finds multiple quality tiers via recursive segmentation
3. Kneedle fallback - perpendicular distance method for edge cases

Curvature formula: κ(i) = |f''(i)| / (1 + f'(i)²)^(3/2)
where f'(i) and f''(i) are discrete derivatives using central differences.
"""

from __future__ import annotations

import logging
from typing import Sequence, Union, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _discrete_curvature(y: np.ndarray) -> np.ndarray:
    """Compute discrete curvature using central differences.
    
    κ(i) = |y''(i)| / (1 + y'(i)²)^(3/2)
    
    First derivative:  y'(i) = (y[i+1] - y[i-1]) / 2
    Second derivative: y''(i) = y[i+1] - 2*y[i] + y[i-1]
    """
    n = len(y)
    if n < 3:
        return np.zeros(n)
    
    curvature = np.zeros(n)
    
    for i in range(1, n - 1):
        y_prime = (y[i + 1] - y[i - 1]) / 2.0
        y_double_prime = y[i + 1] - 2.0 * y[i] + y[i - 1]
        
        denominator = (1.0 + y_prime ** 2) ** 1.5
        if denominator > 1e-10:
            curvature[i] = abs(y_double_prime) / denominator
    
    return curvature


def _segment_cost(y: np.ndarray) -> float:
    """Compute segment cost as negative log-likelihood under Gaussian model.
    
    Cost = n * log(variance) where variance = Σ(y - mean)² / n
    Lower cost = more homogeneous segment.
    """
    if len(y) < 2:
        return 0.0
    variance = np.var(y)
    if variance < 1e-10:
        return 0.0
    return len(y) * np.log(variance)


def find_elbow_curvature(sorted_scores: Sequence[float]) -> int | None:
    """Find elbow using maximum curvature (2nd derivative method).
    
    More mathematically rigorous than perpendicular distance:
    - Curvature measures local bending intensity
    - Invariant to linear transformation of axes
    - Maximum curvature = point of diminishing returns
    
    Args:
        sorted_scores: Scores sorted DESCENDING
        
    Returns:
        Index of elbow point, or None if no significant elbow
    """
    if len(sorted_scores) < 4:
        return None
    
    scores = np.array(sorted_scores, dtype=np.float64)
    
    min_s, max_s = scores.min(), scores.max()
    if max_s - min_s < 1e-10:
        return None
    
    normalized = (scores - min_s) / (max_s - min_s)
    
    x = np.linspace(0, 1, len(normalized))
    
    curvature = _discrete_curvature(normalized)
    
    search_start = 1
    search_end = len(curvature) - 1
    if search_end <= search_start:
        return None
    
    max_idx = search_start + int(np.argmax(curvature[search_start:search_end]))
    max_curvature = curvature[max_idx]
    
    if max_curvature < 0.1:
        logger.debug(f"Curvature: No significant elbow (max_κ={max_curvature:.4f} < 0.1)")
        return None
    
    logger.debug(
        f"Curvature: Found elbow at index {max_idx} "
        f"(κ={max_curvature:.4f}, score={sorted_scores[max_idx]:.3f})"
    )
    return max_idx


def find_changepoints(
    sorted_scores: Sequence[float],
    max_changepoints: int = 3,
    min_segment_size: int = 2,
) -> List[int]:
    """Find multiple changepoints using recursive binary segmentation.
    
    Uses BIC penalty: β = log(n) to prevent overfitting.
    
    Args:
        sorted_scores: Scores sorted DESCENDING
        max_changepoints: Maximum number of changepoints to find
        min_segment_size: Minimum segment size
        
    Returns:
        List of changepoint indices (sorted), empty if none found
    """
    if len(sorted_scores) < 2 * min_segment_size:
        return []
    
    scores = np.array(sorted_scores, dtype=np.float64)
    n = len(scores)
    
    penalty = np.log(n)
    
    def find_best_split(start: int, end: int) -> Tuple[int, float]:
        """Find best split point in segment [start, end)."""
        if end - start < 2 * min_segment_size:
            return -1, 0.0
        
        segment = scores[start:end]
        base_cost = _segment_cost(segment)
        
        best_idx = -1
        best_gain = 0.0
        
        for split in range(start + min_segment_size, end - min_segment_size + 1):
            left_cost = _segment_cost(scores[start:split])
            right_cost = _segment_cost(scores[split:end])
            
            gain = base_cost - (left_cost + right_cost) - penalty
            
            if gain > best_gain:
                best_gain = gain
                best_idx = split
        
        return best_idx, best_gain
    
    changepoints = []
    segments = [(0, n)]
    
    while len(changepoints) < max_changepoints and segments:
        best_segment_idx = -1
        best_split = -1
        best_gain = 0.0
        
        for seg_idx, (start, end) in enumerate(segments):
            split, gain = find_best_split(start, end)
            if gain > best_gain:
                best_gain = gain
                best_split = split
                best_segment_idx = seg_idx
        
        if best_split == -1:
            break
        
        changepoints.append(best_split)
        
        start, end = segments.pop(best_segment_idx)
        segments.append((start, best_split))
        segments.append((best_split, end))
    
    return sorted(changepoints)


def find_elbow_kneedle(sorted_scores: Sequence[float]) -> int | None:
    """Find elbow using perpendicular distance (Kneedle algorithm).
    
    Fallback method when curvature-based detection fails.
    """
    if len(sorted_scores) < 3:
        return None

    scores = np.array(sorted_scores, dtype=np.float64)
    
    min_score, max_score = scores.min(), scores.max()
    if max_score - min_score < 1e-10:
        return None

    normalized = (scores - min_score) / (max_score - min_score)
    x = np.linspace(0, 1, len(normalized))

    x1, y1 = x[0], normalized[0]
    x2, y2 = x[-1], normalized[-1]

    if abs(x2 - x1) < 1e-10:
        return None

    m = (y2 - y1) / (x2 - x1)
    b = y1 - m * x1

    numerator = np.abs(m * x - normalized + b)
    denominator = np.sqrt(m ** 2 + 1)
    distances = numerator / denominator

    elbow_idx = int(np.argmax(distances))

    if distances[elbow_idx] < 0.01:
        return None

    return elbow_idx


def compute_elbow_threshold(
    chunks_or_scores: Union[Sequence[dict], Sequence[float]],
    score_key: str = "score",
    fallback_score_key: str = "rerank_score",
    method: str = "curvature",
) -> float:
    """Compute elbow threshold using specified method.
    
    Args:
        chunks_or_scores: List of chunks (dicts) or raw scores
        score_key: Primary score key for dicts
        fallback_score_key: Fallback score key
        method: "curvature" (default), "kneedle", or "changepoint"
        
    Returns:
        Threshold value at elbow point
    """
    if not chunks_or_scores:
        return 0.5

    if isinstance(chunks_or_scores[0], dict):
        chunk_list: Sequence[dict] = chunks_or_scores  # type: ignore
        scores = []
        for c in chunk_list:
            score = c.get(score_key)
            if score is None:
                score = c.get(fallback_score_key, 0.0)
            scores.append(float(score))
    else:
        scores = [float(s) for s in chunks_or_scores]

    if not scores:
        return 0.5

    sorted_scores = sorted(scores, reverse=True)

    elbow_idx = None
    
    if method == "curvature":
        elbow_idx = find_elbow_curvature(sorted_scores)
        if elbow_idx is None:
            elbow_idx = find_elbow_kneedle(sorted_scores)
    elif method == "changepoint":
        changepoints = find_changepoints(sorted_scores, max_changepoints=1)
        if changepoints:
            elbow_idx = changepoints[0]
    else:
        elbow_idx = find_elbow_kneedle(sorted_scores)

    if elbow_idx is not None and 0 <= elbow_idx < len(sorted_scores):
        return float(sorted_scores[elbow_idx])

    median_idx = len(sorted_scores) // 2
    return float(sorted_scores[median_idx])


def compute_tier_thresholds(
    chunks_or_scores: Union[Sequence[dict], Sequence[float]],
    score_key: str = "score",
    fallback_score_key: str = "rerank_score",
    max_tiers: int = 3,
) -> List[float]:
    """Compute multiple quality tier thresholds.
    
    Uses changepoint detection to find natural breaks in score distribution.
    
    Args:
        chunks_or_scores: List of chunks or raw scores
        score_key: Primary score key
        fallback_score_key: Fallback score key
        max_tiers: Maximum number of tiers (changepoints + 1)
        
    Returns:
        List of threshold values (descending), one per tier boundary
    """
    if not chunks_or_scores:
        return []

    if isinstance(chunks_or_scores[0], dict):
        chunk_list: Sequence[dict] = chunks_or_scores  # type: ignore
        scores = []
        for c in chunk_list:
            score = c.get(score_key)
            if score is None:
                score = c.get(fallback_score_key, 0.0)
            scores.append(float(score))
    else:
        scores = [float(s) for s in chunks_or_scores]

    if not scores:
        return []

    sorted_scores = sorted(scores, reverse=True)
    
    changepoints = find_changepoints(
        sorted_scores, 
        max_changepoints=max_tiers - 1,
        min_segment_size=max(2, len(sorted_scores) // 10)
    )
    
    return [float(sorted_scores[cp]) for cp in changepoints]


def filter_by_elbow(
    results: Sequence[dict],
    score_key: str = "score",
    fallback_score_key: str = "rerank_score",
    min_results: int = 1,
    method: str = "curvature",
) -> list[dict]:
    """Filter results using elbow detection.
    
    Args:
        results: List of result dicts
        score_key: Primary score key
        fallback_score_key: Fallback score key
        min_results: Minimum results to return
        method: Detection method ("curvature", "kneedle", "changepoint")
        
    Returns:
        Filtered results above elbow threshold
    """
    if not results:
        return []
    
    threshold = compute_elbow_threshold(
        results, score_key, fallback_score_key, method
    )
    
    def get_score(r: dict) -> float:
        score = r.get(score_key)
        if score is None:
            score = r.get(fallback_score_key, 0.0)
        return float(score)
    
    filtered = [r for r in results if get_score(r) >= threshold]
    
    if len(filtered) < min_results and len(results) >= min_results:
        sorted_results = sorted(results, key=get_score, reverse=True)
        return sorted_results[:min_results]
    
    return filtered if filtered else results[:min_results]
