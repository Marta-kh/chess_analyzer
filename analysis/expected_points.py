"""Expected-points and Win/Draw/Loss probability model (Classification V2).

Converts canonical mover-perspective engine evaluations (centipawns, mate distance,
or terminal board state) into a 3-outcome distribution (win_prob, draw_prob, loss_prob)
and expected points in [0.0, 1.0]:
    win_prob + draw_prob + loss_prob = 1.0
    expected_points = win_prob + 0.5 * draw_prob

Note: This is a clean-room, configurable provisional model inspired by published
Chess.com Classification V2 expected-points buckets, not a proprietary clone.
"""
from dataclasses import dataclass
import math
from typing import Optional, Tuple
from chess_analyzer.engines.engine_models import EngineScore


@dataclass(frozen=True)
class OutcomeProbabilities:
    """Three-outcome probability distribution from the mover's perspective."""
    win_prob: float
    draw_prob: float
    loss_prob: float

    @property
    def expected_points(self) -> float:
        return max(0.0, min(1.0, self.win_prob + 0.5 * self.draw_prob))


@dataclass(frozen=True)
class ExpectedPointsConfig:
    """Versioned parameters for the expected-points and W/D/L model."""
    model_version: str = "v2.1-provisional"
    # Logistic centipawn scale (~271.58 matches 0.00368208 logistic slope at reference rating)
    base_cp_scale: float = 271.58
    rating_reference: float = 1500.0
    # Higher-rated players convert centipawn advantages more reliably (steeper curve)
    rating_scale_sensitivity: float = 0.065
    min_cp_scale: float = 190.0
    max_cp_scale: float = 370.0
    # Draw probability bell curve peak at 0.0 cp
    base_draw_peak: float = 0.34
    rating_draw_sensitivity: float = 0.045
    draw_width_cp: float = 185.0


class ExpectedPointsModel:
    """Converts normalized mover-perspective evaluations into W/D/L and expected points."""

    def __init__(self, config: Optional[ExpectedPointsConfig] = None) -> None:
        self.config = config or ExpectedPointsConfig()

    def effective_cp_scale(self, rating: Optional[int] = None) -> float:
        if rating is None or rating <= 0:
            return self.config.base_cp_scale
        delta_k = (float(rating) - self.config.rating_reference) / 400.0
        scale = self.config.base_cp_scale * (1.0 - self.config.rating_scale_sensitivity * delta_k)
        return max(self.config.min_cp_scale, min(self.config.max_cp_scale, scale))

    def effective_draw_peak(self, rating: Optional[int] = None) -> float:
        if rating is None or rating <= 0:
            return self.config.base_draw_peak
        delta_k = (float(rating) - self.config.rating_reference) / 400.0
        peak = self.config.base_draw_peak + self.config.rating_draw_sensitivity * delta_k
        return max(0.18, min(0.58, peak))

    def from_cp(self, cp_for_mover: int, rating: Optional[int] = None) -> OutcomeProbabilities:
        scale = self.effective_cp_scale(rating)
        clamped_cp = max(-4000.0, min(4000.0, float(cp_for_mover)))
        ep = 1.0 / (1.0 + math.exp(-clamped_cp / scale))

        draw_peak = self.effective_draw_peak(rating)
        raw_draw = draw_peak * math.exp(-((clamped_cp / self.config.draw_width_cp) ** 2))
        max_feasible_draw = 2.0 * min(ep, 1.0 - ep)
        draw_p = max(0.0, min(raw_draw, max_feasible_draw * 0.98))

        win_p = max(0.0, min(1.0, ep - 0.5 * draw_p))
        loss_p = max(0.0, 1.0 - win_p - draw_p)
        total = win_p + draw_p + loss_p
        if total > 0:
            win_p /= total
            draw_p /= total
            loss_p /= total
        return OutcomeProbabilities(win_prob=win_p, draw_prob=draw_p, loss_prob=loss_p)

    def from_score(
        self,
        score: EngineScore,
        mover_color: str,
        rating: Optional[int] = None,
        is_terminal_draw: bool = False,
    ) -> OutcomeProbabilities:
        """Computes W/D/L and expected points for `mover_color` ('white' or 'black')."""
        if is_terminal_draw:
            return OutcomeProbabilities(win_prob=0.0, draw_prob=1.0, loss_prob=0.0)

        if score.is_mate:
            m = score.mate_for_color(mover_color)
            if m is None:
                return OutcomeProbabilities(0.0, 1.0, 0.0)
            if m > 0:
                if m == 1 or score.raw_mate_pov == 0:
                    return OutcomeProbabilities(1.0, 0.0, 0.0)
                win_p = max(0.965, 1.0 - 0.0022 * (m - 1))
                draw_p = max(0.0, 1.0 - win_p)
                return OutcomeProbabilities(win_prob=win_p, draw_prob=draw_p, loss_prob=0.0)
            elif m < 0:
                abs_m = abs(m)
                if abs_m == 1 or score.raw_mate_pov == 0:
                    return OutcomeProbabilities(0.0, 0.0, 1.0)
                loss_p = max(0.965, 1.0 - 0.0022 * (abs_m - 1))
                draw_p = max(0.0, 1.0 - loss_p)
                return OutcomeProbabilities(win_prob=0.0, draw_prob=draw_p, loss_prob=loss_p)
            else:
                if score.pov_color != mover_color:
                    return OutcomeProbabilities(1.0, 0.0, 0.0)
                return OutcomeProbabilities(0.0, 0.0, 1.0)

        cp = score.cp_for_color(mover_color)
        return self.from_cp(cp if cp is not None else 0, rating=rating)

    @staticmethod
    def compute_loss(ep_after_best: float, ep_after_played: float) -> Tuple[float, float, bool]:
        """Computes expected-points loss: (clamped_loss, raw_delta, negative_loss_detected)."""
        raw_delta = ep_after_best - ep_after_played
        negative_loss = raw_delta < -0.005
        clamped_loss = max(0.0, min(1.0, raw_delta))
        return (clamped_loss, raw_delta, negative_loss)
