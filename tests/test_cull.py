"""
Offscreen cull: AABB keep/skip, pads, SpatialFx tick, parallax exemption.

Run headless (no window):

    python -m unittest tests.test_cull -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import canvas, init
from scena.canvas import ScenaCanvas, _approx_draw_aabb
from scena.filters import GlowFilter
from scena.registry import BUILT_IN_LAYERS
from scena.shapes import Circle, Line, Polygon
from scena.spatial_fx import Fire, tick_all_spatial_fx
from scena import spatial_fx as sfx
from scena import transients as tx


def _engine():
    return ScenaCanvas.get_current()


def _default_layer():
    return _engine().registry.layers["default"]


class CullTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        canvas.cull_offscreen = False
        self._owned = []

    def tearDown(self):
        for s in list(self._owned):
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        for name in list(canvas.layers):
            if name not in BUILT_IN_LAYERS:
                try:
                    canvas.layers[name].delete(destroy_shapes=True)
                except Exception:
                    pass
        canvas.layers.default = "default"
        canvas.cull_offscreen = False
        canvas.reset_view()
        for shape in list(tx._active_shapes):
            tx.clear_transients(shape)
        tx.set_now_fn(None)
        for fx in list(sfx._active_fx):
            try:
                fx.destroy()
            except Exception:
                sfx.unregister_spatial(fx)
        sfx.set_now_fn(None)

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestDefaultOff(CullTestCase):
    def test_far_shape_passes_when_cull_off(self):
        eng = _engine()
        far = self.track(Circle(center=(50000, 50000), radius=10))
        self.assertFalse(eng.cull_offscreen)
        self.assertTrue(eng._passes_cull(far, layer=_default_layer()))


class TestKeepSkip(CullTestCase):
    def test_on_screen_kept_far_skipped(self):
        eng = _engine()
        eng.cull_offscreen = True
        near = self.track(Circle(center=(500, 400), radius=20))
        far = self.track(Circle(center=(50000, 50000), radius=10))
        layer = _default_layer()
        self.assertTrue(eng._passes_cull(near, layer=layer))
        self.assertFalse(eng._passes_cull(far, layer=layer))

    def test_zoom_changes_kept_set(self):
        eng = _engine()
        eng.cull_offscreen = True
        outer = self.track(Circle(center=(2000, 400), radius=30))
        layer = _default_layer()
        self.assertFalse(eng._passes_cull(outer, layer=layer))
        canvas.zoom_to(0.2)
        self.assertTrue(eng._passes_cull(outer, layer=layer))
        canvas.zoom_to(4.0)
        self.assertFalse(eng._passes_cull(outer, layer=layer))


class TestSpanCases(CullTestCase):
    def test_line_crossing_view_with_offscreen_ends(self):
        eng = _engine()
        eng.cull_offscreen = True
        line = self.track(Line(p1=(-200, 400), p2=(2000, 400)))
        self.assertTrue(eng._passes_cull(line, layer=_default_layer()))
        box = _approx_draw_aabb(line)
        self.assertIsNotNone(box)
        minx, miny, maxx, maxy = box
        self.assertLess(minx, 0.0)
        self.assertGreater(maxx, 1000.0)

    def test_polygon_vertex_in_view_centroid_off(self):
        eng = _engine()
        eng.cull_offscreen = True
        # Vertex at (100, 400) is in view; centroid is far to the right.
        poly = self.track(Polygon(points=[
            (100, 400),
            (8000, 400),
            (8000, 0),
        ]))
        cx = float(poly.center.x)
        self.assertGreater(cx, 2000.0)
        box = _approx_draw_aabb(poly)
        self.assertIsNotNone(box)
        self.assertLessEqual(box[0], 100.0)
        self.assertGreaterEqual(box[2], 100.0)
        self.assertTrue(eng._passes_cull(poly, layer=_default_layer()))

    def test_circle_aabb_is_disc_not_diameter(self):
        # Circle.p1/p2 are Derivate diameter ends; cull/batch must use the disc.
        c = self.track(Circle(center=(100, 100), radius=20))
        box = _approx_draw_aabb(c)
        self.assertIsNotNone(box)
        minx, miny, maxx, maxy = box
        self.assertAlmostEqual(minx, 80.0, places=3)
        self.assertAlmostEqual(maxx, 120.0, places=3)
        self.assertAlmostEqual(miny, 80.0, places=3)
        self.assertAlmostEqual(maxy, 120.0, places=3)


class TestPads(CullTestCase):
    def test_filter_outset_keeps_near_edge(self):
        eng = _engine()
        eng.cull_offscreen = True
        layer = _default_layer()
        bare = self.track(Circle(center=(-15, 400), radius=10))
        self.assertFalse(eng._passes_cull(bare, layer=layer))
        glowing = self.track(Circle(center=(-15, 400), radius=10))
        glowing.fill_filter = GlowFilter(radius=20, sigma=20)
        self.assertTrue(eng._passes_cull(glowing, layer=layer))

    def test_outset_keeps_stroke_and_multipass(self):
        from scena.canvas import _filter_outset

        class _Vis:
            _cull_outset = 100.0
            _is_multipass = True

        class _Glow:
            _cull_outset = 100.0

        class _Obj:
            line_width = 20.0
            fill_filter = None
            line_filter = None
            visual = _Vis()
            _glow = _Glow()
            _tail = None

        # max(100, 100) + half stroke 10 + multipass 80
        self.assertAlmostEqual(_filter_outset(_Obj()), 190.0, places=5)

    def test_transient_pad_keeps_near_edge(self):
        eng = _engine()
        eng.cull_offscreen = True
        layer = _default_layer()
        c = self.track(Circle(center=(-15, 400), radius=10))
        self.assertFalse(eng._passes_cull(c, layer=layer))
        c.spark_burst()
        self.assertTrue(eng._passes_cull(c, layer=layer))


class TestSpatialFx(CullTestCase):
    def test_domain_aabb_far_skipped_near_kept(self):
        eng = _engine()
        eng.cull_offscreen = True
        layer = _default_layer()
        near = self.track(Fire(center=(500, 400), radius=40))
        far = self.track(Fire(center=(50000, 50000), radius=40))
        self.assertTrue(eng._passes_cull(near, layer=layer))
        self.assertFalse(eng._passes_cull(far, layer=layer))

    def test_culled_emitter_still_ticks(self):
        eng = _engine()
        eng.cull_offscreen = True
        far = self.track(Fire(center=(50000, 50000), radius=40))
        self.assertFalse(eng._passes_cull(far, layer=_default_layer()))
        t = {"now": 50.0}
        sfx.set_now_fn(lambda: t["now"])
        tick_all_spatial_fx(t["now"])
        first = far._tick_t
        self.assertIsNotNone(first)
        t["now"] = 50.2
        tick_all_spatial_fx(t["now"])
        self.assertGreater(far._tick_t, first)
        self.assertTrue(far.is_alive)
        self.assertTrue(far.visible)


class TestParallaxExemption(CullTestCase):
    def test_parallax_far_shape_kept(self):
        canvas.layers.create("bg", pan_response=0.0)
        eng = _engine()
        eng.cull_offscreen = True
        far = self.track(Circle(center=(50000, 50000), radius=10, layer="bg"))
        layer = eng.registry.layers["bg"]
        self.assertTrue(eng._passes_cull(far, layer=layer))

    def test_neutral_far_still_skipped(self):
        eng = _engine()
        eng.cull_offscreen = True
        far = self.track(Circle(center=(50000, 50000), radius=10))
        self.assertFalse(eng._passes_cull(far, layer=_default_layer()))


class TestFailOpenAndCounters(CullTestCase):
    def test_unknown_geometry_fail_open(self):
        eng = _engine()
        eng.cull_offscreen = True

        class _NoGeom:
            pass

        self.assertIsNone(_approx_draw_aabb(_NoGeom()))
        self.assertTrue(eng._passes_cull(_NoGeom(), layer=_default_layer()))

    def test_draw_counters(self):
        eng = _engine()
        eng.cull_offscreen = True
        self.track(Circle(center=(500, 400), radius=20))
        self.track(Circle(center=(50000, 50000), radius=10))
        eng.draw()
        self.assertGreaterEqual(eng._cull_kept, 1)
        self.assertGreaterEqual(eng._cull_skipped, 1)
        canvas.cull_offscreen = False
        eng.draw()
        self.assertEqual(eng._cull_skipped, 0)
        self.assertGreaterEqual(eng._cull_kept, 2)


class TestPlainBlitCull(CullTestCase):
    def test_plain_sprite_still_culled(self):
        from scena.sprite import Sprite
        import tempfile
        import skia
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorWHITE))
        surf.makeImageSnapshot().save(tmp.name, skia.kPNG)
        eng = _engine()
        eng.cull_offscreen = True
        near = self.track(Sprite(tmp.name, height=16, center=(500, 400)))
        far = self.track(Sprite(tmp.name, height=16, center=(50000, 50000)))
        self.assertTrue(near._plain_blit)
        self.assertTrue(far._plain_blit)
        layer = _default_layer()
        self.assertTrue(eng._passes_cull(near, layer=layer))
        self.assertFalse(eng._passes_cull(far, layer=layer))


class TestDebugZoomCull(CullTestCase):
    def test_debug_zoom_skips_cull_without_changing_bounds(self):
        eng = _engine()
        eng.cull_offscreen = True
        far = self.track(Circle(center=(50000, 50000), radius=10))
        layer = _default_layer()
        bounds_before = canvas.game_view
        self.assertFalse(eng._passes_cull(far, layer=layer))

        eng._debug_zoom_active = True
        self.assertTrue(eng._passes_cull(far, layer=layer))
        bounds_after = canvas.game_view
        self.assertAlmostEqual(bounds_before.left, bounds_after.left)
        self.assertAlmostEqual(bounds_before.top, bounds_after.top)
        self.assertAlmostEqual(bounds_before.width, bounds_after.width)
        self.assertAlmostEqual(bounds_before.height, bounds_after.height)

        eng._debug_zoom_active = False
        self.assertFalse(eng._passes_cull(far, layer=layer))

    def test_debug_zoom_inactive_cull_unchanged(self):
        eng = _engine()
        eng.cull_offscreen = True
        eng._debug_zoom_active = False
        far = self.track(Circle(center=(50000, 50000), radius=10))
        self.assertFalse(eng._passes_cull(far, layer=_default_layer()))


class TestCullCoversMiterJoins(CullTestCase):
    """D9 (Testing Design): the cull pad added half the stroke width, but a
    miter join reaches ``half_width / sin(angle / 2)`` past a corner (x sqrt(2) on a
    rectangle, up to Skia's miter limit 4 on sharp polygon corners). A thick
    rotated rect just outside the view had a visible corner culled.
    Found by ``test_diff_draw`` (cull on vs off)."""

    def test_rotated_rect_corner_inside_the_view_is_kept(self):
        from scena.shapes import Rect
        canvas.cull_offscreen = True
        r = self.track(Rect(center=(0, 0), width=11.2, height=7, angle=20))
        r.line_width = 3.0
        # half-stroke pad ends 0.04 left of the view (x = 0); the miter tip
        # reaches about 0.4 inside it.
        r.move_to(-6.459 - 1.5 - 0.041, 2.0)
        self.assertTrue(_engine()._passes_cull(r, layer=_default_layer()))

    def test_sharp_polygon_tip_is_kept(self):
        import math
        canvas.cull_offscreen = True
        # 30-degree tip at x = -2 pointing right: half-stroke pad ends at -1,
        # the miter reaches +1.86 (3.86 half-widths; under Skia's limit 4,
        # so it is not beveled). Sharper tips bevel and reach less.
        t = math.tan(math.radians(15))
        p = self.track(Polygon(points=[(-40.0, 10 - 38 * t), (-40.0, 10 + 38 * t), (-2.0, 10.0)]))
        p.line_width = 2.0
        self.assertTrue(_engine()._passes_cull(p, layer=_default_layer()))

    def test_smooth_shapes_keep_the_tight_pad(self):
        canvas.cull_offscreen = True
        c = self.track(Circle(center=(-6.0, 50), radius=4))
        c.line_width = 2.0          # right edge + half stroke = -1.0 < 0
        self.assertFalse(_engine()._passes_cull(c, layer=_default_layer()))



class TestCullDrawLoop(CullTestCase):
    """Review 2026-10-09 S9-10: the culling draw was 2-3x slower than drawing
    everything (the view window, two imports and the layer checks per
    object). The loop hoists them; ``_passes_cull`` is the same two steps."""

    def _scene(self):
        objs = []
        for i in range(60):
            objs.append(self.track(Circle(center=(i * 37 % 2400 - 1200, i * 53 % 1600 - 800),
                                          radius=6)))
            objs.append(self.track(Line(p1=(i * 41 % 2000 - 1000, -900),
                                        p2=(i * 29 % 2000 - 1000, 900))))
        canvas.pan_to(130, -40)
        canvas.zoom_to(1.3)
        canvas.cull_offscreen = True
        return objs

    def test_the_loop_agrees_with_passes_cull(self):
        objs = self._scene()
        eng = _engine()
        layer = _default_layer()
        want = sum(1 for o in objs if eng._passes_cull(o, layer=layer))
        skipped = len(objs) - want
        self.assertGreater(skipped, 0, "not vacuous")
        self.assertGreater(want, 0, "not vacuous")
        eng.draw(layer_filter=lambda name: name == "default")
        self.assertEqual(eng._cull_skipped, skipped)

    def test_the_view_window_is_computed_once_per_draw(self):
        from unittest import mock
        self._scene()
        eng = _engine()
        calls = []
        real = type(eng).visible_bounds

        def counted(self):
            calls.append(1)
            return real.fget(self)
        with mock.patch.object(type(eng), "visible_bounds", property(counted)):
            eng.draw(layer_filter=lambda name: name == "default")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
