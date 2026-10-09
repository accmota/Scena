"""
Pre-scene background fields (solid/gradient/image wallpaper + procedural FX).

``canvas.background`` is a :class:`BackgroundStack`: an always-present ``base``
field plus an ordered stack of extra full-screen fields drawn before the camera
transform + scene. Independent of ``canvas.layers`` and ``canvas.effects``.

Empty extra stack costs nothing beyond the base field draw (solid clear when
the base is a plain color).
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import skia

from .closed import ClosedSurface


@dataclass(frozen=True)
class CameraSample:
    """Per-frame snapshot of camera state used by background parallax math.

    ``rest_x`` / ``rest_y`` are the composition look-at (where the author
    framed the scene: design center after default / ``set_origin('corner')``,
    world origin after ``set_origin('center')``). Parallax offsets are always
    relative to that rest so raising ``pan_response`` never shifts the field at
    identity view.
    """

    pan_x: float
    pan_y: float
    zoom: float
    rotation: float  # degrees
    rest_x: float = 0.0
    rest_y: float = 0.0


def parallax_transform(
    *,
    pan_x: float,
    pan_y: float,
    zoom: float,
    rotation_deg: float,
    design_width: float,
    design_height: float,
    fb_width: float,
    fb_height: float,
    pan_response: float,
    zoom_response: float,
    rotation_response: float = 0.0,
    rest_x: Optional[float] = None,
    rest_y: Optional[float] = None,
) -> Tuple[float, float, float, float]:
    """Return ``(offset_x, offset_y, scale, rotation_rad)`` for UV sampling.

    Shaders sample with ``uv ~ (coord - u_offset) / resolution / u_scale`` so a
    positive ``offset`` shifts the painted pattern in the **same** direction
    as ``+offset`` on the framebuffer (y-down).

    Offsets use **look delta from the camera rest look** (not absolute design
    center). Rest defaults to design center when omitted. That keeps authored
    placement (sun position, plasma framing) stable when only ``pan_response``
    changes, including after ``set_origin('center')``.

    Camera: when look-at increases, stage content on screen moves **opposite**
    (``screen ∝ zoom * (world − look)``). For ``pan_response=1`` the background must
    scroll the same way as shapes:

    * ``offset_x = −(look_x − rest_x) · zoom · (fb_w / design_w) · pan_response``
    * ``offset_y = +(look_y − rest_y) · zoom · (fb_h / design_h) · pan_response``
      (sign flips for y-up design → y-down FB)

    * ``pan_response=0`` — screen-locked; zero offset.
    * ``pan_response=1`` — tracks pan/zoom with world content.
    * ``zoom_response`` only sets pattern frequency scale
      (``1 + (zoom−1)·zoom_response``), not pan amplification.

    ``rotation_rad`` is camera-matching, CCW+ (same sense as
    ``partial_camera_matrix`` / world content). SkSL ``u_rotation`` takes it
    as-is. Skia ``canvas.rotate`` is CW+ in y-down identity CTM — Wallpaper
    negates at the CTM site.
    """
    dw = max(float(design_width), 1e-6)
    dh = max(float(design_height), 1e-6)
    fw = float(fb_width)
    fh = float(fb_height)
    p = float(pan_response)
    zr = float(zoom_response)
    rr = float(rotation_response)
    z = max(float(zoom), 1e-6)
    rx = dw * 0.5 if rest_x is None else float(rest_x)
    ry = dh * 0.5 if rest_y is None else float(rest_y)

    device_per_design_x = fw / dw
    device_per_design_y = fh / dh
    # Δlook from composition rest × zoom → same on-screen pixel delta as shapes.
    # Negate X so offset scroll matches content (look ↑ → content left → offset < 0).
    # Y: design y-up vs FB y-down; look ↑ moves content down on FB → offset_y > 0.
    dx = float(pan_x) - rx
    dy = float(pan_y) - ry
    offset_x = -dx * z * p * device_per_design_x
    offset_y = dy * z * p * device_per_design_y
    scale = 1.0 + (z - 1.0) * zr
    if scale < 1e-4:
        scale = 1e-4
    rot_rad = float(rotation_deg) * rr * (3.141592653589793 / 180.0)
    return (offset_x, offset_y, scale, rot_rad)


def vanishing_point_offset(
    *,
    center_x: float,
    center_y: float,
    rest_x: float,
    rest_y: float,
    design_width: float,
    design_height: float,
    fb_width: float,
    fb_height: float,
) -> Tuple[float, float]:
    """FB pixel offset from screen center for a design-space vanishing point.

    Pre-scene fly fields (``Tunnel``, ``StarFly``) draw in identity CTM.
    ``center`` is authored framing, not camera-projected: pan / zoom do not
    move this offset. Add ``parallax_transform`` (``pan_response``) on top
    to bank the point with look. Y-up design → y-down framebuffer.
    """
    dw = max(float(design_width), 1e-6)
    dh = max(float(design_height), 1e-6)
    ox = (float(center_x) - float(rest_x)) * (float(fb_width) / dw)
    oy = -(float(center_y) - float(rest_y)) * (float(fb_height) / dh)
    return (ox, oy)


def _auto_place_background(field) -> None:
    """Attach ``field`` to ``canvas.background`` by class ``_place`` slot."""
    from .place import is_unplaced_creation

    if is_unplaced_creation():
        return
    try:
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        stack = fw.background_stack
    except Exception:
        return
    slot = getattr(type(field), "_place", "extra")
    if slot == "base":
        if field in stack._items:
            stack._items.remove(field)
        stack._base = field
        return
    if stack._base is field:
        return
    stack.add(field)


class BackgroundField(ClosedSurface):
    """Base class for a pre-scene full-screen field.

    Gradual params: constructing with no subclass-specific args produces a
    sensible look. Camera-response knobs default for the visual family
    (far sky vs mid field vs tunnel).

    Construction places the field: ``_place = "base"`` (wallpaper family)
    replaces ``canvas.background.base``; extras append in construction
    order. Use :meth:`temp` or :func:`~scena.place.unplaced_creation` to skip.
    :meth:`remove` detaches an extra (not base).

    ``scroll`` (design units/sec, y-up) moves the field independently of the
    camera — Space Invaders-style rolling stars with a fixed look-at.
    Orthogonal to ``pan_response`` (camera) and kind ``speed`` (intrinsic animation).
    """

    _place = "extra"
    enabled: bool = True
    pan_response: float = 0.0
    zoom_response: float = 0.0
    rotation_response: float = 0.0

    def __init__(self):
        _auto_place_background(self)

    def __init_subclass__(cls, **kwargs):
        if "__init__" in cls.__dict__:
            from .place import wrap_init_autoplace
            wrap_init_autoplace(cls, _auto_place_background)
        # Last: ClosedSurface seals outside the construct-to-place wrapper.
        super().__init_subclass__(**kwargs)

    @classmethod
    def temp(cls, *args, **kwargs):
        """Construct without attaching to ``canvas.background``."""
        from .place import temp_construct
        return temp_construct(cls, *args, **kwargs)

    def remove(self) -> None:
        """Detach from ``canvas.background`` extras. Idempotent if not placed.

        Wallpaper ``base`` cannot be removed this way — replace it or call
        :meth:`~BackgroundStack.reset_base`.
        """
        try:
            from .orchestration import ScenaFramework
            stack = ScenaFramework.get_instance().background_stack
        except Exception:
            return
        if stack.base is self:
            raise TypeError(
                "wallpaper base cannot be removed; replace it or reset_base()"
            )
        stack.remove(self)

    def _fx_cache_key(self) -> tuple:
        return (type(self).__name__,)

    def _is_active(self) -> bool:
        return bool(self.enabled)

    # --- author scroll (planar rate; applied on all kinds via UV offset) ----

    def _apply_scroll_arg(self, scroll=None) -> None:
        """Apply constructor ``scroll=`` (``None`` or omitted → ``(0, 0)``)."""
        self.scroll = scroll if scroll is not None else (0.0, 0.0)

    def _ensure_scroll_state(self) -> None:
        if not hasattr(self, "_scroll"):
            self._scroll = (0.0, 0.0)
        if not hasattr(self, "_scroll_accum"):
            self._scroll_accum = [0.0, 0.0]
        if not hasattr(self, "_scroll_last_t"):
            # Scroll counts from the field's birth (W-T7 / W-T8).
            try:
                from .process import _now
                self._scroll_last_t = _now()
            except Exception:
                self._scroll_last_t = None

    @property
    def scroll(self) -> Tuple[float, float]:
        """Author scroll rate in **design units per second** (y-up).

        Independent of camera. ``(0, -40)`` rolls the field “down” on screen
        like continuous ``pan_by`` of content without moving the look-at.
        """
        self._ensure_scroll_state()
        return (float(self._scroll[0]), float(self._scroll[1]))

    @scroll.setter
    def scroll(self, value) -> None:
        self._ensure_scroll_state()
        if value is None:
            self._scroll = (0.0, 0.0)
            return
        from .validate import scroll_rate
        self._scroll = scroll_rate(value, "scroll")

    def _advance_scroll(self, t: float) -> None:
        """Integrate ``scroll`` over world time, once per frame from the frame
        body (``BackgroundStack.advance_scroll``), enabled or not: scroll is
        world state like layer scroll (review 2026-10-09 W-T8; it ran in the
        draw, only while the field was drawn, and skipped gaps over 1.5 s)."""
        self._ensure_scroll_state()
        t = float(t)
        if not math.isfinite(t):
            return
        last = self._scroll_last_t
        if last is None:
            self._scroll_last_t = t
            return
        dt = t - float(last)
        self._scroll_last_t = t
        if dt <= 0.0:
            return
        sx, sy = self._scroll
        self._scroll_accum[0] += float(sx) * dt
        self._scroll_accum[1] += float(sy) * dt

    def _reset_scroll(self) -> None:
        """Zero accumulated scroll offset (rate knobs unchanged)."""
        self._ensure_scroll_state()
        self._scroll_accum = [0.0, 0.0]

    def _scroll_device_offset(
        self,
        *,
        zoom: float,
        design_width: float,
        design_height: float,
        fb_width: float,
        fb_height: float,
    ) -> Tuple[float, float]:
        """Map accumulated design scroll to FB pixel offset (y-up → y-down)."""
        self._ensure_scroll_state()
        dw = max(float(design_width), 1e-6)
        dh = max(float(design_height), 1e-6)
        z = max(float(zoom), 1e-6)
        ax = float(self._scroll_accum[0])
        ay = float(self._scroll_accum[1])
        # Same content direction as pan_by: +design X → +FB X; +design Y → −FB Y.
        ox = ax * z * (float(fb_width) / dw)
        oy = -ay * z * (float(fb_height) / dh)
        return (ox, oy)

    def _parallax_uv(
        self,
        *,
        cam: CameraSample,
        design_width: float,
        design_height: float,
        fb_width: float,
        fb_height: float,
    ) -> Tuple[float, float, float, float]:
        """Camera parallax + author ``scroll`` UV offset for this field."""
        ox, oy, scale, rot = parallax_transform(
            pan_x=cam.pan_x,
            pan_y=cam.pan_y,
            zoom=cam.zoom,
            rotation_deg=cam.rotation,
            design_width=design_width,
            design_height=design_height,
            fb_width=fb_width,
            fb_height=fb_height,
            pan_response=self.pan_response,
            zoom_response=self.zoom_response,
            rotation_response=self.rotation_response,
            rest_x=cam.rest_x,
            rest_y=cam.rest_y,
        )
        sx, sy = self._scroll_device_offset(
            zoom=cam.zoom,
            design_width=design_width,
            design_height=design_height,
            fb_width=fb_width,
            fb_height=fb_height,
        )
        return (ox + sx, oy + sy, scale, rot)

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
        """Subclass hook: full-screen paint into identity-CTM ``canvas``."""
        raise NotImplementedError


def _default_base_field() -> BackgroundField:
    from .background_kinds import Wallpaper
    from .color import Color
    from .place import unplaced_creation
    with unplaced_creation():
        return Wallpaper(Color(0.0, 0.0, 0.0, 1.0))


def looks_like_image_path(value) -> bool:
    """True when ``value`` is a filename string, not a color name.

    A string with ``.``, ``/``, or ``\\`` is a file
    (``"bg1.jpg"``, ``"media/sky.png"``). Color names have neither
    (``"navy"``, ``"sky blue"``).
    """
    if not isinstance(value, str):
        return False
    return any(ch in value for ch in "./\\")


def coerce_wallpaper_source(value, *, what: str = "Wallpaper source"):
    """Accept a wallpaper paint material or ColorLike; reject other families.

    ``Color`` / ``Gradient`` / ``Texture`` / internal image payload,
    a color name / RGB(A) tuple, a filename string, or a ``skia.Image``.
    Looks, filters, SpatialFx, post effects, and background fields raise
    ``TypeError``.
    """
    from .color import Color
    from .style import Gradient, BackgroundImage, Texture
    from .validate import family_hint
    import skia

    if isinstance(value, (Color, Gradient, BackgroundImage, Texture)):
        return value
    if isinstance(value, skia.Image) or looks_like_image_path(value):
        return BackgroundImage(value)
    if isinstance(value, str) or (
        isinstance(value, (tuple, list)) and len(value) >= 3
    ):
        return Color(value)
    hint = family_hint(value)
    msg = (
        f"{what} expected Color, Gradient, Texture, an image file, "
        f"or a color name/tuple, got {type(value).__name__}"
    )
    if hint:
        msg = f"{msg}. {hint}"
    raise TypeError(msg)


def wrap_background_source(
    value,
    *,
    pan_response: float = 0.0,
    zoom_response: float = 0.0,
    rotation_response: float = 0.0,
    scroll=None,
) -> BackgroundField:
    """Coerce a paint source or existing field into a :class:`BackgroundField`.

    * Existing :class:`BackgroundField` — returned as-is (camera kwargs ignored).
    * ``Color`` / ``Gradient`` / ``Texture`` / image file / ``skia.Image`` —
      wrapped in :class:`~scena.background_kinds.Wallpaper` with the given
      camera knobs.
    * Color names / RGB tuples — wrapped as solid ``Color`` Wallpaper.
    * Looks, filters, SpatialFx, post effects — ``TypeError`` (wrong family).
    """
    if isinstance(value, BackgroundField):
        ignored = (
            float(pan_response) != 0.0
            or float(zoom_response) != 0.0
            or float(rotation_response) != 0.0
            or scroll is not None
        )
        if ignored:
            warnings.warn(
                "camera knobs on an existing background field are ignored; "
                "set pan_response, zoom_response, rotation_response, or scroll "
                "on the field itself",
                RuntimeWarning,
                stacklevel=2,
            )
        return value
    from .background_kinds import Wallpaper

    source = coerce_wallpaper_source(value, what="canvas.background")
    from .place import unplaced_creation
    with unplaced_creation():
        return Wallpaper(
            source,
            pan_response=pan_response,
            zoom_response=zoom_response,
            rotation_response=rotation_response,
            scroll=scroll if scroll is not None else (0.0, 0.0),
        )


class BackgroundStack(ClosedSurface):
    """``canvas.background``: always-present ``base`` + ordered extra fields."""

    _closed_who = "canvas.background"

    def _advance_scroll_all(self, t: float) -> None:
        """Frame body: every field's scroll, the base's too, enabled or not."""
        base = self._base
        if base is not None:
            base._advance_scroll(t)
        for b in self._items:
            b._advance_scroll(t)

    def __init__(self) -> None:
        self._items: List[BackgroundField] = []
        self._base: BackgroundField = _default_base_field()
        self.enabled: bool = True

    # --- base ----------------------------------------------------------------

    @property
    def base(self) -> BackgroundField:
        """The always-present bottom field (never removed by ``clear()``)."""
        return self._base

    @base.setter
    def base(self, value) -> None:
        field = wrap_background_source(value)
        if field in self._items:
            self._items.remove(field)
        self._base = field

    def reset_base(self) -> None:
        """Restore ``base`` to the default solid black wallpaper."""
        self._base = _default_base_field()

    # --- author API (extra stack only) ---------------------------------------

    def add(self, field: BackgroundField) -> BackgroundField:
        """Stack a background field on top of the base (``canvas.background.add(Stars())``). Returns the field."""
        if not isinstance(field, BackgroundField):
            field = wrap_background_source(field)
        if self._base is field:
            return field
        if field not in self._items:
            self._items.append(field)
        return field

    def remove(self, field: BackgroundField) -> None:
        """Take a field off the stack (no-op if absent). The base stays."""
        if field in self._items:
            self._items.remove(field)

    def clear(self) -> None:
        """Empty the extra stack only — ``base`` is untouched."""
        self._items.clear()

    def set_fly(self, field: Optional[BackgroundField] = None) -> Optional[BackgroundField]:
        """Replace the extra stack with a single fly field (or clear).

        The common "just one immersive field" path. Pass ``None`` to clear.
        Does not touch ``base``.
        """
        self.clear()
        if field is None:
            return None
        return self.add(field)

    def __iter__(self) -> Iterable[BackgroundField]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        # Stack object is always truthy as a facade (base always exists).
        return True

    @property
    def _is_active(self) -> bool:
        """True when any extra field is active (base is always drawn)."""
        if not self.enabled:
            return False
        return any(b._is_active() for b in self._items)

    def items(self) -> Sequence[BackgroundField]:
        """The stacked fields, bottom to top, as a tuple (the base not included)."""
        return tuple(self._items)

    # --- render ------------------------------------------------------------

    def _render(
        self,
        skia_canvas: skia.Canvas,
        w: float,
        h: float,
        t: float,
        cam: CameraSample,
        *,
        design_width: float,
        design_height: float,
        fw=None,
        inspector_zoom=None,
        origin=(0.0, 0.0),
    ) -> None:
        """Draw ``base`` then active extra fields bottom→top (identity CTM).

        ``inspector_zoom``: when set (debug zoom active), scale wallpaper about
        the surface center after reset so it letterboxes with the inspector view.
        When ``None`` (normal play), the path is unchanged.
        ``origin``: framebuffer offset of the design rectangle (letterbox pads).
        """
        skia_canvas.save()
        skia_canvas.resetMatrix()
        try:
            t = float(t)
            w = float(w)
            h = float(h)
            ox, oy = float(origin[0]), float(origin[1])
            if ox or oy:
                skia_canvas.translate(ox, oy)
                skia_canvas.clipRect(skia.Rect.MakeWH(w, h))
            if inspector_zoom is not None:
                z = float(inspector_zoom)
                if z != 1.0:
                    cx, cy = w * 0.5, h * 0.5
                    skia_canvas.translate(cx, cy)
                    skia_canvas.scale(z, z)
                    skia_canvas.translate(-cx, -cy)
            dw = float(design_width)
            dh = float(design_height)
            base = self._base
            if base is not None and base._is_active():
                base.draw(
                    skia_canvas, w, h, t, cam,
                    design_width=dw, design_height=dh, fw=fw,
                )
            if not self.enabled:
                return
            for b in self._items:
                if not b._is_active():
                    continue
                b.draw(
                    skia_canvas, w, h, t, cam,
                    design_width=dw, design_height=dh, fw=fw,
                )
        finally:
            skia_canvas.restore()


__all__ = [
    "CameraSample",
    "BackgroundField",
    "BackgroundStack",
    "parallax_transform",
    "vanishing_point_offset",
    "wrap_background_source",
    "coerce_wallpaper_source",
    "looks_like_image_path",
]
