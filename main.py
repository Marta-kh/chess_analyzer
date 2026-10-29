#!/usr/bin/env python3
"""Entrypoint for Python Chess Analyzer (Android APK/AAB, iOS Xcode/kivy-ios, and Desktop 430x860 Portrait)."""
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")
_IS_MOBILE = (
    ("ANDROID_ARGUMENT" in os.environ)
    or ("ANDROID_PRIVATE" in os.environ)
    or (os.environ.get("KIVY_BUILD") == "ios")
    or (sys.platform == "ios")
)

try:
    from kivy.config import Config  # type: ignore
    # Prevent Android back-swipe gesture from exiting the app instead of navigating back
    Config.set("kivy", "exit_on_escape", "0")
    if not _IS_MOBILE:
        Config.set("graphics", "width", "430")
        Config.set("graphics", "height", "860")
        Config.set("graphics", "minimum_width", "360")
        Config.set("graphics", "minimum_height", "640")
        Config.set("graphics", "resizable", "1")
except Exception:
    pass

# Ensure `chess_analyzer` package imports work whether launched from `chess_analyzer/main.py` on desktop
# OR flattened into `/data/user/0/.../files/app/main.py` inside a Buildozer Android APK or kivy-ios bundle!
_PKG_DIR = str(Path(__file__).resolve().parent)
_PARENT_DIR = str(Path(__file__).resolve().parent.parent)
for _bad in ("", ".", _PKG_DIR, os.getcwd()):
    try:
        if Path(_bad or ".").resolve() == Path(_PKG_DIR).resolve():
            while _bad in sys.path:
                sys.path.remove(_bad)
    except Exception:
        pass
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

if "chess_analyzer" not in sys.modules:
    _pkg = types.ModuleType("chess_analyzer")
    _pkg.__path__ = [_PKG_DIR]
    _pkg.__file__ = str(Path(_PKG_DIR) / "__init__.py")
    _pkg.__package__ = "chess_analyzer"
    sys.modules["chess_analyzer"] = _pkg

try:
    import chardet  # type: ignore  # noqa: F401
except Exception:
    _chardet_mod = types.ModuleType("chardet")
    _chardet_mod.__version__ = "5.2.0"
    _chardet_mod.detect = lambda data: {"encoding": "utf-8", "confidence": 0.99, "language": ""}  # type: ignore
    sys.modules["chardet"] = _chardet_mod

from chess_analyzer.app import create_app_container
from chess_analyzer.ui import ChessAnalyzerKivyApp


def main() -> int:
    container = create_app_container()
    try:
        app = ChessAnalyzerKivyApp(container=container)
        if hasattr(app, "run"):
            app.run()
        else:
            app.build()
        return 0
    finally:
        container.shutdown()


if __name__ == "__main__":
    sys.exit(main())