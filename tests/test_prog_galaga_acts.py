"""Program model test: galaga with acts (Titulo / Fase / FimDeJogo, modes, boss on a Track).

Program: tests/programs/galaga_acts.py. Specs a and b were written by two
independent spec-only authors from the docs (tests/programs/spec_agent_prompt.txt).
Harness and protocol: tests/program_support.py, design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import program_test_case  # noqa: E402

TestGalagaActs = program_test_case(
    "galaga_acts",
    l3_scenarios={"a": ["fire", "lose_skip"], "b": ["boss"]},
    tier_c=[("a", "fire")],
)


if __name__ == "__main__":
    unittest.main()
