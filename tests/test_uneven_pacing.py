"""World time does not depend on how frames cut it (review 2026-10-09, writers × time).

Bug class: **a total that depends on the frame cut**. A frame longer than a
lap dropped laps; ``every`` fired one past its bound after ``%``; a handle's
clock read only the current lap; an Endless fell behind a camera moved after
its fill; a scrolling layer lost its first frame. Each test runs the same
world time cut steady (1/60), uneven (5 / 28 ms) and with a 0.25 s hitch
(inside ``MAX_FRAME_DT``, so production passes it whole).

    python tests/run_tiers.py focused test_uneven_pacing
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import system_world  # noqa: E402

from scena import Circle, Endless, Rect, canvas, clock, every  # noqa: E402
from scena.process import _every_fire_budget  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()

CUTS = {
    "steady": [1 / 60] * 120,
    "uneven": [0.005, 0.028] * 60 + [1 / 60] * 2,
    "hitch": [1 / 60] * 15 + [0.25] + [1 / 60] * 90,
}


def _total(dts):
    return round(sum(dts), 6)


class TestTweenLaps(unittest.TestCase):
    """W-T1: every whole lap a frame covers counts."""

    def _run(self, dts):
        with system_world(draw=False) as w:
            done = []
            a = Circle(center=(0, 0), radius=5)
            b = Circle(center=(0, 0), radius=5)
            a.move_by(10, 0, time=0.1, loops=10,
                      on_done=lambda: done.append(round(clock.time, 4)))
            hb = b.move_by(10, 0, time=0.1, loops="forever", yoyo=True)
            for d in dts:
                w.step(1, dt=d)
            out = (done, round(a.center.x, 6), round(b.center.x, 6))
            hb.cancel()
            a.destroy()
            b.destroy()
        return out

    def test_end_time_end_pose_and_yoyo_phase(self):
        steady = self._run(CUTS["steady"])
        hitch = self._run(CUTS["hitch"])
        self.assertEqual(len(hitch[0]), 1, "on_done once")
        self.assertLessEqual(hitch[0][0], 1.0 + 0.25, "ends in the frame that covers t = 1")
        self.assertEqual(hitch[1], steady[1], "the same end pose")
        self.assertEqual(hitch[2], steady[2], "a yoyo keeps its phase")

    def test_a_frame_covering_the_whole_run(self):
        with system_world(draw=False) as w:
            done = []
            a = Circle(center=(0, 0), radius=5)
            a.move_by(10, 0, time=0.02, loops=5, on_done=lambda: done.append(1))
            w.step(1, dt=0.25)
            self.assertEqual(done, [1])
            self.assertAlmostEqual(a.center.x, 10.0, msg="each lap replays the segment")
            a.destroy()


class TestEveryBound(unittest.TestCase):
    """W-T3: past its budget, ``every`` keeps the phase, not one more fire."""

    def test_never_over_the_budget(self):
        for interval in (0.02, 0.01, 0.03):
            with self.subTest(interval=interval), system_world(draw=False) as w:
                n = [0]
                clock.scale = 2.0
                try:
                    h = every(interval, lambda: n.__setitem__(0, n[0] + 1))
                    w.step(1, dt=0.15)
                    h.cancel()
                finally:
                    clock.scale = 1.0
                self.assertLessEqual(n[0], _every_fire_budget(interval))


class TestHandleClockCountsTheRun(unittest.TestCase):
    """W-T4: ``elapsed`` / ``remaining`` of a finite ``loops=`` count the run."""

    def test_readouts(self):
        with system_world(draw=False) as w:
            c = Circle(center=(0, 0), radius=5)
            h = c.move_by(10, 0, time=0.1, loops=10)
            w.step(15, dt=1 / 60)
            self.assertAlmostEqual(h.elapsed, 0.25, places=6)
            self.assertAlmostEqual(h.remaining, 0.75, places=6)
            f = c.move_by(10, 0, time=0.1, loops="forever")
            w.step(3, dt=1 / 60)
            self.assertLessEqual(f.elapsed, 0.1 + 1e-9, "forever reads its lap")
            h.cancel()
            f.cancel()
            c.destroy()


class TestScrollAndFill(unittest.TestCase):
    """W-T6 / W-T7."""

    def test_layer_scroll_counts_its_first_frame(self):
        for name, dts in (("steady", [1 / 60] * 60), ("hitch", [0.25] + [1 / 60] * 45)):
            with self.subTest(cut=name), system_world(draw=False) as w:
                layer = canvas.layers.create("up_scroll", scroll=(-100.0, 0.0))
                t0 = clock.time
                for d in dts:
                    w.step(1, dt=d)
                self.assertAlmostEqual(layer._scroll_state.accum[0],
                                       -100.0 * (clock.time - t0), places=6)

    def test_endless_covers_a_camera_moved_after_its_fill(self):
        def floor(slot):
            return Rect(top_left=(slot.left, 20), width=slot.right - slot.left, height=20)

        for name, dts in CUTS.items():
            with self.subTest(cut=name), system_world(draw=False) as w:
                canvas.reset_view()
                canvas.layers.create("up_pista", below="default")
                e = Endless("up_pista", floor, step=100)
                cam = Circle(center=(0, -500), radius=1)          # made after the Endless
                cam.on_update = lambda me, dt: canvas.pan_to(canvas.pan_x + 1500 * dt,
                                                             canvas.pan_y)
                holes = []
                for d in dts[:60]:
                    w.step(1, dt=d)
                    v = canvas.layers["up_pista"].view
                    keys = sorted(e._live)
                    if not keys or e._bounds(keys[-1])[1] < v.right - 1e-6:
                        holes.append(round(clock.time, 3))
                cam.destroy()
                e.destroy()
                canvas.layers["up_pista"].delete(destroy_shapes=True)
                canvas.reset_view()
                self.assertEqual(holes, [])



class TestDecidedClocks(unittest.TestCase):
    """Review 2026-10-09 decisions W-T2, W-T5, W-T8, W-T9, X-writers-2."""

    def test_ready_keeps_its_rate_at_any_fps(self):
        from scena import ready
        counts = {}
        for fps in (60, 30):
            with system_world(draw=False) as w:
                n = [0]
                w.on_update(lambda dt: n.__setitem__(0, n[0] + (1 if ready("up_tiro", 0.07) else 0)))
                w.step(3 * fps, dt=1 / fps)
                w.on_update(None)
                ready.remove("up_tiro")
                counts[fps] = n[0]
        self.assertEqual(counts[60], counts[30])
        self.assertIn(counts[60], (42, 43))         # 3 s / 0.07, the first poll is True

    def test_ready_after_a_pause_in_polling_does_not_burst(self):
        from scena import ready
        with system_world(draw=False) as w:
            self.assertTrue(ready("up_burst", 0.1))
            w.step(60)                               # not polled for 1 s
            hits = 0
            for _ in range(6):                       # 0.1 s of polls
                hits += 1 if ready("up_burst") else 0
                w.step(1)
            ready.remove("up_burst")
            self.assertEqual(hits, 1)

    def test_ready_after_a_short_gap_restarts_the_cadence(self):
        # Fire held, let go, press again one frame after the cooldown: the
        # next held shot is a full interval later, not one frame early (the
        # overshoot of the reopen is not carried: PG-RD1).
        from scena import ready
        with system_world(draw=False) as w:
            fired = []

            def hold(on):
                w.on_update((lambda dt: fired.append(w.frames_run) if ready("up_gap", 0.15) else None)
                            if on else None)
            hold(True)
            w.step(3)                                # fire at frame 0
            hold(False)
            w.step(7)                                # frames 3..9: not polled
            hold(True)
            w.step(30)
            w.on_update(None)
            ready.remove("up_gap")
        gaps = [b - a for a, b in zip(fired[1:], fired[2:])]
        self.assertEqual(fired[0], 0)
        self.assertTrue(gaps, fired)
        self.assertEqual(set(gaps), {9}, fired)

    def test_a_fast_orbit_hits_a_target_on_its_arc_under_a_hitch(self):
        from scena import collide
        for name, dts in (("steady", [1 / 60] * 30), ("hitch", [0.25] + [1 / 60] * 15)):
            with self.subTest(cut=name), system_world(draw=False) as w:
                hits = []
                blade = w.track(Circle(center=(100, 0), radius=6, group="up_blade"))
                w.track(Circle(center=(0, 100), radius=6, group="up_target"))

                @collide("up_blade", "up_target")
                def hit(b, t):
                    hits.append(1)
                w.on_update(lambda dt: blade.rotate_by(720 * dt, about=(0, 0)))
                for d in dts:
                    w.step(1, dt=d)
                w.on_update(None)
                self.assertTrue(hits)

    def test_background_scroll_is_world_state(self):
        from scena.background import BackgroundField

        class Field(BackgroundField):
            def draw(self, *a, **k):
                pass

        for hidden in (1.0, 2.0):
            with self.subTest(hidden=hidden), system_world(draw=True) as w:
                f = Field()
                f.scroll = (100.0, 0.0)
                canvas.background.add(f)
                t0 = clock.time
                w.step(60)
                f.enabled = False
                w.step(round(hidden * 60))
                f.enabled = True
                w.step(60)
                self.assertAlmostEqual(f._scroll_accum[0], 100.0 * (clock.time - t0), places=6)
                canvas.background.remove(f)

    def test_spatial_fx_keep_world_time(self):
        from scena import Sparks
        for name, dts in (("steady", [1 / 60] * 60), ("hitch", [1 / 60] * 15 + [0.25] + [1 / 60] * 30)):
            with self.subTest(cut=name), system_world(draw=False) as w:
                fx = Sparks(center=(0, 0), rate=40)
                seen = [0.0]
                orig = fx._tick

                def spy(dt, t, _o=orig):
                    seen[0] += dt
                    _o(dt, t)
                fx._tick = spy
                t0 = clock.time
                for d in dts:
                    w.step(1, dt=d)
                self.assertAlmostEqual(seen[0], clock.time - t0, places=6)
                fx.destroy()

    def test_shake_and_flash_end_while_paused(self):
        with system_world(draw=True) as w:
            Circle(center=(200, 150), radius=30, color="red")
            w.step(2)
            canvas.shake(12)
            canvas.flash(0.8)
            clock.paused = True
            try:
                w.step(180)
                hit = w.fw.post_fx_stack._hit
                self.assertLess(hit._shake, 0.5)
                self.assertLess(hit._flash, 0.05)
            finally:
                clock.paused = False


if __name__ == "__main__":
    unittest.main()
