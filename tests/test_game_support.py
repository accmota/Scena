"""The game system tests' own oracles (tests/game_support.py, tests/game_harness.py).

A side model that cannot fail proves nothing, and one that fails on a correct
trace sends the reader after an engine bug that is not there. Each model is
driven here by hand on a fake clock: a trace that follows the rule passes, and
each way to break the rule (early, late, missing, spurious, repeated) is the
named failure. ``geom`` is held to known values and to scena's own answer on
a few shapes (two doors that agree; the games then compare them under load).
Strategy: design/Testing Design.md, "Game system tests".

    python tests/run_tiers.py focused test_game_support
"""
import json
import math
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game_support as gs  # noqa: E402
import game_harness as gh  # noqa: E402


class Clock:
    """A fake ``scena.clock``: ``tick(dt)`` is one frame up to ``G.frame()``."""

    def __init__(self, G):
        self.time, self.dt, self.G = 0.0, 0.0, G
        G._clock = self

    def tick(self, dt=0.1):
        self.time += dt
        self.dt = dt
        self.G.frame()
        return self.G.frame_no


def ledger():
    G = gs.Ledger("unit")
    return G, Clock(G)


class TestLedger(unittest.TestCase):
    def test_a_failed_check_is_recorded_not_raised(self):
        G, _ = ledger()
        self.assertFalse(G.check(False, "x.y", "why", a=1))
        self.assertTrue(G.equal(1.0, 1.0 + 1e-12, "x.eq", tol=1e-9))
        self.assertFalse(G.within(3, 0, 2, "x.in"))
        r = G.report()
        self.assertEqual(r["fails"], {"x.y": 1, "x.in": 1})
        self.assertEqual(r["evals"], {"x.y": 1, "x.eq": 1, "x.in": 1})
        self.assertEqual(r["failures"][0]["ctx"], {"a": 1})

    def test_raise_mode_raises_at_the_site(self):
        with mock.patch.dict(os.environ, {"SCENA_GAME_CHECKS": "raise"}):
            G, _ = ledger()
        with self.assertRaises(AssertionError):
            G.check(False, "x")

    def test_report_is_plain_data(self):
        G, clk = ledger()
        clk.tick()
        G.event("e", obj=object(), xs=(1, object()))
        G.fail("f", ctx=object())
        json.dumps(G.report())          # nothing of the engine, nothing unserializable

    def test_frame_clock_checks(self):
        G, clk = ledger()
        clk.tick(0.1)
        clk.tick(0.1)
        self.assertEqual(G.report()["n_failures"], 0)
        clk.time -= 0.5                 # time went back
        clk.tick(0.1)
        self.assertIn("clock.monotone", G.fails)
        self.assertIn("clock.dt_is_step", G.fails)

    def test_invariants_every_and_after(self):
        G, clk = ledger()
        seen = []
        G.invariant("inv", lambda: seen.append(G.frame_no), every=2, after=3)
        G.invariant("bad", lambda: "broken", after=5)
        G.invariant("boom", lambda: 1 / 0, after=6)
        for _ in range(7):
            clk.tick()
        self.assertEqual(seen, [3, 5, 7])
        self.assertEqual(G.fails, {"bad": 3, "boom": 2})
        self.assertIn("ZeroDivisionError", G.failures[-1]["msg"])

    def test_a_model_that_raises_is_a_failure(self):
        G, clk = ledger()
        G.model(SimpleNamespace(on_frame=lambda G: 1 / 0))
        clk.tick()
        self.assertIn("model.SimpleNamespace", G.fails)

    def test_lifetimes_by_serial(self):
        G, _ = ledger()

        class Obj:
            pass
        a, b = Obj(), Obj()
        G.born(a, "nave")
        G.born(b, "nave")
        G.died(a, "tiro")
        self.assertEqual((G.alive("nave"), G.deaths("nave"), G.deaths("nave", "tiro")), (1, 1, 1))
        G.died(a, "tiro")
        G.born(b, "nave")
        G.died(Obj(), "x")
        self.assertEqual(G.fails, {"life.died_once": 1, "life.born_once": 1, "life.died_known": 1})

    def test_finish_runs_once_and_releases(self):
        G, _ = ledger()
        calls = []
        G.model(SimpleNamespace(on_frame=lambda G: None, on_finish=lambda G: calls.append("fin"),
                                release=lambda: calls.append("rel")))
        G.invariant("i", lambda: None)
        G.finish()
        G.finish()
        self.assertEqual(calls, ["fin", "rel"])
        self.assertEqual(G._invariants, [])

    def test_digest_moves_with_counters(self):
        G, clk = ledger()
        clk.tick()
        d0 = G.digest()
        G.hit("x")
        self.assertNotEqual(G.digest(), d0)


class TestReached(unittest.TestCase):
    def test_relative_tolerance(self):
        self.assertTrue(gs.reached(0.1 + 0.2, 0.3))
        self.assertTrue(gs.reached(0.3 - 1e-12, 0.3))
        self.assertFalse(gs.reached(0.3 - 1e-6, 0.3))
        self.assertTrue(gs.reached(1000.0 - 1e-7, 1000.0))     # relative above 1
        self.assertFalse(gs.reached(1000.0 - 1e-5, 1000.0))


class TestTimerModel(unittest.TestCase):
    """after(0.25) made in update of frame 1 (early): elapsed 0.1, 0.2, 0.3 -> fires in frame 3."""

    def _run(self, fire_at, *, early=True, every=False, frames=6, cancel_at=None, then=None):
        G, clk = ledger()
        tm = G.model(gs.TimerModel())
        h = SimpleNamespace(remaining=0.25, cancelled=False, done=False)
        for n in range(1, frames + 1):
            clk.tick(0.1)
            if n == 1:
                (tm.expect_every if every else tm.expect_after)(G, "t", h, 0.25, early=early)
            if cancel_at == n:
                h.cancelled = True
                tm.cancelled("t")
            if then is not None:
                then(G, tm, n)
            if n in fire_at:
                tm.fired(G, "t")
        return G

    def test_the_due_frame_passes(self):
        self.assertEqual(self._run({3}).fails, {})

    def test_late_made_timer_counts_from_the_next_frame(self):
        # created after the tick of frame 1: elapsed 0.1 at frame 2 ... 0.3 at frame 4
        self.assertEqual(self._run({4}, early=False).fails, {})
        self.assertIn("timer.fire_frame", self._run({3}, early=False).fails)

    def test_early_and_late_fires_fail(self):
        self.assertIn("timer.fire_frame", self._run({2}).fails)
        G = self._run({4})
        self.assertIn("timer.missed", G.fails)

    def test_a_missing_fire_fails(self):
        self.assertIn("timer.missed", self._run(set()).fails)

    def test_every_keeps_its_cadence(self):
        # 0.25, 0.5, 0.75 -> frames 3, 5, 8
        self.assertEqual(self._run({3, 5, 8}, every=True, frames=9).fails, {})
        self.assertIn("timer.fire_frame", self._run({3, 4}, every=True, frames=7).fails)
        self.assertIn("timer.missed", self._run({3, 6}, every=True, frames=7).fails)

    def test_cancelled_never_fires(self):
        self.assertEqual(self._run(set(), cancel_at=2).fails, {})
        self.assertIn("timer.fired_after_close", self._run({3}, cancel_at=2).fails)

    def test_a_replaced_slot_never_fires(self):
        h2 = SimpleNamespace(remaining=1.0)

        def replace(G, tm, n):
            if n == 2:
                tm.expect_after(G, "t", h2, 1.0, early=True)
        G = self._run(set(), then=replace)
        self.assertEqual(G.fails, {})

    def test_retire_needs_the_handle_cancelled(self):
        G, clk = ledger()
        tm = G.model(gs.TimerModel())
        clk.tick()
        live = SimpleNamespace(remaining=1.0, cancelled=False, done=False)
        tm.expect_after(G, "x", live, 1.0, early=True, scope="ato")
        tm.retire(G, "ato")
        self.assertIn("act.timers_cancelled", G.fails)


class TestTweenModel(unittest.TestCase):
    def _run(self, value, done_at=None, ease=lambda u: u * u):
        G, clk = ledger()
        tw = G.model(gs.TweenModel())
        box = {"v": 0.0}
        for n in range(1, 8):
            clk.tick(0.1)
            if n == 1:
                tw.expect(G, "w", lambda: box["v"], 0.0, 10.0, 0.4, ease=ease, early=True)
            box["v"] = value(n)
            if done_at == n:
                tw.done(G, "w")
        return G

    @staticmethod
    def exact(n):
        return 10.0 * min(1.0, n * 0.1 / 0.4) ** 2

    def test_custom_ease_is_exact(self):
        self.assertEqual(self._run(self.exact, done_at=4).fails, {})

    def test_wrong_value_and_wrong_done_frame(self):
        self.assertIn("tween.value", self._run(lambda n: self.exact(n) + 0.5, done_at=4).fails)
        self.assertIn("tween.done_frame", self._run(self.exact, done_at=3).fails)

    def test_named_ease_bounds_and_monotone(self):
        ok = self._run(lambda n: min(10.0, n * 3.0), done_at=4, ease=None)
        self.assertEqual(ok.fails, {})
        back = self._run(lambda n: [0, 3, 6, 5, 10, 10, 10, 10][n], done_at=4, ease=None)
        self.assertIn("tween.monotone", back.fails)


class TestEdgeModel(unittest.TestCase):
    def _run(self, rise_at, fires, frames=6):
        G, clk = ledger()
        st = {"c": False}
        em = G.model(gs.EdgeModel("x", lambda: st["c"]))
        for n in range(1, frames + 1):
            clk.tick()
            if n == rise_at:
                st["c"] = True      # written in this frame's update ...
            if n in fires:
                em.fired(G)         # ... the flush of frame n fires
        return G

    def test_edge_in_update_fires_that_frame(self):
        self.assertEqual(self._run(2, {2}).fails, {})

    def test_edge_from_input_fires_the_next_flush(self):
        # an input-phase write is seen by frame 3's sample and fired in 3's flush
        self.assertEqual(self._run(2, {3}).fails, {})

    def test_missing_and_spurious(self):
        self.assertIn("when.x.edges", self._run(2, set()).fails)
        self.assertIn("when.x.spurious", self._run(None, {2}).fails)


class TestChangeModel(unittest.TestCase):
    def _run(self, writes, calls, frames=6):
        G, clk = ledger()
        st = {"v": 0}
        cm = G.model(gs.ChangeModel("x", lambda: st["v"]))
        for n in range(1, frames + 1):
            clk.tick()
            if n in writes:
                st["v"] = writes[n]
            if n in calls:
                cm.fired(G, calls[n])
        return G

    def test_each_change_carries_the_new_value(self):
        self.assertEqual(self._run({2: 5, 4: 7}, {2: 5, 4: 7}).fails, {})

    def test_missing_wrong_and_repeated(self):
        self.assertIn("change.x.fires", self._run({2: 5}, {}).fails)
        self.assertIn("change.x.fires", self._run({2: 5}, {2: 6}).fails)
        self.assertIn("change.x.repeat", self._run({2: 5, 4: 5}, {2: 5, 4: 5}).fails)


class TestCoverModel(unittest.TestCase):
    def test_out_rises_then_holds(self):
        G, clk = ledger()
        st = {"v": 0.0}
        cm = G.model(gs.CoverModel(lambda: st["v"]))
        clk.tick()
        cm.start(G, "a", out=True)
        for v in (0.3, 0.6, 1.0):
            st["v"] = v
            clk.tick()
        cm.done(G, "a", out=True)
        clk.tick()
        self.assertEqual(G.fails, {})
        st["v"] = 0.9
        clk.tick()
        self.assertIn("cover.holds", G.fails)

    def test_a_cut_fade_is_not_held_to_its_end(self):
        G, clk = ledger()
        st = {"v": 0.0}
        cm = G.model(gs.CoverModel(lambda: st["v"]))
        clk.tick()
        cm.start(G, "a", out=True)
        st["v"] = 0.4
        clk.tick()
        cm.start(G, "b", out=False)
        cm.done(G, "a", out=True)         # the old one's on_done at once, at 0.4
        st["v"] = 0.2
        clk.tick()
        self.assertEqual(G.fails, {})
        st["v"] = 0.5
        clk.tick()
        self.assertIn("cover.in_falls", G.fails)


class TestSoundModel(unittest.TestCase):
    def test_effects_stack_and_done(self):
        G, clk = ledger()
        sm = G.model(gs.SoundModel())
        h = SimpleNamespace(effects=[], done=False)
        clk.tick(0.1)
        sm.started(G, "s", h, 0.3, slot="m")
        e1, e2 = object(), object()
        h.effects.append(e1)
        sm.fx_add(G, "s", e1)
        h.effects.append(e2)
        sm.fx_add(G, "s", e2)
        h.effects.remove(e1)
        sm.fx_remove(G, "s", e1)
        sm.fx_remove(G, "s", e1)          # a second remove does nothing
        self.assertEqual(G.fails, {})
        h.effects.clear()
        sm.fx_add(G, "s", e1)              # model says [e2, e1], the handle has none
        self.assertIn("sound.effects_stack", G.fails)

    def test_done_not_early(self):
        G, clk = ledger()
        sm = G.model(gs.SoundModel())
        clk.tick(0.1)
        sm.started(G, "s", SimpleNamespace(effects=[], done=False), 0.5)
        clk.tick(0.1)
        sm.done(G, "s")
        self.assertIn("sound.done_not_early", G.fails)

    def test_one_voice_per_slot(self):
        G, clk = ledger()
        sm = G.model(gs.SoundModel())
        clk.tick()
        a = SimpleNamespace(effects=[], done=False)
        sm.started(G, "a", a, None, slot="m")
        sm.started(G, "b", SimpleNamespace(effects=[], done=False), None, slot="m")
        G.finish()
        self.assertEqual(G.fails, {})      # one label per slot; the old voice is closed


class TestGeom(unittest.TestCase):
    g = gs.geom

    def test_closed_forms(self):
        self.assertEqual(self.g.seg_circle((-5, 0), (5, 0), (0, 0), 2), [(-2.0, 0.0), (2.0, 0.0)])
        self.assertEqual(self.g.seg_circle((-5, 3), (5, 3), (0, 0), 2), [])
        self.assertEqual(self.g.seg_seg((0, 0), (2, 2), (0, 2), (2, 0)), (1.0, 1.0))
        self.assertIsNone(self.g.seg_seg((0, 0), (1, 0), (0, 1), (1, 1)))
        sq = [(0, 0), (2, 0), (2, 2), (0, 2)]
        self.assertEqual(sorted(self.g.seg_poly((-1, 1), (3, 1), sq)), [(0.0, 1.0), (2.0, 1.0)])
        self.assertTrue(self.g.point_in_poly((1, 1), sq))
        self.assertFalse(self.g.point_in_poly((3, 1), sq))
        self.assertTrue(self.g.point_in_rect((0, 1.9), 0, 0, 1, 4, 90) is False)
        self.assertTrue(self.g.point_in_rect((1.9, 0), 0, 0, 1, 4, 90))
        self.assertEqual(self.g.closest_on_seg((5, 5), (0, 0), (2, 0)), (2.0, 0.0))
        self.assertEqual(self.g.closest_on_circle_disk((4, 0), (0, 0), 2), (2.0, 0.0))
        x0, y0, x1, y1 = self.g.aabb(self.g.rect_corners(0, 0, 2, 2, 45))
        self.assertAlmostEqual(x1 - x0, 2 * math.sqrt(2))
        self.assertTrue(self.g.swept_circle_hits((-10, 0), (10, 0), 1, (0, 1.5), 1))
        self.assertFalse(self.g.swept_circle_hits((-10, 0), (-5, 0), 1, (0, 0), 1))
        # Grid: row 0 at the top (y up), gap between cells
        self.assertEqual(self.g.grid_cell(0, 100, 210, 100, 2, 1, 10, 1, 0), (160.0, 50.0, 100.0, 100.0))

    def test_sweep_circle_box(self):
        s = self.g.sweep_circle_box
        # straight up into a box's bottom face: touches when the top reaches it
        t, n = s((0, -10), (0, 10), 1, 0, 5, 4, 2)
        self.assertAlmostEqual(t, (4 - 1 - (-10)) / 20.0)
        self.assertEqual(n, (0.0, -1.0))
        # sideways into the left face
        t, n = s((-10, 5), (10, 5), 1, 0, 5, 4, 2)
        self.assertEqual(n, (-1.0, 0.0))
        self.assertAlmostEqual(t, (-2 - 1 + 10) / 20.0)
        # straight at the bottom-right corner (2, 4): the normal leaves the corner
        t, n = s((5, 1), (0, 6), 1, 0, 5, 4, 2)
        self.assertAlmostEqual(t, (3 * math.sqrt(2) - 1) / (5 * math.sqrt(2)))
        self.assertAlmostEqual(n[0], math.sqrt(0.5))
        self.assertAlmostEqual(n[1], -math.sqrt(0.5))
        # a miss, a path that stops short, and a start already overlapping
        self.assertIsNone(s((10, -10), (10, 10), 1, 0, 5, 4, 2))
        self.assertIsNone(s((0, -10), (0, 0), 1, 0, 5, 4, 2))
        self.assertIsNone(s((0, 4.5), (0, 10), 1, 0, 5, 4, 2))

    def test_amp_db_agrees_with_scena(self):
        import scena
        for x in (0.0, -1.0, 1e-4, 0.001, 0.01, 0.1, 0.5, 1.0, 2.0):
            self.assertAlmostEqual(self.g.amp_db(x), scena.amp_db(x), places=12, msg=x)


class TestHarnessRules(unittest.TestCase):
    def test_known_entries_carry_a_reason(self):
        for key, why in gh.KNOWN.items():
            self.assertIn(key[0], gh.GAMES, key)
            self.assertGreater(len(why.strip()), 10, key)
        for msg, why in gh.WARN_OK.items():
            self.assertGreater(len(why.strip()), 10, msg)

    def _result(self, **report):
        rep = {"failures": [], "reach": {}, "evals": {}, "fails": {}, "n_failures": 0}
        rep.update(report)
        return gh.GameResult("armada", "x", rep, SimpleNamespace(errors=lambda: []), {}, [], [], [])

    def test_problems_reports_failures_reach_and_vacuous_checks(self):
        r = self._result(failures=[{"name": "a", "frame": 1, "t": 0.1, "scope": "s", "msg": "m",
                                    "ctx": {}}], reach={"x": 1}, evals={"c": 2})
        msgs = gh.problems(r, reach={"x": 2}, checks=("c", "d"))
        self.assertEqual([m.split()[0] for m in msgs], ["FAIL", "REACH", "VACUOUS"])
        self.assertEqual(gh.problems(self._result(), reach={}, checks=()), [])

    def test_known_still_fail_names_the_entries_no_run_hits(self):
        with mock.patch.dict(gh.KNOWN, {("armada", "old.bug"): "a reason long enough"}):
            self.assertEqual(gh.known_still_fail("armada", [self._result()]), ["old.bug"])

    def test_os_level_run_sends_what_a_window_sends(self):
        """GameRun with ``os_level``: a window (the per-frame pointer sample
        runs), Shift held goes in as ``MOD_SHIFT``, ``key_repeat`` is an OS
        repeat, ``place`` moves the cursor with no motion callback, and
        ``glfw.get_key`` reports the held keys; all given back at close."""
        import glfw
        import scena.orchestration as orch
        calls = []
        r = gh.GameRun(gh.game_path("canteiro"), {}, probes={}, seed=1)
        r.os_level = True
        r.start()
        try:
            fw = r.world.fw
            window = fw._window
            self.assertIsNotNone(window)
            real_key, real_move = fw._handle_key, fw._handle_mouse_move
            fw._handle_key = lambda w, k, s, a, m: (calls.append(("key", k, a, m)), real_key(w, k, s, a, m))
            fw._handle_mouse_move = lambda w, x, y: (calls.append(("move",)), real_move(w, x, y))
            r.key_down("LEFT_SHIFT")
            r.key_down("RIGHT")
            r.key_repeat("RIGHT")
            r.place(10.0, 20.0)
            r.step(1)
            self.assertEqual(calls, [("key", glfw.KEY_LEFT_SHIFT, glfw.PRESS, glfw.MOD_SHIFT),
                                     ("key", glfw.KEY_RIGHT, glfw.PRESS, glfw.MOD_SHIFT),
                                     ("key", glfw.KEY_RIGHT, glfw.REPEAT, glfw.MOD_SHIFT)])
            self.assertEqual(orch.glfw.get_key(fw._window, glfw.KEY_RIGHT), glfw.PRESS)
            self.assertEqual(tuple(r._cursor), r._to_screen(10.0, 20.0))
            r.key_up("RIGHT")
            r.key_up("LEFT_SHIFT")
            r.step(1)
            self.assertEqual(orch.glfw.get_key(fw._window, glfw.KEY_RIGHT), glfw.RELEASE)
            fw._handle_key, fw._handle_mouse_move = real_key, real_move
        finally:
            r.close(strict=False)
        self.assertIsNot(fw._window, window)

    def test_every_game_has_its_tables(self):
        for name, make in gh.GAMES.items():
            sp = make()
            self.assertTrue(os.path.isfile(gh.game_path(name)), name)
            for sc in list(sp.reach) + list(sp.checks):
                self.assertIn(sc, sp.scenarios, f"{name}: a table names scenario {sc!r}")


if __name__ == "__main__":
    unittest.main()
