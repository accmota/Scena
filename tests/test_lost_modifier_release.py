"""A modifier whose release the OS took away (bug IN3).

A macOS screenshot (Cmd+Shift+4) or another app's hotkey grabs the keyboard
while Cmd is down, and Cmd goes up there: the window never gets the release.
``keyp`` held Cmd for good, and a held Cmd hides every bare play key, so no
key worked again (``examples/affinity.py``: UP, DOWN, SPACE, 1 2 3 R T all
dead after a screenshot, also after clicking the window).

Every key and button event carries the modifiers as the OS has them
(``mods``); a family it reports up is released, with its ``on_key_up``
(law I1). On macOS GLFW still holds the key, so the next press of it
arrives as a release with the flag set: it is read as the press it is.

    python tests/run_tiers.py focused test_lost_modifier_release
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glfw  # noqa: E402

import scena.orchestration as orch  # noqa: E402
from scena import keyp  # noqa: E402
from tests.input_driver import input_driver  # noqa: E402
from tests.system_support import system_world  # noqa: E402
from tests.test_input_streams import script_hooks  # noqa: E402

# Each physical modifier, its Scena family and its ``mods`` bit.
MODIFIERS = [
    (glfw.KEY_LEFT_SHIFT, "SHIFT", glfw.MOD_SHIFT),
    (glfw.KEY_RIGHT_SHIFT, "SHIFT", glfw.MOD_SHIFT),
    (glfw.KEY_LEFT_CONTROL, "CTRL", glfw.MOD_CONTROL),
    (glfw.KEY_RIGHT_CONTROL, "CTRL", glfw.MOD_CONTROL),
    (glfw.KEY_LEFT_ALT, "ALT", glfw.MOD_ALT),
    (glfw.KEY_RIGHT_ALT, "ALT", glfw.MOD_ALT),
    (glfw.KEY_LEFT_SUPER, "CMD", glfw.MOD_SUPER),
    (glfw.KEY_RIGHT_SUPER, "CMD", glfw.MOD_SUPER),
]


def key(w, code, action, mods=0):
    """A raw GLFW key event: the mods as the OS reports them, nothing added."""
    w.fw._handle_key(w.fw._window, code, 0, action, mods)


def button(w, action, mods=0):
    w.fw._handle_mouse_button(w.fw._window, glfw.MOUSE_BUTTON_LEFT, action, mods)


# Each event that reports the modifiers up after the lost release.
EVENTS = {
    "a play key press": lambda w: key(w, glfw.KEY_UP, glfw.PRESS),
    "a play key repeat": lambda w: key(w, glfw.KEY_UP, glfw.REPEAT),
    "a play key release": lambda w: key(w, glfw.KEY_UP, glfw.RELEASE),
    "an unnamed key": lambda w: key(w, glfw.KEY_KP_1, glfw.PRESS),
    "a click": lambda w: button(w, glfw.PRESS),
    "a button up": lambda w: button(w, glfw.RELEASE),
}


class TestKeysWorkAfterAScreenshot(unittest.TestCase):
    """The repro: Cmd+Shift+4 with no release, then the game's keys."""

    def _screenshot(self, w):
        key(w, glfw.KEY_LEFT_SUPER, glfw.PRESS, glfw.MOD_SUPER)
        key(w, glfw.KEY_LEFT_SHIFT, glfw.PRESS, glfw.MOD_SUPER | glfw.MOD_SHIFT)
        # The system takes the 4 and both releases.

    def test_held_and_once_keys_answer_again(self):
        reads = []
        with system_world(draw=False) as w, input_driver(w):
            w.on_update(lambda dt: reads.append((keyp("UP"), keyp.once("1"))))
            self._screenshot(w)
            w.step(1)
            key(w, glfw.KEY_UP, glfw.PRESS)
            key(w, glfw.KEY_1, glfw.PRESS)
            w.step(1)
            w.on_update(None)
        self.assertEqual(reads[-1], (True, True))
        self.assertFalse(keyp("CMD"))
        self.assertFalse(keyp("SHIFT"))

    def test_the_lost_ups_reach_the_script_once(self):
        log = []
        with system_world(draw=False) as w, input_driver(w):
            with script_hooks(w, on_key_down=lambda k: log.append(("down", str(k))),
                              on_key_up=lambda k: log.append(("up", str(k)))):
                self._screenshot(w)
                key(w, glfw.KEY_UP, glfw.PRESS)
                key(w, glfw.KEY_UP, glfw.RELEASE)
                w.step(1)
        self.assertEqual(sorted(log[:4]), sorted([("down", "CMD"), ("down", "SHIFT"),
                                                  ("up", "CMD"), ("up", "SHIFT")]))
        self.assertEqual(log[4:], [("down", "UP"), ("up", "UP")])

    def test_a_click_frees_the_keys_too(self):
        with system_world(draw=False) as w, input_driver(w):
            self._screenshot(w)
            button(w, glfw.PRESS)
            button(w, glfw.RELEASE)
            self.assertFalse(keyp("CMD"))


class TestEveryModifierEveryEvent(unittest.TestCase):
    """Class guard: each modifier lost × each event that reports it up."""

    def test_matrix(self):
        for code, family, bit in MODIFIERS:
            for label, event in EVENTS.items():
                with self.subTest(family=family, key=code, event=label):
                    ups = []
                    with system_world(draw=False) as w, input_driver(w):
                        with script_hooks(w, on_key_up=lambda k: ups.append(str(k))):
                            key(w, code, glfw.PRESS, bit)
                            self.assertTrue(keyp(family))
                            event(w)
                            self.assertFalse(keyp(family))
                            self.assertEqual(ups, [family])
                            # The release that comes later is no second up.
                            key(w, code, glfw.RELEASE, 0)
                            self.assertEqual(ups, [family])

    def test_a_modifier_still_held_stays(self):
        for code, family, bit in MODIFIERS:
            with self.subTest(family=family, key=code):
                with system_world(draw=False) as w, input_driver(w):
                    key(w, code, glfw.PRESS, bit)
                    key(w, glfw.KEY_Z, glfw.PRESS, bit)
                    button(w, glfw.PRESS, bit)
                    self.assertTrue(keyp(family))
                    self.assertTrue(keyp(f"{family}+Z"))

    def test_another_family_s_event_does_not_drop_it(self):
        # A modifier's own event says nothing of the others (X11 reports the
        # state before it): Ctrl pressed with mods 0 keeps Cmd.
        with system_world(draw=False) as w, input_driver(w):
            key(w, glfw.KEY_LEFT_SUPER, glfw.PRESS, glfw.MOD_SUPER)
            key(w, glfw.KEY_LEFT_CONTROL, glfw.PRESS, 0)
            self.assertTrue(keyp("CMD"))
            self.assertTrue(keyp("CTRL"))


class TestTheNextPressAfterALostRelease(unittest.TestCase):
    """macOS: GLFW still holds the key; its next press arrives as a release."""

    def test_read_as_a_press_on_macos(self):
        log = []
        with mock.patch.object(orch, "_COCOA_KEY_MODS", True), \
                system_world(draw=False) as w, input_driver(w):
            with script_hooks(w, on_key_down=lambda k: log.append(("down", str(k))),
                              on_key_up=lambda k: log.append(("up", str(k)))):
                key(w, glfw.KEY_LEFT_SUPER, glfw.PRESS, glfw.MOD_SUPER)
                key(w, glfw.KEY_UP, glfw.PRESS)                 # Cmd dropped
                key(w, glfw.KEY_UP, glfw.RELEASE)
                log.clear()
                key(w, glfw.KEY_LEFT_SUPER, glfw.RELEASE, glfw.MOD_SUPER)  # the press
                self.assertTrue(keyp("CMD"))
                key(w, glfw.KEY_Z, glfw.PRESS, glfw.MOD_SUPER)
                self.assertTrue(keyp("CMD+Z"))
                key(w, glfw.KEY_Z, glfw.RELEASE, glfw.MOD_SUPER)
                key(w, glfw.KEY_LEFT_SUPER, glfw.RELEASE, 0)    # the real release
                self.assertFalse(keyp("CMD"))
        # Z under Cmd is a chord: keyp sees it, on_key_down does not.
        self.assertEqual(log, [("down", "CMD"), ("up", "CMD")])

    def test_left_up_under_a_held_right_is_a_release(self):
        with mock.patch.object(orch, "_COCOA_KEY_MODS", True), \
                system_world(draw=False) as w, input_driver(w):
            key(w, glfw.KEY_LEFT_SUPER, glfw.PRESS, glfw.MOD_SUPER)
            key(w, glfw.KEY_RIGHT_SUPER, glfw.PRESS, glfw.MOD_SUPER)
            key(w, glfw.KEY_LEFT_SUPER, glfw.RELEASE, glfw.MOD_SUPER)
            self.assertEqual(set(w.fw.keys._pressed_keys), {"RIGHT_CMD"})

    def test_elsewhere_an_orphan_release_is_ignored(self):
        # X11 reports a modifier's own release with the state before it: an
        # orphan release with the bit set must not make the key stick.
        with mock.patch.object(orch, "_COCOA_KEY_MODS", False), \
                system_world(draw=False) as w, input_driver(w):
            key(w, glfw.KEY_LEFT_SUPER, glfw.RELEASE, glfw.MOD_SUPER)
            self.assertFalse(keyp("CMD"))


if __name__ == "__main__":
    unittest.main()
