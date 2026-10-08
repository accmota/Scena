"""SpatialFx density bench — tick CPU vs draw-record CPU vs GPU submit.

Spawns a grid of *one* SpatialFx kind at a time (many instances), measures
per-frame phases with VSync off, quality=high:

  tick_ms   — ``tick_all_spatial_fx`` (particle simulation, pure CPU)
  draw_ms   — sum of each emitter ``draw()`` (Python + Skia command recording)
  submit_ms — ``flushAndSubmit`` (GPU execute + wait on queued work)
  work_ms   — frame start → after submit (≈ Auto FX work_ms)

Usage:
    python scripts/perf_spatial_fx.py
    python scripts/perf_spatial_fx.py --n 24 --duration 0.9
    python scripts/perf_spatial_fx.py --effect plume --n 36 --json /tmp/s.json
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--n", type=int, default=24, help="emitters of one kind (grid)")
parser.add_argument("--duration", type=float, default=0.85)
parser.add_argument("--warmup", type=float, default=0.35)
parser.add_argument("--width", type=int, default=1000)
parser.add_argument("--height", type=int, default=700)
parser.add_argument("--quality", default="high")
parser.add_argument("--effect", default=None, help="single key; omit for all")
parser.add_argument("--json", dest="json_path", default=None)
parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--effect-key", default="baseline", help=argparse.SUPPRESS)
args = parser.parse_args()

EFFECTS = [
    ("baseline", "—"),
    ("campfire", "Fire"),
    ("campfire_soft", "Fire soft"),
    ("plume", "Fire plume"),
    ("tongues", "Fire tongues"),
    ("embers", "Fire embers"),
    ("sun", "Sunburst"),
    ("star", "Starburst"),
    ("rain", "Rain"),
    ("jet", "Jet"),
    ("sparks", "Sparks"),
]


def _grid(n: int, w: int, h: int, margin: float = 70.0):
    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = max(1, int(math.ceil(n / cols)))
    xs = [margin + (w - 2 * margin) * (i + 0.5) / cols for i in range(cols)]
    ys = [margin + (h - 2 * margin) * (j + 0.5) / rows for j in range(rows)]
    out = []
    for j in range(rows):
        for i in range(cols):
            if len(out) >= n:
                return out
            out.append((xs[i], ys[j]))
    return out


if args.worker:
    from scena import *  # noqa: E402
    from scena import spatial_fx as sfx_mod
    from scena.orchestration import ScenaFramework
    import glfw

    key = args.effect_key
    W, H = args.width, args.height
    n_emit = max(0, int(args.n))

    init(width=W, height=H, title=f"spatial_fx bench {key}")
    fw = ScenaFramework.get_instance()
    fw._compute_window_size = (
        lambda design_w, design_h, window_scale: (int(design_w), int(design_h))
    )
    canvas.background = (0.06, 0.07, 0.1, 1)
    set_fx_auto(False)
    canvas.fx_quality = args.quality
    canvas.framerate = "max"

    emitters = []
    if key != "baseline":
        centers = _grid(n_emit, W, H)
        r = 28.0
        cols = max(1, int(math.ceil(math.sqrt(n_emit))))
        for i, (x, y) in enumerate(centers):
            ctor = {
                "campfire": lambda **k: Fire(**k),
                "campfire_soft": lambda **k: Fire(style="soft", **k),
                "plume": lambda **k: Fire(style="plume", **k),
                "tongues": lambda **k: Fire(style="tongues", **k),
                "embers": lambda **k: Fire(style="embers", **k),
                "sun": Sunburst,
                "star": Starburst,
                "rain": Rain,
                "jet": Jet,
                "sparks": Sparks,
            }.get(key)
            if ctor is None:
                print(json.dumps({"error": f"unknown effect {key}"}), flush=True)
                sys.exit(1)
            if key == "rain":
                pw = min(160.0, (W - 80) / cols)
                ph = min(140.0, (H - 80) / max(1, int(math.ceil(n_emit / cols))))
                emitters.append(
                    ctor(center=(x, y), width=pw, height=ph, amount=0.75)
                )
            elif key == "jet":
                emitters.append(
                    ctor(origin=(x, y), angle=90 + (i % 4) * 15, length=70, width=12)
                )
            elif key == "sparks":
                emitters.append(ctor(center=(x, y), radius=r, rate=50))
            elif key in ("plume", "tongues"):
                emitters.append(ctor(center=(x, y), width=r))
            elif key == "embers":
                emitters.append(ctor(center=(x, y), width=r * 0.9))
            elif key == "sun":
                emitters.append(ctor(center=(x, y), radius=r * 1.1))
            else:
                emitters.append(ctor(center=(x, y), radius=r))

    t_tick = 0.0
    t_draw = 0.0
    t_submit = 0.0
    work_samples = []
    n_frames = 0
    n_parts_last = 0
    recording = False
    frame_t0 = [None]

    _orig_tick = sfx_mod.tick_all_spatial_fx

    def _tick_wrapped(now=None):
        global t_tick
        t0 = time.perf_counter()
        _orig_tick(now)
        if recording:
            t_tick += time.perf_counter() - t0

    sfx_mod.tick_all_spatial_fx = _tick_wrapped

    for fx in emitters:
        _draw = fx.draw

        def _make(orig):
            def wrapped(c):
                global t_draw
                t0 = time.perf_counter()
                orig(c)
                if recording:
                    t_draw += time.perf_counter() - t0

            return wrapped

        fx.draw = _make(_draw)

    _orig_clock_tick = fw.clock._tick

    def _clock_tick(now, *a, **kw):
        frame_t0[0] = time.perf_counter()
        return _orig_clock_tick(now, *a, **kw)

    fw.clock._tick = _clock_tick

    _hooked = [False]

    def _ensure_submit_hook():
        if _hooked[0]:
            return
        surf = getattr(fw, "_drawing_surface", None)
        if surf is None:
            return
        real = surf

        def combined(*a, **kw):
            global t_submit, n_frames
            t_sub0 = time.perf_counter()
            r = real.flushAndSubmit(*a, **kw)
            t_sub1 = time.perf_counter()
            if recording:
                t_submit += t_sub1 - t_sub0
                if frame_t0[0] is not None:
                    work_samples.append(t_sub1 - frame_t0[0])
                    n_frames += 1
            return r

        class _Surf:
            def __init__(self, real_s):
                object.__setattr__(self, "_real", real_s)

            def flushAndSubmit(self, *a, **kw):
                return combined(*a, **kw)

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_real"), name)

        fw._drawing_surface = _Surf(real)
        _hooked[0] = True

    _run_t0 = None
    _warmup_done = False
    _bench_t0 = None

    def update(dt):
        global recording, _run_t0, _warmup_done, _bench_t0, n_parts_last
        global t_tick, t_draw, t_submit, n_frames

        _ensure_submit_hook()
        now = time.perf_counter()
        if _run_t0 is None:
            _run_t0 = now
        elapsed = now - _run_t0

        if not _warmup_done:
            if elapsed >= args.warmup:
                _warmup_done = True
                _bench_t0 = now
                recording = True
                t_tick = t_draw = t_submit = 0.0
                work_samples.clear()
                n_frames = 0
            return

        parts = 0
        for e in emitters:
            bank = getattr(e, "_bank", None)
            if bank is not None:
                parts += int(getattr(bank, "n", 0))
        n_parts_last = parts

        if now - _bench_t0 >= args.duration:
            recording = False
            nf = max(n_frames, 1)
            work_ms = (
                (sum(work_samples) / len(work_samples)) * 1000.0
                if work_samples
                else 0.0
            )
            tick_ms = (t_tick / nf) * 1000.0
            draw_ms = (t_draw / nf) * 1000.0
            submit_ms = (t_submit / nf) * 1000.0
            cpu_ms = tick_ms + draw_ms
            result = {
                "key": key,
                "n_emitters": len(emitters),
                "quality": args.quality,
                "frames": n_frames,
                "parts_last": n_parts_last,
                "tick_ms": tick_ms,
                "draw_ms": draw_ms,
                "submit_ms": submit_ms,
                "work_ms": work_ms,
                "cpu_ms": cpu_ms,
                "gpu_ms": submit_ms,
                "rest_ms": max(0.0, work_ms - tick_ms - draw_ms - submit_ms),
                "cpu_frac": cpu_ms / work_ms if work_ms > 1e-6 else 0.0,
                "gpu_frac": submit_ms / work_ms if work_ms > 1e-6 else 0.0,
            }
            print("RESULT_JSON:" + json.dumps(result), flush=True)
            glfw.set_window_should_close(fw._window, True)

    run()
    sys.exit(0)


def _run_worker(effect_key: str) -> dict:
    cmd = [
        sys.executable,
        __file__,
        "--worker",
        "--effect-key",
        effect_key,
        "--n",
        str(args.n),
        "--duration",
        str(args.duration),
        "--warmup",
        str(args.warmup),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--quality",
        str(args.quality),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(45.0, args.duration + args.warmup + 25.0),
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for line in out.splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line[len("RESULT_JSON:") :])
    return {
        "key": effect_key,
        "error": f"worker failed rc={proc.returncode}",
        "tail": out[-1200:],
    }


def _bottleneck(r: dict) -> str:
    if r.get("key") == "baseline":
        return "—"
    cpu, gpu = r["cpu_ms"], r["gpu_ms"]
    if cpu >= gpu * 1.4:
        return "CPU"
    if gpu >= cpu * 1.4:
        return "GPU"
    return "mixed"


def main():
    keys = [k for k, _ in EFFECTS]
    if args.effect:
        keys = [args.effect]
        if keys[0] not in dict(EFFECTS):
            print(f"unknown effect {keys[0]!r}; choose from {[k for k, _ in EFFECTS]}")
            sys.exit(2)

    print(
        f"SpatialFx CPU/GPU bench  n={args.n}  quality={args.quality}  "
        f"window={args.width}x{args.height}  "
        f"warmup={args.warmup}s  measure={args.duration}s"
    )
    print(
        f"{'effect':<16} {'N':>3} {'parts':>5} "
        f"{'work':>7} {'tick':>7} {'draw':>7} {'submit':>7} "
        f"{'cpu%':>5} {'gpu%':>5}  bott  +base"
    )
    print("-" * 92)

    rows = []
    baseline_work = None
    for key in keys:
        row = _run_worker(key)
        rows.append(row)
        if row.get("error"):
            print(f"{key:<16} ERROR {row.get('error')}")
            print((row.get("tail") or "")[-400:])
            continue
        if key == "baseline":
            baseline_work = row["work_ms"]
        extra = (
            row["work_ms"] - baseline_work
            if baseline_work is not None and key != "baseline"
            else 0.0
        )
        bott = _bottleneck(row)
        print(
            f"{key:<16} {row['n_emitters']:>3} {row['parts_last']:>5} "
            f"{row['work_ms']:>6.2f} {row['tick_ms']:>6.2f} "
            f"{row['draw_ms']:>6.2f} {row['submit_ms']:>6.2f} "
            f"{100 * row['cpu_frac']:>4.0f}% {100 * row['gpu_frac']:>4.0f}%  "
            f"{bott:<5} "
            + (f"+{extra:.2f}" if key != "baseline" else "—")
        )

    ranked = sorted(
        [
            r
            for r in rows
            if r.get("key") != "baseline" and "work_ms" in r and not r.get("error")
        ],
        key=lambda r: -r["work_ms"],
    )
    print()
    print("Worst offenders (total work_ms):")
    for i, r in enumerate(ranked, 1):
        bott = _bottleneck(r)
        print(
            f"  {i:2}. {r['key']:<14}  work={r['work_ms']:.2f}ms  "
            f"tick={r['tick_ms']:.2f}  draw={r['draw_ms']:.2f}  "
            f"submit={r['submit_ms']:.2f}  → {bott}"
        )

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "n": args.n,
                    "quality": args.quality,
                    "duration": args.duration,
                    "warmup": args.warmup,
                    "rows": rows,
                },
                f,
                indent=2,
            )
        print(f"\nJSON → {args.json_path}")


if __name__ == "__main__":
    main()
