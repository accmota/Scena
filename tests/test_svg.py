"""Svg — SVG markup or filename Sprite body.

Run headless:

    python -m unittest tests.test_svg -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
import warnings

from scena import Svg, Sprite, Circle, clock
from scena.visuals import Halo
from scena.shapes import Entity, Graphic, Shape
from scena.sprite import reset_sprite_caches
from scena.collision import snapshot_shape, reset_collision_system
from scena.process import reset_process_scheduler
from scena.events import cleanup_global_event_system
from tests.media_support import smoke


# A tracked SVG file (square viewBox), by absolute and by repo-relative path
# (tests run from the repo root, so the relative one resolves through cwd).
_COMPASS = smoke("sonnenschirm.svg")
_REL = "scripts/smoke/sonnenschirm.svg"
# A second, different file for the swap test: written per test, not tracked.
_CAR_MARKUP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80">'
    '<rect x="10" y="20" width="100" height="40" rx="8" fill="#c33"/>'
    '<circle cx="35" cy="62" r="12"/><circle cx="85" cy="62" r="12"/>'
    "</svg>"
)

_TINY = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
    '<circle cx="20" cy="20" r="16" fill="#3cf"/>'
    "</svg>"
)
_TINY_ALT = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
    '<circle cx="20" cy="20" r="16" fill="#f63"/>'
    "</svg>"
)


class SvgTestCase(unittest.TestCase):
    def setUp(self):
        reset_sprite_caches()
        reset_process_scheduler()
        reset_collision_system()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        self._owned = []

    def tearDown(self):
        for obj in self._owned:
            try:
                if getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_process_scheduler()
        reset_collision_system()
        reset_sprite_caches()
        cleanup_global_event_system()

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestIdentity(SvgTestCase):
    def test_svg_is_sprite_not_shape(self):
        s = self.track(Svg(center=(0, 0), size=32))
        self.assertIsInstance(s, Svg)
        self.assertIsInstance(s, Sprite)
        self.assertIsInstance(s, Graphic)
        self.assertIsInstance(s, Entity)
        self.assertNotIsInstance(s, Shape)
        self.assertNotIsInstance(s, Circle)

    def test_empty_is_placeholder_no_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s = self.track(Svg(center=(10, 20), size=40))
        pathish = [
            w for w in caught
            if "not a file path" in str(w.message) or "failed to parse" in str(w.message)
        ]
        self.assertEqual(pathish, [])
        self.assertTrue(s._placeholder)
        self.assertIsNone(s.svg)
        self.assertEqual(float(s.center.x), 10)
        self.assertEqual(float(s.center.y), 20)
        self.assertTrue(s.is_alive)


class TestMarkupBody(SvgTestCase):
    def test_valid_markup_rasterizes(self):
        s = self.track(Svg(_TINY, height=48, center=(0, 0)))
        self.assertFalse(s._placeholder)
        self.assertEqual(s.svg, _TINY)
        self.assertAlmostEqual(float(s.height), 48.0)
        self.assertAlmostEqual(float(s.width), 48.0)
        img = s.sheet.image
        self.assertGreaterEqual(img.width(), 128)
        self.assertGreaterEqual(img.height(), 128)

    def test_same_string_is_noop(self):
        s = self.track(Svg(_TINY, height=40, center=(0, 0)))
        img = s.sheet.image
        s.svg = _TINY
        self.assertIs(s.sheet.image, img)
        # New equal string (not same object) is also a no-op.
        s.svg = str(_TINY)
        self.assertIs(s.sheet.image, img)

    def test_different_string_replaces_body(self):
        s = self.track(Svg(_TINY, height=40, center=(0, 0)))
        img = s.sheet.image
        s.svg = _TINY_ALT
        self.assertIsNot(s.sheet.image, img)
        self.assertEqual(s.svg, _TINY_ALT)
        self.assertFalse(s._placeholder)
        self.assertTrue(s.is_alive)

    def test_missing_file_warns_once_placeholder(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            a = self.track(Svg("heart.svg", height=32, center=(0, 0)))
            b = self.track(Svg("heart.svg", height=32, center=(5, 0)))
        msgs = [w for w in caught if "file not found" in str(w.message)]
        self.assertEqual(len(msgs), 1)
        self.assertTrue(a._placeholder)
        self.assertTrue(b._placeholder)
        self.assertIsNone(a.svg)

    def test_bad_markup_keeps_last_good_on_setter(self):
        s = self.track(Svg(_TINY, height=40, center=(0, 0)))
        img = s.sheet.image
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s.svg = "<svg>not-really-valid"
            s.svg = "broken.svg"
        self.assertTrue(any("file not found" in str(w.message) for w in caught))
        self.assertIs(s.sheet.image, img)
        self.assertEqual(s.svg, _TINY)
        self.assertFalse(s._placeholder)

    def test_reject_sheet_kwargs(self):
        for kwargs in (
            {"cols": 2},
            {"fps": 8},
            {"atlas": "x.xml"},
            {"rows": 2, "cols": 2},
            {"name": "walk"},
            {"wrap": "sway"},
            {"cell": (8, 8)},
        ):
            with self.assertRaises(TypeError):
                self.track(Svg(_TINY, height=32, **kwargs))

    def test_reject_play(self):
        s = self.track(Svg(_TINY, height=32, center=(0, 0)))
        with self.assertRaises(TypeError):
            s.play("walk")


class TestCloneAndCollision(SvgTestCase):
    def test_clone_is_svg_and_isolated(self):
        a = self.track(Svg(_TINY, height=40, center=(10, 20)))
        b = self.track(a.clone(center=(100, 20)))
        self.assertIsInstance(b, Svg)
        self.assertEqual(b.svg, _TINY)
        img_a = a.sheet.image
        img_b = b.sheet.image
        self.assertIsNot(img_a, img_b)
        b.svg = _TINY_ALT
        self.assertIs(a.sheet.image, img_a)
        self.assertEqual(a.svg, _TINY)
        self.assertEqual(b.svg, _TINY_ALT)
        self.assertIsNot(b.sheet.image, img_a)

    def test_hitbox_rebakes_after_markup_swap(self):
        s = self.track(Svg(_TINY, height=48, center=(0, 0), hitbox_shape="auto"))
        s.collidable = True
        self.assertTrue(s._auto_baked)
        prims_before = snapshot_shape(s)
        self.assertGreaterEqual(len(prims_before), 1)
        s.svg = _TINY_ALT
        self.assertFalse(s._auto_baked)
        prims_after = snapshot_shape(s)
        self.assertGreaterEqual(len(prims_after), 1)
        self.assertTrue(s._auto_baked)

    def test_hitbox_from_all_and_each_are_legal(self):
        a = self.track(Svg(_TINY, height=48, center=(0, 0), hitbox_source="all"))
        b = self.track(Svg(_TINY, height=48, center=(0, 0), hitbox_source="each"))
        self.assertEqual(a.hitbox.source, "all")
        self.assertEqual(b.hitbox.source, "each")
        snapshot_shape(a)
        snapshot_shape(b)
        copy = self.track(a.clone(center=(10, 0)))
        self.assertEqual(copy.hitbox.source, "all")
        c = self.track(Svg(_TINY, height=48, center=(0, 0), hitbox_source="clip"))
        self.assertEqual(c.hitbox.source, "clip")
        self.assertEqual(c._hitbox_from_indices(), (0,))


class TestFileSource(SvgTestCase):
    def test_media_path_loads_and_stores_markup(self):
        s = self.track(Svg(_REL, height=48, center=(0, 0)))
        self.assertFalse(s._placeholder)
        self.assertIsNotNone(s.svg)
        self.assertIn("viewBox", s.svg or "")
        self.assertNotEqual(s.svg, _REL)
        self.assertAlmostEqual(float(s.height), 48.0)
        self.assertGreaterEqual(s.sheet.image.width(), 128)

    def test_filename_assign_swaps_body(self):
        s = self.track(Svg(_REL, height=40, center=(0, 0)))
        compass = s.svg
        img = s.sheet.image
        with tempfile.TemporaryDirectory() as tmp:
            car = os.path.join(tmp, "car.svg")
            with open(car, "w", encoding="utf-8") as fh:
                fh.write(_CAR_MARKUP)
            s.svg = car
        self.assertIsNot(s.sheet.image, img)
        self.assertNotEqual(s.svg, compass)
        self.assertIn("<svg", (s.svg or "").lower())
        self.assertFalse(s._placeholder)

    def test_filename_same_contents_is_noop(self):
        s = self.track(Svg(_REL, height=40, center=(0, 0)))
        img = s.sheet.image
        stored = s.svg
        s.svg = _REL
        self.assertIs(s.sheet.image, img)
        self.assertEqual(s.svg, stored)

    def test_class_source_filename(self):
        class Compass(Svg, source=_REL, height=40):
            pass

        s = self.track(Compass(center=(0, 0)))
        self.assertFalse(s._placeholder)
        self.assertIn("viewBox", s.svg or "")
        self.assertAlmostEqual(float(s.height), 40.0)

    def test_absolute_path_loads(self):
        s = self.track(Svg(_COMPASS, height=32, center=(0, 0)))
        self.assertFalse(s._placeholder)
        self.assertIn("viewBox", s.svg or "")


class TestCompassAsset(SvgTestCase):
    def test_compass_file_markup(self):
        with open(_COMPASS, encoding="utf-8") as f:
            markup = f.read()
        s = self.track(Svg(markup, height=48, center=(0, 0)))
        self.assertFalse(s._placeholder)
        self.assertIn("viewBox", s.svg or "")
        self.assertAlmostEqual(float(s.height), 48.0)
        self.assertGreaterEqual(s.sheet.image.width(), 128)


class TestSvgSpriteBody(SvgTestCase):
    def test_halo_uses_render_sprite_and_keeps_line_filter_clear(self):
        s = self.track(Svg(_TINY, height=40, center=(0, 0)))
        s.visual = Halo()
        self.assertTrue(type(s)._is_sprite_body)
        self.assertIsNone(s.line_filter)
        called = []
        real = type(s.visual)._render_sprite_body

        def spy(look, shape, canvas):
            called.append(shape)
            return real(look, shape, canvas)

        type(s.visual)._render_sprite_body = spy
        try:
            import skia
            s.draw(skia.Surface(80, 80).getCanvas())
        finally:
            type(s.visual)._render_sprite_body = real
        self.assertEqual(called, [s])
        self.assertIsNone(s.line_filter)


if __name__ == "__main__":
    unittest.main()
