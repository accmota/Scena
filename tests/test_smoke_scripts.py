"""The developer's scripts build their scene and play 30 frames headless.

The ``SLOW`` half of ``test_scripts_run`` (same rule, same harness; the
catalogue's SR1-SR3 were all here): ``scripts/smoke``, the bench loads
(``tests/loads``) and ``test_scripts_run.EXTRA``. ~22 s of CPU in parallel
children, so gate and deep run it and quick runs the examples only (Testing
Design, "Test tiers").

    python tests/run_tiers.py focused test_smoke_scripts
"""
from __future__ import annotations

import unittest

import tests.test_scripts_run as R


class TestSmokeScriptsRun(unittest.TestCase):
    def test_every_smoke_script_runs_headless(self):
        R.assert_all_run(self, R.scripts(smoke=True), 40)


if __name__ == "__main__":
    unittest.main()
