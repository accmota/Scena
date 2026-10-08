"""Program model test: tutorial 04: mouse chain (widgets, Menu pause, links, rebuild).

Program: examples/cadeia_de_bolas.py. Specs a and b were written by two
independent spec-only authors from the docs (tests/programs/spec_agent_prompt.txt).
Harness and protocol: tests/program_support.py, design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import program_test_case  # noqa: E402

TestCadeiaDeBolas = program_test_case(
    "examples/cadeia_de_bolas.py",
    l3_scenarios={"a": ["mouse", "pause", "menu_recomecar"]},
    tier_c=[("a", "mouse")],
)


if __name__ == "__main__":
    unittest.main()
