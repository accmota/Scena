"""Program model test: platformer (resolve, coyote time, elevator, robots, sprites, game over).

Program: tests/programs/platformer.py. Specs a and b were written by two
independent spec-only authors from the docs (tests/programs/spec_agent_prompt.txt).
Harness and protocol: tests/program_support.py, design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import program_test_case  # noqa: E402

TestPlatformer = program_test_case(
    "platformer",
    l3_scenarios={"a": ["shoot_hold", "game_over_restart"]},
    tier_c=[("a", "shoot_hold")],
)


if __name__ == "__main__":
    unittest.main()
