"""Program model test: bouncing balls (walls, spinning bar, elastic resolve, widgets, zoom).

Program: tests/programs/bouncing_balls.py. Specs a and b were written by two
independent spec-only authors from the docs (tests/programs/spec_agent_prompt.txt).
Harness and protocol: tests/program_support.py, design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import assert_catches  # noqa: E402
from program_support import program_test_case  # noqa: E402

import scena.collision  # noqa: E402,F401  (load the real module)
from scena import clock as _clock  # noqa: E402

_collision = sys.modules["scena.collision"]   # the module, not the facade

TestBouncingBalls = program_test_case(
    "bouncing_balls",
    l3_scenarios={"a": ["start", "zoom", "cells"], "b": ["restart", "zoomed_start"]},
    dt_split={"a/zoom": {"roda_angle": 1e-6, "zoom": 1e-12, "roda_center": 1e-9},
              "b/idle": {"roda_angle": 1e-6, "clock_time": 1e-9}},
    cull_scenarios=[("a", "zoom")],
    tier_c=[("a", "start")],
)


class TestBouncingBallsCanaries(unittest.TestCase):
    """The specs must fail on planted bugs (Testing Design: prove the test can fail)."""

    def test_spec_a_catches_a_lossy_bounce(self):
        lossy = lambda b, _v=_collision._validate_bounce: 0.8 * _v(b)  # noqa: E731
        assert_catches(self, "test_prog_bouncing_balls.TestBouncingBalls.test_spec_a_start",
                       [("scena.collision", "_validate_bounce", lossy)], "bounce=1 losing energy")

    def test_spec_b_catches_a_lossy_bounce(self):
        lossy = lambda b, _v=_collision._validate_bounce: 0.8 * _v(b)  # noqa: E731
        assert_catches(self, "test_prog_bouncing_balls.TestBouncingBalls.test_spec_b_start",
                       [("scena.collision", "_validate_bounce", lossy)], "bounce=1 losing energy")

    def test_specs_catch_a_fast_clock(self):
        adv = type(_clock).advance
        fast = lambda self, dt, _a=adv: _a(self, 2 * dt)  # noqa: E731
        for t in ("test_spec_a_idle", "test_spec_b_idle"):
            with self.subTest(t):
                assert_catches(self, f"test_prog_bouncing_balls.TestBouncingBalls.{t}",
                               [(type(_clock), "advance", fast)], "a clock that runs at 2x")


if __name__ == "__main__":
    unittest.main()
