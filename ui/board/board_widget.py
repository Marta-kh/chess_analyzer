"""
'Analyze This'-style graphical 8x8 chessboard widget:
- Renders colored light/dark squares (`#EEEED2` cream / `#769656` tournament green, plus Wood & Blue themes)
- Renders crisp PNG Staunton chess piece sprites from `assets/pieces/`
- Highlights selected square, last played move squares, legal destination dots, and capture rings
- Displays top/bottom player bars and a pawn promotion piece selector bar
"""
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
import chess
from chess_analyzer.domain import GameSession
from chess_analyzer.ui.kivy_compat import (
    KivyBoxLayout,
    KivyButton,
    KivyGridLayout,
    KivyLabel,
    KivySquareCell,
)

BOARD_THEMES: Dict[str, Tuple[Tuple[float, float, float, float], Tuple[float, float, float, float]]] = {
    "analyze_this_green": ((0.933, 0.933, 0.824, 1.0), (0.463, 0.588, 0.337, 1.0)),  # #EEEED2 / #769656
    "classic_wood": ((0.941, 0.851, 0.710, 1.0), (0.710, 0.533, 0.388, 1.0)),        # #F0D9B5 / #B58863
    "tournament_blue": ((0.918, 0.914, 0.824, 1.0), (0.294, 0.451, 0.600, 1.0)),     # #EAE9D2 / #4B7399
}

HIGHLIGHT_SELECTED = (0.965, 0.965, 0.412, 1.0)   # #F6F669
HIGHLIGHT_LAST_MOVE = (0.729, 0.792, 0.267, 1.0)  # #BACA44
HIGHLIGHT_CHECK = (0.910, 0.255, 0.255, 1.0)      # Red king-in-check highlight

PIECES_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "pieces"


def get_piece_png_path(piece_symbol: str) -> Optional[str]:
    if not piece_symbol:
        return None
    prefix = "w" if piece_symbol.isupper() else "b"
    path = PIECES_DIR / f"{prefix}{piece_symbol.lower()}.png"
    if path.exists():
        return str(path)
    alt = PIECES_DIR / f"{prefix}{piece_symbol.upper()}.png"
    return str(alt) if alt.exists() else None


class InteractiveChessBoardWidget(KivyBoxLayout):
    """
    Shared interactive 8x8 chessboard widget modeled after 'Analyze This'.
    Uses a fixed mobile portrait height (`396dp`) so the 8x8 board is always square and prominent.
    """

    def __init__(
        self,
        session_getter: Callable[[], Optional[GameSession]],
        on_move_played: Optional[Callable[[str], None]] = None,
        editor_square_tap_handler: Optional[Callable[[str], None]] = None,
        board_theme: str = "analyze_this_green",
        **kwargs,
    ) -> None:
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", 436)
        super().__init__(orientation="vertical", spacing=2, padding=2, **kwargs)
        self._get_session = session_getter
        self._on_move_played = on_move_played
        self._editor_tap_handler = editor_square_tap_handler
        self.board_theme = board_theme

        self.selected_square: Optional[str] = None
        self.highlighted_destinations: List[str] = []
        self.pending_promotion_move: Optional[tuple[str, str]] = None

        self.status_banner = KivyLabel(
            text="Ready",
            size_hint_y=None,
            height=24,
            bold=True,
            bg_color=(0.14, 0.18, 0.23, 1.0),
        )
        self.grid = KivyGridLayout(
            cols=8,
            rows=8,
            size_hint_y=None,
            height=384,
            spacing=1,
            bg_color=(0.10, 0.12, 0.15, 1.0),
        )
        self.square_buttons: Dict[str, KivySquareCell] = {}
        self.promotion_bar = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=26,
            spacing=4,
        )

        self.add_widget(self.status_banner)
        self.add_widget(self.grid)
        self.add_widget(self.promotion_bar)
        self.refresh_board()

    def refresh_board(self) -> None:
        session = self._get_session()
        self.grid.clear_widgets()
        self.square_buttons.clear()
        self.promotion_bar.clear_widgets()

        if session is None:
            self.status_banner.text = "No active chess session"
            return

        bm = session.board_manager
        status = bm.get_status()
        preview_tag = " [VARIATION PREVIEW]" if bm.is_inspecting_variation else ""
        self.status_banner.text = f"{status.status_text}{preview_tag}"

        piece_map = bm.get_piece_map_algebraic()
        square_order = bm.get_visual_square_order()
        light_rgba, dark_rgba = BOARD_THEMES.get(self.board_theme, BOARD_THEMES["analyze_this_green"])

        # Identify last played move squares for highlight
        last_squares = set()
        curr_node = bm.history.current_node
        if curr_node and len(curr_node.uci) >= 4:
            last_squares.add(curr_node.uci[:2])
            last_squares.add(curr_node.uci[2:4])

        for idx, sq_name in enumerate(square_order):
            sq_int = chess.parse_square(sq_name)
            file_idx = chess.square_file(sq_int)
            rank_idx = chess.square_rank(sq_int)
            is_light = (file_idx + rank_idx) % 2 == 1

            piece_sym = piece_map.get(sq_name, "")
            png_path = get_piece_png_path(piece_sym)

            # Determine square background color
            if sq_name == self.selected_square:
                bg_rgba = HIGHLIGHT_SELECTED
            elif status.is_check and (
                (status.turn == "white" and piece_sym == "K")
                or (status.turn == "black" and piece_sym == "k")
            ):
                bg_rgba = HIGHLIGHT_CHECK
            elif sq_name in last_squares:
                bg_rgba = HIGHLIGHT_LAST_MOVE
            else:
                bg_rgba = light_rgba if is_light else dark_rgba

            marker_type = ""
            if sq_name == self.selected_square:
                marker_type = "selected"
            elif sq_name in self.highlighted_destinations:
                marker_type = "capture" if piece_sym else "dot"

            # Coordinate labels on left file and bottom rank
            coord_txt = ""
            if idx % 8 == 0:
                coord_txt = sq_name[1]  # Rank number 1..8
            elif idx >= 56:
                coord_txt = sq_name[0]  # File letter a..h
            coord_col = dark_rgba if is_light else light_rgba

            cell = KivySquareCell(
                square_name=sq_name,
                bg_rgba=bg_rgba,
                piece_png_path=png_path,
                coord_text=coord_txt,
                coord_color=coord_col,
                marker_type=marker_type,
                on_release=lambda _b, s=sq_name: self.on_square_tapped(s),
            )
            self.square_buttons[sq_name] = cell
            self.grid.add_widget(cell)

        if self.pending_promotion_move is not None:
            src, dst = self.pending_promotion_move
            self.promotion_bar.add_widget(KivyLabel(text=f"Promote {src}->{dst}:", size_hint_x=0.35))
            for promo_code, promo_label in (("q", "Queen"), ("r", "Rook"), ("b", "Bishop"), ("n", "Knight")):
                p_btn = KivyButton(
                    text=promo_label,
                    id=f"promo_{promo_code}",
                    bg_color=(0.24, 0.52, 0.34, 1.0),
                    on_release=lambda _b, pc=promo_code: self.confirm_promotion(pc),
                )
                self.promotion_bar.add_widget(p_btn)

    def on_square_tapped(self, square_name: str) -> None:
        if self._editor_tap_handler is not None:
            self._editor_tap_handler(square_name)
            return

        session = self._get_session()
        if session is None:
            return
        bm = session.board_manager

        if self.selected_square is not None and square_name in self.highlighted_destinations:
            src = self.selected_square
            dst = square_name
            if bm.requires_promotion(src, dst):
                self.pending_promotion_move = (src, dst)
                self.refresh_board()
                return
            self._execute_move(src, dst, promotion=None)
            return

        legal_dests = bm.get_legal_destinations_from(square_name)
        if legal_dests:
            self.selected_square = square_name
            self.highlighted_destinations = legal_dests
            self.pending_promotion_move = None
        else:
            self.selected_square = None
            self.highlighted_destinations = []
            self.pending_promotion_move = None
        self.refresh_board()

    def confirm_promotion(self, promotion_piece: str) -> None:
        if self.pending_promotion_move is None:
            return
        src, dst = self.pending_promotion_move
        self.pending_promotion_move = None
        self._execute_move(src, dst, promotion=promotion_piece)

    def _execute_move(self, from_sq: str, to_sq: str, promotion: Optional[str]) -> None:
        session = self._get_session()
        if session is None:
            return
        node = session.play_move_squares(from_sq, to_sq, promotion=promotion)
        self.selected_square = None
        self.highlighted_destinations = []
        self.refresh_board()
        if self._on_move_played:
            self._on_move_played(node.uci)
