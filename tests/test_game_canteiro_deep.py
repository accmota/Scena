"""Game system test: Canteiro, the long runs (SLOW; sharded by class in gate).

* ``TestPacings`` — the pilot's session at 30, 144 and 240 Hz (the same game
  time), and two rounds at 60 Hz: a rule tested at one pacing is a rule about
  that pacing (Testing Design, "What the game-behaviour probes taught", 3).
* ``TestOracles`` — replay, probe neutrality, reactive configuration twin,
  dt split, Tier C rewrites on the static scenario. Excluded, with the
  reason: the pilot scenarios (the oracles run a plain ``ProgramRun``, which
  has no window, no OS key state and no ``place`` / ``key_repeat``);
  ``camera_moved`` (the game drives the camera every frame); ``time_scaled``
  (the shed's return and the stations run on world timers the oracle's
  rescaled frames do not line up with input).
* ``TestRandomPilots`` — Hypothesis draws pacing, camera turn, lift speed,
  ramp angle and pilot choices.
* ``TestPhysicsCanaries`` / ``TestHandlerCanaries`` / ``TestInputCanaries`` —
  each PG fix the game guards, put back: the named check (or reach minimum)
  must fail.

    python tests/run_tiers.py focused test_game_canteiro_deep --profile ci
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (profiles)
from hypothesis import given, settings, strategies as hs  # noqa: E402

import game_harness as gh  # noqa: E402
import program_oracles  # noqa: E402

CANARIES = os.environ.get("SCENA_CANARIES", "1") != "0"
GAME = "canteiro"


def _ns():
    return gh.spec(GAME).spec_ns()


def _clean(tc, hz, **kw):
    sc = gh.canteiro_scenario(hz, **kw)
    r = gh.run_game(GAME, f"{hz:g}Hz", scenario_obj=sc)
    sp = gh.spec(GAME)
    msgs = gh.problems(r, reach=sp.reach["curta"], checks=sp.checks["curta"])
    tc.assertFalse(msgs, f"{hz:g} Hz {kw} ({r.report.get('frames')} frames, pilot {r.pilot_done}):\n  "
                         + "\n  ".join(msgs))
    return r


class TestPacings(unittest.TestCase):
    maxDiff = None

    def test_30_hz(self):
        _clean(self, 30.0)

    def test_144_hz(self):
        _clean(self, 144.0)

    def test_240_hz(self):
        _clean(self, 240.0)

    def test_two_rounds_turning_camera(self):
        r = _clean(self, 60.0, rounds=2, params={"giro": 8.0})
        self.assertGreaterEqual(r.report["reach"].get("act", 0), 4)


class TestOracles(unittest.TestCase):
    def _ok(self, msgs):
        self.assertFalse(msgs, "\n".join(msgs))

    def test_replay(self):
        self._ok(program_oracles.replay(gh.game_path(GAME), _ns(), "parado"))

    def test_probe_neutral(self):
        self._ok(program_oracles.probe_neutral(gh.game_path(GAME), _ns(), "parado"))

    def test_reactive_config(self):
        self._ok(program_oracles.reactive_config(gh.game_path(GAME), _ns(), "parado"))

    def test_dt_split(self):
        # An input lands half a coarse frame earlier with dt / 2: the hero's x
        # by up to ANDAR * dt / 2; the camera chases it.
        half = 1 / 120
        self._ok(program_oracles.dt_split(gh.game_path(GAME), _ns(), "parado",
                                          {"x": 140 * half + 0.5, "pan_x": 140 * half + 0.5}))

    def test_tier_c_reorder_defs(self):
        self._ok(program_oracles.tier_c(gh.game_path(GAME), _ns(), "parado", "reorder_defs"))


@hs.composite
def canteiro_runs(draw):
    params = {"giro": draw(hs.sampled_from([0.0, 6.0, 15.0])),
              "lift_speed": draw(hs.sampled_from([80.0, 110.0, 150.0])),
              "ramp_angle": draw(hs.sampled_from([15.0, 25.0, 35.0]))}
    hz = draw(hs.sampled_from([30.0, 60.0, 144.0]))
    pilot = {"shift": draw(hs.booleans()), "wander": draw(hs.booleans()), "hud": draw(hs.booleans())}
    seconds = draw(hs.sampled_from([12.0, gh.CANTEIRO_S]))
    return gh.canteiro_scenario(hz, seconds=seconds, seed=draw(hs.integers(0, 9999)),
                                params=params, **pilot), (hz, params, pilot, seconds)


class TestRandomPilots(unittest.TestCase):
    @settings(max_examples=max(2, settings().max_examples // 20), deadline=None)
    @given(canteiro_runs())
    def test_any_run_is_clean(self, drawn):
        sc, what = drawn
        r = gh.run_game(GAME, "random", scenario_obj=sc)
        msgs = gh.problems(r)
        self.assertFalse(msgs, f"{what} seed {sc.seed}:\n  " + "\n  ".join(msgs))


def _collision_module():
    import scena  # noqa: F401
    return sys.modules["scena.collision"]


class _Canary:
    """Each guard of the game, with its fix turned off (the engine's own canary
    switch where the fix has one, else the old behaviour by ``mock``). Three
    classes, so the gate shards them (``run_tiers.SPLIT``)."""

    def _canary(self, patches, expect):
        gh.assert_canary(self, GAME, "curta", patches, expect)


@unittest.skipUnless(CANARIES, "canaries off (SCENA_CANARIES=0)")
class TestPhysicsCanaries(_Canary, unittest.TestCase):
    """Collision Design: Riders, Resolution, Settle, Mass split, ghost contacts."""

    def test_pb2_no_rider_carry(self):
        self._canary([(_collision_module(), "_RIDER_CARRY", False)], ["rider.carried_x"])

    def test_pb4_no_carry_opening(self):
        self._canary([(_collision_module(), "_carry_opening", lambda a, b: (0.0, 0.0, 0.0))],
                     ["lift.contact_open"])

    def test_pe2_skin_along_the_normal(self):
        self._canary([(_collision_module(), "_SKIN_ALONG_MOTION", False)], ["ramp.idle_no_creep"])

    def test_pe1_settle_guesses_from_velocity(self):
        self._canary([(_collision_module(), "_SETTLE_MIN_OVERLAP", False)],
                     ["settle.ball_in_a_wall_leaves_into_the_room", "settle.pair_keeps_sides",
                      "settle.pair_separates"])

    def test_pe3_settle_ignores_static(self):
        self._canary([(_collision_module(), "_SETTLE_STATIC_CLAMP", False)], ["static.shelf_holds"])

    def test_pe4_inherited_leftover_placed(self):
        self._canary([(_collision_module(), "_SWEEP_INHERIT_CLAMP", False)],
                     ["static.thin_wall_holds", "static.shelf_holds"])

    def test_pe5_no_ghost_contact(self):
        CS = _collision_module().CollisionSystem
        self._canary([(CS, "_apply_ghost_contacts", lambda self: None)],
                     ["breakout.bounce_off_destroyed", "breakout.ball_inside"])



@unittest.skipUnless(CANARIES, "canaries off (SCENA_CANARIES=0)")
class TestHandlerCanaries(_Canary, unittest.TestCase):
    """Contacts and handlers, ownership, clone."""

    def test_pb1_exit_forgets_a_left_tag(self):
        CS = _collision_module().CollisionSystem
        self._canary([(CS, "_note_left_tag", lambda self, c, tag: None)],
                     ["spikes.exit_on_untag", "spikes.enter_balanced", "spikes.exit_balanced"])

    def test_pb3_first_exit_rule_hides_the_rest(self):
        CS = _collision_module().CollisionSystem
        real = CS._exit_matches
        self._canary([(CS, "_exit_matches", lambda self, a, b: real(self, a, b)[:1])],
                     ["exit.every_rule_runs"])

    def test_pb5_a_dead_side_stops_the_dispatch(self):
        """S8-2's old rule: once a handler destroyed a side, the contact's
        remaining handlers did not run (who scored depended on spawn order)."""
        mod = _collision_module()
        real = mod._call

        def call(fn, *args):
            if not all(getattr(x, "is_alive", True) for x in args[:2]):
                return None
            return real(fn, *args)
        self._canary([(mod, "_call", call)], ["collide.every_enter_rule_runs"])

    def test_pa4_closure_over_self_is_not_owned(self):
        import scena.process as proc
        self._canary([(proc, "_closure_self", lambda fn: None)], ["closure.owned_by_actor"])

    def test_pc1_clone_ignores_center(self):
        from scena.shapes import Shape
        self._canary([(Shape, "_clone_places_center", False)], ["clone.center_places"])



@unittest.skipUnless(CANARIES, "canaries off (SCENA_CANARIES=0)")
class TestInputCanaries(_Canary, unittest.TestCase):
    """Input streams and the pointer under the camera."""

    def test_pd1_destroyed_button_stays_on(self):
        from scena.uiwidget import Button
        self._canary([(Button, "_abandon_press", lambda self, button: None)],
                     ["button.destroyed_writes_off"])

    def test_pd2_widget_press_visible(self):
        from scena.input import Mouse
        real = Mouse._button_down

        def down(self, button, x, y, *, widget=False):
            return real(self, button, x, y, widget=False)
        self._canary([(Mouse, "_button_down", down)], ["mouse.widget_press_hidden"])

    def test_pd4_widget_hover_only_on_motion(self):
        import scena.orchestration as orch
        self._canary([(orch.WidgetManager, "refresh_hover", lambda self, x, y: None)],
                     ["hover.leaves_with_the_cursor"])

    def test_pd5_drop_only_in_the_press_space(self):
        import scena.orchestration as orch

        def old(self, shape):
            if self._press_in_ui:
                v = self._ptr_view
                hit = None if v is None else self.hit_test_ui(*v, exclude=shape, droppable=True)
                return (hit, v) if hit is not None else (None, None)
            w = self._ptr_world
            hit = None if w is None else self.hit_test(*w, exclude=shape, droppable=True)
            return (hit, w) if hit is not None else (None, None)
        self._canary([(orch.ShapeInteractionManager, "_drop_target", old)],
                     ["reach:drop.caixote", "reach:drop.lixeira"])

    def test_pd6_shift_blocks_a_bare_key(self):
        from scena.input import KeyPressed
        real = KeyPressed._matches

        def matches(self, spec, *, held, keys=None):
            ok = real(self, spec, held=held, keys=keys)
            if ok and not held and isinstance(spec, str) and "+" not in spec \
                    and spec.upper() not in ("SHIFT", "LEFT_SHIFT", "RIGHT_SHIFT") \
                    and "SHIFT" in self._active_families(keys=keys):
                return False
            return ok
        # The hooks hide the key too (Shift held first), so the twin agrees;
        # the symptom is the sprint that never happens.
        self._canary([(KeyPressed, "_matches", matches)],
                     ["keys.keyp_twin", "keys.once_twin", "reach:tecla.correndo"])

    def test_pd7_act_change_drops_the_up(self):
        import scena.orchestration as orch

        def old(self):
            self._presses.clear()
            self._keys_down.clear()
            self._last_click = None
        self._canary([(orch.CanvasManager, "forget_act_input", old)],
                     ["reach:tecla.up_no_ato_novo", "keys.down_twice"])

    def test_pointer_not_resampled_under_a_moving_camera(self):
        import scena.orchestration as orch
        self._canary([(orch.ScenaFramework, "_sync_pointer_level", lambda self, hover=False: None)],
                     ["mouse.world_under_camera"])


if __name__ == "__main__":
    unittest.main()
