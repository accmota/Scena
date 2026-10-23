"""Interaction — tutorial 11.

A test bench for the mouse, no game. Three pieces to drag, a trash bin
and a 4 by 3 grid. Dropping a piece in a cell snaps it to the cell's center;
dropping it in the trash bin deletes it, and the bin turns red while a piece
passes over it. The cell under the mouse gets a white frame.

Controls
--------
  MOUSE (drag)         carry a piece to a cell or to the trash bin

Usage
-----
    python examples/interaction.py
"""

from scena import *

init(width=1000, height=700, title="Interaction")
Wallpaper("dark navy")

zone = Box(center=(520, 380), width=400, height=300)
board = zone.grid(4, 3, gap=8)
for cell in board:
    Rect(box=cell, color="#33406a")

light = Rect(box=board.cell(0, 0), color="white")
light.fill = None
light.line_width = 4
light.visible = False

trash = Rect(center=(860, 130), width=160, height=110, color="gray")
Text("trash", center=(860, 130))

Square(center=(120, 560), length=70, color="coral", group="pieces")
Square(center=(120, 440), length=70, color="gold", group="pieces")
Square(center=(120, 320), length=70, color="orchid", group="pieces")
group["pieces"].draggable = True


@drop_by(trash)
def tossed(piece, target, pos):
    piece.destroy()
    trash.color = "gray"


@drag_over(group["pieces"])
def passing(piece, target, pos):
    if target is trash:
        trash.color = "red"
    else:
        trash.color = "gray"


@drag_to(group["pieces"])
def released(piece, target, pos):
    cell = board.cell_at(pos)
    if cell is not None:
        piece.center = cell.center


def update(dt):
    cell = board.cell_at(mouse)
    if cell is None:
        light.visible = False
    else:
        light.visible = True
        light.center = cell.center


run()
