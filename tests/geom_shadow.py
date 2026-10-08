"""Affine shadow oracle and the verb-sequence cell runner (geometry campaign, H1).

Not a test module. Every pose verb is an affine map with a known pivot: a move
is a translation, a turn or a scale is about its pivot, a flip is the
reflection about ``center`` along its axis. The ``Shadow`` of a subject
records, once, its drawn point set and every point part, then composes the map
of each step it runs. After **any** sequence the subject must read the
composed map applied to those originals: parts, drawn set, heading (full turns
kept, a flip applied to the unwrapped value: Q1), scale (the product), flip
flags (their parity), and the views that must agree with the drawing (hit
test, collision prims, ``.box``, the cull AABB). A single verb from a fresh
subject is the geometry contract's C1; the shadow is C1 after a history.

The pivot and the expected values come from the shadow, never from a read of
the subject before the step: a subject that drifted cannot drag its own
oracle with it.

Relational shapes keep their documented constraint cells
(``geometry_support.CONTRACT_EXEMPT``): an orbit about the circle's center,
a move across the reference only, a length scaled about the touch point. Each
is still an affine map; ``CONSTRAINT_MAPS`` gives it, and
``test_geom_structure`` pins its keys to ``CONTRACT_EXEMPT``.

A step that raises ``LinkedAttributeError`` on a linked or relational subject
is a refusal: nothing may change (I-atomic). Any other raise is a violation.

Violation keys are ``"kind | check | detail"`` strings, parameter-free, so a
known list can hold them (``geom_campaign_known.SHADOW``).
"""
from __future__ import annotations

import math
import os
import sys
import warnings
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geometry_support as G  # noqa: E402
import geom_axes as A  # noqa: E402
from scena import Point  # noqa: E402
from scena.state import LinkedAttributeError  # noqa: E402
from scena.validate import MIN_SCALE  # noqa: E402

XY = Tuple[float, float]
PIVOT = (50.0, -20.0)

# ---------------------------------------------------------------------------
# Affine maps: (a, b, c, d, e, f) with x' = a x + b y + e, y' = c x + d y + f
# ---------------------------------------------------------------------------

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def compose(m2, m1):
    """m2 ∘ m1 (m1 first)."""
    a2, b2, c2, d2, e2, f2 = m2
    a1, b1, c1, d1, e1, f1 = m1
    return (a2 * a1 + b2 * c1, a2 * b1 + b2 * d1, c2 * a1 + d2 * c1, c2 * b1 + d2 * d1,
            a2 * e1 + b2 * f1 + e2, c2 * e1 + d2 * f1 + f2)


def apply(m, p: XY) -> XY:
    a, b, c, d, e, f = m
    return (a * p[0] + b * p[1] + e, c * p[0] + d * p[1] + f)


def translate(dx, dy):
    return (1.0, 0.0, 0.0, 1.0, float(dx), float(dy))


def rotate_about(pivot: XY, deg: float):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    px, py = pivot
    return (c, -s, s, c, px - c * px + s * py, py - s * px - c * py)


def scale_about(pivot: XY, k: float):
    px, py = pivot
    return (k, 0.0, 0.0, k, px - k * px, py - k * py)


def mirror_about(center: XY, axis: str):
    cx, cy = center
    if axis == "x":
        return (-1.0, 0.0, 0.0, 1.0, 2 * cx, 0.0)
    return (1.0, 0.0, 0.0, -1.0, 0.0, 2 * cy)


# ---------------------------------------------------------------------------
# Shadow
# ---------------------------------------------------------------------------

def placement_name(obj) -> Optional[str]:
    """The part ``angle =`` keeps fixed, by name (None: a turn about the center)."""
    model = getattr(getattr(obj, "model", None), "name", None)
    kind = type(obj).__name__
    if kind in ("Rect", "Square"):
        return {"CENTER_WH": "center", "TOP_LEFT_WH": "top_left", "POINT_VEC": "p1",
                "CORNER_CORNER": "lean"}.get(model)
    if kind == "Ellipse" and model == "CENTER_WH":
        return "center"
    if kind in ("RegularPolygon", "EquilateralTriangle"):
        return "vertex" if model == "VERTEX_SIDE" else "center"
    if kind == "Line":
        return {"CENTER_LENGTH_ANGLE": "center", "POINT_ANGLE_LENGTH": "p1"}.get(model)
    if kind == "Text" and getattr(obj, "_anchor", None) is not None:
        return obj._anchor
    return None


def _xy_safe(fn):
    v = G.safe(fn)
    return v if isinstance(v, G.ReadError) else G.xy(v) if not isinstance(v, tuple) else v


class Shadow:
    """The composed map since the base state, and the pose it implies."""

    def __init__(self, obj, kind: str):
        self.kind = kind
        self.m = IDENTITY
        self.parts0 = {n: G.safe(f) for n, f in G.point_parts(obj).items()}
        self.center0 = G.safe(lambda: G.center_of(obj))
        self.drawn0 = G.safe(lambda: G.drawn(obj))
        self.heading = float(obj.angle)
        self.scale = 1.0 if G.is_box(obj) else float(obj.scale)
        self.flip_x = bool(getattr(obj, "flip_x", False))
        self.flip_y = bool(getattr(obj, "flip_y", False))
        self.pending_turn = 0.0     # an in-flight rotation still to run (mid-tween base)
        self.pose_zoom = G.scale_is_pose(obj)
        # A tangent line's turn orbits its circle's center (its default pivot).
        self.pending_pivot = ((lambda o=obj: _circle_center(o))
                              if G.exempt(kind, "rotate_by timed") and G.is_relational(obj) else None)
        self.parked = False
        self.hits0 = _hit_samples(obj, self.center0, self.drawn0)
        self.prims0 = _prim_vertices(obj)
        self.radius0 = G.safe(lambda: abs(float(obj.radius))) if type(obj).__name__ == "Circle" else None

    def center(self) -> XY:
        return apply(self.m, self.center0)

    def part(self, name: str) -> XY:
        return apply(self.m, self.parts0[name])

    def push(self, m) -> None:
        self.m = compose(m, self.m)

    def settle(self) -> None:
        """Timed motions ran to their end: an in-flight turn finishes about the center."""
        if self.pending_turn and not self.parked:
            pivot = self.pending_pivot() if self.pending_pivot else self.center()
            self.push(rotate_about(pivot, self.pending_turn))
            self.heading += self.pending_turn
            self.pending_turn = 0.0


# ---------------------------------------------------------------------------
# Steps: (name, applies(obj), run(obj, shadow) -> map or None) — run computes
# the expected map from the shadow, performs the verb, and updates the pose.
# ---------------------------------------------------------------------------

def _graphic(obj):
    return not G.is_box(obj)


def _settle():
    G.settle(1.0)


def _turn_steps():
    def rotate_by(o, s):
        o.rotate_by(33)
        return rotate_about(s.center(), 33), ("turn", 33)

    def rotate_by_about(o, s):
        o.rotate_by(33, about=PIVOT)
        return rotate_about(PIVOT, 33), ("turn", 33)

    def rotate_to(o, s):
        o.rotate_to(s.heading + 50)
        return rotate_about(s.center(), 50), ("set", s.heading + 50)

    def rotate_to_about(o, s):
        o.rotate_to(s.heading + 50, about=PIVOT)
        return rotate_about(PIVOT, 50), ("set", s.heading + 50)

    def angle_set(o, s):
        name = placement_name(o)
        pivot = s.part(name) if name in s.parts0 else s.center()
        o.angle = s.heading + 50
        return rotate_about(pivot, 50), ("set", s.heading + 50)

    def angle_set_turn(o, s):
        # A value a full turn away: same geometry, the heading reads the value.
        name = placement_name(o)
        pivot = s.part(name) if name in s.parts0 else s.center()
        o.angle = s.heading + 50 - 360
        return rotate_about(pivot, 50), ("set", s.heading + 50 - 360)

    def rotate_by_timed(o, s):
        c = s.center()
        s.pending_turn = 0.0        # a new timed turn claims the angle key: the running one stops
        o.rotate_by(33, time=0.2)
        _settle()
        return rotate_about(c, 33), ("turn", 33)

    def rotate_to_timed(o, s):
        # Q2: a finished timed rotate_to stores exactly the target. The target
        # is a full turn away so the shortest arc (+50) and the target differ.
        c = s.center()
        s.pending_turn = 0.0
        o.rotate_to(s.heading + 50 - 360, time=0.2)
        _settle()
        return rotate_about(c, 50), ("set", s.heading + 50 - 360)

    not_lean = lambda o: _graphic(o) and placement_name(o) != "lean"  # noqa: E731
    return [
        ("rotate_by", lambda o: True, rotate_by),
        ("rotate_by about", lambda o: True, rotate_by_about),
        ("rotate_to", lambda o: True, rotate_to),
        ("rotate_to about", _graphic, rotate_to_about),
        ("angle =", not_lean, angle_set),
        ("angle = turn", not_lean, angle_set_turn),
        ("rotate_by timed", _graphic, rotate_by_timed),
        ("rotate_to timed", _graphic, rotate_to_timed),
    ]


def _move_steps():
    def move_by(o, s):
        o.move_by(7, -3)
        return translate(7, -3), None

    def move_to(o, s):
        c = s.center()
        o.move_to(60, 40)
        return translate(60 - c[0], 40 - c[1]), None

    def move_by_timed(o, s):
        o.move_by(7, -3, time=0.2)
        _settle()
        return translate(7, -3), None

    return [
        ("move_by", _graphic, move_by),
        ("move_to", _graphic, move_to),
        ("move_by timed", _graphic, move_by_timed),
    ]


def geom_factor(s: "Shadow", k: float) -> float:
    """Scale is stored exactly; a Shape's baked geometry never goes below
    ``MIN_SCALE`` (``shapes._scale_geom_and_store``: a later ``scale_to``
    restores it). A pose-zoom kind (Sprite, Svg, Text, Track) draws its size
    times the stored scale (Shapes Design — Two scale models)."""
    if s.pose_zoom:
        return k
    return max(s.scale * k, MIN_SCALE) / max(s.scale, MIN_SCALE)


def _scale_steps():
    def scale_by(o, s):
        g = geom_factor(s, 1.5)
        o.scale_by(1.5)
        return scale_about(s.center(), g), ("scale", 1.5)

    def scale_by_about(o, s):
        g = geom_factor(s, 1.5)
        o.scale_by(1.5, about=PIVOT)
        return scale_about(PIVOT, g), ("scale", 1.5)

    def scale_to(o, s):
        g = geom_factor(s, 0.8)
        o.scale_to(s.scale * 0.8)
        return scale_about(s.center(), g), ("scale", 0.8)

    def scale_by_timed(o, s):
        c, g = s.center(), geom_factor(s, 1.5)
        o.scale_by(1.5, time=0.2)
        _settle()
        return scale_about(c, g), ("scale", 1.5)

    return [
        ("scale_by", _graphic, scale_by),
        ("scale_by about", _graphic, scale_by_about),
        ("scale_to", _graphic, scale_to),
        ("scale_by timed", _graphic, scale_by_timed),
    ]


def _flip_steps():
    def flip(axis):
        def run(o, s):
            want = not (s.flip_x if axis == "x" else s.flip_y)
            setattr(o, "flip_" + axis, want)
            return mirror_about(s.center(), axis), ("flip", axis)
        return run
    return [
        ("flip_x", G.can_flip, flip("x")),
        ("flip_y", G.can_flip, flip("y")),
    ]


STEPS = _move_steps() + _turn_steps() + _scale_steps() + _flip_steps()
STEP_NAMES = [s[0] for s in STEPS]
STEP_BY_NAME = {s[0]: s for s in STEPS}
TIMED = {n for n in STEP_NAMES if n.endswith("timed")}


def _update_pose(s: Shadow, pose) -> None:
    if pose is None:
        return
    kind, v = pose
    if kind == "turn":
        s.heading += v
    elif kind == "set":
        s.heading = v
    elif kind == "scale":
        s.scale *= v
    elif kind == "flip":
        s.heading = (180.0 - s.heading) if v == "x" else -s.heading
        if v == "x":
            s.flip_x = not s.flip_x
        else:
            s.flip_y = not s.flip_y


# ---------------------------------------------------------------------------
# Constraint cells of relational shapes (Shapes Design — Pose verbs on a
# relational shape). Keyed like geometry_support.CONTRACT_EXEMPT, by reason.
# ---------------------------------------------------------------------------

def _circle_center(obj) -> XY:
    return G.xy(obj._ref.center)


def _ref_normal(obj) -> XY:
    ref = obj._ref
    ux, uy = float(ref.p2.x) - float(ref.p1.x), float(ref.p2.y) - float(ref.p1.y)
    n = math.hypot(ux, uy) or 1.0
    return (-uy / n, ux / n)


def _orbit(step):
    """A turn of the step's amount about the circle's center (tangent lines)."""
    def run(o, s):
        m, pose = STEP_BY_NAME[step][2](o, s)
        deg = 33 if step.startswith("rotate_by") else 50
        return rotate_about(_circle_center(o), deg), pose
    return run


def _along(step):
    """Only the move's component along the reference normal (PARALLEL_DIST)."""
    def run(o, s):
        m, pose = STEP_BY_NAME[step][2](o, s)
        nx, ny = _ref_normal(o)
        dx, dy = m[4], m[5]
        k = dx * nx + dy * ny
        return translate(k * nx, k * ny), pose
    return run


def _length(step):
    """The length scaled about the pinned touch point ``p1`` (TANGENT_ANGLE)."""
    def run(o, s):
        touch = s.part("p1")
        m, pose = STEP_BY_NAME[step][2](o, s)
        return scale_about(touch, m[0]), pose
    return run


_CONSTRAINT_BY_REASON = {G._ORBIT: _orbit, G._ALONG: _along, G._LENGTH: _length}
CONSTRAINT_MAPS: Dict[Tuple[str, str], Callable] = {
    key: _CONSTRAINT_BY_REASON[reason](key[1])
    for key, reason in G.CONTRACT_EXEMPT.items() if key[1] in STEP_BY_NAME
}


# Campaign steps that are a variant of a contract verb: they share its
# documented constraint cell.
_VARIANT_OF = {"angle = turn": "angle =", "rotate_to timed": "rotate_to"}


def _constraint(kind: str, step: str):
    if (kind, step) in CONSTRAINT_MAPS:
        return CONSTRAINT_MAPS[(kind, step)]
    base = _VARIANT_OF.get(step)
    reason = G.CONTRACT_EXEMPT.get((kind, base)) if base else None
    return _CONSTRAINT_BY_REASON[reason](step) if reason else None


def step_runner(kind: str, step: str, obj=None) -> Callable:
    """The step's expected map: a constraint cell while the shape is still
    relational (a copy, a clone or an unlinked shape is free: rigid maps)."""
    if obj is not None and not G.is_relational(obj):
        return STEP_BY_NAME[step][2]
    return _constraint(kind, step) or STEP_BY_NAME[step][2]


# ---------------------------------------------------------------------------
# Observables
# ---------------------------------------------------------------------------

# Kinds whose hit test is their filled region. A Line or Track is picked by a
# stroke tolerance that does not follow ``scale`` (a pick width, not geometry).
_HIT_FAMILIES = {"Circle", "Ellipse", "Polygon", "RegularPolygon", "EquilateralTriangle",
                 "Rect", "Square", "Sprite", "Svg", "Text"}


def _hit_samples(obj, center, drawn) -> List[Tuple[XY, bool]]:
    """Points around the center with their hit-test answer, away from the outline.

    A similarity or a mirror keeps the answer for the image of each point;
    points whose answer changes under a tiny jitter are dropped (tangency band).
    """
    if type(obj).__name__ not in _HIT_FAMILIES or isinstance(center, G.ReadError):
        return []
    if isinstance(drawn, G.ReadError) or not drawn or isinstance(obj, Point):
        return []
    span = max(math.hypot(q[0] - center[0], q[1] - center[1]) for q in drawn) or 1.0
    out = []
    for i in range(12):
        ang = math.radians(30 * i + 7)
        for frac in (0.3, 0.7, 1.4):
            p = (center[0] + frac * span * math.cos(ang), center[1] + frac * span * math.sin(ang))
            try:
                hit = bool(obj.contains_point(*p))
                # The hit tests keep an absolute slack (Rect: 1e-6), so at a
                # tiny scale the band is absolute too (an "either" band, not a
                # contract answer).
                eps = max(1e-3 * span, 4e-6)
                if any(bool(obj.contains_point(p[0] + dx, p[1] + dy)) != hit
                       for dx, dy in ((eps, 0), (-eps, 0), (0, eps), (0, -eps))):
                    continue
            except Exception:  # noqa: BLE001
                return []
            out.append((p, hit))
    return out


def _prim_vertices(obj):
    """Collision prim points and conic centers (rigid under every pose verb)."""
    if type(obj).__name__ not in _HIT_FAMILIES - {"Sprite", "Svg", "Text"}:
        return None             # a Line / Track prim is a stroke: its width does not scale
    try:
        from test_geometry_contract import _prim_points
        pts, conics = _prim_points(obj)
    except Exception:  # noqa: BLE001
        return None
    return pts + [(c[1][0], c[1][1]) for c in conics]


def snapshot(obj) -> dict:
    """Everything a refused step must leave alone."""
    out = {n: G.safe(f) for n, f in G.point_parts(obj).items()}
    out["~drawn"] = G.safe(lambda: G.as_set(G.drawn(obj), 7))
    out["~angle"] = G.safe(lambda: float(obj.angle))
    if not G.is_box(obj):
        out["~scale"] = G.safe(lambda: float(obj.scale))
        out["~flip"] = (getattr(obj, "flip_x", None), getattr(obj, "flip_y", None))
    return out


def _same(a, b, tol=1e-9) -> bool:
    if isinstance(a, G.ReadError) or isinstance(b, G.ReadError):
        return type(a) is type(b) and getattr(a, "name", None) == getattr(b, "name", None)
    if isinstance(a, tuple) and len(a) == 2 and all(isinstance(v, float) for v in a):
        return A.close_xy(a, b, tol)
    if isinstance(a, float):
        return A.close_num(a, b, tol)
    if isinstance(a, list):
        return len(a) == len(b) and all(A.close_xy(p, q, 1e-6) for p, q in zip(a, b))
    return a == b


def compare_snapshots(before: dict, after: dict) -> List[str]:
    return sorted(G.part_group(k) for k in before if not _same(before[k], after.get(k)))


def check(obj, s: Shadow, order: List[str], tol: float = 1e-6) -> Dict[str, str]:
    """Violations of the shadow on ``obj`` (``check -> detail``)."""
    out: Dict[str, str] = {}
    parts = G.point_parts(obj)
    names = [n for n in order if n in s.parts0] + sorted(n for n in s.parts0 if n not in order)
    for n in names:
        want0 = s.parts0[n]
        if isinstance(want0, G.ReadError) or n not in parts:
            continue
        got = G.safe(parts[n])
        want = s.part(n)
        if isinstance(got, G.ReadError) or not A.close_xy(got, want, tol):
            out[f"part {G.part_group(n)}"] = f"{n}: {got} want {want}"
    if not isinstance(s.drawn0, G.ReadError):
        got = G.safe(lambda: G.drawn(obj))
        want = [apply(s.m, q) for q in s.drawn0]
        span = max(1.0, max(abs(c) for q in want for c in q))
        if isinstance(got, G.ReadError) or not G.same_set(got, want, 1e-5 * span):
            out["drawn"] = ""
    head = G.safe(lambda: float(obj.angle))
    if isinstance(head, G.ReadError) or not A.close_num(head, s.heading, 1e-7):
        out["heading"] = f"{head} want {s.heading}"
    if not G.is_box(obj):
        sc = G.safe(lambda: float(obj.scale))
        if isinstance(sc, G.ReadError) or not A.close_num(sc, s.scale, 1e-7):
            out["scale"] = f"{sc} want {s.scale}"
        fl = (getattr(obj, "flip_x", None), getattr(obj, "flip_y", None))
        if fl != (s.flip_x, s.flip_y):
            out["flip flags"] = f"{fl} want {(s.flip_x, s.flip_y)}"
    for p0, hit in s.hits0:
        p = apply(s.m, p0)
        got = G.safe(lambda: bool(obj.contains_point(*p)))
        if got != hit:
            out["hit test"] = f"{p} {got} want {hit}"
            break
    if s.radius0 is not None and s.prims0 and not isinstance(s.radius0, G.ReadError):
        # A pie's wedges are tessellated by radius (the vertex count changes with
        # scale): every prim point lies on the pie — its center or its rim.
        now = _prim_vertices(obj) or []
        c = s.center()
        r = s.radius0 * math.sqrt(abs(s.m[0] * s.m[3] - s.m[1] * s.m[2]))
        e = 1e-6 * max(1.0, r, abs(c[0]), abs(c[1]))
        if not now or any(math.hypot(q[0] - c[0], q[1] - c[1]) > r + e for q in now):
            out["collision prims"] = "off the pie"
    elif s.prims0 is not None and s.prims0:
        now = _prim_vertices(obj)
        want = [apply(s.m, q) for q in s.prims0]
        span = max(1.0, max(abs(c) for q in want for c in q))
        if now is None or not G.same_set(G.as_set(now, 6), G.as_set(want, 6), 1e-4 * span):
            out["collision prims"] = ""
    if type(obj).__name__ in ("Rect", "Square", "Ellipse", "Circle", "Sprite", "Svg", "Text"):
        d = G.safe(lambda: G.drawn(obj))
        if not isinstance(d, G.ReadError):
            from test_geometry_contract import _box_contains
            span = max(1.0, max(abs(c) for q in d for c in q))
            if not G.safe(lambda: _box_contains(obj, d, 1e-6 * span)) is True:
                out[".box contains drawn"] = ""
    if _graphic(obj):
        from scena.canvas import _approx_draw_aabb
        bb = G.safe(lambda: _approx_draw_aabb(obj))
        d = G.safe(lambda: G.drawn(obj))
        if bb is not None and not isinstance(bb, G.ReadError) and not isinstance(d, G.ReadError):
            x1, y1, x2, y2 = bb
            e = 1e-6 * max(1.0, abs(x1), abs(x2), abs(y1), abs(y2))
            if any(q[0] < x1 - e or q[0] > x2 + e or q[1] < y1 - e or q[1] > y2 + e for q in d):
                out["cull aabb"] = ""
    return out


# ---------------------------------------------------------------------------
# One cell: build, base, link, steps — every step checked
# ---------------------------------------------------------------------------

def _refusable(obj, link) -> bool:
    return G.is_relational(obj) or (link is not None and link.name not in ("none", "source"))


def _copy_differs(src, dst) -> Optional[str]:
    """What a copy door (clone, ``<<``) failed to reproduce (C7), or None."""
    a, b = G.safe(lambda: G.drawn(src)), G.safe(lambda: G.drawn(dst))
    if isinstance(a, G.ReadError) or isinstance(b, G.ReadError) or not G.same_set(a, b, 1e-5):
        return "drawn"
    for attr in ("angle", "scale", "flip_x", "flip_y"):
        x, y = G.safe(lambda: getattr(src, attr)), G.safe(lambda: getattr(dst, attr))
        if isinstance(x, bool) or isinstance(y, bool):
            if x != y:
                return attr
        elif isinstance(x, G.ReadError) or isinstance(y, G.ReadError) or not A.close_num(float(x), float(y), 1e-7):
            return attr
    return None


def make_subject(w, kind: str, base: str, link: str, *, x: str = "normal",
                 p: Optional[dict] = None):
    """(subject, shadow, link) in base state ``base`` with link ``link``;
    None when the combination does not apply; a violation dict when the base
    itself breaks a contract (a copy that does not reproduce its source)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        src = w.track(A.build(kind, p))
        if getattr(src, "_ref", None) is not None:
            w.track(src._ref)
        h0 = G.safe(lambda: float(src.angle))
        try:
            obj = A.apply_base(base, src, w)
        except (Exception, RecursionError) as exc:  # noqa: BLE001
            return {f"{kind} | base {base} | raises {type(exc).__name__}": str(exc)[:160]}
        if obj is None:
            return None
        if obj is not src:
            bad = _copy_differs(src, obj)
            if bad:
                return {f"{kind} | base {base} | copy differs {bad}": ""}
        lk = A.apply_link(link, obj, w)
        if lk is None:
            return None
        A.prepare_twin(obj, x)
        s = Shadow(obj, kind)
        if base == "mid_tween" and not isinstance(h0, G.ReadError):
            s.pending_turn = 90.0 - (s.heading - h0)
        if base == "parked":
            s.parked = True
    return obj, s, lk


def run_cell(w, kind: str, base: str, link: str, steps: List[str], read: str = "sorted",
             x: str = "normal", warm: str = "cold", p: Optional[dict] = None,
             reach: Optional[A.Reach] = None) -> Optional[Dict[str, str]]:
    """Run one cell. Returns ``{key: detail}`` of violations, or None if N/A.

    The scheduler and clock start clean: a motion an earlier cell left running
    must not tick inside this one (its refusal would land here)."""
    G.reset_clock()
    made = make_subject(w, kind, base, link, x=x, p=p)
    if made is None:
        return None
    if isinstance(made, dict):
        return made
    obj, s, lk = made
    if reach is not None:
        for axis, v in (("K", kind), ("F", A.family(kind)), ("B", base), ("L", link),
                        ("R", read), ("X", x), ("W", warm)):
            reach.hit(axis, v)
    out: Dict[str, str] = {}
    for i, step in enumerate(steps):
        bad = run_step(obj, kind, s, lk, step, read, x=x, warm=warm, reach=reach,
                       history=steps[:i + 1])
        if bad:
            out.update(bad)
            break
    return out


def run_step(obj, kind: str, s: Shadow, lk, step: str, read: str = "sorted", *,
             x: str = "normal", warm: str = "cold", reach: Optional[A.Reach] = None,
             history=None) -> Dict[str, str]:
    """Run one step on a subject and check it against its shadow."""
    name, applies, _run = STEP_BY_NAME[step]
    if not applies(obj):
        return {}
    if s.parked and step in TIMED:
        return {}                   # parked: owned process time pauses (Actors Design)
    A.W[warm](obj)
    before = snapshot(obj) if _refusable(obj, lk) else None
    run = step_runner(kind, step, obj)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with A.execution(x, obj):
                m, pose = run(obj, s)
    except LinkedAttributeError:
        if before is None:
            return {f"{kind} | {step} | refused while free": ""}
        diff = compare_snapshots(before, snapshot(obj))
        if diff:
            return {f"{kind} | {step} | refusal changed {diff[0]}": ", ".join(diff)}
        if reach is not None:
            reach.hit("refused", step)
        return {}
    except (Exception, RecursionError) as exc:  # noqa: BLE001
        return {f"{kind} | {step} | raises {type(exc).__name__}": str(exc)[:160]}
    if reach is not None:
        reach.hit("V", step)
    s.push(m)
    _update_pose(s, pose)
    if step in TIMED:
        s.settle()
    order = A.read_names(obj, read, lk)
    bad = check(obj, s, order)
    if lk is not None and lk.sink is not None:
        pin = G.safe(lambda: G.xy(lk.sink))
        if isinstance(pin, G.ReadError) or not A.close_xy(pin, s.center()):
            bad["link sink"] = f"{pin} want {s.center()}"
    where = f"after {history or [step]}: "
    return {f"{kind} | {step} | {c}": where + d for c, d in bad.items()}
