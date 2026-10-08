"""Windows vsync timeline sources + a source check (standalone, ctypes only).

Library (used by win_jitter_probe.py):
    DwmTimingSource  DwmGetCompositionTimingInfo polled; exact qpcVBlank per
                     refresh counter, gaps filled by the counter (no GIL error)
    DwmFlushSource   thread loops DwmFlush(); timestamp after return
    D3dkmtSource     thread loops D3DKMTWaitForVerticalBlankEvent (primary)
    WinVsyncClock    drop-in for frame_probe.VsyncClock

Check (run from the repo root, window-free, ~70 s):
    python scripts/bench/win/win_vsync.py --json <out>/vsync_check.json
"""
from __future__ import annotations

import argparse
import ctypes
import json
import statistics
import sys
import threading
import time
from array import array
from typing import Any, Dict, List, Optional, Sequence, Tuple

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes
    _k32 = ctypes.WinDLL("kernel32")
    _dwm = ctypes.WinDLL("dwmapi")
    _gdi = ctypes.WinDLL("gdi32")
    _u32 = ctypes.WinDLL("user32")


# ---------------------------------------------------------------------------
# QPC <-> perf_counter
# ---------------------------------------------------------------------------

def qpc() -> int:
    v = ctypes.c_int64()
    _k32.QueryPerformanceCounter(ctypes.byref(v))
    return v.value


def qpc_freq() -> int:
    v = ctypes.c_int64()
    _k32.QueryPerformanceFrequency(ctypes.byref(v))
    return v.value


def qpc_offset_s(freq: int, n: int = 64) -> Tuple[float, float]:
    """perf_counter() - qpc()/freq (median, spread). ~0 on CPython >= 3.7."""
    offs, spans = [], []
    for _ in range(n):
        a = time.perf_counter()
        q = qpc()
        b = time.perf_counter()
        offs.append((a + b) / 2.0 - q / freq)
        spans.append(b - a)
    return statistics.median(offs), max(spans)


# ---------------------------------------------------------------------------
# Pure helpers (platform independent; unit-testable)
# ---------------------------------------------------------------------------

def reconstruct(samples: Sequence[Tuple[int, int]], period_ticks: float) -> Dict[str, Any]:
    """Fill a vblank timeline from sparse exact (refresh_counter, qpc) samples.

    Between two exact samples every missing counter value is linearly
    interpolated. A gap whose mean interval is > 20% off ``period_ticks``
    (mode change, counter reset, VRR) is left empty and counted.
    """
    pts = sorted(dict(samples).items())
    out: List[float] = []
    n_interp = 0
    bad_gaps = 0
    max_gap = 0
    for (c0, q0), (c1, q1) in zip(pts, pts[1:]):
        dc = c1 - c0
        if dc <= 0:
            continue
        max_gap = max(max_gap, dc)
        step = (q1 - q0) / dc
        out.append(float(q0))
        if period_ticks > 0 and abs(step - period_ticks) > 0.2 * period_ticks:
            bad_gaps += 1
            continue
        for k in range(1, dc):
            out.append(q0 + step * k)
            n_interp += 1
    if pts:
        out.append(float(pts[-1][1]))
    return {"ticks": out, "exact": len(pts), "interpolated": n_interp,
            "bad_gaps": bad_gaps, "max_gap": max_gap}


def fit_residuals_ms(samples: Sequence[Tuple[int, int]], freq: int) -> Dict[str, Optional[float]]:
    """Least-squares q = a + b*c over exact samples; residual spread (ms).

    Small residuals (< 0.1 ms) = the refresh is regular and interpolation
    between sparse polls is exact. Large ones = VRR / unstable timing.
    """
    pts = sorted(dict(samples).items())
    if len(pts) < 3:
        return {"p50": None, "p99": None, "max": None, "period_ms": None}
    c0 = pts[0][0]
    xs = [float(c - c0) for c, _ in pts]
    ys = [float(q) for _, q in pts]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs) or 1.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    res = sorted(abs(y - (a + b * x)) * 1000.0 / freq for x, y in zip(xs, ys))
    return {"p50": pct(res, 0.5), "p99": pct(res, 0.99), "max": res[-1],
            "period_ms": b * 1000.0 / freq}


def pct(sorted_vals: Sequence[float], q: float) -> Optional[float]:
    if not sorted_vals:
        return None
    k = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def interval_stats(times_s: Sequence[float]) -> Dict[str, Any]:
    """Interval stats of a timestamp list (seconds) — ms."""
    t = sorted(times_s)
    iv = sorted((b - a) * 1000.0 for a, b in zip(t, t[1:]))
    if len(iv) < 5:
        return {"n": len(t), "error": "too few samples"}
    med = statistics.median(iv)
    dev = sorted(abs(x - med) for x in iv)
    return {
        "n": len(t),
        "period_ms": med,
        "hz": 1000.0 / med if med > 0 else None,
        "dev_p50_ms": pct(dev, 0.5),
        "dev_p99_ms": pct(dev, 0.99),
        "dev_max_ms": dev[-1],
        "jitter_p99_ms": pct(iv, 0.99) - pct(iv, 0.5),  # same definition as frame_probe
        "missed": sum(1 for x in iv if x > 1.5 * med),
        "short": sum(1 for x in iv if x < 0.5 * med),
    }


def nearest_offsets_ms(a_s: Sequence[float], b_s: Sequence[float]) -> Dict[str, Any]:
    """For each timestamp in ``a``, signed distance to the nearest in ``b`` (ms)."""
    import bisect
    b = sorted(b_s)
    if len(b) < 2 or not a_s:
        return {"n": 0}
    d = []
    for t in a_s:
        i = bisect.bisect_left(b, t)
        cands = [b[j] for j in (i - 1, i) if 0 <= j < len(b)]
        near = min(cands, key=lambda x: abs(x - t))
        d.append((t - near) * 1000.0)
    ds = sorted(d)
    ad = sorted(abs(x) for x in d)
    return {"n": len(d), "median_ms": statistics.median(ds), "p01_ms": pct(ds, 0.01),
            "p99_ms": pct(ds, 0.99), "abs_p99_ms": pct(ad, 0.99)}


# ---------------------------------------------------------------------------
# DWM timing info
# ---------------------------------------------------------------------------

class _RATIO(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("num", ctypes.c_uint32), ("den", ctypes.c_uint32)]


_U32, _U64 = ctypes.c_uint32, ctypes.c_uint64
_DWM_FIELDS = [
    ("cbSize", _U32), ("rateRefresh", _RATIO), ("qpcRefreshPeriod", _U64),
    ("rateCompose", _RATIO), ("qpcVBlank", _U64), ("cRefresh", _U64),
    ("cDXRefresh", _U32), ("qpcCompose", _U64), ("cFrame", _U64),
    ("cDXPresent", _U32), ("cRefreshFrame", _U64), ("cFrameSubmitted", _U64),
    ("cDXPresentSubmitted", _U32), ("cFrameConfirmed", _U64),
    ("cDXPresentConfirmed", _U32), ("cRefreshConfirmed", _U64),
    ("cDXRefreshConfirmed", _U32), ("cFramesLate", _U64),
    ("cFramesOutstanding", _U32), ("cFrameDisplayed", _U64),
    ("qpcFrameDisplayed", _U64), ("cRefreshFrameDisplayed", _U64),
    ("cFrameComplete", _U64), ("qpcFrameComplete", _U64),
    ("cFramePending", _U64), ("qpcFramePending", _U64),
    ("cFramesDisplayed", _U64), ("cFramesComplete", _U64),
    ("cFramesPending", _U64), ("cFramesAvailable", _U64),
    ("cFramesDropped", _U64), ("cFramesMissed", _U64),
    ("cRefreshNextDisplayed", _U64), ("cRefreshNextPresented", _U64),
    ("cRefreshesDisplayed", _U64), ("cRefreshesPresented", _U64),
    ("cRefreshStarted", _U64), ("cPixelsReceived", _U64),
    ("cPixelsDrawn", _U64), ("cBuffersEmpty", _U64),
]


class DWM_TIMING_INFO(ctypes.Structure):  # dwmapi.h wraps it in pshpack1
    _pack_ = 1
    _fields_ = _DWM_FIELDS


class DWM_TIMING_INFO_ALIGNED(ctypes.Structure):  # fallback if pack 1 is refused
    _fields_ = _DWM_FIELDS


def dwm_timing() -> Tuple[int, Any]:
    """(HRESULT, struct) for the whole desktop (hwnd NULL; required on 8.1+)."""
    last = (None, None)
    for cls in (DWM_TIMING_INFO, DWM_TIMING_INFO_ALIGNED):
        info = cls()
        info.cbSize = ctypes.sizeof(cls)
        hr = _dwm.DwmGetCompositionTimingInfo(None, ctypes.byref(info)) & 0xFFFFFFFF
        if hr == 0:
            return 0, info
        last = (hr, info)
    return last  # type: ignore[return-value]


DWM_COUNTERS = ("cFramesLate", "cFramesDropped", "cFramesMissed", "cFrame", "cRefresh")


class DwmTimingSource:
    """Poll DWM timing; keep (cRefresh, qpcVBlank) pairs. Timestamps are
    DWM's own, so polling late (GIL, GC) loses nothing but a sample."""

    name = "dwm"

    def __init__(self, poll_s: float = 0.05) -> None:
        self.poll_s = poll_s
        self.samples: List[Tuple[int, int]] = []
        self.compose_lead: List[float] = []   # (qpcCompose - qpcVBlank) ms, informational
        self.vblank_lead: List[float] = []    # (qpcVBlank - qpc at poll) ms; > 0 = next vblank
        self.period_ticks = 0.0
        self.rate: Optional[Tuple[int, int]] = None
        self.counters0: Dict[str, int] = {}
        self.counters1: Dict[str, int] = {}
        self.polls = 0
        self.errors = 0
        self.error: Optional[str] = None
        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None
        self.freq = qpc_freq()

    def start(self) -> bool:
        hr, info = dwm_timing()
        if hr != 0:
            self.error = f"DwmGetCompositionTimingInfo HRESULT 0x{hr:08X}"
            return False
        self.period_ticks = float(info.qpcRefreshPeriod)
        self.rate = (info.rateRefresh.num, info.rateRefresh.den)
        self.counters0 = {k: int(getattr(info, k)) for k in DWM_COUNTERS}
        self._th = threading.Thread(target=self._run, name="dwm-vsync", daemon=True)
        self._th.start()
        return True

    def _run(self) -> None:
        # Windows-side fix (2026-09-29, Win11 26200 / Intel Iris Xe): with
        # hwnd NULL, cRefresh (and cFrame) increment once per *call*, not per
        # refresh, so keying on cRefresh kept one sample per poll and never
        # interpolated. qpcVBlank is exact (the *next* vblank, 0..1 period
        # ahead of now), so detect a new vblank by qpcVBlank changing and
        # derive the counter from the distance to the previous sample.
        last_q = None
        c = 0
        while not self._stop.is_set():
            hr, info = dwm_timing()
            now = qpc()
            self.polls += 1
            if hr == 0:
                q = int(info.qpcVBlank)
                if q and q != last_q:
                    if last_q is not None and self.period_ticks > 0:
                        c += max(1, int(round((q - last_q) / self.period_ticks)))
                    elif last_q is not None:
                        c += 1
                    self.samples.append((c, q))
                    self.vblank_lead.append((q - now) * 1000.0 / self.freq)
                    if info.qpcCompose:
                        self.compose_lead.append(
                            (int(info.qpcCompose) - int(info.qpcVBlank)) * 1000.0 / self.freq)
                    last_q = q
                self.counters1 = {k: int(getattr(info, k)) for k in DWM_COUNTERS}
            else:
                self.errors += 1
            time.sleep(self.poll_s)

    def stop(self) -> None:
        self._stop.set()
        if self._th is not None:
            self._th.join(timeout=1.0)

    def times_s(self, offset_s: float) -> Tuple[List[float], Dict[str, Any]]:
        rec = reconstruct(self.samples, self.period_ticks)
        ts = [q / self.freq + offset_s for q in rec.pop("ticks")]
        rec["residual"] = fit_residuals_ms(self.samples, self.freq)
        rec["rate_refresh"] = self.rate
        rec["period_ms_dwm"] = self.period_ticks * 1000.0 / self.freq if self.period_ticks else None
        rec["polls"] = self.polls
        rec["poll_errors"] = self.errors
        cl = sorted(self.compose_lead)
        rec["compose_minus_vblank_ms"] = {"p01": pct(cl, 0.01), "p50": pct(cl, 0.5), "p99": pct(cl, 0.99)}
        vl = sorted(self.vblank_lead)
        rec["vblank_minus_poll_ms"] = {"p01": pct(vl, 0.01), "p50": pct(vl, 0.5), "p99": pct(vl, 0.99)}
        rec["dwm_counter_delta"] = {k: self.counters1.get(k, 0) - self.counters0.get(k, 0)
                                    for k in DWM_COUNTERS if self.counters0}
        return ts, rec


class _ThreadWaitSource:
    """Base: a thread blocks in a C call that returns at vblank; stamp after."""

    name = "?"

    def __init__(self) -> None:
        self.t: List[float] = []
        self.error: Optional[str] = None
        self.fail = 0
        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None

    def _open(self) -> bool:
        return True

    def _wait(self) -> bool:
        raise NotImplementedError

    def _close(self) -> None:
        pass

    def start(self) -> bool:
        if not self._open():
            return False
        self._th = threading.Thread(target=self._run, name=f"{self.name}-vsync", daemon=True)
        self._th.start()
        return True

    def _run(self) -> None:
        pc = time.perf_counter
        while not self._stop.is_set():
            if self._wait():
                self.t.append(pc())
            else:
                self.fail += 1
                if self.fail > 50:
                    self.error = self.error or "wait kept failing"
                    return
                time.sleep(0.005)

    def stop(self) -> None:
        self._stop.set()
        if self._th is not None:
            self._th.join(timeout=1.0)
        self._close()

    def times_s(self, offset_s: float = 0.0) -> Tuple[List[float], Dict[str, Any]]:
        return list(self.t), {"fails": self.fail}


class DwmFlushSource(_ThreadWaitSource):
    name = "dwmflush"

    def _wait(self) -> bool:
        return (_dwm.DwmFlush() & 0xFFFFFFFF) == 0


if IS_WIN:
    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _OPEN_FROM_HDC(ctypes.Structure):
        _fields_ = [("hDc", wintypes.HDC), ("hAdapter", ctypes.c_uint32),
                    ("AdapterLuid", _LUID), ("VidPnSourceId", ctypes.c_uint32)]

    class _WAIT_VBLANK(ctypes.Structure):
        _fields_ = [("hAdapter", ctypes.c_uint32), ("hDevice", ctypes.c_uint32),
                    ("VidPnSourceId", ctypes.c_uint32)]

    class _CLOSE_ADAPTER(ctypes.Structure):
        _fields_ = [("hAdapter", ctypes.c_uint32)]


class D3dkmtSource(_ThreadWaitSource):
    """Kernel vblank wait on the primary display's adapter / VidPn source."""

    name = "d3dkmt"

    def _open(self) -> bool:
        try:
            _u32.GetDC.restype = wintypes.HDC
            _u32.GetDC.argtypes = [wintypes.HWND]
            _u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            hdc = _u32.GetDC(None)
            op = _OPEN_FROM_HDC()
            op.hDc = hdc
            st = _gdi.D3DKMTOpenAdapterFromHdc(ctypes.byref(op)) & 0xFFFFFFFF
            _u32.ReleaseDC(None, hdc)
            if st != 0:
                self.error = f"D3DKMTOpenAdapterFromHdc NTSTATUS 0x{st:08X}"
                return False
            self._w = _WAIT_VBLANK(op.hAdapter, 0, op.VidPnSourceId)
            self._h = op.hAdapter
            return True
        except Exception as exc:
            self.error = f"d3dkmt unavailable: {exc}"
            return False

    def _wait(self) -> bool:
        return (_gdi.D3DKMTWaitForVerticalBlankEvent(ctypes.byref(self._w)) & 0xFFFFFFFF) == 0

    def _close(self) -> None:
        try:
            _gdi.D3DKMTCloseAdapter(ctypes.byref(_CLOSE_ADAPTER(self._h)))
        except Exception:
            pass


SOURCES = {"dwm": DwmTimingSource, "dwmflush": DwmFlushSource, "d3dkmt": D3dkmtSource}


# ---------------------------------------------------------------------------
# Drop-in for frame_probe.VsyncClock
# ---------------------------------------------------------------------------

class WinVsyncClock:
    """Same surface as ``frame_probe.VsyncClock``: times / period_s /
    available / error / start() / stop(). ``times`` is filled on stop()."""

    def __init__(self, source: str = "dwm", poll_s: float = 0.05) -> None:
        self.times = array("d")
        self.period_s: Optional[float] = None
        self.available = False
        self.error: Optional[str] = None
        self.source_name = source
        self.meta: Dict[str, Any] = {"source": source}
        self._poll_s = poll_s
        self._src: Any = None
        self._stopped = False

    def start(self) -> bool:
        if not IS_WIN:
            self.error = "WinVsyncClock needs Windows"
            return False
        freq = qpc_freq()
        self._offset, spread = qpc_offset_s(freq)
        self.meta.update({"qpc_freq": freq, "qpc_offset_s": self._offset, "qpc_offset_spread_s": spread})
        cls = SOURCES[self.source_name]
        self._src = cls(poll_s=self._poll_s) if cls is DwmTimingSource else cls()
        if not self._src.start():
            self.error = self._src.error
            return False
        self.available = True
        return True

    def stop(self) -> None:
        if self._stopped or self._src is None:
            return
        self._stopped = True
        self._src.stop()
        ts, info = self._src.times_s(self._offset)
        self.times = array("d", sorted(ts))
        self.meta.update(info)
        st = interval_stats(self.times)
        self.meta["intervals"] = st
        if st.get("period_ms"):
            self.period_s = st["period_ms"] / 1000.0
        if len(self.times) < 10:
            self.available = False
            self.error = self.error or f"{self.source_name}: only {len(self.times)} vsyncs"


# ---------------------------------------------------------------------------
# Check CLI
# ---------------------------------------------------------------------------

def _busy(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:  # holds the GIL like PRECISION busy-wait
        pass


def _run_phase(names: Sequence[str], seconds: float, busy: bool, offset: float,
               poll_s: float = 0.05) -> Dict[str, Any]:
    srcs = {}
    for n in names:
        cls = SOURCES[n]
        srcs[n] = cls(poll_s=poll_s) if cls is DwmTimingSource else cls()
    started = {n: s.start() for n, s in srcs.items()}
    if busy:
        _busy(seconds)
    else:
        time.sleep(seconds)
    out: Dict[str, Any] = {}
    series: Dict[str, List[float]] = {}
    for n, s in srcs.items():
        s.stop()
        if not started[n]:
            out[n] = {"available": False, "error": s.error}
            continue
        ts, info = s.times_s(offset)
        series[n] = ts
        out[n] = {"available": True, "intervals": interval_stats(ts), **info}
    if len(series) == 2:
        a, b = list(series)
        out[f"offset_{a}_vs_{b}"] = nearest_offsets_ms(series[a], series[b])
    return out


def main(argv=None) -> int:
    if not IS_WIN:
        raise SystemExit("win_vsync.py check needs Windows")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seconds", type=float, default=8.0, help="per phase (default 8)")
    p.add_argument("--json", dest="json_path", default=None)
    a = p.parse_args(argv)
    freq = qpc_freq()
    off, spread = qpc_offset_s(freq)
    hr, info = dwm_timing()
    rep: Dict[str, Any] = {
        "python": sys.version,
        "perf_counter": str(time.get_clock_info("perf_counter")),
        "qpc_freq": freq,
        "perf_counter_minus_qpc_s": off,
        "offset_read_spread_s": spread,
        "switch_interval_s": sys.getswitchinterval(),
        "dwm_hresult": f"0x{hr:08X}",
        "dwm_struct_size": ctypes.sizeof(type(info)) if info is not None else None,
        "dwm_rate_refresh": (info.rateRefresh.num, info.rateRefresh.den) if hr == 0 else None,
        "dwm_period_ms": info.qpcRefreshPeriod * 1000.0 / freq if hr == 0 else None,
        "phases": {},
    }
    S = a.seconds
    plan = [
        ("idle_dwm_poll2ms", ["dwm"], False, 0.002),
        ("idle_dwm_poll50ms", ["dwm"], False, 0.05),
        ("idle_dwmflush", ["dwmflush"], False, 0.05),
        ("idle_d3dkmt", ["d3dkmt"], False, 0.05),
        ("busy_dwm_poll50ms", ["dwm"], True, 0.05),
        ("busy_dwmflush", ["dwmflush"], True, 0.05),
        ("busy_d3dkmt", ["d3dkmt"], True, 0.05),
        ("pair_idle_d3dkmt_dwm", ["d3dkmt", "dwm"], False, 0.002),
        ("pair_idle_dwmflush_dwm", ["dwmflush", "dwm"], False, 0.002),
    ]
    for name, srcs, busy, poll in plan:
        print(f"phase {name} ({S:g} s)...", flush=True)
        rep["phases"][name] = _run_phase(srcs, S, busy, off, poll)
    old = sys.getswitchinterval()
    sys.setswitchinterval(0.0005)
    print(f"phase busy_d3dkmt_switch0.5ms ({S:g} s)...", flush=True)
    rep["phases"]["busy_d3dkmt_switch0.5ms"] = _run_phase(["d3dkmt"], S, True, off)
    sys.setswitchinterval(old)

    print(json.dumps({k: v for k, v in rep.items() if k != "phases"}, indent=1, default=str))
    print(f"{'phase':32} {'src':9} {'n':>5} {'period':>8} {'dev p99':>8} {'dev max':>8} {'miss':>5}")
    for ph, res in rep["phases"].items():
        for src, r in res.items():
            if src.startswith("offset_"):
                print(f"{ph:32} {src}: median {r.get('median_ms')} ms  abs p99 {r.get('abs_p99_ms')} ms")
                continue
            if not r.get("available"):
                print(f"{ph:32} {src:9} unavailable: {r.get('error')}")
                continue
            iv = r["intervals"]
            if "error" in iv:
                print(f"{ph:32} {src:9} {iv}")
                continue
            print(f"{ph:32} {src:9} {iv['n']:5d} {iv['period_ms']:8.4f} {iv['dev_p99_ms']:8.3f} "
                  f"{iv['dev_max_ms']:8.3f} {iv['missed']:5d}")
    if a.json_path:
        with open(a.json_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
