"""Data models for Stockfish UCI engines, evaluations, MultiPV variations, and resource budgets."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import chess


class EngineStatus(str, Enum):
    DISABLED = "disabled"
    STARTING = "starting"
    IDLE = "idle"
    ANALYZING = "analyzing"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True)
class EngineScore:
    """
    Normalized evaluation score.
    All stored centipawn and mate values are normalized to WHITE's perspective (`white_cp`, `white_mate`),
    with helper methods to format from either White's perspective or the side-to-move's perspective.
    """
    raw_cp_pov: Optional[int] = None
    raw_mate_pov: Optional[int] = None
    pov_color: str = "white"  # "white" or "black" (side to move when evaluated)

    @property
    def is_mate(self) -> bool:
        return self.raw_mate_pov is not None

    @property
    def white_cp(self) -> Optional[int]:
        if self.raw_cp_pov is None:
            return None
        return self.raw_cp_pov if self.pov_color == "white" else -self.raw_cp_pov

    @property
    def white_mate(self) -> Optional[int]:
        if self.raw_mate_pov is None:
            return None
        if self.raw_mate_pov == 0:
            # Side to move (pov_color) is checkmated on the board
            return -1 if self.pov_color == "white" else 1
        return self.raw_mate_pov if self.pov_color == "white" else -self.raw_mate_pov

    def cp_for_color(self, color: str) -> Optional[int]:
        w_cp = self.white_cp
        if w_cp is None:
            return None
        return w_cp if color.lower().startswith("w") else -w_cp

    def mate_for_color(self, color: str) -> Optional[int]:
        if self.raw_mate_pov is None:
            return None
        is_w = color.lower().startswith("w")
        if self.raw_mate_pov == 0:
            # Side to move (pov_color) is checkmated
            if (is_w and self.pov_color == "white") or (not is_w and self.pov_color == "black"):
                return -1
            return 1
        w_m = self.white_mate
        if w_m is None:
            return None
        return w_m if is_w else -w_m

    def format_display(self, perspective: str = "white") -> str:
        """
        Format score for UI display with explicit sign:
        Positive ALWAYS favors `perspective` (default 'white').
        Mate scores are displayed as 'M+3' or 'M-2' (or '#3' / '#-2').
        """
        if self.is_mate:
            m = self.mate_for_color(perspective)
            if m is None:
                return "0.00"
            if m == 0:
                return "Mate"
            sign = "+" if m > 0 else "-"
            return f"M{sign}{abs(m)}"
        cp = self.cp_for_color(perspective)
        if cp is None:
            return "0.00"
        pawns = cp / 100.0
        sign = "+" if pawns > 0 else ""
        return f"{sign}{pawns:.2f}"


@dataclass
class CandidateVariation:
    """Single candidate variation (MultiPV line) produced by a specific engine."""
    multipv_index: int  # 1..5
    score: EngineScore
    depth: int
    seldepth: int
    pv_uci: List[str]
    pv_san: List[str] = field(default_factory=list)
    nodes: int = 0
    nps: int = 0
    time_ms: int = 0
    is_complete: bool = False

    @property
    def best_move_uci(self) -> Optional[str]:
        return self.pv_uci[0] if self.pv_uci else None

    @property
    def best_move_san(self) -> Optional[str]:
        return self.pv_san[0] if self.pv_san else (self.pv_uci[0] if self.pv_uci else None)


@dataclass
class SearchLimit:
    """Configurable search limits for standard or deep analysis."""
    max_depth: Optional[int] = 14
    movetime_ms: Optional[int] = None
    infinite: bool = False


@dataclass
class EngineConfig:
    """Per-engine configuration (variations count, CPU threads, hash MB, search limits)."""
    visible_variations: int = 1  # 1..5 (Section 7.5: starts with best line or configured count, up to 5)
    threads: int = 1
    hash_mb: int = 16
    search_limit: SearchLimit = field(default_factory=lambda: SearchLimit(max_depth=12))


@dataclass
class EngineDefinition:
    """Metadata and configuration for an installed/registered Stockfish engine."""
    engine_id: str
    display_name: str
    version_build: str
    binary_path: str
    is_bundled: bool = False
    enabled: bool = False  # OFF by default (Section 7.1)
    transport_type: str = "subprocess"  # "subprocess" or "in_process_ios"
    config: EngineConfig = field(default_factory=EngineConfig)
    supported_options: Dict[str, str] = field(default_factory=dict)


@dataclass
class EngineAnalysisResult:
    """Live or completed analysis state for one engine on a specific position."""
    engine_id: str
    engine_name: str
    version_build: str
    fen: str
    search_id: int
    status: EngineStatus
    requested_variations: int
    available_legal_moves: int
    variations: List[CandidateVariation] = field(default_factory=list)
    current_depth: int = 0
    target_depth: Optional[int] = None
    progress_ratio: float = 0.0
    is_calculating_additional_variation: bool = False
    limited_variations_reason: Optional[str] = None
    error_message: Optional[str] = None
