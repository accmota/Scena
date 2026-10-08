"""Cost of swept detection for fast ``@collide`` bodies (and its absence for slow ones).

A body is *fast* on a frame when its ``move_by`` travel exceeds half its own
thickness; only then does detection sweep it (Collision Design.md — Swept
detection). This probe drives ``CollisionSystem.step()`` directly at a fixed
``dt = 1/60`` so the per-frame travel does not depend on the machine.

Modes:
    slow   Shooter-like: 80 enemies drift 0.5 DU/frame, radius-7 bullets 2 DU/frame.
           Nothing is fast; this must match the tree before the change.
    hell   N small bullets (``--radius``) at ``--speed`` DU/s in random
           directions over 80 enemies and a player. Every bullet is fast when
           speed/60 > radius.
    laser  ``--shots`` 6x28 lasers at ``--speed`` DU/s up through 3 rows of enemies.

``--sweep-off`` sets ``_FAST_MOTION_FRACTION = inf`` (the old behaviour) for an
in-process A/B. The script runs on trees without swept detection too (the flag
and the new stats are then simply absent).

Usage:
    python scripts/bench/perf_collision_fast.py --mode slow
    python scripts/bench/perf_collision_fast.py --mode hell --bullets 300 --radius 3 --speed 400
    python scripts/bench/perf_collision_fast.py --mode laser --shots 10 --speed 5000
    python scripts/bench/perf_collision_fast.py --mode hell --ladder
    python scripts/bench/perf_collision_fast.py --mode hell --sweep-off
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import time

parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=("slow", "hell", "laser"), default="slow")
parser.add_argument("--bullets", type=int, default=300)
parser.add_argument("--radius", type=float, default=3.0)
parser.add_argument("--speed", type=float, default=400.0, help="DU/s (hell, laser)")
parser.add_argument("--shots", type=int, default=10)
parser.add_argument("--enemies", type=int, default=80)
parser.add_argument("--frames", type=int, default=400)
parser.add_argument("--repeats", type=int, default=3)
parser.add_argument("--ladder", action="store_true", help="hell: radius 3/6/10 x speed 120/240/400/800")
parser.add_argument("--sweep-off", action="store_true", help="_FAST_MOTION_FRACTION = inf")
args = parser.parse_args()

from scena import *  # noqa: E402,F403
import sys  # noqa: E402
from scena.collision import get_collision_system, reset_collision_system  # noqa: E402
_coll = sys.modules["scena.collision"]   # ``scena.collision`` the name is the query facade

W, H = 900, 700
DT = 1.0 / 60.0
init(width=W, height=H, window_scale=0.5)
set_watchdog(False)

HAS_SWEEP = hasattr(_coll, "_FAST_MOTION_FRACTION")
if args.sweep_off and HAS_SWEEP:
    _coll._FAST_MOTION_FRACTION = math.inf

_hits = [0]


def _on_hit(me, other, info):
    _hits[0] += 1


def build(mode: str, radius: float, speed: float, seed: int = 42):
    for s in list(group["enemy"]) + list(group["bullet"]) + list(group["player"]):
        s.destroy()
    reset_collision_system()
    collide("bullet", "enemy")(_on_hit)
    collide("bullet", "player")(_on_hit)
    rng = random.Random(seed)
    for k in range(args.enemies):
        j, i = divmod(k, 8)
        Rect(center=(100 + i * 90, H - 100 - j * 60), width=44, height=44, group="enemy")
    Circle(center=(W / 2, 60), radius=20, group="player")
    movers = []
    if mode == "slow":
        for i in range(10):
            b = Circle(center=(W / 2 + (i - 5) * 30, 100 + i * 40), radius=7, group="bullet")
            movers.append((b, 0.0, 2.0))
    elif mode == "hell":
        step = speed * DT
        for _ in range(args.bullets):
            b = Circle(center=(rng.uniform(0, W), rng.uniform(0, H)), radius=radius, group="bullet")
            a = rng.uniform(0, math.tau)
            movers.append((b, math.cos(a) * step, math.sin(a) * step))
    else:
        step = speed * DT
        for i in range(args.shots):
            b = Rect(center=(100 + (i % 8) * 90, rng.uniform(0, H)), width=6, height=28, group="bullet")
            movers.append((b, 0.0, step))
    sys_ = get_collision_system()
    sys_.step()
    return sys_, movers


def frame(sys_, movers, enemies_dx):
    t0 = time.perf_counter()
    if enemies_dx:
        for e in group["enemy"]:
            e.move_by(enemies_dx, 0)
    for b, dx, dy in movers:
        b.move_by(dx, dy)
        c = b.center
        if c.x < 0 or c.x > W or c.y < 0 or c.y > H:
            b.center = (c.x % W, c.y % H)     # placement: not swept
    t1 = time.perf_counter()
    sys_.step()
    t2 = time.perf_counter()
    return (t1 - t0) * 1000.0, (t2 - t1) * 1000.0


def run_case(mode: str, radius: float, speed: float):
    rows = []
    for rep in range(args.repeats):
        sys_, movers = build(mode, radius, speed, seed=42 + rep)
        drift = 0.5 if mode == "slow" else 0.0
        for _ in range(20):
            frame(sys_, movers, drift)
        _hits[0] = 0
        moves, steps = [], []
        stats = {k: [] for k in ("ms_broad", "ms_narrow", "proxy_pairs", "narrow", "fast", "swept", "swept_hits")}
        for f in range(args.frames):
            d = drift if (f // 100) % 2 == 0 else -drift
            mv, st_ = frame(sys_, movers, d)
            moves.append(mv)
            steps.append(st_)
            ls = sys_.last_stats
            for k in stats:
                if k in ls:
                    stats[k].append(ls[k])
        rows.append({
            "step": statistics.median(steps),
            "move": statistics.median(moves),
            "hits": _hits[0] / args.frames,
            **{k: (statistics.fmean(v) if v else float("nan")) for k, v in stats.items()},
        })
    med = lambda k: statistics.median(r[k] for r in rows)  # noqa: E731
    return {k: med(k) for k in rows[0]}


def show(label: str, r) -> None:
    print(
        f"{label:<28} step {r['step']:7.3f} ms  move {r['move']:6.3f} ms  "
        f"broad {r['ms_broad']:6.3f}  narrow {r['ms_narrow']:6.3f}  "
        f"pairs {r['proxy_pairs']:7.1f}  narrow# {r['narrow']:6.1f}  "
        f"fast {r['fast']:6.1f}  swept {r['swept']:6.1f}  swept_hits {r['swept_hits']:5.2f}  "
        f"hits/f {r['hits']:5.2f}"
    )


print("=" * 72)
print(f"mode={args.mode}  sweep={'n/a (old tree)' if not HAS_SWEEP else ('off' if args.sweep_off else 'on')}  "
      f"frames={args.frames} x{args.repeats} (median)")
print("=" * 72)
if args.mode == "hell" and args.ladder:
    for radius in (3.0, 6.0, 10.0):
        for speed in (120.0, 240.0, 400.0, 800.0):
            show(f"r={radius:g} v={speed:g} ({speed * DT:.1f}/f)", run_case("hell", radius, speed))
else:
    show(args.mode, run_case(args.mode, args.radius, args.speed))
