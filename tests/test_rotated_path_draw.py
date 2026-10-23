"""
A path drawn under a turned pose or camera looks the same through the fast
route (``entity._draw_path``) as through a plain ``drawPath``.

Skia draws a concave or thickly stroked path under a matrix that does not
keep axes aligned on a slow route every frame (showcase D1 / D2,
2026-10-23: a rotating ``Track.star`` ~4×, a rotating 12-point ``Polygon``
~10× a ``RegularPolygon``, every track slow while the camera is turned).
``_draw_path`` applies the matrix's linear part to a cached copy of the path
and draws it under the translation alone. This module holds the look to the
plain draw (pixels), the cache to its key (a still shape bakes once), and the
paints the route must leave alone (dashes, shaders) to the plain draw.

Bug class guarded: a draw fast path that changes the picture (stroke width,
winding, a CTM-reading paint) or rebakes every frame.

Run:

    python tests/run_tiers.py focused test_rotated_path_draw
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from program_support import FRAME  # noqa: E402
from system_support import boot, system_world  # noqa: E402

import scena.entity as entity_mod  # noqa: E402
import scena.shapes as shapes_mod  # noqa: E402
import scena.track as track_mod  # noqa: E402
from scena import (  # noqa: E402
    Concave, Gradient, Polygon, RegularPolygon, Track, canvas,
)

from tests.leftovers import module_sweep  # noqa: E402

boot()
setUpModule, tearDownModule = module_sweep()

STAR = [(0, -60), (14, -18), (58, -18), (22, 8), (36, 50), (0, 24),
        (-36, 50), (-22, 8), (-58, -18), (-14, -18), (-6, -40), (6, -40)]


def plain(skia_canvas, path, paint, owner):
    skia_canvas.drawPath(path, paint)


def pixels(w):
    w.step(1, dt=FRAME)
    img = w.surface.makeImageSnapshot()
    info = skia.ImageInfo.Make(img.width(), img.height(),
                               skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = bytearray(img.width() * img.height() * 4)
    assert img.readPixels(info, buf, img.width() * 4, 0, 0)
    return np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)[:, :, :3].astype(int)


def scenes():
    def star_track():
        return [Track.star(center=(200, 150), radius=80, line_width=3, color="white", angle=30)]

    def wave_track():
        return [Track.wave(length=260, amplitude=30, waves=3, start=(70, 150),
                           line_width=5, color="cyan", angle=17)]

    def concave_polygon():
        p = Polygon(points=[(200 + x, 150 + y) for x, y in STAR], color="orange", line_width=4)
        p.angle = 33
        return [p]

    def thick_hexagon():
        return [RegularPolygon(n=6, center=(200, 150), radius=70, color="lime",
                               line_width=12, angle=20)]

    def concave_box():
        return [Concave(center=(200, 150), width=160, height=100, color="violet",
                        line_width=3, angle=25)]

    def turned_camera():
        canvas.rotate_to(23)
        return [Track.star(center=(200, 150), radius=80, line_width=2, color="white"),
                Polygon(points=[(200 + x, 150 + y) for x, y in STAR], color="gold")]

    def gradient_polygon():
        p = Polygon(points=[(200 + x, 150 + y) for x, y in STAR], line_width=3,
                    visual=Gradient("red", "blue"))
        p.angle = 30
        return [p]

    return {"gradient polygon": gradient_polygon, "star track": star_track, "wave track": wave_track,
            "concave polygon": concave_polygon, "thick hexagon": thick_hexagon,
            "concave box": concave_box, "turned camera": turned_camera}


def render(make, fast: bool):
    with system_world(draw=True) as w:
        try:
            if fast:
                shapes = make()
                return pixels(w), shapes
            with mock.patch.object(shapes_mod, "_draw_path", plain), \
                    mock.patch.object(track_mod, "_draw_path", plain):
                shapes = make()
                return pixels(w), shapes
        finally:
            canvas.reset_view()


class _AnySize(unittest.TestCase):
    """The route runs only past ``_BAKE_MIN_DEVICE_PX``; the raster world here
    is 1×, so these tests take it at any size."""

    def setUp(self):
        self.enterContext(mock.patch.object(entity_mod, "_BAKE_MIN_DEVICE_PX", 0.0))


class TestSameLook(_AnySize):
    def test_fast_route_draws_what_drawpath_draws(self):
        for name, make in scenes().items():
            with self.subTest(scene=name):
                a, _ = render(make, fast=True)
                b, _ = render(make, fast=False)
                lit = (b.sum(axis=2) > 60).sum()
                self.assertGreater(lit, 200, f"{name}: nothing drawn")
                off = (np.abs(a - b).max(axis=2) > 48).sum()
                # Antialiasing may move an edge pixel: a handful, never a
                # stroke width or a fill (hundreds).
                self.assertLess(off, max(12, lit // 100), f"{name}: {off} pixels differ of {lit}")


class TestCacheAndExclusions(_AnySize):
    def test_a_still_turned_shape_bakes_once(self):
        calls = []
        real = skia.Path.transform

        def counting(path, *a, **k):
            calls.append(1)
            return real(path, *a, **k)

        with system_world(draw=True) as w:
            Track.star(center=(200, 150), radius=80, line_width=3, color="white", angle=30)
            w.step(1, dt=FRAME)
            with mock.patch.object(skia.Path, "transform", counting):
                w.step(10, dt=FRAME)
            self.assertEqual(calls, [], "the still star rebaked its path")

    def test_paints_that_read_the_matrix_draw_plain(self):
        # A shader, a dash, a mask or an image filter reads the CTM: the
        # route leaves them to drawPath (no baked copy is made), and a stroke
        # under a non-uniform scale is not baked either.
        class Owner:
            pass

        surface = skia.Surface(64, 64)
        cv = surface.getCanvas()
        path = skia.Path()
        path.addPoly([(0, 0), (20, 4), (8, 8), (4, 20)], True)
        shader = skia.GradientShader.MakeLinear([(0, 0), (20, 0)], [0xFFFF0000, 0xFF0000FF])
        dashed = skia.Paint(PathEffect=skia.DashPathEffect.Make([4, 2], 0), Style=skia.Paint.kStroke_Style)
        cases = {
            "shader": skia.Paint(Shader=shader),
            "dash": dashed,
            "mask": skia.Paint(MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 2)),
            "image filter": skia.Paint(ImageFilter=skia.ImageFilters.Blur(2, 2)),
        }
        cv.translate(30, 30)
        cv.rotate(30)
        for name, paint in cases.items():
            with self.subTest(paint=name):
                owner = Owner()
                entity_mod._draw_path(cv, path, paint, owner)
                self.assertIsNone(getattr(owner, "_geom_baked", None))
        cv.scale(2, 1)
        owner = Owner()
        entity_mod._draw_path(cv, path, skia.Paint(Style=skia.Paint.kStroke_Style, StrokeWidth=3), owner)
        self.assertIsNone(getattr(owner, "_geom_baked", None), "stroke under a non-uniform scale")
        entity_mod._draw_path(cv, path, skia.Paint(), owner)
        self.assertIsNotNone(getattr(owner, "_geom_baked", None), "a fill bakes under any linear map")

    def test_small_turned_paths_skip_the_route(self):
        # Below the size Skia's own route stays fast at any angle, the bake
        # would only add its cost.
        class Owner:
            pass

        surface = skia.Surface(64, 64)
        cv = surface.getCanvas()
        cv.rotate(30)
        path = skia.Path()
        path.addPoly([(0, 0), (20, 4), (8, 8), (4, 20)], True)
        owner = Owner()
        with mock.patch.object(entity_mod, "_BAKE_MIN_DEVICE_PX", 256.0):
            entity_mod._draw_path(cv, path, skia.Paint(), owner)
        self.assertIsNone(getattr(owner, "_geom_baked", None))

    def test_unturned_shapes_skip_the_route(self):
        with system_world(draw=True) as w:
            t = Track.star(center=(200, 150), radius=80, line_width=3, color="white")
            w.step(1, dt=FRAME)
            self.assertIsNone(getattr(t, "_geom_baked", None))


if __name__ == "__main__":
    unittest.main()
