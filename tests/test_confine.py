"""Graphic.confine — clamp / bounce / wrap against a Box (any angle).

Run headless:

    python -m unittest tests.test_confine -v
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Box, Circle, Line, Rect, Vec2, canvas, init
from scena.confine import _confine_point, _effective_half_extents, _projected_half


class ConfineTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        self._owned = []

    def tearDown(self):
        for s in list(self._owned):
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestClampCenter(ConfineTestCase):
    def test_galaga_style_horizontal_clamp(self):
        # Hand-written pattern from a Galaga game: keep center.x in [40, W-40]
        ship = self.track(Circle(center=(10, 70), radius=20))
        play = Box(center=(500, 400), width=920, height=800)  # inset(40) of 1000×800
        sides = ship.confine(play)
        self.assertAlmostEqual(float(ship.center.x), 40.0)
        self.assertAlmostEqual(float(ship.center.y), 70.0)
        self.assertEqual(sides, frozenset({"left"}))

        ship.center = (990, 70)
        sides = ship.confine(play)
        self.assertAlmostEqual(float(ship.center.x), 960.0)
        self.assertEqual(sides, frozenset({"right"}))

    def test_noop_when_inside(self):
        c = self.track(Circle(center=(400, 300), radius=10))
        box = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(box)
        self.assertEqual(sides, frozenset())
        self.assertAlmostEqual(float(c.center.x), 400.0)
        self.assertAlmostEqual(float(c.center.y), 300.0)

    def test_defaults_are_center_clamp(self):
        c = self.track(Circle(center=(0, 300), radius=5))
        box = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(box)
        self.assertAlmostEqual(float(c.center.x), 300.0)
        self.assertEqual(sides, frozenset({"left"}))


class TestByBox(ConfineTestCase):
    def test_keeps_own_frame_inside(self):
        # Circle radius 20 → box is 40×40; region 200×100 → effective ±80 x, ±30 y
        c = self.track(Circle(center=(500, 300), radius=20))
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, by="box")
        # center at 500: local x = 100; effective hw = 100-20 = 80 → clamp to 480
        self.assertAlmostEqual(float(c.center.x), 480.0)
        self.assertAlmostEqual(float(c.center.y), 300.0)
        self.assertEqual(sides, frozenset({"right"}))

    def test_too_big_pins_to_region_center(self):
        # Object wider than region → remainder half-extent 0 → pin on that axis
        c = self.track(Circle(center=(100, 300), radius=80))  # diameter 160
        region = Box(center=(400, 300), width=100, height=200)  # width 100 < 160
        sides = c.confine(region, by="box")
        self.assertAlmostEqual(float(c.center.x), 400.0)
        self.assertAlmostEqual(float(c.center.y), 300.0)
        self.assertIn("left", sides)

    def test_line_raises_same_as_graphic_box(self):
        line = self.track(Line(p1=(0, 0), p2=(100, 0)))
        region = Box(center=(50, 0), width=200, height=100)
        with self.assertRaises(TypeError) as cm:
            line.confine(region, by="box")
        self.assertIn("unsupported", str(cm.exception))
        with self.assertRaises(TypeError) as cm2:
            _ = line.box
        self.assertIn("unsupported", str(cm2.exception))


class TestByOverlap(ConfineTestCase):
    def test_allows_hanging_out(self):
        # Circle r=20 at x=490, region right edge 500 → still overlaps (span 470..510)
        c = self.track(Circle(center=(490, 300), radius=20))
        region = Box(center=(400, 300), width=200, height=100)  # right=500
        sides = c.confine(region, by="overlap")
        self.assertEqual(sides, frozenset())
        self.assertAlmostEqual(float(c.center.x), 490.0)

    def test_acts_only_when_fully_outside(self):
        # center at 521 → circle spans 501..541, fully past right=500
        # effective right for overlap = 500+20 = 520; center 521 → clamp to 520
        c = self.track(Circle(center=(521, 300), radius=20))
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, by="overlap")
        self.assertAlmostEqual(float(c.center.x), 520.0)
        self.assertEqual(sides, frozenset({"right"}))

    def test_touching_one_pixel_of_overlap_is_noop(self):
        # center at 520 → circle left edge exactly at 500 (touching)
        c = self.track(Circle(center=(520, 300), radius=20))
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, by="overlap")
        self.assertEqual(sides, frozenset())
        self.assertAlmostEqual(float(c.center.x), 520.0)


class TestWrap(ConfineTestCase):
    def test_carries_overshoot(self):
        c = self.track(Circle(center=(515, 300), radius=5))
        region = Box(center=(400, 300), width=200, height=100)  # right=500, left=300
        # overshoot past right by 15 → appear 15 past left → 315
        sides = c.confine(region, action="wrap")
        self.assertAlmostEqual(float(c.center.x), 315.0)
        self.assertEqual(sides, frozenset({"right"}))

    def test_wrap_from_left(self):
        c = self.track(Circle(center=(285, 300), radius=5))
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, action="wrap")
        self.assertAlmostEqual(float(c.center.x), 485.0)
        self.assertEqual(sides, frozenset({"left"}))


class TestBounce(ConfineTestCase):
    def test_flips_vel_axis_aligned(self):
        c = self.track(Circle(center=(510, 300), radius=5))
        c.vel = Vec2(100, 40)
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, action="bounce")
        self.assertAlmostEqual(float(c.center.x), 500.0)
        self.assertEqual(sides, frozenset({"right"}))
        self.assertAlmostEqual(float(c.vel.x), -100.0)
        self.assertAlmostEqual(float(c.vel.y), 40.0)

    def test_requires_vel(self):
        c = self.track(Circle(center=(510, 300), radius=5))
        region = Box(center=(400, 300), width=200, height=100)
        with self.assertRaises(TypeError) as cm:
            c.confine(region, action="bounce")
        self.assertIn("vel", str(cm.exception))

    def test_bounce_on_rotated_region_reflects_local_axis(self):
        # Region rotated 90°: local +x is world +y. Hit "right" in local → flip local vx.
        c = self.track(Circle(center=(400, 510), radius=5))
        c.vel = Vec2(0, 100)  # moving +world y = +local x for 90° region
        region = Box(center=(400, 300), width=200, height=100, angle=90)
        # After 90°: local width 200 is along world y; local height 100 along -world x
        # Region center 400,300; local +x (along width) maps to world +y.
        # World (400, 510) → local x = 210, hw=100 → clamp local x to 100 → world y=400
        sides = c.confine(region, action="bounce")
        self.assertIn("right", sides)
        self.assertAlmostEqual(float(c.center.x), 400.0, places=5)
        self.assertAlmostEqual(float(c.center.y), 400.0, places=5)
        # Local vx was +100 (world +y), flipped to -100 → world vel (0, -100)
        self.assertAlmostEqual(float(c.vel.x), 0.0, places=5)
        self.assertAlmostEqual(float(c.vel.y), -100.0, places=5)


class TestRotatedRegion(ConfineTestCase):
    def test_center_clamp_30_deg(self):
        region = Box(center=(400, 300), width=200, height=100, angle=30)
        # Point far along region's local +x
        rad = math.radians(30)
        far = 200.0
        wx = 400 + far * math.cos(rad)
        wy = 300 + far * math.sin(rad)
        c = self.track(Circle(center=(wx, wy), radius=5))
        sides = c.confine(region)
        self.assertEqual(sides, frozenset({"right"}))
        # Should land at local x = 100
        nx, ny = float(c.center.x), float(c.center.y)
        expect_x = 400 + 100 * math.cos(rad)
        expect_y = 300 + 100 * math.sin(rad)
        self.assertAlmostEqual(nx, expect_x, places=5)
        self.assertAlmostEqual(ny, expect_y, places=5)

    def test_by_box_on_rotated_region(self):
        region = Box(center=(400, 300), width=200, height=100, angle=0)
        c = self.track(Rect(center=(480, 300), width=40, height=20))
        sides = c.confine(region, by="box")
        # hw_eff = 100 - 20 = 80 → clamp to 480 is exactly on edge → noop if already 480
        self.assertEqual(sides, frozenset())
        c.center = (490, 300)
        sides = c.confine(region, by="box")
        self.assertAlmostEqual(float(c.center.x), 480.0)
        self.assertEqual(sides, frozenset({"right"}))


class TestErrorsAndDegenerate(ConfineTestCase):
    def test_unknown_by(self):
        c = self.track(Circle(center=(400, 300), radius=5))
        region = Box(center=(400, 300), width=100, height=100)
        with self.assertRaises(TypeError):
            c.confine(region, by="silhouette")

    def test_unknown_action(self):
        c = self.track(Circle(center=(400, 300), radius=5))
        region = Box(center=(400, 300), width=100, height=100)
        with self.assertRaises(TypeError):
            c.confine(region, action="destroy")

    def test_degenerate_region_from_inset_remainder(self):
        # inset past size → point remainder; clamp pins to center, no crash
        region = Box(center=(400, 300), width=20, height=20).inset(12)  # 0×0
        c = self.track(Circle(center=(450, 350), radius=5))
        sides = c.confine(region)
        self.assertAlmostEqual(float(c.center.x), 400.0)
        self.assertAlmostEqual(float(c.center.y), 300.0)
        self.assertTrue(sides)  # corrected somehow

    def test_region_accepts_rect_graphic(self):
        wall = self.track(Rect(center=(400, 300), width=200, height=100))
        c = self.track(Circle(center=(600, 300), radius=5))
        sides = c.confine(wall)
        self.assertAlmostEqual(float(c.center.x), 500.0)
        self.assertEqual(sides, frozenset({"right"}))


class TestPureHelpers(unittest.TestCase):
    def test_projected_half_axis_aligned(self):
        pw, ph = _projected_half(20, 10, 0, 0)
        self.assertAlmostEqual(pw, 20.0)
        self.assertAlmostEqual(ph, 10.0)

    def test_projected_half_90_swaps(self):
        pw, ph = _projected_half(20, 10, 90, 0)
        self.assertAlmostEqual(pw, 10.0)
        self.assertAlmostEqual(ph, 20.0)

    def test_effective_center_unchanged(self):
        hw, hh = _effective_half_extents(200, 100, "center", None, 0)
        self.assertAlmostEqual(hw, 100.0)
        self.assertAlmostEqual(hh, 50.0)

    def test_confine_point_clamp(self):
        nx, ny, sides, vel = _confine_point(
            600, 300, 400, 300, 100, 50, 0, "clamp",
        )
        self.assertAlmostEqual(nx, 500.0)
        self.assertEqual(sides, frozenset({"right"}))
        self.assertIsNone(vel)


if __name__ == "__main__":
    unittest.main()
