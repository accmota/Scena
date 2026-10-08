"""Sprite size smoke — width / height vs a Square of the same extent.

Row: 5 squares, a sprite under each with ``width=`` the square length.
Column: 5 squares, a sprite beside each with ``height=`` the square length.

Sprites use ``hitbox_shape="rect"`` and collider outlines stay on so the design-unit
box is visible. Left/right edges of the row sprites should match the square
above; top/bottom edges of the column sprites should match the square beside.

Arts: ninja Attack__002 / Dead__006, Fly (1), enemyGreen1, plane.

Controls
--------
  C       toggle collider outlines

Usage
-----
    python scripts/smoke/sprite_size.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
SIZE = 80.0
ARTS = (
    "../../examples/media/ninja/Attack__002.png",
    "../../examples/media/plane/Fly1.png",
    "../../examples/media/space/enemyGreen1.png",
    "../../examples/media/ninja/Dead__006.png",
    "../../examples/media/plane/Fly2.png",
)

init(width=W, height=H, window_scale=0.75, title="Smoke — sprite size")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Sprite size",
    expect="Row: sprite width = square. Column: sprite height = square. Green rect = collider.",
    keys="C colliders",
    status="",
)

_guide = Color(1.0, 1.0, 1.0, 0.16)
_caption = Color(0.55, 0.85, 1.0, 1)
_hint = Color(0.55, 0.6, 0.7, 1)
_sq_fill = "gold"


def _guide_line(p1, p2):
    ln = Line(p1=p1, p2=p2).set_color(_guide)
    ln.line_width = 1
    return ln


def _square(cx, cy):
    sq = Square(center=(cx, cy), length=SIZE).set_color(_sq_fill)
    sq.set_alpha(0.35)
    return sq


def _label(text, x, y, *, size=12, color=None):
    return Text(
        text=text,
        top_left=(x, y + 15),
        font_size=size,
        color=color or Color(0.78, 0.84, 0.94, 1),
    )


def _short(name: str) -> str:
    return name[:-4] if name.lower().endswith(".png") else name


# --- width row (left) -------------------------------------------------------
Text(text="width = square", top_left=(40, H - 112), font_size=15, color=_caption)
Text(
    text="sprite.width matches the square; left/right edges should line up",
    top_left=(40, H - 138), font_size=12, color=_hint,
)

_row_xs = (100.0, 240.0, 380.0, 520.0, 660.0)
_row_sq_y = 680.0
_row_spr_y = 520.0
_half = SIZE * 0.5

_width_sprites: list[Sprite] = []
for i, (art, x) in enumerate(zip(ARTS, _row_xs)):
    _square(x, _row_sq_y)
    spr = Sprite(
        art, width=SIZE, center=(x, _row_spr_y),
        hitbox_shape="rect",
    )
    spr.collidable = True
    _width_sprites.append(spr)
    sh = float(spr.height)
    top = _row_sq_y + _half
    bot = _row_spr_y - sh * 0.5 - 8.0
    _guide_line((x - _half, top), (x - _half, bot))
    _guide_line((x + _half, top), (x + _half, bot))
    _label(
        f"{_short(art)}\n{float(spr.width):.0f}×{sh:.0f}",
        x - 52, _row_spr_y - sh * 0.5 - 28,
    )


# --- height column (right) --------------------------------------------------
Text(text="height = square", top_left=(800, H - 112), font_size=15, color=_caption)
Text(
    text="sprite.height matches the square; top/bottom edges should line up",
    top_left=(800, H - 138), font_size=12, color=_hint,
)

_col_x = 880.0
_col_ys = (680.0, 545.0, 410.0, 275.0, 140.0)
_gap = 28.0

_height_sprites: list[Sprite] = []
for i, (art, y) in enumerate(zip(ARTS, _col_ys)):
    _square(_col_x, y)
    spr = Sprite(
        art, height=SIZE, center=(_col_x, y),
        hitbox_shape="rect",
    )
    spr.collidable = True
    sw = float(spr.width)
    spr.move_to(_col_x + _half + _gap + sw * 0.5, y)
    _height_sprites.append(spr)
    left = _col_x - _half
    right = float(spr.center.x) + sw * 0.5 + 8.0
    _guide_line((left, y + _half), (right, y + _half))
    _guide_line((left, y - _half), (right, y - _half))
    _label(
        f"{_short(art)}  {sw:.0f}×{float(spr.height):.0f}",
        1140,
        y - 8,
    )

st.show_col = True
collision.show_colliders(True)


def _status() -> None:
    bits = []
    for spr, art in zip(_width_sprites, ARTS):
        bits.append(f"{_short(art)} w={float(spr.width):.1f}×{float(spr.height):.1f}")
    hud.status = (
        f"outlines {'ON' if st.show_col else 'OFF'}  ·  "
        f"square={SIZE:.0f}  ·  " + "  ".join(bits)
    )


_status()


def on_key_down(key):
    if key == "C":
        st.show_col = not bool(st.show_col)
        collision.show_colliders(bool(st.show_col))
        _status()


run()
