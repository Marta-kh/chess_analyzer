"""End-to-end integration and UI tests verifying all 5 screens, all 3 session modes, MultiPV buttons, and iOS C FFI bridge."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import chess
from chess_analyzer.app import ScreenName, create_app_container
from chess_analyzer.domain import SessionMode
from chess_analyzer.platform.android import resolve_android_stockfish_path
from chess_analyzer.platform.ios import IOSStockfishFFIBridge
from chess_analyzer.ui import ChessAnalyzerKivyApp


class TestEndToEndUIAndPlatformWorkflows(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / "e2e_test.sqlite3")
        self.container = create_app_container(db_path=self.db_path)
        self.app = ChessAnalyzerKivyApp(container=self.container)
        self.app.build()

    def tearDown(self) -> None:
        self.container.shutdown()
        self._tmpdir.cleanup()

    def test_manual_entry_tap_moves_board_flip_finish_and_reopen_invalidation(self) -> None:
        # 1. Start manual game from Home screen
        self.assertEqual(self.app.navigator.current_screen, ScreenName.HOME)
        self.app.home_screen.btn_manual_game.trigger_release()
        self.assertEqual(self.app.navigator.current_screen, ScreenName.WORKSPACE)

        ws = self.app.workspace_screen
        session = self.container.active_session
        self.assertIsNotNone(session)
        self.assertEqual(session.mode, SessionMode.MANUAL)
        self.assertFalse(session.classification_enabled)

        # 2. Tap e2, then tap e4 on the interactive board widget
        ws.board_widget.on_square_tapped("e2")
        self.assertIn("e4", ws.board_widget.highlighted_destinations)
        ws.board_widget.on_square_tapped("e4")
        self.assertEqual(session.board_manager.history.total_plies, 1)

        # Play e7->e5 via square taps
        ws.board_widget.on_square_tapped("e7")
        ws.board_widget.on_square_tapped("e5")
        self.assertEqual(session.board_manager.history.total_plies, 2)

        # 3. Flip board in manual mode and verify FEN is unchanged
        fen_before = session.board_manager.get_active_fen()
        ws.btn_flip.trigger_release()
        self.assertTrue(session.board_manager.is_flipped)
        self.assertEqual(session.board_manager.get_active_fen(), fen_before)

        # 4. Invoke "Finish game and analyze moves"
        rep = ws.trigger_finish_and_analyze_moves(user_confirmed=True, enable_classification=True, search_depth=2)
        self.assertIsNotNone(rep)
        self.assertTrue(session.is_finished)
        self.assertTrue(session.classification_enabled)
        self.assertEqual(rep.total_plies_analyzed, 2)

        # 5. Reopen finished game and play another move -> invalidates stale classifications
        session.reopen_for_editing()
        ws.board_widget.on_square_tapped("g1")
        ws.board_widget.on_square_tapped("f3")
        self.assertTrue(session.is_classification_stale)
        ws.refresh_workspace()
        self.assertIn("invalidated", ws.classification_status_label.text)

    def test_custom_position_editor_and_engine_add_remove_variations_ui(self) -> None:
        # Navigate to Custom Position Editor
        self.app.home_screen.btn_custom_position.trigger_release()
        self.assertEqual(self.app.navigator.current_screen, ScreenName.CUSTOM_EDITOR)

        ed = self.app.custom_editor_screen
        ed.clear_board()
        # Missing kings -> invalid position, start button disabled
        self.assertTrue(ed.btn_start_play.disabled)

        # Place White King on e1, White Queen on h5, White Bishop on c4, Black King on e8
        ed.selected_brush_piece = "K"
        ed.tap_square("e1")
        ed.selected_brush_piece = "Q"
        ed.tap_square("h5")
        ed.selected_brush_piece = "B"
        ed.tap_square("c4")
        ed.selected_brush_piece = "k"
        ed.tap_square("e8")
        ed.selected_brush_piece = "p"
        ed.tap_square("f7")
        self.assertFalse(ed.btn_start_play.disabled)

        # Flip orientation in editor and start session
        ed.flip_orientation()
        ed.btn_start_play.trigger_release()
        self.assertEqual(self.app.navigator.current_screen, ScreenName.WORKSPACE)

        ws = self.app.workspace_screen
        session = self.container.active_session
        self.assertEqual(session.mode, SessionMode.CUSTOM)
        self.assertTrue(session.board_manager.is_flipped)

        # Enable live Stockfish analysis from UI button
        ws.engine_panel.toggle_analysis_btn.trigger_release()
        self.container.engine_manager.wait_for_all_engines(timeout=5.0)
        ws.engine_panel.refresh()

        bundled_id = self.container.engine_registry.list_engines()[0].engine_id
        inst_panel = ws.engine_panel.engine_panels[bundled_id]
        self.assertEqual(len(inst_panel.result.variations), 1)

        # Click "Add variation" button 4 times to reach 5 variations
        for expected in (2, 3, 4, 5):
            inst_panel.add_variation_btn.trigger_release()
            self.container.engine_manager.wait_for_all_engines(timeout=5.0)
            ws.engine_panel.refresh()
            inst_panel = ws.engine_panel.engine_panels[bundled_id]
            self.assertEqual(inst_panel.engine_def.config.visible_variations, expected)
            self.assertEqual(len(inst_panel.result.variations), expected)

        # At 5 variations, the "Add variation" button MUST be disabled and hidden (opacity 0.0)
        self.assertTrue(inst_panel.add_variation_btn.disabled)
        self.assertEqual(inst_panel.add_variation_btn.opacity, 0.0)

        # Inspect candidate variation on the board without mutating the custom game
        pv_to_inspect = inst_panel.result.variations[0].pv_uci
        ws.inspect_candidate_variation(pv_to_inspect)
        self.assertTrue(session.board_manager.is_inspecting_variation)
        self.assertEqual(session.board_manager.history.total_plies, 0)  # Recorded game still has 0 plies
        ws.exit_variation_preview()
        self.assertFalse(session.board_manager.is_inspecting_variation)

    def test_import_screen_offline_and_online_states(self) -> None:
        self.app.home_screen.btn_import_game.trigger_release()
        imp = self.app.import_screen

        # Test offline guard
        self.container.is_offline = True
        imp.username_input.text = "hikaru"
        imp.fetch_games()
        self.assertEqual(imp.state, "offline")

        # Test online mocked import
        self.container.is_offline = False
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "games": [
                {
                    "uuid": "g1",
                    "url": "https://www.chess.com/game/live/1",
                    "pgn": '[White "hikaru"]\n[Black "anon"]\n[Result "1-0"]\n\n1. e4 e5 1-0',
                    "time_control": "180",
                    "time_class": "blitz",
                    "rules": "chess",
                    "end_time": 1761600000,
                    "white": {"username": "hikaru", "rating": 3200},
                    "black": {"username": "anon", "rating": 2900},
                }
            ]
        }
        self.container.chesscom_client._get = lambda *a, **kw: mock_resp
        games = imp.fetch_games()
        self.assertEqual(imp.state, "loaded")
        self.assertEqual(len(games), 1)
        imp.select_game(games[0])
        self.assertEqual(self.app.navigator.current_screen, ScreenName.WORKSPACE)
        self.assertTrue(self.container.active_session.classification_enabled)

    def test_ios_c_ffi_bridge_and_android_path_resolver(self) -> None:
        # Verify the compiled C FFI shared library (`libstockfish_ios_bridge.so`) works via ctypes
        bridge = IOSStockfishFFIBridge()
        uci_out = bridge.send_command("uci")
        self.assertIn("uciok", uci_out)
        self.assertIn("readyok", bridge.send_command("isready"))
        bridge.send_command("setoption name MultiPV value 4")
        go_out = bridge.send_command("go depth 10")
        self.assertIn("multipv 4", go_out)
        self.assertIn("bestmove ", go_out)

        # Verify Android path resolver returns a valid path
        android_path = resolve_android_stockfish_path()
        self.assertTrue(len(android_path) > 0)


    def test_non_destructive_variants_in_imported_and_custom_games(self) -> None:
        from chess_analyzer.integrations import PGNImporter

        # 1. Import a 4-ply game (1. e4 e5 2. Nf3 Nc6)
        pgn = '[White "PlayerA"]\n[Black "PlayerB"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *'
        imp_session = PGNImporter.import_to_session(pgn, source="chesscom")
        self.container.set_active_session(imp_session)
        self.app.navigator.navigate_to(ScreenName.WORKSPACE)
        ws = self.app.workspace_screen
        ws.on_pre_enter()

        # Cursor starts at 0 (starting position). Playing 1. d4 (d2d4) MUST NOT overwrite 1. e4 e5 2. Nf3 Nc6!
        self.assertEqual(imp_session.board_manager.history.cursor, 0)
        ws.board_widget.on_square_tapped("d2")
        ws.board_widget.on_square_tapped("d4")

        h = imp_session.board_manager.history
        self.assertTrue(h.is_in_variant)
        self.assertEqual(len(h.variants), 1)
        self.assertEqual(len(h.mainline_nodes), 4)  # Original imported game 100% preserved!
        self.assertEqual(h.current_node.san, "d4")

        # Return to original game moves via '↩ Mainline' button
        self.assertFalse(ws.btn_mainline.disabled)
        ws.btn_mainline.trigger_release()
        self.assertFalse(h.is_in_variant)
        self.assertEqual([n.san for n in h.nodes], ["e4", "e5", "Nf3", "Nc6"])

        # Step to move 2 (after 1. e4 e5, cursor=2) and play 2. Bc4 (f1c4) as a second variant
        ws.btn_next.trigger_release()
        ws.btn_next.trigger_release()
        self.assertEqual(h.cursor, 2)
        ws.board_widget.on_square_tapped("f1")
        ws.board_widget.on_square_tapped("c4")
        self.assertTrue(h.is_in_variant)
        self.assertEqual(len(h.variants), 2)
        self.assertEqual(len(h.mainline_nodes), 4)

        # Switch back to mainline and verify all 4 original moves are still intact
        ws.btn_mainline.trigger_release()
        self.assertFalse(h.is_in_variant)
        self.assertEqual([n.san for n in h.nodes], ["e4", "e5", "Nf3", "Nc6"])

    def test_engine_evaluates_current_board_immediately_and_sees_mate_in_2(self) -> None:
        # Set up a custom position with forced Mate in 2 for White:
        # White Kf6, Qh5; Black Kg8 -> 1. Qg6+ Kh8 2. Qg7#
        ed = self.app.custom_editor_screen
        ed.position_title_input.text = "Mate in 2 Study"
        ed.apply_fen_input("6k1/8/5K2/7Q/8/8/8/8 w - - 0 1")
        # Verify piece palette uses KivyIconButton with the user's lowercase PNG icons
        self.assertTrue(ed.piece_buttons["K"].icon_path.endswith("wk.png"))
        self.assertTrue(ed.piece_buttons["q"].icon_path.endswith("bq.png"))

        ed.btn_start_play.trigger_release()
        ws = self.app.workspace_screen
        ws.on_pre_enter()

        # Without playing any move, turn ON Stockfish engine and verify it evaluates the Custom FEN immediately!
        ws.engine_panel.toggle_analysis_btn.trigger_release()
        self.container.engine_manager.wait_for_all_engines(timeout=5.0)
        ws.engine_panel.refresh()

        bundled_id = self.container.engine_registry.list_engines()[0].engine_id
        res = self.container.engine_manager.get_results()[bundled_id]
        self.assertEqual(res.fen, "6k1/8/5K2/7Q/8/8/8/8 w - - 0 1")
        self.assertTrue(res.variations[0].score.is_mate)
        self.assertEqual(res.variations[0].score.white_mate, 2)

        # Play 1. Qg6+ Kh8 2. Qg7# in the custom position and run Game Review
        ws.board_widget.on_square_tapped("h5")
        ws.board_widget.on_square_tapped("g6")
        ws.board_widget.on_square_tapped("g8")
        ws.board_widget.on_square_tapped("h8")
        ws.board_widget.on_square_tapped("g6")
        ws.board_widget.on_square_tapped("g7")

        rep = ws.run_classification_now(search_depth=2)
        self.assertIsNotNone(rep)
        self.assertEqual(rep.total_plies_analyzed, 3)
        self.assertIn("★Best:", ws.classification_status_label.text)
        # Verify the Chess.com-style Scorecard box opened automatically over the board with Accuracy & Game Rating
        self.assertTrue(ws.is_scorecard_open)
        # Verify the 4 custom evaluation icons (Best, Excellent, Good, Book) are loaded in the Scorecard
        self.assertTrue(ws.scorecard_widget.category_badge_widgets["Best"].icon_path.endswith("best.png"))
        self.assertTrue(ws.scorecard_widget.category_badge_widgets["Excellent"].icon_path.endswith("excellent.png"))
        self.assertTrue(ws.scorecard_widget.category_badge_widgets["Good"].icon_path.endswith("good.png"))
        self.assertTrue(ws.scorecard_widget.category_badge_widgets["Book"].icon_path.endswith("book.png"))
        self.assertIn("Stockfish 19", self.container.engine_registry.list_engines()[0].display_name)
        self.assertGreaterEqual(rep.white_summary.game_rating, 400)
        # Close scorecard back to board and verify stepping through moves shows full explanation in coach_box
        ws.scorecard_widget.btn_close.trigger_release()
        self.assertFalse(ws.is_scorecard_open)
        ws.nav_last()
        self.assertIn("Move ", ws.current_move_eval_label.text)

    def test_rename_and_delete_saved_sessions(self) -> None:
        # Start manual game and rename it inside Workspace
        self.app.home_screen.btn_manual_game.trigger_release()
        ws = self.app.workspace_screen
        sid = self.container.active_session.session_id
        ws.rename_current_session("My Sicilian Analysis")
        self.assertEqual(self.container.active_session.metadata.title, "My Sicilian Analysis")

        # Return to Home screen, test tapping the Edit icon button on the row first (pre-fills input),
        # typing new name, and tapping '✓ Save' (btn_save_rename)!
        self.app.navigator.navigate_to(ScreenName.HOME)
        home = self.app.home_screen
        home.on_pre_enter()
        home.on_edit_button_tapped(sid, "My Sicilian Analysis")
        self.assertEqual(home._editing_session_id, sid)
        self.assertEqual(home.rename_input.text, "My Sicilian Analysis")
        self.assertFalse(home.btn_save_rename.disabled)
        home.rename_input.text = "Renamed via Edit Icon"
        home.btn_save_rename.trigger_release()
        loaded = self.container.session_repo.load_session(sid)
        self.assertEqual(loaded.metadata.title, "Renamed via Edit Icon")

        home.delete_saved_session(sid)
        remaining_ids = [r["session_id"] for r in self.container.session_repo.list_sessions()]
        self.assertNotIn(sid, remaining_ids)


if __name__ == "__main__":
    unittest.main()
