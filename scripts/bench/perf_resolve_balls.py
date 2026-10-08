"""Mutual ``resolve()`` isolate — bouncing circles, walls, one spinning bar.

Frozen pulse cell is ``n=40`` (see ``run_resolve.py`` / ``resolve.md``).
Ladder and peel flags are for when that cell moves.

Usage
-----
    python scripts/bench/perf_resolve_balls.py --bench --n 40 --duration 3
    python scripts/bench/perf_resolve_balls.py --bench --n 40 --resolve-off
    python scripts/bench/perf_resolve_balls.py --bench --n 40 --no-ball-ball
    python scripts/bench/perf_resolve_balls.py --bench --ladder 10,20,40,80
"""
from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import sys
from io import StringIO
from random import Random

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--n", type=int, default=40, help="ball count (default 40)")
_parser.add_argument("--size", type=int, default=12, help="ball radius (default 12)")
_parser.add_argument("--bench", action="store_true",
                    help="uncapped FPS, phase-time, then exit")
_parser.add_argument("--duration", type=float, default=3.0,
                    help="measured seconds when --bench (default 3)")
_parser.add_argument("--warmup", type=float, default=0.5,
                    help="warmup seconds excluded from stats (default 0.5)")
_parser.add_argument("--profile", action="store_true",
                    help="with --bench, also print cProfile top functions")
_parser.add_argument("--seed", type=int, default=42)
_parser.add_argument("--resolve-off", action="store_true",
                    help="skip standing resolve (detection stays on)")
_parser.add_argument("--no-spin", action="store_true",
                    help="do not rotate the centre bar (closed-form TOI only)")
_parser.add_argument("--no-ball-ball", action="store_true",
                    help="do not register resolve(\"ball\", \"ball\")")
_parser.add_argument("--ladder", default=None,
                    help="comma-separated ball counts; runs --bench once each")
_parser.add_argument("--json", dest="json_path", default=None,
                    help="write phase-timing JSON (with --bench)")
args, _ = _parser.parse_known_args()

if args.ladder:
    here = os.path.abspath(__file__)
    counts = [p.strip() for p in args.ladder.split(",") if p.strip()]
    forwarded = []
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--ladder":
            i += 2
            continue
        if argv[i].startswith("--ladder="):
            i += 1
            continue
        if argv[i] == "--n":
            i += 2
            continue
        if argv[i].startswith("--n="):
            i += 1
            continue
        forwarded.append(argv[i])
        i += 1
    if "--bench" not in forwarded:
        forwarded.append("--bench")
    code = 0
    for n in counts:
        print(f"\n##### ladder n={n}", flush=True)
        proc_argv = [sys.executable, here, "--n", n, *forwarded]
        import subprocess
        proc = subprocess.run(proc_argv)
        if proc.returncode != 0:
            code = proc.returncode
    raise SystemExit(code)

from scena import *  # noqa: E402
from scena.collision import get_collision_system  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import set_watchdog  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (  # noqa: E402
    average_phase_stats,
    configure_bench,
    empty_phase_stats,
    install_phase_run,
    print_phase_report,
    write_json,
)

W, H = 1000, 720
N_BALLS = max(1, int(args.n))
BALL_R = max(4, int(args.size))
rng = Random(args.seed)

init(width=W, height=H, title=f"Resolve balls — {N_BALLS}")
canvas.background = (0.04, 0.05, 0.09)
configure_bench(quality="medium")
set_watchdog(False)

Rect(center=(W * 0.5, 16), width=W, height=32, group="wall")
Rect(center=(W * 0.5, H - 16), width=W, height=32, group="wall")
Rect(center=(16, H * 0.5), width=32, height=H, group="wall")
Rect(center=(W - 16, H * 0.5), width=32, height=H, group="wall")
group["wall"].visual = Metal()
group["wall"].mass = STATIC

roda = Rect(center=(W * 0.5, H * 0.5), width=100, height=20, group="wall")
roda.visual = Halo("blue")
roda.mass = STATIC

resolve("ball", "wall", bounce=1.0)
if not args.no_ball_ball:
    resolve("ball", "ball", bounce=1.0)

if args.resolve_off:
    collision.resolve_enabled = False

hud = None
if not args.bench:
    hud = Text(text="", top_left=(16, H - 17), font_size=16)


def spawn_balls():
    group["ball"].destroy()
    r = float(BALL_R)
    for _ in range(N_BALLS):
        ball = Circle(
            center=(rng.uniform(80, W - 80), rng.uniform(200, H - 80)),
            radius=r,
            group="ball",
        )
        ball.visual = "red"
        ball.mass = 1.0
        ball.vel = vec_from_angle(rng.uniform(0, 360), length=rng.uniform(180, 340))


def update(dt):
    for ball in group["ball"]:
        ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
    if not args.no_spin:
        roda.rotate_by(50 * dt)
    if hud is not None:
        s = get_collision_system().last_stats
        hud.text = (
            f"n={len(group['ball'])}  FPS {clock.fps:.0f}  "
            f"coll {s['ms_total']:.2f}ms  resolve {s['ms_resolve']:.2f}ms  "
            f"narrow {int(s['narrow'])}  pairs {int(s['proxy_pairs'])}"
        )


spawn_balls()

_COLL_KEYS = (
    "ms_snapshot", "ms_broad", "ms_narrow", "ms_resolve", "ms_bounds", "ms_total",
    "proxies", "prims", "proxy_pairs", "narrow", "sat",
)


def _print_collision_breakdown(acc, frames):
    n = max(1, int(frames))
    print("Collision last_stats (mean / frame)")
    print(f"  proxies:            {acc['proxies'] / n:.1f}")
    print(f"  prims:              {acc['prims'] / n:.1f}")
    print(f"  proxy_pairs:        {acc['proxy_pairs'] / n:.1f}")
    print(f"  narrow:             {acc['narrow'] / n:.1f}")
    print(f"  sat:                {acc['sat'] / n:.1f}")
    print(f"  ms_snapshot:        {acc['ms_snapshot'] / n:.3f}")
    print(f"  ms_broad:           {acc['ms_broad'] / n:.3f}")
    print(f"  ms_narrow:          {acc['ms_narrow'] / n:.3f}")
    print(f"  ms_resolve:         {acc['ms_resolve'] / n:.3f}")
    print(f"  ms_bounds:          {acc['ms_bounds'] / n:.3f}")
    print(f"  ms_total:           {acc['ms_total'] / n:.3f}")
    print(f"  avg live balls:     {acc['n_balls'] / n:.1f}")
    print("=" * 60)


if args.bench:
    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    coll_acc = {k: 0.0 for k in _COLL_KEYS}
    coll_acc["n_balls"] = 0.0

    def on_frame(_framework, recording):
        if not recording:
            return
        s = get_collision_system().last_stats
        for k in _COLL_KEYS:
            coll_acc[k] += float(s.get(k, 0.0) or 0.0)
        coll_acc["n_balls"] += float(len(group["ball"]))

    install_phase_run(
        fw,
        duration=args.duration,
        warmup=args.warmup,
        stats=stats,
        on_frame=on_frame,
    )

    label = (
        f"Resolve balls  n={N_BALLS}  size={BALL_R}  "
        f"spin={not args.no_spin}  ball-ball={not args.no_ball_ball}  "
        f"resolve={not args.resolve_off}"
    )

    def _finish():
        print_phase_report(label, stats)
        _print_collision_breakdown(coll_acc, stats.get("frames", 0))
        avg = average_phase_stats(stats)
        n = max(1, int(avg["frames"]))
        payload = {
            "scene": "resolve_balls",
            "n": N_BALLS,
            "size": BALL_R,
            "seed": args.seed,
            "spin": not args.no_spin,
            "ball_ball": not args.no_ball_ball,
            "resolve_enabled": not args.resolve_off,
            "fps": avg["fps"],
            "work_ms": avg["work_ms"],
            "tick_ms": avg["tick_ms"],
            "coll_ms": avg["coll_ms"],
            "flush_ms": avg["flush_ms"],
            "draw_ms": avg["draw_ms"],
            "submit_ms": avg["submit_ms"],
            "present_ms": avg["present_ms"],
            "frames": avg["frames"],
            "ms_snapshot": coll_acc["ms_snapshot"] / n,
            "ms_broad": coll_acc["ms_broad"] / n,
            "ms_narrow": coll_acc["ms_narrow"] / n,
            "ms_resolve": coll_acc["ms_resolve"] / n,
            "ms_bounds": coll_acc["ms_bounds"] / n,
            "proxy_pairs": coll_acc["proxy_pairs"] / n,
            "narrow": coll_acc["narrow"] / n,
        }
        print("RESULT_JSON: " + json.dumps(payload))
        if args.json_path:
            write_json(args.json_path, payload)

    if args.profile:
        pr = cProfile.Profile()
        pr.enable()
        run()
        pr.disable()
        _finish()
        buf = StringIO()
        pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(40)
        print(buf.getvalue())
        buf2 = StringIO()
        pstats.Stats(pr, stream=buf2).sort_stats("tottime").print_stats(30)
        print("--- tottime ---")
        print(buf2.getvalue())
    else:
        run()
        _finish()
else:
    run()
