"""Repository classes for sessions, moves, custom positions, cached evaluations, engines, and preferences."""
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional
from chess_analyzer.analysis.move_classifier import MoveClassification, MoveQuality
from chess_analyzer.domain.game_session import GameSession, SessionMetadata
from chess_analyzer.domain.move_history import MoveNode, MoveVariant
from chess_analyzer.domain.game_status import SessionMode
from chess_analyzer.engines.engine_models import (
    CandidateVariation,
    EngineConfig,
    EngineDefinition,
    EngineScore,
    SearchLimit,
)
from .database import DatabaseManager


class GameSessionRepository:
    """
    Persists and restores GameSession instances, keeping `original_pgn` strictly separate
    from edited continuation moves (`session_moves`), and managing associated move classifications.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def save_session(self, session: GameSession) -> None:
        conn = self._db.connection
        m = session.metadata
        h = session.board_manager.history
        now_iso = datetime.now(timezone.utc).isoformat()
        session.updated_at = now_iso

        with conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, mode, title, initial_fen, original_pgn,
                    white_player, black_player, white_elo, black_elo,
                    event, site, date_str, result, time_control, game_type,
                    source, external_id, external_url, player_username, player_color,
                    is_finished, classification_enabled, has_per_game_override,
                    classification_stale, cursor_ply, is_flipped, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title=excluded.title,
                    initial_fen=excluded.initial_fen,
                    original_pgn=excluded.original_pgn,
                    white_player=excluded.white_player,
                    black_player=excluded.black_player,
                    white_elo=excluded.white_elo,
                    black_elo=excluded.black_elo,
                    event=excluded.event,
                    site=excluded.site,
                    date_str=excluded.date_str,
                    result=excluded.result,
                    time_control=excluded.time_control,
                    game_type=excluded.game_type,
                    is_finished=excluded.is_finished,
                    classification_enabled=excluded.classification_enabled,
                    has_per_game_override=excluded.has_per_game_override,
                    classification_stale=excluded.classification_stale,
                    cursor_ply=excluded.cursor_ply,
                    is_flipped=excluded.is_flipped,
                    updated_at=excluded.updated_at
                """,
                (
                    session.session_id,
                    session.mode.value,
                    m.title,
                    h.initial_fen,
                    session.original_pgn,
                    m.white_player,
                    m.black_player,
                    m.white_elo,
                    m.black_elo,
                    m.event,
                    m.site,
                    m.date,
                    m.result,
                    m.time_control,
                    m.game_type,
                    m.source,
                    m.external_id,
                    m.external_url,
                    m.player_username,
                    m.player_color,
                    int(session.is_finished),
                    int(session.classification_enabled),
                    int(session.has_per_game_classification_override),
                    int(session.is_classification_stale),
                    h.cursor,
                    int(session.board_manager.is_flipped),
                    session.created_at,
                    session.updated_at,
                ),
            )

            conn.execute("DELETE FROM session_moves WHERE session_id = ?", (session.session_id,))
            for node in h.mainline_nodes:
                conn.execute(
                    """
                    INSERT INTO session_moves (
                        session_id, ply, uci, san, fen_before, fen_after,
                        turn_before, fullmove_number, is_capture, is_check,
                        is_checkmate, is_castling, is_en_passant, promotion, comment
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        node.ply,
                        node.uci,
                        node.san,
                        node.fen_before,
                        node.fen_after,
                        node.turn_before,
                        node.fullmove_number,
                        int(node.is_capture),
                        int(node.is_check),
                        int(node.is_checkmate),
                        int(node.is_castling),
                        int(node.is_en_passant),
                        node.promotion,
                        node.comment,
                    ),
                )

            conn.execute("DELETE FROM session_variants WHERE session_id = ?", (session.session_id,))
            conn.execute(
                "INSERT INTO session_variants (session_id, variant_id, name, branch_ply, nodes_json) VALUES (?, ?, ?, ?, ?)",
                (session.session_id, 0, "__FULL_VARIATION_TREE__", 0, h.to_tree_json()),
            )

    def load_session(self, session_id: str) -> GameSession:
        conn = self._db.connection
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(f"Saved session '{session_id}' not found.")

        meta = SessionMetadata(
            title=row["title"],
            white_player=row["white_player"],
            black_player=row["black_player"],
            white_elo=row["white_elo"],
            black_elo=row["black_elo"],
            event=row["event"],
            site=row["site"],
            date=row["date_str"],
            result=row["result"],
            time_control=row["time_control"],
            game_type=row["game_type"],
            source=row["source"],
            external_id=row["external_id"],
            external_url=row["external_url"],
            player_username=row["player_username"],
            player_color=row["player_color"],
        )

        session = GameSession(
            mode=SessionMode(row["mode"]),
            initial_fen=row["initial_fen"],
            session_id=row["session_id"],
            metadata=meta,
            original_pgn=row["original_pgn"],
        )
        move_rows = conn.execute(
            "SELECT uci, comment FROM session_moves WHERE session_id = ? ORDER BY ply ASC",
            (session_id,),
        ).fetchall()
        for mr in move_rows:
            session.board_manager.play_move_uci(mr["uci"], comment=mr["comment"] or "")

        target_cursor = min(int(row["cursor_ply"]), session.board_manager.history.total_plies)
        session.board_manager.history.go_to_ply(target_cursor)
        session.board_manager.set_flipped(bool(row["is_flipped"]))

        session.is_finished = bool(row["is_finished"])
        session.classification_enabled = bool(row["classification_enabled"])
        session.has_per_game_classification_override = bool(row["has_per_game_override"])
        session._classification_stale = bool(row["classification_stale"])
        var_rows = conn.execute(
            "SELECT variant_id, name, branch_ply, nodes_json FROM session_variants WHERE session_id = ? ORDER BY variant_id ASC",
            (session_id,),
        ).fetchall()
        for vr in var_rows:
            if int(vr["variant_id"]) == 0 and vr["name"] == "__FULL_VARIATION_TREE__":
                try:
                    session.board_manager.history.load_tree_json(vr["nodes_json"])
                    session.board_manager.history.go_to_ply(
                        min(int(row["cursor_ply"]), session.board_manager.history.total_plies)
                    )
                except Exception:
                    pass
                break

        session.created_at = row["created_at"]
        session.updated_at = row["updated_at"]
        return session

    def rename_session(self, session_id: str, new_title: str) -> str:
        cleaned = (new_title or "").strip()
        if not cleaned:
            raise ValueError("Title cannot be empty.")
        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection:
            self._db.connection.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                (cleaned, now, session_id),
            )
        return cleaned

    def rename_custom_position(self, position_id: str, new_name: str) -> str:
        cleaned = (new_name or "").strip()
        if not cleaned:
            raise ValueError("Position name cannot be empty.")
        with self._db.connection:
            self._db.connection.execute(
                "UPDATE saved_positions SET name = ? WHERE position_id = ?",
                (cleaned, position_id),
            )
        return cleaned

    def delete_custom_position(self, position_id: str) -> None:
        with self._db.connection:
            self._db.connection.execute("DELETE FROM saved_positions WHERE position_id = ?", (position_id,))

    def list_sessions(self, mode: Optional[SessionMode] = None) -> List[Dict[str, Any]]:
        conn = self._db.connection
        if mode is not None:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE mode = ? ORDER BY updated_at DESC",
                (mode.value,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        with self._db.connection:
            self._db.connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def save_classifications(self, session_id: str, classifications: List[MoveClassification]) -> None:
        conn = self._db.connection
        with conn:
            conn.execute("DELETE FROM move_classifications WHERE session_id = ?", (session_id,))
            for c in classifications:
                conn.execute(
                    """
                    INSERT INTO move_classifications (
                        session_id, ply, played_uci, played_san, mover_color,
                        quality, badge_symbol, badge_text,
                        eval_before_cp, eval_before_mate, eval_before_pov,
                        eval_after_cp, eval_after_mate, eval_after_pov,
                        best_move_uci, best_move_san, cp_loss, win_prob_loss,
                        engine_id, engine_version, search_depth, confidence, explanation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        c.ply,
                        c.played_uci,
                        c.played_san,
                        c.mover_color,
                        c.quality.value,
                        c.badge_symbol,
                        c.badge_text,
                        c.eval_before.raw_cp_pov if c.eval_before else None,
                        c.eval_before.raw_mate_pov if c.eval_before else None,
                        c.eval_before.pov_color if c.eval_before else None,
                        c.eval_after.raw_cp_pov if c.eval_after else None,
                        c.eval_after.raw_mate_pov if c.eval_after else None,
                        c.eval_after.pov_color if c.eval_after else None,
                        c.best_move_uci,
                        c.best_move_san,
                        c.cp_loss,
                        c.win_prob_loss,
                        c.engine_id,
                        c.engine_version,
                        c.search_depth,
                        c.confidence,
                        c.explanation,
                    ),
                )

    def load_classifications(self, session_id: str) -> List[MoveClassification]:
        rows = self._db.connection.execute(
            "SELECT * FROM move_classifications WHERE session_id = ? ORDER BY ply ASC",
            (session_id,),
        ).fetchall()
        items: List[MoveClassification] = []
        for r in rows:
            ev_before = (
                EngineScore(r["eval_before_cp"], r["eval_before_mate"], r["eval_before_pov"])
                if r["eval_before_pov"]
                else None
            )
            ev_after = (
                EngineScore(r["eval_after_cp"], r["eval_after_mate"], r["eval_after_pov"])
                if r["eval_after_pov"]
                else None
            )
            items.append(
                MoveClassification(
                    ply=r["ply"],
                    played_uci=r["played_uci"],
                    played_san=r["played_san"],
                    mover_color=r["mover_color"],
                    quality=MoveQuality(r["quality"]),
                    badge_symbol=r["badge_symbol"],
                    badge_text=r["badge_text"],
                    eval_before=ev_before,
                    eval_after=ev_after,
                    best_move_uci=r["best_move_uci"],
                    best_move_san=r["best_move_san"],
                    cp_loss=r["cp_loss"],
                    win_prob_loss=r["win_prob_loss"],
                    engine_id=r["engine_id"],
                    engine_version=r["engine_version"],
                    search_depth=r["search_depth"],
                    confidence=r["confidence"],
                    explanation=r["explanation"],
                )
            )
        return items

    def save_custom_position(self, position_id: str, name: str, fen: str, notes: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection:
            self._db.connection.execute(
                """
                INSERT INTO saved_positions (position_id, name, fen, notes, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(position_id) DO UPDATE SET name=excluded.name, fen=excluded.fen, notes=excluded.notes
                """,
                (position_id, name, fen, notes, now),
            )

    def list_custom_positions(self) -> List[Dict[str, Any]]:
        rows = self._db.connection.execute("SELECT * FROM saved_positions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


class AnalysisCacheRepository:
    """
    Caches engine evaluations keyed by `(fen, move_history_hash, engine_id, engine_version, multipv, search_depth)`
    and handles corrupt cached entries safely (Section 11 & Section 16).
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    @staticmethod
    def make_cache_key(
        fen: str,
        uci_history: List[str],
        engine_id: str,
        engine_version: str,
        multipv: int,
        search_depth: int,
    ) -> tuple[str, str]:
        hist_hash = hashlib.sha256(" ".join(uci_history).encode("utf-8")).hexdigest()[:16]
        raw = f"{fen}|{hist_hash}|{engine_id}|{engine_version}|mpv={multipv}|d={search_depth}"
        key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return key, hist_hash

    def put(
        self,
        fen: str,
        uci_history: List[str],
        engine_id: str,
        engine_version: str,
        multipv: int,
        search_depth: int,
        variations: List[CandidateVariation],
    ) -> str:
        key, hist_hash = self.make_cache_key(fen, uci_history, engine_id, engine_version, multipv, search_depth)
        payload = [
            {
                "multipv_index": v.multipv_index,
                "raw_cp_pov": v.score.raw_cp_pov,
                "raw_mate_pov": v.score.raw_mate_pov,
                "pov_color": v.score.pov_color,
                "depth": v.depth,
                "seldepth": v.seldepth,
                "pv_uci": v.pv_uci,
                "pv_san": v.pv_san,
                "nodes": v.nodes,
                "nps": v.nps,
                "time_ms": v.time_ms,
            }
            for v in variations
        ]
        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection:
            self._db.connection.execute(
                """
                INSERT INTO analysis_cache (
                    cache_key, fen, move_history_hash, engine_id, engine_version,
                    multipv, search_depth, variations_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    variations_json=excluded.variations_json,
                    created_at=excluded.created_at
                """,
                (key, fen, hist_hash, engine_id, engine_version, multipv, search_depth, json.dumps(payload), now),
            )
        return key

    def get(
        self,
        fen: str,
        uci_history: List[str],
        engine_id: str,
        engine_version: str,
        multipv: int,
        search_depth: int,
    ) -> Optional[List[CandidateVariation]]:
        key, _ = self.make_cache_key(fen, uci_history, engine_id, engine_version, multipv, search_depth)
        row = self._db.connection.execute(
            "SELECT variations_json FROM analysis_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        try:
            items = json.loads(row["variations_json"])
            result: List[CandidateVariation] = []
            for item in items:
                result.append(
                    CandidateVariation(
                        multipv_index=int(item["multipv_index"]),
                        score=EngineScore(
                            raw_cp_pov=item.get("raw_cp_pov"),
                            raw_mate_pov=item.get("raw_mate_pov"),
                            pov_color=item["pov_color"],
                        ),
                        depth=int(item["depth"]),
                        seldepth=int(item["seldepth"]),
                        pv_uci=list(item["pv_uci"]),
                        pv_san=list(item.get("pv_san", [])),
                        nodes=int(item.get("nodes", 0)),
                        nps=int(item.get("nps", 0)),
                        time_ms=int(item.get("time_ms", 0)),
                        is_complete=True,
                    )
                )
            return result
        except (ValueError, KeyError, TypeError):
            # Corrupt cached entry recovery (Section 16): evict corrupt entry and return None
            with self._db.connection:
                self._db.connection.execute("DELETE FROM analysis_cache WHERE cache_key = ?", (key,))
            return None

    def clear_cache(self) -> None:
        with self._db.connection:
            self._db.connection.execute("DELETE FROM analysis_cache")


class EngineRegistryRepository:
    """Persists registered Stockfish engines and their settings."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def save_engines(self, engines: List[EngineDefinition]) -> None:
        conn = self._db.connection
        with conn:
            conn.execute("DELETE FROM registered_engines")
            for e in engines:
                conn.execute(
                    """
                    INSERT INTO registered_engines (
                        engine_id, display_name, version_build, binary_path,
                        is_bundled, enabled, transport_type, visible_variations,
                        threads, hash_mb, max_depth, movetime_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        e.engine_id,
                        e.display_name,
                        e.version_build,
                        e.binary_path,
                        int(e.is_bundled),
                        int(e.enabled),
                        e.transport_type,
                        e.config.visible_variations,
                        e.config.threads,
                        e.config.hash_mb,
                        e.config.search_limit.max_depth,
                        e.config.search_limit.movetime_ms,
                    ),
                )

    def load_engines(self) -> List[EngineDefinition]:
        rows = self._db.connection.execute("SELECT * FROM registered_engines").fetchall()
        engines: List[EngineDefinition] = []
        for r in rows:
            engines.append(
                EngineDefinition(
                    engine_id=r["engine_id"],
                    display_name=r["display_name"],
                    version_build=r["version_build"],
                    binary_path=r["binary_path"],
                    is_bundled=bool(r["is_bundled"]),
                    enabled=bool(r["enabled"]),
                    transport_type=r["transport_type"],
                    config=EngineConfig(
                        visible_variations=int(r["visible_variations"]),
                        threads=int(r["threads"]),
                        hash_mb=int(r["hash_mb"]),
                        search_limit=SearchLimit(
                            max_depth=r["max_depth"],
                            movetime_ms=r["movetime_ms"],
                        ),
                    ),
                )
            )
        return engines


class PreferencesRepository:
    """Persists validated user settings in SQLite."""

    DEFAULT_PREFERENCES: Dict[str, Any] = {
        "default_board_orientation": "white",
        "board_theme": "classic_wood",
        "piece_set": "cburnett",
        "move_highlighting": True,
        "default_engine_enabled": False,  # Section 7.1 & 13: OFF by default
        "continuous_analysis_default": False,  # Section 13: Never enable continuous analysis by default
        "default_variations_per_engine": 3,
        "analysis_max_depth": 12,
        "analysis_movetime_ms": 2000,
        "cpu_thread_budget": 2,
        "memory_hash_limit_mb": 64,
        "imported_classification_default": True,  # Section 8.3: ON for imported games
        "manual_custom_classification_default": False,  # Section 8.3: OFF for manual/custom until finished
        "auto_save_sessions": True,
        "default_import_platform": "chesscom",
        "default_import_page_size": 20,
    }

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get_all(self) -> Dict[str, Any]:
        prefs = dict(self.DEFAULT_PREFERENCES)
        rows = self._db.connection.execute("SELECT pref_key, pref_value_json FROM user_preferences").fetchall()
        for r in rows:
            try:
                prefs[r["pref_key"]] = json.loads(r["pref_value_json"])
            except ValueError:
                pass
        return prefs

    def get(self, key: str, default: Any = None) -> Any:
        all_prefs = self.get_all()
        return all_prefs.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._validate_preference(key, value)
        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection:
            self._db.connection.execute(
                """
                INSERT INTO user_preferences (pref_key, pref_value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(pref_key) DO UPDATE SET
                    pref_value_json=excluded.pref_value_json,
                    updated_at=excluded.updated_at
                """,
                (key, json.dumps(value), now),
            )

    @staticmethod
    def _validate_preference(key: str, value: Any) -> None:
        if key == "default_variations_per_engine" and not (1 <= int(value) <= 5):
            raise ValueError("default_variations_per_engine must be between 1 and 5.")
        if key == "cpu_thread_budget" and int(value) < 1:
            raise ValueError("cpu_thread_budget must be >= 1.")
        if key == "memory_hash_limit_mb" and int(value) < 8:
            raise ValueError("memory_hash_limit_mb must be >= 8.")
        if key == "default_board_orientation" and value not in ("white", "black"):
            raise ValueError("default_board_orientation must be 'white' or 'black'.")
