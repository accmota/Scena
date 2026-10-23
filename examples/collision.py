"""Collision — tutorial 20.

A collision lab, no game: a puddle with the three phases of a touch
(@collide, @collide_stay, @collide_exit), a click that asks who is at
the point (collision.query_point), a burst over an area
(collision.query_circle with group=) and a guard who sees the hero when
no crate blocks the line (collision.raycast).

Controls
--------
  arrow keys       move the hero
  click            flashes whatever is underneath
  right button     bursts the crates around it

Usage
-----
    python examples/collision.py
"""

from scena import *

init(width=1000, height=700, title="Collision")
Wallpaper("#1b2330")

puddle = Rect(center=(250, 200), width=260, height=180, color="#2a6f97", group="water")

for x, y in [(520, 420), (600, 420), (680, 300), (420, 180), (760, 560)]:
    Rect(center=(x, y), width=70, height=70, color="peru", group="crate")

hero = Circle(center=(120, 560), radius=22, color="coral", group="hero")
hero.pace = 260
resolve("hero", "crate")

st.air = 100
Text(lambda: f"Air: {round(st.air)}", top_left=(20, 680))


def update(dt):
    step = hero.pace * dt
    if keyp("LEFT"):
        hero.move_by(-step, 0)
    if keyp("RIGHT"):
        hero.move_by(step, 0)
    if keyp("UP"):
        hero.move_by(0, step)
    if keyp("DOWN"):
        hero.move_by(0, -step)
    if st.air < 100:
        st.air = min(100, st.air + 10 * dt)
    face()


@collide("hero", "water")
def entered(hero, water, info):
    hero.pace = 110
    hero.color = "light sky blue"


@collide_stay("hero", "water")
def submerged(hero, water, info):
    st.air = max(0, st.air - 30 * clock.dt)


@collide_exit("hero", "water")
def exited(hero, water, info):
    hero.pace = 260
    hero.color = "coral"


def on_mouse_click(x, y, button):
    if button == Mouse.BTN_RIGHT:
        canvas.burst_at((x, y), radius=90)
        for crate in collision.query_circle(x, y, radius=90, group="crate"):
            crate.destroy()
    else:
        for thing in collision.query_point(x, y):
            thing.flash(0.3)


guard = Triangle(center=(900, 620), radius=24, color="gold")
sight = Line(p1=guard.center, p2=hero.center, color="gold")


def face():
    guard.rotate_to(heading(guard.center, hero.center))
    hit = collision.raycast(guard, p2=hero, group=["hero", "crate"])
    if hit:
        thing, t, point = hit
        sight.p2 = point
        if thing is hero:
            sight.color = "red"
        else:
            sight.color = "gray"


run()
