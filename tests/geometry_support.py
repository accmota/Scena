"""Registry and oracles for the geometry contract suite (``test_geometry_contract``).

One entry per Graphic kind × constructor model (plus Box), built from a small
parameter dict ``p = {"x", "y", "s", "r"}`` (position, size factor, rotation in
degrees) so the same shape can be drawn at any pose. Helpers read what the
contract talks about:

* point parts — every Point slot (Defining or Derivate), every ``points[k]``,
  Text's parts, and the named points of ``.box``;
* scalar parts — lengths and areas;
* drawn geometry — the point set that fixes what is painted;
* transforms — the expected image of a point under a pose verb.

Reads never raise out of here: a read that fails is returned as an
``ReadError`` value so a sweep can record it as a violation.
"""
from __future__ import annotations

import math
import warnings
from typing import Callable, Dict, List, Optional, Tuple

from scena import (
    Anchor, Box, Circle, Ellipse, EquilateralTriangle, Line, Point, Polygon, Rect,
    RegularPolygon, Sprite, Square, Svg, Text, Track, clock,
)
from scena.process import reset_process_scheduler, tick_processes
from scena.state import ContainerSlot

XY = Tuple[float, float]
P0 = {"x": 3.0, "y": -2.0, "s": 1.0, "r": 17.0}
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
       '<rect width="40" height="20" fill="red"/></svg>')


class ReadError:
    """A read that raised (recorded, never propagated)."""

    def __init__(self, exc: BaseException):
        self.name = type(exc).__name__

    def __repr__(self) -> str:
        return f"<{self.name}>"


def _dir(deg: float) -> XY:
    a = math.radians(deg)
    return (math.cos(a), math.sin(a))


def _at(p, dx: float, dy: float) -> XY:
    return (p["x"] + dx * p["s"], p["y"] + dy * p["s"])


def _polar(p, r: float, deg: float) -> XY:
    ux, uy = _dir(deg)
    return (p["x"] + r * p["s"] * ux, p["y"] + r * p["s"] * uy)


def _quiet(fn):
    def build(p):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return fn(p)
    return build


def _rotated(obj, deg):
    if deg:
        obj.rotate_by(deg)
    return obj


def _ref_line(p):
    """Reference for the parallel / perpendicular Line models (placed away from p)."""
    return Line(p1=_at(p, -20, 15), p2=_polar(p, 40, p["r"] + 10))


def _ref_circle(p):
    """Reference for the tangent Line models, centred on p."""
    return Circle(center=(p["x"], p["y"]), radius=9 * p["s"])


# ---------------------------------------------------------------------------
# Registry: name -> builder(p)
# ---------------------------------------------------------------------------

KINDS: Dict[str, Callable] = {
    "Point": lambda p: Point(p["x"], p["y"]),
    "Anchor": lambda p: Anchor(p["x"], p["y"]),
    "Line point_point": lambda p: Line(p1=(p["x"], p["y"]), p2=_polar(p, 40, p["r"])),
    "Line point_vec": lambda p: Line(p1=(p["x"], p["y"]), vec=(40 * p["s"] * _dir(p["r"])[0], 40 * p["s"] * _dir(p["r"])[1])),
    "Line center_length": lambda p: Line(center=(p["x"], p["y"]), length=40 * p["s"], angle=p["r"]),
    "Line point_angle_length": lambda p: Line(p1=(p["x"], p["y"]), angle=p["r"], length=40 * p["s"]),
    "Line point_dx_dy": lambda p: Line(p1=(p["x"], p["y"]), dx=30 * p["s"], dy=12 * p["s"]),
    # Relational models: the subject follows a reference shape built with it
    # (Shapes Design — Cross-shape relational constructors). The reference is
    # kept alive by the subject (``_ref``).
    "Line parallel_point": lambda p: Line(p1=(p["x"], p["y"]), parallel_to=_ref_line(p), length=30 * p["s"]),
    "Line parallel_dist": lambda p: Line(dist=8 * p["s"], parallel_to=_ref_line(p)),
    "Line perpendicular_point": lambda p: Line(p1=(p["x"], p["y"]), perpendicular_to=_ref_line(p), length=30 * p["s"]),
    "Line tangent_angle": lambda p: Line(circle=_ref_circle(p), at_angle=p["r"] + 30, length=30 * p["s"]),
    "Line tangent_point": lambda p: Line(circle=_ref_circle(p), from_point=_polar(p, 30, p["r"]), side="left"),
    "Circle center_radius": lambda p: Circle(center=(p["x"], p["y"]), radius=9 * p["s"], angle=p["r"]),
    "Circle center_perimeter": lambda p: Circle(center=(p["x"], p["y"]), perimeter_point=_polar(p, 9, p["r"] + 30)),
    "Circle two_points": lambda p: Circle(p1=_polar(p, 9, p["r"] + 40), p2=_polar(p, 9, p["r"] + 220)),
    "Circle arc": lambda p: Circle(center=(p["x"], p["y"]), radius=9 * p["s"], angle=p["r"], spread=120),
    "Ellipse center_wh": lambda p: Ellipse(center=(p["x"], p["y"]), width=30 * p["s"], height=12 * p["s"], angle=p["r"]),
    "Ellipse focal_points": lambda p: Ellipse(fp1=_polar(p, 8, p["r"] + 180), fp2=_polar(p, 8, p["r"]), major_axis=24 * p["s"]),
    "Ellipse from_rect": lambda p: Ellipse(from_rect=Rect(center=(p["x"], p["y"]), width=30 * p["s"], height=12 * p["s"], angle=p["r"])),
    "Polygon": lambda p: _rotated(Polygon(points=[_at(p, -6, -4), _at(p, 7, -3), _at(p, 5, 6), _at(p, -4, 5)]), p["r"]),
    "RegularPolygon center_radius": lambda p: RegularPolygon(center=(p["x"], p["y"]), radius=6 * p["s"], n=5, angle=p["r"]),
    "RegularPolygon center_side": lambda p: RegularPolygon(center=(p["x"], p["y"]), side=6 * p["s"], n=4, angle=p["r"]),
    "RegularPolygon vertex_side": lambda p: RegularPolygon(vertex=(p["x"], p["y"]), side=6 * p["s"], n=6, angle=p["r"]),
    "EquilateralTriangle center_radius": lambda p: EquilateralTriangle(center=(p["x"], p["y"]), radius=6 * p["s"], angle=p["r"]),
    "EquilateralTriangle center_side": lambda p: EquilateralTriangle(center=(p["x"], p["y"]), side=6 * p["s"], angle=p["r"]),
    "EquilateralTriangle vertex_side": lambda p: EquilateralTriangle(vertex=(p["x"], p["y"]), side=6 * p["s"], angle=p["r"]),
    "Rect center_wh": lambda p: Rect(center=(p["x"], p["y"]), width=40 * p["s"], height=16 * p["s"], angle=p["r"]),
    "Rect top_left_wh": lambda p: Rect(top_left=(p["x"], p["y"]), width=40 * p["s"], height=16 * p["s"], angle=p["r"]),
    "Rect corner_corner": lambda p: Rect(p1=(p["x"], p["y"]), p2=_at(p, 40, 16), angle=p["r"]),
    "Rect corner_corner reversed": lambda p: Rect(p1=_at(p, 40, 0), p2=_at(p, 0, 16), angle=p["r"]),
    "Rect point_vec": lambda p: Rect(p1=(p["x"], p["y"]), vec=(40 * p["s"], 16 * p["s"]), angle=p["r"]),
    "Rect point_vec negative": lambda p: Rect(p1=(p["x"], p["y"]), vec=(-40 * p["s"], 16 * p["s"]), angle=p["r"]),
    "Rect spine cap": lambda p: Rect(p1=(p["x"], p["y"]), p2=_polar(p, 40, p["r"]), height=12 * p["s"], anchor="cap"),
    "Rect spine square": lambda p: Rect(p1=(p["x"], p["y"]), p2=_polar(p, 40, p["r"]), height=12 * p["s"], anchor="square"),
    "Rect spine side_left": lambda p: Rect(p1=(p["x"], p["y"]), p2=_polar(p, 40, p["r"]), height=12 * p["s"], anchor="side_left"),
    "Rect spine side_right": lambda p: Rect(p1=(p["x"], p["y"]), p2=_polar(p, 40, p["r"]), height=12 * p["s"], anchor="side_right"),
    "Square center_length": lambda p: Square(center=(p["x"], p["y"]), length=20 * p["s"], angle=p["r"]),
    "Square top_left_length": lambda p: Square(top_left=(p["x"], p["y"]), length=20 * p["s"], angle=p["r"]),
    "Track line point_point": lambda p: Track.line(p1=(p["x"], p["y"]), p2=_polar(p, 40, p["r"])),
    "Track line length": lambda p: Track.line(length=40 * p["s"], angle=p["r"], p1=(p["x"], p["y"])),
    "Track circle": lambda p: _rotated(Track.circle(radius=12 * p["s"], center=(p["x"], p["y"])), p["r"]),
    "Track eight": lambda p: _rotated(Track.eight(width=60 * p["s"], height=30 * p["s"], center=(p["x"], p["y"])), p["r"]),
    # A reversed() view shares its host's tables and pose: every verb and read
    # on the view must agree with what the view draws (Tracks Design).
    "Track eight reversed": lambda p: _rotated(Track.eight(width=60 * p["s"], height=30 * p["s"], center=(p["x"], p["y"])), p["r"]).reversed(),
    "Track circle reversed": lambda p: _rotated(Track.circle(radius=12 * p["s"], center=(p["x"], p["y"])), p["r"]).reversed(),
    "Track line point_point reversed": lambda p: Track.line(p1=(p["x"], p["y"]), p2=_polar(p, 40, p["r"])).reversed(),
    "Sprite": _quiet(lambda p: _rotated(Sprite("diff_missing.png", center=(p["x"], p["y"])), p["r"])),
    "Svg": _quiet(lambda p: _rotated(Svg(SVG, center=(p["x"], p["y"])), p["r"])),
    "Text center": lambda p: _rotated(Text("geo", center=(p["x"], p["y"])), p["r"]),
    "Text top_left": lambda p: _rotated(Text("geo", top_left=(p["x"], p["y"])), p["r"]),
    "Text top_right": lambda p: _rotated(Text("geo", top_right=(p["x"], p["y"])), p["r"]),
    "Box center_wh": lambda p: Box(center=(p["x"], p["y"]), width=40 * p["s"], height=16 * p["s"], angle=p["r"]),
    "Box top_left_wh": lambda p: Box(top_left=(p["x"], p["y"]), width=40 * p["s"], height=16 * p["s"], angle=p["r"]),
    "Box corner_corner": lambda p: Box(p1=(p["x"], p["y"]), p2=_at(p, 40, 16), angle=p["r"]),
    "Box point_vec": lambda p: Box(p1=(p["x"], p["y"]), vec=(40 * p["s"], 16 * p["s"]), angle=p["r"]),
}

# Kinds with an area (hit test / collapse / box containment make sense).
AREA_KINDS = {k for k in KINDS if k.split()[0] in (
    "Circle", "Ellipse", "Polygon", "RegularPolygon", "EquilateralTriangle", "Rect", "Square")}
FRAME_KINDS = {k for k in KINDS if k.split()[0] in (
    "Rect", "Square", "Ellipse", "Circle", "Sprite", "Svg", "Text")}


def build(kind: str, p: Optional[dict] = None):
    return KINDS[kind](dict(P0) if p is None else p)


# Models linked to a reference shape by construction. A pose verb that would
# write a linked part is refused (LinkedAttributeError, nothing changed); a
# verb that runs must keep every contract (Shapes Design — Linked parts).
RELATIONAL_MODELS = frozenset({
    "PARALLEL_POINT", "PARALLEL_DIST", "PERPENDICULAR_POINT", "TANGENT_ANGLE",
    "TANGENT_POINT", "FROM_RECT",
})


def is_relational(obj) -> bool:
    return getattr(getattr(obj, "model", None), "name", None) in RELATIONAL_MODELS


def refused(obj, err) -> bool:
    """A link refusal on a relational kind: the contract's allowed answer."""
    return err == "LinkedAttributeError" and is_relational(obj)


def is_box(obj) -> bool:
    return isinstance(obj, Box)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def xy(p) -> XY:
    if isinstance(p, tuple):
        return (float(p[0]), float(p[1]))
    return (float(p.x), float(p.y))


def safe(fn):
    try:
        return fn()
    except (Exception, RecursionError) as exc:  # noqa: BLE001
        return ReadError(exc)


def center_of(obj) -> XY:
    if isinstance(obj, Point):
        return xy(obj)
    return xy(obj.center)


def rotation_of(obj) -> float:
    return float(obj.angle)


BOX_NAMES = ("top_left", "top_right", "bottom_left", "bottom_right", "top_center", "right_center")


def point_parts(obj) -> Dict[str, Callable[[], XY]]:
    """name -> reader for every point part of ``obj`` (see module doc)."""
    if isinstance(obj, Point):
        return {"self": lambda o=obj: xy(o)}
    out: Dict[str, Callable[[], XY]] = {}
    slots = obj._field_slots() if hasattr(obj, "_field_slots") else {}
    for name, slot in slots.items():
        if isinstance(slot, ContainerSlot) and slot.container_class.__name__ == "Point":
            out[name] = (lambda o=obj, n=name: xy(getattr(o, n)))
    pts = getattr(type(obj), "points", None)
    if pts is not None and not isinstance(obj, Track):
        for k in range(len(obj.points)):
            out[f"points[{k}]"] = (lambda o=obj, k=k: xy(o.points[k]))
    if not is_box(obj) and type(obj).__name__ in (
            "Rect", "Square", "Ellipse", "Circle", "Sprite", "Svg", "Text"):
        for n in BOX_NAMES:
            out[f"box.{n}"] = (lambda o=obj, n=n: xy(getattr(o.box, n)))
    return out


def vector_parts(obj) -> Dict[str, Callable[[], XY]]:
    """name -> reader for every Vec2 part (``vec``): read-back, not point stability."""
    out: Dict[str, Callable[[], XY]] = {}
    slots = obj._field_slots() if hasattr(obj, "_field_slots") else {}
    for name, slot in slots.items():
        if isinstance(slot, ContainerSlot) and slot.container_class.__name__ == "Vec2":
            out[name] = (lambda o=obj, n=name: xy(getattr(o, n)))
    return out


def part_group(name: str) -> str:
    """Collapse indexed / box parts to one key per family."""
    if name.startswith("points["):
        return "points"
    if name.startswith("box."):
        return "box"
    return name


# Kinds whose ``scale`` is a pose zoom on top of their size knobs (Sprite Design —
# "One scale per sprite": ``width`` / ``height`` are the knob, ``.box`` is the
# drawn frame). Their knobs do not follow ``scale``; Shapes bake scale into
# their sizes, so theirs do.
POSE_SCALED = ("Sprite", "Svg", "Text", "Track")


def scale_is_pose(obj) -> bool:
    return type(obj).__name__ in POSE_SCALED


def can_flip(obj) -> bool:
    """Every Graphic flips except Text (mirrored text is unreadable: it raises)."""
    return type(obj).__name__ not in ("Box", "Text")


def angle_keeps(obj):
    """What ``angle =`` keeps fixed (Shapes Design — Geometry contract).

    ``angle`` is a field: setting it keeps the model's other inputs, so the
    point the shape was placed by stays. Returns that point, ``"lean"`` for
    Rect ``p1=, p2=`` (both corners stay; the box leans — not a rigid turn),
    or ``None`` when the heading is derived or the kind is placed by its
    center: then ``angle =`` is ``rotate_to`` about the center.
    """
    model = getattr(getattr(obj, "model", None), "name", None)
    kind = type(obj).__name__
    if kind in ("Rect", "Square"):
        return {"CENTER_WH": obj.center, "TOP_LEFT_WH": obj.top_left,
                "POINT_VEC": obj.p1, "CORNER_CORNER": "lean"}.get(model)
    if kind == "Ellipse" and model == "CENTER_WH":
        return obj.center
    if kind in ("RegularPolygon", "EquilateralTriangle"):
        return obj.vertex if model == "VERTEX_SIDE" else obj.center
    if kind == "Line":
        return {"CENTER_LENGTH_ANGLE": obj.center, "POINT_ANGLE_LENGTH": obj.p1}.get(model)
    if kind == "Text" and getattr(obj, "_anchor", None) is not None:
        return getattr(obj, obj._anchor)
    return None


LENGTHS = ("width", "height", "radius", "side", "length", "major_axis", "perimeter_length", "c")
AREAS = ("signed_area",)


def scalar_parts(obj) -> Dict[str, Callable[[], float]]:
    out: Dict[str, Callable[[], float]] = {}
    for name in LENGTHS + AREAS:
        if name == "length" and isinstance(obj, Track):
            continue            # Track.length is the travel length (checked with the outline)
        if hasattr(type(obj), name):
            out[name] = (lambda o=obj, n=name: float(getattr(o, n)))
    return out


def _sample_conic(cx, cy, rx, ry, ang_deg, n=24) -> List[XY]:
    c, s = math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg))
    out = []
    for i in range(n):
        t = 2 * math.pi * i / n
        lx, ly = rx * math.cos(t), ry * math.sin(t)
        out.append((cx + lx * c - ly * s, cy + lx * s + ly * c))
    return out


def drawn(obj) -> List[XY]:
    """Point set that fixes the painted geometry (order-free)."""
    from scena.box import region_frame
    from scena.track import shape_outline
    if isinstance(obj, Point):
        return [xy(obj)]
    if isinstance(obj, Line):
        return [xy(obj.p1), xy(obj.p2)]
    if is_box(obj) or type(obj).__name__ in ("Sprite", "Svg", "Text"):
        cx, cy, w, h, ang = region_frame(obj) if not is_box(obj) else obj._oriented_frame()
        return frame_corners(cx, cy, w, h, ang)
    if isinstance(obj, Circle):
        # The disk (or pie) pinned to its heading: a full circle is drawn the
        # same at any heading, but its frame turns, so sample in the frame.
        cx, cy = xy(obj.center)
        r = abs(float(obj.radius))
        a, sp = float(obj.angle), float(obj.spread)
        if sp < 360.0:
            offsets = (-sp / 2, 0.0, sp / 2)
            pts = [(cx, cy)]
        else:
            offsets = (0.0, 90.0, 180.0, 270.0)
            pts = []
        return pts + [(cx + r * math.cos(math.radians(a + d)), cy + r * math.sin(math.radians(a + d)))
                      for d in offsets]
    if isinstance(obj, Ellipse):
        cx, cy, w, h, ang = obj._oriented_frame()
        return _sample_conic(cx, cy, abs(w) / 2, abs(h) / 2, ang, 24)
    verts, _closed = shape_outline(obj, samples=64)
    return [(float(x), float(y)) for x, y in verts]


def frame_corners(cx, cy, w, h, ang) -> List[XY]:
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    return [(cx + sx * w / 2 * c - sy * h / 2 * s, cy + sx * w / 2 * s + sy * h / 2 * c)
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def as_set(points: List[XY], nd: int = 4) -> List[XY]:
    return sorted((round(x, nd) + 0.0, round(y, nd) + 0.0) for x, y in points)


def same_set(a: List[XY], b: List[XY], tol: float = 1e-5) -> bool:
    """Order-free equality: every point of ``a`` has a partner in ``b`` and back."""
    if len(a) != len(b):
        return False
    def covered(xs, ys):
        return all(any(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for q in ys) for p in xs)
    return covered(a, b) and covered(b, a)


def close(a, b, tol: float = 1e-5) -> bool:
    if isinstance(a, ReadError) or isinstance(b, ReadError):
        return False
    if isinstance(a, tuple):
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
    return abs(a - b) <= tol * max(1.0, abs(b))


# ---------------------------------------------------------------------------
# Transforms: expected image of a point
# ---------------------------------------------------------------------------

def turned(pt: XY, pivot: XY, deg: float) -> XY:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    dx, dy = pt[0] - pivot[0], pt[1] - pivot[1]
    return (pivot[0] + dx * c - dy * s, pivot[1] + dx * s + dy * c)


def scaled(pt: XY, pivot: XY, k: float) -> XY:
    return (pivot[0] + k * (pt[0] - pivot[0]), pivot[1] + k * (pt[1] - pivot[1]))


def mirrored(pt: XY, center: XY, axis: str) -> XY:
    return (2 * center[0] - pt[0], pt[1]) if axis == "x" else (pt[0], 2 * center[1] - pt[1])


# ---------------------------------------------------------------------------
# Timed verbs
# ---------------------------------------------------------------------------

def settle(seconds: float = 0.5, dt: float = 0.05) -> None:
    """Run timed verbs to completion (world clock + process tick)."""
    t = 0.0
    while t < seconds:
        clock.advance(dt)
        tick_processes()
        t += dt


def reset_clock() -> None:
    reset_process_scheduler()
    clock.scale = 1.0
    clock.paused = False
