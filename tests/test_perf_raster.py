"""The CPU raster probe (scripts/bench/perf_raster.py) measures the real field.

The probe times ``Embers`` through the engine's own ``draw``, so its rows
compare machines (WP47: the Windows machine's skia, built with MSVC, ran a
2000 x 1200 Embers frame in ~34 s). Bug class: **a probe blind to the
engine**: a probe that stops drawing (a renamed uniform, a changed ``draw``
signature) still prints a fast row. These tests draw at a tiny size and read
the pixels.

    python tests/run_tiers.py focused test_perf_raster
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

import numpy as np  # noqa: E402
import skia  # noqa: E402

import perf_raster  # noqa: E402


class TestProbeDrawsTheRealField(unittest.TestCase):
    def test_every_case_draws_pixels(self):
        w, h = 64, 40
        for name, draw in perf_raster._cases(w, h).items():
            with self.subTest(case=name):
                surface = skia.Surface(w, h)
                surface.getCanvas().clear(skia.ColorBLACK)
                draw(surface.getCanvas())
                px = np.asarray(surface.makeImageSnapshot().toarray(
                    colorType=skia.kRGBA_8888_ColorType))
                self.assertGreater(int(px[..., :3].max()), 0, f"{name} drew nothing")

    def test_measure_returns_a_time_for_every_case(self):
        rows = perf_raster.measure((32, 20), repeats=1)
        self.assertEqual(list(rows), list(perf_raster._cases(32, 20)))
        self.assertTrue(all(ms > 0.0 for ms in rows.values()), rows)

    def test_build_names_skia(self):
        self.assertIn(f"skia {skia.__version__}", perf_raster.skia_build())


if __name__ == "__main__":
    unittest.main()
