"""
Reserved ``ui`` view-space layer: camera-immune draw/hit, no collision / SpatialFx.

Run headless:

    python -m unittest tests.test_ui_layer -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import canvas, collide, init
from scena.canvas import ScenaCanvas
from scena.orchestration import ShapeInteractionManager
from scena.registry import BUILT_IN_LAYERS, UI_LAYER, UiLayerError
from scena.shapes import Circle
from scena.spatial_fx import Fire


def _engine():
    return ScenaCanvas.get_current()


def _registry():
    return _engine().registry


class UiLayerTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        # Full-suite leftovers stay on builtin layers — init() does not wipe them.
        # The wipe also takes the framework's HUD labels: rebuild them after
        # the test, so later modules in one process get live ones (bug O3).
        _registry().destroy_all()
        from scena.orchestration import ScenaFramework
        self.addCleanup(ScenaFramework.get_instance()._build_system_labels)
        self._owned = []
        self.sim = ShapeInteractionManager(_registry())

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
        canvas.reset_view()
        try:
            canvas.effects.clear()
        except Exception:
            pass

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestBuiltinUi(UiLayerTestCase):
    def test_builtin_set_includes_ui(self):
        self.assertEqual(set(BUILT_IN_LAYERS), {"top", "default", "ui"})
        self.assertIn("ui", canvas.layers)
        info = {row["name"]: row for row in canvas.layers.list()}
        self.assertEqual(info["ui"]["z"], 102)

    def test_cannot_delete_ui(self):
        with self.assertRaises(ValueError):
            canvas.layers["ui"].delete()

    def test_cannot_set_post_fx_ui(self):
        with self.assertRaises(ValueError):
            canvas.layers["ui"].post_fx = False

    def test_cannot_create_above_ui(self):
        with self.assertRaises(ValueError):
            canvas.layers.create("hud_above", above="ui")


class TestUiVsWorldCamera(UiLayerTestCase):
    def test_ui_not_in_camera_draw_walk(self):
        ui_c = self.track(Circle(center=(100, 100), radius=20, layer="ui"))
        world = self.track(Circle(center=(100, 100), radius=20))
        names = [layer.name for layer in _registry().layers.iter_draw_order()]
        self.assertNotIn("ui", names)
        eng = _engine()
        # Draw world layers only — ui object must not be visited.
        # Plain Graphics skip ``_draw_object`` and go through ``_draw_plain_object``.
        visited = []
        orig_draw = eng._draw_object
        orig_plain = eng._draw_plain_object

        def spy_draw(obj):
            visited.append(obj)
            return orig_draw(obj)

        def spy_plain(obj):
            visited.append(obj)
            return orig_plain(obj)

        eng._draw_object = spy_draw
        eng._draw_plain_object = spy_plain
        try:
            eng.draw()
        finally:
            eng._draw_object = orig_draw
            eng._draw_plain_object = orig_plain
        self.assertIn(world, visited)
        self.assertNotIn(ui_c, visited)

    def test_ui_cull_always_passes(self):
        eng = _engine()
        canvas.cull_offscreen = True
        far = self.track(Circle(center=(50000, 50000), radius=10, layer="ui"))
        ui_layer = _registry().layers.get(UI_LAYER)
        self.assertTrue(eng._passes_cull(far, layer=ui_layer))
        canvas.cull_offscreen = False


class TestUiHit(UiLayerTestCase):
    def test_click_hits_ui_in_view_coords(self):
        ui_c = self.track(Circle(center=(200, 300), radius=40, layer="ui"))
        ui_c.clickable = True
        # After pan, world mouse at (200,300) would miss a world circle at
        # design (200,300); ui still hits at view (200,300).
        canvas.pan_by(150, 80)
        hit = self.sim.hit_test_ui(200, 300, pressable=True)
        self.assertIs(hit, ui_c)
        # World hit-test at the same *view* numbers is wrong space — use world.
        # At view (200,300) after pan the world point is elsewhere; ui circle
        # must not appear in world interactive walk.
        world_hits = list(_registry().iter_interactive_hit_order())
        self.assertNotIn(ui_c, world_hits)

    def test_world_interactive_skips_ui(self):
        ui_c = self.track(Circle(center=(50, 50), radius=20, layer="ui"))
        ui_c.clickable = True
        world = self.track(Circle(center=(50, 50), radius=20))
        world.clickable = True
        order = list(_registry().iter_interactive_hit_order())
        self.assertIn(world, order)
        self.assertNotIn(ui_c, order)
        ui_order = list(_registry().iter_ui_interactive_hit_order())
        self.assertEqual(ui_order, [ui_c])


class TestUiCollisionForbidden(UiLayerTestCase):
    def test_collidable_raises(self):
        c = self.track(Circle(center=(10, 10), radius=5, layer="ui"))
        with self.assertRaises(UiLayerError):
            c.collidable = True

    def test_collide_decorator_raises(self):
        a = self.track(Circle(center=(0, 0), radius=10, layer="ui", group="ui_g"))
        b = self.track(Circle(center=(5, 0), radius=10, group="world_g"))

        with self.assertRaises(UiLayerError):

            @collide(a, b)
            def _on_hit(me, other, info):
                pass

    def test_move_collidable_to_ui_raises(self):
        c = self.track(Circle(center=(0, 0), radius=5))
        c.collidable = True
        with self.assertRaises(UiLayerError):
            c.layer = "ui"


class TestUiSpatialFxForbidden(UiLayerTestCase):
    def test_construct_on_ui_raises(self):
        with self.assertRaises(UiLayerError):
            Fire(center=(100, 100), layer="ui")

    def test_using_ui_default_raises(self):
        with canvas.layers.using("ui"):
            with self.assertRaises(UiLayerError):
                Fire(center=(50, 50))

    def test_move_spatial_to_ui_raises(self):
        fx = self.track(Fire(center=(100, 100)))
        with self.assertRaises(UiLayerError):
            fx.layer = "ui"


class TestUiInteractiveAllowed(UiLayerTestCase):
    def test_clickable_on_ui_ok(self):
        c = self.track(Circle(center=(40, 40), radius=15, layer="ui"))
        c.clickable = True
        self.assertTrue(c.clickable)
        self.assertIn(c, _registry().layers["ui"]._interactive)


if __name__ == "__main__":
    unittest.main()
