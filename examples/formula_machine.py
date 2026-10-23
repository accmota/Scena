"""Formulas — tutorial 09.

A small machine of shapes linked by formulas, like the cells of a
spreadsheet. A slider writes to the sun's radius; the moon, the wire,
the texts and the spinning hand read the sun, and everything follows.
The sun's color changes in an @on_change; going past radius 100 sets
off a burst (@when). The moon can be released (unlink) and dragged,
and pinned back (@=). Five beads on the wire, made in a for, each keep
their own i (lambda i=i:).

Controls
--------
  Slider "Radius": changes the sun's radius (go past 100 for the burst).
  Button "Release the moon": releases the moon; drag it with the mouse.
  Button "Pin the moon": links the moon to the sun again.

Usage
-----
    python examples/formula_machine.py
"""

from scena import *

init(width=1000, height=700, title="Formulas")
Wallpaper("dark navy")

st.radius_value = 40
Slider(st["radius_value"], label="Radius", min_value=20, max_value=120, only_int=True)

sun = Circle(center=(400, 330), radius=lambda: st.radius_value, color="gold")

def moon_spot():
    return (sun.center.x + sun.radius * 3, sun.center.y)

moon = Circle(
    center=moon_spot,
    radius=lambda: sun.radius / 3,
    color="light steel blue",
)
wire = Line(p1=lambda: sun.center, p2=lambda: moon.center, color="white")

for i in range(1, 6):
    Circle(center=lambda i=i: lerp(sun.center, moon.center, i / 6), radius=4, color="white")

Text(st["radius_value"])
Text(lambda: f"Sun {st.radius_value}   Moon {round(moon.radius)}")

hand = Line(p1=lambda: moon.center, length=lambda: moon.radius * 2, angle=0, color="coral")
hand["angle"] @= lambda: clock.time * 90
spark = Circle(center=lambda: hand.p2, radius=5, color="coral")
spark.glow = True

@on_change(st["radius_value"])
def recolor(value):
    sun.color = Color.from_hsv(value / 200, 0.8, 1)

@when(lambda: sun.radius > 100)
def big():
    canvas.burst_at(sun, radius=150, rings=True)

def unpin():
    moon["center"].unlink()
    moon.draggable = True

def pin():
    if moon.draggable:
        moon.draggable = False
        moon["center"] @= moon_spot

Button(label="Release the moon", on_click=unpin)
Button(label="Pin the moon", on_click=pin)

run()
