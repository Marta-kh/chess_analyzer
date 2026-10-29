#!/usr/bin/env python3
"""Entrypoint for Python Chess Analyzer (Android APK/AAB, iOS Xcode/kivy-ios, and Desktop 430x860 Portrait)."""
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")
_IS_MOBILE = ("ANDROID_ARGUMENT" in os.environ) or ("ANDROID_PRIVATE" in os.environ) or (os.environ.get("KIVY_BUILD") == "ios")

if not _IS_MOBILE:
    try:
        from kivy.config import Config  # type: ignore
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

# Fix directory permissions on Android/iOS (resolves p4a private.tar 0644 traversal bug)
try:
    os.chmod(_PKG_DIR, os.stat(_PKG_DIR).st_mode | 0o755)
except Exception:
    pass
for _root, _dirs, _files in os.walk(_PKG_DIR):
    for _d in _dirs:
        _dp = os.path.join(_root, _d)
        try:
            os.chmod(_dp, os.stat(_dp).st_mode | 0o755)
        except Exception:
            pass

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