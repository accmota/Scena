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

Any other item (the four 40 × 40 rects in the corners) is made too, so the
level's edges show where they are. The window is the level: as wide as
``fase.size`` and as tall plus the HUD band above it, the camera untouched,
so one level unit is one window unit and the level's bounds (``fase.box``, the
thin gold frame) meet the window's left, right and bottom edges.

Each image is made with ``item.make()``; a thin rectangle is the item's box
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

# The level decides the window: read it first (Level only reads a file).
fase = Level("level_sheets.json")
LEVEL_W, LEVEL_H = fase.size
HUD_BAND = 160                      # above the level: the HUD's lines

init(width=LEVEL_W, height=LEVEL_H + HUD_BAND, window_scale=0.75,
     title="Smoke — level sheets")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Level sheets",
    expect="Each picture fills its box; each number drawn = the label under it; the corner rects "
           "touch the gold level frame. Editor: python -m scena_editor scripts/smoke/level_sheets.json",
    keys="C outlines · SPACE play / stop the grid clip · arrows pan · Shift+↑/↓ zoom",
    status="",
)

_box_line = Color(0.55, 0.85, 1.0, 0.7)
_level_line = Color(0.95, 0.82, 0.45, 0.9)
_label_ink = Color(0.78, 0.84, 0.94, 1)
_row_ink = Color(0.95, 0.82, 0.45, 1)

ROWS = {
    "arquivo": "file (whole picture)",
    "grade": "cols 4 × rows 3",
    "celula": "cell 48 × 48",
    "atlas": "atlas (xml)",
}

level_frame = Rect(box=fase.box)
level_frame.fill = None
level_frame.line = _level_line
level_frame.line_width = 1


def frame_of(item):
    """The item's frame, or None for a whole picture or another kind."""
    try:
        return item.frame
    except AttributeError:
        return None


made: list[tuple[LevelItem, Graphic]] = []
outlines: list[Rect] = []
for item in fase:
    shape = item.make()
    made.append((item, shape))
    if item.kind != "image":
        shape.fill = Color(0.55, 0.85, 1.0, 0.25)
        shape.line = _box_line
        continue
    box = Rect(box=item.box)
    box.fill = None
    box.line = _box_line
    box.line_width = 1
    outlines.append(box)
    frame = frame_of(item)
    if frame is None:
        what = item.name
    elif isinstance(frame, int) and "atlas" in item.groups:
        what = f"{frame} → {item.sheet.names[frame]}"
    else:
        what = str(frame)
    turn = math.radians(item.angle)        # half the height of the turned box's bounds
    half = (abs(item.width * math.sin(turn)) + abs(item.height * math.cos(turn))) / 2
    Text(text=what, center=(item.center.x, item.center.y - half - 14),
         font_size=12, color=_label_ink)

for group, caption in ROWS.items():
    row = fase.group(group)
    Text(text=caption, center=(1060, row[0].center.y), font_size=15, color=_row_ink)

hud.aux = (f"level {LEVEL_W:g} × {LEVEL_H:g} (fase.size) = window width; window height "
           f"{LEVEL_H + HUD_BAND:g} (+ HUD)  ·  sheets: " + ", ".join(fase.sheets))


def _mismatches() -> list[str]:
    """What a made shape does not take from the file (empty when all match)."""
    bad = []
    for item, s in made:
        label = item.name or f"{item.kind} at {item.center.x:g}, {item.center.y:g}"
        if (round(s.center.x, 6), round(s.center.y, 6)) != (item.center.x, item.center.y):
            bad.append(f"{label}: center")
        if (round(s.width, 6), round(s.height, 6)) != (item.width, item.height):
            bad.append(f"{label}: size {s.width:g}×{s.height:g}")
        if round((s.angle - item.angle) % 360, 6) not in (0, 360):
            bad.append(f"{label}: angle {s.angle:g}")
        frame = frame_of(item)
        if frame is not None and not playing and s.frame != item.sheet.frame_index(frame):
            bad.append(f"{label}: frame {s.frame}")
    return bad


playing = False
fase.sheet("grade").clip("conta", list(range(12)), fps=3)


def _status() -> None:
    bad = _mismatches()
    check = (f"all {len(made)} items match the file (center, size, angle, frame)"
             if not bad else "MISMATCH: " + "; ".join(bad))
    hud.status = f"{check}  ·  outlines {'on' if outlines[0].visible else 'off'}" + (
        "  ·  grid clip playing" if playing else "")


_status()


def on_key_down(key):
    global playing
    if key == "C":
        for box in outlines + [level_frame]:
            box.visible = not box.visible
    elif key == "SPACE":
        playing = not playing
        for item, s in made:
            if "grade" in item.groups:
                if playing:
                    s.play("conta")
                else:
                    s.frame = item.frame          # back to the file's frame
    _status()


def update(dt):
    apply_camera(dt)


run()
