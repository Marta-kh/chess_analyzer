"""Main Kivy Application class assembling all 5 screens and wiring lifecycle callbacks."""
from chess_analyzer.app.dependencies import AppContainer
from chess_analyzer.app.navigation import AppNavigator, ScreenName
from chess_analyzer.ui.kivy_compat import KivyBaseApp, KivyScreenManager
from chess_analyzer.ui.screens import (
    AnalysisWorkspaceScreen,
    CustomPositionEditorScreen,
    GameImportScreen,
    HomeScreen,
    SettingsScreen,
)


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

    def build(self):
        return self.screen_manager

    def on_pause(self) -> bool:
        self.container.on_app_pause()
        return True

    def on_resume(self) -> None:
        self.container.on_app_resume()

    def on_stop(self) -> None:
        self.container.shutdown()
