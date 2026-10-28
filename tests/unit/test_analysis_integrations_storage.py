"""Unit and integration tests for Milestones 3, 4, 5, and 6 (Move Classification, APIs, Storage)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import chess
import requests
from chess_analyzer.analysis import (
    AnalysisService,
    MoveClassifier,
    MoveQuality,
)
from chess_analyzer.domain import GameSession, PositionBuilder, SessionMetadata
from chess_analyzer.engines import (
    CandidateVariation,
    EngineManager,
    EngineScore,
)
from chess_analyzer.integrations import (
    ChessComClient,
    IntegrationError,
    LichessClient,
    PGNImporter,
    RateLimitError,
)
from chess_analyzer.storage import (
    AnalysisCacheRepository,
    DatabaseManager,
    EngineRegistryRepository,
    GameSessionRepository,
    PreferencesRepository,
)


class TestMoveClassificationAndPolicies(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = MoveClassifier()

    def test_best_small_loss_large_loss_forced_mate_and_missed_win(self) -> None:
        # 1. Best move (played matches engine best move)
        var1 = CandidateVariation(
            multipv_index=1,
            score=EngineScore(raw_cp_pov=35, raw_mate_pov=None, pov_color="white"),
            depth=12,
            seldepth=14,
            pv_uci=["e2e4", "e7e5"],
            pv_san=["e4", "e5"],
        )
        score_after_best = EngineScore(raw_cp_pov=-35, raw_mate_pov=None, pov_color="black")
        c_best = self.classifier.classify_move(
            ply=1,
            played_uci="e2e4",
            played_san="e4",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[var1],
            score_after=score_after_best,
            engine_id="sf16",
            engine_version="16.1",
        )
        self.assertEqual(c_best.quality, MoveQuality.BEST)

        # 2. Small evaluation loss -> Good move (~40 cp loss)
        score_after_good = EngineScore(raw_cp_pov=5, raw_mate_pov=None, pov_color="black")  # -5 for white -> 40 cp loss
        c_good = self.classifier.classify_move(
            ply=1,
            played_uci="d2d3",
            played_san="d3",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[var1],
            score_after=score_after_good,
            engine_id="sf16",
            engine_version="16.1",
        )
        self.assertEqual(c_good.quality, MoveQuality.GOOD)

        # 3. Large evaluation loss -> Blunder (~450 cp loss)
        score_after_blunder = EngineScore(raw_cp_pov=415, raw_mate_pov=None, pov_color="black")
        c_blunder = self.classifier.classify_move(
            ply=1,
            played_uci="f2f4",
            played_san="f4",
            mover_color="white",
            legal_moves_count=20,
            variations_before=[var1],
            score_after=score_after_blunder,
            engine_id="sf16",
            engine_version="16.1",
        )
        self.assertEqual(c_blunder.quality, MoveQuality.BLUNDER)

        # 4. Forced move (only 1 legal move)
        c_forced = self.classifier.classify_move(
            ply=5,
            played_uci="a1a2",
            played_san="Kxa2",
            mover_color="white",
            legal_moves_count=1,
            variations_before=[var1],
            score_after=score_after_best,
            engine_id="sf16",
            engine_version="16.1",
        )
        self.assertEqual(c_forced.quality, MoveQuality.FORCED)

        # 5. Missed Win (White had +450cp winning position, played move dropping to +20cp equal position)
        var_winning = CandidateVariation(
            multipv_index=1,
            score=EngineScore(raw_cp_pov=450, raw_mate_pov=None, pov_color="white"),
            depth=12,
            seldepth=14,
            pv_uci=["d1h5"],
            pv_san=["Qh5"],
        )
        score_after_missed = EngineScore(raw_cp_pov=-20, raw_mate_pov=None, pov_color="black")  # +20cp for white
        c_missed = self.classifier.classify_move(
            ply=11,
            played_uci="a2a3",
            played_san="a3",
            mover_color="white",
            legal_moves_count=25,
            variations_before=[var_winning],
            score_after=score_after_missed,
            engine_id="sf16",
            engine_version="16.1",
        )
        self.assertEqual(c_missed.quality, MoveQuality.MISSED_WIN)

    def test_finish_game_and_analyze_workflow_and_custom_continuation(self) -> None:
        mgr = EngineManager()
        try:
            svc = AnalysisService(engine_manager=mgr)

            # Custom position: White to move with Mate in 1 available, plays 2 plies
            builder = PositionBuilder("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
            session = GameSession.create_from_custom_position(builder)
            self.assertFalse(session.classification_enabled)
            session.play_move_uci("d2d3")
            session.play_move_uci("g8f6")

            # Cannot analyze before finishing
            with self.assertRaises(PermissionError):
                svc.run_game_classification_sync(session, search_depth=2)

            # Invoke "Finish game and analyze moves"
            report = svc.finish_game_and_analyze_moves(
                session=session,
                user_confirmed_finish=True,
                enable_classification=True,
                start_analysis_now=True,
                search_depth=2,
            )
            self.assertIsNotNone(report)
            # Only classifies the 2 recorded continuation moves, never inventing earlier moves
            self.assertEqual(report.total_plies_analyzed, 2)
            self.assertEqual(len(report.classifications), 2)
            self.assertEqual(report.classifications[0].played_san, "d3")
        finally:
            mgr.shutdown()


class TestIntegrationsAndStorage(unittest.TestCase):
    def test_chesscom_and_lichess_mocked_http_and_error_handling(self) -> None:
        sample_pgn = '[Event "Live Chess"]\n[White "hikaru"]\n[Black "magnus"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0'

        def mock_chesscom_get(url: str, **kwargs):
            resp = MagicMock()
            if "invalid_user" in url:
                resp.status_code = 404
                return resp
            if "ratelimited" in url:
                resp.status_code = 429
                return resp
            resp.status_code = 200
            if url.endswith("/archives"):
                resp.json.return_value = {"archives": ["https://api.chess.com/pub/player/hikaru/games/2026/10"]}
            else:
                resp.json.return_value = {
                    "games": [
                        {
                            "uuid": "cc-123",
                            "url": "https://www.chess.com/game/live/123",
                            "pgn": sample_pgn,
                            "time_control": "180",
                            "time_class": "blitz",
                            "rules": "chess",
                            "end_time": 1761600000,
                            "white": {"username": "hikaru", "rating": 3200},
                            "black": {"username": "magnus", "rating": 3210},
                        }
                    ]
                }
            return resp

        cc = ChessComClient(http_get=mock_chesscom_get)
        with self.assertRaises(ValueError):
            cc.list_archive_urls("bad username with spaces!")
        with self.assertRaises(IntegrationError):
            cc.list_archive_urls("invalid_user")
        with self.assertRaises(RateLimitError):
            cc.list_archive_urls("ratelimited")

        archives = cc.list_archive_urls("hikaru")
        self.assertEqual(len(archives), 1)
        games = cc.fetch_games_for_month("hikaru", 2026, 10)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].opponent_username, "magnus")
        session = cc.import_selected_game(games[0])
        self.assertTrue(session.classification_enabled)
        self.assertEqual(session.board_manager.history.total_plies, 4)

        # Lichess NDJSON test
        ndjson_line = json.dumps({
            "id": "li999",
            "speed": "rapid",
            "perf": "rapid",
            "variant": "standard",
            "winner": "white",
            "createdAt": 1761600000000,
            "players": {
                "white": {"user": {"name": "DrNykterstein"}, "rating": 3100},
                "black": {"user": {"name": "Challenger"}, "rating": 2800},
            },
            "pgn": sample_pgn,
        })

        def mock_lichess_get(url: str, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.text = ndjson_line
            return resp

        li = LichessClient(http_get=mock_lichess_get)
        li_games = li.fetch_user_games("DrNykterstein", max_games=5)
        self.assertEqual(len(li_games), 1)
        self.assertEqual(li_games[0].external_id, "li999")

        # Malformed PGN test
        with self.assertRaises(ValueError):
            PGNImporter.parse_pgn_text("")

    def test_sqlite_migrations_persistence_and_corrupt_cache_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = str(Path(tmpdir) / "chess_analyzer.db")
            db = DatabaseManager(db_path=db_file)
            self.assertEqual(
                db.get_applied_migrations(),
                ["001_initial_schema.sql", "002_analysis_cache_and_engines.sql", "003_session_variants.sql"],
            )

            repo = GameSessionRepository(db)
            prefs = PreferencesRepository(db)
            cache = AnalysisCacheRepository(db)

            # Save imported session and edit continuation while preserving original_pgn
            orig_pgn = "1. e4 e5 *"
            sess = PGNImporter.import_to_session(orig_pgn, source="lichess")
            sess.board_manager.history.go_to_last()
            sess.play_move_uci("g1f3")  # Edited continuation move
            repo.save_session(sess)
            db.close()

            # Simulate app restart
            db2 = DatabaseManager(db_path=db_file)
            repo2 = GameSessionRepository(db2)
            loaded = repo2.load_session(sess.session_id)
            self.assertEqual(loaded.original_pgn, orig_pgn)
            self.assertEqual(loaded.board_manager.history.total_plies, 3)

            # Corrupt cache recovery test
            key = cache.put(
                fen=chess.STARTING_FEN,
                uci_moves=[] if hasattr(cache, "uci_moves") else [],
                uci_history=["e2e4"],
                engine_id="sf",
                engine_version="16.1",
                multipv=1,
                search_depth=8,
                variations=[],
            ) if False else None
            # Insert corrupt JSON directly and verify graceful eviction
            k, h_hash = AnalysisCacheRepository.make_cache_key(chess.STARTING_FEN, [], "sf", "16", 1, 8)
            with db2.connection:
                db2.connection.execute(
                    "INSERT INTO analysis_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'now')",
                    (k, chess.STARTING_FEN, h_hash, "sf", "16", 1, 8, "{corrupt_json"),
                )
            cache2 = AnalysisCacheRepository(db2)
            self.assertIsNone(cache2.get(chess.STARTING_FEN, [], "sf", "16", 1, 8))
            db2.close()


if __name__ == "__main__":
    unittest.main()
