"""Jagged look strokes drawn as plain paths (Electric*, Ink, shock stacks).

A look's ``DiscretePathEffect`` stroke handed to Skia as a paint effect has no
cache key on the GPU, so Skia draws every such anti-aliased stroke wider than
a pixel through its software path renderer when the context has no MSAA: a
CPU mask the size of the path, uploaded each draw. Skia turns MSAA off for
every Intel GPU on OpenGL (a driver workaround: ``maxSurfaceSampleCountFor
ColorType`` is 1 on an Iris Xe whose ``GL_MAX_SAMPLES`` is 16), and the mask
pays the MSVC wheel's slow raster (Testing Design WP54).

Here the effect is applied once to the host's local geometry
(``PathEffect.filterPath``), the result is cached by geometry and effect, and
drawn with the same paint minus the effect. Skia does the same steps on a
raster canvas, so a headless frame keeps its bytes (``test_pe_bake``); on
the GPU the plain path has a key and takes a faster route (a stable path:
~10× cheaper a draw; a moving one, re-rasterised at each sub-pixel offset,
~2–4× at hero sizes).

On only for a GPU context without MSAA (``configure``, from
``orchestration._init_skia``): with MSAA (the Mac's GPU) Skia's atlas renderer
already draws such a stroke on the GPU and the bake would add Python per draw;
a raster canvas gains nothing. Tests turn it on to check the bytes. Only
``SkDiscretePathEffect`` (the jitter does not read the canvas matrix or cull
rect; a dash does read the cull rect) and only on a real canvas. The stand-in
serves ``scena.shapes`` kinds, whose ``_geometry_draw`` is canvas calls only
(``visuals._geometry_tape_ok``).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

import skia

# Set by ``configure``; also the A/B switch (``game_bench.py --ab
# scena._pe_bake:ENABLED``).
ENABLED = False

# Filtered paths by (geometry key, effect bytes). Bounded like
# ``recipes._DISCRETE_PE_CACHE``: a few hosts × passes × live seeds.
_CACHE: Dict[Tuple[Any, bytes], skia.Path] = {}
_CACHE_MAX = 512

_DISCRETE = "SkDiscretePathEffect"


def configure(context) -> None:
    """On for a GPU ``context`` that cannot multisample, off otherwise."""
    global ENABLED
    ENABLED = context is not None and int(
        context.maxSurfaceSampleCountForColorType(skia.kRGBA_8888_ColorType)) <= 1


def bake_target(skia_canvas, paint):
    """``skia_canvas`` wrapped for ``paint``'s Discrete effect, or itself."""
    if type(skia_canvas) is not skia.Canvas:
        return skia_canvas
    pe = paint.getPathEffect()
    if pe is None or pe.getTypeName() != _DISCRETE:
        return skia_canvas
    return PeBakeCanvas(skia_canvas, paint, pe)


def without_path_effect(paint: skia.Paint) -> skia.Paint:
    """A copy of ``paint`` with no path effect (``setPathEffect(None)`` is
    refused by skia-python, so the fields are copied one by one). Effects
    are read with ``ref*``: an image filter from ``getImageFilter`` cannot be
    set on another paint ("Unable to cast from non-held to held instance")."""
    q = skia.Paint()
    q.setAntiAlias(paint.isAntiAlias())
    q.setDither(paint.isDither())
    q.setStyle(paint.getStyle())
    q.setStrokeWidth(paint.getStrokeWidth())
    q.setStrokeMiter(paint.getStrokeMiter())
    q.setStrokeCap(paint.getStrokeCap())
    q.setStrokeJoin(paint.getStrokeJoin())
    q.setColor4f(paint.getColor4f())
    q.setBlendMode(paint.getBlendMode())
    shader = paint.refShader()
    if shader is not None:
        q.setShader(shader)
    color_filter = paint.refColorFilter()
    if color_filter is not None:
        q.setColorFilter(color_filter)
    mask = paint.refMaskFilter()
    if mask is not None:
        q.setMaskFilter(mask)
    image_filter = paint.refImageFilter()
    if image_filter is not None:
        q.setImageFilter(image_filter)
    return q


# Source paths as Skia's raster device builds them for a draw with a path
# effect (SkBitmapDevice / SkDraw): an oval starts at index 1 (C++
# ``SkPath::Oval``'s default; skia-python's ``Path.Oval`` defaults to 0),
# a rect at 0, an rrect at 6.

def _oval_path(rect: skia.Rect) -> skia.Path:
    p = skia.Path()
    p.addOval(rect, skia.PathDirection.kCW, 1)
    return p


def _circle_path(x: float, y: float, r: float) -> skia.Path:
    return _oval_path(skia.Rect.MakeLTRB(x - r, y - r, x + r, y + r))


def _rrect_path(rrect: skia.RRect) -> skia.Path:
    p = skia.Path()
    p.addRRect(rrect, skia.PathDirection.kCW, 6)
    return p


def _line_path(x0: float, y0: float, x1: float, y1: float) -> skia.Path:
    p = skia.Path()
    p.moveTo(x0, y0)
    p.lineTo(x1, y1)
    return p


def _rect_key(r: skia.Rect) -> tuple:
    return (r.left(), r.top(), r.right(), r.bottom())


class PeBakeCanvas:
    """A canvas stand-in for one stroke: a host primitive drawn with that
    stroke's paint becomes ``drawPath(filtered, paint minus effect)``; any
    other call (pose transforms, another paint, an arc) goes to the canvas."""

    __slots__ = ("_canvas", "_paint", "_pe", "_pe_key", "_plain")

    def __init__(self, canvas: skia.Canvas, paint: skia.Paint, pe: skia.PathEffect) -> None:
        self._canvas = canvas
        self._paint = paint
        self._pe = pe
        self._pe_key = None
        self._plain = None

    def __getattr__(self, name):
        return getattr(self._canvas, name)

    def _bake(self, key: tuple, make_src: Callable[[], skia.Path]) -> bool:
        pe_key = self._pe_key
        if pe_key is None:
            pe_key = self._pe_key = bytes(self._pe.serialize())
        k = (key, pe_key)
        path = _CACHE.get(k)
        if path is None:
            src = make_src()
            path = skia.Path()
            if not self._pe.filterPath(path, src, skia.StrokeRec(self._paint), src.getBounds()):
                return False
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[k] = path
        plain = self._plain
        if plain is None:
            plain = self._plain = without_path_effect(self._paint)
        self._canvas.drawPath(path, plain)
        return True

    def drawCircle(self, *args):
        if len(args) == 4 and args[3] is self._paint:
            x, y, r = float(args[0]), float(args[1]), float(args[2])
            if self._bake(("c", x, y, r), lambda: _circle_path(x, y, r)):
                return
        self._canvas.drawCircle(*args)

    def drawOval(self, *args):
        if len(args) == 2 and args[1] is self._paint:
            rect = args[0]
            if self._bake(("o",) + _rect_key(rect), lambda: _oval_path(rect)):
                return
        self._canvas.drawOval(*args)

    def drawRect(self, *args):
        if len(args) == 2 and args[1] is self._paint:
            rect = args[0]
            if self._bake(("r",) + _rect_key(rect), lambda: skia.Path.Rect(rect)):
                return
        self._canvas.drawRect(*args)

    def drawRRect(self, *args):
        if len(args) == 2 and args[1] is self._paint:
            rrect = args[0]
            key = ("rr",) + _rect_key(rrect.rect()) + tuple(
                (v.x(), v.y()) for v in (
                    rrect.radii(skia.RRect.kUpperLeft_Corner),
                    rrect.radii(skia.RRect.kUpperRight_Corner),
                    rrect.radii(skia.RRect.kLowerRight_Corner),
                    rrect.radii(skia.RRect.kLowerLeft_Corner),
                )
            )
            if self._bake(key, lambda: _rrect_path(rrect)):
                return
        self._canvas.drawRRect(*args)

    def drawLine(self, *args):
        if len(args) == 5 and args[4] is self._paint:
            x0, y0, x1, y1 = (float(v) for v in args[:4])
            if self._bake(("l", x0, y0, x1, y1), lambda: _line_path(x0, y0, x1, y1)):
                return
        self._canvas.drawLine(*args)

    def drawPath(self, *args):
        if len(args) == 2 and args[1] is self._paint:
            src = args[0]
            if self._bake(("p", bytes(src.serialize())), lambda: src):
                return
        self._canvas.drawPath(*args)


def clear_cache() -> None:
    _CACHE.clear()
