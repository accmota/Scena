"""Frame pacing: lock presents to the display refresh.

Why (``scripts/bench/longrun.md``, Windows jitter SUMMARY): a free-running
60 Hz timer drifts against the display (59.997 / 60.002 Hz …). Where a present
straddles the compositor latch, frames double and drop in bursts ("beat
judder"). More CPU headroom does not fix it; the present has to follow the
display's vblank grid.

Strategies (chosen per platform by :class:`FramePacer`):

* ``NATIVE`` — ``swap_interval(n)``: the driver blocks the swap until the
  vblank. Windows and Linux. Measured on Windows (Intel Iris Xe, windowed and
  fullscreen): exactly one vblank per frame, ~30 % of a core. A self-check
  falls back to ``TIMER`` when the swap does not block (driver override).
* ``DISPLAY_LINK`` — macOS. OpenGL ``swap_interval`` is unreliable there
  (broken in macOS 10.14, 12, 13; GLFW #1990 / #2249). ``swap_interval(0)``
  and a CoreVideo display link for the window's display give the vblank grid;
  the pacer sleeps until just after a vblank, then swaps (SDL2's design). The
  present sits a whole period away from the next latch, so frame-work jitter
  cannot cross it. See ``scena/_display_link.py``.
* ``TIMER`` — a fixed rate the author asked for (``canvas.framerate = 60``)
  and the fallback. Absolute schedule (``target += period``): the
  old ``start + period`` rule accumulated lateness (59.815 Hz instead of 60).
  Sleep, then spin only the last fraction of a millisecond.
* ``UNCAPPED`` — no wait (``canvas.framerate = "max"``).

World ``dt`` follows the display when locked: an interval that is close to
``k`` vblank periods becomes exactly ``k`` periods (Croteam "The Elusive Frame
Timing"; Godot's delta smoothing). Wall-clock drift is bled back only past a
dead zone, so ``clock.time`` stays within a few ms of wall time.

Pure logic here; GLFW / ctypes come in as injected callables, so tests drive
everything with fake clocks. Python 3.10+ syntax.
"""
from __future__ import annotations

import math
import sys
import time
import warnings
from collections import deque
from enum import Enum
from typing import Callable, Deque, Dict, Optional, Tuple

# A vblank grid outside this range is not a display (20–300 Hz).
MIN_PERIOD_S = 1.0 / 300.0
MAX_PERIOD_S = 1.0 / 20.0
# Locked rates stay at or above this on the "60" rung (90 Hz panel → 90, not 45).
MIN_LOCKED_HZ = 50.0
# Present this long after the vblank (DISPLAY_LINK): clear of the vblank edge.
PRESENT_AFTER_VBLANK_S = 0.001
# An interval within this fraction of k periods is snapped to k periods.
DT_SNAP_FRACTION = 0.2
# Wall-clock debt (s) is bled back only beyond this many periods …
DT_DEBT_DEADZONE = 0.25
# … at most this fraction of a period per frame.
DT_DEBT_BLEED = 0.02
# NATIVE self-check: short-work frames sampled before deciding.
NATIVE_CHECK_FRAMES = 60
# A present later than its slot by more than this fraction of a vblank (or
# timer) period is a slip: the frame missed the vblank it was meant for.
SLIP_FRACTION = 0.5
# Present-cost window (frames) and how often its median is recomputed.
PRESENT_COST_WINDOW = 120
PRESENT_COST_REFRESH = 30


class Strategy(Enum):
    NATIVE = "native"
    DISPLAY_LINK = "display_link"
    TIMER = "timer"
    UNCAPPED = "uncapped"


class PaceMode(Enum):
    """What the framework asks for (mapped from ``canvas.framerate``)."""

    LOCKED = "locked"          # every ``interval``-th vblank ("vsync…" tokens)
    FIXED = "fixed"            # fixed rate, sleep + short spin (a number)
    UNCAPPED = "uncapped"      # no wait ("max")


# ---------------------------------------------------------------------------
# Interval choice
# ---------------------------------------------------------------------------

def interval_near(refresh_hz: float, target_hz: float = 60.0) -> int:
    """Vblank interval ``n`` whose rate ``refresh/n`` is nearest ``target_hz``.

    Rates below ``MIN_LOCKED_HZ`` are not chosen for a 60-class target unless
    no divisor reaches it (a 48 Hz panel runs at 48). Ties go to the higher
    rate. 60→1, 59.94→1, 75→1, 90→1, 100→2 (50), 120→2, 144→2 (72),
    165→3 (55), 240→4.
    """
    r = float(refresh_hz)
    if not math.isfinite(r) or r <= 0:
        return 1
    target = max(1.0, float(target_hz))
    floor = min(MIN_LOCKED_HZ, target)
    best_n, best_err = 1, abs(r - target)
    n = 2
    while r / n >= floor:
        err = abs(r / n - target)
        if err < best_err - 1e-9:
            best_n, best_err = n, err
        n += 1
    return best_n


def locked_interval(refresh_hz: float, target_hz: float) -> int:
    """Interval for a product target: ``60`` → ``interval_near(r, 60)``;
    ``30`` → twice that (the survival rung halves the 60 cadence)."""
    n60 = interval_near(refresh_hz, 60.0)
    mult = max(1, int(round(60.0 / max(1.0, float(target_hz)))))
    return n60 * mult


# ---------------------------------------------------------------------------
# Vblank grid
# ---------------------------------------------------------------------------

class VblankGrid:
    """``(period, anchor)`` fitted from vblank stamps (perf_counter seconds).

    Stamps may be sparse (missing vblanks) and must be the vblank's own time
    (CoreVideo ``hostTime``, DWM ``qpcVBlank``), not an after-wake time. The
    fit: period = Σ intervals / Σ vblank counts over the window (unbiased,
    missing vblanks allowed), anchor = the newest stamp moved by the median
    phase residual. ``health(now)`` validates it.
    """

    def __init__(self, period_hint: Optional[float] = None, max_samples: int = 64) -> None:
        self.period_hint = period_hint
        self._stamps: Deque[float] = deque(maxlen=max_samples)
        self._fit: Optional[Tuple[float, float, float]] = None  # period, anchor, max residual
        self.rejected = 0

    def add(self, t: float) -> None:
        if self._stamps and t <= self._stamps[-1]:
            if t < self._stamps[-1]:
                self.rejected += 1
            return
        self._stamps.append(float(t))
        self._fit = None

    def clear(self) -> None:
        self._stamps.clear()
        self._fit = None

    @property
    def count(self) -> int:
        return len(self._stamps)

    @property
    def newest(self) -> Optional[float]:
        return self._stamps[-1] if self._stamps else None

    def _compute(self) -> Optional[Tuple[float, float, float]]:
        st = self._stamps
        if len(st) < 2:
            return None
        diffs = [b - a for a, b in zip(st, list(st)[1:])]
        p0 = self.period_hint
        if p0 is None or p0 <= 0:
            p0 = sorted(diffs)[len(diffs) // 2]
        if p0 <= 0:
            return None
        num = den = 0.0
        for d in diffs:
            k = round(d / p0)
            if k >= 1 and abs(d - k * p0) < 0.25 * p0:
                num += d
                den += k
        if den <= 0:
            return None
        period = num / den
        newest = st[-1]
        res = []
        for t in st:
            x = (t - newest) / period
            res.append((x - round(x)) * period)
        med = sorted(res)[len(res) // 2]
        anchor = newest + med
        worst = max(abs(r - med) for r in res)
        return period, anchor, worst

    def fit(self) -> Optional[Tuple[float, float, float]]:
        if self._fit is None:
            self._fit = self._compute()
        return self._fit

    @property
    def period(self) -> Optional[float]:
        f = self.fit()
        return f[0] if f else None

    def health(self, now: float, *, min_samples: int = 4,
               max_residual_s: float = 0.001, stale_periods: float = 3.0) -> Tuple[bool, str]:
        """``(ok, reason)``. Not ok: too few stamps, period outside 20–300 Hz,
        stale (no stamp for ``stale_periods``), or residual > ``max_residual_s``."""
        if len(self._stamps) < min_samples:
            return False, f"{len(self._stamps)} vblank stamps (need {min_samples})"
        f = self.fit()
        if f is None:
            return False, "no consistent vblank period"
        period, _anchor, worst = f
        if not (MIN_PERIOD_S <= period <= MAX_PERIOD_S):
            return False, f"period {period * 1000:.3f} ms outside 20–300 Hz"
        if now - self._stamps[-1] > stale_periods * period:
            return False, f"stale: last vblank {1000 * (now - self._stamps[-1]):.1f} ms ago"
        if worst > max_residual_s:
            return False, f"irregular vblanks (residual {worst * 1000:.3f} ms)"
        return True, "ok"

    def vblank_at_or_after(self, t: float) -> Optional[float]:
        """First grid vblank ``>= t``."""
        f = self.fit()
        if f is None:
            return None
        period, anchor, _w = f
        i = math.ceil((t - anchor) / period - 1e-9)
        return anchor + i * period

    def snap(self, t: float) -> Optional[float]:
        """Grid vblank nearest ``t``."""
        f = self.fit()
        if f is None:
            return None
        period, anchor, _w = f
        return anchor + round((t - anchor) / period) * period


# ---------------------------------------------------------------------------
# Present-interval period estimate (NATIVE: swap returns are vblank-locked)
# ---------------------------------------------------------------------------

class PeriodEstimator:
    """Refresh period from vblank-locked present times (Σ d / Σ k).

    Swap-return times carry ~1 ms of wake noise but are locked to vblanks, so
    the windowed ratio converges to the true period (60.0019 Hz, not the
    integer 60 GLFW reports).
    """

    def __init__(self, nominal: float, window: int = 240, min_samples: int = 30) -> None:
        self.nominal = float(nominal)
        self.min_samples = int(min_samples)
        self._d: Deque[Tuple[float, int]] = deque(maxlen=window)
        self._sum_d = 0.0
        self._sum_k = 0

    def note(self, interval: float) -> None:
        p0 = self.period
        k = round(interval / p0)
        if k < 1 or abs(interval - k * p0) > 0.25 * p0:
            return
        if len(self._d) == self._d.maxlen:
            od, ok = self._d[0]
            self._sum_d -= od
            self._sum_k -= ok
        self._d.append((interval, k))
        self._sum_d += interval
        self._sum_k += k

    @property
    def converged(self) -> bool:
        return len(self._d) >= self.min_samples

    @property
    def period(self) -> float:
        if len(self._d) >= self.min_samples and self._sum_k > 0:
            return self._sum_d / self._sum_k
        return self.nominal


# ---------------------------------------------------------------------------
# dt from the display
# ---------------------------------------------------------------------------

class DtSmoother:
    """Snap a measured frame interval to whole vblank periods.

    ``raw`` within ``DT_SNAP_FRACTION`` of ``k`` periods → ``k`` periods; the
    difference goes into a debt that is paid back only beyond a dead zone
    (``DT_DEBT_DEADZONE`` periods), at most ``DT_DEBT_BLEED`` period per frame.
    Anything else (a hitch, VRR, no period yet) passes through raw.
    """

    def __init__(self) -> None:
        self.debt = 0.0

    def reset(self) -> None:
        self.debt = 0.0

    def step(self, raw: float, period: Optional[float]) -> float:
        if period is None or period <= 0 or not (raw > 0):
            return raw
        k = round(raw / period)
        if k < 1 or abs(raw - k * period) > DT_SNAP_FRACTION * period:
            return raw
        q = k * period
        self.debt += raw - q
        if abs(self.debt) > 2.0 * period:
            # The period estimate is off: pay it all now, start clean.
            q += self.debt
            self.debt = 0.0
            return q
        excess = abs(self.debt) - DT_DEBT_DEADZONE * period
        if excess > 0:
            pay = math.copysign(min(excess, DT_DEBT_BLEED * period), self.debt)
            q += pay
            self.debt -= pay
        return q


# ---------------------------------------------------------------------------
# Windows timer resolution (Python < 3.11 only)
# ---------------------------------------------------------------------------

def needs_timer_resolution(platform: str = sys.platform,
                           version: Tuple[int, int] = sys.version_info[:2]) -> bool:
    """``time.sleep`` on Windows before 3.11 is quantized to the 15.6 ms system
    tick; 3.11+ uses high-resolution waitable timers (1 ms sleep ≈ 1.7 ms)."""
    return platform == "win32" and tuple(version) < (3, 11)


class _WinTimerResolution:
    def __init__(self) -> None:
        self._on = False

    def begin(self) -> None:
        if self._on:
            return
        try:
            import ctypes
            ctypes.WinDLL("winmm").timeBeginPeriod(1)
            self._on = True
        except Exception:
            self._on = False

    def end(self) -> None:
        if not self._on:
            return
        try:
            import ctypes
            ctypes.WinDLL("winmm").timeEndPeriod(1)
        except Exception:
            pass
        self._on = False


# ---------------------------------------------------------------------------
# The pacer
# ---------------------------------------------------------------------------

class FramePacer:
    """Decides when the frame is presented, and the world ``dt``.

    Run loop use::

        clock._tick(now, smooth=pacer.smooth_dt)
        ... simulate, draw, flush ...
        pacer.wait_for_present()
        glfw.swap_buffers(window)
        pacer.presented()

    Injected: ``now`` / ``sleep`` (tests), ``set_swap_interval`` (GLFW),
    ``display_link_factory`` (macOS; returns an object with ``start()``,
    ``stop()``, ``poll(now)``, ``grid``, ``nominal_period``, ``error``).
    """

    def __init__(
        self,
        *,
        now: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
        set_swap_interval: Optional[Callable[[int], None]] = None,
        platform: str = sys.platform,
        display_link_factory: Optional[Callable[[], object]] = None,
        warn: Optional[Callable[[str], None]] = None,
        version: Tuple[int, int] = sys.version_info[:2],
    ) -> None:
        self._now = now
        self._sleep = sleep
        self._set_swap_interval = set_swap_interval
        self.platform = platform
        self._display_link_factory = display_link_factory
        self._warn = warn if warn is not None else (
            lambda msg: warnings.warn(msg, RuntimeWarning, stacklevel=3))
        self._version = tuple(version)
        self._timer_res = _WinTimerResolution()
        self._link = None
        self._link_failed: Optional[str] = None
        self._started = False

        self.mode = PaceMode.LOCKED
        self.interval = 1
        self.fps = 60.0
        self.refresh_hz = 60.0
        self.strategy = Strategy.TIMER
        self.fallback_reason: Optional[str] = None

        # Sleep margin (s): sleep until target - margin, spin the rest.
        self.margin = 0.001 if platform == "win32" else 0.0003
        self._next: Optional[float] = None       # TIMER schedule
        self._last_vblank: Optional[float] = None  # DISPLAY_LINK schedule
        self._t_pre: Optional[float] = None
        self._t_prev_present: Optional[float] = None
        self._native_samples = []
        self._native_checked = False
        self._native_forced_timer = False
        self._estimator = PeriodEstimator(1.0 / 60.0)
        self._smoother = DtSmoother()
        self._warned: set = set()
        # Slips and present cost (FX Auto's ground truth and net budget).
        # last_slipped: the present missed its vblank (what the viewer sees).
        # last_overran: ... because the frame did not fit — FX Auto's signal.
        # A slip where the frame reached its slot on time but the pacer woke
        # late (App Nap, a busy scheduler) is not the frame's fault.
        self.last_slipped = False
        self.last_overran = False
        self.overruns = 0
        self._slot: Optional[float] = None
        self._arrived_late = False
        self.slips = 0
        self.presents = 0
        self._skip_slip = 1
        self._present_costs: Deque[float] = deque(maxlen=PRESENT_COST_WINDOW)
        self._present_cost_s = 0.0
        self._present_cost_age = 0

    # -- configuration --------------------------------------------------
    def configure(self, *, mode: PaceMode, interval: int = 1, fps: float = 60.0,
                  refresh_hz: float = 60.0) -> None:
        """(Re)choose the strategy. Cheap; call on every rate change."""
        refresh_hz = float(refresh_hz) if refresh_hz and refresh_hz > 1.0 else 60.0
        if abs(refresh_hz - self.refresh_hz) > 0.5:
            # Another display: re-learn the period, re-run the self-check.
            self._estimator = PeriodEstimator(1.0 / refresh_hz)
            self._native_checked = False
            self._native_forced_timer = False
        self.mode = mode
        self.interval = max(1, int(interval))
        self.fps = float(fps) if fps and fps > 0 else 60.0
        self.refresh_hz = refresh_hz
        self._next = None
        self._last_vblank = None
        self._native_samples = []
        self._smoother.reset()
        self.fallback_reason = None
        # The first interval after a change straddles two cadences: not judged.
        self._skip_slip = 1
        self.last_slipped = False
        self._present_costs.clear()
        self._present_cost_s = 0.0
        self._present_cost_age = 0

        if mode is PaceMode.UNCAPPED:
            self._set_strategy(Strategy.UNCAPPED, 0)
        elif mode is PaceMode.FIXED:
            self._set_strategy(Strategy.TIMER, 0)
        elif self.platform == "darwin":
            if self._ensure_link():
                self._set_strategy(Strategy.DISPLAY_LINK, 0)
            else:
                self.fallback_reason = self._link_failed
                self._set_strategy(Strategy.TIMER, 0)
        elif self._native_forced_timer:
            self.fallback_reason = "swap does not block (self-check)"
            self._set_strategy(Strategy.TIMER, 0)
        else:
            self._set_strategy(Strategy.NATIVE, self.interval)

    def _set_strategy(self, strategy: Strategy, swap_interval: int) -> None:
        self.strategy = strategy
        if self._set_swap_interval is not None:
            self._set_swap_interval(swap_interval)

    def _ensure_link(self) -> bool:
        if self._link is not None:
            return True
        if self._link_failed is not None or self._display_link_factory is None:
            if self._link_failed is None:
                self._link_failed = "no display link backend"
            return False
        try:
            link = self._display_link_factory()
            ok = link.start()
        except Exception as exc:  # environment: CoreVideo missing / refused
            self._link_failed = f"display link failed: {exc!r}"
            return False
        if not ok:
            self._link_failed = getattr(link, "error", None) or "display link failed"
            return False
        self._link = link
        return True

    # -- lifetime -------------------------------------------------------
    def start(self) -> None:
        """Call once before the first frame (``run()``)."""
        if self._started:
            return
        self._started = True
        if needs_timer_resolution(self.platform, self._version):
            self._timer_res.begin()

    def stop(self) -> None:
        """Call from ``run()`` cleanup: stops the display link thread."""
        self._started = False
        self._timer_res.end()
        link, self._link = self._link, None
        if link is not None:
            try:
                link.stop()
            except Exception:
                pass

    # -- per frame --------------------------------------------------------
    def vblank_period(self) -> Optional[float]:
        """Best known refresh period (s), or None when not locked."""
        if self.strategy is Strategy.DISPLAY_LINK and self._link is not None:
            p = self._link.grid.period
            if p is not None:
                return p
            return getattr(self._link, "nominal_period", None) or 1.0 / self.refresh_hz
        if self.strategy is Strategy.NATIVE:
            return self._estimator.period
        return None

    def smooth_dt(self, raw_dt: float) -> float:
        """World-step interval for this frame (``Clock._tick(smooth=…)``)."""
        if self.strategy is Strategy.NATIVE and not self._estimator.converged:
            return raw_dt
        return self._smoother.step(raw_dt, self.vblank_period())

    def wait_for_present(self) -> None:
        """Block until this frame may be presented (call right before swap)."""
        self._slot = None
        self._arrived_late = False
        s = self.strategy
        if s is Strategy.DISPLAY_LINK:
            self._wait_display_link()
        elif s is Strategy.TIMER:
            self._wait_timer()
        self._t_pre = self._now()

    def presented(self) -> None:
        """Call right after the swap returns."""
        t = self._now()
        prev = self._t_prev_present
        self._t_prev_present = t
        self.last_slipped = False
        self.last_overran = False
        if prev is None:
            return
        interval = t - prev
        self.presents += 1
        expected, unit = self._expected_interval()
        if expected is not None:
            if self._skip_slip > 0:
                self._skip_slip -= 1
            elif interval > expected + SLIP_FRACTION * unit:
                self.last_slipped = True
                self.slips += 1
                woke_late = (self._slot is not None and self._t_pre is not None
                             and self._t_pre - self._slot > SLIP_FRACTION * unit)
                if self._arrived_late or not woke_late:
                    self.last_overran = True
                    self.overruns += 1
        if (self.strategy in (Strategy.DISPLAY_LINK, Strategy.TIMER)
                and self._t_pre is not None and not self.last_slipped):
            # After the pacer's wait, the swap is pure cost: the next frame
            # cannot start before it returns.
            self._present_costs.append(t - self._t_pre)
            self._present_cost_age += 1
        if self.strategy is Strategy.NATIVE:
            self._estimator.note(interval)
            if not self._native_checked:
                self._native_check(prev, interval)

    def _expected_interval(self) -> Tuple[Optional[float], Optional[float]]:
        """``(expected present interval, slip unit)`` in s, or ``(None, None)``."""
        s = self.strategy
        if s is Strategy.UNCAPPED:
            return None, None
        if s is Strategy.TIMER:
            p = self.timer_period()
            return p, p / (self.interval if self.mode is PaceMode.LOCKED else 1)
        p = self.vblank_period()
        if p is None:
            return None, None
        return self.interval * p, p

    def present_overhead(self) -> float:
        """Median present cost (s) that eats into the frame budget.

        ``DISPLAY_LINK`` / ``TIMER``: the swap after the pacer's wait (the
        next frame starts only when it returns; ~2–3 ms on macOS GL).
        ``NATIVE``: 0 — the swap's time there is mostly the vblank block
        (slack), and the part that does cost (the swap returning a little
        after the vblank) cannot be seen from its return times. Slips are
        the signal under ``NATIVE``.
        """
        if self.strategy not in (Strategy.DISPLAY_LINK, Strategy.TIMER):
            return 0.0
        costs = self._present_costs
        if len(costs) < 10:
            return 0.0
        if self._present_cost_age >= PRESENT_COST_REFRESH or self._present_cost_s == 0.0:
            ordered = sorted(costs)
            self._present_cost_s = ordered[len(ordered) // 2]
            self._present_cost_age = 0
        return self._present_cost_s

    # -- NATIVE self-check ----------------------------------------------
    def _native_check(self, prev: float, interval: float) -> None:
        """Does the swap block? Sample frames whose work was short."""
        n_period = self.interval * (1.0 / self.refresh_hz)
        work = (self._t_pre - prev) if self._t_pre is not None else None
        if work is None or work > 0.5 * n_period:
            return
        self._native_samples.append(interval)
        if len(self._native_samples) < NATIVE_CHECK_FRAMES:
            return
        med = sorted(self._native_samples)[len(self._native_samples) // 2]
        self._native_checked = True
        self._native_samples = []
        if med < 0.75 * n_period:
            self._native_forced_timer = True
            self.fallback_reason = "swap does not block (self-check)"
            self._once(
                "native",
                f"SCENA: VSync is not blocking here (frames {1000 * med:.1f} ms apart, "
                f"expected {1000 * n_period:.1f}); pacing with a timer instead. "
                "A GPU control-panel setting may force VSync off.",
            )
            self._set_strategy(Strategy.TIMER, 0)
            self._next = None

    def _once(self, key: str, msg: str) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        self._warn(msg)

    # -- TIMER ------------------------------------------------------------
    def timer_period(self) -> float:
        if self.mode is PaceMode.LOCKED:
            # Fallback for a locked mode: the display's rate / interval.
            p = self._estimator.period if self._estimator.converged else 1.0 / self.refresh_hz
            if self._link is not None and self._link.grid.period is not None:
                p = self._link.grid.period
            return p * self.interval
        return 1.0 / self.fps

    def _wait_timer(self) -> None:
        period = self.timer_period()
        now = self._now()
        if self._next is None and self._t_prev_present is not None:
            # First timed frame (or a strategy switch): one period after the
            # last present, not "now" (no short frame at the switch).
            self._next = self._t_prev_present + period
        if self._next is not None and now - self._next > SLIP_FRACTION * period:
            self._arrived_late = True  # the frame reached its slot late
        if self._next is None or now - self._next > period:
            self._next = now  # first frame, or more than a period late: resync
        target = self._next
        self._slot = target
        self._sleep_until(target)
        self._next = target + period

    # -- DISPLAY_LINK -----------------------------------------------------
    def _wait_display_link(self) -> None:
        link = self._link
        now = self._now()
        try:
            link.poll(now)
        except Exception:
            pass
        ok, reason = link.grid.health(now)
        if not ok:
            # Grid not usable this frame (startup, display change): timer at
            # the nominal rate until stamps come back.
            self.fallback_reason = reason
            self._last_vblank = None
            self._wait_timer()
            return
        self.fallback_reason = None
        grid = link.grid
        period = grid.period
        eps = PRESENT_AFTER_VBLANK_S
        target_v = None
        if self._last_vblank is not None:
            sched = grid.snap(self._last_vblank + self.interval * period)
            if sched is not None and sched + eps >= now:
                target_v = sched
            elif sched is not None:
                self._arrived_late = True  # the frame reached its slot late
        if target_v is None:
            target_v = grid.vblank_at_or_after(now - eps)
        self._last_vblank = target_v
        self._next = None
        self._slot = target_v + eps
        self._sleep_until(target_v + eps)

    # -- sleeping ---------------------------------------------------------
    def _sleep_until(self, target: float) -> None:
        now = self._now()
        rem = target - now
        if rem <= 0:
            return
        m = self.margin
        if rem > m:
            want = rem - m
            self._sleep(want)
            over = max(0.0, (self._now() - now) - want)
            # Margin tracks sleep overshoot (0.2–3 ms): grows at once to
            # 1.5× a new worst, shrinks slowly — an early wake only costs a
            # spin, a late one costs the frame.
            need = 1.5 * over
            if need > self.margin:
                self.margin = min(0.003, need)
            else:
                self.margin = max(0.0002, 0.99 * self.margin + 0.01 * need)
        while self._now() < target:
            pass

    # -- diagnostics ------------------------------------------------------
    def diagnostics(self) -> Dict[str, object]:
        p = self.vblank_period()
        return {
            "strategy": self.strategy.value,
            "mode": self.mode.value,
            "interval": self.interval,
            "refresh_hz": self.refresh_hz,
            "period_ms": None if p is None else p * 1000.0,
            "present_hz": None if p is None else 1.0 / (p * self.interval),
            "fallback": self.fallback_reason,
            "margin_ms": self.margin * 1000.0,
            "dt_debt_ms": self._smoother.debt * 1000.0,
            "slips": self.slips,
            "overruns": self.overruns,
            "presents": self.presents,
            "present_overhead_ms": self.present_overhead() * 1000.0,
        }
