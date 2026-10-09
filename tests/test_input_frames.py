"""Input contracts in real frames, through the framework's own GLFW handlers
(review 2026-10-09, batch 3: R4 / R5). A frame contract needs frames
(Testing Design, "What the program-model campaign taught" 2).

    python tests/run_tiers.py focused test_input_frames
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glfw  # noqa: E402

from scena import (  # noqa: E402
    Button, Circle, Menu, Mouse, canvas, keyp, mouse,
)
from tests.input_driver import input_driver  # noqa: E402
from tests.system_support import system_world  # noqa: E402

FRAME = 1 / 60


class TestMouseDeltaIsPerFrame(unittest.TestCase):
    """``mouse.dx`` / ``.dy``: how far the pointer moved since the previous
    frame (Guia), not the last callback's step (S1-1 / S3-1)."""

    def test_still_frames_read_zero_and_one_poll_adds_up(self):
        seen = []
        with system_world(draw=False) as w, input_driver(w) as d:
            w.on_update(lambda dt: seen.append(mouse.dx))
            d.move(100, 100)
            w.step(1, dt=FRAME)
            d.move(110, 100)
            w.step(1, dt=FRAME)                 # +10 this frame
            w.step(3, dt=FRAME)                 # still
            d.move(115, 100)
            d.move(130, 100)                    # two callbacks, one poll
            w.step(1, dt=FRAME)
        self.assertEqual(seen[1:], [10.0, 0.0, 0.0, 0.0, 20.0])


class TestDragFollowsTheWorldPointer(unittest.TestCase):

    def test_drag_stays_under_a_still_cursor_while_the_camera_pans(self):
        # review S3-4
        with system_world(draw=False) as w, input_driver(w) as d:
            c = Circle(center=(200, 150), radius=20)
            c.draggable = True
            w.fw.shape_manager.drag_threshold = 1.0
            d.move(200, 150)
            w.step(1, dt=FRAME)
            d.down()
            d.move(210, 150)
            w.step(1, dt=FRAME)
            for _ in range(20):
                canvas.pan_by(5, 0)
                w.step(1, dt=FRAME)
            self.assertAlmostEqual(c.center.x - mouse.x, 0.0, places=6)
            d.up()
            c.destroy()


class TestModalInput(unittest.TestCase):

    def test_a_hidden_modal_lifts_the_mask(self):
        # review S3-2: a hidden / parked modal stopped being modal, the mask stayed
        for how in ("visible", "active"):
            with self.subTest(how), system_world(draw=False) as w, input_driver(w) as d:
                m = Menu(options=["Resume", "Quit"], modal=True)
                w.step(1, dt=FRAME)
                setattr(m, how, False)
                got = {}
                w.on_update(lambda dt: got.update(held=keyp("SPACE")))
                d.press(glfw.KEY_SPACE)
                w.step(1, dt=FRAME)
                self.assertTrue(got["held"])
                d.release(glfw.KEY_SPACE)
                m.destroy()
                w.step(1, dt=FRAME)

    def test_every_script_down_gets_its_up_across_a_modal(self):
        # review S3-7
        log = []
        with system_world(draw=False) as w, input_driver(w) as d:
            cm = w.fw.canvas_manager
            saved = (cm.on_key_down, cm.on_key_up, cm.on_mouse_down, cm.on_mouse_up)
            try:
                cm.on_key_down = lambda k: log.append("down")
                cm.on_key_up = lambda k: log.append("up")
                cm.on_mouse_down = lambda x, y, b: log.append("mdown")
                cm.on_mouse_up = lambda x, y, b, cx, cy: log.append("mup")
                d.move(20, 20)
                d.press(glfw.KEY_SPACE)
                d.down()
                w.step(1, dt=FRAME)
                m = Menu(options=["A", "B"], modal=True)
                w.step(1, dt=FRAME)
                d.release(glfw.KEY_SPACE)
                d.up()
                w.step(1, dt=FRAME)
                m.destroy()
                w.step(1, dt=FRAME)
            finally:
                cm.on_key_down, cm.on_key_up, cm.on_mouse_down, cm.on_mouse_up = saved
        self.assertEqual(sorted(log), ["down", "mdown", "mup", "up"])

    def test_click_pos_ignores_a_click_made_under_the_modal(self):
        # review S3-11
        with system_world(draw=False) as w, input_driver(w) as d:
            d.move(30, 30)
            d.down()
            d.up()
            w.step(1, dt=FRAME)
            game = mouse.click_pos(Mouse.BTN_LEFT)
            m = Menu(options=["Resume"], modal=True)
            w.step(1, dt=FRAME)
            d.move(200, 200)
            d.down()
            d.up()
            w.step(1, dt=FRAME)
            m.destroy()
            w.step(1, dt=FRAME)
            self.assertEqual(mouse.click_pos(Mouse.BTN_LEFT), game)


class TestKeyEdges(unittest.TestCase):

    def test_a_consumed_shortcut_sends_no_up(self):
        # review S1-10
        cs = glfw.MOD_CONTROL | glfw.MOD_SHIFT
        log = []
        with system_world(draw=False) as w, input_driver(w) as d:
            cm = w.fw.canvas_manager
            saved = (cm.on_key_down, cm.on_key_up)
            try:
                cm.on_key_down = lambda k: log.append(("down", str(k)))
                cm.on_key_up = lambda k: log.append(("up", str(k)))
                for code in (glfw.KEY_LEFT_CONTROL, glfw.KEY_LEFT_SHIFT):
                    d.press(code, cs)
                for _ in range(2):              # toggle the HUD on and off
                    d.press(glfw.KEY_1, cs)
                    d.release(glfw.KEY_1, cs)
                    w.step(1, dt=FRAME)
                for code in (glfw.KEY_LEFT_SHIFT, glfw.KEY_LEFT_CONTROL):
                    d.release(code)
                w.step(1, dt=FRAME)
            finally:
                cm.on_key_down, cm.on_key_up = saved
        self.assertEqual([e for e in log if e[1] == "1"], [])

    def test_once_survives_a_modifier_tap_in_the_same_poll(self):
        # review S3-9
        got = []
        with system_world(draw=False) as w, input_driver(w) as d:
            w.on_update(lambda dt: got.append(keyp.once("A")))
            d.press(glfw.KEY_A)
            d.press(glfw.KEY_LEFT_SHIFT)
            d.release(glfw.KEY_LEFT_SHIFT)
            w.step(1, dt=FRAME)
            d.release(glfw.KEY_A)
            w.step(1, dt=FRAME)
        self.assertEqual(got[0], True)


class TestWidgetHover(unittest.TestCase):

    def _center(self, b):
        bx = b.box
        return (bx.left + bx.right) / 2, (bx.top + bx.bottom) / 2

    def test_highlight_clears_after_press_drag_off_release(self):
        # review S3-5 / S1-3
        with system_world(draw=False) as w, input_driver(w) as d:
            b = Button(label="Start", top_left=(50, 250))
            w.step(1, dt=FRAME)
            cx, cy = self._center(b)
            d.move(cx, cy)
            w.step(1, dt=FRAME)
            d.down()
            d.move(cx + 1, cy)
            d.move(cx + 300, cy - 200)
            d.up()
            w.step(1, dt=FRAME)
            self.assertFalse(b._is_mouse_over)
            b.destroy()

    def test_a_widget_shown_under_a_still_cursor_is_hovered(self):
        # review S3-6
        with system_world(draw=False) as w, input_driver(w) as d:
            b = Button(label="Go", top_left=(50, 250))
            w.step(1, dt=FRAME)
            d.move(*self._center(b))
            w.step(1, dt=FRAME)
            b.visible = False
            w.step(1, dt=FRAME)
            b.visible = True
            w.step(1, dt=FRAME)
            self.assertTrue(b.pointer_hover)
            b.destroy()


class TestActChangeForgetsPointerInput(unittest.TestCase):

    def test_a_press_from_the_old_act_is_not_a_click_in_the_new_one(self):
        # review S3-8
        from scena.act import Act, change_act
        log = []

        class Game(Act):
            pass

        class Title(Act):
            pass

        with system_world(draw=False) as w, input_driver(w) as d:
            cm = w.fw.canvas_manager
            saved = cm.on_mouse_click
            try:
                cm.on_mouse_click = lambda x, y, b: log.append("click")
                w.begin_game(Title)
                d.move(20, 20)
                d.down()
                change_act(Game)
                d.up()
                w.step(1, dt=FRAME)
            finally:
                cm.on_mouse_click = saved
        self.assertEqual(log, [])



class TestARaisingPollKeepsInputTrue(unittest.TestCase):
    """Review 2026-10-09 S1-9: pyGLFW drops the rest of a poll after a
    callback raises; a same-poll release was lost and ``keyp`` stuck for a
    caller that catches. The frame re-reads keys and buttons from the OS."""

    def test_a_tap_whose_press_raised_does_not_stick(self):
        from unittest import mock
        import scena.orchestration as orch
        from scena import keyp
        with system_world(draw=False) as w, input_driver(w) as d:
            cm = w.fw.canvas_manager
            saved = cm.on_key_down

            def boom(key):
                raise RuntimeError("author bug in on_key_down")

            def poll():
                # GLFW delivers the press; pyGLFW drops the release after
                # the raise (it never reaches the framework).
                d.press(glfw.KEY_SPACE)

            cm.on_key_down = boom
            try:
                with mock.patch.object(orch.glfw, "poll_events", poll), \
                        mock.patch.object(orch.glfw, "get_key", lambda _w, _k: glfw.RELEASE), \
                        mock.patch.object(orch.glfw, "get_mouse_button",
                                          lambda _w, _b: glfw.RELEASE):
                    with self.assertRaises(RuntimeError):
                        w.step(1)
            finally:
                cm.on_key_down = saved
            w.step(2)
            self.assertFalse(keyp("SPACE"), "the key the OS reports up stays held")



class TestKeyStreamsFollowTheScriptDown(unittest.TestCase):
    """Review 2026-10-09 W-P4: ``on_key`` repeats follow the same door as the
    up; a key pressed under a modal sends nothing once the mask lifts."""

    def test_no_repeat_for_a_key_pressed_under_a_modal(self):
        with system_world(draw=False) as w, input_driver(w) as d:
            cm = w.fw.canvas_manager
            wm = w.fw.widget_manager
            log = []
            saved = (cm.on_key_down, cm.on_key, cm.on_key_up)
            cm.on_key_down = lambda k: log.append(("down", k))
            cm.on_key = lambda k: log.append(("key", k))
            cm.on_key_up = lambda k: log.append(("up", k))
            try:
                mb = Button(label="M")
                wm.push_modal(mb)
                w.step(1)
                d.press(glfw.KEY_A)
                w.step(1)
                mb.destroy()
                w.step(1)
                d.key(glfw.KEY_A, glfw.REPEAT)
                w.step(1)
                d.release(glfw.KEY_A)
                w.step(1)
                self.assertEqual(log, [])
                d.press(glfw.KEY_A)                  # a fresh press: the full stream
                d.key(glfw.KEY_A, glfw.REPEAT)
                d.release(glfw.KEY_A)
                w.step(1)
                self.assertEqual([e[0] for e in log], ["down", "key", "key", "up"])
            finally:
                cm.on_key_down, cm.on_key, cm.on_key_up = saved


class TestALostReleaseEndsTheDrag(unittest.TestCase):
    """Review 2026-10-09 W-P5: the S1-9 recovery ends every press owner."""

    def test_drag_and_hold_end_with_the_button(self):
        from unittest import mock
        import scena.orchestration as orch
        with system_world(draw=False) as w, input_driver(w) as d:
            sm = w.fw.shape_manager
            sm.drag_threshold = 1.0
            c = Circle(center=(200, 150), radius=30)
            c.draggable = True
            patrol = c.move_by(0, 300, time=3)
            boom = {"on": False}

            def over(*a):
                if boom["on"]:
                    raise RuntimeError("author bug in on_drag_over")
            c.on_drag_over = over
            d.move(200, 150)
            w.step(1)
            d.down()
            w.step(1)
            d.move(210, 150)
            w.step(1)
            self.assertTrue(sm._dragging, "not vacuous")
            boom["on"] = True

            def poll():
                d.move(220, 150)                     # raises: the release is lost
                d.up()

            with mock.patch.object(orch.glfw, "poll_events", poll), \
                    mock.patch.object(orch.glfw, "get_mouse_button",
                                      lambda _w, _b: glfw.RELEASE), \
                    mock.patch.object(orch.glfw, "get_key", lambda _w, _k: glfw.RELEASE):
                with self.assertRaises(RuntimeError):
                    w.step(1)
            boom["on"] = False
            self.assertFalse(sm._dragging)
            self.assertFalse(patrol._held)
            d.move(400, 300)
            w.step(5)
            self.assertGreater(abs(c.center.x - 400), 30, "the shape follows the bare cursor")
            patrol.cancel()
            c.destroy()



class TestTheDragIsALevel(unittest.TestCase):
    """Review 2026-10-09 W-P3 (decided): a held shape stays under a still
    cursor whatever ``update`` writes to it."""

    def test_a_per_frame_move_by_does_not_walk_it_off(self):
        with system_world(draw=False) as w, input_driver(w) as d:
            ball = Circle(center=(200, 150), radius=20)
            ball.draggable = True
            w.step(1)
            d.move(200, 150)
            w.step(1)
            d.down()
            d.move(210, 150)
            w.step(1)
            self.assertTrue(w.fw.shape_manager._dragging, "not vacuous")
            gap0 = ball.center.y - mouse.y
            w.on_update(lambda dt: ball.move_by(0, -300 * dt))
            w.step(30)
            self.assertAlmostEqual(ball.center.y - mouse.y, gap0, places=6)
            w.on_update(None)
            d.up()
            w.step(1)
            ball.move_by(0, -10)                    # released: author writes win again
            w.step(1)
            self.assertAlmostEqual(ball.center.y - mouse.y, gap0 - 10, places=6)
            ball.destroy()


if __name__ == "__main__":
    unittest.main()
