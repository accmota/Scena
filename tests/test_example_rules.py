"""
The game rules of the tutorial endpoints, played on purpose: a run of the
``examples/`` file, headless, with the path a 600-frame run without input
never takes (``test_tutorial_steps`` only runs each step; it presses no key,
so no kunai lands twice and the last life is never lost).

Bug classes guarded (catalogue: Testing Design, TU):

* **A rule the game names but the code skips** (TU10): Ligue 4 said "quatro
  em linha" and checked only rows and columns. Each of the four directions
  wins here, and a column's top ball is not read through a negative index
  (``coluna[-1]``) by the diagonal going down.
* **A hit on something already dying counts again** (TU9): ``untag`` takes
  the broken robot out of ``robo``, but its own ``@collide_with("kunai")``
  still fires: a second kunai replayed the break (sound, clip, a second
  ``after(2, destroy)``). Every ninja endpoint breaks a robot once.
* **A one-shot clip from the frame loop** (TU8, the static half is
  ``test_tutorials.TestOneShotClipPlaysOnce``): the dying ninja played
  ``"morto"`` in mid air, and asked again every frame it would loop. It falls
  to the ground first, then holds the clip's last cell.
* **The moving platform** (tutorial 22, "O elevador"): the ninja rides the
  elevator up and down with its feet on it every frame, and reaches the star
  only the elevator gets to. A fall into the water on the last life sinks
  instead of sending the ninja back to the start.

Run:

    python tests/run_tiers.py focused test_example_rules
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402

NINJAS = ("examples/ninja_mundo.py", "examples/ninja_nivel.py", "examples/ninja_perigos.py")


class _Ball:
    def __init__(self, dono: str) -> None:
        self.dono = dono
        self.glow = None


class TestLigue4FourInARow(unittest.TestCase):
    """``conferir`` finds four in every direction, and only real fours."""

    BOARDS = {
        # one string per column, bottom first; V = vermelho, a = azul
        "deitadas": (["V", "V", "V", "V", "", "", ""], True),
        "em pé": (["aVVVV", "", "", "", "", "", ""], True),
        "diagonal que sobe": (["V", "aV", "aaV", "aaaV", "", "", ""], True),
        "diagonal que desce": (["", "", "aaaV", "aaV", "aV", "V", ""], True),
        "nenhuma": (["VaV", "aVa", "VaV", "", "", "", ""], False),
        # (1, -1) from the top of column 0 steps to l = -1 and -2: without
        # ``l < 0`` it reads coluna[-1] and coluna[-2] and finds a four
        "por baixo": (["aV", "V", "aV", "VVa", "", "", ""], False),
    }

    def test_each_direction(self):
        with ProgramRun("examples/ligue4.py") as run:
            run.step(2)
            ns = run.ns
            for name, (cols, wins) in self.BOARDS.items():
                with self.subTest(board=name):
                    ns["colunas"][:] = [
                        [_Ball("vermelho" if ch == "V" else "azul") for ch in col] for col in cols]
                    ns["st"].fim = False
                    ns["st"].vez = "vermelho"
                    ns["conferir"]()
                    self.assertEqual(bool(ns["st"].fim), wins)


def _spy_plays(run, actor, clips):
    """Count ``actor.play(name)`` for ``name`` in ``clips`` (a class-level wrapper)."""
    cls = type(actor)
    real = cls.play
    seen = []

    def play(self, name, *args, **kw):
        if self is actor and name in clips:
            seen.append(run.frames)
        return real(self, name, *args, **kw)

    cls.play = play
    return seen


class TestNinjaRobotBreaksOnce(unittest.TestCase):
    def test_a_second_kunai_does_not_break_it_again(self):
        for path in NINJAS:
            with self.subTest(example=os.path.basename(path)), ProgramRun(path) as run:
                run.step(5)
                ns = run.ns
                robo = list(ns["group"]["robo"])[0]
                plays = _spy_plays(run, robo, {"quebrado"})
                ns["Kunai"](center=(robo.center.x, robo.center.y + 40))
                run.step(10)
                ns["Kunai"](center=(robo.center.x, robo.center.y + 40))
                run.step(10)
                self.assertEqual(len(plays), 1, f"the break played at frames {plays}")


class TestNinjaFallsThenDies(unittest.TestCase):
    def test_the_last_life_lost_in_the_air(self):
        for path in NINJAS:
            with self.subTest(example=os.path.basename(path)), ProgramRun(path) as run:
                run.step(3)
                ns = run.ns
                heroi = list(ns["group"]["heroi"])[0]
                ns["st"].vidas = 1
                heroi.center = (300, 500)      # over the platform at y = 220
                heroi.vel.y = 0
                run.step(2)
                heroi.perder()
                run.step(5)
                self.assertFalse(heroi.showing("morto"), "dead in mid air")
                self.assertNotIn("bottom", heroi.touching_sides)
                run.step(60)
                self.assertIn("bottom", heroi.touching_sides, "never reached the ground")
                self.assertTrue(heroi.showing("morto"))
                run.step(60)                   # the clip (0.8 s) is over
                last = heroi.frame
                cells = set()
                for _ in range(120):
                    run.step(1)
                    cells.add(heroi.frame)
                self.assertEqual(cells, {last}, "the death clip started over")


class TestNinjaElevator(unittest.TestCase):
    PATH = "examples/ninja_perigos.py"

    def test_the_ninja_rides_it_up_and_down(self):
        with ProgramRun(self.PATH) as run:
            run.step(3)
            ns = run.ns
            heroi = list(ns["group"]["heroi"])[0]
            elevador = [p for p in ns["group"]["plataforma"] if type(p).__name__ == "Rect"]
            self.assertEqual(len(elevador), 1)
            elevador = elevador[0]
            low = elevador.center.y
            heroi.center = (elevador.center.x, low + 100)
            heroi.vel.y = 0
            run.step(30)
            gaps, top, off = [], low, 0
            for _ in range(360):           # one trip up and one down (3 s each)
                run.step(1)
                gaps.append(heroi.center.y - elevador.center.y)
                top = max(top, heroi.center.y)
                off += "bottom" not in heroi.touching_sides
            self.assertEqual(off, 0, "the feet left the elevator")
            self.assertLess(max(gaps) - min(gaps), 2.0)
            self.assertGreater(top, low + 300)

    def test_the_high_star_needs_it(self):
        with ProgramRun(self.PATH) as run:
            run.step(3)
            ns = run.ns
            stars = [s for s in ns["group"]["estrela"] if s.center.x > 3800 and s.center.y > 600]
            self.assertEqual(len(stars), 1)
            heroi = list(ns["group"]["heroi"])[0]
            heroi.center = (stars[0].center.x, 200)
            heroi.vel.y = 0
            run.step(300)
            self.assertFalse(stars[0], "the elevator did not reach the star")

    def test_the_last_fall_sinks(self):
        with ProgramRun(self.PATH) as run:
            run.step(3)
            ns = run.ns
            heroi = list(ns["group"]["heroi"])[0]
            ns["st"].vidas = 1
            heroi.center = (560, 150)          # over the first water
            heroi.vel.y = 0
            run.step(60)
            self.assertEqual(ns["st"].vidas, 0)
            self.assertLess(heroi.center.y, 0, "sent back to the start")


if __name__ == "__main__":
    unittest.main()
