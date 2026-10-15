"""Laws campaign, E0 over the three test families: the recorder is neutral.

Every law and equation trusts the laws trace (``tests/laws/trace.py``), so a
run with the recorder must be the run without it — on the black-box
programs (``tests/programs``), the white-box games (``tests/games``) and
every example (``examples/``, the tutorials' endpoints). See
``tests/laws/neutrality.py`` for what is compared.

``dev``: the first scenario of each program and game; ``ci`` / ``deep``:
every scenario. SLOW (``run_tiers.py``): quick skips it.

    python -m unittest tests.test_laws_neutrality -v
"""
from __future__ import annotations

import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402
from hypothesis_support import require_canaries  # noqa: E402
from laws import neutrality, trace  # noqa: E402
from program_support import load_spec  # noqa: E402
from test_prog_invariance import PROGRAMS  # noqa: E402
from test_scripts_run import scripts  # noqa: E402

FULL = hypothesis_support.PROFILE in ("ci", "deep")
EXAMPLE_FRAMES = 120


def _first_or_all(names):
    names = list(names)
    return names if FULL else names[:1]


class TestPrograms(unittest.TestCase):
    def test_every_program_is_the_same_with_the_recorder(self):
        out = []
        for program in PROGRAMS:
            ns = load_spec(program, "a")
            for scenario in _first_or_all(ns["SCENARIOS"]):
                out += neutrality.program(program, ns, scenario)
        self.assertEqual(out, [], "\n".join(out))


class TestGames(unittest.TestCase):
    def test_every_game_is_the_same_with_the_recorder(self):
        import game_harness as gh
        out = []
        for game in gh.GAMES:
            for scenario in _first_or_all(gh.spec(game).scenarios):
                out += neutrality.game(game, scenario)
        self.assertEqual(out, [], "\n".join(out))


class TestExamples(unittest.TestCase):
    def test_every_example_is_the_same_with_the_recorder(self):
        paths = scripts()
        self.assertGreater(len(paths), 20)
        workers = max(2, min(8, (os.cpu_count() or 4) - 1))

        def one(path):
            try:
                return neutrality.script(path, EXAMPLE_FRAMES)
            except Exception as e:  # noqa: BLE001  (a failing script is a finding)
                return [f"{os.path.relpath(path, neutrality.ROOT)}: {e}"]

        with ThreadPoolExecutor(workers) as pool:
            out = [m for msgs in pool.map(one, paths) for m in msgs]
        self.assertEqual(out, [], "\n".join(out))


class TestCanaries(unittest.TestCase):
    """A recorder that holds an author class keeps that class's graph nodes:
    the game census catches it (the bug E0 found in the first recorder)."""

    def setUp(self):
        require_canaries(self)

    def test_holding_classes_is_caught(self):
        real = trace.Recorder._new_label
        held = []

        def planted(self, obj, kind, site):
            held.append(type(obj))                # the plant: a class reference
            return real(self, obj, kind, site)

        try:
            with mock.patch.object(trace.Recorder, "_new_label", planted):
                msgs = neutrality.game("oficina", "parado")
        finally:
            held.clear()
        self.assertTrue(any("leftovers" in m or "survivors" in m for m in msgs), msgs)


if __name__ == "__main__":
    unittest.main()
