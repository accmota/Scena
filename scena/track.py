"""Track: drawable curve and motion ride (one Shape, two roles)."""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Callable, List, Optional, Sequence, Tuple, Union
from weakref import ref

import skia

from ._defaults import Unset
from .curves import (
    SAMPLES_HIGH,
    SAMPLES_LOW,
    apply_offsets,
    apply_pose,
    apply_pose_vec,
    arc_length_table,
    build_table,
    densify_polyline,
    flatten_controls,
    min_samples_for_modifiers,
    orbit_displacements,
    sample as curve_sample,
    sample_angle as curve_angle,
    sample_span as curve_span,
    sample_tangent as curve_tangent,
    subpolyline as curve_subpolyline,
    samples_per_segment_for,
    to_local,
    wander_offsets,
    wrap_u,
    zigzag_amounts,
)
from .entity import (
    _COPY_GROUPS,
    _USE_LAYER_DEFAULT,
    _geom_path_cache_set,
    _pose_rotation_add,
    _pose_rotation_set,
    _pose_scale_set,
    _refuse_if_destroyed,
)
from .shapes import (
    Circle,
    Ellipse,
    Line,
    Point,
    Polygon,
    Rect,
    Shape,
    Square,
    _STYLE_PAINT,
    _bare_attr,
    _bare_num,
    _clamped_spread,
    _default_pose,
    _ensure_writable,
    _takein_xy_float,
    get_xy,
)
from .state import (
    Attribute,
    as_payload,
    Container,
    ContainerSlot,
    DerivedAttributeError,
    FieldType,
    ScalarSlot,
    _init_composite,
    _init_scalar,
    batch_update_self,
)
from .scenamath import Vec2
from .validate import HINT_EXTENT, number as _number
from .validate import expect_bool as _expect_flag


# Upper bound for author sample counts: a typo like spaced_points(1e9) would
# otherwise build a list for minutes (A9: spaced_points(1e308) hung).
_MAX_SAMPLES = 1_000_000


def _u_arg(u, what: str) -> float:
    """Track parameter ``u``: a fixed finite number (functions raise)."""
    from .validate import number
    return number(u, f"{what} u")


def _sample_count(n, what: str) -> int:
    from .validate import count
    n = count(n, what, 1)
    if n > _MAX_SAMPLES:
        raise ValueError(f"{what} must be <= {_MAX_SAMPLES:,}, got {n:,}")
    return n


def _sq(v: float) -> float:
    """``v * v``. Not ``v ** 2``: a float power raises OverflowError for a
    huge-but-finite author coordinate; a product saturates to inf."""
    return v * v

_USE_LAYER_SENTINEL = Unset("<default layer>")
_TRACK_PARTS = ("center", "radius", "u", "begin", "end", "cursor", "length")
_SPEC_CLOSED = frozenset({"circle", "eight", "star", "shuttle"})
_EIGHT_DEFAULT_WIDTH = 90.0
_EIGHT_DEFAULT_HEIGHT = 40.0


def _clamp01(u) -> float:
    v = float(u)
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _pulled_xy(point) -> Tuple[float, float]:
    """Read a Point's x/y, following inbound ``@=`` even if A1 left us not dirty."""
    link = getattr(point, "_link", None)
    if link is not None:
        ev = getattr(link, "evaluate", None)
        if ev is not None:
            try:
                src = ev()
            except Exception:
                src = None
            if src is not None and src is not point:
                if hasattr(src, "x") and hasattr(src, "y"):
                    return float(src.x), float(src.y)
                try:
                    return get_xy(src, bare=False)
                except Exception:
                    pass
    d = getattr(point, "__dict__", None)
    if d is not None:
        d.pop("_scalar_bare_ok", None)
    resolve = getattr(point, "_resolve_link", None)
    if resolve is not None:
        resolve()
    return float(point.x), float(point.y)


# ---------------------------------------------------------------------------
# Author toggle (debug overlay). Immediate-mode; does not flip Track.visible.
# ---------------------------------------------------------------------------
_show_tracks = False
# Magenta — distinct from gold colliders and cyan playfield.
_TRACK_OVERLAY_RGBA = (0.92, 0.38, 0.78, 0.95)
_TRACK_OVERLAY_IDLE_RGBA = (0.92, 0.38, 0.78, 0.45)


def show_tracks(enabled: bool = True) -> None:
    """Draw active ``move_along`` tracks (and idle Track objects) as an overlay.

    Args:
        enabled: Draw every Track as an overlay (``False`` hides them).
    """
    global _show_tracks
    from .validate import expect_bool
    _show_tracks = expect_bool(enabled, "show_tracks enabled")


def tracks_overlay_wanted() -> bool:
    return bool(_show_tracks)


def _parse_smooth(value) -> float:
    if value is False:
        return 0.0
    if value is True or value is None:
        return 1.0
    from .validate import number
    return number(value, "smooth")


def _parse_quality(value) -> str:
    q = "high" if value is None else str(value).lower()
    if q not in ("high", "low"):
        raise ValueError('quality= must be "high" or "low"')
    return q


def _parse_loops(value) -> int:
    """1+ laps, or -1 for forever.

    ``True``/``False`` are rejected (bool is an ``int`` subclass). Non-integral
    floats are rejected; integral floats (``2.0``) are accepted.
    """
    if value == "forever":
        return -1
    if isinstance(value, bool):
        raise ValueError('loops= must be an int >= 1, or "forever"')
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError('loops= must be an int >= 1, or "forever"')
        value = int(value)
    elif not isinstance(value, int):
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError('loops= must be an int >= 1, or "forever"') from None
    if value < 1:
        raise ValueError('loops= must be an int >= 1, or "forever"')
    return value


def _is_linkish(value) -> bool:
    if callable(value) and not isinstance(value, type):
        return True
    if isinstance(value, (Container,)):
        return True
    if isinstance(value, tuple) and len(value) == 2:
        return _is_linkish(value[0]) or _is_linkish(value[1])
    return False


def _as_xy_static(value) -> Tuple[float, float]:
    """Snapshot a delta: Vec2, Point, or ``(dx, dy)``.

    A Graphic is rejected — this is a direction, same rule as ``move_by``.
    Locations use :func:`_point_xy_static`.
    """
    from .shapes import _read_xy
    x, y = _read_xy(value, True, False, False)
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("coordinates must be finite")
    return x, y


def _point_xy_static(value) -> Tuple[float, float]:
    """Snapshot a location (any point-like) and require finite coordinates."""
    from .shapes import _xy_of
    x, y = _xy_of(value, required=True)
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("coordinates must be finite")
    return x, y


def _finite_number(value, *, what: str) -> float:
    """Construction/write check. Not used from sample, hit, or draw."""
    from .validate import finite
    return finite(value, what)


def _resolve_anchored(*, placement_given: bool, floating, anchored) -> bool:
    """``floating=`` always wins; else an explicit ``_anchored``; else inference."""
    if floating is not None:
        return not bool(floating)
    if anchored is not None:
        return bool(anchored)
    return bool(placement_given)


class _TrackCenterSlot(ContainerSlot):
    """``track.center = …`` is a placement (``Track._note_placed``), even onto
    the spot the track already has (a move of 0 changes no value)."""

    def __set__(self, instance, value):
        super().__set__(instance, value)
        instance._note_placed()


def _line_center_from_p1(p1, length: float, angle: float) -> Tuple[float, float]:
    """Defining pose so ``at(0)`` lands on ``p1`` for a sizes-form line."""
    sx, sy = _point_xy_static(p1)
    h = 0.5 * float(length)
    rad = math.radians(float(angle))
    return (sx + h * math.cos(rad), sy + h * math.sin(rad))


def _points_from_vectors(vectors) -> List[Tuple[float, float]]:
    """Expand ``vectors=`` deltas into a start-relative absolute point list.

    Origin is ``(0, 0)``; ``start=`` plants ``u=0`` after ``to_local``. The
    keyword already means "every element is a delta" — ``Vec2`` and ``(dx, dy)``
    are interchangeable, snapshotted at construction.
    """
    if not isinstance(vectors, (list, tuple)) or len(vectors) < 1:
        raise ValueError("Track(vectors=) needs at least 1 vector")
    x = y = 0.0
    pts: List[Tuple[float, float]] = [(0.0, 0.0)]
    for v in vectors:
        dx, dy = _as_xy_static(v)
        x += dx
        y += dy
        pts.append((x, y))
    return pts


def _reject_exclusive_track_raw(*, points, vectors, radius, source) -> None:
    """``points=`` / ``vectors=`` / ``radius=`` / a Shape source are exclusive."""
    raw = []
    if points is not None:
        raw.append("points=")
    if vectors is not None:
        raw.append("vectors=")
    if radius is not None:
        raw.append("radius=")
    source_shape = source is not None and not isinstance(source, (list, tuple))
    source_seq = isinstance(source, (list, tuple))
    if source_shape and raw:
        raise TypeError(
            "Track(shape) does not take " + " / ".join(raw)
        )
    if source_seq and points is not None:
        raise TypeError("Track() takes a point list or points=, not both")
    if source_seq and vectors is not None:
        raise TypeError("Track() takes a point list or vectors=, not both")
    if source_seq and radius is not None:
        raise TypeError("Track() takes a point list or radius=, not both")
    if len(raw) > 1:
        raise TypeError("Track() takes only one of " + ", ".join(raw))


# ---------------------------------------------------------------------------
# Outline of any Shape (world vertices + closed flag)
# ---------------------------------------------------------------------------

def _circle_arc(shape) -> Tuple[float, float, bool]:
    """Heading, clamped opening, and whether the outline is a full ring.

    A full circle starts at ``angle`` (default 0, so ``u=0`` stays on +x).
    A partial arc starts at ``angle - spread/2``.
    """
    arc_angle = getattr(shape, "_arc_angle", None)     # a rim-placed circle: toward p1
    ang = float(arc_angle()) if callable(arc_angle) else float(_bare_num(getattr(shape, "angle", 0.0)))
    spread = _clamped_spread(_bare_num(getattr(shape, "spread", 360.0)))
    full = spread >= 360.0 - 1e-4
    return ang, spread, full


def _circle_verts(shape, n: int) -> List[Tuple[float, float]]:
    cx, cy = get_xy(shape.center, bare=True)
    r = abs(_bare_num(shape.radius))
    ang, spread, full = _circle_arc(shape)
    n = max(8, int(n))
    if full:
        return [
            (cx + r * math.cos(math.radians(ang + 360.0 * i / n)),
             cy + r * math.sin(math.radians(ang + 360.0 * i / n)))
            for i in range(n)
        ]
    start = ang - spread * 0.5
    return [
        (cx + r * math.cos(math.radians(start + spread * i / n)),
         cy + r * math.sin(math.radians(start + spread * i / n)))
        for i in range(n + 1)
    ]


def _ellipse_verts(shape, n: int) -> List[Tuple[float, float]]:
    cx, cy, w, h, ang = shape._oriented_frame()
    rx, ry = abs(w) * 0.5, abs(h) * 0.5
    rad = math.radians(float(ang))
    c, s = math.cos(rad), math.sin(rad)
    n = max(8, int(n))
    out = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        lx, ly = rx * math.cos(a), ry * math.sin(a)
        out.append((cx + lx * c - ly * s, cy + lx * s + ly * c))
    return out


def _rrect_outline_verts(shape, samples: int) -> List[Tuple[float, float]]:
    """World outline of a Rect/Square with ``corner_radius`` (CCW, paint-matched).

    ``u=0`` is the start of the bottom edge after the BL fillet, so as ``r → 0``
    the first point approaches local BL (same as ``_oriented_box_verts``).
    ``r <= 0`` (including a radius clamped to a degenerate side) is the sharp 4-gon.
    Any positive radius, including below half a pixel, follows the rounded silhouette.
    """
    from .geom import _oriented_box_verts

    cx, cy, w, h, ang = shape._oriented_frame()
    hw, hh = abs(w) * 0.5, abs(h) * 0.5
    r = max(0.0, float(getattr(shape, "corner_radius", 0.0) or 0.0))
    r = min(r, hw, hh)
    if r <= 0.0:
        return _oriented_box_verts(shape)

    n_arc = max(2, min(8, int(samples) // 8))
    rad = math.radians(float(ang))
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    def world(lx: float, ly: float) -> Tuple[float, float]:
        return (cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a)

    def arc(bx: float, by: float, a0: float, a1: float) -> None:
        # Skip i=0 (shared with previous edge endpoint); include the arc end.
        for i in range(1, n_arc + 1):
            t = i / n_arc
            a = a0 + t * (a1 - a0)
            out.append(world(bx + r * math.cos(a), by + r * math.sin(a)))

    out: List[Tuple[float, float]] = []
    # Bottom edge after BL fillet → BR fillet start.
    out.append(world(-hw + r, -hh))
    out.append(world(hw - r, -hh))
    # BR: (-90° → 0°), TR: (0° → 90°), TL: (90° → 180°), BL: (180° → 270°).
    arc(hw - r, -hh + r, -math.pi / 2, 0.0)
    out.append(world(hw, hh - r))
    arc(hw - r, hh - r, 0.0, math.pi / 2)
    out.append(world(-hw + r, hh))
    arc(-hw + r, hh - r, math.pi / 2, math.pi)
    out.append(world(-hw, -hh + r))
    arc(-hw + r, -hh + r, math.pi, 1.5 * math.pi)
    # Last arc end == first point; drop the duplicate for a closed ring.
    if out and abs(out[-1][0] - out[0][0]) < 1e-9 and abs(out[-1][1] - out[0][1]) < 1e-9:
        out.pop()
    return out


def _start_at_bottom_left(shape, verts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Rotate a Rect outline so ``u = 0`` is at its named ``bottom_left``.

    Both outlines are CCW in the drawn frame, one equal run of vertices per
    side, starting at the drawn bottom-left. The named corners stay with
    their points (Shapes Design — Named points), so the start follows the
    name, not the drawn corner; travel stays CCW. This is a use of a name.
    """
    sa, sb = shape._effective_name_signs()
    # Drawn corners in outline order: (-,-), (+,-), (+,+), (-,+).
    k = {(-1, -1): 0, (1, -1): 1, (1, 1): 2, (-1, 1): 3}[(-sa, -sb)]
    if k == 0 or len(verts) % 4:
        return verts
    cut = k * (len(verts) // 4)
    return verts[cut:] + verts[:cut]


def _concave_class():
    from .shapes import Concave
    return Concave


def shape_outline(shape, *, samples: int = SAMPLES_HIGH * 4) -> Tuple[List[Tuple[float, float]], bool]:
    """World-space outline vertices and whether the outline is closed.

    ``u=0`` is the first vertex. A full circle starts at its ``angle`` (0 = +x);
    a partial circle starts at ``angle - spread/2``. Travel is CCW.
    Rect/Square with ``corner_radius > 0`` follows the rounded paint silhouette;
    ``r == 0`` stays the sharp 4-gon (same verts as ``geom._oriented_box_verts``).
    Rect/Square start at the named ``bottom_left`` (after its fillet when rounded).
    A Concave starts where its curve begins.
    """
    from .entity import scena_kind
    if isinstance(shape, Track) or scena_kind(shape) == "Track":  # reload-safe
        pts = [shape._world_of(x, y) for x, y in shape._travel_vertices()]
        return pts, bool(shape._table_host()._closed)
    if isinstance(shape, Circle):
        verts = _circle_verts(shape, samples)
        _ang, _spread, full = _circle_arc(shape)
        return verts, full
    if isinstance(shape, Ellipse):
        return _ellipse_verts(shape, samples), True
    if isinstance(shape, Line):
        return [get_xy(shape.p1, bare=True), get_xy(shape.p2, bare=True)], False
    if isinstance(shape, _concave_class()):
        # The box with its curve as chords within 0.01 DU; u = 0 where the
        # curve begins (counter-clockwise travel meets the curve first).
        return shape._world_ring(), True
    if isinstance(shape, (Rect, Square)):
        r = max(0.0, float(getattr(shape, "corner_radius", 0.0) or 0.0))
        if r > 0.0:
            verts = _rrect_outline_verts(shape, samples)
        else:
            from .geom import _oriented_box_verts
            verts = _oriented_box_verts(shape)
        return _start_at_bottom_left(shape, verts), True
    from .entity import is_sprite_family
    if is_sprite_family(shape):
        verts = shape._silhouette_world_verts()
        if len(verts) >= 3:
            return verts, True
        raise TypeError(
            f"move_along / Track() cannot travel {type(shape).__name__} outline"
        )
    from .geom import _outline_verts
    verts = _outline_verts(shape)
    if verts:
        return verts, True
    raise TypeError(
        f"move_along / Track() cannot travel {type(shape).__name__} outline"
    )


class TrackModel(Enum):
    FREE = "free"
    CIRCLE = "circle"
    SHAPE = "shape"


class Track(Shape):
    """Multi-model curve: drawable (invisible by default) and a motion track.

    Construction infers anchored vs floating from the preset's placement
    keyword (``center=`` / ``p1=`` / ``start=``). Sizes only → floating;
    placement given → anchored. A sizes-only track given a place later (a
    link on ``center``, ``center =``, ``move_to`` / ``move_by``) is anchored
    there. ``floating=`` explicit always wins.
    ``points=`` is world-space absolute; ``vectors=`` is a turtle walk of deltas.
    Bare ``Track()`` is ``Track.eight()``.

    Args:
        source: A shape to follow the outline of (``Track(circle)``).
        points: World points to connect.
        vectors: Steps from ``start`` (a turtle walk).
        smooth: 0 = polyline, 1 = smooth curve (default).
        closed: Loop back to the start.
        quality: ``"high"`` (default) or ``"low"``.
        center: Where the track sits (anchors it).
        radius: Size for circle-like presets.
        begin: Start of the used span, 0–1.
        end: End of the used span, 0–1 (default 1).
        start: First point for ``vectors`` (anchors it).
        floating: ``True`` = moves with its rider; ``False`` = fixed in the world
            (default: inferred).
        angle: Heading in degrees (turns the track about its center).
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
        visible: Draw it (default: only when styled).
    """

    # Computed fields come from the path, not from u / begin / end
    # (``Container._derived_field_message``).
    _derived_from = "path"

    def _derived_field_message(self, name, operation, value=None, part=None):
        """``track.cursor = …``: the cursor moves with ``u``, not by placement."""
        if name == "cursor":
            what = "linked" if operation == "link" else "set"
            fix = (
                'Drive it by linking u instead: track["u"] @= lambda: ...'
                if operation == "link"
                else "Move it along the track with track.u = 0.5 (0 = start, 1 = end)."
            )
            return f"Track.cursor is the point at u along the track, so it cannot be {what}. {fix}"
        return super()._derived_field_message(name, operation, value, part)

    _call_example = "Track(points=[(0, 0), (100, 50)]), Track(shape) or Track.circle(radius=80)"
    # Unknown keyword: the actor wrapper names the fix with these hints.
    _call_hints = {
        "width": (
            "width= is not stroke thickness. "
            "Use line_width=. Track.eight(width=) is the figure-eight size."
        ),
        "stroke": "stroke= was removed. Use color= — it writes the stroke on Track.",
        "fill": (
            "fill= is not a Track constructor keyword. "
            "Show the track (color=, visual=, line_width=, or visible=True), then set .fill."
        ),
    }

    center = _TrackCenterSlot(Point)
    radius = ScalarSlot(magnitude=True, hint=HINT_EXTENT, label="Track.radius")
    length = ScalarSlot(FieldType.Derivate)
    u = ScalarSlot()
    # 0..1 like ``=`` (``_write_field`` clamps); the bounds clamp a link too.
    begin = ScalarSlot(minimum=0.0, maximum=1.0, out_of_range="clamp", label="Track.begin")
    end = ScalarSlot(default=1.0, minimum=0.0, maximum=1.0, out_of_range="clamp", label="Track.end")
    cursor = ContainerSlot(Point, FieldType.Derivate)

    _CTOR_EXTRA_KEYS = frozenset({
        "smooth", "closed", "quality",
        "line_width", "visible", "points", "vectors", "radius", "center",
        "begin", "end", "floating", "angle", "start",
    })

    # Author keywords still accepted. Not the private _spec / _anchored / _ends / _register.
    _TRACK_PUBLIC_KEYS = frozenset({
        "points", "vectors", "smooth", "closed", "quality", "center", "radius",
        "begin", "end", "start", "floating", "angle", "layer", "group",
        "visual", "color", "line_width", "visible",
    })

    def __init__(self, source=None, *, points=None, vectors=None, smooth=1.0,
                 closed=None, quality="high", center=None, radius=None,
                 begin=None, end=None, start=None, floating=None, angle=None,
                 layer=_USE_LAYER_SENTINEL, group=None, visual=None, color=None,
                 line_width=None,
                 visible=None, _spec=None, _anchored=None, _ends=None,
                 _register=True):
        # Movement-only Paths stay off the draw list (reclaimable). Styled /
        # visible=True / explicit layer= register so they draw and appear in the
        # idle overlay. Explicit layer=None stays undrawn. Point-style visible
        # setter promotes later if the author shows an unstyled Track.
        # .fill / .line / .line_width after construction do not.
        from .entity import _USE_LAYER_DEFAULT
        # Class keywords (``class Rota(Track, color="gold", group="rotas")``):
        # the Shape rule. Track bypassed it, so they were accepted and dropped.
        defaults = getattr(type(self), '_shape_defaults', None) or {}
        if color is None and 'color' in defaults:
            color = defaults['color']
        if visual is None and 'visual' in defaults:
            visual = defaults['visual']
        if group is None and 'group' in defaults:
            group = defaults['group']
        styled = any(v is not None for v in (color, visual, line_width))
        if visible is None:
            visible = bool(styled)
        visible = _expect_flag(visible, "Track visible")
        want_draw = visible
        if layer is _USE_LAYER_SENTINEL:
            layer = _USE_LAYER_DEFAULT if (_register and want_draw) else None

        super().__init__(
            layer=layer, group=group, visual=visual, color=color,
            line_width=line_width,
        )
        # Stroke-type: prototype fill is white. color= clears it via set_color;
        # line_width= alone, visible=True, and a bare Track() never call set_color.
        self.fill = None
        self._visible = bool(visible)
        self._path_layer_saved = False
        self._layer_before_visible = None
        if not _register:
            # Alias / internal wrap: drop out of the registry if super() registered us.
            try:
                self._scenacanvas.registry.unregister_draw(self)
            except Exception:
                pass

        self._xs: List[float] = []
        self._ys: List[float] = []
        self._s: List[float] = [0.0]
        self._baked_key = None
        self._rebuilds = 0
        self._read_reversed = False
        self._alias_of = None  # Track we share tables with (reversed view)
        self._rev_view = None
        self._ctrl_points: List[Point] = []
        self._ctrl_local: List[Tuple[float, float]] = []
        self._source_ref = None
        self._source_frozen = False
        self._spec = _spec  # ('eight', w, h) / ('star', ...) / None
        self._mod_zigzag = None  # (amount, waves, kind)
        self._mod_orbit = None   # (radius, laps)
        self._mod_wander = None  # (amount, seed)
        self._smooth = _parse_smooth(smooth)
        self._quality = _parse_quality(quality)
        self._closed = True if closed is None else _expect_flag(closed, "Track closed")
        self._anchored = True
        self._frozen_cx = 0.0
        self._frozen_cy = 0.0
        self._frozen_rot = 0.0
        self._frozen_scale = 1.0

        # --- model dispatch ------------------------------------------------
        try:
            from_vectors = False
            if _spec is None and _ends is None:
                _reject_exclusive_track_raw(
                    points=points, vectors=vectors, radius=radius, source=source,
                )
                if vectors is not None:
                    if center is not None:
                        raise TypeError(
                            "Track(vectors=) takes start=, not center=. "
                            ".center is the geometric middle."
                        )
                    points = _points_from_vectors(vectors)
                    from_vectors = True
                elif start is not None:
                    raise TypeError(
                        "start= is for Track(vectors=…) / Track.wave; "
                        "centered presets use center="
                    )
                if (
                    source is None
                    and points is None
                    and radius is None
                ):
                    # Track() is Track.eight() — sizes-only eight, same defaults.
                    _spec = ("eight", _EIGHT_DEFAULT_WIDTH, _EIGHT_DEFAULT_HEIGHT)
                    self._spec = _spec

            if _ends is not None:
                if start is not None:
                    raise TypeError("Track.line(p1=, p2=) does not take start=")
                p1, p2 = _ends
                self.model = TrackModel.FREE
                self._closed = False if closed is None else _expect_flag(closed, "Track closed")
                self._init_ctrl_vertices((p1, p2))
                self._anchored = _resolve_anchored(
                    placement_given=True, floating=floating, anchored=_anchored,
                )
                return

            if _spec is not None:
                self.model = TrackModel.CIRCLE if _spec[0] == "circle" else TrackModel.FREE
                self._set_defining_parts(
                    "center", "u", "begin", "end", catalog=_TRACK_PARTS,
                )
                with self._batch_update():
                    pose_c = center if center is not None else _default_pose()[0]
                    _init_composite(self.center, pose_c)
                    _init_scalar(self, "u", 0.0)
                    if _spec[0] == "circle":
                        _init_scalar(self, "radius", _spec[1])
                self._anchored = _resolve_anchored(
                    placement_given=center is not None,
                    floating=floating, anchored=_anchored,
                )
                if closed is None:
                    self._closed = _spec[0] in _SPEC_CLOSED
                return

            if source is not None and not isinstance(source, (list, tuple)):
                # Track(other_shape) / Track(sprite) live derivation.
                from .sprite import Sprite
                if not isinstance(source, Shape) and not isinstance(source, Sprite):
                    raise TypeError(
                        "Track(shape) expected a Shape or Sprite, "
                        f"got {type(source).__name__}"
                    )
                self.model = TrackModel.SHAPE
                self._source_ref = ref(source)
                if closed is None:
                    self._closed = True
                self._set_defining_parts(
                    "center", "u", "begin", "end", catalog=_TRACK_PARTS,
                )
                with self._batch_update():
                    _init_composite(self.center, get_xy(source.center, bare=True))
                    _init_scalar(self, "u", 0.0)
                # Anchored wrap: source translation is a center link.
                # floating=True snapshots pose and keeps outline live.
                if floating is not True:
                    try:
                        self.center @= source.center
                    except Exception:
                        pass
                self._anchored = _resolve_anchored(
                    placement_given=True, floating=floating, anchored=_anchored,
                )
                return

            if radius is not None:
                self.model = TrackModel.CIRCLE
                if _is_linkish(radius):
                    spec_r = radius
                else:
                    spec_r = _finite_number(radius, what="Track.radius")
                self._spec = ("circle", spec_r, 0.0, 360.0)
                self._closed = True if closed is None else _expect_flag(closed, "Track closed")
                pose_c = center if center is not None else _default_pose()[0]
                self._set_defining_parts(
                    "center", "radius", "u", "begin", "end",
                    catalog=_TRACK_PARTS,
                )
                with self._batch_update():
                    _init_composite(self.center, pose_c)
                    _init_scalar(self, "radius", radius)
                    _init_scalar(self, "u", 0.0)
                self._anchored = _resolve_anchored(
                    placement_given=center is not None,
                    floating=floating, anchored=_anchored,
                )
                return

            # FREE from points= / expanded vectors= (or a raw sequence as source)
            raw = points if points is not None else source
            need = "vectors=" if from_vectors else "points="
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                raise ValueError(f"Track({need}) needs at least 2 points")
            self.model = TrackModel.FREE
            self._closed = False if closed is None else _expect_flag(closed, "Track closed")
            linked = any(_is_linkish(p) for p in raw) or bool(_ends)
            if linked:
                self._init_ctrl_vertices(raw)
                self._anchored = _resolve_anchored(
                    placement_given=True, floating=floating, anchored=_anchored,
                )
            else:
                world = [_as_xy_static(p) for p in raw]
                lxs = [p[0] for p in world]
                lys = [p[1] for p in world]
                loc_x, loc_y, cx, cy = to_local(lxs, lys)
                self._ctrl_local = list(zip(loc_x, loc_y))
                self._set_defining_parts(
                    "center", "u", "begin", "end", catalog=_TRACK_PARTS,
                )
                if from_vectors:
                    # start= plants u=0; omitted → floating placeholder pose.
                    if start is not None:
                        if callable(start) and not isinstance(start, type):
                            raise TypeError(
                                "Track start= is a placement snapshot, not a link. "
                                "Link the pose with track['center'] @= … "
                                "or track['angle'] @= …, or pass the point itself."
                            )
                        sx, sy = _point_xy_static(start)
                        pose = (sx + cx, sy + cy)
                    else:
                        pose, _ = _default_pose()
                    self._anchored = _resolve_anchored(
                        placement_given=start is not None,
                        floating=floating, anchored=_anchored,
                    )
                    with self._batch_update():
                        _init_composite(self.center, pose)
                        _init_scalar(self, "u", 0.0)
                else:
                    self._anchored = _resolve_anchored(
                        placement_given=True, floating=floating, anchored=_anchored,
                    )
                    with self._batch_update():
                        _init_composite(
                            self.center, (cx, cy) if center is None else center,
                        )
                        _init_scalar(self, "u", 0.0)
        finally:
            if getattr(self, "_defining_part_names", None):
                self._init_draw_window(begin, end)
            if floating is None and _anchored is None and not self._anchored:
                # Floats by inference (no placement given): the first
                # placement anchors it (``_note_placed``).
                self._float_mark = self._float_mark_now()
            if angle is not None:
                if callable(angle) and not isinstance(angle, Attribute):
                    self._link_field("angle", angle)   # like every shape's angle=
                else:
                    from .validate import number
                    _pose_rotation_set(self, number(_bare_num(angle) if isinstance(angle, Attribute)
                                                    else angle, "Track angle"))

    def _init_ctrl_vertices(self, raw) -> None:
        """Defining vertices; ``center`` is Derivate (centroid), baked on flatten."""
        for i, _p in enumerate(raw):
            vtx = Point.__new__(Point)
            Point._construct(vtx, attr_name=f"v{i}", owner=self)
            vtx._field_type = FieldType.Defining
            self._ctrl_points.append(vtx)
        with self._batch_update():
            for vtx, p in zip(self._ctrl_points, raw):
                _init_composite(vtx, p)
            # The centroid now, not a placeholder: the first read of ``center``
            # must not see (0, 0) before any refresh (G11).
            world = [_pulled_xy(v) for v in self._ctrl_points]
            n = float(len(world)) or 1.0
            _init_composite(self.center, (sum(q[0] for q in world) / n, sum(q[1] for q in world) / n))
            _init_scalar(self, "u", 0.0)
        self._set_defining_parts("u", "begin", "end", catalog=_TRACK_PARTS)
        self.center._derivate_live = True
        # A live Derivate needs Defining writes (the points) to dirty the track,
        # or ``center`` lags a move by one refresh (G11).
        self.center._flag_pull_consumers()

    def _init_draw_window(self, begin, end) -> None:
        """Presentation window. Not in the bake key. Defaults 0..1."""
        if callable(begin) and not isinstance(begin, type):
            _init_scalar(self, "begin", begin)
        else:
            if isinstance(begin, Attribute):
                begin = begin.value
            _init_scalar(
                self, "begin",
                0.0 if begin is None else _clamp01(_finite_number(begin, what="Track.begin")),
            )
        if callable(end) and not isinstance(end, type):
            _init_scalar(self, "end", end)
        else:
            if isinstance(end, Attribute):
                end = end.value
            _init_scalar(
                self, "end",
                1.0 if end is None else _clamp01(_finite_number(end, what="Track.end")),
            )

    def _write_field(self, name: str, value) -> None:
        # begin / end (finite, clamped to 0..1) and radius (a finite size) are
        # slot rules (ScalarSlot out_of_range / magnitude), shared with links.
        super()._write_field(name, value)
        # Circle/arc radius is baked into the polyline (pose is applied later).
        # A bare scalar write does not mark the track dirty, so an already
        # sampled track would keep the old radius until something else rebuilt.
        if name == "radius":
            host = self._pose_host()
            if host._xs:
                host._invalidate_bake()

    # -- defining / derivate ------------------------------------------------

    def _set_defining_parts(self, *defining: str, catalog=()) -> None:
        self._mark_defining_parts(*defining, catalog=catalog)

    def _materialize_derivate_part(self, name: str) -> None:
        if name in ("length", "cursor", "center"):
            with self._no_update():
                self._update_impl()

    # -- geometry key / bake ------------------------------------------------

    def _sps(self) -> int:
        n_ctrl = max(2, len(self._ctrl_local) or len(self._ctrl_points) or 8)
        waves = None if self._mod_zigzag is None else self._mod_zigzag[1]
        laps = None if self._mod_orbit is None else self._mod_orbit[1]
        base = samples_per_segment_for(self._quality)
        return min_samples_for_modifiers(
            base, n_ctrl=n_ctrl, closed=self._closed,
            zigzag_waves=waves, orbit_laps=laps,
        )

    def _ctrl_world_xy(self) -> List[Tuple[float, float]]:
        if self._ctrl_points:
            # Linked verts (lambda / @=) need pull — bare floats stay stale.
            return [_pulled_xy(p) for p in self._ctrl_points]
        if self._ctrl_local:
            cx, cy = get_xy(self.center, bare=True)
            # Local controls are already centroid-relative; do not apply pose
            # (pose is applied at sample). Return local — caller decides.
            return list(self._ctrl_local)
        return []

    def _geom_key(self):
        mods = (self._mod_zigzag, self._mod_orbit, self._mod_wander)
        q = self._quality
        sm = self._smooth
        cl = self._closed
        if self.model == TrackModel.CIRCLE:
            r = _bare_num(self.radius) if "radius" in getattr(self, "_defining_part_names", {"radius"}) or hasattr(self, "radius") else 0.0
            try:
                r = _bare_num(self.radius)
            except Exception:
                r = 0.0
            spec = self._spec
            return ("circle", round(r, 6), spec, sm, cl, q, mods)
        if self.model == TrackModel.SHAPE:
            src = self._live_source()
            if src is None:
                return ("shape-frozen", id(self._xs), mods)
            try:
                verts, closed = shape_outline(src, samples=self._sps() * 2)
            except Exception:
                return ("shape-err", mods)
            if not verts:
                return ("shape-empty", mods)
            cx = sum(p[0] for p in verts) / len(verts)
            cy = sum(p[1] for p in verts) / len(verts)
            rel = tuple((round(p[0] - cx, 4), round(p[1] - cy, 4)) for p in verts)
            return ("shape", rel, closed, q, mods)
        if self._spec is not None:
            return ("spec", self._spec, sm, cl, q, mods)
        if self._ctrl_points:
            world = [_pulled_xy(p) for p in self._ctrl_points]
            cx = sum(p[0] for p in world) / len(world)
            cy = sum(p[1] for p in world) / len(world)
            rel = tuple((round(p[0] - cx, 5), round(p[1] - cy, 5)) for p in world)
            return ("free-pts", rel, sm, cl, q, mods)
        return ("free-local", tuple((round(x, 6), round(y, 6)) for x, y in self._ctrl_local),
                sm, cl, q, mods)

    def _live_source(self):
        wr = self._source_ref
        if wr is None:
            return None
        src = wr()
        if src is None:
            return None
        if getattr(src, "_destroyed", False) or not getattr(src, "is_alive", True):
            return None
        return src

    def _flatten_now(self) -> None:
        sps = self._sps()
        closed = self._closed
        xs: List[float] = []
        ys: List[float] = []

        if self.model == TrackModel.SHAPE:
            src = self._live_source()
            if src is None:
                if self._xs:
                    self._source_frozen = True
                    return
                xs, ys = [0.0], [0.0]
                closed = True
            else:
                verts, closed = shape_outline(src, samples=max(16, sps * 2))
                self._closed = closed
                if not verts:
                    xs, ys = [0.0], [0.0]
                else:
                    cx, cy = _pulled_xy(src.center)
                    xs = [p[0] - cx for p in verts]
                    ys = [p[1] - cy for p in verts]
        elif self.model == TrackModel.CIRCLE or (self._spec and self._spec[0] == "circle"):
            r = abs(_bare_num(self.radius)) if self.model == TrackModel.CIRCLE else abs(float(self._spec[1]))
            n = max(12, sps * 4)
            fa, ta = 0.0, 360.0
            if self._spec and len(self._spec) >= 4 and self._spec[0] == "circle":
                fa, ta = float(self._spec[2]), float(self._spec[3])
            elif self._spec and self._spec[0] == "arc":
                # Live radius wins. _spec[1] is the construction snapshot and
                # would ignore arc.radius = … after the first sample.
                if self.model != TrackModel.CIRCLE:
                    r = abs(float(self._spec[1]))
                fa, ta = float(self._spec[2]), float(self._spec[3])
                n = max(8, sps * 3)
            sweep = ta - fa
            full = abs(abs(sweep) - 360.0) < 1e-4 or abs(sweep) >= 360.0 - 1e-4
            closed = full if self._spec and self._spec[0] == "arc" else self._closed
            self._closed = closed
            count = n if closed else n + 1
            for i in range(count):
                t = i / n
                a = math.radians(fa + sweep * t)
                xs.append(r * math.cos(a))
                ys.append(r * math.sin(a))
        elif self._spec is not None:
            xs, ys, closed = _preset_local(self._spec, sps)
            self._closed = closed
        elif self._ctrl_points:
            world = [_pulled_xy(p) for p in self._ctrl_points]
            wx, wy = [p[0] for p in world], [p[1] for p in world]
            loc_x, loc_y, cx, cy = to_local(wx, wy)
            self._takein_live_derivate("center", (cx, cy))
            fx, fy = flatten_controls(
                list(zip(loc_x, loc_y)),
                closed=closed, smooth=self._smooth, samples_per_segment=sps,
            )
            xs, ys = fx, fy
        else:
            fx, fy = flatten_controls(
                self._ctrl_local,
                closed=closed, smooth=self._smooth, samples_per_segment=sps,
            )
            xs, ys = fx, fy

        if self._mod_zigzag or self._mod_orbit or self._mod_wander:
            waves = 0.0 if self._mod_zigzag is None else abs(float(self._mod_zigzag[1]))
            laps = 0.0 if self._mod_orbit is None else abs(float(self._mod_orbit[1]))
            need = max(len(xs), int(max(waves, laps, 1.0) * 8.0))
            xs, ys = densify_polyline(xs, ys, closed=closed, n=need)

        xs, ys = self._apply_modifiers(xs, ys, closed)
        if self._local_mirror():
            ys = [-y for y in ys]
        self._xs = [float(x) for x in xs]
        self._ys = [float(y) for y in ys]
        self._s = arc_length_table(self._xs, self._ys, closed=self._closed)
        self._rebuilds += 1
        _geom_path_cache_set(self, None, None)

    def _apply_modifiers(self, xs, ys, closed):
        if not xs:
            return xs, ys
        s = arc_length_table(xs, ys, closed=closed)
        if self._mod_zigzag is not None:
            amt, waves, kind = self._mod_zigzag
            offs = zigzag_amounts(len(xs), amount=amt, waves=waves, kind=kind, closed=closed)
            xs, ys = apply_offsets(xs, ys, offs, closed=closed)
            s = arc_length_table(xs, ys, closed=closed)
        if self._mod_orbit is not None:
            rad, laps = self._mod_orbit
            xs, ys = orbit_displacements(xs, ys, s, radius=rad, laps=laps, closed=closed)
            s = arc_length_table(xs, ys, closed=closed)
        if self._mod_wander is not None:
            amt, seed = self._mod_wander
            offs = wander_offsets(len(xs), amount=amt, seed=seed)
            xs, ys = apply_offsets(xs, ys, offs, closed=closed)
        return xs, ys

    def _ensure_samples(self) -> None:
        host = self._table_host()
        if host.model == TrackModel.SHAPE and not host._source_frozen:
            # Source is not an owned part — pull outline on read (cold: skip if
            # nobody samples). geom_key still skips flatten when only pose moved.
            with host._no_update():
                host._update_impl()
            return
        if host._ctrl_points:
            # Linked control points may not dirty the Track (formula AST often
            # misses nested center.x/y). Cold-pull like SHAPE: key compares
            # pulled world verts; unread paths stay cheap.
            with host._no_update():
                host._update_impl()
            return
        if host._dirty:
            host._resolve_structural()
        elif not host._xs:
            with host._no_update():
                host._update_impl()

    def _update_impl(self) -> None:
        if self._float_mark is not None:
            # A write dirtied an inferred float that is being ridden
            # (``_list_floating_ride`` flags it): a moved center anchors it.
            self._settle_inferred()
        key = (self._geom_key(), self._local_mirror())
        if key != self._baked_key or not self._xs:
            self._flatten_now()
            self._baked_key = key
        if self._ctrl_points:
            # The centroid moves with a translation that does not reflatten
            # (the key is centroid-relative): publish it on every refresh.
            world = [_pulled_xy(p) for p in self._ctrl_points]
            n = float(len(world))
            self._takein_live_derivate(
                "center", (sum(p[0] for p in world) / n, sum(p[1] for p in world) / n))
        self._refresh_length()
        self._refresh_cursor()
        view = self._rev_view
        if view is not None:
            # The view is unregistered: its cursor refreshes with its host.
            view._refresh_cursor()

    def _refresh_length(self) -> None:
        local = self._s[-1] if self._s else 0.0
        self.length = float(local) * abs(float(self._scale))

    def _refresh_cursor(self) -> None:
        # Cold until first read/link: the slot is missing from __dict__.
        cur = self.__dict__.get("cursor")
        if cur is None:
            return
        # Sample the tables ``_update_impl`` just built. ``at()`` would re-enter
        # ``_ensure_samples`` → ``_update_impl`` for a control-point track and
        # recurse forever (G11).
        host = self._table_host()
        if not host._xs:
            return
        lx, ly = curve_sample(host._xs, host._ys, host._s, float(_bare_num(self.u)),
                              closed=host._closed, reversed=self._read_reversed)
        cur._takein(self._world_of(lx, ly))

    def _domain_aabb(self):
        """World AABB of the path for cull: pose applied (rotation, scale, flips) plus the stroke.

        The local bounds are cached per bake (``_rebuilds``), so a frame's cull
        is four corner transforms.
        """
        host = self._table_host()
        xs, ys, _s, _closed, _rev = self._tables()
        if not xs:
            cx, cy = self._pose_xy()
            return (cx, cy, cx, cy)
        stamp = int(getattr(host, "_rebuilds", 0) or 0)
        cached = host.__dict__.get("_local_bounds")
        if cached is None or cached[0] != stamp:
            cached = (stamp, min(xs), min(ys), max(xs), max(ys))
            host.__dict__["_local_bounds"] = cached
        _stamp, x1, y1, x2, y2 = cached
        pts = [self._world_of(x, y) for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
        try:
            pad = 0.5 * abs(float(self.line_width)) * abs(float(host._scale))
        except Exception:  # noqa: BLE001
            pad = 0.0
        return (min(p[0] for p in pts) - pad, min(p[1] for p in pts) - pad,
                max(p[0] for p in pts) + pad, max(p[1] for p in pts) + pad)

    def _local_mirror(self) -> bool:
        """An odd number of flips: the path is mirrored in its own frame.

        A flip turns the heading (``flip_x``: ``180 − θ``, ``flip_y``: ``−θ``)
        and negates local y (baked into the tables at flatten), so every
        reader of the pose — draw, ``at``, tangents, collision, riders — sees a
        true mirror about the center.
        """
        host = self._pose_host()
        return bool(getattr(host, "_flip_x", False)) != bool(getattr(host, "_flip_y", False))

    def _mirror_geometry(self, axis: str, *, force: bool = False) -> None:
        rot = float(self._rotation)
        _pose_rotation_set(self, (180.0 - rot) if axis == "x" else -rot)
        self._invalidate_bake()

    def _pose_moved(self) -> None:
        """A pose verb changed rotation / scale: world parts (cursor, length) refresh."""
        self.update()

    def _orbit_points(self, about, image) -> Optional[Tuple[float, float]]:
        """Control-point track, off-center pivot: the center's image under the verb.

        Its ``center`` is the Derivate centroid of world points, so the verb
        turns / scales about the center (pose) and the points then move by the
        center's orbit — a rigid turn about ``about``. ``None`` otherwise.
        """
        if about is None or not self._table_host()._ctrl_points:
            return None
        cx, cy = self._pose_xy()
        px, py = get_xy(about, bare=True)       # a tuple too: NaN / junk refused (SA6)
        if abs(px - cx) < 1e-12 and abs(py - cy) < 1e-12:
            return None
        nx, ny = image(cx, cy, float(px), float(py))
        return (nx - cx, ny - cy)

    def rotate_by(self, angle, *args, **kwargs):
        """Turn by ``angle`` degrees about a pivot (default: center). Same verb as every Graphic;
        a control-point track turns about the center and its points orbit the pivot."""
        shift = None
        if kwargs.get("time") is None and kwargs.get("speed") is None:
            a = math.radians(_number(angle, "rotate_by angle"))
            shift = self._orbit_points(kwargs.get("about"), lambda cx, cy, px, py: (
                px + (cx - px) * math.cos(a) - (cy - py) * math.sin(a),
                py + (cx - px) * math.sin(a) + (cy - py) * math.cos(a)))
            if shift is not None:
                kwargs["about"] = None
        out = super().rotate_by(angle, *args, **kwargs)
        if shift is not None:
            self._move_by(shift[0], shift[1], force=kwargs.get("force", False))
        if kwargs.get("time") is None and kwargs.get("speed") is None:
            self._pose_moved()
        return out

    def scale_by(self, factor, *args, **kwargs):
        """Scale by ``factor`` about a pivot (default: center). Same verb as every Graphic;
        a control-point track scales about the center and its points follow the pivot."""
        shift = None
        if kwargs.get("time") is None:
            k = _number(factor, "scale_by factor")
            shift = self._orbit_points(kwargs.get("about"), lambda cx, cy, px, py: (
                px + (cx - px) * k, py + (cy - py) * k))
            if shift is not None:
                kwargs["about"] = None
        out = super().scale_by(factor, *args, **kwargs)
        if shift is not None:
            self._move_by(shift[0], shift[1], force=kwargs.get("force", False))
        if kwargs.get("time") is None:
            self._pose_moved()
        return out

    # -- sampling -----------------------------------------------------------

    def _table_host(self) -> "Track":
        """The Track that owns the tables (the host of a reversed() view).

        ``is not None``, never ``or``: a destroyed host is falsy
        (``Entity.__bool__``) and ``or`` would fall back to the view, whose
        own tables are empty (R9 in Testing Design)."""
        return self._alias_of if self._alias_of is not None else self

    def _pose_host(self) -> "Track":
        return self._table_host()

    def _world_of(self, lx: float, ly: float) -> Tuple[float, float]:
        host = self._pose_host()
        cx, cy = host._pose_xy()
        return apply_pose(
            lx, ly,
            cx=cx, cy=cy,
            rotation_deg=float(host._rotation),
            scale=float(host._scale),
        )

    def _pose_xy(self) -> Tuple[float, float]:
        """Live pose origin. Re-pull inbound ``center`` formulas on every sample."""
        host = self._pose_host()
        if host.model == TrackModel.SHAPE and not host.is_floating:
            src = host._live_source()
            if src is not None:
                return _pulled_xy(src.center)
        if host._ctrl_points:
            # The centroid of the world points, read fresh (``center`` is its Derivate).
            world = [_pulled_xy(p) for p in host._ctrl_points]
            n = float(len(world))
            return (sum(q[0] for q in world) / n, sum(q[1] for q in world) / n)
        return _pulled_xy(host.center)

    def _invalidate_bake(self) -> None:
        host = self._pose_host()
        host._baked_key = None
        host._dirty = True
        um = getattr(getattr(host, "_scena_system", None), "update_manager", None)
        if um is not None:
            um.mark_dirty(host)

    def _tables(self):
        host = self._table_host()
        host._ensure_samples()
        return host._xs, host._ys, host._s, host._closed, self._read_reversed

    def at(self, u: float) -> Tuple[float, float]:
        """World point at ``u`` along the track (0 = start, 1 = end), with the track's pose applied."""
        return self._at(_u_arg(u, "Track.at"))

    def _at(self, u: float) -> Tuple[float, float]:
        """``at`` without the argument check (engine loops pass floats)."""
        xs, ys, s, closed, rev = self._tables()
        lx, ly = curve_sample(xs, ys, s, u, closed=closed, reversed=rev)
        return self._world_of(lx, ly)

    def local_at(self, u: float) -> Tuple[float, float]:
        """Point at ``u`` in the track's own frame (no move / rotate / scale applied)."""
        u = _u_arg(u, "Track.local_at")
        xs, ys, s, closed, rev = self._tables()
        return curve_sample(xs, ys, s, u, closed=closed, reversed=rev)

    def tangent_at(self, u: float) -> Tuple[float, float]:
        """Unit direction of travel ``(dx, dy)`` at ``u`` (world frame); ``(0, 0)`` on a degenerate span."""
        u = _u_arg(u, "Track.tangent_at")
        xs, ys, s, closed, rev = self._tables()
        tx, ty = curve_tangent(xs, ys, s, u, closed=closed, reversed=rev)
        host = self._pose_host()
        vx, vy = apply_pose_vec(
            tx, ty, rotation_deg=float(host._rotation), scale=float(host._scale),
        )
        mag = math.hypot(vx, vy)
        if mag <= 1e-18:
            return (0.0, 0.0)
        return (vx / mag, vy / mag)

    def angle_at(self, u: float) -> float:
        """Heading in degrees at ``u`` (0 = +x, counter-clockwise), e.g. to face the way of travel."""
        tx, ty = self.tangent_at(u)
        if tx == 0.0 and ty == 0.0:
            return 0.0
        return math.degrees(math.atan2(ty, tx))

    def sample_span(self, a: float, b: float, n: int = 32) -> List[Tuple[float, float]]:
        """``n`` world points from ``u = a`` to ``u = b`` (default 32), e.g. to draw part of the track."""
        a, b = _u_arg(a, "Track.sample_span a"), _u_arg(b, "Track.sample_span b")
        n = _sample_count(n, "Track.sample_span n")
        xs, ys, s, closed, rev = self._tables()
        local = curve_span(xs, ys, s, a, b, closed=closed, reversed=rev, n=n)
        return [self._world_of(x, y) for x, y in local]

    def spaced_points(self, n: int) -> List[Tuple[float, float]]:
        """Return ``n`` world ``(x, y)`` tuples evenly spaced by arc length.

        Closed tracks sample at ``u = i/n`` (no duplicate wrap at ``u=1``).
        Open tracks sample from ``u=0`` to ``u=1`` inclusive.
        """
        n = _sample_count(n, "Track.spaced_points n")
        if n == 1:
            return [self._at(0.0)]
        _, _, _, closed, _ = self._tables()
        if closed:
            return [self._at(i / float(n)) for i in range(n)]
        denom = float(n - 1)
        return [self._at(i / denom) for i in range(n)]

    @property
    def is_floating(self) -> bool:
        """``True``: the track rides with whoever follows it (relative); ``False``: fixed in the world.

        Writing it is final; a sizes-only track not written here anchors
        when it is given a place (link / write / move of ``center``)."""
        host = self._pose_host()
        if host._float_mark is not None:
            host._settle_inferred()
        return not host._anchored

    @is_floating.setter
    def is_floating(self, value) -> None:
        host = self._pose_host()
        host._anchored = not _expect_flag(value, 'is_floating')
        host._float_mark = None           # said by the author: no placement flips it
        if host._anchored:
            host._pull_floating_rides()

    # -- placement anchors an inferred float ---------------------------------
    # A track made without a placement (``Track.circle(radius=120)``) floats
    # by inference. Giving it a place later -- a link on ``center`` (or its
    # x / y), ``center =``, ``move_to``, or any move of its center -- is the
    # placement it was made without: it anchors, as ``center=`` would have.
    # Until 2026-10 the track kept floating and its riders ignored the place
    # (``orbit["center"] @= lambda: earth.center`` did nothing, KN9).
    # ``floating=`` / ``is_floating =`` said by the author never flip.

    # ``(center.__dict__, x, y)`` at construction while the float is inferred,
    # else None. Class default: construction runs before the inference.
    _float_mark = None

    def _float_mark_now(self):
        d = self.__dict__["center"].__dict__
        return (d, d.get("x"), d.get("y"))

    def _note_placed(self) -> None:
        """An author placement of the center (link, ``center =``, ``move_to``)."""
        host = self._pose_host()
        if host._float_mark is not None:
            host._float_mark = None
            host._anchored = True
            host._pull_floating_rides()

    def _list_floating_ride(self, ride) -> None:
        """``move_along`` began a floating ride here (weakly held; ride start only).

        An inferred float also takes a pull consumer: a write to its center
        (``center.x =``, ``center << p``, ``move_by``, a tween) then dirties
        it, and the ride's next sample refreshes it (``_update_impl``), which
        anchors a moved center. No check on a clean tick."""
        rides = self.__dict__.get("_floating_rides")
        if rides is None:
            from weakref import WeakSet
            rides = self._floating_rides = WeakSet()
        rides.add(ride)
        if self._float_mark is not None:
            self._flag_pull_consumers()

    def _pull_floating_rides(self) -> None:
        """Anchored now: rides that began floating join the track where it is."""
        rides = self.__dict__.get("_floating_rides")
        if rides:
            for ride in tuple(rides):
                ride.floating = False
            rides.clear()

    def _settle_inferred(self) -> None:
        """The lazy half of ``_note_placed``: the center moved since construction
        by a spelling with no hook of its own (``center.x =``, ``center << p``,
        ``move_by``, a tween)."""
        # Bare floats: while inferred the center has no link (a link anchors
        # at once). Asked at ride start, on ``is_floating`` and on a refresh
        # after a write (``_update_impl``), never on a clean tick.
        d, x0, y0 = self._float_mark
        if d.get("x") != x0 or d.get("y") != y0:
            self._note_placed()

    def _part_link_changed(self, node) -> None:
        """A link on ``center`` (or ``center.x`` / ``.y``) is a placement."""
        if self._float_mark is None or node._link is None:
            return
        center = self.__dict__.get("center")
        while node is not None and node is not center:
            node = node._owner
        if node is not None:
            self._note_placed()

    @property
    def smooth(self) -> float:
        """Corner rounding: 0 = straight polyline, 1 = smooth curve (default). Writable."""
        host = self._table_host()
        return host._smooth

    @smooth.setter
    def smooth(self, value) -> None:
        host = self._table_host()
        host._smooth = _parse_smooth(value)
        self._invalidate_bake()

    @property
    def quality(self) -> str:
        """Sampling detail: ``"high"`` (default) or ``"low"`` (cheaper). Writable."""
        host = self._table_host()
        return host._quality

    @quality.setter
    def quality(self, value) -> None:
        host = self._table_host()
        host._quality = _parse_quality(value)
        self._invalidate_bake()

    @property
    def closed(self) -> bool:
        """Whether the track loops back to its start. Read-only."""
        host = self._table_host()
        return host._closed

    def reversed(self) -> "Track":
        """O(1) view: same tables, opposite read direction. ``reversed().reversed()`` is identity."""
        if self._read_reversed and self._alias_of is not None:
            return self._alias_of
        root = self._table_host()
        if root._rev_view is not None and not getattr(root._rev_view, "_destroyed", False):
            return root._rev_view
        if getattr(root, "_destroyed", False):
            # A new view would enter the graph for a dead track (A7).
            from .entity import _refuse_if_destroyed
            _refuse_if_destroyed(root, "reversed")
        view = object.__new__(_ReversedTrack)
        # Set first: the view's pose fields read the host (_HostField).
        object.__setattr__(view, "_alias_of", root)
        # Minimal Shape init, unregistered.
        from .style import PaintState
        from .entity import Graphic
        PaintState.__init__(view)
        Graphic._construct(view, layer=None, register=False)
        view.fill = None
        view._visible = False
        view.model = root.model
        view._xs = root._xs
        view._ys = root._ys
        view._s = root._s
        view._baked_key = root._baked_key
        view._rebuilds = 0
        view._read_reversed = True
        view._alias_of = root
        view._rev_view = None
        view._ctrl_points = root._ctrl_points
        view._ctrl_local = root._ctrl_local
        view._source_ref = root._source_ref
        view._source_frozen = root._source_frozen
        view._spec = root._spec
        view._mod_zigzag = root._mod_zigzag
        view._mod_orbit = root._mod_orbit
        view._mod_wander = root._mod_wander
        view._smooth = root._smooth
        view._quality = root._quality
        view._closed = root._closed
        view._anchored = root._anchored
        view._frozen_cx = root._frozen_cx
        view._frozen_cy = root._frozen_cy
        view._frozen_rot = root._frozen_rot
        view._frozen_scale = root._frozen_scale
        # center / radius / length / pose are the host's (_ReversedTrack): not
        # marked here — marking would rewrite the host's own parts.
        view._set_defining_parts("u", "begin", "end", catalog=("u", "begin", "end", "cursor"))
        _init_scalar(view, "u", 0.0)
        _init_scalar(view, "begin", 0.0)
        _init_scalar(view, "end", 1.0)
        root._rev_view = view
        return view

    # -- modifiers (in-place, return self) ----------------------------------

    def zigzag(self, amount: float = 20.0, waves: float = 6.0, *, kind: str = "sine") -> "Track":
        """Add a side-to-side wiggle along the track. Returns the track.

        Args:
            amount: wiggle size in design units (default 20).
            waves: how many wiggles over the whole track (default 6).
            kind: ``"sine"`` (default) or ``"saw"``.
        """
        host = self._table_host()
        k = str(kind).lower()
        if k not in ("sine", "saw"):
            raise ValueError('zigzag kind= must be "sine" or "saw"')
        from .validate import number
        host._mod_zigzag = (number(amount, "zigzag amount"), number(waves, "zigzag waves"), k)
        self._invalidate_bake()
        return self

    def orbit(self, radius: float = 20.0, laps: float = 8.0) -> "Track":
        """Add small loops around the path (a spiral ride). Returns the track.

        Args:
            radius: loop radius in design units (default 20).
            laps: loops over the whole track (default 8).
        """
        host = self._table_host()
        from .validate import number
        host._mod_orbit = (number(radius, "orbit radius"), number(laps, "orbit laps"))
        self._invalidate_bake()
        return self

    def wander(self, amount: float = 6.0, seed: int = 0) -> "Track":
        """Add a smooth random drift around the path. Returns the track.

        Args:
            amount: drift size in design units (default 6).
            seed: whole number; the same seed gives the same drift.
        """
        host = self._table_host()
        from .validate import number
        seed = as_payload(seed)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError(f"wander seed must be a whole number, got {type(seed).__name__}")
        host._mod_wander = (number(amount, "wander amount"), seed)
        self._invalidate_bake()
        return self

    # -- clone / takein / pose ----------------------------------------------

    def _travel_vertices(self) -> List[Tuple[float, float]]:
        """Vertices of the drawn table in the track's own frame, in travel order.

        Always the host's tables (a ``reversed()`` view's own ``_xs`` is a
        stale construction-time alias), read backwards on a view.
        """
        host = self._table_host()
        host._ensure_samples()
        local = [(float(x), float(y)) for x, y in zip(host._xs, host._ys)]
        if self._read_reversed and local:
            # sample(reversed=True) reads u as 1 − u.
            local = local[:1] + local[:0:-1] if host._closed else local[::-1]
        return local

    def _clone_geometry(self, **kwargs) -> "Track":
        host = self._table_host()
        # Bake the view as the author sees it (reversed() included; links and
        # modifiers dropped): the vertices of the drawn table, so the copy draws
        # the same polyline, in its own frame — the pose stays pose on the copy
        # (``_clone_pose_from``) and is not baked into the points as well.
        closed = bool(host._closed)
        mirror = -1.0 if self._local_mirror() else 1.0   # the copy re-mirrors from its flags
        local = [(x, mirror * y) for x, y in self._travel_vertices()]
        if len(local) < 2:
            local = [(0.0, 0.0), (1.0, 0.0)]
        ox, oy = self._pose_xy()
        kw = dict(kwargs)
        kw.setdefault("closed", closed)
        kw.setdefault("smooth", 0.0)
        cloned = Track(points=[(ox + x, oy + y) for x, y in local], center=(ox, oy), **kw)
        # Local to the pose origin, not to the samples' centroid: the copy turns
        # and scales about the same point as the source.
        cloned._ctrl_local = local
        cloned._invalidate_bake()
        if "floating" not in kw:
            cloned._anchored = not host.is_floating     # settles a moved inferred float
            if host._float_mark is not None:
                cloned._float_mark = cloned._float_mark_now()
        # Effective window: a reversed() view does not own begin/end.
        a, b, _full = self._draw_window()
        cloned.begin = a
        cloned.end = b
        return cloned

    def _clone_pose_from(self, source) -> None:
        # A reversed() view reads its host's pose (its own slots stay identity).
        super()._clone_pose_from(source._pose_host())
        self._invalidate_bake()
        self._pose_moved()

    def clone(
        self,
        *,
        floating=None,
        center=None,
        scale: float = 1.0,
        layer=_USE_LAYER_DEFAULT,
        group=_COPY_GROUPS,
        frame=None,
    ):
        """Freeze geometry. ``clone()`` copies ``is_floating``; ``clone(floating=)`` overrides."""
        copy = super().clone(
            center=center, scale=scale, layer=layer, group=group, frame=frame,
        )
        if floating is not None:
            copy.is_floating = bool(floating)
        return copy

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> "Track":
        host = self._table_host()
        if host._ctrl_points:
            for vtx in host._ctrl_points:
                _ensure_writable(vtx, "move_by", force=force)
            with host._batch_update():
                for vtx in host._ctrl_points:
                    if dx:
                        vtx.x += dx
                    if dy:
                        vtx.y += dy
            return self
        if not force and not host._requires_pull_invalidate():
            # Nothing reads the center through a link: a bare float write
            # (no try: an error here is the slow path's error too, GX8).
            cx = _bare_attr(host.center.x)
            cy = _bare_attr(host.center.y)
            if dx is not None:
                cx = cx + float(dx)
            if dy is not None:
                cy = cy + float(dy)
            _takein_xy_float(host.center, cx, cy)
            return self
        _ensure_writable(host.center, "move_by", force=force)
        cx, cy = get_xy(host.center, bare=True)
        nx = cx + (0.0 if dx is None else float(dx))
        ny = cy + (0.0 if dy is None else float(dy))
        host.center._takein((nx, ny))
        return self

    def _move_to(self, x: float, y: float, *, force: bool = False) -> "Track":
        host = self._table_host()
        cx, cy = get_xy(host.center, bare=True)
        dx = None if x is None else float(x) - cx
        dy = None if y is None else float(y) - cy
        out = self._move_by(dx or 0.0, dy or 0.0, force=force)
        self._note_placed()       # a placement even onto the spot it has
        return out

    def _parts_written_by_drag(self) -> Tuple:
        host = self._table_host()
        if host._ctrl_points:
            return tuple(host._ctrl_points)
        return (host.center,)

    def _parts_written_by_wheel_rotate(self) -> Tuple:
        return ()

    def _takein_impl(self, other: "Track") -> None:
        if not isinstance(other, Track):
            raise TypeError(
                f"Track << expected a Track, got {type(other).__name__}: a copy "
                "reproduces its source. For a path along a shape build one: "
                "Track(shape).")
        # The drawn table has the source's mirror baked in; the copy re-mirrors
        # from the flags it takes (``_clone_pose_from`` below), as clone() does
        # (``_clone_geometry``). Without this a flipped source drew twice
        # mirrored, i.e. unflipped (GX10 in Testing Design).
        mirror = -1.0 if other._local_mirror() else 1.0
        self._ctrl_local = [(x, mirror * y) for x, y in other._travel_vertices()]
        self._ctrl_points = []
        # A copy is a free points= track of the source's travel path (like
        # clone()): drop this track's own preset / circle / live-shape source,
        # which _flatten_now would otherwise keep drawing (D21).
        self._spec = None
        self._source_ref = None
        if self.model != TrackModel.FREE:
            self.model = TrackModel.FREE
            self._set_defining_parts("center", "u", "begin", "end", catalog=_TRACK_PARTS)
            self._invalidate_bare_reads()
        self._closed = other._table_host()._closed
        self._smooth = 0.0
        src = other._pose_host()
        self._anchored = not src.is_floating      # settles a moved inferred float
        self.center._takein(other.center)
        self._float_mark = None if src._float_mark is None else self._float_mark_now()
        a, b, _full = other._draw_window()
        self.begin = a
        self.end = b
        self.u = float(other.u)          # Defining like begin / end (D19: a copy dropped it)
        self._clone_pose_from(other)      # copies carry the pose (Geometry contract C7)
        self._baked_key = None
        self._dirty = True

    # -- visibility (Point-style promote / demote) ---------------------------

    @property
    def visible(self) -> bool:
        """Draw the track (``True``) or keep it an invisible motion path (``False``, the default for unstyled tracks)."""
        return self._visible

    @visible.setter
    def visible(self, value) -> None:
        """Show/hide; promote ``layer=None`` → default when shown, restore on hide.

        Reversed / alias views never join a draw layer. Same idea as ``Point.visible``.
        """
        _refuse_if_destroyed(self, "visible")
        from .validate import expect_bool
        value = expect_bool(value, "Track.visible")
        if getattr(self, "_alias_of", None) is not None:
            if value != self._visible:
                self._visible = value
            return
        if value:
            if not self._path_layer_saved:
                self._layer_before_visible = self._layer
                self._path_layer_saved = True
            if self._layer is None:
                self.layer = self._scenacanvas.registry.layers.default
        else:
            if self._path_layer_saved:
                prev = self._layer_before_visible
                self._path_layer_saved = False
                self._layer_before_visible = None
                if self._layer != prev:
                    self.layer = prev
            elif self._layer is not None:
                # Constructed on a layer (styled / explicit) — drop off the
                # draw list while hidden so idle overlay does not scan it.
                self.layer = None
        if value != self._visible:
            self._visible = value
            self._sync_interactive_registry()

    # -- draw / hit ---------------------------------------------------------

    def _draw_window(self) -> Tuple[float, float, bool]:
        """Clamped begin/end and whether the window is the full curve.

        A ``reversed()`` view reads the host window in host parameter space.
        The view's own begin/end slots are not a second window.
        """
        src = self._alias_of if self._alias_of is not None else self
        a = _clamp01(_bare_num(src.begin))
        b = _clamp01(_bare_num(src.end))
        full = a <= 0.0 and b >= 1.0
        return a, b, full

    def _window_contours(self):
        """Local-space stroke contours for the draw window. Empty if nothing to stroke."""
        a, b, full = self._draw_window()
        xs, ys, s, closed, rev = self._tables()
        if full:
            return curve_subpolyline(xs, ys, s, 0.0, 1.0, closed=closed, reversed=rev)
        # a,b are host-u. reversed=True would mirror that span onto the other arc.
        return curve_subpolyline(xs, ys, s, a, b, closed=closed, reversed=False)

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        # Host tables, not self._xs: reversed() shares the lists only until the
        # next rebake, which assigns new list objects on the host.
        xs, ys, s, closed, rev = self._tables()
        n = len(xs)
        if n < 2:
            return
        host = self._pose_host()
        rot = float(host._rotation)
        sc = float(host._scale)
        a, b, full = self._draw_window()
        # Pose (rot/scale) is the CTM. Identity of the bake is ``_rebuilds``,
        # not ``id(xs)`` (that id can be reused after the list is freed).
        key = (
            n, int(getattr(host, "_rebuilds", 0) or 0), closed, rev, full,
            None if full else (round(a, 5), round(b, 5)),
        )
        if self._geom_path is None or self._geom_path_key != key:
            path = skia.Path()
            if full:
                order = range(n - 1, -1, -1) if rev else range(n)
                first = True
                for i in order:
                    if first:
                        path.moveTo(xs[i], ys[i])
                        first = False
                    else:
                        path.lineTo(xs[i], ys[i])
                if closed:
                    path.close()
            else:
                contours = curve_subpolyline(
                    xs, ys, s, a, b, closed=closed, reversed=False,
                )
                if not contours:
                    return
                for contour in contours:
                    if len(contour) < 2:
                        continue
                    path.moveTo(contour[0][0], contour[0][1])
                    for x, y in contour[1:]:
                        path.lineTo(x, y)
            _geom_path_cache_set(self, path, key)
        path = self._geom_path
        skip_fill = not full
        cx, cy = self._pose_xy()
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if rot:
            skia_canvas.rotate(rot)
        if sc != 1.0:
            skia_canvas.scale(sc, sc)
        skia_fill = None if skip_fill else (
            self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
        )
        if skia_fill:
            skia_canvas.drawPath(path, skia_fill)
        skia_line = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
        if skia_line:
            skia_canvas.drawPath(path, skia_line)
        skia_canvas.restore()

    def _hit_test_xy(self, x: float, y: float) -> bool:
        xs, ys, _s, closed, _rev = self._tables()
        n = len(xs)
        if n < 2:
            return False
        hit_r = max(4.0, float(self.line_width) * 0.5 + 3.0)
        hit_r2 = hit_r * hit_r

        def _hit_segments(pts: List[Tuple[float, float]], *, closed: bool) -> bool:
            m = len(pts)
            if m < 2:
                return False
            segs = m if closed else m - 1
            for i in range(segs):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % m]
                abx, aby = bx - ax, by - ay
                denom = abx * abx + aby * aby
                if denom < 1e-18:
                    d2 = _sq(x - ax) + _sq(y - ay)
                else:
                    t = max(0.0, min(1.0, ((x - ax) * abx + (y - ay) * aby) / denom))
                    px, py = ax + t * abx, ay + t * aby
                    d2 = _sq(x - px) + _sq(y - py)
                if d2 <= hit_r2:
                    return True
            return False

        _a, _b, full = self._draw_window()
        if full:
            pts = [self._world_of(xs[i], ys[i]) for i in range(n)]
            return _hit_segments(pts, closed=bool(closed))
        for contour in self._window_contours():
            if len(contour) < 2:
                continue
            pts = [self._world_of(lx, ly) for lx, ly in contour]
            if _hit_segments(pts, closed=False):
                return True
        return False

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """``(rot, scale, line_width, rebuilds, begin, end)`` — stroke tube cache key.

        Center translation keeps extra identical (proxy translate fast-path).
        Bake changes bump ``_rebuilds``; thickness is plain paint, so it must
        live in extra or a stale tube would slide under ``line_width=``.
        ``begin``/``end`` trim the stroked wall without flattening; a live tween
        of the window must invalidate the cached tube.
        """
        host = self._pose_host()
        host._ensure_samples()
        try:
            rot = float(host._rotation)
        except Exception:
            rot = 0.0
        try:
            scale = float(host._scale)
        except Exception:
            scale = 1.0
        try:
            lw = float(self.line_width)
        except Exception:
            lw = 1.0
        rebuilds = int(getattr(host, "_rebuilds", 0) or 0)
        a, b, _full = self._draw_window()
        return (rot, scale, lw, rebuilds, a, b)

    # -- presets ------------------------------------------------------------

    @classmethod
    def line(cls, length=None, angle=None, p1=None, p2=None, *, vec=None, **kwargs) -> "Track":
        """Open segment. Sizes (``length=``/``angle=`` or ``vec=``, optional ``p1=``)
        or two-point (``p1=``/``p2=``). ``p1=`` plants ``u=0``.

        ``angle=`` is the track's heading: the segment is built along +x and
        turned, so ``Track.line(angle=30).angle == 30``.
        """
        _LINE_POINTS_HINT = (
            "Track.line takes length=/angle= or vec= (sizes; optional p1=), "
            "or p1=/p2= (two-point segment). Not points=/vectors=."
        )
        if "center" in kwargs:
            raise TypeError(
                "Track.line takes p1= (the start, u=0), not center=. "
                ".center is the geometric middle. "
                "Sizes form: Track.line(length=, angle=, p1=) or vec=. "
                "To put the middle at (cx, cy), pass p1 half a length back along angle."
            )
        if "points" in kwargs or "vectors" in kwargs:
            raise TypeError(_LINE_POINTS_HINT)
        if length is not None and not isinstance(length, (int, float)):
            if isinstance(length, (tuple, list, Point, Vec2)) or (
                hasattr(length, "x") and hasattr(length, "y")
            ):
                raise TypeError(
                    "Track.line(p1=, p2=) uses keywords, not positional points. "
                    "Track.line(p1=(x, y), p2=(x, y))."
                )
        if p2 is not None and p1 is None:
            raise TypeError("Track.line(p1=, p2=) needs both p1= and p2=")
        if p2 is not None:
            if vec is not None or length is not None or angle is not None:
                raise TypeError(
                    "Track.line(p1=, p2=) does not take length=/angle=/vec="
                )
            kwargs.setdefault("smooth", 0)
            kwargs.setdefault("closed", False)
            return cls(_ends=(p1, p2), **kwargs)
        if vec is not None and (length is not None or angle is not None):
            raise TypeError("Track.line takes vec= or length=/angle=, not both")
        if vec is not None:
            dx, dy = _as_xy_static(vec)
            length = math.hypot(dx, dy)
            angle = math.degrees(math.atan2(dy, dx))
        else:
            if length is None:
                _, unit = _default_pose()
                length = 2.0 * unit
            if angle is None:
                angle = 0.0
            length = float(length)
            angle = float(angle)
        if not math.isfinite(length) or length < 0.0:
            raise ValueError("Track.line length= must be finite and >= 0")
        if not math.isfinite(angle):
            raise ValueError("Track.line angle= must be finite")
        kwargs.setdefault("smooth", 0)
        kwargs.setdefault("closed", False)
        pose = None if p1 is None else _line_center_from_p1(p1, length, angle)
        return cls(_spec=("line", length, 0.0), center=pose, angle=angle, **kwargs)

    @classmethod
    def circle(cls, radius=None, center=None, **kwargs) -> "Track":
        """A circle track, closed.

        Args:
            radius: design units (default: a medium size).
            center: where it sits (omit for a floating track).

        Other keywords (``center=``, ``color=``, ``line_width=``, ``floating=``, …) as in ``Track(...)``.
        """
        if radius is None:
            _, unit = _default_pose()
            radius = unit
        closed = kwargs.pop("closed", True)
        return cls(center=center, radius=radius, closed=closed, **kwargs)

    @classmethod
    def arc(cls, radius=None, from_angle=0.0, to_angle=180.0, center=None, **kwargs) -> "Track":
        """An arc track from ``from_angle`` to ``to_angle`` degrees (open).

        Args:
            radius: design units (default: a medium size).
            from_angle, to_angle: degrees (default 0 → 180).
            center: where it sits.

        Other keywords (``center=``, ``color=``, ``line_width=``, ``floating=``, …) as in ``Track(...)``.
        """
        if radius is None:
            _, unit = _default_pose()
            radius = unit
        from_angle = _finite_number(from_angle, what="Track.arc from_angle")
        to_angle = _finite_number(to_angle, what="Track.arc to_angle")
        kwargs.setdefault("closed", False)
        p = cls(center=center, radius=radius, **kwargs)
        if _is_linkish(radius):
            spec_r = float(_bare_num(radius))
        else:
            spec_r = _finite_number(radius, what="Track.arc radius")
        p._spec = ("arc", spec_r, from_angle, to_angle)
        p._closed = False
        p._baked_key = None
        return p

    @classmethod
    def eight(cls, width=_EIGHT_DEFAULT_WIDTH, height=_EIGHT_DEFAULT_HEIGHT, center=None, **kwargs) -> "Track":
        """A figure-eight track, closed.

        Args:
            width, height: size of the figure in design units.
            center: where it sits.

        Other keywords (``center=``, ``color=``, ``line_width=``, ``floating=``, …) as in ``Track(...)``.
        """
        from .validate import number
        kwargs.setdefault("closed", True)
        return cls(
            _spec=("eight", number(width, "Track.eight width"), number(height, "Track.eight height")),
            center=center, **kwargs,
        )

    @classmethod
    def star(cls, points=5, radius=None, inner=None, center=None, **kwargs) -> "Track":
        """A star-shaped track, closed.

        Args:
            points: number of tips (whole number >= 3, default 5).
            radius: tip radius (default: a medium size).
            inner: valley radius (default 0.4 × radius).
            center: where it sits.

        Other keywords (``center=``, ``color=``, ``line_width=``, ``floating=``, …) as in ``Track(...)``.
        """
        from .validate import count, number
        n = count(points, "Track.star points", 3)
        if radius is None:
            _, unit = _default_pose()
            radius = unit
        radius = number(radius, "Track.star radius")
        inner = radius * 0.4 if inner is None else number(inner, "Track.star inner")
        kwargs.setdefault("closed", True)
        return cls(
            _spec=("star", n, radius, inner), center=center, **kwargs,
        )

    @classmethod
    def spiral(cls, turns=3.0, radius=None, center=None, **kwargs) -> "Track":
        """An outward spiral track (open).

        Args:
            turns: how many turns (default 3).
            radius: final radius (default: a medium size).
            center: where it sits.

        Other keywords (``center=``, ``color=``, ``line_width=``, ``floating=``, …) as in ``Track(...)``.
        """
        if radius is None:
            _, unit = _default_pose()
            radius = unit
        from .validate import number
        kwargs.setdefault("closed", False)
        return cls(
            _spec=("spiral", number(turns, "Track.spiral turns"), number(radius, "Track.spiral radius")),
            center=center, **kwargs,
        )

    @classmethod
    def wave(cls, length=200.0, amplitude=30.0, waves=3.0, start=None, **kwargs) -> "Track":
        """A sine-wave track going right from ``start`` (open).

        Args:
            length: horizontal length (default 200).
            amplitude: wave height (default 30).
            waves: how many full waves (default 3).
            start: left end point (``center=`` is refused here).

        Other keywords (``center=``, ``color=``, ``line_width=``, ``floating=``, …) as in ``Track(...)``.
        """
        if "center" in kwargs:
            raise TypeError(
                "Track.wave takes start=, not center=. "
                ".center is the geometric middle."
            )
        from .validate import number
        length = number(length, "Track.wave length")
        amplitude = number(amplitude, "Track.wave amplitude")
        waves = number(waves, "Track.wave waves")
        kwargs.setdefault("closed", False)
        pose = None
        if start is not None:
            sx, sy = _point_xy_static(start)
            pose = (sx + length * 0.5, sy)
        return cls(
            _spec=("wave", length, amplitude, waves),
            center=pose, **kwargs,
        )

    @classmethod
    def shuttle(cls, length=None, angle=None, center=None, *, vec=None, **kwargs) -> "Track":
        """Closed 1-D dash: out both ways from ``center``, back to start.

        ``length=`` is the full width (right-end to left-end). ``angle=`` / ``vec=``
        match ``Track.line`` (mutually exclusive): ``angle=`` is the heading, the
        dash built along +x and turned. Arc-length per lap is ``2 * length``.
        """
        _SHUTTLE_HINT = (
            "Track.shuttle takes length=/angle= or vec= (sizes; optional center=). "
            "Not p1=/p2=/points=/vectors=."
        )
        if any(k in kwargs for k in ("p1", "p2", "points", "vectors")):
            raise TypeError(_SHUTTLE_HINT)
        if vec is not None and (length is not None or angle is not None):
            raise TypeError("Track.shuttle takes vec= or length=/angle=, not both")
        if vec is not None:
            dx, dy = _as_xy_static(vec)
            length = math.hypot(dx, dy)
            angle = math.degrees(math.atan2(dy, dx))
        else:
            if length is None:
                _, unit = _default_pose()
                length = 2.0 * unit
            if angle is None:
                angle = 0.0
            length = float(length)
            angle = float(angle)
        if length < 0.0:
            raise ValueError("Track.shuttle length= must be >= 0")
        kwargs.setdefault("smooth", 0)
        kwargs.setdefault("closed", True)
        return cls(_spec=("shuttle", length, 0.0), center=center, angle=angle, **kwargs)


class _HostField:
    """A ``reversed()`` view's field that is its host's, read and written."""

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, view, owner=None):
        if view is None:
            return self
        return getattr(view._alias_of, self.name)

    def __set__(self, view, value):
        setattr(view._alias_of, self.name, value)


class _ViewCursor:
    """A ``reversed()`` view's own ``cursor`` (at its ``u``), kept with the host's pose.

    The view is not in the update graph. A read samples it fresh; the host is
    flagged as having a pull consumer, so a host pose change marks the host
    dirty and its refresh rewrites this cursor (``Track._update_impl``) for
    the links that read it.
    """

    def __get__(self, view, owner=None):
        if view is None:
            return self
        cur = Track.__dict__["cursor"].__get__(view, owner)
        host = view._alias_of
        if not getattr(host, "_destroyed", False):
            host._flag_pull_consumers()
            host._ensure_samples()
            view._refresh_cursor()
        return cur

    def __set__(self, view, value):
        Track.__dict__["cursor"].__set__(view, value)   # a Derivate: raises


# What a reversed() view shares with its host (Tracks Design — reversed()).
_VIEW_HOST_FIELDS = frozenset({
    "center", "radius", "length", "angle", "scale", "flip_x", "flip_y",
})


def _forward_timed(fn):
    """A view verb that forwards to its host: ``time=`` goes to the host's
    own timed verb (one tween key, owned by the host, dies with it), so
    ``Shape.__init_subclass__`` must not wrap the view's method in a second
    tween of the view (review 2026-10-09 S6-3)."""
    fn._timed_wrapped = True
    return fn


class _ReversedTrack(Track):
    """``track.reversed()``: the host's tables read backwards.

    The view has no pose or size of its own. ``center``, ``angle``,
    ``scale``, the flips, ``radius`` and ``length`` are the host's (reads,
    writes and ``view["name"]`` links), and every pose verb turns, scales,
    flips or moves the host, so what the view reports is what it draws. Its
    own parts are ``u`` / ``cursor`` (in travel order). Named ``Track``: to
    the author it is one.
    """

    center = _HostField()
    radius = _HostField()
    length = _HostField()
    angle = _HostField()
    scale = _HostField()
    flip_x = _HostField()
    flip_y = _HostField()
    cursor = _ViewCursor()

    def _on_host(self, out):
        # Chaining stays on the view; a timed verb returns the host's Handle.
        return self if out is self._alias_of else out

    def move_by(self, *args, **kwargs):
        return self._on_host(self._alias_of.move_by(*args, **kwargs))

    def move_to(self, *args, **kwargs):
        return self._on_host(self._alias_of.move_to(*args, **kwargs))

    @_forward_timed
    def rotate_by(self, *args, **kwargs):
        return self._on_host(self._alias_of.rotate_by(*args, **kwargs))

    @_forward_timed
    def rotate_to(self, *args, **kwargs):
        return self._on_host(self._alias_of.rotate_to(*args, **kwargs))

    @_forward_timed
    def scale_by(self, *args, **kwargs):
        return self._on_host(self._alias_of.scale_by(*args, **kwargs))

    @_forward_timed
    def scale_to(self, *args, **kwargs):
        return self._on_host(self._alias_of.scale_to(*args, **kwargs))

    def __getitem__(self, key):
        if key in _VIEW_HOST_FIELDS:
            return self._alias_of[key]
        return super().__getitem__(key)

    def _ensure_scalar_anchor(self, name, anchor_cls=None):
        # A formula that names ``view.angle`` depends on the host's node: the
        # view's own was never notified (G18).
        if name in _VIEW_HOST_FIELDS:
            return self._alias_of._ensure_scalar_anchor(name, anchor_cls)
        return super()._ensure_scalar_anchor(name, anchor_cls)

    def __setitem__(self, key, value):
        if key in _VIEW_HOST_FIELDS:
            self._alias_of[key] = value
            return
        super().__setitem__(key, value)

    def _update_impl(self) -> None:
        host = self._alias_of
        with host._no_update():
            host._update_impl()   # refreshes this view's cursor too

    def _takein_impl(self, other) -> None:
        # The view has no path of its own to copy into: ``view << t`` used to
        # write private tables the view never reads, so nothing changed (D21).
        raise TypeError(
            "A reversed() track shows its host's path backwards; it cannot take "
            "in another track. Copy into the host (host << other), or use "
            "other.reversed()."
        )


_ReversedTrack.__name__ = _ReversedTrack.__qualname__ = "Track"


# move_along string sugar — 1:1 with zero-arg Track presets.
_MOVE_ALONG_PRESET_NAMES = (
    "circle", "eight", "star", "wave", "spiral", "arc", "line", "shuttle",
)


def _resolve_move_along_target(target):
    """If ``target`` is a preset name string, return that floating Track; else pass through.

    Exact lowercase names only. Builds with ``_register=False`` (invisible, reclaimable)
    so sugar matches the live-outline wrap path. Same defaults as ``Track.eight()`` etc.
    — swapping the string for the classmethod must not change the ride.
    """
    if not isinstance(target, str):
        return target
    name = target
    if name == "zigzag":
        raise TypeError(
            'move_along preset "zigzag" was removed; use "eight" (Track.eight()).'
        )
    make = {
        "circle": Track.circle, "eight": Track.eight, "star": Track.star,
        "wave": Track.wave, "spiral": Track.spiral, "arc": Track.arc,
        "line": Track.line, "shuttle": Track.shuttle,
    }.get(name)
    if make is not None:
        track = make(_register=False)
        track._float_mark = None    # no author handle: nothing can place it (KN9)
        return track
    allowed = ", ".join(repr(n) for n in _MOVE_ALONG_PRESET_NAMES)
    raise TypeError(
        f"move_along preset string expected one of {allowed}, got {name!r}. "
        f"Custom size: Track.eight(width=…) (or another Track preset), not a string."
    )


def _preset_local(spec, sps: int) -> Tuple[List[float], List[float], bool]:
    kind = spec[0]
    n = max(24, int(sps) * 4)
    if kind == "line":
        length, ang = float(spec[1]), float(spec[2])
        h = 0.5 * length
        rad = math.radians(ang)
        c, s = math.cos(rad), math.sin(rad)
        return [-h * c, h * c], [-h * s, h * s], False
    if kind == "eight":
        w, h = float(spec[1]), float(spec[2])
        xs, ys = [], []
        for i in range(n):
            t = 2.0 * math.pi * i / n
            xs.append((w * 0.5) * math.sin(t))
            ys.append((h * 0.5) * math.sin(t) * math.cos(t))
        return xs, ys, True
    if kind == "star":
        npts, r, inner = int(spec[1]), float(spec[2]), float(spec[3])
        xs, ys = [], []
        for i in range(npts * 2):
            a = (math.pi / npts) * i  # 0 = +x, CCW
            rad = r if (i % 2 == 0) else inner
            xs.append(rad * math.cos(a))
            ys.append(rad * math.sin(a))
        return xs, ys, True
    if kind == "spiral":
        turns, r = float(spec[1]), float(spec[2])
        n = max(24, int(abs(turns) * sps * 4))
        xs, ys = [], []
        for i in range(n + 1):
            t = i / n
            a = t * turns * 2.0 * math.pi
            rr = r * t
            xs.append(rr * math.cos(a))
            ys.append(rr * math.sin(a))
        return xs, ys, False
    if kind == "shuttle":
        length, ang = float(spec[1]), float(spec[2])
        h = 0.5 * length
        rad = math.radians(ang)
        c, s = math.cos(rad), math.sin(rad)
        return [0.0, h * c, -h * c], [0.0, h * s, -h * s], True
    if kind == "wave":
        length, amp, waves = float(spec[1]), float(spec[2]), float(spec[3])
        n = max(16, int(abs(waves) * sps * 4))
        xs, ys = [], []
        for i in range(n + 1):
            t = i / n
            xs.append(t * length - length * 0.5)
            ys.append(amp * math.sin(t * waves * 2.0 * math.pi))
        return xs, ys, False
    if kind == "arc":
        r, fa, ta = float(spec[1]), float(spec[2]), float(spec[3])
        sweep = ta - fa
        n = max(8, sps * 3)
        xs, ys = [], []
        for i in range(n + 1):
            t = i / n
            a = math.radians(fa + sweep * t)
            xs.append(r * math.cos(a))
            ys.append(r * math.sin(a))
        return xs, ys, False
    return [0.0, 1.0], [0.0, 0.0], False


# ---------------------------------------------------------------------------
# Active ride (move_along)
# ---------------------------------------------------------------------------

class RideState:
    """Per-handle travel along a Track / Shape outline.

    Always motion: ticks apply ``_move_by`` deltas. Floating tracks freeze a
    world root at start; anchored tracks read the path pose live. A floating
    ride whose track is anchored later is switched to the live pose by the
    track (``Track._pull_floating_rides``), one way, at no per-tick cost.
    """

    __slots__ = (
        "rider", "path", "source_ref", "floating", "root_x", "root_y",
        "span0", "span1", "phase", "face", "wrap",
        "prev_x", "prev_y", "baked",
        "frozen_xs", "frozen_ys", "frozen_s", "frozen_closed", "frozen_rev",
        "frozen_cx", "frozen_cy", "frozen_rot", "frozen_scale",
        "__weakref__",      # a floating ride is listed on its track's host
    )

    def __init__(self, rider, path, *, floating, root_x, root_y,
                 span0, span1, phase, face, wrap):
        self.rider = rider
        self.path = path
        self.source_ref = None
        if path is not None and getattr(path, "model", None) is not None:
            host = path._table_host() if hasattr(path, "_table_host") else path
            if host.model == TrackModel.SHAPE:
                self.source_ref = host._source_ref
        self.floating = bool(floating)
        self.root_x = float(root_x)
        self.root_y = float(root_y)
        self.span0 = float(span0)
        self.span1 = float(span1)
        self.phase = float(phase)
        self.face = bool(face)
        self.wrap = bool(wrap)
        self.prev_x = None
        self.prev_y = None
        self.baked = False
        self.frozen_xs = None
        self.frozen_ys = None
        self.frozen_s = None
        self.frozen_closed = True
        self.frozen_rev = False
        self.frozen_cx = 0.0
        self.frozen_cy = 0.0
        self.frozen_rot = 0.0
        self.frozen_scale = 1.0

    def _path_alive(self) -> bool:
        p = self.path
        if p is None:
            return False
        src = None
        if self.source_ref is not None:
            src = self.source_ref()
            if src is None or getattr(src, "_destroyed", False):
                return False
        if getattr(p, "_destroyed", False):
            return False
        # A reversed() view is not destroyed with its host; it reads the
        # host's tables and pose, so the host's death is the view's.
        host = getattr(p, "_alias_of", None)
        if host is not None and getattr(host, "_destroyed", False):
            return False
        return True

    def freeze_last(self) -> bool:
        """Keep the last baked tables; stop tracking a dead source. False if never baked."""
        p = self.path
        if p is None:
            return bool(self.baked)
        # Tables live on the host (a reversed() view has none of its own);
        # keep the view's direction with them.
        host = getattr(p, "_alias_of", None)
        if host is None:
            host = p
        if not getattr(host, "_xs", None):
            return bool(self.baked)
        try:
            xs, ys, ss, closed, rev = p._tables()
        except Exception:
            return bool(self.baked)
        if not xs:
            return bool(self.baked)
        self.frozen_xs = list(xs)
        self.frozen_ys = list(ys)
        self.frozen_s = list(ss)
        self.frozen_closed = bool(closed)
        self.frozen_rev = bool(rev)
        if not self.baked:
            try:
                cx, cy = p._pose_xy()
            except Exception:
                cx, cy = get_xy(p.center, bare=False)
            self.frozen_cx, self.frozen_cy = cx, cy
            # reversed() shares the host pose; the view's own slots stay 0.
            host = p._pose_host()
            self.frozen_rot = float(host._rotation)
            self.frozen_scale = float(host._scale)
        self.baked = True
        self.path = None
        self.source_ref = None
        return True

    def _local(self, u: float, live: Optional[bool] = None) -> Tuple[float, float]:
        if live is None:
            live = self.path is not None and self._path_alive()
        if live:
            try:
                return self.path.local_at(u)
            except Exception:
                pass
            if not self.freeze_last():
                raise RuntimeError("path has no sample table")
        if self.frozen_xs is None:
            raise RuntimeError("path has no sample table")
        return curve_sample(
            self.frozen_xs, self.frozen_ys, self.frozen_s, u,
            closed=self.frozen_closed, reversed=self.frozen_rev,
        )

    def _tangent_local(self, u: float) -> Tuple[float, float]:
        if self.path is not None and self._path_alive():
            p = self.path
            xs, ys, s, closed, rev = p._tables()
            return curve_tangent(xs, ys, s, u, closed=closed, reversed=rev)
        if self.frozen_xs is None:
            return (0.0, 0.0)
        return curve_tangent(
            self.frozen_xs, self.frozen_ys, self.frozen_s, u,
            closed=self.frozen_closed, reversed=self.frozen_rev,
        )

    def world_at(self, u: float) -> Tuple[float, float]:
        # One alive check, one pose pull. _world_of would pull the same
        # center / rotation / scale again just to snapshot the freeze.
        live = self.path is not None and self._path_alive()
        lx, ly = self._local(u, live)
        self.baked = True
        if self.path is None:
            live = False  # _local froze a dead source mid-sample
        if live:
            path = self.path
            host = path._pose_host()
            rot = float(host._rotation)
            sc = float(host._scale)
            self.frozen_rot = rot
            self.frozen_scale = sc
            if self.floating:
                return apply_pose(
                    lx, ly, cx=self.root_x, cy=self.root_y,
                    rotation_deg=rot, scale=sc,
                )
            cx, cy = path._pose_xy()
            self.frozen_cx, self.frozen_cy = cx, cy
            return apply_pose(
                lx, ly, cx=cx, cy=cy, rotation_deg=rot, scale=sc,
            )
        cx = self.root_x if self.floating else self.frozen_cx
        cy = self.root_y if self.floating else self.frozen_cy
        return apply_pose(
            lx, ly, cx=cx, cy=cy,
            rotation_deg=self.frozen_rot, scale=self.frozen_scale,
        )

    def world_angle(self, u: float) -> float:
        tx, ty = self._tangent_local(u)
        live = self.path is not None and self._path_alive()
        if live:
            host = self.path._pose_host()
            rot = float(host._rotation)
            sc = float(host._scale)
        else:
            rot = self.frozen_rot
            sc = self.frozen_scale
        vx, vy = apply_pose_vec(tx, ty, rotation_deg=rot, scale=sc)
        mag = math.hypot(vx, vy)
        if mag <= 1e-18:
            return 0.0
        return math.degrees(math.atan2(vy, vx))

    def map_u(self, t: float) -> float:
        u = self.span0 + (self.span1 - self.span0) * float(t) + self.phase
        if self.wrap:
            u = u % 1.0
            if u < 0.0:
                u += 1.0
            return u
        if u < 0.0:
            return 0.0
        if u > 1.0:
            return 1.0
        return u

    def overlay_polyline(self, n: int = 48):
        pts = []
        try:
            for i in range(n):
                t = i / (n - 1)
                u = self.map_u(t)
                pts.append(self.world_at(u))
        except Exception:
            return [], True, None
        closed = False
        if self.path is not None:
            tables = (self.path._table_host() if hasattr(self.path, "_table_host")
                      else self.path)
            closed = bool(tables._closed) and abs(self.span1 - self.span0) >= 0.999
        elif self.frozen_closed:
            closed = abs(self.span1 - self.span0) >= 0.999
        try:
            ang = self.world_angle(self.map_u(0.0))
            rad = math.radians(ang)
            tang = (math.cos(rad), math.sin(rad))
        except Exception:
            tang = (1.0, 0.0)
        return pts, closed, tang


# ---------------------------------------------------------------------------
# Debug overlay (immediate-mode)
# ---------------------------------------------------------------------------

def _overlay_paint(idle: bool = False) -> skia.Paint:
    rgba = _TRACK_OVERLAY_IDLE_RGBA if idle else _TRACK_OVERLAY_RGBA
    p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=1.6 if not idle else 1.1,
    )
    p.setColor4f(skia.Color4f(*rgba))
    return p


def _draw_polyline(canvas, pts, paint, *, closed: bool, mark_start: bool, tangent=None):
    if len(pts) < 2:
        return
    path = skia.Path()
    path.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        path.lineTo(x, y)
    if closed:
        path.close()
    canvas.drawPath(path, paint)
    if mark_start:
        x0, y0 = pts[0]
        canvas.drawCircle(x0, y0, 4.0, paint)
        if tangent is not None:
            tx, ty = tangent
            canvas.drawLine(x0, y0, x0 + tx * 18.0, y0 + ty * 18.0, paint)


def draw_track_overlay(skia_canvas) -> None:
    """Immediate-mode stroke of active rides + idle Track objects. No Shape churn."""
    paint = _overlay_paint(False)
    idle_paint = _overlay_paint(True)
    from .process import get_scheduler
    sched = get_scheduler()
    for handle in list(getattr(sched, "_tween", ())):
        ride = getattr(handle, "_ride", None)
        if ride is None or handle._done or handle._cancelled:
            continue
        pts, closed, tang = ride.overlay_polyline()
        if pts:
            _draw_polyline(skia_canvas, pts, paint, closed=closed, mark_start=True, tangent=tang)
    # Idle Track objects currently on a layer.
    try:
        from .canvas import ScenaCanvas
        registry = ScenaCanvas.get_current().registry
        ridden = set()
        for handle in list(getattr(sched, "_tween", ())):
            ride = getattr(handle, "_ride", None)
            if ride is not None:
                p = getattr(ride, "path", None)
                if p is not None:
                    ridden.add(id(p))
        for layer in registry.layers.values():
            for obj in list(getattr(layer, "_objects", ())):
                if not isinstance(obj, Track):
                    continue
                if id(obj) in ridden:
                    continue
                if getattr(obj, "_alias_of", None) is not None:
                    continue
                obj._ensure_samples()
                n = len(obj._xs)
                if n < 2:
                    continue
                pts = [obj._world_of(obj._xs[i], obj._ys[i]) for i in range(n)]
                tang = obj.tangent_at(0.0)
                _draw_polyline(
                    skia_canvas, pts, idle_paint,
                    closed=obj._closed, mark_start=True, tangent=tang,
                )
    except Exception:
        pass


def _publish_track_signature() -> None:
    """Author ``help(Track)`` omits the engine-only ``_spec`` / ``_register`` path."""
    import inspect
    init = Track.__init__
    sig = inspect.signature(init)
    kept = [
        p for p in sig.parameters.values()
        if not p.name.startswith("_")
    ]
    init.__signature__ = sig.replace(parameters=kept)


_publish_track_signature()
