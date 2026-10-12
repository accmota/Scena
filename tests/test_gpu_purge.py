"""The run loop frees GPU resources unused for a second, twice a second.

Rule under test (Canvas Design.md, "GPU memory"): after each present,
``ScenaFramework._purge_idle_gpu`` calls Skia's
``purgeResourcesNotUsedInMs(GPU_PURGE_IDLE_S)`` at most once per
``GPU_PURGE_EVERY_S`` of wall time. Neon on moving shapes filled Skia's GPU
cache with one-use blur masks (~1.3 GB of process memory); textures drawn in
the last second are never purged. No context (headless) or a failing call
does nothing.

Bug class guarded: a purge that runs every frame (cost), never (memory), or
with the wrong unit (the binding takes a ``timedelta``).
"""
import datetime
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena  # noqa: F401
from scena.orchestration import GPU_PURGE_EVERY_S, GPU_PURGE_IDLE_S, ScenaFramework

O = sys.modules["scena.orchestration"]


class FakeContext:
    def __init__(self):
        self.calls = []

    def purgeResourcesNotUsedInMs(self, idle):
        if not isinstance(idle, datetime.timedelta):
            raise TypeError("the binding takes a timedelta")
        self.calls.append(idle)


class TestPurgeCadence(unittest.TestCase):
    def fw(self, ctx):
        fw = ScenaFramework.get_instance()
        patch = mock.patch.object(fw, "_context", ctx)
        patch.start()
        self.addCleanup(patch.stop)
        fw._gpu_purge_t = 0.0
        return fw

    def test_twice_a_second_with_a_one_second_age(self):
        ctx = FakeContext()
        fw = self.fw(ctx)
        t = 100.0
        for _ in range(240):                  # 4 s of 60 fps frames
            fw._purge_idle_gpu(t)
            t += 1.0 / 60.0
        self.assertIn(len(ctx.calls), (7, 8, 9))
        self.assertTrue(all(c == datetime.timedelta(seconds=GPU_PURGE_IDLE_S) for c in ctx.calls))
        self.assertEqual((GPU_PURGE_IDLE_S, GPU_PURGE_EVERY_S), (1.0, 0.5))

    def test_headless_and_errors_do_nothing(self):
        fw = self.fw(None)
        fw._purge_idle_gpu(50.0)

        class Broken:
            def purgeResourcesNotUsedInMs(self, idle):
                raise RuntimeError("driver")

        fw = self.fw(Broken())
        fw._purge_idle_gpu(60.0)

    def test_zero_turns_it_off(self):
        ctx = FakeContext()
        fw = self.fw(ctx)
        with mock.patch.object(O, "GPU_PURGE_IDLE_S", 0.0):
            for k in range(10):
                fw._purge_idle_gpu(200.0 + k)
        self.assertEqual(ctx.calls, [])


if __name__ == "__main__":
    unittest.main()
