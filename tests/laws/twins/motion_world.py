"""Motion twin (S6): small resolve worlds that the motion laws and the
invariance equations E10–E14 run in transformed copies.

PARAMS ``scene``: ``"ramp"`` (an idle body on a STATIC ramp), ``"stack"``
(two crates on a STATIC floor), ``"headon"`` (two movable balls hit head on),
``"lift"`` (a rider on a sideways STATIC lift), ``"box"`` (a ball bouncing in
a box). Transforms: ``ox`` / ``oy`` (translation), ``mirror`` (x -> -x),
``k`` (every mass times k), ``s`` (world and speeds times s). ``BODIES``
lists the moving bodies; ``home(x, y)`` maps a point back to the untransformed
world, so a probe compares like with like. Program for the laws harness
(tests/laws/); not an example.
"""
from scena import *

PARAMS = globals().get("PARAMS", {})
SCENE = PARAMS.get("scene", "box")
OX, OY = PARAMS.get("ox", 0.0), PARAMS.get("oy", 0.0)
MIR = -1.0 if PARAMS.get("mirror") else 1.0
K = PARAMS.get("k", 1.0)
S = PARAMS.get("s", 1.0)
G = 900.0 * S

init(width=800, height=600, title="laws twin: motion")
collision.floor = True   # gravity: bodies stand on floors (ramps, lifts, seams)


def P(x, y):
    return (OX + MIR * x * S, OY + y * S)


def V(vx, vy):
    return Vec2(MIR * vx * S, vy * S)


def home(x, y):
    return ((x - OX) / (MIR * S), (y - OY) / S)


def wall(x, y, w, h, angle=0.0):
    r = Rect(center=P(x, y), width=w * S, height=h * S, group="static")
    if angle:
        r.rotate_by(MIR * angle)
    r.mass = STATIC
    return r


BODIES = []
GRAVITY = []
LIFT = None

if SCENE == "ramp":
    wall(300, 200, 400, 20, angle=-25)
    hero = Rect(center=P(330, 260), width=20 * S, height=30 * S, group="body")
    hero.mass = 1.0 * K
    hero.vel = V(0, 0)
    BODIES.append(hero)
    GRAVITY.append(hero)
    resolve("body", "static", bounce=0)
elif SCENE == "stack":
    wall(300, 100, 400, 20)
    low = Rect(center=P(300, 140), width=40 * S, height=40 * S, group="body")
    high = Rect(center=P(300, 190), width=40 * S, height=40 * S, group="body")
    low.mass, high.mass = 1.0 * K, 5.0 * K
    for b in (low, high):
        b.vel = V(0, 0)
        BODIES.append(b)
        GRAVITY.append(b)
    resolve("body", "static", bounce=0)
    resolve("body", "body", bounce=0)
elif SCENE == "headon":
    a = Circle(center=P(200, 300), radius=12 * S, group="body")
    b = Circle(center=P(500, 300), radius=12 * S, group="body")
    a.mass, b.mass = 1.0 * K, 3.0 * K
    a.vel, b.vel = V(240, 0), V(-120, 0)
    BODIES += [a, b]
    resolve("body", "body", bounce=1.0)
elif SCENE == "lift":
    LIFT = wall(200, 150, 160, 20)
    rider = Rect(center=P(200, 185), width=20 * S, height=30 * S, group="body")
    rider.mass = 1.0 * K
    rider.vel = V(0, 0)
    BODIES.append(rider)
    GRAVITY.append(rider)
    resolve("body", "static", bounce=0)
else:
    wall(400, 10, 800, 20)
    wall(400, 590, 800, 20)
    wall(10, 300, 20, 600)
    wall(790, 300, 20, 600)
    ball = Circle(center=P(200, 250), radius=10 * S, group="body")
    ball.mass = 1.0 * K
    ball.vel = V(330, 190)
    BODIES.append(ball)
    resolve("body", "static", bounce=1.0)


def update(dt):
    if SCENE == "ramp":
        hero.vel.x = 0            # the platformer idiom: no walk, so idle (PE2)
    for b in GRAVITY:
        b.vel.y -= G * dt
    for b in BODIES:
        b.move_by(b.vel.x * dt, b.vel.y * dt)
    if LIFT is not None:
        LIFT.move_by(MIR * 60 * S * dt, 0)


run()
