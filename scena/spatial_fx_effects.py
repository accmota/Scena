"""
SpatialFx effect implementations — CPU-optimized ambient emitters.

Policy
------
Always (including ``high``): paint reuse, SoA particle banks, single-pass CTM
per emitter where possible, prebaked soft-disc stamps instead of per-call
``GradientShader.MakeRadial``, recycle spawn slots (no list rebuild).

``medium`` / ``low`` only (may drop a little fidelity where noted): fewer lobes/steps,
no particle/tongue halos, coarser particle caps, amortized domain weight checks.
Some looks (Fire style=soft, Sunburst) keep full high fidelity at every quality.

Public constructors live under the standard names (``Fire``, ``Rain``, …);
domains and registration stay in :mod:`scena.spatial_fx`.
"""
from __future__ import annotations

import math
from array import array
from typing import List, Literal, Optional, Sequence, Tuple, Union

FireStyle = Literal["camp", "soft", "plume", "tongues", "embers", "blaze"]
FIRE_STYLES = ("camp", "soft", "plume", "tongues", "embers", "blaze")

import skia

from ._pkg import is_framework_module
from .color import ColorLike, resolve_rgb
from .validate import expect_choice, fixed_magnitude
from .fx_quality import (
    fidelity_is_lite,
    fidelity_is_max,
    fidelity_is_survival,
    particle_scale,
)
from .shapes import get_xy
from .state import ScalarSlot, _init_scalar, _init_composite
from .spatial_fx import (
    BeamDomainFx,
    BeamModel,
    PadDomainFx,
    PadModel,
    PointDomainFx,
    SpatialFx,
    _assign_angle,
    _bare_num,
    _beam_obb_spec,
    _default_directed_length,
    _fire_angle_rad,
    _fire_emission_ellipse,
    _fire_emission_obb,
    _frac_hash,
    _reject_positional_fx,
    fx_placement_hints,
    _now,
    _shader_time,
    _plume_along_lift,
    _plume_lat_mul,
    _PLUME_BASE_LENGTH,
    _soft_band,
    _star_path,
    _plate_size,
    _plate_surface,
    _wrapped_phase,
)
from ._sksl_backdrop import blaze_builder, portal_builder, warp_builder


# ---------------------------------------------------------------------------
# Shared draw / bank helpers
# ---------------------------------------------------------------------------

_SOFT_DISC: Optional[skia.Image] = None
_SOFT_DISC_N = 64

# Thread-local-ish modular paints (single-threaded Scena frame path).
_PAINT_PLUS = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kPlus,
)
# Soft-stamp path only (always owns a ColorFilter; never cleared to None).
_PAINT_SOFT = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kPlus,
)
_PAINT_FILL = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kSrcOver,
)
_PAINT_STROKE = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kStroke_Style,
    BlendMode=skia.BlendMode.kPlus,
    StrokeWidth=1.0,
)
_PAINT_MASK = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kDstIn,
)
# Shader draws: always setShader before use — never cleared.
_PAINT_GRAD = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kPlus,
)
_PAINT_GRAD_STROKE = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kStroke_Style,
    BlendMode=skia.BlendMode.kPlus,
    StrokeWidth=1.0,
)
_PAINT_ORB_BODY = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kSrcOver,
)
_PAINT_ORB_CUT = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kDstOut,
)
_PAINT_WARP = skia.Paint(
    AntiAlias=True,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kSrcOver,
)
# Portal / blaze shader draws (setShader before every use; additive light).
_PAINT_LIGHT = skia.Paint(
    AntiAlias=False,
    Style=skia.Paint.kFill_Style,
    BlendMode=skia.BlendMode.kPlus,
)
# Blaze plate blit (never carries a shader).
_PAINT_PLATE = skia.Paint(
    AntiAlias=False,
    BlendMode=skia.BlendMode.kPlus,
)
_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)


def _soft_disc_image() -> skia.Image:
    """White soft radial disc (premul) — tint with ColorFilter/paint color."""
    global _SOFT_DISC
    if _SOFT_DISC is not None:
        return _SOFT_DISC
    n = _SOFT_DISC_N
    half = n * 0.5
    surf = skia.Surface.MakeRasterN32Premul(n, n)
    c = surf.getCanvas()
    c.clear(skia.Color4f(0, 0, 0, 0))
    paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
    paint.setShader(
        skia.GradientShader.MakeRadial(
            (half, half),
            half,
            [
                skia.Color4f(1, 1, 1, 1.0),
                skia.Color4f(1, 1, 1, 0.55),
                skia.Color4f(1, 1, 1, 0.0),
            ],
            [0.0, 0.4, 1.0],
            skia.TileMode.kClamp,
        )
    )
    c.drawCircle(half, half, half, paint)
    _SOFT_DISC = surf.makeImageSnapshot()
    return _SOFT_DISC


def _tint_filter(r: float, g: float, b: float, a: float):
    """Premul color matrix: white stamp → rgba. Rebuilt each call is still cheaper than a gradient."""
    # Skia ColorMatrix is 20 floats row-major 4x5.
    return skia.ColorFilters.Matrix((
        r, 0, 0, 0, 0,
        0, g, 0, 0, 0,
        0, 0, b, 0, 0,
        0, 0, 0, a, 0,
    ))


def _draw_soft(
    canvas: skia.Canvas,
    cx: float,
    cy: float,
    rad: float,
    r: float,
    g: float,
    b: float,
    a: float,
) -> None:
    if a < 0.02 or rad < 0.5:
        return
    img = _soft_disc_image()
    p = _PAINT_SOFT
    p.setColorFilter(_tint_filter(r, g, b, a))
    dst = skia.Rect.MakeXYWH(cx - rad, cy - rad, rad * 2.0, rad * 2.0)
    canvas.drawImageRect(img, dst, _SAMPLING, p)


def _draw_soft_local(
    canvas: skia.Canvas,
    rad: float,
    r: float,
    g: float,
    b: float,
    a: float,
) -> None:
    """Soft disc at local origin (CTM already applied)."""
    _draw_soft(canvas, 0.0, 0.0, rad, r, g, b, a)


def _set_plus_color(paint: skia.Paint, r: float, g: float, b: float, a: float) -> skia.Paint:
    """Solid Plus fill color (paint must not carry a leftover shader)."""
    paint.setBlendMode(skia.BlendMode.kPlus)
    paint.setStyle(skia.Paint.kFill_Style)
    paint.setAntiAlias(True)
    paint.setColor4f(skia.Color4f(r, g, b, a))
    return paint


# ---------------------------------------------------------------------------
# SoA particle bank
# ---------------------------------------------------------------------------


class _PartBank:
    """Packed SoA particles. Live count in ``n``; indices ``0..n-1``.

    Fields always present: x,y,vx,vy,life,mlife,r0.
    Optional extras via kwargs of arrays.
    """

    __slots__ = ("cap", "n", "x", "y", "vx", "vy", "life", "mlife", "r0", "hot", "wt", "extra")

    def __init__(self, capacity: int, *, with_hot: bool = False, with_wt: bool = False):
        self.cap = max(8, int(capacity))
        self.n = 0
        self.x = array("f", [0.0]) * self.cap
        self.y = array("f", [0.0]) * self.cap
        self.vx = array("f", [0.0]) * self.cap
        self.vy = array("f", [0.0]) * self.cap
        self.life = array("f", [0.0]) * self.cap
        self.mlife = array("f", [0.0]) * self.cap
        self.r0 = array("f", [0.0]) * self.cap
        self.hot = array("f", [0.0]) * self.cap if with_hot else None
        self.wt = array("f", [0.0]) * self.cap if with_wt else None
        self.extra = {}

    def clear(self) -> None:
        self.n = 0

    def ensure_cap(self, need: int) -> None:
        if need <= self.cap:
            return
        new_cap = max(need, self.cap * 2)
        def grow(a: array) -> array:
            out = array("f", [0.0]) * new_cap
            out[: self.cap] = a
            return out
        self.x = grow(self.x)
        self.y = grow(self.y)
        self.vx = grow(self.vx)
        self.vy = grow(self.vy)
        self.life = grow(self.life)
        self.mlife = grow(self.mlife)
        self.r0 = grow(self.r0)
        if self.hot is not None:
            self.hot = grow(self.hot)
        if self.wt is not None:
            self.wt = grow(self.wt)
        self.cap = new_cap

    def try_spawn(
        self,
        x: float,
        y: float,
        vx: float,
        vy: float,
        mlife: float,
        r0: float,
        *,
        hot: float = 0.0,
        wt: float = 1.0,
    ) -> bool:
        if self.n >= self.cap:
            return False
        i = self.n
        self.x[i] = x
        self.y[i] = y
        self.vx[i] = vx
        self.vy[i] = vy
        self.life[i] = 0.0
        self.mlife[i] = mlife
        self.r0[i] = r0
        if self.hot is not None:
            self.hot[i] = hot
        if self.wt is not None:
            self.wt[i] = wt
        self.n = i + 1
        return True

    def kill_swap(self, i: int) -> None:
        """Remove live index i via swap-with-last."""
        last = self.n - 1
        if i < last:
            self.x[i] = self.x[last]
            self.y[i] = self.y[last]
            self.vx[i] = self.vx[last]
            self.vy[i] = self.vy[last]
            self.life[i] = self.life[last]
            self.mlife[i] = self.mlife[last]
            self.r0[i] = self.r0[last]
            if self.hot is not None:
                self.hot[i] = self.hot[last]
            if self.wt is not None:
                self.wt[i] = self.wt[last]
        self.n = last


def _max_parts(base: int, pscale: float, tier_mul: float) -> int:
    return max(4, int(base * pscale * tier_mul) + 4)


def _tier_mul() -> float:
    """Particle capacity multiplier; 1.0 at high (no fidelity cut)."""
    if fidelity_is_survival():
        return 0.55
    if fidelity_is_lite():
        return 0.8
    return 1.0


def _use_halos() -> bool:
    """Soft halos / multi-pass flecks — high only keeps full look."""
    return not fidelity_is_lite()


# ---------------------------------------------------------------------------
# Fire family (style= camp / soft / plume / tongues / embers)
# ---------------------------------------------------------------------------

_FIRE_STYLES: dict = {}


class Fire(PointDomainFx):
    """Hearth fire. ``style`` selects the look; not interned.

    Zero-arg ``Fire()`` is ``style="camp"`` at a default center. Call shapes::

        Fire(center=(200, 150))
        Fire(center=(200, 150), radius=40)                     # camp / soft: disc
        Fire(center=(200, 150), width=40, style="plume")       # directed
        Fire(center=(200, 150), width=26, length=60, style="plume")
        Fire(center=lambda: ship.center)                       # follows the ship

    Keyword-only, like its sibling ``Circle``: positional numbers and
    ``at=`` / ``x=`` / ``pos=`` raise with the ``center=`` spelling.

    ``style`` is ``camp`` | ``soft`` | ``plume`` | ``tongues`` | ``embers`` |
    ``blaze``. Disc styles take ``radius``; directed styles take ``width`` +
    ``length`` (along ``angle``; omit ``length`` for a style-default ratio ×
    ``width``). ``blaze`` is a volumetric column — a showpiece effect (~0.8 ms per
    256² fire on a weak GPU); at medium / low quality it draws the ``plume``
    look instead.
    Not a look (``shape.visual``) and not canvas post-FX.

    Args:
        center: Where it is, in design units. A function follows: ``center=lambda:
            ship.center``. Default: the design center.
        style: ``"camp"`` (default) · ``"soft"`` · ``"plume"`` · ``"tongues"`` ·
            ``"embers"`` · ``"blaze"``.
        radius: Disc size for camp / soft (default 45).
        width: Jet width for plume / tongues / embers / blaze.
        length: Jet length (0 = the style's ratio × ``width``).
        angle: Jet direction in degrees (default 90 = up).
        amount: Fire intensity.
        speed: Animation speed (default 1.2).
        rate: Particles per second (plume / embers; blaze at medium / low).
        tongues: Flame tongues (tongues style; default 5).
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    def __new__(cls, *args, style: FireStyle = "camp", **kwargs):
        if cls is Fire:
            st = expect_choice(style, FIRE_STYLES, what="Fire style")
            impl = _FIRE_STYLES.get(st, Fire)
            if impl is not Fire:
                return object.__new__(impl)
        elif style != "camp" and not is_framework_module(cls.__module__):
            # An author subclass draws the camp fire: style= was silently
            # ignored (found with AC2).
            expect_choice(style, FIRE_STYLES, what="Fire style")
            raise TypeError(
                f"{cls.__name__} is a Fire subclass: it draws the camp fire, and "
                f"style= cannot change that. Write Fire(style={style!r}) for that style."
            )
        return object.__new__(cls)

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.55

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 45.0,
        amount: float = 1.0,
        speed: float = 1.2,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        _reject_positional_fx(self, args)
        self.amount = float(amount)
        self.speed = float(speed)
        self._seed = _frac_hash(id(self) % 10000, 0.51) * 6.28
        self._init_point_domain(center=center, radius=radius, soft_edge=soft_edge, **kwargs)
        from .style import FlameFill
        self._fill = FlameFill(amount=self.amount, speed=self.speed)

    def _sync_fill(self) -> None:
        fill = self._fill
        fill.amount = float(self.amount)
        fill.speed = float(self.speed)

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 45.0)) * 1.55
        return (cx - r, cy - r, cx + r, cy + r)

    def _tick(self, dt: float, t: float) -> None:
        self._sync_fill()
        self._fill._tick(t)

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 45.0))
        if r < 1.0:
            return
        t = _now() * self.speed
        seed = self._seed
        amt = max(0.35, min(1.5, float(self.amount)))
        self._sync_fill()
        low = fidelity_is_survival()
        # soft glow bed — soft stamps (CPU-cheap) at all tiers
        if low:
            layers = (
                (1.4, 0.34, (1.0, 0.38, 0.05), 0.04),
                (0.75, 0.48, (1.0, 0.85, 0.35), 0.02),
            )
        elif fidelity_is_lite():
            layers = (
                (1.45, 0.32, (1.0, 0.38, 0.05), 0.08),
                (0.7, 0.5, (1.0, 0.85, 0.35), 0.04),
            )
        else:
            layers = (
                (1.45, 0.32, (1.0, 0.38, 0.05), 0.1),
                (0.7, 0.5, (1.0, 0.85, 0.35), 0.05),
            )
        for i, (scale, a0, col, drift) in enumerate(layers):
            ox = r * drift * math.sin(t * 1.3 + i * 1.7 + seed)
            oy = r * drift * math.cos(t * 1.1 + i * 2.1 + seed)
            rr = r * scale * (1.0 + 0.07 * math.sin(t * 2.2 + i))
            _draw_soft(skia_canvas, cx + ox, cy + oy, rr, col[0], col[1], col[2], a0 * amt)

        if low:
            return

        # FlameFill core (high + medium) — same visual mechanism as v1
        from .recipes import _procedural_shader
        ox = r * 0.08 * math.sin(t * 1.4 + seed)
        oy = r * 0.06 * math.cos(t * 1.7 + seed)
        rr = r * (0.92 + 0.08 * math.sin(t * 2.1 + seed))
        skia_canvas.saveLayer(
            skia.Rect.MakeLTRB(cx + ox - rr, cy + oy - rr, cx + ox + rr, cy + oy + rr),
            None,
        )
        skia_canvas.translate(cx + ox, cy + oy)
        fill = _PAINT_FILL
        fill.setShader(_procedural_shader(self._fill, 0.0, 0.0, rr))
        fill.setBlendMode(skia.BlendMode.kSrcOver)
        skia_canvas.drawCircle(0, 0, rr, fill)
        mask = _PAINT_MASK
        mask.setShader(
            skia.GradientShader.MakeRadial(
                (0.0, 0.0),
                rr,
                [
                    skia.Color4f(1, 1, 1, 1.0),
                    skia.Color4f(1, 1, 1, 0.7),
                    skia.Color4f(1, 1, 1, 0.0),
                ],
                [0.0, 0.35, 1.0],
                skia.TileMode.kClamp,
            )
        )
        skia_canvas.drawCircle(0, 0, rr, mask)
        skia_canvas.restore()
        # no high-only orbiting hot fleck (medium look; FlameFill + glow stay)


class _FireSoft(Fire):
    """Glow-only bed — soft stamps + paint reuse (high look at all qualities)."""

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.55

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 45.0,
        amount: float = 1.0,
        speed: float = 1.2,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        _reject_positional_fx(self, args)
        self.amount = float(amount)
        self.speed = float(speed)
        self._seed = _frac_hash(id(self) % 10000, 0.62) * 6.28
        self._init_point_domain(center=center, radius=radius, soft_edge=soft_edge, **kwargs)

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 45.0)) * 1.55
        return (cx - r, cy - r, cx + r, cy + r)

    def _collision_specs(self) -> List[Tuple]:
        cx, cy = get_xy(self.center, bare=True)
        r = max(1e-6, abs(_bare_num(self.radius, 45.0)) * 0.5)
        return [("circle", cx, cy, r)]

    def _tick(self, dt: float, t: float) -> None:
        pass

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 45.0))
        if r < 1.0:
            return
        t = _now() * self.speed
        seed = self._seed
        amt = max(0.35, min(1.5, self.amount))
        # High look at all qualities (cheap enough to keep full 4-layer bed).
        layers = (
            (1.5, 0.26 * amt, (1.0, 0.32, 0.04), 0.12),
            (1.1, 0.4 * amt, (1.0, 0.55, 0.08), 0.08),
            (0.72, 0.5 * amt, (1.0, 0.82, 0.28), 0.05),
            (0.38, 0.65 * amt, (1.0, 0.95, 0.55), 0.03),
        )
        for i, (scale, a0, col, drift) in enumerate(layers):
            ox = r * drift * math.sin(t * 1.3 + i * 1.7 + seed)
            oy = r * drift * math.cos(t * 1.1 + i * 2.1 + seed)
            rr = r * scale * (1.0 + 0.07 * math.sin(t * 2.2 + i))
            _draw_soft(skia_canvas, cx + ox, cy + oy, rr, col[0], col[1], col[2], a0)


# ---------------------------------------------------------------------------
# Directed Fire (plume / tongues / embers) — beam knobs, hearth at center
# ---------------------------------------------------------------------------


class _DirectedFire(Fire):
    """Hearth at ``center``; ``width`` lateral, ``length`` along ``angle``."""

    width = ScalarSlot(magnitude=True)
    length = ScalarSlot(magnitude=True)
    angle = ScalarSlot()

    _absent_hints = {w: "Size it with width / length." for w in ("height", "size")}

    _LENGTH_RATIO = 2.2

    def _init_directed_domain(
        self,
        args,
        center,
        width,
        length,
        angle,
        *,
        soft_edge,
        **kwargs,
    ):
        for name in ("radius", "height"):
            if name in kwargs:
                raise TypeError(
                    "Fire plume/tongues/embers use width= and length=, "
                    f"not {name}="
                )
        _reject_positional_fx(self, args)
        length = _default_directed_length(width, length, self._LENGTH_RATIO)
        self._init_point_domain(
            center=center,
            skip_radius=True,
            extra_defining=("width", "length", "angle"),
            soft_edge=soft_edge,
            **kwargs,
        )
        with self._batch_update():
            _init_scalar(self, "width", width)
            _init_scalar(self, "length", length)
            _assign_angle(self, angle)

    def _point_frame(self) -> Tuple[float, ...]:
        cx, cy = get_xy(self.center, bare=True)
        return (
            cx, cy,
            abs(_bare_num(self.width, 0.0)),
            abs(float(self.length)),
            float(_bare_num(self.angle, 90.0)),
        )


# ---------------------------------------------------------------------------
# Fire style=plume
# ---------------------------------------------------------------------------


class _LookPlume(_DirectedFire):
    """Rising plume — SoA + shared CTM + soft stamps; full flecks at high."""

    _LENGTH_RATIO = 2.2

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.45

    def __init__(
        self,
        *args,
        center=None,
        width: float = 42.0,
        rate: float = 70.0,
        length: float = 0.0,
        amount: float = 1.0,
        angle: float = 90.0,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        self.rate = float(rate)
        self.amount = float(amount)
        self._spawn_acc = 0.0
        self._seed = _frac_hash(id(self) % 10000, 0.31) * 1000.0
        self._bank = _PartBank(120, with_hot=True)
        self._init_directed_domain(
            args, center, width, length, angle, soft_edge=soft_edge, **kwargs,
        )

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.width, 42.0))
        r_lat = max(r, 10.0)
        h = max(abs(self.length), 20.0)
        dx, dy, px, py = _fire_angle_rad(_bare_num(self.angle, 90.0))
        tips = [
            (cx + r_lat * px, cy + r_lat * py),
            (cx - r_lat * px, cy - r_lat * py),
            (cx + dx * h + r_lat * px, cy + dy * h + r_lat * py),
            (cx + dx * h - r_lat * px, cy + dy * h - r_lat * py),
            (cx - dx * r * 0.4, cy - dy * r * 0.4),
        ]
        xs = [p[0] for p in tips]
        ys = [p[1] for p in tips]
        pad = r_lat * 0.35
        return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)

    def _collision_specs(self) -> List[Tuple]:
        r = abs(_bare_num(self.width, 42.0))
        h = abs(self.length)
        reach = h * 0.663
        base_inset = r * 0.28
        along = max(20.0, reach + base_inset)
        reach = along - base_inset
        half_lat = max(10.0, r * 0.901 * _plume_lat_mul(r))
        return [_fire_emission_ellipse(
            self.center, _bare_num(self.angle, 90.0),
            reach=reach,
            half_lat=half_lat,
            base_inset=base_inset,
            along_shift=(
                -r * 0.14
                + _plume_along_lift(r, _PLUME_BASE_LENGTH * 0.663, base_inset)
            ),
        )]

    def _tick(self, dt: float, t: float) -> None:
        pscale = particle_scale()
        self._spawn_acc += self.rate * self.amount * pscale * dt
        n_spawn = int(self._spawn_acc)
        self._spawn_acc -= n_spawn
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.width, 42.0))
        h = abs(self.length)
        dx, dy, px, py = _fire_angle_rad(_bare_num(self.angle, 90.0))
        max_parts = _max_parts(100, pscale, _tier_mul())
        self._bank.ensure_cap(max_parts)
        # shrink if capacity reduced by quality
        while self._bank.n > max_parts:
            self._bank.kill_swap(self._bank.n - 1)

        for _ in range(n_spawn):
            if self._bank.n >= max_parts:
                break
            self._seed += 1.07
            lat = (_frac_hash(self._seed, 1.1) - 0.5) * r * 1.4
            base_along = (_frac_hash(self._seed, 2.2) - 0.5) * r * 0.25
            if abs(lat) > r * 0.9 and _frac_hash(self._seed, 3.0) > 0.35:
                continue
            rise = (h * 0.55 + h * 0.7 * _frac_hash(self._seed, 4.0)) * self.amount
            vx = dx * rise + px * ((_frac_hash(self._seed, 5.1) - 0.5) * 30.0)
            vy = dy * rise + py * ((_frac_hash(self._seed, 5.2) - 0.5) * 30.0)
            self._bank.try_spawn(
                cx + px * lat + dx * base_along,
                cy + py * lat + dy * base_along,
                vx, vy,
                0.35 + 0.55 * _frac_hash(self._seed, 6.2),
                4.0 + 10.0 * _frac_hash(self._seed, 7.3),
                hot=_frac_hash(self._seed, 8.4),
            )

        b = self._bank
        # Wobble: full sin at high; cheaper lateral drift at lite
        if fidelity_is_lite():
            i = 0
            while i < b.n:
                b.life[i] += dt
                u = b.life[i] / max(b.mlife[i], 1e-6)
                if u >= 1.0:
                    b.kill_swap(i)
                    continue
                b.x[i] += b.vx[i] * dt
                b.y[i] += b.vy[i] * dt
                drag = max(0.0, 1.0 - 0.55 * dt)
                b.vx[i] *= drag
                b.vy[i] *= drag
                i += 1
        else:
            i = 0
            while i < b.n:
                b.life[i] += dt
                u = b.life[i] / max(b.mlife[i], 1e-6)
                if u >= 1.0:
                    b.kill_swap(i)
                    continue
                wob = math.sin(t * 9.0 + b.x[i] * 0.05) * 8.0 * dt
                b.x[i] += b.vx[i] * dt + px * wob
                b.y[i] += b.vy[i] * dt + py * wob
                drag = max(0.0, 1.0 - 0.55 * dt)
                b.vx[i] *= drag
                b.vy[i] *= drag
                i += 1

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.width, 42.0))
        ang = _bare_num(self.angle, 90.0)
        # base glow — one CTM
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        skia_canvas.rotate(ang - 90.0)
        skia_canvas.scale(1.0, 0.55)
        for scale, a, col in (
            (1.1, 0.42, (1.0, 0.28, 0.02)),
            (0.7, 0.55, (1.0, 0.55, 0.1)),
        ):
            _draw_soft_local(
                skia_canvas, max(r * scale, 1.0),
                col[0], col[1], col[2], a * self.amount,
            )
        skia_canvas.restore()

        b = self._bank
        if b.n <= 0:
            return
        s = self.amount
        halos = _use_halos()
        # one rotate for all flecks → axis-aligned stretched ovals in emission frame
        skia_canvas.save()
        # Draw in world with per-particle translate only (no rotate if ang==90 optimization)
        if abs(ang - 90.0) < 0.5:
            for i in range(b.n):
                u = b.life[i] / max(b.mlife[i], 1e-6)
                a = (1.0 - u) ** 1.15 * 0.95 * s
                if a < 0.03:
                    continue
                hot = b.hot[i] if b.hot is not None else 0.5
                if u < 0.35:
                    cr, cg, cb = 1.0, 0.92 - 0.2 * hot, 0.45 + 0.2 * hot
                elif u < 0.7:
                    cr, cg, cb = 1.0, 0.45 + 0.25 * hot, 0.08
                else:
                    cr, cg, cb = 0.55, 0.12, 0.04
                    a *= 0.7
                rx = max(b.r0[i] * (1.0 - 0.55 * u), 1.0)
                ry = max(b.r0[i] * (1.3 + 0.9 * u), rx)
                # elliptical via CTM scale once
                skia_canvas.save()
                skia_canvas.translate(b.x[i], b.y[i])
                skia_canvas.scale(1.0, ry / rx)
                _set_plus_color(_PAINT_PLUS, cr, cg, cb, a * 0.85)
                skia_canvas.drawCircle(0, 0, rx * 0.55, _PAINT_PLUS)
                if halos:
                    _draw_soft_local(skia_canvas, rx, cr, cg, cb, a * 0.65)
                skia_canvas.restore()
        else:
            for i in range(b.n):
                u = b.life[i] / max(b.mlife[i], 1e-6)
                a = (1.0 - u) ** 1.15 * 0.95 * s
                if a < 0.03:
                    continue
                hot = b.hot[i] if b.hot is not None else 0.5
                if u < 0.35:
                    cr, cg, cb = 1.0, 0.92 - 0.2 * hot, 0.45 + 0.2 * hot
                elif u < 0.7:
                    cr, cg, cb = 1.0, 0.45 + 0.25 * hot, 0.08
                else:
                    cr, cg, cb = 0.55, 0.12, 0.04
                    a *= 0.7
                rx = max(b.r0[i] * (1.0 - 0.55 * u), 1.0)
                ry = max(b.r0[i] * (1.3 + 0.9 * u), rx)
                skia_canvas.save()
                skia_canvas.translate(b.x[i], b.y[i])
                skia_canvas.rotate(ang - 90.0)
                skia_canvas.scale(1.0, ry / rx)
                _set_plus_color(_PAINT_PLUS, cr, cg, cb, a * 0.85)
                skia_canvas.drawCircle(0, 0, rx * 0.55, _PAINT_PLUS)
                if halos:
                    _draw_soft_local(skia_canvas, rx, cr, cg, cb, a * 0.65)
                skia_canvas.restore()
        skia_canvas.restore()


# ---------------------------------------------------------------------------
# Fire style=blaze (volumetric column; plume look at medium / low)
# ---------------------------------------------------------------------------

# Per-octave rise / swirl rates (rad/s at speed 1); the octave frequency is
# folded in so each octave scrolls at the same world speed.
_BLAZE_FREQS = (1.6, 1.6 * 1.8, 1.6 * 1.8 ** 2, 1.6 * 1.8 ** 3)
_BLAZE_RISE = 2.6
_BLAZE_SWIRL = 0.45
_BLAZE_TWIST = 0.5
# Plate box in fire units (1 = half the width): sideways reach, below the hearth, over the tip.
_BLAZE_X = 1.9
_BLAZE_BELOW = 0.6
_BLAZE_OVER = 0.25
# Collider vs plume's ellipse: the column is taller and slimmer than a plume.
_BLAZE_HIT_LONG = 1.25
_BLAZE_HIT_SLIM = 0.7


class _LookBlaze(_LookPlume):
    """Volumetric column: SkSL march on a reduced plate at high / max.

    High: ½-res plate, 32 steps. Max: full-res plate, 50 steps (reference).
    Medium / low: the plume particle look (``_LookPlume`` tick + draw) — the
    march costs ~0.8 ms per 256² on a weak GPU, so it never runs there.
    """

    _LENGTH_RATIO = 2.4

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.45

    def __init__(
        self,
        *args,
        center=None,
        width: float = 42.0,
        rate: float = 70.0,
        length: float = 0.0,
        amount: float = 1.0,
        angle: float = 90.0,
        speed: float = 1.2,
        **kwargs,
    ):
        self.speed = float(speed)
        self._plate_cache = None
        super().__init__(
            *args, center=center, width=width, rate=rate, length=length,
            amount=amount, angle=angle, **kwargs,
        )

    def _uses_march(self) -> bool:
        return not fidelity_is_lite()

    def _collision_specs(self) -> List[Tuple]:
        """Plume's emission ellipse, reshaped to the taller, slimmer column."""
        r = abs(_bare_num(self.width, 42.0))
        base_inset = r * 0.28
        along = max(20.0, abs(self.length) * 0.663 + base_inset) * _BLAZE_HIT_LONG
        half_lat = max(7.0, r * 0.901 * _plume_lat_mul(r) * _BLAZE_HIT_SLIM)
        return [_fire_emission_ellipse(
            self.center, _bare_num(self.angle, 90.0),
            reach=along - base_inset,
            half_lat=half_lat,
            base_inset=base_inset,
            along_shift=(
                -r * 0.14
                + _plume_along_lift(r, _PLUME_BASE_LENGTH * 0.663, base_inset)
            ),
        )]

    def _tick(self, dt: float, t: float) -> None:
        if self._uses_march():
            if self._bank.n:
                self._bank.n = 0
            return
        super()._tick(dt, t)

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        unit = max(abs(_bare_num(self.width, 42.0)), 2.0) * 0.5
        h = max(abs(float(self.length)), 20.0)
        dx, dy, px, py = _fire_angle_rad(_bare_num(self.angle, 90.0))
        lat = unit * _BLAZE_X
        y0 = -unit * _BLAZE_BELOW
        y1 = h + unit * _BLAZE_OVER
        xs = []
        ys = []
        for a in (y0, y1):
            for s in (-lat, lat):
                xs.append(cx + dx * a + px * s)
                ys.append(cy + dy * a + py * s)
        return (min(xs), min(ys), max(xs), max(ys))

    def _plate_frame(self, device_scale: float):
        """Local rect (fire frame, design units), used plate px, march steps."""
        unit = max(abs(_bare_num(self.width, 42.0)), 2.0) * 0.5
        h = max(abs(float(self.length)), 20.0)
        x0, x1 = -unit * _BLAZE_X, unit * _BLAZE_X
        y0, y1 = -unit * _BLAZE_BELOW, h + unit * _BLAZE_OVER
        full = fidelity_is_max()
        res = 1.0 if full else 0.5
        pw = max(8, int(round((x1 - x0) * device_scale * res)))
        ph = max(8, int(round((y1 - y0) * device_scale * res)))
        bw, bh = _plate_size(pw, ph)
        pw, ph = min(pw, bw), min(ph, bh)
        steps = 50.0 if full else 32.0
        return (x0, y0, x1, y1), (pw, ph), (bw, bh), unit, h, steps

    def draw(self, skia_canvas: skia.Canvas) -> None:
        if not self._uses_march():
            super().draw(skia_canvas)
            return
        cx, cy = get_xy(self.center, bare=True)
        if abs(_bare_num(self.width, 42.0)) < 1.0:
            return
        ang = _bare_num(self.angle, 90.0)
        m = skia_canvas.getTotalMatrix()
        dev = math.sqrt(abs(
            m.getScaleX() * m.getScaleY() - m.getSkewX() * m.getSkewY()
        )) or 1.0
        (x0, y0, x1, y1), (pw, ph), (bw, bh), unit, h, steps = self._plate_frame(dev)
        surf = _plate_surface(self, bw, bh)
        sc = surf.getCanvas()
        sc.clear(skia.Color4f(0.0, 0.0, 0.0, 0.0))
        b = blaze_builder
        spd = float(self.speed)
        t = _shader_time()
        b.setUniform("u_plate", [float(pw), float(ph)])
        b.setUniform("u_box", [x0 / unit, x1 / unit, y0 / unit, y1 / unit])
        b.setUniform("u_height", float(h / unit))
        b.setUniform("u_rise", [_wrapped_phase(_BLAZE_RISE * f * spd, t) for f in _BLAZE_FREQS])
        b.setUniform("u_swirl", [_wrapped_phase(_BLAZE_SWIRL * f * spd, t) for f in _BLAZE_FREQS])
        b.setUniform("u_misc", [
            _wrapped_phase(_BLAZE_TWIST * spd, t), steps,
            1.0, max(0.0, min(2.0, float(self.amount))),
        ])
        paint = _PAINT_LIGHT
        paint.setShader(b.makeShader())
        sc.drawRect(skia.Rect.MakeWH(float(pw), float(ph)), paint)
        img = surf.makeImageSnapshot()
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        skia_canvas.rotate(ang - 90.0)
        # Hearth bed under the column (soft stamp, same as plume's base glow).
        amt = max(0.0, min(1.5, float(self.amount)))
        skia_canvas.save()
        skia_canvas.scale(1.0, 0.5)
        _draw_soft_local(skia_canvas, unit * 2.2, 1.0, 0.35, 0.04, 0.42 * amt)
        _draw_soft_local(skia_canvas, unit * 1.3, 1.0, 0.62, 0.16, 0.38 * amt)
        skia_canvas.restore()
        skia_canvas.drawImageRect(
            img, skia.Rect.MakeWH(float(pw), float(ph)),
            skia.Rect.MakeLTRB(x0, y0, x1, y1), _SAMPLING, _PAINT_PLATE,
        )
        skia_canvas.restore()


# ---------------------------------------------------------------------------
# Fire style=tongues
# ---------------------------------------------------------------------------


class _LookTongues(_DirectedFire):
    """Soft tongues — soft stamps; full step/lobe count only at high."""

    _LENGTH_RATIO = 2.6

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.4

    def __init__(
        self,
        *args,
        center=None,
        width: float = 40.0,
        length: float = 0.0,
        tongues: int = 5,
        speed: float = 1.0,
        amount: float = 1.0,
        angle: float = 90.0,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        self.tongues = max(3, min(int(tongues), 9))
        self.speed = float(speed)
        self.amount = float(amount)
        self._phase = _frac_hash(id(self) % 10000, 0.17) * math.tau
        self._init_directed_domain(
            args, center, width, length, angle, soft_edge=soft_edge, **kwargs,
        )
        self._lobes = []
        for i in range(self.tongues):
            self._lobes.append({
                "phase": self._phase + i * 1.37,
                "spread": (_frac_hash(i + 1.0, 2.2) - 0.5) * 1.1,
                "len": 0.7 + 0.55 * _frac_hash(i + 2.0, 3.3),
                "width": 0.35 + 0.35 * _frac_hash(i + 3.0, 4.4),
            })

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.width, 40.0))
        h = max(abs(self.length), r)
        dx, dy, px, py = _fire_angle_rad(_bare_num(self.angle, 90.0))
        tips = [
            (cx + r * 1.4 * px, cy + r * 1.4 * py),
            (cx - r * 1.4 * px, cy - r * 1.4 * py),
            (cx + dx * h + r * px, cy + dy * h + r * py),
            (cx + dx * h - r * px, cy + dy * h - r * py),
        ]
        xs = [p[0] for p in tips]
        ys = [p[1] for p in tips]
        return (min(xs), min(ys), max(xs), max(ys))

    def _collision_specs(self) -> List[Tuple]:
        r = abs(_bare_num(self.width, 40.0))
        h = abs(self.length)
        half_lat = r * 0.363
        extra = max(0.0, h - r) * (1.72 / 2.6)
        half_len = half_lat + 0.5 * extra
        # Pin the square's base; extra length grows only the tip.
        base_inset = 0.80 * half_lat
        reach = 2.0 * half_len - base_inset
        return [_fire_emission_ellipse(
            self.center, _bare_num(self.angle, 90.0),
            reach=reach,
            half_lat=half_lat,
            base_inset=base_inset,
            along_shift=0.0,
        )]

    def _tick(self, dt: float, t: float) -> None:
        pass

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.width, 40.0))
        h = abs(self.length)
        ang = _bare_num(self.angle, 90.0)
        dx, dy, px, py = _fire_angle_rad(ang)
        t = _now() * self.speed

        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        skia_canvas.rotate(ang - 90.0)
        skia_canvas.scale(1.15, 0.5)
        _draw_soft_local(
            skia_canvas, r * 0.85, 1.0, 0.4, 0.05, 0.55 * self.amount,
        )
        skia_canvas.restore()

        # low shares medium (2-step survival looked broken).
        if fidelity_is_lite():
            n_tongues = max(2, self.tongues // 2)
            steps = 3
            halos = False
        else:
            n_tongues = self.tongues
            steps = 7
            halos = True

        for i, lobe in enumerate(self._lobes[:n_tongues]):
            ph = lobe["phase"] + t * (2.4 + 0.4 * i)
            sway = math.sin(ph) * 0.22 + math.sin(ph * 1.7) * 0.1
            tip_h = h * (1.3 + 0.9 * lobe["len"]) / 2.6 * (0.85 + 0.15 * math.sin(ph * 1.3))
            lat0 = r * lobe["spread"] * 0.75 + sway * r * 0.55
            lat1 = r * lobe["spread"] * 0.35 + sway * r * 0.25
            tip_x = cx + dx * tip_h + px * lat0
            tip_y = cy + dy * tip_h + py * lat0
            mid_x = cx + dx * tip_h * 0.45 + px * lat1
            mid_y = cy + dy * tip_h * 0.45 + py * lat1
            base_w = r * lobe["width"] * (0.85 + 0.2 * math.sin(ph * 0.9))

            for s in range(steps):
                u = s / max(steps - 1, 1)
                omu = 1.0 - u
                x = omu * omu * cx + 2 * omu * u * mid_x + u * u * tip_x
                y = omu * omu * cy + 2 * omu * u * mid_y + u * u * tip_y
                rw = max(base_w * (1.0 - 0.82 * u) + r * 0.06, 1.5)
                rh = rw * (1.1 + 0.9 * u)
                a = (0.65 - 0.5 * u) * self.amount * (0.8 + 0.2 * math.sin(ph + s))
                if a < 0.03:
                    continue
                if u < 0.3:
                    col = (1.0, 0.9, 0.35)
                elif u < 0.7:
                    col = (1.0, 0.45, 0.08)
                else:
                    col = (1.0, 0.2, 0.04)
                skia_canvas.save()
                skia_canvas.translate(x, y)
                skia_canvas.rotate(ang - 90.0)
                skia_canvas.scale(1.0, rh / rw)
                _set_plus_color(_PAINT_PLUS, col[0], col[1], col[2], a * 0.9)
                skia_canvas.drawCircle(0, 0, rw * 0.5, _PAINT_PLUS)
                if halos:
                    _draw_soft_local(skia_canvas, rw, col[0], col[1], col[2], a * 0.7)
                skia_canvas.restore()


# ---------------------------------------------------------------------------
# Fire style=embers / Sparks
# ---------------------------------------------------------------------------


class _LookEmbers(_DirectedFire):
    """Ember bed — SoA + soft bed stamps + solid flecks."""

    _LENGTH_RATIO = 2.4

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.5

    def __init__(
        self,
        *args,
        center=None,
        width: float = 38.0,
        length: float = 0.0,
        rate: float = 35.0,
        amount: float = 1.0,
        angle: float = 90.0,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        self.rate = float(rate)
        self.amount = float(amount)
        self._spawn_acc = 0.0
        self._seed = _frac_hash(id(self) % 10000, 0.91) * 1000.0
        self._bank = _PartBank(70)
        self._init_directed_domain(
            args, center, width, length, angle, soft_edge=soft_edge, **kwargs,
        )

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.width, 38.0))
        h = abs(self.length)
        dx, dy, px, py = _fire_angle_rad(_bare_num(self.angle, 90.0))
        tips = [
            (cx + r * 1.3 * px, cy + r * 1.3 * py),
            (cx - r * 1.3 * px, cy - r * 1.3 * py),
            (cx + dx * h, cy + dy * h),
        ]
        xs = [p[0] for p in tips]
        ys = [p[1] for p in tips]
        return (min(xs) - r * 0.3, min(ys) - r * 0.3, max(xs) + r * 0.3, max(ys) + r * 0.3)

    def _collision_specs(self) -> List[Tuple]:
        r = abs(_bare_num(self.width, 38.0))
        h = abs(self.length)
        return [_fire_emission_obb(
            self.center, _bare_num(self.angle, 90.0),
            reach=h * (1.90 / 2.4),
            half_lat=r * 0.749,
            base_inset=r * 0.22,
        )]

    def _tick(self, dt: float, t: float) -> None:
        pscale = particle_scale()
        self._spawn_acc += self.rate * self.amount * pscale * dt
        n_spawn = int(self._spawn_acc)
        self._spawn_acc -= n_spawn
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.width, 38.0))
        h = abs(self.length)
        dx, dy, px, py = _fire_angle_rad(_bare_num(self.angle, 90.0))
        max_parts = _max_parts(55, pscale, _tier_mul())
        self._bank.ensure_cap(max_parts)
        while self._bank.n > max_parts:
            self._bank.kill_swap(self._bank.n - 1)
        for _ in range(n_spawn):
            if self._bank.n >= max_parts:
                break
            self._seed += 1.19
            lat = (_frac_hash(self._seed, 1.0) - 0.5) * r * 1.4
            along = (_frac_hash(self._seed, 2.0) - 0.5) * r * 0.35
            rise = h * (0.658 + 1.535 * _frac_hash(self._seed, 4.0))
            self._bank.try_spawn(
                cx + px * lat + dx * along,
                cy + py * lat + dy * along,
                dx * rise + px * ((_frac_hash(self._seed, 3.0) - 0.5) * 40.0),
                dy * rise + py * ((_frac_hash(self._seed, 3.1) - 0.5) * 40.0),
                0.4 + 0.7 * _frac_hash(self._seed, 5.0),
                1.2 + 2.8 * _frac_hash(self._seed, 6.0),
            )
        b = self._bank
        drag = max(0.0, 1.0 - 1.2 * dt)
        i = 0
        while i < b.n:
            b.life[i] += dt
            if b.life[i] >= b.mlife[i]:
                b.kill_swap(i)
                continue
            b.x[i] += b.vx[i] * dt
            b.y[i] += b.vy[i] * dt
            b.vx[i] *= drag
            b.vy[i] *= drag
            i += 1

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.width, 38.0))
        ang = _bare_num(self.angle, 90.0)
        t = _now()
        pulse = 0.9 + 0.1 * math.sin(t * 4.2)
        beds = (
            (1.25, 0.28, (0.9, 0.2, 0.02)),
            (0.85, 0.48, (1.0, 0.4, 0.05)),
            (0.45, 0.6, (1.0, 0.7, 0.25)),
        )
        if fidelity_is_survival():
            beds = beds[:2]
        elif fidelity_is_lite():
            beds = beds[:2]
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        skia_canvas.rotate(ang - 90.0)
        skia_canvas.scale(1.2, 0.42)
        for scale, a, col in beds:
            _draw_soft_local(
                skia_canvas, max(r * scale * pulse, 1.0),
                col[0], col[1], col[2], a * self.amount,
            )
        skia_canvas.restore()

        b = self._bank
        for i in range(b.n):
            u = b.life[i] / max(b.mlife[i], 1e-6)
            a = (1.0 - u) ** 1.3 * 0.95 * self.amount
            if a < 0.03:
                continue
            if u < 0.25:
                col = (1.0, 0.95, 0.6)
            elif u < 0.65:
                col = (1.0, 0.55, 0.1)
            else:
                col = (0.7, 0.15, 0.02)
            _set_plus_color(_PAINT_PLUS, col[0], col[1], col[2], a)
            skia_canvas.drawCircle(b.x[i], b.y[i], b.r0[i] * (1.0 - 0.45 * u), _PAINT_PLUS)


# ---------------------------------------------------------------------------
# Sparks — radius is the whole visual envelope
# ---------------------------------------------------------------------------
# Crackle at the classic small size; larger radius mixes toward the former
# Sparks-big look (same code, different parameters).


_SPARK_REF_R = 28.0  # crackle look at this radius
_SPARK_LOOK_X = 1.5
_SPARK_MIX_HI = 1.85  # fully chunky by this scale vs _SPARK_REF_R
_SPARK_BIG_REF_R = 36.0 * 2.025  # former Sparks-big visual size


def _spark_look_mix(radius: float) -> float:
    """0 = crackle, 1 = chunky. Stays crackle through 1.5× ref."""
    s = abs(radius) / max(_SPARK_REF_R, 1e-6)
    if s <= _SPARK_LOOK_X:
        return 0.0
    if s >= _SPARK_MIX_HI:
        return 1.0
    t = (s - _SPARK_LOOK_X) / (_SPARK_MIX_HI - _SPARK_LOOK_X)
    return t * t * (3.0 - 2.0 * t)


class Sparks(PointDomainFx):
    """Continuous spark field. Not shape ``spark_burst``.

    ``radius`` sizes the whole effect. Small (around 28) is a crackle;
    larger mixes toward a chunky burst with a soft core.

    Args:
        center: Where it is, in design units. A function follows: ``center=lambda:
            ship.center``. Default: the design center.
        radius: Field size (default 28).
        rate: Particles per second (default 40).
        amount: Intensity (1 = default).
        color: Tint (any color form; default: the kind's own).
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.4

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 28.0,
        rate: float = 40.0,
        amount: float = 1.0,
        color: Optional[ColorLike] = None,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        style = kwargs.pop("style", None)
        if style is not None and not (isinstance(style, str) and style.strip() == ""):
            raise TypeError("Sparks has no style")
        _reject_positional_fx(self, args)
        self.rate = float(rate)
        self.amount = float(amount)
        self._rgb = resolve_rgb(color, default=(1.0, 0.85, 0.4))
        self._spawn_acc = 0.0
        self._seed = _frac_hash(id(self) % 10000, 0.7) * 1000.0
        self._bank = _PartBank(90, with_hot=True)
        self._init_point_domain(center=center, radius=radius, soft_edge=soft_edge, **kwargs)

    @property
    def color(self):
        """Spark color (any color form). ``None`` resets to the default. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = resolve_rgb(value, default=(1.0, 0.85, 0.4))

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, _SPARK_REF_R)) * 1.7
        return (cx - r, cy - r, cx + r, cy + r)

    def _tick(self, dt: float, t: float) -> None:
        pscale = particle_scale()
        r = abs(_bare_num(self.radius, _SPARK_REF_R))
        mix = _spark_look_mix(r)
        im = 1.0 - mix
        amt = self.amount
        self._spawn_acc += self.rate * amt * pscale * dt
        n_spawn = int(self._spawn_acc)
        self._spawn_acc -= n_spawn
        cx, cy = get_xy(self.center, bare=True)
        s_small = r / _SPARK_REF_R
        s_big = r / _SPARK_BIG_REF_R
        glow_r = r / 2.025
        max_parts = _max_parts(int(60 + 10 * mix), pscale, _tier_mul())
        self._bank.ensure_cap(max_parts)
        while self._bank.n > max_parts:
            self._bank.kill_swap(self._bank.n - 1)
        for _ in range(n_spawn):
            if self._bank.n >= max_parts:
                break
            self._seed += 1.13
            ang = _frac_hash(self._seed, 1.0) * math.tau
            u_dist = _frac_hash(self._seed, 2.0)
            u_spd = _frac_hash(self._seed, 3.0)
            u_life = _frac_hash(self._seed, 4.0)
            u_r0 = _frac_hash(self._seed, 5.0)
            jitter = (_frac_hash(self._seed, 3.1) - 0.5) * 0.35 * mix
            dx = math.cos(ang + jitter)
            dy = math.sin(ang + jitter)
            dist_s = r * math.sqrt(u_dist) * 0.25
            dist_b = glow_r * (0.15 + 0.35 * u_dist)
            spawn_r = dist_s * im + dist_b * mix
            spd = (
                (40.0 + 120.0 * u_spd) * s_small * im
                + (55.0 + 95.0 * u_spd) * amt * s_big * mix
            )
            mlife = (0.12 + 0.28 * u_life) * im + (0.35 + 0.55 * u_life) * mix
            r0 = (
                (1.0 + 2.2 * u_r0) * s_small * im
                + (3.0 + 7.0 * u_r0) * 0.65 * s_big * mix
            )
            self._bank.try_spawn(
                cx + dx * spawn_r, cy + dy * spawn_r,
                dx * spd, dy * spd,
                mlife, r0, hot=_frac_hash(self._seed, 6.4) * mix,
            )
        b = self._bank
        drag = max(0.0, 1.0 - 0.4 * mix * dt)
        grav = 80.0 * s_small * im
        r_out = r * 1.6
        do_cull = mix < 0.9
        i = 0
        while i < b.n:
            b.life[i] += dt
            if b.life[i] >= b.mlife[i]:
                b.kill_swap(i)
                continue
            b.x[i] += b.vx[i] * dt
            b.y[i] += b.vy[i] * dt
            b.vx[i] *= drag
            b.vy[i] = b.vy[i] * drag - grav * dt
            if do_cull and b.life[i] > 0.05:
                if math.hypot(b.x[i] - cx, b.y[i] - cy) > r_out:
                    b.kill_swap(i)
                    continue
            i += 1

    def draw(self, skia_canvas: skia.Canvas) -> None:
        r = abs(_bare_num(self.radius, _SPARK_REF_R))
        mix = _spark_look_mix(r)
        im = 1.0 - mix
        cr, cg, cb = self.color[:3]
        amt = self.amount
        if mix > 0.02:
            cx, cy = get_xy(self.center, bare=True)
            glow_r = r / 2.025
            skia_canvas.save()
            skia_canvas.translate(cx, cy)
            skia_canvas.scale(1.15, 0.72)
            _draw_soft_local(
                skia_canvas, glow_r * 0.95 * 0.65, cr, cg, cb, 0.55 * amt * mix,
            )
            if _use_halos():
                _draw_soft_local(
                    skia_canvas, glow_r * 0.55 * 0.65,
                    cr * 0.9, cg * 0.55, cb * 0.2, 0.35 * amt * mix,
                )
            skia_canvas.restore()

        trails = _use_halos() and mix < 0.85
        a_exp = 1.2 - 0.1 * mix
        bank = self._bank
        for i in range(bank.n):
            u = bank.life[i] / max(bank.mlife[i], 1e-6)
            a = (1.0 - u) ** a_exp * 0.9 * amt
            if a < 0.03:
                continue
            hot = bank.hot[i] if bank.hot is not None else 0.0
            fg = (
                cg * (1.0 - 0.3 * u) * im
                + (cg * (1.0 - 0.35 * u) + 0.2 * hot * (1.0 - u)) * mix
            )
            fb = cb * (1.0 - 0.6 * u) * im + cb * (1.0 - u) * mix
            _set_plus_color(_PAINT_PLUS, cr, fg, fb, a)
            skia_canvas.drawCircle(
                bank.x[i], bank.y[i], bank.r0[i] * (1.0 - 0.5 * u), _PAINT_PLUS,
            )
            if trails:
                _PAINT_STROKE.setStrokeWidth(1.0)
                _PAINT_STROKE.setColor4f(skia.Color4f(cr, cg, cb, a * 0.45 * im))
                skia_canvas.drawLine(
                    bank.x[i], bank.y[i],
                    bank.x[i] - bank.vx[i] * 0.02,
                    bank.y[i] - bank.vy[i] * 0.02,
                    _PAINT_STROKE,
                )


# ---------------------------------------------------------------------------
# Sunburst / Starburst
# ---------------------------------------------------------------------------


class Sunburst(PointDomainFx):
    """Sunburst — multi-stop pyro core at all qualities (high look everywhere).

    Omit ``color`` for the canonical white→amber star ramp. ``color=`` keeps a
    white-hot core and derives mid / rim / halo from that tint.

    Args:
        center: Where it is, in design units. A function follows: ``center=lambda:
            ship.center``. Default: the design center.
        radius: Reach (default 48).
        amount: Intensity (1 = default).
        speed: Animation speed (1 = default).
        color: Ray tint; ``None`` = white → amber.
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.55

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 48.0,
        amount: float = 1.0,
        speed: float = 1.0,
        color: Optional[ColorLike] = None,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        _reject_positional_fx(self, args)
        self.amount = float(amount)
        self.speed = float(speed)
        self._rgb = None if color is None else resolve_rgb(color)
        self._seed = _frac_hash(id(self) % 10000, 0.77) * 6.28
        self._init_point_domain(center=center, radius=radius, soft_edge=soft_edge, **kwargs)

    @property
    def color(self):
        """Ray tint (any color form), or ``None`` for the default warm rays. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = None if value is None else resolve_rgb(value)

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 48.0)) * 1.35
        return (cx - r, cy - r, cx + r, cy + r)

    def _collision_specs(self) -> List[Tuple]:
        cx, cy = get_xy(self.center, bare=True)
        r = max(1e-6, abs(_bare_num(self.radius, 48.0)) * 0.9)
        return [("circle", cx, cy, r)]

    def _tick(self, dt: float, t: float) -> None:
        pass

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 48.0))
        t = _now() * self.speed + self._seed
        pulse = 0.94 + 0.06 * math.sin(t * 2.4)
        wobble = 1.0 + 0.03 * math.sin(t * 1.7)
        core_r = r * 1.08 * pulse * wobble
        from .effects import draw_pyro_core
        draw_pyro_core(
            skia_canvas, cx, cy, core_r,
            strength=self.amount, alpha=0.98, profile="star",
            color=self._rgb,
        )


class Starburst(PointDomainFx):
    """Starburst — paint reuse; ray count / spines step with quality.

    Args:
        center: Where it is, in design units. A function follows: ``center=lambda:
            ship.center``. Default: the design center.
        radius: Reach (default 40).
        points: Rays (default 5).
        amount: Intensity (1 = default).
        speed: Pulse speed.
        color: Star color (default cream).
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.45

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 40.0,
        points: int = 5,
        amount: float = 1.0,
        speed: float = 1.0,
        color: Optional[ColorLike] = None,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        kwargs.pop("style", None)
        _reject_positional_fx(self, args)
        self.points = 5 if int(points) >= 5 else 4
        self.amount = float(amount)
        self.speed = float(speed)
        self._rgb = resolve_rgb(color, default=(1.0, 0.95, 0.75))
        self._seed = _frac_hash(id(self) % 10000, 0.62) * 6.28
        self._init_point_domain(center=center, radius=radius, soft_edge=soft_edge, **kwargs)
        self._path = skia.Path()

    @property
    def color(self):
        """Star color (any color form). ``None`` resets to the default. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = resolve_rgb(value, default=(1.0, 0.95, 0.75))

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 40.0)) * 2.35
        return (cx - r, cy - r, cx + r, cy + r)

    def _tick(self, dt: float, t: float) -> None:
        pass

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 40.0))
        n = self.points
        t = _now() * self.speed + self._seed
        pulse = 0.92 + 0.08 * math.sin(t * 3.1)
        rot = t * 0.12
        cr, cg, cb = self.color[:3]
        s = max(0.35, self.amount) * pulse

        amb_r = r * 1.12 * (0.95 + 0.05 * math.sin(t * 2.0))
        _draw_soft(skia_canvas, cx, cy, amb_r, cr, cg, cb, 0.28 * s)
        hub_r = r * 0.88 * (0.96 + 0.04 * math.sin(t * 2.8))
        _draw_soft(skia_canvas, cx, cy, hub_r, 1.0, 0.98, 0.88, 0.85 * s)

        ray_count = n * 2
        if fidelity_is_survival():
            ray_count = n
            spines = False
        elif fidelity_is_lite():
            ray_count = max(n, ray_count // 2)
            spines = False
        else:
            spines = True

        ray_len = r * (1.75 + 0.1 * math.sin(t * 2.2))
        for i in range(ray_count):
            ang = rot - math.pi * 0.5 + i * (math.pi / max(n, 1))
            is_tip = (i % 2 == 0)
            length = ray_len * (1.0 if is_tip else 0.58)
            half_w = r * 0.07 * (1.0 if is_tip else 0.55)
            half_w *= 0.9 + 0.1 * math.sin(t * 4.0 + i)
            dx, dy = math.cos(ang), math.sin(ang)
            px, py = -dy, dx
            near = r * 0.06
            base_x = cx + dx * near
            base_y = cy + dy * near
            tip_x = cx + dx * length
            tip_y = cy + dy * length
            path = self._path
            path.rewind()
            path.moveTo(base_x + px * half_w, base_y + py * half_w)
            path.lineTo(tip_x, tip_y)
            path.lineTo(base_x - px * half_w, base_y - py * half_w)
            path.close()
            ra = 0.4 * s * (1.0 if is_tip else 0.55)
            # solid-ish triangle with soft alpha (no per-ray linear gradient at lite)
            if fidelity_is_lite():
                _set_plus_color(_PAINT_PLUS, 1.0, 1.0, 0.95, ra * 0.45)
                skia_canvas.drawPath(path, _PAINT_PLUS)
            else:
                gp = _PAINT_GRAD
                gp.setStyle(skia.Paint.kFill_Style)
                gp.setBlendMode(skia.BlendMode.kPlus)
                gp.setShader(
                    skia.GradientShader.MakeLinear(
                        [skia.Point(base_x, base_y), skia.Point(tip_x, tip_y)],
                        [
                            skia.Color4f(1.0, 1.0, 0.98, ra * 0.75),
                            skia.Color4f(1.0, 0.98, 0.92, ra * 0.25),
                            skia.Color4f(1.0, 1.0, 1.0, 0.0),
                        ],
                        [0.0, 0.45, 1.0],
                        skia.TileMode.kClamp,
                    )
                )
                skia_canvas.drawPath(path, gp)
            if spines:
                sp = _PAINT_GRAD_STROKE
                sp.setStrokeWidth(max(0.8, half_w * 0.12))
                sp.setShader(
                    skia.GradientShader.MakeLinear(
                        [skia.Point(base_x, base_y), skia.Point(tip_x, tip_y)],
                        [
                            skia.Color4f(1.0, 1.0, 1.0, ra * 0.85),
                            skia.Color4f(1.0, 1.0, 1.0, ra * 0.2),
                            skia.Color4f(1.0, 1.0, 1.0, 0.0),
                        ],
                        [0.0, 0.5, 1.0],
                        skia.TileMode.kClamp,
                    )
                )
                skia_canvas.drawLine(base_x, base_y, tip_x, tip_y, sp)

        outer = r * 0.9 * (0.97 + 0.03 * math.sin(t * 2.6))
        inner_k = 0.42 if n == 5 else 0.47
        star = _star_path(cx, cy, outer, outer * inner_k, n, rot)
        if fidelity_is_lite():
            _set_plus_color(_PAINT_PLUS, cr, cg, cb, 0.7 * s)
            skia_canvas.drawPath(star, _PAINT_PLUS)
        else:
            gp = _PAINT_GRAD
            gp.setStyle(skia.Paint.kFill_Style)
            gp.setBlendMode(skia.BlendMode.kPlus)
            gp.setShader(
                skia.GradientShader.MakeRadial(
                    skia.Point(cx, cy), max(outer, 1.0),
                    [
                        skia.Color4f(1.0, 1.0, 1.0, 0.85 * s),
                        skia.Color4f(cr, cg, cb, 0.75 * s),
                        skia.Color4f(cr * 0.85, cg * 0.75, cb * 0.55, 0.28 * s),
                        skia.Color4f(cr * 0.5, cg * 0.4, cb * 0.3, 0.0),
                    ],
                    [0.0, 0.35, 0.72, 1.0],
                    skia.TileMode.kClamp,
                )
            )
            skia_canvas.drawPath(star, gp)
        outline = _PAINT_STROKE
        outline.setStyle(skia.Paint.kStroke_Style)
        outline.setStrokeWidth(max(1.0, r * 0.035))
        outline.setColor4f(skia.Color4f(1.0, 1.0, 1.0, 0.45 * s))
        outline.setBlendMode(skia.BlendMode.kPlus)
        skia_canvas.drawPath(star, outline)


# ---------------------------------------------------------------------------
# Rain
# ---------------------------------------------------------------------------


class Rain(PadDomainFx):
    """Rain streaks on an axis-aligned pad. Zero-arg covers a default center pad.

    Call shapes::

        Rain(p1=(0, 0), p2=(400, 300))                # opposite corners
        Rain(center=(500, 400), width=400, height=300)
        Rain.from_rect(platform)

    Keyword-only, like ``Rect``: ``p1=`` needs ``p2=``; positional numbers and
    ``x1=`` / ``pos=`` raise with the point spellings. No ``angle``: drops fall
    straight down. Not a look, not post ``Haze``, not background ``Mist``.

    Args:
        p1: One corner (with ``p2=``: opposite corners).
        p2: The opposite corner.
        center: Or a rectangle: ``center=``, ``width=``, ``height=``.
        width: Rectangle width (default 200).
        height: Rectangle height (default 160).
        amount: Density (default 0.55).
        color: Drop color; ``None`` = light blue.
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.18

    def __init__(
        self,
        *args,
        p1=None,
        p2=None,
        center=None,
        width: float = 200.0,
        height: float = 160.0,
        amount: float = 0.55,
        color: Optional[ColorLike] = None,
        **kwargs,
    ):
        _reject_positional_fx(self, args)
        soft_edge = fixed_magnitude(kwargs.pop("soft_edge", self._soft_edge), f"{type(self).__name__} soft_edge")
        scene_kw = {k: kwargs.pop(k) for k in ("layer", "group") if k in kwargs}
        scene_kw["soft_edge"] = soft_edge
        if kwargs:
            from .validate import reject_unexpected_kwargs
            reject_unexpected_kwargs(
                "Rain",
                kwargs,
                valid=(
                    "p1", "p2", "center", "width", "height", "amount", "color",
                    "soft_edge", "layer", "group",
                ),
                hints=fx_placement_hints("Rain"),
            )
        corners = p1 is not None or p2 is not None
        if corners and (p1 is None or p2 is None):
            raise TypeError(
                "Rain corners come in pairs: p1=(x1, y1), p2=(x2, y2) "
                f"(missing {'p2' if p2 is None else 'p1'}=)"
            )
        if corners and center is not None:
            raise TypeError(
                "Rain: use corners p1=/p2= or center=/width=/height=, not both"
            )

        SpatialFx._construct(self, **scene_kw)
        self.amount = float(amount)
        self._rgb = resolve_rgb(color, default=(0.65, 0.75, 0.9))
        self._spawn_acc = 0.0
        self._seed = _frac_hash(id(self) % 10000, 9.1) * 1000.0
        self._bank = _PartBank(220, with_wt=True)
        self._len = array("f", [0.0]) * self._bank.cap  # streak length parallel
        self._tick_i = 0

        if corners:
            self.model = PadModel.CORNER_CORNER
            self._set_defining_parts("p1", "p2")
            with self._batch_update():
                _init_composite(self.p1, p1)
                _init_composite(self.p2, p2)
        else:
            if center is None:
                center = self._design_center()
            self.model = PadModel.CENTER_WH
            self._set_defining_parts("center", "width", "height")
            with self._batch_update():
                _init_composite(self.center, center)
                _init_scalar(self, "width", width)
                _init_scalar(self, "height", height)

    @property
    def color(self):
        """Drop color (any color form). ``None`` resets to the default. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = resolve_rgb(value, default=(0.65, 0.75, 0.9))

    @classmethod
    def from_rect(cls, rect, *, amount: float = 0.55, color: Optional[ColorLike] = None, **kwargs) -> "Rain":
        """A rain area that follows ``rect`` (its center, width and height, live).

        Args:
            rect: the Rect (or any shape with ``center`` / ``width`` / ``height``) to cover.
            amount: rain density (default 0.55).
            color: drop tint (default: the kind's own).
            layer, group, soft_edge: as in ``Rain(...)``.
        """
        soft_edge = kwargs.pop("soft_edge", cls._soft_edge)
        return cls(
            center=lambda: rect.center,
            width=lambda: rect.width,
            height=lambda: rect.height,
            amount=amount,
            color=color,
            soft_edge=soft_edge,
            **kwargs,
        )

    def _tick(self, dt: float, t: float) -> None:
        cx, cy, w, h = self._pad_frame()
        area = max(w * h, 1.0)
        pscale = particle_scale()
        target = self.amount * 0.00045 * area * pscale
        self._spawn_acc += target * dt
        n_spawn = int(self._spawn_acc)
        self._spawn_acc -= n_spawn
        max_parts = _max_parts(180, pscale, _tier_mul())
        b = self._bank
        b.ensure_cap(max_parts)
        if len(self._len) < b.cap:
            grown = array("f", [0.0]) * b.cap
            n_old = len(self._len)
            grown[:n_old] = self._len
            self._len = grown
        while b.n > max_parts:
            last = b.n - 1
            b.kill_swap(last)
        for _ in range(n_spawn):
            if b.n >= max_parts:
                break
            self._seed += 1.17
            sample = self._sample_pad(self._seed)
            if sample is None:
                continue
            x, y, wt = sample
            if b.try_spawn(
                x, y,
                -20.0 + 40.0 * _frac_hash(self._seed, 6.2),
                -(180.0 + 140.0 * _frac_hash(self._seed, 5.1)),
                0.45 + 0.55 * _frac_hash(self._seed, 7.3),
                1.0,
                wt=wt,
            ):
                self._len[b.n - 1] = 8.0 + 14.0 * _frac_hash(self._seed, 8.4)

        self._tick_i += 1
        check_every = 1 if not fidelity_is_lite() else 2
        do_wt = (self._tick_i % check_every) == 0
        i = 0
        while i < b.n:
            b.life[i] += dt
            if b.life[i] >= b.mlife[i]:
                last = b.n - 1
                if i < last:
                    self._len[i] = self._len[last]
                b.kill_swap(i)
                continue
            b.x[i] += b.vx[i] * dt
            b.y[i] += b.vy[i] * dt
            if do_wt:
                wt = self._pad_weight(b.x[i], b.y[i])
                if wt <= 0.02:
                    last = b.n - 1
                    if i < last:
                        self._len[i] = self._len[last]
                    b.kill_swap(i)
                    continue
                if b.wt is not None:
                    b.wt[i] = wt
            i += 1

    def draw(self, skia_canvas: skia.Canvas) -> None:
        r, g, bcol = self.color
        bank = self._bank
        p = _PAINT_STROKE
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(1.15)
        p.setBlendMode(skia.BlendMode.kSrcOver)
        for i in range(bank.n):
            u = bank.life[i] / max(bank.mlife[i], 1e-6)
            wt = bank.wt[i] if bank.wt is not None else 1.0
            a = (1.0 - u) * 0.55 * wt
            if a < 0.02:
                continue
            ln = self._len[i] if i < len(self._len) else 12.0
            spd = math.hypot(bank.vx[i], bank.vy[i]) or 1.0
            x1, y1 = bank.x[i], bank.y[i]
            x0 = x1 - (bank.vx[i] / spd) * ln
            y0 = y1 - (bank.vy[i] / spd) * ln
            p.setColor4f(skia.Color4f(r, g, bcol, a))
            skia_canvas.drawLine(x0, y0, x1, y1, p)


# ---------------------------------------------------------------------------
# Jet
# ---------------------------------------------------------------------------


class Jet(BeamDomainFx):
    """Directed jet on a beam domain. Zero-arg aims from a default origin.

    Call shapes::

        Jet(p1=nozzle, p2=exhaust, width=14)
        Jet(origin=nozzle, angle=180, length=50)
        Jet.from_line(guide, width=12)

    Keyword-only, like ``Line``: ``p1=`` needs ``p2=`` (a nozzle alone is
    ``origin=`` + ``angle=``). Not a look (Laser) and not a shape Line costume.

    Args:
        p1: Nozzle (with ``p2=``: a segment).
        p2: Tip.
        origin: Or polar: nozzle with ``angle=`` and ``length=``.
        angle: Direction in degrees.
        length: Reach (default 50).
        width: Thickness (default 14).
        amount: Intensity (1 = default).
        color: Tint (any color form; default: the kind's own).
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.25

    def __init__(
        self,
        *args,
        p1=None,
        p2=None,
        origin=None,
        angle: float = 0.0,
        length: float = 50.0,
        width: float = 14.0,
        amount: float = 1.0,
        color: Optional[ColorLike] = None,
        **kwargs,
    ):
        _reject_positional_fx(self, args)
        soft_edge = fixed_magnitude(kwargs.pop("soft_edge", self._soft_edge), f"{type(self).__name__} soft_edge")
        scene_kw = {k: kwargs.pop(k) for k in ("layer", "group") if k in kwargs}
        scene_kw["soft_edge"] = soft_edge
        if kwargs:
            from .validate import reject_unexpected_kwargs
            reject_unexpected_kwargs(
                "Jet",
                kwargs,
                valid=(
                    "p1", "p2", "origin", "angle", "length", "width",
                    "amount", "color", "soft_edge", "layer", "group",
                ),
                hints=fx_placement_hints("Jet"),
            )
        if (p1 is None) != (p2 is None):
            raise TypeError(
                "Jet endpoints come in pairs: p1=, p2= "
                f"(missing {'p2' if p2 is None else 'p1'}=); a nozzle alone is "
                "origin=, angle=, length="
            )
        if p1 is not None and origin is not None:
            raise TypeError(
                "Jet: use p1=/p2= or origin=/angle=/length=, not both"
            )
        SpatialFx._construct(self, **scene_kw)
        self.amount = float(amount)
        self._rgb = resolve_rgb(color, default=(1.0, 0.55, 0.15))
        self._spawn_acc = 0.0
        self._seed = _frac_hash(id(self) % 10000, 2.2) * 1000.0
        self._bank = _PartBank(100, with_wt=True)
        self._tick_i = 0
        self._frame_cache = None  # (x0,y0,x1,y1,len,w)

        if p1 is not None and p2 is not None:
            self.model = BeamModel.POINT_POINT
            self._set_defining_parts("p1", "p2", "width")
            with self._batch_update():
                _init_composite(self.p1, p1)
                _init_composite(self.p2, p2)
                _init_scalar(self, "width", width)
        else:
            self.model = BeamModel.ORIGIN_ANGLE_LENGTH
            self._set_defining_parts("origin", "angle", "length", "width")
            with self._batch_update():
                if origin is None:
                    self.origin._takein(self._design_center())
                else:
                    _init_composite(self.origin, origin)
                _init_scalar(self, "angle", angle)
                _init_scalar(self, "length", length)
                _init_scalar(self, "width", width)

    @property
    def color(self):
        """Jet tint (any color form). ``None`` resets to the default. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = resolve_rgb(value, default=(1.0, 0.55, 0.15))

    def _collision_specs(self) -> List[Tuple]:
        x0, y0, x1, y1, length, width = self._beam_frame()
        s = 0.85  # tip is low-alpha; keep the nozzle, shorten along the beam
        x1 = x0 + (x1 - x0) * s
        y1 = y0 + (y1 - y0) * s
        return [_beam_obb_spec(x0, y0, x1, y1, length * s, width)]

    @classmethod
    def from_line(cls, line, *, width: float = 14.0, amount: float = 1.0, color: Optional[ColorLike] = None, **kwargs) -> "Jet":
        """A jet along ``line`` from ``p1`` to ``p2`` (follows the line live).

        Args:
            line: the Line whose ends are the nozzle and the tip.
            width: jet width at the nozzle (default 14).
            amount: intensity (default 1).
            color: tint (default: the kind's own).
            layer, group, soft_edge: as in ``Jet(...)``.
        """
        soft_edge = fixed_magnitude(kwargs.pop("soft_edge", cls._soft_edge), f"{cls.__name__} soft_edge")
        return cls(
            p1=lambda: line.p1,
            p2=lambda: line.p2,
            width=width,
            amount=amount,
            color=color,
            soft_edge=soft_edge,
            **kwargs,
        )

    def _tick(self, dt: float, t: float) -> None:
        x0, y0, x1, y1, length, width = self._beam_frame()
        self._frame_cache = (x0, y0, x1, y1, length, width)
        if length < 1.0:
            self._bank.clear()
            return
        pscale = particle_scale()
        rate = 55.0 * self.amount * pscale
        self._spawn_acc += rate * dt
        n_spawn = int(self._spawn_acc)
        self._spawn_acc -= n_spawn
        dx, dy = (x1 - x0) / length, (y1 - y0) / length
        px, py = -dy, dx
        max_parts = _max_parts(80, pscale, _tier_mul())
        b = self._bank
        b.ensure_cap(max_parts)
        while b.n > max_parts:
            b.kill_swap(b.n - 1)
        for _ in range(n_spawn):
            if b.n >= max_parts:
                break
            self._seed += 1.09
            lat = (_frac_hash(self._seed, 1.2) - 0.5) * width
            half = width * 0.5
            wt = _soft_band(half - abs(lat), half, self.soft_edge)
            if _frac_hash(self._seed, 2.2) > max(0.2, wt):
                continue
            spd = (length * 1.8 + 40.0) * (0.7 + 0.5 * _frac_hash(self._seed, 3.1))
            b.try_spawn(
                x0 + px * lat, y0 + py * lat,
                dx * spd, dy * spd,
                0.18 + 0.28 * _frac_hash(self._seed, 4.0),
                1.5 + 3.5 * _frac_hash(self._seed, 5.0),
                wt=wt,
            )

        self._tick_i += 1
        # high + medium: per-frame beam_weight (looks like high).
        # low: former medium life falloff only.
        full_wt = not fidelity_is_survival()
        i = 0
        while i < b.n:
            b.life[i] += dt
            if b.life[i] >= b.mlife[i]:
                b.kill_swap(i)
                continue
            b.x[i] += b.vx[i] * dt
            b.y[i] += b.vy[i] * dt
            if full_wt:
                wt = self._beam_weight(b.x[i], b.y[i])
                b.wt[i] = max(wt, 0.15 * (1.0 - b.life[i] / b.mlife[i]))
            else:
                b.wt[i] = max(0.15, 1.0 - b.life[i] / b.mlife[i])
            i += 1

    def draw(self, skia_canvas: skia.Canvas) -> None:
        if self._frame_cache is None:
            frame = self._beam_frame()
        else:
            frame = self._frame_cache
        x0, y0, x1, y1, length, width = frame
        if length < 1.0:
            return
        r, g, bcol = self.color
        # high + medium share dense blob chain; low = former medium count.
        if fidelity_is_survival():
            n_blobs = max(4, int(length / max(width * 0.5, 5.0)))
        else:
            n_blobs = max(5, int(length / max(width * 0.35, 4.0)))
        for i in range(n_blobs):
            u = i / max(n_blobs - 1, 1)
            bx = x0 + (x1 - x0) * u
            by = y0 + (y1 - y0) * u
            rad = max(width * (0.55 - 0.28 * u), width * 0.18)
            a = (0.22 - 0.14 * u) * self.amount
            if a < 0.02:
                continue
            _draw_soft(skia_canvas, bx, by, rad, r, g * 0.9, bcol * 0.4, a)

        bank = self._bank
        for i in range(bank.n):
            u = bank.life[i] / max(bank.mlife[i], 1e-6)
            wt = bank.wt[i] if bank.wt is not None else 1.0
            a = (1.0 - u) * 0.75 * wt * self.amount
            if a < 0.03:
                continue
            cr = r
            cg = g * (1.0 - 0.4 * u) + 0.4 * u
            cb = bcol * (1.0 - u) + 0.1
            _set_plus_color(_PAINT_PLUS, cr, cg, cb, a)
            skia_canvas.drawCircle(
                bank.x[i], bank.y[i], bank.r0[i] * (1.0 - 0.4 * u), _PAINT_PLUS,
            )


class Orb(PointDomainFx):
    """Bright disc + corona. Default is sun-like; color / glow / phase make variants.

    ``radius`` is the felt body (collision). Glow paints outside that disc
    and does not hit. Not ``GlowSpot`` (wash, no body) and not ``Sunburst``
    (pyro). Distant sky discs belong on a parallax layer, not ``canvas.background``.

    Args:
        center: Where it is, in design units. A function follows: ``center=lambda:
            ship.center``. Default: the design center.
        radius: Body size (also collision; default 48).
        color: Tint (any color form; default: the kind's own).
        amount: Intensity (1 = default).
        glow: Corona outside the body (default 1).
        phase: Crescent (0 = full, 1 = new).
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    _reserved_fields = ("glow",)     # plain fields of ``__init__`` (RN2)

    _DEFAULT_COLOR = (1.0, 0.92, 0.65)

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.35

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 48.0,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        glow: float = 1.0,
        phase: float = 0.0,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        _reject_positional_fx(self, args)
        self.amount = float(amount)
        self.glow = float(glow)
        self.phase = float(phase)
        self._rgb = resolve_rgb(color, default=self._DEFAULT_COLOR)
        self._init_point_domain(
            center=center, radius=radius, soft_edge=soft_edge, **kwargs,
        )

    @property
    def color(self):
        """Orb color (any color form). ``None`` resets to the default. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = resolve_rgb(value, default=self._DEFAULT_COLOR)

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 48.0))
        glow = max(0.0, float(self.glow))
        pad = r * (1.0 + 1.15 * glow)
        return (cx - pad, cy - pad, cx + pad, cy + pad)

    def _collision_specs(self) -> List[Tuple]:
        cx, cy = get_xy(self.center, bare=True)
        r = max(1e-6, abs(_bare_num(self.radius, 48.0)))
        return [("circle", cx, cy, r)]

    def _tick(self, dt: float, t: float) -> None:
        pass

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 48.0))
        if r < 0.5:
            return
        amt = max(0.0, min(1.5, float(self.amount)))
        glow = max(0.0, min(2.0, float(self.glow)))
        phase = max(0.0, min(1.0, float(self.phase)))
        se = max(0.02, min(0.85, float(self.soft_edge)))
        cr, cg, cb = self._rgb
        glow_a = amt * glow * (1.0 - phase * 0.45)
        hot = (
            min(1.0, cr * 0.28 + 0.72),
            min(1.0, cg * 0.28 + 0.72),
            min(1.0, cb * 0.28 + 0.72),
        )

        if glow_a > 0.02:
            _draw_soft(
                skia_canvas, cx, cy, r * (1.15 + 0.95 * glow),
                cr, cg, cb, 0.20 * glow_a,
            )
            _draw_soft(
                skia_canvas, cx, cy,
                r * (0.82 + 0.38 * glow),
                min(1.0, cr * 1.08), min(1.0, cg * 1.08), min(1.0, cb * 1.08),
                0.36 * glow_a,
            )

        edge_stop = max(0.18, 1.0 - se)
        body = _PAINT_ORB_BODY
        body.setShader(
            skia.GradientShader.MakeRadial(
                (cx, cy), r,
                [
                    skia.Color4f(hot[0], hot[1], hot[2], 0.98 * amt),
                    skia.Color4f(cr, cg, cb, 0.96 * amt),
                    skia.Color4f(cr, cg, cb, 0.0),
                ],
                [0.0, edge_stop, 1.0],
                skia.TileMode.kClamp,
            )
        )

        if phase <= 0.01:
            skia_canvas.drawCircle(cx, cy, r, body)
        else:
            bounds = skia.Rect.MakeLTRB(cx - r - 2.0, cy - r - 2.0, cx + r + 2.0, cy + r + 2.0)
            skia_canvas.saveLayer(bounds, None)
            skia_canvas.drawCircle(cx, cy, r, body)
            cut = _PAINT_ORB_CUT
            cut.setColor4f(skia.Color4f(1.0, 1.0, 1.0, 1.0))
            ox = r * 2.0 * (1.0 - phase)
            skia_canvas.drawCircle(cx + ox, cy, r * 1.02, cut)
            skia_canvas.restore()

        core_a = 0.32 * amt * (1.0 - phase * 0.55)
        if core_a > 0.03:
            _draw_soft(skia_canvas, cx, cy, r * 0.42, hot[0], hot[1], hot[2], core_a)


class GlowSpot(PointDomainFx):
    """Soft additive radial fade around a point (solid color).

    Gradient/alpha wash from the center out to ``radius``, Plus-blended.
    ``color`` accepts the usual PaintState inputs (name string, Color, RGB).

    Args:
        center: Where it is, in design units. A function follows: ``center=lambda:
            ship.center``. Default: the design center.
        radius: Reach (default 56).
        color: Tint (any color form; default: the kind's own).
        amount: Intensity (1 = default).
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.85

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 56.0,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        _reject_positional_fx(self, args)
        self.amount = float(amount)
        self._rgb = resolve_rgb(color, default=(1.0, 0.55, 0.85))
        self._init_point_domain(center=center, radius=radius, soft_edge=soft_edge, **kwargs)

    @property
    def color(self):
        """Glow color (any color form). ``None`` resets to the default pink. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = resolve_rgb(value, default=(1.0, 0.55, 0.85))

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 56.0)) * 1.05
        return (cx - r, cy - r, cx + r, cy + r)

    def _collision_specs(self) -> List[Tuple]:
        cx, cy = get_xy(self.center, bare=True)
        r = max(1e-6, abs(_bare_num(self.radius, 56.0)) * 0.9)
        return [("circle", cx, cy, r)]

    def _tick(self, dt: float, t: float) -> None:
        pass

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 56.0))
        if r < 0.5:
            return
        a = max(0.0, min(1.35, float(self.amount)))
        cr, cg, cb = self._rgb
        _draw_soft(skia_canvas, cx, cy, r, cr, cg, cb, 0.72 * a)
        _draw_soft(
            skia_canvas, cx, cy, r * 0.38,
            min(1.0, cr * 1.12), min(1.0, cg * 1.12), min(1.0, cb * 1.12),
            0.42 * a,
        )


# ---------------------------------------------------------------------------
# Warp (placed hyperspace disc)
# ---------------------------------------------------------------------------

_WARP_DEFAULT_COLOR = (0.45, 0.55, 1.0)
_WARP_SPOKES_MIN = 3
_WARP_SPOKES_MAX = 24


class Warp(PointDomainFx):
    """Placed radial hyperspace vortex. Point domain, not a fly field.

    Zero-arg is a medium disc at canvas center. Fly-through scenery stays
    ``Tunnel`` / ``StarFly`` on ``canvas.set_fly``. Not ``Sunburst`` (pyro)
    and not background ``Stars``.

    Args:
        center: Where it is, in design units. A function follows: ``center=lambda:
            ship.center``. Default: the design center.
        radius: Body size (also collision; default 72).
        color: Ray color (default cold blue).
        color2: Background / wall; ``None`` = derived from ``color``.
        amount: Energy.
        speed: Flight through the tunnel (0 = still).
        twist: Spiral (default 0.35).
        spokes: Spiral arms, 3–24 (default 6).
        core: Core (0 = hollow).
        into: ``True`` = flies in (default); ``False`` = pulls out.
        spin: Spin, independent of speed.
        glow: Corona outside the radius (default 0.8).
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    _reserved_fields = ("glow",)     # plain fields of ``__init__`` (RN2)

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.35

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 72.0,
        color: Optional[ColorLike] = None,
        color2=None,
        amount: float = 1.0,
        speed: float = 1.0,
        twist: float = 0.35,
        spokes: int = 6,
        core: float = 1.0,
        into: bool = True,
        spin: float = 0.0,
        glow: float = 0.8,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        style = kwargs.pop("style", None)
        if style is not None and not (isinstance(style, str) and style.strip() == ""):
            raise TypeError("Warp has no style")
        _reject_positional_fx(self, args)
        self.amount = float(amount)
        self.speed = float(speed)
        self.twist = float(twist)
        self.core = float(core)
        self.spin = float(spin)
        self.glow = float(glow)
        self._rgb = resolve_rgb(color, default=_WARP_DEFAULT_COLOR)
        self._rgb2 = None if color2 is None else resolve_rgb(color2)
        self._init_point_domain(
            center=center, radius=radius, soft_edge=soft_edge, **kwargs,
        )
        self.spokes = spokes
        self.into = into

    @property
    def color(self):
        """Main swirl color (any color form). ``None`` resets to the default. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = resolve_rgb(value, default=_WARP_DEFAULT_COLOR)

    @property
    def color2(self):
        """Second swirl color, or ``None`` for a single-color warp. Writable."""
        return self._rgb2

    @color2.setter
    def color2(self, value) -> None:
        self._rgb2 = None if value is None else resolve_rgb(value)

    @property
    def spokes(self) -> int:
        """Number of spiral arms, rounded and clamped to 3 … 24. Writable."""
        return self._spokes

    @spokes.setter
    def spokes(self, value) -> None:
        from .validate import number
        n = int(round(number(value, "Warp spokes")))
        if n < _WARP_SPOKES_MIN:
            n = _WARP_SPOKES_MIN
        elif n > _WARP_SPOKES_MAX:
            n = _WARP_SPOKES_MAX
        self._spokes = n

    @property
    def into(self) -> bool:
        """``True`` (default) swirls inward, like a drain; ``False`` pushes outward."""
        return self._into

    @into.setter
    def into(self, value) -> None:
        if not isinstance(value, bool):
            raise TypeError(
                f"Warp into expected True or False, got {type(value).__name__}"
            )
        self._into = value

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 72.0))
        glow = max(0.0, float(self.glow))
        pad = r * (1.0 + 1.15 * glow)
        return (cx - pad, cy - pad, cx + pad, cy + pad)

    def _collision_specs(self) -> List[Tuple]:
        cx, cy = get_xy(self.center, bare=True)
        r = max(1e-6, abs(_bare_num(self.radius, 72.0)) * 0.9)
        return [("circle", cx, cy, r)]

    def _tick(self, dt: float, t: float) -> None:
        pass

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 72.0))
        if r < 0.5:
            return
        amt = max(0.0, min(2.0, float(self.amount)))
        glow = max(0.0, min(2.0, float(self.glow)))
        se = max(0.05, min(0.85, float(self.soft_edge)))
        cr, cg, cb = self._rgb
        glow_a = amt * glow * 0.55
        if glow_a > 0.02:
            _draw_soft(
                skia_canvas, cx, cy, r * (1.12 + 0.9 * glow),
                cr, cg, cb, 0.18 * glow_a,
            )
            _draw_soft(
                skia_canvas, cx, cy, r * (0.78 + 0.28 * glow),
                min(1.0, cr * 1.08), min(1.0, cg * 1.08), min(1.0, cb * 1.08),
                0.22 * glow_a,
            )

        has2 = self._rgb2 is not None
        deep = self._rgb2 if has2 else (cr * 0.05, cg * 0.04, cb * 0.12)
        b = warp_builder
        b.setUniform("u_center", [float(cx), float(cy)])
        b.setUniform("u_radius", float(r))
        b.setUniform("time", float(_shader_time()))
        b.setUniform("u_color", [float(cr), float(cg), float(cb)])
        b.setUniform("u_color2", [float(deep[0]), float(deep[1]), float(deep[2])])
        b.setUniform("u_has_color2", 1.0 if has2 else 0.0)
        b.setUniform("u_amount", float(amt))
        b.setUniform("u_speed", max(0.0, float(self.speed)))
        b.setUniform("u_twist", max(0.0, min(2.0, float(self.twist))))
        b.setUniform("u_spokes", float(self._spokes))
        b.setUniform("u_core", max(0.0, min(1.5, float(self.core))))
        b.setUniform("u_into", 1.0 if self._into else -1.0)
        b.setUniform("u_spin", float(self.spin))
        b.setUniform("u_soft", float(se))
        pad = r * 1.08
        paint = _PAINT_WARP
        try:
            paint.setShader(b.makeShader())
            paint.setBlendMode(skia.BlendMode.kSrcOver)
            skia_canvas.drawRect(
                skia.Rect.MakeLTRB(cx - pad, cy - pad, cx + pad, cy + pad),
                paint,
            )
        except Exception:
            _draw_soft(skia_canvas, cx, cy, r, cr, cg, cb, 0.65 * min(amt, 1.0))


# ---------------------------------------------------------------------------
# Portal (turbulent ring of light)
# ---------------------------------------------------------------------------

_PORTAL_DEFAULT_COLOR = (0.2, 0.65, 1.0)
_PORTAL_DEFAULT_COLOR2 = (0.68, 0.25, 1.0)
# Octave phase rates (rad/s at speed 1). Alternating signs swirl the filaments.
_PORTAL_RATES = (1.15, -1.6, 2.3, -3.1, 4.2)
_PORTAL_SPIN_RATE = 0.35
# Hit radius vs `radius`: a touch past the ring, so the band's outer strands count.
_PORTAL_HIT = 1.035


class Portal(PointDomainFx):
    """Ring of turbulent light. Point domain; ``radius`` is the ring.

    Zero-arg is a medium ring at canvas center. Not ``Warp`` (a filled vortex
    disc) and not a look: ``Circle.visual = ElectricField()`` outlines a shape
    you already have. ``tilt`` turns the ring away from the viewer, so it reads
    as a 3D hoop (an ellipse on screen).

    Args:
        center: Where it is, in design units. A function follows: ``center=lambda:
            ship.center``. Default: the design center.
        radius: Ring radius (also collision; default 60).
        color: Ring color (default electric blue).
        color2: Second color; strands drift between the two. ``None`` = violet
            with the default color, else a lighter tint of ``color``.
        amount: Brightness.
        speed: Animation speed (0 = frozen).
        thickness: Band thickness as a fraction of ``radius``, 0.05–1 (default 0.25).
        chaos: Turbulence, 0 = clean hoop … 2 = wild (default 1).
        tilt: Degrees the ring is turned away from the viewer: 0 = facing, 80 ≈
            edge-on.
        angle: Heading of the tilt axis, in degrees (only matters when ``tilt``
            is not 0).
        glow: Corona around the band (default 0.8).
        layer: Draw layer (default: the default world layer; ``"ui"`` is refused).
        group: Group tag or tags (``group["name"]``; also collision tags).
        soft_edge: Edge softness as a fraction of the size (each kind has its own
            default).
    """

    _reserved_fields = ("glow", "angle", "tilt")     # plain fields of ``__init__`` (RN2)

    # Default soft_edge= (help() / autocomplete read it: _publish_fx_signatures).
    _soft_edge = 0.3

    def __init__(
        self,
        *args,
        center=None,
        radius: float = 60.0,
        color: Optional[ColorLike] = None,
        color2=None,
        amount: float = 1.0,
        speed: float = 1.0,
        thickness: float = 0.25,
        chaos: float = 1.0,
        tilt: float = 0.0,
        angle: float = 0.0,
        glow: float = 0.8,
        **kwargs,
    ):
        soft_edge = kwargs.pop("soft_edge", self._soft_edge)
        style = kwargs.pop("style", None)
        if style is not None and not (isinstance(style, str) and style.strip() == ""):
            raise TypeError("Portal has no style")
        _reject_positional_fx(self, args)
        self.amount = float(amount)
        self.speed = float(speed)
        self.thickness = thickness
        self.chaos = chaos
        self.tilt = float(tilt)
        self.angle = float(angle)
        self.glow = float(glow)
        self._rgb = resolve_rgb(color, default=_PORTAL_DEFAULT_COLOR)
        self._rgb2 = None if color2 is None else resolve_rgb(color2)
        self._init_point_domain(
            center=center, radius=radius, soft_edge=soft_edge, **kwargs,
        )

    @property
    def color(self):
        """Ring color (any color form). ``None`` resets to the default. Writable."""
        return self._rgb

    @color.setter
    def color(self, value) -> None:
        self._rgb = resolve_rgb(value, default=_PORTAL_DEFAULT_COLOR)

    @property
    def color2(self):
        """Second color, or ``None`` (violet with the default color, else a lighter tint). Writable."""
        return self._rgb2

    @color2.setter
    def color2(self, value) -> None:
        self._rgb2 = None if value is None else resolve_rgb(value)

    @property
    def thickness(self) -> float:
        """Band thickness as a fraction of ``radius``, clamped to 0.05 … 1. Writable."""
        return self._thickness

    @thickness.setter
    def thickness(self, value) -> None:
        self._thickness = max(0.05, min(1.0, _portal_number(value, "thickness")))

    @property
    def chaos(self) -> float:
        """Turbulence, clamped to 0 (clean hoop) … 2 (wild). Writable."""
        return self._chaos

    @chaos.setter
    def chaos(self, value) -> None:
        self._chaos = max(0.0, min(2.0, _portal_number(value, "chaos")))

    def _reach(self) -> float:
        """Fade-out radius in ring units (band + corona)."""
        return 1.0 + self._thickness + 1.15 * max(0.0, min(2.0, float(self.glow)))

    def _domain_aabb(self) -> Tuple[float, float, float, float]:
        cx, cy = get_xy(self.center, bare=True)
        pad = abs(_bare_num(self.radius, 60.0)) * self._reach()
        return (cx - pad, cy - pad, cx + pad, cy + pad)

    def _point_frame(self) -> Tuple[float, ...]:
        """The collision key holds every input of ``_collision_specs``: a
        ``tilt`` / ``angle`` write left the old hull cached (review 2026-10-09
        W-G4)."""
        cx, cy = get_xy(self.center, bare=True)
        return (cx, cy, abs(_bare_num(self.radius, 60.0)),
                float(self.tilt), float(self.angle))

    def _collision_specs(self) -> List[Tuple]:
        cx, cy = get_xy(self.center, bare=True)
        r = max(1e-6, abs(_bare_num(self.radius, 60.0)) * _PORTAL_HIT)
        tilt = math.radians(float(self.tilt))
        if abs(tilt) < math.radians(1.0):
            return [("circle", cx, cy, r)]
        # Tilt turns the ring about the heading axis: full radius along it,
        # foreshortened across it.
        minor = max(1e-6, r * abs(math.cos(tilt)))
        return [("ellipse", cx, cy, r, minor, math.radians(float(self.angle)))]

    def _tick(self, dt: float, t: float) -> None:
        pass

    def _quality_steps(self) -> Tuple[float, float]:
        """(march steps, turbulence octaves) for the active quality."""
        if fidelity_is_survival():
            return 3.0, 3.0
        if fidelity_is_lite():
            return 4.0, 4.0
        return 6.0, 5.0

    def _bind(self, cx: float, cy: float, r: float):
        b = portal_builder
        amt = max(0.0, min(2.0, float(self.amount)))
        glow = max(0.0, min(2.0, float(self.glow)))
        se = max(0.05, min(0.85, float(self.soft_edge)))
        tilt = math.radians(max(-85.0, min(85.0, float(self.tilt))))
        head = math.radians(float(self.angle))
        cr, cg, cb = self._rgb
        inner = self._rgb2 if self._rgb2 is not None else _portal_color2(self._rgb)
        spd = float(self.speed)
        t = _shader_time()
        ph = [_wrapped_phase(rate * spd, t) for rate in _PORTAL_RATES]
        steps, octs = self._quality_steps()
        b.setUniform("u_center", [float(cx), float(cy)])
        b.setUniform("u_radius", float(r))
        b.setUniform("u_width", float(self._thickness))
        b.setUniform("u_chaos", float(self._chaos))
        b.setUniform("u_tilt", [math.cos(tilt), math.sin(tilt)])
        b.setUniform("u_heading", [math.cos(head), math.sin(head)])
        b.setUniform("u_color", [float(cr), float(cg), float(cb)])
        b.setUniform("u_color2", [float(inner[0]), float(inner[1]), float(inner[2])])
        b.setUniform("u_amount", float(amt))
        b.setUniform("u_glow", float(glow))
        b.setUniform("u_reach", float(self._reach()))
        b.setUniform("u_soft", float(se))
        b.setUniform("u_ph0", ph[:4])
        b.setUniform("u_ph1", [ph[4], _wrapped_phase(_PORTAL_SPIN_RATE * spd, t), steps, octs])
        return b

    def draw(self, skia_canvas: skia.Canvas) -> None:
        cx, cy = get_xy(self.center, bare=True)
        r = abs(_bare_num(self.radius, 60.0))
        if r < 0.5:
            return
        pad = r * self._reach()
        paint = _PAINT_LIGHT
        try:
            paint.setShader(self._bind(cx, cy, r).makeShader())
            skia_canvas.drawRect(
                skia.Rect.MakeLTRB(cx - pad, cy - pad, cx + pad, cy + pad), paint,
            )
        except Exception:
            cr, cg, cb = self._rgb
            amt = 0.6 * max(0.0, min(1.0, float(self.amount)))
            _draw_soft(skia_canvas, cx, cy, r * 1.2, cr, cg, cb, amt)


def _portal_color2(rgb) -> Tuple[float, float, float]:
    """Second color when ``color2`` is ``None``.

    The default ring drifts blue → violet. A color the author chose gets a
    lighter tint of itself — never a hue the author did not ask for.
    """
    if tuple(rgb) == _PORTAL_DEFAULT_COLOR:
        return _PORTAL_DEFAULT_COLOR2
    return tuple(c + (1.0 - c) * 0.45 for c in rgb)


def _portal_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"Portal {name} expected a number, got {type(value).__name__}"
        )
    from .validate import number
    return number(value, f"Portal {name}")


# Fire.style dispatch (after all Fire subclasses exist)
_FIRE_STYLES.update({
    "camp": Fire,
    "soft": _FireSoft,
    "plume": _LookPlume,
    "tongues": _LookTongues,
    "embers": _LookEmbers,
    "blaze": _LookBlaze,
})

# Export list for packages
__all__ = [
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


def _publish_fx_signatures() -> None:
    """``help(Sunburst)`` / autocomplete list what ``**kwargs`` really takes.

    Each kind forwards ``layer=`` / ``group=`` / ``soft_edge=`` to
    ``SpatialFx`` through ``**kwargs``, so the raw signature ended in
    ``**kwargs`` and hid them. ``Fire`` dispatches on ``style=`` to five
    classes; its published signature is the union (per-style keywords are
    ignored or refused by the style that does not take them — see the docstring).
    """
    import inspect

    base = inspect.signature(SpatialFx.__init__).parameters
    shared = [p for name, p in base.items() if name != "self"]

    def publish(cls, own):
        soft_edge = cls.__dict__.get("_soft_edge")
        params = []
        seen = set()
        for p in own:
            if p.name in ("self", "cls") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            params.append(p.replace(kind=p.KEYWORD_ONLY))
            seen.add(p.name)
        for p in shared:
            if p.name in seen:
                continue
            if p.name == "soft_edge" and soft_edge is not None:
                p = p.replace(default=soft_edge)
            params.append(p)
        cls.__signature__ = inspect.Signature(params)

    for cls in (Sunburst, Starburst, Rain, Jet, Sparks, GlowSpot, Orb, Warp, Portal):
        publish(cls, inspect.signature(cls.__init__).parameters.values())

    P = inspect.Parameter
    kw = P.KEYWORD_ONLY
    publish(Fire, [
        P("center", kw, default=None),
        P("style", kw, default="camp", annotation="FireStyle"),
        P("radius", kw, default=45.0, annotation=float),
        P("width", kw, default=None, annotation="float  # plume / tongues / embers / blaze"),
        P("length", kw, default=0.0, annotation=float),
        P("angle", kw, default=90.0, annotation=float),
        P("amount", kw, default=1.0, annotation=float),
        P("speed", kw, default=1.2, annotation=float),
        P("rate", kw, default=None, annotation="float  # plume / embers"),
        P("tongues", kw, default=5, annotation=int),
    ])


_publish_fx_signatures()
