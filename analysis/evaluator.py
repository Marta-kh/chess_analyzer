"""Perspective-normalized chess position evaluation and expected-points helper."""
from dataclasses import dataclass
import math
from typing import Optional
from chess_analyzer.analysis.expected_points import (
    ExpectedPointsConfig,
    ExpectedPointsModel,
    OutcomeProbabilities,
)
from chess_analyzer.engines.engine_models import EngineScore


@dataclass(frozen=True)
class EvaluationComparison:
    """
    Normalized comparison between the position BEFORE a move (best available line)
    and the position AFTER the played move, from the perspective of the player who moved.
    """
    mover_color: str  # "white" or "black"
    eval_before_cp: int
    eval_after_cp: int
    cp_loss: int
    win_prob_before: float
    win_prob_after: float
    win_prob_loss: float
    mate_before: Optional[int] = None  # Positive = mover had forced mate in N
    mate_after: Optional[int] = None   # Positive = mover still has mate in N; Negative = mover gets mated in N
    # V2 expected-points & W/D/L fields
    expected_points_before: float = 0.5
    expected_points_after: float = 0.5
    expected_points_loss: float = 0.0
    raw_ep_delta: float = 0.0
    negative_loss_detected: bool = False
    outcomes_before: Optional[OutcomeProbabilities] = None
    outcomes_after: Optional[OutcomeProbabilities] = None
    white_cp_before: int = 0
    white_cp_after: int = 0


class EvaluationNormalizer:
    """Explicit perspective conversion utilities for engine evaluations."""

    @staticmethod
    def to_white_cp(score: EngineScore) -> int:
        return PositionEvaluator.score_to_mover_cp(score, "white")

    @staticmethod
    def to_mover_cp(score: EngineScore, mover_color: str) -> int:
        return PositionEvaluator.score_to_mover_cp(score, mover_color)


class PositionEvaluator:
    """Normalizes centipawn and mate evaluations to mover/White perspective and computes expected points."""

    _EP_MODEL = ExpectedPointsModel(ExpectedPointsConfig())

    @staticmethod
    def cp_to_win_probability(cp: int, rating: Optional[int] = None) -> float:
        """Convert centipawns from mover's perspective into expected points [0.0, 1.0]."""
        return PositionEvaluator._EP_MODEL.from_cp(cp, rating=rating).expected_points

    @staticmethod
    def score_to_mover_cp(score: EngineScore, mover_color: str) -> int:
        """Convert an EngineScore (including mate scores) to equivalent centipawns for `mover_color`."""
        if score.is_mate:
            m = score.mate_for_color(mover_color)
            if m is None:
                return 0
            if m == 0:
                return 10000 if score.pov_color != mover_color else -10000
            if m > 0:
                return 10000 - min(50, m) * 50
            return -10000 + min(50, abs(m)) * 50
        cp = score.cp_for_color(mover_color)
        return cp if cp is not None else 0

    @classmethod
    def compare(
        cls,
        score_before: EngineScore,
        score_after: EngineScore,
        mover_color: str,
        player_rating: Optional[int] = None,
        is_terminal_draw_after: bool = False,
    ) -> EvaluationComparison:
        cp_before = cls.score_to_mover_cp(score_before, mover_color)
        cp_after = 0 if is_terminal_draw_after else cls.score_to_mover_cp(score_after, mover_color)
        cp_loss = max(0, cp_before - cp_after)

        white_cp_before = cls.score_to_mover_cp(score_before, "white")
        white_cp_after = 0 if is_terminal_draw_after else cls.score_to_mover_cp(score_after, "white")

        outcomes_before = cls._EP_MODEL.from_score(score_before, mover_color, rating=player_rating)
        outcomes_after = cls._EP_MODEL.from_score(
            score_after,
            mover_color,
            rating=player_rating,
            is_terminal_draw=is_terminal_draw_after,
        )

        ep_before = outcomes_before.expected_points
        ep_after = outcomes_after.expected_points
        ep_loss, raw_delta, neg_loss = cls._EP_MODEL.compute_loss(ep_before, ep_after)

        mate_before = score_before.mate_for_color(mover_color) if score_before.is_mate else None
        mate_after = score_after.mate_for_color(mover_color) if score_after.is_mate else None
        if score_after.is_mate and score_after.raw_mate_pov == 0 and score_after.pov_color != mover_color:
            mate_after = 1

        return EvaluationComparison(
            mover_color=mover_color,
            eval_before_cp=cp_before,
            eval_after_cp=cp_after,
            cp_loss=cp_loss,
            win_prob_before=ep_before,
            win_prob_after=ep_after,
            win_prob_loss=ep_loss,
            mate_before=mate_before,
            mate_after=mate_after,
            expected_points_before=ep_before,
            expected_points_after=ep_after,
            expected_points_loss=ep_loss,
            raw_ep_delta=raw_delta,
            negative_loss_detected=neg_loss,
            outcomes_before=outcomes_before,
            outcomes_after=outcomes_after,
            white_cp_before=white_cp_before,
            white_cp_after=white_cp_after,
        )
