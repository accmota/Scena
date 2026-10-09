"""Background / camera / parallax isolate — fields, wallpaper, depth layers.

The camera pans, zooms and rotates every frame (deterministic from clock time),
so every field re-samples its parallax and every layer rebuilds its partial
camera matrix. Collision, sprites and SpatialFx stay out.

Modes
-----
  sky        SkyGradient + Stars + Stardust + Clouds (procedural fields) → bg_ms
  wallpaper  Wallpaper image (cover, pan/zoom response)                  → bg_ms
  parallax   3 parallax layers (far/mid/near) of shapes + world shapes   → draw_ms
  mix        sky + parallax (a typical side-scroller / shooter). Regular pulse.

Usage
-----
    python scripts/bench/perf_background.py                      # interactive, mix
    python scripts/bench/perf_background.py --bench --mode sky
    python scripts/bench/perf_background.py --pulse              # protocol bg-1, append background.md
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_MODES = ("sky", "wallpaper", "parallax", "mix")
PROTOCOL = "bg-1"

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--mode", choices=_MODES, default="mix")
_parser.add_argument("--bench", action="store_true")
_parser.add_argument("--duration", type=float, default=2.0)
_parser.add_argument("--warmup", type=float, default=0.5)
_parser.add_argument("--repeats", type=int, default=1)
_parser.add_argument("--quality", default="high", choices=("low", "medium", "high", "max"))
_parser.add_argument("--json", dest="json_path", default=None)
_parser.add_argument("--pulse", action="store_true",
                     help=f"protocol {PROTOCOL}: every mode, median of 3; append background.md")
_parser.add_argument("--no-append", action="store_true")
args, _ = _parser.parse_known_args()
args.repeats = max(1, int(args.repeats))

_BENCH = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.environ.get("BG_WORKER")
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from harness import (  # noqa: E402
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
    print_phase_report,
    write_json,
)
from fingerprint import REPO_ROOT, script_hashes  # noqa: E402
from pulse import (  # noqa: E402
    append_pulse,
    autodiff,
    latest_scena_fingerprint,
    now_meta,
    parse_leading_float,
    parse_summary_table,
    print_autodiff_banner,
)

_KEYS = ("fps", "work_ms", "bg_ms", "draw_ms", "tick_ms", "submit_ms")


def _run_worker(mode: str) -> Dict[str, Any]:
    env = dict(os.environ)
    env["BG_WORKER"] = "1"
    cmd = [
        sys.executable, os.path.abspath(__file__), "--bench", "--mode", mode,
        "--duration", str(args.duration), "--warmup", str(args.warmup),
        "--quality", args.quality,
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=str(REPO_ROOT))
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out, end="" if out.endswith("\n") else "\n")
    for line in out.splitlines():
        if line.startswith("RESULT_JSON:"):
            row = json.loads(line.split(":", 1)[1])
            row["ok"] = proc.returncode == 0
            return row
    return {"ok": False, "mode": mode}


def _median(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if r.get("ok") and "work_ms" in r]
    if not ok:
        return {"ok": False}
    out: Dict[str, Any] = {"ok": True, "repeats": len(ok), "mode": ok[0].get("mode")}
    for k in _KEYS:
        vals = [float(r[k]) for r in ok if r.get(k) is not None]
        if vals:
            med = statistics.median(vals)
            out[k] = med
            out[f"{k}_spread_pct"] = 0.0 if med == 0 else 100.0 * (max(vals) - min(vals)) / abs(med)
    return out


def _run_pulse() -> None:
    log_path = Path(_BENCH) / "background.md"
    meta = now_meta()
    hashes = script_hashes(("perf_background.py", "harness.py"), Path(_BENCH))
    print(f"=== background pulse  modes={_MODES} repeats=3  stage={meta['scena_fingerprint']} ===", flush=True)
    res = {m: _median([_run_worker(m) for _ in range(3)]) for m in _MODES}
    mix = res["mix"]

    def w(m: str) -> str:
        v = res[m].get("work_ms")
        return "—" if v is None else f"{v:.3f}"

    row = (
        f"| {meta['date']} | `{PROTOCOL}` | {meta['host_s']} | "
        f"{w('mix')} (bg {mix.get('bg_ms', float('nan')):.2f} · d {mix.get('draw_ms', float('nan')):.2f}) | "
        f"{w('sky')} | {w('wallpaper')} | {w('parallax')} | |"
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
        "| Repeats | 3 per mode (median) |",
        f"| Scripts | {hash_s} |",
        "",
        "| Mode | work_ms | spread | bg_ms | draw_ms | submit_ms | FPS |",
        "|------|-------:|-------:|------:|--------:|----------:|----:|",
    ]
    for m in _MODES:
        r = res[m]
        if not r.get("ok"):
            lines.append(f"| {m} | fail | | | | | |")
            continue
        lines.append(
            f"| {m} | **{r['work_ms']:.3f}** | ±{r.get('work_ms_spread_pct', 0):.0f}% | "
            f"{r.get('bg_ms', 0):.3f} | {r.get('draw_ms', 0):.3f} | {r.get('submit_ms', 0):.3f} | {r.get('fps', 0):.0f} |"
        )
    lines.append("")
    section = "\n".join(lines)

    prev_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    prev = None
    for cells in parse_summary_table(prev_text):
        if len(cells) >= 7 and cells[1].strip().strip("`") == PROTOCOL:
            prev = {
                "mix_work_ms": parse_leading_float(cells[3]),
                "sky_work_ms": parse_leading_float(cells[4]),
                "wallpaper_work_ms": parse_leading_float(cells[5]),
                "parallax_work_ms": parse_leading_float(cells[6]),
            }
            break
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same = (prev_fp == meta["scena_fingerprint"]) if prev_fp else None
    new = {f"{m}_work_ms": res[m]["work_ms"] for m in _MODES if res[m].get("work_ms") is not None}
    print_autodiff_banner(
        autodiff(new, {k: v for k, v in (prev or {}).items() if v is not None},
                 same_scena=same, prev_label=f"last {PROTOCOL} row"),
        same_scena=same,
    )
    print(section)
    if not args.no_append:
        append_pulse(log_path, row, section)
        print(f"appended {log_path}")
        try:
            from dashboard import refresh as refresh_dashboard
            refresh_dashboard()
        except Exception as exc:
            print(f"(dashboard refresh skipped: {exc})")


if not _WORKER and (args.pulse or args.repeats > 1):
    if args.pulse:
        _run_pulse()
        sys.exit(0)
    bundle = _median([_run_worker(args.mode) for _ in range(args.repeats)])
    print("=" * 60)
    print(f"background {args.mode}  repeats={bundle.get('repeats', 0)}")
    for k in _KEYS:
        if k in bundle:
            print(f"{k:10s} {bundle[k]:.3f}")
    print("=" * 60)
    sys.exit(0)


from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework, set_leak_detector  # noqa: E402
from scena.process import set_watchdog  # noqa: E402

W, H = 1000, 700
init(width=W, height=H, title=f"Bench — background {args.mode}")
canvas.set_origin("center")
set_fx_auto(False)
canvas.fx_quality = args.quality
set_watchdog(False)
set_leak_detector(False)
if args.bench:
    canvas.framerate = "max"

WALLPAPER = str(REPO_ROOT / "examples" / "media" / "images" / "bg1.jpeg")


def _sky() -> None:
    SkyGradient("night")
    Stars(pan_response=0.18, density=0.85, amount=0.9, twinkle=0.35, scroll=(0.0, -18.0))
    Stardust(pan_response=0.45, amount=0.55)
    Clouds(pan_response=0.08, amount=0.35)


def _wallpaper() -> None:
    Wallpaper(WALLPAPER, fit="cover", pan_response=0.2, zoom_response=0.4)


def _parallax() -> None:
    canvas.layers.create("far", below="default", pan_response=0.15, zoom_response=0.1)
    canvas.layers.create("mid", below="default", pan_response=0.45, zoom_response=0.35)
    canvas.layers.create("near", below="default", pan_response=0.75, zoom_response=0.6)
    Polygon(
        points=[(-700, -50), (-400, 180), (-100, -20), (200, 220), (500, -40), (700, -80)],
        layer="far",
    ).set_color(Color(0.15, 0.22, 0.38))
    for i, x in enumerate(range(-900, 901, 90)):
        h = 40 + (i % 3) * 18
        Circle(center=(x, 20 + h * 0.3), radius=h * 0.45, layer="mid").set_color(
            Color(0.12, 0.40 + (i % 4) * 0.03, 0.18))
        Rect(center=(x, -10), width=14, height=h * 0.5, layer="mid").set_color(Color(0.25, 0.15, 0.08))
    for i, x in enumerate(range(-1000, 1001, 110)):
        RegularPolygon(center=(x, -60 - (i % 2) * 20), radius=34, n=6, layer="near").set_color(
            Color(0.10, 0.52, 0.22))
    for i in range(24):
        Circle(center=(-600 + i * 52, -200 + (i % 5) * 30), radius=10).set_color("gold")


if args.mode == "sky":
    canvas.background = (0.02, 0.02, 0.05)
    _sky()
elif args.mode == "wallpaper":
    _wallpaper()
elif args.mode == "parallax":
    canvas.background = (0.45, 0.65, 0.85)
    _parallax()
else:
    _sky()
    _parallax()


def update(dt):
    t = clock.time
    canvas.pan_to(160.0 * math.sin(t * 0.85), 60.0 * math.cos(t * 0.7))
    canvas.zoom_to(1.0 + 0.2 * math.sin(t * 1.05))
    canvas.rotate_to(6.0 * math.sin(t * 0.55))


if args.bench:
    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    install_phase_run(fw, duration=args.duration, warmup=args.warmup, stats=stats)
    run()
    print_phase_report(f"background {args.mode} — phase timing", stats)
    avg = average_phase_stats(stats)
    payload = {"ok": True, "mode": args.mode, **{k: avg[k] for k in _KEYS}, "frames": avg["frames"]}
    print("RESULT_JSON: " + json.dumps(payload))
    if args.json_path:
        payload["phases"] = avg
        write_json(args.json_path, payload)
else:
    run()
