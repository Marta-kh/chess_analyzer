"""Authoritative chessboard manager separating chess legality from UI orientation and preview lines."""
from typing import Dict, List, Optional, Tuple
import chess
from .game_status import GameStatus, TerminationType
from .move_history import MoveHistory, MoveNode


class BoardManager:
    """
    Single authoritative controller for board state, legal moves, orientation,
    and non-destructive candidate variation inspection.
    """

    def __init__(self, initial_fen: str = chess.STARTING_FEN) -> None:
        self._history = MoveHistory(initial_fen=initial_fen)
        self._flipped: bool = False  # False = White at bottom, True = Black at bottom
        self._preview_base_fen: Optional[str] = None
        self._preview_moves: List[MoveNode] = []
        self._preview_cursor: int = 0

    @property
    def history(self) -> MoveHistory:
        return self._history

    @property
    def is_flipped(self) -> bool:
        return self._flipped

    def set_flipped(self, flipped: bool) -> None:
        """Change visual board orientation without mutating the underlying chess position."""
        self._flipped = bool(flipped)

    def flip_board(self) -> bool:
        """Toggle visual board orientation and return new state."""
        self._flipped = not self._flipped
        return self._flipped

    @property
    def is_inspecting_variation(self) -> bool:
        return self._preview_base_fen is not None

    @property
    def preview_moves(self) -> List[MoveNode]:
        return list(self._preview_moves)

    def start_variation_inspection(self, uci_line: List[str], base_fen: Optional[str] = None) -> None:
        """
        Inspect an engine candidate variation (PV line) on the board without overwriting
        or mutating the underlying recorded game.
        """
        start_fen = base_fen or self._history.current_fen
        board = chess.Board(start_fen)
        nodes: List[MoveNode] = []
        for idx, uci_str in enumerate(uci_line):
            try:
                move = chess.Move.from_uci(uci_str)
            except ValueError:
                break
            if move not in board.legal_moves:
                break
            fen_before = board.fen()
            turn_before = "white" if board.turn == chess.WHITE else "black"
            fullmove_num = board.fullmove_number
            san = board.san(move)
            is_cap = board.is_capture(move)
            is_castling = board.is_castling(move)
            is_ep = board.is_en_passant(move)
            promo = chess.piece_symbol(move.promotion) if move.promotion else None
            board.push(move)
            nodes.append(
                MoveNode(
                    ply=idx + 1,
                    uci=move.uci(),
                    san=san,
                    fen_before=fen_before,
                    fen_after=board.fen(),
                    turn_before=turn_before,
                    fullmove_number=fullmove_num,
                    is_capture=is_cap,
                    is_check=board.is_check(),
                    is_checkmate=board.is_checkmate(),
                    is_castling=is_castling,
                    is_en_passant=is_ep,
                    promotion=promo,
                )
            )
        self._preview_base_fen = start_fen
        self._preview_moves = nodes
        self._preview_cursor = len(nodes)

    def step_variation_preview(self, delta: int) -> int:
        if not self.is_inspecting_variation:
            return 0
        self._preview_cursor = max(0, min(len(self._preview_moves), self._preview_cursor + delta))
        return self._preview_cursor

    def exit_variation_inspection(self) -> None:
        """Exit candidate variation preview and return to the recorded game cursor."""
        self._preview_base_fen = None
        self._preview_moves.clear()
        self._preview_cursor = 0

    def get_active_board(self) -> chess.Board:
        """Return the active python-chess Board (either variation preview or recorded game cursor)."""
        if hasattr(self, "_board_override") and getattr(self, "_board_override") is not None:
            return getattr(self, "_board_override").copy()
        if self.is_inspecting_variation and self._preview_base_fen:
            board = chess.Board(self._preview_base_fen)
            for node in self._preview_moves[: self._preview_cursor]:
                board.push(chess.Move.from_uci(node.uci))
            return board
        return self._history.get_board_at_cursor()

    def get_active_fen(self) -> str:
        return self.get_active_board().fen()

    def get_legal_moves_from(self, square_name: str) -> List[str]:
        """Return UCI strings for all legal moves originating from `square_name`."""
        board = self.get_active_board()
        sq = chess.parse_square(square_name.lower())
        return [m.uci() for m in board.legal_moves if m.from_square == sq]

    def get_legal_destinations_from(self, square_name: str) -> List[str]:
        """Return algebraic destination square names for legal moves from `square_name`."""
        board = self.get_active_board()
        sq = chess.parse_square(square_name.lower())
        dests = {chess.square_name(m.to_square) for m in board.legal_moves if m.from_square == sq}
        return sorted(dests)

    def requires_promotion(self, from_square: str, to_square: str) -> bool:
        """Return True if moving from `from_square` to `to_square` is a legal pawn promotion."""
        board = self.get_active_board()
        src = chess.parse_square(from_square.lower())
        dst = chess.parse_square(to_square.lower())
        for mv in board.legal_moves:
            if mv.from_square == src and mv.to_square == dst and mv.promotion is not None:
                return True
        return False

    def play_move_uci(self, uci_str: str, comment: str = "") -> MoveNode:
        """
        Validate and record a move in UCI notation ('e2e4', 'e7e8q').
        Automatically exits variation inspection if active before playing on the recorded board.
        """
        if self.is_inspecting_variation:
            self.exit_variation_inspection()
        try:
            move = chess.Move.from_uci(uci_str.strip().lower())
        except ValueError as exc:
            raise ValueError(f"Malformed UCI move '{uci_str}'") from exc
        return self._history.record_move(move, comment=comment)

    def play_move_squares(
        self,
        from_square: str,
        to_square: str,
        promotion: Optional[str] = None,
        comment: str = "",
    ) -> MoveNode:
        """Play a move given origin/destination square names and optional promotion piece ('q','r','b','n')."""
        if self.is_inspecting_variation:
            self.exit_variation_inspection()
        if self.requires_promotion(from_square, to_square) and not promotion:
            raise ValueError("Promotion piece selection required ('q', 'r', 'b', or 'n').")
        promo_suffix = promotion.lower() if promotion else ""
        uci = f"{from_square.lower()}{to_square.lower()}{promo_suffix}"
        return self.play_move_uci(uci, comment=comment)

    def play_move_san(self, san_str: str, comment: str = "") -> MoveNode:
        """Parse and play a move in Standard Algebraic Notation (SAN)."""
        if self.is_inspecting_variation:
            self.exit_variation_inspection()
        board = self._history.get_board_at_cursor()
        try:
            move = board.parse_san(san_str)
        except ValueError as exc:
            raise ValueError(f"Illegal or invalid SAN move '{san_str}': {exc}") from exc
        return self._history.record_move(move, comment=comment)

    def get_piece_map_algebraic(self) -> Dict[str, str]:
        """Return mapping of square name ('e4') -> piece symbol ('P', 'k', etc.)."""
        board = self.get_active_board()
        return {
            chess.square_name(sq): piece.symbol()
            for sq, piece in board.piece_map().items()
        }

    def get_visual_square_order(self) -> List[str]:
        """
        Return the 64 square names ordered row-by-row from top-left to bottom-right
        according to the current visual orientation (`is_flipped`).
        """
        ranks = range(1, 9) if self._flipped else range(8, 0, -1)
        files = range(7, -1, -1) if self._flipped else range(0, 8)
        squares: List[str] = []
        for r in ranks:
            for f in files:
                squares.append(f"{chess.FILE_NAMES[f]}{r}")
        return squares

    def get_status(self) -> GameStatus:
        """Compute complete authoritative GameStatus for the active position."""
        board = self.get_active_board()
        turn = "white" if board.turn == chess.WHITE else "black"
        is_check = board.is_check()
        is_checkmate = board.is_checkmate()
        is_stalemate = board.is_stalemate()
        is_insufficient = board.is_insufficient_material()
        is_75 = board.is_seventyfive_moves()
        is_5fold = board.is_fivefold_repetition()
        can_50 = board.can_claim_fifty_moves()
        can_3fold = board.can_claim_threefold_repetition()
        legal_count = board.legal_moves.count()

        termination = TerminationType.NONE
        result = "*"
        is_over = False

        if is_checkmate:
            is_over = True
            termination = TerminationType.CHECKMATE
            result = "0-1" if board.turn == chess.WHITE else "1-0"
            winner = "Black" if board.turn == chess.WHITE else "White"
            status_text = f"Checkmate — {winner} wins"
        elif is_stalemate:
            is_over = True
            termination = TerminationType.STALEMATE
            result = "1/2-1/2"
            status_text = "Draw by stalemate"
        elif is_insufficient:
            is_over = True
            termination = TerminationType.INSUFFICIENT_MATERIAL
            result = "1/2-1/2"
            status_text = "Draw by insufficient material"
        elif is_75:
            is_over = True
            termination = TerminationType.SEVENTYFIVE_MOVES
            result = "1/2-1/2"
            status_text = "Draw by 75-move rule"
        elif is_5fold:
            is_over = True
            termination = TerminationType.FIVEFOLD_REPETITION
            result = "1/2-1/2"
            status_text = "Draw by fivefold repetition"
        elif can_50:
            termination = TerminationType.FIFTY_MOVES_CLAIMABLE
            status_text = f"{turn.capitalize()} to move (50-move draw claimable)"
        elif can_3fold:
            termination = TerminationType.THREEFOLD_REPETITION_CLAIMABLE
            status_text = f"{turn.capitalize()} to move (Threefold repetition draw claimable)"
        else:
            check_suffix = " — Check!" if is_check else ""
            status_text = f"{turn.capitalize()} to move{check_suffix}"

        return GameStatus(
            turn=turn,
            is_check=is_check,
            is_checkmate=is_checkmate,
            is_stalemate=is_stalemate,
            is_insufficient_material=is_insufficient,
            is_seventyfive_moves=is_75,
            is_fivefold_repetition=is_5fold,
            can_claim_fifty_moves=can_50,
            can_claim_threefold_repetition=can_3fold,
            is_game_over=is_over,
            result=result,
            termination=termination,
            halfmove_clock=board.halfmove_clock,
            fullmove_number=board.fullmove_number,
            legal_moves_count=legal_count,
            status_text=status_text,
        )
