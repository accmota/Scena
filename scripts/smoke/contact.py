"""contact.py — smoke: bang sits on info.point (not body centers).

Shapes and sprites loop on crossing paths. Enter fires a local burst at
``info.point``; a marker tracks the contact on stay. Exit has no point.

Grounding flicker (animated walker on a floor) is covered by
``tests.test_collision.TestSpriteHitboxGrounding``.

Controls
--------
  SPACE     pause / resume auto motion (resume restores orbits)
  drag      any body — movers, targets, or the free probes
  wheel     rotate the body under the cursor (hold, then scroll)
  X         cinematic explosion_at last point (shake off)
  C         toggle collider outlines
  E         cycle FX quality

Usage
-----
    python scripts/smoke/contact.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, cycle_quality

W, H = 1280, 820
init(width=W, height=H, window_scale=0.78, title="Smoke — contact point")
canvas.fx_quality = "high"
canvas.background = (0.07, 0.08, 0.11)
SkyGradient("night")
Stars(density=0.4, twinkle=0.15)
canvas.effects.add(Vignette(amount=0.3))
canvas.effects.add(Bloom(intensity=0.35))

hud = SmokeHud(
    title="Contact point",
    expect="Pyro + cyan marker on the shared face — not inside the wall, not at a center.",
    keys="SPACE stop  ·  drag / wheel any  ·  X explode last  ·  C outlines  ·  E quality",
    status="waiting for enter…",
    show_aux=True,
)

_cx, _cy = W * 0.5, H * 0.42
_paused = False
_t = 0.0
_outlines = False
_last_point = None
_last_n_points = 0
_claimed = set()

# Persistent marker (snapped on each enter / stay)
marker = Circle(center=(_cx, _cy), radius=7).set_color("cyan")
marker.line_color = Color("white")
marker.line_width = 2
marker.glow = Glow("cyan", radius=10, sigma=6, amount=1.1)
marker.collidable = False

# Static / slow targets
wall = Rect(
    center=(_cx, _cy), width=160, height=36, angle=12, group="target",
).set_color("dim gray")
crate = Square(
    center=(_cx + 220, _cy - 40), length=56, angle=-8, group="target",
).set_color("sienna")
pad = Ellipse(
    center=(_cx - 240, _cy + 30), width=90, height=50, angle=25, group="target",
).set_color("slate gray")

# Moving shapes
ball = Circle(
    center=(_cx - 200, _cy), radius=28, group="mover",
).set_color("dodger blue")
block = Rect(
    center=(_cx + 200, _cy), width=70, height=48, angle=0, group="mover",
).set_color("orange")
hexagon = RegularPolygon(
    n=6, center=(_cx, _cy + 160), radius=32, group="mover",
).set_color("coral")

# Moving sprites
ship = Sprite(
    "../../examples/media/space/playerShip1_red.png", height=44, center=(_cx - 180, _cy + 120),
    group="mover", hitbox_shape="auto",
)
meteor = Sprite(
    "../../examples/media/space/meteorBrown_big3.png", size=48, center=(_cx + 180, _cy - 120),
    group="mover", hitbox_shape="auto",
)

# Free probes — never orbit; always available to drag / wheel into the wall
probe_sq = Square(
    center=(90, 140), length=44, angle=18, group="mover",
).set_color("gold")
probe_tri = EquilateralTriangle(
    center=(180, 140), radius=30, angle=-20, group="mover",
).set_color("hot pink")

_movers = (ball, block, hexagon, ship, meteor)
_targets = (wall, crate, pad)
_probes = (probe_sq, probe_tri)


def _claim(from_shape, to_shape, pos):
    _claimed.add(id(from_shape))


for s in (*_targets, *_movers, *_probes):
    s.draggable = True
    s.wheel_rotate = True
    s.on_drag_to = _claim

Text(
    text="SPACE stops orbits  ·  drag / wheel anything  ·  gold+pink probes never auto-move",
    top_left=(40, H - 115), font_size=13,
    color=Color(0.55, 0.75, 0.95, 1),
)


def _mark(me, other, info, *, bang: bool):
    global _last_point, _last_n_points
    pt = info.point
    if not pt:
        return
    _last_point = pt
    _last_n_points = len(info.points)
    marker.center = pt
    if bang:
        canvas.burst_at(pt[0], pt[1], radius=38, amount=0.95, rings=True)
    hud.status = (
        f"{me} ↔ {other}  point=({pt[0]:.0f}, {pt[1]:.0f})  "
        f"points={_last_n_points}  depth={info.depth:.1f}"
    )


@collide("mover", "target")
def on_mover_target(me, other, info):
    _mark(me, other, info, bang=True)


@collide_stay("mover", "target")
def on_mover_target_stay(me, other, info):
    _mark(me, other, info, bang=False)


@collide("mover", "mover")
def on_mover_mover(me, other, info):
    _mark(me, other, info, bang=True)


@collide_stay("mover", "mover")
def on_mover_mover_stay(me, other, info):
    _mark(me, other, info, bang=False)


def _held() -> bool:
    return bool(mouse.press())


def update(dt):
    global _t
    frozen = _paused or _held()
    if not frozen:
        _t += dt
    a = _t * 0.9
    b = _t * 1.1 + 0.7
    c = _t * 0.75 + 1.4
    d = _t * 1.05 + 2.2
    e = _t * 0.85 + 3.0

    if not frozen:
        if id(ball) not in _claimed:
            ball.center = (_cx + 260.0 * math.cos(a), _cy + 90.0 * math.sin(a))
        if id(block) not in _claimed:
            block.center = (_cx + 200.0 * math.cos(b + math.pi), _cy + 110.0 * math.sin(b * 0.8))
            block.angle = math.degrees(b) * 0.4
        if id(hexagon) not in _claimed:
            hexagon.center = (_cx + 80.0 * math.cos(c), _cy + 170.0 * math.sin(c * 1.2))
            hexagon.angle = math.degrees(c)
        if id(ship) not in _claimed:
            ship.center = (_cx + 240.0 * math.cos(d), _cy - 100.0 + 70.0 * math.sin(d * 1.3))
            ship.angle = math.degrees(d) + 90.0
        if id(meteor) not in _claimed:
            meteor.center = (_cx - 40.0 + 200.0 * math.sin(e), _cy + 40.0 * math.cos(e * 0.7))
            meteor.angle = math.degrees(e) * 0.5

    pt = _last_point
    pt_s = f"({pt[0]:.0f}, {pt[1]:.0f})" if pt else "none"
    if _paused:
        mode = "STOPPED — drag / wheel"
    elif _held():
        mode = "holding — auto-motion frozen"
    else:
        mode = "moving"
    hud.aux = (
        f"t={_t:.1f}  last={pt_s}  n_points={_last_n_points}  {mode}"
    )


def on_key_down(key):
    global _paused, _outlines
    if key == "SPACE":
        _paused = not _paused
        if not _paused:
            _claimed.clear()
            hud.status = "moving — resume restored orbits"
        else:
            hud.status = "stopped — drag / wheel any body into the wall"
    elif key == "X":
        if _last_point:
            canvas.explosion_at(
                _last_point[0], _last_point[1],
                amount=0.9, shake=False, flash=False,
            )
            hud.status = f"explosion_at last {_last_point}"
        else:
            hud.status = "no last point yet — wait for a hit"
    elif key == "C":
        _outlines = not _outlines
        collision.show_colliders(_outlines)
        hud.status = f"outlines {'ON' if _outlines else 'OFF'}"
    elif key == "E":
        hud.status = f"quality={cycle_quality()}"


run()
