"""Equation twin for E3 (spawn order): the PB5 shooter.

A shot and an enemy each destroy themselves in their own class handler; the
enemy also scores. Every handler of the contact runs (C3), so the score is
the same whichever was made first — E3 swaps the two construction lines.
Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

init(width=300, height=300, title="laws twin: shooter order")

st.points = 0


class Shot(Circle):
    @collide_with("enemy")
    def hit(self, enemy, info):
        self.destroy()


class Enemy(Rect):
    @collide_with("shot")
    def struck(self, shot, info):
        st.points += 1
        self.destroy()


Enemy(center=(150, 200), width=40, height=20, group="enemy")
Shot(center=(150, 120), radius=5, group="shot")


def update(dt):
    for s in group["shot"]:
        s.move_by(0, 200 * dt)


run()
