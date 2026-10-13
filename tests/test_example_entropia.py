"""
The physics claims of ``examples/entropia.py``, played headless.

The example says: the colours mix once the middle wall goes and the energy of
a closed box stays put; loose outer walls fly off under the pressure (nothing
holds them) until the box bursts, and Recomeçar puts it back; a free middle
wall (piston) slides toward the cold side until the pressures match. The side
models here are the example's own bookkeeping (``.vel``, ``.mass``), never
``energia()`` or the HUD.

Bug class guarded: **a position-dependent force on a body that ``resolve()``
also pushes**. The sweep is mass-blind between two movable bodies (Collision
Design, "Relative-frame sweep": the body swept first stops and inherits the
partner's leftover motion), so a heavy wall swept before a light ball is
carried by the ball's whole step. Free walls pay nothing for that shove; an
early draft held them with a spring that read the pose, and the box gained
~5 % energy per second. The energy check on the loose walls fails if a force
that reads the position comes back without the fix in that section.

Run:

    python tests/run_tiers.py focused test_example_entropia
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402

PATH = "examples/entropia.py"
SECOND = 60


def total_energy(ns) -> float:
    """Motion energy of the balls and of every loose wall; gravity off."""
    e = 0.0
    for ball in ns["group"]["bola"]:
        e += 0.5 * float(ball.mass) * ball.vel.length ** 2
    for wall in list(ns["group"]["parede"]) + [ns["meio"]]:
        if wall.vel is None or wall.mass == ns["STATIC"]:
            continue
        e += 0.5 * float(wall.mass) * wall.vel.length ** 2
    return e


def outward(ns):
    """How far each outer wall went out from home (positive = out)."""
    far = {}
    for wall in ns["group"]["parede"]:
        x, y = wall.casa
        if wall.width < wall.height:      # a side wall moves in x
            far[wall] = (wall.center.x - x) * (1 if x > ns["MEIO"] else -1)
        else:
            far[wall] = (wall.center.y - y) * (1 if y > ns["ALTURA_MEIO"] else -1)
    return far


def side_counts(ns):
    left, right = ns["lado_esq"], ns["lado_dir"]
    return {
        "esq": (len(left.collides_with(group="azul")), len(left.collides_with(group="vermelha"))),
        "dir": (len(right.collides_with(group="azul")), len(right.collides_with(group="vermelha"))),
    }


class TestEntropiaClosedBox(unittest.TestCase):
    def test_the_wall_keeps_the_colours_apart_then_they_mix(self):
        with ProgramRun(PATH) as run:
            ns = run.ns
            run.step(2 * SECOND)
            half = ns["st"].bolas // 2
            self.assertEqual(side_counts(ns), {"esq": (half, 0), "dir": (0, half)})
            start = total_energy(ns)
            ns["st"].parede_no_meio = False
            run.step(10 * SECOND)
            counts = side_counts(ns)
            for side, (azuis, vermelhas) in counts.items():
                self.assertGreater(min(azuis, vermelhas), half // 4, f"{side} did not mix: {counts}")
            # Static walls, equal masses, bounce=1: the box keeps its energy.
            self.assertAlmostEqual(total_energy(ns) / start, 1.0, delta=0.01)


class TestEntropiaLooseWalls(unittest.TestCase):
    def test_the_walls_fly_out_and_the_energy_stays(self):
        with ProgramRun(PATH) as run:
            ns = run.ns
            run.step(2)
            ns["st"].parede_no_meio = False
            ns["st"].paredes_moveis = True
            run.step(2)
            start = total_energy(ns)
            run.step(2 * SECOND)              # the box still holds (first ball out ~4 s)
            self.assertEqual(len(ns["group"]["bola"]), ns["st"].bolas)
            # A spring that read the pose gained ~10 % here; free walls keep it exact.
            self.assertAlmostEqual(total_energy(ns) / start, 1.0, delta=0.01)
            for wall, far in outward(ns).items():
                self.assertGreater(far, 20, "the pressure did not push the walls out")

    def test_the_box_bursts_and_recomecar_puts_it_back(self):
        with ProgramRun(PATH) as run:
            ns = run.ns
            run.step(2)
            ns["st"].paredes_moveis = True
            run.step(8 * SECOND)
            self.assertLess(len(ns["group"]["bola"]), ns["st"].bolas, "no ball left the screen")
            ns["recomecar"]()
            run.step(1)
            self.assertEqual(len(ns["group"]["bola"]), ns["st"].bolas)
            for wall, far in outward(ns).items():
                self.assertLess(abs(far), 2, "a wall did not come home")


class TestEntropiaPiston(unittest.TestCase):
    def test_the_piston_moves_toward_the_cold_side_and_holds_it_in(self):
        with ProgramRun(PATH) as run:
            ns = run.ns
            run.step(2)
            ns["st"].temp_azuis = 10       # left: hot
            ns["st"].temp_vermelhas = 1    # right: cold
            ns["recomecar"]()
            ns["st"].meio_movel = True
            meio = ns["meio"]
            height = meio.center.y
            run.step(6 * SECOND)
            self.assertGreater(meio.center.x, ns["MEIO"] + 60, "the hot side did not push it")
            # Every ball's knock also shoves it sideways; the piston keeps its height
            # (a drift opened a gap at one end and let balls through).
            self.assertAlmostEqual(meio.center.y, height, delta=1.0)
            half = ns["st"].bolas // 2
            self.assertEqual(side_counts(ns), {"esq": (half, 0), "dir": (0, half)})


if __name__ == "__main__":
    unittest.main()
