"""
Kivy framework adapter with 'Analyze This' visual styling, density-independent pixel (`dp`) scaling
for iOS Retina & Android screens, safe-area mobile insets, chunked OpenGL stencil-clipped scrollable text
(preventing >4096px GPU texture blackouts on long move lists), icon-enabled buttons, and Android back-gesture support.
"""
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

os.environ.setdefault("KIVY_NO_ARGS", "1")

_IS_ANDROID = (
    ("ANDROID_ARGUMENT" in os.environ)
    or ("ANDROID_PRIVATE" in os.environ)
    or (os.environ.get("KIVY_BUILD") == "android")
)
_IS_IOS = (
    (os.environ.get("KIVY_BUILD") == "ios")
    or (sys.platform == "ios")
    or ("/Containers/Data/Application/" in str(Path.home()))
    or ("/CoreSimulator/Devices/" in str(Path.home()))
)
_IS_MOBILE = _IS_ANDROID or _IS_IOS

_IN_TEST_RUNNER = (
    os.environ.get("CHESS_ANALYZER_FORCE_HEADLESS") == "1"
    or "unittest" in sys.modules
    or "pytest" in sys.modules
    or any("unittest" in arg or "pytest" in arg for arg in sys.argv)
)

# Glyphs missing from Kivy's default Roboto font on iOS/Android that otherwise render as [X] tofu boxes
_MOBILE_UNSUPPORTED_GLYPHS = (
    ("🔍 ", ""),
    ("🔍", ""),
    ("📊 ", ""),
    ("📊", ""),
    ("↩ ", ""),
    ("↩", ""),
    ("⏳ ", ""),
    ("⏳", ""),
    ("⚙  ", ""),
    ("⚙ ", ""),
    ("⚙", ""),
    ("♟  ", ""),
    ("♟ ", ""),
    ("♟", ""),
    ("☁  ", ""),
    ("☁ ", ""),
    ("☁", ""),
    ("✎  ", ""),
    ("✎ ", ""),
    ("✎", ""),
    ("✓ ", ""),
    ("✓", ""),
    ("▶ ", "> "),
    ("▶", ">"),
    ("★", "*"),
    ("→", "->"),
)


def _clean_mobile_display_text(text: str) -> str:
    if not text:
        return text
    out = text
    for bad, rep in _MOBILE_UNSUPPORTED_GLYPHS:
        if bad in out:
            out = out.replace(bad, rep)
    return out


try:
    if _IN_TEST_RUNNER:
        raise ImportError("Running inside automated test runner; using deterministic headless widget tree.")

    from kivy.config import Config  # type: ignore
    # Prevent Android back-swipe / Escape key from exiting the app instead of navigating back
    Config.set("kivy", "exit_on_escape", "0")
    if not _IS_MOBILE:
        Config.set("graphics", "width", "430")
        Config.set("graphics", "height", "860")

    from kivy.app import App as _NativeApp  # type: ignore
    from kivy.clock import Clock as KivyClock  # type: ignore
    from kivy.core.window import Window as _NativeWindow  # type: ignore
    from kivy.graphics import Color as _NativeColor, Line as _NativeLine, Rectangle as _NativeRectangle  # type: ignore
    from kivy.metrics import dp as _native_dp  # type: ignore
    from kivy.uix.behaviors import ButtonBehavior as _NativeButtonBehavior  # type: ignore
    from kivy.uix.boxlayout import BoxLayout as _NativeBoxLayout  # type: ignore
    from kivy.uix.button import Button as _NativeButton  # type: ignore
    from kivy.uix.gridlayout import GridLayout as _NativeGridLayout  # type: ignore
    from kivy.uix.image import Image as _NativeImage  # type: ignore
    from kivy.uix.label import Label as _NativeLabel  # type: ignore
    from kivy.uix.screenmanager import (  # type: ignore
        NoTransition as _NativeNoTransition,
        Screen as _NativeScreen,
        ScreenManager as _NativeScreenManager,
    )
    from kivy.uix.scrollview import ScrollView as _NativeScrollView  # type: ignore
    from kivy.uix.textinput import TextInput as _NativeTextInput  # type: ignore
    from kivy.uix.widget import Widget as _NativeWidget  # type: ignore

    try:
        if not _IS_MOBILE:
            _NativeWindow.size = (430, 860)
        _NativeWindow.clearcolor = (0.09, 0.11, 0.14, 1.0)
    except Exception:
        pass

    USING_NATIVE_KIVY = True
    KivyWindow = _NativeWindow

    def KivyDP(val: float) -> float:
        return float(_native_dp(val))

    def _scale_dim(val: Any) -> Any:
        if isinstance(val, (int, float)):
            return float(_native_dp(val))
        if isinstance(val, (tuple, list)):
            return [float(_native_dp(x)) if isinstance(x, (int, float)) else x for x in val]
        return val

    def _apply_bg_color(widget: Any, bg_color: Optional[Tuple[float, float, float, float]]) -> None:
        if bg_color is None:
            return
        with widget.canvas.before:
            widget._bg_color_instr = _NativeColor(*bg_color)
            widget._bg_rect_instr = _NativeRectangle(pos=widget.pos, size=widget.size)

        def _update_rect(inst: Any, _val: Any) -> None:
            inst._bg_rect_instr.pos = inst.pos
            inst._bg_rect_instr.size = inst.size

        widget.bind(pos=_update_rect, size=_update_rect)

    def _clean_kwargs(kwargs: Dict[str, Any]):
        wid = kwargs.pop("id", None)
        on_rel = kwargs.pop("on_release", None)
        bg_color = kwargs.pop("bg_color", None)
        for dim_key in ("height", "width", "padding", "spacing", "scroll_wheel_distance"):
            if dim_key in kwargs and kwargs[dim_key] is not None:
                kwargs[dim_key] = _scale_dim(kwargs[dim_key])
        return wid, on_rel, bg_color, kwargs

    class KivyWidget(_NativeWidget):
        def __init__(self, **kwargs: Any) -> None:
            wid, on_rel, bg_color, clean = _clean_kwargs(kwargs)
            super().__init__(**clean)
            self.id = wid
            _apply_bg_color(self, bg_color)
            if on_rel is not None and hasattr(self, "bind"):
                self.bind(on_release=on_rel)

    class KivyBoxLayout(_NativeBoxLayout):
        def __init__(self, orientation: str = "vertical", auto_height: bool = False, **kwargs: Any) -> None:
            kwargs.setdefault("padding", 4)
            kwargs.setdefault("spacing", 4)
            wid, _, bg_color, clean = _clean_kwargs(kwargs)
            if auto_height:
                clean["size_hint_y"] = None
            super().__init__(orientation=orientation, **clean)
            self.id = wid
            _apply_bg_color(self, bg_color)
            if auto_height:
                self.bind(minimum_height=self.setter("height"))

        def set_bg_color(self, rgba: Tuple[float, float, float, float]) -> None:
            if hasattr(self, "_bg_color_instr"):
                self._bg_color_instr.rgba = rgba
            else:
                _apply_bg_color(self, rgba)

    class KivyGridLayout(_NativeGridLayout):
        def __init__(self, cols: int = 1, rows: Optional[int] = None, **kwargs: Any) -> None:
            kwargs.setdefault("spacing", 0)
            wid, _, bg_color, clean = _clean_kwargs(kwargs)
            super().__init__(cols=cols, rows=rows, **clean)
            self.id = wid
            _apply_bg_color(self, bg_color)

    class KivyScrollView(_NativeScrollView):
        """
        Mouse-draggable and touch-scrollable ScrollView with hidden scrollbars (`bar_width=0`).
        Supports both vertical and horizontal scrolling cleanly with OpenGL stencil clipping.
        """

        def __init__(self, **kwargs: Any) -> None:
            kwargs.setdefault("bar_width", 0)
            kwargs.setdefault("scroll_type", ["content"])
            kwargs.setdefault("scroll_wheel_distance", 36)
            wid, _, bg_color, clean = _clean_kwargs(kwargs)
            super().__init__(**clean)
            self.id = wid
            _apply_bg_color(self, bg_color)

        def on_touch_down(self, touch: Any) -> bool:
            if self.collide_point(*touch.pos) and getattr(touch, "is_mouse_scrolling", False):
                if self.do_scroll_x and not self.do_scroll_y:
                    step = 0.08
                    if touch.button == "scrolldown":
                        self.scroll_x = min(1.0, self.scroll_x + step)
                        return True
                    if touch.button == "scrollup":
                        self.scroll_x = max(0.0, self.scroll_x - step)
                        return True
            return super().on_touch_down(touch)

    class KivyLabel(_NativeLabel):
        """
        Zero-feedback-loop Kivy Label with automatic sanitization of unsupported mobile glyphs.
        """

        def __init__(self, text: str = "", **kwargs: Any) -> None:
            wrap = bool(kwargs.pop("wrap", False))
            scrollable_x = bool(kwargs.pop("scrollable_x", False))
            wid, _, bg_color, clean = _clean_kwargs(kwargs)
            clean.setdefault("color", (0.93, 0.95, 0.97, 1.0))
            clean.setdefault("font_size", "12.5sp")

            if scrollable_x:
                clean["size_hint_x"] = None
            elif wrap:
                clean.setdefault("halign", "left")
                clean.setdefault("valign", "middle")

            super().__init__(text=_clean_mobile_display_text(text), **clean)
            self.id = wid
            _apply_bg_color(self, bg_color)

            if scrollable_x:
                def _on_tex_w(inst: Any, ts: Any) -> None:
                    pw = inst.parent.width if inst.parent else _native_dp(120.0)
                    target_w = max(float(pw), float(ts[0]) + _native_dp(16.0))
                    if abs(float(inst.width) - target_w) > _native_dp(2.0):
                        inst.width = target_w

                self.bind(texture_size=_on_tex_w)
            elif wrap:
                def _on_wrap_w(inst: Any, w: float) -> None:
                    target_tw = max(_native_dp(40.0), float(w) - _native_dp(10.0))
                    curr_tw = float(inst.text_size[0]) if (inst.text_size and inst.text_size[0]) else 0.0
                    if abs(curr_tw - target_tw) > _native_dp(2.0):
                        inst.text_size = (target_tw, None)

                self.bind(width=_on_wrap_w)

        def on_text(self, instance: Any, value: str) -> None:
            cleaned = _clean_mobile_display_text(value)
            if cleaned != value:
                self.text = cleaned

    class KivyScrollLabel(KivyScrollView):
        """
        Hardware stencil-clipped, touch/mouse-scrollable label container (`bar_width=0`).
        For `direction="horizontal"`, automatically chunks long strings (such as 60+ move game strips)
        into compact `_NativeLabel` segments inside a horizontal BoxLayout so no single label texture
        ever exceeds iOS/Android's 4096px `GL_MAX_TEXTURE_SIZE` limit (which previously caused long
        imported game move strips to render as a blank black bar on iPhone).
        """

        _CHUNK_MAX_CHARS = 75

        def __init__(
            self,
            text: str = "",
            direction: str = "horizontal",
            font_size: str = "12sp",
            bold: bool = False,
            color: Tuple[float, float, float, float] = (0.93, 0.95, 0.97, 1.0),
            **kwargs: Any,
        ) -> None:
            self._is_horiz = (direction == "horizontal")
            self._font_size = font_size
            self._bold = bold
            self._color = color
            self._raw_text = text
            kwargs.setdefault("do_scroll_x", self._is_horiz)
            kwargs.setdefault("do_scroll_y", not self._is_horiz)
            super().__init__(**kwargs)

            if self._is_horiz:
                self._horiz_box = _NativeBoxLayout(
                    orientation="horizontal",
                    size_hint=(None, 1.0),
                    spacing=_native_dp(8),
                    padding=(_native_dp(4), 0, _native_dp(8), 0),
                )
                self._horiz_box.bind(minimum_width=self._horiz_box.setter("width"))
                self.add_widget(self._horiz_box)
                self._rebuild_horizontal_chunks(text)
            else:
                self._inner_label = KivyLabel(
                    text=text,
                    wrap=True,
                    size_hint_y=None,
                    font_size=font_size,
                    bold=bold,
                    color=color,
                )

                def _on_v_tex(inst: Any, ts: Any) -> None:
                    target_h = max(float(self.height), float(ts[1]) + _native_dp(8.0))
                    if abs(float(inst.height) - target_h) > _native_dp(2.0):
                        inst.height = target_h

                self._inner_label.bind(texture_size=_on_v_tex)
                self.add_widget(self._inner_label)

        def _rebuild_horizontal_chunks(self, raw_value: str) -> None:
            cleaned = _clean_mobile_display_text(raw_value)
            self._horiz_box.clear_widgets()
            if not cleaned:
                cleaned = " "

            # Split into safe chunks <= _CHUNK_MAX_CHARS so each Label texture is < 1024px wide
            tokens = cleaned.split("   ") if "   " in cleaned else cleaned.split(" ")
            sep = "   " if "   " in cleaned else " "
            chunks: List[str] = []
            curr_parts: List[str] = []
            curr_len = 0
            active_chunk_idx = 0

            for tok in tokens:
                if not tok:
                    continue
                if curr_len + len(tok) + len(sep) > self._CHUNK_MAX_CHARS and curr_parts:
                    chunk_str = sep.join(curr_parts)
                    if ">" in chunk_str:
                        active_chunk_idx = len(chunks)
                    chunks.append(chunk_str)
                    curr_parts = [tok]
                    curr_len = len(tok)
                else:
                    curr_parts.append(tok)
                    curr_len += len(tok) + len(sep)
            if curr_parts:
                chunk_str = sep.join(curr_parts)
                if ">" in chunk_str:
                    active_chunk_idx = len(chunks)
                chunks.append(chunk_str)

            if not chunks:
                chunks = [cleaned]

            for ch_str in chunks:
                lbl = _NativeLabel(
                    text=ch_str,
                    font_size=self._font_size,
                    bold=self._bold,
                    color=self._color,
                    size_hint=(None, 1.0),
                    halign="left",
                    valign="middle",
                )

                def _upd_lbl_w(inst: Any, ts: Any) -> None:
                    tw = max(_native_dp(12.0), float(ts[0]) + _native_dp(4.0))
                    if abs(float(inst.width) - tw) > _native_dp(1.5):
                        inst.width = tw

                lbl.bind(texture_size=_upd_lbl_w)
                lbl.texture_update()
                lbl.width = max(_native_dp(12.0), float(lbl.texture_size[0]) + _native_dp(4.0))
                self._horiz_box.add_widget(lbl)

            # Auto-scroll horizontally to keep the active move (`>`) visible when stepping through a long game
            if len(chunks) > 1 and ">" in cleaned:
                ratio = active_chunk_idx / float(max(1, len(chunks) - 1))
                self.scroll_x = max(0.0, min(1.0, ratio))

        @property
        def text(self) -> str:
            return self._raw_text if self._is_horiz else self._inner_label.text

        @text.setter
        def text(self, value: str) -> None:
            if self._is_horiz:
                if self._raw_text == value:
                    return
                self._raw_text = value
                self._rebuild_horizontal_chunks(value)
            else:
                if self._inner_label.text == value:
                    return
                self._inner_label.text = value

    class KivyButton(_NativeButton):
        def __init__(
            self,
            text: str = "",
            on_release: Optional[Callable[..., None]] = None,
            icon_path: Optional[str] = None,
            wrap_text: bool = False,
            **kwargs: Any,
        ) -> None:
            wid, kw_rel, bg_color, clean = _clean_kwargs(kwargs)
            clean.setdefault("background_normal", "")
            clean.setdefault("background_color", bg_color or (0.18, 0.24, 0.32, 1.0))
            clean.setdefault("color", (0.96, 0.97, 0.99, 1.0))
            clean.setdefault("font_size", "11.5sp")
            clean.setdefault("bold", True)
            if wrap_text:
                clean.setdefault("halign", "center")
                clean.setdefault("valign", "middle")
            super().__init__(text=_clean_mobile_display_text(text), **clean)
            self.id = wid
            self.icon_path = icon_path
            self._icon_img: Optional[_NativeImage] = None
            self._release_callbacks: List[Callable[..., None]] = []

            if icon_path and Path(icon_path).exists():
                self._icon_img = _NativeImage(
                    source=icon_path,
                    allow_stretch=True,
                    keep_ratio=True,
                )
                self.add_widget(self._icon_img)

                def _upd_icon(inst: Any, _val: Any) -> None:
                    if inst._icon_img is not None:
                        ico_sz = min(inst.height * 0.56, _native_dp(22))
                        inst._icon_img.size = (ico_sz, ico_sz)
                        inst._icon_img.pos = (
                            inst.x + _native_dp(12),
                            inst.y + (inst.height - ico_sz) * 0.5,
                        )

                self.bind(pos=_upd_icon, size=_upd_icon)
                _upd_icon(self, None)

            if wrap_text:
                def _upd_btn_wrap(inst: Any, w: float) -> None:
                    target_tw = max(_native_dp(40.0), float(w) - _native_dp(12.0))
                    curr_tw = float(inst.text_size[0]) if (inst.text_size and inst.text_size[0]) else 0.0
                    if abs(curr_tw - target_tw) > _native_dp(2.0):
                        inst.text_size = (target_tw, None)

                self.bind(width=_upd_btn_wrap)

            cb = on_release or kw_rel
            if cb is not None:
                self.bind(on_release=cb)

        def on_text(self, instance: Any, value: str) -> None:
            cleaned = _clean_mobile_display_text(value)
            if cleaned != value:
                self.text = cleaned

        def bind(self, **kwargs: Callable[..., None]) -> None:
            if "on_release" in kwargs:
                self._release_callbacks.append(kwargs["on_release"])
            super().bind(**kwargs)

        def trigger_release(self) -> None:
            if self.disabled:
                return
            for cb in list(self._release_callbacks):
                cb(self)

    class KivyIconButton(_NativeButtonBehavior, _NativeWidget):
        def __init__(
            self,
            icon_path: Optional[str] = None,
            text: str = "",
            is_selected: bool = False,
            bg_color: Optional[Tuple[float, float, float, float]] = None,
            on_release: Optional[Callable[..., None]] = None,
            **kwargs: Any,
        ) -> None:
            wid, kw_rel, _, clean = _clean_kwargs(kwargs)
            super().__init__(**clean)
            self.id = wid
            self.icon_path = icon_path
            self.text = text or (Path(icon_path).stem if icon_path else "")
            self.is_selected = is_selected
            self._release_callbacks: List[Callable[..., None]] = []
            self._img: Optional[_NativeImage] = None
            self._lbl: Optional[_NativeLabel] = None

            fill_rgba = bg_color or ((0.28, 0.46, 0.32, 1.0) if is_selected else (0.18, 0.22, 0.28, 1.0))
            with self.canvas.before:
                self._bg_col = _NativeColor(*fill_rgba)
                self._bg_rect = _NativeRectangle(pos=self.pos, size=self.size)
                self._border_col = _NativeColor(*((0.96, 0.82, 0.25, 1.0) if is_selected else (0.28, 0.33, 0.40, 1.0)))
                self._border_line = _NativeLine(
                    rectangle=(self.x + 1, self.y + 1, max(4, self.width - 2), max(4, self.height - 2)),
                    width=1.8 if is_selected else 1.0,
                )

            if icon_path and Path(icon_path).exists():
                self._img = _NativeImage(source=icon_path, allow_stretch=True, keep_ratio=True)
                self.add_widget(self._img)
            else:
                self._lbl = _NativeLabel(text=_clean_mobile_display_text(text), bold=True, font_size="11sp")
                self.add_widget(self._lbl)

            def _upd(inst: Any, _val: Any) -> None:
                inst._bg_rect.pos = inst.pos
                inst._bg_rect.size = inst.size
                inst._border_line.rectangle = (
                    inst.x + 1,
                    inst.y + 1,
                    max(4, inst.width - 2),
                    max(4, inst.height - 2),
                )
                if inst._img is not None:
                    inst._img.pos = (inst.x + inst.width * 0.12, inst.y + inst.height * 0.12)
                    inst._img.size = (inst.width * 0.76, inst.height * 0.76)
                if inst._lbl is not None:
                    inst._lbl.pos = inst.pos
                    inst._lbl.size = inst.size

            self.bind(pos=_upd, size=_upd)
            _upd(self, None)

            cb = on_release or kw_rel
            if cb is not None:
                self.bind(on_release=cb)
                self._release_callbacks.append(cb)

        def set_selected(self, selected: bool) -> None:
            self.is_selected = selected
            self._bg_col.rgba = (0.28, 0.46, 0.32, 1.0) if selected else (0.18, 0.22, 0.28, 1.0)
            self._border_col.rgba = (0.96, 0.82, 0.25, 1.0) if selected else (0.28, 0.33, 0.40, 1.0)

        def trigger_release(self) -> None:
            if self.disabled:
                return
            for cb in list(self._release_callbacks):
                cb(self)

    class KivySquareCell(_NativeButtonBehavior, _NativeWidget):
        def __init__(
            self,
            square_name: str,
            bg_rgba: Tuple[float, float, float, float],
            piece_png_path: Optional[str] = None,
            coord_text: str = "",
            coord_color: Tuple[float, float, float, float] = (0.1, 0.1, 0.1, 0.8),
            marker_type: str = "",
            on_release: Optional[Callable[..., None]] = None,
            **kwargs: Any,
        ) -> None:
            wid, kw_rel, _, clean = _clean_kwargs(kwargs)
            super().__init__(**clean)
            self.id = wid or f"sq_{square_name}"
            self.square_name = square_name
            self.text = f"{square_name}:{Path(piece_png_path).stem if piece_png_path else ''}{marker_type}"
            self._release_callbacks: List[Callable[..., None]] = []
            self._img: Optional[_NativeImage] = None
            self._lbl: Optional[_NativeLabel] = None

            with self.canvas.before:
                self._sq_color = _NativeColor(*bg_rgba)
                self._sq_rect = _NativeRectangle(pos=self.pos, size=self.size)
                if marker_type == "dot":
                    self._dot_color = _NativeColor(0.14, 0.38, 0.18, 0.55)
                    self._dot_rect = _NativeRectangle(
                        pos=(self.x + self.width * 0.36, self.y + self.height * 0.36),
                        size=(self.width * 0.28, self.height * 0.28),
                    )
                elif marker_type == "capture":
                    self._cap_color = _NativeColor(0.85, 0.22, 0.20, 0.80)
                    self._cap_line = _NativeLine(
                        rectangle=(self.x + 2, self.y + 2, max(4, self.width - 4), max(4, self.height - 4)),
                        width=2.2,
                    )

            if piece_png_path:
                self._img = _NativeImage(
                    source=piece_png_path,
                    allow_stretch=True,
                    keep_ratio=True,
                )
                self.add_widget(self._img)

            if coord_text:
                self._lbl = _NativeLabel(
                    text=coord_text,
                    color=coord_color,
                    font_size="9sp",
                    bold=True,
                )
                self.add_widget(self._lbl)

            def _upd(inst: Any, _val: Any) -> None:
                inst._sq_rect.pos = inst.pos
                inst._sq_rect.size = inst.size
                if hasattr(inst, "_dot_rect"):
                    inst._dot_rect.pos = (inst.x + inst.width * 0.36, inst.y + inst.height * 0.36)
                    inst._dot_rect.size = (inst.width * 0.28, inst.height * 0.28)
                if hasattr(inst, "_cap_line"):
                    inst._cap_line.rectangle = (
                        inst.x + 2,
                        inst.y + 2,
                        max(4, inst.width - 4),
                        max(4, inst.height - 4),
                    )
                if inst._img is not None:
                    inst._img.pos = (inst.x + inst.width * 0.07, inst.y + inst.height * 0.07)
                    inst._img.size = (inst.width * 0.86, inst.height * 0.86)
                if inst._lbl is not None:
                    pad_x = _native_dp(2)
                    pad_y = _native_dp(14)
                    inst._lbl.pos = (inst.x + pad_x, inst.top - pad_y)
                    inst._lbl.size = (_native_dp(18), _native_dp(12))

            self.bind(pos=_upd, size=_upd)
            _upd(self, None)

            cb = on_release or kw_rel
            if cb is not None:
                self.bind(on_release=cb)
                self._release_callbacks.append(cb)

        def trigger_release(self) -> None:
            if self.disabled:
                return
            for cb in list(self._release_callbacks):
                cb(self)

    class KivyTextInput(_NativeTextInput):
        def __init__(self, text: str = "", hint_text: str = "", **kwargs: Any) -> None:
            wid, _, _, clean = _clean_kwargs(kwargs)
            clean.setdefault("multiline", False)
            clean.setdefault("background_color", (0.14, 0.17, 0.22, 1.0))
            clean.setdefault("foreground_color", (0.95, 0.97, 1.0, 1.0))
            clean.setdefault("cursor_color", (0.35, 0.65, 1.0, 1.0))
            clean.setdefault("font_size", "12.5sp")
            super().__init__(text=text, hint_text=hint_text, **clean)
            self.id = wid

    class KivyScreen(_NativeScreen):
        def __init__(self, name: str = "", **kwargs: Any) -> None:
            wid, _, bg_color, clean = _clean_kwargs(kwargs)
            super().__init__(name=name, **clean)
            self.id = wid
            if _IS_IOS:
                screen_pad: Any = (6, 44, 6, 20)
            elif _IS_ANDROID:
                screen_pad = (6, 12, 6, 10)
            else:
                screen_pad = 6
            self._layout = KivyBoxLayout(
                orientation="vertical",
                padding=screen_pad,
                spacing=4,
                bg_color=bg_color or (0.09, 0.11, 0.14, 1.0),
            )
            super().add_widget(self._layout)

        def add_widget(self, widget: Any, *args: Any, **kwargs: Any) -> None:
            if hasattr(self, "_layout") and widget is not self._layout:
                self._layout.add_widget(widget, *args, **kwargs)
            else:
                super().add_widget(widget, *args, **kwargs)

    class KivyScreenManager(_NativeScreenManager):
        def __init__(self, **kwargs: Any) -> None:
            kwargs.setdefault("transition", _NativeNoTransition())
            super().__init__(**kwargs)

    class KivyBaseApp(_NativeApp):
        title = "Analyze This • Python Chess Analyzer"

except ImportError:
    USING_NATIVE_KIVY = False
    KivyWindow = None

    def KivyDP(val: float) -> float:
        return float(val)

    class KivyClock:
        @staticmethod
        def schedule_once(callback: Callable[[float], Any], timeout: float = 0.0) -> None:
            callback(timeout)

    class KivyWidget:
        def __init__(self, **kwargs: Any) -> None:
            self.children: List["KivyWidget"] = []
            self.parent: Optional["KivyWidget"] = None
            self.disabled: bool = bool(kwargs.get("disabled", False))
            self.opacity: float = float(kwargs.get("opacity", 1.0))
            self.id: Optional[str] = kwargs.get("id")
            self._bindings: Dict[str, List[Callable[..., None]]] = {}
            for k, v in kwargs.items():
                setattr(self, k, v)

        def add_widget(self, widget: "KivyWidget") -> None:
            widget.parent = self
            self.children.append(widget)

        def remove_widget(self, widget: "KivyWidget") -> None:
            if widget in self.children:
                self.children.remove(widget)
                widget.parent = None

        def clear_widgets(self) -> None:
            for c in self.children:
                c.parent = None
            self.children.clear()

        def bind(self, **kwargs: Callable[..., None]) -> None:
            for event_name, cb in kwargs.items():
                self._bindings.setdefault(event_name, []).append(cb)

        def trigger_event(self, event_name: str, *args: Any) -> None:
            if self.disabled:
                return
            for cb in self._bindings.get(event_name, []):
                cb(self, *args)

    class KivyBoxLayout(KivyWidget):
        def __init__(self, orientation: str = "vertical", auto_height: bool = False, **kwargs: Any) -> None:
            super().__init__(orientation=orientation, **kwargs)

        def set_bg_color(self, rgba: Tuple[float, float, float, float]) -> None:
            self.bg_color = rgba

    class KivyGridLayout(KivyWidget):
        def __init__(self, cols: int = 1, rows: Optional[int] = None, **kwargs: Any) -> None:
            super().__init__(cols=cols, rows=rows, **kwargs)

    class KivyScrollView(KivyWidget):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.scroll_x: float = 0.0
            self.scroll_y: float = 1.0

    class KivyLabel(KivyWidget):
        def __init__(self, text: str = "", **kwargs: Any) -> None:
            super().__init__(text=text, **kwargs)

    class KivyScrollLabel(KivyLabel):
        def __init__(self, text: str = "", direction: str = "horizontal", **kwargs: Any) -> None:
            super().__init__(text=text, **kwargs)
            self.direction = direction

    class KivyButton(KivyLabel):
        def __init__(
            self,
            text: str = "",
            on_release: Optional[Callable[..., None]] = None,
            icon_path: Optional[str] = None,
            wrap_text: bool = False,
            **kwargs: Any,
        ) -> None:
            super().__init__(text=text, **kwargs)
            self.icon_path = icon_path
            self.wrap_text = wrap_text
            if on_release is not None:
                self.bind(on_release=on_release)

        def trigger_release(self) -> None:
            self.trigger_event("on_release")

    class KivyIconButton(KivyButton):
        def __init__(
            self,
            icon_path: Optional[str] = None,
            text: str = "",
            is_selected: bool = False,
            on_release: Optional[Callable[..., None]] = None,
            **kwargs: Any,
        ) -> None:
            label_txt = text or (Path(icon_path).stem if icon_path else "")
            super().__init__(text=label_txt, on_release=on_release, icon_path=icon_path, **kwargs)
            self.icon_path = icon_path
            self.is_selected = is_selected

        def set_selected(self, selected: bool) -> None:
            self.is_selected = selected

    class KivySquareCell(KivyButton):
        def __init__(
            self,
            square_name: str,
            bg_rgba: Tuple[float, float, float, float],
            piece_png_path: Optional[str] = None,
            coord_text: str = "",
            coord_color: Tuple[float, float, float, float] = (0.1, 0.1, 0.1, 0.8),
            marker_type: str = "",
            on_release: Optional[Callable[..., None]] = None,
            **kwargs: Any,
        ) -> None:
            piece_tag = Path(piece_png_path).stem if piece_png_path else ""
            super().__init__(
                text=f"{square_name}:{piece_tag}:{marker_type}",
                id=kwargs.pop("id", f"sq_{square_name}"),
                on_release=on_release,
                **kwargs,
            )
            self.square_name = square_name
            self.piece_png_path = piece_png_path
            self.marker_type = marker_type

    class KivyTextInput(KivyWidget):
        def __init__(self, text: str = "", hint_text: str = "", **kwargs: Any) -> None:
            super().__init__(text=text, hint_text=hint_text, **kwargs)

    class KivyScreen(KivyBoxLayout):
        def __init__(self, name: str = "", **kwargs: Any) -> None:
            super().__init__(name=name, **kwargs)
            self.name = name
            self.manager: Optional["KivyScreenManager"] = None

        def on_pre_enter(self) -> None:
            pass

    class KivyScreenManager(KivyWidget):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._screens: Dict[str, KivyScreen] = {}
            self._current: str = ""

        def add_widget(self, screen: KivyScreen) -> None:  # type: ignore[override]
            super().add_widget(screen)
            self._screens[screen.name] = screen
            screen.manager = self
            if not self._current:
                self._current = screen.name

        @property
        def current(self) -> str:
            return self._current

        @current.setter
        def current(self, name: str) -> None:
            if name not in self._screens:
                raise KeyError(f"Screen '{name}' not registered.")
            self._current = name
            self._screens[name].on_pre_enter()

        def get_screen(self, name: str) -> KivyScreen:
            return self._screens[name]

    class KivyBaseApp:
        def build(self) -> KivyWidget:
            return KivyWidget()
