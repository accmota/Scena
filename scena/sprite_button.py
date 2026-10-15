"""SpriteButton: a Sprite with the whole behavior of a game button.

Hover, press and disabled feedback, optional breathing, a click handler and
sounds — all packaged on one Sprite. The feedback is **draw-time only**: the
pose ``scale`` stays the author's and the click area (the convex hull of the
rest art) never moves with it. Design: design/Sprite Design.md,
"SpriteButton".
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Any, Optional, Tuple

import skia

from .entity import Graphic, _USE_LAYER_DEFAULT
from .shapes import GeneralPoint
from .sprite import _OMIT, Sprite
from .state import as_payload, bound_cell
from .validate import expect_bool as _expect_flag

__all__ = ["SpriteButton"]

_FEEL_TIME = 0.1            # seconds for hover / press / enable transitions
_BREATHE_AMOUNT = 0.05      # ±5 % with breathe=True
_HOVER_LIGHT = 0.12         # lighten toward white while hovered
_PRESS_DARK = 0.12          # darken while pressed
_DISABLED_ALPHA = 0.55      # body alpha while disabled (gray on top)
_LABEL_FILL = 0.88          # a fitted label uses at most this share of its box


def _now() -> float:
    from .transients import _now as now
    return now()


def _smooth(u: float) -> float:
    u = 0.0 if u <= 0.0 else 1.0 if u >= 1.0 else u
    return u * u * (3.0 - 2.0 * u)


class _Ease:
    """A 0–1 level that eases toward its target, evaluated in closed form."""

    __slots__ = ("v0", "target", "t0")

    def __init__(self, value: float = 0.0):
        self.v0 = float(value)
        self.target = float(value)
        self.t0 = -1e9

    def at(self, t: float) -> float:
        u = _smooth((t - self.t0) / _FEEL_TIME)
        return self.v0 + (self.target - self.v0) * u

    def to(self, target: float, t: float) -> None:
        target = float(target)
        if target == self.target:
            return
        self.v0 = self.at(t)
        self.target = target
        self.t0 = t


def _convex_hull(points) -> Tuple[Tuple[float, float], ...]:
    """Counter-clockwise convex hull (monotone chain); collinear points dropped."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return tuple(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return tuple(lower[:-1] + upper[:-1])


def _inside_convex(hull, x: float, y: float) -> bool:
    n = len(hull)
    if n < 3:
        return False
    for i in range(n):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % n]
        if (bx - ax) * (y - ay) - (by - ay) * (x - ax) < -1e-9:
            return False
    return True


def _light_matrix(k: float) -> list:
    """``k > 0`` lightens toward white, ``k < 0`` darkens (RGB only)."""
    if k >= 0.0:
        s, off = 1.0 - k, k
    else:
        s, off = 1.0 + k, 0.0
    return [
        s, 0, 0, 0, off,
        0, s, 0, 0, off,
        0, 0, s, 0, off,
        0, 0, 0, 1, 0,
    ]


def _check_sound(value, what: str):
    value = as_payload(value)
    if value is None:
        return None
    from .audio import Sound
    if isinstance(value, (str, Sound)):
        return value
    raise TypeError(
        f"SpriteButton {what} expected a sound file name or a Sound, "
        f"got {type(value).__name__}."
    )


def _check_inset(value) -> Tuple[float, float, float, float]:
    """``label_inset``: a number (all sides) or ``(left, top, right, bottom)``."""
    from .validate import number
    value = as_payload(value)
    if isinstance(value, (tuple, list)):
        if len(value) != 4:
            raise TypeError(
                "SpriteButton label_inset expected a number or (left, top, right, bottom), "
                f"got {len(value)} values.")
        sides = tuple(number(v, "SpriteButton label_inset") for v in value)
    else:
        v = number(value, "SpriteButton label_inset")
        sides = (v, v, v, v)
    if any(v < 0.0 for v in sides):
        raise ValueError("SpriteButton label_inset must be >= 0 on every side.")
    return sides


_STATES = ("hover", "pressed", "disabled")


def _resolve_state_art(source, arts: dict):
    """Turn ``hover=`` / ``pressed=`` / ``disabled=`` into a source plus slots.

    A file body takes files (the button builds ``Sheet(body, *files)``); a
    Sheet body takes frame names / indices or clip names of that Sheet.
    Returns ``(source, frame_or_None, {state: spec})`` where a spec is an int
    frame index or a clip name.
    """
    from .sprite import Sheet
    given = {k: as_payload(v) for k, v in arts.items() if as_payload(v) is not None}
    if not given:
        return source, None, {}
    if isinstance(source, str):
        bad = [k for k, v in given.items() if not isinstance(v, str)]
        if bad:
            raise TypeError(
                f"SpriteButton {bad[0]}= with a file body takes a file name too "
                f"({bad[0]}=\"button_hover.png\"); frame indices need a Sheet body.")
        files = [source] + [given[k] for k in _STATES if k in given]
        pattern = next((f for f in files if "*" in f), None)
        if pattern is not None:
            raise TypeError(
                f"SpriteButton art is one file per state; {pattern!r} is a file "
                "pattern (several files). Name the file: "
                'SpriteButton("button.png", hover="button_hover.png").')
        sheet = Sheet(*files)
        slots, i = {}, 1
        for k in _STATES:
            if k in given:
                slots[k] = i
                i += 1
        return sheet, 0, slots
    if isinstance(source, Sheet):
        slots = {}
        for k, v in given.items():
            if isinstance(v, str) and v in source._cycles:
                slots[k] = v
            else:
                try:
                    slots[k] = source.frame_index(v)
                except (TypeError, ValueError) as exc:
                    raise type(exc)(
                        f"SpriteButton {k}={v!r}: not a frame or clip of this Sheet. "
                        f"{exc}") from None
        return source, None, slots
    raise TypeError(
        "SpriteButton hover= / pressed= / disabled= need the button art as a file "
        "or a Sheet (source=).")


def _check_scale(value, what: str) -> float:
    from .validate import number
    v = number(value, f"SpriteButton {what}")
    if v <= 0.0:
        raise ValueError(f"SpriteButton {what} must be > 0 (1 = no change), got {v:g}.")
    return v


def _check_breathe(value) -> float:
    value = as_payload(value)
    if value is False:
        return 0.0
    if value is True:
        return _BREATHE_AMOUNT
    if value is None:
        raise TypeError(
            "SpriteButton breathe expected True / False or the swing (0.05), got None.")
    from .validate import number
    v = number(value, "SpriteButton breathe")
    if not 0.0 <= v < 1.0:
        raise ValueError(
            f"SpriteButton breathe is the scale swing (0.05 = ±5 %), between 0 and 1; got {v:g}."
        )
    return v


class SpriteButton(Sprite):
    """A Sprite that is a game button: hover, press, disabled, click.

    ``SpriteButton("play.png", center=(400, 300), on_click=start)``. Hovered it
    grows a little and lightens; pressed it shrinks and darkens; the click runs
    on release inside (``fn()`` or ``fn(button)``, ``@click(button)`` works).
    ``enabled=False`` draws it gray and faded and ignores presses (the press
    does not reach what is below; ``on_hover`` still runs). The feedback is
    drawn, never written to ``scale``; the click area is the convex hull of
    the art at rest, the same in every state. Default layer ``"ui"`` (screen
    space); any world layer works too. ``isinstance(button, Sprite)`` is True.

    Args:
        source: Image file (still) or a ``Sheet`` (clips animate as on a Sprite).
        center: Pivot position (with a bottom-anchored Sheet, the feet).
        width: Width in design units (alone: keeps the aspect; with ``height``:
            stretches).
        height: Height in design units.
        size: Longer side in design units (keeps the aspect; not with ``width`` /
            ``height``).
        frame: Still cell of a Sheet: index or atlas name.
        on_click: Function called on a click, ``fn()`` or ``fn(button)``.
        enabled: ``False`` draws it gray and ignores presses; a function links it
            (``enabled=lambda: st.coins >= 10``).
        hover_sound: Sound played when the pointer starts hovering (file or ``Sound``).
        click_sound: Sound played on each click (file or ``Sound``); it keeps
            playing when the click changes the act.
        hover_scale: Drawn size while hovered (default 1.06; 1 = no growth).
        press_scale: Drawn size while pressed (default 0.94; 1 = no shrink).
        breathe: Slow size pulse while idle: ``True`` (±5 %) or the swing (0.03).
        breathe_time: Seconds per breath (default 1.6).
        label: Text centered on the button (str, number, a cell ``st["lives"]`` or function);
            it shrinks to fit. ``button.label_text`` is the ``Text`` for fine control.
        font: Label font: family name or a ``.ttf`` / ``.otf`` file.
        font_size: Label size in design units (default: 40 % of the button height).
        label_color: Label color, ``Gradient`` or ``Texture`` (default white).
        label_inset: Margin of the label box inside the art: a number or
            ``(left, top, right, bottom)`` — for art with a rim or a 3D lip.
        hover: Art shown while hovered (a file; with a Sheet body, a frame or clip
            name). Replaces the default hover effect.
        pressed: Art shown while pressed. Replaces the default press effect.
        disabled: Art shown while disabled. Replaces the default gray.
        hitbox_shape: The collision hitbox's shape (as on a Sprite).
        hitbox_source: Which art the collision hitbox is measured on.
        hitbox_anchor: Point that stays put when the collision hitbox is scaled.
        hitbox_scale: Shrink / stretch the collision hitbox.
        shield_scale: Size of the Shield / Electric* envelope around the art.
        offset: Shift ``(dx, dy)`` of the picture and collider from ``center``.
        visual: A look (``Halo()``, ``Metal()``, …).
        group: Group tag(s).
        flip_x: Mirror left-right.
        flip_y: Mirror up-down.
        art_angle: Heading the image is drawn facing, in degrees.
        angle: Heading at construction, in degrees.
        box: Fit into a Box (keeps the image aspect).
        layer: Draw layer (default ``"ui"``).
    """

    __slots__ = (
        "_on_click_fn", "_enabled", "_hover_sound", "_click_sound",
        "_hover_scale", "_press_scale", "_breathe", "_breathe_time", "_breathe_t0",
        "_ease_hover", "_ease_press", "_ease_off", "_ease_breathe",
        "_rest_hull", "_rest_hull_key",
        "_label_text", "_label_inset", "_fit_warned",
        "_state_art", "_art_state", "_art_t0",
    )

    _draws_solo = True
    _draws_parts = True
    _property_link_extra = frozenset({"enabled"})

    def __init__(
        self,
        source: Any = None,
        *,
        center: Optional[GeneralPoint] = None,
        width: Any = _OMIT,
        height: Any = _OMIT,
        size: Any = _OMIT,
        frame: Any = _OMIT,
        on_click: Any = None,
        enabled: Any = True,
        hover_sound: Any = None,
        click_sound: Any = None,
        hover_scale: Any = 1.06,
        press_scale: Any = 0.94,
        breathe: Any = False,
        breathe_time: Any = 1.6,
        label: Any = None,
        font: Any = None,
        font_size: Any = None,
        label_color: Any = None,
        label_inset: Any = 0,
        hover: Any = None,
        pressed: Any = None,
        disabled: Any = None,
        hitbox_shape: Any = _OMIT,
        hitbox_source: Any = _OMIT,
        hitbox_anchor: Any = _OMIT,
        hitbox_scale: Any = _OMIT,
        shield_scale: Any = _OMIT,
        offset: Any = _OMIT,
        visual: Any = _OMIT,
        group: Any = _OMIT,
        flip_x: Any = _OMIT,
        flip_y: Any = _OMIT,
        art_angle: Any = _OMIT,
        angle: Any = _OMIT,
        box: Any = _OMIT,
        layer: Any = _USE_LAYER_DEFAULT,
    ):
        from .validate import check_pointer_handler, seconds
        on_click = check_pointer_handler(
            as_payload(on_click), ("the button",), what="SpriteButton on_click")
        enabled_fn = None
        enabled = as_payload(enabled)
        if callable(enabled):
            enabled_fn, enabled = enabled, True
        enabled = _expect_flag(enabled, "SpriteButton enabled")
        hover_sound = _check_sound(hover_sound, "hover_sound")
        click_sound = _check_sound(click_sound, "click_sound")
        hover_scale = _check_scale(hover_scale, "hover_scale")
        press_scale = _check_scale(press_scale, "press_scale")
        breathe = _check_breathe(breathe)
        breathe_time = seconds(as_payload(breathe_time), "SpriteButton breathe_time")
        if breathe_time <= 0.0:
            raise ValueError("SpriteButton breathe_time must be > 0 seconds.")
        label_inset = _check_inset(label_inset)
        source, art_frame, state_art = _resolve_state_art(
            as_payload(source), {"hover": hover, "pressed": pressed, "disabled": disabled})
        if art_frame is not None and frame is _OMIT:
            frame = art_frame
        if layer is _USE_LAYER_DEFAULT:
            layer = "ui"

        t = _now()
        self._on_click_fn = on_click
        self._enabled = enabled
        self._hover_sound = hover_sound
        self._click_sound = click_sound
        self._hover_scale = hover_scale
        self._press_scale = press_scale
        self._breathe = breathe
        self._breathe_time = breathe_time
        self._breathe_t0 = t
        self._ease_hover = _Ease(0.0)
        self._ease_press = _Ease(0.0)
        self._ease_off = _Ease(0.0 if enabled else 1.0)
        self._ease_breathe = _Ease(1.0 if breathe and enabled else 0.0)
        self._rest_hull = ()
        self._rest_hull_key = None
        self._label_text = None
        self._label_inset = label_inset
        self._fit_warned = False
        self._state_art = state_art
        self._art_state = None
        self._art_t0 = t

        kw = {}
        if frame is not _OMIT:
            kw["frame"] = frame
        super().__init__(
            source,
            center=center, width=width, height=height, size=size,
            hitbox_shape=hitbox_shape, hitbox_source=hitbox_source,
            hitbox_anchor=hitbox_anchor, hitbox_scale=hitbox_scale,
            shield_scale=shield_scale, offset=offset, visual=visual,
            group=group, flip_x=flip_x, flip_y=flip_y, art_angle=art_angle,
            angle=angle, box=box, layer=layer, **kw,
        )
        # Never the plain-blit fast path: the feel wraps the body every frame
        # (Graphic.__init__ seeds the flag True directly).
        object.__setattr__(self, "_plain_blit", False)
        # Pressable with or without a handler: the feel works and the press
        # never falls through to what is below.
        self.clickable = True
        if enabled_fn is not None:
            ref = self["enabled"]
            ref @= enabled_fn
        cell = bound_cell(label)
        if cell is not None:
            label = cell          # ``label=st["vidas"]``: the label shows the cell live
        elif not callable(label):
            label = as_payload(label)
        if label is not None:
            self._make_label(label, font=font, font_size=font_size, color=label_color)
        elif any(v is not None for v in (font, font_size, label_color)):
            raise TypeError(
                "SpriteButton font= / font_size= / label_color= style the label; "
                "pass label= too (label=\"Play\").")

    # --- author surface ------------------------------------------------------

    @property
    def on_click(self):
        """Function called on a click, ``fn()`` or ``fn(button)``, or ``None``. Writable."""
        return self._on_click_fn

    @on_click.setter
    def on_click(self, value) -> None:
        from .validate import check_pointer_handler
        self._on_click_fn = check_pointer_handler(
            value, ("the button",), what="SpriteButton on_click")

    @property
    def enabled(self) -> bool:
        """``False`` draws the button gray and faded and ignores presses.

        A disabled button still blocks the pointer (a press does not reach what
        is below) and still runs ``on_hover``. Link it with
        ``button["enabled"] @= lambda: st.coins >= 10``.
        """
        self._pull_property_anchor("enabled")
        return self._enabled

    @enabled.setter
    def enabled(self, value) -> None:
        from .entity import _refuse_if_destroyed
        _refuse_if_destroyed(self, "enabled")
        want = _expect_flag(value, "SpriteButton enabled")
        if self.__dict__.get("_field_anchors"):
            # A linked ``enabled`` follows its formula: a plain write raised
            # nowhere and was overwritten at the next pull (LK1).
            from .entity import _refuse_linked_channel
            _refuse_linked_channel(self, ("enabled",), "set enabled on")
        if want == self._enabled:
            return
        self._enabled = want
        if not want and self._pointer_pressed:
            self._set_pointer_pressed(False)
        self._sync_feel(_now())

    @property
    def hover_sound(self):
        """Sound played when the pointer starts hovering (file or ``Sound``), or ``None``."""
        return self._hover_sound

    @hover_sound.setter
    def hover_sound(self, value) -> None:
        self._hover_sound = _check_sound(value, "hover_sound")

    @property
    def click_sound(self):
        """Sound played on each click (file or ``Sound``), or ``None``."""
        return self._click_sound

    @click_sound.setter
    def click_sound(self, value) -> None:
        self._click_sound = _check_sound(value, "click_sound")

    @property
    def hover_scale(self) -> float:
        """Drawn size while hovered (1 = no growth). Never written to ``scale``."""
        return self._hover_scale

    @hover_scale.setter
    def hover_scale(self, value) -> None:
        self._hover_scale = _check_scale(value, "hover_scale")

    @property
    def press_scale(self) -> float:
        """Drawn size while pressed (1 = no shrink). Never written to ``scale``."""
        return self._press_scale

    @press_scale.setter
    def press_scale(self, value) -> None:
        self._press_scale = _check_scale(value, "press_scale")

    @property
    def breathe(self) -> float:
        """Idle size pulse swing (0 = off; ``True`` writes 0.05). Pauses while hovered."""
        return self._breathe

    @breathe.setter
    def breathe(self, value) -> None:
        amount = _check_breathe(value)
        if amount and not self._breathe:
            self._breathe_t0 = _now()
        self._breathe = amount
        self._sync_feel(_now())

    @property
    def breathe_time(self) -> float:
        """Seconds per breath (default 1.6)."""
        return self._breathe_time

    @breathe_time.setter
    def breathe_time(self, value) -> None:
        from .validate import seconds
        v = seconds(as_payload(value), "SpriteButton breathe_time")
        if v <= 0.0:
            raise ValueError("SpriteButton breathe_time must be > 0 seconds.")
        self._breathe_time = v

    @property
    def label(self) -> Optional[str]:
        """The text shown on the button, or ``None``. Writable: a string or a number.

        Shortcut for the common case; ``button.label_text`` is the ``Text`` itself
        (font, color, glow, a live link with ``button.label_text["text"] @= …``).
        """
        t = self._label_text
        if t is None:
            return None
        return str(t._displayed_text())

    @label.setter
    def label(self, value) -> None:
        from .entity import _refuse_if_destroyed
        from .state import CallableAssignError
        _refuse_if_destroyed(self, "label")
        value = as_payload(value)
        if callable(value):
            raise CallableAssignError(
                "SpriteButton.label cannot be linked by assigning a function — `=` copies "
                "a value. Link the label's text: button.label_text['text'] @= lambda: …")
        if value is None:
            raise TypeError(
                "SpriteButton.label takes a string or a number. To hide the label: "
                "button.label_text.visible = False.")
        if self._label_text is None:
            self._make_label(value)
        else:
            self._label_text.text = value

    @property
    def label_text(self):
        """The label's ``Text`` (``None`` without a label), drawn by the button.

        Full Text styling: ``font``, ``font_size``, ``set_color`` (Gradient /
        Texture), ``glow``. Its pose is **relative** to the label box center
        (``label_text.move_to(0, 4)`` nudges it up); it moves, turns and fades
        with the button and cannot leave it (no layer, no destroy of its own).
        """
        return self._label_text

    @property
    def label_inset(self) -> Tuple[float, float, float, float]:
        """Label box margin inside the art, ``(left, top, right, bottom)`` in design units."""
        return self._label_inset

    @label_inset.setter
    def label_inset(self, value) -> None:
        self._label_inset = _check_inset(value)

    # --- engine hooks ----------------------------------------------------------

    # A press on it is the button's, not the game's: ``mouse.press`` reads
    # False until it goes up, as for a HUD widget (PD2).
    _hides_press = True

    def _accepts_press(self) -> bool:
        return bool(self.enabled)

    def _fire_click(self) -> None:
        if not self.enabled:
            return
        if self._click_sound is not None:
            from .audio import play_sound
            play_sound(self._click_sound)   # not owned: survives an act change
        from .validate import call_truncated
        call_truncated(self._on_click_fn, self)

    def _on_pointer_hover_changed(self) -> None:
        if self._pointer_hover and self._hover_sound is not None and self.enabled:
            self.play_sound(self._hover_sound)
        self._sync_feel(_now())

    def _on_pointer_pressed_changed(self) -> None:
        self._sync_feel(_now())

    def _refresh_plain_blit(self) -> None:
        # Always the full draw: the feel wraps the body every frame.
        object.__setattr__(self, "_plain_blit", False)

    # --- feel ------------------------------------------------------------------

    def _sync_feel(self, t: float) -> None:
        """Retarget the eases from the current state (idempotent)."""
        on = bool(self._enabled)
        pressed = on and bool(self._pointer_pressed)
        hovered = on and bool(self._pointer_hover)
        self._ease_off.to(0.0 if on else 1.0, t)
        self._ease_press.to(1.0 if pressed else 0.0, t)
        self._ease_hover.to(1.0 if hovered else 0.0, t)
        idle = on and not pressed and not hovered and self._breathe > 0.0
        self._ease_breathe.to(1.0 if idle else 0.0, t)
        art = self._state_art
        state = None
        if not on:
            state = "disabled"
        elif pressed:
            state = "pressed"
        elif hovered:
            state = "hover"
        state = state if state in art else None
        if state != self._art_state:
            self._art_state = state
            self._art_t0 = t

    def _feel_at(self, t: float) -> Tuple[float, float, float, float]:
        """``(scale, light, gray, alpha)`` drawn at time ``t``."""
        art = self._state_art
        h = 0.0 if "hover" in art else self._ease_hover.at(t)
        p = 0.0 if "pressed" in art else self._ease_press.at(t)
        d = 0.0 if "disabled" in art else self._ease_off.at(t)
        scale = 1.0 + (self._hover_scale - 1.0) * h
        scale += (self._press_scale - scale) * p
        if self._breathe > 0.0:
            w = self._ease_breathe.at(t)
            if w > 0.0:
                phase = (t - self._breathe_t0) / self._breathe_time
                scale *= 1.0 + self._breathe * w * math.sin(math.tau * phase)
        light = _HOVER_LIGHT * h * (1.0 - p) - _PRESS_DARK * p
        light *= 1.0 - d
        alpha = 1.0 - (1.0 - _DISABLED_ALPHA) * d
        return scale, light, d, alpha

    def _feel_paint(self, light: float, gray: float, alpha: float):
        """saveLayer paint for the color part of the feel, or None (identity)."""
        if abs(light) < 1e-4 and gray < 1e-4 and alpha > 0.9999:
            return None
        paint = skia.Paint()
        cf = None
        if gray >= 1e-4:
            from .visuals import _grayscale_matrix
            cf = skia.ColorFilters.Matrix(_grayscale_matrix(min(1.0, gray)))
        if abs(light) >= 1e-4:
            lf = skia.ColorFilters.Matrix(_light_matrix(light))
            cf = lf if cf is None else skia.ColorFilters.Compose(lf, cf)
        if cf is not None:
            paint.setColorFilter(cf)
        if alpha <= 0.9999:
            paint.setAlphaf(max(0.0, alpha))
        return paint

    def _cull_pad(self) -> float:
        """Extra cull margin for the drawn growth (hover / breathe)."""
        _cx, _cy, w, h, _a = self._oriented_frame()
        grow = max(self._hover_scale, 1.0 + self._breathe) - 1.0
        return 0.5 * math.hypot(w, h) * max(0.0, grow)

    # --- draw ------------------------------------------------------------------

    def draw(self, skia_canvas: skia.Canvas) -> None:
        """Body (and label) inside the feel envelope: drawn scale + color layer."""
        self._pull_property_anchors()
        self._pull_property_anchor("enabled")
        t = _now()
        self._sync_feel(t)
        scale, light, gray, alpha = self._feel_at(t)
        cx, cy, _w, _h, _a = self._oriented_frame()
        count = skia_canvas.save()
        try:
            if abs(scale - 1.0) > 1e-5:
                skia_canvas.translate(cx, cy)
                skia_canvas.scale(scale, scale)
                skia_canvas.translate(-cx, -cy)
            paint = self._feel_paint(light, gray, alpha)
            if paint is not None:
                skia_canvas.saveLayer(None, paint)
            with self._showing_state_art(t):
                self._draw_body_and_parts(skia_canvas)
        finally:
            skia_canvas.restoreToCount(count)

    @contextmanager
    def _showing_state_art(self, t: float):
        """Show the current state's art for this draw only.

        ``frame``, the author's clip, size, collider and click hull are left
        alone: the shown cell is swapped around the body draw and put back.
        """
        spec = self._state_art.get(self._art_state) if self._art_state else None
        if spec is None:
            yield
            return
        if isinstance(spec, str):
            frames, fps, yoyo = self._sheet._require_cycle(spec)
            n = len(frames)
            from .process import whole_steps
            step = whole_steps(max(0.0, t - self._art_t0), float(fps or 0.0))   # GR6 (PB3 class)
            if yoyo and n > 1:
                period = 2 * n - 2
                k = step % period
                idx = frames[k if k < n else period - k]
            else:
                idx = frames[step % n] if n else int(self._frame)
        else:
            idx = int(spec)
        saved = (self._frame, self._play_frames)
        self._play_frames = ()
        self._frame = idx
        try:
            yield
        finally:
            self._frame, self._play_frames = saved

    def _draw_body_and_parts(self, skia_canvas: skia.Canvas) -> None:
        from .canvas import _has_any_batchable_filter
        from .transients import compose_draw_mods, draw_with_transients
        tx = getattr(self, "_tx_state", None)
        if tx is not None and tx.any_active():
            mods = compose_draw_mods(self)
            if mods is not None and not mods.is_identity():
                # The label rides inside the envelope (transients._draw_body).
                draw_with_transients(self, skia_canvas, mods)
                return
        scena_canvas = getattr(self, "_scenacanvas", None)
        if (
            scena_canvas is not None
            and scena_canvas.skia_canvas is skia_canvas
            and _has_any_batchable_filter(self)
        ):
            # ImageFilter glow / shadow live on the canvas's filtered route.
            scena_canvas._draw_filtered_one(self)
        else:
            Graphic.draw(self, skia_canvas)
        self._draw_attached(skia_canvas)

    def _draw_attached(self, skia_canvas: skia.Canvas) -> None:
        """Parts drawn with the body (the label); called inside every envelope."""
        t = self._label_text
        if t is None or not t._visible:
            return
        bx, by, bw, bh, ang = self._label_box()
        if bw <= 0.0 or bh <= 0.0:
            return
        k = self._label_fit(bw, bh)
        sc = abs(float(self._scale)) or 1e-6
        skia_canvas.save()
        try:
            skia_canvas.translate(bx, by)
            if ang:
                skia_canvas.rotate(ang)
            skia_canvas.scale(sc * k, sc * k)
            t.draw(skia_canvas)
        finally:
            skia_canvas.restore()

    # --- label -------------------------------------------------------------------

    def _make_label(self, value, *, font=None, font_size=None, color=None) -> None:
        from .text import Text
        if font_size is None:
            _bx, _by, _bw, bh, _a = self._label_box()
            sc = abs(float(self._scale)) or 1.0
            font_size = max(6.0, 0.4 * bh / sc)
        live = value if callable(value) else None
        if live is None and isinstance(value, (int, float)):
            value = str(value)    # a number label (Text itself takes strings)
        t = Text("" if live is not None else value, center=(0, 0), layer=None,
                 stack=False, font=font, font_size=font_size, color=color)
        if live is not None:
            ref = t["text"]
            ref @= live
        t._attr_name = "label_text"
        t.owner = self
        self._label_text = t

    def _label_box(self) -> Tuple[float, float, float, float, float]:
        """``(cx, cy, w, h, angle)`` of the label box in world units (pose scale applied)."""
        cx, cy, w, h, ang = self._oriented_frame()
        sc = abs(float(self._scale))
        left, top, right, bottom = (v * sc for v in self._label_inset)
        lx = 0.5 * (left - right)
        ly = 0.5 * (bottom - top)
        if ang:
            rad = math.radians(ang)
            c, s = math.cos(rad), math.sin(rad)
            cx += lx * c - ly * s
            cy += lx * s + ly * c
        else:
            cx += lx
            cy += ly
        return cx, cy, w - left - right, h - top - bottom, ang

    def _label_fit(self, bw: float, bh: float) -> float:
        """Shrink factor so the label fits its box (never grows; draw-time only)."""
        t = self._label_text
        gw, gh = t._glyph_box_size()
        ls = abs(float(t._scale)) or 1e-6
        sc = abs(float(self._scale)) or 1e-6
        need_w = gw * ls * sc
        need_h = gh * ls * sc
        room_w, room_h = bw * _LABEL_FILL, bh * _LABEL_FILL
        k = 1.0
        if need_w > room_w:
            k = min(k, room_w / need_w)
        if need_h > room_h:
            k = min(k, room_h / need_h)
        if k < 1.0:
            size = float(t.font_size)
            floor = float(getattr(getattr(t, "_theme", None), "menu_min_font_size", 8.0) or 8.0)
            if size * k < floor and size > floor:
                k = floor / size
                if not self._fit_warned:
                    self._fit_warned = True
                    from .process import report_author_warning
                    report_author_warning(
                        "SpriteButton label",
                        f"label {self.label!r} does not fit its button even at font size "
                        f"{floor:g}; it is cut at the edges. Shorten it, widen the button "
                        f"or lower label_inset.",
                        owner=self,
                    )
        return k

    def look_like(self, other) -> "SpriteButton":
        """Copy appearance, the label's look included."""
        super().look_like(other)
        mine = self._label_text
        theirs = getattr(other, "_label_text", None)
        if mine is not None and theirs is not None:
            mine.look_like(theirs)
        return self

    def _clone_recipe(self, *, center=None, frame=None, **kwargs) -> "SpriteButton":
        """Construct another button like this one (handlers are not copied)."""
        t = self._label_text
        if t is not None:
            kwargs.setdefault("label", self.label)
            kwargs.setdefault("font_size", float(t.font_size))
            kwargs.setdefault("font", getattr(t, "font", None))
        for name in ("hover_sound", "click_sound", "hover_scale", "press_scale",
                     "breathe", "breathe_time"):
            kwargs.setdefault(name, getattr(self, name))
        kwargs.setdefault("enabled", bool(self.enabled))
        kwargs.setdefault("label_inset", self._label_inset)
        for k, spec in self._state_art.items():
            kwargs.setdefault(k, spec)
        kwargs.setdefault("layer", self.layer)
        return super()._clone_recipe(center=center, frame=frame, **kwargs)

    # --- click area: convex hull of the rest art ---------------------------------

    def _rest_frames(self) -> Tuple[int, ...]:
        if self._play_frames:
            return tuple(int(i) for i in self._play_frames)
        return (int(self._frame),)

    def _rest_hull_local(self):
        """Hull of the rest art in blit-local space (y down, before flip)."""
        frames = self._rest_frames()
        sx, sy = self._pixel_scale()
        key = (frames, id(self._sheet), sx, sy, self._offset_x, self._offset_y)
        if key == self._rest_hull_key:
            return self._rest_hull
        from .atlas import _display_mask
        pts = []
        sheet = self._sheet
        for idx in frames:
            fr = sheet._frame_at(idx)
            image = sheet._image_for_frame(idx)
            if image is None or sx <= 0.0 or sy <= 0.0:
                continue
            left = (float(fr.src_x) - float(fr.pivot_x) * float(fr.src_w)) * sx + self._offset_x
            top = (float(fr.src_y) - float(fr.pivot_y) * float(fr.src_h)) * sy - self._offset_y
            dw = float(fr.h if fr.rotated else fr.w) * sx
            dh = float(fr.w if fr.rotated else fr.h) * sy
            mask = _display_mask(image, fr)
            mh, mw = mask.shape
            if mw <= 0 or mh <= 0:
                continue
            rows, cols = mask.nonzero()
            cw, ch = dw / mw, dh / mh
            for r, c in zip(rows.tolist(), cols.tolist()):
                x0 = left + c * cw
                y0 = top + r * ch
                pts.extend(((x0, y0), (x0 + cw, y0), (x0, y0 + ch), (x0 + cw, y0 + ch)))
        self._rest_hull = _convex_hull(pts)
        self._rest_hull_key = key
        return self._rest_hull

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Inside the convex hull of the rest art (not the current frame's alpha)."""
        hull = self._rest_hull_local()
        if len(hull) < 3:
            return False
        lx, ly = self._pointer_local(x, y)
        fx = -1.0 if self._flip_x else 1.0
        fy = -1.0 if self._flip_y else 1.0
        return _inside_convex(hull, lx / fx, ly / (-fy))

    def __str__(self) -> str:
        from .entity import made_at
        where = made_at(self)
        return f"SpriteButton({where})" if where else "SpriteButton()"


def _publish_signature() -> None:
    import inspect as _inspect
    sig = _inspect.signature(SpriteButton.__init__)
    SpriteButton.__signature__ = sig.replace(parameters=[
        p for p in sig.parameters.values() if p.name != "self"
    ])


_publish_signature()
