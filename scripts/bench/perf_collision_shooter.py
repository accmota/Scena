"""
Profile collision cost for an app_shooter-like scene.

Usage:
    python scripts/perf_collision_shooter.py --shape poly
    python scripts/perf_collision_shooter.py --shape rect
    python scripts/perf_collision_shooter.py --shape poly --enemies 80 --frames 200
"""
from __future__ import annotations

import argparse
import cProfile
import pstats
import time
from collections import defaultdict
from io import StringIO

parser = argparse.ArgumentParser()
parser.add_argument("--enemies", type=int, default=80)
parser.add_argument("--bullets", type=int, default=10)
parser.add_argument("--frames", type=int, default=200)
parser.add_argument("--shape", choices=("poly", "rect"), default="poly")
args = parser.parse_args()

from scena import *  # noqa: E402
from scena.collision import get_collision_system, snapshot_shape, narrow_phase

W, H = 900, 700
init(width=W, height=H, window_scale=0.5)
canvas.background = (0.05, 0.06, 0.12, 1)

@collide("bullet", "enemy")
def on_be(me, other, info):
    pass

@collide("bullet", "ceiling")
def on_bc(me, other, info):
    pass

@collide("enemy", "player")
def on_ep(me, other, info):
    pass

player = EquilateralTriangle(center=(W / 2, 60), radius=28, angle=90, group="player").set_color("dodger blue")
ceiling = Rect(center=(W / 2, H + 50), width=W + 200, height=60, group="ceiling")
ceiling.visible = False

colors = ["crimson", "tomato", "orange", "gold", "coral", "salmon", "red", "magenta"]
ns = [5, 6, 4, 8, 5, 6, 7, 4]
n_rows = max(1, (args.enemies + 7) // 8)
for j in range(n_rows):
    for i in range(8):
        if j * 8 + i >= args.enemies:
            break
        x = 100 + i * 90
        y = H - 100 - j * 5
        if args.shape == "rect":
            Rect(center=(x, y), width=44, height=44, angle=0, group="enemy").set_color(colors[i % 8])
        else:
            RegularPolygon(
                n=ns[i % 8], center=(x, y), radius=22, angle=0, group="enemy",
            ).set_color(colors[i % 8])

for i in range(args.bullets):
    Circle(center=(W / 2 + (i - 5) * 12, 200 + i * 40), radius=7, group="bullet").set_color("yellow")

sys = get_collision_system()
sys.step()

print("=" * 64)
print(f"Shape={args.shape}  enemies={args.enemies}  bullets={args.bullets}")
print(f"Colliders={len(sys._colliders)}  handlers={len(sys._pair_handlers)}")
print("=" * 64)

_stats = defaultdict(float)
_counts = defaultdict(int)


def _timed_step():
    import numpy as np

    t0 = time.perf_counter()
    sys._prune_dead()
    _stats["prune"] += time.perf_counter() - t0

    t0 = time.perf_counter()
    sys._resolve_cache.clear()
    for c in sys._colliders:
        c._tags_cache = None
    sys._refresh_pair_enrollments()
    _stats["refresh"] += time.perf_counter() - t0

    t0 = time.perf_counter()
    prim_list = []
    for c in sys._colliders:
        for shape in c.shapes:
            for prim in snapshot_shape(shape, cache_owner=c):
                prim_list.append((c, prim))
    _stats["snapshot"] += time.perf_counter() - t0
    _counts["prims"] += len(prim_list)

    n = len(prim_list)
    t0 = time.perf_counter()
    aabb = np.zeros((n, 4), dtype=np.float64)
    for i, (_, prim) in enumerate(prim_list):
        aabb[i] = prim.aabb
    minx, miny, maxx, maxy = aabb[:, 0], aabb[:, 1], aabb[:, 2], aabb[:, 3]
    no_x = (minx[:, None] > maxx[None, :]) | (minx[None, :] > maxx[:, None])
    no_y = (miny[:, None] > maxy[None, :]) | (miny[None, :] > maxy[:, None])
    overlap = ~(no_x | no_y)
    np.fill_diagonal(overlap, False)
    ii, jj = np.nonzero(np.triu(overlap, k=1))
    _stats["broad"] += time.perf_counter() - t0
    _counts["aabb_pairs"] += len(ii)

    t0 = time.perf_counter()
    n_int = 0
    n_narrow = 0
    n_hit = 0
    for i, j in zip(ii.tolist(), jj.tolist()):
        ca, pa = prim_list[i]
        cb, pb = prim_list[j]
        if ca is cb:
            continue
        if not sys._interested(ca, cb):
            continue
        n_int += 1
        n_narrow += 1
        if narrow_phase(pa, pb) is not None:
            n_hit += 1
    _stats["pair_loop"] += time.perf_counter() - t0
    _counts["interested"] += n_int
    _counts["narrow"] += n_narrow
    _counts["hits"] += n_hit

    t0 = time.perf_counter()
    sys.step()
    _stats["full_step"] += time.perf_counter() - t0


for _ in range(5):
    sys.step()
_stats.clear()
_counts.clear()

t_wall0 = time.perf_counter()
for _ in range(args.frames):
    for e in group["enemy"]:
        e.move_by(0.5, 0)
    for b in group["bullet"]:
        b.move_by(0, 2.0)
    _timed_step()
t_wall = time.perf_counter() - t_wall0
f = args.frames

print("\nMean per frame (ms)")
print("-" * 64)
for k in ("prune", "refresh", "snapshot", "broad", "pair_loop", "full_step"):
    print(f"  {k:<14} {_stats[k] / f * 1000:8.3f}")
print(f"  wall           {t_wall / f * 1000:8.3f}   (~{f / t_wall:.0f} step-FPS)")

print("\nCounts (mean/frame)")
print("-" * 64)
for k in ("prims", "aabb_pairs", "interested", "narrow", "hits"):
    print(f"  {k:<14} {_counts[k] / f:8.1f}")

print("\ncProfile: CollisionSystem.step × 100 (after moves)")
print("-" * 64)
pr = cProfile.Profile()
pr.enable()
for _ in range(100):
    for e in group["enemy"]:
        e.move_by(0.2, 0)
    sys.step()
pr.disable()
buf = StringIO()
pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(30)
for line in buf.getvalue().splitlines():
    if any(s in line for s in (
        "ncalls", "tottime", "collision.py", "shapes.py", "state.py",
        "snapshot", "get_xy", "narrow", "step", "resolve", "wants",
        "interested", "_update_impl", "_bare", "points",
    )):
        print(line)
