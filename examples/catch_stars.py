"""Catch stars — tutorial 02.

The paddle catches the falling stars. No lives, no restart.

Controls
--------
  LEFT / RIGHT   move

Usage
-----
    python examples/catch_stars.py
"""

from random import uniform
from scena import *

init(width=1000, height=800, title="Catch stars")
Wallpaper("dark navy")

st.score = 0
st.missed = 0

scoreboard = Text(text="", top_left=(20, 780), font_size=20)
scoreboard["text"] @= lambda: f"Stars {st.score}   Missed {st.missed}"

bar = Sprite("k-rolling-ball/button_blue.png", width=80, center=(500, 80), group="hero")


@every(0.9)
def drop_star():
    x = uniform(80, 920)
    Sprite("k-rolling-ball/star.png", size=32, center=(x, 780), group="stars")


def update(dt):
    if keyp("LEFT"):
        bar.move_by(-380 * dt, 0)
    if keyp("RIGHT"):
        bar.move_by(380 * dt, 0)

    for star in group["stars"]:
        star.move_by(0, -220 * dt)
        if star.center.y < 40:
            lost(star)


@collide("hero", "stars")
def caught(bar, star):
    star.destroy()
    st.score += 1
    bar.pop(scale=1.25)


def lost(star):
    star.untag("stars")  # so the if does not fire again
    star.flash(0.2)
    star.after(0.2, star.destroy)
    st.missed += 1


run()
