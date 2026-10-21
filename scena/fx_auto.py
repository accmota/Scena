"""
Automatic fidelity + presentation-rate policy for Scena.

Axes stay independent (``FxQuality`` and framerate); this module only *suggests*
coordinated rungs when product Auto is enabled. Pure policy — no GLFW/Skia.

Product default: **on** (starts at high@60). Manual ``canvas.fx_quality`` /
``canvas.framerate`` turn it off. Hot path when Auto is off: do not instantiate
or sample this controller.

Design (product)
----------------
Ladder: high@60 → medium@60 → low@60 → low@30 (never max / batch-off).

Hold **60 fps as long as possible**; drop present to 30 only as the last survival
rung (after fidelity is already low). Interactive feel prefers temporal continuity
over the medium→low look step.

* **Down on a sustained problem** — the period *median* of CPU work (spikes
  and OS stalls do not move it) over ``k_down`` × the *net* budget, or a
  sustained rate of *overruns* (presents that missed their vblank because the
  frame did not fit; the pacer's own late wakes do not count), for 2 s.
* **Sim-bound frames keep their look** — the loop also passes the draw share
  (``_draw_frame`` + ``flushAndSubmit``); the rest is simulation, which no
  fidelity rung changes. When simulation is at least half the work and even
  the cheapest fidelity at this rate is predicted over the line (simulation
  + draw / the remaining draw ratios), quality steps cannot help: with sustained overruns the rate halves at the
  same fidelity (high@60 → high@30, medium@60 → medium@30); without overruns
  (over the line but still fitting) Auto holds. At 30 such a frame holds.
* **Up on a prediction, held long** — the next rung's work is predicted as
  current work × a cost ratio learned from past steps (prior 1.35 for a
  fidelity climb, 1.0 for 30 → 60); climb when it fits in 70–80 % of that
  rung's net budget with few overruns, for 12–18 s. A scene that fit before a
  load spike climbs back once the spike passes; one that genuinely needs a
  lower rung stays there.
* **External slips** — if a slip-driven step down did not cut the slip rate
  by 20 %, the slips come from outside (another process, App Nap): they stop
  counting for 30 s, so they cannot walk the ladder down.
* **Asymmetric cooldown** — short after Down, long after Up.
* **EMA reset + settle** after each step — avoid deciding on ghost work from the
  previous rung.
* **Failed-climb lock** — Up then Down within 30 s locks climbs for 15 s,
  doubling per consecutive failure (cap 120 s); a climb that holds resets it.
* **Startup warmup** — discard samples for ``warmup_s`` after the first drawn
  frame so shader/GPU/Python caches cannot fake an overload. Bootstrap never
  folds a 1-frame hitch into the EMA.

Scenario check (production parameters, 60 Hz, 2.5 ms present overhead;
``tests/test_fx_auto.py`` ``TestStability``): 30 s of +30 % work with a 25 ms
spike every ~0.5 s → no step; 16 ms of work for a minute → down within ~2 s,
back to high ~60 s after it ends; 20 s of rung-independent slips → at most one
step, then back up.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, NamedTuple, Optional, Tuple

from .fx_quality import FxQuality


class Rung(NamedTuple):
    fidelity: FxQuality
    # ``canvas.framerate`` token the rung applies: "vsync60" or "vsync30".
    framerate: str
    # Real locked rate: refresh / interval (144 Hz → 72 for "vsync60").
    present_hz: float
    label: str
    # Vblank interval on this display.
    interval: int


class AutoParams(NamedTuple):
    """Hysteresis knobs for :class:`FxAutoController`.

    **Down on a sustained problem, up on a prediction that fits with room to
    spare, held for a long time.** Down: the period *median* of CPU work
    (spikes and OS stalls do not move it) above ``k_down`` × net budget, or
    a sustained slip rate, for ``t_down_s``. Up: the next rung's predicted
    cost (current work × a cost ratio learned from past steps) below
    ``k_up*`` × *its* net budget, with few slips, for ``t_up_s`` (× scale).
    """

    eval_period_s: float = 1.0
    # Consecutive seconds of overload before a step down (2 evals: one bad
    # second — a GC pass, a window drag, a background burst — never steps).
    t_down_s: float = 2.0
    t_up_s: float = 12.0
    # Asymmetric post-step cooldowns (Down responsive, Up patient).
    cooldown_down_s: float = 1.2
    cooldown_up_s: float = 6.0
    # After cooldown ends, skip this many full eval periods before deciding
    # (re-seed EMA on the new rung). 0 = decide as soon as cool-down ends.
    settle_evals: int = 2
    k_down: float = 0.92
    # Up lines: the target rung's *predicted* work as a fraction of its net
    # budget. Rate-only climb (low@30 → low@60), fidelity climb (→ medium),
    # climb into high (strictest: park on medium).
    k_up: float = 0.80
    k_up_fidelity: float = 0.75
    k_up_to_high: float = 0.70
    # Multiply t_up_s for any fidelity climb / climb into high.
    t_up_fidelity_scale: float = 1.25
    t_up_to_high_scale: float = 1.5
    ema_alpha: float = 0.2
    ema_reset_on_step: bool = True
    # Prior cost ratio (next-better rung / current rung) before one is
    # learned from a real step; a learned ratio is clamped to [1, ratio_max].
    fidelity_cost_ratio: float = 1.35
    ratio_max: float = 2.0
    # Prior draw-share ratio of one fidelity step (draw on the better rung /
    # draw on the cheaper one), learned per step like the work ratio. It
    # predicts whether lowering fidelity can bring a frame under the line
    # (simulation does not shrink). Optimistic on purpose: measured
    # 2026-10-21 at 1.06–1.12 per step on Constelação and the festa bench
    # game, so a wrong guess costs at most one rung before the learned ratio
    # takes over.
    draw_cost_ratio: float = 1.35
    # A frame is sim-bound only when simulation is at least this share of
    # the work (measured, not predicted): a draw-heavy scene keeps the
    # fidelity-first ladder whatever the draw ratio predicts.
    sim_share_min: float = 0.5
    # If Down follows an Up within this window → failed climb → Up lockout,
    # doubling per consecutive failure (capped); a climb that holds resets it.
    failed_climb_window_s: float = 30.0
    failed_climb_lock_s: float = 15.0
    failed_climb_lock_max_s: float = 120.0
    # Discard samples after the first drawn frame (not construct). Covers
    # shader compile / Skia first-use; a false Down is sticky (Up-hard).
    warmup_s: float = 2.0
    # Slips (a present that missed its vblank because the frame did not fit,
    # from the pacer) catch GPU-bound frames the CPU number cannot see. Rate
    # over the last ``slip_window_evals`` periods (≥ ``slip_min_frames``):
    # above ``slip_down_rate`` counts as overload; a climb needs at most
    # ``slip_up_rate``. If a slip-driven step cut the slip rate by less than
    # ``slip_helped_drop`` (a fraction of it), the slips are external (another
    # process, the OS): they stop counting for ``external_slip_hold_s``.
    slip_down_rate: float = 0.10
    slip_up_rate: float = 0.015
    slip_window_evals: int = 5
    slip_min_frames: int = 30
    external_slip_hold_s: float = 30.0
    slip_helped_drop: float = 0.2
    # Net budget = frame time − measured present overhead, never below this
    # fraction of the frame time (a bogus overhead cannot collapse the ladder).
    min_net_budget_frac: float = 0.5


def _label(fidelity: FxQuality, present_hz: float) -> str:
    return f"{fidelity.value}@{present_hz:.0f}"


def _rung(fidelity: FxQuality, framerate: str, refresh_hz: float) -> Rung:
    from .pacing import locked_interval

    n = locked_interval(refresh_hz, 60.0 if framerate == "vsync60" else 30.0)
    hz = refresh_hz / n
    return Rung(fidelity, framerate, float(hz), _label(fidelity, hz), int(n))


def build_rungs(refresh_hz: float) -> Tuple[Rung, ...]:
    """Every rung Auto can stand on, by index: the product ladder
    (:func:`build_ladder`, 0–3) then the rate rungs that keep fidelity for a
    sim-bound frame: 4 = high@30, 5 = medium@30."""
    r = max(1.0, float(refresh_hz))
    return build_ladder(r) + (
        _rung(FxQuality.HIGH, "vsync30", r),
        _rung(FxQuality.MEDIUM, "vsync30", r),
    )


# Moves between rung indices (see build_rungs). The fidelity path is the
# product ladder (low@60's next rung is the survival rate rung, low@30); at 30
# it steps fidelity within the row. The rate path halves the rate at the same
# fidelity. A climb is the reverse of the one step that reaches a rung from
# above at 60 — the 30 row climbs by rate only (hold 60 first).
_DOWN_FIDELITY = {0: 1, 1: 2, 2: 3, 3: None, 4: 5, 5: 3}
_DOWN_RATE = {0: 4, 1: 5, 2: 3, 3: None, 4: None, 5: None}
_UP = {0: None, 1: 0, 2: 1, 3: 2, 4: 0, 5: 1}


def build_ladder(refresh_hz: float) -> Tuple[Rung, ...]:
    """Four-rung product ladder: high@60 → medium@60 → low@60 → low@30.

    Fidelity steps first while present stays at ~60; **~30 Hz is last-resort
    survival** after low fidelity. Nothing below: an overloaded frame slips to
    a later vblank (dt still follows the display).

    Every rung is **display-locked**: the three 60 rungs apply
    ``canvas.framerate = "vsync60"`` (the vblank divisor nearest 60 Hz:
    60→60, 120→60, 144→72, 165→55, 75→75) and the survival rung
    ``"vsync30"`` (twice that interval). A free 60 Hz timer beats against the
    display (judder bursts every few seconds), so no rung uses one. The pacer
    implements the interval itself (native swap interval, or the macOS
    display link), so label, budget and measured FPS agree on every OS.
    ``present_hz`` is the real rate ``refresh / interval``.
    """
    r = max(1.0, float(refresh_hz))
    return (
        _rung(FxQuality.HIGH, "vsync60", r),
        _rung(FxQuality.MEDIUM, "vsync60", r),
        _rung(FxQuality.LOW, "vsync60", r),
        _rung(FxQuality.LOW, "vsync30", r),
    )


def budget_ms(present_hz: float) -> float:
    """Frame budget in ms for the current present rate."""
    hz = max(1.0, float(present_hz))
    return 1000.0 / hz


def _fidelity_rank(q: FxQuality) -> int:
    """Higher = better fidelity (max not on Auto ladder)."""
    return {
        FxQuality.LOW: 0,
        FxQuality.MEDIUM: 1,
        FxQuality.HIGH: 2,
        FxQuality.MAX: 3,
    }.get(q, 1)


class FxAutoController:
    """Hysteresis walker over the ladder.

    * ``note_work_ms`` — call each frame while Auto is on (CPU work, and
      whether the present overran its vblank).
    * ``set_present_overhead_ms`` — the pacer's measured present cost.
    * ``maybe_step`` — ≤1 Hz eval; returns a new :class:`Rung` when the index moves.
    """

    def __init__(
        self,
        refresh_hz: float = 60.0,
        params: Optional[AutoParams] = None,
    ) -> None:
        self.params = params if params is not None else AutoParams()
        self.refresh_hz = max(1.0, float(refresh_hz))
        self.ladder: Tuple[Rung, ...] = build_ladder(self.refresh_hz)
        self.rungs: Tuple[Rung, ...] = build_rungs(self.refresh_hz)
        self.overhead_ms: float = 0.0
        # Learned cost ratios, keyed by the rung a climb starts from.
        self._ratio: dict = {}
        # Learned draw-share ratios, keyed by the fidelity a step lands on.
        self._draw_ratio: dict = {}
        self._slip_hist: Deque[Tuple[int, int]] = deque(
            maxlen=max(1, int(self.params.slip_window_evals)))
        self.reset_to_aspirational()

    def set_refresh_hz(self, refresh_hz: float) -> None:
        """Rebuild ladder if monitor refresh changes; keep index clamped."""
        self.refresh_hz = max(1.0, float(refresh_hz))
        self.ladder = build_ladder(self.refresh_hz)
        self.rungs = build_rungs(self.refresh_hz)
        self.rung_index = max(0, min(self.rung_index, len(self.rungs) - 1))

    def reset_to_aspirational(self) -> Rung:
        """Start at rung 0 (high @ ~60). Clears hysteresis state."""
        self.rung_index = 0
        self.ema_ms = 0.0
        # Simulation share of the work (work − draw), same median + EMA.
        self.sim_ema_ms = 0.0
        self._ema_ready = False
        self.bad_for_s = 0.0
        self.good_for_s = 0.0
        self.cooldown_until = 0.0
        self._last_eval = 0.0
        self._clock_started = False
        self._period_works: list = []
        self._period_sims: list = []
        self._period_slips = 0
        self._settle_left = 0
        self._last_step_dir: Optional[str] = None  # "up" | "down"
        self._last_step_time = 0.0
        self._up_lock_until = 0.0
        self._failed_climbs = 0
        self._warmup_until = 0.0  # 0 = not armed; set on first maybe_step
        self._slip_hist.clear()
        # A down step learns the ratios once the new rung has a clean EMA:
        # (rung index stepped from, rung index stepped to, work and draw
        # before the step).
        self._pending_ratio: Optional[Tuple[int, int, float, float]] = None
        # Where the next down step goes (set by the eval that counts it bad).
        self._down_to: Optional[int] = None
        # A slip-driven down step checks it helped: slip rate before it.
        self._slip_step_rate: Optional[float] = None
        self._slips_external_until = 0.0
        return self.current_rung()

    def current_rung(self) -> Rung:
        return self.rungs[self.rung_index]

    # --- signals ---------------------------------------------------------------

    def note_work_ms(self, work_ms: float, slipped: bool = False,
                     draw_ms: Optional[float] = None) -> None:
        """One frame: CPU work (ms), whether its present overran its vblank
        (``FramePacer.last_overran``), and the draw share of that work
        (``_draw_frame`` + ``flushAndSubmit``; the rest is simulation). No
        draw share = all draw, so every step is a fidelity step. Cheap; no
        decision."""
        ms = float(work_ms)
        if ms < 0.0:
            ms = 0.0
        self._period_works.append(ms)
        if draw_ms is None:
            self._period_sims.append(0.0)
        else:
            draw = float(draw_ms)
            self._period_sims.append(
                ms - draw if 0.0 < draw < ms else (0.0 if draw >= ms else ms))
        if slipped:
            self._period_slips += 1

    @property
    def _has_period(self) -> bool:
        return bool(self._period_works)

    def set_present_overhead_ms(self, overhead_ms: float) -> None:
        """Present cost the pacer measured (``FramePacer.present_overhead``)."""
        self.overhead_ms = max(0.0, float(overhead_ms))

    def net_budget_ms(self, rung: Optional[Rung] = None) -> float:
        """Frame time left for work: ``interval × period − present overhead``."""
        r = rung if rung is not None else self.current_rung()
        full = budget_ms(r.present_hz)
        return max(full * self.params.min_net_budget_frac, full - self.overhead_ms)

    @property
    def slip_rate(self) -> float:
        """Overrun presents / presents over the recent eval periods (0 when
        there are too few frames to judge)."""
        frames = sum(f for f, _s in self._slip_hist)
        if frames < self.params.slip_min_frames:
            return 0.0
        return sum(sl for _f, sl in self._slip_hist) / float(frames)

    def _last_period_slip_rate(self) -> float:
        if not self._slip_hist:
            return 0.0
        frames, slips = self._slip_hist[-1]
        return slips / float(frames) if frames > 0 else 0.0

    def slips_external(self, now: float) -> bool:
        """True while slips were shown not to depend on the rung."""
        return now < self._slips_external_until

    # --- climbing ----------------------------------------------------------------

    def up_thresholds(self) -> Tuple[float, float]:
        """``(k_up, t_up_s)`` for climbing from the current rung one step better."""
        return self._up_thresholds_for(self.rung_index)

    def _up_thresholds_for(self, from_index: int) -> Tuple[float, float]:
        """Thresholds for climbing from ``from_index`` to its climb target."""
        p = self.params
        to = _UP[from_index]
        if to is None:
            return p.k_up, p.t_up_s
        cur = self.rungs[from_index]
        nxt = self.rungs[to]
        if _fidelity_rank(nxt.fidelity) <= _fidelity_rank(cur.fidelity):
            # Rate climb (low@30 → low@60, high@30 → high@60).
            return float(p.k_up), float(p.t_up_s)
        if nxt.fidelity is FxQuality.HIGH:
            return float(p.k_up_to_high), float(p.t_up_s * p.t_up_to_high_scale)
        return float(p.k_up_fidelity), float(p.t_up_s * p.t_up_fidelity_scale)

    def cost_ratio(self, from_index: Optional[int] = None) -> float:
        """Predicted work on the next-better rung / work on ``from_index``.

        Learned from real steps (work before a down step / settled work after
        it); before that, ``fidelity_cost_ratio`` for a fidelity climb and 1.0
        for a rate-only climb (same per-frame work, half the budget).
        """
        i = self.rung_index if from_index is None else from_index
        if i in self._ratio:
            return self._ratio[i]
        to = _UP[i]
        if to is None:
            return 1.0
        cur, nxt = self.rungs[i], self.rungs[to]
        if _fidelity_rank(nxt.fidelity) > _fidelity_rank(cur.fidelity):
            return float(self.params.fidelity_cost_ratio)
        return 1.0

    def predicted_up_ms(self) -> Optional[float]:
        """Work expected on the next-better rung, or None at the top."""
        if _UP[self.rung_index] is None or not self._ema_ready:
            return None
        return self.ema_ms * self.cost_ratio()

    # --- sim-bound or draw-bound ----------------------------------------------------

    def draw_ratio(self, fidelity: FxQuality) -> float:
        """Draw share on the next-better fidelity / draw on ``fidelity``:
        learned from steps that landed on it; before that, the mean of this
        scene's other learned steps (same looks), else ``draw_cost_ratio``."""
        learned = self._draw_ratio
        if fidelity in learned:
            return learned[fidelity]
        if learned:
            return sum(learned.values()) / len(learned)
        return float(self.params.draw_cost_ratio)

    def lowest_fidelity_ms(self) -> float:
        """Work predicted at the cheapest fidelity at this rate: simulation
        (no fidelity changes it) + draw share / the draw ratios of the steps
        still left down to low. Equal to the work when already at low."""
        sim = min(self.sim_ema_ms, self.ema_ms)
        draw = self.ema_ms - sim
        rank = _fidelity_rank(self.current_rung().fidelity)
        for q in (FxQuality.MEDIUM, FxQuality.LOW):
            if _fidelity_rank(q) < rank:
                draw /= self.draw_ratio(q)
        return sim + draw

    def sim_bound(self, line_ms: float) -> bool:
        """Lowering fidelity cannot bring the work under ``line_ms``: the
        simulation is most of the work (``sim_share_min``) and even the
        cheapest fidelity at this rate is predicted over the line."""
        if not self._ema_ready or self.current_rung().fidelity is FxQuality.LOW:
            return False
        if self.sim_ema_ms < self.params.sim_share_min * self.ema_ms:
            return False
        return self.lowest_fidelity_ms() > line_ms

    # --- the decision -------------------------------------------------------------

    def _discard_period(self) -> None:
        self._period_works = []
        self._period_sims = []
        self._period_slips = 0

    def maybe_step(self, now: float) -> Optional[Rung]:
        """Evaluate at most every ``eval_period_s``. Return new rung or None."""
        p = self.params
        now = float(now)
        warmup = max(0.0, float(p.warmup_s))

        # Arm clocks on the first drawn-frame sample — construct may be
        # seconds earlier (init() before run()). Never fold this incomplete
        # period: a single hitch must not seed the EMA. Do not use
        # ``_last_eval <= 0`` as the sentinel: tests (and a relative clock)
        # may start at t=0.
        if not self._clock_started:
            self._clock_started = True
            self._last_eval = now
            if warmup > 0.0:
                self._warmup_until = now + warmup
            self._discard_period()
            return None

        if self._warmup_until > 0.0 and now < self._warmup_until:
            self._discard_period()
            self._last_eval = now
            return None

        # First call after grace: start a clean eval period, no decision yet.
        if (
            self._warmup_until > 0.0
            and self._last_eval < self._warmup_until
            and now >= self._warmup_until
        ):
            self.ema_ms = 0.0
            self._ema_ready = False
            self.bad_for_s = 0.0
            self.good_for_s = 0.0
            self._discard_period()
            self._last_eval = now
            return None

        if now < self.cooldown_until:
            # Still fold samples so EMA rebuilds on the new rung during cool-down.
            self._fold_period_into_ema()
            return None

        if (now - self._last_eval) < p.eval_period_s:
            return None

        dt = now - self._last_eval
        self._last_eval = now
        self._fold_period_into_ema()

        if not self._ema_ready:
            return None

        # Post-step settle: accumulate EMA only for N full periods.
        if self._settle_left > 0:
            self._settle_left -= 1
            self.bad_for_s = 0.0
            self.good_for_s = 0.0
            return None

        self._learn_after_step(now)

        # A climb that held past the failure window resets the backoff.
        if (self._last_step_dir == "up" and self._failed_climbs
                and now - self._last_step_time > p.failed_climb_window_s):
            self._failed_climbs = 0

        rung = self.current_rung()
        budget = self.net_budget_ms(rung)
        ema = self.ema_ms
        external = self.slips_external(now)
        slips = 0.0 if external else self.slip_rate
        line = budget * p.k_down
        over_work = ema > line
        # Slips must be over the line in the window *and* in the latest
        # period: one bad second stays in the window for several evals but
        # must not count as a sustained problem.
        over_slips = slips > p.slip_down_rate and self._last_period_slip_rate() > p.slip_down_rate
        problem = over_work or over_slips
        down_to = _DOWN_FIDELITY[self.rung_index]
        if over_work and self.sim_bound(line):
            # Sim-bound: even the cheapest fidelity stays over the line, so
            # a fidelity step would only cost the look. Halve the rate at
            # this fidelity — only when frames really miss their vblank (a
            # frame over the line that still fits keeps 60); at 30, hold.
            down_to = _DOWN_RATE[self.rung_index]
            problem = over_slips and down_to is not None

        k_up_eff, t_up_eff = self.up_thresholds()
        up_to = _UP[self.rung_index]
        fits_up = False
        if up_to is not None:
            target = self.rungs[up_to]
            predicted = ema * self.cost_ratio()
            fits_up = (predicted < self.net_budget_ms(target) * k_up_eff
                       and slips <= p.slip_up_rate)

        if problem:
            self.bad_for_s += dt
            self.good_for_s = 0.0
        elif fits_up:
            self.good_for_s += dt
            self.bad_for_s = 0.0
        else:
            # Sticky band: decay both slowly.
            half = dt * 0.5
            self.bad_for_s = max(0.0, self.bad_for_s - half)
            self.good_for_s = max(0.0, self.good_for_s - half)

        if self.bad_for_s >= p.t_down_s and down_to is not None:
            if over_slips and not over_work:
                self._slip_step_rate = slips
            return self._commit_step(now, direction="down", to=down_to)

        if (
            self.good_for_s >= t_up_eff
            and up_to is not None
            and now >= self._up_lock_until
        ):
            return self._commit_step(now, direction="up", to=up_to)

        return None

    def _learn_after_step(self, now: float) -> None:
        """First settled eval after a down step: learn the cost ratio, and
        check a slip-driven step actually cut the slips."""
        p = self.params
        if self._pending_ratio is not None:
            source, index, before, draw_before = self._pending_ratio
            if index == self.rung_index and self.ema_ms > 0.0:
                # The work ratio predicts the climb back, so learn it only
                # from the step that climb reverses (low@30 is also reached
                # from medium@30, a fidelity step; its climb is by rate).
                if _UP[index] == source:
                    r = min(p.ratio_max, max(1.0, before / self.ema_ms))
                    old = self._ratio.get(index)
                    self._ratio[index] = r if old is None else 0.5 * (old + r)
                landed = self.rungs[index].fidelity
                draw_after = self.ema_ms - min(self.sim_ema_ms, self.ema_ms)
                if (landed is not self.rungs[source].fidelity
                        and draw_before > 0.0 and draw_after > 0.0):
                    r = min(p.ratio_max, max(1.0, draw_before / draw_after))
                    old = self._draw_ratio.get(landed)
                    self._draw_ratio[landed] = r if old is None else 0.5 * (old + r)
            self._pending_ratio = None
        if self._slip_step_rate is not None:
            frames = sum(f for f, _s in self._slip_hist)
            if frames >= p.slip_min_frames:
                if self.slip_rate > (1.0 - p.slip_helped_drop) * self._slip_step_rate:
                    # Stepping down did not help: the slips come from outside.
                    self._slips_external_until = now + p.external_slip_hold_s
                self._slip_step_rate = None

    def _commit_step(self, now: float, direction: str,
                     to: Optional[int] = None) -> Rung:
        """Move one rung (``to``, default the fidelity path down / the climb
        up), apply asymmetric cooldown / settle / failed-climb lock."""
        p = self.params
        now = float(now)
        if to is None:
            to = (_DOWN_FIDELITY if direction == "down" else _UP)[self.rung_index]
            if to is None:
                return self.current_rung()

        if direction == "down":
            # Failed climb: just went up and was forced back. Lock out climbs,
            # doubling per consecutive failure.
            if (
                self._last_step_dir == "up"
                and self._last_step_time > 0.0
                and (now - self._last_step_time) <= p.failed_climb_window_s
            ):
                self._failed_climbs += 1
                lock = p.failed_climb_lock_s * (2 ** (self._failed_climbs - 1))
                self._up_lock_until = now + min(p.failed_climb_lock_max_s, lock)
            if self._ema_ready and self.ema_ms > 0.0:
                draw = self.ema_ms - min(self.sim_ema_ms, self.ema_ms)
                self._pending_ratio = (self.rung_index, to, self.ema_ms, draw)
            cool = p.cooldown_down_s
        else:
            self._pending_ratio = None
            self._slip_step_rate = None
            cool = p.cooldown_up_s

        self.rung_index = to
        self._last_step_dir = direction
        self._last_step_time = now
        self.bad_for_s = 0.0
        self.good_for_s = 0.0
        self.cooldown_until = now + max(0.0, float(cool))
        self._settle_left = max(0, int(p.settle_evals))

        # Slips on the old rung say nothing about the new one.
        self._slip_hist.clear()
        if p.ema_reset_on_step:
            self.ema_ms = 0.0
            self._ema_ready = False
            self._discard_period()

        return self.current_rung()

    def _fold_period_into_ema(self) -> None:
        works = self._period_works
        if not works:
            return
        # Median, not mean: one 100 ms stall in a second of frames moves a
        # mean by ~1.6 ms; the median ignores it. Sustained overload moves it.
        ordered = sorted(works)
        median = ordered[len(ordered) // 2]
        sims = sorted(self._period_sims)
        sim = sims[len(sims) // 2] if sims else 0.0
        self._slip_hist.append((len(works), self._period_slips))
        self._discard_period()
        a = self.params.ema_alpha
        if not self._ema_ready:
            self.ema_ms = median
            self.sim_ema_ms = sim
            self._ema_ready = True
        else:
            self.ema_ms = (1.0 - a) * self.ema_ms + a * median
            self.sim_ema_ms = (1.0 - a) * self.sim_ema_ms + a * sim

    def diagnostics(self, now: Optional[float] = None) -> dict:
        """Snapshot for labs / stress instrumentation (not hot-path)."""
        rung = self.current_rung()
        budget = self.net_budget_ms(rung)
        p = self.params
        t = float(now) if now is not None else 0.0
        cooldown_left = max(0.0, self.cooldown_until - t) if t > 0.0 else 0.0
        up_lock = max(0.0, self._up_lock_until - t) if t > 0.0 else 0.0
        if self._warmup_until > 0.0:
            warmup_left = max(0.0, self._warmup_until - t) if t > 0.0 else p.warmup_s
        elif p.warmup_s > 0.0:
            warmup_left = float(p.warmup_s)
        else:
            warmup_left = 0.0
        k_up_eff, t_up_eff = self.up_thresholds()
        up_to = _UP[self.rung_index]
        up_budget = self.net_budget_ms(self.rungs[up_to]) \
            if up_to is not None else budget
        return {
            "rung_index": self.rung_index,
            "rung_label": rung.label,
            "fidelity": rung.fidelity.value,
            "framerate": rung.framerate,
            "present_hz": rung.present_hz,
            "budget_ms": budget,
            "frame_ms": budget_ms(rung.present_hz),
            "overhead_ms": self.overhead_ms,
            "slip_rate": self.slip_rate,
            "slips_external": self.slips_external(t),
            "down_line_ms": budget * p.k_down,
            "up_line_ms": up_budget * k_up_eff,
            "predicted_up_ms": self.predicted_up_ms(),
            "cost_ratio": self.cost_ratio() if up_to is not None else None,
            "k_up_eff": k_up_eff,
            "t_up_eff_s": t_up_eff,
            "ema_ms": self.ema_ms if self._ema_ready else None,
            "sim_ms": self.sim_ema_ms if self._ema_ready else None,
            "lowest_fidelity_ms": self.lowest_fidelity_ms() if self._ema_ready else None,
            "sim_bound": self.sim_bound(budget * p.k_down),
            "ema_ready": self._ema_ready,
            "bad_for_s": self.bad_for_s,
            "good_for_s": self.good_for_s,
            "cooldown_left_s": cooldown_left,
            "settle_left": self._settle_left,
            "up_lock_left_s": up_lock,
            "failed_climbs": self._failed_climbs,
            "t_down_s": p.t_down_s,
            "t_up_s": p.t_up_s,
            "cooldown_down_s": p.cooldown_down_s,
            "cooldown_up_s": p.cooldown_up_s,
            "k_down": p.k_down,
            "k_up": p.k_up,
            "eval_period_s": p.eval_period_s,
            "refresh_hz": self.refresh_hz,
            "last_step_dir": self._last_step_dir,
            "warmup_s": p.warmup_s,
            "warmup_left_s": warmup_left,
        }
