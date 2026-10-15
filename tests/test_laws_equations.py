"""Laws campaign: equations — programs an author believes equivalent.

* E3 spawn order (``laws.equations.e3_program`` / ``e3_script``): two
  adjacent independent construction statements swapped; the traces must
  agree frame by frame (multisets: order inside a phase is not compared).
  On the PB5 shooter twin, every program and every example.
* E4 handler home (``tests/laws/twins/handler_home.py``): one rule as a
  module ``@collide``, a class ``@collide_with`` or an ``on_collide``
  property; the same calls in the same frames, by role.
* E8 breaking in the handler vs between frames (``tests/laws/twins/breakout.py``,
  PE5): the ball leaves with the same velocity, within budget (angle 2°,
  speed 2 %), on single hits. A hit on two bricks at once is open (LW2,
  a decision): the test pins that it still diverges, so a fix shows.

Canaries (gate): the old S8-2 "stop once a side died" rule (E3), a dropped
``on_collide_stay`` door (E4), the ghost response off (E8).

``dev``: the twins, the first scenario of each program, one swap per
example; ``ci`` / ``deep``: every scenario and swap. SLOW + SPLIT.

    python -m unittest tests.test_laws_equations -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402
from hypothesis_support import require_canaries  # noqa: E402
from laws import equations as eq  # noqa: E402
from laws.plants import col  # noqa: E402
from program_support import ProgramRun, Scenario, load_spec  # noqa: E402
from test_prog_invariance import PROGRAMS  # noqa: E402
from test_scripts_run import scripts  # noqa: E402

FULL = hypothesis_support.PROFILE in ("ci", "deep")
TWINS = "tests/laws/twins"
WAIT = {"SCENARIOS": {"wait": Scenario(steps=[("wait", 150)])}, "PROBES": {}}
ANGLE_BUDGET = 2.0           # degrees (design/Laws.md, budgets)
SPEED_BUDGET = 0.02


# -- E3 -------------------------------------------------------------------------

class TestSpawnOrder(unittest.TestCase):
    def test_shooter_twin(self):
        self.assertEqual(eq.e3_program(f"{TWINS}/shooter_order", WAIT, "wait"), [])

    def test_programs(self):
        out = []
        for program in PROGRAMS:
            ns = load_spec(program, "a")
            for scenario in (list(ns["SCENARIOS"]) if FULL else list(ns["SCENARIOS"])[:1]):
                out += eq.e3_program(program, ns, scenario, limit=None if FULL else 2)
        self.assertEqual(out, [], "\n".join(m[:800] for m in out))

    def test_examples(self):
        paths = scripts()
        limit = None if FULL else 1

        def one(path):
            try:
                return eq.e3_script(path, 600, limit=limit)
            except Exception as e:  # noqa: BLE001
                return [f"{os.path.basename(path)}: {type(e).__name__}: {str(e)[-300:]}"]

        with ThreadPoolExecutor(max(2, min(8, (os.cpu_count() or 4) - 1))) as pool:
            out = [m for msgs in pool.map(one, paths) for m in msgs]
        self.assertEqual(out, [], "\n".join(m[:800] for m in out))


# -- E4 -------------------------------------------------------------------------

def _roles(events):
    """frame -> Counter of (door, role of me, role of other) for contact doors."""
    out = {}
    frame = 0
    for e in events:
        if e[0] == "F":
            frame = e[1]
        elif e[0] == "X" and e[1] in ("enter", "stay", "exit"):
            role = lambda lab: "zone" if lab and lab.startswith("Rect@") else "ball"  # noqa: E731
            args = e[4]
            if len(args) >= 2:
                out.setdefault(frame, Counter())[(e[1], role(args[0]), role(args[1]))] += 1
    return out


class TestHandlerHome(unittest.TestCase):
    def _trace(self, home):
        ns = {"SCENARIOS": {"w": Scenario(steps=[("wait", 150)], params={"home": home})},
              "PROBES": {}}
        return eq.program_trace(f"{TWINS}/handler_home", ns, "w")

    def test_three_homes_trace_alike(self):
        base = _roles(self._trace("module"))
        self.assertTrue(base, "the twin made no contact (vacuous)")
        for home in ("method", "property"):
            with self.subTest(home=home):
                self.assertEqual(eq.compare(base, _roles(self._trace(home))), [])


# -- E8 -------------------------------------------------------------------------

def _exit_velocity(when, **params):
    run = ProgramRun(f"{TWINS}/breakout", dict(params, when=when), probes={})
    run.start()
    try:
        run.step(150)
        st = run.ns["st"]
        return st.broken, (st.vx, st.vy)
    finally:
        run.close()


def _gap(a, b):
    ang = abs(math.degrees(math.atan2(a[1], a[0]) - math.atan2(b[1], b[0])))
    ang = min(ang, 360 - ang)
    sa, sb = math.hypot(*a), math.hypot(*b)
    return ang, abs(sa - sb) / max(sa, sb, 1e-9)


class TestBreakInHandlerOrLater(unittest.TestCase):
    def test_single_hits_agree(self):
        for vy in (45.0, -30.0, 140.0):
            with self.subTest(vy=vy):
                bh, vh = _exit_velocity("handler", vy=vy)
                bl, vl = _exit_velocity("later", vy=vy)
                self.assertEqual(bh, bl)
                self.assertGreater(bh, 0, "no brick hit (vacuous)")
                ang, speed = _gap(vh, vl)
                self.assertLessEqual(ang, ANGLE_BUDGET, (vh, vl))
                self.assertLessEqual(speed, SPEED_BUDGET, (vh, vl))

    def test_two_bricks_at_once_still_diverge_lw2(self):
        """LW2 (open, a decision): a ball on the seam of two bricks. Pinned so
        a fix of the multi-contact response shows here (then: flip to agree)."""
        _b, vh = _exit_velocity("handler", vy=0.0)
        _b, vl = _exit_velocity("later", vy=0.0)
        ang, _speed = _gap(vh, vl)
        self.assertGreater(ang, ANGLE_BUDGET, (vh, vl))


# -- canaries -------------------------------------------------------------------

class TestCanaries(unittest.TestCase):
    def setUp(self):
        require_canaries(self)

    def test_e3_catches_the_old_stop_rule(self):
        from unittest import mock
        real = col._call

        def stop_once_dead(fn, *args):
            if any(not getattr(a, "is_alive", True) for a in args[:2]):
                return None                        # the plant: S8-2 before PB5
            return real(fn, *args)

        with mock.patch.object(col, "_call", stop_once_dead):
            out = eq.e3_program(f"{TWINS}/shooter_order", WAIT, "wait")
        self.assertTrue(out)

    def test_e4_catches_a_dropped_stay_door(self):
        from unittest import mock
        table = dict(col._PHASE_CALLBACK)
        table[col._PHASE_STAY] = "_no_such_callback"
        with mock.patch.object(col, "_PHASE_CALLBACK", table):
            t = TestHandlerHome()
            base = _roles(t._trace("module"))
            prop = _roles(t._trace("property"))
        self.assertTrue(eq.compare(base, prop))

    def test_e8_catches_the_ghost_off(self):
        from unittest import mock
        with mock.patch.object(col.CollisionSystem, "_note_ghost_contacts",
                               lambda self, c: None):
            _b, vh = _exit_velocity("handler", vy=45.0)
        _b, vl = _exit_velocity("later", vy=45.0)
        self.assertGreater(_gap(vh, vl)[0], ANGLE_BUDGET)


if __name__ == "__main__":
    unittest.main()
