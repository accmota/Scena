"""
Canvas API tests: design size, background, camera (zoom/pan/rotate/frame_to),
game_view / ui_view, facade surface, and screen↔world consistency with the camera matrix.

Run headless (no window):

    python -m unittest tests.test_canvas -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import given, strategies as hst  # noqa: E402

from scena import canvas, init, mouse
from scena.canvas import Canvas, ScenaCanvas, VisibleBounds
from scena.color import Color
from scena.easing import lerp
from scena.shapes import Point, Rect, Circle
from scena.scenamath import Vec2
from scena.orchestration import ScenaFramework

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


class CanvasTestCase(unittest.TestCase):
    def setUp(self):
        # Ensure a known design size for every test.
        init(width=1000, height=800)
        canvas.reset_view()

    def assertAlmostPoint(self, got, x, y, places=5):
        gx, gy = got if isinstance(got, tuple) else (got.x(), got.y())
        self.assertAlmostEqual(gx, x, places=places)
        self.assertAlmostEqual(gy, y, places=places)


class TestCanvasFacade(CanvasTestCase):
    def test_global_canvas_is_facade(self):
        self.assertIsInstance(canvas, Canvas)
        self.assertIsInstance(canvas._engine, ScenaCanvas)
        self.assertIs(canvas._engine, ScenaCanvas.get_current())

    def test_design_size_readonly(self):
        self.assertEqual(canvas.width, 1000)
        self.assertEqual(canvas.height, 800)
        self.assertAlmostEqual(canvas.aspect_ratio, 1000 / 800)
        with self.assertRaises(AttributeError):
            canvas.width = 500  # type: ignore[misc]

    def test_init_resizes_design_space(self):
        init(width=640, height=480)
        self.assertEqual(canvas.width, 640)
        self.assertEqual(canvas.height, 480)
        self.assertAlmostEqual(canvas.aspect_ratio, 640 / 480)
        # Facade identity is stable across rebind.
        self.assertIsInstance(canvas, Canvas)

    def test_no_module_set_background(self):
        import scena
        self.assertFalse(hasattr(scena, 'set_background'))

    def test_star_import_includes_public_helpers(self):
        import scena
        for name in (
            "ComposeFx", "vec_from_angle", "chance",
            "chase", "deadzone",
            "middle_point", "distance", "heading", "nearest",
            "intersections", "intersection", "closest_point",
            "LinkedAttributeError", "ui",
            "Wallpaper", "SkyGradient",
        ):
            self.assertIn(name, scena.__all__)
            self.assertTrue(hasattr(scena, name), name)

    def test_star_import_omits_internals(self):
        import scena
        hidden = {
            'PaintState', 'ScenaFramework', 'ScenaCanvas', 'Registry',
            'ContainerSlot', 'ephemeral_creation', 'get_scena_system',
            'tick_all_spatial_fx', 'PostFxStack', 'PostEffect', 'HitFeedback',
            'BackgroundStack', 'BackgroundField', 'BackgroundImage', 'CompiledVisual', 'FilterEffect',
            'ColorResolveKind', 'LayersFacade',
            'EventSystem', 'EventRegistration', 'PadModel', 'BeamModel',
            'next_quality', 'QUALITY_ORDER', 'collide_enter',
            'SpaceBox',
            'BlendMode', 'DashStyle', 'LineCapStyle', 'LineJoinStyle',
            'TileMode', 'BackgroundFit', 'GradientType',
        }
        self.assertTrue(hidden.isdisjoint(scena.__all__))
        for name in hidden:
            self.assertFalse(hasattr(scena, name), name)

    def test_star_import_avoids_stdlib_collisions(self):
        """``from scena import *`` must not shadow pathlib or dangerous builtins.

        Author globals that Scena installs on ``builtins`` (``st``, ``canvas``, …)
        are intentional and listed in ``__all__``; they are not collisions.
        """
        import scena

        exported = set(scena.__all__)
        pathlib_public = {
            "Path", "PurePath", "PosixPath", "WindowsPath",
            "PurePosixPath", "PureWindowsPath",
        }
        self.assertEqual(
            sorted(exported & pathlib_public), [],
            f"scena.__all__ shadows pathlib: {sorted(exported & pathlib_public)}",
        )
        dangerous_builtins = {
            "open", "input", "print", "type", "id", "object", "str", "int", "float",
            "bool", "list", "dict", "set", "tuple", "bytes", "bytearray",
            "map", "filter", "zip", "enumerate", "reversed", "sorted",
            "range", "slice", "len", "sum", "min", "max", "abs", "round", "pow",
            "all", "any", "iter", "next", "callable", "isinstance", "issubclass",
            "getattr", "setattr", "hasattr", "delattr", "property",
            "staticmethod", "classmethod", "super", "compile", "eval", "exec",
            "quit", "exit", "vars", "dir", "help", "hash", "repr",
        }
        self.assertEqual(
            sorted(exported & dangerous_builtins), [],
            f"scena.__all__ shadows builtins: {sorted(exported & dangerous_builtins)}",
        )
        self.assertIn("Track", exported)
        self.assertNotIn("Path", exported)


class TestBackground(CanvasTestCase):
    def test_background_assign_rgb(self):
        canvas.background = (0.1, 0.2, 0.3)
        src = canvas.background.base.source
        self.assertAlmostEqual(src._r, 0.1, places=5)
        self.assertAlmostEqual(src._g, 0.2, places=5)
        self.assertAlmostEqual(src._b, 0.3, places=5)

    def test_background_assign_named_and_base(self):
        canvas.background = 'red'
        self.assertAlmostEqual(canvas.background.base.source._r, 1.0, places=5)
        canvas.background.base = Color(0.5, 0.5, 0.5)
        self.assertAlmostEqual(canvas.background.base.source._r, 0.5, places=5)

    def test_background_assign_replaces_base_keeps_stack(self):
        from scena.background import BackgroundStack
        canvas.background = Color(0.5, 0.5, 0.5)
        self.assertIsInstance(canvas.background, BackgroundStack)
        self.assertAlmostEqual(canvas.background.base.source._r, 0.5, places=5)

    def test_background_assign_color_object(self):
        from scena.background_kinds import Wallpaper
        c = Color(0.2, 0.3, 0.4)
        canvas.background = c
        self.assertIsInstance(canvas.background.base, Wallpaper)
        self.assertIs(canvas.background.base.source, c)

    def test_background_assign_gradient(self):
        from scena.style import Gradient
        from scena.background_kinds import Wallpaper
        canvas.background = Gradient('navy', 'black', angle=90)
        self.assertIsInstance(canvas.background.base, Wallpaper)
        self.assertIsInstance(canvas.background.base.source, Gradient)

        g = Gradient('red', 'blue', type="radial", size=400)
        canvas.background = g
        self.assertIs(canvas.background.base.source, g)

    def test_background_assign_image(self):
        from scena.style import BackgroundImage
        from scena.background_kinds import Wallpaper
        import skia
        info = skia.ImageInfo.Make(64, 64, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().clear(skia.Color4f(0.2, 0.5, 0.9, 1.0))
        img = surf.makeImageSnapshot()

        Wallpaper(img, fit='cover')
        self.assertIsInstance(canvas.background.base, Wallpaper)
        self.assertIsInstance(canvas.background.base.source, BackgroundImage)
        self.assertEqual(canvas.background.base.source.fit, "cover")

        w = Wallpaper(image=img, fit="tile")
        self.assertIs(canvas.background.base, w)
        self.assertEqual(w.source.fit, "tile")

    def test_background_solid_fast_path(self):
        from scena.background_kinds import Wallpaper
        from scena.style import Gradient
        canvas.background = (0.1, 0.1, 0.1)
        self.assertIsInstance(canvas.background.base, Wallpaper)
        self.assertTrue(canvas.background.base._is_plain_solid())
        canvas.background = Gradient('black', 'white')
        self.assertFalse(canvas.background.base._is_plain_solid())
        canvas.background = (0.0, 0.0, 0.0)
        self.assertTrue(canvas.background.base._is_plain_solid())

    def test_background_is_stack_facade(self):
        from scena.background import BackgroundStack
        from scena import Clouds
        self.assertIsInstance(canvas.background, BackgroundStack)
        canvas.background.clear()
        self.assertEqual(len(canvas.background), 0)
        canvas.background.add(Clouds())
        self.assertEqual(len(canvas.background), 1)
        canvas.background.clear()
        self.assertTrue(canvas.background.base is not None)


class TestCameraFastPath(CanvasTestCase):
    def test_inactive_at_identity(self):
        eng = canvas._engine
        self.assertFalse(eng._camera_active)
        self.assertTrue(eng._camera_matrix.isIdentity())

    def test_active_after_zoom_inactive_after_reset(self):
        eng = canvas._engine
        canvas.zoom_to(2.0)
        self.assertTrue(eng._camera_active)
        self.assertFalse(eng._camera_matrix.isIdentity())
        m_before = eng._camera_matrix
        # Same object while unchanged (cached).
        self.assertIs(eng.camera_matrix(), m_before)
        canvas.reset_view()
        self.assertFalse(eng._camera_active)
        self.assertTrue(eng._camera_matrix.isIdentity())

    def test_returns_to_inactive_when_restored(self):
        eng = canvas._engine
        canvas.pan_by(50, 0).pan_by(-50, 0)
        self.assertFalse(eng._camera_active)

    def test_apply_camera_noop_when_inactive(self):
        import skia
        eng = canvas._engine
        surf = skia.Surface(100, 100)
        c = surf.getCanvas()
        c.resetMatrix()
        c.scale(2, 2)
        eng.apply_camera(c)
        # Still only the 2x scale — camera was identity.
        self.assertAlmostEqual(c.getTotalMatrix().getScaleX(), 2.0, places=5)

    def test_matrix_rebuilt_on_mutation(self):
        eng = canvas._engine
        canvas.zoom_to(2.0)
        m1 = eng.camera_matrix()
        canvas.zoom_to(3.0)
        m2 = eng.camera_matrix()
        self.assertIsNot(m1, m2)
        self.assertAlmostEqual(m2.mapXY(600, 400).x(), 800.0, places=4)


class TestCameraIdentity(CanvasTestCase):
    def test_default_camera(self):
        self.assertAlmostEqual(canvas.zoom, 1.0)
        self.assertAlmostEqual(canvas.pan_x, 500.0)
        self.assertAlmostEqual(canvas.pan_y, 400.0)
        self.assertAlmostEqual(canvas.rotation, 0.0)

    def test_identity_matrix_fixes_corners(self):
        m = canvas._engine.camera_matrix()
        self.assertAlmostPoint(m.mapXY(0, 0), 0, 0)
        self.assertAlmostPoint(m.mapXY(1000, 800), 1000, 800)
        self.assertAlmostPoint(m.mapXY(500, 400), 500, 400)

    def test_reset_view(self):
        canvas.zoom_to(3).pan_by(100, 50).rotate_to(45)
        canvas.reset_view()
        self.assertAlmostEqual(canvas.zoom, 1.0)
        self.assertAlmostEqual(canvas.pan_x, 500.0)
        self.assertAlmostEqual(canvas.pan_y, 400.0)
        self.assertAlmostEqual(canvas.rotation, 0.0)


class TestZoom(CanvasTestCase):
    def test_zoom_to_absolute(self):
        canvas.zoom_to(2.5)
        self.assertAlmostEqual(canvas.zoom, 2.5)
        # Center stays fixed under center-pivot zoom.
        m = canvas._engine.camera_matrix()
        self.assertAlmostPoint(m.mapXY(500, 400), 500, 400)
        # A point 100 right of center is 250 from center on screen at 2.5x.
        self.assertAlmostPoint(m.mapXY(600, 400), 750, 400)

    def test_zoom_by_relative(self):
        canvas.zoom_by(2).zoom_by(1.5)
        self.assertAlmostEqual(canvas.zoom, 3.0)

    def test_zoom_without_about_keeps_pan(self):
        # Guia #mundo-camera (PM1): no about= -> the view centre; pan unchanged.
        canvas.pan_to((300.0, 200.0))
        before = (canvas.pan_x, canvas.pan_y)
        canvas.zoom_by(1.1)
        canvas.zoom_to(0.5)
        self.assertAlmostEqual(canvas.pan_x, before[0])
        self.assertAlmostEqual(canvas.pan_y, before[1])

    def test_zoom_about_keeps_point_fixed(self):
        about = (200.0, 100.0)
        m0 = canvas._engine.camera_matrix()
        s0 = m0.mapXY(*about)
        canvas.zoom_to(3.0, about=about)
        m1 = canvas._engine.camera_matrix()
        s1 = m1.mapXY(*about)
        self.assertAlmostPoint(s1, s0.x(), s0.y())

    def test_zoom_about_graphic_keeps_center_fixed(self):
        hero = Circle(center=(200.0, 100.0), radius=12)
        m0 = canvas._engine.camera_matrix()
        s0 = m0.mapXY(200.0, 100.0)
        canvas.zoom_to(3.0, about=hero)
        m1 = canvas._engine.camera_matrix()
        s1 = m1.mapXY(200.0, 100.0)
        self.assertAlmostPoint(s1, s0.x(), s0.y())

    def test_zoom_clamped_positive(self):
        # 0 is a legal write (a timed zoom-out easing through 0 is a
        # documented effect), but the *stored* zoom clamps to _MIN_ZOOM so
        # every reader (canvas.zoom, parallax response, the camera matrix)
        # agrees — a bare 0 would make the camera matrix singular.
        from scena.canvas import _MIN_ZOOM
        canvas.zoom_to(0.0)
        self.assertEqual(canvas.zoom, _MIN_ZOOM)
        self.assertGreater(canvas.zoom, 0.0)

    def test_chainable(self):
        self.assertIs(canvas.zoom_to(2), canvas)
        self.assertIs(canvas.zoom_by(1.1), canvas)


class TestPan(CanvasTestCase):
    def test_pan_to_places_point_at_center(self):
        canvas.pan_to(100, 200)
        self.assertAlmostEqual(canvas.pan_x, 100.0)
        self.assertAlmostEqual(canvas.pan_y, 200.0)
        m = canvas._engine.camera_matrix()
        self.assertAlmostPoint(m.mapXY(100, 200), 500, 400)

    def test_pan_by_moves_content(self):
        # At identity, pan_by(dx, dy) should move world origin's screen pos by (dx, dy).
        m0 = canvas._engine.camera_matrix()
        s0 = m0.mapXY(0, 0)
        canvas.pan_by(40, -20)
        m1 = canvas._engine.camera_matrix()
        s1 = m1.mapXY(0, 0)
        self.assertAlmostEqual(s1.x() - s0.x(), 40.0, places=5)
        self.assertAlmostEqual(s1.y() - s0.y(), -20.0, places=5)

    def test_pan_by_under_zoom(self):
        canvas.zoom_to(2.0)
        m0 = canvas._engine.camera_matrix()
        s0 = m0.mapXY(0, 0)
        canvas.pan_by(10, 0)
        m1 = canvas._engine.camera_matrix()
        s1 = m1.mapXY(0, 0)
        # World shift of 10 at zoom 2 → 20 design pixels on screen.
        self.assertAlmostEqual(s1.x() - s0.x(), 20.0, places=5)

    def _assert_pan_to_100_200(self):
        self.assertAlmostEqual(canvas.pan_x, 100.0)
        self.assertAlmostEqual(canvas.pan_y, 200.0)
        m = canvas._engine.camera_matrix()
        self.assertAlmostPoint(m.mapXY(100, 200), 500, 400)

    def test_pan_to_tuple(self):
        canvas.pan_to((100, 200))
        self._assert_pan_to_100_200()

    def test_pan_to_point(self):
        canvas.pan_to(Point(100, 200))
        self._assert_pan_to_100_200()

    def test_pan_to_vec2(self):
        canvas.pan_to(Vec2(100, 200))
        self._assert_pan_to_100_200()

    def test_pan_to_graphic_uses_center(self):
        hero = Circle(center=(100, 200), radius=12)
        canvas.pan_to(hero)
        self._assert_pan_to_100_200()

    def test_pan_to_mouse(self):
        mouse._update_position(100, 200)
        canvas.pan_to(mouse)
        self._assert_pan_to_100_200()

    def test_pan_to_chase_tuple_without_unpack(self):
        # chase(...) returns a plain (x, y); the * unpack is optional.
        current = (canvas.pan_x, canvas.pan_y)
        canvas.pan_to(lerp(current, (100, 200), 1.0))
        self._assert_pan_to_100_200()
        canvas.reset_view()
        canvas.pan_to(*lerp((canvas.pan_x, canvas.pan_y), (100, 200), 1.0))
        self._assert_pan_to_100_200()

    def test_pan_to_one_number_raises(self):
        with self.assertRaises(TypeError):
            canvas.pan_to(100)

    def test_pan_by_vec2(self):
        m0 = canvas._engine.camera_matrix()
        s0 = m0.mapXY(0, 0)
        canvas.pan_by(Vec2(40, -20))
        m1 = canvas._engine.camera_matrix()
        s1 = m1.mapXY(0, 0)
        self.assertAlmostEqual(s1.x() - s0.x(), 40.0, places=5)
        self.assertAlmostEqual(s1.y() - s0.y(), -20.0, places=5)

    def test_pan_by_tuple(self):
        m0 = canvas._engine.camera_matrix()
        s0 = m0.mapXY(0, 0)
        canvas.pan_by((40, -20))
        m1 = canvas._engine.camera_matrix()
        s1 = m1.mapXY(0, 0)
        self.assertAlmostEqual(s1.x() - s0.x(), 40.0, places=5)
        self.assertAlmostEqual(s1.y() - s0.y(), -20.0, places=5)

    def test_pan_by_point_raises(self):
        with self.assertRaises(TypeError):
            canvas.pan_by(Point(10, 0))

    def test_pan_by_graphic_raises(self):
        hero = Circle(center=(10, 0), radius=8)
        with self.assertRaises(TypeError):
            canvas.pan_by(hero)

    def test_pan_by_mouse_raises(self):
        with self.assertRaises(TypeError):
            canvas.pan_by(mouse)


class TestSetOrigin(CanvasTestCase):
    def test_center_places_origin_at_view_center(self):
        canvas.zoom_to(1.5).rotate_to(10)
        canvas.set_origin('center')
        self.assertAlmostEqual(canvas.pan_x, 0.0, places=5)
        self.assertAlmostEqual(canvas.pan_y, 0.0, places=5)
        # Zoom / rotation preserved
        self.assertAlmostEqual(canvas.zoom, 1.5, places=5)
        self.assertAlmostEqual(canvas.rotation, 10.0, places=5)
        m = canvas._engine.camera_matrix()
        self.assertAlmostPoint(m.mapXY(0, 0), 500, 400)

    def test_corner_restores_identity_pan(self):
        canvas.set_origin('center')
        canvas.set_origin('corner')
        self.assertAlmostEqual(canvas.pan_x, 500.0, places=5)
        self.assertAlmostEqual(canvas.pan_y, 400.0, places=5)
        m = canvas._engine.camera_matrix()
        # Identity pan: world origin maps to design bottom-left
        self.assertAlmostPoint(m.mapXY(0, 0), 0, 0)

    def test_bottom_left_alias(self):
        canvas.set_origin('center')
        canvas.set_origin('bottom_left')
        self.assertAlmostEqual(canvas.pan_x, 500.0, places=5)
        self.assertAlmostEqual(canvas.pan_y, 400.0, places=5)

    def test_invalid_where_raises(self):
        with self.assertRaises(ValueError):
            canvas.set_origin('top')


class TestRotate(CanvasTestCase):
    def test_rotate_to_about_center(self):
        canvas.rotate_to(90)
        self.assertAlmostEqual(canvas.rotation, 90.0)
        m = canvas._engine.camera_matrix()
        # Center fixed.
        self.assertAlmostPoint(m.mapXY(500, 400), 500, 400)
        # Y-up: point above center (500, 500): delta (0, +100)
        # +90° CCW: (0, 100) → (-100, 0) → screen (400, 400)
        p = m.mapXY(500, 500)
        self.assertAlmostPoint(p, 400, 400)

    def test_rotate_by(self):
        canvas.rotate_by(30).rotate_by(15)
        self.assertAlmostEqual(canvas.rotation, 45.0)

    def test_rotate_about_keeps_point_fixed(self):
        about = (300.0, 250.0)
        m0 = canvas._engine.camera_matrix()
        s0 = m0.mapXY(*about)
        canvas.rotate_to(40, about=about)
        m1 = canvas._engine.camera_matrix()
        s1 = m1.mapXY(*about)
        self.assertAlmostPoint(s1, s0.x(), s0.y(), places=4)

    def test_rotate_about_graphic_keeps_center_fixed(self):
        hero = Circle(center=(300.0, 250.0), radius=12)
        m0 = canvas._engine.camera_matrix()
        s0 = m0.mapXY(300.0, 250.0)
        canvas.rotate_to(40, about=hero)
        m1 = canvas._engine.camera_matrix()
        s1 = m1.mapXY(300.0, 250.0)
        self.assertAlmostPoint(s1, s0.x(), s0.y(), places=4)


class TestFrameTo(CanvasTestCase):
    def test_frame_to_rect(self):
        focus = Rect(center=(200, 150), width=200, height=100)
        canvas.frame_to(focus)
        self.assertAlmostEqual(canvas.pan_x, 200.0, places=5)
        self.assertAlmostEqual(canvas.pan_y, 150.0, places=5)
        # Letterbox: min(1000/200, 800/100) = min(5, 8) = 5
        self.assertAlmostEqual(canvas.zoom, 5.0, places=5)
        self.assertAlmostEqual(canvas.rotation, 0.0)

    def test_frame_to_tuple_with_pad(self):
        # Y-up: (left, top, w, h) = (100, 300, 200, 200) → center (200, 200)
        canvas.frame_to((100, 300, 200, 200), pad=0.1)
        self.assertAlmostEqual(canvas.pan_x, 200.0, places=5)
        self.assertAlmostEqual(canvas.pan_y, 200.0, places=5)
        # Effective size 200 * 1.2 = 240; min(1000/240, 800/240) = 800/240
        self.assertAlmostEqual(canvas.zoom, 800 / 240, places=5)

    def test_frame_to_negative_pad_tightens(self):
        focus = Rect(center=(200, 150), width=200, height=200)
        canvas.frame_to(focus, pad=0.0)
        zoom_tight = canvas.zoom
        canvas.frame_to(focus, pad=-0.1)
        # Effective size 200 * 0.8 = 160; min(1000/160, 800/160) = 5
        self.assertAlmostEqual(canvas.zoom, 5.0, places=5)
        self.assertGreater(canvas.zoom, zoom_tight)

    def test_frame_to_rotate_opt_in(self):
        focus = Rect(center=(500, 400), width=100, height=50, angle=30)
        canvas.frame_to(focus, rotate=True)
        self.assertAlmostEqual(canvas.rotation, -30.0, places=5)

    def test_frame_to_box_rotate_reads_angle(self):
        # Regression: Box exposes ``.angle``. frame_to used to read only a
        # Graphic's old ``.rotation`` (absent on Box → silently treated
        # as 0), so `frame_to(rotated_box, rotate=True)` never rotated.
        from scena.box import Box
        focus = Box(p1=(-50, -25), p2=(50, 25))
        focus.angle = 30.0
        canvas.frame_to(focus, rotate=True)
        self.assertAlmostEqual(canvas.rotation, -30.0, places=5)

    def test_frame_to_circle(self):
        # Regression: Circle has no .width/.height and no _oriented_frame,
        # so frame_to(circle) used to raise TypeError.
        focus = Circle(center=(120, 90), radius=40)
        canvas.frame_to(focus)
        self.assertAlmostEqual(canvas.pan_x, 120.0, places=5)
        self.assertAlmostEqual(canvas.pan_y, 90.0, places=5)
        # Diameter 80 → min(1000/80, 800/80) = 10
        self.assertAlmostEqual(canvas.zoom, 10.0, places=5)

    def test_frame_to_line(self):
        from scena import Line
        focus = Line(p1=(0, 0), p2=(200, 300))
        canvas.frame_to(focus)
        self.assertAlmostEqual(canvas.pan_x, 100.0, places=5)
        self.assertAlmostEqual(canvas.pan_y, 150.0, places=5)
        # bbox 200x300 → min(1000/200, 800/300) = min(5, 2.667) = 2.667
        self.assertAlmostEqual(canvas.zoom, 800.0 / 300.0, places=5)

    def test_frame_to_invalid(self):
        with self.assertRaises(TypeError):
            canvas.frame_to((1, 2, 3))
        with self.assertRaises(TypeError):
            canvas.frame_to("nope")
        with self.assertRaises(TypeError):
            canvas.frame_to(42)
        with self.assertRaises(TypeError):
            canvas.frame_to([1, 2, 3])

    def test_frame_to_negative_size_raises(self):
        with self.assertRaises(ValueError):
            canvas.frame_to((0, 800, -50, 30))
        with self.assertRaises(ValueError):
            canvas.frame_to((0, 800, float("nan"), 30))

    def test_zoom_and_pan_reject_nonfinite(self):
        with self.assertRaises(ValueError):
            canvas.zoom_to(float("nan"))
        with self.assertRaises(ValueError):
            canvas.zoom_to(float("inf"))
        with self.assertRaises(ValueError):
            canvas.pan_to(float("nan"), 0)
        from scena.canvas import _MIN_ZOOM
        canvas.zoom_to(0.0)
        self.assertEqual(canvas.zoom, _MIN_ZOOM)
        canvas.reset_view()

    def test_frame_to_none_holds_view(self):
        canvas.zoom_to(2.0).pan_to(100, 80).rotate_to(15)
        before = (canvas.pan_x, canvas.pan_y, canvas.zoom, canvas.rotation)
        out = canvas.frame_to(None)
        self.assertIs(out, canvas)
        self.assertAlmostEqual(canvas.pan_x, before[0], places=7)
        self.assertAlmostEqual(canvas.pan_y, before[1], places=7)
        self.assertAlmostEqual(canvas.zoom, before[2], places=7)
        self.assertAlmostEqual(canvas.rotation, before[3], places=7)

    def test_frame_to_collapsed_box_clamps_zoom(self):
        from scena import Box
        from scena.canvas import _MIN_ZOOM
        collapsed = Box(center=(200, 150), width=0, height=0)
        canvas.frame_to(collapsed, pad=0.1)
        self.assertAlmostEqual(canvas.pan_x, 200.0, places=5)
        self.assertAlmostEqual(canvas.pan_y, 150.0, places=5)
        # Zero-size target is clamped to _MIN_ZOOM before zoom = design / size.
        self.assertAlmostEqual(canvas.zoom, 800.0 / _MIN_ZOOM, places=1)
        self.assertAlmostEqual(canvas.rotation, 0.0, places=5)


class TestGameView(CanvasTestCase):
    def test_identity_bounds(self):
        from scena import Box
        b = canvas.game_view
        self.assertIsInstance(b, Box)
        self.assertAlmostEqual(b.left, 0.0, places=5)
        self.assertAlmostEqual(b.top, 800.0, places=5)  # y-up: visual top
        self.assertAlmostEqual(b.width, 1000.0, places=5)
        self.assertAlmostEqual(b.height, 800.0, places=5)
        self.assertAlmostEqual(b.right, 1000.0, places=5)
        self.assertAlmostEqual(b.bottom, 0.0, places=5)

    def test_zoomed_bounds_shrink(self):
        canvas.zoom_to(2.0)  # about center
        b = canvas.game_view
        self.assertAlmostEqual(b.width, 500.0, places=5)
        self.assertAlmostEqual(b.height, 400.0, places=5)
        self.assertAlmostEqual(float(b.center.x), 500.0, places=5)
        self.assertAlmostEqual(float(b.center.y), 400.0, places=5)

    def test_ui_view_ignores_camera(self):
        canvas.zoom_to(2.0).pan_to(300, 250)
        ui = canvas.ui_view
        self.assertAlmostEqual(ui.left, 0.0, places=5)
        self.assertAlmostEqual(ui.bottom, 0.0, places=5)
        self.assertAlmostEqual(ui.width, 1000.0, places=5)
        self.assertAlmostEqual(ui.height, 800.0, places=5)
        self.assertNotAlmostEqual(float(canvas.game_view.center.x), 500.0, places=2)


class TestScreenToWorld(CanvasTestCase):
    def test_roundtrip_with_camera(self):
        fw = ScenaFramework.get_instance()
        fw.view_scale = 0.5
        canvas.zoom_to(2.0).pan_to(300, 250).rotate_to(15)

        world = (320.0, 260.0)
        # screen = view_scale · flipY · camera · world
        m = skia_matrix_full(fw)
        screen = m.mapXY(*world)
        back = fw.screen_to_world_coords(screen.x(), screen.y())
        self.assertAlmostEqual(back[0], world[0], places=4)
        self.assertAlmostEqual(back[1], world[1], places=4)

    def test_identity_screen_to_world(self):
        fw = ScenaFramework.get_instance()
        fw.view_scale = 1.0
        canvas.reset_view()
        # Y-up: screen y-down → world y = H - screen_y
        wx, wy = fw.screen_to_world_coords(100, 200)
        self.assertAlmostEqual(wx, 100.0, places=5)
        self.assertAlmostEqual(wy, 600.0, places=5)  # 800 - 200

    def test_view_ignores_camera(self):
        """Widget / view coords stay design-window; world does not after pan/zoom."""
        fw = ScenaFramework.get_instance()
        fw.view_scale = 1.0
        canvas.reset_view()
        sx, sy = 100.0, 200.0
        view0 = fw.screen_to_view_coords(sx, sy)
        world0 = fw.screen_to_world_coords(sx, sy)
        self.assertAlmostEqual(view0[0], world0[0], places=5)
        self.assertAlmostEqual(view0[1], world0[1], places=5)

        canvas.zoom_to(2.0).pan_to(300, 250).rotate_to(30)
        view1 = fw.screen_to_view_coords(sx, sy)
        world1 = fw.screen_to_world_coords(sx, sy)
        self.assertAlmostEqual(view1[0], view0[0], places=5)
        self.assertAlmostEqual(view1[1], view0[1], places=5)
        self.assertNotAlmostEqual(world1[0], view1[0], places=2)
        self.assertNotAlmostEqual(world1[1], view1[1], places=2)


def _finite(lo, hi):
    return hst.floats(lo, hi, allow_nan=False, allow_infinity=False)


_camera = hst.fixed_dictionaries({
    "view_scale": _finite(0.25, 3.0),
    "pad": hst.tuples(_finite(0.0, 200.0), _finite(0.0, 200.0)),
    "zoom": _finite(0.1, 8.0),
    "pan": hst.tuples(_finite(-5000.0, 5000.0), _finite(-5000.0, 5000.0)),
    "rotation": _finite(-360.0, 360.0),
    "debug_zoom": hst.sampled_from([1.0, 0.5, 0.25]),
})


class TestScreenWorldRoundTripProperty(CanvasTestCase):
    """``world_to_view_coords`` applies camera + inspector by hand;
    ``screen_to_world_coords`` builds the Skia matrix and inverts it. Two
    spellings of one chain — they must stay inverse under any camera.

    Tolerance scales with the magnitudes: Skia matrices are float32, so a
    round trip at coordinates in the thousands drifts by ~1e-4 world units
    (Testing Design § Harness pitfalls). An order or sign slip is O(1) or more.
    """

    def _apply(self, cam):
        fw = ScenaFramework.get_instance()
        fw.view_scale = cam["view_scale"]
        fw._letterbox_pad_x, fw._letterbox_pad_y = cam["pad"]
        canvas.reset_view()
        canvas.zoom_to(cam["zoom"]).pan_to(*cam["pan"]).rotate_to(cam["rotation"])
        fw._set_debug_zoom(cam["debug_zoom"])
        return fw

    def _restore(self):
        fw = ScenaFramework.get_instance()
        fw._set_debug_zoom(1.0)
        fw.view_scale = 1.0
        fw._letterbox_pad_x = fw._letterbox_pad_y = 0.0
        canvas.reset_view()

    def _view_to_screen(self, fw, vx, vy):
        vs = fw.view_scale
        return (fw._letterbox_pad_x + vx * vs,
                fw._letterbox_pad_y + (fw.design_height - vy) * vs)

    def _tol(self, cam, screen, *world):
        """float32 slack: world magnitudes plus the screen point in world units."""
        k = cam["view_scale"] * cam["zoom"] * cam["debug_zoom"]
        scale = (1.0 + sum(abs(v) for v in world) + abs(cam["pan"][0]) + abs(cam["pan"][1])
                 + (abs(screen[0]) + abs(screen[1])) / k)
        return 1e-5 * scale

    @given(cam=_camera, world=hst.tuples(_finite(-5000.0, 5000.0), _finite(-5000.0, 5000.0)))
    def test_world_to_screen_to_world(self, cam, world):
        fw = self._apply(cam)
        try:
            vx, vy = fw.world_to_view_coords(*world)
            sx, sy = self._view_to_screen(fw, vx, vy)
            bx, by = fw.screen_to_world_coords(sx, sy)
            tol = self._tol(cam, (sx, sy), *world)
            self.assertLessEqual(math.hypot(bx - world[0], by - world[1]), tol,
                                 f"world {world} came back as {(bx, by)}")
        finally:
            self._restore()

    @given(cam=_camera)
    def test_view_center_is_the_pan_point(self, cam):
        """``canvas.pan_x/pan_y``: the world point under the canvas center,
        through letterbox, view scale, rotation and inspector zoom."""
        fw = self._apply(cam)
        try:
            sx, sy = self._view_to_screen(fw, fw.design_width / 2.0, fw.design_height / 2.0)
            wx, wy = fw.screen_to_world_coords(sx, sy)
            self.assertLessEqual(math.hypot(wx - canvas.pan_x, wy - canvas.pan_y),
                                 self._tol(cam, (sx, sy)), f"center maps to {(wx, wy)}")
        finally:
            self._restore()

    @given(cam=_camera.map(lambda c: {**c, "debug_zoom": 1.0}))
    def test_game_view_is_the_window_in_world(self, cam):
        """``canvas.game_view`` = world AABB of the four window corners (camera
        only; the inspector zoom shows more but does not move the frustum)."""
        fw = self._apply(cam)
        try:
            W, H = float(fw.design_width), float(fw.design_height)
            far = self._view_to_screen(fw, W, 0.0)
            pts = [fw.screen_to_world_coords(*self._view_to_screen(fw, x, y))
                   for x, y in ((0.0, 0.0), (W, 0.0), (W, H), (0.0, H))]
            gv = canvas.game_view
            tol = self._tol(cam, far)
            self.assertAlmostEqual(gv.left, min(p[0] for p in pts), delta=tol)
            self.assertAlmostEqual(gv.right, max(p[0] for p in pts), delta=tol)
            self.assertAlmostEqual(gv.bottom, min(p[1] for p in pts), delta=tol)
            self.assertAlmostEqual(gv.top, max(p[1] for p in pts), delta=tol)
        finally:
            self._restore()


class TestScreenWorldPropertyCanaries(CanvasTestCase):
    """The round trip catches a slip in either spelling (SCENA_CANARIES)."""

    def test_inspector_zoom_about_origin_is_caught(self):
        from diff_support import assert_catches
        original = ScenaFramework.world_to_view_coords

        def zoom_about_origin(self, x, y):
            if not self._debug_zoom_active:
                return original(self, x, y)
            self._debug_zoom_active = False
            try:
                vx, vy = original(self, x, y)
            finally:
                self._debug_zoom_active = True
            return vx * self._debug_zoom, vy * self._debug_zoom

        assert_catches(self, "test_canvas.TestScreenWorldRoundTripProperty.test_world_to_screen_to_world",
                       [(ScenaFramework, "world_to_view_coords", zoom_about_origin)],
                       "inspector zoom about the origin instead of the center")

    def test_letterbox_pad_dropped_is_caught(self):
        from diff_support import assert_catches
        original = ScenaFramework.screen_to_world_coords

        def no_pad(self, sx, sy):
            px, py = self._letterbox_pad_x, self._letterbox_pad_y
            self._letterbox_pad_x = self._letterbox_pad_y = 0.0
            try:
                return original(self, sx, sy)
            finally:
                self._letterbox_pad_x, self._letterbox_pad_y = px, py

        assert_catches(self, "test_canvas.TestScreenWorldRoundTripProperty.test_view_center_is_the_pan_point",
                       [(ScenaFramework, "screen_to_world_coords", no_pad)],
                       "screen_to_world ignoring the letterbox")


def skia_matrix_full(fw):
    import skia
    # screen = T(pad) · view_scale · flipY · camera · world
    H = fw.design_height
    matrix = skia.Matrix()
    matrix.setTranslate(
        float(getattr(fw, "_letterbox_pad_x", 0.0)),
        float(getattr(fw, "_letterbox_pad_y", 0.0)),
    )
    scale_m = skia.Matrix()
    scale_m.setScale(fw.view_scale, fw.view_scale)
    matrix.preConcat(scale_m)
    flip = skia.Matrix()
    flip.setTranslate(0, H)
    flip.preScale(1, -1)
    matrix.preConcat(flip)
    matrix.preConcat(fw._scena_draw.camera_matrix())
    return matrix


class TestFacadeHidesEngine(CanvasTestCase):
    def test_public_api_surface(self):
        public = {
            'width', 'height', 'aspect_ratio', 'background', 'set_fly',
            'zoom', 'pan_x', 'pan_y', 'rotation', 'game_view', 'ui_view',
            'cull_offscreen', 'playfield', 'bounds', 'display',
            'zoom_to', 'zoom_by', 'pan_to', 'pan_by', 'set_origin',
            'rotate_to', 'rotate_by',
            'frame_to', 'reset_view', 'layers',
        }
        # Methods/properties authors should see (ignore dunders and _engine).
        names = {n for n in dir(canvas) if not n.startswith('_')}
        self.assertTrue(public.issubset(names))
        # Engine internals should not be on the facade.
        for forbidden in ('scene', 'registry', 'layer_manager', 'draw', 'rebind', 'skia_canvas', 'camera_matrix'):
            self.assertNotIn(forbidden, names)


class TestTimedCamera(CanvasTestCase):
    def setUp(self):
        super().setUp()
        from scena.process import reset_process_scheduler, tick_processes
        from scena import clock
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        clock._frame = 0
        self._tick_processes = tick_processes
        self._clock = clock

    def tearDown(self):
        from scena.process import reset_process_scheduler
        reset_process_scheduler()
        canvas.reset_view()

    def _frame(self, real_dt=0.1):
        self._clock.advance(real_dt)
        self._tick_processes()

    def test_instant_returns_canvas(self):
        self.assertIs(canvas.pan_to(100, 200), canvas)
        self.assertIs(canvas.zoom_to(2), canvas)
        self.assertIs(canvas.rotate_to(15), canvas)
        self.assertIs(canvas.reset_view(), canvas)

    def test_time_returns_handle_and_lerps(self):
        from scena import Handle
        canvas.pan_to(0, 0)
        h = canvas.pan_to(100, 0, time=0.4, ease="linear")
        self.assertIsInstance(h, Handle)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_x, 50.0, places=4)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_x, 100.0, places=4)
        self.assertTrue(h.done)

    def test_ease_in_not_linear(self):
        canvas.pan_to(0, 0)
        canvas.pan_to(100, 0, time=1.0, ease="ease_in")
        self._frame(0.5)
        self.assertAlmostEqual(canvas.pan_x, 12.5, places=4)

    def test_then_on_done_require_time(self):
        with self.assertRaises(TypeError):
            canvas.pan_to(10, 10, on_done=lambda: None)
        with self.assertRaises(TypeError):
            canvas.zoom_to(2, then=lambda: None)

    def test_same_channel_cancels(self):
        canvas.pan_to(0, 0)
        h1 = canvas.pan_to(100, 0, time=1.0)
        h2 = canvas.pan_to(0, 100, time=1.0)
        self._frame(1.0)
        self.assertTrue(h1.cancelled)
        self.assertTrue(h2.done)
        self.assertAlmostEqual(canvas.pan_x, 0.0, places=4)
        self.assertAlmostEqual(canvas.pan_y, 100.0, places=4)

    def test_orthogonal_pan_and_zoom(self):
        canvas.reset_view()
        canvas.pan_to(0, 0)
        hp = canvas.pan_to(200, 0, time=0.4)
        hz = canvas.zoom_to(2.0, time=0.4)
        self._frame(0.4)
        self.assertTrue(hp.done)
        self.assertTrue(hz.done)
        self.assertAlmostEqual(canvas.pan_x, 200.0, places=4)
        self.assertAlmostEqual(canvas.zoom, 2.0, places=4)

    def test_about_zoom_claims_pan_channel(self):
        canvas.reset_view()
        about = (600, 400)
        m0 = canvas._engine.camera_matrix()
        sx0, sy0 = m0.mapXY(about[0], about[1]).x(), m0.mapXY(about[0], about[1]).y()
        h_zoom = canvas.zoom_to(2.0, about=about, time=1.0)
        h_pan = canvas.pan_to(0, 0, time=1.0)
        self.assertTrue(h_zoom.cancelled)
        self._frame(1.0)
        self.assertTrue(h_pan.done)
        self.assertAlmostEqual(canvas.pan_x, 0.0, places=4)
        self.assertAlmostEqual(canvas.pan_y, 0.0, places=4)
        # Zoom was cancelled — should still be near identity zoom.
        self.assertAlmostEqual(canvas.zoom, 1.0, places=4)

    def test_about_keeps_point_fixed_on_screen(self):
        canvas.reset_view()
        about = (700, 500)
        m0 = canvas._engine.camera_matrix()
        p0 = m0.mapXY(about[0], about[1])
        sx0, sy0 = p0.x(), p0.y()
        canvas.zoom_to(2.5, about=about, time=0.4)
        self._frame(0.2)
        mid = canvas._engine.camera_matrix().mapXY(about[0], about[1])
        self.assertAlmostEqual(mid.x(), sx0, places=3)
        self.assertAlmostEqual(mid.y(), sy0, places=3)
        self._frame(0.2)
        end = canvas._engine.camera_matrix().mapXY(about[0], about[1])
        self.assertAlmostEqual(end.x(), sx0, places=3)
        self.assertAlmostEqual(end.y(), sy0, places=3)
        self.assertAlmostEqual(canvas.zoom, 2.5, places=4)

    def test_rotate_to_shortest_arc(self):
        canvas.reset_view()
        canvas.rotate_to(350)
        canvas.rotate_to(10, time=0.2)
        self._frame(0.1)
        self.assertAlmostEqual(canvas.rotation % 360.0, 0.0, places=4)    # the short way
        self._frame(0.1)
        # Q2: it ends exactly on the target, as the instant form does (it read 370).
        self.assertEqual(canvas.rotation, 10.0)
        canvas.rotate_to(400)
        canvas.rotate_to(30, time=0.2)
        self._frame(0.2)
        self.assertEqual(canvas.rotation, 30.0)
        canvas.reset_view()

    def test_rotate_by_signed(self):
        canvas.reset_view()
        canvas.rotate_by(270, time=0.1)
        self._frame(0.1)
        self.assertAlmostEqual(canvas.rotation, 270.0, places=4)

    def test_set_origin_rest_tracks_look(self):
        canvas.reset_view()
        canvas.pan_to(100, 50)
        # Rest still at identity center until set_origin.
        self.assertAlmostEqual(canvas.pan_rest_x, 500.0, places=4)
        z0, r0 = canvas.zoom, canvas.rotation
        canvas.set_origin("center", time=0.4)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_rest_x, canvas.pan_x, places=4)
        self.assertAlmostEqual(canvas.pan_rest_y, canvas.pan_y, places=4)
        self.assertAlmostEqual(canvas.zoom, z0, places=5)
        self.assertAlmostEqual(canvas.rotation, r0, places=5)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_x, 0.0, places=4)
        self.assertAlmostEqual(canvas.pan_y, 0.0, places=4)
        self.assertAlmostEqual(canvas.pan_rest_x, 0.0, places=4)
        self.assertAlmostEqual(canvas.pan_rest_y, 0.0, places=4)

    def test_timed_frame_to_uses_shortest_rotation(self):
        focus = Rect(center=(500, 400), width=100, height=50, angle=-190)
        canvas.rotate_to(0)
        h = canvas.frame_to(focus, time=1.0, rotate=True)
        self._frame(0.5)
        # Linear 0 → 190 would sit near +95. Shortest arc is −170.
        self.assertLess(canvas.rotation, 0.0)
        self.assertAlmostEqual(canvas.rotation, -85.0, places=3)
        self._frame(0.5)
        self.assertTrue(h.done)
        self.assertAlmostEqual(canvas.rotation, -170.0, places=3)

    def test_frame_to_cancels_pan(self):
        canvas.reset_view()
        h_pan = canvas.pan_to(200, 100, time=1.0)
        focus = Rect(center=(100, 100), width=200, height=160)
        h_frame = canvas.frame_to(focus, pad=0.0, time=0.4)
        self.assertTrue(h_pan.cancelled)
        self._frame(0.4)
        self.assertTrue(h_frame.done)
        self.assertAlmostEqual(canvas.pan_x, 100.0, places=3)
        self.assertAlmostEqual(canvas.pan_y, 100.0, places=3)

    def test_frame_to_none_timed_identity_handle(self):
        from scena import Handle
        canvas.zoom_to(2.0).pan_to(100, 80).rotate_to(15)
        before = (canvas.pan_x, canvas.pan_y, canvas.zoom, canvas.rotation)
        seen = []
        h = canvas.frame_to(None, time=0.4, on_done=lambda: seen.append("done"))
        self.assertIsInstance(h, Handle)
        self.assertTrue(hasattr(h, "__await__"))
        self._frame(0.2)
        self.assertEqual(seen, [])
        self.assertAlmostEqual(canvas.pan_x, before[0], places=7)
        self.assertAlmostEqual(canvas.pan_y, before[1], places=7)
        self.assertAlmostEqual(canvas.zoom, before[2], places=7)
        self.assertAlmostEqual(canvas.rotation, before[3], places=7)
        self._frame(0.2)
        self.assertTrue(h.done)
        self.assertEqual(seen, ["done"])
        self.assertAlmostEqual(canvas.pan_x, before[0], places=7)
        self.assertAlmostEqual(canvas.pan_y, before[1], places=7)
        self.assertAlmostEqual(canvas.zoom, before[2], places=7)
        self.assertAlmostEqual(canvas.rotation, before[3], places=7)

    def test_frame_to_none_cancels_in_flight_pan(self):
        canvas.reset_view()
        canvas.pan_to(0, 0)
        h_pan = canvas.pan_to(200, 100, time=1.0)
        before = (canvas.pan_x, canvas.pan_y, canvas.zoom, canvas.rotation)
        h_frame = canvas.frame_to(None, time=0.4)
        self.assertTrue(h_pan.cancelled)
        self._frame(0.4)
        self.assertTrue(h_frame.done)
        self.assertAlmostEqual(canvas.pan_x, before[0], places=7)
        self.assertAlmostEqual(canvas.pan_y, before[1], places=7)
        self.assertAlmostEqual(canvas.zoom, before[2], places=7)
        self.assertAlmostEqual(canvas.rotation, before[3], places=7)

    def test_frame_to_none_then_from_mode(self):
        seen = []
        actor = Circle(center=(0, 0), radius=8)

        def holding(e):
            seen.append("holding")

        def enter(e):
            canvas.frame_to(None, time=0.4, then=holding)

        canvas.zoom_to(2.0).pan_to(100, 80)
        before = (canvas.pan_x, canvas.pan_y, canvas.zoom, canvas.rotation)
        actor.mode = enter
        self._frame(0.4)
        self.assertEqual(seen, ["holding"])
        self.assertEqual(actor.mode, holding)
        self.assertAlmostEqual(canvas.pan_x, before[0], places=7)
        self.assertAlmostEqual(canvas.pan_y, before[1], places=7)
        self.assertAlmostEqual(canvas.zoom, before[2], places=7)
        self.assertAlmostEqual(canvas.rotation, before[3], places=7)
        actor.destroy()

    def test_reset_view_timed(self):
        canvas.zoom_to(2.5).pan_to(100, 80).rotate_to(30)
        canvas.reset_view(time=0.4)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_rest_x, canvas.pan_x, places=4)
        self.assertAlmostEqual(canvas.pan_rest_y, canvas.pan_y, places=4)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.zoom, 1.0, places=4)
        self.assertAlmostEqual(canvas.pan_x, 500.0, places=4)
        self.assertAlmostEqual(canvas.pan_y, 400.0, places=4)
        self.assertAlmostEqual(canvas.rotation, 0.0, places=4)
        self.assertAlmostEqual(canvas.pan_rest_x, 500.0, places=4)
        self.assertAlmostEqual(canvas.pan_rest_y, 400.0, places=4)

    def test_frame_to_overshoot_ease_stays_positive_zoom(self):
        # Regression: timed_camera_frame_to used to write
        # `e._zoom = za + (zb - za) * u` directly. An overshooting ease
        # (u < 0 or u > 1 mid-tween) drove the zoom negative even though
        # both endpoints were positive, because linear interpolation in
        # zoom-space is not overshoot-safe. Geometric interpolation
        # (za * (zb/za)**u) is positive for any real u.
        def overshoot(t):
            return 3.0 * t  # u reaches 1.5 well before t=1

        canvas.reset_view()
        focus = Rect(center=(0, 0), width=4000, height=2400)
        canvas.frame_to(focus, time=1.0, ease=overshoot)
        for _ in range(12):
            self._frame(0.1)
            self.assertGreater(canvas.zoom, 0.0)

    def test_reset_view_overshoot_ease_stays_positive_zoom(self):
        def overshoot(t):
            return 3.0 * t

        canvas.zoom_to(0.02)
        canvas.reset_view(time=1.0, ease=overshoot)
        for _ in range(12):
            self._frame(0.1)
            self.assertGreater(canvas.zoom, 0.0)

    def test_elastic_zoom_to_never_reaches_zero(self):
        # Regression: an elastic zoom_to used to strobe to exactly 0.0
        # mid-tween (clamp_magnitude turned the overshoot's negative value
        # into a bare 0, and zoom_to used to store that 0 verbatim).
        from scena.canvas import _MIN_ZOOM
        canvas.reset_view()
        canvas.zoom_to(0.5, time=1.0, ease="elastic")
        for _ in range(30):
            self._frame(0.05)
            self.assertGreaterEqual(canvas.zoom, _MIN_ZOOM)

    def test_pan_by_timed(self):
        canvas.reset_view()
        canvas.pan_by(40, -20, time=0.2)
        self._frame(0.2)
        # Content moves +40,-20 → look moves opposite.
        self.assertAlmostEqual(canvas.pan_x, 500.0 - 40.0, places=4)
        self.assertAlmostEqual(canvas.pan_y, 400.0 + 20.0, places=4)

    def test_pan_to_graphic_time_freezes_center(self):
        hero = Circle(center=(100, 200), radius=10)
        canvas.pan_to(hero, time=0.2)
        hero.move_to(400, 500)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_x, 100.0, places=4)
        self.assertAlmostEqual(canvas.pan_y, 200.0, places=4)

    def test_pan_by_vec2_timed(self):
        canvas.reset_view()
        canvas.pan_by(Vec2(40, -20), time=0.2)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_x, 500.0 - 40.0, places=4)
        self.assertAlmostEqual(canvas.pan_y, 400.0 + 20.0, places=4)

    def test_pan_to_yoyo_forever(self):
        canvas.reset_view()
        h = canvas.pan_to(600, 400, time=0.2, loops="forever", yoyo=True)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_x, 600.0, places=3)
        self.assertEqual(h._lap, 1)
        self._frame(0.2)
        self.assertAlmostEqual(canvas.pan_x, 500.0, places=3)
        self.assertEqual(h._lap, 2)
        self.assertFalse(h.done)
        h.cancel()

    def test_zoom_to_yoyo(self):
        canvas.reset_view()
        h = canvas.zoom_to(2.0, time=0.1, loops=2, yoyo=True)
        self._frame(0.1)
        self.assertAlmostEqual(canvas.zoom, 2.0, places=3)
        self._frame(0.1)
        self.assertTrue(h.done)
        self.assertAlmostEqual(canvas.zoom, 1.0, places=3)

    def test_reset_view_yoyo(self):
        canvas.zoom_to(2.0).pan_to(100, 80)
        h = canvas.reset_view(time=0.1, loops=2, yoyo=True)
        self._frame(0.1)
        self.assertAlmostEqual(canvas.zoom, 1.0, places=3)
        self.assertAlmostEqual(canvas.pan_x, 500.0, places=2)
        self._frame(0.1)
        self.assertTrue(h.done)
        self.assertAlmostEqual(canvas.zoom, 2.0, places=3)

    def test_camera_yoyo_requires_loops_gt_one(self):
        with self.assertRaises(ValueError):
            canvas.pan_to(600, 400, time=0.2, yoyo=True)
        with self.assertRaises(TypeError):
            canvas.zoom_to(2, loops=2)


class TestFilteredPaintCache(CanvasTestCase):
    def test_material_paint_is_quiet_after_warmup_and_fade_restores_filter(self):
        import skia
        from scena.filters import Blur, GlowFilter
        from scena import transients as tx

        c = Circle(center=(40, 40), radius=16).set_color("cyan")
        blur = Blur(4)
        c.fill_filter = blur
        surf = skia.Surface(120, 120)
        canvas_sk = surf.getCanvas()
        c._geometry_draw(canvas_sk)
        saved = c._fill_filter
        c._fill_filter = None
        c._geometry_draw(canvas_sk)
        c._fill_filter = saved
        calls = []
        orig = c._material_paint

        def counted(material, **fields):
            calls.append(material)
            return orig(material, **fields)

        c._material_paint = counted
        try:
            for _ in range(3):
                c._geometry_draw(canvas_sk)
                c._fill_filter = None
                c._geometry_draw(canvas_sk)
                c._fill_filter = saved
        finally:
            del c._material_paint
        self.assertEqual(calls, [])

        glow = GlowFilter()
        c.fill_filter = glow
        c._to_skia_fill_paint()
        c.fade_out(0.4)
        c.draw(canvas_sk)
        restored = c._to_skia_fill_paint()
        self.assertIsNotNone(restored)
        self.assertIsNotNone(restored.getImageFilter())



class TestCanvasIsAFormulaSource(CanvasTestCase):
    """RX1 (Testing Design, interaction campaign class 8): ``canvas`` is a
    formula source like ``mouse`` / ``clock``. A formula that reads the
    camera, ``game_view`` or a layer's ``view`` follows every camera move and
    every scroll; a measured Box met in the chain is a value, not the source
    (``state._is_durable_source``), so nothing throwaway joins the graph."""

    def setUp(self):
        super().setUp()
        self._owned = []

    def tearDown(self):
        for o in self._owned:
            try:
                o.destroy()
            except Exception:
                pass
        canvas.reset_view()
        if "rx_bg" in canvas.layers:
            canvas.layers["rx_bg"].delete(destroy_shapes=True)
        super().tearDown()

    def track(self, o):
        self._owned.append(o)
        return o

    def _view_center(self):
        vb = canvas._engine.visible_bounds
        return ((vb.left + vb.right) / 2.0, (vb.bottom + vb.top) / 2.0)

    def test_game_view_center_follows_every_camera_move(self):
        c = self.track(Circle(center=(0, 0), radius=5))
        c["center"] @= (lambda: canvas.game_view.center)
        for name, move in (("zoom", lambda: canvas.zoom_to(2.0)),
                           ("pan", lambda: canvas.pan_by(70.0, -30.0)),
                           ("rotate", lambda: canvas.rotate_to(25.0)),
                           ("origin", lambda: canvas.set_origin("center")),
                           ("reset", lambda: canvas.reset_view())):
            with self.subTest(move=name):
                move()
                want = self._view_center()
                self.assertAlmostPoint((float(c.center.x), float(c.center.y)), *want, places=4)

    def test_camera_scalars_follow(self):
        r = self.track(Rect(center=(0, 0), width=10, height=10))
        r["width"] @= (lambda: canvas.game_view.width * 0.5)
        r["angle"] @= (lambda: canvas.rotation + 1.0)
        canvas.zoom_to(2.0)
        vb = canvas._engine.visible_bounds
        self.assertAlmostEqual(float(r.width), (vb.right - vb.left) * 0.5, places=4)
        canvas.rotate_to(30.0)
        self.assertAlmostEqual(float(r.angle), 31.0, places=6)

    def test_layer_view_follows_scroll_and_camera(self):
        canvas.layers.create("rx_bg", pan_response=0.4, scroll=(-40.0, 0.0), below="default")
        p = self.track(Point(0, 0))
        p["x"] @= (lambda: canvas.layers["rx_bg"].view.left)
        canvas._engine.advance_layer_scroll(0.0)       # the scroll's time origin
        before = float(p.x)
        canvas._engine.advance_layer_scroll(0.5)
        after_scroll = float(p.x)
        self.assertNotAlmostEqual(before, after_scroll, places=3)
        self.assertAlmostEqual(after_scroll, float(canvas.layers["rx_bg"].view.left), places=4)
        canvas.pan_by(100.0, 0.0)
        self.assertAlmostEqual(float(p.x), float(canvas.layers["rx_bg"].view.left), places=4)

    def test_ui_view_formula_is_accepted_and_camera_immune(self):
        p = self.track(Point(0, 0))
        p["x"] @= (lambda: canvas.ui_view.right)
        canvas.zoom_to(3.0)
        canvas.pan_by(200.0, 0.0)
        self.assertAlmostEqual(float(p.x), float(canvas.width), places=6)

    def test_a_graphic_box_formula_follows_the_graphic(self):
        r = self.track(Rect(center=(0, 0), width=10, height=10))
        p = self.track(Point(0, 0))
        p["x"] @= (lambda: r.box.right)
        r.move_by(25.0, 0.0)
        self.assertAlmostEqual(float(p.x), 30.0, places=6)

    def test_nothing_throwaway_joins_the_graph(self):
        import gc
        from scena.state import get_scena_system
        c = self.track(Circle(center=(0, 0), radius=5))
        c["center"] @= (lambda: canvas.game_view.center)
        canvas.zoom_to(1.5)
        float(c.center.x)
        gc.disable()
        try:
            nodes = get_scena_system().dependency_graph.nodes
            n0 = len(nodes)
            for _ in range(30):
                canvas.pan_by(1.0, 0.0)
                float(c.center.x)
            self.assertEqual(len(nodes), n0, "camera pulls joined throwaway Boxes into the graph")
        finally:
            gc.enable()


if __name__ == '__main__':
    unittest.main()