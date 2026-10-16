"""Laws campaign: equations — programs an author believes equivalent.

* E3 spawn order (``laws.equations.e3_program`` / ``e3_script``): two
  adjacent independent construction statements swapped; the traces must
  agree frame by frame (multisets: order inside a phase is not compared).
  On the PB5 shooter twin, every program and every example.
* E4 handler home (``tests/laws/twins/handler_home.py``): one rule as a
  module ``@collide``, a class ``@collide_with`` or an ``on_collide``
  property; the same calls in the same frames, by role.
* E8 breaking in the handler vs between frames (``tests/laws/twins/breakout.py``,
  PE5): the ball leaves with the same velocity and on the same path, within
  budget (angle 2°, speed 2 %, position 0.5 DU), on single hits and on a hit
  on two bricks at once (the seam: LW2, closed 2026-10-15 by the joint stop).

* E15 a neutral rule (``laws.equations.e15_program`` / ``e15_script``): a
  no-op ``@collide_stay`` between two tags the program's rules already name;
  every other rule's calls agree (a rule's enters, stays and exits do not
  depend on another rule pairing the same bodies: V15, CD3). On the shield
  twin (``tests/laws/twins/shield.py``), every program and every example.

Canaries (gate): the old S8-2 "stop once a side died" rule (E3), a dropped
``on_collide_stay`` door (E4), the ghost response off (E8), the old per-pair
contact rule (E15).

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
POS_BUDGET = 0.5             # DU per event


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


# -- E15 ------------------------------------------------------------------------

class TestRuleNeutrality(unittest.TestCase):
    def test_shield_twin(self):
        with open(eq.program_path_of(f"{TWINS}/shield"), encoding="utf-8") as fh:
            self.assertTrue(eq.neutral_candidates(fh.read()), "no neutral rule (vacuous)")
        self.assertEqual(eq.e15_program(f"{TWINS}/shield", WAIT, "wait"), [])

    def test_programs(self):
        out = []
        for program in PROGRAMS:
            ns = load_spec(program, "a")
            for scenario in (list(ns["SCENARIOS"]) if FULL else list(ns["SCENARIOS"])[:1]):
                out += eq.e15_program(program, ns, scenario, limit=None if FULL else 2)
        self.assertEqual(out, [], "\n".join(m[:800] for m in out))

    def test_examples(self):
        paths = scripts()
        limit = None if FULL else 1

        def one(path):
            try:
                return eq.e15_script(path, 600, limit=limit)
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
        return st.broken, (st.vx, st.vy), (st.px, st.py)
    finally:
        run.close()


def _gap(a, b):
    ang = abs(math.degrees(math.atan2(a[1], a[0]) - math.atan2(b[1], b[0])))
    ang = min(ang, 360 - ang)
    sa, sb = math.hypot(*a), math.hypot(*b)
    return ang, abs(sa - sb) / max(sa, sb, 1e-9)


class TestBreakInHandlerOrLater(unittest.TestCase):
    def _agree(self, vy, bricks):
        bh, vh, ph = _exit_velocity("handler", vy=vy)
        bl, vl, pl = _exit_velocity("later", vy=vy)
        self.assertEqual(bh, bl)
        self.assertEqual(bh, bricks, "the hit is not the one this test is about (vacuous)")
        ang, speed = _gap(vh, vl)
        self.assertLessEqual(ang, ANGLE_BUDGET, (vh, vl))
        self.assertLessEqual(speed, SPEED_BUDGET, (vh, vl))
        self.assertLessEqual(math.dist(ph, pl), POS_BUDGET, (ph, pl))

    def test_single_hits_agree(self):
        for vy in (45.0, -30.0, 140.0):
            with self.subTest(vy=vy):
                self._agree(vy, 1)

    def test_two_bricks_at_once_agree(self):
        """LW2 (closed 2026-10-15): a ball on the seam of two bricks breaks
        both and leaves straight back, whether they break in the handler or
        a frame later (they differed by up to 46 degrees)."""
        self._agree(0.0, 2)
        _b, v, _p = _exit_velocity("handler", vy=0.0)
        self.assertLessEqual(_gap(v, (-300.0, 0.0))[0], ANGLE_BUDGET, v)


# -- E1 -------------------------------------------------------------------------

# Examples whose edge events depend on the frame rate for a reason the
# triage named (design/Testing Design.md, catalogue LW). Shrink-only.
E1_EXCLUDED = {
    "bolas.py": "ACADEMIC: twenty balls bouncing off each other amplify the frame dependence "
                "left in many-body contacts (bodies sweep one at a time; a tie with movable "
                "partners answers one at a time); one ball in a box holds (LW7 closed)",
    "entropia.py": "ACADEMIC (as bolas): a box of balls bouncing off each other",
    "aviao.py": "ACADEMIC: the author's own Euler step (vel.y -= g * dt) puts the plane a "
                "few pixels apart at uneven pacing; a door passed one frame later",
    "naves_modos.py": "ACADEMIC: a self re-arming after / a mode's wait starts each period at "
                      "the frame that noticed the last one (Scena Design, Clocks: 'at least p "
                      "apart', not a rate); uneven pacing drifts the chain",
}
E1_DEV = ("one_ball", "orbitas.py", "naves.py", "colisao.py", "ninja.py", "pegar_estrelas.py")


class TestPacing(unittest.TestCase):
    def test_one_ball_twin(self):
        path = os.path.join(eq.ROOT_TESTS, "laws", "twins", "one_ball.py")
        self.assertEqual(eq.e1_script(path, 600), [])

    def test_two_wall_twin(self):
        """A head-on bounce every half second at 700 DU/s: with the leftover
        dropped at each bounce (LW7) the runs were a frame apart by 6 s."""
        path = os.path.join(eq.ROOT_TESTS, "laws", "twins", "two_walls.py")
        self.assertEqual(eq.e1_script(path, 600), [])

    def test_examples(self):
        paths = [p for p in scripts() if os.path.basename(p) not in E1_EXCLUDED
                 and (FULL or os.path.basename(p) in E1_DEV)]
        self.assertTrue(paths)

        def one(path):
            try:
                return eq.e1_script(path, 600)
            except Exception as e:  # noqa: BLE001
                return [f"{os.path.basename(path)}: {type(e).__name__}: {str(e)[-300:]}"]

        with ThreadPoolExecutor(max(2, min(8, (os.cpu_count() or 4) - 1))) as pool:
            out = [m for msgs in pool.map(one, paths) for m in msgs]
        self.assertEqual(out, [], "\n".join(m[:800] for m in out))

    def test_excluded_examples_exist(self):
        names = {os.path.basename(p) for p in scripts()}
        self.assertEqual(sorted(set(E1_EXCLUDED) - names), [])


# -- E5 / E6 --------------------------------------------------------------------

def _home(home):
    ns = {"SCENARIOS": {"w": Scenario(steps=[("wait", 120)], params={"home": home})},
          "PROBES": {}}
    return eq.e5_projection(eq.program_trace(f"{TWINS}/act_home", ns, "w"))


class TestActHome(unittest.TestCase):
    def test_top_and_act_run_alike(self):
        top = _home("top")
        self.assertGreater(sum(sum(c.values()) for c in top.values()), 50, "vacuous")
        self.assertEqual(eq.compare(top, _home("act")), [])


class TestBoundOrClosure(unittest.TestCase):
    def test_twin(self):
        W = {"SCENARIOS": {"w": Scenario(steps=[("wait", 60)])}, "PROBES": {}}
        self.assertEqual(eq.e6_program(f"{TWINS}/closure_owner", W, "w"), [])

    def test_programs_and_examples(self):
        out = []
        ns = load_spec("galaga_acts", "a")
        for scenario in (list(ns["SCENARIOS"]) if FULL else list(ns["SCENARIOS"])[:2]):
            out += eq.e6_program("galaga_acts", ns, scenario)
        for p in scripts():
            with open(p, encoding="utf-8") as fh:
                has = eq.bound_to_closure(fh.read())[1]
            if has:
                out += eq.e6_script(p, 600)
        self.assertEqual(out, [], "\n".join(m[:800] for m in out))


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

    def test_e15_catches_the_per_pair_contact_rule(self):
        """CD3's old rule: a contact is per pair, so a rule gained or lost
        mid-contact gets a stay instead of its enter and no exit."""
        from unittest import mock
        with mock.patch.object(col.CollisionSystem, "_rule_changes",
                               lambda self, stayed, id_to: None), \
                mock.patch.object(col.CollisionSystem, "_rule_filter",
                                  lambda self, ca, cb, runs, only, skip: runs):
            out = eq.e15_program(f"{TWINS}/shield", WAIT, "wait")
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

    def test_e1_catches_an_every_that_drops_its_debt(self):
        # The plant runs in the children: a script twin carries it in its source.
        path = os.path.join(eq.ROOT_TESTS, "laws", "twins", "one_ball.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        src = src.replace(
            "from scena import *",
            "from scena import *\n"
            "import scena.process as _p\n"
            "_fire = _p.Handle._fire_every\n"
            "def _drop(self):\n"
            "    _fire(self)\n"
            "    self._elapsed = 0.0       # the plant: a fire drops the debt\n"
            "_p.Handle._fire_every = _drop\n"
            "st.beats = 0\n"
            "every(0.05, lambda: setattr(st, 'beats', st.beats + 1))", 1)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            twin = os.path.join(tmp, "one_ball.py")
            with open(twin, "w", encoding="utf-8") as fh:
                fh.write(src)
            self.assertTrue(eq.e1_script(twin, 600, paces=("30",)))

    def test_e1_catches_the_dropped_leftover(self):
        # LW7's bug planted in the children: a bounce drops its leftover again.
        path = os.path.join(eq.ROOT_TESTS, "laws", "twins", "two_walls.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        src = src.replace(
            "from scena import *",
            "from scena import *\n"
            "import sys as _sys\n"
            "_sys.modules['scena.collision']._BOUNCE_SUBSTEP = False", 1)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            twin = os.path.join(tmp, "two_walls.py")
            with open(twin, "w", encoding="utf-8") as fh:
                fh.write(src)
            self.assertTrue(eq.e1_script(twin, 600, paces=("144",)))

    def test_e5_catches_act_timers_that_start_late(self):
        from unittest import mock
        import scena.process as proc
        real = proc.Scheduler.add

        def add(self, handle):
            out = real(self, handle)
            if getattr(handle, "scope", None) == "act":
                handle._elapsed = -1 / 60          # the plant: one frame late
            return out
        with mock.patch.object(proc.Scheduler, "add", add):
            act = _home("act")
        self.assertTrue(eq.compare(_home("top"), act))

    def test_e6_catches_closures_without_an_owner(self):
        from unittest import mock
        import scena.process as proc
        W = {"SCENARIOS": {"w": Scenario(steps=[("wait", 60)])}, "PROBES": {}}
        with mock.patch.object(proc, "_closure_self", lambda fn: None):
            out = eq.e6_program(f"{TWINS}/closure_owner", W, "w")
        self.assertTrue(out)

    def test_e8_catches_the_ghost_off(self):
        from unittest import mock
        with mock.patch.object(col.CollisionSystem, "_note_ghost_contacts",
                               lambda self, c: None):
            _b, vh, _p = _exit_velocity("handler", vy=45.0)
        _b, vl, _p = _exit_velocity("later", vy=45.0)
        self.assertGreater(_gap(vh, vl)[0], ANGLE_BUDGET)


if __name__ == "__main__":
    unittest.main()
