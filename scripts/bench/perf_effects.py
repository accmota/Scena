"""
perf_effects.py -- Scena effects performance benchmark.

Measures in-app FPS for shape filters and canvas-wide post FX across
FxQuality levels. Use before/after framework changes to catch regressions.

Usage:
    python scripts/perf_effects.py
    python scripts/perf_effects.py --mode baseline --duration 3
    python scripts/perf_effects.py --mode glow --quality high --duration 3
    python scripts/perf_effects.py --mode post --duration 3
    python scripts/perf_effects.py --suite --duration 2   # all modes × qualities
"""
from __future__ import annotations

import argparse
import math
import sys
import time

from perf_common import print_report, summarize

_MODES = (
    "baseline",   # solid shapes, no filters, no post
    "glow",       # GlowFilter on all shapes (batched)
    "glow_nobatch",
    "post",       # vignette + grain + bloom (canvas.effects when available)
    "all",        # glow + post
)

_QUALITY = ("low", "medium", "high", "max")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--mode", choices=_MODES, default="baseline")
parser.add_argument("--quality", choices=_QUALITY, default="high")
parser.add_argument("--n", type=int, default=80, help="number of shapes")
parser.add_argument("--duration", type=float, default=3.0)
parser.add_argument("--warmup", type=float, default=0.5)
parser.add_argument("--suite", action="store_true",
                    help="run a matrix of modes × qualities and print a table")
parser.add_argument("--width", type=int, default=1000)
parser.add_argument("--height", type=int, default=700)
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Suite mode: spawn subprocesses so each config gets a clean process
# ---------------------------------------------------------------------------
if args.suite:
    import subprocess
    import os

    script = os.path.abspath(__file__)
    rows = []
    configs = [
        ("baseline", "high"),
        ("glow", "high"),
        ("glow_nobatch", "high"),
        ("post", "high"),
        ("all", "high"),
        ("all", "low"),
        ("all", "max"),
    ]
    print(f"=== effects suite  n={args.n}  duration={args.duration}s ===")
    for mode, quality in configs:
        cmd = [
            sys.executable, script,
            "--mode", mode, "--quality", quality,
            "--n", str(args.n),
            "--duration", str(args.duration),
            "--warmup", str(args.warmup),
            "--width", str(args.width),
            "--height", str(args.height),
        ]
        print(f"\n>> {' '.join(cmd[-10:])}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        print(out)
        # Parse "Average FPS:" line from print_report
        fps = None
        for line in out.splitlines():
            if "Average FPS:" in line:
                try:
                    fps = float(line.split(":")[-1].strip())
                except ValueError:
                    pass
        rows.append((mode, quality, fps))
    print("\n=== suite summary ===")
    print(f"{'mode':<16} {'quality':<10} {'fps':>8}")
    print("-" * 36)
    for mode, quality, fps in rows:
        fps_s = f"{fps:.1f}" if fps is not None else "?"
        print(f"{mode:<16} {quality:<10} {fps_s:>8}")
    print("=" * 36)
    sys.exit(0)

# ---------------------------------------------------------------------------
# Single-config run
# ---------------------------------------------------------------------------
from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402

W, H = args.width, args.height
init(width=W, height=H, title=f"FX bench {args.mode}/{args.quality}")
_fw = ScenaFramework.get_instance()
_fw._compute_window_size = lambda dw, dh, wf: (int(dw), int(dh))

canvas.background = (0.05, 0.06, 0.10, 1)
set_fx_auto(False)
canvas.fx_quality = args.quality
use_batch = args.mode != "glow_nobatch"
canvas.batch_shared_filters = use_batch

_GLOW = GlowFilter(radius=8, sigma=5, color=(0.5, 0.85, 1.0, 0.9))

movers = []
cols = max(1, int(math.sqrt(args.n * W / H)))
rows = max(1, math.ceil(args.n / cols))
for i in range(args.n):
    c = i % cols
    r = i // cols
    x = 60 + c * ((W - 120) / max(cols - 1, 1))
    y = 60 + r * ((H - 120) / max(rows - 1, 1))
    shp = Circle(center=(x, y), radius=14 + (i % 5)).set_color(
        ("crimson", "gold", "cyan", "lime", "magenta", "orange")[i % 6]
    )
    if args.mode in ("glow", "glow_nobatch", "all"):
        # Shared instance → batchable; unique instance when nobatch isolation
        if args.mode == "glow_nobatch":
            shp.fill_filter = GlowFilter(radius=8, sigma=5, color=(0.5, 0.85, 1.0, 0.9))
        else:
            shp.fill_filter = _GLOW
    movers.append({"shape": shp, "hx": x, "hy": y, "spin": 40 + (i % 7) * 5})

# Canvas post FX — prefer new API when available, else fall back to post_draw stub
_use_effects_api = hasattr(canvas, "effects")
if args.mode in ("post", "all"):
    if _use_effects_api:
        try:
            from scena import Vignette, Grain, Bloom
            canvas.effects.add(Vignette())
            canvas.effects.add(Grain())
            canvas.effects.add(Bloom())
        except ImportError:
            _use_effects_api = False
    if not _use_effects_api:
        # Pre-engine baseline: no canvas post (shape FX only measurable)
        pass

_start_time = None
_warmup_done = False
_bench_start = None
_frame_times = []
_t = 0.0


def _finish():
    label = f"Effects [{args.mode} / {args.quality}]"
    print_report(label, _frame_times, args.n)
    q = canvas.fx_quality
    qname = q.value if q is not None else "?"
    print(f"  post_fx_scale={canvas.post_fx_scale}  shape_fx_scale={canvas.shape_fx_scale}")
    print(f"  batch={use_batch}  effects_api={_use_effects_api}")
    import glfw
    glfw.set_window_should_close(_fw._window, True)


def update(dt):
    global _start_time, _warmup_done, _bench_start, _t
    _t += dt
    now = time.perf_counter()
    if _start_time is None:
        _start_time = now
    elapsed = now - _start_time

    for i, m in enumerate(movers):
        shp = m["shape"]
        ox = 8 * math.sin(_t * 0.8 + i * 0.2)
        oy = 6 * math.cos(_t * 0.6 + i * 0.15)
        shp.move_to(m["hx"] + ox, m["hy"] + oy)
        shp.rotate_by(m["spin"] * dt)

    if not _warmup_done:
        if elapsed >= args.warmup:
            _warmup_done = True
            _bench_start = now
        return

    _frame_times.append(dt)
    if now - _bench_start >= args.duration:
        _finish()


canvas.framerate = "max"
run()
