"""Engine dispatch by kind must accept subclasses (bug class: ``type(x).__name__``).

Before 2026-10-02 the engine asked ``type(obj).__name__ == "Sprite"`` (or
``in ("Rect", "Square")``, ``== "Circle"`` …) in a dozen places. Every author
subclass (``class Pad(Rect)``, ``class Ship(Sprite)``) and every Scena
subclass of Sprite (``Svg``, ``SpriteButton``) fell through: ``.box`` and
``confine(by="box")`` raised "unsupported", ``.hue`` raised "Sprite-only",
force-field looks lost their sprite outline.

The fix: ``scena.entity.scena_kind`` (nearest Scena class in the MRO) and
``is_sprite_family`` (the bitmap family). The static test keeps new
``type(x).__name__`` comparisons out of ``scena/``.

    python -m unittest tests.test_kind_dispatch -v
"""
from __future__ import annotations

import os
import re
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import Box, Circle, Ellipse, HueShift, Rect, Sprite, Svg, Text  # noqa: E402
from scena.entity import is_sprite_family, scena_kind  # noqa: E402
from scena.recipes import _ff_sprite_shield_scale, _forcefield_kind, _is_circle_like  # noqa: E402
from scena.track import Track  # noqa: E402

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
    '<rect width="20" height="10" fill="red"/></svg>'
)


class Pad(Rect):
    pass


class Ball(Circle):
    pass


class Egg(Ellipse):
    pass


class Ship(Sprite):
    pass


class Logo(Svg):
    pass


class Score(Text):
    pass


def _sprite(cls=Sprite):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return cls("player.png", center=(0, 0))


class TestScenaKind(unittest.TestCase):
    def setUp(self):
        self._owned = []

    def tearDown(self):
        for o in self._owned:
            o.destroy()

    def track(self, o):
        self._owned.append(o)
        return o

    def test_author_subclass_reads_as_its_scena_base(self):
        self.assertEqual(scena_kind(self.track(Pad(center=(0, 0), width=4, height=2))), "Rect")
        self.assertEqual(scena_kind(self.track(Ball(center=(0, 0), radius=2))), "Circle")
        self.assertEqual(scena_kind(self.track(_sprite(Ship))), "Sprite")
        self.assertEqual(scena_kind(self.track(Logo(_SVG))), "Svg")

    def test_scena_subclasses_keep_their_own_name(self):
        from scena import Square
        self.assertEqual(scena_kind(self.track(Square(center=(0, 0), length=3))), "Square")
        self.assertEqual(scena_kind(self.track(Svg(_SVG))), "Svg")

    def test_sprite_family(self):
        for o in (_sprite(), _sprite(Ship), Svg(_SVG), Logo(_SVG)):
            self.track(o)
            self.assertTrue(is_sprite_family(o), type(o).__name__)
        self.assertFalse(is_sprite_family(self.track(Circle(center=(0, 0), radius=1))))
        self.assertFalse(is_sprite_family(self.track(Text("x", center=(0, 0)))))


class TestSubclassesGoThroughTheEngine(unittest.TestCase):
    """Each verb that used to dispatch on the exact class name."""

    def setUp(self):
        self._owned = []

    def tearDown(self):
        for o in self._owned:
            o.destroy()

    def track(self, o):
        self._owned.append(o)
        return o

    def _frame_like(self):
        return [
            self.track(Pad(center=(0, 0), width=40, height=20)),
            self.track(Ball(center=(0, 0), radius=10)),
            self.track(Egg(center=(0, 0), width=30, height=10)),
            self.track(_sprite(Ship)),
            self.track(Svg(_SVG)),
            self.track(Logo(_SVG)),
            self.track(Score("hi", center=(0, 0))),
        ]

    def test_box_and_confine_by_box(self):
        room = Box(center=(0, 0), width=1000, height=1000)
        for o in self._frame_like():
            with self.subTest(kind=type(o).__name__):
                self.assertIsInstance(o.box, Box)
                o.confine(room, by="box")

    def test_box_matches_base_class_box(self):
        pad = self.track(Pad(center=(5, 6), width=40, height=20))
        rect = self.track(Rect(center=(5, 6), width=40, height=20))
        self.assertEqual(
            (pad.box.center.x, pad.box.center.y, pad.box.width, pad.box.height),
            (rect.box.center.x, rect.box.center.y, rect.box.width, rect.box.height),
        )

    def test_hue_stamp_on_every_sprite_body(self):
        for o in (self.track(_sprite(Ship)), self.track(Svg(_SVG)), self.track(Logo(_SVG))):
            with self.subTest(kind=type(o).__name__):
                o.hue = True
                self.assertIsInstance(o.hue, HueShift)
                o.hue = None

    def test_text_subclass_keeps_text_refusals(self):
        s = self.track(Score("hi", center=(0, 0)))
        with self.assertRaisesRegex(TypeError, "Text does not support .hue"):
            s.hue = True

    def test_force_field_dispatch(self):
        self.assertEqual(_forcefield_kind(self.track(_sprite(Ship))), "ellipse")
        self.assertEqual(_forcefield_kind(self.track(Svg(_SVG))), "ellipse")
        self.assertTrue(_is_circle_like(self.track(Ball(center=(0, 0), radius=3))))
        self.assertEqual(
            _ff_sprite_shield_scale(self.track(_sprite(Ship))),
            _ff_sprite_shield_scale(self.track(_sprite())),
        )

    def test_track_from_sprite_subclass(self):
        ship = self.track(_sprite(Ship))
        t = self.track(Track(ship))
        self.assertGreater(t.length, 0.0)


class TestNoNameDispatchInScena(unittest.TestCase):
    """Static guard: no new ``type(x).__name__ ==/!=/in`` dispatch in ``scena/``."""

    PATTERN = re.compile(r"type\([\w.]*\)\.__name__\s*(==|!=|in\s|not\s+in\s)")

    def test_no_type_name_comparisons(self):
        from source_support import iter_files
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scena")
        bad = []
        for path in iter_files(root, ".py"):
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if self.PATTERN.search(line) and "# exact-type:" not in line:
                        bad.append(f"scena/{os.path.basename(path)}:{n}: {line.strip()}")
        self.assertEqual(
            bad, [],
            "Dispatch with scena_kind(obj) / is_sprite_family(obj) (scena.entity), "
            "or mark a deliberate exact-type check with '# exact-type: <reason>'.",
        )


if __name__ == "__main__":
    unittest.main()
