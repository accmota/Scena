"""Slice 1–3 process system: after / every / mode / tween / async await / on_update /
on_mode / exit_mode / on_destroy.

Run headless:

    python -m unittest tests.test_process -v
"""

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    Circle, Color, Entity, Line, Rect, after, every, tween, wait, until, until_empty,
    parallel, race, on_mode, exit_mode,
    clock, ready, recently, Handle, when, on_change, flush, group, Sprite, collide_with,
)
from scena.process import (
    Cancelled,
    FROZEN_MODE_S,
    SCOPE_ENTITY,
    clear_author_error,
    get_scheduler,
    last_author_error,
    owning,
    reset_process_scheduler,
    tick_processes,
    shortest_delta_deg,
)
from scena.state import Attribute, LinkedAttributeError
from scena.events import cleanup_global_event_system
from scena.shapes import Shape, Polygon

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


class ProcessTestCase(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        clock._frame = 0
        self._owned = []
        # Fresh ready() / recently() bags (globals persist across tests).
        ready._timers.clear()
        recently._slots.clear()

    def tearDown(self):
        for obj in self._owned:
            try:
                if getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_process_scheduler()
        try:
            from scena.canvas import ScenaCanvas
            ScenaCanvas.get_current().registry.clear_group_formulas()
        except Exception:
            pass

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestAfterEvery(ProcessTestCase):
    def test_after_fires_once(self):
        n = []
        h = after(0.25, lambda: n.append(1))
        self.assertIsInstance(h, Handle)
        self.assertFalse(h.done)
        _frame(0.1)
        self.assertEqual(n, [])
        _frame(0.2)
        self.assertEqual(n, [1])
        self.assertTrue(h.done)
        _frame(0.5)
        self.assertEqual(n, [1])

    def test_after_zero_fires_next_tick(self):
        n = []
        after(0.0, lambda: n.append(1))
        self.assertEqual(n, [])
        _frame(0.01)
        self.assertEqual(n, [1])

    def test_every_repeats(self):
        n = []
        h = every(0.2, lambda: n.append(1))
        _frame(0.1)
        self.assertEqual(n, [])
        _frame(0.1)
        self.assertEqual(n, [1])
        _frame(0.2)
        self.assertEqual(n, [1, 1])
        h.cancel()
        _frame(0.5)
        self.assertEqual(n, [1, 1])
        self.assertTrue(h.cancelled)

    def test_named_timer_replaces(self):
        n = []
        every(1.0, lambda: n.append("a"), name="spawn")
        every(0.2, lambda: n.append("b"), name="spawn")
        _frame(0.2)
        self.assertEqual(n, ["b"])
        _frame(0.2)
        self.assertEqual(n, ["b", "b"])
        self.assertNotIn("a", n)

    def test_after_and_every_reject_nonfinite_and_negative(self):
        with self.assertRaises(ValueError):
            after(float("nan"), lambda: None)
        with self.assertRaises(ValueError):
            after(float("inf"), lambda: None)
        with self.assertRaises(ValueError):
            after(-0.1, lambda: None)
        with self.assertRaises(ValueError):
            every(float("nan"), lambda: None)
        with self.assertRaises(ValueError):
            every(float("inf"), lambda: None)
        with self.assertRaises(ValueError):
            every(-1.0, lambda: None)
        h = after(0.0, lambda: None)
        self.assertEqual(h.delay, 0.0)
        h.cancel()

    def test_every_nonpositive_points_at_frame_hooks(self):
        for interval in (0, 0.0, -0.1):
            with self.subTest(interval=interval):
                with self.assertRaises(ValueError) as ctx:
                    every(interval, lambda: None)
                msg = str(ctx.exception)
                self.assertIn("interval must be > 0", msg)
                self.assertIn("on_update", msg)
                self.assertIn("update(dt)", msg)

    def test_after_non_callable_raises(self):
        with self.assertRaises(TypeError) as ctx:
            after(0.1, "diving")
        self.assertIn("expected a function", str(ctx.exception))

    def test_every_callback_exception_propagates(self):
        n = []

        def boom():
            n.append(1)
            raise RuntimeError("author bug")

        h = every(0.1, boom)
        with self.assertRaisesRegex(RuntimeError, "author bug"):
            _frame(0.1)
        self.assertEqual(len(n), 1)
        self.assertIsNone(last_author_error())  # not recorded: it raised
        self.assertAlmostEqual(h.elapsed, 0.0)  # interval consumed before firing
        self.assertFalse(get_scheduler()._iterating)

    def test_after_callback_exception_propagates(self):
        n = []

        def boom():
            n.append(1)
            raise RuntimeError("author bug")

        h = after(0.1, boom)
        with self.assertRaisesRegex(RuntimeError, "author bug"):
            _frame(0.1)
        self.assertEqual(n, [1])
        self.assertTrue(h.done)  # completed before the callback ran
        self.assertFalse(get_scheduler()._iterating)

    def test_then_needs_owner(self):
        def diving():
            pass
        with self.assertRaises(TypeError) as ctx:
            after(0.1, then=diving)
        self.assertIn("then=", str(ctx.exception))
        self.assertIn("owner", str(ctx.exception))
        # Top-of-file is "script level": messages never say "scene" (rendered frame only).
        self.assertIn("Script-level after(..., then=)", str(ctx.exception))
        self.assertNotIn("scene", str(ctx.exception).lower())

    def test_then_exclusive_with_fn(self):
        c = self.track(Circle())
        def diving(e):
            pass
        with self.assertRaises(TypeError) as ctx:
            c.after(0.1, lambda: None, then=diving)
        self.assertIn("not both", str(ctx.exception))

    def test_decorator_after(self):
        n = []

        @after(0.15)
        def boom():
            n.append(1)

        self.assertIsInstance(boom.handle, Handle)
        _frame(0.2)
        self.assertEqual(n, [1])
        self.assertTrue(boom.handle.done)

    def test_decorator_every(self):
        n = []

        @every(0.1, name="tick")
        def pulse():
            n.append(1)

        self.assertIsInstance(pulse.handle, Handle)
        _frame(0.1)
        _frame(0.1)
        self.assertEqual(n, [1, 1])

    def test_decorator_every_handle_cancel(self):
        n = []

        @every(0.1)
        def pulse():
            n.append(1)

        pulse.handle.cancel()
        _frame(0.1)
        _frame(0.1)
        self.assertEqual(n, [])
        self.assertTrue(pulse.handle.cancelled)

    def test_decorator_named_replace_updates_handle(self):
        n = []

        @every(1.0, name="spawn")
        def drop():
            n.append("a")

        old = drop.handle
        every(0.2, drop, name="spawn")
        self.assertIsNot(drop.handle, old)
        self.assertTrue(old.cancelled)
        self.assertIs(drop.handle, drop.handle)
        _frame(0.2)
        self.assertEqual(n, ["a"])
        drop.handle.cancel()
        _frame(0.5)
        self.assertEqual(n, ["a"])

    def test_cancel_twice_is_safe(self):
        h = after(1.0, lambda: None)
        h.cancel()
        h.cancel()
        self.assertTrue(h.cancelled)
        self.assertTrue(h.done)

    def test_scheduler_usable_after_callback_raises(self):
        n = []

        def boom():
            raise RuntimeError("author bug")

        after(0.1, boom)
        after(0.1, lambda: n.append(1))
        with self.assertRaises(RuntimeError):
            _frame(0.1)
        self.assertEqual(n, [])  # later work waits for the next tick
        tick_processes()
        self.assertEqual(n, [1])

    def test_await_on_finished_handle(self):
        n = []
        h = after(0.05, lambda: n.append(1))
        _frame(0.1)
        self.assertTrue(h.done)
        gen = h.__await__()
        with self.assertRaises(StopIteration):
            next(gen)

    def test_await_pending_yields_until_done(self):
        h = after(0.2, lambda: None)
        gen = h.__await__()
        yielded = next(gen)
        self.assertIs(yielded, h)
        _frame(0.25)
        with self.assertRaises(StopIteration):
            next(gen)


class TestDueOnTheExactFrame(ProcessTestCase):
    """Bug PM8: a timer whose time is a whole number of frames fired one frame
    late or on time depending on float rounding. 15 steps of 1/60 sum to
    0.24999999999999997 < 0.25, so ``after(0.25)`` at 60 fps fired at frame 16
    while ``after(0.9)`` fired at frame 54. Every "is it due" comparison on
    accumulated time (after / every / tween end / ready / recently) now uses
    ``process.reached`` (a 1e-9 relative tolerance, far below any frame).
    The property covers the class: any fps, any k, the k-th frame."""

    FPS = (24, 30, 50, 60, 120, 144)

    def _frames_until(self, fired, dt, limit=400):
        for n in range(1, limit):
            _frame(dt)
            if fired():
                return n
        return None

    def test_after_every_tween_ready_recently_on_frame_k(self):
        import itertools
        for fps, k in itertools.product(self.FPS, (1, 2, 3, 7, 12, 15, 24, 30, 45, 54, 90)):
            dt = 1.0 / fps
            secs = k * (1.0 / fps)       # what an author writes as k / fps
            secs = round(secs, 6) if abs(round(secs, 6) * fps - k) < 1e-9 else secs
            with self.subTest(fps=fps, k=k, secs=secs):
                self.tearDown()
                self.setUp()
                hit = []
                after(secs, lambda: hit.append(1))
                self.assertEqual(self._frames_until(lambda: hit, dt), k, "after")

                self.tearDown()
                self.setUp()
                ticks = []
                every(secs, lambda: ticks.append(clock.frame))
                for _ in range(3 * k):
                    _frame(dt)
                self.assertEqual(len(ticks), 3, f"every fired at {ticks}")

                self.tearDown()
                self.setUp()
                c = self.track(Circle(center=(0, 0), radius=1))
                c.move_to(100, 0, time=secs)
                self.assertEqual(self._frames_until(lambda: abs(c.center.x - 100) < 1e-9, dt), k,
                                 "tween end")

                from scena.transients import _progress
                t = 0.0
                for _ in range(k):
                    t += dt
                self.assertEqual(_progress(0.0, secs, t), 1.0, "transient progress")

                self.tearDown()
                self.setUp()
                self.assertTrue(ready("pm8", secs))
                got = self._frames_until(lambda: ready("pm8"), dt)
                self.assertEqual(got, k, "ready")

                self.tearDown()
                self.setUp()
                self.assertTrue(recently("pm8", True, hold=secs))
                for n in range(1, k + 1):
                    _frame(dt)
                    self.assertTrue(recently("pm8", False, hold=secs), f"recently at frame {n}")
                _frame(dt)
                self.assertFalse(recently("pm8", False, hold=secs), "recently past the hold")


class TestATweenEndsBeforeATimerOfItsLength(ProcessTestCase):
    """R4-1 (persona probes, round 4): the tick walked timers before tweens,
    so ``after(2, nxt)`` made with ``move_to(…, time=2)`` saw the move one
    step short (295 / 297.5 / 298.96 at 30 / 60 / 144 Hz), and a move on the
    same field started in ``nxt`` replaced the first in flight: its
    ``on_done`` never ran. Tweens now tick first (Laws T1). The class: every
    tween door × ``after`` / ``every`` × rates × lengths."""

    FPS = (24, 30, 60, 144)

    def _doors(self):
        from scena import st
        c = self.track(Circle(center=(0, 0), radius=1))
        st.r41 = 0.0
        return [
            ("move_to", lambda done: c.move_to(300, 0, time=self.secs, on_done=done),
             lambda: c.center.x, 300.0),
            ("rotate_to", lambda done: c.rotate_to(90, time=self.secs, on_done=done),
             lambda: c.angle, 90.0),
            ("tween st", lambda done: tween(st["r41"], 50.0, time=self.secs, on_done=done),
             lambda: st.r41, 50.0),
        ]

    def test_the_timer_sees_the_tween_finished_and_its_on_done_run(self):
        import itertools
        for fps, k, timer in itertools.product(self.FPS, (1, 3, 12, 30), ("after", "every")):
            dt = 1.0 / fps
            self.secs = k / fps
            for name, start, read, end in self._doors():
                with self.subTest(fps=fps, k=k, timer=timer, door=name):
                    log = []
                    start(lambda: log.append("done"))
                    seen = []

                    def fire(h=None):
                        seen.append(read())
                        log.append("timer")
                    h = (after if timer == "after" else every)(self.secs, fire)
                    for _ in range(k):
                        _frame(dt)
                    h.cancel()
                    self.assertEqual(log, ["done", "timer"])
                    self.assertAlmostEqual(seen[0], end, places=9)
                    reset_process_scheduler()

    def test_a_retween_from_the_timer_keeps_the_first_on_done(self):
        for fps in self.FPS:
            with self.subTest(fps=fps):
                self.tearDown()
                self.setUp()
                dt = 1.0 / fps
                c = self.track(Circle(center=(0, 0), radius=1))
                log = []
                c.move_to(300, 0, time=2.0, on_done=lambda: log.append(("done", c.center.x)))
                after(2.0, lambda: (log.append(("after", c.center.x)),
                                    c.move_to(300, 150, time=1.0)))
                for _ in range(int(round(3.5 * fps))):
                    _frame(dt)
                self.assertEqual(log, [("done", 300.0), ("after", 300.0)])
                self.assertAlmostEqual(c.center.y, 150.0, places=9)


class TestACallbackThatNeedsArgumentsRaisesWhereItIsGiven(ProcessTestCase):
    """R6-1 (persona probes, round 6): ``after(0.8, ia_joga)`` with
    ``def ia_joga(peca, casas)`` was accepted and failed 0.8 s later inside
    the engine, with no author line. Every door that keeps a callback for
    later (after, every, ``on_done=`` of a tween or a timed pose, an
    actor's own timers) now refuses it at the call, naming the lambda."""

    def test_every_door_refuses_a_callback_that_needs_more(self):
        def needs_two(peca, casas):
            pass
        c = self.track(Circle(center=(0, 0), radius=1))
        doors = {
            "after": lambda: after(0.8, needs_two),
            "every": lambda: every(0.3, needs_two),
            "tween on_done": lambda: tween(c["radius"], 5.0, time=0.2, on_done=needs_two),
            "move_to on_done": lambda: c.move_to(10, 0, time=0.2, on_done=needs_two),
            "e.after": lambda: c.after(0.5, needs_two),      # gets the owner, needs two
        }
        for door, call in doors.items():
            with self.subTest(door=door):
                with self.assertRaises(TypeError) as cm:
                    call()
                msg = str(cm.exception)
                self.assertIn("needs_two() needs 2 argument(s)", msg)
                self.assertIn("lambda", msg)
        self.assertEqual(len(get_scheduler()._handles), 0)

    def test_what_fits_is_accepted(self):
        c = self.track(Circle(center=(0, 0), radius=1))
        got = []

        def owner_only(e):
            got.append(e)

        def with_defaults(peca=None, casas=3):
            got.append(casas)
        after(0.1, with_defaults)
        after(0.1, lambda: got.append("lambda"))
        c.after(0.1, owner_only)                        # an actor's timer gets the actor
        c.move_to(5, 0, time=0.1, on_done=owner_only)
        for _ in range(3):
            _frame(0.1)
        self.assertIn(3, got)
        self.assertIn("lambda", got)
        self.assertEqual(got.count(c), 2)


class TestASelfRearmingAfterIsNotARate(ProcessTestCase):
    """The Guia's timers paragraph (R5-8, persona probes round 5): an
    ``after`` armed again inside its own function starts each lap at the
    frame the last one fired, so its intervals are "at least p", rounded up
    to frames, and the lag adds up; ``every`` keeps the rate (Laws T2)."""

    def test_rearmed_after_rounds_each_lap_up_and_every_does_not(self):
        import math
        p = 0.418
        for fps in (30, 60, 144):
            with self.subTest(fps=fps):
                self.tearDown()
                self.setUp()
                dt = 1.0 / fps
                laps, beats = [], []

                def lap():
                    laps.append(clock.time)
                    after(p, lap)
                after(p, lap)
                every(p, lambda: beats.append(clock.time))
                for _ in range(int(round(10 * fps))):
                    _frame(dt)
                per_lap = math.ceil(p * fps - 1e-9) / fps
                for k, t in enumerate(laps[:20], 1):
                    self.assertAlmostEqual(t, k * per_lap, places=6)
                    self.assertGreaterEqual(t + 1e-9, k * p)
                for k, t in enumerate(beats[:20], 1):
                    self.assertLess(t - k * p, dt + 1e-9)     # within a frame, no drift


class TestMovesChainedByOnDoneAreNotARate(ProcessTestCase):
    """The Guia's timers paragraph (R6-4, persona probes round 6): a move
    started from the last one's ``on_done`` begins at the frame that saw
    the last one end, so each hop of ``time=p`` takes ``p`` rounded up to
    frames, as a self re-arming ``after`` does (Laws T2, V1 limits)."""

    def test_each_hop_rounds_up_to_frames(self):
        import math
        p, hops = 0.12, 5
        for fps in (30, 60, 144):
            with self.subTest(fps=fps):
                reset_process_scheduler()
                clock._time = 0.0
                dt = 1.0 / fps
                c = self.track(Circle(center=(0, 0), radius=1))
                ends = []

                def hop(n):
                    if n == 0:
                        ends.append(clock.time)
                        return
                    c.move_by(20, 0, time=p, on_done=lambda: hop(n - 1))
                hop(hops)
                for _ in range(int(round(1.5 * fps))):
                    _frame(dt)
                per_hop = math.ceil(p * fps - 1e-9) / fps
                self.assertAlmostEqual(ends[0], hops * per_hop, places=6)
                self.assertAlmostEqual(c.center.x, 20 * hops, places=6)


class TestRearmSameTick(ProcessTestCase):
    """A Handle created during tick() must not fire until the next tick.

    Re-arming ``after`` / ``every`` / ``tween(on_done=...)`` from a fire
    callback used to append onto a live bucket list; ``dt >= delay`` then
    spun inside one ``tick()``. Cap the callback so a regression cannot hang
    the test run.
    """

    _CAP = 10000

    def test_after_rearm_from_fire_does_not_spin_same_tick(self):
        n = []

        def hop():
            n.append(1)
            if len(n) >= self._CAP:
                return
            after(0.05, hop)

        after(0.05, hop)
        _frame(1.0)  # world_dt (1.0) >> delay (0.05) — would spin before the fix
        self.assertEqual(n, [1])
        self.assertLess(len(n), self._CAP)
        live = [
            h for h in get_scheduler()._once
            if h.kind == "after" and not h._cancelled and not h._done
        ]
        self.assertEqual(len(live), 1)
        _frame(0.05)
        self.assertEqual(n, [1, 1])

    def test_entity_after_rearm_from_bound_method_does_not_spin_same_tick(self):
        n = []

        class Hopper(Circle):
            def hop(self):
                n.append(1)
                if len(n) >= TestRearmSameTick._CAP:
                    return
                self.after(0.05, self.hop)

        e = self.track(Hopper())
        e.after(0.05, e.hop)
        _frame(1.0)
        self.assertEqual(n, [1])
        self.assertLess(len(n), self._CAP)
        live = [
            h for h in get_scheduler()._once
            if h.kind == "after" and not h._cancelled and not h._done
        ]
        self.assertEqual(len(live), 1)
        self.assertIs(live[0].owner, e)
        _frame(0.05)
        self.assertEqual(n, [1, 1])

    def test_tween_ondone_pingpong_does_not_spin_same_tick(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        n = []

        def up():
            n.append("up")
            if len(n) >= self._CAP:
                return
            tween(c["radius"], 20, time=0.05, on_done=down)

        def down():
            n.append("down")
            if len(n) >= self._CAP:
                return
            tween(c["radius"], 10, time=0.05, on_done=up)

        up()
        _frame(1.0)
        self.assertEqual(n, ["up", "down"])
        self.assertLess(len(n), self._CAP)
        _frame(0.05)
        self.assertEqual(n, ["up", "down", "up"])

    def test_every_named_replace_from_fire_does_not_fire_same_tick(self):
        n = []

        def pulse():
            n.append(1)
            if len(n) >= self._CAP:
                return
            every(0.05, pulse, name="x")

        every(0.05, pulse, name="x")
        _frame(1.0)
        self.assertEqual(n, [1])
        self.assertLess(len(n), self._CAP)
        _frame(0.05)
        self.assertEqual(n, [1, 1])


class TestHandleRemaining(ProcessTestCase):
    def test_after_remaining_counts_down(self):
        h = after(0.25, lambda: None)
        self.assertAlmostEqual(h.remaining, 0.25, places=5)
        self.assertAlmostEqual(h.elapsed, 0.0, places=5)
        _frame(0.1)
        self.assertAlmostEqual(h.remaining, 0.15, places=5)
        self.assertAlmostEqual(h.elapsed, 0.1, places=5)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertEqual(h.remaining, 0.0)

    def test_cancel_after_done_does_not_mark_cancelled(self):
        h = after(0.1, lambda: None)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)
        h.cancel()
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)

    def test_remaining_zero_when_cancelled(self):
        h = after(1.0, lambda: None)
        _frame(0.3)
        self.assertAlmostEqual(h.remaining, 0.7, places=5)
        h.cancel()
        self.assertEqual(h.remaining, 0.0)
        self.assertTrue(h.cancelled)

    def test_every_remaining_until_next_fire(self):
        n = []
        h = every(0.2, lambda: n.append(1))
        self.assertAlmostEqual(h.remaining, 0.2, places=5)
        _frame(0.1)
        self.assertAlmostEqual(h.remaining, 0.1, places=5)
        self.assertEqual(n, [])
        _frame(0.1)
        self.assertEqual(n, [1])
        self.assertAlmostEqual(h.remaining, 0.2, places=5)
        h.cancel()
        self.assertEqual(h.remaining, 0.0)

    def test_tween_remaining_counts_down(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = tween(c["radius"], 20, time=0.4)
        self.assertAlmostEqual(h.remaining, 0.4, places=5)
        _frame(0.2)
        self.assertAlmostEqual(h.remaining, 0.2, places=5)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertEqual(h.remaining, 0.0)

    def test_remaining_is_read_only(self):
        h = after(1.0, lambda: None)
        with self.assertRaises(TypeError) as ctx:
            h.remaining = 5.0
        msg = str(ctx.exception)
        self.assertIn("read-only", msg)
        self.assertIn("name=", msg)
        self.assertIn("cancel()", msg)
        self.assertAlmostEqual(h.remaining, 1.0, places=5)


class TestHandlePause(ProcessTestCase):
    def test_every_freezes_elapsed_and_keeps_phase(self):
        n = []
        h = every(0.2, lambda: n.append(1))
        _frame(0.1)
        self.assertEqual(n, [])
        self.assertAlmostEqual(h.elapsed, 0.1, places=5)
        self.assertIs(h.pause(), h)
        self.assertTrue(h.paused)
        frozen = h.elapsed
        _frame(0.5)
        self.assertEqual(n, [])
        self.assertAlmostEqual(h.elapsed, frozen, places=5)
        self.assertAlmostEqual(h.remaining, 0.1, places=5)
        self.assertIs(h.resume(), h)
        self.assertFalse(h.paused)
        _frame(0.1)
        self.assertEqual(n, [1])
        self.assertAlmostEqual(h.elapsed, 0.0, places=5)

    def test_after_fires_after_leftover_on_resume(self):
        n = []
        h = after(0.3, on_done=lambda: n.append(1))
        _frame(0.1)
        h.pause()
        _frame(1.0)
        self.assertEqual(n, [])
        self.assertFalse(h.done)
        h.resume()
        _frame(0.15)
        self.assertEqual(n, [])
        _frame(0.05)
        self.assertEqual(n, [1])
        self.assertTrue(h.done)

    def test_wait_stays_awaiting_until_resume(self):
        c = self.track(Circle())
        seen = []
        handles = []

        async def diving(e):
            h = wait(0.3)
            handles.append(h)
            await h
            seen.append("done")

        c.mode = diving
        self.assertEqual(len(handles), 1)
        h = handles[0]
        _frame(0.1)
        h.pause()
        _frame(1.0)
        self.assertEqual(seen, [])
        self.assertTrue(h.paused)
        h.resume()
        _frame(0.15)
        self.assertEqual(seen, [])
        _frame(0.05)
        self.assertEqual(seen, ["done"])

    def test_tween_freezes_value_then_finishes(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        h = tween(c["radius"], 20, time=0.4)
        _frame(0.2)
        mid = float(c.radius)
        self.assertAlmostEqual(mid, 15.0, places=5)
        h.pause()
        _frame(1.0)
        self.assertAlmostEqual(float(c.radius), mid, places=5)
        h.resume()
        _frame(0.2)
        self.assertAlmostEqual(float(c.radius), 20.0, places=5)
        self.assertTrue(h.done)

    def test_motion_velocity_zero_while_paused(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_to(100, 0, time=1.0)
        _frame(0.1)
        self.assertGreater(h.speed, 0.0)
        h.pause()
        self.assertEqual(h.speed, 0.0)
        self.assertEqual(float(h.velocity.x), 0.0)
        _frame(0.2)
        self.assertEqual(h.speed, 0.0)

    def test_pause_resume_idempotent_and_cancelled_noop(self):
        h = after(1.0, lambda: None)
        self.assertIs(h.pause(), h)
        self.assertIs(h.pause(), h)
        self.assertTrue(h.paused)
        self.assertIs(h.resume(), h)
        self.assertIs(h.resume(), h)
        self.assertFalse(h.paused)
        h.cancel()
        self.assertTrue(h.cancelled)
        self.assertFalse(h.paused)
        self.assertIs(h.pause(), h)
        self.assertFalse(h.paused)
        self.assertTrue(h.cancelled)
        self.assertIs(h.resume(), h)
        self.assertTrue(h.cancelled)

    def test_world_and_active_clear_do_not_clear_paused(self):
        h = every(0.2, lambda: None)
        h.pause()
        clock.paused = True
        _frame(0.5)
        clock.paused = False
        self.assertTrue(h.paused)

        c = self.track(Circle())
        h2 = c.every(0.2, lambda: None)
        h2.pause()
        c.active = False
        _frame(0.2)
        c.active = True
        self.assertTrue(h2.paused)

    def test_destroy_owner_cancels_paused(self):
        c = self.track(Circle())
        h = c.every(0.2, lambda: None)
        h.pause()
        self.assertTrue(h.paused)
        c.destroy()
        _frame(0.1)
        self.assertTrue(h.cancelled)
        self.assertFalse(h.paused)

    def test_named_every_replaces_paused(self):
        n = []
        every(1.0, lambda: n.append("a"), name="spawn").pause()
        every(0.1, lambda: n.append("b"), name="spawn")
        _frame(0.1)
        self.assertEqual(n, ["b"])

    def test_until_parallel_race_refuse_pause(self):
        c = self.track(Circle())
        kinds = []

        async def diving(e):
            u = until(lambda: False)
            try:
                u.pause()
            except TypeError as err:
                kinds.append(("until", str(err)))
            u.cancel()
            w1 = wait(10.0)
            w2 = wait(10.0)
            p = parallel(w1, w2)
            try:
                p.pause()
            except TypeError as err:
                kinds.append(("parallel", str(err)))
            p.cancel()
            r = race(wait(10.0), wait(10.0))
            try:
                r.pause()
            except TypeError as err:
                kinds.append(("race", str(err)))
            r.cancel()
            await wait(0.01)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            c.mode = diving
            _frame(0.01)
        self.assertEqual([k for k, _ in kinds], ["until", "parallel", "race"])
        for _, msg in kinds:
            self.assertIn("not on", msg)

    def test_paused_assign_raises(self):
        h = after(1.0, lambda: None)
        with self.assertRaises(TypeError) as ctx:
            h.paused = True
        self.assertIn("pause()", str(ctx.exception))
        self.assertFalse(h.paused)


class TestOwnership(ProcessTestCase):
    def test_item_after_cancels_on_destroy(self):
        c = self.track(Circle())
        n = []
        c.after(0.2, lambda: n.append(1))
        c.destroy()
        _frame(0.5)
        self.assertEqual(n, [])

    def test_bound_method_infers_owner(self):
        c = self.track(Circle())
        h = after(0.3, c.destroy)
        self.assertIs(h.owner, c)
        c.destroy()
        _frame(0.5)
        self.assertTrue(h.cancelled)

    def test_other_entity_bound_method_not_captured_by_mode(self):
        """``after(delay, fx.destroy)`` from a dying mode must outlive the actor.

        Mode context used to win over bound-method inference, so destroying the
        wasp cancelled the Sparks teardown (Galaga ``dying``).
        """
        wasp = self.track(Circle())
        fx = self.track(Circle())

        def dying(e):
            after(0.2, fx.destroy)
            e.destroy()

        wasp.mode = dying
        self.assertFalse(wasp.is_alive)
        self.assertTrue(fx.is_alive)
        h = next(iter(get_scheduler()._handles))
        self.assertIs(h.owner, fx)
        self.assertEqual(h.scope, "entity")
        _frame(0.3)
        self.assertFalse(fx.is_alive)

    def test_bound_method_on_mode_owner_is_mode_scoped(self):
        """``after(0.2, e.destroy)`` inside e's own mode dies on leave.

        Use ``e.after(...)`` when the timer must survive the mode change.
        """
        c = self.track(Circle())

        def idle(e):
            after(0.2, e.destroy)

        c.mode = idle
        h = next(iter(get_scheduler()._handles))
        self.assertIs(h.owner, c)
        self.assertEqual(h.scope, "mode")
        c.mode = None
        _frame(0.5)
        self.assertTrue(c.is_alive)
        self.assertTrue(h.cancelled)

    def test_entity_after_bound_destroy_survives_mode_leave(self):
        c = self.track(Circle())

        def idle(e):
            e.after(0.2, e.destroy)

        c.mode = idle
        h = next(iter(get_scheduler()._handles))
        self.assertEqual(h.scope, "entity")
        c.mode = None
        _frame(0.5)
        self.assertFalse(c.is_alive)

    def test_act_after_survives_unrelated_destroy(self):
        c = self.track(Circle())
        n = []
        after(0.2, lambda: n.append(1))
        c.destroy()
        _frame(0.3)
        self.assertEqual(n, [1])

    def test_bare_after_inside_owning_is_mode_scoped(self):
        """``after`` / ``every`` pick up ambient ``owning`` mode context."""
        c = self.track(Circle())
        n = []
        with owning(c, scope="mode"):
            after(0.2, lambda: n.append(1))
        h = next(iter(get_scheduler()._handles))
        self.assertIs(h.owner, c)
        self.assertEqual(h.scope, "mode")
        get_scheduler().cancel_owner(c, scopes=("mode",))
        _frame(0.5)
        self.assertEqual(n, [])

    def test_after_from_mode_auto_cancels_on_mode_change(self):
        c = self.track(Circle())
        fired = []

        def staggered(e):
            pass

        def charging(e):
            after(0.3, lambda: fired.append(1))

        c.mode = charging
        c.mode = staggered
        _frame(0.5)
        self.assertEqual(fired, [])

    def test_entity_after_survives_mode_change(self):
        c = self.track(Circle())
        fired = []

        def staggered(e):
            pass

        def charging(e):
            e.after(0.3, lambda: fired.append(1))

        c.mode = charging
        c.mode = staggered
        _frame(0.5)
        self.assertEqual(fired, [1])

    def test_bound_other_entity_after_from_mode_is_entity_scoped(self):
        wasp = self.track(Circle())
        bomb = self.track(Circle())
        fired = []

        def idle(e):
            pass

        def dying(e):
            after(0.3, bomb.destroy)
            after(0.3, lambda: fired.append(1))

        wasp.mode = dying
        handles = [h for h in get_scheduler()._handles if not h.done]
        bomb_h = next(h for h in handles if h.owner is bomb)
        mode_h = next(h for h in handles if h.owner is wasp)
        self.assertEqual(bomb_h.scope, "entity")
        self.assertEqual(mode_h.scope, "mode")
        wasp.mode = idle
        self.assertTrue(mode_h.cancelled)
        self.assertFalse(bomb_h.cancelled)
        _frame(0.5)
        self.assertFalse(bomb.is_alive)

    def test_entity_scope_survives_mode_cancel(self):
        c = self.track(Circle())
        n = []
        c.after(0.2, lambda: n.append(1))
        get_scheduler().cancel_owner(c, scopes=("mode",))
        _frame(0.3)
        self.assertEqual(n, [1])

    def test_time_scale_slows_actor_timers(self):
        c = self.track(Circle())
        n = []
        c.time_scale = 0.5
        c.after(0.2, lambda: n.append(1))
        _frame(0.2)  # effective 0.1
        self.assertEqual(n, [])
        _frame(0.2)  # effective 0.2
        self.assertEqual(n, [1])

    def test_time_scale_rejects_negative_nan_inf(self):
        # Regression: `max(0.0, float(value))` silently turned a negative
        # or NaN time_scale into 0, and silently accepted inf (which then
        # turns `elapsed % interval` into NaN downstream, permanently
        # breaking every() for that actor).
        c = self.track(Circle())
        for bad in (-1.0, float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                c.time_scale = bad
        self.assertEqual(c.time_scale, 1.0)  # unchanged by the rejected writes
        c.time_scale = 0.0  # still a legal "pause this actor's timers" value
        self.assertEqual(c.time_scale, 0.0)

    def test_arity_passes_owner_to_free_function(self):
        c = self.track(Circle())
        seen = []

        def on_due(item):
            seen.append(item)

        c.after(0.1, on_due)
        _frame(0.1)
        self.assertEqual(seen, [c])

    def test_arity_zero_arg_lambda(self):
        c = self.track(Circle())
        n = []
        c.after(0.1, lambda: n.append(1))
        _frame(0.1)
        self.assertEqual(n, [1])

    def test_active_pauses_owned_timers(self):
        c = self.track(Circle())
        n = []
        c.after(0.2, lambda: n.append(1))
        c.active = False
        self.assertFalse(c.visible)
        self.assertFalse(c.collidable)
        _frame(0.5)
        self.assertEqual(n, [])
        c.active = True
        self.assertTrue(c.visible)
        _frame(0.2)
        self.assertEqual(n, [1])

    def test_active_restores_collidable(self):
        c = self.track(Circle())
        c.collidable = True
        c.active = False
        self.assertFalse(c.collidable)
        c.active = True
        self.assertTrue(c.collidable)

    def test_active_false_skips_on_update(self):
        c = self.track(Circle())
        n = []
        c.on_update = lambda e, dt: n.append(1)
        c.active = False
        _frame(0.1)
        self.assertEqual(n, [])
        c.active = True
        _frame(0.1)
        self.assertEqual(n, [1])

    def test_active_idempotent(self):
        c = self.track(Circle())
        c.active = False
        c.active = False
        c.active = True
        c.active = True
        self.assertTrue(c.active)
        self.assertTrue(c.visible)

    def test_destroy_sets_active_false(self):
        c = self.track(Circle())
        self.assertTrue(c.active)
        c.destroy()
        self.assertFalse(c.is_alive)
        self.assertFalse(c.active)

    def test_destroy_after_park_stays_inactive(self):
        c = self.track(Circle())
        c.active = False
        c.destroy()
        self.assertFalse(c.is_alive)
        self.assertFalse(c.active)

    def test_active_true_after_destroy_is_noop(self):
        c = self.track(Circle())
        c.collidable = True
        c.active = False
        self.assertFalse(c.visible)
        self.assertFalse(c.collidable)
        c.destroy()
        c.active = True
        self.assertFalse(c.is_alive)
        self.assertFalse(c.active)
        self.assertFalse(c.visible)
        self.assertFalse(c.collidable)

    def test_active_false_after_destroy_is_noop(self):
        c = self.track(Circle())
        c.destroy()
        c.active = False
        self.assertFalse(c.active)
        self.assertFalse(c.is_alive)

    def test_on_destroy_sees_live_active_then_clears(self):
        seen = []
        c = self.track(Circle())

        def hook(e):
            seen.append((e.is_alive, e.active))

        c.on_destroy = hook
        c.destroy()
        self.assertEqual(seen, [(True, True)])
        self.assertFalse(c.is_alive)
        self.assertFalse(c.active)


class TestClosureOverSelfIsOwnedLikeTheBoundMethod(ProcessTestCase):
    """A lambda / nested def over a method's ``self`` is owned by that actor,
    like ``after(d, self.method)`` (review 2026-10-14 PA4). It was act work:
    ``after(0.1, lambda: self.set_color("red"))`` in ``on_update`` outlived
    the actor and raised DestroyedError, and ``lambda: self.atirar()`` made a
    dead enemy shoot."""

    def test_every_closure_shape_is_entity_owned_and_dies_with_the_actor(self):
        import functools
        fired = []
        for label in ("lambda", "nested def", "partial", "every", "on_done="):
            with self.subTest(label):
                reset_process_scheduler()

                class Ini(Circle):
                    def on_update(self, dt):
                        if getattr(self, "armed", False):
                            return
                        self.armed = True
                        if label == "lambda":
                            after(0.2, lambda: self.set_color("red"))
                        elif label == "nested def":
                            def pisca():
                                fired.append(self)
                                self.set_color("red")
                            after(0.2, pisca)
                        elif label == "every":
                            every(0.2, lambda: self.set_color("red"))
                        elif label == "on_done=":
                            after(0.2, on_done=lambda: self.set_color("red"))
                        else:
                            after(0.2, functools.partial(self.set_color, "red"))

                ini = self.track(Ini(radius=5))
                _frame(0.05)
                h = next(h for h in get_scheduler()._handles if not h.done)
                self.assertIs(h.owner, ini)
                self.assertEqual(h.scope, SCOPE_ENTITY)
                ini.destroy()
                _frame(0.5)          # used to raise DestroyedError
                self.assertTrue(h.cancelled)
        self.assertEqual(fired, [])

    def test_a_closure_over_another_actor_keeps_its_rule(self):
        alvo = self.track(Circle(radius=5))

        class Ini(Circle):
            def on_update(self, dt):
                if not getattr(self, "armed", False):
                    self.armed = True
                    after(0.2, lambda: alvo.set_color("red"))

        ini = self.track(Ini(radius=5))
        _frame(0.05)
        h = next(h for h in get_scheduler()._handles if not h.done)
        self.assertIsNone(h.owner)
        ini.destroy()
        _frame(0.5)
        self.assertTrue(h.done and not h.cancelled)

    def test_in_a_mode_body_a_closure_over_self_is_mode_scoped(self):
        class Ini(Circle):
            pass

        ini = self.track(Ini(radius=5))

        def idle(e):
            pass

        def mira(self):
            after(0.2, lambda: self.set_color("red"))

        ini.mode = mira
        h = next(h for h in get_scheduler()._handles if not h.done)
        self.assertIs(h.owner, ini)
        self.assertEqual(h.scope, "mode")
        ini.mode = idle
        self.assertTrue(h.cancelled)

    def test_on_destroy_work_over_self_still_runs_after_the_death(self):
        """``on_destroy`` work is "after I am gone": it keeps the plain rule."""
        seen = []

        class Ini(Circle):
            def on_destroy(self):
                after(0.1, lambda: seen.append(self.is_alive))

        ini = Ini(radius=5)
        ini.destroy()
        _frame(0.3)
        self.assertEqual(seen, [False])


class TestReadyAndClock(ProcessTestCase):
    def test_ready_first_call_true_then_interval(self):
        self.assertTrue(ready("fire", 0.25))
        self.assertFalse(ready("fire", 0.25))
        clock.advance(0.2)
        self.assertFalse(ready("fire"))
        clock.advance(0.1)
        self.assertTrue(ready("fire"))

    def test_ready_uses_scaled_time(self):
        clock.scale = 0.5
        ready("pulse", 0.2)
        clock.advance(0.2)  # world dt 0.1
        self.assertFalse(ready("pulse"))
        clock.advance(0.2)  # world +0.1 → 0.2
        self.assertTrue(ready("pulse"))

    def test_clock_paused_stops_world_time(self):
        clock.scale = 1.0
        clock.advance(0.1)
        t0 = clock.time
        clock.paused = True
        self.assertEqual(clock.scale, 0.0)
        clock.advance(1.0)
        self.assertEqual(clock.dt, 0.0)
        self.assertEqual(clock.time, t0)
        self.assertGreater(clock.real_dt, 0.0)
        clock.paused = False
        self.assertEqual(clock.scale, 1.0)
        clock.advance(0.05)
        self.assertAlmostEqual(clock.time, t0 + 0.05, places=5)

    def test_scale_zero_is_paused(self):
        clock.scale = 0.0
        self.assertTrue(clock.paused)

    def test_advance_does_not_tick_processes(self):
        n = []
        after(0.1, lambda: n.append(1))
        clock.advance(0.2)
        self.assertEqual(n, [])
        tick_processes()
        self.assertEqual(n, [1])

    def test_ready_rejects_non_finite_and_negative_interval(self):
        # Regression: NaN silently meant "never ready again" (`>= nan` is
        # always False); a negative interval silently meant "always ready"
        # (`>=` a negative number is always True).
        for bad in (float("nan"), float("inf"), -1.0):
            with self.assertRaises(ValueError):
                ready("bad_timer", bad)
        # A fresh, valid timer is unaffected by the rejected attempts above.
        self.assertTrue(ready("bad_timer", 0.1))
        with self.assertRaises(ValueError):
            ready("bad_timer", float("nan"))  # updating an existing timer too


class TestRecently(ProcessTestCase):
    def test_false_until_truthy_then_holds(self):
        self.assertFalse(recently("ground", False, hold=0.1))
        self.assertTrue(recently("ground", True, hold=0.1))
        self.assertTrue(recently("ground", False, hold=0.1))
        clock.advance(0.05)
        self.assertTrue(recently("ground", False, hold=0.1))
        clock.advance(0.06)
        self.assertFalse(recently("ground", False, hold=0.1))

    def test_truthy_extends_window(self):
        recently("hit", True, hold=0.1)
        clock.advance(0.08)
        self.assertTrue(recently("hit", True, hold=0.1))  # refresh
        clock.advance(0.08)
        self.assertTrue(recently("hit", False, hold=0.1))
        clock.advance(0.03)
        self.assertFalse(recently("hit", False, hold=0.1))

    def test_uses_scaled_time(self):
        clock.scale = 0.5
        recently("pulse", True, hold=0.2)
        clock.advance(0.2)  # world +0.1
        self.assertTrue(recently("pulse", False, hold=0.2))
        clock.advance(0.2)  # world +0.1 → 0.2 total
        self.assertTrue(recently("pulse", False, hold=0.2))
        clock.advance(0.02)  # past hold
        self.assertFalse(recently("pulse", False, hold=0.2))

    def test_reset_forgets(self):
        recently("jump", True, hold=0.2)
        self.assertTrue(recently("jump", False, hold=0.2))
        recently.reset("jump")
        self.assertFalse(recently("jump", False, hold=0.2))

    def test_remove_forgets(self):
        recently("dash", True, hold=0.2)
        recently.remove("dash")
        self.assertFalse(recently("dash", False, hold=0.2))

    def test_hold_update_on_recall(self):
        recently("buf", True, hold=0.5)
        clock.advance(0.2)
        # Shrink hold below elapsed → False immediately.
        self.assertFalse(recently("buf", False, hold=0.1))

    def test_recently_rejects_non_finite_and_negative_hold(self):
        # Regression: a negative hold made `(now - last) <= hold` false
        # even on the very call that just set ``last_true = now`` (elapsed
        # 0 <= negative hold is false), so `recently(name, True, hold=-1)`
        # returned False for a value that was truthy *right now*.
        for bad in (float("nan"), float("inf"), -1.0):
            with self.assertRaises(ValueError):
                recently("bad_hold", True, hold=bad)


class TestEntityReadyRecently(ProcessTestCase):
    def test_entity_ready_slots_are_independent(self):
        a = self.track(Circle())
        b = self.track(Circle())
        self.assertTrue(a.ready("fire", 0.3))
        self.assertFalse(a.ready("fire", 0.3))
        # Same name on B is a fresh slot.
        self.assertTrue(b.ready("fire", 0.3))
        self.assertFalse(b.ready("fire", 0.3))
        clock.advance(0.3)
        self.assertTrue(a.ready("fire"))
        self.assertTrue(b.ready("fire"))

    def test_entity_ready_does_not_share_global(self):
        e = self.track(Circle())
        self.assertTrue(ready("fire", 0.25))
        self.assertFalse(ready("fire", 0.25))
        self.assertTrue(e.ready("fire", 0.25))
        self.assertFalse(e.ready("fire", 0.25))

    def test_entity_recently_slots_are_independent(self):
        a = self.track(Circle())
        b = self.track(Circle())
        self.assertTrue(a.recently("hit", True, hold=0.1))
        self.assertFalse(b.recently("hit", False, hold=0.1))
        self.assertTrue(b.recently("hit", True, hold=0.1))
        clock.advance(0.12)
        self.assertFalse(a.recently("hit", False, hold=0.1))
        self.assertFalse(b.recently("hit", False, hold=0.1))

    def test_entity_recently_does_not_share_global(self):
        e = self.track(Circle())
        self.assertTrue(recently("hit", True, hold=0.1))
        self.assertFalse(e.recently("hit", False, hold=0.1))
        self.assertTrue(e.recently("hit", True, hold=0.1))

    def test_entity_poll_state_not_a_scheduler_handle(self):
        e = self.track(Circle())
        e.ready("fire", 0.2)
        e.recently("hit", True, hold=0.1)
        sched = get_scheduler()
        owned = [h for h in sched.all_handles() if h.owner is e] if hasattr(sched, "all_handles") else []
        # Fall back: scan known buckets if no all_handles helper.
        if not hasattr(sched, "all_handles"):
            for bucket in (
                getattr(sched, "_after", None),
                getattr(sched, "_every", None),
                getattr(sched, "_tweens", None),
                getattr(sched, "_handles", None),
            ):
                if bucket:
                    owned.extend(h for h in bucket if getattr(h, "owner", None) is e)
        self.assertEqual(owned, [])


class TestHandleConstruction(ProcessTestCase):
    """``Handle`` is returned by the engine, never built by hand.

    Bug class: an author (or copied engine code) calling ``Handle(...)`` got
    Python's ``__init__() got an unexpected keyword argument`` or a half-built
    handle. Every call form now gets one author error; the engine builds
    through ``Handle._make``.
    """

    def test_every_call_form_gets_the_author_error(self):
        from scena.process import Handle
        for call in (lambda: Handle(), lambda: Handle("after"),
                     lambda: Handle(kind="after", delay=1.0, fn=lambda: None)):
            with self.assertRaises(TypeError) as cm:
                call()
            msg = str(cm.exception)
            self.assertIn("not built by hand", msg)
            self.assertIn("after(", msg)
            self.assertIn("h.cancel()", msg)
            self.assertNotIn("__init__", msg)

    def test_engine_verbs_still_return_handles(self):
        from scena.process import Handle
        h = after(1.0, lambda: None)
        self.assertIsInstance(h, Handle)
        e = every(0.5, lambda: None)
        self.assertIsInstance(e, Handle)
        h.cancel()
        e.cancel()
        self.assertTrue(h.cancelled)

    def test_half_built_handle_dies_quietly(self):
        """``_make`` with bad arguments: ``_init`` raises before any slot is
        set; the finalizer must not raise (an unraisable error on GC)."""
        import gc
        from scena.process import Handle
        seen = []
        old_hook = sys.unraisablehook
        sys.unraisablehook = seen.append
        try:
            with self.assertRaises(TypeError):
                Handle._make(no_such_field=1)
            gc.collect()
        finally:
            sys.unraisablehook = old_hook
        self.assertEqual(seen, [])


class TestCancelledType(ProcessTestCase):
    def test_cancelled_is_base_exception(self):
        self.assertTrue(issubclass(Cancelled, BaseException))
        self.assertFalse(issubclass(Cancelled, Exception))


class TestMode(ProcessTestCase):
    def test_enter_calls_body_once_and_bare_after_is_mode_scoped(self):
        c = self.track(Circle())
        n = []

        def idle(e):
            n.append(e)
            after(0.2, lambda: n.append("later"))

        c.mode = idle
        self.assertEqual(n, [c])
        self.assertEqual(c.mode, idle)
        h = next(iter(get_scheduler()._handles))
        self.assertEqual(h.scope, "mode")
        self.assertIs(h.owner, c)
        c.mode = None
        _frame(0.5)
        self.assertEqual(n, [c])  # mode-scoped after cancelled
        self.assertIsNone(c.mode)

    def test_reassigning_same_mode_is_noop(self):
        c = self.track(Circle())
        n = []

        def idle(e):
            n.append(1)

        c.mode = idle
        _frame(0.1)
        mt = c.mode_time
        c.mode = idle
        self.assertEqual(n, [1])
        self.assertAlmostEqual(c.mode_time, mt, places=5)

    def test_goto_mode_restarts_same_mode(self):
        c = self.track(Circle())
        n = []

        def idle(e):
            n.append(1)

        c.mode = idle
        c.goto_mode(idle)
        self.assertEqual(n, [1, 1])
        self.assertEqual(c.mode_time, 0.0)

    def test_mode_time_advances_with_time_scale(self):
        c = self.track(Circle())

        def idle(e):
            pass

        c.mode = idle
        c.time_scale = 0.5
        _frame(0.4)
        self.assertAlmostEqual(c.mode_time, 0.2, places=5)

    def test_string_mode_rejected(self):
        c = self.track(Circle())
        with self.assertRaises(TypeError) as ctx:
            c.mode = "diving"
        self.assertIn("not a string", str(ctx.exception))

    def test_non_callable_mode_rejected(self):
        c = self.track(Circle())
        with self.assertRaises(TypeError) as ctx:
            c.mode = 3
        self.assertIn("must be a function", str(ctx.exception))

    def test_async_mode_runs_until_first_await(self):
        c = self.track(Circle())
        seen = []

        async def diving(e):
            seen.append("enter")
            await wait(0.2)
            seen.append("after")

        c.mode = diving
        self.assertEqual(seen, ["enter"])
        _frame(0.1)
        self.assertEqual(seen, ["enter"])
        _frame(0.1)
        self.assertEqual(seen, ["enter", "after"])

    def test_then_enters_mode(self):
        c = self.track(Circle())
        seen = []

        def leaving(e):
            seen.append("leaving")

        def diving(e):
            seen.append("diving")
            e.after(0.2, then=leaving)

        c.mode = diving
        _frame(0.2)
        self.assertEqual(seen, ["diving", "leaving"])
        self.assertEqual(c.mode, leaving)

    def test_mode_cancel_leaves_entity_and_scene_timers(self):
        c = self.track(Circle())
        n = []

        def idle(e):
            after(0.2, lambda: n.append("mode"))  # cancelled on leave
            e.after(0.2, lambda: n.append("entity"))

        after(0.2, lambda: n.append("scene"))  # outside any mode
        c.mode = idle
        c.mode = None
        _frame(0.3)
        self.assertEqual(sorted(n), ["entity", "scene"])

    def test_compare_modes_with_eq(self):
        c = self.track(Circle())

        def idle(e):
            pass

        def diving(e):
            pass

        c.mode = idle
        self.assertTrue(c.mode == idle)
        self.assertFalse(c.mode == diving)
        self.assertFalse(c.mode is object())

    def test_sync_mode_body_nameerror_raises(self):
        c = self.track(Circle())

        def broken(e):
            every(does_not_exist.uniform(1, 2), e.destroy)

        with self.assertRaises(NameError):
            c.mode = broken
        self.assertEqual(c.mode, broken)
        self.assertEqual(len(get_scheduler()._handles), 0)

    def test_sync_mode_body_every_typeerror_raises(self):
        c = self.track(Circle())

        def broken(e):
            every(1.0, 123)

        with self.assertRaises(TypeError) as ctx:
            c.mode = broken
        self.assertIn("expected a function", str(ctx.exception))

    def test_then_mode_body_error_propagates(self):
        c = self.track(Circle())

        def broken(e):
            missing.foo()

        def start(e):
            e.after(0.1, then=broken)

        c.mode = start
        with self.assertRaises(NameError):
            _frame(0.1)
        self.assertEqual(c.mode, broken)


class TestInkAndWhen(ProcessTestCase):
    def tearDown(self):
        cleanup_global_event_system()
        super().tearDown()

    def test_unknown_name_creates_attribute(self):
        c = self.track(Circle())
        c.hp = 3
        self.assertIsInstance(c.hp, (int, float))
        self.assertEqual(c.hp, 3)
        c.hp = 1
        self.assertEqual(c.hp, 1)

    def test_ink_typo_raises_on_read(self):
        c = self.track(Circle())
        c.hp = 3
        with self.assertRaises(AttributeError):
            _ = c.hpt

    def test_ink_bracket_link_after_other_ink(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        c.line_color = Color("white")
        c["grounded"] @= Attribute(False)
        self.assertTrue(c["grounded"].is_linked)
        self.assertFalse(c.grounded)

    def test_ink_bracket_link(self):
        c = self.track(Circle())
        src = self.track(Circle())
        src.hp = 10
        c.hp = 0
        c["hp"] @= lambda: src.hp * 2
        self.assertTrue(c["hp"].is_linked)
        self.assertEqual(c.hp, 20)
        src.hp = 7
        self.assertEqual(c.hp, 14)
        with self.assertRaises(LinkedAttributeError):
            c.hp = 1
        c["hp"].unlink()
        c.hp = 1
        self.assertEqual(c.hp, 1)

    def test_reserved_names_stay_properties(self):
        c = self.track(Circle())
        c.visible = False
        self.assertIs(c.visible, False)
        self.assertFalse(isinstance(c.visible, Attribute))

    def test_model_is_not_ink(self):
        """Geometry ``model`` must stay a plain enum — never an ink Attribute."""
        from scena.shapes import CircleModel, RectModel

        c = self.track(Circle(center=(0, 0), radius=8))
        self.assertIs(c.model, CircleModel.CENTER_RADIUS)
        self.assertFalse(isinstance(c.model, Attribute))
        self.assertNotIn("model", c._ink or {})
        self.assertIsNone(c._ink)  # lazy: no bag until first ink write
        c.hp = 1
        self.assertIsNotNone(c._ink)
        self.assertIn("hp", c._ink)

        r = self.track(Rect(center=(0, 0), width=10, height=6))
        self.assertIs(r.model, RectModel.CENTER_WH)
        self.assertFalse(isinstance(r.model, Attribute))
        self.assertNotIn("model", r._ink or {})

        ln = self.track(Line(p1=(0, 0), p2=(10, 0)))
        self.assertFalse(isinstance(ln.model, Attribute))
        self.assertNotIn("model", ln._ink or {})
        self.assertTrue(type(ln.model).__name__.endswith("Model") or hasattr(type(ln.model), "__members__"))

    def test_when_on_ink_fires(self):
        c = self.track(Circle())
        c.hp = 5
        fired = []

        @when(lambda: c.hp <= 0)
        def death():
            fired.append(1)

        c.hp = 0
        self.assertEqual(fired, [1])

    def test_when_after_destroy_is_inert(self):
        c = self.track(Circle())
        c.hp = 5
        fired = []

        @when(lambda: c.hp <= 0)
        def death():
            fired.append(1)

        c.destroy()
        # Writing / evaluating after teardown must not fire or traceback.
        try:
            c.hp = 0
        except Exception:
            pass
        flush()
        self.assertEqual(fired, [])

    def test_when_polls_bare_python_flag(self):
        flag = {"dead": False}
        fired = []

        @when(lambda: flag["dead"])
        def death():
            fired.append(1)

        flag["dead"] = True
        self.assertEqual(fired, [])
        flush()
        self.assertEqual(fired, [1])
        flush()
        self.assertEqual(fired, [1])  # still True — not a new edge

    def test_raising_when_propagates_and_consumes_edge(self):
        order = []
        flag = {"v": False}

        @when(lambda: flag["v"])
        def first():
            order.append("first")
            raise RuntimeError("boom")

        @when(lambda: flag["v"])
        def second():
            order.append("second")

        flag["v"] = True
        with self.assertRaisesRegex(RuntimeError, "boom"):
            flush()
        self.assertEqual(order, ["first"])
        flush()  # first's edge consumed; second fires on the next poll
        self.assertEqual(order, ["first", "second"])

    def test_when_eval_error_raises_and_keeps_the_watch(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            # Seed (n==1) is False. First flush raises. Next flush rises.
            if calls["n"] == 1:
                return False
            if calls["n"] == 2:
                raise ValueError("condition bug")
            return True

        fired = []

        @when(flaky)
        def go():
            fired.append(1)

        with self.assertRaisesRegex(ValueError, "condition bug"):
            flush()
        self.assertEqual(fired, [])
        self.assertTrue(go._event_registration._is_active)
        flush()
        self.assertEqual(fired, [1])
        self.assertTrue(go._event_registration._is_active)

    def test_non_bool_when_raises(self):
        order = []
        bad = {"v": False}
        good = {"v": False}

        @when(lambda: bad["v"])
        def first():
            order.append("first")

        @when(lambda: good["v"])
        def second():
            order.append("second")

        bad["v"] = 1
        good["v"] = True
        with self.assertRaisesRegex(TypeError, "bool"):
            flush()
        self.assertEqual(order, [])

    def test_on_change_star_args_receives_value(self):
        seen = []

        @on_change(lambda: 1)
        def follow(*args):
            seen.append(args)

        # Seed is 1, so force a change.
        follow._event_registration._condition = lambda: 2
        flush()
        self.assertEqual(seen, [(2,)])

    def test_when_destroyed_entity_inert_on_next_poll(self):
        c = self.track(Circle())
        c.hp = 5
        fired = []

        @when(lambda: c.hp <= 0)
        def death():
            fired.append(1)

        c.destroy()
        flush()
        self.assertEqual(fired, [])

    def test_tag_sugar(self):
        c = self.track(Circle())
        c.tag("hurt", "player")
        self.assertTrue(c.tagged("hurt"))
        self.assertIn("player", c.group)
        c.untag("hurt")
        self.assertFalse(c.tagged("hurt"))


class TestClassMethodWhen(ProcessTestCase):
    """Proposal D: ``@when(lambda self: …)`` on Entity methods."""

    def test_condition_receives_instance_edge_only(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5

            @when(lambda self: self.hp <= 0)
            def on_death(self):
                fired.append(self)

        d = self.track(Drone())
        self.assertEqual(fired, [])
        d.hp = 3
        flush()
        self.assertEqual(fired, [])
        d.hp = 0
        flush()
        self.assertEqual(fired, [d])
        d.hp = -1
        flush()
        self.assertEqual(fired, [d])  # still True — not a new edge
        d.hp = 2
        flush()
        d.hp = 0
        flush()
        self.assertEqual(fired, [d, d])

    def test_instances_are_independent(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5

            @when(lambda self: self.hp <= 0)
            def on_death(self):
                fired.append(self)

        a = self.track(Drone())
        b = self.track(Drone())
        a.hp = 0
        flush()
        self.assertEqual(fired, [a])

    def test_destroy_leaves_registration_inert(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5

            @when(lambda self: self.hp <= 0)
            def on_death(self):
                fired.append(1)

        d = self.track(Drone())
        d.destroy()
        try:
            d.hp = 0
        except Exception:
            pass
        flush()
        self.assertEqual(fired, [])

    def test_destroy_disables_even_when_condition_still_readable(self):
        """``is_alive`` gate — not only ink AttributeError after teardown."""
        fired = []

        class Drone(Circle):
            @when(lambda self: bool(getattr(self, "_go", False)))
            def on_go(self):
                fired.append(1)

        d = self.track(Drone())
        d.destroy()
        object.__setattr__(d, "_go", True)
        flush()
        self.assertFalse(d.is_alive)
        self.assertEqual(fired, [])

    def test_destroy_drops_method_when_ref(self):
        import gc
        import weakref

        class Drone(Circle):
            @when(lambda self: False)
            def on_go(self):
                pass

        d = Drone()
        ref = weakref.ref(d)
        d.destroy()
        del d
        gc.collect()
        self.assertIsNone(ref())

    def test_park_does_not_suppress_method_when(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5

            @when(lambda self: self.hp <= 0)
            def on_death(self):
                fired.append(self)

        d = self.track(Drone())
        d.active = False
        self.assertTrue(d.is_alive)
        d.hp = 0
        flush()
        self.assertEqual(fired, [d])

    def test_module_level_when_unchanged(self):
        c = self.track(Circle())
        c.hp = 5
        fired = []

        @when(lambda: c.hp <= 0)
        def death():
            fired.append(1)

        c.hp = 0
        self.assertEqual(fired, [1])


class TestClassMethodOnChange(ProcessTestCase):
    """``@on_change(lambda self: …)`` on Entity methods — same deferral as ``@when``."""

    def setUp(self):
        super().setUp()
        cleanup_global_event_system()

    def tearDown(self):
        cleanup_global_event_system()
        super().tearDown()

    def test_fires_on_value_change_with_new_value(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5

            @on_change(lambda self: self.hp)
            def on_hp(self, value):
                fired.append((self, value))

        d = self.track(Drone())
        self.assertEqual(fired, [])
        d.hp = 5
        flush()
        self.assertEqual(fired, [])  # same value — no fire
        d.hp = 3
        flush()
        self.assertEqual(fired, [(d, 3)])
        d.hp = 0
        flush()
        self.assertEqual(fired, [(d, 3), (d, 0)])

    def test_zero_arg_callback(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5

            @on_change(lambda self: self.hp)
            def on_hp(self):
                fired.append(self.hp)

        d = self.track(Drone())
        d.hp = 2
        flush()
        self.assertEqual(fired, [2])

    def test_instances_are_independent(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5

            @on_change(lambda self: self.hp)
            def on_hp(self, value):
                fired.append((self, value))

        a = self.track(Drone())
        b = self.track(Drone())
        a.hp = 1
        flush()
        self.assertEqual(fired, [(a, 1)])

    def test_destroy_leaves_registration_inert(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5

            @on_change(lambda self: self.hp)
            def on_hp(self, value):
                fired.append(value)

        d = self.track(Drone())
        d.destroy()
        try:
            d.hp = 0
        except Exception:
            pass
        flush()
        self.assertEqual(fired, [])

    def test_bare_attribute_in_class_body_raises(self):
        from scena import st
        st.x = 0
        with self.assertRaises(TypeError) as ctx:
            class Drone(Circle):
                @on_change(st["x"])
                def watch(self, value):
                    pass
        self.assertIn("@on_change", str(ctx.exception))
        self.assertIn("lambda self", str(ctx.exception))

    def test_module_level_on_change_unchanged(self):
        from scena import st
        st.heat = 10
        fired = []

        @on_change(st["heat"])
        def on_heat(value):
            fired.append(value)

        st.heat = 20
        self.assertEqual(fired, [20])

    def test_stacked_on_change_both_fire(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5
                self.shield = 5

            @on_change(lambda self: self.hp)
            @on_change(lambda self: self.shield)
            def on_stat(self, value):
                fired.append(value)

        d = self.track(Drone())
        d.hp = 3
        flush()
        self.assertEqual(fired, [3])
        fired.clear()
        d.shield = 1
        flush()
        self.assertEqual(fired, [1])


class TestTweenAndTimedPose(ProcessTestCase):
    def test_destroy_cancels_in_flight_tween(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_to(100, 0, time=1.0)
        c.destroy()
        _frame(1.0)
        self.assertTrue(h.cancelled)

    def test_other_owned_tween_cancels_when_target_destroyed(self):
        # Regression: a tween whose *scheduling* owner is a different, live
        # Entity (a Director's mode body calling `wasp.move_to(...)`) used
        # to keep ticking — and still fire on_done — after the actual
        # write target (wasp) was destroyed, because only the scheduling
        # owner's liveness was ever checked.
        director = self.track(Circle(center=(0, 0), radius=4))
        wasp = self.track(Circle(center=(0, 0), radius=8))
        fired = []
        handles = []

        def start(e):
            h = wasp.move_to(100, 0, time=1.0, on_done=lambda: fired.append(1))
            handles.append(h)

        director.mode = start
        h = handles[0]
        self.assertIs(h.owner, director)  # scheduled by the director's mode
        _frame(0.1)
        wasp.destroy()
        for _ in range(20):
            _frame(0.1)
            if h.done:
                break
        self.assertTrue(h.cancelled)
        self.assertEqual(fired, [])

    def test_other_owned_forever_tween_stops_when_target_destroyed(self):
        # Same bug, but with loops="forever" — an uncancelled tween on a
        # destroyed target never ends (a live-forever leak).
        director = self.track(Circle(center=(0, 0), radius=4))
        bee = self.track(Circle(center=(0, 0), radius=5))
        handles = []

        def loopy(e):
            handles.append(bee.move_to(50, 50, time=0.1, loops="forever"))

        director.mode = loopy
        h = handles[0]
        _frame(0.1)
        bee.destroy()
        for _ in range(10):
            _frame(0.1)
        self.assertTrue(h.cancelled or h.done)

    def test_tween_attribute(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        h = tween(c["radius"], 20, time=0.2)
        self.assertIsInstance(h, Handle)
        _frame(0.1)
        self.assertAlmostEqual(float(c.radius), 15.0, places=5)
        _frame(0.1)
        self.assertAlmostEqual(float(c.radius), 20.0, places=5)
        self.assertTrue(h.done)

    def test_tween_point(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        tween(c.center, (100, 50), time=0.2)
        _frame(0.2)
        self.assertAlmostEqual(float(c.center.x), 100.0, places=4)
        self.assertAlmostEqual(float(c.center.y), 50.0, places=4)

    def test_tween_attribute_start(self):
        """start= seeds lap 1; current value is ignored for the range."""
        c = self.track(Circle(center=(0, 0), radius=10))
        h = tween(c["radius"], 20, time=0.2, start=0)
        _frame(0.1)
        self.assertAlmostEqual(float(c.radius), 10.0, places=5)
        _frame(0.1)
        self.assertAlmostEqual(float(c.radius), 20.0, places=5)
        self.assertTrue(h.done)

    def test_tween_point_start(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        tween(c.center, (100, 50), time=0.2, start=(-100, -50))
        _frame(0.1)
        self.assertAlmostEqual(float(c.center.x), 0.0, places=4)
        self.assertAlmostEqual(float(c.center.y), 0.0, places=4)
        _frame(0.1)
        self.assertAlmostEqual(float(c.center.x), 100.0, places=4)
        self.assertAlmostEqual(float(c.center.y), 50.0, places=4)

    def test_tween_omit_start_uses_current(self):
        """Omitting start= keeps today's snapshot-from-current behavior."""
        c = self.track(Circle(center=(0, 0), radius=10))
        tween(c["radius"], 20, time=0.2)
        _frame(0.1)
        self.assertAlmostEqual(float(c.radius), 15.0, places=5)

    def test_tween_start_yoyo_second_lap_returns_to_start(self):
        """start= only seeds lap 1; yoyo still swaps that start/end pair."""
        c = self.track(Circle(center=(0, 0), radius=10))
        h = tween(c["radius"], 20, time=0.1, loops=2, yoyo=True, start=0)
        _frame(0.1)
        self.assertAlmostEqual(float(c.radius), 20.0, places=4)
        _frame(0.1)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.radius), 0.0, places=4)

    def test_entity_tween_start(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        h = c.tween(c["radius"], 20, time=0.2, start=0)
        _frame(0.1)
        self.assertAlmostEqual(float(c.radius), 10.0, places=5)
        _frame(0.1)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.radius), 20.0, places=5)

    def test_later_tween_cancels_earlier(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h1 = c.move_to(100, 0, time=1.0)
        h2 = c.move_to(0, 100, time=1.0)
        _frame(1.0)
        self.assertTrue(h1.cancelled)
        self.assertTrue(h2.done)
        self.assertAlmostEqual(float(c.center.x), 0.0, places=4)
        self.assertAlmostEqual(float(c.center.y), 100.0, places=4)

    def test_multi_key_tween_cancels_all_occupants(self):
        """A Handle on two keys cancels prior occupants of both keys."""
        from scena.process import Handle, _start_tween, get_scheduler

        seen = []

        def write_a(u):
            seen.append(("a", u))

        def write_b(u):
            seen.append(("b", u))

        def write_ab(u):
            seen.append(("ab", u))

        ha = _start_tween(
            duration=1.0, ease="linear", write=write_a, tween_key=("k", "a"),
        )
        hb = _start_tween(
            duration=1.0, ease="linear", write=write_b, tween_key=("k", "b"),
        )
        hab = _start_tween(
            duration=1.0, ease="linear", write=write_ab,
            tween_keys=(("k", "a"), ("k", "b")),
        )
        self.assertTrue(ha.cancelled)
        self.assertTrue(hb.cancelled)
        sched = get_scheduler()
        self.assertIs(sched._tweens[("k", "a")], hab)
        self.assertIs(sched._tweens[("k", "b")], hab)
        _frame(1.0)
        self.assertTrue(hab.done)
        self.assertTrue(any(tag == "ab" for tag, _ in seen))
        self.assertFalse(any(tag == "a" for tag, _ in seen))
        self.assertFalse(any(tag == "b" for tag, _ in seen))

    def test_move_to_without_time_returns_self(self):
        c = self.track(Circle(center=(10, 10), radius=8))
        out = c.move_to(40, 50)
        self.assertIs(out, c)
        self.assertAlmostEqual(float(c.center.x), 40.0, places=5)

    def test_move_to_with_time_returns_handle(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_to(80, 0, time=0.4, ease="linear")
        self.assertIsInstance(h, Handle)
        _frame(0.2)
        self.assertAlmostEqual(float(c.center.x), 40.0, places=4)
        _frame(0.2)
        self.assertAlmostEqual(float(c.center.x), 80.0, places=4)

    def test_ease_in_is_not_linear(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        c.move_to(100, 0, time=1.0, ease="ease_in")
        _frame(0.5)
        # cubic ease_in(0.5) = 0.125 → x=12.5, not 50
        self.assertAlmostEqual(float(c.center.x), 12.5, places=4)

    def test_unknown_ease_lists_names(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        with self.assertRaises(ValueError) as ctx:
            c.move_to(10, 10, time=0.1, ease="easein")
        msg = str(ctx.exception)
        self.assertIn("ease_in", msg)
        self.assertIn("linear", msg)
        self.assertNotIn("spring", msg)

    def test_rotate_to_shortest_arc_ccw_180(self):
        self.assertAlmostEqual(shortest_delta_deg(350, 10), 20.0)
        self.assertAlmostEqual(shortest_delta_deg(10, 350), -20.0)
        self.assertAlmostEqual(shortest_delta_deg(0, 180), 180.0)
        c = self.track(Circle())
        c.rotate_to(350)
        h = c.rotate_to(10, time=0.2)
        _frame(0.1)
        self.assertAlmostEqual(c.angle % 360.0, 0.0, places=4)     # the short way
        _frame(0.1)
        self.assertTrue(h.done)
        # Q2: it ends exactly on the target, as the instant form does (it read 370).
        self.assertEqual(float(c.angle), 10.0)
        for kind in (lambda: Rect(center=(0, 0), width=10, height=4),
                     lambda: Line(p1=(0, 0), p2=(10, 0)), lambda: Polygon(points=[(0, 0), (5, 0), (3, 4)])):
            o = self.track(kind())
            o.rotate_by(400)
            o.rotate_to(30, time=0.2)
            _frame(0.2)
            self.assertAlmostEqual(float(o.angle), 30.0, places=9)

    def test_rotate_by_uses_signed_delta(self):
        c = self.track(Circle())
        c.rotate_to(0)
        c.rotate_by(270, time=0.1)  # longer than shortest; as written
        _frame(0.1)
        self.assertAlmostEqual(c.angle, 270.0, places=4)

    def test_scale_to_timed(self):
        c = self.track(Circle(center=(200, 200), radius=20))
        start = c.scale
        c.scale_to(start * 2, time=0.2)
        _frame(0.2)
        self.assertAlmostEqual(c.scale, start * 2, places=4)

    def test_then_on_timed_move_to(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []

        def landed(e):
            seen.append("landed")

        def enter(e):
            e.move_to(40, 0, time=0.2, then=landed)

        c.mode = enter
        _frame(0.2)
        self.assertEqual(seen, ["landed"])
        self.assertEqual(c.mode, landed)

    def test_mode_change_cancels_timed_move(self):
        c = self.track(Circle(center=(0, 0), radius=8))

        def diving(e):
            e.move_to(200, 0, time=1.0)

        def dying(e):
            pass

        c.mode = diving
        h = next(iter(get_scheduler()._handles))
        c.mode = dying
        self.assertTrue(h.cancelled)
        _frame(1.0)
        self.assertLess(float(c.center.x), 50.0)

    def test_linked_tween_refuses(self):
        a = self.track(Circle(center=(0, 0), radius=8))
        b = self.track(Circle(center=(10, 0), radius=8))
        a.center["x"] @= lambda: b.center.x
        with self.assertRaises(LinkedAttributeError):
            tween(a.center, (40, 0), time=0.2)

    def test_fn_and_then_on_after_item(self):
        c = self.track(Circle())

        def boom():
            pass

        def next_mode(e):
            pass

        with self.assertRaises(TypeError):
            c.after(0.1, boom, then=next_mode)

    def test_after_on_done_alias(self):
        c = self.track(Circle())
        n = []
        c.after(0.1, on_done=lambda: n.append(1))
        _frame(0.15)
        self.assertEqual(n, [1])

    def test_after_on_done_bound_destroy(self):
        c = self.track(Circle())
        c.after(0.1, on_done=c.destroy)
        _frame(0.15)
        self.assertFalse(c.is_alive)

    def test_after_fn_and_on_done_raises(self):
        c = self.track(Circle())
        with self.assertRaises(TypeError) as ctx:
            c.after(0.1, lambda: None, on_done=lambda: None)
        self.assertIn("same channel", str(ctx.exception))

    def test_after_on_done_and_then_raises(self):
        c = self.track(Circle())

        def next_mode(e):
            pass

        with self.assertRaises(TypeError) as ctx:
            c.after(0.1, on_done=lambda: None, then=next_mode)
        self.assertIn("not both", str(ctx.exception))

    def test_move_to_on_done_fires(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []
        c.move_to(40, 0, time=0.2, on_done=lambda s: seen.append(s))
        _frame(0.2)
        self.assertEqual(seen, [c])
        self.assertAlmostEqual(float(c.center.x), 40.0, places=4)

    def test_move_to_then_and_on_done_raises(self):
        c = self.track(Circle(center=(0, 0), radius=8))

        def landed(e):
            pass

        with self.assertRaises(TypeError):
            c.move_to(40, 0, time=0.2, then=landed, on_done=lambda: None)

    def test_instant_move_to_then_raises(self):
        c = self.track(Circle(center=(0, 0), radius=8))

        def landed(e):
            pass

        with self.assertRaises(TypeError) as ctx:
            c.move_to(40, 0, then=landed)
        self.assertIn("time=", str(ctx.exception))

    def test_instant_move_to_on_done_raises(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        with self.assertRaises(TypeError) as ctx:
            c.move_to(40, 0, on_done=lambda: None)
        self.assertIn("time=", str(ctx.exception))

    def test_tween_on_done_fires(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []
        tween(c["radius"], 20, time=0.15, on_done=lambda: seen.append(1))
        _frame(0.2)
        self.assertEqual(seen, [1])
        self.assertAlmostEqual(float(c.radius), 20.0, places=4)

    def test_tween_on_done_error_propagates(self):
        c = self.track(Circle(center=(0, 0), radius=8))

        def boom():
            raise RuntimeError("on_done bug")

        h = tween(c["radius"], 20, time=0.15, on_done=boom)
        with self.assertRaisesRegex(RuntimeError, "on_done bug"):
            _frame(0.2)
        self.assertTrue(h.done)

    def test_tween_write_error_cancels_and_raises(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = tween(c["radius"], 20, time=1.0)

        def bad_write(u):
            raise RuntimeError("write bug")

        h._tween_write = bad_write
        with self.assertRaisesRegex(RuntimeError, "write bug"):
            _frame(0.1)
        self.assertTrue(h.cancelled)

    def test_tween_replace_skips_first_on_done(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []
        h1 = tween(c["radius"], 20, time=1.0, on_done=lambda: seen.append("first"))
        h2 = tween(c["radius"], 30, time=0.1, on_done=lambda: seen.append("second"))
        self.assertTrue(h1.cancelled)
        _frame(0.15)
        self.assertEqual(seen, ["second"])

    def test_cancel_mid_tween_skips_on_done(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []
        h = c.move_to(100, 0, time=1.0, on_done=lambda: seen.append(1))
        h.cancel()
        _frame(0.2)
        self.assertEqual(seen, [])

    def test_destroy_mid_tween_skips_on_done(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []
        c.move_to(100, 0, time=1.0, on_done=lambda: seen.append(1))
        c.destroy()
        _frame(0.2)
        self.assertEqual(seen, [])

    def test_mode_change_cancels_timed_move_skips_on_done(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []

        def diving(e):
            e.move_to(200, 0, time=1.0, on_done=lambda: seen.append(1))

        def dying(e):
            pass

        c.mode = diving
        c.mode = dying
        _frame(1.0)
        self.assertEqual(seen, [])

    def test_move_by_timed_cartesian(self):
        c = self.track(Circle(center=(10, 20), radius=8))
        h = c.move_by(30, -10, time=0.2)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.center.x), 40.0, places=4)
        self.assertAlmostEqual(float(c.center.y), 10.0, places=4)

    def test_move_by_timed_polar(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(angle=90, distance=40, time=0.15)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.center.x), 0.0, places=4)
        self.assertAlmostEqual(float(c.center.y), 40.0, places=4)

    def test_scale_by_timed_matches_scale_to(self):
        a = self.track(Circle(center=(100, 100), radius=10))
        b = self.track(Circle(center=(200, 100), radius=10))
        start = float(a.scale)
        a.scale_by(2, time=0.2)
        b.scale_to(start * 2, time=0.2)
        _frame(0.2)
        self.assertAlmostEqual(float(a.scale), float(b.scale), places=4)
        self.assertAlmostEqual(float(a.scale), start * 2, places=4)

    def test_move_to_cancels_in_flight_move_by(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h1 = c.move_by(200, 0, time=1.0)
        h2 = c.move_to(10, 0, time=0.1)
        self.assertTrue(h1.cancelled)
        _frame(0.15)
        self.assertTrue(h2.done)
        self.assertAlmostEqual(float(c.center.x), 10.0, places=4)

    def test_scale_to_cancels_in_flight_scale_by(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        start = float(c.scale)
        h1 = c.scale_by(3, time=1.0)
        h2 = c.scale_to(start * 1.5, time=0.1)
        self.assertTrue(h1.cancelled)
        _frame(0.15)
        self.assertTrue(h2.done)
        self.assertAlmostEqual(float(c.scale), start * 1.5, places=4)

    def test_move_by_timed_on_done(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []
        c.move_by(20, 0, time=0.1, on_done=lambda: seen.append(1))
        _frame(0.15)
        self.assertEqual(seen, [1])

    def test_scale_by_timed_then(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []

        def grown(e):
            seen.append("grown")

        def enter(e):
            e.scale_by(2, time=0.15, then=grown)

        c.mode = enter
        _frame(0.2)
        self.assertEqual(seen, ["grown"])
        self.assertEqual(c.mode, grown)

    def test_circle_scale_by_timed_via_install(self):
        """Subclass override still accepts time= via _install_timed_pose."""
        c = self.track(Circle(center=(50, 50), radius=12))
        start = float(c.scale)
        h = c.scale_by(2.5, time=0.1)
        _frame(0.15)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.scale), start * 2.5, places=4)

    def test_rect_scale_by_timed_via_install(self):
        from scena import Rect
        r = self.track(Rect(center=(50, 50), width=40, height=20))
        start = float(r.scale)
        h = r.scale_by(2, time=0.1)
        _frame(0.15)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(r.scale), start * 2, places=4)

    def test_yoyo_scale_bounces(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        start = float(c.scale)
        end = start * 1.5
        h = c.scale_to(end, time=0.2, loops="forever", yoyo=True)
        _frame(0.2)
        self.assertAlmostEqual(float(c.scale), end, places=4)
        self.assertEqual(h._lap, 1)
        _frame(0.2)
        self.assertAlmostEqual(float(c.scale), start, places=4)
        self.assertEqual(h._lap, 2)
        self.assertFalse(h.done)
        h.cancel()

    def test_yoyo_finite_parity_rests_at_start_or_end(self):
        a = self.track(Circle(center=(0, 0), radius=8))
        b = self.track(Circle(center=(50, 0), radius=8))
        start = float(a.scale)
        end = start * 2
        ha = a.scale_to(end, time=0.1, loops=2, yoyo=True)
        hb = b.scale_to(end, time=0.1, loops=3, yoyo=True)
        for _ in range(4):
            _frame(0.1)
        self.assertTrue(ha.done)
        self.assertTrue(hb.done)
        self.assertAlmostEqual(float(a.scale), start, places=4)  # even → start
        self.assertAlmostEqual(float(b.scale), end, places=4)  # odd → end

    def test_loops_rejects_bool_and_fraction(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        with self.assertRaises(ValueError):
            c.move_by(10, 0, time=0.2, loops=1.5)
        with self.assertRaises(ValueError):
            c.move_by(10, 0, time=0.2, loops=True)
        h = c.move_by(10, 0, time=0.2, loops=2.0)
        self.assertEqual(h._loops, 2)
        h.cancel()

    def test_yoyo_forever_never_fires_on_done(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []
        h = c.scale_to(2, time=0.1, loops="forever", yoyo=True, on_done=lambda: seen.append(1))
        _frame(0.5)
        self.assertFalse(h.done)
        self.assertEqual(seen, [])
        h.cancel()

    def test_yoyo_requires_loops_gt_one(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        with self.assertRaises(ValueError):
            c.scale_to(2, time=0.2, yoyo=True)
        with self.assertRaises(ValueError):
            c.scale_to(2, time=0.2, loops=1, yoyo=True)

    def test_loops_without_time_raises(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        with self.assertRaises(TypeError):
            c.scale_to(2, loops=2)
        with self.assertRaises(TypeError):
            c.move_by(10, 0, yoyo=True)

    def test_yoyo_move_by_bounces(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(100, 0, time=0.2, loops=2, yoyo=True)
        _frame(0.2)
        self.assertAlmostEqual(float(c.center.x), 100.0, places=3)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.center.x), 0.0, places=3)

    def test_yoyo_tween_attribute(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        h = tween(c["radius"], 20, time=0.1, loops=2, yoyo=True)
        _frame(0.1)
        self.assertAlmostEqual(float(c.radius), 20.0, places=4)
        _frame(0.1)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.radius), 10.0, places=4)

    def test_yoyo_via_install_on_circle(self):
        """Subclass override path (_install_timed_pose) accepts loops/yoyo."""
        c = self.track(Circle(center=(50, 50), radius=12))
        start = float(c.scale)
        h = c.scale_by(2, time=0.1, loops=2, yoyo=True)
        _frame(0.1)
        _frame(0.1)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.scale), start, places=4)

    def test_link_mid_tween_raises_immediately(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        h = tween(c["radius"], 20, time=1.0)
        with self.assertRaises(LinkedAttributeError) as ctx:
            c["radius"] @= Attribute(5.0)
        self.assertIn("tween", str(ctx.exception))
        h.cancel()
        c["radius"] @= Attribute(7.0)
        self.assertAlmostEqual(float(c.radius), 7.0, places=5)

    def test_link_mid_move_to_raises_immediately(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_to(100, 0, time=1.0)
        src = self.track(Circle(center=(1, 2), radius=1)).center
        with self.assertRaises(LinkedAttributeError):
            c.center @= src
        h.cancel()
        c.center @= src
        self.assertAlmostEqual(float(c.center.x), 1.0, places=4)

    def test_process_claim_releases_on_natural_finish(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        h = tween(c["radius"], 20, time=0.2)
        _frame(0.2)
        self.assertTrue(h.done)
        c["radius"] @= Attribute(3.0)
        self.assertAlmostEqual(float(c.radius), 3.0, places=5)

    def test_process_claim_releases_on_destroy(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        h = c.move_to(100, 0, time=1.0)  # entity-scoped — dies with c
        c.destroy()
        _frame(0.1)  # scheduler drops handles whose owner is gone
        self.assertTrue(h.cancelled)
        other = self.track(Circle(center=(0, 0), radius=5))
        other.center @= self.track(Circle(center=(3, 4), radius=1)).center
        self.assertAlmostEqual(float(other.center.x), 3.0, places=4)

    def test_same_key_tween_replace_warns(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            h1 = tween(c["radius"], 20, time=1.0)
            h2 = tween(c["radius"], 30, time=1.0)
            msgs = [
                str(x.message)
                for x in w
                if issubclass(x.category, RuntimeWarning)
                and "replaces" in str(x.message)
            ]
        self.assertTrue(msgs)
        self.assertTrue(h1.cancelled)
        self.assertFalse(h2.cancelled)

    def test_draggable_composes_with_move_to_in_flight(self):
        """Only a formula is exclusive: declaring draggable while a timed
        move claims center is allowed (it used to raise in this order only —
        the reverse order was always allowed)."""
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_to(100, 0, time=1.0)
        c.draggable = True
        self.assertTrue(c.draggable)
        self.assertFalse(h.cancelled)
        _frame(1.0)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(c.center.x), 100.0, places=4)

    def test_move_to_point_line_never_wakes_cold_center(self):
        """Regression (Finding 8): a point-based Line's ``.center`` is a cold
        Derivate. Naming the tween key used to read ``id(getattr(shape,
        "center", shape))``, which force-materialized it just to compute a
        dict key — permanently costing the shape its pose fast path even
        though the move never touches ``.center`` at all (POINT_POINT writes
        p1/p2). ``move_to`` must run to completion without ever putting
        "center" in the instance ``__dict__``.
        """
        from scena.shapes import LineModel
        line = self.track(Line(p1=(0, 0), p2=(100, 0)))
        self.assertEqual(line.model, LineModel.POINT_POINT)
        self.assertNotIn("center", line.__dict__)
        h = line.move_to(50, 50, time=0.2)
        _frame(0.1)
        self.assertNotIn("center", line.__dict__)
        _frame(0.1)
        self.assertTrue(h.done)
        self.assertNotIn("center", line.__dict__)
        # move_to(50, 50) puts the segment's midpoint at (50, 50): the
        # original midpoint (50, 0) needed a +(0, 50) delta.
        self.assertAlmostEqual(float(line.p1.x), 0.0, places=4)
        self.assertAlmostEqual(float(line.p1.y), 50.0, places=4)
        self.assertAlmostEqual(float(line.p2.x), 100.0, places=4)
        self.assertAlmostEqual(float(line.p2.y), 50.0, places=4)

    def test_link_mid_move_to_raises_on_line_p1_not_center(self):
        """Regression (Finding 8): claim_targets used to always be
        ``(shape.center,)``, so a concurrent link on the part actually
        written by the move (``p1``/``p2`` for a point-based Line) would
        *not* raise — it would silently fight the tween instead of getting
        the loud ``LinkedAttributeError`` every other persistent driver
        gets. ``_move_claim_targets`` (reusing ``_parts_written_by_drag``)
        must protect ``p1``/``p2`` directly.
        """
        line = self.track(Line(p1=(0, 0), p2=(100, 0)))
        h = line.move_to(50, 50, time=1.0)
        src = self.track(Circle(center=(1, 2), radius=1))
        with self.assertRaises(LinkedAttributeError) as ctx:
            line.p1 @= src.center
        self.assertIn("move_to(time=1) pushes it", str(ctx.exception))
        # The claim check itself must not have woken the cold center either.
        self.assertNotIn("center", line.__dict__)
        h.cancel()
        line.p1 @= src.center
        self.assertAlmostEqual(float(line.p1.x), 1.0, places=4)

    def test_move_to_center_length_angle_line_still_claims_center(self):
        """Home model (``center`` Defining) keeps prior behavior: the key
        and claim are still ``.center`` itself — no regression for the one
        Line model where ``.center`` is what ``_move_by`` actually writes.
        """
        from scena.shapes import LineModel
        line = self.track(Line(center=(0, 0), length=100, angle=0))
        self.assertEqual(line.model, LineModel.CENTER_LENGTH_ANGLE)
        h = line.move_to(50, 50, time=1.0)
        # Defining here — materializing it is exactly what `_move_by` does
        # anyway, so this is expected (unlike the point-based model above).
        self.assertIn("center", line.__dict__)
        other = self.track(Circle(center=(1, 2), radius=1))
        with self.assertRaises(LinkedAttributeError) as ctx:
            line.center @= other.center
        self.assertIn("move_to(time=1) pushes it", str(ctx.exception))
        h.cancel()

    def test_link_mid_move_to_raises_on_polygon_vertex_not_centroid(self):
        """Regression (Finding 8): Polygon's ``.center`` is always a
        Derivate alias for ``.centroid`` (vertex-average) — the move writes
        vertices, never centroid. A concurrent link on a vertex during a
        ``move_to`` tween must raise, protecting the part actually driven.
        """
        poly = self.track(Polygon(points=[(0, 0), (10, 0), (10, 10)]))
        h = poly.move_to(5, 5, time=1.0)
        other = self.track(Circle(center=(9, 9), radius=1))
        with self.assertRaises(LinkedAttributeError) as ctx:
            poly.points[0] @= other.center
        self.assertIn("move_to(time=1) pushes it", str(ctx.exception))
        h.cancel()

    def test_move_along_point_line_never_wakes_cold_center(self):
        """Same cold-Derivate hazard as move_to, for the move_along path
        (``timed_move_along`` shares ``_center_pose_key`` /
        ``_move_claim_targets`` at a second call site)."""
        line = self.track(Line(p1=(0, 0), p2=(100, 0)))
        h = line.move_along("eight", time=0.2)
        _frame(0.1)
        _frame(0.1)
        self.assertTrue(h.done)
        self.assertNotIn("center", line.__dict__)


class TestTimedVerbsGateAtTheCall(ProcessTestCase):
    """A timed verb refuses (or unlinks with ``force=True``) at the call,
    exactly where its instant form does, and never from a later tick after
    part of the motion ran (GX4 / GX17 in Testing Design; the class guard is
    ``test_geom_structure.TestTimedVerbsGateLikeInstant``)."""

    def _linked(self, obj, part):
        from scena import State
        st = State(name="gate")
        st.x = 0.0
        obj[part] @= lambda: (st.x, 0.0)
        return obj

    def test_scale_and_move_to_refuse_a_linked_part_at_the_call(self):
        for verb in (lambda r: r.scale_by(1.5, time=0.2), lambda r: r.scale_to(2, time=0.2),
                     lambda r: r.move_to(5, 5, time=0.2), lambda r: r.move_by(7, -3, time=0.2)):
            r = self.track(self._linked(Rect(p1=(0, 0), p2=(10, 0), height=3, anchor="cap"), "p1"))
            before = (float(r.p2.x), float(r.p2.y), float(r.height))
            with self.assertRaises(LinkedAttributeError):
                verb(r)
            _frame(0.5)
            self.assertEqual((float(r.p2.x), float(r.p2.y), float(r.height)), before)

    def test_force_unlinks_at_the_call_and_the_motion_runs(self):
        r = self.track(self._linked(Rect(p1=(0, 0), p2=(10, 0), height=3, anchor="cap"), "p1"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r.scale_by(2, time=0.2, force=True)
        self.assertFalse(r["p1"].is_linked)
        for _ in range(4):
            _frame(0.1)
        self.assertAlmostEqual(float(r.height), 6.0)

    def test_a_turn_about_a_linked_center_runs_timed_as_instant(self):
        # GX17: the instant turn about a linked center runs (the center sits
        # on the pivot); the timed one was refused.
        c = self.track(self._linked(Circle(center=(0, 0), radius=8), "center"))
        c.rotate_by(30, time=0.2)
        for _ in range(4):
            _frame(0.1)
        self.assertAlmostEqual(float(c.angle), 30.0)

    def test_a_tangent_line_refuses_a_timed_move(self):
        c = self.track(Circle(center=(0, 0), radius=9))
        ln = self.track(Line(circle=c, from_point=(30, 0), side="left"))
        for verb in (lambda: ln.move_by(7, -3, time=0.2), lambda: ln.move_to(5, 5, time=0.2)):
            with self.assertRaises(LinkedAttributeError):
                verb()

    def test_a_link_on_what_a_running_motion_writes_is_refused_at_the_link(self):
        # GX6: a turn claimed only ``angle``, so a whole ``@=`` or a link on a
        # point the turn moves was accepted, and the next tick raised.
        from scena import State
        st = State(name="gx6")
        st.x = 0.0
        r = self.track(Rect(center=(0, 0), width=10, height=4))
        src = self.track(r.clone())
        r.rotate_by(90, time=1.0)
        _frame(0.3)
        with self.assertRaises(LinkedAttributeError) as ctx:
            r @= lambda: src
        self.assertIn("pushes it", str(ctx.exception))
        ln = self.track(Line(p1=(0, 0), p2=(10, 0)))
        ln.scale_by(2, time=1.0)
        _frame(0.3)
        with self.assertRaises(LinkedAttributeError):
            ln["p2"] @= lambda: (st.x, 0.0)
        # A point on the pivot is not written: a turning Circle's center may link.
        c = self.track(Circle(center=(0, 0), radius=5))
        c.rotate_by(90, time=1.0)
        _frame(0.3)
        c["center"] @= lambda: (st.x, 0.0)
        for _ in range(10):
            _frame(0.1)                     # nothing raises from a tick
        self.assertAlmostEqual(float(r.angle), 90.0)
        self.assertAlmostEqual(float(c.angle), 90.0)

    def test_a_sheet_sprite_does_not_jump_at_the_call(self):
        # The old move_to probe placed the center on the art-frame pivot first.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import geom_axes as A
        s = self.track(A.build("Sprite sheet pair"))
        s.flip_x = True
        s.move_to(60, 40, time=0.2)
        self.assertEqual((float(s.center.x), float(s.center.y)), (3.0, -2.0))
        for _ in range(4):
            _frame(0.1)
        self.assertAlmostEqual(float(s.center.x), 60.0)
        self.assertAlmostEqual(float(s.center.y), 40.0)


class TestEasingCatalog(ProcessTestCase):
    def test_remap_unknown_lists_names(self):
        from scena import remap
        with self.assertRaises(ValueError) as ctx:
            remap(0.5, 0, 1, 0, 1, modifier="not_an_ease")
        self.assertIn("linear", str(ctx.exception))

    def test_spring_still_available_on_mapping_functions(self):
        from scena.easing import MappingFunctions
        from scena import remap
        self.assertAlmostEqual(MappingFunctions.spring(0.0), 0.5)
        self.assertAlmostEqual(MappingFunctions.spring(1.0), 0.5)
        # remap extras still include spring; tween catalog does not.
        out = remap(0.0, 0, 1, 0, 1, modifier="spring")
        self.assertAlmostEqual(out, 0.5)


class TestFrozenModeWarning(ProcessTestCase):
    """AC7 (game system tests): Actors Design, "Frozen-mode warning only if
    nothing is pending past FROZEN_MODE_S" — idle time, not time in the mode.
    The check compared the mode's age: a mode whose async body waited 2 s
    (``await until_empty`` on a wave, the Guia's Director pattern) and then
    started a cover fade before ``change_act`` warned on its first idle frame."""

    def _frozen(self, caught):
        return [w for w in caught if "frozen" in str(w.message)]

    def test_idle_time_counts_not_mode_age(self):
        c = self.track(Circle(radius=4, group="ac7_wave"))
        e = self.track(Entity())

        async def directing(owner):
            await until_empty("ac7_wave")      # busy: a pending await

        e.mode = directing
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(int(FROZEN_MODE_S / 0.1) + 6):     # 2.6 s waiting
                _frame(0.1)
            self.assertFalse(self._frozen(caught), "a pending await is not frozen")
            c.destroy()
            _frame(0.1)                                      # the body ends
            for _ in range(int(FROZEN_MODE_S / 0.1) - 2):    # idle 1.8 s
                _frame(0.1)
            self.assertFalse(self._frozen(caught), "idle for less than FROZEN_MODE_S")
            for _ in range(4):
                _frame(0.1)
            self.assertEqual(len(self._frozen(caught)), 1, "idle past FROZEN_MODE_S warns once")

    def test_sync_mode_with_nothing_pending_still_warns(self):
        e = self.track(Entity())

        def parked(owner):
            pass

        e.mode = parked
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # Nothing ever ran in this mode: idle since it began, so the
            # warning comes as the mode passes FROZEN_MODE_S, not later.
            for _ in range(int(FROZEN_MODE_S / 0.1) - 1):
                _frame(0.1)
            self.assertFalse(self._frozen(caught))
            for _ in range(3):
                _frame(0.1)
            self.assertEqual(len(self._frozen(caught)), 1)
            for _ in range(30):
                _frame(0.1)
        self.assertEqual(len(self._frozen(caught)), 1, "warns once")

    def test_idle_counts_from_the_last_timer(self):
        # A sync mode whose timer ran 1.5 s: idle from the timer's end.
        e = self.track(Entity())

        def timed(owner):
            owner.after(1.5, lambda: None)

        e.mode = timed
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(int((1.5 + FROZEN_MODE_S) / 0.1) - 2):    # idle 1.8 s
                _frame(0.1)
            self.assertFalse(self._frozen(caught), "idle for less than FROZEN_MODE_S")
            for _ in range(4):
                _frame(0.1)
        self.assertEqual(len(self._frozen(caught)), 1)

    def test_a_new_mode_restarts_the_idle_clock(self):
        e = self.track(Entity())

        def a(owner):
            pass

        def b(owner):
            pass

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            e.mode = a
            for _ in range(15):
                _frame(0.1)
            e.mode = b
            for _ in range(15):
                _frame(0.1)
        self.assertFalse(self._frozen(caught))


class TestNamedTweenSlotReplacesQuietly(ProcessTestCase):
    """AC13 (game system tests, Armada's random pilots): a second
    ``tween(st["escudo"], 0, time=3, name="escudo")`` while the first runs
    warned "tween/move_along on the same property replaces a previous
    in-flight tween". The Guia: a tween with the same ``name=`` in the same
    place "substitui o anterior" — the slot is the author saying so. The
    same-property preempt ran before the slot and warned. Two tweens on one
    property that the author did not put in one slot still warn."""

    def _warned(self, fn):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fn()
        return [str(w.message) for w in caught if "in-flight" in str(w.message)]

    def test_same_slot_on_a_cell_is_quiet(self):
        a = Attribute(1.0)
        h1 = tween(a, 0.0, time=3.0, name="ac13")
        _frame(0.5)
        box = []
        self.assertEqual(self._warned(lambda: box.append(tween(a, 0.0, time=3.0, name="ac13"))), [])
        self.assertTrue(h1.cancelled)
        self.assertFalse(box[0].cancelled)

    def test_same_slot_on_a_field_is_quiet(self):
        c = self.track(Circle(radius=4))
        c.hp = 1.0
        tween(c["hp"], 0.0, time=3.0, name="ac13f")
        _frame(0.5)
        self.assertEqual(self._warned(lambda: tween(c["hp"], 0.0, time=3.0, name="ac13f")), [])

    def test_unnamed_or_other_slot_still_warns(self):
        a = Attribute(1.0)
        tween(a, 0.0, time=3.0)
        _frame(0.1)
        self.assertEqual(len(self._warned(lambda: tween(a, 0.0, time=3.0))), 1)
        b = Attribute(1.0)
        tween(b, 0.0, time=3.0, name="one")
        _frame(0.1)
        self.assertEqual(len(self._warned(lambda: tween(b, 0.0, time=3.0, name="two"))), 1)


class TestAsyncAwait(ProcessTestCase):
    def test_await_move_to_then_continues(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []

        async def diving(e):
            await e.move_to(80, 0, time=0.2)
            seen.append(float(e.center.x))
            await wait(0.1)
            seen.append("done")

        c.mode = diving
        _frame(0.2)
        self.assertEqual(len(seen), 1)
        self.assertAlmostEqual(seen[0], 80.0, places=4)
        _frame(0.1)
        self.assertEqual(seen[-1], "done")

    def test_mode_change_raises_cancelled_finally_runs(self):
        c = self.track(Circle())
        log = []

        async def diving(e):
            try:
                await wait(10.0)
                log.append("resumed")
            except Cancelled:
                log.append("cancelled")
                raise
            finally:
                log.append("finally")

        def dying(e):
            log.append("dying")

        c.mode = diving
        c.mode = dying
        self.assertEqual(log, ["cancelled", "finally", "dying"])
        _frame(0.5)
        self.assertNotIn("resumed", log)

    def test_except_exception_does_not_swallow_cancelled(self):
        c = self.track(Circle())
        swallowed = []

        async def diving(e):
            try:
                await wait(10.0)
            except Exception:
                swallowed.append(1)

        c.mode = diving
        c.mode = None
        self.assertEqual(swallowed, [])

    def test_destroy_while_waiting_is_silent(self):
        c = self.track(Circle())

        async def diving(e):
            await wait(10.0)

        c.mode = diving
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            c.destroy()
            _frame(0.2)
        process_warns = [
            w for w in caught
            if "async" in str(w.message).lower() or "Exception" in str(w.message)
        ]
        self.assertEqual(process_warns, [])

    def test_awaited_tween_preempted_by_key_warns_and_stops_mode(self):
        # Regression: unlike a deliberate `Script.cancel()` (mode switch,
        # owner destroyed — both silent by design), a *different* tween
        # claiming the same property while a mode is `await`ing it raised
        # `Cancelled` straight into the coroutine with zero warning. The
        # mode died silently while `e.mode` kept reporting the dead function.
        c = self.track(Circle(center=(0, 0), radius=5))
        ran_after_await = []

        async def diving(e):
            await e.move_to(100, 100, time=1.0)
            ran_after_await.append(1)

        c.mode = diving
        _frame(0.05)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            c.move_to(50, 50, time=1.0)  # same-key preemption
            _frame(0.05)
        silent_kill_warns = [
            w for w in caught
            if "silently cancelled" in str(w.message)
        ]
        self.assertEqual(len(silent_kill_warns), 1)
        self.assertIn("diving", str(silent_kill_warns[0].message))
        self.assertEqual(ran_after_await, [])
        # Documented gotcha: `.mode` still names the dead function.
        self.assertIs(c.mode, diving)

    def test_awaited_tween_target_destroyed_warns_and_stops_mode(self):
        # Same "silently cancelled" class, reached via the *other* Handle
        # source: a mode awaits a tween on a *different* entity than its
        # own owner, and that other entity is destroyed mid-flight.
        director = self.track(Circle(center=(-50, -50), radius=3))
        target = self.track(Circle(center=(0, 0), radius=5))
        ran_after_await = []

        async def guide(e):
            await target.move_to(100, 100, time=1.0)
            ran_after_await.append(1)

        director.mode = guide
        _frame(0.05)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            target.destroy()
            _frame(0.05)
        silent_kill_warns = [
            w for w in caught
            if "silently cancelled" in str(w.message)
        ]
        self.assertEqual(len(silent_kill_warns), 1)
        self.assertIn("guide", str(silent_kill_warns[0].message))
        self.assertEqual(ran_after_await, [])

    def test_await_already_done_handle(self):
        c = self.track(Circle())
        seen = []
        h = after(0.0, lambda: None)
        _frame(0.01)
        self.assertTrue(h.done)

        async def diving(e):
            await h
            seen.append("ok")

        c.mode = diving
        self.assertEqual(seen, ["ok"])

    def test_second_wait_is_mode_scoped(self):
        c = self.track(Circle())
        seen = []

        async def diving(e):
            await wait(0.1)
            seen.append("one")
            await wait(10.0)
            seen.append("two")

        c.mode = diving
        _frame(0.1)
        self.assertEqual(seen, ["one"])
        h = next(iter(get_scheduler()._handles))
        self.assertEqual(h.scope, "mode")
        c.mode = None
        _frame(1.0)
        self.assertEqual(seen, ["one"])

    def test_self_assign_mode_at_end_of_async(self):
        c = self.track(Circle())
        seen = []

        def idle(e):
            seen.append("idle")

        async def diving(e):
            await wait(0.1)
            seen.append("dive")
            e.mode = idle

        c.mode = diving
        _frame(0.1)
        self.assertEqual(seen, ["dive", "idle"])
        self.assertEqual(c.mode, idle)

    def test_async_mode_first_chunk_nameerror_raises(self):
        c = self.track(Circle())

        async def diving(e):
            missing.foo()
            await wait(0.1)

        with self.assertRaises(NameError):
            c.mode = diving
        script = getattr(c, "_mode_task", None)
        self.assertTrue(script is None or script.done)
        tick_processes()  # nothing left to resume

    def test_async_later_mode_enter_error_raises(self):
        c = self.track(Circle())

        def broken(e):
            missing.foo()

        async def diving(e):
            await wait(0.1)
            e.mode = broken

        c.mode = diving
        with self.assertRaises(NameError):
            _frame(0.1)
            tick_processes()
        self.assertIs(c.mode, broken)  # transition completed before the raise

    def test_await_cancelled_handle_raises(self):
        h = after(1.0, lambda: None)
        h.cancel()
        gen = h.__await__()
        with self.assertRaises(Cancelled):
            next(gen)

    def test_wait_rejects_bad_delay(self):
        with self.assertRaises(TypeError):
            wait("soon")
        with self.assertRaises(ValueError):
            wait(-1)

    def test_wait_outside_script_raises(self):
        with self.assertRaises(TypeError) as ctx:
            wait(0.4)
        msg = str(ctx.exception)
        self.assertIn("async mode", msg)
        self.assertIn("after(", msg)
        with self.assertRaises(TypeError) as ctx2:
            until(lambda: True)
        self.assertIn("async mode", str(ctx2.exception))
        with self.assertRaises(TypeError) as ctx3:
            until_empty("nope")
        self.assertIn("until_empty()", str(ctx3.exception))

        c = self.track(Circle())

        def idle(e):
            wait(0.4)

        with self.assertRaises(TypeError):
            c.mode = idle

        hits = []

        def on_up(e, dt):
            try:
                wait(0.1)
            except TypeError as err:
                hits.append(str(err))

        c.on_update = on_up
        _frame(0.1)
        self.assertTrue(hits)

    def test_nested_async_helper_wait_and_until(self):
        c = self.track(Circle())
        seen = []

        async def pause(s):
            await wait(s)

        async def diving(e):
            await pause(0.1)
            seen.append("after")
            await until(lambda: True)
            seen.append("done")

        c.mode = diving
        self.assertEqual(seen, [])
        _frame(0.1)
        self.assertEqual(seen, ["after", "done"])

    def test_nested_helper_wait_cancels_on_leave(self):
        c = self.track(Circle())
        seen = []

        async def pause(s):
            await wait(s)
            seen.append("resumed")

        async def diving(e):
            await pause(10.0)
            seen.append("done")

        c.mode = diving
        c.mode = None
        _frame(0.5)
        self.assertEqual(seen, [])

    def test_until_predicate(self):
        c = self.track(Circle())
        c.hp = 3
        seen = []

        async def diving(e):
            await until(lambda: float(e.hp) <= 0)
            seen.append("dead")

        c.mode = diving
        _frame(0.1)
        self.assertEqual(seen, [])
        c.hp = 0
        _frame(0.1)
        self.assertEqual(seen, ["dead"])

    def test_until_predicate_error_cancels_and_raises(self):
        c = self.track(Circle())
        calls = {"n": 0}

        def pred():
            calls["n"] += 1
            if calls["n"] >= 2:
                raise ValueError("predicate bug")
            return False

        async def diving(e):
            await until(pred)

        c.mode = diving
        with self.assertRaisesRegex(ValueError, "predicate bug"):
            _frame(0.1)
        n = calls["n"]
        _frame(0.1)  # cancelled: a broken predicate does not re-raise every frame
        self.assertEqual(calls["n"], n)

    def test_until_predicate_on_destroyed_actor_retires_quietly(self):
        # Regression: `until(lambda: boss.hp <= 0)` reads a destroyed
        # boss's `.hp` and raises DestroyedError out of the process tick —
        # unlike a typo (AttributeError from a real bug), a destroyed
        # source should retire the await quietly, same rule ``@when``
        # already uses (events.py ``_SOURCE_GONE``).
        boss = self.track(Circle())
        boss.hp = 10
        watcher = self.track(Circle())
        seen = []

        async def watch(e):
            await until(lambda: boss.hp <= 0)
            seen.append("boss dead")

        watcher.mode = watch
        _frame(0.1)
        boss.destroy()
        for _ in range(5):
            _frame(0.1)  # must not raise
        self.assertEqual(seen, [])

    def test_await_non_handle_raises(self):
        c = self.track(Circle())

        class NotAHandle:
            def __await__(self):
                yield "nope"

        async def diving(e):
            await NotAHandle()

        with self.assertRaisesRegex(TypeError, "await a Handle"):
            c.mode = diving
        self.assertIsNone(getattr(c, "_mode_task", None))

    def test_until_already_true_does_not_yield(self):
        c = self.track(Circle())
        seen = []

        async def diving(e):
            await until(lambda: True)
            seen.append("now")

        c.mode = diving
        self.assertEqual(seen, ["now"])

    def test_until_non_callable(self):
        with self.assertRaises(TypeError) as ctx:
            until("hp")
        msg = str(ctx.exception)
        self.assertIn("expected a function", msg)
        self.assertIn("until_empty", msg)
        self.assertIn("lambda", msg)

    def test_until_rejects_bool_points_at_until_empty(self):
        with self.assertRaises(TypeError) as ctx:
            until(True)
        self.assertIn("until_empty", str(ctx.exception))
        g = group["no_such_group_yet"]
        with self.assertRaises(TypeError) as ctx2:
            until(g.empty)
        self.assertIn("until_empty", str(ctx2.exception))

    def test_until_boxed_cell(self):
        from scena import st
        st.create("cleared", initial=False)
        c = self.track(Circle())
        seen = []

        async def diving(e):
            await until(st["cleared"])
            seen.append("done")

        c.mode = diving
        _frame(0.1)
        self.assertEqual(seen, [])
        st.cleared = True
        _frame(0.1)
        self.assertEqual(seen, ["done"])

    def test_until_an_objects_field(self):
        # 0.8.0: until() takes any bracket handle, not only a State cell.
        boss = self.track(Circle())
        c = self.track(Circle())
        seen = []

        async def waiting(e):
            await until(boss["dead"])
            seen.append("done")

        boss.dead = False
        c.mode = waiting
        _frame(0.1)
        self.assertEqual(seen, [])
        boss.dead = True
        _frame(0.1)
        self.assertEqual(seen, ["done"])

    def test_until_empty_waits_for_group(self):
        wasp = self.track(Circle(group="until_wasps"))
        director = self.track(Entity())
        seen = []

        async def directing(e):
            await until_empty("until_wasps")
            seen.append("clear")

        director.mode = directing
        _frame(0.1)
        self.assertEqual(seen, [])
        wasp.destroy()
        _frame(0.1)
        self.assertEqual(seen, ["clear"])

    def test_until_empty_does_not_warn_when_the_group_empties(self):
        # Bug: polling went through the author lookup group[name], whose
        # near-miss guard warned once the emptied bucket was dropped
        # ("No group 'inimigo'. Did you mean 'tiro_inimigo'?").
        import warnings
        enemy = self.track(Circle(group="inimigo"))
        self.track(Circle(group="tiro_inimigo"))
        director = self.track(Entity())
        seen = []

        async def directing(e):
            await until_empty("inimigo")
            seen.append("clear")

        director.mode = directing
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _frame(0.1)
            enemy.destroy()
            _frame(0.1)
            _frame(0.1)
        self.assertEqual(seen, ["clear"])
        self.assertEqual([str(w.message) for w in caught if "No group" in str(w.message)], [])

    def test_until_empty_typo_still_warns_at_the_call(self):
        import warnings
        self.track(Circle(group="until_typo_wasp"))
        director = self.track(Entity())

        async def directing(e):
            await until_empty("until_typo_wsp")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            director.mode = directing
        self.assertTrue(any("No group 'until_typo_wsp'" in str(w.message) for w in caught))

    def test_until_empty_live_group_and_already_empty(self):
        director = self.track(Entity())
        seen = []

        async def directing(e):
            await until_empty(group["already_empty"])
            seen.append("now")

        director.mode = directing
        self.assertEqual(seen, ["now"])

    def test_until_empty_rejects_snapshot(self):
        self.track(Circle(group="snap_a"))
        snap = group["snap_a"] | group["snap_b"]
        with self.assertRaises(TypeError):
            until_empty(snap)
        with self.assertRaises(TypeError):
            until_empty(12)

    def test_until_empty_formula_name_and_operator(self):
        wasp = self.track(Circle(group="until_f_wasp"))
        group["until_enemies"] @= lambda: group["until_f_wasp"]
        director = self.track(Entity())
        seen = []

        async def directing(e):
            await until_empty("until_enemies")
            seen.append("name")

        director.mode = directing
        _frame(0.1)
        self.assertEqual(seen, [])
        wasp.destroy()
        _frame(0.1)
        self.assertEqual(seen, ["name"])

        extra = self.track(Circle(group="until_f_wasp2"))
        group["until_enemies2"] @= lambda: group["until_f_wasp2"]
        seen.clear()
        director2 = self.track(Entity())

        async def directing_op(e):
            await until_empty(group["until_enemies2"])
            seen.append("op")

        director2.mode = directing_op
        _frame(0.1)
        self.assertEqual(seen, [])
        extra.destroy()
        _frame(0.1)
        self.assertEqual(seen, ["op"])

    def test_parallel_waits_for_all(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []

        async def diving(e):
            await parallel(
                e.move_to(40, 0, time=0.2),
                wait(0.3),
            )
            seen.append((float(e.center.x), "done"))

        c.mode = diving
        _frame(0.2)
        self.assertEqual(seen, [])
        _frame(0.1)
        self.assertEqual(len(seen), 1)
        self.assertAlmostEqual(seen[0][0], 40.0, places=4)

    def test_race_returns_winner_index_and_cancels_losers(self):
        c = self.track(Circle())
        seen = []

        async def diving(e):
            a = wait(0.3)
            b = wait(0.1)
            idx = await race(a, b)
            seen.append(idx)
            seen.append(a.cancelled)
            seen.append(b.done)

        c.mode = diving
        _frame(0.1)
        self.assertEqual(seen, [1, True, True])

    def test_parallel_and_race_reject_empty_and_non_handles(self):
        with self.assertRaises(TypeError):
            parallel()
        with self.assertRaises(TypeError):
            race()
        with self.assertRaises(TypeError):
            parallel("nope")

    def test_unused_wait_outside_script_raises(self):
        with self.assertRaises(TypeError) as ctx:
            wait(0.05)
        self.assertIn("async mode", str(ctx.exception))

    def test_unused_wait_in_async_mode_raises(self):
        c = self.track(Circle())

        async def diving(e):
            wait(0.3)
            await until(lambda: True)

        with self.assertRaises(TypeError) as ctx:
            c.mode = diving
        self.assertIn("not awaited", str(ctx.exception))
        self.assertIn("await wait", str(ctx.exception))

    def test_cancelled_wait_is_not_a_forgotten_await(self):
        c = self.track(Circle())
        seen = []

        async def diving(e):
            w = wait(0.3)
            w.cancel()
            await wait(0.1)
            seen.append("ok")

        c.mode = diving
        _frame(0.1)
        self.assertEqual(seen, ["ok"])

    def test_unused_wait_before_next_await_raises(self):
        c = self.track(Circle())
        seen = []

        async def diving(e):
            wait(0.3)
            await wait(0.1)
            seen.append("ok")

        with self.assertRaisesRegex(TypeError, "not awaited"):
            c.mode = diving
        self.assertIsNone(getattr(c, "_mode_task", None))  # script aborted
        _frame(0.1)
        self.assertEqual(seen, [])

    def test_wait_time_scale(self):
        c = self.track(Circle())
        seen = []
        c.time_scale = 0.5

        async def diving(e):
            await wait(0.2)
            seen.append(1)

        c.mode = diving
        _frame(0.2)  # effective 0.1
        self.assertEqual(seen, [])
        _frame(0.2)
        self.assertEqual(seen, [1])

    def test_then_warns_if_async_still_running(self):
        c = self.track(Circle())

        def other(e):
            pass

        async def diving(e):
            e.after(0.1, then=other)
            await wait(10.0)

        c.mode = diving
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _frame(0.1)
        msgs = [str(w.message) for w in caught]
        self.assertTrue(any("then=" in m and "await" in m for m in msgs), msgs)
        self.assertEqual(c.mode, other)

    def test_watchdog_stops_spin_loop(self):
        import scena.process as proc
        c = self.track(Circle())
        old = proc.WATCHDOG_RESUME_S
        old_every = proc.WATCHDOG_CHECK_EVERY
        proc.WATCHDOG_RESUME_S = 0.05
        proc.WATCHDOG_CHECK_EVERY = 64
        proc.set_watchdog(True)

        async def spinning(e):
            while True:
                pass

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                c.mode = spinning
            msgs = [str(w.message) for w in caught]
            self.assertTrue(
                any("SCENA ERROR" in m and "CANCELLED" in m for m in msgs),
                msgs,
            )
            self.assertTrue(c.mode == spinning)
            script = getattr(c, "_mode_task", None)
            self.assertTrue(script is None or script.done)
        finally:
            proc.WATCHDOG_RESUME_S = old
            proc.WATCHDOG_CHECK_EVERY = old_every

    def test_watchdog_stops_a_loop_on_one_line(self):
        """A one-line loop emits no new LINE event, only its jump back: it
        ran for as long as it liked (review 2026-10-14 PA2). Each loop is
        capped at 2 s so a regression fails instead of hanging."""
        import time
        import scena.process as proc
        old = proc.WATCHDOG_RESUME_S
        old_every = proc.WATCHDOG_CHECK_EVERY
        proc.WATCHDOG_RESUME_S = 0.05
        proc.WATCHDOG_CHECK_EVERY = 64
        proc.set_watchdog(True)
        st_pronto = []

        async def espera(e):
            t0 = time.perf_counter()
            while not st_pronto and time.perf_counter() - t0 < 2: pass  # noqa: E701
            e.ran = time.perf_counter() - t0

        async def conta(e):
            n, t0 = 0, time.perf_counter()
            while n < 10**9 and time.perf_counter() - t0 < 2: n += 1  # noqa: E701
            e.ran = time.perf_counter() - t0

        try:
            for body in (espera, conta):
                with self.subTest(body=body.__name__):
                    c = self.track(Circle())
                    c.ran = None
                    t0 = time.perf_counter()
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        c.mode = body
                    took = time.perf_counter() - t0
                    msgs = [str(w.message) for w in caught]
                    self.assertTrue(any("CANCELLED" in m for m in msgs), msgs)
                    self.assertIsNone(c.ran, "the loop ran to its own end")
                    self.assertLess(took, 1.0)
        finally:
            proc.WATCHDOG_RESUME_S = old
            proc.WATCHDOG_CHECK_EVERY = old_every

    def test_sync_watchdog_stops_a_loop_on_one_line(self):
        import time
        import scena.process as proc
        old = proc.WATCHDOG_RESUME_S
        old_every = proc.WATCHDOG_CHECK_EVERY
        proc.WATCHDOG_RESUME_S = 0.05
        proc.WATCHDOG_CHECK_EVERY = 64
        proc.set_sync_watchdog(True)

        def spin():
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 2: pass  # noqa: E701

        try:
            t0 = time.perf_counter()
            with self.assertRaises(proc._Watchdog):
                proc._run_with_watchdog(spin, sync=True)
            self.assertLess(time.perf_counter() - t0, 1.0)
        finally:
            proc.WATCHDOG_RESUME_S = old
            proc.WATCHDOG_CHECK_EVERY = old_every
            proc.set_sync_watchdog(False)

    def test_on_update_watchdog_disables_hook(self):
        import scena.process as proc
        c = self.track(Circle())
        old = proc.WATCHDOG_RESUME_S
        old_every = proc.WATCHDOG_CHECK_EVERY
        proc.WATCHDOG_RESUME_S = 0.05
        proc.WATCHDOG_CHECK_EVERY = 64
        proc.set_watchdog(True)
        proc.set_sync_watchdog(True)

        def spin(e, dt):
            while True:
                pass

        c.on_update = spin
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                _frame(0.01)
            msgs = [str(w.message) for w in caught]
            self.assertTrue(
                any("SCENA ERROR" in m and "on_update" in m for m in msgs),
                msgs,
            )
            self.assertIsNone(c.on_update)
        finally:
            proc.WATCHDOG_RESUME_S = old
            proc.WATCHDOG_CHECK_EVERY = old_every
            proc.set_sync_watchdog(False)

    def test_script_update_watchdog_trips(self):
        """Module-level update(dt) is guarded the same way as async resume."""
        import scena.process as proc

        old = proc.WATCHDOG_RESUME_S
        old_every = proc.WATCHDOG_CHECK_EVERY
        proc.WATCHDOG_RESUME_S = 0.05
        proc.WATCHDOG_CHECK_EVERY = 64
        proc.set_watchdog(True)
        proc.set_sync_watchdog(True)

        def spin():
            while True:
                pass

        try:
            with self.assertRaises(proc._Watchdog):
                proc._run_with_watchdog(spin, sync=True)
        finally:
            proc.WATCHDOG_RESUME_S = old
            proc.WATCHDOG_CHECK_EVERY = old_every
            proc.set_sync_watchdog(False)

    def test_watchdog_engine_work_stays_under_budget(self):
        """Engine work must stay under the wall-clock budget (Galaga wave)."""
        from scena.sprite import reset_sprite_caches
        import scena.process as proc

        reset_sprite_caches()
        # Tight budget: settrace-era cost would hitch; monitoring+DISABLE must pass.
        old = proc.WATCHDOG_RESUME_S
        proc.WATCHDOG_RESUME_S = 0.15
        proc.set_watchdog(True)

        class Spawner(Entity):
            async def boom(self):
                for i in range(64):
                    Sprite(center=(i * 10, 100), size=16, group="wd_bulk")
                self.done_ok = True
                await wait(0.05)

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                sp = self.track(Spawner())
                sp.done_ok = False
                sp.mode = sp.boom
                for _ in range(5):
                    _frame(0.05)
            err = [str(w.message) for w in caught if "SCENA ERROR" in str(w.message)]
            self.assertEqual(err, [], err)
            self.assertTrue(sp.done_ok)
            self.assertEqual(len(group["wd_bulk"]), 64)
        finally:
            proc.WATCHDOG_RESUME_S = old
            for e in list(group["wd_bulk"]):
                e.destroy()

    def test_set_watchdog_off_skips_guard(self):
        """``set_watchdog(False)`` allows a long resume that would otherwise cancel."""
        import time
        import scena.process as proc

        old = proc.WATCHDOG_RESUME_S
        old_every = proc.WATCHDOG_CHECK_EVERY
        proc.WATCHDOG_RESUME_S = 0.02
        proc.WATCHDOG_CHECK_EVERY = 32

        class Busy(Entity):
            async def work(self):
                t0 = time.perf_counter()
                while time.perf_counter() - t0 < 0.08:
                    pass
                self.done_ok = True
                await wait(0.01)

        try:
            proc.set_watchdog(True)
            a = self.track(Busy())
            a.done_ok = False
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                a.mode = a.work
            self.assertTrue(
                any("SCENA ERROR" in str(w.message) for w in caught),
                [str(w.message) for w in caught],
            )
            self.assertFalse(a.done_ok)

            proc.set_watchdog(False)
            b = self.track(Busy())
            b.done_ok = False
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                b.mode = b.work
                for _ in range(5):
                    _frame(0.05)
            err = [str(w.message) for w in caught if "SCENA ERROR" in str(w.message)]
            self.assertEqual(err, [], err)
            self.assertTrue(b.done_ok)
        finally:
            proc.set_watchdog(True)
            proc.WATCHDOG_RESUME_S = old
            proc.WATCHDOG_CHECK_EVERY = old_every

    def test_frozen_mode_warns_once(self):
        c = self.track(Circle())

        def idle(e):
            pass

        c.mode = idle
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            steps = int(FROZEN_MODE_S / 0.1) + 2
            for _ in range(steps):
                _frame(0.1)
        msgs = [str(w.message) for w in caught]
        frozen = [m for m in msgs if "frozen" in m]
        self.assertEqual(len(frozen), 1)
        self.assertIn("idle", frozen[0])

    def test_frozen_mode_silent_when_timer_pending(self):
        c = self.track(Circle())

        def idle(e):
            e.after(100.0, lambda: None)

        c.mode = idle
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(int(FROZEN_MODE_S / 0.1) + 2):
                _frame(0.1)
        self.assertFalse(any("frozen" in str(w.message) for w in caught))


class TestOnModeAndExitMode(ProcessTestCase):
    def test_on_mode_tags_method_and_does_not_change_enter(self):
        n = []

        class Drone(Circle):
            @on_mode
            def idle(self):
                n.append("idle")
                self.after(10.0, lambda: n.append("never"))

        d = self.track(Drone())
        self.assertIs(Drone.idle._is_mode, True)
        self.assertIs(d.idle._is_mode, True)
        d.mode = d.idle
        self.assertEqual(n, ["idle"])
        self.assertEqual(d.mode, d.idle)
        h = next(iter(get_scheduler()._handles))
        self.assertEqual(h.scope, "entity")
        d.mode = None
        _frame(0.5)
        # entity-scoped timer survives mode clear
        self.assertEqual(n, ["idle"])
        self.assertFalse(h.cancelled)

    def test_on_mode_tags_classless_function(self):
        @on_mode
        def entering(e):
            pass

        self.assertIs(entering._is_mode, True)
        c = self.track(Circle())
        c.mode = entering
        self.assertEqual(c.mode, entering)

    def test_class_body_scan_collects_tagged_modes_only(self):
        class Actor(Circle):
            @on_mode
            def formation(self):
                pass

            def shoot(self):
                pass

            @on_mode
            def diving(self):
                pass

            def on_update(self, dt):
                pass

        tagged = [
            name for name, val in Actor.__dict__.items()
            if callable(val) and getattr(val, "_is_mode", False)
        ]
        self.assertCountEqual(tagged, ["formation", "diving"])

    def test_exit_mode_attaches_to_enter_callable(self):
        @on_mode
        def charging(e):
            pass

        @exit_mode(charging)
        def charging_exit(e):
            pass

        self.assertIs(charging._exit_mode, charging_exit)
        c = self.track(Circle())
        c.mode = charging
        self.assertIs(c.mode._exit_mode, charging_exit)

    def test_exit_hook_runs_once_before_next_body(self):
        order = []

        @on_mode
        def charging(e):
            order.append("charging")

        @exit_mode(charging)
        def charging_exit(e):
            order.append("exit")

        @on_mode
        def diving(e):
            order.append("diving")

        c = self.track(Circle())
        c.mode = charging
        c.mode = diving
        self.assertEqual(order, ["charging", "exit", "diving"])
        self.assertEqual(c.mode, diving)

    def test_exit_hook_work_is_entity_scoped(self):
        n = []

        class Drone(Circle):
            @on_mode
            def charging(self):
                pass

            @exit_mode(charging)
            def charging_exit(self):
                after(0.2, self.ping)

            def ping(self):
                n.append("lived")

            @on_mode
            def other(self):
                pass

            @on_mode
            def idle(self):
                pass

        d = self.track(Drone())
        d.mode = d.charging
        d.mode = d.other
        handles = list(get_scheduler()._handles)
        self.assertEqual(len(handles), 1)
        self.assertEqual(handles[0].scope, "entity")
        d.mode = d.idle
        _frame(0.3)
        self.assertEqual(n, ["lived"])

    def test_exit_hook_then_without_owner_is_the_existing_typeerror(self):
        """Bare ``then=`` inside an exit hook still hits the old owner rule.

        The TypeError is raised by ``after()``; the mode setter finishes
        the transition, then re-raises it.
        """
        @on_mode
        def charging(e):
            pass

        def next_mode(e):
            pass

        @exit_mode(charging)
        def charging_exit(e):
            after(0.3, then=next_mode)

        c = self.track(Circle())
        c.mode = charging
        with self.assertRaisesRegex(TypeError, "needs an owner"):
            c.mode = None
        self.assertIsNone(c.mode)

    def test_async_exit_hook_rejected_at_decoration(self):
        @on_mode
        def charging(e):
            pass

        with self.assertRaises(TypeError) as ctx:
            @exit_mode(charging)
            async def charging_exit(e):
                pass
        self.assertIn("plain function", str(ctx.exception))
        self.assertIn("not async", str(ctx.exception))

    def test_async_enter_fn_allows_exit_mode_without_warning(self):
        """``@exit_mode`` on an async enter is fine (looks / ink cleanup)."""
        @on_mode
        async def charging(e):
            await wait(0.1)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            @exit_mode(charging)
            def charging_exit(e):
                e.glow = False
        async_warns = [
            w for w in caught
            if "try/finally" in str(w.message) or "async modes" in str(w.message)
        ]
        self.assertEqual(async_warns, [])
        self.assertIs(charging._exit_mode, charging_exit)

    def test_redecorating_exit_warns_once(self):
        @on_mode
        def charging(e):
            pass

        @exit_mode(charging)
        def first(e):
            pass

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            @exit_mode(charging)
            def second(e):
                pass
        hits = [w for w in caught if "replaces an existing exit hook" in str(w.message)]
        self.assertEqual(len(hits), 1)
        self.assertIn("remove the duplicate", str(hits[0].message))
        self.assertIs(charging._exit_mode, second)

    def test_exit_hook_exception_raises_after_transition(self):
        @on_mode
        def charging(e):
            pass

        @exit_mode(charging)
        def charging_exit(e):
            raise RuntimeError("exit boom")

        @on_mode
        def diving(e):
            e.ok = True

        c = self.track(Circle())
        c.mode = charging
        with self.assertRaisesRegex(RuntimeError, "exit boom"):
            c.mode = diving
        self.assertEqual(c.mode, diving)  # never left in a cancelled old mode
        self.assertTrue(c.ok)

    def test_same_mode_reassignment_is_noop(self):
        order = []

        @on_mode
        def charging(e):
            order.append("enter")

        @exit_mode(charging)
        def charging_exit(e):
            order.append("exit")

        c = self.track(Circle())
        c.mode = charging
        c.mode = charging
        self.assertEqual(order, ["enter"])

    def test_goto_mode_same_calls_exit_then_enter(self):
        order = []

        @on_mode
        def charging(e):
            order.append("enter")

        @exit_mode(charging)
        def charging_exit(e):
            order.append("exit")

        c = self.track(Circle())
        c.mode = charging
        c.goto_mode(charging)
        self.assertEqual(order, ["enter", "exit", "enter"])

    def test_goto_mode_different_like_assign(self):
        order = []

        @on_mode
        def a(e):
            order.append("a")

        @on_mode
        def b(e):
            order.append("b")

        c = self.track(Circle())
        c.mode = a
        c.goto_mode(b)
        self.assertEqual(order, ["a", "b"])
        self.assertEqual(c.mode, b)

    def test_mode_none_fires_exit_hook(self):
        n = []

        @on_mode
        def charging(e):
            pass

        @exit_mode(charging)
        def charging_exit(e):
            n.append("exit")

        c = self.track(Circle())
        c.mode = charging
        c.mode = None
        self.assertEqual(n, ["exit"])
        self.assertIsNone(c.mode)

    def test_destroy_does_not_fire_exit_mode(self):
        n = []

        @on_mode
        def charging(e):
            pass

        @exit_mode(charging)
        def charging_exit(e):
            n.append("exit")

        c = self.track(Circle())
        c.mode = charging
        c.destroy()
        self.assertEqual(n, [])


class TestCancelProcess(ProcessTestCase):
    def test_cancels_entity_after_and_every(self):
        c = self.track(Circle())
        n = []
        h_after = c.after(0.2, lambda: n.append("after"))
        h_every = c.every(0.1, lambda: n.append("every"))
        self.assertIs(c.cancel_process(), c)
        self.assertTrue(h_after.cancelled)
        self.assertTrue(h_every.cancelled)
        _frame(0.5)
        self.assertEqual(n, [])
        self.assertTrue(c.is_alive)

    def test_cancels_mode_scoped_and_clears_mode_quietly(self):
        c = self.track(Circle())
        n = []
        exited = []

        @on_mode
        def idle(e):
            n.append("enter")
            after(0.2, lambda: n.append("later"))

        @exit_mode(idle)
        def idle_exit(e):
            exited.append(1)

        c.mode = idle
        self.assertEqual(n, ["enter"])
        self.assertEqual(next(iter(get_scheduler()._handles)).scope, "mode")
        c.cancel_process()
        self.assertIsNone(c.mode)
        self.assertEqual(c.mode_time, 0.0)
        self.assertEqual(exited, [])  # no @exit_mode
        _frame(0.5)
        self.assertEqual(n, ["enter"])

    def test_cancels_entity_scoped_that_survived_mode_none(self):
        c = self.track(Circle())
        n = []

        def idle(e):
            pass

        c.mode = idle
        h = c.after(0.2, lambda: n.append(1))
        c.mode = None  # entity-scoped survives
        self.assertFalse(h.cancelled)
        c.cancel_process()
        self.assertTrue(h.cancelled)
        _frame(0.5)
        self.assertEqual(n, [])

    def test_cancels_async_mode_script(self):
        c = self.track(Circle())
        seen = []

        async def diving(e):
            seen.append("enter")
            await wait(0.2)
            seen.append("after")

        c.mode = diving
        self.assertEqual(seen, ["enter"])
        c.cancel_process()
        self.assertIsNone(c.mode)
        _frame(0.5)
        self.assertEqual(seen, ["enter"])

    def test_cancels_timed_move_without_on_done(self):
        c = self.track(Circle(center=(0, 0)))
        done = []
        h = c.move_to(100, 0, time=1.0, on_done=lambda: done.append(1))
        c.cancel_process()
        self.assertTrue(h.cancelled)
        _frame(0.5)
        self.assertEqual(done, [])
        self.assertAlmostEqual(float(c.center.x), 0.0, places=3)

    def test_does_not_fire_on_destroy(self):
        n = []
        c = self.track(Circle())
        c.on_destroy = lambda e: n.append(1)
        c.cancel_process()
        self.assertEqual(n, [])
        self.assertTrue(c.is_alive)
        c.destroy()
        self.assertEqual(n, [1])

    def test_leaves_on_update_and_ink(self):
        ticks = []
        c = self.track(Circle())
        c.hp = 3
        c.on_update = lambda e, dt: ticks.append(dt)
        c.after(10.0, lambda: None)
        c.cancel_process()
        self.assertEqual(float(c.hp), 3)
        self.assertTrue(callable(c.on_update))
        _frame(0.1)
        self.assertEqual(len(ticks), 1)

    def test_idempotent_and_second_cancel_on_handle(self):
        c = self.track(Circle())
        h = c.after(1.0, lambda: None)
        c.cancel_process()
        c.cancel_process()
        h.cancel()
        self.assertTrue(h.cancelled)
        self.assertEqual(h.remaining, 0.0)

    def test_parked_then_cancel_then_resume_does_not_fire(self):
        c = self.track(Circle())
        n = []
        h = c.after(0.2, lambda: n.append(1))
        c.active = False
        c.cancel_process()
        self.assertTrue(h.cancelled)
        c.active = True
        _frame(0.5)
        self.assertEqual(n, [])

    def test_act_scoped_timer_survives(self):
        c = self.track(Circle())
        n = []
        scene_h = after(0.2, lambda: n.append("scene"))
        c.after(0.2, lambda: n.append("entity"))
        c.cancel_process()
        self.assertFalse(scene_h.cancelled)
        _frame(0.3)
        self.assertEqual(n, ["scene"])

    def test_group_forwarding_returns_group(self):
        a = self.track(Circle(group="fleet"))
        b = self.track(Circle(group="fleet"))
        ha = a.after(1.0, lambda: None)
        hb = b.after(1.0, lambda: None)
        fleet = group["fleet"]
        out = fleet.cancel_process()
        self.assertIs(out, fleet)
        self.assertTrue(ha.cancelled)
        self.assertTrue(hb.cancelled)


class TestOnDestroy(ProcessTestCase):
    def test_subclass_on_destroy_is_discovered(self):
        seen = []

        class Drone(Circle):
            def setup(self):
                self.hp = 3

            def on_destroy(self):
                seen.append((float(self.hp), "wasp" in self.group, self.is_alive))

        d = self.track(Drone(group="wasp"))
        self.assertTrue(callable(d.on_destroy))
        d.destroy()
        self.assertEqual(seen, [(3, True, True)])
        self.assertFalse(d.is_alive)

    def test_classless_on_destroy_assignment(self):
        seen = []
        c = self.track(Circle(group="fleet"))

        def cleanup(e):
            seen.append(set(e.group))
            e.note = "still writable"

        c.on_destroy = cleanup
        c.destroy()
        self.assertEqual(len(seen), 1)
        self.assertIn("fleet", seen[0])
        self.assertFalse(c.is_alive)

    def test_on_destroy_runs_once_before_teardown(self):
        n = []
        c = self.track(Circle())
        c.on_destroy = lambda e: n.append(1)
        c.destroy()
        c.destroy()
        self.assertEqual(n, [1])

    def test_on_destroy_mode_and_timer_do_not_leak(self):
        c = self.track(Circle())

        def idle(e):
            after(10.0, lambda: None)

        def cleanup(e):
            e.mode = idle
            e.after(5.0, lambda: None)

        c.on_destroy = cleanup
        c.destroy()
        leftover = [
            h for h in get_scheduler()._handles
            if getattr(h, "owner", None) is c
        ]
        self.assertEqual(leftover, [])
        self.assertFalse(c.is_alive)

    def test_on_destroy_exception_raises_after_teardown(self):
        c = self.track(Circle())
        n = []
        c.every(0.1, lambda: n.append(1))

        def boom(e):
            raise RuntimeError("hook boom")

        c.on_destroy = boom
        with self.assertRaisesRegex(RuntimeError, "hook boom"):
            c.destroy()
        self.assertFalse(c.is_alive)
        _frame(0.1)
        self.assertEqual(n, [])  # owned work cancelled by the teardown

    def test_actor_without_on_destroy_unchanged(self):
        c = self.track(Circle())
        self.assertIsNone(c.on_destroy)
        c.destroy()
        self.assertFalse(c.is_alive)

    def test_on_destroy_non_callable_rejected(self):
        c = self.track(Circle())
        with self.assertRaises(TypeError) as ctx:
            c.on_destroy = 3
        self.assertIn("on_destroy expected a function", str(ctx.exception))

    def test_exit_mode_and_on_destroy_never_both_fire(self):
        n = []

        @on_mode
        def charging(e):
            pass

        @exit_mode(charging)
        def charging_exit(e):
            n.append("exit")

        def cleanup(e):
            n.append("destroy")

        a = self.track(Circle())
        a.mode = charging
        a.mode = None
        self.assertEqual(n, ["exit"])

        n.clear()
        b = self.track(Circle())
        b.on_destroy = cleanup
        b.mode = charging
        b.destroy()
        self.assertEqual(n, ["destroy"])

    def test_park_does_not_fire_on_destroy(self):
        n = []
        c = self.track(Circle())
        c.on_destroy = lambda e: n.append(1)
        c.active = False
        self.assertEqual(n, [])
        self.assertTrue(c.is_alive)


class TestOnUpdateAndSetup(ProcessTestCase):
    def test_on_update_assigned_every_frame(self):
        c = self.track(Circle())
        dts = []
        c.on_update = lambda e, dt: dts.append(dt)
        _frame(0.1)
        _frame(0.2)
        self.assertEqual(len(dts), 2)
        self.assertAlmostEqual(dts[0], 0.1, places=5)
        self.assertAlmostEqual(dts[1], 0.2, places=5)

    def test_on_update_runs_during_await(self):
        c = self.track(Circle())
        n = []

        async def diving(e):
            await wait(0.3)

        c.mode = diving
        c.on_update = lambda e, dt: n.append(1)
        _frame(0.1)
        _frame(0.1)
        self.assertEqual(n, [1, 1])

    def test_on_update_respects_time_scale(self):
        c = self.track(Circle())
        dts = []
        c.time_scale = 0.5
        c.on_update = lambda e, dt: dts.append(dt)
        _frame(0.4)
        self.assertAlmostEqual(dts[0], 0.2, places=5)

    def test_on_update_exception_propagates(self):
        c = self.track(Circle())
        n = []

        def boom(e, dt):
            n.append(1)
            raise RuntimeError("author bug")

        c.on_update = boom
        with self.assertRaisesRegex(RuntimeError, "author bug"):
            _frame(0.1)
        self.assertEqual(len(n), 1)
        self.assertIs(c.on_update, boom)
        self.assertFalse(get_scheduler()._iterating)

    def test_on_update_typo_construct_raises_at_the_call(self):
        """Galaga-shaped: bad Sprite kwargs in on_update raise the TypeError."""
        c = self.track(Circle(center=(0, 0), radius=8))

        def tick(e, dt):
            e.move_by(10 * dt, 0)
            Sprite(center=(0, 0), aaa=1)

        c.on_update = tick
        with self.assertRaisesRegex(TypeError, "aaa"):
            _frame(0.1)

    def test_on_update_non_callable(self):
        c = self.track(Circle())
        with self.assertRaises(TypeError):
            c.on_update = 3

    def test_subclass_setup_and_on_update(self):
        ticks = []

        class Drone(Circle):
            def setup(self):
                self.hp = 7
                self.armed = True

            def on_update(self, dt):
                ticks.append(dt)

        d = self.track(Drone(center=(10, 10), radius=8))
        self.assertEqual(float(d.hp), 7)
        self.assertTrue(d.armed)
        _frame(0.05)
        self.assertEqual(len(ticks), 1)
        # Container.update stays graph recalculation — never reused as the per-frame hook.
        self.assertTrue(callable(d.update))
        self.assertIsNot(d.update, d._on_update)

    def test_setup_runs_after_geometry(self):
        class Sized(Circle):
            def setup(self):
                self.seen_r = float(self.radius)

        s = self.track(Sized(center=(0, 0), radius=12))
        self.assertAlmostEqual(s.seen_r, 12.0, places=5)

    def test_setup_exception_raises_at_construct(self):
        class Broken(Circle):
            def setup(self):
                raise RuntimeError("setup boom")

        with self.assertRaisesRegex(RuntimeError, "setup boom"):
            Broken()

    def test_subclass_on_click_opts_in(self):
        class Buttonish(Circle):
            def on_click(self, shape):
                pass

        b = self.track(Buttonish())
        self.assertTrue(b.clickable)
        self.assertIsNotNone(b.on_click)


class TestEntity(ProcessTestCase):
    def test_bare_entity_is_undrawn_not_shape(self):
        e = self.track(Entity())
        self.assertIsInstance(e, Entity)
        self.assertNotIsInstance(e, Shape)
        self.assertIsNone(e.layer)
        n = []
        e.after(0.1, lambda: n.append(1))
        _frame(0.1)
        self.assertEqual(n, [1])

    def test_circle_and_sprite_are_entities(self):
        from scena import Sprite
        c = self.track(Circle())
        s = self.track(Sprite(center=(0, 0), size=32))
        self.assertIsInstance(c, Entity)
        self.assertIsInstance(s, Entity)
        # Graphic bodies place on a draw layer; bare Entity does not.
        self.assertIsNotNone(c.layer)
        self.assertIsNotNone(s.layer)

    def test_entity_mode_and_destroy(self):
        e = self.track(Entity())
        seen = []

        async def directing(item):
            await wait(0.1)
            seen.append("go")

        e.mode = directing
        e.destroy()
        _frame(0.2)
        self.assertEqual(seen, [])


class TestClassMethodEvery(ProcessTestCase):
    """Proposal A: ``@every`` on Entity methods tags at class body, arms at construct."""

    def test_decorate_does_not_arm_before_construct(self):
        n = []

        class Drone(Circle):
            @every(0.1, name="tick")
            def pulse(self):
                n.append(self)

        self.assertTrue(hasattr(Drone.pulse, "_every_spec"))
        self.assertFalse(hasattr(Drone.pulse, "handle"))
        _frame(0.2)
        self.assertEqual(n, [])
        self.assertEqual(
            [h for h in get_scheduler()._every if not h._cancelled],
            [],
        )

    def test_n_instances_n_entity_handles_destroy_one(self):
        seen = []

        class Drone(Circle):
            @every(0.1, name="tick")
            def pulse(self):
                seen.append(self)

        a = self.track(Drone())
        b = self.track(Drone())
        live = [h for h in get_scheduler()._every if not h._cancelled]
        self.assertEqual(len(live), 2)
        self.assertTrue(all(h.owner in (a, b) for h in live))
        self.assertTrue(all(h.scope == SCOPE_ENTITY for h in live))

        a.destroy()
        _frame(0.1)
        self.assertEqual(seen, [b])
        live = [h for h in get_scheduler()._every if not h._cancelled]
        self.assertEqual(len(live), 1)
        self.assertIs(live[0].owner, b)

    def test_name_replace_is_per_owner(self):
        hits = []

        class Drone(Circle):
            @every(0.5, name="tick")
            def pulse(self):
                hits.append(("slow", self))

        a = self.track(Drone())
        b = self.track(Drone())
        a.every(0.1, a.pulse, name="tick")
        _frame(0.1)
        self.assertEqual(hits, [("slow", a)])
        self.assertTrue(all(src is a for _, src in hits))

        hits.clear()
        _frame(0.5)
        # b still on the original 0.5 interval; a already fired on 0.1 and is due again.
        self.assertIn(("slow", b), hits)
        self.assertIn(("slow", a), hits)

    def test_fire_passes_self(self):
        seen = []

        class Drone(Circle):
            @every(0.1)
            def pulse(self):
                seen.append(self)

        d = self.track(Drone())
        _frame(0.1)
        self.assertEqual(seen, [d])

    def test_untagged_methods_ignored(self):
        class Drone(Circle):
            def idle(self):
                pass

        self.track(Drone())
        self.assertEqual(
            [h for h in get_scheduler()._every if not h._cancelled],
            [],
        )

    def test_module_level_every_still_arms(self):
        n = []

        @every(0.1, name="mod")
        def pulse():
            n.append(1)

        self.assertIsInstance(pulse.handle, Handle)
        _frame(0.1)
        self.assertEqual(n, [1])
        pulse.handle.cancel()

    def test_inherited_every_installs_on_subclass(self):
        seen = []

        class Drone(Circle):
            @every(0.1, name="tick")
            def pulse(self):
                seen.append(type(self).__name__)

        class FastDrone(Drone):
            pass

        self.track(FastDrone())
        _frame(0.1)
        self.assertEqual(seen, ["FastDrone"])

    def test_override_without_decorator_shadows(self):
        seen = []

        class Drone(Circle):
            @every(0.1)
            def pulse(self):
                seen.append("base")

        class Quiet(Drone):
            def pulse(self):
                seen.append("quiet")

        self.track(Quiet())
        _frame(0.2)
        self.assertEqual(seen, [])


class TestClassMethodAfter(ProcessTestCase):
    """``@after`` on Entity methods tags at class body, arms at construct."""

    def test_decorate_does_not_arm_before_construct(self):
        n = []

        class Drone(Circle):
            @after(0.1, name="boom")
            def explode(self):
                n.append(self)

        self.assertTrue(hasattr(Drone.explode, "_after_spec"))
        self.assertFalse(hasattr(Drone.explode, "handle"))
        _frame(0.2)
        self.assertEqual(n, [])
        live = [
            h for h in get_scheduler()._once
            if h.kind == "after" and not h._cancelled and not h._done
        ]
        self.assertEqual(live, [])

    def test_n_instances_n_entity_handles_destroy_one(self):
        seen = []

        class Drone(Circle):
            @after(0.1, name="boom")
            def explode(self):
                seen.append(self)

        a = self.track(Drone())
        b = self.track(Drone())
        live = [
            h for h in get_scheduler()._once
            if h.kind == "after" and not h._cancelled and not h._done
        ]
        self.assertEqual(len(live), 2)
        self.assertTrue(all(h.owner in (a, b) for h in live))
        self.assertTrue(all(h.scope == SCOPE_ENTITY for h in live))

        a.destroy()
        _frame(0.1)
        self.assertEqual(seen, [b])


class TestDecoratorRoles(ProcessTestCase):
    """Fail-loud stacking: one role family per function; class/module parity."""

    def setUp(self):
        super().setUp()
        cleanup_global_event_system()

    def tearDown(self):
        cleanup_global_event_system()
        super().tearDown()

    def test_module_stacked_when_both_fire(self):
        flags = {"a": False, "b": False}
        fired = []

        @when(lambda: flags["a"])
        @when(lambda: flags["b"])
        def on_either():
            fired.append(1)

        flags["a"] = True
        flush()
        self.assertEqual(fired, [1])
        fired.clear()
        flags["a"] = False
        flush()
        flags["b"] = True
        flush()
        self.assertEqual(fired, [1])

    def test_class_stacked_when_both_fire(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 5
                self.shield = 5

            @when(lambda self: self.hp <= 0)
            @when(lambda self: self.shield <= 0)
            def on_fail(self):
                fired.append(self)

        d = self.track(Drone())
        d.hp = 0
        flush()
        self.assertEqual(fired, [d])
        fired.clear()
        d.hp = 5
        flush()
        d.shield = 0
        flush()
        self.assertEqual(fired, [d])

    def test_module_second_every_raises(self):
        def pulse():
            pass

        every(0.1)(pulse)
        with self.assertRaises(TypeError) as ctx:
            every(0.2)(pulse)
        self.assertIn("@every", str(ctx.exception))
        pulse.handle.cancel()

    def test_class_second_every_raises(self):
        with self.assertRaises(TypeError) as ctx:
            class Drone(Circle):
                @every(0.2)
                @every(0.1)
                def pulse(self):
                    pass
        self.assertIn("@every", str(ctx.exception))

    def test_when_plus_every_raises_module(self):
        def mixed():
            pass

        every(0.1)(mixed)
        with self.assertRaises(TypeError) as ctx:
            when(lambda: True)(mixed)
        self.assertIn("@when", str(ctx.exception))
        mixed.handle.cancel()

    def test_when_plus_every_raises_class(self):
        with self.assertRaises(TypeError) as ctx:
            class Drone(Circle):
                @when(lambda self: True)
                @every(0.1)
                def mixed(self):
                    pass
        msg = str(ctx.exception)
        self.assertTrue("@when" in msg or "@every" in msg)

    def test_on_mode_plus_collide_with_raises(self):
        with self.assertRaises(TypeError) as ctx:
            class Drone(Circle):
                @on_mode
                @collide_with("bolt")
                def mixed(self, other, info):
                    pass
        msg = str(ctx.exception)
        self.assertTrue("@on_mode" in msg or "@collide" in msg)

    def test_leave_playfield_plus_every_raises(self):
        from scena import leave_playfield
        with self.assertRaises(TypeError) as ctx:
            class Drone(Circle):
                @every(0.1)
                @leave_playfield
                def mixed(self):
                    pass
        self.assertIn("@leave_playfield", str(ctx.exception))

    def test_when_plus_on_change_raises(self):
        from scena.events import on_change
        from scena import st
        st.x = 0

        def handler(value=None):
            pass

        when(lambda: True)(handler)
        with self.assertRaises(TypeError) as ctx:
            on_change(st["x"])(handler)
        self.assertIn("@on_change", str(ctx.exception))

    def test_decorator_on_actor_hook_raises(self):
        with self.assertRaises(TypeError) as ctx:
            class Drone(Circle):
                @every(0.1)
                def on_update(self, dt):
                    pass
        self.assertIn("on_update", str(ctx.exception))

        with self.assertRaises(TypeError) as ctx:
            class Drone2(Circle):
                @when(lambda self: True)
                def on_destroy(self):
                    pass
        self.assertIn("on_destroy", str(ctx.exception))

        with self.assertRaises(TypeError) as ctx:
            class Drone3(Circle):
                @on_mode
                def setup(self):
                    pass
        self.assertIn("setup", str(ctx.exception))

    def test_when_plus_on_change_raises_class(self):
        with self.assertRaises(TypeError) as ctx:
            class Drone(Circle):
                @on_change(lambda self: self.hp)
                @when(lambda self: self.hp <= 0)
                def mixed(self, value=None):
                    pass
        msg = str(ctx.exception)
        self.assertTrue("@when" in msg or "@on_change" in msg)

    def test_unregister_stacked_when(self):
        from scena.events import unregister_event
        flags = {"a": False, "b": False}
        fired = []

        @when(lambda: flags["a"])
        @when(lambda: flags["b"])
        def on_either():
            fired.append(1)

        unregister_event(on_either)
        flags["a"] = True
        flush()
        flags["b"] = True
        flush()
        self.assertEqual(fired, [])


class _CountingDict(dict):
    """Dict that counts ``__iter__`` so a test can prove a full scan did not happen."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.iters = 0

    def __iter__(self):
        self.iters += 1
        return super().__iter__()


class TestBoundMethodArityCache(ProcessTestCase):
    """``_argcount`` = ``validate.payload_arity``: parameters with no default,
    a bound method's ``self`` not counted, nothing cached on the function
    (a count stored on ``__func__`` would be shared by its bound and plain uses)."""

    def test_bound_every_counts_only_required_parameters(self):
        from scena.process import _argcount

        seen = []

        class Drone(Entity):
            def pulse(self, extra=None):
                seen.append(extra)

        d = self.track(Drone())
        d.every(0.05, d.pulse)
        _frame(0.05)
        self.assertEqual(seen, [None])
        self.assertEqual(_argcount(d.pulse), 0)
        self.assertEqual(_argcount(Drone.pulse), 1)
        self.assertFalse(hasattr(Drone.pulse, "_scena_argcount"))

    def test_same_function_plain_then_bound_then_plain(self):
        from scena.process import _argcount

        def shared(first, second=None):
            return (first, second)

        class Box:
            pass

        box = Box()
        bound = shared.__get__(box, Box)
        self.assertEqual(_argcount(shared), 1)
        self.assertEqual(_argcount(bound), 0)
        self.assertEqual(_argcount(shared), 1)

    def test_on_update_method_arity(self):
        from scena.process import _argcount

        seen = []

        class Holder:
            def on_update(self, dt):
                seen.append(dt)

        holder = Holder()
        ent = self.track(Entity())
        ent.on_update = holder.on_update
        _frame(0.1)
        self.assertEqual(len(seen), 1)
        self.assertAlmostEqual(seen[0], 0.1, places=5)
        self.assertEqual(_argcount(Holder.on_update), 2)
        self.assertEqual(_argcount(holder.on_update), 1)

    def test_builtin_bound_method_stays_zero(self):
        from scena.process import _argcount

        self.assertEqual(_argcount((1).bit_length), 0)


class TestOwnerIndex(ProcessTestCase):
    def test_cancel_owner_does_not_scan_all_handles(self):
        others = [self.track(Entity()) for _ in range(30)]
        for other in others:
            other.every(1.0, lambda: None)
        victim = self.track(Entity())
        victim.every(1.0, lambda: None)
        victim.after(1.0, lambda: None)
        sched = get_scheduler()
        counting = _CountingDict(sched._handles)
        sched._handles = counting
        victim.destroy()
        self.assertEqual(counting.iters, 0)
        self.assertNotIn(id(victim), sched._by_owner)
        self.assertEqual(len(sched._handles), 30)

    def test_mode_change_does_not_scan_all_handles(self):
        c = self.track(Circle())
        for _ in range(20):
            every(1.0, lambda: None)

        def idle(e):
            every(1.0, lambda: None)

        def next_mode(e):
            pass

        c.mode = idle
        sched = get_scheduler()
        counting = _CountingDict(sched._handles)
        sched._handles = counting
        c.mode = next_mode
        self.assertEqual(counting.iters, 0)

    def test_bulk_destroy_clears_buckets_and_index(self):
        ents = [self.track(Entity()) for _ in range(40)]
        for ent in ents:
            ent.every(1.0, lambda: None)
            ent.after(1.0, lambda: None)
        sched = get_scheduler()
        counting = _CountingDict(sched._handles)
        sched._handles = counting
        for ent in ents:
            ent.destroy()
        self.assertEqual(counting.iters, 0)
        self.assertEqual(len(sched._handles), 0)
        self.assertEqual(sched._by_owner, {})
        for bucket in (
            sched._every, sched._once, sched._tween,
            sched._await_family, sched._sound,
        ):
            self.assertEqual(len(bucket), 0)

    def test_cancel_outside_tick_drops_immediately(self):
        fired = []
        h = after(5.0, lambda: fired.append(1))
        sched = get_scheduler()
        self.assertIn(h, sched._once)
        self.assertIn(h, sched._handles)
        h.cancel()
        self.assertNotIn(h, sched._once)
        self.assertNotIn(h, sched._handles)
        self.assertNotIn(h, sched._by_owner.get(id(h.owner), {}))
        _frame(5.0)
        self.assertEqual(fired, [])

    def test_destroy_releases_entity_without_a_tick(self):
        import gc
        import weakref

        c = Circle(center=(0, 0), radius=4)
        c.every(1.0, lambda: None)
        c.after(1.0, lambda: None)
        c.move_to(30, 0, time=1.0)
        ref = weakref.ref(c)
        c.destroy()
        del c
        gc.collect()
        self.assertIsNone(ref())

    def test_after_created_inside_every_waits_for_next_tick(self):
        fired = []

        def hop():
            fired.append("every")
            after(0.0, lambda: fired.append("after"))

        every(0.05, hop)
        _frame(0.05)
        self.assertEqual(fired, ["every"])
        _frame(0.05)
        self.assertEqual(fired, ["every", "every", "after"])

    def test_every_created_in_tween_on_done_waits_for_next_tick(self):
        fired = []
        c = self.track(Circle(center=(0, 0), radius=4))

        def done():
            fired.append("done")
            every(0.05, lambda: fired.append("every"))

        c.move_to(10, 0, time=0.1, on_done=done)
        _frame(0.1)
        self.assertEqual(fired, ["done"])
        _frame(0.05)
        self.assertEqual(fired, ["done", "every"])

    def test_cancel_later_handle_in_same_tick_skips_it(self):
        fired = []
        pending = {}

        def early():
            fired.append("early")
            pending["later"].cancel()

        after(0.05, early)
        pending["later"] = after(0.05, lambda: fired.append("later"))
        _frame(0.05)
        self.assertEqual(fired, ["early"])
        self.assertTrue(pending["later"].cancelled)

    def test_frozen_warn_does_not_scan_all_handles(self):
        c = self.track(Circle())

        def idle(e):
            pass

        c.mode = idle
        for _ in range(10):
            every(5.0, lambda: None)
        sched = get_scheduler()
        counting = _CountingDict(sched._handles)
        sched._handles = counting
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            for _ in range(int(FROZEN_MODE_S / 0.1) + 2):
                _frame(0.1)
        self.assertEqual(counting.iters, 0)

    def test_reset_clears_owner_index(self):
        ent = self.track(Entity())
        ent.every(1.0, lambda: None)
        self.assertIn(id(ent), get_scheduler()._by_owner)
        reset_process_scheduler()
        self.assertEqual(get_scheduler()._by_owner, {})

    def test_mode_cancel_keeps_entity_handles_indexed(self):
        c = self.track(Circle())
        kept = c.every(1.0, lambda: None)

        def idle(e):
            every(1.0, lambda: None)

        c.mode = idle
        sched = get_scheduler()
        self.assertEqual(len(sched._by_owner[id(c)]), 2)
        c.mode = None
        owned = sched._by_owner[id(c)]
        self.assertEqual(list(owned), [kept])
        self.assertFalse(kept.cancelled)


class TestEventOwnerIndex(ProcessTestCase):
    def setUp(self):
        super().setUp()
        cleanup_global_event_system()

    def tearDown(self):
        cleanup_global_event_system()
        super().tearDown()

    def test_method_on_change_inspects_signature_once(self):
        from scena import events as evmod

        calls = {"n": 0}
        real = evmod._callback_npos

        def _wrapped(callback):
            calls["n"] += 1
            return real(callback)

        evmod._callback_npos = _wrapped
        try:
            fired = []

            class Drone(Circle):
                def setup(self):
                    self.hp = 1

                @on_change(lambda self: self.hp)
                def on_hp(self, value):
                    fired.append(value)

            d = self.track(Drone())
            d.hp = 2
            flush()
            d.hp = 3
            flush()
            self.assertEqual(fired, [2, 3])
            self.assertEqual(calls["n"], 1)
        finally:
            evmod._callback_npos = real

    def test_bound_star_args_receives_value(self):
        fired = []

        class Drone(Circle):
            def setup(self):
                self.hp = 1

            @on_change(lambda self: self.hp)
            def on_hp(self, *args):
                fired.append(args)

        d = self.track(Drone())
        d.hp = 4
        flush()
        self.assertEqual(fired, [(4,)])

    def test_drop_owner_does_not_scan_events_and_never_fires(self):
        from scena.events import get_global_event_system

        fired = []

        class Drone(Circle):
            def setup(self):
                self.go = False

            @when(lambda self: bool(self.go))
            def on_go(self):
                fired.append(1)

        class Other(Circle):
            @when(lambda self: False)
            def on_stay(self):
                pass

        from scena.state import get_scena_system

        d = Drone()
        other = self.track(Other())
        es = get_global_event_system()
        ss = get_scena_system()
        ss.begin_frame_batch()
        try:
            d.go = True
            self.assertEqual(fired, [])
            counting = _CountingDict(es._events)
            es._events = counting
            d.destroy()
            self.assertEqual(counting.iters, 0)
            self.assertNotIn(id(d), es._by_owner)
            self.assertTrue(any(event._owner is other for event in es._events))
        finally:
            ss.end_frame_batch()
        flush()
        self.assertEqual(fired, [])

    def test_poll_owner_gone_prunes_index(self):
        from scena.events import get_global_event_system

        class Drone(Circle):
            @when(lambda self: False)
            def on_go(self):
                pass

        d = self.track(Drone())
        es = get_global_event_system()
        self.assertIn(id(d), es._by_owner)
        object.__setattr__(d, "_destroyed", True)
        flush()
        self.assertNotIn(id(d), es._by_owner)
        self.assertEqual(len(es._events), 0)
        # Faked death: undo it so tearDown really destroys (no zombie left on
        # the registry for later modules).
        object.__setattr__(d, "_destroyed", False)


class TestEveryFlood(ProcessTestCase):
    def test_named_fleet_is_not_a_flood(self):
        fleet = [self.track(Entity()) for _ in range(80)]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for e in fleet:
                e.every(2.4, lambda: None, name="fire")
        flood = [w for w in caught if "every() created" in str(w.message)]
        self.assertEqual(flood, [])

    def test_unnamed_burst_still_warns(self):
        n = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(41):
                every(1.0, lambda: n.append(1))
        flood = [w for w in caught if "every() created" in str(w.message)]
        self.assertTrue(flood)


class TestDeadOwnerRelease(ProcessTestCase):
    """System-suite findings S3–S5 (``tests/test_sys_lifetime.py``)."""

    def _collected_after(self, make):
        import gc
        import weakref
        c = make()
        ref = weakref.ref(c)
        _frame(0.05)
        c.destroy()
        del c
        _frame(0.05)  # scheduler now idle: nothing else owns work
        gc.collect()
        return ref() is None

    def test_last_mode_owner_is_released_when_scheduler_goes_idle(self):
        """S4: the dense mode snapshot kept the last destroyed owner alive."""
        def roam(e):
            pass

        def make():
            c = Circle()
            c.mode = roam
            return c
        self.assertTrue(self._collected_after(make))

    def test_last_on_update_owner_is_released_when_scheduler_goes_idle(self):
        """S4: same for the dense ``on_update`` snapshot."""
        def make():
            c = Circle()
            c.on_update = lambda e, dt: None
            return c
        self.assertTrue(self._collected_after(make))

    def test_every_flood_sites_do_not_grow_per_owner(self):
        """S3: ``_every_sites`` is keyed by id(owner); a spawn / destroy churn
        left one key per dead actor forever. Idle keys are swept."""
        from unittest import mock
        import scena.process as proc
        sch = get_scheduler()
        now = [1000.0]
        with mock.patch.object(proc.time, "monotonic", side_effect=lambda: now[0]):
            for _ in range(500):
                e = Entity()
                e.every(1.0, lambda: None)
                e.destroy()
                now[0] += 0.05
        self.assertLessEqual(len(sch._every_sites), proc._EVERY_SITES_SWEEP_AT + 25)

    def test_decorating_inside_a_function_does_not_pin_its_locals(self):
        """S7: the class-body probe read ``frame.f_locals`` of the caller —
        on CPython <= 3.12 that caches a locals snapshot on the frame, so a
        destroyed ``shot`` stayed referenced after ``del``."""
        import gc
        import weakref
        from scena import collide
        wall = self.track(Circle(center=(9000, 9000), radius=5))
        shot = Circle(center=(9000, 9000), radius=2)

        @collide(shot, wall)
        def on_hit(me, other, info=None):
            pass

        ref = weakref.ref(shot)
        shot.destroy()
        del shot
        gc.collect()
        self.assertIsNone(ref())

    def test_work_scheduled_on_destroyed_actor_never_registers(self):
        """S9 (system world machine): ``e.after`` / ``every`` / ``tween`` /
        ``play_sound`` / ``on_update`` on a destroyed actor registered live
        work owned by the dead actor until the next tick noticed."""
        from scena.audio_mixer import make_sine
        from scena.audio import Sound
        snd = Sound._from_pcm(make_sine(440, 0.2, amp=0.1))
        c = Circle()
        c.destroy()
        fired = []
        sch = get_scheduler()
        handles = [
            c.after(0.01, lambda: fired.append("after")),
            c.every(0.01, lambda: fired.append("every")),
            c.tween(c["radius"], 20, time=0.01, on_done=lambda: fired.append("tween")),
            c.play_sound(snd, on_done=lambda: fired.append("sound")),
            c.move_to(5, 5, time=0.01, on_done=lambda: fired.append("move")),
        ]
        c.on_update = lambda e, dt: fired.append("on_update")
        self.assertEqual(len(sch._handles), 0)
        self.assertNotIn(id(c), sch._by_owner)
        self.assertNotIn(c, set(sch._update_owners))
        self.assertTrue(all(h.cancelled for h in handles))
        _frame(0.1)
        self.assertEqual(fired, [])

    def test_mode_on_destroyed_actor_raises_and_never_runs(self):
        """S5: ``mode =`` on a destroyed actor ran the mode body."""
        from scena.state import DestroyedError
        ran = []

        def angry(e):
            ran.append(e)

        c = Circle()
        c.destroy()
        with self.assertRaises(DestroyedError):
            c.mode = angry
        with self.assertRaises(DestroyedError):
            c.goto_mode(angry)
        c.mode = None  # clearing stays a quiet no-op
        self.assertEqual(ran, [])
        self.assertEqual(get_scheduler()._tasks, {})


class TestTweenPropertyBackedField(ProcessTestCase):
    """S10 (system world machine): ``tween(shape["angle"], …)`` on a
    Graphic whose ``angle`` / ``scale`` is property-backed crashed on the
    first tick (``_write_field`` took the ink path: no ink dict, then
    ``_INK_SLOT.default``)."""

    def test_tween_rotation_and_scale_on_every_kind(self):
        kinds = {
            "circle": lambda: Circle(radius=5),
            "sprite": lambda: Sprite("missing_for_test.png"),
            "polygon": lambda: Polygon(points=[(0, 0), (4, 0), (0, 4)]),
            "rect": lambda: Rect(width=4, height=2),  # real ScalarSlot rotation
        }
        for kind, make in kinds.items():
            for field, to in (("angle", 90.0), ("scale", 2.0)):
                with self.subTest(kind=kind, field=field):
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        a = self.track(make())
                    done = []
                    a.tween(a[field], to, time=0.2, on_done=lambda: done.append(1))
                    for _ in range(4):
                        _frame(0.1)
                    self.assertAlmostEqual(getattr(a, field), to)
                    self.assertEqual(done, [1])

    def test_write_to_linked_property_field_still_refuses(self):
        a = self.track(Circle(radius=5))
        b = self.track(Circle(radius=7))
        a["angle"] @= b["radius"]
        with self.assertRaises(LinkedAttributeError):
            a._write_field("angle", 3.0)


class TestPollNameTypes(ProcessTestCase):
    """A1 class (Testing Design): an unhashable name leaked Python's
    ``unhashable type`` from the slot-dict lookup before the name check."""

    BAD = (["shoot"], {"shoot": 1}, {"shoot"}, 5, None)

    def test_ready_and_recently_reject_non_string_names(self):
        e = self.track(Entity())
        calls = {
            "ready": lambda n: ready(n, 0.5),
            "recently": lambda n: recently(n, True),
            "e.ready": lambda n: e.ready(n, 0.5),
            "e.recently": lambda n: e.recently(n, True),
        }
        for label, call in calls.items():
            for bad in self.BAD:
                with self.subTest(call=label, bad=bad):
                    with self.assertRaises(TypeError) as ctx:
                        call(bad)
                    self.assertIn("name expected a string", str(ctx.exception))


class TestParkStashesFlagWrites(ProcessTestCase):
    """D7 contract (Testing Design; Actors Design — active): while parked, a
    ``visible`` / ``collidable`` write updates the stash that resume restores.
    Parked stays "no draw, no collision"; reads report the current (parked,
    off) state, and the written value applies on resume."""

    def test_visible_write_while_parked_is_stashed(self):
        from scena import Sprite, Text, Point
        from scena.spatial_fx import Sparks
        makers = {
            "Circle": lambda: Circle(center=(0, 0), radius=5),
            "Sprite": lambda: Sprite("park_missing.png", center=(0, 0)),
            "Text": lambda: Text("p", center=(0, 0)),
            "Sparks": lambda: Sparks(center=(0, 0)),
        }
        for kind, make in makers.items():
            with self.subTest(kind=kind):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    e = self.track(make())
                e.active = False
                self.assertFalse(e._visible)
                e.visible = True                 # author write while parked
                self.assertFalse(e.visible)      # still parked: not shown
                self.assertFalse(e._visible)
                e.active = True
                self.assertTrue(e.visible)
                self.assertTrue(e._visible)
                e.active = False
                e.visible = False
                e.active = True
                self.assertFalse(e._visible, "a hide written while parked must survive resume")

    def test_collidable_write_while_parked_is_stashed(self):
        from scena import collide
        from scena.collision import get_collision_system, reset_collision_system
        reset_collision_system()
        hits = []
        collide("park_a", "park_b")(lambda a, b: hits.append(1))
        a = self.track(Circle(center=(0, 0), radius=5, group="park_a"))
        self.track(Circle(center=(3, 0), radius=5, group="park_b"))
        system = get_collision_system()
        a.active = False
        a.collidable = False
        a.collidable = True                  # stashed: parked bodies never collide
        self.assertFalse(a.collidable)
        self.assertIsNone(a._collider)
        system.step()
        self.assertEqual(hits, [])
        a.active = True
        system.step()
        self.assertEqual(hits, [1])
        a.active = False
        a.collidable = False                 # stashed opt-out survives resume
        a.active = True
        self.assertFalse(a.collidable)
        self.assertIsNone(a._collider)
        reset_collision_system()

    def test_blink_on_a_parked_shape_does_not_show_it(self):
        c = self.track(Circle(center=(0, 0), radius=5))
        c.active = False
        c.visible = False
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            c.blink(0.4, rate=10.0)
        from scena import transients as tx
        for k in range(10):
            tx.tick_all_transients(k * 0.05)
            self.assertFalse(c._visible, f"blink showed a parked shape at tick {k}")



class TestParkRoundTripKeepsPlacement(ProcessTestCase):
    """``active = False`` then ``active = True`` puts back exactly what was
    there (Actors Design — active): layer, visible, draw-list and pointer-list
    membership. Bug: park wrote ``visible = False`` to an already hidden Point
    on a layer, which drops it off the layer (``_layer_while_hidden``); resume
    wrote ``False`` again and the point came back on ``layer=None``. The
    deep serial pass saw it as ``registry.draw_live`` moving across a
    ``SystemWorld`` quarantine (Testing Design, "serial pass")."""

    @staticmethod
    def _placement(e):
        from scena.canvas import ScenaCanvas
        reg = ScenaCanvas.get_current().registry
        drawn = any(o is e for layer in reg.layers.iter_draw_order()
                    for o in layer._objects)
        pointer = any(o is e for layer in reg.layers.iter_draw_order()
                      for o in getattr(layer, "_interactive", ()))
        return (e.layer, e.visible, e._visible, drawn, pointer)

    def _cases(self):
        from scena import Point, Sprite, Text

        def hidden_point_on_layer():
            p = Point(0, 0)
            p.layer = "default"          # still hidden: on the draw list, skipped
            return p

        def shown_point():
            p = Point(0, 0)
            p.visible = True
            return p

        def handle_point():
            p = Point(0, 0)
            p.handle = True
            return p

        def draggable_rect():
            r = Rect(center=(0, 0), width=4, height=4)
            r.draggable = True
            return r

        def hidden_circle():
            c = Circle(center=(0, 0), radius=5)
            c.visible = False
            return c

        def _line_with_handles():
            ln = Line(p1=(0, 0), p2=(5, 5))
            ln.show_handles()
            return ln

        def hidden_text():
            t = Text("p", center=(0, 0))
            t.visible = False
            return t

        return {
            "Point(0, 0)": lambda: Point(0, 0),
            "hidden Point on a layer": hidden_point_on_layer,
            "shown Point": shown_point,
            "handle Point": handle_point,
            "Circle": lambda: Circle(center=(0, 0), radius=5),
            "hidden Circle": hidden_circle,
            "draggable Rect": draggable_rect,
            "Line with handles": lambda: _line_with_handles(),
            "Sprite": lambda: Sprite("park_missing.png", center=(0, 0)),
            "hidden Text": hidden_text,
        }

    def test_park_resume_is_identity_on_placement(self):
        for kind, make in self._cases().items():
            with self.subTest(kind=kind):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    e = self.track(make())
                    before = self._placement(e)
                    e.active = False
                    e.active = True
                    self.assertEqual(self._placement(e), before)
                    # A second round trip too: the first must not leave a
                    # stash behind that the second reads.
                    e.active = False
                    e.active = True
                    self.assertEqual(self._placement(e), before)


class TestEveryCountsWorldSeconds(unittest.TestCase):
    """``every`` keeps its debt: the rate does not depend on the frame rate,
    and a hitch loses no fires (design decision, review 2026-10-09 S2-16)."""

    def _count(self, interval, dts, **kw):
        from scena import every
        from tests.system_support import system_world
        fires = []
        with system_world(draw=False) as w:
            h = every(interval, lambda: fires.append(1), **kw)
            for dt in dts:
                w.step(1, dt=dt)
            h.cancel()
        return len(fires)

    def test_same_rate_at_30_and_60_fps(self):
        self.assertEqual(self._count(0.02, [1 / 60] * 60), 50)
        self.assertEqual(self._count(0.02, [1 / 30] * 30), 50)

    def test_a_hitch_loses_nothing(self):
        dts = [1 / 60] * 15 + [0.25] + [1 / 60] * 30
        self.assertEqual(self._count(0.1, dts), int((15 / 60 + 0.25 + 30 / 60) / 0.1 + 1e-9))

    def test_a_burst_stops_when_the_callback_cancels(self):
        from scena import every
        from tests.system_support import system_world
        fires = []
        with system_world(draw=False) as w:
            box = {}

            def tick():
                fires.append(1)
                box["h"].cancel()
            box["h"] = every(0.02, tick)
            w.step(1, dt=0.25)
        self.assertEqual(fires, [1])

    def test_a_burst_stops_when_the_owner_parks(self):
        from scena import Entity
        from tests.system_support import system_world
        fires = []
        with system_world(draw=False) as w:
            e = Entity()
            try:
                def tick():
                    fires.append(1)
                    e.active = False
                e.every(0.02, tick)
                w.step(1, dt=0.25)
                self.assertEqual(fires, [1])
            finally:
                e.destroy()


class TestParkHoldsSoundOnDone(unittest.TestCase):
    """Park does not stop audio, but it promises no owned callbacks: an
    owned sound's on_done waits for the resume, and the Handle keeps
    reporting the voice (review 2026-10-09 X-life-4)."""

    def test_on_done_waits_for_resume(self):
        from scena import Circle
        from tests.system_support import system_world, tone
        log = []
        with system_world(draw=False) as w:
            ship = Circle(center=(0, 0), radius=10)
            try:
                h = ship.play_sound(tone(0.3), on_done=lambda: log.append(ship.active))
                w.step(3, dt=1 / 60)
                ship.active = False
                e0 = h.elapsed
                w.step(60, dt=1 / 60)
                self.assertEqual(log, [], "on_done ran on the parked actor")
                self.assertGreater(h.elapsed, e0, "the Handle froze while the voice played")
                self.assertFalse(h.done)
                ship.active = True
                w.step(2, dt=1 / 60)
                self.assertEqual(log, [True])
                self.assertTrue(h.done)
            finally:
                ship.destroy()

    def test_unparked_sound_ends_as_before(self):
        from scena import Circle
        from tests.system_support import system_world, tone
        log = []
        with system_world(draw=False) as w:
            ship = Circle(center=(0, 0), radius=10)
            try:
                ship.play_sound(tone(0.2), on_done=lambda: log.append(1))
                w.step(30, dt=1 / 60)
                self.assertEqual(log, [1])
            finally:
                ship.destroy()


class TestTweenDoorsOnADeadTarget(unittest.TestCase):
    """Every tween() door has the timed pose verbs' dead-target rule: the
    target dies mid-flight → a quiet cancel, no write, no on_done
    (review 2026-10-09 S2-2)."""

    def test_every_door(self):
        from scena import Circle, tween
        from tests.system_support import system_world
        doors = {
            "field": lambda b: tween(b["radius"], 2, time=0.5, on_done=lambda: done.append(1)),
            "ink": lambda b: tween(b["hp"], 0, time=0.5, on_done=lambda: done.append(1)),
            "pose part": lambda b: tween(b.center, (100, 0), time=0.5, on_done=lambda: done.append(1)),
        }
        for label, start in doors.items():
            with self.subTest(door=label), system_world(draw=False) as w:
                done = []
                boss = Circle(center=(0, 0), radius=20)
                boss.hp = 10
                h = start(boss)
                w.step(5, dt=1 / 60)
                boss.destroy()
                w.step(40, dt=1 / 60)            # raised DestroyedError (pose)
                self.assertTrue(h.cancelled, label)
                self.assertEqual(done, [], label)


class TestHooksHaveNoAmbientOwner(unittest.TestCase):
    """setup(), on_destroy and @exit_mode run with no ambient mode owner,
    even when called from inside another actor's mode body; and a mode
    transition survives what its exit hook does (review 2026-10-09 S2-1,
    S2-3, S2-4, S2-12)."""

    def test_setup_of_an_actor_built_in_a_mode_body_owns_its_work(self):
        from scena import Circle, after, every, on_mode
        from tests.system_support import system_world
        shots = []
        with system_world(draw=False) as w:
            class Shot(Circle):
                def setup(self):
                    self.trail = every(0.1, lambda: None)
                    self.flight = self.move_by(0, -300, time=1.0)

            class Wasp(Circle):
                @on_mode
                def attack(self):
                    shots.append(Shot(center=self.center, radius=2))
                    after(0.2, then=self.retreat)

                @on_mode
                def retreat(self):
                    pass

            wasp = Wasp(center=(0, 0), radius=8)
            try:
                wasp.mode = wasp.attack
                s = shots[0]
                self.assertIs(s.flight.owner, s)
                self.assertIsNot(s.trail.owner, wasp)
                w.step(30, dt=1 / 60)               # the wasp changes mode
                self.assertFalse(s.flight.cancelled)
                self.assertFalse(s.trail.cancelled)
                s.trail.cancel()
            finally:
                for o in shots + [wasp]:
                    o.destroy()

    def test_exit_hook_assigning_mode_raises_and_the_change_completes(self):
        from scena import Circle, exit_mode, on_mode
        from tests.system_support import system_world
        exits = []
        with system_world(draw=False) as w:
            class Ship(Circle):
                @on_mode
                def charging(self):
                    pass

                @exit_mode(charging)
                def charging_exit(self):
                    exits.append(1)
                    self.mode = self.cooldown

                @on_mode
                def cooldown(self):
                    pass

                @on_mode
                def diving(self):
                    pass

            s = Ship(radius=3)
            try:
                s.mode = s.charging
                with self.assertRaisesRegex(TypeError, "exit_mode"):
                    s.mode = s.diving            # RecursionError before
                self.assertEqual(exits, [1])
                self.assertEqual(s.mode.__name__, "diving")
            finally:
                s.destroy()

    def test_exit_hook_that_destroys_runs_no_next_body(self):
        from scena import Circle, exit_mode, on_mode
        from tests.system_support import system_world
        ran = []
        with system_world(draw=False) as w:
            class Bomb(Circle):
                @on_mode
                def armed(self):
                    pass

                @exit_mode(armed)
                def armed_exit(self):
                    self.destroy()

                @on_mode
                def fleeing(self):
                    ran.append(self.is_alive)

            b = Bomb(radius=3)
            b.mode = b.armed
            b.mode = b.fleeing
            self.assertEqual(ran, [])
            self.assertFalse(b.is_alive)


class TestWatchOnADestroyedSourceRetires(unittest.TestCase):
    """A classless @when / @on_change over a destroyed actor retires, even on
    a field that stays readable after destroy (review 2026-10-09 S2-8)."""

    def test_readable_fields_retire_the_watch(self):
        import gc
        import weakref
        from scena import Circle, when, on_change
        from scena.events import get_global_event_system
        from tests.system_support import system_world
        for label, make in (
            ("radius", lambda b: when(lambda: b.radius < 5)),
            ("center", lambda b: on_change(lambda: b.center.x)),
            ("default arg", lambda b: when(lambda bb=b: bb.angle > 90)),
        ):
            with self.subTest(label), system_world(draw=False) as w:
                boss = Circle(center=(0, 0), radius=20)
                make(boss)(lambda *a: None)
                es = get_global_event_system()
                n0 = len(es._events)
                ref = weakref.ref(boss)
                boss.destroy()
                self.assertEqual(len(es._events), n0 - 1, label)
                del boss
                gc.collect()
                self.assertIsNone(ref(), f"{label}: the watch kept the dead actor")


class TestWatchdogWindow(ProcessTestCase):
    """The task walk turns the watchdog events on once per tick, at the first
    task ready to resume, and resets only the deadline per resume: each
    ``sys.monitoring.set_events`` re-instruments every function on the stack,
    so a toggle per resume cost ~25 µs (Actors Design — Tasks, perf)."""

    def setUp(self):
        super().setUp()
        import scena.process as proc
        self.proc = proc
        proc.set_watchdog(True)
        self.opened = []
        real = proc._watchdog_window_open

        def counting():
            hit = real()
            self.opened.append(hit)
            return hit

        proc._watchdog_window_open = counting
        self.addCleanup(setattr, proc, "_watchdog_window_open", real)

    def test_one_window_for_every_ready_task(self):
        async def loop(e):
            while True:
                await wait(0.1)

        for _ in range(20):
            self.track(Circle()).mode = loop
        self.opened.clear()
        _frame(0.1)
        self.assertEqual(self.opened, [True])
        self.assertFalse(self.proc._wd_window_open)

    def test_no_window_when_nothing_is_ready(self):
        async def slow(e):
            await wait(10.0)

        self.track(Circle()).mode = slow
        self.opened.clear()
        _frame(0.1)
        self.assertEqual(self.opened, [])

    def test_a_later_step_that_spins_still_trips(self):
        proc = self.proc
        old, old_every = proc.WATCHDOG_RESUME_S, proc.WATCHDOG_CHECK_EVERY
        proc.WATCHDOG_RESUME_S = 0.05
        proc.WATCHDOG_CHECK_EVERY = 64
        self.addCleanup(setattr, proc, "WATCHDOG_RESUME_S", old)
        self.addCleanup(setattr, proc, "WATCHDOG_CHECK_EVERY", old_every)
        c = self.track(Circle())
        other = self.track(Circle())
        log = []

        async def spins_later(e):
            await wait(0.1)
            while True:
                pass

        async def steady(e):
            await wait(0.1)
            log.append("steady ran")

        c.mode = spins_later
        other.mode = steady
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _frame(0.1)
        msgs = [str(w.message) for w in caught]
        self.assertTrue(any("SCENA ERROR" in m and "CANCELLED" in m for m in msgs), msgs)
        self.assertEqual(log, ["steady ran"], "the walk goes on after a trip")
        self.assertIsNone(c._mode_task)
        self.assertFalse(proc._wd_window_open)
        self.assertEqual(proc._wd_deadline, float("inf"), "no deadline between resumes")


class TestModeTask(ProcessTestCase):
    """An async mode's body is a task: a ``Handle(kind="task")`` owned by the
    actor in mode scope, so leaving the mode cancels it with the mode's
    timers (Actors Design — Tasks). Behaviour is the async mode's as before."""

    def test_body_is_an_owned_mode_task(self):
        c = self.track(Circle())

        async def diving(e):
            await wait(1.0)

        c.mode = diving
        h = c._mode_task
        self.assertIsInstance(h, Handle)
        self.assertEqual(h.kind, "task")
        self.assertIs(h.owner, c)
        self.assertEqual(h.scope, "mode")
        sched = get_scheduler()
        self.assertIn(h, sched._tasks)
        self.assertIn(h, sched._by_owner[id(c)])

    def test_leaving_cancels_the_task_after_its_timers(self):
        c = self.track(Circle())
        seen = {}

        async def diving(e):
            timer = after(5.0, lambda: None)
            try:
                await wait(1.0)
            finally:
                seen["timer_cancelled_first"] = timer.cancelled

        c.mode = diving
        h = c._mode_task
        c.mode = None
        self.assertTrue(h.cancelled)
        self.assertIsNone(c._mode_task)
        self.assertEqual(seen, {"timer_cancelled_first": True})
        self.assertNotIn(h, get_scheduler()._tasks)

    def test_finished_body_completes_and_frees_the_slot(self):
        c = self.track(Circle())

        async def short(e):
            await wait(0.1)
            return 7

        c.mode = short
        h = c._mode_task
        _frame(0.1)
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)
        self.assertEqual(h._result, 7)
        self.assertIsNone(c._mode_task)
        self.assertTrue(c.mode == short, "a finished body is not an exit")

    def test_tasks_resume_after_timers_and_before_on_update(self):
        c = self.track(Circle())
        log = []

        async def diving(e):
            await wait(0.1)
            log.append("task")

        c.mode = diving
        every(0.1, lambda: log.append("every"))
        after(0.1, lambda: log.append("after"))
        c.on_update = lambda e, dt: log.append("update")
        _frame(0.1)
        self.assertEqual(log, ["every", "after", "task", "update"])

    def test_a_mode_entered_during_the_walk_is_visited_in_it(self):
        a = self.track(Circle())
        b = self.track(Circle())
        d = self.track(Circle())
        gate = after(100.0, lambda: None)
        log = []

        async def b_mode(e):
            try:
                await gate
            except Cancelled:
                log.append(("b", clock.frame))

        async def a_mode(e):
            await wait(0.1)
            b.mode = b_mode            # started in A's step

        async def d_mode(e):
            await wait(0.1)
            gate.cancel()              # later in the same walk

        a.mode = a_mode
        d.mode = d_mode
        _frame(0.1)
        self.assertEqual(log, [("b", clock.frame)])

    def test_goto_same_mode_from_its_own_body(self):
        c = self.track(Circle())
        runs = []

        async def loop(e):
            runs.append(len(runs))
            await wait(0.1)
            if len(runs) < 3:
                e.goto_mode(loop)

        c.mode = loop
        for _ in range(4):
            _frame(0.1)
        self.assertEqual(runs, [0, 1, 2])

    def test_a_parts_mode_task_ends_with_the_host(self):
        line = Line(p1=(0, 0), p2=(10, 0))

        async def drift(p):
            await wait(5.0)

        line.p1.mode = drift
        h = line.p1._mode_task
        line.destroy()
        self.assertTrue(h.cancelled)
        self.assertNotIn(h, get_scheduler()._tasks)

    def test_parked_owner_task_waits(self):
        c = self.track(Circle())
        log = []

        async def diving(e):
            await wait(0.1)
            log.append("resumed")

        c.mode = diving
        c.active = False
        _frame(0.2)
        self.assertEqual(log, [])
        c.active = True
        _frame(0.1)
        self.assertEqual(log, ["resumed"])


if __name__ == "__main__":
    unittest.main()

