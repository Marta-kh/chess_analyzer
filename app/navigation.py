"""Screen navigation controller for the mobile UI."""
from enum import Enum
from typing import Callable, List, Optional


class ScreenName(str, Enum):
    HOME = "home"
    IMPORT_GAME = "import_game"
    CUSTOM_EDITOR = "custom_editor"
    WORKSPACE = "workspace"
    SETTINGS = "settings"


class AppNavigator:
    """Manages navigation history stack and screen transition callbacks."""

    def __init__(self, on_screen_changed: Optional[Callable[[ScreenName], None]] = None) -> None:
        self._stack: List[ScreenName] = [ScreenName.HOME]
        self._on_screen_changed = on_screen_changed

    @property
    def current_screen(self) -> ScreenName:
        return self._stack[-1]

    def navigate_to(self, screen: ScreenName) -> None:
        if self._stack[-1] != screen:
            self._stack.append(screen)
        if self._on_screen_changed:
            self._on_screen_changed(screen)

    def go_back(self) -> ScreenName:
        if len(self._stack) > 1:
            self._stack.pop()
        current = self._stack[-1]
        if self._on_screen_changed:
            self._on_screen_changed(current)
        return current
