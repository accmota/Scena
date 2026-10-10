"""``Graphic.confine`` — stateless position math against a measuring region.

Plain helper: read pose, clamp / bounce / wrap in the region's local frame,
write pose. No registration, no datapath step, no collision enrollment.
"""
from __future__ import annotations

import math
from typing import FrozenSet, Optional, Set, Tuple

from .box import frame_kind, oriented_xy, region_frame, _FRAME_GRAPHIC_NAMES

__all__ = [
    "confine_graphic",
]

_BY = frozenset({"center", "box", "overlap"})
_ACTIONS = frozenset({"clamp", "bounce", "wrap"})
_SIDES = frozenset({"left", "right", "top", "bottom"})


def _world_to_local(
    x: float, y: float, cx: float, cy: float, ang: float,
) -> Tuple[float, float]:
    dx = x - cx
    dy = y - cy
    if ang:
        rad = math.radians(-float(ang))
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a
    return dx, dy


def _vec_world_to_local(vx: float, vy: float, ang: float) -> Tuple[float, float]:
    if ang:
        rad = math.radians(-float(ang))
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        return vx * cos_a - vy * sin_a, vx * sin_a + vy * cos_a
    return vx, vy


def _vec_local_to_world(lvx: float, lvy: float, ang: float) -> Tuple[float, float]:
    if ang:
        rad = math.radians(float(ang))
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        return lvx * cos_a - lvy * sin_a, lvx * sin_a + lvy * cos_a
    return lvx, lvy


def _projected_half(
    self_hw: float, self_hh: float, self_ang: float, region_ang: float,
) -> Tuple[float, float]:
    """Project self's half-extents onto the region's local axes."""
    rel = math.radians(float(self_ang) - float(region_ang))
    c = abs(math.cos(rel))
    s = abs(math.sin(rel))
    return self_hw * c + self_hh * s, self_hw * s + self_hh * c


def _effective_half_extents(
    region_w: float,
    region_h: float,
    by: str,
    self_frame: Optional[Tuple[float, float, float, float, float]],
    region_ang: float,
) -> Tuple[float, float]:
    """Return local half-width / half-height of the effective confine region."""
    rh_w = abs(region_w) * 0.5
    rh_h = abs(region_h) * 0.5
    if by == "center":
        return rh_w, rh_h
    assert self_frame is not None
    _scx, _scy, sw, sh, sang = self_frame
    proj_w, proj_h = _projected_half(abs(sw) * 0.5, abs(sh) * 0.5, sang, region_ang)
    if by == "box":
        # Remainder: too-big object pins to region center (half → 0), not an error.
        return max(0.0, rh_w - proj_w), max(0.0, rh_h - proj_h)
    # by == "overlap": grow so action fires only after self's box fully exits.
    return rh_w + proj_w, rh_h + proj_h


def _wrap_axis(v: float, half: float) -> Tuple[float, bool, Optional[str]]:
    """Wrap ``v`` into ``[-half, half]``, carrying overshoot. Return (new, changed, side)."""
    span = 2.0 * half
    if span <= 0.0:
        changed = v != 0.0
        side: Optional[str] = None
        if v > 0.0:
            side = "pos"
        elif v < 0.0:
            side = "neg"
        return 0.0, changed, side
    if -half <= v <= half:
        return v, False, None
    side = "pos" if v > half else "neg"
    wrapped = ((v + half) % span) - half
    # Keep +half representable as the positive edge (not -half from modulo).
    if wrapped == -half and v > 0.0:
        wrapped = half
    return wrapped, True, side


def _confine_point(
    x: float,
    y: float,
    cx: float,
    cy: float,
    hw: float,
    hh: float,
    ang: float,
    action: str,
    vel: Optional[Tuple[float, float]] = None,
) -> Tuple[float, float, FrozenSet[str], Optional[Tuple[float, float]]]:
    """Pure local-frame confine. Returns (nx, ny, sides, new_vel_or_None)."""
    lx, ly = _world_to_local(x, y, cx, cy, ang)
    sides: Set[str] = set()

    if action == "wrap":
        nlx, ch_x, sx = _wrap_axis(lx, hw)
        nly, ch_y, sy = _wrap_axis(ly, hh)
        if ch_x:
            sides.add("right" if sx == "pos" else "left")
            lx = nlx
        if ch_y:
            sides.add("top" if sy == "pos" else "bottom")
            ly = nly
    else:
        # clamp and bounce share position correction
        if lx > hw:
            lx = hw
            sides.add("right")
        elif lx < -hw:
            lx = -hw
            sides.add("left")
        if ly > hh:
            ly = hh
            sides.add("top")
        elif ly < -hh:
            ly = -hh
            sides.add("bottom")

    new_vel: Optional[Tuple[float, float]] = None
    if action == "bounce" and sides:
        assert vel is not None
        lvx, lvy = _vec_world_to_local(vel[0], vel[1], ang)
        if "left" in sides or "right" in sides:
            lvx = -lvx
        if "top" in sides or "bottom" in sides:
            lvy = -lvy
        new_vel = _vec_local_to_world(lvx, lvy, ang)

    nx, ny = oriented_xy(cx, cy, lx, ly, ang)
    return nx, ny, frozenset(sides), new_vel


def _graphic_center_xy(graphic) -> Tuple[float, float]:
    center_xy = getattr(graphic, "_center_xy", None)
    if callable(center_xy):
        return center_xy()
    center = getattr(graphic, "center", None)
    if center is None:
        raise TypeError(
            f"{type(graphic).__name__} has no center — confine needs a pose center"
        )
    from .shapes import get_xy
    return get_xy(center, bare=True)


def _self_frame_for_by(graphic, by: str) -> Optional[Tuple[float, float, float, float, float]]:
    if by == "center":
        return None
    name = type(graphic).__name__
    if frame_kind(graphic) not in _FRAME_GRAPHIC_NAMES:
        raise TypeError(
            f"{name}.box is unsupported — Box needs a rectangular frame. "
            "Use Rect, Square, Ellipse, Circle, Sprite, or Svg."
        )
    return region_frame(graphic)


def confine_graphic(
    graphic,
    region,
    *,
    by: str = "center",
    action: str = "clamp",
) -> FrozenSet[str]:
    """Clamp / bounce / wrap ``graphic`` against ``region``. Return acted sides."""
    from .entity import _refuse_if_destroyed
    _refuse_if_destroyed(graphic, "confine")
    if by not in _BY:
        raise TypeError(
            f"confine by= must be one of {sorted(_BY)}, got {by!r}"
        )
    if action not in _ACTIONS:
        raise TypeError(
            f"confine action= must be one of {sorted(_ACTIONS)}, got {action!r}"
        )

    vel_xy: Optional[Tuple[float, float]] = None
    if action == "bounce":
        vel = getattr(graphic, "vel", None)
        if vel is None:
            raise TypeError(
                "confine(action='bounce') requires self.vel to be set — "
                "e.g. self.vel = Vec2(220, 140)"
            )
        vel_xy = (float(vel.x), float(vel.y))

    rcx, rcy, rw, rh, rang = region_frame(region)
    self_frame = _self_frame_for_by(graphic, by)
    hw, hh = _effective_half_extents(rw, rh, by, self_frame, rang)

    # The point compared to the region: the pose ``center`` for by="center"
    # (what the author placed), the drawn frame's middle for "box" /
    # "overlap" (the extents are measured about it). A Sprite with a sheet
    # anchor has the two apart (anchor="bottom": center is the feet), and
    # ``_move_to`` places the pose point, so the correction is applied as a
    # delta to it. Before (2026-10-09, tutorial 14), the drawn middle was
    # written back as the feet: every clamp lifted the sprite by half its
    # height, a frame at a time.
    pose = getattr(type(graphic), "_move_to_xy", None)
    if self_frame is not None:
        x, y = self_frame[0], self_frame[1]
    elif pose is None:
        x, y = _graphic_center_xy(graphic)
    else:
        x, y = pose(graphic)
    nx, ny, sides, new_vel = _confine_point(
        x, y, rcx, rcy, hw, hh, rang, action, vel=vel_xy,
    )
    if pose is not None and self_frame is not None:
        px, py = pose(graphic)
        nx, ny = px + (nx - x), py + (ny - y)
        x, y = px, py

    if sides:
        move_to = getattr(graphic, "_move_to", None)
        if callable(move_to):
            move_to(nx, ny)
            # The collision sweep must match where the body went (review
            # 2026-10-09 S7-4): a wrap is a placement (no sweep across the
            # field); a clamp / bounce cuts the frame's motion short, so the
            # correction joins the pending motion and the sweep ends at the
            # wall, not at the point past it (a ghost @collide behind it).
            from .collision import note_collider_motion, note_collider_placement
            if action == "wrap":
                note_collider_placement(graphic)
            else:
                note_collider_motion(graphic, nx - x, ny - y)
        else:
            graphic.center = (nx, ny)
        if new_vel is not None:
            graphic.vel = new_vel

    return sides
