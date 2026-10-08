"""ScenaFramework._close_guard: a private close veto for tools (the level editor).

A window close request and the Ctrl+Shift+Z quit both ask the guard; a guard
that returns False keeps the app running. No guard: the old behavior.

Run: python -m unittest tests.test_close_guard
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena.orchestration as orch  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402


class TestCloseGuard(unittest.TestCase):
    def setUp(self):
        self.fw = ScenaFramework.get_instance()
        self.addCleanup(setattr, self.fw, "_close_guard", None)
        self.addCleanup(setattr, self.fw, "_running", self.fw._running)

    def test_no_guard_quits(self):
        self.fw._close_guard = None
        self.fw._running = True
        self.fw._quit_framework()
        self.assertFalse(self.fw._running)
        with mock.patch.object(orch.glfw, "set_window_should_close") as should:
            self.fw._handle_window_close("win")
        should.assert_not_called()

    def test_veto_keeps_running_and_cancels_the_window_close(self):
        asked = []
        self.fw._close_guard = lambda: asked.append(1) or False
        self.fw._running = True
        self.fw._quit_framework()
        self.assertTrue(self.fw._running)
        with mock.patch.object(orch.glfw, "set_window_should_close") as should:
            self.fw._handle_window_close("win")
        should.assert_called_once_with("win", False)
        self.assertEqual(len(asked), 2)

    def test_guard_that_allows(self):
        self.fw._close_guard = lambda: True
        self.fw._running = True
        self.fw._quit_framework()
        self.assertFalse(self.fw._running)
        with mock.patch.object(orch.glfw, "set_window_should_close") as should:
            self.fw._handle_window_close("win")
        should.assert_not_called()


if __name__ == "__main__":
    unittest.main()
