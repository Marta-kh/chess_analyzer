"""Platform-specific Stockfish integration (Android JNI/nativeLibraryDir & iOS C FFI).
Also proxies Python stdlib `platform` attributes if top-level `import platform` resolves here when
running directly inside the `chess_analyzer/` directory or inside a Buildozer/kivy-ios bundle.
"""
import importlib.util
from pathlib import Path
import sysconfig

_STDLIB_PLATFORM = Path(sysconfig.get_path("stdlib")) / "platform.py"
if _STDLIB_PLATFORM.exists():
    _spec = importlib.util.spec_from_file_location("_stdlib_platform", str(_STDLIB_PLATFORM))
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        for _k, _v in _mod.__dict__.items():
            if not _k.startswith("__") or _k in ("__version__",):
                globals().setdefault(_k, _v)
