"""Per-frame validators: exact-number fast paths, same results as the full path.

Regression for 2026-09-28 (``balanced-2`` cpu_mix tick 1.10 -> 1.40 ms). The
robustness work (A3-A8 in Testing Design) routed ``move_by`` / ``rotation =``
through ``validate.finite`` / ``_finite_deg``. Correct, but a plain ``float``
took the slow path every call: two ``callable`` probes, ``as_payload`` and an
ABC ``isinstance(numbers.Real)`` -- ``move_by`` 1.19 -> 2.25 us,
``_finite_deg`` 3x per ``rotation =``. Both now test ``type(v) is float / int``
first (the same shortcut ``_coerce_magnitude_slot`` already had).

Two guards: the fast path agrees with the contract on a value table, and a
plain number never reaches the slow-path helpers (so a later edit that drops
the shortcut fails here, not only in a bench pulse).

    python -m unittest tests.test_hot_validators -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from fractions import Fraction
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena import Circle, Rect, init  # noqa: E402
from scena import validate  # noqa: E402
from scena import shapes  # noqa: E402


class _MyFloat(float):
    pass


class _MyInt(int):
    pass


# (value, expected float or exception type) under finite()'s contract.
_TABLE = [
    (0.0, 0.0), (-1.5, -1.5), (1e308, 1e308), (5e-324, 5e-324),
    (7, 7.0), (-3, -3.0), (0, 0.0),
    (_MyFloat(2.5), 2.5), (_MyInt(4), 4.0), (Fraction(1, 4), 0.25),
    (math.nan, ValueError), (math.inf, ValueError), (-math.inf, ValueError),
    (_MyFloat("nan"), ValueError),
    (True, TypeError), (False, TypeError),
    ("3", TypeError), (None, TypeError), ((1, 2), TypeError), (1j, TypeError),
]


class TestFiniteContract(unittest.TestCase):
    def test_table(self):
        for value, want in _TABLE:
            with self.subTest(value=value):
                if isinstance(want, type) and issubclass(want, Exception):
                    with self.assertRaises(want):
                        validate.finite(value, "x")
                else:
                    got = validate.finite(value, "x")
                    self.assertIs(type(got), float)
                    self.assertEqual(got, want)

    def test_formula_passes_through(self):
        fn = lambda: 1.0  # noqa: E731
        self.assertIs(validate.finite(fn, "x"), fn)

    def test_message_unchanged_for_non_finite_float(self):
        with self.assertRaises(ValueError) as ctx:
            validate.finite(math.inf, "move_by dx")
        self.assertIn("move_by dx must be a finite number", str(ctx.exception))


class TestFiniteDegContract(unittest.TestCase):
    def test_table(self):
        for value, want in _TABLE:
            with self.subTest(value=value):
                if isinstance(want, type) and issubclass(want, Exception):
                    with self.assertRaises(want):
                        shapes._finite_deg(value, "angle")
                else:
                    got = shapes._finite_deg(value, "angle")
                    self.assertIs(type(got), float)
                    self.assertEqual(got, want)

    def test_formula_is_type_error(self):
        with self.assertRaises(TypeError):
            shapes._finite_deg(lambda: 1.0, "angle")


def _boom(*_a, **_k):
    raise AssertionError("slow path reached for a plain number")


class TestHotPathsStayHot(unittest.TestCase):
    """A plain float / int never reaches the slow-path helpers."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_finite_skips_payload_and_abc(self):
        with mock.patch.object(validate, "as_payload", _boom), \
                mock.patch.object(validate, "_is_formula", _boom):
            self.assertEqual(validate.finite(1.5, "x"), 1.5)
            self.assertEqual(validate.finite(3, "x"), 3.0)

    def test_finite_deg_skips_finite(self):
        with mock.patch.object(shapes, "finite", _boom), \
                mock.patch.object(validate, "finite", _boom):
            self.assertEqual(shapes._finite_deg(33.0, "angle"), 33.0)
            self.assertEqual(shapes._finite_deg(-90, "angle"), -90.0)

    def test_per_frame_verbs_stay_on_the_fast_path(self):
        objs = (Circle(center=(10.0, 10.0), radius=3), Rect(center=(0.0, 0.0), width=6, height=4))
        try:
            with mock.patch.object(validate, "as_payload", _boom), \
                    mock.patch.object(validate, "_is_formula", _boom):
                for obj in objs:
                    with self.subTest(kind=type(obj).__name__):
                        obj.move_by(0.5, -0.25)
                        obj.move_by(2, 3)
                        obj.angle = 45.0
                        obj.rotate_by(-15)
                        self.assertAlmostEqual(float(obj.angle) % 360.0, 30.0)
        finally:
            for obj in objs:
                obj.destroy()


if __name__ == "__main__":
    unittest.main()
