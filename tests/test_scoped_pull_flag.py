"""A derived read of an actor's own vector keeps its pose on the fast path.

Regression for 2026-10-20 (found writing ``examples/revoada.py``):
``self.angle = self.vel.angle`` in ``on_update`` is an ordinary author idiom.
The first ``vel.angle`` read registered the Derivate scalar
(``_ensure_derivate_scalar``) and set ``_needs_pull_invalidate`` on the
*ownership root*, the whole bird, for good. From then on every ``move_by`` /
``angle =`` took the batched, invalidating path (A2 lost): in-frame
``move_by`` ~2 -> 9 us, the ``angle`` write ~2 -> 10 us, 120 Triangles
~250 -> ~150 fps. ``vel.angle`` reads only ``vel.x`` / ``vel.y``; nothing it
says depends on the bird's center or angle.

Fix: a Vec2's ``length`` / ``angle`` flag the vector alone
(``Container._scalar_pull_scoped``, ``Vec2._requires_pull_invalidate``).
Safe because every store of a Vec2's axes passes through the vector (its
``_write_field`` gate, ``_takein_impl`` or a pull store that runs
``_sync_computed``); the A1 pose writers write Points, never a Vec2. A
``vel`` write still invalidates the vector itself once its scalars were read
(as before; Reactive Design says why a store-time sync was not taken).

Bug class: **a derived read of a part slows writes it does not depend on**,
and its mirror, **a scoped flag that a write skips** (a stale ``length`` /
``angle``). Guarded by: every fast model keeps the fast path after reading
``vel`` and its Defining Vec2 parts, through every pose verb, and every read
vector agrees with its own x / y after each step; every write door of
``vel``; a vector a cell lets go of (VB17's fix, with the scoped flag); live
consumers (a link, ``@when``) still refresh; and a canary
that plants an unscoped check and requires the door test to fail.
Reactive Design: "Scoped pull flag".

    python tests/run_tiers.py focused test_scoped_pull_flag
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import assert_catches, is_fast  # noqa: E402
from hypothesis_support import quiet  # noqa: E402
from test_diff_pose import VERB_SAMPLES, _outcome, _reader_models, apply  # noqa: E402

from scena import State, Triangle, Vec2, when  # noqa: E402
from scena.events import unregister_event  # noqa: E402
from scena.shapes import Line, Point  # noqa: E402
from scena.state import Container, ContainerSlot, get_scena_system  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _mark_dirty_count(fn) -> int:
    um = get_scena_system().update_manager
    orig = um.mark_dirty
    n = 0

    def wrapped(node):
        nonlocal n
        n += 1
        return orig(node)

    um.mark_dirty = wrapped  # type: ignore[method-assign]
    try:
        fn()
    finally:
        um.mark_dirty = orig  # type: ignore[method-assign]
    return n


def _expected(v):
    x, y = float(v.__dict__.get('x', 0.0)), float(v.__dict__.get('y', 0.0))
    a = math.degrees(math.atan2(y, x)) + 0.0
    return math.hypot(x, y), (180.0 if a == -180.0 else a)


def _stale(v):
    """None when ``v.length`` / ``v.angle`` agree with its own x / y."""
    length, angle = _expected(v)
    got_l, got_a = float(v.length), float(v.angle)
    gap = abs((got_a - angle + 180.0) % 360.0 - 180.0)
    if abs(got_l - length) > 1e-7 * max(1.0, length) or (length > 1e-9 and gap > 1e-7):
        return f"length {got_l} angle {got_a}, x/y say {length} {angle}"
    return None


def _defining_vectors(obj):
    """The Vec2 parts of ``obj``'s current model that are inputs (``Line.vec``
    of POINT_VEC); reading a Derivate part wakes the shape by design."""
    out = []
    for name, slot in obj._field_slots().items():
        if (isinstance(slot, ContainerSlot) and issubclass(slot.container_class, Vec2)
                and not obj._field_is_derivate(name, slot)):
            out.append(name)
    return out


class TestVecReadKeepsPoseFast(unittest.TestCase):
    """The bug: one ``vel.angle`` read put the actor on the slow path."""

    def test_bird_idiom_stays_fast(self):
        bird = Triangle(center=(100, 100), radius=10)
        bird.vel = (30, 40)
        bird.angle = bird.vel.angle
        _ = bird.vel.length
        self.assertTrue(is_fast(bird), "vel.angle flagged the whole bird")

        heading = bird.vel.angle

        def frame():
            bird.move_by(bird.vel.x * 0.016, bird.vel.y * 0.016)
            bird.angle = heading + 1.0
            bird.rotate_by(2.0)
        self.assertEqual(_mark_dirty_count(frame), 0, "a pose write paid invalidation")
        bird.vel.x += 1.0                       # the flock's steering write
        self.assertIsNone(_stale(bird.vel))
        self.assertTrue(is_fast(bird))
        bird.destroy()

    def test_every_fast_model_through_every_verb(self):
        """Every model that starts fast: read ``vel`` and its Defining vectors,
        then every pose verb. Still fast after each, and every read vector
        agrees with its own axes (a raw writer that skipped the sync shows
        here as a stale value)."""
        slow, stale = [], []
        for model, make in _reader_models().items():
            with quiet():
                obj = make()
            if not is_fast(obj):
                obj.destroy()
                continue
            obj.vel = (3.0, -4.0)
            vectors = [obj.vel] + [getattr(obj, n) for n in _defining_vectors(obj)]
            for v in vectors:
                _ = v.angle, v.length
            if not is_fast(obj):
                slow.append((model, "read"))
                obj.destroy()
                continue
            for op in VERB_SAMPLES:
                with quiet():
                    _outcome(apply, obj, op)
                if not is_fast(obj):
                    slow.append((model, op[0]))
                    break
                for v in vectors:
                    why = _stale(v)
                    if why is not None:
                        stale.append((model, op[0], v._attr_name, why))
            obj.destroy()
        self.assertEqual(slow, [], "a vector's derived read woke its owner")
        self.assertEqual(stale, [], "a pose verb left a vector's length / angle stale")

    def test_line_point_vec(self):
        ln = Line(p1=(0, 0), vec=(10, 0))
        self.assertEqual(ln.vec.angle, 0.0)
        self.assertTrue(is_fast(ln))
        ln.rotate_by(90)
        self.assertAlmostEqual(ln.vec.angle, 90.0)
        ln.angle = 45
        self.assertAlmostEqual(ln.vec.angle, 45.0)
        ln.vec.x = -10
        ln.vec.y = 0
        self.assertAlmostEqual(ln.vec.angle, 180.0)
        self.assertTrue(is_fast(ln))
        self.assertAlmostEqual(ln.p2.x - ln.p1.x, -10.0)   # p2 is Derivate: wakes it
        ln.destroy()


class TestVelDoorsRefresh(unittest.TestCase):
    """The mirror: with the flag on the vector alone, every write still
    refreshes its ``length`` / ``angle``."""

    DOORS = (
        ("x =", lambda s: setattr(s.vel, "x", -4.0)),
        ("y =", lambda s: setattr(s.vel, "y", 7.0)),
        ("vel = tuple", lambda s: setattr(s, "vel", (0.0, 2.0))),
        ("vel = Vec2", lambda s: setattr(s, "vel", Vec2(-1.0, -1.0))),
        ("+=", lambda s: s.vel.__iadd__((2.0, 0.5))),
        ("-=", lambda s: s.vel.__isub__((0.5, 3.0))),
        ("*=", lambda s: s.vel.__imul__(-2.0)),
        ("/=", lambda s: s.vel.__itruediv__(4.0)),
        ("do_rotation", lambda s: s.vel.do_rotation(75.0)),
        ("<<", lambda s: s.vel << (5.0, -12.0)),
    )

    def test_every_door(self):
        ship = Triangle(center=(0, 0), radius=10)
        ship.vel = (3.0, 4.0)
        _ = ship.vel.angle, ship.vel.length
        for label, door in self.DOORS:
            door(ship)
            self.assertIsNone(_stale(ship.vel), label)
        self.assertTrue(is_fast(ship))
        ship.destroy()

    def test_free_and_held_vectors(self):
        v = Vec2(3, 4)
        self.assertEqual(v.length, 5.0)
        v.x = 0.0
        self.assertEqual(v.length, 4.0)
        self.assertEqual(v.angle, 90.0)
        st = State()
        st.aim = Vec2(1, 0)
        self.assertEqual(st.aim.angle, 0.0)
        st.aim.y = 1.0
        self.assertAlmostEqual(st.aim.angle, 45.0)

    def test_a_cell_letting_go_keeps_the_derived_flag(self):
        """VB17 with the scoped flag: ``_unhold_payload`` must keep the flag a
        ``length`` read needs (a vector an ink field still holds went stale
        after ``st.a = other``)."""
        st = State()
        st.a = Vec2(1, 2)
        ship = Triangle(center=(0, 0), radius=10)
        ship.dir = st.a
        v = ship.dir
        _ = v.length, v.angle
        st.a = Vec2(5, 5)
        v.x = 0.0
        self.assertIsNone(_stale(v))
        ship.destroy()


class TestLiveConsumersStillRefresh(unittest.TestCase):
    """A4: an outbound link or ``@when`` on ``vel.angle`` still sees writes."""

    def test_link_reads_vel_angle(self):
        ship = Triangle(center=(0, 0), radius=10)
        ship.vel = (1.0, 0.0)
        _ = ship.vel.angle
        st = State()
        st.heading = 0.0
        st["heading"] @= lambda: ship.vel.angle
        ship.vel = (0.0, 1.0)
        self.assertAlmostEqual(st.heading, 90.0)
        ship.vel.x = -1.0
        ship.vel.y = 0.0
        self.assertAlmostEqual(st.heading, 180.0)
        mark = Point()
        mark @= lambda: (ship.vel.length, ship.vel.angle)
        ship.vel = (3.0, 4.0)
        self.assertAlmostEqual(mark.x, 5.0)
        st["heading"].unlink()
        mark.destroy()
        ship.destroy()

    def test_when_on_vel_angle(self):
        ship = Triangle(center=(0, 0), radius=10)
        ship.vel = (1.0, 0.0)
        _ = ship.vel.angle
        seen = []

        @when(lambda: ship.vel.angle > 90)
        def turned():
            seen.append(ship.vel.angle)

        ship.vel = (-1.0, 0.1)
        get_scena_system().update_manager.maybe_poll_events()
        self.assertTrue(seen, "@when on vel.angle missed the write")
        unregister_event(turned)
        ship.destroy()


class TestScopedFlagCanary(unittest.TestCase):
    def test_door_test_catches_an_unscoped_check(self):
        """Plant: the vector forgets its own flag (Container's check). Its
        derived value then goes stale after ``vel.x =``; the door test must
        fail."""
        assert_catches(
            self, "test_scoped_pull_flag.TestVelDoorsRefresh.test_every_door",
            [(Vec2, "_requires_pull_invalidate", Container._requires_pull_invalidate)],
            "a scoped flag that writes skip",
        )


if __name__ == "__main__":
    unittest.main()
