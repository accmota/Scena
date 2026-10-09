"""The geometry campaign's axes and covering arrays check themselves.

* ``covering.covering_array`` covers every valid t-tuple (2-wise and 3-wise,
  with and without a constraint), and never emits an invalid row.
* ``geom_axes.K`` reaches every ``_CONSTRUCTOR_SIGNATURES`` row of every
  in-scope class (or lists it in ``ROWS_NOT_BUILT`` with a reason; a stale
  entry fails).
* Every public pose verb (a Graphic method taking ``time=``) is a V step of the
  sequence machine or listed in ``VERBS_NOT_STEPS`` with a reason.
* Every base state, warmth and link configuration applies to at least one kind
  (an axis value no kind can take is a vacuous value).

Testing Design — Geometry campaign.

    python tests/run_tiers.py focused test_geom_axes
"""
from __future__ import annotations

import itertools
import os
import random
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import fresh_world  # noqa: E402

import covering  # noqa: E402
import geom_axes as A  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


class TestCoveringArrays(unittest.TestCase):
    def _axes(self, rng, k, lo=2, hi=5):
        return [(f"a{i}", list(range(rng.randint(lo, hi)))) for i in range(k)]

    def test_every_tuple_is_covered(self):
        rng = random.Random(7)
        for t in (1, 2, 3):
            for _ in range(6):
                axes = self._axes(rng, rng.randint(t, 6))
                rows = covering.covering_array(axes, t)
                self.assertEqual(covering.uncovered_tuples(rows, axes, t), [], (t, axes))

    def test_constraints_are_respected_and_valid_tuples_covered(self):
        rng = random.Random(11)

        def valid(d):
            # a0 == 0 excludes a1 == 1; a2 == 2 excludes a3 == 0.
            if d.get("a0") == 0 and d.get("a1") == 1:
                return False
            if d.get("a2") == 2 and d.get("a3") == 0:
                return False
            return True
        for t in (2, 3):
            for _ in range(5):
                axes = self._axes(rng, 5, 3, 4)
                rows = covering.covering_array(axes, t, valid)
                self.assertTrue(all(valid(r) for r in rows))
                self.assertEqual(covering.uncovered_tuples(rows, axes, t, valid), [])

    def test_smaller_than_the_product(self):
        axes = [(f"a{i}", list(range(5))) for i in range(6)]
        rows = covering.covering_array(axes, 2)
        self.assertLess(len(rows), 5 ** 6 // 50)

    def test_deterministic(self):
        axes = [(f"a{i}", list(range(4))) for i in range(5)]
        self.assertEqual(covering.covering_array(axes, 3), covering.covering_array(axes, 3))

    def test_the_checker_can_fail(self):
        axes = [("a", [0, 1]), ("b", [0, 1])]
        rows = [{"a": 0, "b": 0}, {"a": 1, "b": 1}]
        self.assertEqual(len(covering.uncovered_tuples(rows, axes, 2)), 2)


class TestKindsReachEveryConstructorRow(unittest.TestCase):
    def test_every_row_is_built(self):
        reached = A.signature_reach()
        missing = [r for r in A.every_signature_row()
                   if r not in reached and r not in A.ROWS_NOT_BUILT]
        self.assertFalse(missing, "constructor rows no K builder reaches (add a builder to "
                         f"geom_axes.EXTRA_KINDS or a reason to ROWS_NOT_BUILT): {missing}")

    def test_exclusions_are_not_stale(self):
        reached = A.signature_reach()
        stale = [r for r in A.ROWS_NOT_BUILT if r in reached]
        self.assertFalse(stale, f"ROWS_NOT_BUILT entries K now builds: {stale}")
        rows = set(A.every_signature_row())
        gone = [r for r in A.ROWS_NOT_BUILT if r not in rows]
        self.assertFalse(gone, f"ROWS_NOT_BUILT entries no class declares: {gone}")


class TestEveryPoseVerbIsAStep(unittest.TestCase):
    def test_public_pose_verbs(self):
        import geom_shadow
        steps = {name.split()[0] for name in geom_shadow.STEP_NAMES}
        missing = [v for v in A.public_pose_verbs()
                   if v not in steps and v not in A.VERBS_NOT_STEPS]
        self.assertFalse(missing, f"pose verbs with no V step (add one to geom_shadow.STEPS "
                         f"or a reason to geom_axes.VERBS_NOT_STEPS): {missing}")
        stale = [v for v in A.VERBS_NOT_STEPS if v not in A.public_pose_verbs()]
        self.assertFalse(stale, f"VERBS_NOT_STEPS names no pose verb: {stale}")


class TestAxisValuesApply(unittest.TestCase):
    """Each base state and link configuration applies to some kind."""

    def test_base_states(self):
        applied = {b: 0 for b in A.B}
        with fresh_world() as w:
            for kind in A.K:
                for b in A.B:
                    obj = w.track(A.build(kind))
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        if A.apply_base(b, obj, w) is not None:
                            applied[b] += 1
        self.assertFalse([b for b, n in applied.items() if not n])

    def test_link_configurations(self):
        applied = {name: 0 for name in A.L}
        errors = []
        with fresh_world() as w:
            for kind in A.K:
                for name in A.L:
                    obj = w.track(A.build(kind))
                    try:
                        if A.apply_link(name, obj, w) is not None:
                            applied[name] += 1
                    except Exception as e:  # noqa: BLE001
                        errors.append((kind, name, type(e).__name__))
        self.assertFalse(errors, "a link configuration raised where it claims to apply")
        self.assertFalse([n for n, c in applied.items() if not c])

    def test_warmth_reads_never_raise_out(self):
        with fresh_world() as w:
            for kind in A.K:
                for name, read in A.W.items():
                    read(w.track(A.build(kind)))


if __name__ == "__main__":
    unittest.main()
