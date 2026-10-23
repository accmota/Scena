"""Microphone capture tests. Run: python -m unittest tests.test_audio_capture -v"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import types
import unittest
import warnings
from unittest.mock import Mock, patch

import miniaudio
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Circle, Distortion, Echo, Sound, clock, play_sound
from scena.audio import reset_audio
from scena.audio_capture import MAX_RECORD_SECONDS, Microphone, capture_devices_open
from scena.audio_mixer import SAMPLE_RATE, PullSource, get_mixer
from scena.process import (
    SCOPE_ENTITY,
    clear_author_error,
    last_author_error,
    owning,
    reset_process_scheduler,
    tick_processes,
)


class TestMicrophone(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()

    def tearDown(self):
        reset_process_scheduler()

    def test_null_capture_level_is_zero(self):
        before = capture_devices_open()
        mic = Microphone(backends=[miniaudio.Backend.NULL])
        try:
            self.assertEqual(mic.level, 0.0)
            spec = mic.spectrum(bins=8)
            self.assertEqual(len(spec), 8)
            self.assertTrue(all(v == 0.0 for v in spec))
        finally:
            mic.close()
        self.assertGreater(capture_devices_open(), before - 1)  # closed back
        self.assertEqual(capture_devices_open(), before)

    def test_does_not_open_device_before_construct(self):
        before = capture_devices_open()
        self.assertEqual(before, 0)
        mic = Microphone(backends=[miniaudio.Backend.NULL])
        self.assertEqual(capture_devices_open(), before + 1)
        mic.close()
        self.assertEqual(capture_devices_open(), before)

    def test_available_says_whether_an_input_is_open(self):
        # Showcase C (2026-10-23): a game had no way to know the mic is
        # silent but the SCENA WARNING. ``available`` is read-only.
        mic = Microphone(backends=[miniaudio.Backend.NULL])
        try:
            self.assertTrue(mic.available)
            with self.assertRaises(AttributeError):
                mic.available = False
        finally:
            mic.close()
        self.assertFalse(mic.available)
        with patch("miniaudio.CaptureDevice", side_effect=RuntimeError("no device")), \
                warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            silent = Microphone()
        try:
            self.assertFalse(silent.available)
            self.assertEqual(silent.level, 0.0)
        finally:
            silent.close()

    def test_close_idempotent(self):
        mic = Microphone(backends=[miniaudio.Backend.NULL])
        mic.close()
        mic.close()
        mic.close()
        self.assertTrue(mic._closed)

    def test_play_sound_mic_uses_frame_source_seam(self):
        mic = Microphone(backends=[miniaudio.Backend.NULL])
        try:
            src = mic._audio_frame_source()
            self.assertIsInstance(src, PullSource)
            h = play_sound(mic)
            get_mixer().render_block(64)
            voices = list(get_mixer().voices.values())
            self.assertEqual(len(voices), 1)
            self.assertIsInstance(voices[0].source, PullSource)
            h.cancel()
        finally:
            mic.close()


    def test_close_clears_spectrum(self):
        import numpy as np
        mic = Microphone(backends=[miniaudio.Backend.NULL])
        mic._ingest((np.random.randn(4096, 2).astype(np.float32) * 0.5).tobytes())
        self.assertGreater(mic.level, 0.0)
        self.assertGreater(float(np.max(mic._spectrum)), 0.0)
        mic.close()
        self.assertEqual(mic.level, 0.0)
        self.assertEqual(float(np.max(mic._spectrum)), 0.0)
        mic.close()

    def test_two_monitors_hear_the_same_buffer(self):
        import numpy as np
        from scena.audio_mixer import get_mixer
        mic = Microphone(backends=[miniaudio.Backend.NULL])
        try:
            impulse = np.zeros((4096, 2), dtype=np.float32)
            impulse[0] = 1.0
            mic._ingest(impulse.tobytes())
            first = play_sound(mic)
            second = play_sound(mic)
            dry = get_mixer().render_block(1024).voice_dry
            self.assertAlmostEqual(float(dry[first._voice_id][0, 0]), 1.0, places=4)
            self.assertAlmostEqual(float(dry[second._voice_id][0, 0]), 1.0, places=4)
            first.cancel()
            second.cancel()
        finally:
            mic.close()


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


def _feed(mic, frames):
    mic._ingest(np.ascontiguousarray(frames, dtype=np.float32).tobytes())


class TestRecording(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        reset_audio()
        clear_author_error()
        self._owned = []
        self.mic = Microphone(backends=[miniaudio.Backend.NULL])
        self.mic._device.stop()

    def tearDown(self):
        for obj in self._owned:
            try:
                if getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self.mic.close()
        reset_process_scheduler()
        reset_audio()
        clear_author_error()

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def test_record_stop_returns_exact_pcm_and_duration_grows(self):
        clip = self.mic.record()
        self.assertIsInstance(clip, Sound)
        self.assertTrue(self.mic.recording)
        self.assertEqual(clip.duration, 0.0)
        self.assertEqual(clip._record_handle.scope, "game")  # ownerless, top level
        first = np.full((SAMPLE_RATE // 2, 2), 0.25, np.float32)
        _feed(self.mic, first)
        self.assertAlmostEqual(clip.duration, 0.5, places=4)
        second = np.full((100, 2), -0.5, np.float32)
        _feed(self.mic, second)
        self.assertIsNone(clip._samples)
        done = []
        # on_done was not passed; stop keeps the clip immediately.
        self.mic.stop()
        self.assertFalse(self.mic.recording)
        expected = np.concatenate([first, second], axis=0)
        np.testing.assert_array_equal(clip._pcm(), expected)
        self.assertAlmostEqual(clip.duration, expected.shape[0] / SAMPLE_RATE, places=5)
        with self.assertRaises(RuntimeError) as stopped:
            self.mic.stop()
        self.assertIn("mic.record()", str(stopped.exception))
        with self.assertRaises(RuntimeError) as again:
            self.mic.record()
            self.mic.record()
        self.assertIn("already recording", str(again.exception))
        self.mic.stop()
        self.assertEqual(done, [])

    def test_record_while_recording_raises_and_keeps_the_take(self):
        clip = self.mic.record()
        buf = np.full((32, 2), 0.2, np.float32)
        _feed(self.mic, buf)
        with self.assertRaises(RuntimeError):
            self.mic.record()
        self.mic.stop()
        np.testing.assert_array_equal(clip._pcm(), buf)

    def test_samples_before_record_are_not_in_the_clip(self):
        _feed(self.mic, np.full((80, 2), 0.9, np.float32))
        clip = self.mic.record()
        post = np.full((40, 2), 0.1, np.float32)
        _feed(self.mic, post)
        self.mic.stop()
        np.testing.assert_array_equal(clip._pcm(), post)

    def test_recording_is_dry_even_with_mic_effects_and_monitors(self):
        self.mic.effects.add(Distortion(drive=8))
        raw = np.zeros((2048, 2), np.float32)
        raw[:, 0] = 0.4
        raw[:, 1] = -0.25
        clip = self.mic.record()
        monitor = play_sound(self.mic)
        _feed(self.mic, raw)
        wet = get_mixer().render_block(1024).voice_dry[monitor._voice_id]
        self.mic.stop()
        np.testing.assert_array_equal(clip._pcm(), raw)
        self.assertFalse(np.allclose(wet, raw[:1024]))
        monitor.cancel()

    def test_take_without_a_monitor_and_two_monitors_do_not_duplicate(self):
        raw = np.full((300, 2), 0.15, np.float32)
        clip = self.mic.record()
        _feed(self.mic, raw)
        self.mic.stop()
        np.testing.assert_array_equal(clip._pcm(), raw)

        clip2 = self.mic.record()
        first = play_sound(self.mic)
        second = play_sound(self.mic)
        _feed(self.mic, raw)
        get_mixer().render_block(128)
        self.mic.stop()
        self.assertEqual(clip2._pcm().shape[0], raw.shape[0])
        np.testing.assert_array_equal(clip2._pcm(), raw)
        first.cancel()
        second.cancel()

    def test_seconds_truncates_mid_block_and_on_done_fires_once(self):
        done = []
        n = 5000
        ramp = np.linspace(-1.0, 1.0, n, dtype=np.float32)
        buf = np.column_stack([ramp, ramp])
        clip = self.mic.record(seconds=0.1, on_done=lambda: done.append(1))
        _feed(self.mic, buf)
        self.assertFalse(clip._record_handle.done)
        self.assertEqual(done, [])
        limit = int(round(0.1 * SAMPLE_RATE))
        self.assertEqual(clip.duration, limit / SAMPLE_RATE)
        _frame()
        self.assertEqual(done, [1])
        self.assertTrue(clip._record_handle.done)
        self.assertFalse(clip._record_handle.cancelled)
        got = clip._pcm()
        self.assertEqual(got.shape[0], limit)
        np.testing.assert_allclose(got[:, 0], ramp[:limit])
        _feed(self.mic, buf)
        _frame()
        self.assertEqual(done, [1])
        self.assertEqual(clip._pcm().shape[0], limit)

    def test_open_ended_take_stops_at_the_cap_with_one_warning(self):
        done = []
        n = int(MAX_RECORD_SECONDS * SAMPLE_RATE) + SAMPLE_RATE
        buf = np.zeros((n, 2), np.float32)
        buf[0, 0] = 0.5
        kept = int(MAX_RECORD_SECONDS * SAMPLE_RATE)
        buf[kept - 1, 1] = -0.25
        buf[-1, 0] = 9.0
        clip = self.mic.record(on_done=lambda: done.append("cap"))
        _feed(self.mic, buf)
        self.assertEqual(done, [])
        _frame()
        self.assertEqual(done, ["cap"])
        self.assertEqual(clip._pcm().shape[0], kept)
        self.assertAlmostEqual(float(clip._pcm()[0, 0]), 0.5)
        self.assertAlmostEqual(float(clip._pcm()[kept - 1, 1]), -0.25)
        err = last_author_error()
        self.assertIsNotNone(err)
        self.assertIn("30", err["message"])
        self.assertEqual(err["count"], 1)
        self.mic._warn_cap()
        self.assertEqual(last_author_error()["count"], 1)
        _frame()
        self.assertEqual(done, ["cap"])

    def test_invalid_seconds_raise(self):
        for bad in (float("nan"), float("inf"), 0, -1, 31):
            with self.assertRaises(ValueError):
                self.mic.record(seconds=bad)
        self.assertFalse(self.mic.recording)

    def test_pending_clip_cannot_play_bake_or_decode(self):
        clip = self.mic.record()
        _feed(self.mic, np.full((16, 2), 0.2, np.float32))
        for call in (
            lambda: play_sound(clip),
            lambda: clip.bake(Echo()),
            lambda: clip._pcm(),
        ):
            with self.assertRaises(RuntimeError) as caught:
                call()
            self.assertIn("still recording", str(caught.exception))
        self.assertEqual(get_mixer().voices, {})
        self.mic.stop()
        self.assertEqual(clip._pcm().shape[0], 16)

    def test_await_record_returns_the_same_finished_clip(self):
        seen = {}

        async def flying(e):
            clip = self.mic.record(seconds=0.1)
            seen["started"] = clip
            seen["got"] = await clip

        c = self.track(Circle())
        c.mode = flying
        self.assertTrue(self.mic.recording)
        _feed(self.mic, np.full((8000, 2), 0.3, np.float32))
        _frame()
        self.assertIs(seen["got"], seen["started"])
        self.assertFalse(self.mic.recording)
        self.assertEqual(
            seen["got"]._pcm().shape[0], int(round(0.1 * SAMPLE_RATE))
        )

    def test_await_file_sound_raises(self):
        async def flying(e):
            await Sound._from_pcm(np.zeros((16, 2), np.float32))

        c = self.track(Circle())
        with self.assertRaises(TypeError) as caught:
            c.mode = flying
        self.assertIn("mic.record()", str(caught.exception))

    def test_mode_leave_keeps_audio_without_on_done(self):
        done = []
        held = {}
        buf = np.full((64, 2), 0.4, np.float32)

        def idle(e):
            pass

        def flying(e):
            held["clip"] = self.mic.record(on_done=lambda: done.append(1))

        c = self.track(Circle())
        c.mode = flying
        self.assertEqual(held["clip"]._record_handle.scope, "mode")
        _feed(self.mic, buf)
        c.mode = idle
        self.assertFalse(self.mic.recording)
        self.assertTrue(held["clip"]._record_handle.cancelled)
        np.testing.assert_array_equal(held["clip"]._pcm(), buf)
        _frame()
        self.assertEqual(done, [])

    def test_destroy_keeps_audio_without_on_done(self):
        done = []
        buf = np.full((48, 2), -0.2, np.float32)
        c = self.track(Circle())
        with owning(c, SCOPE_ENTITY):
            clip = self.mic.record(on_done=lambda: done.append(1))
        self.assertEqual(clip._record_handle.scope, "entity")
        _feed(self.mic, buf)
        c.destroy()
        self.assertFalse(self.mic.recording)
        np.testing.assert_array_equal(clip._pcm(), buf)
        _frame()
        self.assertEqual(done, [])

    def test_close_keeps_audio_without_on_done(self):
        done = []
        buf = np.full((36, 2), 0.7, np.float32)
        clip = self.mic.record(on_done=lambda: done.append(1))
        _feed(self.mic, buf)
        self.mic.close()
        self.assertFalse(self.mic.recording)
        np.testing.assert_array_equal(clip._pcm(), buf)
        _frame()
        self.assertEqual(done, [])
        with self.assertRaises(RuntimeError):
            self.mic.record()

    def test_play_and_bake_after_stop_and_bakes_do_not_collide(self):
        def grab(value):
            clip = self.mic.record()
            _feed(self.mic, np.full((1800, 2), value, np.float32))
            self.mic.stop()
            return clip

        loud = grab(0.8)
        quiet = grab(0.05)
        handle = play_sound(loud)
        dry = get_mixer().render_block(64).voice_dry[handle._voice_id]
        self.assertGreater(float(np.max(np.abs(dry))), 0.1)
        handle.cancel()
        baked_loud = loud.bake(Echo())
        baked_quiet = quiet.bake(Echo())
        self.assertIsNot(baked_loud, baked_quiet)
        self.assertFalse(np.allclose(baked_loud._pcm(), baked_quiet._pcm()))
        self.assertIs(loud.bake(Echo()), baked_loud)

    def test_no_device_is_silent_and_timed_record_still_completes(self):
        self.mic.close()
        before = capture_devices_open()
        with patch("miniaudio.CaptureDevice", side_effect=RuntimeError("no device")):
            mic = Microphone()
        self.mic = mic
        self.assertEqual(capture_devices_open(), before)
        self.assertEqual(mic.level, 0.0)
        self.assertTrue(mic._silent)
        err = last_author_error()
        self.assertIsNotNone(err)
        self.assertIn("silent", err["message"].lower())
        clock_t = [0.0]
        mic._now = lambda: clock_t[0]
        done = []
        clip = mic.record(seconds=0.5, on_done=lambda: done.append(1))
        clock_t[0] = 0.5
        _frame()
        self.assertEqual(done, [1])
        pcm = clip._pcm()
        self.assertEqual(pcm.shape[0], int(round(0.5 * SAMPLE_RATE)))
        self.assertTrue(np.all(pcm == 0.0))


def _fake_miniaudio():
    """Stand-in whose ``close`` reports a live release during interpreter shutdown.

    ``__del__`` calls ``close``, the same way pyminiaudio's devices do. A device
    still live at that point is the crash: CoreAudio's thread calls back into
    Python while the interpreter is finalizing.
    """
    fake = types.ModuleType("miniaudio")

    class SampleFormat:
        FLOAT32 = 1

    class _Device:
        def __init__(self, **kwargs):
            self._live = True

        def start(self, gen):
            self._gen = gen

        def close(self):
            if self._live and sys.is_finalizing():
                print("CLOSED_WHILE_FINALIZING")
            self._live = False

        def __del__(self):
            self.close()

    fake.SampleFormat = SampleFormat
    fake.CaptureDevice = _Device
    fake.PlaybackDevice = _Device
    return fake


class TestShutdownClosesCapture(unittest.TestCase):
    def test_run_cleanup_closes_open_microphones(self):
        import scena.audio_mixer as audio_mixer
        import scena.orchestration as orch
        from scena.orchestration import ScenaFramework

        before = capture_devices_open()
        with patch.dict(sys.modules, {"miniaudio": _fake_miniaudio()}):
            mic = Microphone()
            self.assertEqual(capture_devices_open(), before + 1)
            fw = ScenaFramework.get_instance()
            saved_ctx = fw._context
            fw._context = None
            try:
                with patch.object(audio_mixer, "get_mixer", return_value=Mock()), \
                     patch.object(orch.glfw, "terminate"):
                    fw._cleanup()
            finally:
                fw._context = saved_ctx
        self.assertTrue(mic._closed)
        self.assertEqual(capture_devices_open(), before)

    def test_live_device_is_not_released_during_interpreter_shutdown(self):
        """A device still live at finalization writes a marker file.

        ``__del__`` calls ``close``, as pyminiaudio does. Builtins are already
        gone by then, so the marker uses an ``open`` captured beforehand.
        Capture and playback share that ``close``.
        """
        import tempfile

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fd, marker = tempfile.mkstemp(prefix="mic_shutdown_", dir=root)
        os.close(fd)
        os.remove(marker)
        self.addCleanup(lambda: os.path.exists(marker) and os.remove(marker))
        script = textwrap.dedent("""
            import builtins
            import os
            import sys
            import types

            _open = builtins.open
            _finalizing = sys.is_finalizing
            marker = os.environ["SCENA_SHUTDOWN_MARKER"]

            fake = types.ModuleType("miniaudio")

            class SampleFormat:
                FLOAT32 = 1

            class _Device:
                def __init__(self, **kwargs):
                    self._live = True

                def start(self, gen):
                    self._gen = gen

                def close(self):
                    if self._live and _finalizing():
                        with _open(marker, "a") as fh:
                            fh.write("CLOSED_WHILE_FINALIZING\\n")
                    self._live = False

                def __del__(self):
                    self.close()

            fake.SampleFormat = SampleFormat
            fake.CaptureDevice = _Device
            fake.PlaybackDevice = _Device
            sys.modules["miniaudio"] = fake

            from scena.audio_capture import Microphone
            mic = Microphone()
        """)
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            encoding="utf-8", errors="replace",
            cwd=root,
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": root,
                "PYTHONDONTWRITEBYTECODE": "1",
                "SCENA_SHUTDOWN_MARKER": marker,
            },
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        written = open(marker, encoding="utf-8").read() if os.path.exists(marker) else ""
        self.assertNotIn("CLOSED_WHILE_FINALIZING", written)


if __name__ == "__main__":
    unittest.main()
