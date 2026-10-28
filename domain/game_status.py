"""Game status and result models for the chess domain."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TerminationType(str, Enum):
    NONE = "none"
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    INSUFFICIENT_MATERIAL = "insufficient_material"
    SEVENTYFIVE_MOVES = "seventyfive_moves"
    FIVEFOLD_REPETITION = "fivefold_repetition"
    FIFTY_MOVES_CLAIMABLE = "fifty_moves_claimable"
    THREEFOLD_REPETITION_CLAIMABLE = "threefold_repetition_claimable"
    RESIGNATION = "resignation"
    AGREED_DRAW = "agreed_draw"
    TIMEOUT = "timeout"


class SessionMode(str, Enum):
    IMPORTED = "imported"
    MANUAL = "manual"
    CUSTOM = "custom"


@dataclass(frozen=True)
class GameStatus:
    """Authoritative status snapshot of a chess position."""
    turn: str  # "white" or "black"
    is_check: bool
    is_checkmate: bool
    is_stalemate: bool
    is_insufficient_material: bool
    is_seventyfive_moves: bool
    is_fivefold_repetition: bool
    can_claim_fifty_moves: bool
    can_claim_threefold_repetition: bool
    is_game_over: bool
    result: str  # "1-0", "0-1", "1/2-1/2", or "*"
    termination: TerminationType
    halfmove_clock: int
    fullmove_number: int
    legal_moves_count: int
    status_text: str
