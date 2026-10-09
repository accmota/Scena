"""
Dependency-graph lifecycle: create, link, unlink, relink, remove, leaks.

Run headless:

    python -m unittest tests.test_graph_lifecycle -v
"""

import os
import sys
import gc
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Line, Point, Circle, Rect
from scena.state import (
    get_scena_system,
    DependencyState,
    FieldType,
    LinkedAttributeError,
    State,
    Attribute,
)

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _graph():
    return get_scena_system().dependency_graph


def _stable_node_count(g=None):
    """``len(nodes)`` after flushing pending weakref callbacks / cyclic GC.

    With the GC graph backstop, ``WeakValueDictionary`` may briefly retain
    dead entries until finalizers run; snapshots used as baselines must
    collect first or absolute counts race with reclamation.
    """
    gc.collect()
    return len((g or _graph()).nodes)


def _edge_count(g=None):
    g = g or _graph()
    return sum(len(deps) for deps in g.dependencies.values())


def _depends_on(dependent, dependency) -> bool:
    g = _graph()
    if dependent is None or dependency is None:
        return False
    dep_id = getattr(dependent, '_node_id', None)
    src_id = getattr(dependency, '_node_id', None)
    if dep_id is None or src_id is None:
        return False
    return src_id in g.dependencies.get(dep_id, set())


def _anchor(container, name):
    """ScalarAnchor graph node for a linked bare field, or None."""
    anchors = container.__dict__.get('_field_anchors') or {}
    return anchors.get(name)


def _subtree_ids(container):
    return [n._node_id for n in container._iter_subtree() if n._node_id is not None]


class TestCreateStructuralEdges(unittest.TestCase):
    def test_line_defining_and_derivate_directions(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        # Defining: line depends on p1 (downward)
        self.assertTrue(_depends_on(line, line.p1))
        self.assertFalse(_depends_on(line.p1, line))
        # Derivate: center depends on line (upward)
        self.assertTrue(_depends_on(line.center, line))
        self.assertFalse(_depends_on(line, line.center))
        self.assertEqual(line.center.field_type, FieldType.Derivate)


class TestLinkUnlinkRelink(unittest.TestCase):
    def test_formula_edge_added_and_removed(self):
        g = _graph()
        line = Line(p1=(0, 0), p2=(10, 10))
        circle = Circle(center=(5, 5), radius=3)
        e_before = _edge_count(g)

        line.p1["x"] @= lambda: circle.center.y
        self.assertTrue(_depends_on(_anchor(line.p1, 'x'), circle.center))
        self.assertEqual(line.p1.x, circle.center.y)

        circle.center.y = 42
        self.assertEqual(line.p1.x, 42)

        line.p1["x"].unlink()
        self.assertIsNone(_anchor(line.p1, 'x'))
        self.assertFalse(_depends_on(_anchor(line.p1, 'x'), circle.center))
        self.assertEqual(_edge_count(g), e_before)

        circle.center.y = 7
        self.assertEqual(line.p1.x, 42)  # frozen after unlink

    def test_lambda_formula_propagates_and_unlinks(self):
        src = Point(10, 20)
        dst = Point(0, 0)
        dst["x"] @= (lambda: src.x * 2)
        self.assertEqual(dst.x, 20)
        self.assertTrue(_depends_on(_anchor(dst, 'x'), src))
        src.x = 15
        self.assertEqual(dst.x, 30)

        dst["x"].unlink()
        self.assertFalse(_depends_on(_anchor(dst, 'x'), src))
        src.x = 100
        self.assertEqual(dst.x, 30)

    def test_relink_swaps_formula_edge(self):
        a, b, c = Point(1, 0), Point(2, 0), Point(3, 0)
        a["x"] @= lambda: b.x
        self.assertTrue(_depends_on(_anchor(a, 'x'), b))
        self.assertEqual(a.x, 2)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            a["x"] @= lambda: c.x
            self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w))

        self.assertTrue(_depends_on(_anchor(a, 'x'), c))
        self.assertFalse(_depends_on(_anchor(a, 'x'), b))
        self.assertEqual(a.x, 3)

        b.x = 99
        self.assertNotEqual(a.x, 99)
        c.x = 77
        self.assertEqual(a.x, 77)

    def test_assign_value_clears_link_and_edge(self):
        a, b = Point(1, 0), Point(2, 0)
        a["x"] @= lambda: b.x
        with self.assertRaises(LinkedAttributeError):
            a.x = 5
        a["x"].unlink()
        a.x = 5
        self.assertIsNone(_anchor(a, 'x'))
        self.assertFalse(_depends_on(_anchor(a, 'x'), b))
        self.assertEqual(a.x, 5)
        b.x = 50
        self.assertEqual(a.x, 5)

    def test_double_unlink_is_safe(self):
        a, b = Point(1, 0), Point(2, 0)
        a["x"] @= lambda: b.x
        a["x"].unlink()
        a["x"].unlink()
        self.assertIsNone(_anchor(a, 'x'))

    def test_whole_line_direct_link_rewires_then_restores(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        src = Line(p1=(100, 0), p2=(200, 0))

        self.assertTrue(_depends_on(line, line.p1))
        self.assertTrue(_depends_on(line.center, line))

        line @= src
        self.assertEqual(line._dependency_state, DependencyState.LINKED_OUTWARD)
        self.assertTrue(_depends_on(line.p1, line))
        self.assertFalse(_depends_on(line, line.p1))
        self.assertTrue(_depends_on(line, src))
        self.assertTrue(_depends_on(line.center, line))

        line.unlink()
        self.assertEqual(line._dependency_state, DependencyState.DEPENDENT_DOWNWARD)
        self.assertTrue(_depends_on(line, line.p1))
        self.assertFalse(_depends_on(line.p1, line))
        self.assertTrue(_depends_on(line.center, line))
        self.assertFalse(_depends_on(line, src))
        self.assertEqual(line.center.field_type, FieldType.Derivate)


class TestNestedLinkState(unittest.TestCase):
    def test_parent_link_forbidden_when_leaf_linked(self):
        src = Point(50, 60)
        line = Line(p1=(0, 0), p2=(10, 0))
        other = Line(p1=(100, 0), p2=(200, 0))

        line.p1["x"] @= lambda: src.x
        with self.assertRaises(LinkedAttributeError):
            line @= other

    def test_leaf_link_forbidden_when_parent_linked(self):
        src = Point(50, 60)
        line = Line(p1=(0, 0), p2=(10, 0))
        other = Line(p1=(100, 0), p2=(200, 0))

        line @= other
        with self.assertRaises(LinkedAttributeError):
            line.p1["x"] @= lambda: src.x

    def test_unlink_all_allows_parent_link(self):
        src = Point(50, 60)
        line = Line(p1=(0, 0), p2=(10, 0))
        other = Line(p1=(100, 0), p2=(200, 0))

        line.p1["x"] @= lambda: src.x
        line.p2["y"] @= lambda: src.y
        line.unlink_all()
        self.assertIsNone(_anchor(line.p1, 'x'))
        self.assertIsNone(_anchor(line.p2, 'y'))
        line @= other
        self.assertIsNotNone(line._link)
        self.assertEqual(line.p1.x, 100)


class TestObjectRemoval(unittest.TestCase):
    def test_destroy_removes_subtree_from_graph(self):
        g = _graph()
        n0 = _stable_node_count(g)

        circle = Circle(center=(1, 1), radius=2)
        p = Point(9, 9)
        circle.center["x"] @= lambda: p.x
        ids = _subtree_ids(circle)
        self.assertTrue(ids)
        self.assertTrue(_depends_on(_anchor(circle.center, 'x'), p))

        circle.destroy()

        for nid in ids:
            self.assertNotIn(nid, g.nodes)
        self.assertIsNone(circle._node_id)
        self.assertIsNone(_anchor(circle.center, 'x'))
        self.assertFalse(_depends_on(_anchor(circle.center, 'x'), p))

        # Point source remains registered; unlinked Point has no x/y graph nodes
        self.assertIn(p._node_id, g.nodes)
        self.assertEqual(len(_subtree_ids(p)), 1)
        self.assertEqual(_stable_node_count(g), n0 + 1)

    def test_destroy_unlinks_external_dependents(self):
        src = Circle(center=(0, 0), radius=1)
        sink = Point(0, 0)
        sink["x"] @= lambda: src.center.x
        self.assertEqual(sink.x, 0)
        self.assertTrue(_depends_on(_anchor(sink, 'x'), src.center))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            src.destroy()
            self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w))

        self.assertIsNone(_anchor(sink, 'x'))
        self.assertFalse(_depends_on(_anchor(sink, 'x'), src.center))
        # Sink Point remains in the graph
        self.assertIn(sink._node_id, _graph().nodes)
        self.assertEqual(sink.x, 0)  # last value retained

    def test_many_create_destroy_no_leak(self):
        g = _graph()
        n0 = _stable_node_count(g)
        e0 = _edge_count(g)

        for i in range(15):
            c = Circle(center=(i, i), radius=5)
            p = Point(i * 10, i * 10)
            c.center["x"] @= lambda: p.x
            c.destroy()
            p.destroy()

        self.assertEqual(_stable_node_count(g), n0)
        self.assertEqual(_edge_count(g), e0)

    def test_clear_owner_removes_structural_edge_keeps_node(self):
        parent = Point(1, 1)
        child = Point(2, 2, owner=parent)
        self.assertTrue(_depends_on(parent, child) or _depends_on(child, parent))
        child_id = child._node_id
        child._clear_owner()
        self.assertFalse(_depends_on(parent, child))
        self.assertFalse(_depends_on(child, parent))
        self.assertIn(child_id, _graph().nodes)
        self.assertIsNone(child.owner)

    def test_clean_up_idempotent(self):
        p = Point(3, 4)
        p._clean_up()
        p._clean_up()
        self.assertIsNone(p._node_id)

    def test_destroy_unlinks_line_linked_to_derived_point(self):
        """Line(p1=lambda: rect.right_center) links p1 at Point level; destroy freezes it."""
        rect = Rect(top_left=(0, 0), width=100, height=50)
        line = Line(p1=lambda: rect.right_center, p2=(200, 25))
        self.assertIsNotNone(line.p1._link)
        self.assertTrue(_depends_on(line.p1, rect.right_center))
        frozen_x = line.p1.x
        frozen_y = line.p1.y

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            rect.destroy()
            self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w))

        self.assertIsNone(line.p1._link)
        self.assertFalse(_depends_on(line.p1, rect.right_center))
        self.assertEqual(line.p1.x, frozen_x)
        self.assertEqual(line.p1.y, frozen_y)
        self.assertIn(line._node_id, _graph().nodes)
        self.assertIsNone(rect._node_id)

    def test_destroy_unlinks_multi_source_formula_fully(self):
        """Removing one formula source clears the whole multi-source link."""
        a = Point(10, 0)
        b = Point(20, 0)
        sink = Attribute(0, attr_name="sink")
        sink @= (lambda: a.x + b.x)
        self.assertEqual(sink.value, 30)
        self.assertTrue(_depends_on(sink, a))
        self.assertTrue(_depends_on(sink, b))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            a.destroy()
            self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w))

        self.assertIsNone(sink._link)
        self.assertEqual(sink.value, 30)  # last value retained
        self.assertFalse(_depends_on(sink, a))
        self.assertFalse(_depends_on(sink, b))
        b.x = 99
        self.assertEqual(sink.value, 30)  # no longer tracking remaining source

    def test_undraw_keeps_links_alive(self):
        """Soft removal: stop drawing but keep reactive identity and formulas."""
        src = Circle(center=(5, 5), radius=1)
        sink = Point(0, 0)
        sink["x"] @= lambda: src.center.x
        src.undraw()

        self.assertTrue(sink["x"].is_linked)
        self.assertIn(src._node_id, _graph().nodes)
        src.center.x = 42
        self.assertEqual(sink.x, 42)


class TestStateLifecycle(unittest.TestCase):
    def test_create_get_exists_keys(self):
        st = State()
        st.create("a", initial=7)
        self.assertTrue(st.exists("a"))
        self.assertEqual(st.a.value, 7)
        self.assertIn("a", st.keys())
        self.assertFalse(st.exists("missing"))

    def test_dot_assignment_creates_attribute(self):
        st = State()
        st.x = 3
        self.assertTrue(st.exists("x"))
        self.assertIsInstance(st.x, Attribute)
        st.x = 9
        self.assertEqual(st.x, 9)

    def test_remove_tears_down_and_drops_key(self):
        g = _graph()
        st = State()
        st.create("v", initial=1)
        attr = st.v
        # Lazy registration: unlinked State cells stay off-graph until used.
        self.assertIsNone(attr._node_id)
        self.assertNotIn(id(attr), g.nodes)

        # Linking promotes the cell into the graph.
        sink = Attribute(0, attr_name="sink_v")
        sink @= attr
        self.assertIsNotNone(attr._node_id)
        attr_id = attr._node_id
        self.assertIn(attr_id, g.nodes)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            st.remove("v")
        self.assertFalse(st.exists("v"))
        self.assertIsNone(attr._node_id)
        self.assertNotIn(attr_id, g.nodes)
        with self.assertRaises(AttributeError):
            _ = st.v
        sink._clean_up()

    def test_remove_missing_raises(self):
        st = State()
        with self.assertRaises(KeyError):
            st.remove("nope")

    def test_remove_unlinks_external_dependents(self):
        st = State()
        st.create("src", initial=10)
        sink = Attribute(0, attr_name="sink")
        sink @= st.src
        self.assertEqual(sink.value, 10)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            st.remove("src")
            self.assertTrue(any(issubclass(x.category, RuntimeWarning) for x in w))

        self.assertIsNone(sink._link)
        self.assertEqual(sink.value, 10)
        self.assertFalse(st.exists("src"))

    def test_state_formula_propagates_until_remove(self):
        st = State()
        st.create("a", initial=2)
        st.create("b", initial=0)
        a, b = st.a, st.b
        b @= (lambda: a * 5)
        self.assertEqual(b.value, 10)
        a.value = 4
        self.assertEqual(b.value, 20)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            st.remove("a")
        self.assertIsNone(b._link)
        self.assertEqual(b.value, 20)


class TestDerivedExternalFormula(unittest.TestCase):
    def test_formula_on_derived_attr_updates_after_move(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        observer = Point(-1, 0)
        observer["x"] @= lambda: ln.center.x
        self.assertEqual(observer.x, 5)
        ln.p1.x = 0
        ln.p2.x = 20
        self.assertEqual(observer.x, ln.center.x)

    def test_unlink_derived_observer_stops_tracking(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        observer = Point(-1, 0)
        observer["x"] @= lambda: ln.center.x
        observer["x"].unlink()
        ln.p2.x = 100
        self.assertEqual(observer.x, 5)


class TestUnlinkedNodeCount(unittest.TestCase):
    def test_unlinked_circles_are_not_per_field(self):
        """Unlinked scalar fields have no graph nodes (Phase 9 perf guard)."""
        g = _graph()
        n0 = _stable_node_count(g)
        n = 24
        circles = [Circle(center=(i * 8, 40), radius=6) for i in range(n)]
        grown = len(g.nodes) - n0
        # Circle + center Point each; radius/x/y are bare scalars.
        self.assertLessEqual(
            grown, 3 * n,
            f"unlinked scene grew by {grown} nodes for {n} circles "
            f"(expected O(shapes), not O(fields × shapes))",
        )
        self.assertGreaterEqual(grown, n)
        for c in circles:
            c.destroy()
        self.assertEqual(_stable_node_count(g), n0)


class TestSubtreeCacheInvalidation(unittest.TestCase):
    """Tier 1.3: ``_iter_subtree`` must stay correct across part-graph mutations.

    Whether or not a flattened-subtree cache is present, materializing a
    Derivate, linking, unlinking, and destroy must never leave a stale walk.
    """

    def test_materialize_derivate_appears_in_subtree(self):
        rect = Rect(center=(0, 0), width=40, height=20)
        before = set(_subtree_ids(rect))
        self.assertNotIn("left_square_center", rect.__dict__)
        _ = rect.left_square_center
        after = set(_subtree_ids(rect))
        self.assertIn(rect.left_square_center._node_id, after)
        self.assertTrue(after > before)
        rect.destroy()

    def test_add_parts_and_remove_parts_update_walk(self):
        parent = Point(1, 1)
        child = Point(2, 2)
        self.assertNotIn(child._node_id, _subtree_ids(parent))
        child.owner = parent
        self.assertIn(child._node_id, set(_subtree_ids(parent)))
        child._clear_owner()
        self.assertNotIn(child._node_id, set(_subtree_ids(parent)))
        parent.destroy()
        child.destroy()

    def test_unlink_all_then_parent_link_subtree_intact(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        src = Point(50, 60)
        other = Line(p1=(100, 0), p2=(200, 0))
        line.p1["x"] @= (lambda: src.x)
        # ScalarAnchor for p1.x exists while linked; unlink_all drops it.
        self.assertIsNotNone(_anchor(line.p1, "x"))
        line.unlink_all()
        self.assertIsNone(_anchor(line.p1, "x"))
        # Ownership parts (p1/p2/…) remain walkable after unlink_all + parent link.
        line @= other
        ids = set(_subtree_ids(line))
        self.assertIn(line._node_id, ids)
        self.assertIn(line.p1._node_id, ids)
        self.assertIn(line.p2._node_id, ids)
        self.assertEqual(line.p1.x, 100)
        line.destroy()
        other.destroy()
        src.destroy()

    def test_destroy_clears_every_subtree_id(self):
        rect = Rect(center=(3, 4), width=12, height=8)
        _ = rect.top_left
        _ = rect.right_square_center
        ids = _subtree_ids(rect)
        self.assertTrue(ids)
        g = _graph()
        rect.destroy()
        for nid in ids:
            self.assertNotIn(nid, g.nodes)


class TestLazyContainerRegistration(unittest.TestCase):
    """Bare Containers stay off-graph until owned or linked (leak fix)."""

    def test_bare_vec2_not_registered_until_used(self):
        from scena.scenamath import Vec2
        g = _graph()
        n0 = _stable_node_count(g)
        v = Vec2(1.0, 2.0)
        self.assertIsNone(v._node_id)
        self.assertEqual(len(g.nodes), n0)
        self.assertEqual(v.x, 1.0)
        self.assertEqual(v.y, 2.0)

    def test_bare_point_not_registered_until_used(self):
        g = _graph()
        n0 = _stable_node_count(g)
        p = Point(3.0, 4.0)
        # Free Point is an Entity (_graph_citizen) — always registered.
        self.assertIsNotNone(p._node_id)
        self.assertIn(p._node_id, g.nodes)
        p.destroy()
        self.assertEqual(_stable_node_count(g), n0)

    def test_vec2_registers_when_owned(self):
        from scena.scenamath import Vec2
        parent = Point(0, 0)
        v = Vec2(1, 2, owner=parent, attr_name="v")
        self.assertIsNotNone(v._node_id)
        self.assertIn(v._node_id, _graph().nodes)
        self.assertTrue(_depends_on(parent, v) or _depends_on(v, parent))
        parent.destroy()

    def test_vec2_registers_when_linked_as_target(self):
        from scena.scenamath import Vec2
        src = Point(10, 0)
        v = Vec2(0, 0)
        self.assertIsNone(v._node_id)
        v["x"] @= (lambda: src.x)
        self.assertIsNotNone(v._node_id)
        self.assertIn(v._node_id, _graph().nodes)
        self.assertEqual(v.x, 10)
        v["x"].unlink()
        v._clean_up()
        src.destroy()

    def test_vec2_registers_when_used_as_link_source(self):
        from scena.scenamath import Vec2
        v = Vec2(7, 0)
        other = Point(0, 0)
        self.assertIsNone(v._node_id)
        other["x"] @= (lambda: v.x)
        self.assertIsNotNone(v._node_id)
        self.assertEqual(other.x, 7)
        other["x"].unlink()
        other.destroy()
        v._clean_up()

    def test_repeated_reassignment_of_bare_container_attribute_does_not_grow_graph(self):
        from scena.scenamath import Vec2
        g = _graph()
        n0 = _stable_node_count(g)

        class Holder:
            pass

        holder = Holder()
        for i in range(200):
            holder.attr = Vec2(float(i), float(i))
        # Orphans are not registered (lazy) — graph stays flat; GC can collect.
        self.assertEqual(len(g.nodes), n0)
        holder.attr = None

        n1 = _stable_node_count(g)
        for i in range(50):
            holder.pt = Point(float(i), float(i))
            holder.pt.destroy()
        self.assertEqual(_stable_node_count(g), n1)

    def test_graphic_vel_setter_mutates_in_place_no_leak(self):
        from scena.scenamath import Vec2
        g = _graph()
        c = Circle(center=(0, 0), radius=5)
        n0 = _stable_node_count(g)
        c.vel = Vec2(1, 2)
        n1 = len(g.nodes)
        self.assertGreaterEqual(n1, n0)  # first assign may add owned vel Vec2
        vel_id = id(c.vel)
        for i in range(100):
            c.vel = Vec2(float(i), float(-i))
        self.assertEqual(id(c.vel), vel_id)
        self.assertEqual(len(g.nodes), n1)
        self.assertEqual(c.vel.x, 99.0)
        c.destroy()

    def test_bare_container_reads_correctly_without_node_id(self):
        from scena.scenamath import Vec2
        v = Vec2(0, 0)
        self.assertIsNone(v._node_id)
        v.x = 3.5
        v.y = -1.25
        self.assertEqual(v.x, 3.5)
        self.assertEqual(v.y, -1.25)
        v._clean_up()

    def test_clean_up_safe_on_never_registered_container(self):
        from scena.scenamath import Vec2
        v = Vec2(1, 1)
        self.assertIsNone(v._node_id)
        v._clean_up()
        v._clean_up()
        self.assertIsNone(v._node_id)

    def test_circular_reference_detected_when_both_sides_start_unregistered(self):
        from scena.scenamath import Vec2
        from scena.state import CircularReferenceError
        a = Vec2(1, 0)
        b = Vec2(2, 0)
        self.assertIsNone(a._node_id)
        self.assertIsNone(b._node_id)
        a["x"] @= (lambda: b.x)
        with self.assertRaises(CircularReferenceError):
            b["x"] @= (lambda: a.x)
        a["x"].unlink()
        a._clean_up()
        b._clean_up()


if __name__ == "__main__":
    unittest.main(verbosity=2)
