"""Single-game Performance Rating estimator (inspired by Chess.com Game Rating).

Estimates how well a player performed in a single reviewed game:
- When player/opponent ratings are known:
      performance_rating = anchor_rating + rating_adjustment(game_quality_features)
  with sample-size damping so short games do not produce extreme rating swings.
- When ratings are unknown:
      uses a conservatively calibrated absolute feature curve centered at 1150 Elo
      (typical online club/rapid median) rather than 1450+, tagged with confidence metadata.
- Never overrides move quality with game outcome.
"""
from dataclasses import dataclass
from typing import List, Optional
from .move_classifier import MoveClassification, MoveQuality


@dataclass(frozen=True)
class PerformanceEstimate:
    """Single-game performance rating estimate with confidence & uncertainty metadata."""
    estimated_rating: Optional[int]
    anchor_rating: Optional[int]
    rating_delta: Optional[int]
    confidence: str          # "high", "medium", "low", "insufficient_moves"
    uncertainty_plus_minus: int
    model_version: str = "perf-v2.2-provisional"
    explanation: str = ""


class PerformanceRatingModel:
    """Feature-based single-game performance rating estimator."""

    MIN_SCORED_MOVES = 3

    def estimate_player_performance(
        self,
        player_moves: List[MoveClassification],
        accuracy: float,
        player_rating: Optional[int] = None,
        opponent_rating: Optional[int] = None,
    ) -> PerformanceEstimate:
        valid = [c for c in player_moves if c.quality != MoveQuality.INSUFFICIENT_DATA]
        non_book = [c for c in valid if c.quality != MoveQuality.BOOK]
        if not non_book and valid:
            non_book = valid
        n_moves = len(non_book)

        if n_moves == 0:
            fallback = player_rating or 1150
            return PerformanceEstimate(
                estimated_rating=fallback,
                anchor_rating=player_rating,
                rating_delta=0 if player_rating else None,
                confidence="insufficient_moves",
                uncertainty_plus_minus=400,
                explanation="Insufficient moves to estimate single-game performance rating.",
            )

        avg_ep_loss = sum(getattr(c, "expected_points_loss", c.win_prob_loss) for c in non_book) / n_moves
        blunders = sum(1 for c in non_book if c.quality == MoveQuality.BLUNDER)
        mistakes = sum(1 for c in non_book if c.quality in (MoveQuality.MISTAKE, MoveQuality.MISSED_WIN))
        inaccuracies = sum(1 for c in non_book if c.quality == MoveQuality.INACCURACY)
        great_or_brilliant = sum(1 for c in non_book if c.quality in (MoveQuality.BRILLIANT, MoveQuality.GREAT))
        blunder_rate = blunders / n_moves
        mistake_rate = mistakes / n_moves
        inaccuracy_rate = inaccuracies / n_moves

        anchor: Optional[int] = None
        if player_rating and player_rating > 100 and opponent_rating and opponent_rating > 100:
            anchor = int(round(0.70 * player_rating + 0.30 * opponent_rating))
        elif player_rating and player_rating > 100:
            anchor = int(player_rating)
        elif opponent_rating and opponent_rating > 100:
            anchor = int(opponent_rating)

        # Quality index centered around 80.0% accuracy and 0.040 avg EP loss
        acc_centered = (accuracy - 80.0) / 10.5
        loss_centered = (0.040 - avg_ep_loss) / 0.028
        error_penalty = 2.5 * blunder_rate + 1.15 * mistake_rate + 0.40 * inaccuracy_rate
        tactical_bonus = min(0.95, 0.28 * great_or_brilliant) - error_penalty
        composite_z = 0.52 * acc_centered + 0.28 * loss_centered + 0.20 * tactical_bonus

        # Sample-size damping prevents short games from getting exaggerated rating spikes
        sample_damping = min(1.0, max(0.55, n_moves / 14.0))

        if anchor is not None:
            raw_delta = int(round(composite_z * 155.0 * sample_damping))
            clamped_delta = max(-400, min(400, raw_delta))
            est = max(100, min(3300, anchor + clamped_delta))
            est_rounded = int(round(est / 50.0) * 50)
            conf = "high" if n_moves >= 18 else ("medium" if n_moves >= 8 else "low")
            unc = 120 if conf == "high" else (200 if conf == "medium" else 300)
            return PerformanceEstimate(
                estimated_rating=est_rounded,
                anchor_rating=anchor,
                rating_delta=est_rounded - anchor,
                confidence=conf,
                uncertainty_plus_minus=unc,
                explanation=f"Anchored at {anchor} ({est_rounded - anchor:+d} from {accuracy:.1f}% accuracy).",
            )

        # Unanchored absolute rating curve centered at 1150 Elo (typical online club median)
        base_unanchored = 1150.0 + (composite_z * 310.0 * sample_damping)
        est_unanchored = int(round(max(250.0, min(2650.0, base_unanchored))))
        est_rounded = int(round(est_unanchored / 50.0) * 50)
        conf = "medium" if n_moves >= 15 else ("low" if n_moves >= self.MIN_SCORED_MOVES else "insufficient_moves")
        unc = 220 if conf == "medium" else 350
        return PerformanceEstimate(
            estimated_rating=est_rounded,
            anchor_rating=None,
            rating_delta=None,
            confidence=conf,
            uncertainty_plus_minus=unc,
            explanation=f"Unanchored quality estimate from {accuracy:.1f}% accuracy and {avg_ep_loss:.3f} avg EP loss.",
        )
