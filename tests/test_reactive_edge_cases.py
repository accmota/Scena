"""Edge cases for pull reactivity, events, and Vec2 geometry.

Run headless::

    python -m unittest tests.test_reactive_edge_cases -v
"""

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.entity import Entity
from scena.events import on_change, when, cleanup_global_event_system, get_global_event_system
from scena.shapes import Circle, Point, Rect
from scena.state import (
    Attribute,
    DerivedAttributeError,
    DestroyedError,
    FormulaLink,
    State,
    get_scena_system,
)
from scena.scenamath import Vec2
from tests.graph_support import gc_paused, settled_graph_size


class ReactiveEdgeCaseTest(unittest.TestCase):
    def tearDown(self):
        ss = get_scena_system()
        if ss is not None and ss.update_manager.deferring:
            ss.end_frame_batch()
        cleanup_global_event_system()


class TestVec2Geometry(ReactiveEdgeCaseTest):
    def test_reflect_about_and_project_onto(self):
        reflected = Vec2(x=1, y=0).reflect_about(Vec2(x=0, y=1))
        self.assertEqual(reflected.to_tuple(), (1.0, 0.0))
        projected = Vec2(x=1, y=1).project_onto(Vec2(x=1, y=0))
        self.assertEqual(projected.to_tuple(), (1.0, 0.0))
        rejected = Vec2(x=1, y=1).reject_from(Vec2(x=1, y=0))
        self.assertAlmostEqual(rejected.x, 0.0, places=6)
        self.assertAlmostEqual(rejected.y, 1.0, places=6)

    def test_abs_angle_to_zero_length_is_zero(self):
        self.assertEqual(Vec2(x=0, y=0).abs_angle_to(Vec2(x=1, y=0)), 0.0)
        self.assertEqual(Vec2(x=1, y=0).abs_angle_to(Vec2(x=0, y=0)), 0.0)

    def test_abs_angle_to_nonzero_unchanged(self):
        angle = Vec2(x=1, y=0).abs_angle_to(Vec2(x=0, y=1))
        self.assertAlmostEqual(angle, 90.0, places=5)

    def test_takein_list_and_scalar_anchor(self):
        v = Vec2(x=0, y=0)
        v._takein([3, 4])
        self.assertEqual((v.x, v.y), (3.0, 4.0))
        circle = Circle(center=(0, 0), radius=5)
        try:
            anchor = circle._ensure_scalar_anchor("radius")
            v._takein((anchor, 1.0))
            self.assertEqual(v.x, 5.0)
            self.assertEqual(v.y, 1.0)
        finally:
            circle.destroy()


class TestPullResolve(ReactiveEdgeCaseTest):
    def test_failed_pull_preserves_dirty_and_retries(self):
        a = Attribute(1.0)
        c = Attribute(0.0)
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("pull boom")
            return 1.0

        c @= (lambda: a.value + boom())
        self.assertEqual(c.value, 2.0)
        a.value = 10
        self.assertTrue(c._dirty)
        with self.assertRaises(RuntimeError):
            _ = c.value
        self.assertTrue(c._dirty)
        self.assertEqual(c.value, 11.0)
        self.assertFalse(c._dirty)

    def test_failed_link_install_rolls_back(self):
        a = Attribute(1.0)
        b = Attribute(0.0)

        def boom():
            raise RuntimeError("nope")

        with self.assertRaises(RuntimeError):
            b @= (lambda: a.value + boom())
        self.assertIsNone(b._link)
        self.assertEqual(b.value, 0.0)
        self.assertFalse(a._needs_pull_invalidate)
        self.assertFalse(b._needs_pull_invalidate)
        graph = get_scena_system().dependency_graph
        if a._node_id is not None and b._node_id is not None:
            self.assertNotIn(b._node_id, graph.dependents.get(a._node_id, ()))

    def test_state_subscript_in_a_formula_is_refused(self):
        # Inside a formula the bracket is the handle, not the value: refused at
        # link time naming the dot spelling (it used to link a bare
        # ``lambda: st["score"]`` and silently break any arithmetic on it).
        st = State(name="bag")
        st.score = 4
        sink = Attribute(0.0)
        with self.assertRaises(TypeError) as ctx:
            sink @= (lambda: st["score"])
        self.assertIn("st.score", str(ctx.exception))  # the author's spelling
        sink @= (lambda: st.score)
        st.score = 9
        self.assertEqual(sink.value, 9)

    def test_repl_fallback_sees_closure_and_state_cell(self):
        a = Attribute(3.0)
        fn = lambda: a.value + 1  # noqa: E731 — exercised with AST disabled
        orig = FormulaLink.__dict__["_locate_lambda_node"]
        FormulaLink._locate_lambda_node = staticmethod(lambda _fn: None)
        try:
            link = FormulaLink(fn)
            self.assertIn(a, list(link.sources))
            st = State(name="repl")
            st.score = 2
            state_fn = lambda h=st: h.score  # noqa: E731
            state_link = FormulaLink(state_fn)
            self.assertIn(st._data["score"], list(state_link.sources))
        finally:
            FormulaLink._locate_lambda_node = orig


class TestDerivateWriteStaysCold(ReactiveEdgeCaseTest):
    def test_failed_derivate_set_does_not_materialize(self):
        rect = Rect(top_left=(0, 0), width=10, height=5)
        root = rect._ownership_root()
        self.assertFalse(root._needs_pull_invalidate)
        with self.assertRaises(DerivedAttributeError):
            rect.top_right = (99, 99)
        self.assertFalse(root._needs_pull_invalidate)
        self.assertNotIn("top_right", rect.__dict__)
        with self.assertRaises(DerivedAttributeError):
            rect["top_right"] @= Point(1, 1)
        self.assertNotIn("top_right", rect.__dict__)
        self.assertFalse(root._needs_pull_invalidate)

    def test_defining_assignment_still_works(self):
        top_left = Rect(top_left=(0, 0), width=10, height=5)
        top_left.top_left = (3, 4)
        self.assertEqual((top_left.top_left.x, top_left.top_left.y), (3.0, 4.0))
        centered = Rect(center=(0, 0), width=10, height=5)
        centered.center = (8, 9)
        self.assertEqual((centered.center.x, centered.center.y), (8.0, 9.0))


class TestEvents(ReactiveEdgeCaseTest):
    def test_on_change_point_and_fieldref(self):
        point = Point(0, 0)
        hits = []

        @on_change(point)
        def on_point(value):
            hits.append(("point", value))

        point._takein((5, 5))
        get_scena_system().flush()
        self.assertEqual(hits, [("point", (5.0, 5.0))])

        rect = Rect(center=(0, 0), width=10, height=4)
        radius_hits = []
        circle = Circle(center=(0, 0), radius=1)

        @on_change(circle["radius"])
        def on_radius(value):
            radius_hits.append(value)

        circle.radius = 9
        get_scena_system().flush()
        self.assertEqual(radius_hits, [9])
        rect.destroy()
        circle.destroy()
        point.destroy()

    def test_pull_path_flushes_events_outside_frame(self):
        a = Attribute(1.0)
        b = Attribute(0.0)
        b @= (lambda: a.value * 2)
        hits = []

        @on_change(lambda: a.value)
        def on_a(value):
            hits.append(value)

        a.value = 5
        self.assertEqual(hits, [5])
        self.assertEqual(b.value, 10)

    def test_events_wait_for_flush_while_deferring(self):
        a = Attribute(1.0)
        b = Attribute(0.0)
        b @= (lambda: a.value * 2)
        hits = []

        @on_change(lambda: a.value)
        def on_a(value):
            hits.append(value)

        ss = get_scena_system()
        ss.begin_frame_batch()
        a.value = 5
        self.assertEqual(hits, [])
        self.assertEqual(b.value, 10)
        ss.flush()
        self.assertEqual(hits, [5])
        ss.end_frame_batch()

    def test_when_non_bool_raises_at_the_decorator(self):
        st = State(name="bag")
        st.x = 1

        with self.assertRaisesRegex(TypeError, "must evaluate to bool"):
            @when(lambda: st.x)
            def bad():
                pass

    def test_when_turning_non_bool_raises_at_the_write(self):
        st = State(name="bag")
        st.x = True

        @when(lambda: st.x)
        def bad():
            pass

        with self.assertRaisesRegex(TypeError, "must evaluate to bool"):
            st.x = 2

    def test_callback_error_propagates_later_events_run_next_poll(self):
        st = State(name="bag")
        st.y = 0
        hits = []

        @on_change(lambda: st.y)
        def bad(value):
            raise RuntimeError("callback boom")

        @on_change(lambda: st.y)
        def ok(value):
            hits.append(value)

        with self.assertRaisesRegex(RuntimeError, "callback boom"):
            st.y = 4
        self.assertEqual(hits, [])  # later watch waits for the next poll
        get_scena_system().flush()
        self.assertEqual(hits, [4])

    def test_raising_callback_consumes_the_edge(self):
        a = Attribute(0.0)
        calls = []

        @when(lambda: a.value > 1)
        def boom():
            calls.append(1)
            raise ValueError("when body bug")

        with self.assertRaisesRegex(ValueError, "when body bug"):
            a.value = 5
        get_scena_system().flush()  # still True: edge already consumed
        self.assertEqual(calls, [1])
        a.value = 0
        with self.assertRaises(ValueError):
            a.value = 6  # a new rising edge fires again
        self.assertEqual(calls, [1, 1])

    def test_condition_error_propagates_and_keeps_the_watch(self):
        a = Attribute(1.0)
        calls = {"n": 0}

        def cond():
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("condition bug")
            return a.value

        hits = []

        @on_change(cond)
        def on_a(value):
            hits.append(value)

        reg = on_a._event_registration
        with self.assertRaisesRegex(ValueError, "condition bug"):
            a.value = 2
        self.assertTrue(reg._is_active)
        a.value = 3
        self.assertEqual(hits, [3])

    def test_plain_attribute_error_in_condition_raises(self):
        a = Attribute(1.0)
        calls = {"n": 0}

        def cond():
            calls["n"] += 1
            if calls["n"] == 2:
                raise AttributeError("'Ship' object has no attribute 'hpp'")
            return a.value

        @on_change(cond)
        def on_a(value):
            pass

        with self.assertRaisesRegex(AttributeError, "hpp"):
            a.value = 2
        self.assertTrue(on_a._event_registration._is_active)

    def test_typo_in_condition_raises_at_registration(self):
        st = State(name="bag")
        st.score = 0
        with self.assertRaises(AttributeError):
            @when(lambda: st.scroe > 10)
            def never():
                pass

    def test_destroyed_source_retires_quietly(self):
        e = Entity()
        e.hp = 3
        hits = []

        @when(lambda: e.hp <= 0)
        def dead():
            hits.append(1)

        reg = dead._event_registration
        e.destroy()
        get_scena_system().flush()
        self.assertFalse(reg._is_active)
        self.assertEqual(hits, [])

    def test_destroyed_source_at_registration_retires(self):
        e = Entity()
        e.hp = 3
        e.destroy()

        @when(lambda: e.hp <= 0)
        def dead():
            pass

        self.assertFalse(dead._event_registration._is_active)

    def test_when_rejects_bare_bool_constant(self):
        # Regression: `@when(st.hp <= 0)` evaluates the comparison once, at
        # decoration time, into a plain bool that then never changes — the
        # watch registered successfully and simply never fired again.
        st = State(name="bag")
        st.hp = 5
        with self.assertRaisesRegex(TypeError, "wrap them in a lambda"):
            @when(st.hp <= 0)
            def never():
                pass

    def test_on_change_rejects_bare_attribute_read(self):
        e = Entity()
        e.hp = 3
        with self.assertRaisesRegex(TypeError, "wrap them in a lambda"):
            @on_change(e.hp)  # reads the int now, not the live Attribute
            def never(value):
                pass
        e.destroy()

    def test_when_rejects_bare_non_callable_literal(self):
        with self.assertRaisesRegex(TypeError, "wrap them in a lambda"):
            @when(5)
            def never():
                pass

    def test_on_change_rejects_non_leaf_container(self):
        # Regression: `@on_change(circle)` accepted a whole Shape/Entity
        # Container. Its identity never changes, so it can never fire —
        # the author almost certainly meant one of its fields.
        circle = Circle(center=(0, 0), radius=5)
        with self.assertRaisesRegex(TypeError, "never changes"):
            @on_change(circle)
            def never(value):
                pass
        circle.destroy()

    def test_on_change_accepts_attribute_point_and_fieldref(self):
        # These are the three "live reference" shapes that must keep working.
        st = State(name="bag")
        st.hp = 5
        hits = []

        @on_change(st["hp"])
        def on_hp(value):
            hits.append(("attr", value))

        point = Point(1, 1)

        @on_change(point)
        def on_point(value):
            hits.append(("point", value))

        circle = Circle(center=(0, 0), radius=1)

        @on_change(circle["radius"])
        def on_radius(value):
            hits.append(("field", value))

        st.hp = 1
        point._takein((2, 2))
        circle.radius = 9
        get_scena_system().flush()
        self.assertEqual(
            hits, [("attr", 1), ("point", (2.0, 2.0)), ("field", 9)]
        )
        circle.destroy()
        point.destroy()

    def test_numpy_bool_accepted_by_when(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        st = State(name="bag")
        st.hp = 5
        hits = []

        @when(lambda: np.bool_(st.hp <= 0))
        def dead():
            hits.append(1)

        st.hp = -1
        get_scena_system().flush()
        self.assertEqual(hits, [1])

    def test_on_change_fires_on_in_place_list_mutation(self):
        # Regression: `self._old_value = value` stored a *reference*; an
        # in-place `lst.append(...)` compared the list against itself
        # (same object) and never fired.
        lst = [1, 2, 3]
        hits = []

        @on_change(lambda: lst)
        def on_list(value):
            hits.append(list(value))

        lst.append(4)
        get_scena_system().flush()
        self.assertEqual(hits, [[1, 2, 3, 4]])

    def test_destroyed_error_is_an_attribute_error(self):
        e = Entity()
        e.destroy()
        with self.assertRaises(DestroyedError):
            e.hp
        self.assertFalse(hasattr(e, "hp"))

    def test_cascade_settles_in_one_flush(self):
        a = Attribute(0.0)
        b = Attribute(0.0)
        hits = []

        @on_change(lambda: a.value)
        def copy(value):
            b.value = value * 2

        @when(lambda: b.value > 5)
        def high():
            hits.append(b.value)

        ss = get_scena_system()
        ss.begin_frame_batch()
        try:
            a.value = 4
            ss.flush()  # round 1: copy; round 2: high
        finally:
            ss.end_frame_batch()
        self.assertEqual(hits, [8.0])

    def test_retrigger_cycle_warns_instead_of_spinning(self):
        from scena.state import FLUSH_MAX_ROUNDS
        a = Attribute(0.0)
        b = Attribute(0.0)
        calls = []

        @on_change(lambda: a.value)
        def bump_b(value):
            calls.append("b")
            b.value = value + 1

        @on_change(lambda: b.value)
        def bump_a(value):
            calls.append("a")
            a.value = value + 1

        ss = get_scena_system()
        ss.begin_frame_batch()
        try:
            a.value = 1
            with self.assertWarnsRegex(RuntimeWarning, "re-triggering"):
                ss.flush()
        finally:
            ss.end_frame_batch()
        # The first round fires both without a repeat; then at most
        # FLUSH_MAX_ROUNDS rounds in which a watch fires again.
        self.assertLessEqual(len(calls), 2 * (FLUSH_MAX_ROUNDS + 1))

    def test_long_acyclic_chain_settles_in_one_flush(self):
        # A relay chain longer than FLUSH_MAX_ROUNDS with no cycle is not a
        # cycle: no warning, no lag (review 2026-10-09 S2-17). Registered
        # tail first, so every round advances it by one link.
        import warnings
        from scena.state import FLUSH_MAX_ROUNDS
        n = FLUSH_MAX_ROUNDS + 4
        cells = [Attribute(0.0) for _ in range(n + 1)]
        for i in reversed(range(n)):
            def relay(value, i=i):
                cells[i + 1].value = value
            on_change(lambda i=i: cells[i].value)(relay)
        ss = get_scena_system()
        ss.begin_frame_batch()
        try:
            cells[0].value = 7.0
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                ss.flush()
        finally:
            ss.end_frame_batch()
        self.assertEqual([c.value for c in cells], [7.0] * (n + 1))

    def test_nan_fires_once(self):
        b = Attribute(1.0)
        hits = []

        @on_change(lambda: b.value)
        def on_b(value):
            hits.append(value)

        b.value = float("nan")
        self.assertEqual(len(hits), 1)
        get_scena_system().flush()
        self.assertEqual(len(hits), 1)


class TestStateReserved(ReactiveEdgeCaseTest):
    def test_method_names_cannot_be_cells(self):
        st = State(name="bag")
        for key in ("keys", "exists", "create", "remove"):
            with self.assertRaises(AttributeError):
                setattr(st, key, 1)
            with self.assertRaises(AttributeError):
                st.create(key, 1)
        self.assertTrue(callable(st.keys))
        st.score = 1
        self.assertIn("score", st.keys())


class TestNoLinkOntoADestroyedActor(ReactiveEdgeCaseTest):
    """W2 (Testing Design): ``dead["mirror"] @= f`` was accepted and put the
    destroyed actor back in the dependency graph (4 nodes). A link is a write:
    on a destroyed owner — ink cell, slot, or a part like ``center`` — it raises
    ``DestroyedError`` and registers nothing."""

    def test_link_targets_on_a_dead_actor_raise(self):
        from scena.state import DestroyedError
        src = Circle(center=(0, 0), radius=1)
        src.hp = 5
        try:
            for label, link in {
                "ink cell": lambda d: d["mirror"].__imatmul__(lambda s=src: s.hp + 1),
                "slot": lambda d: d["radius"].__imatmul__(lambda s=src: s.radius + 1),
                "part": lambda d: d.center.__imatmul__(lambda s=src: s.center),
            }.items():
                with self.subTest(target=label):
                    dead = Circle(center=(0, 0), radius=3)
                    dead.destroy()
                    with gc_paused():
                        before = settled_graph_size()
                        with self.assertRaises(DestroyedError):
                            link(dead)
                        self.assertEqual(len(get_scena_system().dependency_graph.nodes), before)
        finally:
            src.destroy()


class TestFailedLinkInstallsNothing(ReactiveEdgeCaseTest):
    """W3 (Testing Design): a formula that raises on its first evaluation
    left the ink cell it created (``a.mirror`` read 0.0 afterwards) and a
    scalar anchor in the graph. A rejected ``@=`` installs nothing.

    O9 (Testing Design): the count is taken settled and with the cyclic GC
    paused. Unsettled, an earlier test's garbage (``TestEvents`` leaves two
    Attributes per test) was purged mid-test and the module failed alone."""

    def test_rejected_formula_leaves_no_cell_and_no_node(self):
        a = Circle(center=(0, 0), radius=6)
        b = Circle(center=(0, 0), radius=3)
        self.enterContext(gc_paused())
        try:
            graph = get_scena_system().dependency_graph
            before = settled_graph_size()
            with self.assertRaises(AttributeError):
                a["mirror"] @= (lambda s=b: s.hp + 1)     # b has no hp
            self.assertEqual(len(graph.nodes), before)
            with self.assertRaises(AttributeError):
                a.mirror                                    # no cell was created
            with self.assertRaises(AttributeError):
                a["radius"] @= (lambda s=b: s.nope)         # existing slot
            self.assertFalse(a["radius"].is_linked)
            self.assertEqual(float(a.radius), 6.0)
            self.assertEqual(len(graph.nodes), before)
            b.hp = 1
            a["mirror"] @= (lambda s=b: s.hp + 1)           # the good link still works
            self.assertEqual(a.mirror, 2)
        finally:
            a.destroy()
            b.destroy()


class TestUnlinkFreezesTheCurrentValue(ReactiveEdgeCaseTest):
    """D8 (Testing Design): ``unlink()`` froze the last *computed* value. Under
    pull reactivity a write to the source only marks the dependent dirty, so an
    unlink with no read in between froze a stale value — the result depended on
    whether someone happened to read first. Found by ``test_diff_reactive``'s
    link model (``chain`` op → write → unlink)."""

    def _cases(self):
        a, b = Attribute(0), Attribute(0)
        b @= (lambda a=a: a.value)
        yield "Attribute", (lambda v: setattr(a, "value", v)), b.unlink, (lambda: b.value)
        s, d = Entity(), Entity()
        s.v = 0
        d.v = 0
        d["v"] @= (lambda s=s: s.v)
        yield "ink", (lambda v: setattr(s, "v", v)), d["v"].unlink, (lambda: d.v)
        c, k = Circle(center=(0, 0), radius=2), Circle(center=(0, 0), radius=2)
        k["radius"] @= (lambda c=c: c.radius * 2)
        yield "ScalarSlot", (lambda v: setattr(c, "radius", v / 2)), k["radius"].unlink, (lambda: k.radius)

    def test_unlink_after_an_unread_write(self):
        for batched in (False, True):
            for label, write, unlink, read in self._cases():
                with self.subTest(kind=label, frame_batch=batched):
                    ss = get_scena_system()
                    if batched:
                        ss.begin_frame_batch()
                    try:
                        write(10)          # dependent is dirty, nobody reads it
                        unlink()
                        self.assertEqual(float(read()), 10.0)
                        write(3)           # unlinked: no longer follows
                        self.assertEqual(float(read()), 10.0)
                    finally:
                        if batched:
                            ss.end_frame_batch()

    def test_destroyed_source_leaves_its_final_value(self):
        # Auto-unlink on destroy keeps the dependent's value; the pull happens
        # while the source still reads as alive — after on_destroy's writes.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s, d = Entity(), Entity()
            s.v = 0
            d.v = 0
            d["v"] @= (lambda s=s: s.v)
            s.v = 7                      # unread
            s.on_destroy = lambda: setattr(s, "v", 99)
            s.destroy()
            self.assertEqual(d.v, 99)
            c, k = Circle(center=(0, 0), radius=2), Circle(center=(0, 0), radius=2)
            k["radius"] @= (lambda c=c: c.radius * 2)
            c.radius = 5                 # unread
            c.destroy()
            self.assertEqual(float(k.radius), 10.0)
            d.destroy()
            k.destroy()



class TestReactiveCoreDoors(unittest.TestCase):
    """Review 2026-10-09 S5-3 / S5-4 / S5-5: the same rules on every door."""

    def test_property_anchor_pull_keeps_the_numbers_rule(self):
        from scena import Point, st
        st.s53 = True
        p = Point(0, 0)
        with self.assertRaises(TypeError):
            p["angle"] @= (lambda: st.s53)       # took True as 1.0
        st.s53 = 10 ** 400
        q = Point(0, 0)
        with self.assertRaises(ValueError):
            q["angle"] @= (lambda: st.s53)       # leaked OverflowError
        p.destroy()
        q.destroy()

    def test_handlers_do_not_flush_mid_batch_outside_a_frame(self):
        from scena import Rect, Point, on_change
        r = Rect(top_left=(10, 20), width=10, height=6)
        q = Point(0, 0)
        q @= r.top_left
        seen = []
        on_change(lambda: (r.top_left.x, r.top_left.y))(lambda v: seen.append(v))
        r.move_by(5, 7)                            # one compound write
        self.assertEqual(seen[-1:], [(15.0, 27.0)])
        self.assertNotIn((15.0, 20.0), seen)      # a pose that never existed
        q.destroy()
        r.destroy()

    def test_unlink_keeps_the_last_value_when_the_formula_raises(self):
        from scena import Circle, st
        st.s55 = {"k": 7}
        c = Circle(radius=1)
        c["radius"] @= (lambda: st.s55["k"])
        self.assertEqual(c.radius, 7)
        st.s55 = {}                                # the formula now raises KeyError
        c["radius"].unlink()
        self.assertEqual(c.radius, 7)
        self.assertNotIn("radius", c.__dict__.get("_field_anchors") or {})
        c.destroy()
        self.assertFalse(c.is_alive)

    def test_destroy_with_a_raising_formula_completes(self):
        from scena import Circle, st
        st.s55b = {"k": 3}
        c = Circle(radius=1)
        c["radius"] @= (lambda: st.s55b["k"])
        st.s55b = {}
        c.destroy()                                # raised KeyError half-way
        self.assertFalse(c.is_alive)
        self.assertIsNone(c.__dict__.get("_node_id") if "_node_id" in c.__dict__ else None)

    def test_a_retired_part_reads_inactive(self):
        from scena import Circle
        c = Circle(radius=3)
        center = c.center
        c.destroy()
        self.assertFalse(center.active)            # the slot kept True (S5-4 class)


class TestGraphResetRebindsEverySource(unittest.TestCase):
    """Deep serial pass (2026-10-09): ``init_scena_system()`` re-pointed only
    ``keyp`` / ``mouse`` / ``clock`` at the new graph (a hand list). The
    ``canvas`` facade, a formula source since RX1, kept the old one: after any
    module reset the graph, ``lambda: canvas.game_view`` links froze."""

    def test_a_camera_link_follows_after_a_graph_reset(self):
        import builtins
        from scena import canvas
        from scena.state import Container, get_scena_system, init_scena_system
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from system_support import system_world
        init_scena_system()
        for obj in vars(builtins).values():
            if isinstance(obj, Container) and "_scena_system" in obj.__dict__:
                self.assertIs(obj._scena_system, get_scena_system(), type(obj).__name__)
        with system_world(draw=False) as w:
            dot = Circle(center=(0, 0), radius=2)
            dot["center"] @= (lambda: canvas.game_view.center)
            w.step(1)
            canvas.pan_by(30, 0)
            w.step(1)
            self.assertAlmostEqual(dot.center.x, canvas.game_view.center.x)
            dot.destroy()
            canvas.reset_view()

    def test_a_cell_made_before_a_graph_reset_still_drives_links(self):
        """Deep serial pass (2026-10-22): ``st`` is no ``Container``, so the
        rebind skipped it; a cell another module made before a reset kept
        its node on the old graph. Its writes notified nothing on the new
        one: every later ``lambda: st.n`` link froze (paint links, a HUD
        score, a query position). Every cell of every bag in builtins moves
        to the new graph; values stay."""
        import builtins
        from scena import Rect, Vec2, st
        from scena.state import State, get_scena_system, init_scena_system
        st.gr_n = 0
        st.gr_v = Vec2(1, 2)
        st["gr_lk"] @= lambda: st.gr_n + 1
        self.addCleanup(lambda: [st.remove(k) for k in ("gr_n", "gr_v", "gr_lk")])
        init_scena_system()
        ss = get_scena_system()
        for bag in vars(builtins).values():
            if isinstance(bag, State):
                for key, cell in bag._data.items():
                    self.assertIs(cell._scena_system, ss, f"{bag.name}.{key}")
        self.assertEqual((st.gr_n, tuple(st.gr_v), st.gr_lk), (0, (1.0, 2.0), 1))
        r = Rect()
        self.addCleanup(r.destroy)
        r["color"] @= lambda: "red" if st.gr_n < 5 else "blue"
        r.fill
        st.gr_n = 6
        self.assertEqual(tuple(round(float(c), 3) for c in r.fill.rgb[:3]), (0.0, 0.0, 1.0))
        q = Rect()
        self.addCleanup(q.destroy)
        q["center"] @= lambda: st.gr_v
        st.gr_v.x = 9
        self.assertEqual(tuple(q.center), (9.0, 2.0))



class TestOnChangeComparesOncePerFrame(unittest.TestCase):
    """``@on_change`` compares once per frame, at the flush: two writes in one
    frame that end at the old value fire nothing (persona probes PP: the
    Scratch "broadcast again", ``st.msg = ""; st.msg = "nova onda"``, never
    sent wave 2). Counting is the way to send the same message twice. The
    Guia says so (Começar, "De outro motor"; FRAME_PROMISES)."""

    def setUp(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from system_support import SystemWorld, boot
        boot()
        self.w = SystemWorld(draw=False)
        self.addCleanup(self.w.teardown)

    def test_writes_back_to_the_old_value_in_one_frame_fire_nothing_and_a_count_fires(self):
        from scena import st
        st.pp_msg = "go"
        st.pp_waves = 0
        got, waves = [], []

        @on_change(st["pp_msg"])
        def heard(v):
            got.append(v)

        @on_change(st["pp_waves"])
        def wave(v):
            waves.append(v)

        class Sender(Entity):
            def on_update(self, dt):
                st.pp_msg = ""
                st.pp_msg = "go"
                st.pp_waves += 1

        self.w.track(Sender())
        self.w.step(3)
        self.assertEqual(got, [])
        self.assertEqual(waves, [1, 2, 3])


class TestPauseStartsNextFrame(unittest.TestCase):
    """A pause set during a frame (``update``, a key handler) starts at the
    next frame: this frame already has its ``dt``, so its ``on_update`` and
    tweens run once more (persona probes round 3, R3-11, a documented rule:
    the Guia's ``clock.paused`` row; FRAME_PROMISES)."""

    def setUp(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from system_support import SystemWorld, boot
        boot()
        self.w = SystemWorld(draw=False)
        self.addCleanup(self.w.teardown)

    def test_the_frame_of_the_pause_still_moves_then_nothing_does(self):
        from scena import clock
        moved = []

        class Fleet(Entity):
            def on_update(self, dt):
                moved.append(dt)
                if len(moved) == 3:
                    clock.paused = True

        self.w.track(Fleet())
        self.addCleanup(lambda: setattr(clock, "paused", False))
        self.w.step(6)
        self.assertEqual(len([d for d in moved if d > 0]), 3)
        self.assertTrue(all(d == 0 for d in moved[3:]), moved)


class TestAWatchOnAGlobalRetiresAtTheDestroy(unittest.TestCase):
    """A ``@when`` whose condition reads an actor through a module global
    retired when the read raised after the destroy; a dead actor's own
    fields read now (R3-1), so ``destroy()`` retires it (the world machine
    found the live watch left behind)."""

    def test_the_watch_leaves_with_the_actor(self):
        ns = {"Entity": Entity, "when": when}
        exec(compile("alvo = Entity()\nalvo.hp = 3\n"
                     "@when(lambda: alvo.hp <= 0)\ndef morreu():\n    pass\n",
                     "author_mod.py", "exec"), ns)
        reg = ns["morreu"]._event_registration
        self.assertTrue(reg._is_active)
        ns["alvo"].destroy()
        self.assertFalse(reg._is_active)

if __name__ == "__main__":
    unittest.main(verbosity=2)
