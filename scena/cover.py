"""Canvas cover overlay: fade / wipe / iris, hold until uncover.

Not a ``PostEffect`` and not hit feedback. Drawn after widgets on the window
FB (covers HUD). Does not force the scene render target. ``on_done`` is the
call channel; there is no ``then=`` (canvas is not an Entity).
"""
from __future__ import annotations

import math
import time
from typing import Callable, Optional, Tuple

import skia

from .color import resolve_rgb
from .validate import call_truncated, expect_callable, expect_choice

COVER_STYLES = ("fade", "wipe", "iris")
_SOFT = 0.04  # wipe / iris edge, fraction of the travel range
_EPS = 1e-4

_now_fn: Optional[Callable[[], float]] = None


def set_now_fn(fn: Optional[Callable[[], float]]) -> None:
    """Override the clock (tests). ``None`` restores the presentation clock."""
    global _now_fn
    _now_fn = fn


def _now() -> float:
    if _now_fn is not None:
        return float(_now_fn())
    try:
        from .orchestration import ScenaFramework
        clk = ScenaFramework.get_instance().clock
        if clk is not None:
            # Presentation time, not world time: a fade runs while the world
            # is paused or slowed (a game-over ``fade_out(on_done=change_act)``
            # after ``clock.paused = True`` must finish), and is capped per
            # frame like the world, so a hitch does not skip the fade.
            return float(clk._ui_time)
    except Exception:
        pass
    return time.perf_counter()


def _duration(duration, default: float = 0.5) -> float:
    if duration is None:
        duration = default
    from .validate import seconds
    d = seconds(duration, "duration")
    if d < 0.0:
        raise ValueError("duration must be >= 0")
    return d


def _as_xy(point) -> Tuple[float, float]:
    """Iris center: a point-like (Graphic uses ``.center``), snapshotted."""
    from .shapes import _xy_of
    try:
        return _xy_of(point, required=True)
    except TypeError:
        raise TypeError(
            f"center expected a point-like value, got {type(point)!r}"
        ) from None


def _canvas_facade():
    import builtins
    return getattr(builtins, "canvas", None)


class _Tween:
    __slots__ = (
        "t0", "duration", "start", "end", "on_done",
        "cancelled", "finished", "act_made",
    )

    def __init__(self, t0: float, duration: float, start: float, end: float, on_done):
        self.t0 = float(t0)
        self.duration = float(duration)
        self.start = float(start)
        self.end = float(end)
        self.on_done = on_done
        self.cancelled = False
        self.finished = False
        # Started after the seal (an act's fade): its ``on_done`` belongs to
        # that act and leaves with it (``drop_act_on_done``).
        from .process import _top_level_ended
        self.act_made = bool(_top_level_ended)


class CanvasCover:
    """Singleton cover state. Authors use ``canvas.fade_out`` / ``fade_in``."""

    def __init__(self):
        self.amount = 0.0  # 0 uncovered, 1 fully covered (holds)
        self.color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.style = "fade"
        self.angle = 0.0  # wipe, degrees, 0 = +x
        self.center: Optional[Tuple[float, float]] = None  # iris; None = design center
        self._tween: Optional[_Tween] = None

    def reset(self) -> None:
        """Silent clear (tests / teardown). No ``on_done``."""
        self.amount = 0.0
        self.color = (0.0, 0.0, 0.0)
        self.style = "fade"
        self.angle = 0.0
        self.center = None
        self._tween = None

    def _is_active(self) -> bool:
        return self.amount > _EPS or self._tween is not None

    def fade_out(
        self,
        duration: float = 0.5,
        *,
        color="black",
        style: str = "fade",
        angle: float = 0.0,
        center=None,
        on_done=None,
    ) -> None:
        self._apply_look(color=color, style=style, angle=angle, center=center, uncover=False)
        self._start(target=1.0, duration=duration, on_done=on_done)

    def fade_in(
        self,
        duration: float = 0.5,
        *,
        color=None,
        style=None,
        angle=None,
        center=None,
        on_done=None,
    ) -> None:
        opening = self.amount <= _EPS and self._tween is None
        self._apply_look(color=color, style=style, angle=angle, center=center, uncover=True)
        if opening:
            self.amount = 1.0
        self._start(target=0.0, duration=duration, on_done=on_done)

    def _apply_look(self, *, color, style, angle, center, uncover: bool) -> None:
        if color is not None:
            self.color = resolve_rgb(color, default=(0.0, 0.0, 0.0))
        elif not uncover and color is None:
            self.color = (0.0, 0.0, 0.0)
        if style is not None:
            self.style = expect_choice(style, COVER_STYLES, what="cover style")
        if angle is not None:
            self.angle = float(angle)
        if center is not None:
            self.center = _as_xy(center)

    def _start(self, *, target: float, duration, on_done) -> None:
        dur = _duration(duration, 0.5)
        cb = expect_callable(on_done, none=True, what="on_done")
        self._cancel_tween()
        start = self.amount
        if dur <= 0.0 or abs(start - target) <= _EPS:
            self.amount = target
            self._tween = None
            self._fire(cb)
            return
        self._tween = _Tween(_now(), dur, start, target, cb)

    def _cancel_tween(self) -> None:
        tw = self._tween
        if tw is None or tw.finished:
            self._tween = None
            return
        tw.cancelled = True
        tw.finished = True
        self._tween = None
        self._fire(tw.on_done)

    def _fire(self, cb) -> None:
        if not callable(cb):
            return
        call_truncated(cb, _canvas_facade())

    def tick(self, now: Optional[float] = None) -> None:
        tw = self._tween
        if tw is None or tw.finished:
            return
        t = _now() if now is None else float(now)
        elapsed = t - tw.t0
        # Float-sum slop: 0.2+0.2 may be just shy of 0.4.
        if tw.duration <= 0.0 or elapsed >= tw.duration - 1e-6:
            u = 1.0
        else:
            u = max(0.0, elapsed / tw.duration)
        self.amount = tw.start + (tw.end - tw.start) * u
        if u >= 1.0:
            self.amount = tw.end
            tw.finished = True
            self._tween = None
            self._fire(tw.on_done)

    def draw(self, canvas, w: float, h: float) -> None:
        if self.amount <= _EPS:
            return
        w = float(w)
        h = float(h)
        if w <= 0.0 or h <= 0.0:
            return
        r, g, b = self.color
        style = self.style
        canvas.save()
        try:
            if self.amount >= 1.0 - _EPS:
                self._draw_fade(canvas, w, h, r, g, b)
            elif style == "wipe":
                self._draw_wipe(canvas, w, h, r, g, b)
            elif style == "iris":
                self._draw_iris(canvas, w, h, r, g, b)
            else:
                self._draw_fade(canvas, w, h, r, g, b)
        finally:
            canvas.restore()

    def _draw_fade(self, canvas, w, h, r, g, b) -> None:
        paint = skia.Paint(
            Color4f=skia.Color4f(r, g, b, float(self.amount)),
            AntiAlias=False,
            BlendMode=skia.BlendMode.kSrcOver,
        )
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, w, h), paint)

    def _draw_wipe(self, canvas, w, h, r, g, b) -> None:
        u = float(self.amount)
        rad = math.radians(self.angle)
        ca, sa = math.cos(rad), math.sin(rad)
        corners = ((0.0, 0.0), (w, 0.0), (w, h), (0.0, h))
        dots = [x * ca + y * sa for x, y in corners]
        lo, hi = min(dots), max(dots)
        span = hi - lo
        if span < 1e-6:
            self._draw_fade(canvas, w, h, r, g, b)
            return
        # Gradient along the wipe axis spanning the rect's projected range.
        p0 = skia.Point(ca * lo, sa * lo)
        p1 = skia.Point(ca * hi, sa * hi)
        soft = _SOFT
        t0 = max(0.0, u - soft)
        t1 = min(1.0, u + soft)
        opaque = skia.Color4f(r, g, b, 1.0)
        clear = skia.Color4f(r, g, b, 0.0)
        shader = skia.GradientShader.MakeLinear(
            [p0, p1],
            [opaque, opaque, clear, clear],
            [0.0, t0, t1, 1.0],
        )
        paint = skia.Paint(
            Shader=shader,
            AntiAlias=True,
            BlendMode=skia.BlendMode.kSrcOver,
        )
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, w, h), paint)

    def _draw_iris(self, canvas, w, h, r, g, b) -> None:
        if self.center is None:
            cx, cy = w * 0.5, h * 0.5
        else:
            cx, cy = self.center
        # Farthest corner so amount=0 is fully uncovered.
        R = max(
            math.hypot(cx - 0.0, cy - 0.0),
            math.hypot(cx - w, cy - 0.0),
            math.hypot(cx - w, cy - h),
            math.hypot(cx - 0.0, cy - h),
        )
        R = max(R, 1.0)
        visible = (1.0 - float(self.amount)) * R
        soft = _SOFT * R
        inner = max(0.0, (visible - soft) / R)
        outer = min(1.0, (visible + soft) / R)
        opaque = skia.Color4f(r, g, b, 1.0)
        clear = skia.Color4f(r, g, b, 0.0)
        shader = skia.GradientShader.MakeRadial(
            skia.Point(cx, cy),
            R,
            [clear, clear, opaque, opaque],
            [0.0, inner, outer, 1.0],
        )
        paint = skia.Paint(
            Shader=shader,
            AntiAlias=True,
            BlendMode=skia.BlendMode.kSrcOver,
        )
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, w, h), paint)


_cover = CanvasCover()


def get_cover() -> CanvasCover:
    return _cover


def drop_act_on_done() -> None:
    """An act change: the cover survives (a fade crosses the change) but an
    in-flight ``on_done`` an act gave it does not: it would fire in the next
    act and redirect the game (review 2026-10-09 S4-2; Act Design)."""
    tw = _cover._tween
    if tw is not None and not tw.finished and tw.act_made:
        tw.on_done = None


def tick_cover(now: Optional[float] = None) -> None:
    _cover.tick(now)


def draw_cover(canvas, w: float, h: float) -> None:
    _cover.draw(canvas, w, h)


def is_cover_active() -> bool:
    return _cover._is_active()


def reset_cover() -> None:
    _cover.reset()
