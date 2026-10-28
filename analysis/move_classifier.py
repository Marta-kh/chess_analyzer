"""
Chess.com-inspired Move Classification V2 Engine (Section 8.4).
Supports all 10 scorecard categories from the Game Review table:
Brilliant (!!), Great (!), Best (★), Excellent (✓+), Good (✓), Book (B),
Inaccuracy (?!), Mistake (?), Miss / Missed Win (×), and Blunder (??), plus Forced (→).

Implements:
1. Published Chess.com Classification V2 expected-points loss cutoffs:
   - Best: 0.00
   - Excellent: 0.00 - 0.02
   - Good: 0.02 - 0.05
   - Inaccuracy: 0.05 - 0.10
   - Mistake: 0.10 - 0.20
   - Blunder: 0.20 - 1.00
2. Contextual detectors for Book, Brilliant, Great, and Miss (MISSED_WIN).
3. Explicit label precedence policy:
   1. Book
   2. Brilliant
   3. Great
   4. Miss (MISSED_WIN)
   5. Ordinary V2 expected-points classification (Best / Excellent / Good / Inaccuracy / Mistake / Blunder)
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


PIECE_VALUES_CP = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 315,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


@dataclass
class ClassificationThresholds:
    """Configurable V2 expected-points loss cutoffs and centipawn/detector guardrails."""
    model_version: str = "v2.1-expected-points"
    # Published Chess.com Classification V2 expected-points loss cutoffs
    best_max_ep_loss: float = 0.0025
    excellent_max_ep_loss: float = 0.020
    good_max_ep_loss: float = 0.050
    inaccuracy_max_ep_loss: float = 0.100
    mistake_max_ep_loss: float = 0.200
    # Centipawn guardrails for deep endgame / synthetic positions
    best_max_cp_loss: int = 8
    excellent_max_cp_loss: int = 25
    good_max_cp_loss: int = 55
    inaccuracy_max_cp_loss: int = 110
    mistake_max_cp_loss: int = 240
    winning_advantage_cp: int = 240
    missed_win_drop_below_cp: int = 90
    min_required_depth: int = 1
    # Special detector thresholds
    great_uniqueness_ep_gap: float = 0.12
    great_uniqueness_cp_gap: int = 160
    miss_min_ep_before: float = 0.68
    miss_max_ep_after: float = 0.60
    miss_min_ep_loss: float = 0.11


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


class MoveClassifier:
    """Classifies moves using Expected-Points V2 cutoffs and contextual detectors."""

    SYSTEM_LABEL = "Chess.com-Inspired Game Review V2 (Local Stockfish Evaluation)"

    def __init__(self, thresholds: Optional[ClassificationThresholds] = None) -> None:
        self.thresholds = thresholds or ClassificationThresholds()

    def _classify_ordinary_v2(
        self,
        is_exact_best: bool,
        ep_loss: float,
        cp_loss: int,
        comp: EvaluationComparison,
    ) -> MoveQuality:
        """Applies published Chess.com Classification V2 expected-points loss cutoffs."""
        t = self.thresholds
        if (comp.mate_before is None or comp.mate_before >= 0) and (comp.mate_after is not None and comp.mate_after < 0):
            return MoveQuality.BLUNDER

        if is_exact_best or (ep_loss <= t.best_max_ep_loss and cp_loss <= t.best_max_cp_loss):
            return MoveQuality.BEST
        if ep_loss <= t.excellent_max_ep_loss:
            return MoveQuality.EXCELLENT
        if ep_loss <= t.good_max_ep_loss:
            return MoveQuality.GOOD
        if ep_loss <= t.inaccuracy_max_ep_loss:
            return MoveQuality.INACCURACY
        if ep_loss <= t.mistake_max_ep_loss:
            return MoveQuality.MISTAKE
        return MoveQuality.BLUNDER

    @staticmethod
    def _is_sound_material_sacrifice(
        fen_before: Optional[str],
        played_uci: str,
        mover_color: str,
    ) -> bool:
        """Checks whether `played_uci` sacrifices material or leaves a minor/major piece en prise."""
        if not fen_before:
            return False
        try:
            board = chess.Board(fen_before)
            move = chess.Move.from_uci(played_uci)
            if move not in board.legal_moves:
                return False
            moving_piece = board.piece_at(move.from_square)
            if moving_piece is None or moving_piece.piece_type in (chess.KING, chess.PAWN):
                return False
            captured_piece = board.piece_at(move.to_square)
            captured_val = PIECE_VALUES_CP.get(captured_piece.piece_type, 0) if captured_piece else 0
            moving_val = PIECE_VALUES_CP.get(moving_piece.piece_type, 0)

            mover_chess_color = chess.WHITE if mover_color.lower().startswith("w") else chess.BLACK
            board.push(move)

            # 1. Can opponent capture the moved piece on `move.to_square` for a net material gain >= 200cp?
            if moving_val - captured_val >= 200 and board.is_attacked_by(not mover_chess_color, move.to_square):
                return True

            # 2. Did mover leave another minor/major piece en prise to a lower-value opponent piece?
            for opp_mv in board.legal_moves:
                if not board.is_capture(opp_mv):
                    continue
                target_p = board.piece_at(opp_mv.to_square)
                attacker_p = board.piece_at(opp_mv.from_square)
                if (
                    target_p is not None
                    and target_p.color == mover_chess_color
                    and attacker_p is not None
                    and PIECE_VALUES_CP.get(target_p.piece_type, 0) >= 300
                ):
                    target_v = PIECE_VALUES_CP.get(target_p.piece_type, 0)
                    attacker_v = PIECE_VALUES_CP.get(attacker_p.piece_type, 0)
                    is_defended = board.is_attacked_by(mover_chess_color, opp_mv.to_square)
                    if (not is_defended and target_v > captured_val + 150) or (target_v - attacker_v >= 200 and target_v > captured_val):
                        return True
        except Exception:
            return False
        return False

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
        comp: EvaluationComparison = PositionEvaluator.compare(
            score_before=best_var.score,
            score_after=score_after,
            mover_color=mover_color,
            player_rating=player_rating,
            is_terminal_draw_after=is_terminal_draw_after,
        )
        confidence = "high" if best_var.depth >= 10 else ("medium" if best_var.depth >= 4 else "low")
        best_san_str = best_var.best_move_san or best_var.best_move_uci or "best move"
        pv_preview = " ".join(best_var.pv_san[:4]) if best_var.pv_san else best_san_str

        is_exact_best = best_var.best_move_uci == played_uci
        ep_before = comp.expected_points_before
        ep_after = comp.expected_points_after
        ep_loss = 0.0 if is_exact_best else comp.expected_points_loss
        cp_loss = 0 if is_exact_best else comp.cp_loss

        ordinary_q = self._classify_ordinary_v2(is_exact_best, ep_loss, cp_loss, comp)
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

        # 0. Forced move (only 1 legal move in position)
        if legal_moves_count == 1:
            quality = MoveQuality.FORCED
            special_flags.append("forced_only_legal_move")
            explanation = f"{played_san} was the only legal move available in this position."
        else:
            # 1. Book move detector (Precedence #1)
            is_book = False
            if is_book_line is True and ep_loss <= t.inaccuracy_max_ep_loss:
                is_book = True
                special_flags.append("opening_book")
            elif is_book_line is None and not is_exact_best and ply <= 6 and ep_loss <= t.excellent_max_ep_loss and abs(comp.eval_after_cp) <= 65:
                is_book = True
                special_flags.append("opening_book_heuristic")

            # 2. Brilliant move detector (Precedence #2)
            # Must be Best or Excellent (ep_loss <= 0.02), position after is not losing (ep_after >= 0.45)
            # and was not already trivially won (ep_before <= 0.93), plus involves a sound material sacrifice
            # OR deep tactical uniqueness with capture/check.
            is_brilliant = False
            if (
                not is_book
                and ordinary_q in (MoveQuality.BEST, MoveQuality.EXCELLENT)
                and ep_after >= 0.45
                and ep_before <= 0.93
            ):
                sac = self._is_sound_material_sacrifice(fen_before, played_uci, mover_color)
                tactical_shot = (
                    is_exact_best
                    and uniqueness_cp_gap >= 320
                    and comp.eval_before_cp >= 150
                    and ("x" in played_san or "+" in played_san)
                )
                if sac or tactical_shot:
                    is_brilliant = True
                    special_flags.append("brilliant_sacrifice" if sac else "brilliant_tactical_find")

            # 3. Great move detector (Precedence #3)
            # Finds the critical only good move (uniqueness_ep_gap >= 0.12 or uniqueness_cp_gap >= 160)
            # OR converts a critical transition after an opponent mistake.
            is_great = False
            if (
                not is_book
                and not is_brilliant
                and ordinary_q in (MoveQuality.BEST, MoveQuality.EXCELLENT)
            ):
                if (uniqueness_ep_gap >= t.great_uniqueness_ep_gap or uniqueness_cp_gap >= t.great_uniqueness_cp_gap) and comp.eval_before_cp > -220:
                    is_great = True
                    special_flags.append("only_good_move")
                elif (
                    previous_ep_for_mover is not None
                    and previous_ep_for_mover <= 0.52
                    and ep_after >= 0.72
                    and is_exact_best
                    and uniqueness_ep_gap >= 0.06
                ):
                    is_great = True
                    special_flags.append("critical_conversion")

            # 4. Miss / Missed Win detector (Precedence #4)
            # Mover had a forced mate or clear winning advantage (ep_before >= 0.68 or eval_before_cp >= 240)
            # and failed to capitalize, dropping to equal/unclear without dropping into a completely lost game.
            is_miss = False
            if not is_book and not is_brilliant and not is_great and not is_exact_best:
                missed_forced_mate = (
                    comp.mate_before is not None
                    and comp.mate_before > 0
                    and (comp.mate_after is None or comp.mate_after <= 0)
                    and -80 <= comp.eval_after_cp < t.winning_advantage_cp
                )
                missed_winning_opportunity = (
                    (ep_before >= t.miss_min_ep_before or comp.eval_before_cp >= t.winning_advantage_cp)
                    and (-120 <= comp.eval_after_cp <= t.missed_win_drop_below_cp or (0.38 <= ep_after <= t.miss_max_ep_after))
                    and (ep_loss >= t.miss_min_ep_loss or cp_loss >= t.inaccuracy_max_cp_loss)
                )
                if missed_forced_mate or missed_winning_opportunity:
                    is_miss = True
                    special_flags.append("missed_mate" if missed_forced_mate else "missed_tactical_win")

            # Apply Precedence Policy: 1. Book -> 2. Brilliant -> 3. Great -> 4. Miss -> 5. Ordinary V2
            if is_book:
                quality = MoveQuality.BOOK
                explanation = f"{played_san} is a theoretical opening book move ({pv_preview})."
            elif is_brilliant:
                quality = MoveQuality.BRILLIANT
                if "brilliant_sacrifice" in special_flags:
                    explanation = f"{played_san} is a brilliant material sacrifice maintaining high expected points ({ep_after:.2f} EP)!"
                else:
                    explanation = f"{played_san} is a brilliant tactical find (+{uniqueness_cp_gap / 100:.1f} pawns better than any alternative)!"
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
                # Special check: missed faster mate but still completely winning -> Inaccuracy
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
                            explanation = f"{played_san} is practically equal to Stockfish's top choice {best_san_str} (-{ep_loss:.3f} EP)."
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
        )
