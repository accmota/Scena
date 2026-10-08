"""UIWidget is an Entity: groups, visible, destroy, no layer or collision.

    python -m unittest tests.test_widget_entity -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Button, Circle, DropDown, Slider, Text, click, collide, group, init
from scena.entity import Entity
from scena.orchestration import ScenaFramework


class WidgetEntityTest(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        self.wm = ScenaFramework.get_instance().widget_manager
        self.owned = []

    def tearDown(self):
        for obj in self.owned:
            try:
                obj.destroy()
            except Exception:
                pass

    def track(self, obj):
        self.owned.append(obj)
        return obj

    def test_is_entity_not_graphic_and_no_ink(self):
        b = self.track(Button(label="Go", group="hud"))
        self.assertIsInstance(b, Entity)
        self.assertFalse(b._ink)
        self.assertIsNone(b.layer)
        self.assertTrue(b.is_alive)
        self.assertIn(b, group["hud"])

    def test_group_destroy_and_visible_cover_widgets_and_text(self):
        button = self.track(Button(label="A", group="opts"))
        slider = self.track(Slider(label="Vol", group="opts", top_left=(20, 200)))
        caption = self.track(Text("Opções", group="opts", top_left=(20, 400)))
        self.assertEqual(group["opts"].count, 3)
        group["opts"].visible = False
        self.assertFalse(button.visible)
        self.assertFalse(slider.visible)
        self.assertFalse(caption.visible)
        x = (button._x1 + button._x2) * 0.5
        y = (button._y1 + button._y2) * 0.5
        self.assertIsNone(self.wm.get_widget_at(x, y))
        group["opts"].destroy()
        self.assertTrue(group["opts"].empty)
        self.assertFalse(button.is_alive)
        self.assertNotIn(button, self.wm.widgets)
        self.assertNotIn(slider, self.wm.widgets)

    def test_hidden_textbox_takes_no_keys(self):
        from scena.uiwidget import TextInput
        box = self.track(TextInput(top_left=(40, 40), width=200, initial="hi"))
        self.wm.set_focus(box)
        self.assertTrue(box._has_focus)
        box.visible = False
        self.assertFalse(box._has_focus)
        self.assertFalse(self.wm.handle_key_down("A"))
        self.assertIsNone(self.wm.focused_widget)

    def test_constructor_rollback_leaves_no_widget(self):
        before = list(self.wm.widgets)
        with self.assertRaises(ValueError):
            DropDown(options=[])
        self.assertEqual(self.wm.widgets, before)

    def test_after_cancelled_on_destroy(self):
        button = Button(label="Later")
        handle = button.after(5.0, lambda: None)
        button.destroy()
        self.assertTrue(handle.cancelled)
        self.assertNotIn(button, self.wm.widgets)

    def test_layer_and_collidable_raise(self):
        button = self.track(Button(label="X"))
        with self.assertRaises(TypeError) as layer_err:
            button.layer = "ui"
        self.assertIn("HUD", str(layer_err.exception))
        with self.assertRaises(TypeError) as col_err:
            button.collidable = True
        self.assertIn("cannot collide", str(col_err.exception))
        self.assertIn("not world bodies", str(col_err.exception))
        self.assertNotIn("scene", str(col_err.exception).lower())
        button.collidable = False  # park path; stays opted out
        # enabled is a real flag on widgets (greyed out, inert); not a park alias.
        button.enabled = False
        self.assertFalse(button.enabled)
        self.assertTrue(button.active)
        with self.assertRaises(TypeError):
            button.enabled = "no"

    def test_click_takes_buttons_in_a_group(self):
        # @click used to skip widgets in a group silently; a Button now joins
        # (same handler, receives the button), and other widgets refuse.
        circle = self.track(Circle(center=(100, 100), radius=20, group="mix"))
        button = self.track(Button(label="W", group="mix"))
        seen = []

        @click(group["mix"])
        def on_click(target):
            seen.append(target)

        self.assertTrue(circle.clickable)
        self.assertIs(button.on_click, on_click)

        @click(button)
        def on_widget(target):
            seen.append(target)

        self.assertIs(button.on_click, on_widget)

    def test_click_refuses_value_widgets_before_touching_any(self):
        circle = self.track(Circle(center=(100, 100), radius=20, group="mix2"))
        slider = self.track(Slider(group="mix2"))
        with self.assertRaises(TypeError) as err:
            @click(group["mix2"])
            def on_click(target):
                pass
        self.assertIn("@on_change(slider.data)", str(err.exception))
        self.assertFalse(circle.clickable)  # nothing half-applied

    def test_collide_does_not_enroll_widgets(self):
        self.track(Circle(center=(40, 40), radius=10, group="fleet"))
        button = self.track(Button(label="W", group="fleet"))

        @collide("fleet", "fleet")
        def boom(a, b):
            pass

        self.assertIsNone(button._collider)
        self.assertFalse(button.collidable)

    def test_park_hides_and_blocks_hits(self):
        button = self.track(Button(label="P", top_left=(30, 30)))
        x = (button._x1 + button._x2) * 0.5
        y = (button._y1 + button._y2) * 0.5
        self.assertIs(self.wm.get_widget_at(x, y), button)
        button.active = False
        self.assertFalse(button.visible)
        self.assertIsNone(self.wm.get_widget_at(x, y))
        button.active = True
        self.assertTrue(button.visible)
        self.assertIs(self.wm.get_widget_at(x, y), button)


if __name__ == "__main__":
    unittest.main()
