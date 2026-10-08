"""
geom.py — smoke: outline intersections + closest_point.

Rule (on-canvas): same color → white dots at outline crossings;
different color → no dots even if outlines cross.
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — geometry queries")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Geometry queries",
    expect="Same color → dots; different color → no dots",
    keys="drag / wheel  ·  A/S bead target  ·  mouse → closest_point",
    status="drag shapes…",
)

_CAPTION = Color(0.7, 0.85, 1.0, 1)
_MUTED = Color(0.5, 0.55, 0.62, 1)

Text(
    text="SAME COLOR → white dots where outlines cross",
    top_left=(40, H - 131), font_size=16, color=_CAPTION,
)
Text(
    text="DIFFERENT COLOR → no dots (even if outlines cross — drag to check)",
    top_left=(40, H - 155), font_size=14, color=_MUTED,
)
Text(
    text="Gold chord = the two cyan circles  ·  Lime bead = closest_point (A/S)",
    top_left=(40, H - 179), font_size=13, color=_MUTED,
)


def _stroke(shape, color, *, width=3):
    shape.set_color(color)
    shape.fill = None
    shape.line_width = width
    shape.draggable = True
    if not isinstance(shape, Line):
        shape.wheel_rotate = True
    return shape


# --- Cyan group (2 circles + chord + ellipse) --------------------------------
c1 = _stroke(Circle(center=(520, 620), radius=100), "cyan")
c2 = _stroke(Circle(center=(660, 620), radius=90), "cyan")
cyan_line = _stroke(
    Line(p1=(400, 720), p2=(780, 520)), "cyan", width=4,
)

chord = Line(
    p1=lambda: intersection(c1, c2, 0),
    p2=lambda: intersection(c1, c2, 1),
    color="gold",
)
chord.line_width = 4
cyan_ell = _stroke(
    Ellipse(center=(590, 500), width=220, height=90, angle=28),
    "cyan",
)

# --- Orange group ------------------------------------------------------------
sq = _stroke(Square(center=(180, 580), length=110, angle=18), "orange")
rect = _stroke(
    Rect(center=(200, 380), width=140, height=80, angle=-12),
    "orange",
)
orange_line = _stroke(
    Line(p1=(60, 220), p2=(360, 480)), "orange", width=4,
)

# --- Violet group ------------------------------------------------------------
tri = _stroke(
    EquilateralTriangle(center=(980, 620), radius=70), "violet",
)
hexagon = _stroke(
    RegularPolygon(n=6, center=(1180, 560), radius=65, angle=10),
    "violet",
)
poly = Polygon(
    points=[(900, 280), (1080, 260), (1120, 380), (1020, 440), (880, 400)],
)
_stroke(poly, "violet")
violet_line = _stroke(
    Line(p1=(820, 180), p2=(1280, 420)), "violet", width=4,
)

# Color teams: only pairs inside a team get dots
_TEAMS = (
    (c1, c2, cyan_line, cyan_ell),
    (sq, rect, orange_line),
    (tri, hexagon, poly, violet_line),
)

bodies = [s for team in _TEAMS for s in team]

_MAX_DOTS = 40
_dots = [
    Circle(center=(0, 0), radius=6, color="white")
    for i in range(_MAX_DOTS)
]
for d in _dots:
    d.visible = False

_bead_i = 0
bead = Circle(center=(520, 620), radius=10, color="lime")


def update(dt):
    # Gold chord: cyan circles only
    n_chord = len(intersections(c1, c2))
    chord.visible = n_chord == 2

    used = 0
    total = 0
    for team in _TEAMS:
        for i, a in enumerate(team):
            for b in team[i + 1 :]:
                for x, y in intersections(a, b):
                    total += 1
                    if used >= _MAX_DOTS:
                        continue
                    d = _dots[used]
                    d.visible = True
                    d.center._takein((x, y))
                    used += 1
    for d in _dots[used:]:
        d.visible = False

    target = bodies[_bead_i]
    bead.center._takein(closest_point(target, (mouse.x, mouse.y)))

    chord_note = (
        "chord on" if n_chord == 2
        else ("chord tangent" if n_chord == 1 else "chord off")
    )
    hud.status = (
        f"same-color crossings: {total}  ·  {chord_note}  ·  "
        f"bead→{target} (A/S)"
    )


def on_key_down(key):
    global _bead_i
    if key == "A":
        _bead_i = (_bead_i - 1) % len(bodies)
    elif key == "S":
        _bead_i = (_bead_i + 1) % len(bodies)


run()
