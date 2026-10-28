"""The GIL probe (scripts/bench/perf_audio_gil.py) mixes what it says it times.

The probe's rows compare machines (WP51: a 40 ms block beside a busy thread,
~350x faster at the device's switch interval on the Windows laptop, ~8x on
the Mac, 0.2-1.7x on GitHub's runners, which is why it is a probe and not a
test). Bug class: **a probe blind to the engine**: a probe that mixes
silence, or times its own copy of the interval, still prints a row. These
tests read the block and the interval, never a clock.

    python tests/run_tiers.py focused test_perf_audio_gil
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

import perf_audio_gil  # noqa: E402
from scena.audio_mixer import AUDIO_SWITCH_INTERVAL  # noqa: E402


class TestProbeMixesTheRealVoices(unittest.TestCase):
    def test_the_block_holds_every_voice(self):
        m = perf_audio_gil.mixer()
        self.assertEqual(len(m.voices), perf_audio_gil.VOICES)
        block = np.asarray(m.render_block(perf_audio_gil.BLOCK).block)
        self.assertEqual(block.shape, (perf_audio_gil.BLOCK, 2))
        self.assertGreater(float(np.abs(block).max()), 0.0, "the probe mixed silence")

    def test_it_times_the_engines_interval_and_restores_the_callers(self):
        before = sys.getswitchinterval()
        rows = perf_audio_gil.measure(repeats=1, voices=1)
        self.assertEqual(sys.getswitchinterval(), before)
        self.assertEqual(list(rows), ["alone", "busy, 5 ms",
                                      f"busy, {AUDIO_SWITCH_INTERVAL * 1000:g} ms"])
        self.assertTrue(all(ms > 0.0 for ms in rows.values()), rows)


if __name__ == "__main__":
    unittest.main()
