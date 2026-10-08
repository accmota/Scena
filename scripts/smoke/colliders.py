"""colliders.py — smoke: collision outlines track pose (rotate / scale / atlas).

One of each Shape family plus a PNG sprite and an atlas clip. Bodies orbit
their rest point and spin. Green debug strokes are the hitboxes — fill/line
stay off green at 50% alpha so the overlay is readable.

Controls
--------
  SPACE     pause / resume
  C         toggle collider outlines (starts ON)
  sliders   size (scale) · outline width (shapes)

Usage
-----
    python scripts/smoke/colliders.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, SAFE_BOTTOM, cycle_quality

W, H = 1400, 900
init(width=W, height=H, window_scale=0.78, title="Smoke — collider boundaries")
canvas.background = (0.07, 0.08, 0.11)
SkyGradient("night")
Stars(density=0.35, twinkle=0.1)

hud = SmokeHud(
    title="Collider boundaries",
    expect="Green stroke = hitbox. Must spin with the body (Track.arc = tube, not disk) and match drawn size.",
    keys="SPACE pause  ·  C outlines  ·  E quality  ·  sliders scale / line width",
    status="outlines ON",
    show_aux=True,
)

st.create("body_scale", initial=1.0)
st.create("line_w", initial=2.0)

Slider(
    st.body_scale, label="size (scale)", min_value=0.45, max_value=2.2,
    top_left=(24, SAFE_BOTTOM + 100), width=260, show_value=True,
)
Slider(
    st.line_w, label="outline width", min_value=0.5, max_value=14.0,
    top_left=(24, SAFE_BOTTOM + 56), width=260, show_value=True,
)

# No green / lime / sea green — those fight the collider overlay.
_COLORS = (
    "dodger blue", "orange", "gold", "magenta",
    "coral", "tomato", "plum", "hot pink",
    "sky blue", "yellow", "white", "slate gray",
)

_paused = False
_t = 0.0
_outlines = True
collision.show_colliders(True)

space = Sheet("../../examples/media/shooter/sheet.xml")
space.clip("green", ["enemyGreen1.png", "enemyGreen2.png"], fps=6)


def _tint(name: str) -> Color:
    c = Color(name)
    c.alpha = 0.5
    return c


def _style(obj, name: str):
    c = _tint(name)
    obj.set_color(c)
    obj.line = _tint(name)
    obj.collidable = True
    obj.draggable = True
    obj.tag("lab")
    return obj


# Grid of rest points (clear of HUD ~130 and bottom sliders / FPS).
_XS = (220, 500, 780, 1060)
_YS = (620, 420, 220)
_homes: list = []
_bodies: list = []
_spins: list = []  # deg/s
_orbits: list = []  # (radius, omega, phase)


def _place(obj, col: int, row: int, *, spin: float, orbit: float, omega: float, phase: float):
    hx, hy = _XS[col], _YS[row]
    obj.move_to(hx, hy)
    _homes.append((hx, hy))
    _bodies.append(obj)
    _spins.append(spin)
    _orbits.append((orbit, omega, phase))
    return obj


# --- one of each Shape -------------------------------------------------------
_place(
    _style(Circle(radius=36, group="lab"), _COLORS[0]),
    0, 0, spin=40, orbit=38, omega=0.9, phase=0.0,
)
_place(
    _style(Ellipse(width=96, height=46, angle=0), _COLORS[1]),
    1, 0, spin=-55, orbit=42, omega=1.1, phase=0.7,
)
_place(
    _style(Rect(width=88, height=48, angle=0, corner_radius=40), _COLORS[2]),
    2, 0, spin=70, orbit=40, omega=0.85, phase=1.4,
)
_place(
    _style(Square(length=58, angle=0), _COLORS[3]),
    3, 0, spin=-48, orbit=36, omega=1.05, phase=2.1,
)
_place(
    _style(RegularPolygon(n=6, radius=38, angle=0), _COLORS[4]),
    0, 1, spin=80, orbit=40, omega=0.95, phase=0.4,
)
_place(
    _style(EquilateralTriangle(radius=44, angle=0), _COLORS[5]),
    1, 1, spin=-65, orbit=38, omega=1.15, phase=1.1,
)
_poly = _style(
    Polygon(
        points=[(0, 28), (32, 12), (22, -26), (-8, -22), (-30, 6), (-12, 30)],
    ),
    _COLORS[6],
)
_place(_poly, 2, 1, spin=50, orbit=36, omega=0.8, phase=1.8)
_rod = _style(
    Line(center=(0, 0), length=110, angle=0),
    _COLORS[7],
)
_rod.line_width = 8
_place(_rod, 3, 1, spin=-90, orbit=34, omega=1.2, phase=2.5)
_pt = _style(Point(0, 0), _COLORS[8])
_place(_pt, 0, 2, spin=30, orbit=28, omega=1.4, phase=0.2)

# Track.arc — stroke tube (green overlay follows the curve, not a disk).
_arc = _style(
    Track.arc(
        center=(0, 0), radius=48, from_angle=-30, to_angle=210,
        color=_COLORS[0], line_width=8,
    ),
    _COLORS[0],
)
_place(_arc, 3, 2, spin=55, orbit=36, omega=1.05, phase=1.6)

# PNG sprite (plane) + atlas clip (same enemy as Galaga: sheet then play()).
_plane = _style(
    Sprite("../../examples/media/plane/Fly1.png", height=56, hitbox_shape="auto"),
    _COLORS[9],
)
_place(_plane, 1, 2, spin=45, orbit=40, omega=0.9, phase=3.0)

_wasp = Sprite(space, height=58, hitbox_shape="auto", group="lab")
_wasp.play("green")
_wasp.collidable = True
_wasp.draggable = True
_place(_wasp, 2, 2, spin=-70, orbit=42, omega=1.0, phase=0.9)

_labels = []
for body, (hx, hy) in zip(_bodies, _homes):
    _labels.append(Text(
        text=type(body).__name__,
        top_left=(hx - 40, hy - 63), font_size=13,
        color=Color(0.7, 0.75, 0.85, 1),
    ))


@collide("lab", "lab")
def on_lab_hit(me, other, info):
    pt = info.point
    if pt:
        hud.status = f"{me} ↔ {other}  @ ({pt[0]:.0f}, {pt[1]:.0f})"


def update(dt):
    global _t
    if not _paused:
        _t += dt
    scale = float(st.body_scale)
    lw = float(st.line_w)
    for i, body in enumerate(_bodies):
        hx, hy = _homes[i]
        rad, omega, phase = _orbits[i]
        a = _t * omega + phase
        if not _paused:
            body.move_to(hx + rad * math.cos(a), hy + rad * math.sin(a * 1.15))
            # Slot assign (``.angle =``) is the stale-cache path Rect/hex used to miss.
            ang = _spins[i] * _t
            if hasattr(type(body), "angle") and getattr(type(body).angle, "_is_field_slot", False):
                body.angle = ang
            else:
                body.angle = ang
        body.scale = scale
        if not isinstance(body, Sprite):
            body.line_width = lw
        _labels[i].top_left = (hx - 40, hy - 63)
    hud.aux = (
        f"t={_t:.1f}  scale={scale:.2f}  line_w={lw:.1f}  "
        f"{'PAUSED' if _paused else 'moving'}"
    )


def on_key_down(key):
    global _paused, _outlines
    if key == "SPACE":
        _paused = not _paused
        hud.status = "paused" if _paused else "moving"
    elif key == "C":
        _outlines = not _outlines
        collision.show_colliders(_outlines)
        hud.status = f"outlines {'ON' if _outlines else 'OFF'}"
    elif key == "E":
        hud.status = f"quality={cycle_quality()}"


run()
