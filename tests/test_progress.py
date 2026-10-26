"""
Progress tracker for the Scena update-graph migration.

Run headless (no window) with either:

    python -m unittest tests.test_progress -v
    python tests/test_progress.py

Tests are grouped by migration phase. Tests for phases that are not finished
yet are marked with @unittest.expectedFailure, so:

  - the suite stays green while a phase is still pending, and
  - once you finish a phase, its tests turn into "unexpected success"
    (reported by unittest), which is the signal to remove the
    expectedFailure marker and treat the behavior as a hard requirement.

Current status when written:
  Phase 0 (formula links restored, notify_observer removed) ...... PASSING
  Phase 1 (@when / @on_change events)  .......................... PASSING
  Phase 2 (derived-vs-defining dependency direction) ............ PASSING
"""

import os
import sys
import unittest

# Ensure the repo root is importable regardless of how the test is launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Line, Point
from scena.state import State, Attribute, DependencyState, CircularReferenceError
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


def new_state(**values):
    """Helper: build a State pre-populated with the given key/value pairs."""
    st = State()
    for key, value in values.items():
        st.create(key, initial=value)
    return st


# ---------------------------------------------------------------------------
# Phase 0 - core value/formula plumbing (expected to PASS)
# ---------------------------------------------------------------------------
class TestPhase0Core(unittest.TestCase):

    def test_attribute_basic_value(self):
        a = Attribute(3)
        self.assertEqual(a.value, 3)
        a.value = 7
        self.assertEqual(a.value, 7)

    def test_direct_link_propagates(self):
        """b @= a (container direct link) tracks a."""
        st = new_state(a=5, b=0)
        a, b = st._resolve_cell("a"), st._resolve_cell("b")
        b @= a
        self.assertEqual(b.value, 5)
        a.value = 42
        self.assertEqual(b.value, 42)

    def test_lambda_formula_propagates(self):
        """b @= (lambda: a * 10) tracks a. Regression for FormulaLink.always_update."""
        st = new_state(a=2, b=0)
        a, b = st._resolve_cell("a"), st._resolve_cell("b")
        b @= (lambda: a * 10)
        self.assertEqual(b.value, 20)
        a.value = 5
        self.assertEqual(b.value, 50)

    def test_formula_without_container_sources_raises(self):
        """Plain Python names cannot drive @= — refuse at link time."""
        st = new_state(b=0)
        x = 10
        with self.assertRaises(TypeError) as ctx:
            st["b"] @= (lambda: x * 2)
        self.assertIn("no reactive sources", str(ctx.exception))
        self.assertFalse(st._resolve_cell("b")._link)

    def test_constant_lambda_raises(self):
        st = new_state(b=0)
        with self.assertRaises(TypeError) as ctx:
            st["b"] @= (lambda: 100)
        self.assertIn("no reactive sources", str(ctx.exception))

    def test_mixed_plain_and_container_still_links(self):
        """A Container source is enough; plain names ride along on re-eval."""
        st = new_state(a=2, b=0)
        x = 10
        st["b"] @= (lambda: x + st.a)
        self.assertEqual(st.b, 12)
        st.a = 5
        self.assertEqual(st.b, 15)

    def test_default_arg_capture_is_a_source(self):
        """``lambda h=host: h…`` is the loop-binding idiom — host is reactive."""
        hosts = [Attribute(3.0), Attribute(5.0)]
        sinks = [Attribute(0.0), Attribute(0.0)]
        for i, host in enumerate(hosts):
            sinks[i] @= (lambda h=host: h * 2)
        self.assertEqual(sinks[0].value, 6.0)
        self.assertEqual(sinks[1].value, 10.0)
        hosts[0].value = 7.0
        self.assertEqual(sinks[0].value, 14.0)
        self.assertEqual(sinks[1].value, 10.0)  # still bound to hosts[1]

    def test_subscript_chain_is_a_source(self):
        """``items[i].…`` must resolve the Container behind the index."""
        items = [Attribute(4.0), Attribute(9.0)]
        sink = Attribute(0.0)
        sink @= (lambda: items[0] * 10)
        self.assertEqual(sink.value, 40.0)
        items[0].value = 5.0
        self.assertEqual(sink.value, 50.0)

    def test_line_center_and_vec_are_computed(self):
        """Structural update computes center and vec on construction/update."""
        ln = Line(p1=(0, 0), p2=(10, 0))
        self.assertEqual(ln.center.x, 5)
        self.assertEqual(ln.center.y, 0)
        self.assertEqual(ln.vec.x, 10)
        self.assertEqual(ln.vec.y, 0)

    def test_line_defining_formula_moves_point(self):
        """A lambda formula on a defining attribute drives the point."""
        st = new_state(mx=0)
        mx = st._resolve_cell("mx")
        ln = Line(p1=(0, 0), p2=(10, 0))
        ln.p1["x"] @= (lambda: mx)
        mx.value = 100
        self.assertEqual(ln.p1.x, 100)

    def test_circular_reference_is_detected(self):
        st = new_state(a=0, b=0)
        a, b = st._resolve_cell("a"), st._resolve_cell("b")
        a @= (lambda: b)
        with self.assertRaises(CircularReferenceError):
            b @= (lambda: a)


# ---------------------------------------------------------------------------
# Phase 1 - event system (@when / @on_change). PASSING after graph re-integration.
# ---------------------------------------------------------------------------
class TestPhase1Events(unittest.TestCase):

    def test_when_event_fires_on_threshold(self):
        from scena.events import when, cleanup_global_event_system
        cleanup_global_event_system()
        st = new_state(x=0)
        x = st._resolve_cell("x")
        fired = []

        @when(lambda: x > 100)
        def _handler():
            fired.append(True)

        x.value = 150
        self.assertTrue(fired, "@when handler did not fire")
        cleanup_global_event_system()

    def test_when_rejects_non_bool(self):
        """A non-bool @when raises TypeError at the decorator line."""
        from scena.events import when, cleanup_global_event_system
        cleanup_global_event_system()
        st = new_state(x=0)
        x = st._resolve_cell("x")
        fired = []

        try:
            with self.assertRaisesRegex(TypeError, "bool"):
                @when(lambda: x)
                def _handler():
                    fired.append(True)
            x.value = 1
            self.assertEqual(fired, [])
        finally:
            cleanup_global_event_system()

    def test_on_change_fires_per_value_change(self):
        from scena.events import on_change, cleanup_global_event_system
        cleanup_global_event_system()
        st = new_state(x=0)
        x = st._resolve_cell("x")
        seen = []

        @on_change(x)
        def _handler(value):
            seen.append(value)

        x.value = 1
        x.value = 2
        self.assertEqual(seen, [1, 2])
        cleanup_global_event_system()

    def test_on_change_skips_unchanged(self):
        from scena.events import on_change, cleanup_global_event_system
        cleanup_global_event_system()
        st = new_state(x=0)
        x = st._resolve_cell("x")
        seen = []

        @on_change(x)
        def _handler(value):
            seen.append(value)

        x.value = 1
        x.value = 1
        self.assertEqual(seen, [1])
        cleanup_global_event_system()

    def test_stacked_when_both_fire_and_unregister(self):
        from scena.events import when, unregister_event, cleanup_global_event_system
        cleanup_global_event_system()
        flags = {"a": False, "b": False}
        fired = []

        @when(lambda: flags["a"])
        @when(lambda: flags["b"])
        def _handler():
            fired.append(1)

        flags["a"] = True
        from scena import flush
        flush()
        self.assertEqual(fired, [1])
        fired.clear()
        flags["a"] = False
        flush()
        flags["b"] = True
        flush()
        self.assertEqual(fired, [1])
        fired.clear()
        unregister_event(_handler)
        flags["a"] = True
        flush()
        self.assertEqual(fired, [])
        cleanup_global_event_system()

# ---------------------------------------------------------------------------
# Phase 2 - derived-vs-defining dependency direction.
# ---------------------------------------------------------------------------
class TestPhase2DependencyDirection(unittest.TestCase):

    def test_assign_formula_sets_linked_outward(self):
        st = new_state(a=0, src=100)
        a = st._resolve_cell("a")
        a @= (lambda: st.src)
        self.assertEqual(a._dependency_state, DependencyState.LINKED_OUTWARD)

    def test_unlink_restores_dependent_downward(self):
        st = new_state(a=0, src=100)
        a = st._resolve_cell("a")
        a @= (lambda: st.src)
        a.unlink()
        self.assertEqual(a._dependency_state, DependencyState.DEPENDENT_DOWNWARD)

    def test_external_formula_on_derived_attr_updates(self):
        """A formula reading a derived attribute (line.center) must stay in sync."""
        ln = Line(p1=(0, 0), p2=(10, 0))
        st = new_state(cx=-1)
        cx = st._resolve_cell("cx")
        cx @= (lambda: ln.center.x)
        self.assertEqual(cx.value, 5)
        ln.move_to(100, 0)
        self.assertEqual(cx.value, ln.center.x)

    def test_line_length_and_angle_are_computed(self):
        """length/angle are derived-of-derived (from vec) and must update in one cycle."""
        ln = Line(p1=(0, 0), p2=(10, 0))
        self.assertEqual(ln.length, 10)
        self.assertEqual(ln.angle, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
