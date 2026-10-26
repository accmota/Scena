"""Frame probe — per-frame timing of the *real* ``ScenaFramework.run`` loop.

``harness.install_phase_run`` replaces ``fw.run`` with a replica (uncapped, no
pacing) — right for cost isolates, wrong for jitter: jitter lives in pacing,
present, GC and the OS. This probe keeps the product loop and wraps its callees
instead, so what it measures is what an author sees.

Records per frame (``array('d')``, no GC pressure):

* frame start (``Clock._tick``), duration to the next start (= the ``dt`` authors get)
* exclusive phase ms: update / poll / tick / coll / flush / fxtick / bg / draw /
  post / ui / swap (present) / pace (the pacer's wait before present) / other
* GC ms + highest generation collected in that frame (``gc.callbacks``)

Plus 1 Hz samples (RSS, GC counts, Skia GPU cache, entities, graph nodes,
present mode) and events (FX Auto rung changes, big GC passes).

On macOS it also records the display's **real vsync timeline** (CoreVideo
display link via ctypes; no pyobjc) and models which frame each vsync showed:

* ``held``   — the same image stayed on screen longer than the pacing intends
  (visible stutter, even when every frame was cheap)
* ``dropped`` — a frame that never reached the screen (one-per-vsync pacing)
* ``episodes`` — held/dropped events clustered in time; regular spacing between
  episodes = a beat between the frame timer and the display refresh

The compositor latch offset is unknown (``latch_ms``, default 0). It shifts
*when* an episode happens, not how many there are or how far apart.

Use through ``jitter_probe.py`` (any script) or ``longrun.py`` (pulse).
"""
from __future__ import annotations

import bisect
import ctypes
import ctypes.util
import gc
import os
import statistics
import sys
import time
from array import array
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

PHASES = (
    "update", "poll", "tick", "coll", "flush", "fxtick",
    "bg", "draw", "post", "ui",
)
# Target machine is ~4x slower than the dev box (Scena Design: "use 4x").
SLOWDOWN = 4.0
HITCH_FACTOR = 1.5          # visible hitch: frame dur > 1.5 display periods
SPIKE_FACTOR = 2.0          # work spike: work > 2x median work ...
SPIKE_MIN_MS = 1.0          # ... and at least this much
EPISODE_GAP_S = 1.0         # held/dropped events closer than this = one episode
BUCKET_S = 10.0


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

class _TaskBasicInfo(ctypes.Structure):
    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("resident_size_max", ctypes.c_uint64),
        ("user_time", ctypes.c_int32 * 2),
        ("system_time", ctypes.c_int32 * 2),
        ("policy", ctypes.c_int32),
        ("suspend_count", ctypes.c_int32),
    ]


_libc = None
_task_self = None


def current_rss_mb() -> float:
    """Current (not peak) resident set size in MiB. NaN if unavailable."""
    global _libc, _task_self
    if sys.platform == "darwin":
        try:
            if _libc is None:
                _libc = ctypes.CDLL(None)
                _task_self = ctypes.c_uint32.in_dll(_libc, "mach_task_self_").value
            info = _TaskBasicInfo()
            count = ctypes.c_uint32(ctypes.sizeof(info) // 4)
            kr = _libc.task_info(_task_self, 20, ctypes.byref(info), ctypes.byref(count))
            if kr == 0:
                return info.resident_size / (1024.0 * 1024.0)
        except Exception:
            pass
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024.0 * 1024.0)
    except Exception:
        return float("nan")


class VsyncClock:
    """Real vsync timestamps (perf_counter seconds) from a CoreVideo display link.

    macOS only. ``perf_counter`` is ``mach_absolute_time`` there, the same
    clock as ``CVTimeStamp.hostTime`` — only a timebase conversion is needed.
    """

    def __init__(self) -> None:
        self.times = array("d")
        self.period_s: Optional[float] = None
        self.available = False
        self.error: Optional[str] = None
        self._link = ctypes.c_void_p()
        self._cb = None
        self._cv = None
        self._scale = 1.0

    def start(self) -> bool:
        if sys.platform != "darwin":
            self.error = "vsync clock needs macOS (CoreVideo)"
            return False
        try:
            if time.get_clock_info("perf_counter").implementation != "mach_absolute_time()":
                self.error = "perf_counter is not mach_absolute_time"
                return False
            cv = ctypes.CDLL(ctypes.util.find_library("CoreVideo"))

            class _TB(ctypes.Structure):
                _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

            tb = _TB()
            ctypes.CDLL(None).mach_timebase_info(ctypes.byref(tb))
            self._scale = tb.numer / tb.denom / 1e9

            class _SMPTE(ctypes.Structure):
                _fields_ = [
                    ("subframes", ctypes.c_int16), ("subframeDivisor", ctypes.c_int16),
                    ("counter", ctypes.c_uint32), ("type", ctypes.c_uint32),
                    ("flags", ctypes.c_uint32), ("hours", ctypes.c_int16),
                    ("minutes", ctypes.c_int16), ("seconds", ctypes.c_int16),
                    ("frames", ctypes.c_int16),
                ]

            class _CVTimeStamp(ctypes.Structure):
                _fields_ = [
                    ("version", ctypes.c_uint32), ("videoTimeScale", ctypes.c_int32),
                    ("videoTime", ctypes.c_int64), ("hostTime", ctypes.c_uint64),
                    ("rateScalar", ctypes.c_double), ("videoRefreshPeriod", ctypes.c_int64),
                    ("smpteTime", _SMPTE), ("flags", ctypes.c_uint64),
                    ("reserved", ctypes.c_uint64),
                ]

            cb_t = ctypes.CFUNCTYPE(
                ctypes.c_int32, ctypes.c_void_p,
                ctypes.POINTER(_CVTimeStamp), ctypes.POINTER(_CVTimeStamp),
                ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.c_void_p,
            )
            scale = self._scale
            times = self.times

            def _on_vsync(_link, now, out, _fi, _fo, _ctx):
                # inOutputTime: the vblank's own host time (regular grid);
                # inNow is the callback's wake time (~1 ms jitter).
                ts = out.contents
                times.append(ts.hostTime * scale)
                if self.period_s is None and ts.videoTimeScale > 0:
                    self.period_s = ts.videoRefreshPeriod / float(ts.videoTimeScale)
                return 0

            self._cb = cb_t(_on_vsync)
            cv.CVDisplayLinkCreateWithActiveCGDisplays.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            cv.CVDisplayLinkSetOutputCallback.argtypes = [ctypes.c_void_p, cb_t, ctypes.c_void_p]
            cv.CVDisplayLinkStart.argtypes = [ctypes.c_void_p]
            cv.CVDisplayLinkStop.argtypes = [ctypes.c_void_p]
            if cv.CVDisplayLinkCreateWithActiveCGDisplays(ctypes.byref(self._link)) != 0:
                self.error = "CVDisplayLinkCreate failed"
                return False
            if cv.CVDisplayLinkSetOutputCallback(self._link, self._cb, None) != 0:
                self.error = "CVDisplayLinkSetOutputCallback failed"
                return False
            if cv.CVDisplayLinkStart(self._link) != 0:
                self.error = "CVDisplayLinkStart failed"
                return False
            self._cv = cv
            self.available = True
            return True
        except Exception as exc:  # pragma: no cover - platform specific
            self.error = f"vsync clock unavailable: {exc}"
            return False

    def stop(self) -> None:
        if self._cv is not None and self.available:
            try:
                self._cv.CVDisplayLinkStop(self._link)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Small stats helpers
# ---------------------------------------------------------------------------

def _pct(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return float(sorted_vals[i])


def _slope_per_min(ts: Sequence[float], vs: Sequence[float]) -> Optional[float]:
    pts = [(t, v) for t, v in zip(ts, vs) if v is not None and v == v]
    if len(pts) < 3:
        return None
    n = len(pts)
    mt = sum(p[0] for p in pts) / n
    mv = sum(p[1] for p in pts) / n
    den = sum((p[0] - mt) ** 2 for p in pts)
    if den <= 0:
        return None
    return 60.0 * sum((p[0] - mt) * (p[1] - mv) for p in pts) / den


def _fmt(v: Optional[float], digits: int = 2, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{v:.{digits}f}{unit}"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

class FrameProbe:
    """Install with :meth:`install` after ``import scena`` and before ``run()``."""

    def __init__(
        self,
        *,
        seconds: Optional[float] = None,
        present: str = "keep",
        startup_s: float = 10.0,
        sample_every_s: float = 1.0,
        objects_every_s: float = 0.0,
        vsync: bool = True,
        latch_ms: float = 0.0,
        on_start: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self.seconds = seconds
        self.present = present
        self.startup_s = float(startup_s)
        self.sample_every_s = float(sample_every_s)
        self.objects_every_s = float(objects_every_s)
        self.latch_s = float(latch_ms) / 1000.0
        self.want_vsync = bool(vsync)
        self.on_start = on_start

        self.t_start = array("d")      # frame start (perf_counter s)
        self.t_swap_end = array("d")   # present returned
        self.work = array("d")         # start -> present call (ms)
        self.swap = array("d")         # present call (ms)
        self.gc_ms = array("d")
        self.gc_gen = array("b")
        self.probe_ms = array("d")     # probe's own sampling cost inside the frame
        self.phase: Dict[str, array] = {p: array("d") for p in PHASES}

        self.samples: List[Dict[str, Any]] = []
        self.events: List[Tuple[float, str, str]] = []
        self.gc_events: List[Tuple[float, int, float, int]] = []  # (t, gen, ms, collected)
        self.gc_totals = {0: [0, 0.0], 1: [0, 0.0], 2: [0, 0.0]}

        self.vsync = VsyncClock()
        self.fw = None
        self.meta: Dict[str, Any] = {}
        self._orig: List[Tuple[Any, str, Any]] = []
        self._cur: Optional[Dict[str, float]] = None
        self._stack: List[List[Any]] = []
        self._gc_t0 = 0.0
        self._t0: Optional[float] = None
        self._next_sample = 0.0
        self._next_objects = 0.0
        self._swap_t0 = 0.0
        self._wait_t0: Optional[float] = None  # pacer wait start (this frame)
        self._cpu0: Optional[float] = None
        self._last_pacer: Optional[Dict[str, Any]] = None
        self._stop_requested = False
        self._armed = False

    # -- install / uninstall ------------------------------------------------

    def _patch(self, owner: Any, name: str, wrapper_factory: Callable[[Any], Any]) -> None:
        orig = getattr(owner, name, None)
        if orig is None:
            # Loud, not skipped: a renamed engine hook (Clock.tick -> _tick)
            # once left the probe blind — no frames seen, so the timed run
            # never asked the window to close.
            raise RuntimeError(
                f"frame_probe: {getattr(owner, '__name__', owner)}.{name} not found — "
                "the engine hook was renamed; update FrameProbe.install()")
        self._orig.append((owner, name, orig))
        setattr(owner, name, wrapper_factory(orig))

    def _timed(self, phase: str):
        probe = self
        pc = time.perf_counter

        def factory(orig):
            def wrapper(*a, **kw):
                if probe._cur is None:
                    return orig(*a, **kw)
                stack = probe._stack
                entry = [phase, pc(), 0.0]
                stack.append(entry)
                try:
                    return orig(*a, **kw)
                finally:
                    dur = (pc() - entry[1]) * 1000.0
                    stack.pop()
                    cur = probe._cur
                    if cur is not None:
                        cur[phase] = cur.get(phase, 0.0) + dur - entry[2]
                    if stack:
                        stack[-1][2] += dur
            return wrapper
        return factory

    def install(self) -> "FrameProbe":
        import importlib
        import glfw

        # importlib, not ``import scena.x as m``: ``scena`` re-exports facades
        # (``collision``, ``canvas``) that shadow the submodule attributes.
        mod = importlib.import_module
        orch = mod("scena.orchestration")
        state_mod = mod("scena.state")
        coll_mod = mod("scena.collision")
        canvas_mod = mod("scena.canvas")
        input_mod = mod("scena.input")
        tr_mod = mod("scena.transients")
        sfx_mod = mod("scena.spatial_fx")
        hist_mod = mod("scena.history")
        cover_mod = mod("scena.cover")
        post_mod = mod("scena.postfx")

        self.fw = orch.ScenaFramework.get_instance()
        probe = self

        self._patch(orch, "_run_with_watchdog", self._timed("update"))
        self._patch(orch, "tick_processes", self._timed("tick"))
        self._patch(coll_mod.CollisionSystem, "step", self._timed("coll"))
        self._patch(state_mod.ScenaSystem, "flush", self._timed("flush"))
        for owner, fn in (
            (tr_mod, "tick_all_transients"), (sfx_mod, "tick_all_spatial_fx"),
            (hist_mod, "tick_all_histories"), (cover_mod, "tick_cover"),
        ):
            self._patch(owner, fn, self._timed("fxtick"))
        self._patch(orch.ScenaFramework, "_draw_background", self._timed("bg"))
        self._patch(canvas_mod.ScenaCanvas, "draw", self._timed("draw"))
        self._patch(post_mod.PostFxStack, "_render", self._timed("post"))
        self._patch(orch.ScenaFramework, "_draw_ui_layer", self._timed("ui"))
        self._patch(orch.WidgetManager, "draw", self._timed("ui"))
        self._patch(glfw, "poll_events", self._timed("poll"))

        pc = time.perf_counter

        def swap_factory(orig):
            def swap_buffers(*a, **kw):
                if probe._cur is None:
                    return orig(*a, **kw)
                t0 = pc()
                probe._swap_t0 = t0
                try:
                    return orig(*a, **kw)
                finally:
                    probe._end_frame(t0, pc())
            return swap_buffers

        self._patch(glfw, "swap_buffers", swap_factory)

        def tick_factory(orig):
            def tick(clock_self, current_time, *a, **kw):
                if clock_self is getattr(probe.fw, "clock", None) and probe._armed:
                    probe._begin_frame(float(current_time))
                return orig(clock_self, current_time, *a, **kw)
            return tick

        self._patch(input_mod.Clock, "_tick", tick_factory)

        # The pacer waits before the swap: that time is "pace", not work.
        pacing_mod = mod("scena.pacing")

        def wait_factory(orig):
            def wait_for_present(pacer_self, *a, **kw):
                if probe._cur is not None:
                    probe._wait_t0 = pc()
                return orig(pacer_self, *a, **kw)
            return wait_for_present

        self._patch(pacing_mod.FramePacer, "wait_for_present", wait_factory)

        def rung_factory(orig):
            def _apply_auto_rung(fw_self, rung):
                out = orig(fw_self, rung)
                probe.events.append((pc(), "fx_auto", str(getattr(rung, "label", rung))))
                return out
            return _apply_auto_rung

        self._patch(orch.ScenaFramework, "_apply_auto_rung", rung_factory)

        def run_factory(orig):
            def run(fw_self):
                probe._on_run_start(fw_self)
                try:
                    return orig(fw_self)
                finally:
                    probe._on_run_end()
            return run

        self._patch(orch.ScenaFramework, "run", run_factory)
        gc.callbacks.append(self._gc_cb)
        return self

    def uninstall(self) -> None:
        for owner, name, orig in reversed(self._orig):
            setattr(owner, name, orig)
        self._orig.clear()
        if self._gc_cb in gc.callbacks:
            gc.callbacks.remove(self._gc_cb)
        self.vsync.stop()

    # -- run hooks ----------------------------------------------------------

    # --present → canvas.framerate ("auto" = FX Auto on; "keep" = the script's own).
    PRESENT_FRAMERATE = {
        "fixed60": 60, "fixed30": 30, "vsync": "vsync", "vsync60": "vsync60",
        "vsync30": "vsync30", "none": "max",
    }

    def _apply_present(self, fw) -> None:
        from scena import canvas, set_fx_auto
        p = self.present
        if p == "keep":
            return
        if p == "auto":
            set_fx_auto(True)
        elif p in self.PRESENT_FRAMERATE:
            canvas.framerate = self.PRESENT_FRAMERATE[p]
        else:
            raise ValueError(f"unknown present mode {p!r}")

    def _present_desc(self, fw) -> Tuple[str, Optional[float]]:
        """``(mode, target Hz)``: mode is the framerate token, or "fixed"."""
        fr = getattr(fw, "framerate", None)
        hz: Optional[float]
        if fr == "max":
            return "max", None
        if not isinstance(fr, str):
            return "fixed", float(fr)
        refresh = float(getattr(fw, "_monitor_refresh_hz", 60.0) or 60.0)
        if self.vsync.available and self.vsync.period_s:
            refresh = 1.0 / self.vsync.period_s
        try:
            div = int(fw._pace_request()[1])  # display-locked interval
        except Exception:
            div = 1
        hz = refresh / div
        return str(fr), hz

    @staticmethod
    def _pacer_diag(fw) -> Optional[Dict[str, Any]]:
        try:
            return fw._pacer.diagnostics()
        except Exception:
            return None

    def _on_run_start(self, fw) -> None:
        self._armed = True
        self._cpu0 = time.process_time()
        if self.want_vsync:
            self.vsync.start()

    def _first_frame(self, t: float) -> None:
        """First frame: the app's setup() already ran, so an override sticks."""
        fw = self.fw
        self._apply_present(fw)
        if self.on_start is not None:
            self.on_start(fw)
        mode, hz = self._present_desc(fw)
        self.meta.update({
            "present_arg": self.present,
            "present_mode": mode,
            "present_hz": hz,
            "fx_auto": bool(getattr(fw, "_fx_auto", False)),
            "monitor_hz": float(getattr(fw, "_monitor_refresh_hz", 0.0) or 0.0),
            "fb": (int(getattr(fw, "fb_width", 0) or 0), int(getattr(fw, "fb_height", 0) or 0)),
            "design": (int(getattr(fw, "design_width", 0) or 0), int(getattr(fw, "design_height", 0) or 0)),
            "python": sys.version.split()[0],
            "gc_threshold": gc.get_threshold(),
            "gc_frozen": gc.get_freeze_count(),
            "pacer": self._pacer_diag(fw),
        })
        self._t0 = t
        self._next_sample = t
        self._next_objects = t + self.objects_every_s if self.objects_every_s > 0 else float("inf")

    def _on_run_end(self) -> None:
        self._armed = False
        if self._cur is not None:
            self._cur = None
        self.vsync.stop()
        if self._cpu0 is not None and self.t_start:
            wall = time.perf_counter() - self.t_start[0]
            if wall > 0:
                self.meta["cpu_pct_one_core"] = 100.0 * (time.process_time() - self._cpu0) / wall
        # Last in-run snapshot: run() cleanup has already stopped the pacer.
        self.meta["pacer_end"] = self._last_pacer
        self._take_sample(time.perf_counter(), final=True)

    # -- per-frame ----------------------------------------------------------

    def _begin_frame(self, t: float) -> None:
        if self._t0 is None:
            self._first_frame(t)
        if self._cur is not None:
            # Previous frame never reached present (should not happen) — drop it.
            self._cur = None
        probe_cost = 0.0
        if t >= self._next_sample:
            p0 = time.perf_counter()
            self._take_sample(t)
            self._next_sample = t + self.sample_every_s
            if t >= self._next_objects:
                self._take_objects(t)
                self._next_objects = t + self.objects_every_s
            probe_cost = (time.perf_counter() - p0) * 1000.0
        if self.seconds is not None and self._t0 is not None and not self._stop_requested:
            if t - self._t0 >= self.seconds:
                self._stop_requested = True
                window = self.fw._window
                if window is None:
                    # Headless (tests). Linux's GLFW is built with asserts on:
                    # a NULL window aborts the process instead of raising.
                    self.fw._running = False
                else:
                    try:
                        import glfw
                        glfw.set_window_should_close(window, True)
                    except Exception:
                        self.fw._running = False
        self._stack.clear()
        self._wait_t0 = None
        self._cur = {"t": t, "gc_ms": 0.0, "gc_gen": -1, "probe": probe_cost}

    def _end_frame(self, swap_t0: float, swap_t1: float) -> None:
        cur = self._cur
        if cur is None:
            return
        self._cur = None
        t = cur["t"]
        self.t_start.append(t)
        self.t_swap_end.append(swap_t1)
        work_end = self._wait_t0 if self._wait_t0 is not None else swap_t0
        self._wait_t0 = None
        self.work.append((work_end - t) * 1000.0)
        self.swap.append((swap_t1 - swap_t0) * 1000.0)
        self.gc_ms.append(cur["gc_ms"])
        self.gc_gen.append(int(cur["gc_gen"]))
        self.probe_ms.append(cur["probe"])
        for p in PHASES:
            self.phase[p].append(cur.get(p, 0.0))

    def _gc_cb(self, phase: str, info: Dict[str, Any]) -> None:
        if phase == "start":
            self._gc_t0 = time.perf_counter()
            return
        t1 = time.perf_counter()
        ms = (t1 - self._gc_t0) * 1000.0
        gen = int(info.get("generation", 0))
        tot = self.gc_totals.setdefault(gen, [0, 0.0])
        tot[0] += 1
        tot[1] += ms
        cur = self._cur
        if cur is not None:
            cur["gc_ms"] += ms
            if gen > cur["gc_gen"]:
                cur["gc_gen"] = gen
        if gen >= 1 or ms >= 1.0:
            self.gc_events.append((t1, gen, ms, int(info.get("collected", 0))))

    def _take_sample(self, t: float, final: bool = False) -> None:
        fw = self.fw
        row: Dict[str, Any] = {"t": t, "rss_mb": current_rss_mb(), "gc_count": gc.get_count()}
        try:
            ctx = getattr(fw, "_context", None)
            if ctx is not None:
                # skia-python's getResourceCacheUsage binding returns None;
                # purgeable bytes is the part that grows with churned textures.
                row["gpu_cache_mb"] = ctx.getResourceCachePurgeableBytes() / (1024.0 * 1024.0)
        except Exception:
            pass
        try:
            from scena.state import get_scena_system
            ss = get_scena_system()
            row["graph_nodes"] = len(ss.dependency_graph.nodes) if ss else 0
        except Exception:
            pass
        try:
            row["entities"] = int(fw._count_registry_objects())
        except Exception:
            pass
        try:
            mode, hz = self._present_desc(fw)
            row["present"] = f"{mode}@{hz:.0f}" if hz else mode
        except Exception:
            pass
        if final:
            row["final"] = True
        else:
            self._last_pacer = self._pacer_diag(fw)
        self.samples.append(row)

    def _take_objects(self, t: float) -> None:
        # Frozen objects (gc_policy) leave gc.get_objects(); count them too.
        n = len(gc.get_objects()) + gc.get_freeze_count()
        if self.samples:
            self.samples[-1]["py_objects"] = n

    # -- analysis -----------------------------------------------------------

    def analyze(self) -> Dict[str, Any]:
        n = len(self.t_start)
        out: Dict[str, Any] = {"meta": dict(self.meta), "frames": n}
        if n < 3:
            out["error"] = "too few frames"
            return out
        t0 = self.t_start[0]
        # Frame i's duration = next start - this start (what the next dt will be).
        dur = [(self.t_start[i + 1] - self.t_start[i]) * 1000.0 for i in range(n - 1)]
        m = n - 1
        work = list(self.work[:m])
        swap = list(self.swap[:m])
        pace = [dur[i] - work[i] - swap[i] for i in range(m)]
        probe = list(self.probe_ms[:m])
        rel = [self.t_start[i] - t0 for i in range(m)]

        monitor_hz = float(self.meta.get("monitor_hz") or 60.0)
        vs_period_ms = None
        if self.vsync.available and self.vsync.period_s:
            vs_period_ms = self.vsync.period_s * 1000.0
            monitor_hz = 1000.0 / vs_period_ms
        display_ms = 1000.0 / monitor_hz
        target_hz = self.meta.get("present_hz")
        target_ms = 1000.0 / target_hz if target_hz else None

        hitch_ms = HITCH_FACTOR * max(display_ms, target_ms or 0.0)
        med_work = statistics.median(work)
        spike_ms = max(SPIKE_FACTOR * med_work, med_work + SPIKE_MIN_MS)
        budget_ms = target_ms or display_ms
        over4x_ms = budget_ms / SLOWDOWN

        phase_lists = {p: list(self.phase[p][:m]) for p in PHASES}
        phase_med = {p: statistics.median(v) for p, v in phase_lists.items()}
        other = [
            work[i] - probe[i] - sum(phase_lists[p][i] for p in PHASES) for i in range(m)
        ]
        med_other = statistics.median(other)
        med_swap = statistics.median(swap)
        med_pace = statistics.median(pace)

        def attribute(i: int) -> str:
            parts = []
            if self.gc_ms[i] >= 0.5:
                parts.append(f"gc{self.gc_gen[i]} {self.gc_ms[i]:.1f}")
            ex = {p: phase_lists[p][i] - phase_med[p] for p in PHASES}
            ex["other"] = other[i] - med_other
            ex["swap"] = swap[i] - med_swap
            ex["pace"] = pace[i] - med_pace
            ex["probe"] = probe[i]
            for k, v in sorted(ex.items(), key=lambda kv: -kv[1])[:2]:
                if v >= 0.5:
                    parts.append(f"{k} +{v:.1f}")
            return ", ".join(parts) or "spread"

        startup_end = self.startup_s
        is_probe = [p > 0.5 for p in probe]
        hitches = [i for i in range(m) if dur[i] > hitch_ms and not is_probe[i]]
        spikes = [i for i in range(m) if work[i] - probe[i] > spike_ms and not is_probe[i]]
        over4x = [i for i in range(m) if (work[i] - probe[i]) * SLOWDOWN > budget_ms]

        def window(idx: Sequence[int], lo: float, hi: float) -> List[int]:
            return [i for i in idx if lo <= rel[i] < hi]

        total_s = max(1e-6, rel[-1] + dur[-1] / 1000.0)
        steady_s = max(1e-6, total_s - startup_end)

        def dstats(vals: Sequence[float]) -> Dict[str, float]:
            s = sorted(vals)
            if not s:
                return {}
            return {
                "mean": sum(s) / len(s), "p50": _pct(s, 0.5), "p99": _pct(s, 0.99),
                "p999": _pct(s, 0.999), "max": s[-1],
            }

        steady_idx = [i for i in range(m) if rel[i] >= startup_end]
        start_idx = [i for i in range(m) if rel[i] < startup_end]
        out.update({
            "seconds": total_s,
            "display_hz": monitor_hz,
            "vsync_clock": self.vsync.available,
            "vsync_error": self.vsync.error,
            "target_hz": target_hz,
            "fps": m / total_s,
            "thresholds": {
                "hitch_ms": hitch_ms, "spike_ms": spike_ms, "over4x_work_ms": over4x_ms,
            },
            "dur": dstats(dur),
            "dur_steady": dstats([dur[i] for i in steady_idx]),
            "work": dstats(work),
            "work_steady": dstats([work[i] for i in steady_idx]),
            "phase_median_ms": {**phase_med, "other": med_other, "swap": med_swap, "pace": med_pace},
            "hitches": {
                "count": len(hitches),
                "startup": len(window(hitches, 0, startup_end)),
                "steady": len(window(hitches, startup_end, 1e18)),
                "steady_per_min": 60.0 * len(window(hitches, startup_end, 1e18)) / steady_s,
            },
            "spikes": {
                "count": len(spikes),
                "startup": len(window(spikes, 0, startup_end)),
                "steady_per_min": 60.0 * len(window(spikes, startup_end, 1e18)) / steady_s,
            },
            "over_budget_at_4x": {
                "budget_ms": budget_ms,
                "count": len(over4x),
                "startup": len(window(over4x, 0, startup_end)),
                "steady_per_min": 60.0 * len(window(over4x, startup_end, 1e18)) / steady_s,
            },
            "startup": {
                "frames": len(start_idx),
                "worst_dur_ms": max((dur[i] for i in start_idx), default=float("nan")),
                "worst_work_ms": max((work[i] for i in start_idx), default=float("nan")),
                "first_frames_ms": [round(dur[i], 2) for i in range(min(10, m))],
            },
        })
        if target_ms and self.meta.get("present_mode") == "fixed":
            late = sorted(d - target_ms for d in (dur[i] for i in steady_idx))
            out["pacing"] = {
                "target_ms": target_ms,
                "late_p50_ms": _pct(late, 0.5), "late_p99_ms": _pct(late, 0.99),
                "late_max_ms": late[-1] if late else float("nan"),
                "measured_hz": m / total_s,
            }

        worst = sorted(set(hitches) | set(spikes), key=lambda i: -max(dur[i], work[i]))[:25]
        out["worst_frames"] = [
            {
                "t": round(rel[i], 3), "frame": i, "dur_ms": round(dur[i], 2),
                "work_ms": round(work[i], 2), "swap_ms": round(swap[i], 2),
                "pace_ms": round(pace[i], 2), "cause": attribute(i),
            }
            for i in worst
        ]

        # GC
        out["gc"] = {
            f"gen{g}": {"count": c, "total_ms": round(ms, 2)}
            for g, (c, ms) in sorted(self.gc_totals.items())
        }
        big = [e for e in self.gc_events if e[1] == 2]
        out["gc"]["gen2_max_ms"] = max((e[2] for e in big), default=0.0)
        out["gc"]["gen2_times_s"] = [round(e[0] - t0, 1) for e in big][:40]
        # In play only: the setup collect before gc.freeze() runs before frame 1.
        play = [e for e in big if e[0] - t0 > 0.5]
        out["gc"]["gen2_play_count"] = len(play)
        out["gc"]["gen2_play_max_ms"] = max((e[2] for e in play), default=0.0)
        out["gc"]["hitches_with_gc"] = sum(1 for i in hitches if self.gc_ms[i] >= 0.5)
        out["gc"]["spikes_with_gc"] = sum(1 for i in spikes if self.gc_ms[i] >= 0.5)

        out["present"] = self._presentation(rel, t0, total_s, target_hz, monitor_hz)
        out["vblank_steps"] = vblank_steps(
            self.vsync.times if self.vsync.available else (),
            [e for e, s0 in zip(self.t_swap_end, self.t_start) if s0 - t0 >= startup_end],
            steady_s)
        out["drift"] = self._drift(t0, startup_end)
        out["buckets"] = self._buckets(rel, dur, work, hitches, t0)
        out["events"] = [
            {"t": round(t - t0, 2), "kind": k, "detail": d} for (t, k, d) in self.events
        ]
        return out

    def _presentation(self, rel, t0, total_s, target_hz, refresh_hz) -> Dict[str, Any]:
        V = self.vsync.times
        if not self.vsync.available or len(V) < 10:
            return {"available": False, "why": self.vsync.error or "no vsync samples"}
        V = sorted(V)
        E = self.t_swap_end
        S = self.t_start
        n = len(E)
        lo_i = 0
        while lo_i < n and E[lo_i] + self.latch_s < V[0]:
            lo_i += 1
        hi_i = n
        while hi_i > lo_i and E[hi_i - 1] + self.latch_s >= V[-1]:
            hi_i -= 1
        if hi_i - lo_i < 10:
            return {"available": False, "why": "vsync window too short"}
        slots = [bisect.bisect_right(V, E[i] + self.latch_s) for i in range(lo_i, hi_i)]
        shown: List[Tuple[int, int]] = []  # (slot, frame index)
        dropped_t: List[float] = []
        for j, k in enumerate(slots):
            i = lo_i + j
            if shown and shown[-1][0] == k:
                dropped_t.append(S[shown[-1][1]] - t0)
                shown[-1] = (k, i)
            else:
                shown.append((k, i))
        target = float(target_hz) if target_hz else None
        step = 1
        if target and target < refresh_hz * 0.95:
            step = max(1, int(round(refresh_hz / target)))
        one_per_vsync = target is not None and target <= refresh_hz * 1.05
        held_t: List[float] = []
        held_extra = 0
        motion_err: List[float] = []
        for a, b in zip(shown, shown[1:]):
            gap = b[0] - a[0]
            if gap > step:
                held_t.append(V[a[0]] - t0)
                held_extra += gap - step
            d_disp = V[b[0]] - V[a[0]]
            d_sample = S[b[1]] - S[a[1]]
            motion_err.append(abs(d_sample - d_disp) * 1000.0)
        event_t = sorted(held_t + (dropped_t if one_per_vsync else []))
        episodes: List[List[float]] = []
        for t in event_t:
            if episodes and t - episodes[-1][1] <= EPISODE_GAP_S:
                episodes[-1][1] = t
                episodes[-1][2] += 1
            else:
                episodes.append([t, t, 1])
        starts = [e[0] for e in episodes]
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        span_s = max(1e-6, V[-1] - V[0])
        frames_hz = (hi_i - lo_i - 1) / max(1e-6, E[hi_i - 1] - E[lo_i])
        predicted = None
        if one_per_vsync and target is not None:
            diff = abs(frames_hz - refresh_hz / step)
            predicted = (1.0 / diff) if diff > 1e-6 else float("inf")
        me = sorted(motion_err)
        vs_iv = sorted((b - a) * 1000.0 for a, b in zip(V, V[1:]))
        # Phase of each present inside its vsync interval (0 = just after a
        # vsync, → 1 = right before the next). Timer pacing drifts through it;
        # judder clusters where the phase sits on the latch boundary (~0 / ~1).
        period = statistics.median(vs_iv) / 1000.0
        ph_t: List[float] = []
        ph_v: List[float] = []
        for j, k in enumerate(slots):
            if k <= 0 or k >= len(V):
                continue
            i = lo_i + j
            ph_t.append(E[i] - t0)
            ph_v.append((E[i] + self.latch_s - V[k - 1]) / period)
        track = []
        b_lo, vals = 0.0, []
        for t, v in zip(ph_t, ph_v):
            if t >= b_lo + 5.0:
                if vals:
                    track.append((round(b_lo, 1), round(statistics.median(vals), 3)))
                b_lo, vals = 5.0 * int(t // 5.0), []
            vals.append(v)
        if vals:
            track.append((round(b_lo, 1), round(statistics.median(vals), 3)))

        def ep_phase(e) -> Optional[float]:
            lo_k = bisect.bisect_left(ph_t, e[0] - 0.25)
            hi_k = bisect.bisect_right(ph_t, e[1] + 0.25)
            seg = ph_v[lo_k:hi_k]
            return round(statistics.median(seg), 3) if seg else None

        return {
            "available": True,
            "latch_ms": self.latch_s * 1000.0,
            "vsyncs": len(V),
            "vsync_period_ms": statistics.median(vs_iv),
            "vsync_jitter_p99_ms": _pct(vs_iv, 0.99) - _pct(vs_iv, 0.5),
            "one_per_vsync": one_per_vsync,
            "expected_vsyncs_per_frame": step,
            "shown_frames": len(shown),
            "held": len(held_t),
            "held_extra_vsyncs": held_extra,
            "held_per_min": 60.0 * len(held_t) / span_s,
            "dropped": len(dropped_t),
            "dropped_per_min": 60.0 * len(dropped_t) / span_s,
            "motion_err_p50_ms": _pct(me, 0.5),
            "motion_err_p99_ms": _pct(me, 0.99),
            "episodes": len(episodes),
            "episodes_per_min": 60.0 * len(episodes) / span_s,
            "episode_list": [
                {"t": round(e[0], 2), "len_s": round(e[1] - e[0], 2), "events": e[2], "phase": ep_phase(e)}
                for e in episodes[:80]
            ],
            "phase_track": track,
            "episode_spacing_s": statistics.median(gaps) if gaps else None,
            "frames_hz": frames_hz,
            "refresh_hz": refresh_hz,
            "predicted_beat_s": predicted,
        }

    def _drift(self, t0: float, startup_s: float) -> Dict[str, Any]:
        rows = [r for r in self.samples if r["t"] - t0 >= startup_s]
        if len(rows) < 3:
            rows = list(self.samples)
        ts = [r["t"] - t0 for r in rows]
        out: Dict[str, Any] = {}
        for key in ("rss_mb", "gpu_cache_mb", "graph_nodes", "entities"):
            vals = [r.get(key) for r in rows]
            out[f"{key}_per_10min"] = (lambda s: None if s is None else 10.0 * s)(_slope_per_min(ts, vals))
            got = [v for v in vals if v is not None]
            if got:
                out[f"{key}_first"] = got[0]
                out[f"{key}_last"] = got[-1]
        objs = [(r["t"] - t0, r["py_objects"]) for r in self.samples if "py_objects" in r]
        if objs:
            s = _slope_per_min([o[0] for o in objs], [o[1] for o in objs])
            out["py_objects_first"] = objs[0][1]
            out["py_objects_last"] = objs[-1][1]
            out["py_objects_per_10min"] = None if s is None else 10.0 * s
        # Work drift: per-bucket median work vs time (steady part only).
        n = len(self.work)
        if n > 10:
            bt, bw = [], []
            b0 = self.t_start[0]
            cur_b, vals = None, []
            for i in range(n):
                rel = self.t_start[i] - b0
                if rel < startup_s:
                    continue
                b = int(rel // BUCKET_S)
                if cur_b is None:
                    cur_b = b
                if b != cur_b:
                    if vals:
                        bt.append((cur_b + 0.5) * BUCKET_S)
                        bw.append(statistics.median(vals))
                    cur_b, vals = b, []
                vals.append(self.work[i] - self.probe_ms[i])
            if vals:
                bt.append((cur_b + 0.5) * BUCKET_S)
                bw.append(statistics.median(vals))
            s = _slope_per_min(bt, bw)
            if s is not None and bw:
                base = statistics.median(bw)
                out["work_ms_per_10min"] = 10.0 * s
                out["work_pct_per_10min"] = (100.0 * 10.0 * s / base) if base > 0 else None
        return out

    def _buckets(self, rel, dur, work, hitches, t0) -> List[Dict[str, Any]]:
        if not rel:
            return []
        hset = set(hitches)
        nb = int(rel[-1] // BUCKET_S) + 1
        out = []
        for b in range(nb):
            lo, hi = b * BUCKET_S, (b + 1) * BUCKET_S
            idx = [i for i in range(len(rel)) if lo <= rel[i] < hi]
            if not idx:
                continue
            ds = sorted(dur[i] for i in idx)
            ws = sorted(work[i] for i in idx)
            out.append({
                "t": lo, "frames": len(idx),
                "work_p50": round(_pct(ws, 0.5), 3), "dur_p99": round(_pct(ds, 0.99), 2),
                "dur_max": round(ds[-1], 2), "hitches": sum(1 for i in idx if i in hset),
                "gc_ms": round(sum(self.gc_ms[i] for i in idx), 2),
            })
        return out

    # -- output -------------------------------------------------------------

    def write_trace_csv(self, path: str) -> None:
        n = len(self.t_start)
        t0 = self.t_start[0] if n else 0.0
        with open(path, "w", encoding="utf-8") as f:
            cols = ["t", "dur_ms", "work_ms", "swap_ms", "gc_ms", "gc_gen", "probe_ms"] + list(PHASES)
            f.write(",".join(cols) + "\n")
            for i in range(n - 1):
                d = (self.t_start[i + 1] - self.t_start[i]) * 1000.0
                row = [
                    f"{self.t_start[i] - t0:.5f}", f"{d:.3f}", f"{self.work[i]:.3f}",
                    f"{self.swap[i]:.3f}", f"{self.gc_ms[i]:.3f}", str(self.gc_gen[i]),
                    f"{self.probe_ms[i]:.3f}",
                ] + [f"{self.phase[p][i]:.3f}" for p in PHASES]
                f.write(",".join(row) + "\n")


def vblank_steps(vsync_times: Sequence[float], swap_ends: Sequence[float],
                 seconds: float) -> Dict[str, Any]:
    """Vblanks advanced per presented frame, on a grid fitted to the vsync
    stamps (the Windows SUMMARY's offline check). Needs no latch model: a
    steady cadence is one value ({1: n} at 60 on 60 Hz); a beat shows 0s and
    2s. ``off_cadence`` counts frames off the most common step."""
    V = sorted(vsync_times)
    if len(V) < 20 or len(swap_ends) < 20:
        return {"available": False}
    diffs = [b - a for a, b in zip(V, V[1:]) if b > a]
    p0 = statistics.median(diffs)
    num = den = 0.0
    for d in diffs:
        k = round(d / p0)
        if k >= 1 and abs(d - k * p0) < 0.25 * p0:
            num += d
            den += k
    if den <= 0:
        return {"available": False}
    period = num / den
    res = sorted(((v - V[0]) / period - round((v - V[0]) / period)) for v in V)
    anchor = V[0] + res[len(res) // 2] * period
    idx = [int((e - anchor) // period) for e in swap_ends]
    phase = sorted(((e - anchor) / period) % 1.0 for e in swap_ends)
    steps = [b - a for a, b in zip(idx, idx[1:])]
    hist: Dict[int, int] = {}
    for st in steps:
        hist[st] = hist.get(st, 0) + 1
    cadence = max(hist, key=hist.get)
    off = sum(c for k, c in hist.items() if k != cadence)
    return {
        "available": True, "period_ms": period * 1000.0,
        "hist": dict(sorted(hist.items())), "cadence": cadence,
        "off_cadence": off, "off_per_min": 60.0 * off / max(1e-6, seconds),
        "phase_p01": _pct(phase, 0.01), "phase_p50": _pct(phase, 0.5),
        "phase_p99": _pct(phase, 0.99),
    }


def print_report(rep: Dict[str, Any], title: str = "frame probe") -> None:
    line = "=" * 72
    print(line)
    print(title)
    print(line)
    if rep.get("error"):
        print(f"error: {rep['error']}")
        return
    meta = rep["meta"]
    tgt = rep.get("target_hz")
    print(
        f"present {meta.get('present_mode')} target={_fmt(tgt, 1, ' Hz')}  "
        f"display={rep['display_hz']:.3f} Hz  fx_auto={meta.get('fx_auto')}  "
        f"gc_threshold={meta.get('gc_threshold')}  frozen={meta.get('gc_frozen')}"
    )
    print(
        f"ran {rep['seconds']:.1f}s  frames={rep['frames']}  fps={rep['fps']:.1f}  "
        f"vsync_clock={'yes' if rep['vsync_clock'] else 'no (' + str(rep.get('vsync_error')) + ')'}"
    )
    th = rep["thresholds"]
    d, ds, w = rep["dur"], rep["dur_steady"], rep["work_steady"]
    print()
    print("frame duration (= dt)   p50 {:.2f}  p99 {:.2f}  p99.9 {:.2f}  max {:.2f} ms  (steady p99 {:.2f})".format(
        d["p50"], d["p99"], d["p999"], d["max"], ds.get("p99", float("nan"))))
    print("CPU work (steady)       p50 {:.3f}  p99 {:.3f}  max {:.3f} ms".format(
        w.get("p50", float("nan")), w.get("p99", float("nan")), w.get("max", float("nan"))))
    pm = rep["phase_median_ms"]
    print("phase medians ms        " + "  ".join(
        f"{k} {pm[k]:.3f}" for k in list(PHASES) + ["other", "swap", "pace"] if pm.get(k, 0) >= 0.0005))
    if "pacing" in rep:
        pg = rep["pacing"]
        print("pacing                  target {:.3f} ms  late p50 {:+.3f}  p99 {:+.3f}  max {:+.2f} ms  measured {:.4f} Hz".format(
            pg["target_ms"], pg["late_p50_ms"], pg["late_p99_ms"], pg["late_max_ms"], pg["measured_hz"]))
    h, sp, o4 = rep["hitches"], rep["spikes"], rep["over_budget_at_4x"]
    print()
    print(f"hitches (dur > {th['hitch_ms']:.1f} ms)      total {h['count']}  startup {h['startup']}  steady {h['steady']} ({h['steady_per_min']:.2f}/min)")
    print(f"work spikes (> {th['spike_ms']:.2f} ms)     total {sp['count']}  startup {sp['startup']}  steady {sp['steady_per_min']:.2f}/min")
    print(f"over budget at {SLOWDOWN:.0f}x slower    total {o4['count']}  startup {o4['startup']}  steady {o4['steady_per_min']:.2f}/min  (work > {th['over4x_work_ms']:.2f} ms here)")
    su = rep["startup"]
    print(f"startup window          frames {su['frames']}  worst dur {su['worst_dur_ms']:.1f} ms  worst work {su['worst_work_ms']:.1f} ms")
    print(f"  first frames dur ms   {su['first_frames_ms']}")
    vb = rep.get("vblank_steps") or {}
    print()
    if vb.get("available"):
        print("vblank grid check (latch-free)  cadence {} vblank(s)  off-cadence {} ({:.2f}/min)  "
              "steps {}  swap-end phase p01/p50/p99 {:.3f}/{:.3f}/{:.3f}".format(
                  vb["cadence"], vb["off_cadence"], vb["off_per_min"], vb["hist"],
                  vb["phase_p01"], vb["phase_p50"], vb["phase_p99"]))
    pm_ = rep["meta"]
    if pm_.get("pacer_end") or pm_.get("pacer"):
        pz = pm_.get("pacer_end") or pm_.get("pacer")
        print("pacer  strategy {}  interval {}  present {} Hz  fallback {}  cpu {} % of one core  "
              "slips {}/{}  present overhead {} ms".format(
                  pz.get("strategy"), pz.get("interval"), _fmt(pz.get("present_hz"), 3),
                  pz.get("fallback"), _fmt(pm_.get("cpu_pct_one_core"), 0),
                  pz.get("slips", "—"), pz.get("presents", "—"),
                  _fmt(pz.get("present_overhead_ms"), 2)))
    pr = rep["present"]
    if pr.get("available"):
        print("presentation (vsync model, latch {:.1f} ms)  vsync {:.4f} ms (jitter p99 {:.3f})".format(
            pr["latch_ms"], pr["vsync_period_ms"], pr["vsync_jitter_p99_ms"]))
        print("  held frames      {}  ({:.2f}/min, {} extra vsyncs)   dropped {}  ({:.2f}/min){}".format(
            pr["held"], pr["held_per_min"], pr["held_extra_vsyncs"], pr["dropped"], pr["dropped_per_min"],
            "" if pr["one_per_vsync"] else "  [uncapped/above refresh: drops expected]"))
        print("  judder episodes  {}  ({:.2f}/min)  median spacing {}  frames {:.4f} Hz vs refresh {:.4f} Hz → predicted beat {}".format(
            pr["episodes"], pr["episodes_per_min"], _fmt(pr["episode_spacing_s"], 1, " s"),
            pr["frames_hz"], pr["refresh_hz"] / max(1, pr["expected_vsyncs_per_frame"]),
            _fmt(pr["predicted_beat_s"], 1, " s")))
        print("  motion error     p50 {:.2f}  p99 {:.2f} ms  (sampled dt vs displayed interval)".format(
            pr["motion_err_p50_ms"], pr["motion_err_p99_ms"]))
        if pr["episode_list"]:
            big = sorted(pr["episode_list"], key=lambda e: -e["events"])[:12]
            print("  biggest episodes (t s / len s / events / phase): " + "  ".join(
                f"{e['t']:.1f}/{e['len_s']:.2f}/{e['events']}/{_fmt(e.get('phase'), 2)}"
                for e in sorted(big, key=lambda e: e["t"])))
        tr = pr.get("phase_track") or []
        if tr:
            step = max(1, len(tr) // 20)
            print("  present phase in vsync interval (t s: phase): " + "  ".join(
                f"{t:.0f}:{v:.2f}" for t, v in tr[::step]))
    else:
        print(f"presentation model unavailable: {pr.get('why')}")
    g = rep["gc"]
    print()
    print("gc  " + "  ".join(
        f"{k} n={v['count']} {v['total_ms']:.0f}ms" for k, v in g.items() if k.startswith("gen")
        and isinstance(v, dict)) + f"  gen2 max {g['gen2_max_ms']:.1f} ms  hitches w/ gc {g['hitches_with_gc']}  spikes w/ gc {g['spikes_with_gc']}")
    if g["gen2_times_s"]:
        print(f"  gen2 at s: {g['gen2_times_s'][:20]}")
    dr = rep["drift"]
    print("drift/10min  RSS {} MiB ({}→{})  work {} ({})  gpu cache {} MiB  graph {}  entities {}  py objects {}".format(
        _fmt(dr.get("rss_mb_per_10min"), 2, ""), _fmt(dr.get("rss_mb_first"), 1), _fmt(dr.get("rss_mb_last"), 1),
        _fmt(dr.get("work_ms_per_10min"), 3, " ms"), _fmt(dr.get("work_pct_per_10min"), 1, "%"),
        _fmt(dr.get("gpu_cache_mb_per_10min"), 2), _fmt(dr.get("graph_nodes_per_10min"), 0),
        _fmt(dr.get("entities_per_10min"), 1), _fmt(dr.get("py_objects_per_10min"), 0)))
    if rep["events"]:
        print("events: " + "  ".join(f"{e['t']}s {e['kind']}={e['detail']}" for e in rep["events"][:12]))
    if rep["worst_frames"]:
        print()
        print("worst frames (t s | dur | work | swap | pace | cause = excess over phase medians)")
        for fr in rep["worst_frames"][:15]:
            print("  {:8.2f}  {:7.2f}  {:7.2f}  {:6.2f}  {:7.2f}  {}".format(
                fr["t"], fr["dur_ms"], fr["work_ms"], fr["swap_ms"], fr["pace_ms"], fr["cause"]))
    print(line)
