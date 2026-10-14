"""Guard: each game system test reaches the exports it claims.

A game (tests/games/<name>.py) lists in ``game_harness.GAMES[...].claims`` the
author names it exists to exercise under load. This module runs every scenario
of every game under the coverage profile hook (tests/program_coverage.py,
``collect_runs``: calls made from the game's own code into scena, mapped onto
``scena.__all__``) and fails when a claim is no longer reached: a game edit
that drops a feature drops it from the system tests too, and says so.

Program coverage (test_program_coverage) stays programs-only: the games are
white-box and do not stand in for a doc-spec'd program. In ``run_tiers.SLOW``.
Strategy: design/Testing Design.md, "Game system tests".

    python tests/run_tiers.py focused test_game_coverage
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scena  # noqa: E402
import game_harness as gh  # noqa: E402
import program_coverage as pc  # noqa: E402


def game_reached(game: str):
    """Exports reached by every scenario of ``game`` (calls, globals, enums)."""
    sp = gh.spec(game)
    path = gh.game_path(game)
    runs = [(f"{game}/{sc}", lambda sc=sc: gh.run_game(game, sc)) for sc in sp.scenarios]
    reached = pc.collect_runs(runs, [path])
    with open(path, encoding="utf-8") as fh:
        texts = [fh.read()]
    return set(reached) | pc.global_objects_touched(texts) | pc.source_reached(texts)


class TestGameClaims(unittest.TestCase):
    maxDiff = None

    def test_claims_are_exports(self):
        for game, make in gh.GAMES.items():
            stale = [c for c in make().claims if c not in scena.__all__]
            self.assertEqual(stale, [], f"{game}: a claim that is not in scena.__all__")

    def _check(self, game):
        claims = set(gh.spec(game).claims)
        self.assertTrue(claims, f"{game} claims nothing")
        missed = sorted(claims - game_reached(game))
        self.assertEqual(missed, [], f"{game} no longer reaches what it claims")

    def test_armada(self):
        self._check("armada")

    def test_caverna(self):
        self._check("caverna")

    def test_oficina(self):
        self._check("oficina")

    def test_canteiro(self):
        self._check("canteiro")


if __name__ == "__main__":
    unittest.main()
