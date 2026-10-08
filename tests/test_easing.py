"""``chase`` / ``deadzone`` — stateless math helpers next to ``lerp``.

Run:

    python -m unittest tests.test_easing -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import given, strategies as hst  # noqa: E402

from scena import Circle, Point, Vec2, chase, clock, deadzone, lerp, init
from scena.easing import MappingFunctions, TWEEN_EASES, lerp as easing_lerp



class TestDeadzoneTakesCells(unittest.TestCase):
    """Bug PM12 (found writing the geometry_lab program): deadzone(size=st.x)
    raised 'expected a number … got Attribute'; a cell counts as its value."""

    def test_cell_and_cell_pair(self):
        from scena import deadzone, st
        st.pm12_size = 120
        st.pm12_w = 40
        self.assertEqual(deadzone((0, 0), (300, 0), size=st.pm12_size),
                         deadzone((0, 0), (300, 0), size=120))
        self.assertEqual(deadzone((0, 0), (300, 90), size=(st.pm12_w, st.pm12_size)),
                         deadzone((0, 0), (300, 90), size=(40, 120)))
        st.remove("pm12_size")
        st.remove("pm12_w")

class TestChase(unittest.TestCase):
    def test_number_matches_lerp_exp(self):
        rate, dt = 6.0, 0.016
        t = 1.0 - math.exp(-rate * dt)
        self.assertEqual(chase(10.0, 40.0, rate, dt), lerp(10.0, 40.0, t))

    def test_tuple_matches_lerp_exp(self):
        rate, dt = 4.0, 0.1
        t = 1.0 - math.exp(-rate * dt)
        got = chase((0.0, 0.0), (100.0, 40.0), rate, dt)
        self.assertEqual(got, lerp((0.0, 0.0), (100.0, 40.0), t))

    def test_point_returns_plain_tuple(self):
        a = Point(0, 0)
        b = Point(100, 40)
        out = chase(a, b, rate=6.0, dt=0.1)
        self.assertIsInstance(out, tuple)
        expected = lerp(a, b, 1.0 - math.exp(-6.0 * 0.1))
        self.assertEqual(out, expected)

    def test_dt_zero_unchanged(self):
        cur = (10.0, 20.0)
        self.assertIs(chase(cur, (0.0, 0.0), rate=6.0, dt=0.0), cur)

    def test_rate_zero_unchanged(self):
        cur = 7.5
        self.assertEqual(chase(cur, 100.0, rate=0.0, dt=0.5), cur)

    def test_rate_negative_raises(self):
        with self.assertRaises(ValueError):
            chase((1.0, 2.0), (9.0, 9.0), rate=-1.0, dt=0.1)

    def test_large_rate_dt_near_target(self):
        got = chase(0.0, 100.0, rate=80.0, dt=1.0)
        self.assertAlmostEqual(got, 100.0, places=8)

    def test_vec2_matches_lerp(self):
        a = Vec2.temp(0, 0)
        b = Vec2.temp(10, 20)
        rate, dt = 5.0, 0.05
        got = chase(a, b, rate, dt)
        expected = lerp(a, b, 1.0 - math.exp(-rate * dt))
        self.assertAlmostEqual(float(got.x), float(expected.x))
        self.assertAlmostEqual(float(got.y), float(expected.y))

    def test_omitted_dt_uses_clock(self):
        clock.advance(0.05)
        explicit = chase(0.0, 100.0, rate=6.0, dt=clock.dt)
        implicit = chase(0.0, 100.0, rate=6.0)
        self.assertEqual(implicit, explicit)

    def test_explicit_dt_overrides_clock(self):
        clock.advance(0.2)
        omitted = chase(0.0, 100.0, rate=6.0)
        forced = chase(0.0, 100.0, rate=6.0, dt=0.01)
        self.assertNotEqual(omitted, forced)
        self.assertEqual(forced, lerp(0.0, 100.0, 1.0 - math.exp(-6.0 * 0.01)))

    def test_omitted_dt_when_clock_zero_unchanged(self):
        prev_paused = clock.paused
        clock.paused = True
        try:
            clock.advance(0.1)
            cur = (3.0, 4.0)
            self.assertIs(chase(cur, (9.0, 9.0), rate=6.0), cur)
        finally:
            clock.paused = prev_paused

    def test_exported_from_scena(self):
        import scena
        self.assertIn("chase", scena.__all__)
        self.assertIs(scena.chase, chase)
        self.assertIs(easing_lerp, lerp)


_value = hst.floats(-1e3, 1e3, allow_nan=False, allow_infinity=False)
_rate = hst.floats(0.0, 50.0, allow_nan=False, allow_infinity=False)
_step = hst.floats(0.0, 0.5, allow_nan=False, allow_infinity=False)


class TestChaseProperties(unittest.TestCase):
    """``chase`` is frame-rate independent: the docstring's whole promise."""

    def _close(self, a, b, *scale):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9 * max(1.0, *map(abs, scale)))

    @given(cur=_value, target=_value, rate=_rate, d1=_step, d2=_step)
    def test_two_frames_equal_one_frame_of_their_sum(self, cur, target, rate, d1, d2):
        two = chase(chase(cur, target, rate, d1), target, rate, d2)
        one = chase(cur, target, rate, d1 + d2)
        self.assertTrue(self._close(two, one, cur, target),
                        f"{d1} + {d2}: {two} vs one step of {d1 + d2}: {one}")

    @given(cur=hst.tuples(_value, _value), target=hst.tuples(_value, _value),
           rate=_rate, steps=hst.lists(_step, min_size=1, max_size=8))
    def test_many_frames_equal_one_frame_on_points(self, cur, target, rate, steps):
        stepped = cur
        for dt in steps:
            stepped = chase(stepped, target, rate, dt)
        once = chase(cur, target, rate, math.fsum(steps))
        for a, b, c, t in zip(stepped, once, cur, target):
            self.assertTrue(self._close(a, b, c, t), f"{stepped} vs {once}")

    @given(cur=_value, target=_value, rate=_rate,
           steps=hst.lists(_step, min_size=1, max_size=30))
    def test_gap_shrinks_and_never_crosses(self, cur, target, rate, steps):
        x, gap = cur, abs(target - cur)
        slack = 1e-12 * max(1.0, abs(cur), abs(target))
        for dt in steps:
            x = chase(x, target, rate, dt)
            self.assertLessEqual(abs(target - x), gap + slack, "chase moved away")
            self.assertGreaterEqual((target - x) * (target - cur), -slack,
                                    "chase overshot the target")
            gap = abs(target - x)


class TestChasePropertyCanaries(unittest.TestCase):
    """A per-frame constant factor (the classic ``lerp(a, b, rate * dt)``) is caught."""

    def test_frame_rate_dependent_chase_is_caught(self):
        from diff_support import assert_catches
        import scena.easing as easing

        def naive(current, target, rate, dt=None):
            return easing.lerp(current, target, min(1.0, rate * dt))

        assert_catches(self, "test_easing.TestChaseProperties.test_two_frames_equal_one_frame_of_their_sum",
                       [("scena", "chase", naive)], "chase with t = rate * dt")


class TestDeadzone(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)

    def test_inside_returns_current(self):
        cur = (0.0, 0.0)
        got = deadzone(cur, (10.0, 5.0), size=(40, 40))
        self.assertEqual(got, cur)

    def test_outside_excess_per_axis(self):
        # current at origin, size 20×20 → half 10. target (30, 0) is 20 past
        # the right edge, so look should move by 20 on X.
        got = deadzone((0.0, 0.0), (30.0, 0.0), size=(20, 20))
        self.assertAlmostEqual(got[0], 20.0, places=7)
        self.assertAlmostEqual(got[1], 0.0, places=7)

    def test_outside_both_axes(self):
        got = deadzone((0.0, 0.0), (40.0, -30.0), size=(20, 10))
        self.assertAlmostEqual(got[0], 30.0, places=7)
        self.assertAlmostEqual(got[1], -25.0, places=7)

    def test_exactly_on_boundary_unchanged(self):
        cur = (0.0, 0.0)
        got = deadzone(cur, (10.0, 0.0), size=(20, 20))
        self.assertEqual(got, cur)

    def test_size_number_is_square(self):
        a = deadzone((0.0, 0.0), (40.0, 0.0), size=160)
        b = deadzone((0.0, 0.0), (40.0, 0.0), size=(160, 160))
        self.assertEqual(a, b)
        # 40 is inside a 160 square → current
        self.assertEqual(a, (0.0, 0.0))

    def test_axis_lock_y_inf(self):
        cur = (10.0, 50.0)
        got = deadzone(cur, (200.0, 900.0), size=(20, float("inf")))
        self.assertAlmostEqual(got[0], 190.0, places=7)
        self.assertEqual(got[1], cur[1])

    def test_point_vec2_tuple_coerce(self):
        from_tuple = deadzone((0.0, 0.0), (40.0, 0.0), size=20)
        from_point = deadzone(Point(0, 0), Point(40, 0), size=20)
        from_vec = deadzone(Vec2.temp(0, 0), Vec2.temp(40, 0), size=20)
        self.assertEqual(from_tuple, from_point)
        self.assertEqual(from_tuple, from_vec)

    def test_graphic_center_coerces(self):
        hero = Circle(center=(30.0, 0.0), radius=8)
        got = deadzone((0.0, 0.0), hero, size=20)
        self.assertAlmostEqual(got[0], 20.0, places=7)
        self.assertAlmostEqual(got[1], 0.0, places=7)

    def test_bad_size_raises_typeerror(self):
        with self.assertRaises(TypeError):
            deadzone((0, 0), (1, 1), size="wide")
        with self.assertRaises(TypeError):
            deadzone((0, 0), (1, 1), size=None)
        with self.assertRaises(TypeError):
            deadzone((0, 0), (1, 1), size=(1,))

    def test_nan_size_raises(self):
        with self.assertRaises(ValueError):
            deadzone((0, 0), (10, 10), float("nan"))
        # inf still locks an axis
        self.assertEqual(deadzone((0, 0), (10, 4), (float("inf"), 2)), (0.0, 3.0))

    def test_negative_size_raises(self):
        with self.assertRaises(ValueError):
            deadzone((0, 0), (10, 10), size=-20)
        with self.assertRaises(ValueError):
            deadzone((0, 0), (10, 10), size=(20, -5))

    def test_chase_nan_rate_raises(self):
        with self.assertRaises(ValueError):
            chase(0.0, 10.0, float("nan"), dt=0.1)
        self.assertEqual(chase(3.0, 9.0, 4.0, dt=0.0), 3.0)

    def test_exported_from_scena(self):
        import scena
        self.assertIn("deadzone", scena.__all__)
        self.assertIs(scena.deadzone, deadzone)


class TestTweenEaseCatalog(unittest.TestCase):
    """Every named tween ease must start at 0 and end at 1 — a tween's ``u``
    is snapped to 1.0 at completion regardless (``process.Handle._tick_tween``),
    but ``remap()`` and any direct call use the raw function, so a non-exact
    endpoint is a real (if small) surface bug. See ``design/Fences.md``
    — this list is the full tween catalog, not a sample.
    """

    def test_all_tween_eases_are_endpoint_exact(self):
        for name in TWEEN_EASES:
            fn = getattr(MappingFunctions, name)
            with self.subTest(ease=name):
                # bounce's piecewise constants are exact only to ~1e-8; every
                # other ease is exact to machine precision.
                self.assertAlmostEqual(fn(0.0), 0.0, places=6, msg=name)
                self.assertAlmostEqual(fn(1.0), 1.0, places=6, msg=name)

    def test_elastic_does_not_start_at_two(self):
        # Regression: the old formula's sign/frequency gave elastic(0) == 2.0
        # and jumped chaotically (up to ~1.8x the travel distance per frame)
        # over the first few tweened frames.
        self.assertAlmostEqual(MappingFunctions.elastic(0.0), 0.0)
        self.assertAlmostEqual(MappingFunctions.elastic(1.0), 1.0)
        # Should stay within a sane overshoot band the whole way, not swing
        # past ~2x on either side.
        for i in range(1, 100):
            x = i / 100.0
            y = MappingFunctions.elastic(x)
            self.assertGreater(y, -1.5, msg=f"x={x}")
            self.assertLess(y, 2.5, msg=f"x={x}")

    def test_sigmoid_erratic_endpoint_exact(self):
        self.assertEqual(MappingFunctions.sigmoid(0.0), 0.0)
        self.assertEqual(MappingFunctions.sigmoid(1.0), 1.0)
        self.assertEqual(MappingFunctions.erratic(0.0), 0.0)
        self.assertEqual(MappingFunctions.erratic(1.0), 1.0)

    def test_steps_docstring_matches_step_count(self):
        # steps() divides into 20 buckets (floor(x*21)/20 lands on 21 values
        # 0/20..20/20, i.e. 20 risers) — the docstring used to say "5 steps".
        self.assertIn("20 steps", MappingFunctions.steps.__doc__)
        seen = {MappingFunctions.steps(i / 200.0) for i in range(201)}
        self.assertEqual(len(seen), 21)


if __name__ == "__main__":
    unittest.main()
