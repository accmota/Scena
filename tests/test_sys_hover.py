"""Hover through the real frame body (``ScenaFramework._simulate_frame``).

Unit tests drive ``ShapeInteractionManager`` directly; this module checks the
wiring: ``_step_hover`` runs every frame, after collision / leave-playfield and
before ``flush`` (so ``@when`` sees a hover handler's write in the same
frame), and the widget under the cursor is handed to the resolver.

    python -m unittest tests.test_sys_hover -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase  # noqa: E402

from scena import Button, Circle, hover, hover_exit, when  # noqa: E402


class TestHoverInTheFrame(SystemTestCase, unittest.TestCase):
    world_draw = False

    def setUp(self):
        super().setUp()
        self.sm = self.w.fw.shape_manager
        self.log = []
        self.card = self.track(Circle(center=(40_000, 40_000), radius=30))
        self.card.clickable = True

        @hover(self.card)
        def lit(card):
            self.log.append(("enter", self.w.frames_run))
            card.lit = True

        @hover_exit(self.card)
        def unlit(card):
            self.log.append(("exit", self.w.frames_run))
            card.lit = False

        self.card.lit = False

    def tearDown(self):
        self.sm.note_pointer(view_xy=(-1e6, -1e6), world_xy=(-1e6, -1e6))
        self.w.fw.widget_manager.mouse_over_widget = None
        super().tearDown()

    def point_at_card(self):
        self.sm.note_pointer(view_xy=(-1e6, -1e6), world_xy=(40_000, 40_000))

    def test_frame_resolves_hover_and_when_sees_it_same_frame(self):
        seen = []

        @when(lambda: self.card.lit)
        def on_lit():
            seen.append(self.w.frames_run)

        self.point_at_card()
        self.w.step()
        self.assertTrue(self.card.pointer_hover)
        self.assertEqual(self.log, [("enter", 0)])
        self.assertEqual(seen, [0])  # flushed after the hover step

    def test_hide_exits_next_frame_with_still_pointer(self):
        self.point_at_card()
        self.w.step()
        self.card.visible = False
        self.w.step()
        self.assertFalse(self.card.pointer_hover)
        self.assertEqual([k for k, _ in self.log], ["enter", "exit"])

    def test_widget_under_cursor_takes_hover(self):
        button = self.track(Button(label="over"))
        self.point_at_card()
        self.w.step()
        self.w.fw.widget_manager.mouse_over_widget = button
        self.w.step()
        self.assertTrue(button.pointer_hover)
        self.assertFalse(self.card.pointer_hover)
        self.w.fw.widget_manager.mouse_over_widget = None
        self.w.step()
        self.assertTrue(self.card.pointer_hover)
        self.assertEqual([k for k, _ in self.log], ["enter", "exit", "enter"])


if __name__ == "__main__":
    unittest.main()
