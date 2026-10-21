"""The ninja examples survive a long frame: a hitch is not a fall into the pit.

Bug (2026-10-21): ``ninja_2_mundo`` … ``ninja_4_perigos`` tested the pit with
``if self.center.y < 30: self.perder()`` in ``on_update``, right after
``move_by``. That pose is not resolved yet (the floor pushes back later in the
frame, Collision Design — Frame order). At 60 Hz the gravity step is ~0.6 DU;
a frame of 0.18 s or more (a first ``visual = Aura()`` baked 0.85 s, any hitch)
moves the feet below y = 30 before the push, so a hero standing on the floor
lost a life and went back to the start. The test now lives in a
``@when(lambda self: self.center.y < 30)``, checked after collision.

Bug class: an author reads a resolve body's pose in ``update`` to decide a
game event. Each example runs headless in its own process (``init`` is global):
a long frame while standing keeps the lives; a real fall into the water still
costs one.

    python tests/run_tiers.py focused test_ninja_examples
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = ("ninja_2_mundo.py", "ninja_3_nivel.py", "ninja_4_perigos.py", "ninja_5_espada.py")

DRIVER = r"""
import json, os, runpy, sys, warnings
root, script = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
warnings.simplefilter("ignore")
import random
random.seed(0)
import scena
from scena.orchestration import ScenaFramework

def run(first_act=None):
    import inspect
    fw = ScenaFramework.get_instance()
    caller = inspect.currentframe().f_back.f_globals
    fw.set_auto_callbacks(caller)
    fw._begin_game(first_act)
    heroi = lambda: list(scena.group["heroi"])[0]
    out = {}
    for f in range(330):
        if f == 250:                       # above the water gap
            heroi().center = (560, 300)
            heroi().vel = scena.Vec2(0, 0)
        fw._simulate_frame(dt=0.25 if f == 200 else 1 / 60)
        if f == 199:
            out["before"] = caller["st"].vidas
            out["standing_y"] = heroi().center.y
        if f == 210:
            out["after_hitch"] = caller["st"].vidas
            out["after_hitch_y"] = heroi().center.y
    out["after_fall"] = caller["st"].vidas
    print("RESULT " + json.dumps(out), flush=True)

scena.run = run
os.chdir(os.path.dirname(script))
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
"""


def drive(name):
    script = os.path.normpath(os.path.join(ROOT, "examples", name))
    proc = subprocess.run(
        [sys.executable, "-c", DRIVER, ROOT, script],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    raise AssertionError(f"{name} did not finish:\n{proc.stdout[-2000:]}\n{proc.stderr[-4000:]}")


class TestALongFrameIsNotAFall(unittest.TestCase):
    def test_each_ninja_example(self):
        for name in EXAMPLES:
            with self.subTest(example=name):
                got = drive(name)
                self.assertEqual(got["before"], 3)
                self.assertAlmostEqual(got["standing_y"], 80, delta=1)
                # The hitch: still standing, no life lost, not sent to the start.
                self.assertEqual(got["after_hitch"], 3)
                self.assertAlmostEqual(got["after_hitch_y"], 80, delta=1)
                # A real fall still costs a life.
                self.assertEqual(got["after_fall"], 2)


if __name__ == "__main__":
    unittest.main()
