"""``probe_private(obj, name, default)`` answers what ``getattr`` does.

Rule under test (Sprite Design.md, "Construction cost"): engine code that
probes a private field that may not be set yet (``_tx_state``,
``_blit_gray_cf``, ``_rotation`` before its first write, ``_destroyed`` on a
half-built object) reads it with ``object.__getattribute__`` and falls back
to the default, instead of ``getattr`` falling into ``Entity.__getattr__``,
which builds an error message only for ``getattr`` to swallow it. For a
private name the two agree: a private name is never ink, and every error that
path raises is an ``AttributeError`` (``DestroyedError`` included).

Bug class guarded: a probe helper that answers differently from ``getattr``
(a destroyed actor, a class default, a set field).
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena.entity import Entity
from scena.shapes import Circle, Rect
from scena.sprite import Sprite
from scena.state import probe_private

TILE = os.path.join(ROOT, "examples", "media", "tilesets", "Tiles", "2.png")
NAMES = ("_tx_state", "_blit_gray_cf", "_visual", "_rotation", "_scale", "_destroyed",
         "_defining_part_names", "_never_set_anywhere", "_ink", "_collider")
SENTINEL = object()


class TestSameAsGetattr(unittest.TestCase):
    def test_live_destroyed_and_plain(self):
        objs = [Sprite(TILE, size=32), Rect(center=(0, 0), width=4, height=4),
                Circle(center=(0, 0), radius=3), Entity(), object()]
        objs[0].angle = 30
        for stage in ("live", "destroyed"):
            for o in objs:
                for name in NAMES:
                    self.assertIs(probe_private(o, name, SENTINEL), getattr(o, name, SENTINEL),
                                  f"{stage} {type(o).__name__}.{name}")
            for o in objs[:4]:
                o.destroy()


if __name__ == "__main__":
    unittest.main()
