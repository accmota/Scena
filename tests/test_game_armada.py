"""Game system test: Armada (tests/games/armada.py), quick scenarios.

A shooter with acts, fades, widgets, timers, tweens, modes, sound effects and
collision rules, checked from inside by its side models (tests/game_support.py)
and from outside by the driver (tests/game_harness.py). The long campaign, the
L3 oracles, the random pilots and the canaries: test_game_armada_deep.py.
Strategy: design/Testing Design.md, "Game system tests".

    python tests/run_tiers.py focused test_game_armada
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game_harness as gh  # noqa: E402
import program_oracles  # noqa: E402


class TestArmada(unittest.TestCase):
    maxDiff = None

    def test_curta(self):
        """Title, hangar widgets, one wave, a pause, the boss, the end, back to the title."""
        gh.assert_game_clean(self, gh.run_game("armada", "curta"))

    def test_desiste(self):
        """The pause menu's "Desistir": lives to 0, @when fires, the game ends."""
        gh.assert_game_clean(self, gh.run_game("armada", "desiste"))

    def test_parado(self):
        """A static script (no pilot): the scenario the dt-split oracle re-times."""
        gh.assert_game_clean(self, gh.run_game("armada", "parado"))

    def test_teardown(self):
        """After close the census is back and nothing holds a dead object."""
        msgs = program_oracles.teardown(gh.game_path("armada"), gh.spec("armada").spec_ns(), "parado")
        self.assertFalse(msgs, "\n".join(msgs))

    def test_known_shrinks(self):
        """KNOWN is shrink-only: each entry must still fail somewhere."""
        if not any(g == "armada" for g, _ in gh.KNOWN):
            return
        runs = [gh.run_game("armada", s) for s in ("curta", "desiste", "parado")]
        stale = gh.known_still_fail("armada", runs)
        self.assertFalse(stale, f"KNOWN entries that no longer fail; remove them: {stale}")


if __name__ == "__main__":
    unittest.main()
