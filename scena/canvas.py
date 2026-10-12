import math
from typing import Dict, Optional, Union, Tuple, List
from enum import Enum
import skia
from dataclasses import dataclass

from .shapes import Point, Rect, _xy_of
from .scenamath import _as_xy
from .style import *
from .entity import _drawn
from .registry import (
    Registry,
    LayersFacade,
    GroupOperator,
    Layer,
    LayerStack,
    normalize_layer_name,
    BUILT_IN_LAYERS,
    TOP_LAYER,
    TOP_Z,
    UI_LAYER,
    MAX_LAYER_Z,
)
from .camera_response import CameraResponse, partial_camera_matrix
from .validate import HINT_SCALE, clamp_magnitude, magnitude, fixed_magnitude, seconds
from .closed import ClosedSurface
from .state import Container

def _finite_number(value, what: str) -> float:
    """Float that is not NaN or ±inf. ``bool`` is not a number."""
    from .validate import number
    return number(value, what)   # camera verbs take fixed numbers


def _finite_xy(x: float, y: float, what: str) -> None:
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError(f"{what} must be finite")


def _require_frame_size(width: float, height: float) -> None:
    """Reject a negative or non-finite frame. Zero is a legal collapsed frame."""
    if (
        not math.isfinite(width) or not math.isfinite(height)
        or width < 0.0 or height < 0.0
    ):
        raise ValueError(
            "frame_to width and height must be finite and >= 0"
        )


_MIN_ZOOM = 1e-6
_CAMERA_EPS = 1e-9

# Tween channels for the one global camera (later tween on a channel cancels earlier).
CAMERA_PAN_KEY = ("camera", "pan")
CAMERA_ZOOM_KEY = ("camera", "zoom")
CAMERA_ROTATION_KEY = ("camera", "rotation")
CAMERA_ALL_KEYS = (CAMERA_PAN_KEY, CAMERA_ZOOM_KEY, CAMERA_ROTATION_KEY)


def _zoom_lerp(za: float, zb: float, u: float) -> float:
    """Interpolate a zoom factor, safe against an overshooting ease.

    Linear interpolation (``za + (zb - za) * u``) goes negative whenever an
    ease overshoots past ``[0, 1]`` (``elastic``, or a custom ``3 * t``) —
    even though both endpoints are positive. Geometric interpolation stays
    positive for *any* real ``u`` because a positive base raised to any
    power is positive; it is also endpoint-exact (``u=0 → za``, ``u=1 →
    zb``). Falls back to linear + clamp for a zero/negative endpoint (should
    not happen — callers clamp to ``_MIN_ZOOM`` — but stay defensive).
    """
    if za > 0.0 and zb > 0.0:
        return za * (zb / za) ** u
    return max(za + (zb - za) * u, _MIN_ZOOM)


def _freeze_about(about) -> Optional[Tuple[float, float]]:
    if about is None:
        return None
    xy = _as_xy(about)
    _finite_xy(xy[0], xy[1], "about")
    return xy


def _look_xy(x, y=None) -> Tuple[float, float]:
    """``pan_to`` destination: two floats, or one point-like.

    Point-like: ``(x, y)`` tuple/list, Point, Vec2, Graphic (``.center``), or
    an object with ``.x``/``.y``. ``None`` is an error (not a no-op).
    """
    if y is not None:
        return float(x), float(y)
    return _as_xy(x)


def _delta_xy(dx, dy=None) -> Tuple[float, float]:
    """``pan_by`` displacement: two floats, or one Vec2 / ``(dx, dy)``.

    A Point, Graphic, or mouse is a location — use ``pan_to``.
    """
    if dy is not None:
        return float(dx), float(dy)
    from .input import Mouse
    if isinstance(dx, (Point, Mouse)) or getattr(dx, "center", None) is not None:
        raise TypeError(
            "pan_by does not accept a Point, Graphic, or mouse (those are locations). "
            "Use pan_to(...), or pan_by(dx, dy) / pan_by(v)."
        )
    return _as_xy(dx)


def _origin_look(engine: "ScenaCanvas", where: str) -> Tuple[float, float]:
    """Target look-at for ``set_origin`` without mutating."""
    key = str(where).lower().replace("-", "_")
    if key in ("corner", "bottom_left", "bottomleft"):
        return engine.width * 0.5, engine.height * 0.5
    if key in ("center", "middle"):
        return 0.0, 0.0
    raise ValueError(
        "set_origin where must be 'corner'/'bottom_left' or 'center', "
        f"got {where!r}"
    )


def _frame_end_pose(
    engine: "ScenaCanvas",
    target,
    *,
    pad: float,
    rotate: bool,
) -> Tuple[float, float, float, float]:
    """Frozen (look_x, look_y, zoom, rotation) for timed ``frame_to``."""
    cx, cy, tw, th, ang = ScenaCanvas._parse_frame_target(target)
    pad = float(pad)
    tw = max(float(tw) * (1.0 + 2.0 * pad), _MIN_ZOOM)
    th = max(float(th) * (1.0 + 2.0 * pad), _MIN_ZOOM)
    rot = -float(ang) if rotate else 0.0
    zoom_x = engine.width / tw if tw else 1.0
    zoom_y = engine.height / th if th else 1.0
    zoom = max(min(zoom_x, zoom_y), _MIN_ZOOM)
    return float(cx), float(cy), zoom, rot


def _camera_tween(
    *,
    write,
    tween_keys,
    time: float,
    ease: str = "linear",
    then=None,
    on_done=None,
    call_name: str = "camera",
    loops: object = 1,
    yoyo: bool = False,
):
    from .process import (
        _infer_owner,
        _require_loop_kwargs,
        _require_timed_completion,
        _start_tween,
    )

    _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name=call_name)
    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, call_name=call_name,
    )
    owner, scope = _infer_owner()
    return _start_tween(
        duration=seconds(time, f"{call_name} time="),
        ease=ease,
        write=write,
        tween_keys=tween_keys,
        then=then,
        on_done=on_done,
        owner=owner,
        scope=scope,
        loops=n_loops,
        yoyo=yoyo,
    )


def timed_camera_pan_to(
    canvas: "Canvas",
    x: float,
    y: float,
    *,
    time: float,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    eng = canvas._engine
    x0, y0 = eng._look_x, eng._look_y
    x1, y1 = _finite_number(x, "pan"), _finite_number(y, "pan")

    def write(u, e=eng, ax=x0, ay=y0, bx=x1, by=y1):
        e.pan_to(ax + (bx - ax) * u, ay + (by - ay) * u)

    return _camera_tween(
        write=write,
        tween_keys=(CAMERA_PAN_KEY,),
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="pan_to",
        loops=loops,
        yoyo=yoyo,
    )


def timed_camera_pan_by(
    canvas: "Canvas",
    dx: float,
    dy: float,
    *,
    time: float,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    eng = canvas._engine
    dx, dy = _finite_number(dx, "pan"), _finite_number(dy, "pan")
    applied = [0.0, 0.0]

    def write(u, e=eng, ddx=dx, ddy=dy, box=applied):
        tx, ty = ddx * u, ddy * u
        step_x, step_y = tx - box[0], ty - box[1]
        if step_x != 0.0 or step_y != 0.0:
            e.pan_by(step_x, step_y)
            box[0], box[1] = tx, ty

    return _camera_tween(
        write=write,
        tween_keys=(CAMERA_PAN_KEY,),
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="pan_by",
        loops=loops,
        yoyo=yoyo,
    )


def timed_camera_zoom_to(
    canvas: "Canvas",
    factor: float,
    *,
    time: float,
    about=None,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    eng = canvas._engine
    z0 = eng._zoom
    z1 = fixed_magnitude(factor, "zoom", hint=HINT_SCALE)
    about_xy = _freeze_about(about)
    keys = (CAMERA_ZOOM_KEY, CAMERA_PAN_KEY) if about_xy is not None else (CAMERA_ZOOM_KEY,)

    def write(u, e=eng, a=z0, b=z1, ab=about_xy):
        # Geometric, as Canvas Design says and frame_to / reset_view do: a
        # linear zoom collapsed the world to a dot under an overshooting ease
        # (review 2026-10-09 X-writers-3).
        e.zoom_to(clamp_magnitude(_zoom_lerp(a, b, u)), about=ab)

    return _camera_tween(
        write=write,
        tween_keys=keys,
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="zoom_to",
        loops=loops,
        yoyo=yoyo,
    )


def timed_camera_zoom_by(
    canvas: "Canvas",
    factor: float,
    *,
    time: float,
    about=None,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    eng = canvas._engine
    z0 = eng._zoom
    fac = fixed_magnitude(factor, "zoom", hint=HINT_SCALE)
    z1 = z0 * fac
    about_xy = _freeze_about(about)
    keys = (CAMERA_ZOOM_KEY, CAMERA_PAN_KEY) if about_xy is not None else (CAMERA_ZOOM_KEY,)

    def write(u, e=eng, a=z0, b=z1, ab=about_xy):
        # Geometric, as Canvas Design says and frame_to / reset_view do: a
        # linear zoom collapsed the world to a dot under an overshooting ease
        # (review 2026-10-09 X-writers-3).
        e.zoom_to(clamp_magnitude(_zoom_lerp(a, b, u)), about=ab)

    return _camera_tween(
        write=write,
        tween_keys=keys,
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="zoom_by",
        loops=loops,
        yoyo=yoyo,
    )


def timed_camera_rotate_to(
    canvas: "Canvas",
    angle: float,
    *,
    time: float,
    about=None,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    from .process import shortest_delta_deg

    eng = canvas._engine
    start = float(eng._rotation)
    end = _finite_number(angle, "rotation")
    delta = shortest_delta_deg(start, end)
    about_xy = _freeze_about(about)
    keys = (
        (CAMERA_ROTATION_KEY, CAMERA_PAN_KEY)
        if about_xy is not None
        else (CAMERA_ROTATION_KEY,)
    )

    def write(u, e=eng, a=start, d=delta, ab=about_xy, goal=end):
        # The end stores exactly the target, as the instant form does (the
        # shortest arc from 400 to 30 reached 390; Q2 in Testing Design).
        e.rotate_to(goal if u == 1.0 else a + d * u, about=ab)

    return _camera_tween(
        write=write,
        tween_keys=keys,
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="rotate_to",
        loops=loops,
        yoyo=yoyo,
    )


def timed_camera_rotate_by(
    canvas: "Canvas",
    angle: float,
    *,
    time: float,
    about=None,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    eng = canvas._engine
    start = float(eng._rotation)
    delta = _finite_number(angle, "rotation")
    about_xy = _freeze_about(about)
    keys = (
        (CAMERA_ROTATION_KEY, CAMERA_PAN_KEY)
        if about_xy is not None
        else (CAMERA_ROTATION_KEY,)
    )

    def write(u, e=eng, a=start, d=delta, ab=about_xy):
        e.rotate_to(a + d * u, about=ab)

    return _camera_tween(
        write=write,
        tween_keys=keys,
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="rotate_by",
        loops=loops,
        yoyo=yoyo,
    )


def timed_camera_set_origin(
    canvas: "Canvas",
    where: str = "corner",
    *,
    time: float,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    eng = canvas._engine
    x0, y0 = eng._look_x, eng._look_y
    x1, y1 = _origin_look(eng, where)

    def write(u, e=eng, ax=x0, ay=y0, bx=x1, by=y1):
        e._look_x = ax + (bx - ax) * u
        e._look_y = ay + (by - ay) * u
        e._anchor_rest()
        e._sync_camera()

    return _camera_tween(
        write=write,
        tween_keys=(CAMERA_PAN_KEY,),
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="set_origin",
        loops=loops,
        yoyo=yoyo,
    )


def timed_camera_frame_to(
    canvas: "Canvas",
    target,
    *,
    time: float,
    pad: float = 0.0,
    rotate: bool = False,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    eng = canvas._engine
    lx0, ly0 = eng._look_x, eng._look_y
    z0, r0 = eng._zoom, eng._rotation
    if target is None:
        lx1, ly1, z1, r1 = lx0, ly0, z0, r0
    else:
        lx1, ly1, z1, r1 = _frame_end_pose(eng, target, pad=pad, rotate=rotate)
    from .process import shortest_delta_deg
    drot = shortest_delta_deg(r0, r1)

    def write(u, e=eng, ax=lx0, ay=ly0, bx=lx1, by=ly1, za=z0, zb=z1, ra=r0, d=drot):
        e._look_x = ax + (bx - ax) * u
        e._look_y = ay + (by - ay) * u
        e._zoom = _zoom_lerp(za, zb, u)
        e._rotation = ra + d * u
        e._sync_camera()

    return _camera_tween(
        write=write,
        tween_keys=CAMERA_ALL_KEYS,
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="frame_to",
        loops=loops,
        yoyo=yoyo,
    )


def timed_camera_reset_view(
    canvas: "Canvas",
    *,
    time: float,
    ease: str = "linear",
    then=None,
    on_done=None,
    loops: object = 1,
    yoyo: bool = False,
) -> "Handle":
    eng = canvas._engine
    lx0, ly0 = eng._look_x, eng._look_y
    z0, r0 = eng._zoom, eng._rotation
    lx1, ly1 = eng.width * 0.5, eng.height * 0.5

    def write(u, e=eng, ax=lx0, ay=ly0, bx=lx1, by=ly1, za=z0, ra=r0):
        e._look_x = ax + (bx - ax) * u
        e._look_y = ay + (by - ay) * u
        e._zoom = _zoom_lerp(za, 1.0, u)
        e._rotation = ra + (0.0 - ra) * u
        e._anchor_rest()
        e._sync_camera()

    return _camera_tween(
        write=write,
        tween_keys=CAMERA_ALL_KEYS,
        time=time,
        ease=ease,
        then=then,
        on_done=on_done,
        call_name="reset_view",
        loops=loops,
        yoyo=yoyo,
    )


def _at_xy(x, y=None) -> Optional[Tuple[float, float]]:
    """Locus for canvas ``*_at`` hits. ``None`` → no-op (caller returns self).

    Two numbers ``(x, y)``, or one point-like: ``(x, y)`` tuple, Point, Vec2,
    Graphic (``.center``), ``CollisionInfo`` / ``TouchingContact`` (``.point``).
    Missing ``.point`` (exit) is ``None``. Pose verbs like ``move_to`` still
    error on ``None`` — only this hit family skips.
    """
    if y is not None:
        return float(x), float(y)
    if x is None:
        return None
    from .collision import CollisionInfo, TouchingContact
    if isinstance(x, (CollisionInfo, TouchingContact)):
        pt = x.point
        if pt is None:
            return None
        return float(pt[0]), float(pt[1])
    xy = _xy_of(x, required=False)
    if xy is None:
        raise TypeError(
            "expected (x, y), Point, Vec2, Graphic, CollisionInfo, "
            f"or None, got {type(x).__name__}"
        )
    return float(xy[0]), float(xy[1])


def _bare(v) -> float:
    if hasattr(v, 'value'):
        return float(v.value)
    return float(v)


# Conservative extra pad (design units) for multipass visuals whose paint
# extends past geometry + filter outset. Games-trade: prefer overdraw to popping.
_MULTIPASS_CULL_PAD = 80.0
_BATCH_AABB_FALLBACK = (-40.0, -40.0, 40.0, 40.0)


def _aabb_from_oriented(
    cx: float, cy: float, w: float, h: float, ang: float = 0.0,
) -> Tuple[float, float, float, float]:
    """Axis-aligned box of an oriented frame ``(cx, cy, w, h, ang_deg)``."""
    hw, hh = abs(float(w)) * 0.5, abs(float(h)) * 0.5
    if ang:
        rad = math.radians(float(ang))
        c, s = abs(math.cos(rad)), abs(math.sin(rad))
        ex = hw * c + hh * s
        ey = hw * s + hh * c
    else:
        ex, ey = hw, hh
    return (float(cx) - ex, float(cy) - ey, float(cx) + ex, float(cy) + ey)


def _pad_aabb(
    box: Tuple[float, float, float, float], pad: float,
) -> Tuple[float, float, float, float]:
    p = float(pad)
    return (box[0] - p, box[1] - p, box[2] + p, box[3] + p)


def _aabb_contains(
    outer: Tuple[float, float, float, float],
    inner: Tuple[float, float, float, float],
    *,
    eps: float = 1e-6,
) -> bool:
    return (
        inner[0] >= outer[0] - eps
        and inner[1] >= outer[1] - eps
        and inner[2] <= outer[2] + eps
        and inner[3] <= outer[3] + eps
    )


def _shield_oval_aabb(obj) -> Optional[Tuple[float, float, float, float]]:
    """World AABB of the Sprite Shield / plasma costume oval, or ``None``.

    Shape Shield has no envelope method. Glow stamps and other looks bail on
    ``_visual`` before any Sprite work. Do not import ``sprite`` here — this
    runs on the filter-batch hot path.
    """
    vis = getattr(obj, "_visual", None)
    if vis is None:
        return None
    from .entity import scena_kind
    if scena_kind(vis) != "Shield" and getattr(vis, "_VARIANT", None) != "shield_halo":
        return None
    env_fn = getattr(obj, "_shield_envelope_frame", None)
    if not callable(env_fn):
        return None
    try:
        cx, cy, w, h, ang = env_fn()
    except Exception:
        return None
    return _aabb_from_oriented(cx, cy, w, h, ang)


def _expand_aabb_for_shield_oval(
    box: Tuple[float, float, float, float],
    obj,
    outset: float,
) -> Tuple[float, float, float, float]:
    """Union dest AABB with the Shield oval only when dest+outset does not cover it.

    Filter-layer cost is union AABB × blur. GlowFilter Shield styles already
    pad past the oval — expanding them would grow shared HostGlow/GlowFilter
    plates (bands shares interned HostGlow with HaloLine). Vortex HostGlow
    does not; the oval clips to a dest rect. Shape Shield is a no-op (no
    envelope method).
    """
    env = _shield_oval_aabb(obj)
    if env is None:
        return box
    if _aabb_contains(_pad_aabb(box, outset), env):
        return box
    return _union_aabb([box, env])


_CLASS_HAS: Dict[Tuple[type, str], bool] = {}


def _probe(obj, name: str):
    """``getattr(obj, name, None)`` without the miss: an actor's ink
    ``__getattr__`` makes a miss cost ~0.5 µs, and the cull asks five or six
    optional names per object per frame (review 2026-10-09 S9-10). Whether the
    class has the name is decided once per class; an instance attribute still
    answers through ``__dict__``."""
    key = (type(obj), name)
    has = _CLASS_HAS.get(key)
    if has is None:
        has = _CLASS_HAS[key] = any(name in k.__dict__ for k in type(obj).__mro__)
    if has:
        return getattr(obj, name, None)
    d = getattr(obj, "__dict__", None)
    return d.get(name) if d else None


def _approx_draw_aabb(obj) -> Optional[Tuple[float, float, float, float]]:
    """Loose axis-aligned bounds in y-up world space.

    Dest / geometry only — not Shield costume ovals (those expand in
    ``_layer_bounds_for`` / cull via ``_expand_aabb_for_shield_oval``). Prefer
    Defining parts (vertices, line endpoints) so cull does not wake cold
    Derivates. Returns ``None`` when no usable box is known (cull fail-open;
    batching substitutes a small origin hint).
    """
    # Every measuring reader pulls a linked angle / scale first, as draw and
    # collision do: the cull ran before the draw's pull and skipped a shape a
    # formula had brought into view (review 2026-10-09 W-G3). One dict probe.
    d = getattr(obj, "__dict__", None)
    if d and d.get("_field_anchors"):
        pull = getattr(type(obj), "_pull_property_anchors", None)
        if pull is not None:
            pull(obj)
    domain_aabb = _probe(obj, "_domain_aabb")
    if callable(domain_aabb):
        try:
            box = tuple(float(v) for v in domain_aabb())
            if len(box) == 4:
                return box  # type: ignore[return-value]
        except Exception:
            pass

    oriented = _probe(obj, '_oriented_frame')
    if callable(oriented):
        try:
            cx, cy, w, h, ang = oriented()
            return _aabb_from_oriented(cx, cy, w, h, ang)
        except Exception:
            pass

    placement = _probe(obj, '_placement_params')
    if callable(placement):
        try:
            cx, cy, r, _phi = placement()
            r = abs(float(r))
            return (cx - r, cy - r, cx + r, cy + r)
        except Exception:
            pass

    vertices = _probe(obj, "_vertices")
    if vertices:
        try:
            xs: List[float] = []
            ys: List[float] = []
            for vtx in vertices:
                x, y = _as_xy(vtx)
                xs.append(x)
                ys.append(y)
            if xs:
                return (min(xs), min(ys), max(xs), max(ys))
        except Exception:
            pass

    # Line: Defining endpoints. ``center`` is a cold Derivate on Line — reading
    # it below would mark the Line pull-live and push its motion off A1.
    segment = _probe(obj, '_segment_xy')
    if callable(segment):
        try:
            x1, y1, x2, y2 = segment()
            return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        except Exception:
            pass

    # Circle: Defining center + radius (``radius`` / ``center`` are Derivates
    # on the perimeter and two-point models; reading them wakes them — D3).
    radius_fn = _probe(obj, '_radius_value')
    if callable(radius_fn):
        try:
            cx, cy = obj._center_xy()
            r = abs(float(radius_fn()))
            return (cx - r, cy - r, cx + r, cy + r)
        except Exception:
            pass

    # Circle/radial before Line endpoints: Circle.p1/p2 are Derivate diameter
    # ends (a line AABB), not the disc. Accessing them also wakes cold Derivates.
    center = getattr(obj, 'center', None)
    if center is not None:
        try:
            cx, cy = _as_xy(center)
        except TypeError:
            cx = cy = None
        if cx is not None:
            if hasattr(obj, 'radius'):
                try:
                    r = abs(_bare(obj.radius))
                    return (cx - r, cy - r, cx + r, cy + r)
                except Exception:
                    pass
            if hasattr(obj, 'width') and hasattr(obj, 'height'):
                try:
                    w = abs(_bare(obj.width))
                    h = abs(_bare(obj.height))
                    rv = getattr(obj, '_rotation_value', None)
                    ang = float(rv()) if callable(rv) else _bare(getattr(obj, 'angle', 0.0))
                    return _aabb_from_oriented(cx, cy, w, h, ang)
                except Exception:
                    pass

    p1 = getattr(obj, "p1", None)
    p2 = getattr(obj, "p2", None)
    if p1 is not None and p2 is not None:
        try:
            x1, y1 = _as_xy(p1)
            x2, y2 = _as_xy(p2)
            return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        except Exception:
            pass

    return None


def _union_aabb(boxes: List[Tuple[float, float, float, float]]) -> Tuple[float, float, float, float]:
    minx = min(b[0] for b in boxes)
    miny = min(b[1] for b in boxes)
    maxx = max(b[2] for b in boxes)
    maxy = max(b[3] for b in boxes)
    return (minx, miny, maxx, maxy)


# Bucketed GPU RT pool for low-res shape ImageFilters (glow/blur/shadow).
_SHAPE_FX_POOL_MAX = 4


def _filter_batch_key(fx) -> Optional[tuple]:
    if fx is None:
        return None
    return getattr(fx, '_batch_key', None)


def _aabb_intersects_view(aabb, vb: 'VisibleBounds') -> bool:
    minx, miny, maxx, maxy = aabb
    # VisibleBounds: top is larger y, bottom is smaller y
    return not (maxx < vb.left or minx > vb.right or maxy < vb.bottom or miny > vb.top)


# Skia's default miter limit (Scena never changes it): a miter join longer than
# this many half-widths is beveled, so no join reaches further than this.
_SKIA_MITER_LIMIT = 4.0
_SMOOTH_OUTLINES = ("Circle", "Ellipse")


_SQRT2 = math.sqrt(2.0)


def _scena_kind(obj) -> str:
    from .entity import scena_kind
    return scena_kind(obj)


def _stroke_reach_factor(obj) -> float:
    """How many half-widths the stroke can reach past the outline (D9).

    Half the stroke is exact only for smooth outlines and round joins. A miter
    join reaches ``1 / sin(angle / 2)`` half-widths past a corner (sqrt(2) on a
    rectangle's 90 degree corners, up to the miter limit elsewhere); a square
    cap's corners reach sqrt(2) half-widths past a line end.
    """
    # Each property read once (the nested ``getattr`` defaults read them twice:
    # this runs per object per frame under ``cull_offscreen``, S9-10).
    j = getattr(obj, "line_join", None)
    join = str(getattr(j, "value", j) or "")
    c = getattr(obj, "line_cap", None)
    cap = str(getattr(c, "value", c) or "")
    factor = 1.0
    if cap == "square":
        factor = _SQRT2
    if join == "miter":
        kind = _scena_kind(obj)
        if kind in _SMOOTH_OUTLINES:
            try:
                is_arc = float(getattr(obj, "spread", 360.0)) < 360.0
            except (TypeError, ValueError):
                is_arc = True
            if not is_arc:
                return factor  # closed smooth outline: no joins
        if kind in ("Rect", "Square", "Box"):
            return max(factor, _SQRT2)
        return _SKIA_MITER_LIMIT
    return factor


def _cull_keeps(obj, vb) -> bool:
    """Per object, on a layer that culls: does its padded draw AABB meet the
    view window ``vb``? Fail open (keep drawing) on unknown geometry."""
    try:
        box = _approx_draw_aabb(obj)
        if box is None:
            return True
        pad = _filter_outset(obj)
        if getattr(obj, "_tx_state", None) is not None:
            from .transients import transient_cull_pad
            pad += float(transient_cull_pad(obj) or 0.0)
        extra = _probe(obj, "_cull_pad")
        if extra is not None:
            pad += float(extra())
        box = _expand_aabb_for_shield_oval(box, obj, pad)
        return _aabb_intersects_view(_pad_aabb(box, pad), vb)
    except Exception:
        return True


def _filter_outset(obj) -> float:
    """Cull pad: largest costume outset, plus stroke half-width and multipass/tail.

    ``_cull_outset`` values are combined with ``max`` (they already describe the
    halo). Half the stroke and the multipass / tail pads are added on top so a
    later, larger outset cannot erase them.
    """
    base = 0.0
    for fx in (getattr(obj, 'fill_filter', None), getattr(obj, 'line_filter', None)):
        if fx is not None:
            base = max(base, float(getattr(fx, '_batch_outset', 0.0) or 0.0))
    visual = getattr(obj, "visual", None)
    multipass = False
    if visual is not None:
        extra = getattr(visual, "_cull_outset", None)
        if extra is not None:
            try:
                base = max(base, float(extra))
            except (TypeError, ValueError):
                pass
        try:
            multipass = bool(getattr(visual, "_is_multipass", False))
        except Exception:
            multipass = False
    glow = getattr(obj, "_glow", None)
    if glow is not None:
        extra = getattr(glow, "_cull_outset", None)
        if extra is not None:
            try:
                base = max(base, float(extra))
            except (TypeError, ValueError):
                pass
    pad = base
    try:
        lw = float(getattr(obj, 'line_width', 0) or 0)
        if lw:                          # the join / cap probe only for a stroke
            pad += 0.5 * lw * _stroke_reach_factor(obj)
    except Exception:
        pass
    if multipass:
        pad += _MULTIPASS_CULL_PAD
    if getattr(obj, "_tail", None) is not None:
        pad += _MULTIPASS_CULL_PAD
    return pad


_plain_blit_draws = 0


def _has_any_batchable_filter(obj) -> bool:
    """True when fill or line has an ImageFilter.

    ``_batch_key is None`` means “do not share a layer”, not “no filter”.
    Sprite blits never attach ImageFilters to the paint — those hosts must
    still enter the saveLayer / shape-FX RT path.
    """
    ff = getattr(obj, "fill_filter", None)
    if ff is not None and getattr(ff, "_skia_filter", None) is not None:
        return True
    lf = getattr(obj, "line_filter", None)
    if lf is not None and getattr(lf, "_skia_filter", None) is not None:
        return True
    return False


_CHEAP_GLOW = None
_HAS_ACTIVE_TRANSIENT = None


def _fx_draw_helpers():
    """Lazy module refs so the draw walk does not import per object."""
    global _CHEAP_GLOW, _HAS_ACTIVE_TRANSIENT
    if _CHEAP_GLOW is None:
        from .visuals import CheapGlow
        from .transients import has_active_transient
        _CHEAP_GLOW = CheapGlow
        _HAS_ACTIVE_TRANSIENT = has_active_transient
    return _CHEAP_GLOW, _HAS_ACTIVE_TRANSIENT


def _must_solo_draw(obj) -> bool:
    """True when full ``obj.draw`` is required (multipass, CheapGlow, or transients).

    Tail is not solo: ImageFilter glow/shadow stay on the interned saveLayer
    path; unfiltered ghosts are drawn in a pre-pass on that segment.
    """
    if getattr(type(obj), "_draws_solo", False):
        return True   # draws its own envelope (SpriteButton feel)
    CheapGlow, _has_transient = _fx_draw_helpers()
    if isinstance(getattr(obj, "_glow", None), CheapGlow):
        return True
    visual = getattr(obj, "visual", None)
    if visual is not None and getattr(visual, "_is_multipass", False):
        return True
    try:
        _cheap, has_active_transient = _fx_draw_helpers()
        return has_active_transient(obj)
    except Exception:
        return False


def _look_pass_groupable(obj) -> bool:
    """Interned stroke Recipe eligible for pass-major grouping on this layer.

    Sprites, stamps, CheapGlow, and transients stay on ``obj.draw``. Escape is
    ``batch_shared_filters=False`` (``fx_quality="max"``).
    """
    visual = getattr(obj, "visual", None)
    if visual is None or not getattr(visual, "_look_pass_group", False):
        return False
    if getattr(obj, "_plain_blit", False) or getattr(type(obj), "_draws_solo", False):
        return False
    if getattr(type(obj), "_is_sprite_body", False):
        return False
    if getattr(obj, "_glow", None) is not None:
        return False
    if getattr(obj, "_shadow", None) is not None:
        return False
    if getattr(obj, "_hue", None) is not None:
        return False
    if getattr(obj, "_gray", None) is not None:
        return False
    if getattr(obj, "_tail", None) is not None:
        return False
    try:
        _cheap, has_active_transient = _fx_draw_helpers()
        if has_active_transient(obj):
            return False
    except Exception:
        pass
    return True


def _overlay_glow_groupable(obj) -> bool:
    """Interned Electric* overlay bloom — eligible for a shared Plus plate."""
    visual = getattr(obj, "visual", None)
    return bool(visual is not None and getattr(visual, "_overlay_glow_batch", False))


@dataclass(frozen=True)
class VisibleBounds:
    """Axis-aligned world-space rectangle currently filling the design view.

    ``top`` is the visual top (larger y in y-up authoring space).
    ``bottom`` is ``top - height`` (smaller y).
    """
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top - self.height

    @property
    def center(self) -> Tuple[float, float]:
        return (self.left + self.width * 0.5, self.top - self.height * 0.5)


class Canvas(ClosedSurface, Container):
    """Author-facing canvas API (design size, background, camera).

    Wraps the internal :class:`ScenaCanvas` engine. The global ``canvas`` object
    is an instance of this class.
    """

    _closed_who = "canvas"

    def __init__(self, engine: 'ScenaCanvas'):
        # A Container, like ``mouse`` / ``clock`` / ``keyp``: a formula that
        # reads ``canvas.zoom`` / ``pan_x`` / ``game_view`` / ``layers[…].view``
        # registers the canvas as its source, and the engine calls
        # ``update()`` whenever the camera, a layer's scroll or the design
        # size changes (``ScenaCanvas._notify_view_changed``). Unused: A2
        # skips ``mark_dirty`` until something links to it.
        super().__init__()
        self._engine = engine
        engine._author_facade = self

    def _update_impl(self) -> None:
        pass                              # nothing derived here: the engine holds the camera

    def _takein_impl(self, new_value):
        raise TypeError(
            "canvas is the stage — cannot takein; move the camera with canvas.pan_to / "
            "zoom_to, or link from formulas with lambda: canvas.game_view.center"
        )

    # --- design size (read-only; set via init()) --------------------------------

    @property
    def width(self) -> float:
        """Design-space width (``init(width=)``). Read-only."""
        return self._engine.width

    @property
    def height(self) -> float:
        """Design-space height (``init(height=)``). Read-only."""
        return self._engine.height

    @property
    def aspect_ratio(self) -> float:
        """Design width / height. Read-only."""
        return self._engine.aspect_ratio

    # --- background ------------------------------------------------------------

    @property
    def background(self):
        """Background stack facade (always-present ``base`` + extra fields).

        Reading returns the stack (``.add``, ``.clear``, ``.base``, ``.reset_base``).
        Assigning replaces **base** with a color name, RGB tuple, ``Color``,
        ``Gradient``, ``Texture``, image file, or a wallpaper field. Assigning
        the stack itself (``canvas.background = canvas.background``) keeps it.
        """
        from .orchestration import ScenaFramework
        return ScenaFramework.get_instance().background_stack

    @background.setter
    def background(self, value) -> None:
        from .orchestration import ScenaFramework
        from .background import wrap_background_source
        stack = ScenaFramework.get_instance().background_stack
        if value is stack:
            # canvas.background = canvas.background: the read is the live stack,
            # so writing it back keeps everything (it used to raise TypeError).
            return
        stack.base = wrap_background_source(value)

    @property
    def batch_shared_filters(self) -> bool:
        """When True, batch shapes that share a fill/line filter into saveLayers."""
        return self._engine.batch_shared_filters

    @batch_shared_filters.setter
    def batch_shared_filters(self, value: bool) -> None:
        flag = bool(value)
        self._engine.batch_shared_filters = flag
        from .orchestration import ScenaFramework
        ScenaFramework.get_instance().batch_shared_filters = flag

    @property
    def post_fx_scale(self) -> float:
        """Resolution scale for canvas-wide post FX (1.0 full, 0.5 half, …).

        Prefer :attr:`fx_quality` for a coordinated preset. Scene geometry still
        renders at full framebuffer resolution.
        """
        from .orchestration import ScenaFramework
        return float(ScenaFramework.get_instance().post_fx_scale)

    @post_fx_scale.setter
    def post_fx_scale(self, value: float) -> None:
        from .orchestration import ScenaFramework
        v = float(value)
        if v <= 0.0 or v > 1.0:
            raise ValueError("post_fx_scale must be in (0, 1]")
        ScenaFramework.get_instance().post_fx_scale = v

    @property
    def shape_fx_scale(self) -> float:
        """Resolution scale for shape fill/line ImageFilters (glow/blur/shadow)."""
        return float(self._engine.shape_fx_scale)

    @shape_fx_scale.setter
    def shape_fx_scale(self, value: float) -> None:
        v = float(value)
        if v <= 0.0 or v > 1.0:
            raise ValueError("shape_fx_scale must be in (0, 1]")
        self._engine.shape_fx_scale = v
        from .orchestration import ScenaFramework
        ScenaFramework.get_instance().shape_fx_scale = v

    @property
    def fx_quality(self):
        """Coordinated FX quality preset (:class:`~scena.fx_quality.FxQuality`)."""
        from .orchestration import ScenaFramework
        return ScenaFramework.get_instance().fx_quality

    @fx_quality.setter
    def fx_quality(self, value) -> None:
        from .orchestration import ScenaFramework
        ScenaFramework.get_instance().fx_quality = value

    @property
    def framerate(self):
        """How frames are paced: ``"vsync60"`` (default), ``"vsync30"``,
        ``"vsync"``, ``"max"``, or a fixed fps (``60``, ``30``, …).

        ``"vsync60"`` locks to the display at the vblank divisor nearest 60 Hz
        (60 Hz → every vblank, 120 → every 2nd, 144 → 72 Hz); ``"vsync30"``
        at twice that interval; ``"vsync"`` at every vblank (full refresh);
        ``"max"`` is uncapped. A number is a fixed-rate timer: it does not
        follow the display, so it can judder now and then. Assigning turns FX
        Auto off; while Auto is on, this reads the rung's token. A bad value
        raises before anything changes.
        """
        from .orchestration import ScenaFramework
        return ScenaFramework.get_instance().framerate

    @framerate.setter
    def framerate(self, value) -> None:
        from .orchestration import ScenaFramework
        ScenaFramework.get_instance().framerate = value

    @property
    def display(self) -> str:
        """OS window mode: ``"windowed"``, ``"maximized"``, or ``"fullscreen"``.

        Assignment is absolute (not a toggle). Before ``run()`` this stores
        intent and applies at window open; after, it takes the same path as
        Ctrl+Shift+M / F.
        """
        from .orchestration import ScenaFramework
        return ScenaFramework.get_instance().display

    @display.setter
    def display(self, value) -> None:
        from .orchestration import ScenaFramework
        ScenaFramework.get_instance().display = value

    @property
    def effects(self):
        """Canvas-wide post-FX stack (:class:`~scena.postfx.PostFxStack`)."""
        from .orchestration import ScenaFramework
        return ScenaFramework.get_instance().post_fx_stack

    def set_fly(self, field=None) -> "Canvas":
        """Replace the extra background stack with a single fly field (or clear).

        Sugar over ``canvas.background.set_fly``. Pass ``None`` to clear.
        Does not touch ``canvas.background.base``.
        """
        self.background.set_fly(field)
        return self

    def fade_out(
        self,
        duration: float = 0.5,
        *,
        color="black",
        style: str = "fade",
        angle: float = 0.0,
        center=None,
        on_done=None,
    ) -> "Canvas":
        """Cover the picture (default black) and **hold** until ``fade_in``.

        Drawn after widgets (covers HUD). Not a ``canvas.effects`` post.
        ``style``: ``"fade"`` (default) · ``"wipe"`` · ``"iris"``.
        ``angle`` is wipe direction in degrees (0 = +x). ``center`` is iris
        only (design coords; omit = frame center). ``on_done`` is the call
        channel; there is no ``then=``.
        """
        from .cover import get_cover
        get_cover().fade_out(
            duration, color=color, style=style, angle=angle,
            center=center, on_done=on_done,
        )
        return self

    def fade_in(
        self,
        duration: float = 0.5,
        *,
        color=None,
        style=None,
        angle=None,
        center=None,
        on_done=None,
    ) -> "Canvas":
        """Uncover from the current hold (or from a full cover if none).

        Opening ``fade_in`` with no prior cover snaps to full cover first,
        then reveals. Omit ``color`` / ``style`` to keep the current look.
        """
        from .cover import get_cover
        get_cover().fade_in(
            duration, color=color, style=style, angle=angle,
            center=center, on_done=on_done,
        )
        return self

    @property
    def covered(self) -> float:
        """Cover amount, 0 uncovered … 1 fully covered (holds after fade_out)."""
        from .cover import get_cover
        return get_cover().amount

    def flash(self, intensity: float = 0.6) -> "Canvas":
        """Trigger a brief white flash (hit feedback)."""
        from .validate import magnitude, fixed_magnitude
        self.effects._hit_feedback().flash(fixed_magnitude(intensity, "canvas.flash intensity"))
        return self

    def shake(self, amount: float = 10.0) -> "Canvas":
        """Trigger a brief camera shake (hit feedback)."""
        from .validate import fixed_magnitude
        self.effects._hit_feedback().shake(fixed_magnitude(amount, "canvas.shake amount"))
        return self

    def glitch(self, amount: float = 1.0) -> "Canvas":
        """Trigger a brief slice / RGB-split glitch (hit feedback)."""
        from .validate import fixed_magnitude
        self.effects._hit_feedback().glitch(fixed_magnitude(amount, "canvas.glitch amount"))
        return self

    def ripple_at(
        self,
        x,
        y=None,
        amount: float = 1.0,
        radius: Optional[float] = None,
        *,
        shock: bool = True,
        flash: bool = False,
        shake: bool = True,
    ) -> "Canvas":
        """Trigger a screen-warp ripple at a world locus.

        ``(x, y)`` or one point-like (tuple, Point, Vec2, Graphic, CollisionInfo).
        World coordinates (sprite ``.center``, ``info.point``) map through the
        camera (pan/zoom/rotate) and debug zoom onto the view.
        ``None`` / missing ``info.point`` is a no-op. Remaining knobs after a
        point-like are keyword-only (``amount=``, ``radius=``).

        ``amount`` is warp / shake magnitude. ``radius`` is peak radius in
        design units (``None`` = full-frame default).
        ``shock=True`` (default) draws the expanding accent ring; the
        screen-warp still runs when ``shock=False``.
        ``shake=True`` (default) adds camera shake.
        ``flash=True`` adds a brief whiteout (off by default).
        """
        from .validate import fixed_magnitude, expect_bool
        xy = _at_xy(x, y)
        amt = fixed_magnitude(amount, "canvas.ripple_at amount")
        rad = (None if radius is None
               else fixed_magnitude(radius, "canvas.ripple_at radius", positive=True))
        sk = expect_bool(shock, "canvas.ripple_at shock")
        fl = expect_bool(flash, "canvas.ripple_at flash")
        sh = expect_bool(shake, "canvas.ripple_at shake")
        if xy is None:
            return self
        self.effects._hit_feedback().ripple_at(
            xy[0], xy[1], amount=amt, radius=rad, shock=sk, flash=fl, shake=sh,
        )
        return self

    def wave_at(
        self,
        x,
        y=None,
        angle: float = 0.0,
        amount: float = 1.0,
        *,
        shock: bool = True,
        flash: bool = False,
        shake: bool = True,
    ) -> "Canvas":
        """Trigger a linear shockwave at a world locus.

        ``(x, y)`` or one point-like (see :meth:`ripple_at`). ``None`` is a no-op.

        ``angle`` is degrees (0 = +X / right). ``shock=True`` (default) draws
        the expanding accent band; the screen-warp still runs when
        ``shock=False``. ``shake=True`` (default) adds camera shake.
        ``flash=True`` adds whiteout.
        """
        from .validate import number, fixed_magnitude, expect_bool
        xy = _at_xy(x, y)
        ang = number(angle, "canvas.wave_at angle")
        amt = fixed_magnitude(amount, "canvas.wave_at amount")
        sk = expect_bool(shock, "canvas.wave_at shock")
        fl = expect_bool(flash, "canvas.wave_at flash")
        sh = expect_bool(shake, "canvas.wave_at shake")
        if xy is None:
            return self
        self.effects._hit_feedback().wave_at(
            xy[0], xy[1], angle=ang, amount=amt, shock=sk, flash=fl, shake=sh,
        )
        return self

    def explosion_at(
        self,
        x,
        y=None,
        amount: float = 1.2,
        *,
        shock: bool = True,
        flash: bool = False,
        shake: bool = True,
        rings: bool = True,
    ) -> "Canvas":
        """Trigger a cinematic explosion at a world locus.

        ``(x, y)`` or one point-like (tuple, Point, Vec2, Graphic,
        CollisionInfo). ``None`` / missing ``info.point`` is a no-op.
        After a point-like, pass ``amount=`` by name.

        ``shock=True`` includes a weak screen-warp ripple (smaller than
        :meth:`ripple_at`, matched to the fireball).
        ``rings=True`` (default) draws expanding stroke circles.
        ``flash=True`` adds a brief whiteout (off by default).
        ``shake=True`` (default) adds camera shake — set False to compare pyro only.
        For local multi-instance pops (ships, crates), use :meth:`burst_at`.
        """
        from .validate import fixed_magnitude, expect_bool
        xy = _at_xy(x, y)
        amt = fixed_magnitude(amount, "canvas.explosion_at amount")
        sk = expect_bool(shock, "canvas.explosion_at shock")
        fl = expect_bool(flash, "canvas.explosion_at flash")
        sh = expect_bool(shake, "canvas.explosion_at shake")
        rg = expect_bool(rings, "canvas.explosion_at rings")
        if xy is None:
            return self
        self.effects._hit_feedback().explosion_at(
            xy[0], xy[1], amount=amt, shock=sk, flash=fl, shake=sh, rings=rg,
        )
        return self

    def burst_at(
        self,
        x,
        y=None,
        radius: float = 42.0,
        amount: float = 1.2,
        *,
        rings: bool = False,
    ) -> "Canvas":
        """Trigger a local explosion at a world locus.

        ``(x, y)`` or one point-like (see :meth:`explosion_at`). ``None`` is a no-op.
        After a point-like, pass ``radius=`` by name.

        Sized by design-unit ``radius`` (ship-scale). No camera shake, flash,
        or screen warp. Multiple bursts can run at once.
        ``rings=True`` draws expanding stroke circles (off by default).
        """
        from .validate import fixed_magnitude, expect_bool
        xy = _at_xy(x, y)
        rad = fixed_magnitude(radius, "canvas.burst_at radius", positive=True)
        amt = fixed_magnitude(amount, "canvas.burst_at amount")
        rg = expect_bool(rings, "canvas.burst_at rings")
        if xy is None:
            return self
        self.effects._hit_feedback().burst_at(
            xy[0], xy[1], radius=rad, amount=amt, rings=rg,
        )
        return self

    def bubbles_at(
        self,
        x,
        y=None,
        color=None,
        *,
        count: int = 18,
        height: float = 140.0,
        amount: float = 1.0,
    ) -> "Canvas":
        """Rising bubble plume at a world locus.

        ``(x, y)`` or one point-like (see :meth:`explosion_at`). ``None`` is a no-op.

        Bubbles climb ~``height`` design units, then fade / pop. See also
        :meth:`bubbles` for a multi-column canvas-wide cascade.
        """
        from .validate import fixed_magnitude, count as _count
        xy = _at_xy(x, y)
        n = _count(count, "canvas.bubbles_at count", 1)
        h = fixed_magnitude(height, "canvas.bubbles_at height", positive=True)
        amt = fixed_magnitude(amount, "canvas.bubbles_at amount")
        if xy is None:
            return self
        self.effects._hit_feedback().bubbles_at(
            xy[0], xy[1], color, count=n, height=h, amount=amt,
        )
        return self

    def fireworks_at(
        self,
        x,
        y=None,
        color=None,
        *,
        color2=None,
        radius: float = 64.0,
        amount: float = 1.0,
        count: int = 28,
        fall: float = 0.0,
        trail: float = 0.35,
    ) -> "Canvas":
        """Celebration burst of falling stars at a world locus.

        ``(x, y)`` or one point-like (see :meth:`explosion_at`). ``None`` is a no-op.

        Opens at that point (no mortar). Distinct from :meth:`burst_at`
        (fireball) and SpatialFx ``Sparks`` (sticky crackle). No shake,
        flash, or shock. ``fall=0`` (default) is a peony — no droop;
        ``~1.2`` is a willow. ``color2=None`` derives near-white glitter
        from ``color``.
        """
        from .validate import fixed_magnitude, count as _count
        xy = _at_xy(x, y)
        rad = fixed_magnitude(radius, "canvas.fireworks_at radius", positive=True)
        amt = fixed_magnitude(amount, "canvas.fireworks_at amount")
        n = _count(count, "canvas.fireworks_at count", 1)
        fa = fixed_magnitude(fall, "canvas.fireworks_at fall")
        tr = fixed_magnitude(trail, "canvas.fireworks_at trail")
        if xy is None:
            return self
        self.effects._hit_feedback().fireworks_at(
            xy[0], xy[1], color, color2=color2, radius=rad, amount=amt,
            count=n, fall=fa, trail=tr,
        )
        return self

    def zap_at(
        self,
        x,
        y=None,
        color=None,
        *,
        radius: float = 24.0,
        amount: float = 1.0,
        count=None,
        style: str = "spark",
        flash: bool = False,
    ) -> "Canvas":
        """Electric spark / lightning flash at a world locus.

        ``(x, y)`` or one point-like (see :meth:`explosion_at`). ``None`` is a no-op.

        Bright core + jagged rays (between Bolt tesla and ElectricBolt).
        Styles: ``spark`` (default impact), ``fork`` (branched bolts),
        ``corona`` (expanding crackle ring). Design-unit ``radius`` defaults
        to 24. No shake / shock. ``flash`` toggles a brief whiteout.
        Distinct from SpatialFx ``Sparks``.
        """
        from .validate import fixed_magnitude, count as _count, expect_bool
        from .effects import _zap_style
        xy = _at_xy(x, y)
        rad = fixed_magnitude(radius, "canvas.zap_at radius", positive=True)
        amt = fixed_magnitude(amount, "canvas.zap_at amount")
        n = None if count is None else _count(count, "canvas.zap_at count", 1)
        st = _zap_style(style)
        fl = expect_bool(flash, "canvas.zap_at flash")
        if xy is None:
            return self
        self.effects._hit_feedback().zap_at(
            xy[0], xy[1], color, radius=rad, amount=amt, count=n,
            style=st, flash=fl,
        )
        return self

    def hit_at(
        self,
        x,
        y=None,
        color=None,
        *,
        angle: Optional[float] = None,
        radius: float = 16.0,
        amount: float = 1.0,
        count: Optional[int] = None,
        style: str = "star",
    ) -> "Canvas":
        """Impact mark at a world locus: something was struck and lives on.

        ``(x, y)`` or one point-like (see :meth:`explosion_at`). ``None`` is a no-op.

        A white-hot star, a thin ring, and short spark streaks — about a
        fifth of a second. ``style="disc"`` is the light version: a round
        pop of light, no sparks. Pair it with the body's own reaction
        (``hero.flash()``, ``hero.knock(...)``). No shake / flash / warp;
        many can run at once (a boss under fire).

        Args:
            x: World x, or one point-like (``info``, a Graphic, a Point, ``(x, y)``).
            y: World y when ``x`` is a number.
            color: Rim / spark tint (default warm white). The core stays white.
            angle: Spark direction in world degrees (0 = right, 90 = up); the
                sparks spray in a ~100° cone. ``None`` (default) sprays all
                around. Never read from ``info`` — its normal flips with the
                ``@collide`` argument order.
            radius: Size in design units (default 16).
            amount: Brightness / punch (default 1).
            count: Spark streaks (default 8). ``0`` keeps the star and the
                ring with no sparks.
            style: ``"star"`` (default) is the mark above; ``"disc"`` is a
                round pop of light that opens and fades — no sparks and no
                direction, so ``angle=`` / ``count=`` with it raise.
        """
        from .validate import number, fixed_magnitude, count as _count
        from .effects import _hit_spec
        xy = _at_xy(x, y)
        ang = None if angle is None else number(angle, "canvas.hit_at angle")
        rad = fixed_magnitude(radius, "canvas.hit_at radius", positive=True)
        amt = fixed_magnitude(amount, "canvas.hit_at amount")
        n = None if count is None else _count(count, "canvas.hit_at count", 0)
        st = _hit_spec(style, ang, n, what="canvas.hit_at")
        if xy is None:
            return self
        self.effects._hit_feedback().hit_at(
            xy[0], xy[1], color, angle=ang, radius=rad, amount=amt, count=n,
            style=st,
        )
        return self

    def debris_at(
        self,
        x,
        y=None,
        color=None,
        *,
        radius: float = 40.0,
        amount: float = 1.0,
        count: int = 14,
        fall: float = 0.0,
        dust: bool = True,
    ) -> "Canvas":
        """Matte debris spray at a world locus: it broke into pieces (no fire).

        ``(x, y)`` or one point-like (see :meth:`explosion_at`). ``None`` is a no-op.

        Irregular shards fly out, tumble, then shrink and fade, over a soft
        dust puff. Not emissive, so it reads on bright backgrounds. Chain it
        with :meth:`burst_at` for a ship that blows apart, or :meth:`hit_at`
        for a rock that cracks. Pieces are paint only — they do not collide.
        The color is never taken from a Graphic locus; pass ``color=``.

        Args:
            x: World x, or one point-like (``info``, a Graphic, a Point, ``(x, y)``).
            y: World y when ``x`` is a number.
            color: Shard color (default stone grey). Dust is a lighter mix.
            radius: Spread size in design units (default 40).
            amount: Force — how far the pieces fly (default 1).
            count: Shards (default 14).
            fall: Gravity. ``0`` (default) drifts (space, top-down);
                ``~1`` arcs down (platformer).
            dust: Soft dust puffs under the shards (default True; skipped
                at low quality).
        """
        from .validate import fixed_magnitude, count as _count, expect_bool
        xy = _at_xy(x, y)
        rad = fixed_magnitude(radius, "canvas.debris_at radius", positive=True)
        amt = fixed_magnitude(amount, "canvas.debris_at amount")
        n = _count(count, "canvas.debris_at count", 1)
        fl = fixed_magnitude(fall, "canvas.debris_at fall")
        du = expect_bool(dust, "canvas.debris_at dust")
        if xy is None:
            return self
        self.effects._hit_feedback().debris_at(
            xy[0], xy[1], color, radius=rad, amount=amt, count=n, fall=fl, dust=du,
        )
        return self

    def bubbles(
        self,
        color=None,
        *,
        count: int = 36,
        columns: int = 5,
        height: float = 180.0,
        amount: float = 1.0,
    ) -> "Canvas":
        """Canvas-wide rising bubble cascade (transient overlay)."""
        from .validate import fixed_magnitude, count as _count
        n = _count(count, "canvas.bubbles count", 1)
        cols = _count(columns, "canvas.bubbles columns", 1)
        h = fixed_magnitude(height, "canvas.bubbles height", positive=True)
        amt = fixed_magnitude(amount, "canvas.bubbles amount")
        self.effects._hit_feedback().bubbles(
            color, count=n, columns=cols, height=h, amount=amt,
        )
        return self

    @property
    def cull_offscreen(self) -> bool:
        """Skip **draw** of shapes whose AABB is outside the current view.

        Default **False** (safe for edged beams, glow bleed, small scenes).
        Enable for large worlds whose off-camera objects are expensive to
        draw (glow, multipass visuals): the per-object test costs about as
        much as drawing a plain sprite, so a world of plain sprites runs
        slower with it on (Canvas Design, "Offscreen culling"). Draw-only: tick,
        formulas, collision, and SpatialFx simulation still run. Approximate
        AABB + filter / transient / multipass pads. Parallax (non-neutral)
        layers are never culled — their partial camera CTM is not
        ``visible_bounds``. Widgets, background fields, and canvas post are
        not on this path.
        """
        return self._engine.cull_offscreen

    @cull_offscreen.setter
    def cull_offscreen(self, value: bool) -> None:
        self._engine.cull_offscreen = bool(value)

    def shape_fx_surface_stats(self) -> dict:
        """Shape-FX RT pool counters (``allocs`` / ``reuses`` / ``pool`` size).

        Reset with :meth:`reset_shape_fx_surface_stats` before a timed run.
        """
        eng = self._engine
        return {
            "allocs": int(getattr(eng, "_shape_fx_allocs", 0) or 0),
            "reuses": int(getattr(eng, "_shape_fx_reuses", 0) or 0),
            "pool": len(getattr(eng, "_shape_fx_pool", []) or []),
        }

    def reset_shape_fx_surface_stats(self) -> None:
        eng = self._engine
        eng._shape_fx_allocs = 0
        eng._shape_fx_reuses = 0

    # --- camera state ----------------------------------------------------------

    @property
    def zoom(self) -> float:
        """Current camera zoom (1 = no zoom). Change it with ``zoom_to`` / ``zoom_by``."""
        return self._engine.zoom

    @zoom.setter
    def zoom(self, value) -> None:
        raise AttributeError(
            f"canvas.zoom is read-only. Write canvas.zoom_to({value!r}) "
            f"(or canvas.zoom_to({value!r}, time=0.5) to animate)."
        )

    @property
    def pan_x(self) -> float:
        """World X currently under the canvas center."""
        return self._engine.pan_x

    @pan_x.setter
    def pan_x(self, value) -> None:
        raise AttributeError(
            f"canvas.pan_x is read-only. Write canvas.pan_to({value!r}, canvas.pan_y)."
        )

    @property
    def pan_y(self) -> float:
        """World Y currently under the canvas center."""
        return self._engine.pan_y

    @pan_y.setter
    def pan_y(self, value) -> None:
        raise AttributeError(
            f"canvas.pan_y is read-only. Write canvas.pan_to(canvas.pan_x, {value!r})."
        )

    @property
    def pan_rest_x(self) -> float:
        """Look-at X that is zero offset for background parallax (last set_origin/reset)."""
        return self._engine.pan_rest_x

    @property
    def pan_rest_y(self) -> float:
        """Look-at Y that is zero offset for background parallax (last set_origin/reset)."""
        return self._engine.pan_rest_y

    @property
    def rotation(self) -> float:
        """Camera rotation in degrees."""
        return self._engine.rotation

    @property
    def game_view(self):
        """Window in world units (camera frustum) as a fresh ``Box``.

        A measured Box (``Box._snapshot``): read every frame, its points
        stay off the reactive graph (Box Design, "Measured boxes are lazy").
        In a formula (``c["center"] @= lambda: canvas.game_view.center``) the
        source is ``canvas`` itself: the value follows every camera move.
        """
        from .box import Box
        vb = self._engine.visible_bounds
        return Box._from_aabb(vb.left, vb.bottom, vb.right, vb.top)

    @property
    def ui_view(self):
        """Window in view units (camera-immune HUD) as a fresh ``Box``."""
        from .box import Box
        w, h = float(self.width), float(self.height)
        return Box._from_aabb(0.0, 0.0, w, h)

    @property
    def playfield(self) -> "BoundsPlayfield":
        """World-fixed playfield AABB for ``@leave_playfield`` (default 1.5× design rect)."""
        return self._engine.bounds

    @property
    def bounds(self) -> "BoundsPlayfield":
        """Alias of ``playfield`` (leave-area config). Prefer ``canvas.playfield``."""
        return self.playfield

    # --- camera transforms (chainable; time= returns Handle) -------------------

    def zoom_to(
        self,
        factor: float,
        *,
        about=None,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Set the zoom to ``factor`` (1 = no zoom). ``about=`` keeps that point still.

        Instant without ``time=``; with ``time=`` it animates and returns a Handle (``ease=`` / ``then=`` / ``on_done=`` / ``loops=`` / ``yoyo=``).
        """
        if time is not None:
            return timed_camera_zoom_to(
                self, factor, time=time, about=about, ease=ease, then=then, on_done=on_done,
                loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="zoom_to")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="zoom_to")
        self._engine.zoom_to(factor, about=about)
        return self

    def zoom_by(
        self,
        factor: float,
        *,
        about=None,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Multiply the zoom by ``factor`` (2 = twice as close). ``about=`` keeps that point still.

        Instant without ``time=``; with ``time=`` it animates and returns a Handle (``ease=`` / ``then=`` / ``on_done=`` / ``loops=`` / ``yoyo=``).
        """
        if time is not None:
            return timed_camera_zoom_by(
                self, factor, time=time, about=about, ease=ease, then=then, on_done=on_done,
                loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="zoom_by")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="zoom_by")
        self._engine.zoom_by(factor, about=about)
        return self

    def pan_to(
        self,
        x,
        y=None,
        *,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Place a world point under the canvas center.

        Two numbers ``(x, y)``, or one point-like: ``(x, y)`` tuple, Point,
        Vec2, Graphic (``.center``), or an object with ``.x``/``.y``.
        With ``time=``, the destination freezes at call time (not follow-cam).
        """
        x, y = _look_xy(x, y)
        if time is not None:
            return timed_camera_pan_to(
                self, x, y, time=time, ease=ease, then=then, on_done=on_done,
                loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="pan_to")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="pan_to")
        self._engine.pan_to(x, y)
        return self

    def pan_by(
        self,
        dx,
        dy=None,
        *,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Shift content by ``(dx, dy)`` in world/design units.

        Two numbers, or one Vec2 / ``(dx, dy)`` tuple. A Point or Graphic is
        a location — use ``pan_to``.
        """
        dx, dy = _delta_xy(dx, dy)
        if time is not None:
            return timed_camera_pan_by(
                self, dx, dy, time=time, ease=ease, then=then, on_done=on_done,
                loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="pan_by")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="pan_by")
        self._engine.pan_by(dx, dy)
        return self

    def set_origin(
        self,
        where: str = 'corner',
        *,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Pan so world ``(0, 0)`` sits at a standard place in the view.

        ``where``:
          - ``'corner'`` / ``'bottom_left'`` — origin at the bottom-left of the
            design view (default / identity pan: look-at = design center)
          - ``'center'`` — origin under the middle of the window
            (look-at = ``(0, 0)``)

        Does not change zoom or rotation. For a full identity camera, use
        ``reset_view()``. With ``time=``, rest look tracks look for the whole
        tween (parallax offset stays 0).
        """
        if time is not None:
            return timed_camera_set_origin(
                self, where, time=time, ease=ease, then=then, on_done=on_done,
                loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="set_origin")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="set_origin")
        self._engine.set_origin(where)
        return self

    def rotate_to(
        self,
        angle: float,
        *,
        about=None,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Turn the camera to ``angle`` degrees (absolute). ``about=`` picks the pivot.

        Instant without ``time=``; with ``time=`` it animates and returns a Handle (``ease=`` / ``then=`` / ``on_done=`` / ``loops=`` / ``yoyo=``).
        """
        if time is not None:
            return timed_camera_rotate_to(
                self, angle, time=time, about=about, ease=ease, then=then, on_done=on_done,
                loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="rotate_to")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="rotate_to")
        self._engine.rotate_to(angle, about=about)
        return self

    def rotate_by(
        self,
        angle: float,
        *,
        about=None,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Turn the camera by ``angle`` degrees (relative). ``about=`` picks the pivot.

        Instant without ``time=``; with ``time=`` it animates and returns a Handle (``ease=`` / ``then=`` / ``on_done=`` / ``loops=`` / ``yoyo=``).
        """
        if time is not None:
            return timed_camera_rotate_by(
                self, angle, time=time, about=about, ease=ease, then=then, on_done=on_done,
                loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="rotate_by")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="rotate_by")
        self._engine.rotate_by(angle, about=about)
        return self

    def frame_to(
        self,
        target,
        *,
        pad: float = 0.0,
        rotate: bool = False,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Fit ``target`` in view (zoom + pan; optional align-rotate).

        ``target`` may be a Rect-like object (``.center``, ``.width``, ``.height``,
        optional ``.angle``), an ``(left, top, width, height)`` tuple, or ``None``.
        ``None`` means nothing to frame: hold the current view (untimed returns
        ``canvas``; timed is an identity Handle for the full ``time=``).
        ``pad`` is a fraction of the target size on each side (e.g. ``0.1`` →
        10% margin → size ``× (1+2p)``). Negative ``pad`` tightens the frame.
        World-unit air is composition: ``frame_to(box.outset(40))``.
        """
        if target is None and time is None:
            return self  # nothing to frame; hold current view
        if time is not None:
            return timed_camera_frame_to(
                self, target, time=time, pad=pad, rotate=rotate,
                ease=ease, then=then, on_done=on_done, loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="frame_to")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="frame_to")
        self._engine.frame_to(target, pad=pad, rotate=rotate)
        return self

    def reset_view(
        self,
        *,
        time: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        loops: object = 1,
        yoyo: bool = False,
    ):
        """Put the camera back: no pan, rotation 0, zoom 1.

        Instant without ``time=``; with ``time=`` it animates and returns a Handle (``ease=`` / ``then=`` / ``on_done=`` / ``loops=`` / ``yoyo=``).
        """
        if time is not None:
            return timed_camera_reset_view(
                self, time=time, ease=ease, then=then, on_done=on_done,
                loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="reset_view")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="reset_view")
        self._engine.reset_view()
        return self

    # --- layers ----------------------------------------------------------------

    @property
    def layers(self) -> LayersFacade:
        """Author-facing layer management (create / default / using; per-layer ops via ``canvas.layers[name]``)."""
        return LayersFacade(self._engine.registry)


class ScenaCanvas:
    """Internal drawing engine: layers, Skia surface, camera matrix.

    Authors should use the global :class:`Canvas` facade (``canvas``), not this
    class directly.
    """

    _current_canvas = None  # Class variable to store current canvas
    _plain_blit_draws = 0

    @classmethod
    def get_current(cls) -> 'ScenaCanvas':
        """Returns the current active canvas engine."""
        if cls._current_canvas is None:
            raise RuntimeError("No canvas is currently active")
        return cls._current_canvas

    @classmethod
    def set_current(cls, canvas: 'ScenaCanvas') -> None:
        """Sets the current active canvas engine."""
        cls._current_canvas = canvas

    def __init__(
        self,
        skia_canvas,
        background_color=(0, 0, 0),
        width: float | None = None,
        height: float | None = None,
        pixel_ratio: float = 1.0,
    ):
        self.skia_canvas = skia_canvas

        # Registry (ids, groups) + layer stack (draw / hit order)
        self.registry = Registry()

        # Design size = stable authored coordinates (injected by ScenaFramework).
        # Do not derive from the Skia surface (that is framebuffer pixels).
        # view_scale and pixel_ratio are applied by the Skia CTM in orchestration;
        # camera (zoom/pan/rotate) lives here and is composed into that CTM.
        if width is None or height is None:
            surface_width, surface_height = skia_canvas.getBaseLayerSize()
            pr = pixel_ratio if pixel_ratio else 1.0
            width = surface_width / pr if width is None else width
            height = surface_height / pr if height is None else height

        self.width = float(width)
        self.height = float(height)
        self.aspect_ratio = self.width / self.height if self.height else 1.0
        self.pixel_ratio = pixel_ratio if pixel_ratio else 1.0

        # Camera: look-at (world point under design center) + uniform zoom + rotation.
        # Identity → _camera_active is False (draw/mouse skip the camera entirely).
        # When active, _camera_matrix is rebuilt only on mutation (not every frame).
        self._zoom = 1.0
        self._look_x = self.width * 0.5
        self._look_y = self.height * 0.5
        # Composition rest look for background parallax (updated by set_origin /
        # reset_view). Parallax offsets are relative to this, not absolute center.
        self._look_rest_x = self._look_x
        self._look_rest_y = self._look_y
        self._rotation = 0.0
        self._camera_active = False
        self._camera_matrix = skia.Matrix()  # identity while inactive

        # Draw opts; ``batch_shared_filters`` is owned by ``fx_quality`` presets
        # (True for low/high, False for max). Framework overwrites on init.
        # ``cull_offscreen``: opt-in skip of off-view AABBs (large worlds).
        self.batch_shared_filters = True
        self.cull_offscreen = False
        # Mirrored from ScenaFramework debug-zoom cycle; skip cull when True.
        # Hot path reads the bool only — never compares the zoom float.
        self._debug_zoom_active = False
        # Test hook: number of per-layer CTM swaps this frame (slow path only).
        self._layer_ctm_swaps = 0
        # Test / HUD hooks: visible objects kept vs skipped this ``draw()``.
        self._cull_kept = 0
        self._cull_skipped = 0
        from .bounds import BoundsPlayfield, get_bounds_system
        self.bounds = BoundsPlayfield(self)
        get_bounds_system().bind_playfield(self.bounds)
        # 1.0 = full-res ImageFilter layers; <1 = half/quarter RT then upscale.
        self.shape_fx_scale = 1.0
        # Bucketed GPU RT pool for low-res shape filters (avoids recreate thrash
        # when union AABB wobbles a few pixels). See ``_ensure_shape_fx_surface``.
        self._shape_fx_pool: List = []  # [{w, h, surface, last_use}, ...]
        self._shape_fx_use_tick = 0
        self._shape_fx_allocs = 0
        self._shape_fx_reuses = 0

        # Create and set default style
        self.background_color = background_color
        PaintState._reset_defaults()

        # Set this canvas as current
        ScenaCanvas.set_current(self)

        # Create a rect to represent the canvas boundaries (y-up: top-left is (0, H))
        self.canvas_rect = Rect(
            top_left=Point(0, self.height), width=self.width, height=self.height, layer=None
        )

    def rebind(self, skia_canvas, width=None, height=None, pixel_ratio=None) -> None:
        """Re-target this canvas onto a different Skia surface, in place.

        Used to move from the in-memory placeholder surface created at
        ScenaFramework bootstrap time (before any OS window exists) to the
        real GPU-backed surface once run() opens the window, and to resize
        the placeholder itself if bootstrap() is called again with a
        different design size. Keeps this object's identity -- and its
        registry, so already-registered shapes/widgets/ids/groups --
        intact; callers never need a new ScenaCanvas instance.
        """
        self.skia_canvas = skia_canvas
        if pixel_ratio is not None:
            self.pixel_ratio = pixel_ratio if pixel_ratio else 1.0
        if width is not None or height is not None:
            old_cx, old_cy = self.width * 0.5, self.height * 0.5
            at_identity_look = (
                abs(self._look_x - old_cx) < 1e-9
                and abs(self._look_y - old_cy) < 1e-9
            )
            if width is not None:
                self.width = float(width)
            if height is not None:
                self.height = float(height)
            self.aspect_ratio = self.width / self.height if self.height else 1.0
            self.canvas_rect.width = self.width
            self.canvas_rect.height = self.height
            # Y-up: canvas top-left stays at (0, height)
            self.canvas_rect.top_left._takein((0.0, self.height))
            if at_identity_look:
                self._look_x = self.width * 0.5
                self._look_y = self.height * 0.5
                self._look_rest_x = self._look_x
                self._look_rest_y = self._look_y
            self._sync_camera()

    def advance_layer_scroll(self, t) -> None:
        """Integrate author ``scroll`` on every non-neutral layer, once per frame.

        Called by the frame body right after the clock tick (world state, not
        paint): ``layer.view`` read in ``update`` and the process tick see this
        frame's offset, and a run that never draws still scrolls. Draw only
        reads the accumulated offset (Canvas Design, Parallax layers).
        """
        if t is None or not self.registry.layers.has_parallax_layers:
            return
        t = float(t)
        # Every layer, hidden or not: scroll is world state, and ``visible``
        # is paint. A hidden layer that froze would jump (or lag for good)
        # when shown again, and an Endless on it would stop filling
        # (review 2026-10-09 S9-6).
        moved = False
        for layer in self.registry.layers._layers.values():
            if not layer._is_neutral_response:
                layer._scroll_state.advance(t)
                moved = True
        if moved:
            self._notify_view_changed()      # a formula on layer.view follows the scroll

    def _layer_partial_matrix(self, layer: Layer) -> "skia.Matrix":
        """World → design matrix for ``layer`` including author scroll accum."""
        resp = layer._response
        m = partial_camera_matrix(
            cx=self.width * 0.5,
            cy=self.height * 0.5,
            look_x=self._look_x,
            look_y=self._look_y,
            zoom=self._zoom,
            rotation_deg=self._rotation,
            rest_x=self._look_rest_x,
            rest_y=self._look_rest_y,
            pan_response=resp.pan_response,
            zoom_response=resp.zoom_response,
            rotation_response=resp.rotation_response,
        )
        sx, sy = layer._scroll_state.accum
        if abs(sx) > 1e-12 or abs(sy) > 1e-12:
            m.preTranslate(float(sx), float(sy))
        return m

    def draw(self, layer_filter=None, t=None) -> None:
        """Draw all objects, layer by layer (low z first → high z on top).

        Optional opts:
          - ``cull_offscreen``: skip shapes outside ``visible_bounds``
            (neutral layers only; parallax layers are never culled)
          - ``batch_shared_filters``: one saveLayer / low-res RT per shared
            fill/line filter ``_batch_key`` (z-order tradeoff among keys). Also
            groups consecutive interned stroke Recipes (Laser / Neon / Ink)
            pass-major. Consecutive ElectricField **high** / ElectricBolt
            **medium+high** overlay PE-glows share one Plus ``Blur`` plate. Owned by
            ``fx_quality`` presets (on for low/high, off
            for max); can be overridden per script.
          - ``shape_fx_scale`` < 1: filtered layers render into a lower-res RT
            (works with or without batching; batch groups share one RT)

        ``layer_filter``: optional ``callable(layer_name) -> bool``. When set,
        only layers for which it returns True are drawn (used by post-FX to
        exclude the reserved ``top`` layer from the scene RT).

        ``t``: accepted for callers' symmetry; author ``scroll`` is integrated
        in the frame tick (:meth:`advance_layer_scroll`), not here.
        """
        self._layer_ctm_swaps = 0
        self._cull_kept = 0
        self._cull_skipped = 0
        has_parallax = self.registry.layers.has_parallax_layers
        sk = self.skia_canvas
        vb = None                      # the culling view window, once per draw
        for layer in self.registry.layers.iter_draw_order():
            if layer_filter is not None and not layer_filter(layer.name):
                continue

            # Fast path: no parallax layers in the scene, or this layer is neutral
            # under a scene that already has the full camera applied externally.
            # Slow path: replace full camera with this layer's partial matrix.
            layer_saves = sk.getSaveCount()
            need_swap = has_parallax and not layer._is_neutral_response
            if need_swap:
                self._layer_ctm_swaps += 1
                partial = self._layer_partial_matrix(layer)
                sk.save()
                inv = skia.Matrix()
                if self._camera_active and self._camera_matrix.invert(inv):
                    # CTM is currently View · FullCamera; concat Inv(Full) · Partial.
                    sk.concat(inv)
                sk.concat(partial)

            objs = []
            if getattr(layer, "_tombstones", 0):
                layer._compact()
            # Default ``cull_offscreen=False``: skip the per-object ``_passes_cull``
            # call (its first line is ``return True``). Counters still count kept
            # visibles so draw instrumentation stays honest.
            if self.cull_offscreen and not self._layer_never_culled(layer):
                # The view window and the layer checks once per layer, not per
                # object: they cost more than the blit they could skip
                # (review 2026-10-09 S9-10).
                if vb is None:
                    vb = self.visible_bounds
                keep = _cull_keeps
                append = objs.append
                skipped = 0
                for o in layer._objects:
                    if not _drawn(o):
                        continue
                    if keep(o, vb):
                        append(o)
                    else:
                        skipped += 1
                self._cull_kept += len(objs)
                self._cull_skipped += skipped
            elif self.cull_offscreen:
                for o in layer._objects:
                    if _drawn(o):
                        objs.append(o)
                self._cull_kept += len(objs)
            else:
                for o in layer._objects:
                    if _drawn(o):
                        objs.append(o)
                self._cull_kept += len(objs)
            try:
                if self.batch_shared_filters:
                    self._draw_layer_batched(objs)
                else:
                    # Strict painter's order: still use saveLayer / shape-FX RT per
                    # shape (not paint ImageFilters). Paint-filter draws on the
                    # window backend RT are a known HiDPI FPS cliff (~4× slower).
                    for obj in objs:
                        if getattr(obj, "_plain_blit", False):
                            self._draw_plain_object(obj)
                        elif _must_solo_draw(obj):
                            self._draw_object(obj)
                        elif _has_any_batchable_filter(obj):
                            self._draw_filtered_one(obj)
                        else:
                            self._draw_object(obj)
            finally:
                sk.restoreToCount(layer_saves)

    def _layer_never_culled(self, layer) -> bool:
        """Debug zoom, a parallax layer (its own partial CTM) and the ``ui``
        view pass are never culled (see ``_passes_cull``)."""
        if self._debug_zoom_active or not layer._is_neutral_response:
            return True
        from .registry import UI_LAYER
        return layer.name == UI_LAYER

    def _passes_cull(self, obj, layer=None) -> bool:
        """One object: drawn this frame under ``cull_offscreen``? The draw
        loop runs the same two steps with the layer check and the view window
        hoisted (``_layer_never_culled`` once per layer, ``_cull_keeps`` per
        object): one body, two doors (review 2026-10-09 S9-10)."""
        if not self.cull_offscreen:
            return True
        if layer is None:
            name = getattr(obj, "_layer", None) or getattr(obj, "layer", None)
            try:
                layer = self.registry.layers.get(name) if name else None
            except Exception:
                layer = None
        if layer is not None:
            if self._layer_never_culled(layer):
                return True
        elif self._debug_zoom_active:
            return True
        return _cull_keeps(obj, self.visible_bounds)

    def _draw_filtered_one(self, obj) -> None:
        """One object on the filtered route (ImageFilter glow / shadow on a saveLayer).

        Strict painter's order uses it per object; a self-enveloping Graphic
        (``_draws_solo``: SpriteButton) calls it from its own ``draw`` so its
        ``.glow`` / ``.shadow`` render as on any sprite.
        """
        pull = getattr(obj, "_pull_property_anchors", None)
        if pull is not None:
            pull()
        self._draw_tail_ghosts((obj,))
        self._draw_fill_only(obj)
        self._draw_stroke_only(obj)
        self._draw_deferred_overlays((obj,))

    def _draw_plain_object(self, obj) -> None:
        ScenaCanvas._plain_blit_draws += 1
        blit = getattr(obj, "_blit_plain", None)
        if blit is not None:
            blit(self.skia_canvas)
        else:
            self._draw_object(obj)

    def _draw_object(self, obj) -> None:
        obj.draw(self.skia_canvas)

    def _draw_layer_batched(self, objects) -> None:
        """Two-pass filter batching; solid shapes draw without saveLayer.

        Shapes with a multipass ``visual`` or active transient draw fully via ``obj.draw``
        (envelope / multi-pass) and are not mixed into fill/line filter batches.
        Consecutive interned stroke Recipes (``_look_pass_group``) emit pass-major
        when ``batch_shared_filters`` is on — same escape as filter grouping.
        GlowRim / Halo high enter this path: interned Blur batches, then
        ``_overlay_after_filters`` draws unfiltered rims once per segment.
        Electric* high PE-glow is a second shared Plus plate on that segment.
        """
        i = 0
        n = len(objects)
        group_passes = self.batch_shared_filters
        while i < n:
            obj = objects[i]
            if getattr(obj, "_plain_blit", False):
                self._draw_plain_object(obj)
                i += 1
                continue
            if group_passes and _look_pass_groupable(obj):
                look = getattr(obj, "visual", None)
                j = i + 1
                while j < n and _look_pass_groupable(objects[j]) and getattr(objects[j], "visual", None) is look:
                    j += 1
                if j - i >= 2:
                    self._draw_look_pass_run(objects[i:j])
                else:
                    self._draw_object(obj)
                i = j
                continue
            if _must_solo_draw(obj):
                self._draw_object(objects[i])
                i += 1
                continue
            if not _has_any_batchable_filter(objects[i]):
                self._draw_object(objects[i])
                i += 1
                continue
            j = i + 1
            while j < n and not _must_solo_draw(objects[j]) and _has_any_batchable_filter(objects[j]):
                j += 1
            self._draw_filtered_segment(objects[i:j])
            i = j

    def _draw_look_pass_run(self, segment: List) -> None:
        """Pass-major emit for one interned Recipe run (z relaxed among peers)."""
        look = getattr(segment[0], "visual", None)
        emit = getattr(look, "_emit_look_passes", None)
        if not callable(emit):
            for obj in segment:
                self._draw_object(obj)
            return
        for obj in segment:
            pull = getattr(obj, "_pull_property_anchors", None)
            if pull is not None:
                pull()
        emit(segment, self.skia_canvas)

    def _draw_filtered_segment(self, segment: List) -> None:
        """Fill pass then stroke pass; group by batch_key across the whole segment.

        Unfiltered tail ghosts draw first (behind the filtered body) so Tail
        does not eject ImageFilter glow/shadow from the interned saveLayer.
        After both filter plates, run ``_overlay_after_filters`` (unfiltered rims)
        so GlowRim / Halo high share one Blur RT then one rim pass.
        ElectricField high / ElectricBolt medium+high PE-glow is a second
        shared Plus plate (σ 2.2) when ``batch_shared_filters`` is on; thin
        cores stay in the overlay.
        """
        for obj in segment:
            pull = getattr(obj, "_pull_property_anchors", None)
            if pull is not None:
                pull()
        self._draw_tail_ghosts(segment)
        self._batch_by_key(
            segment,
            key_fn=lambda o: _filter_batch_key(getattr(o, 'fill_filter', None)),
            draw_batch=self._draw_fills_in_layer,
            draw_one=self._draw_fill_only,
        )
        self._batch_by_key(
            segment,
            key_fn=lambda o: _filter_batch_key(getattr(o, 'line_filter', None)),
            draw_batch=self._draw_strokes_in_layer,
            draw_one=self._draw_stroke_only,
        )
        self._draw_deferred_overlays(segment)

    def _draw_deferred_overlays(self, shapes) -> None:
        """Unfiltered rim / character pass after halo ImageFilters.

        Consecutive interned ElectricField high / ElectricBolt medium+high
        looks fold PE-glow into one Plus ``Blur`` plate, then draw mid/core
        with ``glow_batched=True``.
        Escape: ``batch_shared_filters=False`` (per-shape ``_gpu_blur_stroke``).
        """
        skia_canvas = self.skia_canvas
        batch = self.batch_shared_filters
        i = 0
        n = len(shapes)
        while i < n:
            shp = shapes[i]
            visual = getattr(shp, "visual", None)
            if visual is None:
                i += 1
                continue
            if batch and _overlay_glow_groupable(shp):
                look = visual
                j = i + 1
                while (
                    j < n
                    and _overlay_glow_groupable(shapes[j])
                    and getattr(shapes[j], "visual", None) is look
                ):
                    j += 1
                run = shapes[i:j]
                if len(run) >= 2:
                    self._draw_overlay_glow_plate(look, run)
                    for s in run:
                        fn = getattr(getattr(s, "visual", None), "_overlay_after_filters", None)
                        if callable(fn):
                            fn(s, skia_canvas, glow_batched=True)
                    i = j
                    continue
            fn = getattr(visual, "_overlay_after_filters", None)
            if callable(fn):
                fn(shp, skia_canvas)
            i += 1

    def _draw_overlay_glow_plate(self, look, shapes) -> None:
        """One interned ``Blur(σ)`` + Plus ``saveLayer`` for N PE-glow strokes."""
        emit = getattr(look, "_emit_overlay_glow", None)
        if not callable(emit):
            return
        bounds_fn = getattr(look, "_overlay_glow_layer_bounds", None)
        bounds = bounds_fn(shapes) if callable(bounds_fn) else None
        if bounds is None:
            return
        from .filters import Blur
        sigma = float(getattr(look, "_overlay_glow_sigma", 2.2))
        halo = Blur(sigma=sigma)
        layer = skia.Paint()
        layer.setImageFilter(halo._skia_filter)
        layer.setBlendMode(skia.BlendMode.kPlus)
        self.skia_canvas.saveLayer(bounds, layer)
        try:
            for shp in shapes:
                emit(shp, self.skia_canvas)
        finally:
            self.skia_canvas.restore()

    def _draw_tail_ghosts(self, shapes) -> None:
        """Unfiltered Tail stamps behind the live body. Skip until a tail is seen."""
        draw = None
        sk = self.skia_canvas
        for shp in shapes:
            if getattr(shp, "_tail", None) is None:
                continue
            if draw is None:
                from .stamps import draw_tail_stamp
                draw = draw_tail_stamp
            draw(shp, sk)

    def _batch_by_key(self, segment, *, key_fn, draw_batch, draw_one) -> None:
        """Group all shapes sharing a key (not only consecutive) → one saveLayer each."""
        groups: dict = {}
        order: List = []
        singles: List = []
        for obj in segment:
            key = key_fn(obj)
            if key is None:
                singles.append(obj)
                continue
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(obj)

        # Preserve first-seen key order; interleave unkeyed fills/strokes in list order
        # by drawing keyed groups first in discovery order, then remaining singles.
        # (Acceptable z tradeoff under batch_shared_filters.)
        for key in order:
            run = groups[key]
            if len(run) >= 2:
                draw_batch(run)
            else:
                draw_one(run[0])
        for obj in singles:
            draw_one(obj)

    def _layer_bounds_for(self, shapes: List, shared_filter) -> skia.Rect:
        outset = float(getattr(shared_filter, '_batch_outset', 0.0) or 0.0)
        max_thick = 0.0
        for s in shapes:
            try:
                max_thick = max(max_thick, float(getattr(s, 'line_width', 0) or 0))
            except Exception:
                pass
        outset += 0.5 * max_thick
        boxes = []
        for s in shapes:
            box = _approx_draw_aabb(s) or _BATCH_AABB_FALLBACK
            boxes.append(_expand_aabb_for_shield_oval(box, s, outset))
        minx, miny, maxx, maxy = _union_aabb(boxes)
        return skia.Rect.MakeLTRB(
            minx - outset, miny - outset, maxx + outset, maxy + outset
        )

    def _save_filter_layer(self, bounds: skia.Rect, image_filter) -> bool:
        """saveLayer only when an ImageFilter exists. Never for solid fills."""
        if image_filter is None:
            return False
        paint = skia.Paint()
        paint.setImageFilter(image_filter)
        self.skia_canvas.saveLayer(bounds, paint)
        return True

    def _ensure_shape_fx_surface(self, width: int, height: int):
        """GPU RT for reduced-res shape ImageFilters (glow/blur/shadow).

        Sizes are **bucketed** (ceil to 64 px) and surfaces live in a small pool
        (max 4). Exact-size recreate when a batch AABB wobbles a few device
        pixels is a known FPS thrash; pooling keeps the visual map identical
        when only a sub-rect of the bucket is used (see composite).
        """
        from .orchestration import ScenaFramework

        fw = ScenaFramework.get_instance()
        ctx = getattr(fw, "_context", None)
        need_w = max(1, int(width))
        need_h = max(1, int(height))
        bucket = 64
        bw = max(bucket, int(math.ceil(need_w / bucket) * bucket))
        bh = max(bucket, int(math.ceil(need_h / bucket) * bucket))
        bw = min(bw, 4096)
        bh = min(bh, 4096)

        self._shape_fx_use_tick = int(getattr(self, "_shape_fx_use_tick", 0)) + 1
        tick = self._shape_fx_use_tick
        pool: List = getattr(self, "_shape_fx_pool", None)
        if pool is None:
            pool = []
            self._shape_fx_pool = pool

        # Prefer exact bucket match, then any larger entry (smallest waste).
        best = None
        best_waste = None
        for entry in pool:
            sw, sh = entry["w"], entry["h"]
            if sw == bw and sh == bh:
                entry["last_use"] = tick
                self._shape_fx_reuses = int(getattr(self, "_shape_fx_reuses", 0)) + 1
                return entry["surface"], bw, bh
            if sw >= bw and sh >= bh:
                waste = (sw * sh) - (bw * bh)
                if best is None or waste < best_waste:
                    best = entry
                    best_waste = waste
        if best is not None:
            best["last_use"] = tick
            self._shape_fx_reuses = int(getattr(self, "_shape_fx_reuses", 0)) + 1
            return best["surface"], best["w"], best["h"]

        # Allocate new bucketed RT (LRU-evict if pool is full).
        max_pool = _SHAPE_FX_POOL_MAX
        if len(pool) >= max_pool:
            pool.sort(key=lambda e: e["last_use"])
            pool.pop(0)

        if ctx is None:
            surf = skia.Surface(bw, bh)
        else:
            info = skia.ImageInfo.Make(
                bw, bh,
                skia.kRGBA_8888_ColorType,
                skia.kPremul_AlphaType,
                skia.ColorSpace.MakeSRGB(),
            )
            surf = skia.Surface.MakeRenderTarget(ctx, skia.Budgeted.kYes, info)
            if surf is None:
                surf = skia.Surface(bw, bh)
        pool.append({"w": bw, "h": bh, "surface": surf, "last_use": tick})
        self._shape_fx_allocs = int(getattr(self, "_shape_fx_allocs", 0)) + 1
        return surf, bw, bh

    def _composite_filtered_group(
        self, shapes: List, shared_filter, *, fills: bool
    ) -> None:
        """Draw a filter-sharing group via full-res saveLayer or low-res RT.

        Low-res path (``shape_fx_scale`` < 1): rasterize + filter into a smaller
        GPU RT covering the group bounds, then upscale-blit. Measured ~2× faster
        than full-res saveLayer for glow/blur/shadow batches on Retina.

        Survival GlowFilter (``_uses_filter_pipeline`` False) skips the RT and
        calls ``_draw_survival`` per shape (radial soft plate + sharp geometry).
        """
        if shared_filter is not None:
            ufp = getattr(shared_filter, "_uses_filter_pipeline", None)
            if callable(ufp) and not ufp():
                draw_surv = getattr(shared_filter, "_draw_survival", None)
                if draw_surv is not None:
                    for shp in shapes:
                        saved_ff = getattr(shp, "_fill_filter", None)
                        saved_lf = getattr(shp, "_line_filter", None)
                        shp._fill_filter = None
                        shp._line_filter = None
                        try:
                            draw_surv(shp, self.skia_canvas, fills=fills)
                        finally:
                            shp._fill_filter = saved_ff
                            shp._line_filter = saved_lf
                    return

        if shared_filter is None or getattr(shared_filter, "_skia_filter", None) is None:
            for shp in shapes:
                if fills:
                    self._draw_fill_only(shp)
                else:
                    self._draw_stroke_only(shp)
            return

        bounds = self._layer_bounds_for(shapes, shared_filter)
        scale = float(getattr(self, "shape_fx_scale", 1.0) or 1.0)
        image_filter = shared_filter._skia_filter

        if scale >= 0.999:
            if not self._save_filter_layer(bounds, image_filter):
                for shp in shapes:
                    if fills:
                        self._draw_fill_only(shp)
                    else:
                        self._draw_stroke_only(shp)
                return
            try:
                self._draw_group_content(shapes, fills=fills, strip_filters=True)
            finally:
                self.skia_canvas.restore()
            return

        # --- low-res RT path ---
        # Size the RT from *device* pixels of the bounds under the current CTM.
        matrix = self.skia_canvas.getTotalMatrix()
        dev = matrix.mapRect(bounds)
        hw = max(1, int(math.ceil(abs(dev.width()) * scale)))
        hh = max(1, int(math.ceil(abs(dev.height()) * scale)))
        # Cap absurd sizes (full-canvas batches).
        hw = min(hw, 4096)
        hh = min(hh, 4096)

        # ``to_rt`` already scales design units into the RT. A second
        # ``_filter_at_scale`` would shrink sigma twice.

        surf, pool_w, pool_h = self._ensure_shape_fx_surface(hw, hh)
        # Map into a *content* sub-rect (exact hw×hh). The pool surface may be
        # larger (bucketed); blit only that sub-rect so soft edges match the
        # pre-pool path pixel-for-pixel at this resolution.
        content = skia.Rect.MakeWH(float(hw), float(hh))
        fc = surf.getCanvas()
        fc.clear(skia.ColorTRANSPARENT)
        to_rt = skia.Matrix.MakeRectToRect(
            bounds,
            content,
            skia.Matrix.kFill_ScaleToFit,
        )
        fc.setMatrix(to_rt)
        lp = skia.Paint()
        lp.setImageFilter(image_filter)
        fc.saveLayer(bounds, lp)
        try:
            saved = self.skia_canvas
            self.skia_canvas = fc
            try:
                self._draw_group_content(shapes, fills=fills, strip_filters=True)
            finally:
                self.skia_canvas = saved
        finally:
            fc.restore()

        img = surf.makeImageSnapshot()
        sampling = skia.SamplingOptions(skia.FilterMode.kLinear)
        # Prefer src→dst blit of the content sub-rect (bucket-safe).
        try:
            self.skia_canvas.drawImageRect(img, content, bounds, sampling)
        except TypeError:
            # Older binding variant: single dst rect scales full image.
            if pool_w == hw and pool_h == hh:
                self.skia_canvas.drawImageRect(img, bounds, sampling)
            else:
                # Subset then draw if available.
                try:
                    sub = img.makeSubset(skia.IRect.MakeWH(hw, hh))
                    if sub is not None:
                        self.skia_canvas.drawImageRect(sub, bounds, sampling)
                    else:
                        self.skia_canvas.drawImageRect(img, bounds, sampling)
                except Exception:
                    self.skia_canvas.drawImageRect(img, bounds, sampling)

    def _draw_group_content(self, shapes: List, *, fills: bool, strip_filters: bool) -> None:
        """Rasterize fill or stroke into the current filter layer.

        Uses ``_geometry_draw`` (not ``shp.draw``) so GlowRim overlays are not
        baked into the Blur RT — those run later via ``_draw_deferred_overlays``.
        """
        skia_canvas = self.skia_canvas
        for shp in shapes:
            if fills:
                if not getattr(shp, "_fill", None):
                    continue
            else:
                if not getattr(shp, "_line", None):
                    continue
            saved_ff = saved_lf = None
            if strip_filters:
                saved_ff = getattr(shp, "_fill_filter", None)
                saved_lf = getattr(shp, "_line_filter", None)
                shp._fill_filter = None
                shp._line_filter = None
            try:
                if fills:
                    shp._geometry_draw(skia_canvas, stroke_paint=None)
                else:
                    shp._geometry_draw(skia_canvas, fill_paint=None)
            finally:
                if strip_filters:
                    shp._fill_filter = saved_ff
                    shp._line_filter = saved_lf

    def _draw_fill_only(self, shp) -> None:
        """Draw fill only via saveLayer / shape-FX RT when a fill filter is set.

        Always avoid attaching ImageFilters to the paint and drawing that into
        the window backend RT — that path is pathologically slow on HiDPI.
        """
        if not getattr(shp, '_fill', None):
            return
        fx = getattr(shp, "fill_filter", None)
        if fx is not None and getattr(fx, "_skia_filter", None) is not None:
            self._composite_filtered_group([shp], fx, fills=True)
            return
        shp._geometry_draw(self.skia_canvas, stroke_paint=None)

    def _draw_stroke_only(self, shp) -> None:
        """Draw stroke only; filtered strokes use saveLayer / shape-FX RT."""
        if not getattr(shp, '_line', None):
            return
        fx = getattr(shp, "line_filter", None)
        if fx is not None and getattr(fx, "_skia_filter", None) is not None:
            self._composite_filtered_group([shp], fx, fills=False)
            return
        shp._geometry_draw(self.skia_canvas, fill_paint=None)

    def _draw_fills_in_layer(self, shapes: List) -> None:
        """Batch-draw fills into one saveLayer / low-res RT (shared fill_filter)."""
        self._composite_filtered_group(shapes, shapes[0].fill_filter, fills=True)

    def _draw_strokes_in_layer(self, shapes: List) -> None:
        """Batch-draw strokes into one saveLayer / low-res RT (shared line_filter)."""
        self._composite_filtered_group(shapes, shapes[0].line_filter, fills=False)

    # --- camera matrix ---------------------------------------------------------

    def _sync_camera(self) -> None:
        """Update ``_camera_active`` and rebuild ``_camera_matrix`` if needed.

        Called only when camera state (or design size) changes — not per frame.
        """
        cx = self.width * 0.5
        cy = self.height * 0.5
        self._camera_active = not (
            abs(self._zoom - 1.0) < _CAMERA_EPS
            and abs(self._rotation) < _CAMERA_EPS
            and abs(self._look_x - cx) < _CAMERA_EPS
            and abs(self._look_y - cy) < _CAMERA_EPS
        )
        if self._camera_active:
            m = skia.Matrix()
            m.setTranslate(cx, cy)
            m.preRotate(self._rotation)
            m.preScale(max(self._zoom, _MIN_ZOOM), max(self._zoom, _MIN_ZOOM))
            m.preTranslate(-self._look_x, -self._look_y)
            self._camera_matrix = m
        else:
            self._camera_matrix = skia.Matrix()  # identity
        self._notify_view_changed()

    def _world_to_view_xy(self, x: float, y: float) -> Tuple[float, float]:
        """The camera map in float64: ``c + R(rotation) · zoom · (w - look)``.
        ``_camera_matrix`` is a float32 Skia matrix: at x ~ 1e6 it put the
        pointer 0.05 units off, and 1.5 design units at 1e7 for an overlay
        (review 2026-10-09 S9-11). The draw CTM stays float32."""
        z = max(self._zoom, _MIN_ZOOM)
        dx, dy = (x - self._look_x) * z, (y - self._look_y) * z
        r = math.radians(self._rotation)
        c, s = math.cos(r), math.sin(r)
        return (self.width * 0.5 + dx * c - dy * s,
                self.height * 0.5 + dx * s + dy * c)

    def _view_to_world_xy(self, x: float, y: float) -> Tuple[float, float]:
        """The inverse camera map in float64 (see ``_world_to_view_xy``)."""
        z = max(self._zoom, _MIN_ZOOM)
        dx, dy = x - self.width * 0.5, y - self.height * 0.5
        r = math.radians(self._rotation)
        c, s = math.cos(r), math.sin(r)
        return (self._look_x + (dx * c + dy * s) / z,
                self._look_y + (-dx * s + dy * c) / z)

    def _notify_view_changed(self) -> None:
        """The camera, a layer's scroll or the design size moved: formulas
        that read the author ``canvas`` (zoom, pan, ``game_view``, a layer's
        ``view``) re-evaluate. Engine readers keep reading the raw fields."""
        facade = getattr(self, "_author_facade", None)
        # Nothing can depend on a Container that has no graph node yet (a
        # formula that reads ``canvas`` registers it), so an unlinked canvas
        # pays two attribute reads here, not Container.update's ephemeral
        # branch (+1.7 us per camera move, A/B 2026-10-09).
        if facade is not None and (facade._node_id is not None or facade._link is not None):
            facade.update()

    def camera_matrix(self) -> skia.Matrix:
        """Cached world → design-space transform (identity when camera inactive)."""
        return self._camera_matrix

    def apply_camera(self, skia_canvas) -> None:
        """Concat the camera matrix onto an already view-scaled Skia canvas.

        No-op when the camera is identity (``_camera_active`` is False).
        """
        if self._camera_active:
            skia_canvas.concat(self._camera_matrix)

    # --- camera properties -----------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def pan_x(self) -> float:
        return self._look_x

    @property
    def pan_y(self) -> float:
        return self._look_y

    @property
    def pan_rest_x(self) -> float:
        """Look-at X that counts as zero offset for background parallax."""
        return self._look_rest_x

    @property
    def pan_rest_y(self) -> float:
        """Look-at Y that counts as zero offset for background parallax."""
        return self._look_rest_y

    @property
    def rotation(self) -> float:
        return self._rotation

    @property
    def visible_bounds(self) -> VisibleBounds:
        if not self._camera_active:
            # Y-up: visual top is at y=height, bottom at y=0
            return VisibleBounds(0.0, self.height, self.width, self.height)
        return self._inverse_view_aabb(self._camera_matrix)

    def _inverse_view_aabb(self, matrix: "skia.Matrix") -> VisibleBounds:
        """AABB of the four design-view corners mapped through ``matrix``⁻¹.

        ``matrix`` maps some space (world, or a parallax layer's own
        coordinates) to design units; the result is the view window in that
        space. Rotation → AABB of the four corners (over-inclusive). A
        singular matrix falls back to the design rect.
        """
        inv = skia.Matrix()
        if not matrix.invert(inv):
            return VisibleBounds(0.0, self.height, self.width, self.height)
        corners = [
            inv.mapXY(0.0, 0.0),
            inv.mapXY(self.width, 0.0),
            inv.mapXY(self.width, self.height),
            inv.mapXY(0.0, self.height),
        ]
        xs = [p.x() for p in corners]
        ys = [p.y() for p in corners]
        left, right = min(xs), max(xs)
        bottom, top = min(ys), max(ys)
        return VisibleBounds(left, top, right - left, top - bottom)

    def layer_view(self, layer: Layer):
        """``layer.view``: the view window in ``layer``'s own coordinates, as a fresh ``Box``.

        ``ui`` → the view rect (camera-immune); a neutral layer → the world
        window (``canvas.game_view``); a parallax / scroll layer → the inverse
        of its partial matrix (camera response + scroll accum) applied to the
        view corners. Snapshot, off the reactive graph (Canvas Design,
        Parallax layers, "Layer view").
        """
        from .box import Box
        if layer.name == UI_LAYER:
            return Box._from_aabb(0.0, 0.0, float(self.width), float(self.height))
        if layer._is_neutral_response:
            vb = self.visible_bounds
        else:
            vb = self._inverse_view_aabb(self._layer_partial_matrix(layer))
        return Box._from_aabb(vb.left, vb.bottom, vb.right, vb.top)

    # --- camera transforms -----------------------------------------------------

    def zoom_to(self, factor: float, *, about=None) -> 'ScenaCanvas':
        factor = fixed_magnitude(factor, "zoom", hint=HINT_SCALE)
        # ``magnitude`` only rejects negative; 0 is a legal write (a timed
        # zoom-out easing through 0 is a documented effect — Canvas Design
        # "tight zoom"). Clamp the *stored* zoom here so every reader
        # (canvas.zoom, the about-pivot math below, parallax response) sees
        # the same clamped value instead of a raw 0 that only the draw
        # matrix used to clamp.
        draw_z = max(factor, _MIN_ZOOM)
        if about is not None:
            ax, ay = _as_xy(about)
            _finite_xy(ax, ay, "zoom about")
            z_old = max(self._zoom, _MIN_ZOOM)
            self._look_x = ax - (z_old / draw_z) * (ax - self._look_x)
            self._look_y = ay - (z_old / draw_z) * (ay - self._look_y)
        self._zoom = draw_z
        self._sync_camera()
        return self

    def zoom_by(self, factor: float, *, about=None) -> 'ScenaCanvas':
        fac = fixed_magnitude(factor, "zoom", hint=HINT_SCALE)
        return self.zoom_to(self._zoom * fac, about=about)

    def pan_to(self, x: float, y: float) -> 'ScenaCanvas':
        x, y = _finite_number(x, "pan"), _finite_number(y, "pan")
        self._look_x = x
        self._look_y = y
        self._sync_camera()
        return self

    def pan_by(self, dx: float, dy: float) -> 'ScenaCanvas':
        # Content moves by (dx, dy) in world units → look-at moves opposite.
        dx, dy = _finite_number(dx, "pan"), _finite_number(dy, "pan")
        self._look_x -= dx
        self._look_y -= dy
        self._sync_camera()
        return self

    def set_origin(self, where: str = 'corner') -> 'ScenaCanvas':
        """Pan so world ``(0, 0)`` is at the view corner or center (see Canvas)."""
        self._look_x, self._look_y = _origin_look(self, where)
        self._anchor_rest()
        self._sync_camera()
        return self

    def _anchor_rest(self) -> None:
        """Re-anchor background parallax rest to the current look."""
        self._look_rest_x = self._look_x
        self._look_rest_y = self._look_y

    def rotate_to(self, angle: float, *, about=None) -> 'ScenaCanvas':
        angle = _finite_number(angle, "rotation")
        if about is not None:
            ax, ay = _as_xy(about)
            _finite_xy(ax, ay, "rotation about")
            screen = self._camera_matrix.mapXY(ax, ay)
            sx, sy = screen.x(), screen.y()
            self._rotation = angle
            # Solve look so about still maps to the same design-space point.
            # screen = T(c) R S T(-L) about  ⇒  R^{-1}(screen - c)/z = about - L
            cx, cy = self.width * 0.5, self.height * 0.5
            r = skia.Matrix()
            r.setRotate(self._rotation)
            rinv = skia.Matrix()
            if not r.invert(rinv):
                self._sync_camera()
                return self
            local = rinv.mapXY(sx - cx, sy - cy)
            z = self._zoom if self._zoom else _MIN_ZOOM
            self._look_x = ax - local.x() / z
            self._look_y = ay - local.y() / z
        else:
            self._rotation = angle
        self._sync_camera()
        return self

    def rotate_by(self, angle: float, *, about=None) -> 'ScenaCanvas':
        return self.rotate_to(self._rotation + _finite_number(angle, "rotate_by angle"), about=about)

    def frame_to(self, target, *, pad: float = 0.0, rotate: bool = False) -> 'ScenaCanvas':
        cx, cy, tw, th, ang = self._parse_frame_target(target)
        pad = float(pad)
        tw = max(float(tw) * (1.0 + 2.0 * pad), _MIN_ZOOM)
        th = max(float(th) * (1.0 + 2.0 * pad), _MIN_ZOOM)

        if rotate:
            self._rotation = -float(ang)
        else:
            self._rotation = 0.0

        zoom_x = self.width / tw if tw else 1.0
        zoom_y = self.height / th if th else 1.0
        self._zoom = max(min(zoom_x, zoom_y), _MIN_ZOOM)
        self._look_x = float(cx)
        self._look_y = float(cy)
        self._sync_camera()
        return self

    def reset_view(self) -> 'ScenaCanvas':
        self._zoom = 1.0
        self._look_x = self.width * 0.5
        self._look_y = self.height * 0.5
        self._anchor_rest()
        self._rotation = 0.0
        self._sync_camera()
        return self

    @staticmethod
    def _parse_frame_target(target) -> Tuple[float, float, float, float, float]:
        """Return (center_x, center_y, width, height, angle_degrees)."""
        if isinstance(target, (tuple, list)):
            if len(target) != 4:
                raise TypeError("frame_to tuple must be (left, top, width, height)")
            a, b, c, d = (_bare(v) for v in target)
            _require_frame_size(c, d)
            # Y-up: top is visual top (larger y); center is below it.
            return a + c * 0.5, b - d * 0.5, c, d, 0.0

        def _target_angle(obj) -> float:
            # Graphics and Box both name the heading ``angle``. Graphics read it
            # from Defining inputs (``_rotation_value``: no Derivate wakes).
            rv = getattr(obj, '_rotation_value', None)
            if callable(rv):
                return float(rv())
            if hasattr(obj, 'angle'):
                return _bare(obj.angle)
            return 0.0

        if hasattr(target, 'center') and hasattr(target, 'width') and hasattr(target, 'height'):
            cx, cy = _as_xy(target.center)
            w = _bare(target.width)
            h = _bare(target.height)
            _require_frame_size(w, h)
            return cx, cy, w, h, _target_angle(target)

        # Shapes with no width/height slot (Rect/Square/Ellipse via
        # Defining parts, cold-safe): Circle and Line have neither
        # ``.width``/``.height`` nor a cold ``.angle``, so
        # they used to raise TypeError here.
        oriented = getattr(target, '_oriented_frame', None)
        if callable(oriented):
            try:
                cx, cy, w, h, ang = oriented()
                _require_frame_size(w, h)
                return cx, cy, w, h, ang
            except (TypeError, ValueError, AttributeError):
                pass

        # Last resort: the same axis-aligned world bounds cull/draw use.
        # No rotation info in an AABB, so ``rotate=True`` is a no-op here —
        # still better than refusing to frame a Circle / Line / Polygon.
        box = _approx_draw_aabb(target)
        if box is not None:
            x0, y0, x1, y1 = box
            w, h = x1 - x0, y1 - y0
            _require_frame_size(w, h)
            return (x0 + x1) * 0.5, (y0 + y1) * 0.5, w, h, 0.0

        raise TypeError(
            "frame_to expects a Rect-like object, a shape (Circle / Line / "
            "Polygon / ...), or a (left, top, width, height) tuple"
        )

