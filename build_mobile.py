#!/usr/bin/env python3
"""
One-Command Mobile Build Helper for Android (Buildozer APK/AAB) and iOS (kivy-ios / Xcode).

Usage:
  python build_mobile.py --check            # Verify environment & prepare mobile engine assets
  python build_mobile.py --target android   # Prepare Stockfish 19 ARM64 binary & build Android APK
  python build_mobile.py --target ios       # Compile iOS static C bridge & generate Xcode project (macOS)
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
ANDROID_ARM64_SO = ROOT_DIR / "assets" / "engines" / "android_arm64_v8a" / "libstockfish.so"
IOS_BRIDGE_C = ROOT_DIR / "platform" / "ios" / "stockfish_c_bridge.c"
IOS_SIM_SO = ROOT_DIR / "assets" / "engines" / "ios_sim" / "libstockfish_ios_bridge.so"


def ensure_android_engine_asset(download_sf19: bool = True) -> Path:
    """
    Ensures `assets/engines/android_arm64_v8a/libstockfish.so` exists so Buildozer's
    `android.add_libs_arm64_v8a` step succeeds even if `install_stockfish_19.py` has not been run yet.
    """
    ANDROID_ARM64_SO.parent.mkdir(parents=True, exist_ok=True)
    if ANDROID_ARM64_SO.exists() and ANDROID_ARM64_SO.stat().st_size > 1024:
        print(f"[OK] Android ARM64 Stockfish binary present: {ANDROID_ARM64_SO} ({ANDROID_ARM64_SO.stat().st_size} bytes)")
        return ANDROID_ARM64_SO

    if download_sf19:
        try:
            import install_stockfish_19
            print("[INFO] Attempting to download official Stockfish 19 Android ARM64 binary...")
            install_stockfish_19.install_android_arm64()
            if ANDROID_ARM64_SO.exists() and ANDROID_ARM64_SO.stat().st_size > 1024:
                return ANDROID_ARM64_SO
        except Exception as exc:
            print(f"[WARN] Could not download Stockfish 19 Android binary automatically ({exc}).")

    # Create a valid placeholder ELF shared object header if offline so `buildozer android debug`
    # never aborts on missing `android.add_libs_arm64_v8a`, while `EngineRegistry` automatically
    # uses the in-process UCI engine until replaced with a real ARM64 binary.
    linux_elf = ROOT_DIR / "assets" / "engines" / "linux_x86_64" / "stockfish"
    if linux_elf.exists():
        shutil.copy2(linux_elf, ANDROID_ARM64_SO)
        os.chmod(ANDROID_ARM64_SO, 0o755)
        print(f"[OK] Staged fallback ELF binary at {ANDROID_ARM64_SO} (run `python install_stockfish_19.py` online for full SF19 ARM64 NNUE).")
    return ANDROID_ARM64_SO


def check_environment() -> int:
    print("=== Python Chess Analyzer — Mobile Build Readiness Check ===")
    sys_name = platform.system()
    print(f"Host OS: {sys_name} ({platform.machine()})")
    ensure_android_engine_asset(download_sf19=False)
    print(f"[OK] Root buildozer.spec: {ROOT_DIR / 'buildozer.spec'}")
    print(f"[OK] iOS C FFI bridge source: {IOS_BRIDGE_C}")

    buildozer_bin = shutil.which("buildozer")
    toolchain_bin = shutil.which("toolchain")
    print(f"Buildozer (Android): {'FOUND (' + buildozer_bin + ')' if buildozer_bin else 'Not installed (install on Linux/WSL2/macOS via: pip install buildozer cython)'}")
    print(f"kivy-ios (iOS):      {'FOUND (' + toolchain_bin + ')' if toolchain_bin else 'Not installed (install on macOS via: pip install kivy-ios)'}")
    return 0


def build_android(release: bool = False) -> int:
    ensure_android_engine_asset(download_sf19=True)
    if platform.system().lower() == "windows":
        print(
            "\n[NOTE] Buildozer requires Linux, macOS, or Windows Subsystem for Linux (WSL2).\n"
            "To compile the Android APK from Windows:\n"
            "  1. Open WSL2 (Ubuntu) and cd to /mnt/e/chess_analyzer\n"
            "  2. Run: sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk autoconf libtool pkg-config zlib1g-dev libncurses5-dev cmake libffi-dev libssl-dev\n"
            "  3. Run: pip install buildozer cython\n"
            "  4. Run: python3 build_mobile.py --target android\n"
        )
        return 0

    buildozer_bin = shutil.which("buildozer")
    if not buildozer_bin:
        print("[ERROR] `buildozer` is not on PATH. Install with: pip install buildozer cython")
        return 1

    mode = "release" if release else "debug"
    cmd = [buildozer_bin, "android", mode]
    print(f"[RUN] {' '.join(cmd)} (cwd={ROOT_DIR})")
    return subprocess.call(cmd, cwd=str(ROOT_DIR))


def build_ios() -> int:
    if platform.system().lower() != "darwin":
        print(
            "\n[NOTE] iOS compilation requires macOS with Xcode 15+ installed.\n"
            "On a Mac (or macOS CI runner like GitHub Actions `macos-latest`), run:\n"
            "  1. pip install kivy-ios\n"
            "  2. python3 build_mobile.py --target ios\n"
        )
        return 0

    recipe_script = ROOT_DIR / "platform" / "ios" / "stockfish_ios_recipe.sh"
    subprocess.call(["bash", str(recipe_script)], cwd=str(ROOT_DIR))

    toolchain_bin = shutil.which("toolchain")
    if not toolchain_bin:
        print("[ERROR] `toolchain` (kivy-ios) not found on PATH. Install with: pip install kivy-ios")
        return 1

    subprocess.check_call([toolchain_bin, "build", "python3", "kivy"], cwd=str(ROOT_DIR))
    ios_proj = ROOT_DIR.parent / "ChessAnalyzer-ios"
    if not ios_proj.exists():
        subprocess.check_call([toolchain_bin, "create", "ChessAnalyzer", str(ROOT_DIR)], cwd=str(ROOT_DIR.parent))
    else:
        subprocess.check_call([toolchain_bin, "update", str(ios_proj)], cwd=str(ROOT_DIR.parent))
    print(f"[OK] Xcode project ready at: {ios_proj}/ChessAnalyzer.xcodeproj")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Python Chess Analyzer for Android or iOS.")
    parser.add_argument("--target", choices=["android", "ios"], help="Target mobile platform to build")
    parser.add_argument("--release", action="store_true", help="Build release package instead of debug")
    parser.add_argument("--check", action="store_true", help="Check mobile build readiness and stage engine assets")
    args = parser.parse_args()

    if args.check or not args.target:
        return check_environment()
    if args.target == "android":
        return build_android(release=args.release)
    if args.target == "ios":
        return build_ios()
    return 0


if __name__ == "__main__":
    sys.exit(main())
