"""Equation twin for E15 (a rule does not depend on other rules): CD3.

The hero sits in lava. It gains the ``shield`` tag, loses it, gains it
again, and a pickup's handler gives it once more after it walked out and
back in: the shield rules must see the same enters, stays and exits whether
or not another rule (E15 adds a no-op ``@collide_stay("hero", "lava")``)
already pairs the hero with the lava.
Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

init(width=300, height=300, title="laws twin: shield")

st.enters = 0
st.exits = 0

hero = Circle(center=(150, 150), radius=10, group="hero")
Rect(center=(150, 150), width=120, height=120, group="lava")
Circle(center=(150, 40), radius=6, group="pickup")


@collide("shield", "lava")
def shield_up(h, lava, info):
    st.enters += 1


@collide_stay("shield", "lava")
def shield_holds(h, lava, info):
    pass


@collide_exit("shield", "lava")
def shield_down(h, lava, info):
    st.exits += 1


@collide("pickup", "hero")
def pick(p, h, info):
    h.tag("shield")
    p.destroy()


def update(dt):
    f = clock.frame
    if f == 10:
        hero.tag("shield")
    elif f == 20:
        hero.untag("shield")
    elif f == 25:
        hero.tag("shield")
        hero.untag("shield")            # a blink: no change
    elif f == 30:
        hero.tag("shield")
    elif f == 40:
        hero.untag("shield")
        hero.tag("shield")              # a flick: no change
    elif f == 50:
        hero.untag("shield")
    elif 60 <= f < 90:
        hero.move_by(0, -4)             # out of the lava, onto the pickup
    elif 90 <= f < 120:
        hero.move_by(0, 4)              # back in, shielded by the pickup


run()
