"""Reactive matrix: field x write path x read order x construction model.

A linked field must read like the same field written with ``=``, whatever was
read before the source moved (I1), must not change between two reads (I6),
must freeze on unlink (I5), and must honor the slot's limits (I2).
``reactive_matrix_support`` derives the fields from the ``ScalarSlot`` /
``ContainerSlot`` descriptors; ``SUBJECTS`` holds one factory per construction
model, and ``TestEveryReactiveClassIsDriven`` fails when a class is added
without one. Complements ``test_diff_link_write`` (every ``geometry_support``
kind, whole vs per-axis links) with more read orders, a cell source, unlink,
idempotent reads and the limits.

    python tests/run_tiers.py focused test_reactive_matrix
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

import reactive_matrix_support as M  # noqa: E402

# (field, kind) pairs of KNOWN I2 failures. SHRINK-ONLY: a fix removes its
# entry, and an entry that now passes fails the suite. Empty since D16.
KNOWN_RANGE = frozenset()


# (subject, field) pairs that read stale when the Derivates are read BEFORE the
# linked field after the source moved (reversed read order). SHRINK-ONLY: a fix
# removes its entry, and an entry that now passes fails the suite.
# Empty since D18: a Line with a linked, derived heading pulls the heading
# before any read of the points it rewrites.
KNOWN_STALE_READ_ORDER = frozenset()

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _freshness_failures(subjects, reverse=False):
    bad = []
    for label, factory in subjects:
        for name, path, order in M.cells(factory):
            r = M.run_cell(factory, name, path, order, reverse)
            if r:
                bad.append((label, name, path, order, r))
    return bad


class TestLinkReadsLikeWrite(unittest.TestCase):
    def test_every_subject_field_path_and_order(self):
        bad = _freshness_failures(M.SUBJECTS)
        self.assertEqual(bad, [], "linked vs written: (subject, field, path, order, diff)")

    def test_reading_derivates_before_the_linked_field(self):
        bad = _freshness_failures(M.SUBJECTS, reverse=True)
        seen = {(label, name) for label, name, *_ in bad}
        new = [b for b in bad if (b[0], b[1]) not in KNOWN_STALE_READ_ORDER]
        self.assertEqual(new, [], "linked vs written, Derivates read first")
        self.assertEqual(KNOWN_STALE_READ_ORDER - seen, set(),
                         "fixed: remove these from KNOWN_STALE_READ_ORDER")

    def test_a_whole_vector_link_keeps_length_and_angle_fresh(self):
        for label, factory in M.SUBJECTS:
            if label not in ("Vec2", "Point"):
                continue
            for order in M.ORDERS:
                with self.subTest(subject=label, order=order):
                    self.assertIsNone(M.run_self_cell(factory, order))

    def test_the_matrix_is_not_vacuous(self):
        n = sum(1 for _, f in M.SUBJECTS for _ in M.cells(f))
        self.assertGreater(n, 1000)


def _whole_failures(subjects):
    bad = []
    for label, factory in subjects:
        for name, _ in M.field_names(factory()):
            for path in M.WHOLE_PATHS:
                for order in M.ORDERS:
                    r = M.run_whole_cell(factory, name, path, order)
                    if r:
                        bad.append((label, name, path, order, r))
    return bad


# Copies across construction models (``d << s`` where d and s were built
# differently). Kinds whose copy refuses on purpose, and fields a copy does not
# carry on purpose (kind -> reason).
COPY_REFUSES = {
    "RegularPolygon": "a different n is refused (ValueError): the copy cannot change n",
}
COPY_SKIPS_FIELD = {
    "Track": {"radius": "a copy is a free points= track (like clone()); radius is a circle input"},
}


def _cross_model_failures(kinds_by_class=None):
    import collections
    import geometry_support as G
    by = collections.defaultdict(list)
    for k in G.KINDS:
        cls = k.split()[0]
        if cls in ("Point", "Anchor", "Sprite", "Svg", "Text", "Polygon"):
            continue
        if kinds_by_class is not None and cls not in kinds_by_class:
            continue
        by[cls].append(k)
    bad = []
    for cls, kinds in by.items():
        skip = COPY_SKIPS_FIELD.get(cls, {})
        for ka in kinds:
            if ka.endswith("reversed"):
                continue              # a reversed() view refuses a copy (tested apart)
            for kb in kinds:
                d, s = G.build(ka), G.build(kb)
                try:
                    d << s
                except Exception as e:
                    if cls in COPY_REFUSES or G.refused(d, type(e).__name__):
                        continue          # a relational target is linked: << refuses
                    bad.append((ka, kb, "raised " + type(e).__name__))
                    continue
                names = [n for n, _ in M.field_names(s) if n not in skip]
                if G.is_relational(s):
                    # A copy is the free twin (graphics review SB5): the fields
                    # that only place it against the reference do not carry.
                    names = [n for n in names if n not in ("dist", "at_angle")]
                df = M.diff(M.snapshot_names(d, names), M.snapshot_names(s, names))
                if df:
                    bad.append((ka, kb, df))
    return bad


class TestWholeObjectLink(unittest.TestCase):
    """``d @= s`` / ``d @= lambda: s``: every name of d reads like s after s
    changes, whatever was read before (D19)."""

    def test_every_subject_field_and_order(self):
        self.assertEqual(_whole_failures(M.SUBJECTS), [])


class TestCopyAcrossModels(unittest.TestCase):
    """``d << s`` with d and s built by different models: the copy takes the
    source's model and Defining set, and reads like it (D21); Box copies (D20)."""

    def test_every_pair_of_models_of_a_kind(self):
        self.assertEqual(_cross_model_failures(), [])

    def test_a_copy_can_be_edited_through_its_new_inputs(self):
        from scena import Rect
        dst = Rect(center=(10, 10), width=2, height=2)
        dst << Rect(p1=(0, 0), p2=(4, 3))
        dst.p2 = (8, 3)                         # an input after the copy
        self.assertEqual((float(dst.p2.x), float(dst.width)), (8.0, 8.0))

    def test_a_rect_takes_in_a_square_with_its_own_inputs(self):
        # The target names its inputs for the adopted model: width / height,
        # not the Square's length (a Rect has no length).
        from scena import Rect, Square
        r = Rect(p1=(0, 0), p2=(1, 1))
        r << Square(center=(9, 8), length=5)
        self.assertEqual(sorted(r._defining_part_names), ["angle", "center", "height", "width"])
        r.width = 7
        self.assertEqual((float(r.width), float(r.height)), (7.0, 5.0))

    def test_a_square_refuses_a_rect(self):
        # A Rect's sides can differ; the copy used to raise AttributeError
        # (no ``length`` on a Rect). Nothing is written before the refusal.
        from scena import Rect, Square
        q = Square(center=(0, 0), length=3)
        with self.assertRaises(TypeError) as cm:
            q << Rect(center=(5, 5), width=4, height=2)
        self.assertIn("Square(center=rect.center, length=rect.width", str(cm.exception))
        self.assertEqual((float(q.length), float(q.center.x)), (3.0, 0.0))

    def test_a_reversed_view_refuses_a_copy(self):
        from scena import Track
        view = Track.eight().reversed()
        with self.assertRaises(TypeError) as cm:
            view << Track.circle()
        self.assertIn("host << other", str(cm.exception))

    def test_box_takes_only_a_box(self):
        from scena import Box, Rect
        b = Box(center=(0, 0), width=4, height=2)
        b << Box(p1=(0, 0), p2=(6, 3))
        self.assertEqual(float(b.width), 6.0)
        with self.assertRaises(TypeError) as cm:
            b << Rect(center=(0, 0), width=1, height=1)
        self.assertIn("Box(shape)", str(cm.exception))


class TestLinkHonorsTheSlotLimits(unittest.TestCase):
    def test_range_cells_match_the_known_list(self):
        seen = set()
        for label, factory in M.SUBJECTS:
            for name, slot in M.scalar_fields(factory):
                for kind in ("below", "above", "nan"):
                    r = M.run_range_cell(factory, name, slot, kind)
                    if r:
                        seen.add((name, kind))
                        self.assertIn((name, kind), KNOWN_RANGE,
                                      f"{label}.{name} {kind}: {r[1]}")
        stale = KNOWN_RANGE - seen
        self.assertEqual(stale, set(), "fixed: remove these from KNOWN_RANGE")


class TestNonFiniteScalarLink(unittest.TestCase):
    def test_nan_and_inf_raise_like_a_write(self):
        from scena import Point, State
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                st = State(name=f"nf{id(bad)}{bad}")
                st.v = 1.0
                p = Point(0, 0)
                p["x"] @= (lambda: st.v + 0.0)
                self.assertEqual(p.x, 1.0)
                st.v = bad
                with self.assertRaises(ValueError):
                    p.x
                st.v = 2.0
                self.assertEqual(p.x, 2.0)       # the next read recovers

    def test_a_pair_store_is_not_checked(self):
        from scena import Vec2
        v = Vec2(0, 0)
        v << (float("nan"), 0.0)
        self.assertNotEqual(v.x, v.x)


class TestOneCoercionForEveryPath(unittest.TestCase):
    """Item 1 of Track C: a slot's rules (finite, magnitude, range) are applied
    by one coercion on every path — author ``=``, constructor, batch refresh,
    link pull — instead of per-class ``_write_field`` overrides that only the
    author path ran (D14 / D16 and the constructor NaN were that gap)."""

    def _writable_scalars(self):
        for label, factory in M.SUBJECTS:
            for name, slot in M.scalar_fields(factory):
                obj = factory()
                try:
                    setattr(obj, name, getattr(obj, name))
                except Exception:
                    continue                  # Derivate / not plain-writable here
                yield label, factory, name, slot

    def test_the_constructor_refuses_what_a_write_refuses(self):
        from scena.state import _init_scalar
        for label, factory, name, slot in self._writable_scalars():
            for bad in (float("nan"), float("inf")):
                with self.subTest(subject=label, field=name, value=bad):
                    with self.assertRaises(ValueError):
                        setattr(factory(), name, bad)
                    with self.assertRaises(ValueError):
                        _init_scalar(factory(), name, bad)

    def test_assigning_a_function_names_the_link(self):
        from scena.state import CallableAssignError
        for label, factory, name, slot in self._writable_scalars():
            with self.subTest(subject=label, field=name):
                with self.assertRaises(CallableAssignError):
                    setattr(factory(), name, lambda: 1.0)

    def test_a_batch_refresh_clamps_a_negative_size(self):
        for label, factory, name, slot in self._writable_scalars():
            if not slot.magnitude:
                continue
            with self.subTest(subject=label, field=name):
                obj = factory()
                with obj._batch_update():
                    setattr(obj, name, -3.0)
                self.assertEqual(obj.__dict__.get(name), 0.0)

    def test_no_write_override_validates_on_its_own(self):
        # Every _write_field override, and why it exists. A new one that checks
        # a value belongs in the slot's metadata instead.
        import ast
        allowed = {
            ("state.py", "State"): "State cells (not slots)",
            ("state.py", "Container"): "the base write path",
            ("entity.py", "Graphic"): "property-backed angle / scale / enabled",
            ("shapes.py", "_DerivedRotationRoute"): "a derived heading writes through rotate_to",
            ("shapes.py", "Circle"): "keeps the pose in step after an angle write",
            ("track.py", "Track"): "re-bakes after a radius write",
        }
        from source_support import iter_files
        found = set()
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scena")
        for path in iter_files(root, ".py"):
            fname = os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
                if any(isinstance(f, ast.FunctionDef) and f.name == "_write_field" for f in cls.body):
                    found.add((fname, cls.name))
        self.assertEqual(sorted(found - set(allowed)), [],
                         "a _write_field override: put the rule on the ScalarSlot")
        self.assertEqual(sorted(set(allowed) - found), [], "stale entry")


class TestAnchorRefusesEveryLink(unittest.TestCase):
    """An Anchor is dragged (``draggable``): every inbound link is refused,
    and the refusal installs nothing (geometry campaign, H6)."""

    def test_every_field_and_the_whole_object(self):
        from scena import Anchor, State
        from scena.state import LinkedAttributeError, get_scena_system
        st = State(name="anchorlinks")
        st.v = (3.0, 4.0)
        st.s = 2.0
        import gc
        a = Anchor(1, 2)
        g = get_scena_system().dependency_graph
        gc.collect()        # the count includes garbage; a collection mid-test would move it
        before = (len(list(g.nodes)), float(a.x), float(a.y), len(list(a._iter_subtree())))
        targets = [(n, pair) for n, pair in M.field_names(a)]
        self.assertTrue(targets)
        for name, pair in targets:
            with self.assertRaises(LinkedAttributeError, msg=name):
                a[name] @= (lambda: (st.v[0], st.v[1])) if pair else (lambda: st.s + 0.0)
        with self.assertRaises(LinkedAttributeError):
            a @= lambda: (st.v[0], st.v[1])
        gc.collect()
        after = (len(list(g.nodes)), float(a.x), float(a.y), len(list(a._iter_subtree())))
        self.assertEqual(after, before, "a refused link left something behind")
        a.destroy()


class TestEveryReactiveClassIsDriven(unittest.TestCase):
    def test_no_reactive_class_without_a_subject_or_a_reason(self):
        classes = set(M.reactive_classes())
        missing = classes - M.COVERED - set(M.NOT_DRIVEN)
        self.assertEqual(missing, set(), "add a SUBJECTS factory (or a NOT_DRIVEN reason)")

    def test_the_lists_do_not_go_stale(self):
        classes = set(M.reactive_classes())
        self.assertEqual((M.COVERED | set(M.NOT_DRIVEN)) - classes, set())

    def test_every_subject_builds(self):
        for label, factory in M.SUBJECTS:
            with self.subTest(subject=label):
                self.assertIsNotNone(factory())


class TestCanaries(unittest.TestCase):
    """The matrix must catch the bugs that motivated it (Testing Design D12-D14)."""

    def _subject(self, label):
        return [(l, f) for l, f in M.SUBJECTS if l == label]

    def test_stale_vec2_length_and_angle_are_caught(self):
        from diff_support import assert_catches
        from scena import Vec2
        assert_catches(
            self, "test_reactive_matrix.TestCanaryTargets.test_vec2",
            [(Vec2, "_sync_computed", lambda self: None)],
            "a raw store that leaves Vec2 length/angle stale")

    def test_a_frozen_linked_spread_is_caught(self):
        from diff_support import assert_catches
        from scena.state import Container

        def legacy(self):
            for n in self._iter_subtree():
                n._dirty = False
        assert_catches(
            self, "test_reactive_matrix.TestCanaryTargets.test_spread",
            [(Container, "_clear_subtree_dirty", legacy)],
            "an owner refresh that marks a linked part clean before it pulls")

    def test_a_heading_link_that_is_not_pulled_is_caught(self):
        from diff_support import assert_catches
        from scena.shapes import _DerivedRotationRoute
        assert_catches(
            self, "test_reactive_matrix.TestCanaryTargets.test_heading",
            [(_DerivedRotationRoute, "_pull_heading", lambda self: None)],
            "a Derivate read before the linked heading was applied (D18)")

    def test_a_whole_link_that_skips_the_refresh_is_caught(self):
        from diff_support import assert_catches
        from scena.state import Container
        assert_catches(
            self, "test_reactive_matrix.TestCanaryTargets.test_whole",
            [(Container, "_refresh_after_raw_store", lambda self: None)],
            "a whole-object pull that leaves live Derivates stale (D19)")

    def test_a_copy_that_keeps_the_old_defining_set_is_caught(self):
        from diff_support import assert_catches
        from scena.state import Container

        def legacy(self, other):
            self.model = other.model
        assert_catches(
            self, "test_reactive_matrix.TestCanaryTargets.test_cross_model",
            [(Container, "_adopt_model_of", legacy)],
            "a copy that switches model but not the Defining set (D21)")

    def test_an_unclamped_track_window_is_caught(self):
        from diff_support import assert_catches
        from scena import Track
        import types
        slot = Track.__dict__["begin"]
        expected = types.SimpleNamespace(
            minimum=slot.minimum, maximum=slot.maximum, magnitude=False)
        saved = (slot.minimum, slot.maximum)
        slot.minimum = slot.maximum = None
        try:
            r = M.run_range_cell(M.SUBJECTS[-1][1], "begin", expected, "above")
        finally:
            slot.minimum, slot.maximum = saved
        self.assertIsNotNone(r, "the clamp cell did not notice a missing maximum")


class TestCanaryTargets(unittest.TestCase):
    """Run only under assert_catches: they must FAIL with the patch applied."""

    def test_vec2(self):
        vec = [(l, f) for l, f in M.SUBJECTS if l == "Vec2"]
        self.assertEqual(_freshness_failures(vec), [])
        for order in M.ORDERS:
            self.assertIsNone(M.run_self_cell(vec[0][1], order))

    def test_heading(self):
        derived = [(l, f) for l, f in M.SUBJECTS if l in (
            "Line p1,p2", "Line p1,dx,dy", "Ellipse focal_points", "Rect spine cap")]
        self.assertEqual(_freshness_failures(derived, reverse=True), [])

    def test_whole(self):
        rects = [(l, f) for l, f in M.SUBJECTS if l in ("Rect center", "Circle", "Line p1,p2")]
        self.assertEqual(_whole_failures(rects), [])

    def test_cross_model(self):
        self.assertEqual(_cross_model_failures({"Rect", "Circle"}), [])

    def test_spread(self):
        self.assertEqual(_freshness_failures(
            [(l, f) for l, f in M.SUBJECTS if l.startswith("Circle")]), [])



class TestLinkValuesAwayFromConstruction(unittest.TestCase):
    """The machine's link step, made exhaustive: every subject × every
    linkable field × link values away from the construction value, read
    against the plain-write twin.

    The matrix above links each field with one value; for a SPINE Rect's
    ``angle`` that value equals the construction heading, so the update's
    heading publish was an unchanged no-op there. A link to 135° made the
    publish go through the linked-pose refusal, and every read raised (found
    by the gate's reactive machine after graphics review batch 4)."""

    def test_every_linkable_field_at_several_values(self):
        import test_hyp_reactive_matrix as H
        from scena import State
        bad, checked = [], 0
        for label, factory in M.SUBJECTS:
            for name, is_pair, slot in H.linkable_of(label, factory):
                for t in (0.125, 0.5, 0.875):
                    pair = H._Pair(label, factory)
                    cell = State(name=f"lv{checked}")
                    cell.v = t
                    try:
                        if name == "@self":
                            pair.subject @= H.formula(cell, name, slot, is_pair)
                        else:
                            pair.subject[name] @= H.formula(cell, name, slot, is_pair)
                    except Exception:  # noqa: BLE001  (the model refuses this link)
                        continue
                    try:
                        H._put(pair.twin, name, is_pair, H.map_value(name, slot, is_pair, t))
                    except Exception:  # noqa: BLE001  (a write the model refuses)
                        continue
                    checked += 1
                    names = [n for n, _, _ in pair.fields]
                    diff = M.diff(M.snapshot_names(pair.subject, names),
                                  M.snapshot_names(pair.twin, names))
                    if diff:
                        bad.append((label, name, t, sorted(diff)[:4]))
        self.assertGreater(checked, 200, "vacuous")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
