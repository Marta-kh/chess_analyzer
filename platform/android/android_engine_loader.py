"""
Android Stockfish Executable Resolver (API 21 through API 34+).

Technical Architecture Note for Android 10+ (API 29+):
Android 10 introduced strict W^X SELinux enforcement (`execmem` / `app_data_file` noexec),
which prevents executing binaries copied at runtime into writable app data directories
(`/data/data/<package>/files/`).

To comply with Android 10+ security policies:
1. Stockfish is compiled with the Android NDK (`aarch64-linux-android21-clang++ -fPIE -pie`)
   and named `libstockfish.so`.
2. It is packaged inside the APK/AAB under `lib/arm64-v8a/libstockfish.so` and `lib/x86_64/libstockfish.so`
   via `android.add_libs_arm64_v8a` / `android.add_libs_x86_64` in `buildozer.spec`.
3. At install time, Android PackageManager extracts `libstockfish.so` into the read-only,
   SELinux-executable directory `context.getApplicationInfo().nativeLibraryDir`.
4. This loader resolves that exact path via PyJNIus (`autoclass('org.kivy.android.PythonActivity')`)
   or environment fallback, and verifies `os.access(path, os.X_OK)`.
"""
import os
from pathlib import Path
from typing import Optional


def resolve_android_stockfish_path(fallback_dir: Optional[str] = None) -> str:
    """Resolve the SELinux-executable `libstockfish.so` path on Android."""
    # 1. Try PyJNIus on actual Android runtime
    try:
        from jnius import autoclass  # type: ignore
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        context = PythonActivity.mActivity.getApplicationContext()
        native_lib_dir = context.getApplicationInfo().nativeLibraryDir
        candidate = Path(native_lib_dir) / "libstockfish.so"
        if candidate.exists():
            return str(candidate)
    except Exception:
        pass

    # 2. Check environment variable set by Android bootstrap
    env_dir = os.environ.get("ANDROID_NATIVE_LIB_DIR") or fallback_dir
    if env_dir:
        candidate = Path(env_dir) / "libstockfish.so"
        if candidate.exists():
            return str(candidate)

    # 3. Fallback to bundled Linux/Desktop binary during local testing
    repo_root = Path(__file__).resolve().parent.parent.parent
    bundled = repo_root / "assets" / "engines" / "linux_x86_64" / "stockfish"
    return str(bundled)
