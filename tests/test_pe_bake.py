"""Jagged look strokes drawn as baked plain paths (``scena._pe_bake``, WP54).

On a GPU without MSAA a ``DiscretePathEffect`` stroke on the paint took
Skia's software mask every draw. The bake applies the effect itself and
draws the plain path; on a raster canvas Skia does the same steps, so every
check here is byte equality against the paint-effect draw. The canary
proves the comparison sees a wrong source path (an oval started at index 0,
skia-python's ``Path.Oval`` default, against the raster device's 1).
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np
import skia

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (  # noqa: E402
    init, canvas, Circle, Rect, Ellipse, Line, Polygon,
    ElectricBolt, ElectricField, Ink, InkBleed, OrganicOutline,
)
from scena import _pe_bake  # noqa: E402
import scena.recipes as _recipes  # noqa: E402
import scena.visuals as _visuals  # noqa: E402
from scena.visuals import _CanvasTape, _draw_host_stroke  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _pixels(surface) -> np.ndarray:
    return surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)


def _surface(w: int = 160, h: int = 160):
    return skia.Surface.MakeRaster(skia.ImageInfo.Make(
        w, h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType))


_RRECT = skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(-30, -20, 30, 20), 8, 6)
_PRIMS = {
    "circle": lambda c, p: c.drawCircle(0.0, 0.0, 33.0, p),
    "oval": lambda c, p: c.drawOval(skia.Rect.MakeLTRB(-40, -22, 40, 22), p),
    "rect": lambda c, p: c.drawRect(skia.Rect.MakeLTRB(-35, -25, 35, 25), p),
    "rrect": lambda c, p: c.drawRRect(_RRECT, p),
    "line": lambda c, p: c.drawLine(-50.0, -10.0, 45.0, 20.0, p),
    "path": lambda c, p: c.drawPath(skia.Path.Polygon(
        [skia.Point(-40, -30), skia.Point(40, -20), skia.Point(0, 40)], True), p),
}
# A plain pose, a turned and scaled one off the pixel grid, a shrunk one
# (a 1.5 px stroke at 0.5 is a hairline-equivalent: Skia draws it as one).
_MATRICES = (
    skia.Matrix.Translate(80, 80),
    skia.Matrix.Translate(80.3, 79.6).preConcat(skia.Matrix.RotateDeg(23))
    .preConcat(skia.Matrix.Scale(1.3, 1.3)),
    skia.Matrix.Translate(80, 80).preConcat(skia.Matrix.Scale(0.5, 0.5)),
)


def _pe_paint(width: float, seed: int, *, cap=skia.Paint.kRound_Cap,
              join=skia.Paint.kRound_Join) -> skia.Paint:
    p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=width,
                   StrokeCap=cap, StrokeJoin=join, BlendMode=skia.BlendMode.kPlus)
    p.setColor4f(skia.Color4f(0.9, 0.8, 0.3, 0.75))
    p.setPathEffect(skia.DiscretePathEffect.Make(4.0, 5.0, seed))
    return p


def _draw_prim(fn, paint, matrix, *, baked: bool) -> np.ndarray:
    surf = _surface()
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    c.concat(matrix)
    target = _pe_bake.PeBakeCanvas(c, paint, paint.getPathEffect()) if baked else c
    fn(target, paint)
    return _pixels(surf)


class TestPrimitiveBytes(unittest.TestCase):
    """Each primitive a ``scena.shapes`` host draws, baked = paint effect."""

    def setUp(self):
        _pe_bake.clear_cache()

    def test_every_primitive_width_join_and_pose_keeps_its_bytes(self):
        joins = ((skia.Paint.kRound_Cap, skia.Paint.kRound_Join),
                 (skia.Paint.kButt_Cap, skia.Paint.kMiter_Join))
        for name, fn in _PRIMS.items():
            for width in (0.0, 1.5, 3.5):
                for cap, join in joins:
                    for mi, m in enumerate(_MATRICES):
                        paint = _pe_paint(width, 77, cap=cap, join=join)
                        with self.subTest(prim=name, width=width, join=str(join), pose=mi):
                            a = _draw_prim(fn, paint, m, baked=False)
                            b = _draw_prim(fn, paint, m, baked=True)
                            self.assertTrue(a.any(), "the primitive drew nothing")
                            self.assertTrue(np.array_equal(a, b))

    def test_a_cached_path_redraws_the_same_bytes(self):
        paint = _pe_paint(2.0, 5)
        first = _draw_prim(_PRIMS["circle"], paint, _MATRICES[1], baked=True)
        n = len(_pe_bake._CACHE)
        again = _draw_prim(_PRIMS["circle"], paint, _MATRICES[1], baked=True)
        self.assertEqual(len(_pe_bake._CACHE), n, "the second draw missed the cache")
        self.assertTrue(np.array_equal(first, again))

    def test_another_seed_is_another_entry(self):
        _draw_prim(_PRIMS["circle"], _pe_paint(2.0, 5), _MATRICES[0], baked=True)
        _draw_prim(_PRIMS["circle"], _pe_paint(2.0, 6), _MATRICES[0], baked=True)
        self.assertEqual(len(_pe_bake._CACHE), 2)

    def test_canary_an_oval_from_index_zero_is_caught(self):
        orig = _pe_bake._oval_path
        _pe_bake._oval_path = lambda rect: skia.Path.Oval(rect)
        try:
            paint = _pe_paint(3.5, 1, cap=skia.Paint.kButt_Cap, join=skia.Paint.kMiter_Join)
            a = _draw_prim(_PRIMS["oval"], paint, _MATRICES[2], baked=False)
            _pe_bake.clear_cache()
            b = _draw_prim(_PRIMS["oval"], paint, _MATRICES[2], baked=True)
        finally:
            _pe_bake._oval_path = orig
            _pe_bake.clear_cache()
        self.assertFalse(np.array_equal(a, b))

    def test_other_paints_and_an_arc_draw_as_given(self):
        paint = _pe_paint(2.0, 3)
        other = _pe_paint(2.0, 4)
        surf = _surface()
        c = surf.getCanvas()
        baker = _pe_bake.PeBakeCanvas(c, paint, paint.getPathEffect())
        baker.drawCircle(80.0, 80.0, 20.0, other)
        baker.drawArc(skia.Rect.MakeLTRB(40, 40, 120, 120), 0.0, 90.0, False, paint)
        self.assertEqual(len(_pe_bake._CACHE), 0)

    def test_the_cache_is_bounded(self):
        paint = _pe_paint(2.0, 9)
        surf = _surface(32, 32)
        baker = _pe_bake.PeBakeCanvas(surf.getCanvas(), paint, paint.getPathEffect())
        for i in range(_pe_bake._CACHE_MAX + 40):
            baker.drawCircle(0.0, 0.0, 1.0 + i * 0.01, paint)
        self.assertLessEqual(len(_pe_bake._CACHE), _pe_bake._CACHE_MAX)
        _pe_bake.clear_cache()


class TestPaintCopy(unittest.TestCase):

    def test_without_path_effect_keeps_every_other_field(self):
        p = skia.Paint(AntiAlias=False, Style=skia.Paint.kStrokeAndFill_Style, StrokeWidth=2.5,
                       StrokeMiter=3.0, StrokeCap=skia.Paint.kSquare_Cap,
                       StrokeJoin=skia.Paint.kBevel_Join, BlendMode=skia.BlendMode.kScreen)
        p.setDither(True)
        p.setColor4f(skia.Color4f(0.1, 0.2, 0.3, 0.4))
        p.setPathEffect(skia.DiscretePathEffect.Make(3.0, 2.0, 1))
        p.setShader(skia.Shaders.Color(skia.Color4f(1, 0, 0, 1)))
        p.setColorFilter(skia.ColorFilters.Blend(skia.ColorRED, skia.BlendMode.kMultiply))
        p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 2.0))
        p.setImageFilter(skia.ImageFilters.Blur(1.0, 1.0))
        q = _pe_bake.without_path_effect(p)
        self.assertIsNone(q.getPathEffect())
        self.assertEqual(q.isAntiAlias(), p.isAntiAlias())
        self.assertEqual(q.isDither(), p.isDither())
        self.assertEqual(q.getStyle(), p.getStyle())
        self.assertEqual(q.getStrokeWidth(), p.getStrokeWidth())
        self.assertEqual(q.getStrokeMiter(), p.getStrokeMiter())
        self.assertEqual(q.getStrokeCap(), p.getStrokeCap())
        self.assertEqual(q.getStrokeJoin(), p.getStrokeJoin())
        self.assertEqual(q.getBlendMode(), p.getBlendMode())
        c, d = q.getColor4f(), p.getColor4f()
        self.assertEqual((c.fR, c.fG, c.fB, c.fA), (d.fR, d.fG, d.fB, d.fA))
        for getter in ("getShader", "getColorFilter", "getMaskFilter", "getImageFilter"):
            self.assertIsNotNone(getattr(q, getter)(), getter)


class _Ctx:
    def __init__(self, samples: int) -> None:
        self.samples = samples

    def maxSurfaceSampleCountForColorType(self, _color_type) -> int:
        return self.samples


class TestGate(unittest.TestCase):
    """On only for a GPU without MSAA; only a real canvas, a Discrete
    effect and a ``scena.shapes`` host are wrapped."""

    def setUp(self):
        self._enabled = _pe_bake.ENABLED

    def tearDown(self):
        _pe_bake.ENABLED = self._enabled

    def test_configure_follows_the_sample_count(self):
        _pe_bake.configure(_Ctx(1))
        self.assertTrue(_pe_bake.ENABLED)
        _pe_bake.configure(_Ctx(4))
        self.assertFalse(_pe_bake.ENABLED)
        _pe_bake.configure(None)
        self.assertFalse(_pe_bake.ENABLED)

    def test_off_by_default(self):
        import subprocess
        out = subprocess.run(
            [sys.executable, "-c", "import scena, scena._pe_bake as b; print(b.ENABLED)"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        self.assertEqual(out.stdout.strip(), "False", out.stderr)

    def test_bake_target_wraps_only_a_discrete_effect_on_a_real_canvas(self):
        c = _surface(8, 8).getCanvas()
        self.assertIsInstance(_pe_bake.bake_target(c, _pe_paint(2.0, 1)), _pe_bake.PeBakeCanvas)
        plain = skia.Paint(Style=skia.Paint.kStroke_Style, StrokeWidth=2.0)
        self.assertIs(_pe_bake.bake_target(c, plain), c)
        dash = skia.Paint(Style=skia.Paint.kStroke_Style, StrokeWidth=2.0)
        dash.setPathEffect(skia.DashPathEffect.Make([4.0, 2.0], 0.0))
        self.assertIs(_pe_bake.bake_target(c, dash), c)
        tape = _CanvasTape(c)
        self.assertIs(_pe_bake.bake_target(tape, _pe_paint(2.0, 1)), tape)

    def test_stroke_host_wraps_only_when_on(self):
        init(width=200, height=200)
        seen = []
        circle = Circle(center=(50, 50), radius=12)
        circle._geometry_draw = lambda cv, fill_paint=None, stroke_paint=None: seen.append(cv)
        c = _surface(8, 8).getCanvas()
        _pe_bake.ENABLED = False
        _draw_host_stroke(circle, c, _pe_paint(2.0, 1))
        _pe_bake.ENABLED = True
        _draw_host_stroke(circle, c, _pe_paint(2.0, 1))
        self.assertIs(seen[0], c)
        self.assertIsInstance(seen[1], _pe_bake.PeBakeCanvas)


class TestLooksKeepTheirBytes(unittest.TestCase):
    """Every Discrete-effect look on every host kind: the frame with the
    bake on is the frame with it off, and the bake ran."""

    def setUp(self):
        init(width=240, height=240)
        # Process-wide, so tearDown puts it back: "low" left here turned off
        # bloom and Aura in later modules (deep serial pass 2026-11-03).
        self._quality = canvas.fx_quality
        canvas.fx_quality = "high"
        self._clocks = (_recipes._clock, _visuals._clock)
        _recipes._clock = _visuals._clock = lambda: 0.37     # one seed for both frames
        self._enabled = _pe_bake.ENABLED
        _pe_bake.clear_cache()

    def tearDown(self):
        _recipes._clock, _visuals._clock = self._clocks
        _pe_bake.ENABLED = self._enabled
        _pe_bake.clear_cache()
        canvas.fx_quality = self._quality

    def _hosts(self):
        rect = Rect(center=(120, 120), width=60, height=40)
        rect.rotate_by(17)
        return (
            Circle(center=(120.3, 119.6), radius=26),
            rect,
            Ellipse(center=(120, 120), width=80, height=44),
            Line(p1=(60, 100), p2=(180, 140)),
            Polygon(points=[(80, 80), (170, 95), (120, 170)]),
        )

    def _frame(self, shape, enabled: bool) -> np.ndarray:
        _pe_bake.ENABLED = enabled
        surf = _surface(240, 240)
        c = surf.getCanvas()
        c.clear(skia.Color4f(0, 0, 0, 1))
        shape.draw(c)
        return _pixels(surf)

    def test_each_look_on_each_host_at_each_quality(self):
        looks = (ElectricBolt, ElectricField, Ink, InkBleed, OrganicOutline)
        for quality in ("high", "medium", "low"):
            canvas.fx_quality = quality
            for look in looks:
                for shape in self._hosts():
                    shape.set_color("gold")
                    shape.line_width = 2.0
                    shape.visual = look()
                    with self.subTest(quality=quality, look=look.__name__,
                                      host=type(shape).__name__):
                        off = self._frame(shape, False)
                        self.assertEqual(len(_pe_bake._CACHE), 0)
                        on = self._frame(shape, True)
                        if quality == "high":
                            self.assertGreater(len(_pe_bake._CACHE), 0, "the bake never ran")
                        self.assertTrue(off.any(), "the look drew nothing")
                        self.assertTrue(np.array_equal(off, on))
                    _pe_bake.clear_cache()
                    shape.destroy()


if __name__ == "__main__":
    unittest.main()
