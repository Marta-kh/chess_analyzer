"""Opening book and transposition recognizer with ECO codes and opening names.

Supports both move-sequence prefixes and normalized position keys (board + turn + castling)
so transpositions into standard openings are recognized accurately. Once a game permanently
leaves the known book, subsequent moves are never labeled Book.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import chess


@dataclass(frozen=True)
class OpeningInfo:
    eco_code: str
    name: str
    is_book_move: bool
    book_depth_ply: int


STANDARD_OPENING_LINES: List[Tuple[str, str, List[str]]] = [
    ("A00", "Uncommon Opening", []),
    ("B00", "King's Pawn Opening", ["e2e4"]),
    ("C20", "Open Game", ["e2e4", "e7e5"]),
    ("C40", "King's Knight Opening", ["e2e4", "e7e5", "g1f3"]),
    ("C44", "King's Pawn Game", ["e2e4", "e7e5", "g1f3", "b8c6"]),
    ("C50", "Italian Game", ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]),
    ("C53", "Giuoco Piano", ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5"]),
    ("C54", "Giuoco Piano: Main Line", ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "c2c3", "g8f6", "d2d4"]),
    ("C55", "Two Knights Defense", ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"]),
    ("C57", "Two Knights: Fried Liver Attack", ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "f3g5", "d7d5", "e4d5"]),
    ("C60", "Ruy Lopez", ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]),
    ("C65", "Ruy Lopez: Berlin Defense", ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6"]),
    ("C68", "Ruy Lopez: Exchange Variation", ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5c6"]),
    ("C78", "Ruy Lopez: Morphy Defense", ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1"]),
    ("C42", "Petrov's Defense", ["e2e4", "e7e5", "g1f3", "g8f6"]),
    ("C45", "Scotch Game", ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "e5d4", "f3d4"]),
    ("C47", "Four Knights Game", ["e2e4", "e7e5", "g1f3", "b8c6", "b1c3", "g8f6"]),
    ("C25", "Vienna Game", ["e2e4", "e7e5", "b1c3"]),
    ("C30", "King's Gambit", ["e2e4", "e7e5", "f2f4"]),
    ("B20", "Sicilian Defense", ["e2e4", "c7c5"]),
    ("B22", "Sicilian Defense: Alapin Variation", ["e2e4", "c7c5", "c2c3"]),
    ("B23", "Sicilian Defense: Closed", ["e2e4", "c7c5", "b1c3"]),
    ("B27", "Sicilian Defense: Open", ["e2e4", "c7c5", "g1f3"]),
    ("B30", "Sicilian Defense: Old Sicilian", ["e2e4", "c7c5", "g1f3", "b8c6"]),
    ("B33", "Sicilian Defense: Sveshnikov", ["e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "e7e5"]),
    ("B40", "Sicilian Defense: French Variation", ["e2e4", "c7c5", "g1f3", "e7e6"]),
    ("B50", "Sicilian Defense: Modern Variations", ["e2e4", "c7c5", "g1f3", "d7d6"]),
    ("B54", "Sicilian Defense: Open", ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4"]),
    ("B90", "Sicilian Defense: Najdorf", ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6"]),
    ("C00", "French Defense", ["e2e4", "e7e6"]),
    ("C01", "French Defense: Exchange", ["e2e4", "e7e6", "d2d4", "d7d5", "e4d5", "e6d5"]),
    ("C02", "French Defense: Advance", ["e2e4", "e7e6", "d2d4", "d7d5", "e4e5"]),
    ("C03", "French Defense: Tarrasch", ["e2e4", "e7e6", "d2d4", "d7d5", "b1d2"]),
    ("C10", "French Defense: Classical", ["e2e4", "e7e6", "d2d4", "d7d5", "b1c3"]),
    ("B10", "Caro-Kann Defense", ["e2e4", "c7c6"]),
    ("B12", "Caro-Kann Defense: Advance", ["e2e4", "c7c6", "d2d4", "d7d5", "e4e5"]),
    ("B13", "Caro-Kann Defense: Exchange", ["e2e4", "c7c6", "d2d4", "d7d5", "e4d5", "c6d5"]),
    ("B15", "Caro-Kann Defense: Main Line", ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3"]),
    ("B01", "Scandinavian Defense", ["e2e4", "d7d5"]),
    ("B01", "Scandinavian Defense: Main Line", ["e2e4", "d7d5", "e4d5", "d8d5", "b1c3"]),
    ("B07", "Pirc Defense", ["e2e4", "d7d6", "d2d4", "g8f6", "b1c3"]),
    ("B06", "Modern Defense", ["e2e4", "g7g6", "d2d4", "f8g7"]),
    ("B02", "Alekhine's Defense", ["e2e4", "g8f6"]),
    ("A40", "Queen's Pawn Game", ["d2d4"]),
    ("D00", "Queen's Pawn Game", ["d2d4", "d7d5"]),
    ("D02", "London System", ["d2d4", "d7d5", "g1f3", "g8f6", "c1f4"]),
    ("D02", "London System", ["d2d4", "g8f6", "c1f4"]),
    ("D06", "Queen's Gambit", ["d2d4", "d7d5", "c2c4"]),
    ("D10", "Slav Defense", ["d2d4", "d7d5", "c2c4", "c7c6"]),
    ("D20", "Queen's Gambit Accepted", ["d2d4", "d7d5", "c2c4", "d5c4"]),
    ("D30", "Queen's Gambit Declined", ["d2d4", "d7d5", "c2c4", "e7e6"]),
    ("D35", "Queen's Gambit Declined: Exchange", ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c4d5", "e6d5"]),
    ("D37", "Queen's Gambit Declined: Classical", ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "g1f3"]),
    ("A45", "Indian Game", ["d2d4", "g8f6"]),
    ("A46", "Indian Game: Knights Variation", ["d2d4", "g8f6", "g1f3"]),
    ("E00", "Catalan Opening", ["d2d4", "g8f6", "c2c4", "e7e6", "g2g3"]),
    ("E20", "Nimzo-Indian Defense", ["d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4"]),
    ("E60", "King's Indian Defense", ["d2d4", "g8f6", "c2c4", "g7g6"]),
    ("E70", "King's Indian Defense: Normal", ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4", "d7d6"]),
    ("D80", "Grunfeld Defense", ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d5"]),
    ("A57", "Benko Gambit", ["d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "b7b5"]),
    ("A80", "Dutch Defense", ["d2d4", "f7f5"]),
    ("A10", "English Opening", ["c2c4"]),
    ("A20", "English Opening: King's English", ["c2c4", "e7e5"]),
    ("A30", "English Opening: Symmetrical", ["c2c4", "c7c5"]),
    ("A04", "Reti Opening", ["g1f3"]),
    ("A05", "Reti Opening: King's Indian Attack", ["g1f3", "g8f6", "g2g3"]),
    ("A01", "Nimzowitsch-Larsen Attack", ["b2b3"]),
    ("A02", "Bird's Opening", ["f2f4"]),
]


def _position_key(fen: str) -> str:
    parts = fen.strip().split()
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1]} {parts[2]}"
    return fen.strip()


class OpeningRecognizer:
    """Matches games against an opening book by move prefix and position transposition."""

    _POSITION_BOOK: Optional[Dict[str, Tuple[str, str, int]]] = None
    _PREFIX_BOOK: Optional[Dict[Tuple[str, ...], Tuple[str, str]]] = None

    def __init__(self) -> None:
        self._ensure_initialized()

    @classmethod
    def _ensure_initialized(cls) -> None:
        if cls._POSITION_BOOK is not None and cls._PREFIX_BOOK is not None:
            return
        pos_book: Dict[str, Tuple[str, str, int]] = {}
        prefix_book: Dict[Tuple[str, ...], Tuple[str, str]] = {}

        for eco, name, uci_list in STANDARD_OPENING_LINES:
            if not uci_list:
                continue
            board = chess.Board()
            valid = True
            for ply_idx, uci in enumerate(uci_list, start=1):
                try:
                    mv = chess.Move.from_uci(uci)
                    if mv not in board.legal_moves:
                        valid = False
                        break
                    board.push(mv)
                except ValueError:
                    valid = False
                    break
                prefix = tuple(uci_list[:ply_idx])
                if ply_idx == len(uci_list) or prefix not in prefix_book:
                    prefix_book[prefix] = (eco, name)
                pkey = _position_key(board.fen())
                if ply_idx == len(uci_list) or pkey not in pos_book:
                    pos_book[pkey] = (eco, name, ply_idx)
            if not valid:
                continue

        cls._POSITION_BOOK = pos_book
        cls._PREFIX_BOOK = prefix_book

    def analyze_opening_sequence(
        self,
        initial_fen: str,
        uci_moves: List[str],
        fens_after_moves: Optional[List[str]] = None,
    ) -> Tuple[str, str, List[bool]]:
        """Returns `(eco_code, opening_name, is_book_by_move_index)`."""
        if _position_key(initial_fen) != _position_key(chess.STARTING_FEN):
            return ("", "Custom Position", [False] * len(uci_moves))

        assert self._POSITION_BOOK is not None and self._PREFIX_BOOK is not None
        eco_code = "A00"
        opening_name = "Standard Chess"
        is_book_flags: List[bool] = []
        left_book = False

        for idx, uci in enumerate(uci_moves):
            ply = idx + 1
            if left_book or ply > 20:
                is_book_flags.append(False)
                continue

            prefix = tuple(uci_moves[:ply])
            matched = False
            if prefix in self._PREFIX_BOOK:
                eco_code, opening_name = self._PREFIX_BOOK[prefix]
                matched = True
            elif fens_after_moves and idx < len(fens_after_moves):
                pkey = _position_key(fens_after_moves[idx])
                if pkey in self._POSITION_BOOK:
                    eco_code, opening_name, _ = self._POSITION_BOOK[pkey]
                    matched = True

            if matched:
                is_book_flags.append(True)
            else:
                is_book_flags.append(False)
                # Once a player leaves known book lines, stop marking subsequent moves as Book
                left_book = True

        return (eco_code, opening_name, is_book_flags)
