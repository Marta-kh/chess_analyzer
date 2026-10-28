# Python Chess Analyzer for Android and iOS

A complete, modular, local-first Chess Analyzer application built in Python for **Android**, **iOS**, and **Desktop** using `python-chess`, `Stockfish` (UCI), `Kivy`, and `SQLite`.

## Key Features
1. **Three Unified Session Creation Modes**:
   - **Import a Game**: Fetch public game histories from **Chess.com** (Published Data API) or **Lichess** (REST API) by username, or import PGN directly.
   - **Manual Game Entry**: Play legal moves on the interactive board from the standard starting position with full move history, undo/redo, and PGN export.
   - **Custom Position Editor**: Place/remove/move pieces freely, configure side to move, independent White/Black castling rights (never automatically assumed from piece squares), en-passant square, and move counters, validate position warnings/errors, and play continuations.
2. **Stockfish Multi-Engine & MultiPV Subsystem**:
   - Bundled default engine ready offline (**OFF by default** so background searches never drain battery unprompted).
   - Register and compare up to **5 Stockfish engine versions** concurrently with global CPU-thread and Hash memory budgeting (`ResourceScheduler`).
   - Up to **5 candidate variations (`MultiPV 1..5`) per engine**: clicking **"Add variation"** adds another candidate line from that engine (not another engine), and clicking any variation previews its continuation on the board without overwriting the saved game.
3. **Chess.com-like Move Classification**:
   - **ON by default** for imported games; **OFF by default** for manual and custom-position games until the user explicitly triggers **"Finish game and analyze moves"**.
   - Classifies moves into `Best`, `Great`, `Good`, `Forced`, `Inaccuracy`, `Mistake`, `Blunder`, and `Missed Win` with player accuracy percentages and stale-classification invalidation on history edits.
4. **Offline-First SQLite Persistence**:
   - Automatic schema migrations, separate storage of `original_pgn` vs. edited continuation moves, evaluation caching, and corrupt-cache recovery.

## Quickstart (Desktop & Development Environment)

```bash
# Run the complete unit and integration test suite
PYTHONPATH=. python3 -m unittest discover -s chess_analyzer/tests -v

# Launch the application
PYTHONPATH=. python3 -m chess_analyzer.main
```

See:
- `docs/MOVE_CLASSIFICATION.md` for move classification formulas and thresholds.
- `docs/MOBILE_BUILD_AND_ENGINES.md` for Android (`Buildozer`) and iOS (`kivy-ios`/Xcode) build instructions and Stockfish binary integration details.
- `LICENSES.md` for GPLv3 compliance and third-party attributions.
