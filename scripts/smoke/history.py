"""history.py — smoke: History, Contrail, and a Snake-like grow trail.

Panels
------
  A  Contrail fade following a Lissajous tip (Laser)
  B  History Segments (per-stamp Lines) + Dots dissolve
  C  Snake: distance-sampled Contrail; eat food → max_points += 1
  D  Many short Contrails on click sparks

Controls
--------
  A/S/D/W or arrows   snake direction (panel C)
  click               spark Contrail at pointer (panel D)
  R                   reset snake
  SPACE               pause motion on A/B
  E                   cycle FX quality

Usage
-----
    python scripts/smoke/history.py
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, cycle_quality

W, H = 1280, 820
init(width=W, height=H, window_scale=0.78, title="Smoke — History / Contrail")
canvas.fx_quality = "high"
canvas.background = (0.05, 0.06, 0.09)
SkyGradient("Midnight")
Stars(density=0.45, twinkle=0.2)
canvas.effects.add(Vignette(amount=0.3))

hud = SmokeHud(
    title="History / Contrail",
    expect="A faded Contrail · B Segments+Dots · C Snake grows · D click sparks",
    keys="WASD/arrows snake  ·  click sparks  ·  R reset snake  ·  SPACE pause A/B  ·  E quality",
    status="ready",
    show_aux=True,
)

st.paused = False


def _panel(cx, cy, w, h, title):
    r = Rect(center=(cx, cy), width=w, height=h, color=Color(0.1, 0.12, 0.16, 0.55))
    r.line = None
    Text(title, top_left=(cx - w * 0.5 + 12, cy - h * 0.5 + 37), font_size=18, layer="ui")
    return r


# =============================================================================
# Panel A — Lissajous tip + Contrail fade
# =============================================================================
_panel(330, 240, 580, 320, "A · Contrail fade")

hub_a = Circle(center=(330, 240), radius=10)
hub_a.visual = Halo("steel blue", style="fill")
tip_a = Point()
tip_a @= lambda: (
    hub_a.center.x + 160 * math.cos(clock.time * 1.7),
    hub_a.center.y + 110 * math.sin(clock.time * 2.3),
)
marker_a = Circle(center=lambda: tip_a, radius=6)
marker_a.visual = Sphere("cyan")

trail_a = Contrail(
    max_points=90, duration=2.2, fade=True, ease="ease_out",
    visual=Laser("cyan"), line_width=2.5,
)
every(0.03, lambda: (None if st.paused else trail_a.snapshot(tip_a)), name="a_sample")

# =============================================================================
# Panel B — Segments + Dots
# =============================================================================
_panel(950, 240, 580, 320, "B · Segments + Dots")

hub_b = Circle(center=(950, 240), radius=10)
hub_b.visual = Halo("gold", style="fill")
tip_b = Point()
tip_b @= lambda: (
    hub_b.center.x + 150 * math.cos(clock.time * 1.1 + 1.0),
    hub_b.center.y + 100 * math.sin(clock.time * 1.9 + 0.4),
)
marker_b = Circle(center=lambda: tip_b, radius=5)
marker_b.color = "gold"


segments_b = History(max_points=40, duration=1.4)
dots_b = History(max_points=24, duration=1.0, on_leave=lambda dot: dot.dissolve_out(0.3))


def _sample_b():
    if st.paused:
        return
    start = segments_b.last.p2 if segments_b else tip_b.center
    segment = segments_b.add(Line(p1=start, p2=tip_b.center))
    segment.visual = Laser("tomato")
    dot = dots_b.add(Circle(center=tip_b.center, radius=4))
    dot.visual = Halo("magenta")


every(0.05, _sample_b, name="b_sample")

# =============================================================================
# Panel C — Snake (distance-sampled Contrail that grows)
# =============================================================================
_panel(330, 610, 580, 340, "C · Snake (eat → grow)")

arena = Box(center=(330, 610), width=520, height=260)
snake_head = Circle(center=arena.center, radius=9)
snake_head.visual = Halo("lime", style="fill")
snake_head.collidable = True

body = Contrail(
    max_points=8, fade=True, ease="quad",
    color=Color("lime").with_alpha(0.9), line_width=10, line_join="round",
)
body.snapshot(snake_head)

food = Circle(center=(280, 580), radius=7)
food.visual = Halo("orange", style="fill")
food.collidable = True

st.snake_dir = (1.0, 0.3)
st.snake_speed = 160.0
st.snake_step = 14.0
st.snake_blocked = None  # held key that just bounced; ignored until release
snake_head.vel = Vec2(st.snake_speed, 0)
_last_stamp = Point(snake_head)


def _place_food():
    food.center = (
        random.uniform(arena.left + 24, arena.right - 24),
        random.uniform(arena.bottom + 24, arena.top - 24),
    )


def _held_dir():
    if keyp("LEFT") or keyp("A"):
        return (-1.0, 0.0)
    if keyp("RIGHT") or keyp("D"):
        return (1.0, 0.0)
    if keyp("UP") or keyp("W"):
        return (0.0, 1.0)
    if keyp("DOWN") or keyp("S"):
        return (0.0, -1.0)
    return None


def _reset_snake():
    snake_head.center = arena.center
    st.snake_dir = (1.0, 0.0)
    st.snake_blocked = None
    snake_head.vel = Vec2(st.snake_speed, 0)
    body.clear()
    body.max_points = 8
    body.snapshot(snake_head)
    _last_stamp._takein(snake_head.center)
    _place_food()
    hud.status = "snake reset"


def update(dt):
    dx, dy = st.snake_dir
    held = _held_dir()
    if held is None:
        st.snake_blocked = None
    elif held != st.snake_blocked:
        dx, dy = held
        st.snake_blocked = None

    speed = st.snake_speed
    snake_head.vel = (dx * speed, dy * speed)
    snake_head.move_by(dx * speed * dt, dy * speed * dt)
    sides = snake_head.confine(arena, action="bounce")
    if sides:
        vx, vy = float(snake_head.vel.x), float(snake_head.vel.y)
        dx = 0.0 if abs(vx) < 1.0 else (1.0 if vx > 0.0 else -1.0)
        dy = 0.0 if abs(vy) < 1.0 else (1.0 if vy > 0.0 else -1.0)
        # A key held into the wall would cancel the bounce next frame.
        if held is not None and held[0] * dx + held[1] * dy < 0.0:
            st.snake_blocked = held
    st.snake_dir = (dx, dy)

    if distance(snake_head, _last_stamp) >= st.snake_step:
        body.snapshot(snake_head)
        #_last_stamp._takein(snake_head.center)

    if keyp.once("R"):
        _reset_snake()
    if keyp.once("SPACE"):
        st.paused = not st.paused
        hud.status = "paused" if st.paused else "running"
    if keyp.once("E"):
        cycle_quality()


@collide(snake_head, food)
def eat(_me, _other, _info):
    body.max_points += 2
    body.snapshot(snake_head)
    spark = Sparks(center=food.center, radius=22, rate=70, color="orange")
    after(0.35, spark.destroy)
    _place_food()
    hud.status = f"ate · len={body.max_points}"


# =============================================================================
# Panel D — click sparks (many short Contrails)
# =============================================================================
_panel(950, 610, 580, 340, "D · click sparks")

_sparks: list = []


def _spark_at(x, y):
    angle = random.uniform(0, math.tau)
    speed = random.uniform(80, 180)
    tip = Point(x, y)
    tip.vx = math.cos(angle) * speed
    tip.vy = math.sin(angle) * speed
    hue = random.choice(["red", "cyan", "magenta", "gold", "lime"])
    trail = Contrail(
        duration=0.7, fade=True, ease="ease_in",
        visual=Laser(hue), line_width=2.0, max_points=24,
    )
    trail.snapshot(tip)

    def step():
        tip.x = float(tip.x) + tip.vx * clock.dt
        tip.y = float(tip.y) + tip.vy * clock.dt
        tip.vx *= 0.98
        tip.vy *= 0.98
        trail.snapshot(tip)

    handle = every(0.02, step)
    _sparks.append((trail, tip, handle))
    after(0.75, lambda: _retire(trail, tip, handle))


def _retire(trail, tip, handle):
    try:
        handle.cancel()
    except Exception:
        pass
    trail.destroy()
    try:
        tip.destroy()
    except Exception:
        pass
    _sparks[:] = [s for s in _sparks if s[0] is not trail]


hit_zone = Rect(center=(950, 610), width=520, height=260)
hit_zone.fill = Color(0, 0, 0, 0.01)
hit_zone.line = None
hit_zone.clickable = True


@click(hit_zone)
def on_spark_click():
    _spark_at(mouse.x, mouse.y)
    for _ in range(3):
        _spark_at(
            mouse.x + random.uniform(-12, 12),
            mouse.y + random.uniform(-12, 12),
        )
    hud.status = f"sparks · live={len(_sparks)}"


_place_food()
hud.status = "running"
run()
