"""
The claims of ``examples/guardiao.py``, played headless.

The example says: the ship flies around the ring (one angle that is never
wrapped, so the two lights that chase it never take the long way past
360); it shoots outward, and a narrow radar pulls a shot onto an enemy almost
in front; a Seta dies in one shot, a Mandala in three, a Cristal in five; a
shot Mina (one that crosses the screen, apart from the wave) blows up the
enemies around it, other mines in a chain; an
enemy shot costs the ship one life and only sparks on the ring, an enemy that
reaches the ring costs the ring one; with DUPLO the lights shoot ABERTURA
degrees off the ship's line; pills give double, fast and strong shots and a
Portal shield for DURACAO seconds; the waves run one after the other to "O
ANEL ESTÁ SALVO", and the camera turns only on the waves marked virar;
losing either life ends the game and R starts a fresh one.

Bug classes guarded: **an example that stops doing what its docstring says**
while it still builds and runs, and **a power-up that never ends** (the
shield Portal must leave when its time runs out).

Run:

    python tests/run_tiers.py focused test_example_guardiao
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
from scena.act import get_act_manager  # noqa: E402

PATH = "examples/guardiao.py"
SECOND = 60


def act():
    return get_act_manager().current


def count(ns, name):
    return len(list(ns["group"][name]))


def quiet(run):
    """The game with no waves: each test places its own enemies."""
    run.step(2)
    act().ondas.cancel()
    return run.ns, act().nave


def still(ns, kind, angle, far):
    """An enemy that stays where it is put (its timers and moves cancelled)."""
    enemy = ns[kind](center=ns["no_anel"](angle, far))
    enemy.cancel_process()
    return enemy


def shots_fired(run, ns, nave, frames=SECOND):
    """Shots made in ``frames`` frames of SPACE, from a ready gun."""
    old = list(ns["group"]["tiros"])     # still flying from before
    seen = []                       # the shots themselves: an id() is reused
    nave.recarga = 0
    run.key_down("SPACE")
    for _ in range(frames):
        run.step(1)
        for tiro in ns["group"]["tiros"]:
            if not any(tiro is s for s in seen + old):
                seen.append(tiro)
    run.key_up("SPACE")
    run.step(SECOND)
    return len(seen)


class TestGuardiaoShip(unittest.TestCase):
    def test_the_lights_follow_the_ship_past_360_without_a_jump(self):
        with ProgramRun(PATH) as run:
            ns, nave = quiet(run)
            run.key_down("LEFT")
            biggest = 0.0
            before = (nave.luz_a, nave.luz_b)
            for _ in range(4 * SECOND):
                run.step(1)
                now = (nave.luz_a, nave.luz_b)
                biggest = max(biggest, *(abs(a - b) for a, b in zip(now, before)))
                before = now
            run.key_up("LEFT")
            self.assertGreater(nave.angulo, 360 + 90, "vacuous: the ship did not pass 360")
            self.assertLess(biggest, 5, "a light jumped")
            x, y = float(nave.center.x), float(nave.center.y)
            cx, cy = float(ns["CENTRO"].x), float(ns["CENTRO"].y)
            self.assertAlmostEqual(math.dist((x, y), (cx, cy)), ns["ORBITA"], delta=0.5)
            run.step(2 * SECOND)
            for luz, lado in ((nave.luz_a, 1), (nave.luz_b, -1)):
                self.assertAlmostEqual(luz, nave.angulo + lado * ns["AFASTAMENTO"], delta=0.5)

    def test_shots_need_one_three_and_five_hits(self):
        for kind, hits in (("Seta", 1), ("Mandala", 3), ("Cristal", 5)):
            with self.subTest(kind=kind), ProgramRun(PATH) as run:
                ns, nave = quiet(run)
                enemy = still(ns, kind, 90, 480)
                self.assertEqual(enemy.vida, hits)
                run.key_down("SPACE")
                for _ in range(3 * SECOND):
                    run.step(1)
                    if count(ns, "inimigos") == 0:
                        break
                run.key_up("SPACE")
                self.assertEqual(count(ns, "inimigos"), 0, f"{kind} survived")
                self.assertEqual(ns["st"].pontos, enemy.pontos)

    def test_the_radar_pulls_a_shot_onto_an_enemy_almost_in_front(self):
        hit = {}
        for mira in (0.0, None):
            with ProgramRun(PATH) as run:
                ns, nave = quiet(run)
                if mira is not None:
                    ns["MIRA"] = mira
                enemy = still(ns, "Cristal", 92, 600)     # 2 degrees off the shot
                enemy.radius = 10
                run.key_down("SPACE")
                run.step(12)
                run.key_up("SPACE")
                run.step(SECOND)
                hit[mira] = enemy.vida < 5
        self.assertFalse(hit[0.0], "vacuous: the straight shot hits anyway")
        self.assertTrue(hit[None], "the radar did not pull the shot")


    def test_a_mine_takes_its_neighbours_and_the_next_mine(self):
        with ProgramRun(PATH) as run:
            ns, nave = quiet(run)
            still(ns, "Mina", 90, 330)
            still(ns, "Mina", 104, 360)          # inside the first blast
            still(ns, "Seta", 80, 350)
            still(ns, "Cristal", 100, 450)       # in the blast, out of the aim cone
            far = still(ns, "Mandala", 150, 330)
            run.key_down("SPACE")
            run.step(30)
            run.key_up("SPACE")
            run.step(30)
            self.assertEqual(list(ns["group"]["inimigos"]), [far])
            self.assertEqual(count(ns, "minas"), 0)
            self.assertEqual(ns["st"].pontos, 20 + 20 + 10 + 50)


    def test_a_mine_crosses_in_front_of_the_ring_and_leaves(self):
        with ProgramRun(PATH) as run:
            ns, nave = quiet(run)
            ns["cruzar_mina"](90)
            mina = list(ns["group"]["minas"])[0]
            cx, cy = float(ns["CENTRO"].x), float(ns["CENTRO"].y)
            nearest = 1e9
            for _ in range(25 * SECOND):
                run.step(1)
                if not mina.active:
                    break
                nearest = min(nearest, math.dist((float(mina.center.x),
                                                  float(mina.center.y)), (cx, cy)))
            self.assertFalse(mina.active, "the mine never left")
            self.assertAlmostEqual(nearest, ns["TRAVESSIA"], delta=5)
            self.assertEqual(ns["st"].anel, ns["VIDA_ANEL"])


class TestGuardiaoLives(unittest.TestCase):
    def test_an_enemy_shot_costs_the_ship_and_an_invader_costs_the_ring(self):
        with ProgramRun(PATH) as run:
            ns, nave = quiet(run)
            st = ns["st"]
            ns["Bala"](center=ns["no_anel"](90, 420), angle=-90)
            run.step(2 * SECOND)
            self.assertEqual(st.vida, ns["VIDA_NAVE"] - 1)
            ns["Bala"](center=ns["no_anel"](270, 420), angle=90)   # at the ring
            run.step(3 * SECOND)
            self.assertEqual(count(ns, "balas"), 0)
            self.assertEqual(st.anel, ns["VIDA_ANEL"], "an enemy shot hurt the ring")
            still(ns, "Seta", 270, 420)         # no shot of its own
            run.step(4 * SECOND)
            self.assertEqual(st.anel, ns["VIDA_ANEL"] - 1)

    def test_losing_ends_the_game_and_r_starts_a_fresh_one(self):
        with ProgramRun(PATH) as run:
            ns, nave = quiet(run)
            st = ns["st"]
            for _ in range(ns["VIDA_NAVE"]):
                nave.ferir()
            run.step(2 * SECOND)
            self.assertTrue(act().acabou)
            self.assertFalse(nave.active, "the ship was not destroyed")
            run.key_down("R")
            run.step(1)
            run.key_up("R")
            run.step(5)
            self.assertFalse(act().acabou)
            self.assertEqual((st.vida, st.anel, st.pontos),
                             (ns["VIDA_NAVE"], ns["VIDA_ANEL"], 0))


class TestGuardiaoPowers(unittest.TestCase):
    def test_fast_and_double_shoot_more(self):
        with ProgramRun(PATH) as run:
            ns, nave = quiet(run)
            normal = shots_fired(run, ns, nave)
            nave.ganhar("rapido")
            fast = shots_fired(run, ns, nave)
            nave.poderes["rapido"] = 0
            nave.ganhar("duplo")
            double = shots_fired(run, ns, nave)
            self.assertGreaterEqual(fast, 2 * normal - 1)
            self.assertEqual(double, 3 * normal)
            nave.recarga = 0
            run.key_down("SPACE")
            run.step(1)
            run.key_up("SPACE")
            run.step(1)
            new = sorted(round(t.angle - nave.angulo, 3) for t in ns["group"]["tiros"]
                         if abs(t.angle - nave.angulo) < 20 and t.center.y > 400)
            self.assertEqual(new[:1] + new[-1:], [-ns["ABERTURA"], ns["ABERTURA"]])

    def test_strong_shots_go_through(self):
        with ProgramRun(PATH) as run:
            ns, nave = quiet(run)
            nave.ganhar("forte")
            still(ns, "Seta", 90, 380)
            still(ns, "Seta", 90, 460)
            run.key_down("SPACE")
            run.step(4)
            run.key_up("SPACE")
            run.step(SECOND)
            self.assertEqual(count(ns, "inimigos"), 0, "one shot did not pass through both")

    def test_a_pill_gives_the_shield_and_the_shield_ends(self):
        with ProgramRun(PATH) as run:
            ns, nave = quiet(run)
            st = ns["st"]
            pilula = ns["Pilula"](ns["PILULAS"]["escudo"], center=ns["no_anel"](90, 260))
            pilula.poder = "escudo"
            run.step(3 * SECOND)
            self.assertIsNotNone(nave.escudo, "the pill was not picked up")
            self.assertIn("ESCUDO", act().painel.text)
            ns["Bala"](center=ns["no_anel"](200, 430), angle=20)
            ns["Seta"](center=ns["no_anel"](250, 450))
            run.step(2 * SECOND)
            self.assertEqual((st.vida, st.anel), (ns["VIDA_NAVE"], ns["VIDA_ANEL"]))
            self.assertEqual(count(ns, "inimigos") + count(ns, "balas"), 0)
            run.step(int(ns["DURACAO"] * SECOND))
            self.assertIsNone(nave.escudo, "the shield never ended")
            self.assertEqual(count(ns, "escudo"), 0)
            self.assertEqual(act().painel.text, "")


class TestGuardiaoWaves(unittest.TestCase):
    def test_the_waves_run_to_the_end(self):
        """A pilot that aims at the nearest enemy, on an unhurt ship and ring."""
        with ProgramRun(PATH) as run:
            ns = run.ns
            ns["Nave"].ferir = lambda self: None
            ns["ferir_anel"] = lambda: None
            run.step(2)
            nave = act().nave
            cx, cy = float(ns["CENTRO"].x), float(ns["CENTRO"].y)
            held = set()

            def hold(key, on):
                if on and key not in held:
                    run.key_down(key)
                    held.add(key)
                elif not on and key in held:
                    run.key_up(key)
                    held.discard(key)

            hold("SPACE", True)
            first = None
            for frame in range(150 * SECOND):
                enemies = list(ns["group"]["inimigos"])
                turn = 0
                if enemies:
                    near = min(enemies, key=lambda e: math.dist(
                        (float(e.center.x), float(e.center.y)), (cx, cy)))
                    bearing = math.degrees(math.atan2(float(near.center.y) - cy,
                                                      float(near.center.x) - cx))
                    gap = (bearing - nave.angulo + 180) % 360 - 180
                    turn = 1 if gap > 3 else -1 if gap < -3 else 0
                hold("LEFT", turn > 0)
                hold("RIGHT", turn < 0)
                run.step(1)
                if frame == 4 * SECOND:
                    first = ns["canvas"].rotation
                if act().acabou:
                    break
            hold("SPACE", False)
            hold("LEFT", False)
            hold("RIGHT", False)
            self.assertTrue(act().acabou, "the waves never ended")
            self.assertGreater(ns["st"].anel, 0, "vacuous: the ring fell")
            turns = [onda["lado"] for onda in ns["ONDAS"] if onda.get("virar")]
            self.assertEqual(len(turns), 2, "the table should turn the camera twice")
            self.assertAlmostEqual(first, 0, delta=0.01, msg="the camera turned on wave 1")
            self.assertAlmostEqual(ns["canvas"].rotation, 90 - turns[-1], delta=1,
                                   msg="the camera did not turn to the last marked wave")
            self.assertGreater(ns["st"].pontos, 500)
            run.step(3 * SECOND)
            self.assertEqual(count(ns, "inimigos"), 0)


if __name__ == "__main__":
    unittest.main()
