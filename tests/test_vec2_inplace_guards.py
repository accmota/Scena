"""An in-place Vec2 op runs the guards of a plain axis write, before it writes.

``v += …`` / ``v -= …`` / ``v.do_rotation(…)`` write both axes inside one
batch, and a batched axis write skips the field's finite check and its
Derivate refusal (``_coerce_magnitude_slot(clamp=True)``; ``_write_field``
under ``_in_batch_update``). Found 2026-10-16: a free ``w += (inf, 0)`` stored
inf while ``w.x = inf`` raised; ``ship.vel += (inf, 0)`` raised from the vel
setter with x already inf; ``Line(p1, p2).vec += …`` wrote a vector p2 then
disagreed with. ``Vec2._store_xy`` checks both axes, then writes.

A part of a destroyed actor refuses every write (Reactive Design, "Destroy and
teardown"): an Entity part (``center``, ``p1``) was retired, but the ``vel``
Vec2 is not an Entity, so ``held.x = 3`` was stored and ``dead.vel += (1, 0)``
changed the vector before the dead route refused. Teardown marks every part
destroyed; reads stay legal.

    python -m unittest tests.test_vec2_inplace_guards -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import Circle, Line, Polygon, Rect, Text, Vec2  # noqa: E402
from scena.shapes import Point  # noqa: E402
from scena.state import DerivedAttributeError, DestroyedError  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made

INF, NAN = math.inf, math.nan


def _free_holding(x, y):
    """A Vec2 holding a non-finite pair, stored raw: no public door makes one
    since VB4 (every door refuses NaN / inf), but ``+=`` must still refuse a
    corrupted operand rather than pass it on."""
    v = Vec2(0, 0)
    v.__dict__.update(x=float(x), y=float(y))
    return v


def _state(v):
    return (v.x, v.y, v.length, v.angle)


def _same(a, b):
    return all(p == q or (p != p and q != q) for p, q in zip(a, b))


# Every in-place op, as (label, apply(target, operand)).
_OPS = (
    ("+=", lambda v, o: v.__iadd__(o)),
    ("-=", lambda v, o: v.__isub__(o)),
)

# Non-finite operands: each axis, each kind, each operand type.
_BAD_OPERANDS = (
    ("(inf, 0)", lambda: (INF, 0)),
    ("(0, -inf)", lambda: (0, -INF)),
    ("(nan, 0)", lambda: (NAN, 0)),
    ("[0, nan]", lambda: [0, NAN]),
    ("Vec2 holding inf", lambda: _free_holding(INF, 0)),
    ("Vec2 holding nan on y", lambda: _free_holding(0, NAN)),
    ("(10**400, 0)", lambda: (10 ** 400, 0)),
)


def _targets():
    """Every kind of vector an author can hold: free, an actor's vel, a
    Defining vector part (Line(p1, vec=))."""
    free = Vec2(1, 2)
    ship = Circle(center=(100, 100), radius=10)
    ship.vel = (3, 4)
    line = Line(p1=(0, 0), vec=(3, 4))
    return (("free Vec2", free, None), ("ship.vel", ship.vel, ship),
            ("Line(p1, vec=).vec", line.vec, line))


class TestInPlaceOpsRefuseNonFinite(unittest.TestCase):
    """Every in-place op × every non-finite operand × every kind of vector:
    ValueError, and neither axis (nor length / angle) changed."""

    def test_matrix(self):
        for label, target, host in _targets():
            for op_label, op in _OPS:
                for bad_label, bad in _BAD_OPERANDS:
                    with self.subTest(target=label, op=op_label, operand=bad_label):
                        before = _state(target)
                        host_before = tuple(host.vec) if isinstance(host, Line) else None
                        with self.assertRaises(ValueError):
                            op(target, bad())
                        self.assertTrue(_same(_state(target), before),
                                        f"{_state(target)} != {before}")
                        if host_before is not None:
                            self.assertEqual(tuple(host.p2), host_before)

    def test_overflowing_result(self):
        """Two finite operands whose sum overflows float: refused, unchanged."""
        for label, target, _host in _targets():
            with self.subTest(target=label):
                target << (1e308, 1)
                with self.assertRaises(ValueError):
                    target += (1e308, 0)
                self.assertEqual((target.x, target.y), (1e308, 1.0))

    def test_do_rotation_overflow(self):
        """do_rotation's result is checked too (a finite angle can overflow)."""
        for label, target, _host in _targets():
            with self.subTest(target=label):
                target << (1.5e308, 1.5e308)
                with self.assertRaises(ValueError):
                    target.do_rotation(45)
                self.assertEqual((target.x, target.y), (1.5e308, 1.5e308))
                with self.assertRaises(ValueError):
                    target.do_rotation(NAN)
                self.assertEqual((target.x, target.y), (1.5e308, 1.5e308))

    def test_vel_message_names_the_actor(self):
        ship = Circle(center=(0, 0), radius=5)
        ship.vel = (1, 1)
        with self.assertRaises(ValueError) as ctx:
            ship.vel += (INF, 0)
        self.assertIn(f"{ship.name}.vel x", str(ctx.exception))
        self.assertIn("finite", str(ctx.exception))
        self.assertEqual(tuple(ship.vel), (1.0, 1.0))

    def test_same_words_as_plain_write(self):
        w = Vec2(1, 2)
        with self.assertRaises(ValueError) as plain:
            w.x = INF
        with self.assertRaises(ValueError) as inplace:
            w += (INF, 0)
        self.assertEqual(str(plain.exception), str(inplace.exception))

    def test_rebinding_ops_already_refuse(self):
        """``*=`` / ``/=`` rebind through ``*`` / ``/`` (a new vector): the
        constructor and the vel setter refuse, nothing is written."""
        w = Vec2(1, 2)
        for apply in (lambda v: v * INF, lambda v: v * NAN, lambda v: v / 1e-320):
            with self.subTest(op=apply):
                with self.assertRaises((ValueError, ZeroDivisionError)):
                    apply(w)
        ship = Circle(center=(0, 0), radius=5)
        ship.vel = (1, 1)
        with self.assertRaises(ValueError):
            ship.vel *= INF
        self.assertEqual(tuple(ship.vel), (1.0, 1.0))

    def test_finite_ops_still_write(self):
        for label, target, host in _targets():
            with self.subTest(target=label):
                target << (3, 4)
                target += (1, 0)
                target += Vec2(0, 1)
                target -= [2, 2]
                self.assertEqual((target.x, target.y), (2.0, 3.0))
                self.assertAlmostEqual(target.length, math.hypot(2, 3))
                target.do_rotation(90)
                self.assertAlmostEqual(target.x, -3.0)
                self.assertAlmostEqual(target.y, 2.0)
                if isinstance(host, Line):
                    self.assertAlmostEqual(host.p2.x, -3.0)
                    self.assertAlmostEqual(host.p2.y, 2.0)

    def test_point_operand_refused(self):
        # VB10: a Point is a place, not a displacement (as ``v << p`` says).
        w = Vec2(1, 2)
        for op in (w.__iadd__, w.__isub__):
            with self.assertRaises(TypeError):
                op(Point.temp(1, 1))
        self.assertEqual(tuple(w), (1.0, 2.0))

    def test_bad_operand_type_still_type_error(self):
        w = Vec2(1, 2)
        for bad in (5, "ab", (1, 2, 3), (True, 0), ("a", 0)):
            with self.subTest(operand=bad):
                with self.assertRaises(TypeError):
                    w += bad
                with self.assertRaises(TypeError):
                    w -= bad
                self.assertEqual(tuple(w), (1.0, 2.0))


class TestInPlaceOpsOnADerivedVector(unittest.TestCase):
    """A computed vector refuses an in-place op as it refuses ``v.x = …``."""

    def test_line_p1_p2_vec(self):
        line = Line(p1=(0, 0), p2=(3, 4))
        for label, apply in (("+=", lambda v: v.__iadd__((1, 0))),
                             ("-=", lambda v: v.__isub__(Vec2(1, 0))),
                             ("do_rotation", lambda v: v.do_rotation(90))):
            with self.subTest(op=label):
                held = line.vec
                with self.assertRaises(DerivedAttributeError) as ctx:
                    apply(held)
                self.assertIn("computed from the line's p1 and p2", str(ctx.exception))
                self.assertEqual(tuple(line.vec), (3.0, 4.0))
                self.assertEqual(tuple(line.p2), (3.0, 4.0))


class TestDestroyedActorParts(unittest.TestCase):
    """Every part of a destroyed actor the author may still hold refuses every
    write door, before it changes, and stays readable."""

    def _dead_ship(self):
        ship = Circle(center=(100, 100), radius=10)
        ship.vel = (2, 3)
        vel, center = ship.vel, ship.center
        ship.destroy()
        return ship, vel, center

    def test_vel_write_doors(self):
        doors = (
            ("vel.x =", lambda s, v: setattr(v, "x", 3)),
            ("vel.y =", lambda s, v: setattr(v, "y", 3)),
            ("held +=", lambda s, v: v.__iadd__((1, 0))),
            ("held -=", lambda s, v: v.__isub__(Vec2(1, 0))),
            ("held <<", lambda s, v: v.__lshift__((5, 5))),
            ("held.do_rotation", lambda s, v: v.do_rotation(90)),
            ("dead.vel +=", lambda s, v: s.vel.__iadd__((1, 0))),
            ("dead.vel =", lambda s, v: setattr(s, "vel", (5, 5))),
            ("held['x'] @=", lambda s, v: v["x"].__imatmul__(lambda: 4)),
        )
        for label, door in doors:
            with self.subTest(door=label):
                ship, vel, _center = self._dead_ship()
                with self.assertRaises(DestroyedError):
                    door(ship, vel)
                self.assertEqual((vel.x, vel.y), (2.0, 3.0))
                self.assertEqual(tuple(ship.vel), (2.0, 3.0))

    def test_dead_vel_refusal_names_the_host(self):
        ship, vel, _center = self._dead_ship()
        with self.assertRaises(DestroyedError) as ctx:
            vel.x = 3
        self.assertIn("a part of the Circle", str(ctx.exception))

    def test_history_names_the_dead_host(self):
        """History refuses a dead vel as it refuses a dead center (one rule:
        ``_destroyed_with_host``)."""
        from scena.history import History
        _ship, vel, center = self._dead_ship()
        for part in (vel, center):
            with self.subTest(part=type(part).__name__):
                with self.assertRaises(DestroyedError):
                    History().snapshot(part)

    def test_reads_stay_legal(self):
        ship, vel, center = self._dead_ship()
        self.assertEqual((vel.x, vel.y), (2.0, 3.0))
        self.assertAlmostEqual(vel.length, math.hypot(2, 3))
        self.assertAlmostEqual(vel.angle, math.degrees(math.atan2(3, 2)))
        self.assertEqual(tuple(vel + (1, 1)), (3.0, 4.0))
        self.assertAlmostEqual(vel.normalize().length, 1.0)
        x, y = vel
        self.assertEqual((x, y), (2.0, 3.0))
        live = Circle(center=(0, 0), radius=3)
        live.vel = vel                      # a read of the dead vector
        live.vel += vel
        self.assertEqual(tuple(live.vel), (4.0, 6.0))
        self.assertEqual(tuple(center), (100.0, 100.0))

    def test_every_held_part_refuses(self):
        """Every part of each shape kind (Entity or not) refuses an axis write."""
        makers = (
            lambda: Circle(center=(1, 1), radius=3),
            lambda: Rect(center=(5, 5), width=4, height=3),
            lambda: Line(p1=(0, 0), p2=(5, 5)),
            lambda: Line(p1=(0, 0), vec=(5, 5)),
            lambda: Text("hi", center=(3, 3)),
            lambda: Polygon(points=[(0, 0), (4, 0), (0, 4)]),
        )
        for make in makers:
            obj = make()
            obj.vel = (1, 1)
            held = [n for n in obj._iter_subtree()
                    if n is not obj and isinstance(n, (Vec2, Point))]
            if isinstance(obj, Line) and "vec" not in [getattr(n, "_attr_name", "") for n in held]:
                held.append(obj.vec)
            self.assertTrue(held)
            obj.destroy()
            for part in held:
                with self.subTest(kind=type(obj).__name__, part=type(part).__name__):
                    before = (part.x, part.y)
                    with self.assertRaises(DestroyedError):
                        part.x = before[0] + 7
                    self.assertEqual((part.x, part.y), before)


if __name__ == "__main__":
    unittest.main()
