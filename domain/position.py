"""Custom position builder and validator with explicit FEN, castling, and en-passant control."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import chess


@dataclass
class ValidationReport:
    """Detailed validation result for a custom chess position."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    status_mask: int = 0


class PositionBuilder:
    """
    Allows constructing arbitrary chess positions without assuming default castling rights
    simply because a king and rook sit on their initial squares.
    """

    def __init__(self, fen: Optional[str] = None) -> None:
        self._board = chess.Board(fen=None)
        self._board.clear()
        self._castling_wk = False
        self._castling_wq = False
        self._castling_bk = False
        self._castling_bq = False
        self._turn = chess.WHITE
        self._ep_square: Optional[int] = None
        self._halfmove_clock = 0
        self._fullmove_number = 1

        if fen:
            self.load_fen(fen)
        else:
            self.reset_to_standard()

    def clear(self) -> None:
        """Clear all pieces and reset castling/ep rights."""
        self._board.clear()
        self._castling_wk = False
        self._castling_wq = False
        self._castling_bk = False
        self._castling_bq = False
        self._turn = chess.WHITE
        self._ep_square = None
        self._halfmove_clock = 0
        self._fullmove_number = 1
        self._sync_board_state()

    def reset_to_standard(self) -> None:
        """Reset to the standard chess starting position."""
        self.load_fen(chess.STARTING_FEN)

    def load_fen(self, fen: str) -> None:
        """Parse and load a FEN string into the builder."""
        parts = fen.strip().split()
        if len(parts) not in (4, 6):
            raise ValueError(f"Invalid FEN format (expected 4 or 6 fields, got {len(parts)}): {fen}")

        temp_board = chess.Board(fen=None)
        try:
            temp_board.set_fen(fen)
        except ValueError as exc:
            raise ValueError(f"Invalid FEN string: {exc}") from exc

        self._board = temp_board.copy(stack=False)
        self._turn = temp_board.turn
        castling_part = parts[2]
        self._castling_wk = "K" in castling_part
        self._castling_wq = "Q" in castling_part
        self._castling_bk = "k" in castling_part
        self._castling_bq = "q" in castling_part

        ep_part = parts[3]
        if ep_part == "-":
            self._ep_square = None
        else:
            try:
                self._ep_square = chess.parse_square(ep_part)
            except ValueError as exc:
                raise ValueError(f"Invalid en-passant square '{ep_part}'") from exc

        self._halfmove_clock = int(parts[4]) if len(parts) >= 5 else 0
        self._fullmove_number = max(1, int(parts[5])) if len(parts) == 6 else 1
        self._sync_board_state()

    def _sync_board_state(self) -> None:
        """Apply explicit turn, castling rights, ep square, and counters to internal board."""
        self._board.turn = self._turn
        castling_fen = ""
        if self._castling_wk:
            castling_fen += "K"
        if self._castling_wq:
            castling_fen += "Q"
        if self._castling_bk:
            castling_fen += "k"
        if self._castling_bq:
            castling_fen += "q"
        self._board.set_castling_fen(castling_fen or "-")
        self._board.ep_square = self._ep_square
        self._board.halfmove_clock = self._halfmove_clock
        self._board.fullmove_number = self._fullmove_number

    def set_piece(self, square_name: str, piece_symbol: Optional[str]) -> None:
        """
        Place a piece (e.g. 'P', 'k', 'Q') or None to remove a piece on a square ('e4').
        Never automatically grants castling rights.
        """
        sq = chess.parse_square(square_name.lower())
        if piece_symbol is None or piece_symbol == "":
            self._board.remove_piece_at(sq)
        else:
            piece = chess.Piece.from_symbol(piece_symbol)
            self._board.set_piece_at(sq, piece)
        self._sync_board_state()

    def remove_piece(self, square_name: str) -> None:
        self.set_piece(square_name, None)

    def move_piece_arbitrary(self, from_square: str, to_square: str) -> None:
        """Move a piece directly on the editor canvas without enforcing move legality."""
        src = chess.parse_square(from_square.lower())
        dst = chess.parse_square(to_square.lower())
        if src == dst:
            return
        piece = self._board.remove_piece_at(src)
        if piece is not None:
            self._board.set_piece_at(dst, piece)
        self._sync_board_state()

    def set_turn(self, color: str) -> None:
        norm = color.strip().lower()
        if norm not in ("white", "black", "w", "b"):
            raise ValueError(f"Invalid side to move: {color}")
        self._turn = chess.WHITE if norm in ("white", "w") else chess.BLACK
        self._sync_board_state()

    def get_turn(self) -> str:
        return "white" if self._turn == chess.WHITE else "black"

    def set_castling_rights(
        self,
        white_kingside: Optional[bool] = None,
        white_queenside: Optional[bool] = None,
        black_kingside: Optional[bool] = None,
        black_queenside: Optional[bool] = None,
    ) -> None:
        if white_kingside is not None:
            self._castling_wk = bool(white_kingside)
        if white_queenside is not None:
            self._castling_wq = bool(white_queenside)
        if black_kingside is not None:
            self._castling_bk = bool(black_kingside)
        if black_queenside is not None:
            self._castling_bq = bool(black_queenside)
        self._sync_board_state()

    def get_castling_rights(self) -> Dict[str, bool]:
        return {
            "K": self._castling_wk,
            "Q": self._castling_wq,
            "k": self._castling_bk,
            "q": self._castling_bq,
        }

    def set_ep_square(self, square_name: Optional[str]) -> None:
        if not square_name or square_name.strip() == "-":
            self._ep_square = None
        else:
            sq = chess.parse_square(square_name.strip().lower())
            rank = chess.square_rank(sq)
            if rank not in (2, 5):
                raise ValueError("En-passant target square must be on rank 3 or rank 6.")
            self._ep_square = sq
        self._sync_board_state()

    def get_ep_square(self) -> Optional[str]:
        return chess.square_name(self._ep_square) if self._ep_square is not None else None

    def set_counters(self, halfmove_clock: int, fullmove_number: int) -> None:
        if halfmove_clock < 0:
            raise ValueError("Halfmove clock must be non-negative.")
        if fullmove_number < 1:
            raise ValueError("Fullmove number must be >= 1.")
        self._halfmove_clock = halfmove_clock
        self._fullmove_number = fullmove_number
        self._sync_board_state()

    def to_fen(self) -> str:
        """Serialize the exact custom position state, preserving requested castling flags if valid."""
        self._sync_board_state()
        board_fen = self._board.board_fen()
        turn_str = "w" if self._turn == chess.WHITE else "b"
        castling_str = ""
        if self._castling_wk:
            castling_str += "K"
        if self._castling_wq:
            castling_str += "Q"
        if self._castling_bk:
            castling_str += "k"
        if self._castling_bq:
            castling_str += "q"
        castling_str = castling_str or "-"
        ep_str = chess.square_name(self._ep_square) if self._ep_square is not None else "-"
        return f"{board_fen} {turn_str} {castling_str} {ep_str} {self._halfmove_clock} {self._fullmove_number}"

    def validate(self) -> ValidationReport:
        """Validate the position and return detailed errors and warnings."""
        self._sync_board_state()
        errors: List[str] = []
        warnings: List[str] = []

        # Check explicit castling consistency before python-chess cleans it
        w_king = self._board.piece_at(chess.E1)
        b_king = self._board.piece_at(chess.E8)
        if self._castling_wk:
            if w_king != chess.Piece(chess.KING, chess.WHITE) or self._board.piece_at(chess.H1) != chess.Piece(chess.ROOK, chess.WHITE):
                warnings.append("White O-O castling right enabled, but White King/Rook not on e1/h1.")
        if self._castling_wq:
            if w_king != chess.Piece(chess.KING, chess.WHITE) or self._board.piece_at(chess.A1) != chess.Piece(chess.ROOK, chess.WHITE):
                warnings.append("White O-O-O castling right enabled, but White King/Rook not on e1/a1.")
        if self._castling_bk:
            if b_king != chess.Piece(chess.KING, chess.BLACK) or self._board.piece_at(chess.H8) != chess.Piece(chess.ROOK, chess.BLACK):
                warnings.append("Black O-O castling right enabled, but Black King/Rook not on e8/h8.")
        if self._castling_bq:
            if b_king != chess.Piece(chess.KING, chess.BLACK) or self._board.piece_at(chess.A8) != chess.Piece(chess.ROOK, chess.BLACK):
                warnings.append("Black O-O-O castling right enabled, but Black King/Rook not on e8/a8.")

        status = self._board.status()
        if status & chess.STATUS_NO_WHITE_KING:
            errors.append("Position is missing a White King.")
        if status & chess.STATUS_NO_BLACK_KING:
            errors.append("Position is missing a Black King.")
        if status & chess.STATUS_TOO_MANY_KINGS:
            errors.append("Position has more than one King for a side.")
        if status & chess.STATUS_PAWNS_ON_BACKRANK:
            errors.append("Pawns cannot be placed on the 1st or 8th rank.")
        if status & chess.STATUS_OPPOSITE_CHECK:
            errors.append("The side not to move is already in check (illegal position).")
        if status & chess.STATUS_TOO_MANY_WHITE_PAWNS:
            warnings.append("White has more than 8 pawns.")
        if status & chess.STATUS_TOO_MANY_BLACK_PAWNS:
            warnings.append("Black has more than 8 pawns.")
        if status & chess.STATUS_TOO_MANY_WHITE_PIECES:
            warnings.append("White has more than 16 total pieces.")
        if status & chess.STATUS_TOO_MANY_BLACK_PIECES:
            warnings.append("Black has more than 16 total pieces.")
        if status & chess.STATUS_INVALID_EP_SQUARE:
            warnings.append("En-passant target square is invalid for the current pawn placement and will be ignored.")

        is_valid = len(errors) == 0
        return ValidationReport(is_valid=is_valid, errors=errors, warnings=warnings, status_mask=int(status))

    def build_board(self) -> chess.Board:
        """Return a validated python-chess Board ready for play/analysis."""
        report = self.validate()
        if not report.is_valid:
            raise ValueError("Cannot start game from invalid position: " + "; ".join(report.errors))
        board = self._board.copy()
        # Clean invalid castling or ep flags if needed so python-chess operates cleanly
        board.set_fen(board.fen())
        return board
