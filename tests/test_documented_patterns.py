"""The patterns the Guia teaches, run in real frames: no SCENA warning, the result it promises.

Class of bugs (Testing Design, "What the game system tests taught"): a
pattern the Guia shows breaks when used the way a game uses it, while each
unit test used the feature in the shape that worked. The game system tests
met them one at a time; this module keeps each pattern as its own small
program, run through the frame body with every warning recorded:

* a director that awaits a long wave, then fades out and changes act (AC7);
* a ground flag that reads its owner, through resolve, then a destroy (AC11);
* a formula group declared next to a near name (AC9);
* a named tween refreshed while it runs (AC13);
* formulas built in a loop with the default-argument idiom (AC8);
* ``on_collide`` written as a method (AC6);
* class keywords on a spatial effect (AC2);
* a HUD that keeps reading a field its owner unlinks (AC12);
* a soundtrack in the act's own slot (AC5);
* a weak point: a Collider piece that is also a body (AC10).

A new Guia pattern that sits next to a warning gets a test here (and a row
in ``test_warning_contracts.CONTRACTS`` naming it).

    python tests/run_tiers.py focused test_documented_patterns
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import (  # noqa: E402
    Act, Attribute, Circle, Collider, Orb, Rect, canvas, change_act, collide, collision, group,
    on_mode, play_sound, resolve, st, tween, until_empty, wait,
)
from system_support import SystemTestCase, tone  # noqa: E402


class Vazio(Act):
    pass


def scena_warnings(caught):
    return [str(w.message) for w in caught
            if issubclass(w.category, Warning) and "scena" in (w.filename or "").replace("\\", "/")
            or "SCENA" in str(w.message)]


class PatternCase(SystemTestCase, unittest.TestCase):
    world_draw = False

    def run_quietly(self, body):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = body()
        self.assertEqual(scena_warnings(caught), [], "a documented pattern warned")
        return result


class TestDirectorWave(PatternCase):
    """Guia, modos: a director awaits the wave (``until_empty``), then fades out
    and changes act in ``on_done``. A wave longer than FROZEN_MODE_S (AC7)."""

    def test_long_wave_then_fade_then_change(self):
        seen = {}

        class Fase(Act):
            def setup(self):
                for i in range(3):
                    Circle(center=(40 * i, 50), radius=5, group="dp_onda")
                self.mode = self.dirigindo

            @on_mode
            async def dirigindo(self):
                await until_empty("dp_onda")
                seen["onda"] = True
                canvas.fade_out(0.3, on_done=lambda: change_act(Vazio))

        def play():
            self.w.begin_game(Fase)
            self.w.seconds(3.0)                       # the wave lasts past FROZEN_MODE_S
            for c in list(group["dp_onda"]):
                c.destroy()
            self.w.seconds(1.5)
        self.run_quietly(play)
        self.assertTrue(seen.get("onda"))


class TestGroundFlag(PatternCase):
    """Guia, plataforma: ``hero["grounded"] @= lambda: "bottom" in hero.touching_sides``
    under ``resolve``; the hero dies later (AC11)."""

    def test_flag_follows_the_floor_and_dies_quietly(self):
        def play():
            chao = self.track(Rect(center=(200, 20), width=400, height=40, group="dp_chao"))
            heroi = self.track(Rect(center=(200, 60), width=20, height=40, group="dp_heroi"))
            heroi.vel = (0, -200)
            resolve("dp_heroi", "dp_chao")
            heroi["grounded"] @= lambda: "bottom" in heroi.touching_sides
            for _ in range(20):
                heroi.move_by(0, -6)
                self.w.step(1)
            grounded = heroi.grounded
            heroi.destroy()
            self.w.step(1)
            chao.destroy()
            return grounded
        self.assertTrue(self.run_quietly(play))


class TestFormulaGroup(PatternCase):
    """Guia, grupos-fórmula: ``group["coluna0"] @= lambda: ...`` next to a group
    with a near name (AC9)."""

    def test_declaring_next_to_a_near_name(self):
        def play():
            for i in range(3):
                self.track(Circle(center=(10 * i, 0), radius=2, group="col0"))
            group["coluna0"] @= lambda: [c for c in group["col0"] if c.center.x < 15]
            self.w.step(1)
            return len(group["coluna0"])
        self.assertEqual(self.run_quietly(play), 2)


class TestNamedTween(PatternCase):
    """Guia, tween ``name=``: a power-up refreshed while it runs (AC13)."""

    def test_refresh_replaces(self):
        def play():
            st.dp_escudo = 1.0
            first = tween(st["dp_escudo"], 0.0, time=3.0, name="dp_escudo")
            self.w.seconds(1.0)
            st.dp_escudo = 1.0
            tween(st["dp_escudo"], 0.0, time=3.0, name="dp_escudo")
            self.w.seconds(1.0)
            return first
        first = self.run_quietly(play)
        self.assertTrue(first.cancelled)
        self.assertGreater(float(st.dp_escudo), 0.5)


class TestLoopFormulas(PatternCase):
    """Guia, fórmulas: ``for g in gens: g["saida"] @= (lambda g=g: g.ganho * 2)`` (AC8)."""

    def test_each_reads_its_own(self):
        def play():
            gens = [self.track(Circle(radius=3)) for _ in range(3)]
            for i, g in enumerate(gens):
                g.ganho = float(i)
                g["saida"] @= (lambda g=g: g.ganho * 2)
            gens[2].ganho = 10.0
            self.w.step(1)
            return [g.saida for g in gens]
        self.assertEqual(self.run_quietly(play), [0.0, 2.0, 20.0])


class TestCollideMethod(PatternCase):
    """Guia, colisão: ``def on_collide(self, other, info)`` in a class (AC6)."""

    def test_method_sees_the_other(self):
        seen = []

        class Nave(Circle, radius=8, group="dp_nave"):
            def on_collide(self, other, info):
                seen.append((self, other, info.a))

        def play():
            n = self.track(Nave(center=(100, 100)))
            w = self.track(Rect(center=(104, 100), width=10, height=10))
            w.collidable = True
            self.w.step(1)
            return n, w
        n, w = self.run_quietly(play)
        self.assertTrue(seen)
        self.assertEqual(seen[0], (n, w, n))


class TestSpatialFxClass(PatternCase):
    """Guia, subclasse: ``class Energia(Orb, radius=16, color="gold", group=...)`` (AC2)."""

    def test_class_keywords(self):
        def play():
            class Energia(Orb, radius=16, color="gold", group="dp_energia"):
                pass
            e = self.track(Energia(center=(50, 50)))
            self.w.step(1)
            return e
        e = self.run_quietly(play)
        self.assertEqual(e.radius, 16.0)
        self.assertTrue(e.tagged("dp_energia"))


class TestHudOverAnUnlinkedField(PatternCase):
    """Guia, reativo: a HUD reads ``heroi.hp``; the hero's own link on ``hp`` is
    dropped (``heroi["hp"].unlink()``): the HUD keeps reading it (AC12)."""

    def test_reader_stays_linked(self):
        def play():
            base = Attribute(3.0)
            heroi = self.track(Circle(radius=4))
            heroi.hp = 0.0
            heroi["hp"] @= lambda: base.value
            hud = Attribute(0.0)
            hud @= lambda: heroi.hp * 10
            self.w.step(1)
            heroi["hp"].unlink()
            heroi.hp = 1.0
            self.w.step(1)
            return hud.value
        self.assertEqual(self.run_quietly(play), 10.0)


class TestSoundtrack(PatternCase):
    """Guia, play_sound: an act's soundtrack in the act's own slot, changed in
    its mode, is one voice (AC5)."""

    def test_one_voice(self):
        made = {}

        class Fase(Act):
            def setup(self):
                made["a"] = self.play_sound(tone(2.0), name="musica", loops="forever")
                self.mode = self.jogando

            @on_mode
            async def jogando(self):
                await wait(0.2)
                made["b"] = play_sound(tone(2.0), name="musica", loops="forever", crossfade=0.1)

        def play():
            self.w.begin_game(Fase)
            self.w.seconds(0.6)
            change_act(Vazio)
            self.w.step(1)
        self.run_quietly(play)
        self.assertTrue(made["a"].cancelled or made["a"].done)



class TestWeakPoint(PatternCase):
    """Guia, Collider, "Ponto fraco": a piece that is also a body (AC10)."""

    def test_each_rule_sees_its_own_body(self):
        seen = []

        def play():
            torso = self.track(Rect(center=(300, 200), width=80, height=120, group="dp_fraco"))
            head = self.track(Circle(center=(300, 290), radius=30))
            chefe = Collider([torso, head])

            @collide("dp_bolt", "dp_fraco")
            def no_ponto_fraco(tiro, peca):
                seen.append(("fraco", peca))

            chefe.on_collide = lambda me, other, info: seen.append(("chefe", other.tagged("dp_bolt")))
            self.track(Circle(center=(300, 200), radius=4, group="dp_bolt"))
            self.w.step(2)
            hit = collision.raycast((0, 200), p2=(600, 200))
            return torso, chefe, hit
        torso, chefe, hit = self.run_quietly(play)
        self.assertEqual(sorted(seen, key=str), [("chefe", True), ("fraco", torso)])
        self.assertIs(hit[0], chefe)


if __name__ == "__main__":
    unittest.main()
