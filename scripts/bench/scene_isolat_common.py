"""
Shared scene + motion for the 4-tier Scena overhead isolation suite.

Scene
-----
200 axis-aligned-then-rotated rects (seeded):
  - 100 fixed
  - 100 moving (translation + rotation)

Motion deliberately avoids ``cos`` / ``sin`` in the per-frame loop: constant
velocity with edge bounce + angular speed. Isolates framework / draw cost from
script trigonometry (unlike ``app_scene_demo`` orbit math).

Tiers (see ``app_scene_isolat.py``)
----------------------------------
1. reactive  — Scena ``Rect`` (Attribute / Derivate graph)
2. simple    — ``SimpleRect`` float drawable on Scena canvas
3. sprite    — ``SimpleRectSprite`` bitmap blit on Scena canvas
4. raw       — GLFW + Skia only (no Scena)
"""
from __future__ import annotations

import argparse
import random
from typing import Dict, List, Tuple

from perf_common import print_report
from perf_profile import add_profile_args

WIDTH = 1200
HEIGHT = 800
DEFAULT_N = 200          # total shapes
DEFAULT_N_MOVE = 100     # of which movers
DEFAULT_SEED = 11
MARGIN = 40
SIZE_RANGE = (14.0, 36.0)
SPEED_RANGE = (40.0, 140.0)   # px/s
SPIN_RANGE = (30.0, 180.0)    # deg/s

COLORS = (
    (0.20, 0.75, 0.95, 1.0),
    (0.95, 0.35, 0.70, 1.0),
    (0.45, 0.90, 0.40, 1.0),
    (0.98, 0.70, 0.25, 1.0),
    (0.35, 0.55, 0.98, 1.0),
    (0.80, 0.45, 0.95, 1.0),
)

Pose = Dict[str, float]


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--bench", action="store_true",
                   help="run uncapped FPS bench and exit")
    p.add_argument("--duration", type=float, default=2.0)
    p.add_argument("--warmup", type=float, default=0.4)
    p.add_argument("--n", type=int, default=DEFAULT_N,
                   help=f"total shapes (default {DEFAULT_N})")
    p.add_argument("--n-move", type=int, default=DEFAULT_N_MOVE,
                   help=f"moving shapes (default {DEFAULT_N_MOVE})")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--static", action="store_true",
                   help="freeze movers (isolate draw cost)")
    p.add_argument(
        "--tier",
        choices=("reactive", "simple", "sprite", "raw", "1", "2", "3", "4"),
        default="reactive",
        help="1=reactive 2=simple 3=sprite 4=raw",
    )
    p.add_argument(
        "--suite", action="store_true",
        help="with --bench: run all tiers (+ static) in subprocesses",
    )
    add_profile_args(p)
    return p


def normalize_tier(tier: str) -> str:
    return {
        "1": "reactive", "2": "simple", "3": "sprite", "4": "raw",
        "reactive": "reactive", "simple": "simple",
        "sprite": "sprite", "raw": "raw",
    }[tier]


def generate_rects(
    n: int = DEFAULT_N,
    n_move: int = DEFAULT_N_MOVE,
    width: float = WIDTH,
    height: float = HEIGHT,
    seed: int = DEFAULT_SEED,
) -> Tuple[List[Pose], List[Pose]]:
    """Return (fixed_poses, mover_poses). Movers include vx/vy/spin."""
    if n_move > n:
        raise ValueError(f"n_move ({n_move}) cannot exceed n ({n})")
    rng = random.Random(seed)
    fixed: List[Pose] = []
    movers: List[Pose] = []
    for i in range(n):
        w = rng.uniform(*SIZE_RANGE)
        length = rng.uniform(*SIZE_RANGE)
        pose: Pose = {
            "x": rng.uniform(MARGIN, width - MARGIN),
            "y": rng.uniform(MARGIN, height - MARGIN),
            "width": w,
            "length": length,
            "angle": rng.uniform(0.0, 360.0),
            "r": COLORS[i % len(COLORS)][0],
            "g": COLORS[i % len(COLORS)][1],
            "b": COLORS[i % len(COLORS)][2],
            "a": 1.0,
        }
        if i < n_move:
            pose["vx"] = rng.uniform(*SPEED_RANGE) * rng.choice((-1.0, 1.0))
            pose["vy"] = rng.uniform(*SPEED_RANGE) * rng.choice((-1.0, 1.0))
            pose["spin"] = rng.uniform(*SPIN_RANGE) * rng.choice((-1.0, 1.0))
            movers.append(pose)
        else:
            fixed.append(pose)
    return fixed, movers


def step_mover(m: Pose, dt: float, width: float = WIDTH, height: float = HEIGHT) -> None:
    """In-place bounce + spin. No trig."""
    x = m["x"] + m["vx"] * dt
    y = m["y"] + m["vy"] * dt
    if x < MARGIN:
        x = MARGIN
        m["vx"] = abs(m["vx"])
    elif x > width - MARGIN:
        x = width - MARGIN
        m["vx"] = -abs(m["vx"])
    if y < MARGIN:
        y = MARGIN
        m["vy"] = abs(m["vy"])
    elif y > height - MARGIN:
        y = height - MARGIN
        m["vy"] = -abs(m["vy"])
    m["x"] = x
    m["y"] = y
    ang = m["angle"] + m["spin"] * dt
    # keep angle in [0, 360) without trig
    if ang >= 360.0 or ang < 0.0:
        ang %= 360.0
    m["angle"] = ang


def color_of(pose: Pose) -> Tuple[float, float, float, float]:
    return (pose["r"], pose["g"], pose["b"], pose["a"])


def report(label: str, frame_times, n: int, extra: str = "") -> None:
    print_report(label, frame_times, n)
    if extra:
        print(f"  {extra}")
