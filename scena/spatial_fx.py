"""
Registered ambient SpatialFx emitters (Rain, Fire, Jet, Sparks, GlowSpot, Orb, Warp,
Portal).

Sibling to Shape for canvas registration (roster / layer / z list order), but not
a PaintState/look costume and not canvas post-FX. Soft placement domains only —
never hard path silhouettes.

Tick lifecycle runs pre-draw via :func:`tick_all_spatial_fx` (after shape
transients). Particle state is internal (not DependencyGraph nodes).
"""
from __future__ import annotations

import math
import time
import weakref
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import skia

from ._pkg import is_framework_module
from .color import resolve_rgb
from .fx_quality import particle_scale, fidelity_is_lite
from .state import Container, ContainerSlot, ScalarSlot, _init_scalar, _init_composite
from .entity import (
    Entity, _USE_LAYER_DEFAULT, _refuse_if_destroyed, _parked, _stash_flag,
)
from .shapes import Point, get_xy
from .validate import expect_bool

_active_fx: "weakref.WeakSet[SpatialFx]" = weakref.WeakSet()
_now_fn = None  # optional test clock


def set_now_fn(fn) -> None:
    """Test hook: override the spatial clock (``None`` restores world time)."""
    global _now_fn
    _now_fn = fn


def _now() -> float:
    """World time (``clock.time``): SpatialFx are world actors.

    Pause and slow motion reach them like every other world process (their
    own ``after`` / ``every`` already count world seconds). Shader phases read
    the same clock, so a paused world freezes the rain, too.
    """
    if _now_fn is not None:
        return float(_now_fn())
    try:
        from .orchestration import ScenaFramework
        clk = ScenaFramework.get_instance().clock
        if clk is not None:
            return float(clk.time)
    except Exception:
        pass
    return time.perf_counter()


def _shader_time() -> float:
    # World time starts at 0 with the run, so float32 shader clocks keep
    # their precision without an origin subtraction (phases wrap anyway:
    # ``_wrapped_phase``).
    return _now()


_TAU = 2.0 * math.pi


def _wrapped_phase(rate: float, t: Optional[float] = None) -> float:
    """``time * rate`` wrapped to [0, 2π) in float64 — the only way new shaders see time.

    ``_shader_time()`` grows without bound; a phase multiplied by a turbulence
    frequency passes 2^17 within minutes and GPU ``sin`` / ``cos`` lose all
    precision there (Intel collapses). Each octave gets its own wrapped phase,
    so the wrap is seamless (Effect System Design §9, "time as wrapped phases").
    """
    if t is None:
        t = _shader_time()
    return math.fmod(float(t) * float(rate), _TAU) % _TAU


_PLATE_BUCKET = 32
_PLATE_MAX = 1024


def _plate_size(need_w: float, need_h: float) -> Tuple[int, int]:
    """Bucketed (ceil to 32 px) and capped plate size — a wobbling need keeps its RT."""
    b = _PLATE_BUCKET
    w = max(b, int(math.ceil(max(1.0, float(need_w)) / b) * b))
    h = max(b, int(math.ceil(max(1.0, float(need_h)) / b) * b))
    return min(w, _PLATE_MAX), min(h, _PLATE_MAX)


def _plate_surface(fx, w: int, h: int) -> skia.Surface:
    """Per-instance offscreen plate (GPU RT; raster when no GL context).

    Per instance, not pooled: two plates drawn in one frame from one shared
    surface would force a copy-on-write of the first snapshot.
    """
    key = (int(w), int(h))
    cache = getattr(fx, "_plate_cache", None)
    if cache is not None and cache[0] == key:
        return cache[1]
    from .background_kinds import _make_rt
    from .orchestration import ScenaFramework
    surf = _make_rt(ScenaFramework._instance, key[0], key[1])
    fx._plate_cache = (key, surf)
    return surf


from .input import MAX_FRAME_DT  # noqa: E402

# The largest single step an emitter's integrators take.
_MAX_FX_STEP = 0.1


def register_spatial(fx: "SpatialFx") -> None:
    try:
        _active_fx.add(fx)
    except TypeError:
        return
    if getattr(fx, "_tick_t", None) is None:
        # The first tick advances by the real time since birth, not 1/60.
        try:
            fx._tick_t = _now()
        except Exception:
            pass


def unregister_spatial(fx: "SpatialFx") -> None:
    try:
        _active_fx.discard(fx)
    except Exception:
        pass


def tick_all_spatial_fx(now: Optional[float] = None) -> None:
    """Advance all registered SpatialFx. Call pre-draw (after shape transients).

    An emitter's ``tick`` exception propagates.
    """
    t = _now() if now is None else float(now)
    for fx in list(_active_fx):
        if not getattr(fx, "is_alive", True):
            unregister_spatial(fx)
            continue
        t0 = getattr(fx, "_tick_t", None)
        if t0 is None:
            dt = 1.0 / 60.0
        else:
            # The world clock's one cap (MAX_FRAME_DT), not a stricter 0.1 s
            # of its own: a 0.25 s frame advanced the effects by only 0.1 s
            # (review 2026-10-09 W-T9). The integrators keep steps of at most
            # _MAX_FX_STEP, so a long frame is cut into a few.
            dt = max(0.0, min(MAX_FRAME_DT, t - float(t0)))
        fx._tick_t = t
        if fx.visible:
            if dt <= _MAX_FX_STEP:
                fx._tick(dt, t)
            else:
                n = int(math.ceil(dt / _MAX_FX_STEP))
                step = dt / n
                t_start = t - dt
                for i in range(1, n + 1):
                    fx._tick(step, t_start + step * i)


def registered_count() -> int:
    return len(_active_fx)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def _bare_num(v, default: float = 0.0) -> float:
    """Coerce a scalar field (or legacy Attribute) to float."""
    try:
        return float(v)
    except Exception:
        return float(default)


def _frac_hash(a: float, b: float = 0.0) -> float:
    x = math.sin(a * 12.9898 + b * 78.233) * 43758.5453
    return x - math.floor(x)


def _soft_band(dist_to_edge: float, half: float, soft_edge: float) -> float:
    """1 deep inside, 0 at edge. ``soft_edge`` is fraction of half-extent."""
    half = max(abs(half), 1e-6)
    band = max(float(soft_edge), 1e-4) * half
    return _clamp01(dist_to_edge / band)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------



def _hide_positional_catchall(init) -> None:
    """``help(cls)`` shows the keyword-only signature; ``*args`` only exists to reject.

    Runs before :func:`~scena.validate.guard_init_numbers`, whose ``bind_partial``
    then gives up on stray positionals and leaves the message to
    :func:`_reject_positional_fx`.
    """
    import inspect
    try:
        sig = inspect.signature(init)
    except (TypeError, ValueError):
        return
    params = [p for p in sig.parameters.values() if p.kind is not p.VAR_POSITIONAL]
    if len(params) != len(sig.parameters):
        init.__signature__ = sig.replace(parameters=params)


def _public_fx_name(cls: type) -> str:
    """``Fire`` for ``_LookPlume``: the class an author typed."""
    return next(k.__name__ for k in cls.__mro__ if not k.__name__.startswith("_"))


# Placement spellings other frameworks use; SpatialFx places by points.
_SCALAR_PLACEMENT_KEYS = ("x", "y", "x1", "y1", "x2", "y2", "pos", "position", "at")

_FX_PLACEMENT = {
    "Rain": (
        "Rain(p1=(0, 0), p2=(400, 300))",
        "Rain is placed by two corners: p1=(x1, y1), p2=(x2, y2); "
        "or center=, width=, height=",
    ),
    "Jet": (
        "Jet(p1=(200, 100), p2=(200, 40), width=14)",
        "Jet is placed by points: p1=, p2= (or origin=, angle=, length=)",
    ),
}


def _fx_placement(name: str) -> Tuple[str, str]:
    """``(example call, hint)`` for a public SpatialFx kind."""
    return _FX_PLACEMENT.get(name) or (
        f"{name}(center=(200, 150), radius=40)",
        f"{name} is placed by a point: center=(x, y)",
    )


def fx_placement_hints(name: str) -> dict:
    """Orientation for scalar / ``at=`` placement keywords (one hint for all)."""
    hint = _fx_placement(name)[1]
    hints = {key: hint for key in _SCALAR_PLACEMENT_KEYS}
    if name == "Rain":
        hints["angle"] = (
            "Rain has no angle: the pad is axis-aligned and drops fall "
            "straight down"
        )
    return hints


def _reject_positional_fx(fx: "SpatialFx", args: tuple) -> None:
    """SpatialFx constructors are keyword-only, like Shape (see :class:`SpatialFx`)."""
    if not args:
        return
    name = _public_fx_name(type(fx))
    example = _fx_placement(name)[0]
    shown = ", ".join(repr(a) for a in args[:3]) + (", …" if len(args) > 3 else "")
    raise TypeError(
        f"{name}() takes keyword arguments only, got positional {shown}. "
        f"Name each value, e.g. {example}."
    )


class SpatialFx(Entity):
    """Drawable ambient emitter registered in the registry like a Shape.

    Sibling of :class:`~scena.shapes.Shape` under :class:`~scena.shapes.Entity`
    (roster / layer / groups / collidable). No PaintState / look / filter surface.
    Subclasses own placement domain + draw/tick.

    Constructors are keyword-only, like Shape: point kinds are siblings of
    Circle (``center=`` + size), ``Rain`` / ``Jet`` take ``p1=`` / ``p2=``.
    ``*args`` exists only to reject positional numbers with an example.

    ``_pose_xy_guard`` refuses ``.x`` / ``.y``: placement is ``.center``.

    Args:
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    _pose_xy_guard = True

    def __init_subclass__(cls, **kwargs):
        if is_framework_module(cls.__module__) and "__init__" in cls.__dict__:
            _hide_positional_catchall(cls.__dict__["__init__"])
            from .validate import guard_init_numbers
            guard_init_numbers(cls)
        super().__init_subclass__(**kwargs)

    def __init__(
        self,
        *,
        layer: Any = _USE_LAYER_DEFAULT,
        group: Optional[Union[str, Sequence[str]]] = None,
        soft_edge: float = 0.15,
    ):
        self._construct(layer=layer, group=group, soft_edge=soft_edge)

    def _design_center(self) -> Tuple[float, float]:
        """Default placement: the center of the design (``canvas.width / height``).

        Read from the canvas at construction, so ``init(width=…, height=…)``
        moves it. (It once read a ``design_width`` the canvas does not have;
        a bare ``except`` turned that into a fixed (200, 150) for every size.)
        """
        sc = self._scenacanvas
        return (float(sc.width) * 0.5, float(sc.height) * 0.5)

    def _construct(
        self,
        *,
        layer: Any = _USE_LAYER_DEFAULT,
        group: Optional[Union[str, Sequence[str]]] = None,
        soft_edge: float = 0.15,
        attr_name: Optional[str] = None,
        owner: Optional[Container] = None,
    ):
        from .registry import layer_is_ui
        from .canvas import ScenaCanvas
        check = (
            ScenaCanvas.get_current().registry.layers.default
            if layer is _USE_LAYER_DEFAULT
            else layer
        )
        if layer_is_ui(check):
            from .registry import UiLayerError
            raise UiLayerError(
                f"{type(self).__name__} cannot live on the reserved 'ui' layer "
                f"(ui is view-space for Graphics; SpatialFx stays on world layers). "
                f"Leave layer= out, or use a world layer."
            )
        Entity._construct(
            self,
            layer=layer,
            group=group,
            attr_name=attr_name,
            owner=owner,
        )
        from .validate import fixed_magnitude
        object.__setattr__(
            self, "soft_edge",
            float(fixed_magnitude(soft_edge, f"{type(self).__name__} soft_edge")),
        )
        self._tick_t = None
        if not getattr(self, "_ephemeral", False):
            register_spatial(self)

    def __str__(self) -> str:
        from .entity import made_at
        where = made_at(self)
        name = self.__class__.__name__
        return f"{name} ({where})" if where else name

    def __repr__(self) -> str:
        return self.__str__()

    @property
    def visible(self) -> bool:
        """Draw it or not (``True`` / ``False``). Park with ``.active = False`` to also stop its animation."""
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        _refuse_if_destroyed(self, "visible")
        value = expect_bool(value, f"{type(self).__name__}.visible")
        if _parked(self):
            _stash_flag(self, "visible", value)  # parked stays hidden; resume applies
            return
        self._visible = value

    # --- subclass hooks -------------------------------------------------------

    def _tick(self, dt: float, t: float) -> None:
        """Advance particle / animation state (pre-draw)."""

    def draw(self, skia_canvas: skia.Canvas) -> None:
        """Paint into the current scene canvas (design-space CTM already applied)."""

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        """Loose design-space AABB for cull. Override in domain types."""
        return (-40.0, -40.0, 40.0, 40.0)

    def _collision_specs(self) -> List[Tuple]:
        """Tight collision approximations (separate from :meth:`domain_aabb` cull).

        Each entry is one of:
        - ``("circle", cx, cy, r)``
        - ``("aabb", minx, miny, maxx, maxy)``
        - ``("obb", cx, cy, half_len, half_lat, ang_rad)`` — half_len along
          angle; half_lat perpendicular (Jet / OBB convention).
        """
        minx, miny, maxx, maxy = self._domain_aabb()
        return [("aabb", minx, miny, maxx, maxy)]


# ---------------------------------------------------------------------------
# Point domain (blob)
# ---------------------------------------------------------------------------


class PointDomainFx(SpatialFx):
    """Domain: center + radius (soft radial falloff).

    Subclasses may add extra Defining slots (e.g. ``angle``, ``width``,
    ``length``) via ``extra_defining=`` on :meth:`_init_point_domain`.
    Directed Fire styles pass ``skip_radius=True`` and define ``width`` +
    ``length`` instead of the disc ``radius``.
    """

    _has_domain_frame = True

    center = ContainerSlot(Point)
    radius = ScalarSlot(magnitude=True)

    _PART_NAMES = ("center", "radius")

    def _init_point_domain(
        self,
        center=None,
        radius: float = 40.0,
        *,
        extra_defining: Tuple[str, ...] = (),
        skip_radius: bool = False,
        **scene_kw,
    ):
        scene_kw.pop("style", None)
        allowed = frozenset({"layer", "group", "soft_edge", "attr_name", "owner"})
        leftover = {k: scene_kw[k] for k in scene_kw if k not in allowed}
        if leftover:
            from .validate import reject_unexpected_kwargs
            import inspect
            public = {
                p.name for p in inspect.signature(type(self).__init__).parameters.values()
                if p.name != "self" and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
            }
            owner = next(
                k for k in type(self).__mro__ if not k.__name__.startswith("_")
            )
            new = owner.__dict__.get("__new__")
            if new is not None:
                public |= {
                    n for n in inspect.signature(new).parameters
                    if n not in ("cls", "args", "kwargs")
                }
            reject_unexpected_kwargs(
                owner.__name__,
                leftover,
                valid=allowed | public | {"center", "radius", "soft_edge"} | set(extra_defining),
                hints=fx_placement_hints(owner.__name__),
            )
        SpatialFx._construct(self, **{k: scene_kw[k] for k in scene_kw if k in allowed})
        size_parts = () if skip_radius else ("radius",)
        names = ("center",) + size_parts + tuple(extra_defining)
        catalog = self._PART_NAMES + tuple(extra_defining)
        self._mark_defining_parts(*names, catalog=catalog)
        with self._batch_update():
            if center is None:
                self.center._takein(self._design_center())
            else:
                _init_composite(self.center, center)
            if not skip_radius:
                _init_scalar(self, "radius", radius)

    def _point_frame(self) -> Tuple[float, ...]:
        """``(cx, cy, *extent)`` for the collision pose key.

        Disc emitters key ``radius``. Directed Fire overrides with
        ``width``, ``length``, ``angle`` so stretch/rotate rebuilds the hull.
        """
        cx, cy = get_xy(self.center, bare=True)
        return (cx, cy, abs(float(self.radius)))

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(self.radius)
        return (cx - r, cy - r, cx + r, cy + r)

    def _collision_specs(self) -> List[Tuple]:
        # Main defining disc (not bloom / glow pads used by cull AABBs).
        cx, cy = get_xy(self.center, bare=True)
        r = max(1e-6, abs(self.radius))
        return [("circle", cx, cy, r)]

    def _radial_weight(self, x: float, y: float) -> float:
        cx, cy = get_xy(self.center, bare=True)
        r = max(abs(self.radius), 1e-6)
        d = math.hypot(x - cx, y - cy)
        return _soft_band(r - d, r, self.soft_edge)

    def _update_impl(self) -> None:
        """No default structural mirrors; subclasses may override."""
        pass


# ---------------------------------------------------------------------------
# Pad domain (rect-like dual)
# ---------------------------------------------------------------------------


class PadModel(Enum):
    CORNER_CORNER = "corner_corner"
    CENTER_WH = "center_wh"


class PadDomainFx(SpatialFx):
    """Soft axis-aligned pad. Dual models: p1–p2 corners, or center/width/height.

    No ``angle``: Rain (the only pad) falls straight down, so a turned pad
    only turned the clip — see Effect System Design §3.1d fence.
    """

    _has_domain_frame = True

    p1 = ContainerSlot(Point)
    p2 = ContainerSlot(Point)
    center = ContainerSlot(Point)
    width = ScalarSlot(magnitude=True)
    height = ScalarSlot(magnitude=True)

    _PART_NAMES = ("p1", "p2", "center", "width", "height")

    def _set_defining_parts(self, *defining: str) -> None:
        self._mark_defining_parts(*defining, catalog=self._PART_NAMES)

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill a Derivate part on first access (``rain.width`` on a corner pad)."""
        with self._no_update():
            self._update_impl()

    def _update_impl(self) -> None:
        cx, cy, w, h = self._pad_frame()
        if self.model == PadModel.CENTER_WH:
            hw, hh = w * 0.5, h * 0.5
            self._takein_live_derivate("p1", (cx - hw, cy - hh))
            self._takein_live_derivate("p2", (cx + hw, cy + hh))
        else:
            self._takein_live_derivate("center", (cx, cy))
            self._takein_live_derivate("width", w)
            self._takein_live_derivate("height", h)

    def _pad_frame(self) -> Tuple[float, float, float, float]:
        """Return ``(cx, cy, width, height)`` for the soft pad."""
        if self.model == PadModel.CENTER_WH:
            cx, cy = get_xy(self.center, bare=True)
            return cx, cy, abs(self.width), abs(self.height)
        x1, y1 = get_xy(self.p1, bare=True)
        x2, y2 = get_xy(self.p2, bare=True)
        return 0.5 * (x1 + x2), 0.5 * (y1 + y2), abs(x2 - x1), abs(y2 - y1)

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy, w, h = self._pad_frame()
        hw, hh = w * 0.5, h * 0.5
        return (cx - hw, cy - hh, cx + hw, cy + hh)

    def _pad_local_uv(self, x: float, y: float) -> Tuple[float, float]:
        """Local coords: (0,0)=center, half-width=0.5 → u∈[-0.5,0.5]."""
        cx, cy, w, h = self._pad_frame()
        hw = max(w * 0.5, 1e-6)
        hh = max(h * 0.5, 1e-6)
        return ((x - cx) / (2.0 * hw), (y - cy) / (2.0 * hh))  # -0.5..0.5 inside

    def _pad_weight(self, x: float, y: float) -> float:
        u, v = self._pad_local_uv(x, y)
        # Convert to distance-to-edge in half-extents [0, 0.5]
        du = 0.5 - abs(u)
        dv = 0.5 - abs(v)
        if du < 0.0 or dv < 0.0:
            return 0.0
        return min(
            _soft_band(du, 0.5, self.soft_edge),
            _soft_band(dv, 0.5, self.soft_edge),
        )

    def _sample_pad(self, seed: float) -> Optional[Tuple[float, float, float]]:
        """Sample a world point inside the pad with soft-edge weight, or None if rejected."""
        cx, cy, w, h = self._pad_frame()
        if w < 1e-3 or h < 1e-3:
            return None
        x = cx + (_frac_hash(seed, 1.1) - 0.5) * w
        y = cy + (_frac_hash(seed, 2.3) - 0.5) * h
        wt = self._pad_weight(x, y)
        if wt <= 0.0:
            return None
        # soft rejection near the band
        if _frac_hash(seed, 3.7) > max(0.15, wt):
            return None
        return (x, y, wt)


# ---------------------------------------------------------------------------
# Beam domain (line-like dual)
# ---------------------------------------------------------------------------


class BeamModel(Enum):
    POINT_POINT = "point_point"
    ORIGIN_ANGLE_LENGTH = "origin_angle_length"


class BeamDomainFx(SpatialFx):
    """Soft directed segment + lateral width. Dual: p1–p2 or origin+angle+length."""

    _has_domain_frame = True

    p1 = ContainerSlot(Point)
    p2 = ContainerSlot(Point)
    origin = ContainerSlot(Point)
    angle = ScalarSlot()
    length = ScalarSlot(magnitude=True)
    width = ScalarSlot(magnitude=True)

    _PART_NAMES = ("p1", "p2", "origin", "angle", "length", "width")

    def _set_defining_parts(self, *defining: str) -> None:
        self._mark_defining_parts(*defining, catalog=self._PART_NAMES)

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill a Derivate part on first access (``rain.width`` on a corner pad)."""
        with self._no_update():
            self._update_impl()

    def _beam_frame(self) -> Tuple[float, float, float, float, float, float]:
        """``(x0, y0, x1, y1, length, width)`` along the beam."""
        w = abs(self.width)
        if self.model == BeamModel.POINT_POINT:
            x0, y0 = get_xy(self.p1, bare=True)
            x1, y1 = get_xy(self.p2, bare=True)
            length = math.hypot(x1 - x0, y1 - y0)
            return x0, y0, x1, y1, length, w
        x0, y0 = get_xy(self.origin, bare=True)
        ang = math.radians(float(self.angle))
        length = abs(self.length)
        x1 = x0 + math.cos(ang) * length
        y1 = y0 + math.sin(ang) * length
        return x0, y0, x1, y1, length, w

    def _update_impl(self) -> None:
        x0, y0, x1, y1, length, w = self._beam_frame()
        if self.model == BeamModel.POINT_POINT:
            ang = math.degrees(math.atan2(y1 - y0, x1 - x0)) if length > 1e-9 else 0.0
            self._takein_live_derivate("origin", (x0, y0))
            self._takein_live_derivate("angle", ang)
            self._takein_live_derivate("length", length)
            # width is defining in both models
        else:
            self._takein_live_derivate("p1", (x0, y0))
            self._takein_live_derivate("p2", (x1, y1))

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        x0, y0, x1, y1, length, w = self._beam_frame()
        hw = max(w * 0.5, 4.0)
        pad = hw + 8.0
        return (
            min(x0, x1) - pad,
            min(y0, y1) - pad,
            max(x0, x1) + pad,
            max(y0, y1) + pad,
        )

    def _beam_weight(self, x: float, y: float) -> float:
        x0, y0, x1, y1, length, w = self._beam_frame()
        if length < 1e-6:
            return 0.0
        dx, dy = x1 - x0, y1 - y0
        t = ((x - x0) * dx + (y - y0) * dy) / (length * length)
        if t < 0.0 or t > 1.0:
            return 0.0
        px = x0 + t * dx
        py = y0 + t * dy
        lat = math.hypot(x - px, y - py)
        half = max(w * 0.5, 1e-6)
        axial = min(t, 1.0 - t) * length  # distance toward end along axis
        # soft ends + lateral
        end_soft = _soft_band(axial, length * 0.5, max(self.soft_edge, 0.05))
        lat_soft = _soft_band(half - lat, half, self.soft_edge)
        return min(end_soft, lat_soft)

    def _collision_specs(self) -> List[Tuple]:
        x0, y0, x1, y1, length, width = self._beam_frame()
        return [_beam_obb_spec(x0, y0, x1, y1, length, width)]


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------


def _default_directed_length(width, length, ratio: float):
    """If ``length`` is omitted or non-positive, use ``ratio * width``."""
    if isinstance(length, (int, float)) and float(length) <= 0.0:
        try:
            return float(width) * ratio
        except (TypeError, ValueError):
            return 40.0 * ratio
    return length


def _fire_angle_rad(angle_deg: float) -> Tuple[float, float, float, float]:
    """Emission axis from angle degrees (0=+X, 90=+Y). Returns (dx, dy, px, py)."""
    rad = math.radians(float(angle_deg))
    dx, dy = math.cos(rad), math.sin(rad)
    return dx, dy, -dy, dx  # dir + left perpendicular


def _assign_angle(fx, angle) -> None:
    """Default angle scalar (degrees). Construction-time copy only."""
    _init_scalar(fx, "angle", angle if angle is not None else 90.0)


def _beam_obb_spec(
    x0: float, y0: float, x1: float, y1: float, length: float, width: float,
) -> Tuple:
    """Collision spec for a beam segment (circle if degenerate)."""
    half = max(0.5, abs(float(width)) * 0.5)
    length = float(length)
    if length < 1e-12:
        return ("circle", float(x0), float(y0), half)
    ang = math.atan2(y1 - y0, x1 - x0)
    cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    return ("obb", cx, cy, length * 0.5, half, ang)


def _plume_width_t(width: float) -> float:
    """0 at width 10, 1 at 70 (clamped)."""
    t = (float(width) - 10.0) / 60.0
    return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)


def _plume_lat_mul(width: float) -> float:
    """Plume lateral hitbox vs current: 1.25× at width 10, 0.85× at 70."""
    return 1.25 + (0.85 - 1.25) * _plume_width_t(width)


def _plume_along_lift(width: float, reach: float, base_inset: float) -> float:
    """Shift the OBB toward the tip; 25% of box height at width 70."""
    box_h = abs(float(reach)) + abs(float(base_inset))
    return _plume_width_t(width) * 0.25 * box_h


# Catalog default plume length — pin the base lift here, not at the slider max.
_PLUME_BASE_LENGTH = 57.0


def _fire_emission_obb(
    center,
    angle,
    *,
    reach: float,
    half_lat: float,
    base_inset: float,
    along_shift: float = 0.0,
) -> Tuple:
    """OBB along emission: base slightly behind center, tip at ``reach``.

    ``along_shift`` translates the whole box on the emission axis (negative =
    toward base / opposite rise for a default +Y plume).
    """
    cx, cy = get_xy(center, bare=True)
    dx, dy, _, _ = _fire_angle_rad(angle)
    ang_rad = math.atan2(dy, dx)
    shift = float(along_shift)
    s0 = -float(base_inset) + shift
    s1 = float(reach) + shift
    mid = 0.5 * (s0 + s1)
    half_len = 0.5 * abs(s1 - s0)
    return (
        "obb",
        cx + dx * mid,
        cy + dy * mid,
        max(1e-6, half_len),
        max(1e-6, float(half_lat)),
        ang_rad,
    )


def _fire_emission_ellipse(
    center,
    angle,
    *,
    reach: float,
    half_lat: float,
    base_inset: float,
    along_shift: float = 0.0,
) -> Tuple:
    """Same frame as :func:`_fire_emission_obb`, as an ellipse."""
    spec = _fire_emission_obb(
        center, angle,
        reach=reach, half_lat=half_lat,
        base_inset=base_inset, along_shift=along_shift,
    )
    return ("ellipse",) + spec[1:]


def _star_path(cx: float, cy: float, outer: float, inner: float, n: int, rot: float) -> skia.Path:
    """Regular n-pointed star path (two concentric radii)."""
    path = skia.Path()
    n = max(3, min(12, int(n)))
    for i in range(n * 2):
        ang = rot + (i * math.pi / n) - math.pi * 0.5
        rr = outer if (i % 2 == 0) else inner
        x = cx + math.cos(ang) * rr
        y = cy + math.sin(ang) * rr
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.close()
    return path


# ---------------------------------------------------------------------------
# Effect implementations (CPU-optimized) — live in spatial_fx_effects module body
# ---------------------------------------------------------------------------

from .spatial_fx_effects import (  # noqa: E402
    Fire,
    Sunburst,
    Starburst,
    Rain,
    Jet,
    Sparks,
    GlowSpot,
    Orb,
    Warp,
    Portal,
)

__all__ = [
    "SpatialFx",
    "PadModel",
    "BeamModel",
    "PointDomainFx",
    "PadDomainFx",
    "BeamDomainFx",
    "register_spatial",
    "unregister_spatial",
    "tick_all_spatial_fx",
    "registered_count",
    "set_now_fn",
    "Fire",
    "Sunburst",
    "Starburst",
    "Rain",
    "Jet",
    "Sparks",
    "GlowSpot",
    "Orb",
    "Warp",
    "Portal",
]
