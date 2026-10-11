"""Game system test: Oficina (tests/games/oficina.py), quick scenarios.

A reactive workbench: formulas across objects and a second State, widgets of
every kind, drag / drop / hover / click, geometry and collision queries against
closed forms, visuals checked by pixels at checkpoints, baked and live sound
effects, a null-backend microphone. The two-act session, L3 oracles, random
pilots and canaries: test_game_oficina_deep.py. Strategy: design/Testing
Design.md, "Game system tests".

    python tests/run_tiers.py focused test_game_oficina
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game_harness as gh  # noqa: E402
import program_oracles  # noqa: E402


class TestOficina(unittest.TestCase):
    maxDiff = None

    def test_curta(self):
        """One act: drags, the sliders, three materials drawn and checked by pixels."""
        gh.assert_game_clean(self, gh.run_game("oficina", "curta"))

    def test_parado(self):
        gh.assert_game_clean(self, gh.run_game("oficina", "parado"))

    def test_teardown(self):
        msgs = program_oracles.teardown(gh.game_path("oficina"), gh.spec("oficina").spec_ns(), "parado")
        self.assertFalse(msgs, "\n".join(msgs))


if __name__ == "__main__":
    unittest.main()
