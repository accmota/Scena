"""System frame-order suite: the datapath across subsystems, one real frame at a time.

Scena Design § Frame order: ``update`` → processes → collision → leave
playfield → ``flush`` (``@when`` / ``@on_change``) → pre-draw ticks
(transients / history / cover / SpatialFx) → draw. The frame batch stays open
through the pre-draw ticks, so their writes reach ``@when`` at the **next**
flush. These tests drive ``ScenaFramework._simulate_frame`` (the body ``run()``
uses) and check the order, the handoffs between phases, glitch-freedom across
subsystems, recovery from an author error mid-frame, and that the headless
driver and the real ``run()`` loop produce the same phase trace.

    python -m unittest tests.test_sys_frame_order -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase, quiet  # noqa: E402

from scena import (  # noqa: E402
    Circle, Entity, after, canvas, clock, collide, every, leave_playfield, on_change, when,
)
from scena.state import get_scena_system  # noqa: E402

CANON = ["update", "process", "collision", "leave", "flush", "pre_draw", "draw"]


class PhaseRig:
    """Author hooks in every phase, all firing in one chosen frame."""

    def __init__(self, testcase: SystemTestCase):
        self.t = testcase
        self.w = w = testcase.w
        self.log = []
        fw = w.fw
        real_pre, real_draw = fw._tick_pre_draw, fw._draw_frame

        def pre():
            real_pre()
            self.log.append((clock.frame, "pre_draw_end"))

        def draw():
            self.log.append((clock.frame, "draw"))
            real_draw()

        for attr, fn in (("_tick_pre_draw", pre), ("_draw_frame", draw)):
            p = mock.patch.object(fw, attr, side_effect=fn)
            p.start()
            testcase.addCleanup(p.stop)

    def mark(self, phase):
        self.log.append((clock.frame, phase))

    def phases(self, frame):
        seen = []
        for f, p in self.log:
            if f == frame and p not in seen:
                seen.append(p)
        return seen


class TestCanonicalOrder(SystemTestCase, unittest.TestCase):

    def test_every_phase_in_documented_order(self):
        rig = PhaseRig(self)
        w = self.w
        N = 8  # the frame where everything happens
        hero = self.track(Circle(center=(0, 0), radius=8, group="hero"))
        rock = self.track(Circle(center=(300, 0), radius=8, group="rock"))
        hero.n = 0

        @collide("hero", "rock")
        def _hit(a, b, info=None):
            rig.mark("collision")

        @leave_playfield("rock")
        def _gone(item):
            rig.mark("leave")

        @on_change(lambda: hero.n)
        def _changed():
            rig.mark("flush")

        def update(dt):
            if clock.frame == N - 4:
                # 0.06 s (flash floor is 0.05 s): ends inside frame N's
                # pre-draw tick — world time is pinned to 1/60 steps.
                hero.flash(0.06, on_done=lambda: rig.mark("pre_draw"))
            if clock.frame == N:
                rig.mark("update")
                rock.move_to(hero.center)          # collides this frame
                hero.n += 1                        # @on_change at this flush

        w.on_update(update)
        hero.on_update = lambda e, dt: rig.mark("process") if clock.frame == N else None
        # A second body leaves the playfield in the same frame.
        leaver = self.track(Circle(center=(0, 0), radius=2, group="rock"))
        w.step(N - 1)
        leaver.move_to(99999, 0)
        w.step(1)
        got = [p for p in rig.phases(N) if p != "pre_draw_end"]
        self.assertEqual(got, CANON, f"phase order in frame {N}")

    def test_order_is_stable_over_many_frames(self):
        """Every frame, the same phases run in the same relative order."""
        rig = PhaseRig(self)
        w = self.w
        a = self.track(Circle(center=(0, 0), radius=8))
        b = self.track(Circle(center=(0, 0), radius=8))
        b.collidable = True  # a partner for a's ANYTHING interest
        a.n = 0
        a.on_collide_stay = lambda *args: rig.mark("collision")
        a["n2"] @= (lambda: b.radius)

        @on_change(lambda: a.n)
        def _changed():
            rig.mark("flush")

        def update(dt):
            rig.mark("update")
            a.n += 1

        w.on_update(update)
        a.on_update = lambda e, dt: rig.mark("process")
        w.step(40)
        for f in range(3, 40):
            got = [p for p in rig.phases(f) if p in CANON]
            self.assertEqual(got, ["update", "process", "collision", "flush", "draw"],
                             f"frame {f}")


class TestHandoffs(SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_timer_started_in_collision_handler_first_ticks_next_frame(self):
        w = self.w
        a = self.track(Circle(center=(0, 0), radius=8, group="a"))
        self.track(Circle(center=(0, 0), radius=8, group="b"))
        frames = {}

        @collide("a", "b")
        def _hit(x, y, info=None):
            frames["hit"] = clock.frame
            after(0, lambda: frames.setdefault("after0", clock.frame))
            every(1e-4, lambda: frames.setdefault("every", clock.frame))

        w.step(4)
        self.assertEqual(frames["after0"], frames["hit"] + 1)
        self.assertEqual(frames["every"], frames["hit"] + 1)

    def test_pre_draw_write_reaches_when_next_flush_exactly_once(self):
        w = self.w
        a = self.track(Circle(center=(0, 0), radius=8))
        a.hp = 5
        fired = []

        @when(lambda: a.hp <= 0)
        def _dead():
            fired.append(clock.frame)

        done = {}

        def on_done():
            done["frame"] = clock.frame
            a.hp = 0  # write during the pre-draw tick, batch still open

        a.flash(0.05, on_done=on_done)
        w.step(10)
        self.assertIn("frame", done)
        self.assertEqual(fired, [done["frame"] + 1],
                         "pre-draw write must fire @when at the next flush, once")

    def test_actor_spawned_in_update_collides_same_frame(self):
        w = self.w
        self.track(Circle(center=(0, 0), radius=8, group="wall"))
        frames = {}

        @collide("shot", "wall")
        def _hit(s, wall, info=None):
            frames.setdefault("hit", clock.frame)

        def update(dt):
            if clock.frame == 3:
                frames["spawn"] = clock.frame
                self.track(Circle(center=(0, 0), radius=3, group="shot"))

        w.on_update(update)
        w.step(5)
        self.assertEqual(frames["hit"], frames["spawn"])

    def test_actor_spawned_by_timer_collides_same_frame(self):
        w = self.w
        self.track(Circle(center=(0, 0), radius=8, group="wall"))
        frames = {}

        @collide("shot", "wall")
        def _hit(s, wall, info=None):
            frames.setdefault("hit", clock.frame)

        def spawn():
            frames["spawn"] = clock.frame
            self.track(Circle(center=(0, 0), radius=3, group="shot"))

        after(0.05, spawn)
        w.step(10)
        self.assertEqual(frames["hit"], frames["spawn"])


class TestGlitchFreeAcrossSubsystems(SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_handlers_see_linked_geometry_consistent_with_its_source(self):
        """A tween moves A; B's center is linked to A. Every handler that runs
        in the flush window (collision, @on_change) sees B == f(A)."""
        w = self.w
        a = self.track(Circle(center=(0, 0), radius=6, group="a"))
        b = self.track(Circle(center=(10, 0), radius=3))
        b["center"] @= (lambda: (a.center.x + 10, a.center.y * 2))
        self.track(Circle(center=(60, 0), radius=30, group="zone"))
        bad = []

        def check(where):
            want = (a.center.x + 10, a.center.y * 2)
            got = (b.center.x, b.center.y)
            if abs(got[0] - want[0]) > 1e-9 or abs(got[1] - want[1]) > 1e-9:
                bad.append((where, clock.frame, got, want))

        @collide("a", "zone")
        def _in(x, y, info=None):
            check("collide")

        a.on_collide_stay = lambda *args: check("stay")

        @on_change(lambda: a.center.x)
        def _moved():
            check("on_change")

        a.move_to(120, 30, time=1.0)
        w.on_update(lambda dt: check("update"))
        w.seconds(1.2)
        self.assertEqual(bad, [])


class TestAuthorErrorMidFrame(SystemTestCase, unittest.TestCase):
    """A raising author hook propagates; the frame closes; the next frame is sane."""
    world_draw = False

    def _assert_recovers(self, arm):
        w = self.w
        ticks = []
        e = self.track(Entity())
        e.every(1e-4, lambda: ticks.append(clock.frame))
        arm()
        with quiet():
            with self.assertRaises(RuntimeError):
                w.step(10)
        ss = get_scena_system()
        self.assertFalse(ss.update_manager.deferring, "frame batch left open")
        n = len(ticks)
        w.step(3)
        self.assertGreater(len(ticks), n, "frames after the error do not run")

    def test_collision_handler_raises(self):
        hits = []

        def arm():
            self.track(Circle(center=(0, 0), radius=5, group="x"))
            self.track(Circle(center=(0, 0), radius=5, group="y"))

            @collide("x", "y")
            def _boom(a, b, info=None):
                hits.append(clock.frame)
                raise RuntimeError("boom")

        self._assert_recovers(arm)
        self.w.step(5)
        self.assertEqual(len(hits), 1, "contact committed before the handler: no re-enter")

    def test_when_raises(self):
        def arm():
            e = self.track(Entity())
            e.v = 0
            after(0.05, lambda: setattr(e, "v", 1))

            @when(lambda: e.v > 0)
            def _boom():
                raise RuntimeError("boom")

        self._assert_recovers(arm)

    def test_timer_raises(self):
        def arm():
            after(0.05, lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        self._assert_recovers(arm)

    def test_update_raises(self):
        def arm():
            def update(dt):
                if clock.frame == 3:
                    raise RuntimeError("boom")
            self.w.on_update(update)

        self._assert_recovers(arm)


class TestDriverMatchesRunLoop(unittest.TestCase):
    """Drift guard: ``world.step`` and the real ``run()`` loop run the same
    frame body, so a mini game yields the same per-frame phase sequence."""

    @staticmethod
    def _build(log):
        """The mini game (built inside the driver's world)."""
        from scena import Circle as C
        a = C(center=(0, 0), radius=8)
        b = C(center=(0, 0), radius=8)
        b.collidable = True
        a.n = 0
        a.on_collide_stay = lambda *args: log.append((clock.frame, "collision"))
        a.on_update = lambda e, dt: log.append((clock.frame, "process"))

        @on_change(lambda: a.n)
        def _changed():
            log.append((clock.frame, "flush"))

        def update(dt, *_):
            log.append((clock.frame, "update"))
            a.n += 1

        return (a, b), update

    def _trace(self, drive):
        log = []
        drive(log)
        per = {}
        for f, p in log:
            per.setdefault(f, []).append(p)
        return [tuple(v) for _f, v in sorted(per.items())][2:]

    def test_same_phase_trace(self):
        from system_support import system_world
        from test_run_loop import RunLoopTestCase

        def headless(log):
            with system_world() as w:
                objs, update = self._build(log)
                for o in objs:
                    w.track(o)
                fw = w.fw
                real = fw._draw_frame
                with mock.patch.object(fw, "_draw_frame",
                                       side_effect=lambda: (log.append((clock.frame, "draw")), real())):
                    w.on_update(update)
                    w.step(8)

        class _Run(RunLoopTestCase):
            def runTest(self):
                pass

        def real_loop(log):
            rl = _Run()
            rl.setUp()
            objs = ()
            try:
                objs, update = self._build(log)
                fw = rl.fw
                fw.update = update
                real = fw._draw_frame
                with mock.patch.object(fw, "_draw_frame",
                                       side_effect=lambda: (log.append((clock.frame, "draw")), real())):
                    rl.run_frames(8)
            finally:
                with quiet():
                    for o in objs:
                        o.destroy()
                rl.tearDown()
                rl.doCleanups()

        a = self._trace(headless)
        b = self._trace(real_loop)
        self.assertTrue(a)
        self.assertEqual(a, b[:len(a)])
        self.assertEqual(a[0], ("update", "process", "collision", "flush", "draw"))


if __name__ == "__main__":
    unittest.main()
