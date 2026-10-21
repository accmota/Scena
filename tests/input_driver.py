"""Real input inside real frames, headless.

``SystemWorld`` stubs ``glfw.poll_events``, so no system test ran an input
callback through the framework's own GLFW handlers (review 2026-10-09). This
driver patches ``glfw.get_cursor_pos`` to a mutable cursor, gives the
framework a sentinel window (so the per-frame ``_sync_pointer_level`` runs as
in a real run) and delivers events by calling the handlers directly between
``w.step()`` calls — they land in the next frame, as events of its poll do.

The OS level follows the events: ``glfw.get_key`` / ``glfw.get_mouse_button``
report the keys and buttons the driver pressed and has not released (a
TextInput reads Shift that way for Shift+click), and ``type_text`` sends
characters through the framework's char callback.

    with system_world(draw=False) as w, input_driver(w) as d:
        d.move(100, 100)        # a motion callback to view point (100, 100)
        w.step(1)
"""
from __future__ import annotations

import contextlib
from unittest import mock

import glfw

import scena.orchestration as orch


# Characters ``type_text`` can type, by the GLFW key that types them.
_CHAR_KEYS = {c: getattr(glfw, "KEY_" + c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"}
_CHAR_KEYS.update({str(i): getattr(glfw, f"KEY_{i}") for i in range(10)})
_CHAR_KEYS[" "] = glfw.KEY_SPACE

# The ``mods`` bit of each modifier key: an event carries the modifiers held
# (as after it, the macOS reading), as the OS sends them.
_MOD_BITS = {
    glfw.KEY_LEFT_SHIFT: glfw.MOD_SHIFT, glfw.KEY_RIGHT_SHIFT: glfw.MOD_SHIFT,
    glfw.KEY_LEFT_CONTROL: glfw.MOD_CONTROL, glfw.KEY_RIGHT_CONTROL: glfw.MOD_CONTROL,
    glfw.KEY_LEFT_ALT: glfw.MOD_ALT, glfw.KEY_RIGHT_ALT: glfw.MOD_ALT,
    glfw.KEY_LEFT_SUPER: glfw.MOD_SUPER, glfw.KEY_RIGHT_SUPER: glfw.MOD_SUPER,
}


class InputDriver:
    def __init__(self, fw) -> None:
        self.fw = fw
        self.cur = (0.0, 0.0)          # GLFW window points
        self.held_keys: set = set()    # GLFW key codes down (``glfw.get_key``)
        self.held_buttons: set = set()  # GLFW buttons down (``glfw.get_mouse_button``)

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

    def held_mods(self) -> int:
        """The ``mods`` bits of the modifier keys held now."""
        mods = 0
        for code in self.held_keys:
            mods |= _MOD_BITS.get(code, 0)
        return mods

    def down(self, button: int = glfw.MOUSE_BUTTON_LEFT) -> None:
        self.held_buttons.add(button)
        self.fw._handle_mouse_button(self.fw._window, button, glfw.PRESS, self.held_mods())

    def up(self, button: int = glfw.MOUSE_BUTTON_LEFT) -> None:
        self.held_buttons.discard(button)
        self.fw._handle_mouse_button(self.fw._window, button, glfw.RELEASE, self.held_mods())

    def key(self, glfw_key: int, action: int, mods: int = 0) -> None:
        if action == glfw.PRESS:
            self.held_keys.add(glfw_key)
        elif action == glfw.RELEASE:
            self.held_keys.discard(glfw_key)
        self.fw._handle_key(self.fw._window, glfw_key, 0, action, mods | self.held_mods())

    def press(self, glfw_key: int, mods: int = 0) -> None:
        self.key(glfw_key, glfw.PRESS, mods)

    def release(self, glfw_key: int, mods: int = 0) -> None:
        self.key(glfw_key, glfw.RELEASE, mods)

    def char(self, ch: str) -> None:
        """A char callback (the text a key typed)."""
        self.fw._handle_char(self.fw._window, ord(ch))

    def type_text(self, text: str) -> None:
        """Type ``text`` as the OS does: per character, key down, char, key up."""
        for ch in text:
            code = _CHAR_KEYS[ch.lower()]
            self.press(code)
            self.char(ch)
            self.release(code)

    def _get_key(self, _window, glfw_key: int) -> int:
        return glfw.PRESS if glfw_key in self.held_keys else glfw.RELEASE

    def _get_mouse_button(self, _window, button: int) -> int:
        return glfw.PRESS if button in self.held_buttons else glfw.RELEASE


@contextlib.contextmanager
def input_driver(world):
    fw = world.fw
    d = InputDriver(fw)
    saved = fw._window
    patches = (
        mock.patch.object(orch.glfw, "get_cursor_pos", new=lambda _w: d.cur),
        mock.patch.object(orch.glfw, "get_key", new=d._get_key),
        mock.patch.object(orch.glfw, "get_mouse_button", new=d._get_mouse_button),
    )
    for p in patches:
        p.start()
    fw._window = object()
    try:
        yield d
    finally:
        fw._window = saved
        for p in reversed(patches):
            p.stop()
