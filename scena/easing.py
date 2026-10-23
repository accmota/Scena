"""Easing catalog, ``remap``, ``lerp``, ``chase``, ``approach``, and ``deadzone``.

Author tween/pose ``ease=`` is a ``Literal`` name or a callable ``[0,1] → float``.
``spring`` / ``wobble`` settle at 0.5 — they stay on ``MappingFunctions`` for
``remap`` extras, not in the tween catalog.

``lerp`` is the shared on-demand interpolator (scalars, flat tuples/lists,
``Vec2``, ``Color``, pose ``Point`` → ``(x, y)``). ``tween`` uses it for
Attribute / FieldRef targets. ``chase`` / ``approach`` / ``deadzone`` are
stateless math helpers in the same family as ``Graphic.confine`` — call them
yourself; they do not register, do not run later in the frame, and are not
camera-only. Omitted ``chase(..., dt)`` / ``approach(..., dt)`` use this
frame's world ``clock.dt``.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Literal, Optional, Tuple, Union

Number = Union[int, float]
MappingFunction = Callable[[float], float]

EaseName = Literal[
    "linear",
    "ease_in",
    "ease_out",
    "ease_in_out",
    "quad",
    "inv_quad",
    "smoothstep",
    "sigmoid",
    "bounce",
    "elastic",
    "steps",
    "xpsin",
    "erratic",
]
Ease = Union[EaseName, MappingFunction]

TWEEN_EASES: Tuple[str, ...] = (
    "linear",
    "ease_in",
    "ease_out",
    "ease_in_out",
    "quad",
    "inv_quad",
    "smoothstep",
    "sigmoid",
    "bounce",
    "elastic",
    "steps",
    "xpsin",
    "erratic",
)


class MappingFunctions:
    """Collection of mapping functions that operate on [0,1] range."""

    @staticmethod
    def sigmoid(x: float) -> float:
        """Logistic S-curve: sigmoid function (endpoint-exact at 0 and 1)."""
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        return 1 / (1 + math.exp(-10 * (x - 0.5)))  # Scaled to fit [0,1]

    @staticmethod
    def smoothstep(x: float) -> float:
        """Smoothstep function (5th degree polynomial)"""
        return x * x * x * (x * (x * 6 - 15) + 10)

    @staticmethod
    def quad(x: float) -> float:
        """Quadratic function (half parabola going down)"""
        return x * x

    @staticmethod
    def inv_quad(x: float) -> float:
        """Inverted quadratic function (half parabola going up)"""
        return 1 - (1 - x) * (1 - x)

    @staticmethod
    def ease_in(x: float) -> float:
        """Cubic ease in"""
        return x * x * x

    @staticmethod
    def ease_out(x: float) -> float:
        """Cubic ease out"""
        return 1 - (1 - x) * (1 - x) * (1 - x)

    @staticmethod
    def ease_in_out(x: float) -> float:
        """Cubic ease-in-out."""
        x = float(x)
        if x < 0.5:
            return 4.0 * x * x * x
        return 1.0 - pow(-2.0 * x + 2.0, 3) / 2.0

    @staticmethod
    def linear(x: float) -> float:
        """Linear function (identity)"""
        return x

    @staticmethod
    def xpsin(x: float) -> float:
        """Sine function"""
        sinpos = math.sin(x * 14 * math.pi) / 25
        result = x + sinpos
        return max(0.0, min(1.0, result))

    @staticmethod
    def erratic(x: float) -> float:
        """Erratic function that bounces between 0 and 1 using multiple sine waves"""
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        wave1 = math.sin(x * 12.3 * math.pi) * 0.05  # Fast small wave
        wave2 = math.sin(x * 7.1 * math.pi) * 0.08   # Medium wave
        wave3 = math.sin(x * 3.2 * math.pi) * 0.03    # Slower wave
        result = x + wave1 + wave2 + wave3
        return max(0.0, min(1.0, result))

    @staticmethod
    def steps(x: float) -> float:
        """Creates a stair-step effect with 20 steps"""
        return min(1.0, math.floor(x * 21) / 20)

    @staticmethod
    def elastic(x: float) -> float:
        """Elastic ease-out: overshoots past 1 then settles back (starts at 0)."""
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        # Standard Penner ease-out-elastic (period 0.3 of the unit range).
        return pow(2, -10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi / 3)) + 1

    @staticmethod
    def bounce(x: float) -> float:
        """Bouncing effect that becomes progressively smaller"""
        if x < 0.36363636:
            return 7.5625 * x * x
        elif x < 0.72727272:
            x2 = x - 0.54545454
            return 7.5625 * x2 * x2 + 0.75
        elif x < 0.90909090:
            x2 = x - 0.81818181
            return 7.5625 * x2 * x2 + 0.9375
        else:
            x2 = x - 0.95454545
            return 7.5625 * x2 * x2 + 0.984375

    # Note: spring start and end are at 0.5 *****
    @staticmethod
    def spring(x: float) -> float:
        """Spring-like oscillation that starts and settles at 0.5, reaching full range at peak"""
        if x == 0.0 or x == 1.0:
            return 0.5  # Always return to center

        offset = x - 0.5  # Convert to [-0.5, 0.5] range
        x = abs(offset) * 2.5  # Increase frequency based on distance from center

        decay = math.exp(-x * 1.5)  # Slower decay to allow reaching extremes
        oscillation = math.sin(x * 25) * decay * 0.5  # Increased amplitude to reach extremes

        return max(0.0, min(1.0, 0.5 + (oscillation * (1.0 if offset >= 0 else -1.0))))

    # Note: wobble start and end are at 0.5 *****
    @staticmethod
    def wobble(x: float) -> float:
        """Wobbly effect that oscillates with varying frequencies"""
        if x == 0.0 or x == 1.0:
            return 0.5

        offset = x - 0.5
        x = abs(offset) * 3.14159

        wobble = math.sin(x * 10) * math.cos(x * 5) * 0.5
        decay = math.exp(-x * 1.5)

        return max(0.0, min(1.0, 0.5 + (wobble * decay * (1.0 if offset >= 0 else -1.0))))


def _mapping_names() -> Tuple[str, ...]:
    names = []
    for name in dir(MappingFunctions):
        if name.startswith("_"):
            continue
        attr = getattr(MappingFunctions, name)
        if isinstance(attr, staticmethod) or callable(attr):
            names.append(name)
    return tuple(names)


def remap(
    value: Number,
    in_min: Number = 0.0,
    in_max: Number = 1.0,
    out_min: Number = 0.0,
    out_max: Number = 1.0,
    modifier: Optional[Union[str, MappingFunction]] = None,
) -> Number:
    """Map a value from an input range to an output range with optional modifier.

    ``modifier`` is a built-in name (see ``MappingFunctions``) or a callable
    that maps ``[0,1] → [0,1]``.

    Args:
        value: The input number.
        in_min: Input range start (default 0).
        in_max: Input range end (default 1). ``in_min == in_max`` returns ``out_min``.
        out_min: Output range start (default 0).
        out_max: Output range end (default 1).
        modifier: Curve applied between normalizing and scaling: an ease name
            (``"ease_in"``, …, plus ``"spring"`` / ``"wobble"``) or a function
            ``[0, 1] → [0, 1]``.
    """
    from .validate import number
    value = number(value, "remap value")
    in_min = number(in_min, "remap in_min")
    in_max = number(in_max, "remap in_max")
    out_min = number(out_min, "remap out_min")
    out_max = number(out_max, "remap out_max")
    span = in_max - in_min
    if span == 0:
        normalized = 0.0
    else:
        normalized = (value - in_min) / span

    if modifier is not None:
        if isinstance(modifier, str):
            if not hasattr(MappingFunctions, modifier):
                listed = ", ".join(repr(n) for n in _mapping_names())
                raise ValueError(
                    f"Unknown mapping function: {modifier!r}; expected one of {listed}"
                )
            modifier_func = getattr(MappingFunctions, modifier)
        else:
            if not callable(modifier):
                raise TypeError(
                    f"remap modifier expected a function name or callable, "
                    f"got {type(modifier).__name__}"
                )
            modifier_func = modifier
        normalized = modifier_func(normalized)

    return out_min + normalized * (out_max - out_min)


def _is_number(value: Any) -> bool:
    """True for int/float, excluding bool (a subclass of int)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pose_xy(value: Any) -> Optional[Tuple[float, float]]:
    """``(x, y)`` from a pose-like object, or None if not pose-shaped."""
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "_takein"):
        return float(value.x), float(value.y)
    return None


def _xy_destination(value: Any) -> Tuple[float, float]:
    """Destination for a pose lerp: Point/Vec2-like, or ``(x, y)`` sequence."""
    xy = _pose_xy(value)
    if xy is not None:
        return xy
    from .shapes import _read_xy
    xy = _read_xy(value, False, False, True)
    if xy is not None:
        return xy
    raise TypeError(
        f"lerp pose destination expected (x, y), Point, or Vec2, "
        f"got {type(value).__name__}"
    )


def _rebuild_sequence(template: Any, parts: list) -> Any:
    """Rebuild tuple/list (and namedtuple) from interpolated parts."""
    if hasattr(template, "_fields"):
        return type(template)(*parts)
    return type(template)(parts)


def lerp(a: Any, b: Any, t: Number) -> Any:
    """Interpolate between two same-shaped values.

    Supports numbers, flat tuples/lists of lerp-able elements, types with
    ``.lerp(other, t)`` (``Vec2``, ``Color``), and pose Containers / ``Point``
    (returns a plain ``(x, y)`` tuple — never allocates a new Point).

    ``t`` is **not** clamped: elastic / back eases may overshoot ``[0, 1]``.
    Incompatible shapes raise immediately (``TypeError`` / ``ValueError``).
    Nested sequences recurse, but only depth-1 tuples/lists are a documented
    contract — deeper nesting is incidental.

    Args:
        a: Start value (number, tuple / list of numbers, ``Vec2``, ``Color``, or a
            Point).
        b: End value, same kind as ``a``.
        t: Blend factor (0 = ``a``, 1 = ``b``; not clamped).
    """
    from .state import as_payload

    a = as_payload(a)
    b = as_payload(b)
    t = float(as_payload(t))

    if _is_number(a):
        if not _is_number(b):
            raise TypeError(
                f"lerp: number vs {type(b).__name__} — both sides must match"
            )
        return a + (b - a) * t

    lerp_method = getattr(a, "lerp", None)
    if callable(lerp_method):
        return lerp_method(b, t)

    pose_a = _pose_xy(a)
    if pose_a is not None:
        x0, y0 = pose_a
        x1, y1 = _xy_destination(b)
        return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)

    if isinstance(a, (tuple, list)):
        if not isinstance(b, (tuple, list)) and len(a) == 2:
            # A point written as a tuple on one side and a Vec2 / Point on
            # the other: both are points (it said "sequences of the same
            # length" for two 2D points; showcase B3).
            pose_b = _pose_xy(b)
            if pose_b is not None:
                b = pose_b
            else:
                try:
                    b = _xy_destination(b)
                except (TypeError, ValueError, AttributeError):
                    pass
        if not isinstance(b, (tuple, list)):
            raise TypeError(
                f"lerp: {type(a).__name__} vs {type(b).__name__} — "
                "both sides must be sequences of the same length"
            )
        if len(a) != len(b):
            raise ValueError(
                f"lerp: length mismatch {len(a)} vs {len(b)}"
            )
        return _rebuild_sequence(a, [lerp(x, y, t) for x, y in zip(a, b)])

    raise TypeError(
        f"lerp() doesn't know how to interpolate {type(a).__name__}"
    )


def _world_dt() -> float:
    """This frame's world step (``clock.dt``), or ``0.0`` if no clock yet."""
    try:
        import builtins
        clk = getattr(builtins, "clock", None)
        if clk is None:
            return 0.0
        return float(clk.dt)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def chase(current, target, rate: float, dt: Optional[float] = None):
    """Ease ``current`` toward ``target``; frame-rate independent (exponential decay).

    Shape-polymorphic like ``lerp``, which it wraps: numbers, tuples, ``Vec2``,
    ``Color``, and Point/pose containers are all accepted for ``current`` /
    ``target``. Point-like operands return a plain (x, y) tuple, never a new
    Point (same rule ``lerp`` already documents).

    ``rate`` is a 1/time constant — larger closes the gap faster. ``rate * dt``
    near 0 barely moves; ``rate * dt >> 1`` snaps almost immediately.
    Omitted ``dt`` uses this frame's world ``clock.dt``. Pass ``dt=`` for an
    entity ``time_scale`` step or a made-up increment. ``rate < 0`` raises
    (a rate is a magnitude). ``rate == 0`` or ``dt == 0`` returns ``current``.
    ``dt < 0`` raises — a paused clock is ``0``, never negative.
    """
    from .validate import number, magnitude, fixed_magnitude
    if dt is None:
        dt = _world_dt()
    rate_f = fixed_magnitude(rate, "chase rate")
    dt_f = number(dt, "chase dt")
    if dt_f < 0.0:
        raise ValueError(f"chase dt must be >= 0, got {dt_f}")
    if dt_f == 0.0 or rate_f == 0.0:
        return current
    return lerp(current, target, 1.0 - math.exp(-rate_f * dt_f))


def approach(current, target, speed: float, dt: Optional[float] = None):
    """Step ``current`` toward ``target`` at a constant ``speed``; land on it exactly.

    The sibling of ``chase``: ``chase`` brakes near the target and never quite
    lands; ``approach`` moves ``speed * dt`` per call and, once the target is
    that close, returns the target itself (never overshoots, never jitters).
    Called every frame with a live target, it pursues at a fixed speed.

    Numbers step along the line. Points (Point, ``Vec2``, ``(x, y)``, mouse, a
    cell, an object with ``.center``) step in a **straight line** — one call
    for the whole point, never one per axis (a per-axis step runs the diagonal
    √2 faster and lands one axis first). A number returns a ``float``; a
    ``Vec2`` returns a ``Vec2``; any other point returns a plain ``(x, y)``.

    ``speed`` is in units per second. Omitted ``dt`` uses this frame's world
    ``clock.dt``; pass ``dt=`` for an entity ``time_scale`` step. ``speed < 0``
    raises (a speed is a magnitude). ``speed == 0`` or ``dt == 0`` returns
    ``current``. ``dt < 0`` raises. A ``Color`` raises (a colour has no
    distance unit — ease it with ``chase`` or a tween). Angles do not wrap:
    350 → 10 goes the long way round.
    """
    from .validate import number, fixed_magnitude
    from .state import as_payload
    if dt is None:
        dt = _world_dt()
    speed_f = fixed_magnitude(speed, "approach speed")
    dt_f = number(dt, "approach dt")
    if dt_f < 0.0:
        raise ValueError(f"approach dt must be >= 0, got {dt_f}")
    if dt_f == 0.0 or speed_f == 0.0:
        return current
    step = speed_f * dt_f

    a = as_payload(current)
    b = as_payload(target)
    if _is_number(a) or _is_number(b):
        if not (_is_number(a) and _is_number(b)):
            raise TypeError(
                f"approach: {type(a).__name__} vs {type(b).__name__} — both "
                "sides must match (two numbers, or two points)"
            )
        a_f = number(a, "approach current")
        b_f = number(b, "approach target")
        gap = b_f - a_f
        if abs(gap) <= step:
            return b_f
        return a_f + math.copysign(step, gap)

    from .color import Color
    if isinstance(a, Color) or isinstance(b, Color):
        raise TypeError(
            "approach does not move a Color (a colour has no distance unit); "
            "ease it with chase(color, target, rate) or a tween"
        )
    from .scenamath import Vec2, _as_xy
    cx, cy = _as_xy(a)
    tx, ty = _as_xy(b)
    dx, dy = tx - cx, ty - cy
    dist = math.hypot(dx, dy)
    if dist <= step:
        nx, ny = tx, ty
    else:
        k = step / dist
        nx, ny = cx + dx * k, cy + dy * k
    if isinstance(a, Vec2):
        return Vec2.temp(nx, ny)
    return (nx, ny)


def deadzone(current, target, size):
    """Nudge ``target`` only enough to keep it within ``size`` of ``current``.

    ``current`` / ``target`` accept a Point, Vec2, or (x, y) tuple (coerced via
    shared ``_as_xy`` in ``scenamath.py``). ``size`` is a number (square box) or
    ``(width, height)`` — gradual: ``size=160`` ≡ ``size=(160, 160)``. Pass
    ``float('inf')`` on an axis to lock it: the returned value on that axis is
    always ``current``'s, so a downstream ``chase`` never moves that axis.
    Returns a plain (x, y) tuple.

    If ``target`` is already inside the box, this returns ``current`` unchanged
    (zero excess on both axes).
    """
    from .scenamath import _as_xy
    from .state import as_payload

    cx, cy = _as_xy(current)
    tx, ty = _as_xy(target)
    # A cell (st.folga) counts as its value, like every other number argument
    # (bug PM12: deadzone was the one helper that refused it).
    size = as_payload(size)
    if isinstance(size, (tuple, list)):
        size = tuple(as_payload(v) for v in size)
    if isinstance(size, (int, float)) and not isinstance(size, bool):
        w = h = float(size)
    else:
        try:
            w, h = float(size[0]), float(size[1])
        except (TypeError, ValueError, IndexError):
            raise TypeError(
                f"deadzone size expected a number or (width, height), "
                f"got {type(size).__name__}"
            ) from None
    if math.isnan(w) or math.isnan(h):
        raise ValueError("deadzone size must be finite or inf, not nan")
    if w < 0.0 or h < 0.0:
        raise ValueError(
            f"deadzone size must be >= 0 (or inf to lock an axis), got {size!r}"
        )
    hw, hh = w * 0.5, h * 0.5
    ox, oy = tx - cx, ty - cy
    cox = max(-hw, min(hw, ox))
    coy = max(-hh, min(hh, oy))
    return (cx + (ox - cox), cy + (oy - coy))


def resolve_ease(ease: Ease, *, what: str = "ease") -> MappingFunction:
    """Return a callable for a tween ``ease=`` name or author function."""
    from .state import as_payload

    ease = as_payload(ease)
    if callable(ease) and not isinstance(ease, str):
        return ease
    if not isinstance(ease, str):
        raise TypeError(
            f"{what} expected one of {', '.join(repr(n) for n in TWEEN_EASES)} "
            f"or a callable, got {type(ease).__name__}"
        )
    key = ease.strip()
    if key in TWEEN_EASES and hasattr(MappingFunctions, key):
        return getattr(MappingFunctions, key)
    from .validate import did_you_mean
    listed = ", ".join(repr(n) for n in TWEEN_EASES)
    raise ValueError(
        f"{what}={ease!r}; expected one of {listed}.{did_you_mean(key, TWEEN_EASES)}"
    )
