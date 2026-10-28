[app]
title = Chess Analyzer
package.name = chessanalyzer
package.domain = org.chessanalyzer.mobile
source.dir = ../..
source.include_exts = py,png,jpg,kv,atlas,sql,so,json,md
source.exclude_dirs = tests,__pycache__,.buildozer,bin
version = 2.0.0

# Pure-Python + Kivy + PyJNIus requirements for Android
requirements = python3,kivy==2.3.0,chess==1.11.2,requests==2.32.5,urllib3,certifi,charset-normalizer,idna,pyjnius

orientation = portrait
fullscreen = 0

# Request ONLY INTERNET permission (for public Chess.com and Lichess game import)
android.permissions = INTERNET
android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a

# Bundle native Stockfish 19 ARM64 PIE executable as libstockfish.so in jniLibs so Android 10+ (API 29+)
# extracts it into nativeLibraryDir with SELinux r-x execution permissions:
android.add_libs_arm64_v8a = ../../assets/engines/android_arm64_v8a/libstockfish.so

android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
