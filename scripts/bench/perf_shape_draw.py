"""Isolate Scena shape-draw cost (kind × visual × static/move × quality).

Not a product scene. Used to rank general draw-walk ideas (solo Recipes vs
batched compiled looks, static geometry vs motion, Line vs Circle).

Usage
-----
    python scripts/bench/perf_shape_draw.py --cell line_laser_static
    python scripts/bench/perf_shape_draw.py --suite
    python scripts/bench/perf_shape_draw.py --suite --no-sweep-quality
    python scripts/bench/perf_shape_draw.py --micro
    python scripts/bench/perf_shape_draw.py --cell line_laser_static --profile
"""
from __future__ import annotations

import argparse
import cProfile
import json
import math
import os
import pstats
import subprocess
import sys
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (
    WIDTH,
    HEIGHT,
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
    print_phase_report,
    write_json,
)

# (id, kind, visual, motion, n)
# visual: plain | laser | halo | halo_soft | electric | cheapglow | glow |
#         neon | ink | rim | bolt
CELLS = (
    ("circle_plain_static", "circle", "plain", "static", 80),
    ("circle_plain_move", "circle", "plain", "move", 80),
    ("line_plain_static", "line", "plain", "static", 80),
    ("line_plain_move", "line", "plain", "move", 80),
    ("line_laser_static", "line", "laser", "static", 80),
    ("line_laser_move", "line", "laser", "move", 80),
    ("circle_laser_static", "circle", "laser", "static", 80),
    ("circle_halo_static", "circle", "halo", "static", 80),
    ("circle_halosoft_static", "circle", "halo_soft", "static", 80),
    ("circle_ef_static", "circle", "electric", "static", 80),
    ("line_ef_static", "line", "electric", "static", 80),
    ("circle_cheapglow_static", "circle", "cheapglow", "static", 80),
    ("circle_glow_static", "circle", "glow", "static", 80),
    ("circle_neon_static", "circle", "neon", "static", 80),
    ("circle_ink_static", "circle", "ink", "static", 80),
    ("line_ink_static", "line", "ink", "static", 80),
    ("circle_rim_static", "circle", "rim", "static", 80),
    ("line_rim_static", "line", "rim", "static", 80),
    ("circle_bolt_static", "circle", "bolt", "static", 80),
    ("line_plain_n200", "line", "plain", "static", 200),
    ("line_laser_n200", "line", "laser", "static", 200),
)

# Re-run these at medium + low when --suite (Halo med vs high, lod, GlowRim).
QUALITY_SWEEP_IDS = (
    "circle_plain_static",
    "line_laser_static",
    "circle_halo_static",
    "circle_halosoft_static",
    "circle_ef_static",
    "circle_rim_static",
    "circle_glow_static",
    "circle_cheapglow_static",
    "circle_ink_static",
    "circle_neon_static",
    "circle_bolt_static",
)

_CELL_BY_ID = {row[0]: row for row in CELLS}

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--cell", default="line_laser_static", choices=sorted(_CELL_BY_ID))
parser.add_argument("--suite", action="store_true", help="run all cells in subprocesses")
parser.add_argument(
    "--sweep-quality", action=argparse.BooleanOptionalAction, default=True,
    help="with --suite, also run QUALITY_SWEEP_IDS at medium and low (default on)",
)
parser.add_argument("--micro", action="store_true", help="no-window _stroke_paint / Color microbench")
parser.add_argument("--duration", type=float, default=0.85)
parser.add_argument("--warmup", type=float, default=0.35)
parser.add_argument("--quality", default="high", choices=("low", "medium", "high", "max"))
parser.add_argument("--profile", action="store_true", help="cProfile (tottime + cumulative)")
parser.add_argument("--json", dest="json_path", default=None)
args, _ = parser.parse_known_args()


def _parse_result_json(text: str):
    for line in text.splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line[len("RESULT_JSON:") :])
    return None


def _run_micro() -> None:
    """Time Color/_stroke_paint / Neon tint without a window."""
    import time as _time

    import skia

    from scena.color import Color
    from scena.recipes import Laser, Neon, _clamp01, _color_obj, _vivid_rgb
    from scena.style import BlendMode

    look = Laser("tomato")
    rgba = (0.95, 0.12, 0.10, 0.28)
    muted = (0.35, 0.55, 0.62, 1.0)
    n = 40000
    paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeCap=skia.Paint.Cap.kRound_Cap,
    )

    def _bench(label, fn):
        fn()  # warmup
        t0 = _time.perf_counter()
        fn()
        ms = (_time.perf_counter() - t0) * 1000.0
        print(f"{label:<28} {ms:8.2f} ms  ({n} calls, {ms / n * 1000:.3f} µs)")
        return ms

    def color_obj_loop():
        for _ in range(n):
            _color_obj(rgba)

    def color_ctor_loop():
        for _ in range(n):
            Color(_clamp01(rgba[0]), _clamp01(rgba[1]), _clamp01(rgba[2]), _clamp01(rgba[3]))

    def set_color4f_loop():
        c4 = skia.Color4f(*rgba)
        for _ in range(n):
            paint.setColor4f(c4)

    def set_color4f_rebuild_loop():
        for _ in range(n):
            paint.setColor4f(skia.Color4f(*rgba))

    def stroke_paint_loop():
        for _ in range(n):
            look._stroke_paint(color=rgba, width=4.0, blend=BlendMode.ADD)

    def vivid_miss_loop():
        # Vary blue channel so each call misses the intern (cold path).
        for i in range(n):
            _vivid_rgb((muted[0], muted[1], muted[2] + (i % 97) * 1e-6), 0.55)

    def vivid_hit_loop():
        _vivid_rgb(muted, 0.55)  # seed
        for _ in range(n):
            _vivid_rgb(muted, 0.55)

    def neon_tint_via_color_loop():
        # Diagnostic: old Color.vibrant_version path cost.
        for _ in range(n):
            Color(*muted).vibrant_version(0.55).rgb

    print(f"=== _stroke_paint / Neon tint micro  n={n} ===")
    rows = {
        "color_obj": _bench("_color_obj(tuple)", color_obj_loop),
        "color_ctor": _bench("Color(r,g,b,a)", color_ctor_loop),
        "set_color4f_reuse": _bench("setColor4f(cached)", set_color4f_loop),
        "set_color4f_new": _bench("setColor4f(new Color4f)", set_color4f_rebuild_loop),
        "stroke_paint": _bench("Laser._stroke_paint", stroke_paint_loop),
        "vivid_miss": _bench("_vivid_rgb (miss)", vivid_miss_loop),
        "vivid_hit": _bench("_vivid_rgb (hit)", vivid_hit_loop),
        "vibrant_color": _bench("Color.vibrant_version", neon_tint_via_color_loop),
    }
    # Keep Neon import live so intern wiring is exercised at import time.
    _ = Neon("cyan")
    payload = {"ok": True, "probe": "stroke_paint_micro", "n": n, "ms": rows}
    print("RESULT_JSON: " + json.dumps(payload))
    if args.json_path:
        write_json(args.json_path, payload)


if args.micro:
    _run_micro()
    sys.exit(0)


if args.suite:
    script = os.path.abspath(__file__)
    jobs = [(cell_id, args.quality) for cell_id, *_ in CELLS]
    if args.sweep_quality:
        for q in ("medium", "low"):
            if q == args.quality:
                continue
            for cell_id in QUALITY_SWEEP_IDS:
                jobs.append((cell_id, q))
    rows = []
    print(
        f"=== shape-draw suite  base_quality={args.quality}  "
        f"sweep={args.sweep_quality}  jobs={len(jobs)}  "
        f"duration={args.duration}s warmup={args.warmup}s ==="
    )
    timeout = max(60.0, args.duration + args.warmup + 40.0)
    for cell_id, quality in jobs:
        cmd = [
            sys.executable, script,
            "--cell", cell_id,
            "--duration", str(args.duration),
            "--warmup", str(args.warmup),
            "--quality", str(quality),
        ]
        label = cell_id if quality == args.quality else f"{cell_id}@{quality}"
        print(f"\n>> {label}")
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            print(out[-2000:])
            rows.append({
                "cell": cell_id, "quality": quality, "ok": False,
                "error": f"rc={proc.returncode}",
            })
            continue
        payload = _parse_result_json(out)
        if payload is None:
            print(out[-2000:])
            rows.append({
                "cell": cell_id, "quality": quality, "ok": False,
                "error": "no RESULT_JSON",
            })
            continue
        rows.append(payload)
        print(
            f"   fps={payload['fps']:.1f}  work={payload['work_ms']:.3f}  "
            f"draw={payload['draw_ms']:.3f}  submit={payload['submit_ms']:.3f}  "
            f"tick={payload['tick_ms']:.3f}  flush={payload['flush_ms']:.3f}"
        )

    print("\n=== suite summary ===")
    hdr = (
        f"{'cell':<28} {'q':<7} {'n':>4} {'fps':>8} {'work':>8} "
        f"{'draw':>8} {'submit':>8} {'tick':>7} {'flush':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        if not row.get("ok", True) or "fps" not in row:
            print(f"{row.get('cell', '?'):<28}  FAIL  {row.get('error', '')}")
            continue
        print(
            f"{row['cell']:<28} {row['quality']:<7} {row['n']:>4} "
            f"{row['fps']:8.1f} {row['work_ms']:8.3f} {row['draw_ms']:8.3f} "
            f"{row['submit_ms']:8.3f} {row['tick_ms']:7.3f} {row['flush_ms']:7.3f}"
        )
    print("=" * len(hdr))
    bundle = {
        "ok": True,
        "probe": "shape_draw_suite",
        "quality": args.quality,
        "sweep_quality": args.sweep_quality,
        "duration": args.duration,
        "warmup": args.warmup,
        "rows": rows,
    }
    print("RESULT_JSON: " + json.dumps(bundle))
    if args.json_path:
        write_json(args.json_path, bundle)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Single cell
# ---------------------------------------------------------------------------
from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402

cell_id, kind, visual, motion, n = _CELL_BY_ID[args.cell]

init(width=WIDTH, height=HEIGHT, title=f"shape-draw {cell_id}")
fw = ScenaFramework.get_instance()
canvas.background = (0.08, 0.08, 0.10, 1)
set_fx_auto(False)
canvas.fx_quality = args.quality
set_defaults(line=None)

cols = max(1, int(math.ceil(math.sqrt(n))))
rows_n = max(1, int(math.ceil(n / cols)))
gap_x = WIDTH / (cols + 1)
gap_y = HEIGHT / (rows_n + 1)
homes = []
shapes = []
for i in range(n):
    c = i % cols
    r = i // cols
    x = gap_x * (c + 1)
    y = gap_y * (r + 1)
    homes.append((x, y))
    if kind == "line":
        shp = Line(p1=(x - 22, y - 10), p2=(x + 22, y + 10))
        shp.line_width = 2.5
    else:
        shp = Circle(center=(x, y), radius=14)
    def _plain_body():
        if kind == "line":
            shp.set_color("white")
        else:
            shp.fill = (0.82, 0.86, 0.92, 1.0)

    if visual == "plain":
        _plain_body()
    elif visual == "laser":
        shp.visual = Laser("tomato")
    elif visual == "halo":
        shp.visual = Halo("cyan")
    elif visual == "halo_soft":
        shp.visual = Halo("cyan", style="soft")
    elif visual == "electric":
        shp.visual = ElectricField("yellow")
    elif visual == "cheapglow":
        _plain_body()
        shp.glow = CheapGlow(color="tomato", radius=8)
    elif visual == "glow":
        _plain_body()
        shp.glow = Glow(color="gold", radius=12, sigma=6)
    elif visual == "neon":
        shp.visual = Neon("magenta")
    elif visual == "ink":
        _plain_body()
        shp.visual = Ink("black")
    elif visual == "rim":
        shp.visual = Rim("cyan")
    elif visual == "bolt":
        shp.visual = Bolt("deepskyblue")
    else:
        raise ValueError(visual)
    shapes.append(shp)

canvas.framerate = "max"


def update(dt):
    if motion != "move":
        return
    t = clock.time
    for i, shp in enumerate(shapes):
        hx, hy = homes[i]
        ox = 10.0 * math.sin(t * 2.1 + i * 0.17)
        oy = 10.0 * math.cos(t * 1.7 + i * 0.13)
        shp.move_to(hx + ox, hy + oy)


stats = empty_phase_stats()
install_phase_run(fw, duration=args.duration, warmup=args.warmup, stats=stats)

if args.profile:
    pr = cProfile.Profile()
    pr.enable()
    run()
    pr.disable()
else:
    run()

print_phase_report(f"shape-draw {cell_id}", stats)
avg = average_phase_stats(stats)
payload = {
    "ok": True,
    "probe": "shape_draw",
    "cell": cell_id,
    "kind": kind,
    "visual": visual,
    "motion": motion,
    "n": n,
    "quality": args.quality,
    "fps": avg["fps"],
    "work_ms": avg["work_ms"],
    "tick_ms": avg["tick_ms"],
    "coll_ms": avg["coll_ms"],
    "flush_ms": avg["flush_ms"],
    "draw_ms": avg["draw_ms"],
    "submit_ms": avg["submit_ms"],
    "present_ms": avg["present_ms"],
    "frames": avg["frames"],
}
print("RESULT_JSON: " + json.dumps(payload))
if args.json_path:
    payload["phases"] = avg
    write_json(args.json_path, payload)

if args.profile:
    buf = StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("tottime").print_stats(28)
    print("--- tottime ---")
    print(buf.getvalue())
    buf2 = StringIO()
    pstats.Stats(pr, stream=buf2).sort_stats("cumulative").print_stats(22)
    print("--- cumulative ---")
    print(buf2.getvalue())
