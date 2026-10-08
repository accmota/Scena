"""
Regression: arithmetic Point/Vec2 results must not leak into the dependency graph.

Before the fix, each formula eval that did `point + vec` or `vec / 10` registered
new Containers permanently, so graph size (and FPS cost) grew every frame.
"""

import gc
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Point
from scena.scenamath import Vec2
from scena.state import State, get_scena_system


def _stable_node_count(ss=None):
    """``len(nodes)`` after flushing pending weakref callbacks / cyclic GC.

    With the GC graph backstop, ``WeakValueDictionary`` may briefly retain
    dead entries until finalizers run. Snapshots used as baselines must
    collect first or absolute counts race with reclamation of leftovers
    from earlier tests in the same process.
    """
    gc.collect()
    graph = (ss or get_scena_system()).dependency_graph
    return len(graph.nodes)


class TestEphemeralMath(unittest.TestCase):

    def test_vec2_temp_not_registered(self):
        v = Vec2.temp(1, 2)
        self.assertTrue(v._ephemeral)
        self.assertIsNone(v._node_id)
        ss = get_scena_system()
        self.assertNotIn(id(v), ss.dependency_graph.nodes)

    def test_point_temp_not_registered(self):
        p = Point.temp(3, 4)
        self.assertTrue(p._ephemeral)
        self.assertIsNone(p._node_id)
        ss = get_scena_system()
        self.assertNotIn(id(p), ss.dependency_graph.nodes)

    def test_arithmetic_does_not_grow_graph(self):
        st = State()
        st.create('t', initial=0.0)
        v1 = Vec2(10, 20)
        v2 = Vec2(1, 2)
        out = Vec2()
        out @= (lambda: v1 + v2 / 10)

        ss = get_scena_system()
        nodes_before = _stable_node_count(ss)

        for i in range(200):
            st.t = float(i)
            v1.x = 10 + i * 0.01
            _ = out.x

        nodes_after = _stable_node_count(ss)
        self.assertEqual(
            nodes_before, nodes_after,
            f"dependency graph grew by {nodes_after - nodes_before} nodes "
            f"during arithmetic formula evaluation"
        )

    def test_formula_point_plus_vec_stable_graph(self):
        p = Point(0, 0)
        v = Vec2(5, 5)
        dest = Point(0, 0)
        dest @= (lambda: p + v)

        ss = get_scena_system()
        nodes_before = _stable_node_count(ss)

        for i in range(100):
            v.x = float(i)
            self.assertEqual(dest.x, float(i))

        self.assertEqual(_stable_node_count(ss), nodes_before)


if __name__ == '__main__':
    unittest.main()
