"""Registry for bundled and user-registered Stockfish engines (up to 5 engines)."""
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .engine_models import EngineConfig, EngineDefinition, SearchLimit

MAX_REGISTERED_ENGINES = 5
MAX_VARIATIONS_PER_ENGINE = 5


def is_binary_compatible_with_host(path_obj: Path) -> bool:
    """
    Verify that `path_obj` is actually executable on the current host OS.
    Crucial on Windows where `os.access(linux_elf_file, os.X_OK)` returns True
    even though the file is a Linux ELF binary (`\x7fELF`) that raises WinError 193.
    """
    if not path_obj.exists() or not path_obj.is_file():
        return False

    if path_obj.suffix.lower() == ".py":
        return True

    try:
        with path_obj.open("rb") as f:
            magic = f.read(4)
    except OSError:
        return False

    sys_name = platform.system().lower()
    if sys_name == "windows" or os.name == "nt":
        return magic[:2] == b"MZ" or path_obj.suffix.lower() in (".exe", ".bat", ".cmd")

    if sys_name == "linux" or "android" in sys_name or "ANDROID_ARGUMENT" in os.environ:
        if magic == b"\x7fELF" or magic[:2] == b"#!":
            if not os.access(path_obj, os.X_OK):
                try:
                    os.chmod(path_obj, 0o755)
                except OSError:
                    pass
            return os.access(path_obj, os.X_OK)
        return False

    if sys_name == "darwin":
        macho_magics = (
            b"\xfe\xed\xfa\xce",
            b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
        )
        if magic in macho_magics or magic[:2] == b"#!":
            return os.access(path_obj, os.X_OK)
        return False

    return os.access(path_obj, os.X_OK)


class EngineRegistry:
    """
    Manages the bundled default Stockfish engine and up to 4 additional Stockfish versions
    (maximum 5 total engines in the comparison system, Section 7.2).
    """

    def __init__(self, assets_dir: Optional[Path] = None) -> None:
        self._assets_dir = assets_dir or (Path(__file__).resolve().parent.parent / "assets" / "engines")
        self._engines: Dict[str, EngineDefinition] = {}
        self._register_default_bundled_engine()

    def _detect_bundled_binary(self) -> Tuple[str, str]:
        """
        Locate the platform-appropriate Stockfish binary or cross-platform bundled UCI engine.
        Returns `(binary_path, transport_type)`.
        """
        sys_name = platform.system().lower()

        # 1. iOS (Apple Sandbox forbids subprocess spawning -> use in-process C/UCI bridge)
        if sys_name == "ios" or os.environ.get("KIVY_BUILD") == "ios":
            return ("in_process://stockfish_ios_19", "in_process_ios")

        # 2. Android (resolve nativeLibraryDir/libstockfish.so via PyJNIus, or in-process fallback if not bundled)
        if "android" in sys_name or "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ:
            try:
                from chess_analyzer.platform.android.android_engine_loader import resolve_android_stockfish_path
                resolved = Path(resolve_android_stockfish_path())
                if is_binary_compatible_with_host(resolved):
                    return (str(resolved), "subprocess")
            except Exception:
                pass
            return ("in_process://stockfish_android_19", "in_process_ios")

        # 3. Windows (check bundled Windows directory, system PATH, or bundled_uci_core.py)
        if sys_name == "windows" or os.name == "nt":
            win_bundled = self._assets_dir / "windows_x86_64" / "stockfish.exe"
            if is_binary_compatible_with_host(win_bundled):
                return (str(win_bundled), "subprocess")
            which_sf = shutil.which("stockfish") or shutil.which("stockfish.exe")
            if which_sf and is_binary_compatible_with_host(Path(which_sf)):
                return (which_sf, "subprocess")
            py_core = Path(__file__).resolve().parent / "bundled_uci_core.py"
            return (str(py_core), "subprocess")

        # 4. Linux desktop
        if sys_name == "linux":
            bundled_linux = self._assets_dir / "linux_x86_64" / "stockfish"
            if is_binary_compatible_with_host(bundled_linux):
                return (str(bundled_linux), "subprocess")

        # 5. macOS / POSIX system PATH
        which_sf = shutil.which("stockfish")
        if which_sf and is_binary_compatible_with_host(Path(which_sf)):
            return (which_sf, "subprocess")

        # 6. Universal fallback
        py_core = Path(__file__).resolve().parent / "bundled_uci_core.py"
        if py_core.exists():
            return (str(py_core), "subprocess")

        return ("in_process://stockfish_bundled_19", "in_process_ios")

    def _register_default_bundled_engine(self) -> None:
        bin_path, transport = self._detect_bundled_binary()
        default_engine = EngineDefinition(
            engine_id="bundled_stockfish_16_1",
            display_name="Stockfish 19 (Bundled)",
            version_build="19-sf_19",
            binary_path=bin_path,
            is_bundled=True,
            enabled=False,
            transport_type=transport,
            config=EngineConfig(
                visible_variations=1,
                threads=1,
                hash_mb=16,
                search_limit=SearchLimit(max_depth=10),
            ),
        )
        self._engines[default_engine.engine_id] = default_engine

    def list_engines(self) -> List[EngineDefinition]:
        return list(self._engines.values())

    def list_enabled_engines(self) -> List[EngineDefinition]:
        return [e for e in self._engines.values() if e.enabled]

    def get_engine(self, engine_id: str) -> EngineDefinition:
        if engine_id not in self._engines:
            raise KeyError(f"Unknown engine_id: {engine_id}")
        return self._engines[engine_id]

    def register_engine(
        self,
        engine_id: str,
        display_name: str,
        version_build: str,
        binary_path: str,
        transport_type: str = "subprocess",
        enabled: bool = False,
        visible_variations: int = 1,
    ) -> EngineDefinition:
        if engine_id not in self._engines and len(self._engines) >= MAX_REGISTERED_ENGINES:
            raise ValueError(f"Cannot register more than {MAX_REGISTERED_ENGINES} engines in the comparison system.")

        if not (1 <= visible_variations <= MAX_VARIATIONS_PER_ENGINE):
            raise ValueError(f"visible_variations must be between 1 and {MAX_VARIATIONS_PER_ENGINE}.")

        if transport_type == "subprocess":
            path_obj = Path(binary_path)
            if not path_obj.exists() or not path_obj.is_file():
                raise FileNotFoundError(f"Engine binary not found: {binary_path}")
            if path_obj.suffix.lower() != ".py" and not os.access(path_obj, os.X_OK):
                try:
                    os.chmod(path_obj, 0o755)
                except OSError:
                    pass
                if not os.access(path_obj, os.X_OK):
                    raise PermissionError(f"Engine binary is not executable: {binary_path}")
            if not is_binary_compatible_with_host(path_obj):
                py_core = Path(__file__).resolve().parent / "bundled_uci_core.py"
                if py_core.exists():
                    binary_path = str(py_core)
                else:
                    raise PermissionError(f"Binary '{binary_path}' is not compatible with {platform.system()}.")

        eng = EngineDefinition(
            engine_id=engine_id,
            display_name=display_name,
            version_build=version_build,
            binary_path=binary_path,
            is_bundled=False,
            enabled=enabled,
            transport_type=transport_type,
            config=EngineConfig(visible_variations=visible_variations),
        )
        self._engines[engine_id] = eng
        return eng

    def remove_engine(self, engine_id: str) -> None:
        if engine_id not in self._engines:
            raise KeyError(f"Engine '{engine_id}' not found.")
        if self._engines[engine_id].is_bundled:
            raise PermissionError("Cannot remove the bundled default Stockfish engine; disable it instead.")
        del self._engines[engine_id]

    def set_engine_enabled(self, engine_id: str, enabled: bool) -> EngineDefinition:
        eng = self.get_engine(engine_id)
        eng.enabled = bool(enabled)
        return eng

    def set_visible_variations(self, engine_id: str, count: int) -> int:
        if not (1 <= count <= MAX_VARIATIONS_PER_ENGINE):
            raise ValueError(f"Visible variations must be between 1 and {MAX_VARIATIONS_PER_ENGINE}")
        eng = self.get_engine(engine_id)
        eng.config.visible_variations = count
        return count
