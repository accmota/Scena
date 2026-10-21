# harness: cwd=examples/media
"""Bando — a benchmark game (scripts/bench/games/). Not an example, not a tutorial.

A flock written the Scena way: every bird asks ``collision.query_circle``
who is near it, once a frame, in its own ``on_update``, then steers by the
three boid rules (separate, align, cohere) and wraps at the edges. A hawk
chases the flock and asks ``query_sector`` ahead of it; a few rocks are
``raycast`` against. ``examples/revoada.py`` is the same idea with its own
grid of plain floats, because these queries were linear in the group.

Stresses: named queries over a group of moving, non-enrolled shapes (moved
set, query index), the query's narrow phase. ``enroll=1`` makes every bird
a body too (``collidable = True``) and asks without ``group=``.

PARAMS: n (birds, default 140), enroll (0/1), seed, auto (unused: no input).
"""
import math
import random

from scena import *

PARAMS = globals().get("PARAMS", {})
N = int(PARAMS.get("n", 140))
ENROLL = bool(int(PARAMS.get("enroll", 0)))
random.seed(int(PARAMS.get("seed", 5)))

W, H = 1280, 800
VISAO = 70
PERTO = 22
RAPIDEZ = 150
init(width=W, height=H, title="Bando")


class Passaro(Triangle, radius=9, base_ratio=0.5, group="passaro"):
    def setup(self):
        self.vel = vec_from_angle(random.uniform(-180, 180), RAPIDEZ)
        self.line = None
        if ENROLL:
            self.collidable = True

    def on_update(self, dt):
        if ENROLL:
            perto = collision.query_circle(self.center, radius=VISAO, ignore=[self, falcao])
        else:
            perto = collision.query_circle(self.center, radius=VISAO, group="passaro", ignore=self)
        x, y = self.center.x, self.center.y
        vx, vy = self.vel.x, self.vel.y
        if perto:
            sx = sy = ax = ay = cx = cy = 0.0
            for o in perto:
                ox, oy = o.center.x, o.center.y
                cx += ox
                cy += oy
                ax += o.vel.x
                ay += o.vel.y
                dx, dy = x - ox, y - oy
                d2 = dx * dx + dy * dy
                if d2 < PERTO * PERTO and d2 > 1e-6:
                    sx += dx / d2
                    sy += dy / d2
            k = len(perto)
            vx += ((cx / k - x) * 0.7 + (ax / k - vx) * 2.5 + sx * 3000) * dt
            vy += ((cy / k - y) * 0.7 + (ay / k - vy) * 2.5 + sy * 3000) * dt
        s = math.hypot(vx, vy) or 1.0
        vx, vy = vx / s * RAPIDEZ, vy / s * RAPIDEZ
        self.vel = Vec2(vx, vy)
        nx, ny = (x + vx * dt) % W, (y + vy * dt) % H
        self.center = (nx, ny)
        self.angle = math.degrees(math.atan2(vy, vx))


class Falcao(Triangle, radius=20, base_ratio=0.45, color="dark red"):
    def setup(self):
        self.vistos = 0
        self.t = 0.0

    def on_update(self, dt):
        self.t += dt
        alvo = Vec2(W / 2 + 400 * math.cos(self.t * 0.7),
                    H / 2 + 260 * math.sin(self.t * 1.1))
        self.angle = heading(self, alvo)
        self.move_to(chase(self.center, alvo, rate=2))
        self.vistos = len(collision.query_sector(self, radius=200, spread=60, group="passaro"))
        collision.raycast(self, length=300, group="pedra")


falcao = Falcao(center=(W / 2, H / 2))
for i in range(6):
    Rect(center=(random.uniform(100, W - 100), random.uniform(100, H - 100)),
         width=40, height=40, color="gray", group="pedra")
for i in range(N):
    Passaro(center=(random.uniform(0, W), random.uniform(0, H)))

run()
