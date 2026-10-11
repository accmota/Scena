"""Boxed cells (``st.x``, widget ``.data``) take the whole numeric protocol.

Every operator reads the payload and returns a plain value (never a cell), so
``st.f ** 3`` behaves like ``-1.5 ** 3`` and an augmented write
(``st.f **= 2``) takes the number into the same cell. The completeness guard
below fails when Python grows an operator a cell does not answer, or when one
is dropped, so the bug class ("Attribute has + but not **") stays closed.

Run headless:

    python -m unittest tests.test_attribute_operators -v
"""
from __future__ import annotations

import math
import operator
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.state import Attribute, State


# (name, function) for every binary arithmetic operator a cell answers.
_BINARY = [
    ("+", operator.add),
    ("-", operator.sub),
    ("*", operator.mul),
    ("/", operator.truediv),
    ("//", operator.floordiv),
    ("%", operator.mod),
    ("**", operator.pow),
    ("divmod", divmod),
]

# Integer bitwise operators (payload must be an int).
_BITWISE = [
    ("&", operator.and_),
    ("|", operator.or_),
    ("^", operator.xor),
]

# Numeric-protocol dunders deliberately not on Attribute, with the reason.
_EXCLUDED = {
    "__lshift__": "Container.__lshift__ is takein (cell << 3 writes 3)",
    "__rlshift__": "shifts stay out as a pair with <<",
    "__rshift__": "shifts stay out as a pair with <<",
    "__rrshift__": "shifts stay out as a pair with <<",
    "__matmul__": "@ reads as a link in Scena (@=)",
    "__rmatmul__": "@ reads as a link in Scena (@=)",
}

# In-place forms are left to Python's fallback (x = x op y), which goes
# through the owner's setter and keeps the cell's identity.
_INPLACE = {
    "__iadd__", "__isub__", "__imul__", "__itruediv__", "__ifloordiv__",
    "__imod__", "__ipow__", "__iand__", "__ior__", "__ixor__",
    "__ilshift__", "__irshift__", "__imatmul__",
}

_PAYLOADS = [-1.5, 2.5, 7, -3, 0.25]
_OTHERS = [3, -2, 0.5, 4.0]


def _numeric_protocol_dunders() -> set[str]:
    """Every arithmetic dunder ``float`` / ``int`` / ``complex`` answer (the protocol)."""
    names = set()
    for typ in (float, int, complex):
        for name in dir(typ):
            if not (name.startswith("__") and name.endswith("__")):
                continue
            if name in {
                "__abs__", "__add__", "__radd__", "__sub__", "__rsub__",
                "__mul__", "__rmul__", "__truediv__", "__rtruediv__",
                "__floordiv__", "__rfloordiv__", "__mod__", "__rmod__",
                "__divmod__", "__rdivmod__", "__pow__", "__rpow__",
                "__neg__", "__pos__", "__invert__",
                "__and__", "__rand__", "__or__", "__ror__", "__xor__", "__rxor__",
                "__lshift__", "__rlshift__", "__rshift__", "__rrshift__",
                "__round__", "__trunc__", "__floor__", "__ceil__",
                "__float__", "__int__", "__index__", "__bool__", "__complex__",
                "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
            }:
                names.add(name)
    return names


class TestOperatorSetComplete(unittest.TestCase):
    def test_every_numeric_dunder_is_answered_or_excluded(self):
        missing = []
        for name in sorted(_numeric_protocol_dunders()):
            if name in _EXCLUDED:
                continue
            if name == "__ne__":
                # object.__ne__ inverts __eq__; checked in TestComparisons.
                continue
            impl = getattr(Attribute, name, None)
            if impl is None or impl is getattr(object, name, None):
                missing.append(name)
        self.assertEqual(missing, [], f"Attribute does not answer {missing}")

    def test_excluded_dunders_stay_off(self):
        for name in ("__rlshift__", "__rshift__", "__rrshift__", "__matmul__", "__rmatmul__"):
            self.assertFalse(hasattr(Attribute, name), name)
        # << is takein on every Container, not a shift.
        a = Attribute(4)
        self.assertIs(a << 3, a)
        self.assertEqual(a.value, 3)

    def test_no_inplace_dunders(self):
        defined = sorted(n for n in _INPLACE if n in vars(Attribute))
        self.assertEqual(defined, [], "augmented writes must fall back to x = x op y")


class TestBinaryOperators(unittest.TestCase):
    def _check(self, sym, fn, a, b):
        try:
            want = fn(a, b)
        except ZeroDivisionError:
            with self.assertRaises(ZeroDivisionError):
                fn(Attribute(a), b)
            return
        for got in (fn(Attribute(a), b), fn(a, Attribute(b)), fn(Attribute(a), Attribute(b))):
            self.assertNotIsInstance(got, Attribute, sym)
            if isinstance(want, tuple):
                self.assertEqual(got, want, f"{a!r} {sym} {b!r}")
            elif isinstance(want, complex):
                self.assertAlmostEqual(got, want, msg=f"{a!r} {sym} {b!r}")
            else:
                self.assertEqual(type(got), type(want), f"{a!r} {sym} {b!r}")
                if math.isnan(want):
                    self.assertTrue(math.isnan(got))
                else:
                    self.assertEqual(got, want, f"{a!r} {sym} {b!r}")

    def test_matches_payload(self):
        for sym, fn in _BINARY:
            for a in _PAYLOADS:
                for b in _OTHERS:
                    with self.subTest(op=sym, a=a, b=b):
                        self._check(sym, fn, a, b)

    def test_bitwise_matches_payload(self):
        for sym, fn in _BITWISE:
            for a in (6, -3, 0):
                for b in (3, 5, -1):
                    with self.subTest(op=sym, a=a, b=b):
                        self._check(sym, fn, a, b)

    def test_zero_division_propagates(self):
        for fn in (operator.truediv, operator.floordiv, operator.mod, divmod):
            with self.subTest(fn=fn):
                with self.assertRaises(ZeroDivisionError):
                    fn(Attribute(3), 0)
                with self.assertRaises(ZeroDivisionError):
                    fn(3, Attribute(0))

    def test_three_argument_pow(self):
        self.assertEqual(pow(Attribute(3), 4, 5), pow(3, 4, 5))
        self.assertEqual(pow(Attribute(3), Attribute(4), Attribute(5)), pow(3, 4, 5))
        self.assertNotIsInstance(pow(Attribute(3), 4, 5), Attribute)

    def test_non_numeric_payload_raises_type_error(self):
        word = Attribute("abc")
        for sym, fn in _BINARY:
            if sym in ("*",):
                continue  # "abc" * 3 is str repetition, like the payload
            with self.subTest(op=sym):
                with self.assertRaises(TypeError):
                    fn(word, 2)
                with self.assertRaises(TypeError):
                    fn(2, word)

    def test_string_payload_keeps_its_own_operators(self):
        self.assertEqual(Attribute("ab") * 2, "abab")
        self.assertEqual(Attribute("%d pts") % 7, "7 pts")
        self.assertEqual(Attribute("a") + "b", "ab")


class TestUnaryAndIntegral(unittest.TestCase):
    def test_unary_match_payload(self):
        for v in _PAYLOADS:
            with self.subTest(v=v):
                self.assertEqual(-Attribute(v), -v)
                self.assertEqual(+Attribute(v), +v)
                self.assertEqual(abs(Attribute(v)), abs(v))
        self.assertEqual(~Attribute(5), ~5)

    def test_round(self):
        for v in (2.5, 3.5, -1.5, 2.675, 7):
            with self.subTest(v=v):
                got = round(Attribute(v))
                self.assertEqual(got, round(v))
                self.assertIs(type(got), int)
                self.assertEqual(round(Attribute(v), 2), round(v, 2))
                self.assertEqual(round(Attribute(v), Attribute(1)), round(v, 1))

    def test_trunc_floor_ceil(self):
        for v in (-1.5, 2.5, 7, -3, 1e20):
            with self.subTest(v=v):
                for fn in (math.trunc, math.floor, math.ceil):
                    got = fn(Attribute(v))
                    self.assertEqual(got, fn(v))
                    self.assertIs(type(got), int)

    def test_conversions(self):
        a = Attribute(-1.5)
        self.assertEqual(float(a), -1.5)
        self.assertEqual(int(a), -1)
        self.assertEqual(complex(a), complex(-1.5))
        # A complex payload (st.f ** 0.5 with f < 0) converts too; float() would not.
        self.assertEqual(complex(Attribute((-2.25) ** 0.5)), (-2.25) ** 0.5)
        self.assertEqual(list(range(Attribute(3))), [0, 1, 2])


class TestComparisons(unittest.TestCase):
    def test_all_six_both_sides(self):
        cases = [
            (operator.eq, "=="), (operator.ne, "!="), (operator.lt, "<"),
            (operator.le, "<="), (operator.gt, ">"), (operator.ge, ">="),
        ]
        for fn, sym in cases:
            for a in (-1.5, 2, 3.0):
                for b in (-1.5, 2, 4):
                    with self.subTest(op=sym, a=a, b=b):
                        want = fn(a, b)
                        self.assertIs(fn(Attribute(a), b), want)
                        self.assertIs(fn(a, Attribute(b)), want)
                        self.assertIs(fn(Attribute(a), Attribute(b)), want)


class TestStateCells(unittest.TestCase):
    """The author surface: ``st.x`` reads the cell; augmented writes keep it."""

    def setUp(self):
        self.st = State(name="ops_bag")

    def test_issue_repro(self):
        self.st.f = -1.5
        self.assertEqual(self.st.f ** 3, -3.375)
        self.assertEqual(2 ** self.st.f, 2 ** -1.5)
        self.assertEqual(self.st.f % 1, -1.5 % 1)
        self.assertEqual(round(self.st.f), -2)

    def test_augmented_writes_keep_the_cell(self):
        self.st.n = 7
        cell = self.st._resolve_cell("n")
        for op_src, want in (
            ("st.n **= 2", 49), ("st.n //= 5", 9), ("st.n %= 4", 1),
            ("st.n += 0.5", 1.5), ("st.n *= 4", 6.0), ("st.n -= 1", 5.0),
            ("st.n /= 2", 2.5),
        ):
            with self.subTest(step=op_src):
                exec(op_src, {"st": self.st})
                self.assertIs(self.st._resolve_cell("n"), cell, "augmented write replaced the cell")
                self.assertEqual(self.st.n, want)

    def test_formula_reads_pow_and_mod_live(self):
        self.st.f = 2.0
        self.st.y = 0
        st = self.st
        st["y"] @= lambda: (st.f ** 3) % 5
        self.assertEqual(st.y, (2.0 ** 3) % 5)
        st.f = 3.0
        self.assertEqual(st.y, (3.0 ** 3) % 5)


if __name__ == "__main__":
    unittest.main()
