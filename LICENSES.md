# Licensing, Attribution, and Third-Party Notices

## 1. Application License (GPL-3.0-or-later)
Because this application bundles and links with **Stockfish** (which is licensed under the **GNU General Public License v3.0**), the complete distribution of **Python Chess Analyzer for Android and iOS** is licensed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**.

In compliance with Stockfish's GPLv3 redistribution terms:
- Users are free to run, study, share, and modify the software.
- Full source code for both the application and the Stockfish engine integration (`engines/`, `platform/android/`, `platform/ios/`) is included in this repository and must be provided or offered alongside any distributed Android APK/AAB or iOS IPA binary.
- A prominent notice of GPLv3 licensing is displayed in the application's **Settings & About** screen.

## 2. Third-Party Components & Licenses

| Component | Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| **Stockfish Chess Engine** | 19 (sf_19) / UCI | GPL-3.0-only | Local UCI chess analysis engine |
| **python-chess** | 1.11.2 | GPL-3.0-or-later | Authoritative chess move generation, FEN, PGN, and rules |
| **Kivy** | 2.3.0 | MIT License | Cross-platform Python mobile UI framework for Android and iOS |
| **SQLite3** | 3.x | Public Domain | Local-first embedded relational database |
| **Requests / HTTPX** | 2.32.5 / 0.23.3 | Apache-2.0 / BSD-3 | HTTPS clients for Chess.com and Lichess public APIs |

## 3. External API Compliance & Privacy
- **Chess.com Published Data API**: Accessed strictly over HTTPS in read-only mode with a descriptive `User-Agent` header (`PythonChessAnalyzerMobile/1.0`), bounded monthly requests, and rate-limit (`HTTP 429`) handling. No user credentials or passwords are ever requested.
- **Lichess REST API**: Accessed strictly over HTTPS using `/api/games/user/{username}` with bounded `max` parameters and `application/x-ndjson` streaming. No authentication token is required for public game imports.
- **Zero Telemetry Policy**: The application stores all games, custom positions, settings, and evaluations locally in SQLite and never transmits user game histories or telemetry to external servers.
