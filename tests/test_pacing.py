"""Frame pacing (scena/pacing.py): interval choice, vblank grid, dt from the
display, and the three present strategies driven by a fake clock.

Bug classes guarded here:

* **Schedule drift** — the old PRECISION rule ``target = start + period``
  accumulated lateness (59.815 Hz instead of 60 on Windows → beat judder every
  5.4 s). The TIMER schedule is absolute: no drift over 10⁵ frames.
* **Trusting a swap that does not block** — NATIVE falls back to TIMER when
  frames come out faster than the vblank interval.
* **Presenting near the latch** — DISPLAY_LINK presents just after a vblank,
  on schedule, and slips to the next vblank (never between) when late.

    python -m unittest tests.test_pacing -v
"""
from __future__ import annotations

import random
import unittest

from scena.input import Clock
from scena.pacing import (
    DT_DEBT_DEADZONE,
    NATIVE_CHECK_FRAMES,
    PRESENT_AFTER_VBLANK_S,
    DtSmoother,
    FramePacer,
    PaceMode,
    PeriodEstimator,
    Strategy,
    VblankGrid,
    interval_near,
    locked_interval,
    needs_timer_resolution,
)

P60 = 1.0 / 60.0019  # the Windows laptop's measured refresh


class FakeTime:
    """perf_counter / sleep stand-in. Each ``now()`` costs ``tick`` (so spin
    loops end); ``sleep`` oversleeps by ``over`` (Windows ~0.7 ms)."""

    def __init__(self, t0: float = 100.0, tick: float = 2e-6, over: float = 0.0) -> None:
        self.t = t0
        self.tick = tick
        self.over = over
        self.sleeps = []

    def now(self) -> float:
        self.t += self.tick
        return self.t

    def sleep(self, d: float) -> None:
        self.sleeps.append(d)
        self.t += max(0.0, d) + self.over


class TestIntervalChoice(unittest.TestCase):
    def test_interval_near_60_table(self):
        table = {48: 1, 50: 1, 59.94: 1, 60: 1, 75: 1, 90: 1, 100: 2, 120: 2,
                 144: 2, 165: 3, 180: 3, 240: 4, 360: 6}
        for hz, n in table.items():
            with self.subTest(refresh=hz):
                self.assertEqual(interval_near(hz, 60.0), n)

    def test_interval_near_never_below_floor_for_60(self):
        for hz in range(48, 361):
            n = interval_near(hz, 60.0)
            self.assertTrue(hz / n >= 50.0 or n == 1, (hz, n))

    def test_interval_near_other_targets(self):
        self.assertEqual(interval_near(144, 144), 1)
        self.assertEqual(interval_near(60, 30), 2)
        self.assertEqual(interval_near(0, 60), 1)
        self.assertEqual(interval_near(float("nan"), 60), 1)

    def test_locked_interval_30_is_twice_60(self):
        for hz in (60, 75, 120, 144, 165, 240):
            self.assertEqual(locked_interval(hz, 30.0), 2 * interval_near(hz, 60.0))
            self.assertEqual(locked_interval(hz, 60.0), interval_near(hz, 60.0))


class TestVblankGrid(unittest.TestCase):
    def _stamps(self, n=40, period=P60, t0=10.0, jitter=0.0, skip=(), seed=1):
        rnd = random.Random(seed)
        return [t0 + i * period + rnd.uniform(-jitter, jitter)
                for i in range(n) if i not in skip]

    def test_fit_regular_and_sparse(self):
        g = VblankGrid(period_hint=1 / 60.0)
        for t in self._stamps(skip={3, 4, 10, 11, 12}):
            g.add(t)
        ok, reason = g.health(g.newest + 0.001)
        self.assertTrue(ok, reason)
        self.assertAlmostEqual(g.period, P60, delta=1e-9)
        v = g.vblank_at_or_after(g.newest + 0.001)
        self.assertAlmostEqual(v, g.newest + P60, delta=1e-7)

    def test_fit_is_robust_to_small_jitter(self):
        g = VblankGrid(period_hint=1 / 60.0)
        for t in self._stamps(jitter=0.0002):
            g.add(t)
        self.assertAlmostEqual(g.period, P60, delta=2e-5)
        self.assertTrue(g.health(g.newest)[0])

    def test_non_monotonic_rejected(self):
        g = VblankGrid()
        for t in (1.0, 1.0166, 1.0100, 1.0333):
            g.add(t)
        self.assertEqual(g.count, 3)
        self.assertEqual(g.rejected, 1)

    def test_unhealthy_reasons(self):
        g = VblankGrid()
        self.assertFalse(g.health(0.0)[0])  # too few
        for t in self._stamps():
            g.add(t)
        ok, reason = g.health(g.newest + 5 * P60)
        self.assertFalse(ok)
        self.assertIn("stale", reason)
        slow = VblankGrid()
        for t in self._stamps(period=0.1):  # 10 Hz is not a display
            slow.add(t)
        ok, reason = slow.health(slow.newest)
        self.assertFalse(ok)
        self.assertIn("20–300", reason)
        vrr = VblankGrid(period_hint=1 / 60.0)
        rnd = random.Random(3)
        t = 0.0
        for _ in range(40):  # VRR-like: intervals wander 14–19 ms
            t += rnd.uniform(0.014, 0.019)
            vrr.add(t)
        ok, reason = vrr.health(t)
        self.assertFalse(ok)
        self.assertIn("irregular", reason)


class TestPeriodEstimator(unittest.TestCase):
    def test_converges_from_noisy_swap_returns(self):
        est = PeriodEstimator(nominal=1 / 60.0)  # GLFW's integer 60
        rnd = random.Random(7)
        prev = 0.0025
        for i in range(1, 400):
            k = 2 if i % 50 == 0 else 1  # a held frame now and then
            t = (i if k == 1 else i) * P60 + 0.0025 + rnd.uniform(-0.0008, 0.0008)
            if k == 2:
                continue
            est.note(t - prev)
            prev = t
        self.assertTrue(est.converged)
        # Σd/Σk: endpoint noise (±0.8 ms) / ~240 periods.
        self.assertAlmostEqual(est.period, P60, delta=7e-6)

    def test_ignores_non_vblank_intervals(self):
        est = PeriodEstimator(nominal=1 / 60.0, min_samples=1)
        est.note(0.025)  # 1.5 periods: not near a multiple
        self.assertFalse(est.converged)


class TestDtSmoother(unittest.TestCase):
    def test_snaps_noisy_intervals_to_whole_periods(self):
        """Frame starts = vblank + wake noise (±1 ms): intervals telescope, so
        the debt stays inside the dead zone and every dt is exactly P."""
        s = DtSmoother()
        rnd = random.Random(1)
        prev = 0.0
        for i in range(1, 10_000):
            t = i * P60 + rnd.uniform(-0.001, 0.001)
            self.assertEqual(s.step(t - prev, P60), P60)
            prev = t

    def test_slip_is_two_periods(self):
        s = DtSmoother()
        self.assertEqual(s.step(2 * P60 + 0.0007, P60), 2 * P60)
        self.assertEqual(s.step(3 * P60 - 0.0009, P60), 3 * P60)

    def test_off_grid_passes_through(self):
        s = DtSmoother()
        self.assertEqual(s.step(0.1234, P60), 0.1234)  # 7.4 periods
        self.assertEqual(s.step(0.025, P60), 0.025)  # 1.5 periods: a real hitch
        self.assertEqual(s.step(0.016, None), 0.016)

    def test_world_time_tracks_wall_time(self):
        """Period estimate 0.01% off: debt is bled back past the dead zone."""
        s = DtSmoother()
        est = P60 * 1.0001
        wall = world = prev = 0.0
        rnd = random.Random(2)
        for i in range(1, 100_000):
            t = i * P60 + rnd.uniform(-0.0005, 0.0005)
            raw = t - prev
            prev = t
            wall += raw
            world += s.step(raw, est)
            self.assertLess(abs(wall - world), (DT_DEBT_DEADZONE + 0.05) * P60 + 0.001)


class TestClockSmoothHook(unittest.TestCase):
    def test_real_dt_raw_dt_smoothed(self):
        c = Clock()
        c._mark_play_start()
        t = c._last_time + 0.0171
        c._tick(t, smooth=lambda raw: P60)
        self.assertAlmostEqual(c.real_dt, 0.0171, places=9)
        self.assertEqual(c.dt, P60)

    def test_smooth_result_still_clamped(self):
        c = Clock()
        c._mark_play_start()
        c._tick(c._last_time + 1.0, smooth=lambda raw: raw)
        self.assertEqual(c.dt, 0.25)


class TestConfigure(unittest.TestCase):
    def _pacer(self, platform, factory=None):
        ft = FakeTime()
        swaps = []
        p = FramePacer(now=ft.now, sleep=ft.sleep, set_swap_interval=swaps.append,
                       platform=platform, display_link_factory=factory,
                       warn=lambda m: None)
        return p, swaps

    def test_strategies(self):
        p, swaps = self._pacer("win32")
        p.configure(mode=PaceMode.LOCKED, interval=2, refresh_hz=144)
        self.assertIs(p.strategy, Strategy.NATIVE)
        self.assertEqual(swaps[-1], 2)
        p.configure(mode=PaceMode.FIXED, fps=60)
        self.assertIs(p.strategy, Strategy.TIMER)
        self.assertEqual(swaps[-1], 0)
        p.configure(mode=PaceMode.UNCAPPED)
        self.assertIs(p.strategy, Strategy.UNCAPPED)

    def test_darwin_without_link_falls_back_to_timer(self):
        p, swaps = self._pacer("darwin")
        p.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)
        self.assertIs(p.strategy, Strategy.TIMER)
        self.assertIsNotNone(p.fallback_reason)
        self.assertEqual(swaps[-1], 0)

    def test_darwin_link_start_failure_falls_back(self):
        class Broken:
            error = "CVDisplayLinkCreate failed"

            def start(self):
                return False

        p, _ = self._pacer("darwin", factory=Broken)
        p.configure(mode=PaceMode.LOCKED, refresh_hz=60)
        self.assertIs(p.strategy, Strategy.TIMER)
        self.assertIn("CVDisplayLinkCreate", p.fallback_reason)

    def test_timer_resolution_only_old_windows(self):
        self.assertTrue(needs_timer_resolution("win32", (3, 10)))
        self.assertFalse(needs_timer_resolution("win32", (3, 11)))
        self.assertFalse(needs_timer_resolution("win32", (3, 14)))
        self.assertFalse(needs_timer_resolution("darwin", (3, 10)))


def run_frames(pacer, ft, n, work, swap=None):
    """Drive the loop: work → wait_for_present → swap → presented.
    Returns the present times (after the swap)."""
    out = []
    for i in range(n):
        ft.t += work(i) if callable(work) else work
        pacer.wait_for_present()
        if swap is not None:
            swap(ft)
        pacer.presented()
        out.append(ft.t)
    return out


class TestTimer(unittest.TestCase):
    def test_absolute_schedule_does_not_drift(self):
        """The 59.815 Hz bug class: late wakes must not stretch the schedule."""
        ft = FakeTime(over=0.0007)  # Windows-like sleep overshoot
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="win32", warn=lambda m: None)
        p.configure(mode=PaceMode.FIXED, fps=60.0)
        n = 100_000
        rnd = random.Random(5)
        t = run_frames(p, ft, n, lambda i: rnd.uniform(0.003, 0.010))
        rate = (n - 1) / (t[-1] - t[0])
        self.assertAlmostEqual(rate, 60.0, delta=0.0005)
        # Presents never drift off the absolute grid by more than the spin
        # granularity (+ the one fake tick per now()).
        grid0 = t[0]
        worst = max(abs((x - grid0) - round((x - grid0) * 60.0) / 60.0) for x in t[10:])
        self.assertLess(worst, 0.0002)

    def test_sleeps_most_of_the_wait(self):
        ft = FakeTime(over=0.0007)
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="win32", warn=lambda m: None)
        p.configure(mode=PaceMode.FIXED, fps=60.0)
        run_frames(p, ft, 600, 0.004)
        slept = sum(ft.sleeps)
        self.assertGreater(slept / (600 * (1 / 60.0 - 0.004)), 0.8)

    def test_resync_after_long_hitch(self):
        ft = FakeTime()
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="linux", warn=lambda m: None)
        p.configure(mode=PaceMode.FIXED, fps=60.0)
        t = run_frames(p, ft, 5, 0.002)
        ft.t += 0.5  # a hitch: no burst of catch-up frames afterwards
        t2 = run_frames(p, ft, 3, 0.002)
        self.assertGreater(t2[1] - t2[0], 0.9 / 60.0)
        self.assertGreater(t[-1], 0)



class TestNative(unittest.TestCase):
    def _vsync_swap(self, period):
        def swap(ft):
            ft.t = (int(ft.t / period) + 1) * period + 0.0025
        return swap

    def test_blocking_swap_stays_native_and_learns_period(self):
        ft = FakeTime()
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="win32", warn=lambda m: None)
        p.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)
        run_frames(p, ft, 300, 0.003, swap=self._vsync_swap(P60))
        self.assertIs(p.strategy, Strategy.NATIVE)
        self.assertAlmostEqual(p.vblank_period(), P60, delta=1e-6)
        self.assertEqual(p.smooth_dt(P60 + 0.0006), p.vblank_period())

    def test_non_blocking_swap_falls_back_to_timer(self):
        ft = FakeTime()
        warned = []
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="win32", warn=warned.append)
        swaps = []
        p._set_swap_interval = swaps.append
        p.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)
        run_frames(p, ft, NATIVE_CHECK_FRAMES + 5, 0.003)
        self.assertIs(p.strategy, Strategy.TIMER)
        self.assertEqual(swaps[-1], 0)
        self.assertEqual(len(warned), 1)
        self.assertIn("VSync is not blocking", warned[0])
        # Still paced at the display rate afterwards.
        t = run_frames(p, ft, 120, 0.003)
        self.assertAlmostEqual((len(t) - 1) / (t[-1] - t[0]), 60.0, delta=0.05)
        # Reconfiguring at the same refresh keeps the verdict (no re-warn).
        p.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)
        self.assertIs(p.strategy, Strategy.TIMER)

    def test_heavy_frames_do_not_trigger_the_check(self):
        ft = FakeTime()
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="win32", warn=lambda m: None)
        p.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)
        run_frames(p, ft, 200, 0.015)  # work > half the period: no samples
        self.assertIs(p.strategy, Strategy.NATIVE)


class FakeLink:
    """DisplayLink stand-in: a perfect vblank grid, stamps up to ``now``."""

    def __init__(self, ft, period=P60, phase=0.0005):
        self.ft = ft
        self.period = period
        self.phase = phase
        self.grid = VblankGrid(period_hint=1 / 60.0)
        self.nominal_period = 1 / 60.0
        self.started = self.stopped = False
        self.error = None
        self.dead = False

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True

    def vblank(self, i):
        return self.phase + i * self.period

    def poll(self, now):
        if self.dead:
            return
        last = int((now - self.phase) / self.period)
        for i in range(max(0, last - 5), last + 1):
            self.grid.add(self.vblank(i))


class TestDisplayLink(unittest.TestCase):
    def _pacer(self, ft, link, interval=1):
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="darwin",
                       display_link_factory=lambda: link, warn=lambda m: None)
        swaps = []
        p._set_swap_interval = swaps.append
        p.configure(mode=PaceMode.LOCKED, interval=interval, refresh_hz=60)
        return p, swaps

    def _phases(self, link, times):
        return [((t - link.phase) / link.period) % 1.0 for t in times]

    def test_presents_just_after_vblank_every_interval(self):
        for interval in (1, 2):
            with self.subTest(interval=interval):
                ft = FakeTime(t0=1.0, over=0.0003)
                link = FakeLink(ft)
                p, swaps = self._pacer(ft, link, interval)
                self.assertIs(p.strategy, Strategy.DISPLAY_LINK)
                self.assertEqual(swaps[-1], 0)
                t = run_frames(p, ft, 400, lambda i: 0.004 + 0.004 * (i % 3))
                eps_phase = PRESENT_AFTER_VBLANK_S / link.period
                for ph in self._phases(link, t[5:]):
                    self.assertGreaterEqual(ph, eps_phase - 1e-3)
                    self.assertLess(ph, eps_phase + 0.03)
                steps = {round((b - a) / link.period) for a, b in zip(t[5:], t[6:])}
                self.assertEqual(steps, {interval})
                self.assertAlmostEqual(p.smooth_dt(interval * link.period + 0.0003),
                                       interval * link.period, places=9)

    def test_late_frame_slips_to_the_next_vblank(self):
        ft = FakeTime(t0=1.0)
        link = FakeLink(ft)
        p, _ = self._pacer(ft, link)
        t = run_frames(p, ft, 60, lambda i: 0.020 if i == 30 else 0.004)
        steps = [round((b - a) / link.period) for a, b in zip(t[5:], t[6:])]
        self.assertEqual(sorted(set(steps)), [1, 2])
        self.assertEqual(steps.count(2), 1)
        for ph in self._phases(link, t[5:]):
            self.assertLess(ph, 0.1)  # always right after a vblank

    def test_stale_grid_falls_back_to_timer_then_recovers(self):
        ft = FakeTime(t0=1.0)
        link = FakeLink(ft)
        p, _ = self._pacer(ft, link)
        run_frames(p, ft, 30, 0.004)
        link.dead = True
        t = run_frames(p, ft, 30, 0.004)
        self.assertIsNotNone(p.fallback_reason)
        self.assertAlmostEqual((len(t) - 1) / (t[-1] - t[0]), 60.0, delta=0.5)
        link.dead = False
        run_frames(p, ft, 30, 0.004)
        self.assertIsNone(p.fallback_reason)

    def test_stop_stops_the_link(self):
        ft = FakeTime()
        link = FakeLink(ft)
        p, _ = self._pacer(ft, link)
        p.start()
        p.stop()
        self.assertTrue(link.stopped)


class TestSlipsAndOverhead(unittest.TestCase):
    """What FX Auto reads from the pacer: ``last_slipped`` per present (the
    present missed the vblank it was meant for) and ``present_overhead()``
    (the swap cost that eats into the frame budget)."""

    def _native(self, interval=1):
        ft = FakeTime()
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="win32", warn=lambda m: None)
        p.configure(mode=PaceMode.LOCKED, interval=interval, refresh_hz=60)
        return p, ft

    @staticmethod
    def _vsync_swap(period, n=1):
        def swap(ft):
            ft.t = (int(ft.t / period) + n) * period + 0.0025
        return swap

    def _run_marking(self, pacer, ft, works, swap):
        slipped = []
        for w in works:
            ft.t += w
            pacer.wait_for_present()
            swap(ft)
            pacer.presented()
            slipped.append(pacer.last_slipped)
        return slipped

    def test_native_marks_exactly_the_late_frames(self):
        p, ft = self._native()
        works = [0.004] * 200
        late = {50, 120, 121}
        for i in late:
            works[i] = 0.020  # longer than a period: misses the vblank
        slipped = self._run_marking(p, ft, works, self._vsync_swap(P60))
        self.assertEqual({i for i, s in enumerate(slipped) if s}, late)
        self.assertEqual(p.slips, 3)
        self.assertEqual(p.present_overhead(), 0.0)  # NATIVE: slips carry the signal

    def test_interval_two_slip_is_one_extra_vblank(self):
        p, ft = self._native(interval=2)

        def swap(ft, _n=[0]):
            # Every 2nd vblank, except present #40 lands one vblank later.
            _n[0] += 1
            extra = 1 if _n[0] == 40 else 0
            ft.t = (int(ft.t / P60) + 2 + extra) * P60 + 0.0025
        slipped = self._run_marking(p, ft, [0.004] * 80, swap)
        self.assertEqual([i for i, s in enumerate(slipped) if s], [39])

    def test_first_interval_after_configure_is_not_judged(self):
        p, ft = self._native()
        self._run_marking(p, ft, [0.004] * 5, self._vsync_swap(P60))
        p.configure(mode=PaceMode.LOCKED, interval=2, refresh_hz=60)
        # The switch frame is one period long under the new interval-2
        # expectation — short, not late — and the next one straddles.
        slipped = self._run_marking(p, ft, [0.004] * 3, self._vsync_swap(P60, n=2))
        self.assertEqual(slipped, [False, False, False])

    def test_uncapped_never_slips(self):
        ft = FakeTime()
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="linux", warn=lambda m: None)
        p.configure(mode=PaceMode.UNCAPPED)
        self.assertEqual(self._run_marking(p, ft, [0.001, 0.2, 0.001], lambda ft: None),
                         [False, False, False])

    def test_timer_slip_and_overhead(self):
        ft = FakeTime()
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="linux", warn=lambda m: None)
        p.configure(mode=PaceMode.FIXED, fps=60.0)

        def swap(ft):
            ft.t += 0.0015  # the present itself costs 1.5 ms
        works = [0.004] * 60
        works[30] = 0.030  # late by more than half a period
        slipped = self._run_marking(p, ft, works, swap)
        self.assertIn(True, slipped[30:32])
        self.assertAlmostEqual(p.present_overhead(), 0.0015, delta=0.0002)

    def test_oversleep_is_a_slip_but_not_an_overrun(self):
        """The frame reached its slot on time; the pacer woke 12 ms late (App
        Nap, a busy scheduler). The viewer sees a slip; FX Auto must not."""
        ft = FakeTime(t0=1.0)
        link = FakeLink(ft)
        oversleep = [0.0]

        def sleep(d):
            ft.sleep(d + oversleep[0])

        p = FramePacer(now=ft.now, sleep=sleep, platform="darwin",
                       display_link_factory=lambda: link, warn=lambda m: None)
        p.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)
        flags = []
        for i in range(60):
            ft.t += 0.004
            oversleep[0] = 0.012 if i == 40 else 0.0
            p.wait_for_present()
            p.presented()
            flags.append((p.last_slipped, p.last_overran))
        self.assertEqual([i for i, (sl, _o) in enumerate(flags) if sl], [40])
        self.assertEqual([i for i, (_s, ov) in enumerate(flags) if ov], [])
        self.assertEqual((p.slips, p.overruns), (1, 0))

    def test_late_frame_and_native_slips_are_overruns(self):
        ft = FakeTime(t0=1.0)
        link = FakeLink(ft)
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="darwin",
                       display_link_factory=lambda: link, warn=lambda m: None)
        p.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)
        works = [0.004] * 60
        works[30] = 0.020  # the frame itself missed its slot
        self._run_marking(p, ft, works, lambda ft: None)
        self.assertEqual((p.slips, p.overruns), (1, 1))
        n, ft2 = self._native()
        works = [0.004] * 60
        works[20] = 0.020
        self._run_marking(n, ft2, works, self._vsync_swap(P60))
        self.assertEqual((n.slips, n.overruns), (1, 1))

    def test_display_link_overhead_is_the_swap_after_the_wait(self):
        ft = FakeTime(t0=1.0)
        link = FakeLink(ft)
        p = FramePacer(now=ft.now, sleep=ft.sleep, platform="darwin",
                       display_link_factory=lambda: link, warn=lambda m: None)
        p.configure(mode=PaceMode.LOCKED, interval=1, refresh_hz=60)

        def swap(ft):
            ft.t += 0.0025  # macOS GL flush: ~2.5 ms
        works = [0.004] * 120
        works[80] = 0.018  # misses the vblank: slips, and is left out of the cost
        slipped = self._run_marking(p, ft, works, swap)
        self.assertEqual([i for i, s in enumerate(slipped) if s], [80])
        self.assertAlmostEqual(p.present_overhead(), 0.0025, delta=0.0002)
        d = p.diagnostics()
        self.assertEqual(d["slips"], 1)
        self.assertAlmostEqual(d["present_overhead_ms"], 2.5, delta=0.2)


if __name__ == "__main__":
    unittest.main()
