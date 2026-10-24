"""
The claims of ``examples/corrida.py``, played headless with real key events.

The example says: two cars wait for the countdown; the wheel turns
gradually and a fast turn slides the rear, which lines up again when the wheel
comes back; off the wheel the car lines up with the road (steering wins); a
crashed car blinks while it is out; lit strips follow the outer curves (cars
drive over them); two computer cars finish the laps on the level by themselves, fire at a
car ahead (not a sure shot: a random wait and aim) and back out when stuck;
the result lists all four. A head-on hit bounces the car back, brushing a
wall side on keeps it going, a crashed car lets the others through, and the
faster car throws the one ahead. The game opens on a choice of one or two
players, two buttons to click (or the keys 1 and 2), then a second
screen for the track (side by side, each with a drawing of its layout; the
keys 1 and 2 again); player one drives the
blue car with the arrows and Enter, player two the red one with W A S D and
Tab; the countdown sign has the game's font, a gradient and an outline;
the strips on the outer curves are halos that move (one changes colour,
from a light red to yellow, never a dark red; the next brightens and dims); off the asphalt a car slows to the grass limit; tyres, trees and tents hold a car without crashing it (a tree
only bounces it); a barrel crashes it, and it stands still for one to two seconds
before it drives again; the oil spins it; a power-up box gives one shot
(not two) and comes back after a while; the shot flies straight ahead and
crashes the car it reaches, never the shooter, and goes out on a wall or off
the map; pressed against an obstacle the engine does not push (reverse
gets out); a lap counts through the marks in order, a few missed on a wide
line still count, a cut across the grass does not; the first to finish the laps wins, and Space races again.

Bug classes guarded: **an example that stops doing what its docstring says**
while it still builds and runs, and **an invisible collision band that is
reclaimed**: the road is the track's centre line made thick and hidden
(``visible = False``) with no variable holding it, and hiding a styled Track
used to take it off its layer, so it was collected and every car drove at
grass speed on the asphalt (fixed 2026-10-21, Tracks Design "One class";
engine guard ``test_track.TestHiddenStyledTrackIsKept``).

The two whole races (the computer cars' laps on the level, two drivers to
the result and back) are in ``test_example_corrida_deep`` (gate / deep).

Run:

    python tests/run_tiers.py focused test_example_corrida
"""
from __future__ import annotations

import gc
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
from program_support import run_registry  # noqa: E402
from scena.act import get_act_manager  # noqa: E402

PATH = "examples/corrida.py"
SECOND = 60


def act():
    return get_act_manager().current


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


def click(run, x, y):
    run.move(x, y)
    run.press(x, y)
    run.step(1)
    run.release()
    run.step(1)


def pelo_menu(run, jogadores="2", pista="1"):
    """Through the two opening screens: players, then the track (keys)."""
    tap(run, jogadores)
    tap(run, pista)


def heading(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def xy(p):
    return (float(p[0]), float(p[1])) if isinstance(p, tuple) else (float(p.x), float(p.y))


class Race:
    """One run of the race act, past the countdown, with every car but the
    blue one parked (the red one stays with ``park_red=False``)."""

    def __init__(self, run, *, park_red=True, jogadores="2", pista=None):
        self.run = run
        self.ns = run.ns
        if type(act()).__name__ == "Escolha":
            pelo_menu(run, jogadores, {None: "1", "SERPENTINA": "1", "RELÂMPAGO": "2"}[pista])
        for _ in range(4 * SECOND):
            if self.ns["st"].largou:
                break
            run.step(1)
        assert self.ns["st"].largou, "the countdown never ended"
        self.azul = act().azul
        self.vermelho = act().vermelho
        self.cpus = [c for c in self.ns["group"]["carros"] if c.cpu]
        for carro in self.cpus:
            carro.active = False
        if park_red:
            self.vermelho.active = False

    def place(self, carro, at, angle, speed=0):
        carro.center = at
        carro.angle = angle
        carro.velocidade = speed
        carro.vel = self.ns["vec_from_angle"](angle, speed)
        carro.volante = 0

    def aim(self, carro, alvo, back=3, speed=300):
        """Put the car on the centre line a few marks before the mark nearest
        ``alvo`` and point it at ``alvo``."""
        marcos = act().marcos
        ax, ay = xy(alvo.center)
        near = min(range(len(marcos)), key=lambda i: math.dist(marcos[i], (ax, ay)))
        start = marcos[(near - back) % len(marcos)]
        self.place(carro, start, heading(start, (ax, ay)), speed)

    def hold(self, key, frames):
        self.run.key_down(key)
        self.run.step(frames)
        self.run.key_up(key)
        self.run.step(1)


class TestCorridaDriving(unittest.TestCase):
    def test_the_countdown_holds_the_cars(self):
        with ProgramRun(PATH) as run:
            ns = run.ns
            pelo_menu(run)
            run.step(2)
            azul = act().azul
            start = xy(azul.center)
            run.key_down("UP")
            run.step(2 * SECOND)
            self.assertFalse(ns["st"].largou)
            self.assertEqual(azul.velocidade, 0)
            self.assertEqual(xy(azul.center), start)
            run.step(2 * SECOND)
            run.key_up("UP")
            self.assertTrue(ns["st"].largou)
            self.assertGreater(azul.velocidade, 50)

    def test_the_grass_slows_the_car_and_the_asphalt_does_not(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            ns = r.ns
            # The road band is held by nothing but the canvas: a collection
            # must not take it (when one runs is up to the interpreter).
            gc.collect()
            # Infield grass, heading west, clear of the tent and the tree.
            r.place(r.azul, (520, 440), 180)
            top = 0
            run.key_down("UP")
            for _ in range(SECOND):
                run.step(1)
                top = max(top, r.azul.velocidade)
            run.key_up("UP")
            self.assertGreater(top, ns["NA_GRAMA"] - 5, "vacuous: the car never got going")
            self.assertLessEqual(top, ns["NA_GRAMA"] + 1)
            # The bottom straight, heading west, beside the parked red car.
            r.place(r.azul, (1300, 300), 180)
            r.hold("UP", int(1.6 * SECOND))
            self.assertGreater(r.azul.velocidade, ns["NA_GRAMA"] + 100,
                               "the asphalt slows the car like the grass")
            self.assertEqual(ns["group"]["asfalto"].count, 1)

    def test_the_wheel_turns_gradually_and_the_rear_slides(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            ns = r.ns
            r.place(r.azul, (1300, 264), 180, speed=ns["MAXIMA"])
            run.key_down("UP")
            run.key_down("RIGHT")
            run.step(1)
            first = abs(r.azul.angle - 180)
            self.assertLess(first, ns["GIRO"] / SECOND * 0.3, "the wheel turned all at once")

            def slip():
                return abs((r.azul.angle - r.azul.vel.angle + 540) % 360 - 180)
            most = 0
            for _ in range(SECOND // 2):
                run.step(1)
                most = max(most, slip())
            self.assertGreater(most, 8, "a fast turn does not slide")
            run.key_up("RIGHT")
            run.step(SECOND)
            run.key_up("UP")
            self.assertLess(slip(), 2, "the car never lines up again")

    def test_off_the_wheel_the_car_lines_up_with_the_road(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            # The bottom straight runs west (180): start 12 degrees off.
            r.place(r.azul, (1300, 264), 192, speed=300)
            r.azul.marco = len(act().marcos) - 3
            run.key_down("UP")
            run.step(SECOND)
            run.key_up("UP")
            self.assertLess(abs(r.azul.angle - 180), 2, "the car does not line up on a straight")
            # Steering wins: holding the wheel turns away from the road.
            r.place(r.azul, (1300, 264), 180, speed=300)
            run.key_down("UP")
            run.key_down("RIGHT")
            run.step(SECOND // 2)
            run.key_up("RIGHT")
            run.key_up("UP")
            self.assertGreater(abs(r.azul.angle - 180), 20)

    def test_a_shortcut_across_the_grass_does_not_count(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            marcos = act().marcos
            r.place(r.azul, marcos[20], 0)
            run.step(5)
            self.assertEqual(r.azul.marco, 0)
            # A few marks missed on a wide line still count.
            r.place(r.azul, marcos[4], 180)
            run.step(3)
            self.assertIn(r.azul.marco, (4, 5))
            reached = r.azul.marco
            r.place(r.azul, marcos[12], 180)
            run.step(3)
            self.assertEqual(r.azul.marco, reached)


class TestCorridaObstacles(unittest.TestCase):
    def test_a_barrel_crashes_the_car_for_one_to_two_seconds(self):
        for alvo in ("barril",):
            with self.subTest(alvo=alvo), ProgramRun(PATH) as run:
                r = Race(run)
                coisa = min(r.ns["group"][alvo], key=lambda c: c.center.y)
                r.aim(r.azul, coisa)
                run.key_down("UP")
                hit = None
                for f in range(SECOND):
                    run.step(1)
                    if r.azul.mode == r.azul.batido:
                        hit = f
                        break
                self.assertIsNotNone(hit, f"driving into a {alvo} did not crash")
                self.assertEqual(r.azul.velocidade, 0)
                down = 0
                while r.azul.mode == r.azul.batido and down < 3 * SECOND:
                    self.assertLess(r.azul.velocidade, 1, "a crashed car moves")
                    run.step(1)
                    down += 1
                run.key_up("UP")
                self.assertGreaterEqual(down, SECOND)
                self.assertLessEqual(down, 2 * SECOND)
                self.assertIsNone(r.azul.mode)

    def test_tyres_hold_the_car_without_crashing_it(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            pneu = min(r.ns["group"]["pneu"], key=lambda p: math.dist(xy(p.center), (190, 190)))
            r.aim(r.azul, pneu, back=2)
            run.key_down("UP")
            bounced = False
            for _ in range(SECOND):
                run.step(1)
                self.assertIsNone(r.azul.mode, "a tyre crashed the car")
                bounced = bounced or r.azul.velocidade < 0
            run.key_up("UP")
            self.assertTrue(bounced, "vacuous: the car never reached the tyres")

    def test_a_tree_bounces_the_car_without_crashing_it(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            # The tree between the two top bends: come at it from above, fast.
            arvore = min(r.ns["group"]["arvore"], key=lambda c: math.dist(xy(c.center), (792, 792)))
            r.place(r.azul, (arvore.center.x, 968), -90, speed=300)
            run.key_down("UP")
            bounced = False
            for _ in range(SECOND):
                run.step(1)
                self.assertIsNone(r.azul.mode, "a tree crashed the car")
                bounced = bounced or r.azul.velocidade < 0
            run.key_up("UP")
            self.assertTrue(bounced, "vacuous: the car never reached the tree")

    def test_against_an_obstacle_the_engine_does_not_push_and_reverse_gets_out(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            pneu = min(r.ns["group"]["pneu"], key=lambda p: math.dist(xy(p.center), (190, 190)))
            r.aim(r.azul, pneu, back=2, speed=150)
            run.key_down("UP")
            run.step(SECOND)
            self.assertLessEqual(r.azul.velocidade, 40, "pinned against the tyres at full engine")
            run.key_up("UP")
            where = xy(r.azul.center)
            r.hold("DOWN", SECOND)
            self.assertLess(r.azul.velocidade, -50)
            self.assertGreater(math.dist(xy(r.azul.center), where), 30, "reverse does not get out")

    def test_the_oil_spins_the_car(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            oleo = list(r.ns["group"]["oleo"])[0]
            r.aim(r.azul, oleo)
            spun = False
            for _ in range(SECOND):
                run.step(1)
                spun = spun or r.azul.mode == r.azul.rodando
            self.assertTrue(spun)
            run.step(SECOND)
            self.assertIsNone(r.azul.mode)


class TestCorridaBumps(unittest.TestCase):
    def test_head_on_the_car_bounces_back_off_the_tyres(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            pneu = min(r.ns["group"]["pneu"], key=lambda p: math.dist(xy(p.center), (190, 190)))
            r.aim(r.azul, pneu, back=2, speed=300)
            run.key_down("UP")
            hit = None
            for f in range(SECOND):
                run.step(1)
                if r.azul.velocidade < 0:
                    hit = f
                    break
            run.key_up("UP")
            self.assertIsNotNone(hit, "vacuous: the car never reached the tyres")
            near = math.dist(xy(r.azul.center), xy(pneu.center))
            run.step(SECOND // 2)
            self.assertGreater(math.dist(xy(r.azul.center), xy(pneu.center)), near + 3,
                               "the car stays stuck to the tyres")
            self.assertIsNone(r.azul.mode)

    def test_brushing_a_wall_side_on_keeps_going(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            # The red tent in the infield: drive up along its left side.
            tenda = max((p for p in r.ns["group"]["parede"] if 300 < p.center.y < 700),
                        key=lambda p: p.width)
            caixa = tenda.hitbox.box
            r.place(r.azul, (caixa.left - 11, caixa.bottom + 30), 92, 130)
            run.key_down("UP")
            touched = slowest = None
            for _ in range(SECOND):
                run.step(1)
                if r.azul.touching_sides:
                    touched = True
                    v = r.azul.velocidade
                    slowest = v if slowest is None else min(slowest, v)
            run.key_up("UP")
            self.assertTrue(touched, "vacuous: the car never touched the tent")
            self.assertGreater(slowest, 80, "brushing a wall side on holds the car")
            self.assertGreater(r.azul.center.y, caixa.center.y, "the car did not get past")

    def test_a_crashed_car_lets_the_others_through(self):
        with ProgramRun(PATH) as run:
            r = Race(run, park_red=False)
            r.place(r.azul, (900, 264), 180)
            r.place(r.vermelho, (1100, 264), 180, 300)
            r.azul.bater()
            run.key_down("W")
            run.step(SECOND)
            run.key_up("W")
            self.assertLess(r.vermelho.center.x, r.azul.center.x - 40, "the red car did not pass through")
            self.assertGreater(r.vermelho.velocidade, 250)
            run.step(2 * SECOND)
            self.assertIsNone(r.azul.mode)
            self.assertTrue(r.azul.collidable, "a car back in the race still passes through")

    def test_the_faster_car_throws_the_one_ahead(self):
        with ProgramRun(PATH) as run:
            r = Race(run, park_red=False)
            r.place(r.vermelho, (1000, 264), 180, 150)
            r.place(r.azul, (1100, 264), 180, 380)
            run.key_down("UP")
            for _ in range(SECOND // 2):
                run.step(1)
                if r.vermelho.derrapa > 0:
                    break
            self.assertGreater(r.vermelho.derrapa, 0, "vacuous: no hit")
            run.step(SECOND // 3)
            run.key_up("UP")
            self.assertGreater(r.vermelho.vel.length, 250, "the car ahead was not thrown")
            self.assertGreater(math.dist(xy(r.azul.center), xy(r.vermelho.center)), 55,
                               "the two cars stay stuck together")


class TestCorridaPresentation(unittest.TestCase):
    def test_one_or_two_players_and_the_rest_computer(self):
        for tecla, humanos in (("1", 1), ("2", 2)):
            with self.subTest(jogadores=tecla), ProgramRun(PATH) as run:
                self.assertEqual(type(act()).__name__, "Escolha")
                pelo_menu(run, tecla)
                carros = list(run.ns["group"]["carros"])
                self.assertEqual(len(carros), 4)
                self.assertEqual(sum(1 for c in carros if not c.cpu), humanos)
                self.assertEqual(act().vermelho.cpu, humanos == 1)

    def test_the_choice_is_two_buttons_to_click(self):
        for rotulo, humanos in (("UM JOGADOR", 1), ("DOIS JOGADORES", 2)):
            with self.subTest(botao=rotulo), ProgramRun(PATH) as run:
                botoes = [b for b in gc.get_objects()
                          if isinstance(b, run.ns["SpriteButton"]) and b.is_alive
                          and b.label_text.text in ("UM JOGADOR", "DOIS JOGADORES")]
                self.assertEqual(len(botoes), 2)
                botao = next(b for b in botoes if b.label_text.text == rotulo)
                click(run, botao.center.x, botao.center.y)
                self.assertEqual(type(act()).__name__, "EscolhaPista")
                tap(run, "1")
                self.assertEqual(type(act()).__name__, "Corrida")
                self.assertEqual(sum(1 for c in run.ns["group"]["carros"] if not c.cpu), humanos)

    def test_the_track_is_the_second_screen_two_buttons_side_by_side(self):
        for como in ("click", "key"):
            with self.subTest(como=como), ProgramRun(PATH) as run:
                tap(run, "1")
                self.assertEqual(type(act()).__name__, "EscolhaPista")
                botoes = {b.label_text.text: b for b in gc.get_objects()
                          if isinstance(b, run.ns["SpriteButton"]) and b.is_alive}
                self.assertEqual(set(botoes), {"SERPENTINA", "RELÂMPAGO"}, "the players' buttons stayed")
                serpentina, relampago = botoes["SERPENTINA"], botoes["RELÂMPAGO"]
                self.assertAlmostEqual(serpentina.center.y, relampago.center.y)
                self.assertNotEqual(serpentina.frame, relampago.frame, "both tracks wear the same button")
                # Each button has the drawing of its track above it.
                desenhos = [t for t in gc.get_objects()
                            if isinstance(t, run.ns["Track"]) and t.is_alive and t.layer == "ui"]
                for botao in (serpentina, relampago):
                    self.assertTrue(any(abs(t.center.x - botao.center.x) < 60 and t.center.y > botao.center.y
                                        for t in desenhos), f"no drawing above {botao.label_text.text}")
                if como == "click":
                    click(run, relampago.center.x, relampago.center.y)
                else:
                    tap(run, "2")
                self.assertEqual(type(act()).__name__, "Corrida")
                self.assertEqual(run.ns["st"].pista, "RELÂMPAGO")
                self.assertEqual(tuple(act().vista.center), tuple(run.ns["PISTAS"]["RELÂMPAGO"]["vista"].box.center))
                self.assertEqual(sum(1 for c in run.ns["group"]["carros"] if not c.cpu), 1)

    def test_each_track_has_every_piece_the_race_uses(self):
        """Both level files: the cars start on the asphalt, behind the line
        and facing the way round; the centre line closes on itself; every
        group the race makes is there."""
        for pista in ("SERPENTINA", "RELÂMPAGO"):
            with self.subTest(pista=pista), ProgramRun(PATH) as run:
                r = Race(run, pista=pista)
                ns = r.ns
                marcos = act().marcos
                self.assertGreater(len(marcos), 40)
                self.assertTrue(ns["PISTAS"][pista]["linha"].make().closed, "the centre line does not close")
                for nome in ("chao", "luz", "parede", "pneu", "arvore", "barril", "cone", "oleo", "poderes"):
                    self.assertGreater(ns["group"][nome].count, 0, f"{pista} has no {nome}")
                rumo = r.azul.rumo_da_pista(0)
                for carro in ns["group"]["carros"]:
                    self.assertTrue(ns["collision"].query_point(carro, group="asfalto"),
                                    f"{carro.nome} starts off the asphalt on {pista}")
                    self.assertLess(abs((carro.angle - rumo + 540) % 360 - 180), 1)
                    ahead = (xy(marcos[0])[0] - carro.center.x) * math.cos(math.radians(rumo)) \
                        + (xy(marcos[0])[1] - carro.center.y) * math.sin(math.radians(rumo))
                    self.assertGreater(ahead, 0, f"{carro.nome} starts past the line on {pista}")

    def test_player_one_drives_with_the_arrows_and_player_two_with_wasd(self):
        with ProgramRun(PATH) as run:
            r = Race(run, park_red=False)
            for carro, tecla in ((r.azul, "UP"), (r.vermelho, "W")):
                outro = r.vermelho if carro is r.azul else r.azul
                r.place(carro, (900, 264), 180)
                r.place(outro, (1300, 300), 180)
                run.key_down(tecla)
                run.step(SECOND // 2)
                run.key_up(tecla)
                self.assertGreater(carro.velocidade, 50, f"{tecla} does not drive {carro.nome}")
                self.assertLess(outro.velocidade, 1, f"{tecla} drives {outro.nome} too")
                run.step(2 * SECOND)

    def test_the_countdown_sign_has_the_font_a_gradient_and_an_outline(self):
        with ProgramRun(PATH) as run:
            pelo_menu(run)
            aviso = act().aviso
            self.assertIn("Quantico", aviso.font)
            self.assertEqual(type(aviso.fill).__name__, "Gradient")
            self.assertIsNotNone(aviso.line)

    def test_the_lit_strips_move(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            luzes = list(r.ns["group"]["luz"])
            Halo = r.ns["Halo"]
            halos = [l for l in luzes if isinstance(l.visual, Halo)]
            self.assertEqual(halos, luzes, "every strip is a halo")
            pulsando = act().pulsando
            cores = [h for h in halos if h not in pulsando]
            self.assertTrue(pulsando and cores, "one halo changes colour, the other intensity")
            seen_colors = {id(h): set() for h in cores}
            seen_amounts = {id(h): set() for h in pulsando}
            for _ in range(SECOND):
                run.step(1)
                for h in cores:
                    seen_colors[id(h)].add(str(h.color))
                for h in pulsando:
                    seen_amounts[id(h)].add(h.visual.amount)
            for h in cores:
                self.assertGreater(len(seen_colors[id(h)]), 3, "a colour halo does not change colour")
            # The colour never goes as far as a dark red: its brightest
            # channel stays high all the way.
            for _ in range(2 * SECOND):
                run.step(1)
                red, green, _blue = r.ns["st"].cor_luz.rgb[:3]
                self.assertGreater(red, 0.95)
                self.assertGreater(green, 0.35, "the colour strip reaches a dark red")
            for h in pulsando:
                self.assertGreater(len(seen_amounts[id(h)]), 3, "an intensity halo does not pulse")


class TestCorridaShot(unittest.TestCase):
    def test_a_power_up_gives_one_shot_and_comes_back(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            poderes = r.ns["group"]["poderes"]
            n = poderes.count
            box = list(poderes)[0]
            lugar = xy(box.center)
            r.place(r.azul, lugar, 0)
            run.step(2)
            self.assertEqual(r.azul.tiros, 1)
            self.assertTrue(r.azul.glow)
            self.assertEqual(poderes.count, n - 1)
            # A second box while holding a shot: still one shot, the box stays.
            other = list(poderes)[0]
            r.place(r.azul, xy(other.center), 0)
            run.step(2)
            self.assertEqual(r.azul.tiros, 1)
            self.assertEqual(poderes.count, n - 1)
            r.place(r.azul, (520, 440), 180, speed=0)
            run.step(5 * SECOND)
            self.assertEqual(poderes.count, n)
            self.assertTrue(any(math.dist(xy(p.center), lugar) < 1 for p in poderes))

    def test_the_shot_crashes_the_car_ahead_and_not_the_shooter(self):
        with ProgramRun(PATH) as run:
            r = Race(run, park_red=False)
            ns = r.ns
            r.place(r.azul, (800, 264), 180)
            r.place(r.vermelho, (1150, 264), 180)
            r.vermelho.tiros = 1
            tap(run, "TAB")
            tap(run, "TAB")
            self.assertEqual(r.vermelho.tiros, 0)
            self.assertLessEqual(ns["group"]["tiros"].count, 1, "one shot fired twice")
            crashed = False
            for _ in range(SECOND):
                run.step(1)
                crashed = crashed or r.azul.mode == r.azul.batido
                self.assertNotEqual(r.vermelho.mode, r.vermelho.batido, "the shot hit its shooter")
            self.assertTrue(crashed, "the shot missed the car ahead")
            self.assertEqual(ns["group"]["tiros"].count, 0)

    def test_a_car_hit_by_a_shot_smokes_while_it_is_out(self):
        with ProgramRun(PATH) as run:
            r = Race(run, park_red=False)
            Fumaca = r.ns["Fumaca"]
            r.place(r.azul, (800, 264), 180)
            r.place(r.vermelho, (1150, 264), 180)
            r.vermelho.tiros = 1
            tap(run, r.vermelho.teclas["tiro"])
            for _ in range(SECOND):
                run.step(1)
                if r.azul.mode == r.azul.batido:
                    break
            self.assertEqual(r.azul.mode, r.azul.batido, "vacuous: no hit")
            run.step(2)
            nuvens = [o for o in run_registry().live_objects() if isinstance(o, Fumaca) and o.is_alive]
            self.assertEqual(len(nuvens), 1, "no black smoke on the hit car")
            nuvem = nuvens[0]
            # The smoke pack's images are 25 different puffs, not the frames
            # of one animation: cycling them made the smoke jitter. One puff
            # for the whole life.
            frame = nuvem.frame
            r.azul.center = (760, 264)          # the smoke follows the car
            run.step(1)
            self.assertAlmostEqual(nuvem.center.x, 760, delta=1)
            run.step(SECOND // 2)
            self.assertEqual(nuvem.frame, frame, "the smoke changed puff mid-life")
            run.step(int(1.1 * SECOND))
            self.assertFalse(nuvem.is_alive, "the smoke outlived the crash")

    def test_the_shot_goes_out_on_a_wall_and_off_the_map(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            tiros = r.ns["group"]["tiros"]
            for at, angle in [((528, 264), -90), ((1180, 792), 90)]:
                r.place(r.azul, at, angle)
                r.azul.tiros = 1
                tap(run, "ENTER")
                self.assertEqual(tiros.count, 1)
                run.step(SECOND)
                self.assertEqual(tiros.count, 0, f"a shot from {at} lived on")
                self.assertIsNone(r.azul.mode)


class TestCorridaCrashBlinks(unittest.TestCase):
    def test_a_crashed_car_blinks_while_it_is_out(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            r.azul.bater()
            run.step(1)
            out = 0
            while r.azul.mode == r.azul.batido:
                self.assertIsNotNone(r.azul._tx_state.flash, "a crashed car stopped blinking")
                run.step(1)
                out += 1
            self.assertGreater(out, SECOND)
            run.step(5)
            self.assertIsNone(r.azul._tx_state.flash, "it still blinks back in the race")


class TestCorridaLuzes(unittest.TestCase):
    def test_lit_strips_follow_the_outer_curves_and_cars_drive_over_them(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            luzes = list(r.ns["group"]["luz"])
            self.assertGreater(len(luzes), 0)
            for luz in luzes:
                self.assertTrue(luz.visible)
                self.assertIsNotNone(luz.visual)
            # Decoration only: a car crosses one at speed. (A solid strip
            # trapped a computer car that slid behind it, off the road.)
            luz = min(luzes, key=lambda m: math.dist(xy(m.at(0.08)), (300, 300)))
            meio = xy(luz.at(0.08))   # near an end, clear of the tyre stack
            estrada = min(act().marcos, key=lambda m: math.dist(m, meio))
            r.place(r.azul, meio, heading(meio, estrada), 250)
            run.step(SECOND // 3)
            self.assertGreater(math.dist(xy(r.azul.center), meio), 60, "the car stopped at the strip")
            self.assertGreater(r.azul.velocidade, 100)
            self.assertIsNone(r.azul.mode)


class TestCorridaCpu(unittest.TestCase):
    def test_a_computer_car_fires_at_a_car_ahead(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            cpu = r.cpus[0]
            cpu.active = True
            cpu.tiros = 1
            # Not a sure shot: it fires after a random wait (half a second on
            # average) and its aim is off by up to 8 degrees. Each try puts the
            # target back ahead (the computer car pushes it out of its sight).
            tiro = None
            for _ in range(8):
                r.place(r.azul, (800, 264), 180)
                r.place(cpu, (1150, 264), 180)
                cpu.marco = len(act().marcos) - 4
                for _ in range(SECOND):
                    run.step(1)
                    if r.ns["group"]["tiros"].count:
                        tiro = list(r.ns["group"]["tiros"])[0]
                        break
                if tiro is not None:
                    break
            self.assertIsNotNone(tiro, "the computer never fired")
            self.assertEqual(cpu.tiros, 0)
            erro = abs((tiro.angle - cpu.angle + 540) % 360 - 180)
            self.assertGreater(erro, 0, "the computer aims dead on")
            self.assertLessEqual(erro, 8.5)

    def test_a_stuck_computer_car_backs_out(self):
        with ProgramRun(PATH) as run:
            r = Race(run)
            r.azul.active = False
            cpu = r.cpus[0]
            cpu.active = True
            pneu = min(r.ns["group"]["pneu"], key=lambda p: math.dist(xy(p.center), (190, 190)))
            # Nose against the tyres, the road behind it.
            cpu.marco = 4
            r.place(cpu, (pneu.center.x + 30, pneu.center.y + 30),
                    heading((pneu.center.x + 30, pneu.center.y + 30), xy(pneu.center)))
            backed = False
            for _ in range(4 * SECOND):
                run.step(1)
                backed = backed or cpu.velocidade < -30
            self.assertTrue(backed, "a stuck computer car never reversed")
            self.assertGreater(math.dist(xy(cpu.center), xy(pneu.center)), 80, "still at the tyres")


if __name__ == "__main__":
    unittest.main()
