"""Free ``lerp`` and multi-value ``tween`` (Attribute / ink / Color / Vec2 / Point).

Run:

    python -m unittest tests.test_lerp -v
"""

import os
import sys
import unittest
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    Circle, Color, ColorSpace, Point, Vec2, lerp, tween, clock,
)
from scena.process import reset_process_scheduler, tick_processes
from scena.state import Attribute
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


class TestLerpScalars(unittest.TestCase):
    def test_number_midpoint(self):
        self.assertEqual(lerp(0, 100, 0.5), 50.0)

    def test_number_overshoot(self):
        self.assertAlmostEqual(lerp(0, 10, 1.5), 15.0)

    def test_number_vs_str_raises(self):
        with self.assertRaises(TypeError):
            lerp(0, "red", 0.5)

    def test_bool_is_not_a_number(self):
        with self.assertRaises(TypeError):
            lerp(True, False, 0.5)


class TestLerpSequences(unittest.TestCase):
    def test_tuple_xy(self):
        self.assertEqual(lerp((0, 0), (100, 40), 0.25), (25.0, 10.0))

    def test_list_rebuilds_list(self):
        out = lerp([0, 10], [10, 0], 0.5)
        self.assertIsInstance(out, list)
        self.assertEqual(out, [5.0, 5.0])

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            lerp((0, 1), (0, 1, 2), 0.5)

    def test_namedtuple_rebuild(self):
        XY = namedtuple("XY", "x y")
        mid = lerp(XY(0, 0), XY(10, 20), 0.5)
        self.assertIsInstance(mid, XY)
        self.assertEqual(mid, XY(5.0, 10.0))


class TestLerpVec2ColorPoint(unittest.TestCase):
    def test_tuple_with_a_vector_or_point_is_two_points(self):
        # Showcase B3: lerp((0, 0), Vec2(10, 10), 0.5) said "both sides must
        # be sequences of the same length" (both are 2D points). Every
        # mix of the point spellings lerps, the tuple side keeping its kind.
        p = Circle(center=(10, 20), radius=2).center
        for a, b in (((0, 0), Vec2.temp(10, 20)), ([0, 0], Vec2.temp(10, 20)), ((0, 0), p)):
            with self.subTest(a=type(a).__name__, b=type(b).__name__):
                mid = lerp(a, b, 0.5)
                self.assertIs(type(mid), type(a))
                self.assertEqual([float(v) for v in mid], [5.0, 10.0])
        with self.assertRaises(TypeError):
            lerp((0, 0, 0), Vec2.temp(1, 1), 0.5)

    def test_vec2(self):
        a = Vec2.temp(0, 0)
        b = Vec2.temp(10, 20)
        mid = lerp(a, b, 0.5)
        self.assertAlmostEqual(float(mid.x), 5.0)
        self.assertAlmostEqual(float(mid.y), 10.0)

    def test_vec2_overshoot_not_clamped(self):
        a = Vec2.temp(0, 0)
        b = Vec2.temp(10, 0)
        out = a.lerp(b, 1.5)
        self.assertAlmostEqual(float(out.x), 15.0)

    def test_color_default_oklab(self):
        a = Color("red")
        b = Color("blue")
        mid = lerp(a, b, 0.5)
        self.assertIsInstance(mid, Color)
        # OKLAB mid red→blue is not the muddy RGB gray (0.5, 0, 0.5).
        rgb_mid = Color.interpolate(a, b, 0.5, ColorSpace.RGB)
        self.assertFalse(
            abs(mid._r - rgb_mid._r) < 1e-6
            and abs(mid._g - rgb_mid._g) < 1e-6
            and abs(mid._b - rgb_mid._b) < 1e-6
        )

    def test_color_interpolate_default_is_oklab(self):
        a = Color(1, 0, 0)
        b = Color(0, 0, 1)
        default = Color.interpolate(a, b, 0.5)
        oklab = Color.interpolate(a, b, 0.5, ColorSpace.OKLAB)
        self.assertAlmostEqual(default._r, oklab._r, places=5)
        self.assertAlmostEqual(default._g, oklab._g, places=5)
        self.assertAlmostEqual(default._b, oklab._b, places=5)

    def test_color_lerp_rejects_str(self):
        with self.assertRaises(TypeError):
            Color("red").lerp("blue", 0.5)

    def test_point_returns_tuple_not_point(self):
        p = Point(0, 0)
        q = Point(100, 40)
        mid = lerp(p, q, 0.25)
        self.assertIsInstance(mid, tuple)
        self.assertNotIsInstance(mid, Point)
        self.assertAlmostEqual(mid[0], 25.0)
        self.assertAlmostEqual(mid[1], 10.0)
        p.destroy()
        q.destroy()

    def test_point_vs_xy_tuple(self):
        p = Point(0, 0)
        mid = lerp(p, (100, 0), 0.5)
        self.assertEqual(mid, (50.0, 0.0))
        p.destroy()


class TestTweenMultiDim(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        clock._frame = 0
        self._owned = []

    def tearDown(self):
        for obj in self._owned:
            try:
                if getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_process_scheduler()

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def test_tween_scalar_still_works(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        tween(c["radius"], 20, time=0.2)
        _frame(0.2)
        self.assertAlmostEqual(float(c.radius), 20.0, places=4)

    def test_tween_color_ink(self):
        e = self.track(Circle(center=(0, 0), radius=8))
        e.tint = Color("red")
        tween(e["tint"], Color("blue"), time=0.2)
        _frame(0.1)
        mid = e.tint
        self.assertIsInstance(mid, Color)
        self.assertNotEqual(mid.rgb[:3], (1.0, 0.0, 0.0))
        _frame(0.1)
        end = e.tint
        self.assertAlmostEqual(end._r, 0.0, places=3)
        self.assertAlmostEqual(end._b, 1.0, places=3)

    def test_tween_tuple_ink(self):
        e = self.track(Circle(center=(0, 0), radius=8))
        e.pad = (0.0, 0.0)
        tween(e["pad"], (100.0, 40.0), time=0.2)
        _frame(0.1)
        self.assertAlmostEqual(e.pad[0], 50.0, places=3)
        self.assertAlmostEqual(e.pad[1], 20.0, places=3)

    def test_tween_vec2_attribute(self):
        attr = Attribute(Vec2.temp(0, 0))
        tween(attr, Vec2.temp(10, 0), time=0.2)
        _frame(0.1)
        mid = attr.value
        self.assertAlmostEqual(float(mid.x), 5.0, places=3)
        _frame(0.1)
        self.assertAlmostEqual(float(attr.value.x), 10.0, places=3)

    def test_tween_type_mismatch_raises_immediately(self):
        e = self.track(Circle(center=(0, 0), radius=8))
        e.tint = Color("red")
        with self.assertRaises(TypeError):
            tween(e["tint"], "blue", time=0.2)

    def test_tween_length_mismatch_raises_immediately(self):
        e = self.track(Circle(center=(0, 0), radius=8))
        e.pad = (0.0, 0.0)
        with self.assertRaises(ValueError):
            tween(e["pad"], (1.0, 2.0, 3.0), time=0.2)

    def test_tween_pose_unchanged(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        tween(c.center, (100, 40), time=0.2)
        _frame(0.2)
        self.assertAlmostEqual(float(c.center.x), 100.0, places=3)
        self.assertAlmostEqual(float(c.center.y), 40.0, places=3)


if __name__ == "__main__":
    unittest.main()
