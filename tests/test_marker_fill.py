"""A Point's marker paint is shared by value and isolated by write.

Rule under test (Sprite Design.md, "Construction cost", C4a): every Graphic's
center Point paints its marker at construction. The faded marker Color is
built once per (color, alpha) and shared, which is safe because a Color is a
value (immutable). Each Point then holds exactly what ``fill = Color(color)``
and ``set_alpha(alpha)`` gave it, and a paint write on one Point (``set_color``,
``set_alpha``, ``fill =``) gives that Point a new material and leaves every
other Point as it was.

Bug class guarded: shared mutable paint (R5 in Testing Design): one Point's
write showing on every other Point.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena.color import Color
from scena.shapes import Point, Rect


def rgba(c):
    return (c._r, c._g, c._b, c._a)


class TestMarkerFill(unittest.TestCase):
    def setUp(self):
        self.made = []

    def tearDown(self):
        for o in self.made:
            o.destroy()

    def keep(self, o):
        self.made.append(o)
        return o

    def test_points_hold_the_role_colors(self):
        """The colors before the shared marker (checked against the old code):
        a guide at construction, hidden or shown; a handle once draggable."""
        guide = rgba(Color(Point.GUIDE_COLOR).with_alpha(Point.GUIDE_ALPHA))
        hidden = self.keep(Point(1, 2))
        self.assertEqual(rgba(hidden.fill), guide)
        self.assertIsNone(hidden.line)
        self.assertEqual(rgba(self.keep(Point(3, 4, layer="default")).fill), guide)
        self.assertEqual(rgba(self.keep(Rect(width=10, height=10, center=(5, 5))).center.fill), guide)
        handle = self.keep(Point(0, 0))
        handle.draggable = True
        self.assertEqual(rgba(handle.fill),
                         rgba(Color(Point.HANDLE_COLOR).with_alpha(Point.HANDLE_ALPHA)))

    def test_a_write_on_one_point_leaves_the_others(self):
        a, b = self.keep(Point(0, 0)), self.keep(Point(1, 1))
        before = rgba(b.fill)
        a.set_color("gold")
        self.assertEqual(rgba(b.fill), before)
        a.set_alpha(0.1)
        self.assertEqual(rgba(b.fill), before)
        c = self.keep(Point(2, 2))
        c.set_alpha(0.9)
        self.assertEqual(rgba(b.fill), before)
        self.assertAlmostEqual(c.fill._a, 0.9)
        d = self.keep(Point(3, 3))
        self.assertEqual(rgba(d.fill), before, "a new Point after the writes")

    def test_a_subclass_marker_color_is_its_own(self):
        class Pin(Point):
            GUIDE_COLOR = "orange"
            GUIDE_ALPHA = 0.3

        p = self.keep(Pin(0, 0))
        self.assertEqual(rgba(p.fill), rgba(Color("orange").with_alpha(0.3)))
        q = self.keep(Point(0, 0))
        self.assertEqual(rgba(q.fill), rgba(Color(Point.GUIDE_COLOR).with_alpha(Point.GUIDE_ALPHA)))


if __name__ == "__main__":
    unittest.main()
