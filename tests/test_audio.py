"""Audio mixer + play_sound. Run: python -m unittest tests.test_audio -v"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.media_support import MEDIA, media
from tests.source_support import iter_files

from scena.audio_mixer import (
    SAMPLE_RATE,
    BufferSource,
    CMD_CANCEL,
    CMD_FINISH,
    CMD_SET_HELD,
    DECLICK_FRAMES,
    CMD_SET_PAN,
    CMD_SET_VOLUME,
    CommandQueue,
    Mixer,
    Voice,
    make_sine,
    make_silence,
    render,
    rms,
    soft_limit,
)


def _sine_voice(vid, amp=0.5, duration=0.05, freq=440.0, volume=1.0, pan=0.0, pitch=1.0, loops=1):
    src = BufferSource(make_sine(freq, duration, amp=amp), loops=loops)
    return Voice(vid, src, volume=volume, pan=pan, pitch=pitch)


class TestStage0Dependency(unittest.TestCase):
    def test_miniaudio_listed_and_null_backend(self):
        import miniaudio
        from pathlib import Path

        import tomllib
        root = Path(__file__).resolve().parents[1]
        # pyproject.toml is the one package definition (setup.py is gone).
        with open(root / "pyproject.toml", "rb") as f:
            deps = tomllib.load(f)["project"]["dependencies"]
        self.assertTrue(any(d.startswith("miniaudio;") for d in deps), deps)
        self.assertIn("numpy", deps)
        backends = miniaudio.get_enabled_backends()
        self.assertIn(miniaudio.Backend.NULL, backends)

        wav = Path(media("audio", "laser-big.ogg"))
        decoded = miniaudio.decode_file(
            str(wav),
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=2,
            sample_rate=44100,
        )
        self.assertGreater(decoded.num_frames, 0)
        device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=2,
            sample_rate=44100,
            backends=[miniaudio.Backend.NULL],
        )

        def gen():
            n = yield np.zeros((0, 2), dtype=np.float32)
            samples = np.asarray(decoded.samples, dtype=np.float32)
            if samples.ndim == 1:
                samples = samples.reshape(-1, decoded.nchannels)
            pos = 0
            while True:
                frames = int(n) if n else 256
                chunk = samples[pos:pos + frames]
                pos += frames
                if chunk.shape[0] < frames:
                    pad = np.zeros((frames, samples.shape[1]), dtype=np.float32)
                    if chunk.shape[0]:
                        pad[: chunk.shape[0]] = chunk
                    chunk = pad
                n = yield chunk

        g = gen()
        g.send(None)
        device.start(g)
        device.close()


class TestRenderCore(unittest.TestCase):
    def test_two_sines_sum_at_volumes(self):
        n = 512
        a = make_sine(440, n / SAMPLE_RATE, amp=0.4)
        b = make_sine(440, n / SAMPLE_RATE, amp=0.4)
        voices = {
            1: Voice(1, BufferSource(a), volume=0.5),
            2: Voice(2, BufferSource(b), volume=0.25),
        }
        result = render(voices, n)
        expected = a[:n].astype(np.float64) * 0.5 + b[:n].astype(np.float64) * 0.25
        # Below the limiter knee: identity.
        np.testing.assert_allclose(result.block, expected, atol=1e-5)

    def test_finished_on_exact_frame_count(self):
        n = 100
        samples = make_sine(440, n / SAMPLE_RATE, amp=0.3)
        self.assertEqual(samples.shape[0], n)
        voices = {1: Voice(1, BufferSource(samples), volume=1.0)}
        result = render(dict(voices), 50)
        self.assertEqual(result.finished_ids, [])
        self.assertFalse(voices[1].finished)
        result = render(voices, 50)
        self.assertEqual(len(result.finished_ids), 1)
        vid, at = result.finished_ids[0]
        self.assertEqual(vid, 1)
        self.assertEqual(at, 50)
        self.assertTrue(voices[1].finished if 1 in voices else True)

        voices = {2: Voice(2, BufferSource(samples.copy()), volume=1.0)}
        result = render(voices, 200)
        self.assertEqual(result.finished_ids[0][0], 2)
        self.assertEqual(result.finished_ids[0][1], n)
        # Past the clip: tail is silence (mixer zeros).
        self.assertLess(np.max(np.abs(result.block[n:])), 1e-6)
        self.assertGreater(np.max(np.abs(result.block[:n])), 0.05)

    def test_mid_buffer_volume_not_retroactive(self):
        n = 200
        samples = np.ones((n, 2), dtype=np.float32) * 0.2
        voices = {1: Voice(1, BufferSource(samples), volume=1.0)}
        result = render(
            voices, n,
            commands=[(CMD_SET_VOLUME, 1, 0.25, 80)],
        )
        np.testing.assert_allclose(result.block[:80], 0.2, atol=1e-6)
        np.testing.assert_allclose(result.block[80:], 0.2 * 0.25, atol=1e-6)

    def test_mid_buffer_pan_not_retroactive(self):
        n = 100
        samples = np.ones((n, 2), dtype=np.float32) * 0.5
        voices = {1: Voice(1, BufferSource(samples), pan=0.0, volume=1.0)}
        result = render(
            voices, n,
            commands=[(CMD_SET_PAN, 1, 1.0, 40)],
        )
        np.testing.assert_allclose(result.block[:40, 0], 0.5, atol=1e-6)
        np.testing.assert_allclose(result.block[:40, 1], 0.5, atol=1e-6)
        np.testing.assert_allclose(result.block[40:, 0], 0.0, atol=1e-6)
        np.testing.assert_allclose(result.block[40:, 1], 0.5, atol=1e-6)

    def test_full_scale_sum_is_soft_limited(self):
        n = 256
        a = np.ones((n, 2), dtype=np.float32)
        b = np.ones((n, 2), dtype=np.float32)
        voices = {
            1: Voice(1, BufferSource(a), volume=1.0),
            2: Voice(2, BufferSource(b), volume=1.0),
        }
        result = render(voices, n)
        peak = float(np.max(np.abs(result.block)))
        self.assertLessEqual(peak, 1.0 + 1e-6)
        self.assertGreater(peak, 0.95)
        # Must not wrap the way integer clipping would.
        self.assertTrue(np.all(np.isfinite(result.block)))

    def test_held_voice_does_not_advance_or_finish(self):
        from scena.audio_mixer import CMD_SET_HELD
        n = 200
        samples = np.ones((n, 2), dtype=np.float32) * 0.3
        voices = {1: Voice(1, BufferSource(samples), volume=1.0)}
        result = render(voices, 50)
        self.assertEqual(result.finished_ids, [])
        pos = voices[1].source.pos
        result = render(voices, 80, commands=[(CMD_SET_HELD, 1, True)])
        self.assertEqual(result.finished_ids, [])
        self.assertAlmostEqual(voices[1].source.pos, pos)
        self.assertIn(1, voices)
        self.assertTrue(voices[1].held)
        np.testing.assert_allclose(result.block, 0.0, atol=1e-6)
        result = render(voices, 200, commands=[(CMD_SET_HELD, 1, False)])
        self.assertEqual(result.finished_ids[0][0], 1)
        self.assertNotIn(1, voices)

    def test_quiet_voice_unaffected_by_limiter(self):
        n = 256
        quiet = np.full((n, 2), 0.05, dtype=np.float32)
        voices = {1: Voice(1, BufferSource(quiet), volume=1.0)}
        result = render(voices, n)
        np.testing.assert_allclose(result.block, 0.05, atol=1e-6)

    def test_command_queue_applies_once_in_order(self):
        q = CommandQueue()
        q.push((CMD_SET_VOLUME, 1, 0.5))
        q.push((CMD_SET_VOLUME, 1, 0.2))
        cmds = q.drain()
        self.assertEqual(cmds, [(CMD_SET_VOLUME, 1, 0.5), (CMD_SET_VOLUME, 1, 0.2)])
        self.assertEqual(q.drain(), [])
        samples = np.ones((64, 2), dtype=np.float32) * 0.4
        voices = {1: Voice(1, BufferSource(samples), volume=1.0)}
        result = render(voices, 32, commands=cmds)
        np.testing.assert_allclose(result.block, 0.4 * 0.2, atol=1e-6)
        self.assertAlmostEqual(voices[1].volume, 0.2)
        self.assertFalse(voices[1].finished)

    def test_soft_limit_helper_caps_and_is_identity_below_knee(self):
        x = np.array([[0.2, -0.3], [2.0, -3.0]], dtype=np.float32)
        y = soft_limit(x)
        np.testing.assert_allclose(y[0], [0.2, -0.3], atol=1e-6)
        self.assertLessEqual(float(np.max(np.abs(y))), 1.0)

    def test_pitch_two_consumes_twice_as_fast(self):
        n = 200
        samples = make_sine(440, n / SAMPLE_RATE, amp=0.4)
        voices = {1: Voice(1, BufferSource(samples), pitch=2.0)}
        result = render(voices, n)
        self.assertEqual(result.finished_ids[0][1], n // 2)
        self.assertLess(np.max(np.abs(result.block[n // 2 + 2:])), 1e-5)

    def test_mixer_render_block_drains_queue(self):
        mixer = Mixer()
        samples = np.ones((64, 2), dtype=np.float32) * 0.3
        vid = mixer.start_voice(samples=samples, volume=1.0)
        mixer.set_volume(vid, 0.5)
        result = mixer.render_block(64)
        np.testing.assert_allclose(result.block, 0.3 * 0.5, atol=1e-6)
        self.assertEqual(mixer.take_finished(), [vid])
        self.assertEqual(mixer.take_finished(), [])


class TestDeclick(unittest.TestCase):
    """A cut ramps to silence over DECLICK_FRAMES instead of clicking
    (Sound Design — Mixer). Every cut path (h.cancel, loops and named slots
    on an owner's end, name= replace) goes through CMD_CANCEL."""

    AMP = 0.5
    FREQ = 440.0

    def _voices(self):
        return {1: _sine_voice(1, amp=self.AMP, duration=1.0, freq=self.FREQ)}

    def _loud_frame(self):
        # A cut frame where the sine is near its peak: an instant cut there
        # jumps by ~AMP; the ramp must not.
        n = np.arange(200, 2000)
        vals = np.abs(np.sin(2 * np.pi * self.FREQ * n / SAMPLE_RATE))
        return int(n[int(np.argmax(vals > 0.95))])

    def test_cancel_mid_block_ramps_to_silence(self):
        at = self._loud_frame()
        voices = self._voices()
        n = at + DECLICK_FRAMES + 300
        result = render(voices, n, commands=[(CMD_CANCEL, 1, at)])
        left = result.block[:, 0].astype(np.float64)
        max_sine_step = 2 * np.pi * self.FREQ / SAMPLE_RATE * self.AMP
        steps = np.abs(np.diff(left[at - 1:at + DECLICK_FRAMES + 1]))
        self.assertLess(float(np.max(steps)), max_sine_step * 1.5,
                        "the cut must not jump (click)")
        self.assertLess(float(np.max(np.abs(left[at + DECLICK_FRAMES:]))), 1e-6)
        self.assertGreater(float(np.max(np.abs(left[at:at + 20]))), 0.3,
                           "the ramp starts from the playing level")
        self.assertEqual(result.finished_ids, [(1, at)], "reported once, at the cut")
        self.assertEqual(voices, {}, "gone once the ramp ends")

    def test_ramp_spanning_blocks_is_not_a_live_voice(self):
        mixer = Mixer()
        vid = mixer.start_voice(samples=make_sine(440, 1.0, amp=0.5), volume=1.0)
        mixer.render_block(64)
        mixer.cancel_voice(vid)
        mixer.render_block(DECLICK_FRAMES // 2)
        self.assertIn(vid, mixer.voices, "still ramping")
        self.assertNotIn(vid, mixer.live_voice_ids())
        self.assertEqual(mixer.take_finished(), [vid])
        mixer.cancel_voice(vid)  # a second cut mid-ramp is a no-op
        mixer.render_block(DECLICK_FRAMES)
        self.assertNotIn(vid, mixer.voices)
        self.assertEqual(mixer.take_finished(), [], "finished only once")

    def test_silent_cuts_pop_at_once(self):
        cases = {
            "held": [(CMD_SET_HELD, 1, True), (CMD_CANCEL, 1)],
            "finish": [(CMD_FINISH, 1)],
        }
        for name, cmds in cases.items():
            with self.subTest(case=name):
                voices = self._voices()
                render(voices, 64, commands=cmds)
                self.assertEqual(voices, {})
        with self.subTest(case="zero-frame render"):
            voices = self._voices()
            render(voices, 0, commands=[(CMD_CANCEL, 1)])
            self.assertEqual(voices, {})

    def test_muted_voice_pops_at_once(self):
        voices = {1: _sine_voice(1, amp=self.AMP, duration=1.0, volume=0.0)}
        render(voices, 64, commands=[(CMD_CANCEL, 1)])
        self.assertEqual(voices, {})


def _fake_miniaudio():
    """A ``miniaudio`` whose playback device opens no hardware."""
    import types

    fake = types.ModuleType("miniaudio")

    class SampleFormat:
        FLOAT32 = 1

    class _Device:
        def __init__(self, **kwargs):
            pass

        def start(self, gen):
            self._gen = gen

        def close(self):
            pass

    fake.SampleFormat = SampleFormat
    fake.PlaybackDevice = _Device
    return fake


class TestAudioThreadGil(unittest.TestCase):
    """The device callback mixes in Python: it must win the GIL from a busy main thread.

    The mix gives the GIL up inside its numpy calls. With the default 5 ms
    switch interval (a 15.6 ms tick on Windows) every take-back waited for the
    main thread, and at ``canvas.framerate = "max"`` about half the 40 ms
    blocks missed the device (``examples/pendulums.py`` stuttered).
    """

    def setUp(self):
        from unittest.mock import patch

        saved = sys.getswitchinterval()
        self.addCleanup(sys.setswitchinterval, saved)
        sys.setswitchinterval(0.005)
        modules = patch.dict(sys.modules, {"miniaudio": _fake_miniaudio()})
        modules.start()
        self.addCleanup(modules.stop)
        self.mixer = Mixer()
        self.addCleanup(self.mixer.stop_device)

    def test_device_lowers_the_switch_interval_and_stop_restores_it(self):
        from scena.audio_mixer import AUDIO_SWITCH_INTERVAL

        self.mixer.start_device()
        self.assertAlmostEqual(sys.getswitchinterval(), AUDIO_SWITCH_INTERVAL)
        self.mixer.stop_device()
        self.assertAlmostEqual(sys.getswitchinterval(), 0.005)

    def test_a_lower_interval_already_set_is_kept(self):
        sys.setswitchinterval(0.0001)
        lower = sys.getswitchinterval()     # stored in microseconds, so 9.9e-05
        self.mixer.start_device()
        self.assertEqual(sys.getswitchinterval(), lower)
        self.mixer.stop_device()
        self.assertEqual(sys.getswitchinterval(), lower)

    def test_stop_keeps_an_interval_changed_while_playing(self):
        self.mixer.start_device()
        sys.setswitchinterval(0.002)
        self.mixer.stop_device()
        self.assertAlmostEqual(sys.getswitchinterval(), 0.002)

    def test_reset_restores_the_interval(self):
        self.mixer.start_device()
        self.mixer.reset()
        self.assertAlmostEqual(sys.getswitchinterval(), 0.005)

    def test_mix_keeps_up_with_a_busy_thread(self):
        """Pendulums' worst moment: 13 voices, a thread that never sleeps.

        Before the fix one 40 ms block took ~2.5 s of wall time on the Windows
        laptop (~3 ms alone); with it, ~7 ms. A ratio, not a bound: the Mac
        waits the 0.5 ms exactly (Windows rounds it to 0), ~590 ms a block at
        the default and ~70 ms with the fix beside this pure-Python thread,
        though real games keep every block on time there at both (WP51).
        Interleaved, so load hits both sides alike.
        """
        import threading
        import time

        mixer = self.mixer
        mixer.start_device()
        lowered = sys.getswitchinterval()   # what the device set
        for k in range(13):
            mixer.start_voice(samples=make_sine(220 + 30 * k, 5.0, amp=0.05),
                              pitch=1 + k / 20, pan=k / 13 - 0.5)
        frames = 1764                       # the 40 ms block the device asks for
        mixer.render_block(frames)          # START commands, first-touch costs
        stop = threading.Event()

        def busy():
            n = 0
            while not stop.is_set():
                n += 1

        worker = threading.Thread(target=busy, daemon=True)
        worker.start()
        intervals = (0.005, lowered)        # CPython's default, the device's
        walls = ([], [])
        try:
            for _ in range(3):
                for interval, wall in zip(intervals, walls):
                    sys.setswitchinterval(interval)
                    t0 = time.perf_counter()
                    mixer.render_block(frames)
                    wall.append(time.perf_counter() - t0)
        finally:
            sys.setswitchinterval(lowered)  # stop_device restores only its own
            stop.set()
            worker.join()
        default, fixed = (sorted(w)[1] for w in walls)
        self.assertGreater(default / max(fixed, 1e-9), 3.0,
                           f"the device's interval does not speed the mix beside a busy "
                           f"thread: {walls}")


from scena import Circle, Line, play_sound, Sound, clock
from scena.audio import SAMPLE_RATE as _SR
from scena.process import (
    clear_author_error,
    get_scheduler,
    last_author_error,
    reset_process_scheduler,
    tick_processes,
)
from scena.audio_mixer import make_sine as _sine


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


def _pcm(duration=0.4, freq=440.0, amp=0.3):
    return Sound._from_pcm(_sine(freq, duration, amp=amp))


class PlaySoundTestCase(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        clock._frame = 0
        self._owned = []
        clear_author_error()

    def tearDown(self):
        for obj in self._owned:
            try:
                if getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_process_scheduler()
        clear_author_error()

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestPlaySoundOwnership(PlaySoundTestCase):
    def test_destroyed_owner_voice_stops_when_scheduler_goes_idle(self):
        """S2: with no process work left, the idle tick skipped ``tick_audio``;
        the offline mixer never applied the cancel and the voice stayed."""
        from scena.audio_mixer import get_mixer
        c = self.track(Circle())
        # A forever loop: a finite sound would ring out on destroy.
        c.play_sound(_pcm(0.5), loops="forever")
        _frame(0.05)
        self.assertEqual(len(get_mixer().voices), 1)
        c.destroy()
        self.assertEqual(len(get_scheduler()._handles), 0)
        _frame(0.05)
        self.assertEqual(get_mixer().voices, {})

    def test_mode_scoped_cancels_on_mode_change_without_on_done(self):
        c = self.track(Circle())
        done = []

        def idle(e):
            pass

        def flying(e):
            # Forever: a finite mode sound rings out (TestSoundRingsOut).
            play_sound(_pcm(0.8), loops="forever", on_done=lambda: done.append(1))

        c.mode = flying
        h = next(iter(get_scheduler()._sound))
        self.assertEqual(h.scope, "mode")
        self.assertIs(h.owner, c)
        c.mode = idle
        self.assertTrue(h.cancelled)
        _frame(1.0)
        self.assertEqual(done, [])

    def test_entity_play_sound_survives_mode_and_dies_on_destroy(self):
        c = self.track(Circle())
        done = []

        def idle(e):
            pass

        def flying(e):
            e.play_sound(_pcm(0.4), on_done=lambda: done.append(1))

        c.mode = flying
        h = next(iter(get_scheduler()._sound))
        self.assertEqual(h.scope, "entity")
        c.mode = idle
        self.assertFalse(h.cancelled)
        _frame(0.5)
        self.assertEqual(done, [1])
        self.assertTrue(h.done)

        h2 = c.play_sound(_pcm(0.4), loops="forever")  # a finite one rings out
        c.destroy()
        self.assertTrue(h2.cancelled)

    def test_ownerless_bare_play_sound_survives_until_cancel(self):
        # Before the top level ends an ownerless sound is "game" scope; after
        # it, "act" (tests/test_act.py covers the sealed side).
        h = play_sound(_pcm(2.0))
        self.assertEqual(h.scope, "game")
        self.assertIsNone(h.owner)
        _frame(0.3)
        self.assertFalse(h.cancelled)
        self.assertFalse(h.done)
        h.cancel()
        self.assertTrue(h.cancelled)

    def test_on_done_once_on_natural_end_never_on_cancel(self):
        n = []
        h = play_sound(_pcm(0.2), on_done=lambda: n.append("ok"))
        _frame(0.1)
        self.assertEqual(n, [])
        _frame(0.2)
        self.assertEqual(n, ["ok"])
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)
        _frame(0.2)
        self.assertEqual(n, ["ok"])

    def test_then_warns_if_it_cancels_running_async_mode(self):
        c = self.track(Circle())

        async def flying(e):
            from scena import wait
            await wait(10.0)

        def landed(e):
            pass

        c.mode = flying
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            c.play_sound(_pcm(0.15), then=landed)
            _frame(0.3)
        msgs = [str(w.message) for w in caught]
        self.assertTrue(
            any("then=" in m and "cancelled a still-running async mode" in m for m in msgs),
            msgs,
        )
        self.assertIs(c.mode, landed)

    def test_named_slot_replace_cancels_previous_without_on_done(self):
        n = []
        a = play_sound(_pcm(1.0), on_done=lambda: n.append("a"), name="music")
        b = play_sound(_pcm(1.0), on_done=lambda: n.append("b"), name="music")
        self.assertTrue(a.cancelled)
        self.assertFalse(b.cancelled)
        _frame(1.2)
        self.assertEqual(n, ["b"])

    def test_loops_forever_never_on_done(self):
        n = []
        h = play_sound(_pcm(0.1), loops="forever", on_done=lambda: n.append(1))
        _frame(0.5)
        self.assertFalse(h.done)
        self.assertEqual(n, [])
        h.cancel()
        _frame(0.2)
        self.assertEqual(n, [])
        self.assertTrue(h.cancelled)

    def test_missing_file_warns_once_on_banner_and_ticks_silence(self):
        n = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            h = play_sound("no_such_file.wav", on_done=lambda: n.append(1))
            play_sound("no_such_file.wav")
        banner = last_author_error()
        self.assertIsNotNone(banner)
        self.assertEqual(banner["severity"], "warning")
        self.assertEqual(banner["where"], "play_sound")
        self.assertIn("no_such_file.wav", banner["message"])
        self.assertNotIn("SCENA ERROR", banner["message"])
        warn_msgs = [str(w.message) for w in caught if "SCENA WARNING" in str(w.message)]
        self.assertEqual(len(warn_msgs), 1, warn_msgs)
        _frame(1.2)
        self.assertEqual(n, [1])
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)

    def test_corrupt_file_warns_once_and_plays_silence(self):
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "scena_corrupt_sound.wav")
        with open(path, "wb") as f:
            f.write(b"not a wav at all")
        n = []
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            h = play_sound(path, on_done=lambda: n.append(1))
        banner = last_author_error()
        self.assertIsNotNone(banner)
        self.assertEqual(banner["severity"], "warning")
        _frame(1.2)
        self.assertEqual(n, [1])
        self.assertTrue(h.done)

    def test_pitch_two_finishes_in_half_the_frames(self):
        samples = _sine(440, 0.2, amp=0.4)
        n_frames = samples.shape[0]
        h = play_sound(Sound._from_pcm(samples), pitch=2.0)
        _frame(0.09)
        self.assertFalse(h.done)
        _frame(0.03)
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)
        self.assertAlmostEqual(n_frames / _SR / 2.0, 0.1, places=3)

    def test_media_audio_every_format_decodes(self):
        # Every bundled sound effect decodes and plays. audio/ is OGG (and one
        # MP3) since 2026-10; synth/ keeps the WAVs. No bundled file is FLAC:
        # test_flac_decodes writes one.
        import miniaudio
        paths = [p for folder in ("audio", "synth")
                 for p in iter_files(os.path.join(MEDIA, folder), ".wav", ".ogg", ".flac", ".mp3")]
        for ext in (".wav", ".ogg", ".mp3"):
            self.assertTrue(any(p.endswith(ext) for p in paths), ext)
        for path in paths:
            name = os.path.basename(path)
            decoded = miniaudio.decode_file(
                path,
                output_format=miniaudio.SampleFormat.FLOAT32,
                nchannels=2,
                sample_rate=44100,
            )
            self.assertGreater(decoded.num_frames, 0, name)
            h = play_sound(path)
            self.assertFalse(h.cancelled)
            h.cancel()

    def test_flac_decodes(self):
        # FLAC is one of the formats Scena names (_FORMATS) but no bundled
        # file is one any more; soundfile writes it (skipped where absent).
        try:
            import soundfile
        except ImportError:
            self.skipTest("soundfile not installed (pip install soundfile)")
        import tempfile
        samples = _sine(440, 0.2, amp=0.4)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tone.flac")
            soundfile.write(path, samples, _SR, format="FLAC")
            sound = Sound(path)
            self.assertAlmostEqual(sound.duration, 0.2, places=3)
            h = play_sound(sound)
            self.assertFalse(h.cancelled)
            h.cancel()


class TestSoundRingsOut(PlaySoundTestCase):
    """When the owner ends implicitly (destroy, mode leave), a sound that ends
    by itself finishes; one that would play forever is cut. Callbacks never
    outlive the owner. Explicit cuts (cancel_process, h.cancel) cut all.
    Sound Design — When the owner ends; Act Design decision 12."""

    RINGS = "rings out"
    CUT = "cut"

    # state -> fate on an implicit ending.
    STATES = {
        "finite": RINGS,
        "loops=3": RINGS,
        "forever": CUT,
        "named": CUT,
        "paused": CUT,
        "fading-out loop": RINGS,
        "fade_to loop": CUT,
        "fade_to(0) finite": RINGS,
        "on_done": RINGS,
        "then=": RINGS,
        "named fading out": RINGS,
    }
    # "host destroy": the sound is on a part (``line.p1``); the part outlives
    # the host's destroy as a readable value, but its work ends with it.
    IMPLICIT = ("destroy", "mode leave", "host destroy")
    EXPLICIT = ("cancel_process", "h.cancel()")

    def _start(self, state, *, entity, calls, target):
        """Start one sound in ``state``; ``entity`` picks e.play_sound vs bare."""
        def later(e):
            calls.append("then")

        play = entity.play_sound if target == "entity" else play_sound
        kw = {}
        clip = _pcm(0.4)
        if state == "loops=3":
            clip, kw = _pcm(0.2), {"loops": 3}
        elif state in ("forever", "fading-out loop", "fade_to loop"):
            clip, kw = _pcm(0.2), {"loops": "forever"}
        elif state in ("named", "named fading out"):
            kw = {"name": "sfx"}
        elif state == "on_done":
            kw = {"on_done": lambda: calls.append("on_done")}
        elif state == "then=":
            kw = {"then": later}
        h = play(clip, **kw)
        if state == "paused":
            h.pause()
        elif state in ("fading-out loop", "named fading out"):
            h.fade_out(0.3)
        elif state == "fade_to loop":
            h.fade_to(0.2, time=5.0)
        elif state == "fade_to(0) finite":
            h.fade_to(0.0, time=0.1)
        return h

    def _run(self, ending, state):
        from scena.audio_mixer import get_mixer

        host = None
        if ending == "host destroy":
            host = self.track(Line())
            c = host.p1
        else:
            c = self.track(Circle())
        calls = []
        made = []

        def idle(e):
            pass

        if ending == "mode leave":
            def singing(e):
                made.append(self._start(state, entity=e, calls=calls, target="bare"))
            c.mode = singing
        else:
            c.mode = idle
            made.append(self._start(state, entity=c, calls=calls, target="entity"))
        h = made[0]
        _frame(0.02)
        if ending == "destroy":
            c.destroy()
        elif ending == "host destroy":
            host.destroy()
        elif ending == "mode leave":
            c.mode = idle
        elif ending == "cancel_process":
            c.cancel_process()
        else:
            h.cancel()
        return c, h, calls, get_mixer()

    def _assert_rings_out(self, c, h, calls, mixer):
        self.assertFalse(h.cancelled)
        self.assertIsNone(h.owner, "a released sound holds no owner")
        self.assertEqual(h.scope, "game")
        self.assertIsNone(h.name)
        self.assertNotIn(h, get_scheduler()._named.values())
        _frame(0.02)
        self.assertIn(h._voice_id, mixer.live_voice_ids(), "still playing")
        for _ in range(12):
            _frame(0.1)
        self.assertTrue(h.done, "it ends by itself")
        self.assertFalse(h.cancelled)
        self.assertNotIn(h._voice_id, mixer.voices)
        self.assertEqual(calls, [], "callbacks never outlive the owner")
        # then= never entered its mode (a dead host's teardown clears a
        # part's mode to None; that is not the then= target either).
        self.assertNotEqual(getattr(c.mode, "__name__", None), "later")

    def _assert_cut(self, h, calls, mixer):
        self.assertTrue(h.cancelled)
        _frame(0.05)
        self.assertNotIn(h._voice_id, mixer.voices)
        self.assertEqual(calls, [])

    def test_fate_matrix_implicit_endings(self):
        for ending in self.IMPLICIT:
            for state, fate in self.STATES.items():
                with self.subTest(ending=ending, state=state, fate=fate):
                    c, h, calls, mixer = self._run(ending, state)
                    if fate == self.RINGS:
                        self._assert_rings_out(c, h, calls, mixer)
                    else:
                        self._assert_cut(h, calls, mixer)
                    reset_process_scheduler()

    def test_fate_matrix_explicit_endings_always_cut(self):
        for ending in self.EXPLICIT:
            for state in self.STATES:
                with self.subTest(ending=ending, state=state):
                    _c, h, calls, mixer = self._run(ending, state)
                    self._assert_cut(h, calls, mixer)
                    reset_process_scheduler()

    def test_part_work_ends_with_its_host(self):
        # Found while adding the "host destroy" ending: a part's timers,
        # tweens and loops kept running after its host was destroyed.
        host = self.track(Line())
        p = host.p1
        fired = []
        timer = p.after(0.2, lambda: fired.append("after"))
        rep = p.every(0.1, lambda: fired.append("every"))
        loop = p.play_sound(_pcm(0.2), loops="forever")
        host.destroy()
        self.assertFalse(p.is_alive, "a part leaves with its host")
        float(p.x)  # still readable, like any destroyed actor
        for h in (timer, rep, loop):
            with self.subTest(kind=h.kind):
                self.assertTrue(h.cancelled)
        _frame(0.5)
        self.assertEqual(fired, [])
        self.assertEqual(get_scheduler()._by_owner.get(id(p)), None)

    def test_entity_sound_survives_mode_leave_untouched(self):
        # Mode leave only ends mode-scoped work; an entity sound keeps its owner.
        c = self.track(Circle())

        def idle(e):
            pass

        def flying(e):
            pass

        c.mode = flying
        h = c.play_sound(_pcm(0.4), loops="forever")
        c.mode = idle
        self.assertIs(h.owner, c)
        self.assertEqual(h.scope, "entity")
        self.assertFalse(h.cancelled)

    def test_destroyed_owner_is_collectable_while_its_sound_rings_out(self):
        import gc
        import weakref
        c = Circle()
        h = c.play_sound(_pcm(1.0))
        r = weakref.ref(c)
        c.destroy()
        del c
        gc.collect()
        self.assertIsNone(r(), "the released sound must not pin its dead owner")
        self.assertFalse(h.done)

    def test_fade_out_in_on_destroy_lets_a_loop_fade_across_the_end(self):
        from scena.audio_mixer import get_mixer

        class Boss(Circle):
            def on_destroy(self):
                self.music.fade_out(0.3)

        b = self.track(Boss())
        b.music = b.play_sound(_pcm(0.2), loops="forever")
        h = b.music
        _frame(0.05)
        b.destroy()
        self.assertFalse(h.cancelled)
        _frame(0.15)
        self.assertFalse(h.done)
        self.assertGreater(h.volume, 0.0)
        self.assertLess(h.volume, 1.0)
        _frame(0.2)
        self.assertTrue(h.done)
        _frame(0.05)
        self.assertNotIn(h._voice_id, get_mixer().voices)

    def test_released_named_slot_leaves_no_stale_key(self):
        c = self.track(Circle())
        h = c.play_sound(_pcm(1.0), name="music", loops="forever")
        h.fade_out(0.5)
        key = (id(c), "music")
        self.assertIs(get_scheduler()._named.get(key), h)
        c.destroy()
        self.assertNotIn(key, get_scheduler()._named,
                         "a stale key would let an object reusing id(c) cut it")
        self.assertIsNone(h.name)
        self.assertFalse(h.cancelled)


class TestFades(PlaySoundTestCase):
    def test_fade_in_linear_then_holds(self):
        h = play_sound(_pcm(2.0), volume=1.0, fade_in=0.5)
        self.assertAlmostEqual(h.volume, 0.0)
        _frame(0.25)
        self.assertAlmostEqual(h.volume, 0.5, places=2)
        _frame(0.25)
        self.assertAlmostEqual(h.volume, 1.0, places=2)
        _frame(0.2)
        self.assertAlmostEqual(h.volume, 1.0, places=2)
        self.assertFalse(h.done)

    def test_fade_retargets_in_flight_without_warning(self):
        # Bug class of showcase A9: a timed verb that starts a tween on a busy
        # key without preempting it warned from the scheduler's fallback. A
        # new fade on the same voice is last-wins.
        h = play_sound(_pcm(4.0), volume=1.0)
        first = h.fade_to(0.0, time=2.0)
        _frame(0.2)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            second = h.fade_to(1.0, time=0.5)
            _frame(0.1)
            out = h.fade_out(time=0.5)
        self.assertTrue(first.cancelled)
        self.assertTrue(second.cancelled)
        _frame(0.6)
        self.assertTrue(out.done)

    def test_pause_holds_clip_without_on_done(self):
        from scena.audio_mixer import get_mixer
        n = []
        h = play_sound(_pcm(0.4), on_done=lambda: n.append(1))
        _frame(0.05)
        self.assertIs(h.pause(), h)
        self.assertTrue(h.paused)
        _frame(0.5)
        self.assertEqual(n, [])
        self.assertFalse(h.done)
        voice = get_mixer().voices.get(h._voice_id)
        self.assertIsNotNone(voice)
        self.assertTrue(voice.held)
        self.assertIs(h.pause(), h)  # idempotent — still one hold
        h.resume()
        self.assertFalse(h.paused)
        _frame(0.5)
        self.assertEqual(n, [1])
        self.assertTrue(h.done)

    def test_cancel_while_paused_stops_voice(self):
        from scena.audio_mixer import get_mixer
        n = []
        h = play_sound(_pcm(1.0), on_done=lambda: n.append(1))
        _frame(0.05)
        h.pause()
        vid = h._voice_id
        h.cancel()
        self.assertTrue(h.cancelled)
        self.assertFalse(h.paused)
        get_mixer().render_block(256)
        self.assertNotIn(vid, get_mixer().voices)
        _frame(0.5)
        self.assertEqual(n, [])

    def test_fade_out_reaches_zero_and_fires_on_done(self):
        n = []
        h = play_sound(_pcm(2.0), on_done=lambda: n.append(1))
        h.fade_out(0.3)
        _frame(0.2)
        self.assertFalse(h.done)
        self.assertGreater(h.volume, 0.0)
        _frame(0.15)
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)
        self.assertEqual(n, [1])
        self.assertAlmostEqual(h.volume, 0.0, places=2)

    def test_crossfade_two_ramps(self):
        a = play_sound(_pcm(3.0), volume=1.0, name="music", loops="forever")
        b = play_sound(_pcm(3.0), volume=1.0, name="music", loops="forever", crossfade=1.0)
        self.assertAlmostEqual(b.volume, 0.0)
        _frame(0.5)
        self.assertAlmostEqual(a.volume, 0.5, places=1)
        self.assertAlmostEqual(b.volume, 0.5, places=1)
        self.assertFalse(a.done)
        _frame(0.55)
        self.assertTrue(a.cancelled, "a crossfade replace is a cut by the slot (R5-1)")
        self.assertAlmostEqual(b.volume, 1.0, places=1)
        self.assertFalse(b.done)

    def test_crossfade_ends_the_old_voice_as_a_cut(self):
        """R5-1 (persona probes, round 5): a crossfade ended the old named
        voice with ``fade_out``, a natural end, so its ``on_done`` / ``then=``
        ran, even on a ``forever`` loop (``then=`` takes the same path);
        without ``crossfade=`` nothing ran.
        A replace is one fate, smooth or not (Sound Design)."""
        from scena.audio_mixer import get_mixer
        for loops in ("forever", 1):
            for cf in (0, 0.3, 1.0):
                with self.subTest(loops=loops, crossfade=cf):
                    gone = []
                    a = play_sound(_pcm(3.0), volume=1.0, name="cf", loops=loops,
                                   on_done=lambda: gone.append("on_done"))
                    b = play_sound(_pcm(3.0), volume=1.0, name="cf", loops="forever",
                                   crossfade=cf)
                    for _ in range(15):
                        _frame(0.1)
                    self.assertEqual(gone, [])
                    self.assertTrue(a.cancelled)
                    self.assertNotIn(a._voice_id, get_mixer().voices)
                    self.assertFalse(b.done or b.cancelled)
                    b.cancel()

    def test_clock_scale_stretches_fade(self):
        clock.scale = 0.5
        n = []
        h = play_sound(_pcm(4.0), on_done=lambda: n.append(1))
        h.fade_out(0.2)
        _frame(0.2)  # world dt = 0.1
        self.assertFalse(h.done)
        _frame(0.25)  # world +0.125 → total 0.225
        self.assertTrue(h.done)
        self.assertEqual(n, [1])


class TestMasterBus(PlaySoundTestCase):
    def test_volume_zero_mutes_without_cancelling(self):
        from scena import audio
        from scena.audio_mixer import get_mixer
        h = play_sound(_pcm(1.0), volume=1.0)
        audio.volume = 0.0
        block = get_mixer().render_block(256).block
        self.assertLess(float(np.max(np.abs(block))), 1e-6)
        self.assertFalse(h.done)
        self.assertFalse(h.cancelled)
        audio.volume = 1.0

    def test_muted_roundtrip_and_next_block(self):
        from scena import audio
        from scena.audio_mixer import get_mixer
        play_sound(_pcm(1.0), volume=1.0)
        get_mixer().render_block(64)
        self.assertFalse(audio.muted)
        audio.muted = True
        self.assertTrue(audio.muted)
        block = get_mixer().render_block(64).block
        self.assertLess(float(np.max(np.abs(block))), 1e-6)
        audio.muted = False
        self.assertFalse(audio.muted)
        block = get_mixer().render_block(64).block
        self.assertGreater(float(np.max(np.abs(block))), 0.01)

    def test_level_tau_rejects_non_positive(self):
        from scena import audio
        with self.assertRaises(ValueError):
            audio.level_tau = 0
        with self.assertRaises(ValueError):
            audio.level_tau = -0.1
        audio.level_tau = 0.08

    def test_many_full_scale_voices_limited_quiet_unaffected(self):
        from scena.audio_mixer import BufferSource, Voice, get_mixer, make_sine
        n = 256
        full = np.ones((n, 2), dtype=np.float32)
        voices = {i: Voice(i, BufferSource(full.copy()), volume=1.0) for i in range(1, 9)}
        from scena.audio_mixer import render
        peak = float(np.max(np.abs(render(voices, n).block)))
        self.assertLessEqual(peak, 1.0 + 1e-6)
        quiet = np.full((n, 2), 0.04, dtype=np.float32)
        r = render({1: Voice(1, BufferSource(quiet), volume=1.0)}, n)
        np.testing.assert_allclose(r.block, 0.04, atol=1e-6)


class TestAnalysis(PlaySoundTestCase):
    def test_raw_rms_and_ema_toward_it(self):
        import math
        from scena.audio_mixer import (
            AnalysisState, BufferSource, Voice, ema_alpha, loudness, render, rms,
        )
        n = 2048
        samples = _sine(440, n / _SR, amp=1.0)
        voices = {1: Voice(1, BufferSource(samples), volume=1.0)}
        an = AnalysisState()
        tau = 0.08
        r = render(voices, n, analysis=an, level_tau=tau)
        expected_rms = 1.0 / math.sqrt(2.0)
        self.assertAlmostEqual(r.raw_rms, expected_rms, places=2)
        self.assertAlmostEqual(r.raw_level, loudness(r.block), places=5)
        alpha = ema_alpha(n / _SR, tau)
        self.assertAlmostEqual(r.master_level, r.raw_level * alpha, places=5)
        r2 = render(voices, n, analysis=an, level_tau=tau)
        expected2 = r.master_level + (r2.raw_level - r.master_level) * alpha
        self.assertAlmostEqual(r2.master_level, expected2, places=5)

    def test_spectrum_peak_bin_for_known_frequency(self):
        from scena.audio_mixer import AnalysisState, BufferSource, Voice, render
        n = 4096

        def peak_bin(freq):
            samples = _sine(freq, n / _SR, amp=1.0)
            an = AnalysisState()
            voices = {1: Voice(1, BufferSource(samples), volume=1.0)}
            r = None
            for _ in range(8):
                r = render(voices, n, analysis=an, level_tau=0.02, spectrum_bins=8)
                voices = {1: Voice(1, BufferSource(samples.copy()), volume=1.0)}
            return int(np.argmax(r.master_spectrum))

        low = peak_bin(440)
        high = peak_bin(8000)
        # Log bands: 440 Hz is low-mid; 8 kHz sits several bars higher.
        self.assertGreaterEqual(low, 1)
        self.assertLess(low, 5)
        self.assertGreater(high, low + 1)
        samples = _sine(440, n / _SR, amp=1.0)
        h = play_sound(Sound._from_pcm(samples), loops="forever")
        _frame(0.05)
        self.assertEqual(int(np.argmax(h.spectrum(bins=8))), low)

    def test_voice_meter_reads_after_its_volume_and_pan(self):
        # Showcase A11: h.volume = 0 left h.level reading loud (the meter read
        # the source, before the voice's gains). "How loud this sound is now"
        # (Guia) is after its own volume and pan, before the master.
        from scena.audio_mixer import AnalysisState, BufferSource, Voice, render
        n = 2048
        samples = _sine(440, n / _SR, amp=1.0)

        def level(volume, pan=0.0):
            an = AnalysisState()
            v = {1: Voice(1, BufferSource(samples.copy()), volume=volume, pan=pan)}
            return render(v, n, analysis=an, level_tau=0.001).voice_levels[1]

        loud = level(1.0)
        self.assertGreater(loud, 0.1)
        self.assertEqual(level(0.0), 0.0)
        self.assertLess(level(0.25), loud)
        self.assertLess(level(1.0, pan=1.0), loud)   # one side silent
        h = play_sound(Sound._from_pcm(_sine(440, 2.0, amp=1.0)), loops="forever")
        _frame(0.1)
        self.assertGreater(h.level, 0.05)
        h.volume = 0
        for _ in range(10):
            _frame(0.1)
        self.assertLess(h.level, 1e-3)

    def test_level_tau_change_affects_rise(self):
        from scena.audio_mixer import AnalysisState, BufferSource, Voice, render
        n = 512
        samples = _sine(440, 2.0, amp=1.0)
        src = BufferSource(samples)

        def rise(tau):
            an = AnalysisState()
            v = {1: Voice(1, BufferSource(samples.copy()), volume=1.0)}
            r = render(v, n, analysis=an, level_tau=tau)
            return r.master_level

        slow = rise(0.5)
        fast = rise(0.01)
        self.assertGreater(fast, slow)

    def test_level_on_after_handle_raises(self):
        from scena import after
        h = after(1.0, lambda: None)
        with self.assertRaises(AttributeError) as ctx:
            _ = h.level
        self.assertIn("play_sound", str(ctx.exception))


class TestMixerIdleAndSpectrumInterest(unittest.TestCase):
    def test_settled_idle_skips_work(self):
        mixer = Mixer()
        self.assertTrue(mixer._settled)
        r1 = mixer.render_block(256)
        r2 = mixer.render_block(256)
        self.assertIs(r1, r2)  # shared offline silent result
        self.assertEqual(mixer.snapshot().master_level, 0.0)

    def test_idle_decays_then_settles(self):
        mixer = Mixer()
        samples = make_sine(440, 0.05, amp=1.0)
        mixer.start_voice(samples=samples, volume=1.0)
        mixer.render_block(samples.shape[0])
        self.assertFalse(mixer._settled)
        self.assertGreater(mixer.snapshot().master_level, 0.05)
        # Drain EMA toward silence without voices/commands.
        for _ in range(80):
            mixer.render_block(2048)
            if mixer._settled:
                break
        self.assertTrue(mixer._settled)
        self.assertEqual(mixer.snapshot().master_level, 0.0)
        # Further idle pumps are free (same cached silent result).
        a = mixer.render_block(128)
        b = mixer.render_block(128)
        self.assertIs(a, b)

    def test_spectrum_skipped_until_interest(self):
        mixer = Mixer()
        samples = make_sine(440, 0.1, amp=1.0)
        mixer.start_voice(samples=samples.copy(), volume=1.0, loops=-1)
        mixer.render_block(2048)
        self.assertFalse(mixer._spectrum_wanted)
        # Snapshot spectrum stays at the zero default until someone asks.
        self.assertLess(float(np.max(mixer.snapshot().master_spectrum)), 1e-6)
        mixer.note_spectrum_interest()
        self.assertTrue(mixer._spectrum_wanted)
        # Catch-up from last block fills a real peak.
        peak = int(np.argmax(mixer.snapshot().master_spectrum))
        self.assertGreaterEqual(peak, 1)
        mixer.render_block(2048)
        peak2 = int(np.argmax(mixer.snapshot().master_spectrum))
        self.assertEqual(peak2, peak)

    def test_pure_render_still_computes_spectrum_by_default(self):
        n = 2048
        samples = make_sine(440, n / SAMPLE_RATE, amp=1.0)
        voices = {1: Voice(1, BufferSource(samples), volume=1.0)}
        r = render(voices, n, spectrum_bins=8)
        self.assertGreater(float(np.max(r.master_spectrum)), 0.1)


class TestSoundGuards(PlaySoundTestCase):
    def test_rejects_non_finite_pitch_volume_pan(self):
        tone = Sound._from_pcm(_sine(440, 0.2))
        for kwargs in (
            {"pitch": float("nan")},
            {"pitch": 0},
            {"pitch": float("inf")},
            {"volume": float("nan")},
            {"pan": float("nan")},
        ):
            with self.assertRaises(ValueError):
                play_sound(tone, **kwargs)

    def test_fade_rejects_non_finite_time(self):
        h = play_sound(_pcm(1.0))
        with self.assertRaises(ValueError):
            h.fade_to(0.5, time=float("nan"))
        with self.assertRaises(ValueError):
            h.fade_out(time=float("inf"))
        h.cancel()

    def test_crossfade_zero_is_instant_cut(self):
        from scena.audio_mixer import get_mixer
        gone = []
        a = play_sound(
            _pcm(3.0), volume=1.0, name="music", loops="forever",
            on_done=lambda: gone.append("a"),
        )
        b = play_sound(
            _pcm(3.0), volume=1.0, name="music", loops="forever", crossfade=0,
        )
        self.assertTrue(a.cancelled)
        get_mixer().render_block(256)
        voice = get_mixer().voices.get(b._voice_id)
        self.assertIsNotNone(voice)
        self.assertAlmostEqual(voice.volume, 1.0, places=3)
        self.assertAlmostEqual(b.volume, 1.0, places=3)
        peak = float(np.max(np.abs(get_mixer().render_block(512).block)))
        self.assertGreater(peak, 0.05)
        _frame(0.2)
        self.assertEqual(gone, [])
        b.cancel()

    def test_pause_freezes_fade_out(self):
        n = []
        h = play_sound(_pcm(2.0), on_done=lambda: n.append(1))
        h.fade_out(0.2)
        h.pause()
        _frame(0.5)
        self.assertEqual(n, [])
        self.assertFalse(h.done)
        h.resume()
        _frame(0.3)
        self.assertEqual(n, [1])
        self.assertTrue(h.done)

    def test_level_tau_and_amp_db_reject_non_finite(self):
        from scena import audio
        from scena.audio import amp_db, reset_audio
        with self.assertRaises(ValueError):
            audio.level_tau = float("nan")
        self.assertEqual(amp_db(float("nan")), 0.0)
        self.assertEqual(amp_db(float("inf")), 0.0)
        with self.assertRaises(ValueError):
            amp_db(0.5, floor=float("nan"))
        with self.assertRaises(ValueError):
            amp_db(0.5, floor=float("-inf"))
        reset_audio()

    def test_reset_audio_restores_bus(self):
        from scena import audio
        from scena.audio import reset_audio
        audio.volume = 0.2
        audio.muted = True
        audio.level_tau = 0.5
        reset_audio()
        self.assertEqual(audio.volume, 1.0)
        self.assertFalse(audio.muted)
        self.assertAlmostEqual(audio.level_tau, 0.08)

    def test_spectrum_half_scale_is_not_full(self):
        from scena.audio_mixer import AnalysisState, BufferSource, Voice, render
        n = 4096
        samples = _sine(440, n / _SR, amp=0.5)
        an = AnalysisState()
        voices = {1: Voice(1, BufferSource(samples.copy()), volume=1.0)}
        result = None
        for _ in range(8):
            result = render(voices, n, analysis=an, level_tau=0.02, spectrum_bins=32)
            voices = {1: Voice(1, BufferSource(samples.copy()), volume=1.0)}
        peak = float(np.max(result.master_spectrum))
        self.assertGreater(peak, 0.25)
        self.assertLess(peak, 0.75)

    def test_render_zero_frames_keeps_ema(self):
        from scena.audio_mixer import AnalysisState, BufferSource, Voice, render
        an = AnalysisState()
        samples = _sine(440, 0.05)
        render({1: Voice(1, BufferSource(samples), volume=1.0)}, 512, analysis=an, level_tau=0.08)
        before = an.master_level
        self.assertGreater(before, 0.01)
        render({}, 0, analysis=an, level_tau=0.08)
        self.assertAlmostEqual(an.master_level, before, places=6)

    def test_effects_enabled_false_reaches_mixer(self):
        from scena.audio_effects import LowPass
        from scena.audio_mixer import get_mixer
        h = play_sound(_pcm(0.5))
        h.effects.add(LowPass(cutoff=300))
        h.effects.enabled = False
        get_mixer().render_block(128)
        voice = get_mixer().voices[h._voice_id]
        self.assertEqual(tuple(voice.effects), ())
        h.cancel()

    def test_stream_remaining_uses_file_duration(self):
        from scena.audio import reset_audio
        root = media("audio", "laser-big.ogg")
        reset_audio()
        material = Sound(root, stream=True)
        h = play_sound(material)
        _frame(0.05)
        self.assertGreater(h.remaining, material.duration * 0.5)
        h.cancel()
        reset_audio()

    def test_stream_override_does_not_poison_heuristic(self):
        from scena.audio import reset_audio
        root = media("audio", "laser-big.ogg")
        reset_audio()
        Sound(root, stream=True)
        heuristic = Sound(root)
        self.assertFalse(heuristic._is_stream)
        reset_audio()

    def test_at_frame_past_block_applies_later(self):
        mixer = Mixer()
        samples = np.ones((256, 2), dtype=np.float32) * 0.4
        vid = mixer.start_voice(samples=samples, volume=1.0, loops=-1)
        mixer.set_volume(vid, 0.25, at_frame=100)
        first = mixer.render_block(64)
        np.testing.assert_allclose(first.block, 0.4, atol=1e-5)
        second = mixer.render_block(64)
        # 100 - 64 = 36 samples still at the old volume.
        np.testing.assert_allclose(second.block[:36], 0.4, atol=1e-5)
        np.testing.assert_allclose(second.block[36:], 0.4 * 0.25, atol=1e-5)

    def test_settled_idle_block_matches_request(self):
        mixer = Mixer()
        block = mixer.render_block(256).block
        self.assertEqual(block.shape, (256, 2))
        self.assertLess(float(np.max(np.abs(block))), 1e-8)


class TestWithoutMiniaudio(PlaySoundTestCase):
    """No miniaudio wheel for this Python / computer (3.15 on release): the
    install leaves it out (pyproject marker) and the game runs silent, with
    one SCENA WARNING that says how to get sound."""

    def setUp(self):
        from unittest import mock
        from scena.audio_mixer import reset_mixer
        blocked = mock.patch.dict(sys.modules, {"miniaudio": None})
        blocked.start()
        self.addCleanup(reset_mixer)   # probe the real module again
        self.addCleanup(blocked.stop)
        super().setUp()               # reset_mixer: probes the blocked import

    def _scena_warnings(self, caught):
        return [str(w.message) for w in caught if "SCENA WARNING" in str(w.message)]

    def test_files_play_silence_with_one_warning_for_the_game(self):
        from scena.audio_mixer import NO_MINIAUDIO_MESSAGE
        done = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            h = play_sound(media("audio", "laser-big.ogg"), on_done=lambda: done.append(1))
            play_sound(media("audio", "laser-big.ogg"))
            Sound(media("audio", "laser-big.ogg"))
        msgs = self._scena_warnings(caught)
        self.assertEqual(len(msgs), 1, msgs)
        banner = last_author_error()
        self.assertEqual(banner["where"], "play_sound")
        self.assertEqual(banner["message"], NO_MINIAUDIO_MESSAGE)
        # The missing-file rule: nominal duration, the handle ticks.
        _frame(0.5)
        self.assertFalse(h.done)
        _frame(0.7)
        self.assertEqual(done, [1])
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)

    def test_a_pcm_sound_warns_too(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            h = play_sound(_pcm(0.2))
        self.assertEqual(len(self._scena_warnings(caught)), 1)
        _frame(0.3)
        self.assertTrue(h.done)

    def test_a_game_without_sound_does_not_warn(self):
        from scena.audio_mixer import get_mixer
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            get_mixer().start_device()      # what run() does first
            _frame(0.1)
        self.assertEqual(self._scena_warnings(caught), [])
        self.assertIsNone(last_author_error())
        self.assertTrue(get_mixer().offline)

    def test_microphone_is_silent_and_says_why(self):
        from scena import Microphone
        from scena.audio_mixer import NO_MINIAUDIO_MESSAGE
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            mic = Microphone()
            Microphone(backends=["anything"])   # no Backend to check against
        self.assertEqual(len(self._scena_warnings(caught)), 1)
        banner = last_author_error()
        self.assertEqual(banner["where"], "Microphone")
        self.assertEqual(banner["message"], NO_MINIAUDIO_MESSAGE)
        self.assertEqual(mic.level, 0.0)
        mic.close()

    def test_the_message_names_the_way_out(self):
        from scena.audio_mixer import NO_MINIAUDIO_MESSAGE
        self.assertIn("Python 3.14", NO_MINIAUDIO_MESSAGE)
        self.assertIn("python -m pip install miniaudio", NO_MINIAUDIO_MESSAGE)

    def test_scena_imports_and_plays_in_a_fresh_process(self):
        import subprocess
        import textwrap
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = textwrap.dedent("""
            import sys, warnings
            sys.modules["miniaudio"] = None
            warnings.simplefilter("ignore")
            import scena
            from scena.process import last_author_error
            scena.play_sound("laser-big.ogg")
            print(last_author_error()["message"][:9])
        """)
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, encoding="utf-8", errors="replace",
            cwd=os.path.join(MEDIA, "audio"),
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": root,
                 "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "No sound:")


class TestMiniaudioMarker(unittest.TestCase):
    """pip installs miniaudio only where it has a wheel (1.71's list)."""

    def test_marker_matches_the_wheels(self):
        import tomllib
        from pathlib import Path
        try:
            from packaging.requirements import Requirement
        except ImportError:
            self.skipTest("packaging is not installed")
        root = Path(__file__).resolve().parents[1]
        with open(root / "pyproject.toml", "rb") as f:
            deps = tomllib.load(f)["project"]["dependencies"]
        (req,) = [Requirement(d) for d in deps if d.startswith("miniaudio")]

        def env(py, plat, machine):
            return {"python_version": py, "sys_platform": plat, "platform_machine": machine}

        wheels = [
            env("3.12", "darwin", "arm64"), env("3.14", "darwin", "x86_64"),
            env("3.13", "win32", "AMD64"), env("3.12", "win32", "x86"),
            env("3.14", "linux", "x86_64"),
        ]
        no_wheel = [
            env("3.15", "darwin", "arm64"), env("3.15", "win32", "AMD64"),
            env("3.15", "linux", "x86_64"), env("3.14", "win32", "ARM64"),
            env("3.13", "linux", "aarch64"), env("3.13", "linux", "i686"),
        ]
        for e in wheels:
            self.assertTrue(req.marker.evaluate(e), e)
        for e in no_wheel:
            self.assertFalse(req.marker.evaluate(e), e)


class TestStreamsCloseBeforeExit(unittest.TestCase):
    """A stream's decoder is closed before the interpreter tears miniaudio down.

    Bug (2026-10-27, ``examples/guardian.py``): closing the window during
    the music printed "Exception ignored in _samples_stream_generator ...
    'NoneType' object has no attribute 'ma_decoder_uninit'": the live voice's
    stream was finalized after miniaudio's globals were cleared. Bug class:
    **a decoder still open at interpreter teardown** (Sound Design, "Streams
    at exit"). Teardown order is luck, so the tests pin the mechanism: every
    opened stream is tracked, the closer leaves no suspended decoder, and both
    exits (``run()``'s cleanup, ``atexit``) call it.
    """

    MUSIC = "music/space.ogg"

    def setUp(self):
        try:
            import miniaudio  # noqa: F401
        except ImportError:
            self.skipTest("no miniaudio: nothing streams")

    def _stream(self, loops=-1):
        from scena.audio import StreamFileSource
        src = StreamFileSource(media(self.MUSIC), loops=loops, duration=82)
        out, _ = src.pull(1024, 1.0)          # the decoder starts: its finally is armed
        self.assertGreater(float(np.abs(out).max()), 0.0, "vacuous: the stream is silent")
        return src

    def test_an_open_stream_is_tracked_and_the_closer_ends_its_decoder(self):
        import scena.audio as audio_mod
        audio_mod = sys.modules["scena.audio"]
        src = self._stream()
        gen = src._gen
        self.assertIsNotNone(gen.gi_frame, "vacuous: the decoder is not suspended")
        self.assertIn(src, audio_mod._OPEN_STREAMS)
        audio_mod.close_open_streams()
        self.assertIsNone(gen.gi_frame, "the decoder is still suspended")
        self.assertNotIn(src, audio_mod._OPEN_STREAMS)

    def test_a_closed_stream_plays_silence_and_never_reopens(self):
        src = self._stream(loops=-1)
        src.close()
        src.close()                             # idempotent
        for _ in range(3):
            out, _ = src.pull(4096, 1.0)
            self.assertEqual(float(np.abs(out).max()), 0.0)
        self.assertIsNone(src._gen, "a forever loop reopened the decoder")

    def test_both_exits_close_the_streams(self):
        import inspect
        import scena.orchestration as orch
        cleanup = inspect.getsource(orch.ScenaFramework._cleanup)
        self.assertLess(cleanup.index("stop_device()"), cleanup.index("close_open_streams()"),
                        "run()'s cleanup must close the streams after the device stops")
        # The atexit side in a fresh process: a script that never calls run()
        # still has its open streams closed at exit. (Not in this process:
        # atexit._run_exitfuncs runs every handler here and then drops them
        # all.)
        import subprocess
        import textwrap
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = textwrap.dedent("""
            import sys
            import scena
            class Stream:
                def close(self):
                    print("closed at exit", flush=True)
            stream = Stream()
            sys.modules["scena.audio"]._OPEN_STREAMS.add(stream)
        """)
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": root,
                 "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "closed at exit",
                         "close_open_streams is not an atexit handler")

    def test_the_game_leaves_no_decoder_open_after_the_closer(self):
        """The real case: Ring Guardian's music, after its story screen."""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from program_support import ProgramRun
        audio_mod = sys.modules["scena.audio"]
        with ProgramRun("examples/guardian.py") as run:
            run.step(30)
            run.key_down("SPACE")
            run.step(1)
            run.key_up("SPACE")
            run.step(120)
            open_now = [s for s in audio_mod._OPEN_STREAMS
                        if s._gen is not None and s._gen.gi_frame is not None]
            self.assertTrue(open_now, "vacuous: no music is streaming")
            audio_mod.close_open_streams()
            left = [s.path for s in open_now if s._gen is not None]
            self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
