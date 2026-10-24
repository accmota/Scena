"""Laws campaign, stage S7: chaos doors over the test families (law F3).

The quick module (``test_laws_chaos``) proves the machinery on its fixture;
this one fires commands at the doors of the real programs: the laws
fixtures, the four white-box games, the program specs and the examples
(``deep``: the tutorial steps too). For each member, the idle rewrite must
be the plain run (pass 1, E0 for the chaos machinery), then single-fault
runs (examples: one multi-fault run, shrunk by ddmin on a finding) must
pass every chaos check (``chaos.verdict``). A finding prints its repro line;
open ones go in ``tests/laws/known.py`` (family ``chaos``) with their
verdict, refusals in ``tests/laws/chaos_refusals.py``.

Runs per member scale with the profile (dev / ci / deep); the seed is
``SCENA_CHAOS_SEED`` (default 0; printed on a failure). SLOW + SPLIT
(``run_tiers.py``): one gate job per fixture (``TestFixture_s0_basic``, …),
per game (``TestGame_armada``, …) and per other family (WP34).

    python tests/run_tiers.py focused test_laws_chaos_families
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hypothesis_support  # noqa: E402
from laws import chaos  # noqa: E402
from laws.families import load_trace  # noqa: E402
from laws.known import KNOWN  # noqa: E402
from laws.neutrality import run_script as plain_script  # noqa: E402
from program_support import load_spec  # noqa: E402
from test_prog_invariance import PROGRAMS  # noqa: E402
from test_scripts_run import law_scripts  # noqa: E402

PROFILE = hypothesis_support.PROFILE
FULL = PROFILE in ("ci", "deep")
DEEP = PROFILE == "deep"
SEED = int(os.environ.get("SCENA_CHAOS_SEED", "0"))
RUNS = {"fixture": {"dev": 10, "ci": 30, "deep": 120},
        "game": {"dev": 2, "ci": 6, "deep": 24},
        "program": {"dev": 1, "ci": 3, "deep": 10},
        "faults": {"dev": 2, "ci": 3, "deep": 6}}
FIXTURES = (("s0_basic", 60), ("s1_lifetime", 160), ("s2_contacts", 120), ("s4_timers", 160))
SCRIPT_FRAMES = 300
WORKERS = max(2, min(8, (os.cpu_count() or 4) - 1))


def n(kind: str) -> int:
    return RUNS[kind].get(PROFILE, RUNS[kind]["dev"])


def _first_or_all(names):
    names = list(names)
    return names if DEEP else names[:1]


def _sweep(base, run_plan, plans, where, program):
    """Every plan's findings, each with its repro line."""
    out = []
    for plan in plans:
        got = run_plan([plan])
        found = chaos.verdict(base, got, known=tuple(KNOWN))
        if found:
            out.append(f"{where}: {chaos.repro(program, [plan], SEED)} (seed {SEED}): "
                       f"{found[0][:400]}")
    return out


# One class per fixture and per game: one gate job each (WP34). A family's job
# held every member's runs in one process, one after another (fixtures 507 s,
# games 663 s in the Mac's gate); a member is a fixed count of runs.

def _fixture_findings(name, frames):
    program = f"tests/laws/fixtures/{name}"
    plain = chaos.run(program, frames=frames, rewrite_it=False)
    base = chaos.run(program, frames=frames, listing=True)
    out = [f"{name}: idle rewrite {d}" for d in chaos.neutral_diff(plain.events, base.events)]
    plans = chaos.draw(base.chaos.doors, SEED, n("fixture"))
    return out + _sweep(base, lambda p: chaos.run(program, frames=frames, plan=p, seed=SEED),
                        plans, name, program)


def _game_findings(game):
    import game_harness as gh
    out = []
    for scenario in _first_or_all(gh.spec(game).scenarios):
        where = f"{game}/{scenario}"
        plain = chaos.run_family("game", game, scenario, rewrite_it=False)
        base = chaos.run_family("game", game, scenario, listing=True)
        out += [f"{where}: idle rewrite {d}" for d in chaos.neutral_diff(plain.events, base.events)]
        if base.error is not None:
            out.append(f"{where}: the idle run raised {base.error!r}")
            continue
        plans = chaos.draw(base.chaos.doors, SEED, n("game"))
        out += _sweep(base, lambda p: chaos.run_family("game", game, scenario, plan=p,
                                                       seed=SEED),
                      plans, where, f"game:{game}/{scenario}")
    return out


def _member_class(name, doc, findings):
    def test_keeps_the_snapshot_rule(self):
        out = findings()
        self.assertEqual(out, [], "\n".join(out))
    globals()[name] = type(name, (unittest.TestCase,), {
        "__doc__": doc, "__module__": __name__,
        "test_keeps_the_snapshot_rule": test_keeps_the_snapshot_rule})


for _name, _frames in FIXTURES:
    _member_class(f"TestFixture_{_name}", f"The laws fixture {_name}.",
                  lambda name=_name, frames=_frames: _fixture_findings(name, frames))


def _games():
    import game_harness as gh
    return list(gh.GAMES)


for _game in _games():
    _member_class(f"TestGame_{_game}", f"The white-box game {_game}.",
                  lambda game=_game: _game_findings(game))


# S5: every door kind x every command, one S5 run each (ci: 19 kinds x 22
# commands, ~0.6 s a run alone on the Mac). One job per group of commands; a
# door's picks do not depend on the commands, so the groups are the sweep.
# deep picks two runs per door: half the commands per job keep the count.
S5_PER_DOOR = 2 if DEEP else 1
COMMANDS_PER_JOB = 6 // S5_PER_DOOR
S5_RUNS_PER_JOB = 150


def _command_groups():
    commands = list(chaos.COMMANDS)
    return [commands[i:i + COMMANDS_PER_JOB] for i in range(0, len(commands), COMMANDS_PER_JOB)]


def _s5_plans(base, commands):
    return chaos.every_door(base.chaos.doors, commands, per_door=S5_PER_DOOR, seed=SEED)


def _s5_class(k, commands):
    @unittest.skipUnless(FULL, "every door x every command: ci / deep")
    def test_s5_every_door_times_these_commands(self):
        base = chaos.run(chaos.S5, steps=chaos.S5_STEPS, listing=True)
        out = _sweep(base, lambda p: chaos.run(chaos.S5, steps=chaos.S5_STEPS, plan=p, seed=SEED),
                     _s5_plans(base, commands), "s5_doors", chaos.S5)
        self.assertEqual(out, [], "\n".join(out))
    name = f"TestEveryDoorEveryCommand{k}"
    globals()[name] = type(name, (unittest.TestCase,), {
        "__doc__": f"S5, every door kind x {', '.join(commands)}.", "__module__": __name__,
        "test_s5_every_door_times_these_commands": test_s5_every_door_times_these_commands})


for _k, _commands in enumerate(_command_groups(), 1):
    _s5_class(_k, _commands)


class TestS5Jobs(unittest.TestCase):
    """The command groups are the whole sweep, each job within its count."""

    def test_groups_cover_the_sweep_within_the_count(self):
        base = chaos.run(chaos.S5, steps=chaos.S5_STEPS, listing=True)
        groups = [_s5_plans(base, c) for c in _command_groups()]
        whole = _s5_plans(base, list(chaos.COMMANDS))
        self.assertEqual(sorted(p for g in groups for p in g), sorted(whole))
        self.assertLessEqual(max(len(g) for g in groups), S5_RUNS_PER_JOB)


class TestPrograms(unittest.TestCase):
    def test_the_programs_keep_the_snapshot_rule(self):
        out = []
        for program in PROGRAMS:
            specs = ("a", "b") if DEEP else ("a",)
            for spec in specs:
                try:
                    ns = load_spec(program, spec)
                except FileNotFoundError:
                    continue
                for scenario in _first_or_all(ns["SCENARIOS"]):
                    where = f"{program}/{spec}/{scenario}"
                    plain = chaos.run_family("program", program, scenario, spec_ns=ns,
                                             rewrite_it=False)
                    base = chaos.run_family("program", program, scenario, spec_ns=ns, listing=True)
                    out += [f"{where}: idle rewrite {d}"
                            for d in chaos.neutral_diff(plain.events, base.events)]
                    if base.error is not None:
                        out.append(f"{where}: the idle run raised {base.error!r}")
                        continue
                    plans = chaos.draw(base.chaos.doors, SEED, n("program"))
                    out += _sweep(base, lambda p: chaos.run_family(
                        "program", program, scenario, spec_ns=ns, plan=p, seed=SEED),
                        plans, where, f"program:{where}")
        self.assertEqual(out, [], "\n".join(out))


def _script_findings(path: str, frames: int):
    """One example: the idle rewrite against the plain run, then one
    multi-fault run; a finding is shrunk to the plan that still shows it."""
    where = os.path.basename(path)
    out = []
    with tempfile.TemporaryDirectory(prefix="chaos_plain_") as tmp:
        trace = os.path.join(tmp, "t.jsonl")
        plain_script(path, frames, laws_out=trace)
        plain = load_trace(trace)[:-1]
    base = chaos.run_script(path, frames, listing=True)
    out += [f"{where}: idle rewrite {d}" for d in chaos.neutral_diff(plain, base.events)]
    plan = chaos.draw(base.chaos.doors, SEED, n("faults"))
    if not plan:
        return out

    def fails(sub):
        return bool(chaos.verdict(base, chaos.run_script(path, frames, plan=sub, seed=SEED),
                                  known=tuple(KNOWN)))
    got = chaos.run_script(path, frames, plan=plan, seed=SEED)
    found = chaos.verdict(base, got, known=tuple(KNOWN))
    if found:
        small = chaos.ddmin(list(plan), fails)
        out.append(f"{where}: {chaos.repro(path, small, SEED)}: {found[0][:400]}")
    return out


class TestExamples(unittest.TestCase):
    def test_the_examples_keep_the_snapshot_rule(self):
        paths = law_scripts(hypothesis_support.PROFILE)   # one of a translated pair (WP33)
        self.assertGreater(len(paths), 20)
        with ThreadPoolExecutor(WORKERS) as pool:
            out = [line for lines in pool.map(lambda p: _script_findings(p, SCRIPT_FRAMES), paths)
                   for line in lines]
        self.assertEqual(out, [], "\n".join(out))


@unittest.skipUnless(DEEP, "every tutorial step: deep only")
class TestTutorialSteps(unittest.TestCase):
    def test_the_tutorial_steps_keep_the_snapshot_rule(self):
        from tests.test_tutorial_steps import _link_media
        from tests.test_tutorials import extract_steps, tutorial_pages
        with tempfile.TemporaryDirectory(prefix="chaos_steps_") as folder:
            _link_media(folder)
            paths = []
            for page in tutorial_pages():
                for step in extract_steps(page):
                    path = os.path.join(folder, f"step_{len(paths):03d}.py")
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(step.code)
                    paths.append(path)
            with ThreadPoolExecutor(WORKERS) as pool:
                out = [line for lines in pool.map(lambda p: _script_findings(p, SCRIPT_FRAMES), paths)
                       for line in lines]
        self.assertEqual(out, [], "\n".join(out))


if __name__ == "__main__":
    unittest.main()
