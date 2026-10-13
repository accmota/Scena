"""
Author-facing background field kinds (pre-scene full-screen fields).

Wallpaper family (`Wallpaper`, `SkyGradient`) becomes the base. Ambient and
tunnels append as extras::

    SkyGradient("night")
    Stars(density=0.9, pan_response=0.02)
    Clouds(pan_response=0.1)
    canvas.set_fly(Tunnel())
    canvas.set_fly(StarFly(speed=1.5, center=(200, 0)))

Zero-arg constructors look good. Finer control is optional.

``color=`` is ``ColorLike`` (name, ``Color``, RGB tuple). Looks, SpatialFx,
and canvas post effects are the wrong family — construct those on their
own stacks. Shared camera knobs on every field: ``pan_response``,
``zoom_response``, ``rotation_response``, ``scroll``, ``enabled``.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import skia

from .background import (
    BackgroundField,
    CameraSample,
    coerce_wallpaper_source,
    looks_like_image_path,
    vanishing_point_offset,
)
from .color import Color, ColorLike, resolve_rgb
from .validate import expect_choice
from .gradient_presets import SCENIC_PRESET_NAMES
from .style import BackgroundFit, BackgroundImage, Gradient, GradientType, Texture
from ._sksl_backdrop import (
    floor_builder,
    startunnel_builder,
    road_builder,
    starfield_builder,
    planetfly_builder,
    draw_shader_rect,
)
from ._sksl_ambient import (
    clouds_builder,
    stars_builder,
    stardust_builder,
    stardust_survival_builder,
    chromadust_builder,
    chromadust_survival_builder,
    nebuladust_builder,
    nebuladust_survival_builder,
    borealis_builder,
    plasma_builder,
    mist_builder,
    debris_builder,
    embers_builder,
    windstreaks_builder,
    ground_builder,
    nebula_builder,
    lattice_builder,
)
from .fx_quality import fidelity_is_survival
from ._sksl_ambient_kit import (
    churningclouds_builder,
    filamentfield_builder,
)


# Viewport fraction (author y-up) for the sky/ground seam blend. ``fade=0``
# restores a hard cut. Same default on ``SkyGradient`` and ``Ground`` so a
# paired horizon stays aligned. ~0.6% of the frame (~4–6 px) — a lip, not a haze.
HORIZON_FADE = 0.003


def _set_common_uvs(
    builder: skia.RuntimeShaderBuilder,
    *,
    w: float,
    h: float,
    t: float,
    offset_xy: Tuple[float, float],
    scale: float,
    rotation: float,
) -> None:
    """Shared uniforms. ``rotation`` is camera-matching CCW+ radians."""
    builder.setUniform("resolution", [float(w), float(h)])
    builder.setUniform("time", float(t))
    builder.setUniform("u_offset", [float(offset_xy[0]), float(offset_xy[1])])
    builder.setUniform("u_scale", float(scale))
    builder.setUniform("u_rotation", float(rotation))


def _radial_fly_uv(
    field,
    *,
    cam: CameraSample,
    design_width: float,
    design_height: float,
    fb_width: float,
    fb_height: float,
) -> Tuple[float, float, float, float]:
    """Parallax UV plus authored vanishing-point offset for Tunnel / StarFly.

    ``center=None`` → screen center (current rest look). ``pan_response``
    banks that point; it is not wallpaper parallax.
    """
    ox, oy, scale, rot = field._parallax_uv(
        cam=cam,
        design_width=design_width,
        design_height=design_height,
        fb_width=fb_width,
        fb_height=fb_height,
    )
    center = getattr(field, "center", None)
    if center is None:
        return (ox, oy, scale, rot)
    from .shapes import get_xy
    cx, cy = get_xy(center, bare=True)
    vx, vy = vanishing_point_offset(
        center_x=cx,
        center_y=cy,
        rest_x=cam.rest_x,
        rest_y=cam.rest_y,
        design_width=design_width,
        design_height=design_height,
        fb_width=fb_width,
        fb_height=fb_height,
    )
    return (ox + vx, oy + vy, scale, rot)


def _field_boilerplate(self, *, pan_response, zoom_response, rotation_response, scroll, enabled):
    self.pan_response = float(pan_response)
    self.zoom_response = float(zoom_response)
    self.rotation_response = float(rotation_response)
    self.enabled = bool(enabled)
    self._apply_scroll_arg(scroll)


def _lerp_rgb(a, b, u: float) -> Tuple[float, float, float]:
    u = max(0.0, min(1.0, float(u)))
    return (
        float(a[0]) + (float(b[0]) - float(a[0])) * u,
        float(a[1]) + (float(b[1]) - float(a[1])) * u,
        float(a[2]) + (float(b[2]) - float(a[2])) * u,
    )


def _sample_ramp_stops(stops, t: float) -> Tuple[float, float, float]:
    if not stops:
        return (1.0, 1.0, 1.0)
    t = max(0.0, min(1.0, float(t)))
    if t <= stops[0][0]:
        rgb = stops[0][1]
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if t <= p1:
            span = float(p1) - float(p0)
            u = 0.0 if span < 1e-9 else (t - float(p0)) / span
            return _lerp_rgb(c0, c1, u)
    rgb = stops[-1][1]
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]))


def _rgb5_from_stops(stops) -> Tuple[Tuple[float, float, float], ...]:
    return tuple(_sample_ramp_stops(stops, t) for t in (0.0, 0.25, 0.5, 0.75, 1.0))


def _chromadust_palette(colors):
    """Resolve Chromadust ``colors=`` to ``(rainbow: bool, rgb5)``.

    ``None`` is HSV rainbow. A preset name, ``Gradient``, or a sequence of
    colours becomes a 5-stop palette sampled along the rotating field.
    """
    from .gradient_presets import get_preset

    if colors is None:
        return True, (
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.5, 0.0, 1.0),
        )
    if isinstance(colors, str):
        stops = get_preset(colors)
        if stops is None:
            raise ValueError(
                f"Chromadust colors={colors!r} is not a gradient preset. "
                "Pass a preset name, Gradient(...), or a sequence of colors."
            )
        return False, _rgb5_from_stops(stops)
    if isinstance(colors, Gradient):
        stops = [
            (float(p), tuple(float(x) for x in c.rgb[:3]))
            for p, c in zip(colors._positions, colors._colors)
        ]
        if not stops:
            raise ValueError("Chromadust Gradient has no stops")
        return False, _rgb5_from_stops(stops)
    if isinstance(colors, (list, tuple)):
        if len(colors) == 0:
            raise ValueError("Chromadust colors sequence is empty")
        n = len(colors)
        stops = [
            (0.0 if n == 1 else i / (n - 1), resolve_rgb(c, default=(1.0, 1.0, 1.0)))
            for i, c in enumerate(colors)
        ]
        return False, _rgb5_from_stops(stops)
    raise TypeError(
        "Chromadust colors= takes None (rainbow), a preset name, "
        f"Gradient, or a sequence of colors, got {type(colors).__name__}."
    )


# ---------------------------------------------------------------------------
# Sky sugar — full-frame vertical wallpaper from shared Gradient presets
# ---------------------------------------------------------------------------

_SKY_ALIASES = {
    "daylight": "day",
    "sky": "day",
    "noon": "day",
    "sunrise": "dawn",
    "morning": "dawn",
    "evening": "sunset",
    "sunsets": "sunset",
    "twilight": "dusk",
    "dark": "night",
    "midnight": "night",
    "void": "space",
    "cosmos": "space",
    "cloudy": "overcast",
    "grey": "overcast",
    "gray": "overcast",
    "sand": "desert",
    "alien": "toxic",
    "radioactive": "toxic",
    "fire": "ember",
    "arctic": "ice",
    "cold": "ice",
    "deep": "underwater",
}


def _resolving_sky_names():
    """``(scenic, aliases)``: sorted names ``SkyGradient`` can actually build.

    Filtered through ``get_preset`` so an error message never offers a name
    that would itself fail.
    """
    from .gradient_presets import SCENIC_PRESET_NAMES, get_preset

    scenic = sorted(n for n in SCENIC_PRESET_NAMES if get_preset(n) is not None)
    aliases = sorted(a for a, t in _SKY_ALIASES.items() if get_preset(t) is not None)
    return scenic, aliases


def _require_sky_palette_or_color(palette) -> None:
    """``SkyGradient(palette)`` is a sky preset or a color; a typo raises instead of magenta."""
    from .color import ColorNames
    from .gradient_presets import preset_names
    from .validate import did_you_mean

    if not isinstance(palette, str):
        return
    text = palette.strip()
    if text.startswith("#") or ColorNames.is_known(text):
        return
    scenic, aliases = _resolving_sky_names()
    raise ValueError(
        f"SkyGradient palette {palette!r} is neither a sky preset nor a color."
        f"{did_you_mean(text, scenic + aliases + list(preset_names()))} "
        f"Sky presets: {', '.join(scenic)}. Or pass a color "
        f"(\"navy\", \"#203050\") or top=/middle=/bottom=."
    )


def sky_palette(name: str):
    """Return ``(top, middle, bottom)`` RGB triples for a named sky, or None."""
    from .gradient_presets import get_preset, normalize_preset_name, sample_stops_rgb

    key = normalize_preset_name(name)
    key = _SKY_ALIASES.get(key, key)
    stops = get_preset(key)
    if stops is None:
        return None
    return sample_stops_rgb(stops)


class Wallpaper(BackgroundField):
    """Solid / gradient / image / texture field used for ``canvas.background.base``.

    Zero-arg ``Wallpaper()`` is opaque black. ``source`` is a color name,
    RGB tuple, ``Color``, ``Gradient``, ``Texture``, image filename, or
    ``skia.Image``. A string with ``.`` / ``/`` is a file
    (``Wallpaper("bg1.jpg")``); otherwise a color (``Wallpaper("navy")``).
    Image knobs (``fit``, ``tile_mode``, ``scale``, ``tile_size``,
    ``underlay``, ``filename``, ``image``) apply only to image sources —
    they raise ``TypeError`` on a color / gradient / texture.
    Looks, filters, SpatialFx, and post effects raise ``TypeError``.
    Construction becomes the wallpaper **base** (replaces the previous
    base). Plain solids take a single framebuffer ``clear`` when camera
    knobs are at default.

    Args:
        source: A color, ``Gradient``, ``Texture``, image file, or ``skia.Image``
            (default black).
        filename: Instead of ``source``: an image path.
        image: Instead of ``source``: a loaded ``skia.Image``.
        fit: Images: ``"cover"`` · ``"contain"`` · ``"stretch"`` · ``"tile"``.
        tile_mode: Images: what shows past the image edge (a panning or
            zoomed-out camera): ``"decal"`` (nothing; the underlay) ·
            ``"clamp"`` · ``"repeat"`` · ``"mirror"``. Omitted: ``"repeat"``
            with ``fit="tile"``, else ``"decal"``.
        scale: Images: extra zoom (> 0).
        tile_size: Images with ``fit="tile"``: tile size in design units.
        underlay: Images: color behind a ``contain`` letterbox and past a
            ``"decal"`` edge; ``None`` = no clear.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    _place = "base"

    def __init__(
        self,
        source=None,
        *,
        filename: Optional[str] = None,
        image=None,
        fit=None,
        tile_mode=None,
        scale: Optional[float] = None,
        tile_size=None,
        underlay=None,
        pan_response: float = 0.0,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        image_kw = any(
            v is not None
            for v in (filename, image, fit, tile_mode, scale, tile_size, underlay)
        )
        want_image = (
            image_kw
            or looks_like_image_path(source)
            or isinstance(source, skia.Image)
            or isinstance(source, BackgroundImage)
        )
        if want_image:
            if isinstance(source, (Color, Gradient, Texture)):
                raise TypeError(
                    "fit / tile_mode / scale / tile_size / underlay / filename / image "
                    "only apply to image wallpapers, not Color / Gradient / Texture"
                )
            if isinstance(source, (tuple, list)):
                raise TypeError(
                    "fit / tile_mode / scale / tile_size / underlay / filename / image "
                    "only apply to image wallpapers, not a color tuple"
                )
            if (
                isinstance(source, str)
                and not looks_like_image_path(source)
                and image_kw
            ):
                raise TypeError(
                    f"fit= only applies to image wallpapers — {source!r} is a "
                    f"color name. Use Wallpaper({source!r}) or "
                    f'Wallpaper("file.jpg", fit=...).'
                )
            if isinstance(source, BackgroundImage):
                if image_kw:
                    raise TypeError(
                        "image kwargs belong on Wallpaper(...); "
                        "the source is already an image payload"
                    )
                resolved = source
            else:
                resolved = BackgroundImage(
                    source,
                    filename=filename,
                    image=image,
                    fit=BackgroundFit.COVER if fit is None else fit,
                    tile_mode=tile_mode,
                    scale=1.0 if scale is None else scale,
                    tile_size=tile_size,
                    underlay=underlay,
                )
        elif source is None:
            resolved = Color(0.0, 0.0, 0.0, 1.0)
        else:
            resolved = coerce_wallpaper_source(source)
        self.source = resolved
        self.pan_response = float(pan_response)
        self.zoom_response = float(zoom_response)
        self.rotation_response = float(rotation_response)
        self._apply_scroll_arg(scroll)
        self.enabled = bool(enabled)
        self._cache_key = None
        self._base_fill = None
        if want_image:
            # Decode on construct (setup, or the frame that asked), not on the
            # first frame that shows it — e.g. a ``Wallpaper.temp`` swapped in later.
            from .style import prewarm_background_image
            prewarm_background_image(resolved)

    def _is_active(self) -> bool:
        return bool(self.enabled)

    def _is_plain_solid(self) -> bool:
        from .color import Color
        return isinstance(self.source, Color)

    def _solid_color4f(self):
        """Return a Color4f for pre-blit clear, or None when base is not solid."""
        if not self._is_plain_solid():
            return None
        return self.source.color4f

    def draw(
        self,
        canvas: skia.Canvas,
        w: float,
        h: float,
        t: float,
        cam: CameraSample,
        *,
        design_width: float,
        design_height: float,
        fw=None,
    ) -> None:
        from .style import build_background_fill

        # Fast path: opaque solid with no camera drift — one clear, no shader.
        if self._is_plain_solid():
            sx, sy = self.scroll
            if (
                float(self.pan_response) == 0.0
                and float(self.zoom_response) == 0.0
                and float(self.rotation_response) == 0.0
                and float(sx) == 0.0
                and float(sy) == 0.0
            ):
                canvas.clear(self.source.color4f)
                return
            # Solid has no spatial structure; camera knobs are a no-op.
            canvas.clear(self.source.color4f)
            return

        wi = int(w)
        hi = int(h)
        if wi <= 0 or hi <= 0:
            return
        src_id = id(self.source)
        tile_size = getattr(self.source, "tile_size", None)
        src_scale = getattr(self.source, "scale", None)
        src_fit = getattr(self.source, "fit", None)
        # Texture.set_alpha changes the same object: rebuild on a new alpha.
        src_alpha = getattr(self.source, "alpha", None)
        rest_x = float(cam.rest_x)
        rest_y = float(cam.rest_y)
        key = (
            wi, hi, src_id,
            float(design_width), float(design_height),
            rest_x, rest_y,
            tile_size, src_scale, src_fit, src_alpha,
        )
        if key != self._cache_key or self._base_fill is None:
            self._base_fill = build_background_fill(
                self.source, wi, hi, float(design_width), float(design_height),
                rest_x=rest_x, rest_y=rest_y,
            )
            self._cache_key = key
        fill = self._base_fill

        ox, oy, scale, rot = self._parallax_uv(
            cam=cam,
            design_width=design_width,
            design_height=design_height,
            fb_width=w,
            fb_height=h,
        )
        if fill.underlay is not None:
            canvas.clear(fill.underlay)
        elif abs(rot) > 1e-9:
            # Rotation uncovers wedges the previous canvas rect no longer
            # paints. Wipe them so leftover pixels cannot survive a miss.
            canvas.clear(skia.Color4f(0.0, 0.0, 0.0, 1.0))

        cam_active = (
            abs(ox) > 1e-9
            or abs(oy) > 1e-9
            or abs(scale - 1.0) > 1e-9
            or abs(rot) > 1e-9
        )
        if not cam_active:
            fill.fill(canvas, fill.rect)
            return

        # Camera via canvas CTM + cached shader (not makeWithLocalMatrix).
        # Expand the draw rect so after pan/zoom/rotation it still covers the
        # viewport. A viewport-sized rect rotated about center leaves corner
        # wedges unpainted (previous-frame leftover). TILE already needed this;
        # gradient / cover / SkyGradient do too.
        canvas.save()
        try:
            # Device clip first so an oversized rect only fills the viewport.
            canvas.clipRect(fill.rect)
            cx = float(w) * 0.5
            cy = float(h) * 0.5
            s = max(float(scale), 1e-4)
            canvas.translate(cx, cy)
            if abs(float(rot)) > 1e-12:
                # rot is CCW+ (matches camera). Skia y-down rotate is CW+.
                canvas.rotate(-float(rot) * (180.0 / 3.141592653589793))
            if abs(s - 1.0) > 1e-9:
                canvas.scale(s, s)
            canvas.translate(-cx + float(ox), -cy + float(oy))
            # Conservative local extent for inv(T(c)·R·S·T(-c+o)) of the
            # viewport (diagonal + offset, scaled for zoom-out).
            diag = (float(w) * float(w) + float(h) * float(h)) ** 0.5
            pad = (0.5 * diag + abs(float(ox)) + abs(float(oy))) / s + 2.0
            draw_rect = skia.Rect.MakeLTRB(
                -pad, -pad, float(w) + pad, float(h) + pad,
            )
            fill.fill(canvas, draw_rect)
        finally:
            canvas.restore()


class SkyGradient(BackgroundField):
    """Opaque vertical gradient base — **base only**, no sun/clouds.

    Construction becomes ``canvas.background.base`` (last wallpaper wins).

    Sugar for a full-frame ``Gradient(..., type=GradientType.LINEAR, angle=-90)`` wallpaper
    (``top`` at the zenith, ``middle`` on ``horizon``, ``bottom`` below a short blend)::

        canvas.background.base = SkyGradient("sunset")
        canvas.background.base = SkyGradient("night")
        canvas.background.base = SkyGradient(top="navy", middle="sky blue")
        # Same ``horizon`` as Ground (author y-up) — atmosphere colour on the seam:
        canvas.background.base = SkyGradient("day", horizon=0.42)
        canvas.background.add(Ground(horizon=0.42))

    Prefer either a named ``palette`` **or** ``top`` / ``middle`` / ``bottom``
    overrides. Any colour override skips the named preset and fills unspecified
    slots from ``"day"``.

    ``horizon`` is where the atmosphere colour (``middle``) sits: fraction of
    screen height (0–1, **author y-up** from the bottom). ``top`` is always the
    zenith (screen top). Below the line, ``bottom`` ramps in across ``fade``
    (default ~0.6% of the frame; ``fade=0`` is a hard cut). Default ``horizon=0``
    puts ``middle`` at the bottom — a full-height sky, no ground tint. Matches
    ``Ground(horizon=…, fade=…)``.

    Scenic presets: ``day``, ``dawn``, ``sunset``, ``dusk``, ``night``, ``space``,
    ``overcast``, ``desert``, ``forest``, ``toxic``, ``ember``, ``ice``, ``underwater``
    (``SCENIC_PRESET_NAMES``). Sky aliases (``void``, ``alien``, ``fire``, …) map
    onto these; any other ``Gradient`` preset name also works.

    Args:
        palette: ``"day"`` (default), ``"dawn"``, ``"sunset"``, ``"dusk"``, ``"night"``,
            ``"space"``, …
        top: Zenith color (overrides the palette).
        middle: Horizon color.
        bottom: Color below the horizon.
        horizon: Horizon line, 0–1 from the bottom (0 = sky all the way down).
        fade: Blend below the horizon (0 = hard cut).
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    _place = "base"
    _PALETTES = tuple(sorted(SCENIC_PRESET_NAMES))

    def __init__(
        self,
        palette: Optional[str] = "day",
        *,
        top=None,
        middle=None,
        bottom=None,
        horizon: float = 0.0,
        fade: float = HORIZON_FADE,
        pan_response: float = 0.0,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        from .gradient_presets import get_preset, normalize_preset_name, sample_stops_rgb

        custom = top is not None or middle is not None or bottom is not None
        stop_list = None
        z = h = btm = None

        if not custom and palette is not None:
            key = normalize_preset_name(palette)
            key = _SKY_ALIASES.get(key, key)
            stops = get_preset(key)
            if stops is not None:
                stop_list = [(float(p), tuple(c)) for p, c in stops]
                z, h, btm = sample_stops_rgb(stops)
            elif str(palette).strip():
                _require_sky_palette_or_color(palette)
                base = resolve_rgb(palette, default=(0.35, 0.55, 0.85))
                z = (base[0] * 0.35, base[1] * 0.4, base[2] * 0.55)
                h = (
                    min(1.0, base[0] * 1.2),
                    min(1.0, base[1] * 1.15),
                    min(1.0, base[2] * 1.05),
                )
                btm = (base[0] * 0.5, base[1] * 0.5, base[2] * 0.45)

        if z is None:
            stops = get_preset("day")
            stop_list = [(float(p), tuple(c)) for p, c in stops]
            z, h, btm = sample_stops_rgb(stops)

        if top is not None:
            z = resolve_rgb(top, default=z)
        if middle is not None:
            h = resolve_rgb(middle, default=h)
        if bottom is not None:
            btm = resolve_rgb(bottom, default=btm)

        self.top = z
        self.middle = h
        self.bottom = btm
        self.palette = str(palette) if palette is not None else None
        self.horizon = float(horizon)
        self.fade = float(fade)

        if custom or stop_list is None:
            self._stops = [
                (0.0, tuple(self.top)),
                (0.5, tuple(self.middle)),
                (1.0, tuple(self.bottom)),
            ]
        else:
            self._stops = stop_list

        self._grad_key = None
        from .place import unplaced_creation
        with unplaced_creation():
            self._wallpaper = Wallpaper(
                self._make_gradient(),
                pan_response=pan_response,
                zoom_response=zoom_response,
                rotation_response=rotation_response,
                scroll=scroll,
                enabled=enabled,
            )
        self._grad_key = self._ramp_key()
        self.pan_response = float(pan_response)
        self.zoom_response = float(zoom_response)
        self.rotation_response = float(rotation_response)
        self.enabled = bool(enabled)
        self._apply_scroll_arg(scroll)

    def _ramp_end_from_top(self) -> float:
        """Author y-up ``horizon`` → top→bottom position of the atmosphere stop."""
        h = min(max(float(self.horizon), 0.0), 1.0)
        return 1.0 - h

    def _clamped_fade(self) -> float:
        return min(max(float(self.fade), 0.0), 0.5)

    def _ramp_key(self):
        return (
            round(self._ramp_end_from_top(), 4),
            round(self._clamped_fade(), 4),
            id(self._stops),
        )

    def _ramp_stops(self):
        """Place ``middle`` on ``horizon``; blend into ``bottom`` across ``fade``.

        Palette stop *positions* are ignored — they supply colours only.
        ``horizon=0`` is zenith → atmosphere across the full frame (no ground
        tint). ``horizon=1`` is solid ``bottom``. ``fade=0`` is a hard cut at
        the seam; the default is a small band just below the horizon.
        """
        top = tuple(self.top) if self.top is not None else (0.0, 0.0, 0.0)
        mid = tuple(self.middle) if self.middle is not None else top
        btm = tuple(self.bottom) if self.bottom is not None else mid
        end = self._ramp_end_from_top()
        if end >= 1.0 - 1e-6:
            return [(0.0, top), (1.0, mid)]
        if end <= 1e-6:
            return [(0.0, btm), (1.0, btm)]
        fade = self._clamped_fade()
        blend = min(1.0, end + fade)
        if fade <= 1e-6 or blend <= end + 1e-6:
            return [
                (0.0, top),
                (end, mid),
                (end, btm),
                (1.0, btm),
            ]
        stops = [
            (0.0, top),
            (end, mid),
            (blend, btm),
        ]
        if blend < 1.0 - 1e-6:
            stops.append((1.0, btm))
        return stops

    def _make_gradient(self) -> Gradient:
        args = [(p, Color(*c)) for p, c in self._ramp_stops()]
        # Stops run top → bottom: ``angle=-90`` (y-up, like every Gradient).
        return Gradient(*args, type=GradientType.LINEAR, angle=-90.0)

    def _sync_gradient(self, design_height: float = 0.0) -> None:
        # Auto-fit LINEAR angle=-90 covers the frame; rebuild only when the ramp changes.
        key = self._ramp_key()
        if key == self._grad_key:
            return
        self._wallpaper.source = self._make_gradient()
        self._wallpaper._cache_key = None
        self._grad_key = key

    def _is_active(self) -> bool:
        return bool(self.enabled)

    def draw(
        self,
        canvas: skia.Canvas,
        w: float,
        h: float,
        t: float,
        cam: CameraSample,
        *,
        design_width: float,
        design_height: float,
        fw=None,
    ) -> None:
        self._sync_gradient(design_height)
        self._wallpaper.pan_response = self.pan_response
        self._wallpaper.zoom_response = self.zoom_response
        self._wallpaper.rotation_response = self.rotation_response
        self._wallpaper.scroll = self.scroll
        self._wallpaper.enabled = self.enabled
        self._wallpaper.draw(
            canvas, w, h, t, cam,
            design_width=design_width, design_height=design_height, fw=fw,
        )


class Clouds(BackgroundField):
    """Fbm cloud deck. Zero-arg is a soft white band; stack several for depth.

    Drawn on a reduced-resolution plate (``res_scale``, default 0.5) with
    bilinear upscale. At ``FxQuality.LOW`` / survival tier the plate drops to
    ~0.4×. Not a look (no ``shape.visual = Clouds()``) and not post FX.

    Args:
        color: Cloud color (default white).
        amount: Coverage (default 0.45).
        band: Vertical band position (default 0.45).
        spread: How wide the band is (default 0.55).
        detail: Detail (default 1).
        speed: Own drift speed.
        alpha: Opacity, 0–1.
        res_scale: Render resolution as a fraction of the screen (1 = full; lower is
            cheaper).
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    _SURVIVAL_RES_SCALE = 0.4

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        amount: float = 0.45,
        band: float = 0.45,
        spread: float = 0.55,
        detail: float = 1.0,
        speed: float = 1.0,
        alpha: float = 1.0,
        res_scale: float = 0.5,
        pan_response: float = 0.08,
        zoom_response: float = 0.05,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.92, 0.94, 0.98))
        self.amount = float(amount)
        self.band = float(band)
        self.spread = float(spread)
        self.detail = float(detail)
        self.speed = float(speed)
        self.alpha = float(alpha)
        self.res_scale = float(res_scale)
        self._lr_cache: Optional[tuple] = None
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        rs = self._SURVIVAL_RES_SCALE if fidelity_is_survival() else self.res_scale

        def bind(b, lw, lh, sx, sy):
            _set_common_uvs(
                b, w=lw, h=lh, t=t,
                offset_xy=(ox * sx, oy * sy), scale=scale, rotation=rot,
            )
            b.setUniform("u_color", list(self.color))
            b.setUniform("u_amount", float(self.amount))
            b.setUniform("u_band", float(self.band))
            b.setUniform("u_spread", float(self.spread))
            b.setUniform("u_detail", float(self.detail))
            b.setUniform("u_speed", float(self.speed))
            b.setUniform("u_alpha", float(self.alpha))

        _draw_lowres(
            self, canvas, w, h, clouds_builder, fw,
            res_scale=rs, bind=bind,
        )


class Stars(BackgroundField):
    """Flat 2D starfield. Zero-arg is a transparent sprinkle (pair with
    ``SkyGradient("night"|"space")``). Not SpatialFx ``Starburst``.

    Args:
        color: Star color.
        density: How many (default 0.8).
        twinkle: Twinkle (0 = steady).
        amount: Brightness.
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        density: float = 0.8,
        twinkle: float = 0.0,
        amount: float = 1.0,
        alpha: float = 1.0,
        pan_response: float = 0.02,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.75, 0.82, 1.0))
        self.density = float(density)
        self.twinkle = float(twinkle)
        self.amount = float(amount)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = stars_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_density", float(self.density))
        b.setUniform("u_twinkle", float(self.twinkle))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Stardust(BackgroundField):
    """Soft multi-octave dust / nebula wash (alpha from density).

    Drawn on a reduced-resolution plate (``res_scale``, default 0.6) with
    bilinear upscale. At ``FxQuality.LOW`` / survival tier uses a single
    4-octave FBM on a ~0.4× plate.

    Args:
        color: First color.
        color2: Second color.
        amount: Density.
        speed: Own drift (default 0.2).
        alpha: Opacity, 0–1.
        res_scale: Render resolution as a fraction of the screen (1 = full; lower is
            cheaper).
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    _SURVIVAL_RES_SCALE = 0.4

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        color2=None,
        amount: float = 1.0,
        speed: float = 0.2,
        alpha: float = 0.7,
        res_scale: float = 0.6,
        pan_response: float = 0.08,
        zoom_response: float = 0.1,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.45, 0.25, 0.75))
        self.color2 = resolve_rgb(color2, default=(0.15, 0.55, 0.85))
        self.amount = float(amount)
        self.speed = float(speed)
        self.alpha = float(alpha)
        self.res_scale = float(res_scale)
        self._lr_cache: Optional[tuple] = None
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        survival = fidelity_is_survival()
        rs = self._SURVIVAL_RES_SCALE if survival else self.res_scale
        builder = stardust_survival_builder if survival else stardust_builder

        def bind(b, lw, lh, sx, sy):
            _set_common_uvs(
                b, w=lw, h=lh, t=t,
                offset_xy=(ox * sx, oy * sy), scale=scale, rotation=rot,
            )
            b.setUniform("u_color", list(self.color))
            b.setUniform("u_color2", list(self.color2))
            b.setUniform("u_amount", float(self.amount))
            b.setUniform("u_speed", float(self.speed))
            b.setUniform("u_alpha", float(self.alpha))

        _draw_lowres(
            self, canvas, w, h, builder, fw,
            res_scale=rs, bind=bind,
        )


class Chromadust(BackgroundField):
    """Stardust density with a rotating palette (rainbow, or any gradient).

    Zero-arg is a full HSV rainbow. Pass a preset name, a ``Gradient``, or a
    sequence of colours to walk that ramp instead. ``reflect=True`` (default)
    ping-pongs the ramp (red→blue→red); ``False`` wraps.

        Chromadust()
        Chromadust("plasma")
        Chromadust(Gradient("sunset"))
        Chromadust(("magenta", "cyan", "gold"))
        Chromadust(("red", "blue"), reflect=False)

    Args:
        colors: ``None`` = rainbow; a preset name, ``Gradient``, or list of colors.
        amount: Density.
        speed: Own drift (default 0.2).
        hue_speed: Palette cycling speed (default 0.25).
        saturation: Chroma (default 1).
        reflect: ``True`` = go back and forth along the ramp; ``False`` = wrap around.
        alpha: Opacity, 0–1.
        res_scale: Render resolution as a fraction of the screen (1 = full; lower is
            cheaper).
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    _SURVIVAL_RES_SCALE = 0.4

    def __init__(
        self,
        colors=None,
        *,
        amount: float = 1.0,
        speed: float = 0.2,
        hue_speed: float = 0.25,
        saturation: float = 1.0,
        reflect: bool = True,
        alpha: float = 0.7,
        res_scale: float = 0.6,
        pan_response: float = 0.08,
        zoom_response: float = 0.1,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.rainbow, self.palette = _chromadust_palette(colors)
        self.colors = colors
        self.amount = float(amount)
        self.speed = float(speed)
        self.hue_speed = float(hue_speed)
        self.saturation = float(saturation)
        self.reflect = bool(reflect)
        self.alpha = float(alpha)
        self.res_scale = float(res_scale)
        self._lr_cache: Optional[tuple] = None
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        survival = fidelity_is_survival()
        rs = self._SURVIVAL_RES_SCALE if survival else self.res_scale
        builder = chromadust_survival_builder if survival else chromadust_builder
        rainbow, pal = _chromadust_palette(self.colors)
        self.rainbow, self.palette = rainbow, pal

        def bind(b, lw, lh, sx, sy):
            _set_common_uvs(
                b, w=lw, h=lh, t=t,
                offset_xy=(ox * sx, oy * sy), scale=scale, rotation=rot,
            )
            b.setUniform("u_amount", float(self.amount))
            b.setUniform("u_speed", float(self.speed))
            b.setUniform("u_alpha", float(self.alpha))
            b.setUniform("u_hue_speed", float(self.hue_speed))
            b.setUniform("u_saturation", float(self.saturation))
            b.setUniform("u_mode", 0.0 if rainbow else 1.0)
            b.setUniform("u_reflect", 1.0 if self.reflect else 0.0)
            b.setUniform("u_c0", list(pal[0]))
            b.setUniform("u_c1", list(pal[1]))
            b.setUniform("u_c2", list(pal[2]))
            b.setUniform("u_c3", list(pal[3]))
            b.setUniform("u_c4", list(pal[4]))

        _draw_lowres(
            self, canvas, w, h, builder, fw,
            res_scale=rs, bind=bind,
        )


class Nebuladust(BackgroundField):
    """Stardust density with a few nebula colour clusters.

    Same FBM dust as ``Stardust``, but three colours form medium-scale cloudy
    patches (not one tint per side of the screen, and not ``Chromadust``'s
    rotating rainbow).

    Args:
        color: First region color.
        color2: Second region color.
        color3: Third region color.
        amount: Density.
        speed: Own drift (default 0.2).
        alpha: Opacity, 0–1.
        res_scale: Render resolution as a fraction of the screen (1 = full; lower is
            cheaper).
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    _SURVIVAL_RES_SCALE = 0.4

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        color2=None,
        color3=None,
        amount: float = 1.0,
        speed: float = 0.2,
        alpha: float = 0.7,
        res_scale: float = 0.6,
        pan_response: float = 0.08,
        zoom_response: float = 0.1,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.55, 0.18, 0.72))
        self.color2 = resolve_rgb(color2, default=(0.12, 0.58, 0.78))
        self.color3 = resolve_rgb(color3, default=(0.82, 0.28, 0.42))
        self.amount = float(amount)
        self.speed = float(speed)
        self.alpha = float(alpha)
        self.res_scale = float(res_scale)
        self._lr_cache: Optional[tuple] = None
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        survival = fidelity_is_survival()
        rs = self._SURVIVAL_RES_SCALE if survival else self.res_scale
        builder = nebuladust_survival_builder if survival else nebuladust_builder

        def bind(b, lw, lh, sx, sy):
            _set_common_uvs(
                b, w=lw, h=lh, t=t,
                offset_xy=(ox * sx, oy * sy), scale=scale, rotation=rot,
            )
            b.setUniform("u_color", list(self.color))
            b.setUniform("u_color2", list(self.color2))
            b.setUniform("u_color3", list(self.color3))
            b.setUniform("u_amount", float(self.amount))
            b.setUniform("u_speed", float(self.speed))
            b.setUniform("u_alpha", float(self.alpha))

        _draw_lowres(
            self, canvas, w, h, builder, fw,
            res_scale=rs, bind=bind,
        )


class Borealis(BackgroundField):
    """Boreal ribbons (name avoids Recipe ``Aurora``).

    ``height`` (0–1) controls how far down from the top the ribbons reach.

    Args:
        color: Aurora color (default green).
        amount: Intensity.
        speed: Ripple speed (default 0.9).
        height: Reach from the top, 0–1 (default 0.65).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        amount: float = 1.0,
        speed: float = 0.9,
        height: float = 0.65,
        alpha: float = 0.85,
        pan_response: float = 0.1,
        zoom_response: float = 0.15,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.25, 0.95, 0.55))
        self.amount = float(amount)
        self.speed = float(speed)
        self.height = float(height)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = borealis_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_height", float(self.height))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Plasma(BackgroundField):
    """Tileable plasma wash. Zero-arg is a slow color field.

    Not recipe ``GearShell`` and not canvas post ``ColorWash``.

    Args:
        color: Plasma color.
        amount: Energy.
        speed: Animation speed (0 = still).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        amount: float = 1.0,
        speed: float = 0.0,
        alpha: float = 0.55,
        pan_response: float = 0.3,
        zoom_response: float = 0.4,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.55, 0.25, 0.85))
        self.amount = float(amount)
        self.speed = float(speed)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = plasma_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Mist(BackgroundField):
    """Soft atmosphere fog band. Zero-arg is a mild grey veil.

    Not post FX ``Haze`` and not a shape filter.

    Args:
        color: Mist color.
        amount: Density (default 0.7).
        band: Vertical band position.
        spread: How wide the band is.
        speed: Own drift (default 0.15).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        amount: float = 0.7,
        band: float = 0.4,
        spread: float = 0.35,
        speed: float = 0.15,
        alpha: float = 0.7,
        pan_response: float = 0.2,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.75, 0.8, 0.88))
        self.amount = float(amount)
        self.band = float(band)
        self.spread = float(spread)
        self.speed = float(speed)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = mist_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_band", float(self.band))
        b.setUniform("u_spread", float(self.spread))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Debris(BackgroundField):
    """Sparse scrap / wreckage flecks. Zero-arg is a light scatter.

    A full-screen field, not SpatialFx particles.

    Args:
        color: Debris color.
        density: How many (default 0.7).
        scale: Piece size.
        drift: Own drift (default 0.4).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        density: float = 0.7,
        scale: float = 1.0,
        drift: float = 0.4,
        alpha: float = 0.75,
        pan_response: float = 0.35,
        zoom_response: float = 0.15,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.65, 0.68, 0.75))
        self.density = float(density)
        self.scale = float(scale)
        self.drift = float(drift)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = debris_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_density", float(self.density))
        b.setUniform("u_scale_pat", float(self.scale))
        b.setUniform("u_drift", float(self.drift))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Embers(BackgroundField):
    """Rising ash / ember drift (ambient field; ≠ spatial Fire embers).

    Args:
        color: Ember color.
        density: How many (default 1.1).
        rise: Rise speed (default 0.8).
        alpha: Opacity, 0–1 (default 0.95).
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        density: float = 1.1,
        rise: float = 0.8,
        alpha: float = 0.95,
        pan_response: float = 0.4,
        zoom_response: float = 0.1,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(1.0, 0.45, 0.15))
        self.density = float(density)
        self.rise = float(rise)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = embers_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_density", float(self.density))
        b.setUniform("u_rise", float(self.rise))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class WindStreaks(BackgroundField):
    """Head-bright motion-trail streaks with cheap glow.

    ``angle`` is in **degrees** (0 = horizontal). Placement is intentionally
    irregular (not a regular grid of lines).

    Args:
        color: Streak color.
        density: How many (default 0.65).
        length: Streak length (default 1.4).
        angle: Direction in degrees (0 = horizontal).
        speed: Speed (default 1.3).
        glow: Halo (default 0.9).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        density: float = 0.65,
        length: float = 1.4,
        angle: float = 0.0,
        speed: float = 1.3,
        glow: float = 0.9,
        alpha: float = 0.8,
        pan_response: float = 0.85,
        zoom_response: float = 0.2,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.7, 0.85, 1.0))
        self.density = float(density)
        self.length = float(length)
        self.angle = float(angle)  # degrees
        self.speed = float(speed)
        self.glow = float(glow)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = windstreaks_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_density", float(self.density))
        b.setUniform("u_length", float(self.length))
        b.setUniform("u_angle", float(math.radians(self.angle)))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_glow", float(self.glow))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Ground(BackgroundField):
    """Orthographic ground strip — scene base for author art (not mode-7).

    Transparent above ``horizon`` (author y-up, 0–1 of screen height from the
    bottom — the visual horizon line). Pair with ``SkyGradient(..., horizon=…)``
    using the **same** ``horizon`` and ``fade``; also ``Clouds``. Put
    trees/buildings on parallax shape layers.

    Alpha ramps in across ``fade`` just below the horizon (default ~0.6% of the
    frame; ``fade=0`` is a 1 px cut). Vertical grade and grit use variations of
    ``color`` (lighter at the horizon, darker toward the bottom). Optional
    ``edge`` overrides the horizon tint. ``line`` scales grit strength;
    ``detail`` defaults to ``0`` (flat fill).

    Args:
        color: Ground color (darkens downward).
        edge: Horizon tint; ``None`` = a lighter ``color``.
        horizon: Horizon line, 0–1 from the bottom (default 0.42; match
            ``SkyGradient``).
        fade: Horizon blend (0 = 1 px cut).
        detail: Grain (0 = flat).
        line: Grain strength.
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        edge=None,
        horizon: float = 0.42,
        fade: float = HORIZON_FADE,
        detail: float = 0.0,
        line: float = 1.0,
        alpha: float = 1.0,
        pan_response: float = 0.9,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.22, 0.28, 0.16))
        self._edge_explicit = edge is not None
        self.edge = (
            resolve_rgb(edge, default=(0.35, 0.42, 0.24))
            if self._edge_explicit
            else self._edge_from_color(self.color)
        )
        self.horizon = float(horizon)
        self.fade = float(fade)
        self.detail = float(detail)
        self.line = float(line)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    @staticmethod
    def _edge_from_color(rgb):
        """Lighter horizon tint in the same hue as ``color``."""
        r, g, b = rgb
        return (
            min(1.0, r * 1.28 + 0.05),
            min(1.0, g * 1.25 + 0.04),
            min(1.0, b * 1.18 + 0.03),
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        edge = (
            list(self.edge)
            if self._edge_explicit
            else list(self._edge_from_color(self.color))
        )
        b = ground_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_edge", edge)
        b.setUniform("u_horizon", float(self.horizon))
        b.setUniform("u_fade", float(self.fade))
        b.setUniform("u_detail", float(self.detail))
        b.setUniform("u_line", float(self.line))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Lattice(BackgroundField):
    """Soft geometric lattice wash — mix-and-match ``fold`` × ``edge``.

    Closed catalog (invalid names raise). Omitted knobs use sensible defaults;
    continuous values are clamped. Authors never write SkSL. Transparent /
    stackable (no background fill).

    * ``spacing`` — pitch (distance between cell centers).
    * ``size`` — shape extent within each cell (centers stay put; ``1.0`` = reference; max ``1.7``).
    * ``layers`` — square/tri densify ×2 UV; hex places children on parent vertices.
    * ``layer_scale`` — child layer size (``1..2``; ``1`` = natural).

    Example::

        Lattice()
        Lattice(fold="square", edge="fill", color="red")
        Lattice(fold="hex", layers=3, size=1.0, layer_scale=1.5)
        Lattice(fold="tri", angle=15, layers=2)

    Args:
        fold: ``"square"`` · ``"hex"`` (default) · ``"tri"``.
        edge: ``"outline"`` (default) · ``"fill"``.
        color: Line color.
        spacing: Distance between cell centers.
        size: Shape size in each cell (max 1.7).
        line: Line thickness.
        layers: Nested copies, 1–3.
        layer_scale: Child layer size, 1–2.
        angle: Grid rotation in degrees.
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    _FOLDS = ("square", "hex", "tri")
    _EDGES = ("outline", "fill")
    _FOLD_ID = {"square": 0.0, "hex": 1.0, "tri": 2.0}
    _EDGE_ID = {"outline": 0.0, "fill": 1.0}

    def __init__(
        self,
        fold: str = "hex",
        *,
        edge: str = "outline",
        color: Optional[ColorLike] = None,
        spacing: float = 1.0,
        size: float = 1.0,
        line: float = 1.0,
        layers: int = 1,
        layer_scale: float = 1.0,
        angle: float = 0.0,
        alpha: float = 0.55,
        pan_response: float = 0.25,
        zoom_response: float = 0.35,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.45, 0.9, 0.8))
        self._fold = self._validate_fold(fold)
        self._edge = self._validate_edge(edge)
        self.spacing = float(spacing)
        self.size = size
        self.line = float(line)
        self.layers = layers
        self.layer_scale = layer_scale
        self.angle = float(angle)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    @classmethod
    def _validate_fold(cls, fold) -> str:
        return expect_choice(fold, cls._FOLDS, what="Lattice fold")

    @classmethod
    def _validate_edge(cls, edge) -> str:
        return expect_choice(edge, cls._EDGES, what="Lattice edge")

    @property
    def fold(self) -> str:
        """Cell shape: ``"square"`` · ``"hex"`` (default) · ``"tri"``. Writable."""
        return self._fold

    @fold.setter
    def fold(self, value) -> None:
        self._fold = self._validate_fold(value)

    @property
    def edge(self) -> str:
        """Draw each cell as ``"outline"`` (default) or ``"fill"``. Writable."""
        return self._edge

    @edge.setter
    def edge(self, value) -> None:
        self._edge = self._validate_edge(value)

    @property
    def layers(self) -> int:
        """Nested copies, 1 … 3 (square / tri densify; hex adds children on the vertices)."""
        return self._layers

    @layers.setter
    def layers(self, value) -> None:
        from .validate import as_payload
        raw = as_payload(value)
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise TypeError(f"Lattice layers expected a whole number 1 … 3, got {type(raw).__name__}")
        self._layers = max(1, min(3, raw))

    @property
    def size(self) -> float:
        """Shape size inside each cell (1 = reference, up to 1.7); cell centers stay put."""
        return self._size

    @size.setter
    def size(self, value) -> None:
        from .validate import number
        self._size = max(0.05, min(1.7, number(value, "Lattice size")))

    @property
    def layer_scale(self) -> float:
        """Size of each child layer relative to its parent, 1 … 2 (1 = natural)."""
        return self._layer_scale

    @layer_scale.setter
    def layer_scale(self, value) -> None:
        from .validate import number
        self._layer_scale = max(1.0, min(2.0, number(value, "Lattice layer_scale")))

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = lattice_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_fold", float(self._FOLD_ID[self._fold]))
        b.setUniform("u_edge", float(self._EDGE_ID[self._edge]))
        b.setUniform("u_spacing", float(self.spacing))
        b.setUniform("u_line", float(self.line))
        b.setUniform("u_layers", float(self._layers))
        b.setUniform("u_size", float(self._size))
        b.setUniform("u_layer_scale", float(self._layer_scale))
        b.setUniform("u_angle", float(math.radians(self.angle)))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Nebula(BackgroundField):
    """Broad coloured ribbon / dust bands (cheaper Stardust cousin).

    Zero-arg is a soft two-hue wash. Not Shield ``style="nebula"``.

    Args:
        color: First color.
        color2: Second color.
        scale: Pattern size.
        contrast: Band contrast.
        speed: Own drift (default 0.15).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        color2=None,
        scale: float = 1.0,
        contrast: float = 1.0,
        speed: float = 0.15,
        alpha: float = 0.55,
        pan_response: float = 0.06,
        zoom_response: float = 0.08,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.55, 0.2, 0.7))
        self.color2 = resolve_rgb(color2, default=(0.1, 0.45, 0.85))
        self.scale = float(scale)
        self.contrast = float(contrast)
        self.speed = float(speed)
        self.alpha = float(alpha)
        _field_boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )
        b = nebula_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_color2", list(self.color2))
        b.setUniform("u_scale_pat", float(self.scale))
        b.setUniform("u_contrast", float(self.contrast))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


class Floor(BackgroundField):
    """Mode7-style infinite ground / horizon (fake-3D drive surface).

    Soft anti-aliased grid + checker (reduced far-horizon flicker).

    Args:
        color: Floor color.
        sky: Color above the horizon.
        amount: Pattern contrast.
        speed: Flight speed.
        grid: Grid visibility (default 0.75).
        fog: Fog at the horizon (default 0.55).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        sky=None,
        amount: float = 1.0,
        speed: float = 1.0,
        grid: float = 0.75,
        fog: float = 0.55,
        alpha: float = 1.0,
        pan_response: float = 0.0,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.12, 0.55, 0.32))
        self.sky = resolve_rgb(sky, default=(0.05, 0.05, 0.15))
        self.amount = float(amount)
        self.speed = float(speed)
        self.grid = float(grid)
        self.fog = float(fog)
        self.alpha = float(alpha)
        self.pan_response = float(pan_response)
        self.zoom_response = float(zoom_response)
        self.rotation_response = float(rotation_response)
        self.enabled = bool(enabled)
        self._apply_scroll_arg(scroll)

    def _fx_cache_key(self) -> tuple:
        return (
            "floor",
            tuple(round(c, 3) for c in self.color),
            tuple(round(c, 3) for c in self.sky),
            round(self.speed, 3),
            round(self.grid, 3),
            round(self.fog, 3),
        )

    def draw(
        self,
        canvas: skia.Canvas,
        w: float,
        h: float,
        t: float,
        cam: CameraSample,
        *,
        design_width: float,
        design_height: float,
        fw=None,
    ) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam,
            design_width=design_width,
            design_height=design_height,
            fb_width=w,
            fb_height=h,
        )
        b = floor_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_sky", list(self.sky))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_grid", float(self.grid))
        b.setUniform("u_fog", float(self.fog))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)

class Road(BackgroundField):
    """Fake-3D Mode7 floor for side-scrollers — horizontal motion only.

    Vertical pan / vertical scroll do not move the horizon. Prefer ``scroll`` /
    camera pan on X (not a radial tunnel; stack with other background fields if needed).

    Args:
        color: Road color.
        sky: Color above the horizon.
        amount: Pattern contrast.
        speed: Flight speed.
        grid: Grid visibility (default 0.7).
        fog: Fog at the horizon (default 0.5).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        sky=None,
        amount: float = 1.0,
        speed: float = 1.0,
        grid: float = 0.7,
        fog: float = 0.5,
        alpha: float = 1.0,
        pan_response: float = 0.85,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.45, 0.35, 0.22))
        self.sky = resolve_rgb(sky, default=(0.12, 0.18, 0.32))
        self.amount = float(amount)
        self.speed = float(speed)
        self.grid = float(grid)
        self.fog = float(fog)
        self.alpha = float(alpha)
        self.pan_response = float(pan_response)
        self.zoom_response = float(zoom_response)
        self.rotation_response = float(rotation_response)
        self.enabled = bool(enabled)
        self._apply_scroll_arg(scroll)

    def _fx_cache_key(self) -> tuple:
        return (
            "road",
            tuple(round(c, 3) for c in self.color),
            tuple(round(c, 3) for c in self.sky),
            round(self.speed, 3),
            round(self.grid, 3),
            round(self.pan_response, 4),
        )

    def draw(
        self,
        canvas: skia.Canvas,
        w: float,
        h: float,
        t: float,
        cam: CameraSample,
        *,
        design_width: float,
        design_height: float,
        fw=None,
    ) -> None:
        ox, _oy, scale, rot = self._parallax_uv(
            cam=cam,
            design_width=design_width,
            design_height=design_height,
            fb_width=w,
            fb_height=h,
        )
        # Horizontal only: force oy = 0 even with a vertical scroll
        b = road_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, 0.0), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_sky", list(self.sky))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_grid", float(self.grid))
        b.setUniform("u_fog", float(self.fog))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)

class Tunnel(BackgroundField):
    """Fly-through star streaks into the screen (not the flat ``Stars`` field).

    Zero-arg is a mild into-screen field. Prefer ``canvas.set_fly(Tunnel())``.

    ``center`` is the vanishing point in design space (``None`` = screen
    center). ``pan_response`` (default 0) is an opt-in bank of that point,
    not wallpaper parallax. Prefer ``speed`` for immersion.

    Args:
        color: Streak color.
        amount: Brightness.
        speed: Flight speed.
        density: How many streaks.
        streak: Streak length.
        alpha: Opacity, 0–1.
        center: Vanishing point in design space; ``None`` = the screen center.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        amount: float = 1.0,
        speed: float = 1.0,
        density: float = 1.0,
        streak: float = 1.0,
        alpha: float = 1.0,
        center=None,
        pan_response: float = 0.0,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.85, 0.9, 1.0))
        self.amount = float(amount)
        self.speed = float(speed)
        self.density = float(density)
        self.streak = float(streak)
        self.alpha = float(alpha)
        self.center = center
        self.pan_response = float(pan_response)
        self.zoom_response = float(zoom_response)
        self.rotation_response = float(rotation_response)
        self.enabled = bool(enabled)
        self._apply_scroll_arg(scroll)

    def _fx_cache_key(self) -> tuple:
        return (
            "startunnel",
            tuple(round(c, 3) for c in self.color),
            round(self.speed, 3),
            round(self.density, 3),
            round(self.streak, 3),
        )

    def draw(
        self,
        canvas: skia.Canvas,
        w: float,
        h: float,
        t: float,
        cam: CameraSample,
        *,
        design_width: float,
        design_height: float,
        fw=None,
    ) -> None:
        ox, oy, scale, rot = _radial_fly_uv(
            self,
            cam=cam,
            design_width=design_width,
            design_height=design_height,
            fb_width=w,
            fb_height=h,
        )
        b = startunnel_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_density", float(self.density))
        b.setUniform("u_streak", float(self.streak))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)

class StarFly(BackgroundField):
    """Classic 3D point-star flythrough (≠ flat ``Stars`` / ≠ streak ``Tunnel``).

    Shared depth planes + ``(x,y)/z`` perspective (screensaver motion). Cheap ALU
    pin drawing (1× sin hash, d² falloff, 5 planes).

    ``center`` is the vanishing point in design space (``None`` = screen
    center). ``pan_response`` (default 0) is an opt-in bank of that point.

    Args:
        color: Star color.
        amount: Brightness.
        speed: Flight speed.
        density: How many stars.
        alpha: Opacity, 0–1.
        center: Vanishing point in design space; ``None`` = the screen center.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        amount: float = 1.0,
        speed: float = 1.0,
        density: float = 1.0,
        alpha: float = 1.0,
        center=None,
        pan_response: float = 0.0,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.9, 0.94, 1.0))
        self.amount = float(amount)
        self.speed = float(speed)
        self.density = float(density)
        self.alpha = float(alpha)
        self.center = center
        self.pan_response = float(pan_response)
        self.zoom_response = float(zoom_response)
        self.rotation_response = float(rotation_response)
        self.enabled = bool(enabled)
        self._apply_scroll_arg(scroll)

    def _fx_cache_key(self) -> tuple:
        return (
            "starfield",
            tuple(round(c, 3) for c in self.color),
            round(self.speed, 3),
            round(self.density, 3),
        )

    def draw(
        self,
        canvas: skia.Canvas,
        w: float,
        h: float,
        t: float,
        cam: CameraSample,
        *,
        design_width: float,
        design_height: float,
        fw=None,
    ) -> None:
        ox, oy, scale, rot = _radial_fly_uv(
            self,
            cam=cam,
            design_width=design_width,
            design_height=design_height,
            fb_width=w,
            fb_height=h,
        )
        b = starfield_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_density", float(self.density))
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)

class PlanetFly(BackgroundField):
    """Curved-horizon planet surface flyover.

    ``roll`` selects motion (default **into-screen**, former PlanetFly2):

    * ``"into"`` / ``"forward"`` — ground rushes horizon → camera (ship into display)
    * ``"side"`` / ``"lateral"`` — surface rolls R→L (side-scroller)

    ``color`` / ``bright`` control land tint and visibility.

    Args:
        color: Ground color.
        space: Color above the horizon.
        amount: Relief contrast.
        bright: Ground visibility (default 1.15).
        speed: Flight speed.
        relief: Relief (default 0.9).
        fog: Horizon fog (default 0.45).
        size: Planet scale in the frame (default 0.55).
        roll: ``"into"`` (default, fly in) or ``"side"`` (roll right to left).
        alpha: Opacity, 0–1.
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        space=None,
        amount: float = 1.0,
        bright: float = 1.15,
        speed: float = 1.0,
        relief: float = 0.9,
        fog: float = 0.45,
        size: float = 0.55,
        roll: str = "into",
        alpha: float = 1.0,
        pan_response: float = 0.0,
        zoom_response: float = 0.0,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.42, 0.48, 0.32))
        self.space = resolve_rgb(space, default=(0.01, 0.015, 0.04))
        self.amount = float(amount)
        self.bright = float(bright)
        self.speed = float(speed)
        self.relief = float(relief)
        self.fog = float(fog)
        self.size = float(size)
        self.roll = str(roll or "into").strip().lower()
        self.alpha = float(alpha)
        self.pan_response = float(pan_response)
        self.zoom_response = float(zoom_response)
        self.rotation_response = float(rotation_response)
        self.enabled = bool(enabled)
        self._apply_scroll_arg(scroll)

    def _roll_into(self) -> bool:
        r = self.roll
        if r in ("side", "lateral", "x", "horizontal"):
            return False
        return True  # into / forward / default

    def _fx_cache_key(self) -> tuple:
        return (
            "planetfly",
            tuple(round(c, 3) for c in self.color),
            tuple(round(c, 3) for c in self.space),
            round(self.bright, 3),
            round(self.speed, 3),
            round(self.relief, 3),
            round(self.size, 3),
            round(self.fog, 3),
            self.roll,
        )

    def draw(
        self,
        canvas: skia.Canvas,
        w: float,
        h: float,
        t: float,
        cam: CameraSample,
        *,
        design_width: float,
        design_height: float,
        fw=None,
    ) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam,
            design_width=design_width,
            design_height=design_height,
            fb_width=w,
            fb_height=h,
        )
        b = planetfly_builder
        _set_common_uvs(b, w=w, h=h, t=t, offset_xy=(ox, oy), scale=scale, rotation=rot)
        b.setUniform("u_color", list(self.color))
        b.setUniform("u_space", list(self.space))
        b.setUniform("u_amount", float(self.amount))
        b.setUniform("u_speed", float(self.speed))
        b.setUniform("u_relief", float(self.relief))
        b.setUniform("u_fog", float(self.fog))
        b.setUniform("u_size", float(self.size))
        b.setUniform("u_bright", float(self.bright))
        b.setUniform("u_roll", 1.0 if self._roll_into() else 0.0)
        b.setUniform("u_alpha", float(self.alpha))
        draw_shader_rect(canvas, w, h, b)


def _boilerplate(self, *, pan_response, zoom_response, rotation_response, scroll, enabled):
    self.pan_response = float(pan_response)
    self.zoom_response = float(zoom_response)
    self.rotation_response = float(rotation_response)
    self.enabled = bool(enabled)
    self._apply_scroll_arg(scroll)


def _uvs(builder, *, w, h, t, offset_xy, scale, rotation):
    """Shared uniforms. ``rotation`` is camera-matching CCW+ radians."""
    builder.setUniform("resolution", [float(w), float(h)])
    builder.setUniform("time", float(t))
    builder.setUniform("u_offset", [float(offset_xy[0]), float(offset_xy[1])])
    builder.setUniform("u_scale", float(scale))
    builder.setUniform("u_rotation", float(rotation))


def _make_rt(fw, w: int, h: int):
    info = skia.ImageInfo.Make(
        w, h, skia.ColorType.kRGBA_8888_ColorType, skia.kPremul_AlphaType,
        skia.ColorSpace.MakeSRGB(),
    )
    ctx = getattr(fw, "_context", None) if fw is not None else None
    surf = (
        skia.Surface.MakeRenderTarget(ctx, skia.Budgeted.kYes, info)
        if ctx is not None else None
    )
    if surf is None:
        surf = skia.Surface.MakeRaster(info)
    return surf


def _draw_lowres(
    field,
    canvas,
    w: float,
    h: float,
    builder,
    fw,
    *,
    res_scale: float,
    bind,
) -> None:
    """Render shader at ``res_scale`` then bilinear-upscale to full frame."""
    rs = max(0.15, min(1.0, float(res_scale)))
    lw = max(8, int(round(float(w) * rs)))
    lh = max(8, int(round(float(h) * rs)))
    key = (lw, lh)
    cache = getattr(field, "_lr_cache", None)
    if cache is None or cache[0] != key:
        surf = _make_rt(fw, lw, lh)
        field._lr_cache = (key, surf)
    else:
        surf = cache[1]
    sc = surf.getCanvas()
    sc.clear(skia.Color(0, 0, 0, 0))
    sx = float(lw) / max(float(w), 1.0)
    sy = float(lh) / max(float(h), 1.0)
    bind(builder, lw, lh, sx, sy)
    draw_shader_rect(sc, float(lw), float(lh), builder)
    img = surf.makeImageSnapshot()
    canvas.save()
    canvas.scale(float(w) / float(lw), float(h) / float(lh))
    paint = skia.Paint(AntiAlias=False)
    paint.setBlendMode(skia.BlendMode.kSrcOver)
    canvas.drawImage(
        img, 0, 0,
        skia.SamplingOptions(skia.FilterMode.kLinear),
        paint,
    )
    canvas.restore()


class ChurningClouds(BackgroundField):
    """Domain-warped space clouds that churn in place (warp phase + breathe).

    Drawn on a reduced-resolution plate (``res_scale``, default 0.4) with a
    2-octave FBM shader — soft cloud looks tolerate the upsample well.

    Args:
        color: First color.
        color2: Second color.
        amount: Density.
        speed: Churn speed (default 0.4).
        scale: Pattern size.
        contrast: Contrast of the pattern.
        alpha: Opacity, 0–1.
        seed: Noise seed; the same seed gives the same pattern.
        res_scale: Render resolution as a fraction of the screen (1 = full; lower is
            cheaper).
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        color2: Optional[ColorLike] = None,
        amount: float = 1.0,
        speed: float = 0.4,
        scale: float = 1.0,
        contrast: float = 1.0,
        alpha: float = 0.6,
        seed: float = 0.0,
        res_scale: float = 0.4,
        pan_response: float = 0.06,
        zoom_response: float = 0.08,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.35, 0.55, 0.95))
        self.color2 = resolve_rgb(color2, default=(0.85, 0.35, 0.55))
        self.amount = float(amount)
        self.speed = float(speed)
        self.scale = float(scale)
        self.contrast = float(contrast)
        self.alpha = float(alpha)
        self.seed = float(seed)
        self.res_scale = float(res_scale)
        self._lr_cache: Optional[tuple] = None
        _boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )

        def bind(b, lw, lh, sx, sy):
            _uvs(
                b, w=lw, h=lh, t=t,
                offset_xy=(ox * sx, oy * sy), scale=scale, rotation=rot,
            )
            b.setUniform("u_color", list(self.color))
            b.setUniform("u_color2", list(self.color2))
            b.setUniform("u_amount", float(self.amount))
            b.setUniform("u_speed", float(self.speed))
            b.setUniform("u_scale_pat", float(self.scale))
            b.setUniform("u_contrast", float(self.contrast))
            b.setUniform("u_alpha", float(self.alpha))
            b.setUniform("u_seed", float(self.seed))

        _draw_lowres(
            self, canvas, w, h, churningclouds_builder, fw,
            res_scale=self.res_scale, bind=bind,
        )


class FilamentField(BackgroundField):
    """Ridged ambient filaments with slow drift and occasional hotspot surges.

    Drawn on a reduced-resolution plate (``res_scale``, default 0.5) with a
    2-octave ridged-noise shader.

    Args:
        color: Filament color.
        amount: Density.
        speed: Own drift (default 0.35).
        contrast: Contrast of the pattern.
        alpha: Opacity, 0–1.
        seed: Noise seed; the same seed gives the same pattern.
        res_scale: Render resolution as a fraction of the screen (1 = full; lower is
            cheaper).
        pan_response: How much the field follows camera pan: 0 = glued to the screen, 1
            = moves with the world.
        zoom_response: How much camera zoom scales the pattern (0 = not at all).
        rotation_response: Fraction of the camera rotation the field follows.
        scroll: Own drift ``(vx, vy)`` in design units per second (y-up).
        enabled: Draw it (``True``) or hide it without taking it off the stack.
    """

    def __init__(
        self,
        color: Optional[ColorLike] = None,
        *,
        amount: float = 1.0,
        speed: float = 0.35,
        contrast: float = 1.0,
        alpha: float = 0.55,
        seed: float = 0.0,
        res_scale: float = 0.5,
        pan_response: float = 0.18,
        zoom_response: float = 0.08,
        rotation_response: float = 0.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
        enabled: bool = True,
    ):
        self.color = resolve_rgb(color, default=(0.4, 0.75, 1.0))
        self.amount = float(amount)
        self.speed = float(speed)
        self.contrast = float(contrast)
        self.alpha = float(alpha)
        self.seed = float(seed)
        self.res_scale = float(res_scale)
        self._lr_cache: Optional[tuple] = None
        _boilerplate(
            self, pan_response=pan_response, zoom_response=zoom_response,
            rotation_response=rotation_response, scroll=scroll, enabled=enabled,
        )

    def draw(self, canvas, w, h, t, cam, *, design_width, design_height, fw=None) -> None:
        ox, oy, scale, rot = self._parallax_uv(
            cam=cam, design_width=design_width, design_height=design_height,
            fb_width=w, fb_height=h,
        )

        def bind(b, lw, lh, sx, sy):
            _uvs(
                b, w=lw, h=lh, t=t,
                offset_xy=(ox * sx, oy * sy), scale=scale, rotation=rot,
            )
            b.setUniform("u_color", list(self.color))
            b.setUniform("u_amount", float(self.amount))
            b.setUniform("u_speed", float(self.speed))
            b.setUniform("u_contrast", float(self.contrast))
            b.setUniform("u_alpha", float(self.alpha))
            b.setUniform("u_seed", float(self.seed))

        _draw_lowres(
            self, canvas, w, h, filamentfield_builder, fw,
            res_scale=self.res_scale, bind=bind,
        )



__all__ = [
    "Wallpaper",
    "SkyGradient",
    "sky_palette",
    "Clouds",
    "Stars",
    "Stardust",
    "Chromadust",
    "Nebuladust",
    "Borealis",
    "Plasma",
    "Mist",
    "Debris",
    "Embers",
    "WindStreaks",
    "Ground",
    "Lattice",
    "Nebula",
    "Floor",
    "Road",
    "Tunnel",
    "StarFly",
    "PlanetFly",
    "ChurningClouds",
    "FilamentField",
]
