"""Level sheets smoke — a level file's image items in every form, as the game loads them.

``level_sheets.json`` (beside this script; open it in the editor to compare)
holds four rows of image items:

  file         a whole picture (``file``): as is, turned 30°, stretched, half size
  cols × rows  frames of a 4 × 3 numbered grid (``cols`` / ``rows``): 0, 5, 11,
               6 at twice the size, 9 turned 45° — the number drawn is the frame
  cell         the same numbered grid cut by cell size (``cell`` 48 × 48): 3, 7, 10,
               1 at twice the size — a second entry for one file, cut another way
  atlas        frames of the Kenney atlas (``atlas``): by name, and frame 3 by index
               (ball_blue_large), block_corner turned 90°

Each item is made with ``item.make()``; a thin rectangle is the item's box
(``item.box``), so the art should fill it exactly. The label under an item is
its frame (an atlas frame asked by index also shows the name it resolves to). The status line checks
every made Sprite against the file: center, size, angle and, for a frame,
``sprite.frame == item.sheet.frame_index(item.frame)``.

The numbered grid is ``_level_sheets/grade_numerada.png`` (4 × 3 cells of 48 px,
each showing its index, made with skia for this test).

Controls
--------
  C              toggle the box outlines
  SPACE          play / stop the clip "conta" (frames 0–11) on the grid row:
                 a clip registered on level.sheet("grade") plays on make()'s Sprites
  Arrows         pan; Shift+↑ / ↓ zoom

Usage
-----
    python scripts/smoke/level_sheets.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, apply_camera

W, H = 1280, 800

init(width=W, height=H, window_scale=0.75, title="Smoke — level sheets")
canvas.background = (0.07, 0.08, 0.11, 1)

fase = Level("level_sheets.json")

hud = SmokeHud(
    title="Level sheets",
    expect="Each picture fills its box; each number drawn = the label under it. Compare with "
           "the editor: python -m scena_editor scripts/smoke/level_sheets.json",
    keys="C outlines · SPACE play / stop the grid clip · arrows pan · Shift+↑/↓ zoom",
    status="",
)

_box_line = Color(0.55, 0.85, 1.0, 0.7)
_label_ink = Color(0.78, 0.84, 0.94, 1)
_row_ink = Color(0.95, 0.82, 0.45, 1)

ROWS = {
    "arquivo": "file (whole picture)",
    "grade": "cols 4 × rows 3",
    "celula": "cell 48 × 48",
    "atlas": "atlas (xml)",
}

made: list[tuple[LevelItem, Sprite]] = []
outlines: list[Rect] = []
for item in fase:
    sprite = item.make()
    made.append((item, sprite))
    box = Rect(box=item.box)
    box.fill = None
    box.line = _box_line
    box.line_width = 1
    outlines.append(box)
    if item.groups[0] == "arquivo":
        what = item.name
    elif isinstance(item.frame, int) and item.groups[0] == "atlas":
        what = f"{item.frame} → {item.sheet.names[item.frame]}"
    else:
        what = str(item.frame)
    turn = math.radians(item.angle)        # half the height of the turned box's bounds
    half = (abs(item.width * math.sin(turn)) + abs(item.height * math.cos(turn))) / 2
    Text(text=what, center=(item.center.x, item.center.y - half - 14),
         font_size=12, color=_label_ink)

for group, caption in ROWS.items():
    row = fase.group(group)
    Text(text=caption, center=(1060, row[0].center.y), font_size=15, color=_row_ink)

hud.aux = "sheets: " + ", ".join(fase.sheets)


def _mismatches() -> list[str]:
    """What a made Sprite does not take from the file (empty when all match)."""
    bad = []
    for item, s in made:
        if (round(s.center.x, 6), round(s.center.y, 6)) != (item.center.x, item.center.y):
            bad.append(f"{item.name}: center")
        if (round(s.width, 6), round(s.height, 6)) != (item.width, item.height):
            bad.append(f"{item.name}: size {s.width:g}×{s.height:g}")
        if round((s.angle - item.angle) % 360, 6) not in (0, 360):
            bad.append(f"{item.name}: angle {s.angle:g}")
        if item.groups[0] != "arquivo" and not playing:
            if s.frame != item.sheet.frame_index(item.frame):
                bad.append(f"{item.name}: frame {s.frame}")
    return bad


playing = False
fase.sheet("grade").clip("conta", list(range(12)), fps=3)


def _status() -> None:
    bad = _mismatches()
    check = (f"all {len(made)} images match the file (center, size, angle, frame)"
             if not bad else "MISMATCH: " + "; ".join(bad))
    hud.status = f"{check}  ·  outlines {'on' if outlines[0].visible else 'off'}" + (
        "  ·  grid clip playing" if playing else "")


_status()


def on_key_down(key):
    global playing
    if key == "C":
        for box in outlines:
            box.visible = not box.visible
    elif key == "SPACE":
        playing = not playing
        for item, s in made:
            if item.groups[0] == "grade":
                if playing:
                    s.play("conta")
                else:
                    s.frame = item.frame          # back to the file's frame
    _status()


def update(dt):
    apply_camera(dt)


run()
