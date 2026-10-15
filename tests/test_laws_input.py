"""Laws campaign, stage S3: input ownership (I laws).

The model (``tests/laws/model/input.py``) reads one record per OS key,
character and button event — the doors it reached while it was handled —
and checks who got what (design/Laws.md, "Input"). Layers:

* the fixture (``tests/laws/fixtures/s3_input.py``) driven like a player at
  OS level (held keys, auto-repeat, characters): a key held across an act
  change, a box that takes its keys, a key pressed before a box took focus,
  a script click, a hold Button destroyed while held;
* synthetic traces: each rule both ways;
* canaries (gate): PD7, an up for a press the script never got, W-P4, LW5
  and a widget that keeps its press after it left, planted in the engine.

    python -m unittest tests.test_laws_input -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import require_canaries  # noqa: E402
from laws import model  # noqa: E402
from laws.harness import drive  # noqa: E402
from laws.model import input as input_model  # noqa: E402
from laws.plants import PLANTS, both_verify_modes  # noqa: E402

S3 = "tests/laws/fixtures/s3_input"

PLAY = [
    ("step", 2),
    # a script key held across an act change (PD7, W-P4)
    ("key_down", "RIGHT"), ("step", 1), ("key_repeat", "RIGHT"), ("step", 1),
    ("key_down", "N"), ("step", 1), ("key_up", "N"), ("step", 1),
    ("key_repeat", "RIGHT"), ("step", 1), ("key_up", "RIGHT"), ("step", 1),
    # focus the box with a click; a key the box takes
    ("press", 100, 265), ("step", 1), ("release",), ("step", 1),
    ("key_down", "A"), ("step", 1), ("key_repeat", "A"), ("step", 1), ("key_up", "A"),
    ("step", 1),
    # unfocus (a script click); B pressed, then F focuses the box (PD3, LW5)
    ("press", 200, 100), ("step", 1), ("release",), ("step", 1),
    ("key_down", "B"), ("step", 1), ("key_down", "F"), ("step", 1), ("key_up", "F"), ("step", 1),
    ("key_repeat", "B"), ("step", 1), ("key_up", "B"), ("step", 1),
    ("press", 200, 100), ("step", 1), ("release",), ("step", 1),
    # hold the Button, destroy it while held (PD1)
    ("press", 280, 265), ("step", 2), ("key_down", "D"), ("step", 1), ("key_up", "D"), ("step", 1),
    ("release",), ("step", 2),
]


class TestFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_, cls.state, cls.rep = drive(S3, PLAY)

    def test_no_finding(self):
        self.assertEqual(self.rep.findings, [], self.rep.summary())

    def test_every_input_law_is_witnessed(self):
        missing = [law for law in input_model.LAWS if not self.rep.witnesses[law]]
        self.assertEqual(missing, [], dict(self.rep.witnesses))

    def test_the_app_did_what_it_does(self):
        s = self.state
        self.assertEqual(s["downs"], s["ups"])          # every script down got its up
        self.assertEqual(s["text"], "a")                 # only the box's own key typed (LW5)
        self.assertFalse(s["firing"])                    # PD1: the held Button let go
        self.assertEqual(s["acts"], 2)
        self.assertEqual((s["mouse_downs"], s["mouse_ups"], s["clicks"]), (2, 2, 2))


# -- synthetic traces ---------------------------------------------------------

def I(kind, name, action, *doors):
    return ("I", kind, name, action, tuple(sorted(doors)))


def found(events, law):
    return [f for f in model.check(events).findings if f.law == law]


class TestInputRules(unittest.TestCase):
    def test_i1_an_up_lost_after_an_act_change_is_found(self):
        ev = [I("key", "R", 1, "script-down"), ("A", "Fase"), I("key", "R", 0)]
        self.assertTrue(found(ev, "I1"))

    def test_i1_the_up_after_an_act_change_passes(self):
        ev = [I("key", "R", 1, "script-down"), ("A", "Fase"), I("key", "R", 0, "script-up")]
        self.assertEqual(found(ev, "I1"), [])

    def test_i2_a_script_up_for_a_box_press_is_found(self):
        ev = [I("key", "A", 1, "widget-down"), I("key", "A", 0, "widget-up", "script-up")]
        self.assertTrue(found(ev, "I2"))

    def test_i2_a_script_up_for_a_widget_button_press_is_found(self):
        ev = [I("button", "0", 1, "widget-down"), I("button", "0", 0, "script-up")]
        self.assertTrue(found(ev, "I2"))

    def test_i3_an_old_act_repeat_to_the_script_is_found(self):
        ev = [I("key", "R", 1, "script-down"), ("A", "Fase"), I("key", "R", 2, "script-key")]
        self.assertTrue(found(ev, "I3"))

    def test_i3_a_script_press_repeating_into_a_box_is_found(self):
        ev = [I("key", "B", 1, "script-down"), I("key", "B", 2, "widget-key")]
        self.assertTrue(found(ev, "I3"))

    def test_i4_the_char_of_a_script_key_typed_into_a_box_is_found(self):
        ev = [I("key", "T", 1, "script-down"), I("char", "t", 1, "widget-char")]
        self.assertTrue(found(ev, "I4"))

    def test_i4_composed_text_after_a_release_passes(self):
        ev = [I("key", "T", 1, "script-down"), I("key", "T", 0, "script-up"),
              I("char", "é", 1, "widget-char")]
        self.assertEqual(found(ev, "I4"), [])

    def test_i5_a_given_up_press_released_into_a_widget_is_found(self):
        ev = [I("button", "0", 1, "widget-down"), ("O", "abandon", "0", "Button@g.py:1#0"),
              I("button", "0", 0, "widget-up")]
        self.assertTrue(found(ev, "I5"))


class TestCanaries(unittest.TestCase):
    def setUp(self):
        require_canaries(self)

    def _bites(self, law):
        for verify in both_verify_modes():
            with self.subTest(verify=verify):
                run, _state, rep = drive(S3, PLAY, patches=PLANTS[law](), keep_going=True)
                self.assertIn(law, {f.law for f in rep.findings},
                              f"{rep.summary()} (the run stopped on: {run.error!r})")

    def test_i1(self):
        self._bites("I1")

    def test_i2(self):
        self._bites("I2")

    def test_i3(self):
        self._bites("I3")

    def test_i4(self):
        self._bites("I4")

    def test_i5(self):
        self._bites("I5")


if __name__ == "__main__":
    unittest.main()
