"""Shape-local transient effects: trigger → progress → finish.

Orthogonal to sticky visuals / filters. Lifecycle advances in
``tick_all_transients`` (pre-draw); ``Shape.draw`` only reads progress.

Author grammar (Shape methods and this module's twins):
``verb(duration=DEFAULT, *, look..., on_done=None)``.
A bare number is always seconds; look knobs are keyword-only.
"""
from __future__ import annotations

import math
import time
import traceback
import warnings
import weakref
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional, Set, TYPE_CHECKING

import skia

from .entity import scena_kind
from .color import resolve_rgba
from .validate import call_truncated, expect_callable, expect_choice

if TYPE_CHECKING:
    from .shapes import Shape

DoneFn = Optional[Callable[..., None]]
DissolveStyle = Literal["noise", "vortex", "wipe", "fade"]
DISSOLVE_STYLES = ("noise", "vortex", "wipe", "fade")

# ---------------------------------------------------------------------------
# Clock (injectable for tests)
# ---------------------------------------------------------------------------

_now_fn: Optional[Callable[[], float]] = None


def set_now_fn(fn: Optional[Callable[[], float]]) -> None:
    """Override the transient clock (tests). Pass None to restore presentation time."""
    global _now_fn
    _now_fn = fn


def _now() -> float:
    """Presentation time (``clock._ui_time``), like the canvas cover.

    A transient is a screen effect: it runs while the world is paused or
    slowed (a pause menu still animates), and a frame feeds it at most
    ``MAX_FRAME_DT``, so a hitch does not jump it to its end, and a headless
    run is a function of its frames (LW6). ``perf_counter`` only when no
    framework exists yet.
    """
    if _now_fn is not None:
        return float(_now_fn())
    fw = (_framework or _bind_framework())._instance
    if fw is not None:
        clk = getattr(fw, "clock", None)
        if clk is not None:
            return clk._ui_time
    return time.perf_counter()


_framework = None   # ScenaFramework, bound on the first read (an import cycle at load)


def _bind_framework():
    global _framework
    from .orchestration import ScenaFramework
    _framework = ScenaFramework
    return ScenaFramework


def _clamp_duration(duration: float, default: float) -> float:
    from .validate import seconds
    return max(0.05, seconds(duration, "duration"))


def _progress(t0: float, duration: float, now: float) -> float:
    if duration <= 0:
        return 1.0
    from .process import reached
    if reached(now - t0, duration):
        return 1.0          # a whole number of frames, short by rounding (PM8)
    return max(0.0, min(1.0, (now - t0) / duration))


# ---------------------------------------------------------------------------
# Draw mods (pure composition result)
# ---------------------------------------------------------------------------

@dataclass
class DrawMods:
    alpha_mul: float = 1.0
    scale_mul: float = 1.0
    flash_amount: float = 0.0
    dissolve_progress: float = 0.0  # 0 full solid, 1 fully erased
    dissolve_seed: float = 0.0
    dissolve_style: str = "noise"  # noise | vortex | wipe
    dissolve_angle: float = 0.0  # degrees (converted at SkSL)
    burn_fire: float = 0.0
    pulse_color: Optional[tuple] = None
    pulse_width: float = 0.0
    pulse_alpha: float = 0.0
    spark_pad: float = 0.0  # design units of extra pad while sparks fly
    offset_x: float = 0.0  # draw-only knock (CTM)
    offset_y: float = 0.0

    def is_identity(self) -> bool:
        return (
            abs(self.alpha_mul - 1.0) < 1e-6
            and abs(self.scale_mul - 1.0) < 1e-6
            and self.flash_amount <= 1e-6
            and self.dissolve_progress <= 1e-6
            and self.burn_fire <= 1e-6
            and self.pulse_alpha <= 1e-6
            and self.spark_pad <= 1e-6
            and abs(self.offset_x) < 1e-6
            and abs(self.offset_y) < 1e-6
        )

    def needs_save_layer(self) -> bool:
        return (
            abs(self.alpha_mul - 1.0) > 1e-6
            or self.dissolve_progress > 1e-6
        )


def _normalize_dissolve_style(style) -> str:
    return expect_choice(style, DISSOLVE_STYLES, what="dissolve style")



# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

class TransientChannel:
    """One timed effect occupying a shape slot."""

    kind: str = "base"
    hide_on_finish: bool = False
    show_on_finish: bool = False

    def __init__(
        self,
        duration: float,
        *,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
    ):
        self.duration = float(duration)
        self.t0 = float(_now() if t0 is None else t0)
        self.on_done = expect_callable(on_done, none=True, what="on_done")
        self._finished_applied = False
        self._cancelled = False

    @property
    def done(self) -> bool:
        """True after natural finish or cancel (``on_done`` already ran or was skipped)."""
        return self._finished_applied

    @property
    def cancelled(self) -> bool:
        """True if replaced / cleared before natural completion (not destroy)."""
        return self._cancelled

    def progress(self, now: Optional[float] = None) -> float:
        return _progress(self.t0, self.duration, _now() if now is None else float(now))

    def finished(self, now: Optional[float] = None) -> bool:
        return self.progress(now) >= 1.0

    def contribute(self, mods: DrawMods, now: float) -> None:
        pass

    def overlay_after_body(self, shape, skia_canvas, now: float) -> None:
        pass

    def _fire_on_done(self, shape) -> None:
        # Hard-destroyed shapes: never run late author callbacks
        if not getattr(shape, "is_alive", True):
            return
        cb = self.on_done
        if callable(cb):
            call_truncated(cb, shape)

    def finish(self, shape) -> None:
        if self._finished_applied:
            return
        self._finished_applied = True
        if self.hide_on_finish:
            try:
                shape.visible = False
            except Exception:
                pass
        if self.show_on_finish:
            try:
                shape.visible = True
            except Exception:
                pass
        self._fire_on_done(shape)

    def cancel(self, shape) -> None:
        """Interrupt this channel: mark cancelled and fire ``on_done`` once."""
        if self._finished_applied:
            return
        self._cancelled = True
        self._finished_applied = True
        self._fire_on_done(shape)

    def refresh(self, other: "TransientChannel") -> bool:
        """Same-kind deadline extend. Default: not refreshable (caller replaces)."""
        return False


class Dissolve(TransientChannel):
    """Noise / vortex / wipe erase of the silhouette, then hide."""

    kind = "dissolve"
    hide_on_finish = True

    def __init__(
        self,
        duration: float = 0.5,
        *,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
        seed: Optional[float] = None,
        style: str = "noise",
        angle: float = 0.0,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.seed = float(seed if seed is not None else (self.t0 * 12.9898) % 1000.0)
        self.style = _normalize_dissolve_style(style)
        self.angle = float(angle)

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        if self.style == "fade":
            mods.alpha_mul *= max(0.0, 1.0 - u)
            return
        mods.dissolve_progress = max(mods.dissolve_progress, u)
        mods.dissolve_seed = self.seed
        mods.dissolve_style = self.style
        mods.dissolve_angle = self.angle
        mods.alpha_mul *= max(0.0, 1.0 - 0.22 * u)


class DissolveIn(TransientChannel):
    """Inverse dissolve — materialize from dig (or fade-in). Stays visible."""

    kind = "dissolve_in"
    hide_on_finish = False
    show_on_finish = True

    def __init__(
        self,
        duration: float = 0.5,
        *,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
        seed: Optional[float] = None,
        style: str = "noise",
        angle: float = 0.0,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.seed = float(seed if seed is not None else (self.t0 * 19.17) % 1000.0)
        self.style = _normalize_dissolve_style(style)
        self.angle = float(angle)

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        if self.style == "fade":
            mods.alpha_mul *= max(0.0, min(1.0, u))
            return
        # dig 1→0 as progress advances
        dig = max(0.0, 1.0 - u)
        mods.dissolve_progress = max(mods.dissolve_progress, dig)
        mods.dissolve_seed = self.seed
        mods.dissolve_style = self.style
        mods.dissolve_angle = self.angle
        # slight soft intro so holes don't flash fully hollow at frame 0 glitch
        mods.alpha_mul *= max(0.05, min(1.0, 0.35 + 0.65 * u))


class FadeOut(TransientChannel):
    kind = "fade_out"
    hide_on_finish = True

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        mods.alpha_mul *= max(0.0, 1.0 - u)


class FadeIn(TransientChannel):
    kind = "fade_in"
    hide_on_finish = False
    show_on_finish = True

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        mods.alpha_mul *= max(0.0, min(1.0, u))


class Implode(TransientChannel):
    """Scale + alpha collapse then hide (absorb / collect)."""

    kind = "implode"
    hide_on_finish = True

    def __init__(
        self,
        duration: float = 0.28,
        *,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
        scale_end: float = 0.05,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.scale_end = max(0.01, min(0.95, float(scale_end)))

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)

        def _smooth(x: float) -> float:
            x = max(0.0, min(1.0, x))
            return x * x * (3.0 - 2.0 * x)

        t = _smooth(u)
        mods.scale_mul *= max(self.scale_end, 1.0 + (self.scale_end - 1.0) * t)
        mods.alpha_mul *= max(0.0, 1.0 - t * 0.95)


class Burn(TransientChannel):
    """Exit fire multipass + dig. Borderless soft fire body."""

    kind = "burn"
    hide_on_finish = True

    def __init__(
        self,
        duration: float = 0.55,
        *,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
        seed: Optional[float] = None,
        intensity: float = 1.0,
        speed: float = 1.2,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.seed = float(seed if seed is not None else (self.t0 * 7.13) % 1000.0)
        self.intensity = float(intensity)
        self.speed = float(speed)

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        if u < 0.5:
            fire = 1.0
            dig = u * 0.22
        else:
            t = (u - 0.5) / 0.5
            fire = max(0.15, 1.0 - 0.9 * t)
            dig = 0.11 + t * 0.89
        mods.burn_fire = max(mods.burn_fire, fire * self.intensity)
        mods.dissolve_progress = max(mods.dissolve_progress, dig)
        mods.dissolve_seed = self.seed
        mods.dissolve_style = "noise"
        mods.alpha_mul *= max(0.0, 1.0 - 0.12 * u)


class Flash(TransientChannel):
    kind = "flash"
    hide_on_finish = False

    def __init__(
        self,
        duration: float = 0.12,
        *,
        intensity: float = 1.0,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.intensity = float(intensity)

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        # Peak at start, decay
        mods.flash_amount = max(
            mods.flash_amount,
            self.intensity * max(0.0, (1.0 - u) ** 1.5),
        )


class Blink(TransientChannel):
    """Strobe alpha (invuln / attention). Replaces flash; a second blink refreshes."""

    kind = "blink"
    hide_on_finish = False

    def __init__(
        self,
        duration: float = 0.8,
        *,
        rate: float = 8.0,
        intensity: float = 1.0,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.rate = max(1.0, float(rate))
        self.intensity = max(0.0, min(1.0, float(intensity)))

    def refresh(self, other: TransientChannel) -> bool:
        """Keep phase (``t0`` / rate); push the end so remaining ≥ ``other.duration``."""
        if not isinstance(other, Blink) or self._finished_applied:
            return False
        elapsed = max(0.0, _now() - self.t0)
        self.duration = max(self.duration, elapsed + float(other.duration))
        self.intensity = max(self.intensity, other.intensity)
        if other.on_done is not None:
            self.on_done = other.on_done
        return True

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        # Duty ~half; phase from wall time for continuous flicker
        phase = math.sin(self.rate * math.pi * 2.0 * (now - self.t0))
        on = 1.0 if phase >= 0.0 else max(0.08, 1.0 - self.intensity)
        # Soft tail so last frame doesn't pop fully on
        env = 1.0 if u < 0.85 else max(0.0, (1.0 - u) / 0.15)
        mods.alpha_mul *= (1.0 - env) + env * on
        # Mild flash while "on"
        if phase >= 0.0:
            mods.flash_amount = max(mods.flash_amount, 0.25 * self.intensity * env)


class Knock(TransientChannel):
    """Brief draw-offset punch (does not move geometry attributes)."""

    kind = "knock"
    hide_on_finish = False

    def __init__(
        self,
        duration: float = 0.14,
        *,
        dx: float = 0.0,
        dy: float = 0.0,
        distance: Optional[float] = None,
        angle: Optional[float] = None,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        if distance is not None and angle is not None:
            rad = math.radians(float(angle))
            d = float(distance)
            self.dx = d * math.cos(rad)
            self.dy = d * math.sin(rad)
        else:
            self.dx = float(dx)
            self.dy = float(dy)

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        # Kick out then ease back
        if u < 0.35:
            t = u / 0.35
            k = t * t * (3.0 - 2.0 * t)
        else:
            t = (u - 0.35) / 0.65
            k = 1.0 - (t * t * (3.0 - 2.0 * t))
        mods.offset_x += self.dx * k
        mods.offset_y += self.dy * k



class PulseOutline(TransientChannel):
    kind = "pulse"
    hide_on_finish = False

    def __init__(
        self,
        duration: float = 0.25,
        *,
        color=(1.0, 1.0, 1.0, 1.0),
        t0: Optional[float] = None,
        on_done: DoneFn = None,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.color = resolve_rgba(color, (1.0, 1.0, 1.0, 1.0))

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        # Expand then fade
        if u < 0.4:
            w = 2.0 + 6.0 * (u / 0.4)
            a = 0.95
        else:
            t = (u - 0.4) / 0.6
            w = 8.0 * (1.0 - t)
            a = 0.95 * (1.0 - t)
        mods.pulse_color = self.color
        mods.pulse_width = max(mods.pulse_width, w)
        mods.pulse_alpha = max(mods.pulse_alpha, a * self.color[3])


class Pop(TransientChannel):
    kind = "pop"
    hide_on_finish = False

    def __init__(
        self,
        duration: float = 0.18,
        *,
        scale: float = 1.2,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.peak = max(1.0, float(scale))

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        peak = self.peak

        def _smooth(x: float) -> float:
            x = max(0.0, min(1.0, x))
            return x * x * (3.0 - 2.0 * x)

        if u < 0.35:
            s = 1.0 + (peak - 1.0) * _smooth(u / 0.35)
        else:
            s = peak + (1.0 - peak) * _smooth((u - 0.35) / 0.65)
        mods.scale_mul *= s


class SparkBurst(TransientChannel):
    """One-shot crackle flecks outward from shape center (does not hide shape)."""

    kind = "spark"
    hide_on_finish = False

    def __init__(
        self,
        duration: float = 0.35,
        *,
        amount: float = 1.0,
        color=(1.0, 0.92, 0.75, 1.0),
        t0: Optional[float] = None,
        on_done: DoneFn = None,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.amount = max(0.15, float(amount))
        self.color = resolve_rgba(color, (1.0, 0.92, 0.75, 1.0))

    def contribute(self, mods: DrawMods, now: float) -> None:
        u = self.progress(now)
        # Early burst needs pad; shrink as they fade
        fade = max(0.0, 1.0 - u)
        mods.spark_pad = max(mods.spark_pad, 28.0 * self.amount * fade)

    def overlay_after_body(self, shape, skia_canvas, now: float) -> None:
        u = self.progress(now)
        if u >= 1.0:
            return
        # Peak early, then fade
        env = (1.0 - u) ** 1.35
        if env < 1e-3:
            return
        cx, cy, r = shape_pivot(shape)
        t = now * 1.0
        n = max(10, int(12 + self.amount * 10))

        def _frac(x: float) -> float:
            return x - math.floor(x)

        def _hash2(a: float, b: float) -> float:
            return _frac(math.sin(a * 127.1 + b * 311.7) * 43758.5453)

        for i in range(n):
            h0 = _hash2(i + 1.0 + self.t0, 0.17)
            h1 = _hash2(i + 1.0 + self.t0, 1.93)
            h2 = _hash2(i + 1.0 + self.t0, 3.71)
            h3 = _hash2(i + 1.0 + self.t0, 5.29)
            # Expand outward with progress
            phase = min(1.0, u * (0.85 + 0.4 * h0) + 0.05)
            ang = h3 * 2.0 * math.pi + h1 * 0.4
            rad = r * (0.15 + 1.1 * phase ** 0.75) * self.amount
            fade = env * (1.0 - phase * 0.55) * (0.55 + 0.45 * h0)
            if h2 < 0.12:
                continue
            jx = (h1 - 0.5) * r * 0.12
            jy = (h2 - 0.5) * r * 0.12
            sx = cx + math.cos(ang) * rad + jx
            sy = cy + math.sin(ang) * rad + jy
            pr = max(0.4, (0.5 + 0.7 * h1) * fade * self.amount)
            spark = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kFill_Style,
                Color4f=skia.Color4f(
                    self.color[0], self.color[1], self.color[2],
                    0.92 * fade * self.color[3],
                ),
                BlendMode=skia.BlendMode.kPlus,
            )
            skia_canvas.drawCircle(sx, sy, pr, spark)
            d1 = (2.2 + 4.0 * h0) * fade * max(0.6, r / 28.0)
            a1 = ang + (h1 - 0.5) * 1.1
            path = skia.Path()
            path.moveTo(sx, sy)
            path.lineTo(sx - math.cos(a1) * d1, sy - math.sin(a1) * d1)
            streak = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=0.75,
                Color4f=skia.Color4f(
                    self.color[0], self.color[1], self.color[2], 0.55 * fade,
                ),
                BlendMode=skia.BlendMode.kPlus,
            )
            skia_canvas.drawPath(path, streak)


# ---------------------------------------------------------------------------
# Per-shape state + registry
# ---------------------------------------------------------------------------

_CHANNEL_NAMES = ("life", "flash", "pulse", "pop", "knock", "spark", "text")

_active_shapes: "weakref.WeakSet[Any]" = weakref.WeakSet()


@dataclass
class ShapeTransientState:
    life: Optional[TransientChannel] = None
    flash: Optional[TransientChannel] = None
    pulse: Optional[TransientChannel] = None
    pop: Optional[TransientChannel] = None
    knock: Optional[TransientChannel] = None
    spark: Optional[TransientChannel] = None
    text: Optional[TransientChannel] = None

    def channels(self):
        for name in _CHANNEL_NAMES:
            ch = getattr(self, name, None)
            if ch is not None:
                yield name, ch

    def any_active(self) -> bool:
        return any(getattr(self, n) is not None for n in _CHANNEL_NAMES)

    def compose(self, now: Optional[float] = None) -> DrawMods:
        mods = DrawMods()
        t = _now() if now is None else float(now)
        for _, ch in self.channels():
            ch.contribute(mods, t)
        return mods

    def tick(self, shape, now: Optional[float] = None) -> None:
        t = _now() if now is None else float(now)
        for name in _CHANNEL_NAMES:
            ch = getattr(self, name, None)
            if ch is None:
                continue
            if ch.finished(t):
                ch.finish(shape)
                setattr(self, name, None)
                if name == "life":
                    _settle_destroy_pending(shape)


def has_active_transient(shape) -> bool:
    st = getattr(shape, "_tx_state", None)
    return st is not None and st.any_active()


def get_transient_state(shape) -> Optional[ShapeTransientState]:
    return getattr(shape, "_tx_state", None)


def _ensure_state(shape) -> ShapeTransientState:
    st = getattr(shape, "_tx_state", None)
    if st is None:
        st = ShapeTransientState()
        shape._tx_state = st
    return st


def register_shape(shape) -> None:
    try:
        _active_shapes.add(shape)
    except TypeError:
        # non-weakrefable (rare); ignore registry, tick via paintless path unavailable
        pass


def unregister_shape(shape) -> None:
    try:
        _active_shapes.discard(shape)
    except Exception:
        pass


# The verb a life channel came from, for the linked-``visible`` refusal.
_LIFE_VERBS = {
    "Dissolve": "dissolve_out", "DissolveIn": "dissolve_in", "FadeOut": "fade_out",
    "FadeIn": "fade_in", "Implode": "implode", "Burn": "burn",
}


def _refuse_linked_visible(shape, channel: TransientChannel) -> None:
    """A verb that hides or shows its shape at the end refuses a linked
    ``visible`` at the call: ``finish`` swallows errors, so a refusal there
    would leave the shape shown with no word (Reactive Design — Appearance
    links)."""
    if not (channel.hide_on_finish or channel.show_on_finish):
        return
    d = getattr(shape, "__dict__", None)
    if not d or not d.get("_field_anchors"):
        return
    linked = getattr(shape, "_channel_linked", None)
    if linked is None or not linked("visible"):
        return
    from .entity import entity_label
    from .state import LinkedAttributeError, driver_conflict_message
    verb = _LIFE_VERBS.get(type(channel).__name__, type(channel).__name__)
    raise LinkedAttributeError(driver_conflict_message(
        new=verb, subject=entity_label(shape), part="visible",
        existing="has an @= formula",
        undo=f"Unlink it first ({shape.name}['visible'].unlink()), or fade it "
             f"another way (a linked alpha / color)",
    ))


def visibility_verb_running(shape) -> Optional[str]:
    """The verb name when the life slot holds an unfinished verb that hides or
    shows the shape at its end (linking ``visible`` then refuses), else None."""
    st = getattr(shape, "_tx_state", None)
    ch = None if st is None else st.life
    if ch is None or ch.done or not (ch.hide_on_finish or ch.show_on_finish):
        return None
    return _LIFE_VERBS.get(type(ch).__name__, type(ch).__name__)


def _install(shape, channel_name: str, channel: TransientChannel) -> TransientChannel:
    _refuse_linked_visible(shape, channel)
    st = _ensure_state(shape)
    outgoing = getattr(st, channel_name, None)
    live = channel
    if outgoing is not None and not outgoing.done:
        if outgoing.refresh(channel):
            live = outgoing
        else:
            # Replace prior in same channel: fire its on_done as cancelled
            outgoing.cancel(shape)
            setattr(st, channel_name, channel)
    else:
        setattr(st, channel_name, channel)
    if not getattr(shape, "is_alive", True):
        # Dead already, or the replaced channel's on_done just destroyed it:
        # a transient on a destroyed shape never runs and must not re-enter
        # the registry (it would hold the actor until the next tick).
        clear_transients(shape, silent=True)
        return live
    if channel_name == "life":
        _settle_destroy_pending(shape)
    register_shape(shape)
    try:
        object.__setattr__(shape, "_plain_blit", False)
    except Exception:
        pass
    return live


def tick_all_transients(now: Optional[float] = None) -> None:
    """Advance / complete all registered shape transients. Call pre-draw."""
    t = _now() if now is None else float(now)
    # Snapshot: WeakSet may shrink during iteration
    for shape in list(_active_shapes):
        # Hard-destroyed: drop channels without callbacks
        if not getattr(shape, "is_alive", True):
            clear_transients(shape, silent=True)
            continue
        st = getattr(shape, "_tx_state", None)
        if st is None:
            unregister_shape(shape)
            continue
        st.tick(shape, t)
        if not st.any_active():
            unregister_shape(shape)
            fn = getattr(shape, "_refresh_plain_blit", None)
            if callable(fn):
                fn()


def clear_transients(shape, *, silent: bool = False) -> None:
    """Cancel all channels. By default fires ``on_done`` as cancelled.

    Pass ``silent=True`` from ``destroy()`` / dead-shape cleanup so callbacks
    are not run (the shape is gone).
    """
    st = getattr(shape, "_tx_state", None)
    if st is None:
        return
    for name in _CHANNEL_NAMES:
        ch = getattr(st, name, None)
        if ch is not None and not silent and not ch.done:
            ch.cancel(shape)
        setattr(st, name, None)
    if not silent:
        _settle_destroy_pending(shape)
    unregister_shape(shape)
    fn = getattr(shape, "_refresh_plain_blit", None)
    if callable(fn):
        fn()


def is_dying(shape) -> bool:
    """True when the life slot holds an unfinished death verb (``hide_on_finish``)."""
    st = getattr(shape, "_tx_state", None)
    if st is None:
        return False
    ch = st.life
    if ch is None or ch.done:
        return False
    return bool(ch.hide_on_finish)


def destroy_when_not_dying(shape) -> None:
    """Destroy ``shape`` now, or when its life slot next stops being a death verb.

    History's leave path calls this instead of ``destroy()``. The mark is the
    added-at time stored on the shape (``_history_added_at``) plus
    ``_destroy_pending``. A later death verb keeps the wait; a spawn verb,
    a natural finish, or ``clear_transients()`` destroys.
    """
    if not getattr(shape, "is_alive", False):
        return
    if is_dying(shape):
        object.__setattr__(shape, "_destroy_pending", True)
        return
    _destroy_marked(shape)


def _settle_destroy_pending(shape) -> None:
    if not getattr(shape, "_destroy_pending", False):
        return
    if not getattr(shape, "is_alive", False):
        return
    if is_dying(shape):
        return
    _destroy_marked(shape)


def _destroy_marked(shape) -> None:
    object.__setattr__(shape, "_destroy_pending", False)
    added = getattr(shape, "_history_added_at", None)
    if added is None:
        note = "destroyed by History when it left"
    else:
        note = f"destroyed by History when it left (added at t={float(added):g})"
    object.__setattr__(shape, "_destroyed_by", note)
    shape.destroy()


def is_registered(shape) -> bool:
    return shape in _active_shapes


def registered_count() -> int:
    return len(_active_shapes)


# ---------------------------------------------------------------------------
# Author triggers
# ---------------------------------------------------------------------------

def dissolve_out(
    shape,
    duration: float = 0.5,
    *,
    style: DissolveStyle = "noise",
    angle: float = 0.0,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
    seed: Optional[float] = None,
) -> TransientChannel:
    """Life (death): dig silhouette then hide. ``style``: noise | vortex | wipe | fade.

    Replaces any other life verb (spawn or death). ``angle`` is degrees
    (wipe axis / vortex bias; 0 = +x).
    """
    ch = Dissolve(
        _clamp_duration(duration, 0.5),
        t0=t0,
        on_done=on_done,
        seed=seed,
        style=style,
        angle=angle,
    )
    _install(shape, "life", ch)
    return ch


def dissolve_in(
    shape,
    duration: float = 0.5,
    *,
    style: DissolveStyle = "noise",
    angle: float = 0.0,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
    seed: Optional[float] = None,
) -> TransientChannel:
    """Life (spawn): materialize from dig (or fade). Forces ``visible=True``.

    Replaces any other life verb (including an in-flight death).
    """
    # Build (and so validate) the channel BEFORE showing the shape: a rejected
    # duration / style must not leave a hidden shape drawn (A10).
    ch = DissolveIn(
        _clamp_duration(duration, 0.5),
        t0=t0,
        on_done=on_done,
        seed=seed,
        style=style,
        angle=angle,
    )
    try:
        shape.visible = True
    except Exception:
        pass
    _install(shape, "life", ch)
    return ch


def fade_out(
    shape,
    duration: float = 0.35,
    *,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    """Life (death): alpha only. Replaces any other life verb."""
    ch = FadeOut(_clamp_duration(duration, 0.35), t0=t0, on_done=on_done)
    _install(shape, "life", ch)
    return ch


def fade_in(
    shape,
    duration: float = 0.35,
    *,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    """Life (spawn): alpha only. Replaces any other life verb."""
    ch = FadeIn(_clamp_duration(duration, 0.35), t0=t0, on_done=on_done)   # validate first (A10)
    try:
        shape.visible = True
    except Exception:
        pass
    _install(shape, "life", ch)
    return ch


def implode(
    shape,
    duration: float = 0.28,
    *,
    scale_end: float = 0.05,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    """Life (death): scale-collapse + fade then hide. Replaces any other life verb."""
    ch = Implode(
        _clamp_duration(duration, 0.28),
        t0=t0,
        on_done=on_done,
        scale_end=scale_end,
    )
    _install(shape, "life", ch)
    return ch


def burn_out(
    shape,
    duration: float = 0.55,
    *,
    intensity: float = 1.0,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
    seed: Optional[float] = None,
    speed: float = 1.2,
) -> TransientChannel:
    """Life (death): hot body + dig then hide (soft-edge burn recipe).

    Replaces any other life verb.
    """
    ch = Burn(
        _clamp_duration(duration, 0.55),
        t0=t0,
        on_done=on_done,
        seed=seed,
        intensity=intensity,
        speed=speed,
    )
    _install(shape, "life", ch)
    return ch


class FlashText(TransientChannel):
    """Temporary display-string override for widgets (does not unlink ``data``)."""

    kind = "text"
    hide_on_finish = False

    def __init__(
        self,
        duration: float,
        text,
        *,
        t0: Optional[float] = None,
        on_done: DoneFn = None,
    ):
        super().__init__(duration, t0=t0, on_done=on_done)
        self.text = str(text)


def flash_text(
    widget,
    text,
    duration: float = 1.0,
    *,
    t0: Optional[float] = None,
    on_done: DoneFn = None,
) -> TransientChannel:
    """Show ``text`` on a widget for ``duration`` seconds, then resume the cell."""
    ch = FlashText(
        _clamp_duration(duration, 1.0),
        text,
        t0=t0,
        on_done=on_done,
    )
    _install(widget, "text", ch)
    return ch


def active_flash_text(widget, now: Optional[float] = None) -> Optional[str]:
    """Override string while a ``flash_text`` channel is in progress, else None."""
    st = getattr(widget, "_tx_state", None)
    if st is None:
        return None
    ch = getattr(st, "text", None)
    if ch is None:
        return None
    t = _now() if now is None else float(now)
    if ch.finished(t):
        return None
    return ch.text


def flash(
    shape,
    duration: float = 0.12,
    *,
    intensity: float = 1.0,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    ch = Flash(
        _clamp_duration(duration, 0.12),
        intensity=intensity,
        t0=t0,
        on_done=on_done,
    )
    _install(shape, "flash", ch)
    return ch


def blink(
    shape,
    duration: float = 0.8,
    *,
    rate: float = 8.0,
    intensity: float = 1.0,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    """Strobe alpha (i-frames / attention). Replaces flash; a second blink refreshes."""
    ch = Blink(
        _clamp_duration(duration, 0.8),
        rate=rate,
        intensity=intensity,
        t0=t0,
        on_done=on_done,
    )
    return _install(shape, "flash", ch)


def pulse_outline(
    shape,
    duration: float = 0.25,
    *,
    color=(1.0, 1.0, 1.0, 1.0),
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    ch = PulseOutline(
        _clamp_duration(duration, 0.25),
        color=color,
        t0=t0,
        on_done=on_done,
    )
    _install(shape, "pulse", ch)
    return ch


def pop(
    shape,
    duration: float = 0.18,
    *,
    scale: float = 1.2,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    ch = Pop(
        _clamp_duration(duration, 0.18),
        scale=scale,
        t0=t0,
        on_done=on_done,
    )
    _install(shape, "pop", ch)
    return ch


def knock(
    shape,
    duration: float = 0.14,
    *,
    distance: Optional[float] = None,
    angle: Optional[float] = None,
    dx: float = 0.0,
    dy: float = 0.0,
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    """Draw-only offset punch (geometry attrs unchanged). Stacks with pop.

    Prefer ``distance`` + ``angle`` (degrees, y-up) or ``dx`` / ``dy`` design units.
    Re-calling knock replaces the previous knock only.
    """
    ch = Knock(
        _clamp_duration(duration, 0.14),
        dx=dx,
        dy=dy,
        distance=distance,
        angle=angle,
        t0=t0,
        on_done=on_done,
    )
    _install(shape, "knock", ch)
    return ch


def spark_burst(
    shape,
    duration: float = 0.35,
    *,
    amount: float = 1.0,
    color=(1.0, 0.92, 0.75, 1.0),
    on_done: DoneFn = None,
    t0: Optional[float] = None,
) -> TransientChannel:
    """Short outward crackle flecks; stacks with flash/pulse/exit."""
    ch = SparkBurst(
        _clamp_duration(duration, 0.35),
        amount=amount,
        color=color,
        t0=t0,
        on_done=on_done,
    )
    _install(shape, "spark", ch)
    return ch


def compose_draw_mods(shape, now: Optional[float] = None) -> Optional[DrawMods]:
    st = getattr(shape, "_tx_state", None)
    if st is None or not st.any_active():
        return None
    return st.compose(now)


# ---------------------------------------------------------------------------
# Geometry helpers + draw envelope
# ---------------------------------------------------------------------------

def _scalar(v, default: float = 0.0) -> float:
    try:
        if hasattr(v, "value"):
            return float(v.value)
        return float(v)
    except Exception:
        return default


def _radius_from_draw_aabb(shape, cx: float, cy: float) -> Optional[float]:
    """Circumradius of ``_approx_draw_aabb`` about ``(cx, cy)``, or None."""
    try:
        from .canvas import _approx_draw_aabb
        box = _approx_draw_aabb(shape)
    except Exception:
        return None
    if box is None:
        return None
    try:
        minx, miny, maxx, maxy = (float(v) for v in box)
    except Exception:
        return None
    hx = max(abs(minx - cx), abs(maxx - cx))
    hy = max(abs(miny - cy), abs(maxy - cy))
    r = math.hypot(hx, hy)
    return r if r > 1e-3 else None


def shape_pivot(shape) -> tuple[float, float, float]:
    """Return ``(cx, cy, approx_radius)`` for CTM / saveLayer / dissolve UV.

    Radius must cover the full drawn footprint (not a 24 DU guess). Prefer a true
    circumradius host (``radius``), else world AABB extent (free Polygon, Text,
    rotated Rect/Square), else oriented ``width``/``height``/``length`` half-diagonal.
    """
    # Line: Defining endpoints only (``center`` / ``p2`` may be cold Derivates;
    # waking them pushes the host's motion off the A1 fast path).
    segment = getattr(shape, "_segment_xy", None)
    if callable(segment):
        try:
            x1, y1, x2, y2 = segment()
            half = 0.5 * math.hypot(x2 - x1, y2 - y1)
            return 0.5 * (x1 + x2), 0.5 * (y1 + y2), max(half, 8.0)
        except Exception:
            pass

    cx = cy = 0.0
    try:
        center_xy = getattr(shape, "_center_xy", None)
        if callable(center_xy):
            cx, cy = (float(v) for v in center_xy())
        else:
            c = getattr(shape, "center", None)
            if c is not None:
                cx = _scalar(getattr(c, "x", 0.0))
                cy = _scalar(getattr(c, "y", 0.0))
    except Exception:
        pass

    # Strokes / missing center: segment midpoint + half-length.
    try:
        from .style import is_stroke_type
        stroke = is_stroke_type(shape)
    except Exception:
        stroke = scena_kind(shape) == "Line"
    if stroke or (abs(cx) < 1e-12 and abs(cy) < 1e-12):
        try:
            p1, p2 = getattr(shape, "p1", None), getattr(shape, "p2", None)
            if p1 is not None and p2 is not None:
                x1, y1 = _scalar(p1.x), _scalar(p1.y)
                x2, y2 = _scalar(p2.x), _scalar(p2.y)
                cx, cy = 0.5 * (x1 + x2), 0.5 * (y1 + y2)
                half = 0.5 * math.hypot(x2 - x1, y2 - y1)
                return cx, cy, max(half, 8.0)
        except Exception:
            pass

    # True radial hosts (Circle, RegularPolygon, …) — do not inflate via AABB √2.
    if hasattr(shape, "radius"):
        try:
            v = abs(_scalar(getattr(shape, "radius"), 0.0))
            if v > 1e-6:
                return cx, cy, v
        except Exception:
            pass

    # World AABB: free Polygon verts, Text layout box, rotated Rect/Square, …
    r_aabb = _radius_from_draw_aabb(shape, cx, cy)
    if r_aabb is not None:
        return cx, cy, max(r_aabb, 8.0)

    # Attribute fallbacks when AABB is unavailable.
    if hasattr(shape, "width") and hasattr(shape, "height"):
        try:
            w = abs(_scalar(getattr(shape, "width"), 0.0))
            h = abs(_scalar(getattr(shape, "height"), 0.0))
            if w > 1e-6 and h > 1e-6:
                # Half-diagonal covers oriented corners (not 0.5*max(w,h)).
                return cx, cy, max(0.5 * math.hypot(w, h), 8.0)
        except Exception:
            pass
    if hasattr(shape, "length"):
        try:
            v = abs(_scalar(getattr(shape, "length"), 0.0))
            if v > 1e-6:
                # Square side → circumradius; Line already returned above.
                return cx, cy, max(0.5 * v * math.sqrt(2.0), 8.0)
        except Exception:
            pass
    return cx, cy, 24.0


def transient_cull_pad(shape) -> float:
    """Extra design-unit pad for AABB culling while transients run."""
    st = getattr(shape, "_tx_state", None)
    if st is None or not st.any_active():
        return 0.0
    pad = 0.0
    mods = st.compose()
    if mods.scale_mul > 1.0 or mods.scale_mul < 0.99:
        _, _, r = shape_pivot(shape)
        pad = max(pad, abs(r * (mods.scale_mul - 1.0)) + 4.0)
    if mods.pulse_width > 0:
        pad = max(pad, mods.pulse_width * 0.5 + 4.0)
    if mods.spark_pad > 0:
        pad = max(pad, mods.spark_pad)
    if abs(mods.offset_x) > 1e-3 or abs(mods.offset_y) > 1e-3:
        pad = max(pad, math.hypot(mods.offset_x, mods.offset_y) + 4.0)
    return pad


_FIRE_FILL = None
_BURN_GLOW_MASK = None


def _shared_fire_fill():
    global _FIRE_FILL
    if _FIRE_FILL is None:
        from .style import FlameFill
        # Drive heat a bit high so transient burn reads brighter than sticky Flame look.
        _FIRE_FILL = FlameFill(amount=1.35, speed=1.35)
    return _FIRE_FILL


def _burn_glow_mask():
    global _BURN_GLOW_MASK
    if _BURN_GLOW_MASK is None:
        _BURN_GLOW_MASK = skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 5.0)
    return _BURN_GLOW_MASK


def _draw_body(shape, skia_canvas, *, strip_filters: bool = False) -> None:
    """Draw look / geometry. Optionally omit fill/line ImageFilters for this pass.

    GlowFilter / Blur expand into a soft light plate. Alpha saveLayer and dig masks
    must not erase or dim that plate — it reads as the backdrop lighting up.
    Filters stay sticky on the shape; we only skip them while rasterizing.
    """
    saved_ff = saved_lf = None
    if strip_filters:
        saved_ff = getattr(shape, "_fill_filter", None)
        saved_lf = getattr(shape, "_line_filter", None)
        if saved_ff is not None:
            shape._fill_filter = None
        if saved_lf is not None:
            shape._line_filter = None
    try:
        from .stamps import draw_body_with_stamps, has_any_stamp
        if has_any_stamp(shape):
            draw_body_with_stamps(shape, skia_canvas)
        else:
            visual = getattr(shape, "visual", None)
            render_sprite = getattr(visual, "_render_sprite_body", None) if visual is not None else None
            if callable(render_sprite) and getattr(type(shape), "_is_sprite_body", False):
                render_sprite(shape, skia_canvas)
            elif visual is not None and getattr(visual, "_is_multipass", False):
                visual._render(shape, skia_canvas)
            else:
                shape._geometry_draw(skia_canvas)
                fn = getattr(visual, "_overlay_after_filters", None) if visual is not None else None
                if callable(fn):
                    fn(shape, skia_canvas)
        # Parts drawn with the body (a SpriteButton label) share the envelope.
        attached = getattr(shape, "_draw_attached", None)
        if attached is not None:
            attached(skia_canvas)
    finally:
        if strip_filters:
            if saved_ff is not None:
                shape._fill_filter = saved_ff
            if saved_lf is not None:
                shape._line_filter = saved_lf


def _should_strip_filters(mods: DrawMods) -> bool:
    """True when fill/line ImageFilters must be omitted for this paint pass.

    GlowFilter / Blur expand into a soft light plate. Putting that plate in a
    partial-alpha saveLayer (fade / dig / blink / implode) composites as a
    translucent rectangle that lights up the backdrop — including black areas.
    Sticky filter assignment is unchanged; we only skip filters while rasterizing.
    Burn replaces the whole body and never hits this path.
    """
    if mods.burn_fire > 1e-6:
        return False
    if mods.dissolve_progress > 1e-6:
        return True
    if abs(mods.alpha_mul - 1.0) > 1e-6:
        return True
    return False


def _shape_has_fill_safe(shape) -> bool:
    try:
        from .recipes import _shape_has_fill
        return bool(_shape_has_fill(shape))
    except Exception:
        return getattr(shape, "_fill", None) is not None


def _shape_has_line_safe(shape) -> bool:
    try:
        from .recipes import _shape_has_line
        return bool(_shape_has_line(shape))
    except Exception:
        return getattr(shape, "_line", None) is not None


def _stroke_paint_hot(color, width: float, *, blend=skia.BlendMode.kPlus, mask=None) -> skia.Paint:
    r, g, b, a = color
    paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=float(width),
        StrokeCap=skia.Paint.Cap.kRound_Cap,
        StrokeJoin=skia.Paint.Join.kRound_Join,
        BlendMode=blend,
        Color4f=skia.Color4f(float(r), float(g), float(b), float(a)),
    )
    if mask is not None:
        paint.setMaskFilter(mask)
    return paint


def _draw_white_flash(shape, skia_canvas, amount: float) -> None:
    if amount <= 1e-4:
        return
    a = max(0.0, min(1.0, amount))
    fill = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kFill_Style,
        BlendMode=skia.BlendMode.kPlus,
        Color4f=skia.Color4f(a, a, a, a),
    )
    stroke = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=max(1.0, float(getattr(shape, "line_width", 2.0) or 2.0)),
        BlendMode=skia.BlendMode.kPlus,
        Color4f=skia.Color4f(a, a, a, a),
    )
    try:
        shape._geometry_draw(skia_canvas, fill_paint=fill, stroke_paint=stroke)
    except Exception:
        try:
            shape._geometry_draw(skia_canvas, fill_paint=fill, stroke_paint=None)
        except Exception:
            pass


def _draw_pulse(shape, skia_canvas, mods: DrawMods) -> None:
    if mods.pulse_alpha <= 1e-4 or mods.pulse_width <= 1e-4:
        return
    col = mods.pulse_color or (1.0, 1.0, 1.0, 1.0)
    a = max(0.0, min(1.0, mods.pulse_alpha))
    r, g, b = col[0], col[1], col[2]
    paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=float(mods.pulse_width),
        StrokeCap=skia.Paint.Cap.kRound_Cap,
        StrokeJoin=skia.Paint.Join.kRound_Join,
        BlendMode=skia.BlendMode.kPlus,
        Color4f=skia.Color4f(r * a, g * a, b * a, a),
    )
    try:
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)
    except Exception:
        pass


def _draw_burn_silhouette(shape, skia_canvas, intensity: float) -> None:
    """Hot fire body with soft alpha falloff at the silhouette (no hard rim).

    Drawn ~25% larger than the base silhouette so the soft feather still covers
    the original shape edge after degradee.
    """
    if intensity <= 1e-4:
        return
    try:
        from .recipes import _procedural_shader
    except Exception:
        return

    inten = max(0.0, min(1.25, float(intensity)))
    cx, cy, r = shape_pivot(shape)
    # Expand visual body so soft edge still wraps the original geometry footprint
    scale = 1.25
    r_draw = r * scale
    fill = _shared_fire_fill()
    # Mild brighter mid-ground heat (keep some dark cells)
    fill._amount = max(1.1, min(1.65, 1.35 * inten))
    fill._speed = max(1.15, float(getattr(fill, "_speed", 1.3) or 1.3))

    has_fill = _shape_has_fill_safe(shape)
    has_line = _shape_has_line_safe(shape)
    draw_fill = has_fill or not has_line

    # Wide pad so alpha degradee is not clipped (includes expanded body)
    pad = max(56.0, r_draw * 0.9)
    bounds = skia.Rect.MakeLTRB(cx - r_draw - pad, cy - r_draw - pad, cx + r_draw + pad, cy + r_draw + pad)

    soft_blur = max(3.0, min(10.0, r_draw * 0.045))
    layer_paint = None
    try:
        layer_paint = skia.Paint(
            ImageFilter=skia.ImageFilters.Blur(soft_blur, soft_blur),
        )
    except Exception:
        layer_paint = None
    skia_canvas.saveLayer(bounds, layer_paint)

    # Grow fire about pivot so soft edge still reads past the original outline
    skia_canvas.save()
    skia_canvas.translate(cx, cy)
    skia_canvas.scale(scale, scale)
    skia_canvas.translate(-cx, -cy)

    if draw_fill:
        under = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kFill_Style,
            Color4f=skia.Color4f(0.72 * inten, 0.24 * inten, 0.04 * inten, min(1.0, 0.94 * inten)),
        )
        body = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kFill_Style,
            BlendMode=skia.BlendMode.kSrcOver,
        )
        try:
            body.setShader(_procedural_shader(fill, cx, cy, r))
        except Exception:
            skia_canvas.restore()
            skia_canvas.restore()
            return
        wash = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kFill_Style,
            BlendMode=skia.BlendMode.kPlus,
            Color4f=skia.Color4f(0.82 * inten, 0.34 * inten, 0.05 * inten, 0.46 * inten),
        )
        hot = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kFill_Style,
            BlendMode=skia.BlendMode.kPlus,
            Alphaf=0.34 * inten,
        )
        try:
            hot.setShader(body.getShader())
            shape._geometry_draw(skia_canvas, fill_paint=under, stroke_paint=None)
            shape._geometry_draw(skia_canvas, fill_paint=body, stroke_paint=None)
            shape._geometry_draw(skia_canvas, fill_paint=wash, stroke_paint=None)
            shape._geometry_draw(skia_canvas, fill_paint=hot, stroke_paint=None)
        except Exception:
            pass
    else:
        base_w = max(float(getattr(shape, "line_width", 2.0) or 2.0), 2.0)
        try:
            body = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=base_w * 2.4,
                StrokeCap=skia.Paint.Cap.kRound_Cap,
                BlendMode=skia.BlendMode.kPlus,
            )
            body.setShader(_procedural_shader(fill, cx, cy, max(r, base_w * 4)))
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=body)
        except Exception:
            pass

    # Soft alpha degradee near borders: multi-sigma white silhouette x DstIn
    try:
        if draw_fill:
            for frac, a_mul in (
                (0.10, 1.0),
                (0.18, 0.92),
                (0.30, 0.72),
            ):
                sigma = max(6.0, min(42.0, r * frac))
                edge = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kFill_Style,
                    BlendMode=skia.BlendMode.kDstIn,
                    Color4f=skia.Color4f(1, 1, 1, a_mul),
                )
                edge.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, sigma))
                try:
                    edge.setImageFilter(skia.ImageFilters.Blur(sigma * 0.35, sigma * 0.35))
                except Exception:
                    pass
                shape._geometry_draw(skia_canvas, fill_paint=edge, stroke_paint=None)
        else:
            base_w = max(float(getattr(shape, "line_width", 2.0) or 2.0), 2.0)
            for sw_mul, sig_mul in ((3.2, 0.55), (4.8, 0.9)):
                sw = base_w * sw_mul
                sm = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=sw,
                    StrokeCap=skia.Paint.Cap.kRound_Cap,
                    BlendMode=skia.BlendMode.kDstIn,
                    Color4f=skia.Color4f(1, 1, 1, 1),
                )
                sm.setMaskFilter(
                    skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, max(4.0, sw * sig_mul))
                )
                shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=sm)
    except Exception:
        pass

    skia_canvas.restore()  # scale
    skia_canvas.restore()  # soft layer


def _apply_dissolve_mask(
    skia_canvas,
    bounds: skia.Rect,
    progress: float,
    seed: float,
    cx: float,
    cy: float,
    half: float,
    *,
    style: str = "noise",
    angle: float = 0.0,
) -> None:
    if progress <= 1e-4:
        return
    try:
        from ._sksl_shape import dissolve_mask_shader
        sh = dissolve_mask_shader(
            progress, seed, cx, cy, half, style=style, angle=angle,
        )
    except Exception:
        # Fallback: uniform erase via alpha (still DstIn)
        a = max(0.0, 1.0 - progress)
        paint = skia.Paint(
            BlendMode=skia.BlendMode.kDstIn,
            Color4f=skia.Color4f(1, 1, 1, a),
        )
        skia_canvas.drawRect(bounds, paint)
        return
    paint = skia.Paint(BlendMode=skia.BlendMode.kDstIn, AntiAlias=True)
    paint.setShader(sh)
    skia_canvas.drawRect(bounds, paint)


def _transient_layer_bounds(
    shape, cx: float, cy: float, half: float, mods: DrawMods,
) -> skia.Rect:
    """World-space saveLayer / dig-mask rect covering the full silhouette.

    Prefer the draw AABB (padded, scale/offset aware) so free Polygon / Text /
    rotated Square are not clipped to a 24 DU guess. Fall back to a square from
    ``half`` when AABB is unknown.
    """
    scale = max(0.05, float(mods.scale_mul))
    ox, oy = float(mods.offset_x), float(mods.offset_y)
    pad = 12.0 + max(mods.pulse_width, 0.0) + mods.spark_pad
    if abs(ox) > 1e-3 or abs(oy) > 1e-3:
        pad += math.hypot(ox, oy)
    if mods.burn_fire > 1e-4:
        try:
            tw = max(float(getattr(shape, "line_width", 2.0) or 2.0), 2.0)
        except Exception:
            tw = 2.0
        pad += max(half * 0.7, 36.0) + tw * 5.5 + 32.0

    box = None
    try:
        from .canvas import _approx_draw_aabb
        box = _approx_draw_aabb(shape)
    except Exception:
        box = None
    if box is not None:
        try:
            minx, miny, maxx, maxy = (float(v) for v in box)
            # Scale about pivot expands distance from (cx, cy).
            if abs(scale - 1.0) > 1e-4:
                corners = (
                    (minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy),
                )
                xs = [cx + (x - cx) * scale for x, _y in corners]
                ys = [cy + (y - cy) * scale for _x, y in corners]
                minx, maxx = min(xs), max(xs)
                miny, maxy = min(ys), max(ys)
            return skia.Rect.MakeLTRB(
                minx - pad + min(0.0, ox),
                miny - pad + min(0.0, oy),
                maxx + pad + max(0.0, ox),
                maxy + pad + max(0.0, oy),
            )
        except Exception:
            pass

    layer_half = half * max(scale, 1.0) + pad
    return skia.Rect.MakeLTRB(
        cx - layer_half + min(0.0, ox),
        cy - layer_half + min(0.0, oy),
        cx + layer_half + max(0.0, ox),
        cy + layer_half + max(0.0, oy),
    )


def draw_with_transients(shape, skia_canvas, mods: DrawMods) -> None:
    """Envelope around look / geometry. Never mutates style or finishes channels."""
    cx, cy, half = shape_pivot(shape)
    scale = max(0.05, float(mods.scale_mul))
    ox, oy = float(mods.offset_x), float(mods.offset_y)
    bounds = _transient_layer_bounds(shape, cx, cy, half, mods)

    skia_canvas.save()
    use_layer = mods.needs_save_layer() or mods.burn_fire > 1e-4
    if use_layer:
        layer_paint = skia.Paint(Alphaf=max(0.0, min(1.0, mods.alpha_mul)))
        skia_canvas.saveLayer(bounds, layer_paint)

    # Knock + pop scale: draw-only CTM (geometry Attributes unchanged).
    if abs(ox) > 1e-6 or abs(oy) > 1e-6:
        skia_canvas.translate(ox, oy)
    if abs(scale - 1.0) > 1e-4:
        skia_canvas.translate(cx, cy)
        skia_canvas.scale(scale, scale)
        skia_canvas.translate(-cx, -cy)

    if mods.burn_fire > 1e-4:
        # Full hot replacement — no sticky border / GlowFilter / look body.
        _draw_burn_silhouette(shape, skia_canvas, mods.burn_fire)
    else:
        # Dig/fade strip ImageFilters so glow plates don't tint the backdrop.
        strip = _should_strip_filters(mods)
        _draw_body(shape, skia_canvas, strip_filters=strip)

    if mods.flash_amount > 1e-4:
        _draw_white_flash(shape, skia_canvas, mods.flash_amount)

    if mods.pulse_alpha > 1e-4:
        _draw_pulse(shape, skia_canvas, mods)

    # Channel overlays (spark_burst, etc.) — after body, before dissolve mask
    st = getattr(shape, "_tx_state", None)
    if st is not None:
        tnow = _now()
        for _, ch in st.channels():
            try:
                ch.overlay_after_body(shape, skia_canvas, tnow)
            except Exception:
                pass

    if mods.dissolve_progress > 1e-4:
        # Mask in the same CTM as the body (offsets/scale already applied).
        # Square about pivot; ``half`` is the full-footprint circumradius.
        dig_half = half + 12.0 + max(mods.pulse_width, 0.0) + mods.spark_pad
        d_bounds = skia.Rect.MakeLTRB(
            cx - dig_half, cy - dig_half, cx + dig_half, cy + dig_half,
        )
        _apply_dissolve_mask(
            skia_canvas, d_bounds, mods.dissolve_progress, mods.dissolve_seed,
            cx, cy, half,
            style=mods.dissolve_style,
            angle=mods.dissolve_angle,
        )

    if use_layer:
        skia_canvas.restore()
    skia_canvas.restore()
