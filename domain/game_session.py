"""Unified GameSession managing Imported, Manual, and Custom Position modes and classification policies."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
import uuid
import chess
from .board_manager import BoardManager
from .game_status import GameStatus, SessionMode
from .move_history import MoveNode
from .position import PositionBuilder


@dataclass
class SessionMetadata:
    """Metadata for imported, manual, or custom chess sessions."""
    title: str = "Untitled Session"
    white_player: str = "White"
    black_player: str = "Black"
    white_elo: Optional[int] = None
    black_elo: Optional[int] = None
    event: str = "Local Analysis"
    site: str = "Local"
    date: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y.%m.%d"))
    result: str = "*"
    time_control: str = "-"
    game_type: str = "standard"
    source: str = "local"  # "chesscom", "lichess", "manual", "custom", "pgn"
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    player_username: Optional[str] = None
    player_color: Optional[str] = None  # "white" or "black"


class GameSession:
    """
    Single unified chess session supporting all three creation modes:
    1. IMPORTED: Move classification ON by default (unless overridden by global/per-game setting).
    2. MANUAL: Move classification OFF by default until user finishes game and opts in.
    3. CUSTOM: Starts from an arbitrary validated position; classification OFF by default
       until user finishes the continuation and opts in; applies ONLY to recorded continuation.
    """

    def __init__(
        self,
        mode: SessionMode,
        initial_fen: str = chess.STARTING_FEN,
        session_id: Optional[str] = None,
        metadata: Optional[SessionMetadata] = None,
        original_pgn: Optional[str] = None,
        global_imported_classification_default: bool = True,
    ) -> None:
        self.session_id: str = session_id or str(uuid.uuid4())
        self.mode: SessionMode = mode
        self.board_manager = BoardManager(initial_fen=initial_fen)
        self.metadata: SessionMetadata = metadata or SessionMetadata(source=mode.value)
        self.original_pgn: Optional[str] = original_pgn
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.updated_at: str = self.created_at

        # Completion & Move Classification Policy state (Section 8)
        if mode == SessionMode.IMPORTED:
            self.is_finished: bool = True
            self.classification_enabled: bool = bool(global_imported_classification_default)
            self.has_per_game_classification_override: bool = False
        else:
            self.is_finished = False
            self.classification_enabled = False
            self.has_per_game_classification_override = False

        self._classified_revision: Optional[int] = None
        self._classification_stale: bool = False
        self._on_classifications_invalidated: List[Callable[[str], None]] = []

    @classmethod
    def create_manual(cls, metadata: Optional[SessionMetadata] = None) -> "GameSession":
        meta = metadata or SessionMetadata(title="Manual Game", source="manual")
        return cls(mode=SessionMode.MANUAL, initial_fen=chess.STARTING_FEN, metadata=meta)

    @classmethod
    def create_from_custom_position(
        cls,
        builder: PositionBuilder,
        metadata: Optional[SessionMetadata] = None,
    ) -> "GameSession":
        validated_board = builder.build_board()
        meta = metadata or SessionMetadata(title="Custom Position", source="custom")
        return cls(
            mode=SessionMode.CUSTOM,
            initial_fen=validated_board.fen(),
            metadata=meta,
        )

    @classmethod
    def create_imported(
        cls,
        initial_fen: str,
        uci_moves: List[str],
        metadata: SessionMetadata,
        original_pgn: str,
        global_imported_classification_default: bool = True,
    ) -> "GameSession":
        session = cls(
            mode=SessionMode.IMPORTED,
            initial_fen=initial_fen,
            metadata=metadata,
            original_pgn=original_pgn,
            global_imported_classification_default=global_imported_classification_default,
        )
        for uci in uci_moves:
            session.board_manager.play_move_uci(uci)
        session.board_manager.history.go_to_first()
        session._classification_stale = False
        return session

    def add_invalidation_listener(self, callback: Callable[[str], None]) -> None:
        self._on_classifications_invalidated.append(callback)

    @property
    def is_classification_stale(self) -> bool:
        return self._classification_stale

    def mark_classifications_computed(self) -> None:
        self._classified_revision = self.board_manager.history.revision
        self._classification_stale = False

    def _check_history_mutation(self, prev_revision: int) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        curr_revision = self.board_manager.history.revision
        if curr_revision != prev_revision and self._classified_revision is not None:
            self._classification_stale = True
            for cb in self._on_classifications_invalidated:
                cb(self.session_id)

    def play_move_uci(self, uci_str: str, comment: str = "") -> MoveNode:
        prev_rev = self.board_manager.history.revision
        node = self.board_manager.play_move_uci(uci_str, comment=comment)
        self._check_history_mutation(prev_rev)
        return node

    def play_move_squares(
        self,
        from_square: str,
        to_square: str,
        promotion: Optional[str] = None,
        comment: str = "",
    ) -> MoveNode:
        prev_rev = self.board_manager.history.revision
        node = self.board_manager.play_move_squares(from_square, to_square, promotion=promotion, comment=comment)
        self._check_history_mutation(prev_rev)
        return node

    def undo_move(self) -> Optional[MoveNode]:
        prev_rev = self.board_manager.history.revision
        node = self.board_manager.history.undo()
        self._check_history_mutation(prev_rev)
        return node

    def redo_move(self) -> Optional[MoveNode]:
        prev_rev = self.board_manager.history.revision
        node = self.board_manager.history.redo()
        self._check_history_mutation(prev_rev)
        return node

    def finish_game(self, enable_classification: bool = True) -> None:
        """
        Mark a manual or custom-position session as finished and optionally enable
        Chess.com-like move classification (Section 8.2).
        """
        self.is_finished = True
        self.classification_enabled = bool(enable_classification)
        self.has_per_game_classification_override = True
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def rename(self, new_title: str) -> str:
        """Rename this game or custom position session."""
        cleaned = (new_title or "").strip()
        if not cleaned:
            raise ValueError("Session title cannot be empty.")
        self.metadata.title = cleaned
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return self.metadata.title

    def reopen_for_editing(self) -> None:
        """Allow reopening a finished game to resume playing or editing moves."""
        self.is_finished = False
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def set_per_game_classification(self, enabled: bool) -> None:
        """Explicitly override move classification preference for this game."""
        if self.mode in (SessionMode.MANUAL, SessionMode.CUSTOM) and enabled and not self.is_finished:
            raise PermissionError(
                "In Manual and Custom Position modes, move classification can only be activated "
                "after finishing the game ('Finish game and analyze moves')."
            )
        self.classification_enabled = bool(enabled)
        self.has_per_game_classification_override = True
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def apply_global_classification_setting(self, imported_default_enabled: bool) -> None:
        """
        Update session classification state when global setting changes,
        WITHOUT overwriting an explicit per-game preference (Section 8.3).
        """
        if self.has_per_game_classification_override:
            return
        if self.mode == SessionMode.IMPORTED:
            self.classification_enabled = bool(imported_default_enabled)

    def get_status(self) -> GameStatus:
        return self.board_manager.get_status()

    def export_pgn(self) -> str:
        headers = {
            "Event": self.metadata.event,
            "Site": self.metadata.site,
            "Date": self.metadata.date,
            "White": self.metadata.white_player,
            "Black": self.metadata.black_player,
            "Result": self.metadata.result if self.metadata.result != "*" else self.get_status().result,
        }
        return self.board_manager.history.to_pgn(headers=headers, result=headers["Result"])

    def export_fen(self) -> str:
        return self.board_manager.get_active_fen()
