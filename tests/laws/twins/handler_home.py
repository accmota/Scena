"""Equation twin E4: one contact rule declared three ways must act alike.

PARAMS ``home``: ``"module"`` (``@collide`` / ``@collide_stay`` /
``@collide_exit``), ``"method"`` (``@collide_with*`` on the class) or
``"property"`` (``on_collide`` / ``on_collide_stay`` / ``on_collide_exit``).
A ball crosses a zone; a second ball, made in the zone, destroys itself on
entering (the handler that removes its own body runs the same way in every
home). Program for the laws harness (tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})
HOME = PARAMS.get("home", "module")

init(width=400, height=300, title="laws twin: handler home")

st.enter = 0
st.stay = 0
st.exit = 0

zone = Rect(center=(200, 150), width=60, height=60, group="zone")


def entered(ball, other):
    st.enter += 1
    if ball.center.y > 200:          # the second ball: gone on its first touch
        ball.destroy()


def stayed(ball, other):
    st.stay += 1


def left(ball, other):
    st.exit += 1


if HOME == "method":
    class Ball(Circle):
        @collide_with("zone")
        def on_zone(self, other, info):
            entered(self, other)

        @collide_with_stay("zone")
        def in_zone(self, other, info):
            stayed(self, other)

        @collide_with_exit("zone")
        def off_zone(self, other, info):
            left(self, other)

    make = Ball
else:
    make = Circle

balls = [make(center=(120, 150), radius=8, group="ball"),
         make(center=(200, 210), radius=8, group="ball")]

if HOME == "module":
    @collide("ball", "zone")
    def on_zone(ball, other, info):
        entered(ball, other)

    @collide_stay("ball", "zone")
    def in_zone(ball, other, info):
        stayed(ball, other)

    @collide_exit("ball", "zone")
    def off_zone(ball, other, info):
        left(ball, other)
elif HOME == "property":
    # ``on_collide`` reaches "any other registered body": the zone is in no
    # rule here, so it registers itself (Guia, Detectar; E4 first ran without
    # it and the property home saw no contact at all).
    zone.collidable = True
    for b in balls:
        b.on_collide = lambda me, other, info: entered(me, other)
        b.on_collide_stay = lambda me, other, info: stayed(me, other)
        b.on_collide_exit = lambda me, other, info: left(me, other)


def update(dt):
    for b in group["ball"]:
        b.move_by(90 * dt, 60 * dt if b.center.y > 200 else 0)


run()
