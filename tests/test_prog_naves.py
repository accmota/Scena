"""Program model test: tutorial 05: shooter (sprites, @collide, @leave_playfield, every, ready, tweens).

Program: examples/naves.py. Specs a and b were written by two
independent spec-only authors from the docs (tests/programs/spec_agent_prompt.txt).
Harness and protocol: tests/program_support.py, design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import program_test_case  # noqa: E402

TestNaves = program_test_case(
    "examples/naves.py",
    l3_scenarios={"a": ["atira", "congelada"]},
    tier_c=[("a", "atira")],
)


if __name__ == "__main__":
    unittest.main()
