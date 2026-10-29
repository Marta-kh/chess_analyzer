"""Main Kivy Application class assembling all 5 screens, app icon, and Android back-gesture navigation."""
from pathlib import Path
from typing import Any
from chess_analyzer.app.dependencies import AppContainer
from chess_analyzer.app.navigation import AppNavigator, ScreenName
from chess_analyzer.ui.kivy_compat import KivyBaseApp, KivyScreenManager, KivyWindow, USING_NATIVE_KIVY
from chess_analyzer.ui.screens import (
    AnalysisWorkspaceScreen,
    CustomPositionEditorScreen,
    GameImportScreen,
    HomeScreen,
    SettingsScreen,
)

APP_ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "icons" / "app_icon.png"


class ChessAnalyzerKivyApp(KivyBaseApp):
    def __init__(self, container: AppContainer, **kwargs) -> None:
        super().__init__(**kwargs)
        self.container = container
        self.screen_manager = KivyScreenManager()
        self.navigator = AppNavigator(on_screen_changed=self._on_navigate)

        self.home_screen = HomeScreen(container, self.navigator)
        self.import_screen = GameImportScreen(container, self.navigator)
        self.custom_editor_screen = CustomPositionEditorScreen(container, self.navigator)
        self.workspace_screen = AnalysisWorkspaceScreen(container, self.navigator)
        self.settings_screen = SettingsScreen(container, self.navigator)

        for scr in (
            self.home_screen,
            self.import_screen,
            self.custom_editor_screen,
            self.workspace_screen,
            self.settings_screen,
        ):
            self.screen_manager.add_widget(scr)

    def _on_navigate(self, screen_name: ScreenName) -> None:
        self.screen_manager.current = screen_name.value

    def handle_back_action(self) -> bool:
        """
        Handles Android edge-swipe back gesture (`key == 27` / `1001`) so swiping from left/right edge
        returns to the previous screen (or closes the open Scorecard) instead of exiting the app.
        """
        if self.navigator.current_screen == ScreenName.WORKSPACE:
            if self.workspace_screen.is_scorecard_open:
                self.workspace_screen.close_scorecard()
                return True
            if self.container.active_session and self.container.active_session.board_manager.is_inspecting_variation:
                self.workspace_screen.exit_variation_preview()
                return True
        if self.navigator.current_screen != ScreenName.HOME:
            self.navigator.go_back()
            return True
        return True

    def _on_keyboard(self, _window: Any, key: int, *_args: Any) -> bool:
        if key in (27, 1001):
            return self.handle_back_action()
        return False

    def build(self):
        if APP_ICON_PATH.exists():
            self.icon = str(APP_ICON_PATH)
        if USING_NATIVE_KIVY and KivyWindow is not None:
            try:
                KivyWindow.bind(on_keyboard=self._on_keyboard)
            except Exception:
                pass
        return self.screen_manager

    def on_pause(self) -> bool:
        self.container.on_app_pause()
        return True

    def on_resume(self) -> None:
        self.container.on_app_resume()

    def on_stop(self) -> None:
        self.container.shutdown()
