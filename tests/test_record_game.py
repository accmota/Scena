"""tools/video/record_game.py: gameplay videos with sound, rendered offline.

Bug classes guarded:

* **Picture and sound drift apart.** Frame ``i`` of the video and samples
  ``[i*735, (i+1)*735)`` must be the same 1/60 s. Integer frame edges
  (``frame_samples``) keep any run of frames at its exact length, and a sound
  started on the frame something changes colour starts in that frame's block
  (``TestSync``: the colour and the sound come from the same callback).
* **Two clocks advance the voices.** The recorder is the sound card: while it
  is open the mixer is not ``offline`` and the engine's world-time pump
  (``Mixer.pump_dt``) must do nothing, else a sound plays twice as fast and
  ends early (``TestSoundCard``).
* **A frame size the encoder refuses.** 4:2:0 video needs even edges: the
  game is fitted with even edges whatever its design aspect.

    python -m unittest tests.test_record_game -v
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "video"))

import record_game as rg  # noqa: E402
from scena.audio_mixer import Mixer, make_sine  # noqa: E402


class TestFrameSamples(unittest.TestCase):
    def test_sixty_fps_is_735_samples_a_frame(self):
        self.assertEqual({rg.frame_samples(i, 44100) for i in range(600)}, {735})
        self.assertEqual({rg.frame_samples(i, 48000) for i in range(600)}, {800})

    def test_any_run_of_frames_has_its_exact_length(self):
        for rate in (44100, 48000, 22050, 11025):
            for start, n in ((0, 1), (7, 13), (59, 61), (1000, 3600)):
                total = sum(rg.frame_samples(i, rate) for i in range(start, start + n))
                self.assertEqual(total, (start + n) * rate // 60 - start * rate // 60)
            self.assertEqual(sum(rg.frame_samples(i, rate) for i in range(60 * 90)), 90 * rate)


class TestFitSize(unittest.TestCase):
    def test_same_aspect_fills_the_frame(self):
        self.assertEqual(rg.fit_size((640, 360), (1920, 1080)), (1920, 1080))

    def test_other_aspect_is_letterboxed(self):
        self.assertEqual(rg.fit_size((600, 480), (1920, 1080)), (1350, 1080))
        self.assertEqual(rg.fit_size((900, 300), (1920, 1080)), (1920, 640))

    def test_edges_are_even(self):
        for design in ((601, 451), (333, 200), (500, 380), (777, 999)):
            for box in ((1920, 1080), (1280, 720), (2560, 1440), (854, 480)):
                w, h = rg.fit_size(design, box)
                self.assertEqual((w % 2, h % 2), (0, 0), (design, box))
                self.assertLessEqual(w, box[0])
                self.assertLessEqual(h, box[1])


class TestSoundCard(unittest.TestCase):
    def _mixer_with_tone(self, seconds):
        m = Mixer()
        m.start_voice(samples=make_sine(440.0, seconds))
        return m

    def test_card_owns_the_clock(self):
        m = self._mixer_with_tone(0.5)
        with rg.SoundCard(m) as card:
            self.assertFalse(m.offline)
            frames = 0
            while m.voices or m.queue._q:
                self.assertIsNone(m.pump_dt(1 / 60))      # the engine's pump: a no-op
                card.pull()
                frames += 1
                self.assertLess(frames, 120)
        self.assertTrue(m.offline)
        self.assertIn(frames, (30, 31))                   # 0.5 s, not 0.25 s
        out = card.samples()
        self.assertEqual(len(out), sum(rg.frame_samples(i, m.sample_rate) for i in range(frames)))
        self.assertGreater(np.abs(out[:735]).max(), 0.1)

    def test_lead_frames_advance_but_are_not_kept(self):
        m = self._mixer_with_tone(1.0)
        with rg.SoundCard(m) as card:
            for _ in range(10):
                card.pull(keep=False)
            card.pull()
        self.assertEqual(card.frame, 11)
        self.assertEqual(len(card.samples()), 735)

    def test_silence_is_a_copy(self):
        m = Mixer()
        with rg.SoundCard(m) as card:
            a, b = card.pull(), card.pull()
        self.assertFalse(np.shares_memory(a, b))


_PING = """\
from scena import *

init(width=160, height=90, title="ping")
Wallpaper("black")
dot = Circle(center=(80, 45), radius=30, color="blue")

def ping():
    dot.color = "red"
    play_sound("synth/coin.wav")

after(0.5, ping)
run()
"""


class _Memory:
    def __init__(self, size, fps):
        self.size, self.fps, self.frames = size, fps, []

    def frame(self, rgba):
        self.frames.append(rgba.copy())

    def finish(self, samples, rate):
        self.samples, self.rate = samples, rate
        return "memory"

    def abort(self):
        pass


class TestSync(unittest.TestCase):
    """A real program, CPU raster: the colour and the sound change together."""

    def _record(self, **kw):
        sinks = []

        def factory(size, fps):
            sinks.append(_Memory(size, fps))
            return sinks[-1]

        r = rg.record("examples/ping.py", factory, source=_PING, size=(320, 180), gpu=False,
                      progress=False, **kw)
        return r, sinks[0]

    def test_sound_starts_in_the_frame_it_is_seen(self):
        r, sink = self._record(seconds=1.0, lead=0.25)
        self.assertEqual(r["frames"], 60)
        self.assertEqual(len(sink.frames), 60)
        self.assertEqual(sink.frames[0].shape, (180, 320, 4))
        self.assertEqual(len(sink.samples), 44100)
        red = [i for i, f in enumerate(sink.frames) if f[90, 160, 0] > 200 and f[90, 160, 2] < 60]
        self.assertTrue(red, "the dot never turned red")
        loud = np.flatnonzero(np.abs(sink.samples).max(axis=1) > 1e-3)
        self.assertTrue(len(loud), "no sound in the take")
        self.assertEqual(int(loud[0]) // 735, red[0])

    def test_thirty_fps_keeps_every_sample(self):
        r, sink = self._record(seconds=0.5, fps=30)
        self.assertEqual(len(sink.frames), 15)
        self.assertEqual(len(sink.samples), 22050)


if __name__ == "__main__":
    unittest.main()
