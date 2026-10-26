"""Scale about the center of a size-defined model (D28 in Testing Design).

``scale =``, ``scale_to`` and every scale tween about the center of a shape
placed by its center write the sizes and the pose store alone
(``shapes._scale_about_center_fast``); the general ``scale_by`` re-derived the
center twice, rewrote it unchanged and batched the part subtree (~10x a size
write). The oracle is the same build with ``shapes._SCALE_CENTER_FAST = False``.

* ``TestCensus``: the kinds that opt in (``_center_scale_sizes``) are the
  center-placed size models of ``geometry_support.KINDS``; every one of them is
  in the differential below (a new kind that opts in is tested by default).
* ``TestFastPathIsTaken``: on those kinds, unlinked, the kind's ``scale_by``
  never runs for ``scale =`` / ``scale_to`` / a tween (the cost class).
* ``TestFastEqualsGeneral``: random scale / pose sequences on twins, one with
  the switch off; same pose, collision geometry, public reads, pose revision
  bumps and errors after every step.
* ``TestLinkedShapesKeepTheGeneralPath``: links on the shape (its ``scale``, a
  size, a box formula, an outbound link, ``force=``) behave as the general
  path does.
* Canary: a fast path off by 0.1 % fails the differential.

    python tests/run_tiers.py focused test_scale_center_fast
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import assert_same, fingerprint, module_flag  # noqa: E402
from test_diff_pose import _public_reads  # noqa: E402
from hypothesis_support import quiet  # noqa: E402
from hypothesis import given, note, strategies as hst  # noqa: E402

from scena import Circle, Point, Rect, Square, State, clock  # noqa: E402
from scena.process import reset_process_scheduler, tick_processes  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()

SHAPES = "scena.shapes"


def _kinds():
    import geometry_support as G
    return G.KINDS, G.build


def _fast_kinds():
    """Every registry kind that opts in, built fresh and unlinked."""
    kinds, build = _kinds()
    out = []
    for kind in sorted(kinds):
        if kind.startswith("Box"):
            continue                    # a measuring Box is no actor: no pose scale
        with quiet():
            obj = build(kind)
        try:
            hook = getattr(type(obj), "_center_scale_sizes", None)
            if hook is not None and obj._center_scale_sizes() is not None:
                out.append(kind)
        finally:
            obj.destroy()
    return out


FAST_KINDS = _fast_kinds()
# Ellipse from_rect starts linked to its Rect: it opts in by model and takes
# the general path while the link stands (the check is made per write).
UNLINKED_FAST_KINDS = [k for k in FAST_KINDS if k != "Ellipse from_rect"]

# What opts in, by kind: a model placed by its center whose scale only
# changes sizes. A kind added here must add its hook, and the reverse.
EXPECTED = {
    "Circle arc", "Circle center_radius",
    "Ellipse center_wh", "Ellipse from_rect",
    "Rect center_wh", "Square center_length",
    "RegularPolygon center_radius", "RegularPolygon center_side",
    "Triangle center_radius", "Triangle center_radius ship",
    "Triangle center_side", "Triangle center_side wide",
}


def _build(kind):
    _, build = _kinds()
    with quiet():
        return build(kind)


def _tick(dt: float) -> None:
    clock.advance(dt)
    tick_processes()


def _pose_rev(obj) -> int:
    cell = obj.__dict__.get("_pose_cell")
    return cell[0] if cell is not None else 0


# ---------------------------------------------------------------------------
# Census
# ---------------------------------------------------------------------------

class TestCensus(unittest.TestCase):
    def test_the_size_models_placed_by_their_center_opt_in(self):
        self.assertEqual(set(FAST_KINDS), EXPECTED)

    def test_a_fresh_opted_kind_is_unlinked(self):
        for kind in FAST_KINDS:
            obj = _build(kind)
            try:
                if kind == "Ellipse from_rect":
                    self.assertTrue(obj._requires_pull_invalidate())
                else:
                    self.assertFalse(obj._requires_pull_invalidate(), kind)
            finally:
                obj.destroy()


# ---------------------------------------------------------------------------
# The cost class: the general verb never runs
# ---------------------------------------------------------------------------

def _refuse(*_a, **_k):
    raise AssertionError("the general scale_by ran")


class TestFastPathIsTaken(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()

    def tearDown(self):
        reset_process_scheduler()

    def test_scale_assign_and_scale_to(self):
        for kind in UNLINKED_FAST_KINDS:
            obj = _build(kind)
            try:
                with mock.patch.object(type(obj), "scale_by", _refuse):
                    obj.scale = 1.5
                    obj.scale_to(0.25)
                    obj.scale = 0.0                 # a collapse comes back
                    obj.scale = 2.0
                self.assertEqual(obj.scale, 2.0, kind)
                self.assertFalse(obj._requires_pull_invalidate(), kind)
            finally:
                obj.destroy()

    def test_tweens(self):
        for kind in UNLINKED_FAST_KINDS:
            obj = _build(kind)
            try:
                with mock.patch.object(type(obj), "scale_by", _refuse):
                    obj.scale_to(2.0, time=0.2)
                    for _ in range(15):
                        _tick(1 / 60)
                    obj.scale_to(1.0, time=0.2)
                    for _ in range(15):
                        _tick(1 / 60)
                self.assertAlmostEqual(obj.scale, 1.0, msg=kind)
                self.assertFalse(obj._requires_pull_invalidate(), kind)
            finally:
                obj.destroy()

    def test_scale_by_and_a_pivot_keep_the_general_path(self):
        # Only the center scale of ``scale =`` / ``scale_to`` is fast; the
        # patched verb proves the other calls still reach it.
        obj = Rect(center=(0, 0), width=10, height=6)
        try:
            with mock.patch.object(Rect, "scale_by", _refuse):
                with self.assertRaises(AssertionError):
                    obj.scale_to(2.0, about=(5, 5))
                with self.assertRaises(AssertionError):
                    obj.scale_to(2.0, force=True)
        finally:
            obj.destroy()

    def test_the_switch_off_is_the_general_path(self):
        obj = Rect(center=(0, 0), width=10, height=6)
        try:
            with module_flag(SHAPES, "_SCALE_CENTER_FAST", False), \
                    mock.patch.object(Rect, "scale_by", _refuse):
                with self.assertRaises(AssertionError):
                    obj.scale = 2.0
        finally:
            obj.destroy()


# ---------------------------------------------------------------------------
# Differential: switch on vs off
# ---------------------------------------------------------------------------

value = hst.sampled_from([0.0, 1e-9, 0.5, 1.0, 1.25, 3.0])
factor = hst.sampled_from([0.5, 0.8, 1.0, 1.25, 2.0])
coord = hst.integers(-200, 200).map(float)

OPS = hst.one_of(
    hst.tuples(hst.just("scale="), value),
    hst.tuples(hst.just("scale_to"), value),
    hst.tuples(hst.just("scale_to center"), value),
    hst.tuples(hst.just("scale_by"), factor),
    hst.tuples(hst.just("nested"), value),
    hst.tuples(hst.just("tween"), value),
    hst.tuples(hst.just("tick"), hst.sampled_from([0.05, 0.1, 0.25])),
    hst.tuples(hst.just("move_to"), coord, coord),
    hst.tuples(hst.just("rotate_by"), hst.integers(-90, 90).map(float)),
    hst.tuples(hst.just("flip_x")),
)


def apply(obj, op) -> None:
    kind = op[0]
    if kind == "scale=":
        obj.scale = op[1]
    elif kind == "scale_to":
        obj.scale_to(op[1])
    elif kind == "scale_to center":
        # ``about=`` the center: the general path, on both twins.
        obj.scale_to(op[1], about=obj._center_xy())
    elif kind == "scale_by":
        obj.scale_by(op[1])
    elif kind == "nested":
        # Under the shape's own batch (an outer verb's): no update until it ends.
        with obj._no_update():
            obj.scale = op[1]
        obj.update()
    elif kind == "tween":
        obj.scale_to(max(op[1], 0.1), time=0.2)
    elif kind == "move_to":
        obj.move_to(op[1], op[2])
    elif kind == "rotate_by":
        obj.rotate_by(op[1])
    elif kind == "flip_x":
        obj.flip_x = not obj.flip_x
    else:
        raise AssertionError(kind)


def _outcome(fn, *args):
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__
    return None


def _step(obj, op, fast: bool):
    with module_flag(SHAPES, "_SCALE_CENTER_FAST", fast), quiet():
        before = _pose_rev(obj)
        out = _outcome(apply, obj, op)
        return out, _pose_rev(obj) != before


def _public(obj) -> dict:
    return _public_reads(obj)


class TestFastEqualsGeneral(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()

    def tearDown(self):
        reset_process_scheduler()

    @given(kind=hst.sampled_from(FAST_KINDS), ops=hst.lists(OPS, min_size=1, max_size=10))
    def test_same_shape_after_every_step(self, kind, ops):
        reset_process_scheduler()
        a, b = _build(kind), _build(kind)
        try:
            for i, op in enumerate(ops):
                note(f"step {i}: {op}")
                what = f"{kind} step {i} {op}"
                if op[0] == "tick":
                    # One scheduler ticks both twins' tweens (the fast path:
                    # a tick step is ``scale_to``, compared op by op above).
                    with quiet():
                        _tick(op[1])
                    assert_same(self, fingerprint(a), fingerprint(b), what)
                    continue
                ea, moved_a = _step(a, op, True)
                eb, moved_b = _step(b, op, False)
                self.assertEqual(ea, eb, f"{what}: the paths raise differently")
                # A scale that changed the shape bumps the pose revision on
                # both (the collision proxy and the cull box rebuild).
                self.assertEqual(moved_a, moved_b, f"{what}: pose revision")
                assert_same(self, fingerprint(a), fingerprint(b), what)
            with quiet():
                _tick(1.0)                          # finish every tween
            if kind in UNLINKED_FAST_KINDS:      # no vacuous pass: A took the fast path
                self.assertFalse(a._requires_pull_invalidate(), f"{kind}: twin A left the fast path")
            assert_same(self, fingerprint(a), fingerprint(b), f"{kind} end")
            assert_same(self, _public(a), _public(b), f"{kind} public reads")
        finally:
            a.destroy()
            b.destroy()

    def test_a_fast_scale_moves_the_collision_key_and_the_pose_revision(self):
        # A trusted body keeps its collision proxy while its pose revision
        # stands (``collision._POSE_REV_SKIP``), and the snapshot cache keys
        # on the pose key: a fast scale that moved neither would collide at
        # the old size.
        col = sys.modules["scena.collision"]
        for kind in UNLINKED_FAST_KINDS:
            obj = _build(kind)
            try:
                with quiet():
                    key, rev = col._collision_pose_key(obj), _pose_rev(obj)
                    obj.scale = 2.5
                    self.assertNotEqual(col._collision_pose_key(obj), key, kind)
                    self.assertNotEqual(_pose_rev(obj), rev, kind)
            finally:
                obj.destroy()


# ---------------------------------------------------------------------------
# Links keep the general path's behaviour
# ---------------------------------------------------------------------------

def _both(fn):
    """``fn()`` with the switch on and off: (outcome, result) pairs."""
    out = []
    for fast in (True, False):
        with module_flag(SHAPES, "_SCALE_CENTER_FAST", fast), quiet():
            try:
                out.append((None, fn()))
            except Exception as exc:  # noqa: BLE001
                out.append((type(exc).__name__, str(exc)))
    return out


class TestLinkedShapesKeepTheGeneralPath(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        self.st = State()

    def tearDown(self):
        reset_process_scheduler()

    def _same(self, fn):
        fast, general = _both(fn)
        self.assertEqual(fast, general)
        return fast

    def test_a_linked_scale_refuses(self):
        def go():
            r = Rect(center=(0, 0), width=10, height=6)
            r["scale"] @= lambda: self.st.s
            self.st.s = 2.0
            try:
                r.scale = 3.0
            finally:
                r.destroy()
        self.st.s = 1.0
        outcome, _ = self._same(go)
        self.assertIsNotNone(outcome)

    def test_a_linked_size_refuses(self):
        def go():
            sq = Square(center=(0, 0), length=10)
            sq["length"] @= lambda: self.st.w
            try:
                sq.scale = 2.0
            finally:
                sq.destroy()
        self.st.w = 10.0
        outcome, _ = self._same(go)
        self.assertEqual(outcome, "LinkedAttributeError")

    def test_force_unlinks_a_linked_size(self):
        def go():
            c = Circle(center=(0, 0), radius=5)
            c["radius"] @= lambda: self.st.w
            c.scale_to(2.0, force=True)
            try:
                return c.radius, c.scale
            finally:
                c.destroy()
        self.st.w = 5.0
        outcome, result = self._same(go)
        self.assertIsNone(outcome)
        self.assertEqual(result, (10.0, 2.0))

    def test_a_box_formula_refuses(self):
        def go():
            ref = Rect(center=(0, 0), width=10, height=6)
            r = Rect(box=lambda: ref)
            try:
                r.scale = 2.0
            finally:
                r.destroy()
                ref.destroy()
        outcome, _ = self._same(go)
        self.assertIsNotNone(outcome)

    def test_an_outbound_link_follows(self):
        def go():
            r = Rect(center=(3, 4), width=10, height=6)
            p = Point(0, 0)
            p["x"] @= lambda: r.width
            q = Point(0, 0)
            q @= r.center
            r.scale = 2.0
            try:
                return p.x, (q.x, q.y), r.scale
            finally:
                p.destroy()
                q.destroy()
                r.destroy()
        outcome, result = self._same(go)
        self.assertIsNone(outcome)
        self.assertEqual(result, (20.0, (3.0, 4.0), 2.0))

    def test_a_square_reads_its_mirrors_after_a_fast_scale(self):
        # Square's width / height are Derivate mirrors of ``length``: the fast
        # path writes ``length`` only, and a read must not see the old side.
        def go():
            sq = Square(center=(0, 0), length=10)
            sq.scale = 3.0
            sq.scale = 1.5
            try:
                return sq.length, sq.width, sq.height, sq.scale
            finally:
                sq.destroy()
        outcome, result = self._same(go)
        self.assertIsNone(outcome)
        self.assertEqual(result, (15.0, 15.0, 15.0, 1.5))


# ---------------------------------------------------------------------------
# Canary
# ---------------------------------------------------------------------------

class TestScaleFastCanary(unittest.TestCase):
    def test_catches_a_size_error_on_the_fast_path(self):
        from diff_support import assert_catches
        orig = sys.modules[SHAPES]._scale_about_center_fast

        def skewed(obj, geom, store):
            return orig(obj, geom * 1.001, store)

        assert_catches(
            self, "test_scale_center_fast.TestFastEqualsGeneral.test_same_shape_after_every_step",
            [(SHAPES, "_scale_about_center_fast", skewed)],
            "a 0.1 % size error on the center scale fast path")


if __name__ == "__main__":
    unittest.main()
