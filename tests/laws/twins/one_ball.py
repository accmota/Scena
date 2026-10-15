"""Equation twin for E1 (pacing): one ball bouncing in a box (``resolve``).

One body, no other moving body: no chaos to amplify a sub-frame difference.
The wall hits at 30 / 60 / 144 Hz and uneven frames must agree in time,
within a frame. Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

init(width=400, height=300, title="laws twin: one ball")

st.hits = 0
for c, w, h in (((200, 5), 400, 10), ((200, 295), 400, 10), ((5, 150), 10, 300),
                ((395, 150), 10, 300)):
    Rect(center=c, width=w, height=h, group="wall")
ball = Circle(center=(120, 90), radius=8, group="ball")
ball.mass = 1.0
ball.vel = Vec2(230, 170)
resolve("ball", "wall", bounce=1.0)


@collide("ball", "wall")
def hit(b, w, info):
    st.hits += 1


def update(dt):
    ball.move_by(ball.vel.x * dt, ball.vel.y * dt)


run()
