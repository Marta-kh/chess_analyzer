"""
'Analyze This'-style Vertical Mobile Analysis Workspace (Section 5.5).
Clean, zero-overlap vertical layout:
1. Top Header Bar (`< Home`, Mode/Title, `Flip`) — rename input removed from game screen per user request
2. Scrollable Multi-Line Move Review / Coach Box (`KivyScrollLabel`, vertical scroll, `bar_width=0`)
3. Center Slot (`InteractiveChessBoardWidget` OR `GameReviewScorecardWidget` overlay card with interactive Evaluation Graph)
4. Clean 4-Button Action Bar (`[Mainline]`, `[Variants (0)]`, `[Game Review]`, `[Scorecard]`) without placeholder icon boxes
5. Full-Width Horizontally Scrollable Move Strip BELOW the action buttons (`Main: 1. e4 - Best • 1... e5 - Good ...`, chunked for mobile GPUs)
6. Scrollable Multi-Engine & MultiPV Candidate Variation Drawer (`bar_width=0`)
7. Bottom Media Transport Bar (`|<<`, `<`, `>`, `>>|`, `Undo`, `Redo`, `End PV`)
"""
from pathlib import Path
from typing import Optional
import chess
from chess_analyzer.analysis import GameAnalysisProgress, GameAnalysisReport, MoveQuality
from chess_analyzer.app.dependencies import AppContainer
from chess_analyzer.app.navigation import AppNavigator, ScreenName
from chess_analyzer.domain import SessionMode
from chess_analyzer.ui.board import InteractiveChessBoardWidget
from chess_analyzer.ui.kivy_compat import (
    KivyBoxLayout,
    KivyButton,
    KivyClock,
    KivyIconButton,
    KivyLabel,
    KivyScreen,
    KivyScrollLabel,
    KivyScrollView,
    KivyTextInput,
    USING_NATIVE_KIVY,
)
from chess_analyzer.ui.widgets import EngineComparisonPanel, GameReviewScorecardWidget

ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "icons"
EDIT_ICON_PATH = str(ICONS_DIR / "edit.png")


class AnalysisWorkspaceScreen(KivyScreen):
    def __init__(self, container: AppContainer, navigator: AppNavigator, **kwargs) -> None:
        super().__init__(name=ScreenName.WORKSPACE.value, **kwargs)
        self.container = container
        self.navigator = navigator
        self._is_review_running: bool = False
        self._engine_refresh_scheduled: bool = False
        self.is_scorecard_open: bool = False

        # 1. Top Header Bar (Clean 3-item header: < Home | Game Title & Mode | Flip)
        self.top_bar = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=38,
            spacing=4,
            bg_color=(0.12, 0.16, 0.21, 1.0),
        )
        self.btn_home = KivyButton(
            text="< Home",
            size_hint_x=0.22,
            font_size="11sp",
            on_release=lambda _b: self.navigator.navigate_to(ScreenName.HOME),
        )
        self.mode_indicator = KivyLabel(
            text="Analyze This",
            bold=True,
            size_hint_x=0.58,
            font_size="11sp",
            wrap=True,
        )
        # Keep `title_input` and `btn_rename` as attributes for programmatic/API compatibility,
        # but do not mount them in `top_bar` since games are renamed from the Home screen history.
        self.title_input = KivyTextInput(
            text="",
            hint_text="Rename game...",
            size_hint_x=0.24,
        )
        self.btn_rename = KivyIconButton(
            icon_path=EDIT_ICON_PATH,
            text="Rename",
            id="btn_rename_session",
            bg_color=(0.76, 0.84, 0.94, 1.0),
            size_hint_x=0.09,
            on_release=lambda _b: self.rename_current_session(),
        )
        self.btn_flip = KivyButton(
            text="Flip",
            id="btn_flip",
            size_hint_x=0.20,
            font_size="11sp",
            on_release=lambda _b: self.flip_board(),
        )
        self.top_bar.add_widget(self.btn_home)
        self.top_bar.add_widget(self.mode_indicator)
        self.top_bar.add_widget(self.btn_flip)

        # 2. Scrollable Multi-Line Move Review / Coach Box ABOVE the Board
        self.coach_box = KivyBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=50,
            padding=4,
            spacing=2,
            bg_color=(0.15, 0.20, 0.27, 1.0),
        )
        self.current_move_eval_label = KivyScrollLabel(
            text="Coach: Tap 'Game Review' below to classify every move (Best, Great, Blunder, etc.) and open the Scorecard.",
            direction="vertical",
            bold=True,
            font_size="11.5sp",
        )
        self.coach_box.add_widget(self.current_move_eval_label)

        # 3. Center Slot (8x8 Interactive Chessboard OR Chess.com-style Game Review Scorecard Box)
        self.center_slot = KivyBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=436,
            padding=0,
            spacing=0,
        )
        self.board_widget = InteractiveChessBoardWidget(
            session_getter=lambda: self.container.active_session,
            on_move_played=self._on_board_move_played,
        )
        self.scorecard_widget = GameReviewScorecardWidget(
            on_close=self.close_scorecard,
            on_select_ply=self.jump_to_ply_from_review,
        )
        self.center_slot.add_widget(self.board_widget)

        # 4. Clean 4-Button Action Bar without placeholder icon boxes: [Mainline] [Variants (0)] [Game Review] [Scorecard]
        self.action_bar = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=32,
            spacing=4,
        )
        self.btn_mainline = KivyButton(
            text="Mainline",
            id="btn_mainline",
            size_hint_x=0.24,
            font_size="11sp",
            disabled=True,
            bg_color=(0.20, 0.44, 0.36, 1.0),
            on_release=lambda _b: self.return_to_mainline(),
        )
        self.btn_variants = KivyButton(
            text="Variants (0)",
            id="btn_variants",
            size_hint_x=0.24,
            font_size="11sp",
            disabled=True,
            bg_color=(0.36, 0.28, 0.48, 1.0),
            on_release=lambda _b: self.cycle_variants(),
        )
        self.btn_run_imported_classification = KivyButton(
            text="Game Review",
            id="btn_run_classification",
            size_hint_x=0.28,
            font_size="11sp",
            bg_color=(0.22, 0.46, 0.34, 1.0),
            on_release=lambda _b: self.run_classification_now(),
        )
        self.btn_finish_and_analyze = self.btn_run_imported_classification

        self.btn_toggle_scorecard = KivyButton(
            text="Scorecard",
            id="btn_toggle_scorecard",
            size_hint_x=0.24,
            font_size="11sp",
            disabled=True,
            bg_color=(0.44, 0.34, 0.20, 1.0),
            on_release=lambda _b: self.toggle_scorecard(),
        )
        self.classification_status_label = KivyLabel(text="")

        self.action_bar.add_widget(self.btn_mainline)
        self.action_bar.add_widget(self.btn_variants)
        self.action_bar.add_widget(self.btn_run_imported_classification)
        self.action_bar.add_widget(self.btn_toggle_scorecard)

        # 5. Full-Width Horizontally Scrollable Move Strip Placed BELOW the Action Buttons!
        self.notation_row = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=28,
            padding=(6, 2),
            bg_color=(0.13, 0.16, 0.20, 1.0),
        )
        self.move_list_label = KivyScrollLabel(
            text="Main: (start position)",
            direction="horizontal",
            font_size="12sp",
        )
        self.notation_row.add_widget(self.move_list_label)

        # 6. Multi-Engine & MultiPV Candidate Variation Panel
        self.engine_scroll = KivyScrollView(do_scroll_x=False, do_scroll_y=True)
        self.engine_panel = EngineComparisonPanel(
            engine_manager=self.container.engine_manager,
            on_inspect_variation=self.inspect_candidate_variation,
            fen_getter=lambda: (
                self.container.active_session.board_manager.get_active_fen()
                if self.container.active_session
                else chess.STARTING_FEN
            ),
        )
        self.engine_scroll.add_widget(self.engine_panel)
        self.container.engine_manager.add_listener(self._on_engine_update_throttled)

        # 7. Bottom Media Transport Bar
        self.nav_bar = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=40,
            spacing=3,
            bg_color=(0.12, 0.16, 0.21, 1.0),
        )
        self.btn_first = KivyButton(text="|<<", id="btn_nav_first", on_release=lambda _b: self.nav_first())
        self.btn_prev = KivyButton(text="<", id="btn_nav_prev", on_release=lambda _b: self.nav_prev())
        self.btn_next = KivyButton(text=">", id="btn_nav_next", on_release=lambda _b: self.nav_next())
        self.btn_last = KivyButton(text=">>|", id="btn_nav_last", on_release=lambda _b: self.nav_last())
        self.btn_undo = KivyButton(text="Undo", id="btn_undo", on_release=lambda _b: self.undo_move())
        self.btn_redo = KivyButton(text="Redo", id="btn_redo", on_release=lambda _b: self.redo_move())
        self.btn_exit_preview = KivyButton(
            text="End PV",
            id="btn_exit_preview",
            bg_color=(0.50, 0.26, 0.22, 1.0),
            on_release=lambda _b: self.exit_variation_preview(),
        )
        for b in (
            self.btn_first,
            self.btn_prev,
            self.btn_next,
            self.btn_last,
            self.btn_undo,
            self.btn_redo,
            self.btn_exit_preview,
        ):
            self.nav_bar.add_widget(b)

        self.add_widget(self.top_bar)
        self.add_widget(self.coach_box)
        self.add_widget(self.center_slot)
        self.add_widget(self.action_bar)
        self.add_widget(self.notation_row)
        self.add_widget(self.engine_scroll)
        self.add_widget(self.nav_bar)

    def _on_engine_update_throttled(self, _res) -> None:
        if not USING_NATIVE_KIVY:
            self.engine_panel.refresh()
            return
        if self._engine_refresh_scheduled:
            return
        self._engine_refresh_scheduled = True

        def _do_refresh(_dt) -> None:
            self._engine_refresh_scheduled = False
            self.engine_panel.refresh()

        KivyClock.schedule_once(_do_refresh, 0.08)

    def on_pre_enter(self) -> None:
        self.is_scorecard_open = False
        theme = self.container.prefs_repo.get("board_theme", "analyze_this_green")
        self.board_widget.board_theme = theme
        s = self.container.active_session
        if s is not None:
            self.title_input.text = s.metadata.title
            self.container.engine_manager.set_current_fen(s.board_manager.get_active_fen())
            if self.container.analysis_service.get_report(s.session_id) is None:
                saved_cls = self.container.session_repo.load_classifications(s.session_id)
                if saved_cls:
                    from chess_analyzer.analysis.game_report import build_game_report
                    eng = self.container.engine_registry.list_engines()[0]
                    rep = build_game_report(
                        s.session_id,
                        eng.engine_id,
                        eng.version_build,
                        saved_cls,
                        white_rating=getattr(s.metadata, "white_elo", None),
                        black_rating=getattr(s.metadata, "black_elo", None),
                    )
                    self.container.analysis_service._reports_by_session[s.session_id] = rep
        self._sync_center_slot()
        self.refresh_workspace()

    def _sync_center_slot(self) -> None:
        self.center_slot.clear_widgets()
        if self.is_scorecard_open:
            self.center_slot.height = self.scorecard_widget.height
            self.center_slot.add_widget(self.scorecard_widget)
        else:
            self.center_slot.height = self.board_widget.height
            self.center_slot.add_widget(self.board_widget)

    def jump_to_ply_from_review(self, ply: int) -> None:
        """Navigates the board to `ply` when the user clicks a point on the Evaluation Graph."""
        s = self.container.active_session
        if not s:
            return
        s.board_manager.exit_variation_inspection()
        if s.board_manager.history.is_in_variant:
            s.board_manager.history.switch_to_mainline(restore_branch_cursor=False)
        s.board_manager.history.go_to_ply(ply)
        self.is_scorecard_open = False
        self._sync_center_slot()
        self.container.analysis_service.on_position_selected(s)
        self.refresh_workspace()

    def open_scorecard(self) -> None:
        s = self.container.active_session
        if not s:
            return
        rep = self.container.analysis_service.get_report(s.session_id)
        if rep is None:
            return
        self.scorecard_widget.populate(
            rep,
            white_name=s.metadata.white_player or "White",
            black_name=s.metadata.black_player or "Black",
        )
        self.is_scorecard_open = True
        self._sync_center_slot()

    def close_scorecard(self) -> None:
        self.is_scorecard_open = False
        self._sync_center_slot()
        self.refresh_workspace()

    def toggle_scorecard(self) -> None:
        if self.is_scorecard_open:
            self.close_scorecard()
        else:
            self.open_scorecard()

    def rename_current_session(self, new_title: Optional[str] = None) -> str:
        s = self.container.active_session
        if not s:
            return ""
        target = (new_title if new_title is not None else self.title_input.text).strip()
        if not target:
            return s.metadata.title
        s.rename(target)
        self.title_input.text = target
        self.container.session_repo.save_session(s)
        self.refresh_workspace()
        return target

    def return_to_mainline(self) -> None:
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.board_manager.exit_variation_inspection()
            s.board_manager.history.switch_to_mainline(restore_branch_cursor=True)
            if self.container.prefs_repo.get("auto_save_sessions", True):
                self.container.session_repo.save_session(s)
            self.container.analysis_service.on_position_selected(s)
            self.refresh_workspace()

    def cycle_variants(self) -> None:
        """Cycles among the main line and variations at the CURRENT move cursor."""
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.board_manager.exit_variation_inspection()
            h = s.board_manager.history
            var_info = h.get_variations_at_current_move()
            if var_info["total_branches"] > 1:
                h.cycle_variation_at_current_move()
            else:
                h.cycle_active_line()
            if self.container.prefs_repo.get("auto_save_sessions", True):
                self.container.session_repo.save_session(s)
            self.container.analysis_service.on_position_selected(s)
            self.refresh_workspace()

    def _on_board_move_played(self, uci_move: str) -> None:
        session = self.container.active_session
        if session is not None:
            self.container.analysis_service.on_position_selected(session)
            if self.container.prefs_repo.get("auto_save_sessions", True):
                self.container.session_repo.save_session(session)
        self.refresh_workspace()

    def nav_first(self) -> None:
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.board_manager.exit_variation_inspection()
            s.board_manager.history.go_to_first()
            self.container.analysis_service.on_position_selected(s)
            self.refresh_workspace()

    def nav_prev(self) -> None:
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.board_manager.exit_variation_inspection()
            s.board_manager.history.go_to_previous()
            self.container.analysis_service.on_position_selected(s)
            self.refresh_workspace()

    def nav_next(self) -> None:
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.board_manager.exit_variation_inspection()
            s.board_manager.history.go_to_next()
            self.container.analysis_service.on_position_selected(s)
            self.refresh_workspace()

    def nav_last(self) -> None:
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.board_manager.exit_variation_inspection()
            s.board_manager.history.go_to_last()
            self.container.analysis_service.on_position_selected(s)
            self.refresh_workspace()

    def undo_move(self) -> None:
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.undo_move()
            self.container.analysis_service.on_position_selected(s)
            if self.container.prefs_repo.get("auto_save_sessions", True):
                self.container.session_repo.save_session(s)
            self.refresh_workspace()

    def redo_move(self) -> None:
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.redo_move()
            self.container.analysis_service.on_position_selected(s)
            if self.container.prefs_repo.get("auto_save_sessions", True):
                self.container.session_repo.save_session(s)
            self.refresh_workspace()

    def flip_board(self) -> bool:
        s = self.container.active_session
        if not s:
            return False
        flipped = s.board_manager.flip_board()
        self.refresh_workspace()
        return flipped

    def inspect_candidate_variation(self, pv_uci: list[str]) -> None:
        s = self.container.active_session
        if s:
            self.is_scorecard_open = False
            self._sync_center_slot()
            s.board_manager.start_variation_inspection(pv_uci)
            self.refresh_workspace()

    def exit_variation_preview(self) -> None:
        s = self.container.active_session
        if s:
            s.board_manager.exit_variation_inspection()
            self.refresh_workspace()

    def trigger_finish_and_analyze_moves(
        self,
        user_confirmed: bool = True,
        enable_classification: bool = True,
        search_depth: int = 2,
    ) -> Optional[GameAnalysisReport]:
        s = self.container.active_session
        if not s or not user_confirmed:
            return None
        s.finish_game(enable_classification=enable_classification)
        self.container.session_repo.save_session(s)
        if not enable_classification:
            self.refresh_workspace()
            return None
        return self._execute_game_review(s, search_depth=search_depth)

    def run_classification_now(self, search_depth: int = 6) -> Optional[GameAnalysisReport]:
        s = self.container.active_session
        if not s or self._is_review_running:
            return None
        if self.container.analysis_service.has_valid_review(s):
            existing = self.container.analysis_service.get_report(s.session_id)
            self.open_scorecard()
            self.refresh_workspace()
            return existing

        if not s.classification_enabled or not s.is_finished:
            s.finish_game(enable_classification=True)
        self.container.session_repo.save_session(s)
        return self._execute_game_review(s, search_depth=search_depth)

    def _execute_game_review(self, s, search_depth: int = 6) -> Optional[GameAnalysisReport]:
        if USING_NATIVE_KIVY:
            if self._is_review_running:
                return None
            self._is_review_running = True
            self.refresh_workspace()
            self.current_move_eval_label.text = "Running Game Review in background (0%)... The board remains interactive."
            engines = self.container.engine_registry.list_enabled_engines() or self.container.engine_registry.list_engines()
            primary_engine = engines[0]
            effective_depth = max(6, search_depth)

            def _on_prog(prog: GameAnalysisProgress) -> None:
                pct = int(prog.ratio * 100)
                KivyClock.schedule_once(
                    lambda _dt: setattr(
                        self.current_move_eval_label,
                        "text",
                        f"Game Review in progress: evaluating move {prog.completed_plies} of {prog.total_plies} ({pct}%)...",
                    ),
                    0,
                )

            def _on_done(rep: Optional[GameAnalysisReport]) -> None:
                def _finish_ui(_dt) -> None:
                    self._is_review_running = False
                    if rep is not None:
                        self.container.analysis_service._reports_by_session[s.session_id] = rep
                        self.container.session_repo.save_session(s)
                        self.container.session_repo.save_classifications(s.session_id, rep.classifications)
                        self.open_scorecard()
                    self.refresh_workspace()

                KivyClock.schedule_once(_finish_ui, 0)

            self.container.analysis_service.game_analyzer.start_background_analysis(
                session=s,
                engine_def=primary_engine,
                search_depth=effective_depth,
                on_progress=_on_prog,
                on_complete=_on_done,
                force_reanalyze=True,
            )
            return None

        rep = self.container.analysis_service.run_game_classification_sync(
            s,
            search_depth=search_depth,
            force_reanalyze=True,
        )
        if rep is not None:
            self.container.session_repo.save_session(s)
            self.container.session_repo.save_classifications(s.session_id, rep.classifications)
            self.open_scorecard()
        self.refresh_workspace()
        return rep

    def refresh_workspace(self) -> None:
        s = self.container.active_session
        if s is None:
            self.mode_indicator.text = "No Active Session"
            return

        bm = s.board_manager
        h = bm.history
        self.container.engine_manager.set_current_fen(bm.get_active_fen())

        if bm.is_inspecting_variation:
            rec_state = "PV PREVIEW"
        elif h.is_in_variant:
            rec_state = "VARIATION"
        else:
            rec_state = s.mode.value.upper()

        self.mode_indicator.text = f"[{rec_state}] {s.metadata.title}"
        self.btn_exit_preview.disabled = not bm.is_inspecting_variation

        var_info = h.get_variations_at_current_move()
        self.btn_mainline.disabled = not h.is_in_variant
        if var_info["total_branches"] > 1:
            self.btn_variants.disabled = False
            self.btn_variants.text = var_info["button_label"]
        else:
            self.btn_variants.disabled = True
            self.btn_variants.text = "Variants (0)"

        report = self.container.analysis_service.get_report(s.session_id)
        already_reviewed = self.container.analysis_service.has_valid_review(s)
        if self._is_review_running:
            self.btn_run_imported_classification.disabled = True
            self.btn_run_imported_classification.text = "Reviewing..."
        elif already_reviewed:
            self.btn_run_imported_classification.disabled = True
            self.btn_run_imported_classification.text = "Reviewed" if USING_NATIVE_KIVY else "✓ Reviewed"
        else:
            self.btn_run_imported_classification.disabled = False
            self.btn_run_imported_classification.text = "Game Review"

        self.btn_toggle_scorecard.disabled = report is None
        self.btn_toggle_scorecard.text = "Hide Card" if self.is_scorecard_open else "Scorecard"

        cls_by_ply = {c.ply: c for c in report.classifications} if (report and not h.is_in_variant) else {}

        parts = []
        active_path = h._get_active_tree_path()
        for idx, node in enumerate(h.nodes):
            cursor_mark = ">" if node.ply == h.cursor else ""
            mv_prefix = f"{node.fullmove_number}." if node.turn_before == "white" else f"{node.fullmove_number}..."
            var_suffix = ""
            if idx < len(active_path):
                t_node = active_path[idx]
                parent = t_node.parent
                if parent is not None and len(parent.children) > 1:
                    var_suffix = f"(+{len(parent.children) - 1}v)"
            if node.ply in cls_by_ply:
                q_name = cls_by_ply[node.ply].quality.value
                parts.append(f"{cursor_mark}{mv_prefix}{node.san}{var_suffix} - {q_name}")
            else:
                parts.append(f"{cursor_mark}{mv_prefix}{node.san}{var_suffix}")
        prefix_lbl = "Var: " if h.is_in_variant else "Main: "
        self.move_list_label.text = prefix_lbl + ("   ".join(parts) if parts else "(start position)")

        if not self._is_review_running:
            curr_node = h.current_node
            if s.is_classification_stale:
                self.current_move_eval_label.text = (
                    "Move history was edited after analysis — classifications invalidated. Tap 'Game Review' to re-analyze."
                )
                self.classification_status_label.text = "invalidated"
            elif curr_node and curr_node.ply in cls_by_ply:
                c_item = cls_by_ply[curr_node.ply]
                ev_str = c_item.eval_after.format_display("white") if c_item.eval_after else ""
                mv_num = f"{curr_node.fullmove_number}." if curr_node.turn_before == "white" else f"{curr_node.fullmove_number}..."
                self.current_move_eval_label.text = (
                    f"Move {mv_num} {curr_node.san} — {c_item.badge_symbol} {c_item.quality.value} (Eval: {ev_str})\n"
                    f"{c_item.explanation}"
                )
                self.classification_status_label.text = f"★Best:{report.white_summary.counts.get(MoveQuality.BEST.value, 0) + report.black_summary.counts.get(MoveQuality.BEST.value, 0)}"
            elif report is not None and not h.is_in_variant:
                ws = report.white_summary
                bs = report.black_summary
                op_txt = f" ({report.opening_eco} {report.opening_name})" if getattr(report, "opening_name", "") else ""
                self.current_move_eval_label.text = (
                    f"Game Review Complete{op_txt} — White: {ws.accuracy_percent}% ({ws.game_rating} Elo) | "
                    f"Black: {bs.accuracy_percent}% ({bs.game_rating} Elo).\n"
                    f"Step through moves (< or >) to read each move's review, or scroll the move strip below."
                )
                self.classification_status_label.text = f"★Best:{ws.counts.get(MoveQuality.BEST.value, 0) + bs.counts.get(MoveQuality.BEST.value, 0)}"
            elif h.is_in_variant:
                self.current_move_eval_label.text = (
                    "Exploring variation branch — Use the Variants button to switch variations at this move, "
                    "or tap 'Mainline' to return to the original game."
                )
            else:
                self.current_move_eval_label.text = (
                    "Coach: Tap 'Game Review' below to classify every move (Best, Great, Blunder, etc.) and open the Scorecard."
                )

        self.board_widget.refresh_board()
        self.engine_panel.refresh()