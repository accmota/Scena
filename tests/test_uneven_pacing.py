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


if __name__ == "__main__":
    unittest.main()
