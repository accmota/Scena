"""Asset first-use isolate — what a never-seen image costs the frame it appears in.

``skia.Image.open`` is lazy: decode (and GPU upload) happen on the first frame
that *draws* the image, not at construct. So spawning a new sprite, sheet or
wallpaper mid-game can hitch that frame. This isolate spawns each asset into a
running scene (uncapped, real loop via ``frame_probe``), first **cold** (fresh
process, empty caches) then **warm** (same asset again), and reports the
frame's excess work over the steady median.

Assets (small → large)
----------------------
  sprite     single small PNG sprite
  atlas      Kenney XML atlas (1024² sheet) + one frame
  strip      10-file frame sequence (ninja run)
  hitbox     new atlas frame with ``hitbox_shape="auto"`` + collision rule (fit cost)
  wall_jpg   Wallpaper 1280×920 JPEG
  wall_png   Wallpaper 2669×1782 PNG (6 MB)

Per asset: ``construct`` (constructor call), ``cold`` / ``warm`` (frame excess,
includes construct + first draw), ``decode`` (plain Skia raster decode, CPU only
— the rest of ``cold`` is GPU upload + framework work).

Usage
-----
    python scripts/bench/perf_assets.py              # 3 fresh processes, print
    python scripts/bench/perf_assets.py --pulse      # protocol assets-1, append assets.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

PROTOCOL = "assets-1"
_BENCH = os.path.dirname(os.path.abspath(__file__))
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from fingerprint import REPO_ROOT  # noqa: E402

MEDIA = REPO_ROOT / "examples" / "media"
ASSETS = ("sprite", "atlas", "strip", "hitbox", "wall_jpg", "wall_png")
FILES = {
    "sprite": [MEDIA / "planets" / "planet08.png"],
    "atlas": [MEDIA / "shooter" / "sheet.png"],
    "strip": [Path(p) for p in sorted(glob.glob(str(MEDIA / "ninja" / "Run__*.png")))[:10]],
    "hitbox": [],
    "wall_jpg": [MEDIA / "images" / "bg1.jpeg"],
    "wall_png": [MEDIA / "images" / "bg2.png"],
}
BASELINE_S = 1.5    # steady scene before the first spawn
GAP_S = 0.4         # between spawns
WARM_AT_S = BASELINE_S + GAP_S * len(ASSETS) + 0.6


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _worker() -> None:
    from scena import (
        Circle, Sheet, Sprite, Wallpaper, canvas, collide_stay,
        init, run, set_fx_auto,
    )
    from scena.orchestration import set_leak_detector
    from scena.process import set_watchdog
    from frame_probe import FrameProbe

    init(width=1000, height=700, title="Bench — asset first use")
    set_fx_auto(False)
    canvas.fx_quality = "high"
    canvas.background = (0.05, 0.06, 0.09)
    set_watchdog(False)
    set_leak_detector(False)
    canvas.framerate = "max"
    for i in range(40):
        Circle(center=(40 + (i % 20) * 48, 300 + (i // 20) * 60), radius=12).set_color("sky blue")

    @collide_stay("probe_rock", "probe_rock")
    def _rocks(a, b, info):
        pass

    sheet_path = str(MEDIA / "shooter" / "sheet.xml")
    strip = [str(p) for p in FILES["strip"]]
    held: List[Any] = []

    def spawn(name: str, k: int) -> None:
        x = 120 + ASSETS.index(name) * 140
        y = 560 if k == 0 else 160
        if name == "sprite":
            held.append(Sprite(str(FILES["sprite"][0]), size=48, center=(x, y)))
        elif name == "atlas":
            held.append(Sprite(Sheet(sheet_path), frame="playerShip1_blue.png", size=48, center=(x, y)))
        elif name == "strip":
            held.append(Sprite(Sheet(strip, fps=12), size=64, center=(x, y)))
        elif name == "hitbox":
            held.append(Sprite(Sheet(sheet_path), frame="meteorBrown_big1.png", size=56,
                               center=(x, y), hitbox_shape="auto", group="probe_rock"))
        elif name == "wall_jpg":
            Wallpaper(str(FILES["wall_jpg"][0]), fit="cover")
        elif name == "wall_png":
            Wallpaper(str(FILES["wall_png"][0]), fit="cover")

    schedule: List[Tuple[float, str, int]] = []
    for k, t0 in enumerate((BASELINE_S, WARM_AT_S)):
        for i, name in enumerate(ASSETS):
            schedule.append((t0 + i * GAP_S, name, k))
    end_s = WARM_AT_S + GAP_S * len(ASSETS) + 0.8
    probe = FrameProbe(seconds=end_s, present="none", vsync=False, startup_s=0.0).install()
    marks: List[Dict[str, Any]] = []
    state = {"i": 0, "t0": None}

    def update(dt):
        now = time.perf_counter()
        if state["t0"] is None:
            state["t0"] = now
        rel = now - state["t0"]
        while state["i"] < len(schedule) and rel >= schedule[state["i"]][0]:
            _t, name, k = schedule[state["i"]]
            c0 = time.perf_counter()
            spawn(name, k)
            marks.append({"asset": name, "kind": "cold" if k == 0 else "warm",
                          "frame": len(probe.t_start), "construct_ms": (time.perf_counter() - c0) * 1000.0})
            state["i"] += 1

    from scena.orchestration import ScenaFramework
    ScenaFramework.get_instance().update = update
    run()
    probe.uninstall()

    work = list(probe.work)
    starts = list(probe.t_start)
    marked = {m["frame"] for m in marks}
    marked |= {f + 1 for f in marked}
    out: Dict[str, Any] = {"steady_work_ms": statistics.median(work[20:]), "assets": {}}
    for m in marks:
        f = m["frame"]
        if f + 1 >= len(work):
            continue
        # Local baseline: the 0.3 s before the spawn (a wallpaper raises steady cost).
        t_f = starts[f]
        local = [work[i] for i in range(max(0, f - 5000), f)
                 if i not in marked and t_f - 0.3 <= starts[i] < t_f - 0.01]
        p50 = statistics.median(local) if local else out["steady_work_ms"]
        ex0 = work[f] - p50
        ex1 = work[f + 1] - p50
        excess = max(0.0, ex0) + (ex1 if ex1 > 1.0 else 0.0)
        row = out["assets"].setdefault(m["asset"], {})
        row[m["kind"]] = excess
        row[f"{m['kind']}_construct"] = m["construct_ms"]
    import skia
    for name in ASSETS:
        files = FILES[name]
        if not files:
            continue
        d0 = time.perf_counter()
        for pth in files:
            img = skia.Image.open(str(pth))
            if img is not None:
                img.makeRasterImage()
        out["assets"][name]["decode"] = (time.perf_counter() - d0) * 1000.0
    print("RESULT_JSON: " + json.dumps(out))


# ---------------------------------------------------------------------------
# Parent
# ---------------------------------------------------------------------------

def _launch() -> Dict[str, Any]:
    env = dict(os.environ)
    env["ASSETS_WORKER"] = "1"
    proc = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env,
                          capture_output=True, text=True, cwd=str(REPO_ROOT))
    text = (proc.stdout or "") + (proc.stderr or "")
    for line in text.splitlines():
        if line.startswith("RESULT_JSON:"):
            row = json.loads(line.split(":", 1)[1])
            row["ok"] = proc.returncode == 0
            return row
    print(text[-3000:])
    return {"ok": False}


def _median(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    ok = [r for r in rows if r.get("ok")]
    out: Dict[str, Dict[str, float]] = {}
    for name in ASSETS:
        for key in ("construct", "cold", "warm", "decode"):
            src = "cold_construct" if key == "construct" else key
            vals = [r["assets"][name][src] for r in ok if src in r["assets"].get(name, {})]
            if vals:
                out.setdefault(name, {})[key] = statistics.median(vals)
    return out


def _table(res: Dict[str, Dict[str, float]]) -> List[str]:
    lines = [
        "| Asset | construct | cold first-use | warm | decode (CPU) |",
        "|-------|---------:|---------------:|-----:|-------------:|",
    ]
    for name in ASSETS:
        r = res.get(name, {})

        def f(k: str) -> str:
            return "—" if k not in r else f"{r[k]:.2f}"

        lines.append(f"| {name} | {f('construct')} | **{f('cold')}** | {f('warm')} | {f('decode')} |")
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--launches", type=int, default=3)
    p.add_argument("--pulse", action="store_true", help=f"protocol {PROTOCOL}: 3 launches, append assets.md")
    p.add_argument("--no-append", action="store_true")
    args = p.parse_args()
    if os.environ.get("ASSETS_WORKER"):
        _worker()
        return
    n = 3 if args.pulse else max(1, args.launches)
    rows = []
    for i in range(n):
        r = _launch()
        print(f"launch {i + 1}/{n}: ok={r.get('ok')} steady={r.get('steady_work_ms', float('nan')):.3f} ms", flush=True)
        rows.append(r)
    res = _median(rows)
    cold_sum = sum(v.get("cold", 0.0) for v in res.values())
    warm_sum = sum(v.get("warm", 0.0) for v in res.values())
    worst = max(res.items(), key=lambda kv: kv[1].get("cold", 0.0)) if res else ("—", {})
    print("=" * 60)
    print(f"asset first-use (ms of extra frame work, median of {n})")
    for line in _table(res):
        print(line)
    print(f"cold Σ {cold_sum:.1f} ms · worst {worst[0]} {worst[1].get('cold', float('nan')):.1f} ms · warm Σ {warm_sum:.1f} ms")
    print("=" * 60)
    if args.pulse:
        _pulse(res, cold_sum, warm_sum, worst, args.no_append)
    print("RESULT_JSON: " + json.dumps({"cold_sum_ms": cold_sum, "warm_sum_ms": warm_sum, "assets": res}))


def _pulse(res, cold_sum, warm_sum, worst, no_append: bool) -> None:
    from fingerprint import script_hashes
    from pulse import (
        append_pulse, autodiff, latest_scena_fingerprint, now_meta,
        parse_leading_float, parse_summary_table, print_autodiff_banner,
    )
    log_path = Path(_BENCH) / "assets.md"
    meta = now_meta()
    hashes = script_hashes(("perf_assets.py", "frame_probe.py"), Path(_BENCH))
    row = (
        f"| {meta['date']} | `{PROTOCOL}` | {meta['host_s']} | {cold_sum:.1f} | "
        f"{worst[0]} {worst[1].get('cold', float('nan')):.1f} | {warm_sum:.1f} | |"
    )
    hash_s = " · ".join(f"`{k}` `{v}`" for k, v in hashes.items())
    section = "\n".join([
        f"### {meta['date']} — {PROTOCOL}",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `{PROTOCOL}` |",
        f"| Host | {meta['host_s']} |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        "| Launches | 3 fresh processes (median per asset) |",
        f"| Scripts | {hash_s} |",
        "",
        *_table(res),
        "",
    ])
    prev_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    prev = None
    for cells in parse_summary_table(prev_text):
        if len(cells) >= 6 and cells[1].strip().strip("`") == PROTOCOL:
            prev = {"cold_sum_ms": parse_leading_float(cells[3]),
                    "warm_sum_ms": parse_leading_float(cells[5])}
            break
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same = (prev_fp == meta["scena_fingerprint"]) if prev_fp else None
    print_autodiff_banner(
        autodiff({"cold_sum_ms": cold_sum}, {k: v for k, v in (prev or {}).items() if v is not None},
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


if __name__ == "__main__":
    main()
