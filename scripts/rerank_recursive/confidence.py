"""
ConfidenceEstimator - Estimates confidence to enable early stopping.

From TRM: Q-learning inspired halting - stop when improvement is minimal.
Enhanced with score separation analysis for calibrated stopping.
"""
import os
import numpy as np

from scripts.rerank_recursive.state import RefinementState

# Feature flag for enhanced confidence with score separation
CALIBRATED_CONFIDENCE_ENABLED = os.getenv("CALIBRATED_CONFIDENCE", "0") == "1"
MIN_SCORE_SEPARATION = float(os.getenv("CONFIDENCE_MIN_SEPARATION", "0.15"))


class ConfidenceEstimator:
    """
    Estimates confidence to enable early stopping.

    Uses patience to avoid stopping on noisy single-step improvements.
    Enhanced with score separation analysis to prevent stopping on close races.
    """

    def __init__(
        self,
        patience: int = 1,
        min_improvement: float = 0.01,
        min_separation: float | None = None,
    ):
        self.patience = patience
        self.min_improvement = min_improvement
        self.min_separation = min_separation if min_separation is not None else MIN_SCORE_SEPARATION
        self._stable_count = 0

    def reset(self):
        """Reset state for a new query."""
        self._stable_count = 0

    def should_stop(self, state: RefinementState) -> bool:
        """Check if we should stop refining based on score stability and separation."""
        if len(state.score_history) < 2:
            return False

        prev_scores = state.score_history[-2]
        curr_scores = state.scores

        # Check 1: Rank stability
        prev_order = np.argsort(-prev_scores)
        curr_order = np.argsort(-curr_scores)

        k = min(5, len(prev_order))
        rank_stable = np.array_equal(prev_order[:k], curr_order[:k])

        # Check 2: Score improvement
        improvement = np.abs(curr_scores - prev_scores).mean()
        improvement_stable = improvement < self.min_improvement

        # Check 3: Score separation (only if calibrated confidence enabled)
        separation_ok = True
        if CALIBRATED_CONFIDENCE_ENABLED and len(curr_scores) >= 2:
            separation_ok = self._check_score_separation(curr_scores)

        # Combined: stable if rank OR improvement is stable, AND separation is OK
        is_stable = (rank_stable or improvement_stable) and separation_ok

        if is_stable:
            self._stable_count += 1
            if self._stable_count >= self.patience:
                return True
        else:
            self._stable_count = 0

        return False

    def _check_score_separation(self, scores: np.ndarray) -> bool:
        """
        Check if top scores have sufficient separation to stop confidently.

        Returns True if #1 is clearly ahead of #2 (safe to stop).
        Returns False if scores are too close (continue refining).
        """
        if len(scores) < 2:
            return True

        sorted_scores = np.sort(scores)[::-1]
        top1, top2 = sorted_scores[0], sorted_scores[1]

        # Compute relative separation
        if abs(top1) < 1e-8:
            return True  # Degenerate case

        separation = (top1 - top2) / abs(top1)
        return separation >= self.min_separation

    def get_confidence_score(self, scores: np.ndarray) -> float:
        """
        Compute a confidence score [0, 1] for the current ranking.

        Higher confidence = clearer winner, more iterations stable.
        """
        if len(scores) < 2:
            return 1.0

        sorted_scores = np.sort(scores)[::-1]
        top1, top2 = sorted_scores[0], sorted_scores[1]

        # Separation component
        if abs(top1) < 1e-8:
            separation_conf = 0.5
        else:
            separation_conf = min(1.0, (top1 - top2) / abs(top1))

        # Stability component
        stability_conf = min(1.0, self._stable_count / 3.0)

        # Combined: 60% separation, 40% stability
        return 0.6 * separation_conf + 0.4 * stability_conf
