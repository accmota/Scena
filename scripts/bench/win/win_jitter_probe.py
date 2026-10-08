"""jitter_probe.py on Windows: real vsync timeline, Windows RSS, raw dump.

Wraps scripts/bench/jitter_probe.py without editing it (its hash is part of
protocol longrun-1). Patches, for this process only:

* ``frame_probe.VsyncClock``    -> win_vsync.WinVsyncClock (default DWM timing)
* ``frame_probe.current_rss_mb`` -> GetProcessMemoryInfo (else NaN on Windows)
* ``FrameProbe.analyze``        -> adds rep["win"] and writes --raw

    python scripts/bench/win/win_jitter_probe.py [wrapper opts] <jitter_probe args>

Wrapper options (must come before the script path):
    --vsync-source dwm|d3dkmt|dwmflush   (default dwm)
    --poll-ms 50                          DWM poll period
    --raw PATH                            per-frame + vsync arrays as JSON
    --display windowed|maximized|fullscreen
    --timer-res-1                         timeBeginPeriod(1) for the run
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
for _p in (_HERE, _BENCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import win_vsync  # noqa: E402


def split_argv(argv):
    """(wrapper_argv, probe_argv): wrapper options are the leading --opts it knows."""
    own = {"--vsync-source": 1, "--poll-ms": 1, "--raw": 1, "--display": 1, "--timer-res-1": 0}
    w, i = [], 0
    while i < len(argv):
        a = argv[i]
        key = a.split("=", 1)[0]
        if key not in own:
            break
        n = 0 if "=" in a else own[key]
        w.extend(argv[i:i + 1 + n])
        i += 1 + n
    return w, argv[i:]


def win_rss_mb() -> float:
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        c = PMC()
        c.cb = ctypes.sizeof(c)
        if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return c.WorkingSetSize / (1024.0 * 1024.0)
    except Exception:
        pass
    return float("nan")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    wargv, pargv = split_argv(argv)
    wp = argparse.ArgumentParser(prog="win_jitter_probe.py")
    wp.add_argument("--vsync-source", choices=sorted(win_vsync.SOURCES), default="dwm")
    wp.add_argument("--poll-ms", type=float, default=50.0)
    wp.add_argument("--raw", default=None)
    wp.add_argument("--display", choices=("windowed", "maximized", "fullscreen"), default=None)
    wp.add_argument("--timer-res-1", action="store_true")
    w = wp.parse_args(wargv)

    import frame_probe
    import jitter_probe

    clocks = []

    def make_clock():
        c = win_vsync.WinVsyncClock(w.vsync_source, poll_s=w.poll_ms / 1000.0)
        clocks.append(c)
        return c

    frame_probe.VsyncClock = make_clock
    if sys.platform == "win32":
        frame_probe.current_rss_mb = win_rss_mb

    cpu0 = [None]
    orig_on_run_start = frame_probe.FrameProbe._on_run_start
    orig_analyze = frame_probe.FrameProbe.analyze

    def _on_run_start(self, fw):
        cpu0[0] = (time.process_time(), time.perf_counter())
        return orig_on_run_start(self, fw)

    def analyze(self):
        rep = orig_analyze(self)
        clk = clocks[-1] if clocks else None
        win = {
            "vsync_source": w.vsync_source,
            "poll_ms": w.poll_ms,
            "display": w.display,
            "timer_res_1": w.timer_res_1,
            "clock": getattr(clk, "meta", None),
            "clock_error": getattr(clk, "error", None),
            "switch_interval_s": sys.getswitchinterval(),
        }
        if cpu0[0] is not None and len(self.t_start):
            p0, t0 = cpu0[0]
            wall = max(1e-6, self.t_start[-1] - t0)
            win["process_cpu_pct_of_one_core"] = 100.0 * (time.process_time() - p0) / wall
        rep["win"] = win
        if w.raw:
            raw = {
                "t_start": list(self.t_start), "t_swap_end": list(self.t_swap_end),
                "work_ms": list(self.work), "swap_ms": list(self.swap),
                "gc_ms": list(self.gc_ms), "gc_gen": list(self.gc_gen),
                "vsync": list(clk.times) if clk is not None else [],
                "vsync_period_s": getattr(clk, "period_s", None),
                "meta": dict(self.meta), "win": win,
            }
            os.makedirs(os.path.dirname(os.path.abspath(w.raw)) or ".", exist_ok=True)
            with open(w.raw, "w", encoding="utf-8") as f:
                json.dump(raw, f, default=str)
        return rep

    frame_probe.FrameProbe._on_run_start = _on_run_start
    frame_probe.FrameProbe.analyze = analyze

    if w.display:
        import scena  # noqa: F401
        from scena.orchestration import ScenaFramework
        ScenaFramework.get_instance().display = w.display  # stored; applied at window open

    winmm = None
    if w.timer_res_1 and sys.platform == "win32":
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)
    try:
        return jitter_probe.main(pargv)
    finally:
        if winmm is not None:
            winmm.timeEndPeriod(1)


if __name__ == "__main__":
    sys.exit(main())
