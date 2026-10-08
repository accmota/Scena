"""Sign contract: magnitudes, scale recovery, and flip."""

import unittest

from scena import Circle, Line, Rect, Square
from tests.test_shapes import ShapeTestCase


class TestMagnitudes(ShapeTestCase):
    def test_negative_radius_raises_on_assign(self):
        c = Circle(center=(0, 0), radius=5)
        with self.assertRaises(ValueError):
            c.radius = -1

    def test_nan_radius_raises(self):
        with self.assertRaises(ValueError):
            Circle(center=(0, 0), radius=float("nan"))

    def test_zero_radius_is_legal(self):
        c = Circle(center=(0, 0), radius=0)
        self.assertEqual(float(c.radius), 0.0)
        self.assertTrue(c.is_collapsed)


class TestScaleRecovery(ShapeTestCase):
    def test_scale_to_zero_then_one_restores_circle(self):
        c = Circle(center=(0, 0), radius=10)
        c.scale_to(0)
        self.assertEqual(float(c.scale), 0.0)
        self.assertTrue(c.is_collapsed)
        c.scale_to(1)
        self.assertEqual(float(c.scale), 1.0)
        self.assertNumAlmost(c.radius, 10.0)

    def test_negative_scale_raises_with_hint(self):
        c = Circle(center=(0, 0), radius=4)
        with self.assertRaises(ValueError) as ctx:
            c.scale_by(-1)
        self.assertIn("flip_x", str(ctx.exception))


class TestFlip(ShapeTestCase):
    def test_line_flip_x_swaps_ends_and_twice_is_identity(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.flip_x = True
        self.assertPointAlmost(line.p1, 10, 0)
        self.assertPointAlmost(line.p2, 0, 0)
        line.flip_x = False
        self.assertPointAlmost(line.p1, 0, 0)
        self.assertPointAlmost(line.p2, 10, 0)

    def test_rect_flip_mirrors_named_points(self):
        r = Rect(center=(0, 0), width=20, height=10)
        r.flip_x = True
        self.assertGreaterEqual(float(r.width), 0.0)
        self.assertNumAlmost(r.center.x, 0.0)
        # A true mirror: top_left lands where top_right was (not a 180° turn).
        self.assertPointAlmost(r.top_left, 10, 5)
        self.assertPointAlmost(r.top_right, -10, 5)
        r.flip_x = False
        self.assertNumAlmost(r.angle, 0.0)
        self.assertPointAlmost(r.top_left, -10, 5)

    def test_square_flip_twice_is_identity(self):
        s = Square(center=(0, 0), length=12)
        x0, y0 = float(s.center.x), float(s.center.y)
        s.flip_y = True
        s.flip_y = False
        self.assertNumAlmost(s.center.x, x0)
        self.assertNumAlmost(s.center.y, y0)
        self.assertNumAlmost(s.length, 12.0)


if __name__ == "__main__":
    unittest.main()
