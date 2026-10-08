"""A pull (reading a linked value) stores the result; it never invalidates.

Regression for 2026-09-28 (found by the ``graph-1`` bench pulse: sierpinski
7.07 -> 14.64 ms). The ``takein`` -> ``_takein`` / ``_takein`` ->
``_takein_impl`` rename left ``Container._resolve_link`` and the container
branch of ``DirectLink.evaluate_and_update`` calling ``_takein`` -- which now
names the *dispatcher* (``Point._takein`` -> ``update()`` / nested
``mark_dirty``), not the raw store. Every read of a linked Point re-walked its
whole dependent cone: O(cone) per pull, ~2x draw on deep ``@=`` trees.

Values stayed correct (a redundant dirty walk is only slower), so no geometry
test noticed; ``TestDeepBinaryTree`` had its ceilings raised to fit it.

Bug class: a pull path reaching an invalidating write. Caught here by counting
``mark_dirty`` during reads (behaviour) and by an AST guard on the resolvers.
Reactive Design: "Pull stores raw".

    python -m unittest tests.test_pull_no_invalidate -v
"""
from __future__ import annotations

import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.source_support import iter_files  # noqa: E402

from scena.events import cleanup_global_event_system  # noqa: E402
from scena.shapes import Line, Point, Rect, middle_point  # noqa: E402
from scena.state import State, get_scena_system  # noqa: E402


def _mark_dirty_calls(fn) -> int:
    um = get_scena_system().update_manager
    orig = um.mark_dirty
    n = 0

    def wrapped(node):
        nonlocal n
        n += 1
        return orig(node)

    um.mark_dirty = wrapped  # type: ignore[method-assign]
    try:
        fn()
    finally:
        um.mark_dirty = orig  # type: ignore[method-assign]
    return n


def _midpoint_tree(p1, p2, p3, depth, points, lines):
    """Sierpinski: deep ``@=`` midpoint links, Lines with lambda endpoints."""
    if depth == 0:
        for a, b in ((p1, p2), (p2, p3), (p3, p1)):
            lines.append(Line(p1=lambda a=a: a, p2=lambda b=b: b))
        return
    m12, m23, m31 = Point(), Point(), Point()
    m12 @= lambda: middle_point(p1, p2)
    m23 @= lambda: middle_point(p2, p3)
    m31 @= lambda: middle_point(p3, p1)
    points.extend((m12, m23, m31))
    _midpoint_tree(p1, m12, m31, depth - 1, points, lines)
    _midpoint_tree(m12, p2, m23, depth - 1, points, lines)
    _midpoint_tree(m31, m23, p3, depth - 1, points, lines)


def _read_all(points, lines):
    for p in points:
        _ = p.x, p.y
    for ln in lines:
        _ = ln.p1.x, ln.p1.y, ln.p2.x, ln.p2.y


class PullCase(unittest.TestCase):
    def setUp(self):
        self._owned = []

    def tearDown(self):
        for obj in reversed(self._owned):
            # State has no destroy(); only tear down Entities.
            if callable(getattr(type(obj), "destroy", None)) and getattr(obj, "is_alive", True):
                obj.destroy()
        cleanup_global_event_system()

    def own(self, *objs):
        self._owned.extend(objs)
        return objs[0] if len(objs) == 1 else objs


class TestMidpointTreePull(PullCase):
    def _build(self, depth=3):
        st = self.own(State(name="drv"))
        st.x = 500.0
        p1 = Point(x=500.0, y=100.0)
        p1["x"] @= st.x
        p2 = Point(x=300.0, y=500.0)
        p3 = Point(x=700.0, y=500.0)
        points, lines = [p1, p2, p3], []
        _midpoint_tree(p1, p2, p3, depth, points, lines)
        self.own(*points, *lines)
        return st, points, lines

    def test_reads_after_a_write_do_not_mark_dirty(self):
        st, points, lines = self._build()
        _read_all(points, lines)  # settle
        st.x = 520.0  # the write walks the cone once
        self.assertEqual(_mark_dirty_calls(lambda: _read_all(points, lines)), 0)

    def test_frame_invalidates_once_per_write(self):
        st, points, lines = self._build()
        _read_all(points, lines)

        def frame():
            st.x = float(st.x) + 3.0
            _read_all(points, lines)

        # One source write -> one walk (pre-rename budget). The regression did
        # one walk per pulled midpoint + endpoint (hundreds at depth 3).
        self.assertLessEqual(_mark_dirty_calls(frame), 2)

    def test_values_track_every_write(self):
        st, points, lines = self._build(depth=2)
        p1, p2, p3 = points[:3]
        m12 = points[3]
        for x in (500.0, 520.0, 480.0, 480.0, 610.0):
            st.x = x
            self.assertAlmostEqual(float(p1.x), x)
            self.assertAlmostEqual(float(m12.x), (x + float(p2.x)) / 2.0)
            self.assertAlmostEqual(float(m12.y), (100.0 + 500.0) / 2.0)


class TestPullBySinkKind(PullCase):
    """Each kind of link sink: a read stores, it does not invalidate."""

    def test_point_formula_sink(self):
        a = self.own(Point(x=0.0, y=0.0))
        s = self.own(Point())
        s @= lambda: (float(a.x) + 1.0, float(a.y) + 2.0)
        _ = s.x
        a.move_to(10.0, 20.0)
        self.assertEqual(_mark_dirty_calls(lambda: (s.x, s.y)), 0)
        self.assertEqual((float(s.x), float(s.y)), (11.0, 22.0))

    def test_line_endpoint_sink(self):
        a = self.own(Point(x=0.0, y=0.0))
        b = self.own(Point(x=5.0, y=5.0))
        ln = self.own(Line(p1=lambda: a, p2=lambda: b))
        _ = ln.p1.x
        a.move_to(3.0, 4.0)
        self.assertEqual(_mark_dirty_calls(lambda: (ln.p1.x, ln.p2.x)), 0)
        self.assertEqual((float(ln.p1.x), float(ln.p1.y)), (3.0, 4.0))

    def test_scalar_attribute_sink(self):
        st = self.own(State(name="w"))
        st.w = 40.0
        r = self.own(Rect(center=(0.0, 0.0), width=10.0, height=10.0))
        r["width"] @= lambda: float(st.w) * 2.0
        _ = r.width
        st.w = 50.0
        self.assertEqual(_mark_dirty_calls(lambda: r.width), 0)
        self.assertEqual(float(r.width), 100.0)

    def test_state_scalar_sink(self):
        st = self.own(State(name="src"))
        st.a = 1.0
        out = self.own(State(name="out"))
        out.b = 0.0
        out["b"] @= lambda: float(st.a) * 3.0
        _ = out.b
        st.a = 2.0
        self.assertEqual(_mark_dirty_calls(lambda: out.b), 0)
        self.assertEqual(float(out.b), 6.0)


class TestPullKeepsDownstreamFresh(PullCase):
    """The flip side: skipping the pull-time walk must not strand a sink.

    a -> m -> s. Pull ``m`` alone, then read ``s``; write again and repeat.
    ``s`` was dirtied by the write's own walk, so it must still refresh.
    """

    def test_partial_pull_then_downstream_read(self):
        a = self.own(Point(x=0.0, y=0.0))
        m = self.own(Point())
        m @= lambda: (float(a.x) * 2.0, 0.0)
        s = self.own(Point())
        s @= lambda: (float(m.x) + 1.0, 0.0)
        for x in (1.0, 2.0, 2.0, 7.0):
            a.move_to(x, 0.0)
            self.assertEqual(float(m.x), 2.0 * x)  # partial pull first
            self.assertEqual(float(s.x), 2.0 * x + 1.0)

    def test_outbound_link_from_a_pulled_point(self):
        # A pulled Point that is itself the source of a Line endpoint link.
        a = self.own(Point(x=0.0, y=0.0))
        m = self.own(Point())
        m @= lambda: (float(a.x) + 5.0, float(a.y))
        ln = self.own(Line(p1=lambda: m, p2=(100.0, 100.0)))
        for x in (1.0, 9.0, -4.0):
            a.move_to(x, 2.0)
            _ = m.x  # pull the middle node before the Line reads it
            self.assertEqual((float(ln.p1.x), float(ln.p1.y)), (x + 5.0, 2.0))


class TestPullResolversStoreRaw(unittest.TestCase):
    """AST guard for the class: pull resolvers write through ``_takein_impl``.

    ``_takein`` is the invalidating dispatcher. Inside a pull resolver (or
    inside a ``with …_no_update():`` in ``evaluate_and_update``) it re-walks
    the cone the triggering write already walked. Derivate-part refreshes
    that *must* notify their own outbound consumers (``_refresh_*`` in
    shapes / box) are not pull resolvers and are not checked here.
    """

    RESOLVERS = {"_resolve_link", "_resolve_structural"}

    @staticmethod
    def _dispatcher_calls(node):
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "_takein"):
                yield sub.lineno

    @staticmethod
    def _no_update_blocks(fn):
        for w in ast.walk(fn):
            if isinstance(w, ast.With) and any(
                isinstance(i.context_expr, ast.Call)
                and isinstance(i.context_expr.func, ast.Attribute)
                and i.context_expr.func.attr == "_no_update"
                for i in w.items
            ):
                yield w

    def test_resolvers_never_call_the_dispatcher(self):
        bad, seen = [], set()
        for path in iter_files(os.path.join(ROOT, "scena"), ".py"):
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            rel = os.path.relpath(path, ROOT)
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef):
                    continue
                if fn.name in self.RESOLVERS:
                    seen.add(fn.name)
                    bad += [f"{rel}:{ln} {fn.name}" for ln in self._dispatcher_calls(fn)]
                elif fn.name == "evaluate_and_update":
                    seen.add(fn.name)
                    for w in self._no_update_blocks(fn):
                        bad += [f"{rel}:{ln} {fn.name} (under _no_update)"
                                for ln in self._dispatcher_calls(w)]
        # Vacuity guard: a rename must not silently empty this check.
        self.assertEqual(seen, self.RESOLVERS | {"evaluate_and_update"})
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
