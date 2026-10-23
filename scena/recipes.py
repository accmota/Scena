"""
Multipass shape Recipe visuals (``scena.recipes``).

Geometry stays on the shape (``_geometry_draw``). Recipes repaint with CTM /
paints / path effects. Instances intern by ``_batch_key``. Stroke/fill paints
set Skia ``Color4f`` from RGBA tuples (interned seed tints bake RGB; pulse
alpha uses ``setAlphaf``) — they do not construct ``Color`` per stroke.
HSV helpers (``_vivid_rgb`` / ``_energy_rgb``) use ``colorsys`` + a small
intern — same tax avoidance for Neon / energy looks. Interned Laser / Neon /
Ink on one layer emit look-passes together when filter batching is on.
ElectricField high / ElectricBolt medium+high PE-glow shares one overlay Plus
plate among interned peers. Install via ``shape.visual = Neon()``
(or any Recipe / CompiledVisual).

**Primary tint:** when a recipe has a color parameter, shape ``fill`` /
``line`` are the live source of truth. ``color=`` on the constructor is
sugar that seeds the bound channel once at assignment; later style changes
update the costume. Recipes without a host-bound color (Water, Flame, …) leave
style alone. Fixed accents (white cores, yellow sparks) stay recipe-owned.

Compiled single-pass visuals live in :mod:`scena.visuals`.
"""
from __future__ import annotations

import colorsys
import math
import time
from typing import Dict, List, Literal, Optional, Tuple

import skia

from .entity import is_sprite_family, scena_kind
from ._defaults import Unset
from .color import Color, ColorLike, _chroma_weight, resolve_rgba
from .validate import expect_choice

ShieldStyle = Literal[
    "bubble", "nebula", "ember", "void", "molten", "bands", "vortex",
    "cracks", "frost", "plasma",
]
SHIELD_STYLES = (
    "bubble", "nebula", "ember", "void", "molten", "bands", "vortex",
    "cracks", "frost", "plasma",
)
# shield_cracks uniforms and their magma defaults (a fill with no palette).
_CRACKS_UNIFORMS = (
    ("u_rock", (0.12, 0.04, 0.02)), ("u_dark", (0.28, 0.08, 0.04)),
    ("u_lava", (1.0, 0.4, 0.05)), ("u_spar", (1.0, 0.85, 0.25)),
    ("u_shell", (1.0, 0.75, 0.25)),
)
BoltStyle = Literal["core", "filaments", "tesla"]
BOLT_STYLES = ("core", "filaments", "tesla")
from .style import (
    BlendMode, _SKIA_BLEND_MAP, Gradient,
    is_stroke_type, is_sprite_body, SPRITE_BODY, DEFAULT_LINE_WIDTH,
)
from .visuals import (
    Visual, CompiledVisual, GlowRimVisual, Halo,
    _aura_lift_rgb, _aura_mix_hot, _paint_rgba,
    sample_body_rgba, sample_outline_rgba,
)
from .filters import Blur, GlowFilter, HostGlow
from .fx_quality import (
    hero_fx_lod, HeroLod, fidelity_tier, fidelity_is_lite, fidelity_is_survival,
    TIER_LOW, TIER_MED, TIER_HIGH,
)

_EXTRUDE_FOCUS: Tuple[float, float] = (600.0, 40.0)
# World-locked metal specular direction (degrees). Shared by all Metal shapes.
_METAL_LIGHT_ANGLE: float = 28.0
_RECIPE_CACHE: Dict[tuple, "Recipe"] = {}
# Tiny intern of RGB Color4f (alpha always 1). Pulse / layer alpha uses setAlphaf.
_C4F_RGB: Dict[tuple, skia.Color4f] = {}
_C4F_RGB_CAP = 256
_WHITE_C4F = skia.Color4f(1.0, 1.0, 1.0, 1.0)
# HSV helper results (Neon vivid / energy chroma). Keyed by RGB floats — same
# pattern as _C4F_RGB; no Color() / validate on the hot path.
_VIVID_RGB: Dict[tuple, Tuple[float, float, float]] = {}
_VIVID_RGB_CAP = 256
_ENERGY_RGB: Dict[tuple, Tuple[float, float, float, float]] = {}
_ENERGY_RGB_CAP = 256
_ENERGY_SPARK: Dict[tuple, Tuple[float, float, float]] = {}
_ENERGY_SPARK_CAP = 256
_STROKE_JOIN = {
    "round": skia.Paint.Join.kRound_Join,
    "miter": skia.Paint.Join.kMiter_Join,
    "bevel": skia.Paint.Join.kBevel_Join,
}
_STROKE_CAP = {
    "round": skia.Paint.Cap.kRound_Cap,
    "square": skia.Paint.Cap.kSquare_Cap,
    "project": skia.Paint.Cap.kButt_Cap,
}

# Tint channel names for Recipe.tint_channel
_TINT_FILL = "fill"
_TINT_LINE = "line"
_TINT_AUTO = "auto"
_TINT_BODY = "body"
_TINT_OUTLINE = "outline"


def _hero_lod() -> HeroLod:
    """Quality-linked multipass budget for stock multipass looks."""
    return hero_fx_lod()


def _pe_seed(rate: float, lod: Optional[HeroLod] = None, *, cap: bool = True) -> int:
    """PathEffect seed from ``rate`` Hz. ``cap`` applies the quality pe_hz ceiling."""
    hz = max(float(rate), 1.0)
    if cap:
        lod = lod or _hero_lod()
        hz = min(hz, float(lod.pe_hz))
    step = 1.0 / max(hz, 1.0)
    return int(_clock() / step) % 100000


def _lod_mask(default_mask):
    """Return MaskFilter only when quality allows blur masks."""
    if not _hero_lod().mask:
        return None
    return default_mask


def _lod_passes() -> int:
    return int(_hero_lod().passes)


# DashRing dash pattern. Phase must wrap on the *interval sum* — wrapping a
# larger period (e.g. 60) causes a visible jump every wrap (~1.25s at speed=1).
_RING_DASH = (10.0, 7.0, 3.0, 7.0)
_RING_DASH_PERIOD = sum(_RING_DASH)  # 27


def _ring_dash_phase(t: float, *, scale: float = 1.0) -> float:
    """Continuous dash phase in [0, period). ``scale`` reverses/speeds a layer."""
    return (float(t) * 48.0 * float(scale)) % _RING_DASH_PERIOD


def _ring_dash_pe(phase: float) -> skia.PathEffect:
    return skia.DashPathEffect.Make(list(_RING_DASH), float(phase))


def set_extrude_focus(x: float, y: float) -> None:
    """Set the global vanishing point for Extrude when ``focus=`` is not passed.

    Call every frame (e.g. ``set_extrude_focus(mouse.x, mouse.y)``) for a live
    mouse-driven perspective. Per-instance override: ``Extrude(focus=(x, y))``.
    """
    global _EXTRUDE_FOCUS
    from .validate import number
    _EXTRUDE_FOCUS = (number(x, "set_extrude_focus x"), number(y, "set_extrude_focus y"))


def get_extrude_focus() -> Tuple[float, float]:
    """Current global Extrude vanishing point (see :func:`set_extrude_focus`)."""
    return _EXTRUDE_FOCUS


def set_metal_light(angle_deg: float) -> None:
    """Global metal specular light angle (degrees, shared by all Metal shapes)."""
    global _METAL_LIGHT_ANGLE
    _METAL_LIGHT_ANGLE = float(angle_deg) % 360.0


def get_metal_light() -> float:
    return _METAL_LIGHT_ANGLE


def _resolve_color(color, default=(0.3, 0.85, 1.0, 1.0)) -> Tuple[float, float, float, float]:
    """RGBA for look tints; delegates to :func:`scena.color.resolve_rgba`."""
    return resolve_rgba(color, default)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def _vivid_rgb(rgb, amount: float = 0.55) -> Tuple[float, float, float]:
    """Same math as ``Color.vibrant_version`` — float path, no ``Color()``.

    Interned by ``(r, g, b, amount)``. Used by Neon tint; safe for any caller
    that wants the vibrant lift without the Color construction tax. A gray
    stays gray (``_chroma_weight``): no invented hue-0 red.
    """
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    amt = float(amount)
    key = (r, g, b, amt)
    hit = _VIVID_RGB.get(key)
    if hit is not None:
        return hit
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s2 = min(1.0, s + _chroma_weight(s) * (amt + (1.0 - s) * amt * 0.65))
    v2 = min(1.0, max(v, 0.72) + amt * 0.28)
    out = colorsys.hsv_to_rgb(h, s2, v2)
    if len(_VIVID_RGB) < _VIVID_RGB_CAP:
        _VIVID_RGB[key] = out
    return out


def _energy_rgb(tint) -> Tuple[float, float, float, float]:
    """Host hue, slightly chroma-boosted (a gray stays gray). Does not rewrite shape fill/line."""
    if type(tint) is tuple and len(tint) >= 3:
        r, g, b = float(tint[0]), float(tint[1]), float(tint[2])
    else:
        r, g, b, _a = _resolve_color(tint)
    key = (r, g, b)
    hit = _ENERGY_RGB.get(key)
    if hit is not None:
        return hit
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s2 = min(1.0, s + _chroma_weight(s) * (1.0 - s) * 0.32)
    rr, gg, bb = colorsys.hsv_to_rgb(h, s2, v)
    out = (rr, gg, bb, 1.0)
    if len(_ENERGY_RGB) < _ENERGY_RGB_CAP:
        _ENERGY_RGB[key] = out
    return out


def _energy_spark_rgb(rgb, lift: float = 0.15) -> Tuple[float, float, float]:
    """Brighter same-hue accent — an HSV *value* lift, not an RGB-to-white mix.

    Used for a small "hot" highlight inside an energy stroke so it reads as
    more energetic without turning pale.
    """
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    amt = max(0.0, float(lift))
    key = (r, g, b, amt)
    hit = _ENERGY_SPARK.get(key)
    if hit is not None:
        return hit
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    v2 = min(1.0, v + (1.0 - v) * amt)
    out = colorsys.hsv_to_rgb(h, min(1.0, s * 1.05), v2)
    if len(_ENERGY_SPARK) < _ENERGY_SPARK_CAP:
        _ENERGY_SPARK[key] = out
    return out


def _energy_blend(role: str = "glow"):
    """BlendMode for one energy-effect draw pass.

    ``role="core"`` is the primary, most-visible stroke of the effect (must
    read as the true hue). ``role="glow"`` is a softer bloom layer (wash
    fill, secondary/outer dash, blurred halo).
    """
    return BlendMode.NORMAL if role == "core" else BlendMode.ADD


def _gpu_blur_stroke(look, shape, skia_canvas, paint, *, sigma: float = 2.2) -> None:
    """GPU ``Blur`` of one overlay stroke — MaskFilter stand-in (interned kernel).

    Composites with Plus so the bloom stays additive like the old Recipe
    ``blend=ADD`` + ``MaskFilter`` pass. Batched silhouette ``line_filter``
    is unchanged; this is only the PE-shaped glow behind the arcs.
    """
    halo = Blur(sigma=float(sigma))
    bounds = _overlay_glow_shape_bounds(shape, float(paint.getStrokeWidth()), float(sigma))
    layer = skia.Paint()
    layer.setImageFilter(halo._skia_filter)
    layer.setBlendMode(skia.BlendMode.kPlus)
    skia_canvas.saveLayer(bounds, layer)
    try:
        look._stroke_at_scale(shape, skia_canvas, paint, 1.0)
    finally:
        skia_canvas.restore()


def _overlay_glow_shape_bounds(shape, stroke_width: float, sigma: float) -> skia.Rect:
    cx, cy, r = _center_radius(shape)
    pad = 3.0 * float(sigma) + 0.5 * float(stroke_width) + 8.0
    return skia.Rect.MakeLTRB(cx - r - pad, cy - r - pad, cx + r + pad, cy + r + pad)


def _union_overlay_glow_bounds(shapes, sigma: float, designed_w: float) -> skia.Rect:
    """Union of per-shape ``_gpu_blur_stroke`` AABBs (same pad formula)."""
    sig = float(sigma)
    minx = miny = 1e30
    maxx = maxy = -1e30
    for shape in shapes:
        w = _stroke_width_for_shape(shape, designed_w, mode="shock")
        box = _overlay_glow_shape_bounds(shape, w, sig)
        minx = min(minx, box.left())
        miny = min(miny, box.top())
        maxx = max(maxx, box.right())
        maxy = max(maxy, box.bottom())
    return skia.Rect.MakeLTRB(minx, miny, maxx, maxy)


def _draw_electric_add_line(look, shape, skia_canvas, *, amount: float, speed: float) -> None:
    """Survival: host geometry plus one ADD Discrete-PE stroke (no blur / cores)."""
    shape._geometry_draw(skia_canvas)
    tint = look._primary_tint(shape) if hasattr(look, "_primary_tint") else look._tint_rgba(shape)
    rgb = _energy_rgb(tint)
    seed = _pe_seed(14.0 * float(speed), cap=False)
    if _is_line_shape(shape):
        pe = _line_discrete_pe(float(amount), seed)
        width = _stroke_width_for_shape(shape, 1.6, mode="shock")
    else:
        pe = _discrete_pe(max(3.0, float(amount) * 0.4), float(amount), seed)
        width = 1.6
    paint = look._stroke_paint(
        color=rgb, width=width, blend=BlendMode.ADD, path_effect=pe, alpha=0.9,
    )
    shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)


def _draw_shock_pe_stack(
    look, shape, skia_canvas, rgb, pe, *,
    glow_w: float, mid_w: float, core_w: float,
    glow_a: float = 1.0, mid_rgb=(1.0, 1.0, 0.5), mid_a: float = 0.8,
    core_a: float = 0.95, blur_glow: bool = False, blur_sigma: float = 2.2,
    skip_glow: bool = False,
) -> None:
    """Old Recipe electricity: optional GPU-blurred PE glow + yellow mid + white core."""
    if (not skip_glow) and float(glow_w) > 0.05:
        glow = look._rim_skia_paint(rgb, float(glow_a), float(glow_w), path_effect=pe)
        if blur_glow:
            _gpu_blur_stroke(look, shape, skia_canvas, glow, sigma=blur_sigma)
        else:
            look._stroke_at_scale(shape, skia_canvas, glow, 1.0)
    mid = look._rim_skia_paint(mid_rgb, float(mid_a), float(mid_w), path_effect=pe)
    look._stroke_at_scale(shape, skia_canvas, mid, 1.0)
    core = look._rim_skia_paint((1.0, 1.0, 1.0), float(core_a), float(core_w), path_effect=pe)
    look._stroke_at_scale(shape, skia_canvas, core, 0.98)


def _color_obj(color, default=(0.3, 0.85, 1.0, 1.0)) -> Color:
    rgba = _resolve_color(color, default)
    return Color(_clamp01(rgba[0]), _clamp01(rgba[1]), _clamp01(rgba[2]), _clamp01(rgba[3]))


def _rgba_for_paint(color, alpha=None, default=(0.3, 0.85, 1.0, 1.0)):
    """RGBA for Recipe paints. 3/4-tuples skip Color() / resolve_rgba / validate."""
    if type(color) is tuple:
        n = len(color)
        if n >= 4:
            r, g, b, a = color[0], color[1], color[2], color[3]
        elif n == 3:
            r, g, b, a = color[0], color[1], color[2], default[3]
        else:
            r, g, b, a = _resolve_color(color, default)
    else:
        r, g, b, a = _resolve_color(color, default)
    if alpha is not None:
        a = _clamp01(float(alpha))
    return r, g, b, a


def _color4f_rgb(r, g, b) -> skia.Color4f:
    key = (r, g, b)
    hit = _C4F_RGB.get(key)
    if hit is not None:
        return hit
    c4 = skia.Color4f(float(r), float(g), float(b), 1.0)
    if len(_C4F_RGB) < _C4F_RGB_CAP:
        _C4F_RGB[key] = c4
    return c4


def _apply_paint_color4f(paint, look, r, g, b, a) -> None:
    """setColor4f from baked/interned RGB; pulse alpha via setAlphaf only."""
    seed = getattr(look, "_seed_color", None)
    seed_c4f = getattr(look, "_seed_c4f", None)
    if seed is not None and seed_c4f is None:
        seed_c4f = skia.Color4f(float(seed[0]), float(seed[1]), float(seed[2]), 1.0)
        look._seed_c4f = seed_c4f
    if seed_c4f is not None and r == seed[0] and g == seed[1] and b == seed[2]:
        c4 = seed_c4f
    elif r == 1.0 and g == 1.0 and b == 1.0:
        c4 = _WHITE_C4F
    else:
        c4 = _color4f_rgb(r, g, b)
    paint.setColor4f(c4)
    if a != 1.0:
        paint.setAlphaf(float(a))


def _intern(cls, key: tuple, factory):
    hit = _RECIPE_CACHE.get(key)
    if hit is not None:
        return hit
    obj = factory()
    obj.__dict__["_interned"] = True  # shared: public writes refused once _ready
    _RECIPE_CACHE[key] = obj
    return obj


def _scalar(v, default: float = 0.0) -> float:
    try:
        if hasattr(v, "value"):
            return float(v.value)
        return float(v)
    except Exception:
        return default


def _center_radius(shape) -> Tuple[float, float, float]:
    """Return ``(cx, cy, approx_radius)`` for Recipe UV / multipass mapping.

    Delegates to ``transients.shape_pivot`` so free Polygon / Text / rotated
    Square share one extent rule with fade/dissolve saveLayer bounds.
    """
    from .transients import shape_pivot
    return shape_pivot(shape)


def _shape_has_line(shape) -> bool:
    """True when the style would paint a stroke (not no_line)."""
    lp = getattr(shape, "_line", None)
    if lp is None:
        try:
            lp = shape.line
        except Exception:
            return False
    # Color(None) / Gradients that fail bool → no stroke
    return bool(lp)


def _shape_has_fill(shape) -> bool:
    if is_stroke_type(shape):
        return False
    fp = getattr(shape, "_fill", None)
    if fp is None:
        try:
            fp = shape.fill
        except Exception:
            return False
    return bool(fp)


def _host_rgba(shape) -> Tuple[float, float, float, float]:
    """Sample shape fill (Color, Gradient stop, or Texture proxy)."""
    fp = getattr(shape, "_fill", None)
    if fp is None:
        try:
            fp = shape.fill
        except Exception:
            fp = None
    sampled = _paint_rgba(fp)
    if sampled is not None:
        return sampled
    if isinstance(fp, str):
        return _resolve_color(fp)
    if isinstance(fp, (tuple, list)) and len(fp) >= 3:
        return _resolve_color(fp)
    return (0.45, 0.75, 0.95, 1.0)


def _clock() -> float:
    try:
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        return float(getattr(fw.clock, "time", 0.0) or 0.0)
    except Exception:
        return time.perf_counter()


def _local_matrix(cx: float, cy: float, angle_deg: float = 0.0, scale: float = 1.0) -> skia.Matrix:
    m = skia.Matrix()
    m.setTranslate(cx, cy)
    if angle_deg:
        m.preRotate(float(angle_deg))
    if abs(scale - 1.0) > 1e-6:
        m.preScale(float(scale), float(scale))
    return m


def _local_shader(shader, cx: float, cy: float, angle_deg: float = 0.0, scale: float = 1.0):
    if shader is None:
        return None
    m = _local_matrix(cx, cy, angle_deg, scale)
    if hasattr(shader, "makeWithLocalMatrix"):
        return shader.makeWithLocalMatrix(m)
    return shader


def _procedural_shader(
    fill,
    cx: float,
    cy: float,
    half: float,
    *,
    rot_deg: float = 0.0,
    light_deg: Optional[float] = None,
):
    """Tick RuntimeEffect uniforms for origin-centered paint coords.

    Scena geometry draws under ``translate(center)`` so SkSL ``coord`` is local
    to the shape (center = 0). ``u_resolution`` is the design-space **diameter**
    so shaders use ``uv = 0.5 + coord / u_resolution``.
    Do not use ``Shader.makeWithLocalMatrix`` on RuntimeEffects — py-skia yields
    empty samples; diameter uniform is the correct mapping.

    Optional ``rot_deg`` / ``light_deg`` are for world-locked fills (metal).
    """
    t = _clock()
    # Diameter spanning UV 0..1; slight oversize so radial edge softens inside rim.
    res = max(48.0, float(half) * 2.15)
    try:
        b = fill._builder
        b.setUniform("u_time", float(t) * float(getattr(fill, "_speed", 1.0)))
        b.setUniform("u_amount", float(getattr(fill, "_amount", 1.0)))
        b.setUniform("u_seed", float(getattr(fill, "_seed", 0.0)))
        b.setUniform("u_resolution", [res, res])
        kind = str(getattr(fill, "_kind", getattr(fill, "kind", "")))
        col = getattr(fill, "_color", None)
        if col is not None and kind in (
            "wave", "aurora", "sphere", "ink_wash", "ink_bleed",
            "shield_bands", "shield_cloud", "shield_vortex",
        ):
            try:
                b.setUniform("u_color", list(col[:3]))
            except Exception:
                pass
        if kind == "shield_bubble":
            try:
                extra = getattr(fill, "_extra_rgb", None) or Shield._BUBBLE_PALETTE
                for name in ("u_lime", "u_yell", "u_film"):
                    b.setUniform(name, list(extra[name[2:]][:3]))
            except Exception:
                pass
        # Multi-stop shield palettes (nebula family / cracks shell)
        if kind in ("shield_stars", "shield_nebula_mist"):
            try:
                extra = getattr(fill, "_extra_rgb", None) or {}
                for name, default in (
                    ("u_deep", (0.12, 0.02, 0.28)),
                    ("u_mid", (0.45, 0.1, 0.65)),
                    ("u_star", (1.0, 0.35, 0.85)),
                    ("u_shell", (0.35, 0.95, 1.0)),
                ):
                    key = name[2:]  # deep, mid, star, shell
                    rgb = extra.get(key, default)
                    b.setUniform(name, list(rgb[:3]))
            except Exception:
                pass
        if kind == "shield_cracks":
            try:
                extra = getattr(fill, "_extra_rgb", None) or {}
                for name, default in _CRACKS_UNIFORMS:
                    b.setUniform(name, list(extra.get(name[2:], default)[:3]))
            except Exception:
                pass
        if kind == "metal":
            try:
                b.setUniform("u_rot", float(rot_deg))
                b.setUniform("u_origin", [float(cx), float(cy)])
                la = _METAL_LIGHT_ANGLE if light_deg is None else float(light_deg)
                b.setUniform("u_light", float(la))
                b.setUniform("u_tint", _metal_tint(fill))
            except Exception:
                pass
        fill._shader = b.makeShader()
        fill._proc_tick_t = t
    except Exception:
        try:
            fill._tick(t)
        except Exception:
            pass
    return fill._skia_shader


def _outline_points(shape, n: int = 10) -> List[Tuple[float, float]]:
    """World-space silhouette samples (respect rotation for axis-aligned boxes)."""
    cx, cy, r = _center_radius(shape)
    verts = getattr(shape, "_vertices", None)
    if verts:
        try:
            return [(_scalar(v.x), _scalar(v.y)) for v in verts]
        except Exception:
            pass
    # Rect/Square local corners → rotate by pose
    if hasattr(shape, "width") and hasattr(shape, "height"):
        w = abs(_scalar(shape.width)) * 0.5
        h = abs(_scalar(shape.height)) * 0.5
        local = [
            (-w, -h), (w, -h), (w, h), (-w, h),
            (-w, 0.0), (w, 0.0), (0.0, -h), (0.0, h),
        ]
        rv = getattr(shape, "_rotation_value", None)
        rot_deg = float(rv()) if callable(rv) else float(getattr(shape, "_rotation", 0.0) or 0.0)
        oriented = probe_private(shape, "_oriented_frame", None)
        if callable(oriented):
            try:
                rot_deg = float(oriented()[4])
            except Exception:
                pass
        rad = math.radians(rot_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        return [
            (cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a)
            for lx, ly in local
        ]
    return [
        (cx + r * math.cos(2 * math.pi * i / n),
         cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _is_circle_like(shape) -> bool:
    """True only for ``Circle``.

    Do not duck-type on ``center`` + ``radius``: ``RegularPolygon`` /
    ``Triangle`` also expose a ``radius``, but must use the
    best-effort silhouette path (not ``drawCircle``). ``Ellipse`` is a
    separate ``_forcefield_kind`` branch (oval + angle), not circle-like.
    """
    return scena_kind(shape) == "Circle"


def _forcefield_kind(shape) -> Optional[str]:
    """Which outline family force-field looks may use (circle / ellipse / line)."""
    if is_sprite_family(shape):
        return "ellipse"
    name = scena_kind(shape)
    if name == "Line":
        return "line"
    if name == "Ellipse":
        return "ellipse"
    if _is_circle_like(shape):
        return "circle"
    return None


def _ellipse_params(shape) -> Tuple[float, float, float, float, float]:
    """cx, cy, width, height, angle_deg.

    Sprites use the oriented sprite rectangle (AABB of the unrotated sprite,
    then rotated with the sprite) — same ellipse Electric*/Shield use.
    """
    if _is_sprite(shape):
        try:
            cx, cy, w, h, ang = shape._oriented_frame()
            return (
                float(cx), float(cy),
                max(abs(float(w)), 1.0), max(abs(float(h)), 1.0),
                float(ang),
            )
        except Exception:
            pass
    cx = cy = 0.0
    try:
        c = getattr(shape, "center", None)
        if c is not None:
            cx = _scalar(getattr(c, "x", 0.0))
            cy = _scalar(getattr(c, "y", 0.0))
    except Exception:
        pass
    w = abs(_scalar(getattr(shape, "width", 40.0), 40.0))
    h = abs(_scalar(getattr(shape, "height", 24.0), 24.0))
    rv = getattr(shape, "_rotation_value", None)
    ang = float(rv()) if callable(rv) else _scalar(getattr(shape, "angle", 0.0), 0.0)
    return cx, cy, max(w, 1.0), max(h, 1.0), ang


def _line_ends(shape, scale: float = 1.0) -> Tuple[float, float, float, float]:
    """World segment endpoints; scale expands length about the midpoint."""
    p1, p2 = getattr(shape, "p1", None), getattr(shape, "p2", None)
    x1, y1 = _scalar(p1.x), _scalar(p1.y)
    x2, y2 = _scalar(p2.x), _scalar(p2.y)
    if abs(scale - 1.0) < 1e-6:
        return x1, y1, x2, y2
    mx, my = 0.5 * (x1 + x2), 0.5 * (y1 + y2)
    return (
        mx + (x1 - mx) * scale,
        my + (y1 - my) * scale,
        mx + (x2 - mx) * scale,
        my + (y2 - my) * scale,
    )


def _is_line_shape(shape) -> bool:
    return is_stroke_type(shape)


def _host_stroke_knobs(shape) -> dict:
    """Cap (always) and join (stroke types only) from the host for recipe paints.

    Area shapes keep join=\"round\" so neon/rim corners stay soft. Cap defaults
    to \"round\" on the host too — only \"project\" / \"square\" change tips.
    """
    cap = getattr(shape, "line_cap", "round") or "round"
    if is_stroke_type(shape):
        join = getattr(shape, "line_join", "round") or "round"
        return {"cap": cap, "join": join}
    return {"cap": cap}


def _host_line_width(shape, default: float = DEFAULT_LINE_WIDTH) -> float:
    try:
        t = float(getattr(shape, "line_width", default) or default)
    except Exception:
        t = default
    return max(t, 0.5)


def _set_line_width(shape, width: float) -> None:
    """Install a costume's standard outline width (overwrite host)."""
    try:
        shape.line_width = float(width)
    except Exception:
        pass


# Costume-owned outline widths (not host-preserving accessories).
_OUTLINE_RINGFIELD = 2.0
_OUTLINE_SHIELDGEAR = 2.4  # 1.5 × 1.6 (60% thicker)
# Solid / inner-core energy strokes: slight transparency so they sit on the wash.
_ENERGY_CORE_A = 0.90
_OUTLINE_SHIELD = 1.5
_OUTLINE_PLASMASHOT = 1.5
_OUTLINE_SWELL = 1.5
_OUTLINE_FIRE = 1.5
_OUTLINE_METAL = 1.5
_METAL_EDGE = (0.75, 0.78, 0.82, 0.95)  # chrome rim; Line and closed share this
# Internal colour argument of a palette look's recolor sibling (Metal, bubble
# Shield): ``set_color`` swaps the look for the one interned instance that
# tints from the shape's live colour. Not an author spelling: ``Metal()`` is
# the palette; ``Metal(color)`` a fixed tint.
_FOLLOW_SHAPE = Unset("<follows the shape>")
_OUTLINE_GEL = 2.0
_OUTLINE_WAVE = 1.5
_OUTLINE_AURORA = 1.5


def _line_scaled_stroke_width(host_th: float, designed: float) -> float:
    """Map outline-recipe stroke widths onto a Line's line_width.

    On Circle/Ellipse, designed width is a *margin* around the silhouette.
    On Line, stroke width *is* the body — scale modestly around host_th so
    glow/halo layers stay near the original line, not 2–4× thicker.
    """
    d = max(float(designed), 0.25)
    # designed ~0.7 → ~0.95·host, ~1.5 → ~1.15·host, ~3.2 → ~1.5·host
    mul = 0.85 + 0.20 * min(d, 5.0)
    return host_th * min(mul, 1.7)


def _line_shock_stroke_width(host_th: float, designed: float) -> float:
    """Thin emission threads for lightning / electric on Lines (not body line_width).

    Recipe widths are closed-shape halo margins; on lines those must stay fine
    stroke filaments — smaller than the host line_width, not ~1.5× host.
    """
    d = max(float(designed), 0.25)
    # designed 3.5/3.2 → ~0.55–0.7·host (max ~1.4px for host 2.5 is too small?
    # host 2–4.5 in lab: 3.2 → 0.45*host+0.35 → ~1.25–2.3 for halo, 1.5 → mid, 0.65 → core)
    base = 0.22 * d + 0.28 * host_th
    return max(0.35, min(base, host_th * 0.75, d * 0.55 + 0.3))


def _stroke_width_for_shape(shape, designed: float, *, mode: str = "outline") -> float:
    """Keep absolute designed width for closed shapes; scale for Lines."""
    if not _is_line_shape(shape):
        return float(designed)
    host = _host_line_width(shape)
    if mode == "shock":
        return _line_shock_stroke_width(host, designed)
    return _line_scaled_stroke_width(host, designed)


def _line_discrete_pe(amount: float, seed: int) -> skia.PathEffect:
    """Smaller DiscretePathEffect on Lines so arcs do not bloom into thick bands."""
    # Closed-shape electric uses amount≈5 (several px of deviation).
    # On a 2–4px host line that reads as a fat ribbon.
    a = max(0.8, min(float(amount) * 0.28, 1.8))
    seg = max(1.0, a * 0.55)
    return _discrete_pe(seg, a, seed)


# Bounded cache: DiscretePathEffect.Make is relatively heavy and Electric*/Ink
# seeds step infrequently. Same (seg, amp, seed) → same PE object.
_DISCRETE_PE_CACHE: dict = {}
_DISCRETE_PE_CACHE_MAX = 256


def _discrete_pe(seg: float, amp: float, seed: int) -> skia.PathEffect:
    """Interned ``DiscretePathEffect`` for multipass looks (Electric*, Ink fringe)."""
    s = max(0.5, float(seg))
    a = max(0.1, float(amp))
    key = (round(s, 2), round(a, 2), int(seed) % 100000)
    pe = _DISCRETE_PE_CACHE.get(key)
    if pe is not None:
        return pe
    pe = skia.DiscretePathEffect.Make(s, a, key[2])
    if len(_DISCRETE_PE_CACHE) >= _DISCRETE_PE_CACHE_MAX:
        _DISCRETE_PE_CACHE.clear()
    _DISCRETE_PE_CACHE[key] = pe
    return pe


def _host_stroke_rgba(shape) -> Tuple[float, float, float, float]:
    """Host stroke color (for Line looks). Falls back to fill then a cool default."""
    lp = getattr(shape, "_line", None)
    if lp is None:
        try:
            lp = shape.line
        except Exception:
            lp = None
    if isinstance(lp, Color) and bool(lp):
        try:
            rgb = lp.rgb
            if rgb is not None and len(rgb) >= 3:
                a = float(rgb[3]) if len(rgb) > 3 else 1.0
                return (float(rgb[0]), float(rgb[1]), float(rgb[2]), a)
        except Exception:
            pass
    return _host_rgba(shape)


def _line_soft_energy_bed(
    look: "Recipe",
    shape,
    skia_canvas,
    color,
    *,
    body_mul: float = 1.55,
    glow_mul: float = 2.7,
    blur: float = 2.4,
    body_a: float = 0.42,
    glow_a: float = 0.32,
    pulse_speed: float = 4.0,
) -> None:
    """Cheap soft energy underlay along a Line (blurred ADD strokes, no SkSL).

    Compensates for closed shapes getting a soft fill disc while Lines have none.
    ``blur <= 0`` skips the MaskFilter glow pass (cheaper LOD).
    """
    host = _host_line_width(shape)
    pulse = 0.9 + 0.1 * math.sin(_clock() * pulse_speed)
    rgba = _resolve_color(color, (0.55, 0.85, 1.0, 1.0))
    # Soft mid body (always)
    body = look._stroke_paint(
        color=rgba, width=host * body_mul, blend=BlendMode.ADD, alpha=body_a,
    )
    if blur > 0.05:
        mask = skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, max(1.2, float(blur)))
        glow = look._stroke_paint(
            color=rgba, width=host * glow_mul * pulse, blend=BlendMode.ADD, mask=mask, alpha=glow_a,
        )
        _ff_draw_stroke(skia_canvas, shape, glow, 1.0, line_mode="raw")
    _ff_draw_stroke(skia_canvas, shape, body, 1.0, line_mode="raw")
    # Mild bright core so the bed reads as "filled energy"
    core = look._stroke_paint(
        color=(
            min(1.0, rgba[0] * 0.55 + 0.45),
            min(1.0, rgba[1] * 0.55 + 0.45),
            min(1.0, rgba[2] * 0.55 + 0.5),
            1.0,
        ),
        width=max(0.6, host * 0.55),
        blend=BlendMode.ADD,
        alpha=0.28 + 0.08 * math.sin(_clock() * pulse_speed * 1.3),
    )
    _ff_draw_stroke(skia_canvas, shape, core, 1.0, line_mode="raw")


def _ff_draw_fill(
    skia_canvas, shape, paint, scale: float = 1.0, *, line_body: float = 1.2,
) -> None:
    """Soft energy body: full disc / oval / line stroke (``line_body`` · host · scale)."""
    kind = _forcefield_kind(shape)
    if kind == "circle":
        cx, cy, r = _center_radius(shape)
        skia_canvas.drawCircle(cx, cy, max(0.5, r * scale), paint)
    elif kind == "ellipse":
        # Sprite: soft wash follows the alpha silhouette when scale ≈ 1.
        if _is_sprite(shape) and _ff_try_sprite_silhouette(
            skia_canvas, shape, paint, scale,
        ):
            return
        cx, cy, w, h, ang = _ellipse_params(shape)
        geo = scale * _ff_sprite_shield_scale(shape)
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if ang:
            skia_canvas.rotate(ang)
        hw, hh = 0.5 * w * geo, 0.5 * h * geo
        skia_canvas.drawOval(skia.Rect.MakeLTRB(-hw, -hh, hw, hh), paint)
        skia_canvas.restore()
    elif kind == "line":
        x1, y1, x2, y2 = _line_ends(shape, scale)
        p = skia.Paint(paint)
        if p.getStyle() != skia.Paint.kStroke_Style:
            p.setStyle(skia.Paint.kStroke_Style)
        host = _host_line_width(shape)
        p.setStrokeWidth(max(0.5, host * float(line_body) * scale))
        skia_canvas.drawLine(x1, y1, x2, y2, p)


def _ff_sprite_shield_scale(shape) -> float:
    """Shield on Sprite uses ``shield_scale`` (default 1.4); Electric* unchanged."""
    if not is_sprite_family(shape):
        return 1.0
    from .sprite import _sprite_ellipse_scale
    return _sprite_ellipse_scale(shape)


def _ff_try_sprite_silhouette(skia_canvas, shape, paint, scale: float = 1.0) -> bool:
    """Stroke/fill Sprite alpha path when shield scale is 1:1. Returns True if drawn."""
    if not is_sprite_family(shape):
        return False
    if abs(_ff_sprite_shield_scale(shape) - 1.0) > 1e-3:
        return False
    draw = getattr(shape, "_draw_sprite_silhouette", None)
    if not callable(draw):
        return False
    if abs(float(scale) - 1.0) < 1e-3:
        return bool(draw(skia_canvas, paint))
    cx, cy, _w, _h, _ang = _ellipse_params(shape)
    skia_canvas.save()
    skia_canvas.translate(cx, cy)
    skia_canvas.scale(float(scale), float(scale))
    skia_canvas.translate(-cx, -cy)
    ok = bool(draw(skia_canvas, paint))
    skia_canvas.restore()
    return ok


def _is_sprite(shape) -> bool:
    """True for Sprite and subclasses (Svg, author bodies). Not a name check."""
    return bool(getattr(type(shape), "_is_sprite_body", False))


def _stroke_host_v2(skia_canvas, shape, paint) -> None:
    """Simplified cached silhouette on Sprite; host geometry otherwise."""
    if _is_sprite(shape):
        draw = getattr(shape, "_draw_sprite_silhouette_v2", None)
        if callable(draw) and draw(skia_canvas, paint):
            return
    shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)


def _world_stroke_kind(shape) -> Optional[str]:
    """``line`` / ``circle`` when a solid world primitive matches ``_geometry_draw``.

    ``line`` is one ``Line`` segment (world ``drawLine`` of ``p1``/``p2``).
    Polylines — ``Track`` and Contrail's ``_Stroke`` — have no endpoints and
    stay on ``_geometry_draw``.
    """
    if _is_sprite(shape):
        return None
    if scena_kind(shape) == "Line":
        return "line"
    if scena_kind(shape) != "Circle":
        return None
    try:
        spread = float(shape.spread)
        if spread < 360.0 - 1e-6:
            return None
    except Exception:
        pass
    return "circle"


def _stroke_group_world(shapes, skia_canvas, paint, *, centers=None) -> None:
    """One ADD/SrcOver stroke pass for a look-pass run (shared paint).

    World ``drawLine`` / ``drawCircle`` skip Line midpoint CTM. Overlapping
    ADD peers stay N draws (one Path would union coverage). ``drawPoints``
    is used for ≥2 lines when the binding exposes ``kLines``.

    ``centers`` — optional precomputed ``(cx, cy, r)`` per shape for the
    circle fast path (hoist once across halo/body/core passes).
    """
    if not shapes:
        return
    kind = None
    for s in shapes:
        k = _world_stroke_kind(s)
        if k is None or (kind is not None and k != kind):
            kind = None
            break
        kind = k
    if kind == "line":
        n = len(shapes)
        if n >= 2:
            pts = []
            for s in shapes:
                x1, y1, x2, y2 = _line_ends(s)
                pts.append(skia.Point(float(x1), float(y1)))
                pts.append(skia.Point(float(x2), float(y2)))
            try:
                skia_canvas.drawPoints(skia.Canvas.kLines_PointMode, pts, paint)
                return
            except Exception:
                pass
        for s in shapes:
            x1, y1, x2, y2 = _line_ends(s)
            skia_canvas.drawLine(float(x1), float(y1), float(x2), float(y2), paint)
        return
    if kind == "circle":
        if centers is not None and len(centers) == len(shapes):
            for cx, cy, r in centers:
                skia_canvas.drawCircle(float(cx), float(cy), float(r), paint)
            return
        for s in shapes:
            cx, cy, r = _center_radius(s)
            skia_canvas.drawCircle(float(cx), float(cy), float(r), paint)
        return
    for s in shapes:
        s._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)


def _fill_group_world(shapes, skia_canvas, paint, *, centers=None) -> None:
    """Closed-body fill pass; world ``drawCircle`` when every host is a full disk.

    ``centers`` — optional precomputed ``(cx, cy, r)`` (same as stroke group).
    """
    if not shapes:
        return
    if all(_world_stroke_kind(s) == "circle" for s in shapes):
        if centers is not None and len(centers) == len(shapes):
            for cx, cy, r in centers:
                skia_canvas.drawCircle(float(cx), float(cy), float(r), paint)
            return
        for s in shapes:
            cx, cy, r = _center_radius(s)
            skia_canvas.drawCircle(float(cx), float(cy), float(r), paint)
        return
    for s in shapes:
        s._geometry_draw(skia_canvas, fill_paint=paint, stroke_paint=None)


def _blit_sprite_body(shape, skia_canvas) -> None:
    """Draw the sprite bitmap only (no silhouette fill or stroke)."""
    if not _is_sprite(shape):
        return
    blit = getattr(shape, "_blit_image", None)
    paint = getattr(shape, "_blit_paint", None)
    if callable(blit) and paint is not None:
        blit(skia_canvas, paint)
        return
    from .entity import _STYLE_PAINT
    shape._geometry_draw(skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=None)


def _ff_draw_stroke(
    skia_canvas, shape, paint, scale: float = 1.0, *, line_mode: str = "outline",
) -> None:
    """Ring / outline matching the host geometry.

    ``line_mode``: ``outline`` (rings/glow, near host), ``shock`` (electric),
    ``raw`` (paint width as-is — plasma line restore).
    On ``Sprite`` (non-Shield scale), prefers the cached silhouette path.
    """
    kind = _forcefield_kind(shape)
    if kind == "circle":
        # Local CTM so sweep / Gradient shaders on the stroke are centered.
        cx, cy, r = _center_radius(shape)
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        skia_canvas.drawCircle(0.0, 0.0, max(0.5, r * scale), paint)
        skia_canvas.restore()
    elif kind == "ellipse":
        if _ff_try_sprite_silhouette(skia_canvas, shape, paint, scale):
            return
        cx, cy, w, h, ang = _ellipse_params(shape)
        geo = scale * _ff_sprite_shield_scale(shape)
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if ang:
            skia_canvas.rotate(ang)
        hw, hh = 0.5 * w * geo, 0.5 * h * geo
        skia_canvas.drawOval(skia.Rect.MakeLTRB(-hw, -hh, hw, hh), paint)
        skia_canvas.restore()
    elif kind == "line":
        x1, y1, x2, y2 = _line_ends(shape, scale)
        p = skia.Paint(paint)
        if line_mode == "raw":
            pass  # keep paint StrokeWidth
        elif line_mode == "shock":
            p.setStrokeWidth(_line_shock_stroke_width(_host_line_width(shape), p.getStrokeWidth()))
        else:
            p.setStrokeWidth(_line_scaled_stroke_width(_host_line_width(shape), p.getStrokeWidth()))
        skia_canvas.drawLine(x1, y1, x2, y2, p)


def _ff_shader_half(shape, *, plasma_line: bool = False) -> float:
    """Characteristic radius for procedural force-field shaders."""
    kind = _forcefield_kind(shape)
    if kind == "ellipse":
        _, _, w, h, _ = _ellipse_params(shape)
        sc = _ff_sprite_shield_scale(shape)
        return 0.5 * max(w, h) * sc
    if kind == "line":
        host = _host_line_width(shape)
        x1, y1, x2, y2 = _line_ends(shape, 1.0)
        half_len = 0.5 * math.hypot(x2 - x1, y2 - y1)
        if plasma_line:
            # Pre-thinning plasma-on-line: shader spans segment, not a thin tube
            return max(half_len, host * 4.0)
        return max(host * 2.0, min(half_len, host * 8.0))
    _, _, r = _center_radius(shape)
    return r


def _gear_outline_len(shape) -> float:
    """Path length of the rim the dashes crawl on (for sweep lock)."""
    kind = _forcefield_kind(shape)
    if kind == "ellipse":
        _, _, w, h, _ = _ellipse_params(shape)
        a, b = 0.5 * max(w, 1.0), 0.5 * max(h, 1.0)
        return math.pi * (3.0 * (a + b) - math.sqrt((3.0 * a + b) * (a + 3.0 * b)))
    if kind == "line":
        x1, y1, x2, y2 = _line_ends(shape, 1.0)
        return max(math.hypot(x2 - x1, y2 - y1), 1.0)
    _, _, r = _center_radius(shape)
    return 2.0 * math.pi * max(float(r), 1.0)


def _ff_best_effort_pass(
    shape, skia_canvas, *, fill_paint=None, stroke_paint=None, scale: float = 1.0,
) -> None:
    """Repaint host geometry (any shape) once; optional uniform scale about center."""
    if abs(scale - 1.0) < 1e-6:
        shape._geometry_draw(skia_canvas, fill_paint=fill_paint, stroke_paint=stroke_paint)
        return
    cx, cy, _ = _center_radius(shape)
    skia_canvas.save()
    skia_canvas.translate(cx, cy)
    skia_canvas.scale(scale, scale)
    skia_canvas.translate(-cx, -cy)
    shape._geometry_draw(skia_canvas, fill_paint=fill_paint, stroke_paint=stroke_paint)
    skia_canvas.restore()


def _soft_radial_fill_paint(
    cx: float,
    cy: float,
    radius: float,
    rgb: Tuple[float, float, float],
    *,
    alpha: float = 1.0,
    hold: float = 0.72,
    blend=BlendMode.ADD,
) -> skia.Paint:
    """Radial alpha: full opacity to ``hold``, then ease to 0 (soft edge).

    Skia radial positions are 0 at center → 1 at ``radius``.
    """
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    a = max(0.0, min(1.0, float(alpha)))
    h = max(0.05, min(0.95, float(hold)))
    colors = [
        skia.Color4f(r, g, b, a),
        skia.Color4f(r, g, b, a),
        skia.Color4f(r, g, b, 0.0),
    ]
    positions = [0.0, h, 1.0]
    shader = skia.GradientShader.MakeRadial(
        center=(float(cx), float(cy)),
        radius=max(1.0, float(radius)),
        colors=colors,
        positions=positions,
    )
    paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kFill_Style,
        BlendMode=_SKIA_BLEND_MAP.get(blend, skia.BlendMode.kSrcOver),
    )
    paint.setShader(shader)
    return paint


def _plasma_dash_phase(t: float, s: float, intervals=(6.0, 4.0, 2.0, 4.0)) -> float:
    """Dash phase wrapped on the *actual* interval sum (avoids a jump each wrap)."""
    s = max(0.35, float(s))
    period = sum(float(x) for x in intervals) * s
    return (float(t) * 55.0 * s) % max(period, 1e-3)


def _energy_survival_ladder(
    look: "Recipe",
    shape,
    skia_canvas,
    tint,
    *,
    wash_alpha: Optional[float] = None,
    wash_scale: float = 0.90,
    wash_line_body: float = 1.2,
    host_body: bool = False,
    halo_width: float,
    core_width: float,
    core_color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 0.9),
    ff: bool = False,
    line_mode: str = "outline",
    blend=BlendMode.ADD,
    **stroke_knobs,
) -> None:
    """Static wash + halo + core for survival (low) fidelity only.

    Max three solid geometry passes. No MaskFilter, PathEffect, or time.
    ``host_body`` and ``wash_alpha`` are mutually exclusive (≤3 draws).
    ``stroke_knobs`` — optional ``cap`` / ``join`` for host-following looks.
    """
    if host_body:
        shape._geometry_draw(skia_canvas)
    elif wash_alpha is not None and wash_alpha > 0.0:
        disc = look._fill_paint_from(tint, alpha=float(wash_alpha), blend=blend)
        if ff:
            _ff_draw_fill(
                skia_canvas, shape, disc, float(wash_scale),
                line_body=float(wash_line_body),
            )
        else:
            _ff_best_effort_pass(
                shape, skia_canvas, fill_paint=disc, stroke_paint=None,
                scale=float(wash_scale),
            )
    halo = look._stroke_paint(
        color=tint, width=float(halo_width), blend=blend, **stroke_knobs,
    )
    if ff:
        _ff_draw_stroke(skia_canvas, shape, halo, 1.0, line_mode=line_mode)
    else:
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=halo)
    if core_width > 0.0:
        core = look._stroke_paint(
            color=core_color, width=float(core_width), blend=blend, **stroke_knobs,
        )
        if ff:
            _ff_draw_stroke(skia_canvas, shape, core, 0.98, line_mode=line_mode)
        else:
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=core)


def _forcefield_best_effort(
    look: "Recipe", style: str, shape, skia_canvas, *, stroke_knobs: Optional[dict] = None,
) -> None:
    """Generic multipass force-field on arbitrary geometry via ``_geometry_draw``.

    Used when the shape is not Circle / Ellipse / Line. Circle/ellipse/line keep
    their specialized paths; this only approximates rings/glow/plasma/electric.
    Honors quality (lite dashed ring / softer aura at low).
    ``stroke_knobs`` — optional ``cap`` / ``join`` for host-following looks
    (DashRing). Electric costumes omit them so paints stay round.
    """
    t = _clock()
    knobs = stroke_knobs or {}

    # Outline widths: closed-shape margins; slightly modest so shapes stay readable
    def stroke(color, width, *, blend=BlendMode.ADD, path_effect=None, mask=None, alpha=None):
        return look._stroke_paint(
            color=color, width=width, blend=blend,
            path_effect=path_effect, mask=mask, alpha=alpha, **knobs,
        )

    if style == "rings":
        speed = float(getattr(look, "speed", 1.0))
        width = float(getattr(look, "width", 2.0))
        hue = _energy_rgb(look._primary_tint(shape))
        tt = t * speed
        # Low: one dashed rim (readable identity, ~half the multipass work).
        if fidelity_is_survival():
            pe = _ring_dash_pe(_ring_dash_phase(tt))
            paint = stroke(
                hue, max(1.0, width), blend=_energy_blend("core"),
                path_effect=pe, alpha=_ENERGY_CORE_A,
            )
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=paint)
            return
        # Medium: wash + main dash (core) + lighter outer (glow).
        if fidelity_is_lite():
            disc = look._fill_paint_from(hue, blend=_energy_blend("glow"), alpha=0.14)
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=disc, stroke_paint=None)
            pe = _ring_dash_pe(_ring_dash_phase(tt))
            main = stroke(
                hue, max(1.0, width), blend=_energy_blend("core"),
                path_effect=pe, alpha=_ENERGY_CORE_A,
            )
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=main)
            pe2 = _ring_dash_pe(_ring_dash_phase(tt, scale=-1.2))
            outer = stroke(
                hue, max(0.8, width * 0.85), blend=_energy_blend("glow"),
                path_effect=pe2, alpha=0.42,
            )
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=outer, scale=1.08)
            return
        disc = look._fill_paint_from(hue, blend=_energy_blend("glow"), alpha=0.14)
        _ff_best_effort_pass(shape, skia_canvas, fill_paint=disc, stroke_paint=None)
        for sc, role, ph_mul, a in ((1.0, "core", 1.0, _ENERGY_CORE_A), (1.08, "glow", -1.3, 0.46)):
            pe = _ring_dash_pe(_ring_dash_phase(tt, scale=ph_mul))
            paint = stroke(
                hue, width, blend=_energy_blend(role),
                path_effect=pe, alpha=a,
            )
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=paint, scale=sc)
        return

    if style == "glow":
        amount = float(getattr(look, "amount", 1.0))
        color = look._primary_tint(shape)
        if fidelity_is_survival():
            _energy_survival_ladder(
                look, shape, skia_canvas, color,
                wash_alpha=0.14 * amount, wash_scale=0.92,
                halo_width=4.0 * amount,
                core_width=1.4,
                core_color=(1.0, 1.0, 1.0, 0.75),
            )
            return
        # Medium: Laser-style width ladder + white at same place as low (0.98 / 1.4).
        if fidelity_is_lite():
            disc = look._fill_paint_from(color, alpha=0.12 * amount, blend=BlendMode.ADD)
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=disc, stroke_paint=None, scale=0.92)
            base = 4.0 * amount
            for col, w in (
                ((*color[:3], 0.22), base * 1.55),
                ((*color[:3], 0.45), base * 1.05),
                ((*color[:3], 0.85), base * 0.55),
            ):
                _ff_best_effort_pass(
                    shape, skia_canvas, fill_paint=None,
                    stroke_paint=stroke(col, w),
                )
            rim = stroke((1.0, 1.0, 1.0, 0.75), 1.4)
            _ff_best_effort_pass(
                shape, skia_canvas, fill_paint=None, stroke_paint=rim, scale=0.98,
            )
            return
        # High: soft body + masked glow + white at same placement as low.
        mask = getattr(look, "_mask", None)
        disc = look._fill_paint_from(color, alpha=0.12 * amount, blend=BlendMode.ADD)
        _ff_best_effort_pass(shape, skia_canvas, fill_paint=disc, stroke_paint=None, scale=0.96)
        glow = stroke(color, 4.0 * amount, mask=mask)
        _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=glow)
        rim = stroke((1.0, 1.0, 1.0, 0.75), 1.4)
        _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=rim, scale=0.98)
        return

    if style == "plasma":
        speed = float(getattr(look, "speed", 1.2))
        tint = look._tint(shape) if hasattr(look, "_tint") else look._primary_tint(shape)
        hue = _energy_rgb(tint)
        _, _, rr = _center_radius(shape)
        s = max(0.45, float(rr) / 36.0)
        # Low + medium: shared mid ladder; high adds blur mask.
        disc = look._fill_paint_from(hue, blend=_energy_blend("glow"), alpha=0.14)
        _ff_best_effort_pass(
            shape, skia_canvas, fill_paint=disc, stroke_paint=None,
            scale=0.94 if not fidelity_is_lite() else 0.88,
        )
        pe = skia.DashPathEffect.Make(
            [6.0 * s, 4.0 * s, 2.0 * s, 4.0 * s],
            _plasma_dash_phase(t * speed, s),
        )
        if fidelity_is_lite():
            rim = stroke(
                hue, max(1.6, 3.0 * s), blend=_energy_blend("core"),
                path_effect=pe, alpha=_ENERGY_CORE_A,
            )
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=rim)
            return
        blur = skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, max(1.2, 3.5 * s))
        rim = stroke(
            hue, max(1.6, 3.0 * s), blend=_energy_blend("core"),
            path_effect=pe, mask=blur, alpha=_ENERGY_CORE_A,
        )
        _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=rim)
        return

    if style == "electric":
        amount = float(getattr(look, "amount", 5.0))
        speed = float(getattr(look, "speed", 1.0))
        color = look._primary_tint(shape)
        if fidelity_is_survival():
            # Charged shell (no PE) — matches specialized ElectricField survival.
            _energy_survival_ladder(
                look, shape, skia_canvas, color,
                wash_alpha=0.10, wash_scale=0.90,
                halo_width=3.2,
                core_width=0.85,
                core_color=(1.0, 1.0, 0.75, 0.9),
            )
            return
        seed = int(t * 14.0 * speed) % 100000
        pe = _discrete_pe(max(3.0, amount * 0.4), amount, seed)
        mask = getattr(look, "_mask", None)
        disc = look._fill_paint_from(color, alpha=0.06, blend=BlendMode.ADD)
        _ff_best_effort_pass(shape, skia_canvas, fill_paint=disc, stroke_paint=None, scale=0.94)
        _ff_best_effort_pass(
            shape, skia_canvas, fill_paint=None,
            stroke_paint=stroke(color, 3.5, path_effect=pe, mask=mask),
        )
        _ff_best_effort_pass(
            shape, skia_canvas, fill_paint=None,
            stroke_paint=stroke((1.0, 1.0, 0.55, 0.75), 1.6, path_effect=pe),
        )
        _ff_best_effort_pass(
            shape, skia_canvas, fill_paint=None,
            stroke_paint=stroke((1.0, 1.0, 1.0, 0.95), 0.7, path_effect=pe),
        )
        return

    # Unknown style — plain host draw
    shape._geometry_draw(skia_canvas)


def _host_fill_paint(shape, *, alpha: Optional[float] = None, hue_shift: float = 0.0):
    """Fill paint from host PaintState when possible; solid Color fallback."""
    try:
        fp = getattr(shape, "_fill", None)
        if fp is None:
            fp = getattr(shape, "fill", None)
        if fp is not None and not isinstance(fp, (Color, str, tuple, list)):
            paint = shape._to_skia_fill_paint()
            if paint is not None:
                if alpha is not None:
                    # A copy: the host's cached fill paint must keep its own
                    # alpha, or the body draws at the ghost's alpha (HP2).
                    paint = skia.Paint(paint)
                    try:
                        paint.setAlphaf(float(alpha))
                    except Exception:
                        pass
                return paint
    except Exception:
        pass
    rgba = _host_rgba(shape)
    col = Color(rgba[0], rgba[1], rgba[2], rgba[3] if len(rgba) > 3 else 1.0)
    if abs(hue_shift) > 1e-6:
        try:
            col = col.hue_cycle(hue_shift)
        except Exception:
            pass
    if alpha is not None:
        col = col.with_alpha(alpha)
    paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kFill_Style,
        BlendMode=skia.BlendMode.kSrcOver,
    )
    paint.setColor4f(col.color4f)
    return paint


def _clone_paint_alpha(paint, alpha_mul: float):
    """Copy a Skia paint and multiply its alpha (does not mutate the cached host paint)."""
    if paint is None:
        return None
    try:
        out = skia.Paint(paint)
    except Exception:
        return paint
    mul = max(0.0, min(1.0, float(alpha_mul)))
    try:
        out.setAlphaf(max(0.0, min(1.0, float(paint.getAlphaf()) * mul)))
    except Exception:
        try:
            out.setAlpha(int(max(0, min(255, paint.getAlpha() * mul))))
        except Exception:
            pass
    try:
        out.setImageFilter(None)
    except Exception:
        pass
    return out


def _faded_host_paints(shape, alpha_mul: float):
    """Host fill + stroke paints faded for motion ghosts (widths / shaders kept)."""
    fill_p = stroke_p = None
    fill = getattr(shape, "_fill", None)
    if is_sprite_body(fill):
        # Bitmap body: ghost is a faded blit paint (Tail on Sprite).
        fill_p = skia.Paint(AntiAlias=True)
        a = max(0.0, min(1.0, float(alpha_mul)))
        fill_p.setColor4f(skia.Color4f(1.0, 1.0, 1.0, a))
    elif _shape_has_fill(shape):
        try:
            fill_p = _clone_paint_alpha(shape._to_skia_fill_paint(), alpha_mul)
        except Exception:
            fill_p = None
    if _shape_has_line(shape) or _is_line_shape(shape):
        try:
            stroke_p = _clone_paint_alpha(shape._to_skia_line_paint(), alpha_mul)
        except Exception:
            stroke_p = None
    return fill_p, stroke_p


def _solid_paint_rgba(paint) -> Optional[Tuple[float, float, float, float]]:
    """Return RGBA if *paint* is a solid Color/str/tuple; else None (gradient etc.)."""
    if paint is None:
        return None
    if isinstance(paint, Color):
        if not paint:  # Color(None) / falsy no-paint
            return None
        return tuple(float(c) for c in paint.rgb)
    if isinstance(paint, str):
        return _resolve_color(paint)
    if isinstance(paint, (tuple, list)) and len(paint) >= 3:
        return _resolve_color(paint)
    return None


def _channel_paint_rgba(paint) -> Optional[Tuple[float, float, float, float]]:
    """RGBA from solid, Gradient stop, Texture proxy, or ProceduralFill tint."""
    rgba = _paint_rgba(paint)
    if rgba is not None:
        return rgba
    if paint is None:
        return None
    if isinstance(paint, str):
        return _resolve_color(paint)
    pc = getattr(paint, "_color", None) or getattr(paint, "color", None)
    if isinstance(pc, (tuple, list)) and len(pc) >= 3:
        a = float(pc[3]) if len(pc) > 3 else 1.0
        return (float(pc[0]), float(pc[1]), float(pc[2]), a)
    return None


def _host_line_rgba(shape) -> Tuple[float, float, float, float]:
    """Sample shape line/stroke Color (falls back to fill color)."""
    lp = getattr(shape, "_line", None)
    if lp is None:
        try:
            lp = shape.line
        except Exception:
            lp = None
    solid = _channel_paint_rgba(lp)
    if solid is not None:
        return solid
    return _host_rgba(shape)


def _tint_intern_key(color, default: Tuple[float, float, float, float]) -> tuple:
    """Intern key fragment: host-driven when color is None, else rounded seed."""
    if color is None:
        return ("host",)
    return tuple(round(c, 3) for c in _resolve_color(color, default))


def _refuse_number_as_color(owner: str, color, knob: str) -> None:
    """``Beat(0.1)`` / ``Liquify(5)``: the first argument became ``color`` in 0.6.0."""
    if isinstance(color, (int, float)) and not isinstance(color, bool):
        raise TypeError(
            f"{owner}'s first argument is color (since 0.6.0). "
            f"For the old {owner}({color!r}) write {owner}({knob}={color!r})."
        )


_BEAT_DEFAULT = (0.5, 0.5, 0.5, 1.0)       # unused for drawing: Beat paints the host
_LIQUIFY_DEFAULT = (0.5, 0.5, 0.5, 1.0)    # likewise — ghosts sample the host body


def _shape_fill_paint(shape):
    try:
        return getattr(shape, "_fill", None) or shape.fill
    except Exception:
        return getattr(shape, "_fill", None)


def _shape_line_paint(shape):
    try:
        return getattr(shape, "_line", None) or shape.line
    except Exception:
        return getattr(shape, "_line", None)


def _sample_channel_rgba(shape, channel: str) -> Optional[Tuple[float, float, float, float]]:
    """Live sample fill/line color (solid or Gradient stop). None when empty/unknown."""
    if channel in (_TINT_LINE, _TINT_OUTLINE):
        if channel == _TINT_OUTLINE:
            return sample_outline_rgba(shape)
        return _channel_paint_rgba(_shape_line_paint(shape))
    if channel in (_TINT_FILL, _TINT_BODY):
        if channel == _TINT_BODY:
            return sample_body_rgba(shape)
        return _channel_paint_rgba(_shape_fill_paint(shape))
    # auto → Role A body (fill only on area; line on stroke types)
    return sample_body_rgba(shape)


def _apply_at_draw(shape, apply, *args) -> None:
    """Run ``apply(*args)``, a look's package rewritten at draw time (fidelity
    switch inside ``_render``), under ``_in_visual_apply`` like ``visual =``:
    its channel writes neither patch identity nor re-apply the look
    (``PaintState._look_channel_written``)."""
    if getattr(shape, "_in_visual_apply", False):
        apply(*args)
        return
    shape._in_visual_apply = True
    try:
        apply(*args)
    finally:
        shape._in_visual_apply = False


def _write_role_color(shape, role: str, rgba: Tuple[float, float, float, float]) -> None:
    """Seed live channels for identity visuals (assignment-time)."""
    col = Color(
        _clamp01(rgba[0]), _clamp01(rgba[1]), _clamp01(rgba[2]),
        _clamp01(rgba[3] if len(rgba) > 3 else 1.0),
    )
    try:
        if is_stroke_type(shape):
            shape.line = col
            shape.fill = None
            return
        if role == "B":
            shape.line = col
            return
        # Role A: body only — fill on area shapes (never steal / rewrite outline).
        shape.fill = col
    except Exception:
        pass


def _write_channel_color(shape, channel: str, rgba: Tuple[float, float, float, float]) -> None:
    """Seed a solid Color into fill and/or line (assignment-time only)."""
    if channel in (_TINT_OUTLINE, _TINT_LINE):
        _write_role_color(shape, "B", rgba)
        return
    _write_role_color(shape, "A", rgba)


def _apply_live_fill_color(fill, rgb: Tuple[float, float, float]) -> None:
    """Cheap in-place tint for colorable ProceduralFill (shared sequential draw-safe)."""
    try:
        fill._color = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    except Exception:
        pass


def _ink_seed(speed: float = 1.0) -> int:
    return int(_clock() * max(speed, 0.05) * 4.0) % 100000


def _draw_host_fill(shape, skia_canvas) -> None:
    """Preserve original fill (color or advanced paint)."""
    if _is_line_shape(shape) or not _shape_has_fill(shape):
        return
    # Sprite bitmap body: normal blit (SPRITE_BODY is not a solid Skia fill).
    if _is_sprite(shape):
        from .entity import _STYLE_PAINT
        shape._geometry_draw(skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=None)
        return
    host = _host_fill_paint(shape)
    if host is not None:
        shape._geometry_draw(skia_canvas, fill_paint=host, stroke_paint=None)


def _draw_brush_stroke(
    look, shape, skia_canvas, *,
    amount: float = 1.0,
    speed: float = 0.5,
    layers: int = 1,
    darken: float = 0.0,
    widen: float = 1.0,
    alpha_scale: float = 1.0,
) -> None:
    """Stroke host silhouette with pen/brush jitter (DiscretePathEffect)."""
    host_rgba = _host_line_rgba(shape)
    th = _host_line_width(shape, 1.5)
    for i in range(max(1, layers)):
        seg = max(3.0, 7.0 - amount * 0.6)
        amp = max(0.6, amount * (0.9 + 0.35 * i))
        pe = _discrete_pe(seg, amp, (_ink_seed(speed) + i * 131) % 100000)
        k = max(0.25, 1.0 - darken * (0.35 + 0.2 * i))
        a = host_rgba[3] if len(host_rgba) > 3 else 1.0
        a = max(0.2, min(1.0, a * alpha_scale * (1.0 - 0.12 * i)))
        col = (host_rgba[0] * k, host_rgba[1] * k, host_rgba[2] * k, a)
        w = max(0.8, th * widen * (1.0 + 0.35 * i) + amount * 0.15)
        if _is_line_shape(shape):
            w = max(th * 0.85, w * 0.9)
        paint = look._stroke_paint(color=col, width=w, path_effect=pe)
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)


class Recipe(Visual):
    """Multi-pass paint recipe over host geometry (``_is_multipass=True``).

    **Primary tint** (when ``_tint_channel`` is set):
    - ``fill`` / ``line`` are the live source of truth each frame.
    - Constructor ``color=`` seeds that channel once in :meth:`apply` and
      dyes the author snapshot restored by ``visual = None``.
    - Constructor ``color=None`` leaves host style alone and samples it live.
    - Recipe-fixed accents (white cores, spark yellow) never bind to host.

    Recipes with ``_tint_channel is None`` (e.g. Water) do not read/write host color.
    Install via ``shape.visual = Neon()`` (author API).
    """

    _is_multipass = True
    # Consecutive same interned instance on one layer: pass-major emit
    # (canvas look-pass grouping). Off for hero multipass (Water, Metal, …).
    _look_pass_group = False
    _overlay_glow_batch = False
    _color_role = "D"

    # Subclasses set: "fill" | "line" | "auto" | "body" | "outline" | None
    _tint_channel: Optional[str] = None

    def __init__(self):
        self._seed_color: Optional[Tuple[float, float, float, float]] = None
        self._default_color: Tuple[float, float, float, float] = (0.5, 0.5, 0.5, 1.0)
        self.color: Tuple[float, float, float, float] = self._default_color

    def _init_tint(
        self,
        color,
        default: Tuple[float, float, float, float],
        *,
        channel: Optional[str] = _TINT_AUTO,
    ) -> None:
        """Configure primary-tint binding. Call from subclass ``__init__``."""
        self._tint_channel = channel
        self._default_color = _resolve_color(default, default)
        if color is None:
            self._seed_color = None
            self.color = self._default_color
            self._seed_c4f = None
        else:
            self._seed_color = _resolve_color(color, default)
            self.color = self._seed_color
            s = self._seed_color
            self._seed_c4f = skia.Color4f(float(s[0]), float(s[1]), float(s[2]), 1.0)

    @property
    def _batch_key(self) -> tuple:
        return (type(self).__name__,)

    def _apply(self, shape) -> None:
        """Reset paint filters; seed host fill/line when constructed with explicit ``color=``."""
        try:
            shape.fill_filter = None
            shape.line_filter = None
        except Exception:
            pass
        role = getattr(self, "_color_role", "D")
        if role not in ("A", "B") or self._seed_color is None:
            return
        _write_role_color(shape, role, self._seed_color)

    def _identity_patch(self, shape) -> None:
        role = getattr(self, "_color_role", "D")
        if role not in ("A", "B") or self._seed_color is None:
            return
        fn = getattr(shape, "_identity_patch_seed", None)
        if fn is not None:
            fn(self._seed_color, channel="auto")

    def _primary_tint(self, shape) -> Tuple[float, float, float, float]:
        """Live primary color: bound host channel → seed → look default."""
        role = getattr(self, "_color_role", "D")
        if role == "B":
            live = sample_outline_rgba(shape)
        elif role == "A":
            live = sample_body_rgba(shape)
        elif self._tint_channel is not None:
            live = _sample_channel_rgba(shape, self._tint_channel)
        else:
            return self.color
        if live is not None:
            return live
        if self._seed_color is not None:
            return self._seed_color
        return self._default_color

    def _render(self, shape, skia_canvas) -> None:
        shape._geometry_draw(skia_canvas)

    def _emit_look_passes(self, shapes, skia_canvas) -> None:
        """Draw ``shapes`` sharing this interned Recipe, pass-major.

        Default: per-shape :meth:`render` (same pixels and z as solo). Stroke
        ladders override to share paints and world primitives.
        """
        for shp in shapes:
            self._render(shp, skia_canvas)

    def _stroke_paint(
        self, *, color, width: float, blend=BlendMode.NORMAL,
        path_effect=None, alpha: Optional[float] = None, mask=None,
        image_filter=None, shader=None, join: str = "round",
        cap: str = "round",
    ) -> skia.Paint:
        r, g, b, a = _rgba_for_paint(color, alpha)
        # Rotate a small pool — multipass looks hold 2–4 strokes at once.
        slots = getattr(self, "_rp_strokes", None)
        if slots is None:
            slots = [None, None, None, None]
            self._rp_strokes = slots
        i = int(getattr(self, "_rp_stroke_i", 0)) % 4
        # Per-draw pool cursor: straight to __dict__, skipping the interned
        # write guard (Visual.__setattr__) on this hot path.
        self.__dict__["_rp_stroke_i"] = i + 1
        paint = slots[i]
        # skia-python rejects setPathEffect(None) / setMaskFilter(None) /
        # setImageFilter(None) / setShader(None); rebuild the slot when
        # clearing a prior effect.
        need_fresh = paint is not None and (
            (path_effect is None and paint.getPathEffect() is not None)
            or (mask is None and paint.getMaskFilter() is not None)
            or (image_filter is None and paint.getImageFilter() is not None)
            or (shader is None and paint.getShader() is not None)
        )
        if paint is None or need_fresh:
            paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeCap=skia.Paint.Cap.kRound_Cap,
                StrokeJoin=skia.Paint.Join.kRound_Join,
            )
            slots[i] = paint
        # Cap/join every call — pool slots retain the previous caller's values.
        cap_key = cap if type(cap) is str else str(cap)
        if cap_key != "round":
            cap_key = cap_key.lower()
        paint.setStrokeCap(_STROKE_CAP.get(cap_key, skia.Paint.Cap.kRound_Cap))
        join_key = join if type(join) is str else str(join)
        if join_key != "round":
            join_key = join_key.lower()
        paint.setStrokeJoin(_STROKE_JOIN.get(join_key, skia.Paint.Join.kRound_Join))
        if join_key == "miter":
            paint.setStrokeMiter(2.5)
        paint.setStrokeWidth(float(width))
        paint.setBlendMode(_SKIA_BLEND_MAP.get(blend, skia.BlendMode.kSrcOver))
        _apply_paint_color4f(paint, self, r, g, b, a)
        if path_effect is not None:
            paint.setPathEffect(path_effect)
        if mask is not None:
            paint.setMaskFilter(mask)
        if image_filter is not None:
            paint.setImageFilter(image_filter)
        if shader is not None:
            paint.setShader(shader)
        return paint

    def _fill_paint_from(self, color, *, blend=BlendMode.NORMAL, alpha=None) -> skia.Paint:
        r, g, b, a = _rgba_for_paint(color, alpha)
        slots = getattr(self, "_rp_fills", None)
        if slots is None:
            slots = [None, None, None]
            self._rp_fills = slots
        i = int(getattr(self, "_rp_fill_i", 0)) % 3
        self.__dict__["_rp_fill_i"] = i + 1  # hot path; see _stroke_paint
        paint = slots[i]
        if paint is None:
            paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kFill_Style,
            )
            slots[i] = paint
        paint.setBlendMode(_SKIA_BLEND_MAP.get(blend, skia.BlendMode.kSrcOver))
        _apply_paint_color4f(paint, self, r, g, b, a)
        return paint


# ---------------------------------------------------------------------------
# Core looks
# ---------------------------------------------------------------------------

# Fixed AC-hum frequency for Neon(flicker=). Not author-exposed (gradual params).
_NEON_FLICKER_HZ = 5.5


class Neon(Recipe):
    """Soft ADD halo + vivid body + thin white core. Role A (fill / body).

    Zero-arg follows host fill. ``color=`` seeds the body once. Not a filter —
    assign ``shape.visual = Neon()``. For mass halo use ``Glow`` / ``GlowFilter``.
    ``flicker=0`` is today's static Neon; ``>0`` wobbles the ADD halo.

    Args:
        color: Tint (any color form; default: follows the shape's own color).
        amount: Glow strength.
        width: Core thickness (default 3).
        flicker: Tube hum: 0 = steady.
    """

    _color_role = "A"
    _look_pass_group = True

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        width: float = 3.0,
        flicker: float = 0.0,
    ):
        from .validate import magnitude, fixed_magnitude
        amount = fixed_magnitude(amount, "Neon.amount")
        width = fixed_magnitude(width, "Neon.width")
        flicker = fixed_magnitude(flicker, "Neon.flicker")
        key = (
            "neon", _tint_intern_key(color, (0.35, 0.9, 1.0, 1.0)),
            round(float(amount), 3), round(float(width), 2),
            round(float(flicker), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        width: float = 3.0,
        flicker: float = 0.0,
    ):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.35, 0.9, 1.0, 1.0), channel=_TINT_BODY)
        self.amount = float(amount)
        self.width = float(width)
        self.flicker = float(flicker)
        self._mask = skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, max(1.5, 2.2 * self.amount))
        self._ready = True

    def _unseed(self) -> Optional["Neon"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.width, self.flicker)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("neon", ckey, round(self.amount, 3), round(self.width, 2), round(self.flicker, 2))

    def _flicker_env(self) -> float:
        """Pass-level halo envelope. ``flicker=0`` skips the sin() entirely."""
        if self.flicker > 0.0:
            return 1.0 + self.flicker * 0.15 * math.sin(_clock() * _NEON_FLICKER_HZ)
        return 1.0

    def _neon_tint(self, shape) -> Tuple[float, float, float, float]:
        """Shared vivid color for body fill/stroke and glow halo."""
        tint = self._primary_tint(shape)
        r, g, b = _vivid_rgb(tint, 0.55)
        return (r, g, b, 1.0)

    # Compat alias used by tests / callers that still say "glow"
    def _glow_tint(self, shape) -> Tuple[float, float, float, float]:
        return self._neon_tint(shape)

    def _draw_body(self, shape, skia_canvas, tint) -> None:
        """Paint body with the same vivid tint as the glow (not raw host paint)."""
        if _is_line_shape(shape):
            w = max(_host_line_width(shape), 0.8)
            stroke = self._stroke_paint(color=tint, width=w, **_host_stroke_knobs(shape))
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=stroke)
            return
        fill = self._fill_paint_from(tint)
        shape._geometry_draw(skia_canvas, fill_paint=fill, stroke_paint=None)

    def _emit_look_passes(self, shapes, skia_canvas) -> None:
        if not shapes:
            return
        if fidelity_is_lite():
            for shp in shapes:
                self._render(shp, skia_canvas)
            return
        env = self._flicker_env()
        buckets: Dict[tuple, list] = {}
        order: List[tuple] = []
        for shp in shapes:
            tint = self._neon_tint(shp)
            base_w = max(_host_line_width(shp), self.width)
            # Kind in the key so circle+rect same tint never demotes the
            # world drawCircle / drawPoints fast path in _stroke_group_world.
            kind = _world_stroke_kind(shp) or "path"
            knobs = _host_stroke_knobs(shp)
            # Stroke types (Line, Track, open paths) keep a stroked body, as
            # _draw_body does for one shape: a closed Track filled its disk
            # once two Neon shapes drew as a group (showcase A12).
            key = (
                tint[0], tint[1], tint[2], round(base_w, 3), kind,
                knobs["cap"], knobs.get("join"), _is_line_shape(shp),
            )
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(shp)
        passes = _lod_passes()
        mask = _lod_mask(self._mask)
        for key in order:
            group = buckets[key]
            tint = (key[0], key[1], key[2], 1.0)
            kind = key[4]
            knobs = {"cap": key[5]}
            if key[6] is not None:
                knobs["join"] = key[6]
            base_w = max(_host_line_width(group[0]), self.width)
            # Hoist circle centers once across halo / body / core passes.
            centers = None
            if kind == "circle":
                centers = [_center_radius(s) for s in group]
            halo = self._stroke_paint(
                color=(tint[0], tint[1], tint[2], env),
                width=base_w * (2.0 + 1.2 * self.amount) * env,
                blend=BlendMode.ADD, mask=mask, **knobs,
            )
            _stroke_group_world(group, skia_canvas, halo, centers=centers)
            if kind == "line" or key[7]:
                w = max(_host_line_width(group[0]), 0.8)
                body = self._stroke_paint(color=tint, width=w, **knobs)
                _stroke_group_world(group, skia_canvas, body, centers=centers)
            else:
                fill = self._fill_paint_from(tint)
                _fill_group_world(group, skia_canvas, fill, centers=centers)
            if passes >= 3:
                core = self._stroke_paint(
                    color=(1.0, 1.0, 1.0, 0.9), width=max(0.8, base_w * 0.45),
                    blend=BlendMode.ADD, **knobs,
                )
                _stroke_group_world(group, skia_canvas, core, centers=centers)

    def _render(self, shape, skia_canvas) -> None:
        tint = self._neon_tint(shape)
        base_w = max(_host_line_width(shape), self.width)
        env = self._flicker_env()
        knobs = _host_stroke_knobs(shape)
        # Low + medium: body + ADD halo + thin white core.
        if fidelity_is_lite():
            self._draw_body(shape, skia_canvas, tint)
            _energy_survival_ladder(
                self, shape, skia_canvas, (tint[0], tint[1], tint[2], env),
                host_body=False,
                halo_width=base_w * (1.8 + 0.9 * self.amount) * env,
                core_width=max(0.8, base_w * 0.42),
                core_color=(1.0, 1.0, 1.0, 0.9),
                **knobs,
            )
            return
        # High / max: soft mask halo + body + white core.
        passes = _lod_passes()
        mask = _lod_mask(self._mask)
        halo = self._stroke_paint(
            color=(tint[0], tint[1], tint[2], env),
            width=base_w * (2.0 + 1.2 * self.amount) * env,
            blend=BlendMode.ADD, mask=mask, **knobs,
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=halo)
        self._draw_body(shape, skia_canvas, tint)
        if passes >= 3:
            core = self._stroke_paint(
                color=(1.0, 1.0, 1.0, 0.9), width=max(0.8, base_w * 0.45),
                blend=BlendMode.ADD, **knobs,
            )
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=core)


class MultiBorder(Recipe):
    """Widening outline strokes over the host body. Role B (outline).

    On ``Sprite``: blit + silhouette outline stack.

    Args:
        color: Line color.
        layers: How many borders (default 3).
        spread: Spacing between them (default 0.3).
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True

    def __new__(cls, color: Optional[ColorLike] = None, layers: int = 3, spread: float = 0.3):
        key = (
            "multiborder", _tint_intern_key(color, (0.45, 0.9, 1.0, 1.0)),
            int(layers), round(float(spread), 3),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, layers: int = 3, spread: float = 0.3):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.45, 0.9, 1.0, 1.0), channel=_TINT_OUTLINE)
        self.layers = max(1, min(int(layers), 4))
        self.spread = float(spread)
        self._ready = True

    def _unseed(self) -> Optional["MultiBorder"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.layers, self.spread)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("multiborder", ckey, self.layers, round(self.spread, 3))

    def _render(self, shape, skia_canvas) -> None:
        tint = self._primary_tint(shape)
        base_w = max(_host_line_width(shape), 1.2)
        step = max(2.5, 14.0 * self.spread)
        knobs = _host_stroke_knobs(shape)
        for i in range(self.layers, 0, -1):
            alpha = 0.12 + 0.28 * (1.0 - (i - 1) / max(self.layers, 1))
            paint = self._stroke_paint(
                color=tint, width=base_w + step * i, alpha=alpha, **knobs,
            )
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)
        shape._geometry_draw(skia_canvas)


class Extrude(Recipe):
    """Fake solid depth toward a vanishing point. Role A (body).

    On ``Sprite``: silhouette depth slabs, then the bitmap on top.

    Args:
        color: Solid color (default: follows the fill).
        depth: Percent of the way to the vanishing point (default 36).
        focus: Vanishing point; ``None`` = the global one (``set_extrude_focus``).
        layers: Slices (default 5).
        edges: Outline the side edges (default ``False``).
        darken: How much the side faces darken, 0–1 (default 0.42).
        angle: Fixed extrusion direction in degrees; ``None`` = toward the focus.
    """

    _color_role = "A"
    _allows_sprite = True
    _needs_sprite_path = True
    # The slabs reach a share of the way to the vanishing point: how far
    # depends on where the body is, with no bound. Never culled, and no batch
    # draws past it (Canvas Design, "Offscreen culling").
    _cull_outset = math.inf

    def __new__(
        cls,
        color=None,
        depth: float = 36.0,
        focus: Optional[Tuple[float, float]] = None,
        layers: int = 5,
        edges: bool = False,
        darken: float = 0.42,
        angle: Optional[float] = None,
    ):
        if focus is not None:
            from .validate import pair
            _fx, _fy = pair(focus, "Extrude focus")
            fkey = (round(_fx, 1), round(_fy, 1))
        elif angle is not None:
            fkey = ("angle", round(float(angle), 1))
        else:
            fkey = ("default",)  # uses live global focus; not cached angle
        key = (
            "extrude", _tint_intern_key(color, (0.45, 0.75, 0.95, 1.0)), round(float(depth), 1),
            fkey, int(layers), bool(edges), round(float(darken), 3),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(
        self,
        color=None,
        depth: float = 36.0,
        focus: Optional[Tuple[float, float]] = None,
        layers: int = 5,
        edges: bool = False,
        darken: float = 0.42,
        angle: Optional[float] = None,
    ):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.45, 0.75, 0.95, 1.0), channel=_TINT_BODY)
        self.depth = float(depth)
        from .validate import pair
        self.focus = None if focus is None else pair(focus, "Extrude focus")
        self.angle = None if angle is None else float(angle)
        self.layers = max(3, min(int(layers), 7))
        self.edges = bool(edges)
        self.darken = max(0.0, min(float(darken), 1.0))
        self._ready = True

    def _unseed(self) -> Optional["Extrude"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.depth, self.focus, self.layers, self.edges, self.darken, self.angle)

    @property
    def _use_host(self) -> bool:
        """True when look has no constructor seed (reads host fill live)."""
        return self._seed_color is None

    @property
    def _batch_key(self) -> tuple:
        if self.focus is not None:
            fkey = (round(self.focus[0], 1), round(self.focus[1], 1))
        elif self.angle is not None:
            fkey = ("angle", round(self.angle, 1))
        else:
            fkey = ("default",)
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return (
            "extrude", ckey, round(self.depth, 1), fkey, self.layers, self.edges,
            round(self.darken, 3),
        )

    def _focus_point(self) -> Tuple[float, float]:
        if self.focus is not None:
            return self.focus
        return _EXTRUDE_FOCUS

    def _depth_fraction(self) -> float:
        """depth as percent of the gap to the vanishing point (e.g. 36 → 36%)."""
        return max(0.04, min(0.9, float(self.depth) / 100.0))

    def _offset_toward_focus(self, cx: float, cy: float, t: float) -> Tuple[float, float]:
        """Offset ∝ distance to focus (god-rays-style sample along light path)."""
        if self.angle is not None:
            rad = math.radians(self.angle)
            return math.cos(rad) * self.depth * t, math.sin(rad) * self.depth * t
        fx, fy = self._focus_point()
        dx, dy = fx - cx, fy - cy
        mag = math.hypot(dx, dy)
        if mag < 1e-3:
            return 0.0, 0.0
        # Full vector to VP × fraction × step (farther shapes extrude farther)
        frac = self._depth_fraction()
        return dx * frac * t, dy * frac * t

    def _render(self, shape, skia_canvas) -> None:
        cx, cy, r = _center_radius(shape)
        host = self._primary_tint(shape)
        hr, hg, hb = float(host[0]), float(host[1]), float(host[2])
        ha = float(host[3]) if len(host) > 3 else 1.0
        n = self.layers
        # Survival (low) only: medium matches high full multipass.
        if fidelity_is_survival():
            n = min(n, 2)
        frac = self._depth_fraction() if self.angle is None else 0.35
        for i in range(n, 0, -1):
            t = i / n
            ox, oy = self._offset_toward_focus(cx, cy, t)
            k = 1.0 - self.darken * (0.35 + 0.65 * t)
            a = (0.5 + 0.4 * t) * ha
            paint = self._fill_paint_from((hr * k, hg * k, hb * k, a))
            # Shrink along path toward vanishing point
            s = max(0.18, 1.0 - frac * t * 0.75)
            skia_canvas.save()
            skia_canvas.translate(ox, oy)
            skia_canvas.translate(cx, cy)
            skia_canvas.scale(s, s)
            skia_canvas.translate(-cx, -cy)
            shape._geometry_draw(skia_canvas, fill_paint=paint, stroke_paint=None)
            skia_canvas.restore()

        if self.edges and not fidelity_is_survival():
            foot_x, foot_y = self._offset_toward_focus(cx, cy, 1.0)
            edge = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=1.0,
                Color4f=skia.Color4f(hr * 0.7, hg * 0.7, hb * 0.7, 0.45),
            )
            for x, y in _outline_points(shape, 8):
                skia_canvas.drawLine(x, y, x + foot_x, y + foot_y, edge)

        shape._geometry_draw(skia_canvas)


# ---------------------------------------------------------------------------
# Field / shell looks (Circle / Ellipse / Line outlines + best-effort)
# ---------------------------------------------------------------------------

class DashRing(Recipe):
    """Dashed dual-ring shell. Custom path for Circle/Ellipse/Line; best-effort else.

    On ``Sprite``: cached alpha silhouette (same family as Halo / Rim).

    Args:
        color: Ring color.
        speed: Spin speed.
        width: Dash thickness (default 2).
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True

    def __new__(cls, color: Optional[ColorLike] = None, speed: float = 1.0, width: float = 2.0):
        key = (
            "ff_shieldring", _tint_intern_key(color, (0.4, 0.9, 1.0, 1.0)),
            round(float(speed), 2), round(float(width), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, speed: float = 1.0, width: float = 2.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.4, 0.9, 1.0, 1.0), channel=_TINT_OUTLINE)
        self.speed = float(speed)
        self.width = float(width)
        self._ready = True

    def _unseed(self) -> Optional["DashRing"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.speed, self.width)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("ff_shieldring", ckey, round(self.speed, 2), round(self.width, 2))

    def _apply(self, shape) -> None:
        super()._apply(shape)
        _set_line_width(shape, self.width if self.width > 0 else _OUTLINE_RINGFIELD)

    def _render(self, shape, skia_canvas) -> None:
        knobs = _host_stroke_knobs(shape)
        if _forcefield_kind(shape) is None:
            _forcefield_best_effort(
                self, "rings", shape, skia_canvas, stroke_knobs=knobs,
            )
            return
        hue = _energy_rgb(self._primary_tint(shape))
        t = _clock() * self.speed
        # Use designed stroke widths on Lines too (not host-scaled outline mode).
        lm = "raw"
        # Low: one dashed rim on the real silhouette — core role, true hue.
        if fidelity_is_survival():
            pe = _ring_dash_pe(_ring_dash_phase(t))
            paint = self._stroke_paint(
                color=hue, width=max(1.0, self.width), blend=_energy_blend("core"),
                path_effect=pe, alpha=_ENERGY_CORE_A, **knobs,
            )
            _ff_draw_stroke(skia_canvas, shape, paint, 1.0, line_mode=lm)
            return
        # Medium: soft wash + main dash (core) + reverse outer (glow).
        if fidelity_is_lite():
            disc = self._fill_paint_from(hue, blend=_energy_blend("glow"), alpha=0.14)
            _ff_draw_fill(skia_canvas, shape, disc, 1.0)
            pe = _ring_dash_pe(_ring_dash_phase(t))
            main = self._stroke_paint(
                color=hue, width=self.width, blend=_energy_blend("core"),
                path_effect=pe, alpha=_ENERGY_CORE_A, **knobs,
            )
            _ff_draw_stroke(skia_canvas, shape, main, 1.0, line_mode=lm)
            pe2 = _ring_dash_pe(_ring_dash_phase(t, scale=-1.2))
            outer = self._stroke_paint(
                color=hue, width=max(0.8, self.width * 0.85), blend=_energy_blend("glow"),
                path_effect=pe2, alpha=0.42, **knobs,
            )
            _ff_draw_stroke(skia_canvas, shape, outer, 1.10, line_mode=lm)
            return
        # High: dual counter-rotating dashes (core + glow) + soft disc.
        disc = self._fill_paint_from(hue, blend=_energy_blend("glow"), alpha=0.14)
        _ff_draw_fill(skia_canvas, shape, disc, 1.0)
        for scale, role, ph_mul, a in ((1.0, "core", 1.0, _ENERGY_CORE_A), (1.12, "glow", -1.3, 0.46)):
            pe = _ring_dash_pe(_ring_dash_phase(t, scale=ph_mul))
            paint = self._stroke_paint(
                color=hue, width=self.width, blend=_energy_blend(role),
                path_effect=pe, alpha=a, **knobs,
            )
            _ff_draw_stroke(skia_canvas, shape, paint, scale, line_mode=lm)


# Halo / HaloFill / HaloSoft live in visuals.py.

class GearShell(Recipe):
    """Hot plasma shell + spinning rim (no interior plasma-disk shader).

    Primary tint: host fill (or line). ``color=`` seeds once at assignment.
    **Line:** wash + dashed rim (same at medium/high; no MaskFilter).
    **Closed (medium/high):** dual counter-rotating unfiltered dashes.
    **Closed (low):** same dashed rim as Line (not a static solid).
    Core/solid outline alpha is ``_CORE_A`` (80%). Continuum sweep on the
    outline at **high** only (medium/low stay solid tint).
    Stroke thickness is fixed in design units (tuned at circle r≈25).
    Inter-shell gaps grow with size at half the old percentage rate so
    large shapes keep readable spacing without the old wide separation.
    Dash intervals still scale with host size. ``amount`` multiplies width.
    On ``Sprite``: silhouette path (not the bounding ellipse).

    Args:
        color: Gear color.
        speed: Spin speed (default 1.2).
        amount: Strength.
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True

    _USE_SWEEP = True
    _CORE_A = 0.80
    # Width locked to circle r≈25. Gaps: blend fixed (that size) toward old %.
    _REF_HALF = 25.0
    _WIDTH_S = _REF_HALF / 36.0
    _GAP_GROW = 0.2  # 0 = fixed DU, 1 = old proportional scales
    _WASH_FRAC = -0.10       # was scale 0.90
    _WASH_FRAC_BE = -0.08    # best-effort was scale 0.92
    _OUTER_FRAC = 0.08       # was scale 1.08

    @classmethod
    def _radial_scale(cls, half: float, frac: float) -> float:
        """Uniform scale for a signed radius fraction (e.g. -0.10, +0.08).

        Offset is a blend of the r≈25 gap and the old ``frac * half`` gap.
        """
        h = max(float(half), 1.0)
        sign = 1.0 if float(frac) >= 0.0 else -1.0
        af = abs(float(frac))
        fixed = af * cls._REF_HALF
        prop = af * h
        offset = sign * (fixed + cls._GAP_GROW * (prop - fixed))
        return max(0.05, 1.0 + offset / h)

    def __new__(cls, color: Optional[ColorLike] = None, speed: float = 1.2, amount: float = 1.0):
        key = (
            "ff_shieldgear", _tint_intern_key(color, (0.55, 0.35, 1.0, 1.0)),
            round(float(speed), 2), round(float(amount), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, speed: float = 1.2, amount: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.55, 0.35, 1.0, 1.0), channel=_TINT_OUTLINE)
        self.speed = float(speed)
        self.amount = float(amount)
        self._ready = True

    def _unseed(self) -> Optional["GearShell"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.speed, self.amount)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("ff_shieldgear", ckey, round(self.speed, 2), round(self.amount, 2))

    def _apply(self, shape) -> None:
        super()._apply(shape)
        _set_line_width(shape, _OUTLINE_SHIELDGEAR)

    def _tint(self, shape):
        """Compat alias for primary_tint (best-effort plasma helper)."""
        return self._primary_tint(shape)

    def _sweep_shader(self, shape, tint, alpha: float, *, s: float, spin_t: float):
        """Light → dark → light sweep; local-matrix spin matches dash crawl.

        Do not use MakeSweep startAngle (wraps with a visible pop) and do not
        add host ``angle`` (dashes are path-phase, not pose).
        """
        kind = _forcefield_kind(shape)
        if kind == "line":
            x1, y1, x2, y2 = _line_ends(shape, 1.0)
            cx, cy = 0.5 * (x1 + x2), 0.5 * (y1 + y2)
        else:
            # Circle / ellipse / best-effort strokes are drawn in a local CTM.
            cx, cy = 0.0, 0.0
        base = _color_obj(tint).with_alpha(_clamp01(float(alpha)))
        light = base.lighter(0.22)
        dark = base.darker(0.22)
        colors = [
            skia.Color4f(*light.rgb),
            skia.Color4f(*dark.rgb),
            skia.Color4f(*light.rgb),
        ]
        # Same unwrapped path travel as DashPathEffect phase increment (55·s).
        path_len = max(_gear_outline_len(shape), 1.0)
        travel = float(spin_t) * 55.0 * max(0.35, float(s))
        angle = (travel / path_len) * 360.0
        shader = skia.GradientShader.MakeSweep(
            0.0, 0.0,
            colors,
            [0.0, 0.5, 1.0],
        )
        return _local_shader(shader, cx, cy, angle)

    def _rim_paint(
        self, shape, tint, *, width: float, blend, path_effect=None, alpha: float,
        s: float = 1.0, spin_t: float = 0.0,
    ) -> skia.Paint:
        if self._USE_SWEEP and not fidelity_is_lite():
            shader = self._sweep_shader(shape, tint, alpha, s=s, spin_t=spin_t)
            return self._stroke_paint(
                color=(1.0, 1.0, 1.0, 1.0), width=width, blend=blend,
                path_effect=path_effect, shader=shader,
            )
        return self._stroke_paint(
            color=tint, width=width, blend=blend,
            path_effect=path_effect, alpha=alpha,
        )

    def _draw_line_style_rim(
        self, shape, skia_canvas, tint, s: float, t: float, *, ff: bool,
    ) -> None:
        """Dashed rim used on Line at all qualities, and on closed shapes at low."""
        iv = (6.0, 4.0, 2.0, 4.0)
        pe = skia.DashPathEffect.Make(
            [x * s for x in iv],
            _plasma_dash_phase(t, s, iv),
        )
        ow = 1.6
        ws = self._WIDTH_S
        rim = self._rim_paint(
            shape, tint, width=max(1.6, 3.0 * ws) * ow,
            blend=_energy_blend("core"), path_effect=pe, alpha=self._CORE_A,
            s=s, spin_t=t,
        )
        if ff:
            lm = "raw" if _forcefield_kind(shape) == "line" else "outline"
            _ff_draw_stroke(skia_canvas, shape, rim, 1.0, line_mode=lm)
        else:
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=rim)

    def _render_line(self, shape, skia_canvas, tint, s: float, t: float) -> None:
        """Medium/high Line look (no MaskFilter high path)."""
        body = self._fill_paint_from(tint, blend=_energy_blend("glow"), alpha=0.14)
        _ff_draw_fill(skia_canvas, shape, body, 0.94, line_body=4.0)
        self._draw_line_style_rim(shape, skia_canvas, tint, s, t, ff=True)

    def _render_closed(
        self, shape, skia_canvas, tint, s: float, t: float, *, ff: bool, half: float,
    ) -> None:
        """Closed-shape outline. Low = Line dashed rim; medium/high = dual dashes."""
        amt = max(0.45, float(self.amount))
        amt1 = min(1.0, amt)
        wash = self._fill_paint_from(tint, blend=_energy_blend("glow"), alpha=0.14 * amt1)
        if ff:
            wash_sc = self._radial_scale(half, self._WASH_FRAC)
            _ff_draw_fill(skia_canvas, shape, wash, wash_sc)
        else:
            wash_sc = self._radial_scale(half, self._WASH_FRAC_BE)
            _ff_best_effort_pass(
                shape, skia_canvas, fill_paint=wash, stroke_paint=None, scale=wash_sc,
            )

        if fidelity_is_survival():
            self._draw_line_style_rim(shape, skia_canvas, tint, s, t, ff=ff)
            return

        ws = self._WIDTH_S
        iv = (5.0, 3.0, 2.0, 3.0)
        pe = skia.DashPathEffect.Make(
            [x * s for x in iv],
            _plasma_dash_phase(t * 1.15, s, iv),
        )
        rim_w = max(2.2, 3.8 * ws) * amt
        rim = self._rim_paint(
            shape, tint, width=rim_w, blend=_energy_blend("core"),
            path_effect=pe, alpha=self._CORE_A * amt1,
            s=s, spin_t=t * 1.15,
        )
        if ff:
            _ff_draw_stroke(skia_canvas, shape, rim, 1.0)
        else:
            _ff_best_effort_pass(shape, skia_canvas, fill_paint=None, stroke_paint=rim)

        iv2 = (4.0, 5.0, 2.5, 4.0)
        pe2 = skia.DashPathEffect.Make(
            [x * s for x in iv2],
            _plasma_dash_phase(t * -1.35, s, iv2),
        )
        outer = self._rim_paint(
            shape, tint, width=max(1.4, 2.6 * ws) * amt, blend=_energy_blend("glow"),
            path_effect=pe2, alpha=0.42 * amt1,
            s=s, spin_t=t * -1.35,
        )
        outer_sc = self._radial_scale(half, self._OUTER_FRAC)
        if ff:
            _ff_draw_stroke(skia_canvas, shape, outer, outer_sc)
        else:
            _ff_best_effort_pass(
                shape, skia_canvas, fill_paint=None, stroke_paint=outer, scale=outer_sc,
            )

    def _render(self, shape, skia_canvas) -> None:
        kind = _forcefield_kind(shape)
        tint = _energy_rgb(self._primary_tint(shape))
        half = _ff_shader_half(shape)
        s = max(0.45, float(half) / 36.0)
        t = _clock() * self.speed
        if kind == "line":
            self._render_line(shape, skia_canvas, tint, s, t)
            return
        if kind is None:
            self._render_closed(shape, skia_canvas, tint, s, t, ff=False, half=half)
            return
        self._render_closed(shape, skia_canvas, tint, s, t, ff=True, half=half)


class _ElectricFieldHigh(GlowRimVisual):
    """High-only ElectricField: GPU Blur halo + Discrete-PE rim/spine."""

    _VARIANT = "ff_elec_high"
    _DEFAULT_TINT = (0.55, 0.85, 1.0, 1.0)
    _USE_WASH = True
    _RIM_WIDTH = 0.0

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 5.0, speed: float = 1.0):
        return GlowRimVisual.__new__(
            cls, color, amount=1.0, density=amount, speed=speed,
        )

    @classmethod
    def _intern_extra(cls, kw: dict) -> tuple:
        return (
            round(float(kw.get("density", kw.get("amount", 5.0))), 1),
            round(float(kw.get("speed", 1.0)), 2),
        )

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 5.0, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_glowrim(color, amount=1.0)
        self.amount = float(amount)
        self.speed = float(speed)
        self._ready = True

    def _draw_character(self, shape, skia_canvas, rgb, *, glow_batched=False) -> None:
        # Same flicker rate at medium and high (do not cap on lite pe_hz).
        seed = _pe_seed(14.0 * self.speed, cap=False)
        if _is_line_shape(shape):
            pe = _line_discrete_pe(self.amount, seed)
            halo_w = _stroke_width_for_shape(shape, 1.7, mode="shock")
            spine_w = _stroke_width_for_shape(shape, 1.15, mode="shock")
        else:
            pe = _discrete_pe(max(3.0, self.amount * 0.4), self.amount, seed)
            halo_w = 1.7
            spine_w = 1.15
        rim_rgb = _aura_lift_rgb(_aura_mix_hot(rgb, self._RIM_HOT), self._RIM_LIFT)
        spine_rgb = _aura_lift_rgb(_aura_mix_hot(rgb, self._SPINE_HOT), self._SPINE_LIFT)
        rim = self._rim_skia_paint(rim_rgb, 1.0, halo_w, path_effect=pe)
        self._stroke_at_scale(shape, skia_canvas, rim, self._RIM_SCALE)
        spine = self._rim_skia_paint(spine_rgb, 1.0, spine_w, path_effect=pe)
        self._stroke_at_scale(shape, skia_canvas, spine, self._SPINE_SCALE)

    def _draw_extra_rim(self, shape, skia_canvas) -> None:
        return


class ElectricField(Recipe):
    """Arcing electric shell. Custom path for Circle/Ellipse/Line; best-effort else.

    On ``Sprite``: ellipse fitted to the sprite rectangle (not an edge map).

    **Low:** host plus one ADD Discrete-PE stroke (no blur).
    **Medium:** batched ``Blur`` GlowRim, thin cores.
    **High:** batched ``Blur`` GlowRim + one shared overlay PE-glow plate
    (Plus ``Blur`` σ 2.2); thin cores stay unfiltered after the bloom.

    Args:
        color: Arc color.
        amount: Density (default 5).
        speed: Flicker frequency.
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True

    _fidelity_sensitive = True
    # *2 / *3 keep the old Recipe survival ladder at low.
    _SURVIVAL_CHEAP_LINE = True

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 5.0, speed: float = 1.0):
        key = (
            "ff_elec", _tint_intern_key(color, (0.55, 0.85, 1.0, 1.0)),
            round(float(amount), 1), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 5.0, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.55, 0.85, 1.0, 1.0), channel=_TINT_OUTLINE)
        self.amount = float(amount)
        self.speed = float(speed)
        self._med = _ElectricFieldHigh3(color, amount=amount, speed=speed)
        self._high = _ElectricFieldHigh2(color, amount=amount, speed=speed)
        self._ready = True

    def _unseed(self) -> Optional["ElectricField"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("ff_elec", ckey, round(self.amount, 1), round(self.speed, 2))

    def _glowrim(self):
        """Active GlowRim package, or None at survival."""
        if fidelity_is_survival():
            return None
        if fidelity_is_lite():
            return getattr(self, "_med", None) or self._high
        return self._high

    @property
    def _is_multipass(self) -> bool:
        return self._glowrim() is None

    def _overlay_after_filters(self, shape, skia_canvas, *, glow_batched=False) -> None:
        gr = self._glowrim()
        if gr is None:
            return
        gr._overlay_after_filters(shape, skia_canvas, glow_batched=glow_batched)

    @property
    def _overlay_glow_batch(self) -> bool:
        """High only: PE bloom is a shared Plus plate, not N ``saveLayer``s."""
        return self._glowrim() is getattr(self, "_high", None)

    @property
    def _overlay_glow_sigma(self) -> float:
        return float(getattr(self._high, "_overlay_glow_sigma", 2.2))

    def _emit_overlay_glow(self, shape, skia_canvas) -> None:
        gr = self._glowrim()
        fn = getattr(gr, "_emit_overlay_glow", None) if gr is not None else None
        if callable(fn):
            fn(shape, skia_canvas)

    def _overlay_glow_layer_bounds(self, shapes):
        gr = self._glowrim()
        fn = getattr(gr, "_overlay_glow_layer_bounds", None) if gr is not None else None
        if callable(fn):
            return fn(shapes)
        return None

    def _apply(self, shape) -> None:
        gr = self._glowrim()
        if gr is None:
            self._unwind_high_package(shape)
            super()._apply(shape)
            return
        gr._apply(shape)

    def _unwind_high_package(self, shape) -> None:
        """Drop high wash/blur leftovers so the original Recipe path sees host paint."""
        from .style import BlendMode

        cached = getattr(shape, "_glowrim_host_tint", None)
        if cached is not None:
            r, g, b, a = (float(cached[0]), float(cached[1]), float(cached[2]), float(cached[3]))
            if is_stroke_type(shape):
                shape.fill = None
                shape.line = Color(r, g, b, a)
            else:
                shape.fill = Color(r, g, b, a)
        try:
            shape.fill_filter = None
            shape.line_filter = None
        except Exception:
            pass
        try:
            shape.blend = BlendMode.NORMAL
        except Exception:
            pass

    def _render(self, shape, skia_canvas) -> None:
        gr = self._glowrim()
        if gr is not None:
            _apply_at_draw(shape, gr._apply, shape)
            gr._render(shape, skia_canvas)
            return
        if self._SURVIVAL_CHEAP_LINE:
            _draw_electric_add_line(
                self, shape, skia_canvas, amount=self.amount, speed=self.speed,
            )
            return
        if _forcefield_kind(shape) is None:
            _forcefield_best_effort(self, "electric", shape, skia_canvas)
            return
        tint = self._primary_tint(shape)
        if _is_line_shape(shape):
            _energy_survival_ladder(
                self, shape, skia_canvas, tint,
                host_body=True,
                halo_width=_stroke_width_for_shape(shape, 2.4, mode="outline"),
                core_width=_stroke_width_for_shape(shape, 0.75, mode="outline"),
                core_color=(1.0, 1.0, 0.75, 0.9),
                ff=False,
            )
        else:
            _energy_survival_ladder(
                self, shape, skia_canvas, tint,
                wash_alpha=0.10, wash_scale=0.88,
                halo_width=3.2,
                core_width=0.85,
                core_color=(1.0, 1.0, 0.75, 0.9),
                ff=True,
            )


class _ElectricFieldHigh2(_ElectricFieldHigh):
    """GlowRim ElectricField with the old Recipe bloom + thin cores.

    Batched GPU ``Blur`` stays on the silhouette. Overlay: GPU-blurred PE
    glow (MaskFilter σ 2.2, width 3.5) then yellow 1.6 + white 0.7.
    Consecutive peers share one Plus ``saveLayer`` when filter batching is on.
    """

    _VARIANT = "ff_elec_high2"
    _HIGH_WASH = 0.09
    _HIGH_CORE_A = 0.88
    _HIGH_SIGMA = 3.8
    _HIGH_WIDTH = 3.5
    _HIGH_HOT = 0.08
    _OVERLAY_BLEND_ADD = True
    _overlay_glow_batch = True
    _overlay_glow_sigma = 2.2
    _OVERLAY_GLOW_WIDTH = 3.5

    def _halo_rgb(self, rgb):
        return _energy_spark_rgb(rgb, 0.08)

    def _shock_stack_args(self, shape, rgb):
        seed = _pe_seed(14.0 * self.speed, cap=False)
        if _is_line_shape(shape):
            pe = _line_discrete_pe(self.amount, seed)
            glow_w = _stroke_width_for_shape(shape, 3.5, mode="shock")
            mid_w = _stroke_width_for_shape(shape, 1.6, mode="shock")
            core_w = _stroke_width_for_shape(shape, 0.7, mode="shock")
        else:
            pe = _discrete_pe(max(3.0, self.amount * 0.4), self.amount, seed)
            glow_w = 3.5
            mid_w = 1.6
            core_w = 0.7
        return dict(
            rgb=rgb, pe=pe, glow_w=glow_w, mid_w=mid_w, core_w=core_w,
            glow_a=1.0, mid_rgb=(1.0, 1.0, 0.55), mid_a=0.75, core_a=0.95,
            blur_sigma=2.2,
        )

    def _overlay_glow_layer_bounds(self, shapes):
        return _union_overlay_glow_bounds(
            shapes, self._overlay_glow_sigma, self._OVERLAY_GLOW_WIDTH,
        )

    def _emit_overlay_glow(self, shape, skia_canvas) -> None:
        rgb = self._halo_rgb(self._tint_rgba(shape)[:3])

        def _stroke():
            args = self._shock_stack_args(shape, rgb)
            if float(args["glow_w"]) <= 0.05:
                return
            glow = self._rim_skia_paint(
                rgb, float(args["glow_a"]), float(args["glow_w"]),
                path_effect=args["pe"],
            )
            self._stroke_at_scale(shape, skia_canvas, glow, 1.0)

        self._with_filters_stripped(shape, _stroke)

    def _draw_character(self, shape, skia_canvas, rgb, *, glow_batched=False) -> None:
        args = self._shock_stack_args(shape, rgb)
        _draw_shock_pe_stack(
            self, shape, skia_canvas,
            blur_glow=not glow_batched, skip_glow=glow_batched,
            **args,
        )


class _ElectricFieldHigh3(_ElectricFieldHigh):
    """Fast GlowRim ElectricField: stronger batched bloom, thin unfiltered cores.

    Same path as the last cheap field ladder (no per-stroke saveLayer).
    Glow is lifted with interned ``Blur`` knobs only (brighter / wider plate).
    Overlay is the old thin yellow 1.6 + white 0.7 — no fat PE stroke.
    """

    _VARIANT = "ff_elec_high3"
    _HIGH_WASH = 0.09
    _HIGH_CORE_A = 0.8
    _HIGH_SIGMA = 2.0
    _HIGH_WIDTH = 3.5
    _HIGH_HOT = 0.16
    _OVERLAY_BLEND_ADD = True

    def _halo_rgb(self, rgb):
        return _energy_spark_rgb(rgb, 0.18)

    def _draw_character(self, shape, skia_canvas, rgb, *, glow_batched=False) -> None:
        seed = _pe_seed(14.0 * self.speed, cap=False)
        if _is_line_shape(shape):
            pe = _line_discrete_pe(self.amount, seed)
            mid_w = _stroke_width_for_shape(shape, 1.6, mode="shock")
            core_w = _stroke_width_for_shape(shape, 0.7, mode="shock")
        else:
            pe = _discrete_pe(max(3.0, self.amount * 0.4), self.amount, seed)
            mid_w = 1.6
            core_w = 0.7
        # Thin cores only — glow lives on the batched Blur plate.
        _draw_shock_pe_stack(
            self, shape, skia_canvas, rgb, pe,
            glow_w=0.0, mid_w=mid_w, core_w=core_w,
            mid_rgb=(1.0, 1.0, 0.55), mid_a=0.75, core_a=0.95,
            blur_glow=False,
        )


class Shield(CompiledVisual):
    """Orb energy shields — SkSL body + batchable GlowFilter soft halo.

    On ``Sprite``: ellipse fitted to the frozen silhouette-union envelope
    (all sheet frames, design-unit AABBs) × ``shield_scale`` (default 1.4);
    the bitmap stays visible (costume around the image, not a body replace).
    Clip switches do not resize the shell. Electric* still hug the live
    silhouette.

    Styles:
      bubble  — hollow soap film (lime blotches; green-compatible rim)
      nebula  — soft multi-hue mist (classic palette)
      ember   — warm nebula variant
      void    — cool nebula variant
      molten  — fixed fire ramp
      bands   — gas-planet belts; primary tint (``color=`` / host at assign)
      vortex  — spin filaments; lighter high-mode glow; primary tint (+ dashed rim)
      cracks  — magma fissures
      frost   — icy cracks variant
      plasma  — compiled plasma shell (delegates to :class:`~scena.visuals._OrbHalo`)

    Soft outer glow uses interned :class:`~scena.filters.GlowFilter` (filter-
    batchable) for fixed-hue styles. Tinted styles (``bands`` / ``vortex``)
    use interned :class:`~scena.filters.HostGlow` at high so mixed host tints
    share one ``_batch_key`` (GlowFilter tint is in the DAG).
    One style rim on ``line``. Multi-rim ADD stacks from the old Recipe path
    are dropped for fleet FPS.

    At **medium / low**, drops the glow filter (procedural body + rim only) —
    same gate as :class:`~scena.visuals._OrbHalo`.

    Constructor: ``Shield(color=None, *, style="bubble", amount=1.0, speed=1.0)``.
    ``style`` is keyword-only so a positional first argument is always the tint seed.

    Colour, by style: ``bands`` / ``vortex`` / ``plasma`` follow the shape's
    color (tint looks); ``bubble`` is a palette look — its own lime film
    without ``color``, the palette rotated onto ``color`` with it, and
    ``set_color`` retints it (like :class:`Metal`); the other styles paint
    their own palette and take no color (Role D).
    """

    _fidelity_sensitive = True
    _allows_sprite = True

    _styles = SHIELD_STYLES
    _TINTED = frozenset({"bands", "vortex"})
    # Palette looks: own palette without color=, rotated onto color= with it.
    _PALETTE_TINTED = frozenset({"bubble"})
    _NEBULA_FAMILY = frozenset({"nebula", "ember", "void"})
    _CRACKS_FAMILY = frozenset({"cracks", "frost"})

    _FILL_KIND = {
        "bubble": "shield_bubble",
        "nebula": "shield_nebula_mist",
        "ember": "shield_nebula_mist",
        "void": "shield_nebula_mist",
        "molten": "shield_molten",
        "bands": "shield_bands",
        "vortex": "shield_vortex",
        "cracks": "shield_cracks",
        "frost": "shield_cracks",
    }

    _DEFAULT_TINT = {
        "bands": (0.08, 0.55, 0.52, 1.0),
        "vortex": (1.0, 0.3, 0.75, 1.0),
    }

    _RIM_FIXED = {
        "bubble": (0.42, 0.88, 0.18, 1.0),
        "molten": (1.0, 0.9, 0.25, 1.0),
    }

    # shield_bubble film (u_lime / u_yell / u_film) and rim. ``lime`` is the
    # slot a tint lands on; the others keep their hue / saturation / value
    # offsets from it (_shift_palette). No color = these values, exactly.
    _BUBBLE_PALETTE = {
        "lime": (0.26, 0.84, 0.07),
        "yell": (0.78, 0.92, 0.10),
        "film": (0.38, 0.82, 0.18),
        "rim": (0.42, 0.88, 0.18),
    }

    _NEBULA_PALETTES = {
        "classic": {
            "deep": (0.12, 0.02, 0.28),
            "mid": (0.45, 0.1, 0.65),
            "star": (1.0, 0.35, 0.85),
            "shell": (0.35, 0.95, 1.0),
            "rim": (0.35, 0.95, 1.0, 1.0),
        },
        "ember": {
            "deep": (0.18, 0.02, 0.02),
            "mid": (0.55, 0.12, 0.05),
            "star": (1.0, 0.65, 0.2),
            "shell": (1.0, 0.85, 0.35),
            "rim": (1.0, 0.8, 0.3, 1.0),
        },
        "void": {
            "deep": (0.02, 0.04, 0.12),
            "mid": (0.08, 0.15, 0.35),
            "star": (0.75, 0.9, 1.0),
            "shell": (0.45, 0.55, 0.95),
            "rim": (0.55, 0.65, 1.0, 1.0),
        },
    }

    # rock / dark / lava / spar paint the body (shield_cracks shader); shell
    # tints the edge. Frost once shared magma's body: only its rim was icy.
    _CRACKS_PALETTES = {
        "magma": {
            "rock": (0.12, 0.04, 0.02), "dark": (0.28, 0.08, 0.04),
            "lava": (1.0, 0.4, 0.05), "spar": (1.0, 0.85, 0.25),
            "shell": (1.0, 0.72, 0.22),
            "rim": (1.0, 0.75, 0.3, 1.0),
            "rim_hot": (1.0, 0.95, 0.55, 0.6),
        },
        "frost": {
            "rock": (0.03, 0.08, 0.16), "dark": (0.10, 0.24, 0.40),
            "lava": (0.35, 0.75, 1.0), "spar": (0.88, 0.97, 1.0),
            "shell": (0.45, 0.85, 1.0),
            "rim": (0.5, 0.9, 1.0, 1.0),
            "rim_hot": (0.85, 0.95, 1.0, 0.45),
        },
    }

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        *,
        style: ShieldStyle = "bubble",
        amount: float = 1.0,
        speed: float = 1.0,
    ):
        st = cls._normalize_style(style)
        if (color is not None and st != "plasma" and st not in cls._TINTED
                and st not in cls._PALETTE_TINTED):
            # A fixed-hue style paints its own palette: the color would change
            # nothing (KN4, 2026-10-12; before, it was taken and ignored).
            raise TypeError(
                f'Shield(style="{st}") paints its own colors and takes no color. '
                f'A tinted shield is style="bubble", "bands", "vortex" or "plasma": '
                f'Shield({color!r}, style="bubble"); or drop the color.'
            )
        if st == "plasma":
            from .visuals import _OrbHalo
            return _OrbHalo(color, amount=amount, speed=speed)
        if st in cls._TINTED:
            ckey = _tint_intern_key(color, cls._DEFAULT_TINT[st])
        elif st in cls._PALETTE_TINTED and color is _FOLLOW_SHAPE:
            ckey = ("host",)
        elif st in cls._PALETTE_TINTED and color is not None:
            ckey = tuple(round(c, 3) for c in _resolve_color(color, cls._RIM_FIXED[st]))
        else:
            ckey = ("fixed",)
        key = (
            "shield_orb", st, ckey,
            round(float(amount), 2), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    @classmethod
    def _normalize_style(cls, style: str) -> str:
        return expect_choice(style, SHIELD_STYLES, what="Shield style")

    @classmethod
    def _style_palette_key(cls, style: str) -> str:
        if style == "nebula":
            return "classic"
        if style in ("ember", "void"):
            return style
        if style == "cracks":
            return "magma"
        if style == "frost":
            return "frost"
        return ""

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        style: ShieldStyle = "bubble",
        amount: float = 1.0,
        speed: float = 1.0,
    ):
        if getattr(self, "_ready", False):
            return
        self.style = self._normalize_style(style)
        self.amount = float(amount)
        self.speed = float(speed)
        self._follows_shape = color is _FOLLOW_SHAPE
        if self.style in self._PALETTE_TINTED:
            self._seed_color = (
                None if color is None or self._follows_shape
                else _resolve_color(color, self._RIM_FIXED[self.style])
            )
            self.color = self._bubble_rim(self._seed_color)
        elif self.style in self._TINTED:
            default = self._DEFAULT_TINT[self.style]
            if color is None:
                self._seed_color = None
                self.color = default
            else:
                self._seed_color = _resolve_color(color, default)
                self.color = self._seed_color
        else:
            self._seed_color = None
            self.color = self._RIM_FIXED.get(self.style, (0.5, 0.5, 0.5, 1.0))
            if self.style in self._NEBULA_FAMILY:
                pal_key = self._style_palette_key(self.style)
                pal = self._NEBULA_PALETTES.get(pal_key) or self._NEBULA_PALETTES["classic"]
                self.color = pal["rim"]
            elif self.style in self._CRACKS_FAMILY:
                pal_key = self._style_palette_key(self.style)
                pal = self._CRACKS_PALETTES.get(pal_key) or self._CRACKS_PALETTES["magma"]
                self.color = pal["rim"]
        # A (set_color shows): tint looks and the palette look; D: own palette only.
        if self.style in self._TINTED or self.style in self._PALETTE_TINTED:
            self._color_role = "A"
        else:
            self._color_role = "D"
        self._ready = True

    def __repr__(self) -> str:
        return (
            f"Shield(style={self.style!r}, amount={self.amount}, speed={self.speed})"
            f"  # styles: {', '.join(SHIELD_STYLES)}"
        )

    @property
    def _batch_key(self) -> tuple:
        if self.style in self._TINTED:
            ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        elif self._follows_shape:
            ckey = ("host",)
        elif self._seed_color is not None:
            ckey = tuple(round(c, 3) for c in self._seed_color)
        else:
            ckey = ("fixed",)
        return (
            "shield_orb", self.style, ckey,
            round(self.amount, 2), round(self.speed, 2),
        )

    def _unseed(self) -> Optional["Shield"]:
        if self.style in self._TINTED:
            if self._seed_color is None:
                return None
            return type(self)(None, style=self.style, amount=self.amount, speed=self.speed)
        # Palette look: set_color moves to the shape-following sibling (one
        # interned instance for every colour), never back to the lime palette,
        # which would drop the colour just written.
        if self.style not in self._PALETTE_TINTED or self._follows_shape:
            return None
        return type(self)(_FOLLOW_SHAPE, style=self.style, amount=self.amount, speed=self.speed)

    @classmethod
    def _bubble_rim(cls, tint) -> Tuple[float, float, float, float]:
        if tint is None:
            return cls._RIM_FIXED["bubble"]
        return (*_shift_palette(cls._BUBBLE_PALETTE, "lime", tint)["rim"], 1.0)

    def _palette_tint(self, shape) -> Optional[Tuple[float, float, float]]:
        """Palette look: seed, live shape color (recolor sibling), or None (own palette)."""
        if self._seed_color is not None:
            return tuple(float(c) for c in self._seed_color[:3])
        if not self._follows_shape:
            return None
        live = sample_body_rgba(shape)
        if live is not None:
            return (float(live[0]), float(live[1]), float(live[2]))
        # Re-apply over our own film: the tint is stored on it.
        fill = getattr(shape, "_fill", None)
        pc = getattr(fill, "_color", None)
        if pc is not None and len(pc) >= 3:
            return (float(pc[0]), float(pc[1]), float(pc[2]))
        return None

    def _primary_tint(self, shape) -> Tuple[float, float, float, float]:
        """Host / seed / default tint (compat with Recipe shell looks)."""
        if self.style in self._PALETTE_TINTED:
            return self._rim_rgba(shape)
        if self.style not in self._TINTED:
            return tuple(float(c) for c in self.color)
        live = sample_body_rgba(shape)
        if live is not None:
            return live
        # ProceduralFill after apply — read stored RGB
        fill = getattr(shape, "_fill", None) or getattr(shape, "fill", None)
        pc = getattr(fill, "_color", None) if fill is not None else None
        if pc is not None and len(pc) >= 3:
            return (float(pc[0]), float(pc[1]), float(pc[2]), 1.0)
        if self._seed_color is not None:
            return self._seed_color
        return self._DEFAULT_TINT[self.style]

    def _rim_rgba(self, shape) -> Tuple[float, float, float, float]:
        if self.style in self._TINTED:
            return self._primary_tint(shape)
        if self.style in self._PALETTE_TINTED:
            return self._bubble_rim(self._palette_tint(shape))
        if self.style in self._NEBULA_FAMILY:
            pal_key = self._style_palette_key(self.style)
            pal = self._NEBULA_PALETTES.get(pal_key) or self._NEBULA_PALETTES["classic"]
            return pal["rim"]
        if self.style in self._CRACKS_FAMILY:
            pal_key = self._style_palette_key(self.style)
            pal = self._CRACKS_PALETTES.get(pal_key) or self._CRACKS_PALETTES["magma"]
            return pal["rim"]
        return self._RIM_FIXED.get(self.style, (0.8, 0.9, 1.0, 1.0))

    def _sample_tint_rgb(self, shape) -> Tuple[float, float, float]:
        """RGB for procedural / glow at apply time.

        On quality re-apply the host solid is already a ProceduralFill — read its
        stored tint instead of falling back to style defaults (vortex → magenta).
        """
        if self.style in self._TINTED:
            if self._seed_color is not None:
                return self._seed_color[:3]
            live = sample_body_rgba(shape)
            if live is not None:
                return live[:3]
            fill = getattr(shape, "_fill", None) or getattr(shape, "fill", None)
            pc = getattr(fill, "color", None) or getattr(fill, "_color", None)
            if pc is not None and len(pc) >= 3:
                return (float(pc[0]), float(pc[1]), float(pc[2]))
            return self._DEFAULT_TINT[self.style][:3]
        rim = self._rim_rgba(shape)
        return rim[:3]

    def _apply(self, shape) -> None:
        from .style import BlendMode, ProceduralFill, DashStyle
        from .fx_quality import fidelity_is_lite

        is_line = is_stroke_type(shape)
        inten = max(0.35, min(2.0, float(self.amount)))
        rgb = self._sample_tint_rgb(shape)
        rim = self._rim_rgba(shape)
        # Prefer sampled rgb for tinted glow; rim for fixed styles
        glow_rgb = rgb if self.style in self._TINTED else rim[:3]

        glow = None
        if not fidelity_is_lite():
            # bands/vortex: HostGlow (hue not in DAG → fleets batch).
            # Other styles keep GlowFilter (fixed/shared tint).
            if self.style == "vortex":
                glow = HostGlow(
                    sigma=max(1.0, 1.6 * (0.9 + 0.15 * inten)),
                    spread=max(0.2, 0.4 * inten),
                )
            elif self.style in self._TINTED:
                glow = HostGlow(
                    sigma=max(2.0, 4.5 * (0.9 + 0.15 * inten)),
                    spread=max(0.5, 1.2 * inten),
                )
            else:
                glow = GlowFilter(
                    radius=14.0 * (0.9 + 0.2 * inten),
                    sigma=8.0 * (0.95 + 0.15 * inten),
                    intensity=0.7 + 0.4 * inten,
                    color=(*glow_rgb, 1.0),
                )

        if is_line:
            shape.fill = None
            shape.line = Color(
                glow_rgb[0], glow_rgb[1], glow_rgb[2],
                min(1.0, 0.9 * inten),
            )
            _set_line_width(shape, _OUTLINE_SHIELD)
            shape.fill_filter = None
            shape.line_filter = glow
            shape.blend = BlendMode.NORMAL
            return

        kind = self._FILL_KIND[self.style]
        if self.style in self._TINTED:
            fill = ProceduralFill(
                kind=kind, amount=inten, speed=self.speed, color=rgb,
            )
        else:
            fill = ProceduralFill(kind=kind, amount=inten, speed=self.speed)
            if self.style in self._PALETTE_TINTED:
                tint = self._palette_tint(shape)
                if tint is None:
                    fill._extra_rgb = dict(self._BUBBLE_PALETTE)
                else:
                    fill._extra_rgb = _shift_palette(self._BUBBLE_PALETTE, "lime", tint)
                    fill._color = tint      # read back on a re-apply over this film
            elif self.style in self._NEBULA_FAMILY:
                pal_key = self._style_palette_key(self.style)
                pal = self._NEBULA_PALETTES.get(pal_key) or self._NEBULA_PALETTES["classic"]
                fill._extra_rgb = {
                    "deep": pal["deep"], "mid": pal["mid"],
                    "star": pal["star"], "shell": pal["shell"],
                }
            elif self.style in self._CRACKS_FAMILY:
                pal_key = self._style_palette_key(self.style)
                pal = self._CRACKS_PALETTES.get(pal_key) or self._CRACKS_PALETTES["magma"]
                fill._extra_rgb = {k: pal[k] for k in ("rock", "dark", "lava", "spar", "shell")}

        shape.fill = fill
        try:
            rim_a = 0.88 if self.style == "bubble" else 0.65
            shape.line = Color(rim[0], rim[1], rim[2], rim_a)
        except Exception:
            pass
        _set_line_width(shape, _OUTLINE_SHIELD)
        # Vortex: dashed rim as a cheap stand-in for multipass dash rings
        try:
            shape.dash = DashStyle.DOT_DASH if self.style == "vortex" else DashStyle.SOLID
        except Exception:
            pass
        shape.line_filter = None
        shape.fill_filter = glow
        shape.blend = BlendMode.NORMAL

    def _identity_patch(self, shape) -> None:
        seed = getattr(self, "_seed_color", None)
        if seed is None:
            return
        fn = getattr(shape, "_identity_patch_seed", None)
        if fn is not None:
            fn(seed, channel="auto")

    def _render(self, shape, skia_canvas) -> None:
        shape._geometry_draw(skia_canvas)


class HaloLine(Halo):
    """Glowing outline only — Shield-cloud rim + HostGlow, no plasma fill.

    Role B (outline). Drops the interior so the look is a host-tinted stroke.
    """

    _color_role = "B"

    _fidelity_sensitive = True
    _tint_channel = _TINT_OUTLINE
    _DEFAULT_TINT = (0.45, 0.95, 0.25, 1.0)
    _render_sprite_body = None  # keep HostGlow outline; do not use hollow/fill SDF path
    _needs_sprite_path = False
    _needs_sprite_sdf = False

    @property
    def _is_multipass(self) -> bool:
        return False

    def _overlay_after_filters(self, shape, skia_canvas) -> None:
        return

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0):
        key = (
            "line_glow", _tint_intern_key(color, cls._DEFAULT_TINT),
            round(float(amount), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0, *, style="line",
                 rings: int = 3, speed: float = 1.0):
        # rings / speed: Halo(style="line", ...) passes them on; Halo.__new__
        # already refused any but the defaults (they drive style="pulse").
        if getattr(self, "_ready", False):
            return
        self.amount = float(amount)
        default = self._DEFAULT_TINT
        if color is None:
            self._seed_color = None
            self.color = default
        else:
            self._seed_color = _resolve_color(color, default)
            self.color = self._seed_color
        inten = max(0.35, min(2.0, float(amount)))
        self._glow = HostGlow(
            sigma=max(2.0, 4.5 * (0.9 + 0.15 * inten)),
            spread=max(0.5, 1.2 * inten),
        )
        self._ready = True

    def _unseed(self) -> Optional["HaloLine"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("line_glow", ckey, round(self.amount, 2))

    def _primary_tint(self, shape) -> Tuple[float, float, float, float]:
        if self._seed_color is not None:
            return self._seed_color
        live = sample_outline_rgba(shape)
        if live is not None:
            return live
        return self._DEFAULT_TINT

    def _identity_patch(self, shape) -> None:
        seed = getattr(self, "_seed_color", None)
        if seed is None:
            return
        fn = getattr(shape, "_identity_patch_seed", None)
        if fn is not None:
            fn(seed, channel="auto")

    def _apply(self, shape) -> None:
        from .fx_quality import fidelity_is_lite

        inten = max(0.35, min(2.0, float(self.amount)))
        rgb = self._primary_tint(shape)[:3]
        glow = None if fidelity_is_lite() else self._glow
        shape.fill = None
        shape.line = Color(
            rgb[0], rgb[1], rgb[2],
            min(1.0, 0.9 * inten),
        )
        _set_line_width(shape, _OUTLINE_SHIELD)
        shape.fill_filter = None
        shape.line_filter = glow
        shape.blend = BlendMode.NORMAL

    def _render(self, shape, skia_canvas) -> None:
        shape._geometry_draw(skia_canvas)


# Note: ``_OrbHalo`` lives in ``visuals.py`` (compiled GlowFilter).
# ``HaloSoft`` is compiled HostGlow (shared source-blur; mixed tints still batch).
# ``Halo`` / ``HaloFill`` medium is filterless ADD (solo); high is Blur + rim.
# ``HaloLine`` is the former Shield cloud rim (no plasma fill).


class OrganicOutline(Recipe):
    """Host body + jittered fringe from the line color. Role B (outline).

    Primary tint binds to **line** (not fill). The organic stroke is a lighter /
    softer **variation** of the line color so the true host stroke stays readable
    underneath.
    On ``Sprite``: blit + silhouette fringe.

    Args:
        color: Line color.
        amount: Irregularity (default 2.5).
        speed: Animation speed.
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 2.5, speed: float = 1.0):
        key = (
            "organic", _tint_intern_key(color, (0.95, 0.98, 1.0, 1.0)),
            round(float(amount), 2), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 2.5, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.95, 0.98, 1.0, 1.0), channel=_TINT_LINE)
        self.amount = float(amount)
        self.speed = float(speed)
        self._ready = True

    def _unseed(self) -> Optional["OrganicOutline"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("organic", ckey, round(self.amount, 2), round(self.speed, 2))

    def _organic_stroke_color(self, shape) -> Tuple[float, float, float, float]:
        """Lighter, softer variation of the host line so the solid stroke still reads."""
        base = _color_obj(self._primary_tint(shape))
        a = float(base.rgb[3]) if len(base.rgb) > 3 else 1.0
        try:
            var = base.lighter(0.32)
            return tuple(float(c) for c in var.with_alpha(min(0.9, max(0.35, a * 0.7))).rgb)
        except Exception:
            r, g, b = float(base.rgb[0]), float(base.rgb[1]), float(base.rgb[2])
            return (
                _clamp01(r + (1.0 - r) * 0.32),
                _clamp01(g + (1.0 - g) * 0.32),
                _clamp01(b + (1.0 - b) * 0.32),
                min(0.9, max(0.35, a * 0.7)),
            )

    def _render(self, shape, skia_canvas) -> None:
        fringe = self._organic_stroke_color(shape)
        seed = int(_clock() * self.speed * 3.0) % 100000
        pe = _discrete_pe(max(3.5, 8.0 - self.amount * 0.35), self.amount, seed)
        # Slightly wider than host so the jittered fringe peeks around the solid stroke
        w = max(_host_line_width(shape) * 1.35, 2.2)
        paint = self._stroke_paint(
            color=fringe, width=w, path_effect=pe, **_host_stroke_knobs(shape),
        )
        shape._geometry_draw(skia_canvas)  # host fill + exact host line
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)


class Tracer(Recipe):
    """Dashed ADD trail along the outline. Role B.

    On ``Sprite``: dashed silhouette path (no body fill — same as Shape).

    Args:
        color: Tracer color.
        speed: Travel speed.
        gap: Gap between dashes (default 12).
        width: Thickness (default 2.4).
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True

    def __new__(cls, color: Optional[ColorLike] = None, speed: float = 1.0, gap: float = 12.0, width: float = 2.4):
        key = (
            "tracer", _tint_intern_key(color, (1.0, 0.9, 0.3, 1.0)),
            round(float(speed), 2), round(float(gap), 1), round(float(width), 1),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, speed: float = 1.0, gap: float = 12.0, width: float = 2.4):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (1.0, 0.9, 0.3, 1.0), channel=_TINT_OUTLINE)
        self.speed = float(speed)
        self.gap = float(gap)
        self.width = float(width)
        self._ready = True

    def _unseed(self) -> Optional["Tracer"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.speed, self.gap, self.width)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("tracer", ckey, round(self.speed, 2), round(self.gap, 1), round(self.width, 1))

    def _render(self, shape, skia_canvas) -> None:
        if _is_sprite(shape):
            from .entity import _STYLE_PAINT
            shape._geometry_draw(skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=None)
        tint = self._primary_tint(shape)
        knobs = _host_stroke_knobs(shape)
        # Phase must wrap on the *dash pattern length* or the trail snaps each period.
        intervals = [self.gap, self.gap * 0.55]
        period = max(1e-3, float(intervals[0] + intervals[1]))
        phase = (_clock() * self.speed * 55.0) % period
        pe = skia.DashPathEffect.Make(intervals, phase)
        tail = self._stroke_paint(
            color=tint, width=self.width * 1.4, blend=BlendMode.ADD,
            path_effect=pe, alpha=tint[3] * 0.35, **knobs,
        )
        head = self._stroke_paint(
            color=(1.0, 1.0, 0.95, 0.95), width=self.width * 0.7,
            blend=BlendMode.ADD, path_effect=pe, **knobs,
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=tail)
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=head)


class _ElectricLineAdd(Recipe):
    """Survival ElectricBolt / Field: host plus one ADD Discrete-PE stroke."""

    _color_role = "B"

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 5.0, speed: float = 1.0):
        key = (
            "electric_line_add", _tint_intern_key(color, (0.55, 0.85, 1.0, 1.0)),
            round(float(amount), 1), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 5.0, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.55, 0.85, 1.0, 1.0), channel=_TINT_OUTLINE)
        self.amount = float(amount)
        self.speed = float(speed)
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("electric_line_add", ckey, round(self.amount, 1), round(self.speed, 2))

    def _render(self, shape, skia_canvas) -> None:
        _draw_electric_add_line(
            self, shape, skia_canvas, amount=self.amount, speed=self.speed,
        )


class ElectricBolt(GlowRimVisual):
    """Electric shock along the silhouette. Role B (outline).

    On ``Sprite``: ellipse fitted to the sprite rectangle.

    **Low:** host plus one ADD Discrete-PE stroke (no blur).
    **Medium / high:** same GlowRim path — batched ``Blur`` halo plus
    GPU-blurred PE outline glow (one shared Plus plate among interned
    peers; ``fx_quality="max"`` restores per-shape).

    Args:
        color: Bolt color.
        amount: Strength (default 5).
        speed: Frequency.
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True

    _VARIANT = "electric_bolt"
    _DEFAULT_TINT = (0.55, 0.85, 1.0, 1.0)
    _KEEP_HOST_FILL = True
    _USE_WASH = False
    _BLEND_ADD = True
    _OVERLAY_BLEND_ADD = True
    _HIGH_SIGMA = 5.0
    _HIGH_WIDTH = 3.6
    _HIGH_CORE_A = 1.0
    _MID_WHITE = 0.5
    _HOST_LINE_ATTR = "_electric_bolt_host_line"
    _HOST_WIDTH_ATTR = "_electric_bolt_host_width"
    _RIM_HOT = 0.0
    _SPINE_HOT = 0.0
    _RIM_LIFT = 1.0
    _SPINE_LIFT = 1.0
    _overlay_glow_sigma = 2.2
    _OVERLAY_GLOW_WIDTH = 1.7

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 5.0, speed: float = 1.0):
        return GlowRimVisual.__new__(
            cls, color, amount=1.0, density=amount, speed=speed,
        )

    @classmethod
    def _intern_extra(cls, kw: dict) -> tuple:
        return (
            round(float(kw.get("density", kw.get("amount", 5.0))), 1),
            round(float(kw.get("speed", 1.0)), 2),
        )

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 5.0, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_glowrim(color, amount=1.0)
        self.amount = float(amount)
        self.speed = float(speed)
        self._fallback = _ElectricLineAdd(color, amount=amount, speed=speed)
        self._ready = True

    def _unseed(self) -> Optional["ElectricBolt"]:
        if self._seed is None:
            return None
        return type(self)(None, self.amount, self.speed)

    def _halo_rgb(self, rgb):
        t = _energy_rgb((rgb[0], rgb[1], rgb[2], 1.0))
        return (t[0], t[1], t[2])

    def _use_fallback(self) -> bool:
        from .fx_quality import fidelity_is_survival

        return fidelity_is_survival() and getattr(self, "_fallback", None) is not None

    def _stash_host_package(self, shape) -> None:
        """Capture host stroke before the high Blur package overwrites it."""
        if getattr(shape, self._HOST_LINE_ATTR, None) is not None:
            return
        # Already in the high package — don't treat core stroke as host.
        if getattr(shape, "_line_filter", None) is getattr(self, "_halo_high", None):
            return
        try:
            shape._electric_bolt_host_line = getattr(shape, "_line", None)
        except Exception:
            shape._electric_bolt_host_line = None
        try:
            shape._electric_bolt_host_width = float(
                getattr(shape, "line_width", 1.5) or 1.5
            )
        except Exception:
            shape._electric_bolt_host_width = 1.5
        self._remember_host_tint(shape)

    def _unwind_high_package(self, shape) -> None:
        """Drop high blur/core leftovers so the low Recipe path sees host paint.

        ElectricBolt-only — mirrors ElectricField's quality unwind without changing
        shared GlowRimVisual.apply (_OrbHalo / ElectricField high keep their path).
        """
        from .style import BlendMode

        line = getattr(shape, self._HOST_LINE_ATTR, None)
        width = getattr(shape, self._HOST_WIDTH_ATTR, None)
        cached = getattr(shape, self._STASH_ATTR, None)
        is_line = is_stroke_type(shape)
        if is_line:
            try:
                shape._fill = None
                shape._is_fill_paint_dirty = True
            except Exception:
                shape.fill = None
            if line is not None:
                try:
                    shape._line = line
                    shape._is_line_paint_dirty = True
                except Exception:
                    shape.line = line
            elif cached is not None:
                shape.line = Color(
                    float(cached[0]), float(cached[1]), float(cached[2]),
                    float(cached[3]),
                )
        else:
            if line is not None:
                try:
                    shape._line = line
                    shape._is_line_paint_dirty = True
                except Exception:
                    shape.line = line
            elif cached is not None:
                # Fall back to stashed primary as a visible stroke tint.
                shape.line = Color(
                    float(cached[0]), float(cached[1]), float(cached[2]),
                    min(1.0, float(cached[3])),
                )
        if width is not None:
            try:
                shape.line_width = float(width)
            except Exception:
                pass
        try:
            shape.fill_filter = None
            shape.line_filter = None
        except Exception:
            pass
        try:
            shape.blend = BlendMode.NORMAL
        except Exception:
            pass

    def _apply(self, shape) -> None:
        from .style import BlendMode

        if self._use_fallback():
            self._unwind_high_package(shape)
            self._fallback._apply(shape)
            return
        self._stash_host_package(shape)
        self._apply_high(shape, BlendMode)

    def _outline_rgba(self, shape) -> Tuple[float, float, float, float]:
        """Host outline: stashed line paint (solid or Gradient first stop); a
        seed is the outline (``ElectricBolt("red")`` draws ``line = "red"``
        then ``ElectricBolt()``; before 2026-10-13 it mixed the host line in)."""
        if self._seed is not None:
            return self._tint_rgba(shape)
        lp = getattr(shape, self._HOST_LINE_ATTR, None)
        sampled = _channel_paint_rgba(lp) if lp is not None else None
        if sampled is not None:
            return sampled
        return self._tint_rgba(shape)

    def _outline_mid_rgb(self, shape) -> Tuple[float, float, float]:
        r, g, b, _a = self._outline_rgba(shape)
        hot = Color(float(r), float(g), float(b), 1.0).whiter_version(self._MID_WHITE)
        return (float(hot.rgb[0]), float(hot.rgb[1]), float(hot.rgb[2]))

    @property
    def _overlay_glow_batch(self) -> bool:
        # Medium uses the high overlay plate (low stays the survival fallback).
        return not self._use_fallback()

    def _overlay_glow_layer_bounds(self, shapes):
        return _union_overlay_glow_bounds(
            shapes, self._overlay_glow_sigma, self._OVERLAY_GLOW_WIDTH,
        )

    def _shock_stack_args(self, shape, rgb):
        # Same flicker at medium and high (do not cap on lite pe_hz).
        seed = _pe_seed(14.0 * self.speed, cap=False)
        if _is_line_shape(shape):
            pe = _line_discrete_pe(self.amount, seed)
            glow_w = _stroke_width_for_shape(shape, 1.7, mode="shock")
            mid_w = _stroke_width_for_shape(shape, 1.5, mode="shock")
            core_w = _stroke_width_for_shape(shape, 0.65, mode="shock")
        else:
            pe = _discrete_pe(max(3.0, self.amount * 0.4), self.amount, seed)
            glow_w = 1.7
            mid_w = 1.5
            core_w = 0.65
        return dict(
            rgb=rgb, pe=pe, glow_w=glow_w, mid_w=mid_w, core_w=core_w,
            glow_a=1.0, mid_rgb=self._outline_mid_rgb(shape), mid_a=0.8, core_a=0.95,
            blur_sigma=2.2,
        )

    def _emit_overlay_glow(self, shape, skia_canvas) -> None:
        rgb = self._halo_rgb(self._tint_rgba(shape)[:3])

        def _stroke():
            args = self._shock_stack_args(shape, rgb)
            if float(args["glow_w"]) <= 0.05:
                return
            glow = self._rim_skia_paint(
                rgb, float(args["glow_a"]), float(args["glow_w"]),
                path_effect=args["pe"],
            )
            self._stroke_at_scale(shape, skia_canvas, glow, 1.0)

        self._with_filters_stripped(shape, _stroke)

    def _draw_character(self, shape, skia_canvas, rgb, *, glow_batched=False) -> None:
        args = self._shock_stack_args(shape, rgb)
        # Medium and high: GPU-blurred PE glow unless the canvas already
        # opened a shared overlay plate.
        _draw_shock_pe_stack(
            self, shape, skia_canvas,
            blur_glow=not glow_batched, skip_glow=glow_batched,
            **args,
        )

    def _draw_extra_rim(self, shape, skia_canvas) -> None:
        return


class Water(Recipe):
    """Side-view water: volume only *below* the free-surface wave (air above).

    Args:
        amount: Ripple strength.
        speed: Animation speed.
    """

    _color_role = "D"

    def __new__(cls, amount: float = 1.0, speed: float = 1.0):
        key = ("water", round(float(amount), 2), round(float(speed), 2))
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, amount: float = 1.0, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        from .style import WaterFill
        self.amount = float(amount)
        self.speed = float(speed)
        self._fill = WaterFill(kind="side", amount=self.amount, speed=self.speed)
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        return ("water", round(self.amount, 2), round(self.speed, 2))

    def _bounds(self, shape) -> Tuple[float, float, float, float, float, float]:
        """left, right, bot, top, cx, cy (y-up)."""
        cx, cy, r = _center_radius(shape)
        if hasattr(shape, "width") and hasattr(shape, "height"):
            hw = abs(_scalar(shape.width)) * 0.5
            hh = abs(_scalar(shape.height)) * 0.5
        else:
            hw = r
            hh = r
        return cx - hw, cx + hw, cy - hh, cy + hh, cx, cy

    def _render(self, shape, skia_canvas) -> None:
        left, right, bot, top, cx, cy = self._bounds(shape)
        t = _clock() * self.speed
        span = max(right - left, 1.0)
        # Mean free surface near top of bounds (y-up)
        mean = bot + (top - bot) * 0.78
        amp = max(2.5, (top - bot) * 0.06) * self.amount
        segs = 28

        def wave_y(u: float) -> float:
            return (
                mean
                + math.sin(u * 6.5 + t * 3.5) * amp
                + math.sin(u * 13.0 - t * 2.0) * amp * 0.45
            )

        # Closed water body: bottom edge → right → reverse along wave → close
        body = skia.Path()
        body.moveTo(left, bot)
        body.lineTo(right, bot)
        for i in range(segs, -1, -1):
            u = i / segs
            x = left + span * u
            body.lineTo(x, wave_y(u))
        body.close()

        # Clip to host silhouette so water never spills outside the shape
        skia_canvas.save()
        # Host soft empty (air) — do not fill host with solid blue
        try:
            # Build clip from a temporary geometry stroke — use host draw clip
            # by translating nothing; draw rect clip for rects / oval for radius
            if hasattr(shape, "width") and hasattr(shape, "height"):
                clip = skia.Rect.MakeLTRB(left, bot, right, top)
                rv = getattr(shape, "_rotation_value", None)
                ang = float(rv()) if callable(rv) else float(getattr(shape, "_rotation", 0.0) or 0.0)
                if abs(ang) > 1e-3:
                    # Non-rotated water pool is the lab case; still clip AABB
                    skia_canvas.clipRect(clip, skia.ClipOp.kIntersect, True)
                else:
                    skia_canvas.clipRect(clip, skia.ClipOp.kIntersect, True)
            else:
                skia_canvas.clipOval(
                    skia.Rect.MakeLTRB(left, bot, right, top),
                    skia.ClipOp.kIntersect,
                    True,
                )
        except Exception:
            pass

        deep = skia.Paint(
            AntiAlias=True, Style=skia.Paint.kFill_Style,
            Color4f=skia.Color4f(0.04, 0.18, 0.38, 0.5),
        )
        skia_canvas.drawPath(body, deep)
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
        paint.setShader(_procedural_shader(self._fill, cx, cy, max(span, top - bot) * 0.55))
        skia_canvas.drawPath(body, paint)

        # Free-surface stroke
        wave = skia.Path()
        for i in range(segs + 1):
            u = i / segs
            x = left + span * u
            y = wave_y(u)
            if i == 0:
                wave.moveTo(x, y)
            else:
                wave.lineTo(x, y)
        foam = skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.0,
            Color4f=skia.Color4f(0.6, 0.9, 1.0, 0.3),
            BlendMode=skia.BlendMode.kPlus,
        )
        crest = skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0,
            Color4f=skia.Color4f(0.85, 0.98, 1.0, 0.8),
            BlendMode=skia.BlendMode.kPlus,
        )
        skia_canvas.drawPath(wave, foam)
        skia_canvas.drawPath(wave, crest)
        skia_canvas.restore()

        # Soft outline of the *water body only* (below free surface) — not the
        # host rect/ellipse rim in the air region above the wave.
        floor = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=1.2,
            Color4f=skia.Color4f(0.1, 0.35, 0.55, 0.45),
        )
        skia_canvas.drawPath(body, floor)


class Liquify(Recipe):
    """Organic wobble: two borderless ghosts (hue-shifted) + main body.

    ``color=None`` keeps the host body. ``color=`` seeds the body like
    ``Neon`` (Role A); the ghosts are hue-shifted from it.

    Args:
        color: Body color (default: keep the shape's own).
        amount: Wobble (default 3.5).
        speed: Animation speed.
    """

    _color_role = "E"

    def __new__(cls, color=None, amount: float = 3.5, speed: float = 1.0):
        _refuse_number_as_color("Liquify", color, "amount")
        key = (
            "liquify", _tint_intern_key(color, _LIQUIFY_DEFAULT),
            round(float(amount), 2), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color=None, amount: float = 3.5, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, _LIQUIFY_DEFAULT, channel=None)
        # Seeded → Role A (identity body, like Neon). Unseeded is Role E: it
        # draws the host body, so set_color shows (not D, which hides it).
        self._color_role = "E" if self._seed_color is None else "A"
        self.amount = float(amount)
        self.speed = float(speed)
        self._ready = True

    def _unseed(self) -> Optional["Liquify"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("liquify", ckey, round(self.amount, 2), round(self.speed, 2))

    def _render(self, shape, skia_canvas) -> None:
        if fidelity_is_lite():
            shape._geometry_draw(skia_canvas)
            return
        t = _clock() * self.speed
        host_a = _host_rgba(shape)[3] if len(_host_rgba(shape)) > 3 else 1.0
        ghosts = (
            (math.sin(t) * self.amount, math.cos(t * 0.7) * self.amount * 0.6, 0.55 * host_a, 0.06),
            (math.cos(t * 1.3) * self.amount * 0.5, math.sin(t * 0.9) * self.amount, 0.62 * host_a, -0.05),
        )
        for dx, dy, alpha, hue in ghosts:
            skia_canvas.save()
            skia_canvas.translate(dx, dy)
            fill = _host_fill_paint(shape, alpha=alpha, hue_shift=hue)
            shape._geometry_draw(skia_canvas, fill_paint=fill, stroke_paint=None)
            skia_canvas.restore()
        shape._geometry_draw(skia_canvas)


_PLASMASHOT_STYLES = ("core", "filaments", "tesla")


def _plasmashot_style(style: str) -> str:
    return expect_choice(style, BOLT_STYLES, what="Bolt style")


def _plasmashot_intensity(style: str, intensity) -> float:
    """Filaments default 0.6 (calmer body); core/tesla stay 1.0."""
    if intensity is None:
        return 0.6 if style == "filaments" else 1.0
    from .validate import number
    return number(intensity, "Bolt intensity")


def _plasmashot_fill_amount(style: str, amount: float, intensity: float) -> float:
    """SkSL ``u_amount``: filaments = spoke density; others = animation gain."""
    if style == "filaments":
        return float(amount)
    return float(intensity)


def _plasmashot_glow_intensity(style: str, intensity: float) -> float:
    """Halo / outline gain. Filaments: 0.6 maps to the old intensity=1.0 bloom."""
    inten = max(0.0, float(intensity))
    if style == "filaments":
        return max(0.35, inten / 0.6)
    return max(0.35, inten)


def _draw_plasmashot_tesla(shape, skia_canvas, *, amount, intensity, speed, low: bool) -> None:
    """Tesla bolts: closed silhouettes only. Line skips so rays don't spray from the midpoint."""
    if _is_line_shape(shape):
        return
    t = _clock() * float(speed)
    cx, cy, r = _center_radius(shape)
    n_rays = max(4, int(5 + amount))
    if low:
        n_rays = max(2, n_rays // 2)
    seg = max(2.0, r * 0.12)
    dev = max(1.5, r * 0.08 * float(intensity))
    w_out = max(0.8, min(2.2, r * 0.04))
    w_core = max(0.4, min(1.0, r * 0.02))
    for i in range(n_rays):
        reach = r * (0.72 + 0.22 * abs(math.sin(i * 1.7 + 0.3)))
        ang = t * 1.7 + i * (2 * math.pi / n_rays) + 0.4 * math.sin(t * 3 + i)
        pe = _discrete_pe(seg, dev, _pe_seed(20.0) + i * 97)
        path = skia.Path()
        path.moveTo(cx, cy)
        steps = max(3, int(4 + r / 18.0))
        if low:
            steps = max(2, steps // 2)
        for s in range(1, steps + 1):
            u = s / steps
            path.lineTo(cx + math.cos(ang) * reach * u, cy + math.sin(ang) * reach * u)
        bolt = skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=w_out,
            Color4f=skia.Color4f(0.85, 0.95, 1.0, 0.75),
            BlendMode=skia.BlendMode.kPlus,
        )
        bolt.setPathEffect(pe)
        skia_canvas.drawPath(path, bolt)
        if not low:
            core = skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=w_core,
                Color4f=skia.Color4f(1.0, 1.0, 1.0, 0.9),
                BlendMode=skia.BlendMode.kPlus,
            )
            skia_canvas.drawPath(path, core)


class _BoltHigh(GlowRimVisual):
    """High-only Bolt: SkSL body + GPU Blur halo + unfiltered rim/tesla."""

    _color_role = "A"

    _VARIANT = "plasmashot_high"
    _DEFAULT_TINT = (0.55, 0.7, 1.0, 1.0)
    _KEEP_HOST_FILL = False
    _USE_WASH = False
    _BLEND_ADD = True
    _HIGH_HOT = 0.0
    _FILL_KIND = {
        "core": "plasma_core",
        "filaments": "plasma_filaments",
        "tesla": "plasma_tesla",
    }

    def __new__(
        cls,
        color=None,
        amount: float = 3.0,
        speed: float = 1.2,
        intensity=None,
        style: BoltStyle = "core",
    ):
        st = _plasmashot_style(style)
        inten = _plasmashot_intensity(st, intensity)
        return GlowRimVisual.__new__(
            cls, color, amount=inten,
            density=amount, speed=speed, style=st,
        )

    @classmethod
    def _intern_extra(cls, kw: dict) -> tuple:
        return (
            str(kw.get("style", "core")),
            round(float(kw.get("density", kw.get("amount", 3.0))), 2),
            round(float(kw.get("speed", 1.2)), 2),
        )

    def __init__(
        self,
        color=None,
        amount: float = 3.0,
        speed: float = 1.2,
        intensity=None,
        style: BoltStyle = "core",
    ):
        if getattr(self, "_ready", False):
            return
        self.style = _plasmashot_style(style)
        inten = _plasmashot_intensity(self.style, intensity)
        glow = _plasmashot_glow_intensity(self.style, inten)
        self._init_glowrim(color, glow)
        self.intensity = inten
        self.amount = float(amount)
        self.speed = float(speed)
        self._ready = True

    def _apply_high(self, shape, BlendMode) -> None:
        from .style import ProceduralFill

        rgb = self._tint_rgba(shape)[:3]
        glow = _plasmashot_glow_intensity(self.style, self.intensity)
        fill_amt = _plasmashot_fill_amount(self.style, self.amount, self.intensity)
        halo_a = min(1.0, 0.55 * glow)
        width = max(4.5 * glow, _OUTLINE_PLASMASHOT * 2.4)
        hot = 0.0
        if self.style == "filaments":
            hot = min(0.5, 0.08 + 0.22 * max(0.0, glow - 1.0))
        core = Color(
            rgb[0] + (1.0 - rgb[0]) * hot,
            rgb[1] + (1.0 - rgb[1]) * hot,
            rgb[2] + (1.0 - rgb[2]) * hot,
            halo_a,
        )
        is_line = is_stroke_type(shape)
        if is_line:
            shape.fill = None
            shape.line = core
        else:
            kind = self._FILL_KIND.get(self.style, "plasma_core")
            shape.fill = ProceduralFill(
                kind=kind, amount=fill_amt, speed=self.speed,
            )
            shape.line = core
        try:
            shape.line_width = width
        except Exception:
            pass
        shape.fill_filter = None
        shape.line_filter = self._halo_high
        shape.blend = BlendMode.ADD

    def _draw_extra_rim(self, shape, skia_canvas) -> None:
        pulse = 0.75 + 0.25 * math.sin(_clock() * float(self.speed) * 5.5)
        glow = _plasmashot_glow_intensity(self.style, self.intensity)
        rim_hot = self._RIM_HOT
        rim_w = self._RIM_WIDTH
        if self.style == "filaments":
            pulse = min(1.0, pulse * min(1.85, glow))
            rim_hot = min(0.65, self._RIM_HOT + 0.18 * max(0.0, glow - 1.0))
            rim_w = self._RIM_WIDTH * min(1.85, glow)
        rgb = self._tint_rgba(shape)[:3]
        knobs = _host_stroke_knobs(shape)
        rim_rgb = _aura_lift_rgb(_aura_mix_hot(rgb, rim_hot), self._RIM_LIFT)
        paint = self._rim_skia_paint(rim_rgb, pulse, rim_w, **knobs)
        self._stroke_at_scale(shape, skia_canvas, paint, self._RIM_SCALE)
        spine_rgb = _aura_lift_rgb(_aura_mix_hot(rgb, self._SPINE_HOT), self._SPINE_LIFT)
        spine = self._rim_skia_paint(
            spine_rgb, min(1.0, 0.9 * pulse), self._SPINE_WIDTH, **knobs,
        )
        self._stroke_at_scale(shape, skia_canvas, spine, self._SPINE_SCALE)

    def _draw_overlays(self, shape, skia_canvas, rgb, *, glow_batched=False) -> None:
        self._draw_extra_rim(shape, skia_canvas)
        if self.style == "tesla":
            _draw_plasmashot_tesla(
                shape, skia_canvas,
                amount=self.amount, intensity=self.intensity,
                speed=self.speed, low=False,
            )


class Bolt(Recipe):
    """Projectile energy — core | filaments | tesla. Role A (body).

    - **core** (default): classic centered swirl plasma
    - **filaments**: rotating filament plasma (default ``intensity=0.6``;
      ``amount`` = spoke density; ``intensity`` = outline / color glow only)
    - **tesla**: plasma-ball rays from center to rim (closed shapes only;
      ``Line`` skips the bolts and matches core / filaments)

    **High:** interned ``Blur`` on ``line_filter`` (filter-batchable) +
    unfiltered rim/spine/tesla via ``_overlay_after_filters``.
    **Medium/low:** SkSL body + thin ADD lip (Recipe solo).

    Args:
        color: Bolt color.
        amount: Filament density (default 3).
        speed: Animation speed (default 1.2).
        intensity: Outline glow; ``None`` = per style.
        style: ``"core"`` (default) · ``"filaments"`` · ``"tesla"``.
    """

    _color_role = "A"

    _fidelity_sensitive = True
    _STYLES = _PLASMASHOT_STYLES

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        amount: float = 3.0,
        speed: float = 1.2,
        intensity=None,
        style: BoltStyle = "core",
    ):
        st = _plasmashot_style(style)
        if st == "core" and float(amount) != 3.0:
            # Filament density: core draws no filaments, so it would change
            # nothing (KN4, 2026-10-12; before, it was taken and ignored).
            raise TypeError(
                'Bolt(style="core") has no filaments, so amount= changes nothing. '
                'Write Bolt(style="filaments", amount=…) or "tesla", or drop amount.'
            )
        inten = _plasmashot_intensity(st, intensity)
        key = (
            "plasmashot", st,
            _tint_intern_key(color, (0.55, 0.7, 1.0, 1.0)),
            round(float(amount), 2),
            round(float(speed), 2),
            round(float(inten), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        amount: float = 3.0,
        speed: float = 1.2,
        intensity=None,
        style: BoltStyle = "core",
    ):
        if getattr(self, "_ready", False):
            return
        from .style import ProceduralFill
        self._init_tint(color, (0.55, 0.7, 1.0, 1.0), channel=_TINT_BODY)
        self.style = _plasmashot_style(style)
        self.amount = float(amount)
        self.speed = float(speed)
        self.intensity = _plasmashot_intensity(self.style, intensity)
        kind = _BoltHigh._FILL_KIND[self.style]
        fill_amt = _plasmashot_fill_amount(self.style, self.amount, self.intensity)
        self._fill = ProceduralFill(kind=kind, amount=fill_amt, speed=self.speed)
        self._high = _BoltHigh(
            color, amount=self.amount, speed=self.speed,
            intensity=self.intensity, style=self.style,
        )
        self._ready = True

    def _unseed(self) -> Optional["Bolt"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed, self.intensity, style=self.style)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return (
            "plasmashot", self.style,
            ckey,
            round(self.amount, 2),
            round(self.speed, 2),
            round(self.intensity, 2),
        )

    @property
    def _is_multipass(self) -> bool:
        return fidelity_is_lite()

    def _overlay_after_filters(self, shape, skia_canvas) -> None:
        if fidelity_is_lite():
            return
        self._high._overlay_after_filters(shape, skia_canvas)

    def _apply(self, shape) -> None:
        if fidelity_is_lite():
            self._unwind_high_package(shape)
            super()._apply(shape)
            _set_line_width(shape, _OUTLINE_PLASMASHOT)
            return
        self._high._apply(shape)

    def _unwind_high_package(self, shape) -> None:
        from .style import BlendMode

        cached = getattr(shape, "_glowrim_host_tint", None)
        if cached is not None:
            r, g, b, a = (float(cached[0]), float(cached[1]), float(cached[2]), float(cached[3]))
            if is_stroke_type(shape):
                shape.fill = None
                shape.line = Color(r, g, b, a)
            else:
                shape.fill = Color(r, g, b, a)
        try:
            shape.fill_filter = None
            shape.line_filter = None
        except Exception:
            pass
        try:
            shape.blend = BlendMode.NORMAL
        except Exception:
            pass

    def _emit_glow(self, shape, skia_canvas, cx, cy, r, t, tint):
        pulse = 0.75 + 0.25 * math.sin(t * 5.5)
        rim_w = _OUTLINE_PLASMASHOT
        rgb = tint[:3]
        glow = _plasmashot_glow_intensity(self.style, self.intensity)
        lip = self._stroke_paint(
            color=(*rgb, min(1.0, 0.55 * glow * pulse)),
            width=max(rim_w, 1.35 * 0.85 * glow),
            blend=BlendMode.ADD,
            **_host_stroke_knobs(shape),
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=lip)

    def _render(self, shape, skia_canvas) -> None:
        if not fidelity_is_lite():
            _apply_at_draw(shape, self._high._apply, shape)
            self._high._render(shape, skia_canvas)
            return
        t = _clock() * self.speed
        cx, cy, r = _center_radius(shape)
        tint = self._primary_tint(shape)
        body = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style, BlendMode=skia.BlendMode.kPlus)
        body.setShader(_procedural_shader(self._fill, cx, cy, r))
        shape._geometry_draw(skia_canvas, fill_paint=body, stroke_paint=None)
        self._emit_glow(shape, skia_canvas, cx, cy, r, t, tint)
        if self.style == "tesla":
            _draw_plasmashot_tesla(
                shape, skia_canvas,
                amount=self.amount, intensity=self.intensity,
                speed=self.speed, low=True,
            )


_LASER_SPRITE_THICK = 1.75  # glow / mid vs Shape Laser
# White core: 2/3 of the thin v2 band + 1/3 of the last (too fat) pass.
_LASER_SPRITE_CORE = 0.45
_LASER_SPRITE_CORE_MIN = 0.82


class Laser(Recipe):
    """Thin beam: soft ADD halo + color mid + white core.

    Role B (outline / stroke). Primary tint binds to host line.
    ``amount`` scales the ADD stroke ladder relative to host ``line_width``.
    Shape keeps the original stroke ladder. Sprite blits the bitmap, then
    paints the beam with one SDF quad (smoothed-path strokes as fallback).
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True
    _needs_sprite_sdf = True  # Sprite beam uses SDF bands
    _look_pass_group = True

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0):
        key = (
            "laser", _tint_intern_key(color, (0.95, 0.12, 0.1, 1.0)),
            round(float(amount), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.95, 0.12, 0.1, 1.0), channel=_TINT_LINE)
        self.amount = float(amount)
        self._ready = True

    def _unseed(self) -> Optional["Laser"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("laser", ckey, round(self.amount, 2))

    def _render_sprite(self, shape, skia_canvas) -> None:
        _blit_sprite_body(shape, skia_canvas)
        tint = self._primary_tint(shape)
        base = _host_line_width(shape) * self.amount * _LASER_SPRITE_THICK
        core_w = max(_LASER_SPRITE_CORE_MIN, base * _LASER_SPRITE_CORE)
        t = fidelity_tier()
        pulse = 0.9 + 0.1 * math.sin(_clock() * 6.5)
        sdf = getattr(shape, "_draw_sprite_sdf_bands", None)
        if callable(sdf):
            if t == TIER_LOW:
                ok = sdf(
                    skia_canvas, tint,
                    glow_width=0.0, glow_alpha=0.0,
                    rim_width=base * 1.35, rim_alpha=0.92,
                    core_width=core_w if _lod_passes() >= 1 else 0.0,
                    core_alpha=0.9 if _lod_passes() >= 1 else 0.0,
                )
            else:
                ok = sdf(
                    skia_canvas, tint,
                    glow_width=base * 2.15, glow_alpha=0.28 * pulse,
                    rim_width=base * 1.15, rim_alpha=0.72,
                    core_width=core_w, core_alpha=0.98,
                )
            if ok:
                return
        knobs = _host_stroke_knobs(shape)
        if t == TIER_LOW:
            mid = self._stroke_paint(
                color=(*tint[:3], 0.92),
                width=base * 1.35,
                blend=BlendMode.ADD,
                **knobs,
            )
            _stroke_host_v2(skia_canvas, shape, mid)
            if _lod_passes() >= 1:
                core = self._stroke_paint(
                    color=(1.0, 1.0, 1.0, 0.9),
                    width=core_w,
                    blend=BlendMode.ADD,
                    **knobs,
                )
                _stroke_host_v2(skia_canvas, shape, core)
            return
        layers = (
            ((*tint[:3], 0.28 * pulse), base * 2.15),
            ((*tint[:3], 0.72), base * 1.15),
            ((1.0, 1.0, 1.0, 0.98), core_w),
        )
        for col, w in layers:
            paint = self._stroke_paint(
                color=col, width=w, blend=BlendMode.ADD, **knobs,
            )
            _stroke_host_v2(skia_canvas, shape, paint)

    def _render(self, shape, skia_canvas) -> None:
        if _is_sprite(shape) and not _is_line_shape(shape):
            self._render_sprite(shape, skia_canvas)
            return
        knobs = _host_stroke_knobs(shape)
        for col, w in self._laser_stroke_layers(shape):
            paint = self._stroke_paint(
                color=col, width=w, blend=BlendMode.ADD, **knobs,
            )
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=paint)

    def _laser_stroke_layers(self, shape):
        """ADD ladder (color, width) for one host. Shared by render and look-pass emit."""
        tint = self._primary_tint(shape)
        base = _host_line_width(shape) * self.amount
        t = fidelity_tier()
        if t == TIER_LOW:
            layers = [((*tint[:3], 0.92), base * 1.35)]
            if _lod_passes() >= 1:
                layers.append(((1.0, 1.0, 1.0, 0.9), max(0.7, base * 0.4)))
            return layers
        pulse = 0.9 + 0.1 * math.sin(_clock() * 6.5)
        return [
            ((*tint[:3], 0.28 * pulse), base * 2.15),
            ((*tint[:3], 0.72), base * 1.15),
            ((1.0, 1.0, 1.0, 0.98), max(0.55, base * 0.32)),
        ]

    def _emit_look_passes(self, shapes, skia_canvas) -> None:
        buckets: Dict[tuple, list] = {}
        order: List[tuple] = []
        for shp in shapes:
            tint = self._primary_tint(shp)
            base = _host_line_width(shp) * self.amount
            t = fidelity_tier()
            kind = _world_stroke_kind(shp) or "path"
            knobs = _host_stroke_knobs(shp)
            key = (
                t, tint[0], tint[1], tint[2], round(base, 3),
                _lod_passes() if t == TIER_LOW else 3, kind,
                knobs["cap"], knobs.get("join"),
            )
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(shp)
        for key in order:
            group = buckets[key]
            layers = self._laser_stroke_layers(group[0])
            knobs = {"cap": key[7]}
            if key[8] is not None:
                knobs["join"] = key[8]
            centers = None
            if key[6] == "circle":
                centers = [_center_radius(s) for s in group]
            for col, w in layers:
                paint = self._stroke_paint(
                    color=col, width=w, blend=BlendMode.ADD, **knobs,
                )
                _stroke_group_world(group, skia_canvas, paint, centers=centers)


class Ink(Recipe):
    """Hand-inked contour — host fill + pen-jittered stroke.

    Role B (outline). Primary tint: host line. Host fill is always drawn.
    On ``Sprite``: blit + silhouette ink stroke.

    Args:
        color: Tint (any color form; default: follows the shape's own color).
        amount: Line tremor (default 1.8).
        speed: Animation speed (default 0.6).
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True
    _look_pass_group = True

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.8, speed: float = 0.6):
        key = (
            "ink", _tint_intern_key(color, (0.1, 0.1, 0.12, 1.0)),
            round(float(amount), 2), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.8, speed: float = 0.6):
        if getattr(self, "_ready", False):
            return
        # Optional seed writes line; when None, brush stroke samples host live.
        self._init_tint(color, (0.1, 0.1, 0.12, 1.0), channel=_TINT_LINE)
        self.amount = float(amount)
        self.speed = float(speed)
        self._ready = True

    def _unseed(self) -> Optional["Ink"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("ink", ckey, round(self.amount, 2), round(self.speed, 2))

    def _emit_look_passes(self, shapes, skia_canvas) -> None:
        for shp in shapes:
            _draw_host_fill(shp, skia_canvas)
        pe = _discrete_pe(
            max(3.0, 7.0 - self.amount * 0.5),
            max(0.7, self.amount),
            _pe_seed(max(self.speed, 0.2) * 3.0) if not fidelity_is_lite() else 11,
        )
        buckets: Dict[tuple, list] = {}
        order: List[tuple] = []
        for shp in shapes:
            w = max(_host_line_width(shp, 1.5), 1.2) * (1.15 if not _is_line_shape(shp) else 1.0)
            tint = self._primary_tint(shp)
            kind = _world_stroke_kind(shp) or "path"
            knobs = _host_stroke_knobs(shp)
            key = (
                tint[0], tint[1], tint[2], tint[3] if len(tint) > 3 else 1.0,
                round(w, 3), kind, knobs["cap"], knobs.get("join"),
            )
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append((shp, w, tint))
        for key in order:
            group = buckets[key]
            w = group[0][1]
            tint = group[0][2]
            knobs = {"cap": key[6]}
            if key[7] is not None:
                knobs["join"] = key[7]
            stroke = self._stroke_paint(
                color=tint, width=w, path_effect=pe, **knobs,
            )
            _stroke_group_world([item[0] for item in group], skia_canvas, stroke)

    def _render(self, shape, skia_canvas) -> None:
        _draw_host_fill(shape, skia_canvas)
        pe = _discrete_pe(
            max(3.0, 7.0 - self.amount * 0.5),
            max(0.7, self.amount),
            _pe_seed(max(self.speed, 0.2) * 3.0) if not fidelity_is_lite() else 11,
        )
        w = max(_host_line_width(shape, 1.5), 1.2) * (1.15 if not _is_line_shape(shape) else 1.0)
        stroke = self._stroke_paint(
            color=self._primary_tint(shape), width=w, path_effect=pe,
            **_host_stroke_knobs(shape),
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=stroke)


class InkBleed(Recipe):
    """Wet brush — host colors with soft static bleed (no animation).

    On ``Sprite``: blit + silhouette bleed strokes.

    Args:
        color: Tint (any color form; default: follows the shape's own color).
        amount: How far the ink bleeds.
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0):
        key = ("inkbleed", _tint_intern_key(color, (0.1, 0.1, 0.12, 1.0)), round(float(amount), 2))
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.1, 0.1, 0.12, 1.0), channel=_TINT_LINE)
        self.amount = float(amount)
        # Cache path effects once — recreating Discrete every frame stalls the loop.
        a = self.amount
        self._pe_soft = _discrete_pe(
            max(4.0, 9.0 - a * 0.4),
            max(1.0, a * 1.2),
            17,
        )
        self._pe_core = _discrete_pe(
            max(3.5, 6.5 - a * 0.35),
            max(0.6, a * 0.7),
            41,
        )
        self._mist_blur = skia.MaskFilter.MakeBlur(
            skia.kNormal_BlurStyle, max(1.2, 1.6 + a * 0.35),
        )
        self._ready = True

    def _unseed(self) -> Optional["InkBleed"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("inkbleed", ckey, round(self.amount, 2))

    def _render(self, shape, skia_canvas) -> None:
        _draw_host_fill(shape, skia_canvas)
        host = self._primary_tint(shape)
        th = _host_line_width(shape, 1.5)
        knobs = _host_stroke_knobs(shape)
        t = fidelity_tier()
        # Survival: hard stroke only (no Discrete PE / mist).
        if t == TIER_LOW:
            core = self._stroke_paint(
                color=(*host[:3], 0.9),
                width=max(th, 1.4),
                **knobs,
            )
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=core)
            return
        # Medium: core PE only (promoted former low).
        if t == TIER_MED:
            core = self._stroke_paint(
                color=(*host[:3], 0.9),
                width=max(th, 1.4),
                path_effect=self._pe_core,
                **knobs,
            )
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=core)
            return
        # High: mist blur + soft PE + core PE.
        mist = self._stroke_paint(
            color=(*host[:3], 0.22),
            width=max(th * 2.4, 3.2 + self.amount),
            mask=self._mist_blur,
            **knobs,
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=mist)
        edge = self._stroke_paint(
            color=(*host[:3], 0.55),
            width=max(th * 1.5, 2.0 + self.amount * 0.4),
            path_effect=self._pe_soft,
            **knobs,
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=edge)
        core = self._stroke_paint(
            color=(*host[:3], 0.9),
            width=max(th, 1.4),
            path_effect=self._pe_core,
            **knobs,
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=core)


class Recolor(Recipe):
    """Hue-band palette swap on a bitmap. Sprite ``.visual`` or ``Texture(shift=)``.

    ``key`` is the source hue (color or name); pixels near that hue are
    shifted to ``to``. No mask channel — any PNG with a distinct key hue.
    On Sprite: multipass SkSL blit. On Texture: paint ColorFilter.
    A gray key (white, gray, black) raises ``ValueError``: it has no hue, and
    pixels that gray are never matched. ``to`` may be gray.

    Args:
        key: Hue to replace (default ``"blue"``).
        to: Hue to paint instead (default ``"tomato"``).
        range: Width of the matched hue band (default 0.08).
        soft: Softness of the band edge (default 0.04).
    """

    _color_role = "C"
    _allows_sprite = True
    _sprite_only = True
    _is_multipass = True
    _tint_channel = None

    def __new__(
        cls,
        key: ColorLike = "blue",
        to: ColorLike = "tomato",
        *,
        range: float = 0.08,
        soft: float = 0.04,
    ):
        kr = _as_color_rgb(key)
        _refuse_gray_recolor_key(key, kr)
        tr = _as_color_rgb(to)
        key_t = (
            "recolor",
            tuple(round(x, 3) for x in kr),
            tuple(round(x, 3) for x in tr),
            round(float(range), 3), round(float(soft), 3),
        )
        return _intern(cls, key_t, lambda: object.__new__(cls))

    def __init__(
        self,
        key: ColorLike = "blue",
        to: ColorLike = "tomato",
        *,
        range: float = 0.08,
        soft: float = 0.04,
    ):
        if getattr(self, "_ready", False):
            return
        self.key = key
        self.to = to
        self.range = max(0.01, float(range))
        self.soft = max(0.001, float(soft))
        self._key_hsv = _rgb_to_hsv(_as_color_rgb(key))
        self._to_hsv = _rgb_to_hsv(_as_color_rgb(to))
        self._color_filter = self._make_texture_color_filter()
        self._ready = True

    def _make_texture_color_filter(self):
        """Paint ColorFilter for ``Texture(shift=Recolor(...))`` (not the Sprite blit)."""
        from ._sksl_shape import color_filter_builder
        b = color_filter_builder("texture_recolor")
        kh, ks, kv = self._key_hsv
        th, ts, tv = self._to_hsv
        b.setUniform("u_key_hsv", [float(kh), float(ks), float(kv)])
        b.setUniform("u_to_hsv", [float(th), float(ts), float(tv)])
        b.setUniform("u_range", float(self.range))
        b.setUniform("u_soft", float(self.soft))
        return b.makeColorFilter()

    @property
    def _batch_key(self) -> tuple:
        return (
            "recolor",
            tuple(round(x, 3) for x in self._key_hsv),
            tuple(round(x, 3) for x in self._to_hsv),
            round(self.range, 3), round(self.soft, 3),
        )

    def _apply(self, shape) -> None:
        try:
            shape.fill_filter = None
            shape.line_filter = None
        except Exception:
            pass

    def _render(self, shape, skia_canvas) -> None:
        draw = getattr(shape, "_draw_sprite_recolor", None)
        if callable(draw):
            draw(skia_canvas, self)
        else:
            shape._geometry_draw(skia_canvas)


# The recolor shaders (``sprite_recolor`` / ``texture_recolor`` in
# _sksl_shape.py: ``smoothstep(0.12, 0.28, hsv.y)``) never match a pixel below
# this HSV saturation. A gray key has no hue (colorsys says 0, red), so it
# would recolor red pixels and never its own color.
_RECOLOR_MIN_KEY_S = 0.12


def _refuse_gray_recolor_key(key, rgb) -> None:
    s = colorsys.rgb_to_hsv(rgb[0], rgb[1], rgb[2])[1]
    if s < _RECOLOR_MIN_KEY_S:
        raise ValueError(
            f"Recolor(key={key!r}): Recolor matches pixels by hue and skips pixels under "
            f"HSV saturation {_RECOLOR_MIN_KEY_S}; this key's is {s:.2f}, so it can never "
            f"select its own color (a pure gray reads as hue 0 and would recolor red pixels). "
            f"Pick a key with a hue, e.g. key=\"red\". Recolor cannot select white, gray "
            f"or black areas."
        )


def _as_color_rgb(color) -> Tuple[float, float, float]:
    c = color if isinstance(color, Color) else Color(color)
    return (float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]))


def _rgb_to_hsv(rgb: Tuple[float, float, float]) -> Tuple[float, float, float]:
    import colorsys
    return colorsys.rgb_to_hsv(rgb[0], rgb[1], rgb[2])


def _soften_rim_rgb(rgb) -> Tuple[float, float, float]:
    """Soften pure white so ADD strokes read as a glow, not a chalk plate."""
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    sat = max(r, g, b) - min(r, g, b)
    if sat < 0.08 and max(r, g, b) > 0.85:
        return (0.72, 0.88, 1.0)
    return (r, g, b)


def _rim_core_rgb(rgb) -> Tuple[float, float, float]:
    """Slight lift so white rims keep a cool tint."""
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    return (
        min(1.0, r * 1.05 + 0.05),
        min(1.0, g * 1.05 + 0.05),
        min(1.0, b * 1.08 + 0.08),
    )


class _RimHigh(GlowRimVisual):
    """Rim GlowRim: batched GPU Blur halo + unfiltered ADD core. Host fill kept.

    Same package at every quality (no lite/survival fallback).
    """

    _VARIANT = "edgeglow_high"
    _DEFAULT_TINT = (0.55, 0.9, 1.0, 1.0)
    _KEEP_HOST_FILL = True
    _USE_WASH = False
    _BLEND_ADD = False
    _OVERLAY_BLEND_ADD = True
    _HIGH_SIGMA = 2.2
    _HIGH_WIDTH = 0.5
    _HIGH_HOT = 0.0
    _HIGH_CORE_A = 0.72
    _SPINE_WIDTH = 0.0
    _RIM_PASSES = 1

    def __new__(
        cls,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        width: float = 4.0,
        darken: float = 0.35,
    ):
        return GlowRimVisual.__new__(
            cls, color, amount=amount, width=width, darken=darken,
        )

    @classmethod
    def _intern_extra(cls, kw: dict) -> tuple:
        return (
            round(float(kw.get("width", 4.0)), 1),
            round(float(kw.get("darken", 0.35)), 2),
        )

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        amount: float = 1.0,
        width: float = 4.0,
        darken: float = 0.35,
    ):
        if getattr(self, "_ready", False):
            return
        self._init_glowrim(color, amount)
        self.width = max(0.5, float(width) * 2.0)
        self._core_width = max(1.0, float(width) * 0.45)
        self._core_alpha = 0.85 * float(amount)
        self.darken = float(darken)
        self._ready = True

    def _halo_rgb(self, rgb):
        return _soften_rim_rgb(rgb)

    def _draw_darken(self, shape, skia_canvas) -> None:
        if _is_line_shape(shape) or getattr(shape, "_rim_darkened", False):
            return
        d = max(0.0, min(0.85, float(self.darken)))
        if d <= 1e-3 or not _shape_has_fill(shape):
            return
        dark = skia.Paint(
            AntiAlias=True, Style=skia.Paint.kFill_Style,
            Color4f=skia.Color4f(0.0, 0.0, 0.0, d),
        )
        shape._geometry_draw(skia_canvas, fill_paint=dark, stroke_paint=None)

    def _draw_extra_rim(self, shape, skia_canvas) -> None:
        rgb = self._halo_rgb(self._tint_rgba(shape)[:3])
        core = _rim_core_rgb(rgb)
        paint = self._rim_skia_paint(
            core, self._core_alpha, self._core_width, **_host_stroke_knobs(shape),
        )
        self._stroke_at_scale(shape, skia_canvas, paint, 1.0)

    def _draw_overlays(self, shape, skia_canvas, rgb, *, glow_batched=False) -> None:
        self._draw_darken(shape, skia_canvas)
        self._draw_extra_rim(shape, skia_canvas)


class Rim(Recipe):
    """Highlight outline — GlowRim on Shape; SDF bands on Sprite.

    Same look at every quality: interned GPU ``Blur`` on a wide tinted stroke
    (batches) + unfiltered ADD core via ``_overlay_after_filters``. Solid fills
    bake ``darken`` into the host fill. **Sprite:** blit + SDF (no ImageFilter);
    v2 path if SDF is missing.

    Args:
        color: Rim color.
        amount: Strength.
        width: Thickness (default 4).
        darken: Darken the middle (default 0.35).
    """

    _color_role = "B"
    _allows_sprite = True
    _needs_sprite_path = True
    _needs_sprite_sdf = True  # Sprite render_sprite uses SDF bands
    _is_multipass = False
    _fidelity_sensitive = False

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0, width: float = 4.0, darken: float = 0.35):
        key = (
            "edgeglow", _tint_intern_key(color, (0.55, 0.9, 1.0, 1.0)),
            round(float(amount), 2), round(float(width), 1), round(float(darken), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0, width: float = 4.0, darken: float = 0.35):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.55, 0.9, 1.0, 1.0), channel=_TINT_OUTLINE)
        self.amount = float(amount)
        self.width = float(width)
        self.darken = float(darken)
        self._high = _RimHigh(color, amount=amount, width=width, darken=darken)
        self._ready = True

    def _unseed(self) -> Optional["Rim"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.width, self.darken)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return (
            "edgeglow", ckey,
            round(self.amount, 2), round(self.width, 1), round(self.darken, 2),
        )

    def _overlay_after_filters(self, shape, skia_canvas) -> None:
        self._high._overlay_after_filters(shape, skia_canvas)

    def _rim_rgb(self, shape) -> Tuple[float, float, float]:
        return _soften_rim_rgb(self._primary_tint(shape)[:3])

    def _bake_darken(self, shape) -> None:
        """Fold ``darken`` into a solid fill so the fill pass is already dimmed."""
        d = max(0.0, min(0.85, float(self.darken)))
        if d <= 1e-3 or _is_line_shape(shape) or _is_sprite(shape):
            return
        if getattr(shape, "_rim_darkened", False):
            return
        fill = getattr(shape, "_fill", None)
        if not isinstance(fill, Color) or not fill:
            return
        rgb = fill.rgb
        a = float(rgb[3]) if len(rgb) > 3 else 1.0
        shape.fill = Color(
            float(rgb[0]) * (1.0 - d),
            float(rgb[1]) * (1.0 - d),
            float(rgb[2]) * (1.0 - d),
            a,
        )
        shape._rim_darkened = True

    def _apply(self, shape) -> None:
        if _is_sprite(shape):
            super()._apply(shape)
            return
        self._high._apply(shape)
        self._bake_darken(shape)

    def _render_sprite_body(self, shape, skia_canvas) -> None:
        """SDF glow + blit + v2 core. Sprite only; Shape keeps GlowRim."""
        if is_stroke_type(shape):
            self._render(shape, skia_canvas)
            return
        r, g, b = self._rim_rgb(shape)
        _blit_sprite_body(shape, skia_canvas)
        sdf = getattr(shape, "_draw_sprite_sdf_bands", None)
        w = float(self.width)
        amt = float(self.amount)
        cr, cg, cb = _rim_core_rgb((r, g, b))
        if callable(sdf):
            ok = sdf(
                skia_canvas, (r, g, b, 1.0),
                glow_width=w * 2.4, glow_alpha=0.28 * amt,
                rim_width=w * 1.25, rim_alpha=0.55 * amt,
                core_width=0.0, core_alpha=0.0,
            )
            if ok:
                core = self._stroke_paint(
                    color=(cr, cg, cb, 0.85 * amt),
                    width=max(1.0, w * 0.45), blend=BlendMode.ADD,
                    **_host_stroke_knobs(shape),
                )
                _stroke_host_v2(skia_canvas, shape, core)
                return
        self._stroke_rim_fallback(shape, skia_canvas, r, g, b, cr, cg, cb)

    def _stroke_rim_fallback(self, shape, skia_canvas, r, g, b, cr, cg, cb) -> None:
        """v2 silhouette stack when SDF is unavailable (no MaskFilter)."""
        amt = float(self.amount)
        w = float(self.width)
        knobs = _host_stroke_knobs(shape)
        glow = self._stroke_paint(
            color=(r, g, b, 0.28 * amt),
            width=w * 2.4, blend=BlendMode.ADD, **knobs,
        )
        mid = self._stroke_paint(
            color=(r, g, b, 0.55 * amt),
            width=w * 1.25, blend=BlendMode.ADD, **knobs,
        )
        core = self._stroke_paint(
            color=(cr, cg, cb, 0.85 * amt),
            width=max(1.0, w * 0.45), blend=BlendMode.ADD, **knobs,
        )
        _stroke_host_v2(skia_canvas, shape, glow)
        _stroke_host_v2(skia_canvas, shape, mid)
        _stroke_host_v2(skia_canvas, shape, core)

    def _render(self, shape, skia_canvas) -> None:
        _apply_at_draw(shape, self._draw_package, shape)
        self._high._render(shape, skia_canvas)

    def _draw_package(self, shape) -> None:
        self._high._apply(shape)
        self._bake_darken(shape)


# ---------------------------------------------------------------------------
# Motion / frame looks (Tail, Beat, InsetRim)
# ---------------------------------------------------------------------------


_TAIL_ANGLE_UNSET = Unset("<auto>")
# Default length when ``size`` is omitted (follow / Tail() / tail=angle).
_TAIL_DEFAULT_SIZE = 1.2


class Tail(Recipe):
    """Ghost motion trail: faded copies along ``angle``, then host body.

    ``angle`` is where the trail extends in degrees (0 = right, 90 = up).
    Omit ``angle`` (or assign ``shape.tail = True``) to follow smoothed center
    velocity: the trail stays behind motion and length tracks speed (collapses
    when stopped; shrinks through zero on reverse). Omit ``size`` (or pass
    ``True`` / a bare angle) for the catalog default 1.6. Accept any real angle
    (``-90`` ≡ ``270``); callables link live fields.

    Role E: ``color=`` tints trail ghosts only. Does not rewrite host style.
    On ``Sprite``, ghosts the current frame (not a solid disc).
    Assign with ``shape.tail = Tail(...)`` — not ``.visual``.

    Args:
        color: Tint for the ghost copies only.
        angle: Omit to follow the motion; degrees (or a function) to lock it.
        size: Length (number or function; default 1.2).
        amount: Opacity of the copies (number or function; default 1).
    """

    # Knobs that may be a live formula (``amount=lambda: speed / 10``).
    _formula_knobs = frozenset({"amount", "size"})

    _color_role = "E"
    _allows_sprite = True

    _tint_channel = None

    def __new__(
        cls,
        color=None,
        angle=_TAIL_ANGLE_UNSET,
        size: float = _TAIL_DEFAULT_SIZE,
        amount: float = 1.0,
    ):
        ang_fn = callable(angle) and not isinstance(angle, type) and angle is not _TAIL_ANGLE_UNSET
        size_fn = callable(size) and not isinstance(size, type)
        amount_fn = callable(amount) and not isinstance(amount, type)
        follow = angle is _TAIL_ANGLE_UNSET
        if ang_fn or size_fn or amount_fn or follow:
            # Unique instance — formulas / follow are per-host, not interned.
            return object.__new__(cls)
        from .validate import number
        ang = number(angle, "Tail angle") % 360.0
        key = (
            "tail", _tint_intern_key(color, (0.6, 0.85, 1.0, 1.0)),
            round(ang, 1), round(float(size), 2),
            round(float(amount), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(
        self,
        color=None,
        angle=_TAIL_ANGLE_UNSET,
        size: float = _TAIL_DEFAULT_SIZE,
        amount: float = 1.0,
    ):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.6, 0.85, 1.0, 1.0), channel=None)
        ang_fn = (
            angle
            if (callable(angle) and not isinstance(angle, type) and angle is not _TAIL_ANGLE_UNSET)
            else None
        )
        size_fn = size if callable(size) and not isinstance(size, type) else None
        amount_fn = amount if callable(amount) and not isinstance(amount, type) else None
        follow = angle is _TAIL_ANGLE_UNSET
        self._stamp_follow = follow and ang_fn is None
        self._stamp_angle_fn = ang_fn
        self._stamp_size_fn = size_fn
        self._stamp_amount_fn = amount_fn
        if ang_fn is not None:
            self.angle = 0.0
        elif follow:
            self.angle = 0.0
        else:
            self.angle = float(angle)
        self.size = 1.0 if size_fn is not None else max(0.15, float(size))
        self.amount = 1.0 if amount_fn is not None else max(0.05, float(amount))
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return (
            "tail", ckey, round(float(self.angle) % 360.0, 1), round(self.size, 2),
            round(self.amount, 2),
        )

    def _apply(self, shape) -> None:
        """Trail only — stamp path does not rewrite filters (costume owns them)."""
        pass

    def _render(self, shape, skia_canvas) -> None:
        """Legacy multipass path if Tail were still a costume (tests / fallback)."""
        from .stamps import draw_tail_ghosts
        draw_tail_ghosts(
            shape, skia_canvas,
            angle=float(self.angle), size=float(self.size), amount=float(self.amount),
            look=self,
        )
        shape._geometry_draw(skia_canvas)


class Beat(Recipe):
    """Breathing scale loop about the shape pivot — multiplies over host scale.

    Role E (motion only) with ``color=None``: keeps the host fill, line and
    width. ``color=`` seeds the body like ``Neon`` (Role A): the shape takes
    that color, ``visual = None`` keeps it, a later ``set_color`` wins.
    Shape-only when seeded (a Sprite keeps its pixels).

    Args:
        color: Body color (default: keep the shape's own).
        amount: How much it grows on each beat (default 0.08).
        speed: Rhythm.
    """

    _color_role = "E"
    _allows_sprite = True
    _sprite_takes_color = False

    _tint_channel = None

    def __new__(cls, color=None, amount: float = 0.08, speed: float = 1.0):
        _refuse_number_as_color("Beat", color, "amount")
        key = (
            "pulsescale", _tint_intern_key(color, _BEAT_DEFAULT),
            round(float(amount), 3), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color=None, amount: float = 0.08, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, _BEAT_DEFAULT, channel=None)
        # Seeded → Role A (identity body, like Neon); unseeded stays motion-only.
        self._color_role = "E" if self._seed_color is None else "A"
        self.amount = max(0.0, min(0.5, float(amount)))
        self.speed = max(0.05, float(speed))
        self._ready = True

    def _unseed(self) -> Optional["Beat"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("pulsescale", ckey, round(self.amount, 3), round(self.speed, 2))

    def _apply(self, shape) -> None:
        """Scale envelope; rewrites only the body color, and only when seeded."""
        super()._apply(shape)

    def _render(self, shape, skia_canvas) -> None:
        cx, cy, _ = _center_radius(shape)
        s = 1.0 + self.amount * math.sin(_clock() * self.speed * (2.0 * math.pi))
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        skia_canvas.scale(s, s)
        skia_canvas.translate(-cx, -cy)
        shape._geometry_draw(skia_canvas)
        skia_canvas.restore()


class InsetRim(Recipe):
    """Inset fill (default 80%) plus a single outline.

    Role B (outline). Leaves a visible gap between body and stroke.
    Shape-only (not on ``Sprite``).

    Args:
        color: Rim color.
        fill_scale: How much the middle shrinks (default 0.8).
        width: Rim thickness (default 6).
        amount: Strength (default 0.3).
    """

    _color_role = "B"

    def __new__(
        cls,
        color=None,
        fill_scale: float = 0.8,
        width: Optional[float] = 6.0,
        amount: float = 0.3,
    ):
        bw = None if width is None else round(float(width), 2)
        key = (
            "insetrim", _tint_intern_key(color, (0.5, 0.75, 0.95, 1.0)),
            round(float(fill_scale), 3), bw,
            round(float(amount), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(
        self,
        color=None,
        fill_scale: float = 0.8,
        width: Optional[float] = 6.0,
        amount: float = 0.3,
    ):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.5, 0.75, 0.95, 1.0), channel=_TINT_OUTLINE)
        self.fill_scale = max(0.2, min(1.0, float(fill_scale)))
        self.width = None if width is None else float(width)
        self.amount = max(0.05, float(amount))
        self._ready = True

    def _unseed(self) -> Optional["InsetRim"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.fill_scale, self.width, self.amount)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        bw = None if self.width is None else round(self.width, 2)
        return (
            "insetrim", ckey, round(self.fill_scale, 3), bw,
            round(self.amount, 2),
        )

    def _outline_width(self, shape) -> float:
        # Default width=6.0 × amount=0.3 → 1.8 drawn outline.
        base_w = float(self.width) if self.width is not None else 6.0
        return max(0.8, base_w * self.amount)

    def _apply(self, shape) -> None:
        super()._apply(shape)
        _set_line_width(shape, self._outline_width(shape))

    def _render(self, shape, skia_canvas) -> None:
        tint = self._primary_tint(shape)
        fs = self.fill_scale
        if not _is_line_shape(shape) and _shape_has_fill(shape):
            host = _host_fill_paint(shape)
            if host is not None:
                _ff_best_effort_pass(
                    shape, skia_canvas, fill_paint=host, stroke_paint=None, scale=fs,
                )
            else:
                fill = self._fill_paint_from(tint)
                _ff_best_effort_pass(
                    shape, skia_canvas, fill_paint=fill, stroke_paint=None, scale=fs,
                )
        elif _is_line_shape(shape):
            # Lines: draw a thinner underlay as "inset", then border stroke.
            knobs = _host_stroke_knobs(shape)
            under = self._stroke_paint(
                color=tint, width=self._outline_width(shape) * fs * 0.85,
                alpha=(tint[3] if len(tint) > 3 else 1.0) * 0.85,
                **knobs,
            )
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=under)

        base_w = self._outline_width(shape)
        border = self._stroke_paint(
            color=tint, width=base_w, **_host_stroke_knobs(shape),
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=border)


class Gel(Recipe):
    """Translucent candy: tinted body + bright rim (2-pass).

    Args:
        color: Tint (any color form; default: follows the shape's own color).
        amount: Strength.
    """

    _color_role = "A"

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0):
        key = (
            "gel", _tint_intern_key(color, (0.35, 0.85, 0.75, 1.0)),
            round(float(amount), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0):
        if getattr(self, "_ready", False):
            return
        self._init_tint(color, (0.35, 0.85, 0.75, 1.0), channel=_TINT_BODY)
        self.amount = float(amount)
        self._ready = True

    def _unseed(self) -> Optional["Gel"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("gel", ckey, round(self.amount, 2))

    def _apply(self, shape) -> None:
        super()._apply(shape)
        _set_line_width(shape, _OUTLINE_GEL)

    def _render(self, shape, skia_canvas) -> None:
        tint = self._primary_tint(shape)
        knobs = _host_stroke_knobs(shape)
        if _is_line_shape(shape):
            shape._geometry_draw(
                skia_canvas, fill_paint=None,
                stroke_paint=self._stroke_paint(
                    color=(*tint[:3], 0.7), width=_OUTLINE_GEL, **knobs,
                ),
            )
            return
        body = self._fill_paint_from((
            min(1.0, tint[0] * 0.85 + 0.1),
            min(1.0, tint[1] * 0.85 + 0.1),
            min(1.0, tint[2] * 0.85 + 0.1),
            0.62 * self.amount,
        ))
        shape._geometry_draw(skia_canvas, fill_paint=body, stroke_paint=None)
        rim = self._stroke_paint(
            color=(
                min(1.0, tint[0] * 0.5 + 0.5),
                min(1.0, tint[1] * 0.5 + 0.5),
                min(1.0, tint[2] * 0.5 + 0.5),
                0.65,
            ),
            width=_OUTLINE_GEL, blend=BlendMode.ADD, **knobs,
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=rim)



def _shift_palette(palette: dict, base: str, tint) -> dict:
    """``palette`` rotated so its ``base`` slot lands on ``tint``.

    Every other slot keeps its offset from the base: hue added, saturation
    and value scaled (HSV). A grey tint gives a grey palette. The look's own
    palette is passed as is, never through here, so "no color" stays exact.
    """
    bh, bs, bv = colorsys.rgb_to_hsv(*palette[base][:3])
    th, ts, tv = colorsys.rgb_to_hsv(*(float(c) for c in tint[:3]))
    out = {}
    for name, rgb in palette.items():
        h, s, v = colorsys.rgb_to_hsv(*rgb[:3])
        out[name] = colorsys.hsv_to_rgb(
            (th + h - bh) % 1.0,
            min(1.0, s * ts / bs) if bs > 0 else ts,
            min(1.0, v * tv / bv) if bv > 0 else tv,
        )
    return out


def _metal_tint(fill) -> list:
    """The metal shader's ``u_tint``: rgb + 1 for ``Metal(color)``, zeros (chrome) without."""
    rgb = (getattr(fill, "_extra_rgb", None) or {}).get("tint")
    return [0.0, 0.0, 0.0, 0.0] if rgb is None else [*rgb, 1.0]


def _metal_edge(tint) -> Tuple[float, float, float, float]:
    """Rim for a tinted metal: 60 % from the shader's tinted base toward its
    tinted highlight, the place the chrome rim holds between chrome's own
    (``_METAL_EDGE`` ~ mix(0.50, 0.92, 0.6)). Before 2026-10-13 a gold Metal
    kept the chrome rim."""
    if tint is None:
        return _METAL_EDGE
    r, g, b = (float(c) for c in tint[:3])
    return (0.68 * r + 0.3, 0.68 * g + 0.3, 0.68 * b + 0.3, _METAL_EDGE[3])


class Metal(Recipe):
    """Chrome: brushed metal fill + shared world light + chrome rim.

    Palette look (Role A): ``Metal()`` is chrome whatever the shape's color;
    ``Metal(color)`` tints body and rim and becomes the shape's color.
    ``set_color`` retints either one live (the look swaps to its
    shape-following sibling, ``_FOLLOW_SHAPE``). Grain is painted on the body
    (rotates with the shape). On ``Sprite``: fills the alpha silhouette
    (replaces the bitmap).

    Args:
        color: Tint (any color form; default: chrome, whatever the shape's
            own color — ``Metal("gold")`` for a gold metal).
        amount: Grain.
        speed: Shimmer speed (0 freezes the grain).
    """

    _color_role = "A"
    _allows_sprite = True
    _replaces_sprite_body = True

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0, speed: float = 1.0):
        if color is None:
            ckey = ("chrome",)
        elif color is _FOLLOW_SHAPE:
            ckey = ("host",)
        else:
            c = Color(color)
            ckey = tuple(round(float(x), 3) for x in c.rgb)
        key = ("metal", ckey, round(float(amount), 2), round(float(speed), 2))
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        from .style import ProceduralFill
        self._follows_shape = color is _FOLLOW_SHAPE
        self._metal_seed = None if color is None or self._follows_shape else Color(color)
        self.amount = float(amount)
        self.speed = float(speed)
        fill_speed = 1.15 * self.speed if self.speed > 0 else 0.0
        self._fill = ProceduralFill(
            kind="metal", amount=self.amount, speed=fill_speed,
        )
        # Per-look tint and rim, resolved once (the shape-following sibling
        # reads its tint per draw).
        self._seed_rgb = None
        if self._metal_seed is not None:
            self._seed_rgb = tuple(float(c) for c in self._metal_seed.rgb[:3])
            # The shader mixes its chrome palette toward the tint. Before
            # 2026-10-09 the tint never reached it: Metal("gold") drew silver.
            self._fill._extra_rgb = {"tint": self._seed_rgb}
        self._edge = _metal_edge(self._seed_rgb)
        self._ready = True

    @property
    def _batch_key(self) -> tuple:
        if self._follows_shape:
            ckey = ("host",)
        elif self._metal_seed is None:
            ckey = ("chrome",)
        else:
            ckey = tuple(round(c, 3) for c in self._metal_seed.rgb)
        return ("metal", ckey, round(self.amount, 2), round(self.speed, 2))

    def _unseed(self) -> Optional["Metal"]:
        # A palette look's recolor sibling tints from the shape (one interned
        # instance for every colour): chrome is not "unseeded" here, it would
        # drop the colour set_color just wrote (silent before 2026-10-13).
        if self._follows_shape:
            return None
        return type(self)(_FOLLOW_SHAPE, self.amount, self.speed)

    def _live_tint(self, shape) -> Optional[Tuple[float, float, float]]:
        """Shape-following sibling: the shape's live color (None: chrome)."""
        live = sample_body_rgba(shape)
        if live is None:
            return None
        return (float(live[0]), float(live[1]), float(live[2]))

    def _apply(self, shape) -> None:
        # Metal has no tint_channel seed path — still install standard outline.
        try:
            shape.fill_filter = None
            shape.line_filter = None
        except Exception:
            pass
        if self._metal_seed is not None:
            rgba = tuple(float(c) for c in self._metal_seed.rgb)
            _write_role_color(shape, "A", rgba)
        _set_line_width(shape, _OUTLINE_METAL)

    def _identity_patch(self, shape) -> None:
        if self._metal_seed is None:
            return
        fn = getattr(shape, "_identity_patch_seed", None)
        if fn is not None:
            rgba = tuple(float(c) for c in self._metal_seed.rgb)
            fn(rgba, channel="auto")

    def _render(self, shape, skia_canvas) -> None:
        cx, cy, r = _center_radius(shape)
        edge = self._edge
        if self._follows_shape:
            tint = self._live_tint(shape)
            edge = _metal_edge(tint)
            # One shared fill for every shape on this sibling: set its tint
            # just before the shader is built (draws are sequential).
            self._fill._extra_rgb = None if tint is None else {"tint": tint}
        rim = self._stroke_paint(
            color=edge, width=_OUTLINE_METAL, **_host_stroke_knobs(shape),
        )
        if _is_line_shape(shape):
            shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=rim)
            return

        rv = getattr(shape, "_rotation_value", None)
        rot = float(rv()) if callable(rv) else 0.0
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
        paint.setShader(
            _procedural_shader(
                self._fill, cx, cy, r,
                rot_deg=rot, light_deg=get_metal_light(),
            )
        )
        shape._geometry_draw(skia_canvas, fill_paint=paint, stroke_paint=rim)


class Sphere(Recipe):
    """Fake 3D orb lighting. Primary tint from host fill (``color=`` seeds once).

    Args:
        color: Tint (any color form; default: follows the shape's own color).
        amount: Relief.
        speed: Light sweep speed (default 0.5).
    """

    _color_role = "A"

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0, speed: float = 0.5):
        key = (
            "sphere", _tint_intern_key(color, (0.35, 0.55, 0.85, 1.0)),
            round(float(amount), 2), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0, speed: float = 0.5):
        if getattr(self, "_ready", False):
            return
        from .style import ProceduralFill
        self._init_tint(color, (0.35, 0.55, 0.85, 1.0), channel=_TINT_BODY)
        self.amount = float(amount)
        self.speed = float(speed)
        self._fill = ProceduralFill(
            kind="sphere", amount=self.amount, speed=self.speed, color=self.color[:3],
        )
        self._ready = True

    def _unseed(self) -> Optional["Sphere"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("sphere", ckey, round(self.amount, 2), round(self.speed, 2))

    def _render(self, shape, skia_canvas) -> None:
        cx, cy, r = _center_radius(shape)
        if _is_line_shape(shape):
            shape._geometry_draw(skia_canvas)
            return
        tint = self._primary_tint(shape)
        knobs = _host_stroke_knobs(shape)
        _apply_live_fill_color(self._fill, tint[:3])
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
        paint.setShader(_procedural_shader(self._fill, cx, cy, r))
        shape._geometry_draw(skia_canvas, fill_paint=paint, stroke_paint=None)
        rim = self._stroke_paint(
            color=(0.05, 0.08, 0.12, 0.35), width=1.2, **knobs,
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=rim)
        hi = self._stroke_paint(
            color=(1.0, 1.0, 1.0, 0.18 * self.amount), width=1.0,
            blend=BlendMode.ADD, **knobs,
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=hi)


# ---------------------------------------------------------------------------
# Wave / Aurora multipass (host-tinted procedural body + ADD rim)
# ---------------------------------------------------------------------------

class Wave(Recipe):
    """Host-tinted WaveFill body + soft ADD rim (multipass).

    On ``Sprite``: fills the alpha silhouette (replaces the bitmap).

    Args:
        color: Liquid tint (default: follows the fill).
        amount: Strength.
        speed: Animation speed.
    """

    _color_role = "A"
    _allows_sprite = True
    _replaces_sprite_body = True

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0, speed: float = 1.0):
        key = (
            "wave", _tint_intern_key(color, (0.15, 0.55, 0.85, 1.0)),
            round(float(amount), 2), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0, speed: float = 1.0):
        if getattr(self, "_ready", False):
            return
        from .style import WaveFill
        self._init_tint(color, (0.15, 0.55, 0.85, 1.0), channel=_TINT_BODY)
        self.amount = float(amount)
        self.speed = float(speed)
        self._fill = WaveFill(color=self.color[:3], amount=self.amount, speed=self.speed)
        self._ready = True

    def _unseed(self) -> Optional["Wave"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("wave", ckey, round(self.amount, 2), round(self.speed, 2))

    def _apply(self, shape) -> None:
        super()._apply(shape)
        _set_line_width(shape, _OUTLINE_WAVE)

    def _render(self, shape, skia_canvas) -> None:
        if _is_line_shape(shape):
            shape._geometry_draw(skia_canvas)
            return
        cx, cy, r = _center_radius(shape)
        tint = self._primary_tint(shape)
        _apply_live_fill_color(self._fill, tint[:3])
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
        paint.setShader(_procedural_shader(self._fill, cx, cy, r))
        shape._geometry_draw(skia_canvas, fill_paint=paint, stroke_paint=None)
        rim = self._stroke_paint(
            color=(*tint[:3], 0.55), width=_OUTLINE_WAVE, blend=BlendMode.ADD,
            alpha=0.45, **_host_stroke_knobs(shape),
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=rim)


class Aurora(Recipe):
    """Host-tinted AuroraFill body + soft ADD rim (multipass).

    On ``Sprite``: fills the alpha silhouette (replaces the bitmap).

    Args:
        color: Tint (any color form; default: follows the shape's own color).
        amount: Strength (1 = default).
        speed: Animation speed (default 0.9).
    """

    _color_role = "A"
    _allows_sprite = True
    _replaces_sprite_body = True

    def __new__(cls, color: Optional[ColorLike] = None, amount: float = 1.0, speed: float = 0.9):
        key = (
            "aurora", _tint_intern_key(color, (0.25, 0.9, 0.55, 1.0)),
            round(float(amount), 2), round(float(speed), 2),
        )
        return _intern(cls, key, lambda: object.__new__(cls))

    def __init__(self, color: Optional[ColorLike] = None, amount: float = 1.0, speed: float = 0.9):
        if getattr(self, "_ready", False):
            return
        from .style import AuroraFill
        self._init_tint(color, (0.25, 0.9, 0.55, 1.0), channel=_TINT_BODY)
        self.amount = float(amount)
        self.speed = float(speed)
        self._fill = AuroraFill(color=self.color[:3], amount=self.amount, speed=self.speed)
        self._ready = True

    def _unseed(self) -> Optional["Aurora"]:
        if self._seed_color is None:
            return None
        return type(self)(None, self.amount, self.speed)

    @property
    def _batch_key(self) -> tuple:
        ckey = ("host",) if self._seed_color is None else tuple(round(c, 3) for c in self.color)
        return ("aurora", ckey, round(self.amount, 2), round(self.speed, 2))

    def _apply(self, shape) -> None:
        super()._apply(shape)
        _set_line_width(shape, _OUTLINE_AURORA)

    def _render(self, shape, skia_canvas) -> None:
        if _is_line_shape(shape):
            shape._geometry_draw(skia_canvas)
            return
        cx, cy, r = _center_radius(shape)
        tint = self._primary_tint(shape)
        _apply_live_fill_color(self._fill, tint[:3])
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
        paint.setShader(_procedural_shader(self._fill, cx, cy, r))
        shape._geometry_draw(skia_canvas, fill_paint=paint, stroke_paint=None)
        rim = self._stroke_paint(
            color=(*tint[:3], 0.55), width=_OUTLINE_AURORA, blend=BlendMode.ADD,
            alpha=0.5, **_host_stroke_knobs(shape),
        )
        shape._geometry_draw(skia_canvas, fill_paint=None, stroke_paint=rim)


# Compiled material / shell visuals (single-pass) live in visuals.py
from .visuals import Swell, Flame, Halo
from .state import probe_private


__all__ = [
    "Recipe",
    "Neon", "MultiBorder", "Extrude",
    "DashRing", "GearShell",
    "ElectricField",
    "Shield",
    "OrganicOutline", "Tracer", "ElectricBolt",
    "Swell", "Water", "Flame", "Metal",
    "Wave", "Aurora", "Liquify", "Bolt",
    "Laser",
    "Ink", "InkBleed", "Sphere", "Rim", "Gel", "Recolor",
    "Tail", "Beat", "InsetRim",
    "set_extrude_focus", "get_extrude_focus",
    "set_metal_light", "get_metal_light",
]
