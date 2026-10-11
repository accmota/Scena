"""CPU stress arena — realistic demanding 2D game for Scena framework benches.

Not a showcase; exists to exercise:
  * mass Sprite + Shape actors with per-entity ``on_update``
  * mix of unlinked pose writes (A2) and ``@=`` formula-driven aim
  * dense named ``every()`` / ``after()`` / async modes (scheduler)
  * several ``@collide`` tag pairs + high spawn/destroy churn
  * HUD / score / combo via ``@=`` and ``@when`` / ``@on_change``
  * continuous Sprite / Shape rotation (collision proxy under spin)
  * optional ``--firestorm`` mid-run spawn / fire-rate burst

Minimal canvas post (no Bloom stack) — CPU-focused. GPU/render opts are out of scope.

Usage
-----
    python scripts/bench/cpu_mix.py
    python scripts/bench/cpu_mix.py --bench --duration 2 --warmup 0.5
    python scripts/bench/cpu_mix.py --bench --n 200 --profile
    python scripts/bench/cpu_mix.py --bench --n 180 --firestorm --duration 3

Controls (interactive): LEFT/RIGHT or A/D, SPACE fire, R restart.
"""
from __future__ import annotations

import argparse
import cProfile
import math
import os
import pstats
import sys
from io import StringIO
from random import Random, uniform

# Parse args before importing scena so --help is fast and workers stay clean.
_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--n", type=int, default=180,
                     help="enemy count at wave start (default 180)")
_parser.add_argument("--bench", action="store_true",
                     help="uncapped FPS, phase-time, then exit")
_parser.add_argument("--duration", type=float, default=2.0,
                     help="measured seconds when --bench (default 2)")
_parser.add_argument("--warmup", type=float, default=0.5,
                     help="warmup seconds excluded from stats (default 0.5)")
_parser.add_argument("--profile", action="store_true",
                    help="with --bench, also print cProfile top functions")
_parser.add_argument("--firestorm", action="store_true",
                    help="with --bench, mid-run fire-rate / spawn burst window")
_parser.add_argument("--seed", type=int, default=42)
_parser.add_argument(
    "--json", dest="json_path", default=None,
    help="write phase-timing JSON (with --bench)",
)
args, _ = _parser.parse_known_args()

from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import set_watchdog  # noqa: E402

# Shared harness lives next to this script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from perf_common import (  # noqa: E402
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
    print_phase_report,
    write_json,
)

W, H = 1000, 800
init(width=W, height=H, title="Stress Arena — Scena CPU bench")
canvas.background = (0.04, 0.05, 0.09)
# Keep FX minimal — this is a CPU stress, not a GPU one.
set_fx_auto(False)
canvas.fx_quality = "medium"

rng = Random(args.seed)
set_watchdog(False)

space = Sheet("examples/media/shooter/sheet.xml")
space.clip("fly_green", ["enemyGreen1.png", "enemyGreen2.png"], fps=6)
space.clip("fly_red", ["enemyRed1.png", "enemyRed2.png"], fps=6)
space.clip("fly_blue", ["enemyBlue1.png", "enemyBlue2.png"], fps=6)

st.score = 0
st.combo = 0
st.wave = 0
st.kills = 0
st.milestones = 0
st.firestorm = 0  # 1 during --firestorm burst window (bench only)

N_ENEMIES = max(40, int(args.n))
COLS = 15
ROWS = max(3, (N_ENEMIES + COLS - 1) // COLS)
COL_GAP = (W - 80) / max(1, COLS - 1)
ROW_GAP = 48
FORM_LEFT = 40
FORM_TOP = H - 80

player = None  # set below


# --- projectiles -------------------------------------------------------------

class Bolt(Sprite):
    """Player shot — unlinked pose (A2 fast path)."""

    def setup(self):
        self.angle = 90.0  # heading +y

    def on_update(self, dt):
        self.move_by(0, 620 * dt)
        if self.center.y > H + 40:
            self.destroy()


class Shard(Circle):
    """Enemy shape projectile — stresses Shape collision + construct churn."""

    def setup(self):
        self.set_color("tomato")
        self.fill_alpha = 0.85
        self.vx = 0.0
        self.vy = -200.0

    def on_update(self, dt):
        self.move_by(self.vx * dt, self.vy * dt)
        # Orient along velocity (Circle rotation still bumps collision epoch).
        if self.vx or self.vy:
            self.angle = math.degrees(math.atan2(self.vy, self.vx))
        x, y = self.center.x, self.center.y
        if x < -40 or x > W + 40 or y < -40 or y > H + 40:
            self.destroy()


class Sting(Sprite):
    """Enemy sprite projectile."""

    def setup(self):
        self.vx = 0.0
        self.vy = -280.0

    def on_update(self, dt):
        self.move_by(self.vx * dt, self.vy * dt)
        if self.vx or self.vy:
            self.angle = math.degrees(math.atan2(self.vy, self.vx))
        x, y = self.center.x, self.center.y
        if x < -40 or x > W + 40 or y < -40 or y > H + 40:
            self.destroy()


# --- actors ------------------------------------------------------------------

class Ship(Sprite):
    def setup(self):
        self.hp = 99 if args.bench else 5
        self._aim = Point(x=self.center.x, y=self.center.y + 200)
        # Formula-driven aim angle (linked path — not A2).
        self.aim_angle = 0.0
        self["aim_angle"] @= lambda: math.degrees(
            math.atan2(
                self._aim.y - self.center.y,
                self._aim.x - self.center.x,
            )
        )

    def on_update(self, dt):
        if not self.active:
            return
        dx = 0.0
        if keyp("LEFT") or keyp("A"):
            dx -= 380 * dt
        if keyp("RIGHT") or keyp("D"):
            dx += 380 * dt
        # Bench: auto-strafe so motion stays busy without input.
        if args.bench:
            dx = math.sin(clock.time * 2.4) * 280 * dt
        self.move_by(dx, 0)
        x = self.center.x
        if x < 40:
            self.center.x = 40
        elif x > W - 40:
            self.center.x = W - 40
        self._aim.x = self.center.x + math.sin(clock.time * 3.1) * 40
        self._aim.y = self.center.y + 220
        # Touch the linked attribute so pull-resolve stays on the hot path.
        _ = self.aim_angle
        rate = 0.09 if args.bench else 0.14
        if ready("fire", rate) and (args.bench or keyp("SPACE")):
            Bolt(
                space,
                frame="laserBlue02.png",
                height=26,
                center=(self.center.x, self.center.y + 26),
                group="bolt",
            )


class Drone(Sprite):
    """Enemy with named every-slot fire + formation sway + occasional dive mode."""

    def setup(self):
        self.hp = 2
        self.slot_x = self.center.x
        self.slot_y = self.center.y
        self.kind = "sprite"
        # Per-entity fire timer (named replace slot — supported dense pattern).
        every(uniform(1.6, 2.8), self.volley, name="fire")

    def volley(self):
        if not self.active or not player or not player.active:
            return
        if self.mode not in (self.formation, None):
            return
        px, py = player.center.x, player.center.y
        cx, cy = self.center.x, self.center.y
        dx, dy = px - cx, py - cy
        dist = math.hypot(dx, dy) or 1.0
        speed = 280.0
        burst = 3 if int(st.firestorm) else 1
        for i in range(burst):
            spread = (i - (burst - 1) * 0.5) * 0.12
            sx = dx / dist * math.cos(spread) - dy / dist * math.sin(spread)
            sy = dx / dist * math.sin(spread) + dy / dist * math.cos(spread)
            sting = Sting(
                space,
                frame="fire06.png",
                height=16,
                center=(cx, cy - 10),
                group="sting",
                hitbox_shape="rect",
                hitbox_scale=0.9,
            )
            sting.vx = sx * speed
            sting.vy = sy * speed
            sting.angle = math.degrees(math.atan2(sy, sx))
            # Also spawn a Shape shard every other fire for mixed collision.
            if int(self.slot_x) % 2 == 0:
                sh = Shard(center=(cx, cy - 8), radius=5, group="shard")
                sh.vx = sx * (speed * 0.7)
                sh.vy = sy * (speed * 0.7)
                sh.angle = math.degrees(math.atan2(sh.vy, sh.vx))

    def on_update(self, dt):
        # Formation sway — unlinked center.x writes (A2).
        if self.mode == self.formation or self.mode is None:
            t = clock.time
            self.center.x = self.slot_x + math.sin(t * 2.0 + self.slot_x * 0.01) * 12
            # Slow continuous spin — exercises rotating Sprite hitbox proxy path.
            self.angle = t * 25.0 + self.slot_x * 0.1
        if int(st.firestorm) and (self.mode == self.formation or self.mode is None):
            # Extra mid-burst volleys on top of the named every() timer.
            if int(clock.time * 10 + self.slot_x) % 17 == 0:
                self.volley()

    @on_mode
    def formation(self):
        if uniform(0, 1) < 0.08:
            self._dive_timer = after(uniform(1.5, 5.0), then=self.diving)

    @exit_mode(formation)
    def formation_exit(self):
        h = getattr(self, "_dive_timer", None)
        if h is not None:
            h.cancel()
            self._dive_timer = None

    @on_mode
    async def diving(self):
        if not player or not player.active:
            self.mode = self.formation
            return
        aim_x = player.center.x + uniform(-40, 40)
        aim_y = max(120.0, player.center.y + 160)
        await self.move_to(aim_x, aim_y, time=0.55, ease="ease_in")
        self.volley()
        await wait(0.1)
        await self.move_to(self.slot_x, self.slot_y, time=0.7, ease="ease_out")
        self.mode = self.formation

    @on_mode
    def dying(self):
        self.untag("drone")
        st.score += 50
        st.kills += 1
        st.combo += 1
        x, y = self.center.x, self.center.y
        # Short-lived marker — construct churn under kill waves.
        mark = Circle(center=(x, y), radius=4, group="fx")
        mark.set_color("gold")
        mark.fill_alpha = 0.7
        after(0.35, mark.destroy)
        self.destroy()


class Rock(RegularPolygon):
    """Shape-body enemy — stresses geometry + collision without Sprite blit."""

    def setup(self):
        self.hp = 3
        self.slot_x = self.center.x
        self.slot_y = self.center.y
        self.set_color("orange")
        self.fill_alpha = 0.75
        every(uniform(2.0, 3.5), self.lob, name="fire")

    def lob(self):
        if not self.active or not player or not player.active:
            return
        px, py = player.center.x, player.center.y
        cx, cy = self.center.x, self.center.y
        dx, dy = px - cx, py - cy
        dist = math.hypot(dx, dy) or 1.0
        burst = 3 if int(st.firestorm) else 1
        for i in range(burst):
            spread = (i - (burst - 1) * 0.5) * 0.15
            sx = dx / dist * math.cos(spread) - dy / dist * math.sin(spread)
            sy = dx / dist * math.sin(spread) + dy / dist * math.cos(spread)
            sh = Shard(center=(cx, cy), radius=6, group="shard")
            sh.vx = sx * 220
            sh.vy = sy * 220
            sh.angle = math.degrees(math.atan2(sh.vy, sh.vx))
            sh.set_color("orange")

    def on_update(self, dt):
        self.angle = clock.time * 40 + self.slot_x
        t = clock.time
        self.center.x = self.slot_x + math.sin(t * 1.4 + self.slot_y * 0.02) * 10
        if int(st.firestorm) and int(t * 8 + self.slot_x) % 11 == 0:
            self.lob()

    def die(self):
        self.untag("rock")
        st.score += 75
        st.kills += 1
        st.combo += 1
        self.destroy()


class Director(Entity):
    def setup(self):
        self.divers = 0
        self.mode = self.directing

    @on_mode
    async def directing(self):
        while True:
            self.start_wave()
            await until_empty("drone")
            # Rocks may linger; clear them between waves under bench.
            if args.bench:
                group["rock"].destroy()
            await wait(0.8 if args.bench else 1.5)

    def start_wave(self):
        st.wave += 1
        st.combo = 0
        clips = ("fly_green", "fly_red", "fly_blue")
        n_sprite = int(N_ENEMIES * 0.75)
        n_rock = N_ENEMIES - n_sprite
        i = 0
        for row in range(ROWS):
            for col in range(COLS):
                if i >= n_sprite:
                    break
                slot_x = FORM_LEFT + col * COL_GAP
                slot_y = FORM_TOP - row * ROW_GAP
                clip = clips[(row + col) % 3]
                d = Drone(
                    space,
                    height=16,
                    center=(slot_x, slot_y),
                    group="drone",
                    hitbox_shape="auto",
                )
                d.play(clip)
                d.slot_x, d.slot_y = slot_x, slot_y
                d.mode = d.formation
                i += 1
            if i >= n_sprite:
                break
        for k in range(n_rock):
            slot_x = FORM_LEFT + (k % COLS) * COL_GAP + 20
            slot_y = FORM_TOP - (ROWS + 1 + k // COLS) * ROW_GAP
            Rock(
                n=5,
                radius=14,
                center=(slot_x, slot_y),
                group="rock",
            )


# --- scene -------------------------------------------------------------------

player = Ship(
    space,
    frame="playerShip1_blue.png",
    height=48,
    center=(W / 2, 70),
    group="player",
    hitbox_shape="ellipse",
)

hud = Text(text="", top_left=(16, H - 11), font_size=18)
hud["text"] @= (
    lambda: (
        f"Score {st.score}  Wave {st.wave}  Combo {st.combo}  "
        f"Kills {st.kills}  HP {player.hp if player.active else 0}"
    )
)

director = Director()


# Reactive achievement / combo observers (events.py path).
@when(lambda: int(st.combo) >= 10)
def combo_milestone():
    st.milestones += 1
    st.combo = 0


@on_change(st["kills"])
def on_kill(value):
    # Cheap side effect — keeps on_change on the hot path under churn.
    if int(value) > 0 and int(value) % 25 == 0:
        st.score += 100


@collide("bolt", "drone")
def hit_drone(bolt, drone):
    bolt.destroy()
    drone.hp -= 1
    if drone.hp <= 0:
        drone.mode = drone.dying


@collide("bolt", "rock")
def hit_rock(bolt, rock):
    bolt.destroy()
    rock.hp -= 1
    if rock.hp <= 0:
        rock.die()


@collide("sting", "player")
def hit_player_sting(sting, ship):
    sting.destroy()
    if args.bench:
        return
    ship.hp -= 1
    if ship.hp <= 0:
        ship.active = False


@collide("shard", "player")
def hit_player_shard(shard, ship):
    shard.destroy()
    if args.bench:
        return
    ship.hp -= 1
    if ship.hp <= 0:
        ship.active = False


def on_key_down(key):
    if key == "R":
        for name in ("drone", "rock", "bolt", "sting", "shard", "fx"):
            group[name].destroy()
        st.score = 0
        st.combo = 0
        st.kills = 0
        st.wave = 0
        player.hp = 99 if args.bench else 5
        player.center = (W / 2, 70)
        player.active = True
        player.visible = True
        director.mode = director.directing


canvas.framerate = "max"

if args.bench:
    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    burst_stats = empty_phase_stats() if args.firestorm else None
    # When firestorming, ensure the recording window covers the burst.
    duration = max(args.duration, 3.0) if args.firestorm else args.duration
    burst_window = (0.6, 1.8) if args.firestorm else None
    extra = {
        "n_drone": 0.0, "n_proj": 0.0, "n_frames": 0.0,
        "burst_drone": 0.0, "burst_proj": 0.0, "burst_frames": 0.0,
    }
    _firestorm_spawned = {"done": False}

    def on_frame(framework, recording):
        if not recording:
            st.firestorm = 0
            return
        in_burst = bool(getattr(framework, "_bench_in_burst", False))
        st.firestorm = 1 if (args.firestorm and in_burst) else 0
        # One-shot dump of short-lived enemies at burst start.
        if args.firestorm and in_burst and not _firestorm_spawned["done"]:
            _firestorm_spawned["done"] = True
            for k in range(40):
                slot_x = FORM_LEFT + (k % COLS) * COL_GAP
                slot_y = FORM_TOP + 40 + (k // COLS) * 18
                d = Drone(
                    space,
                    height=14,
                    center=(slot_x, slot_y),
                    group="drone",
                    hitbox_shape="auto",
                )
                d.play(("fly_green", "fly_red", "fly_blue")[k % 3])
                d.slot_x, d.slot_y = slot_x, slot_y
                d.mode = d.formation
                after(1.2, d.destroy)
        n_e = len(group["drone"]) + len(group["rock"])
        n_p = len(group["bolt"]) + len(group["sting"]) + len(group["shard"])
        extra["n_drone"] += n_e
        extra["n_proj"] += n_p
        extra["n_frames"] += 1
        if in_burst:
            extra["burst_drone"] += n_e
            extra["burst_proj"] += n_p
            extra["burst_frames"] += 1

    install_phase_run(
        fw,
        duration=duration,
        warmup=args.warmup,
        stats=stats,
        on_frame=on_frame,
        burst_window=burst_window,
        burst_stats=burst_stats,
    )

    def _print_extras(label_stats, prefix=""):
        n = max(1.0, label_stats)
        print(f"{prefix}avg enemies:          {extra['n_drone'] / max(1.0, extra['n_frames']):.1f}")
        print(f"{prefix}avg projectiles:      {extra['n_proj'] / max(1.0, extra['n_frames']):.1f}")

    if args.profile:
        pr = cProfile.Profile()
        pr.enable()
        run()
        pr.disable()
        print_phase_report("Stress Arena — phase timing", stats)
        _print_extras(extra["n_frames"])
        if burst_stats is not None and burst_stats.get("frames", 0) > 0:
            print_phase_report("Stress Arena — firestorm burst window", burst_stats)
            bf = max(1.0, extra["burst_frames"])
            print(f"burst avg enemies:    {extra['burst_drone'] / bf:.1f}")
            print(f"burst avg projectiles:{extra['burst_proj'] / bf:.1f}")
        buf = StringIO()
        pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(40)
        print(buf.getvalue())
        buf2 = StringIO()
        pstats.Stats(pr, stream=buf2).sort_stats("tottime").print_stats(25)
        print("--- tottime ---")
        print(buf2.getvalue())
    else:
        run()
        print_phase_report("Stress Arena — phase timing", stats)
        _print_extras(extra["n_frames"])
        if burst_stats is not None and burst_stats.get("frames", 0) > 0:
            print_phase_report("Stress Arena — firestorm burst window", burst_stats)
            bf = max(1.0, extra["burst_frames"])
            print(f"burst avg enemies:    {extra['burst_drone'] / bf:.1f}")
            print(f"burst avg projectiles:{extra['burst_proj'] / bf:.1f}")
        avg = average_phase_stats(stats)
        print(f"avg work_ms:          {avg['work_ms']:.3f}")
        payload = {
            "n": args.n,
            "seed": args.seed,
            "fps": avg["fps"],
            "work_ms": avg["work_ms"],
            "tick_ms": avg["tick_ms"],
            "coll_ms": avg["coll_ms"],
            "flush_ms": avg["flush_ms"],
            "draw_ms": avg["draw_ms"],
            "submit_ms": avg["submit_ms"],
            "present_ms": avg["present_ms"],
            "frames": avg["frames"],
        }
        print(
            f"RESULT_JSON: "
            f'{{"fps": {avg["fps"]:.2f}, "work_ms": {avg["work_ms"]:.4f}, '
            f'"tick_ms": {avg["tick_ms"]:.4f}, "coll_ms": {avg["coll_ms"]:.4f}, '
            f'"flush_ms": {avg["flush_ms"]:.4f}, "draw_ms": {avg["draw_ms"]:.4f}}}'
        )
        if args.json_path:
            write_json(args.json_path, payload)
else:
    run()
