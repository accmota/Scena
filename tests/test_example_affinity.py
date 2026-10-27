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
rules, the table shows them) and the sliders show each recipe's mix; the
sliders and Rodar build a mix of free atoms with the rules of the moment,
and dragging a slider does not stir; T the trail.

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
And **a placement that searches among every atom**: a recipe switch took
seconds (a frozen window); the switch's own lines per atom placed are
counted, not timed (a 1 s bound failed under the quick tier's load, WP49).

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


SWITCHES = ("receita", "elementos_novos", "mistura")   # what 1 2 3 R and Rodar call
LINES_PER_ATOM = 100    # the lattice spends 33-40; a search among every atom 165-640


def switch_lines(run, limit):
    """The lines of the example's own code that a switch runs in one frame
    (``SWITCHES`` and what they call; not the world's step): its work, which
    the machine's load does not change (a clock does, WP49). Counting stops
    at ``limit``, so a runaway costs its own time and no tracing."""
    path = os.path.normcase(run.ns["__file__"])
    count = 0

    def line(frame, event, arg):
        nonlocal count
        if event != "line":
            return line
        count += 1
        if count >= limit:
            sys.settrace(None)
            return None
        return line

    def call(frame, event, arg):
        if os.path.normcase(frame.f_code.co_filename) != path:
            return None
        while frame is not None:
            if frame.f_code.co_name in SWITCHES:
                return line
            frame = frame.f_back
        return None

    old = sys.gettrace()
    sys.settrace(call)
    try:
        run.step(1)
    finally:
        sys.settrace(old)
    return count


# the draft's search, planted in the example (compiled under its file name,
# so its lines count): a point at random until no atom is near it
RANDOM_SEARCH = '''
class _BuscaAoAcaso:
    def __init__(self, espaco):
        self.espaco = espaco * 0.6
    def __len__(self):
        return 1
    def pop(self):
        while True:
            x = uniform(CX - PRATO, CX + PRATO)
            y = uniform(CY - PRATO, CY + PRATO)
            if distance((x, y), (CX, CY)) < PRATO - 24 and all(
                    distance((x, y), (a.x, a.y)) > self.espaco for a in atomos):
                return x, y
def lugares(espaco):
    return _BuscaAoAcaso(espaco)
'''


def check_bonds(test, ns):
    """Every bond obeys the rules the docstring states."""
    for a in ns["atomos"]:
        test.assertLessEqual(len(a.vizinhos), a.valencia, a.nome)
        test.assertLessEqual(len(a.pontes), a.max_fracas, a.nome)
        for b in a.vizinhos:
            test.assertIn(a, b.vizinhos)
            test.assertNotEqual(a.nome, b.nome, "a strong bond between two equal atoms")
        for b in a.pontes:
            test.assertIn(a, b.pontes)
            test.assertIsNot(a.molecula, b.molecula, "a weak bond inside one molecule")
            # it forms above POLO and lives while the two charges stay
            # opposite (a borrowed charge fades as the atom leaves the ion)
            test.assertLess(a.carga * b.carga, 0, "a weak bond between equal charges")


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
    def test_free_atoms_react_even_when_cool(self):
        """The shell must not hide the collision from the reaction check: it
        measured the approach at 1.2x the contact, inside the shell, after
        the shell had braked both atoms. At 10% heat 27 bonds formed in
        10 s instead of 118, and a dish of free atoms (Acaso, or after a
        spark) looked dead (user report 2026-10-21). The check now sits at
        the shell's edge."""
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.move(*AWAY)
            ns["st"].calor = 0.1
            run.step(5 * SECOND)
            self.assertGreater(len(ns["fortes"]), 60, "free atoms do not react when cool")

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
        take points of a shuffled hex lattice (~0.1 s per switch).

        The check counts the switch's own lines per atom placed, not the
        seconds: a bound of 1 s read 1.12 s under the quick tier's load on a
        slower machine (WP49)."""
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            for key in ("1", "2", "3", "R"):
                limit = LINES_PER_ATOM * 400        # more atoms than any recipe makes
                run.key_down(key)
                lines = switch_lines(run, limit)
                run.key_up(key)
                run.step(1)
                placed = len(ns["atomos"])
                self.assertLess(lines, LINES_PER_ATOM * placed,
                                f"recipe {key}: {lines} lines for {placed} atoms")

    def test_the_switch_check_catches_a_random_search(self):
        """Canary: the draft's search planted back (a spot at random until no
        atom is near) fails the check, even a mild one (~0.07 s more a
        switch; at 0.68 of the lattice's spacing Coroas took 57 s)."""
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            exec(compile(RANDOM_SEARCH, ns["__file__"], "exec"), ns)
            run.key_down("1")
            lines = switch_lines(run, LINES_PER_ATOM * 400)
            run.key_up("1")
            self.assertEqual(len(ns["atomos"]), 210)
            self.assertGreaterEqual(lines, LINES_PER_ATOM * 210)

    def test_t_switches_the_trail(self):
        with ProgramRun(PATH, seed=1) as run:
            rastro = run.ns["rastro"]
            self.assertFalse(rastro.enabled)
            tap(run, "T")
            self.assertTrue(rastro.enabled)
            tap(run, "T")
            self.assertFalse(rastro.enabled)


def click(run, x, y):
    run.move(x, y)
    run.press(x, y)
    run.step(1)
    run.release()
    run.step(1)


class TestAffinityMixPanel(unittest.TestCase):
    """The sliders set how many atoms and the weight of each element;
    Rodar builds that mix of free atoms with the rules of the moment."""

    def press_rodar(self, run):
        centre = run.ns["rodar"].box.center
        click(run, centre.x, centre.y)
        run.move(*AWAY)

    def test_rodar_builds_the_mix_of_the_sliders(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            st.total, st.branco, st.vermelho, st.ambar, st.verde, st.violeta = 300, 10, 5, 3, 1, 1
            old = set(ns["atomos"])
            self.press_rodar(run)
            self.assertFalse(old & set(ns["atomos"]), "Rodar kept atoms of the old dish")
            self.assertEqual(st.receita, "Mistura")
            count = {n: sum(a.nome == n for a in ns["atomos"]) for n in ns["ELEMENTOS"]}
            self.assertEqual(count, {"branco": 150, "vermelho": 75, "ambar": 45, "verde": 15, "violeta": 15})
            # free atoms: two frames after the click only a few collisions reacted
            self.assertLess(len(ns["fortes"]), 10, "Rodar does not start from free atoms")
            run.step(5 * SECOND)
            self.assertGreater(len(ns["fortes"]), 60, "the mix does not react")

    def test_rodar_keeps_the_rules_of_the_moment(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            tap(run, "R")
            rules = {n: dict(e) for n, e in ns["ELEMENTOS"].items()}
            self.press_rodar(run)
            self.assertEqual(ns["ELEMENTOS"], rules)
            red = next(a for a in ns["atomos"] if a.nome == "vermelho")
            self.assertEqual(red.valencia, rules["vermelho"]["valencia"])

    def test_a_recipe_shows_its_mix_on_the_sliders(self):
        with ProgramRun(PATH, seed=1) as run:
            st = run.ns["st"]
            tap(run, "3")       # 50 red and 40 amber molecules, each with two whites
            self.assertEqual((st.total, st.branco, st.vermelho, st.ambar, st.verde, st.violeta),
                             (270, 10, 3, 2, 0, 0))
            tap(run, "1")
            self.assertEqual((st.total, st.branco, st.vermelho), (210, 10, 5))

    def test_all_weights_at_zero_leave_the_dish_as_it_is(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            st.branco = st.vermelho = st.ambar = st.verde = st.violeta = 0
            before = list(ns["atomos"])
            self.press_rodar(run)
            self.assertEqual(ns["atomos"], before)
            self.assertEqual(st.receita, "Nascente")

    def test_dragging_a_slider_does_not_stir_the_liquid(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            run.move(*AWAY)
            run.step(2 * SECOND)
            centre = ns["rodar"].box.center
            x, y = centre.x, centre.y + 6 * 40      # the first slider (Átomos)
            start = st.total
            run.move(x, y)
            run.press(x, y)
            run.step(1)
            for k in range(1, 21):
                run.move(x + 6 * k, y)
                run.step(1)
            run.release()
            run.step(1)
            self.assertNotEqual(st.total, start, "vacuous: the slider did not move")
            near = [a for a in ns["atomos"] if a.x < ns["CX"] - ns["PRATO"] + 140]
            self.assertTrue(near)
            self.assertLess(sum(a.vx for a in near) / len(near), 40, "the slider drag stirred the atoms")


class TestAffinityIons(unittest.TestCase):
    """An ion lends the opposite charge to the atoms near it, so it holds
    neutral atoms too (before, with no charged molecule in the dish, the two
    ions only bonded each other); Acaso draws the ions as well."""

    def test_an_ion_holds_neutral_atoms(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            run.move(*AWAY)
            # no red: white on amber stays neutral, only the ions are charged
            st.total, st.branco, st.vermelho, st.ambar, st.verde, st.violeta = 200, 5, 0, 5, 1, 1
            ns["mistura"]()
            run.step(8 * SECOND)
            check_bonds(self, ns)
            polo = ns["POLO"]
            ions = [a for a in ns["atomos"] if a.carga_fixa]
            held = [(ion, b) for ion in ions for b in ion.pontes if abs(b.carga_propria) < polo]
            self.assertGreater(len(held), 15, "the ions hold no neutral atom")
            for ion, b in held:
                self.assertLess(b.carga * ion.carga_fixa, 0, "a borrowed charge with the ion's sign")
            # the borrowed charge is there only near an ion
            reach = ns["ALCANCE_INDUZ"]
            far = [a for a in ns["atomos"] if not a.carga_fixa
                   and all(math.dist((a.x, a.y), (i.x, i.y)) >= reach for i in ions)]
            self.assertTrue(far)
            for a in far:
                self.assertEqual(a.carga, a.carga_propria)

    def test_acaso_draws_the_ions(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            tap(run, "R")
            for nome, sign in (("verde", 1), ("violeta", -1)):
                e = ns["ELEMENTOS"][nome]
                self.assertTrue(0.5 <= sign * e["carga"] <= 1.5, e)
                self.assertIn(e["fracas"], range(2, 7))
                self.assertIn(f"íon {e['carga']:+.2f}  segura {e['fracas']}", ns["legenda"][nome].text)
            ns["st"].verde = ns["st"].violeta = 3
            centre = ns["rodar"].box.center
            click(run, centre.x, centre.y)
            ion = next(a for a in ns["atomos"] if a.nome == "verde")
            self.assertEqual(ion.carga_fixa, ns["ELEMENTOS"]["verde"]["carga"])
            self.assertEqual(ion.max_fracas, ns["ELEMENTOS"]["verde"]["fracas"])
            tap(run, "1")
            self.assertEqual(ns["ELEMENTOS"], ns["ORIGINAIS"])


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
