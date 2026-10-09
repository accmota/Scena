"""Graphics and SpatialFx refuse ``.x`` / ``.y`` instead of storing dead ink.

The bug class: any pose actor whose position is ``.center`` must not accept
``x`` / ``y`` as ink, on write, read, bracket ``@=``, or ``_link_field``.
Point keeps real axis slots. A bare Entity still uses those names as ink.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena.history  # noqa: F401 — registers _Stroke and friends
import scena.spatial_fx_effects  # noqa: F401 — Fire, Rain, …
import scena.sprite  # noqa: F401
import scena.text  # noqa: F401
import scena.track  # noqa: F401
from scena.entity import Entity, Graphic, _LOOK_MISSING, _SET_OBJECT
from scena.shapes import Circle, Point, _xy_of
from scena.spatial_fx import SpatialFx

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _concrete(cls):
    found = []

    def walk(base):
        for sub in base.__subclasses__():
            walk(sub)
            if sub.__name__.startswith("_"):
                continue
            if inspect.isabstract(sub):
                continue
            found.append(sub)

    walk(cls)
    return found


def _try_build(cls):
    try:
        return cls()
    except Exception:
        return None


def _has_real_xy(obj) -> bool:
    """Point-style axis slots, not the pose guard."""
    route = getattr(type(obj), "_setattr_route", {}) or {}
    desc = route.get("x")
    return desc is not None and desc is not _SET_OBJECT and desc is not _LOOK_MISSING


class TestGraphicXyGuard(unittest.TestCase):
    def test_every_pose_actor_refuses_xy(self):
        built = []
        for cls in _concrete(Graphic) + _concrete(SpatialFx):
            obj = _try_build(cls)
            if obj is None or _has_real_xy(obj):
                continue
            built.append(obj)

        names = {type(obj).__name__ for obj in built}
        for required in ("Circle", "Rect", "Text", "Track", "Fire"):
            self.assertIn(required, names, names)

        for obj in built:
            kind = type(obj).__name__
            for axis in ("x", "y"):
                with self.assertRaises(AttributeError) as caught:
                    setattr(obj, axis, 10)
                self.assertIn(".center", str(caught.exception), kind)
                ink = getattr(obj, "_ink", None) or {}
                self.assertNotIn(axis, ink, kind)

                with self.assertRaises(AttributeError) as caught:
                    getattr(obj, axis)
                self.assertIn(".center", str(caught.exception), kind)

                with self.assertRaises(AttributeError):
                    obj[axis]

                with self.assertRaises(AttributeError):
                    obj._link_field(axis, lambda: 1)

            self.assertFalse(hasattr(obj, "x"))
            self.assertFalse(hasattr(obj, "y"))

    def test_callable_assign_uses_the_pose_hint(self):
        circle = Circle(radius=4)
        with self.assertRaises(AttributeError) as caught:
            circle.x = lambda: 1
        self.assertIn("move_by", str(caught.exception))
        self.assertNotIn("x", getattr(circle, "_ink", None) or {})

    def test_point_axes_still_read_write_and_link(self):
        src = Point(4, 7, layer=None)
        point = Point(0, 0, layer=None)
        point.x = 2
        point.y = 3
        self.assertEqual(float(point.x), 2.0)
        self.assertEqual(float(point.y), 3.0)
        point["x"] @= lambda: src.x
        point["y"] @= lambda: src.y
        src.x = 11
        src.y = 12
        self.assertAlmostEqual(float(point.x), 11.0)
        self.assertAlmostEqual(float(point.y), 12.0)

    def test_bare_entity_keeps_xy_ink(self):
        entity = Entity()
        entity.x = 1
        entity.y = 2
        self.assertEqual(entity.x, 1)
        self.assertEqual(entity.y, 2)
        self.assertIn("x", entity._ink)

    def test_xy_of_still_reads_center(self):
        circle = Circle(center=(3, 4), radius=1)
        self.assertEqual(_xy_of(circle), (3.0, 4.0))
        self.assertFalse(hasattr(circle, "x"))


if __name__ == "__main__":
    unittest.main()
