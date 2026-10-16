"""Laws campaign, stage S2: the contact (C) laws.

The model (``tests/laws/model/collision.py``) checks each collision step's
author calls against the contacts the step committed (design/Laws.md,
"Contacts"). Three layers, as for S1:

* the fixture (``tests/laws/fixtures/s2_contacts.py``): Breakout bounces,
  a shot that touches two enemies, zones with stays and a destroying exit,
  an untag mid-contact, a mine with two methods on one contact, a drone
  that parks on landing — every C law witnessed, none broken;
* synthetic traces: each rule both ways;
* canaries (gate): a bug of each law's class planted in the engine.

    python -m unittest tests.test_laws_contacts -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import require_canaries  # noqa: E402
from laws import model  # noqa: E402
from laws.harness import record  # noqa: E402
from laws.model import collision  # noqa: E402
from laws.plants import PLANTS, both_verify_modes  # noqa: E402
from test_laws_lifetime import X, findings  # noqa: E402

S2 = "tests/laws/fixtures/s2_contacts"
FRAMES = 120


class TestFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_, cls.state, cls.rep = record(S2, FRAMES)

    def test_no_finding(self):
        self.assertEqual(self.rep.findings, [], self.rep.summary())

    def test_every_contact_law_is_witnessed(self):
        missing = [law for law in collision.LAWS if not self.rep.witnesses[law]]
        self.assertEqual(missing, [], dict(self.rep.witnesses))

    def test_the_game_did_what_it_does(self):
        s = self.state
        self.assertEqual(s["bricks"], 1)
        self.assertEqual((s["score"], s["hits"]), (1, 1))     # the shot enters one enemy only
        self.assertGreater(s["stays"], 10)
        self.assertEqual((s["exits_a"], s["exits_b"]), (1, 1))  # PB3: both exit handlers
        self.assertEqual((s["spikes_in"], s["spikes_out"]), (1, 1))  # PB1: the untag exits
        self.assertTrue(s["smoke"])                           # PB5: the dying body's 2nd method
        self.assertEqual(s["naps"], 1)                        # C4: one pad of two


# -- synthetic traces ---------------------------------------------------------

A, B, Z = "A@g.py:1#0", "B@g.py:2#0", "Z@g.py:3#0"
AB, AZ = (A, B), (A, Z)


def step(n, entered=(), stayed=(), exited=(), calls=(), resolve=True, tail=(),
         gained=(), lost=()):
    """One frame whose collision step commits the given pairs, then makes the calls."""
    out = [("F", n, 1 / 60), ("P", "collision", True),
           ("C", tuple(entered), tuple(stayed), tuple(exited), tuple(gained), tuple(lost))]
    out += list(calls)
    if resolve:
        out.append(("S", "resolve"))
    out += list(tail)
    out += [("p", "collision"), ("f", n)]
    return out


def H(door, me, other, fn="g.py:9:h", method=False):
    return X(door, "collision", fn, me, other, method=method)


class TestContactRules(unittest.TestCase):
    born = [("N", A, "A", "g.py:1", None), ("N", B, "B", "g.py:2", None),
            ("N", Z, "Z", "g.py:3", None)]

    def test_c1_enter_of_an_entered_pair_passes(self):
        ev = self.born + step(1, entered=[AB], calls=[H("enter", A, B)])
        self.assertEqual(findings(ev, "C1"), [])

    def test_c1_enter_of_a_staying_pair_is_found(self):
        ev = self.born + step(1, entered=[AB]) + step(2, stayed=[AB], calls=[H("enter", A, B)])
        self.assertTrue(findings(ev, "C1"))

    def test_c1_stay_of_a_new_pair_is_found(self):
        ev = self.born + step(1, entered=[AB], calls=[H("stay", A, B)])
        self.assertTrue(findings(ev, "C1"))

    def test_c2_stay_before_enter_is_found(self):
        ev = self.born + step(2, entered=[AZ], stayed=[AB],
                              calls=[H("stay", A, B), H("enter", A, Z)])
        self.assertTrue(findings(ev, "C2"))

    def test_c4_a_body_parked_in_one_contact_entering_another_is_found(self):
        calls = [H("enter", A, B), ("K", A, None), H("enter", A, Z)]
        ev = self.born + step(1, entered=[AB, AZ], calls=calls)
        self.assertTrue(findings(ev, "C4"))

    def test_c4_the_rest_of_its_own_contact_still_runs(self):
        calls = [H("enter", A, B, "g.py:9:first"), ("K", A, None),
                 H("enter", A, B, "g.py:10:second")]
        ev = self.born + step(1, entered=[AB, AZ], calls=calls)
        self.assertEqual(findings(ev, "C4"), [])

    def test_c5_exit_of_a_pair_not_in_contact_is_found(self):
        ev = self.born + step(1, calls=[H("exit", A, B)])
        self.assertTrue(findings(ev, "C5"))

    def test_c5_two_exit_handlers_of_one_exit_pass(self):
        ev = self.born + step(1, entered=[AB]) + step(
            2, exited=[AB], calls=[H("exit", A, B, "g.py:9:a"), H("exit", A, B, "g.py:10:b")])
        self.assertEqual(findings(ev, "C5"), [])

    def test_c5_a_second_exit_a_step_later_is_found(self):
        ev = self.born + step(1, entered=[AB]) + step(2, exited=[AB], calls=[H("exit", A, B)]) \
            + step(3, calls=[H("exit", A, B)])
        self.assertTrue(findings(ev, "C5"))

    def test_c1_enter_of_a_staying_pair_a_rule_gained_passes(self):
        """CD3: a tag joined while touching: that rule's enter, the pair stays."""
        ev = self.born + step(1, entered=[AB]) + step(
            2, stayed=[AB], gained=[AB], calls=[H("enter", A, B), H("stay", A, B)])
        self.assertEqual(findings(ev, "C1") + findings(ev, "C2"), [])

    def test_c5_exit_of_a_rule_a_staying_pair_lost_then_its_exit_passes(self):
        """CD3: a tag left while another rule keeps the pair: that rule's
        exit, then the pair's own exit when it separates."""
        ev = self.born + step(1, entered=[AB]) + step(
            2, stayed=[AB], lost=[AB], calls=[H("stay", A, B), H("exit", A, B, "g.py:9:a")]) \
            + step(3, exited=[AB], calls=[H("exit", A, B, "g.py:10:b")])
        self.assertEqual(findings(ev, "C5") + findings(ev, "C2"), [])

    def test_c5_exit_of_a_staying_pair_no_rule_lost_is_found(self):
        ev = self.born + step(1, entered=[AB]) + step(2, stayed=[AB], calls=[H("exit", A, B)]) \
            + step(3, exited=[AB], calls=[H("exit", A, B)])
        self.assertTrue(findings(ev, "C5"))

    def test_c7_a_dead_body_in_a_later_commit_is_found(self):
        dead = [("Q", A, None), ("D", A, False), ("T", A), ("d", A, True)]
        ev = self.born + step(1, entered=[AB]) + dead + step(2, exited=[AB])
        self.assertTrue(findings(ev, "C7"))

    def test_c8_a_handler_after_resolve_is_found(self):
        ev = self.born + step(1, entered=[AB], calls=[], tail=[H("enter", A, B)])
        self.assertTrue(findings(ev, "C8"))


class TestCanaries(unittest.TestCase):
    """A contact bug of each law's class, planted: the model names that law."""

    def setUp(self):
        require_canaries(self)

    def _bites(self, law):
        for verify in both_verify_modes():
            with self.subTest(verify=verify):
                run, _state, rep = record(S2, FRAMES, patches=PLANTS[law](), keep_going=True)
                self.assertIn(law, {f.law for f in rep.findings},
                              f"{rep.summary()} (the run stopped on: {run.error!r})")

    def test_c1(self):
        self._bites("C1")

    def test_c2(self):
        self._bites("C2")

    def test_c4(self):
        self._bites("C4")

    def test_c5(self):
        self._bites("C5")

    def test_c7(self):
        self._bites("C7")

    def test_c8(self):
        self._bites("C8")


if __name__ == "__main__":
    unittest.main()
