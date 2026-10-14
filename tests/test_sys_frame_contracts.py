"""Frame-scoped promises of the Guia, each checked in real frames.

Class guard for the lesson of PM3 (Testing Design, "What the program-model
campaign taught" 2): a contract that names a frame ("só no frame do aperto",
"no próximo frame", "no mesmo frame", "cada frame seguinte") is tested with
real frames (``SystemWorld`` / ``ProgramRun``), never by calling internals back
to back. ``TestEveryFramePromiseHasATest`` scans the Guia for such sentences:
each one maps to a test here (or elsewhere) or to a reason it is not a timing
contract, so a new promise without a test fails.

    python -m unittest tests.test_sys_frame_contracts -v
"""
from __future__ import annotations

import html
import importlib
import math
import os
import re
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import FRAME, quiet, system_world  # noqa: E402

import numpy as np  # noqa: E402
import skia  # noqa: E402

from scena import (  # noqa: E402
    STATIC, Circle, GlowSpot, Plasma, Rect, Sheet, Sprite, Vignette, canvas,
    collide, collide_stay, resolve, when,
)
from scena.scenamath import Vec2  # noqa: E402
from scena.state import LinkedAttributeError  # noqa: E402

GUIA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "docs", "pt", "guide", "index.html")


def _png(path, w, h, color):
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    surf.getCanvas().drawPaint(skia.Paint(Color=color))
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _screen(world):
    a = np.asarray(world.surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))
    return a[: int(canvas.height), : int(canvas.width)].copy()


# --------------------------------------------------------------------------
# Collision
# --------------------------------------------------------------------------

class TestCollisionFrames(unittest.TestCase):

    def test_stay_runs_each_following_frame_not_the_enter_frame(self):
        # Guia #colisao-collide: "on_collide stay — Cada frame seguinte ainda sobrepostos."
        with system_world(draw=False) as w:
            w.track(Circle(center=(100, 100), radius=10, group="fc_a"))
            w.track(Circle(center=(105, 100), radius=10, group="fc_b"))
            log = []
            collide("fc_a", "fc_b")(lambda a, b, info=None: log.append((w.frames_run, "enter")))
            collide_stay("fc_a", "fc_b")(lambda a, b, info=None: log.append((w.frames_run, "stay")))
            w.step(4)
        self.assertEqual(log, [(0, "enter"), (1, "stay"), (2, "stay"), (3, "stay")])

    def test_stay_sees_the_overlap_before_the_auto_resolve(self):
        # Guia #colisao-touching: touching reflects the previous frame; "Para
        # decidir no mesmo frame, use @collide_stay com info.side, antes do
        # auto-resolve."
        with system_world(draw=False) as w:
            floor = w.track(Rect(center=(200, 50), width=400, height=20, group="fc_floor"))
            floor.mass = STATIC
            box = w.track(Rect(center=(200, 75), width=20, height=20, group="fc_box"))
            box.mass = 1.0
            box.vel = Vec2(0.0, 0.0)
            resolve("fc_box", "fc_floor", bounce=0.0)
            seen = []

            def stay(me, other, info):
                seen.append((info.side, float(info.depth), tuple(me.touching_sides)))
            collide_stay("fc_box", "fc_floor")(stay)
            w.on_update(lambda dt: box.move_by(0, -120 * dt))     # pressed into the floor
            w.step(5)
        self.assertTrue(seen, "no stay contact")
        sides = {s for s, _d, _t in seen}
        self.assertEqual(sides, {"bottom"})
        # In the handler the body is still pressed in: the resolve comes after.
        self.assertTrue(any(d > 0.5 for _s, d, _t in seen), seen)

    def test_leaves_the_ground_only_when_it_moves_away(self):
        # Guia #res-snap: "Só sai do chão quando, no mesmo frame, a velocidade
        # (.vel) aponta para longe do chão e o corpo de fato se afasta dele."
        with system_world(draw=False) as w:
            floor = w.track(Rect(center=(200, 50), width=400, height=20, group="fc_floor"))
            floor.mass = STATIC
            hero = w.track(Rect(center=(200, 71), width=20, height=20, group="fc_hero"))
            hero.mass = 1.0
            hero.vel = Vec2(0.0, 0.0)
            resolve("fc_hero", "fc_floor", bounce=0.0)

            def fall(dt):
                hero.vel.y -= 900 * dt
                hero.move_by(0, hero.vel.y * dt)
            w.on_update(fall)
            w.step(30)
            self.assertIn("bottom", hero.touching_sides)
            w.on_update(None)
            hero.vel = Vec2(0.0, 300.0)       # points away, but it does not move:
            w.step(3)
            self.assertIn("bottom", hero.touching_sides, "left the ground without moving")
            w.on_update(lambda dt: hero.move_by(0, hero.vel.y * dt))
            w.step(3)                         # points away and moves away
            self.assertNotIn("bottom", hero.touching_sides)


# --------------------------------------------------------------------------
# Motion
# --------------------------------------------------------------------------

class TestMotionFrames(unittest.TestCase):

    def test_handle_velocity_is_this_frames_units_per_second(self):
        # Guia #agendar-handle: ".velocity — Unidades por segundo neste frame (mundo)."
        with system_world(draw=False) as w:
            c = w.track(Circle(center=(0, 0), radius=5))
            h = c.move_to(120, 0, time=1.0)
            w.step(10)
            v = h.velocity
            self.assertAlmostEqual(float(v.x), 120.0, places=6)
            self.assertAlmostEqual(float(v.y), 0.0, places=6)
            w.step(60)                        # finished: keeps the last frame's
            self.assertTrue(h.done)           # (on_done reads the arrival speed)
            self.assertAlmostEqual(float(h.velocity.x), 120.0, places=6)

    def test_link_on_a_tweened_field_refuses_at_the_link(self):
        # Guia #reativo-drivers: "LinkedAttributeError no @= (não no próximo frame)".
        with system_world(draw=False) as w:
            c = w.track(Circle(center=(0, 0), radius=5))
            src = w.track(Circle(center=(9, 9), radius=5))
            c.move_to(100, 0, time=1.0)
            w.step(1)
            with self.assertRaises(LinkedAttributeError):
                c["center"] @= lambda: src.center


# --------------------------------------------------------------------------
# Look parameters
# --------------------------------------------------------------------------

class TestParametersApplyNextFrame(unittest.TestCase):
    """Guia #desenhar-spatial / #mundo-background / #mundo-post: "atribuem na
    instância e valem no próximo frame" — the read is the new value at once,
    and the next drawn frame shows it."""

    def _check(self, make, attr, value):
        with system_world(draw=True) as w:
            with quiet():
                obj = make(w)
            w.step(2)
            before = _screen(w)
            setattr(obj, attr, value)
            self.assertAlmostEqual(float(getattr(obj, attr)), float(value))
            w.step(1)
            after = _screen(w)
            remove = getattr(obj, "remove", None) or getattr(obj, "destroy", None)
            with quiet():
                remove()
        self.assertGreater(int(np.abs(before.astype(int) - after.astype(int)).max()), 0,
                           f"{type(obj).__name__}.{attr} = {value} did not change the next frame")

    def test_spatial_fx(self):
        self._check(lambda w: w.track(GlowSpot(center=(200, 150), radius=60, amount=0.2)),
                    "amount", 2.0)

    def test_post_effect(self):
        def make(w):
            w.track(Rect(center=(200, 150), width=400, height=300, color="white"))
            v = Vignette(amount=0.0)
            canvas.effects.add(v)
            return v
        self._check(make, "amount", 1.0)

    def test_background(self):
        self._check(lambda w: Plasma("cyan", amount=0.1, alpha=0.9), "amount", 1.0)


# --------------------------------------------------------------------------
# Sprite parts
# --------------------------------------------------------------------------

class TestSpritePartFrames(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _sheet(self, blank_frame=None):
        names = []
        for i in range(4):
            p = os.path.join(self._tmp.name, f"f{i}.png")
            color = skia.ColorTRANSPARENT if i == blank_frame else skia.ColorWHITE
            _png(p, 32, 32, color)
            names.append(p)
        sheet = Sheet(names, fps=60)
        sheet.clip("idle", [0, 1], fps=60)
        sheet.clip("punch", [2, 3], fps=60)
        return sheet

    def test_formula_driven_part_is_live_in_the_same_frame_when_is_late(self):
        # Guia #spr-hit-ref: part["active"] @= lambda: … "é calculado antes da
        # colisão do mesmo frame do jogo. @when roda depois: um frame de atraso."
        results = {}
        for how in ("formula", "when"):
            with system_world(draw=False) as w:
                with quiet():
                    hero = w.track(Sprite(self._sheet(), center=(100, 100), height=32))
                    target = w.track(Circle(center=(120, 100), radius=8, group="fc_tgt"))
                    part = hero.add_hitbox(group="fc_fist", source="each")
                part.active = False
                if how == "formula":
                    part["active"] @= lambda: hero.showing("punch")
                else:
                    @when(lambda: hero.showing("punch"))
                    def _on():
                        part.active = True
                hits = []
                collide("fc_fist", "fc_tgt")(lambda a, b, info=None: hits.append(w.frames_run))
                w.step(2)
                w.on_update(lambda dt: hero.play("punch") if not hero.showing("punch") else None)
                w.step(3)
                results[how] = hits[:1]
        self.assertTrue(results["formula"], results)
        self.assertTrue(results["when"], results)
        self.assertEqual(results["when"][0], results["formula"][0] + 1, results)

    def test_part_is_absent_on_a_frame_without_art(self):
        # Guia #spr-hit-partes: "Frame sem arte (com "each") = parte ausente nesse frame."
        with system_world(draw=False) as w:
            with quiet():
                hero = w.track(Sprite(self._sheet(blank_frame=3), center=(100, 100), height=32))
                w.track(Circle(center=(100, 100), radius=4, group="fc_tgt2"))
                hero.add_hitbox(group="fc_part", source="each")
            log = []
            collide("fc_part", "fc_tgt2")(lambda a, b, info=None: log.append((w.frames_run, "enter")))
            from scena import collide_exit
            collide_exit("fc_part", "fc_tgt2")(lambda a, b, info=None: log.append((w.frames_run, "exit")))
            hero.frame = 2
            w.step(1)
            hero.frame = 3                   # transparent: no part this frame
            w.step(1)
            hero.frame = 2
            w.step(1)
            during = [e for _f, e in log]    # before teardown's own exit
        self.assertEqual(during, ["enter", "exit", "enter"], log)


# --------------------------------------------------------------------------
# The Guia scan: every frame promise has a test or a reason
# --------------------------------------------------------------------------

_HERE = "test_sys_frame_contracts"
# A distinctive piece of the sentence -> "module.Class.test" or "prose: why".
FRAME_PROMISES = {
    "com speed= ele termina no frame seguinte": "test_timed_speed.TestSameTweenAfterwards.test_empty_group_is_a_finished_timer",
    "Distância zero termina no frame seguinte": "test_timed_speed.TestSameTweenAfterwards.test_zero_distance_finishes_on_the_next_tick",
    "quanto o objeto andou neste frame, por segundo": "test_timed_speed.TestSameTweenAfterwards.test_linear_readout_reads_the_requested_speed",
    'keyp("A") é True em todo frame em que a tecla está segurada': "test_keyp.TestOnceIsFrameScopedInFrames.test_a_press_read_in_its_frame_fires_once",
    'keyp.once("A") só no frame em que A foi apertada': "test_keyp.TestOnceIsFrameScopedInFrames.test_a_press_nobody_read_does_not_fire_later",
    "True só no frame do aperto de A": "test_keyp.TestOnceIsFrameScopedInFrames.test_a_press_nobody_read_does_not_fire_later",
    "dispara uma vez, no frame do aperto, só quando os dois flags": "test_keyp.TestOnceIsFrameScopedInFrames.test_a_press_nobody_read_does_not_fire_later",
    "O gotcha acima só cobre o mesmo frame": "prose: points back at the keyp.once rule",
    "LinkedAttributeError no @= (não no próximo frame)": f"{_HERE}.TestMotionFrames.test_link_on_a_tweened_field_refuses_at_the_link",
    "Sem colisor nesse frame": f"{_HERE}.TestSpritePartFrames.test_part_is_absent_on_a_frame_without_art",
    'Frame sem arte (com "each" ) = parte ausente nesse frame': f"{_HERE}.TestSpritePartFrames.test_part_is_absent_on_a_frame_without_art",
    "atrasa se um play() vier depois dela no mesmo frame do jogo": f"{_HERE}.TestSpritePartFrames.test_formula_driven_part_is_live_in_the_same_frame_when_is_late",
    "é calculado antes da colisão do mesmo frame do jogo": f"{_HERE}.TestSpritePartFrames.test_formula_driven_part_is_live_in_the_same_frame_when_is_late",
    "( fogo.amount = 2 ) e valem no próximo frame": f"{_HERE}.TestParametersApplyNextFrame.test_spatial_fx",
    "Parâmetros do construtor atribuem na instância e valem no próximo frame — exceções": f"{_HERE}.TestParametersApplyNextFrame.test_background",
    "Parâmetros do construtor atribuem na instância e valem no próximo frame. Impactos": f"{_HERE}.TestParametersApplyNextFrame.test_post_effect",
    "não tocou a borda neste frame": "test_confine.TestClampCenter.test_defaults_are_center_clamp",
    "Unidades por segundo neste frame (mundo)": f"{_HERE}.TestMotionFrames.test_handle_velocity_is_this_frames_units_per_second",
    "on_done / then= no próximo frame, só num fim natural": "test_audio_capture.TestRecording.test_seconds_truncates_mid_block_and_on_done_fires_once",
    "O clip toca na linha seguinte; on_done espera o próximo frame": "test_audio_capture.TestRecording.test_seconds_truncates_mid_block_and_on_done_fires_once",
    "tocável na linha seguinte no próximo frame": "test_audio_capture.TestRecording.test_seconds_truncates_mid_block_and_on_done_fires_once",
    "seconds= atingido sim no próximo frame": "test_audio_capture.TestRecording.test_seconds_truncates_mid_block_and_on_done_fires_once",
    "teto de 30 s sim no próximo frame": "test_audio_capture.TestRecording.test_seconds_truncates_mid_block_and_on_done_fires_once",
    "Cada frame seguinte ainda sobrepostos": f"{_HERE}.TestCollisionFrames.test_stay_runs_each_following_frame_not_the_enter_frame",
    "no mesmo frame, a velocidade ( .vel ) aponta para longe do chão": f"{_HERE}.TestCollisionFrames.test_leaves_the_ground_only_when_it_moves_away",
    "Para decidir no mesmo frame, use @collide_stay com info.side": f"{_HERE}.TestCollisionFrames.test_stay_sees_the_overlap_before_the_auto_resolve",
    "o que o tween andou neste frame": "prose: names Handle.heading to tell it apart from heading()",
    "mouse.x ainda é o valor de antes da câmera andar": f"{_HERE}.TestPointerFrames.test_mouse_x_after_pan_is_the_frame_sample",
}

_PROMISE = re.compile(r"(só no frame|próximo frame|mesmo frame|neste frame|nesse frame|"
                      r"frame do aperto|frame seguinte|no frame em que)", re.I)


def _guia_text() -> str:
    with open(GUIA, encoding="utf-8") as fh:
        raw = fh.read()
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))


class TestPointerFrames(unittest.TestCase):

    def test_mouse_x_after_pan_is_the_frame_sample(self):
        """PC8 (2026-10-14): the pointer is sampled once per frame. After
        ``canvas.pan_by`` in an update, ``mouse.x`` still reads the world value
        of the frame's start; the next frame reads the moved camera."""
        from input_driver import input_driver
        from scena import mouse
        with system_world(draw=False) as w, input_driver(w) as d:
            seen = []

            def update(dt):
                before = float(mouse.x)
                canvas.pan_by(10, 0)
                seen.append((before, float(mouse.x)))
            w.on_update(update)
            w.begin_game()
            d.move(100, 100)
            w.step(3)
            w.on_update(None)
        self.assertGreaterEqual(len(seen), 3)
        for (before, after), (nxt, _) in zip(seen[1:], seen[2:]):
            self.assertEqual(after, before)          # same update: not moved yet
            self.assertAlmostEqual(abs(nxt - before), 10.0)   # next frame: the pan shows


class TestEveryFramePromiseHasATest(unittest.TestCase):

    def test_each_promise_is_mapped(self):
        text = _guia_text()
        unmapped = []
        for m in _PROMISE.finditer(text):
            window = text[max(0, m.start() - 160): m.end() + 160]
            if not any(key in window for key in FRAME_PROMISES):
                unmapped.append("…" + text[max(0, m.start() - 90): m.end() + 60] + "…")
        self.assertFalse(unmapped, "Guia frame promises with no test in FRAME_PROMISES:\n"
                         + "\n".join(unmapped))

    def test_no_stale_entry_and_tests_exist(self):
        text = _guia_text()
        for key, target in FRAME_PROMISES.items():
            with self.subTest(promise=key):
                self.assertIn(key, text, "the Guia no longer says this: update the table")
                if target.startswith("prose:"):
                    continue
                mod, cls, meth = target.split(".")
                module = importlib.import_module(mod)
                self.assertTrue(hasattr(getattr(module, cls), meth), f"missing test {target}")


if __name__ == "__main__":
    unittest.main()
