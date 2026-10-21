"""``Graphic.confine`` — stateless position math against a measuring region.

Plain helper: read pose, clamp / bounce / wrap in the region's local frame,
write pose. No registration, no datapath step, no collision enrollment.
"""
from __future__ import annotations

import math
from typing import FrozenSet, List, Optional, Set, Tuple

from .box import frame_kind, oriented_xy, region_frame, _FRAME_GRAPHIC_NAMES
from .entity import scena_kind
from .shapes import get_xy

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
    """Return local half-width / half-height of the effective confine region
    for a self frame ``(cx, cy, w, h, ang)`` (projected onto the region's axes)."""
    if by == "center":
        return abs(region_w) * 0.5, abs(region_h) * 0.5
    assert self_frame is not None
    _scx, _scy, sw, sh, sang = self_frame
    proj_w, proj_h = _projected_half(abs(sw) * 0.5, abs(sh) * 0.5, sang, region_ang)
    return _region_half_for(region_w, region_h, by, proj_w, proj_h)


def _region_half_for(
    region_w: float, region_h: float, by: str, proj_w: float, proj_h: float,
) -> Tuple[float, float]:
    """The region's half-extents shrunk (``"box"``) or grown (``"overlap"``) by
    self's half-extents along its axes."""
    rh_w = abs(region_w) * 0.5
    rh_h = abs(region_h) * 0.5
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


def _outline_points(graphic) -> Optional[List[Tuple[float, float]]]:
    """World points whose hull is the outline of a kind with no frame:
    a regular polygon's vertices, a free polygon's, a line's ends, a track's
    samples, a point. ``None``: a kind confine cannot measure."""
    params = getattr(graphic, "_placement_params", None)
    verts = getattr(graphic, "_world_verts", None)
    if callable(params) and callable(verts):           # Triangle, RegularPolygon
        cx, cy, r, phi0 = params()
        return list(verts(cx, cy, r, phi0))
    kind = scena_kind(graphic)
    if kind == "Polygon":
        return [get_xy(v, bare=True) for v in graphic._vertices]
    if kind == "Line":
        x1, y1, x2, y2 = graphic._segment_xy()
        return [(x1, y1), (x2, y2)]
    if kind == "Track":
        xs, ys = graphic._tables()[:2]          # the track's own frame
        world = graphic._world_of
        return [world(x, y) for x, y in zip(xs, ys)]
    if kind == "Point":
        return [get_xy(graphic, bare=True)]
    return None


def _outline_extent(graphic, region_ang: float) -> Tuple[float, float, float, float, bool]:
    """``(mx, my, hw, hh, moved)`` of the shape's outline along the region's
    axes: the middle (world) and the half-extents of its region-local bounding
    box. ``moved``: the middle is not the pose point, so the correction moves
    the pose by the same amount (``confine_graphic``).

    A frame kind is measured by its frame turned onto the region's axes, except
    the round ones: a Circle by its radius, an Ellipse by its true extent at its
    angle (their frame turned with them reached past the curve: a rotated ball
    stopped up to 0.41 r short of the wall). Other kinds by their points.
    """
    kind = frame_kind(graphic)
    if kind in _FRAME_GRAPHIC_NAMES:
        cx, cy, w, h, ang = region_frame(graphic)      # pulls linked angle / scale
        a, b = abs(w) * 0.5, abs(h) * 0.5
        if kind == "Circle":
            return cx, cy, a, a, False
        if kind == "Ellipse":
            rel = math.radians(float(ang) - float(region_ang))
            c, s = math.cos(rel), math.sin(rel)
            return cx, cy, math.hypot(a * c, b * s), math.hypot(a * s, b * c), False
        pw, ph = _projected_half(a, b, ang, region_ang)
        return cx, cy, pw, ph, False
    d = getattr(graphic, "__dict__", None)
    if d and d.get("_field_anchors"):
        pull = getattr(type(graphic), "_pull_property_anchors", None)
        if pull is not None:
            pull(graphic)
    pts = _outline_points(graphic)
    if not pts:
        name = type(graphic).__name__
        raise TypeError(
            f'{name}.confine(by="box" / "overlap") measures the outline of a shape, '
            f'and a {kind} has none. Use by="center" (the default).'
        )
    if region_ang:
        rad = math.radians(-float(region_ang))
        c, s = math.cos(rad), math.sin(rad)
        lxs = [x * c - y * s for x, y in pts]
        lys = [x * s + y * c for x, y in pts]
    else:
        lxs = [x for x, _y in pts]
        lys = [y for _x, y in pts]
    x0, x1, y0, y1 = min(lxs), max(lxs), min(lys), max(lys)
    mx, my = oriented_xy(0.0, 0.0, 0.5 * (x0 + x1), 0.5 * (y0 + y1), region_ang)
    return mx, my, 0.5 * (x1 - x0), 0.5 * (y1 - y0), True


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
    outline = None if by == "center" else _outline_extent(graphic, rang)
    if outline is None:
        hw, hh = abs(rw) * 0.5, abs(rh) * 0.5
    else:
        hw, hh = _region_half_for(rw, rh, by, outline[2], outline[3])

    # The point compared to the region: the pose ``center`` for by="center"
    # (what the author placed), the drawn frame's middle for "box" /
    # "overlap" (the extents are measured about it). A Sprite with a sheet
    # anchor has the two apart (anchor="bottom": center is the feet), and
    # ``_move_to`` places the pose point, so the correction is applied as a
    # delta to it. Before (2026-10-09, tutorial 17), the drawn middle was
    # written back as the feet: every clamp lifted the sprite by half its
    # height, a frame at a time.
    pose = getattr(type(graphic), "_move_to_xy", None)
    if outline is not None:
        x, y = outline[0], outline[1]
    elif pose is None:
        x, y = _graphic_center_xy(graphic)
    else:
        x, y = pose(graphic)
    nx, ny, sides, new_vel = _confine_point(
        x, y, rcx, rcy, hw, hh, rang, action, vel=vel_xy,
    )
    if outline is not None and (pose is not None or outline[4]):
        # The outline's middle moved: move the pose point by as much (an
        # anchored Sprite's feet, a Triangle's centroid, a Line's midpoint).
        px, py = pose(graphic) if pose is not None else _graphic_center_xy(graphic)
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
