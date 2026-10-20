"""The Graphic center fast read (``shapes._center_part_xy``) answers what the
descriptors answer, or steps aside.

``nearest`` / ``distance`` / ``heading`` read an actor's center from its
slots' own A3 cache (Shapes Design, "Point-likes"). The read must give the
same floats as ``center.x`` / ``center.y`` through the descriptors whenever
it answers, step aside (None) whenever the descriptor would pull (a Derivate,
linked or anchored center), never wake a cold Derivate (Reactive Design,
"Lazy Derivates": a woken center costs the shape the A2 skip for good), and
leave ``nearest``'s rules alone: unpositioned items skipped, first of a tie
wins, ``within=`` inclusive, ``where=`` before the read.
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    Circle, Concave, Ellipse, Line, Polygon, Rect, RegularPolygon, Sprite, Square,
    Text, Triangle, canvas, group, init, nearest,
)
from scena.entity import _center_part_class
from scena.input import Mouse
from scena.shapes import Point, _center_part_xy, _read_xy, _xy_of
from scena.scenamath import Vec2
from scena.state import Attribute
from tests.leftovers import module_sweep


def _general(obj):
    """The read before the fast path: ``_read_xy`` from the top."""
    return _read_xy(obj)


def _fast(obj):
    part = getattr(type(obj), "_scena_center_part", None)
    return None if part is None else _center_part_xy(obj, part)


def _mouse(x, y):
    m = Mouse()
    m._x = x
    m._y = y
    return m


# kind -> maker; each a fresh actor with a center that is not a round number.
MAKERS = {
    "circle": lambda: Circle(center=(10.5, 20.25), radius=3),
    "rect by center": lambda: Rect(center=(11.5, 21.25), width=4, height=6),
    "rect by corner": lambda: Rect(top_left=(12.5, 22.25), width=4, height=6),
    "square": lambda: Square(center=(13.5, 23.25), length=3),
    "ellipse": lambda: Ellipse(center=(14.5, 24.25), width=3, height=5),
    "regular polygon": lambda: RegularPolygon(center=(15.5, 25.25), radius=3, n=5),
    "triangle": lambda: Triangle(center=(16.5, 26.25), radius=3),
    "concave": lambda: Concave(center=(17.5, 27.25), width=8, height=8),
    "line": lambda: Line(p1=(0.3, 0.7), p2=(10.1, 4.9)),
    "polygon": lambda: Polygon(points=[(0, 0), (10, 0), (3, 7)]),
    "text": lambda: Text("hi", center=(5.5, 6.5)),
    "sprite": lambda: Sprite(center=(3.5, 4.5), width=8, height=8),
}


# Kinds whose center is computed from other parts (cannot be set).
DERIVED_CENTER = {"rect by corner", "line", "polygon", "text"}

setUpModule, tearDownModule = module_sweep()


class CenterFastReadCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def assertSameRead(self, obj, msg=""):
        """Fast read (when it answers) == descriptors; ``_xy_of`` == the general read."""
        general = _general(obj)
        fast = _fast(obj)
        if fast is not None:
            self.assertEqual(fast, general, msg)
            self.assertIs(type(fast[0]), float, msg)
        self.assertEqual(_xy_of(obj), general, msg)
        return general


class TestClassTable(CenterFastReadCase):
    def test_which_kinds_take_the_fast_read(self):
        fast = {k for k, make in MAKERS.items() if type(make())._scena_center_part is Point}
        self.assertEqual(fast, set(MAKERS) - {"polygon", "text"})
        self.assertIsNone(Point._scena_center_part)

    def test_an_author_class_with_its_own_center_keeps_the_general_read(self):
        class Fixed(Circle):
            @property
            def center(self):
                return Point(1.0, 2.0, layer=None)

        class Watched(Circle):
            def __getattribute__(self, name):
                return object.__getattribute__(self, name)

        self.assertIsNone(_center_part_class(Fixed))
        self.assertIsNone(_center_part_class(Watched))
        self.assertIs(_center_part_class(type("Plain", (Circle,), {})), Point)
        f = Fixed(center=(5, 5), radius=1)
        self.assertEqual(_xy_of(f), (1.0, 2.0))


class TestSameFloatsEveryKind(CenterFastReadCase):
    def test_fresh_then_read_again(self):
        for kind, make in MAKERS.items():
            with self.subTest(kind=kind):
                obj = make()
                first = self.assertSameRead(obj, kind)
                self.assertEqual(self.assertSameRead(obj, kind), first)

    def test_after_every_pose_write(self):
        for kind, make in MAKERS.items():
            with self.subTest(kind=kind):
                obj = make()
                self.assertSameRead(obj, kind)
                obj.move_by(1.25, -2.5)
                self.assertSameRead(obj, kind + " move_by")
                obj.move_to(7.75, 8.125)
                self.assertSameRead(obj, kind + " move_to")
                obj.rotate_to(33)
                self.assertSameRead(obj, kind + " rotate_to")
                if kind not in DERIVED_CENTER:
                    obj.center = (3.5, 9.25)
                    self.assertSameRead(obj, kind + " center =")
                    obj.center.x = 4.75
                    self.assertSameRead(obj, kind + " center.x =")

    def test_point_likes_that_are_not_actors(self):
        cell = Attribute((1.5, 2.5))
        for label, obj in {
            "tuple": (1.5, 2.5), "list": [1.5, 2.5], "int tuple": (1, 2),
            "Point": Point(1.5, 2.5, layer=None), "Vec2": Vec2(1.5, 2.5),
            "mouse": _mouse(1.5, 2.5), "cell": cell,
        }.items():
            with self.subTest(label=label):
                self.assertIsNone(_fast(obj))
                self.assertEqual(_xy_of(obj), _general(obj))
        for label, obj in {"str": "ab", "object": object(), "none": None,
                           "bool pair": (True, 1), "three": (1, 2, 3)}.items():
            with self.subTest(label=label):
                self.assertIsNone(_xy_of(obj))
                self.assertIsNone(_general(obj))


class TestStepsAsideWhenTheDescriptorPulls(CenterFastReadCase):
    def test_a_linked_center_follows_its_source(self):
        guide = Circle(center=(1.5, 1.5), radius=1)
        follower = Circle(center=(0, 0), radius=1)
        follower.center @= guide.center
        self.assertSameRead(follower)
        guide.move_by(10.25, 0)
        self.assertEqual(self.assertSameRead(follower), (11.75, 1.5))

    def test_a_formula_center_is_read_fresh(self):
        src = Circle(center=(0, 0), radius=2.5)
        c = Circle(center=(0, 0), radius=1)
        c["center"] @= lambda: (src.radius, 3.5)
        self.assertEqual(self.assertSameRead(c), (2.5, 3.5))
        src.radius = 9.5
        self.assertEqual(self.assertSameRead(c), (9.5, 3.5))

    def test_an_anchored_axis_is_read_fresh(self):
        src = Circle(center=(0, 0), radius=2.5)
        c = Circle(center=(0, 7.5), radius=1)
        c.center["x"] @= lambda: -src.radius
        self.assertEqual(self.assertSameRead(c), (-2.5, 7.5))
        src.radius = 4.25
        self.assertEqual(self.assertSameRead(c), (-4.25, 7.5))

    def test_unlinked_again_takes_the_fast_read(self):
        guide = Circle(center=(1.5, 1.5), radius=1)
        c = Circle(center=(0, 0), radius=1)
        c.center @= guide.center
        self.assertSameRead(c)
        c["center"].unlink()
        self.assertSameRead(c)
        c.center = (6.5, 6.5)
        self.assertSameRead(c)
        self.assertEqual(_fast(c), (6.5, 6.5))

    def test_a_woken_derivate_center_steps_aside_and_stays_fresh(self):
        for kind in ("rect by corner", "line"):
            with self.subTest(kind=kind):
                obj = MAKERS[kind]()
                self.assertSameRead(obj)        # wakes the center (as before)
                self.assertIn("center", obj.__dict__)
                self.assertIsNone(_fast(obj))
                obj.move_by(3.5, -1.25)
                self.assertSameRead(obj, kind + " after move")

    def test_a_parked_and_a_destroyed_actor_read_the_same(self):
        for kind in ("circle", "sprite"):
            with self.subTest(kind=kind):
                parked = MAKERS[kind]()
                self.assertSameRead(parked)
                parked.active = False
                self.assertSameRead(parked, kind + " parked")
                dead = MAKERS[kind]()
                self.assertSameRead(dead)
                dead.destroy()
                self.assertSameRead(dead, kind + " destroyed")


class TestWakesNothing(CenterFastReadCase):
    def test_a_cold_derivate_center_stays_cold(self):
        for kind in ("rect by corner", "line"):
            with self.subTest(kind=kind):
                obj = MAKERS[kind]()
                self.assertNotIn("center", obj.__dict__)
                self.assertIsNone(_fast(obj))
                self.assertNotIn("center", obj.__dict__)
                self.assertFalse(getattr(obj, "_needs_pull_invalidate", False))


class TestNearestRulesUnchanged(CenterFastReadCase):
    @staticmethod
    def _reference(origin, items, within=None, where=None):
        """``nearest`` as it was: ``_read_xy`` on every item."""
        ox, oy = _read_xy(origin, True)
        best, best_d2 = None, None
        for item in items:
            if where is not None and not where(item):
                continue
            xy = _read_xy(item)
            if xy is None:
                continue
            d2 = (xy[0] - ox) ** 2 + (xy[1] - oy) ** 2
            if within is not None and d2 > within * within:
                continue
            if best_d2 is None or d2 < best_d2:
                best, best_d2 = item, d2
        return best

    def test_ties_first_wins_and_unpositioned_skipped(self):
        a = Circle(center=(10, 0), radius=1)
        b = Circle(center=(-10, 0), radius=1)
        c = Sprite(center=(0, 10), width=2, height=2)
        items = ["nope", None, b, a, c, (0, -10)]
        self.assertIs(nearest((0, 0), items), b)
        self.assertIs(nearest((0, 0), items[3:]), a)
        self.assertIs(nearest((0, 0), items, within=10), b)
        self.assertIsNone(nearest((0, 0), items, within=9.99))
        self.assertIs(nearest((0, 0), items, where=lambda o: o is not b), a)

    def test_where_runs_on_every_item_before_any_read(self):
        seen = []
        a = Circle(center=(1, 0), radius=1)
        nearest((0, 0), [a, "nope", (2, 0)], where=lambda o: seen.append(o) or True)
        self.assertEqual(seen, [a, "nope", (2, 0)])

    def test_random_mixed_fleets_match_the_reference(self):
        rng = random.Random(1234)
        makers = list(MAKERS.values()) + [
            lambda: (rng.uniform(0, 50), rng.uniform(0, 50)),
            lambda: Point(rng.uniform(0, 50), rng.uniform(0, 50), layer=None),
            lambda: Vec2(rng.uniform(0, 50), rng.uniform(0, 50)),
            lambda: _mouse(rng.uniform(0, 50), rng.uniform(0, 50)),
            lambda: "nope",
        ]
        for trial in range(60):
            items = [rng.choice(makers)() for _ in range(rng.randint(0, 12))]
            for obj in items:
                if hasattr(obj, "move_to") and rng.random() < 0.7:
                    obj.move_to(rng.choice((5.0, 10.0, rng.uniform(0, 50))),
                                rng.choice((5.0, 10.0, rng.uniform(0, 50))))
            if items and rng.random() < 0.5:
                items.append(items[0])          # a duplicate: still first wins
            origin = rng.choice([(5.0, 5.0), _mouse(10.0, 10.0),
                                 Circle(center=(7.5, 7.5), radius=1)])
            within = rng.choice([None, 0.0, 5.0, 20.0])
            where = rng.choice([None, lambda o: not isinstance(o, str),
                                lambda o: getattr(o, "visible", True)])
            want = self._reference(origin, items, within, where)
            self.assertIs(nearest(origin, items, within=within, where=where), want,
                          f"trial {trial}")

    def test_group_nearest_matches_the_reference(self):
        rng = random.Random(99)
        pts = [Circle(center=(rng.uniform(0, 100), rng.uniform(0, 100)), radius=2,
                      group="cfr_dot") for _ in range(30)]
        pts[3].move_to(*pts[7].center)          # a tie inside the group
        fleet = group["cfr_dot"]
        for p in pts:
            want = self._reference(p, list(fleet), where=lambda o: o is not p)
            self.assertIs(fleet.nearest(p, where=lambda o: o is not p), want)
            self.assertIs(fleet.nearest(p, within=15), self._reference(p, list(fleet), 15))


if __name__ == "__main__":
    unittest.main()
