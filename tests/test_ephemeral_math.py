"""
Regression: arithmetic Point/Vec2 results must not leak into the dependency graph.

Before the fix, each formula eval that did `point + vec` or `vec / 10` registered
new Containers permanently, so graph size (and FPS cost) grew every frame.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Point
from scena.scenamath import Vec2
from scena.state import DerivedAttributeError, State, get_scena_system
from tests.graph_support import settled_graph_size  # noqa: E402


def _stable_node_count(ss=None):
    """``len(nodes)`` after flushing pending weakref callbacks / cyclic GC.

    With the GC graph backstop, ``WeakValueDictionary`` may briefly retain
    dead entries until finalizers run. Snapshots used as baselines must
    collect first or absolute counts race with reclamation of leftovers
    from earlier tests in the same process.
    """
    return settled_graph_size(ss)


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


class TestVec2TempFastPath(unittest.TestCase):
    """``Vec2.temp`` (every arithmetic result) fills a fresh vector's
    ``__dict__`` directly, and a free vector's first ``length`` / ``angle``
    read stores the value without the guarded field write (Reactive Design,
    "Vec2 (scenamath.py)"). The result must be an ordinary Vec2: the same
    state the general constructor leaves, the same reads, a closed surface,
    and a formula source like any other.
    """

    @staticmethod
    def _general(fn):
        """Run ``fn`` with both fast paths off (they take finite values only)."""
        from unittest import mock
        import scena.scenamath as sm
        with mock.patch.object(sm, '_isfinite', lambda v: False):
            return fn()

    def _assert_same_state(self, fast, general):
        fd, gd = fast.__dict__, general.__dict__
        self.assertEqual(list(fd), list(gd), "same keys, same order")
        for key in fd:
            if key == '_parts':
                self.assertEqual(len(fd[key]), 0)
                self.assertIs(type(fd[key]), type(gd[key]))
            elif key == '_scena_system':
                self.assertIs(fd[key], gd[key])
            else:
                self.assertEqual((key, fd[key]), (key, gd[key]))

    def test_temp_has_the_general_constructors_state(self):
        from scena.state import Attribute, ephemeral_creation
        for x, y in ((3.0, 4.0), (0, 0), (-0.0, 0.0), (1e300, -1e300), (2, 7.5),
                     (Attribute(1.5), Attribute(-2))):
            with self.subTest(x=x, y=y):
                fast = Vec2.temp(x, y)
                with ephemeral_creation():
                    general = Vec2(x=float(as_value(x)), y=float(as_value(y)))
                self._assert_same_state(fast, general)
                self.assertIs(type(fast.x), float)
        a, b = Vec2.temp(1, 2), Vec2.temp(1, 2)
        self.assertIsNot(a.__dict__['_parts'], b.__dict__['_parts'])

    def test_results_are_ordinary_vectors(self):
        from scena.closed import is_sealed
        a, b = Vec2(3, 4), Vec2(1, -2)
        made = {
            "temp": Vec2.temp(3, 4), "a + b": a + b, "a - b": a - b,
            "a * 2": a * 2, "a / 2": a / 2, "-a": -a, "normalize": a.normalize(),
            "rotate": a.rotate(30), "perp": a.perp_left(), "lerp": a.lerp(b, 0.5),
            "vec_from_angle": __import__('scena').vec_from_angle(30, 5),
        }
        import math
        for label, v in made.items():
            with self.subTest(made=label):
                self.assertTrue(is_sealed(v))
                self.assertTrue(v._ephemeral)
                self.assertIsNone(v._node_id)
                x, y = v.x, v.y
                self.assertAlmostEqual(v.length, math.hypot(x, y))
                self.assertAlmostEqual(v.angle, math.degrees(math.atan2(y, x)))
                with self.assertRaises(AttributeError):
                    v.lenght = 5
                with self.assertRaises(DerivedAttributeError):
                    v.length = 5
                v.x, v.y = 6.0, 8.0          # computed fields follow a write
                self.assertEqual((v.length, round(v.angle, 6)), (10.0, 53.130102))

    def test_first_read_stores_what_the_general_write_stores(self):
        for x, y in ((3.0, 4.0), (0.0, 0.0), (0.0, -1.0), (-0.0, 0.0), (-2.0, 0.0)):
            with self.subTest(x=x, y=y):
                fast = Vec2.temp(x, y)
                general = self._general(lambda: Vec2.temp(x, y))
                values = (fast.length, fast.angle)
                self.assertEqual(values, self._general(lambda: (general.length, general.angle)))
                fd, gd = fast.__dict__, general.__dict__
                # The general write also builds a pose cell and a subtree
                # cache a free vector never uses; everything else is the same.
                if any(values):                             # it stored, so it bumped
                    self.assertIn('_pose_cell', gd)          # (the general write ran)
                self.assertLessEqual(set(gd) - set(fd), {'_pose_cell', '_subtree_cache'})
                self.assertEqual(set(fd) - set(gd), set())
                for key in fd:
                    if key not in ('_parts', '_scena_system'):
                        self.assertEqual((key, fd[key]), (key, gd[key]))

    @staticmethod
    def _source_scenario():
        """Results feeding formulas and links; what each sink reads after."""
        a, b = Vec2(3, 4), Vec2(1, 1)
        s = a + b
        first = s.length                              # read before linking
        whole = Vec2()
        whole @= s                                    # a link on a held result
        scaled = Vec2()
        scaled @= (lambda: (a + b) * 2)               # results built per pull
        measured = Vec2()
        measured["x"] @= (lambda: (a - b).length)
        held = Vec2()
        held @= (lambda: s * 3)
        before = (tuple(scaled), measured.x, tuple(held))
        a.x, a.y = 6.0, 8.0
        s.x, s.y = 6.0, 8.0
        return (first, before, tuple(whole), whole.length, tuple(scaled),
                measured.x, tuple(held), held.length, s.length, s.angle)

    def test_a_result_is_a_formula_source_like_before(self):
        fast = self._source_scenario()
        self.assertEqual(fast, self._general(self._source_scenario))
        self.assertEqual(fast[4], (14.0, 18.0))      # formulas over results follow
        self.assertAlmostEqual(fast[5], (5 ** 2 + 7 ** 2) ** 0.5)
        self.assertEqual((fast[8], round(fast[9], 6)), (10.0, 53.130102))

    def test_general_path_rules_unchanged(self):
        with self.assertRaises(ValueError):
            Vec2.temp(float('nan'), 0)
        with self.assertRaises(ValueError):
            Vec2.temp(0, float('inf'))
        with self.assertRaises((TypeError, ValueError)):
            Vec2.temp("a", 0)
        big = Vec2.temp(1e200, 1e200)             # x*x overflows: the general write
        self.assertEqual(big.length, float('inf'))

        class Mine(Vec2):
            pass
        m = Mine.temp(1, 2)                         # a subclass builds through its class
        self.assertIs(type(m), Mine)
        self.assertEqual((m.x, m.y, m.length), (1.0, 2.0, 5 ** 0.5))

        from scena.state import get_scena_system, set_scena_system
        ss = get_scena_system()
        set_scena_system(None)
        try:
            with self.assertRaises(RuntimeError):
                Vec2.temp(1, 2)
        finally:
            set_scena_system(ss)

    def test_point_and_pair_operands_still_work(self):
        v = Vec2(1, 2)
        self.assertIsInstance(v + Point.temp(1, 1), Point)
        with self.assertRaises(TypeError):          # a place is not a displacement (VB10)
            v - Point.temp(1, 1)
        self.assertEqual(v + (1, 1), (2.0, 3.0))
        w = Vec2(1, 2)
        w += Vec2.temp(1, 1)
        w -= (0.5, 0.5)
        with self.assertRaises(TypeError):          # VB10
            w += Point.temp(1, 0)
        self.assertEqual(w, (1.5, 2.5))
        with self.assertRaises(TypeError):
            w += 5


def as_value(v):
    from scena.state import as_payload
    return as_payload(v)


if __name__ == '__main__':
    unittest.main()
