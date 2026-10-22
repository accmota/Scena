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
* **The moving platform** (tutorial 27, "O elevador"): the ninja rides the
  elevator up and down with its feet on it every frame, and reaches the star
  only the elevator gets to. A fall into the water on the last life sinks
  instead of sending the ninja back to the start.
* **Mouse input no step run gives** (tutorial 11, Script 3; tutorial 22):
  the canvas callbacks (a click lights a star, a drag is not a click, the
  wheel sets the size, a double click clears the stars its own clicks lit)
  and a key's ``on_click`` with the equalizer rising under the note;
  the ship of tutorial 12 changes destination mid-trip without the
  replace warning, stops on Space and follows the mouse; the collision
  lab of tutorial 20 (the pool's enter / stay / exit, the guard's ray
  hidden by a crate, a right click that only blasts crates).
* **A gauge that freezes** (tutorial 10, "O velocímetro"): the speed bar's
  width and color are ``@=`` formulas on the chosen ball's ``vel``, which
  only ``resolve`` changes (a ball-ball hit). Each frame the bar agrees with
  the speed, and the speed does change, so the check is not vacuous.
* **A hitbox switched by the animation** (tutorial 28, Ninja V): the sword's
  part is on only in the cut's frames, so a crate the ninja leans on does
  not break until Space; the crate leaves a light; the light makes the ninja
  invincible for 6 s, the Aura blinks in the last 2 and goes; a shock just
  before the light does not take the Aura away when its 2.5 s end.
* **A pause that only looks paused** (tutorial 25, "Pausa"): with
  ``clock.paused`` the fleet and the shots stop, but ``on_update`` still runs,
  so Space must not fire into the frozen screen; R during the pause starts
  the next act unpaused.
* **Two players no step run moves** (tutorial 31, Duelo): the choice act
  hands the chosen ship to the duel; a ship rides its rail (always on the
  curve, stopping at the ends, coasting after the key); a laser bounces three
  times and goes on the fourth; a big asteroid splits in two and a small one
  breaks; the shield takes three blows (laser or asteroid) and then the ship
  takes damage; a broken star sends its power-up to the shooter; a ship out
  of energy ends the duel, and Space goes back to the choice.

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

NINJAS = ("examples/ninja_2_mundo.py", "examples/ninja_3_nivel.py", "examples/ninja_4_perigos.py",
          "examples/ninja_5_espada.py")


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
    PATH = "examples/ninja_4_perigos.py"

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


class TestNinjaEspada(unittest.TestCase):
    PATH = "examples/ninja_5_espada.py"

    def _at_the_first_crate(self, run):
        ns = run.ns
        heroi = list(ns["group"]["heroi"])[0]
        caixa = ns["group"]["caixa"].nearest((230, 105))
        heroi.center = (caixa.center.x - 60, 80.08)
        heroi.vel.y = 0
        run.key_down("RIGHT")
        run.step(20)                       # walks into it and stops there
        run.key_up("RIGHT")
        run.step(5)
        return heroi, caixa

    def test_only_the_cut_breaks_a_crate(self):
        with ProgramRun(self.PATH) as run:
            run.step(3)
            ns = run.ns
            heroi, caixa = self._at_the_first_crate(run)
            espada = heroi.hitboxes[-1]
            run.step(60)
            self.assertTrue(caixa, "the crate broke with no swing")
            run.key_down("SPACE")
            on = []
            for _ in range(30):            # the clip: 10 cells at 20 fps
                run.step(1)
                on.append((espada.active, heroi.showing(ns["GOLPE"])))
            run.key_up("SPACE")
            self.assertTrue(any(a for a, _ in on), "the sword's box never came on")
            self.assertTrue(all(a == g for a, g in on), f"box on outside the cut: {on}")
            self.assertFalse(caixa, "the cut did not break the crate")
            self.assertEqual(len(list(ns["group"]["luz"])), 1)

    def test_the_light_gives_six_seconds_and_blinks_at_the_end(self):
        with ProgramRun(self.PATH) as run:
            run.step(3)
            ns = run.ns
            heroi = list(ns["group"]["heroi"])[0]
            heroi.pegou_luz(ns["Orb"](center=(0, 0), radius=5))
            run.step(2)
            self.assertTrue(heroi.invencivel)
            vidas = ns["st"].vidas
            heroi.perder()
            self.assertEqual(ns["st"].vidas, vidas, "a hit while invincible")
            looks = []
            for _ in range(int(6.2 * 60)):
                run.step(1)
                looks.append(type(heroi.visual).__name__ if heroi.visual else None)
            first_off = looks.index(None)
            self.assertGreater(first_off, int(3.9 * 60), "the Aura went out before the warning")
            self.assertIn("Aura", looks[first_off:], "no blink: the Aura went out for good")
            self.assertIsNone(heroi.visual)
            self.assertFalse(heroi.invencivel)
            heroi.perder()
            self.assertEqual(ns["st"].vidas, vidas - 1)

    def test_a_shock_then_the_light_keeps_the_aura(self):
        with ProgramRun(self.PATH) as run:
            run.step(3)
            ns = run.ns
            heroi = list(ns["group"]["heroi"])[0]
            ns["choque"](None, heroi, None)
            run.step(10)
            heroi.pegou_luz(ns["Orb"](center=(0, 0), radius=5))
            run.step(int(3 * 60))          # past the shock's 2.5 s
            self.assertEqual(type(heroi.visual).__name__, "Aura")
            self.assertIsNone(heroi.glow, "the shock's glow stayed on")


class TestDueloRules(unittest.TestCase):
    """Tutorial 31: the rules two players reach, played on purpose."""

    PATH = "examples/duelo.py"

    def _start(self, run, tipo_azul=None):
        if tipo_azul == 2:
            self._tap(run, "D")
        self._tap(run, "TAB")
        self._tap(run, "ENTER")
        run.step(2)
        ns = run.ns
        naves = list(ns["group"]["naves"])
        self.assertEqual(len(naves), 2, "the choice did not start the duel")
        azul = [n for n in naves if n.teclas["tiro"] == "TAB"][0]
        vermelha = [n for n in naves if n.teclas["tiro"] == "ENTER"][0]
        for a in list(ns["group"]["asteroides"]):
            a.destroy()
        ns["PUXAO"] = 0                 # lasers fly straight in these checks
        return ns, azul, vermelha

    def _tap(self, run, name):
        run.key_down(name)
        run.step(1)
        run.key_up(name)
        run.step(1)

    def _laser(self, ns, at, vel, dono):
        tiro = ns["Tiro"](frame="laserBlue01.png", center=at)
        tiro.vel = ns["Vec2"](*vel)
        tiro.dono = dono
        return tiro

    def test_the_choice_picks_the_drawing(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns, azul, vermelha = self._start(run, tipo_azul=2)
            folha = ns["folha"]
            self.assertEqual(azul.frame, folha.frame_index("playerShip2_blue.png"))
            self.assertEqual(vermelha.frame, folha.frame_index("playerShip1_red.png"))

    def test_the_ship_rides_its_rail(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns, azul, _ = self._start(run)
            start = azul.u
            run.key_down("W")
            for _ in range(40):
                run.step(1)
                self.assertLess(ns["distance"](azul, azul.trilho.at(azul.u)), 0.5, "off the rail")
            run.key_up("W")
            run.step(2)
            moving = azul.u
            self.assertGreater(moving, start)
            run.step(10)
            self.assertGreater(azul.u, moving, "no coasting after the key")
            run.key_down("W")
            run.step(240)                  # far more than the rail
            self.assertEqual(azul.u, 1)
            self.assertEqual(azul.passo, 0)
            run.key_up("W")

    def test_a_laser_bounces_three_times(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns, azul, _ = self._start(run)
            tiro = self._laser(ns, (560, 400), (0, 700), azul)
            seen = 0
            for _ in range(60 * 6):
                run.step(1)
                if not tiro:
                    break
                seen = tiro.batidas
            self.assertFalse(tiro, "the laser outlived its fourth hit")
            self.assertEqual(seen, 3)

    def test_an_asteroid_splits_then_breaks(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns, azul, _ = self._start(run)
            grande = ns["Asteroide"](center=(560, 460))
            grande.vel = ns["Vec2"](0, 0)
            self._laser(ns, (560, 360), (0, 700), azul)
            run.step(20)
            pedacos = list(ns["group"]["asteroides"])
            self.assertFalse(grande)
            self.assertEqual(len(pedacos), 2)
            self.assertEqual({p.height for p in pedacos}, {30})
            alvo = pedacos[0]
            alvo.vel = ns["Vec2"](0, 0)
            self._laser(ns, (alvo.center.x, alvo.center.y - 80), (0, 700), azul)
            run.step(20)
            self.assertFalse(alvo, "the small one did not break")
            self.assertEqual(len(ns["group"]["asteroides"]), 1)

    def test_the_shield_takes_three_blows(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns, azul, vermelha = self._start(run)
            azul.escudo.cargas = 3
            azul.escudo.active = True
            y = azul.center.y
            for left in (2, 1):
                self._laser(ns, (250, y), (-700, 0), vermelha)
                run.step(20)
                self.assertEqual(azul.escudo.cargas, left)
            pedra = ns["Asteroide"](frame="meteorBrown_small1.png", height=30, center=(240, y))
            pedra.vel = ns["Vec2"](-200, 0)
            run.step(40)
            self.assertFalse(pedra, "the shield did not break the asteroid")
            self.assertFalse(azul.escudo.active)
            self.assertEqual(azul.energia, 100)
            self._laser(ns, (250, y), (-700, 0), vermelha)
            run.step(20)
            self.assertEqual(azul.energia, 90)

    def test_a_broken_star_sends_the_power_up_to_the_shooter(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns, azul, vermelha = self._start(run)
            azul.energia = 50
            estrela = ns["Alvo"](center=(250, 600))
            self._laser(ns, (250, 520), (0, 700), azul)
            run.step(20)
            self.assertFalse(estrela)
            self.assertEqual(len(ns["group"]["poderes"]), 1)
            for _ in range(60 * 6):
                run.step(1)
                if not ns["group"]["poderes"]:
                    break
            self.assertTrue(azul.energia == 90 or azul.escudo.active, "the shooter never got it")

    def test_out_of_energy_ends_the_duel(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns, azul, vermelha = self._start(run)
            # inside a frame, as a hit would: a timer of the duel act
            ns["after"](0.01, lambda: setattr(vermelha, "energia", 0))
            run.step(5)
            self.assertFalse(vermelha)
            self.assertEqual(ns["st"].vencedor, "AZUL")
            run.step(100)
            self.assertEqual(len(ns["group"]["naves"]), 1)
            run.step(100)                   # 3 s after the blast: the victory act
            self.assertEqual(len(ns["group"]["naves"]), 0)
            self._tap(run, "SPACE")
            run.step(2)
            self.assertEqual(len(ns["group"]["naves"]), 0)
            self._tap(run, "TAB")
            self._tap(run, "ENTER")
            run.step(2)
            self.assertEqual(len(ns["group"]["naves"]), 2, "the choice did not come back")


if __name__ == "__main__":
    unittest.main()


class TestNavesPause(unittest.TestCase):
    """Tutorial 25, "Pausa": P stops the battle and P goes on.

    The pause is ``clock.paused``: ``dt`` is 0, so the fleet, the shots, the
    timers and the ``await wait`` stop. The ``on_update`` hooks still run, so
    the hero's own ``if clock.paused: return`` is what keeps Space from firing
    into a frozen screen. R during the pause starts a fresh act, not paused.
    """

    PATH = "examples/naves_6_atos.py"

    def _tap(self, run, name):
        run.key_down(name)
        run.step(1)
        run.key_up(name)
        run.step(1)

    def _shots(self, ns):
        return len(list(ns["group"]["tiros"]))

    def test_p_freezes_the_battle_and_p_resumes_it(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns = run.ns
            ns["comecar"]()
            run.step(240)                   # the fleet has arrived
            inimigo = list(ns["group"]["inimigos"])[0]
            self._tap(run, "P")
            self.assertTrue(ns["clock"].paused)
            run.step(2)
            antes = tuple(inimigo.center)
            tiros = self._shots(ns)
            run.key_down("SPACE")
            run.step(60)
            run.key_up("SPACE")
            run.step(1)
            self.assertEqual(tuple(inimigo.center), antes, "an enemy moved during the pause")
            self.assertEqual(self._shots(ns), tiros, "Space fired during the pause")
            self._tap(run, "P")
            self.assertFalse(ns["clock"].paused)
            run.step(30)
            self.assertNotEqual(tuple(inimigo.center), antes, "the fleet did not go on after P")

    def test_r_during_the_pause_starts_unpaused(self):
        with ProgramRun(self.PATH) as run:
            run.step(2)
            ns = run.ns
            ns["comecar"]()
            run.step(60)
            self._tap(run, "P")
            self.assertTrue(ns["clock"].paused)
            self._tap(run, "R")
            run.step(2)
            self.assertFalse(ns["clock"].paused, "the new act started paused")
            self.assertEqual(len(list(ns["group"]["heroi"])), 1)


class TestCeuEstreladoMouseOnTheCanvas(unittest.TestCase):
    """Tutorial 11, Script 3: the canvas callbacks do what the steps say.

    A click lights a star where it landed; the wheel sets the next star's
    size; a drag leaves dust and no star (a drag is not a click); a double
    click clears the sky, including the two stars its own clicks lit.
    """

    def stars(self, run):
        return [s for s in run.ns["group"]["estrelas"] if s.radius >= 6]

    def test_click_scroll_drag_and_double_click(self):
        from program_support import click, drag, scroll, wait
        with ProgramRun("examples/ceu_estrelado.py") as run:
            run.step(2)
            run.play([click(300, 300), wait(2)])
            self.assertEqual([(s.center.x, s.center.y, s.radius) for s in self.stars(run)],
                             [(300, 300, 6)])
            run.play([scroll(3), click(600, 400), wait(2)])
            self.assertEqual(run.ns["st"].raio, 9)
            self.assertEqual(sorted(s.radius for s in self.stars(run)), [6, 9])
            before = run.ns["group"]["estrelas"].count
            run.play([drag(100, 100, 400, 150, frames=6), wait(2)])
            self.assertEqual(len(self.stars(run)), 2, "a drag lit a star")
            self.assertGreater(run.ns["group"]["estrelas"].count, before, "no dust")
            run.play([click(800, 200), click(800, 200), wait(2)])
            self.assertTrue(run.ns["group"]["estrelas"].empty)


class TestPianoClickAndEqualizer(unittest.TestCase):
    """Tutorial 22: a click on a key plays it (``on_click`` in the class), and
    the equalizer's bars rise with the note."""

    def test_a_clicked_key_lights_and_the_bars_rise(self):
        from program_support import click, wait
        from scena import Color
        with ProgramRun("examples/piano.py") as run:
            run.step(2)
            run.play([click(94, 190), wait(6)])
            teclas = list(run.ns["group"]["teclas"])
            gold = Color("gold").rgb
            self.assertEqual([t.letra for t in teclas if t.color.rgb == gold], ["A"])
            self.assertGreater(max(b.height for b in run.ns["barras"]), 20)


class TestMovimentoTripControl(unittest.TestCase):
    """Tutorial 12: a click mid-trip changes the destination without the
    replace warning (``parar()`` cancels the old trip first), Space stops
    the ship where it is, and the right button makes it follow the mouse."""

    def test_retarget_stop_and_follow(self):
        import warnings
        from program_support import click, wait
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun("examples/movimento.py") as run:
                run.step(2)
                nave = run.ns["nave"]
                run.play([click(800, 600), wait(20), click(200, 100), wait(200)])
                self.assertEqual((round(nave.center.x), round(nave.center.y)), (200, 100))
                self.assertFalse(run.ns["alvo"].visible, "the target stays after landing")
                run.play([click(800, 100), wait(10)])
                run.key_down("SPACE"); run.step(1); run.key_up("SPACE"); run.step(30)
                self.assertIsNone(nave.viagem)
                self.assertLess(nave.center.x, 400, "Space did not stop the trip")
                run.move(100, 650); run.press(100, 650, "right"); run.step(150)
                run.release("right"); run.step(2)
                self.assertEqual((round(nave.center.x), round(nave.center.y)), (100, 650))
        replaced = [w for w in caught if "replaces a previous" in str(w.message)]
        self.assertEqual(replaced, [])


class TestColisaoLab(unittest.TestCase):
    """Tutorial 20: the three phases of a touch, and the queries.

    In the pool the hero slows and loses air every frame (stay); out of it
    the speed comes back (exit). A crate between the guard and the hero
    hides the hero (the ray stops on the crate); a right click destroys only
    the crates near it (``query_circle`` with ``group=``)."""

    def test_pool_guard_and_blast(self):
        from program_support import click, wait
        with ProgramRun("examples/colisao.py") as run:
            run.step(2)
            ns = run.ns
            heroi, visao = ns["heroi"], ns["visao"]
            self.assertEqual(visao.color.rgb[:3], (1, 0, 0), "the guard sees the hero at the start")
            heroi.center = (250, 200)
            run.step(30)
            self.assertEqual(heroi.velocidade, 110)
            self.assertLess(ns["st"].ar, 95)
            heroi.center = (450, 420)
            run.step(3)
            self.assertEqual(heroi.velocidade, 260)
            self.assertEqual(visao.color.rgb[:3], (0.5, 0.5, 0.5), "a crate hides the hero")
            run.play([click(600, 420, "right"), wait(2)])
            self.assertEqual(ns["group"]["caixa"].count, 3)
            self.assertIn(heroi, list(ns["group"]["heroi"]), "the blast took the hero")


class TestBolasSpeedBar(unittest.TestCase):
    """Tutorial 10: the bar follows the golden ball's speed after every hit."""

    def test_width_and_color_follow_the_speed(self):
        with ProgramRun("examples/bolas.py") as run:
            ns = run.ns
            escolhida, barra, rampa = ns["escolhida"], ns["barra"], ns["rampa"]
            speeds = set()
            for _ in range(60 * 20):
                run.step(1)
                v = escolhida.vel.length
                speeds.add(round(v))
                self.assertAlmostEqual(barra.width, 300 * min(v / 500, 1), places=6)
                self.assertEqual(barra.color.rgb, rampa.get_color(v / 500).rgb)
            self.assertGreater(len(speeds), 3, "no ball-ball hit changed the speed")
