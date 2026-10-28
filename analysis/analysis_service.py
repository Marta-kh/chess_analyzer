"""High-level AnalysisService coordinating live engine searches, move classification, and settings policies."""
from typing import Callable, Dict, Optional
from chess_analyzer.domain.game_session import GameSession
from chess_analyzer.engines.engine_manager import EngineManager
from .game_analyzer import GameAnalyzer, GameAnalysisProgress
from .game_report import GameAnalysisReport


class AnalysisService:
    """
    Coordinates:
    1. Live position MultiPV analysis via `EngineManager` (does NOT re-run full-game classification on move navigation).
    2. Explicit game-wide move classification via `GameAnalyzer` with strict adherence to Section 8 policies:
       - Imported games: Move classification ON by default (can be toggled globally or per-game).
       - Manual & Custom Position games: Move classification OFF by default; only activated via
         `finish_game_and_analyze_moves(...)` after user confirmation.
    3. Reuses already-computed `GameAnalysisReport` when valid (`not session.is_classification_stale`) unless
       `force_reanalyze=True` is explicitly requested.
    """

    def __init__(
        self,
        engine_manager: EngineManager,
        game_analyzer: Optional[GameAnalyzer] = None,
    ) -> None:
        self.engine_manager = engine_manager
        self.game_analyzer = game_analyzer or GameAnalyzer()
        self.global_imported_classification_default: bool = True
        self._reports_by_session: Dict[str, GameAnalysisReport] = {}

    def set_global_imported_classification_default(
        self,
        enabled: bool,
        active_session: Optional[GameSession] = None,
    ) -> None:
        self.global_imported_classification_default = bool(enabled)
        if active_session is not None:
            active_session.apply_global_classification_setting(self.global_imported_classification_default)

    def on_position_selected(self, session: GameSession) -> None:
        active_fen = session.board_manager.get_active_fen()
        self.engine_manager.set_current_fen(active_fen)
        if self.engine_manager.is_analysis_active:
            self.engine_manager.analyze_position(active_fen)

    def has_valid_review(self, session: Optional[GameSession]) -> bool:
        """Returns True if `session` already has a non-stale GameAnalysisReport."""
        if session is None or session.is_classification_stale:
            return False
        rep = self._reports_by_session.get(session.session_id)
        return rep is not None and rep.total_plies_analyzed == len(session.board_manager.history.mainline_nodes)

    def finish_game_and_analyze_moves(
        self,
        session: GameSession,
        user_confirmed_finish: bool,
        enable_classification: bool = True,
        start_analysis_now: bool = True,
        search_depth: int = 4,
    ) -> Optional[GameAnalysisReport]:
        if not user_confirmed_finish:
            return None
        session.finish_game(enable_classification=enable_classification)
        if enable_classification and start_analysis_now:
            return self.run_game_classification_sync(session, search_depth=search_depth)
        return None

    def run_game_classification_sync(
        self,
        session: GameSession,
        search_depth: int = 4,
        force_reanalyze: bool = False,
        on_progress: Optional[Callable[[GameAnalysisProgress], None]] = None,
    ) -> Optional[GameAnalysisReport]:
        if not force_reanalyze and self.has_valid_review(session):
            return self._reports_by_session[session.session_id]

        engines = self.engine_manager.registry.list_enabled_engines() or self.engine_manager.registry.list_engines()
        primary_engine = engines[0]
        report = self.game_analyzer.analyze_session_sync(
            session=session,
            engine_def=primary_engine,
            search_depth=search_depth,
            on_progress=on_progress,
            force_reanalyze=force_reanalyze,
        )
        if report is not None:
            self._reports_by_session[session.session_id] = report
        return report

    def get_report(self, session_id: str) -> Optional[GameAnalysisReport]:
        return self._reports_by_session.get(session_id)

    def invalidate_report(self, session_id: str) -> None:
        self._reports_by_session.pop(session_id, None)
