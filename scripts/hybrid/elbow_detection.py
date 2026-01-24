"""Elbow detection utilities for adaptive threshold computation.

Implements the Kneedle algorithm (Satopaa et al. 2011) for finding elbow points
in score curves. Used for adaptive threshold computation in hybrid search.

Ported from ChunkHound to Context-Engine.

Usage:
    from scripts.hybrid.elbow_detection import compute_elbow_threshold, find_elbow_kneedle
    
    # With raw scores
    scores = [0.95, 0.88, 0.45, 0.42, 0.40]
    threshold = compute_elbow_threshold(scores)
    
    # With search results (dicts with 'score' or 'rerank_score' keys)
    results = [{"score": 0.95}, {"score": 0.88}, {"score": 0.45}]
    threshold = compute_elbow_threshold(results)
    
    # Filter results by elbow threshold
    filtered = [r for r in results if r.get("score", 0) >= threshold]
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import numpy as np

logger = logging.getLogger(__name__)


def find_elbow_kneedle(sorted_scores: Sequence[float]) -> int | None:
    """Find elbow point in score curve using simplified Kneedle algorithm.

    Implementation based on Kneedle algorithm (Satopaa et al. 2011):
    1. Normalize scores to [0,1]
    2. Draw line from first to last point
    3. Find point with maximum perpendicular distance to line
    4. That's the elbow/knee point

    Args:
        sorted_scores: Scores sorted DESCENDING (highest to lowest)

    Returns:
        Index of elbow point (0-based array index), or None if no clear elbow detected.
        Return value can be used to threshold: scores[:elbow_idx+1] are above elbow.

    Examples:
        >>> scores = [0.95, 0.92, 0.88, 0.45, 0.42, 0.40]  # Clear drop at index 2
        >>> find_elbow_kneedle(scores)
        2  # Select first 3 items (indices 0, 1, 2)

        >>> scores = [0.5, 0.5, 0.5, 0.5]  # All identical
        >>> find_elbow_kneedle(scores)
        None  # No elbow

        >>> scores = [0.9, 0.8]  # Too few points
        >>> find_elbow_kneedle(scores)
        None  # Need at least 3 points
    """
    if len(sorted_scores) < 3:
        logger.debug("Kneedle: Too few points (<3), cannot detect elbow")
        return None  # Need at least 3 points for elbow

    # Extract scores as numpy array
    scores = np.array(sorted_scores)

    # Normalize scores to [0, 1]
    min_score = scores.min()
    max_score = scores.max()
    if max_score == min_score:
        logger.debug("Kneedle: All scores identical, no elbow")
        return None  # All scores identical, no elbow

    normalized_scores = (scores - min_score) / (max_score - min_score)

    # X-axis: normalized positions [0, 1]
    x = np.linspace(0, 1, len(normalized_scores))

    # Draw line from first point to last point
    # Line equation: y = mx + b
    x1, y1 = x[0], normalized_scores[0]
    x2, y2 = x[-1], normalized_scores[-1]

    # Handle vertical line case (shouldn't happen with normalized x)
    if x2 == x1:
        logger.debug("Kneedle: Vertical line case, no elbow")
        return None

    m = (y2 - y1) / (x2 - x1)
    b = y1 - m * x1

    # Compute perpendicular distance from each point to line
    # Formula: |mx - y + b| / sqrt(m^2 + 1)
    numerator = np.abs(m * x - normalized_scores + b)
    denominator = np.sqrt(m**2 + 1)
    distances = numerator / denominator

    # Find point with maximum distance (that's the elbow)
    elbow_idx = int(np.argmax(distances))

    # Validate elbow is significant (distance > 1% of normalized range)
    if distances[elbow_idx] < 0.01:
        logger.debug(
            f"Kneedle: Elbow not significant (distance={distances[elbow_idx]:.4f} < 0.01)"
        )
        return None  # Elbow not significant enough

    logger.debug(
        f"Kneedle: Found elbow at index {elbow_idx} "
        f"(distance={distances[elbow_idx]:.4f}, score={sorted_scores[elbow_idx]:.3f})"
    )

    # Return 0-based index (for array slicing: scores[:elbow_idx+1])
    return elbow_idx


def compute_elbow_threshold(
    chunks_or_scores: Union[Sequence[dict], Sequence[float]],
    score_key: str = "score",
    fallback_score_key: str = "rerank_score",
) -> float:
    """Compute elbow threshold from chunks or scores using Kneedle algorithm.

    Uses the Kneedle algorithm (Satopaa et al. 2011) to detect the elbow point
    in the score distribution. Falls back to median if Kneedle fails to find
    a significant elbow.

    Args:
        chunks_or_scores: Either:
            - List of chunks (dicts with score_key)
            - List of raw float scores
        score_key: Primary key to extract scores from dicts (default: "score")
        fallback_score_key: Fallback key if primary not found (default: "rerank_score")

    Returns:
        Threshold value (score at elbow point, or median if no elbow)

    Examples:
        >>> chunks = [{'score': 0.95}, {'score': 0.88}]
        >>> compute_elbow_threshold(chunks)
        0.88

        >>> scores = [0.95, 0.88, 0.45, 0.42]
        >>> compute_elbow_threshold(scores)
        0.45
        
        >>> # With rerank scores
        >>> chunks = [{'rerank_score': 0.95}, {'rerank_score': 0.45}]
        >>> compute_elbow_threshold(chunks, score_key="rerank_score")
        0.45
    """
    # Handle empty input
    if not chunks_or_scores:
        return 0.5  # Default threshold

    # Extract scores from chunks or use raw scores
    if isinstance(chunks_or_scores[0], dict):
        # Type narrowing: if first element is dict, all are dicts
        chunk_list: Sequence[dict] = chunks_or_scores  # type: ignore[assignment]
        scores = []
        for c in chunk_list:
            # Try primary key, then fallback, then 0.0
            score = c.get(score_key)
            if score is None:
                score = c.get(fallback_score_key, 0.0)
            scores.append(float(score))
    else:
        # Type narrowing: if first element is not dict, all are floats
        scores = [float(s) for s in chunks_or_scores]

    if not scores:
        return 0.5

    sorted_scores = sorted(scores, reverse=True)

    # Try Kneedle algorithm first
    elbow_idx = find_elbow_kneedle(sorted_scores)
    if elbow_idx is not None and elbow_idx < len(sorted_scores):
        threshold = float(sorted_scores[elbow_idx])
        logger.debug(
            f"Elbow threshold: {threshold:.3f} (Kneedle at index {elbow_idx} "
            f"of {len(scores)} scores)"
        )
        return threshold

    # Fallback to median if Kneedle fails
    median_idx = len(sorted_scores) // 2
    threshold = float(sorted_scores[median_idx])
    logger.debug(
        f"Elbow threshold: {threshold:.3f} (median fallback, "
        f"Kneedle found no significant elbow in {len(scores)} scores)"
    )
    return threshold


def filter_by_elbow(
    results: Sequence[dict],
    score_key: str = "score",
    fallback_score_key: str = "rerank_score",
    min_results: int = 1,
) -> list[dict]:
    """Filter results using elbow detection for adaptive thresholding.
    
    Args:
        results: List of result dicts with score fields
        score_key: Primary key to extract scores (default: "score")
        fallback_score_key: Fallback key if primary not found (default: "rerank_score")
        min_results: Minimum number of results to return (default: 1)
        
    Returns:
        Filtered list of results above elbow threshold
        
    Example:
        >>> results = [
        ...     {"id": 1, "score": 0.95},
        ...     {"id": 2, "score": 0.88},
        ...     {"id": 3, "score": 0.45},  # <- elbow here
        ...     {"id": 4, "score": 0.42},
        ... ]
        >>> filtered = filter_by_elbow(results)
        >>> len(filtered)
        3  # Only items above elbow threshold (0.45)
    """
    if not results:
        return []
    
    threshold = compute_elbow_threshold(results, score_key, fallback_score_key)
    
    filtered = []
    for r in results:
        score = r.get(score_key)
        if score is None:
            score = r.get(fallback_score_key, 0.0)
        if float(score) >= threshold:
            filtered.append(r)
    
    # Ensure minimum results
    if len(filtered) < min_results and len(results) >= min_results:
        # Return top min_results by score
        sorted_results = sorted(
            results,
            key=lambda x: float(x.get(score_key) or x.get(fallback_score_key, 0.0)),
            reverse=True
        )
        return sorted_results[:min_results]
    
    return filtered if filtered else results[:min_results]
