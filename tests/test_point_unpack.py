"""``x, y = ship.center``: a Point, a Vec2 and the mouse unpack as ``(x, y)``.

PB6 / PD8 / PC4 (2026-10-14): ``x, y = ship.center``, ``tuple(mouse)`` and
``x, y = Vec2(1, 2)`` raised "field name must be a str, got int" — Python's
old iteration fallback called ``p[0]`` through the field-bracket
``__getitem__``. They now iterate as a value snapshot of the two floats (like
``track.at()``).

The risk of a new ``__iter__`` is an entry that decides "is this a sequence?"
by iterating: a Point passed where it means a place or a link source would be
silently read as a tuple. Every such entry reads a Point by type; the
``TestPointKeepsItsMeaning`` rows pin that (a link still follows after the
source moves, a copy still copies), and the ``TestNotAList`` rows the entries
that take a *list* of points.

    python tests/run_tiers.py focused test_point_unpack
"""
from __future__ import annotations

import collections.abc
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

from scena import (  # noqa: E402
    Anchor, Circle, Line, Point, Polygon, Rect, Text, Track, Vec2, middle_point,
    mouse, nearest, st,
)
from scena.state import FieldRef  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


def _xy(p):
    return (round(float(p.x), 6), round(float(p.y), 6))


class TestUnpack(unittest.TestCase):
    def test_point_center_unpacks(self):
        ship = Circle(center=(10, 20), radius=5)
        x, y = ship.center
        self.assertEqual((x, y), (10.0, 20.0))
        self.assertIs(type(x), float)
        self.assertEqual(tuple(Point(3, 4)), (3.0, 4.0))
        self.assertEqual(list(Rect(center=(1, 2), width=4, height=2).top_left), [-1.0, 3.0])

    def test_vec2_and_mouse_unpack(self):
        x, y = Vec2(1, 2)
        self.assertEqual((x, y), (1.0, 2.0))
        mx, my = mouse
        self.assertEqual((mx, my), (float(mouse.x), float(mouse.y)))
        self.assertEqual(tuple(mouse), (float(mouse.x), float(mouse.y)))

    def test_star_call(self):
        c = Circle(center=(0, 0), radius=1)
        c.move_to(*Point(7, 8))
        self.assertEqual(_xy(c.center), (7.0, 8.0))

    def test_unpack_is_a_snapshot(self):
        a = Anchor(1, 2)
        x, y = a
        a.move_to(50, 60)
        self.assertEqual((x, y), (1.0, 2.0))
        self.assertEqual(tuple(a), (50.0, 60.0))

    def test_linked_point_unpacks_fresh(self):
        a = Anchor(1, 2)
        c = Circle(center=lambda: a, radius=1)
        a.move_to(30, 40)
        self.assertEqual(tuple(c.center), (30.0, 40.0))

    def test_point_is_not_a_sequence(self):
        # Iterable for unpacking, but not a Sequence: entries that test
        # Sequence (hitbox, sprite frames) keep refusing a Point.
        self.assertNotIsInstance(Point(0, 0), collections.abc.Sequence)
        self.assertNotIsInstance(Vec2(0, 0), collections.abc.Sequence)


class TestIndexRefused(unittest.TestCase):
    def test_number_index_names_the_axes(self):
        for obj, var in ((Point(1, 2), "p"), (Vec2(1, 2), "v"), (mouse, "mouse")):
            with self.subTest(kind=type(obj).__name__):
                with self.assertRaises(TypeError) as cm:
                    obj[0]
                msg = str(cm.exception)
                self.assertIn(f"{var}.x", msg)
                self.assertIn(f"x, y = {var}", msg)
                self.assertNotIn("field name must be a str", msg)

    def test_string_subscript_still_links_an_axis(self):
        src = Anchor(5, 0)
        p = Point(0, 0)
        self.assertIsInstance(p["x"], FieldRef)
        p["x"] @= lambda: src.x
        src.move_to(9, 0)
        self.assertEqual(float(p.x), 9.0)
        v = Vec2(0, 0)
        self.assertIsInstance(v["x"], FieldRef)

    def test_graphic_unpack_points_to_center(self):
        ship = Circle(center=(1, 2), radius=1)
        with self.assertRaises(TypeError) as cm:
            x, y = ship
        msg = str(cm.exception)
        self.assertIn("x, y = circle.center", msg)
        self.assertNotIn("field name must be a str", msg)

    def test_field_ref_does_not_iterate(self):
        # A link handle is not a value (Reactive Design): iterating it raises.
        st.unpack_pos = (1, 2)
        with self.assertRaises(TypeError):
            iter(st["unpack_pos"])
        with self.assertRaises(TypeError):
            iter(Point(0, 0)["x"])


class TestPointKeepsItsMeaning(unittest.TestCase):
    """A Point passed where a link or a place is meant is read by type."""

    def _moved(self, build, read):
        a = Anchor(10, 20)
        b = Anchor(30, 40)
        obj = build(a, b)
        before = read(obj)
        a.move_to(100, 200)
        return before, read(obj)

    def test_links_follow_the_source(self):
        def linked_center(a, b):
            c = Circle(center=(0, 0), radius=1)
            c.center @= a
            return c

        def bracket_center(a, b):
            c = Circle(center=(0, 0), radius=1)
            c["center"] @= a
            return c

        def whole_point(a, b):
            p = Point(0, 0)
            p @= a
            return p

        rows = {
            "c.center @= A": (linked_center, lambda o: _xy(o.center)),
            "c['center'] @= A": (bracket_center, lambda o: _xy(o.center)),
            "p @= A": (whole_point, _xy),
            "Circle(center=lambda: A)": (lambda a, b: Circle(center=lambda: a, radius=1),
                                         lambda o: _xy(o.center)),
            "Line(p1=lambda: A)": (lambda a, b: Line(p1=lambda: a, p2=b), lambda o: _xy(o.p1)),
            "Point(lambda: A)": (lambda a, b: Point(lambda: a), _xy),
            "Polygon(points=[lambda: A, ...])": (
                lambda a, b: Polygon(points=[lambda: a, b, (0, 0)]),
                lambda o: _xy(o.points[0])),
            "Text(center=lambda: A)": (
                lambda a, b: Text("hi", center=lambda: a, layer="default"),
                lambda o: _xy(o.center)),
            "middle_point(A, B) in a formula": (
                lambda a, b: Point(lambda: middle_point(a, b)), _xy),
        }
        for label, (build, read) in rows.items():
            with self.subTest(label):
                before, after = self._moved(build, read)
                self.assertNotEqual(before, after, f"{label} stopped following")
        before, after = self._moved(lambda a, b: Point(lambda: middle_point(a, b)), _xy)
        self.assertEqual(after, (65.0, 120.0))

    def test_values_copy(self):
        rows = {
            "Line(p1=A, p2=B)": (lambda a, b: Line(p1=a, p2=b), lambda o: _xy(o.p1)),
            "Circle(center=A)": (lambda a, b: Circle(center=a, radius=1), lambda o: _xy(o.center)),
            "Point(A)": (lambda a, b: Point(a), _xy),
            "Polygon(points=[A, B, ...])": (lambda a, b: Polygon(points=[a, b, (0, 0)]),
                                            lambda o: _xy(o.points[0])),
            "Rect(p1=A, p2=B)": (lambda a, b: Rect(p1=a, p2=b), lambda o: _xy(o.p1)),
        }
        for label, (build, read) in rows.items():
            with self.subTest(label):
                before, after = self._moved(build, read)
                self.assertEqual(before, (10.0, 20.0))
                self.assertEqual(after, before)

    def test_reads_by_type(self):
        a = Anchor(10, 20)
        self.assertEqual(middle_point(a, (30, 40)), (20.0, 30.0))
        self.assertEqual(Track(points=[a, (30, 40)]).at(0), (10.0, 20.0))
        self.assertEqual(str(a), str(Text(a, center=(0, 0), layer="default").text))


class TestNotAList(unittest.TestCase):
    """One point iterates as two numbers: entries that take a list of points
    refuse it instead of reading (x, y) as two items."""

    def test_polygon_points_refuses_one_point(self):
        for value in (Anchor(1, 2), Vec2(1, 2), mouse):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(TypeError) as cm:
                    Polygon(points=value)
                self.assertIn("list of points", str(cm.exception))

    def test_nearest_refuses_one_point_as_items(self):
        with self.assertRaises(TypeError) as cm:
            nearest((0, 0), Anchor(1, 2))
        self.assertIn("nearest(origin, [", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
