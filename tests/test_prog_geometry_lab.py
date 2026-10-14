"""Program model test: geometry playground (API-first: Ellipse, Polygon, RegularPolygon,
Square, Triangle, Anchor, Contrail, History, Hitbox, Svg, Texture, lerp, remap,
deadzone, distance, heading, closest_point, middle_point, intersection(s), nearest, XPos, clock).

Program: tests/programs/geometry_lab.py (written from the Guia for the coverage pass).
Spec a was written by a spec-only author from the docs
(tests/programs/spec_agent_prompt.txt). Protocol: design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import program_test_case  # noqa: E402

TestGeometryLab = program_test_case(
    "geometry_lab", specs=("a",),
    l3_scenarios={"a": ["mouse", "pause"]},
    tier_c=[("a", "click")],
)


if __name__ == "__main__":
    unittest.main()
