# Chess.com-Inspired Game Review V2, Per-Move Variation Tree & Mobile Compilation Guide

## 1. Root-Cause Diagnosis & Fixes Applied

| Issue / Requirement | Root Cause Identified | Fix Implemented |
|---|---|---|
| **Evaluation Graph text overlap (`ui/widgets/game_review_card.py`)** | `EvaluationGraphWidget` previously drew the green evaluation curve in `self.canvas.after` over the same bounding box occupied by `self.graph_summary_label`. | Split `EvaluationGraphWidget` into two stacked containers: a top `self.graph_canvas_box` (`height=30`, pure graph canvas with zero text inside) and a bottom `self.text_below_box` (`height=28`) placed strictly **below** the graph canvas containing `self.opening_label` and `self.graph_summary_label`. |
| **Accuracies & Game Ratings slightly too high (`analysis/accuracy_model.py`, `analysis/performance_rating.py`, `analysis/game_analyzer.py`)** | 1. Evaluating `fen_after` 1 ply deeper from the root than `fen_before` caused $+1$ ply horizon-effect score boosts on non-best moves, which got clamped to `0.00` expected-points loss.<br>2. `AccuracyModel` used `loss_decay_k = 3.65` and a `Q ** 0.85` exponent that inflated mid-range accuracies toward 90%+.<br>3. `PerformanceRatingModel` used an unanchored baseline of `1450 + 420 * Z` without sample-size damping on short games. | 1. Added horizon-effect clamping in `GameAnalyzer.analyze_session_sync` so non-best moves cannot exceed their root MultiPV evaluation.<br>2. Recalibrated `AccuracyModel` (`loss_decay_k = 5.40`, `cp_penalty_weight = 0.14`, `harmonic_blend_weight = 0.45`, and convex exponent `Q ** 1.08`).<br>3. Recalibrated `PerformanceRatingModel` around a `1150` Elo unanchored club median (`80.0%` accuracy / `0.040` avg EP loss center) with sample-size damping (`min(1.0, max(0.55, n_moves / 14.0))`). |
| **Android & iOS Compilation Readiness (`buildozer.spec`, `build_mobile.py`, `main.py`, `app/bootstrap.py`, `platform/`)** | 1. When Buildozer or `kivy-ios` packages `source.dir = .` into `/files/app/main.py`, top-level `from chess_analyzer.*` imports fail unless `sys.modules["chess_analyzer"]` is aliased to the app root.<br>2. Running scripts inside `chess_analyzer/` could shadow Python's stdlib `platform` module.<br>3. Android/iOS require platform-specific writable SQLite paths (`ANDROID_PRIVATE` / `~/Documents`) and native fullscreen viewport sizing. | 1. Registered `sys.modules["chess_analyzer"]` dynamically in `main.py` and proxied stdlib `platform` in `platform/__init__.py`.<br>2. Added `_resolve_writable_data_dir()` in `app/bootstrap.py` for Android (`ANDROID_PRIVATE`) and iOS (`~/Documents`).<br>3. Added root `buildozer.spec`, `build_mobile.py` (`--check`, `--target android`, `--target ios`), `platform/ios/stockfish_ios_recipe.sh`, and `.github/workflows/build_mobile_apk_ipa.yml` for cloud Android + iOS builds. |
| **Kivy Clock Lag & Terminal Spam (`ui/kivy_compat.py`)** | `KivyLabel` mutated `text_size` inside `texture_size`/`size` callbacks without a tolerance threshold, triggering `Label.texture_update` (`-1` priority) in an infinite frame loop. | Removed `text_size` mutation on horizontal scroll labels, added a `> 2.0px` change threshold guard, and throttled live Stockfish UI refresh callbacks to `0.08s` (`~12 fps`). |
| **Per-Move Recursive Tree Variations (`domain/move_history.py`)** | Flat variation list jumped between unrelated moves. | Replaced with recursive `MoveTreeNode` JSON tree so each move stores and cycles its own variations (`Main+2Var (10.Nf3)` $\to$ `Var 1/2 (10.Bd3)` $\to$ `Var 2/2 (10.Rb1)`) independently, supporting nested sub-variations. |

## 2. Mathematical Models & Formulas (Game Review V2.2)

### 2.1 Perspective Normalization & 3-Outcome Expected Points (`analysis/expected_points.py`, `analysis/evaluator.py`)
- Given mover-perspective centipawns $cp$ and optional player rating $R$, the logistic scale is:
  $$S(R) = \text{clip}\!\left(271.58 \cdot \left(1 - 0.065 \cdot \frac{R - 1500}{400}\right),\; 190.0,\; 370.0\right)$$
- Expected points $E \in [0, 1]$ and 3-outcome probabilities $(P_{\text{win}}, P_{\text{draw}}, P_{\text{loss}})$ satisfy:
  $$E(cp, R) = \frac{1}{1 + \exp(-cp / S(R))}, \qquad P_{\text{win}} + P_{\text{draw}} + P_{\text{loss}} = 1.0, \qquad E = P_{\text{win}} + 0.5\,P_{\text{draw}}$$
- **Expected-Points Loss**:
  $$\text{loss}_i = \max\!\left(0.0,\; E_{\text{before, best}} - E_{\text{after, played}}\right)$$

### 2.2 Classification V2 Cutoffs & Precedence Policy (`analysis/move_classifier.py`)
- **Published Chess.com Classification V2 Ordinary Cutoffs**:
  - **Best**: Exact engine top choice or $\text{loss}_i \le 0.0025$ (`0.00`)
  - **Excellent**: $0.00 < \text{loss}_i \le 0.02$
  - **Good**: $0.02 < \text{loss}_i \le 0.05$
  - **Inaccuracy**: $0.05 < \text{loss}_i \le 0.10$
  - **Mistake**: $0.10 < \text{loss}_i \le 0.20$
  - **Blunder**: $0.20 < \text{loss}_i \le 1.00$
- **Precedence Order**: `1. Book` $\to$ `2. Brilliant` $\to$ `3. Great` $\to$ `4. Miss` $\to$ `5. Ordinary V2`.

### 2.3 Recalibrated CAPS2-Inspired Player Accuracy (`analysis/accuracy_model.py`)
- Per-move quality score $q_i \in (0, 1]$:
  $$q_i = \exp\!\left(-5.40 \cdot \left(\text{loss}_i + 0.14 \cdot \min\!\left(1.0, \frac{\text{cp\_loss}_i}{180}\right)\right)\right)$$
- Context-weighted arithmetic mean $\bar{q}_w$ (55%) and harmonic mean $\bar{q}_h$ (45%) are combined and calibrated via a convex exponent ($1.08$) so mistakes and blunders pull accuracy down realistically:
  $$Q = 0.55\,\bar{q}_w + 0.45\,\bar{q}_h, \qquad \text{Accuracy} = \text{clip}\!\left(100 \cdot Q^{1.08},\; 0.0,\; 100.0\right)$$

### 2.4 Recalibrated Single-Game Performance Rating (`analysis/performance_rating.py`)
- Quality composite $Z$ is centered at `80.0%` accuracy and `0.040` average EP loss, with sample-size damping $d = \min(1.0, \max(0.55, n_{\text{moves}} / 14))$.
- **Rated games**: $R_{\text{perf}} = R_{\text{anchor}} + \text{clip}(\text{round}(155 \cdot d \cdot Z), -400, +400)$.
- **Unrated games**: Centered at `1150` Elo ($R_{\text{perf}} = \text{clip}(\text{round}(1150 + 310 \cdot d \cdot Z), 250, 2650)$ rounded to the nearest 50).

## 3. Compiling to Android & iOS

### 3.1 Verify Mobile Readiness & Stage Assets (Any OS)
```powershell
python build_mobile.py --check
```

### 3.2 Compile Android APK (Linux, macOS, or Windows WSL2)
Buildozer runs on Linux, macOS, or **WSL2 (Ubuntu)** on Windows:
```bash
# Inside WSL2 (Ubuntu) or Linux:
cd /mnt/e/chess_analyzer
sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk autoconf libtool pkg-config zlib1g-dev libncurses5-dev cmake libffi-dev libssl-dev
pip install buildozer cython

# Download Stockfish 19 Android ARM64 binary & build debug APK:
python3 install_stockfish_19.py
python3 build_mobile.py --target android
```
The compiled APK is output to `bin/chessanalyzer-2.0.0-arm64-v8a-debug.apk`.

### 3.3 Compile iOS App (macOS with Xcode 15+ or GitHub Actions macOS Runner)
On iOS, Apple forbids child process spawning (`fork`/`execve`), so our app automatically switches to `in_process_ios` transport (`platform/ios/stockfish_c_bridge.c` + `IOSStockfishFFIBridge`):
```bash
# On macOS with Xcode installed:
pip install kivy-ios
python3 build_mobile.py --target ios
open ../ChessAnalyzer-ios/ChessAnalyzer.xcodeproj
```
*(If you do not have a Mac locally, push the project folder to a GitHub repository: the included `.github/workflows/build_mobile_apk_ipa.yml` workflow builds both the Android APK on `ubuntu-22.04` and the iOS Xcode bundle on `macos-14` automatically.)*
