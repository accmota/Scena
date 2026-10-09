"""The scheduler's order and keys do not depend on accidents (review 2026-10-09, R8).

Bug class: **a key or an order that depends on something unrelated**. The
replace key of a timed move depended on whether anything had read
``.center``; the ``on_update`` fleet ran in memory-address order; a frame's
snapshot ran a function an earlier hook had already cleared; a cancel of an
outer running script threw into a coroutine still on the stack; ``True`` and
``1`` compared equal for ``@on_change``.

    python tests/run_tiers.py focused test_scheduler_order
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase  # noqa: E402

from scena import (  # noqa: E402
    Circle, Line, on_change, on_mode, tween, unregister_event, wait,
)

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class TestMoveReplaceKey(SystemTestCase, unittest.TestCase):
    """S2-7: a second timed move replaces the first whether or not anything
    read ``.center`` in between; ``tween(shape.center)`` shares the key."""
    world_draw = False

    def test_a_read_between_two_moves(self):
        for read_center in (False, True):
            with self.subTest(read_center=read_center):
                ln = self.w.track(Line(p1=(0, 0), p2=(10, 0)))
                h1 = ln.move_to(200, 0, time=1.0)
                self.w.step(6)
                if read_center:
                    _ = ln.center.x
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    ln.move_to(-200, 0, time=0.5)
                self.w.step(70)
                self.assertTrue(h1.cancelled)
                self.assertAlmostEqual((ln.p1.x + ln.p2.x) / 2, -200.0)

    def test_tween_of_the_center_replaces_a_move(self):
        c = self.w.track(Circle(center=(0, 0), radius=3))
        h1 = c.move_to(100, 0, time=1.0)
        self.w.step(3)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tween(c.center, (0, 50), time=0.2)
        self.assertTrue(h1.cancelled)


class TestUpdateFleetOrder(SystemTestCase, unittest.TestCase):
    """S2-9 / S2-10."""
    world_draw = False

    def test_on_update_runs_in_creation_order(self):
        order = []
        for i in range(40):
            c = self.w.track(Circle(center=(0, 0), radius=2))
            c.on_update = (lambda i: (lambda e, dt: order.append(i)))(i)
        self.w.step(1)
        self.assertEqual(order, list(range(40)))

    def test_a_cleared_on_update_does_not_run_later_that_frame(self):
        calls = []
        a = self.w.track(Circle(center=(0, 0), radius=3))
        b = self.w.track(Circle(center=(0, 0), radius=3))

        def a_update(e, dt):
            if self.w.frames_run == 3:
                b.on_update = None

        def b_update(e, dt):
            calls.append(self.w.frames_run)

        a.on_update = a_update
        b.on_update = b_update
        self.w.step(6)
        self.assertEqual(calls, [0, 1, 2])


class TestOuterScriptCancel(SystemTestCase, unittest.TestCase):
    """S2-11: ending an outer running mode from an inner one does not throw
    into the executing coroutine (``coroutine already executing``)."""
    world_draw = False

    def test_no_spurious_warning(self):
        log = []
        w = self.w

        class Boss(Circle):
            @on_mode
            async def call_minion(self):
                await wait(0.05)
                minion.mode = minion.relieve
                log.append(self.mode)
                await wait(1.0)
                log.append("after the end")      # never: the mode ended

        class Minion(Circle):
            @on_mode
            async def relieve(self):
                boss.mode = None
                await wait(1.0)

        boss = w.track(Boss(center=(0, 0), radius=5))
        minion = w.track(Minion(center=(0, 0), radius=5))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            boss.mode = boss.call_minion
            w.step(70)
        bad = [str(c.message) for c in caught
               if "Exception in cancelled async" in str(c.message)]
        self.assertEqual(bad, [])
        self.assertEqual(log, [None])


class TestOnChangeSeesBoolVersusNumber(SystemTestCase, unittest.TestCase):
    """S2-14: ``1 → True → 1.0 → 0 → False`` fires on every bool change;
    ``10 → 10.0`` does not fire."""
    world_draw = False

    def test_bool_changes_fire(self):
        seen = []
        box = {"v": 1}

        @on_change(lambda: box["v"])
        def changed(value):
            seen.append(value)
        self.addCleanup(unregister_event, changed)
        for new in (True, 1.0, 0, False, 0.0, 0):
            box["v"] = new
            self.w.step(1)
        self.assertEqual(seen, [True, 1.0, 0, False, 0.0])

    def test_int_to_float_is_not_a_change(self):
        seen = []
        box = {"v": 10}

        @on_change(lambda: box["v"])
        def changed(value):
            seen.append(value)
        self.addCleanup(unregister_event, changed)
        box["v"] = 10.0
        self.w.step(2)
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
