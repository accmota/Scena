"""A setter that gets its own held object back writes nothing.

``ship.vel += w`` runs ``Vec2.__iadd__`` (both axes written, guarded) and then
assigns the same Vec2 back through the ``Graphic.vel`` setter. The setter used
to write both axes a second time: four guarded field writes per ``+=``, about
2 µs of a 7.5 µs line (2026-10-16). It now returns early on its own object,
keeping the one check ``+=`` does not run (a batched write skips the finite
check). The class: every exported Entity kind, every held part a route can
assign, assigned back to itself, makes zero field writes.

Run headless:

    python -m unittest tests.test_held_part_assign_back -v
"""
import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import surface_support as ss  # noqa: E402  (boots headless)

import scena  # noqa: E402
from scena import Circle, State, Vec2, vec_from_angle  # noqa: E402
from scena.entity import Graphic  # noqa: E402
from scena import DestroyedError  # noqa: E402
from scena.state import Container, _pose_cell_of  # noqa: E402


class _CountWrites:
    """Count ``Container._write_field`` calls on ``held`` (and its parts)."""

    def __init__(self, held):
        self.held = held
        self.names = []

    def __enter__(self):
        orig = Container._write_field
        held, names = self.held, self.names

        def counting(node, name, value):
            if node is held or node.__dict__.get("_owner") is held:
                names.append(name)
            return orig(node, name, value)

        self._orig = orig
        Container._write_field = counting
        return self

    def __exit__(self, *exc):
        Container._write_field = self._orig
        return False


class TestVelInPlace(unittest.TestCase):
    def setUp(self):
        self.c = Circle(center=(0, 0), radius=5)
        self.c.vel = (1, 2)

    def tearDown(self):
        if self.c:
            self.c.destroy()

    def test_iadd_isub_keep_the_object_and_add(self):
        held = self.c.vel
        self.c.vel += Vec2(0.5, -1)
        self.assertIs(self.c.vel, held)
        self.assertEqual(tuple(self.c.vel), (1.5, 1.0))
        self.c.vel -= (0.5, 1)
        self.assertIs(self.c.vel, held)
        self.assertEqual(tuple(self.c.vel), (1.0, 0.0))
        self.c.vel += vec_from_angle(0, 2)
        self.assertEqual(tuple(self.c.vel), (3.0, 0.0))

    def test_iadd_writes_each_axis_once(self):
        held = self.c.vel
        with _CountWrites(held) as w:
            self.c.vel += Vec2(1, 1)
        self.assertEqual(sorted(w.names), ["x", "y"])
        with _CountWrites(held) as w:
            self.c.vel -= (1, 1)
        self.assertEqual(sorted(w.names), ["x", "y"])

    def test_assign_back_writes_nothing(self):
        held = self.c.vel
        with _CountWrites(held) as w:
            self.c.vel = self.c.vel
        self.assertEqual(w.names, [])
        self.assertIs(self.c.vel, held)
        self.assertEqual(tuple(self.c.vel), (1.0, 2.0))

    def test_a_tuple_and_another_vec2_still_write_into_the_held_one(self):
        held = self.c.vel
        self.c.vel = (3, 4)
        self.assertIs(self.c.vel, held)
        self.assertEqual(tuple(self.c.vel), (3.0, 4.0))
        other = Vec2(5, 6)
        self.c.vel = other
        self.assertIs(self.c.vel, held)
        self.assertIsNot(self.c.vel, other)
        self.assertEqual(tuple(self.c.vel), (5.0, 6.0))

    def test_a_non_finite_sum_still_raises_naming_the_axis(self):
        # The batched ``+=`` write skips the finite check; the setter keeps it.
        for start, delta, axis in (((1, 2), (math.inf, 0), "x"),
                                   ((1, 2), (0, -math.inf), "y"),
                                   ((1e308, 2), (1e308, 0), "x")):   # overflow
            with self.subTest(start=start, delta=delta):
                self.c.vel = start
                with self.assertRaises(ValueError) as ctx:
                    self.c.vel += delta
                self.assertIn(f"Circle.vel {axis} must be a finite number",
                              str(ctx.exception))

    def test_destroyed_refuses_the_assignment(self):
        self.c.destroy()
        with self.assertRaises(DestroyedError):
            self.c.vel += (1, 0)
        with self.assertRaises(DestroyedError):
            self.c.vel = self.c.vel

    def test_link_on_vel_stays_refused(self):
        with self.assertRaises(AttributeError):
            self.c.vel @= lambda: (1, 1)
        with self.assertRaises(AttributeError):
            self.c.vel["x"] @= lambda: 1

    def test_a_formula_reading_vel_follows(self):
        o = Circle(center=(0, 0), radius=3)
        try:
            o.center["x"] @= lambda: self.c.vel.x * 10
            self.c.vel += (1, 0)
            self.assertEqual(o.center.x, 20.0)
            self.c.vel -= (2, 0)
            self.assertEqual(o.center.x, 0.0)
        finally:
            o.destroy()

    def test_pose_revision_bumps_once_per_change(self):
        cell = _pose_cell_of(self.c.vel)
        r0 = cell[0]
        self.c.vel += (1, 0)
        self.assertEqual(cell[0] - r0, 1)
        self.c.vel = self.c.vel
        self.assertEqual(cell[0] - r0, 1)

    def test_a_state_cell_keeps_its_copy(self):
        st = State()
        st.v0 = self.c.vel
        self.c.vel += (1, 0)
        self.assertEqual(tuple(st.v0), (1.0, 2.0))
        self.assertEqual(tuple(self.c.vel), (2.0, 2.0))


class TestAssignBackWritesNothing(unittest.TestCase):
    """Bug class: no setter rewrites the part it already holds."""

    def test_every_kind_every_held_part(self):
        checked = 0
        for name in ss.constructor_names():
            if ss.family_of(name) != "entity":
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    obj = ss.make_instance(name)
                except Exception:
                    continue      # kinds with required arguments
            try:
                if isinstance(obj, Graphic):
                    obj.vel = (1, 2)
                routes = getattr(obj, "_setattr_route", None) or {}
                for attr, route in sorted(routes.items()):
                    if not (hasattr(route, "__set__") and hasattr(route, "__get__")):
                        continue
                    try:
                        held = getattr(obj, attr)
                    except Exception:
                        continue
                    if (not isinstance(held, Container)
                            or held.__dict__.get("_owner") is not obj):
                        continue
                    try:
                        with _CountWrites(held) as w:
                            setattr(obj, attr, held)
                    except scena.DerivedAttributeError:
                        continue  # a computed part refuses any write (by design)
                    with self.subTest(kind=name, part=attr):
                        self.assertEqual(w.names, [])
                        self.assertIs(getattr(obj, attr), held)
                    checked += 1
            finally:
                ss.remove(obj)
        # Vacuity guard: vel and center on the shapes at least.
        self.assertGreater(checked, 20)


if __name__ == "__main__":
    unittest.main()
