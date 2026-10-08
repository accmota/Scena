"""Program model test: keyboard-steered chain (chase, @every growth, confine).

Program: tests/programs/snake_chain.py. Specs a and b were written by two
independent spec-only authors from the docs (tests/programs/spec_agent_prompt.txt).
Harness and protocol: tests/program_support.py, design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import program_test_case  # noqa: E402

TestSnakeChain = program_test_case(
    "snake_chain",
    l3_scenarios={"a": ["left_right", "up"]},
    dt_split={"a/up": {"time": 1e-9}},
    tier_c=[("a", "left")],
)


if __name__ == "__main__":
    unittest.main()
