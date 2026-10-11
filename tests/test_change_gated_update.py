"""
Change-gated updates and keypress graph-stability regressions.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Circle, Point
from scena.scenamath import Vec2
from scena.state import State, Attribute, get_scena_system
from scena.input import KeyPressed
from tests.graph_support import settled_graph_size  # noqa: E402


def _settled_nodes(ss):
    """Graph size after garbage from earlier tests is gone. GC-backstop
    finalizers purge graph nodes; if they run mid-test the count drops and a
    "did not grow" check fails only when the module runs alone."""
    return settled_graph_size(ss)


class TestKeypressGraphStable(unittest.TestCase):
    def test_keypress_does_not_grow_graph(self):
        keyp = KeyPressed()
        c5 = Circle(center=(800, 700), radius=10)
        vt = Vec2(100, 100)
        st = State()
        st.create('var1', initial=0)
        st.create('var2', initial=0)

        st.var1 @= (lambda: vt.rotate(Point.temp(c5.center.x, c5.center.y).x))
        st.var2 @= (lambda: c5.center + vt)
        c5.center["x"] @= (lambda: 1200 if keyp("D") else 800)

        ss = get_scena_system()
        n0 = _settled_nodes(ss)

        for _ in range(50):
            keyp._press('A')
            keyp._release('A')

        for _ in range(10):
            keyp._press('D')
            keyp._release('D')

        n1 = _settled_nodes(ss)
        self.assertEqual(
            n0, n1,
            f"dependency graph grew by {n1 - n0} nodes on keypress"
        )

    def test_point_temp_does_not_link_attributes(self):
        p = Point(10, 20)
        ss = get_scena_system()
        n0 = _settled_nodes(ss)
        for _ in range(20):
            c = Point.temp(p.x, p.y)
            self.assertTrue(c._ephemeral)
            self.assertIsNone(c._node_id)
        self.assertEqual(_settled_nodes(ss), n0)


class TestChangeGatedUpdate(unittest.TestCase):
    def test_unchanged_formula_still_correct(self):
        """v1 pull over-marks; values must stay correct when sources do not change."""
        st = State()
        st.create('a', initial=1.0)
        st.create('b', initial=0.0)
        st.create('c', initial=0.0)
        a, b, c = st.a, st.b, st.c

        b @= (lambda: 100 if a.value > 0 else 0)
        c @= (lambda: b * 2)

        self.assertEqual(c.value, 200)

        a.value = 5.0
        self.assertEqual(b.value, 100)
        self.assertEqual(c.value, 200)

    def test_changed_formula_propagates(self):
        st = State()
        st.create('a', initial=1.0)
        st.create('b', initial=0.0)
        st.create('c', initial=0.0)
        a, b, c = st.a, st.b, st.c

        b @= (lambda: a * 10)
        c @= (lambda: b + 1)

        self.assertEqual(c.value, 11)
        a.value = 3.0
        self.assertEqual(b.value, 30)
        self.assertEqual(c.value, 31)

    def test_diamond_recalculates_c_once(self):
        """A→B, A→C, B→C: reading C after changing A must resolve C only once."""
        st = State()
        st.create('a', initial=1.0)
        st.create('b', initial=0.0)
        st.create('c', initial=0.0)
        a, b, c = st.a, st.b, st.c

        b @= (lambda: a + 1)
        c @= (lambda: a + b)

        self.assertEqual(c.value, 3)

        c_count = {'n': 0}
        orig_c = c._resolve_link

        def wrapped():
            c_count['n'] += 1
            return orig_c()

        c._resolve_link = wrapped
        a.value = 10.0
        self.assertEqual(c.value, 21)
        self.assertEqual(c_count['n'], 1, f"C resolved {c_count['n']} times")
        c._resolve_link = orig_c

    def test_deep_midpoint_chain_updates(self):
        """Sierpinski-like depth must not drop updates."""
        from scena.shapes import middle_point

        p1 = Point(0, 0)
        p2 = Point(100, 0)
        chain = [p1]
        for i in range(12):
            nxt = Point()
            prev = chain[-1]

            def make_fn(a=prev, b=p2):
                return (lambda: middle_point(a, b))

            nxt @= make_fn()
            chain.append(nxt)

        tip = chain[-1]
        before = tip.x
        p1.x = 50.0
        self.assertNotEqual(tip.x, before)
        self.assertGreater(tip.x, before)

    def test_keyp_unchanged_x_keeps_sink_correct(self):
        keyp = KeyPressed()
        c5 = Circle(center=(800, 700), radius=10)
        st = State()
        st.create('sink', initial=0.0)
        sink = st.sink

        c5.center["x"] @= (lambda: 1200 if keyp("D") else 800)
        sink @= (lambda: c5.center.x * 2)

        self.assertEqual(sink.value, 1600)

        keyp._press('A')  # not D — x stays 800
        self.assertEqual(sink.value, 1600)


class TestEventPoll(unittest.TestCase):
    def tearDown(self):
        from scena.events import cleanup_global_event_system
        cleanup_global_event_system()

    def test_when_on_bare_ink_polls_without_graph_edge(self):
        from scena.events import when
        from scena.state import get_scena_system
        c = Circle(center=(10, 10), radius=8)
        c.hp = 4
        fired = []

        @when(lambda: c.hp <= 0)
        def death():
            fired.append(1)

        ss = get_scena_system()
        n0 = _settled_nodes(ss)
        c.hp = 0
        self.assertEqual(fired, [1])
        # Event is not a graph node; writing unlinked ink must not grow the graph.
        self.assertEqual(_settled_nodes(ss), n0)
        c.destroy()


class TestPoseRotationNotifyChangeGate(unittest.TestCase):
    """Tier 1.2: unchanged rotation/scale must not break dependents.

    After T1.2, writing the same value may skip property-anchor notify; writing
    a new value (or Derivate SPINE rotation) must still fan out.
    """

    def test_rotate_to_same_then_different(self):
        from scena.shapes import Rect
        from scena.state import Attribute

        r = Rect(center=(0, 0), width=40, height=20, angle=0.0)
        sink = Attribute(0.0)
        sink @= (lambda r=r: r.angle)
        self.assertEqual(float(sink.value), 0.0)
        r.rotate_to(45.0)
        self.assertEqual(float(sink.value), 45.0)
        # Second call with same angle: sink stays correct.
        r.rotate_to(45.0)
        self.assertEqual(float(sink.value), 45.0)
        r.rotate_to(10.0)
        self.assertEqual(float(sink.value), 10.0)
        r.destroy()

    def test_spine_rotation_change_notifies(self):
        from scena.shapes import Rect
        from scena.state import Attribute

        spine = Rect(p1=(0.0, 0.0), p2=(10.0, 0.0), height=4.0, anchor="cap")
        sink = Attribute(0.0)
        sink @= (lambda s=spine: s.angle)
        self.assertEqual(float(sink.value), 0.0)
        spine.p2 = (0.0, 10.0)
        self.assertEqual(float(sink.value), 90.0)
        spine.destroy()

    def test_circle_scale_same_then_different(self):
        from scena.state import Attribute

        c = Circle(center=(0, 0), radius=5)
        sink = Attribute(0.0)
        sink @= (lambda c=c: c.scale)
        c.scale_to(2.0)
        self.assertEqual(float(sink.value), 2.0)
        c.scale_to(2.0)
        self.assertEqual(float(sink.value), 2.0)
        c.scale_to(3.0)
        self.assertEqual(float(sink.value), 3.0)
        c.destroy()


if __name__ == '__main__':
    unittest.main()
