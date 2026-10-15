"""Laws campaign, stage S1: the frame (F) and lifetime (L) laws.

The model (``tests/laws/model/frame.py``, ``lifetime.py``) checks a laws
trace against design/Laws.md, "Frame" and "Lifetime". Three layers:

* the fixture (``tests/laws/fixtures/s1_lifetime.py``): a short game that
  witnesses every F and L law and breaks none;
* synthetic traces: each rule on a hand-made event list, both ways;
* canaries (gate): an engine bug of each law's class planted
  (``tests/laws/plants.py``), the model must name that law.

The sweeps over the test families are ``test_laws_families`` (SLOW).

    python -m unittest tests.test_laws_lifetime -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import require_canaries  # noqa: E402
from laws import model  # noqa: E402
from laws.harness import record  # noqa: E402
from laws.model import frame as frame_model, lifetime  # noqa: E402
from laws.plants import PLANTS  # noqa: E402

S1 = "tests/laws/fixtures/s1_lifetime"
FRAMES = 160
LAWS = frame_model.LAWS + lifetime.LAWS


class TestFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_, cls.state, cls.rep = record(S1, FRAMES)

    def test_no_finding(self):
        self.assertEqual(self.rep.findings, [], self.rep.summary())

    def test_every_law_is_witnessed(self):
        missing = [law for law in LAWS if not self.rep.witnesses[law]]
        self.assertEqual(missing, [], dict(self.rep.witnesses))

    def test_the_game_did_what_it_does(self):
        s = self.state
        self.assertEqual(s["rounds"], 2)
        self.assertEqual(s["hooks"], 8)          # 4 drones x 2 rounds, once each
        self.assertGreater(s["pings"], 20)
        self.assertGreater(s["updates"], 100)


# -- synthetic traces ---------------------------------------------------------

def frame(n, *inner, order=frame_model.ORDER):
    """One frame body; ``inner``: (phase, [events]) placed inside that phase."""
    body = dict(inner)
    out = [("F", n, 1 / 60)]
    out += body.get("poll", [])
    for ph in order:
        out.append(("P", ph, True))
        out += body.get(ph, [])
        out.append(("p", ph))
    out.append(("f", n))
    return out


def X(door, phase, fn, *args, method=True):
    return ("X", door, phase, fn, tuple(args), False, method)


def findings(events, law):
    return [f for f in model.check(events).findings if f.law == law]


class TestFrameRules(unittest.TestCase):
    def test_f1_canonical_order_passes(self):
        self.assertEqual(findings(frame(1), "F1"), [])

    def test_f1_a_missing_phase_is_found(self):
        order = tuple(p for p in frame_model.ORDER if p != "tick")
        self.assertTrue(findings(frame(1, order=order), "F1"))

    def test_f1_swapped_phases_are_found(self):
        order = ("update", "collision", "tick") + frame_model.ORDER[3:]
        self.assertTrue(findings(frame(1, order=order), "F1"))

    def test_f1_an_explicit_flush_is_not_a_frame_phase(self):
        ev = frame(1, ("poll", [("P", "flush", False), ("p", "flush")]))
        self.assertEqual(findings(ev, "F1"), [])

    def test_f1_abstains_on_an_aborted_frame(self):
        order = ("update", "tick")
        ev = frame(1, order=order)
        ev.insert(-1, ("E", "CollisionSystem.step", "ValueError"))
        rep = model.check(ev)
        self.assertEqual([f for f in rep.findings if f.law == "F1"], [])
        self.assertEqual(rep.abstain["F1"], 1)

    def test_f2_a_timer_in_its_phase_passes(self):
        self.assertEqual(findings(frame(1, ("tick", [X("every", "tick", "g.py:1:f")])), "F2"), [])

    def test_f2_a_timer_in_collision_is_found(self):
        ev = frame(1, ("collision", [X("every", "collision", "g.py:1:f")]))
        self.assertTrue(findings(ev, "F2"))

    def test_f2_destroy_time_hooks_run_anywhere(self):
        ev = frame(1, ("update", [X("on_destroy", "update", "g.py:1:h", "A@g.py:1#0")]))
        self.assertEqual(findings(ev, "F2"), [])


class TestLifetimeRules(unittest.TestCase):
    A = "A@g.py:1#0"

    def born(self):
        return [("N", self.A, "A", "g.py:1", None)]

    def destroyed(self, dead=True, hook=True):
        out = [("Q", self.A, None)]
        if hook:
            out.append(X("on_destroy", "update", "g.py:5:A.on_destroy", self.A))
        out += [("D", self.A, False), ("T", self.A), ("d", self.A, dead)]
        return out

    def test_l1_dead_on_return_passes(self):
        self.assertEqual(findings(self.born() + self.destroyed(), "L1"), [])

    def test_l1_alive_on_return_is_found(self):
        self.assertTrue(findings(self.born() + self.destroyed(dead=False), "L1"))

    def test_l2_twice_is_found(self):
        ev = self.born() + [X("on_destroy", "update", "g.py:5:A.on_destroy", self.A)] \
            + self.destroyed()
        self.assertTrue(findings(ev, "L2"))

    def test_l2_after_the_teardown_started_is_found(self):
        ev = self.born() + [("Q", self.A, None), ("D", self.A, False), ("T", self.A),
                            X("on_destroy", "update", "g.py:5:A.on_destroy", self.A),
                            ("d", self.A, True)]
        self.assertTrue(findings(ev, "L2"))

    def test_l3_a_method_after_death_is_found(self):
        ev = self.born() + self.destroyed() + frame(2, ("tick", [X("every", "tick", "g.py:9:A.ping",
                                                                    self.A)]))
        self.assertTrue(findings(ev, "L3"))

    def test_l3_a_module_rule_with_a_dead_me_is_not_the_objects_own(self):
        ev = self.born() + self.destroyed() + frame(
            2, ("collision", [X("exit", "collision", "g.py:9:left", self.A, method=False)]))
        self.assertEqual(findings(ev, "L3"), [])

    def test_l3_a_new_object_on_the_same_label_is_a_new_life(self):
        ev = self.born() + self.destroyed() + self.born() + frame(
            2, ("tick", [X("every", "tick", "g.py:9:A.ping", self.A)]))
        self.assertEqual(findings(ev, "L3"), [])

    def test_l4_a_parked_actors_timer_is_found(self):
        ev = self.born() + [("K", self.A, None)] + frame(
            2, ("tick", [X("every", "tick", "g.py:9:A.ping", self.A)]))
        self.assertTrue(findings(ev, "L4"))

    def test_l4_resumed_runs_again(self):
        ev = self.born() + [("K", self.A, None), ("R", self.A, None)] + frame(
            2, ("tick", [X("every", "tick", "g.py:9:A.ping", self.A)]))
        self.assertEqual(findings(ev, "L4"), [])

    def test_l4_a_parked_actors_exit_is_allowed(self):
        ev = self.born() + [("K", self.A, None)] + frame(
            2, ("collision", [X("exit", "collision", "g.py:9:A.left", self.A)]))
        self.assertEqual(findings(ev, "L4"), [])

    def _act_change(self, hooks_first=True, top=None):
        b, c = "B@g.py:2#0", "C@g.py:3#0"
        ev = [("B", "Fase"), ("b", "Fase")]
        ev += [("N", b, "B", "g.py:2", None), ("N", c, "C", "g.py:3", None)]
        hooks = [X("on_destroy", "tick", "g.py:5:B.on_destroy", b),
                 X("on_destroy", "tick", "g.py:6:C.on_destroy", c)]
        tear = [("D", b, False), ("T", b), ("d", b, True), ("D", c, False), ("T", c), ("d", c, True)]
        body = hooks + tear if hooks_first else tear[:3] + hooks + tear[3:]
        if top is not None:
            body += [("D", top, False), ("T", top), ("d", top, True)]
        return ev + [("A", "Fim")] + body + [("B", "Fim"), ("b", "Fim"), ("a", "Fim")]

    def test_l5_hooks_before_teardown_pass(self):
        self.assertEqual(findings(self._act_change(), "L5"), [])

    def test_l5_a_hook_after_a_sibling_was_torn_down_is_found(self):
        self.assertTrue(findings(self._act_change(hooks_first=False), "L5"))

    def test_l6_a_top_level_object_torn_down_is_found(self):
        ev = [("N", self.A, "A", "g.py:1", None)] + self._act_change(top=self.A)
        self.assertTrue(findings(ev, "L6"))

    def test_l6_build_before_teardown_is_found(self):
        ev = self._act_change()
        a = ev.index(("A", "Fim"))
        ev.insert(a + 1, ("B", "Fim"))
        self.assertTrue(findings(ev, "L6"))


class TestCanaries(unittest.TestCase):
    """An engine bug of each law's class, planted: the model names that law."""

    def setUp(self):
        require_canaries(self)

    def _bites(self, law):
        _run, _state, rep = record(S1, FRAMES, patches=PLANTS[law](), keep_going=True)
        self.assertIn(law, {f.law for f in rep.findings}, rep.summary())

    def test_f1(self):
        self._bites("F1")

    def test_f2(self):
        self._bites("F2")

    def test_l1(self):
        self._bites("L1")

    def test_l2(self):
        self._bites("L2")

    def test_l3(self):
        self._bites("L3")

    def test_l4(self):
        self._bites("L4")

    def test_l5(self):
        self._bites("L5")

    def test_l6(self):
        self._bites("L6")


if __name__ == "__main__":
    unittest.main()
