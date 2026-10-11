"""Reactive matrix, every cell: subject x field x write path x read order.

The heavy half of ``test_reactive_matrix`` (the guards, canaries and canary
targets stay there, in quick). Every ``reactive_matrix_support.SUBJECTS``
factory, every linked field, every path and every read order reads like the
same field written with ``=`` (I1, I6), with the Derivates read after and
before the linked field, and through a whole-object link (D19). ``SLOW``
(~20 s alone at ``dev``): gate and deep run it (Testing Design, "Test tiers").

    python tests/run_tiers.py focused test_reactive_matrix_cells
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

import reactive_matrix_support as M  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made

# (subject, field) pairs that read stale when the Derivates are read BEFORE the
# linked field after the source moved (reversed read order). SHRINK-ONLY: a fix
# removes its entry, and an entry that now passes fails the suite.
# Empty since D18: a Line with a linked, derived heading pulls the heading
# before any read of the points it rewrites.
KNOWN_STALE_READ_ORDER = frozenset()


class TestLinkReadsLikeWrite(unittest.TestCase):
    def test_every_subject_field_path_and_order(self):
        bad = M.freshness_failures(M.SUBJECTS)
        self.assertEqual(bad, [], "linked vs written: (subject, field, path, order, diff)")

    def test_reading_derivates_before_the_linked_field(self):
        bad = M.freshness_failures(M.SUBJECTS, reverse=True)
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


class TestWholeObjectLink(unittest.TestCase):
    """``d @= s`` / ``d @= lambda: s``: every name of d reads like s after s
    changes, whatever was read before (D19)."""

    def test_every_subject_field_and_order(self):
        self.assertEqual(M.whole_failures(M.SUBJECTS), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
