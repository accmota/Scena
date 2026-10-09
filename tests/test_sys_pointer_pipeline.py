"""Pointer pipeline under every transform: one OS pixel through the window
scale, the letterbox, the camera and the layer kind to the handler that
fires.

Interaction campaign, class 5 (design/Testing Design.md, "Interaction
campaign"). ``test_canvas`` round-trips the mapping as a function;
``test_pointer_hover`` / ``test_shape_interaction`` hit-test at the identity
camera; ``test_ui_layer`` checks ui immunity by calling the hit test. Here the
pixel goes in through the real GLFW handlers (``_handle_mouse_move``,
``_handle_mouse_button``) and the frame body, and the verdict is the handler:

* **display** × **camera** × **target** × **verb**: a world shape under a
  zoomed, panned, rotated, re-origined camera, a shape on the ``ui`` layer
  and a Button (both immune to the camera), hovered, clicked and dragged at
  the pixel their centre maps to; a drag of ``D`` screen pixels moves a
  world shape by the world delta the inverse map gives;
* **not vacuous**: under a non-identity transform the same pixel computed
  without the transform (as if design space were the screen) misses;
* **precedence**: a Button over a world shape takes the hover and the click.

Oracle: the engine's own forward map (``world_to_view_coords``, the view →
screen chain of ``test_canvas``), the inverse for the drag; the handler's
firing is the fact. ``KNOWN`` is shrink-only.

    python -m unittest tests.test_sys_pointer_pipeline -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from typing import Any, Callable, Dict, List, Tuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glfw  # noqa: E402

from diff_support import assert_catches  # noqa: E402
from system_support import SystemTestCase, quiet  # noqa: E402

import scena.orchestration as orch  # noqa: E402
from scena import Button, Circle, canvas, click, drag_to, hover  # noqa: E402

DISPLAYS: Dict[str, Tuple[float, Tuple[float, float]]] = {
    "1:1": (1.0, (0.0, 0.0)),
    "half, pad x": (0.5, (37.0, 0.0)),
    "1.75, pad y": (1.75, (0.0, 21.0)),
}
CAMERAS: Dict[str, Callable[[], None]] = {
    "identity": lambda: None,
    "zoom 2": lambda: canvas.zoom_to(2.0),
    "pan": lambda: canvas.pan_by(60.0, -25.0),
    "rotate 30": lambda: canvas.rotate_to(30.0),
    "origin center, zoom 1.5": lambda: (canvas.set_origin("center"), canvas.zoom_to(1.5)),
    "zoom .5, pan, rotate": lambda: (canvas.zoom_to(0.5), canvas.pan_by(-80.0, 40.0),
                                     canvas.rotate_to(-20.0)),
}
TARGETS = ("world shape", "ui shape", "button")
VERBS = ("hover", "click", "drag")
DRAG_PX = 40.0
WORLD_AT = (120.0, 90.0)
UI_AT = (300.0, 60.0)

# Shrink-only: "display | camera | target | verb" -> reason.
KNOWN: Dict[str, str] = {
}


class Rig:
    """A world with the three targets, the display and camera applied, and a
    cursor the GLFW handlers read."""

    def __init__(self, tc: SystemTestCase, display: str, camera: str) -> None:
        self.tc, self.w = tc, tc.w
        fw = self.fw = tc.w.fw
        self.cursor = [0.0, 0.0]
        p = mock.patch.object(orch.glfw, "get_cursor_pos", new=lambda _w: tuple(self.cursor))
        p.start()
        tc.addCleanup(p.stop)
        self.saved = (fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y)
        vs, (px, py) = DISPLAYS[display]
        fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y = vs, px, py
        canvas.reset_view()
        CAMERAS[camera]()
        self.log: List[Tuple[str, str]] = []
        with quiet():
            self.world = tc.track(Circle(center=WORLD_AT, radius=12))
            self.ui = tc.track(Circle(center=UI_AT, radius=12, layer="ui"))
        self.button = tc.track(Button(label="Pipe", on_click=lambda: self.log.append(("click", "button"))))
        for name, shape in (("world shape", self.world), ("ui shape", self.ui)):
            shape.clickable = True
            shape.draggable = True
            hover(shape)((lambda n: lambda s: self.log.append(("hover", n)))(name))
            click(shape)((lambda n: lambda s, *a: self.log.append(("click", n)))(name))
            drag_to(shape)((lambda n: lambda s, *a: self.log.append(("drag", n)))(name))
        tc.w.step(1)

    def restore(self) -> None:
        fw = self.fw
        with quiet():
            self.release()
            fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y = self.saved
            canvas.reset_view()
            fw.shape_manager.note_pointer(view_xy=(-1e6, -1e6), world_xy=(-1e6, -1e6))
            # The next cell builds its own targets at the same spots: these go.
            for obj in (self.world, self.ui, self.button):
                if obj.is_alive:
                    obj.destroy()
            self.w.step(1)

    # -- the forward map (the engine's own, plus the view -> screen chain) --
    def view_to_screen(self, vx: float, vy: float) -> Tuple[float, float]:
        fw = self.fw
        vs = fw.view_scale
        return (fw._letterbox_pad_x + vx * vs, fw._letterbox_pad_y + (fw.design_height - vy) * vs)

    def screen_of(self, target: str) -> Tuple[float, float]:
        if target == "world shape":
            return self.view_to_screen(*self.fw.world_to_view_coords(*WORLD_AT))
        if target == "ui shape":
            return self.view_to_screen(*UI_AT)
        b = self.button
        return self.view_to_screen((b._x1 + b._x2) / 2.0, (b._y1 + b._y2) / 2.0)

    def naive_screen_of(self, target: str) -> Tuple[float, float]:
        """The pixel as if design space were the screen and the camera identity."""
        fw = self.fw
        if target == "world shape":
            return (WORLD_AT[0], fw.design_height - WORLD_AT[1])
        if target == "ui shape":
            return (UI_AT[0], fw.design_height - UI_AT[1])
        b = self.button
        return ((b._x1 + b._x2) / 2.0, fw.design_height - (b._y1 + b._y2) / 2.0)

    # -- the OS side ---------------------------------------------------------
    def move(self, sx: float, sy: float) -> None:
        self.cursor[:] = [sx, sy]
        self.fw._handle_mouse_move(None, sx, sy)

    def press(self) -> None:
        self.fw._handle_mouse_button(None, glfw.MOUSE_BUTTON_LEFT, glfw.PRESS, 0)

    def release(self) -> None:
        self.fw._handle_mouse_button(None, glfw.MOUSE_BUTTON_LEFT, glfw.RELEASE, 0)

    def do(self, verb: str, sx: float, sy: float) -> None:
        self.move(sx, sy)
        if verb == "hover":
            self.w.step(1)
        elif verb == "click":
            self.press()
            self.w.step(1)
            self.release()
            self.w.step(1)
        elif verb == "drag":
            self.press()
            self.w.step(1)
            self.move(sx + DRAG_PX, sy)
            self.w.step(1)
            self.release()
            self.w.step(1)


class TestPipeline(SystemTestCase, unittest.TestCase):
    world_draw = False
    maxDiff = None

    def _cell(self, display: str, camera: str, target: str, verb: str) -> None:
        rig = Rig(self, display, camera)
        try:
            key = f"{display} | {camera} | {target} | {verb}"
            msgs: List[str] = []
            sx, sy = rig.screen_of(target)
            before = tuple(map(float, (rig.world.center.x, rig.world.center.y)))
            rig.do(verb, sx, sy)
            hits = [t for v, t in rig.log if v == verb]
            if target == "button":
                # A Button has no hover handler and no drag: its hover is the
                # manager's level, a drag is a press and a release (a click).
                if verb == "hover":
                    hits = ["button"] if rig.fw.widget_manager.mouse_over_widget is rig.button else []
                elif verb == "drag":
                    hits = [t for v, t in rig.log if v == "click"]
            if hits != [target]:
                msgs.append(f"{verb} at screen {(round(sx, 2), round(sy, 2))}: handlers fired "
                            f"{rig.log}, want {verb!r} on {target!r} only")
            if verb == "drag" and target == "world shape":
                fw = rig.fw
                ax, ay = fw.screen_to_world_coords(sx, sy)
                bx, by = fw.screen_to_world_coords(sx + DRAG_PX, sy)
                want = (before[0] + (bx - ax), before[1] + (by - ay))
                got = (float(rig.world.center.x), float(rig.world.center.y))
                if math.hypot(got[0] - want[0], got[1] - want[1]) > 1e-3 * (1 + abs(want[0]) + abs(want[1])):
                    msgs.append(f"drag of {DRAG_PX} px moved the shape to {got}, want {want}")
            # Not vacuous: the untransformed pixel misses when the transform is not identity.
            nx, ny = rig.naive_screen_of(target)
            if (display, camera) != ("1:1", "identity") and math.hypot(nx - sx, ny - sy) > 25.0 \
                    and target != "button":
                rig.log.clear()
                rig.release()
                rig.do("hover", nx, ny)
                if any(t == target for _v, t in rig.log):
                    msgs.append(f"the untransformed pixel {(nx, ny)} also hits {target!r}: the "
                                f"pipeline ignores the transform")
            if msgs:
                if key in KNOWN:
                    self.skipTest(f"known: {KNOWN[key]}")
                self.fail(f"{key}:\n  " + "\n  ".join(msgs))
            elif key in KNOWN:
                self.fail(f"KNOWN entry no longer fails; remove it: {key!r}")
        finally:
            rig.restore()

    def _matrix(self, target: str, verb: str) -> None:
        for display in DISPLAYS:
            for camera in CAMERAS:
                with self.subTest(display=display, camera=camera):
                    self._cell(display, camera, target, verb)


for _t in TARGETS:
    for _v in VERBS:
        setattr(TestPipeline, "test_" + "".join(ch if ch.isalnum() else "_" for ch in f"{_t}_{_v}"),
                (lambda t, v: lambda self: self._matrix(t, v))(_t, _v))


class TestPrecedence(SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_a_button_over_a_world_shape_takes_hover_and_click(self):
        for camera in CAMERAS:
            with self.subTest(camera=camera):
                rig = Rig(self, "half, pad x", camera)
                try:
                    b = rig.button
                    bvx, bvy = (b._x1 + b._x2) / 2.0, (b._y1 + b._y2) / 2.0
                    # Put the world shape under the button's pixel.
                    wx, wy = rig.fw.screen_to_world_coords(*rig.view_to_screen(bvx, bvy))
                    rig.world.move_to(wx, wy)
                    rig.w.step(1)
                    sx, sy = rig.screen_of("button")
                    rig.do("hover", sx, sy)
                    rig.do("click", sx, sy)
                    self.assertNotIn(("hover", "world shape"), rig.log, rig.log)
                    self.assertNotIn(("click", "world shape"), rig.log, rig.log)
                    self.assertIn(("click", "button"), rig.log, rig.log)
                finally:
                    rig.restore()


class TestAxes(unittest.TestCase):
    def test_tables(self):
        self.assertIn("identity", CAMERAS)
        self.assertIn("1:1", DISPLAYS)
        for key in KNOWN:
            d, c, t, v = key.split(" | ")
            self.assertIn(d, DISPLAYS); self.assertIn(c, CAMERAS)
            self.assertIn(t, TARGETS); self.assertIn(v, VERBS)


class TestCanaries(unittest.TestCase):
    def test_catches_a_pointer_that_ignores_the_letterbox(self):
        real = orch.ScenaFramework._pointer_from_glfw

        def no_pad(self, gx, gy, _r=real):
            return _r(self, gx - self._letterbox_pad_x, gy - self._letterbox_pad_y)
        assert_catches(self, "test_sys_pointer_pipeline.TestPipeline.test_world_shape_hover",
                       [(orch.ScenaFramework, "_pointer_from_glfw", no_pad)],
                       "a pointer map that drops the letterbox pad")


if __name__ == "__main__":
    unittest.main()
