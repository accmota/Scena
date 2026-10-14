import glfw
import skia
import sys
import time
from typing import Any, Optional, Union
import inspect
import math
import warnings

from .entity import Entity
from .input import Mouse, _PUNCT_KEYS
from .state import ContainerSlot, Attribute, as_payload, bound_cell, unbound_value_hint
from .color import Color
from .validate import expect_bool as _expect_flag
from .closed import ClosedSurface


# Compact chrome at ui.scale == 1. Positions (top_left=) and explicit width /
# height / font_size / size stay in design units; these metrics scale.
_UI_FONT_SIZE = 13.0
_UI_ROW_HEIGHT = 28.0
_UI_CHECKBOX_SIZE = 18.0
_UI_DEFAULT_WIDTH = 260.0
_UI_STACK_GAP = 12.0
_UI_CORNER_RADIUS = 4.0
_UI_CARD_PADDING = 4.0
_UI_LINE_WIDTH = 1.5
_UI_LINE_WIDTH_THICK = 2.25
_UI_SLIDER_BAR = 3.0
_UI_SLIDER_BAR_HOVER = 5.0
_UI_SLIDER_HANDLE = 7.0
_UI_SLIDER_MARGIN = 8.0
_UI_SLIDER_VALUE_SPACE = 36.0
_UI_MIN_LABEL_SPACE = 50.0
_UI_CONTROL_PAD = 5.0
_UI_ARROW_WIDTH = 8.0
_UI_ARROW_HEIGHT = 5.0

# First available family wins. Hidden macOS UI font, then Windows, then
# common Linux faces, then Arial (Mac/Windows, some Linux).
_UI_FONT_CANDIDATES = (
    ".AppleSystemUIFont",
    "Segoe UI",
    "Ubuntu",
    "Cantarell",
    "Noto Sans",
    "DejaVu Sans",
    "Liberation Sans",
    "Arial",
    "Helvetica",
)

_fallback_typeface_cache: dict[tuple[int, int], object] = {}
_run_font_cache: dict[tuple[int, float], object] = {}


def _make_ui_font(typeface, size: float):
    font = skia.Font(typeface, size)
    font.setEdging(skia.Font.kAntiAlias)
    font.setSubpixel(True)
    return font


def _try_family(mgr, name: str):
    tf = mgr.matchFamilyStyle(name, skia.FontStyle.Normal())
    if tf is None:
        return None
    resolved = tf.getFamilyName()
    if resolved.lower() == name.lower():
        return tf
    if name.startswith(".") and resolved:
        return tf
    return None


def resolve_ui_typeface(family: str | None = None):
    """Pick a UI typeface. ``family`` is an optional author override."""
    mgr = skia.FontMgr.RefDefault()
    if family:
        tf = _try_family(mgr, family)
        if tf is not None:
            return tf
        from .process import report_author_warning
        report_author_warning(
            "font",
            f"{family!r} is not installed; using the default UI typeface.",
        )
    for name in _UI_FONT_CANDIDATES:
        tf = _try_family(mgr, name)
        if tf is not None:
            return tf
    return skia.Typeface.MakeDefault()


_typeface_cache: dict[str, object] = {}


def _is_font_file(spec: str) -> bool:
    low = spec.lower()
    return low.endswith(".ttf") or low.endswith(".otf")


def resolve_typeface(spec: str | None):
    """Typeface for ``ui.font`` / ``Text.font`` / ``Menu.font``.

    A ``.ttf`` / ``.otf`` path is loaded from that file (same search as images).
    Anything else is an installed family name. Missing file or family: one
    SCENA WARNING and the default UI typeface.
    """
    if spec is None or spec == "":
        return resolve_ui_typeface(None)
    spec = str(spec)
    hit = _typeface_cache.get(spec)
    if hit is not None:
        return hit
    if _is_font_file(spec):
        from .sprite import _resolve_image_path
        path = _resolve_image_path(spec)
        tf = skia.Typeface.MakeFromFile(path) if path else None
        if tf is None:
            from .process import report_author_warning
            report_author_warning(
                "font",
                f"{spec!r} was not found; using the default typeface.",
            )
            tf = resolve_ui_typeface(None)
    else:
        tf = resolve_ui_typeface(spec)
    _typeface_cache[spec] = tf
    return tf


def _typeface_for_char(primary, char: str):
    """Typeface that has ``char``, falling back via the system FontMgr."""
    cp = ord(char)
    if primary.unicharToGlyph(cp):
        return primary
    key = (primary.uniqueID(), cp)
    hit = _fallback_typeface_cache.get(key)
    if hit is not None:
        return hit
    mgr = skia.FontMgr.RefDefault()
    tf = mgr.matchFamilyStyleCharacter(
        primary.getFamilyName(),
        primary.fontStyle(),
        ["en"],
        cp,
    )
    found = tf if (tf is not None and tf.unicharToGlyph(cp)) else primary
    _fallback_typeface_cache[key] = found
    return found


def _font_with_typeface(font, typeface):
    primary = font.getTypeface()
    if primary is not None and primary.uniqueID() == typeface.uniqueID():
        return font
    key = (typeface.uniqueID(), font.getSize())
    cached = _run_font_cache.get(key)
    if cached is not None:
        return cached
    run_font = _make_ui_font(typeface, font.getSize())
    _run_font_cache[key] = run_font
    return run_font


def iter_font_runs(font, text: str):
    """Yield ``(substring, font)`` runs so missing glyphs use a fallback face."""
    if not text:
        return
    primary = font.getTypeface()
    if primary is None:
        yield text, font
        return
    run_tf = _typeface_for_char(primary, text[0])
    start = 0
    for i in range(1, len(text)):
        tf = _typeface_for_char(primary, text[i])
        if tf.uniqueID() != run_tf.uniqueID():
            yield text[start:i], _font_with_typeface(font, run_tf)
            run_tf = tf
            start = i
    yield text[start:], _font_with_typeface(font, run_tf)


def measure_text(font, text) -> float:
    """Advance width with the same fallback runs as ``draw_string_upright``."""
    s = str(text) if text is not None else ""
    if not s:
        return 0.0
    width = 0.0
    for run, run_font in iter_font_runs(font, s):
        width += run_font.measureText(run)
    return width


def text_line_height(font) -> float:
    """Tight glyph box height: ascent + descent (Skia ``fAscent`` is negative)."""
    metrics = font.getMetrics()
    return float(-metrics.fAscent + metrics.fDescent)


def build_upright_text_path(text, x: float, y: float, font) -> skia.Path:
    """Glyph outlines in y-up space (baseline at ``y``, left at ``x``).

    Skia glyph paths are y-down from the baseline; this flips them so fills
    share the same local frame as Shape ``Gradient`` / ``GlowFilter`` hosts.
    """
    out = skia.Path()
    s = "" if text is None else str(text)
    if not s:
        return out
    x_off = 0.0
    for run, run_font in iter_font_runs(font, s):
        glyphs = run_font.textToGlyphs(run)
        if not glyphs:
            continue
        widths = run_font.getWidths(glyphs)
        for i, g in enumerate(glyphs):
            gp = run_font.getPath(g)
            adv = float(widths[i]) if i < len(widths) else float(run_font.measureText(run[i:i+1]))
            if gp is not None and not gp.isEmpty():
                m = skia.Matrix()
                m.setScale(1.0, -1.0)
                m.postTranslate(float(x) + x_off, float(y))
                out.addPath(gp, m)
            x_off += adv
    return out


def _paint_for_upright_string(paint, x: float, y: float):
    """Re-anchor auto-fit shaders after ``translate(x, y) · scale(1, -1)``.

    Prefer :func:`build_upright_text_path` + ``drawPath`` for Shape-like
    materials. This keeps ``draw_string_upright`` correct for widget chrome.
    """
    shader = paint.getShader()
    if shader is None:
        return paint
    out = skia.Paint(paint)
    m = skia.Matrix()
    m.setTranslate(-float(x), -float(y))
    m.preScale(1.0, -1.0)
    if hasattr(shader, "makeWithLocalMatrix"):
        out.setShader(shader.makeWithLocalMatrix(m))
    return out


def draw_string_upright(canvas, text, x, y, font, paint):
    """Draw text upright in y-up authoring space (view CTM includes flipY).

    ``y`` is the baseline in world coordinates. Glyphs extend toward +y (visual up);
    descent extends toward -y. Missing glyphs in the UI face are drawn with a
    fallback typeface (Skia's ``drawString`` does not substitute).
    """
    s = "" if text is None else str(text)
    paint = _paint_for_upright_string(paint, x, y)
    canvas.save()
    canvas.translate(x, y)
    canvas.scale(1, -1)
    x_off = 0.0
    for run, run_font in iter_font_runs(font, s):
        canvas.drawString(run, x_off, 0, run_font, paint)
        x_off += run_font.measureText(run)
    canvas.restore()


def text_baseline_in_box(y_min: float, height: float, font) -> float:
    """Baseline so glyphs tightly fill ``[y_min, y_min+height]`` when height is
    :func:`text_line_height` (ascent + descent).

    Skia ``fAscent`` is negative; top of ink is ``baseline - fAscent``.
    """
    metrics = font.getMetrics()
    return float(y_min) + float(height) + float(metrics.fAscent)


def text_baseline_centered(y_min: float, height: float, font) -> float:
    """Baseline Y so glyphs look vertically centered in ``[y_min, y_min+height]`` (y-up).

    Centers on the ascent extent (Skia ``fAscent`` is negative). Ignoring descent
    matches UI label optics better than the full ascent+descent box.
    """
    metrics = font.getMetrics()
    return y_min + height * 0.5 + metrics.fAscent * 0.5


def text_baseline_from_bottom(y_min: float, font, padding: float = 8.0) -> float:
    """Baseline near the bottom of a box, clearing descent (y-up)."""
    metrics = font.getMetrics()
    return y_min + padding + metrics.fDescent


# Widget Design overview:
# 
# WidgetManager class manages the mouse and keyboard interaction and sends the proper events to UIWidget classes.
# Every UIWidget object has access to the WidgetManager through its _widget_manager property (set by the WidgetManager upon registering an UIWidget)
# 
# These are the events sent by WidgetManager to UIWidget objects and their dynamics:
# 
#   on_mouse_move
#     - a widget receives this event if the mouse is hovering over it
#     - if there is another widget where the mouse button was pressed down and not yet released, that widget will also receive an on_mouse_move event
#   
#   on_mouse_down
#     - always called when mouse button was pressed over the widget (defined by the widget method contains_point)
#     - if called, it means the mouse pos (x, y) was over the widget when the button was pressed
#   
#   on_mouse_up
#     - the event is always sent to the widget where the mouse was pressed down, not necessarily the widget the mouse was over when the mouse button was released
#   
#   on_mouse_click
#     - the event is sent to the widget if the mouse was pressed down and up on the same widget
#   
#   on_mouse_double_click
#     - the event is sent to the widget if two near clicks are detected (in time and space)
#     - note that the two individual click events are also sent to the widget
#   
#   on_mouse_drag
#     - if the mouse left button was pressed over a widget and not released yet, any mouse movement (inside and outside the widget area) will be sent as an on_mouse_drag event
#   
#   on_mouse_scroll
#     - sent when mouse wheel is scrolled while hovering over the widget
#   
#   on_key_down
#     - sent to the focused widget when a key is pressed
#   
#   on_key_up
#     - sent to the focused widget when a key is released
#   
#   on_key
#     - sent to the focused widget for continuous key press events (PRESSED or REPEATED)
#   
#   on_char
#     - sent to the focused widget when a character is typed
#     - handles actual text input, including special characters
#   
#   draw
#     - called to render the widget on the canvas
#     - must be implemented by all widget subclasses
#   
#   on_focus_gained
#     - called when the widget gains focus
#   
#   on_focus_lost
#     - called when the widget loses focus
#   
#   contains_point
#     - determines if a point (x,y) is within the widget's bounds
#     - used for hit testing and event routing
# 
# UIWidget object properties managed by WidgetManager:
# 
#   _widget_manager: reference to allow widgets to call WidgetManager methods
#
#   visible: if False, WidgetManager will not draw it nor send any events
#            (same flag as Entity.visible; hiding also drops focus and hover)
#   
#   has_focus: indicates the widget has keyboard focus
#   
#   pressed: True when mouse is pressed on widget, False when released
#
#   is_mouse_over: True when mouse is over widget, False when not
#
# Common widget patterns:
#   - All widgets should update their bounds (_x1,_y1,_x2,_y2) in their constructor
#   - Widgets that need keyboard input should set handle_key = True
#   - Most widgets support callbacks like on_click; for value-change callbacks, use @on_change over the data Attribute
#   - .data is the widget's graph cell (identity-bind target). .value unwraps it to a Python payload.
#   - Domain aliases (CheckBox.checked) return that same Attribute so they can take @=.
#     TextInput.text is the edit buffer (plain str), not the cell — Enter / Tab / focus loss commit it
#     to .data, but only when it differs from the cell's own text at focus time.
#   - Modifier keys for the key being dispatched are in WidgetManager._key_mods (GLFW bits).


class UiSettings(ClosedSurface):
    """Author-facing UI chrome: one scale, one font family, HUD column cursor.

    Live properties (like ``canvas.fx_quality``): assign anytime; set before
    constructing widgets (layout is construct-time). ``init()`` does not wipe
    them; pass ``ui_scale=`` / ``ui_font=`` on ``init()`` to write them in the
    same call. ``stack_reset`` / ``stack_origin`` / ``stack_from`` /
    ``stack_column`` move the shared HUD column (widgets + view ``Text``).
    ``gap`` inserts one extra theme gap before the next omitted-y item.

    ``min_label_space`` is the unscaled floor (design units at ``ui.scale==1``)
    for the Slider label column; the theme multiplies it by ``ui.scale``.
    Next widgets pick up a write; existing ones keep the snapshot they
    constructed with.
    """

    _closed_who = "ui"

    def __init__(self):
        self._scale = 1.0
        self._font = None
        self._min_label_space = _UI_MIN_LABEL_SPACE

    def _reset(self, scale: float = 1.0, font: str | None = None) -> None:
        s = float(scale)
        if s <= 0:
            raise ValueError("ui.scale must be > 0")
        self._scale = s
        self._font = None if font is None or font == "" else str(font)

    @property
    def scale(self) -> float:
        """Size multiplier for every widget (1 = theme size). Set before creating widgets."""
        return self._scale

    @scale.setter
    def scale(self, value) -> None:
        from .validate import number
        s = number(value, "ui.scale")
        if s <= 0:
            raise ValueError("ui.scale must be > 0")
        self._scale = s

    @property
    def font(self) -> str | None:
        """Requested family name, or ``None`` for the platform UI stack."""
        return self._font

    @font.setter
    def font(self, value) -> None:
        if value is None or value == "":
            self._font = None
            return
        self._font = str(value)

    @property
    def min_label_space(self) -> float:
        """Unscaled floor for the Slider label column (theme × ``ui.scale``)."""
        return self._min_label_space

    @min_label_space.setter
    def min_label_space(self, value) -> None:
        from .validate import number
        v = number(value, "ui.min_label_space")
        if v < 0:
            raise ValueError("ui.min_label_space must be >= 0")
        self._min_label_space = v

    def _widget_manager(self):
        try:
            from .orchestration import ScenaFramework
            fw = ScenaFramework.get_instance()
            return getattr(fw, "widget_manager", None)
        except Exception:
            return None

    def stack_reset(self) -> None:
        """Next omitted-y HUD item uses the default top-left origin."""
        wm = self._widget_manager()
        if wm is not None:
            wm.reset_hud_stack()

    def stack_origin(self, x, y=None) -> None:
        """Next omitted HUD item's visual top-left is ``(x, y)``.

        ``stack_origin(x, y)`` or one point-like (``stack_origin(p)``), same
        rule as ``move_to``.
        """
        from .scenamath import _as_xy
        from .validate import number
        if y is None:
            try:
                x, y = _as_xy(as_payload(x))
            except (TypeError, ValueError, AttributeError):
                raise TypeError(
                    f"ui.stack_origin takes (x, y) or one point, got {x!r}"
                ) from None
        x = number(as_payload(x), "ui.stack_origin x")
        y = number(as_payload(y), "ui.stack_origin y")
        wm = self._widget_manager()
        if wm is not None:
            wm.set_hud_stack_origin(x, y)

    def stack_from(self, item) -> None:
        """Next omitted-y HUD item stacks below this view box (theme gap applies)."""
        wm = self._widget_manager()
        if wm is not None:
            wm.adopt_hud_box(item._x1, item._y1, clear_extra=True)
            wm._note_column_extent(item)

    def stack_column(self, gap=None) -> None:
        """Next omitted-y HUD item starts a new column: same visual top, x past this one.

        ``gap`` is extra space between columns; omit it to use the theme stack gap.
        Clears a pending ``ui.gap`` and closes the Slider label-column run.
        """
        wm = self._widget_manager()
        if wm is not None:
            wm.advance_hud_column(gap)

    def gap(self) -> None:
        """Insert one extra theme gap before the next omitted-y HUD item.

        Also closes the current Slider label-column alignment run.
        """
        wm = self._widget_manager()
        if wm is not None:
            wm.add_space_separator()


ui = UiSettings()


class WidgetTheme:
    """Internal paint kit. Not an author-facing theme API.

    Layout metrics are the compact base × ``ui.scale``. Call ``_ensure()``
    before reading fonts, paints, or sizes so a late ``ui.scale`` / ``ui.font``
    / ``ui.min_label_space`` write is picked up.
    """

    def __init__(self, pixel_ratio=1.0):
        # Informational only: layout and hit-testing use design-space points.
        # Physical pixels are applied by the Skia CTM (view_scale * pixel_ratio)
        # in orchestration.
        self.pixel_ratio = pixel_ratio if pixel_ratio else 1.0
        self._cache_key = None
        self._rebuild()

    def _ensure(self) -> None:
        key = (ui.scale, ui.font, ui.min_label_space)
        if key != self._cache_key:
            self._rebuild()

    def _rebuild(self) -> None:
        s = ui.scale
        self._cache_key = (ui.scale, ui.font, ui.min_label_space)

        self.font_size = _UI_FONT_SIZE * s
        self.row_height = _UI_ROW_HEIGHT * s
        self.checkbox_size = _UI_CHECKBOX_SIZE * s
        self.default_width = _UI_DEFAULT_WIDTH * s
        self.stack_gap = _UI_STACK_GAP * s
        self.line_width_normal = _UI_LINE_WIDTH * s
        self.line_width_thick = _UI_LINE_WIDTH_THICK * s
        self.corner_radius = _UI_CORNER_RADIUS * s
        self.card_padding = _UI_CARD_PADDING * s
        self.slider_bar_width = _UI_SLIDER_BAR * s
        self.slider_bar_width_hover = _UI_SLIDER_BAR_HOVER * s
        self.slider_handle_radius = _UI_SLIDER_HANDLE * s
        self.slider_margin = _UI_SLIDER_MARGIN * s
        self.slider_value_space = _UI_SLIDER_VALUE_SPACE * s
        self.min_label_space = ui.min_label_space * s
        self.control_pad = _UI_CONTROL_PAD * s
        self.arrow_width = _UI_ARROW_WIDTH * s
        self.arrow_height = _UI_ARROW_HEIGHT * s

        self.typeface = resolve_typeface(ui.font)
        self.default_font = _make_ui_font(self.typeface, self.font_size)

        # Palette (RGB 0–255)
        bg = (20, 22, 28)
        hover = (30, 45, 100)
        pressed = (0, 60, 130)
        invalid = (100, 0, 0)
        accent = (0, 90, 200)
        accent_hi = (30, 120, 240)
        accent_mid = (40, 110, 230)
        accent_dim = (0, 40, 120)
        text = (200, 200, 200)
        text_hi = (230, 240, 255)
        text_dim = (128, 128, 128)
        stroke = (100, 115, 164)

        def fill(*rgba):
            p = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
            p.setColor(skia.Color(*rgba))
            return p

        def stroke_p(color, width=None):
            p = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=width if width is not None else self.line_width_normal,
            )
            p.setColor(skia.Color(*color))
            return p

        def font_p(color):
            p = skia.Paint(AntiAlias=True)
            p.setColor(skia.Color(*color))
            return p

        self.card_bkg = fill(20, 22, 28, 210)
        self.normal_drw = stroke_p(text)
        self.high_drw = stroke_p(text_hi)

        self.dropdownmenu_button_bkg = fill(*accent_dim)
        self.dropdownmenu_button_hover_bkg = fill(30, 90, 200)
        self.dropdownmenu_button_pressed_bkg = fill(0, 70, 164)
        self.dropdownmenu_button_border_drw = stroke_p(accent)
        self.dropdownmenu_area_bkg = fill(*accent_dim)
        self.dropdownmenu_area_hover_bkg = fill(0, 100, 200)
        self.dropdownmenu_area_selected_line_drw = stroke_p((0, 122, 255), self.line_width_thick)
        self.dropdownmenu_area_border_drw = stroke_p((0, 0, 0))
        self.dropdownmenu_scrollbar_bkg = fill(*text, 150)

        self.button_bkg = fill(*accent)
        self.button_hover_bkg = fill(*accent_hi)
        self.button_pressed_bkg = fill(*pressed)

        self.text_input_bkg = fill(*bg)
        self.text_input_hover_bkg = fill(*hover)
        self.text_input_focused_bkg = fill(20, 40, 100)
        self.text_input_invalid_bkg = fill(*invalid)
        self.text_input_border_drw = stroke_p(stroke)
        self.text_input_focused_border_drw = stroke_p((0, 122, 255))
        self.text_input_selection_bkg = fill(40, 110, 230, 150)
        # Opacity (0–255) of a widget with enabled=False.
        self.disabled_alpha = 110

        self.slider_handle_bkg = fill(*accent_mid)
        self.slider_handle_hover_bkg = fill(70, 150, 255)
        self.slider_handle_pressed_bkg = fill(40, 60, 230)
        self.slider_bar_left_drw = stroke_p((40, 140, 255), self.slider_bar_width)
        self.slider_bar_right_drw = stroke_p((210, 210, 210), self.slider_bar_width)

        self.checkbox_checked_bkg = fill(40, 100, 210)
        self.checkbox_unchecked_bkg = fill(30, 30, 30)
        self.checkbox_checked_hover_bkg = fill(40, 120, 230)
        self.checkbox_unchecked_hover_bkg = fill(*hover)
        self.checkbox_pressed_bkg = fill(30, 60, 160)
        self.checkbox_border_checked_drw = stroke_p((40, 100, 210))
        self.checkbox_border_unchecked_drw = stroke_p(stroke)
        self.checkbox_check_drw = stroke_p(text_hi, self.line_width_thick)

        self.normal_font = font_p(text)
        self.highlight_font = font_p(text_hi)
        self.discrete_font = font_p(text_dim)

        self.menu_font_size = 28.0 * s
        self.menu_title_size = 28.0 * s
        self.menu_min_font_size = 11.0 * s
        self.menu_pad = 18.0 * s
        # Vertical inset of the option block (under the header, and above the
        # panel bottom). Half of menu_pad.
        self.menu_option_pad = 9.0 * s
        self.menu_gap = 8.0 * s
        self.menu_panel_color = Color(16 / 255, 18 / 255, 28 / 255, 230 / 255)
        self.menu_panel_bkg = fill(16, 18, 28, 230)
        # Light veil over a Gradient or Texture title band (no single color to lift).
        self.menu_header_veil = fill(255, 255, 255, 48)
        self.menu_highlight_bkg = fill(40, 90, 200, 220)
        self.menu_backdrop = fill(0, 0, 0, 150)
        self.menu_text = font_p((245, 245, 245))
        self.menu_title_text = font_p((255, 255, 255))


class _DataAlias:
    """Author-facing name for ``UIWidget.data`` (same Attribute; supports ``@=``).

    ``widget.alias @= formula`` gets the cell, installs the link, then stores
    the Attribute back through ``.value`` — ``assign_value`` treats identity as
    a no-op. A later ``widget.alias = concrete`` goes through ``assign_value``
    and raises ``LinkedAttributeError`` if the cell is linked (Decision 4).
    """

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.data

    def __set__(self, instance, value):
        instance.data.value = value


def _geom_point(value, cls_name: str):
    """Widget ``top_left=``: ``None`` (HUD column slot) or a finite point.

    Validated before any layout-cursor move, so a rejected widget leaves the
    HUD column untouched (A5). A snapshot: widgets are Entities without a pose
    graph, so a callable raises instead of linking.
    """
    value = as_payload(value)
    if value is None:
        return None
    callable_part = callable(value) or (
        isinstance(value, (tuple, list)) and any(callable(v) for v in value)
    )
    if callable_part and not isinstance(value, type):
        raise TypeError(
            f"{cls_name} top_left= is a point, not a link — widgets do not "
            "follow formulas. Pass (x, y), or omit it to stack in the HUD column."
        )
    from .scenamath import _as_xy
    from .validate import number
    try:
        x, y = _as_xy(value)
    except (TypeError, ValueError, AttributeError):
        raise TypeError(
            f"{cls_name} top_left= must be a point (x, y), got {value!r}"
        ) from None
    return (
        float(number(as_payload(x), f"{cls_name} top_left x")),
        float(number(as_payload(y), f"{cls_name} top_left y")),
    )


def widget_placement_hints(cls_name: str) -> dict:
    """Orientation for placement spellings other frameworks use."""
    hint = (
        f"{cls_name} is placed by top_left=(x, y) (visual top-left), or omit "
        "it to stack in the HUD column"
    )
    return {
        key: hint
        for key in ("x1", "y1", "x2", "y2", "x", "y", "pos", "position")
    }


def _geom_size(value, what: str):
    """Widget ``width`` / ``height``: ``None`` (default) or a size >= 0."""
    value = as_payload(value)
    if value is None:
        return None
    from .validate import magnitude, fixed_magnitude
    return fixed_magnitude(value, what)


class UIWidget(Entity):
    """HUD control. An Entity that is not a Graphic (same idea as SpatialFx).

    Drawn by ``WidgetManager`` in view space, never by a registry layer.
    ``layer=`` and ``collidable=True`` raise. ``visible=False`` also drops input.
    """

    _scena_is_widget = True

    data = ContainerSlot(Attribute)

    # Public fields assigned in constructors. Class defaults keep them off the
    # ink bag (Entity.__setattr__ treats an unknown name as author ink).
    _x1 = 0.0
    _y1 = 0.0
    _x2 = 0.0
    _y2 = 0.0
    _has_focus = False
    _pressed = False
    _press_over = False
    _is_mouse_over = False
    _pointer_hover = False
    _on_hover = None
    _on_hover_exit = None
    _handle_key = False
    _captures_pointer = True
    _enabled = True
    _tab_stop = False
    label = None
    min_value = 0.0
    max_value = 100.0
    only_int = False
    _handle_radius = 0.0
    show_value = True
    _total_width = 0.0
    _total_height = 0.0
    _dragging_handle = False
    _dragging_value = None
    _is_mouse_over_handle = False
    _internal_margin = 0.0
    _value_space = 0.0
    _label_space = 0.0
    _slider_length = 0.0
    _slider_x = 0.0
    _slider_y = 0.0
    _thick_slider_bar_left_drw = None
    _thick_slider_bar_right_drw = None
    _is_open = False
    _hover_index = -1
    options = None
    _list_margin_top = 0.0
    _list_padding = 0.0
    _option_margin = 0.0
    _option_height = 0.0
    value_on = None
    value_off = None
    _text_width = 0.0
    placeholder = ""
    _cursor_pos = 0
    _cursor_visible = True
    _cursor_blink_time = 0.5
    _last_blink = 0.0

    @property
    def value(self):
        """Python payload of ``data`` (not the Attribute)."""
        return self.data.value

    @property
    def on_click(self):
        """Only ``Button`` has ``on_click``; a value widget reports changes through ``@on_change(widget.data)``."""
        return None

    @on_click.setter
    def on_click(self, value) -> None:
        if value is None:
            return
        name = type(self).__name__
        raise TypeError(
            f"{name} has no on_click: a click changes its value. Watch the "
            f"value instead: @on_change({name.lower()}.data). Only Button "
            f"has on_click."
        )

    @property
    def on_hover(self):
        """Called when the pointer starts hovering this widget, ``fn(widget)``, or ``None``."""
        return self._on_hover

    @on_hover.setter
    def on_hover(self, value) -> None:
        from .validate import check_pointer_handler
        self._on_hover = check_pointer_handler(
            value, ("the widget",), what=f"{type(self).__name__} on_hover")

    @property
    def on_hover_exit(self):
        """Called when the pointer stops hovering this widget, ``fn(widget)``, or ``None``."""
        return self._on_hover_exit

    @on_hover_exit.setter
    def on_hover_exit(self, value) -> None:
        from .validate import check_pointer_handler
        self._on_hover_exit = check_pointer_handler(
            value, ("the widget",), what=f"{type(self).__name__} on_hover_exit")

    @property
    def pointer_hover(self) -> bool:
        """True when this widget is the one hover target under the pointer (read-only)."""
        return self._pointer_hover

    def _set_pointer_hover(self, hovered: bool) -> None:
        """Framework-driven hover bit (set by the per-frame hover resolver)."""
        object.__setattr__(self, "_pointer_hover", bool(hovered))

    @property
    def pointer_pressed(self) -> bool:
        """True while the left button, pressed on this widget, is held and the pointer is over it (read-only).

        Same rule as a Graphic's ``pointer_pressed``. A disabled widget never reads True.
        """
        return bool(self._pressed and self._press_over)

    @property
    def visible(self) -> bool:
        """Show / hide the widget (``True`` / ``False``). A hidden widget ignores the mouse."""
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        from .validate import expect_bool
        want = expect_bool(value, f"{type(self).__name__}.visible")
        self._visible = want
        if not want:
            self._release_interaction()
        wm = getattr(self, "_widget_manager", None)
        if wm is not None:
            wm._widget_epoch += 1     # hover re-resolves under a still cursor

    @property
    def enabled(self) -> bool:
        """``False`` greys the widget out: still drawn (faded), but it ignores input.

        It blocks the pointer (a click does not fall through to the game) and
        still reports hover (``on_hover`` / ``pointer_hover``), so a hint can say
        why it is off. It cannot take focus; Tab skips it. Disabling a focused
        TextInput commits it. ``visible = False`` hides the widget instead.
        """
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        from .validate import expect_bool
        want = expect_bool(value, f"{type(self).__name__}.enabled")
        self._enabled = want
        if not want:
            self._release_interaction()
        wm = getattr(self, "_widget_manager", None)
        if wm is not None:
            wm._widget_epoch += 1     # hover re-resolves under a still cursor

    @property
    def layer(self):
        """Always ``None``: widgets draw in the HUD, above the world (assigning raises)."""
        return None

    @layer.setter
    def layer(self, value) -> None:
        raise TypeError(
            f"{type(self).__name__} has no layer: widgets always draw in the HUD. "
            f"Hide one with visible=False."
        )

    @property
    def collidable(self) -> bool:
        """Always ``False``: widgets are HUD controls, not world bodies (``True`` raises)."""
        return False

    @collidable.setter
    def collidable(self, value: bool) -> None:
        if _expect_flag(value, 'collidable'):
            raise TypeError(
                f"{type(self).__name__} cannot collide. Widgets are HUD controls, "
                f"not world bodies."
            )
        object.__setattr__(self, "_collision_opt_out", True)
        object.__setattr__(self, "_collidable", False)

    def __init__(self, *, group=None, stack=True, top_left=None):
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        if not fw.widget_manager:
            raise RuntimeError(
                "Widgets need the framework: import scena (from scena import *) "
                "before creating one"
            )
        Entity._construct(
            self, layer=None, group=group,
            attr_name=type(self).__name__,
        )
        # Never enrolled by @collide group refresh.
        object.__setattr__(self, "_collision_opt_out", True)
        object.__setattr__(self, "_on_click", None)
        widget_manager = fw.widget_manager
        if stack:
            widget_manager.add_widget(self, top_left=top_left)
        else:
            widget_manager.widgets.append(self)
        self._widget_manager = widget_manager
        self._theme = widget_manager.widget_theme
        self._theme._ensure()

        self._has_focus = False
        self._pressed = False
        self._is_mouse_over = False
        self._handle_key = False
        self._captures_pointer = True

    @property
    def box(self):
        """Fresh view-space ``Box`` of this widget's rectangle (a snapshot).

        Read it to place things next to a widget:
        ``ui.stack_origin(slider.box.top_right + (16, 0))``.
        """
        from .box import Box
        x1, y1, x2, y2 = self._x1, self._y1, self._x2, self._y2
        return Box._from_aabb(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def _release_interaction(self) -> None:
        """Drop focus, press, and hover so a hidden widget cannot keep input."""
        wm = getattr(self, "_widget_manager", None)
        if wm is None:
            return
        if wm.focused_widget is self:
            wm.set_focus(None)
        if wm.pressed_widget is self:
            self._pressed = False
            wm.pressed_widget = None
        if wm.mouse_over_widget is self:
            self._is_mouse_over = False
            wm.mouse_over_widget = None

    def _data_is_linked(self) -> bool:
        """True when the widget cell carries an inbound ``@=`` formula."""
        data = self.__dict__.get('data')
        if data is None:
            return False
        return getattr(data, '_link', None) is not None

    def _resolve_field(self, key: str):
        """Map author aliases (``text``, ``checked``, ``value``) onto ``data``."""
        if key != "data":
            for base in type(self).__mro__:
                desc = base.__dict__.get(key)
                if isinstance(desc, _DataAlias):
                    key = "data"
                    break
            else:
                if key == "value":
                    key = "data"
        return super()._resolve_field(key)

    def _bind_data(self, cell: Attribute) -> None:
        """Alias self.data to an external Attribute for two-way binding.

        Ownership of cell is left unchanged; the widget shares the same
        Attribute instance so reads/writes go directly to it. Live display
        values need no observer — draw/input already read self.data.
        """
        self.__dict__['data'] = cell

    def _apply_data(self, cell, initial, default, *, skip_if_equal=False) -> None:
        """Bind and/or seed ``data``. ``initial`` wins when both are given."""
        if cell is not None:
            self._bind_data(cell)
            if initial is not None:
                if skip_if_equal and self.data.value == initial:
                    return
                self.data.value = initial
        elif initial is not None:
            self.data.value = initial
        else:
            self.data.value = default

    def flash_text(self, text, duration: float = 1.0, *, on_done=None):
        """Show ``text`` for ``duration`` seconds, then go back to the cell's text.

        The link to the data cell stays; only the display is overridden.

        Args:
            text: what to show meanwhile.
            duration: seconds (default 1).
            on_done: optional function called when the flash ends.

        Returns this widget (chainable).
        """
        from .transients import flash_text as _flash_text
        _flash_text(self, text, duration, on_done=on_done)
        return self

    def _displayed_text(self, now: float | None = None) -> str:
        """String currently shown: flash override if active, else the data payload."""
        from .transients import active_flash_text
        override = active_flash_text(self, now)
        if override is not None:
            return override
        return str(self.value)

    def _draw_card(self, canvas):
        """Backing plate for pointer-capturing widgets. Visual only (hit box unchanged)."""
        if not self._captures_pointer:
            return
        pad = self._theme.card_padding
        rect = skia.Rect.MakeXYWH(
            self._x1 - pad,
            self._y1 - pad,
            (self._x2 - self._x1) + 2 * pad,
            (self._y2 - self._y1) + 2 * pad,
        )
        rrect = skia.RRect.MakeRectXY(
            rect, self._theme.corner_radius, self._theme.corner_radius
        )
        canvas.drawRRect(rrect, self._theme.card_bkg)

    def _update_impl(self) -> None:
        pass

    def _on_mouse_move(self, x, y):
        """Handle mouse movement events. Return True if handled."""
        return False
    
    def _on_mouse_leave(self, x, y):
        """Handle mouse leave events. Return True if handled."""
        return False
        
    def _on_mouse_down(self, x, y, button):
        """Handle mouse press events. Return True if handled."""
        return False
        
    def _on_mouse_up(self, x, y, button, click_x, click_y):
        """Handle mouse release events. Return True if handled.
        click_x, click_y are the coordinates where the initial press occurred."""
        return False

    def _on_mouse_click(self, x, y, button):
        """Handle mouse click events. Return True if handled."""
        return False

    def _abandon_press(self, button) -> None:
        """This widget held ``button``'s press and leaves before its release
        (destroyed, its act ended, the release was lost): undo what the press
        set, with no release callback and no click (bug PD1)."""
        return

    def _on_mouse_double_click(self, x, y, button):
        """Handle mouse double click events. Return True if handled."""
        return False
        
    def _on_mouse_scroll(self, x_scroll, y_scroll):
        """Handle mouse scroll events. Return True if handled."""
        return

    def _on_mouse_drag(self, x, y):
        """Handle mouse drag events. Return True if handled."""
        return

    def _on_key_down(self, key):
        """Handle key press events. Return True if handled."""
        return

    def _on_key_up(self, key):
        """Handle key release events. Return True if handled."""
        return

    def _on_key(self, key):
        """Handle key release events. Return True if handled."""
        return

    def _on_char(self, char):
        """Handle character input events. Return True if handled."""
        return

    def _claims_key(self, key, mods) -> bool:
        """While focused (``_handle_key``): keep ``key`` from the game? Default: all."""
        return True

    def _before_key_leaves(self) -> None:
        """While focused: a key this widget did not claim is going to the game."""
        return

    def draw(self, canvas):
        """Draw the base layer. Must be implemented by subclasses."""
        raise NotImplementedError

    def _draw_priority(self, canvas):
        """Draw the priority layer. Override in subclasses that need it."""
        pass

    def _on_focus_gained(self):
        """Handle focus gained events. Return True if handled."""
        return False

    def _on_focus_lost(self):
        """Handle focus lost events. Return True if handled."""
        return False

    def _give_up_focus(self):
        self._widget_manager.set_focus(None)

    def contains_point(self, x, y):
        """Check if the given point (x, y) is within the widget's bounds."""
        return self._x1 <= x <= self._x2 and self._y1 <= y <= self._y2

class _NoCell:
    """Default of a widget's ``cell``: none given (an explicit ``None`` raises)."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "<no cell>"


_NO_CELL = _NoCell()


def _require_bound(cell, widget: str, example: str, *, takes_initial: bool = True):
    """The cell a widget binds: ``st["volume"]`` → its Attribute; omitted → None.

    A plain value raises: ``Slider(st.volume)`` reads the value (0.8.0), so
    it names the bracket spelling. So does an explicit ``None`` — what
    ``Menu(st.ship)`` passes while ``st.ship`` still holds ``None``, which
    would otherwise leave the widget silently unbound.
    """
    if cell is _NO_CELL:
        return None
    bound = bound_cell(cell)
    if bound is not None:
        return bound
    call = f'{widget}(st["{example}"])'
    if cell is None:
        raise TypeError(
            f"{widget}(None): to bind a cell, pass it with brackets: {call} "
            f"(st.{example} reads the value, here None). For a widget with "
            f"no cell, leave the argument out."
        )
    tail = (f" To set the starting value instead, write {widget}(initial={cell!r:.40})."
            if takes_initial and not hasattr(cell, "owner") else "")
    raise TypeError(f"{widget}(cell) binds a data cell: "
                    + unbound_value_hint(call, cell, example) + tail)


class Slider(UIWidget):
    """A horizontal value slider in the HUD (drag, click, or mouse wheel).

    Args:
        cell: numeric data cell the slider reads and writes (``st["volume"]``).
        label: caption (default: the cell's name).
        top_left: ``(x, y)`` of the visual top-left; omit to stack in the HUD column.
        width: track length in design units (default: theme size).
        min_value, max_value: the range (``min_value <= max_value``).
        initial: starting value (clamped to the range).
        show_value: print the current number next to the track (default ``True``).
        only_int: snap to whole numbers (default ``False``).
        enabled: ``False`` draws it faded and ignores input (default ``True``).
        group: group tag(s).
    """

    def __init__(self, cell: Attribute | None = _NO_CELL, *, label: str | None = None, 
                 top_left=None, width: float | None = None, 
                 min_value: float = None, max_value: float = None, initial: float | None = None,
                 show_value: bool = True, only_int: bool = False,
                 enabled=True, group=None):
        label = as_payload(label)
        top_left = _geom_point(top_left, "Slider")
        width = _geom_size(width, "width")
        min_value = as_payload(min_value)
        max_value = as_payload(max_value)
        initial = as_payload(initial)
        from .validate import expect_bool
        # Flags before any layout call: a rejected Slider must not move the HUD column.
        show_value = expect_bool(show_value, "Slider show_value")
        only_int = expect_bool(only_int, "Slider only_int")
        cell = _require_bound(cell, "Slider", "volume")
        from .validate import number   # fixed numbers: finite() lets a function through
        if min_value is not None:
            min_value = number(min_value, "Slider min_value")
        if max_value is not None:
            max_value = number(max_value, "Slider max_value")
        if initial is not None:
            initial = number(initial, "Slider initial")
        lo = 0.0 if min_value is None else min_value
        hi = 100.0 if max_value is None else max_value
        if lo == hi:
            raise ValueError("min_value cannot equal max_value in Slider")
        if lo > hi:
            raise ValueError(
                f"Slider min_value ({lo:g}) is greater than max_value ({hi:g}). "
                f"Swap them: Slider(min_value={hi:g}, max_value={lo:g})."
            )
        
        enabled = _expect_flag(enabled, "Slider enabled")
        super().__init__(group=group, top_left=top_left)
        self._enabled = enabled

        # Set min and max values. Attribute cells no longer carry constraints
        # (those lived on MovementController); defaults are 0–100 unless given.
        self.min_value = min_value if min_value is not None else 0.0
        self.max_value = max_value if max_value is not None else 100.0
        self.only_int = only_int if only_int is not None else False

        mid = (self.min_value + self.max_value) / 2
        default = int(round(mid)) if self.only_int else mid
        self._apply_data(cell, initial, default=default, skip_if_equal=True)
            
        # Set properties
        self.height = self._theme.slider_bar_width
        self._handle_radius = self._theme.slider_handle_radius
        self.show_value = show_value
        self.label = label if label is not None else (cell.name if cell is not None else None)
        self._total_width = width

        # State properties
        self._dragging_handle = False
        self._dragging_value = None
        self._is_mouse_over_handle = False

        # Calculate internal layout
        self._internal_margin = self._theme.slider_margin
        self._value_space = self._theme.slider_value_space if show_value else 0
        self._label_space = 0
        self._min_label_space = self._theme.min_label_space
        self._needed_label_space = 0.0
        if self.label:
            natural = (
                measure_text(self._theme.default_font, str(self.label))
                + 2 * self._theme.control_pad
            )
            self._needed_label_space = max(natural, self._min_label_space)

        # Establish boundaries first
        if width is not None:
            self.width = width

        self._joins_label_column = (
            getattr(self, '_stack_auto', False) and bool(self.label)
        )

        self._total_height = max(self._theme.row_height, 2 * self._handle_radius)
        self._x2 = self._x1 + self.width
        self._y2 = self._y1 + self._total_height
        self._widget_manager.finish_auto_layout(self)

        self._update_track_layout()
        if self._joins_label_column:
            self._widget_manager.join_label_column(self)

        self._thick_slider_bar_left_drw = skia.Paint(self._theme.slider_bar_left_drw)
        self._thick_slider_bar_left_drw.setStrokeWidth(self._theme.slider_bar_width_hover)
        
        self._thick_slider_bar_right_drw = skia.Paint(self._theme.slider_bar_right_drw) 
        self._thick_slider_bar_right_drw.setStrokeWidth(self._theme.slider_bar_width_hover)

        # Name
        if label is not None:
            pass
            #self.name = label   #error, name has no setter
    
    @property
    def percentage(self):
        """Return the current value as a percentage between min and max values"""
        return (self.value - self.min_value) / (self.max_value - self.min_value)

    def _on_focus_lost(self):
        self._dragging_handle = False
        return True

    def _update_track_layout(self, label_space: float | None = None) -> None:
        """Recompute track origin/length from current label, width, and value gutter.

        ``_label_space`` overrides the measured label column (HUD run alignment
        and smoke panels pass a shared width so tracks line up). The handle
        disc at 0% and 100% stays inside the widget box so hover/drag still
        hit it. With no override, the floor is the construct-time snapshot
        ``_min_label_space``, not a live ``ui.min_label_space`` read.
        """
        if label_space is None:
            label_space = 0.0
            if self.label:
                label_space = (
                    measure_text(self._theme.default_font, str(self.label))
                    + 2 * self._theme.control_pad
                )
                floor = getattr(self, '_min_label_space', self._theme.min_label_space)
                if label_space < floor:
                    label_space = floor
        self._label_space = label_space
        self._value_space = self._theme.slider_value_space if self.show_value else 0
        self._slider_length = (
            self.width
            - self._value_space
            - self._label_space
            - (2 * self._internal_margin)
            - (2 * self._handle_radius)
        )
        self._slider_x = self._x1 + self._handle_radius + self._label_space
        self._slider_y = self._y1 + (self._total_height / 2)

    def _point_on_handle(self, x, y) -> bool:
        hx, hy = self._get_handle_pos()
        r = self._handle_radius
        dx, dy = x - hx, y - hy
        # Products, not ``** 2``: a float power raises OverflowError for a
        # huge-but-finite coordinate; a product saturates to inf.
        return dx * dx + dy * dy <= r * r

    def _quantize(self, value):
        """Snap to an integer when ``only_int``, then clamp to [min, max].

        ``int()`` truncation would map the last unit of the track to
        ``max_value - 1`` (and often miss ``max_value`` entirely after float
        error). Round so each integer, including the endpoints, has a bin.
        """
        if self.only_int:
            value = int(round(value))
        return min(max(value, self.min_value), self.max_value)

    def _value_from_x(self, x):
        """Map a pointer x onto the track, then quantize."""
        new_x = min(max(x, self._slider_x), self._slider_x + self._slider_length)
        t = (new_x - self._slider_x) / self._slider_length
        return self._quantize(self.min_value + t * (self.max_value - self.min_value))

    def _in_track_area(self, x, y) -> bool:
        r = self._handle_radius
        lo = self._slider_x
        hi = self._slider_x + self._slider_length
        # Include the disc overhang past each end of the track.
        return lo - r <= x <= hi + r and abs(y - self._slider_y) <= r

    def contains_point(self, x, y):
        """Hit the widget box or the handle disc (disc may sit past the box)."""
        if super().contains_point(x, y):
            return True
        return self._point_on_handle(x, y)

    def _on_mouse_down(self, x, y, button):
        if button == Mouse.BTN_LEFT:
            on_handle = self._point_on_handle(x, y)
            if on_handle or self._in_track_area(x, y):
                if self._data_is_linked():
                    return True
                self._dragging_handle = True
                if not on_handle:
                    self.data = self._value_from_x(x)
                    self._is_mouse_over_handle = True
                return True
        return False

    def _on_mouse_drag(self, x, y):
        if self._dragging_handle:
            if self._data_is_linked():
                return True
            aux_value = self._value_from_x(x)
            self.data = aux_value
            self._dragging_value = aux_value
            return True
        return False

    def _on_mouse_up(self, x, y, button, click_x, click_y):
        if button == Mouse.BTN_LEFT and self._dragging_handle:
            self._dragging_handle = False
            self._widget_manager.no_focus()
            if not self._point_on_handle(x, y):
                self._is_mouse_over_handle = False
            return True
        return False

    def _on_mouse_scroll(self, x_scroll, y_scroll):
        if self._data_is_linked():
            return True
        span = self.max_value - self.min_value
        step = 1.0 if self.only_int else span * 0.02
        self.data = self._quantize(self.value + y_scroll * step)
        return True

    def _on_mouse_move(self, x, y):
        self._is_mouse_over_handle = self._point_on_handle(x, y) or self._dragging_handle
        return True

    def _on_mouse_leave(self, x, y):
        self._is_mouse_over_handle = False
        return True

    def _get_handle_pos(self):
        adjusted_value = min(max(self.value, self.min_value), self.max_value)

        handle_x = self._slider_x + (adjusted_value - self.min_value) / (self.max_value - self.min_value) * self._slider_length
        return (handle_x, self._slider_y)

    def draw(self, canvas):
        if self.label:
            draw_string_upright(
                canvas,
                self.label,
                self._x1,  # Start at left edge
                text_baseline_centered(
                    self._y1, self._total_height, self._theme.default_font
                ),
                self._theme.default_font,
                self._theme.normal_font
            )

        # Get handle position
        handle_pos = self._get_handle_pos()
        
        # Draw the two parts of the line
        # Active (blue) line from start to handle using selected_drw
        if self._is_mouse_over or self._pressed:
            left_drw = self._thick_slider_bar_left_drw
            right_drw = self._thick_slider_bar_right_drw
        else:
            left_drw = self._theme.slider_bar_left_drw
            right_drw = self._theme.slider_bar_right_drw
        
        canvas.drawLine(self._slider_x, self._slider_y, 
                        handle_pos[0], self._slider_y, 
                        left_drw)
        
        # Inactive line from handle to end using normal_drw
        canvas.drawLine(handle_pos[0], self._slider_y, 
                        self._slider_x + self._slider_length, self._slider_y, 
                        right_drw)


        # Draw handle with different sizes and colors based on state
        if self._pressed:
            handle_paint = self._theme.slider_handle_pressed_bkg
        elif self._is_mouse_over_handle:
            handle_paint = self._theme.slider_handle_hover_bkg
        else:
            handle_paint = self._theme.slider_handle_bkg

        handle_radius = self._handle_radius * 1.2 if self._is_mouse_over_handle else self._handle_radius
        canvas.drawCircle(handle_pos[0], handle_pos[1], handle_radius, handle_paint)
        
        # Draw value text using normal_drw
        if self.show_value:
            if self.only_int:
                # Check if value has a fractional part
                if self.value == int(self.value):
                    value_text = f"{int(self.value)}"
                else:
                    value_text = f"{self.value:.1f}"
            else:
                value_text = f"{self.value:.1f}"
            draw_string_upright(
                canvas,
                value_text,
                self._slider_x + self._slider_length + self._handle_radius + 5,
                text_baseline_centered(
                    self._y1, self._total_height, self._theme.default_font
                ),
                self._theme.default_font,
                self._theme.normal_font
            )


class DropDown(UIWidget):
    """A pick-one list in the HUD.

    Args:
        cell: data cell that receives the chosen option (``st["palette"]``).
        top_left: ``(x, y)`` of the visual top-left; omit to stack in the HUD column.
        width, height: size in design units (default: theme size).
        options: the choices (a list); omitted, the cell's ``options`` are used.
        initial: the option selected at start (default: the first).
        enabled: ``False`` draws it faded and ignores input (default ``True``).
        group: group tag(s).
    """

    def __init__(self, cell: Attribute | None = _NO_CELL, *, top_left=None, width=None, 
                 height=None, options=None, initial=None, enabled=True, group=None):
        top_left = _geom_point(top_left, "DropDown")
        width = _geom_size(width, "width")
        height = _geom_size(height, "height")
        options = as_payload(options)
        initial = as_payload(initial)
        cell = _require_bound(cell, "DropDown", "palette")
        if options is not None:
            if isinstance(options, (str, bytes)) or not hasattr(options, "__iter__"):
                raise TypeError(
                    f"DropDown options= expected a list of choices, got "
                    f"{type(options).__name__} {options!r}. "
                    f"Write options=[\"easy\", \"hard\"]."
                )
            options = list(options)
            if not options:
                raise ValueError(
                    "DropDown options= is empty; give at least one choice, "
                    "e.g. options=[\"easy\", \"hard\"]."
                )
        
        enabled = _expect_flag(enabled, "DropDown enabled")
        super().__init__(group=group, top_left=top_left)
        self._enabled = enabled
        self._is_open = False
        self._hover_index = -1
        self._scroll = 0.0  # design units the rows are shifted up (0 = first row on top)

        if options is not None:
            self.options = options
        elif cell is not None and hasattr(cell, 'options') and cell.options:
            self.options = list(cell.options)
        else:
            self.options = ["Option 1", "Option 2", "Option 3"]

        write_initial = initial
        if initial is not None and initial not in self.options:
            write_initial = self.options[0]
        self._apply_data(cell, write_initial, default=self.options[0])
        if self.value not in self.options:
            self.data = self.options[0]

        # Constants for margins and styling
        self._list_margin_top = self._theme.control_pad
        self._list_padding = self._theme.card_padding
        self._option_margin = max(1.0, 2.0 * ui.scale)

        # Establish boundaries
        if width is not None:
            self.width = width

        self.height = self._theme.row_height if height is None else height
        self._option_height = self.height
        self._x2 = self._x1 + self.width
        self._y2 = self._y1 + self.height
        self._widget_manager.finish_auto_layout(self)

    @property
    def text(self):
        """Unwrapped selection (not a graph alias — that is ``.data``)."""
        return self.value

    @property
    def selected_index(self):
        """Index of ``value`` in ``options``, or -1 if the value is not in the list."""
        try:
            return self.options.index(self.value)
        except ValueError:
            return -1

    @selected_index.setter 
    def selected_index(self, new_index):
        if not isinstance(new_index, int) or isinstance(new_index, bool):
            raise TypeError(f"DropDown.selected_index expected a whole number, got {type(new_index).__name__}")
        if new_index < 0 or new_index >= len(self.options):
            raise ValueError("Selected index out of range")
        self.data = self.options[new_index]

    def _on_focus_gained(self):
        return True

    def _on_focus_lost(self):
        self._is_open = False
        self._hover_index = -1
        self._scroll = 0.0
        return True

    def _list_span(self):
        """``(bottom, top)`` of the open list in view space (y-up).

        It hangs below the button unless it does not fit there and there is
        more room above; then it opens upward. Too tall for the side it takes,
        it ends at the view edge and its rows scroll (``_scroll``). A list
        that fits is unchanged. The one source of the list rectangle: the hit
        test, the row lookup and the drawing all read it.
        """
        from .orchestration import ScenaFramework
        h = len(self.options) * self._option_height + 2 * self._list_padding
        m = self._list_margin_top
        below = self._y1 - m
        above = ScenaFramework.get_instance().design_height - (self._y2 + m)
        up = below < h and above > below
        room = above if up else below
        if h > room:
            # At least one row shows, even with almost no room.
            h = max(room, self._option_height + 2 * self._list_padding)
        if up:
            bottom = self._y2 + m
            return bottom, bottom + h
        return below - h, below

    def _opens_up(self) -> bool:
        return self._list_span()[0] >= self._y2

    def _scroll_range(self):
        """How far the rows can scroll (0 when they all fit)."""
        bottom, top = self._list_span()
        visible = top - bottom - 2 * self._list_padding
        return max(0.0, len(self.options) * self._option_height - visible)

    def _scroll_offset(self):
        """``_scroll`` clamped to the current range (options or room may have changed)."""
        return min(max(self._scroll, 0.0), self._scroll_range())

    def _row_y(self, index):
        """Bottom y of row ``index`` (may lie outside the visible list)."""
        top = self._list_span()[1]
        return (top - self._list_padding - self._option_height * (index + 1)
                + self._scroll_offset())

    def _option_index_at(self, x, y):
        """Row under ``(x, y)``, or -1. Rows run top to bottom on either side;
        only the visible part of a row counts."""
        if not self._x1 <= x <= self._x2:
            return -1
        bottom, top = self._list_span()
        pad = self._list_padding
        if not bottom + pad <= y <= top - pad:
            return -1
        i = int((top - pad + self._scroll_offset() - y) // self._option_height)
        if 0 <= i < len(self.options):
            return i
        return -1

    def _scroll_to_selected(self):
        """On open: the selected row in the middle of the list, if it scrolls."""
        rng = self._scroll_range()
        i = self.selected_index
        if rng <= 0 or i < 0:
            self._scroll = 0.0
            return
        bottom, top = self._list_span()
        visible = top - bottom - 2 * self._list_padding
        want = (i + 0.5) * self._option_height - visible / 2
        self._scroll = min(max(want, 0.0), rng)

    def _on_mouse_move(self, x, y):
        if not self._is_open:
            return False
        self._hover_index = self._option_index_at(x, y)
        return True

    def _on_mouse_leave(self, x, y):
        self._hover_index = -1

    def _on_mouse_scroll(self, x_scroll, y_scroll):
        if not self._is_open:
            return True
        # Wheel up (positive) shows earlier rows; one row per wheel notch.
        self._scroll = min(max(self._scroll_offset() - y_scroll * self._option_height, 0.0),
                           self._scroll_range())
        # The rows moved under a still pointer: hover follows (no move event comes).
        ptr = self._widget_manager._ptr_seen
        self._hover_index = self._option_index_at(*ptr) if ptr is not None else -1
        return True

    def _on_mouse_down(self, x, y, button):
        if button != Mouse.BTN_LEFT:
            return False

        # Check if click is within main button
        if self._is_inside_main_button(x, y):
            self._is_open = not self._is_open
            self._hover_index = -1
            if self._is_open:
                self._scroll_to_selected()
            else:
                self._scroll = 0.0
            return True

        return False

    def _on_mouse_click(self, x, y, button):
        if button != Mouse.BTN_LEFT:
            return False

        idx = self._option_index_at(x, y)
        if self._is_open and idx != -1:
            if not self._data_is_linked():
                self.selected_index = idx
            self._is_open = False
            self._hover_index = -1
            self._widget_manager.no_focus()
            return True

        return True

    def draw(self, canvas):
        # Define arrow dimensions first
        arrow_width = self._theme.arrow_width
        arrow_height = self._theme.arrow_height

        # Draw the main button background
        if (self._pressed or self._is_open):
            main_button_paint = self._theme.dropdownmenu_button_pressed_bkg
        elif self._is_mouse_over:
            main_button_paint = self._theme.dropdownmenu_button_hover_bkg
        else:
            main_button_paint = self._theme.dropdownmenu_button_bkg

        # Draw the main button background and border
        rect = skia.Rect.MakeXYWH(self._x1, self._y1, self.width, self.height)
        rrect = skia.RRect.MakeRectXY(rect, self.height/2, self.height/2)
        canvas.drawRRect(rrect, main_button_paint)
        canvas.drawRRect(rrect, self._theme.dropdownmenu_button_border_drw)
        
        # Draw the selected option text
        selected_text = self.value
        # Calculate text width and center position, leaving space for arrow
        text_width = measure_text(self._theme.default_font, selected_text)
        available_width = self.width - self._theme.arrow_width - 20  # 20px total padding for arrow
        text_x = self._x1 + (available_width - text_width) / 2
        text_y = text_baseline_centered(
            self._y1, self.height, self._theme.default_font
        )
        draw_string_upright(
            canvas,
            selected_text,
            text_x,
            text_y,
            self._theme.default_font,
            self._theme.highlight_font
        )
        
        # Draw dropdown arrow
        arrow_paint = skia.Paint(self._theme.normal_drw)
        arrow_paint.setStrokeWidth(self._theme.line_width_normal)
        arrow_x = self._x1 + self.width - arrow_width - 15  # px padding from right
        arrow_y = self._y1 + (self.height - arrow_height) / 2
        
        if self._is_open and not self._opens_up():
            # Open below: tip toward +y (visual up)
            canvas.drawLine(arrow_x, arrow_y,
                            arrow_x + arrow_width/2, arrow_y + arrow_height,
                            arrow_paint)
            canvas.drawLine(arrow_x + arrow_width/2, arrow_y + arrow_height,
                            arrow_x + arrow_width, arrow_y,
                            arrow_paint)
        else:
            # Closed, or open above: tip toward -y (visual down)
            canvas.drawLine(arrow_x, arrow_y + arrow_height,
                            arrow_x + arrow_width/2, arrow_y,
                            arrow_paint)
            canvas.drawLine(arrow_x + arrow_width/2, arrow_y,
                            arrow_x + arrow_width, arrow_y + arrow_height,
                            arrow_paint)

    def _draw_priority(self, canvas):
        if self._is_open:
            # Below the button, or above it when there is no room below.
            list_y, list_top = self._list_span()
            list_height = list_top - list_y
            
            # Draw outer container with rounded corners
            list_rect = skia.Rect.MakeXYWH(self._x1, list_y, self.width, list_height)
            list_rrect = skia.RRect.MakeRectXY(list_rect, self._theme.corner_radius, self._theme.corner_radius)
            
            # Draw background and border
            canvas.drawRRect(list_rrect, self._theme.dropdownmenu_area_bkg)
            canvas.drawRRect(list_rrect, self._theme.dropdownmenu_area_border_drw)

            # Draw options from top of list downward; a list that scrolls
            # clips to its inside and draws only the rows that show.
            pad = self._list_padding
            oh = self._option_height
            scroll = self._scroll_offset()
            rng = self._scroll_range()
            first, last = 0, len(self.options)
            if rng > 0:
                canvas.save()
                canvas.clipRect(skia.Rect.MakeLTRB(
                    self._x1, list_y + pad, self._x2, list_top - pad))
                first = int(scroll // oh)
                last = min(last, int((scroll + list_height - 2 * pad) // oh) + 1)
            option_y = self._row_y(first)
            text_left_padding = 15  # Increased padding to make room for selection line
            for i in range(first, last):
                option = self.options[i]
                option_rect = skia.Rect.MakeXYWH(
                    self._x1 + self._list_padding,
                    option_y,
                    self.width - (2 * self._list_padding),
                    self._option_height - self._option_margin
                )
                option_rrect = skia.RRect.MakeRectXY(option_rect, 
                    self._theme.corner_radius/2,
                    self._theme.corner_radius/2
                )

                # Only draw hover background, selected item now uses a line indicator
                if i == self._hover_index:
                    canvas.drawRRect(option_rrect, self._theme.dropdownmenu_area_hover_bkg)
                
                # Draw selection indicator line for selected item
                if i == self.selected_index:
                    line_x = self._x1 + self._list_padding + 6  # Small offset from left edge
                    canvas.drawLine(
                        line_x,
                        option_y + 2,  # Small offset from top
                        line_x,
                        option_y + self._option_height - self._option_margin - 2,  # Small offset from bottom
                        self._theme.dropdownmenu_area_selected_line_drw
                    )
                
                # Draw option text with increased left padding
                text_paint = self._theme.highlight_font if i == self.selected_index else self._theme.normal_font
                draw_string_upright(
                    canvas,
                    option,
                    self._x1 + self._list_padding + text_left_padding,
                    text_baseline_centered(
                        option_y,
                        self._option_height - self._option_margin,
                        self._theme.default_font,
                    ),
                    self._theme.default_font,
                    text_paint
                )
                
                option_y -= self._option_height

            if rng > 0:
                canvas.restore()
                # Passive scrollbar: a thumb on the right edge, sized by the
                # share of rows that show, placed by the scroll offset.
                track = list_height - 2 * pad
                thumb = max(track * track / (track + rng), min(track, oh / 2))
                thumb_top = list_top - pad - (track - thumb) * (scroll / rng)
                bar_w = max(2.0, pad)
                bar = skia.Rect.MakeLTRB(
                    self._x2 - pad / 2 - bar_w, thumb_top - thumb,
                    self._x2 - pad / 2, thumb_top)
                canvas.drawRRect(skia.RRect.MakeRectXY(bar, bar_w / 2, bar_w / 2),
                                 self._theme.dropdownmenu_scrollbar_bkg)

    def contains_point(self, x, y):
        """Check if the given point (x, y) is within the widget's bounds, considering dropdown state."""
        if self._is_open:
            bottom, top = self._list_span()
            return (
                self._x1 <= x <= self._x1 + self.width
                and min(bottom, self._y1) <= y <= max(top, self._y1 + self.height)
            )
        else:
            # When closed, just check the main button area
            return self._x1 <= x <= self._x1 + self.width and self._y1 <= y <= self._y1 + self.height

    def _is_inside_main_button(self, x, y):
        return self._x1 <= x <= self._x1 + self.width and self._y1 <= y <= self._y1 + self.height

class Button(UIWidget):
    """A push button in the HUD.

    ``Button(label="Reset", on_click=reset)`` calls ``reset()`` on a click;
    a handler with one parameter receives the button (``def pressed(b):``),
    like ``shape.on_click``. ``@click(button)`` works too.
    With a data cell, the cell follows the press: ``value_on`` while the
    button is held, ``value_off`` after release (default ``True`` / ``False``)
    — a momentary switch, not a toggle (use ``CheckBox`` for on/off).

    Args:
        cell: optional data cell (``st["firing"]``) written on press / release.
        top_left: ``(x, y)`` of the visual top-left; omit to stack in the HUD column.
        width, height: size in design units (default: theme size).
        label: text on the button (default ``"Button"``).
        on_click: function called on each click, ``fn()`` or ``fn(button)``.
        value_on, value_off: values written to ``cell`` while held / after release.
        enabled: ``False`` draws it faded and ignores input (default ``True``).
        group: group tag(s), like any actor.
    """

    def __init__(self, cell: Attribute | None = _NO_CELL, *, top_left=None, width=None, 
                 height=None, label="Button", on_click=None, value_on = None, value_off = None,
                 enabled=True, group=None):
        top_left = _geom_point(top_left, "Button")
        width = _geom_size(width, "width")
        height = _geom_size(height, "height")
        label = as_payload(label)
        on_click = as_payload(on_click)
        value_on = as_payload(value_on)
        value_off = as_payload(value_off)
        cell = _require_bound(cell, "Button", "firing", takes_initial=False)
        from .validate import check_pointer_handler
        check_pointer_handler(on_click, ("the Button",), what="Button on_click")
        enabled = _expect_flag(enabled, "Button enabled")
        super().__init__(group=group, top_left=top_left)
        self._enabled = enabled
        
        self.value_on = value_on
        self.value_off = value_off

        if cell is not None:
            self._bind_data(cell)
            self._clicked = (cell.value == value_on)
        else:
            self._clicked = False

        self.label = label
        self.on_click = on_click
        
        # Establish boundaries
        if width is not None:
            self.width = width

        self.height = self._theme.row_height if height is None else height
        self._x2 = self._x1 + self.width
        self._y2 = self._y1 + self.height
        self._widget_manager.finish_auto_layout(self)

    @property
    def on_click(self):
        """Function called on a click, ``fn()`` or ``fn(button)``, or ``None``. Writable."""
        return self._on_click

    @on_click.setter
    def on_click(self, value) -> None:
        from .validate import check_pointer_handler
        self._on_click = check_pointer_handler(
            value, ("the Button",), what="Button on_click")

    def _on_mouse_down(self, x, y, button):
        if button == Mouse.BTN_LEFT:
            self._clicked = True  # Set clicked state
            if not self._data_is_linked():
                if self.value_on is not None:
                    self.data.value = self.value_on
                else:
                    self.data.value = self._clicked
            return True
        return False

    def _on_mouse_up(self, x, y, button, click_x, click_y):
        if button == Mouse.BTN_LEFT:
            self._write_released()
            return True
        return False

    def _write_released(self) -> None:
        self._clicked = False  # Clear clicked state
        if not self._data_is_linked():
            if self.value_off is not None:
                self.data.value = self.value_off
            else:
                self.data.value = self._clicked

    def _abandon_press(self, button) -> None:
        # A hold-to-fire button destroyed (or its act ended) while held lets
        # go of its cell: ``value_off``, no click (bug PD1).
        if button == Mouse.BTN_LEFT and self._clicked:
            self._write_released()

    def _on_mouse_click(self, x, y, button):
        if button == Mouse.BTN_LEFT:
            if self.on_click:
                from .validate import call_truncated
                call_truncated(self.on_click, self)
            self._widget_manager.no_focus()
            return True
        return False

    def draw(self, canvas):
        # Create rounded rects using theme's corner radius
        inner_rect = skia.Rect.MakeXYWH(self._x1, self._y1, self.width, self.height)
        #button_rrect = skia.RRect.MakeRectXY(inner_rect, self._theme.corner_radius, self._theme.corner_radius)
        button_rrect = skia.RRect.MakeRectXY(
            inner_rect, self._theme.corner_radius, self._theme.corner_radius
        )
        
        # Use theme-specific button paints
        bg_paint = (self._theme.button_pressed_bkg if self._pressed else 
                   self._theme.button_hover_bkg if self._is_mouse_over else 
                   self._theme.button_bkg)
        
        # Draw filled inner rounded rect
        canvas.drawRRect(button_rrect, bg_paint)
        
        # Draw text using highlight_font
        text_width = measure_text(self._theme.default_font, self.label)
        draw_string_upright(
            canvas,
            self.label,
            self._x1 + (self.width - text_width) / 2,
            text_baseline_centered(self._y1, self.height, self._theme.default_font),
            self._theme.default_font,
            self._theme.highlight_font
        )

class CheckBox(UIWidget):
    """An on/off box with a label in the HUD. ``.checked`` is the value.

    Args:
        cell: boolean data cell it toggles (``st["mute"]``).
        top_left: ``(x, y)`` of the visual top-left; omit to stack in the HUD column.
        size: side of the box in design units (default: theme size).
        label: text next to the box (default ``"CheckBox"``).
        initial: starting state (wins over the cell's value when both are given).
        enabled: ``False`` draws it faded and ignores input (default ``True``).
        group: group tag(s).
    """

    checked = _DataAlias()

    def __init__(self, cell: Attribute | None = _NO_CELL, *, top_left=None, size=None, 
                 label="CheckBox", initial=None, enabled=True, group=None):
        top_left = _geom_point(top_left, "CheckBox")
        size = _geom_size(size, "CheckBox size")
        label = as_payload(label)
        initial = as_payload(initial)
        cell = _require_bound(cell, "CheckBox", "mute")
        enabled = _expect_flag(enabled, "CheckBox enabled")
        super().__init__(group=group, top_left=top_left)
        self._enabled = enabled
        self.label = label
        self._apply_data(cell, initial, default=False)

        # Establish boundaries
        self.size = self._theme.checkbox_size if size is None else size
        pad = self._theme.control_pad
        self._text_width = measure_text(self._theme.default_font, self.label) if self.label else 0
        self._total_width = self.size + pad + self._text_width
        self._x2 = self._x1 + self._total_width
        self._y2 = self._y1 + self.size
        self._widget_manager.finish_auto_layout(self)

    def _on_mouse_click(self, x, y, button):
        if button == Mouse.BTN_LEFT:
            if not self._data_is_linked():
                self.data.value = not self.data.value
            self._widget_manager.no_focus()
            return True
        return False

    def draw(self, canvas):
        rect = skia.Rect.MakeXYWH(self._x1, self._y1, self.size, self.size)
        rrect = skia.RRect.MakeRectXY(rect, self._theme.corner_radius, self._theme.corner_radius)  # Rounded corners using theme
        
        # Choose background and border paints based on state
        if self._pressed:
            bg_paint = self._theme.checkbox_pressed_bkg
            border_paint = self._theme.checkbox_border_checked_drw
        elif self.data.value:
            bg_paint = self._theme.checkbox_checked_bkg
            border_paint = self._theme.checkbox_border_checked_drw
            if self._is_mouse_over:
                bg_paint = self._theme.checkbox_checked_hover_bkg
        else:
            bg_paint = self._theme.checkbox_unchecked_bkg
            border_paint = self._theme.checkbox_border_unchecked_drw
            if self._is_mouse_over:
                bg_paint = self._theme.checkbox_unchecked_hover_bkg

        # Draw background and border
        canvas.drawRRect(rrect, bg_paint)
        canvas.drawRRect(rrect, border_paint)

        # Draw checkmark if checked (y-up: valley toward smaller y, tip toward larger y)
        if self.data.value:
            path = skia.Path()
            path.moveTo(self._x1 + self.size * 0.2, self._y1 + self.size * 0.5)
            path.lineTo(self._x1 + self.size * 0.45, self._y1 + self.size * 0.25)
            path.lineTo(self._x1 + self.size * 0.8, self._y1 + self.size * 0.75)
            canvas.drawPath(path, self._theme.checkbox_check_drw)

        # Draw label using normal_font
        if self.label:
            draw_string_upright(
                canvas,
                self.label,
                self._x1 + self.size + self._theme.control_pad,
                text_baseline_centered(self._y1, self.size, self._theme.default_font),
                self._theme.default_font,
                self._theme.normal_font
            )

_IS_MAC = sys.platform == "darwin"
_UNSYNCED = object()
_clipboard_buffer = ""


def _scena_window():
    """The GLFW window, or ``None`` (headless tests, before ``open_window``)."""
    from .orchestration import ScenaFramework
    return getattr(ScenaFramework.get_instance(), "_window", None)


def _clipboard_get() -> str:
    """System clipboard text; a module buffer when there is no window."""
    win = _scena_window()
    if win is None:
        return _clipboard_buffer
    try:
        raw = glfw.get_clipboard_string(win)
    except Exception:  # empty or non-text clipboard reports a GLFW error
        return ""
    if raw is None:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).decode("utf-8", "replace")
    return str(raw)


def _clipboard_set(text: str) -> None:
    global _clipboard_buffer
    win = _scena_window()
    if win is None:
        _clipboard_buffer = text
        return
    glfw.set_clipboard_string(win, text)


def _edit_mods(mods: int):
    """``(shift, primary, word)`` from GLFW modifier bits.

    Primary is Cmd on macOS, Ctrl elsewhere (clipboard, select all). Word
    moves use Option on macOS, Ctrl elsewhere.
    """
    shift = bool(mods & glfw.MOD_SHIFT)
    primary = _primary_chord(mods)
    word = bool(mods & (glfw.MOD_ALT if _IS_MAC else glfw.MOD_CONTROL))
    return shift, primary, word


# Keys a focused TextInput keeps whatever the modifiers: it acts on them.
_EDIT_KEYS = frozenset({
    "LEFT", "RIGHT", "UP", "DOWN", "HOME", "END",
    "BACKSPACE", "DEL", "ENTER", "TAB", "ESC",
})
# Primary + these stay in the box: select all / clipboard, and undo / redo
# claimed as no-ops (no undo inside the box) so they never reach a document undo.
_BOX_SHORTCUTS = frozenset({"A", "C", "X", "V", "Z", "Y"})
_TEXT_KEYS = frozenset(_PUNCT_KEYS) | {"SPACE"}


def _primary_chord(mods: int) -> bool:
    """Primary held (Cmd on macOS, Ctrl elsewhere), not Windows AltGr.

    AltGr arrives as Ctrl+Alt on Windows and types text (``@``, ``€``).
    """
    if _IS_MAC:
        return bool(mods & glfw.MOD_SUPER)
    ctrl = bool(mods & glfw.MOD_CONTROL)
    if ctrl and sys.platform.startswith("win") and mods & glfw.MOD_ALT:
        return False
    return ctrl


def _types_text(key: str) -> bool:
    """A key that produces a character (letters, digits, punctuation, space)."""
    return len(key) == 1 or key in _TEXT_KEYS


def _is_word_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def _word_left(text: str, i: int) -> int:
    while i > 0 and not _is_word_char(text[i - 1]):
        i -= 1
    while i > 0 and _is_word_char(text[i - 1]):
        i -= 1
    return i


def _word_right(text: str, i: int) -> int:
    n = len(text)
    while i < n and not _is_word_char(text[i]):
        i += 1
    while i < n and _is_word_char(text[i]):
        i += 1
    return i


def _word_span(text: str, i: int):
    """``(start, end)`` of the run of same-kind characters at index ``i``."""
    n = len(text)
    if n == 0:
        return 0, 0
    i = min(max(i, 0), n - 1)
    kind = _is_word_char(text[i])
    a = b = i
    while a > 0 and _is_word_char(text[a - 1]) == kind:
        a -= 1
    while b < n and _is_word_char(text[b]) == kind:
        b += 1
    return a, b


class TextInput(UIWidget):
    """A one-line text box in the HUD.

    Typing edits ``.text``. Enter, Tab, or a click elsewhere commits it to the
    data cell; Esc puts back the cell's value and commits nothing. A box that
    shows the cell's value unchanged never writes it. If the cell holds a
    number and the text does not convert, the cell keeps its old value and
    ``.is_valid`` turns ``False``. Text longer than the box scrolls.

    Keys: arrows, Home / End, Backspace / Del, Shift to select, Cmd (macOS) or
    Ctrl + A / C / X / V for select all and the clipboard, Option (macOS) or
    Ctrl + arrows / Backspace by word. Drag selects; double-click selects a word.

    Args:
        cell: data cell the committed text goes to (``st["player_name"]``).
        top_left: ``(x, y)`` of the visual top-left; omit to stack in the HUD column.
        width, height: size in design units (default: theme size). With a
            ``label``, ``width`` covers the label and the box.
        initial: starting text (a bound cell keeps its value if both are given
            and ``initial`` is omitted).
        placeholder: grey hint shown while the box is empty.
        label: caption to the left of the box; stacked labeled Sliders and
            TextInputs share one label column.
        max_length: most characters typing or pasting can make (default: no limit).
        on_submit: function called when Enter commits, ``fn()`` or ``fn(value)``.
        enabled: ``False`` draws the box faded and ignores input.
        group: group tag(s).
    """

    _tab_stop = True
    _text = ""
    _anchor = 0
    _scroll_x = 0.0
    _text_at_focus = None
    _synced = _UNSYNCED
    _valid = True
    _max_length = None
    _on_submit = None
    _field_x1 = 0.0
    _needed_label_space = 0.0
    _joins_label_column = False

    def __init__(self, cell: Attribute | None = _NO_CELL, *, top_left=None, width=None,
                 height=None, initial=None, placeholder="", label=None, max_length=None,
                 on_submit=None, enabled=True, group=None):
        from .validate import check_pointer_handler, count, expect_bool
        top_left = _geom_point(top_left, "TextInput")
        width = _geom_size(width, "width")
        height = _geom_size(height, "height")
        initial = as_payload(initial)
        placeholder = as_payload(placeholder)
        label = as_payload(label)
        on_submit = as_payload(on_submit)
        # Everything that can raise runs before layout: a rejected TextInput
        # must not move the HUD column.
        enabled = expect_bool(enabled, "TextInput enabled")
        if max_length is not None:
            max_length = count(max_length, "TextInput max_length", 1)
        check_pointer_handler(on_submit, ("the value",), what="TextInput on_submit")
        cell = _require_bound(cell, "TextInput", "player_name")
        starting = initial if initial is not None else (
            cell.value if cell is not None else "")
        if isinstance(starting, bool):
            raise TypeError(
                "TextInput cannot edit a True/False value. Use CheckBox for an "
                "on/off cell."
            )
        super().__init__(group=group, top_left=top_left)
        self._enabled = enabled
        self._apply_data(cell, initial, default="")
        self._resync()

        self.placeholder = placeholder
        self.label = label
        self._max_length = max_length
        self._on_submit = on_submit
        self._cursor_pos = 0
        self._anchor = 0
        self._scroll_x = 0.0
        self._cursor_visible = True
        self._cursor_blink_time = 0.5
        self._last_blink = time.time()
        self._handle_key = True

        if label:
            natural = (measure_text(self._theme.default_font, str(label))
                       + 2 * self._theme.control_pad)
            self._needed_label_space = max(natural, self._theme.min_label_space)

        # Establish boundaries
        if width is not None:
            self.width = width

        self.height = self._theme.row_height if height is None else height
        self._x2 = self._x1 + self.width
        self._y2 = self._y1 + self.height
        self._joins_label_column = getattr(self, '_stack_auto', False) and bool(label)
        self._widget_manager.finish_auto_layout(self)
        self._update_track_layout()
        if self._joins_label_column:
            self._widget_manager.join_label_column(self)

    # -- public ----------------------------------------------------------------------

    @property
    def text(self) -> str:
        """The edit buffer (a plain ``str``), not the cell.

        It follows the cell while the box is not being edited. Writing it
        changes what the box shows; Enter or focus loss commits it like typing.
        """
        return self._text

    @text.setter
    def text(self, value) -> None:
        value = as_payload(value)
        if not isinstance(value, str):
            raise TypeError(
                f"TextInput.text takes a str, got {type(value).__name__} {value!r}. "
                f"To set the value, write the cell (st.name = {value!r})."
            )
        self._text = str(value)   # a KeyName (on_key_down) is kept as a plain str
        n = len(value)
        self._cursor_pos = min(self._cursor_pos, n)
        self._anchor = min(self._anchor, n)

    @property
    def is_valid(self):
        """Return True if the input holds a value that converted to the Attribute type."""
        return self._valid

    @property
    def on_submit(self):
        """Function called when Enter commits, ``fn()`` or ``fn(value)``, or ``None``. Writable.

        It runs after the box has dropped focus, even when the text did not
        change; not on a click elsewhere, and not when a number fails to convert.
        """
        return self._on_submit

    @on_submit.setter
    def on_submit(self, value) -> None:
        from .validate import check_pointer_handler
        self._on_submit = check_pointer_handler(
            value, ("the value",), what="TextInput on_submit")

    @property
    def focused(self) -> bool:
        """True while this box has the keyboard (read-only)."""
        return bool(self._has_focus)

    def focus(self):
        """Give this box the keyboard, as if it were clicked; the text is selected.

        Typing goes here at once (a name prompt, a console after Enter).
        Raises when the box is hidden, destroyed, disabled, or while a modal
        Menu is open.

        Returns this widget (chainable).
        """
        wm = self._widget_manager
        if not getattr(self, "is_alive", True) or self not in wm.widgets:
            from .state import DestroyedError
            raise DestroyedError("This TextInput was destroyed; it cannot take focus.")
        if not self.visible or not getattr(self, "active", True):
            raise RuntimeError(
                "A hidden TextInput cannot take focus. Show it first (visible = True).")
        if not self._enabled:
            raise RuntimeError(
                "A disabled TextInput cannot take focus. Enable it first (enabled = True).")
        if wm._modal_consumes():
            raise RuntimeError(
                "A modal Menu is open. Focus the box after it closes "
                "(in on_choose, or after await menu).")
        wm.set_focus(self)
        return self

    # -- layout ----------------------------------------------------------------------

    def _update_track_layout(self, label_space: float | None = None) -> None:
        """Place the box after the label column (shared with stacked Sliders)."""
        if label_space is None:
            label_space = self._needed_label_space if self.label else 0.0
        min_field = 2 * self._theme.control_pad + 8.0
        self._field_x1 = min(self._x1 + label_space, self._x2 - min_field)

    # -- cell <-> text -------------------------------------------------------------------

    @staticmethod
    def _format(val) -> str:
        if isinstance(val, bool):
            return str(val)
        if isinstance(val, int):
            return f"{val:d}"
        if isinstance(val, float):
            return format(val, ".15g")
        return str(val)

    @staticmethod
    def _sync_key(val):
        return (type(val), val)

    def _resync(self) -> None:
        """Show the cell's value; clears the invalid state."""
        val = self.data.value
        self._text = self._format(val)
        self._synced = self._sync_key(val)
        self._valid = True
        n = len(self._text)
        self._cursor_pos = min(self._cursor_pos, n)
        self._anchor = min(self._anchor, n)

    def _maybe_resync(self) -> None:
        """Follow the cell while not editing, but only when the cell changed.

        A failed commit leaves the cell as it was, so the typed text stays
        on screen (red) until the user edits it or the cell changes.
        """
        if not self._has_focus:
            self._resync_if_cell_changed()

    def _resync_if_cell_changed(self) -> None:
        try:
            same = self._sync_key(self.data.value) == self._synced
        except Exception:
            same = False
        if not same:
            self._resync()

    def _commit(self) -> bool:
        """Convert ``.text`` to the cell's type and write it. False if it did not convert."""
        if self._data_is_linked():
            return True
        raw = self._text.strip()
        current = self.data.value
        try:
            if isinstance(current, bool):
                raise ValueError("TextInput does not edit a True/False cell")
            if isinstance(current, int):
                converted = int(raw)
            elif isinstance(current, float):
                converted = float(raw)
            else:
                converted = raw
        except (ValueError, TypeError):
            self._valid = False
            self._synced = self._sync_key(current)
            return False
        self.data.value = converted
        self._resync()
        return True

    def _changed_since_focus(self) -> bool:
        return self._text_at_focus is not None and self._text != self._text_at_focus

    # -- focus -------------------------------------------------------------------------

    def _on_focus_gained(self):
        # Focus is already set here, so check the cell directly (the box may
        # not have been drawn since the cell changed).
        self._resync_if_cell_changed()
        # What "unchanged" means: the cell's own text, so a box showing the
        # cell never writes it back (0.125 stays 0.125), while a ``.text``
        # write made before focus still commits.
        self._text_at_focus = self._format(self.data.value)
        self._anchor = 0
        self._cursor_pos = len(self._text)
        self._restart_blink()
        return True

    def _on_focus_lost(self):
        if self._changed_since_focus():
            self._commit()
        self._text_at_focus = None
        self._anchor = self._cursor_pos = 0
        self._scroll_x = 0.0
        return True

    def _submit(self) -> None:
        if self._changed_since_focus():
            ok = self._commit()
        else:
            ok = self._valid
        self._text_at_focus = self._text  # focus loss below must not commit again
        self._widget_manager.no_focus()
        if ok and self._on_submit is not None and not self._data_is_linked():
            from .validate import call_truncated
            call_truncated(self._on_submit, self.data.value)

    def _cancel(self) -> None:
        self._resync()
        self._text_at_focus = self._text
        self._widget_manager.no_focus()

    # -- editing -----------------------------------------------------------------------

    def _restart_blink(self) -> None:
        self._cursor_visible = True
        self._last_blink = time.time()

    def _sel_range(self):
        n = len(self._text)
        a = min(max(self._anchor, 0), n)
        b = min(max(self._cursor_pos, 0), n)
        return (a, b) if a <= b else (b, a)

    def _has_selection(self) -> bool:
        a, b = self._sel_range()
        return a != b

    def _move(self, to: int, extend: bool) -> None:
        to = min(max(to, 0), len(self._text))
        self._cursor_pos = to
        if not extend:
            self._anchor = to
        self._restart_blink()

    def _replace(self, a: int, b: int, s: str) -> None:
        """Replace ``text[a:b]`` with ``s`` (clipped to ``max_length``)."""
        text = self._text
        if self._max_length is not None:
            room = self._max_length - (len(text) - (b - a))
            s = s[:max(0, room)]
        if a == b and not s:
            return
        self._text = text[:a] + s + text[b:]
        self._cursor_pos = self._anchor = a + len(s)
        self._valid = True
        self._restart_blink()

    def _insert(self, s: str) -> None:
        a, b = self._sel_range()
        self._replace(a, b, s)

    def _delete(self, a: int, b: int) -> None:
        if a != b:
            self._replace(min(a, b), max(a, b), "")

    def _claims_key(self, key, mods) -> bool:
        """Keep editing keys, keys that type text, and the box's Primary shortcuts.

        Primary + another key (Cmd+S), F-keys, Page Up / Down and Insert go to
        the game; the manager commits this box first (``_before_key_leaves``).
        """
        if key in _EDIT_KEYS:
            return True
        if _primary_chord(mods):
            return key in _BOX_SHORTCUTS
        return _types_text(key)

    def _before_key_leaves(self) -> None:
        """Commit pending text (keeping focus) before a shortcut reaches the game."""
        if not self._has_focus or self._data_is_linked() or not self._changed_since_focus():
            return
        if self._commit():
            self._text_at_focus = self._text

    def _on_key(self, key):
        if not self._has_focus:
            return False
        shift, primary, word = _edit_mods(self._widget_manager._key_mods)
        text = self._text
        n = len(text)
        cur = min(self._cursor_pos, n)
        read_only = self._data_is_linked()

        if key == "ESC":
            self._cancel()
        elif key == "ENTER":
            self._submit()
        elif key == "TAB":
            self._widget_manager.focus_next(self, backwards=shift)
        elif primary and key == "A":
            self._anchor, self._cursor_pos = 0, n
        elif primary and key in ("C", "X"):
            a, b = self._sel_range()
            if a != b:
                _clipboard_set(text[a:b])
                if key == "X" and not read_only:
                    self._delete(a, b)
        elif primary and key == "V":
            if not read_only:
                pasted = _clipboard_get().replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
                self._insert("".join(c for c in pasted if c >= " "))
        elif key in ("LEFT", "RIGHT"):
            left = key == "LEFT"
            if _IS_MAC and primary:
                to = 0 if left else n
            elif word:
                to = _word_left(text, cur) if left else _word_right(text, cur)
            elif self._has_selection() and not shift:
                to = self._sel_range()[0 if left else 1]
            else:
                to = cur - 1 if left else cur + 1
            self._move(to, shift)
        elif key in ("HOME", "END"):
            self._move(0 if key == "HOME" else n, shift)
        elif key == "BACKSPACE" and not read_only:
            if self._has_selection():
                self._delete(*self._sel_range())
            elif _IS_MAC and primary:
                self._delete(0, cur)
            elif word:
                self._delete(_word_left(text, cur), cur)
            elif cur > 0:
                self._delete(cur - 1, cur)
        elif key == "DEL" and not read_only:
            if self._has_selection():
                self._delete(*self._sel_range())
            elif word:
                self._delete(cur, _word_right(text, cur))
            elif cur < n:
                self._delete(cur, cur + 1)
        return True

    def _on_char(self, char):
        if not self._has_focus:
            return False
        if self._data_is_linked() or char < " ":
            return True
        self._insert(char)
        return True

    # -- pointer -----------------------------------------------------------------------

    def _text_x0(self) -> float:
        """Design x of the first character (scroll applied)."""
        return self._field_x1 + self._theme.control_pad - self._scroll_x

    def _index_at_x(self, x: float) -> int:
        """Character boundary nearest to design ``x`` (kerning-correct, scrolled)."""
        font = self._theme.default_font
        text = self._text
        rel = x - self._text_x0()
        lo, hi = 0, len(text)
        # First i whose boundary midpoint (prefix i-1 .. prefix i) is past rel.
        while lo < hi:
            mid = (lo + hi + 1) // 2
            left = measure_text(font, text[:mid - 1])
            right = measure_text(font, text[:mid])
            if (left + right) / 2 <= rel:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def _shift_held(self) -> bool:
        win = _scena_window()
        if win is None:
            return bool(self._widget_manager._key_mods & glfw.MOD_SHIFT)
        return (glfw.get_key(win, glfw.KEY_LEFT_SHIFT) == glfw.PRESS
                or glfw.get_key(win, glfw.KEY_RIGHT_SHIFT) == glfw.PRESS)

    def _on_mouse_down(self, x, y, button):
        if button == Mouse.BTN_LEFT and self.contains_point(x, y):
            self._move(self._index_at_x(x), self._shift_held())
            return True
        return False

    def _on_mouse_drag(self, x, y):
        if self._pressed and self._has_focus:
            self._move(self._index_at_x(x), True)
        return True

    def _on_mouse_double_click(self, x, y, button):
        if button == Mouse.BTN_LEFT and self._has_focus:
            a, b = _word_span(self._text, self._index_at_x(x))
            self._anchor, self._cursor_pos = a, b
            return True
        return False

    # -- draw --------------------------------------------------------------------------

    def _ensure_cursor_visible(self) -> None:
        font = self._theme.default_font
        pad = self._theme.control_pad
        inner = max(1.0, (self._x2 - self._field_x1) - 2 * pad)
        cx = measure_text(font, self._text[:min(self._cursor_pos, len(self._text))])
        total = measure_text(font, self._text)
        s = self._scroll_x
        if cx - s > inner:
            s = cx - inner
        if cx - s < 0:
            s = cx
        self._scroll_x = max(0.0, min(s, max(0.0, total - inner)))

    def draw(self, canvas):
        self._maybe_resync()
        theme = self._theme
        font = theme.default_font
        pad = theme.control_pad
        text = self._text
        baseline = text_baseline_centered(self._y1, self.height, font)

        if self.label:
            draw_string_upright(canvas, str(self.label), self._x1, baseline,
                                font, theme.normal_font)

        fx = self._field_x1
        rect = skia.Rect.MakeXYWH(fx, self._y1, self._x2 - fx, self.height)
        rrect = skia.RRect.MakeRectXY(rect, theme.corner_radius, theme.corner_radius)

        bg_paint = (theme.text_input_invalid_bkg if not self._valid else
                    theme.text_input_focused_bkg if self._has_focus else
                    theme.text_input_hover_bkg   if self._is_mouse_over else
                    theme.text_input_bkg)
        border_paint = (theme.text_input_focused_border_drw if self._has_focus else
                        theme.text_input_border_drw)
        canvas.drawRRect(rrect, bg_paint)
        canvas.drawRRect(rrect, border_paint)

        if self._has_focus:
            self._ensure_cursor_visible()
        else:
            self._scroll_x = 0.0
        x0 = self._text_x0()

        canvas.save()
        canvas.clipRect(skia.Rect.MakeLTRB(fx + 1, self._y1, self._x2 - 1, self._y1 + self.height))
        if self._has_focus and self._has_selection():
            a, b = self._sel_range()
            sx1 = x0 + measure_text(font, text[:a])
            sx2 = x0 + measure_text(font, text[:b])
            canvas.drawRect(
                skia.Rect.MakeLTRB(sx1, self._y1 + pad / 2, sx2, self._y1 + self.height - pad / 2),
                theme.text_input_selection_bkg)
        if text:
            draw_string_upright(canvas, text, x0, baseline, font, theme.highlight_font)
        elif not self._has_focus and self.placeholder:
            draw_string_upright(canvas, self.placeholder, fx + pad, baseline,
                                font, theme.discrete_font)

        if self._has_focus and not self._data_is_linked():
            now = time.time()
            if now - self._last_blink >= self._cursor_blink_time:
                self._cursor_visible = not self._cursor_visible
                self._last_blink = now
            if self._cursor_visible:
                cursor_x = x0 + measure_text(font, text[:min(self._cursor_pos, len(text))])
                canvas.drawLine(cursor_x, self._y1 + pad, cursor_x,
                                self._y1 + self.height - pad, theme.high_drw)
        canvas.restore()


# Unknown keyword on a widget (``Button(x=10)``): the actor wrapper names the
# fix with these hints (validate.install_friendly_constructor / _call_hints).
for _widget in (Button, TextInput, DropDown, Slider, CheckBox):
    _widget._call_hints = widget_placement_hints(_widget.__name__)
del _widget
