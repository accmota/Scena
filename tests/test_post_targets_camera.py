"""
A post effect's ``target=`` / ``center=`` / ``origin=`` lands on the object
where the picture shows it, whatever the camera does.

Posts work on the finished picture; their points are world points (a
position, an object, the mouse). They were read as design coords, so
``canvas.set_origin("center"); GodRays(target=(0, 0))`` put the rays at the
bottom-left corner, and a pan, zoom or turn moved them off their object
(showcase A2, 2026-10-23).

Bug class guarded: a world point used on the picture without the camera's
map (``_sksl_effects._world_to_view``).

Run:

    python tests/run_tiers.py focused test_post_targets_camera
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from program_support import FRAME  # noqa: E402
from system_support import boot, system_world  # noqa: E402

from scena import Circle, canvas  # noqa: E402
from scena import _sksl_effects as sk  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

boot()
setUpModule, tearDownModule = module_sweep()

CAMERAS = {
    "identity": lambda: None,
    "origin center": lambda: canvas.set_origin("center"),
    "pan": lambda: canvas.pan_to(70, -30),
    "zoom": lambda: canvas.zoom_to(2.0),
    "turn": lambda: canvas.rotate_to(30),
}


def frame(w):
    w.step(1, dt=FRAME)
    img = w.surface.makeImageSnapshot()
    info = skia.ImageInfo.Make(img.width(), img.height(),
                               skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = bytearray(img.width() * img.height() * 4)
    assert img.readPixels(info, buf, img.width() * 4, 0, 0)
    return np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)[:, :, :3]


class TestPostPointsFollowTheCamera(unittest.TestCase):
    def test_target_lands_on_the_object(self):
        for name, set_camera in CAMERAS.items():
            with self.subTest(camera=name), system_world(draw=True) as w:
                try:
                    set_camera()
                    world = (20.0, 15.0) if name == "origin center" else (150.0, 110.0)
                    dot = Circle(center=world, radius=7, color="white")
                    a = frame(w)
                    h, wd = a.shape[:2]
                    for target in (world, dot):
                        fx, fy = sk._resolve_target_fb(target, wd, h)
                        px = a[int(round(fy)), int(round(fx))]
                        self.assertGreater(int(px.sum()), 600, f"{name}: {target!r} → ({fx:.0f}, {fy:.0f}) is {px}")
                    dot.destroy()
                finally:
                    canvas.reset_view()

    def test_origin_center_puts_world_zero_where_the_view_middle_is(self):
        with system_world(draw=True) as w:
            try:
                canvas.set_origin("center")
                frame(w)
                fw, fh = w.surface.width(), w.surface.height()
                W, H = sk._design_size()
                self.assertEqual(sk._resolve_target_fb((0, 0), fw, fh),
                                 sk._view_to_fb(W / 2, H / 2, fw, fh))
            finally:
                canvas.reset_view()

    def test_a_length_matches_two_mapped_points(self):
        # Lamp radius / range and Spotlight range are design units (they
        # were pixels of the post image, which shrinks with post_fx_scale).
        # A length maps as the distance between two mapped points does,
        # under any camera and at any post image size.
        import math
        for name, set_camera in CAMERAS.items():
            with self.subTest(camera=name), system_world(draw=True) as w:
                try:
                    set_camera()
                    frame(w)
                    fw, fh = w.surface.width(), w.surface.height()
                    for scale in (1.0, 0.5):
                        pw, ph = fw * scale, fh * scale
                        a = sk._resolve_target_fb((100.0, 100.0), pw, ph)
                        b = sk._resolve_target_fb((160.0, 100.0), pw, ph)
                        self.assertAlmostEqual(math.hypot(b[0] - a[0], b[1] - a[1]),
                                               sk._length_to_fb(60.0, pw, ph), places=4)
                finally:
                    canvas.reset_view()

    def test_lamp_and_spotlight_feed_their_lengths_through_the_mapping(self):
        # The 0.10.0 release audit: only ``_length_to_fb`` was tested, so a
        # lamp back on raw post-image pixels passed. The uniforms a draw sets
        # are the mapped lengths, under zoom and at a smaller post image.
        from scena import Lamp, Spotlight
        caught = {}

        class Spy:
            def __init__(self, real):
                self.real = real

            def setUniform(self, k, v):
                caught[k] = v
                return self.real.setUniform(k, v)

            def __getattr__(self, k):
                return getattr(self.real, k)

        saved = sk._lamp_builder, sk._spotlight_builder
        sk._lamp_builder, sk._spotlight_builder = Spy(saved[0]), Spy(saved[1])
        try:
            with system_world(draw=True) as w:
                try:
                    canvas.zoom_to(2.0)
                    frame(w)
                    fw, fh = w.surface.width(), w.surface.height()
                    lamp = Lamp(radius=50, range=100, target=(150.0, 110.0))
                    spot = Spotlight(range=80, target=(150.0, 110.0))
                    for scale in (1.0, 0.5):
                        pw, ph = int(fw * scale), int(fh * scale)
                        surf = skia.Surface(pw, ph)
                        for effect, uniforms in ((lamp, {"u_radius": 50, "u_range": 100}),
                                                 (spot, {"u_range": 80})):
                            caught.clear()
                            effect._draw_shader(surf.getCanvas(), surf.makeImageSnapshot(), pw, ph, 0.0, None)
                            for name, design in uniforms.items():
                                with self.subTest(effect=type(effect).__name__, uniform=name, scale=scale):
                                    self.assertAlmostEqual(float(caught[name]),
                                                           sk._length_to_fb(design, pw, ph), places=3)
                finally:
                    canvas.reset_view()
        finally:
            sk._lamp_builder, sk._spotlight_builder = saved

    def test_the_mouse_default_maps_like_a_target(self):
        # ``target=None`` aims at the mouse: the same mapping as a point there
        # (it ignored the zoom before 0.10.0; the release audit found no test).
        import builtins
        import types
        for name, set_camera in CAMERAS.items():
            with self.subTest(camera=name), system_world(draw=True) as w:
                try:
                    set_camera()
                    frame(w)
                    fw, fh = w.surface.width(), w.surface.height()
                    # ``mouse.x`` is read-only: a stand-in where the effect reads it.
                    saved = builtins.mouse
                    builtins.mouse = types.SimpleNamespace(x=150.0, y=110.0)
                    try:
                        self.assertEqual(sk._mouse_fb_xy(fw, fh),
                                         sk._resolve_target_fb((150.0, 110.0), fw, fh))
                    finally:
                        builtins.mouse = saved
                finally:
                    canvas.reset_view()

    def test_view_to_fb_counts_the_letterbox(self):
        # A 400×300 design in a 2000×1200 framebuffer (maximized, Retina 2×:
        # a 1000×600 window): view_scale 2, pillars of 100 window px. The
        # post image may be smaller (post_fx_scale): the same place, scaled.
        from scena.orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        # the design size too: a module before this one may have init'd its own (WP41)
        metrics = dict(design_width=400.0, design_height=300.0,
                       fb_width=2000, fb_height=1200, view_scale=2.0, pixel_ratio=2.0,
                       _letterbox_pad_x=100.0, _letterbox_pad_y=0.0)
        saved = {k: getattr(fw, k) for k in metrics}
        try:
            for k, v in metrics.items():
                setattr(fw, k, v)
            W, H = sk._design_size()
            self.assertEqual(sk._view_to_fb(W / 2, H / 2, 2000, 1200), (1000.0, 600.0))
            self.assertEqual(sk._view_to_fb(0, H, 2000, 1200), (200.0, 0.0))
            self.assertEqual(sk._view_to_fb(W, 0, 1000, 600), (900.0, 600.0))
        finally:
            for k, v in saved.items():
                setattr(fw, k, v)


if __name__ == "__main__":
    unittest.main()
