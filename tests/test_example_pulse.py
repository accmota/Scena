"""
The claims of ``examples/pulse.py``, played headless.

The example says: the song plays and the shapes listen to it (the bars of
the mandala follow their band of sound, the heart's triangles breathe with
the bass); each kick is a beat, never two within 0.3 s; each beat lights the
next of 16 steps; a ring flies out of the heart and the History keeps the
last few; after 28 beats the video cuts to the next scene (Mandala, Runners,
Bloom, and round again); the neon lights leap forward on each beat; keys 1
to 3 jump to a scene; M listens to the microphone and back, and a microphone
that hears nothing for a whole second is no microphone: the video goes back
to the music and the HUD says so.

Headless the offline mixer plays the song (``tick_audio`` pumps it with the
frame's dt), so ``audio.spectrum`` and the beats are the real ones. The
microphone is a ``miniaudio`` NULL capture device (put in the example's
namespace for ``Microphone``): it never opens the machine's input, hears
silence, and a test feeds it a tone by hand (``Microphone._ingest``, as
``test_audio_level_source`` does).

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``audio.spectrum`` bins, ``amp_db``, ``@when`` /
``@on_change`` on an ``st`` cell, ``History`` eviction, ``change_act`` from a
handler, the mic's silent fallback) while it still builds and runs:
``test_scripts_run`` plays only its first 30 frames, before the first beat.

Run:

    python tests/run_tiers.py focused test_example_pulse
"""
from __future__ import annotations

import math
import os
import sys
import unittest
import warnings

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import run_registry  # noqa: E402
from program_support import ProgramRun  # noqa: E402

import miniaudio  # noqa: E402
import scena  # noqa: E402
from scena import clock  # noqa: E402
from scena.act import get_act_manager  # noqa: E402
from scena.audio_capture import SAMPLE_RATE, Microphone  # noqa: E402

PATH = "examples/pulse.py"
SECOND = 60
IGNORED = (DeprecationWarning, PendingDeprecationWarning, ResourceWarning)
TITLES = ["I  MANDALA", "II  RUNNERS", "III  BLOOM"]


def live(kind):
    return [o for o in run_registry().live.values() if isinstance(o, kind)]


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


def hud(run) -> str:
    texts = [t for t in live(scena.Text) if "listening to the" in t.text]
    assert len(texts) == 1, texts
    return texts[0].text


def null_mic():
    """A capture device that hears nothing and never opens the real input."""
    return Microphone(backends=[miniaudio.Backend.NULL])


def scene(run) -> str:
    return type(get_act_manager().current).__name__


class TestPulseSong(unittest.TestCase):
    """Two whole rounds of the three scenes (~113 s of song, ~6 s headless):
    a scene's leftovers (a hidden shape never destroyed, a tween that runs
    on) show up as a growing count or a warning only on its next visit."""

    @classmethod
    def setUpClass(cls):
        cls.enters = []         # (number, title, st.beats, clock.time, live count)
        cls.beat_times = []
        cls.failures = []
        cls.max_rings = 0
        cls.lit_steps = 0
        cls.bars_checked = 0
        cls.hearts_checked = 0
        cls.run_by_scene = {}   # Runners: st.run at its first and last frame
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                cls.play(run)
        cls.warnings = [str(w.message) for w in caught if not issubclass(w.category, IGNORED)]

    @classmethod
    def play(cls, run):
        ns = run.ns
        st = ns["st"]
        enter = ns["enter"]

        def watched_enter(number, title):
            # the last scene is gone, the new one not built yet
            cls.enters.append((number, title, st.beats, clock.time, len(run_registry().live)))
            enter(number, title)

        ns["enter"] = watched_enter
        # run(Mandala) set up the first scene before the program returned
        cls.enters.append((st.scene, st.title, st.beats, clock.time, None))
        beats = st.beats
        for frame in range(130 * SECOND):
            run.step(1)
            if len(cls.enters) == 7 and clock.time > cls.enters[-1][3] + 1:
                return          # the third Mandala has begun
            if st.beats != beats:
                beats = st.beats
                cls.beat_times.append(clock.time)
            act = get_act_manager().current
            name = type(act).__name__
            if name == "Mandala":
                cls.max_rings = max(cls.max_rings, len(act.rings))
                if frame % 97 == 50:
                    cls.check_mandala(ns, st)
            elif name == "Runners":
                first, _last = cls.run_by_scene.get("Runners", (st.run, None))
                cls.run_by_scene["Runners"] = (first, st.run)
            if st.beats == 20:
                cls.lit_steps = sum(1 for c in ns["steps"] if c.radius > 2)

    @classmethod
    def check_mandala(cls, ns, st):
        """Each bar is as long as its band is loud now; the heart's two
        triangles are as big as the bass."""
        hear = ns["hear"]
        for line in live(scena.Line):
            # the bar's place round the ring says which band it plays
            angle = math.degrees(math.atan2(line.p1.y - 400, line.p1.x - 640)) % 360
            i = round((angle - 90) % 360 / (360 / 64) - 0.5) % 64
            k = i % 16
            if i // 16 % 2:
                k = 15 - k
            want = 12 + 320 * hear(1 + 2 * k)
            if abs(line.length - want) > 1e-6:
                cls.failures.append(f"bar {i}: length {line.length}, its band says {want}")
            cls.bars_checked += 1
        for tri in live(scena.Triangle):
            cls.hearts_checked += 1
            if abs(tri.radius - (50 + 120 * st.bass)) > 1e-6:
                cls.failures.append(f"a heart triangle at {tri.radius}, the bass says {st.bass}")

    def test_plays_a_whole_round_without_a_warning(self):
        self.assertEqual(self.warnings, [])
        self.assertEqual(self.failures, [])
        self.assertGreater(self.bars_checked, 64 * 5, "vacuous: no bars checked")
        self.assertGreater(self.hearts_checked, 2 * 5, "vacuous: no heart checked")

    def test_every_28_beats_the_video_cuts_to_the_next_scene(self):
        numbers = [e[0] for e in self.enters]
        self.assertEqual(numbers, [0, 1, 2, 0, 1, 2, 0], "the scenes' order, and round again")
        self.assertEqual([e[1] for e in self.enters], TITLES * 2 + TITLES[:1])
        beats = [e[2] for e in self.enters]
        self.assertEqual([b - a for a, b in zip(beats, beats[1:])], [28] * 6)
        times = [e[3] for e in self.enters]
        for a, b in zip(times, times[1:]):
            # "after 28 beats (about 20 seconds)"
            self.assertTrue(12 < b - a < 30, f"a scene lasted {b - a:.1f} s")

    def test_nothing_piles_up_from_round_to_round(self):
        counts = {}
        for number, _title, _beats, _t, count in self.enters[1:]:
            counts.setdefault(number, []).append(count)
        self.assertEqual(sorted(counts), [0, 1, 2])
        for number, seen in counts.items():
            self.assertEqual(len(set(seen)), 1, f"{TITLES[number]}: live objects {seen}")

    def test_a_kick_never_counts_twice(self):
        self.assertGreater(len(self.beat_times), 160)
        gaps = [b - a for a, b in zip(self.beat_times, self.beat_times[1:])]
        self.assertGreaterEqual(min(gaps), 0.3 - 1e-9)

    def test_each_beat_lights_the_next_step(self):
        self.assertEqual(self.lit_steps, 16, "the strip does not keep the last 16 kicks")

    def test_the_heart_keeps_the_last_rings(self):
        self.assertEqual(self.max_rings, 6)

    def test_the_lights_run_and_leap_on_the_beat(self):
        first, last = self.run_by_scene["Runners"]
        # 28 leaps of 0.06, and the bass sets the pace in between
        self.assertGreater(last - first, 28 * 0.06)


class TestPulseControls(unittest.TestCase):
    def test_keys_jump_to_a_scene(self):
        with ProgramRun(PATH, seed=1) as run:
            st = run.ns["st"]
            run.step(SECOND)
            for key, number, act in (("3", 2, "Flower"), ("1", 0, "Mandala"), ("2", 1, "Runners")):
                tap(run, key)
                self.assertEqual(scene(run), act, key)
                self.assertEqual(st.scene, number, key)
                self.assertEqual(st.title, TITLES[number], key)
                self.assertTrue(hud(run).startswith(TITLES[number]), hud(run))

    def test_m_with_no_microphone_falls_back_to_the_music(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st = ns["st"]
                ns["Microphone"] = null_mic
                run.step(SECOND)
                self.assertIn("listening to the music ", hud(run))
                tap(run, "M")
                try:
                    mic = st.mic
                    self.assertIs(st.ear, mic)
                    self.assertEqual(st.gain, ns["MIC_GAIN"])
                    self.assertIn("listening to the microphone", hud(run))
                    opened = st.mic_opened
                    while st.source == "microphone" and clock.time < opened + 3:
                        run.step(1)
                    # a whole second of exact silence, not less
                    self.assertGreater(clock.time, opened + 1)
                    self.assertLess(clock.time, opened + 1.1)
                    self.assertEqual(st.source, "music (no microphone found)")
                    self.assertIs(st.ear, scena.audio)
                    self.assertEqual(st.gain, 1)
                    self.assertIn("listening to the music (no microphone found)", hud(run))
                    # M again tries the same microphone, and M once more is the music
                    tap(run, "M")
                    self.assertIs(st.ear, mic)
                    tap(run, "M")
                    self.assertEqual(st.source, "music")
                    self.assertIs(st.ear, scena.audio)
                finally:
                    if st.mic is not None:
                        st.mic.close()
        self.assertEqual([str(w.message) for w in caught
                          if not issubclass(w.category, IGNORED)], [])

    def test_the_room_drives_the_picture(self):
        """Low tone bursts into the mic: the bass follows them (not the
        song, which still plays) and each burst is a beat."""
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            ns["Microphone"] = null_mic
            run.step(SECOND)
            tap(run, "M")
            try:
                mic = st.mic
                beats = st.beats
                n = 0
                on_bass, off_bass = [], []
                block = int(SAMPLE_RATE / SECOND)
                for frame in range(4 * SECOND):
                    on = (frame // 30) % 2 == 0      # half a second on, half off
                    t = (np.arange(block) + n) / SAMPLE_RATE
                    n += block
                    tone = (0.5 * on * np.sin(2 * np.pi * 80 * t)).astype(np.float32)
                    mic._ingest(np.stack([tone, tone], 1).tobytes())
                    run.step(1)
                    phase = frame % 30
                    if on and phase > 10:
                        on_bass.append(st.bass)
                    elif not on and phase > 20:
                        off_bass.append(st.bass)
                self.assertEqual(st.source, "microphone", "a mic that hears the room fell back")
                self.assertGreater(min(on_bass), 0.3, "the bass does not follow the mic")
                self.assertLess(max(off_bass), 0.05, "the picture still hears the song")
                self.assertGreaterEqual(st.beats - beats, 4, "a burst is not a beat")
            finally:
                st.mic.close()


if __name__ == "__main__":
    unittest.main()
