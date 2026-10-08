"""Program model test: toy box (API-first: hover / drag / drop hooks, on_change, flush,
unregister_event, collide_stay / exit, collide_with_*, Collider, ANYTHING, CollisionInfo,
TouchingContact, test_collision, unresolve, collision settings, above / below).

Program: tests/programs/toybox.py (written from the Guia for the coverage pass).
Specs written by spec-only authors from the docs (tests/programs/spec_agent_prompt.txt);
b concentrates on dragging and dropping. Protocol: design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import PROGRAMS, program_test_case  # noqa: E402

_SPECS = tuple(l for l in ("a", "b")
               if os.path.exists(os.path.join(PROGRAMS, f"toybox_spec_{l}.py")))

TestToybox = program_test_case(
    "toybox", specs=_SPECS,
    l3_scenarios={"a": ["scan", "cells"]},
    tier_c=[("a", "scan")],
)


if __name__ == "__main__":
    unittest.main()
