"""
Layer scroll in the frame tick (B2), ``layer.view`` (P1) and live
``layer.scroll`` (P3). Canvas Design, Parallax layers.

Bug class pinned here: world state that only moves when something paints
(scroll integrated inside ``ScenaCanvas.draw``), so a read in ``update`` sees
last frame's value and a run that never draws never scrolls.

Run headless:

    python -m unittest tests.test_layer_scroll_view
"""

from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase  # noqa: E402

from scena import canvas, clock, init  # noqa: E402
from scena.box import Box  # noqa: E402
from scena.canvas import ScenaCanvas  # noqa: E402
from scena.registry import BUILT_IN_LAYERS  # noqa: E402


def _engine():
    return ScenaCanvas.get_current()


class _LayerCleanup:
    def tearDown(self):
        for name in list(canvas.layers):
            if name not in BUILT_IN_LAYERS:
                try:
                    canvas.layers[name].delete(destroy_shapes=True)
                except Exception:
                    pass
        canvas.reset_view()
        super().tearDown()


class TestScrollInFrameTick(_LayerCleanup, SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_frames_scroll_without_drawing(self):
        layer = canvas.layers.create("nuvens", scroll=(0.0, -60.0))
        self.w.step(1)                       # first frame seeds the integrator
        y0 = layer._scroll_state.accum[1]
        self.w.step(30, dt=0.1)
        self.assertAlmostEqual(layer._scroll_state.accum[1] - y0, -60.0 * 3.0, places=3)

    def test_update_sees_this_frames_offset(self):
        layer = canvas.layers.create("nuvens", scroll=(100.0, 0.0))
        seen = []
        self.w.on_update(lambda dt: seen.append(layer._scroll_state.accum[0]))
        self.w.step(5, dt=0.1)
        # Frame 1 seeds; frames 2..5 each add 10 before update runs.
        self.assertAlmostEqual(seen[-1], 40.0, places=3)

    def test_hidden_layer_keeps_scrolling(self):
        # Scroll is world state; ``visible`` is paint (review 2026-10-09 S9-6).
        shown = canvas.layers.create("nuvens", scroll=(60.0, 0.0))
        hidden = canvas.layers.create("nuvens2", scroll=(60.0, 0.0))
        self.w.step(1)
        hidden.visible = False
        self.w.step(60, dt=1 / 60)          # 1 s hidden: no freeze
        self.assertAlmostEqual(hidden._scroll_state.accum[0],
                               shown._scroll_state.accum[0], places=6)
        self.w.step(120, dt=1 / 60)         # 2 s more: no "tab resume" skip
        hidden.visible = True
        self.w.step(1, dt=1 / 60)           # no jump on re-show
        self.assertAlmostEqual(hidden._scroll_state.accum[0],
                               shown._scroll_state.accum[0], places=6)

    def test_clock_pause_stops_scroll(self):
        layer = canvas.layers.create("nuvens", scroll=(100.0, 0.0))
        self.w.step(3, dt=0.1)
        x0 = layer._scroll_state.accum[0]
        clock.scale = 0.0
        try:
            self.w.step(10, dt=0.1)
        finally:
            clock.scale = 1.0
        self.assertAlmostEqual(layer._scroll_state.accum[0], x0, places=6)


class _ViewCase(unittest.TestCase):
    """Bare engine (no frame body): the camera is driven directly."""

    W, H = 800, 600

    def setUp(self):
        init(width=self.W, height=self.H)
        canvas.reset_view()

    def tearDown(self):
        for name in list(canvas.layers):
            if name not in BUILT_IN_LAYERS:
                try:
                    canvas.layers[name].delete(destroy_shapes=True)
                except Exception:
                    pass
        canvas.reset_view()

    def assertBox(self, box, l, b, r, t, places=3):
        self.assertIsInstance(box, Box)
        for got, want, edge in ((box.left, l, "left"), (box.bottom, b, "bottom"),
                                (box.right, r, "right"), (box.top, t, "top")):
            self.assertAlmostEqual(got, want, places=places, msg=edge)


class TestLayerView(_ViewCase):
    """P1: ``layer.view`` is the window each layer shows, in its own coordinates."""

    def test_neutral_layers_see_game_view(self):
        canvas.layers.create("pista", below="default")
        canvas.pan_to(1234, -56)
        gv = canvas.game_view
        for name in ("default", "top", "pista"):
            with self.subTest(layer=name):
                v = canvas.layers[name].view
                self.assertBox(v, gv.left, gv.bottom, gv.right, gv.top)

    def test_ui_sees_ui_view(self):
        canvas.pan_to(5000, 0)
        canvas.zoom_to(2)
        self.assertBox(canvas.layers["ui"].view, 0, 0, self.W, self.H)

    def test_worked_example_g1(self):
        # 800-DU view, pan_response=0.3, camera x = 10000, rest look x = 400:
        # look_eff = 400 + (10000 - 400) * 0.3 = 3280 → x in [2880, 3680].
        montes = canvas.layers.create("montes", pan_response=0.3)
        canvas.pan_to(10000, canvas.pan_y)
        v = montes.view
        self.assertAlmostEqual(v.left, 2880.0, places=3)
        self.assertAlmostEqual(v.right, 3680.0, places=3)
        self.assertAlmostEqual(v.bottom, 0.0, places=3)
        self.assertAlmostEqual(v.top, self.H, places=3)

    def test_screen_locked_layer_never_moves(self):
        hud = canvas.layers.create("ceu", pan_response=0.0)
        canvas.pan_to(-9000, 4000)
        self.assertBox(hud.view, 0, 0, self.W, self.H)

    def test_scroll_accum_shifts_the_view(self):
        nuvens = canvas.layers.create("nuvens", pan_response=0.5, scroll=(20.0, -10.0))
        before = nuvens.view
        _engine().advance_layer_scroll(0.0)
        _engine().advance_layer_scroll(1.0)          # accum (20, -10)
        after = nuvens.view
        # Content drawn at p + accum: the window over layer coords moves by -accum.
        self.assertAlmostEqual(after.left - before.left, -20.0, places=3)
        self.assertAlmostEqual(after.bottom - before.bottom, 10.0, places=3)

    def test_zoom_response(self):
        far = canvas.layers.create("far", zoom_response=0.5)
        canvas.zoom_to(3)                            # layer zoom 1 + 2 * 0.5 = 2
        v = far.view
        self.assertAlmostEqual(v.width, self.W / 2, places=3)
        self.assertAlmostEqual(v.height, self.H / 2, places=3)
        self.assertAlmostEqual(v.center.x, self.W / 2, places=3)

    def test_rotated_camera_is_over_inclusive(self):
        layer = canvas.layers.create("half", pan_response=0.5)
        canvas.pan_to(300, 200)
        canvas.rotate_to(30)
        v = layer.view
        m = _engine()._layer_partial_matrix(canvas.layers["half"])
        inv = __import__("skia").Matrix()
        self.assertTrue(m.invert(inv))
        for x, y in ((0, 0), (self.W, 0), (self.W, self.H), (0, self.H), (self.W / 2, self.H / 2)):
            p = inv.mapXY(x, y)
            self.assertLessEqual(v.left - 1e-6, p.x())
            self.assertGreaterEqual(v.right + 1e-6, p.x())
            self.assertLessEqual(v.bottom - 1e-6, p.y())
            self.assertGreaterEqual(v.top + 1e-6, p.y())

    def test_view_maps_onto_the_screen(self):
        # The draw matrix sends the view's corners to the screen corners.
        layer = canvas.layers.create("par", pan_response=0.4, zoom_response=0.7, scroll=(5, 0))
        canvas.pan_to(777, -333)
        canvas.zoom_to(1.6)
        _engine().advance_layer_scroll(0.0)
        _engine().advance_layer_scroll(0.5)
        v = layer.view
        m = _engine()._layer_partial_matrix(canvas.layers["par"])
        p0 = m.mapXY(v.left, v.bottom)
        p1 = m.mapXY(v.right, v.top)
        self.assertAlmostEqual(min(p0.x(), p1.x()), 0.0, places=2)
        self.assertAlmostEqual(max(p0.x(), p1.x()), self.W, places=2)
        self.assertAlmostEqual(min(p0.y(), p1.y()), 0.0, places=2)
        self.assertAlmostEqual(max(p0.y(), p1.y()), self.H, places=2)

    def test_fresh_snapshot(self):
        layer = canvas.layers.create("montes", pan_response=0.3)
        a = layer.view
        canvas.pan_to(1000, 0)
        b = layer.view
        self.assertIsNot(a, b)
        self.assertNotAlmostEqual(a.left, b.left)

    def test_view_is_read_only(self):
        layer = canvas.layers.create("montes", pan_response=0.3)
        with self.assertRaisesRegex(AttributeError, "read-only"):
            layer.view = Box._from_aabb(0, 0, 1, 1)
        self.assertNotIn("view", vars(layer))


class TestViewInUpdate(_LayerCleanup, SystemTestCase, unittest.TestCase):
    """B2 + P1: ``layer.view`` read in ``update`` matches the frame that draws."""

    def test_update_view_matches_this_frames_draw_matrix(self):
        layer = canvas.layers.create("nuvens", pan_response=0.5, scroll=(100.0, 0.0))
        seen = []

        def update(dt):
            canvas.pan_to(canvas.pan_x + 10, canvas.pan_y)
            seen.append((layer.view.left,
                         _engine()._layer_partial_matrix(canvas.layers["nuvens"])))

        self.w.on_update(update)
        self.w.step(6, dt=0.1)
        left, m_update = seen[-1]
        # The matrix draw will use (after the process tick) is the same one.
        m_draw = _engine()._layer_partial_matrix(canvas.layers["nuvens"])
        p = m_update.mapXY(left, 0.0)
        q = m_draw.mapXY(left, 0.0)
        self.assertAlmostEqual(p.x(), q.x(), places=4)
        self.assertAlmostEqual(p.x(), 0.0, places=3)


class TestLiveScroll(_ViewCase):
    """P3: ``layer.scroll`` reads and writes the rate on non-neutral layers."""

    def test_read_is_the_create_rate(self):
        layer = canvas.layers.create("nuvens", scroll=(0, -180))
        self.assertEqual(layer.scroll, (0.0, -180.0))
        self.assertEqual(canvas.layers.create("montes", pan_response=0.3).scroll, (0.0, 0.0))
        self.assertEqual(canvas.layers["default"].scroll, (0.0, 0.0))

    def test_write_changes_speed_without_a_jump(self):
        layer = canvas.layers.create("nuvens", scroll=(100.0, 0.0))
        eng = _engine()
        eng.advance_layer_scroll(0.0)
        eng.advance_layer_scroll(1.0)                 # +100
        layer.scroll = (10.0, 5.0)
        self.assertEqual(layer._scroll_state.accum, (100.0, 0.0))   # no pop at the write
        eng.advance_layer_scroll(2.0)                 # +10, +5
        ax, ay = layer._scroll_state.accum
        self.assertAlmostEqual(ax, 110.0, places=6)
        self.assertAlmostEqual(ay, 5.0, places=6)
        self.assertEqual(layer.scroll, (10.0, 5.0))

    def test_zero_stops_and_classification_stays(self):
        layer = canvas.layers.create("nuvens", scroll=(100.0, 0.0))
        layer.scroll = (0, 0)
        eng = _engine()
        eng.advance_layer_scroll(0.0)
        eng.advance_layer_scroll(1.0)
        self.assertEqual(layer._scroll_state.accum, (0.0, 0.0))
        # Still a decoration layer: (0, 0) written later does not make it neutral.
        self.assertFalse(layer._is_neutral_response)
        from scena.registry import ParallaxLayerError
        from scena.shapes import Circle
        with self.assertRaises(ParallaxLayerError):
            Circle(center=(0, 0), radius=5, layer="nuvens").collidable = True
        layer.scroll = (30, 0)                        # restart
        eng.advance_layer_scroll(2.0)
        self.assertAlmostEqual(layer._scroll_state.accum[0], 30.0, places=6)

    def test_neutral_layer_raises_with_the_create_fix(self):
        canvas.layers.create("pista", below="default")
        for name in ("pista", "default", "top", "ui"):
            layer = canvas.layers[name]
            with self.subTest(layer=name):
                with self.assertRaises(ValueError) as cm:
                    layer.scroll = (0, -40)
                self.assertIn(f"canvas.layers.create({name!r}, scroll=", str(cm.exception))
                self.assertEqual(layer.scroll, (0.0, 0.0))
                self.assertTrue(layer._is_neutral_response)

    def test_bad_values_raise_and_keep_the_rate(self):
        layer = canvas.layers.create("nuvens", scroll=(1.0, 2.0))
        for bad, exc in ((5, TypeError), (True, TypeError), ("ab", TypeError),
                         ((1, 2, 3), TypeError), ({"x": 1}, TypeError), (None, TypeError),
                         ((math.nan, 0), ValueError), ((0, math.inf), ValueError)):
            with self.subTest(bad=bad):
                with self.assertRaises(exc):
                    layer.scroll = bad
                self.assertEqual(layer.scroll, (1.0, 2.0))

    def test_create_uses_the_same_check(self):
        for bad, exc in ((5, TypeError), ("ab", TypeError), ((1, 2, 3), TypeError),
                         ((math.nan, 0), ValueError)):
            with self.subTest(bad=bad):
                with self.assertRaises(exc):
                    canvas.layers.create("x", scroll=bad)
                self.assertNotIn("x", canvas.layers)

    def test_chase_on_the_pair(self):
        from scena import chase
        layer = canvas.layers.create("nuvens", scroll=(0, -180))
        for _ in range(200):
            layer.scroll = chase(layer.scroll, (0, 0), 3, dt=1 / 60)
        sx, sy = layer.scroll
        self.assertAlmostEqual(sx, 0.0, places=3)
        self.assertAlmostEqual(sy, 0.0, places=1)


if __name__ == "__main__":
    unittest.main()
