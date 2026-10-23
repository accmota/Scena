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
example; ``ci`` / ``deep``: every scenario and swap. SLOW + SPLIT. The
examples' E3 and E15 checks are classes of at most ``RUNS_PER_JOB`` runs
(``TestSpawnOrderExamples1``, …) and the programs' of at most
``PROGRAM_RUNS_PER_JOB`` (``TestSpawnOrderPrograms1``, …), one gate job each; below ``deep`` an
English example whose Portuguese twin is here is left out (WP33).

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
from program_support import ProgramRun, Scenario, load_spec, program_path  # noqa: E402
from test_prog_invariance import PROGRAMS  # noqa: E402
from test_scripts_run import law_scripts, scripts  # noqa: E402

FULL = hypothesis_support.PROFILE in ("ci", "deep")
LAW_SCRIPTS = law_scripts(hypothesis_support.PROFILE)
TWINS = "tests/laws/twins"
WAIT = {"SCENARIOS": {"wait": Scenario(steps=[("wait", 150)])}, "PROBES": {}}
ANGLE_BUDGET = 2.0           # degrees (design/Laws.md, budgets)
SPEED_BUDGET = 0.02
POS_BUDGET = 0.5             # DU per event


# -- E3 -------------------------------------------------------------------------

def _spread_runs(make_runs, paths, limit, frames=600):
    """Every run of every script on one pool, then each script judged: a
    script with many twins no longer holds one slot for all of them (WP31:
    ninja_5_espada's 37 E15 runs timed a gate job out on a slower machine).
    An error in any run of a script is that script's one message."""
    plans, tasks, out = [], [], []
    for path in paths:
        name = os.path.basename(path)
        try:
            runs, judge = make_runs(path, frames, limit=limit)
        except Exception as e:  # noqa: BLE001
            out.append(f"{name}: {type(e).__name__}: {str(e)[-300:]}")
            continue
        plans.append((name, judge, len(tasks), len(runs)))
        tasks += runs
    # The runs of the longest scripts first, so none of them starts last.
    size = [0] * len(tasks)
    for _name, _judge, start, n in plans:
        size[start:start + n] = [n] * n
    order = sorted(range(len(tasks)), key=lambda k: -size[k])

    def go(k):
        try:
            return tasks[k](), None
        except Exception as e:  # noqa: BLE001
            return None, f"{type(e).__name__}: {str(e)[-300:]}"

    results = [None] * len(tasks)
    with ThreadPoolExecutor(max(2, min(8, (os.cpu_count() or 4) - 1))) as pool:
        for k, res in zip(order, pool.map(go, order)):
            results[k] = res
    for name, judge, start, n in plans:
        mine = results[start:start + n]
        errors = [err for _got, err in mine if err]
        if errors:
            out.append(f"{name}: {errors[0]}")
        else:
            out += judge([got for got, _err in mine])
    return out


class TestSpreadRuns(unittest.TestCase):
    """``_spread_runs`` hands each script's judge its own results, in its own
    order, whatever order the pool ran them in; an error stays its script's."""

    def test_each_judge_gets_its_runs_in_order(self):
        def make(path, frames, limit=None):
            n = {"a.py": 3, "b.py": 1, "c.py": 0, "d.py": 2}[path]
            runs = [lambda path=path, i=i: (path, i) for i in range(n)]
            return runs, lambda results, path=path: [f"{path}: {results}"]

        out = _spread_runs(make, ["a.py", "b.py", "c.py", "d.py"], None)
        self.assertEqual(out, ["a.py: [('a.py', 0), ('a.py', 1), ('a.py', 2)]",
                               "b.py: [('b.py', 0)]", "c.py: []",
                               "d.py: [('d.py', 0), ('d.py', 1)]"])

    def test_an_error_is_its_scripts_message(self):
        def make(path, frames, limit=None):
            if path == "bad_plan.py":
                raise OSError("no folder")

            def boom():
                raise ValueError("twin broke")
            runs = [lambda: 1, boom] if path == "bad_run.py" else [lambda: 1]
            return runs, lambda results: []

        out = _spread_runs(make, ["ok.py", "bad_plan.py", "bad_run.py"], None)
        self.assertEqual(out, ["bad_plan.py: OSError: no folder",
                               "bad_run.py: ValueError: twin broke"])


# A gate job's work is a count, sized for a machine much slower than the Mac,
# not a time measured on it (WP33). A 600-frame example run: ~8 s on the Mac,
# ~25 s on a machine 3× slower; a job's pool gets ~2 cores' worth in a busy
# gate. 48 runs × 25 s / 2 = 600 s, a third of the gate's 1 800 s per job.
RUNS_PER_JOB = 48
# A program run is in-process and serial (one engine per process): ~2 s in
# the Mac's loaded gate (511 E3 runs in 1 010 s), ~5 s on a machine 2.5×
# slower. 120 runs × 5 s = 600 s.
PROGRAM_RUNS_PER_JOB = 120


def _pack(sized, cap):
    """``[(runs, unit), …]`` → ``[[unit, …], …]``: as few jobs as hold at most
    ``cap`` runs each, the largest unit first into the lightest job. A unit's
    runs stay in one job (a script's judge needs them all)."""
    jobs = max(1, -(-sum(n for n, _u in sized) // cap))
    load, plan = [0] * jobs, [[] for _ in range(jobs)]
    for n, unit in sorted(sized, key=lambda s: (-s[0], s[1])):
        k = load.index(min(load))
        load[k] += n
        plan[k].append(unit)
    return [sorted(job) for job in plan if job]


def _shard_plan(make_runs, paths, limit, cap=RUNS_PER_JOB):
    """``[[path, …], …]``: the scripts packed by their runs (``_pack``). A
    script whose plan fails counts one run: its job reports the error."""
    sized = []
    for path in paths:
        try:
            n = len(make_runs(path, 600, limit=limit)[0])
        except Exception:  # noqa: BLE001
            n = 1
        if n:
            sized.append((n, path))
    return _pack(sized, cap)


def _shard_classes(prefix, make_runs, doc):
    """One TestCase per job of ``_shard_plan`` (``prefix1``, ``prefix2``, …):
    the runner gives each class of this SPLIT module its own job, so the
    number of jobs follows the examples folder."""
    limit = None if FULL else 1
    for k, paths in enumerate(_shard_plan(make_runs, LAW_SCRIPTS, limit), 1):
        def test_examples(self, paths=paths):
            out = _spread_runs(make_runs, paths, limit)
            self.assertEqual(out, [], "\n".join(m[:800] for m in out))
        name = f"{prefix}{k}"
        globals()[name] = type(name, (unittest.TestCase,), {
            "__doc__": doc, "__module__": __name__, "test_examples": test_examples})


def _program_units(candidates, base_alone):
    """``[(runs, (program, scenario)), …]``: each program × scenario of this
    profile, with the runs its check makes (the base run, one per candidate;
    ``base_alone``: the base runs with no candidate too)."""
    limit = None if FULL else 2
    out = []
    for program in PROGRAMS:
        ns = load_spec(program, "a")
        with open(program_path(program), encoding="utf-8") as fh:
            n = len(candidates(fh.read())[:limit])
        runs = n + 1 if n or base_alone else 0
        scenarios = list(ns["SCENARIOS"]) if FULL else list(ns["SCENARIOS"])[:1]
        out += [(runs, (program, scenario)) for scenario in scenarios if runs]
    return out


def _program_classes(prefix, check, candidates, base_alone, doc):
    """One TestCase per job of program × scenario units, at most
    ``PROGRAM_RUNS_PER_JOB`` runs (``prefix1``, …); they run in order, in
    the job's own process."""
    limit = None if FULL else 2
    for k, units in enumerate(_pack(_program_units(candidates, base_alone),
                                    PROGRAM_RUNS_PER_JOB), 1):
        def test_programs(self, units=units):
            specs, out = {}, []
            for program, scenario in units:
                ns = specs.setdefault(program, load_spec(program, "a"))
                out += check(program, ns, scenario, limit=limit)
            self.assertEqual(out, [], "\n".join(m[:800] for m in out))
        name = f"{prefix}{k}"
        globals()[name] = type(name, (unittest.TestCase,), {
            "__doc__": doc, "__module__": __name__, "test_programs": test_programs})


class TestShardPlan(unittest.TestCase):
    """``_shard_plan``: every script once, no job past the cap, the jobs
    balanced; at the ``ci`` count, no single example outgrows a job."""

    def test_every_script_once_and_no_job_past_the_cap(self):
        sizes = {"a.py": 30, "b.py": 25, "c.py": 20, "d.py": 10, "e.py": 0, "f.py": 5}

        def make(path, frames, limit=None):
            return [None] * sizes[path], None

        plan = _shard_plan(make, sorted(sizes), None, cap=40)
        flat = [p for job in plan for p in job]
        self.assertEqual(sorted(flat), ["a.py", "b.py", "c.py", "d.py", "f.py"])
        self.assertEqual(len(plan), 3)                       # ceil(90 / 40)
        self.assertTrue(all(sum(sizes[p] for p in job) <= 40 for job in plan))

    def test_a_failing_plan_still_has_a_job(self):
        def make(path, frames, limit=None):
            raise OSError("no folder")
        self.assertEqual(_shard_plan(make, ["x.py"], None), [["x.py"]])

    def test_no_example_alone_outgrows_a_job(self):
        # A script's runs share one job; past the cap it needs its runs split.
        for make in (eq.e3_script_runs, eq.e15_script_runs):
            for path in LAW_SCRIPTS:
                n = len(make(path, 600, limit=None)[0])
                with self.subTest(law=make.__name__, script=os.path.basename(path)):
                    self.assertLessEqual(n, RUNS_PER_JOB)

    def test_every_program_scenario_once_and_none_outgrows_a_job(self):
        for candidates, alone in ((eq.swap_candidates, True), (eq.neutral_candidates, False)):
            units = _program_units(candidates, alone)
            plan = _pack(units, PROGRAM_RUNS_PER_JOB)
            with self.subTest(law=candidates.__name__):
                self.assertEqual(sorted(u for job in plan for u in job), sorted(u for _n, u in units))
                self.assertLessEqual(max(n for n, _u in units), PROGRAM_RUNS_PER_JOB)
                size = dict((u, n) for n, u in units)
                self.assertTrue(all(sum(size[u] for u in job) <= PROGRAM_RUNS_PER_JOB
                                    for job in plan))


class TestSpawnOrder(unittest.TestCase):
    def test_shooter_twin(self):
        self.assertEqual(eq.e3_program(f"{TWINS}/shooter_order", WAIT, "wait"), [])



_program_classes("TestSpawnOrderPrograms", eq.e3_program, eq.swap_candidates, True,
                 """E3 on the programs, one job of at most ``PROGRAM_RUNS_PER_JOB`` runs.""")
_shard_classes("TestSpawnOrderExamples", eq.e3_script_runs,
               """E3 on the examples, one job of at most ``RUNS_PER_JOB`` runs.""")


# -- E15 ------------------------------------------------------------------------

class TestRuleNeutrality(unittest.TestCase):
    def test_shield_twin(self):
        with open(eq.program_path_of(f"{TWINS}/shield"), encoding="utf-8") as fh:
            self.assertTrue(eq.neutral_candidates(fh.read()), "no neutral rule (vacuous)")
        self.assertEqual(eq.e15_program(f"{TWINS}/shield", WAIT, "wait"), [])



_program_classes("TestRuleNeutralityPrograms", eq.e15_program, eq.neutral_candidates, False,
                 """E15 on the programs, one job of at most ``PROGRAM_RUNS_PER_JOB`` runs.""")
_shard_classes("TestRuleNeutralityExamples", eq.e15_script_runs,
               """E15 on the examples, one job of at most ``RUNS_PER_JOB`` runs.""")


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
    "constelacao.py": "ACADEMIC (as aviao): the author's own Euler steps (vel += push * dt, "
                      "chase toward a heading) in a pursuit where the nearest prey switches; "
                      "a capture lands a few frames apart at other pacings",
    "affinity.py": "ACADEMIC (as constelacao): the dish is the author's own world step "
                   "(Euler with dt, random jitter drawn every frame, bonds that break with "
                   "probability quebra * dt), so a bond line appears at another time at "
                   "other pacings; Scena only draws it",
    "aviao.py": "ACADEMIC: the author's own Euler step (vel.y -= g * dt) puts the plane a "
                "few pixels apart at uneven pacing; a door passed one frame later",
    "naves_5_modos.py": "ACADEMIC: a self re-arming after / a mode's wait starts each period at "
                      "the frame that noticed the last one (Scena Design, Clocks: 'at least p "
                      "apart', not a rate); uneven pacing drifts the chain",
}
E1_DEV = ("one_ball", "orbitas.py", "naves_1.py", "colisao.py", "ninja_1.py", "pegar_estrelas.py")


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
        paths = [p for p in LAW_SCRIPTS if os.path.basename(p) not in E1_EXCLUDED
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
        for p in LAW_SCRIPTS:
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
