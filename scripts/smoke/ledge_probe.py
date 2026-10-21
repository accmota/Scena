"""ledge_probe.py — smoke: two ways to turn a patrol at a ledge, side by side.

Both lanes have the same ground and the same walkers. Only the ledge test
differs:

  A (gold)  floor_below(dx=hitbox.box.width) — the solver's own question: hitbox,
            floor rule (±45°), snap reach, resolve() partners.
  B (cyan)  a hidden Rect linked with @= just past the front foot, and
            sensor.collides_with(group="chao"). No new API.

Every walker also turns at a wall ("left" / "right" in touching_sides).

What to look at (left → right): a wall, a tile join, two 10 DU steps down,
a 12 DU gap narrower than the walker (the body bridges it), a 40° ramp down,
a flat bottom, a 30° ramp up, a plateau, and a cliff. Walkers cannot climb a
step: coming back, a step face is a wall. Expected (checked headless):

  A  floor_below depth 16 (the default): the left walker goes down the
     steps, over the gap and the ramps, and turns only at the cliff; the
     right one turns at the cliff and at a step face. A (depth down) below
     10: the left walker turns at the top of the steps — a 10 DU step is now
     a fall. Depth never changes the ramps: slopes up to 45° are floor.
  B  sensor depth 6: the left walker turns at the top of the steps, the
     right one at the top of the 30° ramp (resting on the ramp's top corner,
     the body leaves its sensor over air). W to 12: the left walker goes
     down the steps, then turns at the gap at any depth (the sensor sees air
     past the front foot, though the body would bridge it). The right walker
     needs 16 for the 30° ramp and still turns atop the 40° one — and a
     sensor that deep would also step off any 16 DU drop.

Usage
-----
    python scripts/smoke/ledge_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SAFE_BOTTOM, SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.78, title="Smoke — ledge probe")
collision.floor = True   # gravity: bodies stand on floors (ramps, lifts, seams)
canvas.background = (0.07, 0.08, 0.11)

GRAVITY = 900.0
SPEED = 70.0
WALKER_W, WALKER_H = 26.0, 30.0
SENSOR_W = 4.0

GROUND = Color(0.42, 0.46, 0.54, 1)
A_INK = Color("gold")
B_INK = Color("deep sky blue")
SENSOR_INK = Color("tomato")
INK = Color(0.78, 0.84, 0.94, 1)

hud = SmokeHud(
    title="Ledge probe — floor_below vs a linked sensor Rect",
    expect="A (gold): down the steps, over the gap, both ramps; depth < 10 turns it at the steps, never at a ramp. "
           "B (cyan): turns at the steps (until W ≥ 12), at the 30° ramp top (until 16), and at the gap at any depth.",
    keys="SPACE restart  ·  A / S floor_below depth  ·  Q / W sensor depth  ·  C colliders + probes (magenta = floor, red = none)  ·  V sensors",
    status="",
)

st.floor_depth = 16.0   # floor_below(depth=) (lane A); 16 = the default
st.depth = 6.0          # sensor depth (lane B)
st.turns_a = 0
st.turns_b = 0
_outlines = False
_sensors_shown = False
collision.show_colliders(False)


# --- ground: one lane, drawn twice ------------------------------------------

def slab(x0, x1, top, y0, thick=20.0):
    s = Rect(p1=(x0, y0 + top - thick), p2=(x1, y0 + top), group="chao", color=GROUND)
    s.mass = STATIC
    return s


def ramp(x0, top0, x1, top1, y0, below=20.0):
    low = min(top0, top1) - below
    p = Polygon(points=[(x0, y0 + top0), (x1, y0 + top1), (x1, y0 + low), (x0, y0 + low)],
                group="chao", color=GROUND)
    p.mass = STATIC
    return p


def lane(y0):
    slab(150, 170, 80, y0, thick=100)                  # wall
    slab(170, 230, 0, y0)                               # tiles: a join is not an edge
    slab(230, 290, 0, y0)
    slab(290, 330, -10, y0)                             # two 10 DU steps down
    slab(330, 370, -20, y0)
    slab(382, 442, -20, y0)                             # after a 12 DU gap
    ramp(442, -20, 498, -67, y0)                        # 40° down
    slab(498, 760, -67, y0)                             # bottom
    ramp(760, -67, 876, 0, y0)                          # 30° up
    slab(876, 1160, 0, y0)                              # plateau, cliff at 1160


LANE_A, LANE_B = 560.0, 230.0
lane(LANE_A)
lane(LANE_B)
Text(text="A — walker.floor_below(dx=walker.hitbox.box.width * dir)", top_left=(170, LANE_A + 150),
     font_size=16, color=A_INK)
Text(text="B — hidden Rect linked with @=, sensor.collides_with(group=\"chao\")",
     top_left=(170, LANE_B + 150), font_size=16, color=B_INK)


# --- walkers ------------------------------------------------------------------

SPAWNS = [(200.0, 1.0), (1080.0, -1.0)]    # (x, direction) per lane


def walker(x, y0, ink, group):
    w = Rect(center=(x, y0 + WALKER_H / 2 + 1), width=WALKER_W, height=WALKER_H,
             group=["bicho", group], color=ink)
    w.mass = 1.0
    w.vel = Vec2(0.0, 0.0)
    return w


walkers_a = [walker(x, LANE_A, A_INK, "a") for x, _d in SPAWNS]
walkers_b = [walker(x, LANE_B, B_INK, "b") for x, _d in SPAWNS]
resolve("bicho", "chao", bounce=0.0)


def sensor_for(w):
    """Just past the front foot, from the feet down ``st.depth``."""
    s = Rect(center=(0, 0), width=SENSOR_W, height=6.0, color=SENSOR_INK)
    s.visible = False
    s["height"] @= lambda: st.depth
    s["center"] @= lambda: w.center + (
        (WALKER_W / 2 + SENSOR_W / 2) if w.vel.x >= 0 else -(WALKER_W / 2 + SENSOR_W / 2),
        -(WALKER_H / 2 + st.depth / 2),
    )
    return s


sensors = [sensor_for(w) for w in walkers_b]


walkers = walkers_a + walkers_b
dirs = [1.0] * len(walkers)             # walk direction per walker


def restart():
    for lane_y, ws in ((LANE_A, walkers_a), (LANE_B, walkers_b)):
        for w, (x, _d) in zip(ws, SPAWNS):
            w.center = (x, lane_y + WALKER_H / 2 + 1)
            w.vel = Vec2(0.0, 0.0)
    dirs[:] = [d for _x, d in SPAWNS] * 2
    st.turns_a = 0
    st.turns_b = 0


def hits_wall(w, d):
    sides = w.touching_sides
    return ("right" in sides and d > 0) or ("left" in sides and d < 0)


def update(dt):
    for i, w in enumerate(walkers):
        d = dirs[i]
        grounded = "bottom" in w.touching_sides
        if i < len(walkers_a):
            ledge = grounded and not w.floor_below(dx=w.hitbox.box.width * d, depth=st.floor_depth)
        else:
            ledge = grounded and not sensors[i - len(walkers_a)].collides_with(group="chao")
        if ledge or hits_wall(w, d):
            d = dirs[i] = -d
            if i < len(walkers_a):
                st.turns_a += 1
            else:
                st.turns_b += 1
        w.vel.x = SPEED * d                 # walk: a steady speed, every frame
        w.vel.y -= GRAVITY * dt
        w.move_by(w.vel.x * dt, w.vel.y * dt)
    hud.status = (
        f"A: floor_below depth {st.floor_depth:.0f} DU (default 16, the resolver's step-down reach)"
        f"   turns {st.turns_a}      B: sensor depth {st.depth:.0f} DU   turns {st.turns_b}"
    )


def on_key_down(key):
    global _outlines, _sensors_shown
    if key == "SPACE":
        restart()
    elif key == "C":
        _outlines = not _outlines
        collision.show_colliders(_outlines)
    elif key == "V":
        _sensors_shown = not _sensors_shown
        for s in sensors:
            s.visible = _sensors_shown
    elif key == "A":
        st.floor_depth = max(2.0, st.floor_depth - 2.0)
    elif key == "S":
        st.floor_depth = min(40.0, st.floor_depth + 2.0)
    elif key == "Q":
        st.depth = max(2.0, st.depth - 2.0)
    elif key == "W":
        st.depth = min(40.0, st.depth + 2.0)


Text(text="A and B share ground and walkers; only the ledge test differs. "
          "Each walker also turns at a wall (touching_sides).",
     top_left=(24, SAFE_BOTTOM + 28), font_size=14, color=INK)

restart()
run()
