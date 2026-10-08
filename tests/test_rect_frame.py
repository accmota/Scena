"""Rect and Box share one oriented-frame model (``shapes._RectFrame``).

Box used to carry a near-copy of Rect's construction models, ``_oriented_frame``,
Derivate materialization and per-model ``_update_impl_*``; the copies drifted
(Box's ``top_left`` model ignored mirrored corner names). Track C item 4.

    python tests/run_tiers.py focused test_rect_frame
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

from scena import Box, Rect  # noqa: E402
from scena.shapes import _RECT_NAMED_POINTS, _RectFrame  # noqa: E402

MODELS = {
    "center_wh": dict(center=(3, -2), width=40, height=16, angle=17),
    "top_left_wh": dict(top_left=(3, -2), width=40, height=16, angle=17),
    "corner_corner": dict(p1=(3, -2), p2=(43, 14), angle=17),
    "point_vec": dict(p1=(3, -2), vec=(40, 16), angle=17),
    "spine": dict(p1=(3, -2), p2=(41, 9), height=12, anchor="cap"),
}
SIGNS = ((1, 1), (-1, 1), (1, -1), (-1, -1))


def _xy(p):
    return (round(float(p.x), 6), round(float(p.y), 6))


# Named points both have (Box has no left / right_square_center).
NAMES = [n for n in _RECT_NAMED_POINTS if hasattr(Box, n) and hasattr(Rect, n)]


def _reads(obj):
    frame = tuple(round(float(v), 6) for v in obj._oriented_frame())
    return frame, {n: _xy(getattr(obj, n)) for n in NAMES}


class TestBoxReadsLikeRect(unittest.TestCase):
    def test_every_model_every_name_signs_and_a_turn(self):
        for model, kw in MODELS.items():
            for signs in SIGNS:
                with self.subTest(model=model, signs=signs):
                    b, r = Box(**kw), Rect(**kw)
                    # As a copy or a flip would leave them (mirrored names).
                    b.__dict__["_name_signs"] = signs
                    r.__dict__["_name_signs"] = signs
                    self.assertEqual(_reads(b), _reads(r))
                    b.rotate_by(10)
                    r.rotate_by(10)
                    self.assertEqual(_reads(b), _reads(r))


class TestOneCopyOfTheFrame(unittest.TestCase):
    """Neither class re-defines what the mixin shares (allowed overrides named)."""

    ALLOWED = {
        ("Rect", "_publish_heading"): "writes the pose store",
        ("Box", "_oriented_frame"): "snapshot center as floats, then the shared frame",
    }

    def test_shared_methods_are_not_copied_back(self):
        shared = {n for n, v in vars(_RectFrame).items() if callable(v) and not n.startswith("__")}
        for cls in (Rect, Box):
            own = {n for n in vars(cls) if n in shared}
            extra = {n for n in own if (cls.__name__, n) not in self.ALLOWED}
            self.assertEqual(extra, set(), f"{cls.__name__} copies _RectFrame methods")


if __name__ == "__main__":
    unittest.main(verbosity=2)
