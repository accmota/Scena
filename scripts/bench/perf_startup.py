"""Startup + warm-up isolate — time to first frame, and what the first seconds cost.

A beginner's first impression is the launch: how long until something is on
screen, and whether the first seconds stutter while caches fill (Skia shader
programs, glyph atlases, lazy image decode, first-touch graph slots, early
GC generations). Each sample is a **fresh process** (warm OS file cache and
.pyc — a second launch, not a first-ever one).

Stages (ms, from the parent's spawn; perf_counter is system-wide on macOS/Linux):

  python      spawn → first line of this script (interpreter + site)
  import      ``import scena`` (skia, glfw, numpy, SkSL compile at import)
  build       construct a representative scene (fields, shapes, sprites, text, FX)
  window      ``open_window`` (GLFW window + GL context + Skia surface)
  first       first frame through present (includes lazy first-use work)
  ttff        spawn → first frame presented                      ← headline

Warm-up (uncapped, real loop via ``frame_probe``): frames in the first 2 s vs
the steady median of seconds 3–4:

  warm_excess  Σ max(0, work − steady p50) over the first 2 s (ms of extra work)
  warm_spikes  frames with work > 2× steady p50 + 1 ms
  warm_worst   worst single frame work in the first 2 s

Usage
-----
    python scripts/bench/perf_startup.py                 # 5 fresh launches, print
    python scripts/bench/perf_startup.py --headless      # python + import only (no window; CI-safe)
    python scripts/bench/perf_startup.py --pulse         # protocol startup-1, append startup.md
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_T_SCRIPT = time.perf_counter()
PROTOCOL = "startup-1"
_BENCH = os.path.dirname(os.path.abspath(__file__))
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

_KEYS = ("python_ms", "import_ms", "build_ms", "window_ms", "first_ms", "ttff_ms",
         "warm_excess_ms", "warm_spikes", "warm_worst_ms", "steady_work_ms")


# ---------------------------------------------------------------------------
# Worker (one fresh launch)
# ---------------------------------------------------------------------------

def _worker(headless: bool) -> None:
    t_spawn = float(os.environ["STARTUP_SPAWN_T"])
    out: Dict[str, Any] = {"python_ms": (_T_SCRIPT - t_spawn) * 1000.0}
    t0 = time.perf_counter()
    import scena  # noqa: F401
    t1 = time.perf_counter()
    out["import_ms"] = (t1 - t0) * 1000.0
    if headless:
        print("RESULT_JSON: " + json.dumps(out))
        return

    from scena import (  # noqa: E402
        Circle, Color, Glow, Rect, RegularPolygon, Sheet, SkyGradient,
        Sprite, Stars, Text, Vignette, canvas, init, run, set_fx_auto,
    )
    from scena.orchestration import set_leak_detector
    from scena.process import set_watchdog
    from fingerprint import REPO_ROOT
    from frame_probe import FrameProbe

    init(width=1000, height=700, title="Bench — startup")
    set_fx_auto(False)
    canvas.fx_quality = "high"
    set_watchdog(False)
    set_leak_detector(False)
    canvas.framerate = "max"

    tb0 = time.perf_counter()
    SkyGradient("night")
    Stars(density=0.8, amount=0.8)
    canvas.effects.add(Vignette(amount=0.25))
    sheet = Sheet(str(REPO_ROOT / "examples" / "media" / "shooter" / "sheet.xml"))
    frames = ("playerShip1_blue.png", "enemyRed1.png", "ufoGreen.png", "meteorBrown_big1.png")
    for i in range(12):
        Sprite(sheet, frame=frames[i % len(frames)], size=40, center=(80 + i * 70, 560))
    for i in range(60):
        x, y = 60 + (i % 15) * 60, 120 + (i // 15) * 80
        if i % 3 == 0:
            Circle(center=(x, y), radius=14).set_color("gold")
        elif i % 3 == 1:
            Rect(center=(x, y), width=26, height=18).set_color("tomato")
        else:
            RegularPolygon(center=(x, y), radius=14, n=6).set_color("sky blue")
    for i in range(4):
        t = Text(text=f"Score {i * 1000:06d}", top_left=(20, 680 - i * 22 + 19), font_size=16,
                 color=Color(0.9, 0.92, 1.0, 1), stack=False)
        if i == 0:
            t.glow = Glow()
    tb1 = time.perf_counter()
    out["build_ms"] = (tb1 - tb0) * 1000.0

    import importlib
    orch = importlib.import_module("scena.orchestration")
    orig_open = orch.ScenaFramework.open_window
    win = {}

    def open_window(self):
        w0 = time.perf_counter()
        try:
            return orig_open(self)
        finally:
            win["ms"] = (time.perf_counter() - w0) * 1000.0

    orch.ScenaFramework.open_window = open_window
    probe = FrameProbe(seconds=4.0, present="none", vsync=False, startup_s=2.0).install()

    run()
    probe.uninstall()
    out["window_ms"] = win.get("ms", float("nan"))
    if len(probe.t_start) < 10:
        out["error"] = "too few frames"
        print("RESULT_JSON: " + json.dumps(out))
        return
    out["first_ms"] = (probe.t_swap_end[0] - probe.t_start[0]) * 1000.0
    out["ttff_ms"] = (probe.t_swap_end[0] - t_spawn) * 1000.0
    base = probe.t_start[0]
    work = list(probe.work)
    rel = [t - base for t in probe.t_start]
    steady = [w for w, r in zip(work, rel) if 3.0 <= r < 4.0] or work[len(work) // 2:]
    p50 = statistics.median(steady)
    warm = [w for w, r in zip(work, rel) if r < 2.0]
    out["steady_work_ms"] = p50
    out["warm_excess_ms"] = sum(max(0.0, w - p50) for w in warm)
    out["warm_spikes"] = sum(1 for w in warm if w > 2.0 * p50 + 1.0)
    out["warm_worst_ms"] = max(warm) if warm else float("nan")
    out["warm_top"] = [
        {"t": round(r, 3), "work_ms": round(w, 2)}
        for w, r in sorted(((w, r) for w, r in zip(work, rel) if r < 2.0), reverse=True)[:6]
    ]
    print("RESULT_JSON: " + json.dumps(out))


# ---------------------------------------------------------------------------
# Parent
# ---------------------------------------------------------------------------

def _launch(headless: bool) -> Dict[str, Any]:
    env = dict(os.environ)
    # An author's import reads cached bytecode. A shell that disables it
    # (Claude Code sets PYTHONDONTWRITEBYTECODE=1) compiles scena from source
    # on every launch and doubled import_ms in the 2026-10-12 run (games.md B4).
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env["STARTUP_WORKER"] = "1"
    cmd = [sys.executable, os.path.abspath(__file__)]
    if headless:
        cmd.append("--headless")
    env["STARTUP_SPAWN_T"] = repr(time.perf_counter())
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    for line in text.splitlines():
        if line.startswith("RESULT_JSON:"):
            row = json.loads(line.split(":", 1)[1])
            row["ok"] = proc.returncode == 0 and "error" not in row
            return row
    print(text)
    return {"ok": False}


def _median(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if r.get("ok")]
    out: Dict[str, Any] = {"n": len(ok)}
    for k in _KEYS:
        vals = [float(r[k]) for r in ok if r.get(k) is not None]
        if vals:
            out[k] = statistics.median(vals)
            out[f"{k}_min"] = min(vals)
            out[f"{k}_max"] = max(vals)
    return out


def _print(res: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> None:
    print("=" * 60)
    print(f"startup  launches={res['n']} (median, min–max)")
    for k in _KEYS:
        if k in res:
            print(f"  {k:16s} {res[k]:9.2f}   ({res[k + '_min']:.2f}–{res[k + '_max']:.2f})")
    tops = [r.get("warm_top") for r in rows if r.get("warm_top")]
    if tops:
        print("  warm-up worst frames (launch 1): " + ", ".join(
            f"{e['t']:.2f}s {e['work_ms']:.1f}ms" for e in tops[0]))
    print("=" * 60)


def _pulse(res: Dict[str, Any], no_append: bool) -> None:
    from fingerprint import script_hashes
    from pulse import (
        append_pulse, autodiff, latest_scena_fingerprint, now_meta,
        parse_leading_float, parse_summary_table, print_autodiff_banner,
    )
    log_path = Path(_BENCH) / "startup.md"
    meta = now_meta()
    hashes = script_hashes(("perf_startup.py", "frame_probe.py"), Path(_BENCH))

    def f(k: str, d: int = 1) -> str:
        v = res.get(k)
        return "—" if v is None else f"{v:.{d}f}"

    row = (
        f"| {meta['date']} | `{PROTOCOL}` | {meta['host_s']} | {f('ttff_ms', 0)} | "
        f"{f('import_ms', 0)} | {f('build_ms', 0)} | {f('window_ms', 0)} | {f('first_ms', 1)} | "
        f"{f('warm_excess_ms', 1)} ({f('warm_spikes', 0)}) | |"
    )
    hash_s = " · ".join(f"`{k}` `{v}`" for k, v in hashes.items())
    lines = [
        f"### {meta['date']} — {PROTOCOL}",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `{PROTOCOL}` |",
        f"| Host | {meta['host_s']} |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        f"| Launches | {res['n']} fresh processes (median) |",
        f"| Scripts | {hash_s} |",
        "",
        "| Stage | median ms | min–max |",
        "|-------|---------:|--------:|",
    ]
    for k in _KEYS:
        if k in res:
            lines.append(f"| {k} | {res[k]:.2f} | {res[k + '_min']:.2f}–{res[k + '_max']:.2f} |")
    lines.append("")
    section = "\n".join(lines)
    prev_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    prev = None
    for cells in parse_summary_table(prev_text):
        if len(cells) >= 8 and cells[1].strip().strip("`") == PROTOCOL:
            prev = {"ttff_ms": parse_leading_float(cells[3]),
                    "import_ms": parse_leading_float(cells[4]),
                    "first_ms": parse_leading_float(cells[7])}
            break
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same = (prev_fp == meta["scena_fingerprint"]) if prev_fp else None
    new = {k: res[k] for k in ("ttff_ms", "import_ms", "first_ms") if k in res}
    print_autodiff_banner(
        autodiff(new, {k: v for k, v in (prev or {}).items() if v is not None},
                 same_scena=same, prev_label=f"last {PROTOCOL} row"),
        same_scena=same,
    )
    print(section)
    if not no_append:
        append_pulse(log_path, row, section)
        print(f"appended {log_path}")
        try:
            from dashboard import refresh as refresh_dashboard
            refresh_dashboard()
        except Exception as exc:
            print(f"(dashboard refresh skipped: {exc})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--launches", type=int, default=5)
    p.add_argument("--headless", action="store_true", help="python + import only (no window)")
    p.add_argument("--pulse", action="store_true", help=f"protocol {PROTOCOL}: 5 launches, append startup.md")
    p.add_argument("--no-append", action="store_true")
    p.add_argument("--json", dest="json_path", default=None)
    args = p.parse_args()
    if os.environ.get("STARTUP_WORKER"):
        _worker(args.headless)
        return
    n = 5 if args.pulse else max(1, args.launches)
    headless = args.headless and not args.pulse
    rows = []
    for i in range(n):
        r = _launch(headless)
        print(f"launch {i + 1}/{n}: " + ", ".join(
            f"{k}={r[k]:.1f}" for k in _KEYS if isinstance(r.get(k), (int, float))), flush=True)
        rows.append(r)
    res = _median(rows)
    _print(res, rows)
    if args.json_path:
        Path(args.json_path).write_text(json.dumps({"median": res, "launches": rows}, indent=1) + "\n", encoding="utf-8")
    if args.pulse:
        _pulse(res, args.no_append)
    print("RESULT_JSON: " + json.dumps({k: res.get(k) for k in _KEYS}))


if __name__ == "__main__":
    main()
