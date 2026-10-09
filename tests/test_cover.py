"""Canvas cover overlay: fade_in / fade_out (fade · wipe · iris).

    python -m unittest tests.test_cover -v
"""
from __future__ import annotations

import os
import sys
import unittest

import skia

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import canvas, init
from scena import cover as cv


def _clock():
    state = {"t": 10.0}

    def now():
        return state["t"]

    def set_t(t):
        state["t"] = float(t)

    def advance(dt):
        state["t"] += float(dt)

    return now, set_t, advance


class CoverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def setUp(self):
        self.now, self.set_t, self.advance = _clock()
        cv.set_now_fn(self.now)
        cv.reset_cover()
        canvas.effects.clear()
        canvas.effects.enabled = True

    def tearDown(self):
        cv.reset_cover()
        cv.set_now_fn(None)

    def _tick(self):
        cv.tick_cover(self.now())


class TestFadeHold(CoverTest):
    def test_fade_out_holds_at_one(self):
        canvas.fade_out(0.5)
        self.assertAlmostEqual(canvas.covered, 0.0, places=4)
        self.advance(0.25)
        self._tick()
        self.assertAlmostEqual(canvas.covered, 0.5, places=4)
        self.advance(0.25)
        self._tick()
        self.assertAlmostEqual(canvas.covered, 1.0, places=4)
        self.advance(1.0)
        self._tick()
        self.assertAlmostEqual(canvas.covered, 1.0, places=4)
        self.assertTrue(cv.get_cover()._is_active())

    def test_fade_in_from_hold(self):
        canvas.fade_out(0.0)
        self.assertAlmostEqual(canvas.covered, 1.0, places=4)
        canvas.fade_in(0.4)
        self.advance(0.2)
        self._tick()
        self.assertAlmostEqual(canvas.covered, 0.5, places=4)
        self.advance(0.2)
        self._tick()
        self.assertAlmostEqual(canvas.covered, 0.0, places=4)
        self.assertFalse(cv.get_cover()._is_active())

    def test_opening_fade_in_snaps_to_cover(self):
        self.assertEqual(canvas.covered, 0.0)
        canvas.fade_in(0.5)
        self.assertAlmostEqual(canvas.covered, 1.0, places=4)
        self.advance(0.5)
        self._tick()
        self.assertAlmostEqual(canvas.covered, 0.0, places=4)

    def test_default_color_is_black(self):
        canvas.fade_out(0.0)
        self.assertEqual(cv.get_cover().color, (0.0, 0.0, 0.0))

    def test_color_navy(self):
        canvas.fade_out(0.0, color="navy")
        r, g, b = cv.get_cover().color
        self.assertLess(r, 0.1)
        self.assertLess(g, 0.1)
        self.assertGreater(b, 0.4)

    def test_duration_zero_is_instant(self):
        done = []
        canvas.fade_out(0, on_done=lambda: done.append("out"))
        self.assertEqual(done, ["out"])
        self.assertAlmostEqual(canvas.covered, 1.0, places=4)
        canvas.fade_in(0, on_done=lambda: done.append("in"))
        self.assertEqual(done, ["out", "in"])
        self.assertAlmostEqual(canvas.covered, 0.0, places=4)

    def test_negative_duration_raises(self):
        with self.assertRaises(ValueError):
            canvas.fade_out(-0.1)

    def test_non_numeric_duration_raises(self):
        with self.assertRaises(TypeError):
            canvas.fade_out("slow")  # type: ignore[arg-type]

    def test_returns_canvas(self):
        self.assertIs(canvas.fade_out(0.2), canvas)
        self.assertIs(canvas.fade_in(0.2), canvas)

    def test_does_not_activate_post_stack(self):
        canvas.fade_out(0.3)
        self.assertFalse(canvas.effects._is_active)
        self.assertEqual(len(canvas.effects), 0)


class TestOnDone(CoverTest):
    def test_on_done_fires_once_at_end(self):
        hits = []
        canvas.fade_out(0.4, on_done=lambda: hits.append(canvas.covered))
        self.advance(0.2)
        self._tick()
        self.assertEqual(hits, [])
        self.advance(0.2)
        self._tick()
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0], 1.0, places=4)
        self.advance(0.5)
        self._tick()
        self.assertEqual(len(hits), 1)

    def test_on_done_error_propagates_once(self):
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("cover done bug")

        canvas.fade_out(0.2, on_done=boom)
        self.advance(0.3)
        with self.assertRaisesRegex(RuntimeError, "cover done bug"):
            self._tick()
        self.assertAlmostEqual(canvas.covered, 1.0, places=4)
        self._tick()
        self.assertEqual(calls, [1])

    def test_on_done_arity_truncated(self):
        seen = []
        canvas.fade_out(0.0, on_done=lambda c: seen.append(c))
        self.assertIs(seen[0], canvas)
        seen.clear()
        canvas.fade_in(0.0, on_done=lambda: seen.append("z"))
        self.assertEqual(seen, ["z"])

    def test_replace_fires_first_on_done(self):
        done = []
        canvas.fade_out(0.5, on_done=lambda: done.append("first"))
        canvas.fade_out(0.5, on_done=lambda: done.append("second"))
        self.assertEqual(done, ["first"])
        self.advance(0.5)
        self._tick()
        self.assertEqual(done, ["first", "second"])

    def test_non_callable_on_done_raises(self):
        with self.assertRaises(TypeError):
            canvas.fade_out(0.2, on_done="nope")  # type: ignore[arg-type]

    def test_then_is_not_a_parameter(self):
        with self.assertRaises(TypeError):
            canvas.fade_out(0.2, then=lambda: None)  # type: ignore[call-arg]


class TestStyles(CoverTest):
    def test_default_style_is_fade(self):
        canvas.fade_out(0.0)
        self.assertEqual(cv.get_cover().style, "fade")

    def test_wipe_and_iris(self):
        canvas.fade_out(0.0, style="wipe", angle=90)
        self.assertEqual(cv.get_cover().style, "wipe")
        self.assertAlmostEqual(cv.get_cover().angle, 90.0)
        canvas.fade_out(0.0, style="iris", center=(10, 20))
        self.assertEqual(cv.get_cover().style, "iris")
        self.assertEqual(cv.get_cover().center, (10.0, 20.0))

    def test_fade_in_keeps_style(self):
        canvas.fade_out(0.0, style="wipe", angle=180, color="navy")
        canvas.fade_in(0.4)
        self.assertEqual(cv.get_cover().style, "wipe")
        self.assertAlmostEqual(cv.get_cover().angle, 180.0)

    def test_unknown_style_raises(self):
        with self.assertRaises(ValueError) as ctx:
            canvas.fade_out(0.2, style="vortex")
        self.assertIn("fade", str(ctx.exception))
        self.assertIn("wipe", str(ctx.exception))
        self.assertIn("iris", str(ctx.exception))

    def test_style_fade_explicit(self):
        canvas.fade_out(0.0, style="wipe")
        canvas.fade_out(0.0, style="fade")
        self.assertEqual(cv.get_cover().style, "fade")


class TestDraw(CoverTest):
    def _pixels(self, w=80, h=60):
        surf = skia.Surface(w, h)
        c = surf.getCanvas()
        c.clear(skia.ColorWHITE)
        cv.draw_cover(c, w, h)
        return surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)

    def test_uncovered_is_noop(self):
        px = self._pixels()
        # White clear, no cover.
        self.assertGreater(px[30, 40, 0], 250)

    def test_fade_out_tints_frame(self):
        canvas.fade_out(0.0)
        px = self._pixels()
        # Fully covered black.
        self.assertLess(px[30, 40, 0], 10)
        self.assertLess(px[30, 40, 1], 10)
        self.assertLess(px[30, 40, 2], 10)

    def test_wipe_and_iris_full_cover_are_solid(self):
        canvas.fade_out(0.0, style="wipe", angle=0)
        px = self._pixels(w=100, h=40)
        self.assertLess(int(px[20, 95, 0]), 10)
        canvas.fade_out(0.0, style="iris")
        px = self._pixels(w=100, h=60)
        self.assertLess(int(px[30, 50, 0]), 10)

    def test_wipe_covers_incoming_side(self):
        # angle=0: cover from -x (left) toward +x.
        cv.get_cover().style = "wipe"
        cv.get_cover().angle = 0.0
        cv.get_cover().color = (0.0, 0.0, 0.0)
        cv.get_cover().amount = 0.35
        px = self._pixels(w=100, h=40)
        left = px[20, 5]
        right = px[20, 95]
        self.assertLess(int(left[0]), 40)
        self.assertGreater(int(right[0]), 200)

    def test_iris_center_stays_open_midway(self):
        cv.get_cover().style = "iris"
        cv.get_cover().center = (50.0, 30.0)
        cv.get_cover().color = (0.0, 0.0, 0.0)
        cv.get_cover().amount = 0.35
        px = self._pixels(w=100, h=60)
        mid = px[30, 50]
        corner = px[2, 2]
        self.assertGreater(int(mid[0]), 200)
        self.assertLess(int(corner[0]), 40)


class TestCoverRunsOnPresentationTime(unittest.TestCase):
    """The cover is presentation: it runs while the world is paused or
    slowed, and a hitch advances it at most MAX_FRAME_DT (design decision,
    review 2026-10-09 S1-6; Scena Design "Clocks")."""

    def test_fade_out_finishes_while_paused(self):
        from scena import clock
        from tests.system_support import system_world
        done = []
        with system_world(draw=False) as w:
            clock.paused = True
            try:
                canvas.fade_out(0.5, on_done=lambda: done.append(clock.time))
                w.step(40, dt=1 / 60)
            finally:
                clock.paused = False
                cv.reset_cover()
        self.assertEqual(len(done), 1, "fade_out never finished under clock.paused")

    def test_slow_motion_does_not_slow_the_fade(self):
        from scena import clock
        from tests.system_support import system_world
        frames = []
        with system_world(draw=False) as w:
            clock.scale = 0.25
            try:
                canvas.fade_out(0.5, on_done=lambda: frames.append(w.frames_run))
                w.step(60, dt=1 / 60)
            finally:
                clock.scale = 1.0
                cv.reset_cover()
        self.assertTrue(frames and frames[0] <= 31, frames)

    def test_presentation_time_is_unscaled_and_capped(self):
        from scena.input import Clock, MAX_FRAME_DT
        c = Clock()
        c._last_time = 0.0
        c._tick(1.0)                      # a 1 s hitch
        self.assertAlmostEqual(c._ui_time, MAX_FRAME_DT)
        c.paused = True
        c._tick(1.1)
        self.assertAlmostEqual(c._ui_time, MAX_FRAME_DT + 0.1)
        self.assertAlmostEqual(c.time, MAX_FRAME_DT)   # the world stayed put
        c.advance(0.5)                     # an explicit step is taken as given
        self.assertAlmostEqual(c._ui_time, MAX_FRAME_DT + 0.6)


if __name__ == "__main__":
    unittest.main()
