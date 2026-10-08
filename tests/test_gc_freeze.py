"""GC policy (scena/gc_policy.py): freeze the built world, thaw at act change.

Bug class guarded: **stranded by freeze**. Scena objects sit in reference
cycles, so a frozen object is reclaimed only after a thaw. Every act change
must thaw and collect, or each act's objects would pile up in the permanent
generation. Also: the policy must be a no-op when off (headless tests), and
``run()`` cleanup must thaw.

    python tests/run_tiers.py focused test_gc_freeze
"""
from __future__ import annotations

import gc
import os
import sys
import unittest
import weakref
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase, quiet  # noqa: E402

import scena.gc_policy as gc_policy  # noqa: E402
import scena.orchestration as orch  # noqa: E402
from scena import Circle, Entity, Rect, Text, collide  # noqa: E402
from scena.act import Act, change_act  # noqa: E402


class _PolicyOn:
    """Turn the policy on for one test (SystemWorld turns it off)."""

    def setUp(self):
        super().setUp()
        gc_policy.set_gc_freeze(True)
        self.addCleanup(gc_policy.thaw_world)
        self.addCleanup(gc_policy.set_gc_freeze, False)


REFS: list = []


class Busy(Act):
    """An act whose objects all need the cyclic GC once destroyed."""

    def setup(self):
        self.pieces = [Circle(center=(i * 12, 40), radius=4, group="bola") for i in range(20)]
        r = Rect(width=10, height=10)
        c = Circle(radius=2)
        c.center @= lambda: r.center
        e = Entity()
        e.every(0.05, lambda: None)
        t = Text(text="placar")

        @collide("bola", "bola")
        def bump(a, b):
            pass

        REFS[:] = [weakref.ref(o) for o in (*self.pieces, r, c, e, t, self)]


class Calm(Act):
    def setup(self):
        pass


class TestGcFreeze(_PolicyOn, SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_begin_game_freezes_the_built_world(self):
        with quiet():
            for i in range(10):
                Circle(center=(i, i), radius=3)
        self.w.begin_game()
        self.assertTrue(gc_policy.world_frozen())
        self.assertGreater(gc.get_freeze_count(), 0)

    def test_act_change_collects_the_old_act(self):
        self.w.begin_game(Busy)
        self.assertTrue(gc_policy.world_frozen())
        self.w.step(3)
        self.assertTrue(all(r() is not None for r in REFS))
        change_act(Calm)
        # No explicit gc.collect(): the change thawed, collected, re-froze.
        alive = [type(r()).__name__ for r in REFS if r() is not None]
        self.assertEqual(alive, [], f"stranded after change_act: {alive}")
        self.assertTrue(gc_policy.world_frozen())

    def test_setup_object_destroyed_in_play_waits_for_the_next_thaw(self):
        """The documented cost: bounded (it was alive at the freeze), reclaimed
        at the next act change."""
        self.w.begin_game(Busy)
        victim = REFS[0]
        with quiet():
            victim().destroy()
        self.w.step(2)
        gc.collect()
        self.assertIsNotNone(victim(), "expected: frozen until the next thaw")
        change_act(Calm)
        self.assertIsNone(victim())

    def test_thaw_is_only_undo(self):
        gc_policy.thaw_world()
        self.assertFalse(gc_policy.thaw_world())  # nothing frozen: no-op
        count = gc.get_freeze_count()
        self.assertFalse(gc_policy.world_frozen())
        self.assertEqual(gc.get_freeze_count(), count)


class TestGcFreezeOff(SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_policy_off_never_touches_gc(self):
        self.assertFalse(gc_policy.gc_freeze_enabled())  # SystemWorld default
        with mock.patch.object(gc, "freeze") as freeze, \
                mock.patch.object(gc, "unfreeze") as unfreeze:
            self.w.begin_game(Busy)
            change_act(Calm)
        freeze.assert_not_called()
        unfreeze.assert_not_called()
        self.assertFalse(gc_policy.world_frozen())


class TestCleanupThaws(unittest.TestCase):
    def test_run_cleanup_unfreezes(self):
        gc_policy.set_gc_freeze(True)
        try:
            self.assertTrue(gc_policy.freeze_world())
            fw = orch.ScenaFramework.get_instance()
            saved = fw._context
            fw._context = None
            try:
                with mock.patch.object(orch.glfw, "terminate"):
                    fw._cleanup()
            finally:
                fw._context = saved
            self.assertFalse(gc_policy.world_frozen())
        finally:
            gc_policy.thaw_world()
            gc_policy.set_gc_freeze(True)


if __name__ == "__main__":
    unittest.main()
