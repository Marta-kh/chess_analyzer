"""
Chess.com-style Game Review Scorecard Overlay Box (`GameReviewScorecardWidget`)
with an interactive `EvaluationGraphWidget` at the top of the card and text placed cleanly below the graph.
Uses the user's custom uploaded icons for Best (`best.png`), Excellent (`excellent.png`),
Good (`good.png`), and Book (`book.png`), while keeping the other 6 category badges as text pills.
"""
from pathlib import Path
from typing import Callable, Dict, List, Optional
from chess_analyzer.analysis import GameAnalysisReport, MoveQuality, SCORECARD_ROWS
from chess_analyzer.ui.kivy_compat import (
    KivyBoxLayout,
    KivyButton,
    KivyIconButton,
    KivyLabel,
    KivyScrollLabel,
    USING_NATIVE_KIVY,
)

if USING_NATIVE_KIVY:
    from kivy.graphics import Color, Line, Rectangle  # type: ignore

ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "icons"

CUSTOM_EVAL_ICONS: Dict[MoveQuality, str] = {
    MoveQuality.BEST: str(ICONS_DIR / "best.png"),
    MoveQuality.EXCELLENT: str(ICONS_DIR / "excellent.png"),
    MoveQuality.GOOD: str(ICONS_DIR / "good.png"),
    MoveQuality.BOOK: str(ICONS_DIR / "book.png"),
}


class EvaluationGraphWidget(KivyBoxLayout):
    """
    Interactive Chess.com-style Evaluation Graph placed at the top of the Game Review Scorecard.
    - Top sub-box (`self.graph_canvas_box`, height=32): pure graph plot area with zero text inside,
      so the evaluation curve never overlaps any text.
    - Bottom sub-box (`self.text_below_box`, height=28): Opening title and key-moments caption placed
      strictly BELOW the graph plot area.
    """

    def __init__(
        self,
        on_select_ply: Optional[Callable[[int], None]] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", 62)
        super().__init__(
            orientation="vertical",
            spacing=2,
            padding=(4, 2),
            bg_color=(0.14, 0.17, 0.22, 1.0),
            **kwargs,
        )
        self._on_select_ply = on_select_ply
        self.eval_curve_cp: List[int] = []
        self.ep_curve_white: List[float] = []
        self.selected_ply: Optional[int] = None

        # 1. Pure Graph Plot Area on TOP (no text inside this widget!)
        self.graph_canvas_box = KivyBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=30,
            bg_color=(0.09, 0.11, 0.15, 1.0),
        )

        # 2. Text Container strictly BELOW the Graph Plot Area
        self.text_below_box = KivyBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=28,
            spacing=1,
        )
        self.opening_label = KivyLabel(
            text="Opening: Standard Chess",
            id="scorecard_opening_label",
            font_size="10sp",
            bold=True,
            size_hint_y=None,
            height=14,
            color=(0.82, 0.88, 0.95, 1.0),
        )
        self.graph_summary_label = KivyLabel(
            text="Tap graph above to jump to move",
            id="scorecard_eval_graph_summary",
            font_size="9.5sp",
            size_hint_y=None,
            height=13,
            color=(0.66, 0.76, 0.86, 1.0),
        )
        self.text_below_box.add_widget(self.opening_label)
        self.text_below_box.add_widget(self.graph_summary_label)

        self.add_widget(self.graph_canvas_box)
        self.add_widget(self.text_below_box)

        if USING_NATIVE_KIVY:
            self.graph_canvas_box.bind(pos=self._redraw_canvas, size=self._redraw_canvas)

    def set_report(self, report: Optional[GameAnalysisReport]) -> None:
        if report is None:
            self.eval_curve_cp = []
            self.ep_curve_white = []
            self.opening_label.text = "Opening: —"
            self.graph_summary_label.text = "Tap graph above to jump to move"
            return

        self.eval_curve_cp = list(report.eval_curve_white_cp)
        self.ep_curve_white = list(getattr(report, "eval_curve_ep_white", []))
        eco = getattr(report, "opening_eco", "")
        op_name = getattr(report, "opening_name", "Standard Chess")
        prefix = f"{eco} " if eco else ""
        self.opening_label.text = f"📖 {prefix}{op_name}"

        events = getattr(report, "selected_events", [])
        if events:
            ev_tags = [f"{e.move_number}{'.' if e.mover_color == 'white' else '...'}{e.played_san}" for e in events[:4]]
            self.graph_summary_label.text = f"Key moments: {', '.join(ev_tags)} (tap graph to jump)"
        else:
            self.graph_summary_label.text = f"{len(self.eval_curve_cp)} plies analyzed • Tap graph above to jump to move"

        if USING_NATIVE_KIVY:
            self._redraw_canvas()

    def select_ply(self, ply: int) -> Optional[int]:
        """Programmatically or interactively select a 1-based ply on the evaluation graph."""
        if not self.eval_curve_cp:
            return None
        clamped = max(1, min(len(self.eval_curve_cp), int(ply)))
        self.selected_ply = clamped
        if USING_NATIVE_KIVY:
            self._redraw_canvas()
        if self._on_select_ply is not None:
            self._on_select_ply(clamped)
        return clamped

    def on_touch_down(self, touch):  # type: ignore
        if USING_NATIVE_KIVY and self.graph_canvas_box.collide_point(*touch.pos) and self.eval_curve_cp:
            rel_x = max(
                0.0,
                min(1.0, (touch.x - self.graph_canvas_box.x) / max(1.0, float(self.graph_canvas_box.width))),
            )
            n = len(self.eval_curve_cp)
            target_ply = max(1, min(n, int(round(rel_x * (n - 1))) + 1))
            self.select_ply(target_ply)
            return True
        if USING_NATIVE_KIVY:
            return super().on_touch_down(touch)
        return False

    def _redraw_canvas(self, *args) -> None:
        if not USING_NATIVE_KIVY:
            return
        box = self.graph_canvas_box
        box.canvas.after.clear()
        if not self.eval_curve_cp or box.width <= 10 or box.height <= 8:
            return

        gx = box.x + 6
        gw = max(10.0, box.width - 12)
        gy = box.y + 3
        gh = max(8.0, box.height - 6)
        mid_y = gy + gh * 0.5

        with box.canvas.after:
            # Equality midline (0.00)
            Color(0.45, 0.50, 0.58, 0.55)
            Line(points=[gx, mid_y, gx + gw, mid_y], width=1.0)

            n = len(self.eval_curve_cp)
            pts: List[float] = []
            for idx, cp in enumerate(self.eval_curve_cp):
                px = gx + (gw * idx / max(1, n - 1)) if n > 1 else gx + gw * 0.5
                norm = max(-1.0, min(1.0, float(cp) / 700.0))
                py = mid_y + norm * (gh * 0.44)
                pts.extend([px, py])

            if len(pts) >= 4:
                Color(0.55, 0.82, 0.40, 0.95)
                Line(points=pts, width=1.5)

            if self.selected_ply is not None and 1 <= self.selected_ply <= n:
                sel_idx = self.selected_ply - 1
                sx = gx + (gw * sel_idx / max(1, n - 1)) if n > 1 else gx + gw * 0.5
                Color(0.98, 0.80, 0.22, 0.95)
                Line(points=[sx, gy, sx, gy + gh], width=1.2)


class GameReviewScorecardWidget(KivyBoxLayout):
    """Visual Game Review Scorecard box displayed above/over the board when Game Review finishes."""

    def __init__(
        self,
        on_close: Callable[[], None],
        on_select_ply: Optional[Callable[[int], None]] = None,
        report: Optional[GameAnalysisReport] = None,
        white_name: str = "White",
        black_name: str = "Black",
        **kwargs,
    ) -> None:
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", 436)
        super().__init__(
            orientation="vertical",
            spacing=1,
            padding=5,
            bg_color=(0.11, 0.13, 0.17, 1.0),
            **kwargs,
        )
        self._on_close = on_close
        self._on_select_ply = on_select_ply
        self.report = report
        self.white_name = white_name
        self.black_name = black_name
        self.category_badge_widgets: Dict[str, object] = {}

        # Header Bar with Title & Close Button
        self.header_row = KivyBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=26,
            spacing=6,
            bg_color=(0.15, 0.19, 0.25, 1.0),
        )
        self.title_label = KivyLabel(
            text="📊 GAME REVIEW REPORT",
            bold=True,
            font_size="12sp",
            size_hint_x=0.68,
        )
        self.btn_close = KivyButton(
            text="× Show Board",
            id="btn_close_scorecard",
            size_hint_x=0.32,
            font_size="11sp",
            bg_color=(0.24, 0.46, 0.34, 1.0),
            on_release=lambda _b: self._on_close(),
        )
        self.header_row.add_widget(self.title_label)
        self.header_row.add_widget(self.btn_close)

        # Interactive Evaluation Graph on top of the Scorecard (with text cleanly below the graph plot)
        self.eval_graph = EvaluationGraphWidget(on_select_ply=self._handle_graph_select_ply)

        self.body_box = KivyBoxLayout(orientation="vertical", spacing=1)
        self.add_widget(self.header_row)
        self.add_widget(self.eval_graph)
        self.add_widget(self.body_box)
        self.populate(report, white_name=white_name, black_name=black_name)

    def _handle_graph_select_ply(self, ply: int) -> None:
        if self._on_select_ply is not None:
            self._on_select_ply(ply)

    def select_ply(self, ply: int) -> Optional[int]:
        """Jump to a specific 1-based ply from the Scorecard's Evaluation Graph."""
        return self.eval_graph.select_ply(ply)

    def populate(
        self,
        report: Optional[GameAnalysisReport],
        white_name: str = "White",
        black_name: str = "Black",
    ) -> None:
        self.report = report
        self.white_name = white_name
        self.black_name = black_name
        self.eval_graph.set_report(report)
        self.body_box.clear_widgets()
        self.category_badge_widgets.clear()

        if report is None:
            self.body_box.add_widget(
                KivyLabel(
                    text="No Game Review report generated yet. Tap 'Game Review' to analyze all moves.",
                    wrap=True,
                )
            )
            return

        ws = report.white_summary
        bs = report.black_summary

        # 1. Players Header Row
        players_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=16, spacing=6)
        players_row.add_widget(KivyLabel(text="Player", size_hint_x=0.40, font_size="10.5sp", color=(0.68, 0.73, 0.80, 1.0)))
        players_row.add_widget(KivyLabel(text=white_name[:12], size_hint_x=0.24, bold=True, font_size="10.5sp"))
        players_row.add_widget(KivyLabel(text="", size_hint_x=0.12))
        players_row.add_widget(KivyLabel(text=black_name[:12], size_hint_x=0.24, bold=True, font_size="10.5sp"))
        self.body_box.add_widget(players_row)

        # 2. Accuracy Row (White pill box + Black pill box)
        acc_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=26, spacing=6)
        acc_row.add_widget(
            KivyLabel(text="Accuracy", size_hint_x=0.40, bold=True, font_size="11.5sp")
        )
        acc_row.add_widget(
            KivyLabel(
                text=f"{ws.accuracy_percent:.1f}",
                id="scorecard_white_acc",
                size_hint_x=0.24,
                bold=True,
                font_size="13.5sp",
                color=(0.08, 0.10, 0.13, 1.0),
                bg_color=(0.96, 0.97, 0.99, 1.0),
            )
        )
        acc_row.add_widget(KivyLabel(text="", size_hint_x=0.12))
        acc_row.add_widget(
            KivyLabel(
                text=f"{bs.accuracy_percent:.1f}",
                id="scorecard_black_acc",
                size_hint_x=0.24,
                bold=True,
                font_size="13.5sp",
                color=(0.96, 0.97, 0.99, 1.0),
                bg_color=(0.20, 0.23, 0.28, 1.0),
            )
        )
        self.body_box.add_widget(acc_row)

        # 3. 10 Move-Quality Rows:
        #    Uses uploaded PNG icons for Best, Excellent, Good, and Book, and keeps the existing badge pills for the other 6!
        for label_txt, quality_enum, badge_sym, rgba in SCORECARD_ROWS:
            w_cnt = ws.counts.get(quality_enum.value, 0)
            b_cnt = bs.counts.get(quality_enum.value, 0)
            row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=22, spacing=4)
            row.add_widget(
                KivyLabel(
                    text=label_txt,
                    size_hint_x=0.40,
                    font_size="11sp",
                    color=(0.86, 0.89, 0.93, 1.0),
                )
            )
            row.add_widget(
                KivyLabel(
                    text=str(w_cnt),
                    size_hint_x=0.24,
                    bold=True,
                    font_size="12sp",
                    color=rgba,
                )
            )

            icon_file = CUSTOM_EVAL_ICONS.get(quality_enum)
            if icon_file and Path(icon_file).exists():
                badge_widget = KivyIconButton(
                    icon_path=icon_file,
                    text=badge_sym,
                    id=f"badge_{quality_enum.name.lower()}",
                    bg_color=rgba,
                    size_hint_x=0.12,
                )
            else:
                badge_widget = KivyLabel(
                    text=badge_sym,
                    id=f"badge_{quality_enum.name.lower()}",
                    size_hint_x=0.12,
                    bold=True,
                    font_size="10sp",
                    color=(0.08, 0.09, 0.11, 1.0) if rgba[0] + rgba[1] > 1.3 else (0.98, 0.99, 1.0, 1.0),
                    bg_color=rgba,
                )
            self.category_badge_widgets[quality_enum.value] = badge_widget
            row.add_widget(badge_widget)

            row.add_widget(
                KivyLabel(
                    text=str(b_cnt),
                    size_hint_x=0.24,
                    bold=True,
                    font_size="12sp",
                    color=rgba,
                )
            )
            self.body_box.add_widget(row)

        # 4. Bottom Game Rating Row
        rating_row = KivyBoxLayout(orientation="horizontal", size_hint_y=None, height=26, spacing=6)
        rating_row.add_widget(
            KivyLabel(text="Game Rating", size_hint_x=0.40, bold=True, font_size="11.5sp")
        )
        rating_row.add_widget(
            KivyLabel(
                text=str(ws.game_rating),
                id="scorecard_white_rating",
                size_hint_x=0.24,
                bold=True,
                font_size="13sp",
                color=(0.08, 0.10, 0.13, 1.0),
                bg_color=(0.96, 0.97, 0.99, 1.0),
            )
        )
        rating_row.add_widget(KivyLabel(text="", size_hint_x=0.12))
        rating_row.add_widget(
            KivyLabel(
                text=str(bs.game_rating),
                id="scorecard_black_rating",
                size_hint_x=0.24,
                bold=True,
                font_size="13sp",
                color=(0.96, 0.97, 0.99, 1.0),
                bg_color=(0.20, 0.23, 0.28, 1.0),
            )
        )
        self.body_box.add_widget(rating_row)
