"""Comprehensive test suite for Chess.com-Inspired Game Review V2.2, Conservative Brilliant Detection, and Mobile UI Fixes."""
import tempfile
import unittest
from pathlib import Path
import chess

from chess_analyzer.analysis import (
    AccuracyModel,
    BrilliantEligibilityConfig,
    ClassificationThresholds,
    EvaluationNormalizer,
    ExpectedPointsModel,
    GameEventSelector,
    MoveClassification,
    MoveClassifier,
    MoveQuality,
    OpeningRecognizer,
    PerformanceRatingModel,
    PositionEvaluator,
    build_game_report,
)
from chess_analyzer.app import ScreenName, create_app_container
from chess_analyzer.domain import MoveHistory
from chess_analyzer.engines import CandidateVariation, EngineScore
from chess_analyzer.integrations import PGNImporter
from chess_analyzer.ui import ChessAnalyzerKivyApp


class TestExpectedPointsAndPerspectiveNormalization(unittest.TestCase):
    def setUp(self) -> None:
        self.ep_model = ExpectedPointsModel()
        self.classifier = MoveClassifier()

    def test_three_outcome_probabilities_and_terminal_states(self) -> None:
        eq = self.ep_model.from_cp(0, rating=1500)
        self.assertAlmostEqual(eq.win_prob + eq.draw_prob + eq.loss_prob, 1.0, places=6)
        self.assertAlmostEqual(eq.expected_points, 0.5, places=6)
        self.assertGreater(eq.draw_prob, 0.25)

        ep_1200 = self.ep_model.from_cp(150, rating=1200).expected_points
        ep_2400 = self.ep_model.from_cp(150, rating=2400).expected_points
        self.assertGreater(ep_2400, ep_1200)

        mate_delivered = EngineScore(raw_cp_pov=None, raw_mate_pov=0, pov_color="black")
        out_w = self.ep_model.from_score(mate_delivered, "white")
        out_b = self.ep_model.from_score(mate_delivered, "black")
        self.assertEqual((out_w.win_prob, out_w.draw_prob, out_w.loss_prob), (1.0, 0.0, 0.0))
        self.assertEqual(out_w.expected_points, 1.0)
        self.assertEqual((out_b.win_prob, out_b.draw_prob, out_b.loss_prob), (0.0, 0.0, 1.0))
        self.assertEqual(out_b.expected_points, 0.0)

        out_draw = self.ep_model.from_score(
            EngineScore(raw_cp_pov=500, raw_mate_pov=None, pov_color="white"),
            "white",
            is_terminal_draw=True,
        )
        self.assertEqual((out_draw.win_prob, out_draw.draw_prob, out_draw.loss_prob), (0.0, 1.0, 0.0))
        self.assertEqual(out_draw.expected_points, 0.5)

    def test_white_and_black_perspective_symmetry(self) -> None:
        var_w = CandidateVariation(
            multipv_index=1,
            score=EngineScore(raw_cp_pov=40, raw_mate_pov=None, pov_color="white"),
            depth=12,
            seldepth=14,
            pv_uci=["e2e4"],
            pv_san=["e4"],
        )
        after_w = EngineScore(raw_cp_pov=80, raw_mate_pov=None, pov_color="black")

        var_b = CandidateVariation(
            multipv_index=1,
            score=EngineScore(raw_cp_pov=40, raw_mate_pov=None, pov_color="black"),
            depth=12,
            seldepth=14,
            pv_uci=["e7e5"],
            pv_san=["e5"],
        )
        after_b = EngineScore(raw_cp_pov=80, raw_mate_pov=None, pov_color="white")

        cls_w = self.classifier.classify_move(
            ply=15,
            played_uci="a2a3",
            played_san="a3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[var_w],
            score_after=after_w,
            engine_id="sf_19",
            engine_version="19",
            is_book_line=False,
        )
        cls_b = self.classifier.classify_move(
            ply=16,
            played_uci="a7a6",
            played_san="a6",
            mover_color="black",
            legal_moves_count=20,
            variations_before=[var_b],
            score_after=after_b,
            engine_id="sf_19",
            engine_version="19",
            is_book_line=False,
        )
        self.assertAlmostEqual(cls_w.expected_points_loss, cls_b.expected_points_loss, places=6)
        self.assertEqual(cls_w.quality, cls_b.quality)
        self.assertEqual(cls_w.quality, MoveQuality.MISTAKE)


class TestClassificationV2AndSpecialDetectors(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = MoveClassifier()

    def test_ordinary_v2_expected_points_buckets(self) -> None:
        base_var = CandidateVariation(
            multipv_index=1,
            score=EngineScore(raw_cp_pov=0, raw_mate_pov=None, pov_color="white"),
            depth=14,
            seldepth=18,
            pv_uci=["g1f3"],
            pv_san=["Nf3"],
        )
        c_exc = self.classifier.classify_move(
            ply=15,
            played_uci="d2d3",
            played_san="d3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[base_var],
            score_after=EngineScore(raw_cp_pov=12, raw_mate_pov=None, pov_color="black"),
            engine_id="sf_19",
            engine_version="19",
            is_book_line=False,
        )
        self.assertEqual(c_exc.quality, MoveQuality.EXCELLENT)
        self.assertTrue(0.00 < c_exc.expected_points_loss <= 0.02)

        c_good = self.classifier.classify_move(
            ply=15,
            played_uci="d2d3",
            played_san="d3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[base_var],
            score_after=EngineScore(raw_cp_pov=35, raw_mate_pov=None, pov_color="black"),
            engine_id="sf_19",
            engine_version="19",
            is_book_line=False,
        )
        self.assertEqual(c_good.quality, MoveQuality.GOOD)
        self.assertTrue(0.02 < c_good.expected_points_loss <= 0.05)

        c_inac = self.classifier.classify_move(
            ply=15,
            played_uci="d2d3",
            played_san="d3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[base_var],
            score_after=EngineScore(raw_cp_pov=80, raw_mate_pov=None, pov_color="black"),
            engine_id="sf_19",
            engine_version="19",
            is_book_line=False,
        )
        self.assertEqual(c_inac.quality, MoveQuality.INACCURACY)
        self.assertTrue(0.05 < c_inac.expected_points_loss <= 0.10)

        c_mist = self.classifier.classify_move(
            ply=15,
            played_uci="d2d3",
            played_san="d3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[base_var],
            score_after=EngineScore(raw_cp_pov=160, raw_mate_pov=None, pov_color="black"),
            engine_id="sf_19",
            engine_version="19",
            is_book_line=False,
        )
        self.assertEqual(c_mist.quality, MoveQuality.MISTAKE)
        self.assertTrue(0.10 < c_mist.expected_points_loss <= 0.20)

        c_blun = self.classifier.classify_move(
            ply=15,
            played_uci="d2d3",
            played_san="d3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[base_var],
            score_after=EngineScore(raw_cp_pov=300, raw_mate_pov=None, pov_color="black"),
            engine_id="sf_19",
            engine_version="19",
            is_book_line=False,
        )
        self.assertEqual(c_blun.quality, MoveQuality.BLUNDER)
        self.assertGreater(c_blun.expected_points_loss, 0.20)

    def test_brilliant_great_book_and_precedence_policy(self) -> None:
        fen_sac = "r1bqkbnr/pp1p1ppp/2p5/4p3/2B1P3/2N5/PPPP1PPP/R1BQK1NR w KQkq - 0 4"
        var_sac = CandidateVariation(
            multipv_index=1,
            score=EngineScore(raw_cp_pov=180, raw_mate_pov=None, pov_color="white"),
            depth=14,
            seldepth=18,
            pv_uci=["c3d5", "c6d5"],
            pv_san=["Nd5", "cxd5"],
        )
        var_second = CandidateVariation(
            multipv_index=2,
            score=EngineScore(raw_cp_pov=0, raw_mate_pov=None, pov_color="white"),
            depth=14,
            seldepth=18,
            pv_uci=["g1f3"],
            pv_san=["Nf3"],
        )
        c_bril = self.classifier.classify_move(
            ply=7,
            played_uci="c3d5",
            played_san="Nd5",
            mover_color="white",
            legal_moves_count=28,
            variations_before=[var_sac, var_second],
            score_after=EngineScore(raw_cp_pov=-180, raw_mate_pov=None, pov_color="black"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_sac,
            is_book_line=False,
        )
        self.assertEqual(c_bril.quality, MoveQuality.BRILLIANT)
        self.assertEqual(c_bril.ordinary_classification, MoveQuality.BEST)
        self.assertIn("brilliant_sacrifice", c_bril.special_flags)
        self.assertIsNotNone(c_bril.brilliant_diagnostics)
        self.assertTrue(c_bril.brilliant_diagnostics.passed_all_gates)
        self.assertGreaterEqual(c_bril.brilliant_diagnostics.eligibility_score, 0.65)

        # Book takes precedence over Brilliant for theoretical opening traps
        c_book_override = self.classifier.classify_move(
            ply=7,
            played_uci="c3d5",
            played_san="Nd5",
            mover_color="white",
            legal_moves_count=28,
            variations_before=[var_sac, var_second],
            score_after=EngineScore(raw_cp_pov=-180, raw_mate_pov=None, pov_color="black"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_sac,
            is_book_line=True,
        )
        self.assertEqual(c_book_override.quality, MoveQuality.BOOK)

        # Great move (critical only good move without sacrificing material)
        c_great = self.classifier.classify_move(
            ply=18,
            played_uci="g1f3",
            played_san="Nf3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[
                CandidateVariation(1, EngineScore(50, None, "white"), 14, 16, ["g1f3"], ["Nf3"]),
                CandidateVariation(2, EngineScore(-160, None, "white"), 14, 16, ["a2a3"], ["a3"]),
            ],
            score_after=EngineScore(-50, None, "black"),
            engine_id="sf_19",
            engine_version="19",
            is_book_line=False,
        )
        self.assertEqual(c_great.quality, MoveQuality.GREAT)

    def test_false_brilliant_regressions_all_eleven_scenarios(self) -> None:
        """
        Comprehensive regression test suite targeting all 11 false-Brilliant scenarios (Section 9):
        1. Routine best move without a sacrifice (including defended development attacked by equal/higher piece) -> NOT Brilliant.
        2. Ordinary capture (winning material or equal trade) -> NOT Brilliant.
        3. Sacrifice that loses material without adequate compensation -> NOT Brilliant (Blunder).
        4. Forced recapture / only reasonable move -> NOT Brilliant.
        5. Speculative sacrifice that the engine refutes -> NOT Brilliant.
        6. Move that preserves a completely winning position without forcing mate -> NOT Brilliant.
        7. Sound, objectively justified sacrifice with concrete tactical payoff -> QUALIFIES as Brilliant.
        8. Sound mating sacrifice without material recovery -> QUALIFIES as Brilliant.
        9. Genuine Brilliant in a poor game qualifies, while poor game state (multi-piece blunder) does NOT loosen rules.
        10. Deeper analysis that refutes a sacrifice removes Brilliant eligibility.
        11. Repeated analysis of the same position produces identical classifications.
        """
        # Scenario 1: Routine best move developing a piece onto a defended square attacked by an enemy bishop/rook
        # White plays Nf3 on a board where Black's Bg4 attacks f3, but g2/Qd1 defend f3 (equal trade, NOT a sacrifice!)
        fen_defended_dev = "rn1qkbnr/ppp1pppp/8/3p4/6b1/8/PPPPPPPP/RNBQKBNR w KQkq - 2 3"
        c_routine = self.classifier.classify_move(
            ply=5,
            played_uci="g1f3",
            played_san="Nf3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[
                CandidateVariation(1, EngineScore(45, None, "white"), 14, 16, ["g1f3", "e7e6"], ["Nf3", "e6"]),
                CandidateVariation(2, EngineScore(20, None, "white"), 14, 16, ["d2d4"], ["d4"]),
            ],
            score_after=EngineScore(-45, None, "black"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_defended_dev,
            is_book_line=False,
        )
        self.assertEqual(c_routine.quality, MoveQuality.BEST)
        self.assertFalse(c_routine.brilliant_diagnostics.is_eligible)
        self.assertIn("gate_2_sound_sacrifice", c_routine.brilliant_diagnostics.failed_gates)

        # Scenario 2: Ordinary capture winning a hanging piece or trading queens (must NOT be Brilliant even with huge uniqueness gap)
        fen_ordinary_cap = "r1bqkbnr/pppp1ppp/8/4n3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 4"
        c_cap = self.classifier.classify_move(
            ply=7,
            played_uci="f3e5",
            played_san="Nxe5",
            mover_color="white",
            legal_moves_count=26,
            variations_before=[
                CandidateVariation(1, EngineScore(320, None, "white"), 14, 18, ["f3e5", "d7d6"], ["Nxe5", "d6"]),
                CandidateVariation(2, EngineScore(-20, None, "white"), 14, 18, ["d2d4"], ["d4"]),
            ],
            score_after=EngineScore(-320, None, "black"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_ordinary_cap,
            is_book_line=False,
        )
        self.assertNotEqual(c_cap.quality, MoveQuality.BRILLIANT)
        self.assertEqual(c_cap.brilliant_diagnostics.sacrifice_type, "ordinary_capture")

        # Scenario 3: Uncompensated blunder leaving a Rook en prise
        fen_blunder_sac = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
        c_uncomp = self.classifier.classify_move(
            ply=5,
            played_uci="f3xe5",
            played_san="Nxe5",
            mover_color="white",
            legal_moves_count=25,
            variations_before=[
                CandidateVariation(1, EngineScore(35, None, "white"), 14, 16, ["f1b5"], ["Bb5"]),
            ],
            score_after=EngineScore(260, None, "black"),  # Black is +260cp after Nxe5 Nxe5
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_blunder_sac,
            is_book_line=False,
        )
        self.assertEqual(c_uncomp.quality, MoveQuality.BLUNDER)
        self.assertFalse(c_uncomp.brilliant_diagnostics.is_eligible)
        self.assertIn("gate_1_engine_quality", c_uncomp.brilliant_diagnostics.failed_gates)
        self.assertIn("gate_3_concrete_compensation", c_uncomp.brilliant_diagnostics.failed_gates)

        # Scenario 4: Forced recapture (where recapturing a piece is the only good move) -> Great/Best, NEVER Brilliant
        fen_forced_recap = "r1bqkbnr/ppp2ppp/2np4/4N3/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 4"
        c_recap = self.classifier.classify_move(
            ply=8,
            played_uci="d6e5",
            played_san="dxe5",
            mover_color="black",
            legal_moves_count=25,
            variations_before=[
                CandidateVariation(1, EngineScore(-20, None, "black"), 14, 16, ["d6e5"], ["dxe5"]),
                CandidateVariation(2, EngineScore(-330, None, "black"), 14, 16, ["g8f6"], ["Nf6"]),
            ],
            score_after=EngineScore(20, None, "white"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_forced_recap,
            is_book_line=False,
        )
        self.assertNotEqual(c_recap.quality, MoveQuality.BRILLIANT)
        self.assertEqual(c_recap.quality, MoveQuality.GREAT)

        # Scenario 5: Speculative sacrifice that the engine refutes (e.g. unsound Bxh7+ dropping from +20cp to -220cp)
        fen_unsound_greek = "r1bq1rk1/ppp1ppbp/2np1np1/8/2B1P3/2NP1N2/PPP2PPP/R1BQK2R w KQ - 2 6"
        c_refuted = self.classifier.classify_move(
            ply=11,
            played_uci="c4f7",
            played_san="Bxf7+",
            mover_color="white",
            legal_moves_count=30,
            variations_before=[
                CandidateVariation(1, EngineScore(20, None, "white"), 14, 18, ["e1g1"], ["O-O"]),
            ],
            score_after=EngineScore(220, None, "black"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_unsound_greek,
            is_book_line=False,
        )
        self.assertNotEqual(c_refuted.quality, MoveQuality.BRILLIANT)
        self.assertIn(c_refuted.quality, (MoveQuality.MISTAKE, MoveQuality.BLUNDER))

        # Scenario 6: Move in an already completely winning position (+550cp / EP > 0.94) without forcing mate -> NOT Brilliant
        fen_already_won = "r1bqkbnr/pp1p1ppp/2p5/4p3/2B1P3/2N5/PPPP1PPP/R1BQK1NR w KQkq - 0 4"
        c_already_won = self.classifier.classify_move(
            ply=25,
            played_uci="c3d5",
            played_san="Nd5",
            mover_color="white",
            legal_moves_count=28,
            variations_before=[
                CandidateVariation(1, EngineScore(550, None, "white"), 14, 18, ["c3d5", "c6d5"], ["Nd5", "cxd5"]),
                CandidateVariation(2, EngineScore(420, None, "white"), 14, 18, ["g1f3"], ["Nf3"]),
            ],
            score_after=EngineScore(-540, None, "black"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_already_won,
            is_book_line=False,
        )
        self.assertEqual(c_already_won.quality, MoveQuality.BEST)
        self.assertFalse(c_already_won.brilliant_diagnostics.is_eligible)
        self.assertIn("gate_5_position_context", c_already_won.brilliant_diagnostics.failed_gates)

        # Scenario 8: Sound mating sacrifice (sacrificing a Rook on e8 where Kxe8/Rxe8 is possible, forcing mate in 2)
        # Position: White Kh1, Qd3, Re1; Black Kg8, Rf8, f7, g7, h6 -> 1. Re8! (attacked by Rf8, undefended or offered)
        fen_mate_sac = "4rrk1/pp3pp1/7p/8/8/3Q4/PPP2PPP/4R1K1 w - - 0 18"
        # Let's test a direct Rook sacrifice onto h7 (`Rxh7+!` where Kxh7 is legal and Qh3+ Kg8 Qh8# follows):
        fen_rook_mate_sac = "r4rk1/ppp2ppp/8/8/8/2B4Q/PPP2PPP/6KR w - - 0 15"
        c_mate_sac = self.classifier.classify_move(
            ply=29,
            played_uci="h3h7",
            played_san="Qxh7+",
            mover_color="white",
            legal_moves_count=24,
            variations_before=[
                CandidateVariation(1, EngineScore(None, 2, "white"), 14, 18, ["h3h7", "g8h7", "h1h5"], ["Qxh7+", "Kxh7", "Rh5#"]),
                CandidateVariation(2, EngineScore(0, None, "white"), 14, 18, ["g1f1"], ["Kf1"]),
            ],
            score_after=EngineScore(None, -1, "black"),  # Black is mated in 1 after Qxh7+ Kxh7
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_rook_mate_sac,
            is_book_line=False,
        )
        self.assertEqual(c_mate_sac.quality, MoveQuality.BRILLIANT)
        self.assertTrue(c_mate_sac.brilliant_diagnostics.is_eligible)

        # Scenario 9: Pre-existing multi-piece blunder in a poor game must NOT trigger a false Brilliant when saving one piece
        # Both White's Knight on a4 (attacked by b5 pawn) and Bishop on h4 (attacked by g5 pawn) are already hanging
        fen_two_hanging = "rnbqkbnr/p3pp1p/8/1p4p1/N6B/8/PPPPPPPP/R2QKBNR w KQkq - 0 5"
        c_damage_control = self.classifier.classify_move(
            ply=9,
            played_uci="a4c3",
            played_san="Nc3",
            mover_color="white",
            legal_moves_count=22,
            variations_before=[
                CandidateVariation(1, EngineScore(-220, None, "white"), 14, 16, ["a4c3", "g5h4"], ["Nc3", "gxh4"]),
                CandidateVariation(2, EngineScore(-500, None, "white"), 14, 16, ["a2a3"], ["a3"]),
            ],
            score_after=EngineScore(220, None, "black"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_two_hanging,
            is_book_line=False,
        )
        self.assertNotEqual(c_damage_control.quality, MoveQuality.BRILLIANT)
        self.assertFalse(c_damage_control.brilliant_diagnostics.is_eligible)

        # Scenario 10: Shallow depth (< min_depth=6) or deeper post-move refutation removes Brilliant eligibility
        c_shallow = self.classifier.classify_move(
            ply=7,
            played_uci="c3d5",
            played_san="Nd5",
            mover_color="white",
            legal_moves_count=28,
            variations_before=[
                CandidateVariation(1, EngineScore(180, None, "white"), 3, 4, ["c3d5", "c6d5"], ["Nd5", "cxd5"]),
                CandidateVariation(2, EngineScore(0, None, "white"), 3, 4, ["g1f3"], ["Nf3"]),
            ],
            score_after=EngineScore(-180, None, "black"),
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_already_won,
            is_book_line=False,
        )
        self.assertNotEqual(c_shallow.quality, MoveQuality.BRILLIANT)
        self.assertIn("gate_6_reliable_analysis", c_shallow.brilliant_diagnostics.failed_gates)

        c_deep_refuted = self.classifier.classify_move(
            ply=7,
            played_uci="c3d5",
            played_san="Nd5",
            mover_color="white",
            legal_moves_count=28,
            variations_before=[
                CandidateVariation(1, EngineScore(180, None, "white"), 10, 14, ["c3d5", "c6d5"], ["Nd5", "cxd5"]),
                CandidateVariation(2, EngineScore(0, None, "white"), 10, 14, ["g1f3"], ["Nf3"]),
            ],
            score_after=EngineScore(160, None, "black"),  # Deeper post-move search shows -160cp refutation for White!
            engine_id="sf_19",
            engine_version="19",
            fen_before=fen_already_won,
            is_book_line=False,
        )
        self.assertNotEqual(c_deep_refuted.quality, MoveQuality.BRILLIANT)
        self.assertFalse(c_deep_refuted.brilliant_diagnostics.is_eligible)

        # Scenario 11: Deterministic consistency across repeated runs
        runs = [
            self.classifier.classify_move(
                ply=7,
                played_uci="c3d5",
                played_san="Nd5",
                mover_color="white",
                legal_moves_count=28,
                variations_before=[
                    CandidateVariation(1, EngineScore(180, None, "white"), 14, 18, ["c3d5", "c6d5"], ["Nd5", "cxd5"]),
                    CandidateVariation(2, EngineScore(0, None, "white"), 14, 18, ["g1f3"], ["Nf3"]),
                ],
                score_after=EngineScore(-180, None, "black"),
                engine_id="sf_19",
                engine_version="19",
                fen_before=fen_already_won,
                is_book_line=False,
            )
            for _ in range(5)
        ]
        self.assertTrue(all(r.quality == MoveQuality.BRILLIANT for r in runs))
        self.assertEqual(len({r.brilliant_diagnostics.eligibility_score for r in runs}), 1)

    def test_opening_recognizer_and_event_selector(self) -> None:
        rec = OpeningRecognizer()
        uci_seq = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "h7h6", "a2a3"]
        eco, name, flags = rec.analyze_opening_sequence(chess.STARTING_FEN, uci_seq)
        self.assertEqual(eco, "C50")
        self.assertEqual(name, "Italian Game")
        self.assertEqual(flags, [True, True, True, True, True, False, False])

        var1 = CandidateVariation(1, EngineScore(30, None, "white"), 12, 12, ["e2e4"], ["e4"])
        c1 = self.classifier.classify_move(1, "e2e4", "e4", "white", 20, [var1], EngineScore(-30, None, "black"), "sf_19", "19", is_book_line=True)
        c2 = self.classifier.classify_move(2, "e7e5", "e5", "black", 20, [var1], EngineScore(300, None, "white"), "sf_19", "19", is_book_line=False)
        selector = GameEventSelector()
        events = selector.select_events([c1, c2])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].quality, MoveQuality.BLUNDER)
        self.assertEqual(events[0].mover_color, "black")


class TestAccuracyAndPerformanceRatingModels(unittest.TestCase):
    def test_accuracy_monotonicity_and_independence_from_best_move_percent(self) -> None:
        acc_model = AccuracyModel()
        classifier = MoveClassifier()
        base_var = CandidateVariation(1, EngineScore(20, None, "white"), 12, 12, ["e2e4"], ["e4"])

        moves_a = [
            classifier.classify_move(
                ply=i * 2 + 1,
                played_uci="d2d4",
                played_san="d4",
                mover_color="white",
                legal_moves_count=20,
                variations_before=[base_var],
                score_after=EngineScore(-10, None, "black"),
                engine_id="sf_19",
                engine_version="19",
                is_book_line=False,
            )
            for i in range(10)
        ]
        moves_b = []
        for i in range(10):
            if i % 2 == 0:
                moves_b.append(
                    classifier.classify_move(
                        i * 2 + 1, "e2e4", "e4", "white", 20, [base_var], EngineScore(-20, None, "black"), "sf_19", "19", is_book_line=False
                    )
                )
            else:
                moves_b.append(
                    classifier.classify_move(
                        i * 2 + 1, "f2f4", "f4", "white", 20, [base_var], EngineScore(380, None, "black"), "sf_19", "19", is_book_line=False
                    )
                )

        acc_a = acc_model.compute_player_accuracy(moves_a)
        acc_b = acc_model.compute_player_accuracy(moves_b)
        self.assertGreater(acc_a, 88.0)
        self.assertLess(acc_b, 50.0)
        self.assertGreater(acc_a, acc_b + 20.0)

        perf_model = PerformanceRatingModel()
        perf_a = perf_model.estimate_player_performance(moves_a, acc_a, player_rating=1500, opponent_rating=1500)
        perf_b = perf_model.estimate_player_performance(moves_b, acc_b, player_rating=1500, opponent_rating=1500)
        self.assertIsNotNone(perf_a.estimated_rating)
        self.assertIsNotNone(perf_b.estimated_rating)
        self.assertGreater(perf_a.estimated_rating, 1550)
        self.assertLess(perf_b.estimated_rating, 1350)
        self.assertGreater(perf_a.estimated_rating, perf_b.estimated_rating)


class TestPerMoveRecursiveVariationTreeAndUIReview(unittest.TestCase):
    def test_per_move_independent_variations_and_nested_subvariations(self) -> None:
        h = MoveHistory()
        for uci in ("e2e4", "e7e5", "g1f3", "b8c6"):
            h.record_move(chess.Move.from_uci(uci))
        self.assertEqual([n.san for n in h.mainline_nodes], ["e4", "e5", "Nf3", "Nc6"])

        h.go_to_ply(2)
        h.record_move(chess.Move.from_uci("f1c4"))  # Variation 1 at ply 3: 2. Bc4
        h.record_move(chess.Move.from_uci("g8f6"))  # Continuation inside 2. Bc4: 2... Nf6

        h.go_to_ply(2)
        h.record_move(chess.Move.from_uci("d2d4"))  # Variation 2 at ply 3: 2. d4

        self.assertEqual(h.cursor, 3)
        var_info = h.get_variations_at_current_move()
        self.assertEqual(var_info["total_branches"], 3)
        self.assertEqual(var_info["branch_san_list"], ["2.Nf3", "2.Bc4", "2.d4"])
        self.assertEqual(var_info["active_index"], 2)

        h.cycle_variation_at_current_move()
        self.assertEqual(h.current_node.san, "Nf3")
        self.assertFalse(h.is_in_variant)

        h.cycle_variation_at_current_move()
        self.assertEqual(h.current_node.san, "Bc4")
        self.assertTrue(h.is_in_variant)
        self.assertEqual([n.san for n in h.nodes], ["e4", "e5", "Bc4", "Nf6"])

        h.go_to_ply(3)
        h.record_move(chess.Move.from_uci("f8c5"))  # Sub-variation 2... Bc5 inside 2. Bc4
        self.assertEqual(h.cursor, 4)
        sub_info = h.get_variations_at_current_move()
        self.assertEqual(sub_info["total_branches"], 2)
        self.assertEqual(sub_info["branch_san_list"], ["2...Nf6", "2...Bc5"])

        tree_json = h.to_tree_json()
        h2 = MoveHistory()
        h2.load_tree_json(tree_json)
        self.assertEqual([n.san for n in h2.mainline_nodes], ["e4", "e5", "Nf3", "Nc6"])
        h2.go_to_ply(3)
        info2 = h2.get_variations_at_current_move()
        self.assertEqual(info2["total_branches"], 3)
        self.assertEqual(info2["branch_san_list"], ["2.Nf3", "2.Bc4", "2.d4"])

    def test_workspace_move_strip_below_buttons_and_no_redundant_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "ui_v2.sqlite3")
            container = create_app_container(db_path=db_path)
            try:
                app = ChessAnalyzerKivyApp(container=container)
                app.build()
                ws = app.workspace_screen

                # 0. Verify home screen buttons have the 4 uploaded icons wired and workspace top_bar removed rename box
                self.assertTrue(app.home_screen.btn_manual_game.icon_path.endswith("new_game.png"))
                self.assertTrue(app.home_screen.btn_import_game.icon_path.endswith("import_game.png"))
                self.assertTrue(app.home_screen.btn_custom_position.icon_path.endswith("custom_game.png"))
                self.assertTrue(app.home_screen.btn_settings.icon_path.endswith("settings.png"))
                self.assertNotIn(ws.title_input, ws.top_bar.children)
                self.assertNotIn(ws.btn_rename, ws.top_bar.children)
                self.assertEqual(ws.btn_mainline.text, "Mainline")
                self.assertEqual(ws.btn_run_imported_classification.text, "Game Review")
                self.assertEqual(ws.btn_toggle_scorecard.text, "Scorecard")

                # 1. Verify notation_row (move strip) is placed BELOW action_bar
                idx_action = ws.children.index(ws.action_bar)
                idx_notation = ws.children.index(ws.notation_row)
                self.assertGreater(idx_notation, idx_action)

                # 2. Import a game and run Game Review
                pgn = '[White "Alice"]\n[Black "Bob"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *'
                sess = PGNImporter.import_to_session(pgn, source="chesscom")
                container.set_active_session(sess)
                app.navigator.navigate_to(ScreenName.WORKSPACE)
                ws.on_pre_enter()
                self.assertEqual(len(ws.board_widget.square_buttons), 64)
                self.assertNotEqual(ws.board_widget.status_banner.text, "No active chess session")

                rep1 = ws.run_classification_now(search_depth=2)
                self.assertIsNotNone(rep1)
                self.assertEqual(rep1.opening_eco, "C44")
                self.assertTrue(ws.btn_run_imported_classification.disabled)
                self.assertEqual(ws.btn_run_imported_classification.text, "✓ Reviewed")

                # 3. Verify Android back gesture closes open Scorecard first, then returns to previous screen
                self.assertTrue(ws.is_scorecard_open)
                self.assertTrue(app.handle_back_action())
                self.assertFalse(ws.is_scorecard_open)
                self.assertEqual(app.navigator.current_screen, ScreenName.WORKSPACE)

                # Open scorecard again and test clicking a point on the Evaluation Graph jumps the board to that ply
                ws.open_scorecard()
                ws.scorecard_widget.select_ply(3)
                eg = ws.scorecard_widget.eval_graph
                idx_canvas = eg.children.index(eg.graph_canvas_box)
                idx_text = eg.children.index(eg.text_below_box)
                self.assertGreater(idx_text, idx_canvas)

                self.assertFalse(ws.is_scorecard_open)
                self.assertEqual(sess.board_manager.history.cursor, 3)

                # Back gesture from Workspace returns to Home screen instead of exiting the app
                self.assertTrue(app.handle_back_action())
                self.assertEqual(app.navigator.current_screen, ScreenName.HOME)
            finally:
                container.shutdown()


if __name__ == "__main__":
    unittest.main()
