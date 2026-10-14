"""Pure geometry for the editor: outlines, hit tests, handles, resize, snap.

Items are ``level_format`` dicts. World units, y up, ``angle`` in degrees
counter-clockwise (Scena's convention). Nothing here touches Scena objects.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

Pt = Tuple[float, float]
AREA = ("rect", "ellipse", "image")
# Handle sign pairs, counter-clockwise from bottom-left (local frame).
HANDLE_SIGNS = ((-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0))
CORNER_SIGNS = ((-1, -1), (1, -1), (1, 1), (-1, 1))


def rot(x: float, y: float, deg: float) -> Pt:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return x * c - y * s, x * s + y * c


def snap(v: float, grid: float) -> float:
    return round(v / grid) * grid if grid > 0 else v


def snap_point(p: Pt, grid: float) -> Pt:
    return snap(p[0], grid), snap(p[1], grid)


def snap_angle(deg: float, step: float = 15.0) -> float:
    return (round(deg / step) * step) % 360.0


# ---------------------------------------------------------------------------
# Outlines and bounds
# ---------------------------------------------------------------------------

def frame(item: Dict[str, Any]) -> Tuple[float, float, float, float, float]:
    """``(cx, cy, width, height, angle)`` of an area item (circle: its square)."""
    if item["kind"] == "circle":
        d = 2 * item["radius"]
        return item["center"][0], item["center"][1], d, d, 0.0
    return (item["center"][0], item["center"][1], item["width"], item["height"],
            item.get("angle", 0.0))


def corners(item: Dict[str, Any]) -> List[Pt]:
    cx, cy, w, h, r = frame(item)
    out = []
    for sx, sy in CORNER_SIGNS:
        dx, dy = rot(sx * w / 2, sy * h / 2, r)
        out.append((cx + dx, cy + dy))
    return out


def regular_vertices(item: Dict[str, Any]) -> List[Pt]:
    """A regular polygon's corners: vertex 0 toward ``angle``, then counter-
    clockwise every 360/n degrees — as ``RegularPolygon`` places them."""
    (cx, cy), r, n = item["center"], item["radius"], item["n"]
    a0 = item.get("angle", 0.0)
    return [(cx + r * math.cos(math.radians(a0 + i * 360.0 / n)),
             cy + r * math.sin(math.radians(a0 + i * 360.0 / n))) for i in range(n)]


def outline(item: Dict[str, Any]) -> List[Pt]:
    """Points whose bounding box is the item's bounding box."""
    kind = item["kind"]
    if kind == "regular_polygon":
        return regular_vertices(item)
    if kind in AREA:
        return corners(item)
    if kind == "circle":
        (cx, cy), r = item["center"], item["radius"]
        return [(cx - r, cy - r), (cx + r, cy + r)]
    if kind == "line":
        return [tuple(item["p1"]), tuple(item["p2"])]
    if kind in ("polygon", "track"):
        return [tuple(p) for p in item["points"]]
    return [tuple(item["center"])]


def track_curve(item: Dict[str, Any]) -> List[Pt]:
    """The line a track draws: its points, or with ``smooth`` > 0 the curve
    Scena samples through them (hit tests follow the drawing, not the
    straight segments). Bounds stay the points' box, as ``LevelItem.center``."""
    pts = [tuple(p) for p in item["points"]]
    smooth = item.get("smooth", 0.0)
    if not smooth or len(pts) < 2:
        return pts
    from ._engine import track_curve as sample
    return sample(pts, closed=bool(item.get("closed")), smooth=smooth)


def aabb(item: Dict[str, Any]) -> Tuple[float, float, float, float]:
    pts = outline(item)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def union_aabb(items: Sequence[Dict[str, Any]]) -> Optional[Tuple[float, float, float, float]]:
    if not items:
        return None
    boxes = [aabb(i) for i in items]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def inside(item: Dict[str, Any], box: Tuple[float, float, float, float]) -> bool:
    """True when the item's bounding box is fully inside ``box`` (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = aabb(item)
    return x0 >= box[0] and y0 >= box[1] and x1 <= box[2] and y1 <= box[3]


# ---------------------------------------------------------------------------
# Hit test
# ---------------------------------------------------------------------------

def _dist_to_segment(p: Pt, a: Pt, b: Pt) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _in_polygon(p: Pt, pts: Sequence[Pt]) -> bool:
    x, y = p
    inside_ = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside_ = not inside_
    return inside_


def local(item: Dict[str, Any], x: float, y: float) -> Pt:
    """A world point in an area item's own frame (origin at its center)."""
    cx, cy, _w, _h, r = frame(item)
    return rot(x - cx, y - cy, -r)


def contains(item: Dict[str, Any], x: float, y: float, tol: float = 0.0) -> bool:
    """Is ``(x, y)`` on the item? ``tol`` widens thin things (lines, points)."""
    kind = item["kind"]
    if kind in ("rect", "image"):
        lx, ly = local(item, x, y)
        _cx, _cy, w, h, _r = frame(item)
        return abs(lx) <= w / 2 + tol and abs(ly) <= h / 2 + tol
    if kind == "ellipse":
        lx, ly = local(item, x, y)
        a, b = item["width"] / 2 + tol, item["height"] / 2 + tol
        if a <= 0 or b <= 0:
            return False
        return (lx / a) ** 2 + (ly / b) ** 2 <= 1.0
    if kind == "circle":
        return math.dist((x, y), item["center"]) <= item["radius"] + tol
    if kind == "line":
        return _dist_to_segment((x, y), item["p1"], item["p2"]) <= tol
    if kind in ("polygon", "regular_polygon"):
        pts = (regular_vertices(item) if kind == "regular_polygon"
               else [tuple(p) for p in item["points"]])
        if _in_polygon((x, y), pts):
            return True
        return any(_dist_to_segment((x, y), pts[i], pts[(i + 1) % len(pts)]) <= tol
                   for i in range(len(pts)))
    if kind == "track":
        pts = track_curve(item)
        segs = list(zip(pts, pts[1:]))
        if item.get("closed") and len(pts) > 2:
            segs.append((pts[-1], pts[0]))
        return any(_dist_to_segment((x, y), a, b) <= tol for a, b in segs)
    return math.dist((x, y), item["center"]) <= tol


# ---------------------------------------------------------------------------
# Moving
# ---------------------------------------------------------------------------

def translate(item: Dict[str, Any], dx: float, dy: float) -> Dict[str, Any]:
    """The changed fields of ``item`` moved by ``(dx, dy)``."""
    def move(p):
        return (p[0] + dx, p[1] + dy)
    kind = item["kind"]
    if kind == "line":
        return {"p1": move(item["p1"]), "p2": move(item["p2"])}
    if kind in ("polygon", "track"):
        return {"points": tuple(move(p) for p in item["points"])}
    return {"center": move(item["center"])}


def nearest_corner(box: Tuple[float, float, float, float], p: Pt) -> Pt:
    """The corner of ``box`` (x0, y0, x1, y1) nearest ``p``, axis by axis;
    a tie takes the min side (a grab at the exact center → bottom-left)."""
    x0, y0, x1, y1 = box
    return (x0 if abs(p[0] - x0) <= abs(p[0] - x1) else x1,
            y0 if abs(p[1] - y0) <= abs(p[1] - y1) else y1)


def snapped_delta(ref: Pt, dx: float, dy: float, grid: float) -> Pt:
    """``(dx, dy)`` adjusted so ``ref`` (the grabbed corner of the selection's
    box, :func:`nearest_corner`) lands on the grid — the corner you hold snaps,
    as when drawing or resizing."""
    return snap(ref[0] + dx, grid) - ref[0], snap(ref[1] + dy, grid) - ref[1]


# ---------------------------------------------------------------------------
# Handles
# ---------------------------------------------------------------------------

class Handle:
    """A grab point on the selected item.

    ``role``: ``"resize"`` (``key`` = sign pair), ``"rotate"``, ``"radius"``,
    ``"end"`` (``key`` = ``"p1"`` / ``"p2"``) or ``"vertex"`` (``key`` = index).
    """
    __slots__ = ("role", "key", "x", "y")

    def __init__(self, role: str, key: Any, x: float, y: float):
        self.role, self.key, self.x, self.y = role, key, x, y

    def __repr__(self) -> str:
        return f"Handle({self.role}, {self.key!r}, {self.x:.1f}, {self.y:.1f})"


def handles(item: Dict[str, Any], rotate_offset: float) -> List[Handle]:
    """The handles of ``item``. ``rotate_offset``: world distance of the rotate
    knob above the top edge (a fixed screen distance / zoom)."""
    kind = item["kind"]
    if kind in AREA:
        cx, cy, w, h, r = frame(item)
        out = []
        signs = CORNER_SIGNS if kind == "image" else HANDLE_SIGNS   # images keep aspect
        for sx, sy in signs:
            dx, dy = rot(sx * w / 2, sy * h / 2, r)
            out.append(Handle("resize", (sx, sy), cx + dx, cy + dy))
        dx, dy = rot(0, h / 2 + rotate_offset, r)
        out.append(Handle("rotate", None, cx + dx, cy + dy))
        return out
    if kind == "circle":
        (cx, cy), radius = item["center"], item["radius"]
        return [Handle("radius", None, cx + radius, cy)]
    if kind == "regular_polygon":
        # Radius on vertex 0; the rotate knob further out on the same spoke.
        (cx, cy), radius = item["center"], item["radius"]
        a = math.radians(item.get("angle", 0.0))
        ux, uy = math.cos(a), math.sin(a)
        return [Handle("radius", None, cx + radius * ux, cy + radius * uy),
                Handle("rotate", None, cx + (radius + rotate_offset) * ux,
                       cy + (radius + rotate_offset) * uy)]
    if kind == "line":
        return [Handle("end", "p1", *item["p1"]), Handle("end", "p2", *item["p2"])]
    if kind in ("polygon", "track"):
        return [Handle("vertex", i, p[0], p[1]) for i, p in enumerate(item["points"])]
    return []


def anchor_for(item: Dict[str, Any], signs: Tuple[int, int]) -> Pt:
    """World point that stays fixed while dragging the handle ``signs``."""
    cx, cy, w, h, r = frame(item)
    dx, dy = rot(-signs[0] * w / 2, -signs[1] * h / 2, r)
    return cx + dx, cy + dy


def resize(item: Dict[str, Any], signs: Tuple[int, int], anchor: Pt, pointer: Pt,
           *, keep_aspect: bool = False) -> Dict[str, Any]:
    """New ``center`` / ``width`` / ``height`` for dragging handle ``signs`` to
    ``pointer`` with the opposite handle fixed at ``anchor`` (rotated frame).

    Edge handles change one axis; corner handles both. ``keep_aspect``
    (images) scales both by the larger stretch.
    """
    _cx, _cy, w0, h0, r = frame(item)
    sx, sy = signs
    dx, dy = rot(pointer[0] - anchor[0], pointer[1] - anchor[1], -r)
    w = abs(dx) if sx else w0
    h = abs(dy) if sy else h0
    if keep_aspect and sx and sy and w0 > 0 and h0 > 0:
        scale = max(abs(dx) / w0, abs(dy) / h0)
        w, h = w0 * scale, h0 * scale
        dx = math.copysign(w, dx if dx else sx)
        dy = math.copysign(h, dy if dy else sy)
    # Local center relative to the anchor: half the extent on the moved axes;
    # on an untouched axis the anchor (an edge midpoint) is already centered.
    lcx = (dx / 2) if sx else 0.0
    lcy = (dy / 2) if sy else 0.0
    wx, wy = rot(lcx, lcy, r)
    return {"center": (anchor[0] + wx, anchor[1] + wy), "width": w, "height": h}


def heading_toward(item: Dict[str, Any], pointer: Pt) -> float:
    """The ``angle`` that turns ``item``'s rotate knob to ``pointer``: an
    area's top (local +y) for rect / ellipse / image, a regular polygon's
    vertex 0 (its ``angle`` is that direction)."""
    if item["kind"] == "regular_polygon":
        c = item["center"]
        return math.degrees(math.atan2(pointer[1] - c[1], pointer[0] - c[0])) % 360.0
    return angle_toward(item["center"], pointer)


def angle_toward(center: Pt, pointer: Pt) -> float:
    """Rotation that points the item's top (local +y) at ``pointer``."""
    return (math.degrees(math.atan2(pointer[1] - center[1], pointer[0] - center[0])) - 90.0) % 360.0


def resize_cursor(item: Dict[str, Any], signs: Tuple[int, int]) -> str:
    """``"ew"`` / ``"ns"`` / ``"nesw"`` / ``"nwse"`` for a handle, following the
    item's angle (y up, no camera rotation)."""
    _cx, _cy, w, h, r = frame(item)
    return frame_cursor(w, h, r, signs)


def frame_cursor(w: float, h: float, angle: float, signs: Tuple[int, int]) -> str:
    """The resize cursor for handle ``signs`` of a ``w`` × ``h`` frame turned ``angle``."""
    r = angle
    hx, hy = rot(signs[0] * max(w, 1e-9) / 2, signs[1] * max(h, 1e-9) / 2, r)
    a = math.degrees(math.atan2(hy, hx)) % 180.0
    return ("ew", "nesw", "ns", "nwse")[int(((a + 22.5) % 180.0) // 45.0)]


# ---------------------------------------------------------------------------
# A group selection: rotate and scale together
# ---------------------------------------------------------------------------
# Several items turn about the center of their box and scale evenly about the
# corner opposite the dragged one. Even scaling only: a circle, a regular
# polygon, a rotated area or an image cannot stretch by different amounts in
# x and y and stay what it is (an ellipse, a parallelogram), so the group has
# corner handles only.

MIN_SCALE = 0.01     # a group never shrinks to nothing or turns inside out


def group_handles(box_frame: Tuple[float, float, float, float, float],
                  rotate_offset: float) -> List[Handle]:
    """Corner handles (``"group_resize"``, key = sign pair) and the rotate
    knob (``"group_rotate"``) of a selection's frame ``(cx, cy, w, h, angle)``."""
    cx, cy, w, h, r = box_frame
    out = []
    for sx, sy in CORNER_SIGNS:
        dx, dy = rot(sx * w / 2, sy * h / 2, r)
        out.append(Handle("group_resize", (sx, sy), cx + dx, cy + dy))
    dx, dy = rot(0, h / 2 + rotate_offset, r)
    out.append(Handle("group_rotate", None, cx + dx, cy + dy))
    return out


def scale_item(item: Dict[str, Any], origin: Pt, s: float) -> Dict[str, Any]:
    """The changed fields of ``item`` scaled by ``s`` about ``origin``: places
    and sizes; angles stay. Every kind stays its kind (images keep their aspect)."""
    ox, oy = origin

    def sc(p):
        return (ox + (p[0] - ox) * s, oy + (p[1] - oy) * s)
    kind = item["kind"]
    if kind == "line":
        return {"p1": sc(item["p1"]), "p2": sc(item["p2"])}
    if kind in ("polygon", "track"):
        return {"points": tuple(sc(p) for p in item["points"])}
    out: Dict[str, Any] = {"center": sc(item["center"])}
    if kind in AREA:
        out["width"] = item["width"] * s
        out["height"] = item["height"] * s
    elif kind in ("circle", "regular_polygon"):
        out["radius"] = item["radius"] * s
    return out


def rotate_item(item: Dict[str, Any], origin: Pt, deg: float) -> Dict[str, Any]:
    """The changed fields of ``item`` turned ``deg`` (counter-clockwise) about
    ``origin``: places turn, and so does ``angle`` where the kind has one."""
    ox, oy = origin

    def turn(p):
        dx, dy = rot(p[0] - ox, p[1] - oy, deg)
        return (ox + dx, oy + dy)
    kind = item["kind"]
    if kind == "line":
        return {"p1": turn(item["p1"]), "p2": turn(item["p2"])}
    if kind in ("polygon", "track"):
        return {"points": tuple(turn(p) for p in item["points"])}
    out: Dict[str, Any] = {"center": turn(item["center"])}
    if kind in AREA or kind == "regular_polygon":
        out["angle"] = (item.get("angle", 0.0) + deg) % 360.0
    return out


def group_scale(box: Tuple[float, float, float, float], signs: Tuple[int, int],
                pointer: Pt, grid: float) -> Tuple[float, Pt]:
    """``(s, anchor)`` for dragging corner ``signs`` of ``box`` to ``pointer``.

    The anchor is the opposite corner. ``s`` is the larger stretch of the two
    axes (as an image's corner handle keeps its aspect), from the snapped
    pointer: the dragged corner lands on the grid on that axis. A zero-size
    axis (a row of points) does not count. Never below ``MIN_SCALE``: dragging
    past the anchor does not mirror the group.
    """
    x0, y0, x1, y1 = box
    sx, sy = signs
    anchor = (x1 if sx < 0 else x0, y1 if sy < 0 else y0)
    w, h = x1 - x0, y1 - y0
    p = snap_point(pointer, grid)
    ratios = []
    if w > 0:
        ratios.append((p[0] - anchor[0]) * sx / w)
    if h > 0:
        ratios.append((p[1] - anchor[1]) * sy / h)
    s = max(ratios) if ratios else 1.0
    return max(s, MIN_SCALE), anchor
