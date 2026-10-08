"""Framework HUD labels (system info, SCENA WARNING) vs a hard registry wipe.

Bug O3 (Testing Design.md): ``test_ui_layer`` wipes the registry in setUp
(``destroy_all``), which destroys the framework's own HUD labels too. Every
later frame in the same process then failed in ``_refresh_system_label`` /
``_refresh_error_label`` ("Text.visible cannot change a destroyed actor") —
found when the deep tier's serial pass started running the level editor's
system tests after the framework's.

Run: python -m unittest tests.test_hud_labels
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase  # noqa: E402


class TestDeadHudLabels(SystemTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        fw = self.w.fw
        fw._build_system_labels()
        self.addCleanup(fw._build_system_labels)
        shown = fw._show_system_info
        self.addCleanup(setattr, fw, "_show_system_info", shown)

    def test_frames_survive_destroyed_hud_labels(self):
        fw = self.w.fw
        fw._system_label.destroy()
        fw._error_label.destroy()
        fw._show_system_info = True               # the FPS line wants updating
        fw._last_hud_info_time = None
        from scena.process import clear_author_error, report_author_warning
        self.addCleanup(clear_author_error)
        report_author_warning("test", "a pending warning")   # the banner wants showing
        self.w.step(3)                            # used to raise DestroyedError
        fw._flash_system_feedback("feedback")     # Ctrl+Shift shortcuts write here too
        self.w.step(1)

    def test_a_new_game_rebuilds_them(self):
        fw = self.w.fw
        fw._system_label.destroy()
        fw._error_label.destroy()
        fw._build_system_labels()
        self.assertTrue(fw._system_label.is_alive)
        self.assertTrue(fw._error_label.is_alive)


if __name__ == "__main__":
    unittest.main()
