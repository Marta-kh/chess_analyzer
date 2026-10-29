"""
'Analyze This'-style Portrait Home Screen with 4 icon-equipped action buttons
(`new_game.png`, `import_game.png`, `custom_game.png`, `settings.png`), saved games list with
uploaded Edit (`edit.png`) and Delete (`delete.png`) icon buttons, and interactive Rename workflow.
"""
from pathlib import Path
from typing import Optional
from chess_analyzer.app.dependencies import AppContainer
from chess_analyzer.app.navigation import AppNavigator, ScreenName
from chess_analyzer.domain import GameSession
from chess_analyzer.ui.kivy_compat import (
    KivyBoxLayout,
    KivyButton,
    KivyIconButton,
    KivyLabel,
    KivyScreen,
    KivyScrollView,
    KivyTextInput,
    USING_NATIVE_KIVY,
)

ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "icons"
NEW_GAME_ICON_PATH = str(ICONS_DIR / "new_game.png")
IMPORT_GAME_ICON_PATH = str(ICONS_DIR / "import_game.png")
CUSTOM_GAME_ICON_PATH = str(ICONS_DIR / "custom_game.png")
SETTINGS_ICON_PATH = str(ICONS_DIR / "settings.png")
EDIT_ICON_PATH = str(ICONS_DIR / "edit.png")
DELETE_ICON_PATH = str(ICONS_DIR / "delete.png")


class HomeScreen(KivyScreen):
    def __init__(self, container: AppContainer, navigator: AppNavigator, **kwargs) -> None:
        super().__init__(name=ScreenName.HOME.value, **kwargs)
        self.container = container
        self.navigator = navigator
        self._editing_session_id: Optional[str] = None

        self.header_box = KivyBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=64,
            padding=6,
            bg_color=(0.13, 0.17, 0.22, 1.0),
        )
        self.title_label = KivyLabel(
            text="ANALYZE THIS • CHESS",
            font_size="18sp",
            bold=True,
        )
        self.subtitle_label = KivyLabel(
            text="Local Stockfish MultiPV Analysis • Chess.com & Lichess • Custom FEN",
            font_size="11sp",
        )
        self.header_box.add_widget(self.title_label)
        self.header_box.add_widget(self.subtitle_label)

        self.btn_manual_game = KivyButton(
            text="New Game / Manual Analysis Board",
            icon_path=NEW_GAME_ICON_PATH,
            id="btn_home_manual",
            size_hint_y=None,
            height=46,
            bg_color=(0.24, 0.50, 0.32, 1.0),
            on_release=lambda _b: self.start_manual_game(),
        )
        self.btn_import_game = KivyButton(
            text="Import Game (Chess.com / Lichess / PGN)",
            icon_path=IMPORT_GAME_ICON_PATH,
            id="btn_home_import",
            size_hint_y=None,
            height=46,
            bg_color=(0.20, 0.38, 0.56, 1.0),
            on_release=lambda _b: self.navigator.navigate_to(ScreenName.IMPORT_GAME),
        )
        self.btn_custom_position = KivyButton(
            text="Setup Position / Custom FEN Editor",
            icon_path=CUSTOM_GAME_ICON_PATH,
            id="btn_home_custom",
            size_hint_y=None,
            height=46,
            bg_color=(0.42, 0.32, 0.52, 1.0),
            on_release=lambda _b: self.navigator.navigate_to(ScreenName.CUSTOM_EDITOR),
        )
        self.btn_settings = KivyButton(
            text="Engines, Board Theme & Settings",
            icon_path=SETTINGS_ICON_PATH,
            id="btn_home_settings",
            size_hint_y=None,
            height=40,
            bg_color=(0.22, 0.26, 0.32, 1.0),
            on_release=lambda _b: self.navigator.navigate_to(ScreenName.SETTINGS),
        )

        # Saved History Header + Interactive Rename Bar (activated when user taps the Edit icon on any game!)
        self.saved_bar = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=36,
            spacing=4,
            bg_color=(0.14, 0.18, 0.24, 1.0),
        )
        self.saved_header = KivyLabel(
            text="SAVED GAMES (Tap Edit Icon to Rename)",
            size_hint_x=0.42,
            bold=True,
            font_size="10sp",
            wrap=True,
        )
        self.rename_input = KivyTextInput(
            text="",
            hint_text="Select a game's Edit button or type new name...",
            size_hint_x=0.40,
        )
        self.btn_save_rename = KivyButton(
            text="Save",
            id="btn_confirm_home_rename",
            size_hint_x=0.18,
            font_size="11sp",
            disabled=True,
            bg_color=(0.22, 0.52, 0.34, 1.0),
            on_release=lambda _b: self.confirm_active_rename(),
        )
        self.saved_bar.add_widget(self.saved_header)
        self.saved_bar.add_widget(self.rename_input)
        self.saved_bar.add_widget(self.btn_save_rename)

        self.scroll = KivyScrollView(do_scroll_x=False, do_scroll_y=True)
        self.saved_sessions_box = KivyBoxLayout(
            orientation="vertical",
            auto_height=True,
            spacing=4,
            size_hint_y=None,
            height=340,
        )
        self.scroll.add_widget(self.saved_sessions_box)

        self.add_widget(self.header_box)
        self.add_widget(self.btn_manual_game)
        self.add_widget(self.btn_import_game)
        self.add_widget(self.btn_custom_position)
        self.add_widget(self.btn_settings)
        self.add_widget(self.saved_bar)
        self.add_widget(self.scroll)

    def on_pre_enter(self) -> None:
        self._editing_session_id = None
        self.btn_save_rename.disabled = True
        self.saved_header.text = "SAVED GAMES (Tap Edit Icon to Rename)"
        self.refresh_saved_list()

    def start_manual_game(self) -> GameSession:
        session = GameSession.create_manual()
        self.container.set_active_session(session)
        self.container.engine_manager.set_current_fen(session.board_manager.get_active_fen())
        self.navigator.navigate_to(ScreenName.WORKSPACE)
        return session

    def refresh_saved_list(self) -> None:
        self.saved_sessions_box.clear_widgets()
        saved = self.container.session_repo.list_sessions()
        if not saved:
            self.saved_sessions_box.add_widget(
                KivyLabel(
                    text="No saved games in history yet.",
                    size_hint_y=None,
                    height=36,
                )
            )
            return

        if not USING_NATIVE_KIVY:
            self.saved_sessions_box.height = max(260, len(saved[:15]) * 42)
        for row in saved[:15]:
            sid = row["session_id"]
            curr_title = row["title"]
            is_editing_this = (self._editing_session_id == sid)
            item_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=38, spacing=4)

            open_btn = KivyButton(
                text=f"{'> ' if is_editing_this else ''}{curr_title} [{row['mode'].upper()}]",
                id=f"open_session_{sid}",
                size_hint_x=0.72,
                wrap_text=True,
                font_size="10.5sp",
                bg_color=(0.22, 0.34, 0.26, 1.0) if is_editing_this else (0.16, 0.21, 0.28, 1.0),
                on_release=lambda _b, s=sid: self.open_saved_session(s),
            )
            rename_btn = KivyIconButton(
                icon_path=EDIT_ICON_PATH,
                text="Edit",
                id=f"rename_session_{sid}",
                is_selected=is_editing_this,
                bg_color=(0.76, 0.84, 0.94, 1.0),
                size_hint_x=0.14,
                on_release=lambda _b, s=sid, t=curr_title: self.on_edit_button_tapped(s, t),
            )
            del_btn = KivyIconButton(
                icon_path=DELETE_ICON_PATH,
                text="Delete",
                id=f"delete_session_{sid}",
                bg_color=(0.92, 0.65, 0.65, 1.0),
                size_hint_x=0.14,
                on_release=lambda _b, s=sid: self.delete_saved_session(s),
            )
            item_row.add_widget(open_btn)
            item_row.add_widget(rename_btn)
            item_row.add_widget(del_btn)
            self.saved_sessions_box.add_widget(item_row)

    def on_edit_button_tapped(self, session_id: str, current_title: str) -> str:
        typed = self.rename_input.text.strip()
        if self._editing_session_id == session_id and typed and typed != current_title:
            return self.rename_saved_session(session_id, typed)
        if self._editing_session_id is None and typed and typed != current_title:
            return self.rename_saved_session(session_id, typed)

        self._editing_session_id = session_id
        self.rename_input.text = current_title
        try:
            self.rename_input.focus = True
        except Exception:
            pass
        self.btn_save_rename.disabled = False
        self.saved_header.text = f"Editing: {current_title[:16]} -> Tap Save"
        self.refresh_saved_list()
        return current_title

    def confirm_active_rename(self) -> str:
        if not self._editing_session_id:
            return ""
        return self.rename_saved_session(self._editing_session_id, self.rename_input.text)

    def open_saved_session(self, session_id: str) -> GameSession:
        session = self.container.session_repo.load_session(session_id)
        self.container.set_active_session(session)
        self.container.engine_manager.set_current_fen(session.board_manager.get_active_fen())
        self.navigator.navigate_to(ScreenName.WORKSPACE)
        return session

    def rename_saved_session(self, session_id: str, new_title: str = "") -> str:
        title = (new_title or self.rename_input.text).strip()
        if not title:
            return ""
        updated = self.container.session_repo.rename_session(session_id, title)
        if self.container.active_session and self.container.active_session.session_id == session_id:
            self.container.active_session.rename(updated)
        self._editing_session_id = None
        self.rename_input.text = ""
        self.btn_save_rename.disabled = True
        self.saved_header.text = f"Renamed to '{updated}'!"
        self.refresh_saved_list()
        return updated

    def delete_saved_session(self, session_id: str) -> None:
        self.container.session_repo.delete_session(session_id)
        self.container.analysis_service.invalidate_report(session_id)
        if self.container.active_session and self.container.active_session.session_id == session_id:
            self.container.active_session = None
        if self._editing_session_id == session_id:
            self._editing_session_id = None
            self.btn_save_rename.disabled = True
        self.refresh_saved_list()
