"""
The whole races of ``examples/corrida.py``, played headless (gate / deep: ~10 s).

The example says: the computer cars finish every lap on each level as it is,
obstacles included, dodging and backing out by themselves; two drivers
finish the laps, the race ends with the result listing all four cars in
arrival order, and Space goes back to the choice of players (then the track). The rules each
race is made of are in ``test_example_corrida`` (quick).

Run:

    python tests/run_tiers.py focused test_example_corrida_deep
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
from test_example_corrida import PATH, SECOND, Race, act, heading, pelo_menu, tap, xy  # noqa: E402


class TestCorridaCpuRace(unittest.TestCase):
    def test_the_computer_cars_finish_the_laps_on_the_level(self):
        """On each level as it is, obstacles included: each computer car
        finishes every lap on its own, dodging and backing out by itself."""
        for pista in ("SERPENTINA", "RELÂMPAGO"):
            with self.subTest(pista=pista), ProgramRun(PATH) as run:
                r = Race(run, pista=pista)
                r.azul.active = False
                for carro in r.cpus:
                    carro.active = True
                for _ in range(100 * SECOND):
                    if all(c.chegou for c in r.cpus):
                        break
                    run.step(1)
                for carro in r.cpus:
                    self.assertTrue(carro.chegou,
                                    f"{pista}: {carro.nome} stopped at lap {carro.voltas}, mark {carro.marco}")



class TestCorridaRace(unittest.TestCase):
    def drive(self, run, carro):
        """Hold the car's keys toward a mark ahead on the centre line."""
        marcos = run.ns["MARCOS"]
        alvo = marcos[(carro.marco + 3) % len(marcos)]
        diff = (heading(xy(carro.center), alvo) - carro.angle + 540) % 360 - 180
        keys = carro.teclas
        want = {
            keys["acelera"]: abs(diff) < 70 or carro.velocidade < 120,
            keys["freia"]: abs(diff) > 70 and carro.velocidade > 200,
            keys["esquerda"]: diff > 6,
            keys["direita"]: diff < -6,
        }
        for key, on in want.items():
            if on and key not in self.held:
                run.key_down(key)
                self.held.add(key)
            elif not on and key in self.held:
                run.key_up(key)
                self.held.discard(key)

    def test_two_drivers_finish_the_laps_and_space_races_again(self):
        with ProgramRun(PATH) as run:
            ns = run.ns
            self.held = set()
            pelo_menu(run)
            corrida = act()
            corrida_carros = list(ns["group"]["carros"])
            self.assertEqual(len(corrida_carros), 4)
            self.assertEqual(sum(1 for c in corrida_carros if c.cpu), 2)
            # This pilot only follows the centre line and never backs out, so
            # the race runs on a clear road: the level's obstacles are the
            # author's to move (each kind has its own test above).
            for nome in ("barril", "pneu", "cone", "oleo", "arvore"):
                for coisa in list(ns["group"][nome]):
                    coisa.destroy()
            for _ in range(120 * SECOND):
                if act() is not corrida:
                    break
                for carro in (corrida.azul, corrida.vermelho):
                    if not carro.chegou:
                        self.drive(run, carro)
                run.step(1)
            for key in list(self.held):
                run.key_up(key)
            run.step(1)
            self.assertEqual(type(act()).__name__, "Resultado", "the race never ended")
            self.assertGreaterEqual(ns["st"].chegaram, 2)
            podio = [nome for nome, cor in ns["st"].podio]
            self.assertEqual(sorted(podio), ["AMARELO", "AZUL", "VERDE", "VERMELHO"])
            # Whoever arrived is ahead of whoever did not, in arrival order.
            chegaram = [c for c in corrida_carros if c.chegou]
            chegaram.sort(key=lambda c: c.chegada)
            self.assertEqual(podio[:len(chegaram)], [c.nome for c in chegaram])
            tap(run, "SPACE")
            self.assertEqual(type(act()).__name__, "Escolha")
            pelo_menu(run)
            run.step(2)
            self.assertEqual(type(act()).__name__, "Corrida")
            self.assertFalse(ns["st"].largou)
            self.assertEqual(ns["st"].chegaram, 0)
            self.assertEqual(act().azul.voltas, 0)



if __name__ == "__main__":
    unittest.main()
