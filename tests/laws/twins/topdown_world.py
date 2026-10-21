"""Top-down twin (V10): small resolve worlds without gravity, turned whole.

A world without a floor (``collision.floor = False``, the default) has no
"down": every side is alike, so turning the whole world turns every path
with it (equation E16). Each scene is a floor rule's case seen from above,
where that rule must not act:

* ``leave``: a body slides along a wall under it, then drives off it at a
  shallow angle (floor snap glued it to the wall);
* ``lift``: a STATIC barrier under a body slides sideways (rider carry
  dragged the body along);
* ``slope``: a body drives straight into a 30-degree wall under it
  (stop-on-slope dropped the slide that a wall at its side gives);
* ``seam``: a body slides along two blocks under it with a 1.5 DU lip
  between them (the seam step climbed it);
* ``bounce``: a ball with ``bounce=0.4`` in a box (the bounce sub-step
  skipped the floor it started on).

PARAMS: ``scene``, ``rot`` (degrees: the world turned about its centre),
``floor`` (``collision.floor``; ``True`` is E16's canary: the floor rules
act, and the turned world moves differently). ``BODIES`` lists the moving
bodies; ``home(x, y)`` turns a point back. Program for the laws harness
(tests/laws/); not an example.
"""
import math

from scena import *

PARAMS = globals().get("PARAMS", {})
SCENE = PARAMS.get("scene", "leave")
ROT = float(PARAMS.get("rot", 0.0))
CX, CY = 400.0, 300.0
_C, _S = math.cos(math.radians(ROT)), math.sin(math.radians(ROT))

init(width=800, height=600, title="laws twin: top-down")
collision.floor = bool(PARAMS.get("floor", False))


def P(x, y):
    dx, dy = x - CX, y - CY
    return (CX + dx * _C - dy * _S, CY + dx * _S + dy * _C)


def V(vx, vy):
    return Vec2(vx * _C - vy * _S, vx * _S + vy * _C)


def home(x, y):
    dx, dy = x - CX, y - CY
    return (CX + dx * _C + dy * _S, CY - dx * _S + dy * _C)


def wall(x, y, w, h, angle=0.0):
    r = Rect(center=P(x, y), width=w, height=h, group="static")
    if angle + ROT:
        r.rotate_by(angle + ROT)
    r.mass = STATIC
    return r


def body(x, y):
    b = Circle(center=P(x, y), radius=12, group="body")
    b.vel = V(0, 0)
    BODIES.append(b)
    return b


BODIES = []
DRIVE = {}          # body -> (vx, vy) it drives at, in the untransformed world
LIFT = None

if SCENE == "leave":
    wall(400, 200, 600, 40)
    car = body(200, 233)
    DRIVE[car] = (200, -60)
    resolve("body", "static")
elif SCENE == "lift":
    LIFT = wall(400, 200, 240, 40)
    rider = body(400, 233)
    DRIVE[rider] = (0, -30)
    resolve("body", "static")
elif SCENE == "slope":
    wall(400, 200, 600, 40, angle=30)
    ball = body(400, 330)
    DRIVE[ball] = (0, -150)
    resolve("body", "static")
elif SCENE == "seam":
    wall(250, 200, 300, 40)
    wall(550, 201.5, 300, 40)
    slider = body(200, 232)
    DRIVE[slider] = (150, -20)
    resolve("body", "static", bounce=0)
else:
    wall(400, 40, 760, 40)
    wall(400, 560, 760, 40)
    wall(40, 300, 40, 520)
    wall(760, 300, 40, 520)
    ball = body(200, 400)
    ball.vel = V(160, -260)
    resolve("body", "static", bounce=0.4)


def update(dt):
    for b, (vx, vy) in DRIVE.items():
        if SCENE == "leave" and clock.time > 0.3:
            vx, vy = 200, 40            # drive off the wall at a shallow angle
        b.vel = V(vx, vy)
    for b in BODIES:
        b.move_by(b.vel.x * dt, b.vel.y * dt)
    if LIFT is not None:
        LIFT.move_by(V(120 * dt, 0))


run()
