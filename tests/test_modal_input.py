"""Modal input mask: keyp/mouse reads, latch, swallowed clicks, stuck keys.

    python -m unittest tests.test_modal_input -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glfw

from scena import Button, Circle, TextInput, init, keyp, mouse
from scena.orchestration import ScenaFramework


class ModalInputTest(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        self.fw = ScenaFramework.get_instance()
        self.wm = self.fw.widget_manager
        self.keys = self.fw.keys
        self.owned = []
        self.keys._pressed_keys.clear()
        self.keys._once_fired.clear()
        self.keys._pending_edges.clear()
        self.keys._input_masked = False
        mouse._pressed_buttons.clear()
        mouse._mask_latch_buttons.clear()
        mouse._input_masked = False

    def tearDown(self):
        if self.wm.modal_widget is not None:
            self.wm.release_modal(self.wm.modal_widget)
        self.keys._set_input_masked(False)
        mouse._set_input_masked(False)
        for obj in self.owned:
            try:
                obj.destroy()
            except Exception:
                pass

    def track(self, obj):
        self.owned.append(obj)
        return obj

    def test_key_reads_false_while_masked_and_held_across(self):
        self.keys._press("A")
        self.assertTrue(keyp("A"))
        self.keys._set_input_masked(True)
        self.assertFalse(keyp("A"))
        self.assertFalse(keyp.once("A"))
        self.assertFalse(keyp.held("A"))
        self.keys._press("B")
        self.assertFalse(keyp("B"))
        self.keys._set_input_masked(False)
        self.assertTrue(keyp("A"))
        self.assertTrue(keyp("B"))
        self.assertFalse(keyp.once("A"))
        self.assertFalse(keyp.once("B"))
        self.keys._release("B")
        self.keys._press("B")
        self.assertTrue(keyp.once("B"))

    def test_mask_toggle_repulls_formula(self):
        from scena import st
        st.held_a = False
        st["held_a"] @= lambda: keyp("A")
        self.keys._press("A")
        self.assertTrue(st.held_a)
        self.keys._set_input_masked(True)
        self.assertFalse(st.held_a)
        self.keys._set_input_masked(False)
        self.assertTrue(st.held_a)

    def test_formula_survives_scena_system_reset(self):
        """A graph reset must not orphan keyp: the next formula still re-pulls."""
        from scena.state import init_scena_system
        from scena import st
        init_scena_system()
        st.held_b = False
        st["held_b"] @= lambda: keyp("B")
        self.keys = ScenaFramework.get_instance().keys
        self.keys._press("B")
        self.assertTrue(st.held_b)
        self.keys._release("B")
        try:
            st["held_b"].unlink()
        except Exception:
            pass

    def test_picking_click_stays_hidden_until_release(self):
        mouse._button_down(mouse.BTN_LEFT, 10, 10)
        mouse._set_input_masked(True)
        self.assertFalse(mouse.press())
        self.assertIsNone(mouse.click_pos())
        mouse._set_input_masked(False)
        self.assertFalse(mouse.press(mouse.BTN_LEFT))
        self.assertIsNone(mouse.click_pos(mouse.BTN_LEFT))
        mouse._button_up(mouse.BTN_LEFT)
        mouse._button_down(mouse.BTN_LEFT, 3, 4)
        self.assertTrue(mouse.press(mouse.BTN_LEFT))
        self.assertEqual(mouse.click_pos(mouse.BTN_LEFT), (3, 4))

    def test_modal_swallows_miss_and_blocks_shape_click(self):
        button = self.track(Button(label="Go", top_left=(100, 100), width=80))
        clicked = []
        circle = self.track(Circle(center=(20, 20), radius=30))
        circle.on_click = lambda shape: clicked.append(shape)
        self.wm.push_modal(button)
        self.assertTrue(self.wm.handle_mouse_down(10, 10, mouse.BTN_LEFT))
        if not self.wm.handle_mouse_down(10, 10, mouse.BTN_LEFT):
            self.fw.shape_manager.handle_mouse_down(10, 10, mouse.BTN_LEFT, ui=False)
        self.assertEqual(clicked, [])
        x = (button._x1 + button._x2) * 0.5
        y = (button._y1 + button._y2) * 0.5
        self.assertIs(self.wm.get_widget_at(x, y), button)
        self.assertIsNone(self.wm.get_widget_at(10, 10))

    def test_second_modal_raises(self):
        a = self.track(Button(label="A"))
        b = self.track(Button(label="B"))
        self.wm.push_modal(a)
        with self.assertRaises(RuntimeError):
            self.wm.push_modal(b)
        self.wm.release_modal(a)
        self.wm.push_modal(b)

    def test_release_reaches_keyp_when_textbox_has_focus(self):
        self.fw._handle_key(None, glfw.KEY_A, 0, glfw.PRESS, 0)
        self.assertTrue(keyp("A"))
        box = self.track(TextInput(top_left=(40, 40), width=120))
        self.wm.set_focus(box)
        self.fw._handle_key(None, glfw.KEY_A, 0, glfw.RELEASE, 0)
        self.assertFalse(keyp("A"))

    def test_punctuation_reaches_keyp_and_on_key_by_number(self):
        seen = []
        cm = self.fw.canvas_manager
        original = cm.handle_key_down
        cm.handle_key_down = lambda key: seen.append(key)
        try:
            self.fw._handle_key(None, glfw.KEY_PERIOD, 0, glfw.PRESS, 0)
            self.assertTrue(keyp("K11"))
            self.assertEqual(seen, ["K11"])
            self.fw._handle_key(None, glfw.KEY_PERIOD, 0, glfw.RELEASE, 0)
            self.assertFalse(keyp("K11"))
        finally:
            cm.handle_key_down = original

    def test_unnamed_key_is_dropped(self):
        # Numpad + used to land in keyp and on_key as the raw code "334".
        seen = []
        cm = self.fw.canvas_manager
        original = cm.handle_key_down
        cm.handle_key_down = lambda key: seen.append(key)
        try:
            for code in (glfw.KEY_KP_ADD, glfw.KEY_UNKNOWN):
                self.fw._handle_key(None, code, 0, glfw.PRESS, 0)
            self.assertEqual(seen, [])
            self.assertEqual(dict(self.keys._pressed_keys), {})
        finally:
            cm.handle_key_down = original

    def test_destroy_releases_modal_mask(self):
        button = self.track(Button(label="M"))
        self.wm.push_modal(button)
        self.keys._press("A")
        self.assertFalse(keyp("A"))
        button.destroy()
        self.assertIsNone(self.wm.modal_widget)
        self.assertTrue(keyp("A"))


if __name__ == "__main__":
    unittest.main()
