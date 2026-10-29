"""
'Analyze This'-style Multi-Engine & MultiPV Candidate Variation Panel.
Uses `auto_height=True` (`minimum_height` binding) on all vertical containers so adding
2..5 variations expands the scrollable container cleanly and NEVER overlaps the engine header or status text!
"""
from typing import Callable, Dict, Optional
import chess
from chess_analyzer.engines import (
    CandidateVariation,
    EngineAnalysisResult,
    EngineDefinition,
    EngineManager,
    MAX_VARIATIONS_PER_ENGINE,
)
from chess_analyzer.ui.kivy_compat import KivyBoxLayout, KivyButton, KivyDP, KivyLabel, KivyScrollLabel


class EngineInstancePanel(KivyBoxLayout):
    """Single Stockfish engine card displaying up to 5 candidate variations (MultiPV 1..5) without overlap."""

    def __init__(
        self,
        engine_def: EngineDefinition,
        result: Optional[EngineAnalysisResult],
        engine_manager: EngineManager,
        on_inspect_variation: Callable[[list[str]], None],
        on_ui_changed: Callable[[], None],
        perspective: str = "white",
        **kwargs,
    ) -> None:
        super().__init__(
            orientation="vertical",
            auto_height=True,
            spacing=3,
            padding=4,
            bg_color=(0.13, 0.16, 0.21, 1.0),
            **kwargs,
        )
        self.engine_def = engine_def
        self.result = result
        self.engine_manager = engine_manager
        self._on_inspect = on_inspect_variation
        self._on_ui_changed = on_ui_changed
        self.perspective = perspective

        self.top_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=28, spacing=4)
        self.header_label = KivyLabel(
            text=f"⚙ {engine_def.display_name}",
            bold=True,
            halign="left",
            size_hint_x=0.52,
        )
        req_count = engine_def.config.visible_variations
        can_add_more = req_count < MAX_VARIATIONS_PER_ENGINE
        self.add_variation_btn = KivyButton(
            text=f"+ Line ({req_count}/{MAX_VARIATIONS_PER_ENGINE})",
            id=f"add_var_{engine_def.engine_id}",
            size_hint_x=0.48,
            disabled=not can_add_more,
            opacity=1.0 if can_add_more else 0.0,
            bg_color=(0.20, 0.45, 0.30, 1.0),
            on_release=lambda _b: self._handle_add_variation(),
        )
        self.top_row.add_widget(self.header_label)
        self.top_row.add_widget(self.add_variation_btn)

        self.status_label = KivyLabel(
            text="",
            size_hint_y=None,
            height=20,
            font_size="11sp",
            halign="left",
            color=(0.72, 0.78, 0.86, 1.0),
        )
        self.variations_box = KivyBoxLayout(orientation="vertical", auto_height=True, spacing=3)
        self.limitation_label = KivyLabel(text="", size_hint_y=None, height=0, font_size="11sp", halign="left")

        self.add_widget(self.top_row)
        self.add_widget(self.status_label)
        self.add_widget(self.variations_box)
        self.add_widget(self.limitation_label)
        self._populate()

    def _populate(self) -> None:
        self.variations_box.clear_widgets()
        if self.result is None:
            self.status_label.text = "Engine idle — tap 'Engine: OFF' to start analysis."
            return

        depth_str = f"d{self.result.current_depth}/{self.result.target_depth or '∞'}"
        pct = int(self.result.progress_ratio * 100)
        calc_extra = " • Calculating..." if self.result.is_calculating_additional_variation else ""
        self.status_label.text = (
            f"{self.result.status.value.upper()} | {depth_str} ({pct}%) | "
            f"Score: {'White (+)' if self.perspective == 'white' else 'Black (+)'}{calc_extra}"
        )

        if self.result.limited_variations_reason:
            self.limitation_label.height = KivyDP(18)
            self.limitation_label.text = f"Note: {self.result.limited_variations_reason}"
        else:
            self.limitation_label.height = 0
            self.limitation_label.text = ""

        for var in self.result.variations:
            row = self._build_variation_row(var)
            self.variations_box.add_widget(row)

    def _build_variation_row(self, var: CandidateVariation) -> KivyBoxLayout:
        row = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=28,
            spacing=3,
            bg_color=(0.17, 0.21, 0.27, 1.0),
        )
        eval_str = var.score.format_display(self.perspective)
        pv_text = " ".join(var.pv_san[:8]) if var.pv_san else " ".join(var.pv_uci[:8])
        line_scroll = KivyScrollLabel(
            text=f"#{var.multipv_index} [{eval_str}] {pv_text}",
            direction="horizontal",
            font_size="12sp",
            size_hint_x=0.66,
        )
        inspect_btn = KivyButton(
            text="Preview",
            id=f"inspect_{self.engine_def.engine_id}_{var.multipv_index}",
            size_hint_x=0.22,
            bg_color=(0.22, 0.36, 0.52, 1.0),
            on_release=lambda _b, pv=list(var.pv_uci): self._on_inspect(pv),
        )
        remove_btn = KivyButton(
            text="×",
            id=f"remove_var_{self.engine_def.engine_id}_{var.multipv_index}",
            size_hint_x=0.12,
            disabled=(self.engine_def.config.visible_variations <= 1),
            bg_color=(0.45, 0.22, 0.22, 1.0),
            on_release=lambda _b, idx=var.multipv_index: self._handle_remove_variation(idx),
        )
        row.add_widget(line_scroll)
        row.add_widget(inspect_btn)
        row.add_widget(remove_btn)
        return row

    def _handle_add_variation(self) -> None:
        self.engine_manager.add_variation(self.engine_def.engine_id)
        self._on_ui_changed()

    def _handle_remove_variation(self, multipv_index: int) -> None:
        self.engine_manager.remove_variation(self.engine_def.engine_id, multipv_index=multipv_index)
        self._on_ui_changed()


class EngineComparisonPanel(KivyBoxLayout):
    """Auto-height container displaying the 'Analyze This' engine control strip and active engine cards."""

    def __init__(
        self,
        engine_manager: EngineManager,
        on_inspect_variation: Callable[[list[str]], None],
        fen_getter: Optional[Callable[[], str]] = None,
        **kwargs,
    ) -> None:
        super().__init__(orientation="vertical", auto_height=True, spacing=4, **kwargs)
        self.engine_manager = engine_manager
        self._on_inspect = on_inspect_variation
        self._fen_getter = fen_getter
        self.engine_panels: Dict[str, EngineInstancePanel] = {}

        self.control_bar = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=32, spacing=4)
        self.eval_pill = KivyLabel(
            text="Eval: --",
            size_hint_x=0.36,
            bold=True,
            bg_color=(0.20, 0.25, 0.32, 1.0),
        )
        self.toggle_analysis_btn = KivyButton(
            text="Engine: OFF (Start Stockfish)",
            id="btn_toggle_analysis",
            size_hint_x=0.64,
            bg_color=(0.22, 0.48, 0.32, 1.0),
            on_release=lambda _b: self.toggle_analysis(),
        )
        self.control_bar.add_widget(self.eval_pill)
        self.control_bar.add_widget(self.toggle_analysis_btn)

        self.panels_container = KivyBoxLayout(orientation="vertical", auto_height=True, spacing=4)
        self.add_widget(self.control_bar)
        self.add_widget(self.panels_container)
        self.refresh()

    def toggle_analysis(self, current_fen: Optional[str] = None) -> None:
        if current_fen is None and self._fen_getter is not None:
            try:
                current_fen = self._fen_getter()
            except Exception:
                current_fen = chess.STARTING_FEN
        new_state = not self.engine_manager.is_analysis_active
        self.engine_manager.set_analysis_active(new_state, current_fen=current_fen)
        self.refresh()

    def refresh(self) -> None:
        self.panels_container.clear_widgets()
        self.engine_panels.clear()
        active = self.engine_manager.is_analysis_active
        self.toggle_analysis_btn.text = "Engine: ON (Stop Stockfish)" if active else "Engine: OFF (Start Stockfish)"

        if not active:
            self.eval_pill.text = "Eval: OFF"
            self.panels_container.add_widget(
                KivyLabel(
                    text="Stockfish is paused. Tap 'Engine: OFF (Start Stockfish)' to evaluate current board.",
                    size_hint_y=None,
                    height=24,
                    font_size="11.5sp",
                )
            )
            return

        results = self.engine_manager.get_results()
        first_score_str = "Eval: ..."
        for eng in self.engine_manager.registry.list_enabled_engines():
            res = results.get(eng.engine_id)
            if res and res.variations:
                top_score = res.variations[0].score
                disp = top_score.format_display("white")
                if top_score.is_mate:
                    wm = top_score.white_mate
                    if wm and wm > 0:
                        first_score_str = f"Mate in {wm} (W)"
                    elif wm and wm < 0:
                        first_score_str = f"Mate in {abs(wm)} (B)"
                    else:
                        first_score_str = f"Eval: {disp}"
                else:
                    first_score_str = f"Eval: {disp}"
            panel = EngineInstancePanel(
                engine_def=eng,
                result=res,
                engine_manager=self.engine_manager,
                on_inspect_variation=self._on_inspect,
                on_ui_changed=self.refresh,
            )
            self.engine_panels[eng.engine_id] = panel
            self.panels_container.add_widget(panel)
        self.eval_pill.text = first_score_str
