"""Editor geometry: handles, resize in the rotated frame, snapping, hit tests.

Run: python -m unittest scena_editor.tests.test_editor_geometry
"""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import assume, given, strategies as hst  # noqa: E402

from scena_editor import geometry as geo  # noqa: E402


def rect(cx=0.0, cy=0.0, w=100.0, h=40.0, r=0.0, kind="rect"):
    return {"kind": kind, "center": (cx, cy), "width": w, "height": h, "angle": r}


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


_coord = hst.floats(-1000, 1000, allow_nan=False)
_extent = hst.floats(1, 500, allow_nan=False)
_angle = hst.floats(0, 360, allow_nan=False, exclude_max=True)
_signs = hst.sampled_from(geo.HANDLE_SIGNS)


class TestResize(unittest.TestCase):
    @given(cx=_coord, cy=_coord, w=_extent, h=_extent, r=_angle, signs=_signs,
           px=_coord, py=_coord)
    def test_opposite_handle_stays_fixed(self, cx, cy, w, h, r, signs, px, py):
        item = rect(cx, cy, w, h, r)
        anchor = geo.anchor_for(item, signs)
        new = {**item, **geo.resize(item, signs, anchor, (px, py))}
        # The fixed point is still a handle point of the new rect (dragging past
        # it flips the rect, so its name may change, not its place).
        points = [(h_.x, h_.y) for h_ in geo.handles(new, 0) if h_.role == "resize"]
        self.assertTrue(any(close(p, anchor, 1e-6) for p in points), (anchor, points))

    @given(cx=_coord, cy=_coord, w=_extent, h=_extent, r=_angle, signs=_signs,
           px=_coord, py=_coord)
    def test_dragged_handle_follows_the_pointer_on_its_axes(self, cx, cy, w, h, r, signs,
                                                            px, py):
        item = rect(cx, cy, w, h, r)
        anchor = geo.anchor_for(item, signs)
        new = {**item, **geo.resize(item, signs, anchor, (px, py))}
        # In the item's frame, the moved handle sits at the pointer on the axes
        # it controls (the other axis keeps its size).
        lp = geo.rot(px - anchor[0], py - anchor[1], -r)
        sx, sy = signs
        if sx:
            self.assertAlmostEqual(new["width"], abs(lp[0]), places=6)
        else:
            self.assertAlmostEqual(new["width"], w, places=6)
        if sy:
            self.assertAlmostEqual(new["height"], abs(lp[1]), places=6)
        else:
            self.assertAlmostEqual(new["height"], h, places=6)

    def test_keep_aspect_scales_both(self):
        item = rect(0, 0, 100, 50, 0, kind="image")
        anchor = geo.anchor_for(item, (1, 1))
        new = geo.resize(item, (1, 1), anchor, (150, 10))
        self.assertEqual((new["width"], new["height"]), (200.0, 35.0))
        new = geo.resize(item, (1, 1), anchor, (150, 10), keep_aspect=True)
        self.assertAlmostEqual(new["width"] / new["height"], 2.0)
        self.assertAlmostEqual(new["width"], 200.0)

    def test_angle_toward(self):
        self.assertAlmostEqual(geo.angle_toward((0, 0), (0, 10)), 0.0)
        self.assertAlmostEqual(geo.angle_toward((0, 0), (-10, 0)), 90.0)


class TestSnap(unittest.TestCase):
    @given(v=_coord, grid=hst.sampled_from([1.0, 5.0, 10.0, 20.0]))
    def test_snap_is_idempotent_and_on_grid(self, v, grid):
        s = geo.snap(v, grid)
        self.assertEqual(geo.snap(s, grid), s)
        self.assertAlmostEqual((s / grid) - round(s / grid), 0.0)
        self.assertLessEqual(abs(s - v), grid / 2 + 1e-9)

    @given(rx=_coord, ry=_coord, dx=_coord, dy=_coord)
    def test_snapped_move_puts_the_reference_on_the_grid(self, rx, ry, dx, dy):
        sdx, sdy = geo.snapped_delta((rx, ry), dx, dy, 10.0)
        self.assertAlmostEqual(((rx + sdx) / 10) - round((rx + sdx) / 10), 0.0, places=6)
        self.assertAlmostEqual(((ry + sdy) / 10) - round((ry + sdy) / 10), 0.0, places=6)

    def test_angle_snap(self):
        self.assertEqual(geo.snap_angle(22.0), 15.0)
        self.assertEqual(geo.snap_angle(359.0), 0.0)

    def test_zero_grid_is_free(self):
        self.assertEqual(geo.snap(3.3, 0.0), 3.3)

    def test_nearest_corner(self):
        box = (0.0, 0.0, 40.0, 20.0)
        self.assertEqual(geo.nearest_corner(box, (5, 3)), (0, 0))
        self.assertEqual(geo.nearest_corner(box, (35, 3)), (40, 0))
        self.assertEqual(geo.nearest_corner(box, (35, 17)), (40, 20))
        self.assertEqual(geo.nearest_corner(box, (5, 17)), (0, 20))
        # A tie takes the min side: a grab at the exact center → bottom-left.
        self.assertEqual(geo.nearest_corner(box, (20, 10)), (0, 0))
        # Outside the box still picks the nearest side.
        self.assertEqual(geo.nearest_corner(box, (99, -50)), (40, 0))


class TestHitAndBounds(unittest.TestCase):
    def test_rotated_rect_contains(self):
        item = rect(0, 0, 100, 10, 90)
        self.assertTrue(geo.contains(item, 0, 45))
        self.assertFalse(geo.contains(item, 45, 0))

    def test_thin_kinds_use_tolerance(self):
        line = {"kind": "line", "p1": (0, 0), "p2": (100, 0)}
        self.assertFalse(geo.contains(line, 50, 3))
        self.assertTrue(geo.contains(line, 50, 3, tol=5))
        point = {"kind": "point", "center": (10, 10)}
        self.assertTrue(geo.contains(point, 12, 10, tol=5))
        path = {"kind": "track", "points": ((0, 0), (10, 0), (10, 10)), "closed": False}
        self.assertFalse(geo.contains(path, 5, 5, tol=1))
        self.assertTrue(geo.contains({**path, "closed": True}, 5, 5, tol=1))

    def test_smooth_track_is_hit_on_its_curve(self):
        """A smooth track is hit where it is drawn — the curve Scena samples —
        not on the straight segments between its points."""
        straight = {"kind": "track", "points": ((0, 0), (100, 0), (100, 100), (0, 100)),
                    "closed": False, "smooth": 0.0}
        smooth = {**straight, "smooth": 1.0}
        curve = geo.track_curve(smooth)
        self.assertGreater(len(curve), len(smooth["points"]))
        for p in smooth["points"]:                      # it runs through its points
            self.assertTrue(any(math.dist(p, c) < 1e-6 for c in curve), p)
        # The sample farthest from the straight segments: off them, on the curve.
        far = max(curve, key=lambda c: min(geo._dist_to_segment(c, a, b) for a, b in
                                           zip(straight["points"], straight["points"][1:])))
        self.assertTrue(geo.contains(smooth, *far, tol=1))
        self.assertFalse(geo.contains(straight, *far, tol=1))
        # Bounds stay the points' box (LevelItem.center reads the same).
        self.assertEqual(geo.aabb(smooth), geo.aabb(straight))

    def test_regular_polygon_vertices_and_hit(self):
        hexagon = {"kind": "regular_polygon", "center": (0, 0), "radius": 10, "n": 6,
                   "angle": 0}
        v = geo.regular_vertices(hexagon)
        self.assertEqual(len(v), 6)
        self.assertAlmostEqual(v[0][0], 10)                  # vertex 0 toward angle
        self.assertAlmostEqual(v[1][1], 10 * math.sin(math.radians(60)))   # counter-clockwise
        self.assertTrue(geo.contains(hexagon, 0, 0))
        self.assertTrue(geo.contains(hexagon, 9.9, 0, tol=0.5))
        self.assertFalse(geo.contains(hexagon, 0, 9.5))      # past the flat top edge (8.66)
        x0, y0, x1, y1 = geo.aabb(hexagon)
        self.assertAlmostEqual(x1 - x0, 20)
        self.assertAlmostEqual(y1 - y0, 2 * 10 * math.sin(math.radians(60)))
        self.assertEqual(geo.translate(hexagon, 5, 1), {"center": (5, 1)})

    def test_polygon_inside_and_edge(self):
        poly = {"kind": "polygon", "points": ((0, 0), (10, 0), (5, 10))}
        self.assertTrue(geo.contains(poly, 5, 3))
        self.assertFalse(geo.contains(poly, 0, 9))

    def test_ellipse(self):
        e = rect(0, 0, 20, 10, 0, kind="ellipse")
        self.assertTrue(geo.contains(e, 9, 0))
        self.assertFalse(geo.contains(e, 9, 4))

    @given(cx=_coord, cy=_coord, w=_extent, h=_extent, r=_angle)
    def test_aabb_holds_every_corner(self, cx, cy, w, h, r):
        item = rect(cx, cy, w, h, r)
        x0, y0, x1, y1 = geo.aabb(item)
        for x, y in geo.corners(item):
            self.assertTrue(x0 - 1e-9 <= x <= x1 + 1e-9 and y0 - 1e-9 <= y <= y1 + 1e-9)

    def test_inside_box(self):
        item = rect(10, 10, 4, 4)
        self.assertTrue(geo.inside(item, (0, 0, 20, 20)))
        self.assertFalse(geo.inside(item, (9, 9, 20, 20)))


class TestHandles(unittest.TestCase):
    def test_counts_per_kind(self):
        self.assertEqual(len(geo.handles(rect(), 10)), 9)
        self.assertEqual(len(geo.handles(rect(kind="image"), 10)), 5)   # corners + rotate
        self.assertEqual(len(geo.handles({"kind": "circle", "center": (0, 0), "radius": 5}, 10)), 1)
        self.assertEqual(len(geo.handles({"kind": "line", "p1": (0, 0), "p2": (1, 1)}, 10)), 2)
        self.assertEqual(len(geo.handles({"kind": "point", "center": (0, 0)}, 10)), 0)

    def test_rotate_knob_is_above_the_top_edge(self):
        h = [x for x in geo.handles(rect(0, 0, 100, 40, 90), 10) if x.role == "rotate"][0]
        self.assertTrue(close((h.x, h.y), (-30, 0)))

    @given(r=_angle, signs=_signs)
    def test_resize_cursor_is_a_known_name(self, r, signs):
        self.assertIn(geo.resize_cursor(rect(r=r), signs), ("ew", "ns", "nesw", "nwse"))

    def test_resize_cursor_follows_rotation(self):
        self.assertEqual(geo.resize_cursor(rect(r=0), (1, 0)), "ew")
        self.assertEqual(geo.resize_cursor(rect(r=90), (1, 0)), "ns")


if __name__ == "__main__":
    unittest.main()
