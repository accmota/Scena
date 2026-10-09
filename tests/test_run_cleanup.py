"""``run()`` releases audio / GPU / GLFW however it ends, and author
exceptions propagate unchanged.

Headless: GLFW + audio mixer are mocked; no window opens.

    python -m unittest tests.test_run_cleanup -v
"""
import os
import sys
import unittest
import warnings
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena.audio_mixer as audio_mixer
import scena.orchestration as orch
from scena import init
from scena.orchestration import ScenaFramework


class RunCleanupTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        self.fw = ScenaFramework.get_instance()
        self._saved = (self.fw.setup, self.fw._context, self.fw._running)
        self.mixer = mock.Mock()
        self.context = mock.Mock()
        self.fw._context = self.context
        patches = [
            mock.patch.object(audio_mixer, "get_mixer", return_value=self.mixer),
            mock.patch.object(orch.glfw, "terminate"),
        ]
        self.terminate = patches[1].start()
        patches[0].start()
        for p in patches:
            self.addCleanup(p.stop)

    def tearDown(self):
        self.fw.setup, self.fw._context, self.fw._running = self._saved

    def _assert_cleaned_once(self):
        self.mixer.stop_device.assert_called_once()
        self.context.abandonContext.assert_called_once()
        self.terminate.assert_called_once()
        self.assertFalse(self.fw._running)

    def test_setup_raise_propagates_and_cleans_up(self):
        def setup(canvas):
            raise ValueError("author setup bug")

        self.fw.setup = setup
        with self.assertRaisesRegex(ValueError, "author setup bug"):
            self.fw.run()
        self._assert_cleaned_once()

    def test_loop_raise_propagates_and_cleans_up(self):
        with mock.patch.object(
            self.fw, "_run_loop", side_effect=RuntimeError("author update bug")
        ):
            with self.assertRaisesRegex(RuntimeError, "author update bug"):
                self.fw.run()
        self._assert_cleaned_once()

    def test_keyboard_interrupt_cleans_up(self):
        with mock.patch.object(self.fw, "_run_loop", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.fw.run()
        self._assert_cleaned_once()

    def test_a_closed_window_is_forgotten(self):
        # Review 2026-10-09 S1-11: GLFW was terminated but the framework kept
        # its window fields, so a second run() in the same process (a REPL, a
        # notebook) skipped open_window() and drew on the dead window.
        fw = self.fw
        saved = (fw._windowed, fw._window, fw._drawing_surface, fw._drawing_canvas)
        fw._windowed, fw._window = True, object()
        try:
            with mock.patch.object(fw, "_run_loop"):
                fw.run()
            self.assertFalse(fw._windowed, "the next run() opens a new window")
            self.assertIsNone(fw._window)
            self.assertIsNone(fw._context)
        finally:
            fw._windowed, fw._window, fw._drawing_surface, fw._drawing_canvas = saved

    def test_normal_exit_cleans_up(self):
        with mock.patch.object(self.fw, "_run_loop"):
            self.fw.run()
        self.mixer.start_device.assert_called_once()
        self._assert_cleaned_once()

    def test_failing_cleanup_does_not_shadow_author_error(self):
        self.context.abandonContext.side_effect = RuntimeError("gpu gone")
        self.mixer.stop_device.side_effect = RuntimeError("no device")
        with mock.patch.object(
            self.fw, "_run_loop", side_effect=ValueError("author bug")
        ):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with self.assertRaisesRegex(ValueError, "author bug"):
                    self.fw.run()
        self.terminate.assert_called_once()
        self.assertTrue(
            any("gpu gone" in str(w.message) for w in caught), caught
        )

    def test_no_context_skips_abandon(self):
        self.fw._context = None
        with mock.patch.object(self.fw, "_run_loop"):
            self.fw.run()
        self.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
