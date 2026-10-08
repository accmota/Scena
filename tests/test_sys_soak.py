"""Opt-in endurance run: a small game for thousands of real frames.

Skipped unless ``SCENA_SOAK=1`` (minutes). ``SCENA_SOAK_FRAMES`` sets the
length (default 20000). A self-contained mini game — a spawner firing bullets
that hit rocks (``@collide_with``), leave the playfield, time out, play sounds,
flash, leave debris (``Sparks``) from ``on_destroy``; a hero with modes and a
Contrail; a camera that pans — runs with a raster draw every few frames.

Checks: the registries plateau (the last third holds no more than the first
third, plus slack), the product leak heuristic (``leak_signal``) stays quiet,
``tracemalloc`` growth between the first and last thirds stays small, and a
full drain returns every registry to its baseline.

    SCENA_SOAK=1 python -m unittest tests.test_sys_soak -v
    SCENA_SOAK=1 SCENA_SOAK_FRAMES=100000 python -m unittest tests.test_sys_soak
"""
from __future__ import annotations

import os
import sys
import tracemalloc
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import (  # noqa: E402
    census, describe_new_live, diff_census, format_diff, full_collect, roster_snapshot,
    quiet, system_world, tone,
)

from scena import (  # noqa: E402
    Circle, Contrail, Entity, Sparks, after, canvas, chance, clock, collide_with,
    leave_playfield, wait,
)
from scena.leak_detector import leak_signal  # noqa: E402

FRAMES = int(os.environ.get("SCENA_SOAK_FRAMES", "20000"))
PLATEAU_KEYS = ("graph.nodes", "sched.handles", "collision.colliders", "registry.live",
                "registry.draw_live", "fx.spatial_fx", "fx.transient_shapes",
                "mixer.voices", "events.all", "collision.pair_handlers")


@unittest.skipUnless(os.environ.get("SCENA_SOAK") == "1", "set SCENA_SOAK=1 to run")
class TestSoak(unittest.TestCase):

    def test_mini_game_holds_steady(self):
        with system_world(draw=False) as w:
            base = census()
            base_ids = roster_snapshot()
            snd = tone(0.08)

            class Bullet(Circle):
                @collide_with("rock")
                def hit(self, rock, info=None):
                    rock.hp -= 1
                    self.destroy()

                @leave_playfield
                def gone(self):
                    self.destroy()

            class Rock(Circle):
                def setup(self):
                    self.hp = 3

            rocks = []

            def respawn_rocks():
                for r in list(rocks):
                    if not r.is_alive or r.hp <= 0:
                        if r.is_alive:
                            with quiet():
                                r.destroy()
                        rocks.remove(r)
                while len(rocks) < 6:
                    with quiet():
                        rocks.append(Rock(center=(120 + 30 * len(rocks), 40 - 15 * len(rocks)),
                                          radius=10, group="rock"))

            hero = w.track(Circle(center=(-150, 0), radius=8))
            trail = w.track(Contrail(max_points=30, color="cyan"))
            hero.on_update = lambda e, dt: trail.snapshot(e)

            async def patrol(e):
                while True:
                    await e.move_to(-150, 80, time=0.5)
                    await e.move_to(-150, -80, time=0.5)

            def shooting(e):
                e.every(0.1, fire, name="gun")

            def fire():
                with quiet():
                    b = Bullet(center=(hero.center.x + 10, hero.center.y), radius=3)
                b.move_by(600, (hash(clock.frame) % 7 - 3) * 20, time=1.2)
                b.after(1.5, b.destroy)
                if chance(0.3):
                    b.play_sound(snd)
                b.flash(0.05)

                def debris(b=b):
                    if chance(0.5):
                        fx = Sparks(center=(b.center.x, b.center.y), radius=6, rate=15)
                        fx.after(0.3, fx.destroy)
                b.on_destroy = debris

            director = w.track(Entity())
            director.every(2.0, lambda: setattr(hero, "mode",
                                                shooting if hero.mode is not shooting else patrol))
            director.every(0.5, respawn_rocks)
            director.every(1.0, lambda: canvas.pan_to(chance(0.5) * 20, 0, time=0.5))
            hero.mode = patrol
            respawn_rocks()

            tracemalloc.start()
            samples, history, snap_first = [], [], None
            third = max(1, FRAMES // 3)
            for f in range(FRAMES):
                w.step(1, draw=(f % 5 == 0))
                if f % 250 == 0:
                    c = census()
                    samples.append(c)
                    history.append((c["registry.draw_live"], c["graph.nodes"]))
                if f == third:
                    full_collect()
                    snap_first = tracemalloc.take_snapshot()
            full_collect()
            snap_last = tracemalloc.take_snapshot()
            tracemalloc.stop()

            n = len(samples)
            for key in PLATEAU_KEYS:
                early = max(s.get(key, 0) for s in samples[: n // 3])
                late = max(s.get(key, 0) for s in samples[2 * n // 3:])
                self.assertLessEqual(late, early * 1.2 + 10, f"{key} keeps growing: {early} → {late}")
            self.assertIsNone(leak_signal(history), "product leak heuristic fired")
            growth = sum(s.size_diff for s in snap_last.compare_to(snap_first, "filename")
                         if s.size_diff > 0)
            self.assertLess(growth, 8 * 1024 * 1024,
                            f"heap grew {growth / 1e6:.1f} MB between first and last thirds")
            self.assertEqual(w.probe.dead_calls(), [])
            self.assertEqual(w.zombies(), [])

            # Drain.
            with quiet():
                director.destroy()
                hero.destroy()
                trail.destroy()
                while rocks:
                    rock = rocks.pop()
                    if rock.is_alive:
                        rock.destroy()
                rock = None  # a leftover local would pin the last rock
            w.step(200)
            w.objects.clear()
            hero = trail = director = None
            canvas.reset_view()
            w.step(3)
            d = diff_census(base, census(), ("sched.every_sites",))
            self.assertEqual(d, {}, "soak left residue: " + format_diff(d)
                             + " | new: " + describe_new_live(base_ids))


if __name__ == "__main__":
    unittest.main()
