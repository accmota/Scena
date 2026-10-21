"""
The claims of ``examples/revoada.py``, played headless.

The example says: with the three rules on, neighbours fly the same way (so
they share a colour) and the flock's order rises, which lights the sky (the
Bloom); with alinhar off each bird flies its own way; birds turn back at the
edges; a bird near the falcon takes a whole fright, turns white and thin, and
the fright passes to neighbours that never saw the falcon, then fades; a
click scares and scatters the birds near it; S / A / J switch the rules.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``move_by(face=True)``, in-place ``vel.x`` writes,
``Triangle.base_ratio``) while it still builds and runs, and **a flock that
falls off the fast pose path**: reading a derived value of a bird's own
``vel`` (``self.vel.angle``, ``self.vel.length``) marks the bird as a pull
source for good, and every ``move_by`` / ``angle`` write after it takes the
invalidating path (measured: ~150 fps instead of ~250 with 120 birds). The
example aims with ``face=True`` instead; the canary below fails if a bird
gets that mark. Also **a contagion that never reaches zero**: two neighbours
that pass the fright to each other kept it at ~1e-302 for good (a draft did,
and every bird then rewrote ``medo`` each frame); the fade check asks for an
exact 0.

Run:

    python tests/run_tiers.py focused test_example_revoada
"""
from __future__ import annotations

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402

PATH = "examples/revoada.py"
SECOND = 60
AWAY = (-500, -500)     # the falcon parked off screen


def xy(p):
    return float(p.center.x), float(p.center.y)


def neighbour_angle(ns) -> float:
    """Mean heading gap (degrees) between birds that see each other."""
    birds = list(ns["group"]["passaro"])
    total = pairs = 0
    for p in birds:
        for q in birds:
            if p is not q and math.dist(xy(p), xy(q)) < ns["VISAO"]:
                total += abs((p.angle - q.angle + 180) % 360 - 180)
                pairs += 1
    return total / max(pairs, 1)


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


class TestRevoadaRules(unittest.TestCase):
    def fly(self, seed, *, off=None, seconds=20):
        """Order samples (one per second) and the last frame's numbers."""
        with ProgramRun(PATH, seed=seed) as run:
            ns = run.ns
            run.move(*AWAY)
            if off:
                tap(run, off)
            order = []
            lowest = 1.0
            for _ in range(seconds):
                for _ in range(SECOND):
                    run.step(1)
                    for p in ns["group"]["passaro"]:
                        x, y = xy(p)
                        lowest = min(lowest, x, 1280 - x, y, 800 - y)
                order.append(ns["st"].ordem)
            return {
                "order": sum(order[-10:]) / 10,
                "angle": neighbour_angle(ns),
                "lowest": lowest,
                "light": ns["luz"].intensity,
                "rules": (ns["st"].separar, ns["st"].alinhar, ns["st"].juntar),
            }

    def test_neighbours_align_and_the_sky_follows_the_order(self):
        for seed in (1, 3):
            with self.subTest(seed=seed):
                on = self.fly(seed)
                off = self.fly(seed, off="A")
                self.assertEqual(on["rules"], (True, True, True))
                self.assertEqual(off["rules"], (True, False, True))
                self.assertLess(on["angle"], 25, "neighbours do not fly the same way")
                self.assertGreater(off["angle"], 60, "alinhar off still aligns")
                self.assertGreater(on["order"], 0.3)
                self.assertLess(off["order"], 0.25)
                self.assertGreater(on["light"], off["light"])

    def test_birds_turn_back_at_the_edges(self):
        self.assertGreater(self.fly(2, seconds=30)["lowest"], -20,
                           "a bird flew off the screen")

    def test_neighbours_share_a_colour(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            run.step(15 * SECOND)
            birds = list(ns["group"]["passaro"])
            same = pairs = 0
            for p in birds:
                for q in birds:
                    if p is not q and math.dist(xy(p), xy(q)) < ns["PERTO"] * 2:
                        gap = abs(p.tom[0] - q.tom[0]) % ns["FAIXAS"]
                        same += min(gap, ns["FAIXAS"] - gap) <= 1
                        pairs += 1
            self.assertGreater(pairs, 50, "vacuous: no close pairs")
            self.assertGreater(same / pairs, 0.8)


class TestRevoadaFright(unittest.TestCase):
    def test_the_fright_spreads_past_the_falcon_then_fades(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            run.step(10 * SECOND)
            falcao = ns["falcao"]
            alvo = xy(list(ns["group"]["passaro"])[0])
            falcao.move_to(*alvo)
            run.move(*alvo)
            spread = False
            for _ in range(SECOND):
                run.step(1)
                fx, fy = xy(falcao)
                for p in ns["group"]["passaro"]:
                    if math.dist(xy(p), (fx, fy)) > ns["SUSTO"] + 30 and p.medo > 0.2:
                        spread = True
            self.assertTrue(spread, "no bird out of the falcon's reach caught the fright")
            scared = [p for p in ns["group"]["passaro"] if p.medo > 0.6]
            self.assertTrue(scared, "vacuous: nobody is scared")
            for p in scared:
                self.assertLess(p.base_ratio, 0.45, "a scared bird is not thinner")
                self.assertGreater(min(p.fill.rgb[:3]), 0.6, "a scared bird is not whitish")
            run.move(*AWAY)
            falcao.move_to(*AWAY)
            run.step(6 * SECOND)
            self.assertEqual([p.medo for p in ns["group"]["passaro"] if p.medo > 0], [],
                             "the fright did not fade")
            for p in ns["group"]["passaro"]:
                self.assertAlmostEqual(p.base_ratio, 0.6)

    def test_a_click_scares_and_scatters_the_birds_near_it(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            run.step(10 * SECOND)
            x, y = xy(list(ns["group"]["passaro"])[0])
            near = [p for p in ns["group"]["passaro"] if math.dist(xy(p), (x, y)) < 220]
            before = {p: math.dist(xy(p), (x, y)) for p in near}
            run.move(x, y)
            run.press(x, y)
            run.step(1)
            run.release()
            run.step(1)
            self.assertTrue(near)
            for p in near:
                self.assertGreater(p.medo, 0.9)
            run.move(*AWAY)
            run.step(SECOND // 2)
            moved_out = sum(math.dist(xy(p), (x, y)) > before[p] for p in near)
            self.assertGreater(moved_out, 0.8 * len(near))

    def test_keys_switch_the_rules(self):
        with ProgramRun(PATH, seed=1) as run:
            st = run.ns["st"]
            for key, name in (("S", "separar"), ("A", "alinhar"), ("J", "juntar")):
                tap(run, key)
                self.assertFalse(getattr(st, name), key)
                tap(run, key)
                self.assertTrue(getattr(st, name), key)


class TestRevoadaFastPath(unittest.TestCase):
    def test_birds_stay_on_the_fast_pose_path(self):
        """Canary: no bird becomes a pull source (see the module docstring)."""
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            for i in range(6 * SECOND):
                t = i / SECOND
                run.move(640 + 400 * math.cos(t), 400 + 250 * math.sin(1.3 * t))
                run.step(1)
            x, y = xy(list(ns["group"]["passaro"])[0])
            run.move(x, y)
            run.press(x, y)
            run.step(1)
            run.release()
            run.step(SECOND)
            marked = [p for p in ns["group"]["passaro"] if p._requires_pull_invalidate()]
            self.assertEqual(marked, [], "a bird left the fast pose path")


if __name__ == "__main__":
    unittest.main()
