"""
GC-backed DependencyGraph eviction (proposal: General Fix for Container Graph Leaks).

Run headless:

    python -m unittest tests.test_graph_gc_backstop -v
"""

from __future__ import annotations

import gc
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Point, Rect
from scena.state import (
    DependencyGraph,
    get_scena_system,
    init_scena_system,
    set_graph_gc_backstop,
    graph_gc_backstop_enabled,
)
from scena.scenamath import Vec2
from tests.graph_support import settled_graph_size  # noqa: E402


def _graph():
    return get_scena_system().dependency_graph


def _enable_backstop():
    set_graph_gc_backstop(True)
    init_scena_system()


def _disable_backstop():
    set_graph_gc_backstop(False)
    init_scena_system()


class _BackstopTestCase(unittest.TestCase):
    def setUp(self):
        self._prev = graph_gc_backstop_enabled()
        _enable_backstop()

    def tearDown(self):
        set_graph_gc_backstop(self._prev)
        init_scena_system()


class TestFreestandingLeak(_BackstopTestCase):
    """§6: sink @= Vec2; unlink; drop source → gone from nodes/edges."""

    def test_linked_then_unlinked_vec2_evicted_without_destroy(self):
        g = _graph()
        sink = Point(0, 0)
        src = Vec2(1.0, 2.0)
        sink["x"] @= (lambda: src.x)
        self.assertIsNotNone(src._node_id)
        nid = src._node_id
        self.assertIn(nid, g.nodes)

        sink["x"].unlink()
        del src
        gc.collect()

        self.assertNotIn(nid, g.nodes)
        self.assertNotIn(nid, g.dependencies)
        for deps in g.dependents.values():
            self.assertNotIn(nid, deps)
        for deps in g.dependencies.values():
            self.assertNotIn(nid, deps)

        sink.destroy()


class TestOwnedSubtreeDropped(_BackstopTestCase):
    """§6: Rect + touched parts dropped without destroy → all ids purged."""

    def test_rect_subtree_evicted_via_one_finalizer_per_node_step1(self):
        g = _graph()
        rect = Rect(p1=(0, 0), p2=(40, 20))
        # Touch several Derivate / Defining slots so they register.
        for name in ("top_left", "top_right", "center", "vec", "p1", "p2"):
            getattr(rect, name)
        ids = {
            n._node_id
            for n in rect._iter_subtree()
            if getattr(n, "_node_id", None) is not None
        }
        self.assertGreater(len(ids), 3)
        for nid in ids:
            self.assertIn(nid, g.nodes)

        # Scene layer holds a strong ref; undraw drops it without destroy/clean_up.
        rect.undraw()
        del rect
        gc.collect()

        for nid in ids:
            self.assertNotIn(nid, g.nodes)
            self.assertNotIn(nid, g.dependencies)
            self.assertNotIn(nid, g.dependents)


class TestReparentStandalone(_BackstopTestCase):
    """§6: freestanding registered Vec2 later gets an owner (step-1: per-node)."""

    def test_reparent_keeps_id_reachable_until_tree_drops(self):
        g = _graph()
        parent = Point(0, 0)
        free = Vec2(3.0, 4.0)
        # Force registration via a link, then unlink — free stays registered.
        parent["x"] @= (lambda: free.x)
        parent["x"].unlink()
        self.assertIsNotNone(free._node_id)
        nid = free._node_id
        fin = free.__dict__.get("_graph_finalizer")
        self.assertIsNotNone(fin)
        self.assertTrue(fin.alive)

        free.owner = parent
        # Step 1: per-node finalizer stays on the child; ownership does not
        # coalesce yet (§4 gated). Id must remain in the graph while live.
        self.assertIn(nid, g.nodes)
        self.assertIs(g.nodes.get(nid), free)

        del free
        del parent
        gc.collect()
        self.assertNotIn(nid, g.nodes)


class TestCleanUpThenDrop(_BackstopTestCase):
    """§6: explicit clean_up detaches finalizer; late GC is a no-op."""

    def test_cleanup_detaches_finalizer_no_double_purge_error(self):
        g = _graph()
        v = Vec2(1.0, 2.0)
        sink = Point(0, 0)
        sink["x"] @= (lambda: v.x)
        nid = v._node_id
        fin = v.__dict__["_graph_finalizer"]
        self.assertTrue(fin.alive)

        sink["x"].unlink()
        v._clean_up()
        self.assertFalse(fin.alive)
        self.assertNotIn(nid, g.nodes)

        # Simulate a stale finalize call on already-cleaned ids.
        g._purge_ids({nid})
        g._purge_ids({nid})
        self.assertNotIn(nid, g.nodes)

        sink.destroy()


class TestTopoSortResilience(_BackstopTestCase):
    """§6: drop subtree + gc between drop and topo/mark_dirty."""

    def test_dangling_ids_do_not_false_positive_cycle(self):
        g = _graph()
        a = Point(0, 0)
        b = Vec2(1.0, 0.0)
        a["x"] @= (lambda: b.x)
        dead_id = 9_001_001
        # Inject a stale edge id that is not in nodes.
        g.dependencies[a._node_id].add(dead_id)
        g.dependents[dead_id].add(a._node_id)

        # Must not raise CircularDependencyError from the phantom edge.
        order = g.topological_sort()
        self.assertIn(a._node_id, order)

        a["x"].unlink()
        del b
        gc.collect()
        # mark_dirty / topo after a live drop
        g.needs_topological_sort = True
        order2 = g.get_update_order()
        self.assertIn(a._node_id, order2)
        a.destroy()

    def test_iteration_survives_collect_during_sort_setup(self):
        g = _graph()
        keep = Point(0, 0)
        temps = [Vec2(float(i), 0.0) for i in range(20)]
        for t in temps:
            keep["x"] @= (lambda s=t: s.x)
            keep["x"].unlink()
        del temps
        gc.collect()
        # Public iteration protocol must not raise RuntimeError.
        _ = list(g.nodes)
        g.needs_topological_sort = True
        _ = g.topological_sort()
        keep.destroy()


class TestPurgeIdempotency(_BackstopTestCase):
    def test_purge_twice_no_exception(self):
        g = DependencyGraph()
        g._purge_ids({1, 2, 3})
        g._purge_ids({1, 2, 3})
        g._purge_ids(set())


class TestGeneralFixWithoutSitePatch(_BackstopTestCase):
    """§6: reassignment churn that registers (link) stays flat under GC."""

    def test_relink_fresh_vec2_each_tick_graph_stays_flat(self):
        g = _graph()
        sink = Point(0, 0)
        n0 = settled_graph_size()

        class Holder:
            pass

        holder = Holder()
        for i in range(80):
            holder.vel = Vec2(float(i), float(-i))
            # Force the (a)/(b) registration path: link then move on.
            sink["x"] @= (lambda: holder.vel.x)
            sink["x"].unlink()
            holder.vel = None
            gc.collect()

        # Allow a small constant for sink + anchors; must not grow with i.
        self.assertLessEqual(len(g.nodes), n0 + 8)
        sink.destroy()
        gc.collect()
        self.assertLessEqual(len(g.nodes), n0 + 2)


class TestNoAuthorApiChange(_BackstopTestCase):
    """§6: existing @= / ownership / clean_up semantics unchanged."""

    def test_formula_still_propagates(self):
        src = Point(10, 20)
        dst = Point(0, 0)
        dst["x"] @= (lambda: src.x * 2)
        self.assertEqual(dst.x, 20)
        src.x = 15
        self.assertEqual(dst.x, 30)
        dst["x"].unlink()
        src.destroy()
        dst.destroy()


class TestFlagOffKeepsStrongRefs(unittest.TestCase):
    """With backstop off, linked-then-dropped sources still pin the graph."""

    def setUp(self):
        self._prev = graph_gc_backstop_enabled()
        _disable_backstop()

    def tearDown(self):
        set_graph_gc_backstop(self._prev)
        init_scena_system()

    def test_orphan_survives_without_backstop(self):
        g = _graph()
        sink = Point(0, 0)
        src = Vec2(1.0, 2.0)
        sink["x"] @= (lambda: src.x)
        nid = src._node_id
        sink["x"].unlink()
        del src
        gc.collect()
        # Strong dict still holds the orphan — the residual leak class.
        self.assertIn(nid, g.nodes)
        # Explicit teardown still works.
        orphan = g.nodes[nid]
        orphan._clean_up()
        sink.destroy()


if __name__ == "__main__":
    unittest.main()
