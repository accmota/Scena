"""Scheduler time algebra over real frames (Hypothesis).

Timers, tweens and park run inside the real frame body
(``ScenaFramework._simulate_frame``) with generated ``dt`` sequences —
zero-length frames, 1/60, 1/30, hitches. Contracts (Actors Design § Scheduler,
Scena Design § Frame order):

* ``after(t)`` fires once, in the first frame whose cumulative world time
  reaches ``t``;
* ``every(p)`` fires at most once per frame, never more than ⌊T/p⌋ times, and
  exactly ⌊T/p⌋ (± a float edge) when no frame is longer than ``p``;
* a linear tween's value depends only on elapsed world time, not on how that
  time was split into frames; it lands exactly on the target and finishes once;
* parking an owner for k frames delays its timers by exactly those frames;
* the wall-clock path clamps a hitch to ``MAX_FRAME_DT``; ``advance`` does not.

    python -m unittest tests.test_sys_hyp_scheduler -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import assume, given, strategies as hst  # noqa: E402

from system_support import quiet, system_world  # noqa: E402

from scena import Circle, Entity, after, clock, every  # noqa: E402
from scena.input import MAX_FRAME_DT  # noqa: E402

EPS = 1e-9
frame_dts = hst.lists(
    hst.sampled_from([0.0, 1 / 120, 1 / 60, 1 / 30, 0.1, 0.25]), min_size=1, max_size=60)


def _cumulative(dts):
    out, t = [], 0.0
    for dt in dts:
        t += dt
        out.append(t)
    return out


def _run(w, dts, on_frame=None):
    for i, dt in enumerate(dts):
        w.step(1, dt=dt)
        if on_frame is not None:
            on_frame(i)


class TestAfter(unittest.TestCase):

    @given(dts=frame_dts, t=hst.floats(0.0, 2.0, allow_nan=False))
    def test_fires_once_in_first_frame_reaching_t(self, dts, t):
        with system_world(draw=False) as w:
            fired = []
            frame_of = {}
            after(t, lambda: fired.append(frame_of["i"]))
            cum = _cumulative(dts)

            for i, dt in enumerate(dts):
                frame_of["i"] = i
                w.step(1, dt=dt)
            reach = next((i for i, c in enumerate(cum) if c >= t), None)
            near = [i for i, c in enumerate(cum) if abs(c - t) < 1e-7]
            if reach is None and not near:
                self.assertEqual(fired, [])
                return
            self.assertLessEqual(len(fired), 1, f"cum={cum} t={t}")
            if not near:
                self.assertEqual(fired, [reach], f"cum={cum} t={t}")
            else:
                # Float edge: the scheduler's own accumulator may land on
                # either side of t — one frame of slack around the edge.
                ok = set(near) | {i + 1 for i in near if i + 1 < len(cum)}
                if reach is not None:
                    ok.add(reach)
                if fired:
                    self.assertIn(fired[0], ok, f"cum={cum} t={t}")


class TestEvery(unittest.TestCase):

    @given(dts=frame_dts, p=hst.sampled_from([1 / 60, 0.05, 0.1, 0.3]))
    def test_count_follows_world_seconds(self, dts, p):
        # ``every`` counts world seconds: the count after N frames is
        # floor(total / p) whatever the frame times (a frame that covers
        # several intervals fires several times), and no frame fires more
        # than one capped world step owes (review 2026-10-09 S2-16).
        from scena.process import _every_fire_budget
        with system_world(draw=False) as w:
            fires = []
            idx = {"i": -1}
            every(p, lambda: fires.append(idx["i"]))
            for i, dt in enumerate(dts):
                idx["i"] = i
                w.step(1, dt=dt)
            total = sum(dts)
            exact = total / p
            bound = math.floor(exact + 1e-7)
            edge = abs(exact - round(exact)) < 1e-6 and round(exact) > 0
            self.assertLessEqual(len(fires), bound)
            self.assertGreaterEqual(len(fires), bound - (1 if edge else 0),
                                    f"dts={dts} p={p}")
            per_frame = max((fires.count(i) for i in set(fires)), default=0)
            self.assertLessEqual(per_frame, _every_fire_budget(p))


class TestTween(unittest.TestCase):

    @given(parts=hst.lists(hst.floats(0.0, 0.2, allow_nan=False), min_size=1, max_size=40),
           dur=hst.floats(0.1, 1.5, allow_nan=False),
           target=hst.floats(0.0, 500.0, allow_nan=False))
    def test_value_depends_only_on_elapsed_time(self, parts, dur, target):
        with system_world(draw=False) as w:
            c = w.track(Circle(radius=10))
            done = []
            h = c.tween(c["radius"], target, time=dur, on_done=lambda: done.append(1))
            _run(w, parts)
            t = sum(parts)
            if t >= dur - EPS:
                self.assertAlmostEqual(c.radius, target, places=6)
                self.assertTrue(h.done)
                self.assertEqual(done, [1])
            else:
                want = 10 + (target - 10) * (t / dur)
                self.assertAlmostEqual(c.radius, want, delta=1e-6 * max(1.0, abs(target)))
                self.assertEqual(done, [])
            # Keep stepping: it never overshoots or fires again.
            w.step(3, dt=0.5)
            self.assertAlmostEqual(c.radius, target, places=6)
            self.assertEqual(done, [1])


class TestParkDelays(unittest.TestCase):

    @given(before=hst.integers(0, 10), parked=hst.integers(0, 20), delay_frames=hst.integers(1, 30))
    def test_park_shifts_owned_timer_by_parked_frames(self, before, parked, delay_frames):
        assume(before < delay_frames)
        dt = 1 / 60
        with system_world(draw=False) as w:
            e = w.track(Entity())
            fired = []
            idx = {"i": -1}
            e.after(delay_frames * dt - 1e-6, lambda: fired.append(idx["i"]))

            def step():
                idx["i"] += 1
                w.step(1, dt=dt)

            for _ in range(before):
                step()
            e.active = False
            for _ in range(parked):
                step()
            e.active = True
            for _ in range(delay_frames + 5):
                step()
            self.assertEqual(fired, [delay_frames - 1 + parked])


class TestClockClamp(unittest.TestCase):

    @given(walls=hst.lists(hst.floats(0.0, 3.0, allow_nan=False), min_size=1, max_size=20))
    def test_wall_clock_hitch_is_clamped(self, walls):
        with system_world(draw=False) as w:
            fw = w.fw
            now = 1000.0
            clock._last_time = now
            for real in walls:
                t0 = clock.time
                now += real
                with quiet():
                    fw._simulate_frame(now=now)
                self.assertAlmostEqual(clock.time - t0, min(real, MAX_FRAME_DT), places=9)
            t0 = clock.time
            w.step(1, dt=2.0)  # an explicit driver step is taken as given
            self.assertAlmostEqual(clock.time - t0, 2.0)


if __name__ == "__main__":
    unittest.main()
