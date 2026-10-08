"""Fast shots hit the same enemies at every frame pacing (swept detection).

A shot moving faster per frame than the overlap window used to pass through
``@collide`` partners, and how often it did depended on the frame rate. Swept
detection checks a fast ``move_by`` body along its path, so across real frames:

* a piercing shot enters every enemy in its column exactly once, and exits it;
* a shot that destroys itself on contact hits the **nearest** enemy, even when
  one frame crosses several rows;
* both hold at 30 / 60 / 120 Hz, uneven 5 / 28 ms pacing, and far from the
  origin;
* a fast body pushed into a thin ``resolve()`` wall fires ``@collide`` once
  (CT2 in Testing Design: before, the pre-resolve end pose was always past
  the wall and the handler never ran).

Collision Design.md — Swept detection (fast bodies).

    python -m unittest tests.test_sys_fast_shots -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import system_world  # noqa: E402

from scena import STATIC, Circle, Rect, collide, collide_exit, resolve  # noqa: E402

PACINGS = {
    "30 Hz": [1 / 30],
    "60 Hz": [1 / 60],
    "120 Hz": [1 / 120],
    "5 / 28 ms": [0.005, 0.028],
}
OFFSETS = (0.0, 65_536.0)
SPEED = 5000.0          # 83 DU per frame at 60 Hz, 167 at 30 Hz
COLS = 4
ROWS = 3


def _run(world, pacing, frames, update):
    world.on_update(update)
    for f in range(frames):
        world.step(1, dt=pacing[f % len(pacing)], draw=False)


def fleet(offset, *, pierce, pacing):
    """One 6x28 laser per column, flying up through ROWS rows of 40x40 enemies.

    Rows are 70 apart (gap 30), so a 30 Hz frame crosses two rows. Returns
    ``{column: [row hit, ...]}`` in enter order and the exit count.
    """
    hits = {c: [] for c in range(COLS)}
    exits = [0]
    with system_world(draw=False) as w:
        enemies = {}
        for r in range(ROWS):
            for c in range(COLS):
                e = w.track(Rect(center=(offset + c * 90, offset + 300 + r * 70),
                                 width=40, height=40, group="enemy"))
                enemies[id(e)] = (c, r)
        shots = [w.track(Rect(center=(offset + c * 90, offset + 20 + c * 7),
                              width=6, height=28, group="shot"))
                 for c in range(COLS)]

        @collide("shot", "enemy")
        def hit(shot, enemy, info):
            c, r = enemies[id(enemy)]
            hits[c].append(r)
            if not pierce:
                shot.destroy()
                enemy.destroy()

        @collide_exit("shot", "enemy")
        def left(shot, enemy, info):
            exits[0] += 1

        def update(dt):
            for s in shots:
                if s.is_alive:
                    s.move_by(0, SPEED * dt)

        _run(w, pacing, 40, update)
    return hits, exits[0]


class TestFastShotsAcrossPacings(unittest.TestCase):
    def test_piercing_shot_enters_every_row_once(self):
        for name, pacing in PACINGS.items():
            for off in OFFSETS:
                with self.subTest(pacing=name, offset=off):
                    hits, exits = fleet(off, pierce=True, pacing=pacing)
                    self.assertEqual(hits, {c: list(range(ROWS)) for c in range(COLS)})
                    self.assertEqual(exits, COLS * ROWS)

    def test_self_destroying_shot_hits_the_nearest_row(self):
        for name, pacing in PACINGS.items():
            for off in OFFSETS:
                with self.subTest(pacing=name, offset=off):
                    hits, _exits = fleet(off, pierce=False, pacing=pacing)
                    self.assertEqual(hits, {c: [0] for c in range(COLS)})


class TestFastBodyIntoResolvedWall(unittest.TestCase):
    def test_collide_fires_once_while_pushed(self):
        for name, pacing in PACINGS.items():
            for off in OFFSETS:
                with self.subTest(pacing=name, offset=off):
                    log = []
                    with system_world(draw=False) as w:
                        ball = w.track(Circle(center=(off, off), radius=5, group="ball"))
                        ball.mass = 1.0
                        wall = w.track(Rect(center=(off + 150, off), width=4,
                                            height=200, group="wall"))
                        wall.mass = STATIC
                        resolve("ball", "wall")

                        @collide("ball", "wall")
                        def touch(b, wl, info):
                            log.append("enter")

                        @collide_exit("ball", "wall")
                        def untouch(b, wl, info):
                            log.append("exit")

                        _run(w, pacing, 30, lambda dt: ball.move_by(6000 * dt, 0))
                        self.assertLess(float(ball.center.x), off + 148.0)
                        seen = list(log)          # before teardown's exits
                    self.assertEqual(seen, ["enter"])


if __name__ == "__main__":
    unittest.main()
