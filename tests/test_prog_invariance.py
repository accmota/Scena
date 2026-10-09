"""Metamorphic invariances over whole programs: the world does not depend on
how it is looked at, how time is sliced, or what its layers are called.

Interaction campaign, class 3 (design/Testing Design.md, "Interaction
campaign"). Each oracle runs a spec scenario twice and compares the trace
and the world (``program_oracles``):

* ``camera_moved`` — zoom, pan, rotation and origin set before the program's
  first line: world motion, contacts, timers and scores do not depend on the
  camera (probes that read the camera, a view or the pointer in world units
  are named per program in ``CAMERA_IGNORE``; programs that read the mouse
  are excluded, the pointer sits at a view point);
* ``time_scaled`` — ``clock.scale = k`` with frames of ``dt / k``: the same
  world time per frame, the same trace (anything that reads the real dt or
  wall time shows here; a program that sets the scale itself is excluded);
* ``rename_layers`` — the program rewritten with every author layer name
  suffixed leaves the same world (Tier C, like ``rename_groups``).

Scenarios with pointer input (move, click, drag) are skipped by the camera
oracle: a view-space click lands elsewhere in the world on purpose. ``dev``
runs the first eligible scenario of each program; ``ci`` / ``deep`` every one.
``KNOWN`` is shrink-only.

    python -m unittest tests.test_prog_invariance -v
"""
from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402
import program_oracles  # noqa: E402
from diff_support import assert_catches  # noqa: E402
from program_support import load_spec  # noqa: E402

FULL = hypothesis_support.PROFILE in ("ci", "deep")

PROGRAMS = ["bouncing_balls", "examples/cadeia_de_bolas", "galaga_acts", "geometry_lab",
            "examples/naves", "examples/pegar_estrelas", "platformer", "runner_story",
            "snake_chain", "toybox"]

# program -> reason it is outside an oracle
CAMERA_EXCLUDED: Dict[str, str] = {
    "examples/cadeia_de_bolas": "the chain chases the mouse (a view point, elsewhere in the world under a moved camera)",
    "geometry_lab": "reads the mouse",
    "toybox": "reads the mouse",
    "examples/naves": "confines the ship to canvas.game_view every frame (the world follows the camera by design)",
    "snake_chain": "places the head at the view's centre and confines it to the view",
    "runner_story": "Endless fills what the camera sees (camera-driven by design)",
    "galaga_acts": "places the ship by canvas.game_view when the play act starts",
}
TIME_EXCLUDED: Dict[str, str] = {
    "runner_story": "sets clock.scale itself (a slow-motion beat)",
}
# program -> probes that read the camera, a view or the pointer in world units
CAMERA_IGNORE: Dict[str, List[str]] = {
    "bouncing_balls": ["zoom", "pan"],
}
CAMERAS = [
    {"zoom": 2.0},
    {"pan": (137.0, -59.0)},
    {"zoom": 0.5, "pan": (-300.0, 200.0), "rotate": 15.0},
    {"origin": "center", "zoom": 1.5},
]
POINTER_STEPS = {"move", "click", "drag", "scroll"}

# Shrink-only: "oracle | program | scenario" -> reason.
KNOWN: Dict[str, str] = {
}


def _ident(name: str) -> str:
    return name.replace("examples/", "").replace("/", "_").replace(".", "_")


def _scenarios(program: str, *, pointer_free: bool) -> List[str]:
    ns = load_spec(program, "a")
    names = []
    for name, sc in ns["SCENARIOS"].items():
        if pointer_free and any(step[0] in POINTER_STEPS for step in sc.steps):
            continue
        names.append(name)
    return names if FULL else names[:1]


def _check(tc: unittest.TestCase, key: str, msgs: List[str]) -> None:
    if msgs:
        if key in KNOWN:
            tc.skipTest(f"known: {KNOWN[key]}")
        tc.fail(f"{key}:\n  " + "\n  ".join(msgs))
    elif key in KNOWN and FULL:
        tc.fail(f"KNOWN entry no longer fails; remove it: {key!r}")


class TestCameraMoved(unittest.TestCase):
    maxDiff = None

    def _program(self, program: str) -> None:
        ns = load_spec(program, "a")
        ignore = CAMERA_IGNORE.get(program, [])
        for sc in _scenarios(program, pointer_free=True):
            for cam in (CAMERAS if FULL else CAMERAS[:2]):
                with self.subTest(scenario=sc, camera=cam):
                    msgs = program_oracles.camera_moved(program, ns, sc, cam, ignore=ignore)
                    _check(self, f"camera_moved | {program} | {sc}", msgs)


for _p in PROGRAMS:
    if _p not in CAMERA_EXCLUDED:
        setattr(TestCameraMoved, f"test_{_ident(_p)}",
                (lambda p: lambda self: self._program(p))(_p))


class TestTimeScaled(unittest.TestCase):
    maxDiff = None

    def _program(self, program: str) -> None:
        ns = load_spec(program, "a")
        for sc in _scenarios(program, pointer_free=False):
            for k in ((2.0, 0.5) if FULL else (2.0,)):
                with self.subTest(scenario=sc, k=k):
                    msgs = program_oracles.time_scaled(program, ns, sc, k)
                    _check(self, f"time_scaled | {program} | {sc}", msgs)


for _p in PROGRAMS:
    if _p not in TIME_EXCLUDED:
        setattr(TestTimeScaled, f"test_{_ident(_p)}",
                (lambda p: lambda self: self._program(p))(_p))


class TestRenameLayers(unittest.TestCase):
    maxDiff = None

    def _program(self, program: str) -> None:
        ns = load_spec(program, "a")
        for sc in _scenarios(program, pointer_free=False):
            with self.subTest(scenario=sc):
                msgs = program_oracles.tier_c(program, ns, sc, "rename_layers")
                _check(self, f"rename_layers | {program} | {sc}", msgs)


for _p in PROGRAMS:
    setattr(TestRenameLayers, f"test_{_ident(_p)}",
            (lambda p: lambda self: self._program(p))(_p))


class TestAxes(unittest.TestCase):
    def test_every_program_module_has_a_row(self):
        from source_support import iter_files
        here = os.path.dirname(os.path.abspath(__file__))
        mods = sorted(os.path.basename(f)[len("test_prog_"):-3]
                      for f in iter_files(here, ".py", recursive=False)
                      if os.path.basename(f).startswith("test_prog_"))
        rows = {_ident(p) for p in PROGRAMS}
        missing = [m for m in mods if m not in rows and m not in ("compose", "isolation", "invariance")]
        self.assertFalse(missing, f"program modules with no invariance row: {missing}")

    def test_exclusions_name_programs(self):
        for table in (CAMERA_EXCLUDED, TIME_EXCLUDED, CAMERA_IGNORE):
            for p in table:
                self.assertIn(p, PROGRAMS, p)

    def test_rename_layers_rewrites_only_author_layers(self):
        src = ('canvas.layers.create("track", below="default")\n'
               'r = Rect(layer="track")\nt = Text(layer="ui")\nx = canvas.layers["track"]\n')
        out = program_oracles.rename_layers(src)
        self.assertIn("'track_r'", out)
        self.assertNotIn("'ui_r'", out)
        self.assertNotIn("'default_r'", out)


class TestCanaries(unittest.TestCase):
    def test_camera_oracle_catches_physics_that_reads_the_zoom(self):
        from scena import canvas as _canvas
        from scena.input import Clock
        real = Clock.advance

        def zoom_scaled(self, dt, _r=real):
            _r(self, dt * float(_canvas.zoom or 1.0))     # world time follows the camera
        assert_catches(self, "test_prog_invariance.TestCameraMoved.test_bouncing_balls",
                       [(Clock, "advance", zoom_scaled)], "a world clock that reads the zoom")

    def test_time_oracle_catches_a_timer_on_real_time(self):
        import scena.process as proc
        from scena.input import Clock
        real = Clock.advance

        def unscaled(self, dt, _r=real):
            _r(self, dt)
            self._dt = dt          # world dt ignores the scale
        assert_catches(self, "test_prog_invariance.TestTimeScaled.test_bouncing_balls",
                       [(Clock, "advance", unscaled)], "a clock whose dt ignores clock.scale")


if __name__ == "__main__":
    unittest.main()
