"""Program model test: tutorial 02: catch the stars (every, @collide, untag, after).

Program: examples/pegar_estrelas.py. Specs a and b were written by two
independent spec-only authors from the docs (tests/programs/spec_agent_prompt.txt).
Harness and protocol: tests/program_support.py, design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import program_test_case  # noqa: E402

TestPegarEstrelas = program_test_case(
    "examples/pegar_estrelas.py",
    l3_scenarios={"a": ["direita", "ambas"]},
    tier_c=[("a", "direita")],
)


if __name__ == "__main__":
    unittest.main()
