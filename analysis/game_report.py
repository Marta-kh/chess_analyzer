"""Summary report generator for full-game Chess.com-Inspired Game Review V2."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from chess_analyzer.engines.engine_models import EngineScore
from .accuracy_model import AccuracyModel
from .event_selector import GameEventSelector, KeyGameEvent
from .move_classifier import MoveClassification, MoveQuality
from .performance_rating import PerformanceEstimate, PerformanceRatingModel


@dataclass(frozen=True)
class PositionAnalysis:
    """Canonical per-position evaluation record (ply 0..N) normalized to White's perspective."""
    ply: int
    fen: str
    turn_color: str
    score_white_pov: EngineScore
    white_cp: int
    expected_points_white: float
    win_prob_white: float
    draw_prob: float
    loss_prob_white: float
    best_move_uci: Optional[str] = None
    best_move_san: Optional[str] = None
    pv_uci: List[str] = field(default_factory=list)
    depth: int = 0


@dataclass
class PlayerSummary:
    color: str
    accuracy_percent: float
    average_cp_loss: float
    game_rating: int = 1200
    counts: Dict[str, int] = field(default_factory=dict)
    average_ep_loss: float = 0.0
    performance: Optional[PerformanceEstimate] = None


@dataclass
class GameAnalysisReport:
    session_id: str
    engine_id: str
    engine_version: str
    system_label: str
    total_plies_analyzed: int
    white_summary: PlayerSummary
    black_summary: PlayerSummary
    classifications: List[MoveClassification]
    eval_curve_white_cp: List[int]
    opening_eco: str = ""
    opening_name: str = "Standard Chess"
    positions: List[PositionAnalysis] = field(default_factory=list)
    selected_events: List[KeyGameEvent] = field(default_factory=list)
    eval_curve_ep_white: List[float] = field(default_factory=list)
    white_rating: Optional[int] = None
    black_rating: Optional[int] = None


def build_game_report(
    session_id: str,
    engine_id: str,
    engine_version: str,
    classifications: List[MoveClassification],
    system_label: str = "Chess.com-Inspired Game Review V2",
    opening_eco: str = "",
    opening_name: str = "Standard Chess",
    positions: Optional[List[PositionAnalysis]] = None,
    white_rating: Optional[int] = None,
    black_rating: Optional[int] = None,
) -> GameAnalysisReport:
    acc_model = AccuracyModel()
    perf_model = PerformanceRatingModel()
    event_selector = GameEventSelector()

    def summarize_side(color: str, player_elo: Optional[int], opp_elo: Optional[int]) -> PlayerSummary:
        side_moves = [
            c for c in classifications
            if c.mover_color == color and c.quality != MoveQuality.INSUFFICIENT_DATA
        ]
        counts = {q.value: 0 for q in MoveQuality}
        for c in classifications:
            if c.mover_color == color:
                counts[c.quality.value] = counts.get(c.quality.value, 0) + 1
                if c.quality == MoveQuality.FORCED:
                    counts[MoveQuality.BEST.value] = counts.get(MoveQuality.BEST.value, 0) + 1

        if not side_moves:
            default_elo = player_elo or 1500
            return PlayerSummary(
                color=color,
                accuracy_percent=100.0,
                average_cp_loss=0.0,
                game_rating=default_elo,
                counts=counts,
                average_ep_loss=0.0,
                performance=PerformanceEstimate(
                    estimated_rating=default_elo,
                    anchor_rating=player_elo,
                    rating_delta=0 if player_elo else None,
                    confidence="insufficient_moves",
                    uncertainty_plus_minus=400,
                ),
            )

        avg_cpl = sum(c.cp_loss for c in side_moves) / len(side_moves)
        avg_epl = sum(getattr(c, "expected_points_loss", c.win_prob_loss) for c in side_moves) / len(side_moves)
        overall_acc = acc_model.compute_player_accuracy(side_moves)
        perf_est = perf_model.estimate_player_performance(
            player_moves=side_moves,
            accuracy=overall_acc,
            player_rating=player_elo,
            opponent_rating=opp_elo,
        )

        return PlayerSummary(
            color=color,
            accuracy_percent=overall_acc,
            average_cp_loss=round(avg_cpl, 1),
            game_rating=perf_est.estimated_rating or 1200,
            counts=counts,
            average_ep_loss=round(avg_epl, 4),
            performance=perf_est,
        )

    eval_curve: List[int] = []
    ep_curve: List[float] = []
    for c in classifications:
        if c.eval_after is not None:
            w_cp = c.eval_after.white_cp
            if w_cp is not None:
                eval_curve.append(max(-1000, min(1000, w_cp)))
            elif c.eval_after.white_mate is not None:
                eval_curve.append(1000 if c.eval_after.white_mate > 0 else -1000)
            else:
                eval_curve.append(0)
        else:
            eval_curve.append(0)
        ep_w = c.expected_points_after if c.mover_color == "white" else (1.0 - c.expected_points_after)
        ep_curve.append(round(ep_w, 4))

    selected_events = event_selector.select_events(classifications)

    return GameAnalysisReport(
        session_id=session_id,
        engine_id=engine_id,
        engine_version=engine_version,
        system_label=system_label,
        total_plies_analyzed=len(classifications),
        white_summary=summarize_side("white", white_rating, black_rating),
        black_summary=summarize_side("black", black_rating, white_rating),
        classifications=list(classifications),
        eval_curve_white_cp=eval_curve,
        opening_eco=opening_eco,
        opening_name=opening_name,
        positions=list(positions) if positions else [],
        selected_events=selected_events,
        eval_curve_ep_white=ep_curve,
        white_rating=white_rating,
        black_rating=black_rating,
    )
