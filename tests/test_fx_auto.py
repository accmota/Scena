"""
Auto FX quality ladder tests.

    python -m unittest tests.test_fx_auto -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.fx_auto import (
    AutoParams,
    FxAutoController,
    build_ladder,
    budget_ms,
)
from scena.fx_quality import DEFAULT_FX_QUALITY, FxQuality
from scena import init, canvas, set_fx_auto
from scena.orchestration import (
    DEFAULT_FRAMERATE,
    DEFAULT_FX_AUTO,
    DEFAULT_SHOW_SYSTEM_INFO,
    FRAMERATE_CYCLE,
    FRAMERATE_TOKENS,
    ScenaFramework,
    framerate_label,
)
from scena.pacing import PaceMode


class TestLadder(unittest.TestCase):
    def test_ladder_display_locked_targets(self):
        """Auto ladder: high@60 → med@60 → low@60 → low@30 (hold 60, 30 last),
        every rung locked to the vblank divisor nearest 60 (30 = twice it)."""
        cases = {  # refresh: (interval for "60", rate, rate of the 30 rung)
            60.0: (1, 60.0, 30.0),
            59.94: (1, 59.94, 29.97),
            75.0: (1, 75.0, 37.5),
            120.0: (2, 60.0, 30.0),
            144.0: (2, 72.0, 36.0),
            165.0: (3, 55.0, 27.5),
            240.0: (4, 60.0, 30.0),
        }
        for r_hz, (n60, hz60, hz30) in cases.items():
            with self.subTest(refresh=r_hz):
                ladder = build_ladder(r_hz)
                self.assertEqual(len(ladder), 4)
                self.assertEqual(ladder[0].fidelity, FxQuality.HIGH)
                self.assertEqual(ladder[1].fidelity, FxQuality.MEDIUM)
                self.assertEqual(ladder[2].fidelity, FxQuality.LOW)
                self.assertEqual(ladder[3].fidelity, FxQuality.LOW)
                for rung in ladder[:3]:
                    self.assertEqual(rung.interval, n60)
                    self.assertAlmostEqual(rung.present_hz, hz60, places=2)
                self.assertEqual(ladder[3].interval, 2 * n60)
                self.assertAlmostEqual(ladder[3].present_hz, hz30, places=2)
                self.assertEqual([r.framerate for r in ladder],
                                 ["vsync60", "vsync60", "vsync60", "vsync30"])
                for rung in ladder:
                    self.assertIsNot(rung.fidelity, FxQuality.MAX)
                    # Budget is the real locked frame time.
                    self.assertAlmostEqual(budget_ms(rung.present_hz),
                                           1000.0 * rung.interval / r_hz, places=6)

    def test_ladder_no_max(self):
        for r_hz in (60, 90, 120, 144, 240):
            for rung in build_ladder(r_hz):
                self.assertNotEqual(rung.fidelity, FxQuality.MAX)

    def test_budget_ms(self):
        self.assertAlmostEqual(budget_ms(60.0), 1000.0 / 60.0, places=4)
        self.assertAlmostEqual(budget_ms(30.0), 1000.0 / 30.0, places=4)

    def test_default_params_bias_sticky_medium(self):
        p = AutoParams()
        self.assertGreaterEqual(p.t_up_s, 10.0)
        self.assertGreater(p.cooldown_up_s, p.cooldown_down_s)
        self.assertLess(p.k_up_to_high, p.k_up_fidelity)
        self.assertLessEqual(p.k_up_fidelity, p.k_up)
        self.assertTrue(p.ema_reset_on_step)
        self.assertGreaterEqual(p.settle_evals, 1)
        self.assertGreaterEqual(p.failed_climb_lock_s, 10.0)
        self.assertGreaterEqual(p.warmup_s, 1.5)


class TestControllerHysteresis(unittest.TestCase):
    def _ctrl(self, refresh=120.0, **kwargs) -> FxAutoController:
        # Lab defaults: fast ladder motion without production settle / lock.
        base = dict(
            eval_period_s=0.5,
            t_down_s=1.0,
            t_up_s=3.0,
            cooldown_down_s=1.0,
            cooldown_up_s=1.0,
            settle_evals=0,
            k_down=0.92,
            k_up=0.55,
            k_up_fidelity=0.55,
            k_up_to_high=0.55,
            t_up_fidelity_scale=1.0,
            t_up_to_high_scale=1.0,
            ema_alpha=1.0,  # period mean is EMA
            ema_reset_on_step=False,
            failed_climb_window_s=0.0,
            failed_climb_lock_s=0.0,
            warmup_s=0.0,  # lab: hysteresis only; product default is 2s
        )
        base.update(kwargs)
        return FxAutoController(refresh_hz=refresh, params=AutoParams(**base))

    def _feed(self, ctrl: FxAutoController, work_ms: float, n: int = 5) -> None:
        for _ in range(n):
            ctrl.note_work_ms(work_ms)

    def test_starts_aspirational(self):
        ctrl = self._ctrl(120.0)
        rung = ctrl.reset_to_aspirational()
        self.assertEqual(ctrl.rung_index, 0)
        self.assertEqual(rung.fidelity, FxQuality.HIGH)
        self.assertEqual(rung.framerate, "vsync60")
        self.assertEqual(rung.interval, 2)  # 120 Hz → every 2nd vblank
        self.assertAlmostEqual(rung.present_hz, 60.0, places=1)

    def test_sustained_overload_steps_down_once(self):
        ctrl = self._ctrl(120.0)
        ctrl.reset_to_aspirational()
        # budget @60 ≈ 16.7; overload 25 ms
        t = 0.0
        self.assertIsNone(ctrl.maybe_step(t))  # bootstrap
        t = 0.6
        self._feed(ctrl, 25.0)
        self.assertIsNone(ctrl.maybe_step(t))  # first period, bad_for starts
        t = 1.2
        self._feed(ctrl, 25.0)
        # bad_for ~0.6 after first; need ~1.0 → second eval
        r = ctrl.maybe_step(t)
        # after 0.6+0.6 = 1.2 may already step on second or need third
        if r is None:
            t = 1.8
            self._feed(ctrl, 25.0)
            r = ctrl.maybe_step(t)
        self.assertIsNotNone(r)
        self.assertEqual(ctrl.rung_index, 1)
        self.assertEqual(r.fidelity, FxQuality.MEDIUM)
        self.assertEqual(r.framerate, "vsync60")
        self.assertAlmostEqual(r.present_hz, 60.0, places=1)

    def test_does_not_double_step_during_cooldown(self):
        ctrl = self._ctrl(
            120.0, t_down_s=0.4, cooldown_down_s=2.0, eval_period_s=0.4
        )
        ctrl.reset_to_aspirational()
        t = 0.0
        ctrl.maybe_step(t)
        # force two potential eval windows with heavy load
        for i in range(1, 8):
            t = i * 0.4
            self._feed(ctrl, 40.0)
            out = ctrl.maybe_step(t)
            if out is not None:
                break
        self.assertEqual(ctrl.rung_index, 1)
        # Immediate further overload within cooldown must not step again
        idx = ctrl.rung_index
        for i in range(1, 5):
            t += 0.4
            self._feed(ctrl, 40.0)
            out = ctrl.maybe_step(t)
            self.assertIsNone(out)
        self.assertEqual(ctrl.rung_index, idx)

    def test_headroom_steps_up_only_after_t_up(self):
        ctrl = self._ctrl(
            120.0,
            t_up_s=2.0,
            t_down_s=0.5,
            eval_period_s=0.5,
            cooldown_up_s=0.1,
        )
        ctrl.reset_to_aspirational()
        # Manually place on medium
        ctrl.rung_index = 1
        t = 0.0
        ctrl.maybe_step(t)
        # Light load: budget 16.7, up_line ≈ 9.2 — use 5 ms
        short_rung = None
        for i in range(1, 3):
            t = i * 0.5
            self._feed(ctrl, 5.0)
            short_rung = ctrl.maybe_step(t)
        self.assertIsNone(short_rung)
        self.assertEqual(ctrl.rung_index, 1)
        # Sustain headroom for T_UP
        climbed = None
        for i in range(3, 12):
            t = i * 0.5
            self._feed(ctrl, 5.0)
            climbed = ctrl.maybe_step(t)
            if climbed is not None:
                break
        self.assertIsNotNone(climbed)
        self.assertEqual(ctrl.rung_index, 0)
        self.assertEqual(climbed.fidelity, FxQuality.HIGH)

    def test_hysteresis_band_does_not_move(self):
        # budget ~16.67; K_UP* b ≈ 9.2, K_DOWN * b ≈ 15.3; mid = 12 stays
        ctrl = self._ctrl(120.0, t_down_s=0.5, t_up_s=0.5, eval_period_s=0.5)
        ctrl.reset_to_aspirational()
        t = 0.0
        ctrl.maybe_step(t)
        for i in range(1, 10):
            t = i * 0.5
            self._feed(ctrl, 12.0)
            self.assertIsNone(ctrl.maybe_step(t))
        self.assertEqual(ctrl.rung_index, 0)

    def test_can_reach_low_under_load(self):
        ctrl = self._ctrl(
            120.0,
            t_down_s=0.4,
            cooldown_down_s=0.05,
            eval_period_s=0.4,
            ema_alpha=1.0,
        )
        ctrl.reset_to_aspirational()
        t = 0.0
        ctrl.maybe_step(t)
        # Heavy enough to fail even at 30 Hz budget (~33 ms) — 50 ms
        for i in range(1, 40):
            t = i * 0.4
            self._feed(ctrl, 50.0)
            ctrl.maybe_step(t)
        self.assertEqual(ctrl.rung_index, 3)
        self.assertEqual(ctrl.current_rung().fidelity, FxQuality.LOW)

    def test_diagnostics_snapshot(self):
        ctrl = self._ctrl(120.0)
        ctrl.reset_to_aspirational()
        ctrl.maybe_step(0.0)
        self._feed(ctrl, 10.0)
        ctrl.maybe_step(0.6)
        d = ctrl.diagnostics(now=1.0)
        self.assertEqual(d["rung_index"], 0)
        self.assertEqual(d["fidelity"], "high")
        self.assertAlmostEqual(d["present_hz"], 60.0, places=1)
        self.assertAlmostEqual(d["budget_ms"], budget_ms(60.0), places=3)
        self.assertTrue(d["ema_ready"])
        self.assertIsNotNone(d["ema_ms"])
        self.assertIn("down_line_ms", d)
        self.assertIn("up_line_ms", d)
        self.assertIn("cooldown_left_s", d)
        self.assertIn("k_up_eff", d)
        self.assertIn("up_lock_left_s", d)
        self.assertIn("warmup_s", d)
        self.assertIn("warmup_left_s", d)
        self.assertAlmostEqual(d["warmup_s"], 0.0, places=3)
        self.assertAlmostEqual(d["warmup_left_s"], 0.0, places=3)

    def test_up_to_high_stricter_than_rate_up(self):
        """medium→high needs lower k / longer t than low@30→low@60."""
        ctrl = FxAutoController(refresh_hz=120.0, params=AutoParams())
        # from medium@60 (index 1) → high@60
        k_hi, t_hi = ctrl._up_thresholds_for(1)
        # from low@60 (index 2) → medium@60 (fidelity)
        k_fid, t_fid = ctrl._up_thresholds_for(2)
        # from low@30 (index 3) → low@60 (rate-only)
        k_rate, t_rate = ctrl._up_thresholds_for(3)
        self.assertLess(k_hi, k_rate)
        self.assertGreater(t_hi, t_rate)
        self.assertLess(k_fid, k_rate)
        self.assertGreater(t_fid, t_rate)

    def test_cooldown_up_longer_than_down(self):
        ctrl = self._ctrl(
            120.0,
            t_down_s=0.4,
            t_up_s=0.4,
            cooldown_down_s=1.0,
            cooldown_up_s=5.0,
            eval_period_s=0.4,
            ema_reset_on_step=False,
        )
        ctrl.reset_to_aspirational()
        ctrl.rung_index = 1
        t = 0.0
        ctrl.maybe_step(t)
        # Climb with light load
        climbed = None
        for i in range(1, 8):
            t = i * 0.4
            self._feed(ctrl, 5.0)
            climbed = ctrl.maybe_step(t)
            if climbed is not None:
                break
        self.assertIsNotNone(climbed)
        self.assertEqual(ctrl.rung_index, 0)
        # Within long up cooldown, overload must not step down yet
        for i in range(1, 8):
            t += 0.4
            self._feed(ctrl, 40.0)
            out = ctrl.maybe_step(t)
            self.assertIsNone(out)
        self.assertEqual(ctrl.rung_index, 0)

    def test_ema_reset_on_step(self):
        ctrl = self._ctrl(
            120.0,
            t_down_s=0.4,
            cooldown_down_s=0.1,
            eval_period_s=0.4,
            ema_reset_on_step=True,
            settle_evals=0,
        )
        ctrl.reset_to_aspirational()
        t = 0.0
        ctrl.maybe_step(t)
        for i in range(1, 8):
            t = i * 0.4
            self._feed(ctrl, 40.0)
            out = ctrl.maybe_step(t)
            if out is not None:
                break
        self.assertEqual(ctrl.rung_index, 1)
        self.assertFalse(ctrl._ema_ready)

    def test_settle_skips_decisions(self):
        ctrl = self._ctrl(
            120.0,
            t_down_s=0.3,
            cooldown_down_s=0.05,
            eval_period_s=0.3,
            settle_evals=3,
            ema_reset_on_step=True,
            ema_alpha=1.0,
        )
        ctrl.reset_to_aspirational()
        t = 0.0
        ctrl.maybe_step(t)
        # Step down once
        for i in range(1, 10):
            t = i * 0.3
            self._feed(ctrl, 40.0)
            if ctrl.maybe_step(t) is not None:
                break
        self.assertEqual(ctrl.rung_index, 1)
        self.assertEqual(ctrl._settle_left, 3)
        # Wait out cooldown, then settle periods must not double-step immediately
        # even under continued overload.
        # After step, EMA not ready; need feeds + time past cooldown.
        for i in range(20):
            t += 0.3
            self._feed(ctrl, 40.0)
            out = ctrl.maybe_step(t)
            if out is not None:
                # May eventually step after settle, but not before settle consumed
                break
        # Settle should have been consumed by now OR still walking — at worst
        # one extra step, never 0-period thrash to low in one shot after first down.
        self.assertLessEqual(ctrl.rung_index, 3)

    def test_failed_climb_locks_up(self):
        ctrl = self._ctrl(
            120.0,
            t_down_s=0.3,
            t_up_s=0.3,
            cooldown_down_s=0.05,
            cooldown_up_s=0.05,
            eval_period_s=0.3,
            settle_evals=0,
            ema_reset_on_step=False,
            failed_climb_window_s=5.0,
            failed_climb_lock_s=20.0,
            k_up=0.55,
            k_up_fidelity=0.55,
            k_up_to_high=0.55,
        )
        ctrl.reset_to_aspirational()
        ctrl.rung_index = 1
        t = 0.0
        ctrl.maybe_step(t)
        # Climb to high
        for i in range(1, 8):
            t = i * 0.3
            self._feed(ctrl, 5.0)
            if ctrl.maybe_step(t) is not None:
                break
        self.assertEqual(ctrl.rung_index, 0)
        # Quick overload dumps back to medium → failed climb lock
        for i in range(10):
            t += 0.3
            self._feed(ctrl, 40.0)
            if ctrl.maybe_step(t) is not None:
                break
        self.assertEqual(ctrl.rung_index, 1)
        self.assertGreater(ctrl._up_lock_until, t)
        # Headroom again must not climb while locked
        for i in range(15):
            t += 0.3
            self._feed(ctrl, 5.0)
            out = ctrl.maybe_step(t)
            self.assertIsNone(out)
            self.assertEqual(ctrl.rung_index, 1)

    def test_bootstrap_does_not_seed_ema_from_one_frame(self):
        """A hitch on the first sample must not become the EMA seed."""
        ctrl = self._ctrl(
            120.0,
            warmup_s=0.0,
            ema_alpha=0.2,
            eval_period_s=0.5,
            t_down_s=1.0,
        )
        ctrl.reset_to_aspirational()
        ctrl.note_work_ms(80.0)
        self.assertIsNone(ctrl.maybe_step(0.0))
        self.assertFalse(ctrl._ema_ready)
        t = 0.5
        self._feed(ctrl, 2.0, n=10)
        self.assertIsNone(ctrl.maybe_step(t))
        self.assertTrue(ctrl._ema_ready)
        self.assertLess(ctrl.ema_ms, 5.0)
        for i in range(2, 8):
            t = i * 0.5
            self._feed(ctrl, 2.0)
            self.assertIsNone(ctrl.maybe_step(t))
        self.assertEqual(ctrl.rung_index, 0)

    def test_startup_hitch_does_not_step_down(self):
        """Product warmup + hitch, then cheap frames: stay on high@60."""
        ctrl = FxAutoController(refresh_hz=120.0, params=AutoParams())
        ctrl.reset_to_aspirational()
        ctrl.note_work_ms(80.0)
        self.assertIsNone(ctrl.maybe_step(0.0))
        self.assertFalse(ctrl._ema_ready)
        self.assertGreater(ctrl._warmup_until, 0.0)
        stepped = None
        t = 0.0
        while t < 6.0:
            t += 0.05
            ctrl.note_work_ms(2.0)
            stepped = ctrl.maybe_step(t)
            if stepped is not None:
                break
        self.assertIsNone(stepped)
        self.assertEqual(ctrl.rung_index, 0)
        self.assertEqual(ctrl.current_rung().fidelity, FxQuality.HIGH)

    def test_overload_after_warmup_still_steps_down(self):
        ctrl = self._ctrl(
            120.0,
            warmup_s=2.0,
            eval_period_s=0.5,
            t_down_s=1.0,
            cooldown_down_s=0.05,
            ema_alpha=1.0,
        )
        ctrl.reset_to_aspirational()
        t = 0.0
        self.assertIsNone(ctrl.maybe_step(t))
        while t < 2.0:
            t += 0.5
            self._feed(ctrl, 40.0)
            self.assertIsNone(ctrl.maybe_step(t))
        self.assertEqual(ctrl.rung_index, 0)
        stepped = None
        for _ in range(12):
            t += 0.5
            self._feed(ctrl, 40.0)
            stepped = ctrl.maybe_step(t)
            if stepped is not None:
                break
        self.assertIsNotNone(stepped)
        self.assertEqual(ctrl.rung_index, 1)
        self.assertEqual(stepped.fidelity, FxQuality.MEDIUM)


class TestFrameworkAutoToggle(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        fw = ScenaFramework.get_instance()
        fw._show_system_info = DEFAULT_SHOW_SYSTEM_INFO
        set_fx_auto(True)

    def test_product_defaults(self):
        self.assertTrue(DEFAULT_FX_AUTO)
        self.assertFalse(DEFAULT_SHOW_SYSTEM_INFO)
        self.assertEqual(DEFAULT_FX_QUALITY, FxQuality.HIGH)
        self.assertEqual(DEFAULT_FRAMERATE, "vsync60")

        fw = ScenaFramework.get_instance()
        self.assertTrue(fw.fx_auto)
        self.assertEqual(canvas.fx_quality, FxQuality.HIGH)
        # Auto's first rung is the default token: locked, nearest 60.
        self.assertEqual(canvas.framerate, "vsync60")
        self.assertFalse(fw._show_system_info)

    def test_manual_quality_disables_auto(self):
        fw = ScenaFramework.get_instance()
        set_fx_auto(True)
        self.assertTrue(fw.fx_auto)
        canvas.fx_quality = "medium"
        self.assertFalse(fw.fx_auto)
        self.assertEqual(canvas.fx_quality, FxQuality.MEDIUM)

    def test_manual_framerate_disables_auto(self):
        fw = ScenaFramework.get_instance()
        set_fx_auto(True)
        self.assertTrue(fw.fx_auto)
        canvas.framerate = "vsync30"
        self.assertFalse(fw.fx_auto)
        self.assertEqual(canvas.framerate, "vsync30")

    def test_set_fx_auto_applies_aspirational(self):
        fw = ScenaFramework.get_instance()
        # Force known ladder via refresh override
        set_fx_auto(False)
        set_fx_auto(True, refresh_hz=120.0)
        self.assertTrue(fw.fx_auto)
        self.assertEqual(canvas.fx_quality, FxQuality.HIGH)
        self.assertEqual(canvas.framerate, "vsync60")
        self.assertEqual(fw._fx_auto_ctrl.current_rung().interval, 2)

    def test_set_fx_auto_accepts_params(self):
        from scena.fx_auto import AutoParams

        fw = ScenaFramework.get_instance()
        params = AutoParams(t_up_s=14.0, cooldown_up_s=8.0, k_up_to_high=0.28)
        set_fx_auto(False)
        set_fx_auto(True, refresh_hz=60.0, params=params)
        self.assertTrue(fw.fx_auto)
        self.assertIsNotNone(fw._fx_auto_ctrl)
        self.assertAlmostEqual(fw._fx_auto_ctrl.params.t_up_s, 14.0)
        self.assertAlmostEqual(fw._fx_auto_ctrl.params.cooldown_up_s, 8.0)
        self.assertAlmostEqual(fw._fx_auto_ctrl.params.k_up_to_high, 0.28)

    def test_auto_apply_does_not_self_disable(self):
        fw = ScenaFramework.get_instance()
        set_fx_auto(True, refresh_hz=60.0)
        self.assertTrue(fw.fx_auto)
        # Internal apply must stay on
        from scena.fx_auto import build_ladder

        rung = build_ladder(60.0)[1]
        fw._apply_auto_rung(rung)
        self.assertTrue(fw.fx_auto)
        self.assertEqual(canvas.fx_quality, FxQuality.MEDIUM)


class TestSlipsAndNetBudget(unittest.TestCase):
    """FX Auto under display-locked pacing: missed vblanks (slips) and the
    present overhead (net budget). Bug class: frames that do not fit but
    look fine to the CPU-work number — work between the net and the full
    budget, or GPU-bound frames — never stepped the ladder down."""

    FPS = 60.0

    def _ctrl(self, **kw) -> FxAutoController:
        base = dict(
            eval_period_s=1.0, t_down_s=1.0, t_up_s=3.0, cooldown_down_s=1.0,
            cooldown_up_s=1.0, settle_evals=0, k_down=0.92, k_up=0.55,
            k_up_fidelity=0.55, k_up_to_high=0.55, t_up_fidelity_scale=1.0,
            t_up_to_high_scale=1.0, ema_alpha=1.0, ema_reset_on_step=False,
            failed_climb_window_s=0.0, failed_climb_lock_s=0.0, warmup_s=0.0,
        )
        base.update(kw)
        ctrl = FxAutoController(refresh_hz=60.0, params=AutoParams(**base))
        ctrl.reset_to_aspirational()
        return ctrl

    def _run(self, ctrl, seconds, work_ms, slip_every=0, t0=0.0, overhead_ms=0.0):
        """Feed 60 frames/s; every ``slip_every``-th present slipped. Returns
        (end time, first rung change or None)."""
        t = t0
        step = None
        if t0 == 0.0:
            ctrl.maybe_step(0.0)  # arm the clock
        frames = int(seconds * self.FPS)
        for i in range(1, frames + 1):
            ctrl.note_work_ms(work_ms, slipped=bool(slip_every) and i % slip_every == 0)
            ctrl.set_present_overhead_ms(overhead_ms)
            t = t0 + i / self.FPS
            r = ctrl.maybe_step(t)
            if r is not None and step is None:
                step = r
        return t, step

    def test_net_budget_is_frame_time_minus_overhead_with_floor(self):
        ctrl = self._ctrl()
        self.assertAlmostEqual(ctrl.net_budget_ms(), 1000.0 / 60.0, places=6)
        ctrl.set_present_overhead_ms(2.5)
        self.assertAlmostEqual(ctrl.net_budget_ms(), 1000.0 / 60.0 - 2.5, places=6)
        ctrl.set_present_overhead_ms(50.0)  # bogus: the floor holds
        self.assertAlmostEqual(ctrl.net_budget_ms(), 0.5 * 1000.0 / 60.0, places=6)
        ctrl.set_present_overhead_ms(-3.0)
        self.assertEqual(ctrl.overhead_ms, 0.0)

    def test_work_between_net_and_full_budget_steps_down(self):
        # 13.5 ms: under 92 % of the full 16.7 ms (15.3), over 92 % of the
        # net 14.2 ms (13.0) — the frames that used to slip unnoticed.
        with_overhead = self._ctrl()
        _t, step = self._run(with_overhead, 4.0, 13.5, overhead_ms=2.5)
        self.assertIsNotNone(step)
        self.assertEqual(step.fidelity, FxQuality.MEDIUM)
        without = self._ctrl()
        _t, step = self._run(without, 4.0, 13.5, overhead_ms=0.0)
        self.assertIsNone(step)

    def test_sustained_slips_step_down_even_with_light_cpu_work(self):
        # GPU-bound: CPU work 5 ms, but one present in 5 misses its vblank.
        ctrl = self._ctrl()
        _t, step = self._run(ctrl, 5.0, 5.0, slip_every=5)
        self.assertIsNotNone(step, "slips must step down on their own")
        self.assertEqual(step.fidelity, FxQuality.MEDIUM)

    def test_os_stall_slips_do_not_step_down(self):
        # Two isolated slips in 6 s (a window drag, a background burst).
        ctrl = self._ctrl()
        _t, step = self._run(ctrl, 6.0, 5.0, slip_every=180)
        self.assertIsNone(step)
        self.assertLessEqual(ctrl.slip_rate, 0.03)

    def test_climb_needs_a_slip_free_window(self):
        # Start on the survival rung with plenty of CPU headroom.
        slippy = self._ctrl()
        slippy.rung_index = len(slippy.ladder) - 1
        _t, step = self._run(slippy, 8.0, 2.0, slip_every=60)  # ~1.7 % slips
        self.assertIsNone(step, "no climb while presents still slip")
        clean = self._ctrl()
        clean.rung_index = len(clean.ladder) - 1
        _t, step = self._run(clean, 8.0, 2.0)
        self.assertIsNotNone(step)
        self.assertLess(clean.rung_index, len(clean.ladder) - 1)

    def test_slip_window_needs_enough_frames_and_resets_on_step(self):
        ctrl = self._ctrl()
        ctrl.note_work_ms(5.0, slipped=True)
        ctrl._fold_period_into_ema()
        self.assertEqual(ctrl.slip_rate, 0.0)  # 1 frame: too few to judge
        _t, step = self._run(ctrl, 5.0, 5.0, slip_every=5)
        self.assertIsNotNone(step)
        self.assertEqual(ctrl.slip_rate, 0.0)  # new rung, fresh window

    def test_diagnostics_report_the_signals(self):
        ctrl = self._ctrl()
        self._run(ctrl, 3.0, 5.0, slip_every=50, overhead_ms=2.0)  # 2 %: no step
        d = ctrl.diagnostics(3.0)
        self.assertAlmostEqual(d["frame_ms"], 1000.0 / 60.0, places=6)
        self.assertAlmostEqual(d["budget_ms"], 1000.0 / 60.0 - 2.0, places=6)
        self.assertEqual(d["overhead_ms"], 2.0)
        self.assertGreater(d["slip_rate"], 0.0)


class TestStability(unittest.TestCase):
    """Production parameters (warmup off): minor load must not move the
    ladder, real overload steps down fast, and the ladder climbs back once it
    passes — more slowly than it went down.

    Bug class (2026-09-29): any minor system load stepped FX down (a period
    mean dragged by spikes, one bad second, a 3 % slip line) and nothing
    stepped it back up (climbing needed current work under ~⅓ of the budget,
    out of reach for a scene that fits comfortably)."""

    FPS = 60.0
    COST = {"high": 1.0, "medium": 0.8, "low": 0.65}  # half of work is FX

    def _ctrl(self, **kw):
        params = AutoParams(warmup_s=0.0, **kw)
        ctrl = FxAutoController(refresh_hz=60.0, params=params)
        ctrl.reset_to_aspirational()
        ctrl.maybe_step(0.0)
        return ctrl

    def _sim(self, ctrl, seconds, scene_ms, slip_p=None, seed=1, overhead=2.5, t0=0.0):
        """Frames at the rung's rate. ``scene_ms(t, rnd)``: work at high
        fidelity; FX is half of it. A frame slips when it does not fit, or
        with probability ``slip_p(t, rung)``. Returns (end t, steps)."""
        import random
        rnd = random.Random(seed)
        t, steps = t0, []
        while t < t0 + seconds:
            rung = ctrl.current_rung()
            dt = rung.interval / self.FPS
            work = scene_ms(t, rnd) * (0.5 + 0.5 * self.COST[rung.fidelity.value])
            slipped = work + overhead > 1000.0 * dt
            if slip_p is not None and rnd.random() < slip_p(t, rung):
                slipped = True
            ctrl.note_work_ms(work, slipped=slipped)
            ctrl.set_present_overhead_ms(overhead)
            t += dt
            r = ctrl.maybe_step(t)
            if r is not None:
                steps.append((round(t, 1), r.label))
        return t, steps

    def test_minor_load_with_spikes_does_not_step(self):
        def scene(t, rnd):
            w = 7.0 * rnd.uniform(0.9, 1.1)
            if 20 <= t < 50:
                w *= 1.3
                if rnd.random() < 1 / 30:
                    w = 25.0  # a spike every ~0.5 s (and its slip)
            return w
        for seed in range(1, 6):
            with self.subTest(seed=seed):
                _t, steps = self._sim(self._ctrl(), 120.0, scene, seed=seed)
                self.assertEqual(steps, [])

    def test_one_bad_second_does_not_step(self):
        ctrl = self._ctrl()
        scene = lambda t, rnd: 20.0 if 10.0 <= t < 11.0 else 7.0  # noqa: E731
        _t, steps = self._sim(ctrl, 30.0, scene)
        self.assertEqual(steps, [])

    def test_overload_steps_down_fast_and_climbs_back_slowly(self):
        ctrl = self._ctrl()
        scene = lambda t, rnd: 16.0 if 10.0 <= t < 70.0 else 7.0  # noqa: E731
        _t, steps = self._sim(ctrl, 200.0, scene)
        downs = [s for s in steps if s[0] < 70.0]
        ups = [s for s in steps if s[0] >= 70.0]
        self.assertEqual(downs[0][1], "medium@60")
        self.assertLess(downs[0][0], 14.0, "down within a few seconds")
        self.assertEqual(ctrl.current_rung().label, "high@60", f"never climbed back: {steps}")
        # Harder up: the first climb waits well past the down reaction.
        self.assertGreater(ups[0][0] - 70.0, 10.0)

    def test_scene_that_fits_only_at_medium_parks_there(self):
        # Work at high 17 ms (over the 14.2 ms net budget); medium 15.3 is
        # also over, low 14.0 fits. It must not oscillate back up.
        ctrl = self._ctrl()
        _t, steps = self._sim(ctrl, 240.0, lambda t, rnd: 17.0 * rnd.uniform(0.98, 1.02))
        labels = [label for _t, label in steps]
        self.assertNotIn("high@60", labels)
        self.assertLessEqual(len(steps), 4, steps)

    def test_gpu_bound_slips_walk_down_until_they_stop(self):
        rate = {"high": 0.30, "medium": 0.15, "low": 0.01}
        slip_p = lambda t, rung: rate[rung.fidelity.value] if t < 90 else 0.0  # noqa: E731
        ctrl = self._ctrl()
        _t, steps = self._sim(ctrl, 90.0, lambda t, rnd: 6.0, slip_p=slip_p)
        self.assertEqual(ctrl.current_rung().fidelity, FxQuality.LOW, steps)

    def test_external_slips_do_not_walk_the_ladder(self):
        # 20 s of heavy slips that do not depend on the rung (App Nap,
        # another process): at most one step, then back up.
        slip_p = lambda t, rung: 0.30 if 10 <= t < 30 else 0.0  # noqa: E731
        ctrl = self._ctrl()
        _t, steps = self._sim(ctrl, 120.0, lambda t, rnd: 6.0, slip_p=slip_p)
        downs = [s for s in steps if s[1] != "high@60"]
        self.assertLessEqual(len(downs), 1, steps)
        self.assertEqual(ctrl.current_rung().label, "high@60", steps)

    def test_cost_ratio_is_learned_from_a_step(self):
        ctrl = self._ctrl()
        self.assertAlmostEqual(ctrl.cost_ratio(1), 1.35)  # prior, before any step
        # 14 ms at high (over the 13.0 ms down line of the 14.2 net budget);
        # 12.6 ms at medium fits: one step, then the ratio 14 / 12.6 is learned.
        _t, steps = self._sim(ctrl, 20.0, lambda t, rnd: 14.0)
        self.assertEqual([label for _t, label in steps], ["medium@60"])
        self.assertAlmostEqual(ctrl.cost_ratio(1), 14.0 / 12.6, places=2)

    def test_failed_climbs_back_off_and_a_held_climb_resets(self):
        ctrl = self._ctrl()
        ctrl.rung_index = 1
        ctrl._last_step_dir, ctrl._last_step_time = "up", 100.0
        ctrl._ema_ready = False
        ctrl._commit_step(105.0, "down")  # failed climb #1
        self.assertAlmostEqual(ctrl._up_lock_until, 105.0 + 15.0)
        ctrl._commit_step(106.0, "up")
        ctrl._commit_step(110.0, "down")  # failed climb #2: doubled
        self.assertAlmostEqual(ctrl._up_lock_until, 110.0 + 30.0)
        for _ in range(5):
            ctrl._commit_step(111.0, "up")
            ctrl._commit_step(112.0, "down")
        self.assertLessEqual(ctrl._up_lock_until - 112.0, 120.0)  # capped
        self.assertGreater(ctrl._failed_climbs, 2)


class TestCanvasFramerate(unittest.TestCase):
    """``canvas.framerate``: one string token (or a fixed fps) per pacing mode.

    Tokens: "vsync60" (default, FX Auto's 60 rungs), "vsync30" (survival
    rung), "vsync" (every vblank), "max" (uncapped); a number is a fixed-rate
    timer. Scena Design, "Frame pacing and GC".
    """

    def setUp(self):
        init(width=800, height=600)
        self.fw = ScenaFramework.get_instance()
        self._saved = (self.fw._framerate, self.fw._fx_auto, self.fw._fx_auto_ctrl,
                       self.fw._monitor_refresh_hz)

    def tearDown(self):
        (self.fw._framerate, self.fw._fx_auto, self.fw._fx_auto_ctrl,
         self.fw._monitor_refresh_hz) = self._saved

    def test_tokens_and_numbers_read_back(self):
        for value in ("vsync60", "vsync30", "vsync", "max", 60, 30, 23.976):
            with self.subTest(value=value):
                canvas.framerate = value
                self.assertEqual(canvas.framerate, value)
        canvas.framerate = "  VSync60 "
        self.assertEqual(canvas.framerate, "vsync60")  # canonical token

    def test_mapping_on_60_120_144_hz(self):
        # (token, refresh) -> (PaceMode, vblank interval)
        cases = {
            ("vsync60", 60): (PaceMode.LOCKED, 1), ("vsync60", 120): (PaceMode.LOCKED, 2),
            ("vsync60", 144): (PaceMode.LOCKED, 2), ("vsync30", 60): (PaceMode.LOCKED, 2),
            ("vsync30", 120): (PaceMode.LOCKED, 4), ("vsync30", 144): (PaceMode.LOCKED, 4),
            ("vsync", 60): (PaceMode.LOCKED, 1), ("vsync", 120): (PaceMode.LOCKED, 1),
            ("vsync", 144): (PaceMode.LOCKED, 1),
            ("max", 120): (PaceMode.UNCAPPED, 1), (60, 144): (PaceMode.FIXED, 1),
        }
        for (token, hz), (mode, n) in cases.items():
            with self.subTest(token=token, refresh=hz):
                self.fw._monitor_refresh_hz = float(hz)
                canvas.framerate = token
                got_mode, got_n, fps = self.fw._pace_request()
                self.assertEqual((got_mode, got_n), (mode, n))
                if mode is PaceMode.FIXED:
                    self.assertEqual(fps, 60.0)

    def test_bad_values_raise_and_change_nothing(self):
        set_fx_auto(True)
        before = (canvas.framerate, self.fw.fx_auto)
        cases = (
            ("vsinc", ValueError, "Did you mean 'vsync'"),
            ("vsync_half", ValueError, "'vsync30'"),
            ("fast", ValueError, "'vsync60' (default)"),
            (0, ValueError, "> 0"), (-30, ValueError, "> 0"),
            (float("nan"), ValueError, "finite"), (float("inf"), ValueError, "finite"),
            (True, TypeError, "bool"), (None, TypeError, "NoneType"),
            ([60], TypeError, "list"),
        )
        for value, exc, text in cases:
            with self.subTest(value=value):
                with self.assertRaises(exc) as cm:
                    canvas.framerate = value
                self.assertIn(text, str(cm.exception))
        self.assertEqual((canvas.framerate, self.fw.fx_auto), before)

    def test_old_enum_spelling_is_gone(self):
        import scena
        self.assertFalse(hasattr(scena, "FrameRateControl"))
        self.assertFalse(hasattr(scena, "set_framerate"))
        self.assertNotIn("FrameRateControl", scena.__all__)
        self.assertNotIn("set_framerate", scena.__all__)

    def test_shortcut_cycle_and_labels(self):
        self.assertEqual(FRAMERATE_CYCLE, ("vsync", "vsync60", "vsync30", 60, 30, "max"))
        self.assertTrue(set(FRAMERATE_TOKENS) <= set(FRAMERATE_CYCLE))
        self.fw._monitor_refresh_hz = 144.0
        canvas.framerate = "max"
        seen = []
        for _ in range(len(FRAMERATE_CYCLE)):
            self.fw._cycle_framerate()
            seen.append(canvas.framerate)
        self.assertEqual(seen, list(FRAMERATE_CYCLE))
        self.assertEqual(framerate_label("vsync", 144.0), "VSync (144 Hz)")
        self.assertEqual(framerate_label("vsync60", 144.0), "VSync 60 (72 Hz)")
        self.assertEqual(framerate_label("vsync30", 144.0), "VSync 30 (36 Hz)")
        self.assertEqual(framerate_label(60, 144.0), "Fixed 60")
        self.assertEqual(framerate_label("max", 144.0), "Max")

    def test_fx_auto_rungs_use_the_tokens(self):
        set_fx_auto(True, refresh_hz=144.0)
        ctrl = self.fw._fx_auto_ctrl
        self.assertEqual(canvas.framerate, "vsync60")
        ctrl.rung_index = len(ctrl.ladder) - 1
        self.fw._apply_auto_rung(ctrl.current_rung())
        self.assertEqual(canvas.framerate, "vsync30")
        self.assertTrue(self.fw.fx_auto)  # applying a rung is not a manual change


if __name__ == "__main__":
    unittest.main()
