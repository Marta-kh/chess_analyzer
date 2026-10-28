#!/usr/bin/env python3
"""
One-command downloader & installer for Official Stockfish 19 (`sf_19`) native binaries:
1. Windows x86-64 native binary (`assets/engines/windows_x86_64/stockfish.exe`)
2. Android ARM64 (`arm64-v8a`) native binary (`assets/engines/android_arm64_v8a/libstockfish.so`)
   ready for `buildozer android debug` APK packaging!

Usage on Windows / macOS / Linux:
    python install_stockfish_19.py
"""
import io
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
import requests

GITHUB_SF19_API = "https://api.github.com/repos/official-stockfish/Stockfish/releases/tags/sf_19"
GITHUB_LATEST_API = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
ROOT_DIR = Path(__file__).resolve().parent
WIN_DIR = ROOT_DIR / "assets" / "engines" / "windows_x86_64"
ANDROID_ARM64_DIR = ROOT_DIR / "assets" / "engines" / "android_arm64_v8a"


def fetch_release_metadata() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "PythonChessAnalyzer-SF19-Installer"}
    resp = requests.get(GITHUB_SF19_API, headers=headers, timeout=15)
    if resp.status_code != 200:
        resp = requests.get(GITHUB_LATEST_API, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def download_and_extract_windows_sf19(assets: list) -> None:
    WIN_DIR.mkdir(parents=True, exist_ok=True)
    # Prefer x86-64-avx2 or x86-64-sse41-popcnt zip for broad modern Windows compatibility
    target_asset = None
    for preferred in ("windows-x86-64-avx2.zip", "windows-x86-64-sse41-popcnt.zip", "windows-x86-64.zip"):
        for a in assets:
            if preferred in a.get("name", "").lower():
                target_asset = a
                break
        if target_asset:
            break

    if not target_asset:
        print("Could not find Windows x86-64 asset in release metadata.")
        return

    url = target_asset["browser_download_url"]
    print(f"Downloading Stockfish 19 for Windows: {target_asset['name']} ...")
    r = requests.get(url, timeout=120)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        for info in zf.infolist():
            if info.filename.lower().endswith(".exe") and "stockfish" in info.filename.lower():
                out_file = WIN_DIR / "stockfish.exe"
                out_file.write_bytes(zf.read(info.filename))
                print(f"Installed native Windows Stockfish 19 binary -> {out_file}")
                return


def download_and_extract_android_sf19(assets: list) -> None:
    ANDROID_ARM64_DIR.mkdir(parents=True, exist_ok=True)
    target_asset = None
    for preferred in ("android-armv8.tar", "android-armv8-dotprod.tar"):
        for a in assets:
            if preferred in a.get("name", "").lower():
                target_asset = a
                break
        if target_asset:
            break

    if not target_asset:
        return

    url = target_asset["browser_download_url"]
    print(f"Downloading Stockfish 19 for Android ARM64: {target_asset['name']} ...")
    r = requests.get(url, timeout=120)
    r.raise_for_status()

    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:*") as tf:
        for member in tf.getmembers():
            if member.isfile() and "stockfish" in Path(member.name).name.lower():
                extracted = tf.extractfile(member)
                if extracted:
                    out_so = ANDROID_ARM64_DIR / "libstockfish.so"
                    out_so.write_bytes(extracted.read())
                    try:
                        os.chmod(out_so, 0o755)
                    except OSError:
                        pass
                    print(f"Installed native Android ARM64 Stockfish 19 binary -> {out_so}")
                    return


def main() -> None:
    print("=== Official Stockfish 19 (sf_19) Native Binary Installer ===")
    data = fetch_release_metadata()
    print(f"Found release: {data.get('name') or data.get('tag_name')}")
    assets = data.get("assets", [])
    download_and_extract_windows_sf19(assets)
    download_and_extract_android_sf19(assets)
    print("Done! Restart `python main.py` to use the native Stockfish 19 binary automatically.")


if __name__ == "__main__":
    main()
