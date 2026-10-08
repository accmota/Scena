"""
Built-in canvas-wide post effects for Scena.

Gradual params: each effect looks good with zero arguments. Authors never
write SkSL — curated shader effects live in ``_sksl_effects`` and are
re-exported here as ordinary classes.
"""
from __future__ import annotations

import math
import random
from typing import Optional, Sequence, Tuple, Union

import numpy as np
import skia

from .postfx import PostEffect, PostEffectStage
from .color import resolve_rgb
from .fx_quality import fidelity_is_survival, fidelity_is_lite, particle_scale
from .validate import expect_choice
from .validate import expect_bool as _expect_flag

# Re-export SkSL effects so ``from scena import Prism`` works.
from ._sksl_effects import (  # noqa: F401
    Prism, Perspective, Lamp, GodRays, Haze, Spotlight, DistantLight,
    Kaleidoscope, draw_ripple_shader, draw_glitch_shader,
    Crt, Vortex, ZoomBlur, Chroma, draw_scanlines_multiply,
    ColorSweep, ColorWash, CosmicBloom,
)


# ---------------------------------------------------------------------------
# OVERLAY
# ---------------------------------------------------------------------------

class Vignette(PostEffect):
    """Darken frame edges with gradient strips (SrcOver) — center stays sharp.

    Edge-strip recipe (formerly Lite). ``_quality_sensitive=False`` so hybrid
    compose never soft-upscales the whole scene.

    Args:
        amount: Strength (default 1).
        thickness: Border fraction that darkens (default 0.22).
    """

    _stage = PostEffectStage.OVERLAY
    _quality_sensitive = False

    def __init__(self, amount: float = 1.0, thickness: float = 0.22):
        self.amount = float(amount)
        self.thickness = float(thickness)  # fraction of min(w,h) from each edge
        self._shaders = None  # (key, top, bot, left, right, paints) cache

    def _fx_cache_key(self) -> tuple:
        return ("vignette", round(self.amount, 3), round(self.thickness, 3))

    def _ensure_edge_shaders(self, w: float, h: float):
        a = max(0.0, min(1.0, self.amount))
        t_edge = max(8.0, min(w, h) * max(0.08, min(0.4, self.thickness)))
        key = (int(w), int(h), round(a, 3), round(t_edge, 1))
        if self._shaders is not None and self._shaders[0] == key:
            return self._shaders
        top = skia.GradientShader.MakeLinear(
            [(0, 0), (0, t_edge)],
            [skia.Color4f(0, 0, 0, 0.55 * a), skia.Color4f(0, 0, 0, 0.0)],
            [0.0, 1.0],
        )
        bot = skia.GradientShader.MakeLinear(
            [(0, h), (0, h - t_edge)],
            [skia.Color4f(0, 0, 0, 0.55 * a), skia.Color4f(0, 0, 0, 0.0)],
            [0.0, 1.0],
        )
        left = skia.GradientShader.MakeLinear(
            [(0, 0), (t_edge, 0)],
            [skia.Color4f(0, 0, 0, 0.45 * a), skia.Color4f(0, 0, 0, 0.0)],
            [0.0, 1.0],
        )
        right = skia.GradientShader.MakeLinear(
            [(w, 0), (w - t_edge, 0)],
            [skia.Color4f(0, 0, 0, 0.45 * a), skia.Color4f(0, 0, 0, 0.0)],
            [0.0, 1.0],
        )
        paints = (
            skia.Paint(Shader=top, BlendMode=skia.BlendMode.kSrcOver, AntiAlias=False),
            skia.Paint(Shader=bot, BlendMode=skia.BlendMode.kSrcOver, AntiAlias=False),
            skia.Paint(Shader=left, BlendMode=skia.BlendMode.kSrcOver, AntiAlias=False),
            skia.Paint(Shader=right, BlendMode=skia.BlendMode.kSrcOver, AntiAlias=False),
        )
        self._shaders = (key, t_edge, paints)
        return self._shaders

    def _draw_overlay(self, canvas, w, h, t) -> None:
        if self.amount <= 0:
            return
        _, t_edge, paints = self._ensure_edge_shaders(w, h)
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, w, t_edge), paints[0])
        canvas.drawRect(skia.Rect.MakeXYWH(0, h - t_edge, w, t_edge), paints[1])
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, t_edge, h), paints[2])
        canvas.drawRect(skia.Rect.MakeXYWH(w - t_edge, 0, t_edge, h), paints[3])


class Grain(PostEffect):
    """Animated film grain (Plus blend — nearly free vs SoftLight).

    Args:
        amount: Grain opacity (default 0.07).
    """

    _stage = PostEffectStage.OVERLAY
    _quality_sensitive = False  # cheap; keep full-res

    def __init__(self, amount: float = 0.07):
        self.amount = float(amount)
        self._image = None

    def _fx_cache_key(self) -> tuple:
        return ("grain", round(self.amount, 3))

    def _ensure_image(self):
        if self._image is not None:
            return self._image
        rng = np.random.default_rng(7)
        noise = rng.integers(0, 255, (128, 128), dtype=np.uint8)
        rgba = np.dstack([noise, noise, noise, np.full_like(noise, 255)])
        self._image = skia.Image.fromarray(rgba, colorType=skia.kRGBA_8888_ColorType)
        return self._image

    def _draw_overlay(self, canvas, w, h, t) -> None:
        if self.amount <= 0:
            return
        img = self._ensure_image()
        m = skia.Matrix.Translate((t * 90.0) % 128.0, (t * 60.0) % 128.0)
        shader = img.makeShader(
            skia.TileMode.kRepeat, skia.TileMode.kRepeat,
            skia.SamplingOptions(), m,
        )
        paint = skia.Paint(
            Shader=shader,
            Alphaf=float(self.amount),
            BlendMode=skia.BlendMode.kPlus,
        )
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


class Scanlines(PostEffect):
    """CRT-style horizontal scanlines (Multiply).

    Nearest-tiled design-pixel bands (visible at Full/Retina). Marked
    ``_quality_sensitive`` so Balanced draws on the half-res overlay plate
    (cheap fill-rate); Full keeps sharp full-res bands.

    Args:
        amount: Strength (default 1).
    """

    _stage = PostEffectStage.OVERLAY
    _quality_sensitive = True

    def __init__(self, amount: float = 1.0):
        self.amount = float(amount)

    def _fx_cache_key(self) -> tuple:
        return ("scanlines", round(self.amount, 3))

    def _draw_overlay(self, canvas, w, h, t) -> None:
        draw_scanlines_multiply(canvas, w, h, self.amount)


class Fog(PostEffect):
    """Atmospheric mist: bottom-weighted soft wash (OVERLAY).

    Args:
        amount: Density (default 0.45).
        color: Fog color.
        height: How far up the screen it reaches (default 0.55).
    """

    _stage = PostEffectStage.OVERLAY
    _quality_sensitive = True

    def __init__(
        self,
        amount: float = 0.45,
        color: Tuple[float, float, float] = (0.75, 0.82, 0.9),
        height: float = 0.55,
    ):
        self.amount = float(amount)
        self.color = resolve_rgb(color, default=(0.75, 0.82, 0.9))
        self.height = float(height)
        self._shader = None
        self._size = None

    def _fx_cache_key(self) -> tuple:
        return (
            "fog",
            round(self.amount, 3),
            tuple(round(c, 3) for c in self.color),
            round(self.height, 3),
        )

    def _ensure_shader(self, w: float, h: float):
        key = (
            int(w), int(h), round(self.amount, 3),
            tuple(round(c, 3) for c in self.color),
            round(self.height, 3),
        )
        if self._shader is not None and self._size == key:
            return self._shader
        # FB y-down: fog denser toward bottom (y → h).
        top = max(0.0, h * (1.0 - self.height))
        r, g, b = self.color
        a = max(0.0, min(1.0, self.amount))
        colors = [
            skia.Color4f(r, g, b, 0.0),
            skia.Color4f(r, g, b, 0.35 * a),
            skia.Color4f(r, g, b, 0.85 * a),
        ]
        self._shader = skia.GradientShader.MakeLinear(
            [(w * 0.5, top), (w * 0.5, h)],
            colors,
            [0.0, 0.45, 1.0],
            skia.TileMode.kClamp,
        )
        self._size = key
        return self._shader

    def _draw_overlay(self, canvas, w, h, t) -> None:
        if self.amount <= 0:
            return
        shader = self._ensure_shader(w, h)
        paint = skia.Paint(
            Shader=shader,
            BlendMode=skia.BlendMode.kSrcOver,
            AntiAlias=False,
        )
        canvas.drawRect(skia.Rect.MakeWH(w, h), paint)


# ---------------------------------------------------------------------------
# ADDITIVE
# ---------------------------------------------------------------------------

_BRIGHT_MATRIX = [
    1.6, 0, 0, 0, -0.45,
    0, 1.6, 0, 0, -0.45,
    0, 0, 1.6, 0, -0.45,
    0, 0, 0, 1, 0,
]


class Bloom(PostEffect):
    """Bright-extract + blur, Plus-blended over the scene.

    Larger σ is often *faster* (Skia downsamples) and looks better for glow.

    Args:
        intensity: Strength (default 0.6).
        sigma: Blur (default 10).
    """

    _stage = PostEffectStage.ADDITIVE
    _quality_sensitive = True

    def __init__(self, intensity: float = 0.6, sigma: float = 10.0):
        self.intensity = float(intensity)
        self.sigma = float(sigma)

    def _fx_cache_key(self) -> tuple:
        return ("bloom", round(self.intensity, 3), round(self.sigma, 2))

    def _build_additive(self, inp, scale: float = 1.0):
        if self.intensity <= 0:
            return None
        sig = self.sigma * max(scale, 0.35)
        bright = skia.ImageFilters.ColorFilter(
            skia.ColorFilters.Matrix(_BRIGHT_MATRIX), inp
        )
        blurred = skia.ImageFilters.Blur(sig, sig, skia.TileMode.kDecal, bright)
        # Intensity via alpha matrix on the glow
        if abs(self.intensity - 1.0) > 1e-3:
            s = float(self.intensity)
            m = [s, 0, 0, 0, 0, 0, s, 0, 0, 0, 0, 0, s, 0, 0, 0, 0, 0, 1, 0]
            blurred = skia.ImageFilters.ColorFilter(
                skia.ColorFilters.Matrix(m), blurred
            )
        return blurred


# ---------------------------------------------------------------------------
# COLOR
# ---------------------------------------------------------------------------

_GRADE_PRESETS = {
    # Punchy defaults — near-identity matrices are invisible in the lab.
    "filmic": [
        1.18, -0.04, -0.02, 0, 0.02,
        -0.03, 1.12, -0.02, 0, 0.01,
        -0.02, -0.04, 0.98, 0, 0.03,
        0, 0, 0, 1, 0,
    ],
    "cool": [
        0.62, 0.05, 0.08, 0, 0.02,
        0.04, 0.82, 0.10, 0, 0.03,
        0.06, 0.10, 1.35, 0, 0.06,
        0, 0, 0, 1, 0,
    ],
    "warm": [
        1.35, 0.08, 0.0, 0, 0.05,
        0.06, 1.05, 0.02, 0, 0.02,
        0.0, 0.02, 0.70, 0, -0.03,
        0, 0, 0, 1, 0,
    ],
    "sepia": [
        0.393, 0.769, 0.189, 0, 0.02,
        0.349, 0.686, 0.168, 0, 0.01,
        0.272, 0.534, 0.131, 0, 0.0,
        0, 0, 0, 1, 0,
    ],
    "bw": [
        0.299, 0.587, 0.114, 0, 0,
        0.299, 0.587, 0.114, 0, 0,
        0.299, 0.587, 0.114, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "duo": [
        1.15, 0.25, 0.05, 0, 0.03,
        0.08, 0.45, 0.55, 0, 0.02,
        0.05, 0.35, 1.25, 0, 0.05,
        0, 0, 0, 1, 0,
    ],
    "night": [
        0.40, 0.05, 0.12, 0, -0.06,
        0.04, 0.50, 0.18, 0, -0.04,
        0.08, 0.15, 1.20, 0, 0.08,
        0, 0, 0, 1, 0,
    ],
}


class Grade(PostEffect):
    """Color-matrix grade. Named presets or a custom 20-float matrix.

    Default preset ``filmic`` is intentionally visible (contrast + warmth).

    Args:
        preset: ``"filmic"`` (default) · ``"cool"`` · ``"warm"`` · ``"sepia"`` ·
            ``"bw"`` · ``"duo"`` · ``"night"``.
        brightness: Offset (default 0).
        contrast: Contrast (default 1).
        saturation: Saturation (default 1).
        matrix: Your own 4×5 color matrix (20 numbers); ``None`` = the preset.
    """

    _stage = PostEffectStage.COLOR
    _quality_sensitive = False

    def __init__(
        self,
        preset: str = "filmic",
        *,
        brightness: float = 0.0,
        contrast: float = 1.0,
        saturation: float = 1.0,
        matrix: Optional[Sequence[float]] = None,
    ):
        self.preset = expect_choice(
            str(preset).lower(), tuple(_GRADE_PRESETS.keys()), what="Grade preset",
        ) if matrix is None else str(preset).lower()
        self.brightness = float(brightness)
        self.contrast = float(contrast)
        self.saturation = float(saturation)
        if matrix is not None:
            from .validate import number
            if isinstance(matrix, (str, bytes)) or not hasattr(matrix, "__iter__"):
                raise TypeError(
                    f"Grade matrix= expected 20 numbers (a 4x5 colour matrix), got "
                    f"{type(matrix).__name__}"
                )
            matrix = [number(v, "Grade matrix") for v in matrix]
            if len(matrix) != 20:
                raise ValueError(f"Grade matrix= needs 20 numbers, got {len(matrix)}")
        self.matrix = list(matrix) if matrix is not None else None

    def _fx_cache_key(self) -> tuple:
        return (
            "grade", self.preset,
            round(self.brightness, 3), round(self.contrast, 3),
            round(self.saturation, 3),
            tuple(self.matrix) if self.matrix else None,
        )

    def _build_color_filter(self):
        if self.matrix is not None:
            base = list(self.matrix)
        else:
            base = list(_GRADE_PRESETS[self.preset])
        # Apply simple brightness / contrast / saturation on top of the preset.
        c = self.contrast
        b = self.brightness
        if abs(c - 1.0) > 1e-6 or abs(b) > 1e-6:
            # contrast around 0.5 mid-grey, then brightness offset
            o = 0.5 * (1.0 - c) + b
            for i in (0, 6, 12):
                base[i] *= c
            for i in (4, 9, 14):
                base[i] += o
        if abs(self.saturation - 1.0) > 1e-6:
            s = self.saturation
            # Lerp toward luminance matrix
            lum = [0.299, 0.587, 0.114]
            for row in range(3):
                for col in range(3):
                    idx = row * 5 + col
                    base[idx] = lum[col] * (1 - s) + base[idx] * s
        return skia.ColorFilters.Matrix(base)


# ---------------------------------------------------------------------------
# FILTER (replace-style)
# ---------------------------------------------------------------------------

class Pixelate(PostEffect):
    """Mosaic / pixelate the whole frame.

    Args:
        cell: Block size (default 5).
    """

    _stage = PostEffectStage.FILTER
    _quality_sensitive = True

    def __init__(self, cell: float = 5.0):
        self.cell = float(cell)

    def _fx_cache_key(self) -> tuple:
        return ("pixelate", round(self.cell, 2))

    def _build_filter(self, inp, scale: float = 1.0):
        cell = max(self.cell * max(scale, 0.25), 1.0)
        down = skia.Matrix.Scale(1.0 / cell, 1.0 / cell)
        up = skia.Matrix.Scale(cell, cell)
        nearest = skia.SamplingOptions(skia.FilterMode.kNearest)
        small = skia.ImageFilters.MatrixTransform(down, nearest, inp)
        return skia.ImageFilters.MatrixTransform(up, nearest, small)


class ScreenBlur(PostEffect):
    """Whole-scene Gaussian blur (renamed to avoid clashing with shape ``Blur``).

    Args:
        sigma: Blur (default 2.5).
    """

    _stage = PostEffectStage.FILTER
    _quality_sensitive = True

    def __init__(self, sigma: float = 2.5):
        self.sigma = float(sigma)

    def _fx_cache_key(self) -> tuple:
        return ("screen_blur", round(self.sigma, 2))

    def _build_filter(self, inp, scale: float = 1.0):
        s = self.sigma * max(scale, 0.25)
        if s < 0.05:
            return inp
        return skia.ImageFilters.Blur(s, s, skia.TileMode.kClamp, inp)


# ---------------------------------------------------------------------------
# Wash (steady bleach / tint) · Motion trails
# ---------------------------------------------------------------------------

class Wash(PostEffect):
    """Steady full-frame bleach (ColorFilter). Hit whiteouts use ``canvas.flash``.

    Zero-arg is a mild white wash. ``intensity=0`` is a no-op. ``color`` tints
    the overlay (damage red, heat gold, …).
    """

    _stage = PostEffectStage.COLOR
    _quality_sensitive = False

    def __init__(
        self,
        intensity: float = 0.25,
        color: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    ):
        self.intensity = float(intensity)
        self.color = resolve_rgb(color, default=(1.0, 1.0, 1.0))

    def _fx_cache_key(self) -> tuple:
        return ("wash", round(self.intensity, 3), self.color)

    def _is_active(self) -> bool:
        return bool(self.enabled) and self.intensity > 0.01

    def _build_color_filter(self):
        f = min(1.0, max(0.0, self.intensity))
        if f < 0.01:
            return None
        r, g, b = self.color
        s = 1.0 - f
        return skia.ColorFilters.Matrix([
            s, 0, 0, 0, r * f,
            0, s, 0, 0, g * f,
            0, 0, s, 0, b * f,
            0, 0, 0, 1, 0,
        ])


# Residual-free afterimage compose for MotionTrail.
# Plus of a full-scene EMA plate permanently washes the BG. Keep the live pixel
# 100% and only add history that is *brighter*. A deadzone kills 8-bit EMA
# quant stick; a luma check avoids fringe on dark BG under bright movers.
_MOTION_TRAIL_SKSL = """
uniform shader current;
uniform shader trail;
uniform float u_opacity;

half luma(half3 c) {
    return dot(c, half3(0.299, 0.587, 0.114));
}

half4 main(float2 coord) {
    half4 c = current.eval(coord);
    half4 t = trail.eval(coord);
    half3 add = max(t.rgb - c.rgb, half3(0.0));
    half peak = max(max(add.r, add.g), add.b);
    half gate = smoothstep(half(0.04), half(0.12), peak);
    // Only leave ghosts when history is brighter overall (no dark-BG fringe).
    half br = smoothstep(half(0.0), half(0.04), luma(t.rgb) - luma(c.rgb));
    half3 rgb = min(
        c.rgb + half(u_opacity) * gate * br * add,
        half3(1.0)
    );
    return half4(rgb, 1.0);
}
"""


def _compile_motion_trail_builder() -> skia.RuntimeShaderBuilder:
    eff = skia.RuntimeEffect.MakeForShader(_MOTION_TRAIL_SKSL)
    err = None
    if isinstance(eff, tuple):
        eff, err = eff
    if eff is None:
        raise RuntimeError(f"MotionTrail SkSL failed: {err}")
    return skia.RuntimeShaderBuilder(eff)


_MOTION_TRAIL_BUILDER = None  # lazy


def release_motion_trail_children() -> None:
    """Drop MotionTrail RuntimeEffect children so snapshots can be freed."""
    b = _MOTION_TRAIL_BUILDER
    if b is None:
        return
    try:
        b.setChild("current", None)
        b.setChild("trail", None)
    except Exception:
        pass


class MotionTrail(PostEffect):
    """Ghosting / motion trails via time-based feedback of successive frames.

    ``fade`` is the fraction of history kept after **1/60 s**, so trails look
    the same at 30 fps, 60 fps, or uncapped (``canvas.framerate = "max"``).

    Live silhouettes stay crisp; the feedback buffer holds **previous** frames
    and only brighter residual history is composited (static scene → identity,
    no permanent background wash).

    At ``FxQuality.LOW`` / survival tier this is a no-op (identity passthrough).
    Medium / high / max keep full trails.

    Muting (``enabled = False``), stack mute (``canvas.effects.enabled``),
    ``remove`` / ``clear``, or survival quality **drops ping-pong history** so
    the next active frame seeds from the live plate (no ghost of the previous
    trail).

    For whole-frame speed-lines / radial smear, use :class:`ZoomBlur` instead.
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(self, fade: float = 0.90, opacity: float = 1.0):
        """
        Args:
            fade: History kept after 1/60s (0.85–0.95 = long trails).
            opacity: Residual afterimage strength on top of the sharp scene.
        """
        self.fade = float(fade)
        self.opacity = float(opacity)
        self._enabled = True
        self._a = None
        self._b = None
        self._size = None
        self._primed = False
        self._flip = 0
        self._prev = None

    @property
    def enabled(self) -> bool:
        """Turn the trail on / off (``True`` / ``False``) without removing the effect; off clears the trail."""
        return bool(self._enabled)

    @enabled.setter
    def enabled(self, value) -> None:
        value = _expect_flag(value, 'enabled')
        if value == self._enabled:
            return
        self._enabled = value
        if not value:
            self._reset_history()

    def _reset_history(self) -> None:
        """Drop both ping-pong RTs so the next active frame seeds cleanly."""
        self._a = None
        self._b = None
        self._prev = None
        self._primed = False
        self._flip = 0
        self._size = None
        release_motion_trail_children()

    def _discard_feedback(self) -> None:
        self._reset_history()

    def _release_resources(self) -> None:
        """Drop ping-pong RTs and history when removed from the stack."""
        self._reset_history()

    def _fx_cache_key(self) -> tuple:
        return ("trail", round(self.fade, 3), round(self.opacity, 3))

    def _make_surface(self, fw, w: int, h: int):
        info = skia.ImageInfo.Make(
            w, h,
            skia.kRGBA_8888_ColorType,
            skia.kPremul_AlphaType,
            skia.ColorSpace.MakeSRGB(),
        )
        ctx = getattr(fw, "_context", None) if fw is not None else None
        surf = (
            skia.Surface.MakeRenderTarget(ctx, skia.Budgeted.kYes, info)
            if ctx is not None else None
        )
        if surf is None:
            surf = skia.Surface(w, h)
        surf.getCanvas().clear(skia.ColorBLACK)
        return surf

    def _ensure(self, fw, w: int, h: int) -> None:
        key = (w, h)
        if self._a is not None and self._b is not None and self._size == key:
            return
        self._a = self._make_surface(fw, w, h)
        self._b = self._make_surface(fw, w, h)
        self._size = key
        self._primed = False
        self._flip = 0
        self._prev = None

    def _draw_composite(self, canvas, image, trail, linear) -> None:
        global _MOTION_TRAIL_BUILDER
        op = float(self.opacity)
        if op < 0.01:
            canvas.drawImage(image, 0, 0)
            return
        try:
            if _MOTION_TRAIL_BUILDER is None:
                _MOTION_TRAIL_BUILDER = _compile_motion_trail_builder()
            b = _MOTION_TRAIL_BUILDER
            b.setChild(
                "current",
                image.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp),
            )
            b.setChild(
                "trail",
                trail.makeShader(skia.TileMode.kClamp, skia.TileMode.kClamp),
            )
            b.setUniform("u_opacity", op)
            paint = skia.Paint(Shader=b.makeShader(), AntiAlias=False)
            canvas.drawRect(
                skia.Rect.MakeWH(float(image.width()), float(image.height())),
                paint,
            )
            return
        except Exception:
            pass
        # Fallback: Lighten residual (no Plus of the full-scene plate).
        canvas.drawImage(image, 0, 0)
        canvas.drawImage(
            trail, 0, 0, linear,
            skia.Paint(
                Alphaf=op,
                BlendMode=skia.BlendMode.kLighten,
                AntiAlias=False,
            ),
        )

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        if fidelity_is_survival():
            # Survival: skip trail work; drop both RTs so quality-up is clean.
            self._reset_history()
            canvas.drawImage(image, 0, 0)
            return

        wi, hi = max(1, int(w)), max(1, int(h))
        self._ensure(fw, wi, hi)

        dt = float(getattr(getattr(fw, "clock", None), "dt", 1.0 / 60.0) or (1.0 / 60.0))
        dt = max(1e-4, min(dt, 0.1))
        fade_60 = max(0.05, min(0.98, self.fade))
        frame_fade = float(fade_60 ** (dt * 60.0))
        frame_fade = max(0.0, min(0.99, frame_fade))

        linear = skia.SamplingOptions(skia.FilterMode.kLinear)
        src = self._a if self._flip == 0 else self._b
        dst = self._b if self._flip == 0 else self._a
        dc = dst.getCanvas()

        if not self._primed or self._prev is None:
            # Seed with the live plate so residual starts at zero (no flash).
            dc.drawImage(
                image, 0, 0, linear,
                skia.Paint(BlendMode=skia.BlendMode.kSrc),
            )
            self._primed = True
        else:
            # EMA of previous frames only — current silhouette stays crisp.
            prev_trail = src.makeImageSnapshot()
            dc.drawImage(
                prev_trail, 0, 0, linear,
                skia.Paint(BlendMode=skia.BlendMode.kSrc),
            )
            dc.drawImage(
                self._prev, 0, 0, linear,
                skia.Paint(Alphaf=1.0 - frame_fade, AntiAlias=False),
            )

        trail = dst.makeImageSnapshot()
        self._flip = 1 - self._flip
        self._prev = image
        self._draw_composite(canvas, image, trail, linear)


_EXPLOSION_DURATION = 0.85
_MAX_BURSTS = 48
_BUBBLE_DURATION = 1.35
_MAX_BUBBLE_PLUMES = 12
_MAX_BUBBLES_PER_PLUME = 28
_MAX_FIREWORKS = 24
_FW_GOLD = (1.0, 0.82, 0.28)
_MAX_ZAPS = 24
_ZAP_CYAN = (0.45, 0.85, 1.0)
_ZAP_STYLES = ("spark", "fork", "corona")
# ``hit_at``: many can be live at once (a boss under a stream of shots).
_MAX_HITS = 64
_HIT_WARM = (1.0, 0.86, 0.55)
# ``hit_at(style=)``: the star mark (default) or a round pop of light.
_HIT_STYLES = ("star", "disc")
_HIT_SPARKS = 8  # star spark streaks when ``count`` is omitted
# Half-width of the spark cone around ``angle`` (radians).
_HIT_CONE = math.radians(50.0)
# ``debris_at``: matte shards + dust (SrcOver, not emissive).
_MAX_DEBRIS = 16
_DEBRIS_STONE = (0.56, 0.54, 0.51)
_DEBRIS_DUST = (0.62, 0.60, 0.56)
_DEBRIS_DRAG = 2.0
# Interned MaskFilter blurs for high-quality zap bolt soft bands (sparse one-shots).
_ZAP_STROKE_BLUR: dict = {}
# Soft-disc stamp paint (GlowSpot path) — reused; ColorFilter swapped per call.
_ZAP_SOFT_PAINT = None
_ZAP_SOFT_DISC = None
_ZAP_SOFT_N = 64
_ZAP_SOFT_SAMPLING = None
# SkSL warp dies at dist = span / falloff (must match ``_RIPPLE_SKSL``).
_RIPPLE_FALLOFF = 1.35
# Explosion shock (warp + accent ring) vs full-screen ``ripple_at`` radius.
_EXPLOSION_SHOCK_SPAN = 0.4


def _zap_soft_disc_image():
    """White soft radial disc (premul) — same recipe as SpatialFx GlowSpot stamps."""
    global _ZAP_SOFT_DISC, _ZAP_SOFT_SAMPLING
    if _ZAP_SOFT_DISC is not None:
        return _ZAP_SOFT_DISC
    n = _ZAP_SOFT_N
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
    _ZAP_SOFT_DISC = surf.makeImageSnapshot()
    _ZAP_SOFT_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)
    return _ZAP_SOFT_DISC


def _zap_soft_paint():
    global _ZAP_SOFT_PAINT
    if _ZAP_SOFT_PAINT is None:
        _ZAP_SOFT_PAINT = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kFill_Style,
            BlendMode=skia.BlendMode.kPlus,
        )
    return _ZAP_SOFT_PAINT


def _zap_tint_filter(r: float, g: float, b: float, a: float):
    return skia.ColorFilters.Matrix((
        r, 0, 0, 0, 0,
        0, g, 0, 0, 0,
        0, 0, b, 0, 0,
        0, 0, 0, a, 0,
    ))


def _zap_stroke_blur(sigma: float):
    """Interned ``MaskFilter`` blur for high-quality bolt soft bands."""
    sig = max(0.8, float(sigma))
    key = round(sig, 1)
    mf = _ZAP_STROKE_BLUR.get(key)
    if mf is None:
        mf = skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, sig)
        _ZAP_STROKE_BLUR[key] = mf
        if len(_ZAP_STROKE_BLUR) > 24:
            # Bound cache; drop an arbitrary old entry
            _ZAP_STROKE_BLUR.pop(next(iter(_ZAP_STROKE_BLUR)))
    return mf




def _frac_hash(a: float, b: float) -> float:
    x = math.sin(a * 127.1 + b * 311.7) * 43758.5453
    return x - math.floor(x)


def _draw_bubble(
    canvas,
    x: float,
    y: float,
    r: float,
    color: Tuple[float, float, float],
    alpha: float,
) -> None:
    """Single foam bubble — body + ring + specular (``canvas.bubbles_at``)."""
    if alpha < 0.02 or r < 0.4:
        return
    a = max(0.0, min(1.0, alpha))
    cr, cg, cb = color
    body = skia.Paint(
        AntiAlias=True, Style=skia.Paint.kFill_Style,
        Color4f=skia.Color4f(
            min(1.0, cr * 0.55 + 0.45),
            min(1.0, cg * 0.55 + 0.45),
            min(1.0, cb * 0.55 + 0.45),
            0.35 * a,
        ),
    )
    canvas.drawCircle(x, y, r, body)
    ring = skia.Paint(
        AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=max(0.7, r * 0.12),
        Color4f=skia.Color4f(cr, cg, cb, 0.55 * a),
    )
    canvas.drawCircle(x, y, r, ring)
    # Speckle highlight
    canvas.drawCircle(
        x - r * 0.25, y + r * 0.2, max(0.4, r * 0.2),
        skia.Paint(
            AntiAlias=True, Style=skia.Paint.kFill_Style,
            Color4f=skia.Color4f(1.0, 1.0, 1.0, 0.4 * a),
        ),
    )


def _draw_bubble_plume(canvas, plume: dict, w: float, h: float, sox: float, soy: float) -> None:
    """Rising bubbles: fade out near max height; light pop on dying ones."""
    p = plume["t"] / _BUBBLE_DURATION
    if p >= 1.0:
        return
    sx = float(w)
    sy = float(h)
    W, H = plume.get("design_size") or _design_size_safe()
    dx = sx / max(float(W), 1.0)
    dy = sy / max(float(H), 1.0)
    ox = plume["uv"][0] * w + sox
    oy = plume["uv"][1] * h + soy
    color = plume["color"]
    rise_fb = plume["height_design"] * dy
    s = max(0.35, float(plume["strength"]))

    for i, b in enumerate(plume["parts"]):
        # Stagger start so the plume streams, not blasts
        local_t = max(0.0, plume["t"] - b["delay"])
        life = b["life"]
        if local_t <= 0.0 or local_t >= life:
            continue
        u = local_t / life
        # Rise (FB y-down → decrease y)
        y = oy - u * rise_fb * b["vy"] * s
        x = ox + b["ox"] * dx + math.sin(u * 6.0 + b["phase"]) * b["wobble"] * dx
        pr = b["r0"] * dx * (1.0 + 0.25 * u) * s
        # Fade in then soft fade; burst pop in last 12%
        if u < 0.12:
            a = u / 0.12
        elif u > 0.88:
            a = max(0.0, (1.0 - u) / 0.12)
            # Expand + burst rings near death
            if u > 0.92:
                pop = (u - 0.92) / 0.08
                pr *= 1.0 + 0.55 * pop
                a *= max(0.0, 1.0 - pop)
                if pop < 0.65:
                    canvas.drawCircle(
                        x, y, pr * (1.1 + 0.8 * pop),
                        skia.Paint(
                            Style=skia.Paint.kStroke_Style,
                            StrokeWidth=1.0,
                            Color4f=skia.Color4f(*color, 0.35 * (1.0 - pop)),
                            AntiAlias=True,
                        ),
                    )
        else:
            a = 1.0
        a *= 0.55 + 0.45 * _frac_hash(i + 1.1, plume["seed"])
        _draw_bubble(canvas, x, y, pr, color, a)


def _spawn_bubble_parts(count: int, seed: float) -> list:
    parts = []
    n = max(4, min(int(count), _MAX_BUBBLES_PER_PLUME))
    for i in range(n):
        h0 = _frac_hash(i + 1.0, seed)
        h1 = _frac_hash(i + 2.3, seed + 1.1)
        h2 = _frac_hash(i + 4.7, seed + 2.2)
        h3 = _frac_hash(i + 7.1, seed + 3.3)
        parts.append({
            "ox": (h0 - 0.5) * 36.0,
            "r0": 2.0 + 5.5 * h1,
            "vy": 0.75 + 0.55 * h2,
            "wobble": 4.0 + 10.0 * h3,
            "phase": h0 * 6.28,
            "delay": h1 * 0.35,
            "life": 0.55 + 0.55 * h2,
        })
    return parts


def _fw_glitter(rgb: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Near-white tips derived from star pigment (``color2=None``)."""
    return (
        min(1.0, rgb[0] * 0.22 + 0.78),
        min(1.0, rgb[1] * 0.22 + 0.78),
        min(1.0, rgb[2] * 0.22 + 0.78),
    )


def _spawn_firework_stars(count: int, seed: float) -> list:
    parts = []
    n = max(6, int(count))
    for i in range(n):
        h0 = _frac_hash(i + 1.0, seed)
        h1 = _frac_hash(i + 2.7, seed + 1.3)
        h2 = _frac_hash(i + 4.1, seed + 2.6)
        h3 = _frac_hash(i + 6.9, seed + 3.9)
        ang = (i + 0.5) / n * math.tau + (h0 - 0.5) * 0.55
        parts.append({
            "ang": ang,
            "speed": 1.55 + 1.35 * h1,
            "r0": 1.4 + 2.6 * h2,
            "g": 0.82 + 0.36 * h3,
            "delay": h0 * 0.08,
            "life": 0.62 + 0.38 * h1,
            "phase": h2 * math.tau,
            "mix": 0.15 + 0.7 * h3,
        })
    return parts


def _fw_offset(star: dict, t: float, radius: float, fall: float) -> Tuple[float, float]:
    """Design-space offset from burst center (y-up) after ``t`` seconds."""
    sp = star["speed"] * radius
    vx = math.cos(star["ang"]) * sp
    vy = math.sin(star["ang"]) * sp
    g = fall * star["g"] * radius * 4.2
    return vx * t, vy * t - 0.5 * g * t * t


def _zap_style(style) -> str:
    return expect_choice(style, _ZAP_STYLES, what="Zap style")


def _hit_spec(style, angle, count, *, what: str = "hit_at") -> str:
    """Canonical ``hit_at`` style. A disc has no sparks and no direction, so
    ``angle=`` / ``count=`` with ``style="disc"`` raise instead of being ignored."""
    st = expect_choice(style, _HIT_STYLES, what=f"{what} style")
    if st == "disc":
        if count is not None:
            raise ValueError(
                f'{what} count= has no effect with style="disc" (a disc has no '
                f'sparks). Drop count=, or use style="star".'
            )
        if angle is not None:
            raise ValueError(
                f'{what} angle= has no effect with style="disc" (a disc has no '
                f'direction). Drop angle=, or use style="star".'
            )
    return st


def _zap_hot(rgb: Tuple[float, float, float], hot: float = 0.55) -> Tuple[float, float, float]:
    h = max(0.0, min(1.0, hot))
    return (
        min(1.0, rgb[0] + (1.0 - rgb[0]) * h),
        min(1.0, rgb[1] + (1.0 - rgb[1]) * h),
        min(1.0, rgb[2] + (1.0 - rgb[2]) * h),
    )


def _spawn_zap_rays(count: int, seed: float, *, style: str) -> list:
    """Deterministic ray / fork / corona samples for one zap flash."""
    parts = []
    n = max(4, int(count))
    for i in range(n):
        h0 = _frac_hash(i + 1.0, seed)
        h1 = _frac_hash(i + 2.9, seed + 1.4)
        h2 = _frac_hash(i + 5.3, seed + 2.8)
        h3 = _frac_hash(i + 8.1, seed + 4.1)
        ang = (i + 0.5) / n * math.tau + (h0 - 0.5) * (0.85 if style == "spark" else 0.35)
        if style == "spark":
            reach = 0.28 + 0.55 * h1
            life = 0.18 + 0.28 * h2
            delay = h0 * 0.06
            branches = 0
        elif style == "fork":
            reach = 0.72 + 0.28 * h1
            life = 0.28 + 0.42 * h2
            delay = h3 * 0.05
            branches = 1 if h2 > 0.35 else (2 if h2 > 0.72 else 0)
        else:  # corona
            reach = 0.88 + 0.14 * h1
            life = 0.32 + 0.38 * h2
            delay = h1 * 0.04
            branches = 0
        parts.append({
            "ang": ang,
            "reach": reach,
            "life": life,
            "delay": delay,
            "phase": h2 * math.tau,
            "jitter": 0.55 + 0.9 * h3,
            "width": 0.65 + 0.7 * h0,
            "branches": branches,
            "b_ang": (h1 - 0.5) * 1.1,
            "b_reach": 0.35 + 0.4 * h3,
        })
    return parts


def _zap_bolt_path(
    ox: float, oy: float, ang: float, reach_fb: float, *,
    segs: int, jitter: float, seed: float, t: float,
) -> skia.Path:
    """Jagged polyline from center outward (FB y-down)."""
    path = skia.Path()
    path.moveTo(ox, oy)
    n = max(2, int(segs))
    px = math.cos(ang)
    py = math.sin(ang)  # FB: +y is down; design ang used as-is for radial spray
    qx, qy = -py, px
    for s in range(1, n + 1):
        u = s / n
        # Lateral zigzag + high-freq flicker (tesla / ElectricBolt feel)
        wob = math.sin(u * 9.0 + seed * 3.1 + t * 28.0) * jitter
        wob += math.sin(u * 17.0 + seed * 5.7 - t * 19.0) * jitter * 0.45
        # Soft taper: less lateral near tip
        wob *= (1.0 - 0.35 * u)
        x = ox + px * reach_fb * u + qx * wob
        y = oy + py * reach_fb * u + qy * wob
        path.lineTo(x, y)
    return path


def _draw_zap_glow(
    canvas, ox: float, oy: float, radius_fb: float,
    rgb: Tuple[float, float, float], alpha: float, *, layers: int = 4,
) -> None:
    """Additive soft bloom at the strike point.

    **High / medium:** prebaked soft-disc stamps (GlowSpot recipe) — smooth
    halo, two draws. **Low (survival):** concentric solid ADD circles (cheap).
    """
    if alpha < 0.02 or radius_fb < 0.5:
        return
    hot = _zap_hot(rgb, 0.65)
    if fidelity_is_survival():
        # Survival: stepped discs (no soft stamp / no gradient build).
        n = max(2, min(4, int(layers)))
        for i in range(n):
            u = (i + 1) / n
            r = radius_fb * (0.28 + 1.05 * u)
            a = alpha * (0.5 / (i + 1.2))
            canvas.drawCircle(
                ox, oy, r,
                skia.Paint(
                    Color4f=skia.Color4f(hot[0], hot[1], hot[2], a),
                    AntiAlias=True,
                    BlendMode=skia.BlendMode.kPlus,
                ),
            )
        return

    # Soft-disc halo (outer atmosphere) + hotter inner wash.
    # Medium uses a slightly tighter plate; high keeps more airy bloom.
    lite = fidelity_is_lite()
    outer_r = radius_fb * (1.15 if lite else 1.35)
    inner_r = radius_fb * (0.42 if lite else 0.48)
    img = _zap_soft_disc_image()
    paint = _zap_soft_paint()
    samp = _ZAP_SOFT_SAMPLING
    # Outer tinted bloom
    paint.setColorFilter(_zap_tint_filter(rgb[0], rgb[1], rgb[2], 0.55 * alpha))
    canvas.drawImageRect(
        img,
        skia.Rect.MakeXYWH(ox - outer_r, oy - outer_r, outer_r * 2.0, outer_r * 2.0),
        samp, paint,
    )
    # Inner hot core wash (Halo split: soft band ≠ sharp kernel)
    paint.setColorFilter(_zap_tint_filter(hot[0], hot[1], hot[2], 0.7 * alpha))
    canvas.drawImageRect(
        img,
        skia.Rect.MakeXYWH(ox - inner_r, oy - inner_r, inner_r * 2.0, inner_r * 2.0),
        samp, paint,
    )


def _stroke_zap_path(
    canvas, path: skia.Path, rgb: Tuple[float, float, float],
    alpha: float, width: float, *, core: bool = True,
) -> None:
    """Electric bolt stroke with quality ladder (Halo / CheapGlow lessons).

    - **High:** soft MaskFilter bloom band + sharp hot core (blur ≠ core pixels)
    - **Medium:** filterless fat ADD + sharp core (CheapGlow dual stroke)
    - **Low:** single ADD stroke (+ thin core when ``core``)
    """
    if alpha < 0.03 or width < 0.15:
        return
    hot = _zap_hot(rgb, 0.85)
    if fidelity_is_survival():
        canvas.drawPath(
            path,
            skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style,
                StrokeWidth=max(0.5, width * 1.6),
                Color4f=skia.Color4f(rgb[0], rgb[1], rgb[2], 0.7 * alpha),
                BlendMode=skia.BlendMode.kPlus,
                StrokeCap=skia.Paint.kRound_Cap,
                StrokeJoin=skia.Paint.kRound_Join,
            ),
        )
        if core:
            canvas.drawPath(
                path,
                skia.Paint(
                    AntiAlias=True, Style=skia.Paint.kStroke_Style,
                    StrokeWidth=max(0.3, width * 0.55),
                    Color4f=skia.Color4f(hot[0], hot[1], hot[2], min(1.0, 0.9 * alpha)),
                    BlendMode=skia.BlendMode.kPlus,
                    StrokeCap=skia.Paint.kRound_Cap,
                    StrokeJoin=skia.Paint.kRound_Join,
                ),
            )
        return

    if fidelity_is_lite():
        # Medium: CheapGlow-style dual unfiltered ADD, then sharp core.
        outer_w = max(1.2, width * 3.2)
        mid_w = max(0.7, width * 1.7)
        canvas.drawPath(
            path,
            skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style,
                StrokeWidth=outer_w,
                Color4f=skia.Color4f(rgb[0], rgb[1], rgb[2], 0.28 * alpha),
                BlendMode=skia.BlendMode.kPlus,
                StrokeCap=skia.Paint.kRound_Cap,
                StrokeJoin=skia.Paint.kRound_Join,
            ),
        )
        canvas.drawPath(
            path,
            skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style,
                StrokeWidth=mid_w,
                Color4f=skia.Color4f(rgb[0], rgb[1], rgb[2], 0.5 * alpha),
                BlendMode=skia.BlendMode.kPlus,
                StrokeCap=skia.Paint.kRound_Cap,
                StrokeJoin=skia.Paint.kRound_Join,
            ),
        )
    else:
        # High: soft bloom band (MaskFilter) + mid ADD — core stays unfiltered.
        bloom_w = max(1.6, width * 3.6)
        bloom = skia.Paint(
            AntiAlias=True, Style=skia.Paint.kStroke_Style,
            StrokeWidth=bloom_w,
            Color4f=skia.Color4f(rgb[0], rgb[1], rgb[2], 0.42 * alpha),
            BlendMode=skia.BlendMode.kPlus,
            StrokeCap=skia.Paint.kRound_Cap,
            StrokeJoin=skia.Paint.kRound_Join,
        )
        bloom.setMaskFilter(_zap_stroke_blur(max(1.2, width * 1.1)))
        canvas.drawPath(path, bloom)
        canvas.drawPath(
            path,
            skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style,
                StrokeWidth=max(0.8, width * 1.8),
                Color4f=skia.Color4f(rgb[0], rgb[1], rgb[2], 0.45 * alpha),
                BlendMode=skia.BlendMode.kPlus,
                StrokeCap=skia.Paint.kRound_Cap,
                StrokeJoin=skia.Paint.kRound_Join,
            ),
        )

    if core:
        canvas.drawPath(
            path,
            skia.Paint(
                AntiAlias=True, Style=skia.Paint.kStroke_Style,
                StrokeWidth=max(0.35, width * 0.75),
                Color4f=skia.Color4f(hot[0], hot[1], hot[2], min(1.0, 0.95 * alpha)),
                BlendMode=skia.BlendMode.kPlus,
                StrokeCap=skia.Paint.kRound_Cap,
                StrokeJoin=skia.Paint.kRound_Join,
            ),
        )


def _draw_zap_spark(canvas, zap: dict, ox: float, oy: float, dx: float, t: float) -> None:
    """v1 — impact spark: strong bloom + many short crackling rays."""
    p = zap["t"] / max(zap["duration"], 1e-3)
    if p >= 1.0:
        return
    rgb = zap["color"]
    radius = float(zap["radius_design"]) * dx
    s = max(0.25, float(zap["amount"]))
    # Envelope: hard hit then quick die
    if p < 0.12:
        env = (p / 0.12) ** 0.5
    else:
        env = max(0.0, (1.0 - (p - 0.12) / 0.88) ** 1.6)
    env *= s
    _draw_zap_glow(canvas, ox, oy, radius * (0.55 + 0.35 * (1.0 - p)), rgb, 0.9 * env, layers=5)
    # White-hot kernel
    canvas.drawCircle(
        ox, oy, max(2.0, radius * 0.08 * (1.1 - 0.4 * p)) * s,
        skia.Paint(
            Color4f=skia.Color4f(1.0, 1.0, 1.0, 0.95 * env),
            AntiAlias=True,
            BlendMode=skia.BlendMode.kPlus,
        ),
    )
    survival = fidelity_is_survival()
    for i, ray in enumerate(zap["parts"]):
        local = t - ray["delay"]
        life = ray["life"]
        if local <= 0.0 or local >= life:
            continue
        u = local / life
        flicker = 0.55 + 0.45 * abs(math.sin(t * 42.0 + ray["phase"]))
        a = env * flicker * (1.0 - u * 0.85)
        reach = radius * ray["reach"] * (0.85 + 0.25 * math.sin(t * 18.0 + i))
        segs = 3 if survival else 5
        path = _zap_bolt_path(
            ox, oy, ray["ang"], reach,
            segs=segs, jitter=ray["jitter"] * radius * 0.07,
            seed=zap["seed"] + i, t=t,
        )
        _stroke_zap_path(canvas, path, rgb, a, ray["width"] * (1.1 + 0.4 * s) * dx, core=not survival)


def _draw_zap_fork(canvas, zap: dict, ox: float, oy: float, dx: float, t: float) -> None:
    """v2 — tesla forks: longer branched bolts + bright core (Bolt tesla family)."""
    p = zap["t"] / max(zap["duration"], 1e-3)
    if p >= 1.0:
        return
    rgb = zap["color"]
    radius = float(zap["radius_design"]) * dx
    s = max(0.25, float(zap["amount"]))
    if p < 0.08:
        env = p / 0.08
    elif p > 0.55:
        env = max(0.0, (1.0 - p) / 0.45)
    else:
        env = 1.0
    env *= s
    _draw_zap_glow(canvas, ox, oy, radius * 0.42, rgb, 0.75 * env, layers=4)
    canvas.drawCircle(
        ox, oy, max(1.8, radius * 0.06) * s,
        skia.Paint(
            Color4f=skia.Color4f(1.0, 1.0, 1.0, 0.9 * env),
            AntiAlias=True,
            BlendMode=skia.BlendMode.kPlus,
        ),
    )
    survival = fidelity_is_survival()
    for i, ray in enumerate(zap["parts"]):
        local = t - ray["delay"]
        life = ray["life"] * max(zap["duration"], 0.2)
        if local <= 0.0 or local >= life:
            continue
        u = local / life
        flicker = 0.65 + 0.35 * abs(math.sin(t * 26.0 + ray["phase"]))
        a = env * flicker * (1.0 - 0.55 * u * u)
        reach = radius * ray["reach"]
        segs = 4 if survival else (6 + int(reach / 28.0))
        path = _zap_bolt_path(
            ox, oy, ray["ang"], reach,
            segs=segs, jitter=ray["jitter"] * radius * 0.055,
            seed=zap["seed"] + i * 1.7, t=t,
        )
        _stroke_zap_path(
            canvas, path, rgb, a,
            ray["width"] * (1.35 + 0.35 * s) * dx,
            core=not survival,
        )
        # Side forks (tesla branches)
        n_b = 0 if survival else int(ray["branches"])
        for b in range(n_b):
            bu = 0.45 + 0.2 * b
            bx = ox + math.cos(ray["ang"]) * reach * bu
            by = oy + math.sin(ray["ang"]) * reach * bu
            bang = ray["ang"] + ray["b_ang"] * (1.0 if b == 0 else -1.15)
            br = reach * ray["b_reach"] * (0.7 if b else 1.0)
            bpath = _zap_bolt_path(
                bx, by, bang, br,
                segs=3 if survival else 4,
                jitter=ray["jitter"] * radius * 0.04,
                seed=zap["seed"] + i + b * 11.0, t=t,
            )
            _stroke_zap_path(
                canvas, bpath, rgb, a * 0.75,
                ray["width"] * 0.85 * dx, core=True,
            )


def _draw_zap_corona(canvas, zap: dict, ox: float, oy: float, dx: float, t: float) -> None:
    """v3 — electric corona: expanding jagged ring + rim arcs (ElectricBolt family)."""
    p = zap["t"] / max(zap["duration"], 1e-3)
    if p >= 1.0:
        return
    rgb = zap["color"]
    hot = _zap_hot(rgb, 0.6)
    radius = float(zap["radius_design"]) * dx
    s = max(0.25, float(zap["amount"]))
    if p < 0.1:
        env = p / 0.1
    else:
        env = max(0.0, (1.0 - (p - 0.1) / 0.9) ** 1.25)
    env *= s
    # Expanding crackle ring
    ring_u = min(1.0, p / 0.55)
    ring_r = radius * (0.25 + 0.75 * ring_u)
    ring_a = env * (1.0 - 0.35 * ring_u)
    survival = fidelity_is_survival()
    n_arc = 6 if survival else max(8, len(zap["parts"]))
    # Closed jagged corona path
    path = skia.Path()
    for i in range(n_arc + 1):
        u = i / n_arc
        ang = u * math.tau + t * 3.5
        j = (_frac_hash(i + 0.5, zap["seed"] + t * 0.7) - 0.5) * radius * 0.12
        j += math.sin(ang * 5.0 + t * 22.0) * radius * 0.04
        r = ring_r + j
        x = ox + math.cos(ang) * r
        y = oy + math.sin(ang) * r
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.close()
    _stroke_zap_path(canvas, path, rgb, ring_a, (2.2 + 1.2 * s) * dx, core=not survival)
    # Soft fill wash inside the ring
    canvas.drawCircle(
        ox, oy, ring_r * 0.92,
        skia.Paint(
            Color4f=skia.Color4f(rgb[0], rgb[1], rgb[2], 0.12 * env),
            AntiAlias=True,
            BlendMode=skia.BlendMode.kPlus,
        ),
    )
    _draw_zap_glow(canvas, ox, oy, radius * 0.35, rgb, 0.7 * env, layers=4)
    canvas.drawCircle(
        ox, oy, max(2.0, radius * 0.07) * s,
        skia.Paint(
            Color4f=skia.Color4f(hot[0], hot[1], hot[2], 0.95 * env),
            AntiAlias=True,
            BlendMode=skia.BlendMode.kPlus,
        ),
    )
    # Short rim spokes (ElectricBolt crackle)
    for i, ray in enumerate(zap["parts"]):
        local = t - ray["delay"]
        life = ray["life"]
        if local <= 0.0 or local >= life:
            continue
        u = local / life
        flicker = 0.5 + 0.5 * abs(math.sin(t * 36.0 + ray["phase"]))
        a = env * flicker * (1.0 - u)
        # Spoke straddles the ring
        mid = ring_r
        half = radius * 0.18 * ray["reach"]
        ang = ray["ang"] + t * 1.2
        x0 = ox + math.cos(ang) * (mid - half)
        y0 = oy + math.sin(ang) * (mid - half)
        path = _zap_bolt_path(
            x0, y0, ang, half * 2.0,
            segs=3 if survival else 4,
            jitter=ray["jitter"] * radius * 0.035,
            seed=zap["seed"] + i, t=t,
        )
        _stroke_zap_path(canvas, path, rgb, a, ray["width"] * dx, core=True)


def _draw_zap_flash(canvas, zap: dict, w: float, h: float, sox: float, soy: float) -> None:
    """One electric zap flash (``canvas.zap_at``) — style spark | fork | corona."""
    dur = max(float(zap["duration"]), 1e-3)
    if zap["t"] / dur >= 1.0:
        return
    W, H = zap.get("design_size") or _design_size_safe()
    dx = float(w) / max(float(W), 1.0)
    ox = zap["uv"][0] * w + sox
    oy = zap["uv"][1] * h + soy
    t = float(zap["t"])
    style = zap.get("style", "spark")
    if style == "fork":
        _draw_zap_fork(canvas, zap, ox, oy, dx, t)
    elif style == "corona":
        _draw_zap_corona(canvas, zap, ox, oy, dx, t)
    else:
        _draw_zap_spark(canvas, zap, ox, oy, dx, t)


def _draw_firework_shell(canvas, shell: dict, w: float, h: float, sox: float, soy: float) -> None:
    """One chrysanthemum / willow burst (``canvas.fireworks_at``)."""
    dur = max(float(shell["duration"]), 1e-3)
    p = shell["t"] / dur
    if p >= 1.0:
        return
    sx = float(w)
    sy = float(h)
    W, H = shell.get("design_size") or _design_size_safe()
    dx = sx / max(float(W), 1.0)
    dy = sy / max(float(H), 1.0)
    ox = shell["uv"][0] * w + sox
    oy = shell["uv"][1] * h + soy
    color = shell["color"]
    color2 = shell["color2"]
    radius = float(shell["radius_design"])
    fall = float(shell["fall"])
    trail = float(shell["trail"])
    s = max(0.25, float(shell["amount"]))
    t = float(shell["t"])

    # Brief break flash at the burst point (not a fireball / not camera flash).
    if p < 0.12:
        fa = (1.0 - p / 0.12) ** 2
        fr = (6.0 + radius * 0.10 * (p / 0.12)) * dx * s
        canvas.drawCircle(
            ox, oy, max(fr, 1.5),
            skia.Paint(
                Color4f=skia.Color4f(
                    min(1.0, color2[0] * 0.35 + 0.65),
                    min(1.0, color2[1] * 0.35 + 0.65),
                    min(1.0, color2[2] * 0.35 + 0.65),
                    0.85 * fa * s,
                ),
                AntiAlias=True,
                BlendMode=skia.BlendMode.kPlus,
            ),
        )

    survival = fidelity_is_survival()
    n_trail = 0 if survival or trail < 0.04 else 2 + int(trail * 5)

    for star in shell["parts"]:
        local = t - star["delay"]
        life = star["life"] * dur
        if local <= 0.0 or local >= life:
            continue
        u = local / life
        x_des, y_des = _fw_offset(star, local, radius, fall)
        x = ox + x_des * dx
        y = oy - y_des * dy
        if u < 0.08:
            a = u / 0.08
        elif u > 0.62:
            a = max(0.0, (1.0 - u) / 0.38)
        else:
            a = 1.0
        a *= 0.55 + 0.45 * abs(math.sin(t * 22.0 + star["phase"]))
        a *= s
        if a < 0.03:
            continue
        mix = min(1.0, u * u * (0.45 + star["mix"]))
        cr = color[0] * (1.0 - mix) + color2[0] * mix
        cg = color[1] * (1.0 - mix) + color2[1] * mix
        cb = color[2] * (1.0 - mix) + color2[2] * mix
        pr = star["r0"] * dx * (0.9 + 0.25 * (1.0 - u)) * (0.75 + 0.25 * s)

        if n_trail:
            step = 0.018 + 0.012 * trail
            for k in range(1, n_trail + 1):
                bt = local - k * step
                if bt <= 0.0:
                    break
                bx, by = _fw_offset(star, bt, radius, fall)
                ta = a * (1.0 - k / (n_trail + 1.0)) * (0.35 + 0.45 * trail)
                canvas.drawCircle(
                    ox + bx * dx, oy - by * dy,
                    max(0.6, pr * (1.0 - 0.12 * k)),
                    skia.Paint(
                        Color4f=skia.Color4f(cr, cg, cb, ta * 0.55),
                        AntiAlias=True,
                        BlendMode=skia.BlendMode.kPlus,
                    ),
                )
            # Streak from previous sample to the star.
            px, py = _fw_offset(star, max(0.0, local - step), radius, fall)
            canvas.drawLine(
                ox + px * dx, oy - py * dy, x, y,
                skia.Paint(
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=max(0.8, pr * 0.55),
                    Color4f=skia.Color4f(cr, cg, cb, a * 0.45 * trail),
                    AntiAlias=True,
                    BlendMode=skia.BlendMode.kPlus,
                    StrokeCap=skia.Paint.Cap.kRound_Cap,
                ),
            )

        canvas.drawCircle(
            x, y, max(pr, 0.8),
            skia.Paint(
                Color4f=skia.Color4f(cr, cg, cb, min(1.0, a * 0.95)),
                AntiAlias=True,
                BlendMode=skia.BlendMode.kPlus,
            ),
        )
        # Speck highlight
        canvas.drawCircle(
            x, y, max(0.5, pr * 0.35),
            skia.Paint(
                Color4f=skia.Color4f(1.0, 1.0, 1.0, min(1.0, a * 0.55)),
                AntiAlias=True,
                BlendMode=skia.BlendMode.kPlus,
            ),
        )


def _spawn_hit_sparks(count: int, seed: float, *, directed: bool) -> list:
    """Spark streaks for ``hit_at``: a cone around ``angle``, or a full ring."""
    parts = []
    n = max(3, int(count))
    for i in range(n):
        h0 = _frac_hash(i + 1.0, seed)
        h1 = _frac_hash(i + 2.7, seed + 1.3)
        h2 = _frac_hash(i + 4.1, seed + 2.6)
        h3 = _frac_hash(i + 6.9, seed + 3.9)
        if directed:
            off = ((i + 0.5) / n - 0.5) * 2.0 * _HIT_CONE + (h0 - 0.5) * 0.25
        else:
            off = (i + 0.5) / n * math.tau + (h0 - 0.5) * 0.6
        parts.append({
            "off": off,
            "speed": 0.75 + 0.6 * h1,
            "len": 0.45 + 0.4 * h2,
            "life": 0.55 + 0.45 * h3,
            "width": 0.9 + 0.8 * h2,
        })
    return parts


def _hit_star_path(cx: float, cy: float, ang: float, size: float, arms) -> "skia.Path":
    """Four-point impact star (FB space). ``arms`` are the four arm lengths."""
    path = skia.Path()
    inner = size * 0.2
    for k in range(4):
        a_out = ang + k * (math.pi * 0.5)
        a_in = a_out + math.pi * 0.25
        ro = size * arms[k]
        xo, yo = cx + math.cos(a_out) * ro, cy + math.sin(a_out) * ro
        if k == 0:
            path.moveTo(xo, yo)
        else:
            path.lineTo(xo, yo)
        path.lineTo(cx + math.cos(a_in) * inner, cy + math.sin(a_in) * inner)
    path.close()
    return path


def _draw_hit_disc(canvas, ox: float, oy: float, R: float, rgb, s: float,
                   p: float, survival: bool) -> None:
    """``hit_at(style="disc")``: a round pop of light — a tinted disc that
    opens fast and fades, over a soft white-hot core. Reaches ~1.6 × the
    radius (the star's sparks reach ~2 ×). Draws at every quality: survival
    swaps the radial gradients for flat ADD discs."""
    r, g, b = rgb
    e = 1.0 - (1.0 - p) ** 2.5
    rad = R * (0.7 + 0.9 * e)
    a = min(1.0, (1.0 - p) ** 1.4 * s)
    disc = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kPlus)
    if survival:
        # Two concentric ADD discs stand in for the gradient (zap_at's LOW
        # recipe); faded faster so the flat edge never lingers as a plate.
        a *= 1.0 - p
        disc.setColor4f(skia.Color4f(r, g, b, 0.3 * a))
        canvas.drawCircle(ox, oy, rad, disc)
        disc.setColor4f(skia.Color4f(r, g, b, 0.35 * a))
        rad *= 0.6
    else:
        disc.setShader(skia.GradientShader.MakeRadial(
            skia.Point(ox, oy), rad,
            [skia.Color4f(r, g, b, a), skia.Color4f(r, g, b, 0.75 * a),
             skia.Color4f(r, g, b, 0.0)],
            [0.0, 0.5, 1.0],
            skia.TileMode.kClamp,
        ))
    canvas.drawCircle(ox, oy, rad, disc)
    # White-hot core: brightest on the first frames, then shrinks away.
    if p < 0.5:
        k = 1.0 - p / 0.5
        cr = max(1.5, R * 0.6 * k ** 0.6)
        ca = min(1.0, k * s)
        core = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kPlus)
        if survival:
            core.setColor4f(skia.Color4f(1.0, 1.0, 1.0, ca))
            cr *= 0.6
        else:
            core.setShader(skia.GradientShader.MakeRadial(
                skia.Point(ox, oy), cr,
                [skia.Color4f(1.0, 1.0, 1.0, ca), skia.Color4f(1.0, 1.0, 1.0, ca),
                 skia.Color4f(1.0, 1.0, 1.0, 0.0)],
                [0.0, 0.45, 1.0],
                skia.TileMode.kClamp,
            ))
        canvas.drawCircle(ox, oy, cr, core)


def _draw_hit(canvas, hit: dict, w: float, h: float, sox: float, soy: float) -> None:
    """One impact mark (``canvas.hit_at``): star → ring → spark spray, or a disc."""
    dur = max(float(hit["duration"]), 1e-3)
    p = hit["t"] / dur
    if p >= 1.0:
        return
    W, _H = hit.get("design_size") or _design_size_safe()
    dx = float(w) / max(float(W), 1.0)
    ox = hit["uv"][0] * w + sox
    oy = hit["uv"][1] * h + soy
    s = float(hit["amount"])
    R = max(2.0, float(hit["radius_design"]) * dx * (0.8 + 0.2 * s))
    r, g, b = hit["color"]
    a0 = float(hit["angle_fb"])
    survival = fidelity_is_survival()
    if hit["style"] == "disc":
        _draw_hit_disc(canvas, ox, oy, R, (r, g, b), s, p, survival)
        return
    fill = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kPlus)

    # 0. Soft tinted glow under the star (the punch of the first frames).
    if p < 0.35 and not survival:
        k = 1.0 - p / 0.35
        gr = R * (0.9 + 0.5 * (1.0 - k))
        glow = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kPlus)
        glow.setShader(skia.GradientShader.MakeRadial(
            skia.Point(ox, oy), gr,
            [skia.Color4f(r, g, b, min(1.0, 0.5 * k * s)), skia.Color4f(r, g, b, 0.0)],
            [0.0, 1.0],
            skia.TileMode.kClamp,
        ))
        canvas.drawCircle(ox, oy, gr, glow)

    # 1. Impact star: holds full size for the first frames, then shrinks fast.
    if p < 0.45:
        k = 1.0 if p < 0.12 else 1.0 - (p - 0.12) / 0.33
        alpha = min(1.0, (k ** 0.8) * s)
        size = R * 1.15 * (0.35 + 0.65 * k ** 0.7)
        rot = a0 + float(hit["twist"])
        fill.setColor4f(skia.Color4f(r, g, b, 0.9 * alpha))
        canvas.drawPath(_hit_star_path(ox, oy, rot, size, hit["arms"]), fill)
        if not survival:
            fill.setColor4f(skia.Color4f(1.0, 1.0, 1.0, alpha))
            canvas.drawPath(_hit_star_path(ox, oy, rot, size * 0.55, hit["arms"]), fill)
        fill.setColor4f(skia.Color4f(1.0, 1.0, 1.0, alpha))
        canvas.drawCircle(ox, oy, max(1.5, R * 0.16 * k), fill)

    stroke = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        BlendMode=skia.BlendMode.kPlus,
        StrokeCap=skia.Paint.Cap.kRound_Cap,
    )
    # 2. Thin crisp ring.
    if p < 0.65:
        u = p / 0.65
        e = 1.0 - (1.0 - u) ** 2
        stroke.setStrokeWidth(max(1.0, R * 0.14 * (1.0 - u)))
        stroke.setColor4f(skia.Color4f(r, g, b, min(1.0, 0.75 * (1.0 - u) ** 1.5 * s)))
        canvas.drawCircle(ox, oy, R * (0.25 + 0.95 * e), stroke)

    # 3. Spark streaks: white-hot, cooling to the tint.
    for part in hit["parts"]:
        u = p / part["life"]
        if u >= 1.0:
            continue
        ang = a0 + part["off"]
        e = 1.0 - (1.0 - u) ** 2.2
        d1 = R * (0.2 + 1.8 * part["speed"] * e)
        d0 = max(R * 0.1, d1 - R * part["len"] * (1.0 - 0.7 * u))
        ca, sa = math.cos(ang), math.sin(ang)
        m = min(1.0, u * 1.6)
        stroke.setStrokeWidth(max(1.2, R * 0.09 * part["width"] * (1.0 - 0.5 * u)))
        stroke.setColor4f(skia.Color4f(
            1.0 - (1.0 - r) * m, 1.0 - (1.0 - g) * m, 1.0 - (1.0 - b) * m,
            min(1.0, (1.0 - u) ** 1.2 * s),
        ))
        canvas.drawLine(ox + ca * d0, oy + sa * d0, ox + ca * d1, oy + sa * d1, stroke)


def _spawn_debris_shards(count: int, seed: float) -> list:
    """Irregular 3–5-gon shards; a few big, many small (sizes are × radius)."""
    parts = []
    n = max(4, int(count))
    for i in range(n):
        h0 = _frac_hash(i + 1.0, seed)
        h1 = _frac_hash(i + 2.7, seed + 1.3)
        h2 = _frac_hash(i + 4.1, seed + 2.6)
        h3 = _frac_hash(i + 6.9, seed + 3.9)
        h4 = _frac_hash(i + 8.3, seed + 4.4)
        h5 = _frac_hash(i + 9.7, seed + 5.2)
        size = 0.09 + 0.24 * h1 ** 2.0
        nv = 3 + int(h3 * 2.999)
        verts = []
        for k in range(nv):
            hk = _frac_hash(i * 7.3 + k + 1.0, seed + 6.1)
            hj = _frac_hash(i * 3.1 + k + 2.0, seed + 7.7)
            verts.append(((k + 0.6 * (hk - 0.5)) / nv * math.tau, 0.55 + 0.45 * hj))
        parts.append({
            "ang": (i + 0.5) / n * math.tau + (h0 - 0.5) * 0.9,
            # Big shards fly slower.
            "speed": (0.55 + 0.9 * h2) * (1.2 - 1.3 * size),
            "size": size,
            "verts": verts,
            "rot0": h4 * math.tau,
            "spin": (h5 - 0.5) * 28.0,
            "phase": h2 * math.tau,
            "tone": 0.85 + 0.25 * h0,
            "g": 0.85 + 0.3 * h5,
            "life": 0.72 + 0.28 * h4,
        })
    return parts


def _spawn_debris_puffs(seed: float) -> list:
    puffs = []
    for i in range(5):
        h0 = _frac_hash(i + 11.0, seed)
        h1 = _frac_hash(i + 12.5, seed + 0.7)
        puffs.append({
            "ang": (i + h0) / 5.0 * math.tau,
            "dist": 0.2 + 0.35 * h1,
            "r0": 0.3 + 0.2 * h0,
        })
    return puffs


def _debris_offset(part: dict, t: float, radius: float, fall: float, force: float) -> Tuple[float, float]:
    """Design-space offset (y-up) of one shard after ``t`` seconds (drag + fall)."""
    v = part["speed"] * radius * 4.2 * force
    reach = v * (1.0 - math.exp(-_DEBRIS_DRAG * t)) / _DEBRIS_DRAG
    x = math.cos(part["ang"]) * reach
    y = math.sin(part["ang"]) * reach - 0.5 * fall * part["g"] * radius * 5.0 * t * t
    return x, y


def _draw_debris(canvas, deb: dict, w: float, h: float, sox: float, soy: float) -> None:
    """One matte debris spray (``canvas.debris_at``): dust puffs, then tumbling shards."""
    dur = max(float(deb["duration"]), 1e-3)
    t = float(deb["t"])
    p = t / dur
    if p >= 1.0:
        return
    W, _H = deb.get("design_size") or _design_size_safe()
    dx = float(w) / max(float(W), 1.0)
    ox = deb["uv"][0] * w + sox
    oy = deb["uv"][1] * h + soy
    R = float(deb["radius_design"])
    s = float(deb["amount"])
    fall = float(deb["fall"])
    r, g, b = deb["color"]
    survival = fidelity_is_survival()

    if deb["dust"] and not survival:
        dr, dg, db = (
            r * 0.5 + _DEBRIS_DUST[0] * 0.5,
            g * 0.5 + _DEBRIS_DUST[1] * 0.5,
            b * 0.5 + _DEBRIS_DUST[2] * 0.5,
        )
        da = 0.30 * (1.0 - p) ** 1.6 * min(1.0, s)
        if da > 0.01:
            e = 1.0 - (1.0 - p) ** 2
            puff_paint = skia.Paint(AntiAlias=True)
            for puff in deb["puffs"]:
                d = R * puff["dist"] * e * s
                cx = ox + math.cos(puff["ang"]) * d * dx
                cy = oy - (math.sin(puff["ang"]) * d + R * 0.18 * p) * dx
                pr = max(1.0, R * (puff["r0"] + 0.55 * e) * dx)
                puff_paint.setShader(skia.GradientShader.MakeRadial(
                    skia.Point(cx, cy), pr,
                    [
                        skia.Color4f(dr, dg, db, da),
                        skia.Color4f(dr, dg, db, da * 0.5),
                        skia.Color4f(dr, dg, db, 0.0),
                    ],
                    [0.0, 0.5, 1.0],
                    skia.TileMode.kClamp,
                ))
                canvas.drawCircle(cx, cy, pr, puff_paint)

    fill = skia.Paint(AntiAlias=True)
    edge = None if survival else skia.Paint(
        AntiAlias=True, Style=skia.Paint.kStroke_Style,
        StrokeJoin=skia.Paint.Join.kRound_Join,
    )
    for part in deb["parts"]:
        life = part["life"] * dur
        if t >= life:
            continue
        u = t / life
        if u < 0.6:
            alpha, shrink = 1.0, 1.0
        else:
            q = (1.0 - u) / 0.4
            alpha, shrink = q, 0.6 + 0.4 * q
        x, y = _debris_offset(part, t, R, fall, s)
        px = ox + x * dx
        py = oy - y * dx
        size = part["size"] * R * dx * shrink
        rot = part["rot0"] + part["spin"] * t
        # Tumbling face: brightness swings with the turn (fake light).
        shade = part["tone"] * (0.78 + 0.32 * math.cos(rot + part["phase"]))
        path = skia.Path()
        for k, (va, vr) in enumerate(part["verts"]):
            vx = px + math.cos(rot + va) * vr * size
            vy = py + math.sin(rot + va) * vr * size
            if k == 0:
                path.moveTo(vx, vy)
            else:
                path.lineTo(vx, vy)
        path.close()
        fill.setColor4f(skia.Color4f(
            min(1.0, r * shade), min(1.0, g * shade), min(1.0, b * shade), alpha,
        ))
        canvas.drawPath(path, fill)
        if edge is not None:
            edge.setStrokeWidth(max(0.6, size * 0.12))
            edge.setColor4f(skia.Color4f(r * 0.45, g * 0.45, b * 0.45, alpha * 0.8))
            canvas.drawPath(path, edge)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def _pyro_tint_ramp(
    cr: float, cg: float, cb: float, core_a: float, halo_a: float, *, star: bool,
):
    """White-hot core + author mid + darker rim. Same stop geometry as the
    hardcoded palettes — used only when ``color=`` is set.
    """
    cr, cg, cb = _clamp01(cr), _clamp01(cg), _clamp01(cb)

    def mix_w(t: float) -> Tuple[float, float, float]:
        # t=0 author, t=1 white
        return (
            _clamp01(cr + (1.0 - cr) * t),
            _clamp01(cg + (1.0 - cg) * t),
            _clamp01(cb + (1.0 - cb) * t),
        )

    def dim(k: float) -> Tuple[float, float, float]:
        return (_clamp01(cr * k), _clamp01(cg * k), _clamp01(cb * k))

    if star:
        colors = [
            skia.Color4f(1.0, 1.0, 1.0, core_a),
            skia.Color4f(*mix_w(0.72), core_a * 0.95),
            skia.Color4f(*mix_w(0.12), core_a * 0.72),
            skia.Color4f(*dim(0.55), core_a * 0.28),
            skia.Color4f(*dim(0.22), 0.0),
        ]
        stops = [0.0, 0.35, 0.62, 0.88, 1.0]
        halo_cols = [
            skia.Color4f(*mix_w(0.15), halo_a),
            skia.Color4f(*dim(0.35), 0.0),
        ]
        return colors, stops, halo_cols
    colors = [
        skia.Color4f(1.0, 1.0, 1.0, core_a),
        skia.Color4f(*mix_w(0.45), core_a * 0.85),
        skia.Color4f(*dim(0.55), core_a * 0.45),
        skia.Color4f(*dim(0.20), 0.0),
    ]
    stops = [0.0, 0.28, 0.62, 1.0]
    halo_cols = [
        skia.Color4f(*mix_w(0.10), halo_a),
        skia.Color4f(*dim(0.25), 0.0),
    ]
    return colors, stops, halo_cols


def draw_pyro_core(
    canvas,
    cx: float,
    cy: float,
    core_r: float,
    *,
    strength: float = 1.0,
    alpha: float = 1.0,
    profile: str = "fireball",
    color=None,
) -> None:
    """Emissive radial core (white→yellow→orange) + outer heat halo.

    ``profile``:
      - ``"fireball"`` — explosion peak (larger red/translucent rim)
      - ``"star"`` — larger white-hot core, tighter cool rim (Sun look)

    ``color`` omitted / ``None`` keeps the hardcoded palette (pixel-identical
    to the untinted look). A 3-tuple tints: white core, author mid, darker rim.
    """
    s = max(0.25, float(strength))
    a = max(0.0, min(1.2, float(alpha))) * s
    core_r = max(float(core_r), 1.0)
    core_a = 0.95 * a
    prof = str(profile or "fireball").lower()
    star = prof in ("star", "sun", "hot")
    if color is not None:
        cr, cg, cb = float(color[0]), float(color[1]), float(color[2])
        halo_a = core_a * (0.18 if star else 0.35)
        colors, stops, halo_cols = _pyro_tint_ramp(
            cr, cg, cb, core_a, halo_a, star=star,
        )
        halo_r = core_r * (1.18 if star else 1.55)
        halo_inner = 0.5 if star else 0.35
    elif star:
        # Hold white/amber deep into the disc; thin cool rim
        colors = [
            skia.Color4f(1.0, 1.0, 1.0, core_a),
            skia.Color4f(1.0, 0.97, 0.75, core_a * 0.95),
            skia.Color4f(1.0, 0.85, 0.28, core_a * 0.72),
            skia.Color4f(1.0, 0.5, 0.12, core_a * 0.28),
            skia.Color4f(0.95, 0.2, 0.04, 0.0),
        ]
        stops = [0.0, 0.35, 0.62, 0.88, 1.0]
        halo_r = core_r * 1.18
        halo_a = core_a * 0.18
        halo_inner = 0.5
        halo_cols = [
            skia.Color4f(1.0, 0.75, 0.35, halo_a),
            skia.Color4f(1.0, 0.35, 0.08, 0.0),
        ]
    else:
        colors = [
            skia.Color4f(1.0, 1.0, 1.0, core_a),
            skia.Color4f(1.0, 0.92, 0.35, core_a * 0.85),
            skia.Color4f(1.0, 0.45, 0.08, core_a * 0.45),
            skia.Color4f(0.9, 0.15, 0.02, 0.0),
        ]
        stops = [0.0, 0.28, 0.62, 1.0]
        halo_r = core_r * 1.55
        halo_a = core_a * 0.35
        halo_inner = 0.35
        halo_cols = [
            skia.Color4f(1.0, 0.55, 0.1, halo_a),
            skia.Color4f(1.0, 0.2, 0.0, 0.0),
        ]
    shader = skia.GradientShader.MakeRadial(
        skia.Point(cx, cy), core_r,
        colors, stops,
        skia.TileMode.kClamp,
    )
    canvas.drawCircle(
        cx, cy, core_r,
        skia.Paint(Shader=shader, AntiAlias=True, BlendMode=skia.BlendMode.kPlus),
    )
    halo = skia.GradientShader.MakeRadial(
        skia.Point(cx, cy), max(halo_r, 1.0),
        halo_cols,
        [halo_inner, 1.0],
        skia.TileMode.kClamp,
    )
    canvas.drawCircle(
        cx, cy, halo_r,
        skia.Paint(Shader=halo, AntiAlias=True, BlendMode=skia.BlendMode.kPlus),
    )


def _draw_explosion_pyro(
    canvas, cx: float, cy: float, p: float, strength: float, short: float,
    *, rings: bool = False,
) -> None:
    """Flash → hot core → optional rings → cooling smoke.

    ``p`` is progress in ``[0, 1]``. ``short`` is the characteristic size in
    FB pixels (cinematic = ``min(fb_w, fb_h)``; local = mapped from design radius).

    ``rings``: expanding stroke circles (off by default).
    """
    s = max(0.35, float(strength))
    short = max(float(short), 1.0)

    # Impact flash disc (very brief).
    if p < 0.10:
        fa = (1.0 - p / 0.10) ** 2
        fr = (12.0 + p * short * 0.08) * s
        canvas.drawCircle(
            cx, cy, fr,
            skia.Paint(
                Color4f=skia.Color4f(1.0, 1.0, 1.0, 0.95 * fa),
                AntiAlias=True,
                BlendMode=skia.BlendMode.kPlus,
            ),
        )

    # Hot core — ease-out expand, white → yellow → orange → red.
    if p < 0.55:
        ease = 1.0 - (1.0 - min(1.0, p / 0.50)) ** 3
        core_r = (22.0 + ease * short * 0.20) * (0.75 + 0.25 * s)
        fade = max(0.0, 1.0 - p / 0.55)
        draw_pyro_core(canvas, cx, cy, core_r, strength=1.0, alpha=fade * fade * 0.95 * s)

    # Expanding rings (staggered, bright then fade). Opt-in.
    if rings:
        for delay, speed, width, warm in (
            (0.06, 0.50, 4.0, (1.0, 0.95, 0.75)),
            (0.16, 0.62, 2.5, (1.0, 0.75, 0.35)),
            (0.28, 0.72, 1.5, (0.95, 0.55, 0.25)),
        ):
            if p < delay:
                continue
            local = (p - delay) / max(1e-3, 0.75)
            if local >= 1.0:
                continue
            ease_r = 1.0 - (1.0 - min(1.0, local)) ** 2
            rr = 18.0 + ease_r * speed * short * 0.42 * s
            aa = max(0.0, (1.0 - local) ** 1.4) * 0.55 * s
            r, g, b = warm
            canvas.drawCircle(
                cx, cy, rr,
                skia.Paint(
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=width * (1.0 - 0.55 * local) + 1.0,
                    Color4f=skia.Color4f(r, g, b, aa),
                    AntiAlias=True,
                    BlendMode=skia.BlendMode.kPlus,
                ),
            )

    # Cooling smoke puff (opaque dark, late).
    if p > 0.35:
        sp = (p - 0.35) / 0.65
        smoke_r = (30.0 + sp * short * 0.28) * s
        smoke_a = max(0.0, (1.0 - sp) * 0.22 * s)
        # Drift slightly upward in FB (y decreases).
        sy_smoke = cy - sp * short * 0.04
        smoke = skia.GradientShader.MakeRadial(
            skia.Point(cx, sy_smoke), max(smoke_r, 1.0),
            [
                skia.Color4f(0.12, 0.10, 0.08, smoke_a),
                skia.Color4f(0.08, 0.07, 0.06, smoke_a * 0.4),
                skia.Color4f(0.05, 0.05, 0.05, 0.0),
            ],
            [0.0, 0.55, 1.0],
            skia.TileMode.kClamp,
        )
        canvas.drawCircle(
            cx, sy_smoke, smoke_r,
            skia.Paint(
                Shader=smoke,
                AntiAlias=True,
                BlendMode=skia.BlendMode.kSrcOver,
            ),
        )


def _short_for_local_radius(radius_fb: float) -> float:
    """Map peak design/FB radius to the pyro ``short`` param.

    Outer ring peaks near ``18 + 0.72 * 0.42 * short ≈ 18 + 0.30 * short``.
    """
    r = max(float(radius_fb), 8.0)
    return max((r - 18.0) / 0.30, r * 2.2, 32.0)


class HitFeedback(PostEffect):
    """Gameplay hit feedback: flash, shake, glitch, warp, explosion, bursts, bubbles, fireworks, zap, hit, debris.

    Authors normally use ``canvas.flash()`` / ``shake()`` / ``glitch()`` /
    ``ripple_at()`` / ``wave_at()`` / ``explosion_at()`` / ``burst_at()`` /
    ``bubbles_at()`` / ``fireworks_at()`` / ``zap_at()`` / ``hit_at()`` /
    ``debris_at()`` instead of constructing this directly. The stack keeps
    one singleton.

    Ripple / wave + flash run as a single compile-once SkSL pass (no CPU
    displacement maps). Shake is a FB-space translate in ``_draw_shader``.
    Glitch is a compile-once SkSL slice / RGB-split pass. Explosions /
    bursts / bubble plumes / firework shells / electric zaps / impact
    marks / debris sprays paint via
    ``draw_ring`` (pool).
    """

    _stage = PostEffectStage.SHADER
    _quality_sensitive = False

    def __init__(self):
        self._flash = 0.0
        self._shake = 0.0
        self._shake_ox = 0.0
        self._shake_oy = 0.0
        self._glitch = 0.0
        self._glitch_surf = None
        self._ripple_t = 99.0
        self._ripple_uv = (0.5, 0.5)
        self._ripple_strength = 1.0
        self._ripple_mode = 0.0  # 0 = radial, 1 = linear
        self._ripple_angle = 0.0  # FB-space radians for linear wave normal
        self._ripple_span = 1.0  # 1 = full ``ripple_at``; explosion shock is smaller
        self._ripple_radius_design = None  # view-scaled explicit radius, or None
        self._ripple_radius_world = None  # author radius; None = full-frame / shock span
        self._ripple_world = None  # world (x, y) for the active ripple / wave
        self._ripple_world_angle = 0.0  # wave angle in world degrees
        self._ripple_shock = True  # overlay ring/band; warp still runs when False
        # Active pyro instances: world + view-baked uv / radius_design
        self._bursts: list = []
        # Rising bubble plumes (canvas-wide transients)
        self._bubble_plumes: list = []
        # Firework shells (celebration bursts; not pyro, not Sparks)
        self._fireworks: list = []
        # Electric zap flashes (spark / fork / corona; not Sparks SpatialFx)
        self._zaps: list = []
        # Impact marks (star + ring + spark spray; not a death)
        self._hits: list = []
        # Matte debris sprays (shards + dust; not pyro)
        self._debris: list = []
        self._design_size = None  # (W, H) for UV conversion
        self._bubble_seed = 0.0
        self._fw_seed = 0.0
        self._zap_seed = 0.0
        self._hit_seed = 0.0
        self._debris_seed = 0.0

    def _clear_pulses(self) -> None:
        """Drop every pending one-shot (a scene change). The singleton stays."""
        self._flash = 0.0
        self._shake = 0.0
        self._shake_ox = 0.0
        self._shake_oy = 0.0
        self._glitch = 0.0
        self._ripple_t = 99.0
        self._ripple_world = None
        self._ripple_radius_design = None
        self._ripple_radius_world = None
        self._bursts.clear()
        self._bubble_plumes.clear()
        self._fireworks.clear()
        self._zaps.clear()
        self._hits.clear()
        self._debris.clear()

    def flash(self, intensity: float = 0.6) -> None:
        self._flash = min(1.0, float(intensity) + self._flash * 0.3)

    def shake(self, amount: float = 10.0) -> None:
        self._shake = max(self._shake, float(amount))

    def glitch(self, amount: float = 1.0) -> None:
        self._glitch = max(self._glitch, float(amount))

    def _set_design_uv(self, x: float, y: float) -> Tuple[float, float]:
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        W = float(fw.design_width)
        H = float(fw.design_height)
        self._design_size = (W, H)
        # World → view (camera then inspector), then FB y-down UV.
        # Identity camera + inspector: same x/W, 1-y/H as before.
        vx, vy = fw.world_to_view_coords(x, y)
        return (vx / W if W else 0.5, 1.0 - (vy / H if H else 0.5))

    def _remap_overlays(self) -> None:
        """Re-map stored world loci through the live camera + debug zoom.

        Post overlays paint in FB UV. Baking that UV at spawn left fireworks
        behind a follow-cam (platformer landing: camera drops, burst sits
        below the hero). Galaga bursts looked fine because ``frame_to``
        barely moves during a short pop.
        """
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        W = float(fw.design_width)
        H = float(fw.design_height)
        self._design_size = (W, H)
        scale = float(fw.world_to_view_scale())
        rot = float(fw.world_to_view_rotation())

        def uv_of(xy) -> Tuple[float, float]:
            vx, vy = fw.world_to_view_coords(float(xy[0]), float(xy[1]))
            return (vx / W if W else 0.5, 1.0 - (vy / H if H else 0.5))

        if self._ripple_world is not None and self._ripple_t < 0.9:
            self._ripple_uv = uv_of(self._ripple_world)
            rw = self._ripple_radius_world
            if rw is not None:
                r = max(8.0, float(rw)) * scale
                self._ripple_radius_design = r
                self._ripple_span = max(0.05, _RIPPLE_FALLOFF * r / max(float(W), 1.0))
            if self._ripple_mode > 0.5:
                rad = math.radians(float(self._ripple_world_angle) + rot)
                self._ripple_angle = math.atan2(-math.sin(rad), math.cos(rad))

        for b in self._bursts:
            b["uv"] = uv_of(b["world"])
            if not b["screen"]:
                b["radius_design"] = max(6.0, float(b["radius_world"])) * scale

        for plume in self._bubble_plumes:
            plume["uv"] = uv_of(plume["world"])
            plume["height_design"] = max(40.0, float(plume["height_world"])) * scale
            plume["design_size"] = (W, H)

        for shell in self._fireworks:
            shell["uv"] = uv_of(shell["world"])
            rd = max(24.0, min(220.0, float(shell["radius_world"])))
            shell["radius_design"] = rd * scale
            shell["design_size"] = (W, H)

        for zap in self._zaps:
            zap["uv"] = uv_of(zap["world"])
            rd = max(12.0, min(220.0, float(zap["radius_world"])))
            zap["radius_design"] = rd * scale
            zap["design_size"] = (W, H)

        for hit in self._hits:
            hit["uv"] = uv_of(hit["world"])
            hit["radius_design"] = float(hit["radius_world"]) * scale
            hit["design_size"] = (W, H)
            if hit["angle_world"] is not None:
                # World degrees (y-up) → FB radians (y-down), camera turn included.
                rad = math.radians(float(hit["angle_world"]) + rot)
                hit["angle_fb"] = math.atan2(-math.sin(rad), math.cos(rad))

        for deb in self._debris:
            deb["uv"] = uv_of(deb["world"])
            deb["radius_design"] = float(deb["radius_world"]) * scale
            deb["design_size"] = (W, H)

    def _push_burst(
        self,
        x: float,
        y: float,
        strength: float,
        *,
        screen: bool = False,
        radius_design: float = 40.0,
        rings: bool = False,
    ) -> None:
        rd = max(6.0, float(radius_design))
        self._bursts.append({
            "world": (float(x), float(y)),
            "uv": (0.5, 0.5),
            "t": 0.0,
            "strength": float(strength),
            "screen": bool(screen),
            "radius_world": rd,
            "radius_design": rd,
            "rings": bool(rings),
        })
        if len(self._bursts) > _MAX_BURSTS:
            self._bursts = self._bursts[-_MAX_BURSTS:]
        self._remap_overlays()

    def bubbles_at(
        self,
        x: float,
        y: float,
        color=None,
        *,
        count: int = 18,
        height: float = 140.0,
        amount: float = 1.0,
    ) -> None:
        """Spawn a rising bubble plume at world ``(x, y)`` (no camera shake).

        Bubbles climb ~``height`` design units, fade, and pop. Colorable via ``color``.
        """
        uv = self._set_design_uv(x, y)
        self._bubble_seed += 1.17
        h = max(40.0, float(height))
        self._bubble_plumes.append({
            "world": (float(x), float(y)),
            "uv": uv,
            "t": 0.0,
            "color": resolve_rgb(color, default=(0.55, 0.85, 1.0)),
            "strength": float(amount),
            "height_world": h,
            "height_design": h,
            "seed": self._bubble_seed,
            "design_size": self._design_size,
            "parts": _spawn_bubble_parts(count, self._bubble_seed),
        })
        if len(self._bubble_plumes) > _MAX_BUBBLE_PLUMES:
            self._bubble_plumes = self._bubble_plumes[-_MAX_BUBBLE_PLUMES:]
        self._remap_overlays()

    def bubbles(
        self,
        color=None,
        *,
        count: int = 36,
        columns: int = 5,
        height: float = 180.0,
        amount: float = 1.0,
    ) -> None:
        """Canvas-wide bubble cascade: several plumes across the design floor."""
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        W = float(fw.design_width)
        H = float(fw.design_height)
        cols = max(1, int(columns))
        per = max(4, int(count) // cols)
        for i in range(cols):
            u = (i + 0.5) / cols
            x = u * W + (0.5 - _frac_hash(i + 0.3, 9.1)) * W * 0.08
            y = H * 0.12 + _frac_hash(i + 1.7, 2.4) * H * 0.18
            self.bubbles_at(
                x, y, color,
                count=per + int(3 * _frac_hash(i, 0.5)),
                height=height * (0.85 + 0.3 * _frac_hash(i, 3.3)),
                amount=amount,
            )

    def fireworks_at(
        self,
        x: float,
        y: float,
        color=None,
        *,
        color2=None,
        radius: float = 64.0,
        amount: float = 1.0,
        count: int = 28,
        fall: float = 0.0,
        trail: float = 0.35,
    ) -> None:
        """Burst of falling stars at world ``(x, y)`` (celebration, not pyro).

        One phase: the shell opens at ``(x, y)``. No mortar launch, shake,
        flash, or shock. ``fall=0`` (default) is a peony — no droop;
        ``~1.2`` is a willow. ``color2=None`` derives near-white glitter
        from ``color``.
        """
        uv = self._set_design_uv(x, y)
        self._fw_seed += 1.17
        rd = max(24.0, min(220.0, float(radius)))
        rgb = resolve_rgb(color, default=_FW_GOLD)
        glitter = _fw_glitter(rgb) if color2 is None else resolve_rgb(color2)
        fall_v = max(0.0, min(1.5, float(fall)))
        n = max(8, min(48, int(count)))
        n = max(6, int(round(n * particle_scale())))
        trail_v = max(0.0, min(1.0, float(trail)))
        amount_v = max(0.15, min(2.5, float(amount)))
        dur = 0.90 + 0.006 * max(0.0, rd - 32.0) + 0.22 * fall_v
        dur = max(0.85, min(1.70, dur))
        self._fireworks.append({
            "world": (float(x), float(y)),
            "uv": uv,
            "t": 0.0,
            "duration": dur,
            "color": rgb,
            "color2": glitter,
            "amount": amount_v,
            "radius_world": rd,
            "radius_design": rd,
            "fall": fall_v,
            "trail": trail_v,
            "seed": self._fw_seed,
            "design_size": self._design_size,
            "parts": _spawn_firework_stars(n, self._fw_seed),
        })
        if len(self._fireworks) > _MAX_FIREWORKS:
            self._fireworks = self._fireworks[-_MAX_FIREWORKS:]
        self._remap_overlays()

    def zap_at(
        self,
        x: float,
        y: float,
        color=None,
        *,
        radius: float = 24.0,
        amount: float = 1.0,
        count: Optional[int] = None,
        style: str = "spark",
        flash: bool = False,
    ) -> None:
        """Electric spark / lightning flash at world ``(x, y)``.

        Between Bolt(tesla) rays and ElectricBolt crackle: a bright core plus
        jagged electric rays. Styles:

        - ``spark`` — impact bloom + short crackling rays (default)
        - ``fork`` — longer branched tesla bolts
        - ``corona`` — expanding jagged ring + rim arcs

        No camera shake or screen warp. ``flash=True`` adds a brief whiteout.
        Distinct from SpatialFx ``Sparks`` (sticky) and ``fireworks_at`` (stars).
        ``count`` defaults by style (spark 16 / fork 8 / corona 12).
        """
        uv = self._set_design_uv(x, y)
        self._zap_seed += 1.31
        st = _zap_style(style)
        rd = max(12.0, min(220.0, float(radius)))
        rgb = resolve_rgb(color, default=_ZAP_CYAN)
        amount_v = max(0.15, min(2.5, float(amount)))
        if st == "spark":
            n_default, dur = 16, 0.38
        elif st == "fork":
            n_default, dur = 8, 0.55
        else:
            n_default, dur = 12, 0.52
        n = n_default if count is None else int(count)
        n = max(4, min(36, n))
        n = max(4, int(round(n * particle_scale())))
        self._zaps.append({
            "world": (float(x), float(y)),
            "uv": uv,
            "t": 0.0,
            "duration": dur,
            "color": rgb,
            "amount": amount_v,
            "radius_world": rd,
            "radius_design": rd,
            "style": st,
            "seed": self._zap_seed,
            "design_size": self._design_size,
            "parts": _spawn_zap_rays(n, self._zap_seed, style=st),
        })
        if len(self._zaps) > _MAX_ZAPS:
            self._zaps = self._zaps[-_MAX_ZAPS:]
        self._remap_overlays()
        if flash:
            self.flash(0.35 * amount_v)

    def hit_at(
        self,
        x: float,
        y: float,
        color=None,
        *,
        angle: Optional[float] = None,
        radius: float = 16.0,
        amount: float = 1.0,
        count: Optional[int] = None,
        style: str = "star",
    ) -> None:
        """Impact mark at world ``(x, y)``: something was struck and lives on.

        ``style="star"`` (default): a white-hot four-point star (full size on
        the first frame, then shrinking), a thin ring, and short spark
        streaks. ``angle`` (world degrees, 0 = +X, 90 = up) aims the sparks
        in a ~100° cone; ``None`` sprays all around. ``count`` is the spark
        streaks (default 8); ``0`` keeps star and ring without sparks.
        ``style="disc"``: a round pop of light (no sparks, no direction —
        ``angle`` / ``count`` raise). No shake / flash / warp. Many can run
        at once.
        """
        st = _hit_spec(style, angle, count)
        uv = self._set_design_uv(x, y)
        self._hit_seed += 1.21
        seed = self._hit_seed
        rd = max(6.0, min(120.0, float(radius)))
        rgb = resolve_rgb(color, default=_HIT_WARM)
        amount_v = max(0.15, min(2.5, float(amount)))
        if st == "disc" or count == 0:
            n = 0  # no sparks; quality never adds them back
        else:
            n = max(3, min(24, _HIT_SPARKS if count is None else int(count)))
            n = max(3, int(round(n * particle_scale())))
        directed = angle is not None
        if directed:
            # Spray axis arm longest; the opposite one shorter; sides short.
            arms = (1.0, 0.55, 0.7, 0.55)
        else:
            arms = (1.0, 0.7, 1.0, 0.7)
        self._hits.append({
            "world": (float(x), float(y)),
            "uv": uv,
            "t": 0.0,
            "duration": max(0.16, min(0.36, 0.20 + 0.002 * rd)),
            "color": rgb,
            "amount": amount_v,
            "radius_world": rd,
            "radius_design": rd,
            "angle_world": float(angle) if directed else None,
            "angle_fb": 0.0 if directed else _frac_hash(seed, 0.37) * math.tau,
            "twist": (_frac_hash(seed, 1.91) - 0.5) * math.radians(24.0),
            "arms": arms,
            "seed": seed,
            "design_size": self._design_size,
            "style": st,
            "parts": _spawn_hit_sparks(n, seed, directed=directed) if n else [],
        })
        if len(self._hits) > _MAX_HITS:
            self._hits = self._hits[-_MAX_HITS:]
        self._remap_overlays()

    def debris_at(
        self,
        x: float,
        y: float,
        color=None,
        *,
        radius: float = 40.0,
        amount: float = 1.0,
        count: int = 14,
        fall: float = 0.0,
        dust: bool = True,
    ) -> None:
        """Matte debris spray at world ``(x, y)``: shards + dust, no fire.

        Irregular shards (a few big, many small) fly out, slow down, tumble,
        then shrink and fade. Normal blend — readable on bright backgrounds.
        ``amount`` is the force (how far pieces fly). ``fall=0`` (default)
        drifts; ``~1`` arcs down like a platformer. ``dust`` adds soft puffs
        (skipped at low quality). No shake / flash / warp.
        """
        uv = self._set_design_uv(x, y)
        self._debris_seed += 1.43
        seed = self._debris_seed
        rd = max(10.0, min(240.0, float(radius)))
        rgb = resolve_rgb(color, default=_DEBRIS_STONE)
        amount_v = max(0.15, min(2.5, float(amount)))
        fall_v = max(0.0, min(1.5, float(fall)))
        n = max(4, min(40, int(count)))
        n = max(4, int(round(n * particle_scale())))
        dur = 0.75 + 0.0025 * rd + 0.15 * fall_v
        self._debris.append({
            "world": (float(x), float(y)),
            "uv": uv,
            "t": 0.0,
            "duration": max(0.7, min(1.4, dur)),
            "color": rgb,
            "amount": amount_v,
            "radius_world": rd,
            "radius_design": rd,
            "fall": fall_v,
            "dust": bool(dust),
            "seed": seed,
            "design_size": self._design_size,
            "parts": _spawn_debris_shards(n, seed),
            "puffs": _spawn_debris_puffs(seed),
        })
        if len(self._debris) > _MAX_DEBRIS:
            self._debris = self._debris[-_MAX_DEBRIS:]
        self._remap_overlays()

    def _apply_ripple_radius(self, radius: Optional[float]) -> None:
        """Store optional world-unit ``radius``; view scale is applied in remap."""
        if radius is None:
            self._ripple_radius_world = None
            self._ripple_radius_design = None
            self._ripple_span = 1.0
            return
        self._ripple_radius_world = max(8.0, float(radius))

    def ripple_at(
        self,
        x: float,
        y: float,
        amount: float = 1.0,
        radius: Optional[float] = None,
        *,
        shock: bool = True,
        flash: bool = False,
        shake: bool = True,
    ) -> None:
        """Radial screen-warp + accent ring at world ``(x, y)``.

        ``radius`` is peak radius in design units. ``None`` (default) keeps the
        full-frame look. ``amount`` is warp / shake magnitude.
        ``shock`` (default True): expanding accent ring. The screen-warp
        still runs when off. ``shake`` (default True): camera shake.
        """
        self._ripple_world = (float(x), float(y))
        self._ripple_world_angle = 0.0
        self._ripple_uv = self._set_design_uv(x, y)
        self._ripple_t = 0.0
        self._ripple_strength = float(amount)
        self._ripple_mode = 0.0
        self._ripple_angle = 0.0
        self._ripple_shock = bool(shock)
        self._apply_ripple_radius(radius)
        self._remap_overlays()
        if flash:
            self.flash(0.55 * amount)
        if shake:
            self.shake(10.0 * amount)

    def wave_at(
        self,
        x: float,
        y: float,
        angle: float = 0.0,
        amount: float = 1.0,
        *,
        shock: bool = True,
        flash: bool = False,
        shake: bool = True,
    ) -> None:
        """Linear shockwave. ``angle`` is degrees in world space (0 = +X).

        ``shock`` (default True): expanding accent band. The screen-warp
        still runs when off. ``shake`` (default True): camera shake.
        """
        self._ripple_world = (float(x), float(y))
        self._ripple_world_angle = float(angle)
        self._ripple_uv = self._set_design_uv(x, y)
        self._ripple_t = 0.0
        self._ripple_strength = float(amount)
        self._ripple_mode = 1.0
        self._ripple_radius_world = None
        self._ripple_radius_design = None
        self._ripple_span = 1.0
        self._ripple_shock = bool(shock)
        self._remap_overlays()
        if flash:
            self.flash(0.45 * amount)
        if shake:
            self.shake(8.0 * amount)

    def explosion_at(
        self,
        x: float,
        y: float,
        amount: float = 1.2,
        *,
        shock: bool = True,
        flash: bool = False,
        shake: bool = True,
        rings: bool = True,
    ) -> None:
        """Cinematic explosion: large pyro + optional camera / shock / flash.

        Screen-scaled fireball at ``(x, y)``. Prefer :meth:`burst_at` for
        local multi-instance ship-sized pops (no camera feedback).

        ``shake`` (default True): camera shake. ``shock``: weak warp ripple
        (radius ~2/5 of ``ripple_at`` so it sits around the fireball).
        ``rings``: expanding stroke circles (on by default).
        """
        self._push_burst(x, y, amount, screen=True, rings=rings)
        if shock:
            self._ripple_world = (float(x), float(y))
            self._ripple_world_angle = 0.0
            self._ripple_radius_world = None
            self._ripple_t = 0.0
            self._ripple_strength = 0.18 * float(amount)
            self._ripple_mode = 0.0
            self._ripple_angle = 0.0
            self._ripple_radius_design = None
            self._ripple_span = _EXPLOSION_SHOCK_SPAN
            self._ripple_shock = True
            self._remap_overlays()
        if flash:
            self.flash(0.55 * amount)
        if shake:
            self.shake(7.0 * amount)

    def burst_at(
        self,
        x: float,
        y: float,
        radius: float = 42.0,
        amount: float = 1.2,
        *,
        rings: bool = False,
    ) -> None:
        """Local multi-instance explosion (design-unit ``radius``).

        Same emissive pyro family as :meth:`explosion_at`, sized for gameplay
        (ship, crate, …). No camera shake, flash, or screen warp — fire many
        bursts at once safely.

        ``rings``: expanding stroke circles (off by default).
        """
        self._push_burst(
            x, y, amount, screen=False, radius_design=radius, rings=rings,
        )

    def _is_active(self) -> bool:
        return (
            self._flash > 1e-3
            or self._ripple_t < 0.9
            or self._shake > 0.5
            or self._glitch > 0.01
            or bool(self._bursts)
            or bool(self._bubble_plumes)
            or bool(self._fireworks)
            or bool(self._zaps)
            or bool(self._hits)
            or bool(self._debris)
        )

    def _fx_cache_key(self) -> tuple:
        n = len(self._bursts)
        t0 = round(self._bursts[0]["t"], 2) if n else 0.0
        nb = len(self._bubble_plumes)
        tb = round(self._bubble_plumes[0]["t"], 2) if nb else 0.0
        nf = len(self._fireworks)
        tf = round(self._fireworks[0]["t"], 2) if nf else 0.0
        nz = len(self._zaps)
        tz = round(self._zaps[0]["t"], 2) if nz else 0.0
        nh = len(self._hits)
        th = round(self._hits[0]["t"], 2) if nh else 0.0
        nd = len(self._debris)
        td = round(self._debris[0]["t"], 2) if nd else 0.0
        return (
            "hit",
            round(self._flash, 2),
            round(self._ripple_t, 2),
            round(self._ripple_uv[0], 2),
            round(self._ripple_uv[1], 2),
            round(self._ripple_mode, 1),
            round(self._glitch, 2),
            n,
            t0,
            nb,
            tb,
            nf,
            tf,
            nz,
            tz,
            nh,
            th,
            nd,
            td,
        )

    def _ensure_glitch_surf(self, w, h, fw):
        wi, hi = max(1, int(w)), max(1, int(h))
        surf = self._glitch_surf
        if surf is not None and surf.width() == wi and surf.height() == hi:
            return surf
        info = skia.ImageInfo.Make(
            wi, hi,
            skia.kRGBA_8888_ColorType,
            skia.kPremul_AlphaType,
            skia.ColorSpace.MakeSRGB(),
        )
        ctx = getattr(fw, "_context", None) if fw is not None else None
        surf = skia.Surface.MakeRenderTarget(ctx, skia.Budgeted.kYes, info) if ctx else None
        if surf is None:
            surf = skia.Surface(wi, hi)
        self._glitch_surf = surf
        return surf

    def _glitch_plate(self, image, w, h, t, fw):
        surf = self._ensure_glitch_surf(w, h, fw)
        gc = surf.getCanvas()
        gc.clear(skia.ColorBLACK)
        draw_glitch_shader(gc, image, w, h, t, self._glitch)
        return surf.makeImageSnapshot()

    def _draw_shader(self, canvas, image, w, h, t, fw=None) -> None:
        self._remap_overlays()
        progress = min(1.0, self._ripple_t / 0.9) if self._ripple_t < 0.9 else 1.0
        need_ripple = progress < 0.999
        need_flash = self._flash > 0.01
        need_glitch = self._glitch > 0.01
        # Design-pixel shake → FB pixels (Retina-aware).
        W, H = self._design_size or _design_size_safe()
        sx = float(w) / max(float(W), 1.0)
        sy = float(h) / max(float(H), 1.0)
        ox = self._shake_ox * sx
        oy = self._shake_oy * sy
        need_shake = abs(ox) > 0.05 or abs(oy) > 0.05
        if not need_ripple and not need_flash and not need_shake and not need_glitch:
            canvas.drawImage(image, 0, 0)
            return
        src = image
        if need_glitch and (need_ripple or need_flash):
            src = self._glitch_plate(image, w, h, t, fw)
            need_glitch = False
        # Shake is a FB-pixel translate here — never touch canvas.pan (that
        # left the camera non-identity after clear and tanked the no-FX path).
        if need_shake:
            canvas.save()
            canvas.translate(ox, oy)
        if need_glitch and not need_ripple and not need_flash:
            draw_glitch_shader(canvas, src, w, h, t, self._glitch)
        elif not need_ripple and not need_flash:
            canvas.drawImage(src, 0, 0)
        else:
            draw_ripple_shader(
                canvas, src, w, h,
                center_uv=self._ripple_uv,
                progress=progress if need_ripple else 1.0,
                strength=self._ripple_strength if need_ripple else 0.0,
                flash=self._flash if need_flash else 0.0,
                mode=self._ripple_mode if need_ripple else 0.0,
                angle=self._ripple_angle if need_ripple else 0.0,
                span=self._ripple_span if need_ripple else 1.0,
            )
        if need_shake:
            canvas.restore()

    def draw_ring(self, canvas, w, h) -> None:
        self._remap_overlays()
        W, H = self._design_size or _design_size_safe()
        sx = float(w) / max(float(W), 1.0)
        sy = float(h) / max(float(H), 1.0)
        sox = self._shake_ox * sx
        soy = self._shake_oy * sy

        # Radial ripple accent ring (skip for linear waves — no circle).
        if self._ripple_shock and self._ripple_t < 0.9 and self._ripple_mode < 0.5:
            u = self._ripple_t / 0.9
            alpha = max(0.0, 1.0 - u)
            cx = self._ripple_uv[0] * w + sox
            cy = self._ripple_uv[1] * h + soy
            if self._ripple_radius_design is not None:
                peak = float(self._ripple_radius_design) * (sx + sy) * 0.5
                start = min(20.0, peak * 0.12)
                radius = start + u * max(0.0, peak - start)
            else:
                span = max(0.05, float(self._ripple_span))
                radius = (20.0 + u * min(w, h) * 0.35) * span
            paint = skia.Paint(
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=2.5 + 4.0 * (1.0 - u),
                Color4f=skia.Color4f(0.7, 0.9, 1.0, 0.28 * alpha),
                AntiAlias=True,
                BlendMode=skia.BlendMode.kPlus,
            )
            canvas.drawCircle(cx, cy, radius, paint)

        # Linear wave accent: short glowing band along the front.
        if self._ripple_shock and self._ripple_t < 0.9 and self._ripple_mode > 0.5:
            u = self._ripple_t / 0.9
            alpha = max(0.0, 1.0 - u)
            cx = self._ripple_uv[0] * w + sox
            cy = self._ripple_uv[1] * h + soy
            # Progress pushes the front outward along the wave normal.
            dist = (20.0 + u * min(w, h) * 0.4)
            nx = math.cos(self._ripple_angle)
            ny = math.sin(self._ripple_angle)
            px, py = -ny, nx
            half_len = min(w, h) * 0.55
            x0 = cx + nx * dist - px * half_len
            y0 = cy + ny * dist - py * half_len
            x1 = cx + nx * dist + px * half_len
            y1 = cy + ny * dist + py * half_len
            paint = skia.Paint(
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=3.0 + 5.0 * (1.0 - u),
                Color4f=skia.Color4f(0.85, 0.95, 1.0, 0.32 * alpha),
                AntiAlias=True,
                BlendMode=skia.BlendMode.kPlus,
            )
            canvas.drawLine(x0, y0, x1, y1, paint)

        # Pyro pool: cinematic (screen-scaled) + local (design radius) bursts.
        for b in self._bursts:
            p = b["t"] / _EXPLOSION_DURATION
            if p >= 1.0:
                continue
            cx = b["uv"][0] * w + sox
            cy = b["uv"][1] * h + soy
            if b["screen"]:
                short = min(w, h)
            else:
                radius_fb = b["radius_design"] * (sx + sy) * 0.5
                short = _short_for_local_radius(radius_fb)
            _draw_explosion_pyro(
                canvas, cx, cy, p, b["strength"], short,
                rings=bool(b.get("rings", False)),
            )

        for plume in self._bubble_plumes:
            _draw_bubble_plume(canvas, plume, w, h, sox, soy)

        for shell in self._fireworks:
            _draw_firework_shell(canvas, shell, w, h, sox, soy)

        for zap in self._zaps:
            _draw_zap_flash(canvas, zap, w, h, sox, soy)

        # Debris under impact marks: matte pieces, then emissive sparks on top.
        for deb in self._debris:
            _draw_debris(canvas, deb, w, h, sox, soy)

        for hit in self._hits:
            _draw_hit(canvas, hit, w, h, sox, soy)

    def tick_frame(self, dt: float, canvas) -> None:
        """Decay flash/shake/glitch/ripple/bursts/bubbles/fireworks/zaps/hits/debris. Shake offset applied in draw."""
        if self._flash > 0:
            self._flash = max(0.0, self._flash - dt * 2.8)
        if self._shake > 0:
            self._shake = max(0.0, self._shake - dt * 55.0)
        if self._glitch > 0:
            self._glitch = max(0.0, self._glitch - dt * 2.8)
        self._ripple_t += dt

        if self._bursts:
            for b in self._bursts:
                b["t"] += dt
            self._bursts = [b for b in self._bursts if b["t"] < _EXPLOSION_DURATION]

        if self._bubble_plumes:
            for plume in self._bubble_plumes:
                plume["t"] += dt
            self._bubble_plumes = [
                p for p in self._bubble_plumes if p["t"] < _BUBBLE_DURATION
            ]

        if self._fireworks:
            for shell in self._fireworks:
                shell["t"] += dt
            self._fireworks = [
                f for f in self._fireworks if f["t"] < f["duration"]
            ]

        if self._zaps:
            for zap in self._zaps:
                zap["t"] += dt
            self._zaps = [
                z for z in self._zaps if z["t"] < z["duration"]
            ]

        if self._hits:
            for hit in self._hits:
                hit["t"] += dt
            self._hits = [m for m in self._hits if m["t"] < m["duration"]]

        if self._debris:
            for deb in self._debris:
                deb["t"] += dt
            self._debris = [d for d in self._debris if d["t"] < d["duration"]]

        if self._shake > 0.5:
            ang = random.random() * math.tau
            self._shake_ox = math.cos(ang) * self._shake
            self._shake_oy = math.sin(ang) * self._shake
        else:
            self._shake_ox = 0.0
            self._shake_oy = 0.0
        self._remap_overlays()


def _design_size_safe():
    try:
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        return float(fw.design_width), float(fw.design_height)
    except Exception:
        return 1200.0, 800.0
