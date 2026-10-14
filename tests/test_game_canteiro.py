"""Game system test: Canteiro (tests/games/canteiro.py), quick scenarios.

A physics-style world with input under a moving camera: riders on a sideways
and a climbing lift, an idle hero on a ramp, stacks on thin STATIC shelves,
overlapping bubbles, a brick box whose ball bounces off the bricks it breaks,
a turret whose shots and targets both count a hit, parcels through a scale
with two exit rules, spikes that untag the hero; the HUD (a Slider that zooms,
a held Button that breaks, two TextInputs, drags between the ui and the world)
and keys (Shift held, a key held across ``change_act``) while the camera
chases, zooms and may turn. The game-behaviour campaign's seams, kept covered
(Testing Design, "Game system tests" and "PG"). The pacings, the L3 oracles,
random pilots and canaries: test_game_canteiro_deep.py.

    python tests/run_tiers.py focused test_game_canteiro
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game_harness as gh  # noqa: E402
import program_oracles  # noqa: E402


class TestCanteiro(unittest.TestCase):
    maxDiff = None

    def test_curta(self):
        """One round at 60 Hz: the HUD, the walk over every station, the shed."""
        gh.assert_game_clean(self, gh.run_game("canteiro", "curta"))

    def test_parado(self):
        """A static script (no pilot): the scenario the dt-split oracle re-times."""
        gh.assert_game_clean(self, gh.run_game("canteiro", "parado"))

    def test_teardown(self):
        msgs = program_oracles.teardown(gh.game_path("canteiro"), gh.spec("canteiro").spec_ns(),
                                        "parado")
        self.assertFalse(msgs, "\n".join(msgs))


if __name__ == "__main__":
    unittest.main()
