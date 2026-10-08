"""
resolve.py — smoke: collision resolution API.

Zones
-----
Left:  bouncing balls (different bounce= values) on a STATIC floor
Mid:   mixed masses head-on; resolve / unresolve toggle
Right: ball vs STATIC wall; draggable STATIC sprite to shove things

Controls
--------
  drag      any shape or the hand sprite
  R         toggle resolve(balls, balls) on / off
  SPACE     toggle collider outlines
  1 / 2 / 3 reset ball speeds for bounce demo

Usage
-----
    python scripts/smoke/resolve.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.78, title="Smoke — collision resolve")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Collision resolve",
    expect="balls bounce; wall stops; masses split; hand (STATIC) shoves on drag",
    keys="drag  ·  R unresolve balls  ·  SPACE outlines  ·  1/2/3 reset speeds",
    status="drag the gold hand into the balls…",
)

_resolving_balls = True
_outlines = False

# --- STATIC floor (whole width) ------------------------------------------------
floor = Rect(center=(W * 0.5, H - 60), width=W - 40, height=30, group="floor")
floor.set_color("dim gray")
floor.mass = STATIC

# --- Left: bounce demo ---------------------------------------------------------
Text(text="bounce= 0 / 0.5 / 1 / 1.2", top_left=(40, H - 113), font_size=14,
     color=Color(0.55, 0.85, 1.0, 1))

ball_stop = Circle(center=(120, 200), radius=22, group="bounce")
ball_stop.set_color("tomato")
ball_stop.mass = 1.0
ball_stop.vel = Vec2(0, 0)

ball_half = Circle(center=(220, 160), radius=22, group="bounce")
ball_half.set_color("orange")
ball_half.mass = 1.0
ball_half.vel = Vec2(0, 0)

ball_full = Circle(center=(320, 120), radius=22, group="bounce")
ball_full.set_color("gold")
ball_full.mass = 1.0
ball_full.vel = Vec2(0, 0)

ball_super = Circle(center=(420, 80), radius=22, group="bounce")
ball_super.set_color("cyan")
ball_super.mass = 1.0
ball_super.vel = Vec2(0, 0)

resolve(ball_stop, "floor", bounce=0.0)
resolve(ball_half, "floor", bounce=0.5)
resolve(ball_full, "floor", bounce=1.0)
resolve(ball_super, "floor", bounce=1.2)

# --- Mid: mixed mass + resolve toggle ------------------------------------------
Text(text="mixed mass  ·  R toggles resolve(big, small)", top_left=(520, H - 113),
     font_size=14, color=Color(1.0, 0.85, 0.45, 1))

big = Circle(center=(580, 220), radius=34, group="big")
big.set_color("dodger blue")
big.mass = 5.0
big.vel = Vec2(-120, 0)

small = Circle(center=(760, 220), radius=18, group="small")
small.set_color("lime")
small.mass = 1.0
small.vel = Vec2(180, 0)

resolve("big", "small", bounce=0.8)
resolve("big", "floor", bounce=0.0)
resolve("small", "floor", bounce=0.0)

# --- Right: wall + draggable hand ----------------------------------------------
Text(text="wall bounce=0  ·  gold hand mass=STATIC", top_left=(980, H - 113),
     font_size=14, color=Color(0.85, 0.75, 1.0, 1))

wall = Rect(center=(W - 120, 400), width=24, height=260, group="wall")
wall.set_color("slate gray")
wall.mass = STATIC

runner = Circle(center=(W - 320, 400), radius=20, group="runner")
runner.set_color("hot pink")
runner.mass = 1.0
runner.vel = Vec2(260, 0)

resolve("runner", "wall", bounce=0.0)
resolve("runner", "floor", bounce=0.0)

hand = Sprite(Sheet("../../examples/media/shooter/sheet.xml"), frame="playerShip1_orange.png", height=64, center=(W - 320, 280),
              group="hand", hitbox_shape="auto")
hand.mass = STATIC
hand.draggable = True
resolve("hand", "bounce")
resolve("hand", "big")
resolve("hand", "small")
resolve("hand", "runner")

for s in (ball_stop, ball_half, ball_full, ball_super, big, small, runner, hand):
    s.draggable = True

GRAVITY = 420.0


def _reset_bounce_speeds():
    ball_stop.vel = Vec2(0, 280)
    ball_half.vel = Vec2(0, 280)
    ball_full.vel = Vec2(0, 280)
    ball_super.vel = Vec2(0, 280)


_reset_bounce_speeds()


def update(dt):
    for b in (ball_stop, ball_half, ball_full, ball_super):
        b.vel.y += GRAVITY * dt
        b.move_by(b.vel.x * dt, b.vel.y * dt)
    big.vel.y += GRAVITY * dt
    small.vel.y += GRAVITY * dt
    runner.vel.y += GRAVITY * dt
    big.move_by(big.vel.x * dt, big.vel.y * dt)
    small.move_by(small.vel.x * dt, small.vel.y * dt)
    runner.move_by(runner.vel.x * dt, runner.vel.y * dt)


def on_key_down(key):
    global _resolving_balls, _outlines
    if key == "R":
        if _resolving_balls:
            unresolve("big", "small")
            _resolving_balls = False
            hud.status = "resolve(big, small) OFF — watch overlap"
        else:
            resolve("big", "small", bounce=0.8)
            _resolving_balls = True
            hud.status = "resolve(big, small) ON"
    elif key == "SPACE":
        _outlines = not _outlines
        collision.show_colliders(_outlines)
        hud.status = f"outlines {'ON' if _outlines else 'OFF'}"
    elif key == "1":
        _reset_bounce_speeds()
        hud.status = "bounce balls reset (drop from top)"
    elif key == "2":
        big.vel = Vec2(-120, 0)
        small.vel = Vec2(180, 0)
        hud.status = "big/small relaunched"
    elif key == "3":
        runner.vel = Vec2(260, 0)
        runner.center = (W - 320, 400)
        hud.status = "runner relaunched at wall"


run()
