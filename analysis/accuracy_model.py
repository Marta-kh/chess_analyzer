"""CAPS2-inspired provisional player accuracy model (0-100 scale).

Computes per-move quality scores from expected-points loss:
    q_i = exp(-k * effective_loss_i)
Aggregates via context-weighted harmonic/arithmetic blend (excluding pure Book moves,
down-weighting trivial Forced 1-legal-move positions, and up-weighting high-tension positions),
then applies a slightly convex calibration curve (Q ** 1.08) so inaccuracies, mistakes,
and blunders reduce accuracy realistically without inflating scores toward 95%+.

Never derives accuracy from the percentage of 'Best' moves.
"""
from dataclasses import dataclass
import math
from typing import List, Optional
from .move_classifier import MoveClassification, MoveQuality


@dataclass(frozen=True)
class AccuracyConfig:
    model_version: str = "caps2-inspired-v2.2"
    loss_decay_k: float = 5.40
    cp_penalty_weight: float = 0.14
    cp_penalty_scale: float = 180.0
    harmonic_blend_weight: float = 0.45
    calibration_exponent: float = 1.08
    critical_tension_boost: float = 1.35
    forced_move_weight: float = 0.20
    decided_position_weight: float = 0.55


class AccuracyModel:
    """Computes CAPS2-inspired player accuracy in [0.0, 100.0] from move expected-points losses."""

    def __init__(self, config: Optional[AccuracyConfig] = None) -> None:
        self.config = config or AccuracyConfig()

    def move_quality_score(self, ep_loss: float, cp_loss: int = 0) -> float:
        """Returns move quality q_i in (0.0, 1.0] as a strictly decreasing function of loss."""
        clean_loss = max(0.0, min(1.0, ep_loss))
        cp_component = self.config.cp_penalty_weight * min(
            1.0, max(0, cp_loss) / max(1.0, self.config.cp_penalty_scale)
        )
        effective_loss = clean_loss + cp_component
        return math.exp(-self.config.loss_decay_k * effective_loss)

    def compute_player_accuracy(self, player_moves: List[MoveClassification]) -> float:
        valid = [c for c in player_moves if c.quality != MoveQuality.INSUFFICIENT_DATA]
        if not valid:
            return 100.0

        weighted_sum = 0.0
        total_weight = 0.0
        scored_qs: List[float] = []

        for c in valid:
            if c.quality == MoveQuality.BOOK:
                continue

            ep_loss = getattr(c, "expected_points_loss", c.win_prob_loss)
            q_i = self.move_quality_score(ep_loss, c.cp_loss)
            scored_qs.append(q_i)

            ep_before = getattr(c, "expected_points_before", 0.5)
            if c.quality == MoveQuality.FORCED:
                w_i = self.config.forced_move_weight
            elif 0.20 <= ep_before <= 0.80:
                w_i = self.config.critical_tension_boost
            elif ep_before > 0.94 or ep_before < 0.06:
                w_i = self.config.decided_position_weight
            else:
                w_i = 1.0

            weighted_sum += w_i * q_i
            total_weight += w_i

        if total_weight <= 0.0 or not scored_qs:
            return 90.0

        weighted_mean = weighted_sum / total_weight
        inv_sum = sum(1.0 / max(0.06, q) for q in scored_qs)
        harmonic_mean = len(scored_qs) / inv_sum if inv_sum > 0 else weighted_mean

        h_w = self.config.harmonic_blend_weight
        Q = (1.0 - h_w) * weighted_mean + h_w * harmonic_mean
        calibrated = 100.0 * (max(0.0, min(1.0, Q)) ** self.config.calibration_exponent)
        return round(max(0.0, min(100.0, calibrated)), 1)
