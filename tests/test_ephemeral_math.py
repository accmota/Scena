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


class TestPointTempFastPath(unittest.TestCase):
    """``Point.temp`` (every ``p + v``, ``p - v``, ``v + p``) copies a template
    read off a Point the general constructor built (Shapes Design, "Point
    arithmetic"). The result must be an ordinary Point: the general
    constructor's state, whatever the defaults are, and the same behaviour.
    """

    # Made on first use (``_pose_cell``, ``_subtree_cache``) or per call.
    OWN = {'_pose_cell', '_subtree_cache', '_parts', '_scena_system', '_scenacanvas'}

    @staticmethod
    def _general(fn):
        """Run ``fn`` with the fast path off (it takes finite values only)."""
        from unittest import mock
        import scena.shapes as sh
        with mock.patch.object(sh, '_isfinite', lambda v: False):
            return fn()

    @staticmethod
    def _slots(p):
        out = {}
        for klass in Point.__mro__:
            names = klass.__dict__.get('__slots__', ())
            for name in (names,) if isinstance(names, str) else names:
                if name not in ('__weakref__', '__dict__'):
                    try:
                        out[name] = object.__getattribute__(p, name)
                    except AttributeError:
                        pass
        return out

    def _assert_same_state(self, fast, general):
        fd = {k: v for k, v in fast.__dict__.items() if k not in self.OWN}
        gd = {k: v for k, v in general.__dict__.items() if k not in self.OWN}
        self.assertEqual(list(fd), list(gd), "same keys, same order")
        self.assertEqual(fd, gd)
        fs, gs = self._slots(fast), self._slots(general)
        self.assertEqual(list(fs), list(gs), "the same slots set")
        for name in fs:
            if name not in self.OWN:
                self.assertEqual((name, fs[name]), (name, gs[name]))
        self.assertIs(fast._scena_system, general._scena_system)
        self.assertIs(fast._scenacanvas, general._scenacanvas)
        self.assertEqual(len(fast.__dict__['_parts']), 0)
        self.assertIs(type(fast.__dict__['_parts']), type(general.__dict__['_parts']))

    def _assert_like_general(self, x=3.0, y=4.0):
        self._assert_same_state(Point.temp(x, y), self._general(lambda: Point.temp(x, y)))

    def test_temp_has_the_general_constructors_state(self):
        from scena.state import Attribute
        for x, y in ((3.0, 4.0), (0, 0), (-0.0, 0.0), (1e300, -1e300), (2, 7.5),
                     (Attribute(1.5), Attribute(-2))):
            with self.subTest(x=x, y=y):
                self._assert_like_general(x, y)
                p = Point.temp(x, y)
                self.assertIs(type(p), Point)
                self.assertIs(type(p.__dict__['x']), float)
        a, b = Point.temp(1, 2), Point.temp(1, 2)
        self.assertIsNot(a.__dict__['_parts'], b.__dict__['_parts'])

    def test_the_fast_path_is_taken(self):
        from unittest import mock
        Point.temp(1, 2)                         # the template exists
        with mock.patch.object(Point, '_construct', side_effect=AssertionError("constructor ran")):
            self.assertEqual(tuple(Point.temp(1, 2)), (1.0, 2.0))

    def test_the_template_follows_the_defaults(self):
        import scena
        from scena.style import PaintState
        saved = PaintState._default_instance
        try:
            scena.set_defaults("coral", line_width=4.0, blend="add")
            self._assert_like_general()
            self.assertEqual(Point.temp(1, 2).line_width, 4.0)
            # The prototype written in place (set_defaults() returns it).
            scena.set_defaults().line_width = 7.0
            self._assert_like_general()
            self.assertEqual(Point.temp(1, 2).line_width, 7.0)
            scena.set_defaults().dash = "dash"
            self._assert_like_general()
            scena.set_defaults(fill_filter=None, visual=scena.Neon())
            self._assert_like_general()
            self._assert_same_state(Point.temp(1, 2).look_like(PaintState._default_instance),
                                    self._general(lambda: Point.temp(1, 2)).look_like(
                                        PaintState._default_instance))
        finally:
            PaintState._default_instance = saved
        self._assert_like_general()
        self.assertEqual(Point.temp(1, 2).line_width, saved._line_width)

    def test_the_template_follows_an_installed_prototype(self):
        # An act change puts the saved prototype back by assignment.
        from scena.style import PaintState
        saved = PaintState._default_instance
        try:
            other = PaintState.set_defaults(line_width=9.0)
            self.assertEqual(Point.temp(1, 2).line_width, 9.0)
            PaintState._default_instance = saved
            self.assertEqual(Point.temp(1, 2).line_width, saved._line_width)
            PaintState._default_instance = other
            self.assertEqual(Point.temp(1, 2).line_width, 9.0)
        finally:
            PaintState._default_instance = saved

    def test_each_temp_reads_the_current_canvas_and_system(self):
        from unittest import mock
        from scena.canvas import ScenaCanvas
        import scena.state as state
        Point.temp(1, 2)                         # the template exists
        marker = ScenaCanvas.get_current()
        self.assertIs(Point.temp(1, 2)._scenacanvas, marker)
        self.assertIs(Point.temp(1, 2)._scena_system, state.get_scena_system())
        with mock.patch.object(ScenaCanvas, '_current_canvas', None):
            with self.assertRaises(RuntimeError):
                Point.temp(1, 2)                 # the constructor's own error

    def test_a_temp_is_no_cycle_and_queues_no_pose_cell(self):
        import gc
        import weakref
        from scena.state import DIRTY_POSE_CELLS
        Point.temp(0, 0)
        queued = len(DIRTY_POSE_CELLS)
        gc.disable()
        try:
            p = Point.temp(1, 2)
            ref = weakref.ref(p)
            self.assertEqual(len(DIRTY_POSE_CELLS), queued)
            del p
            self.assertIsNone(ref(), "freed by its last reference, not by the collector")
        finally:
            gc.enable()

    def test_a_write_makes_what_the_first_use_needs(self):
        from scena.state import pose_rev
        fast = Point.temp(1, 2)
        self.assertEqual(pose_rev(fast), 0)
        fast.x = 5
        self.assertEqual(pose_rev(fast), 1)
        self.assertEqual(fast.x, 5.0)
        fast.move_by(1, 1)
        self.assertEqual(tuple(fast), (6.0, 3.0))
        self.assertEqual(fast._subtree_list(), [fast])
        self.assertIs(fast._ownership_root(), fast)

    @staticmethod
    def _behaviour():
        """What every door reads and writes on a result; compared whole."""
        import copy
        from scena.state import State
        src = Point(10, 20)
        out = {}
        p = src + (1, 2)
        out["add"] = tuple(p)
        out["radd"] = tuple((1, 2) + src)
        out["sub"] = tuple(src - Vec2(1, 2))
        out["vec_add"] = tuple(Vec2(1, 2) + src)
        out["between"] = tuple(src - p)
        out["free"] = (p.owner, p._node_id, p.layer, p.visible, p.draggable, p.group)
        out["copy"] = tuple(copy.copy(p))
        p.move_by(1, 1)
        p.move_to(4, 5)
        p.x += 1
        out["moved"] = tuple(p)
        # A source of a link and a formula.
        q = Point(0, 0)
        q @= (lambda: src + (5, 5))
        out["formula"] = tuple(q)
        src.x = 100
        out["formula after"] = tuple(q)
        r = Point(0, 0)
        held = src + (1, 1)
        r @= held
        held.x = 7
        out["link"] = tuple(r)
        # A linked cell's output refuses a write; a free one takes it.
        st = State()
        st.create("pos", initial=Point.temp(0, 0))
        st["pos"] @= (lambda: src + (1, 1))
        try:
            st.pos.x = 3
            out["cell write"] = "took it"
        except Exception as exc:
            out["cell write"] = type(exc).__name__
        out["cell"] = tuple(st.pos)
        # Shown: a real marker on a layer, hidden again, then destroyed.
        m = src + (2, 2)
        m.visible = True
        out["shown"] = (m.visible, m.layer, m.fill, m.line, m.line_width)
        m.visible = False
        out["hidden"] = (m.visible, m.layer)
        m.color = "red"
        out["painted"] = (str(m.fill), m.line)
        m.tag("marks")
        out["tagged"] = sorted(m.group)
        t = src + (0, 0)
        t.destroy()
        out["destroyed"] = t._destroyed
        return out

    def test_a_result_behaves_like_before(self):
        self.assertEqual(self._behaviour(), self._general(self._behaviour))

    def test_general_path_rules_unchanged(self):
        with self.assertRaises((ValueError, TypeError)):
            Point.temp(float('nan'), 0)
        with self.assertRaises((ValueError, TypeError)):
            Point.temp(0, float('inf'))
        with self.assertRaises((ValueError, TypeError)):
            Point.temp("a", 0)
        with self.assertRaises(OverflowError):
            Point.temp(10 ** 400, 0)

    def test_a_subclass_keeps_its_constructor(self):
        built = []

        class Mark(Point):
            def setup(self):
                built.append(self)

        m = Mark.temp(1, 2)
        self.assertIs(type(m), Mark)
        self.assertEqual(built, [m])
        self.assertEqual(tuple(m), (1.0, 2.0))
        self.assertTrue(m._ephemeral)


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
