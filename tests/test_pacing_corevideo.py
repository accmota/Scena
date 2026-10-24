"""macOS display link (scena/_display_link.py): ctypes layout, the callback →
grid path, and a live CoreVideo run (macOS only).

A wrong struct layout reads garbage timestamps silently; a callback left
running into interpreter shutdown crashes. Both are guarded here.

    python tests/run_tiers.py focused test_pacing_corevideo
"""
from __future__ import annotations

import ctypes
import sys
import time
import unittest

from scena import _display_link as dl
from scena.pacing import FramePacer, PaceMode, Strategy


class TestLayout(unittest.TestCase):
    def test_cvtimestamp_matches_corevideo_abi(self):
        # CVTimeStamp (CVBase.h): 80 bytes on 64-bit; hostTime at offset 16.
        self.assertEqual(ctypes.sizeof(dl.CVTimeStamp), 80)
        self.assertEqual(dl.CVTimeStamp.hostTime.offset, 16)
        self.assertEqual(dl.CVTimeStamp.videoRefreshPeriod.offset, 32)
        self.assertEqual(ctypes.sizeof(dl.CVTime), 16)
        self.assertEqual(ctypes.sizeof(dl.CGPoint), 16)


class TestCallbackPath(unittest.TestCase):
    def test_callback_stamps_reach_the_grid(self):
        link = dl.DisplayLink()
        link._scale, link._offset = 1e-9, 0.0  # host ticks in ns
        period_ns = 16_667_000
        for i in range(10):
            ts = dl.CVTimeStamp()
            ts.hostTime = 1_000_000_000 + i * period_ns
            link._on_vsync(None, None, ctypes.pointer(ts), 0, None, None)
        link.poll(1.0 + 9 * period_ns * 1e-9)
        self.assertEqual(link.grid.count, 10)
        self.assertAlmostEqual(link.grid.period, period_ns * 1e-9, delta=1e-9)
        ok, reason = link.grid.health(1.0 + 9.5 * period_ns * 1e-9)
        self.assertTrue(ok, reason)

    def test_callback_never_raises(self):
        link = dl.DisplayLink()
        self.assertEqual(link._on_vsync(None, None, None, 0, None, None), 0)

    def test_start_off_macos_reports_error(self):
        if sys.platform == "darwin":
            self.skipTest("macOS runs the live test instead")
        link = dl.DisplayLink()
        self.assertFalse(link.start())
        self.assertIn("macOS", link.error)


@unittest.skipUnless(sys.platform == "darwin", "CoreVideo is macOS-only")
class TestLiveCoreVideo(unittest.TestCase):
    def test_host_time_matches_perf_counter(self):
        _scale, offset = dl.host_time_scale()
        self.assertLess(abs(offset), 0.001)

    def test_live_link_gives_a_healthy_grid_and_stops(self):
        link = dl.DisplayLink()
        if not link.start():
            self.skipTest(f"no display link here: {link.error}")
        try:
            self.assertIn(link, dl._LIVE_LINKS)
            deadline = time.perf_counter() + 0.6
            while time.perf_counter() < deadline:
                sum(range(20000))  # hold the GIL like a busy frame
                link.poll(time.perf_counter())
            ok, reason = link.grid.health(time.perf_counter())
            self.assertTrue(ok, reason)
            self.assertLess(link.grid.fit()[2], 0.0005)
        finally:
            link.stop()
        self.assertNotIn(link, dl._LIVE_LINKS)

    def test_pacer_uses_display_link_on_macos(self):
        pacer = FramePacer(display_link_factory=dl.DisplayLink, warn=lambda m: None)
        pacer.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)
        try:
            if pacer.strategy is not Strategy.DISPLAY_LINK:
                self.skipTest(f"display link unavailable: {pacer.fallback_reason}")
            deadline = time.perf_counter() + 0.1
            while time.perf_counter() < deadline:
                pacer._link.poll(time.perf_counter())
                time.sleep(0.002)
            presents, slots = [], []
            for _ in range(20):
                pacer.wait_for_present()
                slots.append(pacer._slot)
                pacer.presented()
                presents.append(time.perf_counter())
            period = pacer.vblank_period()
            steps = [round((b - a) / period) for a, b in zip(presents[2:], presents[3:])]
            targets = [round((b - a) / period) for a, b in zip(slots[2:], slots[3:])]
            # Locked to the link: never two presents for one vblank, and most one
            # apart. A loaded machine may miss a vblank (a step of 2, the next
            # one waited for): the quick tier saw it once (WP36). The vblanks are
            # the ones each present targeted, not the clock after it: a thread
            # stalled past its vblank presents late for one already gone, then
            # on time for the next, 0.4 period later on the clock ([5, 0] in a
            # loaded gate, WP37).
            self.assertNotIn(0, targets, (targets, steps))
            self.assertEqual(sorted(steps)[len(steps) // 2], 1, steps)
        finally:
            pacer.stop()


if __name__ == "__main__":
    unittest.main()
