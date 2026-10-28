"""Dependency injection container wiring storage, domain, engines, analysis, and integrations."""
from dataclasses import dataclass
from typing import Optional
from chess_analyzer.analysis import AnalysisService, GameAnalyzer, MoveClassifier
from chess_analyzer.domain import GameSession
from chess_analyzer.engines import EngineManager, EngineRegistry, ResourceBudget, ResourceScheduler
from chess_analyzer.integrations import ChessComClient, LichessClient, PGNImporter
from chess_analyzer.storage import (
    AnalysisCacheRepository,
    DatabaseManager,
    EngineRegistryRepository,
    GameSessionRepository,
    PreferencesRepository,
)


@dataclass
class AppContainer:
    """Central dependency container holding singletons and active session state."""
    db: DatabaseManager
    session_repo: GameSessionRepository
    cache_repo: AnalysisCacheRepository
    engine_repo: EngineRegistryRepository
    prefs_repo: PreferencesRepository
    engine_registry: EngineRegistry
    resource_scheduler: ResourceScheduler
    engine_manager: EngineManager
    move_classifier: MoveClassifier
    game_analyzer: GameAnalyzer
    analysis_service: AnalysisService
    chesscom_client: ChessComClient
    lichess_client: LichessClient
    pgn_importer: PGNImporter
    active_session: Optional[GameSession] = None
    is_offline: bool = False

    def set_active_session(self, session: GameSession) -> None:
        """Set the single authoritative active GameSession and wire auto-save/invalidation."""
        self.active_session = session
        default_orient = self.prefs_repo.get("default_board_orientation", "white")
        session.board_manager.set_flipped(default_orient == "black")

        if self.prefs_repo.get("auto_save_sessions", True):
            self.session_repo.save_session(session)

        def _on_invalidated(sess_id: str) -> None:
            self.analysis_service.invalidate_report(sess_id)
            if self.prefs_repo.get("auto_save_sessions", True):
                self.session_repo.save_session(session)

        session.add_invalidation_listener(_on_invalidated)

    def on_app_pause(self) -> None:
        """Handle mobile app backgrounding safely (Section 16): pause searches and flush state."""
        self.engine_manager.stop_all_searches()
        self.game_analyzer.cancel()
        if self.active_session and self.prefs_repo.get("auto_save_sessions", True):
            self.session_repo.save_session(self.active_session)

    def on_app_resume(self) -> None:
        """Handle mobile app resume: if live analysis was active, resume for current board position."""
        if self.active_session and self.engine_manager.is_analysis_active:
            self.engine_manager.analyze_position(self.active_session.board_manager.get_active_fen())

    def shutdown(self) -> None:
        self.on_app_pause()
        self.engine_manager.shutdown()
        self.db.close()
