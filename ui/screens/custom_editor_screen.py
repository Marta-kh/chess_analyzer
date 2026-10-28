"""
'Analyze This'-style Custom Position Setup Screen (Section 5.4).
Displays graphical piece icons (`KivyIconButton`) for White and Black pieces instead of text ('wK', 'wQ'),
supports naming/renaming the custom position, and validates castling/ep/FEN rules.
"""
from typing import Dict, Optional
from chess_analyzer.app.dependencies import AppContainer
from chess_analyzer.app.navigation import AppNavigator, ScreenName
from chess_analyzer.domain import GameSession, PositionBuilder, SessionMetadata, ValidationReport
from chess_analyzer.ui.board import InteractiveChessBoardWidget
from chess_analyzer.ui.board.board_widget import get_piece_png_path
from chess_analyzer.ui.kivy_compat import (
    KivyBoxLayout,
    KivyButton,
    KivyIconButton,
    KivyLabel,
    KivyScreen,
    KivyTextInput,
)


class CustomPositionEditorScreen(KivyScreen):
    def __init__(self, container: AppContainer, navigator: AppNavigator, **kwargs) -> None:
        super().__init__(name=ScreenName.CUSTOM_EDITOR.value, **kwargs)
        self.container = container
        self.navigator = navigator
        self.builder = PositionBuilder()
        self.selected_brush_piece: Optional[str] = "P"
        self.is_flipped: bool = False
        self._preview_session = GameSession.create_manual()
        self.piece_buttons: Dict[Optional[str], KivyIconButton] = {}

        # Top Bar with Back, Title input for naming position, and Flip
        self.top_bar = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=40,
            spacing=4,
            bg_color=(0.13, 0.17, 0.22, 1.0),
        )
        self.btn_back = KivyButton(text="< Home", size_hint_x=0.22, on_release=lambda _b: self.navigator.go_back())
        self.position_title_input = KivyTextInput(
            text="Custom Position",
            hint_text="Position Name",
            size_hint_x=0.56,
        )
        self.btn_flip = KivyButton(text="Flip ⇅", size_hint_x=0.22, on_release=lambda _b: self.flip_orientation())
        self.top_bar.add_widget(self.btn_back)
        self.top_bar.add_widget(self.position_title_input)
        self.top_bar.add_widget(self.btn_flip)

        # Interactive 8x8 Editor Board
        self.editor_board = InteractiveChessBoardWidget(
            session_getter=lambda: self._preview_session,
            editor_square_tap_handler=self.tap_square,
        )

        # White Piece Icons Palette Row (uses actual PNG icons from assets/pieces/)
        self.palette_white = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=38, spacing=4)
        for sym in ("K", "Q", "R", "B", "N", "P"):
            icon_btn = KivyIconButton(
                icon_path=get_piece_png_path(sym),
                text=f"w{sym}",
                id=f"brush_w{sym}",
                is_selected=(sym == self.selected_brush_piece),
                on_release=lambda _btn, s=sym: self.select_brush(s),
            )
            self.piece_buttons[sym] = icon_btn
            self.palette_white.add_widget(icon_btn)

        erase_btn = KivyIconButton(
            icon_path=None,
            text="🗑 Erase",
            id="brush_erase",
            is_selected=(self.selected_brush_piece is None),
            on_release=lambda _btn: self.select_brush(None),
        )
        self.piece_buttons[None] = erase_btn
        self.palette_white.add_widget(erase_btn)

        # Black Piece Icons Palette Row (uses actual PNG icons from assets/pieces/)
        self.palette_black = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=38, spacing=4)
        for sym in ("k", "q", "r", "b", "n", "p"):
            icon_btn = KivyIconButton(
                icon_path=get_piece_png_path(sym),
                text=f"b{sym.upper()}",
                id=f"brush_b{sym.upper()}",
                is_selected=(sym == self.selected_brush_piece),
                on_release=lambda _btn, s=sym: self.select_brush(s),
            )
            self.piece_buttons[sym] = icon_btn
            self.palette_black.add_widget(icon_btn)

        # Turn & Castling Rights Controls
        self.rules_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=32, spacing=3)
        self.btn_turn = KivyButton(text="Turn: White", on_release=lambda _b: self.toggle_turn())
        self.btn_castle_wk = KivyButton(text="W O-O", on_release=lambda _b: self.toggle_castling("K"))
        self.btn_castle_wq = KivyButton(text="W O-O-O", on_release=lambda _b: self.toggle_castling("Q"))
        self.btn_castle_bk = KivyButton(text="B O-O", on_release=lambda _b: self.toggle_castling("k"))
        self.btn_castle_bq = KivyButton(text="B O-O-O", on_release=lambda _b: self.toggle_castling("q"))
        for w in (self.btn_turn, self.btn_castle_wk, self.btn_castle_wq, self.btn_castle_bk, self.btn_castle_bq):
            self.rules_row.add_widget(w)

        # Action Row: Clear, Reset Standard, Apply FEN
        self.action_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=32, spacing=4)
        self.btn_clear = KivyButton(text="Clear Board", on_release=lambda _b: self.clear_board())
        self.btn_reset = KivyButton(text="Standard FEN", on_release=lambda _b: self.reset_board())
        self.btn_apply_fen = KivyButton(
            text="Load FEN Text",
            on_release=lambda _b: self.apply_fen_input(self.fen_input.text),
        )
        self.action_row.add_widget(self.btn_clear)
        self.action_row.add_widget(self.btn_reset)
        self.action_row.add_widget(self.btn_apply_fen)

        self.fen_input = KivyTextInput(
            text=self.builder.to_fen(),
            hint_text="Paste or edit FEN string here",
            size_hint_y=None,
            height=32,
        )
        self.validation_label = KivyLabel(text="Position is valid.", size_hint_y=None, height=22)
        self.btn_start_play = KivyButton(
            text="✓ Done — Analyze & Play from Position",
            id="btn_start_custom_session",
            size_hint_y=None,
            height=42,
            bg_color=(0.22, 0.50, 0.32, 1.0),
            on_release=lambda _b: self.start_session_from_editor(),
        )

        self.add_widget(self.top_bar)
        self.add_widget(self.editor_board)
        self.add_widget(self.palette_white)
        self.add_widget(self.palette_black)
        self.add_widget(self.rules_row)
        self.add_widget(self.action_row)
        self.add_widget(self.fen_input)
        self.add_widget(self.validation_label)
        self.add_widget(self.btn_start_play)
        self.refresh_validation()

    def select_brush(self, symbol: Optional[str]) -> None:
        self.selected_brush_piece = symbol
        for sym, btn in self.piece_buttons.items():
            btn.set_selected(sym == symbol)
        self.refresh_validation()

    def toggle_turn(self) -> None:
        new_turn = "black" if self.builder.get_turn() == "white" else "white"
        self.builder.set_turn(new_turn)
        self.btn_turn.text = f"Turn: {new_turn.capitalize()}"
        self.refresh_validation()

    def toggle_castling(self, flag: str) -> None:
        rights = self.builder.get_castling_rights()
        curr = rights.get(flag, False)
        if flag == "K":
            self.builder.set_castling_rights(white_kingside=not curr)
        elif flag == "Q":
            self.builder.set_castling_rights(white_queenside=not curr)
        elif flag == "k":
            self.builder.set_castling_rights(black_kingside=not curr)
        elif flag == "q":
            self.builder.set_castling_rights(black_queenside=not curr)
        self.refresh_validation()

    def clear_board(self) -> None:
        self.builder.clear()
        self.refresh_validation()

    def reset_board(self) -> None:
        self.builder.reset_to_standard()
        self.refresh_validation()

    def flip_orientation(self) -> bool:
        self.is_flipped = not self.is_flipped
        self._preview_session.board_manager.set_flipped(self.is_flipped)
        self.editor_board.refresh_board()
        return self.is_flipped

    def tap_square(self, square_name: str) -> None:
        self.builder.set_piece(square_name, self.selected_brush_piece)
        self.refresh_validation()

    def apply_fen_input(self, fen_str: str) -> ValidationReport:
        self.builder.load_fen(fen_str)
        self.fen_input.text = self.builder.to_fen()
        return self.refresh_validation()

    def refresh_validation(self) -> ValidationReport:
        fen = self.builder.to_fen()
        self.fen_input.text = fen
        self._preview_session.board_manager._history._initial_fen = fen
        try:
            self._preview_session.board_manager._board_override = self.builder._board.copy()
        except Exception:
            pass
        report = self.builder.validate()
        if not report.is_valid:
            self.validation_label.text = "Invalid: " + "; ".join(report.errors)
            self.btn_start_play.disabled = True
        elif report.warnings:
            self.validation_label.text = "Valid (Warning: " + "; ".join(report.warnings) + ")"
            self.btn_start_play.disabled = False
        else:
            self.validation_label.text = "Valid Position — Tap squares to place selected piece icon."
            self.btn_start_play.disabled = False
        self.editor_board.refresh_board()
        return report

    def start_session_from_editor(self) -> GameSession:
        custom_title = self.position_title_input.text.strip() or "Custom Position"
        meta = SessionMetadata(title=custom_title, source="custom")
        session = GameSession.create_from_custom_position(self.builder, metadata=meta)
        self.container.set_active_session(session)
        session.board_manager.set_flipped(self.is_flipped)
        self.container.engine_manager.set_current_fen(session.board_manager.get_active_fen())
        self.navigator.navigate_to(ScreenName.WORKSPACE)
        return session
