"""``==`` on a Point compares the object; author code that meant the position warns (PE1 in Testing Design).

``c.center == (400, 120)`` was always False, with nothing to say so: a Point is
an object (the engine keys weak sets and dicts on it and scans its lists with
``in`` / ``remove``, where two handles often share a spot), so its ``==`` is
identity. An author who stepped ``elevador`` onto a stop with ``approach`` and
then tested ``elevador.center == PARADA`` waited forever. Value ``==`` would
make the engine remove the wrong handle and unhash every Point; the fix keeps
identity and warns, once per line, when author code compares a Point with a
position (tuple, list, Vec2) or with another Point on the same spot.

Bug class: an ``==`` that is silently always False on a type authors read as a
value. Guards: every spelling of the comparison warns (both operand orders,
``!=``, ``in``, through a cell), the results stay identity, the hash stays
identity (a class that gains ``__eq__`` loses its ``__hash__``), and engine
compares stay silent.

    python tests/run_tiers.py focused test_point_equality
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings
import weakref

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import Circle, Point, Rect, Vec2, distance, st  # noqa: E402
from scena.canvas import ScenaCanvas  # noqa: E402
from scena import shapes  # noqa: E402
from scena.shapes import Anchor  # noqa: E402
from scena.state import Attribute  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class _Recording(unittest.TestCase):
    def setUp(self):
        shapes._POINT_EQ_WARNED.clear()
        rec = warnings.catch_warnings(record=True)
        self.caught = self.enterContext(rec)
        warnings.simplefilter("always")

    def compare_warnings(self):
        return [w for w in self.caught
                if issubclass(w.category, RuntimeWarning)
                and "==" in str(w.message) and "Point" in str(w.message)]

    def assertWarnsOnce(self, fragment):
        found = self.compare_warnings()
        self.assertEqual(len(found), 1, [str(w.message) for w in found])
        self.assertIn(fragment, str(found[0].message))
        self.assertIn("distance(", str(found[0].message))
        self.assertEqual(os.path.abspath(found[0].filename), os.path.abspath(__file__))
        return found[0]

    def assertSilent(self):
        self.assertEqual([str(w.message) for w in self.compare_warnings()], [])


class TestAuthorComparesWarn(_Recording):
    def setUp(self):
        super().setUp()
        self.c = Circle(center=(5, 5), radius=1)
        self.d = Circle(center=(5, 5), radius=2)

    def test_point_eq_tuple(self):
        self.assertFalse(self.c.center == (5, 5))
        self.assertWarnsOnce("Point == tuple is always False")

    def test_tuple_eq_point(self):
        self.assertFalse((5, 5) == self.c.center)
        self.assertWarnsOnce("Point == tuple")

    def test_point_ne_tuple(self):
        self.assertTrue(self.c.center != (5, 5))
        self.assertWarnsOnce("!= always True")

    def test_point_eq_list(self):
        self.assertFalse(self.c.center == [5, 5])
        self.assertWarnsOnce("Point == list")

    def test_point_eq_vec2(self):
        self.assertFalse(self.c.center == Vec2(5, 5))
        self.assertWarnsOnce("Point == Vec2")

    def test_vec2_eq_point(self):
        self.assertFalse(Vec2(5, 5) == self.c.center)
        self.assertWarnsOnce("Point == Vec2")

    def test_any_position_warns_not_only_the_same_one(self):
        self.assertFalse(self.c.center == (400, 120))
        self.assertWarnsOnce("always False")

    def test_arithmetic_result(self):
        self.assertFalse(self.c.center + (0, 10) == (5, 15))
        self.assertWarnsOnce("Point == tuple")

    def test_two_points_on_one_spot(self):
        self.assertFalse(self.c.center == self.d.center)
        w = self.assertWarnsOnce("same position (5, 5)")
        self.assertIn("a is b", str(w.message))

    def test_a_stop_kept_as_a_point(self):
        parada = Point(5, 5)
        self.assertFalse(self.c.center == parada)
        self.assertWarnsOnce("same position")

    def test_membership_on_one_spot(self):
        # The agreed price: ``in`` runs ``==``, so a list holding another
        # Point on the same spot warns too.
        self.assertFalse(self.c.center in [self.d.center])
        self.assertWarnsOnce("same position")

    def test_through_a_cell(self):
        cell = Attribute((5, 5))
        self.assertFalse(cell == self.c.center)
        self.assertWarnsOnce("Point == tuple")

    def test_anchor_is_a_point(self):
        a = Anchor(5, 5)
        try:
            self.assertFalse(a == (5, 5))
            self.assertWarnsOnce("Point == tuple")
        finally:
            a.destroy()

    def test_once_per_line(self):
        for _ in range(3):
            self.assertFalse(self.c.center == (5, 5))
        self.assertWarnsOnce("Point == tuple")


class TestQuietWhenNothingIsWrong(_Recording):
    def test_other_spot_or_other_kinds(self):
        c = Circle(center=(5, 5), radius=1)
        d = Circle(center=(9, 9), radius=1)
        self.assertFalse(c.center == d.center)        # different spots: False either way
        self.assertFalse(c.center == c)               # a Graphic is not a position
        self.assertFalse(c.center == (1, 2, 3))       # not a point-like
        self.assertFalse(c.center == 5)
        self.assertTrue(c.center == c.center)
        self.assertTrue(distance(c.center, (5, 5)) == 0)
        self.assertTrue(distance(c.center, Vec2(5, 5)) == 0)
        self.assertSilent()

    def test_vec2_value_eq_unchanged(self):
        self.assertTrue(Vec2(1, 2) == (1, 2))
        self.assertTrue(Vec2(1, 2) == Vec2(1, 2))
        self.assertFalse(Vec2(1, 2) == "x")
        self.assertSilent()


class TestIdentityKept(unittest.TestCase):
    def test_hash_is_identity(self):
        # A class body that defines ``__eq__`` gets ``__hash__ = None``.
        self.assertIs(Point.__hash__, object.__hash__)
        self.assertIs(Anchor.__hash__, object.__hash__)
        p, q = Point(5, 5), Point(5, 5)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.assertEqual(len({p, q}), 2)
            self.assertEqual({p: 1, q: 2}[q], 2)
        ws = weakref.WeakSet([p, q])
        wk = weakref.WeakKeyDictionary({p: 1, q: 2})
        self.assertEqual((len(ws), wk[p], wk[q]), (2, 1, 2))
        p.x = 9                                   # moving keeps the key
        self.assertIn(p, ws)
        self.assertEqual(wk[p], 1)

    def test_retired_value_helpers(self):
        # ``Point.eq`` / ``get_hash`` were a second spelling of "same
        # position" and a hash that changed when the point moved.
        self.assertFalse(hasattr(Point(1, 2), "eq"))
        self.assertFalse(hasattr(Point(1, 2), "get_hash"))


class TestEngineStaysSilent(_Recording):
    def test_handles_on_one_spot(self):
        # The registry scans ``layer._interactive`` with ``in`` / ``remove``:
        # with value ``==`` it would remove the wrong handle.
        a = Circle(center=(50, 50), radius=5)
        b = Circle(center=(50, 50), radius=9)
        try:
            a.center.handle = True
            b.center.handle = True
            a.center.handle = False
            self.assertTrue(b.center.handle)
            self.assertFalse(a.center.handle)
            layer = ScenaCanvas.get_current().registry.layers[b.center._layer]
            self.assertTrue(any(o is b.center for o in layer._interactive))
            self.assertFalse(any(o is a.center for o in layer._interactive))
            b.center.handle = False
            self.assertSilent()
        finally:
            a.destroy()
            b.destroy()

    def test_debug_points_on_one_spot(self):
        a = Rect(center=(0, 0), width=10, height=10)
        b = Rect(center=(0, 0), width=10, height=10)
        try:
            a.show_points()
            b.show_points()
            a.no_points()
            b.no_points()
            self.assertSilent()
        finally:
            a.destroy()
            b.destroy()

    def test_cell_holding_a_point_takes_a_tuple(self):
        c = Circle(center=(5, 5), radius=1)
        try:
            st.pe1_spot = c.center
            st.pe1_spot = (5, 5)                  # the cell compares old != new
            st.pe1_spot = Point(5, 5)
            self.assertSilent()
        finally:
            c.destroy()


if __name__ == "__main__":
    unittest.main()
