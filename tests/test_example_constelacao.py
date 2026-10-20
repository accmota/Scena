"""
The claims of ``examples/constelacao.py``, played headless.

The example says: each point's thread runs to its nearest neighbour and fades
out past ``FIO_MAXIMO``; each comet hunts the nearest *free* point (no two
comets after the same one); a caught point is reborn elsewhere and the comet
takes its colour; a point that runs off an edge comes back by the other one;
holding the mouse pulls the points in and letting go pushes them out; SPACE
adds a comet up to six; T switches the screen trail.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``nearest(where=)``, ``confine(action="wrap")``, a
linked colour read back as a value) while it still builds and runs — the
headless run in ``test_scripts_run`` only proves that it does not raise.

Run:

    python tests/run_tiers.py focused test_example_constelacao
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402

PATH = "examples/constelacao.py"
SECOND = 60


def dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def xy(p):
    return float(p.x), float(p.y)


def mean_distance(ns, x, y) -> float:
    pontos = list(ns["group"]["ponto"])
    return sum(dist(xy(p.center), (x, y)) for p in pontos) / len(pontos)


class TestConstelacao(unittest.TestCase):
    def test_threads_and_prey(self):
        with ProgramRun(PATH, seed=3) as run:
            ns = run.ns
            pontos = list(ns["group"]["ponto"])
            self.assertEqual(len(pontos), ns["PONTOS"])
            for _ in range(3 * SECOND):
                run.step(1)
                presas = [c.presa for c in ns["group"]["cometa"]]
                self.assertEqual(len(set(map(id, presas))), len(presas),
                                 "two comets chase the same point")
                for c in ns["group"]["cometa"]:
                    self.assertIs(c.presa.cacador, c)
            for p in pontos:
                outros = [o for o in pontos if o is not p]
                viz = min(outros, key=lambda o: dist(xy(o.center), xy(p.center)))
                far = dist(xy(viz.center), xy(p.center))
                if far >= ns["FIO_MAXIMO"]:
                    self.assertFalse(p.fio.visible)
                    continue
                self.assertTrue(p.fio.visible)
                self.assertLess(dist(xy(p.fio.p1), xy(p.center)), 1e-6)
                # p2 was copied before the others' steps this frame, so the
                # nearest may have changed since: the thread's end is a point
                # (it moved < 15 since) about as near as the nearest
                alvo = min(outros, key=lambda o: dist(xy(o.center), xy(p.fio.p2)))
                self.assertLess(dist(xy(alvo.center), xy(p.fio.p2)), 15)
                self.assertLess(dist(xy(alvo.center), xy(p.center)), far + 30)

    def test_a_caught_point_is_reborn_and_lends_its_colour(self):
        with ProgramRun(PATH, seed=3) as run:
            ns = run.ns
            caught = []
            reborn = ns["Ponto"].renascer

            def spy(ponto):
                caught.append((ponto, xy(ponto.center), ponto.color))
                reborn(ponto)

            ns["Ponto"].renascer = spy
            for _ in range(20 * SECOND):
                run.step(1)
                if caught:
                    break
            self.assertTrue(caught, "the comets caught nothing in 20 s")
            ponto, where, cor = caught[-1]
            colours = [c.color for c in ns["group"]["cometa"]]
            self.assertIn(cor, colours, "no comet took the caught point's colour")
            self.assertGreater(dist(xy(ponto.center), where), 0.0)

    def test_points_wrap_and_comets_stay_in(self):
        with ProgramRun(PATH, seed=3) as run:
            ns = run.ns
            w, h = ns["LARGURA"], ns["ALTURA"]
            p = list(ns["group"]["ponto"])[0]
            p.move_to(w - 2, h / 2)
            p.vel = ns["Vec2"](300, 0)
            run.step(10)
            self.assertLess(p.center.x, w / 2, "the point did not come back by the left")
            for _ in range(5 * SECOND):
                run.step(1)
                for c in ns["group"]["cometa"]:
                    self.assertTrue(0 <= c.center.x <= w and 0 <= c.center.y <= h)

    def test_mouse_pulls_then_pushes(self):
        with ProgramRun(PATH, seed=3) as run:
            ns = run.ns
            x, y = 640, 400
            run.move(x, y)
            run.step(2)
            before = mean_distance(ns, x, y)
            run.press(x, y)
            run.step(2 * SECOND)
            pulled = mean_distance(ns, x, y)
            self.assertLess(pulled, before * 0.8)
            run.release()
            run.step(SECOND // 2)
            self.assertGreater(mean_distance(ns, x, y), pulled * 1.2)

    def test_space_adds_comets_up_to_six_and_t_switches_the_trail(self):
        with ProgramRun(PATH, seed=3) as run:
            ns = run.ns
            self.assertEqual(len(ns["group"]["cometa"]), 3)
            for _ in range(5):
                run.key_down("SPACE")
                run.step(1)
                run.key_up("SPACE")
                run.step(1)
            self.assertEqual(len(ns["group"]["cometa"]), 6)
            self.assertFalse(ns["rastro"].enabled)
            run.key_down("T")
            run.step(1)
            run.key_up("T")
            run.step(1)
            self.assertTrue(ns["rastro"].enabled)


if __name__ == "__main__":
    unittest.main()
