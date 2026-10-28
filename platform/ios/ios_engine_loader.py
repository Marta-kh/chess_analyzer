"""
iOS Stockfish In-Process FFI Bridge (`ctypes`).
Loads the compiled C/C++ shared library on POSIX/iOS simulators, and falls back to the
in-process UCI session on Windows hosts where an ELF `.so` cannot be loaded by Win32 `CDLL`.
"""
import ctypes
from pathlib import Path
from typing import List, Optional
from chess_analyzer.engines.bundled_uci_core import BundledUCISession


class IOSStockfishFFIBridge:
    """Bindings to the compiled C/C++ in-process Stockfish UCI bridge."""

    def __init__(self, shared_lib_path: Optional[str] = None) -> None:
        if shared_lib_path is None:
            repo_root = Path(__file__).resolve().parent.parent.parent
            default_so = repo_root / "assets" / "engines" / "ios_sim" / "libstockfish_ios_bridge.so"
            shared_lib_path = str(default_so)

        self._lib_path = shared_lib_path
        self._lib = None
        self._fallback_lines: List[str] = []
        self._fallback_session: Optional[BundledUCISession] = None

        try:
            self._lib = ctypes.CDLL(self._lib_path)
            self._lib.sf_ios_init.argtypes = []
            self._lib.sf_ios_init.restype = None
            self._lib.sf_ios_command.argtypes = [ctypes.c_char_p]
            self._lib.sf_ios_command.restype = ctypes.c_char_p
            self._lib.sf_ios_init()
        except OSError:
            # Windows host fallback when ELF .so is loaded on Win32
            self._fallback_session = BundledUCISession(
                emit_callback=lambda line: self._fallback_lines.append(line),
                engine_name="Stockfish 19-iOS-StaticBridge",
            )

    def send_command(self, uci_command: str) -> str:
        if self._lib is not None:
            raw = self._lib.sf_ios_command(uci_command.encode("utf-8"))
            if not raw:
                return ""
            return raw.decode("utf-8", errors="replace")

        assert self._fallback_session is not None
        self._fallback_lines.clear()
        self._fallback_session.handle_command(uci_command)
        if uci_command.strip().startswith("go"):
            t = self._fallback_session._search_thread
            if t is not None:
                t.join(timeout=3.0)
        return "\n".join(self._fallback_lines) + ("\n" if self._fallback_lines else "")
