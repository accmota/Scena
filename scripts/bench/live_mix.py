"""Live mixed scene — everything moving, every frame.

Answers: when sprites, shapes, SpatialFx, camera, background, and lifecycle
churn all run together, how does Scena perform?

Exercises
---------
  * sprites of many sizes, ``hitbox_shape="auto"``, rotating + scaling
  * shapes colliding with sprites, rotating + scaling
  * SpatialFx with live params, colliding with sprites and shapes
  * camera pan / zoom / rotate
  * background fields (and field ``enabled`` toggling)
  * sprite create/destroy, ``visible``, ``active`` (park = enable/disable)
  * per-frame dynamic ink fields (hp / phase / energy / heat)

Usage
-----
    python scripts/bench/live_mix.py
    python scripts/bench/live_mix.py --bench --duration 3 --warmup 0.5
    python scripts/bench/live_mix.py --bench --n 120 --quality high
    python scripts/bench/live_mix.py --bench --ladder 40,80,160
    python scripts/bench/live_mix.py --bench --profile --duration 2

Controls (interactive)
----------------------
  SPACE   pause / resume
  C       collider outlines
  E       cycle FX quality
  O       toggle offscreen cull
  R       reset camera
"""
from __future__ import annotations

import argparse
import cProfile
import math
import os
import pstats
import subprocess
import sys
from io import StringIO
from random import Random

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--n", type=int, default=80,
                     help="persistent sprite count (default 80); shapes ≈ n/2")
_parser.add_argument("--bench", action="store_true",
                     help="uncapped FPS, phase-time, then exit")
_parser.add_argument("--duration", type=float, default=3.0,
                     help="measured seconds when --bench (default 3)")
_parser.add_argument("--warmup", type=float, default=0.5,
                     help="warmup seconds excluded from stats (default 0.5)")
_parser.add_argument("--ladder", type=str, default=None,
                     help="comma-separated N values; overrides --n")
_parser.add_argument("--quality", default="high",
                     choices=("low", "medium", "high", "max"))
_parser.add_argument("--seed", type=int, default=42)
_parser.add_argument("--cull", action="store_true",
                     help="enable canvas.cull_offscreen")
_parser.add_argument("--profile", action="store_true",
                     help="with --bench, also print cProfile top functions")
_parser.add_argument("--json", dest="json_path", default=None)
args, _ = _parser.parse_known_args()

_BENCH = os.path.dirname(os.path.abspath(__file__))
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from harness import (  # noqa: E402
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
    parse_ladder,
    print_phase_report,
    write_json,
)

if args.ladder and not os.environ.get("LIVE_MIX_WORKER"):
    ns = parse_ladder(args.ladder)
    script = os.path.abspath(__file__)
    env = dict(os.environ)
    env["LIVE_MIX_WORKER"] = "1"
    print(f"=== live_mix ladder  n={ns}  duration={args.duration}s  Q={args.quality} ===", flush=True)
    for n in ns:
        cmd = [
            sys.executable, script,
            "--bench", "--n", str(n),
            "--duration", str(args.duration), "--warmup", str(args.warmup),
            "--quality", args.quality, "--seed", str(args.seed),
        ]
        if args.cull:
            cmd.append("--cull")
        print(f"\n>> n={n}", flush=True)
        subprocess.run(cmd, env=env, check=False)
    sys.exit(0)

from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import set_watchdog  # noqa: E402

W, H = 1280, 800
WORLD_W, WORLD_H = 1180.0, 780.0
N_SPRITES = max(12, int(args.n))
N_SHAPES = max(6, N_SPRITES // 2)

init(width=W, height=H, window_scale=0.72, title="Bench — live mix")
canvas.set_origin("center")
set_fx_auto(False)
canvas.fx_quality = args.quality
canvas.cull_offscreen = bool(args.cull)
canvas.batch_shared_filters = True
set_watchdog(False)
canvas.framerate = "max"

rng = Random(args.seed)

SkyGradient("night")
_stars = Stars(pan_response=0.18, density=0.8, amount=0.9, twinkle=0.35, scroll=(0.0, -18.0))
_stardust = Stardust(pan_response=0.45, amount=0.55)
canvas.effects.add(Vignette(amount=0.28))

space = Sheet("examples/media/shooter/sheet.xml")

SPRITE_KINDS = (
    ("playerShip1_blue.png", 52),
    ("playerShip2_orange.png", 40),
    ("playerShip3_green.png", 28),
    ("enemyBlue1.png", 44),
    ("enemyGreen2.png", 34),
    ("enemyRed3.png", 26),
    ("ufoBlue.png", 48),
    ("ufoRed.png", 22),
    ("meteorBrown_big1.png", 72),
    ("meteorBrown_med1.png", 40),
    ("meteorBrown_small1.png", 22),
    ("meteorGrey_tiny1.png", 14),
    ("meteorGrey_big2.png", 64),
    ("ufoYellow.png", 18),
)
SHAPE_COLORS = (
    "crimson", "tomato", "orange", "gold", "coral",
    "dodger blue", "medium orchid", "sea green", "sky blue", "salmon",
)
CHURN_FRAMES = (
    ("meteorBrown_tiny1.png", 16),
    ("meteorGrey_tiny2.png", 14),
    ("laserBlue02.png", 22),
    ("fire06.png", 18),
)

st.hits_sg = 0
st.hits_sx = 0
st.hits_gx = 0
st.hits_ch = 0
st.spawned = 0
st.destroyed = 0

_paused = False
_outlines = False
_fleet: list = []
_geom: list = []
_sfx: list = []
_vis_toggle: list = []
_park_toggle: list = []
_emitters: list = []  # (fx, kind)


def _world_xy(i: int, n: int, jitter: float) -> tuple[float, float]:
    cols = max(1, int(math.ceil(math.sqrt(n * WORLD_W / WORLD_H))))
    rows = max(1, int(math.ceil(n / cols)))
    col = i % cols
    row = i // cols
    x = (col + 0.5) / cols * WORLD_W - WORLD_W * 0.5
    y = (row + 0.5) / rows * WORLD_H - WORLD_H * 0.5
    x += rng.uniform(-jitter, jitter)
    y += rng.uniform(-jitter, jitter)
    return x, y


# ---------------------------------------------------------------------------
# Actors
# ---------------------------------------------------------------------------

class Craft(Sprite):
    """Persistent sprite: pose + ink fields rewritten every tick."""

    def setup(self):
        self.home_x = float(self.center.x)
        self.home_y = float(self.center.y)
        self.spin = rng.uniform(-140.0, 140.0)
        self.orbit = rng.uniform(0.6, 1.8) * rng.choice((-1.0, 1.0))
        self.bob = rng.uniform(16.0, 42.0)
        self.hp = 10.0
        self.phase = rng.uniform(0.0, 360.0)
        self.energy = 1.0
        self.heat = 0.0

    def on_update(self, dt):
        t = clock.time
        self.phase = (float(self.phase) + self.spin * dt) % 360.0
        self.energy = 0.5 + 0.5 * math.sin(t * 2.15 + self.home_x * 0.012)
        self.heat = 0.5 + 0.5 * math.cos(t * 1.55 + self.home_y * 0.01)
        self.hp = 6.0 + 4.0 * float(self.energy)
        self.angle = float(self.phase)
        self.scale = 0.78 + 0.32 * float(self.energy)
        self.center = (
            self.home_x + math.cos(t * self.orbit) * self.bob,
            self.home_y + math.sin(t * self.orbit * 0.82) * (self.bob * 0.7),
        )


def _bind_shape(shp, home_r=None, home_w=None, home_h=None, home_l=None):
    shp.home_x = float(shp.center.x)
    shp.home_y = float(shp.center.y)
    shp.home_r = home_r
    shp.home_w = home_w
    shp.home_h = home_h
    shp.home_l = home_l
    shp.spin = rng.uniform(-90.0, 90.0)
    shp.orbit = rng.uniform(0.4, 1.4) * rng.choice((-1.0, 1.0))
    shp.bob = rng.uniform(10.0, 28.0)
    shp.hp = 8.0
    shp.phase = rng.uniform(0.0, 360.0)
    shp.energy = 1.0
    shp.heat = 0.0

    def on_update(e, dt):
        t = clock.time
        e.phase = (float(e.phase) + e.spin * dt) % 360.0
        e.energy = 0.5 + 0.5 * math.sin(t * 1.7 + e.home_x * 0.01)
        e.heat = 0.5 + 0.5 * math.cos(t * 1.3 + e.home_y * 0.008)
        e.hp = 5.0 + 3.0 * float(e.energy)
        e.angle = float(e.phase)
        k = 0.82 + 0.28 * float(e.energy)
        if e.home_r is not None:
            e.radius = e.home_r * k
        if e.home_w is not None:
            e.width = e.home_w * k
        if e.home_h is not None:
            e.height = e.home_h * k
        if e.home_l is not None:
            e.length = e.home_l * k
        e.center = (
            e.home_x + math.sin(t * e.orbit) * e.bob,
            e.home_y + math.cos(t * e.orbit * 0.9) * (e.bob * 0.65),
        )

    shp.on_update = on_update
    return shp


class Spark(Sprite):
    """Short-lived sprite — create/destroy churn + ink writes."""

    def setup(self):
        self.life = rng.uniform(0.7, 1.4)
        self.spin = rng.uniform(-220.0, 220.0)
        self.vx = rng.uniform(-90.0, 90.0)
        self.vy = rng.uniform(-70.0, 70.0)
        self.hp = 1.0
        self.phase = 0.0
        self.energy = 1.0
        self.heat = 1.0
        st.spawned += 1

    def on_update(self, dt):
        self.life -= dt
        self.phase = float(self.phase) + self.spin * dt
        self.energy = max(0.0, self.life)
        self.heat = float(self.energy)
        self.hp = float(self.energy)
        self.angle = float(self.phase)
        self.scale = 0.55 + 0.55 * max(0.0, min(1.0, self.life))
        self.move_by(self.vx * dt, self.vy * dt)
        if self.life <= 0.0:
            st.destroyed += 1
            self.destroy()


def _spawn_churn():
    frame, size = CHURN_FRAMES[rng.randrange(len(CHURN_FRAMES))]
    Spark(
        space,
        frame=frame,
        size=size,
        center=(rng.uniform(-WORLD_W * 0.4, WORLD_W * 0.4),
                rng.uniform(-WORLD_H * 0.4, WORLD_H * 0.4)),
        group="churn",
        hitbox_shape="auto",
    )


# ---------------------------------------------------------------------------
# Scene build
# ---------------------------------------------------------------------------

for i in range(N_SPRITES):
    frame, size = SPRITE_KINDS[i % len(SPRITE_KINDS)]
    x, y = _world_xy(i, N_SPRITES, 36.0)
    spr = Craft(
        space,
        frame=frame,
        size=size,
        center=(x, y),
        group="fleet",
        hitbox_shape="auto",
    )
    _fleet.append(spr)

n_vis = max(2, N_SPRITES // 7)
n_park = max(2, N_SPRITES // 7)
_vis_toggle = _fleet[:n_vis]
_park_toggle = _fleet[n_vis:n_vis + n_park]


def _make_shape(i: int):
    x, y = _world_xy(i, N_SHAPES, 40.0)
    kind = i % 6
    color = SHAPE_COLORS[i % len(SHAPE_COLORS)]
    s = 18.0 + (i % 5) * 8.0
    if kind == 0:
        shp = Circle(center=(x, y), radius=s * 0.5, group="geom")
        _bind_shape(shp, home_r=s * 0.5)
    elif kind == 1:
        shp = Rect(center=(x, y), width=s, height=s * 0.65, group="geom")
        _bind_shape(shp, home_w=s, home_h=s * 0.65)
    elif kind == 2:
        shp = Square(center=(x, y), length=s * 0.85, group="geom")
        _bind_shape(shp, home_l=s * 0.85)
    elif kind == 3:
        shp = Ellipse(center=(x, y), width=s * 1.15, height=s * 0.55, group="geom")
        _bind_shape(shp, home_w=s * 1.15, home_h=s * 0.55)
    elif kind == 4:
        shp = RegularPolygon(n=5 + (i % 4), center=(x, y), radius=s * 0.5, group="geom")
        _bind_shape(shp, home_r=s * 0.5)
    else:
        shp = EquilateralTriangle(center=(x, y), radius=s * 0.5, group="geom")
        _bind_shape(shp, home_r=s * 0.5)
    shp.set_color(color)
    shp.fill_alpha = 0.78
    return shp


for i in range(N_SHAPES):
    _geom.append(_make_shape(i))


def _place_sfx():
    camp = Fire(center=(-220, -80), radius=32, style="camp", group="sfx")
    plume = Fire(center=(200, 140), width=28, length=70, style="plume", group="sfx")
    sparks = Sparks(center=(0, 160), radius=26, rate=40, group="sfx")
    glow = GlowSpot(center=(160, -120), radius=52, color="cyan", amount=0.7, group="sfx")
    rain = Rain(center=(-160, 120), width=180, height=220, amount=0.5, group="sfx")
    jet = Jet(origin=(240, -40), angle=200, length=110, width=14, group="sfx")
    for fx in (camp, plume, sparks, glow, rain, jet):
        fx.collidable = True
        _sfx.append(fx)
    _emitters.extend([
        (camp, "camp"),
        (plume, "plume"),
        (sparks, "sparks"),
        (glow, "glow"),
        (rain, "rain"),
        (jet, "jet"),
    ])


_place_sfx()


def _tune_sfx(t: float) -> None:
    for fx, kind in _emitters:
        if not getattr(fx, "is_alive", False):
            continue
        if kind == "camp":
            fx.radius = 26.0 + 10.0 * math.sin(t * 1.4)
            fx.amount = 0.65 + 0.45 * (0.5 + 0.5 * math.sin(t * 0.9))
            fx.speed = 0.8 + 0.7 * (0.5 + 0.5 * math.cos(t * 0.7))
            fill = getattr(fx, "_fill", None)
            if fill is not None:
                if hasattr(fill, "amount"):
                    fill.amount = fx.amount
                if hasattr(fill, "speed"):
                    fill.speed = fx.speed
        elif kind == "plume":
            fx.width = 22.0 + 10.0 * math.sin(t * 1.1)
            fx.length = 55.0 + 28.0 * math.sin(t * 0.85)
            fx.angle = 90.0 + 50.0 * math.sin(t * 0.6)
            fx.amount = 0.7 + 0.4 * (0.5 + 0.5 * math.sin(t * 1.2))
        elif kind == "sparks":
            fx.radius = 20.0 + 12.0 * math.sin(t * 1.6)
            fx.rate = 18.0 + 36.0 * (0.5 + 0.5 * math.sin(t * 1.05))
            fx.center = (40.0 * math.sin(t * 0.4), 160.0 + 30.0 * math.cos(t * 0.35))
        elif kind == "glow":
            fx.radius = 40.0 + 22.0 * math.sin(t * 0.95)
            fx.intensity = 0.35 + 0.7 * (0.5 + 0.5 * math.sin(t * 1.8))
        elif kind == "rain":
            fx.density = 0.25 + 0.55 * (0.5 + 0.5 * math.sin(t * 0.55))
            fx.width = 150.0 + 50.0 * math.sin(t * 0.4)
            fx.height = 180.0 + 60.0 * math.cos(t * 0.32)
            fx.angle = 8.0 * math.sin(t * 0.5)
        elif kind == "jet":
            fx.angle = 200.0 + 55.0 * math.sin(t * 0.75)
            fx.length = 80.0 + 50.0 * (0.5 + 0.5 * math.sin(t * 1.15))
            fx.width = 10.0 + 8.0 * (0.5 + 0.5 * math.cos(t * 0.9))
            fx.amount = 0.7 + 0.5 * (0.5 + 0.5 * math.sin(t * 1.4))


def _drive_camera(t: float) -> None:
    canvas.pan_to(110.0 * math.sin(t * 0.85), 70.0 * math.cos(t * 0.7))
    canvas.zoom_to(1.0 + 0.24 * math.sin(t * 1.05))
    canvas.rotate_to(11.0 * math.sin(t * 0.55))


# ---------------------------------------------------------------------------
# Collision
# ---------------------------------------------------------------------------

@collide_stay("fleet", "geom")
def _hit_sg(me, other, info):
    st.hits_sg += 1


@collide_stay("fleet", "sfx")
def _hit_sx(me, other, info):
    st.hits_sx += 1


@collide_stay("geom", "sfx")
def _hit_gx(me, other, info):
    st.hits_gx += 1


@collide_stay("churn", ["fleet", "geom", "sfx"])
def _hit_ch(me, other, info):
    st.hits_ch += 1


# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------

hud = Text(
    text="",
    top_left=(18, H - 9), font_size=16,
    color=Color(0.92, 0.94, 1.0, 1),
)
hint = Text(
    text="SPACE pause  ·  C colliders  ·  E quality  ·  O cull  ·  R reset cam",
    top_left=(18, H - 35), font_size=13,
    color=Color(0.55, 0.62, 0.75, 1),
)


def _hud_line() -> str:
    n_churn = len(group["churn"])
    n_vis = sum(1 for s in _vis_toggle if s.is_alive and not s.visible)
    n_park = sum(1 for s in _park_toggle if s.is_alive and not s.active)
    hits = int(st.hits_sg) + int(st.hits_sx) + int(st.hits_gx) + int(st.hits_ch)
    return (
        f"live mix  sprites={len(group['fleet'])}  shapes={len(group['geom'])}  "
        f"sfx={len(_sfx)}  churn={n_churn}  hits={hits}  "
        f"hidden={n_vis}  parked={n_park}  "
        f"cam z={canvas.zoom:.2f} r={canvas.rotation:.1f}"
    )


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------

def update(dt):
    if _paused:
        hud.text = _hud_line() + "  PAUSED"
        return
    t = clock.time
    _drive_camera(t)
    _tune_sfx(t)
    if ready("churn", 0.08):
        _spawn_churn()
    if ready("vis", 0.42):
        for s in _vis_toggle:
            if s.is_alive:
                s.visible = not s.visible
    if ready("park", 0.58):
        for s in _park_toggle:
            if s.is_alive:
                s.active = not s.active
    if ready("bg", 2.4):
        _stars.enabled = not _stars.enabled
    hud.text = _hud_line()


def on_key_down(key):
    global _paused, _outlines
    if key == "SPACE":
        _paused = not _paused
    elif key == "C":
        _outlines = not _outlines
        collision.show_colliders(_outlines)
    elif key == "E":
        ladder = ("low", "medium", "high", "max")
        cur = canvas.fx_quality
        name = cur.value if cur is not None else "high"
        i = ladder.index(name) if name in ladder else 2
        canvas.fx_quality = ladder[(i + 1) % 4]
    elif key == "O":
        canvas.cull_offscreen = not canvas.cull_offscreen
    elif key == "R":
        canvas.reset_view()
        canvas.set_origin("center")


# ---------------------------------------------------------------------------
# Bench
# ---------------------------------------------------------------------------

if args.bench:
    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    extra = {
        "n_fleet": 0.0, "n_churn": 0.0, "n_geom": 0.0,
        "hits": 0.0, "n_frames": 0.0,
    }

    def on_frame(framework, recording):
        if not recording:
            return
        extra["n_fleet"] += len(group["fleet"])
        extra["n_churn"] += len(group["churn"])
        extra["n_geom"] += len(group["geom"])
        extra["hits"] += (
            int(st.hits_sg) + int(st.hits_sx) + int(st.hits_gx) + int(st.hits_ch)
        )
        extra["n_frames"] += 1

    install_phase_run(
        fw,
        duration=args.duration,
        warmup=args.warmup,
        stats=stats,
        on_frame=on_frame,
    )

    def _finish(stats_acc):
        print_phase_report(
            f"live mix — n={N_SPRITES} shapes={N_SHAPES} Q={args.quality} "
            f"cull={canvas.cull_offscreen}",
            stats_acc,
        )
        nf = max(1.0, extra["n_frames"])
        print(f"avg fleet:            {extra['n_fleet'] / nf:.1f}")
        print(f"avg shapes:           {extra['n_geom'] / nf:.1f}")
        print(f"avg churn:            {extra['n_churn'] / nf:.1f}")
        print(f"spawned / destroyed:  {int(st.spawned)} / {int(st.destroyed)}")
        total_hits = (
            int(st.hits_sg) + int(st.hits_sx) + int(st.hits_gx) + int(st.hits_ch)
        )
        print(
            f"stay hits (sg/sx/gx/ch): "
            f"{int(st.hits_sg)}/{int(st.hits_sx)}/{int(st.hits_gx)}/{int(st.hits_ch)}"
        )
        print(f"stay hits / frame:    {total_hits / nf:.1f}")
        avg = average_phase_stats(stats_acc)
        print(f"avg work_ms:          {avg['work_ms']:.3f}")
        payload = {
            "n": N_SPRITES,
            "n_shapes": N_SHAPES,
            "quality": args.quality,
            "cull": bool(args.cull),
            "fps": avg["fps"],
            "work_ms": avg["work_ms"],
            "tick_ms": avg["tick_ms"],
            "coll_ms": avg["coll_ms"],
            "flush_ms": avg["flush_ms"],
            "spatial_ms": avg["spatial_ms"],
            "bg_ms": avg["bg_ms"],
            "draw_ms": avg["draw_ms"],
            "post_ms": avg["post_ms"],
            "submit_ms": avg["submit_ms"],
            "hits_sg": int(st.hits_sg),
            "hits_sx": int(st.hits_sx),
            "hits_gx": int(st.hits_gx),
            "hits_ch": int(st.hits_ch),
            "spawned": int(st.spawned),
            "destroyed": int(st.destroyed),
        }
        print(
            f"RESULT_JSON: "
            f'{{"fps": {avg["fps"]:.2f}, "work_ms": {avg["work_ms"]:.4f}, '
            f'"tick_ms": {avg["tick_ms"]:.4f}, "coll_ms": {avg["coll_ms"]:.4f}, '
            f'"spatial_ms": {avg["spatial_ms"]:.4f}, "draw_ms": {avg["draw_ms"]:.4f}}}'
        )
        if args.json_path:
            write_json(args.json_path, payload)
        return payload

    if args.profile:
        pr = cProfile.Profile()
        pr.enable()
        run()
        pr.disable()
        _finish(stats)
        buf = StringIO()
        pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(40)
        print(buf.getvalue())
        buf2 = StringIO()
        pstats.Stats(pr, stream=buf2).sort_stats("tottime").print_stats(25)
        print("--- tottime ---")
        print(buf2.getvalue())
    else:
        run()
        _finish(stats)
else:
    run()
