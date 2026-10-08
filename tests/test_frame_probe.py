"""The bench frame probe (scripts/bench/frame_probe.py) keeps up with the engine.

Bug class: **a probe blind to a renamed engine hook.** The probe wraps engine
functions by name. When ``Clock.tick`` became ``Clock._tick`` (and
``PostFxStack.render`` became ``_render``), ``_patch`` skipped the missing
names silently: the probe saw no frames, so a ``--seconds`` run never asked
the window to close and every jitter / longrun / Windows run hung. Now a
missing target raises at install, and these tests install the probe on the
real engine.

    python tests/run_tiers.py focused test_frame_probe
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "scripts", "bench")
for _p in (ROOT, BENCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import frame_probe  # noqa: E402
import jitter_probe  # noqa: E402
from scena import init  # noqa: E402


class TestInstallOnTheRealEngine(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)

    def test_every_target_exists_and_uninstall_restores(self):
        probe = frame_probe.FrameProbe(vsync=False)
        probe.install()  # raises if an engine hook was renamed
        try:
            patched = list(probe._orig)
            self.assertGreaterEqual(len(patched), 16)
            names = {name for _owner, name, _orig in patched}
            for hook in ("_tick", "_render", "swap_buffers", "wait_for_present", "run"):
                self.assertIn(hook, names)
            before = [(owner, name, orig) for owner, name, orig in patched]
        finally:
            probe.uninstall()
        for owner, name, orig in before:
            self.assertIs(getattr(owner, name), orig, f"{name} not restored")

    def test_missing_target_is_loud(self):
        probe = frame_probe.FrameProbe(vsync=False)

        class Engine:
            pass

        with self.assertRaisesRegex(RuntimeError, r"Engine\.tick not found"):
            probe._patch(Engine, "tick", lambda orig: orig)

    def test_timed_run_asks_to_stop(self):
        """The hang itself: frames must reach the probe and end the run."""
        from scena.orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        probe = frame_probe.FrameProbe(seconds=0.05, vsync=False)
        probe.install()
        saved = fw._running
        try:
            probe.fw = fw
            probe._armed = True
            fw._running = True
            fw.clock._tick(100.0)
            self.assertIsNotNone(probe._t0, "probe saw no frame start")
            fw.clock._tick(100.1)
            self.assertTrue(probe._stop_requested)
        finally:
            probe._armed = False
            probe.uninstall()
            fw._running = saved


class TestPresentChoices(unittest.TestCase):
    def test_every_present_choice_maps_to_a_framerate(self):
        from scena.orchestration import coerce_framerate
        for p in jitter_probe.PRESENTS:
            with self.subTest(present=p):
                if p in ("keep", "auto"):
                    continue
                self.assertIn(p, frame_probe.FrameProbe.PRESENT_FRAMERATE)
                coerce_framerate(frame_probe.FrameProbe.PRESENT_FRAMERATE[p])


if __name__ == "__main__":
    unittest.main()
