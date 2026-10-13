"""A rejected call leaves no trace (review 2026-10-09, root cause R6).

Bug class: **a rejected call half-applies**. A refusal checked late, after
some of the work was done: the same-property replace cancelled the job in
flight before ``time=-1`` was refused, a list side registered its first pairs
before a later member was refused, a two-slot setter wrote one slot before
the other refused. Also the engine variant: a deferred switch (a sprite's
``next=``) with no call site raised from whatever read it first, the draw
included, and a raising ``on_done`` lost the other sounds that ended in the
same frame.

    python tests/run_tiers.py focused test_rejected_calls_leave_no_trace
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase, quiet, tone  # noqa: E402

from scena import (  # noqa: E402
    Circle, Rect, Sheet, Sprite, collide, play_sound, resolve, tween,
)
from scena.collision import get_collision_system  # noqa: E402
from scena.state import LinkedAttributeError  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402
from tests.test_sprite import _write_rect_png  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class TestRejectedTimedVerbs(SystemTestCase, unittest.TestCase):
    """S2-5: every refusal ``_start_tween`` makes runs before the verb
    touches the job in flight or snaps the heading."""
    world_draw = False

    CASES = (
        ("move_to", lambda c: c.move_to(300, 0, time=1), lambda c: c.move_to(0, 300, time=-1)),
        ("move_by", lambda c: c.move_by(300, 0, time=1),
         lambda c: c.move_by(0, 300, time=1, ease="nope")),
        ("move_by heading face", lambda c: c.move_by(300, 0, time=1),
         lambda c: c.move_by(distance=-300, time=1, face=True)),
        ("rotate_to", lambda c: c.rotate_to(90, time=1), lambda c: c.rotate_to(10, time=-1)),
        ("rotate_by", lambda c: c.rotate_by(90, time=1),
         lambda c: c.rotate_by(10, time=1, on_done=5)),
        ("scale_to", lambda c: c.scale_to(2, time=1), lambda c: c.scale_to(3, time=-1)),
        ("scale_by", lambda c: c.scale_by(2, time=1), lambda c: c.scale_by(3, time=float("nan"))),
        ("tween", lambda c: tween(c["width"], 100, time=1),
         lambda c: tween(c["width"], 50, time=-1)),
        ("move_to speed", lambda c: c.move_to(300, 0, time=1), lambda c: c.move_to(0, 300, speed=0)),
        ("move_by speed", lambda c: c.move_by(300, 0, time=1),
         lambda c: c.move_by(0, 300, time=1, speed=5)),
        ("rotate_to speed", lambda c: c.rotate_to(90, time=1),
         lambda c: c.rotate_to(10, speed=float("nan"))),
        ("rotate_by speed", lambda c: c.rotate_by(90, time=1), lambda c: c.rotate_by(10, speed=-1)),
        ("move_along speed", lambda c: c.move_along("circle", time=1),
         lambda c: c.move_along("circle", speed=0)),
    )

    def test_a_rejected_call_keeps_the_job_in_flight(self):
        c = self.w.track(Rect(center=(0, 0), width=20, height=10))
        for name, start, bad in self.CASES:
            with self.subTest(verb=name):
                h = start(c)
                self.w.step(3)
                with self.assertRaises((TypeError, ValueError)):
                    bad(c)
                self.assertFalse(h.cancelled, f"rejected {name} cancelled the {name} in flight")
                h.cancel()

    def test_a_rejected_face_move_does_not_turn(self):
        c = self.w.track(Rect(center=(0, 0), width=20, height=10))
        before = c.angle
        with self.assertRaises(ValueError):
            c.move_to(0, 300, time=-1, face=True)
        self.assertEqual(c.angle, before)
        # face= with the heading as the direction is refused before the snap.
        with self.assertRaises(TypeError):
            c.move_by(distance=-300, time=1, face=True)
        self.assertEqual(c.angle, before)

    def test_then_on_an_actor_verb_still_works(self):
        # The early check must not refuse what ``_start_tween`` accepts: an
        # actor's own verb has an owner for ``then=``.
        c = self.w.track(Rect(center=(0, 0), width=20, height=10))

        def parado(me):
            pass

        h = c.move_to(10, 0, time=0.05, then=parado)
        self.w.seconds(0.1)
        self.assertTrue(h.done)


class TestRejectedListSides(SystemTestCase, unittest.TestCase):
    """S8-1: a list side is all-or-nothing; a ``ui`` member in the last
    slot left the earlier pairs live."""
    world_draw = False

    def test_collide_with_a_refused_member_registers_nothing(self):
        cs = get_collision_system()
        hero = self.w.track(Circle(center=(0, 0), radius=10))
        hud = self.w.track(Circle(center=(0, 0), radius=10, layer="ui"))
        wall = self.w.track(Circle(center=(5, 0), radius=10, group="rl_wall"))
        before = (list(cs._pair_handlers), set(cs._pair_tags), list(cs._colliders))
        hits = []
        with self.assertRaises(Exception) as cm:
            @collide([hero, hud], "rl_wall")
            def bate(a, b, info):
                hits.append(1)
        self.assertEqual(type(cm.exception).__name__, "UiLayerError")
        self.assertEqual((list(cs._pair_handlers), set(cs._pair_tags), list(cs._colliders)),
                         before)
        self.w.step(2)
        self.assertEqual(hits, [])
        self.assertIsNone(wall._collider)

    def test_resolve_with_a_refused_member_registers_nothing(self):
        cs = get_collision_system()
        hero = self.w.track(Circle(center=(0, 0), radius=10))
        hud = self.w.track(Circle(center=(0, 0), radius=10, layer="ui"))
        self.w.track(Circle(center=(5, 0), radius=10, group="rl_floor"))
        with self.assertRaises(Exception):
            resolve([hero, hud], "rl_floor")
        self.assertEqual(cs._resolve_pairs, [])
        self.assertNotIn("rl_floor", cs._pair_tags)

    def test_a_bad_bounce_refuses_before_any_pair(self):
        cs = get_collision_system()
        a = self.w.track(Circle(center=(0, 0), radius=10))
        b = self.w.track(Circle(center=(50, 0), radius=10))
        with self.assertRaises((TypeError, ValueError)):
            resolve([a, b], "rl_any", bounce="muito")
        self.assertEqual(cs._resolve_pairs, [])


class _SheetCase(SystemTestCase, unittest.TestCase):
    world_draw = True

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.small = os.path.join(self.tmp, "a.png")
        self.big = os.path.join(self.tmp, "b.png")
        _write_rect_png(self.small, 32, 32)
        _write_rect_png(self.big, 64, 32)

    def sheet(self):
        sheet = Sheet([self.small, self.small, self.big], fps=60)
        sheet.clip("walk", [0, 1], fps=10)
        sheet.clip("hit", [0, 1], fps=60)
        sheet.clip("wide", [2], fps=60)
        return sheet


class TestRejectedSpriteSize(_SheetCase):
    """S7-5 / S7-6: both size slots are checked before either is written."""

    def test_size_with_a_linked_height_changes_nothing(self):
        ref = self.w.track(Circle(center=(0, 0), radius=16))
        hero = self.w.track(Sprite(self.sheet(), frame=2, center=(0, 0)))
        hero["height"] @= lambda: ref.radius * 2
        before = (float(hero.width), float(hero.height))
        with self.assertRaises(LinkedAttributeError):
            hero.size = 128
        self.assertEqual((float(hero.width), float(hero.height)), before)

    def test_frame_with_a_linked_width_keeps_the_clip(self):
        ref = self.w.track(Circle(center=(0, 0), radius=16))
        hero = self.w.track(Sprite(self.sheet(), frame=0, center=(0, 0)))
        hero["width"] @= lambda: ref.radius * 2
        hero.play("walk")
        with self.assertRaises(LinkedAttributeError):
            hero.frame = 2                      # a wider cell
        self.assertEqual((hero._play_name, hero.frame), ("walk", 0))


class TestDeferredClipSwitch(_SheetCase):
    """S7-7: a ``next=`` switch has no call site to refuse at. It happens in
    the simulation (``settle_clip_ends``), never first in the draw, and a
    linked size keeps its link."""

    def test_a_linked_width_keeps_its_link_and_nothing_raises(self):
        ref = self.w.track(Circle(center=(0, 0), radius=16))
        hero = self.w.track(Sprite(self.sheet(), frame=0, center=(0, 0)))
        hero.play("hit", loops=1, next="wide")
        hero["width"] @= lambda: ref.radius * 2      # linked after the play gate
        self.w.step(5)                               # draws too
        self.assertEqual(hero._play_name, "wide")
        self.assertAlmostEqual(float(hero.width), 32.0)

    def test_the_switch_happens_before_the_draw(self):
        hero = self.w.track(Sprite(self.sheet(), frame=0, center=(0, 0)))
        w0 = float(hero.width)
        hero.play("hit", loops=1, next="wide")
        self.w.step(5, draw=False)                   # nothing reads the frame
        self.assertEqual(hero._play_name, "wide", "no reader: the clip never ended")
        self.assertAlmostEqual(float(hero.width), 2 * w0, msg="the wide cell's size")

    def test_the_end_follows_time_scale(self):
        hero = self.w.track(Sprite(self.sheet(), frame=0, center=(0, 0)))
        hero.play("hit", loops=1, next="wide")      # 2 cells at 60 fps: 1/30 s
        hero.time_scale = 0.25                       # now 4/30 s
        self.w.step(4, draw=False)
        self.assertEqual(hero._play_name, "hit")
        self.w.step(6, draw=False)
        self.assertEqual(hero._play_name, "wide")

    def test_a_frozen_clip_waits_and_a_thaw_reschedules(self):
        hero = self.w.track(Sprite(self.sheet(), frame=0, center=(0, 0)))
        hero.play("hit", loops=1, next="wide")
        hero.time_scale = 0
        self.w.step(10, draw=False)
        self.assertEqual(hero._play_name, "hit")
        hero.time_scale = 1
        self.w.step(4, draw=False)
        self.assertEqual(hero._play_name, "wide")

    def test_frame_set_drops_the_scheduled_end(self):
        from scena import sprite as sprite_mod
        hero = self.w.track(Sprite(self.sheet(), frame=0, center=(0, 0)))
        hero.play("hit", loops=1, next="wide")
        hero.frame = 1
        self.w.step(5, draw=False)
        self.assertEqual((hero._play_name, hero.frame), (None, 1))
        self.assertFalse([e for e in sprite_mod._CLIP_DUE if e[2]() is hero],
                         "a stopped clip stays scheduled")

    def test_destroyed_long_clips_do_not_pile_up(self):
        from scena import sprite as sprite_mod
        sheet = self.sheet()
        for _ in range(400):
            sp = Sprite(sheet, frame=0, center=(0, 0))
            sp.play("walk", loops=10000)
            sp.destroy()
            self.w.step(1, draw=False)
        self.assertLessEqual(len(sprite_mod._CLIP_DUE), 2 * 256 + 1)


class TestRaisingSoundDone(SystemTestCase, unittest.TestCase):
    """S2-13: a raising ``on_done`` does not lose the other sounds that
    ended in the same frame."""
    world_draw = False

    def test_the_other_finished_sound_still_completes(self):
        done = []

        def boom():
            raise RuntimeError("author bug in on_done")

        h1 = play_sound(tone(0.2), on_done=boom)
        h2 = play_sound(tone(0.2), on_done=lambda: done.append("h2"))
        caught = 0
        for _ in range(60):
            try:
                self.w.step(1)
            except RuntimeError:
                caught += 1
        self.assertEqual(caught, 1)
        self.assertTrue(h1.done)
        self.assertTrue(h2.done, "h2 never completed")
        self.assertEqual(done, ["h2"])


if __name__ == "__main__":
    unittest.main()
