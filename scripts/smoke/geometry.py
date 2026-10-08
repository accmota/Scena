"""
geometry.py — smoke: the geometry contract (point stability, flips, heading,
setting angle, scale models, Circle rim, Text frame, Track views, clones).

Every page draws colored pins **linked** (``@=`` / lambda) to named points. A
pin that leaves its point, or a named point that jumps to another corner, is
the bug class this smoke guards. Each page also runs live numeric checks,
shown on the aux line as ✓ / ✗ (✗ = look closer).

Pages (A/S)
-----------
  Named points   Rect p1/p2 crossing: names stay with their points; Square
  Flips          every kind vs its unflipped twin: a true mirror about center
  Heading        angle is the heading on every kind (arrow = angle)
  Set angle      angle= keeps the placement point; derived kinds turn about center
  Scale          pivot stays; Shapes bake scale, Sprite / Text keep it as zoom
  Circle rim     p1 = perimeter point at the heading, p2 opposite, box turns
  Text           parts = the drawn frame; anchor pinned; no flips; linked refuses
  Track views    reversed() shares the host pose; line center; pivot turns
  Clones         a clone keeps pose, model, anchor form (same look, same numbers)
  Edge cases     focal ellipse → segment, Rect collapse, Text scale 0→1,
                 polygon stats, Line full turns

Usage
-----
    python scripts/smoke/geometry.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — Geometry contract")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(title="Geometry contract", expect="", keys="", status="ready", show_aux=True)

_SHEET = Path(__file__).resolve().parents[2] / "examples" / "media" / "shooter" / "sheet.xml"
space = Sheet(str(_SHEET))

PIN_COLORS = {
    "top_left": "tomato", "top_right": "lime green", "bottom_left": "deep sky blue",
    "bottom_right": "gold", "p1": "white", "p2": "violet",
}
FAINT = Color(0.55, 0.6, 0.7, 0.55)
COMMON_KEYS = "A/S page  ·  SPACE reset page"

_PAGES: list = []
_page_i = 0
_owned: list = []
_checks: list = []          # (label, fn) evaluated every frame
_flags: dict = {}           # label -> bool, set by actions (one-off checks)
_syncs: list = []           # callables run every frame (box outlines, readouts)
_tick: list = []            # callables(dt) run every frame (animations)
_S: dict = {}               # page state


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def page(name: str, expect: str, keys: str):
    def deco(fn):
        _PAGES.append({"name": name, "expect": expect, "keys": keys, "build": fn, "actions": {}})
        return fn
    return deco


def action(key: str, what: str):
    """Register a key action on the page being built (and for the headless check)."""
    def deco(fn):
        _PAGES[_page_i]["actions"][key] = (what, fn)
        return fn
    return deco


def own(obj):
    _owned.append(obj)
    return obj


def check(label: str, fn) -> None:
    _checks.append((label, fn))


def flag(label: str, ok: bool) -> None:
    _flags[label] = bool(ok)


def xy(p):
    if isinstance(p, tuple):
        return (float(p[0]), float(p[1]))
    return (float(p.x), float(p.y))


def near(a, b, tol: float = 1e-4) -> bool:
    a, b = xy(a), xy(b)
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def same_angle(a: float, b: float, tol: float = 1e-3) -> bool:
    d = (float(a) - float(b)) % 360.0
    return min(d, 360.0 - d) <= tol


def direction(a, b) -> float:
    a, b = xy(a), xy(b)
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def mirrored(p, c, fx: bool, fy: bool):
    x, y = xy(p)
    cx, cy = xy(c)
    return (2 * cx - x if fx else x, 2 * cy - y if fy else y)


def cap(text: str, pos, *, size: int = 13, color=(0.78, 0.84, 0.94, 1)):
    return own(Text(text, center=pos, font_size=size, color=Color(*color)))


def live_cap(fn, pos, *, size: int = 12):
    """A caption whose text is re-read every frame."""
    t = cap("", pos, size=size, color=(0.92, 0.82, 0.45, 1))
    _syncs.append(lambda: setattr(t, "text", fn()))
    return t


def pin(point_fn, color, label: str = "", *, radius: float = 6.0, dy: float = 16.0):
    """A dot linked to a point part (and its label). The link is the test."""
    dot = own(Circle(center=point_fn, radius=radius, color=color))
    dot.line = Color(0, 0, 0, 0.8)
    dot.line_width = 1.5
    if label:
        # Name the dot (a Scena value) in the formula: a helper call hides its sources.
        own(Text(label, center=lambda: _offset(dot.center, 0, dy), font_size=12, color=Color(color)))
    return dot


def _offset(p, dx, dy):
    x, y = xy(p)
    return (x + dx, y + dy)


def ring(pos, color="white", radius: float = 11.0):
    """A fixed (unlinked) ring: where a point is supposed to stay."""
    r = own(Circle(center=xy(pos), radius=radius))
    r.fill = None
    r.line = Color(color)
    r.line_width = 2
    return r


def heading_arrow(obj, length: float = 70.0, color="white"):
    def tip():
        cx, cy = xy(obj.center)
        a = math.radians(float(obj.angle))
        return (cx + length * math.cos(a), cy + length * math.sin(a))
    ln = own(Line(p1=lambda: obj.center, p2=tip))
    ln.line = Color(color)
    ln.line_width = 3
    head = own(Circle(center=tip, radius=5, color=color))
    # The drawn arrow (read bare, as draw does — a pulled read would re-run the
    # formula and hide one that was never told the heading changed).
    arrows = _S.setdefault("arrows", [])
    if not arrows:
        check("arrows follow angle",
              lambda: all(near(a._segment_xy()[2:], t(), 1e-3) for a, t in _S.get("arrows", ())))
    arrows.append((ln, tip))
    return ln, head, tip


def box_outline(obj, color="cyan"):
    """A Rect redrawn every frame from ``obj.box`` (a fresh measuring Box)."""
    b = obj.box
    r = own(Rect(center=xy(b.center), width=max(float(b.width), 1e-3),
                 height=max(float(b.height), 1e-3), angle=float(b.angle)))
    r.fill = None
    r.line = Color(color)
    r.line_width = 1.5

    def sync():
        if not getattr(obj, "is_alive", False):
            return
        bb = obj.box
        r.center = xy(bb.center)
        r.width = max(float(bb.width), 1e-3)
        r.height = max(float(bb.height), 1e-3)
        r.angle = float(bb.angle)
    _syncs.append(sync)
    return r


def outline_only(shape, color="gold", width: float = 2.0):
    shape.fill = None
    shape.line = Color(color)
    shape.line_width = width
    return shape


def try_call(fn):
    """Run ``fn``; return the error text (or '' when it did not raise)."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — the smoke shows the author error
        return f"{type(exc).__name__}: {exc}"
    return ""


# ---------------------------------------------------------------------------
# page 1 — Named points
# ---------------------------------------------------------------------------

@page("Named points",
      "Drag p1 across p2 (or D): top_right stays on p2 even when p2 is visually on the left — names never jump",
      f"{COMMON_KEYS}  ·  drag handles  ·  D cross p1 over p2  ·  Q/W rotate  ·  X/Y flip  ·  J/K scale")
def page_names():
    r = own(Rect(p1=(380, 320), p2=(640, 480), color=(0.85, 0.7, 0.2, 0.25)))
    outline_only(r, "gold")
    r.fill = Color(0.85, 0.7, 0.2, 0.18)
    r.show_handles()
    for name in ("top_left", "top_right", "bottom_left", "bottom_right"):
        pin(lambda n=name: getattr(r, n), PIN_COLORS[name], name)
    own(Text("p1", center=lambda: _offset(r.p1, 0, -18), font_size=12, color=Color("white")))
    own(Text("p2", center=lambda: _offset(r.p2, 0, -18), font_size=12, color=Color("violet")))
    cap("Rect(p1=, p2=) — p1 starts bottom-left, so top_right is p2 for life", (510, 250))

    sq = own(Square(top_left=(900, 480), length=150, angle=20, color=(0.3, 0.7, 0.5, 0.25)))
    outline_only(sq, "sea green")
    sq.fill = Color(0.3, 0.7, 0.5, 0.18)
    for name in ("top_left", "top_right", "bottom_left", "bottom_right"):
        pin(lambda n=name: getattr(sq, n), PIN_COLORS[name], name)
    cap("Square(top_left=) turned 20°", (975, 250))
    _S.update(r=r, sq=sq)

    check("top_right ≡ p2", lambda: near(r.top_right, r.p2))
    check("bottom_left ≡ p1", lambda: near(r.bottom_left, r.p1))
    check("Square corners stay a square",
          lambda: abs(math.dist(xy(sq.top_left), xy(sq.top_right)) - math.dist(xy(sq.top_left), xy(sq.bottom_left))) < 1e-4)

    @action("D", "cross p1 over p2")
    def _cross():
        p1, p2 = xy(r.p1), xy(r.p2)
        r.p1 = (2 * p2[0] - p1[0], p1[1])
        hud.status = "p1 crossed over p2: top_right is still p2 (now visually on the left)"

    _pose_actions([r, sq])


def _pose_actions(objs, *, flips=True, scales=True):
    @action("Q", "rotate −15°")
    def _q():
        for o in objs:
            o.rotate_by(-15)
        hud.status = "rotate_by(−15) about each center"

    @action("W", "rotate +15°")
    def _w():
        for o in objs:
            o.rotate_by(15)
        hud.status = "rotate_by(+15) about each center"

    if flips:
        @action("X", "flip_x")
        def _x():
            for o in objs:
                o.flip_x = not o.flip_x
            hud.status = f"flip_x = {objs[0].flip_x}"

        @action("Y", "flip_y")
        def _y():
            for o in objs:
                o.flip_y = not o.flip_y
            hud.status = f"flip_y = {objs[0].flip_y}"

    if scales:
        @action("J", "scale ×0.8")
        def _j():
            for o in objs:
                o.scale_by(0.8)
            hud.status = "scale_by(0.8)"

        @action("K", "scale ×1.25")
        def _k():
            for o in objs:
                o.scale_by(1.25)
            hud.status = "scale_by(1.25)"


# ---------------------------------------------------------------------------
# page 2 — Flips
# ---------------------------------------------------------------------------

def _flip_kinds():
    return [
        ("Line", lambda: Line(p1=(-50, -20), p2=(50, 25)), lambda o: o.p1),
        ("Circle arc", lambda: Circle(center=(0, 0), radius=50, angle=30, spread=120), lambda o: o.p1),
        ("Ellipse center_wh", lambda: Ellipse(center=(0, 0), width=110, height=50, angle=20), lambda o: o.fp1),
        ("Ellipse foci", lambda: Ellipse(fp1=(-35, -10), fp2=(30, 15), major_axis=110), lambda o: o.fp1),
        ("Polygon", lambda: Polygon(points=[(-50, -30), (45, -30), (55, 25), (-30, 35)]), lambda o: o.points[0]),
        ("RegularPolygon vertex=", lambda: RegularPolygon(vertex=(-20, -40), side=45, n=5, angle=15), lambda o: o.points[0]),
        ("EquilateralTriangle", lambda: EquilateralTriangle(center=(0, 0), radius=50, angle=10), lambda o: o.points[0]),
        ("Rect spine", lambda: Rect(p1=(-55, -15), p2=(50, 20), height=40, anchor="side_left"), lambda o: o.top_right),
        ("Square top_left=", lambda: Square(top_left=(-40, 40), length=80, angle=15), lambda o: o.top_left),
    ]


@page("Flips",
      "Each shape is the mirror of its grey unflipped twin about the center (+). The dot is points[0] / p1 / a named point: it lands on the twin's dot mirrored",
      f"{COMMON_KEYS}  ·  X/Y flip  ·  Q/W rotate both (flip is a mirror at any heading)")
def page_flips():
    kinds = _flip_kinds()
    cols = 3
    items = []
    for i, (name, make, dot_of) in enumerate(kinds):
        cx = 300 + (i % cols) * 400
        cy = 620 - (i // cols) * 210
        twin = own(make())
        twin.move_by(cx, cy)
        outline_only(twin, FAINT, 1.5)
        shape = own(make())
        shape.move_by(cx, cy)
        outline_only(shape, "orange", 2.5)
        pin(lambda o=twin, f=dot_of: f(o), FAINT, radius=5)
        pin(lambda o=shape, f=dot_of: f(o), "orange", radius=6)
        mx, my = xy(shape.center)
        own(Line(p1=(mx - 10, my), p2=(mx + 10, my))).line = Color("white")
        own(Line(p1=(mx, my - 10), p2=(mx, my + 10))).line = Color("white")
        cap(name, (cx, cy - 90), size=12)
        items.append((name, twin, shape, dot_of, xy(shape.center)))
    _S["items"] = items

    def mirrors():
        for _name, twin, shape, dot_of, _c in items:
            fx, fy = shape.flip_x, shape.flip_y
            if not near(dot_of(shape), mirrored(dot_of(twin), twin.center, fx, fy), 1e-3):
                return False
        return True

    check("dot = twin's dot mirrored", mirrors)
    check("centers stay", lambda: all(near(s.center, c, 1e-3) for _n, _t, s, _d, c in items))

    @action("X", "flip_x")
    def _x():
        for _n, _t, s, _d, _c in items:
            s.flip_x = not s.flip_x
        hud.status = f"flip_x = {items[0][2].flip_x} (twice = identity)"

    @action("Y", "flip_y")
    def _y():
        for _n, _t, s, _d, _c in items:
            s.flip_y = not s.flip_y
        hud.status = f"flip_y = {items[0][2].flip_y}"

    @action("Q", "rotate −15° (both)")
    def _q():
        for _n, t, s, _d, _c in items:
            t.rotate_by(-15)
            s.rotate_by(-15)

    @action("W", "rotate +15° (both)")
    def _w():
        for _n, t, s, _d, _c in items:
            t.rotate_by(15)
            s.rotate_by(15)


# ---------------------------------------------------------------------------
# page 3 — Heading
# ---------------------------------------------------------------------------

@page("Heading",
      "The arrow is `angle` from the center. It points at the front of every kind: Line direction, arc middle, vertex 0, triangle apex (0° = right), width axis, ship nose, text baseline",
      f"{COMMON_KEYS}  ·  Q/W rotate  ·  X flip_x (heading → 180 − θ; Text refuses)")
def page_heading():
    objs = [
        ("Line", Line(p1=(160, 560), p2=(300, 610), color="white")),
        ("Circle arc", Circle(center=(470, 580), radius=60, angle=0, spread=100, color="orchid")),
        ("RegularPolygon", RegularPolygon(center=(720, 580), radius=60, n=5, color="medium orchid")),
        ("EquilateralTriangle", EquilateralTriangle(center=(980, 580), radius=60, color="orange")),
        ("Rect", Rect(center=(1220, 580), width=120, height=50, color="steel blue")),
        ("Ellipse", Ellipse(center=(230, 330), width=130, height=60, color="tomato")),
        ("Polygon (pose heading)", Polygon(points=[(430, 290), (540, 300), (520, 370), (440, 360)], color="sea green")),
        ("Sprite (art_angle=90)", Sprite(space, frame="playerShip1_blue.png", center=(720, 330), height=70, art_angle=90)),
        ("Text", Text("heading", center=(980, 330), font_size=28)),
        ("Track.eight", Track.eight(width=150, height=70, center=(1220, 330), color="cyan", line_width=2)),
    ]
    for name, o in objs:
        own(o)
        heading_arrow(o, 75, "white")
        cap(name, (float(o.center.x), float(o.center.y) - 105), size=12)
        live_cap(lambda o=o: f"angle {float(o.angle):.1f}°", (float(o.center.x), float(o.center.y) - 122))
    d = dict(objs)
    line, arc, poly, tri, rect, text = (d["Line"], d["Circle arc"], d["RegularPolygon"],
                                        d["EquilateralTriangle"], d["Rect"], d["Text"])

    check("Line: p1→p2", lambda: same_angle(direction(line.p1, line.p2), line.angle))
    check("arc: p1 at heading", lambda: same_angle(direction(arc.center, arc.p1), arc.angle))
    check("polygon: vertex 0", lambda: same_angle(direction(poly.center, poly.points[0]), poly.angle))
    check("triangle: apex", lambda: same_angle(direction(tri.center, tri.points[0]), tri.angle))
    check("Rect: width axis", lambda: same_angle(direction(rect.left_center, rect.right_center), rect.angle))
    check("Text: baseline", lambda: same_angle(direction(text.top_left, text.top_right), text.angle))
    flip_objs = [o for n, o in objs if n != "Text"]

    @action("Q", "rotate −15°")
    def _q():
        for _n, o in objs:
            o.rotate_by(-15)

    @action("W", "rotate +15°")
    def _w():
        for _n, o in objs:
            o.rotate_by(15)

    @action("X", "flip_x (all but Text)")
    def _x():
        before = [float(o.angle) for o in flip_objs]
        for o in flip_objs:
            o.flip_x = not o.flip_x
        ok = all(same_angle(o.angle, 180.0 - b) for o, b in zip(flip_objs, before))
        flag("flip_x: heading 180 − θ", ok)
        err = try_call(lambda: setattr(text, "flip_x", True))
        hud.status = f"flip_x on all; Text: {err or 'UNEXPECTED: no error'}"
        flag("Text refuses a flip", bool(err))


# ---------------------------------------------------------------------------
# page 4 — Set angle
# ---------------------------------------------------------------------------

_INPUT_MODELS = [
    ("Rect top_left=", lambda: Rect(top_left=(140, 620), width=170, height=70, color=(0.3, 0.55, 0.9, 0.4)), "top_left"),
    ("Rect p1=, vec=", lambda: Rect(p1=(420, 560), vec=(150, 60), color=(0.3, 0.55, 0.9, 0.4)), "p1"),
    ("Square top_left=", lambda: Square(top_left=(700, 640), length=100, color=(0.3, 0.55, 0.9, 0.4)), "top_left"),
    ("RegularPolygon vertex=", lambda: RegularPolygon(vertex=(960, 560), side=65, n=5, color=(0.3, 0.55, 0.9, 0.4)), "vertex"),
    ("Ellipse center=", lambda: Ellipse(center=(1240, 590), width=160, height=60, color=(0.3, 0.55, 0.9, 0.4)), "center"),
    ("Line p1=, angle=", lambda: Line(p1=(560, 470), angle=10, length=150, color=(0.3, 0.55, 0.9, 1.0)), "p1"),
]
_DERIVED_MODELS = [
    ("Rect spine (p1, p2)", lambda: Rect(p1=(260, 300), p2=(460, 340), height=60, anchor="cap", color=(0.9, 0.5, 0.3, 0.4)), "center"),
    ("Ellipse foci", lambda: Ellipse(fp1=(780, 300), fp2=(900, 340), major_axis=200, color=(0.9, 0.5, 0.3, 0.4)), "center"),
    ("Line p1=, p2=", lambda: Line(p1=(1120, 290), p2=(1260, 340), color=(0.9, 0.5, 0.3, 1.0)), "center"),
]


@page("Set angle",
      "Blue (angle is an input): angle= keeps the ring point (top_left / p1 / vertex / center). Orange (derived): it turns about the center. L links all to a sweeping angle — same rule",
      f"{COMMON_KEYS}  ·  Q/W angle = ∓15  ·  L link / unlink  ·  V rotate_by (a verb: pivots on center)")
def page_set_angle():
    rows = []
    for name, make, part in _INPUT_MODELS + _DERIVED_MODELS:
        o = own(make())
        o.line = Color("white")
        o.line_width = 1.5
        r = ring(getattr(o, part), "yellow")
        pin(lambda o=o, p=part: getattr(o, p), "yellow", radius=5)
        heading_arrow(o, 60, "white")
        c = o.center
        cap(name, (float(c.x), float(c.y) - 95), size=12)
        live_cap(lambda o=o: f"angle {float(o.angle):.1f}°", (float(c.x), float(c.y) - 112))
        rows.append([name, o, part, r])
    cap("angle is an input  →  the ring point stays", (700, 740), size=15)
    cap("derived heading  →  turns about the center", (700, 410), size=15)
    _S.update(rows=rows, want=None, linked=False)
    st.geo_angle = 0.0

    def placement_kept():
        return all(near(getattr(o, p), r.center, 1e-3) for _n, o, p, r in rows)

    def reads_back():
        want = _S["want"]
        return want is None or all(same_angle(o.angle, want) for _n, o, _p, _r in rows)

    check("ring point stays", placement_kept)
    check("angle reads what was set", reads_back)

    def set_all(value):
        for _n, o, _p, _r in rows:
            o.angle = value
        _S["want"] = value

    @action("Q", "angle = current − 15")
    def _q():
        if _S["linked"]:
            hud.status = "linked: press L to unlink first"
            return
        set_all(float(rows[0][1].angle) - 15)
        hud.status = f"angle = {_S['want']:.0f} on every shape"

    @action("W", "angle = current + 15")
    def _w():
        if _S["linked"]:
            hud.status = "linked: press L to unlink first"
            return
        set_all(float(rows[0][1].angle) + 15)
        hud.status = f"angle = {_S['want']:.0f} on every shape"

    @action("L", "link / unlink angle")
    def _l():
        if not _S["linked"]:
            st.geo_angle = float(rows[0][1].angle)
            for _n, o, _p, _r in rows:
                o["angle"] @= lambda: st.geo_angle
            _S["linked"] = True
            hud.status = 'shape["angle"] @= lambda: st.geo_angle  (sweeping)'
        else:
            for _n, o, _p, _r in rows:
                o["angle"].unlink()
            _S["linked"] = False
            hud.status = "unlinked"

    @action("V", "rotate_by(15) — a verb")
    def _v():
        centers = [xy(o.center) for _n, o, _p, _r in rows]
        err = ""
        for _n, o, _p, _r in rows:
            err = err or try_call(lambda o=o: o.rotate_by(15))
        flag("verb keeps the center", not err and all(near(o.center, c, 1e-3) for (_n, o, _p, _r), c in zip(rows, centers)))
        for _n, o, p, r in rows:           # the ring re-seats: the placement point moved
            r.center = xy(getattr(o, p))
        _S["want"] = None
        hud.status = err or "rotate_by(15): every center stayed; the rings re-seat on the moved placement points"

    def tick(dt):
        if _S["linked"]:
            st.geo_angle = float(st.geo_angle) + 40.0 * dt
            _S["want"] = float(st.geo_angle)
    _tick.append(tick)


# ---------------------------------------------------------------------------
# page 5 — Scale
# ---------------------------------------------------------------------------

@page("Scale",
      "Square(top_left=): the pivot ring stays (center, or top_left with P). Shapes bake scale into width; Sprite / Text keep width and zoom the drawing (cyan = .box)",
      f"{COMMON_KEYS}  ·  J/K scale ×0.8 / ×1.25  ·  P pivot center ↔ top_left  ·  Q/W rotate")
def page_scale():
    sq = own(Square(top_left=(160, 640), length=140, angle=15, color=(0.3, 0.7, 0.5, 0.35)))
    sq.line = Color("white")
    rc = ring(sq.center, "yellow")
    rtl = ring(sq.top_left, "tomato")
    pin(lambda: sq.center, "yellow", "center", radius=5)
    pin(lambda: sq.top_left, "tomato", "top_left", radius=5)
    cap("Square(top_left=)", (230, 420))
    live_cap(lambda: f"length {float(sq.length):.1f}  ·  scale {float(sq.scale):.3f}", (230, 400))

    rect = own(Rect(center=(640, 560), width=160, height=70, color="steel blue"))
    box_outline(rect)
    cap("Rect — scale baked", (640, 430))
    live_cap(lambda: f"width {float(rect.width):.1f}  ·  scale {float(rect.scale):.3f}", (640, 410))

    ship = own(Sprite(space, frame="playerShip1_blue.png", center=(930, 560), height=80, art_angle=90))
    box_outline(ship)
    cap("Sprite — pose zoom", (930, 430))
    live_cap(lambda: f"width {float(ship.width):.1f}  ·  box {float(ship.box.width):.1f}  ·  scale {float(ship.scale):.3f}", (930, 410))

    txt = own(Text("zoom", center=(1210, 560), font_size=34))
    box_outline(txt)
    cap("Text — pose zoom", (1210, 430))
    live_cap(lambda: f"font_size {float(txt.font_size):.0f}  ·  box {float(txt.box.width):.1f}", (1210, 410))

    w_rect, w_ship, bw_ship = float(rect.width), float(ship.width), float(ship.box.width)
    _S.update(pivot="center", L0=float(sq.length))

    check("Square pivot ring stays",
          lambda: near(sq.center if _S["pivot"] == "center" else sq.top_left,
                       (rc if _S["pivot"] == "center" else rtl).center, 1e-3))
    check("Square length = L0 · scale", lambda: abs(float(sq.length) - _S["L0"] * float(sq.scale)) < 1e-6)
    check("Rect width = w0 · scale", lambda: abs(float(rect.width) - w_rect * float(rect.scale)) < 1e-6)
    check("Sprite width knob unchanged", lambda: abs(float(ship.width) - w_ship) < 1e-6)
    check("Sprite box = width · scale", lambda: abs(float(ship.box.width) - bw_ship * float(ship.scale)) < 1e-4)

    def reseat():
        rc.center = xy(sq.center)
        rtl.center = xy(sq.top_left)

    def scale_all(k):
        about = None if _S["pivot"] == "center" else xy(sq.top_left)
        sq.scale_by(k, about=about)
        for o in (rect, ship, txt):
            o.scale_by(k)
        # the ring of the other (non-pivot) point re-seats
        if _S["pivot"] == "center":
            rtl.center = xy(sq.top_left)
        else:
            rc.center = xy(sq.center)
        hud.status = f"scale_by({k}) — pivot {_S['pivot']}"

    @action("J", "scale ×0.8")
    def _j():
        scale_all(0.8)

    @action("K", "scale ×1.25")
    def _k():
        scale_all(1.25)

    @action("P", "pivot center ↔ top_left")
    def _p():
        _S["pivot"] = "top_left" if _S["pivot"] == "center" else "center"
        reseat()
        hud.status = f"pivot = {_S['pivot']}"

    @action("Q", "rotate −15°")
    def _q():
        for o in (sq, rect, ship, txt):
            o.rotate_by(-15)
        reseat()

    @action("W", "rotate +15°")
    def _w():
        for o in (sq, rect, ship, txt):
            o.rotate_by(15)
        reseat()


# ---------------------------------------------------------------------------
# page 6 — Circle rim
# ---------------------------------------------------------------------------

@page("Circle rim",
      "p1 (white) is the perimeter point at the heading, p2 (violet) opposite; the cyan box turns with them. Two-point circle: drag p1 — its rotation follows the direction to p1",
      f"{COMMON_KEYS}  ·  Q/W rotate  ·  X/Y flip  ·  J/K scale  ·  drag the two-point circle's handles")
def page_circle():
    c = own(Circle(center=(330, 470), radius=120, angle=30, color=(0.9, 0.8, 0.3, 0.3)))
    arc = own(Circle(center=(760, 470), radius=110, angle=60, spread=140, color=(0.8, 0.45, 0.9, 0.35)))
    two = own(Circle(p1=(1070, 400), p2=(1250, 520), spread=250, color=(0.3, 0.8, 0.8, 0.3)))
    two.show_handles()
    for o, name in ((c, "center= radius= angle=30"), (arc, "arc spread=140"), (two, "Circle(p1=, p2=, spread=250)")):
        o.line = Color("white")
        box_outline(o)
        pin(lambda o=o: o.p1, "white", "p1")
        pin(lambda o=o: o.p2, "violet", "p2")
        # .box is a fresh measuring Box per read (not a live part): place the dot each frame.
        rc = own(Circle(center=xy(o.box.right_center), radius=4, color="cyan"))
        _syncs.append(lambda o=o, rc=rc: setattr(rc, "center", xy(o.box.right_center)))
        cap(name, (float(o.center.x), 290))
        live_cap(lambda o=o: f"angle {float(o.angle):.1f}°  ·  box.angle {float(o.box.angle):.1f}°",
                 (float(o.center.x), 270))
    circles = (c, arc, two)

    def rim_ok(o):
        cx, cy = xy(o.center)
        r, a = float(o.radius), math.radians(float(o.angle))
        return (near(o.p1, (cx + r * math.cos(a), cy + r * math.sin(a)), 1e-3)
                and near(o.p2, (2 * cx - float(o.p1.x), 2 * cy - float(o.p1.y)), 1e-3))

    check("p1 at angle, p2 opposite", lambda: all(rim_ok(o) for o in circles))
    check("box turns to p1 (box.right_center ≡ p1)", lambda: all(near(o.box.right_center, o.p1, 1e-3) for o in circles))
    check("angle = box.angle", lambda: all(same_angle(o.angle, o.box.angle, 1e-3) for o in circles))
    _pose_actions(list(circles))


# ---------------------------------------------------------------------------
# page 7 — Text
# ---------------------------------------------------------------------------

@page("Text",
      "Pins = the anchor part; cyan = text.box: the anchor is the drawn corner at any rotation / scale. T changes the string: anchored captions grow from their anchor. X: Text cannot flip. R: a linked anchor refuses to turn",
      f"{COMMON_KEYS}  ·  Q/W rotate  ·  J/K scale  ·  T text  ·  Z scale 0 → back  ·  X flip  ·  R turn linked  ·  drag the anchor")
def page_text():
    anchored = []
    for name, pos in (("top_left", (160, 600)), ("top_center", (700, 600)), ("top_right", (1240, 600))):
        t = own(Text(f"{name}=", **{name: pos}, layer="default", font_size=30, color="white"))
        box_outline(t)
        pin(lambda t=t, n=name: getattr(t, n), PIN_COLORS.get(name, "gold"), name)
        anchored.append((name, t))
    center_cap = own(Text("center= caption", center=(420, 360), font_size=30, color="gold"))
    box_outline(center_cap)
    pin(lambda: center_cap.center, "gold", "center")

    handle = own(Anchor(980, 330))
    linked = own(Text("linked top_left", top_left=lambda: handle, layer="default", font_size=26, color="violet"))
    box_outline(linked, "violet")
    cap("top_left=lambda: anchor  (drag the handle)", (1060, 250), size=12)
    posed = [t for _n, t in anchored] + [center_cap]
    _S.update(long=False)

    check("anchor = drawn corner",
          lambda: all(near(getattr(t, n), getattr(t.box, n), 1e-3) for n, t in anchored))
    check("linked caption follows its anchor", lambda: near(linked.top_left, handle, 1e-3))

    @action("Q", "rotate −15°")
    def _q():
        for t in posed:
            t.rotate_by(-15)

    @action("W", "rotate +15°")
    def _w():
        for t in posed:
            t.rotate_by(15)

    @action("J", "scale ×0.8")
    def _j():
        for t in posed:
            t.scale_by(0.8)

    @action("K", "scale ×1.25")
    def _k():
        for t in posed:
            t.scale_by(1.25)

    @action("T", "short ↔ long text")
    def _t():
        before = [xy(getattr(t, n)) for n, t in anchored]
        _S["long"] = not _S["long"]
        for n, t in anchored:
            t.text = f"{n}= a much longer caption" if _S["long"] else f"{n}="
        ok = all(near(getattr(t, n), b, 1e-3) for (n, t), b in zip(anchored, before))
        flag("new text keeps the anchor", ok)
        hud.status = "text changed: each anchored caption grew from its pin"

    @action("Z", "scale to 0, then back")
    def _z():
        before = [(xy(t.top_left), xy(t.top_right)) for t in posed]
        scales = [float(t.scale) for t in posed]
        for t in posed:
            t.scale_to(0.0)
        for t, s in zip(posed, scales):
            t.scale_to(s)
        ok = all(near(t.top_left, a, 1e-3) and near(t.top_right, b, 1e-3) for t, (a, b) in zip(posed, before))
        flag("scale 0 → back restores", ok)
        hud.status = "scale_to(0) then back: every caption where it was"

    @action("X", "try flip_x")
    def _x():
        err = try_call(lambda: setattr(center_cap, "flip_x", True))
        flag("Text refuses a flip", bool(err))
        hud.status = err or "UNEXPECTED: Text flipped"

    @action("R", "try rotate the linked caption")
    def _r():
        err = try_call(lambda: linked.rotate_by(30))
        flag("linked anchor refuses to turn", bool(err))
        hud.status = err or "UNEXPECTED: the linked caption turned"


# ---------------------------------------------------------------------------
# page 8 — Track views
# ---------------------------------------------------------------------------

@page("Track views",
      "Orange rides the host, violet rides host.reversed(). Verbs on the VIEW turn / scale / flip / move the host: both riders stay on the drawn path. Track.line center (+) is the middle. P turns the curve about the ring",
      f"{COMMON_KEYS}  ·  Q/W rotate view  ·  J/K scale view  ·  X/Y flip view  ·  M move view  ·  P pivot turn")
def page_tracks():
    host = own(Track.eight(width=380, height=170, center=(380, 470), color="cyan", line_width=3))
    view = host.reversed()
    a = own(Circle(center=(0, 0), radius=9, color="orange"))
    b = own(Circle(center=(0, 0), radius=9, color="violet"))
    a.center @= host.cursor
    b.center @= view.cursor
    heading_arrow(view, 90, "violet")
    cap("host = Track.eight   ·   view = host.reversed()", (380, 330))
    live_cap(lambda: f"view: angle {float(view.angle):.0f}  scale {float(view.scale):.2f}  flip_x {view.flip_x}   ·   "
                     f"host: angle {float(host.angle):.0f}  scale {float(host.scale):.2f}", (380, 310))

    line = own(Track.line(p1=(820, 560), p2=(1200, 650), color="gold", line_width=3))
    c = own(Circle(center=(0, 0), radius=8, color="lime green"))
    c.center @= line.cursor
    pin(lambda: line.center, "white", "line.center", radius=5)
    cap("Track.line(p1=, p2=) — center is the middle", (1010, 500))

    curve = own(Track(points=[(820, 250), (940, 380), (1080, 260), (1200, 380)], color="tomato", line_width=3))
    pivot = own(Anchor(1010, 190))
    cap("P: rotate_by(25, about=the ring)", (1010, 150))
    _S.update(u=0.0)

    def tick(dt):
        _S["u"] = (_S["u"] + 0.12 * dt) % 1.0
        host.u = _S["u"]
        view.u = _S["u"]
        line.u = (math.sin(_S["u"] * 2 * math.pi) + 1) / 2
    _tick.append(tick)

    check("view pose = host pose",
          lambda: (view.center is host.center and same_angle(view.angle, host.angle)
                   and float(view.scale) == float(host.scale) and view.flip_x == host.flip_x))
    check("riders on the drawn path",
          lambda: near(a.center, host.at(host.u), 1e-3) and near(b.center, view.at(view.u), 1e-3)
          and near(b.center, host.at((1.0 - float(view.u)) % 1.0), 1e-3))
    check("line center = middle",
          lambda: near(line.center, ((line.at(0)[0] + line.at(1)[0]) / 2, (line.at(0)[1] + line.at(1)[1]) / 2), 1e-3))

    @action("Q", "view.rotate_by(−15)")
    def _q():
        view.rotate_by(-15)

    @action("W", "view.rotate_by(+15)")
    def _w():
        view.rotate_by(15)

    @action("J", "view.scale_by(0.8)")
    def _j():
        view.scale_by(0.8)

    @action("K", "view.scale_by(1.25)")
    def _k():
        view.scale_by(1.25)

    @action("X", "view.flip_x")
    def _x():
        view.flip_x = not view.flip_x

    @action("Y", "view.flip_y")
    def _y():
        view.flip_y = not view.flip_y

    @action("M", "view.move_by(40, 0)")
    def _m():
        view.move_by(40, 0)
        hud.status = f"view.move_by: host.center.x = {float(host.center.x):.0f}"

    @action("P", "curve.rotate_by(25, about=pivot)")
    def _p():
        px, py = xy(pivot)
        us = (0.0, 0.3, 0.7, 1.0)
        before = [math.dist((px, py), curve.at(u)) for u in us]
        curve.rotate_by(25, about=(px, py))
        after = [math.dist((px, py), curve.at(u)) for u in us]
        flag("pivot turn is rigid", all(abs(x - y) < 1e-3 for x, y in zip(before, after)))


# ---------------------------------------------------------------------------
# page 9 — Clones
# ---------------------------------------------------------------------------

@page("Clones",
      "Top: sources, turned / scaled / flipped. C clones each and moves it down: the copy looks the same and reads the same pose, model and parts",
      f"{COMMON_KEYS}  ·  C clone  ·  X flip sources  ·  Q/W rotate sources")
def page_clones():
    rect = own(Rect(p1=(110, 560), p2=(260, 640), color="steel blue"))
    tri = own(EquilateralTriangle(center=(400, 600), radius=55, color="orange"))
    ship = own(Sprite(space, frame="playerShip1_blue.png", center=(600, 600), height=70, art_angle=90))
    text = own(Text("clone me", top_left=(740, 640), layer="default", font_size=28, color="white"))
    trk = own(Track.eight(width=150, height=70, center=(1050, 600), color="cyan", line_width=2))
    line = own(Line(p1=(1210, 570), p2=(1300, 630), color="gold", line_width=3))
    for o in (rect, tri, trk):
        o.flip_x = True
    rect.rotate_by(25)
    rect.scale_by(1.2)
    tri.flip_y = True
    ship.rotate_by(30)
    ship.scale_by(1.3)
    ship.flip_x = True
    ship.tilt = 10
    text.rotate_by(20)
    text.scale_by(1.3)
    trk.rotate_by(30)
    trk.scale_by(0.8)
    line.rotate_by(400)
    srcs = [("Rect p1/p2", rect), ("Triangle", tri), ("Sprite", ship), ("Text top_left=", text),
            ("Track.eight", trk), ("Line (turned 400°)", line)]
    for name, o in srcs:
        cx = float(o.center.x)
        cap(name, (cx, 730), size=12)
        live_cap(lambda o=o: _pose_text(o), (cx, 490), size=11)
    pin(lambda: rect.p1, "white", "p1")
    pin(lambda: text.top_left, "tomato", "top_left")
    cap("clones appear 260 below", (700, 400), size=12)
    _S.update(srcs=srcs, copies=[])
    dy = -260.0

    def clones_match():
        copies = _S["copies"]
        if not copies:
            return True
        for (name, s), c in zip(srcs, copies):
            for attr in ("angle", "scale", "flip_x", "flip_y"):
                a, b = getattr(s, attr), getattr(c, attr)
                if isinstance(a, bool) and a != b:
                    return False
                if not isinstance(a, bool) and abs(float(a) - float(b)) > 1e-6:
                    return False
        s_rect, c_rect = srcs[0][1], copies[0]
        s_text, c_text = srcs[3][1], copies[3]
        s_trk, c_trk = srcs[4][1], copies[4]
        return (near(c_rect.p1, _offset(s_rect.p1, 0, dy), 1e-3)
                and near(c_rect.p2, _offset(s_rect.p2, 0, dy), 1e-3)
                and c_text._anchor == "top_left"
                and near(c_text.top_left, _offset(s_text.top_left, 0, dy), 1e-3)
                and all(near(c_trk.at(u), _offset(s_trk.at(u), 0, dy), 1e-3) for u in (0.0, 0.2, 0.55, 0.9)))


    @action("C", "clone each (moved 260 down)")
    def _c():
        for c in _S["copies"]:
            c.destroy()
        copies = []
        for _name, s in srcs:
            c = own(s.clone())
            c.move_by(0, dy)
            copies.append(c)
        _S["copies"] = copies
        flag("copies match their sources", clones_match())
        pin(lambda: copies[0].p1, "white", "p1")
        pin(lambda: copies[3].top_left, "tomato", "top_left")
        for (_name, s), c in zip(srcs, copies):
            live_cap(lambda c=c: _pose_text(c), (float(c.center.x), 490 + dy), size=11)
        hud.status = "cloned: compare each copy with its source"

    @action("X", "flip_x sources")
    def _x():
        for _n, o in srcs:
            if not isinstance(o, Text):
                o.flip_x = not o.flip_x

    @action("Q", "rotate sources −15°")
    def _q():
        for _n, o in srcs:
            o.rotate_by(-15)

    @action("W", "rotate sources +15°")
    def _w():
        for _n, o in srcs:
            o.rotate_by(15)


def _pose_text(o) -> str:
    if not getattr(o, "is_alive", False):
        return ""
    flips = ("x" if o.flip_x else "") + ("y" if o.flip_y else "")
    return f"rot {float(o.angle):.0f} · scale {float(o.scale):.2f} · flip {flips or '-'}"


# ---------------------------------------------------------------------------
# page 10 — Edge cases
# ---------------------------------------------------------------------------

@page("Edge cases",
      "Focal ellipse down to a segment (major_axis = focal distance is legal) · Rect collapsed to zero width and back keeps its names · stats of a flipped polygon · Line turns accumulate",
      f"{COMMON_KEYS}  ·  Q/W major_axis −/+  ·  Z collapse / restore Rect  ·  X flip polygon  ·  L line +360°")
def page_edges():
    ell = own(Ellipse(fp1=(150, 560), fp2=(330, 600), major_axis=260, color=(0.9, 0.4, 0.4, 0.35)))
    ell.line = Color("white")
    pin(lambda: ell.fp1, "white", "fp1", radius=5)
    pin(lambda: ell.fp2, "violet", "fp2", radius=5)
    dist = math.dist(xy(ell.fp1), xy(ell.fp2))
    cap("Ellipse(fp1=, fp2=, major_axis=)", (240, 690), size=12)
    live_cap(lambda: f"major_axis {float(ell.major_axis):.1f}  ·  focal distance {dist:.1f}  ·  collapsed {ell.is_collapsed}", (240, 470))

    rect = own(Rect(p1=(520, 520), p2=(700, 640), color=(0.3, 0.55, 0.9, 0.35)))
    rect.line = Color("white")
    for name in ("top_left", "top_right", "bottom_left", "bottom_right"):
        pin(lambda n=name: getattr(rect, n), PIN_COLORS[name], name)
    cap("Rect(p1=, p2=)", (610, 690), size=12)
    live_cap(lambda: f"width {float(rect.width):.1f}  ·  collapsed {rect.is_collapsed}", (610, 470))

    poly = own(RegularPolygon(center=(950, 580), radius=70, n=6, angle=10, color=(0.6, 0.4, 0.9, 0.35)))
    poly.line = Color("white")
    for k in range(6):
        own(Text(str(k), center=lambda k=k: _offset(poly.points[k], 0, 14), font_size=12, color=Color("white")))
    cap("RegularPolygon — labels are points[k]", (950, 690), size=12)
    live_cap(lambda: f"signed_area {float(poly.signed_area):.0f}  ·  perimeter {float(poly.perimeter_length):.1f}", (950, 470))

    line = own(Line(p1=(1150, 560), p2=(1280, 610), color="gold", line_width=3))
    heading_arrow(line, 60)
    cap("Line", (1215, 690), size=12)
    live_cap(lambda: f"angle {float(line.angle):.1f}°", (1215, 470))
    _S.update(collapsed=None, area0=float(poly.signed_area))

    def poly_matches_free():
        ref = Polygon(points=[xy(p) for p in poly.points])
        try:
            return (abs(float(poly.signed_area) - float(ref.signed_area)) < 1e-6
                    and abs(float(poly.perimeter_length) - float(ref.perimeter_length)) < 1e-6)
        finally:
            ref.destroy()

    check("top_right ≡ p2", lambda: near(rect.top_right, rect.p2))
    check("polygon stats = a free Polygon's", poly_matches_free)
    check("signed_area sign follows the winding",
          lambda: (float(poly.signed_area) > 0) == (poly.flip_x == poly.flip_y))

    def set_major(v):
        err = try_call(lambda: setattr(ell, "major_axis", v))
        hud.status = err or f"major_axis = {v:.1f}" + ("  (= focal distance: a segment)" if abs(v - dist) < 1e-9 else "")
        return err

    @action("Q", "major_axis − 20 (stops at the focal distance)")
    def _q():
        flag("major_axis = focal distance is legal", not set_major(max(dist, float(ell.major_axis) - 20)))

    @action("W", "major_axis + 20")
    def _w():
        set_major(float(ell.major_axis) + 20)

    @action("Z", "collapse / restore the Rect")
    def _z():
        if _S["collapsed"] is None:
            _S["collapsed"] = xy(rect.p1)
            rect.p1 = (float(rect.p2.x), float(rect.p1.y))
            hud.status = "p1 moved onto p2's x: zero width (collapsed)"
        else:
            rect.p1 = _S["collapsed"]
            _S["collapsed"] = None
            flag("names survive a collapse", near(rect.top_right, rect.p2) and near(rect.bottom_left, rect.p1))
            hud.status = "restored: the pins are back on their corners"

    @action("X", "flip_x the polygon")
    def _x():
        before = [xy(p) for p in poly.points]
        c = poly.center
        poly.flip_x = not poly.flip_x
        flag("points[k] lands on its mirror", all(near(p, mirrored(b, c, True, False), 1e-3)
                                                  for p, b in zip(poly.points, before)))

    @action("L", "line.rotate_by(360)")
    def _l():
        r0 = float(line.angle)
        line.rotate_by(360)
        flag("full turns accumulate", abs(float(line.angle) - (r0 + 360.0)) < 1e-6)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def _clear():
    for o in reversed(list(_owned)):
        try:
            if hasattr(o, "destroy") and getattr(o, "is_alive", True):
                o.destroy()
        except Exception:
            pass
    _owned.clear()
    _checks.clear()
    _flags.clear()
    _syncs.clear()
    _tick.clear()
    _S.clear()


def _rebuild():
    _clear()
    p = _PAGES[_page_i]
    p["actions"] = {}
    hud.title = f"Geometry contract — {p['name']}  ({_page_i + 1}/{len(_PAGES)})"
    hud.expect = p["expect"]
    hud.keys = p["keys"]
    hud.status = "ready"
    p["build"]()


def _failing():
    """Labels of the checks that fail right now (the headless run reads this)."""
    bad = []
    for label, fn in _checks:
        try:
            if not fn():
                bad.append(label)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{label} ({type(exc).__name__}: {exc})")
    bad += [label for label, ok in _flags.items() if not ok]
    return bad


def _report():
    parts = []
    for label, fn in _checks:
        try:
            ok = bool(fn())
        except Exception:  # noqa: BLE001
            ok = False
        parts.append(("✓ " if ok else "✗ ") + label)
    parts += [("✓ " if ok else "✗ ") + label for label, ok in _flags.items()]
    hud.aux = "   ".join(parts)


def setup(_canvas):
    _rebuild()


def update(dt):
    global _page_i
    if keyp.once("A"):
        _page_i = (_page_i - 1) % len(_PAGES)
        _rebuild()
        return
    if keyp.once("S"):
        _page_i = (_page_i + 1) % len(_PAGES)
        _rebuild()
        return
    if keyp.once("SPACE"):
        _rebuild()
        return
    for key, (what, fn) in list(_PAGES[_page_i]["actions"].items()):
        if keyp.once(key):
            err = try_call(fn)
            if err:
                hud.status = f"{what}: {err}"
    for fn in list(_tick):
        fn(dt)
    for fn in list(_syncs):
        fn()
    _report()


run()
