"""Oscilloscope — a tip spins around the ball and leaves a trail. Tutorial 30.

The tip is a Point with a formula: a circle of radius 200 around the ball,
plus a smaller circle (x1, y1) that makes tx1 / ty1 turns for each big turn.
The angle, st.time, moves forward in update, so changing the speed does not
make the tip jump. The panel writes to st; the formula reads st every
frame. Clicking the ball switches on the beam and the trail.

Controls
--------
  click     on the ball: switches on the beam and the trail
  panel     n (speed), x1 / y1 (size of the small spin),
            tx1 / ty1 (turns of the small spin)

Usage
-----
    python examples/oscilloscope.py
"""

from scena import *
from math import cos, sin

W, H = 1000, 720
init(width=W, height=H, title="Oscilloscope")

ui.scale = 0.9

st.n = 4
st.x1 = 60
st.tx1 = 6
st.y1 = 60
st.ty1 = 6
st.switched_on = False
Slider(st["n"], label="n", min_value=1, max_value=6)
Slider(st["x1"], label="x1", min_value=-100, max_value=100)
Slider(st["tx1"], label="tx1", min_value=-10, max_value=10, only_int=True)
Slider(st["y1"], label="y1", min_value=-100, max_value=100)
Slider(st["ty1"], label="ty1", min_value=-10, max_value=10, only_int=True)


ball = Circle(center=(W * 0.6, H * 0.5), radius=20, color="red")
ball.visual = Beat()

st.time = 0


def update(dt):
    st.time += dt * st.n


tip = Point()
tip @= lambda: (
    ball.center.x + 200 * cos(st.time) + st.x1 * cos(st.time * st.tx1),
    ball.center.y + 200 * sin(st.time) + st.y1 * sin(st.time * st.ty1),
)

beam = Line(p1=lambda: ball.center, p2=lambda: tip)
beam.visual = ElectricField("yellow")
beam.visible = False

trail = Contrail(duration=6.28 / 4, fade=True, visual=Neon("red"), line_width=2.5)


@click(ball)
def switch_on():
    if st.switched_on:
        return
    st.switched_on = True
    beam.visible = True
    ball.visual = None
    tip.every(6.28 / (st.n * 100), lambda: trail.snapshot(tip))


run()
