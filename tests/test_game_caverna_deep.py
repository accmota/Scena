"""Game system test: Caverna, the long runs (SLOW; sharded by class in gate).

* ``TestRun`` — the pilot's full route: a fall into a gap, a coyote jump, a
  buffered jump, both robots struck, a fall into the lift's pit (the respawn far
  behind brings Endless slots back), the lift ridden to the exit.
* ``TestOracles`` — replay, probe neutrality, reactive configuration twin,
  dt split (static scenario), Tier C rewrites (reorder_defs, rename_layers).
  Excluded, with the reason: ``camera_moved`` (the game drives the camera
  itself every frame); ``time_scaled`` (the covers run on presentation time);
  ``rename_groups`` (level group names are data in caverna.json, which a
  source rewrite does not touch).
* ``TestRandomPilots`` — Hypothesis draws pilot choices and camera mode.
* ``TestCanaries`` — known bugs put back.

    python tests/run_tiers.py focused test_game_caverna_deep --profile ci
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (profiles)
from hypothesis import given, settings, strategies as hs  # noqa: E402

import game_harness as gh  # noqa: E402
import program_oracles  # noqa: E402
from program_support import Scenario, drive  # noqa: E402

CANARIES = os.environ.get("SCENA_CANARIES", "1") != "0"
GAME = "caverna"


def _ns():
    return gh.spec(GAME).spec_ns()


class TestRun(unittest.TestCase):
    maxDiff = None

    def test_volta(self):
        gh.assert_game_clean(self, gh.run_game(GAME, "volta"))


class TestOracles(unittest.TestCase):
    def _ok(self, msgs):
        self.assertFalse(msgs, "\n".join(msgs))

    def test_replay(self):
        self._ok(program_oracles.replay(gh.game_path(GAME), _ns(), "volta"))

    def test_probe_neutral(self):
        self._ok(program_oracles.probe_neutral(gh.game_path(GAME), _ns(), "volta"))

    def test_reactive_config(self):
        self._ok(program_oracles.reactive_config(gh.game_path(GAME), _ns(), "volta"))

    def test_dt_split(self):
        # An input lands half a coarse frame earlier with dt / 2: the hero's x
        # by up to 300 * dt / 2; y follows from the jump's own start time.
        half = 1 / 120
        self._ok(program_oracles.dt_split(gh.game_path(GAME), _ns(), "parado",
                                          {"x": 300 * half + 0.5, "covered": half / 0.25 + 1e-6}))

    def test_tier_c_reorder_defs(self):
        self._ok(program_oracles.tier_c(gh.game_path(GAME), _ns(), "parado", "reorder_defs"))

    def test_tier_c_rename_layers(self):
        self._ok(program_oracles.tier_c(gh.game_path(GAME), _ns(), "parado", "rename_layers"))


@hs.composite
def caverna_runs(draw):
    params = {"camera": draw(hs.sampled_from(["chase", "deadzone"])),
              "fade": draw(hs.sampled_from([0.0, 0.15, 0.3])),
              "endless_layer_response": draw(hs.sampled_from([0.5, 1.0]))}
    fall_gap, fall_pit, coyote = draw(hs.booleans()), draw(hs.booleans()), draw(hs.booleans())
    frames = draw(hs.integers(400, 1800))
    return Scenario(params=params, seed=draw(hs.integers(0, 9999)), steps=[drive(
        lambda: gh.CavernaPilot(fall_gap=fall_gap, fall_pit=fall_pit, coyote=coyote), frames)])


class TestRandomPilots(unittest.TestCase):
    @settings(max_examples=max(2, settings().max_examples // 20), deadline=None)
    @given(caverna_runs())
    def test_any_run_is_clean(self, sc):
        r = gh.run_game(GAME, "random", scenario_obj=sc)
        msgs = gh.problems(r)
        self.assertFalse(msgs, f"params {sc.params} seed {sc.seed}:\n  " + "\n  ".join(msgs))


@unittest.skipUnless(CANARIES, "canaries off (SCENA_CANARIES=0)")
class TestCanaries(unittest.TestCase):
    def test_pm8_timers_late(self):
        import scena.process as proc
        gh.assert_canary(self, GAME, "volta", [(proc, "_DUE_EPS", 0.0)],
                         ["timer.fire_frame", "timer.missed"])

    def test_deadzone_frozen(self):
        import scena
        gh.assert_canary(self, GAME, "seco",
                         [(scena, "deadzone", lambda current, target, size: tuple(current))],
                         ["deadzone.formula"])

    def test_level_angles_negated(self):
        import scena.level as level
        real = level.parse

        def negated(data, source=None):
            doc = real(data, source=source)
            for it in doc["items"]:
                if "angle" in it:
                    it["angle"] = -it["angle"]
            return doc
        gh.assert_canary(self, GAME, "parado", [(level, "parse", negated)],
                         ["level.size_angle", "level.box"])

    def test_recently_forgets(self):
        from scena.process import RememberedManager
        gh.assert_canary(self, GAME, "volta",
                         [(RememberedManager, "__call__", lambda self, name, value, hold=0.1: bool(value))],
                         ["recently.coyote_twin", "recently.buffer_twin"])

    def test_floor_below_always_floor(self):
        from scena.entity import Graphic
        gh.assert_canary(self, GAME, "volta",
                         [(Graphic, "floor_below", lambda self, **kw: True)],
                         ["robo.stays_on_ground"])


if __name__ == "__main__":
    unittest.main()
