"""Who owns an input stream, in real frames (fix pass 2026-10-14, PD1–PD7).

A press opens a stream (repeats, drags, the release); the stream belongs to
whoever got the press, and what the press set is undone when it ends, even
when its owner went away. Each case goes in through the framework's own GLFW
handlers (``tests/input_driver.py``, which also reports held keys and buttons
to ``glfw.get_key`` / ``get_mouse_button`` and types characters) and the
frame body.

* PD1 — a held hold-to-fire ``Button`` destroyed (or its act ended) writes
  ``value_off``, no click;
* PD2 — a press a HUD widget takes is hidden from ``mouse.press``;
* PD3 — an OS key repeat reaches a widget only if it got the press;
* PD4 — widget hover follows the per-frame pointer sample;
* PD5 — a drag drops across the ``ui`` / world spaces;
* PD6 — Shift held does not hide a bare play key;
* PD7 — a key / button held across ``change_act`` gets its up.

``TestStreamOwnershipMatrix`` is the class guard: for every interruption
between a key's press and its release, each repeat and the release reach the
receiver that got the press, and nobody else.

    python tests/run_tiers.py focused test_input_streams
"""
from __future__ import annotations

import contextlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glfw  # noqa: E402

from scena import (  # noqa: E402
    Act, Button, Circle, Menu, Mouse, Rect, Slider, TextInput, canvas, change_act,
    keyp, mouse, st,
)
from tests.input_driver import input_driver  # noqa: E402
from tests.system_support import system_world  # noqa: E402

FRAME = 1 / 60
_HOOKS = ("on_key_down", "on_key_up", "on_key", "on_mouse_down", "on_mouse_up",
          "on_mouse_click", "on_mouse_drag")


@contextlib.contextmanager
def script_hooks(w, **hooks):
    """Top-level script hooks (``on_key_down`` …) for one test, restored after."""
    cm = w.fw.canvas_manager
    saved = {name: getattr(cm, name) for name in _HOOKS}
    try:
        for name, fn in hooks.items():
            setattr(cm, name, fn)
        yield
    finally:
        for name, fn in saved.items():
            setattr(cm, name, fn)


def center(widget):
    b = widget.box
    return b.center.x, b.center.y


class TestAHeldButtonThatLeavesLetsGo(unittest.TestCase):
    """PD1: ``Button(st["firing"])`` held, then destroyed / its act ended:
    the cell reads ``value_off`` (no click), not stuck at ``value_on``."""

    def _hold(self, w, d, b):
        d.move(*center(b))
        w.step(1)
        d.down()
        w.step(1)

    def test_destroyed_while_held(self):
        clicks = []
        with system_world(draw=False) as w, input_driver(w) as d:
            st.firing = False
            fire = Button(st["firing"], label="Fire", on_click=lambda: clicks.append(1))
            w.step(1)
            self._hold(w, d, fire)
            self.assertIs(st.firing, True, "not vacuous: the hold wrote value_on")
            fire.destroy()
            self.assertIs(st.firing, False)
            d.up()
            w.step(1)
            self.assertIs(st.firing, False)
            self.assertEqual(clicks, [])

    def test_custom_value_off(self):
        with system_world(draw=False) as w, input_driver(w) as d:
            st.mode = "idle"
            b = Button(st["mode"], label="Go", value_on="go", value_off="idle")
            w.step(1)
            self._hold(w, d, b)
            self.assertEqual(st.mode, "go")
            b.destroy()
            self.assertEqual(st.mode, "idle")
            d.up()
            w.step(1)

    def test_act_change_while_held(self):
        class Game(Act):
            def setup(self):
                Game.fire = Button(st["firing"], label="Fire")

        class Title(Act):
            pass

        with system_world(draw=False) as w, input_driver(w) as d:
            st.firing = False
            w.begin_game(Game)
            w.step(1)
            self._hold(w, d, Game.fire)
            self.assertIs(st.firing, True)
            change_act(Title)
            w.step(1)
            d.up()
            w.step(1)
            self.assertIs(st.firing, False)

    def test_a_lost_release_lets_go(self):
        # The S1-9 recovery (a poll cut short by an author error) also ends
        # the widget's press.
        from unittest import mock
        import scena.orchestration as orch
        with system_world(draw=False) as w, input_driver(w) as d:
            st.firing = False
            fire = Button(st["firing"], label="Fire")
            w.step(1)
            self._hold(w, d, fire)
            d.held_buttons.clear()                  # the OS reports it up
            boom = mock.patch.object(orch.glfw, "poll_events",
                                     side_effect=RuntimeError("author bug"))
            with boom, self.assertRaises(RuntimeError):
                w.step(1)
            self.assertIs(st.firing, False)
            fire.destroy()

    def test_a_released_button_does_not_write_on_destroy(self):
        with system_world(draw=False) as w, input_driver(w) as d:
            st.firing = False
            fire = Button(st["firing"], label="Fire")
            w.step(1)
            self._hold(w, d, fire)
            d.up()
            w.step(1)
            st.firing = "set by the game"
            fire.destroy()
            self.assertEqual(st.firing, "set by the game")


class TestAWidgetPressIsHiddenFromMousePress(unittest.TestCase):
    """PD2: a paint app reading ``mouse.press`` does not paint under a Slider
    being dragged or a Button held; a press on a shape stays visible."""

    def test_dragging_a_slider_does_not_paint(self):
        dots = []
        with system_world(draw=False) as w, input_driver(w) as d:
            st.size = 5
            size = Slider(st["size"], label="Brush", min_value=1, max_value=20)

            def update(dt):
                if mouse.press(Mouse.BTN_LEFT) or mouse.press():
                    dots.append((mouse.x, mouse.y))
            w.on_update(update)
            w.step(1)
            hx, hy = size._get_handle_pos()
            d.move(hx, hy)
            w.step(1)
            d.down()
            w.step(1)
            for i in range(5):
                d.move(hx + 10 * i, hy)
                w.step(1)
            self.assertNotEqual(st.size, 5, "not vacuous: the slider moved")
            self.assertIsNone(mouse.click_pos(Mouse.BTN_LEFT))
            d.up()
            w.step(1)
            self.assertEqual(dots, [])
            d.move(300, 150)                         # the canvas: paints again
            d.down()
            w.step(2)
            self.assertEqual(len(dots), 2)
            self.assertEqual(mouse.click_pos(Mouse.BTN_LEFT), (mouse.x, mouse.y))
            d.up()
            w.on_update(None)
            size.destroy()

    def test_a_held_button_hides_the_press_until_release(self):
        with system_world(draw=False) as w, input_driver(w) as d:
            b = Button(label="Clear")
            w.step(1)
            d.move(*center(b))
            d.down()
            w.step(1)
            self.assertTrue(b._pressed, "not vacuous")
            self.assertFalse(mouse.press(Mouse.BTN_LEFT))
            b.destroy()                              # still the widget's press
            w.step(1)
            self.assertFalse(mouse.press(Mouse.BTN_LEFT))
            d.up()
            w.step(1)
            d.down()                                 # nothing there now: visible
            w.step(1)
            self.assertTrue(mouse.press(Mouse.BTN_LEFT))
            d.up()

    def test_a_shape_press_stays_visible(self):
        with system_world(draw=False) as w, input_driver(w) as d:
            c = Circle(center=(200, 150), radius=30)
            c.draggable = True
            w.step(1)
            d.move(200, 150)
            d.down()
            w.step(1)
            self.assertTrue(c.pointer_pressed, "not vacuous: the shape took it")
            self.assertTrue(mouse.press(Mouse.BTN_LEFT))
            d.up()
            c.destroy()


class TestASpriteButtonPressIsHiddenToo(unittest.TestCase):
    """A SpriteButton is a HUD button: a paint app's ``mouse.press`` does not
    paint under a tool icon, enabled or not, on the ui layer or in the world
    under a camera; a plain Sprite with ``on_click`` stays visible (PD2)."""

    ART = None

    @classmethod
    def setUpClass(cls):
        from tests.media_support import media
        cls.ART = media("k-rolling-ball", "button_blue.png")

    def _paint_run(self, make, *, camera=False):
        dots, clicks = [], []
        with system_world(draw=False) as w, input_driver(w) as d:
            if camera:
                canvas.zoom_to(2)
                canvas.pan_to(50, 40)
            tool = make(clicks)
            w.on_update(lambda dt: dots.append(1) if mouse.press(Mouse.BTN_LEFT) else None)
            w.step(1)
            vx, vy = w.fw.world_to_view_coords(tool.center.x, tool.center.y) \
                if tool.layer != "ui" else (tool.center.x, tool.center.y)
            d.move(vx, vy)
            w.step(1)
            d.down()
            w.step(3)
            hidden_click = mouse.click_pos(Mouse.BTN_LEFT)
            d.up()
            w.step(1)
            w.on_update(None)
            tool.destroy()
            if camera:
                canvas.reset_view()
        return dots, clicks, hidden_click

    def test_a_tool_icon_does_not_paint(self):
        from scena import SpriteButton
        dots, clicks, cp = self._paint_run(lambda c: SpriteButton(
            self.ART, center=(60, 60), width=80, on_click=lambda: c.append(1)))
        self.assertEqual(clicks, [1], "not vacuous: the button was clicked")
        self.assertEqual(dots, [])
        self.assertIsNone(cp)

    def test_a_disabled_tool_icon_does_not_paint(self):
        from scena import SpriteButton
        dots, clicks, _cp = self._paint_run(lambda c: SpriteButton(
            self.ART, center=(60, 60), width=80, enabled=False, on_click=lambda: c.append(1)))
        self.assertEqual(clicks, [])
        self.assertEqual(dots, [])

    def test_a_world_button_under_a_camera_does_not_paint(self):
        from scena import SpriteButton
        dots, clicks, _cp = self._paint_run(lambda c: SpriteButton(
            self.ART, center=(80, 60), width=60, layer="default",
            on_click=lambda: c.append(1)), camera=True)
        self.assertEqual(clicks, [1], "not vacuous: the button was clicked")
        self.assertEqual(dots, [])

    def test_a_clickable_sprite_stays_visible(self):
        from scena import Sprite

        def make(c):
            s = Sprite(self.ART, center=(60, 60), width=80)
            s.on_click = lambda *_: c.append(1)
            return s
        dots, clicks, _cp = self._paint_run(make)
        self.assertEqual(clicks, [1], "not vacuous: the sprite was clicked")
        self.assertEqual(len(dots), 3)


class TestARepeatFollowsItsPress(unittest.TestCase):
    """PD3: holding Enter that submits one box, whose ``on_submit`` focuses
    the next box (or changes act to one that does), does not submit the next
    box empty on the OS auto-repeat."""

    def test_on_submit_focuses_the_next_box(self):
        got = []
        with system_world(draw=False) as w, input_driver(w) as d:
            st.nome = ""
            st.resp = ""
            resp = TextInput(st["resp"], on_submit=got.append)
            nome = TextInput(st["nome"], on_submit=lambda v: resp.focus())
            w.step(1)
            nome.focus()
            d.type_text("ana")
            d.press(glfw.KEY_ENTER)
            w.step(1)
            self.assertEqual(st.nome, "ana")
            self.assertTrue(resp._has_focus, "not vacuous: focus moved")
            for _ in range(3):
                d.key(glfw.KEY_ENTER, glfw.REPEAT)
                w.step(1)
            d.release(glfw.KEY_ENTER)
            w.step(1)
            self.assertEqual(got, [])
            d.type_text("ok")                         # a fresh Enter submits
            d.press(glfw.KEY_ENTER)
            d.release(glfw.KEY_ENTER)
            w.step(1)
            self.assertEqual(got, ["ok"])

    def test_on_submit_changes_to_an_act_that_focuses_a_box(self):
        got = []

        class Quiz(Act):
            def setup(self):
                Quiz.box = TextInput(st["resp"], on_submit=got.append)
                Quiz.box.focus()

        class Name(Act):
            def setup(self):
                Name.box = TextInput(st["nome"], on_submit=lambda v: change_act(Quiz))
                Name.box.focus()

        with system_world(draw=False) as w, input_driver(w) as d:
            st.nome = ""
            st.resp = ""
            w.begin_game(Name)
            w.step(1)
            d.type_text("bia")
            d.press(glfw.KEY_ENTER)
            w.step(2)
            self.assertTrue(Quiz.box._has_focus, "not vacuous")
            d.key(glfw.KEY_ENTER, glfw.REPEAT)
            w.step(1)
            d.release(glfw.KEY_ENTER)
            w.step(1)
            self.assertEqual(got, [])

    def test_a_box_keeps_the_repeats_of_its_own_press(self):
        with system_world(draw=False) as w, input_driver(w) as d:
            st.t = ""
            box = TextInput(st["t"])
            w.step(1)
            box.focus()
            d.type_text("abcd")
            d.press(glfw.KEY_BACKSPACE)
            d.key(glfw.KEY_BACKSPACE, glfw.REPEAT)
            d.key(glfw.KEY_BACKSPACE, glfw.REPEAT)
            d.release(glfw.KEY_BACKSPACE)
            w.step(1)
            self.assertEqual(box._text, "a")
            box.destroy()

    def test_a_game_key_held_into_focus_does_not_edit_the_box(self):
        log = []
        with system_world(draw=False) as w, input_driver(w) as d:
            st.t = ""
            box = TextInput(st["t"])
            w.step(1)
            box.focus()
            d.type_text("ab")
            box._give_up_focus()
            with script_hooks(w, on_key=lambda k: log.append(str(k))):
                d.press(glfw.KEY_LEFT)                # the game's press
                box.focus()
                d.key(glfw.KEY_LEFT, glfw.REPEAT)
                d.key(glfw.KEY_LEFT, glfw.REPEAT)
                d.release(glfw.KEY_LEFT)
                w.step(1)
            self.assertEqual(box._cursor_pos, 2, "the box cursor did not move")
            self.assertEqual(log, ["LEFT", "LEFT", "LEFT"])
            box.destroy()

    def test_shift_click_in_a_box_reads_the_os_shift(self):
        # input_driver reports held keys to glfw.get_key (TextInput reads
        # the physical Shift for Shift+click).
        with system_world(draw=False) as w, input_driver(w) as d:
            st.t = "hello"
            box = TextInput(st["t"], width=300)
            w.step(1)
            box.focus()
            d.press(glfw.KEY_LEFT_SHIFT)
            d.move(*center(box))
            d.down()
            d.up()
            d.release(glfw.KEY_LEFT_SHIFT)
            w.step(1)
            self.assertTrue(box._has_focus)
            box.destroy()


class TestWidgetHoverFollowsThePointerSample(unittest.TestCase):
    """PD4: the cursor leaves the window with no motion event: a hovered
    Button gets its exit, as a Graphic does, from the per-frame sample."""

    def test_leaving_the_window_ends_widget_hover(self):
        ev = []
        with system_world(draw=False) as w, input_driver(w) as d:
            btn = Button(label="Play", top_left=(20, 280))
            btn.on_hover = lambda b: ev.append("in")
            btn.on_hover_exit = lambda b: ev.append("out")
            w.step(1)
            cx, cy = center(btn)
            d.move(cx, cy)
            w.step(1)
            self.assertEqual(ev, ["in"])
            d.place(cx, 330)                         # outside, no callback
            w.step(2)
            self.assertEqual(ev, ["in", "out"])
            self.assertFalse(btn.pointer_hover)
            self.assertFalse(btn._is_mouse_over)
            d.place(cx, cy)                          # back in, still no callback
            w.step(1)
            self.assertEqual(ev, ["in", "out", "in"])
            btn.destroy()

    def test_a_pressed_widget_keeps_hover_off_window(self):
        # S3-5 stays: a pressed widget keeps its hover until the release.
        with system_world(draw=False) as w, input_driver(w) as d:
            btn = Button(label="Hold", top_left=(20, 280))
            w.step(1)
            d.move(*center(btn))
            d.down()
            w.step(1)
            d.place(-40, 330)
            w.step(2)
            self.assertTrue(btn.pointer_hover)
            d.up()
            w.step(2)
            self.assertFalse(btn.pointer_hover)
            btn.destroy()


class TestDropsCrossSpaces(unittest.TestCase):
    """PD5: the drop target is the topmost droppable under the cursor, ``ui``
    first, whichever space the drag started in; ``pos`` is in the space of
    the shape whose handler runs."""

    def _drag(self, w, d, start, path):
        d.move(*start)
        w.step(1)
        d.down()
        w.step(1)
        for p in path:
            d.move(*p)
            w.step(1)
        d.up()
        w.step(1)

    def test_a_hud_seed_drops_on_a_world_plot(self):
        log = []
        with system_world(draw=False) as w, input_driver(w) as d:
            w.fw.shape_manager.drag_threshold = 1.0
            canvas.pan_by(50, 0)                     # world ≠ view
            seed = Circle(center=(40, 40), radius=12, layer="ui")
            seed.draggable = True
            seed.on_drag_to = lambda a, b, pos: log.append(("to", b, pos))
            plot = Rect(center=(300, 150), width=80, height=80)
            plot.on_drop_by = lambda a, b, pos: log.append(("drop", b, pos))
            w.step(1)
            vx, vy = w.fw.world_to_view_coords(300, 150)
            self._drag(w, d, (40, 40), [(120, 80), (vx, vy)])
            self.assertEqual([e[0] for e in log], ["to", "drop"])
            (_, to, to_pos), (_, target, drop_pos) = log
            self.assertIs(to, plot)
            self.assertIs(target, plot)
            self.assertAlmostEqual(to_pos[0], vx)          # the seed's (view) space
            self.assertAlmostEqual(drop_pos[0], 300.0)     # the plot's (world) space
            self.assertAlmostEqual(drop_pos[1], 150.0)
            seed.destroy()
            plot.destroy()

    def test_a_world_piece_drops_on_a_hud_bin(self):
        log = []
        with system_world(draw=False) as w, input_driver(w) as d:
            w.fw.shape_manager.drag_threshold = 1.0
            rock = Circle(center=(200, 150), radius=15)
            rock.draggable = True
            over = []
            rock.on_drag_over = lambda a, b, pos: over.append(b)
            trash = Rect(center=(360, 40), width=60, height=60, layer="ui")
            trash.on_drop_by = lambda a, b, pos: log.append(("trash", pos))
            w.step(1)
            self._drag(w, d, (200, 150), [(260, 100), (360, 40)])
            self.assertEqual(log, [("trash", (360.0, 40.0))])
            self.assertIs(over[-1], trash)
            rock.destroy()
            trash.destroy()

    def test_ui_first_over_a_world_target_under_it(self):
        log = []
        with system_world(draw=False) as w, input_driver(w) as d:
            w.fw.shape_manager.drag_threshold = 1.0
            piece = Circle(center=(100, 150), radius=10)
            piece.draggable = True
            floor = Rect(center=(300, 150), width=120, height=120)
            floor.on_drop_by = lambda a, b, pos: log.append("floor")
            hud = Rect(center=(300, 150), width=40, height=40, layer="ui")
            hud.on_drop_by = lambda a, b, pos: log.append("hud")
            w.step(1)
            self._drag(w, d, (100, 150), [(200, 150), (300, 150)])
            self.assertEqual(log, ["hud"])
            for s in (piece, floor, hud):
                s.destroy()


class TestShiftDoesNotBlockABareKey(unittest.TestCase):
    """PD6: "hold Shift to run" keeps ``keyp("RIGHT")`` and the jump."""

    def test_sprint_and_jump_while_shift_is_held(self):
        jumps, downs = [], []
        with system_world(draw=False) as w, input_driver(w) as d:
            hero = Circle(center=(50, 50), radius=8)

            def update(dt):
                speed = 250 if keyp("SHIFT") else 100
                if keyp("RIGHT"):
                    hero.move_by(speed * dt, 0)
                if keyp.once("SPACE"):
                    jumps.append(1)
            w.on_update(update)
            with script_hooks(w, on_key_down=lambda k: downs.append(str(k))):
                d.press(glfw.KEY_RIGHT)
                d.press(glfw.KEY_LEFT_SHIFT, glfw.MOD_SHIFT)
                w.step(1)
                x0 = hero.center.x
                w.step(6)
                d.press(glfw.KEY_SPACE, glfw.MOD_SHIFT)
                w.step(1)
                d.release(glfw.KEY_SPACE, glfw.MOD_SHIFT)
                for code in (glfw.KEY_LEFT_SHIFT, glfw.KEY_RIGHT):
                    d.release(code)
                w.step(1)
            w.on_update(None)
            self.assertAlmostEqual(hero.center.x - x0, 250 * 7 / 60, places=6)
            self.assertEqual(jumps, [1])
            self.assertEqual(downs, ["RIGHT", "SHIFT", "SPACE"])
            hero.destroy()

    def test_ctrl_still_blocks(self):
        downs, reads = [], []
        with system_world(draw=False) as w, input_driver(w) as d:
            w.on_update(lambda dt: reads.append((keyp("R"), keyp("CTRL+R"))))
            with script_hooks(w, on_key_down=lambda k: downs.append(str(k))):
                d.press(glfw.KEY_LEFT_CONTROL, glfw.MOD_CONTROL)
                d.press(glfw.KEY_R, glfw.MOD_CONTROL)
                w.step(1)
                d.release(glfw.KEY_R)
                d.release(glfw.KEY_LEFT_CONTROL)
                w.step(1)
            w.on_update(None)
            self.assertEqual(downs, ["CTRL"])
            self.assertEqual(reads[0], (False, True))


class TestUpsCrossAnActChange(unittest.TestCase):
    """PD7: a key / button held across ``change_act`` gets its up (the
    top-level handler that saw the down lives on); nothing that continues
    the old press — no repeat, drag or click — reaches the new act."""

    class Level(Act):
        pass

    def test_on_key_up_after_the_act_changed(self):
        log = []
        with system_world(draw=False) as w, input_driver(w) as d:
            st.dir = 0

            def down(k):
                log.append(("down", str(k)))
                if k == "RIGHT":
                    st.dir = 1

            def up(k):
                log.append(("up", str(k)))
                if k == "RIGHT":
                    st.dir = 0
            with script_hooks(w, on_key_down=down, on_key_up=up,
                              on_key=lambda k: log.append(("key", str(k)))):
                w.begin_game(self.Level)
                w.step(1)
                d.press(glfw.KEY_RIGHT)
                w.step(3)
                change_act(self.Level)
                w.step(1)
                d.key(glfw.KEY_RIGHT, glfw.REPEAT)   # W-P4: no repeat now
                w.step(1)
                d.release(glfw.KEY_RIGHT)
                w.step(1)
                self.assertEqual(st.dir, 0)
                self.assertEqual(log, [("down", "RIGHT"), ("key", "RIGHT"), ("up", "RIGHT")])
                log.clear()
                d.press(glfw.KEY_RIGHT)              # a fresh press: the full stream
                d.key(glfw.KEY_RIGHT, glfw.REPEAT)
                d.release(glfw.KEY_RIGHT)
                w.step(1)
                self.assertEqual([e[0] for e in log], ["down", "key", "key", "up"])

    def test_on_mouse_up_but_no_click_or_drag_after_the_act_changed(self):
        log = []
        with system_world(draw=False) as w, input_driver(w) as d:
            with script_hooks(
                    w,
                    on_mouse_down=lambda x, y, b: log.append("down"),
                    on_mouse_up=lambda x, y, b, cx, cy: log.append(("up", round(cx))),
                    on_mouse_click=lambda x, y, b: log.append("click"),
                    on_mouse_drag=lambda x, y, b: log.append("drag")):
                w.begin_game(self.Level)
                w.step(1)
                d.move(30, 30)
                d.down()
                w.step(1)
                change_act(self.Level)
                w.step(1)
                d.move(31, 30)
                d.up()
                w.step(1)
                self.assertEqual(log, ["down", ("up", 30)])
                log.clear()
                d.down()
                d.up()
                w.step(1)
                self.assertEqual(log, ["down", ("up", 31), "click"])


class TestStreamOwnershipMatrix(unittest.TestCase):
    """Class guard (PD3 / PD7 / W-P4 / S3-7): whatever happens between a
    key's press and its release, each OS repeat and the release reach the
    receiver that got the press and nobody else; every script down gets
    exactly one up."""

    class Stage(Act):
        pass

    INTERRUPTS = ("nothing", "focus another box", "box loses focus",
                  "box destroyed", "act change", "modal opens")

    def _interrupt(self, how, w, other):
        if how == "focus another box":
            other.focus()
        elif how == "box loses focus":
            w.fw.widget_manager.set_focus(None)
        elif how == "box destroyed":
            first = w.fw.widget_manager.focused_widget
            if first is not None:
                first.destroy()
        elif how == "act change":
            change_act(self.Stage)
        elif how == "modal opens":
            return Menu(options=["Resume"], modal=True)
        return None

    def test_matrix(self):
        for owner in ("script", "box"):
            for how in self.INTERRUPTS:
                with self.subTest(owner=owner, interrupt=how):
                    self._case(owner, how)

    def _case(self, owner, how):
        script, submits = [], []
        with system_world(draw=False) as w, input_driver(w) as d:
            st.a = ""
            st.b = ""
            with script_hooks(w, on_key_down=lambda k: script.append("down"),
                              on_key=lambda k: script.append("key"),
                              on_key_up=lambda k: script.append("up")):
                w.begin_game(self.Stage)
                box = TextInput(st["a"], on_submit=lambda v: submits.append("a"))
                other = TextInput(st["b"], on_submit=lambda v: submits.append("b"))
                w.step(1)
                if owner == "box":
                    box.focus()
                d.press(glfw.KEY_ENTER)
                w.step(1)
                menu = self._interrupt(how, w, other)
                w.step(1)
                d.key(glfw.KEY_ENTER, glfw.REPEAT)
                w.step(1)
                d.release(glfw.KEY_ENTER)
                w.step(1)
                if menu is not None:
                    menu.destroy()
                    w.step(1)
            if owner == "script":
                repeats = 1 if how in ("nothing", "focus another box",
                                       "box loses focus", "box destroyed") else 0
                self.assertEqual(script, ["down", "key"] + ["key"] * repeats + ["up"])
                self.assertEqual(submits, [])
            else:
                # The press submitted "a" (and dropped focus); no repeat
                # reaches a box focused since, nor the script.
                self.assertEqual(script, [])
                self.assertEqual(submits, ["a"])


if __name__ == "__main__":
    unittest.main()
