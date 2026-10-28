#!/usr/bin/env bash
# Compiles the in-process C UCI bridge (`platform/ios/stockfish_c_bridge.c`) into a universal
# iOS static archive (`libstockfish_ios_bridge.a`) for iphoneos (arm64) and iphonesimulator,
# or compiles a shared library on Linux/macOS host for local simulator testing.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC_C="$SCRIPT_DIR/stockfish_c_bridge.c"
OUT_DIR="$ROOT_DIR/assets/engines/ios_sim"
mkdir -p "$OUT_DIR"

echo "=== Building iOS In-Process Stockfish 19 C FFI Bridge ==="
if [[ "$(uname -s)" == "Darwin" ]] && command -v xcrun >/dev/null 2>&1; then
    IOS_SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
    SIM_SDK="$(xcrun --sdk iphonesimulator --show-sdk-path)"
    xcrun -sdk iphoneos clang -O3 -arch arm64 -isysroot "$IOS_SDK" -c "$SRC_C" -o "$OUT_DIR/stockfish_c_bridge_arm64.o"
    xcrun ar rcs "$OUT_DIR/libstockfish_ios_bridge_device.a" "$OUT_DIR/stockfish_c_bridge_arm64.o"
    xcrun -sdk iphonesimulator clang -O3 -isysroot "$SIM_SDK" -shared -fPIC "$SRC_C" -o "$OUT_DIR/libstockfish_ios_bridge.so"
    rm -f "$OUT_DIR/stockfish_c_bridge_arm64.o"
    echo "[OK] Built iOS arm64 static archive ($OUT_DIR/libstockfish_ios_bridge_device.a) and simulator library."
elif command -v gcc >/dev/null 2>&1; then
    gcc -O3 -shared -fPIC "$SRC_C" -o "$OUT_DIR/libstockfish_ios_bridge.so"
    echo "[OK] Built host simulator shared library: $OUT_DIR/libstockfish_ios_bridge.so"
fi
