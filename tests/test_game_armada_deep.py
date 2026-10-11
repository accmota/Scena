"""Game system test: Armada, the long runs (SLOW; sharded by class in gate).

* ``TestCampaign`` — two waves, the boss, a pause, crossfaded music, the shield
  tween, swept contacts (fast shots); a defeat by lives.
* ``TestOracles`` — model-free L3 oracles (tests/program_oracles.py) on the game:
  replay, probe neutrality, reactive configuration twin, dt split (the static
  scenario), Tier C rewrites. Excluded, with the reason: ``camera_moved`` (the
  game places by ``canvas.game_view`` and zooms the camera itself);
  ``time_scaled`` (the cover runs on presentation time, so act changes gated by
  a fade move under ``clock.scale``); ``rename_groups`` (the game names its
  groups through data tables for its population invariants).
* ``TestRandomPilots`` — Hypothesis draws game params and pilot behaviour; a
  run must record no failure and leave nothing behind.
* ``TestCanaries`` — known bugs put back: the models must see each.

    python tests/run_tiers.py focused test_game_armada_deep --profile ci
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
GAME = "armada"


def _ns():
    return gh.spec(GAME).spec_ns()


class TestCampaign(unittest.TestCase):
    maxDiff = None

    def test_campanha(self):
        gh.assert_game_clean(self, gh.run_game(GAME, "campanha"))

    def test_derrota(self):
        gh.assert_game_clean(self, gh.run_game(GAME, "derrota"))


class TestOracles(unittest.TestCase):
    def _ok(self, msgs):
        self.assertFalse(msgs, "\n".join(msgs))

    def test_replay(self):
        self._ok(program_oracles.replay(gh.game_path(GAME), _ns(), "curta"))

    def test_probe_neutral(self):
        self._ok(program_oracles.probe_neutral(gh.game_path(GAME), _ns(), "curta"))

    def test_reactive_config(self):
        self._ok(program_oracles.reactive_config(gh.game_path(GAME), _ns(), "curta"))

    def test_dt_split(self):
        # Continuous probes only (a score or a kill depends on sub-frame
        # timing). With dt / 2 an input lands half a coarse frame earlier (it
        # is delivered in the first fine frame), so each tolerance is its
        # rate times dt / 2: the hero at 360 / s, the cover at 1 / 0.25 s.
        half = 1 / 120
        self._ok(program_oracles.dt_split(gh.game_path(GAME), _ns(), "parado",
                                          {"heroi_x": 360 * half + 1e-6,
                                           "covered": half / 0.25 + 1e-6}))

    def test_tier_c_reorder_defs(self):
        self._ok(program_oracles.tier_c(gh.game_path(GAME), _ns(), "parado", "reorder_defs"))

    def test_tier_c_rename_layers(self):
        self._ok(program_oracles.tier_c(gh.game_path(GAME), _ns(), "parado", "rename_layers"))


@hs.composite
def armada_runs(draw):
    params = {
        "waves": draw(hs.integers(1, 2)), "cols": draw(hs.integers(2, 6)),
        "rows": draw(hs.integers(1, 2)), "boss_hp": draw(hs.integers(3, 12)),
        "lives": draw(hs.integers(1, 4)), "god": draw(hs.booleans()),
        "fade": draw(hs.sampled_from([0.0, 0.1, 0.25, 0.4])),
        "mergulho": draw(hs.sampled_from([0.1, 0.35, 0.9])),
        "vel_tiro": draw(hs.sampled_from([620, 1500, 6000])),
        "music": draw(hs.booleans()),
    }
    pause = draw(hs.one_of(hs.none(), hs.integers(30, 400)))
    dodge = draw(hs.booleans())
    desistir = draw(hs.booleans())
    frames = draw(hs.integers(500, 1600))
    seed = draw(hs.integers(0, 10_000))
    return Scenario(params=params, seed=seed, steps=[drive(
        lambda: gh.ArmadaPilot(rounds=2, pause_at=pause, dodge=dodge, desistir=desistir),
        frames)])


class TestRandomPilots(unittest.TestCase):
    @settings(max_examples=max(2, settings().max_examples // 20), deadline=None)
    @given(armada_runs())
    def test_any_run_is_clean(self, sc):
        r = gh.run_game(GAME, "random", scenario_obj=sc)
        msgs = gh.problems(r)
        self.assertFalse(msgs, f"params {sc.params} seed {sc.seed}:\n  " + "\n  ".join(msgs))


@unittest.skipUnless(CANARIES, "canaries off (SCENA_CANARIES=0)")
class TestCanaries(unittest.TestCase):
    """Each planted bug must trip the model written for it."""

    def test_pm8_timers_late(self):
        import scena.process as proc
        gh.assert_canary(self, GAME, "curta", [(proc, "_DUE_EPS", 0.0)],
                         ["timer.fire_frame", "timer.missed", "ready.cadence", "tween.done_frame"])

    def test_custom_ease_ignored(self):
        import scena.process as proc
        from scena.easing import MappingFunctions
        gh.assert_canary(self, GAME, "campanha",
                         [(proc, "resolve_ease", lambda ease, what="ease": MappingFunctions.linear)],
                         ["tween.value"])

    def test_swept_detection_off(self):
        from scena.collision import CollisionSystem
        gh.assert_canary(self, GAME, "campanha",
                         [(CollisionSystem, "_swept_contacts", lambda self, *a, **k: ({}, 0, 0))],
                         ["ccd.no_tunnel", "reach:collide.swept"])

    def test_ac3_hit_feedback_in_authors_stack(self):
        from scena.postfx import PostFxStack
        gh.assert_canary(self, GAME, "curta",
                         [(PostFxStack, "__iter__", lambda self: iter(self._effects))],
                         ["act.effects_restored"])

    def test_ac6_on_collide_method_args(self):
        col = sys.modules["scena.collision"]     # ``scena.collision`` is the facade
        gh.assert_canary(self, GAME, "campanha", [(col, "_pair_method_adapter", lambda bound: bound)],
                         ["reach:orb.pego", "reach:tween.done"])


if __name__ == "__main__":
    unittest.main()
