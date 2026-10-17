"""Vec2 algebra: black-box properties, inequalities, degenerate bases.

Testing Design, "Vec2 battery". The algebra had no property test (the review
found ``cross``, ``perp_*``, ``angle_to``, ``reflect``, ``project``,
``reject``, ``clamp_length`` and ``to_array`` called by no test at all). Each
property here needs no expected value:

* **exact identities** on integer-valued vectors, where float arithmetic is
  exact (commutativity, associativity, ``dot`` / ``cross`` symmetry, ``perp``);
* **identities within a few ULP** on general floats (rotation keeps length,
  ``project + reject == v``, a reflection twice is the identity);
* **inequalities** (triangle, reverse triangle, Cauchy–Schwarz, the range of
  ``angle`` and ``angle_to``, ``clamp_length`` bounds);
* **twins** that must agree to the bit: an operator and its tuple form, an
  in-place op and its pure form, a method and its alias;
* **author errors only**: every operation, given junk, returns a finite
  vector or raises a Scena error with a Scena message.

    python -m unittest tests.test_vec2_algebra -v
"""
from __future__ import annotations

import inspect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import assume, given, strategies as hst  # noqa: E402

import hypothesis_support as hs  # noqa: E402
from scena import Vec2, init, vec_from_angle  # noqa: E402

# Integer-valued coordinates: sums, products and dot / cross are exact.
exact = hst.integers(min_value=-1000, max_value=1000).map(float)
# General coordinates: far from overflow (|x|² stays finite) and from
# subnormals (a length of 1e-300 squares to 0).
coord = hst.one_of(
    hst.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    hst.integers(min_value=-1000, max_value=1000).map(float),
).filter(lambda c: c == 0.0 or abs(c) > 1e-6)
angle = hst.floats(min_value=-1080.0, max_value=1080.0, allow_nan=False, allow_infinity=False)


@hst.composite
def vecs(draw, c=coord):
    return Vec2(draw(c), draw(c))


@hst.composite
def nonzero(draw, c=coord):
    v = draw(vecs(c))
    assume(v.length > 1e-3)
    return v


def xy(v):
    return (v.x, v.y)


def close(a, b, scale=1.0, ulps=64):
    """Within a few ULP of the operands' magnitude (``scale``)."""
    tol = ulps * math.ulp(max(1.0, abs(scale)))
    return abs(a - b) <= tol


def close_xy(a, b, scale=1.0, ulps=64):
    return close(a.x, b.x, scale, ulps) and close(a.y, b.y, scale, ulps)


def mag(*vs):
    return max([1.0] + [abs(c) for v in vs for c in (v.x, v.y)])


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=800, height=600)


class TestExactIdentities(_Case):
    """Integer-valued vectors: every identity holds to the bit."""

    @given(vecs(exact), vecs(exact), vecs(exact))
    def test_addition(self, a, b, c):
        self.assertEqual(xy(a + b), xy(b + a))
        self.assertEqual(xy((a + b) + c), xy(a + (b + c)))
        self.assertEqual(xy(a - b), xy(a + (-b)))
        self.assertEqual(xy(-(-a)), xy(a))
        self.assertEqual(xy(a + Vec2()), xy(a))
        self.assertEqual(xy(a * 2), xy(a + a))
        self.assertEqual(xy(a * 1), xy(a))
        # Division by a power of two is exact (a mutant turning / into *
        # survived the first battery: nothing divided).
        self.assertEqual(xy(a / 2), xy(a * 0.5))
        self.assertEqual(xy((a * 4) / 4), xy(a))
        self.assertEqual(xy(a / -1), xy(-a))

    @given(vecs(exact), exact, exact)
    def test_a_vector_moves_a_point(self, a, px, py):
        from scena.shapes import Point
        moved = a + Point(px, py)               # by design a Point: the place moved
        self.assertIsInstance(moved, Point)
        self.assertEqual((moved.x, moved.y), (a.x + px, a.y + py))

    @given(vecs(exact), vecs(exact))
    def test_dot_and_cross(self, a, b):
        self.assertEqual(a.dot(b), b.dot(a))
        self.assertEqual(a.cross(b), -b.cross(a))
        self.assertEqual(a.cross(a), 0.0)
        self.assertEqual(a.dot(a.perp_left()), 0.0)
        self.assertEqual(a.dot(a.perp_right()), 0.0)
        # Lagrange's identity: dot² + cross² = |a|²|b|².
        self.assertEqual(a.dot(b) ** 2 + a.cross(b) ** 2,
                         a.dot(a) * b.dot(b))

    @given(vecs(exact))
    def test_perpendiculars(self, a):
        self.assertEqual(xy(a.perp_left().perp_left()), xy(-a))
        self.assertEqual(xy(a.perp_right()), xy(-a.perp_left()))
        self.assertEqual(xy(a.perp_left().perp_right()), xy(a))
        # Counter-clockwise (y up): perp_left is a quarter turn by +90.
        self.assertEqual(a.cross(a.perp_left()), a.dot(a))

    @given(vecs(exact), vecs(exact))
    def test_a_pair_is_a_vector(self, a, b):
        # Every operand form gives the same bits: Vec2, tuple, list.
        pair = (b.x, b.y)
        self.assertEqual(xy(a + pair), xy(a + b))
        self.assertEqual(xy(a + list(pair)), xy(a + b))
        self.assertEqual(xy(a - pair), xy(a - b))
        self.assertEqual(a.dot(pair), a.dot(b))
        self.assertEqual(a.cross(pair), a.cross(b))
        self.assertEqual(a.angle_to(pair), a.angle_to(b))

    @given(vecs(exact), vecs(exact))
    def test_in_place_is_the_pure_form(self, a, b):
        for op, pure in (("__iadd__", "__add__"), ("__isub__", "__sub__")):
            w = Vec2(a.x, a.y)
            getattr(w, op)(b)
            self.assertEqual(xy(w), xy(getattr(a, pure)(b)), op)

    @given(vecs(exact))
    def test_conversions(self, a):
        self.assertEqual(a.to_tuple(), (a.x, a.y))
        self.assertEqual(a.to_array(), [a.x, a.y])
        self.assertEqual(tuple(a), (a.x, a.y))
        self.assertTrue(a == (a.x, a.y))
        self.assertEqual(xy(Vec2(*a)), xy(a))


class TestNearIdentities(_Case):
    """General floats: identities within a few ULP of the operands."""

    @given(vecs(), angle)
    def test_rotation_keeps_length(self, a, t):
        r = a.rotate(t)
        self.assertTrue(close(r.length, a.length, mag(a)), (r.length, a.length))
        self.assertTrue(close_xy(r.rotate(-t), a, mag(a), ulps=256))
        self.assertTrue(close_xy(a.rotate(360), a, mag(a)))

    @given(vecs(), angle)
    def test_do_rotation_is_rotate(self, a, t):
        w = Vec2(a.x, a.y)
        w.do_rotation(t)
        self.assertEqual(xy(w), xy(a.rotate(t)))

    @given(vecs(exact))
    def test_quarter_turn_is_perp_left(self, a):
        self.assertTrue(close_xy(a.rotate(90), a.perp_left(), mag(a)))
        self.assertTrue(close_xy(a.rotate(-90), a.perp_right(), mag(a)))

    @given(nonzero())
    def test_normalize(self, a):
        n = a.normalize()
        self.assertTrue(close(n.length, 1.0))
        self.assertGreaterEqual(n.dot(a), 0.0)
        self.assertTrue(close(n.cross(a) / a.length, 0.0, ulps=256))

    @given(angle, hst.floats(min_value=1e-3, max_value=1e6))
    def test_vec_from_angle_round_trip(self, t, length):
        v = vec_from_angle(t, length)
        self.assertTrue(close(v.length, length, length))
        turn = (v.angle - t) % 360.0
        self.assertTrue(min(turn, 360.0 - turn) < 1e-9 * max(1.0, abs(t)), (v.angle, t))

    @given(vecs(), nonzero())
    def test_project_and_reject(self, v, n):
        p, r = v.project(n), v.reject(n)
        scale = mag(v, n) ** 2
        self.assertTrue(close_xy(p + r, v, scale, ulps=1024))
        self.assertTrue(close(r.dot(n) / n.length, 0.0, scale, ulps=1024))
        self.assertTrue(close(p.cross(n) / n.length, 0.0, scale, ulps=1024))

    @given(vecs(), nonzero())
    def test_reflect(self, v, n):
        once = v.reflect(n)
        self.assertTrue(close(once.length, v.length, mag(v), ulps=256))
        self.assertTrue(close_xy(once.reflect(n), v, mag(v), ulps=1024))

    @given(vecs(), vecs(), hst.floats(min_value=0.0, max_value=1.0))
    def test_lerp(self, a, b, t):
        self.assertEqual(xy(a.lerp(b, 0)), xy(a))
        self.assertTrue(close_xy(a.lerp(b, 1), b, mag(a, b)))
        m = a.lerp(b, t)
        self.assertTrue(close(a.distance(m) + m.distance(b), a.distance(b),
                              mag(a, b), ulps=1024))


class TestInequalities(_Case):
    @given(vecs(), vecs())
    def test_triangle_and_cauchy_schwarz(self, a, b):
        slack = 64 * math.ulp(mag(a, b) ** 2)
        self.assertLessEqual((a + b).length, a.length + b.length + slack)
        self.assertLessEqual(abs(a.length - b.length), (a - b).length + slack)
        self.assertLessEqual(abs(a.dot(b)), a.length * b.length * (1 + 1e-12) + slack)
        self.assertLessEqual(abs(a.cross(b)), a.length * b.length * (1 + 1e-12) + slack)

    @given(vecs(), vecs(), vecs())
    def test_distance_is_a_metric(self, a, b, c):
        slack = 64 * math.ulp(mag(a, b, c))
        self.assertEqual(a.distance(a), 0.0)
        self.assertEqual(a.distance(b), b.distance(a))
        self.assertGreaterEqual(a.distance(b), 0.0)
        self.assertLessEqual(a.distance(c), a.distance(b) + b.distance(c) + slack)

    @given(vecs())
    def test_angle_range(self, a):
        self.assertGreaterEqual(a.angle, -180.0)
        self.assertLessEqual(a.angle, 180.0)
        self.assertEqual(a.angle, math.degrees(math.atan2(a.y, a.x)))
        self.assertEqual(a.length, math.sqrt(a.x * a.x + a.y * a.y))

    @given(nonzero(), nonzero())
    def test_angle_to(self, a, b):
        t = a.angle_to(b)
        self.assertGreaterEqual(t, -180.0)
        self.assertLessEqual(t, 180.0)
        u = a.abs_angle_to(b)
        self.assertGreaterEqual(u, 0.0)
        self.assertLessEqual(u, 180.0)
        self.assertEqual(abs(t), u)            # one formula, two spellings (VB14)
        # Turning a by angle_to points it along b.
        turned = a.rotate(t)
        self.assertGreaterEqual(turned.dot(b), -1e-9 * a.length * b.length)
        self.assertLess(abs(turned.cross(b)), 1e-6 * a.length * b.length)

    @given(nonzero(), hst.floats(min_value=0.0, max_value=1e4),
           hst.floats(min_value=0.0, max_value=1e4))
    def test_clamp_length(self, v, lo, hi):
        lo, hi = min(lo, hi), max(lo, hi)
        c = v.clamp_length(lo, hi)
        slack = 1e-9 * max(1.0, hi)
        self.assertGreaterEqual(c.length, lo - slack)
        self.assertLessEqual(c.length, hi + slack)
        if c.length > 0:
            self.assertGreaterEqual(c.dot(v), 0.0)      # same direction
        if lo <= v.length <= hi:
            self.assertTrue(close_xy(c, v, mag(v)))


class TestAliasesAgree(_Case):
    """The long and short spellings are one function."""

    PAIRS = (("reflect", "reflect_about"), ("project", "project_onto"),
             ("reject", "reject_from"), ("clamp_length", "clamp_length_to"))

    @given(vecs(), nonzero(), hst.floats(min_value=0, max_value=100))
    def test_aliases(self, v, n, k):
        for short, long in self.PAIRS:
            args = (k, k + 50) if short == "clamp_length" else (n,)
            self.assertEqual(xy(getattr(v, short)(*args)), xy(getattr(v, long)(*args)), short)


class TestTheGuiaSays(_Case):
    """The Guia's own sentences, as written (the documented sentence is the oracle)."""

    def test_examples(self):
        v = Vec2(3, 4)
        self.assertEqual(v.length, 5.0)
        self.assertAlmostEqual(v.angle, 53.13, places=2)
        self.assertEqual(xy(Vec2(1, -1).reflect_about(Vec2(0, 1))), (1.0, 1.0))
        w = vec_from_angle(30, 10)
        self.assertAlmostEqual(w.x, 8.66, places=2)
        self.assertAlmostEqual(w.y, 5.0, places=12)
        front = Vec2(1, 0)
        left = vec_from_angle(90, reference_vec=front)    # 90° to the left
        self.assertGreater(front.cross(left), 0)
        self.assertGreater(Vec2(1, 0).cross(Vec2(0, 1)), 0)  # other on the left: positive
        self.assertEqual(xy(Vec2(0, 0).lerp(Vec2(10, 0), 1.5)), (15.0, 0.0))  # not clamped
        self.assertLessEqual(Vec2(400, 300).clamp_length(0, 300).length, 300.0)


class TestDegenerateBases(_Case):
    """The zero vector: one defined outcome per operation, never a raise."""

    def test_zero_vector(self):
        z = Vec2(0, 0)
        v = Vec2(3, 4)
        self.assertEqual(xy(z.normalize()), (0.0, 0.0))
        self.assertEqual(z.angle, 0.0)
        self.assertEqual(z.length, 0.0)
        self.assertEqual(xy(z.clamp_length(1, 2)), (0.0, 0.0))
        self.assertEqual(v.abs_angle_to(z), 0.0)
        self.assertEqual(z.abs_angle_to(v), 0.0)
        self.assertEqual(v.angle_to(z), 0.0)
        self.assertEqual(xy(v.project(z)), (0.0, 0.0))     # onto nothing: nothing
        self.assertEqual(xy(v.reject(z)), (3.0, 4.0))
        self.assertEqual(xy(v.reflect(z)), (3.0, 4.0))     # no normal: unchanged
        self.assertEqual(xy(z.rotate(37)), (0.0, 0.0))


# --------------------------------------------------------------------------
# Author errors only
# --------------------------------------------------------------------------

JUNK = (None, "ab", ("a", 1), (1,), [1, 2, 3], object(), math.nan, math.inf,
        10 ** 400, True, (math.nan, 0), (10 ** 400, 0))

# Every operation, as name -> call(v, junk). The completeness guard below
# checks every public method of Vec2 is here or in NOT_OPERATIONS.
OPERATIONS = {
    "__add__": lambda v, j: v + j,
    "__sub__": lambda v, j: v - j,
    "__mul__": lambda v, j: v * j,
    "__truediv__": lambda v, j: v / j,
    "__eq__": lambda v, j: v == j,
    "__iadd__": lambda v, j: v.__iadd__(j),
    "__isub__": lambda v, j: v.__isub__(j),
    "__lshift__": lambda v, j: v << j,
    "dot": lambda v, j: v.dot(j),
    "cross": lambda v, j: v.cross(j),
    "angle_to": lambda v, j: v.angle_to(j),
    "abs_angle_to": lambda v, j: v.abs_angle_to(j),
    "reflect": lambda v, j: v.reflect(j),
    "reflect_about": lambda v, j: v.reflect_about(j),
    "project": lambda v, j: v.project(j),
    "project_onto": lambda v, j: v.project_onto(j),
    "reject": lambda v, j: v.reject(j),
    "reject_from": lambda v, j: v.reject_from(j),
    "lerp": lambda v, j: v.lerp(j, 0.5),
    "lerp t": lambda v, j: v.lerp(Vec2(1, 1), j),
    "distance": lambda v, j: v.distance(j),
    "rotate": lambda v, j: v.rotate(j),
    "do_rotation": lambda v, j: v.do_rotation(j),
    "clamp_length": lambda v, j: v.clamp_length(j, 10),
    "clamp_length max": lambda v, j: v.clamp_length(0, j),
    "clamp_length_to": lambda v, j: v.clamp_length_to(j, 10),
    "vec_from_angle": lambda v, j: vec_from_angle(j),
    "vec_from_angle length": lambda v, j: vec_from_angle(30, j),
    "vec_from_angle reference": lambda v, j: vec_from_angle(30, 1, j),
    "Vec2()": lambda v, j: Vec2(j),
    "Vec2(x, y)": lambda v, j: Vec2(j, 0),
}

# Public methods that take no operand (or only read): nothing to feed junk to.
NOT_OPERATIONS = {"normalize", "perp_left", "perp_right", "to_tuple", "to_array",
                  "clone", "copy", "unlink",
                  "temp"}   # engine-internal (not in the Guia): numbers only

# Violations known to the catalogue, by ``"<operation> <junk!r>"``. Shrink-only.
KNOWN = {
    "__lshift__ (nan, 0)": "VB4: a free Vec2 takes NaN through << (GX15)",
}


def _finite_result(r) -> bool:
    if isinstance(r, Vec2):
        return math.isfinite(r.x) and math.isfinite(r.y)
    if isinstance(r, float):
        return math.isfinite(r)
    return True


class TestAuthorErrorsOnly(_Case):
    def test_every_operation_with_junk(self):
        bad = []
        for name, call in OPERATIONS.items():
            for i, junk in enumerate(JUNK):
                v = Vec2(3, 4)
                try:
                    with hs.quiet():
                        r = call(v, junk)
                except hs.AUTHOR_ERRORS as exc:
                    if hs.leak_message(exc):
                        bad.append(f"{name} {junk!r:.20}: leaked {type(exc).__name__}: {exc!s:.80}")
                    continue
                except Exception as exc:  # noqa: BLE001
                    bad.append(f"{name} {junk!r:.20}: {type(exc).__name__}: {exc!s:.80}")
                    continue
                if not _finite_result(r) or not (math.isfinite(v.x) and math.isfinite(v.y)):
                    bad.append(f"{name} {junk!r}: accepted, gave {r!r:.40} / v = {v!r:.40}")
        known = [b for b in bad if b.split(":")[0] in KNOWN]
        new = [b for b in bad if b not in known]
        self.assertFalse(new, "operations that broke 'author errors only':\n  " + "\n  ".join(new))
        self.assertEqual(sorted(b.split(":")[0] for b in known), sorted(KNOWN),
                         "a KNOWN entry no longer breaks: remove it")

    def test_division_by_zero(self):
        # Kept apart: Python's ZeroDivisionError is the known message (VB11).
        with self.assertRaises(ZeroDivisionError):
            Vec2(1, 2) / 0

    def test_every_public_method_is_covered(self):
        public = {n for n, f in inspect.getmembers(Vec2, callable)
                  if not n.startswith("_") and n in vars(Vec2)}
        named = {n.split()[0] for n in OPERATIONS} | NOT_OPERATIONS
        missing = sorted(public - named)
        self.assertFalse(missing, f"Vec2 methods no junk call reaches: {missing}")


if __name__ == "__main__":
    unittest.main()
