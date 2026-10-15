"""Equation twin E5: a game built at the top of the file or in its first act.

PARAMS ``home``: ``"top"`` calls ``build()`` at the top of the file;
``"act"`` calls it from ``Fase.setup``. The same lines make the same
objects, timers, rules and class hooks, so until the act ends both run
alike. Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})
HOME = PARAMS.get("home", "top")

init(width=400, height=300, title="laws twin: act home")

st.hits = 0
st.ticks = 0
st.updates = 0


class Mover(Circle):
    def on_update(self, dt):
        st.updates += 1
        self.move_by(90 * dt, 0)


def tick():
    st.ticks += 1


def build():
    Mover(center=(60, 150), radius=8, group="mover")
    Rect(center=(250, 150), width=20, height=80, group="wall")
    every(0.2, tick)
    after(0.5, lambda: Circle(center=(300, 60), radius=5))

    @collide("mover", "wall")
    def hit(m, w, info):
        st.hits += 1
        m.destroy()


class Fase(Act):
    def setup(self):
        build()


if HOME == "top":
    build()
    run()
else:
    run(Fase)
