"""Attribute cell contract: unhashable + selective as_payload at scalar gates.

Run headless:

    python -m unittest tests.test_attribute_payload -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

import skia

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.atlas import (
    AtlasFrame,
    _AUTO_CACHE,
    auto_collider_for_frame,
    reset_atlas_caches,
)
from scena.easing import resolve_ease
from scena.sprite import Sheet, Sprite, _parse_hitbox, _parse_offset, reset_sprite_caches
from scena.state import Attribute, as_payload, as_payload_all
from scena.scenamath import Vec2
from scena.style import LineCapStyle, TileMode, Gradient, PaintState
from scena.color import Color, ColorSpace
from scena.validate import coerce_enum, expect_choice
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


def _disk_image(side: int = 32, radius: float = 14.0) -> skia.Image:
    info = skia.ImageInfo.Make(
        side, side, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
    )
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(Color=skia.ColorWHITE, AntiAlias=False)
    c.drawCircle(side * 0.5, side * 0.5, float(radius), paint)
    return surf.makeImageSnapshot()


class TestUnhashable(unittest.TestCase):
    def test_attribute_unhashable(self):
        a = Attribute("circle")
        with self.assertRaises(TypeError):
            hash(a)
        with self.assertRaises(TypeError):
            {a}

    def test_vec2_unhashable(self):
        v = Vec2(1.0, 2.0)
        with self.assertRaises(TypeError):
            hash(v)
        with self.assertRaises(TypeError):
            {v}


class TestAsPayload(unittest.TestCase):
    def test_unwraps_attribute(self):
        self.assertEqual(as_payload(Attribute("circle")), "circle")
        self.assertIs(as_payload(None), None)
        self.assertEqual(as_payload(3), 3)


class TestAsPayloadAll(unittest.TestCase):
    def test_mixed_args(self):
        self.assertEqual(
            as_payload_all(Attribute(1), 2, Attribute("x"), None),
            (1, 2, "x", None),
        )

    def test_empty(self):
        self.assertEqual(as_payload_all(), ())


class TestP0Gates(unittest.TestCase):
    def test_expect_choice_attribute(self):
        self.assertEqual(
            expect_choice(Attribute("side"), ("side", "top"), what="kind"),
            "side",
        )

    def test_coerce_enum_attribute(self):
        self.assertIs(
            coerce_enum(Attribute("round"), LineCapStyle, what="cap"),
            LineCapStyle.ROUND,
        )
        self.assertIs(
            coerce_enum(Attribute("clamp"), TileMode, what="tile_mode"),
            TileMode.CLAMP,
        )

    def test_resolve_ease_attribute(self):
        fn = resolve_ease(Attribute("ease_in"))
        self.assertTrue(callable(fn))
        self.assertAlmostEqual(fn(0.0), 0.0)

    def test_auto_collider_force_kind_attribute_shares_cache(self):
        reset_atlas_caches()
        img = _disk_image()
        fr = AtlasFrame(
            name="disk", x=0, y=0, w=32, h=32,
            src_x=0, src_y=0, src_w=32, src_h=32,
            pivot_x=0.5, pivot_y=0.5,
        )
        col_attr = auto_collider_for_frame(
            img, fr,
            force_kind=Attribute("circle"),
        )
        self.assertEqual(col_attr.kind, "circle")
        from scena.atlas import _auto_key
        key = _auto_key(img, fr, "circle")
        self.assertIn(key, _AUTO_CACHE)
        n_before = len(_AUTO_CACHE)
        col_str = auto_collider_for_frame(
            img, fr, force_kind="circle",
        )
        self.assertIs(col_str, col_attr)
        self.assertEqual(len(_AUTO_CACHE), n_before)


class TestP1Sprite(unittest.TestCase):
    def setUp(self):
        reset_sprite_caches()
        reset_atlas_caches()

    def test_parse_hitbox_attribute(self):
        self.assertEqual(_parse_hitbox(Attribute("auto")), "auto")
        self.assertEqual(_parse_hitbox(Attribute("ellipse")), "ellipse")
        self.assertEqual(_parse_hitbox(Attribute("circle")), "circle")
        self.assertEqual(_parse_hitbox(Attribute("hull")), "hull")
        self.assertEqual(_parse_hitbox(Attribute("rect")), "rect")

    def test_cycle_and_play_attribute_names(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "grid.png")
            info = skia.ImageInfo.Make(
                32, 32, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType,
            )
            surf = skia.Surface.MakeRaster(info)
            surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorRED))
            surf.makeImageSnapshot().save(path, skia.kPNG)

            sheet = Sheet(path, cell=(16, 16))
            sheet.clip(Attribute("idle"), [0, 1], fps=Attribute(6.0))
            self.assertIn("idle", sheet._cycles)

            sprite = Sprite(sheet, frame=0, height=32, hitbox_shape="rect")
            sprite.play(Attribute("idle"))
            self.assertEqual(sprite._play_name, "idle")


class TestMigrationRegressions(unittest.TestCase):
    """Attribute args still work after retiring @unwrap_attributes."""

    def test_color_from_name_and_tuple_attribute(self):
        c = Color.from_name(Attribute("red"))
        self.assertAlmostEqual(c._r, 1.0)
        self.assertAlmostEqual(c._g, 0.0)
        self.assertAlmostEqual(c._b, 0.0)
        c2 = Color(Attribute((0.0, 1.0, 0.0)))
        self.assertAlmostEqual(c2._g, 1.0)

    def test_color_interpolate_attribute_t(self):
        a = Color(1, 0, 0)
        b = Color(0, 0, 1)
        mid = Color.interpolate(a, b, Attribute(0.5), Attribute(ColorSpace.RGB))
        self.assertAlmostEqual(mid._r, 0.5)
        self.assertAlmostEqual(mid._b, 0.5)

    def test_gradient_and_set_color_attribute(self):
        g = Gradient(Attribute("rdyl"))
        self.assertGreaterEqual(len(g._colors), 2)
        ps = PaintState()
        ps.set_color(Attribute(Color("red")))
        self.assertIsInstance(ps.fill, Color)

    def test_vec2_lerp_and_rotate_attribute(self):
        a = Vec2.temp(x=1.0, y=1.0)
        b = Vec2.temp(x=3.0, y=3.0)
        mid = a.lerp(b, Attribute(0.5))
        self.assertAlmostEqual(float(mid.x), 2.0)
        self.assertAlmostEqual(float(mid.y), 2.0)
        spun = Vec2.temp(x=1.0, y=0.0).rotate(Attribute(90.0))
        self.assertAlmostEqual(float(spun.x), 0.0, places=5)
        self.assertAlmostEqual(float(spun.y), 1.0, places=5)

    def test_parse_offset_attribute(self):
        self.assertEqual(_parse_offset(Attribute((2.0, 3.0))), (2.0, 3.0))

    def test_sprite_offset_attribute(self):
        reset_sprite_caches()
        reset_atlas_caches()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "grid.png")
            info = skia.ImageInfo.Make(
                32, 32, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType,
            )
            surf = skia.Surface.MakeRaster(info)
            surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorRED))
            surf.makeImageSnapshot().save(path, skia.kPNG)
            sheet = Sheet(path, cell=(16, 16))
            sprite = Sprite(
                sheet, frame=0, height=32, hitbox_shape="rect",
                offset=Attribute((2.0, 3.0)),
            )
            self.assertEqual(sprite.offset, (2.0, 3.0))

    def test_slider_width_attribute(self):
        from scena import init
        from scena.uiwidget import Slider
        from scena.orchestration import ScenaFramework
        init(width=800, height=600)
        wm = ScenaFramework.get_instance().widget_manager
        s = Slider(
            top_left=(20, 80), width=Attribute(200.0),
            min_value=0.0, max_value=100.0, initial=50.0,
        )
        try:
            self.assertEqual(s.width, 200.0)
        finally:
            wm.remove_widget(s)


class TestBoxedCellFormat(unittest.TestCase):
    def test_attribute_format_spec(self):
        a = Attribute(12.5)
        self.assertEqual(f"{a:.1f}", "12.5")
        self.assertEqual(format(a, ".0f"), "12")

    def test_attribute_format_string_payload(self):
        a = Attribute("hud")
        self.assertEqual(f"{a:>6}", "   hud")


if __name__ == "__main__":
    unittest.main()
