"""
Shape visuals: author-facing appearance recipes.

* **CompiledVisual** — writes PaintState channels once (``apply``); single ``_geometry_draw``.
  Eligible for filter batching. Animated materials use ``ProceduralFill._tick`` each frame.
* Multipass costumes live in :mod:`scena.recipes` as ``Recipe`` (``_is_multipass=True``).

Assign with ``shape.visual = Neon()`` or ``shape.visual = Gradient("sunset")``.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Literal, Optional, Tuple, Union

from ._pkg import is_framework_module
from .closed import seal_after_init
from .entity import scena_kind
from ._defaults import Unset
from .color import Color, ColorLike
from .filters import GlowFilter, DropShadow, HostGlow, Blur, glow_blur_radius
from .style import _interned_setattr, is_stroke_type
from .validate import expect_choice, magnitude, fixed_magnitude
from .validate import formula_knobs as _formula_knobs_of


HaloStyle = Literal["hollow", "fill", "soft", "line", "pulse"]
HALO_STYLES = ("hollow", "fill", "soft", "line", "pulse")


def _host_stroke_knobs(shape) -> dict:
    """Cap (always) and join (stroke types only) from the host for rim paints."""
    cap = getattr(shape, "line_cap", "round") or "round"
    if is_stroke_type(shape):
        join = getattr(shape, "line_join", "round") or "round"
        return {"cap": cap, "join": join}
    return {"cap": cap}


def _frac(x: float) -> float:
    return float(x) - math.floor(float(x))


def _clock() -> float:
    try:
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        return float(getattr(fw.clock, "time", 0.0) or 0.0)
    except Exception:
        import time
        return time.perf_counter()


def _halo_repr(look) -> str:
    amt = getattr(look, "amount", 1.0)
    return f"Halo(amount={amt})  # styles: {', '.join(HALO_STYLES)}"


def _normalize_halo_style(style) -> str:
    return expect_choice(style, HALO_STYLES, what="Halo style")


_VISUAL_CACHE: Dict[tuple, "Visual"] = {}
_PAINT_UNSET = Unset("<unset>")


def _intern(key: tuple, factory):
    hit = _VISUAL_CACHE.get(key)
    if hit is not None:
        return hit
    obj = factory()
    obj.__dict__["_interned"] = True  # shared: public writes refused once _ready
    _VISUAL_CACHE[key] = obj
    return obj


def _paint_ctor_material(material, color):
    """Resolve Paint ``material`` / ``color=`` alias (not both)."""
    if material is not _PAINT_UNSET and color is not _PAINT_UNSET:
        raise TypeError("Paint: use material= or color=, not both")
    if color is not _PAINT_UNSET:
        return color
    if material is _PAINT_UNSET:
        return "steel blue"
    return material


def _as_color(color) -> Color:
    if isinstance(color, Color):
        return color if color else Color(0.5, 0.5, 0.5, 1.0)
    return Color(color)


def _expect_solid_color(color, *, what: str) -> Color:
    """Fill/Stroke take solids only — Gradient / Texture / looks raise TypeError."""
    from .style import Gradient, Texture, ProceduralFill, FilterEffect

    if isinstance(color, (Gradient, Texture, ProceduralFill)):
        raise TypeError(
            f"{what} takes a solid color only, got {type(color).__name__}. "
            f"Use Paint({type(color).__name__}(...)) or "
            f"shape.visual = {type(color).__name__}(...)."
        )
    if isinstance(color, FilterEffect):
        raise TypeError(
            f"{what} takes a solid color only, got filter {type(color).__name__}. "
            "Use fill_filter / line_filter for ImageFilters."
        )
    if isinstance(color, Visual):
        raise TypeError(
            f"{what} takes a solid color only, got look {type(color).__name__}. "
            f"Assign with shape.visual = {type(color).__name__}()."
        )
    return _as_color(color)


def _solid_rgba(material) -> Optional[Tuple[float, float, float, float]]:
    """Solid Color / rgba only — None for gradients, textures, procedural fills."""
    if material is None:
        return None
    if isinstance(material, Color):
        if not material:  # Color(none) — missing paint, not transparent black
            return None
        try:
            r, g, b, a = material.rgb
            return (float(r), float(g), float(b), float(a))
        except Exception:
            return None
    if isinstance(material, (tuple, list)) and len(material) >= 3:
        a = float(material[3]) if len(material) > 3 else 1.0
        return (float(material[0]), float(material[1]), float(material[2]), a)
    return None


def _gradient_rgba(material) -> Optional[Tuple[float, float, float, float]]:
    """First stop of a Gradient, else None."""
    try:
        from .style import Gradient
        if not isinstance(material, Gradient):
            return None
        cols = getattr(material, "_colors", None) or ()
        if not cols:
            return None
        rgb = getattr(cols[0], "rgb", None)
        if rgb is None or len(rgb) < 3:
            return None
        a = float(rgb[3]) if len(rgb) > 3 else 1.0
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]), a)
    except Exception:
        return None


def _texture_rgba(material) -> Optional[Tuple[float, float, float, float]]:
    """Proxy hue on a Texture (does not tint the bitmap)."""
    try:
        from .style import Texture
        if not isinstance(material, Texture):
            return None
        return _solid_rgba(getattr(material, "color", None))
    except Exception:
        return None


def _procedural_rgba(material) -> Optional[Tuple[float, float, float, float]]:
    """ProceduralFill ``_color`` proxy, else None."""
    pc = getattr(material, "_color", None)
    if isinstance(pc, (tuple, list)) and len(pc) >= 3:
        a = float(pc[3]) if len(pc) > 3 else 1.0
        return (float(pc[0]), float(pc[1]), float(pc[2]), a)
    return None


def _paint_rgba(material) -> Optional[Tuple[float, float, float, float]]:
    """Solid rgba, Gradient first stop, Texture proxy, or ProceduralFill tint.

    Missing paint → None; never invent black from Color(none).
    """
    return (
        _solid_rgba(material)
        or _gradient_rgba(material)
        or _texture_rgba(material)
        or _procedural_rgba(material)
    )


def _channel_attr_rgba(shape, attr: str) -> Optional[Tuple[float, float, float, float]]:
    try:
        paint = getattr(shape, f"_{attr}", None) or getattr(shape, attr, None)
    except Exception:
        paint = getattr(shape, f"_{attr}", None)
    return _paint_rgba(paint)


def sample_body_rgba(shape) -> Optional[Tuple[float, float, float, float]]:
    """Role A: fill only on area shapes; line then fill on stroke types."""
    if is_stroke_type(shape):
        return _channel_attr_rgba(shape, "line") or _channel_attr_rgba(shape, "fill")
    return _channel_attr_rgba(shape, "fill")


def sample_outline_rgba(shape) -> Optional[Tuple[float, float, float, float]]:
    """Role B: line then fill (both families)."""
    return _channel_attr_rgba(shape, "line") or _channel_attr_rgba(shape, "fill")


def _is_gradient(material) -> bool:
    try:
        from .style import Gradient
        return isinstance(material, Gradient)
    except Exception:
        return False


def _host_uses_stroke_filter(shape) -> bool:
    """True when the body is a stroke (stroke-type / unfilled) so accessories go on line_filter."""
    if is_stroke_type(shape):
        return True
    return not bool(getattr(shape, "_fill", None))


def _set_line_width(shape, width: float) -> None:
    try:
        shape.line_width = float(width)
    except Exception:
        pass


# Costume-owned outline widths (Shield / materials — not host accessories).
_OUTLINE_SHIELD = 1.5
_OUTLINE_SHIELD_HALO = 1.75  # 2.5 × 0.7 (30% thinner)
_OUTLINE_SWELL = 1.5
_OUTLINE_FIRE = 1.5


def _clamp01(value: float) -> float:
    from .validate import number
    v = number(value, "amount")
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _opt_alpha(alpha) -> Optional[float]:
    """None stays None; otherwise clamp to ``[0, 1]`` (intern-key safe)."""
    if alpha is None:
        return None
    return _clamp01(alpha)


def _opt_width(width) -> Optional[float]:
    """None stays None; a negative width raises (magnitude)."""
    if width is None:
        return None
    from .validate import magnitude, fixed_magnitude
    return fixed_magnitude(width, "width")


def _shadow_tint_rgba(
    color,
    alpha: Optional[float],
    shadow_color: Tuple[float, float, float, float],
) -> Tuple[float, float, float, float]:
    """Resolve DropShadow tint: ``color=`` wins over ``shadow_color``; optional alpha."""
    if shadow_color is None:
        raise TypeError(
            "shadow_color= expected an (r, g, b, a) tuple; omit it for the default "
            "or use color= (any Scena colour)"
        )
    if color is not None:
        c = _as_color(color)
        rgba = [float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]), float(c.rgb[3])]
    else:
        sc = shadow_color
        if isinstance(sc, (str, bytes)) or not hasattr(sc, "__len__") or len(sc) not in (3, 4):
            raise TypeError(
                f"shadow_color= expected an (r, g, b) or (r, g, b, a) tuple, got "
                f"{type(sc).__name__}; or use color= (any Scena colour)"
            )
        from .validate import number
        rgba = [
            number(sc[0], "shadow_color"), number(sc[1], "shadow_color"),
            number(sc[2], "shadow_color"),
            number(sc[3], "shadow_color") if len(sc) > 3 else 0.55,
        ]
    if alpha is not None:
        rgba[3] = _clamp01(alpha)
    else:
        rgba[3] = _clamp01(rgba[3])
    return (rgba[0], rgba[1], rgba[2], rgba[3])


def _aura_anchor(shape) -> Tuple[float, float]:
    """Scale pivot for an extra Halo rim pass."""
    # Defining pose first: ``center`` is a cold Derivate on Line (and other
    # models); waking it would push the host's motion off the A1 fast path.
    center_xy = getattr(shape, "_center_xy", None)
    if callable(center_xy):
        try:
            cx, cy = center_xy()
            return (float(cx), float(cy))
        except Exception:
            pass
    c = getattr(shape, "center", None)
    if c is not None:
        try:
            return (float(c.x), float(c.y))
        except Exception:
            pass
    p1 = getattr(shape, "p1", None)
    p2 = getattr(shape, "p2", None)
    if p1 is not None and p2 is not None:
        try:
            return (
                0.5 * (float(p1.x) + float(p2.x)),
                0.5 * (float(p1.y) + float(p2.y)),
            )
        except Exception:
            pass
    return (0.0, 0.0)


def _aura_mix_hot(rgb, hot: float) -> Tuple[float, float, float]:
    h = max(0.0, float(hot))
    return (
        rgb[0] + (1.0 - rgb[0]) * h,
        rgb[1] + (1.0 - rgb[1]) * h,
        rgb[2] + (1.0 - rgb[2]) * h,
    )


def _aura_lift_rgb(rgb, lift: float) -> Tuple[float, float, float]:
    k = max(0.0, float(lift))
    return (min(1.0, rgb[0] * k), min(1.0, rgb[1] * k), min(1.0, rgb[2] * k))


def _host_primary_rgba(shape) -> Optional[Tuple[float, float, float, float]]:
    """Host body color (Role A): fill on area shapes, line on stroke types."""
    try:
        return sample_body_rgba(shape)
    except Exception:
        return None


# Author tint stashed before compiled packages rewrite fill/line.
_HOST_TINT_STASH_ATTRS = (
    "_aura_host_tint",
    "_aura_fill_host",
    "_phantom_host",
    "_glowrim_host_tint",
    "_electric_bolt_host_line",
    "_electric_bolt_host_width",
    "_rim_host_line",
    "_rim_host_width",
    "_rim_host_fill",
    "_rim_host_blend",
    "_rim_stashed",
    "_rim_darkened",
)


def _stash_host_rgba(shape, attr: str, rgba) -> None:
    setattr(shape, attr, rgba)


def _read_host_rgba(shape, attr: str):
    return getattr(shape, attr, None)


def _clear_host_tint_stashes(shape) -> None:
    for name in _HOST_TINT_STASH_ATTRS:
        if hasattr(shape, name):
            delattr(shape, name)


def _resolve_paint_material(material) -> Any:
    """Color / Gradient / Texture / ProceduralFill / str / tuple."""
    from .style import Gradient, Texture, ProceduralFill

    if isinstance(material, (Gradient, Texture, ProceduralFill)):
        return material
    if isinstance(material, Color):
        return material
    return Color(material)


def reset_paint_package(shape, *, keep_line_width: bool = True) -> None:
    """Reset fill/line/blend/filters to module defaults; optionally keep line_width."""
    from .style import PaintState, BlendMode

    defaults = PaintState.get_defaults()
    if defaults is None:
        return
    from .style import DEFAULT_LINE_WIDTH
    thick = (
        getattr(shape, "_line_width", DEFAULT_LINE_WIDTH)
        if keep_line_width
        else defaults._line_width
    )
    shape._line_width = thick
    shape._dash = defaults._dash
    shape._line_cap = defaults._line_cap
    shape._line_join = defaults._line_join
    shape._line = defaults._line
    shape._fill = defaults._fill
    shape._blend = defaults._blend
    shape._line_filter = None
    shape._fill_filter = None
    shape._is_line_paint_dirty = True
    shape._is_fill_paint_dirty = True
    shape._cached_line_paint = None
    shape._cached_fill_paint = None
    if not getattr(shape, "_in_visual_apply", False):
        fn = getattr(shape, "_rebuild_blit_paint", None)
        if callable(fn):
            fn()


def _identity_capture_live(shape) -> None:
    """Paint-family identity: the applied package is the new author look."""
    fn = getattr(shape, "_identity_capture_live", None)
    if fn is not None:
        fn()


def _identity_patch_seed(shape, rgba, *, channel: str = "auto") -> None:
    fn = getattr(shape, "_identity_patch_seed", None)
    if fn is not None:
        fn(rgba, channel=channel)


def _guard_visual_numbers(cls) -> None:
    """Numeric knob checks on a framework look's ``__init__`` / ``__new__`` (A3)."""
    import functools
    import inspect
    from .validate import check_numeric_params

    orig = cls.__dict__["__init__"]
    if getattr(orig, "_scena_numbers_guarded", False):
        return
    try:
        sig = inspect.signature(orig)
    except (TypeError, ValueError):
        return

    @functools.wraps(orig)
    def wrapped(self, *args, **kwargs):
        # Interned looks set ``_ready`` in ``__init__``. A repeat construct
        # of the same key skips the check (once per distinct look).
        if type(self) is cls and not getattr(self, "_ready", False):
            check_numeric_params(cls.__name__, sig, args, kwargs,
                                 _formula_knobs_of(cls))
        return orig(self, *args, **kwargs)

    wrapped._scena_numbers_guarded = True
    cls.__init__ = wrapped

    # Interned looks build their intern key in ``__new__`` (``float(amount)``)
    # BEFORE ``__init__`` runs: check the knobs there too (A3).
    orig_new = cls.__dict__.get("__new__")
    if orig_new is not None and not getattr(orig_new, "_scena_numbers_guarded", False):
        raw_new = orig_new.__func__ if isinstance(orig_new, staticmethod) else orig_new
        try:
            new_sig = inspect.signature(raw_new)   # knobs live on __new__ here
        except (TypeError, ValueError):
            new_sig = sig

        @functools.wraps(raw_new)
        def new_wrapped(klass, *args, **kwargs):
            if klass is cls:
                check_numeric_params(cls.__name__, new_sig, args, kwargs,
                                     _formula_knobs_of(cls))
            return raw_new(klass, *args, **kwargs)

        new_wrapped._scena_numbers_guarded = True
        cls.__new__ = staticmethod(new_wrapped)


class Visual:
    """Base appearance. Compiled visuals set ``_is_multipass=False``; Recipes set True.

    ``_color_role``:
      ``A`` identity body, ``B`` identity outline, ``C`` pigment,
      ``D`` none/fixed art (the look paints its own colors: ``set_color``
      is kept but hidden, and warns once), ``E`` motion/overlay over the host.

    ``_allows_sprite``: when True, legal on ``Sprite.visual`` (overlay / ellipse
    costume / silhouette body). Body-replacing looks leave this False and raise
    on assignment unless opted in.

    ``_sprite_only``: when True, legal only on Sprite (pixel-body looks). Shape
    assignment raises — use Glow / Halo / Rim, or a Sprite.

    ``_sprite_takes_color``: when False, a seeded instance (``Beat("red")``)
    raises on ``Sprite.visual`` — its ``color=`` paints a Shape body and a
    Sprite keeps its pixels. The unseeded look stays legal.

    ``_replaces_sprite_body``: when True with ``_allows_sprite``, the look paints
    the silhouette (procedural / solid fill) instead of blitting the bitmap.

    ``_needs_sprite_path`` / ``_needs_sprite_sdf``: assign-time FrameFx warmup
    for Sprite. Path looks bake the silhouette contour for every sheet cell;
    SDF looks also run the EDT (Aura, and Sprite Halo / Rim / Laser bands).
    """

    _is_multipass: bool = False
    _color_role: str = "D"
    _allows_sprite: bool = False
    _sprite_only: bool = False
    _sprite_takes_color: bool = True
    _replaces_sprite_body: bool = False
    _needs_sprite_path: bool = False
    _needs_sprite_sdf: bool = False
    _overlay_glow_batch = False

    __setattr__ = _interned_setattr

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if is_framework_module(cls.__module__) and "__init__" in cls.__dict__:
            _guard_visual_numbers(cls)
        # Last (every subclass, author ones too): closed surface after init.
        seal_after_init(cls)

    @property
    def _batch_key(self) -> tuple:
        return (type(self).__name__,)

    def _unseed(self) -> Optional["Visual"]:
        """Return this look's un-seeded sibling (same non-color params), or
        None if this look has no seed / live-tracking duality. Default: not
        supported — set_color() falls back to today's re-apply behavior."""
        return None

    def _apply(self, shape) -> None:
        """Write style package (and seed multipass tints). Called on visual assignment."""
        pass

    def _identity_patch(self, shape) -> None:
        """After ``apply``, dye the author snapshot if this visual is a host seed.

        Accent tints (Glow / Shadow) and looks that do not bind ``color=``
        leave the snapshot alone. Must not copy live fill (Halo wash, FlameFill).
        """
        pass

    def _render(self, shape, skia_canvas) -> None:
        """Draw when ``_is_multipass``. Default: single geometry pass."""
        shape._geometry_draw(skia_canvas)

    def _overlay_after_filters(self, shape, skia_canvas) -> None:
        """Unfiltered pass after a batched or solo halo. Default: no-op.

        GlowRim / Halo high use this for the sharp rim (and Discrete-PE
        character) so the interned ``Blur`` can join the filter batcher.
        """
        return


class CompiledVisual(Visual):
    """Single-pass visual — only ``apply`` matters; never forces multipass solo draw."""

    _is_multipass = False


class Paint(CompiledVisual):
    """Complete shape color package. Matches ``PaintState.set_color``.

    Internal installer for ``color=`` / ``visual = Gradient(...)`` coercion.
    Zero-arg ``Paint()`` is steel-blue fill + contrast stroke.

    ``material`` / ``color=`` may be a solid color, ``Gradient``, ``Texture``,
    or ``ProceduralFill``. Do not pass a filter (use ``fill_filter``) or a
    named look (assign ``shape.visual = Neon()``).

    Args:
        material: Solid color, ``Gradient``, ``Texture`` or procedural fill. Default:
            steel blue + contrast outline.
        alpha: Opacity 0–1 applied to the material.
        color: The same as ``material``, by name.
        line: Draw the matching outline (default ``True``).
    """

    _color_role = "A"

    def __new__(
        cls,
        material: Any = _PAINT_UNSET,
        alpha: Optional[float] = None,
        *,
        color: Any = _PAINT_UNSET,
        line: bool = True,
    ):
        from .style import Gradient, Texture, ProceduralFill

        material = _paint_ctor_material(material, color)
        if isinstance(material, (Gradient, Texture, ProceduralFill)):
            mkey = (type(material).__name__, id(material))
        else:
            c = _as_color(material)
            mkey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        a = _opt_alpha(alpha)
        key = ("paint", mkey, None if a is None else round(a, 3), bool(line))

        def _build(resolved=c if not isinstance(material, (Gradient, Texture, ProceduralFill)) else None):
            obj = object.__new__(cls)
            if resolved is not None:
                obj._pending_color = resolved
            return obj

        return _intern(key, _build)

    def __init__(
        self,
        material: Any = _PAINT_UNSET,
        alpha: Optional[float] = None,
        *,
        color: Any = _PAINT_UNSET,
        line: bool = True,
    ):
        if getattr(self, "_ready", False):
            return
        pending = getattr(self, "_pending_color", None)
        if pending is not None:
            self.material = pending
            del self._pending_color
        else:
            mat = _paint_ctor_material(material, color)
            from .style import Gradient, Texture, ProceduralFill
            if not isinstance(mat, (Gradient, Texture, ProceduralFill)):
                mat = _as_color(mat)
            self.material = mat
        self.alpha = _opt_alpha(alpha)
        self.line = bool(line)
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        from .style import Gradient, Texture, ProceduralFill

        if isinstance(self.material, (Gradient, Texture, ProceduralFill)):
            mkey = (type(self.material).__name__, id(self.material))
        else:
            c = _as_color(self.material)
            mkey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        return ("paint", mkey, None if self.alpha is None else round(self.alpha, 3), self.line)

    def _apply(self, shape) -> None:
        from .style import Gradient, Texture, ProceduralFill, BlendMode

        reset_paint_package(shape, keep_line_width=True)
        mat = self.material
        if isinstance(mat, (Gradient, Texture, ProceduralFill, Color)):
            material = mat
        else:
            material = _as_color(mat)
        shape._apply_primary_paint(
            material,
            contrast_stroke=bool(self.line),
            alpha=self.alpha,
        )
        shape.blend = BlendMode.NORMAL
        shape.fill_filter = None
        shape.line_filter = None

    def _identity_patch(self, shape) -> None:
        _identity_capture_live(shape)


class Fill(CompiledVisual):
    """Fill only (no stroke). Zero-arg is steel blue.

    ``color`` must be a solid (name, RGB tuple, or ``Color``). Gradient /
    Texture / named looks raise ``TypeError`` — use ``Paint(Gradient(...))``
    or ``shape.visual = Gradient(...)``.

    Args:
        color: Solid color (default steel blue).
        alpha: Opacity 0–1.
    """

    _color_role = "A"

    def __new__(cls, color: ColorLike = "steel blue", alpha: Optional[float] = None):
        c = _expect_solid_color(color, what="Fill")
        a = _opt_alpha(alpha)
        key = ("fill", tuple(round(float(x), 3) for x in c.rgb), None if a is None else round(a, 3))
        return _intern(key, lambda: object.__new__(cls))

    def __init__(self, color: ColorLike = "steel blue", alpha: Optional[float] = None):
        if getattr(self, "_ready", False):
            return
        self.color = color
        self.alpha = _opt_alpha(alpha)
        self._ready = True

    def _apply(self, shape) -> None:
        from .style import BlendMode

        reset_paint_package(shape, keep_line_width=True)
        c = _expect_solid_color(self.color, what="Fill")
        if self.alpha is not None:
            c = c.with_alpha(self.alpha)
        shape.fill = c
        shape.line = None
        shape.blend = BlendMode.NORMAL
        shape.fill_filter = None
        shape.line_filter = None

    def _identity_patch(self, shape) -> None:
        _identity_capture_live(shape)


class Stroke(CompiledVisual):
    """Stroke only (no fill). Optional line_width override. Zero-arg is black.

    ``color`` must be a solid. Gradient / Texture / looks raise ``TypeError``.

    Args:
        color: Solid color (default black).
        width: Outline thickness; ``None`` keeps the shape's ``line_width``.
    """

    _color_role = "B"

    def __new__(cls, color: ColorLike = "black", width: Optional[float] = None):
        c = _expect_solid_color(color, what="Stroke")
        w = _opt_width(width)
        key = (
            "stroke",
            tuple(round(float(x), 3) for x in c.rgb),
            None if w is None else round(w, 2),
        )
        return _intern(key, lambda: object.__new__(cls))

    def __init__(self, color: ColorLike = "black", width: Optional[float] = None):
        if getattr(self, "_ready", False):
            return
        self.color = color
        self.width = _opt_width(width)
        self._ready = True

    def _apply(self, shape) -> None:
        from .style import BlendMode

        reset_paint_package(shape, keep_line_width=True)
        shape.fill = None
        shape.line = _as_color(self.color)
        if self.width is not None:
            shape.line_width = self.width
        shape.blend = BlendMode.NORMAL
        shape.fill_filter = None
        shape.line_filter = None

    def _identity_patch(self, shape) -> None:
        _identity_capture_live(shape)


class Glow(CompiledVisual):
    """Host paint + shared interned GlowFilter (filter-batchable).

    Zero-arg keeps the host color and adds a soft halo. ``color=`` tints
    **only** the glow pigment — never fill/line. Assign with
    ``shape.glow = Glow()`` or ``shape.glow = True``. For a raw ImageFilter
    use ``GlowFilter``.

    For fleets / projectiles prefer :class:`CheapGlow` on ``.glow``
    (filterless ADD halo, same knobs, no ImageFilter RT).

    Args:
        color: Glow color only (default: follows the object).
        alpha: Glow opacity 0–1; ``None`` = the color's own.
        radius: Reach (default 12).
        sigma: Blur (default 6).
        amount: Intensity (default 1).
    """

    _color_role = "C"
    _allows_sprite = True
    _fidelity_sensitive = True
    _is_multipass = False
    # Match :class:`~scena.filters.GlowFilter` zero-arg default tint when host is kept.
    _DEFAULT_GLOW = (1.0, 0.95, 0.65, 1.0)

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        alpha: Optional[float] = None,
        *,
        radius: float = 12.0,
        sigma: float = 6.0,
        amount: float = 1.0,
    ):
        if color is None:
            ckey = ("default",)
        else:
            c = _as_color(color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        a = _opt_alpha(alpha)
        key = (
            "glow",
            ckey,
            None if a is None else round(a, 3),
            round(fixed_magnitude(radius, "radius"), 2),
            round(fixed_magnitude(sigma, "sigma"), 2),
            round(float(amount), 2),
        )
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        alpha: Optional[float] = None,
        *,
        radius: float = 12.0,
        sigma: float = 6.0,
        amount: float = 1.0,
    ):
        if getattr(self, "_ready", False):
            return
        self.color = color
        self.alpha = _opt_alpha(alpha)
        self.radius = fixed_magnitude(radius, "radius")
        self.sigma = fixed_magnitude(sigma, "sigma")
        self.amount = float(amount)
        if color is None:
            glow_rgba = list(self._DEFAULT_GLOW)
        else:
            c = _as_color(color)
            glow_rgba = [float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]), float(c.rgb[3])]
        if self.alpha is not None:
            glow_rgba[3] = float(self.alpha)
        self._glow = GlowFilter(
            radius=self.radius,
            sigma=self.sigma,
            intensity=self.amount,
            color=tuple(glow_rgba),
        )
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        if self.color is None:
            ckey = ("default",)
        else:
            c = _as_color(self.color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        return (
            "glow",
            ckey,
            None if self.alpha is None else round(self.alpha, 3),
            round(float(self.radius), 2),
            round(float(self.sigma), 2),
            round(float(self.amount), 2),
        )

    def _apply(self, shape) -> None:
        from .style import BlendMode

        # Filter accessory only — never rewrite host fill/line/width.
        shape.fill_filter = None
        shape.line_filter = None
        # Thin glyph strokes make DropShadowOnly ImageFilters nearly invisible,
        # and paint-attached ImageFilters on the ui RT clip / are a HiDPI cliff.
        # ``Text`` draws a filterless ADD stroke halo in ``_geometry_draw``.
        if scena_kind(shape) == "Text":
            shape.blend = BlendMode.NORMAL
            return
        if _host_uses_stroke_filter(shape):
            shape.line_filter = self._glow
        else:
            shape.fill_filter = self._glow
        shape.blend = BlendMode.NORMAL


class CheapGlow(CompiledVisual):
    """Fleet glow — dilated ADD copies (same knobs as :class:`Glow`, no blur RT).

    Prefer this on bolts / stings / coins: ``shot.glow = CheapGlow(...)``.
    ``Glow`` batches a ``DropShadowOnly`` ImageFilter (saveLayer / union RT).
    CheapGlow draws a few scaled silhouette copies with falling ADD alpha —
    the usual fake bloom. No MaskFilter (CPU) and no ImageFilter RT, so sparse
    fleets stay cheaper than Glow. Caption ``CheapGlow`` is the same
    filterless glyph halo as ``Glow`` (color / alpha / amount). Shape and
    sprite CheapGlow are unchanged. Zero-arg is ``radius=8``, ``sigma=0``,
    ``amount=1``.
    """

    _color_role = "C"
    _allows_sprite = True
    _fidelity_sensitive = False
    _is_multipass = False
    _DEFAULT_GLOW = (1.0, 0.95, 0.65, 1.0)
    # Fake Gaussian: tent of dilated fills (frac of pad, alpha mul). Outer first.
    _FILL_BANDS = (
        (1.00, 0.08),
        (0.70, 0.12),
        (0.40, 0.18),
        (0.16, 0.26),
    )
    _STROKE_BANDS = (
        (1.40, 0.10),
        (0.85, 0.16),
        (0.40, 0.24),
    )
    _PAD_MIN = 3.0
    _PAD_MAX = 22.0

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        alpha: Optional[float] = None,
        *,
        radius: float = 8.0,
        sigma: float = 0.0,
        amount: float = 1.0,
    ):
        if color is None:
            ckey = ("default",)
        else:
            c = _as_color(color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        a = _opt_alpha(alpha)
        key = (
            "cheap_glow",
            ckey,
            None if a is None else round(a, 3),
            round(max(0.0, float(radius)), 2),
            round(max(0.0, float(sigma)), 2),
            round(float(amount), 2),
        )
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        alpha: Optional[float] = None,
        *,
        radius: float = 8.0,
        sigma: float = 0.0,
        amount: float = 1.0,
    ):
        if getattr(self, "_ready", False):
            return
        self.color = color
        self.alpha = _opt_alpha(alpha)
        self.radius = max(0.0, float(radius))
        self.sigma = max(0.0, float(sigma))
        self.amount = float(amount)
        if color is None:
            glow_rgba = list(self._DEFAULT_GLOW)
        else:
            c = _as_color(color)
            glow_rgba = [
                float(c.rgb[0]),
                float(c.rgb[1]),
                float(c.rgb[2]),
                float(c.rgb[3]),
            ]
        if self.alpha is not None:
            glow_rgba[3] = float(self.alpha)
        inten = max(0.0, float(self.amount))
        self._blur = glow_blur_radius(self.radius, self.sigma, inten)
        a = min(1.0, max(0.0, float(glow_rgba[3]) * inten))
        self._halo = (
            float(glow_rgba[0]), float(glow_rgba[1]), float(glow_rgba[2]), a,
        )
        self._pad = min(max(self._PAD_MIN, float(self._blur)), self._PAD_MAX)
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        if self.color is None:
            ckey = ("default",)
        else:
            c = _as_color(self.color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        return (
            "cheap_glow",
            ckey,
            None if self.alpha is None else round(self.alpha, 3),
            round(float(self.radius), 2),
            round(float(self.sigma), 2),
            round(float(self.amount), 2),
        )

    def _stroke_layers(self, host_w: float = 0.0):
        """ADD stroke bands for lines / caption glyphs (width, alpha)."""
        r, g, b, a = self._halo
        pad = float(self._pad)
        a = max(0.0, float(a))
        layers = tuple(
            (float(host_w) + pad * float(frac), min(1.0, a * float(amul)))
            for frac, amul in self._STROKE_BANDS
        )
        return (r, g, b), layers

    @property
    def _cull_outset(self) -> float:
        return float(self._pad) + 2.0

    def _cull_grow(self, shape, box):
        """``box`` under the largest fill band: the host scaled about its
        anchor (``_draw_scaled``), which reaches past a constant pad when the
        anchor is off center or the drawn cell outgrows ``width`` / ``height``."""
        if scena_kind(shape) == "Text" or _host_uses_stroke_filter(shape):
            return box
        k = 1.0 + float(self._pad) / self._host_radius(shape) * max(f for f, _a in self._FILL_BANDS)
        ax, ay = _aura_anchor(shape)
        return (min(box[0], ax + k * (box[0] - ax)), min(box[1], ay + k * (box[1] - ay)),
                max(box[2], ax + k * (box[2] - ax)), max(box[3], ay + k * (box[3] - ay)))

    def _add_paint(self):
        import skia

        paint = getattr(self, "_glow_add_paint", None)
        if paint is None:
            paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kFill_Style,
                StrokeCap=skia.Paint.Cap.kRound_Cap,
                StrokeJoin=skia.Paint.Join.kRound_Join,
                BlendMode=skia.BlendMode.kPlus,
            )
            self._glow_add_paint = paint
        return paint

    def _host_radius(self, shape) -> float:
        try:
            r = getattr(shape, "radius", None)
            if r is not None:
                return max(6.0, abs(float(r)))
        except Exception:
            pass
        # Rect / Square / Ellipse: Defining frame (Square ``width``/``height``
        # are cold Derivates — reading them wakes the host). Shapes only:
        # Sprite's frame is scaled, not ``width``/``height``.
        oriented = getattr(shape, "_oriented_frame", None)
        if callable(oriented) and getattr(shape, "_defining_part_names", None) is not None:
            try:
                _cx, _cy, w, h, _ang = oriented()
                w, h = abs(float(w)), abs(float(h))
                if w > 0.0 and h > 0.0:
                    return max(6.0, 0.5 * max(w, h))
            except Exception:
                pass
        try:
            w = abs(float(shape.width))
            h = abs(float(shape.height))
            if w > 0.0 and h > 0.0:
                return max(6.0, 0.5 * max(w, h))
        except Exception:
            pass
        return 12.0

    def _draw_scaled(self, shape, skia_canvas, paint, scale: float, *, fill: bool) -> None:
        cx, cy = _aura_anchor(shape)
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        skia_canvas.scale(scale, scale)
        skia_canvas.translate(-cx, -cy)
        if fill:
            shape._geometry_draw(skia_canvas, fill_paint=paint, stroke_paint=None)
        else:
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)
        skia_canvas.restore()

    def _apply(self, shape) -> None:
        from .style import BlendMode

        shape.fill_filter = None
        shape.line_filter = None
        shape.blend = BlendMode.NORMAL

    def _overlay_after_filters(self, shape, skia_canvas) -> None:
        """Dilated ADD copies — fake bloom, no MaskFilter / ImageFilter RT."""
        if scena_kind(shape) == "Text":
            return
        import skia

        r, g, b, a = self._halo
        a = max(0.0, float(a))
        if a < 0.02:
            return
        paint = self._add_paint()
        pad = float(self._pad)
        if _host_uses_stroke_filter(shape):
            paint.setStyle(skia.Paint.kStroke_Style)
            host_w = 2.0
            try:
                host_w = max(1.0, float(getattr(shape, "line_width", 2.0) or 2.0))
            except Exception:
                pass
            rgb, layers = self._stroke_layers(host_w)
            for width, alpha in layers:
                paint.setStrokeWidth(float(width))
                paint.setColor4f(skia.Color4f(r, g, b, float(alpha)))
                shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)
            return
        paint.setStyle(skia.Paint.kFill_Style)
        extra = pad / self._host_radius(shape)
        for frac, amul in self._FILL_BANDS:
            paint.setColor4f(skia.Color4f(r, g, b, min(1.0, a * float(amul))))
            self._draw_scaled(
                shape, skia_canvas, paint, 1.0 + extra * float(frac), fill=True,
            )


class Halo(CompiledVisual):
    """Hollow luminous shell: faint wash + tinted stroke + glow.

    Zero-arg ``Halo()`` is ``style="hollow"``. ``style`` is one of
    ``hollow`` | ``fill`` | ``soft`` | ``line`` | ``pulse`` (no aliases).
    ``hollow`` = see-through shell (faint wash + glowing stroke).
    ``pulse`` = hollow shell + animated concentric rings inside the outline.
    On ``Sprite``, hollow/fill use an SDF glow + blit + smoothed rim
    (no ImageFilter). Shape hosts keep the compiled filter package.

    Args:
        color: Shell tint (default: follows the object).
        amount: Strength.
        style: ``"hollow"`` (default) · ``"fill"`` · ``"soft"`` · ``"line"`` ·
            ``"pulse"``.
        rings: Rings in ``style="pulse"`` (default 3).
        speed: Ring rhythm (pulse only).
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True
    _needs_sprite_sdf = True  # Sprite render_sprite uses SDF glow bands
    _fidelity_sensitive = True
    _styles = HALO_STYLES
    _DEFAULT_AURA = (0.45, 0.85, 1.0, 1.0)
    _VARIANT = "aura"
    # Medium = filterless ADD glow + sharp outline (former Aura4).
    _MED_SIGMA = 2.0
    _MED_SPREAD = 1.25
    _MED_HOT = 0.54
    _MED_WIDTH = 1.4
    _MED_WASH = 0.12
    _MED_CORE_A = 1.0
    _MED_EXTRA_RIM = False
    _MED_FILTERLESS = True
    _MED_RIM_WIDTH = 1.45
    _MED_RIM_HOT = 0.38
    _MED_RIM_LIFT = 1.12
    _MED_RIM_ALPHA = 1.0
    _MED_RIM_SCALE = 1.0
    _MED_RIM_SPINE = 0.0
    _MED_GLOW_WIDTH = 3.2
    _MED_GLOW_ALPHA = 0.36
    _MED_GLOW_SCALE = 1.03
    _MED_GLOW_OUTER_WIDTH = 4.8
    _MED_GLOW_OUTER_ALPHA = 0.16
    _MED_GLOW_OUTER_SCALE = 1.08
    # High = blur-only halo + rim + inner spine.
    _HIGH_SIGMA = 3.0
    _HIGH_HOT = 0.0
    _HIGH_WASH = 0.12
    _HIGH_WIDTH = 3.2
    _HIGH_CORE_A = 0.88
    _RIM_HOT = 0.22
    _RIM_WIDTH = 1.7
    _RIM_ALPHA = 1.0
    _RIM_SCALE = 0.98
    _RIM_LIFT = 1.12
    _RIM_PASSES = 1
    _SPINE_WIDTH = 1.15
    _SPINE_HOT = 0.48
    _SPINE_LIFT = 1.18
    _SPINE_ALPHA = 1.0
    _SPINE_SCALE = 0.97

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        *,
        style: HaloStyle = "hollow",
        rings: int = 3,
        speed: float = 1.0,
    ):
        if cls is Halo:
            st = _normalize_halo_style(style)
            if st != "pulse" and (rings != 3 or speed != 1.0):
                # The rings exist only in style="pulse": elsewhere the knobs would
                # change nothing (KN4, 2026-10-12; before, hollow / fill / soft
                # took and ignored them, and line leaked Python's own error, KN3).
                raise TypeError(
                    f'Halo(style="{st}") takes no rings= / speed=: they set the '
                    f'rings of style="pulse". Write Halo(style="pulse", rings=…), '
                    f'or drop them.'
                )
            if st == "fill":
                return HaloFill(color, amount)
            if st == "soft":
                return HaloSoft(color, amount)
            if st == "line":
                from .recipes import HaloLine
                return HaloLine(color, amount)
            if st == "pulse":
                return HaloPulse(color, amount, rings=rings, speed=speed)
        if color is None:
            ckey = ("host",)
        else:
            c = _as_color(color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        key = (cls._VARIANT, ckey, round(float(amount), 2))
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        *,
        style: HaloStyle = "hollow",
        rings: int = 3,
        speed: float = 1.0,
    ):
        if getattr(self, "_ready", False):
            return
        if type(self) not in (Halo, HaloFill, HaloSoft, HaloPulse):
            type(self).__init__(self, color, amount)
            return
        self.color = color
        self.amount = float(amount)
        self._seed = None if color is None else _as_color(color)
        inten = max(0.35, float(amount))
        self._halo_med = HostGlow(
            sigma=max(0.5, self._MED_SIGMA * inten),
            spread=max(0.0, self._MED_SPREAD * inten),
        )
        self._halo_high = Blur(sigma=max(1.1, self._HIGH_SIGMA * inten))
        self._ready = True

    def _unseed(self) -> Optional["Halo"]:
        # HaloLine (Phase 2) uses ``_seed_color``, not ``_seed``. A missing
        # seed means live-tracking is already on, or this subclass is out of
        # Phase 1 scope — do not intern a sibling.
        if getattr(self, "_seed", None) is None:
            return None
        return type(self)(None, self.amount)

    @property
    def _batch_key(self) -> tuple:
        if self.color is None:
            ckey = ("host",)
        else:
            c = _as_color(self.color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        return (self._VARIANT, ckey, round(self.amount, 2))

    @property
    def _is_multipass(self) -> bool:
        from .fx_quality import fidelity_is_lite, fidelity_is_survival
        if fidelity_is_survival():
            return False
        if fidelity_is_lite():
            return bool(self._MED_EXTRA_RIM or self._MED_FILTERLESS)
        # High: batched Blur + overlay_after_filters (not solo render).
        return False

    def _is_installed_package(self, shape, live) -> bool:
        """True when fill/line already hold this visual's compiled package."""
        if _read_host_rgba(shape, "_aura_host_tint") is None:
            return False
        if is_stroke_type(shape):
            return True
        return float(live[3]) < 0.35

    def _host_tint_sample(self, shape):
        if getattr(self, "_color_role", "B") == "A":
            return sample_body_rgba(shape)
        return sample_outline_rgba(shape)

    def _remember_host_tint(self, shape) -> None:
        if self._seed is not None:
            return
        if _read_host_rgba(shape, "_aura_host_tint") is not None:
            return
        live = self._host_tint_sample(shape)
        if live is None:
            return
        _stash_host_rgba(shape, "_aura_host_tint", live)

    def _tint_rgba(self, shape) -> Tuple[float, float, float, float]:
        """Seed → stashed host → live solid / gradient → default.

        After the first apply, fill/line are the compiled package (faint wash
        or mixed core). Stash the author tint on the shape so quality
        re-apply / high rim still see the original hue and alpha.
        """
        if self._seed is not None:
            c = self._seed
            return (
                float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]),
                float(c.rgb[3]) if len(c.rgb) > 3 else 1.0,
            )
        self._remember_host_tint(shape)
        cached = _read_host_rgba(shape, "_aura_host_tint")
        if cached is not None:
            return cached
        live = self._host_tint_sample(shape)
        if live is not None:
            return (float(live[0]), float(live[1]), float(live[2]), float(live[3]))
        d = self._DEFAULT_AURA
        return (d[0], d[1], d[2], d[3])

    def _apply(self, shape) -> None:
        from .style import BlendMode
        from .fx_quality import fidelity_is_lite, fidelity_is_survival

        inten = max(0.35, float(self.amount))
        rgb = self._tint_rgba(shape)[:3]
        survival = fidelity_is_survival()
        lite = fidelity_is_lite()
        if survival:
            halo = None
            hot = 0.58
            wash_a = min(1.0, max(0.06, 0.12 * inten))
            width = 1.4
            core_a = min(1.0, 0.90 + 0.10 * inten)
        elif lite:
            halo = None if self._MED_FILTERLESS else self._halo_med
            hot = float(self._MED_HOT)
            wash_a = min(1.0, max(0.06, self._MED_WASH * inten))
            width = float(self._MED_WIDTH)
            core_a = min(1.0, float(self._MED_CORE_A))
        else:
            halo = self._halo_high
            hot = float(self._HIGH_HOT)
            wash_a = min(1.0, max(0.06, self._HIGH_WASH * inten))
            width = float(self._HIGH_WIDTH)
            core_a = min(1.0, float(self._HIGH_CORE_A))

        is_line = is_stroke_type(shape)
        core = Color(
            rgb[0] + (1.0 - rgb[0]) * hot,
            rgb[1] + (1.0 - rgb[1]) * hot,
            rgb[2] + (1.0 - rgb[2]) * hot,
            core_a,
        )
        host_line = getattr(shape, "_line", None)

        # Same stroke + halo on Line and closed shapes. Lines have no wash fill.
        # Keep a Gradient outline when the host already has one (blur follows it).
        line_paint = host_line if _is_gradient(host_line) else core
        if is_line:
            shape.fill = None
            shape.line = line_paint
        else:
            shape.fill = Color(rgb[0], rgb[1], rgb[2], wash_a)
            shape.line = line_paint
        try:
            shape.line_width = width
        except Exception:
            pass
        shape.fill_filter = None
        shape.line_filter = self._halo_filter_for_host(shape, halo)
        shape.blend = BlendMode.ADD

    def _halo_filter_for_host(self, shape, halo):
        """Sprite Halo/HaloFill draw via ``_render_sprite_body`` (no ImageFilter RT)."""
        if getattr(type(shape), "_is_sprite_body", False) and callable(
            getattr(type(self), "_render_sprite_body", None)
        ):
            return None
        return halo

    def _render_sprite_body(self, shape, skia_canvas) -> None:
        """SDF glow + blit + smoothed rim. Sprite only; Shape keeps v1."""
        if is_stroke_type(shape):
            self._render(shape, skia_canvas)
            return
        rgb = self._tint_rgba(shape)[:3]
        inten = max(0.35, float(self.amount))
        sdf = getattr(shape, "_draw_sprite_sdf_bands", None)
        if callable(sdf):
            sdf(
                skia_canvas, (*rgb, 1.0),
                glow_width=4.8 * inten, glow_alpha=0.36,
                rim_width=0.0, rim_alpha=0.0,
                core_width=0.0, core_alpha=0.0,
            )
        blit = getattr(shape, "_blit_image", None)
        paint = getattr(shape, "_blit_paint", None)
        if callable(blit) and paint is not None:
            blit(skia_canvas, paint)
        else:
            from .entity import _STYLE_PAINT
            shape._geometry_draw(skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=None)
        rim_rgb = _aura_lift_rgb(_aura_mix_hot(rgb, 0.54), 1.12)
        rim = self._rim_skia_paint(rim_rgb, 1.0, 1.4, **_host_stroke_knobs(shape))
        draw_v2 = getattr(shape, "_draw_sprite_silhouette_v2", None)
        if callable(draw_v2) and draw_v2(skia_canvas, rim):
            return
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=rim)

    def _identity_patch(self, shape) -> None:
        if self._seed is None:
            return
        c = self._seed
        rgba = (
            float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]),
            float(c.rgb[3]) if len(c.rgb) > 3 else 1.0,
        )
        _identity_patch_seed(shape, rgba, channel="auto")

    def _rim_skia_paint(
        self, rgb, alpha: float, width: float, *,
        cap: str = "round", join: str = "round",
    ):
        import skia
        from .style import BlendMode, _SKIA_BLEND_MAP, _SKIA_CAP_MAP, _SKIA_JOIN_MAP, LineCapStyle, LineJoinStyle

        paint = getattr(self, "_rim_paint", None)
        if paint is None:
            paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeCap=skia.Paint.Cap.kRound_Cap,
                StrokeJoin=skia.Paint.Join.kRound_Join,
                BlendMode=_SKIA_BLEND_MAP[BlendMode.ADD],
            )
            self._rim_paint = paint
        # Cap/join every call — cached paint retains the previous host's values.
        cap_key = (cap if type(cap) is str else str(cap)).lower()
        join_key = (join if type(join) is str else str(join)).lower()
        try:
            paint.setStrokeCap(_SKIA_CAP_MAP[LineCapStyle(cap_key)])
        except (ValueError, KeyError):
            paint.setStrokeCap(skia.Paint.Cap.kRound_Cap)
        try:
            paint.setStrokeJoin(_SKIA_JOIN_MAP[LineJoinStyle(join_key)])
        except (ValueError, KeyError):
            paint.setStrokeJoin(skia.Paint.Join.kRound_Join)
        paint.setStrokeWidth(float(width))
        paint.setColor4f(skia.Color4f(
            float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha),
        ))
        return paint

    def _stroke_at_scale(self, shape, skia_canvas, paint, scale: float) -> None:
        if abs(scale - 1.0) > 1e-3:
            cx, cy = _aura_anchor(shape)
            skia_canvas.save()
            skia_canvas.translate(cx, cy)
            skia_canvas.scale(scale, scale)
            skia_canvas.translate(-cx, -cy)
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)
            skia_canvas.restore()
        else:
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)

    def _draw_medium_rim(self, shape, skia_canvas) -> None:
        """Unfiltered outline at medium — sharpness without high's spine stack."""
        rgb = self._tint_rgba(shape)[:3]
        knobs = _host_stroke_knobs(shape)
        rim_rgb = _aura_lift_rgb(
            _aura_mix_hot(rgb, self._MED_RIM_HOT), self._MED_RIM_LIFT,
        )
        paint = self._rim_skia_paint(
            rim_rgb, self._MED_RIM_ALPHA, self._MED_RIM_WIDTH, **knobs,
        )
        saved_ff = getattr(shape, "_fill_filter", None)
        saved_lf = getattr(shape, "_line_filter", None)
        shape._fill_filter = None
        shape._line_filter = None
        shape._is_fill_paint_dirty = True
        shape._is_line_paint_dirty = True
        try:
            self._stroke_at_scale(shape, skia_canvas, paint, self._MED_RIM_SCALE)
            spine_w = float(self._MED_RIM_SPINE)
            if spine_w > 0.05:
                spine_rgb = _aura_lift_rgb(_aura_mix_hot(rgb, 0.48), 1.12)
                spine = self._rim_skia_paint(spine_rgb, 1.0, spine_w, **knobs)
                self._stroke_at_scale(
                    shape, skia_canvas, spine, min(self._MED_RIM_SCALE, 0.97),
                )
        finally:
            shape._fill_filter = saved_ff
            shape._line_filter = saved_lf
            shape._is_fill_paint_dirty = True
            shape._is_line_paint_dirty = True

    def _draw_extra_rim(self, shape, skia_canvas) -> None:
        """Sharp inner line on top of the glow — not mixed into the halo source."""
        rgb = self._tint_rgba(shape)[:3]
        knobs = _host_stroke_knobs(shape)
        rim_rgb = _aura_lift_rgb(_aura_mix_hot(rgb, self._RIM_HOT), self._RIM_LIFT)
        paint = self._rim_skia_paint(
            rim_rgb, self._RIM_ALPHA, self._RIM_WIDTH, **knobs,
        )
        saved_ff = getattr(shape, "_fill_filter", None)
        saved_lf = getattr(shape, "_line_filter", None)
        shape._fill_filter = None
        shape._line_filter = None
        shape._is_fill_paint_dirty = True
        shape._is_line_paint_dirty = True
        try:
            for _ in range(max(1, int(self._RIM_PASSES))):
                self._stroke_at_scale(shape, skia_canvas, paint, self._RIM_SCALE)
            if float(self._SPINE_WIDTH) > 0.05:
                spine_rgb = _aura_lift_rgb(
                    _aura_mix_hot(rgb, self._SPINE_HOT), self._SPINE_LIFT,
                )
                spine = self._rim_skia_paint(
                    spine_rgb, self._SPINE_ALPHA, self._SPINE_WIDTH, **knobs,
                )
                self._stroke_at_scale(shape, skia_canvas, spine, self._SPINE_SCALE)
        finally:
            shape._fill_filter = saved_ff
            shape._line_filter = saved_lf
            shape._is_fill_paint_dirty = True
            shape._is_line_paint_dirty = True

    def _draw_medium_filterless(self, shape, skia_canvas) -> None:
        """Cheap unfiltered ADD glow + sharp ADD outline (no ImageFilter RT)."""
        rgb = self._tint_rgba(shape)[:3]
        saved_ff = getattr(shape, "_fill_filter", None)
        saved_lf = getattr(shape, "_line_filter", None)
        shape._fill_filter = None
        shape._line_filter = None
        shape._is_fill_paint_dirty = True
        shape._is_line_paint_dirty = True
        try:
            is_line = is_stroke_type(shape)
            if not is_line:
                shape._geometry_draw(skia_canvas, stroke_paint=None)
            knobs = _host_stroke_knobs(shape)
            glow_rgb = _aura_mix_hot(rgb, 0.12)
            outer = self._rim_skia_paint(
                glow_rgb, float(self._MED_GLOW_OUTER_ALPHA),
                float(self._MED_GLOW_OUTER_WIDTH), **knobs,
            )
            self._stroke_at_scale(
                shape, skia_canvas, outer, float(self._MED_GLOW_OUTER_SCALE),
            )
            inner = self._rim_skia_paint(
                glow_rgb, float(self._MED_GLOW_ALPHA),
                float(self._MED_GLOW_WIDTH), **knobs,
            )
            self._stroke_at_scale(
                shape, skia_canvas, inner, float(self._MED_GLOW_SCALE),
            )
            rim_rgb = _aura_lift_rgb(
                _aura_mix_hot(rgb, self._MED_RIM_HOT), self._MED_RIM_LIFT,
            )
            rim = self._rim_skia_paint(
                rim_rgb, self._MED_RIM_ALPHA, self._MED_RIM_WIDTH, **knobs,
            )
            self._stroke_at_scale(shape, skia_canvas, rim, self._MED_RIM_SCALE)
        finally:
            shape._fill_filter = saved_ff
            shape._line_filter = saved_lf
            shape._is_fill_paint_dirty = True
            shape._is_line_paint_dirty = True

    def _render(self, shape, skia_canvas) -> None:
        from .fx_quality import fidelity_is_survival, fidelity_is_lite

        if fidelity_is_survival():
            saved_ff = getattr(shape, "_fill_filter", None)
            saved_lf = getattr(shape, "_line_filter", None)
            shape._fill_filter = None
            shape._line_filter = None
            shape._is_fill_paint_dirty = True
            shape._is_line_paint_dirty = True
            try:
                shape._geometry_draw(skia_canvas)
            finally:
                shape._fill_filter = saved_ff
                shape._line_filter = saved_lf
                shape._is_fill_paint_dirty = True
                shape._is_line_paint_dirty = True
            return
        if fidelity_is_lite() and self._MED_FILTERLESS:
            self._draw_medium_filterless(shape, skia_canvas)
            return
        shape._geometry_draw(skia_canvas)
        if fidelity_is_lite():
            self._draw_medium_rim(shape, skia_canvas)
            return
        self._draw_extra_rim(shape, skia_canvas)

    def _overlay_after_filters(self, shape, skia_canvas) -> None:
        from .fx_quality import fidelity_is_survival, fidelity_is_lite

        if fidelity_is_survival() or fidelity_is_lite():
            return
        self._draw_extra_rim(shape, skia_canvas)


class HaloPulse(Halo):
    """Hollow Halo plus animated concentric rings inside the outline.

    Same body/wash/filter package as ``Halo(style="hollow")``. Rings are a
    scaled copy of the host silhouette (via ``_stroke_at_scale``) and never
    exceed the current outline. ``rings`` / ``speed`` are this style's knobs.
    """

    _VARIANT = "aura_pulse"

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        *,
        style: HaloStyle = "pulse",
        rings: int = 3,
        speed: float = 1.0,
    ):
        if color is None:
            ckey = ("host",)
        else:
            c = _as_color(color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        key = (
            cls._VARIANT, ckey, round(float(amount), 2),
            max(1, int(rings)), round(float(speed), 2),
        )
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        *,
        style: HaloStyle = "pulse",
        rings: int = 3,
        speed: float = 1.0,
    ):
        if getattr(self, "_ready", False):
            return
        self.rings = max(1, int(rings))
        self.speed = float(speed)
        super().__init__(color, amount)

    def _unseed(self) -> Optional["Halo"]:
        if getattr(self, "_seed", None) is None:
            return None
        return type(self)(None, self.amount, rings=self.rings, speed=self.speed)

    @property
    def _batch_key(self) -> tuple:
        return super()._batch_key + (self.rings, round(self.speed, 2))

    def _pulse_ring_budget(self) -> int:
        from .fx_quality import fidelity_is_survival, fidelity_is_lite

        if fidelity_is_survival():
            return 1
        if fidelity_is_lite():
            return min(self.rings, 2)
        return self.rings

    def _draw_pulse_rings(self, shape, skia_canvas) -> None:
        n = self._pulse_ring_budget()
        if n <= 0:
            return
        t = _clock() * self.speed
        rgb = self._tint_rgba(shape)[:3]
        knobs = _host_stroke_knobs(shape)
        for i in range(n):
            phase = _frac(i / n - t)
            fade = min(phase, 1.0 - phase) * 4.0
            if fade <= 0.02:
                continue
            paint = self._rim_skia_paint(
                rgb, min(1.0, fade) * 0.8, 1.2, **knobs,
            )
            self._stroke_at_scale(shape, skia_canvas, paint, max(0.05, phase))

    def _render(self, shape, skia_canvas) -> None:
        # Lite is multipass (filterless solo) so overlay_after_filters is skipped.
        super()._render(shape, skia_canvas)
        self._draw_pulse_rings(shape, skia_canvas)

    def _overlay_after_filters(self, shape, skia_canvas) -> None:
        super()._overlay_after_filters(shape, skia_canvas)
        self._draw_pulse_rings(shape, skia_canvas)


class HaloFill(Halo):
    """Halo shell with the host fill kept opaque (not a faint wash). Role A (body)."""

    _color_role = "A"

    _VARIANT = "aura_fill"
    _STASH_ATTR = "_aura_fill_host"
    # HaloSoft: high uses this medium package instead of blur+rim.
    _HIGH_FOLLOWS_MED = False
    # Light saturation lift — Neon uses ~0.55; keep this subtler.
    _VIVID = 0.22

    def _is_installed_package(self, shape, live) -> bool:
        # Opaque fill stays — detect via stash, not wash alpha.
        return _read_host_rgba(shape, self._STASH_ATTR) is not None

    def _remember_host_tint(self, shape) -> None:
        if self._seed is not None:
            return
        if _read_host_rgba(shape, self._STASH_ATTR) is not None:
            return
        live = self._host_tint_sample(shape)
        if live is None:
            return
        if self._is_installed_package(shape, live):
            return
        fill = getattr(shape, "_fill", None) or getattr(shape, "fill", None)
        line = getattr(shape, "_line", None) or getattr(shape, "line", None)
        tint = (float(live[0]), float(live[1]), float(live[2]), float(live[3]))
        _stash_host_rgba(shape, self._STASH_ATTR, {
            "tint": tint,
            "fill": fill,
            "line": line,
        })
        # Halo rim / tint path also reads `_aura_host_tint`.
        _stash_host_rgba(shape, "_aura_host_tint", tint)

    def _tint_rgba(self, shape) -> Tuple[float, float, float, float]:
        if self._seed is not None:
            c = self._seed
            return (
                float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]),
                float(c.rgb[3]) if len(c.rgb) > 3 else 1.0,
            )
        self._remember_host_tint(shape)
        cached = _read_host_rgba(shape, self._STASH_ATTR)
        if cached is not None:
            t = cached.get("tint")
            if t is not None:
                return (float(t[0]), float(t[1]), float(t[2]), float(t[3]))
        live = self._host_tint_sample(shape)
        if live is not None:
            return (float(live[0]), float(live[1]), float(live[2]), float(live[3]))
        d = self._DEFAULT_AURA
        return (d[0], d[1], d[2], d[3])

    def _vivid_color(self, rgba) -> Color:
        c = Color(float(rgba[0]), float(rgba[1]), float(rgba[2]), float(rgba[3]))
        return c.vibrant_version(self._VIVID)

    def _apply(self, shape) -> None:
        from .style import BlendMode, Gradient, Texture, ProceduralFill
        from .fx_quality import fidelity_is_lite, fidelity_is_survival

        inten = max(0.35, float(self.amount))
        rgba = self._tint_rgba(shape)
        rgb = rgba[:3]
        survival = fidelity_is_survival()
        lite = fidelity_is_lite() or bool(self._HIGH_FOLLOWS_MED)
        if survival:
            halo = None
            hot = 0.58
            width = 1.4
            core_a = min(1.0, 0.90 + 0.10 * inten)
        elif lite:
            halo = None if self._MED_FILTERLESS else self._halo_med
            hot = float(self._MED_HOT)
            width = float(self._MED_WIDTH)
            core_a = min(1.0, float(self._MED_CORE_A))
        else:
            halo = self._halo_high
            hot = float(self._HIGH_HOT)
            width = float(self._HIGH_WIDTH)
            core_a = min(1.0, float(self._HIGH_CORE_A))

        is_line = is_stroke_type(shape)
        core_rgb = (
            rgb[0] + (1.0 - rgb[0]) * hot,
            rgb[1] + (1.0 - rgb[1]) * hot,
            rgb[2] + (1.0 - rgb[2]) * hot,
            core_a,
        )
        # Medium only: lift outline toward white when there is no extra rim
        # pass (the rim is what makes the edge read at high).
        if lite and not survival and not self._MED_EXTRA_RIM and not self._MED_FILTERLESS:
            whiten = 0.42
            core_rgb = (
                core_rgb[0] + (1.0 - core_rgb[0]) * whiten,
                core_rgb[1] + (1.0 - core_rgb[1]) * whiten,
                core_rgb[2] + (1.0 - core_rgb[2]) * whiten,
                core_rgb[3],
            )
        vivid_core = self._vivid_color(core_rgb)
        host_pack = _read_host_rgba(shape, self._STASH_ATTR)
        host_line = None
        host_fill = None
        if host_pack is not None:
            host_line = host_pack.get("line")
            host_fill = host_pack.get("fill")
        else:
            host_line = getattr(shape, "_line", None) or getattr(shape, "line", None)
            host_fill = getattr(shape, "_fill", None) or getattr(shape, "fill", None)

        # Keep a Gradient outline when the host already has one (blur follows it).
        if _is_gradient(host_line):
            line_paint = host_line
        else:
            line_paint = vivid_core

        if is_line:
            shape.fill = None
            shape.line = line_paint
        else:
            # Original fill — solid gets a light vibrant boost; else leave as-is.
            if self._seed is not None:
                shape.fill = self._vivid_color(rgba)
            elif isinstance(host_fill, (Gradient, Texture, ProceduralFill)):
                shape.fill = host_fill
            else:
                solid = _solid_rgba(host_fill)
                if solid is not None:
                    shape.fill = self._vivid_color(solid)
                elif host_fill is not None:
                    shape.fill = host_fill
                else:
                    shape.fill = self._vivid_color(rgba)
            shape.line = line_paint
        try:
            shape.line_width = width
        except Exception:
            pass
        shape.fill_filter = None
        shape.line_filter = self._halo_filter_for_host(shape, halo)
        # Opaque body must not ADD-composite (Halo wash is ~12% α). Halo /
        # rim paints still force ADD on their own passes.
        shape.blend = BlendMode.NORMAL

    def _overlay_after_filters(self, shape, skia_canvas) -> None:
        # HaloSoft keeps the medium HostGlow look at high — no Halo rim/spine.
        if getattr(self, "_HIGH_FOLLOWS_MED", False):
            return
        super()._overlay_after_filters(shape, skia_canvas)


class HaloSoft(HaloFill):
    """Filled Halo shell that keeps the medium HostGlow look at high. Role B (outline)."""

    _color_role = "B"

    _VARIANT = "phantom"
    _STASH_ATTR = "_phantom_host"
    _HIGH_FOLLOWS_MED = True
    _MED_EXTRA_RIM = False
    _MED_FILTERLESS = False
    _is_multipass = False
    _render_sprite_body = None  # keep HostGlow; do not use hollow/fill SDF path
    _needs_sprite_path = False
    _needs_sprite_sdf = False

    def _render(self, shape, skia_canvas) -> None:
        from .fx_quality import fidelity_is_survival

        if fidelity_is_survival():
            HaloFill._render(self, shape, skia_canvas)
            return
        # Medium and high: one HostGlow geometry draw (Merge is the core).
        shape._geometry_draw(skia_canvas)


class GlowRimVisual(CompiledVisual):
    """Shared GPU-blur halo + unfiltered rim/spine (Halo high package)."""

    _color_role = "B"

    _fidelity_sensitive = True
    _VARIANT = "glowrim"
    _DEFAULT_TINT = (0.45, 0.85, 1.0, 1.0)
    _STASH_ATTR = "_glowrim_host_tint"
    _HIGH_SIGMA = 3.0
    _HIGH_WIDTH = 3.2
    _HIGH_WASH = 0.12
    _HIGH_CORE_A = 0.88
    _HIGH_HOT = 0.0
    _RIM_HOT = 0.22
    _RIM_WIDTH = 1.7
    _RIM_ALPHA = 1.0
    _RIM_SCALE = 0.98
    _RIM_LIFT = 1.12
    _RIM_PASSES = 1
    _SPINE_WIDTH = 1.15
    _SPINE_HOT = 0.48
    _SPINE_LIFT = 1.18
    _SPINE_ALPHA = 1.0
    _SPINE_SCALE = 0.97
    # Policy
    _KEEP_HOST_FILL = False
    _USE_WASH = True
    _LINE_CHANNEL = False
    _BLEND_ADD = True
    # Blend for the unfiltered rim/spine overlay drawn in _draw_character /
    # _draw_extra_rim. Defaults to _BLEND_ADD's value; subclasses may split
    # this from the (filtered) halo blend — e.g. ElectricBolt keeps its Blur
    # halo additive but draws its crisp rim/spine with SrcOver so that line
    # always reads as the true hue.
    _OVERLAY_BLEND_ADD = None

    def __new__(cls, color=None, amount: float = 1.0, **_kw):
        if color is None:
            ckey = ("host",)
        else:
            c = _as_color(color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        extra = cls._intern_extra(_kw)
        key = (cls._VARIANT, ckey, round(float(amount), 2), extra)
        return _intern(key, lambda: object.__new__(cls))

    @classmethod
    def _intern_extra(cls, kw: dict) -> tuple:
        return ()

    def _init_glowrim(self, color=None, amount: float = 1.0) -> None:
        self.color = color
        self.amount = float(amount)
        self._seed = None if color is None else _as_color(color)
        inten = max(0.35, float(amount))
        self._halo_high = Blur(sigma=max(1.1, self._HIGH_SIGMA * inten))
        self._fallback = None

    def _use_fallback(self) -> bool:
        from .fx_quality import fidelity_is_lite
        return fidelity_is_lite() and getattr(self, "_fallback", None) is not None

    def _halo_rgb(self, rgb):
        """RGB written into the blur source / rim. Override to saturate without bleaching."""
        return rgb

    @property
    def _batch_key(self) -> tuple:
        if self.color is None:
            ckey = ("host",)
        else:
            c = _as_color(self.color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        return (self._VARIANT, ckey, round(self.amount, 2))

    @property
    def _is_multipass(self) -> bool:
        if self._use_fallback():
            fb = self._fallback
            mp = getattr(fb, "_is_multipass", True)
            return bool(mp() if callable(mp) else mp)
        # High GlowRim: batched Blur + overlay_after_filters.
        return False

    def _is_rewritten_package(self, shape, live) -> bool:
        if _read_host_rgba(shape, self._STASH_ATTR) is None:
            return False
        if is_stroke_type(shape):
            return True
        if self._KEEP_HOST_FILL:
            return True
        return float(live[3]) < 0.35

    def _remember_host_tint(self, shape) -> None:
        if self._seed is not None:
            return
        if _read_host_rgba(shape, self._STASH_ATTR) is not None:
            return
        live = self._live_host_rgba(shape)
        if live is None:
            return
        _stash_host_rgba(shape, self._STASH_ATTR, live)

    def _live_host_rgba(self, shape):
        if getattr(self, "_color_role", "B") == "A":
            return sample_body_rgba(shape)
        if self._LINE_CHANNEL and not is_stroke_type(shape):
            line = _channel_attr_rgba(shape, "line")
            if line is not None:
                return line
        return sample_outline_rgba(shape)

    def _tint_rgba(self, shape) -> Tuple[float, float, float, float]:
        if self._seed is not None:
            c = self._seed
            return (
                float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]),
                float(c.rgb[3]) if len(c.rgb) > 3 else 1.0,
            )
        self._remember_host_tint(shape)
        cached = _read_host_rgba(shape, self._STASH_ATTR)
        if cached is not None:
            return cached
        live = self._live_host_rgba(shape)
        if live is not None:
            return (float(live[0]), float(live[1]), float(live[2]), float(live[3]))
        d = self._DEFAULT_TINT
        return (d[0], d[1], d[2], d[3])

    def _apply(self, shape) -> None:
        from .style import BlendMode

        if self._use_fallback():
            self._fallback._apply(shape)
            return
        self._apply_high(shape, BlendMode)

    def _apply_high(self, shape, BlendMode) -> None:
        inten = max(0.35, float(self.amount))
        rgb = self._halo_rgb(self._tint_rgba(shape)[:3])
        wash_a = min(1.0, max(0.06, self._HIGH_WASH * inten))
        width = float(getattr(self, "width", self._HIGH_WIDTH) or self._HIGH_WIDTH)
        width = max(self._HIGH_WIDTH, float(width))
        core_a = min(1.0, float(self._HIGH_CORE_A))
        hot = float(self._HIGH_HOT)
        is_line = is_stroke_type(shape)
        core = Color(
            rgb[0] + (1.0 - rgb[0]) * hot,
            rgb[1] + (1.0 - rgb[1]) * hot,
            rgb[2] + (1.0 - rgb[2]) * hot,
            core_a,
        )
        if is_line:
            shape.fill = None
            shape.line = core
        elif self._KEEP_HOST_FILL:
            shape.line = core
        elif self._USE_WASH:
            shape.fill = Color(rgb[0], rgb[1], rgb[2], wash_a)
            shape.line = core
        else:
            shape.fill = None
            shape.line = core
        try:
            shape.line_width = width
        except Exception:
            pass
        shape.fill_filter = None
        shape.line_filter = self._halo_high
        shape.blend = BlendMode.ADD if self._BLEND_ADD else BlendMode.NORMAL

    def _identity_patch(self, shape) -> None:
        if getattr(self, "_seed", None) is None:
            return
        c = self._seed
        rgba = (
            float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]),
            float(c.rgb[3]) if len(c.rgb) > 3 else 1.0,
        )
        ch = "line" if getattr(self, "_LINE_CHANNEL", False) else "auto"
        _identity_patch_seed(shape, rgba, channel=ch)

    def _rim_skia_paint(
        self, rgb, alpha: float, width: float, path_effect=None, *,
        cap: str = "round", join: str = "round",
    ):
        import skia
        from .style import BlendMode, _SKIA_BLEND_MAP, _SKIA_CAP_MAP, _SKIA_JOIN_MAP, LineCapStyle, LineJoinStyle

        overlay_add = self._OVERLAY_BLEND_ADD
        if overlay_add is None:
            overlay_add = self._BLEND_ADD
        blend = BlendMode.ADD if overlay_add else BlendMode.NORMAL
        cap_key = (cap if type(cap) is str else str(cap)).lower()
        join_key = (join if type(join) is str else str(join)).lower()
        try:
            sk_cap = _SKIA_CAP_MAP[LineCapStyle(cap_key)]
        except (ValueError, KeyError):
            sk_cap = skia.Paint.Cap.kRound_Cap
        try:
            sk_join = _SKIA_JOIN_MAP[LineJoinStyle(join_key)]
        except (ValueError, KeyError):
            sk_join = skia.Paint.Join.kRound_Join
        paint = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeCap=sk_cap,
            StrokeJoin=sk_join,
            BlendMode=_SKIA_BLEND_MAP[blend],
            StrokeWidth=float(width),
        )
        paint.setColor4f(skia.Color4f(
            float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha),
        ))
        if path_effect is not None:
            paint.setPathEffect(path_effect)
        return paint

    def _stroke_at_scale(self, shape, skia_canvas, paint, scale: float) -> None:
        if abs(scale - 1.0) > 1e-3:
            cx, cy = _aura_anchor(shape)
            skia_canvas.save()
            skia_canvas.translate(cx, cy)
            skia_canvas.scale(scale, scale)
            skia_canvas.translate(-cx, -cy)
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)
            skia_canvas.restore()
        else:
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)

    def _with_filters_stripped(self, shape, fn) -> None:
        saved_ff = getattr(shape, "_fill_filter", None)
        saved_lf = getattr(shape, "_line_filter", None)
        shape._fill_filter = None
        shape._line_filter = None
        shape._is_fill_paint_dirty = True
        shape._is_line_paint_dirty = True
        try:
            fn()
        finally:
            shape._fill_filter = saved_ff
            shape._line_filter = saved_lf
            shape._is_fill_paint_dirty = True
            shape._is_line_paint_dirty = True

    def _draw_host_fill(self, shape, skia_canvas) -> None:
        if is_stroke_type(shape):
            return
        from .style import BlendMode

        saved_blend = getattr(shape, "_blend", None)
        try:
            shape._blend = BlendMode.NORMAL
            shape._is_fill_paint_dirty = True
            shape._geometry_draw(skia_canvas, stroke_paint=None)
        finally:
            if saved_blend is not None:
                shape._blend = saved_blend
            shape._is_fill_paint_dirty = True

    def _draw_character(self, shape, skia_canvas, rgb, *, glow_batched=False) -> None:
        """Optional unfiltered overlay (dash / Discrete PE) before rim."""
        return

    def _draw_extra_rim(self, shape, skia_canvas) -> None:
        rgb = self._halo_rgb(self._tint_rgba(shape)[:3])
        rim_rgb = _aura_lift_rgb(_aura_mix_hot(rgb, self._RIM_HOT), self._RIM_LIFT)
        paint = self._rim_skia_paint(rim_rgb, self._RIM_ALPHA, self._RIM_WIDTH)
        for _ in range(max(1, int(self._RIM_PASSES))):
            self._stroke_at_scale(shape, skia_canvas, paint, self._RIM_SCALE)
        if float(self._SPINE_WIDTH) > 0.05:
            spine_rgb = _aura_lift_rgb(
                _aura_mix_hot(rgb, self._SPINE_HOT), self._SPINE_LIFT,
            )
            spine = self._rim_skia_paint(spine_rgb, self._SPINE_ALPHA, self._SPINE_WIDTH)
            self._stroke_at_scale(shape, skia_canvas, spine, self._SPINE_SCALE)

    def _render(self, shape, skia_canvas) -> None:
        if self._use_fallback():
            self._fallback._render(shape, skia_canvas)
            return
        if self._KEEP_HOST_FILL:
            from .style import BlendMode

            self._with_filters_stripped(
                shape, lambda: self._draw_host_fill(shape, skia_canvas),
            )
            saved_blend = getattr(shape, "_blend", None)
            try:
                shape._blend = BlendMode.ADD if self._BLEND_ADD else BlendMode.NORMAL
                shape._is_line_paint_dirty = True
                shape._geometry_draw(skia_canvas, fill_paint=None)
            finally:
                if saved_blend is not None:
                    shape._blend = saved_blend
                shape._is_line_paint_dirty = True
        else:
            shape._geometry_draw(skia_canvas)
        rgb = self._halo_rgb(self._tint_rgba(shape)[:3])
        self._with_filters_stripped(shape, lambda: self._draw_overlays(shape, skia_canvas, rgb))

    def _draw_overlays(self, shape, skia_canvas, rgb, *, glow_batched=False) -> None:
        self._draw_character(shape, skia_canvas, rgb, glow_batched=glow_batched)
        self._draw_extra_rim(shape, skia_canvas)

    def _overlay_after_filters(self, shape, skia_canvas, *, glow_batched=False) -> None:
        if self._use_fallback():
            return
        rgb = self._halo_rgb(self._tint_rgba(shape)[:3])
        self._with_filters_stripped(
            shape,
            lambda: self._draw_overlays(
                shape, skia_canvas, rgb, glow_batched=glow_batched,
            ),
        )


class Shadow(CompiledVisual):
    """Host paint + shared interned DropShadow (filter-batchable).

    ``color=`` tints **only** the shadow pigment — never fill/line.
    Assign with ``shape.shadow = Shadow()`` or ``shape.shadow = True``.

    Args:
        color: Shadow tint (default soft black).
        alpha: Shadow opacity 0–1; ``None`` = the color's own.
        offset: A number or ``(dx, dy)`` (default 8).
        dx: Shift in x; ``None`` = from ``offset``.
        dy: Shift in y (y-up); ``None`` = from ``offset``.
        sigma: Blur (default 5).
        shadow_color: RGBA used when ``color`` is not given.
    """

    _color_role = "C"
    _allows_sprite = True
    _fidelity_sensitive = True

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        alpha: Optional[float] = None,
        *,
        offset: Union[Tuple[float, float], float] = 8.0,
        dx: Optional[float] = None,
        dy: Optional[float] = None,
        sigma: float = 5.0,
        shadow_color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.55),
    ):
        from .filters import DropShadow as _DS
        a = _opt_alpha(alpha)
        sc = _shadow_tint_rgba(color, a, shadow_color)
        ds = _DS(offset=offset, dx=dx, dy=dy, sigma=sigma, color=sc)
        key = (
            "shadow",
            tuple(round(float(x), 3) for x in sc),
            None if a is None else round(a, 3),
            ds._batch_key,
        )
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        alpha: Optional[float] = None,
        *,
        offset: Union[Tuple[float, float], float] = 8.0,
        dx: Optional[float] = None,
        dy: Optional[float] = None,
        sigma: float = 5.0,
        shadow_color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.55),
    ):
        if getattr(self, "_ready", False):
            return
        self.color = color
        self.alpha = _opt_alpha(alpha)
        self.offset = offset
        self.dx = dx
        self.dy = dy
        self.sigma = max(0.0, float(sigma))
        self.shadow_color = _shadow_tint_rgba(color, self.alpha, shadow_color)
        self._shadow = DropShadow(
            offset=offset,
            dx=dx,
            dy=dy,
            sigma=self.sigma,
            color=self.shadow_color,
        )
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        return (
            "shadow",
            tuple(round(float(x), 3) for x in self.shadow_color),
            None if self.alpha is None else round(self.alpha, 3),
            self._shadow._batch_key,
        )

    def _apply(self, shape) -> None:
        from .style import BlendMode
        from .fx_quality import fidelity_is_survival

        # Filter accessory only — never rewrite host fill/line/width.
        shape.fill_filter = None
        shape.line_filter = None
        if fidelity_is_survival():
            return
        if _host_uses_stroke_filter(shape):
            shape.line_filter = self._shadow
        else:
            shape.fill_filter = self._shadow
        shape.blend = BlendMode.NORMAL


class _OrbHaloLegacy(CompiledVisual):
    """Low / medium _OrbHalo (GlowFilter high retired)."""

    _fidelity_sensitive = True
    _DEFAULT_TINT = (0.45, 0.95, 0.35, 1.0)

    def __new__(
        cls,
        color=None,
        *,
        amount: float = 1.0,
        speed: float = 1.0,
        radius: float = 16.0,
        sigma: float = 8.0,
    ):
        if color is None:
            ckey = ("host",)
        else:
            c = _as_color(color)
            ckey = tuple(round(float(x), 3) for x in c.rgb)
        key = (
            "shield_halo_legacy",
            ckey,
            round(float(amount), 2),
            round(float(speed), 2),
            round(float(radius), 2),
            round(float(sigma), 2),
        )
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        color=None,
        *,
        amount: float = 1.0,
        speed: float = 1.0,
        radius: float = 16.0,
        sigma: float = 8.0,
    ):
        if getattr(self, "_ready", False):
            return
        self.color = color
        self._seed = None if color is None else _as_color(color)
        self.amount = float(amount)
        self.speed = float(speed)
        self.radius = float(radius)
        self.sigma = float(sigma)
        self._ready = True

    @property
    def _is_multipass(self) -> bool:
        # Always use paint package; GlowFilter is quality-gated in apply().
        return False

    @property
    def _batch_key(self) -> tuple:
        if self.color is None:
            ckey = ("host",)
        else:
            c = _as_color(self.color)
            ckey = tuple(round(float(x), 3) for x in c.rgb)
        return (
            "shield_halo_legacy",
            ckey,
            round(self.amount, 2),
            round(self.speed, 2),
            round(self.radius, 2),
            round(self.sigma, 2),
        )

    def _tint_rgb(self, shape) -> Tuple[float, float, float]:
        tint = _host_primary_rgba(shape)
        if tint is None:
            # Re-apply after quality change: host may already be shield_cloud.
            fill = getattr(shape, "_fill", None) or getattr(shape, "fill", None)
            pc = getattr(fill, "color", None) if fill is not None else None
            if pc is not None and len(pc) >= 3:
                return (float(pc[0]), float(pc[1]), float(pc[2]))
        if tint is None and self._seed is not None:
            try:
                r, g, b = self._seed.rgb[:3]
                tint = (float(r), float(g), float(b), 1.0)
            except Exception:
                tint = None
        if tint is None:
            tint = self._DEFAULT_TINT
        return (float(tint[0]), float(tint[1]), float(tint[2]))

    def _apply(self, shape) -> None:
        from .style import BlendMode, ProceduralFill
        from .fx_quality import fidelity_is_lite

        if self._seed is not None:
            try:
                if is_stroke_type(shape):
                    shape.line = self._seed
                else:
                    shape.fill = self._seed
            except Exception:
                pass

        rgb = self._tint_rgb(shape)
        inten = max(0.35, min(2.0, self.amount))
        is_line = is_stroke_type(shape)
        glow = None
        if not fidelity_is_lite():
            glow = GlowFilter(
                radius=self.radius * (0.9 + 0.2 * inten),
                sigma=self.sigma * (0.95 + 0.15 * inten),
                intensity=0.75 + 0.4 * inten,
                color=(*rgb, 1.0),
            )
        if is_line:
            # Lines have no fill plate — keep a bright stroke + optional line glow.
            shape.fill = None
            shape.line = Color(rgb[0], rgb[1], rgb[2], min(1.0, 0.85 * inten))
            _set_line_width(shape, _OUTLINE_SHIELD_HALO)
            shape.fill_filter = None
            shape.line_filter = glow
            shape.blend = BlendMode.NORMAL
            return

        # Unique fill instance per shape so fleets with different tints do not
        # thrash a shared ProceduralFill uniform bag.
        shape.fill = ProceduralFill(
            kind="shield_cloud",
            amount=inten,
            speed=self.speed,
            color=rgb,
        )
        try:
            # Match host fill hue at half opacity.
            shape.line = Color(rgb[0], rgb[1], rgb[2], 0.5)
        except Exception:
            pass
        _set_line_width(shape, _OUTLINE_SHIELD_HALO)
        shape.line_filter = None
        # Outer glow only on high/max — medium/low keep animated plasma only.
        shape.fill_filter = glow
        shape.blend = BlendMode.NORMAL

    def _render(self, shape, skia_canvas) -> None:
        # Package path always — kept for API symmetry; not used as multipass.
        shape._geometry_draw(skia_canvas)


class _OrbHalo(GlowRimVisual):
    """Energy shell: tinted plasma fill + Halo GPU-blur rim at high.

    Not multipass :class:`~scena.recipes.Shield` (no multi-rim stack).
    Returned by ``Shield(style="halo")`` — legal on ``Sprite.visual``.

    **Low / medium:** plasma body + tinted stroke, no halo filter.
    **High:** interned ``Blur`` on the stroke (shared ``_batch_key`` across hues)
    + unfiltered rim/spine. GlowFilter is not used — tint stays out of the DAG.
    """

    _allows_sprite = True
    _VARIANT = "shield_halo"
    _DEFAULT_TINT = (0.45, 0.95, 0.35, 1.0)
    _KEEP_HOST_FILL = True
    _USE_WASH = False
    _BLEND_ADD = False

    @classmethod
    def _intern_extra(cls, kw: dict) -> tuple:
        return (
            round(float(kw.get("speed", 1.0)), 2),
            round(float(kw.get("radius", 16.0)), 2),
            round(float(kw.get("sigma", 8.0)), 2),
        )

    def __init__(
        self,
        color=None,
        *,
        amount: float = 1.0,
        speed: float = 1.0,
        radius: float = 16.0,
        sigma: float = 8.0,
    ):
        if getattr(self, "_ready", False):
            return
        self._init_glowrim(color, amount)
        self.speed = float(speed)
        self.radius = float(radius)
        self.sigma = float(sigma)
        self._fallback = _OrbHaloLegacy(
            color, amount=amount, speed=speed, radius=radius, sigma=sigma,
        )
        self._ready = True

    def _apply_high(self, shape, BlendMode) -> None:
        from .style import ProceduralFill

        if self._seed is not None:
            try:
                if is_stroke_type(shape):
                    shape.line = self._seed
                else:
                    shape.fill = self._seed
            except Exception:
                pass
        rgb = self._tint_rgba(shape)[:3]
        inten = max(0.35, min(2.0, self.amount))
        is_line = is_stroke_type(shape)
        if is_line:
            shape.fill = None
            shape.line = Color(rgb[0], rgb[1], rgb[2], min(1.0, 0.85 * inten))
            _set_line_width(shape, _OUTLINE_SHIELD_HALO)
            shape.fill_filter = None
            shape.line_filter = self._halo_high
            shape.blend = BlendMode.ADD
            return
        shape.fill = ProceduralFill(
            kind="shield_cloud",
            amount=inten,
            speed=self.speed,
            color=rgb,
        )
        try:
            shape.line = Color(rgb[0], rgb[1], rgb[2], 0.88)
        except Exception:
            pass
        _set_line_width(shape, _OUTLINE_SHIELD_HALO)
        shape.fill_filter = None
        shape.line_filter = self._halo_high
        shape.blend = BlendMode.NORMAL


# Metal / Sphere / Wave / Aurora live in recipes.py.


class Swell(CompiledVisual):
    """Abstract flow-field fill (procedural). Single pass; animates via fill tick.

    On ``Sprite``: fills the alpha silhouette (replaces the bitmap).

    Args:
        amount: Strength.
        speed: Animation speed.
    """

    _color_role = "D"
    _allows_sprite = True
    _replaces_sprite_body = True

    def __new__(cls, amount: float = 1.0, speed: float = 1.0):
        key = ("swell", round(float(amount), 2), round(float(speed), 2))
        return _intern(key, lambda: object.__new__(cls))

    def __init__(self, amount: float = 1.0, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        from .style import SwellFill
        self.amount = float(amount)
        self.speed = float(speed)
        self._fill = SwellFill(amount=self.amount, speed=self.speed)
        self._ready = True

    def _apply(self, shape) -> None:
        from .style import BlendMode, Color as C

        reset_paint_package(shape, keep_line_width=True)
        # Unique fill instance per apply so shared visuals don't thrash uniforms across differently sized shapes at different times — shared intern is OK (same params).
        shape.fill = self._fill
        shape.line = C(0.55, 0.75, 0.9, 0.5)
        _set_line_width(shape, _OUTLINE_SWELL)
        shape.blend = BlendMode.NORMAL
        shape.fill_filter = None
        shape.line_filter = None


class Flame(CompiledVisual):
    """Animated fire fill (procedural). Thin rim always present.

    On ``Sprite``: fills the alpha silhouette (replaces the bitmap).

    Args:
        amount: Turbulence.
        speed: Animation speed (default 1.2).
        border: Yellow rim (default ``False``).
    """

    _color_role = "D"
    _allows_sprite = True
    _replaces_sprite_body = True

    def __new__(
        cls,
        amount: float = 1.0,
        speed: float = 1.2,
        border: bool = False,
    ):
        key = (
            "fire",
            round(float(amount), 2),
            round(float(speed), 2),
            bool(border),
        )
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        amount: float = 1.0,
        speed: float = 1.2,
        border: bool = False,
    ):
        if getattr(self, "_ready", False):
            return
        from .style import FlameFill
        self.amount = float(amount)
        self.speed = float(speed)
        self.border = bool(border)
        self._fill = FlameFill(amount=self.amount, speed=self.speed)
        self._ready = True

    def _apply(self, shape) -> None:
        from .style import BlendMode, Color as C

        reset_paint_package(shape, keep_line_width=True)
        shape.fill = self._fill
        shape.blend = BlendMode.NORMAL
        shape.fill_filter = None
        shape.line_filter = None
        if is_stroke_type(shape) or self.border:
            # Brighter / yellower rim; costume-owned tip width
            shape.line = C(1.0, 0.88, 0.28, 0.95)
        else:
            shape.line = C(0.0, 0.0, 0.0, 0.5)
        _set_line_width(shape, _OUTLINE_FIRE)



# Metal / Sphere multipass Recipes live in recipes.py.
# Wave / Aurora multipass Recipes live in recipes.py.


def _hue_rotate_matrix(turns: float) -> list:
    """Skia ColorMatrix (4x5 row-major) for hue rotation by ``turns`` (1.0 = 360°)."""
    import math
    ang = float(turns) * math.tau
    c = math.cos(ang)
    s = math.sin(ang)
    # CSS / SVG hue-rotate matrix
    return [
        0.213 + 0.787 * c - 0.213 * s,
        0.715 - 0.715 * c - 0.715 * s,
        0.072 - 0.072 * c + 0.928 * s,
        0, 0,
        0.213 - 0.213 * c + 0.143 * s,
        0.715 + 0.285 * c + 0.140 * s,
        0.072 - 0.072 * c - 0.283 * s,
        0, 0,
        0.213 - 0.213 * c - 0.787 * s,
        0.715 - 0.715 * c + 0.715 * s,
        0.072 + 0.928 * c + 0.072 * s,
        0, 0,
        0, 0, 0, 1, 0,
    ]


class HueShift(CompiledVisual):
    """Rotate every pixel's hue. Sprite ``.hue`` or ``Texture(shift=)``.

    ``amount`` is turns (1.0 = full circle). ``to=`` sets amount from that
    color's hue (absolute rotation from identity). Static amounts use an
    interned ColorFilter on the blit / Texture paint; live / animated amount
    uses SkSL and is Sprite-only (``Texture(shift=HueShift(live=True))`` raises).
    Assign with ``sprite.hue = HueShift(...)`` or ``sprite.hue = True`` (1/3 turn).
    """

    _color_role = "C"
    _allows_sprite = True
    _sprite_only = True
    _is_multipass = False

    def __new__(
        cls,
        amount: Optional[float] = None,
        *,
        to: Optional[ColorLike] = None,
        live: bool = False,
    ):
        turns = _resolve_hue_turns(amount, to)
        key = ("hueshift", round(float(turns), 4), bool(live))
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        amount: Optional[float] = None,
        *,
        to: Optional[ColorLike] = None,
        live: bool = False,
    ):
        if getattr(self, "_ready", False):
            return
        self.amount = _resolve_hue_turns(amount, to)
        self.live = bool(live)
        self._color_filter = None
        if not self.live:
            import skia
            self._color_filter = skia.ColorFilters.Matrix(_hue_rotate_matrix(self.amount))
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        return ("hueshift", round(float(self.amount), 4), bool(self.live))

    def _apply(self, shape) -> None:
        # Blit ColorFilter installed by Sprite; clear ImageFilters.
        shape.fill_filter = None
        shape.line_filter = None
        install = getattr(shape, "_install_blit_color_filter", None)
        if callable(install):
            install(self._color_filter if not self.live else None)
            live_fn = getattr(shape, "_install_blit_hue_live", None)
            if callable(live_fn):
                live_fn(self.amount if self.live else None)


def _resolve_hue_turns(amount, to) -> float:
    if amount is not None and to is not None:
        raise TypeError("HueShift: use amount= or to=, not both")
    if to is not None:
        c = _as_color(to)
        try:
            hsv = c.hsv
            return float(hsv[0]) % 1.0
        except Exception:
            return 0.0
    if amount is None:
        return 0.0
    return float(amount) % 1.0


_LUMA = (0.2126, 0.7152, 0.0722)


def _grayscale_matrix(amount: float) -> list:
    """Skia ColorMatrix (4x5 row-major): identity → luma gray, ``amount`` 0–1."""
    k = float(amount)
    rows = []
    for i in range(3):
        row = [k * w for w in _LUMA]
        row[i] += 1.0 - k
        rows.extend(row + [0, 0])
    rows.extend([0, 0, 0, 1, 0])
    return rows


def _check_gray_amount(amount) -> float:
    from .validate import number
    value = number(amount, "Grayscale amount")
    if not 0.0 <= value <= 1.0:
        raise ValueError(
            f"Grayscale amount must be between 0 and 1 (1 = fully gray), got {value:g}."
        )
    return value


class Grayscale(CompiledVisual):
    """Drain the color from every pixel. Sprite ``.gray``.

    ``amount`` 1 is fully gray (luma), 0.5 half way. One interned
    ColorFilter on the blit paint, so a gray sprite stays on the cheap blit
    path; it composes with ``.hue`` (hue first, then gray). Assign with
    ``sprite.gray = True`` / ``sprite.gray = 0.5`` / ``sprite.gray = Grayscale(0.5)``.

    Args:
        amount: How gray, 0–1 (default 1, fully gray).
    """

    _color_role = "C"
    _allows_sprite = True
    _sprite_only = True
    _is_multipass = False

    def __new__(cls, amount: float = 1.0):
        value = round(_check_gray_amount(amount), 4)
        return _intern(("grayscale", value), lambda: object.__new__(cls))

    def __init__(self, amount: float = 1.0):
        if getattr(self, "_ready", False):
            return
        import skia
        # Store the interned key, not the raw value: the first caller must
        # not decide what a later Grayscale(0) reads (0.00001 then 0 shared
        # one object with amount 1e-5, so ``sprite.gray = 0`` stayed on).
        self.amount = round(_check_gray_amount(amount), 4)
        self._color_filter = skia.ColorFilters.Matrix(_grayscale_matrix(self.amount))
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        return ("grayscale", round(float(self.amount), 4))

    def _apply(self, shape) -> None:
        install = getattr(shape, "_install_blit_gray", None)
        if callable(install):
            install(self._color_filter)


class Aura(CompiledVisual):
    """Pixel-accurate SDF fringe (inner+outer band, no hard stroke). Sprite-only.

    Not Halo (bloom + sharp rim) and not Rim (glow + lip + core). Dual-host
    outline lighting stays ``Halo`` / ``Rim``.

    Args:
        color: Band color (default: follows the object).
        amount: Strength.
        width: Band thickness (default 0.35).
    """

    _color_role = "C"
    _allows_sprite = True
    _sprite_only = True
    _needs_sprite_path = True
    _needs_sprite_sdf = True
    _is_multipass = True  # custom render: SDF quad + blit
    _fidelity_sensitive = True

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        *,
        width: float = 0.35,
    ):
        if color is None:
            ckey = ("default",)
        else:
            c = _as_color(color)
            ckey = ("solid", tuple(round(float(x), 3) for x in c.rgb))
        key = (
            "aura", ckey, round(float(amount), 2), round(float(width), 2),
        )
        return _intern(key, lambda: object.__new__(cls))

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        *,
        width: float = 0.35,
    ):
        if getattr(self, "_ready", False):
            return
        self.color = color
        self.amount = float(amount)
        self.width = max(0.05, float(width))
        if color is None:
            self._rgba = (0.45, 0.85, 1.0, 1.0)
        else:
            c = _as_color(color)
            self._rgba = (
                float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]),
                float(c.rgb[3]) if len(c.rgb) > 3 else 1.0,
            )
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        return (
            "aura", tuple(round(x, 3) for x in self._rgba),
            round(self.amount, 2), round(self.width, 2),
        )

    def _apply(self, shape) -> None:
        shape.fill_filter = None
        shape.line_filter = None

    def _render(self, shape, skia_canvas) -> None:
        from .fx_quality import fidelity_is_survival
        draw = getattr(shape, "_draw_sprite_aura", None)
        if callable(draw) and not fidelity_is_survival():
            draw(skia_canvas, self)
        shape._geometry_draw(skia_canvas)


class EmissiveBloom(CompiledVisual):
    """Bright-pass bloom of this sprite's pixels. Sprite-only; heroes / few.

    Interned ImageFilter (luminance gate + blur) on ``fill_filter``.
    Low quality drops the blur.

    Args:
        intensity: Strength (default 1.35).
        sigma: Blur (default 10).
    """

    _color_role = "C"
    _allows_sprite = True
    _sprite_only = True
    _fidelity_sensitive = True
    _is_multipass = False

    def __new__(
        cls,
        intensity: float = 1.35,
        sigma: float = 10.0,
    ):
        key = ("emissive", round(float(intensity), 2), round(float(sigma), 2))
        return _intern(key, lambda: object.__new__(cls))

    def __init__(self, intensity: float = 1.35, sigma: float = 10.0):
        if getattr(self, "_ready", False):
            return
        self.intensity = max(0.0, float(intensity))
        self.sigma = max(0.5, float(sigma))
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        return ("emissive", round(self.intensity, 2), round(self.sigma, 2))

    def _apply(self, shape) -> None:
        from .fx_quality import fidelity_is_survival
        from .style import BlendMode
        from .filters import EmissiveFilter
        shape.line_filter = None
        if fidelity_is_survival() or self.intensity <= 0:
            shape.fill_filter = None
        else:
            shape.fill_filter = EmissiveFilter(
                intensity=self.intensity, sigma=self.sigma,
            )
        shape.blend = BlendMode.NORMAL


__all__ = [
    "Visual",
    "CompiledVisual",
    "Paint",
    "Fill",
    "Stroke",
    "Glow",
    "CheapGlow",
    "Halo",
    "Shadow",
    "Swell",
    "Flame",
    "HueShift",
    "Aura",
    "EmissiveBloom",
    "sample_body_rgba",
    "sample_outline_rgba",
]
