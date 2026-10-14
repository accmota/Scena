"""
Geometry query tests: intersections / intersection / closest_point.

Run headless:

    python -m unittest tests.test_geom -v
"""

from __future__ import annotations

import math
import os
import random
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import repo_layout as layout  # noqa: E402
from scena.box import Box
from scena.geom import (
    _allowlist_types,
    _closest_on_segment,
    _collapsed_axis_segment,
    _conic_collapsed,
    _conic_params,
    _is_conic,
    _is_line,
    _line_segment,
    _outline_segments,
    _to_unit,
    closest_point,
    intersection,
    intersections,
)
from scena.shapes import (
    Circle, Ellipse, Triangle, Line, Point, Polygon, Rect,
    RegularPolygon, Square,
)
from scena.scenamath import Vec2
from scena.track import Track

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


class GeomTestCase(unittest.TestCase):
    def assertPointAlmost(self, got, x, y, places=5, msg=None):
        self.assertAlmostEqual(got[0], x, places=places, msg=msg)
        self.assertAlmostEqual(got[1], y, places=places, msg=msg)

    def assertPointsSetAlmost(self, got, expected, places=5):
        self.assertEqual(len(got), len(expected), f"got {got!r} vs {expected!r}")
        remaining = list(expected)
        for g in got:
            match = None
            for i, e in enumerate(remaining):
                if (
                    abs(g[0] - e[0]) < 10 ** (-places)
                    and abs(g[1] - e[1]) < 10 ** (-places)
                ):
                    match = i
                    break
            self.assertIsNotNone(match, f"{g} not in {expected}; got={got}")
            remaining.pop(match)


# ---------------------------------------------------------------------------
# line × line
# ---------------------------------------------------------------------------

class TestLineLine(GeomTestCase):
    def test_cross(self):
        a = Line(p1=(0, 0), p2=(10, 10))
        b = Line(p1=(0, 10), p2=(10, 0))
        hits = intersections(a, b)
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 5, 5)

    def test_parallel(self):
        a = Line(p1=(0, 0), p2=(10, 0))
        b = Line(p1=(0, 2), p2=(10, 2))
        self.assertEqual(intersections(a, b), [])

    def test_endpoint_touch(self):
        a = Line(p1=(0, 0), p2=(5, 0))
        b = Line(p1=(5, 0), p2=(5, 5))
        hits = intersections(a, b)
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 5, 0)

    def test_collinear_overlap_empty(self):
        a = Line(p1=(0, 0), p2=(10, 0))
        b = Line(p1=(5, 0), p2=(15, 0))
        self.assertEqual(intersections(a, b), [])

    def test_order_along_first_line(self):
        # Two crossings with a polyline-like pair of segments via rect edges:
        # use two lines that don't apply; just check single-hit order is stable.
        a = Line(p1=(0, 0), p2=(20, 0))
        b = Line(p1=(10, -5), p2=(10, 5))
        hits = intersections(a, b)
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 10, 0)


# ---------------------------------------------------------------------------
# line × circle
# ---------------------------------------------------------------------------

class TestLineCircle(GeomTestCase):
    def test_two_hits(self):
        c = Circle(center=(0, 0), radius=5)
        line = Line(p1=(-10, 0), p2=(10, 0))
        hits = intersections(line, c)
        self.assertEqual(len(hits), 2)
        self.assertPointAlmost(hits[0], -5, 0)
        self.assertPointAlmost(hits[1], 5, 0)

    def test_tangent(self):
        c = Circle(center=(0, 0), radius=5)
        line = Line(p1=(-10, 5), p2=(10, 5))
        hits = intersections(line, c)
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 0, 5)

    def test_miss(self):
        c = Circle(center=(0, 0), radius=5)
        line = Line(p1=(-10, 6), p2=(10, 6))
        self.assertEqual(intersections(line, c), [])

    def test_segment_clip_misses_far_circle(self):
        c = Circle(center=(100, 0), radius=5)
        line = Line(p1=(0, 0), p2=(10, 0))
        self.assertEqual(intersections(line, c), [])

    def test_chord_order_p1_to_p2(self):
        c = Circle(center=(0, 0), radius=5)
        # Reversed segment → opposite order
        line = Line(p1=(10, 0), p2=(-10, 0))
        hits = intersections(line, c)
        self.assertPointAlmost(hits[0], 5, 0)
        self.assertPointAlmost(hits[1], -5, 0)


# ---------------------------------------------------------------------------
# circle × circle
# ---------------------------------------------------------------------------

class TestCircleCircle(GeomTestCase):
    def test_two_hits(self):
        a = Circle(center=(0, 0), radius=5)
        b = Circle(center=(6, 0), radius=5)
        hits = intersections(a, b)
        self.assertEqual(len(hits), 2)
        # Left then right of a→b (+x): left is +y, right is -y
        self.assertPointAlmost(hits[0], 3, 4)
        self.assertPointAlmost(hits[1], 3, -4)

    def test_external_tangent(self):
        a = Circle(center=(0, 0), radius=5)
        b = Circle(center=(10, 0), radius=5)
        hits = intersections(a, b)
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 5, 0)

    def test_separate(self):
        a = Circle(center=(0, 0), radius=5)
        b = Circle(center=(20, 0), radius=5)
        self.assertEqual(intersections(a, b), [])

    def test_one_inside_no_touch(self):
        a = Circle(center=(0, 0), radius=10)
        b = Circle(center=(1, 0), radius=2)
        self.assertEqual(intersections(a, b), [])

    def test_concentric(self):
        a = Circle(center=(0, 0), radius=5)
        b = Circle(center=(0, 0), radius=3)
        self.assertEqual(intersections(a, b), [])


# ---------------------------------------------------------------------------
# line / circle × rect / square / polygon
# ---------------------------------------------------------------------------

class TestWithPolygons(GeomTestCase):
    def test_line_axis_aligned_rect(self):
        r = Rect(center=(0, 0), width=20, height=10)
        line = Line(p1=(-30, 0), p2=(30, 0))
        hits = intersections(line, r)
        self.assertEqual(len(hits), 2)
        self.assertPointAlmost(hits[0], -10, 0)
        self.assertPointAlmost(hits[1], 10, 0)

    def test_circle_inside_square_no_outline_cross(self):
        sq = Square(center=(0, 0), length=40)
        c = Circle(center=(0, 0), radius=5)
        self.assertEqual(intersections(c, sq), [])

    def test_circle_square_corner_dedupe(self):
        # Circle through a square corner should yield that corner once
        # (shared by two edges).
        sq = Square(center=(0, 0), length=20)  # corners at (±10, ±10)
        # Circumcircle of the square: centre 0, radius √200 ≈ 14.14
        c = Circle(center=(0, 0), radius=math.sqrt(200))
        hits = intersections(c, sq)
        self.assertEqual(len(hits), 4)
        self.assertPointsSetAlmost(
            hits,
            [(10, 10), (10, -10), (-10, 10), (-10, -10)],
        )

    def test_regular_polygon_edges(self):
        hexagon = RegularPolygon(n=6, center=(0, 0), radius=10, angle=0)
        line = Line(p1=(-20, 0), p2=(20, 0))
        hits = intersections(line, hexagon)
        self.assertGreaterEqual(len(hits), 2)

    def test_equilateral_triangle(self):
        t = Triangle(center=(0, 0), radius=20)
        line = Line(p1=(-30, 0), p2=(30, 0))
        hits = intersections(line, t)
        self.assertGreaterEqual(len(hits), 1)

    def test_free_polygon(self):
        poly = Polygon(points=[(0, 0), (20, 0), (20, 10), (0, 10)])
        line = Line(p1=(-5, 5), p2=(25, 5))
        hits = intersections(line, poly)
        self.assertEqual(len(hits), 2)
        self.assertPointAlmost(hits[0], 0, 5)
        self.assertPointAlmost(hits[1], 20, 5)


# ---------------------------------------------------------------------------
# intersection slots / stand-in / live chord
# ---------------------------------------------------------------------------

class TestIntersectionSlots(GeomTestCase):
    def test_two_hits_indexed(self):
        a = Circle(center=(0, 0), radius=5)
        b = Circle(center=(6, 0), radius=5)
        self.assertPointAlmost(intersection(a, b, 0), 3, 4)
        self.assertPointAlmost(intersection(a, b, 1), 3, -4)

    def test_tangent_fills_both_slots(self):
        a = Circle(center=(0, 0), radius=5)
        b = Circle(center=(10, 0), radius=5)
        p0 = intersection(a, b, 0)
        p1 = intersection(a, b, 1)
        self.assertPointAlmost(p0, 5, 0)
        self.assertPointAlmost(p1, 5, 0)

    def test_none_stand_in_never_throws(self):
        a = Circle(center=(0, 0), radius=5)
        b = Circle(center=(20, 0), radius=5)
        p = intersection(a, b, 0)
        self.assertIsInstance(p, tuple)
        self.assertEqual(len(p), 2)
        # Stand-in on a toward b: (5, 0)
        self.assertPointAlmost(p, 5, 0)

    def test_negative_index(self):
        a = Circle(center=(0, 0), radius=5)
        b = Circle(center=(6, 0), radius=5)
        with self.assertRaises(ValueError):
            intersection(a, b, -1)

    def test_live_chord_follows(self):
        c1 = Circle(center=(0, 0), radius=5)
        c2 = Circle(center=(6, 0), radius=5)
        chord = Line(
            p1=lambda: intersection(c1, c2, 0),
            p2=lambda: intersection(c1, c2, 1),
        )
        self.assertPointAlmost((chord.p1.x, chord.p1.y), 3, 4)
        self.assertPointAlmost((chord.p2.x, chord.p2.y), 3, -4)
        c2.center.move_to(8, 0)
        # Re-read linked endpoints
        self.assertAlmostEqual(float(chord.p1.x) + float(chord.p2.x), 8.0, places=4)
        # Still two crossings while overlapping
        self.assertEqual(len(intersections(c1, c2)), 2)


# ---------------------------------------------------------------------------
# closest_point
# ---------------------------------------------------------------------------

class TestClosestPoint(GeomTestCase):
    def test_circle_outside(self):
        c = Circle(center=(0, 0), radius=5)
        self.assertPointAlmost(closest_point(c, (10, 0)), 5, 0)

    def test_circle_inside(self):
        c = Circle(center=(0, 0), radius=5)
        self.assertPointAlmost(closest_point(c, (1, 2)), 1, 2)

    def test_circle_centre_convention(self):
        c = Circle(center=(0, 0), radius=5)
        self.assertPointAlmost(closest_point(c, (0, 0)), 5, 0)

    def test_rect_outside_and_inside(self):
        r = Rect(center=(0, 0), width=20, height=10)
        self.assertPointAlmost(closest_point(r, (30, 0)), 10, 0)
        self.assertPointAlmost(closest_point(r, (1, 2)), 1, 2)

    def test_line_clamp(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        self.assertPointAlmost(closest_point(line, (5, 3)), 5, 0)
        self.assertPointAlmost(closest_point(line, (-2, 1)), 0, 0)
        self.assertPointAlmost(closest_point(line, (12, 1)), 10, 0)

    def test_polygon_inside(self):
        poly = Polygon(points=[(0, 0), (10, 0), (10, 10), (0, 10)])
        self.assertPointAlmost(closest_point(poly, (3, 4)), 3, 4)

    def test_accepts_vec2_and_tuple(self):
        c = Circle(center=(0, 0), radius=5)
        self.assertPointAlmost(closest_point(c, Vec2(10, 0)), 5, 0)
        self.assertPointAlmost(closest_point(c, Point(10, 0)), 5, 0)

    def test_accepts_mouse_like_and_graphic(self):
        c = Circle(center=(0, 0), radius=5)
        mouseish = type("M", (), {"x": 10.0, "y": 0.0})()
        self.assertPointAlmost(closest_point(c, mouseish), 5, 0)
        mark = Circle(center=(10, 0), radius=1)
        self.assertPointAlmost(closest_point(c, mark), 5, 0)


# ---------------------------------------------------------------------------
# Errors / not collision
# ---------------------------------------------------------------------------

class TestErrors(GeomTestCase):
    def test_track_raises(self):
        # Track is a path, not one closed outline — still outside the allowlist.
        track = Track(points=[(0, 0), (10, 0), (10, 10)])
        c = Circle(center=(0, 0), radius=5)
        with self.assertRaises(TypeError):
            intersections(track, c)
        with self.assertRaises(TypeError):
            closest_point(track, (0, 0))

    def test_point_raises(self):
        p = Point(0, 0)
        c = Circle(center=(0, 0), radius=5)
        with self.assertRaises(TypeError):
            intersections(p, c)
        with self.assertRaises(TypeError):
            closest_point(p, (1, 1))

    def test_non_shape_raises(self):
        c = Circle(center=(0, 0), radius=5)
        with self.assertRaises(TypeError):
            intersections(c, "wall")

    def test_overlapping_aabb_no_outline_cross(self):
        # Two axis-aligned squares that overlap in area but outlines do not
        # cross (one fully inside the other).
        outer = Square(center=(0, 0), length=40)
        inner = Square(center=(0, 0), length=10)
        self.assertEqual(intersections(outer, inner), [])


# ---------------------------------------------------------------------------
# Ellipse
# ---------------------------------------------------------------------------

def _outline_residual(shape, x, y) -> float:
    """Distance from ``(x, y)`` to the shape's outline (0 when it lies on it)."""
    if _is_line(shape):
        x1, y1, x2, y2 = _line_segment(shape)
        qx, qy = _closest_on_segment(x, y, x1, y1, x2, y2)
        return math.hypot(qx - x, qy - y)
    if _is_conic(shape):
        conic = _conic_params(shape)
        if _conic_collapsed(conic):
            seg = _collapsed_axis_segment(conic)
            qx, qy = _closest_on_segment(x, y, *seg)
            return math.hypot(qx - x, qy - y)
        u, v = _to_unit(conic, x, y)
        ru = math.hypot(u, v)
        a, b = conic[2], conic[3]
        if ru < 1e-15:
            return min(a, b)
        local_r = math.hypot(a * u / ru, b * v / ru)
        return abs(ru - 1.0) * local_r
    best = float("inf")
    for seg in _outline_segments(shape):
        qx, qy = _closest_on_segment(x, y, *seg)
        best = min(best, math.hypot(qx - x, qy - y))
    return best


def _local_theta(shape, p) -> float:
    u, v = _to_unit(_conic_params(shape), p[0], p[1])
    th = math.atan2(v, u)
    if th < 0.0:
        th += 2.0 * math.pi
    return th


def _matrix_shape(cls, *, far=False):
    """One pose per allowlisted type. ``far`` shifts it off the origin."""
    x = 4000.0 if far else 0.0
    name = cls.__name__
    if name == "Line":
        return Line(p1=(x - 30, -5), p2=(x + 30, 5))
    if name == "Circle":
        return Circle(center=(x, 0), radius=15)
    if name == "Ellipse":
        return Ellipse(center=(x, 0), width=40, height=16, angle=20)
    if name == "Rect":
        return Rect(center=(x, 0), width=30, height=18, angle=-10)
    if name == "Square":
        return Square(center=(x, 0), length=28, angle=12)
    if name == "Polygon":
        return Polygon(points=[
            (x - 12, -8), (x + 14, -6), (x + 10, 12), (x - 8, 9),
        ])
    if name == "RegularPolygon":
        return RegularPolygon(n=5, center=(x, 0), radius=16, angle=8)
    if name == "Triangle":
        return Triangle(center=(x, 0), radius=18, angle=-15)
    if name == "Box":
        return Box(center=(x, 0), width=24, height=14, angle=15)
    raise AssertionError(f"no matrix pose for {name}")


class TestEllipse(GeomTestCase):
    def test_line_through_rotated_centre_ordered(self):
        e = Ellipse(center=(0, 0), width=40, height=20, angle=30)
        line = Line(p1=(-100, 0), p2=(100, 0))
        hits = intersections(line, e)
        self.assertEqual(len(hits), 2)
        self.assertLess(hits[0][0], hits[1][0])
        for x, y in hits:
            self.assertLess(_outline_residual(e, x, y), 1e-6)
            self.assertLess(_outline_residual(line, x, y), 1e-6)

    def test_two_ellipses_crossed_at_90_degrees(self):
        # x²/20² + y²/5² = 1 and the same ellipse turned 90°. Four crossings,
        # x² = y² = 400*25/425.
        e1 = Ellipse(center=(0, 0), width=40, height=10, angle=0)
        e2 = Ellipse(center=(0, 0), width=40, height=10, angle=90)
        hits = intersections(e1, e2)
        x = math.sqrt(400 * 25 / 425)
        self.assertPointsSetAlmost(
            hits,
            [(x, x), (-x, x), (-x, -x), (x, -x)],
            places=4,
        )
        thetas = [_local_theta(e1, p) for p in hits]
        self.assertEqual(thetas, sorted(thetas))

    def test_external_tangent_fills_both_slots(self):
        # Right tip of the 20×10 ellipse meets the left tip of the partner.
        a = Ellipse(center=(0, 0), width=20, height=10)
        b = Ellipse(center=(15, 0), width=10, height=10)
        hits = intersections(a, b)
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 10, 0, places=5)
        self.assertPointAlmost(intersection(a, b, 0), 10, 0, places=5)
        self.assertPointAlmost(intersection(a, b, 1), 10, 0, places=5)

    def test_ellipse_inside_circle_stand_in(self):
        c = Circle(center=(0, 0), radius=20)
        e = Ellipse(center=(0, 0), width=6, height=4)
        self.assertEqual(intersections(e, c), [])
        p = intersection(e, c, 3)
        self.assertIsInstance(p, tuple)
        self.assertEqual(len(p), 2)

    def test_concentric_identical_ellipses_empty(self):
        a = Ellipse(center=(1, 2), width=30, height=12, angle=40)
        b = Ellipse(center=(1, 2), width=30, height=12, angle=40)
        self.assertEqual(intersections(a, b), [])

    def test_collapsed_segment_and_point(self):
        flat = Ellipse(center=(0, 0), width=20, height=0)
        hits = intersections(flat, Line(p1=(0, -5), p2=(0, 5)))
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 0, 0)
        turned = Ellipse(center=(0, 0), width=20, height=0, angle=90)
        hits = intersections(turned, Line(p1=(-5, 0), p2=(5, 0)))
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 0, 0)
        point = Ellipse(center=(0, 0), width=0, height=0)
        hits = intersections(point, Line(p1=(-5, 0), p2=(5, 0)))
        self.assertEqual(len(hits), 1)
        self.assertPointAlmost(hits[0], 0, 0)
        self.assertEqual(
            intersections(point, Line(p1=(-5, 3), p2=(5, 3))),
            [],
        )

    def test_from_rect_follows_host(self):
        host = Rect(center=(0, 0), width=30, height=16)
        e = Ellipse(from_rect=host)
        line = Line(p1=(-40, 0), p2=(40, 0))
        before = intersections(e, line)
        self.assertEqual(len(before), 2)
        host.center.move_to(5, 0)
        after = intersections(e, line)
        self.assertEqual(len(after), 2)
        self.assertAlmostEqual(after[0][0], before[0][0] + 5, places=4)
        self.assertAlmostEqual(after[1][0], before[1][0] + 5, places=4)

    def test_live_chord_follows_move_by(self):
        c = Circle(center=(0, 0), radius=8)
        e = Ellipse(center=(6, 0), width=12, height=8)
        self.assertEqual(len(intersections(c, e)), 2)
        chord = Line(
            p1=lambda: intersection(c, e, 0),
            p2=lambda: intersection(c, e, 1),
        )
        x_before = float(chord.p1.x)
        e.move_by(1, 0)
        self.assertEqual(len(intersections(c, e)), 2)
        self.assertNotAlmostEqual(float(chord.p1.x), x_before, places=3)

    def test_round_ellipse_matches_circle_circle(self):
        c = Circle(center=(0, 0), radius=10)
        e = Ellipse(center=(4, 1), width=20, height=20, angle=33)
        other = Circle(center=(4, 1), radius=10)
        self.assertPointsSetAlmost(
            intersections(c, e), intersections(c, other), places=5,
        )

    def test_ellipse_rect_matches_dense_polygon(self):
        e = Ellipse(center=(1, -2), width=50, height=30, angle=20)
        rect = Rect(center=(10, 0), width=40, height=24, angle=-15)
        hits = intersections(e, rect)
        self.assertGreaterEqual(len(hits), 1)
        cx, cy, w, h, ang = e._oriented_frame()
        a, b = w * 0.5, h * 0.5
        rad = math.radians(ang)
        co, si = math.cos(rad), math.sin(rad)
        pts = []
        for i in range(512):
            th = 2.0 * math.pi * i / 512
            lx, ly = a * math.cos(th), b * math.sin(th)
            pts.append((cx + lx * co - ly * si, cy + lx * si + ly * co))
        poly = Polygon(points=pts)
        phits = intersections(poly, rect)
        for hx, hy in hits:
            self.assertTrue(
                any(math.hypot(hx - px, hy - py) < 0.1 for px, py in phits),
                f"{(hx, hy)} not near {phits}",
            )

    def test_residual_on_random_poses(self):
        rng = random.Random(0)

        def ell():
            return Ellipse(
                center=(rng.uniform(-30, 30), rng.uniform(-30, 30)),
                width=rng.uniform(5, 40),
                height=rng.uniform(5, 40),
                angle=rng.uniform(-180, 180),
            )

        for _ in range(20):
            e = ell()
            partners = [
                ell(),
                Circle(
                    center=(rng.uniform(-30, 30), rng.uniform(-30, 30)),
                    radius=rng.uniform(4, 25),
                ),
                Line(
                    p1=(rng.uniform(-40, 40), rng.uniform(-40, 40)),
                    p2=(rng.uniform(-40, 40), rng.uniform(-40, 40)),
                ),
                Rect(
                    center=(rng.uniform(-30, 30), rng.uniform(-30, 30)),
                    width=rng.uniform(8, 40),
                    height=rng.uniform(8, 30),
                    angle=rng.uniform(-180, 180),
                ),
            ]
            for other in partners:
                hits = intersections(e, other)
                self.assertLessEqual(len(hits), 4)
                for x, y in hits:
                    self.assertLess(_outline_residual(e, x, y), 1e-4)
                    self.assertLess(_outline_residual(other, x, y), 1e-4)


class TestEllipseClosest(GeomTestCase):
    def test_outside_matches_rim_sample(self):
        e = Ellipse(center=(2, -3), width=40, height=18, angle=35)
        p = (30, 10)
        got = closest_point(e, p)
        self.assertLess(_outline_residual(e, got[0], got[1]), 1e-6)
        cx, cy, w, h, ang = e._oriented_frame()
        a, b = w * 0.5, h * 0.5
        rad = math.radians(ang)
        co, si = math.cos(rad), math.sin(rad)
        best = float("inf")
        for i in range(4000):
            th = 2.0 * math.pi * i / 4000
            lx, ly = a * math.cos(th), b * math.sin(th)
            x = cx + lx * co - ly * si
            y = cy + lx * si + ly * co
            best = min(best, math.hypot(x - p[0], y - p[1]))
        got_d = math.hypot(got[0] - p[0], got[1] - p[1])
        self.assertLessEqual(got_d, best + 1e-6)

    def test_inside_centre_and_rim(self):
        e = Ellipse(center=(2, -3), width=40, height=18, angle=35)
        self.assertPointAlmost(closest_point(e, (2, -3)), 2, -3)
        self.assertPointAlmost(closest_point(e, (3, -3)), 3, -3)
        cx, cy, w, h, ang = e._oriented_frame()
        a = w * 0.5
        rad = math.radians(ang)
        rim = (cx + a * math.cos(rad), cy + a * math.sin(rad))
        self.assertPointAlmost(closest_point(e, rim), rim[0], rim[1], places=5)

    def test_collapsed_is_the_segment(self):
        e = Ellipse(center=(0, 0), width=20, height=0)
        self.assertPointAlmost(closest_point(e, (3, 4)), 3, 0)
        self.assertPointAlmost(closest_point(e, (30, 1)), 10, 0)


class TestConicOrder(GeomTestCase):
    def test_circle_first_against_square_follows_theta(self):
        # Corners of the square, from local +x toward local +y.
        sq = Square(center=(0, 0), length=20)
        c = Circle(center=(0, 0), radius=math.sqrt(200))
        hits = intersections(c, sq)
        self.assertEqual(len(hits), 4)
        self.assertPointAlmost(hits[0], 10, 10)
        self.assertPointAlmost(hits[1], -10, 10)
        self.assertPointAlmost(hits[2], -10, -10)
        self.assertPointAlmost(hits[3], 10, -10)

    def test_ellipse_first_against_ellipse_follows_theta(self):
        e1 = Ellipse(center=(0, 0), width=40, height=10, angle=0)
        e2 = Ellipse(center=(0, 0), width=40, height=10, angle=90)
        hits = intersections(e1, e2)
        thetas = [_local_theta(e1, p) for p in hits]
        self.assertGreater(len(thetas), 1)
        self.assertEqual(thetas, sorted(thetas))


class TestAllowlistMatrix(GeomTestCase):
    """Every allowlisted pair must answer. A missed branch (``_shape_center``,
    ordering, stand-in) fails here for any type added later."""

    def test_every_pair_crossing_and_disjoint(self):
        types = _allowlist_types()
        for cls_a in types:
            for cls_b in types:
                for far in (False, True):
                    for swap in (False, True):
                        a = _matrix_shape(cls_a, far=False)
                        b = _matrix_shape(cls_b, far=far)
                        if swap:
                            a, b = b, a
                        hits = intersections(a, b)
                        self.assertIsInstance(hits, list)
                        for slot in (0, 5):
                            p = intersection(a, b, slot)
                            self.assertIsInstance(p, tuple)
                            self.assertEqual(len(p), 2)
                        q = closest_point(a, (1.0, 2.0))
                        self.assertIsInstance(q, tuple)
                        self.assertEqual(len(q), 2)


class TestAllowlistDocs(unittest.TestCase):
    """The allowlist is written once, in ``_allowlist_types``."""

    def test_design_and_guia_match_code(self):
        expected = {t.__name__ for t in _allowlist_types()}

        design_path = os.path.join(layout.DESIGN, "Shapes Design.md")
        with open(design_path, encoding="utf-8") as f:
            design = f.read()
        mark = "**Allowlist:**"
        i = design.find(mark)
        self.assertGreaterEqual(i, 0, "Shapes Design is missing **Allowlist:**")
        sentence = design[i:design.find(".", i)]
        documented = set(re.findall(r"`([A-Za-z]+)`", sentence))
        self.assertEqual(documented, expected)

        guia_path = layout.GUIDE_HTML
        with open(guia_path, encoding="utf-8") as f:
            guia = f.read()
        sec = guia.find('id="geo-intersecoes"')
        self.assertGreaterEqual(sec, 0)
        end = guia.find("<section", sec + 10)
        chunk = guia[sec:end if end != -1 else None]
        row = re.search(
            r"<td>Permitidos</td>\s*<td>(.*?)</td>", chunk, re.S,
        )
        self.assertIsNotNone(row, "Guia is missing the Permitidos row")
        codes = set(re.findall(r"<code>([A-Za-z]+)</code>", row.group(1)))
        self.assertEqual(codes, expected)


if __name__ == "__main__":
    unittest.main()
