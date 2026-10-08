"""Appearance stamps: sticky pigment / motion on top of ``.visual``.

Author surface: ``shape.glow`` / ``.shadow`` / ``.hue`` / ``.gray`` / ``.tail``.
Costume stays one exclusive ``.visual``. Stamps compose around it.
"""
from __future__ import annotations

import math
from typing import Any, Optional, Tuple, Union

from .entity import scena_kind
from .color import Color, ColorLike
from .state import as_payload

# HueShift(True) catalog default — 1/3 turn (120°), visible character variant.
_HUE_TRUE_TURNS = 1.0 / 3.0
# Follow-tail: smooth velocity → heading + length (not a fixed sticker).
_TAIL_TAU = 0.08  # s; exponential-smooth time constant (alpha = dt / (tau + dt))
_TAIL_SPEED_EPS = 15.0  # DU/s; below this keep last heading while v decays
# ~120 DU/s → scale 1.0 (ellipse cruise in stamps smoke ≈ 100–187 DU/s).
# Follow length matches locked Tail(angle=) at the same author size= (cap 1.0).
_TAIL_REF_SPEED = 120.0
_TAIL_SCALE_MAX = 1.0
_TAIL_SCALE_SKIP = 0.05  # skip ghost draws when follow scale is tiny
_TAIL_SPAN = 22.0  # size=1, follow and locked
_TAIL_DT_MIN = 1.0 / 240.0
_TAIL_DT_MAX = 1.0 / 15.0


def is_stamp_visual(value) -> bool:
    """True when ``value`` is a look that must use a stamp property, not ``.visual``."""
    if value is None:
        return False
    from .visuals import Glow, CheapGlow, Shadow, HueShift, Grayscale
    from .recipes import Tail
    return isinstance(value, (Glow, CheapGlow, Shadow, HueShift, Grayscale, Tail))


def stamp_visual_hint(value) -> str:
    """Family hint when a stamp look is assigned to ``.visual``."""
    name = type(value).__name__
    if name in ("Glow", "CheapGlow"):
        return f"{name} is a stamp — assign with shape.glow = {name}() or shape.glow = True."
    if name == "Shadow":
        return "Shadow is a stamp — assign with shape.shadow = Shadow() or shape.shadow = True."
    if name == "HueShift":
        return (
            "HueShift is a stamp — assign with sprite.hue = HueShift(...) or "
            "sprite.hue = True. For Shape bitmaps use Texture(..., shift=HueShift(...))."
        )
    if name == "Grayscale":
        return "Grayscale is a stamp — assign with sprite.gray = True, a number 0–1, or Grayscale(...)."
    if name == "Tail":
        return "Tail is a stamp — assign with shape.tail = Tail() or shape.tail = True."
    return f"{name} is a stamp — use the matching .glow / .shadow / .hue / .gray / .tail property."


def _as_color(color) -> Color:
    if isinstance(color, Color):
        return color if color else Color(0.5, 0.5, 0.5, 1.0)
    return Color(color)


def coerce_glow(value):
    """``True`` / color / Glow / CheapGlow → look; ``False``/``None`` → None."""
    from .visuals import Glow, CheapGlow

    value = as_payload(value)
    if value is None or value is False:
        return None
    if value is True:
        return Glow()
    if isinstance(value, (Glow, CheapGlow)):
        return value
    if isinstance(value, (Color, str)):
        return Glow(value)
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return Glow(value)
    raise TypeError(
        f"shape.glow expected True, a color, Glow(...), or CheapGlow(...), "
        f"got {type(value).__name__}."
    )


def coerce_shadow(value):
    """``True`` / color / Shadow → look; ``False``/``None`` → None."""
    from .visuals import Shadow

    value = as_payload(value)
    if value is None or value is False:
        return None
    if value is True:
        return Shadow()
    if isinstance(value, Shadow):
        return value
    if isinstance(value, (Color, str)):
        return Shadow(value)
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return Shadow(value)
    raise TypeError(
        f"shape.shadow expected True, a color, or Shadow(...), "
        f"got {type(value).__name__}."
    )


def coerce_hue(value):
    """``True`` → HueShift(1/3); number → turns; ``0``/False/None → None."""
    from .visuals import HueShift

    value = as_payload(value)
    if value is None or value is False:
        return None
    if value is True:
        return HueShift(amount=_HUE_TRUE_TURNS)
    if isinstance(value, HueShift):
        return value
    if isinstance(value, (int, float)):
        turns = float(value) % 1.0
        if turns == 0.0 and float(value) == 0.0:
            return None
        return HueShift(amount=float(value))
    raise TypeError(
        f"sprite.hue expected True, a number of turns, or HueShift(...), "
        f"got {type(value).__name__}."
    )


def coerce_gray(value):
    """``True`` → Grayscale(1); number 0–1 → that amount; ``0``/False/None → None."""
    from .visuals import Grayscale

    value = as_payload(value)
    if value is None or value is False:
        return None
    if value is True:
        return Grayscale()
    if isinstance(value, Grayscale):
        return value
    if isinstance(value, (int, float)):
        look = Grayscale(float(value))
        return None if look.amount == 0.0 else look
    raise TypeError(
        f"sprite.gray expected True, a number 0–1, or Grayscale(...), "
        f"got {type(value).__name__}."
    )


def coerce_tail(value):
    """``True`` / number(angle) / color / Tail → look; ``False``/``None`` → None.

    Returns ``(look, follow, locked_angle)``.
    """
    from .recipes import Tail

    value = as_payload(value)
    if value is None or value is False:
        return None, False, None
    if value is True:
        return Tail(), True, None
    if isinstance(value, Tail):
        follow = bool(getattr(value, "_stamp_follow", False))
        return value, follow, None
    if isinstance(value, (int, float)):
        ang = float(value)
        return Tail(angle=ang), False, ang
    if isinstance(value, (Color, str)):
        return Tail(color=value), True, None
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return Tail(color=value), True, None
    if callable(value) and not isinstance(value, type):
        raise TypeError(
            "shape.tail cannot be a bare lambda — use "
            "Tail(angle=lambda: ...) or assign a number each frame."
        )
    raise TypeError(
        f"shape.tail expected True, an angle in degrees, a color, or Tail(...), "
        f"got {type(value).__name__}."
    )


def _host_uses_stroke_filter(shape) -> bool:
    from .visuals import _host_uses_stroke_filter as _hs
    return _hs(shape)


def _compose_filter(outer, inner):
    """Compose outer(inner(x)); either may be None."""
    if outer is None:
        return inner
    if inner is None:
        return outer
    from .style import ComposeFx
    return ComposeFx(outer, inner)


def _glow_filter(look):
    """ImageFilter from Glow; CheapGlow has none (overlay path)."""
    from .visuals import Glow, CheapGlow
    if isinstance(look, Glow):
        return getattr(look, "_glow", None)
    if isinstance(look, CheapGlow):
        return None
    return None


def _shadow_filter(look):
    from .visuals import Shadow
    from .fx_quality import fidelity_is_survival
    if not isinstance(look, Shadow):
        return None
    if fidelity_is_survival():
        return None
    return getattr(look, "_shadow", None)


def capture_stamp_bases(shape) -> None:
    """Remember current filters as costume/author bases (before stamp compose)."""
    shape._stamp_base_ff = getattr(shape, "_fill_filter", None)
    shape._stamp_base_lf = getattr(shape, "_line_filter", None)


def sync_stamp_filters(shape) -> None:
    """Write composed fill/line filters from stamp bases + glow/shadow.

    CheapGlow does not use ImageFilters (overlay at draw). Text Glow is
    drawn in Text._geometry_draw (no ImageFilter).
    """
    base_ff = getattr(shape, "_stamp_base_ff", None)
    base_lf = getattr(shape, "_stamp_base_lf", None)
    # First compose: if bases never captured, treat live filters as bases
    # only when no glow/shadow stamp yet wrote over them.
    if not hasattr(shape, "_stamp_base_ff"):
        base_ff = getattr(shape, "_fill_filter", None)
        base_lf = getattr(shape, "_line_filter", None)
        shape._stamp_base_ff = base_ff
        shape._stamp_base_lf = base_lf

    glow = getattr(shape, "_glow", None)
    shadow = getattr(shape, "_shadow", None)
    is_text = scena_kind(shape) == "Text"

    stamp_fx = None
    if not is_text:
        gf = _glow_filter(glow)
        sf = _shadow_filter(shadow)
        # Fixed order: shadow under, glow around (outer = glow).
        stamp_fx = _compose_filter(gf, sf)

    use_stroke = _host_uses_stroke_filter(shape) if not is_text else False
    if use_stroke:
        shape._line_filter = _compose_filter(stamp_fx, base_lf)
        shape._fill_filter = base_ff
    else:
        shape._fill_filter = _compose_filter(stamp_fx, base_ff)
        shape._line_filter = base_lf
    # Direct _fill_filter writes skip the property setter; solo draw uses the
    # cached Skia paint. Dirty so glow/shadow assign and clear take effect.
    shape._is_fill_paint_dirty = True
    shape._is_line_paint_dirty = True
    shape._cached_fill_paint = None
    shape._cached_line_paint = None


def apply_hue_stamp(shape, look) -> None:
    """Install Sprite blit ColorFilter from HueShift without clearing ImageFilters."""
    install = getattr(shape, "_install_blit_color_filter", None)
    live_fn = getattr(shape, "_install_blit_hue_live", None)
    if look is None:
        if callable(install):
            install(None)
        if callable(live_fn):
            live_fn(None)
        return
    if not callable(install):
        return
    if getattr(look, "live", False):
        install(None)
        if callable(live_fn):
            live_fn(look.amount)
    else:
        if callable(live_fn):
            live_fn(None)
        install(getattr(look, "_color_filter", None))


def apply_gray_stamp(shape, look) -> None:
    """Install (or clear) the Sprite blit gray ColorFilter."""
    install = getattr(shape, "_install_blit_gray", None)
    if callable(install):
        install(None if look is None else look._color_filter)


def has_any_stamp(shape) -> bool:
    return (
        getattr(shape, "_glow", None) is not None
        or getattr(shape, "_shadow", None) is not None
        or getattr(shape, "_hue", None) is not None
        or getattr(shape, "_gray", None) is not None
        or getattr(shape, "_tail", None) is not None
    )


def _reset_tail_motion(shape) -> None:
    """Clear per-instance follow motion history (plain floats, no Attributes)."""
    shape._tail_prev = None
    shape._tail_vx = 0.0
    shape._tail_vy = 0.0
    shape._tail_speed_scale = 0.0
    shape._tail_frame = None


def copy_stamps(dst, src) -> None:
    """Copy stamp fields (look refs + tail follow state) without re-apply side effects."""
    dst._glow = getattr(src, "_glow", None)
    dst._shadow = getattr(src, "_shadow", None)
    dst._hue = getattr(src, "_hue", None)
    dst._gray = getattr(src, "_gray", None)
    dst._tail = getattr(src, "_tail", None)
    dst._tail_follow = bool(getattr(src, "_tail_follow", False))
    dst._tail_locked_angle = getattr(src, "_tail_locked_angle", None)
    _reset_tail_motion(dst)  # motion history is per-instance
    dst._stamp_base_ff = getattr(src, "_stamp_base_ff", None)
    dst._stamp_base_lf = getattr(src, "_stamp_base_lf", None)
    # Live formula fields (owned Attributes) — share values by copying float payloads.
    for name in ("_tail_angle", "_tail_size", "_tail_amount"):
        src_v = getattr(src, name, None)
        if src_v is None:
            setattr(dst, name, None)
            continue
        if hasattr(src_v, "value"):
            setattr(dst, name, float(src_v.value))
        else:
            setattr(dst, name, float(src_v) if src_v is not None else None)


def init_stamp_fields(shape) -> None:
    """Zero stamp slots on a fresh PaintState / after look_like from defaults."""
    shape._glow = None
    shape._shadow = None
    shape._hue = None
    shape._gray = None
    shape._tail = None
    shape._tail_follow = False
    shape._tail_locked_angle = None
    _reset_tail_motion(shape)
    shape._tail_angle = None
    shape._tail_size = None
    shape._tail_amount = None
    shape._stamp_base_ff = None
    shape._stamp_base_lf = None


def _scalar(v, default: float = 0.0) -> float:
    try:
        if hasattr(v, "value"):
            return float(v.value)
        return float(v)
    except Exception:
        return default


def _center_xy(shape) -> Tuple[float, float]:
    try:
        c = getattr(shape, "center", None)
        if c is not None:
            return _scalar(getattr(c, "x", 0.0)), _scalar(getattr(c, "y", 0.0))
    except Exception:
        pass
    return 0.0, 0.0


def _pull_tail_num(v, default: float) -> float:
    if v is None:
        return default
    if callable(v) and not isinstance(v, type):
        try:
            return float(v())
        except Exception:
            return default
    return _scalar(v, default)


def _linked_field_value(shape, name: str):
    """Live value of a formula-linked stamp field, or ``None`` if unlinked.

    ``_link_field("_tail_angle", …)`` stores the result on a ``ScalarAnchor``
    (ink), while PaintState keeps a parallel slot. Draw/resolve must pull the
    anchor — ``getattr(shape, "_tail_angle")`` is the stale slot.
    """
    try:
        anchors = shape.__dict__.get("_field_anchors")
    except Exception:
        return None
    if not anchors:
        return None
    anchor = anchors.get(name)
    if anchor is None:
        return None
    return anchor.value


def _clock_dt_frame() -> Tuple[float, int]:
    """World ``dt`` and frame from builtins.clock (cheap; no framework lookup)."""
    try:
        import builtins
        clk = getattr(builtins, "clock", None)
        if clk is None:
            return 0.0, -1
        dt = float(getattr(clk, "_dt", None) if hasattr(clk, "_dt") else getattr(clk, "dt", 0.0) or 0.0)
        # Prefer raw _frame to avoid property overhead; fall back to .frame.
        if hasattr(clk, "_frame"):
            frame = int(clk._frame)
        else:
            frame = int(getattr(clk, "frame", -1) or -1)
        return dt, frame
    except Exception:
        return 0.0, -1


def _sync_tail_motion(shape) -> None:
    """Smooth center velocity; write trail ``_tail_angle`` and ``_tail_speed_scale``.

    Public angle is where the trail extends (behind motion = heading + 180°).
    Same ``clock.frame`` with unchanged center reuses cache (second draw must
    not see dx=0 and kill the trail). Position change in the same frame still
    integrates (unit tests: ``move_by`` then ``resolve_tail_angle``).
    """
    cx, cy = _center_xy(shape)
    prev = getattr(shape, "_tail_prev", None)
    dt_raw, frame = _clock_dt_frame()
    last_frame = getattr(shape, "_tail_frame", None)

    if prev is None:
        shape._tail_prev = (cx, cy)
        shape._tail_vx = 0.0
        shape._tail_vy = 0.0
        shape._tail_speed_scale = 0.0
        shape._tail_frame = frame
        return

    px, py = prev
    dx = cx - px
    dy = cy - py
    moved = abs(dx) > 1e-9 or abs(dy) > 1e-9

    if last_frame is not None and frame == last_frame and not moved:
        return

    if dt_raw <= 0.0:
        if not moved:
            # Engine pause: freeze state.
            shape._tail_frame = frame
            return
        dt = 1.0 / 60.0  # unit tests / teleports with no clock step
    else:
        dt = max(_TAIL_DT_MIN, min(_TAIL_DT_MAX, dt_raw))

    raw_x = dx / dt
    raw_y = dy / dt
    alpha = dt / (_TAIL_TAU + dt)
    vx = float(getattr(shape, "_tail_vx", 0.0) or 0.0)
    vy = float(getattr(shape, "_tail_vy", 0.0) or 0.0)
    vx += alpha * (raw_x - vx)
    vy += alpha * (raw_y - vy)
    speed = math.hypot(vx, vy)

    shape._tail_vx = vx
    shape._tail_vy = vy
    shape._tail_prev = (cx, cy)
    shape._tail_frame = frame
    shape._tail_speed_scale = min(_TAIL_SCALE_MAX, speed / _TAIL_REF_SPEED)

    if speed >= _TAIL_SPEED_EPS:
        # Public angle = trail direction (behind motion).
        shape._tail_angle = math.degrees(math.atan2(vy, vx)) + 180.0


def resolve_tail_angle(shape) -> float:
    """Degrees where the trail extends (ghosts along this heading), for draw."""
    locked = getattr(shape, "_tail_locked_angle", None)
    if locked is not None:
        return float(locked)
    if not getattr(shape, "_tail_follow", False):
        linked = _linked_field_value(shape, "_tail_angle")
        if linked is not None:
            return _pull_tail_num(linked, 0.0)
        return _pull_tail_num(getattr(shape, "_tail_angle", None), 0.0)
    _sync_tail_motion(shape)
    linked = _linked_field_value(shape, "_tail_angle")
    if linked is not None:
        return _pull_tail_num(linked, 0.0)
    return _pull_tail_num(getattr(shape, "_tail_angle", None), 0.0)


def resolve_tail_size(shape, look) -> float:
    # Author ``size=`` callable owns length — do not double-scale with velocity.
    if getattr(look, "_stamp_size_fn", None) is not None:
        linked = _linked_field_value(shape, "_tail_size")
        v = linked if linked is not None else getattr(shape, "_tail_size", None)
        return max(0.15, _pull_tail_num(v, 1.0))
    if getattr(shape, "_tail_follow", False):
        # Ensure motion is current when size is read without angle first.
        _sync_tail_motion(shape)
        base = float(getattr(look, "size", 1.0))
        linked = _linked_field_value(shape, "_tail_size")
        v = linked if linked is not None else getattr(shape, "_tail_size", None)
        if v is not None and not (callable(v) and not isinstance(v, type)):
            base = _pull_tail_num(v, base)
        scale = float(getattr(shape, "_tail_speed_scale", 0.0) or 0.0)
        # No 0.15 floor — stopped follow-tail must shrink to zero.
        return max(0.0, base * scale)
    linked = _linked_field_value(shape, "_tail_size")
    v = linked if linked is not None else getattr(shape, "_tail_size", None)
    if v is not None:
        return max(0.15, _pull_tail_num(v, 1.0))
    return max(0.15, float(getattr(look, "size", 1.0)))


def resolve_tail_amount(shape, look) -> float:
    linked = _linked_field_value(shape, "_tail_amount")
    v = linked if linked is not None else getattr(shape, "_tail_amount", None)
    if v is not None:
        return max(0.05, _pull_tail_num(v, 1.0))
    return max(0.05, float(getattr(look, "amount", 1.0)))


def draw_tail_ghosts(shape, skia_canvas, *, angle: float, size: float, amount: float, look) -> None:
    """Faded copies of geometry/blit, then caller draws the real body."""
    from .fx_quality import fidelity_is_survival
    from .recipes import _center_radius, _faded_host_paints, _host_line_width
    from .recipes import _is_line_shape, _shape_has_line

    cx, cy, _ = _center_radius(shape)
    rad = math.radians(float(angle))
    # ``angle`` is where the trail extends (0 = right, 90 = up).
    dx, dy = math.cos(rad), math.sin(rad)
    span = _TAIL_SPAN * float(size)
    n = 3 if fidelity_is_survival() else 5
    seed = getattr(look, "_seed_color", None)
    host_w = _host_line_width(shape)
    for i in range(n, 0, -1):
        t = i / n
        ox, oy = dx * span * t, dy * span * t
        # Keep ghost geometry near host size; trail reads via offset + alpha, not shrink.
        s = max(0.88, 1.0 - 0.08 * t)
        # Stronger falloff toward the tip (alpha), not the body scale.
        fade = (0.06 + 0.62 * ((1.0 - t) ** 1.75)) * float(amount)
        if seed is not None:
            a = float(seed[3] if len(seed) > 3 else 1.0) * fade
            col = (float(seed[0]), float(seed[1]), float(seed[2]), a)
            fill_p = None if _is_line_shape(shape) else look._fill_paint_from(col)
            stroke_p = None
            if _shape_has_line(shape) or _is_line_shape(shape):
                stroke_p = look._stroke_paint(color=col, width=host_w)
        else:
            fill_p, stroke_p = _faded_host_paints(shape, fade)
            # Filled hosts: drop contrast stroke so ghosts match body color
            # (outline-heavy tiny ghosts looked like a different tint).
            if fill_p is not None and not _is_line_shape(shape):
                stroke_p = None
        # Mark stamp tail so Sprite blits ghosts (role E path).
        shape._tail_ghosting = True
        skia_canvas.save()
        try:
            skia_canvas.translate(ox, oy)
            skia_canvas.translate(cx, cy)
            skia_canvas.scale(s, s)
            skia_canvas.translate(-cx, -cy)
            shape._geometry_draw(skia_canvas, fill_paint=fill_p, stroke_paint=stroke_p)
        finally:
            skia_canvas.restore()
            shape._tail_ghosting = False


def draw_cheap_glow_overlay(shape, skia_canvas) -> None:
    """CheapGlow dilated ADD bloom under the body (stamp path).

    Text paints its halo inside ``_geometry_draw`` (glyph strokes). Scaling
    the caption from center would inflate the whole string.
    """
    if scena_kind(shape) == "Text":
        return
    from .visuals import CheapGlow
    glow = getattr(shape, "_glow", None)
    if isinstance(glow, CheapGlow):
        glow._overlay_after_filters(shape, skia_canvas)


def draw_tail_stamp(shape, skia_canvas) -> None:
    """Unfiltered trail ghosts behind the live body. No-op when no tail."""
    tail = getattr(shape, "_tail", None)
    if tail is None:
        return
    ang = resolve_tail_angle(shape)
    size = resolve_tail_size(shape, tail)
    amount = resolve_tail_amount(shape, tail)
    follow = bool(getattr(shape, "_tail_follow", False))
    scale = float(getattr(shape, "_tail_speed_scale", 0.0) or 0.0)
    if follow and scale < _TAIL_SCALE_SKIP:
        return
    draw_tail_ghosts(
        shape, skia_canvas, angle=ang, size=size, amount=amount, look=tail,
    )


def draw_body_with_stamps(shape, skia_canvas) -> None:
    """Tail ghosts (if any), CheapGlow underlay, then costume/body.

    Dilated ADD copies first, sharp body on top, so the halo cannot bleach
    the silhouette the way a post-body ring did.
    """
    visual = getattr(shape, "visual", None)

    def _draw_body():
        if visual is not None:
            render_sprite = getattr(visual, "_render_sprite_body", None)
            if callable(render_sprite) and getattr(type(shape), "_is_sprite_body", False):
                render_sprite(shape, skia_canvas)
                return
            if getattr(visual, "_is_multipass", False):
                visual._render(shape, skia_canvas)
                return
        shape._geometry_draw(skia_canvas)
        fn = getattr(visual, "_overlay_after_filters", None) if visual is not None else None
        if callable(fn):
            fn(shape, skia_canvas)

    draw_tail_stamp(shape, skia_canvas)
    draw_cheap_glow_overlay(shape, skia_canvas)
    _draw_body()


def install_tail_from_look(shape, look, *, follow: bool, locked_angle: Optional[float]) -> None:
    """Wire per-host Tail fields from a coerced Tail look."""
    shape._tail = look
    shape._tail_follow = bool(follow)
    shape._tail_locked_angle = locked_angle
    _reset_tail_motion(shape)
    if look is None:
        shape._tail_angle = None
        shape._tail_size = None
        shape._tail_amount = None
        return

    ang_fn = getattr(look, "_stamp_angle_fn", None)
    size_fn = getattr(look, "_stamp_size_fn", None)
    amount_fn = getattr(look, "_stamp_amount_fn", None)
    follow = follow or bool(getattr(look, "_stamp_follow", False))
    shape._tail_follow = follow and ang_fn is None and locked_angle is None

    if locked_angle is not None:
        shape._tail_angle = float(locked_angle)
        shape._tail_follow = False
    elif ang_fn is not None and hasattr(shape, "_link_field"):
        from .state import Attribute
        if not isinstance(getattr(shape, "_tail_angle", None), Attribute):
            # Seed a float Attribute via setattr then link.
            object.__setattr__(shape, "_tail_angle", 0.0)
            # Prefer Container link if available
            try:
                shape._link_field("_tail_angle", ang_fn)
            except Exception:
                shape._tail_angle = ang_fn  # pull at draw via callable
        else:
            shape._link_field("_tail_angle", ang_fn)
        shape._tail_follow = False
        shape._tail_locked_angle = None
    elif follow:
        shape._tail_angle = 0.0
    else:
        shape._tail_angle = float(getattr(look, "angle", 0.0))

    if size_fn is not None and hasattr(shape, "_link_field"):
        try:
            object.__setattr__(shape, "_tail_size", 1.0)
            shape._link_field("_tail_size", size_fn)
        except Exception:
            shape._tail_size = size_fn
    else:
        shape._tail_size = float(getattr(look, "size", 1.0))

    if amount_fn is not None and hasattr(shape, "_link_field"):
        try:
            object.__setattr__(shape, "_tail_amount", 1.0)
            shape._link_field("_tail_amount", amount_fn)
        except Exception:
            shape._tail_amount = amount_fn
    else:
        shape._tail_amount = float(getattr(look, "amount", 1.0))
