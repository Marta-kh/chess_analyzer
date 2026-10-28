"""Comprehensive test suite for Chess.com-Inspired Game Review V2, Per-Move Variation Trees, and UI fixes."""
import tempfile
import unittest
from pathlib import Path
import chess

from chess_analyzer.analysis import (
    AccuracyModel,
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
from chess_analyzer.storage import DatabaseManager, GameSessionRepository
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
        self.assertLessEqual(c_exc.expected_points_loss, 0.02)

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

                rep1 = ws.run_classification_now(search_depth=2)
                self.assertIsNotNone(rep1)
                self.assertEqual(rep1.opening_eco, "C44")
                self.assertTrue(ws.btn_run_imported_classification.disabled)
                self.assertEqual(ws.btn_run_imported_classification.text, "✓ Reviewed")

                # 3. Clicking a point on the Scorecard's Evaluation Graph jumps the board to that ply
                ws.scorecard_widget.select_ply(3)
                # 4. Verify EvaluationGraphWidget puts graph_canvas_box on TOP and text_below_box strictly BELOW (no overlap)
                eg = ws.scorecard_widget.eval_graph
                idx_canvas = eg.children.index(eg.graph_canvas_box)
                idx_text = eg.children.index(eg.text_below_box)
                self.assertGreater(idx_text, idx_canvas)

                self.assertFalse(ws.is_scorecard_open)
                self.assertEqual(sess.board_manager.history.cursor, 3)
            finally:
                container.shutdown()


if __name__ == "__main__":
    unittest.main()
