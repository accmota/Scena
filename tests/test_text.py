"""
Unit tests for Text (caption Graphic replacing Label).

Run:

    python -m unittest tests.test_text -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Color, Glow, Neon, CheapGlow, Text, Button, Slider, canvas, group, init, st, ui
from scena.orchestration import ScenaFramework
from scena.registry import BUILT_IN_LAYERS, UiLayerError
from scena.shapes import Circle
from scena.state import Attribute, LinkedAttributeError, State


class TextTestCase(unittest.TestCase):
    _key_n = 0

    def setUp(self):
        init(width=800, height=600)
        ui.scale = 1.0
        ui.font = None
        self.wm = ScenaFramework.get_instance().widget_manager
        self._owned = []

    def tearDown(self):
        for o in list(self._owned):
            try:
                o.destroy()
            except Exception:
                pass
        self._owned.clear()
        for w in list(self.wm.widgets):
            self.wm.remove_widget(w)
        ui.stack_reset()
        for name in list(canvas.layers):
            if name not in BUILT_IN_LAYERS:
                try:
                    canvas.layers[name].delete(destroy_shapes=True)
                except Exception:
                    pass
        canvas.layers.default = "default"

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def key(self, prefix="tx"):
        TextTestCase._key_n += 1
        return f"{prefix}_{TextTestCase._key_n}"


class TestTextPlacement(TextTestCase):
    def test_default_is_ui_autostack(self):
        ui.stack_reset()
        a = self.track(Text("AAAA", font_size=16))
        b = self.track(Text("BBBB", font_size=16))
        self.assertEqual(a.layer, "ui")
        self.assertEqual(b.layer, "ui")
        self.assertAlmostEqual(a._x1, b._x1)
        self.assertGreater(a._y1, b._y1)
        self.assertNotIn(a, self.wm.widgets)

    def test_scalar_placement_keywords_orient_to_points(self):
        # x1= / y1= / x= / pos= are other frameworks' spellings; one hint names
        # the point keywords (no "removed" wording: this was never published).
        for kw in ("x1", "y1", "x", "y", "pos", "position"):
            with self.subTest(kw=kw):
                with self.assertRaises(TypeError) as ctx:
                    Text("Hi", **{kw: 80})
                msg = str(ctx.exception)
                self.assertIn("top_left=(x, y)", msg)
                self.assertNotIn("removed", msg)
        with self.assertRaises(TypeError) as ctx:
            Text("Hi", x1=80, y1=90)
        self.assertEqual(str(ctx.exception).count("Text is placed by a point"), 1)

    def test_center_implies_world_default(self):
        t = self.track(Text("HP", center=(100, 200)))
        self.assertEqual(t.layer, "default")

    def test_move_to_about_center_and_offset(self):
        t = self.track(Text("HP", center=(0, 0), stack=False))
        t.move_to(50, 60, about=t.center)
        self.assertAlmostEqual(float(t.center.x), 50.0, places=5)
        self.assertAlmostEqual(float(t.center.y), 60.0, places=5)
        t.move_to(50, 60, about=(40, 60))
        self.assertAlmostEqual(float(t.center.x), 60.0, places=5)
        self.assertAlmostEqual(float(t.center.y), 60.0, places=5)

    def test_top_left_view_placement(self):
        t = self.track(Text(text="Hi", top_left=(20, 100), font_size=16))
        self.assertEqual(t.layer, "ui")
        self.assertAlmostEqual(t._x1, 20.0)
        self.assertAlmostEqual(t._y2, 100.0)   # the anchor is the visual top
        self.assertLess(t._y1, 100.0)

    def test_center_plus_anchor_raises(self):
        with self.assertRaises(TypeError):
            Text("bad", center=(1, 1), top_left=(20, 20))

    def test_world_layer_needs_center(self):
        with self.assertRaises(TypeError):
            Text("bad", layer="default")


class TestHudStack(TextTestCase):
    def theme_gap(self):
        self.wm.widget_theme._ensure()
        return self.wm.widget_theme.stack_gap

    def test_auto_text_then_widget(self):
        ui.stack_reset()
        t = self.track(Text("Title", font_size=16))
        b = self.track(Button(label="Go"))
        self.assertAlmostEqual(t._x1, b._x1)
        self.assertGreater(t._y1, b._y1)
        self.assertNotIn(t, self.wm.widgets)
        self.assertIn(b, self.wm.widgets)

    def test_explicit_text_then_widget(self):
        ui.stack_reset()
        t = self.track(Text("Volume", top_left=(20, 400), font_size=16))
        s = self.track(Slider(label="Vol"))
        self.assertAlmostEqual(s._x1, t._x1)
        self.assertAlmostEqual(s._y2, t._y1 - self.theme_gap(), places=4)

    def test_widget_then_text_then_widget(self):
        ui.stack_reset()
        a = self.track(Button(label="AAAA"))
        t = self.track(Text("hint", font_size=16))
        b = self.track(Button(label="BBBB"))
        self.assertAlmostEqual(a._x1, t._x1)
        self.assertAlmostEqual(t._x1, b._x1)
        self.assertGreater(a._y1, t._y1)
        self.assertGreater(t._y1, b._y1)

    def test_world_text_does_not_seed_column(self):
        ui.stack_reset()
        self.track(Text("HP", center=(100, 200)))
        b = self.track(Button(label="Go"))
        self.assertAlmostEqual(b._x1, 20.0)
        self.assertAlmostEqual(b._y2, 560.0, places=4)

    def test_stack_false_does_not_steal_column(self):
        ui.stack_reset()
        a = self.track(Text("A", font_size=16))
        self.track(Text("fps", top_left=(20, 16), font_size=14, stack=False))
        b = self.track(Button(label="Go"))
        self.assertAlmostEqual(b._x1, a._x1)
        self.assertAlmostEqual(b._y2, a._y1 - self.theme_gap(), places=4)

    def test_destroy_last_item_rewinds_column(self):
        ui.stack_reset()
        t = self.track(Text("A", font_size=16))
        top = t._y2
        x = t._x1
        t.destroy()
        self._owned.remove(t)
        b = self.track(Button(label="Go"))
        self.assertAlmostEqual(b._x1, x)
        self.assertAlmostEqual(b._y2, top, places=4)

    def test_gap_between_text_and_widget(self):
        ui.stack_reset()
        t = self.track(Text("A", font_size=16))
        ui.gap()
        b = self.track(Button(label="Go"))
        self.assertAlmostEqual(b._y2, t._y1 - 2 * self.theme_gap(), places=4)

    def test_stack_reset_restarts_column(self):
        ui.stack_reset()
        t = self.track(Text("A", top_left=(20, 200), font_size=16))
        ui.stack_reset()
        b = self.track(Button(label="Go"))
        self.assertGreater(b._y1, t._y1)

    def test_stack_from_continues_below_item(self):
        ui.stack_reset()
        t = self.track(Text("chrome", top_left=(24, 500), font_size=16))
        ui.stack_reset()
        ui.stack_from(t)
        b = self.track(Button(label="Go"))
        self.assertAlmostEqual(b._x1, t._x1)
        self.assertAlmostEqual(b._y2, t._y1 - self.theme_gap(), places=4)

    def test_stack_origin_starts_new_column(self):
        ui.stack_reset()
        ui.stack_origin(80, 300)
        b = self.track(Button(label="Go"))
        self.assertAlmostEqual(b._x1, 80.0)
        self.assertAlmostEqual(b._y2, 300.0, places=4)

    def test_stack_column_clears_widest_hud_text(self):
        ui.stack_reset()
        t = self.track(Text("Title that is wider than Go", font_size=16))
        b = self.track(Button(label="Go", width=40))
        self.assertGreater(t._x2, b._x2)
        ui.stack_column()
        c = self.track(Button(label="Next"))
        self.assertAlmostEqual(c._x1, t._x2 + self.theme_gap(), places=4)
        self.assertAlmostEqual(c._y2, t._y2, places=4)


class TestTextCell(TextTestCase):
    def test_text_formula_tracks_state(self):
        bag = State(name="hud_bag")
        bag.score = 3
        hud = self.track(Text(text="", top_left=(20, 100), font_size=16))
        self.assertIsInstance(hud.text, Attribute)

        hud["text"] @= (lambda: f"Stars {bag.score}")
        self.assertEqual(hud.value, "Stars 3")
        self.assertEqual(str(hud.text), "Stars 3")

        bag.score = 7
        self.assertEqual(hud.value, "Stars 7")

        with self.assertRaises(LinkedAttributeError):
            hud.text = "paused"
        self.assertEqual(hud.value, "Stars 7")
        hud.text.unlink()
        hud.text = "paused"
        self.assertEqual(hud.value, "paused")

    def test_cell_text_links_one_way(self):
        # ``Text(st["x"])`` is ``t["text"] @= st["x"]``: it shows the cell and
        # follows it, and a write to the text raises naming the cell. It used
        # to share the cell, so ``lab.text = "Hi"`` wrote ``st.<name>``: a
        # display that changed the game state, with the error far away.
        name = self.key("title")
        st.create(name, initial="Hello")
        attr = st._resolve_cell(name)
        lab = self.track(Text(st[name], top_left=(20, 400)))
        self.assertIsNot(lab.text, attr)
        self.assertTrue(lab["text"].is_linked)
        self.assertEqual(lab.value, "Hello")
        setattr(st, name, "Bye")
        self.assertEqual(lab.value, "Bye")
        for write in (lambda: setattr(lab, "text", "Hi"),
                      lambda: setattr(lab, "value", "Hi")):
            with self.assertRaises(LinkedAttributeError) as ctx:
                write()
            msg = str(ctx.exception)
            self.assertIn(f"st[{name!r}]", msg)
            self.assertIn(f"st.{name} = ", msg)
        self.assertEqual(attr.value, "Bye")
        lab["text"].unlink()
        lab.text = "Hi"
        self.assertEqual(lab.value, "Hi")
        self.assertEqual(attr.value, "Bye")

    def test_number_cell_shows_as_text(self):
        name = self.key("pts")
        st.create(name, initial=3)
        lab = self.track(Text(st[name], top_left=(20, 400)))
        self.assertEqual(lab.value, 3)
        setattr(st, name, 12)
        self.assertEqual(lab.value, 12)
        self.assertEqual(getattr(st, name), 12)

    def test_assignment_and_concat(self):
        lab = self.track(Text(text="ab", top_left=(20, 80), font_size=16))
        lab.text = lab.text + "c"
        self.assertEqual(lab.value, "abc")

    def test_bracket_link_unlink(self):
        st.create("hud", initial="ready")
        lab = self.track(Text(text="idle", top_left=(20, 400), font_size=16))
        self.assertFalse(lab["text"].is_linked)
        lab["text"] @= st["hud"]
        self.assertTrue(lab["text"].is_linked)
        self.assertEqual(lab.value, "ready")
        st.hud = "go"
        self.assertEqual(lab.value, "go")
        with self.assertRaises(LinkedAttributeError):
            lab.text = "clobber"
        lab["text"].unlink()
        lab.text = "plain"
        self.assertEqual(lab.value, "plain")


class TestTextPaint(TextTestCase):
    def test_background_plate(self):
        lab = self.track(Text(
            text="Hi", top_left=(20, 40), font_size=16, background="maroon",
        ))
        self.assertIsInstance(lab.background, Color)
        self.assertAlmostEqual(lab.background.alpha, 1.0)
        lab.background = None
        self.assertIsNone(lab.background)

    def test_bounds_follow_text_on_draw(self):
        import skia
        lab = self.track(Text(text="Hi", top_left=(20, 40), font_size=16))
        w0 = lab._x2 - lab._x1
        lab.text = "Hello there, much longer"
        self.assertAlmostEqual(lab._x2 - lab._x1, w0)
        lab.draw(skia.Surface(8, 8).getCanvas())
        self.assertGreater(lab._x2 - lab._x1, w0)
        # Lower-left stays put when the string grows (Label contract).
        self.assertAlmostEqual(lab._x1, 20.0)

    def test_color_sets_fill_only(self):
        t = self.track(Text("Hi", top_left=(20, 40), color="tomato"))
        self.assertIsNone(t.line)
        t2 = self.track(Text("Hi", top_left=(20, 20)))
        t2.set_color("cyan")
        self.assertIsNone(t2.line)
        self.assertIsInstance(t2.fill, Color)

    def test_x1_zero_is_left_edge(self):
        t = self.track(Text("AB", top_left=(0, 100), font_size=20))
        self.assertAlmostEqual(t._x1, 0.0)
        import skia
        t.draw(skia.Surface(8, 8).getCanvas())
        self.assertAlmostEqual(t._x1, 0.0)
        self.assertGreater(t._x2, 0.0)

    def test_not_in_widget_hit_list(self):
        lab = self.track(Text(text="HUD", top_left=(20, 500), font_size=18))
        self.assertIsNone(self.wm.get_widget_at(lab._x1 + 2, lab._y1 + 2))

    def test_glow_allowed_neon_cheap_raise(self):
        t = self.track(Text("GLOW", top_left=(20, 40)))
        t.glow = Glow()
        self.assertIsInstance(t.glow, Glow)
        self.assertIsNone(t.visual)
        with self.assertRaises(TypeError):
            t.visual = Neon()
        with self.assertRaises(TypeError):
            t.visual = Glow()
        t.glow = CheapGlow()
        self.assertIsInstance(t.glow, CheapGlow)
        with self.assertRaises(TypeError):
            t.shadow = True

    def test_ui_collidable_raises(self):
        t = self.track(Text("x", top_left=(10, 10)))
        with self.assertRaises(UiLayerError):
            t.collidable = True

    def test_gradient_fill_spans_full_text_width(self):
        import numpy as np
        import skia
        from scena.style import Gradient

        t = self.track(Text("ABCDEFGH", top_left=(20, 40), font_size=24))
        t.fill = Gradient("red", "white", type="linear", angle=0)
        surf = skia.Surface(400, 200)
        canvas = surf.getCanvas()
        canvas.clear(skia.Color4f(0, 0, 0, 1))
        H = 200.0
        canvas.translate(0, H)
        canvas.scale(1, -1)
        t.draw(canvas)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        x1, x2 = int(t._x1), int(t._x2)
        bg = np.array([0, 0, 0])
        diff = np.abs(px[:, x1:x2, :3].astype(int) - bg).max(axis=2)
        ys, xs = np.where(diff > 40)
        self.assertGreater(len(xs), 0, "expected visible glyphs")
        cols = sorted(set(xs))
        w = max(x2 - x1 - 1, 1)
        left_col = min(cols, key=lambda c: abs(c - int(0.12 * w)))
        right_col = min(cols, key=lambda c: abs(c - int(0.88 * w)))

        def _red_minus_green(col):
            sel = px[ys[xs == col], x1 + col, :3]
            self.assertGreater(len(sel), 0)
            med = np.median(sel, axis=0)
            return float(med[0] - med[1])

        self.assertGreater(_red_minus_green(left_col), _red_minus_green(right_col) + 8.0)

    def test_gradient_fill_angle_90_spans_full_text_height(self):
        import numpy as np
        import skia
        from scena.style import Gradient

        t = self.track(Text("Hg", top_left=(40, 60), font_size=48))
        t.fill = Gradient("dark red", "white", type="linear", angle=90)
        surf = skia.Surface(300, 250)
        canvas = surf.getCanvas()
        canvas.clear(skia.Color4f(0, 0, 0, 1))
        canvas.translate(0, 250.0)
        canvas.scale(1, -1)
        t.draw(canvas)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        x1, x2 = int(t._x1), int(t._x2)
        bg = np.array([0, 0, 0])
        diff = np.abs(px[:, x1:x2, :3].astype(int) - bg).max(axis=2)
        ys, xs = np.where(diff > 40)
        self.assertGreater(len(ys), 0, "expected visible glyphs")
        mx = int(np.median(xs))
        y_ink = sorted(set(int(y) for y in ys[xs == mx]))
        self.assertGreater(len(y_ink), 4)
        # Image y grows downward; smaller y = visual top (should be whiter).
        top_y, bot_y = y_ink[1], y_ink[-2]

        def _whiteness(row):
            rgb = px[row, x1 + mx, :3].astype(float)
            return float(rgb[1] + rgb[2])  # G+B rises toward white

        self.assertGreater(_whiteness(top_y), _whiteness(bot_y) + 15.0)

    def test_plain_box_uses_font_metrics(self):
        from scena.uiwidget import measure_text, text_line_height
        t = self.track(Text("BOXED", top_left=(20, 40), font_size=26))
        self.assertAlmostEqual(t._y2 - t._y1, text_line_height(t._skia_font), places=3)
        self.assertAlmostEqual(t._x2 - t._x1, measure_text(t._skia_font, "BOXED"), places=3)

    def test_gradient_box_matches_tight_glyphs(self):
        from scena.style import Gradient
        from scena.uiwidget import build_upright_text_path
        t = self.track(Text("BOXED", top_left=(20, 40), font_size=26))
        t.fill = Gradient("red", "white")
        t._refresh_layout()
        path = build_upright_text_path("BOXED", 0.0, 0.0, t._skia_font)
        b = path.computeTightBounds()
        self.assertAlmostEqual(t._y2 - t._y1, float(b.height()), places=3)
        self.assertAlmostEqual(t._x2 - t._x1, float(b.width()), places=3)

    def test_glow_draws_visible_halo(self):
        import numpy as np
        import skia

        t = self.track(Text("GLOW", top_left=(40, 80), font_size=48, color="cyan"))
        t.glow = Glow()
        self.assertIsNone(t.fill_filter)  # Text uses filterless ADD underlay
        surf = skia.Surface(400, 300)
        canvas = surf.getCanvas()
        canvas.clear(skia.Color4f(0, 0, 0, 1))
        canvas.translate(0, 300.0)
        canvas.scale(1, -1)
        t.draw(canvas)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r, g, bch = px[:, :, 0], px[:, :, 1], px[:, :, 2]
        cyan = (g > 150) & (bch > 150) & (r < 80)
        # Default Glow tint is warm (1, 0.95, 0.65); ADD halo is modest.
        warm = (r > 25) & (g > 20) & (bch < r) & ~cyan
        self.assertGreater(int(cyan.sum()), 200)
        self.assertGreater(int(warm.sum()), 80)

    def test_cheapglow_caption_matches_glow(self):
        import skia

        def _snap(look):
            t = self.track(Text("GLOW", top_left=(40, 80), font_size=48, color="cyan"))
            t.glow = look
            surf = skia.Surface(400, 300)
            canvas = surf.getCanvas()
            canvas.clear(skia.Color4f(0, 0, 0, 1))
            canvas.translate(0, 300.0)
            canvas.scale(1, -1)
            t.draw(canvas)
            return surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)

        a = _snap(Glow())
        b = _snap(CheapGlow())
        self.assertEqual(a.shape, b.shape)
        self.assertLess(abs(int(a.sum()) - int(b.sum())), 80)

    def test_world_text_domain_aabb_for_glow_batch(self):
        from scena.canvas import _approx_draw_aabb
        t = self.track(Text("GLOW WORLD", center=(300, 420), font_size=36))
        box = _approx_draw_aabb(t)
        self.assertIsNotNone(box)
        self.assertAlmostEqual(box[0], t._x1)
        self.assertAlmostEqual(box[1], t._y1)
        self.assertAlmostEqual(box[2], t._x2)
        self.assertAlmostEqual(box[3], t._y2)
        # Must not fall back to origin-sized batch rect.
        self.assertGreater(box[0], 50.0)
        self.assertGreater(box[1], 300.0)

    def test_glow_aabb_pad_is_modest(self):
        t = self.track(Text("GLOW WORLD", center=(300, 420), font_size=36))
        t.glow = Glow()
        box = t._domain_aabb()
        pad = t._x1 - box[0]
        self.assertGreater(pad, 1.0)
        # Filterless ADD stroke, not GlowFilter batch_outset (~40 px).
        self.assertLess(pad, 12.0)

    def test_cheapglow_caption_uses_glow_stroke_ladder(self):
        t = self.track(Text("GLOW WORLD", center=(300, 420), font_size=36))
        t.glow = CheapGlow()
        box = t._domain_aabb()
        pad = t._x1 - box[0]
        self.assertGreater(pad, 1.0)
        # Same modest caption stroke pad as Glow — not scaled-copy inflation.
        self.assertLess(pad, 12.0)
        g = self.track(Text("GLOW WORLD", center=(300, 200), font_size=36))
        g.glow = Glow()
        glow_pad = g._x1 - g._domain_aabb()[0]
        self.assertAlmostEqual(pad, glow_pad, places=2)


class TestTextAlignWidth(TextTestCase):
    def test_top_right_pin_stays_as_string_grows(self):
        import skia
        pin = 400.0
        t = self.track(Text("9", top_right=(pin, 100), font_size=20))
        self.assertEqual(t.align, "right")
        self.assertAlmostEqual(t._x2, pin)
        t.text = "9999"
        t.draw(skia.Surface(8, 8).getCanvas())
        self.assertAlmostEqual(t._x2, pin)
        self.assertLess(t._x1, pin)

    def test_top_center_pin_stays_as_string_grows(self):
        import skia
        pin = 300.0
        t = self.track(Text("A", top_center=(pin, 100), font_size=20))
        self.assertEqual(t.align, "center")
        mid0 = 0.5 * (t._x1 + t._x2)
        self.assertAlmostEqual(mid0, pin)
        t.text = "ABCDEFGH"
        t.draw(skia.Surface(8, 8).getCanvas())
        mid1 = 0.5 * (t._x1 + t._x2)
        self.assertAlmostEqual(mid1, pin)

    def test_fixed_width_hud_does_not_shrink(self):
        import skia
        t = self.track(Text(
            "HELLO WORLD", top_left=(20, 80), font_size=20, width=200, align="left",
        ))
        self.assertAlmostEqual(t._x2 - t._x1, 200.0)
        t.text = "Hi"
        t.draw(skia.Surface(8, 8).getCanvas())
        self.assertAlmostEqual(t._x2 - t._x1, 200.0)
        self.assertAlmostEqual(t._x1, 20.0)

    def test_fixed_width_world_center_stable(self):
        import skia
        t = self.track(Text(
            "HP 100/100", center=(400, 300), font_size=22, width=120, align="center",
        ))
        cx0, cy0 = float(t.center.x), float(t.center.y)
        self.assertAlmostEqual(t._x2 - t._x1, 120.0)
        t.text = "HP 0/100"
        t.draw(skia.Surface(8, 8).getCanvas())
        self.assertAlmostEqual(float(t.center.x), cx0)
        self.assertAlmostEqual(float(t.center.y), cy0)
        self.assertAlmostEqual(t._x2 - t._x1, 120.0)

    def test_world_align_left_without_width_is_legal(self):
        # align places each line inside the box (the widest line without
        # width=); a single line has nothing to justify, formula text may
        # gain lines later — so it is never an error.
        t = self.track(Text("x", center=(100, 100), align="left"))
        self.assertEqual(t.align, "left")
        self.assertAlmostEqual(float(t.center.x), 100.0)

    def test_world_align_center_without_width_ok(self):
        t = self.track(Text("HP", center=(100, 200), align="center"))
        self.assertEqual(t.align, "center")
        self.assertIsNone(t.width)

    def test_world_default_align_is_center(self):
        t = self.track(Text("HP", center=(50, 50)))
        self.assertEqual(t.align, "center")

    def test_overflow_aabb_stays_at_width(self):
        import skia
        t = self.track(Text(
            "ABCDEFGHIJKLMNOP",
            top_left=(40, 60),
            font_size=28,
            width=50,
            align="left",
            color="white",
        ))
        t.draw(skia.Surface(8, 8).getCanvas())
        self.assertAlmostEqual(t._x2 - t._x1, 50.0)

    def test_invalid_align_raises(self):
        with self.assertRaises(TypeError):
            Text("x", top_left=(10, 10), align="justify")

    def test_nonpositive_width_raises(self):
        with self.assertRaises(ValueError):
            Text("x", top_left=(10, 10), width=0)
        with self.assertRaises(ValueError):
            Text("x", top_left=(10, 10), width=-5)

    def test_xpos_enum_accepted(self):
        from scena.shapes import XPos
        t = self.track(Text("Hi", top_right=(200, 40), align=XPos.RIGHT, font_size=16))
        self.assertEqual(t.align, "right")
        self.assertAlmostEqual(t._x2, 200.0)

    def test_assign_align_never_moves_the_box(self):
        for kw in ({"center": (100, 100)}, {"top_right": (300, 300)}):
            with self.subTest(**{"placement": next(iter(kw))}):
                t = self.track(Text("HP", **kw))
                t._refresh_layout()
                box = (t._x1, t._y1, t._x2, t._y2)
                for a in ("left", "right", "center"):
                    t.align = a
                    t._refresh_layout()
                    self.assertEqual((t._x1, t._y1, t._x2, t._y2), box)

    def test_assign_width_then_align_on_world(self):
        t = self.track(Text("HP", center=(100, 100), width=80))
        t.align = "left"
        self.assertEqual(t.align, "left")
        self.assertAlmostEqual(t._x2 - t._x1, 80.0)


class TestTextThemeFont(TextTestCase):
    def test_default_font_follows_ui_scale(self):
        lab = self.track(Text(text="Hi", top_left=(20, 40)))
        self.assertAlmostEqual(lab.font_size, 13.0)
        ui.scale = 2.0
        lab2 = self.track(Text(text="Hi", top_left=(20, 20)))
        self.assertAlmostEqual(lab2.font_size, 26.0)
        sized = self.track(Text(text="Hi", top_left=(20, 10), font_size=16))
        self.assertAlmostEqual(sized.font_size, 16.0)


class TestTextWorldVsUi(TextTestCase):
    def test_ui_stays_after_pan_in_hit(self):
        from scena.orchestration import ShapeInteractionManager
        from scena.canvas import ScenaCanvas

        t = self.track(Text("UI", top_left=(200, 300), font_size=20))
        t.clickable = True
        canvas.pan_by(80, 40)
        sim = ShapeInteractionManager(ScenaCanvas.get_current().registry)
        cx = 0.5 * (t._x1 + t._x2)
        cy = 0.5 * (t._y1 + t._y2)
        hit = sim.hit_test_ui(cx, cy, pressable=True)
        self.assertIs(hit, t)


class TestTextReactivePose(TextTestCase):
    def test_rotation_and_scale_are_linkable(self):
        t = self.track(Text("HP", center=(100, 200)))
        heading = Attribute(25.0)
        t["angle"] @= heading
        self.assertTrue(t["angle"].is_linked)
        self.assertAlmostEqual(t.angle, 25.0)
        heading.value = 80.0
        self.assertAlmostEqual(t.angle, 80.0)
        t["angle"].unlink()
        zoom = Attribute(1.0)
        t["scale"] @= zoom
        zoom.value = 1.5
        self.assertAlmostEqual(t.scale, 1.5)


from tests.font_support import system_font_file  # noqa: E402

# A monospace face installed with the OS (Courier New / DejaVu Sans Mono / …).
_FONT = system_font_file()


class TestFontSpec(TextTestCase):
    def _need_font(self):
        if _FONT is None:
            self.skipTest("no system .ttf found (tests/font_support.py)")

    def test_file_font_changes_width_and_reassign_restores(self):
        self._need_font()
        plain = self.track(Text("MMMM", top_left=(20, 400)))
        w0 = plain._x2 - plain._x1
        fancy = self.track(Text("MMMM", top_left=(20, 360), font=_FONT))
        self.assertEqual(fancy.font, _FONT)
        self.assertNotAlmostEqual(fancy._x2 - fancy._x1, w0, places=2)
        fancy.font = None
        self.assertIsNone(fancy.font)
        self.assertAlmostEqual(fancy._x2 - fancy._x1, w0, places=2)

    def test_missing_file_warns_and_keeps_spec(self):
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            caption = self.track(Text("Hi", font="no-such-font-scena.ttf", top_left=(10, 200)))
        self.assertTrue(any("no-such-font-scena.ttf" in str(w.message) for w in caught))
        self.assertEqual(caption.font, "no-such-font-scena.ttf")
        self.assertIsInstance(caption.font, str)

    def test_ui_font_file_reaches_widgets(self):
        self._need_font()
        import skia
        want = skia.Typeface.MakeFromFile(_FONT).getFamilyName()
        ui.font = _FONT
        try:
            self.wm.widget_theme._ensure()
            self.assertEqual(self.wm.widget_theme.typeface.getFamilyName(), want)
        finally:
            ui.font = None


class TestTextHardBreaks(TextTestCase):
    """Explicit ``\\n`` / ``\\r`` are hard rows. ``width=`` still clips; no wrap."""

    def _line_h(self, t):
        from scena.uiwidget import text_line_height
        return text_line_height(t._skia_font)

    def _widths(self, t, *lines):
        from scena.uiwidget import measure_text
        return [measure_text(t._skia_font, line) for line in lines]

    def test_newline_is_two_metric_rows(self):
        t = self.track(Text("aa\nb", top_left=(20, 40), font_size=26))
        wa, wb = self._widths(t, "aa", "b")
        self.assertGreater(wa, wb)
        self.assertAlmostEqual(t._y2 - t._y1, 2 * self._line_h(t), places=3)
        self.assertAlmostEqual(t._x2 - t._x1, max(wa, wb), places=3)

    def test_crlf_and_cr_match_lf(self):
        lf = self.track(Text("\n", top_left=(20, 200), font_size=20))
        crlf = self.track(Text("\r\n", top_left=(20, 160), font_size=20))
        cr = self.track(Text("\r", top_left=(20, 120), font_size=20))
        h = 2 * self._line_h(lf)
        for t in (lf, crlf, cr):
            self.assertAlmostEqual(t._y2 - t._y1, h, places=3)
            self.assertAlmostEqual(t._x2 - t._x1, 0.0, places=3)

    def test_trailing_break_is_a_blank_row_empty_string_is_one(self):
        blank = self.track(Text("", top_left=(20, 80), font_size=20))
        trail = self.track(Text("a\n", top_left=(20, 40), font_size=20))
        self.assertAlmostEqual(blank._y2 - blank._y1, self._line_h(blank), places=3)
        self.assertAlmostEqual(trail._y2 - trail._y1, 2 * self._line_h(trail), places=3)
        wa, = self._widths(trail, "a")
        self.assertAlmostEqual(trail._x2 - trail._x1, wa, places=3)

    def test_width_clips_each_line_and_does_not_wrap(self):
        t = self.track(Text(
            "WWWWWW\nI", top_left=(20, 40), font_size=24, width=10, align="left",
        ))
        self.assertAlmostEqual(t._x2 - t._x1, 10.0, places=3)
        self.assertAlmostEqual(t._y2 - t._y1, 2 * self._line_h(t), places=3)

    def test_hud_stack_uses_construct_time_row_count(self):
        ui.stack_reset()
        t = self.track(Text("A\nB", font_size=16))
        b = self.track(Button(label="Go"))
        self.wm.widget_theme._ensure()
        gap = self.wm.widget_theme.stack_gap
        self.assertAlmostEqual(t._y2 - t._y1, 2 * self._line_h(t), places=3)
        self.assertAlmostEqual(b._y2, t._y1 - gap, places=4)

    def test_world_center_stays_the_box_center(self):
        t = self.track(Text("A\nB", center=(100, 200), font_size=16))
        self.assertAlmostEqual(t._y2 - t._y1, 2 * self._line_h(t), places=3)
        self.assertAlmostEqual(0.5 * (t._y1 + t._y2), 200.0, places=3)
        self.assertAlmostEqual(float(t.center.y), 200.0, places=3)
        self.assertAlmostEqual(float(t.center.x), 100.0, places=3)

    def test_later_line_count_does_not_reflow_the_column(self):
        import skia
        ui.stack_reset()
        t = self.track(Text("A", top_left=(20, 300), font_size=16))
        b = self.track(Button(label="Go"))
        top = t._y2
        b_y2 = b._y2
        t.text = "A\nB"
        t.draw(skia.Surface(8, 8).getCanvas())
        # The anchor is the top: a new line grows the box downward.
        self.assertAlmostEqual(t._y2, top, places=3)
        self.assertAlmostEqual(t._y2, 300.0, places=3)
        self.assertAlmostEqual(t._y2 - t._y1, 2 * self._line_h(t), places=3)
        self.assertAlmostEqual(b._y2, b_y2, places=3)

    def test_gradient_box_stays_line_metrics(self):
        from scena.style import Gradient
        t = self.track(Text("A\nB", top_left=(20, 40), font_size=26))
        t.fill = Gradient("red", "white")
        t._refresh_layout()
        self.assertAlmostEqual(t._y2 - t._y1, 2 * self._line_h(t), places=3)
        wa, wb = self._widths(t, "A", "B")
        self.assertAlmostEqual(t._x2 - t._x1, max(wa, wb), places=3)

    def test_flash_uses_break_count_then_restores(self):
        import skia
        from scena import transients as tx
        clock = {"t": 100.0}
        tx.set_now_fn(lambda: clock["t"])
        try:
            for shape in list(tx._active_shapes):
                tx.clear_transients(shape)
            t = self.track(Text("Hi", top_left=(20, 80), font_size=20))
            line_h = self._line_h(t)
            t.draw(skia.Surface(8, 8).getCanvas())
            h0 = t._y2 - t._y1
            self.assertAlmostEqual(h0, line_h, places=3)
            t.flash_text("X\nY", duration=0.5)
            t._tx_state.text.t0 = clock["t"]
            t.draw(skia.Surface(8, 8).getCanvas())
            self.assertEqual(t.value, "Hi")
            self.assertAlmostEqual(t._y2 - t._y1, 2 * line_h, places=3)
            clock["t"] += 0.6
            tx.tick_all_transients(clock["t"])
            t.draw(skia.Surface(8, 8).getCanvas())
            self.assertEqual(t._displayed_text(), "Hi")
            self.assertAlmostEqual(t._y2 - t._y1, h0, places=3)
        finally:
            for shape in list(tx._active_shapes):
                tx.clear_transients(shape)
            tx.set_now_fn(None)

    def _ink_columns(self, t, band):
        import numpy as np
        import skia
        W, H = 600, 400
        surf = skia.Surface(W, H)
        canvas = surf.getCanvas()
        canvas.clear(skia.Color4f(0, 0, 0, 1))
        canvas.translate(0, float(H))
        canvas.scale(1, -1)
        t.draw(canvas)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        x1 = max(0, int(t._x1))
        x2 = min(W, int(t._x2))
        row_top = max(0, int(round(H - t._y2)))
        row_bot = min(H, int(round(H - t._y1)))
        mid = (row_top + row_bot) // 2
        rows = px[row_top:mid] if band == "top" else px[mid:row_bot]
        if rows.size == 0 or x2 <= x1:
            return []
        diff = np.abs(rows[:, x1:x2, :3].astype(int) - 0).max(axis=2)
        _ys, xs = np.where(diff > 40)
        return list(xs)

    def test_align_places_each_line(self):
        # Short second row must sit on the named edge of the wide first row,
        # whichever point anchors the block (align never moves the anchor):
        # e.g. a top-right block of left-justified lines.
        cases = [
            (anchor, align)
            for anchor in ("top_left", "top_center", "top_right")
            for align in ("left", "right", "center")
        ]
        for anchor, align in cases:
            side = align
            with self.subTest(anchor=anchor, align=align):
                t = self.track(Text(
                    "WWW\nI", font_size=48, align=align, color="white",
                    **{anchor: (300, 200)},
                ))
                t._refresh_layout()
                pinned = {
                    "top_left": t._x1,
                    "top_center": 0.5 * (t._x1 + t._x2),
                    "top_right": t._x2,
                }[anchor]
                self.assertAlmostEqual(pinned, 300.0, places=6)
                self.assertAlmostEqual(t._y2, 200.0, places=6)
                wide, narrow = self._widths(t, "WWW", "I")
                self.assertGreater(wide, narrow * 2)
                self.assertAlmostEqual(t._x2 - t._x1, wide, places=3)
                top = self._ink_columns(t, "top")
                bot = self._ink_columns(t, "bot")
                self.assertGreater(len(top), 0, "top row missing")
                self.assertGreater(len(bot), 0, "bottom row missing")
                span = max(t._x2 - t._x1, 1.0)
                bot_mid = float(sorted(bot)[len(bot) // 2]) / span
                if side == "left":
                    self.assertLess(bot_mid, 0.35)
                elif side == "right":
                    self.assertGreater(bot_mid, 0.65)
                else:
                    self.assertGreater(bot_mid, 0.35)
                    self.assertLess(bot_mid, 0.65)


_LONG = "Estrelas 0   Vidas 3"
_ALIGNS = ("left", "center", "right")
# Each align case of the pin tests uses the anchor that pins that edge.
_ALIGN_ANCHOR = {"left": "top_left", "center": "top_center", "right": "top_right"}


def _mid_x_for_pin(pin: float, align: str, w: float) -> float:
    if align == "right":
        return pin - 0.5 * w
    if align == "center":
        return pin
    return pin + 0.5 * w


def _pin_x(t) -> float:
    """x of the pinned point: left / middle / right box edge by anchor."""
    t._refresh_layout()
    if t._anchor == "top_right":
        return float(t._x2)
    if t._anchor == "top_center":
        return 0.5 * (float(t._x1) + float(t._x2))
    return float(t._x1)


class TestViewPinMotion(TextTestCase):
    """Anchored caption (``top_left=`` / ``top_center=`` / ``top_right=``):
    every pose writer translates the pin (the anchor point; y is the top).

    Regression: ``center`` stays the old string's midpoint until the next
    layout (formula text is pull), and ``_move_by`` / ``_move_to`` used to
    rebuild the box around that stale midpoint (``x1 = 16 − w/2``).
    Every case below changes the string and moves *before* any draw.
    """

    def setUp(self):
        super().setUp()
        from scena import clock
        from scena.process import reset_process_scheduler
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False

    def tearDown(self):
        from scena.process import reset_process_scheduler
        reset_process_scheduler()
        super().tearDown()

    def make(self, align="left", text=_LONG):
        anchor = {_ALIGN_ANCHOR[align]: (300, 300)}
        t = self.track(Text(text="", align=align, font_size=18, **anchor))
        t.text = text  # no layout yet: center is the empty string's point
        return t

    def run_frames(self, n, dt=1.0 / 60.0):
        from scena import clock
        from scena.process import tick_processes
        for _ in range(n):
            clock.advance(dt)
            tick_processes()

    def fresh_mid(self, t, pin_x, pin_y):
        box_w, h, _ = t._layout_box_size()
        return _mid_x_for_pin(pin_x, t.align, box_w), pin_y - 0.5 * h

    def assert_pin(self, t, align, pin_x, pin_y):
        t._refresh_layout()
        self.assertEqual(t.align, align)
        self.assertAlmostEqual(_pin_x(t), pin_x, places=6)
        self.assertAlmostEqual(float(t._y2), pin_y, places=6)
        box_w, h, _ = t._layout_box_size()
        self.assertAlmostEqual(float(t._x2 - t._x1), box_w, places=6)
        self.assertAlmostEqual(float(t.center.x), 0.5 * (t._x1 + t._x2), places=9)
        self.assertAlmostEqual(float(t.center.y), 0.5 * (t._y1 + t._y2), places=9)

    def test_platformer_repro_forever_zero_move_keeps_left_pin(self):
        st.tp_estrelas = 0
        t = self.track(Text(text="", top_left=(16, 560), font_size=18))
        t["text"] @= lambda: f"Estrelas {st.tp_estrelas}   Vidas 3"
        t.move_by(0, 0, loops="forever", time=2.0)
        self.run_frames(30)
        self.assert_pin(t, "left", 16.0, 560.0)
        self.assertAlmostEqual(float(t._x1), 16.0, places=6)

    def test_instant_move_by(self):
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                t.move_by(0, 0)
                self.assert_pin(t, align, 300.0, 300.0)
                t = self.make(align)
                t.move_by(40, -10)
                self.assert_pin(t, align, 340.0, 290.0)

    def test_instant_move_to_is_midpoint_of_current_string(self):
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                mx, my = self.fresh_mid(t, 300.0, 300.0)
                t.move_to(mx, my)
                self.assert_pin(t, align, 300.0, 300.0)
                t = self.make(align)
                t.move_to(mx + 25, my + 5)
                self.assert_pin(t, align, 325.0, 305.0)

    def test_timed_move_by_probe_and_end(self):
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                t.move_by(60, 0, time=1.0)
                self.assert_pin(t, align, 300.0, 300.0)  # up-front probe
                self.run_frames(1)
                t._refresh_layout()
                self.assertGreater(_pin_x(t), 300.0)
                self.run_frames(70)
                self.assert_pin(t, align, 360.0, 300.0)

    def test_timed_move_to_reads_fresh_pivot(self):
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                mx, my = self.fresh_mid(t, 300.0, 300.0)
                t.move_to(mx + 30, my, time=0.5)
                self.assert_pin(t, align, 300.0, 300.0)  # probe: no jump
                self.run_frames(40)
                self.assert_pin(t, align, 330.0, 300.0)

    def test_move_along_first_step_starts_from_current_string(self):
        from scena.shapes import Line
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                mx, my = self.fresh_mid(t, 300.0, 300.0)
                line = self.track(Line(p1=(mx + 50, my), p2=(mx + 250, my)))
                t.move_along(line, time=1.0)
                self.assert_pin(t, align, 350.0, 300.0)

    def test_confine_reads_fresh_center(self):
        from scena import Box
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                mx, my = self.fresh_mid(t, 300.0, 300.0)
                # Right edge 50 left of the fresh midpoint: clamp by -50.
                region = Box(center=(mx - 100, my), width=100, height=1000)
                t.confine(region)
                self.assert_pin(t, align, 250.0, 300.0)

    def test_center_write_is_translation_stale_and_fresh(self):
        for align in _ALIGNS:
            for fresh in (False, True):
                with self.subTest(align=align, fresh=fresh):
                    t = self.make(align)
                    if fresh:
                        t._refresh_layout()
                    t.center.x = float(t.center.x) + 7
                    x1, _y1, x2, _y2 = t._domain_aabb()  # cull box follows
                    self.assert_pin(t, align, 307.0, 300.0)
                    self.assertAlmostEqual(x1, float(t._x1), places=6)
                    self.assertAlmostEqual(x2, float(t._x2), places=6)

    def test_center_write_survives_later_string_change(self):
        """Old bug: a center-only write snapped back on the next width change."""
        t = self.make("left")
        t._refresh_layout()
        t.center.x = float(t.center.x) + 100
        t._refresh_layout()
        t.text = "curto"
        self.assert_pin(t, "left", 400.0, 300.0)

    def test_absolute_center_assign_on_stale_caption(self):
        """``center = P`` means the midpoint of the string showing now.

        Regression from implementation: the reconcile alone read a stale
        absolute write as a translation from the old string's midpoint.
        """
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                mx, my = self.fresh_mid(t, 300.0, 300.0)
                t.center = (mx + 30, my - 4)
                self.assert_pin(t, align, 330.0, 296.0)

    def test_center_read_is_current_string_midpoint(self):
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                mx, my = self.fresh_mid(t, 300.0, 300.0)
                self.assertAlmostEqual(float(t.center.x), mx, places=6)
                self.assertAlmostEqual(float(t.center.y), my, places=6)

    def test_tween_on_center_moves_pin(self):
        from scena import tween
        for align in _ALIGNS:
            with self.subTest(align=align):
                t = self.make(align)
                mx, my = self.fresh_mid(t, 300.0, 300.0)
                tween(t.center, (mx + 30, my), time=0.2)
                self.run_frames(20)
                self.assert_pin(t, align, 330.0, 300.0)

    def test_formula_growing_between_moves(self):
        for align in _ALIGNS:
            with self.subTest(align=align):
                st.tp_n = 0
                t = self.track(Text(text="", top_left=(300, 300), align=align, font_size=18))
                t["text"] @= lambda: "n" * (st.tp_n + 1)
                t.move_by(10, 0)
                st.tp_n = 20
                t.move_by(10, 0)
                self.assert_pin(t, align, 320.0, 300.0)

    def test_formula_change_without_motion_keeps_pin(self):
        st.tp_m = 0
        t = self.track(Text(text="", top_left=(300, 300), font_size=18))
        t["text"] @= lambda: "m" * (st.tp_m + 1)
        t._refresh_layout()
        c0 = float(t.center.x)
        st.tp_m = 30
        self.assert_pin(t, "left", 300.0, 300.0)
        self.assertGreater(float(t.center.x), c0)

    def test_align_and_width_setters_keep_pending_center_move(self):
        t = self.make("left")
        t.center.x = float(t.center.x) + 7
        t.align = "center"  # pin coordinate kept, now the middle
        self.assert_pin(t, "center", 307.0, 300.0)
        t = self.make("left")
        t.center.x = float(t.center.x) + 7
        t.width = 400
        self.assert_pin(t, "left", 307.0, 300.0)

    def test_clone_rehomes_on_current_string_midpoint(self):
        t = self.make("left")
        mx, my = self.fresh_mid(t, 300.0, 300.0)
        c = self.track(t.clone())
        self.assertAlmostEqual(float(c.center.x), mx, places=6)
        self.assertAlmostEqual(float(c.center.y), my, places=6)

    def test_world_caption_still_grows_around_center(self):
        t = self.track(Text("hi", center=(200, 200), font_size=18))
        t.text = _LONG
        t.move_by(10, 0)
        t._refresh_layout()
        self.assertAlmostEqual(float(t.center.x), 210.0, places=6)
        self.assertAlmostEqual(0.5 * (t._x1 + t._x2), 210.0, places=6)
        box_w, _, _ = t._layout_box_size()
        self.assertAlmostEqual(float(t._x2 - t._x1), box_w, places=6)


class TestViewPinMotionProperty(TextTestCase):
    """Bug class: the anchor drifts on re-layout.

    Any interleaving of string changes (incl. hard breaks), ``width`` /
    ``align`` / ``font_size`` writes, layouts, pose writes and absolute anchor
    writes leaves the anchored point exactly at start + the sum of requested
    translations, the box growing away from it (top stays, x edge by anchor),
    and every part reading the current box.
    """

    def test_pin_is_start_plus_sum_of_translations(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hypothesis_support  # noqa: F401  (loads the shared profiles)
        from hypothesis import given, strategies as hst

        delta = hst.integers(min_value=-200, max_value=200).map(float)
        op = hst.one_of(
            hst.tuples(hst.just("text"), hst.integers(min_value=0, max_value=40)),
            hst.tuples(
                hst.just("lines"),
                hst.lists(hst.integers(min_value=0, max_value=12), min_size=1, max_size=4),
            ),
            hst.tuples(hst.just("by"), delta, delta),
            hst.tuples(hst.just("to"), delta, delta),
            hst.tuples(hst.just("center"), delta, delta),
            hst.tuples(hst.just("center_to"), delta, delta),
            hst.tuples(hst.just("anchor"), delta, delta),
            hst.tuples(hst.just("width"), hst.one_of(
                hst.none(), hst.integers(min_value=20, max_value=300).map(float))),
            hst.tuples(hst.just("align"), hst.sampled_from(_ALIGNS)),
            hst.tuples(hst.just("font"), hst.integers(min_value=8, max_value=40).map(float)),
            hst.tuples(hst.just("layout")),
        )

        @given(
            anchor=hst.sampled_from(("top_left", "top_center", "top_right")),
            ops=hst.lists(op, max_size=25),
        )
        def check(anchor, ops):
            t = Text(text="", font_size=18, **{anchor: (300, 300)})
            align_of = {"top_left": "left", "top_center": "center", "top_right": "right"}
            try:
                px, py = 300.0, 300.0
                for o in ops:
                    kind = o[0]
                    if kind == "text":
                        t.text = "W" * o[1]
                    elif kind == "lines":
                        t.text = "\n".join("W" * k for k in o[1])
                    elif kind == "by":
                        t.move_by(o[1], o[2])
                        px, py = px + o[1], py + o[2]
                    elif kind == "to":
                        cx, cy = t._center_xy()
                        t.move_to(cx + o[1], cy + o[2])
                        px, py = px + o[1], py + o[2]
                    elif kind == "center":
                        t.center.x = float(t.center.x) + o[1]
                        t.center.y = float(t.center.y) + o[2]
                        px, py = px + o[1], py + o[2]
                    elif kind == "center_to":
                        # Absolute write of a point computed from a fresh read.
                        box_w, h, _ = t._layout_box_size()
                        mx = _mid_x_for_pin(px, align_of[anchor], box_w) + o[1]
                        my = py - 0.5 * h + o[2]
                        t.center = (mx, my)
                        px, py = px + o[1], py + o[2]
                    elif kind == "anchor":
                        setattr(t, anchor, (px + o[1], py + o[2]))
                        px, py = px + o[1], py + o[2]
                    elif kind == "width":
                        t.width = o[1]
                    elif kind == "align":
                        t.align = o[1]
                    elif kind == "font":
                        t.font_size = o[1]
                    else:
                        t._refresh_layout()
                t._refresh_layout()
                self.assertAlmostEqual(_pin_x(t), px, places=6)
                self.assertAlmostEqual(float(t._y2), py, places=6)
                box_w, h, _ = t._layout_box_size()
                self.assertAlmostEqual(float(t._x2 - t._x1), box_w, places=6)
                self.assertAlmostEqual(float(t._y2 - t._y1), h, places=6)
                part = getattr(t, anchor)
                self.assertAlmostEqual(float(part.x), px, places=6)
                self.assertAlmostEqual(float(part.y), py, places=6)
                self.assertAlmostEqual(
                    float(t.center.x), 0.5 * (t._x1 + t._x2), places=9,
                )
                self.assertAlmostEqual(
                    float(t.center.y), 0.5 * (t._y1 + t._y2), places=9,
                )
                self.assertAlmostEqual(float(t.top_right.x), float(t._x2), places=9)
                self.assertAlmostEqual(float(t.top_left.x), float(t._x1), places=9)
            finally:
                t.destroy()

        check()

    def test_linked_anchor_tracks_its_source(self):
        """Same class for a linked anchor: the box follows the source."""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hypothesis_support  # noqa: F401
        from hypothesis import given, strategies as hst
        from scena import Point

        delta = hst.integers(min_value=-200, max_value=200).map(float)
        op = hst.one_of(
            hst.tuples(hst.just("src"), delta, delta),
            hst.tuples(
                hst.just("lines"),
                hst.lists(hst.integers(min_value=0, max_value=12), min_size=1, max_size=4),
            ),
            hst.tuples(hst.just("width"), hst.one_of(
                hst.none(), hst.integers(min_value=20, max_value=300).map(float))),
            hst.tuples(hst.just("align"), hst.sampled_from(_ALIGNS)),
            hst.tuples(hst.just("font"), hst.integers(min_value=8, max_value=40).map(float)),
            hst.tuples(hst.just("layout")),
        )

        @given(
            anchor=hst.sampled_from(("top_left", "top_center", "top_right")),
            ops=hst.lists(op, max_size=20),
        )
        def check(anchor, ops):
            src = Point(300, 300)
            t = Text(text="x", font_size=18, **{anchor: lambda: src})
            try:
                for o in ops:
                    kind = o[0]
                    if kind == "src":
                        src.move_by(o[1], o[2])
                    elif kind == "lines":
                        t.text = "\n".join("W" * k for k in o[1])
                    elif kind == "width":
                        t.width = o[1]
                    elif kind == "align":
                        t.align = o[1]
                    elif kind == "font":
                        t.font_size = o[1]
                    else:
                        t._refresh_layout()
                sx, sy = float(src.x), float(src.y)
                self.assertAlmostEqual(_pin_x(t), sx, places=6)
                self.assertAlmostEqual(float(t._y2), sy, places=6)
                self.assertAlmostEqual(float(t.center.x), 0.5 * (t._x1 + t._x2), places=9)
            finally:
                t.destroy()
                src.destroy()

        check()


def _xy(point):
    return (float(point.x), float(point.y))


class TestTextAnchors(TextTestCase):
    """Placement is one point; the string grows away from it."""

    def test_each_anchor_pins_its_point(self):
        expect = {
            "top_left": lambda t: (t._x1, t._y2),
            "top_center": lambda t: (0.5 * (t._x1 + t._x2), t._y2),
            "top_right": lambda t: (t._x2, t._y2),
        }
        for anchor, pinned in expect.items():
            with self.subTest(anchor=anchor):
                t = self.track(Text("Score 0", font_size=20, **{anchor: (400, 500)}))
                t._refresh_layout()
                self.assertEqual(pinned(t), (400.0, 500.0))
                self.assertEqual(_xy(getattr(t, anchor)), (400.0, 500.0))
                self.assertEqual(t.align, _ALIGN_ANCHOR_INV[anchor])

    def test_growth_is_downward_and_away_from_the_anchor(self):
        """Regression: the tutorial score near the top gained a line and its
        first line was pushed off the top of the screen (y1 was the bottom)."""
        t = self.track(Text("Estrelas 0", top_left=(20, 780), font_size=20))
        _, h1, _ = t._layout_box_size()
        t.text = "Estrelas 0\nVidas 3"
        t._refresh_layout()
        self.assertAlmostEqual(t._y2, 780.0)
        self.assertAlmostEqual(t._y2 - t._y1, 2 * h1, places=3)
        t.font_size = 40
        t._refresh_layout()
        self.assertAlmostEqual(t._y2, 780.0)
        self.assertAlmostEqual(t._x1, 20.0)
        r = self.track(Text("9", top_right=(980, 780), font_size=20))
        r.text = "99999"
        r._refresh_layout()
        self.assertAlmostEqual(r._x2, 980.0)
        self.assertAlmostEqual(r._y2, 780.0)

    def test_every_anchor_align_width_combination_is_legal(self):
        for anchor in ("top_left", "top_center", "top_right"):
            for align in ("left", "center", "right"):
                for width in (None, 200):
                    with self.subTest(anchor=anchor, align=align, width=width):
                        t = self.track(Text(
                            "A\nlonger line", align=align, width=width,
                            **{anchor: (300, 300)},
                        ))
                        self.assertEqual(_xy(getattr(t, anchor)), (300.0, 300.0))
                        if width is not None:
                            self.assertAlmostEqual(t._x2 - t._x1, 200.0)

    def test_one_anchor_and_one_point(self):
        with self.assertRaises(TypeError):
            Text("x", top_left=(1, 1), top_right=(2, 2))
        with self.assertRaises(TypeError):
            Text("x", top_center=(1, 1), center=(2, 2))
        from scena import Box
        with self.assertRaises(TypeError):
            Text("x", top_left=(1, 1), box=Box(center=(0, 0), width=10, height=10))

    def test_bad_anchor_value_raises(self):
        for bad in ("ab", object(), (1, 2, 3), (float("nan"), 0)):
            with self.subTest(bad=bad):
                with self.assertRaises((TypeError, ValueError)):
                    Text("x", top_left=bad)

    def test_world_anchor_is_a_world_caption_outside_the_column(self):
        ui.stack_reset()
        before = (self.wm._stack_x, self.wm._stack_bottom)
        t = self.track(Text("Plat", top_left=(10, 20), layer="default"))
        self.assertEqual(t.layer, "default")
        self.assertEqual(_xy(t.top_left), (10.0, 20.0))
        self.assertEqual((self.wm._stack_x, self.wm._stack_bottom), before)

    def test_world_layer_without_a_point_raises(self):
        with self.assertRaises(TypeError) as ctx:
            Text("x", layer="default")
        self.assertIn("top_left=", str(ctx.exception))

    def test_ui_anchor_advances_the_column(self):
        ui.stack_reset()
        t = self.track(Text("HUD", top_left=(40, 500), font_size=16))
        b = self.track(Button(label="Next"))
        self.assertAlmostEqual(b._x1, 40.0)
        self.assertAlmostEqual(b._y2, t._y1 - self.wm.widget_theme.stack_gap, places=4)

    def test_derived_parts_refuse_writes(self):
        from scena.state import DerivedAttributeError
        t = self.track(Text("x", top_left=(10, 10)))
        with self.assertRaises(DerivedAttributeError):
            t.top_right = (5, 5)
        c = self.track(Text("x", center=(10, 10)))
        with self.assertRaises(DerivedAttributeError):
            c.top_left = (5, 5)

    def test_parts_read_the_current_string(self):
        t = self.track(Text("a", top_left=(100, 400), font_size=20))
        x_right_short = float(t.top_right.x)
        t.text = "a much longer string"
        self.assertGreater(float(t.top_right.x), x_right_short)
        self.assertEqual(_xy(t.top_left), (100.0, 400.0))
        w = self.track(Text("a", center=(100, 100), font_size=20))
        left0 = float(w.top_left.x)
        w.text = "a much longer string"
        self.assertLess(float(w.top_left.x), left0)

    def test_box_reads_the_layout_box(self):
        t = self.track(Text("Score", top_left=(20, 300), font_size=20))
        b = t.box
        self.assertAlmostEqual(float(b.top_left.x), 20.0)
        self.assertAlmostEqual(float(b.top_left.y), 300.0)
        self.assertAlmostEqual(float(b.width), t._x2 - t._x1)

    def test_no_public_scalar_edges(self):
        """Guard: scalar box edges must not leak back into the author API."""
        t = self.track(Text("x", top_left=(1, 1)))
        w = self.track(Button(label="b"))
        for obj in (t, w):
            for name in ("x1", "y1", "x2", "y2"):
                with self.subTest(obj=type(obj).__name__, name=name):
                    self.assertFalse(hasattr(type(obj), name))
                    self.assertNotIn(name, obj.__dict__)


_ALIGN_ANCHOR_INV = {"top_left": "left", "top_center": "center", "top_right": "right"}


class TestTextAnchorLinks(TextTestCase):
    """Anchors link like Rect(top_left=): callables link, values copy."""

    def test_lambda_anchor_follows(self):
        from scena import Point
        p = Point(300, 300)
        t = self.track(Text("linked", top_left=lambda: p, font_size=16))
        p.move_by(5, -7)
        self.assertEqual(_xy(t.top_left), (305.0, 293.0))
        t._refresh_layout()
        self.assertAlmostEqual(t._x1, 305.0)
        self.assertAlmostEqual(t._y2, 293.0)

    def test_lambda_to_a_rect_part_follows_the_rect(self):
        from scena import Rect
        panel = self.track(Rect(center=(200, 200), width=100, height=60, layer="ui"))
        t = self.track(Text("Menu", top_left=lambda: panel.top_left))
        panel.move_by(30, 10)
        t._refresh_layout()
        self.assertAlmostEqual(t._x1, float(panel.top_left.x))
        self.assertAlmostEqual(t._y2, float(panel.top_left.y))

    def test_a_point_value_copies(self):
        from scena import Point
        p = Point(50, 60)
        t = self.track(Text("copy", top_left=p))
        p.move_by(10, 10)
        self.assertEqual(_xy(t.top_left), (50.0, 60.0))
        t.move_by(1, 1)   # a copy is movable

    def test_mixed_tuple_links_one_component(self):
        from scena import Point
        p = Point(100, 0)
        t = self.track(Text("x", top_left=(lambda: p.x * 2 + 10, 50)))
        self.assertEqual(_xy(t.top_left), (210.0, 50.0))
        p.move_by(5, 0)
        self.assertEqual(_xy(t.top_left), (220.0, 50.0))

    def test_linked_top_right_keeps_the_edge_as_the_string_grows(self):
        from scena import Point
        p = Point(700, 500)
        t = self.track(Text("1", top_right=lambda: p, font_size=20))
        t.text = "123456"
        t._refresh_layout()
        self.assertAlmostEqual(t._x2, 700.0)
        p.move_by(-100, 0)
        t._refresh_layout()
        self.assertAlmostEqual(t._x2, 600.0)

    def test_pose_writers_on_a_linked_anchor_raise(self):
        from scena import Point, tween
        from scena.state import DerivedAttributeError
        p = Point(300, 300)
        t = self.track(Text("x", top_left=lambda: p))
        for label, call in (
            ("move_by", lambda: t.move_by(1, 1)),
            ("move_to", lambda: t.move_to(1, 1)),
            ("draggable", lambda: setattr(t, "draggable", True)),
        ):
            with self.subTest(label):
                with self.assertRaises(LinkedAttributeError) as ctx:
                    call()
                self.assertIn("top_left", str(ctx.exception))
        for label, call in (
            ("center =", lambda: setattr(t, "center", (1, 1))),
            ("center.x =", lambda: setattr(t.center, "x", 1)),
        ):
            with self.subTest(label):
                with self.assertRaises(DerivedAttributeError):
                    call()
        t["top_left"].unlink()
        t.move_by(10, 0)
        self.assertEqual(_xy(t.top_left), (310.0, 300.0))

    def test_line_linked_to_a_caption_part_follows(self):
        from scena import Line
        score = self.track(Text("1", top_left=(100, 400), font_size=20))
        ln = self.track(Line(p1=lambda: score.top_right, p2=(0, 0)))
        score.text = "1000000"
        self.assertAlmostEqual(float(ln.p1.x), float(score.top_right.x))
        self.assertGreater(float(ln.p1.x), 110.0)

    def test_linked_anchor_advances_the_column_once(self):
        from scena import Point
        ui.stack_reset()
        p = Point(40, 500)
        t = self.track(Text("L", top_left=lambda: p, font_size=16))
        b = self.track(Button(label="after"))
        cursor = (self.wm._stack_x, self.wm._stack_bottom)
        p.move_by(0, -200)
        t._refresh_layout()
        self.assertEqual((self.wm._stack_x, self.wm._stack_bottom), cursor)
        self.assertAlmostEqual(b._x1, 40.0)


class TestTextTakesAFunction(unittest.TestCase):
    """``Text(fn)`` links, as the docstring and the constructor-links rule
    say: the same link as ``t["text"] @= fn`` (review 2026-10-09 S6-7)."""

    def test_function_argument_links(self):
        from scena import Text, st
        st.s67_n = 3
        t = Text(lambda: f"pontos {st.s67_n}", center=(0, 0))
        try:
            self.assertEqual(t.text.value, "pontos 3")
            st.s67_n = 12
            self.assertEqual(t.text.value, "pontos 12")
            self.assertIsNotNone(t.text._link)
        finally:
            t.destroy()

    def test_a_function_with_no_source_raises_and_leaves_nothing(self):
        from scena import Text
        from scena.canvas import ScenaCanvas
        reg = ScenaCanvas.get_current().registry
        before = len([o for o in reg.live_objects() if isinstance(o, Text)])
        with self.assertRaises(TypeError):
            Text(lambda: "fixo", center=(0, 0))
        after = len([o for o in reg.live_objects() if isinstance(o, Text)])
        self.assertEqual(after, before)



class TestClassKeywords(unittest.TestCase):
    """Class keywords on a Text subclass (decided 2026-10-10, after AC2 / AC15):
    the look on the class line, the content and the placement on the instance."""

    def _sub(self, name="Placar", base=None, **kw):
        return type(name, (base or Text,), {"__module__": "author_game"}, **kw)

    def test_defaults_apply_and_the_instance_wins(self):
        Placar = self._sub(font_size=32, color="gold", group="hud_ck", align="right")
        p = Placar("10", center=(100, 100))
        try:
            self.assertEqual(p.font_size, 32.0)
            self.assertTrue(p.tagged("hud_ck"))
            self.assertEqual(Placar("x", center=(0, 0), font_size=12).font_size, 12.0)
            Big = self._sub("Big", Placar, font_size=48)
            self.assertEqual(Big("y", center=(0, 0)).font_size, 48.0)
            self.assertTrue(Big("y", center=(0, 0)).tagged("hud_ck"))
        finally:
            for t in list(group["hud_ck"]):
                t.destroy()

    def test_refusals_on_the_class_line(self):
        cases = {"center": "instance placement", "top_left": "instance placement",
                 "layer": "instance placement", "text": "content",
                 "font_sise": "Did you mean 'font_size'"}
        for key, words in cases.items():
            with self.subTest(key=key):
                with self.assertRaises(TypeError) as ctx:
                    self._sub(**{key: (1, 1) if key != "font_sise" else 3})
                self.assertIn(words, str(ctx.exception))
        with self.assertRaises(TypeError):
            self._sub(font_size="big")
        with self.assertRaises(ValueError):
            self._sub(width=-3)

    def test_plain_text_is_unchanged(self):
        t = Text("a", center=(0, 0))
        try:
            self.assertEqual(Text._class_defaults, {})
            self.assertIsNotNone(t.font_size)
        finally:
            t.destroy()


if __name__ == "__main__":
    unittest.main()


class TestTextFrame(TextTestCase):
    """Text parts are the drawn frame's points (Named points; Canvas Design)."""

    def _xy(self, p):
        return (float(p.x), float(p.y))

    def _near(self, a, b, tol=1e-6):
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

    def _turned(self, p, c, deg):
        import math
        a = math.radians(deg)
        dx, dy = p[0] - c[0], p[1] - c[1]
        return (c[0] + dx * math.cos(a) - dy * math.sin(a), c[1] + dx * math.sin(a) + dy * math.cos(a))

    def test_anchors_turn_and_scale_about_the_center(self):
        for anchor in ("top_left", "top_center", "top_right"):
            with self.subTest(anchor=anchor):
                t = self.track(Text("geo", **{anchor: (40, 30)}, layer="default"))
                c = self._xy(t.center)
                parts = {n: self._xy(getattr(t, n)) for n in ("top_left", "top_center", "top_right")}
                t.rotate_by(90)
                self.assertTrue(self._near(self._xy(t.center), c))
                for n, p in parts.items():
                    self.assertTrue(self._near(self._xy(getattr(t, n)), self._turned(p, c, 90)), n)
                    self.assertTrue(self._near(self._xy(getattr(t, n)), self._xy(getattr(t.box, n))), n)

    def test_turning_about_a_pivot_moves_the_pin_rigidly(self):
        t = self.track(Text("geo", top_left=(40, 30), layer="default"))
        tl = self._xy(t.top_left)
        t.rotate_by(90, about=(0, 0))
        self.assertTrue(self._near(self._xy(t.top_left), self._turned(tl, (0, 0), 90)))
        t.scale_by(2, about=(0, 0))
        want = self._turned(tl, (0, 0), 90)
        self.assertTrue(self._near(self._xy(t.top_left), (2 * want[0], 2 * want[1])))

    def test_hud_caption_is_unchanged(self):
        t = self.track(Text("score", top_left=(10, 580)))
        self.assertTrue(self._near(self._xy(t.top_left), (10, 580)))

    def test_scale_zero_then_one_restores_the_caption(self):
        t = self.track(Text("geo", top_right=(40, 30), layer="default"))
        before = {n: self._xy(getattr(t, n)) for n in ("center", "top_left", "top_right")}
        t.scale_to(0.0)
        t.scale_to(1.0)
        for n, p in before.items():
            self.assertTrue(self._near(self._xy(getattr(t, n)), p, 1e-5), n)

    def test_a_linked_anchor_refuses_to_turn(self):
        pin = self.track(Circle(center=(40, 30), radius=1))
        t = self.track(Text("geo", top_left=lambda: pin.center, layer="default"))
        with self.assertRaises(LinkedAttributeError):
            t.rotate_by(30)
        t.rotate_by(30, force=True)                 # unlinks, then turns
        self.assertFalse(t["top_left"].is_linked)

    def test_flips_raise(self):
        t = self.track(Text("geo", center=(0, 0)))
        for flag in ("flip_x", "flip_y"):
            with self.assertRaises(TypeError):
                setattr(t, flag, True)
            setattr(t, flag, False)                 # a no-op

    def test_clone_keeps_the_anchor_form_and_the_pose(self):
        for anchor in ("top_left", "top_center", "top_right"):
            with self.subTest(anchor=anchor):
                t = self.track(Text("geo", **{anchor: (40, 30)}, layer="default"))
                t.rotate_by(35)
                t.scale_by(1.5)
                copy = self.track(t.clone())
                self.assertEqual(copy._anchor, anchor)             # was center=
                self.assertFalse(copy._is_on_ui_layer())           # a world caption stays in the world
                self.assertEqual((copy.angle, copy.scale), (t.angle, t.scale))
                for n in ("center", "top_left", "top_center", "top_right"):
                    self.assertTrue(self._near(self._xy(getattr(copy, n)), self._xy(getattr(t, n))), n)
                # The copy is pinned like the source: a new text grows from the anchor.
                pin = self._xy(getattr(copy, anchor))
                copy.text.value = "a longer caption"
                self.assertTrue(self._near(self._xy(getattr(copy, anchor)), pin), anchor)

    def test_clone_of_a_linked_anchor_is_a_free_snapshot(self):
        pin = self.track(Circle(center=(40, 30), radius=1))
        t = self.track(Text("geo", top_left=lambda: pin.center, layer="default"))
        copy = self.track(t.clone())
        self.assertFalse(copy["top_left"].is_linked)
        self.assertTrue(self._near(self._xy(copy.top_left), (40, 30)))

    def test_hud_clone_does_not_join_the_column(self):
        def next_gap(clone):
            ui.stack_reset()
            t = self.track(Text("Title", font_size=16))
            if clone:
                copy = self.track(t.clone())
                self.assertTrue(self._near(self._xy(copy.top_left), self._xy(t.top_left)))
            nxt = self.track(Text("Next", font_size=16))
            return t._y1 - nxt._y1
        self.assertAlmostEqual(next_gap(True), next_gap(False))


class TestTimedPoseOfAPinnedCaption(unittest.TestCase):
    """An anchored caption's turn and scale move its pin. With the pin linked,
    the instant verb refuses; the timed one accepted and raised from a tick
    (found when the gate-parity guard linked every Defining part)."""

    def test_a_linked_pin_refuses_a_timed_turn_or_scale_at_the_call(self):
        from scena import State, Text
        from scena.state import LinkedAttributeError
        st = State(name="pin")
        st.p = (-17.0, -1.0)
        for verb in (lambda t: t.rotate_by(30, time=0.2), lambda t: t.rotate_to(30, time=0.2),
                     lambda t: t.scale_by(1.5, time=0.2), lambda t: t.scale_to(2, time=0.2)):
            t = Text("pin", top_left=(-17, -1))
            t["top_left"] @= lambda: st.p
            with self.assertRaises(LinkedAttributeError):
                verb(t)
            t.destroy()


class TestOnePlacementLink(unittest.TestCase):
    """GX13 (geometry campaign): an anchored caption takes a link on its anchor
    or on its center, not both (they disagreed: the center followed its source
    while the anchor stayed)."""

    def test_the_second_placement_link_refuses(self):
        from scena import State
        st2 = State(name="gx13t")
        st2.a, st2.c = (1.0, 2.0), (3.0, 4.0)
        for anchor in ("top_left", "top_right"):
            for first, second in ((anchor, "center"), ("center", anchor)):
                t = Text("geo", **{anchor: (0, 0)})
                fns = {anchor: (lambda: st2.a), "center": (lambda: st2.c)}
                t[first] @= fns[first]
                with self.assertRaises(LinkedAttributeError):
                    t[second] @= fns[second]
                t.destroy()

    def test_a_centred_caption_still_links_its_center(self):
        from scena import State
        st2 = State(name="gx13c")
        st2.c = (3.0, 4.0)
        t = Text("geo", center=(0, 0))
        t["center"] @= lambda: st2.c
        self.assertAlmostEqual(float(t.center.x), 3.0)
        t.destroy()

    def test_every_link_spelling_takes_one_placement(self):
        """The refusal holds for the whole part (``t.center @= f``) and a
        leaf (``t.center["x"] @= f``), not only the bracket: the whole-part
        spelling was accepted and the two disagreed."""
        from scena import State
        from scena.state import DerivedAttributeError
        st2 = State(name="gx13s")
        st2.a, st2.c, st2.x = (1.0, 2.0), (3.0, 4.0), 5.0
        spellings = {
            "bracket": lambda t, name, fn: t.__setitem__(name, t[name].__imatmul__(fn)),
            "whole": lambda t, name, fn: getattr(t, name).__imatmul__(fn),
        }
        for anchor in ("top_left", "top_center", "top_right"):
            for first, second in ((anchor, "center"), ("center", anchor)):
                for how1, link1 in spellings.items():
                    for how2, link2 in spellings.items():
                        t = Text("geo", **{anchor: (0, 0)})
                        fns = {anchor: (lambda: st2.a), "center": (lambda: st2.c)}
                        link1(t, first, fns[first])
                        with self.subTest(anchor=anchor, first=first, how1=how1, how2=how2):
                            with self.assertRaises((LinkedAttributeError, DerivedAttributeError)):
                                link2(t, second, fns[second])
                        t.destroy()
                t = Text("geo", **{anchor: (0, 0)})
                t[first] @= (lambda: st2.a) if first == anchor else (lambda: st2.c)
                with self.assertRaises((LinkedAttributeError, DerivedAttributeError)):
                    getattr(t, second)["x"] @= lambda: st2.x
                t.destroy()


class TestLinkedCenterIsThePin(unittest.TestCase):
    """Deep serial pass 2026-10-09 (`test_hyp_reactive_matrix`): on an anchored
    caption a linked ``center`` lost its formula when the string changed. The
    layout kept the anchor and moved the centre by half the width change, then
    published that over the link (center x -16.95 for a formula of -16.0).
    Contract (Canvas Design, Text): a linked part is the pin while it links.
    A linked ``center``: the box lays out around it, the anchor follows and is
    output (a write raises), unlinking restores the construction model."""

    ANCHORS = ("top_left", "top_center", "top_right")

    def setUp(self):
        from scena import State
        self.cell = State(name="lcpin")
        self.cell.c = (10.0, 20.0)
        self.cell.s = "geo"
        self.made = []

    def tearDown(self):
        for t in self.made:
            t.destroy()

    def caption(self, **kw):
        t = Text("geo", **kw)
        self.made.append(t)
        return t

    def assert_center_holds(self, t, x, y, msg=""):
        self.assertAlmostEqual(float(t.center.x), x, places=6, msg=msg)
        self.assertAlmostEqual(float(t.center.y), y, places=6, msg=msg)

    def assert_anchor_follows(self, t, anchor, msg=""):
        b = t.box
        expect = {"top_left": b.top_left, "top_center": b.top_center,
                  "top_right": b.top_right}[anchor]
        part = getattr(t, anchor)
        self.assertAlmostEqual(float(part.x), float(expect.x), places=6, msg=msg)
        self.assertAlmostEqual(float(part.y), float(expect.y), places=6, msg=msg)

    def test_a_string_change_keeps_a_linked_center(self):
        """Every width input: a plain write, formula text, ``width``, ``font_size``."""
        cell = self.cell
        changes = (
            ("write", lambda t: setattr(t, "text", "a much longer string\nand a line")),
            ("formula", None),
            ("width", lambda t: setattr(t, "width", 300)),
            ("font_size", lambda t: setattr(t, "font_size", 40)),
        )
        for anchor in self.ANCHORS:
            for label, change in changes:
                t = self.caption(**{anchor: (0, 0)})
                t["center"] @= lambda: cell.c
                if change is None:
                    t["text"] @= lambda: cell.s
                    cell.s = "a much longer string"
                else:
                    change(t)
                msg = f"{anchor} / {label}"
                self.assert_center_holds(t, 10.0, 20.0, msg)
                self.assert_anchor_follows(t, anchor, msg)
                cell.s = "geo"

    def test_one_cell_moves_the_string_and_the_center(self):
        """The shortest Hypothesis case: ``text`` and ``center`` linked to one
        cell, then the cell moves; read like plain writes, string first."""
        from scena import State
        cell = State(name="lcpin1")
        cell.v = 1.0
        for anchor in self.ANCHORS:
            t = self.caption(**{anchor: (0, 0)})
            twin = self.caption(**{anchor: (0, 0)})
            t["text"] @= lambda: (40.0 * cell.v - 9.0, 20.0 * cell.v + 15.0)
            t["center"] @= lambda: (40.0 * cell.v - 16.0, 20.0 * cell.v + 1.0)
            for v in (0.0, 0.37, 1.0):
                cell.v = v
                twin.text = (40.0 * v - 9.0, 20.0 * v + 15.0)
                twin.center = (40.0 * v - 16.0, 20.0 * v + 1.0)
                for name in ("center",) + self.ANCHORS:
                    a, b = getattr(t, name), getattr(twin, name)
                    self.assertAlmostEqual(float(a.x), float(b.x), places=6, msg=f"{anchor} {name} v={v}")
                    self.assertAlmostEqual(float(a.y), float(b.y), places=6, msg=f"{anchor} {name} v={v}")
                self.assert_center_holds(t, 40.0 * v - 16.0, 20.0 * v + 1.0)

    def test_the_anchor_is_output_while_the_center_links(self):
        """An anchor write would fight the link: every spelling raises, and the
        move verbs raise as before. A leaf link counts as a link."""
        from scena.state import DerivedAttributeError
        cell = self.cell
        cell.x = 3.0
        writes = (
            lambda t, a: setattr(t, a, (5, 5)),
            lambda t, a: setattr(getattr(t, a), "x", 7),
            lambda t, a: setattr(getattr(t, a), "y", 7),
        )
        for anchor in self.ANCHORS:
            for leaf in (False, True):
                t = self.caption(**{anchor: (0, 0)})
                if leaf:
                    t.center["x"] @= lambda: cell.x
                else:
                    t["center"] @= lambda: cell.c
                for w in writes:
                    with self.assertRaises(DerivedAttributeError, msg=f"{anchor} leaf={leaf}"):
                        w(t, anchor)
                with self.assertRaises(LinkedAttributeError):
                    t.move_by(1, 1)
                self.assertAlmostEqual(float(t.center.x), 3.0 if leaf else 10.0)

    def test_the_center_is_output_while_the_anchor_links_after_construction(self):
        """The mirror: ``t["top_left"] @= f`` after construction makes ``center``
        output too, as ``Text(top_left=lambda: …)`` does (a ``center`` write
        was accepted and left the two parts apart)."""
        from scena.state import DerivedAttributeError
        cell = self.cell
        for anchor in self.ANCHORS:
            t = self.caption(**{anchor: (0, 0)})
            t[anchor] @= lambda: cell.c
            with self.assertRaises(DerivedAttributeError):
                t.center = (5, 5)
            with self.assertRaises(DerivedAttributeError):
                t.center.x = 7
            part = getattr(t, anchor)
            self.assertAlmostEqual(float(part.x), 10.0)
            self.assert_anchor_follows(t, anchor)
            t[anchor].unlink()                   # the snapshot model is back
            t.center = (5, 5)
            self.assert_center_holds(t, 5.0, 5.0)
        built = self.caption(top_left=lambda: cell.c)
        built["top_left"].unlink()               # built linked: center stays derived
        with self.assertRaises(DerivedAttributeError):
            built.center = (5, 5)

    def test_unlink_restores_the_construction_model(self):
        """After unlinking, the anchor where it is now is the pin again: both
        placement parts take writes, and a longer string grows away from it."""
        cell = self.cell
        for anchor in self.ANCHORS:
            t = self.caption(**{anchor: (0, 0)})
            t["center"] @= lambda: cell.c
            t["center"].unlink()
            part = getattr(t, anchor)
            px, py = float(part.x), float(part.y)
            t.text = "a much longer string"
            self.assertAlmostEqual(float(part.x), px, places=6)
            self.assertAlmostEqual(float(part.y), py, places=6)
            setattr(t, anchor, (1, 2))
            t.center = (30, 40)
            self.assert_center_holds(t, 30.0, 40.0)
            t[anchor] @= lambda: cell.c          # one placement link again
            self.assertAlmostEqual(float(part.x), 10.0)

    def test_a_turned_caption_keeps_a_linked_center(self):
        cell = self.cell
        for anchor in self.ANCHORS:
            t = self.caption(**{anchor: (0, 0)})
            t.angle = 30
            t["center"] @= lambda: cell.c
            t.text = "a much longer string"
            t.rotate_by(15)
            self.assert_center_holds(t, 10.0, 20.0, anchor)
            self.assert_anchor_follows(t, anchor, anchor)
