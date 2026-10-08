"""
Hover is a level resolved once per frame (``ShapeInteractionManager.step_hover``).

Bug class guarded here: *event-driven level state goes stale*. Hover used to
be recomputed only on mouse events, so ``pointer_hover`` stayed True after
``visible = False`` / ``clickable = False`` / destroy / the shape moving away,
and a new target on top never took it. See Shapes Design, Hover, and Testing
Design (bug catalogue).

Tiered contract (tested): a full hit test runs when the pointer, the pointer
targets (``registry._pointer_epoch``) or the layer stack changed; otherwise
only the current target is re-checked. Documented trade-off (tested): a
*different* shape sliding under a still pointer is found when it next moves.

Run headless:

    python -m unittest tests.test_pointer_hover -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.canvas import ScenaCanvas
from scena.orchestration import ShapeInteractionManager
from scena.shapes import Circle, Rect


def _canvas():
    return ScenaCanvas.get_current()


def _registry():
    return _canvas().registry


class HoverTestCase(unittest.TestCase):
    """Each test owns its shapes; a unique patch keeps leftovers from colliding."""

    _origin = 50_000

    def setUp(self):
        self.sim = ShapeInteractionManager(_registry())
        self._owned = []
        HoverTestCase._origin += 2000
        self.origin = HoverTestCase._origin

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, shape):
        self._owned.append(shape)
        return shape

    def at(self, x, y):
        return (self.origin + x, self.origin + y)

    def clickable_circle(self, x=0, y=0, **kw):
        c = self.track(Circle(center=self.at(x, y), radius=30, **kw))
        c.clickable = True
        return c

    def point(self, x=0, y=0):
        """Move the (world) pointer and run one frame's hover step."""
        self.sim.note_pointer(world_xy=self.at(x, y))
        self.sim.step_hover()

    def frame(self):
        """One frame with a still pointer."""
        self.sim.step_hover()


class TestStaleness(HoverTestCase):
    """Every way out of hover is seen on the next frame, pointer still."""

    def test_hidden_loses_hover(self):
        c = self.clickable_circle()
        self.point()
        self.assertTrue(c.pointer_hover)
        c.visible = False
        self.frame()
        self.assertFalse(c.pointer_hover)

    def test_unclickable_loses_hover(self):
        c = self.clickable_circle()
        self.point()
        c.clickable = False
        self.frame()
        self.assertFalse(c.pointer_hover)

    def test_flag_flip_keeping_membership_re_resolves(self):
        # clickable off while draggable stays on: still a target, still hovered.
        c = self.clickable_circle()
        c.draggable = True
        self.point()
        c.clickable = False
        self.frame()
        self.assertTrue(c.pointer_hover)

    def test_destroyed_loses_hover_at_once(self):
        c = self.clickable_circle()
        self.point()
        self.assertIs(self.sim._hover_target, c)
        c.destroy()
        self.assertIsNone(self.sim._hover_target)
        self.assertFalse(c._pointer_hover)

    def test_moved_away_loses_hover_with_still_pointer(self):
        c = self.clickable_circle()
        self.point()
        c.move_to(*self.at(500, 500))
        self.frame()
        self.assertFalse(c.pointer_hover)

    def test_new_target_on_top_takes_hover(self):
        a = self.clickable_circle()
        self.point()
        b = self.clickable_circle()  # later in paint order = on top
        self.frame()
        self.assertTrue(b.pointer_hover)
        self.assertFalse(a.pointer_hover)

    def test_move_to_front_takes_hover(self):
        a = self.clickable_circle()
        b = self.clickable_circle()
        self.point()
        self.assertTrue(b.pointer_hover)
        a.move_to_front()
        self.frame()
        self.assertTrue(a.pointer_hover)
        self.assertFalse(b.pointer_hover)

    def test_hidden_layer_loses_hover(self):
        from scena import canvas
        layer = canvas.layers.create("hover_probe", z=5)
        try:
            top = self.clickable_circle(layer="hover_probe")
            under = self.clickable_circle()
            self.point()
            self.assertTrue(top.pointer_hover)
            layer.visible = False
            self.frame()
            self.assertFalse(top.pointer_hover)
            self.assertTrue(under.pointer_hover)
        finally:
            for s in list(self._owned):
                s.destroy()
            self._owned.clear()
            layer.delete()

    def test_world_pointer_change_re_resolves(self):
        # A camera pan moves the world pointer under a still cursor; the frame
        # sample (note_pointer) is enough, no mouse event needed.
        c = self.clickable_circle(200, 0)
        self.point()
        self.assertFalse(c.pointer_hover)
        self.sim.note_pointer(world_xy=self.at(200, 0))
        self.frame()
        self.assertTrue(c.pointer_hover)

    def test_decorative_shape_never_hovers_and_does_not_block(self):
        under = self.clickable_circle()
        label = self.track(Rect(p1=self.at(-50, -50), p2=self.at(50, 50)))
        self.point()
        self.assertFalse(label.pointer_hover)
        self.assertTrue(under.pointer_hover)


class TestTradeOff(HoverTestCase):
    """Entry under a still pointer waits for pointer motion (documented)."""

    def test_shape_sliding_under_still_pointer_waits_for_motion(self):
        c = self.clickable_circle(500, 0)
        self.point()
        c.move_to(*self.at(0, 0))
        self.frame()
        self.assertFalse(c.pointer_hover)
        self.point(1, 0)
        self.assertTrue(c.pointer_hover)


class TestPress(HoverTestCase):
    def test_pressed_shape_keeps_hover_then_re_resolves(self):
        from scena.input import Mouse
        c = self.clickable_circle()
        c.draggable = True
        self.point()
        x, y = self.at(0, 0)
        self.assertTrue(self.sim.handle_mouse_down(x, y, Mouse.BTN_LEFT))
        self.sim.handle_mouse_move(x + 200, y)
        self.frame()
        self.assertTrue(c.pointer_hover)  # dragged along, affordance kept
        self.sim.handle_mouse_up(x + 200, y, Mouse.BTN_LEFT)
        self.frame()
        self.assertTrue(c.pointer_hover)  # still under the pointer
        c.move_to(*self.at(900, 900))
        self.frame()
        self.assertFalse(c.pointer_hover)

    def test_modal_clears_hover(self):
        c = self.clickable_circle()
        self.point()
        self.sim.step_hover(modal=True)
        self.assertFalse(c.pointer_hover)
        self.frame()
        self.assertTrue(c.pointer_hover)

    def test_widget_over_clears_shape_hover(self):
        c = self.clickable_circle()
        self.point()
        widget = object()
        self.sim.step_hover(widget_over=widget)
        self.assertFalse(c.pointer_hover)
        self.assertIs(self.sim._hover_target, widget)
        self.frame()
        self.assertTrue(c.pointer_hover)


class TestCost(HoverTestCase):
    """Tiered: a still frame costs at most one contains_point."""

    def test_still_frame_is_o1(self):
        grid = [self.clickable_circle(i % 25 * 70, i // 25 * 70) for i in range(200)]
        self.point(5 * 70, 3 * 70)
        hovered = self.sim._hover_target
        self.assertIsNotNone(hovered)
        calls = []
        real = ShapeInteractionManager._hit_test.__func__

        def spy(cls, *a, **k):
            calls.append("full")
            return real(cls, *a, **k)

        ShapeInteractionManager._hit_test = classmethod(spy)
        try:
            for _ in range(10):
                self.frame()
        finally:
            ShapeInteractionManager._hit_test = classmethod(real)
        self.assertEqual(calls, [])
        self.assertIs(self.sim._hover_target, hovered)
        self.assertEqual(len(grid), 200)

    def test_moves_coalesce_to_one_hit_test_per_frame(self):
        self.clickable_circle()
        calls = []
        real = ShapeInteractionManager._hit_test.__func__

        def spy(cls, *a, **k):
            calls.append(1)
            return real(cls, *a, **k)

        ShapeInteractionManager._hit_test = classmethod(spy)
        try:
            for i in range(10):
                self.sim.handle_mouse_move(*self.at(i, 0))
            self.assertEqual(calls, [])
            self.frame()
        finally:
            ShapeInteractionManager._hit_test = classmethod(real)
        # ui pass (nothing noted in view space) is skipped; one world pass.
        self.assertEqual(len(calls), 1)

    def test_empty_space_still_frame_is_free(self):
        self.clickable_circle()
        self.point(900, 900)
        self.assertIsNone(self.sim._hover_target)
        calls = []
        real = ShapeInteractionManager._hit_test.__func__

        def spy(cls, *a, **k):
            calls.append(1)
            return real(cls, *a, **k)

        ShapeInteractionManager._hit_test = classmethod(spy)
        try:
            self.frame()
        finally:
            ShapeInteractionManager._hit_test = classmethod(real)
        self.assertEqual(calls, [])


class TestHitOrder(HoverTestCase):
    """The k-sorted hit order equals the old full paint-order walk."""

    @staticmethod
    def _reference_order(registry):
        out = []
        for layer in registry.layers.iter_hit_order():
            interactive = set(layer._interactive)
            for obj in reversed(layer._objects):
                if obj is not None and obj in interactive:
                    out.append(obj)
        return out

    def test_matches_paint_order_after_edits(self):
        reg = _registry()
        shapes = [self.clickable_circle(i * 5, 0) for i in range(12)]
        deco = [self.track(Circle(center=self.at(i, 9), radius=3)) for i in range(8)]
        shapes[3].move_to_front()
        shapes[7].move_to_back()
        shapes[5].destroy()
        deco[2].destroy()
        shapes[9].clickable = False
        shapes[9].clickable = True
        self.assertEqual(list(reg.iter_interactive_hit_order()),
                         self._reference_order(reg))

    def test_draw_index_set_at_construction(self):
        # Graphic.__init__ used to reset _draw_index to -1 after registration.
        a = self.track(Circle(center=self.at(0, 0), radius=5))
        b = self.track(Circle(center=self.at(0, 0), radius=5))
        layer = _registry().layers[a._layer]
        self.assertIs(layer._objects[a._draw_index], a)
        self.assertIs(layer._objects[b._draw_index], b)


class TestEdges(HoverTestCase):
    """@hover / @hover_exit: exactly one exit per enter, on every way out."""

    def setUp(self):
        super().setUp()
        self.log = []

    def watched(self, x=0, y=0, clickable=True, **kw):
        from scena import hover, hover_exit
        c = self.track(Circle(center=self.at(x, y), radius=30, **kw))
        if clickable:
            c.clickable = True

        @hover(c)
        def enter(shape):
            self.log.append(("enter", shape))

        @hover_exit(c)
        def leave(shape):
            self.log.append(("exit", shape))

        return c

    def assertBalanced(self, shape):
        kinds = [k for k, s in self.log if s is shape]
        self.assertEqual(kinds, ["enter", "exit"] * (len(kinds) // 2))
        self.assertEqual(len(kinds) % 2, 0)

    def test_enter_and_exit_on_pointer(self):
        c = self.watched()
        self.point()
        self.frame()
        self.assertEqual(self.log, [("enter", c)])
        self.point(500, 500)
        self.assertEqual(self.log, [("enter", c), ("exit", c)])

    def test_exit_on_every_way_out(self):
        for way in ("hide", "move", "modal", "widget", "destroy"):
            with self.subTest(way=way):
                self.log.clear()
                c = self.watched()
                self.point()
                if way == "hide":
                    c.visible = False
                    self.frame()
                elif way == "move":
                    c.move_to(*self.at(700, 700))
                    self.frame()
                elif way == "modal":
                    self.sim.step_hover(modal=True)
                elif way == "widget":
                    self.sim.step_hover(widget_over=object())
                elif way == "destroy":
                    c.destroy()
                self.assertEqual([k for k, s in self.log if s is c][-1:], ["exit"])
                self.assertBalanced(c)
                self.sim.step_hover(modal=True)  # park the pointer target
                c.destroy()

    def test_hover_handlers_keep_an_unclickable_shape_a_target(self):
        c = self.watched()
        self.point()
        c.clickable = False
        self.frame()
        self.assertTrue(c.pointer_hover)
        self.assertEqual(self.log, [("enter", c)])

    def test_destroy_exit_sees_a_live_shape(self):
        seen = []
        c = self.watched()
        c.on_hover_exit = lambda shape: seen.append(bool(shape.is_alive) or shape.center)
        self.point()
        c.destroy()
        self.assertEqual(len(seen), 1)

    def test_hover_only_shape_is_click_transparent(self):
        from scena.input import Mouse
        clicks = []
        under = self.clickable_circle()
        under.on_click = lambda shape: clicks.append(shape)
        top = self.watched(clickable=False)
        self.point()
        self.assertTrue(top.pointer_hover)
        self.assertFalse(under.pointer_hover)
        x, y = self.at(0, 0)
        self.assertTrue(self.sim.handle_mouse_down(x, y, Mouse.BTN_LEFT))
        self.sim.handle_mouse_up(x, y, Mouse.BTN_LEFT)
        self.assertEqual(clicks, [under])

    def test_hover_only_over_empty_space_leaves_click_to_script(self):
        from scena.input import Mouse
        self.watched(clickable=False)
        x, y = self.at(0, 0)
        self.assertFalse(self.sim.handle_mouse_down(x, y, Mouse.BTN_LEFT))

    def test_handler_arity(self):
        c = self.clickable_circle()
        c.on_hover = lambda: self.log.append("no-arg")
        self.point()
        self.assertEqual(self.log, ["no-arg"])
        with self.assertRaises(TypeError):
            c.on_hover = lambda a, b: None
        with self.assertRaises(TypeError):
            c.on_click = lambda a, b: None

    def test_subclass_method_hooks(self):
        log = self.log

        class Card(Circle):
            def on_hover(self):
                log.append("enter")

            def on_hover_exit(self):
                log.append("exit")

        card = self.track(Card(center=self.at(0, 0), radius=30))
        self.point()
        self.point(900, 0)
        self.assertEqual(log, ["enter", "exit"])

    def test_act_refuses_hover_hooks(self):
        from scena import Act
        with self.assertRaises(TypeError):
            class Menu(Act):
                def on_hover(self):
                    pass


class TestWidgets(HoverTestCase):
    def test_widget_hover_edges_and_exclusivity(self):
        from scena import Button, hover, hover_exit
        log = []
        b = self.track(Button(label="H"))
        c = self.clickable_circle()

        @hover(b, c)
        def enter(target):
            log.append(("enter", target))

        @hover_exit(b, c)
        def leave(target):
            log.append(("exit", target))

        self.point()
        self.sim.step_hover(widget_over=b)
        self.assertTrue(b.pointer_hover)
        self.assertFalse(c.pointer_hover)
        self.frame()
        self.assertEqual(log, [("enter", c), ("exit", c), ("enter", b), ("exit", b), ("enter", c)])

    def test_button_click_payload(self):
        from scena import Button
        got = []
        b0 = self.track(Button(label="0", on_click=lambda: got.append("none")))
        b1 = self.track(Button(label="1", on_click=lambda btn: got.append(btn)))
        for b in (b0, b1):
            b._on_mouse_click(0, 0, 0)
        self.assertEqual(got, ["none", b1])

    def test_button_click_arity_refused_at_ctor_and_setter(self):
        from scena import Button
        with self.assertRaises(TypeError):
            Button(label="x", on_click=lambda a, b: None)
        b = self.track(Button(label="y"))
        with self.assertRaises(TypeError):
            b.on_click = lambda a, b: None

    def test_value_widget_has_no_on_click(self):
        from scena import CheckBox, click
        box = self.track(CheckBox())
        with self.assertRaises(TypeError) as err:
            box.on_click = lambda: None
        self.assertIn("@on_change(checkbox.data)", str(err.exception))
        with self.assertRaises(TypeError):
            @click(box)
            def pressed():
                pass

    def test_drag_refuses_widgets(self):
        from scena import Button, drag_to
        b = self.track(Button(label="d"))
        with self.assertRaises(TypeError):
            @drag_to(b)
            def dragged(a, b_, pos):
                pass

    def test_one_handler_for_shape_and_button(self):
        from scena import Button, click
        from scena.input import Mouse
        got = []
        b = self.track(Button(label="s"))
        c = self.clickable_circle()

        @click(c, b)
        def pressed(target):
            got.append(target)

        x, y = self.at(0, 0)
        self.sim.handle_mouse_down(x, y, Mouse.BTN_LEFT)
        self.sim.handle_mouse_up(x, y, Mouse.BTN_LEFT)
        b._on_mouse_click(0, 0, Mouse.BTN_LEFT)
        self.assertEqual(got, [c, b])


class TestCallTruncated(unittest.TestCase):
    def test_varargs_receive_everything(self):
        from scena.validate import call_truncated
        got = []
        call_truncated(lambda *a: got.append(a), 1, 2)
        call_truncated(lambda a: got.append(a), 1, 2)
        call_truncated(lambda: got.append("none"), 1, 2)
        self.assertEqual(got, [(1, 2), 1, "none"])


if __name__ == "__main__":
    unittest.main()
