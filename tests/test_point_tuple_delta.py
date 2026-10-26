"""Point ``+`` / ``-`` accept a ``(dx, dy)`` delta. ``+=`` does not teleport."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Circle, Point
from scena.scenamath import Vec2
from scena.state import State, get_scena_system
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


def _xy(point):
    return float(point.x), float(point.y)


class TestPointTupleDelta(unittest.TestCase):
    def test_add_and_sub_tuple_and_vec(self):
        point = Point(10, 20, layer=None)
        self.assertEqual(_xy(point + (2, -3)), (12.0, 17.0))
        self.assertEqual(_xy((2, -3) + point), (12.0, 17.0))
        self.assertEqual(_xy(point + Vec2(1, 4)), (11.0, 24.0))
        self.assertEqual(_xy(point - (2, -3)), (8.0, 23.0))
        self.assertEqual(_xy(point - Vec2(1, 4)), (9.0, 16.0))

        delta = point - Point(1, 5, layer=None)
        self.assertIsInstance(delta, Vec2)
        self.assertEqual((float(delta.x), float(delta.y)), (9.0, 15.0))

    def test_attribute_tuple_parts(self):
        state = State()
        state.create("dx", initial=2.0)
        state.create("dy", initial=-1.0)
        point = Point(10, 10, layer=None)
        self.assertEqual(_xy(point + (state.dx, state.dy)), (12.0, 9.0))

    def test_point_plus_point_and_inplace_raise(self):
        point = Point(1, 2, layer=None)
        other = Point(3, 4, layer=None)
        with self.assertRaises(TypeError) as caught:
            point + other
        self.assertIn("middle_point", str(caught.exception))

        ship = Circle(center=(4, 5), radius=1)
        with self.assertRaises(TypeError) as caught:
            ship.center += (1, 0)
        self.assertIn("move_by", str(caught.exception))
        self.assertEqual(_xy(ship.center), (4.0, 5.0))

        with self.assertRaises(TypeError) as caught:
            ship.center -= (1, 0)
        self.assertIn("move_by", str(caught.exception))
        self.assertEqual(_xy(ship.center), (4.0, 5.0))

        with self.assertRaises(TypeError):
            point += (1, 0)
        self.assertEqual(_xy(point), (1.0, 2.0))

    def test_result_is_detached(self):
        point = Point(1, 2, layer=None)
        result = point + (3, 4)
        self.assertTrue(result._ephemeral)
        self.assertIsNone(result._node_id)
        graph = get_scena_system().dependency_graph
        self.assertNotIn(id(result), graph.nodes)

    def test_formula_follows_the_ship(self):
        ship = Circle(center=(0, 0), radius=4)
        bullet = Circle(center=(0, 0), radius=1)
        bullet.center @= lambda: ship.center + (0, 10)
        self.assertEqual(_xy(bullet.center), (0.0, 10.0))
        ship.move_to(3, 4)
        self.assertEqual(_xy(bullet.center), (3.0, 14.0))


if __name__ == "__main__":
    unittest.main()
