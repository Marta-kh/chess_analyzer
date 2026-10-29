"""
Chess.com-inspired Move Classification V2.2 Engine with Conservative Multi-Gate Brilliant Detection.
Supports all 10 scorecard categories from the Game Review table:
Brilliant (!!), Great (!), Best (★), Excellent (✓+), Good (✓), Book (B),
Inaccuracy (?!), Mistake (?), Miss / Missed Win (×), and Blunder (??), plus Forced (→).

Implements:
1. Configurable Expected-Points Loss cutoffs (with floating-point tolerance):
   - Best: loss == 0.00
   - Excellent: 0.00 < loss <= 0.02
   - Good: 0.02 < loss <= 0.05
   - Inaccuracy: 0.05 < loss <= 0.10
   - Mistake: 0.10 < loss <= 0.20
   - Blunder: loss > 0.20
2. Strict 6-Gate Brilliant Eligibility Evaluator + Conservative Eligibility Score + Diagnostics:
   - Gate 1 (Engine Quality): Must be Best or near-best within tight EP/CP tolerance.
   - Gate 2 (Sound Sacrifice): Must intentionally offer/sacrifice net material (verified via legal
     opponent capture & Static Exchange net-gain analysis), rejecting ordinary captures, equal trades,
     forced recaptures, and pre-existing multi-piece blunders.
   - Gate 3 (Concrete Compensation): Post-move evaluation must confirm forced mate or strong compensation.
   - Gate 4 (Exceptional Justification): Must be non-forced and demonstrate tactical/strategic superiority.
   - Gate 5 (Position Context): Rejects moves in already trivially winning positions unless forcing mate.
   - Gate 6 (Reliable Analysis): Requires sufficient search depth and post-move evaluation stability.
3. Distinct detectors and strict precedence for Book, Brilliant, Great, Miss, and Ordinary labels.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import chess
from chess_analyzer.engines.engine_models import CandidateVariation, EngineScore
from .evaluator import EvaluationComparison, PositionEvaluator


class MoveQuality(str, Enum):
    BRILLIANT = "Brilliant"
    GREAT = "Great"
    BEST = "Best"
    EXCELLENT = "Excellent"
    GOOD = "Good"
    BOOK = "Book"
    FORCED = "Forced"
    INACCURACY = "Inaccuracy"
    MISTAKE = "Mistake"
    MISSED_WIN = "Missed Win"
    MISS = "Missed Win"  # Alias so MoveQuality.MISS and MoveQuality.MISSED_WIN work interchangeably
    BLUNDER = "Blunder"
    INSUFFICIENT_DATA = "Unclassified"


QUALITY_BADGES: Dict[MoveQuality, Tuple[str, str]] = {
    MoveQuality.BRILLIANT: ("!!", "Brilliant Move"),
    MoveQuality.GREAT: ("!", "Great Move"),
    MoveQuality.BEST: ("★", "Best Move"),
    MoveQuality.EXCELLENT: ("✓+", "Excellent Move"),
    MoveQuality.GOOD: ("✓", "Good Move"),
    MoveQuality.BOOK: ("B", "Book Move"),
    MoveQuality.FORCED: ("→", "Forced Move"),
    MoveQuality.INACCURACY: ("?!", "Inaccuracy"),
    MoveQuality.MISTAKE: ("?", "Mistake"),
    MoveQuality.MISSED_WIN: ("×", "Miss / Missed Win"),
    MoveQuality.BLUNDER: ("??", "Blunder"),
    MoveQuality.INSUFFICIENT_DATA: ("·", "Not Analyzed"),
}

SCORECARD_ROWS: List[Tuple[str, MoveQuality, str, Tuple[float, float, float, float]]] = [
    ("Brilliant", MoveQuality.BRILLIANT, "!!", (0.106, 0.675, 0.651, 1.0)),    # Teal #1BACA6
    ("Great", MoveQuality.GREAT, "!", (0.361, 0.545, 0.690, 1.0)),             # Sky Blue #5C8BB0
    ("Best", MoveQuality.BEST, "★", (0.506, 0.714, 0.298, 1.0)),               # Bright Green #81B64C
    ("Excellent", MoveQuality.EXCELLENT, "✓+", (0.588, 0.737, 0.294, 1.0)),    # Lime Green #96BC4B
    ("Good", MoveQuality.GOOD, "✓", (0.592, 0.686, 0.545, 1.0)),               # Sage Green #97AF8B
    ("Book", MoveQuality.BOOK, "B", (0.659, 0.533, 0.396, 1.0)),               # Bronze/Tan #A88865
    ("Inaccuracy", MoveQuality.INACCURACY, "?!", (0.969, 0.776, 0.192, 1.0)),  # Gold #F7C631
    ("Mistake", MoveQuality.MISTAKE, "?", (0.898, 0.561, 0.165, 1.0)),         # Orange #E58F2A
    ("Miss", MoveQuality.MISSED_WIN, "×", (0.945, 0.357, 0.357, 1.0)),         # Coral Red #F15B5B
    ("Blunder", MoveQuality.BLUNDER, "??", (0.792, 0.204, 0.192, 1.0)),        # Crimson #CA3431
]


PIECE_VALUES_CP: Dict[int, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 315,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


@dataclass
class BrilliantEligibilityConfig:
    """Configurable thresholds and mandatory gate parameters for conservative Brilliant detection."""
    # Gate 1: Engine quality tolerance
    max_ep_loss: float = 0.015
    max_cp_loss: int = 20
    # Gate 2: Material sacrifice threshold (centipawns)
    min_net_sacrifice_cp: int = 180
    min_mating_sacrifice_cp: int = 100
    # Gate 3: Concrete compensation after the sacrifice
    min_ep_after: float = 0.48
    min_eval_after_cp: int = -35
    # Gate 4: Exceptional tactical/strategic justification
    min_uniqueness_ep_gap: float = 0.03
    min_uniqueness_cp_gap: int = 35
    # Gate 5: Position context (do not award in already trivially winning positions unless forcing mate)
    max_ep_before: float = 0.88
    max_eval_before_cp: int = 350
    max_winning_eval_drop_cp: int = 25
    # Gate 6: Reliable engine search depth
    min_depth: int = 6
    # Conservative composite score cutoff (applied only if all 6 mandatory gates pass)
    min_eligibility_score: float = 0.65


@dataclass
class BrilliantEligibilityResult:
    """Detailed diagnostic record explaining why a candidate move passed or failed Brilliant eligibility."""
    passed_all_gates: bool = False
    is_eligible: bool = False
    eligibility_score: float = 0.0
    failed_gates: List[str] = field(default_factory=list)
    gate_1_engine_quality: bool = False
    gate_2_sound_sacrifice: bool = False
    gate_3_concrete_compensation: bool = False
    gate_4_exceptional_justification: bool = False
    gate_5_position_context: bool = False
    gate_6_reliable_analysis: bool = False
    sacrifice_detected: bool = False
    sacrifice_type: str = "none"
    sacrificed_material_cp: int = 0
    eval_before_cp: int = 0
    eval_after_cp: int = 0
    ep_before: float = 0.5
    ep_after: float = 0.5
    ep_loss: float = 0.0
    search_depth: int = 0
    engine_confidence: str = "low"
    compensation_evidence: str = ""
    summary_reason: str = ""


@dataclass
class _SacrificeCandidateInfo:
    is_sacrifice: bool = False
    sacrifice_type: str = "none"
    sacrificed_material_cp: int = 0
    is_forced_recapture: bool = False
    details: str = ""


@dataclass
class ClassificationThresholds:
    """Configurable V2 expected-points loss cutoffs and special-detector parameters."""
    model_version: str = "v2.2-expected-points-conservative-brilliant"
    # Baseline Expected-Points Loss cutoffs (Section 1):
    # Best: loss == 0.00 | Excellent: <= 0.02 | Good: <= 0.05 | Inaccuracy: <= 0.10 | Mistake: <= 0.20 | Blunder: > 0.20
    best_max_ep_loss: float = 0.00
    excellent_max_ep_loss: float = 0.02
    good_max_ep_loss: float = 0.05
    inaccuracy_max_ep_loss: float = 0.10
    mistake_max_ep_loss: float = 0.20
    float_eps: float = 1e-9
    # Centipawn guardrails
    best_max_cp_loss: int = 0
    excellent_max_cp_loss: int = 25
    good_max_cp_loss: int = 55
    inaccuracy_max_cp_loss: int = 110
    mistake_max_cp_loss: int = 240
    winning_advantage_cp: int = 220
    missed_win_drop_below_cp: int = 95
    min_required_depth: int = 1
    # Great move detector thresholds
    great_uniqueness_ep_gap: float = 0.12
    great_uniqueness_cp_gap: int = 150
    great_max_ep_before: float = 0.85
    great_max_eval_before_cp: int = 300
    # Miss detector thresholds
    miss_min_ep_before: float = 0.68
    miss_max_ep_after: float = 0.60
    miss_min_ep_after: float = 0.22
    miss_min_ep_loss: float = 0.10
    # Conservative Brilliant configuration
    brilliant: BrilliantEligibilityConfig = field(default_factory=BrilliantEligibilityConfig)


@dataclass
class MoveClassification:
    """Complete classification record for a single ply in a game."""
    ply: int
    played_uci: str
    played_san: str
    mover_color: str
    quality: MoveQuality
    badge_symbol: str
    badge_text: str
    eval_before: Optional[EngineScore]
    eval_after: Optional[EngineScore]
    best_move_uci: Optional[str]
    best_move_san: Optional[str]
    cp_loss: int
    win_prob_loss: float
    engine_id: str
    engine_version: str
    search_depth: int
    confidence: str
    explanation: str
    # V2 extended fields
    ordinary_classification: MoveQuality = MoveQuality.GOOD
    expected_points_before: float = 0.5
    expected_points_after: float = 0.5
    expected_points_loss: float = 0.0
    win_prob_before: float = 0.5
    draw_prob_before: float = 0.0
    loss_prob_before: float = 0.5
    win_prob_after: float = 0.5
    draw_prob_after: float = 0.0
    loss_prob_after: float = 0.5
    special_flags: List[str] = field(default_factory=list)
    negative_loss_detected: bool = False
    brilliant_diagnostics: Optional[BrilliantEligibilityResult] = None


class MoveClassifier:
    """Classifies moves using Expected-Points V2 cutoffs and strict special-move detectors."""

    SYSTEM_LABEL = "Chess.com-Inspired Game Review V2.2 (Local Stockfish Evaluation)"

    def __init__(self, thresholds: Optional[ClassificationThresholds] = None) -> None:
        self.thresholds = thresholds or ClassificationThresholds()

    def _classify_ordinary_v2(
        self,
        is_exact_best: bool,
        ep_loss: float,
        cp_loss: int,
        comp: EvaluationComparison,
    ) -> MoveQuality:
        """Applies baseline Expected-Points Loss cutoffs with floating-point tolerance."""
        t = self.thresholds
        eps = t.float_eps
        if (comp.mate_before is None or comp.mate_before >= 0) and (comp.mate_after is not None and comp.mate_after < 0):
            return MoveQuality.BLUNDER

        if is_exact_best or (ep_loss <= t.best_max_ep_loss + eps and cp_loss <= t.best_max_cp_loss):
            return MoveQuality.BEST
        if ep_loss <= t.excellent_max_ep_loss + eps:
            return MoveQuality.EXCELLENT
        if ep_loss <= t.good_max_ep_loss + eps:
            return MoveQuality.GOOD
        if ep_loss <= t.inaccuracy_max_ep_loss + eps:
            return MoveQuality.INACCURACY
        if ep_loss <= t.mistake_max_ep_loss + eps:
            return MoveQuality.MISTAKE
        return MoveQuality.BLUNDER

    @staticmethod
    def _net_exposure_on_square(
        board: chess.Board,
        sq: chess.Square,
        piece_color: chess.Color,
    ) -> int:
        """
        Calculates how many centipawns the opponent can profitably win by legally capturing
        the piece on `sq` on `board` (where `board.turn == (not piece_color)`).
        Accounts for pinned attackers (via `board.legal_moves`) and whether `sq` is defended.
        """
        target_p = board.piece_at(sq)
        if target_p is None or target_p.color != piece_color:
            return 0
        target_val = PIECE_VALUES_CP.get(target_p.piece_type, 0)
        if target_val <= 0:
            return 0

        legal_caps = [m for m in board.legal_moves if m.to_square == sq]
        if not legal_caps:
            return 0

        attacker_vals = []
        for m in legal_caps:
            att_p = board.piece_at(m.from_square)
            if att_p is not None:
                att_v = PIECE_VALUES_CP.get(att_p.piece_type, 0)
                # King can only capture if square is undefended (already enforced by legal_moves)
                attacker_vals.append(att_v)
        if not attacker_vals:
            return 0

        min_attacker_val = min(attacker_vals)
        is_defended = board.is_attacked_by(piece_color, sq)
        if not is_defended:
            return target_val
        if min_attacker_val == 0:
            return target_val
        return max(0, target_val - min_attacker_val)

    @classmethod
    def _analyze_sacrifice(
        cls,
        fen_before: Optional[str],
        played_uci: str,
        mover_color: str,
    ) -> _SacrificeCandidateInfo:
        """
        Analyzes whether `played_uci` on `fen_before` is a genuine, intentional material sacrifice.
        Distinguishes true sacrifices from:
        - Ordinary captures and equal/winning exchanges
        - Defended developments onto squares attacked only by equal/higher-value enemy pieces
        - Pre-existing blunders where multiple pieces were already hanging before the move
        """
        if not fen_before:
            return _SacrificeCandidateInfo(is_sacrifice=False, sacrifice_type="no_fen", details="No FEN provided.")
        try:
            board_before = chess.Board(fen_before)
            move = chess.Move.from_uci(played_uci)
            if move not in board_before.legal_moves:
                return _SacrificeCandidateInfo(is_sacrifice=False, sacrifice_type="illegal_move", details="Move not legal.")

            mover_chess_color = chess.WHITE if mover_color.lower().startswith("w") else chess.BLACK
            moving_piece = board_before.piece_at(move.from_square)
            if moving_piece is None:
                return _SacrificeCandidateInfo(is_sacrifice=False, sacrifice_type="no_piece")

            moving_val = PIECE_VALUES_CP.get(moving_piece.piece_type, 0)
            if board_before.is_en_passant(move):
                captured_val = PIECE_VALUES_CP[chess.PAWN]
            else:
                cap_p = board_before.piece_at(move.to_square)
                captured_val = PIECE_VALUES_CP.get(cap_p.piece_type, 0) if cap_p else 0

            # Measure pre-existing hanging pieces on board_before (by flipping turn to opponent if not in check)
            hanging_before_squares: Dict[chess.Square, int] = {}
            if not board_before.is_check():
                b_probe = board_before.copy(stack=False)
                b_probe.turn = not mover_chess_color
                for sq in chess.SQUARES:
                    p = b_probe.piece_at(sq)
                    if p is not None and p.color == mover_chess_color and PIECE_VALUES_CP.get(p.piece_type, 0) >= 300:
                        exp = cls._net_exposure_on_square(b_probe, sq, mover_chess_color)
                        if exp >= 180:
                            hanging_before_squares[sq] = exp

            board_after = board_before.copy(stack=False)
            board_after.push(move)

            # 1. Check direct sacrifice of the moved piece on `move.to_square`
            dest_exposure = cls._net_exposure_on_square(board_after, move.to_square, mover_chess_color)
            net_dest_sac = dest_exposure - captured_val

            if captured_val > 0 and dest_exposure == 0:
                # Moving piece captured material and cannot be profitably captured back
                pass
            elif captured_val > 0 and net_dest_sac <= 50:
                # Ordinary capture or equal/favorable recapture (e.g. NxN, BxN, RxR, QxQ, PxP)
                return _SacrificeCandidateInfo(
                    is_sacrifice=False,
                    sacrifice_type="ordinary_capture",
                    sacrificed_material_cp=0,
                    is_forced_recapture=True,
                    details=f"Capture of {captured_val}cp with {moving_val}cp is an equal/favorable trade, not a sacrifice.",
                )

            if net_dest_sac >= 100 and moving_piece.piece_type != chess.KING:
                return _SacrificeCandidateInfo(
                    is_sacrifice=True,
                    sacrifice_type="direct_piece_offer",
                    sacrificed_material_cp=net_dest_sac,
                    details=f"Moved {moving_piece.symbol()} ({moving_val}cp) to {chess.square_name(move.to_square)} offering {net_dest_sac}cp net material.",
                )

            # 2. Check indirect sacrifice (leaving another friendly minor/major piece en prise on sq != move.to_square)
            # If >= 2 friendly pieces were already hanging before the move, saving one is damage control, not a sacrifice.
            if len(hanging_before_squares) >= 2:
                return _SacrificeCandidateInfo(
                    is_sacrifice=False,
                    sacrifice_type="preexisting_multi_piece_blunder",
                    details="Multiple friendly pieces were already hanging before this move.",
                )

            best_indirect_sac = 0
            best_indirect_sq: Optional[chess.Square] = None
            for sq in chess.SQUARES:
                if sq == move.to_square:
                    continue
                p = board_after.piece_at(sq)
                if p is None or p.color != mover_chess_color:
                    continue
                p_val = PIECE_VALUES_CP.get(p.piece_type, 0)
                if p_val < 300:
                    continue
                exp_after = cls._net_exposure_on_square(board_after, sq, mover_chess_color)
                net_indirect = exp_after - captured_val
                if net_indirect < 180:
                    continue

                was_hanging_before = sq in hanging_before_squares
                if was_hanging_before:
                    # Only count leaving a previously attacked piece en prise if the played move is an active
                    # counter-attacking / checking / tactical move rather than a passive retreat of another piece.
                    gives_check = board_after.is_check()
                    creates_threat = False
                    for sq_enemy in chess.SQUARES:
                        ep_piece = board_after.piece_at(sq_enemy)
                        if ep_piece and ep_piece.color != mover_chess_color and PIECE_VALUES_CP.get(ep_piece.piece_type, 0) >= 300:
                            if board_after.is_attacked_by(mover_chess_color, sq_enemy):
                                creates_threat = True
                                break
                    if not (gives_check or creates_threat or captured_val >= 100):
                        continue

                if net_indirect > best_indirect_sac:
                    best_indirect_sac = net_indirect
                    best_indirect_sq = sq

            if best_indirect_sac >= 180 and best_indirect_sq is not None:
                return _SacrificeCandidateInfo(
                    is_sacrifice=True,
                    sacrifice_type="positional_piece_offer",
                    sacrificed_material_cp=best_indirect_sac,
                    details=f"Left piece on {chess.square_name(best_indirect_sq)} exposed for {best_indirect_sac}cp net sacrifice.",
                )

            return _SacrificeCandidateInfo(
                is_sacrifice=False,
                sacrifice_type="ordinary_capture" if captured_val > 0 else "none",
                sacrificed_material_cp=0,
                details="No net material sacrifice detected.",
            )
        except Exception as exc:
            return _SacrificeCandidateInfo(is_sacrifice=False, sacrifice_type="error", details=str(exc))

    @classmethod
    def _is_sound_material_sacrifice(
        cls,
        fen_before: Optional[str],
        played_uci: str,
        mover_color: str,
    ) -> bool:
        """Backward-compatible helper returning True when `_analyze_sacrifice` finds a >= 180cp material sacrifice."""
        info = cls._analyze_sacrifice(fen_before, played_uci, mover_color)
        return info.is_sacrifice and info.sacrificed_material_cp >= 180

    def evaluate_brilliant_eligibility(
        self,
        *,
        fen_before: Optional[str],
        played_uci: str,
        played_san: str,
        mover_color: str,
        legal_moves_count: int,
        ordinary_quality: MoveQuality,
        is_exact_best: bool,
        ep_before: float,
        ep_after: float,
        ep_loss: float,
        cp_loss: int,
        comp: EvaluationComparison,
        best_var: CandidateVariation,
        uniqueness_ep_gap: float,
        uniqueness_cp_gap: int,
        num_variations: int,
        confidence: str,
        is_book: bool = False,
        is_terminal_draw_after: bool = False,
    ) -> BrilliantEligibilityResult:
        """
        Evaluates all 6 mandatory Brilliant gates and computes a conservative eligibility score.
        A high eligibility score can NEVER override a failed mandatory gate.
        """
        bc = self.thresholds.brilliant
        eps = self.thresholds.float_eps
        sac_info = self._analyze_sacrifice(fen_before, played_uci, mover_color)

        forces_mate = comp.mate_after is not None and comp.mate_after > 0
        loses_mate = (
            comp.mate_before is not None
            and comp.mate_before > 0
            and (comp.mate_after is None or comp.mate_after <= 0 or comp.mate_after > comp.mate_before + 1)
        )

        # Gate 1: Engine quality (must be Best/Excellent and within strict EP/CP loss tolerance, never Book)
        gate_1 = (
            not is_book
            and ordinary_quality in (MoveQuality.BEST, MoveQuality.EXCELLENT)
            and ep_loss <= bc.max_ep_loss + eps
            and cp_loss <= bc.max_cp_loss
            and not loses_mate
        )

        # Gate 2: Sound intentional material sacrifice
        min_sac_req = bc.min_mating_sacrifice_cp if forces_mate else bc.min_net_sacrifice_cp
        gate_2 = (
            sac_info.is_sacrifice
            and not sac_info.is_forced_recapture
            and sac_info.sacrificed_material_cp >= min_sac_req
        )

        # Gate 3: Concrete compensation confirmed after the sacrifice
        saving_draw_from_lost = is_terminal_draw_after and ep_before <= 0.22
        gate_3 = (
            forces_mate
            or saving_draw_from_lost
            or (
                not is_terminal_draw_after
                and ep_after >= bc.min_ep_after - eps
                and comp.eval_after_cp >= bc.min_eval_after_cp
                and (comp.mate_after is None or comp.mate_after > 0)
            )
        )

        # Gate 4: Exceptional tactical or strategic justification (not forced, clear purpose)
        has_uniqueness = (
            uniqueness_ep_gap >= bc.min_uniqueness_ep_gap - eps
            or uniqueness_cp_gap >= bc.min_uniqueness_cp_gap
        )
        single_line_strong_initiative = (
            num_variations == 1
            and is_exact_best
            and (forces_mate or (comp.eval_after_cp >= 80 and len(best_var.pv_uci) >= 2))
        )
        gate_4 = (
            legal_moves_count > 1
            and not sac_info.is_forced_recapture
            and (forces_mate or has_uniqueness or single_line_strong_initiative)
        )

        # Gate 5: Position context (do not award in already completely winning positions unless forcing mate;
        # never award if a winning position becomes noticeably less winning)
        not_already_trivially_won = (
            ep_before <= bc.max_ep_before + eps
            and comp.eval_before_cp <= bc.max_eval_before_cp
        ) or (
            forces_mate
            and (comp.mate_before is None or comp.mate_after <= comp.mate_before)
        )
        preserves_or_improves_win = not (
            comp.eval_before_cp >= 200
            and not forces_mate
            and comp.eval_after_cp < comp.eval_before_cp - bc.max_winning_eval_drop_cp
        )
        gate_5 = not_already_trivially_won and preserves_or_improves_win

        # Gate 6: Reliable analysis depth & stability across before/after evaluations
        post_move_refuted = (
            (comp.mate_before is None and comp.mate_after is not None and comp.mate_after < 0)
            or comp.expected_points_loss > bc.max_ep_loss + eps
            or comp.cp_loss > bc.max_cp_loss
        )
        gate_6 = best_var.depth >= bc.min_depth and not post_move_refuted

        failed_gates: List[str] = []
        if not gate_1:
            failed_gates.append("gate_1_engine_quality")
        if not gate_2:
            failed_gates.append("gate_2_sound_sacrifice")
        if not gate_3:
            failed_gates.append("gate_3_concrete_compensation")
        if not gate_4:
            failed_gates.append("gate_4_exceptional_justification")
        if not gate_5:
            failed_gates.append("gate_5_position_context")
        if not gate_6:
            failed_gates.append("gate_6_reliable_analysis")

        passed_all = len(failed_gates) == 0

        # Compute conservative composite eligibility score in [0.0, 1.0]
        q_factor = 1.0 if is_exact_best else max(0.0, 1.0 - (ep_loss / max(0.001, bc.max_ep_loss)))
        sac_factor = min(1.0, sac_info.sacrificed_material_cp / 300.0) if sac_info.is_sacrifice else 0.0
        if forces_mate:
            comp_factor = 1.0
        elif saving_draw_from_lost:
            comp_factor = 0.85
        else:
            comp_factor = min(1.0, max(0.0, (ep_after - 0.42) / 0.35))
        if forces_mate or uniqueness_cp_gap >= 140:
            just_factor = 1.0
        elif num_variations >= 2:
            just_factor = min(1.0, max(0.25, uniqueness_cp_gap / 140.0))
        else:
            just_factor = 0.75 if single_line_strong_initiative else 0.25
        depth_factor = min(1.0, best_var.depth / 10.0) if best_var.depth >= bc.min_depth else 0.0

        score = round(
            0.20 * q_factor
            + 0.25 * sac_factor
            + 0.25 * comp_factor
            + 0.15 * just_factor
            + 0.15 * depth_factor,
            4,
        )
        is_eligible = passed_all and (score + eps >= bc.min_eligibility_score)

        if forces_mate:
            comp_ev = f"Forces checkmate in {comp.mate_after} after sacrificing {sac_info.sacrificed_material_cp}cp."
        elif gate_3:
            comp_ev = f"Sustains {ep_after:.2f} expected points ({comp.eval_after_cp:+d}cp) after {sac_info.sacrificed_material_cp}cp sacrifice."
        else:
            comp_ev = f"Insufficient compensation ({ep_after:.2f} EP, {comp.eval_after_cp:+d}cp)."

        if is_eligible:
            reason = f"Passed all 6 mandatory Brilliant gates (score={score:.2f}): {sac_info.details} {comp_ev}"
        else:
            reason = f"Rejected ({', '.join(failed_gates) or 'score_below_threshold'}, score={score:.2f}): {sac_info.details}"

        return BrilliantEligibilityResult(
            passed_all_gates=passed_all,
            is_eligible=is_eligible,
            eligibility_score=score,
            failed_gates=failed_gates,
            gate_1_engine_quality=gate_1,
            gate_2_sound_sacrifice=gate_2,
            gate_3_concrete_compensation=gate_3,
            gate_4_exceptional_justification=gate_4,
            gate_5_position_context=gate_5,
            gate_6_reliable_analysis=gate_6,
            sacrifice_detected=sac_info.is_sacrifice,
            sacrifice_type=sac_info.sacrifice_type,
            sacrificed_material_cp=sac_info.sacrificed_material_cp,
            eval_before_cp=comp.eval_before_cp,
            eval_after_cp=comp.eval_after_cp,
            ep_before=ep_before,
            ep_after=ep_after,
            ep_loss=ep_loss,
            search_depth=best_var.depth,
            engine_confidence=confidence,
            compensation_evidence=comp_ev,
            summary_reason=reason,
        )

    def classify_move(
        self,
        ply: int,
        played_uci: str,
        played_san: str,
        mover_color: str,
        legal_moves_count: int,
        variations_before: List[CandidateVariation],
        score_after: Optional[EngineScore],
        engine_id: str,
        engine_version: str,
        fen_before: Optional[str] = None,
        is_book_line: Optional[bool] = None,
        previous_ep_for_mover: Optional[float] = None,
        player_rating: Optional[int] = None,
        is_terminal_draw_after: bool = False,
    ) -> MoveClassification:
        if not variations_before or score_after is None:
            sym, txt = QUALITY_BADGES[MoveQuality.INSUFFICIENT_DATA]
            return MoveClassification(
                ply=ply,
                played_uci=played_uci,
                played_san=played_san,
                mover_color=mover_color,
                quality=MoveQuality.INSUFFICIENT_DATA,
                badge_symbol=sym,
                badge_text=txt,
                eval_before=None,
                eval_after=score_after,
                best_move_uci=None,
                best_move_san=None,
                cp_loss=0,
                win_prob_loss=0.0,
                engine_id=engine_id,
                engine_version=engine_version,
                search_depth=0,
                confidence="insufficient",
                explanation="Insufficient engine analysis data to classify this move.",
            )

        best_var = variations_before[0]
        if best_var.depth < self.thresholds.min_required_depth:
            sym, txt = QUALITY_BADGES[MoveQuality.INSUFFICIENT_DATA]
            return MoveClassification(
                ply=ply,
                played_uci=played_uci,
                played_san=played_san,
                mover_color=mover_color,
                quality=MoveQuality.INSUFFICIENT_DATA,
                badge_symbol=sym,
                badge_text=txt,
                eval_before=best_var.score,
                eval_after=score_after,
                best_move_uci=best_var.best_move_uci,
                best_move_san=best_var.best_move_san,
                cp_loss=0,
                win_prob_loss=0.0,
                engine_id=engine_id,
                engine_version=engine_version,
                search_depth=best_var.depth,
                confidence="insufficient",
                explanation=f"Search depth ({best_var.depth}) below minimum threshold.",
            )

        t = self.thresholds
        eps = t.float_eps
        comp: EvaluationComparison = PositionEvaluator.compare(
            score_before=best_var.score,
            score_after=score_after,
            mover_color=mover_color,
            player_rating=player_rating,
            is_terminal_draw_after=is_terminal_draw_after,
        )
        confidence = "high" if best_var.depth >= 10 else ("medium" if best_var.depth >= 6 else "low")
        best_san_str = best_var.best_move_san or best_var.best_move_uci or "best move"
        pv_preview = " ".join(best_var.pv_san[:4]) if best_var.pv_san else best_san_str

        is_exact_best = best_var.best_move_uci == played_uci
        ep_before = comp.expected_points_before
        ep_after = comp.expected_points_after
        # If the played move is the engine's top move, clamp horizon noise only when score_after did not refute it
        post_move_drop = comp.expected_points_loss
        if is_exact_best and post_move_drop <= t.brilliant.max_ep_loss + eps and comp.cp_loss <= t.brilliant.max_cp_loss:
            ep_loss = 0.0
            cp_loss = 0
        else:
            ep_loss = comp.expected_points_loss
            cp_loss = comp.cp_loss

        ordinary_q = self._classify_ordinary_v2(
            is_exact_best and ep_loss <= eps,
            ep_loss,
            cp_loss,
            comp,
        )
        special_flags: List[str] = []
        if comp.negative_loss_detected and not is_exact_best:
            special_flags.append("negative_loss_clamped")

        # Uniqueness gap vs 2nd best variation
        uniqueness_ep_gap = 0.0
        uniqueness_cp_gap = 0
        if len(variations_before) >= 2:
            sec_comp = PositionEvaluator.compare(
                score_before=best_var.score,
                score_after=variations_before[1].score,
                mover_color=mover_color,
                player_rating=player_rating,
            )
            uniqueness_ep_gap = sec_comp.expected_points_loss
            uniqueness_cp_gap = sec_comp.cp_loss

        brilliant_diag: Optional[BrilliantEligibilityResult] = None

        # 0. Forced move (only 1 legal move in position)
        if legal_moves_count == 1:
            quality = MoveQuality.FORCED
            special_flags.append("forced_only_legal_move")
            explanation = f"{played_san} was the only legal move available in this position."
        else:
            # 1. Book move detector (strictly requires opening database match via is_book_line is True)
            is_book = False
            if is_book_line is True and ep_loss <= t.good_max_ep_loss + eps:
                is_book = True
                special_flags.append("opening_book")

            # 2. Conservative Multi-Gate Brilliant detector
            brilliant_diag = self.evaluate_brilliant_eligibility(
                fen_before=fen_before,
                played_uci=played_uci,
                played_san=played_san,
                mover_color=mover_color,
                legal_moves_count=legal_moves_count,
                ordinary_quality=ordinary_q,
                is_exact_best=is_exact_best,
                ep_before=ep_before,
                ep_after=ep_after,
                ep_loss=ep_loss,
                cp_loss=cp_loss,
                comp=comp,
                best_var=best_var,
                uniqueness_ep_gap=uniqueness_ep_gap,
                uniqueness_cp_gap=uniqueness_cp_gap,
                num_variations=len(variations_before),
                confidence=confidence,
                is_book=is_book,
                is_terminal_draw_after=is_terminal_draw_after,
            )
            is_brilliant = brilliant_diag.is_eligible
            if is_brilliant:
                special_flags.append("brilliant_sacrifice")

            # 3. Great move detector (distinct from Brilliant: critical turning-point / defensive resource)
            # Never awarded for routine best moves in already winning positions.
            is_great = False
            if (
                not is_book
                and not is_brilliant
                and ordinary_q in (MoveQuality.BEST, MoveQuality.EXCELLENT)
                and ep_before <= t.great_max_ep_before + eps
                and comp.eval_before_cp <= t.great_max_eval_before_cp
                and ep_after >= 0.42
            ):
                if (
                    (uniqueness_ep_gap >= t.great_uniqueness_ep_gap - eps or uniqueness_cp_gap >= t.great_uniqueness_cp_gap)
                    and comp.eval_before_cp >= -250
                ):
                    is_great = True
                    special_flags.append("only_good_move")
                elif (
                    previous_ep_for_mover is not None
                    and previous_ep_for_mover <= 0.50
                    and ep_after >= 0.70
                    and is_exact_best
                    and uniqueness_ep_gap >= 0.06
                ):
                    is_great = True
                    special_flags.append("critical_conversion")

            # 4. Miss / Missed Win detector
            # Awarded only when the position had a clear winning / mate opportunity (created by opponent's mistake)
            # and the played move forfeited that opportunity to an equal/unclear game without blundering into a lost position.
            is_miss = False
            if (
                not is_book
                and not is_brilliant
                and not is_great
                and not is_exact_best
                and ordinary_q in (MoveQuality.INACCURACY, MoveQuality.MISTAKE, MoveQuality.BLUNDER)
            ):
                missed_forced_mate = (
                    comp.mate_before is not None
                    and comp.mate_before > 0
                    and (comp.mate_after is None or comp.mate_after <= 0)
                    and -90 <= comp.eval_after_cp < t.winning_advantage_cp
                )
                missed_winning_opportunity = (
                    (ep_before >= t.miss_min_ep_before - eps or comp.eval_before_cp >= t.winning_advantage_cp)
                    and (
                        -120 <= comp.eval_after_cp <= t.missed_win_drop_below_cp
                        or (t.miss_min_ep_after <= ep_after <= t.miss_max_ep_after)
                    )
                    and (ep_loss >= t.miss_min_ep_loss - eps or cp_loss >= t.inaccuracy_max_cp_loss)
                    and (comp.mate_after is None or comp.mate_after >= 0)
                )
                if missed_forced_mate or missed_winning_opportunity:
                    is_miss = True
                    special_flags.append("missed_mate" if missed_forced_mate else "missed_tactical_win")

            # 5. Apply Consistent Precedence Policy:
            # Book -> Brilliant (only when Best/Excellent + all 6 gates) -> Great -> Miss -> Ordinary V2
            if is_book:
                quality = MoveQuality.BOOK
                explanation = f"{played_san} is a theoretical opening book move ({pv_preview})."
            elif is_brilliant:
                quality = MoveQuality.BRILLIANT
                if comp.mate_after is not None and comp.mate_after > 0:
                    explanation = (
                        f"{played_san} is a brilliant mating sacrifice ({brilliant_diag.sacrificed_material_cp}cp offered) "
                        f"forcing checkmate in {comp.mate_after}!"
                    )
                else:
                    explanation = (
                        f"{played_san} is a brilliant material sacrifice ({brilliant_diag.sacrificed_material_cp}cp offered) "
                        f"with strong compensation ({ep_after:.2f} EP)!"
                    )
            elif is_great:
                quality = MoveQuality.GREAT
                explanation = f"{played_san} found the critical resource (+{uniqueness_cp_gap / 100:.1f} pawns over the next option)."
            elif is_miss:
                quality = MoveQuality.MISSED_WIN
                if comp.mate_before is not None and comp.mate_before > 0:
                    explanation = f"{played_san} missed forced mate in {comp.mate_before} ({best_san_str}), letting the opponent escape."
                else:
                    explanation = f"{played_san} missed a winning opportunity (-{ep_loss:.2f} EP). Best was {best_san_str} ({pv_preview})."
            else:
                if (
                    comp.mate_before is not None
                    and comp.mate_before > 0
                    and (comp.mate_after is None or comp.mate_after < 0)
                    and comp.eval_after_cp >= t.winning_advantage_cp
                ):
                    quality = MoveQuality.INACCURACY
                    ordinary_q = MoveQuality.INACCURACY
                    explanation = f"{played_san} missed a faster forced mate ({best_san_str}), though the position stays winning."
                else:
                    quality = ordinary_q
                    if quality == MoveQuality.BEST:
                        if is_exact_best:
                            explanation = f"{played_san} is Stockfish's #1 choice (continuation: {pv_preview})."
                        else:
                            explanation = f"{played_san} is equal to Stockfish's top choice {best_san_str} (-{ep_loss:.3f} EP)."
                    elif quality == MoveQuality.EXCELLENT:
                        explanation = f"{played_san} is an excellent move (-{ep_loss:.2f} EP, -{cp_loss / 100:.2f} pawns; top line was {best_san_str})."
                    elif quality == MoveQuality.GOOD:
                        explanation = f"{played_san} is a solid move (-{ep_loss:.2f} EP, -{cp_loss / 100:.2f} pawns; best was {best_san_str})."
                    elif quality == MoveQuality.INACCURACY:
                        explanation = f"{played_san} is an inaccuracy (-{ep_loss:.2f} EP, loses {cp_loss / 100:.2f} pawns). Best was {best_san_str} ({pv_preview})."
                    elif quality == MoveQuality.MISTAKE:
                        explanation = f"{played_san} is a mistake (-{ep_loss:.2f} EP, loses {cp_loss / 100:.2f} pawns). Best was {best_san_str} ({pv_preview})."
                    else:
                        if (comp.mate_before is None or comp.mate_before >= 0) and (comp.mate_after is not None and comp.mate_after < 0):
                            explanation = f"{played_san} is a blunder allowing forced checkmate in {abs(comp.mate_after)}! Best was {best_san_str}."
                        else:
                            explanation = f"{played_san} is a blunder (-{ep_loss:.2f} EP, loses {cp_loss / 100:.2f} pawns)! {best_san_str} was required ({pv_preview})."

        sym, txt = QUALITY_BADGES[quality]
        ob = comp.outcomes_before
        oa = comp.outcomes_after
        return MoveClassification(
            ply=ply,
            played_uci=played_uci,
            played_san=played_san,
            mover_color=mover_color,
            quality=quality,
            badge_symbol=sym,
            badge_text=txt,
            eval_before=best_var.score,
            eval_after=score_after,
            best_move_uci=best_var.best_move_uci,
            best_move_san=best_var.best_move_san,
            cp_loss=cp_loss,
            win_prob_loss=ep_loss,
            engine_id=engine_id,
            engine_version=engine_version,
            search_depth=best_var.depth,
            confidence=confidence,
            explanation=explanation,
            ordinary_classification=ordinary_q,
            expected_points_before=ep_before,
            expected_points_after=ep_after,
            expected_points_loss=ep_loss,
            win_prob_before=ob.win_prob if ob else ep_before,
            draw_prob_before=ob.draw_prob if ob else 0.0,
            loss_prob_before=ob.loss_prob if ob else (1.0 - ep_before),
            win_prob_after=oa.win_prob if oa else ep_after,
            draw_prob_after=oa.draw_prob if oa else 0.0,
            loss_prob_after=oa.loss_prob if oa else (1.0 - ep_after),
            special_flags=special_flags,
            negative_loss_detected=comp.negative_loss_detected,
            brilliant_diagnostics=brilliant_diag,
        )
