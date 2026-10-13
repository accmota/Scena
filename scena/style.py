import warnings
from typing import Any, Optional, Union, Tuple, overload, List, TYPE_CHECKING
from enum import Enum
import copy
import skia
import os
import numpy as np
import math

from ._pkg import is_framework_module
from .closed import ClosedSurface, check_closed_write, seal_after_init
from ._defaults import Unset
from .color import Color, ColorLike, ColorNames, resolve_rgb
from .state import as_payload, as_payload_all, probe_private
from .validate import coerce_enum, expect_choice, magnitude, fixed_magnitude

if TYPE_CHECKING:
    from .visuals import Visual

"""
Paint channels (internal) and paint materials (Gradient, Texture, …).

``PaintState`` is the internal mixin on Shape: fill/line materials, stroke
params, blend, filters, Skia paint cache, and the ``.visual`` handle.
Authors use shape properties (``.fill``, ``.visual``, …) — not this module's
class name.
"""

# Prototype stroke width for new Shapes (Text / transients keep their own).
DEFAULT_LINE_WIDTH = 1.5


_RECOLOR_HIDDEN_WARNED: set = set()


def _warn_recolor_hidden(visual) -> None:
    """``set_color`` under a Role D look (Flame, Swell, Water, flat Shield).

    The look paints its own colors, so the new color is stored in the identity
    snapshot but does not show until ``visual = None``. Warn once per look
    class: recoloring a group that holds a few flames must not flood stderr.
    """
    name = type(visual).__name__
    if name in _RECOLOR_HIDDEN_WARNED:
        return
    _RECOLOR_HIDDEN_WARNED.add(name)
    warnings.warn(
        f"{name} paints its own colors, so set_color does not show while it is "
        f"the visual. The color is kept and shows after shape.visual = None.",
        RuntimeWarning, stacklevel=3,
    )


class LineCapStyle(Enum):
    ROUND = "round"     
    SQUARE = "square"
    PROJECT = "project"

class LineJoinStyle(Enum):
    MITER = "miter"     
    BEVEL = "bevel"
    ROUND = "round"

class DashStyle(Enum):
    SOLID = "solid"
    DASH = "dash"
    DOT = "dot"
    DOT_DASH = "dot-dash"

class GradientType(Enum):
    LINEAR = "linear"
    RADIAL = "radial"
    SWEEP = "sweep"

class TileMode(Enum):
    CLAMP = "clamp"
    REPEAT = "repeat"
    MIRROR = "mirror"
    DECAL = "decal"


class BackgroundFit(Enum):
    """How an image maps to a framebuffer or a shape's local AABB."""
    COVER = "cover"      # scale uniformly to cover; crop overflow
    CONTAIN = "contain"  # scale uniformly to fit; letterbox
    STRETCH = "stretch"  # non-uniform scale to fill
    TILE = "tile"        # repeat; cell = tile_size design units (see tile_mode)

# Map our enums to Skia constants
_SKIA_CAP_MAP = {
    LineCapStyle.ROUND: skia.Paint.Cap.kRound_Cap,
    LineCapStyle.SQUARE: skia.Paint.Cap.kSquare_Cap,
    LineCapStyle.PROJECT: skia.Paint.Cap.kButt_Cap
}

_SKIA_JOIN_MAP = {
    LineJoinStyle.MITER: skia.Paint.Join.kMiter_Join,
    LineJoinStyle.BEVEL: skia.Paint.Join.kBevel_Join,
    LineJoinStyle.ROUND: skia.Paint.Join.kRound_Join
}

class BlendMode(Enum):
    """
    Defines how pixels from the source (drawing object) blend with 
    destination pixels (canvas/background).
    """
    NORMAL = "normal"            # Standard alpha blending (default)
    MULTIPLY = "multiply"        # Multiplies source and dest colors
    SCREEN = "screen"            # Opposite of multiply - brightens
    OVERLAY = "overlay"          # Combination of multiply and screen
    DARKEN = "darken"            # Takes darker of source/dest
    LIGHTEN = "lighten"          # Takes lighter of source/dest
    ADD = "add"                  # Adds colors together
    SUBTRACT = "subtract"        # Subtracts source from dest
    DIFFERENCE = "difference"    # Absolute difference between colors
    EXCLUSION = "exclusion"      # Similar to difference but lower contrast
    COLOR_DODGE = "color-dodge"  # Brightens dest based on source
    COLOR_BURN = "color-burn"    # Darkens dest based on source
    HARD_LIGHT = "hard-light"    # Similar to overlay
    SOFT_LIGHT = "soft-light"    # Softer version of hard-light
    HUE = "hue"                  # Takes hue from source, sat/lum from dest
    SATURATION = "saturation"    # Takes sat from source, hue/lum from dest
    COLOR = "color"              # Takes hue/sat from source, lum from dest
    LUMINOSITY = "luminosity"    # Takes lum from source, hue/sat from dest

# Map our BlendMode enum to Skia's blend mode constants
_SKIA_BLEND_MAP = {
    BlendMode.NORMAL: skia.BlendMode.kSrcOver,
    BlendMode.MULTIPLY: skia.BlendMode.kMultiply,
    BlendMode.SCREEN: skia.BlendMode.kScreen,
    BlendMode.OVERLAY: skia.BlendMode.kOverlay,
    BlendMode.DARKEN: skia.BlendMode.kDarken,
    BlendMode.LIGHTEN: skia.BlendMode.kLighten,
    BlendMode.ADD: skia.BlendMode.kPlus,
    BlendMode.SUBTRACT: skia.BlendMode.kDifference,
    BlendMode.DIFFERENCE: skia.BlendMode.kDifference,
    BlendMode.EXCLUSION: skia.BlendMode.kExclusion,
    BlendMode.COLOR_DODGE: skia.BlendMode.kColorDodge,
    BlendMode.COLOR_BURN: skia.BlendMode.kColorBurn,
    BlendMode.HARD_LIGHT: skia.BlendMode.kHardLight,
    BlendMode.SOFT_LIGHT: skia.BlendMode.kSoftLight,
    BlendMode.HUE: skia.BlendMode.kHue,
    BlendMode.SATURATION: skia.BlendMode.kSaturation,
    BlendMode.COLOR: skia.BlendMode.kColor,
    BlendMode.LUMINOSITY: skia.BlendMode.kLuminosity,
}

_SKIA_TILE_MAP = {
    TileMode.CLAMP: skia.TileMode.kClamp,
    TileMode.REPEAT: skia.TileMode.kRepeat,
    TileMode.MIRROR: skia.TileMode.kMirror,
    TileMode.DECAL: skia.TileMode.kDecal,
}

_IMAGE_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)
_IMAGE_CACHE: dict = {}
_MISSING_WARNED: set = set()
_IMAGE_MEAN_CACHE: dict = {}
_SHAPE_TILE_DEFAULT_DU = 48.0
_TEXTURE_COLOR_FALLBACK = (0.65, 0.65, 0.65, 1.0)
_MEAN_THUMB_SIDE = 32
_MEAN_MIN_ALPHA = 16  # 0–255; skip near-transparent matte / holes

# Open-path shapes whose primary paint is stroke (Line today; Bézier later).
STROKE_TYPE_NAMES = frozenset({"Line", "Track", "_Stroke"})


def _kind(obj) -> str:
    from .entity import scena_kind
    return scena_kind(obj)


def is_stroke_type(shape) -> bool:
    """True when the shape family draws as a stroke, not a filled area."""
    from .entity import scena_kind
    return scena_kind(shape) in STROKE_TYPE_NAMES


class SpriteBody:
    """Truthy fill sentinel for :class:`~scena.sprite.Sprite`.

    The bitmap is the body. Filter batching sees a fill channel; drawing never
    paints this as a solid — ``Sprite._geometry_draw`` blits the image instead.
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return "SpriteBody"


SPRITE_BODY = SpriteBody()


def is_sprite_body(value) -> bool:
    return value is SPRITE_BODY


def _coerce_channel_paint(value):
    """Fill/line channel: ``None`` clears; Gradient/Texture/ProceduralFill pass through."""
    value = as_payload(value)
    if value is None:
        return None
    if value is SPRITE_BODY:
        return SPRITE_BODY
    fe = globals().get("FilterEffect")
    if fe is not None and isinstance(value, fe):
        raise TypeError(
            "fill/line expected a paint material (color, Gradient, Texture, …), "
            f"got filter {type(value).__name__}. Use fill_filter / line_filter."
        )
    try:
        from .visuals import Visual
        if isinstance(value, Visual):
            raise TypeError(
                "fill/line expected a paint material (color, Gradient, Texture, …), "
                f"got look {type(value).__name__}. Assign with "
                f"shape.visual = {type(value).__name__}()."
            )
    except ImportError:
        pass
    types = tuple(
        t for t in (
            globals().get("Gradient"),
            globals().get("Texture"),
            globals().get("ProceduralFill"),
        )
        if t is not None
    )
    if types and isinstance(value, types):
        return value
    return Color(value)


class PaintState:
    """Internal paint/filter/visual channels for drawable shapes.

    Not part of the beginner API by name — authors use Shape properties
    (``.visual``, ``.fill``, ``.line``, ``.line_width``, …).
    """

    __slots__ = (
        '_line_width', '_dash', '_line_cap', '_line_join',
        '_line', '_fill', '_blend',
        '_cached_line_paint', '_cached_fill_paint',
        '_cached_line_fx', '_cached_line_bare',
        '_cached_fill_fx', '_cached_fill_bare',
        '_cached_proc_paint', '_cached_proc_bare', '_cached_proc_fx',
        '_is_line_paint_dirty', '_is_fill_paint_dirty',
        '_line_filter', '_fill_filter', '_visual',
        '_look_identity', '_in_visual_apply',
        '_tex_fill_hw', '_tex_fill_hh',
        '_tex_line_hw', '_tex_line_hh',
        '_saved_visual',
        # Appearance stamps (sticky; orthogonal to .visual)
        '_glow', '_shadow', '_hue', '_gray', '_tail',
        '_tail_follow', '_tail_locked_angle', '_tail_prev',
        '_tail_vx', '_tail_vy', '_tail_speed_scale', '_tail_frame',
        '_tail_angle', '_tail_size', '_tail_amount',
        '_stamp_base_ff', '_stamp_base_lf',
        '_in_stamp_sync', '_tail_ghosting',
    )

    _default_instance = None

    @classmethod
    def get_defaults(cls) -> 'PaintState':
        """Prototype channels copied into new shapes."""
        return cls._default_instance

    @classmethod
    def set_defaults(
        cls,
        visual: Optional["LookLike"] = None,
        *,
        line_width: float = DEFAULT_LINE_WIDTH,
        dash: Union[DashStyle, str] = DashStyle.SOLID,
        line_cap: Union[LineCapStyle, str] = LineCapStyle.ROUND,
        line_join: Union[LineJoinStyle, str] = LineJoinStyle.MITER,
        line: Optional["PaintMaterial"] = (0.0, 0.0, 0.0, 1.0),
        fill: Optional["PaintMaterial"] = (1.0, 1.0, 1.0, 1.0),
        blend: Union[BlendMode, str] = BlendMode.NORMAL,
        line_filter: Optional["FilterEffect"] = None,
        fill_filter: Optional["FilterEffect"] = None,
    ) -> 'PaintState':
        """Install the prototype paint-state for new shapes.

        Prefer ``set_defaults(visual=Neon())`` or a color / Gradient; optional
        channel kwargs set the underlying package (rare).
        """
        look = coerce_visual(visual) if visual is not None else None
        state = cls.__new__(cls)
        state._line_width = fixed_magnitude(line_width, "line_width")
        state._dash = coerce_enum(dash, DashStyle, what="dash")
        state._line_cap = coerce_enum(line_cap, LineCapStyle, what="line_cap")
        state._line_join = coerce_enum(line_join, LineJoinStyle, what="line_join")
        state._blend = coerce_enum(blend, BlendMode, what="blend")
        state._line_filter = _coerce_filter(line_filter, what="line_filter")
        state._fill_filter = _coerce_filter(fill_filter, what="fill_filter")
        state._visual = None
        state._look_identity = None
        state._in_visual_apply = False
        state._line = _coerce_channel_paint(line)
        state._fill = _coerce_channel_paint(fill)
        state._cached_line_paint = None
        state._cached_fill_paint = None
        state._cached_line_fx = None
        state._cached_line_bare = None
        state._cached_fill_fx = None
        state._cached_fill_bare = None
        state._cached_proc_paint = None
        state._cached_proc_bare = None
        state._cached_proc_fx = None
        state._is_line_paint_dirty = True
        state._is_fill_paint_dirty = True
        state._tex_fill_hw = None
        state._tex_fill_hh = None
        state._tex_line_hw = None
        state._tex_line_hh = None
        state._saved_visual = None
        from .stamps import init_stamp_fields
        init_stamp_fields(state)
        cls._default_instance = state
        if look is not None:
            # Apply after installing defaults so Paint/etc. write channels onto prototype.
            state.visual = look
        return state

    @classmethod
    def _reset_defaults(cls) -> 'PaintState':
        """Install the framework's own prototype (what a fresh canvas has):
        pale line, navy fill, solid round-capped stroke. Called by the canvas
        at construction and by test harnesses that start a program from a
        clean process (``tests/system_support.reset_world_settings``)."""
        return cls.set_defaults(
            line_width=DEFAULT_LINE_WIDTH,
            dash=DashStyle.SOLID,
            line_cap=LineCapStyle.ROUND,
            line_join=LineJoinStyle.MITER,
            line=(0.8, 0.8, 0.9, 1.0),
            fill=(0.0, 0.0, 0.5, 1.0),
            blend=BlendMode.NORMAL,
        )

    def __init__(self):
        defaults = self.get_defaults()
        if defaults is None:
            raise RuntimeError("No default paint state has been set yet")
        self.look_like(defaults)
        self._cached_line_paint = None
        self._cached_fill_paint = None
        self._cached_line_fx = None
        self._cached_line_bare = None
        self._cached_fill_fx = None
        self._cached_fill_bare = None
        self._cached_proc_paint = None
        self._cached_proc_bare = None
        self._cached_proc_fx = None
        self._invalidate_line_paint()
        self._invalidate_fill_paint()
        self._tex_fill_hw = None
        self._tex_fill_hh = None
        self._tex_line_hw = None
        self._tex_line_hh = None
        self._saved_visual = None
        # look_like copies stamps from defaults (usually None); ensure fields exist.
        from .stamps import init_stamp_fields
        if not hasattr(self, "_glow"):
            init_stamp_fields(self)
        self._in_stamp_sync = False
        self._tail_ghosting = False

    def _cached_line_slot(self):
        if self._is_line_paint_dirty:
            return None
        fx = self._line_filter
        if fx is None:
            return self._cached_line_bare
        if fx is self._cached_line_fx:
            return self._cached_line_paint
        return None

    def _store_line_slot(self, paint) -> None:
        fx = self._line_filter
        if fx is None:
            self._cached_line_bare = paint
            if self._cached_line_fx is None:
                self._cached_line_paint = paint
        else:
            paint.setImageFilter(fx._skia_filter)
            self._cached_line_paint = paint
            self._cached_line_fx = fx

    def _cached_fill_slot(self):
        if self._is_fill_paint_dirty:
            return None
        fx = self._fill_filter
        if fx is None:
            return self._cached_fill_bare
        if fx is self._cached_fill_fx:
            return self._cached_fill_paint
        return None

    def _store_fill_slot(self, paint) -> None:
        fx = self._fill_filter
        if fx is None:
            self._cached_fill_bare = paint
            if self._cached_fill_fx is None:
                self._cached_fill_paint = paint
        else:
            paint.setImageFilter(fx._skia_filter)
            self._cached_fill_paint = paint
            self._cached_fill_fx = fx

    def _invalidate_line_paint(self) -> None:
        """Drop both line-paint slots (filtered and filter-free)."""
        self._is_line_paint_dirty = True
        self._cached_line_paint = None
        self._cached_line_fx = None
        self._cached_line_bare = None

    def _invalidate_fill_paint(self) -> None:
        """Drop both fill-paint slots and the procedural paint shell."""
        self._is_fill_paint_dirty = True
        self._cached_fill_paint = None
        self._cached_fill_fx = None
        self._cached_fill_bare = None
        self._cached_proc_paint = None
        self._cached_proc_bare = None
        self._cached_proc_fx = None

    def look_like(self, other: 'PaintState') -> 'PaintState':
        """Copy full appearance (channels + visual + stamps) without re-running apply."""
        if not isinstance(other, PaintState):
            raise TypeError(
                f"look_like() takes a shape or sprite to copy, got {type(other).__name__}"
            )
        self._line_width = other._line_width
        self._dash = other._dash
        self._line_cap = other._line_cap
        self._line_join = other._line_join
        self._line = other._line
        self._fill = other._fill
        self._blend = other._blend
        self._line_filter = other._line_filter
        self._fill_filter = other._fill_filter
        self._visual = getattr(other, '_visual', None)
        ident = getattr(other, '_look_identity', None)
        self._look_identity = None if ident is None else dict(ident)
        self._in_visual_apply = False

        if not other._is_line_paint_dirty:
            self._cached_line_paint = other._cached_line_paint
            self._cached_line_fx = getattr(other, "_cached_line_fx", None)
            self._cached_line_bare = getattr(other, "_cached_line_bare", None)
            self._is_line_paint_dirty = False
        else:
            self._invalidate_line_paint()

        if not other._is_fill_paint_dirty:
            self._cached_fill_paint = other._cached_fill_paint
            self._cached_fill_fx = getattr(other, "_cached_fill_fx", None)
            self._cached_fill_bare = getattr(other, "_cached_fill_bare", None)
            self._cached_proc_paint = getattr(other, "_cached_proc_paint", None)
            self._cached_proc_bare = getattr(other, "_cached_proc_bare", None)
            self._cached_proc_fx = getattr(other, "_cached_proc_fx", None)
            self._is_fill_paint_dirty = False
        else:
            self._invalidate_fill_paint()
        self._tex_fill_hw = getattr(other, "_tex_fill_hw", None)
        self._tex_fill_hh = getattr(other, "_tex_fill_hh", None)
        self._tex_line_hw = getattr(other, "_tex_line_hw", None)
        self._tex_line_hh = getattr(other, "_tex_line_hh", None)
        from .stamps import copy_stamps, init_stamp_fields
        if hasattr(other, "_glow"):
            copy_stamps(self, other)
        else:
            init_stamp_fields(self)
        self._in_stamp_sync = False
        self._tail_ghosting = False
        return self

    def save_visual(self) -> 'PaintState':
        """Remember current appearance for :meth:`restore_visual`.

        First call fills the one slot; further calls are no-ops until restore.
        Captures the same payload as :meth:`look_like` (channels, ``.visual``,
        look identity). Does not snapshot pose, transients, or ink.
        """
        if getattr(self, "_saved_visual", None) is not None:
            return self
        snap = PaintState.__new__(PaintState)
        snap.look_like(self)
        self._saved_visual = snap
        return self

    def restore_visual(self) -> 'PaintState':
        """Put back appearance from :meth:`save_visual`; clear the slot.

        No-op when nothing was saved. Uses :meth:`look_like`, not
        ``visual = None`` (identity restore).
        """
        snap = getattr(self, "_saved_visual", None)
        if snap is None:
            return self
        self.look_like(snap)
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn):
            fn()
        self._saved_visual = None
        return self

    def _primary_is_stroke(self) -> bool:
        """True when the drawn primary paint is stroke (stroke-type family)."""
        return is_stroke_type(self)

    def _apply_primary_paint(
        self,
        material,
        *,
        contrast_stroke: bool = True,
        alpha: Optional[float] = None,
    ) -> 'PaintState':
        """Write the beginner primary-paint package.

        Area shapes: solid → fill + optional contrast stroke; Gradient → fill
        plus optional darker mean-stop outline (``line_width`` unchanged);
        Texture / ProceduralFill → fill only.
        Stroke types (Line, …): material goes on ``.line``, ``.fill`` cleared.
        """
        advanced = isinstance(material, (Gradient, Texture, ProceduralFill))
        if self._primary_is_stroke():
            if advanced:
                self.line = material
            else:
                c = material if isinstance(material, Color) else Color(material)
                if alpha is not None:
                    c = c.with_alpha(float(alpha))
                self.line = c
            self.fill = None
            return self

        if advanced:
            self.fill = material
            if contrast_stroke and isinstance(material, Gradient):
                line = material.mean_color().darker(0.2)
                if alpha is not None:
                    try:
                        line = line.with_alpha(float(alpha))
                    except Exception:
                        pass
                self.line = line
            else:
                self.line = None
            return self

        c = material if isinstance(material, Color) else Color(material)
        if alpha is not None:
            c = c.with_alpha(float(alpha))
        self.fill = c
        if contrast_stroke:
            line = c.contrast_tone(intensity=0.2)
            if alpha is not None:
                try:
                    line = line.with_alpha(float(alpha))
                except Exception:
                    pass
            self.line = line
        else:
            self.line = None
        return self

    def set_color(self, *args) -> 'PaintState':
        """Look-level recolor: solid, Gradient, Texture, or ProceduralFill.

        Stroke types: always the stroke channel. Area shapes: standard fill
        package, except outline-only rings keep fill empty and recolor the line.
        Active identity visuals (roles A/B) write the bound channel then re-apply.
        A seeded look (``Neon("red")``, ``Halo("blue")``, …) is swapped for its
        unseeded sibling first so the re-apply samples the new live color.
        Pigment visuals (Glow/Shadow) recolor the body only.

        Interned Paint / Fill / Stroke installers are replaced (not re-applied)
        so set_color is not rewound by the previous material.
        """
        from .entity import _refuse_if_destroyed
        _refuse_if_destroyed(self, "set_color")
        args = as_payload_all(*args)
        if not args:
            raise TypeError(
                "set_color() needs a color: set_color(\"red\"), set_color(\"#ff8800\"), "
                "set_color(1, 0.5, 0) or set_color(Gradient(...))."
            )
        if len(args) == 1 and isinstance(args[0], (Gradient, Texture, ProceduralFill, Color)):
            material = args[0]
        else:
            material = Color(*args) if len(args) > 1 else Color(args[0])
        visual = getattr(self, "_visual", None)
        role = getattr(visual, "_color_role", None) if visual is not None else None
        outline_only = self._is_outline_only()

        # Paint / Fill / Stroke bake material into an interned look. Re-apply
        # would stamp the old material back — replace the installer instead.
        if visual is not None:
            from .visuals import Paint, Fill, Stroke
            advanced = isinstance(material, (Gradient, Texture, ProceduralFill))
            if isinstance(visual, Paint):
                self.visual = Paint(material, alpha=visual.alpha, line=visual.line)
                return self
            if isinstance(visual, Fill):
                if advanced:
                    self.visual = Paint(material)
                else:
                    self.visual = Fill(material, alpha=getattr(visual, "alpha", None))
                return self
            if isinstance(visual, Stroke):
                if advanced:
                    self.visual = Paint(material)
                else:
                    self.visual = Stroke(material, width=getattr(visual, "width", None))
                return self

        if role == "A":
            self._in_recolor = True
            try:
                self._apply_primary_paint(material)
            finally:
                self._in_recolor = False
            self._deseed_active_visual()
            self._reapply_visual()
            return self
        if role == "B":
            # Same package as color= (fill + derived outline; a ring keeps its
            # ring): the outline look then follows that outline. Before
            # 2026-10-13 it wrote the exact line, so the shape kept a line no
            # color= gives once the look was removed.
            self._in_recolor = True
            try:
                if outline_only:
                    self._recolor_outline_only(material)
                else:
                    self._apply_primary_paint(material)
            finally:
                self._in_recolor = False
            self._deseed_active_visual()
            self._reapply_visual()
            return self

        if outline_only and not self._primary_is_stroke():
            self._recolor_outline_only(material)
        else:
            self._apply_primary_paint(material)
        if visual is not None and role in ("C", "D", "E"):
            self._reapply_visual()
        if role == "D":
            _warn_recolor_hidden(visual)
        return self

    @property
    def color(self) -> Color:
        """Primary solid color (fill on area shapes, stroke on Line).

        Under a look that paints its own body (Flame, Swell, …) the live paint
        is the look's; the author's color is the identity snapshot.
        """
        stroke = self._primary_is_stroke()
        paint = self._line if stroke else self._fill
        if isinstance(paint, Color) and paint:
            return paint
        ident = getattr(self, "_look_identity", None)
        if ident is not None and getattr(self, "_visual", None) is not None:
            authored = ident.get("line" if stroke else "fill")
            if isinstance(authored, Color) and authored:
                return authored
        return Color(0.0, 0.0, 0.5, 1.0)

    @color.setter
    def color(self, value) -> None:
        self.set_color(value)

    def _is_outline_only(self) -> bool:
        """Ring: no fill, has line. Uses look-identity when a visual is active."""
        if self._primary_is_stroke():
            return False
        ident = getattr(self, "_look_identity", None)
        if ident is not None:
            return ident.get("fill") is None and bool(ident.get("line"))
        return getattr(self, "_fill", None) is None and bool(getattr(self, "_line", None))

    def _recolor_outline_only(self, material) -> None:
        """Keep fill empty; put the material on the stroke."""
        if isinstance(material, (Gradient, Texture, ProceduralFill)):
            self.line = material
        else:
            c = material if isinstance(material, Color) else Color(material)
            self.line = c
        self.fill = None

    def _deseed_active_visual(self) -> None:
        """If the active look was constructed with an explicit color=, swap it for
        its unseeded sibling so this and future recolors track the live channel
        instead of being silently reverted, and so repeated recoloring does not
        keep interning new seeded instances."""
        vis = getattr(self, "_visual", None)
        unseed = getattr(vis, "_unseed", None)
        sibling = unseed() if callable(unseed) else None
        if sibling is not None and sibling is not vis:
            self._visual = sibling          # bypass the .visual setter on purpose

    def _reapply_visual(self) -> None:
        """Rebuild the active look from the author package (does not re-patch identity).

        Compiled looks (GlowRim, ElectricBolt, …) rewrite live fill/line/filters.
        Quality cycling and ``set_color`` must not sample that compiled core as
        if it were the host tint. Restore identity first; ``apply`` then writes
        the fidelity-appropriate package. Stamp recomposition runs after apply.
        """
        vis = getattr(self, "_visual", None)
        if vis is None:
            return
        from .visuals import Visual
        if not isinstance(vis, Visual):
            return
        # Cheap restore: apply() rewrites the package; skip stamp/blit here.
        self._restore_look_identity(recompose=False)
        try:
            from .visuals import _clear_host_tint_stashes
            _clear_host_tint_stashes(self)
        except Exception:
            pass
        self._in_visual_apply = True
        try:
            vis._apply(self)
        finally:
            self._in_visual_apply = False
        from .stamps import capture_stamp_bases, sync_stamp_filters
        capture_stamp_bases(self)
        self._in_stamp_sync = True
        try:
            sync_stamp_filters(self)
        finally:
            self._in_stamp_sync = False

    def set_alpha(self, alpha: float) -> 'PaintState':
        """Update alpha on fill and line materials when they support it."""
        from .validate import alpha01
        alpha = alpha01(alpha, "set_alpha")
        def _alpha_changed(paint) -> bool:
            if isinstance(paint, Color):
                return abs(paint.alpha - alpha) >= 1e-6
            if isinstance(paint, Gradient):
                return any(abs(c.alpha - alpha) >= 1e-6 for c in paint._colors)
            if isinstance(paint, Texture):
                return abs(float(paint.alpha) - float(alpha)) >= 1e-6
            return True

        def _faded(paint):
            # A new material: the old one may be shared (the default paint,
            # a clone, a look_like source, a save_visual snapshot, a Gradient
            # two shapes use). Mutating it faded all of them (HP1).
            if isinstance(paint, Color):
                return paint.with_alpha(alpha)
            if isinstance(paint, Gradient):
                return paint._map_stops(lambda c: c.with_alpha(alpha))
            if isinstance(paint, Texture):
                faded = copy.copy(paint)        # shares the image and shaders
                object.__setattr__(faded, "_alpha", alpha)
                return faded
            paint.set_alpha(alpha)              # procedural: no shared state
            return paint

        if self._fill and _alpha_changed(self._fill):
            self._fill = _faded(self._fill)
            self._invalidate_fill_paint()
        if self._line and _alpha_changed(self._line):
            self._line = _faded(self._line)
            self._invalidate_line_paint()
        return self

    # --- channel properties ---

    @property
    def line_width(self) -> float:
        """Outline thickness in design units (>= 0; shapes default to 1.5)."""
        return self._line_width

    @line_width.setter
    def line_width(self, value: float) -> None:
        self._line_width = fixed_magnitude(value, "line_width")
        self._invalidate_line_paint()
        if self._patch_look_identity(line_width=self._line_width):
            self._look_channel_written("line_width")

    @property
    def dash(self) -> str:
        """Outline pattern: ``"solid"`` · ``"dash"`` · ``"dot"`` · ``"dot-dash"``."""
        return self._dash.value

    @dash.setter
    def dash(self, value: Union[DashStyle, str]) -> None:
        self._dash = coerce_enum(value, DashStyle, what="dash")
        self._invalidate_line_paint()
        if self._patch_look_identity(dash=self._dash):
            self._look_channel_written("dash")

    @property
    def line_cap(self) -> str:
        """Open-line ends: ``"round"`` · ``"square"`` · ``"project"``."""
        return self._line_cap.value

    @line_cap.setter
    def line_cap(self, value: Union[LineCapStyle, str]) -> None:
        self._line_cap = coerce_enum(value, LineCapStyle, what="line_cap")
        self._invalidate_line_paint()
        if self._patch_look_identity(line_cap=self._line_cap):
            self._look_channel_written("line_cap")

    @property
    def line_join(self) -> str:
        """Outline corners: ``"miter"`` · ``"bevel"`` · ``"round"``."""
        return self._line_join.value

    @line_join.setter
    def line_join(self, value: Union[LineJoinStyle, str]) -> None:
        self._line_join = coerce_enum(value, LineJoinStyle, what="line_join")
        self._invalidate_line_paint()
        if self._patch_look_identity(line_join=self._line_join):
            self._look_channel_written("line_join")

    @property
    def line(self) -> Optional["PaintMaterial"]:
        """Outline material: a color, ``Gradient``, ``Texture``, or ``None`` (no outline)."""
        return self._line

    @line.setter
    def line(self, value: Optional["PaintMaterial"]) -> None:
        self._line = _coerce_channel_paint(value)
        self._invalidate_line_paint()
        if self._patch_look_identity(line=self._line):
            self._look_channel_written("line")

    @property
    def fill(self) -> Optional["PaintMaterial"]:
        """Interior material: a color, ``Gradient``, ``Texture``, a procedural fill (``WaterFill()`` …), or ``None``."""
        return self._fill

    @fill.setter
    def fill(self, value: Optional["PaintMaterial"]) -> None:
        self._fill = _coerce_channel_paint(value)
        self._invalidate_fill_paint()
        if self._patch_look_identity(fill=self._fill):
            self._look_channel_written("fill")

    @property
    def blend(self) -> str:
        """How this paints over what is below: ``"normal"`` (default), ``"add"``,
        ``"multiply"``, ``"screen"``, ``"overlay"``, … (any ``BlendMode`` name).
        """
        return self._blend.value

    @blend.setter
    def blend(self, value: Union[BlendMode, str]) -> None:
        self._blend = coerce_enum(value, BlendMode, what="blend")
        self._invalidate_line_paint()
        self._invalidate_fill_paint()
        # Looks rewrite ``.blend`` for fill/line wash while ``_in_visual_apply``.
        # Sprite body blit stays on the author package (Halo fill: NORMAL blit,
        # not ADD wash). Identity restore / author writes still rebuild — the
        # blit before the re-apply below, so it takes the author's blend.
        if not getattr(self, "_in_visual_apply", False):
            fn = getattr(self, "_rebuild_blit_paint", None)
            if callable(fn):
                fn()
        if self._patch_look_identity(blend=self._blend):
            self._look_channel_written("blend")

    @property
    def line_filter(self) -> Optional['FilterEffect']:
        """Filter on the outline only (``Blur()``, ``GlowFilter()``, …), or ``None``."""
        return self._line_filter

    @line_filter.setter
    def line_filter(self, value: Optional['FilterEffect']) -> None:
        self._line_filter = _coerce_filter(value, what="line_filter")
        self._invalidate_line_paint()
        if (
            not getattr(self, "_in_visual_apply", False)
            and not getattr(self, "_in_stamp_sync", False)
        ):
            self._stamp_base_lf = self._line_filter
            from .stamps import sync_stamp_filters
            self._in_stamp_sync = True
            try:
                sync_stamp_filters(self)
            finally:
                self._in_stamp_sync = False
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn) and not getattr(self, "_in_visual_apply", False):
            fn()

    @property
    def fill_filter(self) -> Optional['FilterEffect']:
        """Filter on the interior only (``Blur()``, ``DropShadow()``, …), or ``None``."""
        return self._fill_filter

    @fill_filter.setter
    def fill_filter(self, value: Optional['FilterEffect']) -> None:
        self._fill_filter = _coerce_filter(value, what="fill_filter")
        self._invalidate_fill_paint()
        if (
            not getattr(self, "_in_visual_apply", False)
            and not getattr(self, "_in_stamp_sync", False)
        ):
            self._stamp_base_ff = self._fill_filter
            from .stamps import sync_stamp_filters
            self._in_stamp_sync = True
            try:
                sync_stamp_filters(self)
            finally:
                self._in_stamp_sync = False
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn) and not getattr(self, "_in_visual_apply", False):
            fn()

    def _look_channel_written(self, channel: str) -> None:
        """An author write to ``.fill`` / ``.line`` (or ``line_width`` /
        ``blend`` / ``dash`` / ``line_cap`` / ``line_join``) under a look:
        re-apply the look on the new value, so writing before or after
        ``visual =`` draws the same. A look that sets the knob itself keeps its
        own (Rim's width, Halo's ADD); the value shows after ``visual = None``.
        A seed on the written colour channel gives way (``Rim("red")`` then
        ``.line = "blue"`` is a blue rim), as in ``set_color``. Installers
        (Paint / Fill / Stroke) wrote the channels once: a later write stands.
        Looks' own writes (``_in_visual_apply``) and ``set_color``'s
        (``_in_recolor``) do not come here."""
        if getattr(self, "_in_recolor", False):
            return
        from .visuals import Visual, Paint, Fill, Stroke
        vis = getattr(self, "_visual", None)
        if not isinstance(vis, Visual) or isinstance(vis, (Paint, Fill, Stroke)):
            return
        role = getattr(vis, "_color_role", None)
        bound = "line" if role == "B" or self._primary_is_stroke() else "fill"
        if role in ("A", "B") and channel == bound and vis._seeded():
            self._deseed_active_visual()
        self._reapply_visual()

    def _patch_look_identity(self, **channels) -> bool:
        """Keep the author snapshot in sync with explicit fill/line edits.
        True when it patched: an author write under a look (the snapshot
        exists only while a look is on), so the setter re-applies it — a
        shape without a look pays nothing more than this lookup.

        Costume ``_apply()`` writes channels with ``_in_visual_apply`` set so
        wash / filters / procedural fills do not overwrite identity.
        """
        ident = getattr(self, "_look_identity", None)
        if ident is None or getattr(self, "_in_visual_apply", False):
            return False
        patch = dict(ident)
        patch.update(channels)
        self._look_identity = patch
        return True

    def _look_identity_from_live(self) -> dict:
        # Prefer stamp bases so GlowFilter from stamps is not snapshotted as identity.
        ff = getattr(self, "_stamp_base_ff", None)
        lf = getattr(self, "_stamp_base_lf", None)
        if not hasattr(self, "_stamp_base_ff"):
            ff = self._fill_filter
            lf = self._line_filter
        return {
            "line_width": self._line_width,
            "dash": self._dash,
            "line_cap": self._line_cap,
            "line_join": self._line_join,
            "line": self._line,
            "fill": self._fill,
            "blend": self._blend,
            "line_filter": lf,
            "fill_filter": ff,
        }

    def _snapshot_look_identity(self) -> None:
        """Capture author package (first costume only)."""
        if getattr(self, "_look_identity", None) is None:
            self._look_identity = self._look_identity_from_live()

    def _restore_look_identity(self, *, recompose: bool = True) -> None:
        ident = getattr(self, "_look_identity", None)
        if ident is None:
            return
        self._line_width = ident["line_width"]
        self._dash = ident["dash"]
        self._line_cap = ident["line_cap"]
        self._line_join = ident["line_join"]
        self._line = ident["line"]
        self._fill = ident["fill"]
        self._blend = ident["blend"]
        self._line_filter = ident["line_filter"]
        self._fill_filter = ident["fill_filter"]
        self._invalidate_line_paint()
        self._invalidate_fill_paint()
        self._cached_line_paint = None
        self._cached_fill_paint = None
        if not recompose:
            return
        # Identity filters become stamp bases; recompose glow/shadow on top.
        from .stamps import capture_stamp_bases, sync_stamp_filters
        capture_stamp_bases(self)
        self._in_stamp_sync = True
        try:
            sync_stamp_filters(self)
        finally:
            self._in_stamp_sync = False
        fn = getattr(self, "_rebuild_blit_paint", None)
        if callable(fn):
            fn()

    def _identity_capture_live(self) -> None:
        """Paint-family: identity becomes the applied package."""
        if getattr(self, "_look_identity", None) is None:
            return
        self._look_identity = self._look_identity_from_live()

    def _identity_patch_seed(self, rgba, *, channel: str = "auto") -> None:
        """Dye identity with a look's seed: a body look (Role A) as the
        set_color package (outline-only keeps a ring); an outline look
        (Role B, or ``channel="line"``) on the outline only, exact —
        ``Rim("red")`` leaves what ``line = "red"`` then ``Rim()`` leaves."""
        ident = getattr(self, "_look_identity", None)
        if ident is None or rgba is None:
            return
        rgb = tuple(rgba)
        a = float(rgb[3]) if len(rgb) > 3 else 1.0
        col = Color(float(rgb[0]), float(rgb[1]), float(rgb[2]), a)
        patch = dict(ident)
        outline_only = (
            not self._primary_is_stroke()
            and patch.get("fill") is None
            and patch.get("line") is not None
        )
        if channel == "auto":
            vis = getattr(self, "_visual", None)
            channel = "line" if getattr(vis, "_color_role", None) == "B" else "fill"
        if self._primary_is_stroke() or outline_only:
            patch["line"] = col
            if self._primary_is_stroke():
                patch["fill"] = None
        elif channel == "line":
            patch["line"] = col
        else:
            patch["fill"] = col
            if patch.get("line") is not None:
                try:
                    patch["line"] = col.contrast_tone(intensity=0.2)
                except Exception:
                    patch["line"] = col
        self._look_identity = patch

    @property
    def visual(self) -> Optional["Visual"]:
        """Active look program, or None.

        Assigning snapshots the author package (first look), then runs
        ``visual._apply``. Replacing a look restores that snapshot first so
        leftover wash / ADD blend / filters do not leak into the next look.
        Host-tint ``color=`` seeds that snapshot.
        ``visual = None`` restores the snapshot (not module defaults).
        """
        return getattr(self, '_visual', None)

    @visual.setter
    def visual(self, value: Optional["Visual"]) -> None:
        if value is None:
            self._visual = None
            try:
                from .visuals import _clear_host_tint_stashes
                _clear_host_tint_stashes(self)
            except Exception:
                pass
            if getattr(self, "_look_identity", None) is not None:
                self._restore_look_identity()
                self._look_identity = None
            else:
                # No identity — stamps stay. Recompose from existing stamp
                # bases; do not capture live filters (they already include stamps).
                from .stamps import sync_stamp_filters
                self._in_stamp_sync = True
                try:
                    sync_stamp_filters(self)
                finally:
                    self._in_stamp_sync = False
            fn = getattr(self, "_refresh_plain_blit", None)
            if callable(fn):
                fn()
            return
        value = coerce_visual(value)
        from .stamps import is_stamp_visual, stamp_visual_hint
        if is_stamp_visual(value):
            raise TypeError(stamp_visual_hint(value))
        # Every refusal before any write: a rejected look used to strip the
        # current one first (HP3).
        # Pixel-body looks are Sprite-only (HueShift / Recolor / Aura / EmissiveBloom).
        from .entity import is_sprite_family, scena_kind
        if getattr(value, "_sprite_only", False) and not is_sprite_family(self):
            name = type(value).__name__
            tex_hint = (
                f"For Shape bitmaps use Texture(..., shift={name}(...)). "
                if name in ("HueShift", "Recolor")
                else ""
            )
            raise TypeError(
                f"Cannot assign {name} as shape.visual — it is sprite-only "
                f"(needs a bitmap body). {tex_hint}"
                f"Use Halo / Rim on a Shape, or assign {name} to a Sprite."
            )
        prev = getattr(self, "_visual", None)
        if prev is None:
            self._snapshot_look_identity()
        elif prev is not value:
            # Start the new look from the author package, not live look
            # memory (Halo wash, Bolt ADD, rewritten width, …).
            # Same interned instance (slider rebuild / re-apply) keeps live fill.
            try:
                from .visuals import _clear_host_tint_stashes
                _clear_host_tint_stashes(self)
            except Exception:
                pass
            self._restore_look_identity()
        self._visual = value
        self._in_visual_apply = True
        try:
            from .visuals import Visual
            if isinstance(value, Visual):
                value._apply(self)
                patch = getattr(value, "_identity_patch", None)
                if patch is not None:
                    patch(self)
        finally:
            self._in_visual_apply = False
        # Costume filters are stamp bases; recompose glow/shadow on top.
        from .stamps import capture_stamp_bases, sync_stamp_filters
        capture_stamp_bases(self)
        self._in_stamp_sync = True
        try:
            sync_stamp_filters(self)
        finally:
            self._in_stamp_sync = False
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn):
            fn()

    # --- Appearance stamps ---------------------------------------------------

    def _after_stamp_change(self) -> None:
        from .stamps import sync_stamp_filters
        self._in_stamp_sync = True
        try:
            sync_stamp_filters(self)
        finally:
            self._in_stamp_sync = False
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn):
            fn()

    @property
    def glow(self):
        """Sticky glow stamp (Glow or CheapGlow), or None."""
        return getattr(self, "_glow", None)

    @glow.setter
    def glow(self, value) -> None:
        from .stamps import coerce_glow
        from .visuals import Glow, CheapGlow
        if _kind(self) == "Text" and value is not None:
            look = coerce_glow(value)
            if look is not None and not isinstance(look, (Glow, CheapGlow)):
                raise TypeError(
                    f"Text.glow expected True, a color, Glow(...), or CheapGlow(...), "
                    f"got {type(look).__name__}."
                )
            self._glow = look
        else:
            self._glow = coerce_glow(value)
        self._after_stamp_change()

    @property
    def shadow(self):
        """Sticky shadow stamp, or None."""
        return getattr(self, "_shadow", None)

    @shadow.setter
    def shadow(self, value) -> None:
        if _kind(self) == "Text" and value is not None and value is not False:
            raise TypeError(
                "Text does not support .shadow — use shape.shadow / sprite.shadow."
            )
        from .stamps import coerce_shadow
        self._shadow = coerce_shadow(value)
        self._after_stamp_change()

    @property
    def hue(self):
        """Sticky HueShift stamp (Sprite only), or None."""
        return getattr(self, "_hue", None)

    @hue.setter
    def hue(self, value) -> None:
        from .entity import is_sprite_family, scena_kind
        name = scena_kind(self)
        if name == "Text" and value is not None and value is not False:
            raise TypeError("Text does not support .hue — use sprite.hue.")
        if not is_sprite_family(self) and value is not None and value is not False:
            raise TypeError(
                "shape.hue is Sprite-only (needs a bitmap body). "
                "For Shape bitmaps use Texture(..., shift=HueShift(...))."
            )
        from .stamps import coerce_hue, apply_hue_stamp
        look = coerce_hue(value)
        self._hue = look
        apply_hue_stamp(self, look)
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn):
            fn()

    @property
    def gray(self):
        """Sticky Grayscale stamp (Sprite only), or None."""
        return getattr(self, "_gray", None)

    @gray.setter
    def gray(self, value) -> None:
        from .entity import is_sprite_family
        if value is not None and value is not False:
            if _kind(self) == "Text":
                raise TypeError("Text does not support .gray — use sprite.gray.")
            if not is_sprite_family(self):
                raise TypeError(
                    "shape.gray is Sprite-only (needs a bitmap body). "
                    "For a gray shape, pick a gray color."
                )
        from .stamps import coerce_gray, apply_gray_stamp
        look = coerce_gray(value)
        self._gray = look
        apply_gray_stamp(self, look)
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn):
            fn()

    @property
    def tail(self):
        """Sticky Tail stamp, or None."""
        return getattr(self, "_tail", None)

    @tail.setter
    def tail(self, value) -> None:
        if _kind(self) == "Text" and value is not None and value is not False:
            raise TypeError("Text does not support .tail — use shape.tail / sprite.tail.")
        from .stamps import coerce_tail, install_tail_from_look
        look, follow, locked = coerce_tail(value)
        install_tail_from_look(self, look, follow=follow, locked_angle=locked)
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn):
            fn()

    # --- Skia materialization ---

    def _texture_shader(self, tex: 'Texture'):
        """Stable image shader: tile is baked; sprite is cached per quantized AABB."""
        if not tex._needs_host_fit:
            return tex._skia_shader, None, None
        hw, hh = _local_half_extents(self)
        qhw = _quantize_extent(hw)
        qhh = _quantize_extent(hh)
        return tex._shader_for_local(hw, hh), qhw, qhh

    def _gradient_shader(self, grad: 'Gradient'):
        """Absolute size is baked; auto size scales a unit shader per quantized AABB."""
        if not grad._needs_host_fit:
            return grad._skia_shader, None, None
        hw, hh = _local_half_extents(self)
        qhw = _quantize_extent(hw)
        qhh = _quantize_extent(hh)
        scale = _gradient_fit_scale(qhw, qhh, grad)
        return grad._shader_for_scale(scale), qhw, qhh

    def _material_paint(self, material, **fields) -> Tuple[skia.Paint, Optional[Tuple[float, float]]]:
        """New paint for ``material`` with ``fields`` (``skia.Paint`` kwargs).

        Returns ``(paint, extents)``; extents are set when the material is
        size-sensitive. The shader goes in through the ``Shader=`` kwarg, which
        shares it; ``setShader`` would deep-copy a Texture's image per paint
        (see the note above ``_IMAGE_PAINT_CACHE``).
        """
        if isinstance(material, Texture):
            shader, qhw, qhh = self._texture_shader(material)
            paint = skia.Paint(Shader=shader, **fields)
            paint.setAlphaf(float(material.alpha))
            cf = material._shift_color_filter
            if cf is not None:
                paint.setColorFilter(cf)
        elif isinstance(material, Gradient):
            shader, qhw, qhh = self._gradient_shader(material)
            paint = skia.Paint(Shader=shader, **fields)
        elif isinstance(material, ProceduralFill):
            return skia.Paint(Shader=material._skia_shader, **fields), None
        else:
            paint = skia.Paint(**fields)
            paint.setColor4f(material.color4f)
            return paint, None
        return paint, (None if qhw is None else (qhw, qhh))

    def _to_skia_line_paint(self) -> skia.Paint:
        if not self._line:
            return None

        tex_extents = None
        qhw = qhh = None
        if _material_needs_host_fit(self._line):
            hw, hh = _local_half_extents(self)
            qhw, qhh = _quantize_extent(hw), _quantize_extent(hh)
            tex_extents = (qhw, qhh)
            if self._tex_line_hw != qhw or self._tex_line_hh != qhh:
                self._cached_line_paint = None
                self._cached_line_bare = None
                self._cached_line_fx = None
        hit = self._cached_line_slot()
        if hit is not None and (qhw is None or (
            self._tex_line_hw == qhw and self._tex_line_hh == qhh
        )):
            return hit
        # Zero is a collapsed size: no stroke. Skia's width 0 is a 1-device-pixel
        # hairline, which a tween or formula ending at 0 left visible (HP10).
        # Checked on a build only: ``line_width =`` clears the cached paint.
        if self._line_width <= 0:
            return None

        paint, got = self._material_paint(
            self._line,
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=self._line_width,
            StrokeCap=_SKIA_CAP_MAP[self._line_cap],
            StrokeJoin=_SKIA_JOIN_MAP[self._line_join],
            BlendMode=_SKIA_BLEND_MAP[self._blend]
        )
        if got is not None:
            self._tex_line_hw, self._tex_line_hh = got
        elif tex_extents is not None:
            self._tex_line_hw, self._tex_line_hh = tex_extents

        if self._dash == DashStyle.DASH:
            paint.setPathEffect(skia.DashPathEffect.Make([15, 5], 0))
        elif self._dash == DashStyle.DOT:
            paint.setPathEffect(skia.DashPathEffect.Make([2, 5], 0))
        elif self._dash == DashStyle.DOT_DASH:
            paint.setPathEffect(skia.DashPathEffect.Make([15, 5, 2, 5], 0))

        self._store_line_slot(paint)
        self._is_line_paint_dirty = False
        return paint

    def _to_skia_fill_paint(self) -> skia.Paint:
        if not self._fill or self._fill is SPRITE_BODY:
            return None

        if isinstance(self._fill, ProceduralFill):
            return self._procedural_fill_paint()

        qhw = qhh = None
        if _material_needs_host_fit(self._fill):
            hw, hh = _local_half_extents(self)
            qhw, qhh = _quantize_extent(hw), _quantize_extent(hh)
            if self._tex_fill_hw != qhw or self._tex_fill_hh != qhh:
                self._cached_fill_paint = None
                self._cached_fill_bare = None
                self._cached_fill_fx = None
        hit = self._cached_fill_slot()
        if hit is not None and (qhw is None or (
            self._tex_fill_hw == qhw and self._tex_fill_hh == qhh
        )):
            return hit

        paint, got = self._material_paint(
            self._fill,
            AntiAlias=True,
            Style=skia.Paint.kFill_Style,
            BlendMode=_SKIA_BLEND_MAP[self._blend]
        )
        if got is not None:
            self._tex_fill_hw, self._tex_fill_hh = got

        self._store_fill_slot(paint)
        self._is_fill_paint_dirty = False
        return paint

    def _procedural_fill_paint(self) -> skia.Paint:
        """Cached paint shell; only the image-free shader is replaced per frame."""
        fill = self._fill
        shader_fn, center_radius, metal_light, uses_envelope = _proc_paint_helpers()
        try:
            kind = str(getattr(fill, "kind", getattr(fill, "_kind", "")))
            if uses_envelope(self):
                half = float(self._shield_envelope_half())
                cx = cy = 0.0
            else:
                cx, cy, half = center_radius(self)
            if kind == "metal":
                rv = getattr(self, "_rotation_value", None)
                rot = float(rv()) if callable(rv) else 0.0
                shader = shader_fn(
                    fill, cx, cy, half,
                    rot_deg=rot, light_deg=metal_light(),
                )
            else:
                shader = shader_fn(fill, 0.0, 0.0, half)
        except AttributeError:
            raise
        except Exception:
            fill._tick()
            shader = fill._skia_shader
        fx = self._fill_filter
        if not self._is_fill_paint_dirty:
            if fx is None and self._cached_proc_bare is not None:
                self._cached_proc_bare.setShader(shader)
                return self._cached_proc_bare
            if (
                fx is not None
                and fx is self._cached_proc_fx
                and self._cached_proc_paint is not None
            ):
                self._cached_proc_paint.setShader(shader)
                return self._cached_proc_paint
        paint = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kFill_Style,
            BlendMode=_SKIA_BLEND_MAP[self._blend],
            Shader=shader,
        )
        if fx is None:
            self._cached_proc_bare = paint
        else:
            paint.setImageFilter(fx._skia_filter)
            self._cached_proc_paint = paint
            self._cached_proc_fx = fx
        self._is_fill_paint_dirty = False
        return paint


# Paint writes on a destroyed actor raise ``DestroyedError``, like
# ``set_color`` already did: one table, one wrap (graphics review HP9). Living
# actors pay one attribute lookup per paint write; reads stay legal.
_PAINT_WRITE_PROPERTIES = (
    "color", "fill", "line", "line_width", "dash", "line_cap", "line_join", "blend",
    "line_filter", "fill_filter", "visual", "glow", "shadow", "hue", "gray", "tail",
)
_PAINT_WRITE_METHODS = ("set_alpha", "look_like", "restore_visual")


def _refuse_on_dead(fn, what: str):
    def checked(self, *args, **kwargs):
        if probe_private(self, "_destroyed", False):
            from .entity import _refuse_if_destroyed
            _refuse_if_destroyed(self, what)
        try:
            return fn(self, *args, **kwargs)
        finally:
            # Every paint write moves the look revision: the cached cull box
            # keys on it (Canvas Design, "Offscreen culling", the cache).
            d = getattr(self, "__dict__", None)
            if d is not None:
                d["_look_rev"] = d.get("_look_rev", 0) + 1
    checked.__name__, checked.__qualname__, checked.__doc__ = fn.__name__, fn.__qualname__, fn.__doc__
    return checked


for _name in _PAINT_WRITE_PROPERTIES:
    _prop = PaintState.__dict__[_name]
    setattr(PaintState, _name, _prop.setter(_refuse_on_dead(_prop.fset, _name)))
for _name in _PAINT_WRITE_METHODS:
    setattr(PaintState, _name, _refuse_on_dead(PaintState.__dict__[_name], _name))
del _name, _prop


def _proc_paint_helpers():
    """One-time imports for the procedural fill paint path."""
    cached = getattr(_proc_paint_helpers, "_fns", None)
    if cached is None:
        from .recipes import _procedural_shader, _center_radius, get_metal_light
        from .sprite import _uses_shield_envelope
        cached = (
            _procedural_shader, _center_radius, get_metal_light, _uses_shield_envelope,
        )
        _proc_paint_helpers._fns = cached
    return cached


class Gradient(ClosedSurface):
    """Paint material: a color ramp in the shape's local space (or the wallpaper frame).

    Omitted ``size`` fits the host (last stop at the rim). A number is design
    units — LINEAR half-span from the center, RADIAL radius. ``SWEEP`` ignores size.

    Tone helpers: ``mean_color()``, ``darker(n)``, ``lighter(n)`` (stop-wise;
    return a new ``Gradient``). On area shapes, ``visual = Gradient(...)`` /
    ``set_color(Gradient(...))`` also stroke ``mean_color().darker(0.2)`` without
    changing ``line_width``.
    """

    def __init__(self,
                 *stops: Union['Color', str, Tuple[float, ...], Tuple[float, Union['Color', str, Tuple[float, ...]]]],
                 type: Union[GradientType, str] = GradientType.LINEAR,
                 size: Optional[float] = None,
                 angle: float = 0.0):
        """
        Initialize gradient with:
        1. Multiple colors: gradient will transition through all colors evenly
        2. Single color: creates a gradient from darker to lighter version
        3. Color positions: [(pos, color), ...] for precise control
        4. Preset name: uses predefined gradient

        Args:
            *stops: colors (names, RGB(A) tuples, ``Color``), ``(position, color)``
                pairs, or one preset name (``"sunset"``)
            type: ``"linear"`` (default), ``"radial"`` or ``"sweep"`` (or ``GradientType``)
            size: Design-unit extent, or None to fit the host / wallpaper frame
            angle: Angle for linear and sweep gradients (degrees)
        """
        args = as_payload_all(*stops)
        if size is not None:
            from .validate import magnitude, fixed_magnitude
            from .validate import fixed_magnitude
            size = fixed_magnitude(size, "Gradient size", positive=True)
        self._type = coerce_enum(type, GradientType, what="Gradient type")
        self._size = size
        from .validate import number
        self._angle = number(angle, "Gradient angle")
        self._shader = None

        # Handle no colors case
        if not args:
            # Use RdYl preset if no colors provided
            preset_colors = self._get_preset_colors('rdyl')
            self._positions = [pos for pos, _ in preset_colors]
            self._colors = [Color(color) for _, color in preset_colors]
            self._update_shader()
            return

        # Check if first argument is a preset name
        if len(args) == 1 and isinstance(args[0], str):
            preset_name = args[0].lower()
            if preset_name in self._get_presets():
                preset_colors = self._get_preset_colors(preset_name)
                self._positions = [pos for pos, _ in preset_colors]
                self._colors = [Color(color) for _, color in preset_colors]
                self._update_shader()
                return

        # Process input arguments
        colors = []
        positions = []
        has_positions = False

        # Check if arguments are position-color pairs
        if all(isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[0], (int, float))
               for arg in args):
            has_positions = True
            # First verify positions are in ascending order
            positions_only = [arg[0] for arg in args]
            if not all(positions_only[i] <= positions_only[i+1] for i in range(len(positions_only)-1)):
                raise ValueError("Gradient positions must be in ascending order")

            for pos, color in args:
                if not 0.0 <= pos <= 1.0:
                    raise ValueError(f"Position must be between 0 and 1, got {pos}")
                positions.append(float(pos))
                colors.append(Color(color))

        # If not position-color pairs, treat as colors
        if not has_positions:
            colors = [Color(arg) for arg in args]
            if len(colors) == 1:
                # Single color case - create gradient from darker to lighter
                base_color = colors[0]
                colors = [base_color.darker(0.3), base_color.lighter(0.2)]
                positions = [0.0, 1.0]
            else:
                # Multiple colors - distribute evenly
                positions = [i / (len(colors) - 1) for i in range(len(colors))]

        self._colors = colors
        self._positions = positions
        self._update_shader()

    def set_alpha(self, alpha: float) -> 'Gradient':
        """Updates the gradient's colors with new alpha values."""
        from .validate import alpha01
        alpha = alpha01(alpha, "Gradient.set_alpha")
        # Check if any color's alpha is different from the requested alpha
        if all(abs(color.alpha - alpha) < 1e-6 for color in self._colors):
            return self  # No change needed

        # New stop colours: a stop may be the author's own Color (immutable).
        self._colors = [color.with_alpha(alpha) for color in self._colors]

        self._update_shader()
        return self

    def _get_presets(self) -> dict:
        """Shared gradient preset table (see ``scena.gradient_presets``)."""
        from .gradient_presets import GRADIENT_PRESETS
        return GRADIENT_PRESETS

    def _get_preset_colors(self, preset: str) -> List[Tuple[float, Tuple[float, float, float]]]:
        """Get colors for a preset gradient"""
        from .gradient_presets import get_preset, normalize_preset_name
        key = normalize_preset_name(preset)
        stops = get_preset(key)
        if stops is None:
            from .gradient_presets import preset_names
            from .validate import did_you_mean
            names = list(preset_names())
            raise ValueError(
                f"Invalid preset name: {preset!r}.{did_you_mean(preset, names)} "
                f"See the {len(names)} presets in the Guia (Cor / Gradient / Texture)."
            )
        return stops

    def _update_shader(self) -> None:
        """Bake the stop list into a Skia shader. Geometry: absolute size, or unit for auto-fit."""
        if not self._colors:
            return

        colors = [skia.Color4f(*color.rgb) for color in self._colors]
        positions = self._positions
        span = 1.0 if self._size is None else float(self._size)

        if self._type == GradientType.LINEAR:
            rad = math.radians(self._angle)
            dx = math.cos(rad)
            dy = math.sin(rad)
            points = [(-dx * span, -dy * span), (dx * span, dy * span)]
            self._shader = skia.GradientShader.MakeLinear(
                points=points,
                colors=colors,
                positions=positions
            )
        elif self._type == GradientType.RADIAL:
            self._shader = skia.GradientShader.MakeRadial(
                center=(0, 0),
                radius=span,
                colors=colors,
                positions=positions
            )
        elif self._type == GradientType.SWEEP:
            # angle rotates the rainbow (startAngle degrees) — required for Iridescent.
            self._shader = skia.GradientShader.MakeSweep(
                cx=0, cy=0,
                colors=colors,
                positions=positions,
                startAngle=float(self._angle),
                endAngle=float(self._angle) + 360.0,
            )

    @property
    def type(self) -> str:
        """Ramp kind: ``"linear"``, ``"radial"``, or ``"sweep"``."""
        return self._type.value

    @property
    def size(self) -> Optional[float]:
        """Design-unit extent, or None when the ramp fits the host."""
        return self._size

    @property
    def _needs_host_fit(self) -> bool:
        return self._size is None and self._type != GradientType.SWEEP

    def _shader_for_scale(self, scale: float) -> skia.Shader:
        """Unit auto-fit shader scaled to design units (cached on the shape paint)."""
        shader = self._shader
        if shader is None:
            return None
        s = max(float(scale), 1e-6)
        if abs(s - 1.0) <= 1e-9:
            return shader
        m = skia.Matrix()
        m.setScale(s, s)
        if hasattr(shader, "makeWithLocalMatrix"):
            return shader.makeWithLocalMatrix(m)
        return shader

    @property
    def _skia_shader(self) -> skia.Shader:
        return self._shader

    def mean_color(self) -> Color:
        """Weighted mean of stops along the ramp (piecewise-linear RGB integral)."""
        colors = self._colors
        positions = self._positions
        n = len(colors)
        if n == 0:
            return Color(0.0, 0.0, 0.0, 1.0)
        if n == 1:
            r, g, b, a = colors[0].rgb
            return Color(r, g, b, a)
        total_r = total_g = total_b = total_a = 0.0
        total_w = 0.0
        for i in range(n - 1):
            p0 = float(positions[i])
            p1 = float(positions[i + 1])
            span = p1 - p0
            if span <= 0.0:
                continue
            c0 = colors[i].rgb
            c1 = colors[i + 1].rgb
            half = 0.5 * span
            total_r += half * (c0[0] + c1[0])
            total_g += half * (c0[1] + c1[1])
            total_b += half * (c0[2] + c1[2])
            total_a += half * (c0[3] + c1[3])
            total_w += span
        if total_w <= 1e-12:
            r = sum(c.rgb[0] for c in colors) / n
            g = sum(c.rgb[1] for c in colors) / n
            b = sum(c.rgb[2] for c in colors) / n
            a = sum(c.rgb[3] for c in colors) / n
            return Color(r, g, b, a)
        inv = 1.0 / total_w
        return Color(total_r * inv, total_g * inv, total_b * inv, total_a * inv)

    def darker(self, amount: float = 0.1) -> "Gradient":
        """New gradient with each stop darkened (same positions / type / size / angle)."""
        return self._map_stops(lambda c: c.darker(amount))

    def lighter(self, amount: float = 0.1) -> "Gradient":
        """New gradient with each stop lightened (same positions / type / size / angle)."""
        return self._map_stops(lambda c: c.lighter(amount))

    def _map_stops(self, fn) -> "Gradient":
        pairs = [(float(p), fn(c)) for p, c in zip(self._positions, self._colors)]
        return Gradient(*pairs, type=self._type, size=self._size, angle=self._angle)


def _coerce_texture_shift(shift):
    """``Texture(shift=)``: HueShift (static) or Recolor only."""
    if shift is None:
        return None
    from .visuals import HueShift
    from .recipes import Recolor
    if isinstance(shift, HueShift):
        if getattr(shift, "live", False):
            raise TypeError(
                "Texture(shift=) does not accept HueShift(live=True) — "
                "live hue is Sprite-only. Use HueShift(amount=...) or HueShift(to=...)."
            )
        return shift
    if isinstance(shift, Recolor):
        return shift
    raise TypeError(
        f"Texture(shift=) expected HueShift or Recolor, got {type(shift).__name__}."
    )


class Texture(ClosedSurface):
    """Image fill for shapes: cover the local AABB or a tiled cell.

    Assign to ``.fill`` / ``.line`` (author path). ``color=`` is a proxy hue
    for looks that sample host RGB — it does not tint the bitmap. Omitted
    ``color`` is the mean of opaque pixels (once, at construct).
    ``shift=`` is a pixel transform (``HueShift`` / ``Recolor``) on the bitmap.

    Args:
        source: Image file name, or an image object (``skia.Image``).
        filename: Instead of ``source``: a path.
        image: Instead of ``source``: an already loaded ``skia.Image``.
        fit: ``"cover"`` (default) · ``"contain"`` · ``"stretch"`` · ``"tile"``.
        tile_mode: Outside the image: ``"clamp"`` · ``"repeat"`` · ``"mirror"`` ·
            ``"decal"`` (default ``"repeat"`` when tiling, else ``"decal"``).
        scale: Extra zoom on the image (> 0; default 1).
        tile_size: With ``fit="tile"``: tile width, or ``(w, h)``, in design units.
        angle: Image rotation in degrees.
        color: Proxy color for looks that need a hue (not a multiply on the image).
        shift: ``HueShift(...)`` or ``Recolor(...)`` applied to the pixels.
    """

    def __init__(
        self,
        source: Union[str, skia.Image, None] = None,
        *,
        filename: str = None,
        image: skia.Image = None,
        fit: Union[BackgroundFit, str] = BackgroundFit.COVER,
        tile_mode: Optional[TileMode] = None,
        scale: float = 1.0,
        tile_size: Union[float, Tuple[float, float], None] = None,
        angle: float = 0.0,
        color=None,
        shift=None,
    ):
        source = as_payload(source)
        if isinstance(source, str):
            filename = source
        elif source is not None:
            image = source

        fit_val = coerce_enum(fit, BackgroundFit, what="fit")
        self._fit = fit_val
        if tile_mode is None:
            tm = TileMode.REPEAT if fit_val == BackgroundFit.TILE else TileMode.DECAL
        else:
            tm = coerce_enum(tile_mode, TileMode, what="tile_mode")
        if fit_val == BackgroundFit.TILE and tm == TileMode.CLAMP:
            tm = TileMode.REPEAT
        self._tile_mode = tm
        self._scale = _positive_scale(scale)
        self._tile_size = _parse_tile_size(tile_size, fit_val)
        from .validate import number
        self._angle = number(angle, "Texture angle")
        self._alpha = 1.0
        self._filename = filename
        self._fit_shaders = {}
        self._shader = None
        self._shift = _coerce_texture_shift(shift)

        if image is not None:
            if not hasattr(image, "isLazyGenerated"):
                raise TypeError(
                    f"image= expected a skia.Image, got {type(image).__name__}. "
                    f"Pass a file name instead: filename=\"sky.png\"."
                )
            self._image = image
        elif filename is not None:
            self._image = _load_image(filename, kind="texture")
        else:
            self._image = _make_fallback_image()

        if color is not None:
            self._color = color if isinstance(color, Color) else Color(color)
        else:
            self._color = _image_mean_opaque_color(self._image)

        if fit_val == BackgroundFit.TILE:
            self._shader = self._bake_tile_shader()

    def _bake_tile_shader(self) -> skia.Shader:
        img = self._image
        m = _shape_tile_local_matrix(
            image_width=img.width(),
            image_height=img.height(),
            tile_size=self._tile_size,
            scale=self._scale,
            angle=self._angle,
        )
        return _make_image_shader(img, self._tile_mode, m)

    def set_alpha(self, alpha: float) -> 'Texture':
        """Fade the whole image: ``alpha`` 0 (invisible) … 1 (opaque). Returns this Texture."""
        from .validate import alpha01
        a = alpha01(alpha, "Texture.set_alpha")
        if abs(self._alpha - a) < 1e-6:
            return self
        self._alpha = a
        return self

    def _shader_for_local(self, hw: float, hh: float) -> skia.Shader:
        """Cover/contain/stretch shader for a host AABB (cached by quantized size)."""
        qhw = _quantize_extent(hw)
        qhh = _quantize_extent(hh)
        key = (qhw, qhh)
        cached = self._fit_shaders.get(key)
        if cached is not None:
            return cached
        img = self._image
        m = _shape_fit_local_matrix(
            fit=self._fit,
            hw=qhw,
            hh=qhh,
            image_width=img.width(),
            image_height=img.height(),
            scale=self._scale,
            angle=self._angle,
        )
        shader = _make_image_shader(img, self._tile_mode, m)
        self._fit_shaders[key] = shader
        return shader

    @property
    def _needs_host_fit(self) -> bool:
        return self._fit != BackgroundFit.TILE

    @property
    def _skia_shader(self) -> skia.Shader:
        if self._shader is not None:
            return self._shader
        # Sprite fallback (wallpaper / stroke without extents): 48 DU box.
        return self._shader_for_local(24.0, 24.0)

    @property
    def image(self) -> skia.Image:
        """The loaded picture (a ``skia.Image``; the checkerboard when the file is missing). Read-only."""
        return self._image

    @property
    def fit(self) -> str:
        """How the image fills the shape: ``"cover"`` · ``"contain"`` · ``"stretch"`` · ``"tile"``. Read-only."""
        return self._fit.value

    @property
    def tile_mode(self) -> str:
        """Edge behavior outside the image: ``"clamp"`` · ``"repeat"`` · ``"mirror"`` · ``"decal"``. Read-only."""
        return self._tile_mode.value

    @property
    def scale(self) -> float:
        """Extra zoom on the image (1 = as fitted). Read-only."""
        return self._scale

    @property
    def tile_size(self) -> Optional[Union[float, Tuple[float, float]]]:
        """Tile width, or ``(w, h)``, in design units when ``fit="tile"``; else ``None``. Read-only."""
        return self._tile_size

    @property
    def angle(self) -> float:
        """Image rotation in degrees. Read-only."""
        return self._angle

    @property
    def alpha(self) -> float:
        """Current image opacity, 0 … 1. Change it with ``set_alpha``."""
        return self._alpha

    @property
    def color(self) -> Color:
        """Proxy color for looks that need a hue (not a multiply on the image)."""
        return self._color

    @property
    def shift(self):
        """Optional ``HueShift`` / ``Recolor`` pixel transform (construct-time)."""
        return self._shift

    @property
    def _shift_color_filter(self):
        """Skia ColorFilter for ``shift=``, or ``None``."""
        s = self._shift
        if s is None:
            return None
        return getattr(s, "_color_filter", None)

    @property
    def filename(self) -> Optional[str]:
        """The file this Texture was loaded from, or ``None`` for an in-memory image."""
        return self._filename


# Kinds that accept optional recolor via u_color half3.
_COLORABLE_FILL_KINDS = frozenset({
    "wave", "aurora", "sphere", "ink_wash", "ink_bleed",
    "shield_bands", "shield_cloud", "shield_vortex",
})

# Default design-space diameter for UV mapping when host bounds are unknown.
# Scena shapes paint origin-centered (local CTM); shaders use
# ``uv = 0.5 + coord / u_resolution``. ~96 units ≈ radius ~48 — typical lab sizes.
_PROC_FILL_RES = 96.0


def _resolve_fill_color(color, default=(0.25, 0.75, 0.95)) -> Tuple[float, float, float]:
    """RGB 0–1 for procedural fill tint (no alpha)."""
    return resolve_rgb(color, default)


class ProceduralFill:
    """Curated animated fill (RuntimeEffect shader). Authors never write SkSL.

    Use factories: ``WaterFill()``, ``FlameFill()``, ``WaveFill()``,
    ``AuroraFill()``, ``SwellFill()``.
    Zero-arg constructors look good; ``tick()`` updates time uniforms.

    Args:
        kind: Shader name (``"water_side"``, ``"fire"``, ``"aurora"``, …). Prefer the
            factories (``WaterFill()`` …).
        amount: Intensity (0 = off, 1 = default).
        speed: Animation speed multiplier.
        seed: Noise seed.
        color: Tint for the kinds that take one (``WaveFill`` / ``AuroraFill``).
    """

    __slots__ = (
        '_kind', '_amount', '_speed', '_seed', '_color',
        '_builder', '_shader', '_proc_tick_t',
        '_extra_rgb',  # optional name→rgb map for multi-stop shields
    )

    def __init__(
        self,
        kind: str = "water_side",
        amount: float = 1.0,
        speed: float = 1.0,
        seed: float = 0.0,
        color=None,
    ):
        from ._sksl_shape import procedural_builder, PROCEDURAL_FILL_KINDS
        self._kind = expect_choice(kind, PROCEDURAL_FILL_KINDS, what="ProceduralFill kind")
        from .validate import number
        self._amount = number(amount, "ProceduralFill amount")
        self._speed = number(speed, "ProceduralFill speed")
        self._seed = number(seed, "ProceduralFill seed")
        self._color = _resolve_fill_color(color) if color is not None else None
        self._extra_rgb = None
        if self._color is None and self._kind in _COLORABLE_FILL_KINDS:
            defaults = {
                "wave": (0.15, 0.55, 0.85),
                "aurora": (0.25, 0.9, 0.55),
                "sphere": (0.35, 0.55, 0.85),
                "ink_wash": (0.18, 0.2, 0.32),
                "ink_bleed": (0.15, 0.12, 0.22),
                "shield_bands": (0.08, 0.55, 0.52),
                "shield_cloud": (0.45, 0.95, 0.25),
                "shield_vortex": (1.0, 0.3, 0.75),
            }
            self._color = defaults.get(self._kind, (0.3, 0.7, 0.95))
        self._builder = procedural_builder(self._kind)
        self._shader = None
        self._proc_tick_t = None
        self._tick(t=0.0)

    def _tick(self, t: Optional[float] = None) -> None:
        """Update time uniforms and rebuild shader (local-origin UV map).

        Fixed ``_PROC_FILL_RES`` diameter — draw uses ``_procedural_shader`` with
        host half-extent instead. Still writes multi-stop ``_extra_rgb`` palettes
        so a last-resort fallback does not zero nebula/cracks uniforms.
        """
        if t is None:
            try:
                from .orchestration import ScenaFramework
                fw = ScenaFramework.get_instance()
                t = float(getattr(fw.clock, "time", 0.0) or 0.0)
            except Exception:
                t = 0.0
        b = self._builder
        res = _PROC_FILL_RES
        b.setUniform("u_time", float(t) * self._speed)
        b.setUniform("u_amount", self._amount)
        b.setUniform("u_seed", self._seed)
        # Design-space diameter; colorable SkSL uses origin-centered paint coords.
        b.setUniform("u_resolution", [res, res])
        if self._kind in _COLORABLE_FILL_KINDS and self._color is not None:
            try:
                b.setUniform("u_color", list(self._color[:3]))
            except Exception:
                pass
        # Multi-stop shield palettes (same keys as recipes._procedural_shader).
        if self._kind in ("shield_stars", "shield_nebula_mist"):
            try:
                extra = self._extra_rgb or {}
                for name, default in (
                    ("u_deep", (0.12, 0.02, 0.28)),
                    ("u_mid", (0.45, 0.1, 0.65)),
                    ("u_star", (1.0, 0.35, 0.85)),
                    ("u_shell", (0.35, 0.95, 1.0)),
                ):
                    rgb = extra.get(name[2:], default)
                    b.setUniform(name, list(rgb[:3]))
            except Exception:
                pass
        if self._kind == "shield_bubble":
            try:
                from .recipes import Shield
                extra = self._extra_rgb or Shield._BUBBLE_PALETTE
                for name in ("u_lime", "u_yell", "u_film"):
                    b.setUniform(name, list(extra[name[2:]][:3]))
            except Exception:
                pass
        if self._kind == "shield_cracks":
            try:
                from .recipes import _CRACKS_UNIFORMS
                extra = self._extra_rgb or {}
                for name, default in _CRACKS_UNIFORMS:
                    b.setUniform(name, list(extra.get(name[2:], default)[:3]))
            except Exception:
                pass
        if self._kind == "metal":
            # Defaults; Metal visual overwrites per draw for world-locked light when multipass.
            try:
                b.setUniform("u_rot", 0.0)
                b.setUniform("u_origin", [0.0, 0.0])
                b.setUniform("u_light", 28.0)
                from .recipes import _metal_tint
                b.setUniform("u_tint", _metal_tint(self))
            except Exception:
                pass
        self._shader = b.makeShader()

    def set_alpha(self, alpha: float) -> "ProceduralFill":
        """Accepted so ``shape.set_alpha`` works on any fill; a procedural shader keeps
        its own alpha, so this changes nothing. Returns this fill.
        """
        from .validate import alpha01
        alpha01(alpha, "ProceduralFill.set_alpha")   # validated; the shader owns its alpha
        return self

    @property
    def _skia_shader(self) -> skia.Shader:
        if self._shader is None:
            self._tick(0.0)
        return self._shader

    @property
    def kind(self) -> str:
        """Which shader this is (``"water_side"``, ``"fire"``, ``"aurora"``, …). Read-only."""
        return self._kind

    @property
    def color(self) -> Optional[Tuple[float, float, float]]:
        """The tint as ``(r, g, b)`` 0–1, or ``None`` for the kind's own colors. Read-only."""
        return self._color

    @property
    def amount(self) -> float:
        """Intensity (0 = off, 1 = default). Writable."""
        return self._amount

    @amount.setter
    def amount(self, value: float) -> None:
        from .validate import fixed_magnitude
        self._amount = fixed_magnitude(value, "ProceduralFill amount")

    @property
    def speed(self) -> float:
        """Animation speed multiplier (1 = default). Writable."""
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        from .validate import number
        self._speed = number(value, "ProceduralFill speed")


def WaterFill(kind: str = "side", amount: float = 1.0, speed: float = 1.0):
    """Procedural water fill (``shape.fill = WaterFill()``).

    Args:
        kind: ``"side"`` (platform seen from the side, surface on top) or
            ``"top"`` (a lake seen from above).
        amount: intensity (0 = off, 1 = default).
        speed: animation speed multiplier.
    """
    k = expect_choice(kind, ("side", "top"), what="WaterFill kind")
    mapped = "water_top" if k == "top" else "water_side"
    return ProceduralFill(kind=mapped, amount=amount, speed=speed)


def FlameFill(amount: float = 1.0, speed: float = 1.2):
    """Procedural fire rising inside the shape (``shape.fill = FlameFill()``).

    Args:
        amount: intensity (0 = off, 1 = default).
        speed: animation speed multiplier.
    """
    return ProceduralFill(kind="fire", amount=amount, speed=speed)


def SwellFill(amount: float = 1.0, speed: float = 1.0):
    """Abstract flow-field fill (not side-view water).

    Args:
        amount: intensity (0 = off, 1 = default).
        speed: animation speed multiplier.
    """
    return ProceduralFill(kind="swell", amount=amount, speed=speed)


def WaveFill(color=None, amount: float = 1.0, speed: float = 1.0):
    """Recolorable liquid volume field (any tint). Not the free-surface ``Water`` look.

    Args:
        color: tint (any color form; default: the look's own).
        amount: intensity (0 = off, 1 = default).
        speed: animation speed multiplier.
    """
    return ProceduralFill(kind="wave", amount=amount, speed=speed, color=color)


def AuroraFill(color=None, amount: float = 1.0, speed: float = 0.9):
    """Vertical aurora ribbon field (any tint).

    Args:
        color: tint (any color form; default: the look's own).
        amount: intensity (0 = off, 1 = default).
        speed: animation speed multiplier.
    """
    return ProceduralFill(kind="aurora", amount=amount, speed=speed, color=color)


def _parse_tile_size(value, fit=None) -> Optional[Union[float, Tuple[float, float]]]:
    """Validate ``tile_size``: ``None``, a positive width, or ``(w, h)`` in design units.

    Only ``fit="tile"`` has tiles: with another fit the knob would change
    nothing, so it raises (KN4, 2026-10-12; before, it was taken and ignored).
    """
    value = as_payload(value)
    if value is None:
        return None
    if fit is not None and fit != BackgroundFit.TILE:
        raise TypeError(
            f'tile_size= sizes the tiles of fit="tile"; with fit="{fit.value}" '
            f'it changes nothing. Write fit="tile", tile_size=…, or drop tile_size.'
        )
    if isinstance(value, (int, float)):
        w = float(value)
        if w <= 0.0:
            raise ValueError("tile_size must be > 0")
        return w
    if isinstance(value, (tuple, list)) and len(value) == 2:
        tw, th = float(as_payload(value[0])), float(as_payload(value[1]))
        if tw <= 0.0 or th <= 0.0:
            raise ValueError("tile_size must be > 0")
        return (tw, th)
    raise TypeError("tile_size must be a positive number, (w, h), or None")


def _positive_scale(value, *, what: str = "scale") -> float:
    """Unitless zoom; must be ``> 0`` (same contract as ``Gradient.size``)."""
    from .validate import fixed_magnitude
    return fixed_magnitude(value, what, positive=True)


def _resolve_tile_size_du(
    tile_size,
    *,
    image_width: int,
    image_height: int,
    design_width: float,
    design_height: float,
) -> Tuple[float, float]:
    """Cell size in design units (width, height). ``None`` → 1/4 of the short design side."""
    iw = max(int(image_width), 1)
    ih = max(int(image_height), 1)
    aspect = ih / iw
    dw = max(float(design_width), 1e-6)
    dh = max(float(design_height), 1e-6)
    if tile_size is None:
        w_du = 0.25 * min(dw, dh)
        return (w_du, w_du * aspect)
    if isinstance(tile_size, (tuple, list)) and len(tile_size) == 2:
        return (float(tile_size[0]), float(tile_size[1]))
    w_du = float(tile_size)
    return (w_du, w_du * aspect)


def _tile_matrix_components(
    *,
    image_width: int,
    image_height: int,
    tile_size,
    scale: float,
    fb_width: float,
    fb_height: float,
    design_width: float,
    design_height: float,
    rest_x: Optional[float] = None,
    rest_y: Optional[float] = None,
) -> Tuple[float, float, float, float]:
    """Image→FB ``(sx, sy, tx, ty)`` for ``fit=tile``.

    Period is ``tile_size`` design units (times unitless ``scale``), independent
    of bitmap resolution. Phase puts a cell corner on world ``(0, 0)`` with the
    bitmap upright (image top toward +design Y). ``rest`` is the camera look-at
    at identity (FB center), same convention as :func:`~scena.background.parallax_transform`.
    """
    iw = max(int(image_width), 1)
    ih = max(int(image_height), 1)
    dw = max(float(design_width), 1e-6)
    dh = max(float(design_height), 1e-6)
    fw = float(fb_width)
    fh = float(fb_height)
    user_scale = float(scale) if float(scale) > 0.0 else 1.0
    tile_w_du, tile_h_du = _resolve_tile_size_du(
        tile_size, image_width=iw, image_height=ih,
        design_width=dw, design_height=dh,
    )
    fb_x_per_du = fw / dw
    fb_y_per_du = fh / dh
    tile_w_fb = tile_w_du * user_scale * fb_x_per_du
    tile_h_fb = tile_h_du * user_scale * fb_y_per_du
    sx = tile_w_fb / iw
    sy = tile_h_fb / ih
    rx = dw * 0.5 if rest_x is None else float(rest_x)
    ry = dh * 0.5 if rest_y is None else float(rest_y)
    # World (0, 0) at identity: look-at ``rest`` sits at FB center; y-up → y-down.
    fx0 = fw * 0.5 - rx * fb_x_per_du
    fy0 = fh * 0.5 + ry * fb_y_per_du
    tx = fx0
    ty = fy0 - tile_h_fb
    return (sx, sy, tx, ty)


def _tile_local_matrix(
    *,
    image_width: int,
    image_height: int,
    tile_size,
    scale: float,
    fb_width: float,
    fb_height: float,
    design_width: float,
    design_height: float,
    rest_x: Optional[float] = None,
    rest_y: Optional[float] = None,
) -> skia.Matrix:
    """Skia localMatrix for a tiled background image (image → framebuffer)."""
    sx, sy, tx, ty = _tile_matrix_components(
        image_width=image_width,
        image_height=image_height,
        tile_size=tile_size,
        scale=scale,
        fb_width=fb_width,
        fb_height=fb_height,
        design_width=design_width,
        design_height=design_height,
        rest_x=rest_x,
        rest_y=rest_y,
    )
    m = skia.Matrix()
    m.setScale(sx, sy)
    m.postTranslate(tx, ty)
    return m


def _make_fallback_image() -> skia.Image:
    info = skia.ImageInfo.Make(128, 128, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surface = skia.Surface.MakeRaster(info)
    c = surface.getCanvas()
    yellow = skia.Paint(Color=skia.ColorYELLOW)
    dark = skia.Paint(Color=0xFF202000)
    for i in range(4):
        for j in range(4):
            c.drawRect(
                skia.Rect.MakeXYWH(i * 32, j * 32, 32, 32),
                yellow if (i + j) % 2 == 0 else dark,
            )
    return surface.makeImageSnapshot()


def _load_image(filename: str, *, kind: str = "image") -> skia.Image:
    """Decode ``filename`` once (shared GPU texture). Fallback checker on failure.

    Paths resolve via ``scena.sprite._resolve_image_path`` (absolute, script
    dir, ``media/`` next to the script, then cwd — not recursive).
    """
    if not isinstance(filename, (str, os.PathLike)):
        # Checked before the cache lookup: a list leaked "unhashable type".
        raise TypeError(f"{kind} expected a file name, got {type(filename).__name__} {filename!r:.30}")
    try:
        from .sprite import _resolve_image_path
        resolved = _resolve_image_path(filename)
        path = resolved if resolved is not None else filename
        key = os.path.abspath(path)
        hit = _IMAGE_CACHE.get(key)
        if hit is not None:
            return hit
        if not os.path.exists(path):
            raise FileNotFoundError(f"{kind} file not found: {filename}")
        img = skia.Image.open(path)
        if img is None:
            raise ValueError(f"Failed to load {kind}: {filename}")
        _IMAGE_CACHE[key] = img
        _pinnable(img)
        return img
    except Exception as e:
        key = filename
        if key not in _MISSING_WARNED:
            _MISSING_WARNED.add(key)
            warnings.warn(
                f"Failed to load {kind} from {filename}: {e}. "
                "Using yellow checkerboard pattern.",
                RuntimeWarning,
                stacklevel=2,
            )
        return _make_fallback_image()


def _image_mean_opaque_color(image: skia.Image) -> Color:
    """Mean RGB of opaque pixels (downscaled). Cached per ``skia.Image`` identity."""
    fallback = Color(*_TEXTURE_COLOR_FALLBACK)
    if image is None:
        return fallback
    key = id(image)
    hit = _IMAGE_MEAN_CACHE.get(key)
    if hit is not None:
        return Color(*hit)
    try:
        iw = max(int(image.width()), 1)
        ih = max(int(image.height()), 1)
        side = max(iw, ih)
        s = min(1.0, _MEAN_THUMB_SIDE / float(side))
        tw = max(1, int(round(iw * s)))
        th = max(1, int(round(ih * s)))
        info = skia.ImageInfo.Make(
            tw, th, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
        )
        surf = skia.Surface.MakeRaster(info)
        if surf is None:
            _IMAGE_MEAN_CACHE[key] = _TEXTURE_COLOR_FALLBACK
            return fallback
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorTRANSPARENT)
        canvas.drawImageRect(
            image,
            skia.Rect.MakeWH(float(tw), float(th)),
            _IMAGE_SAMPLING,
        )
        arr = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        if arr is None or arr.size < 4:
            _IMAGE_MEAN_CACHE[key] = _TEXTURE_COLOR_FALLBACK
            return fallback
        pixels = arr.reshape(-1, arr.shape[-1])
        a = pixels[:, 3].astype(np.float64)
        opaque = a >= float(_MEAN_MIN_ALPHA)
        if not np.any(opaque):
            _IMAGE_MEAN_CACHE[key] = _TEXTURE_COLOR_FALLBACK
            return fallback
        rgb = pixels[opaque, :3].astype(np.float64)
        mean = rgb.mean(axis=0) / 255.0
        rgba = (float(mean[0]), float(mean[1]), float(mean[2]), 1.0)
        _IMAGE_MEAN_CACHE[key] = rgba
        return Color(*rgba)
    except Exception:
        _IMAGE_MEAN_CACHE[key] = _TEXTURE_COLOR_FALLBACK
        return fallback


def _make_image_shader(image: skia.Image, tile_mode: TileMode, local_matrix: skia.Matrix) -> skia.Shader:
    tm = _SKIA_TILE_MAP.get(tile_mode, skia.TileMode.kRepeat)
    try:
        return image.makeShader(tm, tm, _IMAGE_SAMPLING, local_matrix)
    except TypeError:
        return image.makeShader(tmx=tm, tmy=tm, localMatrix=local_matrix)


def _quantize_extent(value: float) -> float:
    return round(float(value) * 2.0) / 2.0


def _material_needs_host_fit(material) -> bool:
    return bool(getattr(material, "_needs_host_fit", False))


def _gradient_fit_scale(hw: float, hh: float, gradient: 'Gradient') -> float:
    """Host (or frame) half-extents → design-unit scale for an auto-fit Gradient."""
    gtype = getattr(gradient, "_type", GradientType.LINEAR)
    if gtype == GradientType.SWEEP:
        return 1.0
    hw = max(float(hw), 1e-6)
    hh = max(float(hh), 1e-6)
    if gtype == GradientType.RADIAL:
        return min(hw, hh)
    rad = math.radians(float(getattr(gradient, "_angle", 0.0) or 0.0))
    return abs(hw * math.cos(rad)) + abs(hh * math.sin(rad))


def _coerce_panel_material(value, *, what: str):
    """Widget panel ``background=``: ``None``, a color, ``Gradient`` or ``Texture``.

    Checked at construction so a bad value raises at the author's line, not on
    the first draw. ``ProceduralFill`` is refused: it animates per frame and a
    widget panel does not tick it.
    """
    value = as_payload(value)
    if value is None or isinstance(value, (Gradient, Texture)):
        return value
    if isinstance(value, ProceduralFill):
        raise TypeError(
            f"{what} takes a color, Gradient or Texture, got "
            f"{type(value).__name__}. Animated fills paint shapes only: "
            f"use a Gradient or Texture here."
        )
    from .validate import family_hint
    try:
        return Color(value)
    except (TypeError, ValueError) as exc:
        hint = family_hint(value)
        msg = (
            f"{what} takes a color, Gradient or Texture, got "
            f"{type(value).__name__} {value!r}. "
            f"Write background=\"navy\" or background=Gradient(\"red\", \"gold\")."
        )
        if hint:
            msg = f"{msg} {hint}"
        raise TypeError(msg) from exc


def _material_paint_for_rect(material, cx: float, cy: float, hw: float, hh: float) -> skia.Paint:
    """Paint a Gradient / Texture into a rect that is not a Shape host.

    Material shaders live in an origin-centered local frame (Shapes get it from
    their transform). Anything that draws a material straight in view or world
    coordinates — a widget panel — must go through here: fit the shader to the
    rect's half-extents like a Shape host, then move its origin to the rect
    center. Using ``material._skia_shader`` directly paints a solid end stop.
    """
    hw = max(float(hw), 1e-6)
    hh = max(float(hh), 1e-6)
    if isinstance(material, Gradient):
        if material._needs_host_fit:
            shader = material._shader_for_scale(_gradient_fit_scale(hw, hh, material))
        else:
            shader = material._skia_shader
    elif isinstance(material, Texture):
        shader = material._shader_for_local(hw, hh) if material._needs_host_fit else material._skia_shader
    else:
        raise TypeError(
            f"_material_paint_for_rect expected Gradient or Texture, got {type(material).__name__}"
        )
    shader = shader.makeWithLocalMatrix(skia.Matrix.Translate(float(cx), float(cy)))
    paint = skia.Paint(AntiAlias=True, Shader=shader)
    if isinstance(material, Texture):
        paint.setAlphaf(float(material.alpha))
        cf = material._shift_color_filter
        if cf is not None:
            paint.setColorFilter(cf)
    return paint


def _paint_attr_float(v, default: float = 0.0, *, abs_value: bool = True) -> float:
    if v is None:
        return default
    try:
        raw = getattr(v, "_raw_value", None)
        if raw is not None:
            n = float(raw)
            return abs(n) if abs_value else n
    except Exception:
        pass
    try:
        val = getattr(v, "value", None)
        if val is not None and not callable(val):
            n = float(val)
            return abs(n) if abs_value else n
    except Exception:
        pass
    try:
        n = float(v)
        return abs(n) if abs_value else n
    except Exception:
        return default


def _local_half_extents(shape) -> Tuple[float, float]:
    """Origin-centered local AABB half-size (design units)."""
    if _kind(shape) == "Text":
        refresh = getattr(shape, "_refresh_layout", None)
        if callable(refresh):
            refresh()
        # Layout box is tight ink, origin-centered on draw.
        x1 = _paint_attr_float(getattr(shape, "_x1", None), 0.0, abs_value=False)
        x2 = _paint_attr_float(getattr(shape, "_x2", None), 0.0, abs_value=False)
        y1 = _paint_attr_float(getattr(shape, "_y1", None), 0.0, abs_value=False)
        y2 = _paint_attr_float(getattr(shape, "_y2", None), 0.0, abs_value=False)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        if w > 1e-6 and h > 1e-6:
            return (0.5 * w, 0.5 * h)

    # Defining geometry first: Line ``length`` and Square ``width``/``height``
    # are cold Derivates — reading them marks the host pull-live (off A1).
    segment = getattr(shape, "_segment_xy", None)
    if callable(segment):
        try:
            x1, y1, x2, y2 = segment()
            length = math.hypot(x2 - x1, y2 - y1)
            lw = _paint_attr_float(getattr(shape, "line_width", None), DEFAULT_LINE_WIDTH)
            return (max(length * 0.5, 1e-3), max(lw * 0.5, 1e-3))
        except Exception:
            pass
    # Shapes only (lazy Derivate hosts): Sprite's frame is scaled, not width/height.
    oriented = getattr(shape, "_oriented_frame", None)
    if callable(oriented) and getattr(shape, "_defining_part_names", None) is not None:
        try:
            _cx, _cy, w, h, _ang = oriented()
            w, h = abs(float(w)), abs(float(h))
            if w > 1e-6 and h > 1e-6:
                return (0.5 * w, 0.5 * h)
        except Exception:
            pass

    if _kind(shape) == "Line":
        length = _paint_attr_float(getattr(shape, "length", None), 0.0)
        if length < 1e-6:
            try:
                p1, p2 = getattr(shape, "p1", None), getattr(shape, "p2", None)
                x1 = _paint_attr_float(getattr(p1, "x", None), 0.0, abs_value=False)
                y1 = _paint_attr_float(getattr(p1, "y", None), 0.0, abs_value=False)
                x2 = _paint_attr_float(getattr(p2, "x", None), 0.0, abs_value=False)
                y2 = _paint_attr_float(getattr(p2, "y", None), 0.0, abs_value=False)
                length = math.hypot(x2 - x1, y2 - y1)
            except Exception:
                length = 48.0
        lw = _paint_attr_float(getattr(shape, "line_width", None), DEFAULT_LINE_WIDTH)
        return (max(length * 0.5, 1e-3), max(lw * 0.5, 1e-3))

    w = _paint_attr_float(getattr(shape, "width", None), 0.0)
    h = _paint_attr_float(getattr(shape, "height", None), 0.0)
    if w > 1e-6 and h > 1e-6:
        return (0.5 * w, 0.5 * h)
    r = _paint_attr_float(getattr(shape, "radius", None), 0.0)
    if r > 1e-6:
        return (r, r)
    length = _paint_attr_float(getattr(shape, "length", None), 0.0)
    if length > 1e-6:
        return (0.5 * length, 0.5 * length)
    return (24.0, 24.0)


def _shape_tile_cell_du(tile_size, image_width: int, image_height: int) -> Tuple[float, float]:
    """Cell size in design units. ``None`` → 48 DU wide (height follows aspect)."""
    iw = max(int(image_width), 1)
    ih = max(int(image_height), 1)
    aspect = ih / iw
    if tile_size is None:
        w_du = _SHAPE_TILE_DEFAULT_DU
        return (w_du, w_du * aspect)
    if isinstance(tile_size, (tuple, list)) and len(tile_size) == 2:
        return (float(tile_size[0]), float(tile_size[1]))
    w_du = float(tile_size)
    return (w_du, w_du * aspect)


def _shape_tile_local_matrix(
    *,
    image_width: int,
    image_height: int,
    tile_size,
    scale: float,
    angle: float = 0.0,
) -> skia.Matrix:
    """Image → origin-centered Y-up local space. One cell centered on the origin."""
    iw = max(int(image_width), 1)
    ih = max(int(image_height), 1)
    user_scale = float(scale) if float(scale) > 0.0 else 1.0
    tile_w, tile_h = _shape_tile_cell_du(tile_size, iw, ih)
    tile_w *= user_scale
    tile_h *= user_scale
    sx = tile_w / iw
    sy = tile_h / ih
    m = skia.Matrix()
    m.setScale(sx, -sy)
    m.postTranslate(-0.5 * tile_w, 0.5 * tile_h)
    if abs(float(angle)) > 1e-9:
        m.postRotate(float(angle))
    return m


def _shape_fit_local_matrix(
    *,
    fit: BackgroundFit,
    hw: float,
    hh: float,
    image_width: int,
    image_height: int,
    scale: float,
    angle: float = 0.0,
) -> skia.Matrix:
    """Image → origin-centered Y-up AABB ``[-hw, hw] × [-hh, hh]`` (cover/contain/stretch)."""
    hw = max(float(hw), 1e-6)
    hh = max(float(hh), 1e-6)
    iw = max(int(image_width), 1)
    ih = max(int(image_height), 1)
    user_scale = float(scale) if float(scale) > 0.0 else 1.0
    dw, dh = 2.0 * hw, 2.0 * hh
    if fit == BackgroundFit.STRETCH:
        sx = (dw / iw) * user_scale
        sy = (dh / ih) * user_scale
    else:
        ratio = max(dw / iw, dh / ih) if fit == BackgroundFit.COVER else min(dw / iw, dh / ih)
        s = ratio * user_scale
        sx = sy = s
    m = skia.Matrix()
    m.setScale(sx, -sy)
    m.postTranslate(-0.5 * iw * sx, 0.5 * ih * sy)
    if abs(float(angle)) > 1e-9:
        m.postRotate(float(angle))
    return m


class BackgroundImage:
    """Internal image payload for :class:`~scena.background_kinds.Wallpaper`.

    Authors construct ``Wallpaper("bg.jpg", fit="cover")`` — this class is
    not part of the star-import surface. ``fit='tile'`` repeats a cell of
    ``tile_size`` **design units** (default one-quarter of the shorter design
    side). ``scale`` is a unitless extra zoom.
    """

    __slots__ = ('_image', '_filename', '_fit', '_tile_mode', '_scale', '_tile_size', '_underlay')

    def __init__(
        self,
        source: Union[str, skia.Image, None] = None,
        *,
        filename: str = None,
        image: skia.Image = None,
        fit: Union[BackgroundFit, str] = BackgroundFit.COVER,
        tile_mode: Union[TileMode, str, None] = None,
        scale: float = 1.0,
        tile_size: Union[float, Tuple[float, float], None] = None,
        underlay: Union[Tuple[float, float, float, float], 'Color', str, None] = None,
    ):
        if isinstance(source, str):
            filename = source
        elif source is not None:
            image = source

        fit_val = coerce_enum(fit, BackgroundFit, what="fit")
        self._fit = fit_val
        # Omitted: REPEAT for tile, DECAL (nothing past the edge, the underlay
        # shows) for cover / contain / stretch — same as Texture. An explicit
        # clamp / repeat / mirror extends a fitted image past its edge under a
        # panning or zoomed-out camera.
        if tile_mode is None:
            tm = TileMode.REPEAT if fit_val == BackgroundFit.TILE else TileMode.DECAL
        else:
            tm = coerce_enum(tile_mode, TileMode, what="tile_mode")
        # fit=tile is infinite wallpaper: CLAMP would smear the image edge
        # once UV exceeds the first cell.
        if fit_val == BackgroundFit.TILE and tm == TileMode.CLAMP:
            tm = TileMode.REPEAT
        self._tile_mode = tm
        self._scale = _positive_scale(scale)
        self._tile_size = _parse_tile_size(tile_size, fit_val)
        self._filename = filename
        self._image = None

        if image is not None:
            if not hasattr(image, "isLazyGenerated"):
                raise TypeError(
                    f"image= expected a skia.Image, got {type(image).__name__}. "
                    f"Pass a file name instead: filename=\"sky.png\"."
                )
            self._image = image
        elif filename is not None:
            self._image = _load_image(filename, kind="background image")
        else:
            self._image = _make_fallback_image()

        # Underlay for letterbox (contain) and for edges revealed by pan/zoom
        # (cover/stretch with the DECAL default). Default black. None = no clear.
        if underlay is not None:
            self._underlay = Color(underlay) if not isinstance(underlay, Color) else underlay
        elif fit_val in (BackgroundFit.CONTAIN, BackgroundFit.COVER, BackgroundFit.STRETCH):
            self._underlay = Color(0.0, 0.0, 0.0, 1.0)
        else:
            self._underlay = None

    @staticmethod
    def _make_fallback_image() -> skia.Image:
        return _make_fallback_image()

    @property
    def image(self) -> skia.Image:
        return self._image

    @property
    def fit(self) -> str:
        return self._fit.value

    @property
    def tile_mode(self) -> str:
        return self._tile_mode.value

    @property
    def scale(self) -> float:
        return self._scale

    @property
    def tile_size(self) -> Optional[Union[float, Tuple[float, float]]]:
        """Cell size in design units when ``fit='tile'``; ``None`` = default at draw."""
        return self._tile_size

    @property
    def underlay(self) -> Optional['Color']:
        return self._underlay

    @property
    def filename(self) -> Optional[str]:
        return self._filename


# Image wallpapers and skia-python's ``Paint.setShader``
# ------------------------------------------------------
# ``setShader`` deep-copies the shader (serialize -> deserialize). The copy
# wraps a *new* ``skia.Image`` with a new ``uniqueID``, and Ganesh keys its
# texture cache by that ID. So every ``setShader`` of an image shader misses
# the GPU cache: a lazy (``Image.open``) image decodes again on its next draw
# (~35 ms for a 2669x1782 PNG), and a raster / GPU image is re-encoded to PNG
# inside ``setShader`` (~0.8 s at that size). ``_IMAGE_CACHE`` alone cannot
# help — the drawn image is never the cached one.
#
# Wallpaper images therefore never get a per-build ``setShader``:
# fitted images with the DECAL default draw with ``drawImageRect`` on the
# shared cached image, and tiles — and fitted images with an explicit
# clamp / repeat / mirror ``tile_mode`` — share one template Paint per image +
# mode (shader set once, identity local matrix, copied with
# ``skia.Paint(template)`` which keeps the same shader) placed by the canvas
# matrix. Same decoded texture across Wallpaper
# instances, window resizes, and camera-rest changes.
#
# The ``skia.Paint(Shader=...)`` kwarg shares the shader like the copy
# constructor does (measured with skia-python 144). Shape materials use it
# (``PaintState._material_paint``): every shape paint of a Texture file,
# at any extent and across Texture instances, samples the one cached image.
# With per-paint ``setShader``, 50 shapes on a 2670x1780 Texture held 50
# copies of about 19 MB each, overran the GPU budget, and re-decoded every
# frame (~1.1 s/frame).
_IMAGE_PAINT_CACHE: dict = {}
_PREWARM_SURFACE: dict = {}
_PENDING_PREWARM: list = []
_UNIT_RECT = skia.Rect.MakeWH(1.0, 1.0)


def _image_template_paint(image: skia.Image, tile_mode: TileMode) -> skia.Paint:
    """Paint holding ``image``'s identity-matrix shader, set once per image + mode.

    Callers copy it (``skia.Paint(template)``) and place it with the canvas
    matrix; see the note above on why the shader must not be set again.
    """
    tm = _SKIA_TILE_MAP.get(tile_mode, skia.TileMode.kRepeat)
    key = (image.uniqueID(), tm)
    hit = _IMAGE_PAINT_CACHE.get(key)
    if hit is not None:
        return hit[1]
    paint = skia.Paint()
    paint.setShader(image.makeShader(tm, tm, _IMAGE_SAMPLING))
    # Hold the source image so its uniqueID is not reused while cached.
    _IMAGE_PAINT_CACHE[key] = (image, paint)
    return paint


class BackgroundFill:
    """How a wallpaper source fills a framebuffer rect (built per size / rest key).

    ``fill(canvas, rect)`` paints ``rect`` (current canvas coordinates, which
    may carry the camera CTM). ``underlay`` is the letterbox clear colour or
    ``None``. ``paint`` is the paint used by :meth:`fill`.
    """

    __slots__ = ("paint", "rect", "underlay", "_image", "_src", "_dst", "_matrix", "_inverse")

    def __init__(self, paint, rect, underlay=None, *, image=None, dst=None, matrix=None):
        self.paint = paint
        self.rect = rect
        self.underlay = underlay
        self._image = image
        self._src = skia.Rect.MakeWH(image.width(), image.height()) if image is not None else None
        self._dst = dst
        self._matrix = matrix
        self._inverse = None
        if matrix is not None:
            inv = skia.Matrix()
            self._inverse = inv if matrix.invert(inv) else None

    def fill(self, canvas: skia.Canvas, rect: skia.Rect) -> None:
        if self._image is not None:
            # Fitted image: only its dst rect paints (the underlay shows around it).
            # ``matrix`` here is the Texture's turn about the frame center.
            if self._matrix is None:
                self._draw_image(canvas)
                return
            canvas.save()
            try:
                canvas.concat(self._matrix)
                self._draw_image(canvas)
            finally:
                canvas.restore()
        elif self._matrix is not None:
            if self._inverse is None:
                return
            canvas.save()
            try:
                canvas.concat(self._matrix)
                canvas.drawRect(self._inverse.mapRect(rect), self.paint)
            finally:
                canvas.restore()
        else:
            canvas.drawRect(rect, self.paint)

    def _draw_image(self, canvas: skia.Canvas) -> None:
        canvas.drawImageRect(
            gpu_image(self._image, canvas), self._src, self._dst, skia.SamplingOptions(),
            self.paint,
            skia.Canvas.kFast_SrcRectConstraint,
        )


def prewarm_background_image(source) -> None:
    """Decode + upload a wallpaper image on the GPU context (now, or when it opens).

    ``skia.Image.open`` is lazy: without this the decode lands on the first
    frame that shows the wallpaper — a mid-game hitch for
    ``bg = Wallpaper.temp(...)`` built in setup and swapped in later. Before
    ``run()`` opens the window there is no context, so the image is queued and
    decoded by :func:`prewarm_pending_images` before the first frame.
    No-op for non-lazy images (nothing to decode).
    """
    img = getattr(source, "image", None)
    if img is None or not img.isLazyGenerated():
        return
    job = (img, _uses_template(source), source._tile_mode)
    ctx = _live_gr_context()
    if ctx is None:
        _PENDING_PREWARM.append(job)
        return
    _prewarm(ctx, *job)


def prewarm_pending_images() -> None:
    """Run prewarms queued before the GPU context existed (called once it does)."""
    ctx = _live_gr_context()
    if ctx is None:
        return
    jobs = list(_PENDING_PREWARM)
    _PENDING_PREWARM.clear()
    seen = set()
    for img, tile, tile_mode in jobs:
        key = (img.uniqueID(), tile, tile_mode)
        if key not in seen:
            seen.add(key)
            _prewarm(ctx, img, tile, tile_mode)


def _uses_template(source) -> bool:
    """True when the wallpaper draws through the image's template Paint.

    Tiles, and fitted images whose ``tile_mode`` extends past the edge; a fitted
    DECAL image draws with ``drawImageRect`` instead.
    """
    return source._fit == BackgroundFit.TILE or source._tile_mode != TileMode.DECAL


def _live_gr_context():
    try:
        from .orchestration import ScenaFramework
    except Exception:
        return None
    return getattr(ScenaFramework._instance, "_context", None)


# Pinned GPU textures of loaded images (Canvas Design, "GPU memory"). The
# idle purge frees what was not drawn for a second, and a raster image's
# upload is such a resource: a background shown again after a pause menu was
# uploaded again (2048²: 0.5 → 3.7 ms that frame). Holding a texture copy does
# not keep the raster's own upload, so the draw sites below draw the copy
# itself, on a GPU canvas: an unbudgeted texture, made once per image and
# context, that no purge touches. Only decoded files (the decode caches hold
# them for the session anyway); CPU readers keep the raster. False: draw the
# raster (A/B).
_PIN_IMAGES = True
_PINNABLE: dict = {}        # id(image) -> image: decoded file images
_PINNED: dict = {}          # id(image) -> (context, texture copy)
_PIN_CANVAS: list = [None, None]    # last canvas asked, and its context (None: raster)


def _pinnable(img) -> None:
    """``img`` is a decoded file image (a decode cache holds it)."""
    if img is not None:
        _PINNABLE[id(img)] = img


def _drop_pins() -> None:
    """Free the pinned textures (their context is closing)."""
    _PINNED.clear()
    _PIN_CANVAS[0] = _PIN_CANVAS[1] = None


def _unpin_images() -> None:
    """Drop every pin (the decode caches were cleared)."""
    _PINNABLE.clear()
    _drop_pins()


def _pin_canvas(canvas) -> None:
    """Remember ``canvas`` and the live context it draws with (None: raster)."""
    surf = canvas.getSurface()
    gpu = surf is not None and surf.recordingContext() is not None
    _PIN_CANVAS[0] = canvas
    _PIN_CANVAS[1] = _live_gr_context() if gpu else None


def gpu_image(img, canvas):
    """The image to draw for ``img`` on ``canvas``: its pinned texture when
    ``img`` is a decoded file and ``canvas`` draws on the GPU, else ``img``."""
    if not _PIN_IMAGES:
        return img
    memo = _PIN_CANVAS
    if memo[0] is not canvas:
        _pin_canvas(canvas)
    ctx = memo[1]
    if ctx is None:
        return img
    key = id(img)
    pin = _PINNED.get(key)
    if pin is not None and pin[0] is ctx:
        return pin[1]
    if key not in _PINNABLE:
        return img
    try:
        tex = img.makeTextureImage(ctx, skia.GrMipmapped.kNo, skia.Budgeted.kNo)
    except Exception:
        tex = None
    if tex is None:
        _PINNABLE.pop(key, None)            # not uploadable: draw the raster
        return img
    _PINNED[key] = (ctx, tex)
    return tex


def _prewarm(ctx, img: skia.Image, tile: bool, tile_mode: TileMode) -> None:
    # Draw exactly what BackgroundFill draws (same image / template shader) so
    # the texture lands under the key the real draw looks up.
    surf = _PREWARM_SURFACE.get(id(ctx))
    if surf is None:
        surf = skia.Surface.MakeRenderTarget(
            ctx, skia.Budgeted.kYes, skia.ImageInfo.MakeN32Premul(1, 1),
        )
        if surf is None:
            return
        _PREWARM_SURFACE.clear()
        _PREWARM_SURFACE[id(ctx)] = surf
    c = surf.getCanvas()
    if tile:
        c.drawRect(_UNIT_RECT, _image_template_paint(img, tile_mode))
    else:
        c.drawImageRect(img, _UNIT_RECT, skia.SamplingOptions())


def _texture_turn(source) -> float:
    """A wallpaper image's rotation in degrees (a Texture's ``angle``; else 0)."""
    return float(getattr(source, "_angle", 0.0) or 0.0)


def _texture_knobs_paint(paint: skia.Paint, source) -> skia.Paint:
    """``paint`` with a Texture's alpha and ``shift`` (as a shape fill takes them)."""
    if isinstance(source, Texture):
        if source.alpha < 1.0:
            paint.setAlphaf(float(source.alpha))
        cf = source._shift_color_filter
        if cf is not None:
            paint.setColorFilter(cf)
    return paint


def build_background_fill(
    source,
    w: int,
    h: int,
    design_width: float,
    design_height: float,
    rest_x: Optional[float] = None,
    rest_y: Optional[float] = None,
) -> BackgroundFill:
    """Build the full-surface fill (+ optional letterbox underlay) for a wallpaper source.

    Coordinates are device pixels of the target surface (identity CTM).
    A Gradient keeps its y-up local frame (``angle=90`` runs bottom → top, as
    on a shape). Gradient sizes authored in design units are scaled by ``w / design_width``.
    Omitted Gradient ``size`` fits the design frame first (LINEAR along ``angle``,
    RADIAL to the nearer edge), then that pixel scale.
    Tiled images use ``tile_size`` design units (default ¼ of the shorter design
    side); ``scale`` is a unitless extra zoom. ``rest_x`` / ``rest_y`` phase
    tiles so world ``(0, 0)`` is a cell corner (defaults to design center).
    A Texture keeps what a shape fill takes from it: ``angle`` (y-up CCW, about
    the frame center; a tile turns about world ``(0, 0)``), ``shift`` and alpha.
    Used by :class:`~scena.background_kinds.Wallpaper`.
    """
    rect = skia.Rect.MakeWH(float(w), float(h))

    if isinstance(source, (BackgroundImage, Texture)):
        img = source.image
        iw = max(img.width(), 1)
        ih = max(img.height(), 1)
        fit = source._fit
        user_scale = source.scale if source.scale > 0 else 1.0
        # Texture knobs a shape fill honours (``angle``, ``shift``, alpha): the
        # same here, baked once per build. ``angle`` is y-up CCW, as on a
        # shape; the device frame is y-down, hence ``-angle``.
        angle = _texture_turn(source)
        turn = abs(angle) > 1e-9
        if fit == BackgroundFit.TILE:
            m = _tile_local_matrix(
                image_width=iw,
                image_height=ih,
                tile_size=source.tile_size,
                scale=user_scale,
                fb_width=float(w),
                fb_height=float(h),
                design_width=float(design_width),
                design_height=float(design_height),
                rest_x=rest_x,
                rest_y=rest_y,
            )
            if turn:
                # About world (0, 0), so a cell corner stays there.
                px, py = m.mapXY(0.0, float(ih))
                m.postRotate(-angle, px, py)
            paint = _texture_knobs_paint(skia.Paint(_image_template_paint(img, source._tile_mode)), source)
            paint.setAntiAlias(False)
            # kSrc replaces prior frame contents without a separate clear when opaque.
            paint.setBlendMode(skia.BlendMode.kSrc)
            return BackgroundFill(paint, rect, None, matrix=m)
        if fit == BackgroundFit.STRETCH:
            sx = (w / iw) * user_scale
            sy = (h / ih) * user_scale
        else:
            s = max(w / iw, h / ih) if fit == BackgroundFit.COVER else min(w / iw, h / ih)
            sx = sy = s * user_scale
        tx = (w - iw * sx) * 0.5
        ty = (h - ih * sy) * 0.5
        underlay_src = getattr(source, "underlay", None)
        underlay = underlay_src.color4f if underlay_src is not None else skia.Color4f(0.0, 0.0, 0.0, 1.0)
        if _uses_template(source):
            # clamp / repeat / mirror: the image continues past its edge, so a
            # panning or zoomed-out camera never reveals the underlay. Same
            # placement as the dst rect below, through the template shader.
            m = skia.Matrix.Translate(tx, ty)
            m.preScale(sx, sy)
            if turn:
                m.postRotate(-angle, w * 0.5, h * 0.5)
            paint = _texture_knobs_paint(skia.Paint(_image_template_paint(img, source._tile_mode)), source)
            paint.setAntiAlias(False)
            return BackgroundFill(paint, rect, underlay, matrix=m)
        # DECAL: pan/zoom can reveal outside the fitted image: nothing is drawn
        # there, so the underlay shows as clean surroundings (no edge smear).
        dst = skia.Rect.MakeXYWH(tx, ty, iw * sx, ih * sy)
        paint = _texture_knobs_paint(skia.Paint(), source)
        paint.setAntiAlias(False)
        m = skia.Matrix.RotateDeg(-angle, skia.Point(w * 0.5, h * 0.5)) if turn else None
        return BackgroundFill(paint, rect, underlay, image=img, dst=dst, matrix=m)

    paint = skia.Paint()
    paint.setAntiAlias(False)  # fullscreen rect; AA not needed
    paint.setBlendMode(skia.BlendMode.kSrc)
    if isinstance(source, Gradient):
        sx = (w / design_width) if design_width else 1.0
        # The fill is in device pixels (y down); the gradient's local frame is
        # y-up, as on a shape: ``angle=90`` runs from the bottom up everywhere.
        # Before 0.8.1 a Wallpaper skipped this flip and drew it top-down.
        sy = -((h / design_height) if design_height else 1.0)
        m = skia.Matrix()
        m.setTranslate(w * 0.5, h * 0.5)
        if source._needs_host_fit:
            hw = 0.5 * max(float(design_width), 1.0)
            hh = 0.5 * max(float(design_height), 1.0)
            fit = _gradient_fit_scale(hw, hh, source)
            m.preScale(sx * fit, sy * fit)
        else:
            m.preScale(sx, sy)
        shader = source._skia_shader
        if hasattr(shader, "makeWithLocalMatrix"):
            shader = shader.makeWithLocalMatrix(m)
        paint.setShader(shader)
    else:
        paint.setColor4f(skia.Color4f(0.0, 0.0, 0.0, 1.0))
    return BackgroundFill(paint, rect)


def paint_with_camera_offset(
    base_paint: skia.Paint,
    offset_x: float,
    offset_y: float,
    scale: float,
    rotation_rad: float,
    w: float,
    h: float,
) -> skia.Paint:
    """Return a Paint whose shader is offset/scaled for wallpaper parallax.

    Matches the canvas CTM
    ``T(center) · R · S(scale) · T(-center) · T(offset)`` —
    positive ``offset`` shifts content in the +FB direction; ``scale > 1``
    zooms content in (same as procedural ``u_scale``). ``rotation_rad`` is
    camera-matching CCW+; Skia y-down ``postRotate`` is CW+, so this
    negates. Prefer applying the same transform on the canvas (see
    ``Wallpaper.draw``): per-frame ``makeWithLocalMatrix`` is much more
    expensive on image shaders.
    """
    shader = base_paint.getShader()
    if shader is None:
        return base_paint

    cx, cy = float(w) * 0.5, float(h) * 0.5
    s = max(float(scale), 1e-4)
    # localMatrix maps shader space → local; makeWithLocalMatrix multiplies
    # so sampling matches canvas concat of T(c)·R·S(s)·T(-c)·T(offset).
    m = skia.Matrix()
    m.setTranslate(float(offset_x), float(offset_y))
    m.postTranslate(-cx, -cy)
    m.postScale(s, s)
    if abs(float(rotation_rad)) > 1e-12:
        m.postRotate(-float(rotation_rad) * (180.0 / 3.141592653589793))
    m.postTranslate(cx, cy)

    if hasattr(shader, "makeWithLocalMatrix"):
        shader = shader.makeWithLocalMatrix(m)

    out = skia.Paint(base_paint)
    out.setShader(shader)
    return out


def _interned_setattr(self, name: str, value) -> None:
    """``__setattr__`` for interned looks / filters (``Visual``, ``FilterEffect``).

    ``Neon("red")`` is one shared object per argument tuple (the intern cache
    key). A public write on it would repaint every shape using it, poison the
    cache for the next ``Neon("red")``, and skip whatever ``__init__`` derived
    from that field. Once built (``_ready``) an interned instance refuses
    public writes; private caches (``_rp_stroke_i``) pay only the ``name[0]``
    check. Colour changes swap instances (de-seed), never mutate one.

    Every other built instance (``ComposeFx``, ``Recipe``, ``Tail`` in follow
    mode, an author subclass) is a closed surface: a public write to a name
    it does not have raises (:mod:`scena.closed`).
    """
    if name[0] != "_":
        d = self.__dict__
        if d.get("_sealed") and name not in d:
            check_closed_write(self, name)
        if d.get("_ready") and d.get("_interned"):
            cls = type(self).__name__
            raise AttributeError(
                f"{cls}.{name} is read-only: {cls}(...) is shared by every "
                f"shape built with the same arguments. Build a new one with "
                f"the value you want, {cls}({name}={value!r}), and assign it "
                f"where this one is used."
            )
    object.__setattr__(self, name, value)


class FilterEffect:
    """Base class for all filter effects"""

    __setattr__ = _interned_setattr

    def __init_subclass__(cls, **kwargs):
        # Every filter checks its numeric knobs before building (A3): filters
        # construct in ``__new__`` and some also take knobs in ``__init__``.
        super().__init_subclass__(**kwargs)
        if is_framework_module(cls.__module__):
            from .validate import guard_init_numbers, guard_new_numbers
            guard_new_numbers(cls)
            if "__init__" in cls.__dict__:
                guard_init_numbers(cls)
        # Last (every subclass, author ones too): closed surface after init.
        seal_after_init(cls)
    def __init__(self, image_filter: skia.ImageFilter):
        self._filter = image_filter

    @property
    def _skia_filter(self) -> skia.ImageFilter:
        return self._filter

    @property
    def _batch_key(self):
        """Identity for scene-level filter batching; ``None`` means never batch."""
        return None

    @property
    def _batch_outset(self) -> float:
        """Extra padding (design units) for saveLayer bounds when batching."""
        return 0.0

    def _uses_filter_pipeline(self) -> bool:
        """False to draw via ``_draw_survival`` instead of ImageFilter RT."""
        return True

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        """ImageFilter with length params scaled for a reduced-res RT.

        When fill/line filters are rasterized into a ``shape_fx_scale`` RT,
        soft kernels (blur σ, dilate radius, glow) shrink with the RT so the
        upscaled result matches full-res softness. **Positional** params
        (e.g. DropShadow ``dx``/``dy``) stay in design space — geometry CTM
        already maps them. Default: unchanged (unknown params).
        """
        return self._filter

    def compose(self, inner: 'FilterEffect') -> 'ComposeFx':
        """Compose this filter with another (outer(inner(x)))"""
        if not isinstance(inner, FilterEffect):
            raise TypeError(
                f"compose() takes a filter such as Blur(2), got {type(inner).__name__}"
            )
        return ComposeFx(self, inner)


seal_after_init(FilterEffect)


class ComposeFx(FilterEffect):
    """Composes two filters (outer(inner(x)))"""
    def __init__(self, outer: FilterEffect, inner: FilterEffect):
        self._outer = outer
        self._inner = inner
        super().__init__(skia.ImageFilters.Compose(
            outer=outer._skia_filter,
            inner=inner._skia_filter
        ))

    @property
    def _batch_key(self):
        return (
            "compose",
            getattr(self._outer, "_batch_key", None),
            getattr(self._inner, "_batch_key", None),
        )

    @property
    def _batch_outset(self) -> float:
        return max(
            float(getattr(self._outer, "_batch_outset", 0.0) or 0.0),
            float(getattr(self._inner, "_batch_outset", 0.0) or 0.0),
        )

    def _uses_filter_pipeline(self) -> bool:
        for child in (self._outer, self._inner):
            fn = getattr(child, "_uses_filter_pipeline", None)
            if callable(fn) and not fn():
                return False
        return True

    def _filter_at_scale(self, scale: float) -> skia.ImageFilter:
        if scale >= 0.999:
            return self._filter
        return skia.ImageFilters.Compose(
            outer=self._outer._filter_at_scale(scale),
            inner=self._inner._filter_at_scale(scale),
        )

"""
Module defaults API (rare). Prefer per-shape ``.visual`` / ``.fill`` / …
"""

# Author-facing unions (constructors / properties). Not star-exported.
PaintMaterial = Optional[Union[Color, str, tuple, list, Gradient, Texture, ProceduralFill]]
FilterLike = Optional[FilterEffect]
if TYPE_CHECKING:
    from .visuals import Visual as _Visual
    LookLike = Union[_Visual, PaintMaterial]
else:
    LookLike = object  # runtime checks go through coerce_visual


def _coerce_filter(value, *, what: str):
    """``None`` or a :class:`FilterEffect`; looks get a redirect hint."""
    value = as_payload(value)
    if value is None:
        return None
    if isinstance(value, FilterEffect):
        return value
    hint = (
        f"Use {what.replace('_filter', '')}_filter only for ImageFilters "
        f"(Blur, GlowFilter, DropShadow, HostGlow, Dilate, Erode). "
    )
    try:
        from .visuals import Visual
        if isinstance(value, Visual):
            hint = (
                f"{type(value).__name__} is a look — assign with "
                f"shape.visual = {type(value).__name__}()."
            )
    except ImportError:
        pass
    raise TypeError(
        f"{what} expected a filter (Blur, GlowFilter, DropShadow, …) or None, "
        f"got {type(value).__name__}. {hint}"
    )


def _look_family_hint(value) -> Optional[str]:
    """Redirect wrong families away from ``shape.visual``."""
    from .stamps import is_stamp_visual, stamp_visual_hint
    if is_stamp_visual(value):
        return stamp_visual_hint(value)
    if isinstance(value, FilterEffect):
        return (
            f"{type(value).__name__} is a filter — assign with "
            "shape.fill_filter / shape.line_filter."
        )
    try:
        from .spatial_fx import SpatialFx
        if isinstance(value, SpatialFx):
            return (
                f"{type(value).__name__} is SpatialFx — construct it to place "
                "(Rain(), Fire(), …), do not assign to shape.visual."
            )
    except ImportError:
        pass
    try:
        from .postfx import PostEffect
        if isinstance(value, PostEffect):
            return (
                f"{type(value).__name__} is a canvas post effect — construct it "
                "(Vignette(), Bloom(), …), do not assign to shape.visual."
            )
    except ImportError:
        pass
    try:
        from .shapes import Shape
        if isinstance(value, Shape):
            return (
                f"{type(value).__name__} is a shape, not a look. "
                "Assign Neon() / Halo() / a color / Gradient to shape.visual."
            )
    except ImportError:
        pass
    return None


def _look_class_named(text: str) -> Optional[str]:
    """Public Visual class whose name is ``text`` (any case), unless ``text`` is a color."""
    key = text.strip().lower().replace("_", "").replace(" ", "")
    if not key or text.strip().startswith("#") or ColorNames.is_known(text.strip()):
        return None
    import sys
    from ._pkg import PKG
    from .visuals import Visual
    package = sys.modules[PKG]
    for name in package.__all__:
        obj = getattr(package, name, None)
        if isinstance(obj, type) and issubclass(obj, Visual) and name.lower() == key:
            return name
    return None


def coerce_visual(value):
    """Turn an author look value into a ``Visual`` instance.

    Accepts named visuals, ``Color`` / color strings, ``Gradient``,
    ``Texture``, and ``ProceduralFill`` (``WaveFill`` → ``Wave``).
    Stamp looks (Glow / Shadow / HueShift / Tail) raise with a property hint.
    """
    value = as_payload(value)
    if value is None:
        return None
    from .stamps import is_stamp_visual, stamp_visual_hint
    if is_stamp_visual(value):
        raise TypeError(stamp_visual_hint(value))
    from .visuals import Visual, Paint
    if isinstance(value, Visual):
        return value
    if isinstance(value, ProceduralFill):
        kind = str(getattr(value, "_kind", "") or "")
        if kind == "wave":
            from .recipes import Wave
            col = getattr(value, "_color", None)
            return Wave(
                color=col,
                amount=float(getattr(value, "_amount", 1.0)),
                speed=float(getattr(value, "_speed", 1.0)),
            )
        return Paint(value)
    if isinstance(value, (Gradient, Texture)):
        return Paint(value)
    if isinstance(value, Color):
        return Paint(value)
    if isinstance(value, str):
        look = _look_class_named(value)
        if look is not None:
            raise TypeError(
                f"shape.visual = {value!r} is a look name, not a color. "
                f"Looks are objects: shape.visual = {look}()"
            )
        return Paint(value)
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return Paint(value)
    hint = _look_family_hint(value)
    msg = (
        "shape.visual expected a look (named visual, color, Gradient, or Texture), "
        f"got {type(value).__name__}"
    )
    if hint:
        msg = f"{msg}. {hint}"
    raise TypeError(msg)


# The channels ``set_defaults(**channels)`` takes (help() lists them).
_DEFAULT_CHANNELS = (
    "line_width", "dash", "line_cap", "line_join", "line", "fill",
    "blend", "line_filter", "fill_filter",
)


def set_defaults(visual: Optional["LookLike"] = None, **channels) -> PaintState:
    """Set the prototype appearance for newly created shapes.

    Typical use::

        set_defaults(visual=Neon())
        set_defaults("coral", line_width=2.0)

    ``visual`` is a look (named visual, color, Gradient, Texture). Channel
    kwargs (``fill_filter``, ``dash``, …) use the same checks as shape
    properties. Wrong families raise ``TypeError``.

    Args:
        visual: Default look for new shapes (a look, color, ``Gradient`` or
            ``Texture``).
        line_width: Default outline thickness.
        dash: Default outline pattern (``"solid"``, ``"dash"``, …).
        line_cap: Default line ends.
        line_join: Default corners.
        line: Default outline material.
        fill: Default interior material.
        blend: Default blend mode.
        line_filter: Default outline filter.
        fill_filter: Default interior filter.
    """
    if visual is None and not channels:
        return PaintState.get_defaults()
    extra = set(channels) - set(_DEFAULT_CHANNELS)
    if extra:
        from .validate import did_you_mean
        valid = ("visual", *_DEFAULT_CHANNELS)
        hint = "".join(did_you_mean(k, valid) for k in sorted(extra))
        raise TypeError(
            f"set_defaults() got unexpected keyword argument(s): "
            f"{', '.join(sorted(extra))}.{hint} Valid: {', '.join(sorted(valid))}."
        )
    defaults = PaintState.get_defaults()
    if defaults is None:
        return PaintState.set_defaults(visual, **channels)
    # Merge onto existing prototype so bootstrap can call twice safely.
    kwargs = {
        "line_width": channels.get("line_width", defaults._line_width),
        "dash": channels.get("dash", defaults._dash),
        "line_cap": channels.get("line_cap", defaults._line_cap),
        "line_join": channels.get("line_join", defaults._line_join),
        "line": channels.get("line", defaults._line),
        "fill": channels.get("fill", defaults._fill),
        "blend": channels.get("blend", defaults._blend),
        "line_filter": channels.get("line_filter", defaults._line_filter),
        "fill_filter": channels.get("fill_filter", defaults._fill_filter),
    }
    return PaintState.set_defaults(visual if visual is not None else defaults.visual, **kwargs)


def _publish_set_defaults_signature() -> None:
    """``help(set_defaults)`` lists the channels ``**channels`` accepts."""
    import inspect
    P = inspect.Parameter
    params = [P("visual", P.POSITIONAL_OR_KEYWORD, default=None)]
    params += [P(name, P.KEYWORD_ONLY, default=Unset("<keep>")) for name in _DEFAULT_CHANNELS]
    set_defaults.__signature__ = inspect.Signature(params, return_annotation=PaintState)


_publish_set_defaults_signature()
