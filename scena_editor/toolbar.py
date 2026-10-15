"""Icon tool buttons and their tooltip (Scena Graphics on the ``ui`` layer).

Scena draws every widget after the whole ``ui`` layer, so an icon cannot sit
on a ``Button``. A tool button is a ``ui`` Rect holding the pointer handlers;
its icon and corner letter are Graphics with none, which Scena leaves out of
hit tests, so the pointer always reaches the Rect. Each icon is drawn with
the Scena shape the tool makes (the Polygon button shows a ``Polygon``).
"""
from __future__ import annotations

import time
from typing import Any, Callable, List, Optional, Tuple

from scena import (Circle, Color, Concave, Ellipse, Line, Polygon, Rect, RegularPolygon, Text,
                   Track, Triangle)

from .view import DESIGN

W, H = DESIGN
BG = Color(0.11, 0.115, 0.13, 0.97)
ACCENT = Color(1.0, 0.82, 0.25, 0.9)
IDLE = Color(0.18, 0.19, 0.22)
HOVER = Color(0.27, 0.29, 0.34)
INK = Color(0.86, 0.88, 0.92)          # icon on an idle / hovered button
INK_ACTIVE = Color(0.12, 0.12, 0.14)   # icon on the accent (current tool)
LETTER = Color(0.62, 0.65, 0.72)
TIP_BG = Color(0.24, 0.27, 0.34)
STROKE = 1.6


def _safe(fn, *args, say=None):
    """A Button action that reports an error instead of closing the editor
    (an exception in a Scena callback ends ``run()``): logged, and named in
    the status bar through ``say`` (the App's)."""
    def click():
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001 — a bug must not close the editor
            import traceback
            from . import log
            from .i18n import t
            traceback.print_exc()
            path = log.write_error(e, getattr(fn, "__name__", "button"))
            if callable(say):
                say(t("error.internal", error=f"{type(e).__name__}: {e}", log=path))
    return click


def _rect(x0, y0, x1, y1, color) -> Rect:
    r = Rect(center=((x0 + x1) / 2, (y0 + y1) / 2), width=x1 - x0, height=y1 - y0, layer="ui")
    r.fill = color
    r.line = None
    return r


# -- icons -----------------------------------------------------------------------------
# Each takes the icon's center and half-size ``s`` and returns its parts as
# (graphic, paints) — paints: "line", "fill" or "both" (recolored when the
# button turns active).

Part = Tuple[Any, str]


def _stroke(g, paints: str = "line") -> Part:
    if paints == "line":
        g.fill = None
    g.line_width = STROKE
    return g, paints


def _icon_rect(cx, cy, s) -> List[Part]:
    return [_stroke(Rect(center=(cx, cy), width=2 * s, height=1.3 * s, layer="ui"))]


def _icon_ellipse(cx, cy, s) -> List[Part]:
    return [_stroke(Ellipse(center=(cx, cy), width=2 * s, height=1.3 * s, layer="ui"))]


def _icon_concave(cx, cy, s) -> List[Part]:
    # A quarter-pipe: the curve rises from the bottom left to the top right.
    return [_stroke(Concave(center=(cx, cy), width=1.8 * s, height=1.8 * s, rim=(0.25 * s, 0),
                            layer="ui"))]


def _icon_circle(cx, cy, s) -> List[Part]:
    return [_stroke(Circle(center=(cx, cy), radius=s * 0.9, layer="ui"))]


def _icon_line(cx, cy, s) -> List[Part]:
    return [_stroke(Line(p1=(cx - s, cy - s * 0.8), p2=(cx + s, cy + s * 0.8), layer="ui"))]


def _icon_polygon(cx, cy, s) -> List[Part]:
    # Free corners, one notch: not a regular shape (that is the next tool's).
    pts = [(cx - s, cy - 0.8 * s), (cx + s, cy - 0.8 * s), (cx + 0.7 * s, cy + 0.85 * s),
           (cx + 0.05 * s, cy + 0.1 * s), (cx - 0.6 * s, cy + 0.7 * s)]
    return [_stroke(Polygon(points=pts, layer="ui"))]


def _icon_triangle(cx, cy, s) -> List[Part]:
    # Apex up; the centroid sits a quarter radius below the icon's middle.
    r = 1.1 * s
    return [_stroke(Triangle(center=(cx, cy - 0.25 * r), radius=r, angle=90, layer="ui"))]


def _icon_regular_polygon(cx, cy, s) -> List[Part]:
    return [_stroke(RegularPolygon(n=6, center=(cx, cy), radius=s * 0.95, angle=90,
                                   layer="ui"))]


def _icon_track(cx, cy, s) -> List[Part]:
    pts = [(cx - s, cy - s * 0.6), (cx - s * 0.35, cy + s * 0.6),
           (cx + s * 0.3, cy - s * 0.4), (cx + s, cy + s * 0.7)]
    track = Track(points=pts, smooth=0, closed=False, color=INK, line_width=STROKE, layer="ui")
    return [(track, "line")]


def _icon_point(cx, cy, s) -> List[Part]:
    dot = Circle(center=(cx, cy), radius=s * 0.3, layer="ui")
    dot.line = None
    ring = _stroke(Circle(center=(cx, cy), radius=s * 0.75, layer="ui"))
    return [(dot, "fill"), ring]


def _icon_image(cx, cy, s) -> List[Part]:
    frame = _stroke(Rect(center=(cx, cy), width=2 * s, height=1.5 * s, layer="ui"))
    bottom = cy - 0.75 * s
    hill = Polygon(points=[(cx - s, bottom), (cx - s * 0.2, cy + s * 0.25),
                           (cx + s * 0.3, cy - s * 0.2), (cx + s * 0.55, cy),
                           (cx + s, cy - s * 0.4), (cx + s, bottom)], layer="ui")
    hill.line = None
    sun = Circle(center=(cx + s * 0.45, cy + s * 0.4), radius=s * 0.18, layer="ui")
    sun.line = None
    return [frame, (hill, "fill"), (sun, "fill")]


def _icon_select(cx, cy, s) -> List[Part]:
    # An arrow cursor, tip at the top left.
    x, y = cx - s * 0.55, cy + s
    pts = [(x, y), (x, y - 1.75 * s), (x + 0.45 * s, y - 1.35 * s), (x + 0.75 * s, y - 2.0 * s),
           (x + 1.0 * s, y - 1.88 * s), (x + 0.72 * s, y - 1.25 * s), (x + 1.25 * s, y - 1.25 * s)]
    return [_stroke(Polygon(points=pts, layer="ui"), "both")]


def _icon_hand(cx, cy, s) -> List[Part]:
    # Four-way arrows: the view moves in every direction.
    parts: List[Part] = [_stroke(Line(p1=(cx - s, cy), p2=(cx + s, cy), layer="ui")),
                         _stroke(Line(p1=(cx, cy - s), p2=(cx, cy + s), layer="ui"))]
    h = s * 0.35
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        tip = (cx + dx * s * 1.05, cy + dy * s * 1.05)
        back = (tip[0] - dx * h, tip[1] - dy * h)
        side = (-dy * h * 0.8, dx * h * 0.8)
        head = Polygon(points=[tip, (back[0] + side[0], back[1] + side[1]),
                               (back[0] - side[0], back[1] - side[1])], layer="ui")
        head.line = None
        parts.append((head, "fill"))
    return parts


ICONS = {
    "select": _icon_select, "hand": _icon_hand, "rect": _icon_rect, "ellipse": _icon_ellipse,
    "circle": _icon_circle, "line": _icon_line, "polygon": _icon_polygon,
    "triangle": _icon_triangle, "regular_polygon": _icon_regular_polygon,
    "track": _icon_track, "concave": _icon_concave,
    "point": _icon_point, "image": _icon_image,
}


# -- tooltip ---------------------------------------------------------------------------

class Tooltip:
    """One hint box, shown next to the hovered button and kept in the window.

    Timing, as desktop toolkits do it: a tooltip appears after the pointer
    rests ``DELAY`` seconds; once one has shown, the next button's shows at
    once ("warm") until the pointer has been off the buttons ``COOL`` seconds;
    a click hides it until the pointer leaves that button. ``tick()`` runs
    every frame (``Panel.refresh``).
    """

    PAD = 6.0
    DELAY = 0.6
    COOL = 0.3

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.box = _rect(0, 0, 1, 1, TIP_BG)
        self.box.line = Color(0.45, 0.5, 0.6)
        self.box.line_width = 1.0
        self.text = Text("", top_left=(0, 0), font_size=13, stack=False)
        self.owner: Any = None
        self._pending: Optional[tuple] = None    # (owner, text, at, side, since)
        self._warm_until = 0.0
        self._muted: Any = None                  # clicked: no tooltip until it is left
        self._hide()

    @property
    def visible(self) -> bool:
        return self.box.visible

    # -- what the buttons call -----------------------------------------------------------
    def request(self, owner: Any, text: str, at: Tuple[float, float], side: str) -> None:
        """The pointer entered ``owner``: show ``text`` now when warm, else after DELAY."""
        if owner is self._muted:
            return
        if self.visible or self.clock() < self._warm_until:
            self._pending = None
            self._show(owner, text, at, side)
        else:
            self._pending = (owner, text, at, side, self.clock())

    def leave(self, owner: Any) -> None:
        """The pointer left ``owner``."""
        if owner is self._muted:
            self._muted = None
        if self._pending is not None and self._pending[0] is owner:
            self._pending = None
        if self.owner is owner:
            self._hide()
            self._warm_until = self.clock() + self.COOL

    def dismiss(self, owner: Any) -> None:
        """``owner`` was clicked: hide, and stay quiet until the pointer leaves it."""
        self._pending = None
        self._warm_until = 0.0
        self._muted = owner
        self._hide()

    def tick(self) -> None:
        p = self._pending
        if p is not None and self.clock() - p[4] >= self.DELAY:
            self._pending = None
            self._show(*p[:4])

    # -- drawing -------------------------------------------------------------------------
    def _show(self, owner: Any, text: str, at: Tuple[float, float], side: str) -> None:
        """``side`` "right" / "left": the box's near edge at ``at``, centered
        on its y; "below": its top edge at ``at``, centered on its x."""
        self.owner = owner
        self.text.text = text
        tb = self.text.box
        w, h = tb.right - tb.left + 2 * self.PAD, tb.top - tb.bottom + 2 * self.PAD
        x, y = at
        if side == "right":
            x0, y1 = x, y + h / 2
        elif side == "left":
            x0, y1 = x - w, y + h / 2
        else:
            x0, y1 = x - w / 2, y
        x0 = min(max(x0, 2.0), W - 2.0 - w)
        y1 = min(max(y1, h + 2.0), H - 2.0)
        self.box.center = (x0 + w / 2, y1 - h / 2)
        self.box.width, self.box.height = w, h
        self.text.top_left = (x0 + self.PAD, y1 - self.PAD)
        self.box.visible = self.text.visible = True
        # Above the ui Graphics made after it (icon buttons); widgets always
        # draw over the ui layer, so callers place it beside them, not on them.
        self.box.move_to_front()
        self.text.move_to_front()

    def _hide(self) -> None:
        self.owner = None
        self.box.visible = self.text.visible = False


def attach_tip(widget, tooltip: Tooltip, text: str, side: str = "below",
               edge: Optional[float] = None) -> None:
    """Give a Scena widget (Button, CheckBox …) a delayed tooltip on ``side``
    ("below" / "left" / "right") of it; a click hides it. ``edge``: the x the
    box keeps to on "left" / "right" — clear of a whole column of widgets,
    which would draw over it."""
    def at():
        b = widget.box
        if side == "below":
            return ((b.left + b.right) / 2, b.bottom - 6)
        if side == "left":
            return (b.left - 8 if edge is None else edge, (b.top + b.bottom) / 2)
        return (b.right + 8 if edge is None else edge, (b.top + b.bottom) / 2)

    widget.on_hover = lambda: tooltip.request(widget, text, at(), side)
    widget.on_hover_exit = lambda: tooltip.leave(widget)
    click = getattr(widget, "on_click", None)
    if click is not None:
        def clicked():
            tooltip.dismiss(widget)
            click()
        widget.on_click = clicked


# -- the button ------------------------------------------------------------------------

class ToolButton:
    """A tool's icon button: click chooses it, hover shows ``tip``, the corner
    shows its ``key``; ``set_active`` paints it as the current tool."""

    def __init__(self, tool: str, center: Tuple[float, float], size: Tuple[float, float],
                 on_click: Callable[[], None], tip: str, tooltip: Tooltip, *,
                 key: Optional[str] = None, tip_side: str = "right"):
        cx, cy = center
        w, h = size
        self.tool = tool
        self.tip = tip
        self.tooltip = tooltip
        self.tip_side = tip_side
        self.active = False
        self.hovered = False
        self._box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        self.bg = _rect(*self._box, IDLE)
        self.standby = False
        self._on_click = on_click
        self.bg.on_click = self._click
        self.bg.on_hover = self._enter
        self.bg.on_hover_exit = self._exit
        lift = 3.0 if key else 0.0           # room for the letter under the icon's corner
        self.parts = ICONS[tool](cx - lift, cy + lift, min(w, h) * 0.3)
        self.letter: Optional[Text] = None
        if key:
            self.letter = Text(key, top_right=(cx + w / 2 - 3, cy - h / 2 + 15), font_size=10,
                               color=LETTER, stack=False)
        self._paint()

    @property
    def box(self) -> Tuple[float, float, float, float]:
        """(x0, y0, x1, y1) in view space."""
        return self._box

    def set_active(self, active: bool) -> None:
        if active != self.active:
            self.active = active
            self._paint()

    def set_standby(self, standby: bool) -> None:
        """An accent outline: this tool is what a press does right now (Select
        while Primary is held in another tool)."""
        if standby != self.standby:
            self.standby = standby
            self._paint()

    def _click(self) -> None:
        self.tooltip.dismiss(self)
        self._on_click()

    def _enter(self) -> None:
        self.hovered = True
        self._paint()
        x0, y0, x1, y1 = self.box
        if self.tip_side == "right":
            self.tooltip.request(self, self.tip, (x1 + 8, (y0 + y1) / 2), "right")
        else:
            self.tooltip.request(self, self.tip, ((x0 + x1) / 2, y0 - 6), "below")

    def _exit(self) -> None:
        self.hovered = False
        self._paint()
        self.tooltip.leave(self)

    def _paint(self) -> None:
        self.bg.fill = ACCENT if self.active else HOVER if self.hovered else IDLE
        self.bg.line = ACCENT if self.standby and not self.active else None
        self.bg.line_width = 2.0
        ink = INK_ACTIVE if self.active else INK
        for g, paints in self.parts:
            if paints in ("line", "both"):
                g.line = ink
            if paints in ("fill", "both"):
                g.fill = ink
        if self.letter is not None:
            self.letter.color = INK_ACTIVE if self.active else LETTER
