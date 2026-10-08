"""Program model test: endless runner with a scripted story (API-first: Endless, layers
above / below, tween, parallel, race, until, after, async modes, exit_mode, Cancelled,
Sound / amp_db, TextInput, set_defaults, clock.paused / clock.scale).

Program: tests/programs/runner_story.py (written from the Guia for the coverage pass).
Spec a was written by a spec-only author from the docs
(tests/programs/spec_agent_prompt.txt). Protocol: design/Testing Design.md,
"Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import program_test_case  # noqa: E402

TestRunnerStory = program_test_case(
    "runner_story", specs=("a",),
    l3_scenarios={"a": ["skip", "outro_named"]},
    tier_c=[("a", "jump")],
)


if __name__ == "__main__":
    unittest.main()
