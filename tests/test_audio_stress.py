"""Audio under stress: broken files, files that change, voices that fail, churn.

Contract (Sound Design, "Failure contract"): whatever the files and however
the game uses them, a running game sees no exception from audio (only the
documented guards on bad arguments), every finite sound Handle ends, one
broken voice never silences the others, and nothing leaks.

Bug classes (Testing Design, "Audio stress"; campaign 2026-10-27):

- **An exception on the audio thread.** The device callback had no guard: a
  voice that raised (a looping stream whose file was deleted, an effect knob
  set to ``None``) stopped miniaudio's callback for the rest of the run, so no
  sound played or ended again and ``on_done`` / ``await`` hung (AU1, AU2,
  AU11). Offline the same exception was swallowed every frame (AU6).
- **A file that changes under the game.** A streamed ``Sound`` whose file
  vanished raised ``FileNotFoundError`` from ``play_sound`` (AU3).
- **A stream read past miniaudio's buffer.** More than 16384 frames in one
  read ended the stream at once: ``pitch`` above ~9, a 2 s hitch (AU4).
- **A file named for another format.** An Ogg saved as ``.wav`` was silence
  (AU10).

    python tests/run_tiers.py focused test_audio_stress
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import unittest
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.audio_stress_support import (
    PLAYS,
    SILENT_NO_WARNING,
    audio_census,
    bad_assets,
    copy_media,
    frames,
    live_mixer,
    miniaudio_or_none,
    open_fds,
    wait_frames,
    write_wav,
)
from tests.media_support import media

from scena import Sound, clock, play_sound
from scena.audio_effects import AudioEffect, Echo, LowPass
from scena.audio_mixer import (
    BufferSource,
    FrameSource,
    Mixer,
    Voice,
    get_mixer,
    make_sine,
    render,
)
from scena.process import clear_author_error, last_author_error, reset_process_scheduler


class _Raises(FrameSource):
    """A source that plays silence, then raises on its ``at``-th pull."""

    path = "broken_source.wav"

    def __init__(self, at: int = 2, exc=RuntimeError("decoder went away")):
        self.n = 0
        self.at = at
        self.exc = exc

    def remaining_seconds(self, pitch, sample_rate=44100):
        return 1.0

    def pull(self, n_frames, pitch):
        self.n += 1
        if self.n >= self.at:
            raise self.exc
        return np.zeros((int(n_frames), 2), dtype=np.float32), None


class AudioCase(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clear_author_error()
        self.tmp = tempfile.mkdtemp(prefix="scena_audio_stress_")
        self.addCleanup(self._rm_tmp)

    def tearDown(self):
        reset_process_scheduler()
        clear_author_error()

    def _rm_tmp(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def warnings_of(self, fn):
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            out = fn()
        return out, [str(w.message) for w in seen if "SCENA WARNING" in str(w.message)]


class TestBadAssets(AudioCase):
    """Group A: every kind of file, through every way of playing it."""

    def setUp(self):
        super().setUp()
        if miniaudio_or_none() is None:
            self.skipTest("no miniaudio: every file is the missing-file silence")
        self.assets = bad_assets(self.tmp)

    def _uses(self, path):
        return [
            ("play_sound(path)", lambda **k: play_sound(path, **k)),
            ("Sound(stream=True)", lambda **k: play_sound(Sound(path, stream=True), **k)),
            ("Sound(stream=False)", lambda **k: play_sound(Sound(path, stream=False), **k)),
            ("loops=2", lambda **k: play_sound(path, loops=2, **k)),
            ("bake", lambda **k: play_sound(Sound(path).bake(LowPass(), transpose=2), **k)),
        ]

    def test_no_kind_raises_and_every_handle_ends(self):
        for kind, path in self.assets.items():
            for use, start in self._uses(path):
                with self.subTest(kind=kind, use=use):
                    reset_process_scheduler()
                    done = []
                    h, _ = self.warnings_of(lambda: start(on_done=lambda: done.append(1)))
                    frames(int(60 * 2.5))       # longest: 2 laps of the 1 s silence
                    self.assertTrue(h.done, f"{kind} via {use} never ended")
                    self.assertEqual(done, [1])
                    self.assertEqual(get_mixer().voices, {})

    def test_a_broken_file_warns_once_and_a_good_one_never(self):
        for kind, path in self.assets.items():
            with self.subTest(kind=kind):
                reset_process_scheduler()
                _, seen = self.warnings_of(lambda: [play_sound(path) for _ in range(5)])
                if kind in PLAYS or kind in SILENT_NO_WARNING:
                    self.assertEqual(seen, [])
                else:
                    self.assertEqual(len(seen), 1, seen)
                    self.assertIn(os.path.basename(path), seen[0])

    def test_a_file_that_holds_sound_is_heard(self):
        for kind in sorted(PLAYS):
            with self.subTest(kind=kind):
                reset_process_scheduler()
                s = Sound(self.assets[kind])
                self.assertGreater(float(np.abs(s._samples).max()), 0.05, f"{kind} decoded to silence")

    def test_an_ogg_saved_as_wav_plays(self):
        """AU10: the decoder was picked by the extension only."""
        s, seen = self.warnings_of(lambda: Sound(self.assets["ogg_named.wav"]))
        self.assertEqual(seen, [])
        self.assertAlmostEqual(s.duration, Sound(media("audio", "footstep_snow_001.ogg")).duration,
                               places=2)

    def test_an_unsupported_format_says_which_formats_play(self):
        _, seen = self.warnings_of(lambda: play_sound(self.assets["aac.m4a"]))
        self.assertEqual(len(seen), 1)
        self.assertIn("WAV, FLAC, Ogg Vorbis and MP3", seen[0])


class TestVoiceFaults(AudioCase):
    """Group C, offline: a voice that raises ends alone (AU1, AU6)."""

    def test_render_ends_the_faulty_voice_and_mixes_the_rest(self):
        good = Voice(1, BufferSource(make_sine(440, 1.0, amp=0.5)))
        bad = Voice(2, _Raises(at=1))
        voices = {1: good, 2: bad}
        faults = []
        result = render(voices, 1024, faults=faults)
        self.assertEqual(list(voices), [1])
        self.assertIn((2, 0), result.finished_ids)
        self.assertEqual([(v, label, type(e)) for v, label, e in faults],
                         [(2, "broken_source.wav", RuntimeError)])
        self.assertGreater(float(np.abs(result.block).max()), 0.1, "the good voice was not mixed")

    def test_a_raising_effect_ends_its_voice(self):
        class Bad(AudioEffect):
            def _process(self, frames, sample_rate):
                raise ValueError("effect broke")
        voices = {1: Voice(1, BufferSource(make_sine(440, 1.0)), effects=(Bad(),))}
        faults = []
        render(voices, 512, faults=faults)
        self.assertEqual(voices, {})
        self.assertEqual(type(faults[0][2]), ValueError)

    def test_a_failure_outside_the_voices_ends_them_all_and_renders_silence(self):
        from unittest import mock
        mixer = Mixer()
        a = mixer.start_voice(samples=make_sine(440, 1.0))
        b = mixer.start_voice(samples=make_sine(220, 1.0))
        with mock.patch("scena.audio_mixer.render", side_effect=RuntimeError("mix broke")):
            out = mixer.render_block(512)
        self.assertEqual(out.block.shape, (512, 2))
        self.assertEqual(float(np.abs(out.block).max()), 0.0)
        self.assertEqual(mixer.voices, {})
        self.assertEqual(sorted(mixer.take_finished()), sorted([a, b]))
        self.assertEqual(len(mixer.take_faults()), 1)
        mixer.start_voice(samples=make_sine(440, 0.1, amp=0.5))
        self.assertGreater(float(np.abs(mixer.render_block(512).block).max()), 0.1,
                           "the mixer did not play after the failure")

    def test_the_game_hears_one_warning_and_every_handle_ends(self):
        from unittest import mock
        broken = Sound._from_pcm(make_sine(220, 0.3))
        real = Sound._frame_source

        def frame_source(sound, loops):
            return _Raises(at=3) if sound is broken else real(sound, loops)
        good = play_sound(Sound._from_pcm(make_sine(440, 0.3)))
        with mock.patch.object(Sound, "_frame_source", frame_source):
            bad = play_sound(broken)
        _, seen = self.warnings_of(lambda: frames(30))
        self.assertTrue(bad.done and good.done)
        self.assertEqual(len(seen), 1, seen)
        self.assertIn("broken_source.wav", seen[0])
        self.assertIn("other sounds keep playing", seen[0])
        self.assertEqual(last_author_error()["severity"], "warning")
        later = play_sound(Sound._from_pcm(make_sine(440, 0.2)))
        frames(20)
        self.assertTrue(later.done)

    def test_a_raising_source_warns_once_however_often_it_plays(self):
        from unittest import mock
        broken = Sound._from_pcm(make_sine(220, 0.3))
        with mock.patch.object(Sound, "_frame_source", lambda sound, loops: _Raises(at=1)):
            _, seen = self.warnings_of(lambda: [(play_sound(broken), frames(2)) for _ in range(20)])
        self.assertEqual(len(seen), 1)


    def test_cutting_a_voice_whose_source_raises_ends_only_that_voice(self):
        """The de-click ramp of a cut voice pulls its source too: a raise there
        ended every voice in the block, and a crossfaded-out slot ran its
        ``on_done`` (found by the deep audio machine)."""
        bad = Voice(2, _Raises(at=1))
        good = Voice(1, BufferSource(make_sine(440, 1.0, amp=0.5)))
        voices = {1: good, 2: bad}
        result = render(voices, 1024, [("cancel", 2)])
        self.assertEqual(list(voices), [1])
        self.assertGreater(float(np.abs(result.block).max()), 0.1)

    def test_a_fault_with_no_handle_is_reported_on_the_idle_tick(self):
        """No sound Handle: the frame is idle and pumps the mixer by itself."""
        get_mixer().start_voice(source=_Raises(at=1))
        _, seen = self.warnings_of(lambda: frames(3))
        self.assertEqual(get_mixer()._faults, [])
        self.assertEqual(len(seen), 1)

    def test_a_cut_voice_whose_source_fails_during_its_ramp_goes_quietly(self):
        """It was being cut: nothing the author hears is missing, no warning."""
        from unittest import mock
        broken = Sound._from_pcm(make_sine(220, 0.3))
        with mock.patch.object(Sound, "_frame_source", lambda sound, loops: _Raises(at=1)):
            h = play_sound(broken)
        h.cancel()
        _, seen = self.warnings_of(lambda: frames(3))
        self.assertEqual((seen, get_mixer().voices), ([], {}))


class TestCrossfadeLeaving(AudioCase):
    """AU15: a fade on the handle a ``crossfade=`` replace is taking away.

    ``fade_to`` cancelled the crossfade's ramp: the replaced ``forever`` loop
    played on for good beside the new one, out of its slot (ducking the music
    during a crossfade). ``fade_out`` turned the slot's cut into an end, and
    its ``on_done`` ran (a stray "next song")."""

    def _swap(self):
        done = []
        old = play_sound(Sound._from_pcm(make_sine(440, 0.5)), loops="forever", name="music",
                         on_done=lambda: done.append(1))
        frames(5)
        new = play_sound(Sound._from_pcm(make_sine(220, 0.5)), loops="forever", name="music",
                         crossfade=0.5)
        frames(5)
        return old, new, done

    def test_fade_to_on_the_outgoing_loop_does_not_keep_it(self):
        old, new, done = self._swap()
        old.fade_to(0.8, time=0.1)
        frames(60)
        self.assertTrue(old.cancelled)
        self.assertEqual(set(get_mixer().live_voice_ids()), {new._voice_id})
        self.assertEqual(done, [])

    def test_fade_out_on_the_outgoing_loop_is_still_a_cut(self):
        old, new, done = self._swap()
        old.fade_out(0.1)
        frames(60)
        self.assertTrue(old.cancelled)
        self.assertEqual(done, [])

    def test_a_fade_on_the_incoming_loop_still_works(self):
        old, new, done = self._swap()
        new.fade_to(0.2, time=0.1)
        frames(60)
        self.assertAlmostEqual(new.volume, 0.2, places=3)


class TestEffectKnobLiveWrites(AudioCase):
    """AU11: a knob is read on the audio thread; a non-number raises at the
    author's line. Bug class: every numeric knob of every effect."""

    def _effects(self):
        out = []
        stack = list(AudioEffect.__subclasses__())
        while stack:
            cls = stack.pop()
            stack.extend(cls.__subclasses__())
            if cls.__module__ == "scena.audio_effects":
                out.append(cls)
        return out

    def test_every_knob_refuses_a_non_number_and_takes_any_number(self):
        from scena.audio_effects import _live_knobs
        effects = self._effects()
        self.assertGreaterEqual(len(effects), 6, "vacuous: effect discovery")
        for cls in effects:
            knobs = _live_knobs(cls)
            self.assertTrue(knobs, f"{cls.__name__}: no knob found")
            for knob in knobs:
                fx = cls()
                for bad in (None, "800", True, [1], lambda: 1):
                    with self.subTest(effect=cls.__name__, knob=knob, value=bad):
                        with self.assertRaises(TypeError) as ctx:
                            setattr(fx, knob, bad)
                        self.assertIn(f"{cls.__name__}.{knob}", str(ctx.exception))
                for good in (2, 0.5, np.float32(0.5), np.int64(3), float("nan"), -1.0):
                    setattr(fx, knob, good)          # range and finiteness: clamped per block
                out = fx._process(make_sine(440, 0.05), 44100)
                self.assertTrue(np.all(np.isfinite(out)))

    def test_a_live_knob_change_still_reaches_the_mix(self):
        h = play_sound(Sound._from_pcm(make_sine(440, 1.0)))
        lp = LowPass(cutoff=300)
        h.effects.add(lp)
        lp.cutoff = np.float32(5000)
        frames(2)
        self.assertEqual(float(lp.cutoff), 5000.0)
        h.cancel()


class TestStreamsUnderChange(AudioCase):
    """Group B and F: the file moves, the pitch is extreme, the frame hitches."""

    def setUp(self):
        super().setUp()
        if miniaudio_or_none() is None:
            self.skipTest("no miniaudio: nothing streams")
        self.long = write_wav(os.path.join(self.tmp, "long.wav"), 9.0, amp=0.1)

    def test_a_streamed_sound_whose_file_vanished_plays_silence(self):
        """AU3: ``play_sound(sound)`` raised FileNotFoundError."""
        s = Sound(self.long)
        self.assertTrue(s._is_stream, "vacuous: not a stream")
        os.remove(self.long)
        h, seen = self.warnings_of(lambda: play_sound(s))
        self.assertEqual(len(seen), 1)
        self.assertIn("long.wav", seen[0])
        frames(60 * 10)
        self.assertTrue(h.done)

    def test_a_looping_stream_whose_file_vanished_ends_with_a_warning(self):
        """AU2 offline: the reopen at the lap raised inside the mix."""
        h = play_sound(self.long, loops="forever", pitch=8.0)
        frames(10)
        os.remove(self.long)
        _, seen = self.warnings_of(lambda: frames(120))
        self.assertTrue(h.done or h.cancelled)
        self.assertEqual(len(seen), 1, seen)
        later = play_sound(Sound._from_pcm(make_sine(440, 0.2)))
        frames(20)
        self.assertTrue(later.done)

    def test_one_read_bigger_than_the_stream_buffer_keeps_playing(self):
        """AU4: a pull over 16384 frames ended the stream (pitch 10, a hitch)."""
        from scena.audio import StreamFileSource
        for n, pitch in ((1764, 10.0), (88200, 1.0), (44100, 4.0)):
            with self.subTest(n=n, pitch=pitch):
                src = StreamFileSource(self.long, loops=1, duration=9.0)
                out, done_at = src.pull(n, pitch)
                self.assertIsNone(done_at, "the stream ended early")
                self.assertGreater(float(np.abs(out[-100:]).max()), 0.01, "the block ends silent")
                src.close()

    def test_pitch_ten_lasts_a_tenth(self):
        h = play_sound(self.long, pitch=10.0)
        frames(30)                                  # 0.5 s of 0.9 s
        self.assertFalse(h.done)
        self.assertGreater(h.remaining, 0.2)
        frames(40)
        self.assertTrue(h.done)

    def test_a_long_hitch_does_not_end_the_music(self):
        h = play_sound(self.long)
        frames(2)
        frames(1, dt=2.0)
        self.assertFalse(h.done)
        self.assertAlmostEqual(h.remaining, 9.0 - 2.0 - 2 / 60, delta=0.2)


class TestChurn(AudioCase):
    """Group E: many sounds, fast replaces, repeated streams. Nothing leaks."""

    def test_a_thousand_sounds_in_one_frame(self):
        laser = Sound(media("audio", "laser7.ogg"))
        hs = [play_sound(laser, volume=0.01, pitch=0.5 + (i % 10) / 10) for i in range(1000)]
        frames(60 * 3)
        self.assertTrue(all(h.done for h in hs))
        census = audio_census()
        self.assertEqual((census["voices"], census["finished_pending"], census["queued"]), (0, 0, 0))

    def test_named_replaces_every_frame_leave_one_voice(self):
        music = copy_media(self.tmp, "music", "space.ogg")
        before = open_fds()
        for i in range(240):
            play_sound(music if i % 2 else media("audio", "laser7.ogg"), name="music",
                       crossfade=0.05 if i % 3 else 0)
            frames(1)
        frames(30)
        import gc
        gc.collect()
        self.assertLessEqual(len(get_mixer().voices), 2)
        if before >= 0:
            self.assertLessEqual(open_fds() - before, 3, "streams were left open")

    def test_a_stream_played_and_cancelled_many_times_closes_its_files(self):
        if miniaudio_or_none() is None:
            self.skipTest("no miniaudio")
        music = copy_media(self.tmp, "music", "space.ogg")
        before = open_fds()
        for _ in range(100):
            play_sound(music, volume=0.01).cancel()
            frames(1)
        import gc
        gc.collect()
        if before >= 0:
            self.assertLessEqual(open_fds() - before, 2)


class TestLiveDevice(AudioCase):
    """Group C and G on a real device thread (NULL backend)."""

    def test_a_raising_voice_does_not_stop_the_device(self):
        """AU1: miniaudio dropped the callback; nothing played or ended again."""
        with live_mixer() as mixer:
            good = play_sound(Sound._from_pcm(make_sine(440, 0.2)))
            mixer.start_voice(source=_Raises(at=2))
            _, seen = self.warnings_of(lambda: wait_frames(lambda: good.done))
            self.assertTrue(good.done, "the device stopped pulling")
            self.assertEqual(len(seen), 1)
            later = play_sound(Sound._from_pcm(make_sine(440, 0.1)))
            self.assertTrue(wait_frames(lambda: later.done), "no sound ends after the fault")

    def test_a_looping_stream_whose_file_vanished_does_not_stop_the_device(self):
        """AU2: the reopen at the lap ran on the device thread."""
        long = write_wav(os.path.join(self.tmp, "loop.wav"), 9.0, amp=0.05)
        with live_mixer():
            h = play_sound(long, loops="forever", pitch=16.0)       # a lap is ~0.56 s
            frames(5, sleep=True)
            os.remove(long)
            _, seen = self.warnings_of(lambda: wait_frames(lambda: h.done, timeout=3))
            self.assertTrue(h.done)
            self.assertEqual(len(seen), 1)
            later = play_sound(Sound._from_pcm(make_sine(440, 0.1)))
            self.assertTrue(wait_frames(lambda: later.done))

    def test_the_main_thread_hammers_handles_while_the_device_mixes(self):
        """G: every Handle verb at random, the GIL switching every microsecond."""
        files = [Sound(media("audio", "laser7.ogg")), Sound(media("audio", "explosion01.ogg"))]
        rng = random.Random(7)
        saved = sys.getswitchinterval()
        with live_mixer(buffersize_msec=5) as mixer:
            sys.setswitchinterval(1e-6)
            try:
                hs = []
                import time
                end = time.monotonic() + 1.5
                while time.monotonic() < end:
                    if rng.random() < 0.2 or not hs:
                        hs.append(play_sound(rng.choice(files), volume=0.1,
                                             name=rng.choice([None, "a", "b"]),
                                             loops=rng.choice([1, 2, "forever"])))
                    else:
                        h = rng.choice(hs)
                        op = rng.randrange(9)
                        if op == 0:
                            h.volume = rng.random()
                        elif op == 1:
                            h.pitch = rng.uniform(0.25, 4)
                        elif op == 2:
                            h.fade_to(rng.random(), time=0.05)
                        elif op == 3:
                            h.pause()
                        elif op == 4:
                            h.resume()
                        elif op == 5:
                            h.cancel()
                        elif op == 6:
                            h.spectrum(8)
                        elif op == 7:
                            h.effects.add(rng.choice([LowPass(), Echo()]))
                        else:
                            h.fade_out(0.05)
                    frames(1, dt=rng.choice([0, 1 / 240, 1 / 60, 0.2]))
                    hs = [h for h in hs if not (h.done or h.cancelled)][-40:]
            finally:
                sys.setswitchinterval(saved)
            for h in hs:
                h.cancel()
            self.assertTrue(wait_frames(lambda: not mixer.voices), "voices left after cancel")
            self.assertEqual(mixer.take_faults(), [])


if __name__ == "__main__":
    unittest.main()
