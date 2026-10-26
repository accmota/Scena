"""Canopy: a tree of light that is one rule, repeated.

Every branch is a Line that starts where its parent ends, turns a little
from its parent's direction and is a little shorter. That is the whole
tree: one recursive function, grow(), lays all 511 branches every frame,
and a few numbers in st change it. Turn the branches wider and the tree
becomes a circuit, a coral, a fern, and back. Nothing else is placed by
hand: a change at the trunk runs to the last twig.

  I    Seed      the tree grows, a level at a time
  II   Wind      it sways; the sway grows as it climbs
  III  Shapes    the branching angle turns: a circuit, then a coral that spins
  IV   Spiral    the two sides turn unequally: the tree curls into a fern

The sky is still dust that changes colour slowly; embers rise in front.
The camera drifts, and the two layers follow it at different rates
(pan_response), so the sky is far and the embers near.

Things to try
-------------
  Change DEPTH            more levels: 2 ** DEPTH twigs (slower)
  Change st.ratio         how much shorter each branch is than its parent
  Change the storyboard   other angles, other leans

No keys: it loops (close the window to stop).
"""
from math import sin
from scena import *

init(width=1280, height=800, title="Canopy")
canvas.set_origin("center")
canvas.background = "#03040a"

# the far sky: still dust (speed 0) whose colours the storyboard changes
sky = Nebuladust(amount=0.8, speed=0, alpha=0.45, pan_response=0.1, zoom_response=0.1)
# near: embers rising, they follow the camera more than the sky does
Embers(color="gold", density=0.45, rise=0.35, alpha=0.7, pan_response=0.9, zoom_response=0.7)
light = Bloom(intensity=1.1)
Grade("filmic", saturation=1.1)
ColorSweep(["deep sky blue", "orange"], amount=0.2, speed=0.15)
Vignette(amount=0.8)

DEPTH = 8
TRUNK = 140
SKY = Colormap.from_colors("#101a4a", "#3a1450", "#0b3a4a", "#101a4a")
LIGHT = Colormap.from_colors("#3b2a8a", "medium orchid", "hot pink", "orange", "light yellow")

st.grow = 0         # how many levels have grown (a level grows from 0 to 1)
st.spread = 24      # degrees each branch turns away from its parent
st.lean = 0         # extra turn to the same side for every branch (curls the tree)
st.ratio = 0.72     # each branch is this much of its parent's length
st.sway = 0         # wind
st.turn = 90        # the trunk's direction
st.dusk = 0         # where the sky is on its colours (SKY)
st.root = -380      # the height of the foot of the trunk


def update(dt):
    # a background does not link: its colours are written each frame
    sky.color = SKY.get_color(st.dusk)
    sky.color2 = SKY.get_color((st.dusk + 0.33) % 1)
    sky.color3 = SKY.get_color((st.dusk + 0.66) % 1)
    grow(0, st.root, st.turn, 0, 0)


def growth(depth):
    """0 before this level starts growing, 1 when it is grown."""
    return min(1, max(0, st.grow - depth))


branches = []        # (line, depth), in the order grow() walks them


def make(depth):
    """A branch and, recursively, the two branches on its end."""
    line = Line(p1=(0, 0), p2=(0, 1), line_width=12 * 0.7 ** depth,
                color=LIGHT.get_color(depth / DEPTH))
    branches.append((line, depth))
    if depth < DEPTH:
        make(depth + 1)
        make(depth + 1)


def grow(x, y, angle, depth, i):
    """Lay branch i at (x, y), turned to angle; then its two children. Returns the next i."""
    line = branches[i][0]
    length = TRUNK * st.ratio ** depth * growth(depth)
    end = vec_from_angle(angle, length)
    line.p1 = (x, y)
    line.p2 = (x + end.x, y + end.y)
    i += 1
    if depth < DEPTH:
        wind = st.sway * (depth + 1) * sin(clock.time * 1.3 - depth * 0.5)
        for side in (-1, 1):
            i = grow(x + end.x, y + end.y, angle + side * st.spread + st.lean + wind, depth + 1, i)
    return i


make(0)


async def show():
    while True:
        # I  Seed: the tree grows a level at a time
        canvas.fade_in(2)
        st.dusk = 0
        tween(st["dusk"], 1, time=75)
        await tween(st["grow"], DEPTH + 1, time=10, ease="ease_in_out")
        # II  Wind: it sways, the camera drifts
        tween(st["sway"], 1.2, time=4, ease="ease_in_out")
        canvas.pan_to(-120, 40, time=10, ease="ease_in_out")
        canvas.zoom_to(1.25, time=10, ease="ease_in_out")
        await wait(10)
        # III  Shapes: wider and wider: circuit, coral, snowflake
        tween(st["sway"], 0.3, time=4)
        canvas.pan_to(0, 0, time=8, ease="ease_in_out")
        canvas.zoom_to(1, time=8, ease="ease_in_out")
        tween(st["root"], -160, time=8, ease="ease_in_out")
        tween(st["ratio"], 0.78, time=8, ease="ease_in_out")
        await tween(st["spread"], 90, time=8, ease="ease_in_out")
        await wait(3)
        tween(st["turn"], 450, time=24, ease="ease_in_out")
        await tween(st["spread"], 60, time=10, ease="ease_in_out")
        await wait(6)
        # IV  Spiral: one side turns more than the other
        tween(st["root"], -300, time=8, ease="ease_in_out")
        tween(st["ratio"], 0.72, time=8, ease="ease_in_out")
        await tween(st["lean"], 25, time=8, ease="ease_in_out")
        canvas.pan_to(80, 60, time=12, ease="ease_in_out")
        await tween(st["spread"], 35, time=8, ease="ease_in_out")
        await wait(4)
        await tween(st["lean"], 0, time=6, ease="ease_in_out")
        # the tree shrinks back into its seed
        canvas.pan_to(0, 0, time=6, ease="ease_in_out")
        await tween(st["grow"], 0, time=6, ease="ease_in")
        canvas.fade_out(1.5)
        await wait(1.5)
        st.spread, st.lean, st.sway, st.turn, st.root = 24, 0, 0, 90, -380


run_task(show)
run()
