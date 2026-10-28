"""Unit and integration tests for Milestone 2: Stockfish UCI Engine Subsystem."""
import unittest
import chess
from chess_analyzer.engines import (
    EngineManager,
    EngineRegistry,
    MAX_REGISTERED_ENGINES,
    MAX_VARIATIONS_PER_ENGINE,
    ResourceBudget,
    ResourceScheduler,
    SearchLimit,
)


class TestEngineSubsystem(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = EngineRegistry()
        self.scheduler = ResourceScheduler(ResourceBudget(max_total_threads=4, max_total_hash_mb=64))
        self.manager = EngineManager(registry=self.registry, scheduler=self.scheduler)

    def tearDown(self) -> None:
        self.manager.shutdown()

    def test_default_engine_bundled_and_off_by_default(self) -> None:
        engines = self.registry.list_engines()
        self.assertEqual(len(engines), 1)
        bundled = engines[0]
        self.assertTrue(bundled.is_bundled)
        self.assertFalse(bundled.enabled)
        self.assertFalse(self.manager.is_analysis_active)

    def test_single_engine_analysis_and_add_remove_variations_up_to_five(self) -> None:
        bundled_id = self.registry.list_engines()[0].engine_id
        # Enable analysis
        self.manager.set_analysis_active(True, chess.STARTING_FEN)
        self.manager.wait_for_all_engines(timeout=5.0)
        results = self.manager.get_results()
        self.assertIn(bundled_id, results)
        res1 = results[bundled_id]
        self.assertEqual(res1.requested_variations, 1)
        self.assertEqual(len(res1.variations), 1)
        self.assertTrue(len(res1.variations[0].pv_uci) >= 1)

        # Click "Add variation" up to 3 lines, then 4, then 5
        for target_count in (2, 3, 4, 5):
            count = self.manager.add_variation(bundled_id)
            self.assertEqual(count, target_count)
            self.manager.wait_for_all_engines(timeout=5.0)
            res = self.manager.get_results()[bundled_id]
            self.assertEqual(res.requested_variations, target_count)
            self.assertEqual(len(res.variations), target_count)
            # Ensure still only 1 engine is active (didn't spawn additional engines)
            self.assertEqual(len(self.registry.list_enabled_engines()), 1)

        # Clicking "Add variation" at 5 must cap at 5
        self.assertEqual(self.manager.add_variation(bundled_id), MAX_VARIATIONS_PER_ENGINE)

        # Remove a variation: reduces variation count without disabling engine
        new_count = self.manager.remove_variation(bundled_id, multipv_index=2)
        self.assertEqual(new_count, 4)
        self.assertTrue(self.registry.get_engine(bundled_id).enabled)
        self.assertEqual(len(self.manager.get_results()[bundled_id].variations), 4)

    def test_fewer_than_five_legal_moves_explanation(self) -> None:
        # Position where White King on a1 is in check and has only 1 legal move (a1b1)
        # Black Queen on a2, Black King on c3 -> White King on a1 can only capture Qa2 (1 legal move)
        fen_one_move = "8/8/8/8/8/2k5/q7/K7 w - - 0 1"
        bundled_id = self.registry.list_engines()[0].engine_id
        self.registry.set_visible_variations(bundled_id, 5)
        self.manager.set_analysis_active(True, fen_one_move)
        self.manager.wait_for_all_engines(timeout=5.0)

        res = self.manager.get_results()[bundled_id]
        self.assertEqual(res.available_legal_moves, 1)
        self.assertEqual(len(res.variations), 1)
        self.assertEqual(res.variations[0].best_move_uci, "a1a2")
        self.assertIsNotNone(res.limited_variations_reason)
        self.assertIn("Only 1 legal move", res.limited_variations_reason)

    def test_multi_engine_registration_max_five_and_resource_budget(self) -> None:
        bundled_bin = self.registry.list_engines()[0].binary_path
        # Register 4 additional engines (total 5)
        for i in range(2, 6):
            eng = self.registry.register_engine(
                engine_id=f"sf_v{i}",
                display_name=f"Stockfish Dev #{i}",
                version_build=f"16.{i}",
                binary_path=bundled_bin,
                transport_type="in_process_ios" if i % 2 == 0 else "subprocess",
                enabled=True,
                visible_variations=2,
            )
            eng.config.threads = 4
            eng.config.hash_mb = 64

        self.assertEqual(len(self.registry.list_engines()), MAX_REGISTERED_ENGINES)
        # Attempting to register a 6th engine must fail
        with self.assertRaises(ValueError):
            self.registry.register_engine(
                engine_id="sf_v6",
                display_name="Stockfish 6",
                version_build="16.6",
                binary_path=bundled_bin,
            )

        # Verify resource scheduler enforces budget across all 5 active engines
        self.registry.set_engine_enabled("bundled_stockfish_16_1", True)
        active = self.registry.list_enabled_engines()
        self.assertEqual(len(active), 5)
        alloc = self.scheduler.allocate_resources(active)
        # Budget is 4 total threads, but minimum floor is 1 thread per engine (5 total)
        # Hash budget is 64 MB across 5 engines
        for eid, a in alloc.items():
            self.assertGreaterEqual(a["threads"], 1)
            self.assertGreaterEqual(a["hash_mb"], 8)

    def test_position_change_discards_stale_results_and_mate_scores(self) -> None:
        # Mate in 1 position for White: White Qh5, Bc4, Black King e8 -> Qxf7#
        mate_in_1_fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
        bundled_id = self.registry.list_engines()[0].engine_id
        self.manager.set_analysis_active(True, chess.STARTING_FEN)
        # Immediately switch position to Mate in 1 while search is running
        self.manager.analyze_position(mate_in_1_fen, search_limit_override=SearchLimit(max_depth=3))
        self.manager.wait_for_all_engines(timeout=5.0)

        res = self.manager.get_results()[bundled_id]
        self.assertEqual(res.fen, mate_in_1_fen)
        self.assertEqual(res.variations[0].best_move_uci, "h5f7")
        self.assertTrue(res.variations[0].score.is_mate)
        self.assertEqual(res.variations[0].score.white_mate, 1)
        self.assertEqual(res.variations[0].score.format_display("white"), "M+1")


    def test_windows_host_binary_detection_and_subprocess_fallback(self) -> None:
        from unittest.mock import patch
        from chess_analyzer.engines.engine_registry import is_binary_compatible_with_host
        from pathlib import Path

        linux_elf = Path(__file__).resolve().parent.parent.parent / "assets" / "engines" / "linux_x86_64" / "stockfish"
        with patch("platform.system", return_value="Windows"):
            # On Windows, a Linux ELF binary must NEVER be reported as compatible
            self.assertFalse(is_binary_compatible_with_host(linux_elf))
            win_reg = EngineRegistry()
            bundled = win_reg.list_engines()[0]
            self.assertTrue(bundled.binary_path.endswith(".py") or bundled.binary_path.endswith(".exe"))

            # Verify EngineManager runs real subprocess analysis using the Windows-selected engine
            win_mgr = EngineManager(registry=win_reg, scheduler=self.scheduler)
            try:
                win_mgr.set_analysis_active(True, chess.STARTING_FEN)
                win_mgr.wait_for_all_engines(timeout=5.0)
                res = win_mgr.get_results()[bundled.engine_id]
                self.assertEqual(len(res.variations), 1)
                self.assertTrue(len(res.variations[0].pv_uci) >= 1)
            finally:
                win_mgr.shutdown()


if __name__ == "__main__":
    unittest.main()
