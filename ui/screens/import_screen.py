"""
Game Import Screen for Chess.com, Lichess, and Direct PGN Paste (Section 5.2).
Fixes platform switching, fetches newest player archives automatically on Chess.com,
and displays results in a scrollable vertical list.
"""
from datetime import datetime, timezone
from typing import List
from chess_analyzer.app.dependencies import AppContainer
from chess_analyzer.app.navigation import AppNavigator, ScreenName
from chess_analyzer.domain import GameSession
from chess_analyzer.integrations import ExternalGameSummary, IntegrationError
from chess_analyzer.ui.kivy_compat import (
    KivyBoxLayout,
    KivyButton,
    KivyLabel,
    KivyScreen,
    KivyScrollView,
    KivyTextInput,
)


class GameImportScreen(KivyScreen):
    def __init__(self, container: AppContainer, navigator: AppNavigator, **kwargs) -> None:
        super().__init__(name=ScreenName.IMPORT_GAME.value, **kwargs)
        self.container = container
        self.navigator = navigator

        self.selected_platform: str = "chesscom"  # "chesscom" or "lichess"
        self.year: int = datetime.now(timezone.utc).year
        self.month: int = datetime.now(timezone.utc).month
        self.page: int = 1
        self.state: str = "idle"
        self.error_message: str = ""
        self.games: List[ExternalGameSummary] = []

        # Top Bar
        self.top_bar = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=42,
            bg_color=(0.13, 0.17, 0.22, 1.0),
        )
        self.btn_back = KivyButton(
            text="< Home",
            size_hint_x=0.25,
            on_release=lambda _b: self.navigator.go_back(),
        )
        self.header_lbl = KivyLabel(text="Import Public Game", bold=True, size_hint_x=0.75)
        self.top_bar.add_widget(self.btn_back)
        self.top_bar.add_widget(self.header_lbl)

        # Platform Selector Row (Chess.com vs Lichess)
        self.platform_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=40, spacing=6)
        self.btn_plat_chesscom = KivyButton(
            text="✓ Chess.com",
            id="btn_plat_chesscom",
            bg_color=(0.24, 0.52, 0.34, 1.0),
            on_release=lambda _b: self.set_platform("chesscom"),
        )
        self.btn_plat_lichess = KivyButton(
            text="Lichess.org",
            id="btn_plat_lichess",
            bg_color=(0.20, 0.24, 0.30, 1.0),
            on_release=lambda _b: self.set_platform("lichess"),
        )
        self.platform_row.add_widget(self.btn_plat_chesscom)
        self.platform_row.add_widget(self.btn_plat_lichess)

        # Username Input + Fetch Row
        self.input_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=42, spacing=4)
        self.username_input = KivyTextInput(
            text="",
            hint_text="Enter Chess.com or Lichess username",
            size_hint_x=0.65,
        )
        self.btn_fetch = KivyButton(
            text="Fetch Games",
            id="btn_fetch_games",
            size_hint_x=0.35,
            bg_color=(0.20, 0.42, 0.62, 1.0),
            on_release=lambda _b: self.fetch_games(),
        )
        self.input_row.add_widget(self.username_input)
        self.input_row.add_widget(self.btn_fetch)

        # Quick Preset Usernames Row
        self.preset_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=30, spacing=4)
        self.preset_row.add_widget(KivyLabel(text="Try:", size_hint_x=0.16))
        for p_plat, p_user in (("chesscom", "hikaru"), ("chesscom", "MagnusCarlsen"), ("lichess", "DrNykterstein")):
            b_pre = KivyButton(
                text=f"{p_user} ({p_plat})",
                font_size="11sp",
                bg_color=(0.18, 0.22, 0.28, 1.0),
                on_release=lambda _b, pl=p_plat, u=p_user: self._use_preset(pl, u),
            )
            self.preset_row.add_widget(b_pre)

        # Status & Retry Row
        self.status_label = KivyLabel(
            text="Select Chess.com or Lichess, enter a username, and tap 'Fetch Games'.",
            size_hint_y=None,
            height=28,
        )
        self.btn_retry = KivyButton(
            text="Retry Fetch",
            id="btn_retry_import",
            size_hint_y=None,
            height=34,
            bg_color=(0.55, 0.25, 0.25, 1.0),
            on_release=lambda _b: self.fetch_games(),
        )

        # Scrollable Game Results List
        self.scroll = KivyScrollView()
        self.results_box = KivyBoxLayout(orientation="vertical", spacing=4, size_hint_y=None, height=420)
        self.scroll.add_widget(self.results_box)

        # Direct PGN Paste Row (like Analyze This 'Paste PGN')
        self.pgn_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=40, spacing=4)
        self.pgn_input = KivyTextInput(
            text="",
            hint_text="Or paste raw PGN moves here (e.g. 1. e4 e5 2. Nf3 Nc6)...",
            size_hint_x=0.70,
        )
        self.btn_import_pgn = KivyButton(
            text="Load PGN",
            id="btn_load_pgn",
            size_hint_x=0.30,
            bg_color=(0.38, 0.30, 0.50, 1.0),
            on_release=lambda _b: self.import_raw_pgn(),
        )
        self.pgn_row.add_widget(self.pgn_input)
        self.pgn_row.add_widget(self.btn_import_pgn)

        self.btn_next_page = KivyButton(
            text="Next Page >",
            id="btn_next_page",
            size_hint_y=None,
            height=36,
            on_release=lambda _b: self.next_page(),
        )

        self.add_widget(self.top_bar)
        self.add_widget(self.platform_row)
        self.add_widget(self.input_row)
        self.add_widget(self.preset_row)
        self.add_widget(self.status_label)
        self.add_widget(self.scroll)
        self.add_widget(self.pgn_row)
        self.add_widget(self.btn_next_page)

    def _use_preset(self, platform_name: str, username: str) -> None:
        self.set_platform(platform_name)
        self.username_input.text = username
        self.fetch_games()

    def set_platform(self, platform_name: str) -> None:
        if platform_name not in ("chesscom", "lichess"):
            raise ValueError("Platform must be 'chesscom' or 'lichess'.")
        self.selected_platform = platform_name
        self.page = 1
        if platform_name == "chesscom":
            self.btn_plat_chesscom.text = "✓ Chess.com"
            self.btn_plat_lichess.text = "Lichess.org"
        else:
            self.btn_plat_chesscom.text = "Chess.com"
            self.btn_plat_lichess.text = "✓ Lichess.org"

    def import_raw_pgn(self) -> GameSession:
        raw = self.pgn_input.text.strip()
        session = self.container.pgn_importer.import_to_session(
            pgn_text=raw,
            source="pgn",
            global_imported_classification_default=self.container.analysis_service.global_imported_classification_default,
        )
        self.container.set_active_session(session)
        self.navigator.navigate_to(ScreenName.WORKSPACE)
        return session

    def fetch_games(self) -> List[ExternalGameSummary]:
        if self.container.is_offline:
            self.state = "offline"
            self.error_message = "Offline mode: External game import requires internet access."
            self.status_label.text = self.error_message
            return []

        username = self.username_input.text.strip()
        self.state = "loading"
        self.status_label.text = f"Fetching public games for '{username}' on {self.selected_platform}..."
        self.results_box.clear_widgets()

        try:
            if self.selected_platform == "chesscom":
                self.games = self.container.chesscom_client.fetch_recent_games(
                    username=username,
                    page=self.page,
                    page_size=20,
                )
            else:
                self.games = self.container.lichess_client.fetch_user_games(
                    username=username,
                    max_games=20,
                )

            if not self.games:
                self.state = "empty"
                self.status_label.text = f"No public games found for '{username}'."
            else:
                self.state = "loaded"
                self.status_label.text = f"Loaded {len(self.games)} game(s) from {self.selected_platform}. Tap a game to analyze:"
                self.results_box.height = max(360, len(self.games) * 46)
                for idx, g in enumerate(self.games):
                    w_elo = f" ({g.white_rating})" if g.white_rating else ""
                    b_elo = f" ({g.black_rating})" if g.black_rating else ""
                    btn = KivyButton(
                        text=f"{g.played_at_iso} | {g.white_username}{w_elo} vs {g.black_username}{b_elo} [{g.result}] ({g.time_class})",
                        id=f"import_game_{idx}",
                        size_hint_y=None,
                        height=42,
                        bg_color=(0.16, 0.22, 0.29, 1.0),
                        on_release=lambda _b, summary=g: self.select_game(summary),
                    )
                    self.results_box.add_widget(btn)
        except (ValueError, IntegrationError) as exc:
            self.state = "error"
            self.error_message = str(exc)
            self.status_label.text = f"Error: {self.error_message}"
            self.results_box.add_widget(self.btn_retry)
        return self.games

    def next_page(self) -> None:
        self.page += 1
        self.fetch_games()

    def select_game(self, summary: ExternalGameSummary) -> GameSession:
        imp_default = self.container.analysis_service.global_imported_classification_default
        if summary.source == "chesscom":
            session = self.container.chesscom_client.import_selected_game(summary, imp_default)
        else:
            session = self.container.lichess_client.import_selected_game(summary, imp_default)
        self.container.set_active_session(session)
        self.navigator.navigate_to(ScreenName.WORKSPACE)
        return session
