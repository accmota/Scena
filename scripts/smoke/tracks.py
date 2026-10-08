"""tracks.py — smoke: Track presets, move_along, modifiers, show_tracks, face=.

Expect
------
  Left: moon on an anchored circle around a planet (live center).
  Middle: three wasps on one floating eight, staggered with phase=.
  Right: a gold zigzag line; a bead rides it at constant speed.
  Center: a cyan circle rides a Rect outline (live Shape — not a Track).
  Bottom: Anchors drive a Track via lambda points=; drag an Anchor, track rebuilds.
  Deco Track.star with ElectricBolt — drawn only (not a ride).
  Deco Track.eight(center=, floating=True) — gold template; riders still root at themselves.
  Left-mid: gold ring draws on (tween end); cyan window crawls (begin/end wrap —
    stroke + collision follow the window; travel stays the full curve).
  Mid: shuttle patrol (closed dash, out both ways from the rider).
  Top strip: three planes (plane.png) with face=True —
    move_to yoyo, move_by yoyo, move_along on a floating eight.
  Top-left: floating Track.line (angle=0 horizontal, angle=90 vertical) yoyo.
  HUD strip: orbit / rail / rider readout (velocity, speed, heading, u, lap).
  SPACE toggles the magenta track overlay (does not show/hide Track strokes).
  Center: cyan circle rides a rounded Rect outline (corner_radius — silhouette).

Usage
-----
    python scripts/smoke/tracks.py
"""
from __future__ import annotations

import sys
from scena import *
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1280, 820
PLANE = "../../examples/media/plane/Fly1.png"
init(width=W, height=H, window_scale=0.78, title="Smoke — tracks")
canvas.background = (0.06, 0.07, 0.10)
SkyGradient("night")
canvas.effects.add(Vignette(amount=0.28))

hud = SmokeHud(
    title="Tracks & move_along",
    expect="Orbit · phase eights · zigzag rail · shuttle · deco floating eight · rounded Rect · Track.line float · Anchor-linked · face= planes · ElectricBolt star · begin/end.",
    keys="SPACE overlay  ·  drag planet / Anchors",
    status="show_tracks off",
)

# --- face=True planes (move_to / move_by / move_along) ----------------------
Text(
    text="face=True  ·  move_to  ·  move_by  ·  move_along",
    center=(700, 90),
    font_size=14,
    color=Color(0.75, 0.82, 0.9, 1),
)
plane_to = Sprite(PLANE, height=44, center=(420, 150), art_angle=0)
plane_to.move_to(620, 250, time=2.2, ease="ease_in_out", loops="forever", yoyo=True, face=True)
Text(text="move_to", center=(520, 105), font_size=13, color=Color(0.7, 0.78, 0.85, 1))

plane_by = Sprite(PLANE, height=44, center=(700, 150), art_angle=0)
plane_by.move_by(180, 20, time=2.0, ease="ease_in_out", loops="forever", yoyo=True, face=True)
Text(text="move_by", center=(790, 105), font_size=13, color=Color(0.7, 0.78, 0.85, 1))

plane_along = Sprite(PLANE, height=44, center=(1080, 150), art_angle=0)
plane_along.move_along(
    Track.eight(width=120, height=40),
    time=3.0, loops="forever", face=True,
)
Text(text="move_along", center=(1080, 95), font_size=13, color=Color(0.7, 0.78, 0.85, 1))

# --- floating Track.line (horizontal + vertical) ---------------------------
Text(
    text="Track.line(length=, angle=)  ·  floating",
    center=(280, 90),
    font_size=14,
    color=Color(0.75, 0.82, 0.9, 1),
)
line_h = Circle(center=(200, 150), radius=8, color="tomato")
line_h.move_along(
    Track.line(length=140),
    time=1.6, loops="forever", yoyo=True, face=True,
)
Text(text="angle=0", center=(200, 105), font_size=13, color=Color(0.7, 0.78, 0.85, 1))
line_v = Circle(center=(320, 120), radius=8, color="gold")
line_v.move_along(
    Track.line(length=100, angle=90),
    time=1.4, loops="forever", yoyo=True, face=True,
)
Text(text="angle=90", center=(320, 105), font_size=13, color=Color(0.7, 0.78, 0.85, 1))

# --- anchored orbit (planet is draggable) -----------------------------------
earth = Circle(center=(280, 420), radius=28, color="steelblue")
earth.draggable = True
moon = Circle(center=(280, 310), radius=10, color="silver")
orbit = Track.circle(center=(280, 420), radius=110, color="white", line_width=1.5).zigzag()
orbit.center @= earth.center
h_orbit = moon.move_along(orbit, time=4.0, loops="forever", face=True)

# --- floating eight + phase stagger ----------------------------------------
eight = Track.eight(width=160, height=70)
for i, color in enumerate(("tomato", "gold", "mediumseagreen")):
    wasp = Circle(center=(640, 400), radius=9, color=color)
    wasp.move_along(eight, time=3.0, loops="forever", phase=i / 3.0)

# --- stroke window (begin / end) — draw + collision; travel stays full ------
_win_c = (180, 250)
Track.circle(center=_win_c, radius=48, color=(1, 1, 1, 0.18), line_width=6)
reveal = Track.circle(center=_win_c, radius=48, color="gold", line_width=6)
reveal.end = 0
tween(reveal["end"], 1, time=2.2, ease="ease_in_out", loops="forever", yoyo=True)
crawl = Track.circle(center=_win_c, radius=68, color="cyan", line_width=4)
crawl.begin = 0.0
crawl.end = 0.18
Text(
    text="begin / end  (stroke window)",
    center=(180, 330),
    font_size=13,
    color=Color(0.85, 0.78, 0.45, 1),
)

# --- zigzag rail -----------------------------------------------------------
rail = Track(points=[(920, 280), (1180, 620)], smooth=0, color="gold", line_width=2)
rail.zigzag(amount=28, waves=5)
bead = Circle(center=(920, 280), radius=8, color="orange")
h_rail = bead.move_along(rail, time=2.5, loops="forever")

# --- live Shape outline (rounded Rect) -------------------------------------
box = Rect(center=(760, 500), width=170, height=90, color=(0.12, 0.22, 0.26, 0.45), corner_radius=30)
box.line = "cyan"
box.line_width = 2
bug = Circle(center=(760, 500), radius=8, color="cyan")
bug.move_along(box, time=5.0, loops="forever", face=True)
Text(
    text="move_along(Rect)  ·  rounded",
    center=(760, 565),
    font_size=13,
    color=Color(0.55, 0.85, 0.85, 1),
)

# --- deco eight (positioned template, riders still float) + shuttle --------
Track.eight(width=90, height=36, center=(640, 220), floating=True, color="gold", line_width=2)
Text(text="eight center= + floating=True", center=(640, 175), font_size=13, color=(0.85, 0.75, 0.4, 1))
shuttle_bead = Circle(center=(880, 220), radius=8, color="sea green")
shuttle_bead.move_along(
    Track.shuttle(length=140),
    time=1.6, loops="forever", face=True,
)
Text(text="Track.shuttle", center=(880, 175), font_size=13, color=Color(0.55, 0.85, 0.7, 1))

# --- Anchor-linked control points ------------------------------------------
a1 = Anchor(200, 700, color="cyan")
a2 = Anchor(400, 620, color="cyan")
a3 = Anchor(600, 700, color="cyan")
a1.draggable = a2.draggable = a3.draggable = True
linked = Track(
    points=[lambda: (a1.center.x, a1.center.y),
            lambda: (a2.center.x, a2.center.y),
            lambda: (a3.center.x, a3.center.y)],
    color="orchid",
)
rider = Circle(center=(200, 700), radius=7, color="orchid")
h_rider = rider.move_along(linked, time=3.0, loops="forever")

# --- draw-only star + ElectricBolt -----------------------------------------
bolt = Track.star(points=5, radius=55, center=(1100, 280), color="gold", line_width=2.5)
bolt.visual = ElectricBolt()

# --- HUD readouts (orbit / rail / rider) -----------------------------------
_PLATE = Color(0.04, 0.05, 0.08, 0.78)
_y_hud = 116.0


def _hud_line(color, y):
    return Text(
        text="",
        top_left=(24, y + 15),
        font_size=13,
        color=color,
        background=_PLATE,
        stack=False,
    )


hud_orbit = _hud_line(Color(0.82, 0.86, 0.92, 1), _y_hud)
hud_rail = _hud_line(Color(1.0, 0.72, 0.35, 1), _y_hud - 22.0)
hud_rider = _hud_line(Color(0.85, 0.62, 0.95, 1), _y_hud - 44.0)


def _motion_line(name, h):
    v = h.velocity
    return (
        f"{name}  v=({v.x:.0f}, {v.y:.0f})  "
        f"{h.speed:.0f} DU/s  {h.heading:.0f}°  "
        f"u={h.u:.2f}  lap={h.lap}"
    )


st.tracks_on = False


@when(lambda: keyp("SPACE"))
def _toggle_overlay():
    st.tracks_on = not st.tracks_on
    show_tracks(st.tracks_on)
    hud.status = "show_tracks on" if st.tracks_on else "show_tracks off"


def update(dt):
    hud_orbit.text = _motion_line("orbit", h_orbit)
    hud_rail.text = _motion_line("rail", h_rail)
    hud_rider.text = _motion_line("rider", h_rider)
    crawl.begin = (float(crawl.begin) + 0.35 * dt) % 1.0
    crawl.end = (float(crawl.begin) + 0.18) % 1.0


run()
