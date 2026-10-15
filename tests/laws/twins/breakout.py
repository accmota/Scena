"""Equation twin E8 (PE5): a brick broken in its handler or between frames.

PARAMS ``when``: ``"handler"`` (the ``@collide`` handler destroys the brick:
the resolve partner leaves mid-step, a ghost contact gives the ball its
bounce) or ``"later"`` (the handler marks the brick, ``update`` destroys it
next frame: resolve saw the brick). The ball must leave with the same
velocity and on the same path. The bricks are STATIC, as a Breakout's are (at
the default mass the ball pushed them: LW9). Program for the laws harness
(tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})
WHEN = PARAMS.get("when", "handler")

init(width=400, height=300, title="laws twin: breakout")

st.broken = 0
st.vx = 0.0
st.vy = 0.0
st.px = 0.0
st.py = 0.0

for i in range(3):
    Rect(center=(330, 90 + 60 * i), width=16, height=50, group="brick").mass = STATIC
ball = Circle(center=(120, 120), radius=6, group="ball")
ball.mass = 1.0
ball.vel = Vec2(PARAMS.get("vx", 300), PARAMS.get("vy", 90))
resolve("ball", "brick", bounce=1.0)
doomed = []


@collide("ball", "brick")
def broke(b, brick, info):
    st.broken += 1
    if WHEN == "handler":
        brick.destroy()
    else:
        doomed.append(brick)


def update(dt):
    while doomed:
        doomed.pop().destroy()
    ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
    st.vx = ball.vel.x
    st.vy = ball.vel.y
    st.px = ball.center.x
    st.py = ball.center.y


run()
