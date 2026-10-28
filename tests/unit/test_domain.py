"""Comprehensive unit tests for Milestone 1: Chess Domain Model."""
import unittest
import chess
from chess_analyzer.domain import (
    BoardManager,
    GameSession,
    MoveHistory,
    PositionBuilder,
    SessionMetadata,
    SessionMode,
    TerminationType,
)


class TestChessDomain(unittest.TestCase):
    def test_standard_starting_position(self) -> None:
        bm = BoardManager()
        status = bm.get_status()
        self.assertEqual(bm.get_active_fen(), chess.STARTING_FEN)
        self.assertEqual(status.turn, "white")
        self.assertFalse(status.is_check)
        self.assertFalse(status.is_game_over)
        self.assertEqual(status.legal_moves_count, 20)

    def test_legal_and_illegal_moves(self) -> None:
        bm = BoardManager()
        node = bm.play_move_squares("e2", "e4")
        self.assertEqual(node.san, "e4")
        self.assertEqual(bm.get_status().turn, "black")
        # Illegal move should raise ValueError
        with self.assertRaises(ValueError):
            bm.play_move_squares("e7", "e4")

    def test_board_flipping_independence(self) -> None:
        bm = BoardManager()
        bm.play_move_uci("e2e4")
        fen_before = bm.get_active_fen()
        order_normal = bm.get_visual_square_order()
        self.assertEqual(order_normal[0], "a8")
        self.assertEqual(order_normal[-1], "h1")

        bm.flip_board()
        self.assertTrue(bm.is_flipped)
        self.assertEqual(bm.get_active_fen(), fen_before)
        order_flipped = bm.get_visual_square_order()
        self.assertEqual(order_flipped[0], "h1")
        self.assertEqual(order_flipped[-1], "a8")

    def test_castling_and_custom_position_no_assumed_castling(self) -> None:
        builder = PositionBuilder()
        builder.clear()
        builder.set_piece("e1", "K")
        builder.set_piece("h1", "R")
        builder.set_piece("a1", "R")
        builder.set_piece("e8", "k")
        builder.set_piece("a8", "r")
        # Placing King and Rooks on initial squares MUST NOT automatically grant castling rights
        self.assertEqual(builder.get_castling_rights(), {"K": False, "Q": False, "k": False, "q": False})
        self.assertIn(" - - ", builder.to_fen())

        # Now explicitly enable White kingside castling only
        builder.set_castling_rights(white_kingside=True)
        self.assertIn(" w K - ", builder.to_fen())
        session = GameSession.create_from_custom_position(builder)
        legal_from_e1 = session.board_manager.get_legal_destinations_from("e1")
        self.assertIn("g1", legal_from_e1)  # O-O allowed
        self.assertNotIn("c1", legal_from_e1)  # O-O-O not allowed

    def test_en_passant_and_promotion(self) -> None:
        # En passant test
        bm = BoardManager()
        for mv in ["e2e4", "a7a6", "e4e5", "d7d5"]:
            bm.play_move_uci(mv)
        node = bm.play_move_squares("e5", "d6")
        self.assertTrue(node.is_en_passant)
        self.assertTrue(node.is_capture)
        self.assertEqual(node.san, "exd6")

        # Promotion requires promotion piece selector
        promo_fen = "8/P7/8/8/8/8/7k/4K3 w - - 0 1"
        bm_promo = BoardManager(initial_fen=promo_fen)
        self.assertTrue(bm_promo.requires_promotion("a7", "a8"))
        with self.assertRaises(ValueError):
            bm_promo.play_move_squares("a7", "a8", promotion=None)
        promo_node = bm_promo.play_move_squares("a7", "a8", promotion="q")
        self.assertEqual(promo_node.promotion, "q")
        self.assertEqual(promo_node.san, "a8=Q")

    def test_checkmate_stalemate_and_draws(self) -> None:
        # Fool's mate
        bm = BoardManager()
        for mv in ["f2f3", "e7e5", "g2g4", "d8h4"]:
            bm.play_move_uci(mv)
        st = bm.get_status()
        self.assertTrue(st.is_checkmate)
        self.assertTrue(st.is_game_over)
        self.assertEqual(st.result, "0-1")
        self.assertEqual(st.termination, TerminationType.CHECKMATE)

        # Stalemate
        bm_stale = BoardManager("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        st_stale = bm_stale.get_status()
        self.assertTrue(st_stale.is_stalemate)
        self.assertEqual(st_stale.result, "1/2-1/2")

        # Insufficient material
        bm_insuff = BoardManager("8/8/4k3/8/8/4K3/8/8 w - - 0 1")
        self.assertTrue(bm_insuff.get_status().is_insufficient_material)

        # Threefold repetition claimable
        bm_rep = BoardManager()
        for mv in ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1", "f6g8"]:
            bm_rep.play_move_uci(mv)
        self.assertTrue(bm_rep.get_status().can_claim_threefold_repetition)

    def test_navigation_undo_redo_and_variation_preview(self) -> None:
        bm = BoardManager()
        for mv in ["e2e4", "e7e5", "g1f3", "b8c6"]:
            bm.play_move_uci(mv)
        self.assertEqual(bm.history.total_plies, 4)

        bm.history.go_to_first()
        self.assertEqual(bm.get_active_fen(), chess.STARTING_FEN)
        bm.history.go_to_next()
        self.assertEqual(bm.history.current_node.san, "e4")
        bm.history.go_to_last()
        self.assertEqual(bm.history.cursor, 4)

        # Inspect variation without mutating underlying game
        bm.start_variation_inspection(["f1b5", "a7a6", "b5a4"])
        self.assertTrue(bm.is_inspecting_variation)
        self.assertEqual(len(bm.preview_moves), 3)
        bm.exit_variation_inspection()
        self.assertFalse(bm.is_inspecting_variation)
        self.assertEqual(bm.history.total_plies, 4)
        self.assertEqual(bm.history.current_node.san, "Nc6")

        # Undo and redo
        undone = bm.history.undo()
        self.assertEqual(undone.san, "Nc6")
        self.assertEqual(bm.history.total_plies, 3)
        redone = bm.history.redo()
        self.assertEqual(redone.san, "Nc6")
        self.assertEqual(bm.history.total_plies, 4)

    def test_session_classification_activation_policies(self) -> None:
        # Imported: ON by default
        imp = GameSession.create_imported(
            initial_fen=chess.STARTING_FEN,
            uci_moves=["e2e4", "e7e5"],
            metadata=SessionMetadata(source="lichess"),
            original_pgn="1. e4 e5 *",
        )
        self.assertTrue(imp.classification_enabled)
        self.assertTrue(imp.is_finished)

        # Manual: OFF by default, cannot enable before finishing
        man = GameSession.create_manual()
        self.assertFalse(man.classification_enabled)
        self.assertFalse(man.is_finished)
        with self.assertRaises(PermissionError):
            man.set_per_game_classification(True)

        man.play_move_uci("e2e4")
        man.finish_game(enable_classification=True)
        self.assertTrue(man.is_finished)
        self.assertTrue(man.classification_enabled)
        man.mark_classifications_computed()
        self.assertFalse(man.is_classification_stale)

        # Reopen and edit invalidates classifications
        man.reopen_for_editing()
        man.play_move_uci("e7e5")
        self.assertTrue(man.is_classification_stale)


if __name__ == "__main__":
    unittest.main()
