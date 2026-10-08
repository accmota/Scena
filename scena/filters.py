"""Shape ImageFilters: per-shape ``fill_filter`` / ``line_filter`` effects."""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple, Union

import skia

from .entity import scena_kind
from .color import resolve_rgba
from .style import FilterEffect, ComposeFx, TileMode, _SKIA_TILE_MAP  # noqa: F401
from .validate import coerce_enum

# Re-export base types so ``from scena.filters import FilterEffect`` works.
__all__ = [
    "FilterEffect", "ComposeFx",
    "Blur", "HostGlow", "GlowFilter", "DropShadow", "Dilate", "Erode",
    "EmissiveFilter",
    "draw_soft_glow_plate", "glow_blur_radius",
]

# Content-key intern so beginner loops rebuild identical DAGs once.
_FILTER_CACHE: Dict[tuple, FilterEffect] = {}


def _fresh_filter(cls, key: tuple):
    """New interned filter; ``_batch_key`` is this intern key (input + tile)."""
    obj = object.__new__(cls)
    obj._key = key
    return obj


def _intern_filter(key: tuple, factory):
    hit = _FILTER_CACHE.get(key)
    if hit is not None:
        return hit
    obj = factory()
    obj.__dict__["_interned"] = True  # shared: public writes refused once _ready
    _FILTER_CACHE[key] = obj
    return obj


def _nonneg(value: float, *, what: str = "value") -> float:
    from .validate import magnitude, fixed_magnitude
    return fixed_magnitude(value, what)


def _input_key(input: Optional[FilterEffect]):
    return id(input) if input is not None else None


def _skia_tile_mode(tile_mode) -> skia.TileMode:
    """Author ``TileMode`` / lowercase string → Skia constant."""
    tm = coerce_enum(tile_mode, TileMode, what="tile_mode")
    return _SKIA_TILE_MAP[tm]


def glow_blur_radius(radius: float, sigma: float, intensity: float = 1.0) -> float:
    """Effective blur length used by :class:`GlowFilter`."""
    blur = max(_nonneg(sigma) + _nonneg(radius) * 0.65, 4.0)
    inten = max(0.0, float(intensity))
    blur *= 1.0 + max(0.0, inten - 1.0) * 0.25
    return float(blur)


def draw_soft_glow_plate(
    shape,
    skia_canvas,
    *,
    color: Tuple[float, float, float, float],
    blur: float,
    intensity: float = 1.0,
    fills: bool = True,
) -> None:
    """Soft radial underlay + sharp geometry — no ImageFilter RT / saveLayer.

    Used by :meth:`GlowFilter.draw_survival` when the filter pipeline is skipped.
    Always draw via ``_geometry_draw`` (never ``shape.draw``) to avoid recursion.
    """
    r, g, b, a = color
    inten = max(0.0, float(intensity))
    under_a = min(0.32, max(0.06, 0.20 * max(0.35, inten) * max(float(a), 0.2)))
    blur = max(float(blur), 0.5)
    try:
        cx = float(getattr(shape, "x", 0.0) or 0.0)
        cy = float(getattr(shape, "y", 0.0) or 0.0)
        if hasattr(shape, "center"):
            c = shape.center
            if c is not None:
                if hasattr(c, "x"):
                    cx, cy = float(c.x), float(c.y)
                elif isinstance(c, (tuple, list)) and len(c) >= 2:
                    cx, cy = float(c[0]), float(c[1])
    except Exception:
        cx, cy = 0.0, 0.0
    rad = max(6.0, blur * 0.85)
    try:
        if hasattr(shape, "radius"):
            rad = max(rad, float(shape.radius) * 1.55 + blur * 0.35)
        elif hasattr(shape, "width") and hasattr(shape, "height"):
            hw = abs(float(shape.width)) * 0.5
            hh = abs(float(shape.height)) * 0.5
            rad = max(rad, math.hypot(hw, hh) * 1.25 + blur * 0.3)
    except Exception:
        pass
    is_line = scena_kind(shape) == "Line"
    if is_line:
        under = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            Color4f=skia.Color4f(float(r), float(g), float(b), under_a * 0.9),
            BlendMode=skia.BlendMode.kPlus,
        )
        try:
            under.setStrokeWidth(
                max(3.0, float(getattr(shape, "line_width", 2.0) or 2.0) * 2.6)
            )
        except Exception:
            under.setStrokeWidth(5.0)
        under.setStrokeCap(skia.Paint.Cap.kRound_Cap)
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=under)
    else:
        colors = [
            skia.Color4f(float(r), float(g), float(b), under_a),
            skia.Color4f(float(r), float(g), float(b), under_a * 0.40),
            skia.Color4f(float(r), float(g), float(b), 0.0),
        ]
        positions = [0.0, 0.35, 1.0]
        shader = skia.GradientShader.MakeRadial(
            center=(float(cx), float(cy)),
            radius=float(rad),
            colors=colors,
            positions=positions,
        )
        plate = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kFill_Style,
            BlendMode=skia.BlendMode.kPlus,
        )
        plate.setShader(shader)
        skia_canvas.drawCircle(float(cx), float(cy), float(rad), plate)
    if fills:
        shape._geometry_draw(skia_canvas, stroke_paint=None)
    else:
        shape._geometry_draw(skia_canvas, fill_paint=None)


class Blur(FilterEffect):
    """Gaussian blur filter. Assign to ``fill_filter`` / ``line_filter``, not ``.visual``.

    ``tile_mode`` is Scena ``TileMode`` (or ``"decal"`` / ``"clamp"`` / …).

    Args:
        sigma: Blur radius (default 4).
        sigmaX: Blur along x only; ``None`` = ``sigma``.
        sigmaY: Blur along y only; ``None`` = ``sigma``.
        tile_mode: Edge handling: ``"decal"`` (default) · ``"clamp"`` · ``"repeat"`` ·
            ``"mirror"``.
        input: Filter to feed in (chains filters); ``None`` = the shape itself.
    """

    def __new__(
        cls,
        sigma: float = 4.0,
        *,
        sigmaX: Optional[float] = None,
        sigmaY: Optional[float] = None,
        tile_mode: Union[TileMode, str] = TileMode.DECAL,
        input: Optional[FilterEffect] = None,
    ):
        sx = _nonneg(sigmaX if sigmaX is not None else sigma)
        sy = _nonneg(sigmaY if sigmaY is not None else sigma)
        skia_tm = _skia_tile_mode(tile_mode)
        key = ("blur", round(sx, 3), round(sy, 3), int(skia_tm), _input_key(input))
        return _intern_filter(key, lambda key=key: _fresh_filter(cls, key))

    def __init__(
        self,
        sigma: float = 4.0,
        *,
        sigmaX: Optional[float] = None,
        sigmaY: Optional[float] = None,
        tile_mode: Union[TileMode, str] = TileMode.DECAL,
        input: Optional[FilterEffect] = None,
    ):
        if getattr(self, "_ready", False):
            return
        sx = sigmaX if sigmaX is not None else sigma
        sy = sigmaY if sigmaY is not None else sigma
        self._sigma_x = _nonneg(sx)
        self._sigma_y = _nonneg(sy)
        self._tile_mode = _skia_tile_mode(tile_mode)
        self._input = input
        input_filter = _checked_input(input, type(self))._skia_filter if input else None
        super().__init__(skia.ImageFilters.Blur(
            sigmaX=self._sigma_x,
            sigmaY=self._sigma_y,
            tileMode=self._tile_mode,
            input=input_filter,
        ))
        self._ready = True

    @property
    def _batch_key(self):
        return self._key

    @property
    def _batch_outset(self) -> float:
        return 3.0 * max(self._sigma_x, self._sigma_y)

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        if scale >= 0.999:
            return self._filter
        inp = self._input._filter_at_scale(scale) if self._input else None
        return skia.ImageFilters.Blur(
            sigmaX=self._sigma_x * scale,
            sigmaY=self._sigma_y * scale,
            tileMode=self._tile_mode,
            input=inp,
        )


class HostGlow(FilterEffect):
    """Blur the source and merge the sharp graphic on top.

    Halo inherits the source colour, so one interned instance batches across
    a mixed-tint fleet (unlike :class:`GlowFilter`, whose colour is in the DAG).

    ``spread`` dilates the *halo* before blur (HaloSoft-style mass) while the
    merged core stays the original stroke. Default 0 = blur only.

    Args:
        sigma: Blur radius (default 3.5).
        spread: Grow the halo before blurring (default 0).
        input: Filter to feed in (chains filters); ``None`` = the shape itself.
    """

    def __new__(
        cls,
        sigma: float = 3.5,
        spread: float = 0.0,
        input: Optional[FilterEffect] = None,
    ):
        sig = max(float(sigma), 0.5)
        spr = max(float(spread), 0.0)
        key = ("source_glow", round(sig, 2), round(spr, 2), _input_key(input))
        return _intern_filter(key, lambda key=key: _fresh_filter(cls, key))

    def __init__(
        self,
        sigma: float = 3.5,
        spread: float = 0.0,
        input: Optional[FilterEffect] = None,
    ):
        if getattr(self, "_ready", False):
            return
        self._sigma = max(float(sigma), 0.5)
        self._spread = max(float(spread), 0.0)
        self._input = input
        input_filter = _checked_input(input, type(self))._skia_filter if input else None
        super().__init__(self._build(self._sigma, self._spread, input_filter))
        self._ready = True

    @staticmethod
    def _build(sigma: float, spread: float, input_filter) -> skia.ImageFilter:
        glow_in = input_filter
        if spread > 0.05:
            glow_in = skia.ImageFilters.Dilate(
                radiusX=float(spread), radiusY=float(spread), input=input_filter,
            )
        halo = skia.ImageFilters.Blur(
            float(sigma), float(sigma),
            tileMode=skia.TileMode.kDecal,
            input=glow_in,
        )
        return skia.ImageFilters.Merge([halo, input_filter])

    @property
    def _batch_key(self):
        return self._key

    @property
    def _batch_outset(self) -> float:
        return 3.0 * self._sigma + self._spread

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        if scale >= 0.999:
            return self._filter
        s = max(scale, 0.05)
        inp = self._input._filter_at_scale(s) if self._input else None
        return self._build(
            max(self._sigma * s, 0.5),
            self._spread * s,
            inp,
        )


class GlowFilter(FilterEffect):
    """Soft outer glow via ``DropShadowOnly(0,0)`` + Merge.

    Uses Skia's shadow-only path (stable across ``shape_fx_scale`` / batching)
    instead of a colourise → MatrixTransform → blur DAG, which artifacted at
    reduced quality and looked wrong on the unbatched full-quality paint path.

    ``intensity`` scales glow color alpha (and boosts blur slightly above 1.0).

    Default tint is warm yellow ``(1.0, 0.95, 0.65)``.

    Args:
        radius: Reach (default 12).
        sigma: Blur (default 10).
        color: Glow color (default warm white).
        intensity: Strength (default 1).
        input: Filter to feed in (chains filters); ``None`` = the shape itself.
    """

    def __new__(
        cls,
        radius: float = 12.0,
        sigma: float = 10.0,
        color: Tuple[float, float, float, float] = (1.0, 0.95, 0.65, 1.0),
        intensity: float = 1.0,
        input: Optional[FilterEffect] = None,
    ):
        blur = max(_nonneg(sigma) + _nonneg(radius) * 0.65, 4.0)
        inten = max(0.0, float(intensity))
        # Mild blur boost when intensity > 1
        blur *= 1.0 + max(0.0, inten - 1.0) * 0.25
        resolved = resolve_rgba(color, (1.0, 0.95, 0.65, 1.0))
        c = tuple(round(float(x), 3) for x in resolved)
        key = ("glow", round(blur, 2), c, round(inten, 3), _input_key(input))
        return _intern_filter(key, lambda key=key: _fresh_filter(cls, key))

    def __init__(
        self,
        radius: float = 12.0,
        sigma: float = 10.0,
        color: Tuple[float, float, float, float] = (1.0, 0.95, 0.65, 1.0),
        intensity: float = 1.0,
        input: Optional[FilterEffect] = None,
    ):
        if getattr(self, "_ready", False):
            return
        blur = max(_nonneg(sigma) + _nonneg(radius) * 0.65, 4.0)
        self._intensity = max(0.0, float(intensity))
        blur *= 1.0 + max(0.0, self._intensity - 1.0) * 0.25
        self._blur = blur
        base = resolve_rgba(color, (1.0, 0.95, 0.65, 1.0))
        a = min(1.0, max(0.0, base[3] * self._intensity))
        self._color = (base[0], base[1], base[2], a)
        self._input = input
        input_filter = _checked_input(input, type(self))._skia_filter if input else None
        super().__init__(self._build(blur, self._color, input_filter))
        self._ready = True

    @staticmethod
    def _build(
        blur: float,
        color: Tuple[float, float, float, float],
        input_filter,
    ) -> skia.ImageFilter:
        # Zero-offset shadow-only = halo; Merge keeps the sharp source on top.
        # ``None`` in Merge is the source graphic being filtered.
        halo = skia.ImageFilters.DropShadowOnly(
            0.0, 0.0,
            float(blur), float(blur),
            skia.Color4f(*color),
            input_filter,
        )
        return skia.ImageFilters.Merge([halo, input_filter])

    @property
    def _batch_key(self):
        return self._key

    @property
    def _batch_outset(self) -> float:
        return 3.0 * self._blur

    def _uses_filter_pipeline(self) -> bool:
        """Always use the ImageFilter RT."""
        return True

    def _draw_survival(self, shape, skia_canvas, *, fills: bool = True) -> None:
        """Soft radial underlay + sharp pass (no ImageFilter RT).

        Kept for callers that skip the filter pipeline.
        """
        draw_soft_glow_plate(
            shape,
            skia_canvas,
            color=self._color,
            blur=self._blur,
            intensity=self._intensity,
            fills=fills,
        )

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        s = float(scale)
        if s >= 0.999:
            return self._filter
        inp = self._input._filter_at_scale(s) if self._input else None
        return self._build(max(self._blur * s, 0.5), self._color, inp)


class DropShadow(FilterEffect):
    """Drop shadow filter.

    Design space is y-up, so a positive ``dy`` moves the shadow *up* (visual
    top). Zero-arg / scalar ``offset`` defaults to bottom-right ``(+d, -d)``.

    Args:
        offset: Shadow shift: a number or ``(dx, dy)`` (default ``(8, -8)``).
        dx: Shift in x; ``None`` = from ``offset``.
        dy: Shift in y (y-up); ``None`` = from ``offset``.
        sigma: Blur (default 5).
        color: Shadow color (default soft black).
        input: Filter to feed in (chains filters); ``None`` = the shape itself.
    """

    def __new__(
        cls,
        offset: Union[Tuple[float, float], float] = (8.0, -8.0),
        *,
        dx: Optional[float] = None,
        dy: Optional[float] = None,
        sigma: float = 5.0,
        color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.55),
        input: Optional[FilterEffect] = None,
    ):
        dx_v, dy_v = _drop_shadow_offset(offset, dx, dy)
        resolved = resolve_rgba(color, (0.0, 0.0, 0.0, 0.55))
        c = tuple(round(float(x), 3) for x in resolved)
        sig = _nonneg(sigma)
        key = (
            "shadow",
            round(dx_v, 2),
            round(dy_v, 2),
            round(sig, 2),
            c,
            _input_key(input),
        )
        return _intern_filter(key, lambda key=key: _fresh_filter(cls, key))

    def __init__(
        self,
        offset: Union[Tuple[float, float], float] = (8.0, -8.0),
        *,
        dx: Optional[float] = None,
        dy: Optional[float] = None,
        sigma: float = 5.0,
        color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.55),
        input: Optional[FilterEffect] = None,
    ):
        if getattr(self, "_ready", False):
            return
        self._dx, self._dy = _drop_shadow_offset(offset, dx, dy)
        self._sigma = _nonneg(sigma)
        self._color = resolve_rgba(color, (0.0, 0.0, 0.0, 0.55))
        self._input = input

        input_filter = _checked_input(input, type(self))._skia_filter if input else None
        super().__init__(skia.ImageFilters.DropShadow(
            dx=self._dx,
            dy=self._dy,
            sigmaX=self._sigma,
            sigmaY=self._sigma,
            color=skia.Color4f(*self._color),
            input=input_filter,
        ))
        self._ready = True

    @property
    def _batch_key(self):
        return self._key

    @property
    def _batch_outset(self) -> float:
        return 3.0 * self._sigma + max(abs(self._dx), abs(self._dy))

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        """Scale soft σ for low-res shape FX RTs; keep design-space offset.

        Geometry is drawn into the RT under a design→pixel CTM, so absolute
        ``dx``/``dy`` already land in the correct relative position after upscale.
        Scaling them by ``shape_fx_scale`` (as older code did) pulled the cast
        toward the body at low quality.
        """
        if scale >= 0.999:
            return self._filter
        inp = self._input._filter_at_scale(scale) if self._input else None
        s = float(scale)
        return skia.ImageFilters.DropShadow(
            dx=self._dx,
            dy=self._dy,
            sigmaX=max(self._sigma * s, 0.5),
            sigmaY=max(self._sigma * s, 0.5),
            color=skia.Color4f(*self._color),
            input=inp,
        )


def _checked_input(value, cls):
    from .validate import filter_input
    return filter_input(value, getattr(cls, "__name__", "filter"))


def _drop_shadow_offset(
    offset: Union[Tuple[float, float], float],
    dx: Optional[float],
    dy: Optional[float],
) -> Tuple[float, float]:
    from .validate import number, pair
    if isinstance(offset, (int, float)) and not isinstance(offset, bool):
        d = number(offset, "offset")
        return (
            d if dx is None else number(dx, "dx"),
            -d if dy is None else number(dy, "dy"),
        )
    ox, oy = pair(offset, "offset")
    return (
        number(dx, "dx") if dx is not None else ox,
        number(dy, "dy") if dy is not None else oy,
    )


def _resolve_xy_radius(
    radius: Union[Tuple[float, float], float],
    radiusX: Optional[float],
    radiusY: Optional[float],
) -> Tuple[float, float]:
    if radiusX is not None or radiusY is not None:
        if isinstance(radius, (int, float)):
            base = float(radius)
            return (
                _nonneg(radiusX if radiusX is not None else base),
                _nonneg(radiusY if radiusY is not None else base),
            )
        from .validate import pair
        rx, ry = pair(radius, "radius")
        return (
            _nonneg(radiusX if radiusX is not None else rx),
            _nonneg(radiusY if radiusY is not None else ry),
        )
    if isinstance(radius, (int, float)) and not isinstance(radius, bool):
        r = _nonneg(radius)
        return r, r
    from .validate import pair
    rx, ry = pair(radius, "radius")
    return _nonneg(rx), _nonneg(ry)


class Dilate(FilterEffect):
    """Morphology dilate (expands shape silhouette).

    Args:
        radius: Grow by this many design units (default 4).
        radiusX: Grow in x only; ``None`` = ``radius``.
        radiusY: Grow in y only; ``None`` = ``radius``.
        input: Filter to feed in (chains filters); ``None`` = the shape itself.
    """

    def __new__(
        cls,
        radius: Union[Tuple[float, float], float] = 4.0,
        *,
        radiusX: Optional[float] = None,
        radiusY: Optional[float] = None,
        input: Optional[FilterEffect] = None,
    ):
        rx, ry = _resolve_xy_radius(radius, radiusX, radiusY)
        key = ("dilate", round(rx, 2), round(ry, 2), _input_key(input))
        return _intern_filter(key, lambda key=key: _fresh_filter(cls, key))

    def __init__(
        self,
        radius: Union[Tuple[float, float], float] = 4.0,
        *,
        radiusX: Optional[float] = None,
        radiusY: Optional[float] = None,
        input: Optional[FilterEffect] = None,
    ):
        if getattr(self, "_ready", False):
            return
        self._rx, self._ry = _resolve_xy_radius(radius, radiusX, radiusY)
        self._input = input
        input_filter = _checked_input(input, type(self))._skia_filter if input else None
        super().__init__(skia.ImageFilters.Dilate(
            radiusX=self._rx,
            radiusY=self._ry,
            input=input_filter,
        ))
        self._ready = True

    @property
    def _batch_key(self):
        return self._key

    @property
    def _batch_outset(self) -> float:
        return max(self._rx, self._ry)

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        if scale >= 0.999:
            return self._filter
        inp = self._input._filter_at_scale(scale) if self._input else None
        return skia.ImageFilters.Dilate(
            radiusX=max(self._rx * scale, 0.5),
            radiusY=max(self._ry * scale, 0.5),
            input=inp,
        )


class Erode(FilterEffect):
    """Morphology erode (contracts shape silhouette).

    Args:
        radius: Shrink by this many design units (default 2.5).
        radiusX: Shrink in x only; ``None`` = ``radius``.
        radiusY: Shrink in y only; ``None`` = ``radius``.
        input: Filter to feed in (chains filters); ``None`` = the shape itself.
    """

    def __new__(
        cls,
        radius: Union[Tuple[float, float], float] = 2.5,
        *,
        radiusX: Optional[float] = None,
        radiusY: Optional[float] = None,
        input: Optional[FilterEffect] = None,
    ):
        rx, ry = _resolve_xy_radius(radius, radiusX, radiusY)
        key = ("erode", round(rx, 2), round(ry, 2), _input_key(input))
        return _intern_filter(key, lambda key=key: _fresh_filter(cls, key))

    def __init__(
        self,
        radius: Union[Tuple[float, float], float] = 2.5,
        *,
        radiusX: Optional[float] = None,
        radiusY: Optional[float] = None,
        input: Optional[FilterEffect] = None,
    ):
        if getattr(self, "_ready", False):
            return
        self._rx, self._ry = _resolve_xy_radius(radius, radiusX, radiusY)
        self._input = input
        input_filter = _checked_input(input, type(self))._skia_filter if input else None
        super().__init__(skia.ImageFilters.Erode(
            radiusX=self._rx,
            radiusY=self._ry,
            input=input_filter,
        ))
        self._ready = True

    @property
    def _batch_key(self):
        return self._key

    @property
    def _batch_outset(self) -> float:
        return 0.0

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        if scale >= 0.999:
            return self._filter
        inp = self._input._filter_at_scale(scale) if self._input else None
        return skia.ImageFilters.Erode(
            radiusX=max(self._rx * scale, 0.5),
            radiusY=max(self._ry * scale, 0.5),
            input=inp,
        )


_BRIGHT_PASS_MATRIX = [
    # Soft luminance gate: lift brights, crush shadows for the bloom plate.
    2.0, 0, 0, 0, -0.55,
    0, 2.0, 0, 0, -0.55,
    0, 0, 2.0, 0, -0.55,
    0, 0, 0, 1, 0,
]


class EmissiveFilter(FilterEffect):
    """Bright-extract + blur merged under the sharp source (sprite bloom).

    Args:
        intensity: Strength (default 1.35).
        sigma: Blur (default 10).
        input: Filter to feed in (chains filters); ``None`` = the shape itself.
    """

    def __new__(
        cls,
        intensity: float = 1.35,
        sigma: float = 10.0,
        input: Optional[FilterEffect] = None,
    ):
        inten = max(0.0, float(intensity))
        sig = max(0.5, float(sigma))
        key = ("emissive", round(inten, 2), round(sig, 2), _input_key(input))
        return _intern_filter(key, lambda key=key: _fresh_filter(cls, key))

    def __init__(
        self,
        intensity: float = 1.35,
        sigma: float = 10.0,
        input: Optional[FilterEffect] = None,
    ):
        if getattr(self, "_ready", False):
            return
        self._intensity = max(0.0, float(intensity))
        self._sigma = max(0.5, float(sigma))
        self._input = input
        input_filter = _checked_input(input, type(self))._skia_filter if input else None
        super().__init__(self._build(self._intensity, self._sigma, input_filter))
        self._ready = True

    @staticmethod
    def _build(intensity: float, sigma: float, input_filter) -> skia.ImageFilter:
        bright = skia.ImageFilters.ColorFilter(
            skia.ColorFilters.Matrix(_BRIGHT_PASS_MATRIX), input_filter,
        )
        blurred = skia.ImageFilters.Blur(
            float(sigma), float(sigma), skia.TileMode.kDecal, bright,
        )
        # Always boost bloom plate (intensity 1.0 still reads as a real glow).
        s = max(0.0, float(intensity)) * 1.35
        if abs(s - 1.0) > 1e-3:
            m = [s, 0, 0, 0, 0, 0, s, 0, 0, 0, 0, 0, s, 0, 0, 0, 0, 0, 1, 0]
            blurred = skia.ImageFilters.ColorFilter(
                skia.ColorFilters.Matrix(m), blurred,
            )
        # Halo first, sharp source on top (same Merge order as GlowFilter).
        return skia.ImageFilters.Merge([blurred, input_filter])

    @property
    def _batch_key(self):
        return self._key

    @property
    def _batch_outset(self) -> float:
        return self._sigma * 3.5

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        if scale >= 0.999:
            return self._filter
        inp = self._input._filter_at_scale(scale) if self._input else None
        sig = max(self._sigma * scale, 0.5)
        return self._build(self._intensity, sig, inp)
