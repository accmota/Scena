"""Galaga frame-phase bench — instrumentation only (not a product script).

Times tick / collision / flush / draw / post / submit with canvas.framerate = "max" (uncapped)
with optional ablations. Suite runs each ablation in a clean subprocess.

Usage:
  python scripts/_bench_galaga.py --suite
  python scripts/_bench_galaga.py --ablation full
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from math import sin
from random import uniform

ABLATIONS = (
    "full",
    "no_post",
    "no_visuals",
    "no_bg",
    "no_collision",
    "sprites_only",
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ablation", default="full", choices=ABLATIONS)
parser.add_argument("--duration", type=float, default=2.5)
parser.add_argument("--warmup", type=float, default=0.6)
parser.add_argument(
    "--fire-storm",
    action="store_true",
    help="Fast wasp fire (~0.45s) to profile projectile load",
)
parser.add_argument("--suite", action="store_true")
parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
args = parser.parse_args()


def _suite():
    rows = []
    for abl in ABLATIONS:
        p = subprocess.run(
            [
                sys.executable,
                __file__,
                "--worker",
                "--ablation",
                abl,
                "--duration",
                str(args.duration),
                "--warmup",
                str(args.warmup),
            ]
            + (["--fire-storm"] if args.fire_storm else []),
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            print(f"FAIL {abl}:\n{p.stderr[-1500:]}", file=sys.stderr)
            rows.append({"ablation": abl, "error": True})
            continue
        line = [ln for ln in p.stdout.splitlines() if ln.startswith("{")][-1]
        rows.append(json.loads(line))
    print("=== galaga phase bench suite ===")
    print(
        f"{'ablation':<14} {'fps':>7} {'work':>7} {'tick':>6} {'coll':>6} "
        f"{'snap':>6} {'brd':>5} {'nar':>5} {'draw':>6} {'post':>6} "
        f"{'stings':>7} {'bolts':>6} {'prox':>6}"
    )
    for r in rows:
        if r.get("error"):
            print(f"{r['ablation']:<14} ERROR")
            continue
        print(
            f"{r['ablation']:<14} {r['fps']:7.1f} {r['work_ms']:7.2f} "
            f"{r['tick_ms']:6.2f} {r['coll_ms']:6.2f} "
            f"{r.get('coll_snap_ms', 0):6.2f} {r.get('coll_broad_ms', 0):5.2f} "
            f"{r.get('coll_narrow_ms', 0):5.2f} "
            f"{r['draw_ms']:6.2f} {r['post_ms']:6.2f} "
            f"{r.get('avg_stings', 0):7.1f} {r.get('avg_bolts', 0):6.1f} "
            f"{r.get('avg_colliders', 0):6.0f}"
        )
    print(json.dumps({"suite": rows}, indent=2))


if args.suite and not args.worker:
    _suite()
    sys.exit(0)

# --- worker -----------------------------------------------------------------
from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework, callback_if_exists
from scena.process import tick_processes
from scena.state import get_scena_system
from scena.transients import tick_all_transients
from scena.spatial_fx import tick_all_spatial_fx
from OpenGL import GL as _GL
import glfw
import types

W, H = 1000, 800
ABL = args.ablation
use_post = ABL in ("full", "no_visuals", "no_bg", "no_collision")
use_visuals = ABL in ("full", "no_post", "no_bg", "no_collision")
use_bg = ABL in ("full", "no_post", "no_visuals", "no_collision")
use_collision = ABL in ("full", "no_post", "no_visuals", "no_bg")

init(width=W, height=H, title=f"galaga bench {ABL}")
fw = ScenaFramework.get_instance()
fw._compute_window_size = (
    lambda design_w, design_h, window_frac: (int(design_w), int(design_h))
)
canvas.background = (0.02, 0.03, 0.07)
canvas.fx_quality = "high"
if use_post:
    canvas.effects.add(Vignette(amount=0.35))
    canvas.effects.add(Bloom(intensity=0.45))

if use_bg:
    SkyGradient("night")
    Stars(pan_response=0.0, density=0.9, amount=1.0, scroll=(0.0, -28.0))
    Stardust()

space = Sheet("examples/media/shooter/sheet.xml")
space.clip("fly_green", ["enemyGreen1.png", "enemyGreen2.png"], fps=6)
space.clip("fly_red", ["enemyRed1.png", "enemyRed2.png"], fps=6)
space.clip("fly_blue", ["enemyBlue1.png", "enemyBlue2.png"], fps=6)

st.score = 0
player = None
ROWS, COLS = 8, 10
ENEMY_H = 14
COL_GAP = 88
ROW_GAP = 70
FORM_LEFT = (W - (COLS - 1) * COL_GAP) / 2
FORM_TOP = 660
DIVE_CLEARANCE = 230


class Bolt(Sprite):
    def setup(self):
        # Match app_galaga: projectile CheapGlow is commented out.
        pass

    def on_update(self, dt):
        self.move_by(0, 560 * dt)
        if self.center.y > H + 40:
            self.destroy()


class Sting(Sprite):
    def setup(self):
        pass

    def on_update(self, dt):
        self.move_by(0, -400 * dt)
        if self.center.y < -40:
            self.destroy()


class Ship(Sprite):
    def setup(self):
        self.hp = 3
        if use_visuals:
            self.glow = Glow(color="skyblue", radius=14, sigma=7)

    def on_update(self, dt):
        if not self.active:
            return
        self.move_by(0, 0)  # keep hot path warm without requiring input
        x = self.center.x
        if x < 40:
            self.center.x = 40
        elif x > W - 40:
            self.center.x = W - 40
        # Auto-fire so collision / bolt visuals exercise during bench
        if ready("fire", 0.22):
            _spawn(
                Bolt,
                space,
                frame="laserBlue02.png",
                height=28,
                center=(self.center.x, self.center.y + 28),
                group="bolt",
            )

    def arm_shield(self):
        self.tag("shielded")
        if use_visuals:
            # Glow is a sticky stamp; drop it so the shield replaces it (one look at a time).
            self.glow = None
            self.visual = Shield(style="bubble", amount=1.1)
        self.after(10.0, self.drop_shield, name="shield")

    def drop_shield(self):
        self.untag("shielded")
        if self.active and use_visuals:
            self.visual = None
            self.glow = Glow(color="skyblue", radius=14, sigma=7)


class Wasp(Sprite):
    def setup(self):
        self.hp = 2
        # Match app_galaga: no formation Halo (logic stress, not look stress).

    def on_update(self, dt):
        if self.mode == self.formation:
            self.center.x = self.slot_x + sin(clock.time * 2.2 + self.slot_x * 0.01) * 14

    def shoot(self):
        _spawn(
            Sting,
            space,
            frame="fire06.png",
            height=18,
            center=(self.center.x, self.center.y - 12),
            group="sting",
        )

    def entering(self):
        self.center = (self.slot_x, H + 60)
        self.fade_in(0.35)
        self.move_to(self.slot_x, self.slot_y, time=1.0, ease="ease_out", then=self.formation)

    def formation(self):
        # Default 2.4s matches app; --fire-storm stresses projectile / Glow load.
        self._fire = every(0.45 if args.fire_storm else 2.4, self.shoot, name="fire")
        self._dive_timer = after(uniform(2.5, 7.0), then=self.diving)

    @exit_mode(formation)
    def formation_exit(self):
        for name in ("_fire", "_dive_timer"):
            h = getattr(self, name, None)
            if h is not None:
                h.cancel()
                setattr(self, name, None)

    async def diving(self):
        # Match app_galaga dive looks (only a few divers at a time).
        if use_visuals:
            self.tail = Tail(angle=270, size=1.2, color="tomato")
            self.pulse_outline(color="tomato", duration=0.3)
        aim_x = player.center.x
        aim_y = player.center.y + DIVE_CLEARANCE
        await self.move_to(aim_x, aim_y, time=0.7, ease="ease_in")
        self.shoot()
        await wait(0.12)
        self.shoot()
        side = 70 if aim_x < self.slot_x else -70
        await self.move_to(aim_x + side, aim_y + 40, time=0.28)
        if use_visuals:
            self.tail = None
            self.visual = Halo(style="soft", color="sea green")
        await self.move_to(self.slot_x, self.slot_y, time=0.85, ease="ease_out")
        self.mode = self.formation

    def dying(self):
        self.untag("wasp")
        st.score += 100
        x, y = self.center.x, self.center.y
        canvas.burst_at(x, y, radius=40)
        fx = Sparks(center=(x, y), radius=32)
        after(0.55, fx.destroy)
        self.dissolve_out(0.3, on_done=self.destroy)


class Director(Entity):
    def setup(self):
        self.wave = 0
        self.mode = self.directing

    async def directing(self):
        while True:
            self.start_wave()
            await until(lambda: len(group["wasp"]) == 0)
            await wait(1.4)

    def start_wave(self):
        self.wave += 1
        clips = ("fly_green", "fly_red", "fly_blue")
        for row in range(ROWS):
            for col in range(COLS):
                clip = clips[(row + col) % 3]
                slot_x = FORM_LEFT + col * COL_GAP
                slot_y = FORM_TOP - row * ROW_GAP
                w = Wasp(
                    space,
                    height=ENEMY_H,
                    center=(slot_x, slot_y),
                    group="wasp",
                    hitbox_shape="auto",
                )
                w.play(clip)
                w.slot_x, w.slot_y = slot_x, slot_y
                w.mode = w.entering


player = Ship(
    space,
    frame="playerShip1_blue.png",
    height=52,
    center=(W / 2, 70),
    group="player",
    hitbox_shape="ellipse",
)

hud = Text(text="", top_left=(20, H - 36), font_size=20)
hud["text"] @= (
    lambda: f"Score {st.score}   HP {player.hp if player.active else 0}"
    + ("   SHIELD" if player.tagged("shielded") else "")
)

director = Director()


@every(10.0, name="powerup")
def drop_shield_token():
    if not player.active:
        return
    Sprite(
        space,
        frame="powerupBlue_shield.png",
        size=36,
        center=(uniform(80, W - 80), H - 40),
        group="powerup",
        visual=Beat(amount=0.12, speed=1.4) if use_visuals else None,
    )


def update(dt):
    for token in group["powerup"]:
        token.move_by(0, -140 * dt)
        token.angle = clock.time * 90
        if token.center.y < -40:
            token.destroy()


if use_collision:

    @collide("bolt", "wasp")
    def hit_wasp(bolt, wasp):
        bolt.destroy()
        wasp.hp -= 1
        wasp.flash(0.1)
        if wasp.hp <= 0:
            wasp.mode = wasp.dying

    @collide("sting", "player")
    def hit_player(sting, ship):
        sting.destroy()
        if ship.tagged("hurt"):
            return
        if ship.tagged("shielded"):
            ship.pulse_outline(color="skyblue", duration=0.25)
            return
        ship.hp -= 1
        ship.tag("hurt")
        ship.blink(0.7)
        canvas.shake(8.0)
        canvas.flash(0.55)
        ship.after(0.7, lambda: ship.untag("hurt"), name="hurt")
        if False and ship.hp <= 0:  # match app_galaga: invincible for perf tests
            x, y = ship.center.x, ship.center.y
            fx = Sparks(center=(x, y), radius=40)
            after(0.8, fx.destroy)
            ship.dissolve_out(0.4, on_done=lambda: setattr(ship, "active", False))

    @collide("player", "powerup")
    def take_shield(ship, token):
        token.pop()
        token.destroy()
        ship.arm_shield()
        canvas.flash(0.35)


canvas.framerate = "max"

# Open the OS window before patching run() — ``run()`` would open it too, but
# doing it here makes hang diagnosis easier and avoids re-entry surprises.
if not fw._windowed:
    fw.open_window()
canvas.framerate = "max"

stats = {
    "tick_ms": 0.0,
    "coll_ms": 0.0,
    "flush_ms": 0.0,
    "transient_ms": 0.0,
    "spatial_ms": 0.0,
    "bg_ms": 0.0,
    "draw_ms": 0.0,
    "post_ms": 0.0,
    "submit_ms": 0.0,
    "work_ms": 0.0,
    "frames": 0,
    "n_wasps": 0,
    "n_stings": 0,
    "n_bolts": 0,
    "n_colliders": 0,
    "coll_prims": 0,
    "coll_narrow": 0,
    "coll_pairs": 0,
    "coll_sat": 0,
    "coll_snap_ms": 0.0,
    "coll_broad_ms": 0.0,
    "coll_narrow_ms": 0.0,
    "spawn_ms": 0.0,
    "spawn_n": 0,
    "destroy_ms": 0.0,
    "destroy_n": 0,
    "fid_ms": 0.0,
    "pull_true": 0,
    "scene_n": 0,
}

# Per-spawn / destroy wall time (constructor + teardown of full Sprite actors).
_spawn_t = [0.0, 0]
_destroy_t = [0.0, 0]


def _spawn(cls, *a, **k):
    t0 = time.perf_counter()
    obj = cls.__new__(cls)
    cls.__init__(obj, *a, **k)
    _spawn_t[0] += (time.perf_counter() - t0) * 1000.0
    _spawn_t[1] += 1
    return obj


def _wrap_destroy(cls):
    orig = cls.destroy

    def wrapped(self, *a, **k):
        t0 = time.perf_counter()
        out = orig(self, *a, **k)
        _destroy_t[0] += (time.perf_counter() - t0) * 1000.0
        _destroy_t[1] += 1
        return out

    cls.destroy = wrapped


_wrap_destroy(Sprite)

# Live-count buckets: mean work vs projectile pressure.
_bucket_work = {}
_bucket_n = {}


def instrumented_run(self):
    self._running = True
    callback_if_exists(self, "setup", self._canvas)
    self.frame_count = 0
    canvas.framerate = "max"
    t_start = time.perf_counter()
    recording = False

    while self._running and not glfw.window_should_close(self._window):
        ss = get_scena_system()
        if ss is not None:
            ss.begin_frame_batch()
        try:
            current_time = time.perf_counter()
            elapsed = current_time - t_start
            if elapsed >= args.warmup:
                recording = True
            if elapsed >= args.warmup + args.duration:
                self._running = False
                break

            self.clock._tick(current_time)

            # Match production: with post FX, paint background once after update.
            bg_dt = 0.0
            if not self._needs_scene_rt():
                t_bg0 = time.perf_counter()
                self._draw_background(self._drawing_canvas)
                self._apply_view_transform()
                bg_dt = (time.perf_counter() - t_bg0) * 1000.0

            glfw.poll_events()
            callback_if_exists(self, "update", clock.dt, self._canvas)

            t0 = time.perf_counter()
            tick_processes()
            tick_dt = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            if self.collision_system is not None:
                self.collision_system.step()
            coll_dt = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            if ss is not None:
                ss.flush()
            flush_dt = (time.perf_counter() - t0) * 1000.0
        finally:
            if ss is not None:
                ss.end_frame_batch()

        t0 = time.perf_counter()
        tick_all_transients()
        tr_dt = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        tick_all_spatial_fx()
        sx_dt = (time.perf_counter() - t0) * 1000.0

        post_dt = 0.0
        draw_dt = 0.0
        if self._needs_scene_rt():
            _GL.glViewport(0, 0, self.fb_width, self.fb_height)
            self._was_using_post = True
            self._prefer_scene_blit = True
            scene_surf = self._ensure_scene_surface()
            scene_canvas = scene_surf.getCanvas()
            t_bg0 = time.perf_counter()
            self._draw_background(scene_canvas)
            self._apply_view_transform(scene_canvas)
            bg_dt += (time.perf_counter() - t_bg0) * 1000.0
            top_exempt = self._top_exempt_from_post()
            t0 = time.perf_counter()
            self._draw_scene_to(scene_canvas, exclude_top=top_exempt)
            draw_dt = (time.perf_counter() - t0) * 1000.0
            scene_image = scene_surf.makeImageSnapshot()
            self._clear_background_fast(self._drawing_canvas)
            t0 = time.perf_counter()
            if self._post_draw_live():
                callback_if_exists(self, "post_draw", self._drawing_canvas, scene_image)
            else:
                self.post_fx_stack._render(
                    self._drawing_canvas, scene_image, fw=self, t=self.clock.time
                )
            post_dt = (time.perf_counter() - t0) * 1000.0
            self._apply_view_transform()
            if top_exempt:
                self._draw_top_layer(self._drawing_canvas)
        else:
            _GL.glViewport(0, 0, self.fb_width, self.fb_height)
            t = self.clock.time if self.clock is not None else None
            t0 = time.perf_counter()
            self._scena_draw.draw(t=t)
            draw_dt = (time.perf_counter() - t0) * 1000.0

        self._apply_view_transform(camera=False)
        self.widget_manager.draw(self._drawing_canvas)

        t0 = time.perf_counter()
        self._drawing_surface.flushAndSubmit()
        sub_dt = (time.perf_counter() - t0) * 1000.0
        glfw.swap_buffers(self._window)
        work = (time.perf_counter() - current_time) * 1000.0
        self.frame_count += 1

        if recording:
            stats["tick_ms"] += tick_dt
            stats["coll_ms"] += coll_dt
            stats["flush_ms"] += flush_dt
            stats["transient_ms"] += tr_dt
            stats["spatial_ms"] += sx_dt
            stats["bg_ms"] += bg_dt
            stats["draw_ms"] += draw_dt
            stats["post_ms"] += post_dt
            stats["submit_ms"] += sub_dt
            stats["work_ms"] += work
            stats["frames"] += 1
            stats["n_wasps"] += len(group["wasp"])
            stats["n_stings"] += len(group["sting"])
            stats["n_bolts"] += len(group["bolt"])
            if self.collision_system is not None:
                ls = getattr(self.collision_system, "last_stats", None) or {}
                stats["n_colliders"] += int(ls.get("proxies", 0) or 0)
                stats["coll_prims"] += int(ls.get("prims", 0) or 0)
                stats["coll_narrow"] += int(ls.get("narrow", 0) or 0)
                stats["coll_pairs"] += int(ls.get("proxy_pairs", 0) or 0)
                stats["coll_sat"] += int(ls.get("sat", 0) or 0)
                stats["coll_snap_ms"] += float(ls.get("ms_snapshot", 0.0) or 0.0)
                stats["coll_broad_ms"] += float(ls.get("ms_broad", 0.0) or 0.0)
                stats["coll_narrow_ms"] += float(ls.get("ms_narrow", 0.0) or 0.0)
            n_proj = len(group["sting"]) + len(group["bolt"])
            bkey = int(n_proj // 25) * 25
            _bucket_work[bkey] = _bucket_work.get(bkey, 0.0) + work
            _bucket_n[bkey] = _bucket_n.get(bkey, 0) + 1

    n_pull = 0
    n_scene = 0
    for layer_name in self._scena_draw.registry.layers:
        layer = self._scena_draw.registry.layers[layer_name]
        for obj in list(layer._objects):
            n_scene += 1
            try:
                if obj._requires_pull_invalidate():
                    n_pull += 1
            except Exception:
                if getattr(obj, "_needs_pull_invalidate", False):
                    n_pull += 1
    stats["pull_true"] = n_pull
    stats["scene_n"] = n_scene


fw.run = types.MethodType(instrumented_run, fw)
run()

n = max(1, stats["frames"])
hitbox_kinds = {}
if fw.collision_system is not None:
    for c in fw.collision_system._colliders:
        for shape in c.shapes:
            kind = getattr(shape, "_hitbox_kind", None) or "?"
            extra = ""
            if getattr(shape, "_hitbox_poly", ()):
                extra = "+poly"
            elif getattr(shape, "_hitbox_circles", ()) or getattr(shape, "_hitbox_circle", None):
                extra = "+circ"
            elif getattr(shape, "_hitbox_ellipses", ()) or getattr(shape, "_hitbox_ellipse", None):
                extra = "+ell"
            elif getattr(shape, "_hitbox_boxes", ()):
                extra = "+box"
            key = f"{kind}{extra}"
            hitbox_kinds[key] = hitbox_kinds.get(key, 0) + 1

buckets = []
for k in sorted(_bucket_n):
    buckets.append({
        "proj_lo": k,
        "frames": _bucket_n[k],
        "work_ms": _bucket_work[k] / _bucket_n[k],
    })

out = {
    "ablation": ABL,
    "frames": n,
    "fps": n / args.duration,
    "work_ms": stats["work_ms"] / n,
    "tick_ms": stats["tick_ms"] / n,
    "coll_ms": stats["coll_ms"] / n,
    "flush_ms": stats["flush_ms"] / n,
    "transient_ms": stats["transient_ms"] / n,
    "spatial_ms": stats["spatial_ms"] / n,
    "bg_ms": stats["bg_ms"] / n,
    "draw_ms": stats["draw_ms"] / n,
    "post_ms": stats["post_ms"] / n,
    "submit_ms": stats["submit_ms"] / n,
    "avg_wasps": stats["n_wasps"] / n,
    "avg_stings": stats["n_stings"] / n,
    "avg_bolts": stats["n_bolts"] / n,
    "avg_colliders": stats["n_colliders"] / n,
    "avg_prims": stats["coll_prims"] / n,
    "avg_narrow": stats["coll_narrow"] / n,
    "avg_sat": stats["coll_sat"] / n,
    "avg_proxy_pairs": stats["coll_pairs"] / n,
    "coll_snap_ms": stats["coll_snap_ms"] / n,
    "coll_broad_ms": stats["coll_broad_ms"] / n,
    "coll_narrow_ms": stats["coll_narrow_ms"] / n,
    "spawn_ms_frame": _spawn_t[0] / n,
    "spawn_n_frame": _spawn_t[1] / n,
    "destroy_ms_frame": _destroy_t[0] / n,
    "destroy_n_frame": _destroy_t[1] / n,
    "hitbox_kinds": hitbox_kinds,
    "proj_buckets": buckets,
    "fire_storm": bool(args.fire_storm),
    "pull_invalidate_true": stats["pull_true"],
    "scene_n": stats["scene_n"],
}
print(json.dumps(out))
