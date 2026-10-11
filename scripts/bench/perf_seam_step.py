"""perf_seam_step.py -- cost of the seam step (Collision Design § Seam lips).

In-process interleaved A/B on the collision step alone (no window): each
round builds the scene twice, ``_SEAM_STEP`` on (2.0) and off (0), in
alternating order, and times ``move_by`` + ``step()`` per frame. Median of
the rounds, in ms per frame.

Scenes (``--walkers`` bodies 20 x 36 on ``--tiles`` tiles 40 wide):
  flat     -- aligned tiles: the common case, no step ever runs
  lips     -- every seam a random rise in [0.2, 1.5]: steps run (off: walkers snag)
  oneway   -- ``lips`` with ``only="bottom"`` (off: walkers drop into tiles)
  walls    -- each walker presses into a wall every frame: the probe's worst
              case (lift + forward, refused), nothing else moves

    python scripts/bench/perf_seam_step.py [--frames 400] [--rounds 9] [--scene all]
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scena.collision import STATIC, get_collision_system, reset_collision_system, resolve  # noqa: E402
from scena.shapes import Rect  # noqa: E402
from scena.scenamath import Vec2  # noqa: E402

_coll = sys.modules["scena.collision"]   # ``scena.collision`` the name is the query facade

GRAVITY = 900.0
DT = 1.0 / 60.0
TILE_W, TILE_H = 40.0, 20.0
BODY_W, BODY_H = 20.0, 36.0
RUN = 120.0


def build(scene, n_tiles, n_walkers, seed):
    reset_collision_system()
    rng = random.Random(seed)
    owned = []
    top = 0.0
    tops = []
    for k in range(n_tiles):
        if scene in ("lips", "oneway") and k:
            top += rng.uniform(0.2, 1.5) * rng.choice((1.0, -1.0))
        t = Rect(center=(k * TILE_W, top - TILE_H / 2.0), width=TILE_W, height=TILE_H,
                 group="chao")
        t.mass = STATIC
        owned.append(t)
        tops.append(top)
    if scene == "walls":
        for k in range(0, n_tiles, max(1, n_tiles // n_walkers)):
            w = Rect(center=(k * TILE_W + TILE_W / 2.0, tops[k] + 50.0), width=8.0,
                     height=100.0, group="chao")
            w.mass = STATIC
            owned.append(w)
    walkers = []
    span = n_tiles * TILE_W
    for i in range(n_walkers):
        x = (i + 0.5) * span / n_walkers
        k = min(n_tiles - 1, max(0, int(round(x / TILE_W))))
        if scene == "walls":
            x = k * TILE_W + TILE_W / 2.0 - 4.0 - BODY_W / 2.0 - 0.5
        b = Rect(center=(x, tops[k] + BODY_H / 2.0 + 3.0), width=BODY_W, height=BODY_H,
                 group="corpo")
        b.mass = 1.0
        b.vel = Vec2(0.0, 0.0)
        b._dir = 1.0
        walkers.append(b)
        owned.append(b)
    resolve("corpo", "chao", bounce=0.0, only="bottom" if scene == "oneway" else None)
    return owned, walkers, span


def frame(walkers, span):
    for b in walkers:
        x = float(b.center.x)
        if (x > span - 60.0 and b._dir > 0) or (x < 20.0 and b._dir < 0):
            b._dir = -b._dir
            b.vel = Vec2(0.0, 0.0)
        b.vel.y -= GRAVITY * DT
        b.vel.x = RUN * b._dir
        b.move_by(float(b.vel.x) * DT, float(b.vel.y) * DT)
    get_collision_system().step()


def run_once(scene, step_value, args, seed):
    _coll._SEAM_STEP = step_value
    owned, walkers, span = build(scene, args.tiles, args.walkers, seed)
    for _ in range(args.warmup):
        frame(walkers, span)
    t0 = time.perf_counter()
    for _ in range(args.frames):
        frame(walkers, span)
    ms = (time.perf_counter() - t0) * 1000.0 / args.frames
    for s in owned:
        s.destroy()
    reset_collision_system()
    return ms


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", type=int, default=400)
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--rounds", type=int, default=9)
    ap.add_argument("--tiles", type=int, default=100)
    ap.add_argument("--walkers", type=int, default=30)
    ap.add_argument("--scene", default="all", choices=("all", "flat", "lips", "oneway", "walls"))
    args = ap.parse_args()
    saved = _coll._SEAM_STEP
    scenes = ("flat", "lips", "oneway", "walls") if args.scene == "all" else (args.scene,)
    print(f"seam step A/B: {args.walkers} walkers, {args.tiles} tiles, "
          f"{args.frames} frames x {args.rounds} rounds (median ms/frame)")
    try:
        for scene in scenes:
            on, off = [], []
            for r in range(args.rounds):
                order = ((saved, on), (0.0, off)) if r % 2 == 0 else ((0.0, off), (saved, on))
                for value, out in order:
                    out.append(run_once(scene, value, args, seed=r))
            m_on, m_off = statistics.median(on), statistics.median(off)
            print(f"  {scene:7s} on {m_on:7.3f}   off {m_off:7.3f}   "
                  f"{(m_on / m_off - 1.0) * 100.0:+6.1f}%")
    finally:
        _coll._SEAM_STEP = saved


if __name__ == "__main__":
    main()
