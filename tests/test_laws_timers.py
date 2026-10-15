"""Laws campaign, stage S4: timers (T laws).

The model (``tests/laws/model/timers.py``) replays every ``after`` and
``every`` in exact rational time and checks when each fires (design/Laws.md,
"Timers"). Layers:

* the fixture (``tests/laws/fixtures/s4_timers.py``): an exact-frame
  ``after``, an ``every`` across a long hitch frame (the per-tick cap), a
  timer made in a timer's callback and one made in ``update``, a parked and
  a destroyed owner, a half-speed owner, work on a destroyed actor;
* synthetic traces: each rule both ways;
* canaries (gate): PM8, work made in the tick ticked at once, a parked
  owner that keeps counting, an uncapped ``every``, work registered on a
  dead actor.

    python -m unittest tests.test_laws_timers -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import require_canaries  # noqa: E402
from laws import model  # noqa: E402
from laws.harness import drive  # noqa: E402
from laws.model import timers  # noqa: E402
from laws.plants import PLANTS, both_verify_modes  # noqa: E402

S4 = "tests/laws/fixtures/s4_timers"
PLAY = [("step", 90), ("step_dt", 0.5), ("step", 30)]


def _drive(**kw):
    from game_harness import GameRun
    if not hasattr(GameRun, "step_dt"):
        GameRun.step_dt = lambda self, dt: self.step(1, dt=dt)
    return drive(S4, PLAY, **kw)


class TestFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_, cls.state, cls.rep = _drive()

    def test_no_finding(self):
        self.assertEqual(self.rep.findings, [], self.rep.summary())

    def test_every_timer_law_is_witnessed(self):
        missing = [law for law in timers.LAWS if not self.rep.witnesses[law]]
        self.assertEqual(missing, [], dict(self.rep.witnesses))

    def test_the_game_did_what_it_does(self):
        s = self.state
        self.assertEqual((s["half"], s["chained"], s["made_in_update"]), (1, 1, 1))
        self.assertEqual((s["ghost"], s["late"]), (0, 0))   # dead owners' work never ran
        self.assertEqual(s["slow"], 1)
        # 90 frames: 30 fires; the 0.5 s hitch owes 10, the cap gives 5; 30 more: 10.
        self.assertEqual(s["ticks"], 45)


# -- synthetic traces ---------------------------------------------------------

DT = 1 / 60


def H_add(h, kind, delay=0.0, interval=0.0, owner=None, phase="update", refused=False):
    return ("H", "add", h, kind, delay, interval, owner, "act", refused, phase)


def H_tick(h, dt=DT, scale=1.0, active=True, alive=True):
    return ("H", "tick", h, dt, scale, active, alive, False, False, False)


def frames(n, body):
    """``n`` frames; ``body(k)`` → events inside frame k (1-based)."""
    out = []
    for k in range(1, n + 1):
        out.append(("F", k, DT))
        out += body(k)
        out.append(("f", k))
    return out


def found(ev, law):
    return [f for f in model.check(ev).findings if f.law == law]


class TestTimerRules(unittest.TestCase):
    def test_t1_on_the_exact_frame_passes(self):
        ev = [H_add("a", "after", delay=0.5)] + frames(
            30, lambda k: [H_tick("a")] + ([("H", "fire", "a")] if k == 30 else []))
        self.assertEqual(found(ev, "T1"), [])

    def test_t1_a_frame_late_is_found(self):
        ev = [H_add("a", "after", delay=0.5)] + frames(
            31, lambda k: [H_tick("a")] + ([("H", "fire", "a")] if k == 31 else []))
        self.assertTrue(found(ev, "T1"))

    def test_t2_made_in_the_tick_and_ticked_that_frame_is_found(self):
        ev = [("F", 1, DT), H_add("a", "after", delay=0.1, phase="tick"), H_tick("a"), ("f", 1)]
        self.assertTrue(found(ev, "T2"))

    def test_t3_a_parked_owners_fire_is_found(self):
        ev = [H_add("a", "after", delay=1 / 60, owner="O#0")] + frames(
            1, lambda k: [H_tick("a", active=False), ("H", "fire", "a")])
        self.assertTrue(found(ev, "T3"))

    def test_t4_the_cap_holds_on_a_hitch(self):
        ev = [H_add("e", "every", interval=0.05), ("F", 1, 0.5), H_tick("e", dt=0.5)] \
            + [("H", "fire", "e")] * 5 + [("f", 1)]
        self.assertEqual(found(ev, "T4"), [])

    def test_t4_past_the_cap_is_found(self):
        ev = [H_add("e", "every", interval=0.05), ("F", 1, 0.5), H_tick("e", dt=0.5)] \
            + [("H", "fire", "e")] * 10 + [("f", 1)]
        self.assertTrue(found(ev, "T4"))

    def test_t6_work_on_a_dead_actor_that_ticks_is_found(self):
        ev = [("N", "O#0", "O", "g.py:1", None), ("D", "O#0", False), ("d", "O#0", True),
              H_add("a", "after", delay=0.1, owner="O#0")] + frames(1, lambda k: [H_tick("a")])
        self.assertTrue(found(ev, "T6"))


class TestCanaries(unittest.TestCase):
    def setUp(self):
        require_canaries(self)

    def _bites(self, law):
        for verify in both_verify_modes():
            with self.subTest(verify=verify):
                run, _state, rep = _drive(patches=PLANTS[law](), keep_going=True)
                self.assertIn(law, {f.law for f in rep.findings},
                              f"{rep.summary()} (the run stopped on: {run.error!r})")

    def test_t1(self):
        self._bites("T1")

    def test_t2(self):
        self._bites("T2")

    def test_t3(self):
        self._bites("T3")

    def test_t4(self):
        self._bites("T4")

    def test_t6(self):
        self._bites("T6")


if __name__ == "__main__":
    unittest.main()
