"""
Parallax layers: guards, draw wiring, fast path, cull exemption, formulas.

Designed to catch partial-mutation and CTM-wiring bugs, not just happy paths.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skia

from scena import canvas, collide, group, init
from scena.camera_response import partial_camera_matrix
from scena.canvas import ScenaCanvas
from scena.collision import Collider, get_collision_system
from scena.registry import BUILT_IN_LAYERS, ParallaxLayerError
from scena.shapes import Circle, Line, Point
from scena.spatial_fx import Rain
from scena.state import Attribute, get_scena_system


def _registry():
    return ScenaCanvas.get_current().registry


def _engine():
    return ScenaCanvas.get_current()


class ParallaxTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        self._owned = []
        # Isolate collision system state between tests.
        sys = get_collision_system()
        sys._colliders.clear()
        sys._pair_handlers.clear()
        sys._prev_contacts.clear()
        sys._resolve_cache.clear()

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
        # RenderEndToEnd leaves camera zoom/pan; do not leak into later modules.
        canvas.reset_view()
        sys = get_collision_system()
        sys._colliders.clear()
        sys._pair_handlers.clear()

    def track(self, shape):
        self._owned.append(shape)
        return shape


class TestGuardsInteractive(ParallaxTestCase):
    def test_clickable_raises_and_no_partial_mutation(self):
        canvas.layers.create("bg", pan_response=0.4)
        c = self.track(Circle(center=(0, 0), radius=10, layer="bg"))
        with self.assertRaises(ParallaxLayerError):
            c.clickable = True
        self.assertFalse(c.clickable)
        self.assertNotIn(c, _registry().layers["bg"]._interactive)

    def test_draggable_droppable_wheel_rotate(self):
        canvas.layers.create("bg", pan_response=0.4)
        c = self.track(Circle(center=(0, 0), radius=10, layer="bg"))
        for flag in ("draggable", "droppable", "wheel_rotate"):
            with self.subTest(flag=flag):
                with self.assertRaises(ParallaxLayerError):
                    setattr(c, flag, True)
                self.assertFalse(getattr(c, flag))

    def test_collidable_raises_collider_none(self):
        canvas.layers.create("bg", pan_response=0.4)
        c = self.track(Circle(center=(0, 0), radius=10, layer="bg"))
        with self.assertRaises(ParallaxLayerError):
            c.collidable = True
        self.assertFalse(c.collidable)
        self.assertIsNone(c._collider)
        self.assertEqual(get_collision_system()._colliders, [])

    def test_on_collide_raises(self):
        canvas.layers.create("bg", pan_response=0.4)
        c = self.track(Circle(center=(0, 0), radius=10, layer="bg"))

        def fn(me, other, info):
            pass

        with self.assertRaises(ParallaxLayerError):
            c.on_collide = fn
        self.assertIsNone(c._collider)

    def test_on_hover_raises_and_a_hover_shape_cannot_move_in(self):
        """Hover is pointer interaction (interaction campaign, class 10)."""
        canvas.layers.create("bg", pan_response=0.4)
        c = self.track(Circle(center=(0, 0), radius=10, layer="bg"))
        for name in ("on_hover", "on_hover_exit"):
            with self.subTest(flag=name):
                with self.assertRaises(ParallaxLayerError):
                    setattr(c, name, lambda shape: None)
                self.assertIsNone(getattr(c, name))
        self.assertNotIn(c, _registry().layers["bg"]._interactive)
        d = self.track(Circle(center=(0, 0), radius=10))
        d.on_hover = lambda shape: None
        with self.assertRaises(ParallaxLayerError):
            d.layer = "bg"
        self.assertEqual(d.layer, "default")

    def test_leave_playfield_never_fires_for_a_parallax_item(self):
        """Decoration moves with its layer: a leave edge would be meaningless
        (documented in Canvas Design, parallax-layer invariant)."""
        from scena import leave_playfield
        from scena.bounds import get_bounds_system
        canvas.layers.create("bg", pan_response=0.4)
        fired = []
        leave_playfield("deco")(lambda item: fired.append(item))
        c = self.track(Circle(center=(0, 0), radius=10, layer="bg", group="deco"))
        get_bounds_system().step()
        c.move_to(99999, 0)
        get_bounds_system().step()
        get_bounds_system().step()
        self.assertEqual(fired, [])

    def test_point_handle_raises(self):
        canvas.layers.create("bg", pan_response=0.4)
        p = self.track(Point(1, 2, layer="bg"))
        with self.assertRaises(ParallaxLayerError):
            p.handle = True
        self.assertFalse(p.draggable)


class TestGuardsCollisionAllOrNothing(ParallaxTestCase):
    def test_mixed_explicit_collider(self):
        canvas.layers.create("bg", pan_response=0.4)
        a = self.track(Circle(center=(0, 0), radius=10, layer="bg"))
        b = self.track(Circle(center=(30, 0), radius=10))  # default
        colliders_before = list(get_collision_system()._colliders)
        with self.assertRaises(ParallaxLayerError):
            Collider([a, b])
        self.assertEqual(get_collision_system()._colliders, colliders_before)
        self.assertIsNone(a._collider)
        self.assertIsNone(b._collider)
        self.assertFalse(b.collidable)

    def test_collide_decorator_unchanged_on_raise(self):
        canvas.layers.create("bg", pan_response=0.4)
        tree = self.track(Circle(center=(0, 0), radius=10, layer="bg"))
        player = self.track(Circle(center=(40, 0), radius=10))
        sys = get_collision_system()
        handlers_before = list(sys._pair_handlers)
        colliders_before = list(sys._colliders)

        with self.assertRaises(ParallaxLayerError):

            @collide(tree, player)
            def _on(me, other, info):
                pass

        self.assertEqual(sys._pair_handlers, handlers_before)
        self.assertEqual(sys._colliders, colliders_before)
        self.assertIsNone(player._collider)
        self.assertFalse(player.collidable)

    def test_collide_mixed_group_transactional(self):
        canvas.layers.create("bg", pan_response=0.4)
        px = self.track(Circle(center=(0, 0), radius=10, layer="bg", group="mixed"))
        norm = self.track(Circle(center=(40, 0), radius=10, group="mixed"))
        player = self.track(Circle(center=(80, 0), radius=10))
        sys = get_collision_system()
        handlers_before = list(sys._pair_handlers)

        with self.assertRaises(ParallaxLayerError):

            @collide(group["mixed"], player)
            def _on(me, other, info):
                pass

        self.assertEqual(sys._pair_handlers, handlers_before)
        self.assertIsNone(norm._collider)
        self.assertFalse(norm.collidable)
        self.assertIsNone(player._collider)


class TestGuardsLayerMove(ParallaxTestCase):
    def test_move_clickable_into_parallax_preserves_layer(self):
        canvas.layers.create("bg", pan_response=0.4)
        c = self.track(Circle(center=(0, 0), radius=10))
        c.clickable = True
        with self.assertRaises(ParallaxLayerError):
            c.layer = "bg"
        self.assertEqual(c.layer, "default")
        self.assertTrue(c.clickable)

    def test_move_collidable_into_parallax_preserves_layer(self):
        canvas.layers.create("bg", pan_response=0.4)
        c = self.track(Circle(center=(0, 0), radius=10))
        c.collidable = True
        with self.assertRaises(ParallaxLayerError):
            c.layer = "bg"
        self.assertEqual(c.layer, "default")
        self.assertTrue(c.collidable)

    def test_ban_is_layer_scoped_not_sticky(self):
        canvas.layers.create("bg", pan_response=0.4)
        c = self.track(Circle(center=(0, 0), radius=10, layer="bg"))
        c.layer = "default"
        c.clickable = True  # must succeed after leave
        self.assertTrue(c.clickable)


class TestGuardsSpatialFx(ParallaxTestCase):
    def test_rain_collidable_blocked(self):
        canvas.layers.create("bg", pan_response=0.3)
        rain = self.track(Rain(center=(0, 0), width=80, height=80, layer="bg"))
        with self.assertRaises(ParallaxLayerError):
            rain.collidable = True
        self.assertFalse(rain.collidable)


class TestFastPath(ParallaxTestCase):
    def test_zero_swaps_without_parallax_layers(self):
        for i in range(5):
            self.track(Circle(center=(i * 10, 0), radius=5))
        canvas.layers.create("guide", z=1)  # neutral custom layer
        self.track(Circle(center=(0, 50), radius=5, layer="guide"))
        eng = _engine()
        eng.draw(t=0.0)
        self.assertEqual(eng._layer_ctm_swaps, 0)
        self.assertFalse(_registry().layers.has_parallax_layers)

    def test_swaps_equal_non_neutral_layer_count(self):
        canvas.layers.create("a", pan_response=0.2)
        canvas.layers.create("b", pan_response=0.5)
        canvas.layers.create("c", z=2)  # neutral
        self.track(Circle(center=(0, 0), radius=5, layer="a"))
        self.track(Circle(center=(10, 0), radius=5, layer="b"))
        self.track(Circle(center=(20, 0), radius=5, layer="c"))
        eng = _engine()
        eng.draw(t=0.0)
        self.assertEqual(eng._layer_ctm_swaps, 2)

    def test_flag_clears_when_last_parallax_deleted(self):
        canvas.layers.create("bg", pan_response=0.3)
        self.assertTrue(_registry().layers.has_parallax_layers)
        canvas.layers["bg"].delete(destroy_shapes=True)
        self.assertFalse(_registry().layers.has_parallax_layers)
        eng = _engine()
        eng.draw(t=0.0)
        self.assertEqual(eng._layer_ctm_swaps, 0)


class TestCullExemption(ParallaxTestCase):
    def test_parallax_shape_not_culled_outside_global_bounds(self):
        canvas.layers.create("bg", pan_response=0.0)  # screen-locked
        eng = _engine()
        eng.cull_offscreen = True
        # Far outside design space — neutral would cull; parallax must not.
        far = self.track(Circle(center=(50000, 50000), radius=10, layer="bg"))
        layer = _registry().layers["bg"]
        self.assertTrue(eng._passes_cull(far, layer=layer))

    def test_neutral_still_culled(self):
        eng = _engine()
        eng.cull_offscreen = True
        far = self.track(Circle(center=(50000, 50000), radius=10))
        layer = _registry().layers["default"]
        self.assertFalse(eng._passes_cull(far, layer=layer))


class TestRenderEndToEnd(ParallaxTestCase):
    def _raster_and_map(self, matrix, world_xy):
        return matrix.mapXY(float(world_xy[0]), float(world_xy[1]))

    def test_partial_matrix_wired_into_draw_path(self):
        """Predict screen placement via partial_camera_matrix; draw uses same math."""
        canvas.layers.create("bg", pan_response=0.4, zoom_response=0.3)
        eng = _engine()
        eng.pan_to(600, 450)
        eng.zoom_to(1.5)
        eng._sync_camera()
        predicted = eng._layer_partial_matrix(_registry().layers["bg"])
        reference = partial_camera_matrix(
            cx=500,
            cy=400,
            look_x=eng.pan_x,
            look_y=eng.pan_y,
            zoom=eng.zoom,
            rotation_deg=eng.rotation,
            rest_x=eng.pan_rest_x,
            rest_y=eng.pan_rest_y,
            pan_response=0.4,
            zoom_response=0.3,
            rotation_response=1.0,
        )
        # Draw path helper equals math helper.
        pt = (100.0, 50.0)
        pa = predicted.mapXY(*pt)
        pb = reference.mapXY(*pt)
        self.assertAlmostEqual(pa.x(), pb.x(), places=5)
        self.assertAlmostEqual(pa.y(), pb.y(), places=5)
        # And differs from full camera.
        full = eng.camera_matrix()
        pf = full.mapXY(*pt)
        self.assertTrue(abs(pf.x() - pa.x()) > 1.0 or abs(pf.y() - pa.y()) > 1.0)

    def test_screen_locked_layer_ignores_pan(self):
        canvas.layers.create("locked", pan_response=0.0, zoom_response=0.0, rotation_response=0.0)
        eng = _engine()
        m0 = eng._layer_partial_matrix(_registry().layers["locked"])
        eng.pan_to(700, 500)
        eng.zoom_to(2.0)
        eng._sync_camera()
        m1 = eng._layer_partial_matrix(_registry().layers["locked"])
        for xy in ((0, 0), (100, -50), (400, 300)):
            p0 = m0.mapXY(*xy)
            p1 = m1.mapXY(*xy)
            self.assertAlmostEqual(p0.x(), p1.x(), places=4)
            self.assertAlmostEqual(p0.y(), p1.y(), places=4)

    def test_scroll_accumulates_over_time(self):
        canvas.layers.create("scroll", pan_response=1.0, scroll=(20.0, -10.0))
        eng = _engine()
        layer = _registry().layers["scroll"]
        eng.advance_layer_scroll(0.0)
        eng.advance_layer_scroll(0.5)
        ax, ay = layer._scroll_state.accum
        self.assertAlmostEqual(ax, 10.0, places=4)
        self.assertAlmostEqual(ay, -5.0, places=4)
        # Matrix includes scroll as pre-translate of world.
        m = eng._layer_partial_matrix(layer)
        # Without scroll, identity-ish at rest maps center correctly + scroll shift.
        p = m.mapXY(0.0, 0.0)
        m_no = partial_camera_matrix(
            cx=500, cy=400,
            look_x=eng.pan_x, look_y=eng.pan_y,
            zoom=eng.zoom, rotation_deg=eng.rotation,
            rest_x=eng.pan_rest_x, rest_y=eng.pan_rest_y,
        )
        m_no.preTranslate(10.0, -5.0)
        p2 = m_no.mapXY(0.0, 0.0)
        self.assertAlmostEqual(p.x(), p2.x(), places=4)
        self.assertAlmostEqual(p.y(), p2.y(), places=4)

    def test_draw_does_not_advance_scroll(self):
        # B2: scroll is world state, integrated in the frame tick. Painting
        # (twice per frame with post FX, or never in a headless run) must not
        # move it.
        canvas.layers.create("scroll", scroll=(20.0, 0.0))
        eng = _engine()
        layer = _registry().layers["scroll"]
        eng.advance_layer_scroll(0.0)
        eng.draw(t=0.5)
        eng.draw(t=1.0)
        self.assertEqual(layer._scroll_state.accum, (0.0, 0.0))

    def test_neutral_layers_never_scroll(self):
        canvas.layers.create("still")
        eng = _engine()
        eng.advance_layer_scroll(0.0)
        eng.advance_layer_scroll(1.0)
        self.assertEqual(_registry().layers["still"]._scroll_state.accum, (0.0, 0.0))

    def test_rotation_response_half(self):
        canvas.layers.create("half", rotation_response=0.5)
        eng = _engine()
        eng.rotate_to(90.0)
        eng._sync_camera()
        m = eng._layer_partial_matrix(_registry().layers["half"])
        expected = partial_camera_matrix(
            cx=500, cy=400,
            look_x=eng.pan_x, look_y=eng.pan_y,
            zoom=eng.zoom, rotation_deg=90.0,
            rest_x=eng.pan_rest_x, rest_y=eng.pan_rest_y,
            rotation_response=0.5,
        )
        p1 = m.mapXY(100, 0)
        p2 = expected.mapXY(100, 0)
        self.assertAlmostEqual(p1.x(), p2.x(), places=4)
        self.assertAlmostEqual(p1.y(), p2.y(), places=4)


class TestCrossLayerFormulas(ParallaxTestCase):
    def test_formula_reads_world_coords_from_parallax_shape(self):
        canvas.layers.create("bg", pan_response=0.3)
        tree = self.track(Circle(center=(40, 80), radius=5, layer="bg"))
        other = self.track(Circle(center=(0, 0), radius=5))
        other.center["x"] @= lambda: tree.center.x
        get_scena_system().flush()
        self.assertAlmostEqual(float(other.center.x), 40.0, places=5)
        tree.center = (100, 80)
        get_scena_system().flush()
        self.assertAlmostEqual(float(other.center.x), 100.0, places=5)

    def test_line_linking_across_layers(self):
        canvas.layers.create("bg", pan_response=0.35)
        tree = self.track(Circle(center=(-50, 20), radius=5, layer="bg"))
        player = self.track(Circle(center=(50, -20), radius=5))
        line = self.track(Line(p1=lambda: tree.center, p2=lambda: player.center))
        get_scena_system().flush()
        self.assertAlmostEqual(float(line.p1.x), -50.0, places=5)
        self.assertAlmostEqual(float(line.p2.x), 50.0, places=5)
        tree.center = (-10, 30)
        get_scena_system().flush()
        self.assertAlmostEqual(float(line.p1.x), -10.0, places=5)
        self.assertAlmostEqual(float(line.p1.y), 30.0, places=5)


if __name__ == "__main__":
    unittest.main()
