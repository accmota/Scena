"""
Triangle: isosceles, equilateral by default (``base_ratio``; 0.9.0).

Covers:
  - base_ratio = base / side; side = the two equal sides; radius = centroid → apex
  - base_ratio=1 is RegularPolygon(n=3), in every model
  - changing base_ratio keeps each model's inputs in place
  - validation (0 < base_ratio < 2), clamped links, n= / free corners refused
  - box= alone fills the box; with base_ratio it contains (the largest, centered)
  - flips, scale, clone, takein keep base_ratio
  - every outline consumer agrees with points[] (the bug class "a consumer
    still uses the regular n-gon formula"), and the bounds hold every vertex
  - caches: a base_ratio write alone redraws and re-collides
  - EquilateralTriangle is retired loudly (Scena Design, Compatibility)

Run:
    python tests/run_tiers.py focused test_triangle
"""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena  # noqa: E402
from scena import Box, Circle, Polygon, RegularPolygon, Triangle  # noqa: E402
from scena.shapes import RegularPolygonModel  # noqa: E402
from scena.state import Attribute  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def xy(p):
    return (float(p.x), float(p.y))


def verts(t):
    return [xy(p) for p in t.points]


def close(a, b, tol=1e-9):
    return all(math.isclose(x, y, rel_tol=0, abs_tol=tol) for x, y in zip(a, b))


def same_set(test, got, want, tol=1e-6):
    got = sorted((round(x, 5), round(y, 5)) for x, y in got)
    want = sorted((round(x, 5), round(y, 5)) for x, y in want)
    test.assertEqual(len(got), len(want))
    for g, w in zip(got, want):
        test.assertAlmostEqual(g[0], w[0], delta=tol * 10 + 1e-4)
        test.assertAlmostEqual(g[1], w[1], delta=tol * 10 + 1e-4)


def build(model, k, *, angle=0.0, pos=(0.0, 0.0), size=20.0):
    if model == "center_radius":
        return Triangle(center=pos, radius=size, angle=angle, base_ratio=k)
    if model == "center_side":
        return Triangle(center=pos, side=size, angle=angle, base_ratio=k)
    return Triangle(vertex=pos, side=size, angle=angle, base_ratio=k)


MODELS = ("center_radius", "center_side", "vertex_side")


class TestDefinition(unittest.TestCase):
    def test_side_forty_ratio_point_six(self):
        """The worked example of the design: legs 40, base 24."""
        t = Triangle(center=(0, 0), side=40, base_ratio=0.6)
        a, b, c = verts(t)
        self.assertAlmostEqual(math.dist(a, b), 40.0, places=9)
        self.assertAlmostEqual(math.dist(a, c), 40.0, places=9)
        self.assertAlmostEqual(math.dist(b, c), 24.0, places=9)
        height = math.sqrt(40.0 ** 2 - 12.0 ** 2)
        self.assertAlmostEqual(float(t.radius), 2.0 * height / 3.0, places=9)
        apex = math.degrees(2.0 * math.asin(0.3))
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - a[0], c[1] - a[1])
        got = math.degrees(math.acos((v1[0] * v2[0] + v1[1] * v2[1]) / 1600.0))
        self.assertAlmostEqual(got, apex, places=9)

    def test_center_is_the_centroid_and_apex_is_vertex_zero(self):
        t = Triangle(center=(5, -3), radius=12, angle=37, base_ratio=1.4)
        pts = verts(t)
        gx = sum(p[0] for p in pts) / 3.0
        gy = sum(p[1] for p in pts) / 3.0
        self.assertAlmostEqual(gx, 5.0, places=9)
        self.assertAlmostEqual(gy, -3.0, places=9)
        apex = pts[0]
        self.assertAlmostEqual(math.dist(apex, (5, -3)), 12.0, places=9)
        self.assertAlmostEqual(math.degrees(math.atan2(apex[1] + 3, apex[0] - 5)), 37.0, places=9)
        self.assertAlmostEqual(math.dist(apex, pts[1]), math.dist(apex, pts[2]), places=9)

    def test_ratio_one_is_the_regular_triangle_in_every_model(self):
        for kw in (dict(center=(1, 2), radius=10, angle=25),
                   dict(center=(1, 2), side=10, angle=25),
                   dict(vertex=(1, 2), side=10, angle=25)):
            t, r = Triangle(**kw), RegularPolygon(n=3, **kw)
            self.assertTrue(close([c for p in verts(t) for c in p],
                                  [c for p in verts(r) for c in p], 1e-12), kw)
            self.assertAlmostEqual(float(t.radius), float(r.radius), places=12)
            self.assertAlmostEqual(float(t.side), float(r.side), places=12)
            self.assertTrue(close(xy(t.center), xy(r.center), 1e-12))

    def test_not_a_regular_polygon(self):
        self.assertNotIsInstance(Triangle(), RegularPolygon)
        self.assertEqual(Triangle().model, RegularPolygonModel.CENTER_RADIUS)
        self.assertEqual(float(Triangle().base_ratio), 1.0)


class TestBaseRatioKeepsTheModelInputs(unittest.TestCase):
    def _apex_center_legs(self, t):
        pts = verts(t)
        return pts[0], xy(t.center), math.dist(pts[0], pts[1])

    def test_center_radius_keeps_center_and_apex(self):
        t = build("center_radius", 1.0, angle=20)
        apex0, c0, _ = self._apex_center_legs(t)
        t.base_ratio = 0.5
        apex1, c1, _ = self._apex_center_legs(t)
        self.assertTrue(close(apex0, apex1) and close(c0, c1))
        self.assertAlmostEqual(math.dist(verts(t)[1], verts(t)[2]), 0.5 * float(t.side), places=9)

    def test_center_side_keeps_center_and_legs(self):
        t = build("center_side", 1.0, angle=20)
        _, c0, legs0 = self._apex_center_legs(t)
        t.base_ratio = 1.7
        _, c1, legs1 = self._apex_center_legs(t)
        self.assertTrue(close(c0, c1))
        self.assertAlmostEqual(legs0, legs1, places=9)

    def test_vertex_side_keeps_apex_and_legs(self):
        t = build("vertex_side", 1.0, angle=20, pos=(7, 8))
        apex0, _, legs0 = self._apex_center_legs(t)
        t.base_ratio = 0.3
        apex1, _, legs1 = self._apex_center_legs(t)
        self.assertTrue(close(apex0, apex1) and close(apex1, (7, 8)))
        self.assertAlmostEqual(legs0, legs1, places=9)

    def test_derived_side_and_radius_follow_a_ratio_write(self):
        t = build("center_radius", 1.0, size=10)
        s0 = float(t.side)                      # read: the Derivate goes live
        t.base_ratio = 0.6
        self.assertNotAlmostEqual(float(t.side), s0)
        self.assertAlmostEqual(float(t.side), math.dist(verts(t)[0], verts(t)[1]), places=9)
        u = build("center_side", 1.0, size=10)
        r0 = float(u.radius)
        u.base_ratio = 1.5
        self.assertNotAlmostEqual(float(u.radius), r0)
        self.assertAlmostEqual(float(u.radius), math.dist(verts(u)[0], xy(u.center)), places=9)

    def test_a_constructor_formula_links(self):
        dial = Attribute(0.5)
        t = Triangle(center=(0, 0), side=30, base_ratio=lambda: dial.value)
        self.assertAlmostEqual(math.dist(verts(t)[1], verts(t)[2]), 15.0, places=9)
        dial.value = 1.5
        self.assertAlmostEqual(math.dist(verts(t)[1], verts(t)[2]), 45.0, places=9)

    def test_a_linked_ratio_follows_its_source(self):
        dial = Attribute(1.0)
        t = build("center_side", 1.0, size=30)
        t["base_ratio"] @= dial
        dial.value = 0.5
        pts = verts(t)
        self.assertAlmostEqual(math.dist(pts[1], pts[2]), 15.0, places=9)


class TestValidation(unittest.TestCase):
    def test_out_of_range_and_non_numbers_raise(self):
        for bad in (0, 0.0, -1, 2, 2.0, 3, float("nan"), float("inf")):
            with self.assertRaises(ValueError, msg=repr(bad)):
                Triangle(base_ratio=bad)
            t = Triangle()
            with self.assertRaises(ValueError, msg=repr(bad)):
                t.base_ratio = bad
            self.assertEqual(float(t.base_ratio), 1.0)
        for bad in (True, "a", None):
            with self.assertRaises(TypeError, msg=repr(bad)):
                Triangle(base_ratio=bad)

    def test_the_limit_message_explains_the_two(self):
        with self.assertRaises(ValueError) as cm:
            Triangle(base_ratio=2)
        self.assertIn("< 2", str(cm.exception))

    def test_a_link_past_the_range_is_clamped_not_raised(self):
        dial = Attribute(1.0)
        t = build("center_radius", 1.0)
        t["base_ratio"] @= dial
        for v in (5.0, 2.0, -3.0, 0.0):
            dial.value = v
            k = float(t.base_ratio)
            self.assertTrue(0.0 <= k < 2.0, (v, k))
            for x, y in verts(t):
                self.assertTrue(math.isfinite(x) and math.isfinite(y), (v, x, y))

    def test_n_and_free_corners_are_refused_with_the_fix(self):
        with self.assertRaises(TypeError) as cm:
            Triangle(n=3, center=(0, 0), radius=5)
        self.assertIn("RegularPolygon(n=", str(cm.exception))
        for kw in (dict(points=[(0, 0), (1, 0), (0, 1)]), dict(p1=(0, 0))):
            with self.assertRaises(TypeError) as cm:
                Triangle(**kw)
            self.assertIn("Polygon(points=", str(cm.exception))

    def test_class_default(self):
        class Nave(Triangle, base_ratio=0.6):
            pass
        n = Nave(center=(0, 0), radius=10)
        self.assertAlmostEqual(float(n.base_ratio), 0.6)
        self.assertAlmostEqual(float(Nave(base_ratio=1.2).base_ratio), 1.2)

    def test_other_kinds_refuse_the_word(self):
        from scena import Circle
        with self.assertRaises(AttributeError) as cm:
            Circle().base_ratio = 0.5
        self.assertIn("Triangle", str(cm.exception))


def box_extent(t, box_center, angle):
    """``(x0, x1, y0, y1)`` of the vertices in a box's own frame."""
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    loc = [((x - box_center[0]) * c + (y - box_center[1]) * s,
            -(x - box_center[0]) * s + (y - box_center[1]) * c) for x, y in verts(t)]
    xs = [p[0] for p in loc]
    ys = [p[1] for p in loc]
    return min(xs), max(xs), min(ys), max(ys)


class TestBox(unittest.TestCase):
    """box= with base_ratio contains, like a Sprite: the largest triangle of
    that ratio, its outline centered, the apex along the box's +x. box=
    alone fills, like an Ellipse: base = the box's height, apex on the far
    side, base_ratio from the box. Centering the centroid (a regular
    polygon's inscribe) left the apex on one side and a gap on the other;
    contain alone left a gap on one axis."""

    BOXES = ((80, 60, 0.0), (150, 190, 0.0), (230, 110, 15.0), (60, 200, 90.0), (90, 90, -40.0))

    def test_alone_fills_the_box(self):
        for w, h, ang in self.BOXES:
            with self.subTest(w=w, h=h, angle=ang):
                t = Triangle(box=Box(center=(100, 50), width=w, height=h, angle=ang))
                self.assertAlmostEqual(float(t.angle), ang)
                x0, x1, y0, y1 = box_extent(t, (100, 50), ang)
                for got, want in ((x0, -w / 2), (x1, w / 2), (y0, -h / 2), (y1, h / 2)):
                    self.assertAlmostEqual(got, want, places=9)
                self.assertAlmostEqual(float(t.base_ratio), h / math.hypot(w, h / 2))
                # the apex is the middle of the far side
                a = math.radians(ang)
                self.assertTrue(close(verts(t)[0], (100 + w / 2 * math.cos(a), 50 + w / 2 * math.sin(a))))

    def test_a_class_default_ratio_is_kept(self):
        class Nave(Triangle, base_ratio=0.6):
            pass
        t = Nave(box=Box(center=(0, 0), width=150, height=190))
        self.assertAlmostEqual(float(t.base_ratio), 0.6)
        x0, x1, y0, y1 = box_extent(t, (0, 0), 0.0)
        self.assertAlmostEqual(x0 + x1, 0.0, places=9)
        self.assertAlmostEqual(x1, 75.0)

    def test_a_box_with_no_width_stays_valid(self):
        for w in (0.0, 1e-12):
            t = Triangle(box=Box(center=(0, 0), width=w, height=50))
            self.assertLess(float(t.base_ratio), 2.0)

    def test_fits_inside_centered_and_keeps_the_ratio(self):
        for w, h, ang in self.BOXES:
            box = Box(center=(100, 50), width=w, height=h, angle=ang)
            for k in (0.3, 0.6, 1.0, 1.4, 1.8):
                with self.subTest(w=w, h=h, angle=ang, k=k):
                    t = Triangle(box=box, base_ratio=k)
                    self.assertAlmostEqual(float(t.base_ratio), k)
                    self.assertAlmostEqual(float(t.angle), ang)
                    x0, x1, y0, y1 = box_extent(t, (100, 50), ang)
                    self.assertAlmostEqual(x0 + x1, 0.0, places=9)   # centered
                    self.assertAlmostEqual(y0 + y1, 0.0, places=9)
                    self.assertLessEqual(x1, w / 2 + 1e-9)            # inside
                    self.assertLessEqual(y1, h / 2 + 1e-9)
                    # the largest: it touches the box on one axis
                    self.assertTrue(math.isclose(x1, w / 2) or math.isclose(y1, h / 2))

    def test_apex_points_along_the_box_width(self):
        t = Triangle(box=Box(center=(0, 0), width=150, height=190), base_ratio=1.0)
        apex = verts(t)[0]
        self.assertAlmostEqual(apex[0], 75.0)
        self.assertAlmostEqual(apex[1], 0.0)

    def test_an_explicit_size_only_centers_the_centroid(self):
        box = Box(center=(100, 50), width=150, height=190, angle=20)
        for size in ({"radius": 30}, {"side": 40}):
            t = Triangle(box=box, base_ratio=0.6, **size)
            self.assertTrue(close(xy(t.center), (100, 50)), size)

    def test_a_linked_ratio_fits_as_equilateral(self):
        box = Box(center=(0, 0), width=150, height=190)
        src = Circle(center=(0, 0), radius=1.0)
        t = Triangle(box=box, base_ratio=lambda: src.radius)
        x0, x1, y0, y1 = box_extent(t, (0, 0), 0.0)
        self.assertAlmostEqual(x0 + x1, 0.0, places=9)
        self.assertAlmostEqual(x1, 75.0)

    def test_a_zero_box_gives_an_invisible_triangle(self):
        t = Triangle(box=Box(center=(10, 20), width=0, height=50))
        self.assertEqual(float(t.radius), 0.0)

    def test_takes_the_box_angle_on_a_subclass_too(self):
        class Seta(Triangle):
            pass
        box = Box(center=(0, 0), width=40, height=40, angle=30)
        self.assertAlmostEqual(float(Seta(box=box).angle), 30.0)
        self.assertAlmostEqual(float(Triangle(box=box).angle), 30.0)


class TestTransformsKeepTheRatio(unittest.TestCase):
    def test_flip_mirrors_keeps_center_and_twice_is_identity(self):
        for model in MODELS:
            for axis in ("x", "y"):
                t = build(model, 0.6, angle=33, pos=(4, -2))
                before = verts(t)
                cx, cy = t._center_xy()
                setattr(t, f"flip_{axis}", True)
                mirrored = [((2 * cx - x, y) if axis == "x" else (x, 2 * cy - y)) for x, y in before]
                for k in range(3):   # vertex[k] lands on the mirror of the old vertex[k]
                    self.assertTrue(close(verts(t)[k], mirrored[k], 1e-9), (model, axis, k))
                self.assertTrue(close(t._center_xy(), (cx, cy), 1e-9))
                setattr(t, f"flip_{axis}", False)
                for a, b in zip(verts(t), before):
                    self.assertTrue(close(a, b, 1e-9), (model, axis))
                self.assertAlmostEqual(float(t.base_ratio), 0.6)

    def test_scale_rotate_move_keep_the_shape(self):
        t = build("center_side", 0.6, size=40)
        t.scale_by(2)
        t.rotate_by(45)
        t.move_by(10, 5)
        pts = verts(t)
        self.assertAlmostEqual(math.dist(pts[0], pts[1]), 80.0, places=9)
        self.assertAlmostEqual(math.dist(pts[1], pts[2]), 48.0, places=9)
        self.assertAlmostEqual(float(t.base_ratio), 0.6)

    def test_clone_and_takein_carry_the_ratio(self):
        t = build("vertex_side", 1.3, angle=12)
        t.flip_x = True
        c = t.clone()
        self.assertIsInstance(c, Triangle)
        self.assertAlmostEqual(float(c.base_ratio), 1.3)
        for a, b in zip(verts(c), verts(t)):
            self.assertTrue(close(a, b, 1e-9))
        u = Triangle(center=(50, 50), radius=3)
        u << t
        self.assertAlmostEqual(float(u.base_ratio), 1.3)
        for a, b in zip(verts(u), verts(t)):
            self.assertTrue(close(a, b, 1e-9))

    def test_face_motion_flies_apex_first(self):
        t = build("center_radius", 0.5)
        t.move_by(30, 30, face=True)
        cx, cy = t._center_xy()
        apex = verts(t)[0]
        self.assertAlmostEqual(math.degrees(math.atan2(apex[1] - cy, apex[0] - cx)), 45.0, places=5)


def _consumer_outlines(t):
    """Every engine reader of a Triangle's outline, as world vertex sets."""
    from scena import geom
    from scena.collision import snapshot_shape
    from scena.track import shape_outline
    out = {}
    out["points"] = verts(t)
    out["geom"] = geom._outline_verts(t)
    prims = snapshot_shape(t)
    out["collision"] = [v for p in prims for v in (p.verts or ())]
    out["track"] = shape_outline(t)[0][:3]
    cx, cy, r, phi0 = t._placement_params()
    a = math.radians(phi0)
    c, s = math.cos(a), math.sin(a)
    out["draw"] = [(cx + x * c - y * s, cy + x * s + y * c) for x, y in t._local_verts(r)]
    return out


class TestEveryConsumerAgrees(unittest.TestCase):
    """A Triangle is not a regular n-gon: any reader with its own n-gon formula
    (collision hull, geom, Track, draw, culling) disagrees once base_ratio != 1."""

    def test_random_triangles(self):
        rng = random.Random(1709)
        for _ in range(60):
            model = rng.choice(MODELS)
            k = rng.uniform(0.05, 1.95)
            t = build(model, k, angle=rng.uniform(-180, 180),
                      pos=(rng.uniform(-50, 50), rng.uniform(-50, 50)),
                      size=rng.uniform(2, 60))
            if rng.random() < 0.5:
                t.flip_x = True
            outs = _consumer_outlines(t)
            want = outs.pop("points")
            for name, got in outs.items():
                with self.subTest(model=model, k=k, consumer=name):
                    same_set(self, got, want)
            # hit test: inside at the centroid, outside just past each vertex
            cx, cy = t._center_xy()
            self.assertTrue(t._hit_test_xy(cx, cy))
            for x, y in want:
                self.assertFalse(t._hit_test_xy(cx + 1.05 * (x - cx), cy + 1.05 * (y - cy)))
            from scena.canvas import _approx_draw_aabb
            from scena.collision import _proxy_aabb_for_shape
            for name, box in (("canvas", _approx_draw_aabb(t)), ("broad-phase", _proxy_aabb_for_shape(t))):
                x0, y0, x1, y1 = box
                for x, y in want:
                    with self.subTest(model=model, k=k, bounds=name):
                        self.assertTrue(x0 - 1e-6 <= x <= x1 + 1e-6 and y0 - 1e-6 <= y <= y1 + 1e-6)

    def test_geom_queries_see_the_real_outline(self):
        t = Triangle(center=(0, 0), side=40, base_ratio=0.25, angle=90)
        # Base half-width is 5: a point 8 units off the axis at the base is outside.
        base_y = verts(t)[1][1]
        q = scena.closest_point(t, (8.0, base_y))
        self.assertAlmostEqual(q[0], 5.0, places=6)


class TestCaches(unittest.TestCase):
    def test_a_ratio_write_alone_rebuilds_the_drawn_path(self):
        import skia
        t = build("center_radius", 1.0)
        surface = skia.Surface(64, 64)
        t._geometry_draw(surface.getCanvas())
        key0 = t._geom_path_key
        t.base_ratio = 0.4
        t._geometry_draw(surface.getCanvas())
        self.assertNotEqual(t._geom_path_key, key0)
        pts = [(p.x(), p.y()) for p in t._geom_path.getPoints(t._geom_path.countPoints())]
        same_set(self, pts, t._local_verts(t._placement_params()[2]))

    def test_a_ratio_write_alone_rebuilds_the_collision_hull(self):
        from scena.collision import snapshot_shape
        t = build("center_radius", 1.0, pos=(300, 300))
        t.collidable = True
        owner = t._collider
        snapshot_shape(t, cache_owner=owner)
        t.base_ratio = 0.4
        got = [v for p in snapshot_shape(t, cache_owner=owner) for v in (p.verts or ())]
        same_set(self, got, verts(t))
        t.move_by(25, -10)     # the translate fast path must not slide the old hull
        got = [v for p in snapshot_shape(t, cache_owner=owner) for v in (p.verts or ())]
        same_set(self, got, verts(t))
        t.collidable = False


class TestRetiredName(unittest.TestCase):
    def test_import_works_and_use_raises_with_the_fix(self):
        ns = {}
        exec("from scena import EquilateralTriangle", ns)
        old = ns["EquilateralTriangle"]
        self.assertIs(old, scena.EquilateralTriangle)
        with self.assertRaises(TypeError) as cm:
            old(center=(0, 0), radius=5)
        self.assertIn("Triangle(", str(cm.exception))
        self.assertIn("0.9.0", str(cm.exception))
        with self.assertRaises(TypeError) as cm:
            class Nave(old):
                pass
        self.assertIn("class Nave(Triangle)", str(cm.exception))

    def test_not_api_and_star_import_does_not_bring_it(self):
        import builtins
        self.assertNotIn("EquilateralTriangle", scena.__all__)
        self.assertIn("Triangle", scena.__all__)
        ns = {}
        exec("from scena import *", ns)
        self.assertNotIn("EquilateralTriangle", ns)
        self.assertFalse(hasattr(builtins, "EquilateralTriangle"))
        with self.assertRaises(NameError):
            exec("EquilateralTriangle(center=(0, 0), radius=5)", ns)
        with self.assertRaises(AttributeError):
            scena.NoSuchName  # noqa: B018 — module __getattr__ keeps the default


if __name__ == "__main__":
    unittest.main()
