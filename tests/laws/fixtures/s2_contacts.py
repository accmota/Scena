"""Laws fixture S2: contacts — enter, stay, exit, under the handler patterns
the game-behaviour probes found (PE5, PB1, PB3, PB5).

* Breakout: a ball bounces (``resolve``) off bricks an ``@collide`` destroys.
* A shot that touches two enemies in one step destroys itself in its own
  class handler; each enemy's class handler scores; a module rule counts.
* A crate rests in a zone (stays), then is pushed out (exit); a second zone
  has two exit handlers, the first destroys the crate (PB3).
* A spike untags the hero while touching (PB1: the exit still comes).
* A drone lands on two pads in one step and parks itself in the first
  enter: it enters no other pair that step (C4).

Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})

init(width=600, height=400, title="laws s2")

st.bricks = 0
st.score = 0
st.hits = 0
st.stays = 0
st.exits_a = 0
st.exits_b = 0
st.spikes_in = 0
st.spikes_out = 0
st.naps = 0

# -- Breakout (PE5) ------------------------------------------------------------
for i in range(3):
    Rect(center=(560, 60 + 50 * i), width=16, height=40, group="brick")
ball = Circle(center=(420, 110), radius=6, group="ball")
ball.mass = 1.0
ball.vel = Vec2(300, 0)
resolve("ball", "brick", bounce=1.0)


@collide("ball", "brick")
def broke(b, brick, info):
    st.bricks += 1
    brick.destroy()


# -- Shot and two enemies in one step (PB5) ------------------------------------
class Shot(Circle):
    def setup(self):
        self.vel = Vec2(0, 240)

    def on_update(self, dt):
        self.move_by(0, self.vel.y * dt)

    @collide_with("enemy")
    def hit(self, enemy, info):
        self.destroy()


class Enemy(Rect):
    @collide_with("shot")
    def struck(self, shot, info):
        st.score += 1
        self.destroy()


Enemy(center=(100, 300), width=30, height=20, group="enemy")
Enemy(center=(108, 300), width=30, height=20, group="enemy")
Shot(center=(104, 250), radius=5, group="shot")


@collide("shot", "enemy")
def counted(shot, enemy, info):
    st.hits += 1


# -- Zones: stays, exits, a destroy in an exit (PB3) ---------------------------
crate = Rect(center=(250, 200), width=20, height=20, group="crate")
zone_a = Rect(center=(250, 200), width=60, height=60, group="zone")
zone_b = Rect(center=(330, 200), width=60, height=60, group="zone2")


@collide_stay("crate", "zone")
def stayed(c, z, info):
    st.stays += 1


@collide_exit("crate", "zone2")
def left_first(c, z, info):
    st.exits_a += 1
    c.destroy()


@collide_exit("crate", "zone2")
def left_second(c, z, info):
    st.exits_b += 1


def push(dt):
    if crate.is_alive:
        crate.move_by(120 * dt, 0)


# -- A spike untags the hero (PB1) ---------------------------------------------
hero = Rect(center=(450, 300), width=20, height=20, group="hero")
spike = Rect(center=(450, 300), width=30, height=10, group="spike")


@collide("hero", "spike")
def on_spike(h, s, info):
    st.spikes_in += 1


@collide_exit("hero", "spike")
def off_spike(h, s, info):
    st.spikes_out += 1


# -- A mine with two methods on one contact; the first destroys it (PB5) -------
class Mine(Circle):
    @collide_with("rock")
    def boom(self, rock, info):
        self.destroy()

    @collide_with("rock")
    def smoke(self, rock, info):
        st.smoke = True          # runs too: every handler of the contact (PB5)


st.smoke = False
Mine(center=(300, 50), radius=8, group="mine")
Rect(center=(300, 50), width=10, height=10, group="rock")


# -- A drone parks itself in its own enter -------------------------------------
class Drone(Circle):
    @collide_with("pad")
    def landed(self, pad, info):
        st.naps += 1
        self.active = False
        after(0.2, lambda: setattr(self, "active", True))


Rect(center=(40, 60), width=40, height=10, group="pad")
Rect(center=(44, 60), width=40, height=10, group="pad")     # touched in the same step (C4)
drone = Drone(center=(40, 120), radius=6, group="drone")


def update(dt):
    ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
    if clock.time > 0.3:
        push(dt)
    if 0.2 < clock.time < 0.25 and "hero" in hero.group:
        hero.untag("hero")
    if drone.active and drone.center.y > 64:
        drone.move_by(0, -120 * dt)


run()
