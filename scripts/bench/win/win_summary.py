"""Markdown runs table from the reports of win_jitter_probe.py.

    python scripts/bench/win/win_summary.py scripts/bench/results/windows-jitter
    python scripts/bench/win/win_summary.py scripts/bench/results/windows-jitter-fix --prefix V

``R*`` (default): the 2026-09-29 data-collection matrix. ``--prefix V``: the
verification table for the pacing fix (pacer strategy, vblank grid check,
gen-2 during play, frozen objects).
"""
from __future__ import annotations

import glob
import json
import os
import sys


def g(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def f(v, n=2):
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:.{n}f}"
    return str(v)


COLS = ("run", "present → mode Hz", "display", "src", "fps", "frames Hz / refresh Hz",
        "held /min (ep /min)", "spacing s (beat s)", "hitch /min", "dur p99 / p99.9 / max",
        "work p50 / p99", "swap p50", "pace p50", "late p99", "gc2 n / max", "CPU %1core",
        "DWM missed/dropped/late Δ")


def row(name, r):
    m = r.get("meta", {})
    pr = r.get("present") or {}
    w = r.get("win") or {}
    ds = r.get("dur_steady") or {}
    ws = r.get("work_steady") or {}
    ph = r.get("phase_median_ms") or {}
    dd = g(w, "clock", "dwm_counter_delta", default={}) or {}
    exp = r.get("experiments") or {}
    present = f"{m.get('present_arg')}{' +gcfreeze' if exp.get('gc_freeze') else ''}" \
              f"{' +tr1' if w.get('timer_res_1') else ''} → {m.get('present_mode')} {f(m.get('present_hz'), 0)}"
    return [
        name, present, w.get("display") or "windowed", w.get("vsync_source", "—"), f(r.get("fps"), 1),
        f"{f(pr.get('frames_hz'), 4)} / {f(pr.get('refresh_hz'), 4)}" if pr.get("available") else f"— / {f(r.get('display_hz'), 3)}",
        f"{f(pr.get('held_per_min'))} ({f(pr.get('episodes_per_min'))})" if pr.get("available") else "n/a",
        f"{f(pr.get('episode_spacing_s'), 1)} ({f(pr.get('predicted_beat_s'), 1)})" if pr.get("available") else "n/a",
        f(g(r, "hitches", "steady_per_min")),
        f"{f(ds.get('p99'))} / {f(ds.get('p999'))} / {f(ds.get('max'), 1)}",
        f"{f(ws.get('p50'))} / {f(ws.get('p99'))}",
        f(ph.get("swap")), f(ph.get("pace")), f(g(r, "pacing", "late_p99_ms"), 3),
        f"{g(r, 'gc', 'gen2', 'count', default='—')} / {f(g(r, 'gc', 'gen2_max_ms'), 1)}",
        f(w.get("process_cpu_pct_of_one_core"), 0),
        "/".join(str(dd.get(k, "—")) for k in ("cFramesMissed", "cFramesDropped", "cFramesLate")) if dd else "—",
    ]


VCOLS = ("run", "present → mode Hz", "display", "src", "pacer (n) [fallback]", "FX Auto (changes)", "fps",
         "vblank steps", "off-cadence /min", "phase p01/p50/p99", "held /min (ep /min)",
         "hitch /min", "dur p99 / max", "work p50 / p99", "gc2 in play n / max", "frozen",
         "CPU %1core")


def fx_path(r) -> str:
    """FX Auto rungs in order and the number of changes after the first
    (the probe's first event is Auto being applied at the first frame)."""
    rungs = [e.get("detail") for e in (r.get("events") or []) if e.get("kind") == "fx_auto"]
    if not rungs:
        return "—"
    path = [rungs[0]]
    for rung in rungs[1:]:
        if rung != path[-1]:
            path.append(rung)
    return f"{' → '.join(path)} ({len(path) - 1})"


def vrow(name, r):
    """Verification row: did the pacer lock, and is the cadence even?"""
    m = r.get("meta", {})
    pr = r.get("present") or {}
    w = r.get("win") or {}
    vb = r.get("vblank_steps") or {}
    ds = r.get("dur_steady") or {}
    ws = r.get("work_steady") or {}
    pz = m.get("pacer_end") or m.get("pacer") or {}
    pacer = "—"
    if pz:
        pacer = f"{pz.get('strategy')} ({pz.get('interval')})"
        if pz.get("slips") is not None:
            pacer += f" slips {pz.get('slips')}"
            if pz.get("overruns") is not None:
                pacer += f" (overruns {pz.get('overruns')})"
            pacer += f"/{pz.get('presents')}"
        if pz.get("fallback"):
            pacer += f" [{pz.get('fallback')}]"
    # gen-2 passes in play (the setup collect before the freeze runs before frame 1).
    n_play = g(r, "gc", "gen2_play_count")
    if n_play is None:  # older probe: count from the (capped) times list
        n_play = len([t for t in (g(r, "gc", "gen2_times_s", default=[]) or []) if t > 0.5])
    play_max = g(r, "gc", "gen2_play_max_ms")
    cpu = m.get("cpu_pct_one_core", w.get("process_cpu_pct_of_one_core"))
    return [
        name, f"{m.get('present_arg')} → {m.get('present_mode')} {f(m.get('present_hz'), 0)}",
        w.get("display") or "windowed", w.get("vsync_source", "—"), pacer, fx_path(r),
        f(r.get("fps"), 1),
        str(vb.get("hist")) if vb.get("available") else "n/a",
        f(vb.get("off_per_min")) if vb.get("available") else "n/a",
        f"{f(vb.get('phase_p01'), 3)}/{f(vb.get('phase_p50'), 3)}/{f(vb.get('phase_p99'), 3)}"
        if vb.get("available") else "n/a",
        f"{f(pr.get('held_per_min'))} ({f(pr.get('episodes_per_min'))})" if pr.get("available") else "n/a",
        f(g(r, "hitches", "steady_per_min")),
        f"{f(ds.get('p99'))} / {f(ds.get('max'), 1)}",
        f"{f(ws.get('p50'))} / {f(ws.get('p99'))}",
        f"{n_play} / {f(play_max, 1) if n_play else '—'}",
        str(m.get("gc_frozen", "—")),
        f(cpu, 0),
    ]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    prefix = "R"
    if "--prefix" in argv:
        i = argv.index("--prefix")
        prefix = argv[i + 1]
        del argv[i:i + 2]
    out_dir = argv[0] if argv else "."
    cols, make = (COLS, row) if prefix == "R" else (VCOLS, vrow)
    paths = sorted(p for p in glob.glob(os.path.join(out_dir, prefix + "*.json"))
                   if not p.endswith(".raw.json"))
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            r = json.load(fh)
        name = os.path.splitext(os.path.basename(p))[0]
        print("| " + " | ".join(make(name, r)) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
