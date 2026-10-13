"""Rendering composition pixel oracle: a bright actor lands on the screen
pixel the transform chain predicts, across camera × layer response × post
FX × window scale × letterbox, and the ``ui`` layer at its design pixel.

Interaction campaign, class 6 (design/Testing Design.md, "Interaction
campaign"). ``test_diff_draw`` compares draw doors with each other and
``test_parallax_layers`` checks the matrix the draw path uses; here the
frame is rastered and the brightest pixel is compared with the pixel the
engine's own maps give (``world_to_view_coords`` for a world layer,
``_layer_partial_matrix`` for a parallax layer, the design point for ``ui``,
then ``screen = pad + view_scale · flipY(view)``). One white square on black,
one target per cell.

    python -m unittest tests.test_diff_pipeline -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from typing import Callable, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from diff_support import assert_catches  # noqa: E402
from hypothesis_support import registry  # noqa: E402
from system_support import SystemTestCase, quiet  # noqa: E402

from scena import Grain, Rect, Vignette, canvas  # noqa: E402

DISPLAYS: Dict[str, Tuple[float, Tuple[float, float]]] = {
    "1:1": (1.0, (0.0, 0.0)),
    "half, pad x": (0.5, (37.0, 0.0)),
    "0.8, pad y": (0.8, (0.0, 21.0)),
}
CAMERAS: Dict[str, Callable[[], None]] = {
    "identity": lambda: None,
    "zoom 1.5": lambda: canvas.zoom_to(1.5),
    "pan": lambda: canvas.pan_by(40.0, -25.0),
    "rotate 30": lambda: canvas.rotate_to(30.0),
    "origin center, zoom .8": lambda: (canvas.set_origin("center"), canvas.zoom_to(0.8)),
    "zoom .7, pan, rotate": lambda: (canvas.zoom_to(0.7), canvas.pan_by(-30.0, 20.0),
                                     canvas.rotate_to(-20.0)),
}
LAYERS = ("world", "parallax", "ui")
POST = ("post off", "post on")
SIZE = 7.0
AT = {"world": (170.0, 140.0), "parallax": (210.0, 160.0), "ui": (300.0, 60.0)}
TOL = 3.0            # pixels: antialiasing and a half-pixel centre

# Shrink-only: "display | camera | layer | post" -> reason.
KNOWN: Dict[str, str] = {
}


def _screen(surface) -> np.ndarray:
    return np.asarray(surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))


def brightest(img: np.ndarray) -> Tuple[float, float]:
    lum = img[..., :3].astype(np.int32).sum(axis=-1)
    top = lum.max()
    ys, xs = np.nonzero(lum >= top - 30)
    return float(xs.mean()) + 0.5, float(ys.mean()) + 0.5


class TestPixelOracle(SystemTestCase, unittest.TestCase):
    world_draw = True
    maxDiff = None

    def setUp(self):
        super().setUp()
        fw = self.w.fw
        self._saved = (fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y)
        canvas.layers.create("px_bg", pan_response=0.4, below="default")
        self._fx = None

    def tearDown(self):
        fw = self.w.fw
        with quiet():
            fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y = self._saved
            canvas.reset_view()
            canvas.effects.clear()
            if "px_bg" in canvas.layers:
                canvas.layers["px_bg"].delete(destroy_shapes=True)
        super().tearDown()

    def view_to_screen(self, vx: float, vy: float) -> Tuple[float, float]:
        fw = self.w.fw
        vs = fw.view_scale
        return (fw._letterbox_pad_x + vx * vs, fw._letterbox_pad_y + (fw.design_height - vy) * vs)

    def predict(self, layer: str) -> Tuple[float, float]:
        fw = self.w.fw
        x, y = AT[layer]
        if layer == "world":
            vx, vy = fw.world_to_view_coords(x, y)
        elif layer == "parallax":
            m = canvas._engine._layer_partial_matrix(registry().layers["px_bg"])
            vx, vy = m.mapXY(x, y)
        else:
            vx, vy = x, y
        return self.view_to_screen(vx, vy)

    def _cell(self, display: str, camera: str, layer: str, post: str) -> None:
        fw = self.w.fw
        vs, (px, py) = DISPLAYS[display]
        fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y = vs, px, py
        canvas.reset_view()
        canvas.effects.clear()
        if post == "post on":
            canvas.effects.add(Vignette())
        CAMERAS[camera]()
        layer_key = {"world": "default", "parallax": "px_bg", "ui": "ui"}[layer]
        with quiet():
            r = self.track(Rect(center=AT[layer], width=SIZE, height=SIZE, color="white",
                                line_width=0, layer=layer_key))
        try:
            self.w.step(1)
            img = _screen(self.w.surface)
            got = brightest(img)
            want = self.predict(layer)
            key = f"{display} | {camera} | {layer} | {post}"
            err = math.hypot(got[0] - want[0], got[1] - want[1])
            if err > TOL:
                if key in KNOWN:
                    self.skipTest(f"known: {KNOWN[key]}")
                self.fail(f"{key}: brightest pixel at {tuple(round(v, 1) for v in got)}, "
                          f"predicted {tuple(round(v, 1) for v in want)} ({err:.1f} px off)")
            elif key in KNOWN:
                self.fail(f"KNOWN entry no longer fails; remove it: {key!r}")
        finally:
            with quiet():
                r.destroy()
            self.w.step(1)

    def _matrix(self, layer: str, post: str) -> None:
        for display in DISPLAYS:
            for camera in CAMERAS:
                with self.subTest(display=display, camera=camera):
                    self._cell(display, camera, layer, post)


for _l in LAYERS:
    for _p in POST:
        setattr(TestPixelOracle, "test_" + "".join(ch if ch.isalnum() else "_" for ch in f"{_l}_{_p}"),
                (lambda l, p: lambda self: self._matrix(l, p))(_l, _p))


class TestLetterboxBands(SystemTestCase, unittest.TestCase):
    """LB1: in display letterbox (maximized / fullscreen) the bands stay black.

    Red bodies straddle the four edges of the design rectangle (half in, half
    out) on a world layer and a parallax layer, under a zoomed-out camera, with
    post FX off / on (``Grain`` draws over the whole framebuffer). Every pixel
    outside the design rectangle must be black; the inner halves must draw (not
    vacuous). Pads come from ``letterbox_view``, as the real window gets them.
    """
    world_draw = True
    FBS = {"pad x": (2000, 1200), "pad y": (1600, 1600)}

    def setUp(self):
        super().setUp()
        fw = self.w.fw
        self._saved = (fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y,
                       fw._display_mode, fw.fb_width, fw.fb_height,
                       fw._drawing_surface, fw._drawing_canvas, fw._scena_draw.skia_canvas)
        canvas.layers.create("lb_bg", pan_response=0.4, below="default")

    def tearDown(self):
        fw = self.w.fw
        with quiet():
            (fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y,
             fw._display_mode, fw.fb_width, fw.fb_height,
             fw._drawing_surface, fw._drawing_canvas, fw._scena_draw.skia_canvas) = self._saved
            canvas.reset_view()
            canvas.effects.clear()
            if "lb_bg" in canvas.layers:
                canvas.layers["lb_bg"].delete(destroy_shapes=True)
        super().tearDown()

    def _frame(self, fb: str, display: str, post: str) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        from scena.orchestration import letterbox_view
        fw = self.w.fw
        w, h = self.FBS[fb]
        surf = skia.Surface(w, h)
        fw.fb_width, fw.fb_height = w, h
        fw._drawing_surface, fw._drawing_canvas = surf, surf.getCanvas()
        fw._scena_draw.skia_canvas = fw._drawing_canvas
        W, H = float(fw.design_width), float(fw.design_height)
        fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y = letterbox_view(w, h, W, H)
        fw._display_mode = display
        canvas.reset_view()
        canvas.effects.clear()
        if post == "post on":
            canvas.effects.add(Grain(amount=0.5))
        canvas.zoom_to(0.9)
        r = 0.12 * min(W, H)
        edges = ((0.0, H / 2), (W, H / 2), (W / 2, 0.0), (W / 2, H))
        with quiet():
            shapes = [self.track(Rect(center=c, width=2 * r, height=2 * r, color="red",
                                      line_width=0, layer=layer))
                      for layer in ("default", "lb_bg") for c in edges]
        try:
            self.w.step(1)
            img = _screen(surf)
        finally:
            with quiet():
                for sh in shapes:
                    sh.destroy()
            self.w.step(1, draw=False)
        vs, px, py = fw.view_scale, fw._letterbox_pad_x, fw._letterbox_pad_y
        rect = (int(math.ceil(px)), int(math.ceil(py)),
                int(math.floor(px + W * vs)), int(math.floor(py + H * vs)))
        return img, rect

    def _cell(self, fb: str, post: str, display: str = "maximized") -> int:
        img, (x0, y0, x1, y1) = self._frame(fb, display, post)
        outside = np.ones(img.shape[:2], bool)
        outside[y0:y1, x0:x1] = False
        lit = img[..., :3].max(axis=-1) > 8
        red = (img[..., 0] > 120) & (img[..., 1] < 80)
        inside = red[y0:y1, x0:x1]
        self.assertGreater(int(inside.sum()), 1000, f"{fb} | {post}: no body drew inside")
        return int((lit & outside).sum())

    def test_bands_stay_black(self):
        for display in ("maximized", "fullscreen"):
            for fb in self.FBS:
                for post in POST:
                    with self.subTest(display=display, fb=fb, post=post):
                        n = self._cell(fb, post, display)
                        self.assertEqual(n, 0, f"{display} | {fb} | {post}: {n} lit pixels "
                                         "in the letterbox bands")

    def test_windowed_draws_past_the_design_rect(self):
        """Not vacuous: the same frame windowed (no bands) does reach outside."""
        for fb in self.FBS:
            with self.subTest(fb=fb):
                self.assertGreater(self._cell(fb, "post off", "windowed"), 1000)


class TestAxes(unittest.TestCase):
    def test_known_keys_name_cells(self):
        for key in KNOWN:
            d, c, l, p = key.split(" | ")
            self.assertIn(d, DISPLAYS); self.assertIn(c, CAMERAS)
            self.assertIn(l, LAYERS); self.assertIn(p, POST)


class TestCanaries(unittest.TestCase):
    def test_catches_a_draw_that_drops_the_letterbox(self):
        import scena.orchestration as orch
        real = orch.ScenaFramework._apply_view_transform

        def no_pad(self, skia_canvas=None, *, camera=True, _r=real):
            px, py = self._letterbox_pad_x, self._letterbox_pad_y
            self._letterbox_pad_x = self._letterbox_pad_y = 0.0
            try:
                return _r(self, skia_canvas, camera=camera)
            finally:
                self._letterbox_pad_x, self._letterbox_pad_y = px, py
        assert_catches(self, "test_diff_pipeline.TestPixelOracle.test_world_post_off",
                       [(orch.ScenaFramework, "_apply_view_transform", no_pad)],
                       "a scene drawn without the letterbox offset")

    def test_catches_bands_left_unmasked(self):
        import scena.orchestration as orch
        assert_catches(self, "test_diff_pipeline.TestLetterboxBands.test_bands_stay_black",
                       [(orch.ScenaFramework, "_mask_letterbox_bands", lambda self, c: None)],
                       "world geometry spilling into the letterbox bands (LB1)")


if __name__ == "__main__":
    unittest.main()
