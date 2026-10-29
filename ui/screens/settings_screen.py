"""'Analyze This'-style Settings Screen for board theme, orientation, engine budgets, classification defaults, and cache."""
from chess_analyzer.app.dependencies import AppContainer
from chess_analyzer.app.navigation import AppNavigator, ScreenName
from chess_analyzer.engines import ResourceBudget
from chess_analyzer.ui.kivy_compat import (
    KivyBoxLayout,
    KivyButton,
    KivyLabel,
    KivyScreen,
    KivyScrollLabel,
    KivyWidget,
)


class SettingsScreen(KivyScreen):
    def __init__(self, container: AppContainer, navigator: AppNavigator, **kwargs) -> None:
        super().__init__(name=ScreenName.SETTINGS.value, **kwargs)
        self.container = container
        self.navigator = navigator

        self.top_bar = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=42,
            bg_color=(0.13, 0.17, 0.22, 1.0),
        )
        self.btn_back = KivyButton(text="< Back", size_hint_x=0.25, on_release=lambda _b: self.navigator.go_back())
        self.title_lbl = KivyLabel(text="Settings & Engine Setup", bold=True, size_hint_x=0.75)
        self.top_bar.add_widget(self.btn_back)
        self.top_bar.add_widget(self.title_lbl)

        # Horizontally scrollable summary line so long status text is never clipped off-screen
        self.summary_label = KivyScrollLabel(
            text="",
            direction="horizontal",
            font_size="12sp",
            size_hint_y=None,
            height=40,
            bg_color=(0.14, 0.18, 0.24, 1.0),
        )

        # Board Theme Selector Row
        self.theme_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=40, spacing=4)
        for th_key, th_label in (
            ("analyze_this_green", "Theme: Analyze Green"),
            ("classic_wood", "Theme: Wood"),
            ("tournament_blue", "Theme: Blue"),
        ):
            b = KivyButton(
                text=th_label,
                font_size="10.5sp",
                wrap_text=True,
                on_release=lambda _btn, tk=th_key: self.update_setting("board_theme", tk),
            )
            self.theme_row.add_widget(b)

        # Orientation & Classification Default Row
        self.orient_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=40, spacing=4)
        self.btn_orient_w = KivyButton(
            text="Default: White Bottom",
            on_release=lambda _b: self.update_setting("default_board_orientation", "white"),
        )
        self.btn_orient_b = KivyButton(
            text="Default: Black Bottom",
            on_release=lambda _b: self.update_setting("default_board_orientation", "black"),
        )
        self.orient_row.add_widget(self.btn_orient_w)
        self.orient_row.add_widget(self.btn_orient_b)

        # Engine Resource Budget Row
        self.budget_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=40, spacing=4)
        self.btn_threads_2 = KivyButton(
            text="CPU Budget: 2 Threads",
            on_release=lambda _b: self.update_setting("cpu_thread_budget", 2),
        )
        self.btn_threads_4 = KivyButton(
            text="CPU Budget: 4 Threads",
            on_release=lambda _b: self.update_setting("cpu_thread_budget", 4),
        )
        self.budget_row.add_widget(self.btn_threads_2)
        self.budget_row.add_widget(self.btn_threads_4)

        self.btn_clear_cache = KivyButton(
            text="Clear SQLite Evaluation Cache",
            id="btn_clear_cache",
            size_hint_y=None,
            height=42,
            bg_color=(0.48, 0.24, 0.24, 1.0),
            on_release=lambda _b: self.clear_analysis_cache(),
        )

        # Horizontally scrollable about line
        self.about_label = KivyScrollLabel(
            text="Python Chess Analyzer v2.0.0 • Stockfish 19 (sf_19) UCI (GPLv3) • Local-First SQLite",
            direction="horizontal",
            font_size="11.5sp",
            size_hint_y=None,
            height=34,
        )
        # Flexible bottom spacer so settings controls anchor cleanly at the top of the screen
        self.bottom_spacer = KivyWidget(size_hint_y=1.0)

        self.add_widget(self.top_bar)
        self.add_widget(self.summary_label)
        self.add_widget(self.theme_row)
        self.add_widget(self.orient_row)
        self.add_widget(self.budget_row)
        self.add_widget(self.btn_clear_cache)
        self.add_widget(self.about_label)
        self.add_widget(self.bottom_spacer)
        self.refresh()

    def on_pre_enter(self) -> None:
        self.refresh()

    def update_setting(self, key: str, value) -> None:
        self.container.prefs_repo.set(key, value)
        if key in ("cpu_thread_budget", "memory_hash_limit_mb"):
            prefs = self.container.prefs_repo.get_all()
            self.container.resource_scheduler.update_budget(
                ResourceBudget(
                    max_total_threads=int(prefs["cpu_thread_budget"]),
                    max_total_hash_mb=int(prefs["memory_hash_limit_mb"]),
                )
            )
        if key == "imported_classification_default":
            self.container.analysis_service.set_global_imported_classification_default(
                bool(value),
                active_session=self.container.active_session,
            )
        self.refresh()

    def clear_analysis_cache(self) -> None:
        self.container.cache_repo.clear_cache()
        self.refresh()

    def refresh(self) -> None:
        prefs = self.container.prefs_repo.get_all()
        engines = self.container.engine_registry.list_engines()
        theme = prefs.get("board_theme", "analyze_this_green")
        self.summary_label.text = (
            f"Theme: {theme} | Orientation: {prefs['default_board_orientation']} | "
            f"Threads: {prefs['cpu_thread_budget']} | Hash: {prefs['memory_hash_limit_mb']}MB | "
            f"Engines: {len(engines)}/5"
        )
