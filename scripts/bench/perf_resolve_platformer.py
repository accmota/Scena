"""Sprite ``resolve()`` probe — platformer pairs, ball count is the only load knob.

Same standing resolves as a platformer game: one hero,
three walkers, a moving platform, a ramp, a spinning slab, and ``--balls``
sprite shots. Frozen pulse cell is ``--balls 50`` (see ``run_resolve.py``).
``cpu_mix`` already covers sprite count; this scene keeps sprite hitboxes,
resting contacts, elevators, and ramps in the measured loop.

Usage
-----
    python scripts/bench/perf_resolve_platformer.py --bench --balls 50 --duration 3
    python scripts/bench/perf_resolve_platformer.py --bench --balls 50 --resolve-off
    python scripts/bench/perf_resolve_platformer.py --bench --balls 50 --no-ball-ball
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from random import Random

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--balls", type=int, default=50, help="live sprite shots (default 50)")
_parser.add_argument("--bench", action="store_true",
                    help="uncapped FPS, phase-time, then exit")
_parser.add_argument("--duration", type=float, default=3.0,
                    help="measured seconds when --bench (default 3)")
_parser.add_argument("--warmup", type=float, default=0.5,
                    help="warmup seconds excluded from stats (default 0.5)")
_parser.add_argument("--seed", type=int, default=42)
_parser.add_argument("--resolve-off", action="store_true",
                    help="skip standing resolve (detection stays on)")
_parser.add_argument("--no-ball-ball", action="store_true",
                    help="do not register resolve(\"bola\", \"bola\")")
_parser.add_argument("--json", dest="json_path", default=None,
                    help="write phase-timing JSON (with --bench)")
args, _ = _parser.parse_known_args()

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

W, H = 1100, 720
GRAVITY = 900.0
N_BALLS = max(0, int(args.balls))
rng = Random(args.seed)

init(width=W, height=H, title=f"Resolve platformer — {N_BALLS} balls")
collision.floor = True   # gravity: bodies stand on floors (ramps, lifts, seams)
canvas.background = (0.55, 0.75, 0.95)
configure_bench(quality="medium")
set_watchdog(False)


def platform(center, width, height, angle=0):
    block = Rect(
        center=center, width=width, height=height, angle=angle, group="plataforma",
    )
    block.visual = "sienna"
    block.mass = STATIC
    return block


platform(center=(550, 40), width=W, height=40)
platform(center=(420, 200), width=220, height=24)
platform(center=(780, 280), width=180, height=24)
platform(center=(880, 160), width=200, height=24, angle=22)

elevator = platform(center=(230, 200), width=120, height=20)
elevator.visual = "goldenrod"
elevator.vel = Vec2(0, 80)

slab = platform(center=(600, 400), width=120, height=20)
slab.visual = "steel blue"

for x, color in ((30, "dim gray"), (1070, "dim gray")):
    wall = Rect(center=(x, H * 0.5), width=24, height=H, group="parede")
    wall.visual = color
    wall.mass = STATIC

idle = [f"examples/media/ninja/Idle__{i:03d}.png" for i in range(10)]
sheet = Sheet(idle)
sheet.clip("parado", idle, fps=8)
hero = Sprite(
    sheet,
    height=70,
    center=(120, 120),
    group="heroi",
    hitbox_shape="rect",
    hitbox_source="all",
    hitbox_anchor="bottom",
    hitbox_scale=(0.55, 1),
)
hero.mass = 1.0
hero.vel = Vec2(180, 0)
hero.play("parado")

for center, speed in (((520, 90), 55), ((420, 230), -55), ((780, 350), 55)):
    walker = Sprite(
        Sheet([f"examples/media/robot/Run ({i}).png" for i in range(1, 9)], fps=12, pixel_size=0.1),
        height=36,
        center=center,
        group="inimigo",
        hitbox_shape="rect",
    )
    walker.mass = 1.0
    walker.vel = Vec2(speed, 0)
    walker.flip_x = speed > 0

resolve("heroi", ["plataforma", "parede"], bounce=0.0)
resolve("inimigo", "plataforma", bounce=0.2)
resolve("inimigo", "parede", bounce=0.0)
resolve("bola", ["plataforma", "parede"], bounce=0.7)
if not args.no_ball_ball:
    resolve("bola", "bola", bounce=1.0)

if args.resolve_off:
    collision.resolve_enabled = False


def spawn_balls():
    group["bola"].destroy()
    cols = 10
    for i in range(N_BALLS):
        col = i % cols
        row = i // cols
        ball = Sprite(
            "examples/media/k-rolling-ball/ball_red_large.png",
            center=(160 + col * 72, 280 + row * 36),
            size=16,
            group="bola",
        )
        ball.mass = 0.1
        ball.vel = vec_from_angle(rng.uniform(-40, 40) + (20 if col < 5 else 160), length=rng.uniform(180, 420))


@collide("inimigo", "parede")
def turn(walker, _wall, _info):
    walker.flip_x = not walker.flip_x
    walker.vel.x = -walker.vel.x


def update(dt):
    hero.vel.y -= GRAVITY * dt
    if hero.center.x < 160:
        hero.vel.x = abs(hero.vel.x)
        hero.flip_x = False
    elif hero.center.x > 940:
        hero.vel.x = -abs(hero.vel.x)
        hero.flip_x = True
    hero.move_by(hero.vel.x * dt, hero.vel.y * dt)

    elevator.move_by(0, elevator.vel.y * dt)
    if elevator.center.y > 700:
        elevator.vel.y = -80
    elif elevator.center.y < 90:
        elevator.vel.y = 80

    slab.rotate_by(150 * dt)

    for walker in group["inimigo"]:
        walker.vel.y -= GRAVITY * dt
        walker.move_by(walker.vel.x * dt, walker.vel.y * dt)

    for ball in group["bola"]:
        ball.vel.y -= GRAVITY * dt
        ball.move_by(ball.vel.x * dt, ball.vel.y * dt)


spawn_balls()

_COLL_KEYS = (
    "ms_snapshot", "ms_broad", "ms_narrow", "ms_resolve", "ms_bounds", "ms_total",
    "proxies", "prims", "proxy_pairs", "narrow", "sat",
)

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
        coll_acc["n_balls"] += float(len(group["bola"]))

    install_phase_run(
        fw,
        duration=args.duration,
        warmup=args.warmup,
        stats=stats,
        on_frame=on_frame,
    )

    label = (
        f"Resolve platformer  balls={N_BALLS}  "
        f"ball-ball={not args.no_ball_ball}  resolve={not args.resolve_off}"
    )

    def _finish():
        print_phase_report(label, stats)
        n = max(1, int(stats.get("frames", 0)))
        avg = average_phase_stats(stats)
        payload = {
            "scene": "resolve_platformer",
            "balls": N_BALLS,
            "seed": args.seed,
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
            "avg_balls": coll_acc["n_balls"] / n,
        }
        print("RESULT_JSON: " + json.dumps(payload))
        print(
            f"  ms_resolve:         {payload['ms_resolve']:.3f}  "
            f"ms_bounds: {payload['ms_bounds']:.3f}  "
            f"ms_broad: {payload['ms_broad']:.3f}  "
            f"avg balls: {payload['avg_balls']:.1f}"
        )
        if args.json_path:
            write_json(args.json_path, payload)

    run()
    _finish()
else:
    run()
