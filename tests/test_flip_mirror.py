"""Flips mirror every shape kind in place (class guard: a mirror applied as a rotation).

``flip_x`` / ``flip_y`` must redraw the mirror image of the shape about its
``center``: the drawn geometry after the flip is the mirror of the geometry
before, the shape does not move, and flipping twice is the identity. Rect /
Square also mirror each named point (``test_rect_names``); here the check is
the drawn geometry of every kind.

Testing Design G6: EquilateralTriangle mirrored ``angle`` instead of its
apex heading (a different triangle); RegularPolygon / EquilateralTriangle
``vertex=`` left the Defining vertex in place (the polygon swung about it).

    python -m unittest tests.test_flip_mirror -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import example, given, strategies as hst  # noqa: E402

from scena import (  # noqa: E402
    Circle, Ellipse, EquilateralTriangle, Line, Polygon, Rect, RegularPolygon, Square,
)
from scena.shapes import get_xy  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def xy(p):
    return (float(p.x), float(p.y))


def _arc_ends(c):
    cx, cy = xy(c.center)
    r, a, s = float(c.radius), float(c.angle), float(c.spread)
    return [
        (cx + r * math.cos(math.radians(a + d)), cy + r * math.sin(math.radians(a + d)))
        for d in (-s / 2.0, s / 2.0)
    ]


def _box_corners(r):
    cx, cy, w, h, ang = r._oriented_frame()
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    return [
        (cx + sx * w / 2 * c - sy * h / 2 * s, cy + sx * w / 2 * s + sy * h / 2 * c)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]


def drawn(obj):
    """The points that fix what is drawn (a set: order and identity do not matter here)."""
    if isinstance(obj, Line):
        pts = [xy(obj.p1), xy(obj.p2)]
    elif isinstance(obj, Circle):
        pts = [xy(obj.center)] + _arc_ends(obj)
    elif isinstance(obj, Ellipse):
        pts = [xy(obj.center), xy(obj.fp1), xy(obj.fp2)]
    elif isinstance(obj, (Rect, Square)):
        pts = _box_corners(obj)
    else:  # Polygon, RegularPolygon, EquilateralTriangle
        pts = [xy(p) for p in obj.points]
    return sorted((round(x, 6) + 0.0, round(y, 6) + 0.0) for x, y in pts)


KINDS = {
    "Line": lambda rot: Line(p1=(0, 0), p2=(10, 4)).rotate_by(rot),
    "Circle arc": lambda rot: Circle(center=(1, 2), radius=9, angle=30 + rot, spread=120),
    "Ellipse center_wh": lambda rot: Ellipse(center=(0, 0), width=12, height=5, angle=rot),
    "Ellipse focal_points": lambda rot: Ellipse(fp1=(-3, 1), fp2=(3, 2), major_axis=10).rotate_by(rot),
    "Polygon": lambda rot: Polygon(points=[(0, 0), (10, 0), (12, 8), (0, 6)]).rotate_by(rot),
    "RegularPolygon center_radius": lambda rot: RegularPolygon(center=(3, 4), radius=6, n=5, angle=rot),
    "RegularPolygon center_side": lambda rot: RegularPolygon(center=(3, 4), side=6, n=4, angle=rot),
    "RegularPolygon vertex_side": lambda rot: RegularPolygon(vertex=(3, 4), side=6, n=5, angle=rot),
    "EquilateralTriangle center_radius": lambda rot: EquilateralTriangle(center=(3, 4), radius=6, angle=rot),
    "EquilateralTriangle center_side": lambda rot: EquilateralTriangle(center=(3, 4), side=6, angle=rot),
    "EquilateralTriangle vertex_side": lambda rot: EquilateralTriangle(vertex=(3, 4), side=6, angle=rot),
    "Rect point_vec": lambda rot: Rect(p1=(3, 4), vec=(40, 16), angle=rot),
    "Rect spine side_left": lambda rot: Rect(p1=(0, 0), p2=(40, 10), height=12, anchor="side_left").rotate_by(rot),
    "Square top_left_length": lambda rot: Square(top_left=(0, 20), length=20, angle=rot),
}


def _mirror(pts, c, axis):
    cx, cy = c
    out = [(2 * cx - x, y) if axis == "x" else (x, 2 * cy - y) for x, y in pts]
    return sorted((round(x, 6) + 0.0, round(y, 6) + 0.0) for x, y in out)


class TestFlipMirrorsEveryKind(unittest.TestCase):
    def assertSamePoints(self, got, want, msg):
        self.assertEqual(len(got), len(want), msg)
        for g, w in zip(got, want):
            self.assertTrue(abs(g[0] - w[0]) <= 1e-5 and abs(g[1] - w[1]) <= 1e-5,
                            f"{msg}: {got} != {want}")

    @given(
        kind=hst.sampled_from(sorted(KINDS)),
        rot=hst.integers(-180, 180),
        axis=hst.sampled_from(["x", "y"]),
    )
    # G6: the triangle drew a different triangle; vertex= models moved.
    @example(kind="EquilateralTriangle center_radius", rot=10, axis="x")
    @example(kind="EquilateralTriangle vertex_side", rot=0, axis="y")
    @example(kind="RegularPolygon vertex_side", rot=10, axis="x")
    def test_flip_draws_the_mirror_in_place(self, kind, rot, axis):
        obj = KINDS[kind](rot)
        center = xy(obj.center)
        before = drawn(obj)
        setattr(obj, "flip_" + axis, True)
        self.assertSamePoints(drawn(obj), _mirror(before, center, axis),
                              f"{kind} flip_{axis} at {rot}")
        self.assertSamePoints([xy(obj.center)], [center], f"{kind}: the center moved")
        setattr(obj, "flip_" + axis, False)
        self.assertSamePoints(drawn(obj), before, f"{kind}: flip twice is not the identity")

    def test_triangle_flip_mirrors_the_apex_heading(self):
        # G6 repro: a flipped triangle is the triangle whose apex heading is mirrored.
        for axis, heading in (("x", 170), ("y", -10)):
            t = EquilateralTriangle(center=(0, 0), radius=10, angle=10)
            setattr(t, "flip_" + axis, True)
            want = drawn(EquilateralTriangle(center=(0, 0), radius=10, angle=heading))
            self.assertSamePoints(drawn(t), want, f"triangle flip_{axis}")


INDEXED = {k: v for k, v in KINDS.items()
           if k.startswith(("Polygon", "RegularPolygon", "EquilateralTriangle"))}


class TestVerticesFollowTheirPoints(unittest.TestCase):
    """Named-points rule for indexed vertices: ``points[k]`` lands on the mirror
    of the old ``points[k]`` (Shapes Design — RegularPolygon, winding)."""

    def assertXY(self, got, want, msg):
        self.assertTrue(abs(got[0] - want[0]) <= 1e-5 and abs(got[1] - want[1]) <= 1e-5,
                        f"{msg}: {got} != {want}")

    @given(
        kind=hst.sampled_from(sorted(INDEXED)),
        rot=hst.integers(-180, 180),
        axes=hst.lists(hst.sampled_from(["x", "y"]), min_size=1, max_size=3),
    )
    @example(kind="RegularPolygon center_radius", rot=10, axes=["x"])
    def test_every_vertex_lands_on_its_mirror(self, kind, rot, axes):
        obj = INDEXED[kind](rot)
        cx, cy = xy(obj.center)
        pts = [xy(p) for p in obj.points]
        for axis in axes:
            flag = "flip_" + axis
            setattr(obj, flag, not getattr(obj, flag))
            pts = [(2 * cx - x, y) if axis == "x" else (x, 2 * cy - y) for x, y in pts]
            for k, p in enumerate(obj.points):
                self.assertXY(xy(p), pts[k], f"{kind} after flip_{axis}: points[{k}]")

    def test_a_link_on_a_vertex_follows_it_through_a_flip(self):
        hexagon = RegularPolygon(center=(0, 0), radius=10, n=6, angle=0)
        tip = Line(p1=(0, 0), p2=lambda: hexagon.points[1])
        before = xy(tip.p2)
        hexagon.flip_x = True
        self.assertXY(xy(tip.p2), (-before[0], before[1]), "linked points[1]")

    def test_winding_shows_in_signed_area_and_survives_clone(self):
        for obj in (RegularPolygon(center=(1, 2), radius=5, n=5, angle=10),
                    EquilateralTriangle(vertex=(3, 4), side=6, angle=20)):
            with self.subTest(kind=type(obj).__name__):
                area = float(obj.signed_area)
                self.assertGreater(area, 0.0)
                obj.flip_y = True
                self.assertAlmostEqual(float(obj.signed_area), -area, places=6)  # CW now
                copy = obj.clone()
                for a, b in zip(obj.points, copy.points):
                    self.assertXY(xy(b), xy(a), "clone keeps vertex identity")


class TestRegularPolygonStatsMatchAFreePolygon(unittest.TestCase):
    """RegularPolygon's Derivate stats equal a free Polygon's on the same vertices,
    on the very first read (class guard: a Derivate missing from the update —
    G8: ``signed_area`` read 0 and ``perimeter_length`` 0 on first read)."""

    def test_first_read_of_each_stat_is_right(self):
        for kind in sorted(INDEXED):
            if kind == "Polygon":
                continue
            for stat in ("signed_area", "perimeter_length", "centroid"):
                with self.subTest(kind=kind, stat=stat):
                    obj = INDEXED[kind](15)
                    got = getattr(obj, stat)             # the first read
                    ref = getattr(Polygon(points=[xy(p) for p in obj.points]), stat)
                    if stat == "centroid":
                        self.assertTrue(abs(got.x - ref.x) < 1e-6 and abs(got.y - ref.y) < 1e-6)
                    else:
                        self.assertAlmostEqual(float(got), float(ref), places=6)

    def test_stats_do_not_depend_on_what_was_read_first(self):
        # G8 was incomplete: reading ``side`` (or ``radius``) first left the stats at 0.
        for first in ("side", "radius", "vertex", "center"):
            for stat in ("signed_area", "perimeter_length"):
                with self.subTest(first=first, stat=stat):
                    obj = RegularPolygon(center=(3, 4), radius=6, n=5, angle=10)
                    getattr(obj, first)
                    ref = Polygon(points=[xy(p) for p in obj.points])
                    self.assertAlmostEqual(float(getattr(obj, stat)), float(getattr(ref, stat)), places=6)

    def test_vertex_is_points_zero_in_every_model(self):
        for obj in (RegularPolygon(center=(3, 4), radius=6, n=5, angle=10),
                    RegularPolygon(center=(3, 4), side=6, n=4, angle=10),
                    EquilateralTriangle(center=(3, 4), radius=6, angle=10)):
            with self.subTest(model=obj.model):
                self.assertTrue(abs(obj.vertex.x - obj.points[0].x) < 1e-9 and abs(obj.vertex.y - obj.points[0].y) < 1e-9)
                obj.rotate_by(30)
                obj.scale_by(1.5)
                self.assertTrue(abs(obj.vertex.x - obj.points[0].x) < 1e-9 and abs(obj.vertex.y - obj.points[0].y) < 1e-9)

    def test_square_of_radius_five_has_area_fifty(self):
        # G8 repro.
        self.assertAlmostEqual(float(RegularPolygon(center=(0, 0), radius=5, n=4).signed_area), 50.0)


class TestFlipHeadingEdges(unittest.TestCase):
    """The heading a flip leaves where the geometry alone does not say it
    (Testing Design, geometry campaign: Q1, GX1–GX3)."""

    def test_spine_flip_applies_the_convention_to_the_unwrapped_heading(self):
        # Q1: 180 - θ / -θ on the unwrapped heading (it unwrapped toward the
        # previous heading: 500 for -220).
        for rot in (0.0, 30.0, 400.0, -220.0):
            for axis in ("x", "y"):
                r = Rect(p1=(0, 0), p2=(10, 0), height=3, anchor="cap")
                r.rotate_to(rot)
                setattr(r, f"flip_{axis}", True)
                want = 180.0 - rot if axis == "x" else -rot
                self.assertAlmostEqual(float(r.angle), want, msg=f"{rot} {axis}")
                self.assertAlmostEqual(float(r._rotation), want, msg=f"{rot} {axis}")

    def test_a_tall_ellipse_mirrors_each_focus(self):
        # GX1: height > width put the foci 90° the wrong way after a flip,
        # so fp1 and fp2 swapped.
        for w, h in ((10, 30), (30, 10)):
            for flips in (("x",), ("y",), ("x", "y")):
                e = Ellipse(center=(3, -2), width=w, height=h, angle=17)
                for axis in flips:
                    f1, f2 = xy(e.fp1), xy(e.fp2)
                    setattr(e, f"flip_{axis}", True)
                    for got, was in ((xy(e.fp1), f1), (xy(e.fp2), f2)):
                        want = (6.0 - was[0], was[1]) if axis == "x" else (was[0], -4.0 - was[1])
                        self.assertAlmostEqual(got[0], want[0], msg=f"{w}x{h} {flips}")
                        self.assertAlmostEqual(got[1], want[1], msg=f"{w}x{h} {flips}")

    def test_a_zero_length_line_flips_its_heading(self):
        # GX2: no point moves, so the derived heading kept its cached value.
        for build in (lambda: Line(p1=(0, 0), p2=(10, 0)), lambda: Line(p1=(0, 0), vec=(10, 0))):
            ln = build()
            ln.rotate_by(17)
            if ln.model.name == "POINT_POINT":
                ln.p2 = xy(ln.p1)
            else:
                ln.vec = (0, 0)
            h = float(ln.angle)            # read first: the cached value must not survive
            ln.flip_x = True
            self.assertAlmostEqual(float(ln.angle), 180.0 - h)
            ln.flip_y = True
            self.assertAlmostEqual(float(ln.angle), h - 180.0)
            self.assertAlmostEqual(float(ln._rotation), float(ln.angle))

    def test_a_flip_that_moves_no_point_rewrites_a_warm_heading(self):
        # GX21: placement points on the mirror axis (a vertical diameter under
        # flip_x, a horizontal one under flip_y) do not move, so nothing
        # refreshed a heading read before the flip: it kept 450 while the store
        # (and a clone, whose points moved by 1e-15) read -270.
        kinds = {   # placement parts on x = 0; flip_y swaps each pair (on y = 0)
            "Circle two_points": (Circle, {"p1": (0, 5), "p2": (0, -5)}),
            "Circle center_perimeter": (Circle, {"center": (0, 0), "perimeter_point": (0, 5)}),
            "Ellipse foci": (Ellipse, {"fp1": (0, -5), "fp2": (0, 5), "major_axis": 14}),
            "Line p1/p2": (Line, {"p1": (0, -5), "p2": (0, 5)}),
            "Line p1/vec": (Line, {"p1": (0, -5), "vec": (0, 10)}),
            "Rect spine": (Rect, {"p1": (0, -5), "p2": (0, 5), "height": 4, "anchor": "cap"}),
        }
        for name, (kind, kw) in kinds.items():
            for axis in ("x", "y"):
                parts = {k: (v[::-1] if axis == "y" else v) for k, v in kw.items()
                         if isinstance(v, tuple)}
                for turns in (0.0, 360.0, -720.0):
                    obj = kind(**{**kw, **parts})
                    obj.rotate_by(turns)
                    for part, here in parts.items():
                        setattr(obj, part, here)     # back exactly on the axis
                    # Read twice: the first read makes the Derivate live and
                    # leaves the shape dirty; the second leaves it clean.
                    float(obj.angle)
                    h = float(obj.angle)
                    setattr(obj, f"flip_{axis}", True)
                    want = 180.0 - h if axis == "x" else -h
                    msg = f"{name} flip_{axis} from {h}"
                    self.assertAlmostEqual(float(obj.angle), want, msg=msg)
                    self.assertEqual(float(obj.angle), float(obj._rotation), msg=msg)

    def test_a_clone_flips_its_heading_like_its_source(self):
        # GX21 as the C7 contract found it (deep profile, r=153): the source's
        # diameter was exactly vertical, the clone's 1e-15 off.
        def polar(r, a):
            return (r * 0.5 * math.cos(math.radians(a)), r * 0.5 * math.sin(math.radians(a)))
        src = Circle(p1=polar(9, 193), p2=polar(9, 373))
        src.flip_x = True
        src.rotate_by(20)
        src.scale_by(1.25)
        cp = src.clone()
        for act in (lambda o, a: o.move_by(7, -3), lambda o, a: o.rotate_to(a + 50),
                    lambda o, a: o.rotate_by(33), lambda o, a: o.scale_by(1.5),
                    lambda o, a: setattr(o, "flip_x", not o.flip_x)):
            a = float(src.angle)
            act(src, a)
            act(cp, a)
            self.assertEqual(float(src.angle), float(cp.angle))
        self.assertEqual(float(src.angle), -270.0)

    def test_a_zero_length_tangent_line_refuses_a_flip_like_any_length(self):
        # GX3: its points sat on the pivot, so the gate let the flip through
        # and the store left the drawn (tangent) heading.
        from scena.state import LinkedAttributeError
        for length in (20, 0):
            c = Circle(center=(0, 0), radius=9)
            ln = Line(circle=c, at_angle=30, length=20)
            ln.length = length
            for axis in ("x", "y"):
                with self.assertRaises(LinkedAttributeError, msg=f"{length} {axis}"):
                    setattr(ln, f"flip_{axis}", True)


class TestFlipMirrorCanary(unittest.TestCase):
    def test_mirroring_raw_rotation_is_caught(self):
        from diff_support import assert_catches
        from scena.shapes import Shape
        assert_catches(
            self,
            "test_flip_mirror.TestFlipMirrorsEveryKind.test_flip_draws_the_mirror_in_place",
            [(RegularPolygon, "_mirror_geometry", Shape._mirror_geometry)],
            "RegularPolygon flip through the generic rotation mirror",
        )


if __name__ == "__main__":
    unittest.main()
