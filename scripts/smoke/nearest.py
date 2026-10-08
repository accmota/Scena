"""nearest.py — smoke: standalone nearest + group.nearest + within.

Modes (A/S)
-----------
  List      scattered Circles; probe = mouse; highlight winner
  Group     tagged fleet; status shows nearest(...) vs group.nearest(...)
  Within    ring around probe (Q/W radius); winner only inside ring
  Vertices  Polygon; snap highlight to nearest vertex

Usage
-----
    python scripts/smoke/nearest.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1200, 800
init(width=W, height=H, window_scale=0.75, title="Smoke — nearest")
canvas.background = (0.07, 0.08, 0.11, 1)

MODES = ("list", "group", "within", "vertices")
_mode_i = 0
_radius = 120.0

hud = SmokeHud(
    title="nearest",
    expect="Closest item lights up; Within only inside the ring; Vertices snaps to a corner",
    keys="A/S mode  ·  Q/W radius (within)  ·  mouse = origin",
    status="",
)

# --- list / within targets ---------------------------------------------------
_LIST_POS = [
    (220, 280), (420, 520), (680, 300), (880, 560),
    (300, 650), (750, 480), (980, 250), (150, 480),
]
list_targets: list[Circle] = []
for i, (x, y) in enumerate(_LIST_POS):
    c = Circle(center=(x, y), radius=28).set_color("steel blue")
    list_targets.append(c)

# --- group fleet -------------------------------------------------------------
_GROUP_POS = [
    (200, 350), (400, 550), (600, 320), (800, 500), (1000, 380),
]
group_targets: list[Circle] = []
for i, (x, y) in enumerate(_GROUP_POS):
    c = Circle(center=(x, y), radius=30, group="fleet").set_color("orchid")
    group_targets.append(c)

# --- polygon vertices --------------------------------------------------------
poly = Polygon(
    points=[(350, 250), (700, 220), (850, 450), (600, 620), (280, 520)],
).set_color("dim gray")
poly.line_width = 3
poly.fill = None
vertex_marks: list[Circle] = []
for i, p in enumerate(poly.points):
    m = Circle(center=(float(p.x), float(p.y)), radius=10).set_color("gray")
    vertex_marks.append(m)

probe = Circle(center=(W * 0.5, H * 0.5), radius=8).set_color("gold")
probe.line = None
ring = Circle(center=(W * 0.5, H * 0.5), radius=_radius).set_color("gold")
ring.fill = None
ring.line_width = 2
ring.set_alpha(0.45)
link = Line(p1=(0, 0), p2=(1, 1)).set_color("gold")
link.line_width = 2
link.set_alpha(0.7)

_BASE = {
    "list": "steel blue",
    "group": "orchid",
    "within": "steel blue",
    "vertices": "gray",
}


def _set_visible(shapes, on: bool) -> None:
    for s in shapes:
        s.visible = on


def _paint_all(shapes, color: str) -> None:
    for s in shapes:
        try:
            s.set_color(color)
        except Exception:
            pass


def _apply_mode() -> None:
    mode = MODES[_mode_i]
    _set_visible(list_targets, mode in ("list", "within"))
    _set_visible(group_targets, mode == "group")
    poly.visible = mode == "vertices"
    _set_visible(vertex_marks, mode == "vertices")
    ring.visible = mode == "within"
    hud.title = f"nearest — {mode}"


_apply_mode()


def update(dt):
    global _mode_i, _radius

    if keyp.once("A"):
        _mode_i = (_mode_i - 1) % len(MODES)
        _apply_mode()
    if keyp.once("S"):
        _mode_i = (_mode_i + 1) % len(MODES)
        _apply_mode()

    if keyp("Q"):
        _radius = max(20.0, _radius - 180.0 * dt)
    if keyp("W"):
        _radius = min(400.0, _radius + 180.0 * dt)

    ox, oy = float(mouse.x), float(mouse.y)
    probe.move_to(ox, oy)
    ring.move_to(ox, oy)
    ring.radius = _radius

    mode = MODES[_mode_i]
    winner = None
    via = ""

    if mode == "list":
        _paint_all(list_targets, _BASE["list"])
        winner = nearest(mouse, list_targets)
        via = "nearest(mouse, list)"
    elif mode == "group":
        _paint_all(group_targets, _BASE["group"])
        a = nearest(mouse, group["fleet"])
        b = group["fleet"].nearest(mouse)
        winner = a
        same = a is b
        via = f"nearest≡group.nearest? {same}"
    elif mode == "within":
        _paint_all(list_targets, _BASE["within"])
        winner = nearest(mouse, list_targets, within=_radius)
        via = f"within={_radius:.0f}"
    else:
        _paint_all(vertex_marks, _BASE["vertices"])
        winner = nearest(mouse, poly.points)
        via = "nearest(mouse, poly.points)"
        if winner is not None:
            # light the matching mark
            for m, p in zip(vertex_marks, poly.points):
                if p is winner:
                    m.set_color("lime")
                    winner = m
                    break

    if winner is not None and mode != "vertices":
        try:
            winner.set_color("lime")
        except Exception:
            pass

    if winner is not None:
        try:
            wx, wy = float(winner.center.x), float(winner.center.y)
        except Exception:
            wx, wy = float(winner.x), float(winner.y)
        link.visible = True
        link.p1 = (ox, oy)
        link.p2 = (wx, wy)
        d = math.hypot(wx - ox, wy - oy)
        label = getattr(winner, "id", None) or f"({wx:.0f},{wy:.0f})"
        hud.status = f"{via}  →  {label}  d={d:.0f}"
    else:
        link.visible = False
        hud.status = f"{via}  →  None"


run()
