"""Laws campaign: the model over the three test families.

Every program scenario (``tests/programs``), every game scenario
(``tests/games``) and every example (``examples/``, the tutorials'
endpoints) is recorded and checked by the model (``tests/laws/model``);
``deep`` also runs every tutorial step. A finding must be in
``tests/laws/known.py`` with its verdict, or it fails the test (triage:
design/Testing Design.md, "Laws and equations"); a known entry that no run
produces any more is stale and fails too.

``dev``: the first scenario of each program spec and game; ``ci`` / ``deep``:
every one. SLOW + SPLIT (``run_tiers.py``): one gate job per family.

    python -m unittest tests.test_laws_families -v
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
from laws import families, model  # noqa: E402
from laws.known import KNOWN  # noqa: E402
from program_support import load_spec  # noqa: E402
from test_prog_invariance import PROGRAMS  # noqa: E402
from test_scripts_run import law_scripts  # noqa: E402

FULL = hypothesis_support.PROFILE in ("ci", "deep")
DEEP = hypothesis_support.PROFILE == "deep"
SCRIPT_FRAMES = 600         # 10 s of game time, as the tutorial step runs
WORKERS = max(2, min(8, (os.cpu_count() or 4) - 1))


def _first_or_all(names):
    names = list(names)
    return names if FULL else names[:1]


def _check(tc, reports, family):
    """No finding outside ``KNOWN``; in ci / deep, every ``KNOWN`` entry of
    this family still happens (shrink-only: a fixed one is removed)."""
    total = model.Report()
    out = []
    seen = set()
    for where, rep in reports:
        total.merge(rep)
        seen.update(rep.signatures())
        out += [f"{where}: {line}" for line in families.unexpected(rep)]
    if FULL:
        out += [f"stale known entry (fixed? remove it): {sig}"
                for sig, (_v, _why, fam) in sorted(KNOWN.items())
                if fam == family and sig not in seen]
    tc.assertEqual(out, [], "\n".join(out))
    return total


class TestPrograms(unittest.TestCase):
    def test_every_program_scenario_keeps_the_laws(self):
        reports = []
        for program in PROGRAMS:
            for spec in ("a", "b"):
                try:
                    ns = load_spec(program, spec)
                except FileNotFoundError:
                    continue
                for scenario in _first_or_all(ns["SCENARIOS"]):
                    reports.append((f"{program}/{spec}/{scenario}",
                                    families.program(program, ns, scenario)))
        _check(self, reports, "programs")


class TestGames(unittest.TestCase):
    def test_every_game_scenario_keeps_the_laws(self):
        import game_harness as gh
        reports = []
        for game in gh.GAMES:
            for scenario in _first_or_all(gh.spec(game).scenarios):
                reports.append((f"{game}/{scenario}", families.game(game, scenario)))
        _check(self, reports, "games")


def _script_reports(paths):
    def one(path):
        try:
            return os.path.basename(path), families.script(path, SCRIPT_FRAMES)
        except Exception as e:  # noqa: BLE001  (a script that fails is a finding)
            rep = model.Report()
            rep.find("RUN", 0, str(e)[-400:], os.path.basename(path))
            return os.path.basename(path), rep
    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(one, paths))


class TestExamples(unittest.TestCase):
    def test_every_example_keeps_the_laws(self):
        paths = law_scripts(hypothesis_support.PROFILE)   # one of a translated pair (WP33)
        self.assertGreater(len(paths), 20)
        _check(self, _script_reports(paths), "examples")


@unittest.skipUnless(DEEP, "every tutorial step: deep only")
class TestTutorialSteps(unittest.TestCase):
    def test_every_tutorial_step_keeps_the_laws(self):
        from tests.test_tutorial_steps import _link_media
        from tests.test_tutorials import extract_steps, tutorial_pages
        with tempfile.TemporaryDirectory(prefix="laws_steps_") as folder:
            _link_media(folder)
            paths = []
            for page in tutorial_pages():
                for step in extract_steps(page):
                    path = os.path.join(folder, f"step_{len(paths):03d}.py")
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(step.code)
                    paths.append(path)
            _check(self, _script_reports(paths), "tutorials")


if __name__ == "__main__":
    unittest.main()
