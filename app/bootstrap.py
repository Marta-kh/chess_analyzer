"""Application bootstrapper initializing SQLite database, preferences, and engine registry across Desktop, Android, and iOS."""
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Optional
from chess_analyzer.analysis import AnalysisService, GameAnalyzer, MoveClassifier
from chess_analyzer.engines import EngineManager, EngineRegistry, ResourceBudget, ResourceScheduler
from chess_analyzer.integrations import ChessComClient, LichessClient, PGNImporter
from chess_analyzer.storage import (
    AnalysisCacheRepository,
    DatabaseManager,
    EngineRegistryRepository,
    GameSessionRepository,
    PreferencesRepository,
)
from .dependencies import AppContainer


def _resolve_writable_data_dir() -> Path:
    """Resolves the platform-appropriate writable app data directory on Android, iOS, and Desktop."""
    # 1. Android (python-for-android / Buildozer sets ANDROID_PRIVATE)
    android_priv = os.environ.get("ANDROID_PRIVATE") or os.environ.get("ANDROID_APP_PATH")
    if android_priv:
        p = Path(android_priv) / "chess_analyzer_data"
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            pass

    # 2. iOS (kivy-ios sets HOME to the app sandbox root where Documents/ is writable)
    if os.environ.get("KIVY_BUILD") == "ios":
        docs = Path.home() / "Documents" / "chess_analyzer"
        try:
            docs.mkdir(parents=True, exist_ok=True)
            return docs
        except OSError:
            pass

    # 3. Desktop default (~/.chess_analyzer) with fallback to tempdir
    try:
        data_dir = Path.home() / ".chess_analyzer"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "chess_analyzer_data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def create_app_container(db_path: Optional[str] = None, assets_dir: Optional[Path] = None) -> AppContainer:
    if db_path is None:
        data_dir = _resolve_writable_data_dir()
        candidate = str(data_dir / "chess_analyzer.sqlite3")
        try:
            db = DatabaseManager(db_path=candidate)
        except sqlite3.OperationalError:
            fallback_dir = Path(tempfile.gettempdir()) / "chess_analyzer_data"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            db = DatabaseManager(db_path=str(fallback_dir / "chess_analyzer.sqlite3"))
    else:
        db = DatabaseManager(db_path=db_path)

    session_repo = GameSessionRepository(db)
    cache_repo = AnalysisCacheRepository(db)
    engine_repo = EngineRegistryRepository(db)
    prefs_repo = PreferencesRepository(db)

    prefs_repo.set("default_board_orientation", "white")
    prefs = prefs_repo.get_all()
    budget = ResourceBudget(
        max_total_threads=int(prefs.get("cpu_thread_budget", 2)),
        max_total_hash_mb=int(prefs.get("memory_hash_limit_mb", 64)),
    )
    scheduler = ResourceScheduler(budget=budget)
    registry = EngineRegistry(assets_dir=assets_dir)

    saved_engines = engine_repo.load_engines()
    for se in saved_engines:
        if not se.is_bundled:
            try:
                registry.register_engine(
                    engine_id=se.engine_id,
                    display_name=se.display_name,
                    version_build=se.version_build,
                    binary_path=se.binary_path,
                    transport_type=se.transport_type,
                    enabled=False,
                    visible_variations=se.config.visible_variations,
                )
            except Exception:
                pass

    engine_manager = EngineManager(registry=registry, scheduler=scheduler)
    classifier = MoveClassifier()
    game_analyzer = GameAnalyzer(classifier=classifier)
    analysis_service = AnalysisService(engine_manager=engine_manager, game_analyzer=game_analyzer)
    analysis_service.global_imported_classification_default = bool(
        prefs.get("imported_classification_default", True)
    )

    return AppContainer(
        db=db,
        session_repo=session_repo,
        cache_repo=cache_repo,
        engine_repo=engine_repo,
        prefs_repo=prefs_repo,
        engine_registry=registry,
        resource_scheduler=scheduler,
        engine_manager=engine_manager,
        move_classifier=classifier,
        game_analyzer=game_analyzer,
        analysis_service=analysis_service,
        chesscom_client=ChessComClient(),
        lichess_client=LichessClient(),
        pgn_importer=PGNImporter(),
    )
