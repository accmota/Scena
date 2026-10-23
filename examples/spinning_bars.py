"""Spinning bars — recursive rectangles. Tutorial 30.

A function makes a bar and calls itself to make two smaller ones,
one at each end (left_square_center / right_square_center): the
child's center is a formula over the parent. Each level spins 1.5 times
faster, in the opposite direction. Five levels below the first: 63 bars.

Controls
--------
  panel     Speed, Spin
  M         turns the trail on / off

Usage
-----
    python examples/spinning_bars.py
"""

from scena import *

W, H = 1000, 700
init(width=W, height=H, title="Spinning bars")

Wallpaper(Gradient("ocean", type="radial", size=1000))
Grain()
mt = MotionTrail()

RECURSIONS = 5
RATIO = 1 / 15  # height / length
SIZE_FACTOR = 2
LENGTH = W * 0.5

st.speed = 26
st.spin_factor = -1.5

PALETTE = Palette("lisboa")

Slider(st["speed"], label="Speed", min_value=0, max_value=80)
Slider(st["spin_factor"], label="Spin", min_value=-3, max_value=3)


@when(lambda: keyp("M"))
def toggle_trail():
    mt.enabled = not mt.enabled


def make_bar(depth, center):
    length = LENGTH / (SIZE_FACTOR ** depth)
    height = length * RATIO

    bar = Rect(
        center=center,
        width=length,
        height=height,
        color=PALETTE[depth],
    )

    bar.visual = Aurora()
    bar["angle"] @= lambda: (clock.time * st.speed * (st.spin_factor ** depth)) % 360

    if depth < RECURSIONS:
        make_bar(depth + 1, lambda: bar.left_square_center)
        make_bar(depth + 1, lambda: bar.right_square_center)


make_bar(0, (W / 2, H / 2))
run()
