"""Geometry contract: every Graphic kind × model against one written contract.

The contract (Shapes Design — Geometry contract):

* Angles are degrees, 0 = +x, counter-clockwise. The default pivot is ``center``.
* A pose verb is a similarity (move / rotate / uniform scale) or a mirror (flip)
  about its pivot, and **every point part follows it** (named points, Defining
  and Derivate slots, ``points[k]``, the named points of ``.box``).
* The drawn geometry follows the same transform; verbs compose and invert like
  the transforms they are; absolute verbs agree with relative ones.
* Lengths are unchanged by move / rotate / flip and scale by ``k``; areas by ``k²``;
  a single flip negates ``signed_area``.
* Every Derivate reads what an independent computation from the Defining values
  gives, whatever order the parts are read in.
* Every constructor model of the same shape draws the same shape with the same
  named parts.
* Every subsystem sees the same geometry: hit test, collision prims, the
  ``geom`` outline, ``.box``, the cull AABB, ``is_collapsed``.
* ``clone()`` / ``_takein`` reproduce geometry, parts and pose (flip included).
* Far coordinates, zero sizes and tiny scales keep all of this, with no NaN.

Each family (C1…C8) runs two tests:

* ``test_sweep`` — every kind × verb × part at a few fixed poses
  (``SWEEP_POSES``); the union of violations must equal the family's ``KNOWN``
  set exactly. A new violation fails; a
  listed one that passes fails too (the list only shrinks — the
  ``test_diff_pose.KNOWN_WARM`` rule).
* ``test_property`` — Hypothesis over kind and pose; violations must stay
  inside ``KNOWN``.

Keys are ``"kind | check | detail"`` strings, parameter-free.

    python -m unittest tests.test_geometry_contract -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import given, settings, strategies as hst  # noqa: E402
from hypothesis_support import fresh_world  # noqa: E402

import geometry_support as G  # noqa: E402
from scena import Box, Circle, Ellipse, Line, Point, Polygon, Rect, RegularPolygon, Square  # noqa: E402

PIVOT = (50.0, -20.0)
KINDS = sorted(G.KINDS)
POSES = hst.fixed_dictionaries({
    "x": hst.integers(-200, 200).map(float),
    "y": hst.integers(-200, 200).map(float),
    "s": hst.sampled_from([0.5, 1.0, 2.5]),
    "r": hst.integers(-180, 180).map(float),
})

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _track(w, obj):
    if not isinstance(obj, Box):
        w.track(obj)
    return obj


def _new(w, kind, p):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _track(w, G.KINDS[kind](dict(p)))


def _has(obj, name):
    return callable(getattr(type(obj), name, None)) or name in getattr(type(obj), "__dict__", {})


# ---------------------------------------------------------------------------
# Verbs: (name, applies-to, apply(obj, ctx), expected image of a point)
# ctx = {"c": center before, "r0": rotation before, "s0": scale before}
# ---------------------------------------------------------------------------

def _is_graphic(obj):
    return not isinstance(obj, Box)


VERBS = [
    ("move_by", _is_graphic, lambda o, c: o.move_by(7, -3),
     lambda p, c: (p[0] + 7, p[1] - 3)),
    ("move_to", _is_graphic, lambda o, c: o.move_to(60, 40),
     lambda p, c: (p[0] + 60 - c["c"][0], p[1] + 40 - c["c"][1])),
    ("rotate_by", lambda o: True, lambda o, c: o.rotate_by(33),
     lambda p, c: G.turned(p, c["c"], 33)),
    ("rotate_by about", lambda o: True, lambda o, c: o.rotate_by(33, about=PIVOT),
     lambda p, c: G.turned(p, PIVOT, 33)),
    ("rotate_to", lambda o: True, lambda o, c: o.rotate_to(c["r0"] + 50),
     lambda p, c: G.turned(p, c["c"], 50)),
    # rotate_to is rotate_by(target - angle) about any pivot (SA4: Point placed
    # itself at polar angle target about the pivot instead).
    ("rotate_to about", _is_graphic, lambda o, c: o.rotate_to(c["r0"] + 50, about=PIVOT),
     lambda p, c: G.turned(p, PIVOT, 50)),
    # Setting angle keeps the model's placement point (an input model) or
    # is rotate_to about the center (derived heading). A p1=, p2= Rect leans:
    # not a rigid turn — its names are checked in test_rect_names.
    ("angle =", lambda o: _is_graphic(o) and G.angle_keeps(o) != "lean",
     lambda o, c: setattr(o, "angle", c["r0"] + 50),
     lambda p, c: G.turned(p, c["pivot"] if c["pivot"] is not None else c["c"], 50)),
    ("scale_by", _is_graphic, lambda o, c: o.scale_by(1.5),
     lambda p, c: G.scaled(p, c["c"], 1.5)),
    ("scale_by about", _is_graphic, lambda o, c: o.scale_by(1.5, about=PIVOT),
     lambda p, c: G.scaled(p, PIVOT, 1.5)),
    ("scale_to", _is_graphic, lambda o, c: o.scale_to(c["s0"] * 1.5),
     lambda p, c: G.scaled(p, c["c"], 1.5)),
    ("flip_x", G.can_flip, lambda o, c: setattr(o, "flip_x", True),
     lambda p, c: G.mirrored(p, c["c"], "x")),
    ("flip_y", G.can_flip, lambda o, c: setattr(o, "flip_y", True),
     lambda p, c: G.mirrored(p, c["c"], "y")),
    ("rotate_by timed", _is_graphic, lambda o, c: (o.rotate_by(33, time=0.2), G.settle()),
     lambda p, c: G.turned(p, c["c"], 33)),
    ("scale_by timed", _is_graphic, lambda o, c: (o.scale_by(1.5, time=0.2), G.settle()),
     lambda p, c: G.scaled(p, c["c"], 1.5)),
    ("move_by timed", _is_graphic, lambda o, c: (o.move_by(7, -3, time=0.2), G.settle()),
     lambda p, c: (p[0] + 7, p[1] - 3)),
]
VERB_NAMES = [v[0] for v in VERBS]


def _ctx(obj):
    pivot = G.safe(lambda: G.angle_keeps(obj))
    if pivot is not None and not isinstance(pivot, (str, G.ReadError)):
        pivot = G.xy(pivot)
    return {
        "pivot": pivot,
        "c": G.safe(lambda: G.center_of(obj)),
        "r0": G.safe(lambda: G.rotation_of(obj)),
        "s0": G.safe(lambda: float(obj.scale)) if _is_graphic(obj) else 1.0,
    }


def _apply(obj, verb, ctx):
    """Run a verb; return an error name when it raises."""
    try:
        verb(obj, ctx)
        return None
    except (Exception, RecursionError) as exc:  # noqa: BLE001
        return type(exc).__name__


# ---------------------------------------------------------------------------
# C1 — point stability
# ---------------------------------------------------------------------------

def sweep_c1(kinds, p):
    out = {}
    with fresh_world() as w:
        G.reset_clock()
        for kind in kinds:
            for name, applies, verb, image in VERBS:
                if G.exempt(kind, name):
                    continue        # a documented relational meaning (CONTRACT_EXEMPT)
                obj = _new(w, kind, p)
                if not applies(obj):
                    continue
                parts = G.point_parts(obj)
                before = {n: G.safe(f) for n, f in parts.items()}
                ctx = _ctx(obj)
                if isinstance(ctx["c"], G.ReadError):
                    out[f"{kind} | read | center raises {ctx['c'].name}"] = ""
                    continue
                err = _apply(obj, verb, ctx)
                if G.refused(obj, err):
                    continue
                if err:
                    out[f"{kind} | {name} | raises {err}"] = ""
                    continue
                for n, f in parts.items():
                    b = before[n]
                    if isinstance(b, G.ReadError):
                        out[f"{kind} | read | {n} raises {b.name}"] = ""
                        continue
                    got, want = G.safe(f), image(b, ctx)
                    if not G.close(got, want, 1e-5):
                        out[f"{kind} | {name} | {G.part_group(n)}"] = f"{n}: {got} != {want}"
    return out


# ---------------------------------------------------------------------------
# C2 — transform algebra on the drawn geometry and the pose
# ---------------------------------------------------------------------------

def _drawn(obj):
    return G.safe(lambda: G.drawn(obj))


def _same_drawn(a, b, tol=1e-5):
    return not isinstance(a, G.ReadError) and not isinstance(b, G.ReadError) and G.same_set(a, b, tol)


def _heading_ok(before, after, want):
    if isinstance(before, G.ReadError) or isinstance(after, G.ReadError):
        return False
    d = (after - want) % 360.0
    return min(d, 360.0 - d) < 1e-6


def sweep_c2(kinds, p):
    out = {}
    with fresh_world() as w:
        G.reset_clock()
        for kind in kinds:
            # The drawn geometry follows every verb (as a point set).
            for name, applies, verb, image in VERBS:
                if G.exempt(kind, name):
                    continue        # a documented relational meaning (CONTRACT_EXEMPT)
                obj = _new(w, kind, p)
                if not applies(obj):
                    continue
                ctx = _ctx(obj)
                before = _drawn(obj)
                if isinstance(ctx["c"], G.ReadError) or isinstance(before, G.ReadError) or _apply(obj, verb, ctx):
                    continue           # C1 records the raise
                want = [image(q, ctx) for q in before]
                if not _same_drawn(_drawn(obj), want):
                    out[f"{kind} | drawn follows | {name}"] = ""
            base = _new(w, kind, p)
            ref = _drawn(base)
            graphic = _is_graphic(base)

            def roundtrip(label, *steps):
                obj = _new(w, kind, p)
                for s in steps:
                    if _apply(obj, lambda o, c: s(o), {}):
                        return
                if not _same_drawn(_drawn(obj), ref):
                    out[f"{kind} | inverse | {label}"] = ""

            roundtrip("rotate a, -a", lambda o: o.rotate_by(37), lambda o: o.rotate_by(-37))
            roundtrip("rotate about a, -a", lambda o: o.rotate_by(37, about=PIVOT),
                      lambda o: o.rotate_by(-37, about=PIVOT))
            if graphic:
                roundtrip("scale k, 1/k", lambda o: o.scale_by(2), lambda o: o.scale_by(0.5))
                roundtrip("scale about k, 1/k", lambda o: o.scale_by(2, about=PIVOT),
                          lambda o: o.scale_by(0.5, about=PIVOT))
                roundtrip("flip_x twice", lambda o: setattr(o, "flip_x", True),
                          lambda o: setattr(o, "flip_x", False))
                roundtrip("flip_y twice", lambda o: setattr(o, "flip_y", True),
                          lambda o: setattr(o, "flip_y", False))
                roundtrip("move and back", lambda o: o.move_by(9, 4), lambda o: o.move_by(-9, -4))

            def compare(label, steps_a, steps_b):
                a, b = _new(w, kind, p), _new(w, kind, p)
                for s in steps_a:
                    if _apply(a, lambda o, c: s(o), {}):
                        return
                for s in steps_b:
                    if _apply(b, lambda o, c: s(o), {}):
                        return
                if not _same_drawn(_drawn(a), _drawn(b)):
                    out[f"{kind} | compose | {label}"] = ""

            compare("rotate a then b == a+b", [lambda o: o.rotate_by(20), lambda o: o.rotate_by(45)],
                    [lambda o: o.rotate_by(65)])
            r0 = G.safe(lambda: G.rotation_of(base))
            if not isinstance(r0, G.ReadError):
                compare("rotate_to == rotate_by", [lambda o: o.rotate_to(r0 + 70)], [lambda o: o.rotate_by(70)])
            if graphic:
                compare("scale k1 then k2 == k1k2", [lambda o: o.scale_by(1.5), lambda o: o.scale_by(2)],
                        [lambda o: o.scale_by(3)])
                compare("scale_to == scale_by", [lambda o: o.scale_to(float(o.scale) * 1.5)],
                        [lambda o: o.scale_by(1.5)])
                compare("flip_x + flip_y == rotate 180",
                        [lambda o: setattr(o, "flip_x", True), lambda o: setattr(o, "flip_y", True)],
                        [lambda o: o.rotate_by(180)])
                # Pose read-backs follow the conventions.
                for label, step, want in (
                    ("rotation after rotate_by", lambda o: o.rotate_by(33), lambda r: r + 33),
                    ("rotation after flip_x", lambda o: setattr(o, "flip_x", True), lambda r: 180 - r),
                    ("rotation after flip_y", lambda o: setattr(o, "flip_y", True), lambda r: -r),
                ):
                    obj = _new(w, kind, p)
                    rb = G.safe(lambda: G.rotation_of(obj))
                    if _apply(obj, lambda o, c: step(o), {}):
                        continue
                    ra = G.safe(lambda: G.rotation_of(obj))
                    if isinstance(rb, G.ReadError) or not _heading_ok(rb, ra, want(rb)):
                        out[f"{kind} | pose | {label}"] = f"{rb} -> {ra}"
                obj = _new(w, kind, p)
                s0 = G.safe(lambda: float(obj.scale))
                if not _apply(obj, lambda o, c: o.scale_by(1.5), {}):
                    s1 = G.safe(lambda: float(obj.scale))
                    if not G.close(s1, s0 * 1.5 if not isinstance(s0, G.ReadError) else s0):
                        out[f"{kind} | pose | scale after scale_by"] = f"{s0} -> {s1}"
    return out


# ---------------------------------------------------------------------------
# C3 — invariance laws of scalar parts
# ---------------------------------------------------------------------------

def sweep_c3(kinds, p):
    out = {}
    with fresh_world() as w:
        G.reset_clock()
        for kind in kinds:
            probe = _new(w, kind, p)
            names = list(G.scalar_parts(probe))
            if not names:
                continue
            graphic = _is_graphic(probe)
            cases = [("move_by", lambda o: o.move_by(7, -3), 1.0, False),
                     ("rotate_by", lambda o: o.rotate_by(33), 1.0, False),
                     ("rotate_by about", lambda o: o.rotate_by(33, about=PIVOT), 1.0, False)]
            if graphic:
                cases += [("scale_by", lambda o: o.scale_by(1.5), 1.5, False),
                          ("flip_x", lambda o: setattr(o, "flip_x", True), 1.0, True)]
            cases = [c for c in cases if graphic or c[0] != "move_by"]
            for label, step, k, flips in cases:
                obj = _new(w, kind, p)
                reads = G.scalar_parts(obj)
                before = {n: G.safe(f) for n, f in reads.items()}
                if _apply(obj, lambda o, c: step(o), {}):
                    continue
                for n, f in reads.items():
                    b, a = before[n], G.safe(f)
                    if isinstance(b, G.ReadError):
                        continue
                    kk = 1.0 if G.scale_is_pose(obj) else k     # a knob, not a measurement
                    if n == "signed_area":
                        want = (-b if flips else b) * kk * kk
                    else:
                        want = b * kk
                    if not G.close(a, want, 1e-6):
                        out[f"{kind} | {label} | {n}"] = f"{b} -> {a}, want {want}"
    return out


# ---------------------------------------------------------------------------
# C4 — read-back = oracle; read-order independence
# ---------------------------------------------------------------------------

def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _oracles(obj):
    """(label, got, want) triples computed independently from the parts."""
    o = []
    if isinstance(obj, Line):
        p1, p2 = G.xy(obj.p1), G.xy(obj.p2)
        o += [("length = |p2 - p1|", float(obj.length), _dist(p1, p2)),
              ("center = midpoint", G.xy(obj.center), _mid(p1, p2))]
    elif isinstance(obj, Circle):
        c, r = G.xy(obj.center), float(obj.radius)
        o += [("radius = |p1 - center|", r, _dist(G.xy(obj.p1), c)),
              ("radius = |p2 - center|", r, _dist(G.xy(obj.p2), c)),
              ("radius = |perimeter_point - center|", r, _dist(G.xy(obj.perimeter_point), c)),
              ("center = mid(p1, p2)", c, _mid(G.xy(obj.p1), G.xy(obj.p2)))]
    elif isinstance(obj, Ellipse):
        c = G.xy(obj.center)
        f1, f2 = G.xy(obj.fp1), G.xy(obj.fp2)
        a = max(float(obj.width), float(obj.height)) / 2
        b = min(float(obj.width), float(obj.height)) / 2
        o += [("center = mid(fp1, fp2)", c, _mid(f1, f2)),
              ("c = |fp1 - center|", float(obj.c), _dist(f1, c)),
              ("c^2 = a^2 - b^2", float(obj.c) ** 2, a * a - b * b),
              ("major_axis = 2a", float(obj.major_axis), 2 * a)]
    elif isinstance(obj, Polygon):
        pts = [G.xy(q) for q in obj.points]
        ref = Polygon(points=pts)
        try:
            o += [("signed_area = free Polygon", float(obj.signed_area), float(ref.signed_area)),
                  ("perimeter = free Polygon", float(obj.perimeter_length), float(ref.perimeter_length)),
                  ("centroid = free Polygon", G.xy(obj.centroid), G.xy(ref.centroid))]
        finally:
            ref.destroy()
        if isinstance(obj, RegularPolygon):
            c = G.xy(obj.center)
            o += [("radius = |v0 - center|", float(obj.radius), _dist(pts[0], c)),
                  ("side = |v0 - v1|", float(obj.side), _dist(pts[0], pts[1])),
                  ("vertex = points[0]", G.xy(obj.vertex), pts[0])]
    elif isinstance(obj, (Rect, Box)):
        bl, br, tl, tr = (G.xy(obj.bottom_left), G.xy(obj.bottom_right),
                          G.xy(obj.top_left), G.xy(obj.top_right))
        o += [("width = |br - bl|", float(obj.width), _dist(bl, br)),
              ("height = |tl - bl|", float(obj.height), _dist(bl, tl)),
              ("center = mid(bl, tr)", G.xy(obj.center), _mid(bl, tr)),
              ("top_center = mid(tl, tr)", G.xy(obj.top_center), _mid(tl, tr)),
              ("left_center = mid(bl, tl)", G.xy(obj.left_center), _mid(bl, tl))]
        ang = math.radians(float(obj.angle if isinstance(obj, Box) else obj.angle))
        v = G.xy(obj.vec)
        p1, p2 = G.xy(obj.p1), G.xy(obj.p2)
        o.append(("p2 = p1 + R @ vec" if getattr(obj, "model", None) is not None and obj.model.name != "SPINE" else "skip",
                  p2, (p1[0] + v[0] * math.cos(ang) - v[1] * math.sin(ang),
                       p1[1] + v[0] * math.sin(ang) + v[1] * math.cos(ang))))
        if isinstance(obj, Square):
            o.append(("length = width", float(obj.length), float(obj.width)))
    elif type(obj).__name__ == "Track" and obj.__dict__.get("_ends") is not None:
        a, b = G.xy(obj.at(0.0)), G.xy(obj.at(1.0))
        o += [("center = midpoint", G.xy(obj.center), _mid(a, b))]
    elif type(obj).__name__ == "Text":
        o += [("top_center = mid(top_left, top_right)", G.xy(obj.top_center),
               _mid(G.xy(obj.top_left), G.xy(obj.top_right)))]
    return [t for t in o if t[0] != "skip"]


def _all_reads(obj):
    reads = dict(G.point_parts(obj))
    reads.update(G.vector_parts(obj))
    reads.update(G.scalar_parts(obj))
    return reads


def sweep_c4(kinds, p):
    out = {}
    with fresh_world() as w:
        G.reset_clock()
        for kind in kinds:
            for label, prep in (("fresh", None), ("after rotate+scale", "pose")):
                obj = _new(w, kind, p)
                if prep:
                    # Warm every part first: a Derivate that misses the update's
                    # write list stays at its first value (G5 class).
                    for f in _all_reads(obj).values():
                        G.safe(f)
                    if _is_graphic(obj):
                        _apply(obj, lambda o, c: (o.rotate_by(33), o.scale_by(1.5)), {})
                    else:
                        _apply(obj, lambda o, c: o.rotate_by(33), {})
                try:
                    triples = _oracles(obj)
                except (Exception, RecursionError) as exc:  # noqa: BLE001
                    out[f"{kind} | oracle | raises {type(exc).__name__}"] = str(exc)[:80]
                    continue
                for name, got, want in triples:
                    if not G.close(got, want, 1e-6):
                        out[f"{kind} | oracle {label} | {name}"] = f"{got} != {want}"
            # Read-order independence: the same shape read forwards / backwards.
            a, b = _new(w, kind, p), _new(w, kind, p)
            ra, rb = _all_reads(a), _all_reads(b)
            va = {n: G.safe(f) for n, f in ra.items()}
            vb = {n: G.safe(rb[n]) for n in reversed(list(rb))}
            for n in va:
                if isinstance(va[n], G.ReadError) and isinstance(vb[n], G.ReadError):
                    continue
                if not G.close(va[n], vb[n], 1e-9):
                    out[f"{kind} | read order | {G.part_group(n)}"] = f"{va[n]} vs {vb[n]}"
    return out


# ---------------------------------------------------------------------------
# C5 — model equivalence
# ---------------------------------------------------------------------------

def _equivalents(p):
    """Groups of builders that must draw the same shape with the same named parts."""
    x, y, s, r = p["x"], p["y"], p["s"], p["r"]
    ref = Rect(center=(x, y), width=40 * s, height=16 * s, angle=r)
    bl, tr, tl = G.xy(ref.bottom_left), G.xy(ref.top_right), G.xy(ref.top_left)
    lc, rc = G.xy(ref.left_center), G.xy(ref.right_center)
    ref.destroy()
    u = G._dir(r)
    rim = (x + 9 * s * u[0], y + 9 * s * u[1])
    anti = (x - 9 * s * u[0], y - 9 * s * u[1])
    eref = Ellipse(center=(x, y), width=30 * s, height=12 * s, angle=r)
    f1, f2 = G.xy(eref.fp1), G.xy(eref.fp2)
    eref.destroy()
    rp = RegularPolygon(center=(x, y), radius=6 * s, n=5, angle=r)
    v0, side = G.xy(rp.points[0]), float(rp.side)
    rp.destroy()
    return {
        "Rect": [
            ("center_wh", lambda: Rect(center=(x, y), width=40 * s, height=16 * s, angle=r)),
            ("top_left_wh", lambda: Rect(top_left=tl, width=40 * s, height=16 * s, angle=r)),
            ("corner_corner", lambda: Rect(p1=bl, p2=tr, angle=r)),
            ("point_vec", lambda: Rect(p1=bl, vec=(40 * s, 16 * s), angle=r)),
            # A spine's p1 / p2 are axis points (not corners): compared by name only.
            ("spine cap", lambda: Rect(p1=lc, p2=rc, height=16 * s, anchor="cap")),
        ],
        "Square": [
            ("Square center", lambda: Square(center=(x, y), length=20 * s, angle=r)),
            ("Rect center", lambda: Rect(center=(x, y), width=20 * s, height=20 * s, angle=r)),
        ],
        "Circle": [
            ("center_radius", lambda: Circle(center=(x, y), radius=9 * s, angle=r)),
            ("center_perimeter", lambda: Circle(center=(x, y), perimeter_point=rim, angle=r)),
            ("two_points", lambda: Circle(p1=rim, p2=anti, angle=r)),
        ],
        "Ellipse": [
            ("center_wh", lambda: Ellipse(center=(x, y), width=30 * s, height=12 * s, angle=r)),
            ("focal_points", lambda: Ellipse(fp1=f1, fp2=f2, major_axis=30 * s)),
        ],
        "Line": [
            ("point_point", lambda: Line(p1=(x, y), p2=(x + 40 * s * u[0], y + 40 * s * u[1]))),
            ("point_vec", lambda: Line(p1=(x, y), vec=(40 * s * u[0], 40 * s * u[1]))),
            ("point_angle_length", lambda: Line(p1=(x, y), angle=r, length=40 * s)),
            ("center_length", lambda: Line(center=(x + 20 * s * u[0], y + 20 * s * u[1]), length=40 * s, angle=r)),
        ],
        "RegularPolygon": [
            ("center_radius", lambda: RegularPolygon(center=(x, y), radius=6 * s, n=5, angle=r)),
            ("center_side", lambda: RegularPolygon(center=(x, y), side=side, n=5, angle=r)),
            ("vertex_side", lambda: RegularPolygon(vertex=v0, side=side, n=5, angle=r)),
        ],
        "EquilateralTriangle": [
            ("EquilateralTriangle", lambda: __import__("scena").EquilateralTriangle(center=(x, y), radius=6 * s, angle=r)),
            ("RegularPolygon n=3", lambda: RegularPolygon(center=(x, y), radius=6 * s, n=3, angle=r)),
        ],
    }


def sweep_c5(kinds, p):
    out = {}
    families = {k.split()[0] for k in kinds}
    with fresh_world() as w:
        for fam, builders in _equivalents(p).items():
            if fam not in families:
                continue
            built = [(label, _track(w, b())) for label, b in builders]
            ref_label, ref = built[0]
            ref_drawn, ref_parts = _drawn(ref), {n: G.safe(f) for n, f in G.point_parts(ref).items()}
            for label, obj in built[1:]:
                if not _same_drawn(_drawn(obj), ref_drawn):
                    out[f"{fam} | same shape | {label} vs {ref_label}: drawn"] = ""
                parts = G.point_parts(obj)
                roles = {"p1", "p2", "vec"} if label.startswith("spine") else set()
                for n, want in ref_parts.items():
                    if n not in parts or n.startswith("points[") or n in roles:
                        continue
                    if not G.close(G.safe(parts[n]), want, 1e-5):
                        out[f"{fam} | same shape | {label} vs {ref_label}: {G.part_group(n)}"] = n
    return out


# ---------------------------------------------------------------------------
# C6 — every subsystem sees the same geometry
# ---------------------------------------------------------------------------

_prim_points = G.prim_points
_box_contains = G.box_contains


def sweep_c6(kinds, p):
    from scena.canvas import _approx_draw_aabb
    from scena.geom import _outline_verts
    out = {}
    with fresh_world() as w:
        for kind in kinds:
            obj = _new(w, kind, p)
            d = _drawn(obj)
            if isinstance(d, G.ReadError):
                out[f"{kind} | drawn | raises {d.name}"] = ""
                continue
            fam = kind.split()[0]
            c = G.safe(lambda: G.center_of(obj))
            if isinstance(c, G.ReadError):
                out[f"{kind} | read | center raises {c.name}"] = ""
                continue
            # The frame turns with the heading: ``box.angle`` is ``angle`` wherever a
            # kind has a frame (G17: a rim-placed Circle read 0 while its box turned to p1).
            frame = G.safe(lambda: float(obj.box.angle))
            rot = G.safe(lambda: float(obj.angle))
            if not isinstance(frame, G.ReadError) and not isinstance(rot, G.ReadError):
                gap = (frame - rot) % 360.0
                if min(gap, 360.0 - gap) > 1e-6:
                    out[f"{kind} | frame | box.angle is not rotation"] = f"{frame} vs {rot}"
            # Hit test: just inside the outline is in, just outside is out.
            if kind in G.AREA_KINDS and fam != "Polygon":
                for q in d[:: max(1, len(d) // 8)]:
                    if _dist(q, c) < 1e-9:
                        continue
                    inside = (c[0] + 0.97 * (q[0] - c[0]), c[1] + 0.97 * (q[1] - c[1]))
                    outside = (c[0] + 1.03 * (q[0] - c[0]), c[1] + 1.03 * (q[1] - c[1]))
                    if not obj.contains_point(*inside):
                        out[f"{kind} | hit test | misses inside"] = ""
                        break
                    if obj.contains_point(*outside):
                        out[f"{kind} | hit test | hits outside"] = ""
                        break
            # Collision prims: polygons / boxes share the drawn vertices; conics the drawn frame.
            if kind in G.AREA_KINDS:
                pts, conics = _prim_points(obj)
                if pts and not G.same_set(G.as_set(pts), G.as_set(d), 1e-4) and fam not in ("Circle", "Ellipse"):
                    out[f"{kind} | collision prims | vertices"] = ""
                for ck, params in conics:
                    if ck == "circle":
                        if not (G.close((params[0], params[1]), G.xy(obj.center), 1e-6)
                                and G.close(params[2], abs(float(obj.radius)), 1e-6)):
                            out[f"{kind} | collision prims | circle"] = str(params)
                    else:
                        cx, cy, ww, hh, ang = obj._oriented_frame()
                        if not (G.close((params[0], params[1]), (cx, cy), 1e-6)
                                and G.close(params[2], abs(ww) / 2, 1e-6) and G.close(params[3], abs(hh) / 2, 1e-6)):
                            out[f"{kind} | collision prims | ellipse"] = str(params)
            # geom outline agrees with the Track outline (polygonal kinds).
            if fam in ("Polygon", "RegularPolygon", "EquilateralTriangle", "Rect", "Square"):
                gv = _outline_verts(obj)
                if gv is not None and not G.same_set(G.as_set(list(gv)), G.as_set(d), 1e-4):
                    out[f"{kind} | geom outline | vertices"] = ""
            # .box contains the drawn geometry (and equals the frame for boxes).
            if kind in G.FRAME_KINDS:
                if not _box_contains(obj, d):
                    out[f"{kind} | .box | contains drawn"] = ""
            # Cull AABB contains the drawn geometry.
            bb = G.safe(lambda: _approx_draw_aabb(obj))
            if not isinstance(bb, G.ReadError) and bb is not None:
                x1, y1, x2, y2 = bb
                if any(q[0] < x1 - 1e-6 or q[0] > x2 + 1e-6 or q[1] < y1 - 1e-6 or q[1] > y2 + 1e-6 for q in d):
                    out[f"{kind} | cull aabb | contains drawn"] = ""
            # is_collapsed is False for a real area; True at zero size.
            if kind in G.AREA_KINDS:
                if obj.is_collapsed:
                    out[f"{kind} | is_collapsed | true at full size"] = ""
                flat = G.safe(lambda: _new(w, kind, dict(p, s=0.0))) if kind != "Polygon" else None
                if isinstance(flat, G.ReadError):
                    out[f"{kind} | zero size | build raises {flat.name}"] = ""
                elif flat is not None and not flat.is_collapsed:
                    out[f"{kind} | is_collapsed | false at zero size"] = ""
    return out


# ---------------------------------------------------------------------------
# C7 — copies
# ---------------------------------------------------------------------------

# Copy doors (C7: "clone() / _takein reproduce geometry, parts and pose"). The
# graphics review found ``<<`` dropping the pose and relational models kept
# without their links: ``sweep_c7`` used to test ``clone()`` only.
COPY_DOORS = ("clone", "<<", "absorb")

# Verbs run on source and copy alike after the copy ("copy then act"): a copy
# that lost its turn count, flip or model diverges here even when it read the
# same right after the copy. Absolute targets come from the source.
COPY_ACTS = (
    ("move_by", lambda o, a: o.move_by(7, -3)),
    ("rotate_to", lambda o, a: o.rotate_to(a + 50)),
    ("rotate_by", lambda o, a: o.rotate_by(33)),
    ("scale_by", lambda o, a: o.scale_by(1.5)),
    ("flip_x", lambda o, a: setattr(o, "flip_x", not o.flip_x)),
)


_FREE_OF = {"Line": "Line point_point", "Ellipse": "Ellipse center_wh"}


def _free_kind(w, kind, p):
    """A free model of the same class (a relational source copies into it)."""
    return _FREE_OF[kind.split()[0]] if G.is_relational(_new(w, kind, p)) else kind


def _prepped(w, kind, p):
    src = _new(w, kind, p)
    if G.can_flip(src):
        _apply(src, lambda o, c: setattr(o, "flip_x", True), {})
    _apply(src, lambda o, c: (o.rotate_by(20), o.scale_by(1.25)), {})
    return src


def _copy_by(w, door, kind, p, src):
    if door == "clone":
        return _track(w, src.clone())
    dst = _new(w, _free_kind(w, kind, p), dict(p, x=p["x"] + 37.0, y=p["y"] - 11.0))
    if door == "<<":
        dst << src
    else:
        dst.absorb(_prepped(w, kind, p))      # absorb destroys its source: a twin
    return dst


def _pose_of(obj):
    out = {}
    for attr in ("angle", "scale", "flip_x", "flip_y"):
        out[attr] = G.safe(lambda: getattr(obj, attr))
    return out


def _same_pose(a, b, attr):
    x, y = a[attr], b[attr]
    if isinstance(x, bool) or isinstance(y, bool):
        return x == y
    if isinstance(x, G.ReadError):
        return True
    return not isinstance(y, G.ReadError) and G.close(float(y), float(x), 1e-6)


def sweep_c7(kinds, p):
    out = {}
    with fresh_world() as w:
        for kind in kinds:
            if not _is_graphic(_new(w, kind, p)):
                continue
            for door in COPY_DOORS:
                if door != "clone" and (kind.endswith("reversed") or kind.split()[0] in ("Sprite", "Svg", "Text", "Track", "Point", "Anchor")):
                    continue          # << / absorb are Shape copies (a reversed view refuses: tested apart)
                src = _prepped(w, kind, p)
                try:
                    copy = _copy_by(w, door, kind, p, src)
                except (Exception, RecursionError) as exc:  # noqa: BLE001
                    out[f"{kind} | {door} | raises {type(exc).__name__}"] = ""
                    continue
                if not _same_drawn(_drawn(copy), _drawn(src)):
                    out[f"{kind} | {door} | drawn"] = ""
                sp, cp = G.point_parts(src), G.point_parts(copy)
                for n, f in sp.items():
                    if n in cp and not G.close(G.safe(cp[n]), G.safe(f), 1e-5):
                        out[f"{kind} | {door} | {G.part_group(n)}"] = n
                a, b = _pose_of(src), _pose_of(copy)
                for attr in a:
                    if not _same_pose(a, b, attr):
                        out[f"{kind} | {door} | {attr}"] = f"{a[attr]} vs {b[attr]}"
                # Copy then act: the same verbs keep source and copy alike. A
                # relational source may refuse (it is linked); its copy is free,
                # so then the copy is checked against the verb's own image.
                for act, verb in COPY_ACTS:
                    if act == "flip_x" and not G.can_flip(copy):
                        continue
                    if G.exempt(kind, act):
                        break       # the source verb has its own documented meaning
                    ang = G.safe(lambda: float(src.angle))
                    ang = 0.0 if isinstance(ang, G.ReadError) else ang
                    c_before, c_ctx = _drawn(copy), _ctx(copy)
                    e_copy = _apply(copy, lambda o, c: verb(o, ang), {})
                    e_src = _apply(src, lambda o, c: verb(o, ang), {})
                    if e_copy:
                        out[f"{kind} | {door} then {act} | copy raises {e_copy}"] = ""
                        break
                    if not e_src:
                        if not _same_drawn(_drawn(copy), _drawn(src)):
                            out[f"{kind} | {door} then {act} | drawn"] = ""
                            break
                        a, b = _pose_of(src), _pose_of(copy)
                        bad = [attr for attr in a if not _same_pose(a, b, attr)]
                        if bad:
                            out[f"{kind} | {door} then {act} | {bad[0]}"] = f"{a[bad[0]]} vs {b[bad[0]]}"
                            break
                    elif G.refused(src, e_src) and act in ("move_by", "rotate_by", "scale_by"):
                        image = {"move_by": lambda q: (q[0] + 7, q[1] - 3),
                                 "rotate_by": lambda q: G.turned(q, c_ctx["c"], 33),
                                 "scale_by": lambda q: G.scaled(q, c_ctx["c"], 1.5)}[act]
                        if isinstance(c_before, G.ReadError) or not _same_drawn(
                                _drawn(copy), [image(q) for q in c_before], 1e-4):
                            out[f"{kind} | {door} then {act} | copy off its verb"] = ""
                        break           # source and copy now differ by design
                    else:
                        break           # the source refused a verb the copy ran
    return out


# ---------------------------------------------------------------------------
# C8 — degenerate and extreme
# ---------------------------------------------------------------------------

def _finite(v):
    if isinstance(v, G.ReadError):
        return False
    if isinstance(v, tuple):
        return all(math.isfinite(c) for c in v)
    return math.isfinite(v)


def sweep_c8(kinds, p):
    out = {}
    far = 1.0e6
    with fresh_world() as w:
        for kind in kinds:
            # Translation invariance at far coordinates (after a turn).
            near = _new(w, kind, p)
            away = _new(w, kind, dict(p, x=p["x"] + far, y=p["y"] - far))
            for o in (near, away):
                _apply(o, lambda q, c: q.rotate_by(33), {})
            dn, da = _drawn(near), _drawn(away)
            if not isinstance(dn, G.ReadError) and not isinstance(da, G.ReadError):
                shifted = [(x - far, y + far) for x, y in da]
                if not G.same_set(dn, shifted, 1e-3):
                    out[f"{kind} | far | drawn"] = ""
            # Zero size: builds, every read finite.
            if kind in G.AREA_KINDS or kind.startswith("Line"):
                flat = G.safe(lambda: _new(w, kind, dict(p, s=0.0)))
                if isinstance(flat, G.ReadError):
                    out[f"{kind} | zero size | build raises {flat.name}"] = ""
                else:
                    for n, f in _all_reads(flat).items():
                        if not _finite(G.safe(f)):
                            out[f"{kind} | zero size | {G.part_group(n)}"] = ""
            # Collapse and recovery; tiny scale and back.
            if _is_graphic(near):
                for label, steps in (("scale 0 then 1", (lambda o: o.scale_to(0.0), lambda o: o.scale_to(1.0))),
                                     ("tiny and back", (lambda o: o.scale_by(1e-6), lambda o: o.scale_by(1e6)))):
                    obj = _new(w, kind, p)
                    ref = _drawn(obj)
                    err = None
                    for s in steps:
                        err = err or _apply(obj, lambda o, c: s(o), {})
                    if G.refused(obj, err):
                        pass
                    elif err:
                        out[f"{kind} | {label} | raises {err}"] = ""
                    elif not _same_drawn(_drawn(obj), ref, 1e-4):
                        out[f"{kind} | {label} | drawn"] = ""
    return out


# ---------------------------------------------------------------------------
# Known violations (seeded by the first sweep; shrink-only)
# ---------------------------------------------------------------------------

from geometry_known import KNOWN  # noqa: E402  (shrink-only)

# The sweep's fixed poses: the union of their violations must equal KNOWN.
# Add a pose here when a property run finds a pose-dependent violation.
SWEEP_POSES = (
    G.P0,
    {"x": 0.0, "y": 0.0, "s": 0.5, "r": 22.0},      # deep: Rect corner_corner clone p1 / p2
    {"x": -120.0, "y": 75.0, "s": 2.5, "r": -90.0},
    {"x": 40.0, "y": -160.0, "s": 1.0, "r": 135.0},
    {"x": 0.0, "y": 0.0, "s": 0.5, "r": 1.0},       # gate: Rect spine << loses the turn count
    {"x": 0.0, "y": 0.0, "s": 0.5, "r": 153.0},     # deep: a vertical diameter's flip_x kept 450 (GX21)
)

SWEEPS = {"C1": sweep_c1, "C2": sweep_c2, "C3": sweep_c3, "C4": sweep_c4,
          "C5": sweep_c5, "C6": sweep_c6, "C7": sweep_c7, "C8": sweep_c8}


def _report(found, known):
    new = sorted(set(found) - known)
    stale = sorted(known - set(found))
    lines = []
    if new:
        lines.append("NEW violations:\n  " + "\n  ".join(f"{k}  {found[k]}".rstrip() for k in new))
    if stale:
        lines.append("FIXED but still listed in KNOWN (remove them):\n  " + "\n  ".join(stale))
    return "\n".join(lines)


def _family(fid):
    sweep = SWEEPS[fid]

    class Family(unittest.TestCase):
        def test_sweep(self):
            found = {}
            for pose in SWEEP_POSES:
                found.update(sweep(KINDS, dict(pose)))
            msg = _report(found, KNOWN[fid])
            self.assertFalse(msg, f"{fid}:\n{msg}")

        @settings(max_examples=max(5, settings().max_examples // 4))
        @given(kind=hst.sampled_from(KINDS), p=POSES)
        def test_property(self, kind, p):
            found = sweep([kind], p)
            new = sorted(set(found) - KNOWN[fid])
            self.assertFalse(new, f"{fid} at {p}:\n  " + "\n  ".join(f"{k}  {found[k]}" for k in new))

    Family.__name__ = f"Test{fid}"
    Family.__qualname__ = f"Test{fid}"
    return Family


TestC1PointStability = _family("C1")
TestC2TransformAlgebra = _family("C2")
TestC3Invariance = _family("C3")
TestC4Readback = _family("C4")
TestC5ModelEquivalence = _family("C5")
TestC6CrossView = _family("C6")
TestC7Copies = _family("C7")
TestC8Extremes = _family("C8")



class TestKindsCoverEveryModel(unittest.TestCase):
    """Every constructor model of every kind is in ``geometry_support.KINDS``.

    The 2026-10-08 graphics review found bugs in the relational Line models
    and Ellipse FROM_RECT that no sweep reached: they were missing from KINDS
    (Testing Design — What the graphics review taught). A sweep is only as
    wide as its list, so the list is checked against the model enums.
    """

    # (class, model) pairs with no constructor, each with its reason.
    NOT_CONSTRUCTIBLE = {
        ("Box", "SPINE"): "Box has no p1=, p2=, height= constructor (a region, not a spine)",
        ("Square", "CORNER_CORNER"): "Square takes center= or top_left= with length=",
        ("Square", "POINT_VEC"): "Square takes center= or top_left= with length=",
        ("Square", "SPINE"): "Square takes center= or top_left= with length=",
        ("Track", "SHAPE"): "Track(shape) derives its curve from the source; covered in test_tracks",
    }

    @staticmethod
    def _built():
        """(class name -> model enum, set of model names KINDS builds)."""
        from enum import Enum
        enums, seen = {}, {}
        with fresh_world() as w:
            for kind in KINDS:
                model = getattr(_new(w, kind, dict(G.P0)), "model", None)
                if isinstance(model, Enum):
                    name = type(_new(w, kind, dict(G.P0))).__name__
                    enums[name] = type(model)
                    seen.setdefault(name, set()).add(model.name)
        return enums, seen

    def test_every_model_has_a_kind(self):
        enums, seen = self._built()
        missing = sorted((cls, m.name) for cls, enum in enums.items() for m in enum
                         if m.name not in seen[cls] and (cls, m.name) not in self.NOT_CONSTRUCTIBLE)
        self.assertFalse(missing, "models with no entry in geometry_support.KINDS "
                         f"(add a builder, or a reason to NOT_CONSTRUCTIBLE): {missing}")

    def test_exclusions_are_not_stale(self):
        _enums, seen = self._built()
        stale = sorted(k for k in self.NOT_CONSTRUCTIBLE if k[1] in seen.get(k[0], ()))
        self.assertFalse(stale, f"NOT_CONSTRUCTIBLE entries KINDS now builds (remove them): {stale}")


class TestContractCanaries(unittest.TestCase):
    """Each family catches its bug class (SCENA_CANARIES; ``diff_support.assert_catches``)."""

    def _catch(self, test_id, patches, what):
        from diff_support import assert_catches
        assert_catches(self, f"test_geometry_contract.{test_id}", patches, what)

    def test_c1_catches_a_rotation_only_flip(self):
        from scena.shapes import Shape
        self._catch("TestC1PointStability.test_sweep",
                    [(RegularPolygon, "_mirror_geometry", Shape._mirror_geometry)],
                    "RegularPolygon flip through the generic rotation mirror")

    def test_c4_catches_a_stale_vec(self):
        self._catch("TestC4Readback.test_sweep",
                    [(Rect, "_refresh_live_vec", lambda self: None)],
                    "Rect update skips the Derivate vec")

    def test_c6_catches_a_hit_test_that_ignores_the_shape(self):
        self._catch("TestC6CrossView.test_sweep",
                    [(Rect, "_hit_test_xy", lambda self, x, y: True)],
                    "Rect hit test answers True everywhere")

    def test_c7_catches_a_clone_that_drops_names(self):
        self._catch("TestC7Copies.test_sweep",
                    [(Rect, "_adopt_names", lambda self, signs: None)],
                    "Rect clone drops the name signs")

    def test_c7_catches_a_clone_that_drops_the_pose(self):
        from scena.entity import Graphic
        self._catch("TestC7Copies.test_sweep",
                    [(Graphic, "_clone_pose_from", lambda self, source: None)],
                    "clone leaves rotation / scale / flips at their defaults")


def prune_known() -> None:
    """Rewrite ``geometry_known.py`` without the entries that now pass.

    Shrink-only by construction: it never adds a violation (a new one must be
    triaged, not listed). ``python tests/test_geometry_contract.py --prune``
    """
    import re
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geometry_known.py")
    text = open(path, encoding="utf-8").read()
    removed = 0
    for fid, sweep in SWEEPS.items():
        found = {}
        for pose in SWEEP_POSES:
            found.update(sweep(KINDS, dict(pose)))
        for key in sorted(KNOWN[fid] - set(found)):
            pattern = r"\n        " + re.escape(repr(key)) + r",[^\n]*"
            text, n = re.subn(pattern, "", text, count=1)
            removed += n
    open(path, "w", encoding="utf-8").write(text)
    print(f"pruned {removed} fixed entries from geometry_known.py")


if __name__ == "__main__":
    if "--prune" in sys.argv:
        prune_known()
    else:
        unittest.main()
