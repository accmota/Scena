"""Game system test: Caverna (tests/games/caverna.py), quick scenarios.

A platformer on a tracked level file (tests/games/caverna.json): Level, resolve,
touching contacts and slopes, coyote time and a jump buffer, a lift carrying
its rider, a camera on deadzone + chase, parallax and Endless layers, sprite
clips, hitbox parts switched by a formula, History, death and respawn. The
longer run, the L3 oracles, random pilots and canaries:
test_game_caverna_deep.py. Strategy: design/Testing Design.md, "Game system tests".

    python tests/run_tiers.py focused test_game_caverna
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game_harness as gh  # noqa: E402
import program_oracles  # noqa: E402


class TestCaverna(unittest.TestCase):
    maxDiff = None

    def test_level_fixture_parses(self):
        """The tracked level file is a valid scena-level document."""
        from scena.level_format import parse
        with open(os.path.join(gh.GAMES_DIR, "caverna.json"), encoding="utf-8") as fh:
            doc = parse(json.load(fh))
        self.assertGreater(len(doc["items"]), 20)

    def test_seco(self):
        """The level end to end with no falls, the deadzone-only camera."""
        gh.assert_game_clean(self, gh.run_game("caverna", "seco"))

    def test_parado(self):
        """A static script (no pilot): the scenario the dt-split oracle re-times."""
        gh.assert_game_clean(self, gh.run_game("caverna", "parado"))

    def test_teardown(self):
        msgs = program_oracles.teardown(gh.game_path("caverna"), gh.spec("caverna").spec_ns(), "parado")
        self.assertFalse(msgs, "\n".join(msgs))


if __name__ == "__main__":
    unittest.main()
