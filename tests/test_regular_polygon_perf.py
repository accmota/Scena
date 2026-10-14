"""
RegularPolygon deferred vertex wiring + transform performance guards.

Covers:
  - cold vertices stay out of the dependents cone until first live access
  - move/rotate/scale correctness across models and read orderings
  - external formula links (captured Point/Attribute) stay live across transforms
  - rotate_by cost stays ~flat in n (guards O(n) bookkeeping regressions)

Run:
    python -m unittest tests.test_regular_polygon_perf -v
"""

import gc
import math
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import (
    Point, RegularPolygon, RegularPolygonModel, Triangle, get_xy,
)
from scena.state import get_scena_system

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _vertex_xy(n: int, idx: int, cx: float, cy: float, r: float, angle_deg: float):
    a = math.radians(angle_deg) + idx * (2.0 * math.pi / n)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def _shape_vertex_dependents(poly: RegularPolygon) -> set:
    """Node ids of poly._vertices (and their x/y) that are dependents of poly."""
    g = get_scena_system().dependency_graph
    deps = set(g.dependents.get(poly._node_id, ()))
    vertex_ids = set()
    for vtx in poly._vertices:
        if vtx._node_id in deps:
            vertex_ids.add(vtx._node_id)
        for part in vtx.parts:
            if part._node_id in deps:
                vertex_ids.add(part._node_id)
    return vertex_ids


class TestDeferredVertexWiring(unittest.TestCase):
    def test_fresh_regular_polygon_has_no_vertex_dependents(self):
        poly = RegularPolygon(n=60, center=(0, 0), radius=10)
        self.assertEqual(len(poly._wired_vertices), 0)
        self.assertEqual(_shape_vertex_dependents(poly), set())

    def test_equilateral_triangle_also_defers_wiring(self):
        tri = Triangle(center=(0, 0), radius=10)
        self.assertEqual(len(tri._wired_vertices), 0)
        self.assertEqual(_shape_vertex_dependents(tri), set())

    def test_points_index_wires_only_that_vertex(self):
        poly = RegularPolygon(n=12, center=(0, 0), radius=10)
        _ = poly.points[3]
        self.assertEqual(poly._wired_vertices, {3})
        # Other vertices remain unwired.
        for i, vtx in enumerate(poly._vertices):
            if i == 3:
                continue
            self.assertNotIn(vtx._node_id, get_scena_system().dependency_graph.dependents.get(poly._node_id, ()))

    def test_centroid_wires_all_vertices(self):
        poly = RegularPolygon(n=8, center=(2, -1), radius=5)
        _ = poly.centroid.x
        self.assertEqual(poly._wired_vertices, set(range(8)))
        self.assertAlmostEqual(poly.centroid.x, 2.0, places=5)
        self.assertAlmostEqual(poly.centroid.y, -1.0, places=5)


class TestTransformCorrectness(unittest.TestCase):
    def test_unread_then_rotate_then_read(self):
        """Move/rotate without ever reading verts, then read — values must be fresh."""
        poly = RegularPolygon(n=6, center=(0, 0), radius=10, angle=0.0)
        poly.rotate_by(30)
        poly.move_by(5, -3)
        ex, ey = _vertex_xy(6, 0, 5, -3, 10, 30)
        self.assertAlmostEqual(poly.points[0].x, ex, places=6)
        self.assertAlmostEqual(poly.points[0].y, ey, places=6)

    def test_read_then_rotate_then_read(self):
        poly = RegularPolygon(n=6, center=(0, 0), radius=10, angle=0.0)
        _ = poly.points[0].x  # wire + live
        poly.rotate_by(45)
        ex, ey = _vertex_xy(6, 0, 0, 0, 10, 45)
        self.assertAlmostEqual(poly.points[0].x, ex, places=6)
        self.assertAlmostEqual(poly.points[0].y, ey, places=6)

    def test_centroid_then_rotate_keeps_stats_and_verts(self):
        poly = RegularPolygon(n=5, center=(1, 2), radius=7, angle=0.0)
        _ = poly.centroid.x
        poly.rotate_by(20)
        self.assertAlmostEqual(poly.centroid.x, 1.0, places=4)
        self.assertAlmostEqual(poly.centroid.y, 2.0, places=4)
        ex, ey = _vertex_xy(5, 2, 1, 2, 7, 20)
        self.assertAlmostEqual(poly.points[2].x, ex, places=5)
        self.assertAlmostEqual(poly.points[2].y, ey, places=5)

    def test_center_side_rotate_and_scale(self):
        poly = RegularPolygon(n=4, center=(0, 0), side=10, angle=0.0)
        r0 = poly.radius
        poly.rotate_by(15)
        poly.scale_by(2.0)
        self.assertAlmostEqual(poly.side, 20.0, places=6)
        self.assertAlmostEqual(poly.radius, 2.0 * r0, places=5)
        self.assertAlmostEqual(poly.angle, 15.0, places=6)
        ex, ey = _vertex_xy(4, 0, 0, 0, 2.0 * r0, 15)
        self.assertAlmostEqual(poly.points[0].x, ex, places=5)
        self.assertAlmostEqual(poly.points[0].y, ey, places=5)

    def test_vertex_side_move_rotate_scale(self):
        poly = RegularPolygon(n=3, vertex=(10, 0), side=10, angle=0.0)
        poly.move_by(1, 2)
        self.assertAlmostEqual(poly.vertex.x, 11.0, places=6)
        self.assertAlmostEqual(poly.vertex.y, 2.0, places=6)
        poly.rotate_by(30)
        # vertex orbits about derived center
        self.assertAlmostEqual(poly.angle, 30.0, places=6)
        poly.scale_by(1.5)
        self.assertAlmostEqual(poly.side, 15.0, places=6)
        # points[0] tracks defining vertex
        self.assertAlmostEqual(poly.points[0].x, poly.vertex.x, places=5)
        self.assertAlmostEqual(poly.points[0].y, poly.vertex.y, places=5)

    def test_n3_and_large_n_rotate(self):
        for n in (3, 4, 48):
            with self.subTest(n=n):
                poly = RegularPolygon(n=n, center=(0, 0), radius=5, angle=0.0)
                poly.rotate_by(10)
                ex, ey = _vertex_xy(n, 0, 0, 0, 5, 10)
                self.assertAlmostEqual(poly.points[0].x, ex, places=5)
                self.assertAlmostEqual(poly.points[0].y, ey, places=5)

    def test_rotate_about_non_center_pivot(self):
        poly = RegularPolygon(n=6, center=(10, 0), radius=4, angle=0.0)
        poly.rotate_by(90, about=(0, 0))
        # center (10,0) → (0,10)
        self.assertAlmostEqual(poly.center.x, 0.0, places=5)
        self.assertAlmostEqual(poly.center.y, 10.0, places=5)
        self.assertAlmostEqual(poly.angle, 90.0, places=6)
        ex, ey = _vertex_xy(6, 0, 0, 10, 4, 90)
        self.assertAlmostEqual(poly.points[0].x, ex, places=5)
        self.assertAlmostEqual(poly.points[0].y, ey, places=5)


class TestExternalFormulaRegression(unittest.TestCase):
    def test_captured_vertex_attribute_stays_live_across_rotate(self):
        poly = RegularPolygon(n=6, center=(0, 0), radius=10, angle=0.0)
        v0 = poly.points[0]
        other = Point(0, 0)
        other["x"] @= lambda: v0.x * 2
        self.assertAlmostEqual(other.x, 20.0, places=6)

        poly.rotate_by(45)
        expected = 10 * math.cos(math.radians(45))
        self.assertAlmostEqual(v0.x, expected, places=6)
        self.assertAlmostEqual(other.x, 2 * expected, places=6)

    def test_captured_vertex_stays_live_across_move_and_scale(self):
        poly = RegularPolygon(n=8, center=(0, 0), radius=5, angle=0.0)
        v0 = poly.points[0]
        mirror = Point(0, 0)
        mirror._assign_formula(lambda: v0)

        poly.move_by(3, 4)
        poly.scale_by(2.0)
        # After move+scale about center: v0 at (3+10, 4) = (13, 4) for angle=0
        self.assertAlmostEqual(mirror.x, 13.0, places=5)
        self.assertAlmostEqual(mirror.y, 4.0, places=5)

    def test_link_after_rotate_without_prior_read(self):
        """Wire happens at link-setup via _note_became_link_source → materialize."""
        poly = RegularPolygon(n=6, center=(0, 0), radius=10, angle=0.0)
        poly.rotate_by(30)  # no vertex reads yet
        v0 = poly.points[0]
        other = Point(0, 0)
        other["x"] @= lambda: v0.x
        ex, _ = _vertex_xy(6, 0, 0, 0, 10, 30)
        self.assertAlmostEqual(other.x, ex, places=6)
        poly.rotate_by(15)
        ex2, _ = _vertex_xy(6, 0, 0, 0, 10, 45)
        self.assertAlmostEqual(other.x, ex2, places=6)


class TestPerfSmoke(unittest.TestCase):
    def test_rotate_by_cost_flat_in_n(self):
        """n=200 rotate_by must stay within a small factor of n=6 (no O(n) bookkeeping).

        Load-robust (WP18): both sizes are timed in short interleaved blocks
        (alternating which goes first) and each keeps its best block, so a
        loaded tier slows both sides alike and a preemption spike lands in
        one block only. GC is off while timing.
        """
        shapes, iters, repeats = 40, 8, 25

        def make(n: int) -> list:
            polys = [
                RegularPolygon(n=n, center=(i, 0), radius=10)
                for i in range(shapes)
            ]
            for p in polys:
                p.rotate_by(0.1)  # warmup
            return polys

        def block(polys: list) -> float:
            t0 = time.perf_counter()
            for _ in range(iters):
                for p in polys:
                    p.rotate_by(1.0)
            return (time.perf_counter() - t0) / (shapes * iters)

        p6, p200 = make(6), make(200)
        best6 = best200 = float("inf")
        gc_was_enabled = gc.isenabled()
        gc.collect()
        gc.disable()
        try:
            for r in range(repeats):
                if r % 2:
                    best200 = min(best200, block(p200))
                    best6 = min(best6, block(p6))
                else:
                    best6 = min(best6, block(p6))
                    best200 = min(best200, block(p200))
        finally:
            if gc_was_enabled:
                gc.enable()

        ratio = best200 / best6 if best6 > 0 else float("inf")
        # Before the fix this was ~20-25x; after, ~1x. Allow generous CI slack.
        self.assertLess(
            ratio, 4.0,
            f"rotate_by scaled with n: n=6={best6*1e6:.2f}us n=200={best200*1e6:.2f}us "
            f"ratio={ratio:.2f}x (best of {repeats} interleaved blocks; "
            f"expected ~1x, fail if >4x)",
        )


if __name__ == "__main__":
    unittest.main()
