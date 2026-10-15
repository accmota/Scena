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
(``run_tiers.py``): one gate job per family.

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
from test_scripts_run import scripts  # noqa: E402

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


class TestFixtures(unittest.TestCase):
    def test_the_laws_fixtures_keep_the_snapshot_rule(self):
        out = []
        for name, frames in FIXTURES:
            program = f"tests/laws/fixtures/{name}"
            plain = chaos.run(program, frames=frames, rewrite_it=False)
            base = chaos.run(program, frames=frames, listing=True)
            out += [f"{name}: idle rewrite {d}" for d in chaos.neutral_diff(plain.events, base.events)]
            plans = chaos.draw(base.chaos.doors, SEED, n("fixture"))
            out += _sweep(base, lambda p: chaos.run(program, frames=frames, plan=p, seed=SEED),
                          plans, name, program)
        self.assertEqual(out, [], "\n".join(out))

    @unittest.skipUnless(FULL, "every door x every command: ci / deep")
    def test_s5_every_door_times_every_command(self):
        base = chaos.run(chaos.S5, steps=chaos.S5_STEPS, listing=True)
        plans = chaos.every_door(base.chaos.doors, list(chaos.COMMANDS),
                                 per_door=2 if DEEP else 1, seed=SEED)
        out = _sweep(base, lambda p: chaos.run(chaos.S5, steps=chaos.S5_STEPS, plan=p, seed=SEED),
                     plans, "s5_doors", chaos.S5)
        self.assertEqual(out, [], "\n".join(out))


class TestGames(unittest.TestCase):
    def test_the_games_keep_the_snapshot_rule(self):
        import game_harness as gh
        out = []
        for game in gh.GAMES:
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
        self.assertEqual(out, [], "\n".join(out))


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
        paths = scripts()
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
