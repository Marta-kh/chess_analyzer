"""Authoritative chess domain model independent of UI and storage."""
from .game_status import GameStatus, SessionMode, TerminationType
from .position import PositionBuilder, ValidationReport
from .move_history import MoveHistory, MoveNode, MoveVariant
from .board_manager import BoardManager
from .game_session import GameSession, SessionMetadata

__all__ = [
    "GameStatus",
    "SessionMode",
    "TerminationType",
    "PositionBuilder",
    "ValidationReport",
    "MoveHistory",
    "MoveNode",
    "MoveVariant",
    "BoardManager",
    "GameSession",
    "SessionMetadata",
]
