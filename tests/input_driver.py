"""Real input inside real frames, headless.

``SystemWorld`` stubs ``glfw.poll_events``, so no system test ran an input
callback through the framework's own GLFW handlers (review 2026-10-09). This
driver patches ``glfw.get_cursor_pos`` to a mutable cursor, gives the
framework a sentinel window (so the per-frame ``_sync_pointer_level`` runs as
in a real run) and delivers events by calling the handlers directly between
``w.step()`` calls — they land in the next frame, as events of its poll do.

    with system_world(draw=False) as w, input_driver(w) as d:
        d.move(100, 100)        # a motion callback to view point (100, 100)
        w.step(1)
"""
from __future__ import annotations

import contextlib
from unittest import mock

import glfw

import scena.orchestration as orch


class InputDriver:
    def __init__(self, fw) -> None:
        self.fw = fw
        self.cur = (0.0, 0.0)          # GLFW window points

    def to_screen(self, vx: float, vy: float):
        fw = self.fw
        vs = fw.view_scale or 1.0
        return (fw._letterbox_pad_x + vx * vs, fw._letterbox_pad_y + (fw.design_height - vy) * vs)

    def move(self, vx: float, vy: float) -> None:
        """A motion callback to the VIEW point (vx, vy)."""
        self.cur = self.to_screen(vx, vy)
        self.fw._handle_mouse_move(self.fw._window, *self.cur)

    def place(self, vx: float, vy: float) -> None:
        """The OS cursor is at (vx, vy) with no motion callback (level only)."""
        self.cur = self.to_screen(vx, vy)

    def down(self, button: int = glfw.MOUSE_BUTTON_LEFT) -> None:
        self.fw._handle_mouse_button(self.fw._window, button, glfw.PRESS, 0)

    def up(self, button: int = glfw.MOUSE_BUTTON_LEFT) -> None:
        self.fw._handle_mouse_button(self.fw._window, button, glfw.RELEASE, 0)

    def key(self, glfw_key: int, action: int, mods: int = 0) -> None:
        self.fw._handle_key(self.fw._window, glfw_key, 0, action, mods)

    def press(self, glfw_key: int, mods: int = 0) -> None:
        self.key(glfw_key, glfw.PRESS, mods)

    def release(self, glfw_key: int, mods: int = 0) -> None:
        self.key(glfw_key, glfw.RELEASE, mods)


@contextlib.contextmanager
def input_driver(world):
    fw = world.fw
    d = InputDriver(fw)
    saved = fw._window
    p = mock.patch.object(orch.glfw, "get_cursor_pos", new=lambda _w: d.cur)
    p.start()
    fw._window = object()
    try:
        yield d
    finally:
        fw._window = saved
        p.stop()
