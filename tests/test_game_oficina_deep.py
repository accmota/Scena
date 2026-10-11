"""Game system test: Oficina, the long runs (SLOW; sharded by class in gate).

* ``TestSession`` — two act instances (a reset through the Menu): every
  material drawn, the trash, the seed box, mute, unlink / relink.
* ``TestOraclesSessao`` — replay, probe neutrality, reactive configuration
  twin, over the session. ``TestOraclesParado`` — dt split and ``time_scaled``
  (everything runs on world time, no cover), Tier C rewrites. Two classes so
  the gate shards them (``test_run_tiers``: no job holds half the module).
  Excluded, with the reason: ``camera_moved`` (input arrives
  in view units: under a moved camera the drags land elsewhere in the world).
* ``TestRandomPilots`` — Hypothesis draws the materials and the rounds.
* ``TestCanaries`` — known bugs put back.

    python tests/run_tiers.py focused test_game_oficina_deep --profile ci
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
GAME = "oficina"


def _ns():
    return gh.spec(GAME).spec_ns()


class TestSession(unittest.TestCase):
    maxDiff = None

    def test_sessao(self):
        gh.assert_game_clean(self, gh.run_game(GAME, "sessao"))


class _Oracles(unittest.TestCase):
    def _ok(self, msgs):
        self.assertFalse(msgs, "\n".join(msgs))


class TestOraclesSessao(_Oracles):
    def test_replay(self):
        self._ok(program_oracles.replay(gh.game_path(GAME), _ns(), "sessao"))

    def test_probe_neutral(self):
        self._ok(program_oracles.probe_neutral(gh.game_path(GAME), _ns(), "sessao"))

    def test_reactive_config(self):
        self._ok(program_oracles.reactive_config(gh.game_path(GAME), _ns(), "sessao"))


class TestOraclesParado(_Oracles):
    def test_dt_split(self):
        self._ok(program_oracles.dt_split(gh.game_path(GAME), _ns(), "parado",
                                          {"potencia": 1e-9, "raio": 1e-9}))

    def test_time_scaled(self):
        self._ok(program_oracles.time_scaled(gh.game_path(GAME), _ns(), "parado"))

    def test_tier_c_reorder_defs(self):
        self._ok(program_oracles.tier_c(gh.game_path(GAME), _ns(), "parado", "reorder_defs"))

    def test_tier_c_rename_layers(self):
        self._ok(program_oracles.tier_c(gh.game_path(GAME), _ns(), "parado", "rename_layers"))


@hs.composite
def oficina_runs(draw):
    mats = draw(hs.lists(hs.sampled_from(["fill", "stroke", "paint", "gradiente", "textura"]),
                         min_size=1, max_size=5, unique=True))
    rounds = draw(hs.integers(1, 2))
    return Scenario(params={}, seed=draw(hs.integers(0, 9999)), steps=[drive(
        lambda: gh.OficinaPilot(rounds=rounds, materials=tuple(mats)), 420 * rounds + 60)])


class TestRandomPilots(unittest.TestCase):
    @settings(max_examples=max(2, settings().max_examples // 20), deadline=None)
    @given(oficina_runs())
    def test_any_run_is_clean(self, sc):
        r = gh.run_game(GAME, "random", scenario_obj=sc)
        msgs = gh.problems(r)
        self.assertFalse(msgs, f"seed {sc.seed}:\n  " + "\n  ".join(msgs))


@unittest.skipUnless(CANARIES, "canaries off (SCENA_CANARIES=0)")
class TestCanaries(unittest.TestCase):
    def test_intersections_drop_a_point(self):
        import scena
        real = scena.intersections
        gh.assert_canary(self, GAME, "curta",
                         [(scena, "intersections", lambda a, b: list(real(a, b))[:1])],
                         ["geom.intersections"])

    def test_hover_never_steps(self):
        from scena.orchestration import ScenaFramework
        gh.assert_canary(self, GAME, "curta", [(ScenaFramework, "_step_hover", lambda self: None)],
                         ["reach:hover.enter", "hover.alternates"])

    def test_amp_db_linear(self):
        import scena
        gh.assert_canary(self, GAME, "parado", [(scena, "amp_db", lambda x, floor=-60: min(max(x, 0), 1))],
                         ["audio.amp_db_closed_form"])

    def test_stale_link_pull(self):
        from scena.state import ScalarAnchor
        gh.assert_canary(self, GAME, "curta", [(ScalarAnchor, "_ensure_fresh", lambda self: None)],
                         ["link.generator_a", "link.state_power", "link.constructor_formula"])


if __name__ == "__main__":
    unittest.main()
