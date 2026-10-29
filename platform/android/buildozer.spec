[app]
p4a.branch = v2024.01.21
title = Chess Analyzer
package.name = chessanalyzer
package.domain = org.chessanalyzer.mobile
source.dir = ../..
source.include_exts = py,png,jpg,kv,atlas,sql,so,json,md
source.exclude_dirs = tests,__pycache__,.buildozer,bin,chessanalyzer-ios,build,dist
version = 2.0.0

# Pure-Python + Kivy + PyJNIus requirements for Android
requirements = python3,kivy==2.3.0,chess==1.11.2,requests==2.32.5,urllib3==1.26.20,chardet==5.2.0,idna==3.10,certifi,pyjnius

orientation = portrait
fullscreen = 0

# Request ONLY INTERNET permission (for public Chess.com and Lichess game import)
android.permissions = INTERNET
android.api = 34
android.minapi = 24
android.ndk = 25b
android.sdk_path = /usr/local/lib/android/sdk
android.ndk_path = /usr/local/lib/android/sdk/ndk/25.2.9519653
android.archs = arm64-v8a, x86_64

android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
