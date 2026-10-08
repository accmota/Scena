"""group_formula.py — smoke: live formula groups vs frozen snapshot.

Modes (A/S)
-----------
  union    group["combo"] @= lambda: group["left"] | group["right"]
  filter   combo = union filtered to y > mid
  nested   mid @= left|right; combo @= mid (same members, nested name)
  frozen   hold (left | right) once — gold does not follow later joins

Keys
----
  SPACE spawn left   Q spawn right   W destroy one combo member   U unlink

Gold fill = current combo membership (join order). Control: frozen stays put.
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, TOP_BAND, SAFE_BOTTOM

W, H = 1200, 800
init(width=W, height=H, window_scale=0.75, title="Smoke — group formula")
canvas.background = (0.07, 0.08, 0.11, 1)

MODES = ("union", "filter", "nested", "frozen")
_mode_i = 0
_n = 0
_frozen = None
_MID_Y = H * 0.48

hud = SmokeHud(
    title="group formula — union",
    expect="Gold = group['combo'] now; frozen ignores later spawns; U clears the name",
    keys="A/S mode  ·  SPACE left  ·  Q right  ·  W kill combo  ·  U unlink",
    status="",
)

LEFT_X, RIGHT_X = 280.0, 920.0
_BASE = {"left": "steel blue", "right": "orchid"}


def _spawn(tag: str, x: float) -> Circle:
    global _n
    _n += 1
    y = 160.0 + ((_n * 47) % int(H - TOP_BAND - SAFE_BOTTOM - 80))
    c = Circle(center=(x, y), radius=22, group=tag)
    c.set_color(_BASE[tag])
    c.hp = 1
    c.n = _n  # spawn number, shown in the join-order readout
    return c


def _bind_formula() -> None:
    global _frozen
    mode = MODES[_mode_i]
    if group["combo"].is_linked:
        group["combo"].unlink()
    if group["mid"].is_linked:
        group["mid"].unlink()
    _frozen = None
    if mode == "union":
        group["combo"] @= lambda: group["left"] | group["right"]
    elif mode == "filter":
        group["combo"] @= lambda: (group["left"] | group["right"]).filter(
            lambda c: float(c.center.y) > _MID_Y
        )
    elif mode == "nested":
        group["mid"] @= lambda: group["left"] | group["right"]
        group["combo"] @= lambda: group["mid"]
    else:
        _frozen = group["left"] | group["right"]
    hud.title = f"group formula — {mode}"


def _combo_members():
    if _frozen is not None:
        return list(_frozen)
    return list(group["combo"])


def _paint() -> None:
    gold = set(_combo_members())
    for c in list(group["left"]) + list(group["right"]):
        c.set_color("gold" if c in gold else _BASE["left" if c.tagged("left") else "right"])


_spawn("left", LEFT_X)
_spawn("left", LEFT_X)
_spawn("right", RIGHT_X)
_bind_formula()
_paint()

Line(p1=(80, _MID_Y), p2=(W - 80, _MID_Y)).set_color("dim gray")
Text(
    text="filter: gold only above this line",
    top_left=(80, _MID_Y + 32),
    font_size=12,
    color=Color(0.55, 0.6, 0.7, 1),
)


def update(dt):
    global _mode_i

    if keyp.once("A"):
        _mode_i = (_mode_i - 1) % len(MODES)
        _bind_formula()
    if keyp.once("S"):
        _mode_i = (_mode_i + 1) % len(MODES)
        _bind_formula()
    if keyp.once("SPACE"):
        _spawn("left", LEFT_X)
    if keyp.once("Q"):
        _spawn("right", RIGHT_X)
    if keyp.once("W"):
        members = _combo_members()
        if members:
            members[0].destroy()
    if keyp.once("U"):
        if group["combo"].is_linked:
            group["combo"].unlink()
        if group["mid"].is_linked:
            group["mid"].unlink()

    _paint()
    members = _combo_members()
    linked = group["combo"].is_linked
    hud.status = (
        f"combo {len(members)}  linked={linked}  "
        f"left={group['left'].count}  right={group['right'].count}  "
        f"order={[m.n for m in members]}"
    )

run()