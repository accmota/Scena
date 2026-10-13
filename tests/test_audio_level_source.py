"""Audio levels as formula sources: ``@= lambda: mic.level`` / ``audio.level`` / ``h.level``.

A level is written by an audio thread, off the reactive graph. A formula that
reads it depends on a ``LevelSource`` node that the frame's audio sample dirties
when the capture / the mix published (Sound Design, "Analysis").

Run: python tests/run_tiers.py focused test_audio_level_source
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import miniaudio
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import Circle, Entity, Rect, after, amp_db, audio, play_sound, st, when  # noqa: E402
from scena import level_source  # noqa: E402
from scena.audio_capture import Microphone  # noqa: E402
from scena.level_source import LEVEL_SOURCES, LevelSource  # noqa: E402
from system_support import SystemTestCase, system_world, tone  # noqa: E402
from leftovers import module_sweep  # noqa: E402

# Its tests build Rects and Recorders the world teardown does not reach: a later
# module counting a layer's objects (test_cull's backoff) saw them.
setUpModule, tearDownModule = module_sweep()


def _block(amp: float, n: int = 800) -> bytes:
    """One capture block: a constant ``amp`` on both channels."""
    return np.full((n, 2), amp, dtype=np.float32).tobytes()


def _null_mic() -> Microphone:
    return Microphone(backends=[miniaudio.Backend.NULL])


class TestMicLevelIsASource(SystemTestCase, unittest.TestCase):
    world_draw = False

    def setUp(self):
        super().setUp()
        self.mic = _null_mic()

    def tearDown(self):
        self.mic.close()
        super().tearDown()

    def feed(self, amp, frames=1):
        for _ in range(frames):
            self.mic._ingest(_block(amp))
            self.w.step(1)

    def test_formula_follows_the_level(self):
        mic = self.mic
        bar = Rect(top_left=(0, 0), width=1, height=10)
        bar["width"] @= lambda: 300 * mic.level
        self.assertEqual(bar.width, 0.0)
        self.feed(0.5)
        self.assertGreater(mic.level, 0.0)
        self.assertAlmostEqual(bar.width, 300 * mic.level)
        self.feed(0.5, frames=5)
        self.assertAlmostEqual(bar.width, 300 * mic.level)

    def test_amp_db_and_spectrum_follow(self):
        mic = self.mic
        bar = Rect(top_left=(0, 0), width=1, height=10)
        bar["width"] @= lambda: 300 * amp_db(mic.level)
        bar["height"] @= lambda: 1 + 100 * mic.spectrum(8)[0]
        self.feed(0.5, frames=3)
        self.assertAlmostEqual(bar.width, 300 * amp_db(mic.level))
        self.assertAlmostEqual(bar.height, 1 + 100 * mic.spectrum(8)[0])

    def test_when_fires_once_on_the_rise(self):
        mic = self.mic
        hits = []

        @when(lambda: mic.level > 0.2)
        def loud():
            hits.append(mic.level)

        self.feed(0.0, frames=2)
        self.assertEqual(hits, [])
        self.feed(0.9, frames=6)
        self.assertEqual(len(hits), 1)

    def test_on_change_hears_the_level(self):
        from scena import on_change
        mic = self.mic
        seen = []
        on_change(lambda: round(mic.level, 3))(lambda value: seen.append(value))
        self.feed(0.0, frames=2)
        before = len(seen)
        self.feed(0.6, frames=3)
        self.assertGreater(len(seen), before)
        self.assertGreater(seen[-1], 0.0)

    def test_a_mic_held_by_an_entity_follows(self):
        """The chain ``g.mic.level`` used to depend on ``g`` only: accepted, frozen."""
        mic = self.mic

        class Recorder(Circle):
            def setup(self):
                self.mic = mic
                self.bar = Rect(top_left=(0, 0), width=1, height=10)
                self.bar["width"] @= lambda: 300 * self.mic.level

        g = Recorder(radius=4)
        other = Rect(top_left=(0, 20), width=1, height=10)
        other["width"] @= lambda: 300 * amp_db(g.mic.level)
        self.feed(0.5, frames=2)
        self.assertGreater(mic.level, 0.0)
        self.assertAlmostEqual(g.bar.width, 300 * mic.level)
        self.assertAlmostEqual(other.width, 300 * amp_db(mic.level))

    def test_a_mic_held_in_a_state_cell_follows(self):
        """``st.mic.level``: the chain stopped at the cell, so the formula
        depended on ``st["mic"]`` only and stayed at 0 while the level moved."""
        from scena import State
        hud = State(name="hud_mic")
        hud.mic = self.mic
        st.mic_t = self.mic
        a = Rect(top_left=(0, 0), width=1, height=10)
        b = Rect(top_left=(0, 20), width=1, height=10)
        try:
            a["width"] @= lambda: 300 * hud.mic.level
            b["width"] @= lambda: 300 * amp_db(st.mic_t.level)
            self.feed(0.5, frames=2)
            self.assertGreater(self.mic.level, 0.0)
            self.assertAlmostEqual(a.width, 300 * self.mic.level)
            self.assertAlmostEqual(b.width, 300 * amp_db(self.mic.level))
        finally:
            a["width"].unlink()
            b["width"].unlink()
            st.mic_t = None

    def test_a_mic_not_opened_yet_names_the_read_and_the_fix(self):
        """``g.mic.level`` with ``g.mic`` None raised Python's bare "'NoneType'
        object has no attribute 'level'", also behind ``if g.mic else 0``
        (sources are learned at link time; Sound Design said it linked)."""

        class Recorder(Circle):
            def setup(self):
                self.mic = None

        g = Recorder(radius=4)
        bar = Rect(top_left=(0, 0), width=1, height=10)
        for formula in (lambda: 300 * g.mic.level,
                        lambda: amp_db(g.mic.level) if g.mic else 0):
            with self.subTest(formula=formula):
                with self.assertRaises(AttributeError) as cm:
                    bar["width"] @= formula
                msg = str(cm.exception)
                self.assertIn("g.mic.level", msg)
                self.assertIn("g.mic is None when the formula is linked", msg)

    def test_close_drops_the_formula_to_zero(self):
        mic = self.mic
        bar = Rect(top_left=(0, 0), width=1, height=10)
        bar["width"] @= lambda: 300 * mic.level
        self.feed(0.5, frames=2)
        self.assertGreater(bar.width, 0.0)
        mic.close()
        self.w.step(1)
        self.assertEqual(bar.width, 0.0)

    def test_two_mics_have_their_own_node(self):
        mic, other = self.mic, _null_mic()
        try:
            a = Rect(top_left=(0, 0), width=1, height=10)
            b = Rect(top_left=(0, 20), width=1, height=10)
            a["width"] @= lambda: 300 * mic.level
            b["width"] @= lambda: 300 * other.level
            self.assertIsNot(mic._formula_source(), other._formula_source())
            self.feed(0.5, frames=2)
            self.assertGreater(a.width, 0.0)
            self.assertEqual(b.width, 0.0)
        finally:
            other.close()

    def test_link_from_source_less_lambda(self):
        """REPL / ``exec``: the mic reached as a global is still a source."""
        mic = self.mic
        bar = Rect(top_left=(0, 0), width=1, height=10)
        ns = {"mic": mic, "bar": bar}
        exec("bar['width'] @= lambda: 300 * mic.level", ns)
        self.feed(0.5, frames=2)
        self.assertAlmostEqual(bar.width, 300 * mic.level)

    def test_source_less_lambda_through_an_entity(self):
        """Tutorial 21 run from a string: ``lambda: amp_db(self.mic.level)``
        inside a method found only ``self`` (the Entity) and froze."""
        mic = self.mic
        ns = {"mic": mic}
        exec(
            "from scena import *\n"
            "class Gravador(Circle, radius=4):\n"
            "    def setup(self):\n"
            "        self.mic = None\n"
            "    def abrir(self):\n"
            "        self.mic = mic\n"
            "        st['voz_t18'] @= lambda: amp_db(self.mic.level)\n"
            "st.voz_t18 = 0\n"
            "g = Gravador()\n"
            "g.abrir()\n",
            ns,
        )
        try:
            self.feed(0.5, frames=2)
            self.assertGreater(st.voz_t18, 0.0)
            self.assertAlmostEqual(st.voz_t18, amp_db(mic.level))
        finally:
            st["voz_t18"].unlink()


class TestSamplingCost(unittest.TestCase):
    """Nothing is created or sampled until a formula links a level."""

    def test_no_node_without_a_formula(self):
        with system_world(draw=False) as w:
            mic = _null_mic()
            try:
                _ = mic.level, mic.spectrum(), audio.level
                mic._ingest(_block(0.5))
                w.step(3)
                self.assertEqual(LEVEL_SOURCES, [])
                self.assertNotIn("_level_source", mic.__dict__)
            finally:
                mic.close()

    def test_frame_skips_the_sample_when_nothing_is_linked(self):
        with system_world(draw=False) as w, \
                mock.patch("scena.orchestration.sample_level_sources") as sample:
            w.step(2)
            sample.assert_not_called()

    def test_an_unchanged_level_does_not_dirty(self):
        with system_world(draw=False) as w:
            mic = _null_mic()
            try:
                bar = Rect(top_left=(0, 0), width=1, height=10)
                bar["width"] @= lambda: 300 * mic.level
                src = mic._formula_source()
                with mock.patch.object(LevelSource, "update", autospec=True) as up:
                    w.step(3)                       # no capture: no update
                    self.assertEqual(up.call_count, 0)
                    mic._ingest(_block(0.5))
                    w.step(1)
                    self.assertEqual(up.call_count, 1)
                    self.assertIs(up.call_args[0][0], src)
            finally:
                mic.close()

    def test_a_collected_mic_leaves_the_sample_list(self):
        import gc
        with system_world(draw=False) as w:
            mic = _null_mic()
            mic._formula_source()
            self.assertEqual(len(LEVEL_SOURCES), 1)
            mic.close()
            del mic
            gc.collect()
            w.step(1)
            self.assertEqual(LEVEL_SOURCES, [])


class TestMixLevelsAreSources(unittest.TestCase):
    def test_audio_level_and_a_sound_level_follow(self):
        with system_world(draw=False) as w:
            h = play_sound(tone(duration=1.0, amp=0.5))
            mix = Rect(top_left=(0, 0), width=1, height=10)
            voice = Rect(top_left=(0, 20), width=1, height=10)
            mix["width"] @= lambda: 300 * audio.level
            voice["width"] @= lambda: 300 * h.level
            w.step(4)
            self.assertGreater(audio.level, 0.0)
            self.assertAlmostEqual(mix.width, 300 * audio.level)
            self.assertAlmostEqual(voice.width, 300 * h.level)
            self.assertGreater(voice.width, 0.0)
            # One node for the whole mix: every voice reads the same snapshot.
            self.assertIs(h._formula_source(), audio._formula_source())
            h.cancel()

    def test_a_timer_handle_has_no_level(self):
        with system_world(draw=False):
            t = after(1, lambda: None)
            bar = Rect(top_left=(0, 0), width=1, height=10)
            with self.assertRaisesRegex(AttributeError, "play_sound"):
                bar["width"] @= lambda: 300 * t.level
            t.cancel()


class TestGraphReset(unittest.TestCase):
    def test_a_link_after_a_graph_reset_uses_the_new_graph(self):
        from scena.state import get_scena_system, init_scena_system
        mic = _null_mic()
        try:
            with system_world(draw=False):
                old = mic._formula_source()
            init_scena_system()
            with system_world(draw=False) as w:
                new = mic._formula_source()
                self.assertIsNot(new, old)
                self.assertIs(new._scena_system, get_scena_system())
                bar = Rect(top_left=(0, 0), width=1, height=10)
                bar["width"] @= lambda: 300 * mic.level
                mic._ingest(_block(0.5))
                w.step(1)
                self.assertGreater(bar.width, 0.0)
                self.assertFalse(any(s is old for s in LEVEL_SOURCES))
        finally:
            mic.close()

    def test_a_cleared_list_registers_again(self):
        mic = _null_mic()
        try:
            with system_world(draw=False) as w:
                src = mic._formula_source()
                level_source.reset_level_sources()
                self.assertIs(mic._formula_source(), src)
                self.assertTrue(any(s is src for s in LEVEL_SOURCES))
        finally:
            mic.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
