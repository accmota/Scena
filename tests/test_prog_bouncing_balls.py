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

    def test_specs_catch_a_concave_colliding_as_one_hull(self):
        # CV1's shape: the quarter-pipe met as the hull of its pieces (the
        # chord from tip to tip), so a ball stops ~35 DU before the drawn arc.
        def hull_prims(shape):
            pts = sorted({p for poly in shape._world_pieces() for p in poly})
            hull = []
            for seq in (pts, pts[::-1]):        # monotone chain
                part = []
                for q in seq:
                    while len(part) >= 2 and (
                            (part[-1][0] - part[-2][0]) * (q[1] - part[-2][1])
                            - (part[-1][1] - part[-2][1]) * (q[0] - part[-2][0])) <= 0:
                        part.pop()
                    part.append(q)
                hull += part[:-1]
            xs, ys = [q[0] for q in hull], [q[1] for q in hull]
            return [_collision.Prim(_collision.PrimKind.POLY,
                                    (min(xs), min(ys), max(xs), max(ys)), (), hull)]
        for t in ("test_spec_a_corners", "test_spec_b_corner_one"):
            with self.subTest(t):
                assert_catches(self, f"test_prog_bouncing_balls.TestBouncingBalls.{t}",
                               [("scena.collision", "_concave_prims", hull_prims)],
                               "a Concave colliding as one hull (CV1)")


if __name__ == "__main__":
    unittest.main()
