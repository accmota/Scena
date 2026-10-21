"""
The claims of ``examples/affinity.py``, played headless.

The example says: free white and red atoms react into molecules (a red one
with two whites); a strong bond joins two different elements and never more
than an atom's valence; a weak bond joins a + end to a - end of two
different molecules, at most the atom's own count of them; nobody piles up
(a soft shell around each atom, a hard core inside it), and the shell
leaves a gap even across a weak bond; the cold stops the reactions; red and
amber molecules do not mix (Ilhas); ions gather red molecules around them
(Coroas); the spark breaks the bonds near the mouse; a drag stirs the
liquid; UP / DOWN heat and cool; 1 2 3 R switch the recipes (R draws new
rules, the table shows them); T the trail.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change, and **a world step that slides back onto actor
fields**: every read of a field on a Circle goes through Scena's change
tracking (~0.6 us); the step reads ~30 000 numbers a frame, so keeping them
on the Circle made it ~6x slower (15-26 ms instead of ~4 ms with 210 atoms,
measured 2026-10-21). The numbers live on a plain object; the canary below
fails if an atom becomes an actor. Also **a repulsion that pumps energy**: a
1/d² core was so stiff near its floor that a 1/60 s step overshot and the
atoms sped up (mean speed 1148 px/s five seconds into Ilhas, ~85 when
calm); every recipe is checked to keep its calm speed.

The long runs (the chemistry, nobody piles up, the gap, every recipe's
calm speed) are in ``test_example_affinity_deep`` (gate / deep; ~70 s).

Run:

    python tests/run_tiers.py focused test_example_affinity test_example_affinity_deep
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

PATH = "examples/affinity.py"
SECOND = 60
AWAY = (-500, -500)     # the mouse parked off screen


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


def check_bonds(test, ns):
    """Every bond obeys the rules the docstring states."""
    polo = ns["POLO"]
    for a in ns["atomos"]:
        test.assertLessEqual(len(a.vizinhos), a.valencia, a.nome)
        test.assertLessEqual(len(a.pontes), a.max_fracas, a.nome)
        for b in a.vizinhos:
            test.assertIn(a, b.vizinhos)
            test.assertNotEqual(a.nome, b.nome, "a strong bond between two equal atoms")
        for b in a.pontes:
            test.assertIn(a, b.pontes)
            test.assertIsNot(a.molecula, b.molecula, "a weak bond inside one molecule")
            test.assertLess(a.carga * b.carga, 0, "a weak bond between equal charges")
            test.assertGreater(abs(a.carga), polo)


def molecules(ns):
    mols = {}
    for a in ns["atomos"]:
        mols.setdefault(a.molecula, []).append(a)
    return list(mols.values())


def same_kind_nearby(ns, reach=60):
    """Mean share of same-kind molecules (oil / water) around a molecule."""
    centres = []
    for atoms in molecules(ns):
        if len(atoms) < 3:
            continue
        x = sum(a.x for a in atoms) / len(atoms)
        y = sum(a.y for a in atoms) / len(atoms)
        centres.append((x, y, any(a.nome == "ambar" for a in atoms)))
    total = counted = 0
    for i, (x, y, oil) in enumerate(centres):
        near = [c for j, c in enumerate(centres)
                if j != i and math.dist((x, y), c[:2]) < reach]
        if near:
            total += sum(c[2] == oil for c in near) / len(near)
            counted += 1
    return total / max(counted, 1)


def closeness(ns):
    """Distance / contact distance of every close pair with no strong bond."""
    free, weak = [], []
    atoms = ns["atomos"]
    for i, a in enumerate(atoms):
        for b in atoms[i + 1:]:
            if b in a.vizinhos:
                continue
            ratio = math.dist((a.x, a.y), (b.x, b.y)) / (a.raio + b.raio)
            if ratio < 1.3:
                (weak if b in a.pontes else free).append(ratio)
    return free, weak


class TestAffinityRepulsion(unittest.TestCase):
    def test_no_pile_up_after_a_spark_at_full_heat(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            ns["st"].calor = 1.0
            run.move(ns["CX"], ns["CY"])
            run.step(5 * SECOND)
            tap(run, "SPACE")
            seen = []
            for _ in range(SECOND):
                run.step(1)
                free, weak = closeness(ns)
                seen += free + weak
            self.assertGreater(min(seen), 0.35)


class TestAffinityControls(unittest.TestCase):
    def test_the_spark_breaks_the_bonds_near_the_mouse(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            run.step(20 * SECOND)
            alvo = next(a for a in ns["atomos"] if len(a.vizinhos) == 2)
            far = [a for a in ns["atomos"]
                   if math.dist((a.x, a.y), (alvo.x, alvo.y)) > ns["FAISCA"] + 60]
            before = {a: len(a.vizinhos) for a in far}
            run.move(alvo.x, alvo.y)
            run.key_down("SPACE")
            run.step(1)
            run.key_up("SPACE")
            self.assertEqual(alvo.vizinhos, [])
            self.assertEqual(alvo.pontes, [])
            self.assertEqual({a: len(a.vizinhos) for a in far}, before)
            run.move(*AWAY)
            run.step(1)
            self.assertEqual(alvo.carga, 0, "a freed atom kept its charge")

    def test_a_drag_stirs_the_liquid(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            cx, cy = ns["CX"], ns["CY"]
            run.move(*AWAY)
            run.step(5 * SECOND)
            run.move(cx - 100, cy)
            run.press(cx - 100, cy)
            speeds = []
            for k in range(20):
                run.move(cx - 100 + 10 * (k + 1), cy)
                run.step(1)
                x = cx - 100 + 10 * (k + 1)
                near = [a for a in ns["atomos"] if math.dist((a.x, a.y), (x, cy)) < 60]
                speeds += [a.vx for a in near]
            run.release()
            self.assertTrue(speeds)
            self.assertGreater(sum(speeds) / len(speeds), 100, "the drag did not pull the atoms along")

    def test_up_and_down_heat_and_cool_within_bounds(self):
        with ProgramRun(PATH, seed=1) as run:
            st = run.ns["st"]
            run.move(*AWAY)
            start = st.calor
            run.key_down("UP")
            run.step(SECOND)
            run.key_up("UP")
            self.assertAlmostEqual(st.calor, start + 0.3, delta=0.02)
            run.key_down("UP")
            run.step(4 * SECOND)
            run.key_up("UP")
            self.assertEqual(st.calor, 1)
            run.key_down("DOWN")
            run.step(5 * SECOND)
            run.key_up("DOWN")
            self.assertEqual(st.calor, 0)

    def test_recipes_and_new_elements(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            tap(run, "R")
            self.assertEqual(ns["st"].receita, "Acaso")
            for nome in ("branco", "vermelho", "ambar"):
                e = ns["ELEMENTOS"][nome]
                self.assertIn(e["valencia"], (1, 2, 3))
                self.assertTrue(0 <= e["avidez"] <= 1)
                self.assertIn(f"valência {e['valencia']}", ns["legenda"][nome].text)
                self.assertIn(f"avidez {e['avidez']:.2f}", ns["legenda"][nome].text)
            atom = next(a for a in ns["atomos"] if a.nome == "vermelho")
            self.assertEqual(atom.valencia, ns["ELEMENTOS"]["vermelho"]["valencia"])
            run.step(10 * SECOND)
            check_bonds(self, ns)
            tap(run, "1")
            self.assertEqual(ns["st"].receita, "Nascente")
            self.assertEqual(ns["ELEMENTOS"], ns["ORIGINAIS"])
            self.assertIn("valência 2  avidez 0.90", ns["legenda"]["vermelho"].text)
            self.assertEqual(len(ns["atomos"]), 210)
            self.assertEqual(ns["fortes"] + ns["fracas"], [])

    def test_a_recipe_switch_does_not_freeze_the_window(self):
        """A draft looked for free spots at random among every atom: with the
        dish nearly full a switch took seconds and Scena's watchdog reported
        a frozen window (found by the quick tier, 2026-10-21). The atoms now
        take points of a shuffled hex lattice (~0.1 s per switch)."""
        import time
        with ProgramRun(PATH, seed=1) as run:
            for key in ("1", "2", "3", "R"):
                run.key_down(key)
                start = time.perf_counter()
                run.step(1)
                took = time.perf_counter() - start
                run.key_up(key)
                run.step(1)
                self.assertLess(took, 1.0, f"recipe {key} took {took:.2f} s")

    def test_t_switches_the_trail(self):
        with ProgramRun(PATH, seed=1) as run:
            rastro = run.ns["rastro"]
            self.assertFalse(rastro.enabled)
            tap(run, "T")
            self.assertTrue(rastro.enabled)
            tap(run, "T")
            self.assertFalse(rastro.enabled)


class TestAffinityFastPath(unittest.TestCase):
    def test_atoms_are_plain_numbers_not_actors(self):
        """Canary: the step's numbers stay off the Circle (module docstring)."""
        from scena.entity import Entity
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.step(2)
            for a in ns["atomos"]:
                self.assertNotIsInstance(a, Entity)
                self.assertIsInstance(a.x, float)
                self.assertIsInstance(a.bola, Entity)


if __name__ == "__main__":
    unittest.main()
