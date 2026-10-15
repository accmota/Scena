"""Laws fixture S0: a little breakout — every door the recorder must see.

A ball runs into bricks (``@collide`` destroys the brick, ``resolve``
bounces the ball), a timer and a repeating timer, ``update``, a Brick
class with ``on_destroy``, a park and a resume. Program for the laws
harness (tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})

init(width=400, height=300, title="laws s0")

st.hits = 0
st.ticks = 0
st.gone = 0


class Brick(Rect):
    def on_destroy(self):
        st.gone += 1


for i in range(3):
    Brick(center=(300, 60 + 90 * i), width=20, height=60, group="brick")

ball = Circle(center=(60, 150), radius=8, group="ball")
ball.mass = 1.0
ball.vel = Vec2(PARAMS.get("speed", 400), 0)

resolve("ball", "brick", bounce=1.0)


@collide("ball", "brick")
def hit(b, brick, info):
    st.hits += 1
    brick.destroy()


def update(dt):
    ball.move_by(ball.vel.x * dt, ball.vel.y * dt)


@every(0.25)
def tick():
    st.ticks += 1


def nap():
    ball.active = False
    after(0.1, wake)


def wake():
    ball.active = True


after(0.5, nap)

run()
