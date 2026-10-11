"""SpriteButton: hover / press / disabled feel, click, hull click area, sounds.

    python -m unittest tests.test_sprite_button -v
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from unittest import mock

import skia

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Attribute, Rect, Sprite, SpriteButton, click  # noqa: E402
from scena.canvas import ScenaCanvas  # noqa: E402
from scena.input import Mouse  # noqa: E402
from scena.orchestration import ShapeInteractionManager  # noqa: E402
from scena import transients  # noqa: E402


def _png(path, w, h, draw):
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    draw(c)
    surf.makeImageSnapshot().save(path, skia.kPNG)
    return path


def _disc(c, w=64, h=64, color=skia.ColorSetARGB(255, 220, 40, 40)):
    c.drawCircle(w / 2, h / 2, w / 2, skia.Paint(Color=color, AntiAlias=False))


def _ring(c):
    p = skia.Paint(Color=skia.ColorSetARGB(255, 40, 160, 220), AntiAlias=False,
                   Style=skia.Paint.kStroke_Style, StrokeWidth=10)
    c.drawCircle(32, 32, 26, p)


def _wedge(c):
    """Right triangle: opaque below the diagonal (bottom-left half)."""
    path = skia.Path()
    path.moveTo(0, 0)
    path.lineTo(0, 64)
    path.lineTo(64, 64)
    path.close()
    c.drawPath(path, skia.Paint(Color=skia.ColorSetARGB(255, 30, 200, 90), AntiAlias=False))


class ButtonTestCase(unittest.TestCase):
    _origin = 0

    def setUp(self):
        self.sim = ShapeInteractionManager(ScenaCanvas.get_current().registry)
        self.btn = Mouse.BTN_LEFT
        self._owned = []
        self._tmp = tempfile.TemporaryDirectory()
        ButtonTestCase._origin += 1000
        self.o = 50_000 + ButtonTestCase._origin
        self.t = [100.0]
        transients.set_now_fn(lambda: self.t[0])

    def tearDown(self):
        transients.set_now_fn(None)
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._tmp.cleanup()

    def track(self, s):
        self._owned.append(s)
        return s

    def art(self, name="disc.png", draw=_disc, w=64, h=64):
        return _png(os.path.normpath(os.path.join(self._tmp.name, name)), w, h, draw)

    def make(self, art=None, **kw):
        kw.setdefault("center", (self.o, self.o))
        kw.setdefault("width", 64)
        return self.track(SpriteButton(art or self.art(), **kw))

    # pointer helpers (ui layer = view coords)
    def down(self, x, y):
        return self.sim.handle_mouse_down(x, y, self.btn, ui=True)

    def up(self, x, y):
        return self.sim.handle_mouse_up(x, y, self.btn, ui=True)

    def move(self, x, y):
        self.sim.handle_mouse_move(x, y, ui=True)

    def hover_at(self, x, y):
        self.sim.note_pointer(view_xy=(x, y), world_xy=(-1e7, -1e7))
        self.sim.step_hover()

    def tick(self, dt=1.0):
        self.t[0] += dt


class TestBasics(ButtonTestCase):
    def test_is_a_sprite_on_ui_by_default(self):
        b = self.make()
        self.assertIsInstance(b, Sprite)
        self.assertEqual(b.layer, "ui")
        w = self.make(layer="default")
        self.assertEqual(w.layer, "default")

    def test_clickable_without_handler(self):
        b = self.make()
        self.assertTrue(b.clickable)
        self.assertIsNone(b.on_click)

    def test_bad_knobs(self):
        with self.assertRaises(ValueError):
            self.make(hover_scale=0)
        with self.assertRaises(ValueError):
            self.make(breathe=2)
        with self.assertRaises(TypeError):
            self.make(click_sound=3)
        with self.assertRaises(TypeError):
            self.make(enabled="no")
        with self.assertRaises(TypeError):
            self.make(on_click=lambda a, b, c: None)


class TestClick(ButtonTestCase):
    def test_click_on_release_inside_both_arities(self):
        seen = []
        b = self.make(on_click=lambda: seen.append("plain"))
        self.down(self.o, self.o)
        self.assertEqual(seen, [])
        self.up(self.o, self.o)
        self.assertEqual(seen, ["plain"])
        b.on_click = lambda button: seen.append(button)
        self.down(self.o, self.o)
        self.up(self.o, self.o)
        self.assertIs(seen[-1], b)

    def test_release_outside_no_click(self):
        seen = []
        self.make(on_click=lambda: seen.append(1))
        self.down(self.o, self.o)
        self.up(self.o + 500, self.o)
        self.assertEqual(seen, [])

    def test_click_decorator(self):
        b = self.make()
        seen = []

        @click(b)
        def go(button):
            seen.append(button)

        self.down(self.o, self.o)
        self.up(self.o, self.o)
        self.assertEqual(seen, [b])

    def test_class_body_on_click(self):
        seen = []

        class Play(SpriteButton):
            def on_click(self):
                seen.append(self)

        b = self.track(Play(self.art(), center=(self.o, self.o), width=64))
        self.down(self.o, self.o)
        self.up(self.o, self.o)
        self.assertEqual(seen, [b])


class TestDisabled(ButtonTestCase):
    def test_no_click_press_swallowed_hover_runs(self):
        below = self.track(Rect(center=(self.o, self.o), width=200, height=200, layer="ui"))
        below_clicks = []
        below.on_click = lambda s: below_clicks.append(s)
        clicks, hovers = [], []
        b = self.make(on_click=lambda: clicks.append(1), enabled=False)
        b.move_to_front()
        b.on_hover = lambda s: hovers.append(s)
        self.assertTrue(self.down(self.o, self.o))
        self.assertFalse(b.pointer_pressed)
        self.up(self.o, self.o)
        self.assertEqual(clicks, [])
        self.assertEqual(below_clicks, [])
        self.hover_at(self.o, self.o)
        self.assertEqual(hovers, [b])

    def test_disabling_between_press_and_release(self):
        clicks = []
        b = self.make(on_click=lambda: clicks.append(1))
        self.down(self.o, self.o)
        self.assertTrue(b.pointer_pressed)
        b.enabled = False
        self.assertFalse(b.pointer_pressed)
        self.move(self.o + 1, self.o)
        self.assertFalse(b.pointer_pressed)
        self.up(self.o, self.o)
        self.assertEqual(clicks, [])

    def test_enabled_link(self):
        coins = Attribute(3)
        b = self.make(enabled=lambda: coins.value >= 10)
        self.assertFalse(b.enabled)
        coins.value = 12
        self.assertTrue(b.enabled)
        b2 = self.make()
        b2["enabled"] @= lambda: coins.value >= 20
        self.assertFalse(b2.enabled)

    def test_enabled_lambda_assignment_refused(self):
        b = self.make()
        with self.assertRaises(Exception) as cm:
            b.enabled = lambda: True
        self.assertIn("@=", str(cm.exception))

    def test_plain_sprite_keeps_enabled_near_miss(self):
        s = self.track(Sprite(self.art(), center=(self.o, self.o)))
        with self.assertRaisesRegex(AttributeError, "active"):
            s.enabled = False
        with self.assertRaisesRegex(AttributeError, "active"):
            s["enabled"]


class TestHull(ButtonTestCase):
    def test_transparent_corner_is_outside(self):
        b = self.make()
        self.assertTrue(b.contains_point(self.o, self.o))
        self.assertFalse(b.contains_point(self.o + 30, self.o + 30))  # bbox corner

    def test_hull_fills_holes(self):
        ring = self.art("ring.png", _ring)
        b = self.make(ring)
        s = self.track(Sprite(ring, center=(self.o, self.o), width=64))
        self.assertFalse(s.contains_point(self.o, self.o))   # sprite: hole
        self.assertTrue(b.contains_point(self.o, self.o))    # button: hull

    def test_follows_flip_rotate_scale_offset(self):
        wedge = self.art("wedge.png", _wedge)
        b = self.make(wedge)
        o = self.o
        # Opaque half is bottom-left in the image (y down) → lower-left on screen.
        self.assertTrue(b.contains_point(o - 20, o - 20))
        self.assertFalse(b.contains_point(o + 20, o + 20))
        b.flip_x = True
        self.assertTrue(b.contains_point(o + 20, o - 20))
        self.assertFalse(b.contains_point(o - 20, o + 20))
        b.flip_x = False
        b.rotate_by(180)
        self.assertTrue(b.contains_point(o + 20, o + 20))
        b.rotate_by(180)
        b.scale = 2
        self.assertTrue(b.contains_point(o - 50, o - 50))
        b.scale = 1
        b.offset = (100, 0)
        self.assertTrue(b.contains_point(o + 80, o - 20))
        self.assertFalse(b.contains_point(o - 20, o - 20))

    def test_feel_never_writes_scale(self):
        b = self.make()
        self.hover_at(self.o, self.o)
        self.down(self.o, self.o)
        self.tick()
        self.assertEqual(b.scale, 1)
        self.assertEqual(b.width, 64)
        self.up(self.o, self.o)


def _render(b, size=200):
    info = skia.ImageInfo.Make(size, size, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    cx, cy = b.center.x, b.center.y
    c.translate(size / 2 - cx, size / 2 - cy)
    b.draw(c)
    img = surf.makeImageSnapshot()
    buf = bytearray(size * size * 4)
    img.readPixels(info, buf, size * 4, 0, 0)
    return buf, size


def _opaque_width(buf, size):
    row = size // 2
    xs = [x for x in range(size) if buf[(row * size + x) * 4 + 3] > 128]
    return (max(xs) - min(xs) + 1) if xs else 0


def _center_rgba(buf, size):
    i = ((size // 2) * size + size // 2) * 4
    return tuple(buf[i:i + 4])


class TestFeelPixels(ButtonTestCase):
    def test_hover_bigger_and_lighter_press_smaller_darker(self):
        b = self.make()
        base_buf, n = _render(b)
        base_w = _opaque_width(base_buf, n)
        base_rgb = _center_rgba(base_buf, n)
        self.hover_at(self.o, self.o)
        self.tick()
        hb, _ = _render(b)
        self.assertGreater(_opaque_width(hb, n), base_w)
        self.assertGreater(_center_rgba(hb, n)[1], base_rgb[1])
        self.down(self.o, self.o)
        self.tick()
        pb, _ = _render(b)
        self.assertLess(_opaque_width(pb, n), base_w)
        self.assertLess(_center_rgba(pb, n)[0], base_rgb[0])
        self.up(self.o, self.o)

    def test_disabled_gray_and_faded(self):
        b = self.make(enabled=False)
        buf, n = _render(b)
        r, g, bl, a = _center_rgba(buf, n)
        self.assertLessEqual(max(r, g, bl) - min(r, g, bl), 3)
        self.assertLess(a, 200)

    def test_transition_is_eased(self):
        b = self.make()
        self.hover_at(self.o, self.o)
        s0 = b._feel_at(self.t[0])[0]
        self.assertAlmostEqual(s0, 1.0)
        half = b._feel_at(self.t[0] + 0.05)[0]
        done = b._feel_at(self.t[0] + 0.2)[0]
        self.assertGreater(half, 1.0)
        self.assertLess(half, done)
        self.assertAlmostEqual(done, b.hover_scale)

    def test_breathe_swings_and_rests_on_hover(self):
        b = self.make(breathe=True, breathe_time=2.0)
        t0 = self.t[0]
        quarter = b._feel_at(t0 + 0.5)[0]
        three_q = b._feel_at(t0 + 1.5)[0]
        self.assertAlmostEqual(quarter, 1.05, places=3)
        self.assertAlmostEqual(three_q, 0.95, places=3)
        self.hover_at(self.o, self.o)
        self.tick(0.5)
        self.assertAlmostEqual(b._feel_at(self.t[0])[0], b.hover_scale, places=6)

    def test_breathe_off_by_default(self):
        b = self.make()
        self.assertEqual(b.breathe, 0.0)
        self.assertAlmostEqual(b._feel_at(self.t[0] + 0.4)[0], 1.0)


class TestDrawRoutes(ButtonTestCase):
    def test_draws_solo_through_the_canvas(self):
        from scena.canvas import _must_solo_draw
        b = self.make()
        self.assertTrue(_must_solo_draw(b))
        self.assertFalse(b._plain_blit)
        b.hue = True          # would make a plain Sprite plain-blit
        self.assertFalse(b._plain_blit)

    def test_glow_takes_the_filtered_route(self):
        b = self.make()
        b.glow = True
        canvas = ScenaCanvas.get_current()
        with mock.patch.object(type(canvas), "_draw_filtered_one",
                               autospec=True, side_effect=type(canvas)._draw_filtered_one) as spy:
            canvas._draw_layer_batched([b])
        spy.assert_called_once()

    def test_attached_parts_ride_the_transient_envelope(self):
        b = self.make()
        calls = []
        with mock.patch.object(SpriteButton, "_draw_attached", lambda self, c: calls.append(1)):
            _render(b)
            self.assertEqual(len(calls), 1)
            b.fade_out(1.0)
            self.tick(0.3)
            _render(b)
            self.assertEqual(len(calls), 2)

    def test_cull_pad_covers_growth(self):
        b = self.make(breathe=0.1)
        self.assertGreater(b._cull_pad(), 0.0)


def _dark(c):
    c.drawRect(skia.Rect.MakeWH(64, 64), skia.Paint(Color=skia.ColorSetARGB(255, 20, 20, 60)))


class TestLabel(ButtonTestCase):
    def dark(self, **kw):
        kw.setdefault("width", 160)
        return self.make(self.art("dark.png", _dark), **kw)

    def test_label_is_a_text_part(self):
        from scena import Text
        b = self.dark(label="Jogar")
        self.assertEqual(b.label, "Jogar")
        self.assertIsInstance(b.label_text, Text)
        self.assertIsNone(b.label_text.layer)
        self.assertEqual(b.label_text.name.split(".")[-1], "label_text")
        b.label = "Continuar"
        self.assertEqual(b.label_text.text.value, "Continuar")
        b.label = 3
        self.assertEqual(b.label, "3")

    def test_no_label_then_set(self):
        b = self.dark()
        self.assertIsNone(b.label)
        self.assertIsNone(b.label_text)
        b.label = "Oi"
        self.assertEqual(b.label, "Oi")

    def test_label_drawn_at_the_center(self):
        def bright(buf, n):
            row = n // 2
            return [x for x in range(n) if buf[(row * n + x) * 4] > 200]

        b = self.dark(label="OOOO", label_color="white")
        buf, n = _render(b)
        xs = bright(buf, n)
        self.assertTrue(xs)
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, n / 2, delta=4)   # centered
        self.assertEqual(bright(*_render(self.dark())), [])

    def test_shrinks_to_fit_font_size_unchanged(self):
        b = self.dark(label="Um texto muito comprido para o botao", font_size=40)
        _bx, _by, bw, bh, _a = b._label_box()
        k = b._label_fit(bw, bh)
        self.assertLess(k, 1.0)
        self.assertEqual(b.label_text.font_size, 40)
        short = self.dark(label="Ok", font_size=20)
        self.assertEqual(short._label_fit(*short._label_box()[2:4]), 1.0)

    def test_fit_floor_warns_once(self):
        b = self.make(self.art("dark.png", _dark), width=20,
                      label="Texto longo demais para um botao pequeno", font_size=30)
        with mock.patch("scena.process.report_author_warning") as warn:
            _render(b)
            _render(b)
        self.assertEqual(warn.call_count, 1)

    def test_reactive_label(self):
        score = Attribute(1)
        b = self.dark(label=lambda: f"Vidas {score.value}")
        self.assertEqual(b.label, "Vidas 1")
        score.value = 2
        self.assertEqual(b.label, "Vidas 2")
        with self.assertRaisesRegex(Exception, "label_text"):
            b.label = lambda: "x"

    def test_a_state_cell_label_follows(self):
        # 0.8.0: label=st["vidas"] binds the cell; label=st.vidas is the number
        # of now (a snapshot, as for any value).
        from scena import State
        hud = State(name="hud_sb")
        hud.vidas = 3
        b = self.dark(label=hud["vidas"])
        self.assertEqual(b.label, "3")
        hud.vidas = 2
        self.assertEqual(b.label, "2")
        snap = self.dark(label=hud.vidas)
        hud.vidas = 1
        self.assertEqual(snap.label, "2")

    def test_style_keywords_need_a_label(self):
        with self.assertRaisesRegex(TypeError, "label="):
            self.dark(font_size=20)

    def test_gradient_color_and_glow_render(self):
        from scena import Gradient
        b = self.dark(label="AB", label_color=Gradient("gold", "red"))
        b.label_text.glow = True
        _render(b)

    def test_inset_moves_the_box(self):
        b = self.dark(label="A")
        cx0, cy0, w0, h0, _ = b._label_box()
        b.label_inset = (0, 0, 0, 10)          # a 10-unit lip at the bottom
        cx1, cy1, w1, h1, _ = b._label_box()
        self.assertAlmostEqual(cy1 - cy0, 5.0)
        self.assertAlmostEqual(h0 - h1, 10.0)
        with self.assertRaises(ValueError):
            b.label_inset = -1

    def test_flip_keeps_text_upright(self):
        b = self.dark(label="A")
        a0 = b._label_box()[4]
        b.flip_x = True
        self.assertAlmostEqual(b._label_box()[4], a0)

    def test_part_lifecycle(self):
        b = self.dark(label="A")
        t = b.label_text
        with self.assertRaises(TypeError):
            t.destroy()
        with self.assertRaisesRegex(TypeError, "drawn by its SpriteButton"):
            t.layer = "ui"
        b.active = False
        self.assertFalse(t.active)
        b.active = True
        self.assertTrue(t.active)
        b.destroy()
        self.assertFalse(t.is_alive)

    def test_clone_keeps_label_not_handler(self):
        b = self.dark(label="Jogar", font_size=22, on_click=lambda: None, breathe=True)
        c = self.track(b.clone())
        self.assertEqual(c.label, "Jogar")
        self.assertEqual(c.label_text.font_size, 22)
        self.assertEqual(c.breathe, b.breathe)
        self.assertIsNone(c.on_click)
        self.assertEqual(c.layer, "ui")


def _solid(rgb):
    def draw(c):
        c.drawRect(skia.Rect.MakeWH(64, 64), skia.Paint(Color=skia.ColorSetARGB(255, *rgb)))
    return draw


class TestStateArt(ButtonTestCase):
    def files(self):
        return (self.art("idle.png", _solid((200, 0, 0))),
                self.art("hov.png", _solid((0, 200, 0))),
                self.art("prs.png", _solid((0, 0, 200))),
                self.art("off.png", _solid((90, 90, 30))))

    def test_files_swap_art_and_skip_default_effect(self):
        idle, hov, prs, off = self.files()
        b = self.make(idle, hover=hov, pressed=prs, disabled=off)
        base_buf, n = _render(b)
        self.assertEqual(_center_rgba(base_buf, n)[:3], (200, 0, 0))
        base_w = _opaque_width(base_buf, n)
        self.hover_at(self.o, self.o)
        self.tick()
        buf, _ = _render(b)
        self.assertEqual(_center_rgba(buf, n)[:3], (0, 200, 0))
        self.assertEqual(_opaque_width(buf, n), base_w)       # no hover growth
        self.assertEqual(b.frame, 0)                           # author frame untouched
        self.down(self.o, self.o)
        self.tick()
        self.assertEqual(_center_rgba(_render(b)[0], n)[:3], (0, 0, 200))
        self.up(self.o, self.o)
        b.enabled = False
        self.tick()
        self.assertEqual(_center_rgba(_render(b)[0], n), (90, 90, 30, 255))   # not grayed

    def test_only_some_states(self):
        idle, hov, _, _ = self.files()
        b = self.make(idle, hover=hov)
        self.down(self.o, self.o)
        self.tick()
        buf, n = _render(b)
        self.assertLess(_center_rgba(buf, n)[0], 200)          # default press darkens
        self.up(self.o, self.o)

    def test_taller_pressed_art_does_not_move_the_hull(self):
        idle = self.art("idle.png", _disc)
        tall = self.art("tall.png", lambda c: c.drawRect(
            skia.Rect.MakeWH(64, 96), skia.Paint(Color=skia.ColorBLUE)), h=96)
        b = self.make(idle, pressed=tall)
        probe = (self.o + 30, self.o + 30)
        before = b.contains_point(*probe)
        self.down(self.o, self.o)
        self.tick()
        _render(b)
        self.assertEqual(b.contains_point(*probe), before)
        self.assertFalse(before)
        self.up(self.o, self.o)

    def test_sheet_frames_and_clips(self):
        from scena import Sheet
        files = self.files()
        sheet = Sheet(*files)
        sheet.clip("brilho", [1, 2], fps=10)
        b = self.make(sheet, frame=0, hover="brilho", pressed=3)
        self.assertEqual(b._state_art, {"hover": "brilho", "pressed": 3})
        self.hover_at(self.o, self.o)
        t0 = self.t[0]
        n = 200
        self.t[0] = t0 + 0.05
        self.assertEqual(_center_rgba(_render(b)[0], n)[:3], (0, 200, 0))
        self.t[0] = t0 + 0.15
        self.assertEqual(_center_rgba(_render(b)[0], n)[:3], (0, 0, 200))

    def test_author_clip_keeps_playing_under_state_art(self):
        from scena import Sheet
        idle, hov, prs, _ = self.files()
        sheet = Sheet(idle, prs)
        sheet.clip("idle", [0, 1], fps=4)
        b = self.make(sheet, hover=1)
        b.play("idle")
        playing = b._play_frames
        self.hover_at(self.o, self.o)
        _render(b)
        self.assertEqual(b._play_frames, playing)
        self.assertEqual(b._play_name, "idle")

    def test_bad_specs(self):
        from scena import Sheet
        idle, hov, _, _ = self.files()
        with self.assertRaises(TypeError):
            self.make(idle, hover=1)
        with self.assertRaises(ValueError):
            self.make(Sheet(idle, hov), hover="nope")

    def test_clone_keeps_state_art(self):
        idle, hov, prs, _ = self.files()
        b = self.make(idle, hover=hov, pressed=prs)
        c = self.track(b.clone())
        self.assertEqual(c._state_art, b._state_art)


class TestSounds(ButtonTestCase):
    def test_click_sound_is_global_hover_sound_owned(self):
        b = self.make(click_sound="click.wav", hover_sound="hover.wav")
        with mock.patch("scena.audio.play_sound") as global_play, \
                mock.patch.object(SpriteButton, "play_sound") as owned:
            self.hover_at(self.o, self.o)
            owned.assert_called_once_with("hover.wav")
            self.down(self.o, self.o)
            self.up(self.o, self.o)
            global_play.assert_called_once_with("click.wav")

    def test_disabled_is_silent(self):
        b = self.make(click_sound="click.wav", hover_sound="hover.wav", enabled=False)
        with mock.patch("scena.audio.play_sound") as global_play, \
                mock.patch.object(SpriteButton, "play_sound") as owned:
            self.hover_at(self.o, self.o)
            self.down(self.o, self.o)
            self.up(self.o, self.o)
            owned.assert_not_called()
            global_play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
