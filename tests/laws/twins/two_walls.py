"""Equation twin for E1 (pacing): one fast ball between two STATIC walls.

A head-on bounce every half second at 700 DU/s: the case where a bounce that
dropped the rest of its frame's travel (LW7) put the 30 / 144 Hz and uneven
runs more than a frame apart within a few seconds. The wall hits must agree in
time, within a frame. Program for the laws harness (tests/laws/); not an
example.
"""
from scena import *

init(width=400, height=300, title="laws twin: two walls")

st.hits = 0
for x in (5, 395):
    Rect(center=(x, 150), width=10, height=300, group="wall").mass = STATIC
ball = Circle(center=(120, 150), radius=8, group="ball")
ball.mass = 1.0
ball.vel = Vec2(700, 0)
resolve("ball", "wall", bounce=1.0)


@collide("ball", "wall")
def hit(b, w, info):
    st.hits += 1


def update(dt):
    ball.move_by(ball.vel.x * dt, ball.vel.y * dt)


run()
