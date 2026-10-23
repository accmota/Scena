"""Bounded owned sequence (``History``) and fading polyline recipe (``Contrail``).

``History`` is a plain sequence — not a reactive Container. ``add`` keeps an
object and destroys it on leave; ``snapshot`` keeps a detached position.
``Contrail`` is a ``History`` subclass that keeps one private stroke Shape in
sync with those positions. Duration eviction ticks pre-draw with shape transients.
"""
from __future__ import annotations

import weakref
from typing import Any, Callable, List, Optional, Sequence, Tuple

import skia

from .curves import _phantom_open, catmull_rom_to_bezier
from .easing import Ease, resolve_ease
from .entity import _USE_LAYER_DEFAULT, Entity, _destroyed_access_message
from .shapes import Point, Shape, _STYLE_PAINT, _xy_of
from .state import Container, DestroyedError, as_payload, ephemeral_creation
from .validate import expect_bool, expect_callable
from .closed import ClosedSurface

# Duration-bound histories only (count-only / unbounded stay off this set).
_active_histories: set = set()

# Fade paints at most this many constant-alpha subpaths (index ramp quantized).
_FADE_BANDS = 16


def _parse_contrail_smooth(value) -> float:
    """Same coercion as Track._parse_smooth — False→0, True/None→1."""
    if value is False:
        return 0.0
    if value is True or value is None:
        return 1.0
    from .validate import number
    return number(value, "smooth")


def _destroyed_source(thing: Any):
    """Dead Entity in ``thing`` or its owner chain, or the host that owned a detached part.

    ``destroy()`` clears ``owner`` before the next ``snapshot``, so parts are
    stamped ``_destroyed_with_host`` in ``Container._clean_up``.
    """
    seen = set()
    cur = thing
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, Entity) and not cur.is_alive:
            return cur
        try:
            host = object.__getattribute__(cur, "_destroyed_with_host")
        except AttributeError:
            host = None
        if isinstance(host, Entity) and not host.is_alive:
            return host
        nxt = getattr(cur, "owner", None)
        cur = nxt if nxt is not cur else None
    return None


def _reject_destroyed_source(thing: Any, verb: str) -> None:
    """Raise when ``thing`` is a destroyed Entity or a part of one."""
    dead = _destroyed_source(thing)
    if dead is None:
        return
    label = dead.name
    if verb == "snapshot":
        base = (
            f"snapshot({label}): {label} is destroyed. "
            "Something is still sampling it, usually a module-level every(). "
            f"Start the timer as `{label}.every(...)` so it stops when {label} "
            "is destroyed, or cancel its handle."
        )
    else:
        base = f"{verb}({label}): {label} is destroyed — nothing left to keep."
    raise DestroyedError(_destroyed_access_message(dead, base))


def _now() -> float:
    """World clock seconds (respects pause / time_scale)."""
    import builtins
    clk = getattr(builtins, "clock", None)
    if clk is not None:
        try:
            return float(clk.time)
        except Exception:
            pass
    import time
    return float(time.perf_counter())


def _register_history(history: "History") -> None:
    ref = weakref.ref(history, _active_histories.discard)
    history._tick_ref = ref
    _active_histories.add(ref)


def _unregister_history(history: "History") -> None:
    ref = getattr(history, "_tick_ref", None)
    if ref is not None:
        _active_histories.discard(ref)
        history._tick_ref = None


def tick_all_histories(now: Optional[float] = None) -> None:
    """Age-evict duration-bound histories. Call pre-draw (with transients)."""
    if not _active_histories:
        return
    t = _now() if now is None else float(now)
    dead: List = []
    for ref in tuple(_active_histories):
        h = ref() if isinstance(ref, weakref.ref) else None
        if h is None:
            dead.append(ref)
            continue
        h._evict_over_bounds(now=t)
    for ref in dead:
        _active_histories.discard(ref)


def registered_history_count() -> int:
    return sum(1 for ref in _active_histories if ref() is not None)


def _method_overrides(cls: type, name: str, base: type) -> bool:
    """True when ``cls`` (or an intermediate) defines ``name`` differently from ``base``."""
    own = getattr(cls, name, None)
    base_fn = getattr(base, name, None)
    return own is not None and own is not base_fn


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class History(ClosedSurface):
    """Bounded, expiring sequence. Does not draw.

    ``add`` keeps an object and destroys it when it leaves. ``snapshot`` keeps
    a detached position instead. Oldest at index ``0``, newest at ``-1``.
    ``max_points=`` and ``duration=`` are independent and live-writable;
    lowering a bound evicts immediately.

    Args:
        max_points: Keep at most this many entries.
        duration: Keep entries younger than this many seconds.
        on_leave: ``fn(item)`` called when an entry falls out.
        destroy_on_leave: Destroy actors that fall out (default ``True``).
    """

    def __init__(
        self,
        *,
        max_points: Optional[int] = None,
        duration: Optional[float] = None,
        on_leave: Optional[Callable] = None,
        destroy_on_leave: bool = True,
    ):
        if on_leave is not None and _method_overrides(type(self), "on_leave", History):
            raise TypeError(
                f"{type(self).__name__} already defines on_leave; "
                "do not pass on_leave= to the constructor"
            )
        if on_leave is not None:
            expect_callable(on_leave, what="on_leave")
        if not isinstance(destroy_on_leave, bool):
            raise TypeError(
                f"destroy_on_leave expected bool, got {type(destroy_on_leave).__name__}"
            )

        self._items: List[Tuple[Any, float]] = []  # (value, added_at)
        self._on_leave_cb = on_leave
        self._destroy_on_leave = destroy_on_leave
        self._tick_ref = None
        # Contrail.destroy() sets this. Plain History has no destroy().
        self._destroyed = False
        self._max_points: Optional[int] = None
        self._duration: Optional[float] = None
        # Assign via properties so registration / eviction run.
        if max_points is not None:
            self.max_points = max_points
        if duration is not None:
            self.duration = duration

    # -- bounds --------------------------------------------------------------

    @property
    def max_points(self) -> Optional[int]:
        """Keep at most this many entries (oldest drop first), or ``None`` for no limit."""
        return self._max_points

    @max_points.setter
    def max_points(self, value: Optional[int]) -> None:
        self._check_alive("max_points")
        if value is None:
            self._max_points = None
        else:
            from .validate import count
            n = count(value, "max_points", 0)
            self._max_points = n
        self._evict_over_bounds()

    @property
    def duration(self) -> Optional[float]:
        """Keep entries younger than this many world seconds, or ``None`` for no age limit."""
        return self._duration

    @duration.setter
    def duration(self, value: Optional[float]) -> None:
        self._check_alive("duration")
        if value is None:
            was = self._duration
            self._duration = None
            if was is not None:
                _unregister_history(self)
        else:
            from .validate import seconds
            t = float(seconds(value, "duration"))   # A4: no float() leak
            if t < 0:
                raise ValueError(f"duration must be >= 0, got {t}")
            self._duration = t
            _register_history(self)
        self._evict_over_bounds()

    @property
    def destroy_on_leave(self) -> bool:
        """When True (default), an owned Entity is destroyed after ``on_leave``."""
        return self._destroy_on_leave

    # -- add / snapshot / remove ---------------------------------------------

    def add(self, thing: Any) -> Any:
        """Keep ``thing``. Returns it. Owned Entities are destroyed on leave."""
        self._check_alive("add")
        self._guard_add(thing)
        self._append(thing)
        return thing

    def snapshot(self, *args: Any) -> Point:
        """Keep a position: point-like value, or ``(x, y)``.

        Always a fresh detached ``Point`` — out of the registry and the reactive graph.
        A destroyed Entity (or a part of one) raises ``DestroyedError``.
        """
        self._check_alive("snapshot")
        if len(args) == 2:
            value = Point.temp(*args)
        elif len(args) == 1:
            _reject_destroyed_source(args[0], "snapshot")
            with ephemeral_creation():
                value = Point(args[0])
        else:
            raise TypeError(
                f"snapshot() takes a point or (x, y), got {len(args)} arguments"
            )
        self._append(value)
        return value

    def pop(self, index: int = -1) -> Any:
        """Take an item out alive. No ``on_leave``, no destroy."""
        self._check_alive("pop")
        index = as_payload(index)
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError(f"History.pop() index must be a whole number, got {type(index).__name__}")
        n = len(self._items)
        if not self._items:
            raise IndexError("pop from empty History")
        if not -n <= index < n:
            raise IndexError(f"History.pop({index}): only {n} item(s)")
        value, _t = self._items.pop(index)
        self._note_removed()
        return value

    def discard(self, value: Any) -> bool:
        """Remove ``value`` by identity. Full leave when removed."""
        self._check_alive("discard")
        for i, (v, added_at) in enumerate(self._items):
            if v is value:
                del self._items[i]
                self._leave(value, added_at)
                return True
        return False

    def clear(self) -> None:
        """Everything leaves, oldest first."""
        self._check_alive("clear")
        self._clear_items(silent=False)

    def _clear_items(self, *, silent: bool) -> None:
        if silent:
            self._items.clear()
            self._note_removed()
            return
        while self._items:
            value, added_at = self._items.pop(0)
            self._leave(value, added_at)

    def _append(self, value: Any) -> None:
        self._items.append((value, _now()))
        self._note_stored()
        self._evict_over_bounds()

    def _note_stored(self) -> None:
        """Private hook after an item is stored (Contrail marks its stroke)."""

    def _note_removed(self) -> None:
        """Private hook after storage shrinks without a full leave, or on silent clear."""

    def _leave(self, value: Any, added_at: float) -> None:
        """Full leave: ``on_leave`` while alive, then destroy if owned."""
        self._note_removed()
        try:
            self._invoke_on_leave(value)
        finally:
            self._destroy_owned(value, added_at)

    def _invoke_on_leave(self, value: Any) -> None:
        if _method_overrides(type(self), "on_leave", History):
            type(self).on_leave(self, value)
            return
        cb = self._on_leave_cb
        if cb is not None:
            cb(value)

    def _destroy_owned(self, value: Any, added_at: float) -> None:
        if not self._destroy_on_leave:
            return
        if not isinstance(value, Entity) or getattr(value, "_ephemeral", False):
            return
        if not value.is_alive:
            return
        from .transients import destroy_when_not_dying
        object.__setattr__(value, "_history_added_at", float(added_at))
        destroy_when_not_dying(value)

    def _check_alive(self, verb: str) -> None:
        """Mutators raise after ``Contrail.destroy()``. Reads stay legal."""
        if not self._destroyed:
            return
        raise DestroyedError(
            f"{type(self).__name__} is destroyed and cannot {verb}. "
            "A timer is probably still feeding it; cancel its handle "
            "when you destroy the Contrail."
        )

    def _guard_add(self, thing: Any) -> None:
        _reject_destroyed_source(thing, "add")
        if isinstance(thing, Entity):
            owner = getattr(thing, "owner", None)
            if owner is not None:
                part = getattr(thing, "name", type(thing).__name__)
                host = getattr(owner, "name", type(owner).__name__)
                raise TypeError(
                    f"`{part}` belongs to `{host}` — "
                    f"use `snapshot({host})` to keep its position."
                )
            if self._destroy_on_leave and any(v is thing for v, _t in self._items):
                raise ValueError(
                    f"{type(thing).__name__} is already in this History — "
                    "owning it twice would destroy it twice."
                )
            return
        if isinstance(thing, Container):
            raise TypeError(
                f"{type(thing).__name__} is a live value — "
                "use snapshot(...) to keep a position, or add a copy of the value."
            )

    def _evict_oldest(self) -> None:
        if not self._items:
            return
        value, added_at = self._items.pop(0)
        self._leave(value, added_at)

    def _evict_over_bounds(self, *, now: Optional[float] = None) -> None:
        mp = self._max_points
        while mp is not None and len(self._items) > mp:
            self._evict_oldest()
        dur = self._duration
        if dur is None:
            return
        t = _now() if now is None else float(now)
        while self._items and (t - self._items[0][1]) > dur:
            self._evict_oldest()

    # -- hooks ---------------------------------------------------------------

    @property
    def on_leave(self):
        """Side effect when something leaves. One argument: the thing. Additive."""
        return self._on_leave_cb

    @on_leave.setter
    def on_leave(self, value) -> None:
        self._check_alive("on_leave")
        if value is not None:
            expect_callable(value, what="on_leave")
        if value is not None and _method_overrides(type(self), "on_leave", History):
            raise TypeError(
                f"{type(self).__name__} already defines on_leave; "
                "do not also assign on_leave"
            )
        self._on_leave_cb = value

    # -- sequence ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        for v, _t in self._items:
            yield v

    def __getitem__(self, key):
        if isinstance(key, slice):
            return [v for v, _t in self._items[key]]
        return self._items[key][0]

    @property
    def first(self) -> Any:
        """The oldest kept entry. Raises ``IndexError`` when empty."""
        if not self._items:
            raise IndexError("History is empty")
        return self._items[0][0]

    @property
    def last(self) -> Any:
        """The newest entry. Raises ``IndexError`` when empty."""
        if not self._items:
            raise IndexError("History is empty")
        return self._items[-1][0]

    def __repr__(self) -> str:
        parts = []
        if self._max_points is not None:
            parts.append(f"max_points={self._max_points}")
        if self._duration is not None:
            parts.append(f"duration={self._duration}")
        return f"History(len={len(self)}" + (", " + ", ".join(parts) if parts else "") + ")"


# ---------------------------------------------------------------------------
# Private stroke for Contrail
# ---------------------------------------------------------------------------

def _span_table(xs: List[float], ys: List[float], smooth: float) -> Optional[List[tuple]]:
    """Each span ``i → i+1`` as its cubic's ``(c1x, c1y, c2x, c2y, ex, ey)``,
    or ``None`` for a polyline (``smooth <= 0``).

    Computed once per rebuild and replayed into the stroke and its fade bands.
    Each span used to rebuild the point list and the phantom ends on its own
    (O(n²) a rebuild) and the bands computed every span a second time: a
    40-point faded trail took ~160 µs a snapshot, now ~57, with the same
    path bytes (History Design, "One span table a rebuild")."""
    n = len(xs)
    if smooth <= 0.0 or n < 2:
        return None
    pts = list(zip(xs, ys))
    before, after = _phantom_open(pts)
    spans = []
    for i in range(n - 1):
        p0 = before if i == 0 else pts[i - 1]
        p3 = after if i + 2 >= n else pts[i + 2]
        _b0, b1, b2, b3 = catmull_rom_to_bezier(p0, pts[i], pts[i + 1], p3, smooth=smooth)
        spans.append((b1[0], b1[1], b2[0], b2[1], b3[0], b3[1]))
    return spans


def _append_span(path: skia.Path, xs: List[float], ys: List[float], i: int,
                 spans: Optional[List[tuple]]) -> None:
    """Append sample span ``i → i+1`` (line, or the cubic from ``spans``) onto ``path``."""
    if spans is None:
        path.lineTo(xs[i + 1], ys[i + 1])
    else:
        path.cubicTo(*spans[i])


def _fill_stroke_path(path: skia.Path, xs: List[float], ys: List[float],
                      spans: Optional[List[tuple]]) -> None:
    """Full open stroke through samples: polyline or Catmull-Rom cubics (``spans``)."""
    path.rewind()
    n = len(xs)
    if n == 0:
        return
    path.moveTo(xs[0], ys[0])
    for i in range(n - 1):
        _append_span(path, xs, ys, i, spans)


def _fill_band_path(
    path: skia.Path,
    xs: List[float],
    ys: List[float],
    *,
    span0: int,
    span1: int,
    spans: Optional[List[tuple]],
) -> None:
    """Open subpath covering sample spans ``[span0, span1)``."""
    path.rewind()
    if span1 <= span0:
        return
    path.moveTo(xs[span0], ys[span0])
    for i in range(span0, span1):
        _append_span(path, xs, ys, i, spans)


class _Stroke(Shape):
    """Minimal world-space stroke Shape. Mutated in place on rebuild."""

    def __init__(
        self,
        *,
        color=None,
        visual=None,
        line_width: Optional[float] = None,
        line_join: Optional[str] = None,
        layer: Any = _USE_LAYER_DEFAULT,
    ):
        super().__init__(color=color, visual=visual, line_width=line_width, layer=layer)
        self.fill = None
        self.line_join = "round" if line_join is None else line_join
        self._xs: List[float] = []
        self._ys: List[float] = []
        self._fade = False
        self._ease_fn: Optional[Callable[[float], float]] = None
        self._smooth = 1.0
        self._path = skia.Path()
        self._band_paths: List[skia.Path] = []
        self._band_alphas: List[float] = []  # ease multipliers (not × base alpha)
        self._center_pt = Point(0.0, 0.0, layer=None)

    def _primary_is_stroke(self) -> bool:
        return True

    @property
    def center(self) -> Point:
        return self._center_pt

    def rebuild(
        self,
        points: Sequence[Any],
        *,
        fade: bool = False,
        ease: Optional[Callable[[float], float]] = None,
        smooth: float = 1.0,
    ) -> None:
        xs = self._xs
        ys = self._ys
        xs.clear()
        ys.clear()
        for p in points:
            xy = _xy_of(p, required=True)
            xs.append(float(xy[0]))
            ys.append(float(xy[1]))
        self._fade = bool(fade)
        self._ease_fn = ease
        self._smooth = float(smooth)
        self._rebuild_geometry()

    def _rebuild_geometry(self) -> None:
        """Fill ``_path`` / fade bands from current ``_xs`` / ``_ys``."""
        xs, ys = self._xs, self._ys
        n = len(xs)
        smooth = self._smooth
        table = _span_table(xs, ys, smooth)
        _fill_stroke_path(self._path, xs, ys, table)
        self._band_paths.clear()
        self._band_alphas.clear()
        if n >= 1:
            self._center_pt.x = sum(xs) / n
            self._center_pt.y = sum(ys) / n
        if self._fade and n >= 2:
            ease = self._ease_fn or (lambda t: t)
            spans = n - 1
            n_bands = min(_FADE_BANDS, spans)
            denom = float(n - 1)
            for b in range(n_bands):
                span0 = (b * spans) // n_bands
                span1 = ((b + 1) * spans) // n_bands
                if span1 <= span0:
                    continue
                band = skia.Path()
                _fill_band_path(band, xs, ys, span0=span0, span1=span1, spans=table)
                # Alpha at the band's newest stamp index.
                t = float(ease(span1 / denom))
                self._band_paths.append(band)
                self._band_alphas.append(max(0.0, min(1.0, t)))
        self._geom_path = self._path
        self._geom_path_key = n

    def _domain_aabb(self):
        if not self._xs:
            return None
        pad = max(4.0, float(self.line_width) * 0.5 + 2.0)
        return (
            min(self._xs) - pad,
            min(self._ys) - pad,
            max(self._xs) + pad,
            max(self._ys) + pad,
        )

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        n = len(self._xs)
        if n < 2:
            return
        paint = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
        if paint is None:
            return
        if not self._fade:
            skia_canvas.drawPath(self._path, paint)
            return
        bands = self._band_paths
        if not bands:
            return
        work = skia.Paint(paint)
        c4 = paint.getColor4f()
        base_a = float(c4.fA)
        host_cap = paint.getStrokeCap()
        n_bands = len(bands)
        for i, (bpath, mul) in enumerate(zip(bands, self._band_alphas)):
            a = max(0.0, min(1.0, base_a * mul))
            work.setColor4f(skia.Color4f(c4.fR, c4.fG, c4.fB, a))
            # Tail + head keep the host cap; interior bands butt to avoid ADD knots.
            if n_bands == 1 or i == 0 or i == n_bands - 1:
                work.setStrokeCap(host_cap)
            else:
                work.setStrokeCap(skia.Paint.Cap.kButt_Cap)
            skia_canvas.drawPath(bpath, work)

    def _clone_geometry(self, **kwargs):
        raise TypeError("_Stroke is private to Contrail and cannot be cloned")

    def _move_by(self, dx: float, dy: float, *, force: bool = False):
        if not self._xs:
            return self
        dx = 0.0 if dx is None else float(dx)
        dy = 0.0 if dy is None else float(dy)
        if dx == 0.0 and dy == 0.0:
            return self
        for i in range(len(self._xs)):
            self._xs[i] += dx
            self._ys[i] += dy
        self._rebuild_geometry()
        return self

    def _move_to(self, x: float, y: float, *, force: bool = False):
        if not self._xs:
            return self
        cx = sum(self._xs) / len(self._xs)
        cy = sum(self._ys) / len(self._ys)
        dx = 0.0 if x is None else float(x) - cx
        dy = 0.0 if y is None else float(y) - cy
        return self._move_by(dx, dy, force=force)


# ---------------------------------------------------------------------------
# Contrail
# ---------------------------------------------------------------------------

class Contrail(History):
    """One stroke through sampled positions, optional alpha fade tail→head.

    ``snapshot`` stores an ephemeral ``Point`` (Graphic / tuple / Point / x, y).
    The point is not a registry citizen and does not enter the reactive graph.
    ``on_leave=`` is an author side-effect hook; the stroke always trims itself.
    ``add`` raises — Contrail keeps positions, not objects.
    Default ``smooth=1`` is a Catmull-Rom cubic; ``smooth=0`` is a polyline.

    Args:
        max_points: Keep at most this many positions.
        duration: Keep positions younger than this many seconds.
        fade: Taper toward the tail.
        ease: Fade curve (needs ``fade=True``).
        color: Trail color.
        visual: A look along the trail (``Laser('red')``).
        line_width: Thickness.
        line_join: Corners: ``"miter"`` · ``"bevel"`` · ``"round"``.
        smooth: 0 = polyline, 1 = smooth (default).
        on_leave: ``fn(point)`` called when a position falls out.
        layer: Draw layer of the trail (default: the default world layer), so
            it can sit behind its source (``layer="back"``).
    """

    def __init__(
        self,
        *,
        max_points: Optional[int] = None,
        duration: Optional[float] = None,
        fade: bool = False,
        ease: Optional[Ease] = None,
        color=None,
        visual=None,
        line_width: Optional[float] = None,
        line_join: Optional[str] = None,
        smooth=1,
        on_leave: Optional[Callable] = None,
        layer: Any = _USE_LAYER_DEFAULT,
    ):
        self._fade = expect_bool(fade, "Contrail fade")
        if self._fade:
            self._ease = resolve_ease(ease if ease is not None else "linear", what="ease")
        else:
            if ease is not None:
                raise TypeError("ease= requires fade=True")
            self._ease = None
        self._smooth = _parse_contrail_smooth(smooth)
        self._stroke_dirty = False
        self._rebuild_count = 0
        # Validate before building the private stroke: a rejected call must
        # not leave a registered line behind (A4).
        from .validate import count as _count, seconds as _seconds
        if max_points is not None:
            _count(max_points, "max_points", 0)
        if duration is not None:
            if _seconds(duration, "duration") < 0:
                raise ValueError(f"duration must be >= 0, got {duration}")
        if on_leave is not None:
            expect_callable(on_leave, what="on_leave")
        _parse_contrail_smooth(smooth)
        self._stroke = _Stroke(
            color=color,
            visual=visual,
            line_width=line_width,
            line_join=line_join,
            layer=layer,
        )
        try:
            super().__init__(
                max_points=max_points, duration=duration, on_leave=on_leave,
            )
        except BaseException:
            # The stroke is a registered Line: a rejected Contrail must not
            # leave it drawn (A10; H1 rollback does not know about it).
            self._stroke.destroy()
            raise

    # -- stroke proxies ------------------------------------------------------

    @property
    def fade(self) -> bool:
        """Taper the trail's opacity toward its tail (``True`` / ``False``)."""
        return self._fade

    @fade.setter
    def fade(self, value: bool) -> None:
        self._check_alive("fade")
        self._fade = expect_bool(value, "Contrail.fade")
        if self._fade and self._ease is None:
            self._ease = resolve_ease("linear", what="ease")
        self._mark_stroke_dirty()
        self._flush_stroke()

    @property
    def ease(self):
        """Fade curve along the trail (``"linear"``, ``"ease_out"``, ...). Needs ``fade=True``."""
        return self._ease

    @ease.setter
    def ease(self, value: Ease) -> None:
        self._check_alive("ease")
        if not self._fade:
            raise TypeError("ease= requires fade=True")
        self._ease = resolve_ease(value, what="ease")
        self._mark_stroke_dirty()
        self._flush_stroke()

    @property
    def smooth(self) -> float:
        """Corner rounding: 0 = polyline, 1 = smooth curve (default)."""
        return self._smooth

    @smooth.setter
    def smooth(self, value) -> None:
        self._check_alive("smooth")
        self._smooth = _parse_contrail_smooth(value)
        self._mark_stroke_dirty()
        self._flush_stroke()

    @property
    def layer(self):
        """The trail's draw layer (its name). Writable: ``trail.layer = "back"``
        puts it behind what draws on the default layer (showcase C; it was
        fixed to the default layer)."""
        return self._stroke.layer

    @layer.setter
    def layer(self, value) -> None:
        self._check_alive("layer")
        self._stroke.layer = value

    @property
    def color(self):
        """Trail color (any color form)."""
        return self._stroke.color

    @color.setter
    def color(self, value) -> None:
        self._check_alive("color")
        self._stroke.color = value

    @property
    def visual(self):
        """A look drawn along the trail (``Laser('red')``, ``Neon()``, ...), or ``None``."""
        return self._stroke.visual

    @visual.setter
    def visual(self, value) -> None:
        self._check_alive("visual")
        self._stroke.visual = value

    @property
    def line_width(self) -> float:
        """Trail thickness in design units."""
        return self._stroke.line_width

    @line_width.setter
    def line_width(self, value: float) -> None:
        self._check_alive("line_width")
        self._stroke.line_width = value

    @property
    def line_join(self) -> str:
        """Corner style: ``"miter"`` · ``"bevel"`` · ``"round"``."""
        return self._stroke.line_join

    @line_join.setter
    def line_join(self, value: str) -> None:
        self._check_alive("line_join")
        self._stroke.line_join = value

    @property
    def line_cap(self) -> str:
        """End style: ``"round"`` · ``"butt"`` · ``"square"``."""
        return self._stroke.line_cap

    @line_cap.setter
    def line_cap(self, value: str) -> None:
        self._check_alive("line_cap")
        self._stroke.line_cap = value

    # -- stroke dirty / flush ------------------------------------------------

    def _mark_stroke_dirty(self) -> None:
        self._stroke_dirty = True

    def _flush_stroke(self) -> None:
        if not self._stroke_dirty:
            return
        self._stroke_dirty = False
        self._stroke.rebuild(
            list(self),
            fade=self._fade,
            ease=self._ease,
            smooth=self._smooth,
        )
        self._rebuild_count += 1

    def _evict_over_bounds(self, *, now: Optional[float] = None) -> None:
        super()._evict_over_bounds(now=now)
        self._flush_stroke()

    # -- History overrides ---------------------------------------------------

    def add(self, thing: Any) -> Any:
        """Refused: a Contrail keeps positions — use ``snapshot(point)``."""
        self._check_alive("add")
        _reject_destroyed_source(thing, "add")
        raise TypeError("Contrail keeps positions — use snapshot(...)")

    def _note_stored(self) -> None:
        self._mark_stroke_dirty()

    def _note_removed(self) -> None:
        self._mark_stroke_dirty()

    def pop(self, index: int = -1) -> Any:
        """Remove and return an entry (default the newest); the trail redraws."""
        value = super().pop(index)
        self._flush_stroke()
        return value

    def discard(self, value: Any) -> bool:
        """Remove ``value`` if present; ``True`` if something was removed. The trail redraws."""
        ok = super().discard(value)
        self._flush_stroke()
        return ok

    def clear(self) -> None:
        """Remove every entry; the trail disappears until the next ``snapshot``."""
        super().clear()
        self._flush_stroke()

    def destroy(self) -> None:
        """Clear positions (no ``on_leave``) and destroy the private stroke.

        Idempotent. Afterwards every mutator raises ``DestroyedError``;
        reads (``len``, index, getters) stay legal.
        """
        if self._destroyed:
            return
        self._destroyed = True
        _unregister_history(self)
        self._clear_items(silent=True)
        self._flush_stroke()
        stroke = getattr(self, "_stroke", None)
        if stroke is not None and getattr(stroke, "is_alive", False):
            stroke.destroy()

    def __repr__(self) -> str:
        parts = [f"len={len(self)}"]
        if self._max_points is not None:
            parts.append(f"max_points={self._max_points}")
        if self._duration is not None:
            parts.append(f"duration={self._duration}")
        if self._fade:
            parts.append("fade=True")
        if self._smooth != 1.0:
            parts.append(f"smooth={self._smooth}")
        return f"Contrail({', '.join(parts)})"
