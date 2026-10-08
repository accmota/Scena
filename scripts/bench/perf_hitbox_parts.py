"""Cost of hitbox parts at fleet scale (``sprite.add_hitbox``).

N animated walkers (Run.png strip, 12 fps) with a stable body rect and M
bullets crossing them. ``body`` mode: the body carries ``"hurt"`` (one
collider per sprite). ``parts`` mode: a per-frame silhouette part answers
``"hurt"`` (``hitbox_source="each"``), so every sprite has two colliders and
the part rebakes as the clip plays. ``linked`` mode (round 2): the part is a
``px_rect`` whose ``active`` is linked to half the cells
(``hb["active"] @= lambda: s.showing(...)``), so each step also calls one
function per sprite. The reported overhead is ``parts − body`` (and
``linked − body``) per ``step()``; ×4 approximates the target machine.

Usage:
    python scripts/bench/perf_hitbox_parts.py
    python scripts/bench/perf_hitbox_parts.py --n 200 --frames 300
    python scripts/bench/perf_hitbox_parts.py --rotation 1.5 --tilt 12
    python scripts/bench/perf_hitbox_parts.py --mode all
"""
from __future__ import annotations

import argparse
import os
import statistics
import time

parser = argparse.ArgumentParser()
parser.add_argument("--n", type=int, default=100, help="animated sprites")
parser.add_argument("--bullets", type=int, default=20)
parser.add_argument("--frames", type=int, default=240, help="measured steps")
parser.add_argument("--mode", choices=("body", "parts", "linked", "both", "all"), default="both")
parser.add_argument("--rotation", type=float, default=0.0, help="degrees per frame")
parser.add_argument("--tilt", type=float, default=0.0, help="constant tilt (degrees)")
args = parser.parse_args()

from scena import *  # noqa: E402,F403
from scena.collision import get_collision_system, reset_collision_system  # noqa: E402

W, H = 1200, 800
init(width=W, height=H, window_scale=0.5)
set_watchdog(False)

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_PNG = os.path.join(HERE, "..", "..", "examples", "media", "pixel_adv", "Start (Moving) (64x64).png")
SHEET = Sheet(RUN_PNG, cols=17, fps=12, name="run")
DT = 1.0 / 60.0
_STRIKE = (0, 1, 2, 3)   # half of the 8 Run cells


def build(mode: str):
    reset_collision_system()
    hits = [0]

    @collide("bullet", "hurt")
    def _hit(bullet, target, info):
        hits[0] += 1

    actors = []
    cols = 20
    for i in range(args.n):
        x = 60 + (i % cols) * 56
        y = 120 + (i // cols) * 90
        s = Sprite(
            SHEET, height=60, center=(x, y),
            hitbox_shape="rect", hitbox_source="all", hitbox_anchor="bottom",
            hitbox_scale=(0.55, 1.0),
            group=("walker", "hurt") if mode == "body" else "walker",
        )
        if args.tilt:
            s.tilt = args.tilt
        if mode == "parts":
            s.add_hitbox(group="hurt")
        elif mode == "linked":
            hb = s.add_hitbox(group="hurt", px_rect=(20, 10, 40, 44))
            hb["active"] @= (lambda s=s: s.showing(_STRIKE))
        actors.append(s)
    bullets = [
        Circle(center=(60 + i * (W - 120) / max(1, args.bullets - 1), 40), radius=4,
               group="bullet")
        for i in range(args.bullets)
    ]
    return actors, bullets, hits


def run(mode: str) -> dict:
    actors, bullets, hits = build(mode)
    sys = get_collision_system()
    for _ in range(10):  # warm bakes (every Run cell) and caches
        clock.advance(DT)
        sys.step()
    builds0 = sys._debug_hull_builds
    times = []
    for f in range(args.frames):
        clock.advance(DT)
        for b in bullets:
            b.move_by(0, 3.0)
            if b.center.y > H:
                b.center = (b.center.x, 40)
        for a in actors:
            a.move_by(0.4 if (f // 60) % 2 == 0 else -0.4, 0)
            if args.rotation:
                a.rotate_by(args.rotation)
        t0 = time.perf_counter()
        sys.step()
        times.append(time.perf_counter() - t0)
    out = {
        "mode": mode,
        "colliders": len(sys._colliders),
        "ms": statistics.mean(times) * 1000.0,
        "p95": sorted(times)[int(len(times) * 0.95)] * 1000.0,
        "builds": (sys._debug_hull_builds - builds0) / args.frames,
        "hits": hits[0],
    }
    for a in actors + bullets:
        a.destroy()
    return out


modes = {"both": ("body", "parts"), "all": ("body", "parts", "linked")}.get(
    args.mode, (args.mode,))
results = [run(m) for m in modes]
print("=" * 72)
print(f"hitbox parts — n={args.n} bullets={args.bullets} frames={args.frames} "
      f"rotation={args.rotation}/frame tilt={args.tilt}")
print("-" * 72)
print(f"{'mode':<6} {'colliders':>9} {'ms/step':>9} {'p95':>8} {'prim builds/step':>17} {'hits':>6}")
for r in results:
    print(f"{r['mode']:<6} {r['colliders']:>9} {r['ms']:>9.3f} {r['p95']:>8.3f} "
          f"{r['builds']:>17.1f} {r['hits']:>6}")
base = next((r for r in results if r["mode"] == "body"), None)
if base is not None and len(results) > 1:
    print("-" * 72)
    for r in results:
        if r is base:
            continue
        over = r["ms"] - base["ms"]
        print(f"{r['mode']} overhead: {over:+.3f} ms/step here, "
              f"~{over * 4:+.3f} ms on the target (x4)")
