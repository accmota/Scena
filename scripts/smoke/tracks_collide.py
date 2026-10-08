"""tracks_collide.py — smoke: move_along riders vs bounce=1 resolve.

Expect
------
  Many balls ride Tracks (circles / eights / lines). Obstacles weave through —
  some also on Tracks, others with free vel. Everything resolves with bounce=1
  against everything (including walls). Riders stop / shove on contact, then
  keep trying the path (resolve enrolls before move_along — exclusive drivers).

Controls
--------
  SPACE     toggle collider outlines
  P         toggle track overlay
  drag      any body

Usage
-----
    python scripts/smoke/tracks_collide.py
"""
from __future__ import annotations

import sys
from scena import *
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1280, 820
init(width=W, height=H, window_scale=0.78, title="Smoke — tracks × collide")
canvas.background = (0.05, 0.06, 0.09)
SkyGradient("night")
canvas.effects.add(Vignette(amount=0.32))

hud = SmokeHud(
    title="Tracks × resolve (bounce=1)",
    expect="Riders keep trying the track; obstacles shove them; bounce=1; trimmed begin/end wall (gold).",
    keys="SPACE outlines  ·  P track overlay  ·  drag bodies",
    status="watch track motion vs bounce",
)

WALL_T = 22

# --- arena walls (STATIC) ----------------------------------------------------
walls = [
    Rect(center=(W * 0.5, WALL_T * 0.5), width=W, height=WALL_T, group="body", color="dim gray"),
    Rect(center=(W * 0.5, H - WALL_T * 0.5), width=W, height=WALL_T, group="body", color="dim gray"),
    Rect(center=(WALL_T * 0.5, H * 0.5), width=WALL_T, height=H, group="body", color="dim gray"),
    Rect(center=(W - WALL_T * 0.5, H * 0.5), width=WALL_T, height=H, group="body", color="dim gray"),
]
for w in walls:
    w.mass = STATIC

# Tracks are geometry only until enrolled — keep rails off collision so
# move_along riders do not fight their own path (enrollment is opt-in).
orbits = [
    Track.circle(center=(280, 420), radius=130),
    Track.circle(center=(640, 400), radius=100),
    Track.circle(center=(980, 430), radius=120),
]
eights = [
    Track.eight(width=180, height=80),
    Track.eight(width=140, height=60),
]
rails = [
    Track(points=[(120, 200), (500, 680)], smooth=0),
    Track(points=[(760, 180), (1160, 640)], smooth=0).zigzag(amount=36, waves=4),
]
for t in (*orbits, *eights, *rails):
    t.collidable = False

# --- balls on paths (spawn only; ride after resolve) -------------------------
# Standing resolve() and in-flight move_along both claim center. Enroll resolve
# first, then start rides — same order as test_move_along_stops_at_wall.
COLORS = ("tomato", "gold", "cyan", "sea green", "orange", "hotpink", "skyblue", "violet")
riders = []
rides = []  # (shape, track, kwargs) deferred until after resolve

for i, orbit in enumerate(orbits):
    for k in range(3):
        b = Circle(
            center=(float(orbit.center.x) + float(orbit.radius), float(orbit.center.y)),
            radius=11,
            color=COLORS[(i * 3 + k) % len(COLORS)],
            group="body",
        )
        b.mass = 1.0
        b.draggable = True
        riders.append(b)
        rides.append((b, orbit, dict(time=5.0 + i * 0.6, loops="forever", phase=k * 0.28)))

for i, eight in enumerate(eights):
    cx = 420 + i * 360
    cy = 280
    for k in range(2):
        b = Circle(center=(cx, cy - k * 10), radius=10, color=COLORS[(i + k + 2) % len(COLORS)], group="body")
        b.mass = 1.0
        b.draggable = True
        riders.append(b)
        rides.append((b, eight, dict(time=3.2 + i * 0.4, loops="forever", phase=k * 0.35)))

for i, rail in enumerate(rails):
    p0 = rail.at(0.0)
    b = Circle(center=p0, radius=12, color=COLORS[(i + 5) % len(COLORS)], group="body")
    b.mass = 1.0
    b.draggable = True
    riders.append(b)
    rides.append((b, rail, dict(time=4.0 + i, loops="forever")))

# --- obstacles on paths ------------------------------------------------------
obs_paths = [
    Track.circle(center=(500, 520), radius=90),
    Track.wave(length=220, amplitude=50, waves=3),
]
for t in obs_paths:
    t.collidable = False

obs_path_riders = []
block = Rect(center=(500 + 90, 520), width=36, height=36, color="gray", group="body")
block.mass = 2.5
block.draggable = True
obs_path_riders.append(block)
rides.append((block, obs_paths[0], dict(time=6.0, loops="forever")))

slab = Rect(center=(700, 560), width=50, height=28, color="dim gray", group="body")
slab.mass = 3.0
slab.draggable = True
obs_path_riders.append(slab)
rides.append((slab, obs_paths[1], dict(time=5.0, loops="forever")))

# --- free-moving obstacles (no path) -----------------------------------------
free = []
specs = [
    ((200, 600), 18, Vec2(140, 90), "coral"),
    ((900, 250), 22, Vec2(-120, 110), "orchid"),
    ((640, 700), 16, Vec2(80, -160), "khaki"),
    ((1100, 500), 20, Vec2(-150, -70), "light sea green"),
    ((360, 300), 14, Vec2(200, -40), "salmon"),
]
for (xy, r, vel, col) in specs:
    c = Circle(center=xy, radius=r, color=col, group="body")
    c.mass = 1.5
    c.vel = vel
    c.draggable = True
    free.append(c)

# --- trimmed stroke wall (begin/end = visible collider only) -----------------
# Full circle geometry; only a quarter is stroked / collidable. Ghost half must
# not shove riders (was the old begin/end surprise).
trim_wall = Track.circle(
    center=(1100, 160), radius=70, color="gold", line_width=10, group="body",
)
trim_wall.begin = 0.0
trim_wall.end = 0.28
trim_wall.mass = STATIC
Text(
    text="begin/end wall",
    center=(1100, 70),
    font_size=12,
    color=Color(0.85, 0.75, 0.4, 1),
)

# Everything vs everything, elastic — before move_along claims center.
resolve("body", "body", bounce=1.0)

for shape, track, kw in rides:
    shape.move_along(track, **kw)

st.outlines = False
st.tracks_on = False


def on_key_down(key):
    if key == "SPACE":
        st.outlines = not st.outlines
        collision.show_colliders(st.outlines)
        hud.status = "outlines on" if st.outlines else "outlines off"
    elif key == "P":
        st.tracks_on = not st.tracks_on
        show_tracks(st.tracks_on)
        hud.status = "show_tracks on" if st.tracks_on else "show_tracks off"


run()
