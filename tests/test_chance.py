"""chance() — boolean roll with probability in [0, 1]."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.scenamath import chance
from scena.state import State


class TestChance(unittest.TestCase):
    def test_never(self):
        for _ in range(40):
            self.assertFalse(chance(0))
            self.assertFalse(chance(0.0))

    def test_always(self):
        for _ in range(40):
            self.assertTrue(chance(1))
            self.assertTrue(chance(1.0))

    def test_matches_random_threshold(self):
        random.seed(0)
        expected = [random.random() < 0.3 for _ in range(30)]
        random.seed(0)
        got = [chance(0.3) for _ in range(30)]
        self.assertEqual(got, expected)

    def test_rejects_percent(self):
        with self.assertRaises(ValueError) as ctx:
            chance(30)
        msg = str(ctx.exception)
        self.assertIn("0 to 1", msg)
        self.assertIn("chance(0.30)", msg)
        self.assertIn("percent", msg)

    def test_rejects_above_one_and_nan(self):
        for bad in (2, 1.0001, float("nan"), float("inf")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                chance(bad)

    def test_rejects_negative(self):
        with self.assertRaises(ValueError) as ctx:
            chance(-0.1)
        self.assertIn("chance(0.30)", str(ctx.exception))

    def test_rejects_non_number(self):
        with self.assertRaises(TypeError) as ctx:
            chance("30%")
        self.assertIn("chance(0.30)", str(ctx.exception))

    def test_attribute_payload(self):
        st = State()
        st.create("p", initial=1.0)
        self.assertTrue(chance(st.p))
        st.p = 0.0
        self.assertFalse(chance(st.p))

    def test_star_import(self):
        import scena
        self.assertIn("chance", scena.__all__)
        self.assertTrue(callable(scena.chance))


if __name__ == "__main__":
    unittest.main()
