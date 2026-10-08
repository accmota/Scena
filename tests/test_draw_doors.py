"""One actor, one picture, whichever draw path paints it (graphics review).

The 2026-10-08 review found paint knobs that the two draw paths read
differently:

* PB7: ``sprite.color = "blue"`` did nothing on the plain blit, but stroked a
  blue outline once any slow-path trigger was on.
* PB8: a ``Recolor`` visual ignored ``Sprite.alpha`` and ``blend``.
* HP10: ``line_width = 0`` drew a one-device-pixel hairline (Skia's width 0),
  where zero is a collapsed size and draws nothing.

Two oracles, neither a model of the renderer:

* **Two doors.** For each kind × paint knob, the frame drawn as computed and
  the frame drawn with the plain-blit flag forced off (the full path) are the
  same pixels.
* **Every knob counts on every path.** A sprite's ``alpha`` and ``blend``
  change the picture with and without a ``Recolor``. ``line_width = 0``
  draws what no line draws.

Known violations are shrink-only (``graphics_known.DRAW_DOORS``).

    python tests/run_tiers.py focused test_draw_doors
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from hypothesis_support import fresh_world, quiet  # noqa: E402
from tests.media_support import media  # noqa: E402
from test_diff_draw import render  # noqa: E402

import scena  # noqa: E402

SPRITE_ART = ("space", "enemyGreen1.png")

KINDS = {
    "Circle": lambda: scena.Circle(center=(80, 60), radius=25, color="gold"),
    "Rect": lambda: scena.Rect(center=(80, 60), width=60, height=30, angle=15, color="gold"),
    "Polygon": lambda: scena.Polygon(points=[(55, 40), (110, 45), (85, 85)], color="gold"),
    "Ellipse": lambda: scena.Ellipse(center=(80, 60), width=60, height=30, color="gold"),
    "Line": lambda: scena.Line(p1=(45, 40), p2=(115, 80), color="gold"),
    "Sprite": lambda: scena.Sprite(media(*SPRITE_ART), center=(80, 60), height=60),
}

# Knobs applied after construction; each must draw alike on both paths.
KNOBS = {
    "plain": lambda o: None,
    "line_width = 0": lambda o: setattr(o, "line_width", 0),
    "line_width = 4": lambda o: setattr(o, "line_width", 4),
    "set_alpha(0.5)": lambda o: o.set_alpha(0.5),
    "color = 'blue'": lambda o: setattr(o, "color", "blue"),
    "alpha = 0.5": lambda o: setattr(o, "alpha", 0.5),
    "blend = 'add'": lambda o: setattr(o, "blend", "add"),
}


def _build(kind, knob):
    with quiet():
        obj = KINDS[kind]()
        try:
            KNOBS[knob](obj)
        except Exception:  # noqa: BLE001  (the knob does not apply to this kind)
            obj.destroy()
            return None
    return obj


def _same(a, b, tol=2) -> bool:
    return int(np.abs(a.astype(int) - b.astype(int)).max()) <= tol


def door_violations() -> dict:
    out = {}
    with fresh_world():
        for kind in KINDS:
            for knob in KNOBS:
                obj = _build(kind, knob)
                if obj is None:
                    continue
                if not _same(render([obj]), render([obj], plain=False)):
                    out[f"{kind} | {knob} | plain blit vs full draw"] = ""
                obj.destroy()
    return out


def knob_violations() -> dict:
    """A knob that changes nothing on some path, or a zero width that draws."""
    out = {}
    with fresh_world():
        # line_width = 0 draws what no line draws (HP10).
        for kind in ("Circle", "Rect", "Polygon", "Ellipse"):
            zero, none = _build(kind, "line_width = 0"), _build(kind, "plain")
            none.line = None
            for path in (None, False):
                if not _same(render([zero], plain=path), render([none], plain=path), tol=0):
                    out[f"{kind} | line_width = 0 | draws a hairline ({'full' if path is False else 'as computed'})"] = ""
            zero.destroy()
            none.destroy()
        # Sprite alpha / blend change the picture, with and without a Recolor (PB8).
        for look in (None, "Recolor"):
            for knob in ("alpha = 0.5", "blend = 'add'"):
                base, tuned = _build("Sprite", "plain"), _build("Sprite", knob)
                if look:
                    base.visual = scena.Recolor("red")
                    tuned.visual = scena.Recolor("red")
                for path in (None, False):
                    if _same(render([base], plain=path), render([tuned], plain=path), tol=0):
                        where = "full" if path is False else "as computed"
                        out[f"Sprite | {look or 'no look'} | {knob} ignored ({where})"] = ""
                base.destroy()
                tuned.destroy()
    return out


class TestDrawDoors(unittest.TestCase):
    def test_both_paths_draw_the_same_picture(self):
        from graphics_known import shrink_only
        shrink_only(self, {**door_violations(), **knob_violations()}, "DRAW_DOORS")

    def test_canary_a_plain_blit_that_draws_nothing(self):
        from diff_support import assert_catches
        from scena.shapes import Shape
        assert_catches(self, "test_draw_doors.TestDrawDoors.test_both_paths_draw_the_same_picture",
                       [(Shape, "_blit_plain", lambda self, canvas: None)],
                       "a plain blit that skips the geometry")


if __name__ == "__main__":
    unittest.main(verbosity=2)
