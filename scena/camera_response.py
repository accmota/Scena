"""Camera response for shape layers (pan / zoom / rotation / scroll).

Shared vocabulary with background fields, but layers apply a real affine
matrix at draw time (not SkSL UV offsets). Kept separate from
``scena/background.py`` so procedural background paths stay untouched.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import skia

# Match ScenaCanvas._CAMERA_EPS for neutral detection (float noise).
_RESPONSE_EPS = 1e-9


@dataclass(frozen=True)
class CameraResponse:
    """Per-layer camera response. Immutable — set only at layer creation.

    Defaults ``(1, 1, 1, (0, 0))`` mean full camera tracking (today's single
    global CTM). Non-neutral values mark a parallax layer: interactive and
    collidable shapes are forbidden there (see :class:`registry.ParallaxLayerError`).
    """

    pan_response: float = 1.0
    zoom_response: float = 1.0
    rotation_response: float = 1.0
    scroll: Tuple[float, float] = (0.0, 0.0)

    @property
    def is_neutral(self) -> bool:
        """True when this response is identical to today's full-camera path."""
        sx, sy = self.scroll
        return (
            abs(float(self.pan_response) - 1.0) < _RESPONSE_EPS
            and abs(float(self.zoom_response) - 1.0) < _RESPONSE_EPS
            and abs(float(self.rotation_response) - 1.0) < _RESPONSE_EPS
            and abs(float(sx)) < _RESPONSE_EPS
            and abs(float(sy)) < _RESPONSE_EPS
        )


def partial_camera_matrix(
    *,
    cx: float,
    cy: float,
    look_x: float,
    look_y: float,
    zoom: float,
    rotation_deg: float,
    rest_x: float,
    rest_y: float,
    pan_response: float = 1.0,
    zoom_response: float = 1.0,
    rotation_response: float = 1.0,
) -> skia.Matrix:
    """World → design-space matrix with partial camera response.

    Same composition recipe as :meth:`ScenaCanvas._sync_camera`
    (``T(center) · R · S · T(-look)``), with look / zoom / rotation lerped
    toward the composition rest::

        look_eff  = rest + (look − rest) · pan_response
        zoom_eff  = 1 + (zoom − 1) · zoom_response
        rot_eff   = rotation · rotation_response

    At ``(pan_response, zoom_response, rotation_response) = (1, 1, 1)`` this is
    identical to the full camera matrix for the same look/zoom/rotation.
    """
    p = float(pan_response)
    zr = float(zoom_response)
    rr = float(rotation_response)
    rx = float(rest_x)
    ry = float(rest_y)
    look_eff_x = rx + (float(look_x) - rx) * p
    look_eff_y = ry + (float(look_y) - ry) * p
    z = max(1.0 + (float(zoom) - 1.0) * zr, 1e-6)
    rot = float(rotation_deg) * rr
    m = skia.Matrix()
    m.setTranslate(float(cx), float(cy))
    m.preRotate(rot)
    m.preScale(z, z)
    m.preTranslate(-look_eff_x, -look_eff_y)
    return m


class ScrollState:
    """Accumulates author scroll rate (design units/sec, y-up).

    The rate can change live without popping. Fed world time once per frame
    (``advance_layer_scroll``), so a gap is real world time and is integrated
    in full: the run loop already caps a frame at ``MAX_FRAME_DT``.
    """

    __slots__ = ("_rate", "_accum", "_last_t")

    def __init__(self, rate: Tuple[float, float] = (0.0, 0.0)) -> None:
        sx, sy = float(rate[0]), float(rate[1])
        if not math.isfinite(sx) or not math.isfinite(sy):
            raise ValueError("scroll rate must be finite")
        self._rate = (sx, sy)
        self._accum = [0.0, 0.0]
        self._last_t: Optional[float] = None

    @property
    def rate(self) -> Tuple[float, float]:
        return self._rate

    @rate.setter
    def rate(self, value: Tuple[float, float]) -> None:
        sx, sy = float(value[0]), float(value[1])
        if not math.isfinite(sx) or not math.isfinite(sy):
            raise ValueError("scroll rate must be finite")
        self._rate = (sx, sy)

    @property
    def accum(self) -> Tuple[float, float]:
        """Accumulated design-space offset applied as pre-translate at draw."""
        return (float(self._accum[0]), float(self._accum[1]))

    def advance(self, t: float) -> None:
        """Integrate rate over world time (call once per frame)."""
        t = float(t)
        if not math.isfinite(t):
            return
        last = self._last_t
        if last is None:
            self._last_t = t
            return
        dt = t - float(last)
        self._last_t = t
        if dt <= 0.0:
            return
        sx, sy = self._rate
        self._accum[0] += float(sx) * dt
        self._accum[1] += float(sy) * dt

    def reset(self) -> None:
        """Zero accumulated offset (rate unchanged)."""
        self._accum = [0.0, 0.0]
