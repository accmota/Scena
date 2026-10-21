"""
The long claims of ``examples/affinity.py`` (gate / deep tier; ~70 s alone).

The quick part, its helpers and the bug classes are in
``test_example_affinity``. Here: free atoms react into molecules and every
bond obeys the rules; the cold stops the reactions; red and amber molecules
separate (Ilhas); ions hold red molecules (Coroas); nobody piles up, warm or
at full heat; the shell leaves a gap across a weak bond; and every recipe
keeps its calm speed (the canary for a repulsion that pumps energy).

Run:

    python tests/run_tiers.py focused test_example_affinity_deep
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
from test_example_affinity import (  # noqa: E402
    AWAY, PATH, SECOND, check_bonds, closeness, same_kind_nearby, tap,
)


class TestAffinityChemistry(unittest.TestCase):
    def test_water_forms_and_every_bond_obeys_the_rules(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            for _ in range(30):
                run.step(SECOND)
                check_bonds(self, ns)
            reds = [a for a in ns["atomos"] if a.nome == "vermelho"]
            water = [a for a in reds if sorted(b.nome for b in a.vizinhos) == ["branco", "branco"]]
            self.assertGreater(len(water), 0.75 * len(reds), "the atoms did not react into water")
            self.assertGreater(len(ns["fracas"]), 40, "water makes no weak bonds")
            # charge comes from the bonds: a free atom is neutral
            for a in ns["atomos"]:
                if not a.vizinhos:
                    self.assertEqual(a.carga, 0)

    def test_the_cold_stops_the_reactions(self):
        bonds = {}
        for calor in (0.0, 0.4):
            with ProgramRun(PATH, seed=1) as run:
                run.move(*AWAY)
                run.ns["st"].calor = calor
                run.step(10 * SECOND)
                bonds[calor] = len(run.ns["fortes"])
        self.assertGreater(bonds[0.4], 60)
        self.assertLess(bonds[0.0], 0.2 * bonds[0.4], "atoms react without heat")

    def test_oil_and_water_do_not_mix(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            tap(run, "3")
            self.assertEqual(ns["st"].receita, "Ilhas")
            samples = []
            for _ in range(5):
                run.step(10 * SECOND)
                samples.append(same_kind_nearby(ns))
            check_bonds(self, ns)
            # mixed at random this is ~0.5 (50 water and 40 oil molecules)
            self.assertGreater(sum(samples[2:]) / 3, 0.62, samples)
            for a in ns["atomos"]:
                if a.molecula.nome == "ambar" or any(b.nome == "ambar" for b in a.vizinhos):
                    self.assertEqual(a.pontes, [], "oil makes weak bonds")

    def test_ions_gather_red_molecules(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            tap(run, "2")
            run.step(20 * SECOND)
            check_bonds(self, ns)
            ions = [a for a in ns["atomos"] if a.valencia == 0]
            self.assertEqual(len(ions), 20)
            held = sum(len(a.pontes) for a in ions) / len(ions)
            self.assertGreater(held, 1.5, "the ions hold no molecules")
            self.assertEqual(ns["st"].receita, "Coroas")


class TestAffinityRepulsion(unittest.TestCase):
    def test_nobody_piles_up(self):
        """The drawn balls touch below BOLA (0.6) of the contact distance."""
        for calor, lowest in ((0.4, 0.5), (1.0, 0.4)):
            with self.subTest(calor=calor), ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                run.move(*AWAY)
                ns["st"].calor = calor
                run.step(10 * SECOND)
                seen = []
                for _ in range(SECOND):
                    run.step(1)
                    free, weak = closeness(ns)
                    seen += free + weak
                self.assertGreater(len(seen), 1000, "vacuous: no close pairs")
                self.assertGreater(min(seen), lowest)
                seen.sort()
                self.assertGreater(seen[len(seen) // 20], 0.7, "many atoms sit on each other")

    def test_the_shell_leaves_a_gap_across_a_weak_bond(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            run.step(20 * SECOND)
            weak = []
            for _ in range(30):
                run.step(1)
                weak += closeness(ns)[1]
            self.assertGreater(len(weak), 500)
            weak.sort()
            self.assertGreater(weak[len(weak) // 2], 1.05, "weak bonds pull the atoms onto each other")

    def test_every_recipe_keeps_its_calm_speed(self):
        """Canary for a repulsion that pumps energy (module docstring)."""
        for key in ("1", "2", "3", "R"):
            with self.subTest(recipe=key), ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                run.move(*AWAY)
                tap(run, key)
                worst = 0
                for _ in range(10):
                    run.step(SECOND)
                    speeds = [math.hypot(a.vx, a.vy) for a in ns["atomos"]]
                    worst = max(worst, sum(speeds) / len(speeds))
                self.assertLess(worst, 200, "the atoms keep speeding up")



if __name__ == "__main__":
    unittest.main()
