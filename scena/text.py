"""Caption Graphic: view HUD ``Text`` or world caption.

Replaces author ``Label``. Placement is always a point:
  - omit every placement keyword → reserved ``ui`` + HUD column auto-stack
  - ``top_left=`` / ``top_center=`` / ``top_right=`` → that point of the layout
    box is pinned; the string grows away from it (down, and left / both / right).
    Layer omitted → ``ui`` (still advances the HUD column unless
    ``stack=False``); a world ``layer=`` → world caption, never in the column.
  - ``center=`` (layer omitted) → world ``default``; the box grows around it
  - ``box=`` → ``center=`` the region's centre on ``ui``, ``width=`` its width
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional, Sequence, Tuple, TYPE_CHECKING, Union

import skia

from .color import Color, ColorLike
from .entity import (
    Graphic,
    _STYLE_PAINT,
    _USE_LAYER_DEFAULT,
    _refuse_if_destroyed,
)
from .registry import UI_LAYER, layer_is_ui, normalize_layer_name
from .shapes import Point, get_xy, _takein_xy_float, _ensure_writable, _bare_attr
from .validate import MIN_SCALE, magnitude, fixed_magnitude
from .state import (
    Attribute,
    ContainerSlot,
    ValueSlot,
    FieldRef,
    FieldType,
    LinkedAttributeError,
    as_payload,
    bound_cell,
    unbound_value_hint,
    _init_composite,
    _pull_channel_links,
)
from .style import PaintState
from .uiwidget import (
    _make_ui_font,
    build_upright_text_path,
    draw_string_upright,
    measure_text,
    text_baseline_in_box,
    text_line_height,
)


# Cheap caption Glow() — two ADD strokes, no MaskFilter. Tune here.
# Glow() default blur ≈ 14 → outer ~5.6 px @ 0.26, inner ~3.5 px @ 0.48.
_TEXT_GLOW_OUTER_BLUR = 0.60
_TEXT_GLOW_OUTER_MIN = 3.0
_TEXT_GLOW_OUTER_MAX = 18.0
_TEXT_GLOW_INNER_RATIO = 0.62
_TEXT_GLOW_INNER_MIN = 0.6
_TEXT_GLOW_OUTER_ALPHA = 0.36
_TEXT_GLOW_INNER_ALPHA = 0.52

_ALIGN_VALUES = frozenset({"left", "center", "right"})


def _normalize_text_align(value: Any) -> str:
    """Return ``'left'`` / ``'center'`` / ``'right'`` from str or ``XPos``."""
    from .shapes import XPos
    raw = as_payload(value)
    if isinstance(raw, XPos):
        raw = raw.value
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in _ALIGN_VALUES:
            return key
    raise TypeError(
        f"Text align= must be 'left', 'center', or 'right' (or XPos), got {value!r}"
    )


def _reject_layout_link(value: Any, what: str) -> None:
    """``width`` sizes the caption; it is not a pose link."""
    if callable(value) and not isinstance(value, type):
        raise TypeError(
            f"Text {what} is layout, not pose. Link the caption's position "
            "instead: Text(top_left=lambda: …) or Text(center=lambda: …)."
        )


# Anchor keyword → the in-box glyph alignment it implies by default.
_ANCHORS = ("top_left", "top_center", "top_right")
_ANCHOR_ALIGN = {"top_left": "left", "top_center": "center", "top_right": "right"}
_TEXT_PARTS = ("center",) + _ANCHORS

_TEXT_PLACEMENT_HINT = (
    "Text is placed by a point: top_left=(x, y) (visual top-left; also "
    "top_center= / top_right=), center=, or box="
)
# Spellings other frameworks use; each gets the same orientation.
if TYPE_CHECKING:
    from .shapes import XPos
    from .visuals import Visual

# A placement point: (x, y), Point, Vec2, a Graphic (its center), or a
# formula / pair with a formula (links, like ``Rect(center=lambda: …)``).
TextPoint = Union[Tuple[float, float], Point, Any, Callable[[], Any]]

TEXT_PLACEMENT_HINTS = {
    key: _TEXT_PLACEMENT_HINT
    for key in ("x1", "y1", "x2", "y2", "x", "y", "pos", "position")
}


def _is_link_spec(value: Any) -> bool:
    """True when construction links (callable, or a 2-tuple with a callable)."""
    if callable(value) and not isinstance(value, type):
        return True
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return any(callable(v) and not isinstance(v, type) for v in value)
    return False


def _anchor_xy(value: Any, name: str) -> tuple[float, float]:
    """Snapshot point-like → finite ``(x, y)``; raises before any HUD call (A5)."""
    from .scenamath import _as_xy
    from .validate import number
    raw = as_payload(value)
    try:
        x, y = _as_xy(raw)
    except (TypeError, ValueError, AttributeError):
        raise TypeError(
            f"Text {name}= must be a point: (x, y), a Point, or a lambda; "
            f"got {value!r}"
        ) from None
    return float(number(as_payload(x), f"Text {name} x")), float(
        number(as_payload(y), f"Text {name} y")
    )


def _normalize_text_width(value: Any) -> Optional[float]:
    """Return ``None`` (content-sized) or a positive layout width."""
    raw = as_payload(value)
    if raw is None:
        return None
    _reject_layout_link(raw, "width")
    from .validate import fixed_magnitude
    return fixed_magnitude(raw, "Text width", positive=True)   # not reactive: a function raises


def _has_line_breaks(text: str) -> bool:
    """True when the caption has an explicit hard break (``\\n`` or ``\\r``)."""
    return "\n" in text or "\r" in text


def _split_text_lines(text: str) -> list[str]:
    """Hard breaks only. ``\\r\\n`` and lone ``\\r`` count as one break each.

    Empty rows stay (``"a\\n"`` is two lines). No word wrap.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _read_by_a_link(point) -> bool:
    """A link reads this point: a whole-point link (``_link_source``) or a
    link on one of its fields (``q["x"] @= t.top_left["x"]``: a field
    anchor). Then a raw float write would leave the link stale: the writer
    notifies (D25; review 2026-10-09 S6-5)."""
    d = point.__dict__
    return bool(d.get('_link_source') or d.get('_field_anchors'))


class _TextPartSlot(ContainerSlot):
    """``Text.center`` / ``top_left`` / ``top_center`` / ``top_right``.

    The string (formula text is pull) and the other width inputs never notify,
    so a derived point can lag the string showing now. Reading a part from
    outside the layout code re-lays-out first, so a relative write
    (``center.x += 7``), an absolute one (``center = P``, ``tween``), every
    pose verb, and every formula that reads a part start from the current
    string. Layout code runs under ``_in_text_layout`` and sees the raw point.

    ``center`` of a pose caption (``center=`` / ``box=``) is the pose itself,
    so only anchored captions pay the refresh on a ``center`` read.
    """

    def __get__(self, instance, owner):
        if instance is not None:
            d = instance.__dict__
            if (
                d.get("_layout_ready")
                and not d.get("_in_text_layout")
                and not d.get("_destroyed")
                and (self.name != "center" or d.get("_anchor") is not None)
            ):
                instance._refresh_layout()
        return super().__get__(instance, owner)


def _refuse_linked_text_paint(text, names, operation: str) -> None:
    from .entity import _refuse_linked_channel
    _refuse_linked_channel(text, names, operation)



class TextValue(str):
    """What ``t.text`` reads: the text shown, a plain ``str`` to the author.

    Until 0.9.0 ``t.text`` was the cell. Its spellings (``.value``,
    ``.unlink()``, ``.is_linked``, ``t.text @= …``) now raise naming the
    bracket handle ``t["text"]`` (Scena Design, "Compatibility and versions").
    """

    __slots__ = ()

    def __new__(cls, payload, owner=None):
        return str.__new__(cls, payload)

    def _moved(self, what: str):
        raise AttributeError(
            f'Text.text is the text itself, a str, since 0.9.0: read it as t.text. '
            f'The link handle is the bracket: t["text"]{what}.'
        )

    @property
    def value(self):
        self._moved(".value")

    @property
    def is_linked(self):
        self._moved(".is_linked")

    def unlink(self):
        self._moved(".unlink()")

    def __imatmul__(self, other):
        raise TypeError(
            'Text.text is the text itself, a str, since 0.9.0. '
            'Link the text with the bracket: t["text"] @= lambda: …'
        )


class Text(Graphic, PaintState):
    """Single author caption class (HUD or world).

    Paint: ``color=`` / :meth:`set_color`, ``background=``, ``.fill`` / ``.line`` /
    ``.line_width`` (Gradient legal on fill and line). Appearance stamp: ``.glow``
    only (``Glow`` / ``CheapGlow``). No costume ``.visual``.

    Placement is one point, never scalar coordinates. ``top_left=`` /
    ``top_center=`` / ``top_right=`` pin that point of the layout box; the
    string grows away from it (always downward). A callable, or a 2-tuple with
    a callable, links like ``Rect(top_left=)``: the anchor is then the only
    Defining pose and ``center`` is derived. ``center=`` is the pose itself (the
    box grows around it). ``box=`` is ``center=`` the region's centre with
    ``width=`` its width. Omit all of them → HUD column slot (``top_left``).
    ``.top_left`` / ``.top_center`` / ``.top_right`` / ``.center`` read the
    current layout box.

    HUD placement (layer ``ui``) shares the widget column: an explicit anchor
    still advances it; ``stack=False`` opts out (framework FPS / error
    captions). World captions (``center=``, or an anchor with a world
    ``layer=``) never touch it.

    Optional ``width=`` fixes the layout box (overflow clips; no wrap). ``align=``
    places each line inside the box (``width=`` or the widest line) and never
    moves the anchor; its default follows the anchor. ``\\n`` is a hard line
    break (height is n × line metrics). The HUD column does not reflow if the
    line count changes after construct.

    Args:
        text: What to show: a string, a data cell (``st["score"]``, shown live) or
            a function (linked, updates live). A number raises: write a string.
        center: Middle of the text box.
        top_left: Pin the visual top-left corner here (the text grows right and down).
        top_center: Pin the top-center here.
        top_right: Pin the top-right corner here.
        width: Fixed box width in design units (wraps lines); default: as wide as the
            text.
        align: ``"left"`` · ``"center"`` · ``"right"`` inside the box.
        layer: Draw layer (default: ``"ui"``, the HUD — immune to the camera).
        font_size: Glyph size in design units.
        font: Font family name or a ``.ttf`` / ``.otf`` file.
        color: Text color (default white).
        background: Panel color behind the text, or ``None``.
        glow: ``True``, a color, or ``Glow(...)`` / ``CheapGlow(...)`` for a glowing
            caption.
        stack: In the HUD with no position: stack in the widget column (default
            ``True``).
        group: Group tag(s).
        box: Place and size by a Box (its own form).
        angle: Heading at construction, in degrees (turns about the center);
            a function links it.
    """

    # A caption does not collide: ``text.hitbox`` raises (measure with ``.box``).
    _has_no_hitbox = True
    # Appearance links (Reactive Design — Appearance links). No flips: Text
    # cannot be mirrored.
    _property_link_extra = frozenset({
        "color", "fill", "line", "line_width", "background", "visible"})
    # ``text["flip_x"] @= …`` answers as ``text.flip_x = True`` does (B7, RA
    # 0.9.0: it said "set it with text.flip_x = …", which raises too). Read by
    # ``entity._ink_link_forbidden_message``.
    _link_refusals = {
        f"flip_{axis}": (
            f"{{cls}}.flip_{axis} cannot be linked with @=: Text cannot be "
            f"flipped, because mirrored text is unreadable. Turn it instead: "
            f"text[\"angle\"] @= lambda: 180 if … else 0 (angle = 180 turns "
            f"it upside down)."
        )
        for axis in ("x", "y")
    }
    # Text's color is its fill only: a linked color leaves ``.line`` free.
    _paint_fields = {
        "color": ("color", "fill"),
        "fill": ("fill", "color"),
        "line": ("line",),
    }

    # Unknown keyword (``Text("hi", x=10)``): the actor wrapper names the fix.
    _call_hints = TEXT_PLACEMENT_HINTS

    center = _TextPartSlot(Point)
    top_left = _TextPartSlot(Point)
    top_center = _TextPartSlot(Point)
    top_right = _TextPartSlot(Point)
    # ``t.text`` reads the text shown, a str (persona probes PP, 0.9.0: it was
    # the cell); the link handle is ``t["text"]``, the cell ``_text_cell()``.
    text = ValueSlot(Attribute, read=lambda v, owner, name: TextValue(v, owner))

    # Class keywords of an author subclass (``class Placar(Text, font_size=32,
    # color="gold", group="hud")``): the look, never the content or the
    # placement (``class_defaults``; AC15 follow-up, 2026-10-10).
    _class_defaults: dict = {}
    _CLASS_KEYS = frozenset({"font_size", "font", "color", "background", "glow",
                             "align", "width", "group"})
    _CLASS_PLACEMENT = frozenset({"center", "top_left", "top_center", "top_right",
                                  "box", "layer", "stack", "angle"})

    @classmethod
    def _class_keywords(cls) -> frozenset:
        return Text._CLASS_KEYS

    def __init_subclass__(cls, **kwargs):
        from ._pkg import is_framework_module
        if not is_framework_module(cls.__module__):
            from .class_defaults import take_class_defaults
            take_class_defaults(
                cls, kwargs, kind=Text, allowed=Text._CLASS_KEYS,
                placement=Text._CLASS_PLACEMENT,
                refused={"text": (
                    f"text= is the content of one {cls.__name__}, not a class default. "
                    f"Pass it when you make one: {cls.__name__}(\"...\"), or set "
                    f"self.text in setup()."
                )},
            )
            for key in ("font_size", "width"):     # None defaults: not in the generic check
                value = cls._class_defaults.get(key)
                if value is not None and not callable(value):
                    fixed_magnitude(value, f"{cls.__name__} {key}")
        super().__init_subclass__(**kwargs)

    def __init__(
        self,
        text: Union[str, Attribute, Callable[[], Any], None] = None,
        *,
        center: Optional[TextPoint] = None,
        top_left: Optional[TextPoint] = None,
        top_center: Optional[TextPoint] = None,
        top_right: Optional[TextPoint] = None,
        width: Union[float, Callable[[], float], None] = None,
        align: Union[str, XPos, None] = None,
        layer: Union[str, int, None] = _USE_LAYER_DEFAULT,
        font_size: Union[float, Callable[[], float], None] = None,
        font: Optional[str] = None,
        color: Optional[ColorLike] = None,
        background: Optional[ColorLike] = None,
        glow: Optional[Visual] = None,
        stack: bool = True,
        group: Optional[Union[str, Sequence[str]]] = None,
        box: Any = None,
        angle: Union[float, Callable[[], float], None] = None,
    ):
        defaults = type(self)._class_defaults
        if defaults:
            # Class keywords fill what the call left out (the instance wins).
            d = defaults.get
            if width is None:
                width = d("width")
            if align is None:
                align = d("align")
            if font_size is None:
                font_size = d("font_size")
            if font is None:
                font = d("font")
            if color is None:
                color = d("color")
            if background is None:
                background = d("background")
            if glow is None:
                glow = d("glow")
            if group is None:
                group = d("group")
        given = [
            (name, value)
            for name, value in (
                ("top_left", top_left),
                ("top_center", top_center),
                ("top_right", top_right),
            )
            if value is not None
        ]
        if len(given) > 1:
            names = " and ".join(f"{name}=" for name, _ in given)
            raise TypeError(
                f"Text takes one anchor (top_left=, top_center=, or top_right=), "
                f"got {names}"
            )
        anchor, anchor_value = given[0] if given else (None, None)

        from_box = box is not None
        if from_box:
            if center is not None or anchor is not None:
                raise TypeError(
                    "Text(box=) cannot mix with center= / top_left= / "
                    "top_center= / top_right= — box= is its own constructor family"
                )
            from .box import region_frame
            cx, cy, rw, _rh, _ang = region_frame(box)
            if width is None and rw > 0.0:
                width = rw
            center = (cx, cy)

        # Positional / text=: a cell (``st["score"]``, a standalone Attribute)
        # links one way, as ``t["text"] @= st["score"]`` would; anything else is
        # the text, or a function that links.
        initial_text = None
        bounded: Optional[Attribute] = bound_cell(text)
        if bounded is None:
            if isinstance(text, FieldRef):
                raise TypeError("Text(field): " + unbound_value_hint('Text(st["score"])', text, "score"))
            if isinstance(text, (int, float)):
                # ``Text(st.score)`` reads the number (0.8.0): it would show a
                # snapshot where the author meant the live cell.
                raise TypeError(
                    f"Text({text!r}) takes a string: Text(\"{text}\") or "
                    f"Text(str(n)). To show a st field live, pass it with "
                    f"brackets: Text(st[\"score\"]) (st.score reads the value "
                    f"since 0.8.0), or a formula: Text(lambda: f\"Score {{st.score}}\")."
                )
            if text is not None:
                initial_text = text

        center = as_payload(center)
        # Validate a snapshot anchor before anything touches the HUD column (A5).
        anchor_linked = anchor is not None and _is_link_spec(anchor_value)
        if anchor is not None and not anchor_linked:
            anchor_value = _anchor_xy(anchor_value, anchor)
        font_size = as_payload(font_size)
        font = as_payload(font)
        color = as_payload(color)
        background = as_payload(background)
        fixed_width = _normalize_text_width(width)

        has_center = center is not None
        from .validate import expect_bool
        participate = expect_bool(stack, "Text stack")
        if has_center and anchor is not None:
            raise TypeError(
                f"Text cannot take both center= and {anchor}= — one point "
                "places the caption"
            )

        if align is None:
            resolved_align = (
                "center" if has_center else _ANCHOR_ALIGN.get(anchor, "left")
            )
        else:
            resolved_align = _normalize_text_align(align)

        if layer is _USE_LAYER_DEFAULT:
            resolved = "default" if (has_center and not from_box) else UI_LAYER
        else:
            resolved = normalize_layer_name(layer)
            if (
                resolved is not None
                and not layer_is_ui(resolved)
                and not has_center
                and anchor is None
            ):
                raise TypeError(
                    f"World Text on layer {resolved!r} needs a point: "
                    "top_left= (or top_center= / top_right=), center=, or box="
                )
        on_ui = resolved is not None and layer_is_ui(resolved)
        auto_stack = anchor is None and not has_center and on_ui
        if auto_stack:
            anchor = "top_left"

        # Which parts are Defining. The anchor (when any) is; ``center`` is too
        # unless the anchor links — then ``center`` is derived, like
        # ``Rect(top_left=lambda: …).center``. The other top parts are derived.
        if anchor is None:
            derived = set(_ANCHORS)
        elif anchor_linked:
            derived = set(_TEXT_PARTS) - {anchor}
        else:
            derived = set(_ANCHORS) - {anchor}
        self.__dict__["_defining_part_names"] = frozenset(
            set(self._field_slots()) - derived
        )
        # The construction model: a runtime placement link changes the Defining
        # set while it links, and unlinking restores this (_sync_placement_model).
        self.__dict__["_built_defining"] = self.__dict__["_defining_part_names"]

        PaintState.__init__(self)
        # Caption default: white fill, no stroke. color=/set_color must not
        # install Shape's contrast outline (that makes glyphs look double-struck).
        self._fill = Color(1.0, 1.0, 1.0, 1.0)
        self._line = None
        self._line_width = 1.0
        self._look_identity = None
        self._is_fill_paint_dirty = True
        self._is_line_paint_dirty = True

        Graphic.__init__(self, layer=resolved, group=group)

        wm = self._widget_manager()
        theme = wm.widget_theme if wm is not None else None
        if theme is not None:
            theme._ensure()
        self._theme = theme
        default_size = 16.0 if theme is None else float(theme.font_size)
        self._font_spec = None if font is None or font == "" else str(font)
        self.font_size = default_size if font_size is None else font_size
        from .validate import _is_formula
        # A function links it after construction, like ``t["background"] @=``.
        background_link = background if _is_formula(background) else None
        self._background = (None if background is None or background_link is not None
                            else Color(background))
        self._auto_layout_top = None
        self._width = fixed_width
        self._align = resolved_align
        # Anchor part name, or None for a pose caption (center= / box=).
        self._anchor = anchor
        # Layout record: the box edges (min / max, y-up), the pinned point and
        # the centre last published. A later ``center`` write is a translation.
        self._x1 = 0.0
        self._y1 = 0.0
        self._x2 = 0.0
        self._y2 = 0.0
        self._pin = None
        self._center_rec = None

        if color is not None:
            if _is_formula(color):
                self._link_field("color", color)    # like ``t["color"] @= …``
            else:
                self.set_color(color)
        if background_link is not None:
            self._link_field("background", background_link)

        if bounded is not None:
            # One way, like every other link: the text shows the cell, and
            # ``t.text = …`` raises LinkedAttributeError naming the cell. Before,
            # the text *was* the cell, so ``t.text = "oi"`` wrote ``st.score``
            # (a display that edited the game state, far from any error).
            self._text_cell().value = ""
            self._link_field("text", bounded)
        elif callable(initial_text):
            # ``Text(lambda: f"Pontos {st.pontos}")``: a function links, the
            # same link as ``t["text"] @= fn`` (same source rules), before the
            # first layout reads it (review 2026-10-09 S6-7; the docstring and
            # the constructor-links rule promised it).
            self._text_cell().value = ""
            self._link_field("text", initial_text)
        else:
            seed = "no label" if initial_text is None else initial_text
            self._text_cell().value = seed

        hud = on_ui and wm is not None
        if anchor is None:
            with self._batch_update():
                _init_composite(self.center, center if has_center else (0.0, 0.0))
            self.__dict__["_layout_ready"] = True
            self._refresh_layout()
        else:
            if auto_stack:
                if hud and participate:
                    anchor_value = wm.begin_hud_item(self)
                elif hud:
                    anchor_value = wm.peek_hud_slot()
                else:
                    anchor_value = (0.0, 0.0)
            part = getattr(self, anchor)
            with self._batch_update():
                _init_composite(part, anchor_value)
            # Create ``center`` before the first layout publishes it; created
            # later it would start at (0, 0) and read as a translation.
            self.center
            self.__dict__["_layout_ready"] = True
            self._refresh_layout()
            if hud:
                wm.finish_auto_layout(self, participate=participate)

        if glow is not None:
            self.glow = glow
        if angle is not None:
            self._init_heading(angle)

    def _widget_manager(self):
        try:
            from .orchestration import ScenaFramework
            fw = ScenaFramework.get_instance()
            return getattr(fw, "widget_manager", None)
        except Exception:
            return None

    def _displayed_text(self) -> str:
        from .transients import active_flash_text
        flash = active_flash_text(self)
        if flash is not None:
            return flash
        return str(self._text_cell().value)

    def _text_cell(self) -> Attribute:
        """The ``text`` cell (``t["text"]`` links it; ``t.text`` reads its str).
        Made on the first read, then held in ``__dict__`` (the slot's own store)."""
        c = self.__dict__.get("text")
        return c if c is not None else Text.__dict__["text"].cell(self)

    def _needs_outline_path(self) -> bool:
        """True when fill/line is a shader material (Gradient / Texture / …).

        Solid Color + optional Glow can use GPU ``drawString`` (glyph atlas).
        Path outlines exist so shaders share the Shape local frame.
        """
        fill = self._fill
        if fill is not None and not isinstance(fill, Color):
            return True
        line = self._line
        if line is not None and not isinstance(line, Color):
            return True
        return False

    def flash_text(self, text, duration: float = 1.0, *, on_done=None):
        """Show ``text`` for ``duration`` seconds, then go back to the cell's text.

        The link to the data cell stays; only the display is overridden.

        Args:
            text: what to show meanwhile.
            duration: seconds (default 1).
            on_done: optional function called when the flash ends.

        Returns this Text (chainable, like the widgets' ``flash_text``).
        """
        from .transients import flash_text as _flash_text
        _flash_text(self, text, duration, on_done=on_done)
        return self

    def _glyph_path0(self) -> skia.Path:
        """Origin-space glyph outlines, rebuilt only when ink/font change."""
        content = self._displayed_text()
        key = (content, float(self._font_size), id(self._skia_font))
        if getattr(self, "_gp0_key", None) != key:
            path = build_upright_text_path(content, 0.0, 0.0, self._skia_font)
            self._gp0 = path
            self._gp0_key = key
            self._gp0_bounds = None
            if path is not None and not path.isEmpty():
                self._gp0_bounds = path.computeTightBounds()
            self._gp_box_key = None
        return self._gp0

    def _glyph_box_size(self) -> tuple[float, float]:
        """Advance × line metrics, or tight ink when a shader needs the path.

        A hard break uses max line width × n × line metrics (not tight ink).
        No break keeps the single-line path below unchanged.
        """
        content = self._displayed_text()
        if _has_line_breaks(content):
            return self._broken_box_size(content)
        need_path = self._needs_outline_path()
        key = (content, float(self._font_size), id(self._skia_font), need_path)
        if getattr(self, "_box_key", None) == key:
            return self._box_wh
        if need_path:
            self._glyph_path0()
            b = getattr(self, "_gp0_bounds", None)
            if b is not None:
                w = float(b.width())
                h = float(b.height())
                if w > 1e-6 and h > 1e-6:
                    self._box_key = key
                    self._box_wh = (w, h)
                    return self._box_wh
        wh = (measure_text(self._skia_font, content), text_line_height(self._skia_font))
        self._box_key = key
        self._box_wh = wh
        return wh

    def _broken_box_size(self, content: str) -> tuple[float, float]:
        """Max line advance × n × line metrics. Same box for solid and shader ink."""
        key = (content, float(self._font_size), id(self._skia_font), "lines")
        if getattr(self, "_box_key", None) == key:
            return self._box_wh
        lines = _split_text_lines(content)
        font = self._skia_font
        widths = [measure_text(font, line) for line in lines]
        w = max(widths) if widths else 0.0
        h = len(lines) * text_line_height(font)
        self._box_key = key
        self._box_wh = (w, h)
        return self._box_wh

    def _glyph_path_in_box(self, local_x1: float, local_y1: float) -> skia.Path:
        """Glyph path with tight ink filling the local box from ``(local_x1, local_y1)``.

        Probe paths are built at baseline 0; Skia ``Rect.top()`` is min-y
        (visual bottom in y-up), ``left()`` is min-x.
        """
        path0 = self._glyph_path0()
        if path0 is None or path0.isEmpty():
            return path0 if path0 is not None else skia.Path()
        b = self._gp0_bounds
        x1 = float(local_x1)
        y1 = float(local_y1)
        box_key = (self._gp0_key, round(x1, 2), round(y1, 2))
        if getattr(self, "_gp_box_key", None) == box_key:
            return self._gp_box
        m = skia.Matrix()
        m.setTranslate(x1 - float(b.left()), y1 - float(b.top()))
        out = skia.Path()
        out.addPath(path0, m)
        self._gp_box = out
        self._gp_box_key = box_key
        return out

    def _layout_box_size(self) -> tuple[float, float, float]:
        """Return ``(box_w, box_h, glyph_w)`` — fixed width or content width."""
        glyph_w, h = self._glyph_box_size()
        box_w = float(self._width) if self._width is not None else float(glyph_w)
        return box_w, float(h), float(glyph_w)

    def _glyph_x_in_box(self, box_w: float, glyph_w: float) -> float:
        """Horizontal offset of glyphs inside the layout box (local left = 0)."""
        if self._align == "right":
            return box_w - glyph_w
        if self._align == "center":
            return 0.5 * (box_w - glyph_w)
        return 0.0

    def _anchor_is_linked(self) -> bool:
        """True while the anchor part carries an ``@=`` / constructor link."""
        name = self._anchor
        if name is None:
            return False
        part = self.__dict__.get(name)
        if part is None:
            return False
        return any(node._link is not None for node in part._iter_subtree())

    def _part_link_changed(self, node) -> None:
        """A part's link was installed or removed (``Container`` hook)."""
        d = self.__dict__
        if d.get("_anchor") is None or d.get("_destroyed"):
            return
        root = node
        while root._owner is not None and root._owner is not self:
            root = root._owner
        if root._attr_name in ("center", d["_anchor"]):
            self._sync_placement_model()

    def _sync_placement_model(self) -> None:
        """Which placement part is Defining follows which one links.

        A linked part is the pin while it links: a linked anchor (as at
        construction), or a linked ``center``, around which the box lays out.
        The other placement part is then output (Derivate: a write raises,
        it cannot fight the link). With no link the construction model holds.
        """
        d = self.__dict__
        anchor = d["_anchor"]
        center = d.get("center")
        center_links = center is not None and any(
            node._link is not None for node in center._iter_subtree())
        d["_center_links"] = center_links
        if center_links:
            derived = set(_TEXT_PARTS) - {"center"}
        elif self._anchor_is_linked():
            derived = set(_TEXT_PARTS) - {anchor}
        else:
            derived = set(_TEXT_PARTS) - d["_built_defining"]
        defining = frozenset(set(self._field_slots()) - derived)
        if defining == d["_defining_part_names"]:
            return
        d["_defining_part_names"] = defining
        for name in _TEXT_PARTS:
            part = d.get(name)
            if part is None:
                continue
            ft = FieldType.Derivate if name in derived else FieldType.Defining
            if part.__dict__.get("_field_type") == ft:
                continue
            part._field_type = ft
            part._invalidate_bare_reads()      # a cached bare write skips the guard
            if ft == FieldType.Derivate:
                part._rewire_subtree_structural_edges(upward=True)
        self._rewire_subtree_structural_edges(upward=None)

    def _anchor_offset(self, box_w: float) -> float:
        """The anchor's x in the unturned box, from its center."""
        if self._anchor == "top_right":
            return 0.5 * box_w
        if self._anchor == "top_center":
            return 0.0
        return -0.5 * box_w

    def _posed(self, lx: float, ly: float) -> tuple:
        """A local offset from the center, turned and scaled like the drawing
        (scale 0 draws at ``MIN_SCALE``: the pin keeps its offset, so it recovers)."""
        sc = self._draw_scale()
        ang = float(getattr(self, "_rotation", 0.0) or 0.0)
        if ang:
            c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            lx, ly = lx * c - ly * s, lx * s + ly * c
        return (lx * sc, ly * sc)

    def _edges_from_pin(self, px: float, py: float, box_w: float, h: float):
        """Box ``(x1, y1, x2, y2)`` (unturned, around the drawn center) whose anchor,
        as drawn — turned and scaled about the center — sits at ``(px, py)``.

        The anchor is the pin of the drawn corner (Named points): a turned or
        scaled caption keeps its ``top_left`` where the pin is.
        """
        ox, oy = self._posed(self._anchor_offset(box_w), 0.5 * h)
        cx, cy = px - ox, py - oy
        return (cx - 0.5 * box_w, cy - 0.5 * h, cx + 0.5 * box_w, cy + 0.5 * h)

    def _part_values(self) -> dict:
        """Current point of every Text part, as drawn (anchor = the pin)."""
        x1, y1, x2, y2 = self._x1, self._y1, self._x2, self._y2
        cx, cy = 0.5 * (x1 + x2), 0.5 * (y1 + y2)
        hw, hh = 0.5 * (x2 - x1), 0.5 * (y2 - y1)

        def at(lx: float, ly: float) -> tuple:
            ox, oy = self._posed(lx, ly)
            return (cx + ox, cy + oy)

        values = {
            "center": (cx, cy),
            "top_left": at(-hw, hh),
            "top_center": at(0.0, hh),
            "top_right": at(hw, hh),
        }
        if self._anchor is not None and self._pin is not None:
            values[self._anchor] = self._pin   # exact: never re-derived
        return values

    def _link_field(self, name: str, source) -> None:
        """An anchored caption takes one placement link: its anchor or its
        center, not both. Both drove one caption two ways and disagreed (the
        center followed its source, the anchor stayed; GX13 in Testing
        Design), so the second ``@=`` refuses, the way a Rect placed by its
        corner refuses a ``center`` link."""
        anchor = self.__dict__.get("_anchor")
        if anchor is not None and name in ("center", anchor):
            other = anchor if name == "center" else "center"
            part = self.__dict__.get(other)
            if part is not None and part.__dict__.get("_link") is not None:
                raise LinkedAttributeError(
                    f"{self.name}['{name}'] @= …: this caption is placed by its {anchor} and "
                    f"{self.name}['{other}'] already has a link. Link one of them: "
                    f"call {self.name}['{other}'].unlink() first"
                )
        super()._link_field(name, source)

    def _part_became_link_source(self, part) -> None:
        """An anchored caption's ``center`` is written by the lazy layout, not
        by its readers' sources. When a link first reads it: it depends on the
        caption (so a move or a new string dirties it and its readers) and its
        reads pull the caption first (``_pull_owner``: re-lay-out), as a
        derived heading does (D18). Without this, ``q @= t.center`` read the
        old centre until something read the caption (D26). Derived parts
        already depend on the caption; the anchor and a pose caption's centre
        are inputs."""
        d = part.__dict__
        if d.get('_attr_name') != "center" or self._anchor is None or '_pull_owner' in d:
            return
        ss = getattr(self, '_scena_system', None)
        if ss is not None:
            ss.add_dependency(part, self)
        d['_pull_owner'] = self
        part._invalidate_bare_reads()

    def _publish_parts(self) -> None:
        """Write the parts the layout owns: derived ones, and the anchored centre.

        A linked anchor is its own source and is never written. A snapshot
        anchor is rewritten to the pin (a ``center`` translation moved it).
        """
        d = self.__dict__
        values = self._part_values()
        outer = d.get("_in_text_layout", False)
        d["_in_text_layout"] = True
        try:
            with self._batch_update():
                for name in _TEXT_PARTS:
                    part = d.get(name)
                    if part is None:
                        continue
                    if name == "center":
                        if self._anchor is None or d.get("_center_links"):
                            continue   # the pose, or a linked pin: its own source
                    elif name == self._anchor:
                        if self._anchor_is_linked():
                            continue
                    elif not part._is_derivate_live():
                        continue
                    x, y = values[name]
                    # Raw float write unless a link reads this point; then
                    # notify (D25, hazard #8).
                    if not _read_by_a_link(part):
                        _takein_xy_float(part, x, y)
                    else:
                        part._takein((x, y))
            if self._anchor is not None:
                self._center_rec = values["center"]
        finally:
            d["_in_text_layout"] = outer

    def _update_impl(self) -> None:
        """A derived part is read while the caption is dirty: re-lay-out."""
        self._refresh_layout()

    def _materialize_derivate_part(self, name: str) -> None:
        """First read of a derived part: fill it from the current layout."""
        d = self.__dict__
        if not d.get("_layout_ready") or name not in _TEXT_PARTS:
            return
        outer = d.get("_in_text_layout", False)
        d["_in_text_layout"] = True
        try:
            self._refresh_layout_now()
            part = d.get(name)
            if part is not None:
                x, y = self._part_values()[name]
                with self._batch_update():
                    _takein_xy_float(part, x, y)
        finally:
            d["_in_text_layout"] = outer

    def _domain_aabb(self):
        """World AABB for cull; pad when ``.glow`` is on (ADD stroke halo)."""
        self._refresh_layout()
        pad = 0.0
        glow = self._text_glow()
        if glow is not None:
            metrics = self._text_glow_metrics(glow)
            if metrics is not None:
                pad = 0.5 * float(metrics[3]) + 2.0
        x1, y1, x2, y2 = float(self._x1), float(self._y1), float(self._x2), float(self._y2)
        ang = float(getattr(self, "_rotation", 0.0) or 0.0)
        sc = abs(float(getattr(self, "_scale", 1.0)))
        if ang or sc != 1.0:
            # Drawn turned and scaled about the center: bound that box, or a
            # turned caption near the edge is culled while visible.
            cx, cy = 0.5 * (x1 + x2), 0.5 * (y1 + y2)
            hw, hh = 0.5 * (x2 - x1) * sc, 0.5 * (y2 - y1) * sc
            c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            ex, ey = abs(c) * hw + abs(s) * hh, abs(s) * hw + abs(c) * hh
            x1, y1, x2, y2 = cx - ex, cy - ey, cx + ex, cy + ey
            pad *= sc
        return (x1 - pad, y1 - pad, x2 + pad, y2 + pad)

    def _text_glow(self):
        """Active glow stamp (Glow or CheapGlow), or None."""
        from .visuals import Glow, CheapGlow
        glow = getattr(self, "_glow", None)
        return glow if isinstance(glow, (Glow, CheapGlow)) else None

    def _text_glow_metrics(self, glow):
        """Caption ADD stroke ladder. CheapGlow uses Glow's halo (already cheap)."""
        from .visuals import CheapGlow, Glow
        if isinstance(glow, CheapGlow):
            # Same filterless glyph halo as Glow() — not CheapGlow's shape bloom.
            glow = Glow(
                color=glow.color,
                alpha=glow.alpha,
                amount=glow.amount,
            )
        gf = getattr(glow, "_glow", None)
        if gf is None:
            return None
        rgba = getattr(gf, "_color", (1.0, 0.95, 0.65, 1.0))
        blur = max(float(getattr(gf, "_blur", 8.0) or 8.0), 1.0)
        a = min(1.0, max(0.0, float(rgba[3])))
        outer_w = min(max(blur * _TEXT_GLOW_OUTER_BLUR, _TEXT_GLOW_OUTER_MIN), _TEXT_GLOW_OUTER_MAX)
        inner_w = max(_TEXT_GLOW_INNER_MIN, outer_w * _TEXT_GLOW_INNER_RATIO)
        layers = (
            (outer_w, _TEXT_GLOW_OUTER_ALPHA * a),
            (inner_w, _TEXT_GLOW_INNER_ALPHA * a),
        )
        return ("bands", rgba, layers, outer_w)

    def _text_glow_paint(self) -> skia.Paint:
        paint = getattr(self, "_glow_add_paint", None)
        if paint is None:
            paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeCap=skia.Paint.Cap.kRound_Cap,
                StrokeJoin=skia.Paint.Join.kRound_Join,
                BlendMode=skia.BlendMode.kPlus,
            )
            self._glow_add_paint = paint
        return paint

    def _tint_glow_paint(self, rgba, width: float, alpha: float):
        paint = self._text_glow_paint()
        paint.setStrokeWidth(float(width))
        paint.setColor4f(skia.Color4f(
            float(rgba[0]), float(rgba[1]), float(rgba[2]), float(alpha),
        ))
        return paint

    def _draw_path_glow(self, skia_canvas, glyph_path: skia.Path, glow) -> None:
        """Filterless ADD halo on glyph outlines (shader / Gradient hosts)."""
        if glyph_path.isEmpty():
            return
        metrics = self._text_glow_metrics(glow)
        if metrics is None:
            return
        _kind, rgba, layers, _max_w = metrics
        for width, alpha in layers:
            skia_canvas.drawPath(glyph_path, self._tint_glow_paint(rgba, width, alpha))

    def _draw_string_glow(self, skia_canvas, text: str, x: float, y: float, glow) -> None:
        """Same ADD ladder via glyph atlas (no path tessellation)."""
        if not text:
            return
        metrics = self._text_glow_metrics(glow)
        if metrics is None:
            return
        _kind, rgba, layers, _max_w = metrics
        font = self._skia_font
        for width, alpha in layers:
            draw_string_upright(
                skia_canvas, text, x, y, font,
                self._tint_glow_paint(rgba, width, alpha),
            )

    def _refresh_layout(self) -> None:
        """Re-lay-out the box for the string showing now.

        Anchored caption: the anchor part is the pin. A link on it is pulled
        here; a snapshot anchor that someone wrote (``top_left = P``, a move
        verb, ``tween`` on it) is the new pin. Otherwise a ``center`` write
        since the last layout (``center =``, ``tween`` on ``center``, drag) is
        a translation of the pin by ``center − last published centre``. The
        box then grows away from the pin. Pose caption (``center=`` /
        ``box=``): the box grows around ``center``.

        The string (formula text is pull) and the other width inputs never
        notify, so this is the only place they meet the pose — run on draw /
        cull / hit-test and on every outside read of a part
        (``_TextPartSlot``). Skip graph writes when nothing changed — HUD
        captions are redrawn every frame.
        """
        d = self.__dict__
        if d.get("_in_text_layout", False) or not d.get("_layout_ready"):
            return
        d["_in_text_layout"] = True
        try:
            self._refresh_layout_now()
        finally:
            d["_in_text_layout"] = False

    def _refresh_layout_now(self) -> None:
        box_w, h, _ = self._layout_box_size()
        current = (self._x1, self._y1, self._x2, self._y2)
        # The parts are posed (turned / scaled about the center): a pose change
        # republishes them even when the unturned box did not move.
        pose = (float(getattr(self, "_rotation", 0.0) or 0.0), self._draw_scale())
        posed = pose != self.__dict__.get("_published_pose")
        self.__dict__["_published_pose"] = pose
        if self._anchor is not None:
            part = self.__dict__.get(self._anchor)
            if part is None:
                return
            pin = self._pin
            if self.__dict__.get("_center_links"):
                # A linked center is the pin while it links: the box lays out
                # around it and the anchor follows, so the center holds its
                # formula whatever the string does.
                center = self.__dict__["center"]
                cx, cy = float(center.x), float(center.y)
                ox, oy = self._posed(self._anchor_offset(box_w), 0.5 * h)
                px, py = cx + ox, cy + oy
                edges = (cx - 0.5 * box_w, cy - 0.5 * h, cx + 0.5 * box_w, cy + 0.5 * h)
                if (px, py) != pin or edges != current or posed:
                    self._pin = (px, py)
                    self._x1, self._y1, self._x2, self._y2 = edges
                    self._publish_parts()
                return
            ax, ay = float(part.x), float(part.y)
            if pin is None or (ax, ay) != pin or self._anchor_is_linked():
                px, py = ax, ay
            else:
                px, py = pin
                rec = self._center_rec
                center = self.__dict__.get("center")
                if rec is not None and center is not None:
                    cx, cy = get_xy(center, bare=True)
                    if cx != rec[0] or cy != rec[1]:
                        px += cx - rec[0]
                        py += cy - rec[1]
            edges = self._edges_from_pin(px, py, box_w, h)
            if (px, py) != pin or edges != current or posed:
                self._pin = (px, py)
                self._x1, self._y1, self._x2, self._y2 = edges
                self._publish_parts()
        else:
            cx, cy = get_xy(self.center, bare=True)
            x1 = cx - 0.5 * box_w
            y1 = cy - 0.5 * h
            edges = (x1, y1, x1 + box_w, y1 + h)
            if edges != current or posed:
                self._x1, self._y1, self._x2, self._y2 = edges
                self._publish_parts()

    def set_color(self, *args) -> "Text":
        """Recolor glyph fill only — no Shape contrast stroke on ``.line``."""
        _refuse_if_destroyed(self, "set_color")
        if self._alinks:
            _refuse_linked_text_paint(self, ("color", "fill"), "set the color of")
        from .style import Gradient, Texture, ProceduralFill
        from .state import as_payload_all
        args = as_payload_all(*args)
        if len(args) == 1 and isinstance(args[0], (Gradient, Texture, ProceduralFill, Color)):
            material = args[0]
        else:
            material = Color(*args) if len(args) > 1 else Color(args[0])
        # Fill only; author outline stays on ``.line = …`` when wanted.
        if isinstance(material, (Gradient, Texture, ProceduralFill)):
            self.fill = material
        else:
            self.fill = material if isinstance(material, Color) else Color(material)
        visual = getattr(self, "_visual", None)
        glow = getattr(self, "_glow", None)
        if glow is not None:
            from .stamps import sync_stamp_filters
            # Re-apply glow stamp so Text ADD halo tracks fill.
            sync_stamp_filters(self)
        elif visual is not None:
            role = getattr(visual, "_color_role", None)
            if role in ("A", "C", "D", "E") or role is None:
                # Body looks: re-apply so filter tint tracks fill.
                reapply = getattr(self, "_reapply_visual", None)
                if callable(reapply):
                    reapply()
        return self

    def _rebuild_skia_font(self) -> None:
        from .uiwidget import resolve_typeface
        spec = getattr(self, "_font_spec", None)
        if spec:
            typeface = resolve_typeface(spec)
        else:
            theme = getattr(self, "_theme", None)
            typeface = None if theme is None else getattr(theme, "typeface", None)
            if typeface is None:
                typeface = resolve_typeface(None)
        object.__setattr__(self, "_skia_font", _make_ui_font(typeface, self._font_size))

    @property
    def font(self):
        """Family name or ``.ttf`` / ``.otf`` path. ``None`` uses ``ui.font``."""
        return self._font_spec

    @font.setter
    def font(self, value) -> None:
        spec = None if value is None or value == "" else str(value)
        self._font_spec = spec
        self._rebuild_skia_font()
        self._refresh_layout()

    @property
    def font_size(self) -> float:
        """Glyph size in design units (> 0). Writable; the layout rebuilds."""
        return self._font_size

    @font_size.setter
    def font_size(self, value) -> None:
        n = fixed_magnitude(value, "font_size")
        self._font_size = n
        self._rebuild_skia_font()

    @property
    def value(self):
        """Python payload of the ``text`` cell (Label migration)."""
        return self._text_cell().value

    @value.setter
    def value(self, v) -> None:
        self.text = v

    @property
    def background(self):
        """Panel color behind the text, or ``None`` for no panel. Any color form."""
        if self._alinks:
            _pull_channel_links(self, ("background",))
        return self._background

    @background.setter
    def background(self, value) -> None:
        if self._alinks:
            _refuse_linked_text_paint(self, ("background",), "set background on")
        self._background = None if value is None else Color(value)

    @property
    def width(self) -> Optional[float]:
        """Fixed layout width, or ``None`` when the box follows the string."""
        return self._width

    @width.setter
    def width(self, value) -> None:
        fixed = _normalize_text_width(value)
        self._refresh_layout()  # settle a pending move before the box changes
        self._width = fixed
        self._refresh_layout()   # anchor (or centre) stays; the box follows

    @property
    def align(self) -> str:
        """``'left'`` / ``'center'`` / ``'right'`` — each line inside the box.

        The box is ``width=`` or the widest line; ``align`` never moves it.
        """
        return self._align

    @align.setter
    def align(self, value) -> None:
        self._align = _normalize_text_align(value)

    @property
    def color(self):
        """Text color (solid). ``None`` resets to white. Gradients go on ``.fill``."""
        if self._alinks:
            _pull_channel_links(self, ("color", "fill"))
        fill = self._fill
        if isinstance(fill, Color):
            return fill
        return Color(1.0, 1.0, 1.0, 1.0)

    @color.setter
    def color(self, value) -> None:
        if self._alinks:
            _refuse_linked_text_paint(self, ("color", "fill"), "set the color of")
        if value is None:
            self.fill = Color(1.0, 1.0, 1.0, 1.0)
        else:
            self.set_color(value)

    @PaintState.visual.setter
    def visual(self, value):
        if value is not None:
            raise TypeError(
                "Text has no costume .visual — use Text.glow = True / Glow(...) / "
                "CheapGlow(...). Glyph paint is .fill / .line / color= / background=."
            )
        PaintState.visual.fset(self, None)

    def _anchor_part(self):
        """The Defining anchor Point, or ``None`` for a pose caption."""
        name = self._anchor
        return None if name is None else getattr(self, name)

    def _parts_written_by_drag(self):
        anchor = self._anchor_part()
        return (self.center,) if anchor is None else (anchor, self.center)

    def _parts_written_by_resolve(self):
        return self._parts_written_by_drag()

    def _parts_written_by_wheel_rotate(self):
        # An anchored caption turns about its center and its pin moves with
        # it: the pin is written too (the timed probe and the claims read this;
        # a timed turn with a linked pin raised from a tick).
        anchor = self._anchor_part()
        return (self["angle"],) if anchor is None else (anchor, self["angle"])

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        """The pose zoom's gate, plus the pin an anchored caption moves (the
        instant verb checks it in ``_pinned_pose_verb``; the timed probe and
        the claims run this)."""
        anchor = self._anchor_part()
        if anchor is not None:
            if pivot is None:
                pivot = self._pivot_xy(about)
            _ensure_writable(anchor, "scale_by", force=force, pivot=pivot)
        super()._scale_gate(about, force, pivot)

    def _ensure_pose_writable(self, operation: str, force: bool, pivot=None) -> None:
        """A linked anchor (or a linked centre) refuses every pose writer that
        moves it; one on the verb's ``pivot`` does not move and may stay linked."""
        anchor = self._anchor_part()
        if anchor is not None:
            _ensure_writable(anchor, operation, force=force, pivot=pivot)
        _ensure_writable(self.center, operation, force=force, pivot=pivot)

    def _shift_anchor(self, dx: float, dy: float) -> None:
        """Move the Defining anchor; the next layout re-lays the box from it."""
        if dx == 0.0 and dy == 0.0:
            return
        if self.__dict__.get("_center_links"):
            # The linked center is the pin; the layout places the anchor (a
            # turn about the center already moved it: shifting it again
            # turned it twice).
            self._refresh_layout()
            return
        anchor = self._anchor_part()
        ax, ay = float(anchor.x), float(anchor.y)
        if not _read_by_a_link(anchor):
            with self._batch_update():
                _takein_xy_float(anchor, ax + dx, ay + dy)
        else:
            # A link reads the anchor: notify (a raw float write left a
            # direct link stale; D25, hazard #8).
            anchor._takein((ax + dx, ay + dy))

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> "Text":
        self._ensure_pose_writable("move_by", force)
        ddx = 0.0 if dx is None else float(dx)
        ddy = 0.0 if dy is None else float(dy)
        if self._anchor is not None:
            self._shift_anchor(ddx, ddy)
            return self
        cx = _bare_attr(self.center.x)
        cy = _bare_attr(self.center.y)
        center = self.center
        if not _read_by_a_link(center):
            _takein_xy_float(center, cx + ddx, cy + ddy)
        else:
            center._takein((cx + ddx, cy + ddy))         # D25: notify link readers
        self._refresh_layout()
        return self

    def _move_to(self, x: float, y: float, *, force: bool = False) -> "Text":
        # "Midpoint goes to (x, y)" for every caption. Reading center
        # re-lays-out first, so it is the midpoint of the string showing now.
        self._ensure_pose_writable("move_to", force)
        cx, cy = get_xy(self.center, bare=True)
        nx = cx if x is None else float(x)
        ny = cy if y is None else float(y)
        if self._anchor is not None:
            self._shift_anchor(nx - cx, ny - cy)
            return self
        center = self.center
        if not _read_by_a_link(center):
            _takein_xy_float(
                center,
                x=nx if nx != cx else None,
                y=ny if ny != cy else None,
            )
        else:
            center._takein((nx, ny))                      # D25: notify link readers
        self._refresh_layout()
        return self

    def _clone_recipe(self, *, center=None, frame=None, **kwargs) -> "Text":
        # Layer is placement (clone() passes layer= only when the author did).
        # Omitted: a HUD caption stays in the HUD pass; a world caption takes the
        # class default, like every other Graphic.
        if "layer" not in kwargs and self._is_on_ui_layer():
            kwargs["layer"] = self._layer
        if center is not None or self._anchor is None:
            if center is None:
                center = get_xy(self.center, bare=True)
            kwargs["center"] = center
        else:
            # Same anchor form, pinned where the source's is (a snapshot: a
            # linked anchor is not copied). A HUD copy does not join the column.
            self._refresh_layout()
            kwargs[self._anchor] = self._pin
            kwargs["stack"] = False
            # An anchor alone defaults to the HUD; a world caption's copy takes
            # the world default, as a center= copy does.
            kwargs.setdefault("layer", "default")
        return type(self)(
            str(self._text_cell().value),
            font_size=self.font_size,
            background=self._background,
            width=self._width,
            align=self._align,
            **kwargs,
        )

    def _hit_test_xy(self, x: float, y: float) -> bool:
        self._refresh_layout()
        cx, cy = get_xy(self.center, bare=True)
        ang = math.radians(float(getattr(self, "_rotation", 0.0) or 0.0))
        sc = float(getattr(self, "_scale", 1.0))
        if sc == 0.0:
            return False
        dx = x - cx
        dy = y - cy
        if abs(ang) > 1e-9:
            c, s = math.cos(-ang), math.sin(-ang)
            dx, dy = dx * c - dy * s, dx * s + dy * c
        if sc != 0.0:
            dx /= sc
            dy /= sc
        hw = 0.5 * (self._x2 - self._x1)
        hh = 0.5 * (self._y2 - self._y1)
        return abs(dx) <= hw and abs(dy) <= hh

    def _clean_up(self) -> None:
        super()._clean_up()

    @property
    def angle(self) -> float:
        """The heading in degrees (0 = +x, counter-clockwise)."""
        self._pull_property_anchor("angle")
        return self._rotation

    @angle.setter
    def angle(self, value: float) -> None:
        """Set the heading, keeping the point the caption was placed by: its
        anchor (``top_left`` / ``top_center`` / ``top_right``) when it has one,
        otherwise its center (then this is ``rotate_to(value)``)."""
        from .shapes import _finite_deg
        anchor = self._anchor
        about = getattr(self, anchor) if anchor is not None else None
        self.rotate_to(_finite_deg(value, "angle"), about=about)

    def _apply_flip(self, axis: str, value, *, force: bool = False) -> None:
        """Text cannot be mirrored: mirrored text is unreadable. ``False`` is a no-op."""
        if not bool(value):
            return
        raise TypeError(
            f"Text cannot be flipped (flip_{axis} = True): mirrored text is unreadable. "
            "Turn it instead (angle = 180 turns it upside down)."
        )

    def _draw_scale(self) -> float:
        sc = float(getattr(self, "_scale", 1.0))
        return sc if sc != 0.0 else MIN_SCALE

    def _pinned_pose_verb(self, verb, amount, args, kwargs, operation: str):
        """Run a rotate / scale verb on an anchored caption so its pin moves with the drawing.

        The drawn center is derived from the pin, so the pose change runs about
        the center and the pin then moves by the measured turn and scale about
        the pivot (default: the center) — a rigid motion of every part. A
        linked anchor cannot move: raise, like ``move_by`` (``force=True``
        unlinks). Timed verbs step through here on every tick.
        """
        anchor = self._anchor_part()
        if kwargs.get("time") is not None or kwargs.get("speed") is not None or anchor is None:
            return verb(amount, *args, **kwargs)
        self._refresh_layout()
        qx, qy = self._pivot_xy(kwargs.get("about"))       # validates the pivot
        self._ensure_pose_writable(operation, kwargs.get("force", False), pivot=(qx, qy))
        rot0, sc0 = float(self._rotation), self._draw_scale()
        kwargs["about"] = None
        out = verb(amount, *args, **kwargs)                  # validates the amount
        a = math.radians(float(self._rotation) - rot0)
        k = self._draw_scale() / sc0
        px, py = float(anchor.x), float(anchor.y)
        dx, dy = px - qx, py - qy
        nx = qx + k * (dx * math.cos(a) - dy * math.sin(a))
        ny = qy + k * (dx * math.sin(a) + dy * math.cos(a))
        self._shift_anchor(nx - px, ny - py)
        return out

    def rotate_by(self, angle, *args, **kwargs):
        """Turn by ``angle`` degrees about a pivot (default: center). An anchored caption's
        pin turns with it, so every part stays with the drawing."""
        return self._pinned_pose_verb(super().rotate_by, angle, args, kwargs, "rotate_by")

    def scale_by(self, factor, *args, **kwargs):
        """Scale by ``factor`` about a pivot (default: center). An anchored caption's
        pin scales with it, so every part stays with the drawing."""
        return self._pinned_pose_verb(super().scale_by, factor, args, kwargs, "scale_by")

    def _broken_glyph_path(
        self, lines, local_x1: float, local_y1: float, box_w: float, line_h: float, font,
    ) -> skia.Path:
        """One outline path: each hard-break line in its metric slot (y-up)."""
        out = skia.Path()
        n = len(lines)
        for i, line in enumerate(lines):
            if not line:
                continue
            y_min = local_y1 + (n - 1 - i) * line_h
            baseline = text_baseline_in_box(y_min, line_h, font)
            glyph_x = local_x1 + self._glyph_x_in_box(box_w, measure_text(font, line))
            piece = build_upright_text_path(line, glyph_x, baseline, font)
            if piece is not None and not piece.isEmpty():
                out.addPath(piece)
        return out

    def _draw_broken_lines(
        self, skia_canvas, content: str, local_x1: float, local_y1: float,
        box_w: float, fill, stroke, glow,
    ) -> None:
        """Draw explicit ``\\n`` rows. ``width=`` clip is already on the canvas."""
        lines = _split_text_lines(content)
        font = self._skia_font
        line_h = text_line_height(font)
        n = len(lines)
        if self._needs_outline_path():
            glyph_path = self._broken_glyph_path(
                lines, local_x1, local_y1, box_w, line_h, font,
            )
            empty = glyph_path.isEmpty()
            if fill is not None and not empty:
                if glow is not None:
                    self._draw_path_glow(skia_canvas, glyph_path, glow)
                skia_canvas.drawPath(glyph_path, fill)
            if stroke is not None and not empty:
                stroke.setStyle(skia.Paint.kStroke_Style)
                skia_canvas.drawPath(glyph_path, stroke)
            return
        for i, line in enumerate(lines):
            if not line:
                continue
            y_min = local_y1 + (n - 1 - i) * line_h
            baseline = text_baseline_in_box(y_min, line_h, font)
            glyph_x = local_x1 + self._glyph_x_in_box(box_w, measure_text(font, line))
            if fill is not None:
                if glow is not None:
                    self._draw_string_glow(
                        skia_canvas, line, glyph_x, baseline, glow,
                    )
                draw_string_upright(
                    skia_canvas, line, glyph_x, baseline, font, fill,
                )
            if stroke is not None:
                stroke.setStyle(skia.Paint.kStroke_Style)
                draw_string_upright(
                    skia_canvas, line, glyph_x, baseline, font, stroke,
                )

    def _geometry_draw(
        self,
        skia_canvas: skia.Canvas,
        fill_paint=_STYLE_PAINT,
        stroke_paint=_STYLE_PAINT,
    ) -> None:
        self._refresh_layout()
        cx, cy = get_xy(self.center, bare=True)
        ang = float(getattr(self, "_rotation", 0.0) or 0.0)
        sc = float(self._scale)
        from .validate import MIN_SCALE
        draw = sc if sc != 0.0 else MIN_SCALE
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if ang:
            skia_canvas.rotate(ang)
        if draw != 1.0:
            skia_canvas.scale(draw, draw)

        box_w = self._x2 - self._x1
        h = self._y2 - self._y1
        glyph_w, _ = self._glyph_box_size()
        ink_dx = self._glyph_x_in_box(box_w, glyph_w)
        local_x1 = -0.5 * box_w
        local_y1 = -0.5 * h
        glyph_x = local_x1 + ink_dx

        bg = self._background
        if bg is not None:
            pad = float(getattr(self._theme, "card_padding", 6.0) or 6.0)
            radius = float(getattr(self._theme, "corner_radius", 6.0) or 6.0)
            rect = skia.Rect.MakeXYWH(
                local_x1 - pad,
                local_y1 - pad,
                box_w + 2 * pad,
                h + 2 * pad,
            )
            rrect = skia.RRect.MakeRectXY(rect, radius, radius)
            bg_paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
            bg_paint.setColor(bg.color4f)
            skia_canvas.drawRRect(rrect, bg_paint)

        # Fixed width: clip ink to the layout box (overflow does not grow the box).
        if self._width is not None:
            skia_canvas.clipRect(skia.Rect.MakeXYWH(local_x1, local_y1, box_w, h))

        fill = self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
        stroke = (
            self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
        )
        glow = self._text_glow() if fill is not None else None

        content = self._displayed_text()
        if _has_line_breaks(content):
            self._draw_broken_lines(
                skia_canvas, content, local_x1, local_y1, box_w, fill, stroke, glow,
            )
        elif self._needs_outline_path():
            # Shader materials: local-space glyph path (Gradient/Texture frame).
            glyph_path = self._glyph_path_in_box(glyph_x, local_y1)
            empty = glyph_path is None or glyph_path.isEmpty()
            if fill is not None and not empty:
                if glow is not None:
                    self._draw_path_glow(skia_canvas, glyph_path, glow)
                skia_canvas.drawPath(glyph_path, fill)
            if stroke is not None and not empty:
                stroke.setStyle(skia.Paint.kStroke_Style)
                skia_canvas.drawPath(glyph_path, stroke)
        else:
            # Solid Color (± Glow): GPU glyph atlas, same as old Label.
            if content:
                baseline = text_baseline_in_box(local_y1, h, self._skia_font)
                if fill is not None:
                    if glow is not None:
                        self._draw_string_glow(
                            skia_canvas, content, glyph_x, baseline, glow,
                        )
                    draw_string_upright(
                        skia_canvas, content, glyph_x, baseline, self._skia_font, fill,
                    )
                if stroke is not None:
                    stroke.setStyle(skia.Paint.kStroke_Style)
                    draw_string_upright(
                        skia_canvas, content, glyph_x, baseline, self._skia_font, stroke,
                    )

        skia_canvas.restore()

    def __str__(self) -> str:
        from .entity import made_at
        where = made_at(self)
        text = repr(self._displayed_text())
        return f"Text({text}, {where})" if where else f"Text({text})"

    def __repr__(self) -> str:
        return self.__str__()


from .entity import _install_setattr_route  # noqa: E402

_install_setattr_route(Text)
