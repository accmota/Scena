"""Script-level callbacks: ``callback_if_exists`` arity + CanvasManager pointer
events (``on_mouse_up`` / ``on_mouse_click`` / ``on_mouse_double_click`` /
``on_mouse_drag``).

Headless (no GLFW window).

    python -m unittest tests.test_script_callbacks -v
"""
import functools
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glfw

from scena import init
from scena.orchestration import CanvasManager, ScenaFramework, callback_if_exists


class _Host:
    pass


class TestCallbackIfExists(unittest.TestCase):
    def test_missing_is_noop(self):
        callback_if_exists(_Host(), "update", 1, 2)

    def test_none_is_noop(self):
        h = _Host()
        h.update = None
        callback_if_exists(h, "update", 1, 2)

    def test_placeholder_lambda_is_skipped(self):
        h = _Host()
        h.update = lambda dt, canvas: None
        callback_if_exists(h, "update", 1, 2)

    def test_plain_function_truncated(self):
        seen = []
        h = _Host()

        def update(dt):
            seen.append(dt)

        h.update = update
        callback_if_exists(h, "update", 0.016, "canvas")
        self.assertEqual(seen, [0.016])

    def test_partial_supported(self):
        seen = []
        h = _Host()
        h.update = functools.partial(lambda a, b: seen.append((a, b)))
        callback_if_exists(h, "update", 1, 2)
        self.assertEqual(seen, [(1, 2)])

    def test_callable_object_supported(self):
        seen = []

        class Updater:
            def __call__(self, dt, canvas):
                seen.append((dt, canvas))

        h = _Host()
        h.update = Updater()
        callback_if_exists(h, "update", 0.5, "c")
        self.assertEqual(seen, [(0.5, "c")])

    def test_bound_method_does_not_count_self(self):
        seen = []

        class Game:
            def update(self, dt):
                seen.append(dt)

        h = _Host()
        h.update = Game().update
        callback_if_exists(h, "update", 0.016, "canvas")
        self.assertEqual(seen, [0.016])

    def test_body_error_propagates(self):
        h = _Host()

        def boom(dt):
            raise ValueError("author bug line")

        h.update = boom
        with self.assertRaisesRegex(ValueError, "author bug"):
            callback_if_exists(h, "update", 0.016, None)

    def test_post_draw_live_accepts_partial(self):
        fw = ScenaFramework.get_instance()
        saved = fw.post_draw
        try:
            fw.post_draw = functools.partial(lambda sk, img: None)
            self.assertTrue(fw._post_draw_live())
            fw.post_draw = lambda skia_canvas, scene_image=None: None
            self.assertFalse(fw._post_draw_live())
            fw.post_draw = None
            self.assertFalse(fw._post_draw_live())
        finally:
            fw.post_draw = saved


class TestCanvasManagerPointer(unittest.TestCase):
    def setUp(self):
        self.cm = CanvasManager()
        self.log = []
        self.cm.on_mouse_up = lambda x, y, b, cx, cy: self.log.append(("up", x, y, b, cx, cy))
        self.cm.on_mouse_click = lambda x, y, b: self.log.append(("click", x, y, b))
        self.cm.on_mouse_double_click = lambda x, y, b: self.log.append(("double", x, y, b))
        self.cm.on_mouse_drag = lambda x, y, b: self.log.append(("drag", x, y, b))

    def _kinds(self):
        return [e[0] for e in self.log]

    def test_up_carries_press_position(self):
        self.cm.handle_mouse_down(10, 20, "LEFT")
        self.cm.handle_mouse_up(12, 21, "LEFT")
        self.assertEqual(self.log[0], ("up", 12, 21, "LEFT", 10, 20))

    def test_click_in_place(self):
        self.cm.handle_mouse_down(10, 20, "LEFT")
        self.cm.handle_mouse_up(12, 21, "LEFT")
        self.assertEqual(self._kinds(), ["up", "click"])

    def test_no_click_when_moved_far(self):
        self.cm.handle_mouse_down(10, 20, "LEFT")
        self.cm.handle_mouse_up(100, 20, "LEFT")
        self.assertEqual(self._kinds(), ["up"])

    def test_click_distance_uses_view_space(self):
        # Zoomed camera: world moved far, view barely moved → still a click.
        self.cm.handle_mouse_down(0, 0, "LEFT", view=(50, 50))
        self.cm.handle_mouse_up(40, 0, "LEFT", view=(52, 50))
        self.assertEqual(self._kinds(), ["up", "click"])

    def test_up_without_script_press_is_not_a_click(self):
        self.cm.handle_mouse_up(5, 5, "LEFT")
        self.assertEqual(self.log, [("up", 5, 5, "LEFT", 5, 5)])

    def test_double_click(self):
        for _ in range(2):
            self.cm.handle_mouse_down(10, 10, "LEFT")
            self.cm.handle_mouse_up(10, 10, "LEFT")
        self.assertEqual(self._kinds(), ["up", "click", "up", "click", "double"])

    def test_third_click_starts_new_pair(self):
        for _ in range(3):
            self.cm.handle_mouse_down(10, 10, "LEFT")
            self.cm.handle_mouse_up(10, 10, "LEFT")
        self.assertEqual(self._kinds().count("double"), 1)

    def test_double_click_needs_same_button(self):
        self.cm.handle_mouse_down(10, 10, "LEFT")
        self.cm.handle_mouse_up(10, 10, "LEFT")
        self.cm.handle_mouse_down(10, 10, "RIGHT")
        self.cm.handle_mouse_up(10, 10, "RIGHT")
        self.assertNotIn("double", self._kinds())

    def test_double_click_expires(self):
        self.cm.handle_mouse_down(10, 10, "LEFT")
        self.cm.handle_mouse_up(10, 10, "LEFT")
        b, vx, vy, t = self.cm._last_click
        self.cm._last_click = (b, vx, vy, t - 1.0)
        self.cm.handle_mouse_down(10, 10, "LEFT")
        self.cm.handle_mouse_up(10, 10, "LEFT")
        self.assertNotIn("double", self._kinds())

    def test_drag_only_while_script_press_held(self):
        self.cm.handle_mouse_move(1, 1)
        self.cm.handle_mouse_down(0, 0, "LEFT")
        self.cm.handle_mouse_move(3, 4)
        self.cm.handle_mouse_up(3, 4, "LEFT")
        self.cm.handle_mouse_move(5, 5)
        drags = [e for e in self.log if e[0] == "drag"]
        self.assertEqual(drags, [("drag", 3, 4, "LEFT")])

    def test_forget_press_stops_drag_and_click(self):
        self.cm.handle_mouse_down(0, 0, "LEFT")
        self.cm.forget_press("LEFT")
        self.cm.handle_mouse_move(3, 4)
        self.assertNotIn("drag", self._kinds())

    def test_missing_author_callbacks_are_noops(self):
        cm = CanvasManager()
        cm.handle_mouse_down(0, 0, "LEFT")
        cm.handle_mouse_move(1, 1)
        cm.handle_mouse_up(1, 1, "LEFT")


class TestFrameworkRoutesScriptPointer(unittest.TestCase):
    """``_handle_mouse_button`` / ``_handle_mouse_move`` reach the script."""

    def setUp(self):
        init(width=1000, height=800)
        self.fw = ScenaFramework.get_instance()
        self._saved_cm = self.fw.canvas_manager
        self.fw.canvas_manager = CanvasManager()
        self.log = []
        cm = self.fw.canvas_manager
        cm.on_mouse_click = lambda x, y, b: self.log.append("click")
        cm.on_mouse_drag = lambda x, y, b: self.log.append("drag")

    def tearDown(self):
        self.fw.canvas_manager = self._saved_cm

    def _button(self, action, pos=(100.0, 100.0)):
        with mock.patch.object(glfw, "get_cursor_pos", return_value=pos):
            self.fw._handle_mouse_button(None, glfw.MOUSE_BUTTON_LEFT, action, 0)

    def test_click_on_empty_canvas(self):
        self._button(glfw.PRESS)
        self._button(glfw.RELEASE)
        self.assertEqual(self.log, ["click"])

    def test_drag_on_empty_canvas(self):
        self._button(glfw.PRESS)
        self.fw._handle_mouse_move(None, 150.0, 120.0)
        self._button(glfw.RELEASE, pos=(150.0, 120.0))
        self.fw._handle_mouse_move(None, 160.0, 120.0)
        self.assertEqual(self.log, ["drag"])


class TestModalDropsShapePress(unittest.TestCase):
    """A modal opened while a shape is held drops that press (bug class: stale press).

    Before the fix the stale ``_pressed_shape`` survived the modal: the next
    release anywhere was routed to it — a click on a shape the pointer merely
    crossed, and the script's own click eaten.
    """

    SHAPE = (100.0, 100.0)   # screen coords
    EMPTY = (400.0, 400.0)

    def setUp(self):
        from scena import Button, Circle
        init(width=1000, height=800)
        self.fw = ScenaFramework.get_instance()
        self._saved_cm = self.fw.canvas_manager
        self.fw.canvas_manager = CanvasManager()
        self.log = []
        cm = self.fw.canvas_manager
        cm.on_mouse_click = lambda x, y, b: self.log.append("script click")
        wx, wy = self.fw.screen_to_world_coords(*self.SHAPE)
        self.card = Circle(center=(wx, wy), radius=20)
        self.card.on_click = lambda s: self.log.append("card click")
        self.modal = Button(label="modal")

    def tearDown(self):
        wm = self.fw.widget_manager
        wm.release_modal(self.modal)
        self.modal.destroy()
        self.card.destroy()
        self.fw.canvas_manager = self._saved_cm

    def _button(self, action, pos):
        with mock.patch.object(glfw, "get_cursor_pos", return_value=pos):
            self.fw._handle_mouse_button(None, glfw.MOUSE_BUTTON_LEFT, action, 0)

    def test_modal_mid_press_leaves_no_stale_press(self):
        wm = self.fw.widget_manager
        self._button(glfw.PRESS, self.SHAPE)
        self.assertTrue(self.card.pointer_pressed)
        wm.push_modal(self.modal)
        self.assertFalse(self.card.pointer_pressed)
        self.assertIsNone(self.fw.shape_manager._pressed_shape)
        self._button(glfw.RELEASE, self.SHAPE)        # the modal eats it
        wm.release_modal(self.modal)
        # Press on empty space, release over the card: no card click.
        self._button(glfw.PRESS, self.EMPTY)
        self._button(glfw.RELEASE, self.SHAPE)
        self.assertNotIn("card click", self.log)
        # The script still gets its own clicks.
        self._button(glfw.PRESS, self.EMPTY)
        self._button(glfw.RELEASE, self.EMPTY)
        self.assertEqual(self.log, ["script click"])


if __name__ == "__main__":
    unittest.main()
