"""The program-model harness itself (tests/program_support.py, program_oracles.py).

Input reaches the program through the real window handlers inside the frame's
poll; probes and marks land on the right frame; a run leaves nothing behind;
the spec vocabulary and the ledger guard behave. Strategy: design/Testing
Design.md, "Program model tests".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import program_ledger  # noqa: E402
from program_support import (  # noqa: E402
    ProbeError, ProgramRun, Trace, Sample, always, at_end, close, eventually,
    never, steady,
)
from system_support import zombies  # noqa: E402


class TestInputDelivery(unittest.TestCase):
    def test_a_second_press_with_no_release_is_the_harness_error(self):
        """A window never sends it (GLFW makes it a REPEAT): the run refuses
        it rather than hand the engine a stream the I1 model reads as an
        engine fault (chaos caverna/volta ``key-down-twice``)."""
        from program_support import PressedTwice
        with ProgramRun("input_probe") as run:
            run.key_down("SPACE")
            run.step(1)
            run.key_up("SPACE")
            run.key_down("SPACE")            # up then down: a fresh press
            run.step(1)
            run.key_down("SPACE")
            with self.assertRaisesRegex(PressedTwice, "SPACE.*pressed twice"):
                run.step(1)

    def test_key_reaches_callbacks_and_keyp_on_the_next_frame(self):
        with ProgramRun("input_probe") as run:
            run.step(2)
            run.key_down("SPACE")
            run.step(3)
            run.key_up("SPACE")
            run.step(2)
            downs = run.trace.marks("key_down")
            ups = run.trace.marks("key_up")
            self.assertEqual([(e.frame, e.data["key"]) for e in downs], [(3, "SPACE")])
            self.assertEqual([(e.frame, e.data["key"]) for e in ups], [(6, "SPACE")])
            # keyp is a level: held for the frames between press and release.
            self.assertEqual(len(run.ns["held"]), 3)

    def test_click_reaches_a_widget_and_not_the_script(self):
        with ProgramRun("input_probe") as run:
            run.play([("wait", 1), ("click_widget", "Go"), ("wait", 1)])
            self.assertEqual(len(run.trace.marks("button")), 1)
            self.assertEqual(run.trace.marks("mouse_click"), [])
            self.assertEqual(run.view.st.clicks, 1)

    def test_world_click_coordinates_follow_the_camera(self):
        for zoom in (None, 2.0):
            with self.subTest(zoom=zoom), ProgramRun("input_probe", {"zoom": zoom}) as run:
                run.play([("click", 500.0, 400.0, "left")])
                (e,) = run.trace.marks("mouse_click")
                # View (500, 400) is world (500, 400) without a camera; with zoom
                # 2 about the view centre (400, 300) it is (450, 350).
                want = (500.0, 400.0) if zoom is None else (450.0, 350.0)
                self.assertAlmostEqual(e.data["x"], want[0], places=6)
                self.assertAlmostEqual(e.data["y"], want[1], places=6)

    def test_scroll_and_cell_steps(self):
        with ProgramRun("input_probe") as run:
            run.play([("move", 100.0, 100.0), ("scroll", 0.0, -1.0),
                      ("set_cell", "st.clicks", 7)])
            self.assertEqual([e.data["dy"] for e in run.trace.marks("scroll")], [-1.0])
            self.assertEqual(run.view.st.clicks, 7)

    def test_inputs_are_logged_with_their_frame(self):
        with ProgramRun("input_probe") as run:
            run.play([("wait", 2), ("key", "A", 1)])
            self.assertEqual(run.trace.input_frame("key"), 3)
            self.assertEqual(run.trace.input_frame("key", 1), 4)


class TestProbesAndTeardown(unittest.TestCase):
    def test_probe_values_are_frozen_and_errors_recorded(self):
        probes = {"center": lambda p: p.target.center,
                  "boom": lambda p: p.no_such_global,
                  "t": lambda p: p.clock.time}
        with ProgramRun("input_probe", probes=probes) as run:
            run.step(2)
            s = run.trace.samples[-1]
            self.assertEqual(s.values["center"], (600.0, 300.0))
            self.assertIsInstance(s.values["boom"], ProbeError)
            self.assertAlmostEqual(s.values["t"], 2 / 60)
            self.assertEqual(run.trace.errors()[0][1], "boom")

    def test_a_run_leaves_nothing_behind(self):
        run = ProgramRun("input_probe")
        run.start()
        run.play([("click_widget", "Go"), ("wait", 3)])
        run.close()
        self.assertEqual(run.leftovers(), {})
        self.assertEqual(zombies(), [])

    def test_the_freeze_budget_is_no_wall_clock_in_a_run(self):
        # A run counts frames: the 0.5 s wall-clock budget for one async step
        # cut a long build under the gate's load, and law E1 saw one pacing
        # make fewer Lines (string_theory, 0.10.0 gate). A run lifts the
        # default budget and gives it back; a test's own budget stays.
        from unittest import mock
        import scena.process as proc
        default = proc.WATCHDOG_RESUME_S
        with ProgramRun("input_probe"):
            self.assertGreaterEqual(proc.WATCHDOG_RESUME_S, 5.0)
        self.assertEqual(proc.WATCHDOG_RESUME_S, default)
        with mock.patch.object(proc, "WATCHDOG_RESUME_S", 0.05):
            with ProgramRun("input_probe"):
                self.assertEqual(proc.WATCHDOG_RESUME_S, 0.05)

    def test_a_harness_run_lifts_the_freeze_budget_too(self):
        # The example scripts of the laws (E1, E3, E15) run in a child process
        # through tests/script_harness.py, not through ProgramRun: the lift
        # above never reached them, and E1 failed again under load.
        import subprocess
        import tempfile
        here = os.path.dirname(os.path.abspath(__file__))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "budget.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("import scena.process as p\nprint('BUDGET', p.WATCHDOG_RESUME_S)\n"
                         "from scena import *\ninit(width=200, height=100)\nrun()\n")
            out = subprocess.run([sys.executable, os.path.join(here, "script_harness.py"), path, "2"],
                                 capture_output=True, text=True, encoding="utf-8", timeout=120).stdout
        budget = float(out.split("BUDGET", 1)[1].split()[0])
        self.assertGreaterEqual(budget, 5.0, out)

    def test_leftovers_from_another_module_are_not_the_programs(self):
        # The deep serial pass runs every module in one process: actors an
        # earlier module left alive are parked while the program runs and
        # resumed at close. Both censuses must see them in the same state —
        # census_before was taken after parking, census_after after resuming,
        # and every parked drawn actor read as the program's leak (draw_live
        # 1608 -> 1610 in 43 teardown checks). A hidden Point on a layer also
        # came back off it (park / resume was not an identity).
        from scena import Circle, Point
        shown = Circle(center=(0, 0), radius=5)
        marker = Point(0, 0)
        marker.visible = True            # on 'top'; parking takes it off
        hidden = Point(0, 0)
        hidden.layer = "default"
        try:
            run = ProgramRun("input_probe")
            run.start()
            run.play([("wait", 2)])
            run.close()
            self.assertEqual(run.leftovers(), {})
            self.assertTrue(shown.active and shown.visible)
            self.assertEqual((marker.layer, marker.visible), ("top", True))
            self.assertEqual(hidden.layer, "default")
        finally:
            for obj in (shown, marker, hidden):
                obj.destroy()

    def test_a_program_starts_with_an_empty_st_and_gives_back_the_old_cells(self):
        # Deep serial pass 2026-10-22: a game wrote ``st.pontos`` over a cell
        # an earlier module left; the program reused it and the node its HUD
        # link gave that cell outlived the run (LEFTOVERS graph.nodes 24 -> 25).
        # A program has its own process: it starts with no cells, and the
        # cells other modules made come back, the same objects, at close.
        from scena import st
        st.pontos = 7
        old = st._data["pontos"]
        self.addCleanup(lambda: st._data.get("pontos") is not None and st.remove("pontos"))
        source = (
            "from scena import *\n"
            "SEEN = sorted(st.keys())\n"
            "st.pontos = 0\n"
            "placar = Text('')\n"
            "placar['text'] @= lambda: f'Pontos {st.pontos}'\n"
            "def update(dt):\n"
            "    st.pontos += 1\n"
            "run()\n"
        )
        with ProgramRun("input_probe", source=source,
                        probes={"t": lambda p: p.placar.text}) as run:
            self.assertEqual(run.ns["SEEN"], [])
            run.step(2)
            self.assertEqual(run.trace.end("t"), "Pontos 2")
        self.assertIs(st._data["pontos"], old)
        self.assertEqual(st.pontos, 7)
        self.assertEqual(run.leftovers(), {})

    def test_a_program_starts_from_fresh_world_settings(self):
        # O8: test_noop_cost / test_closed_surfaces left the auto playfield
        # pinned to 400x300 edges; naves and galaga (1000x800) lost their shots
        # at that stale edge, in the serial pass only. A real program starts
        # in a fresh process: the run starts from the framework defaults
        # (system_support.reset_world_settings) and gives back what it found.
        from scena import canvas
        from scena.act import WORLD_SETTINGS
        setting = {w.name: w for w in WORLD_SETTINGS}["playfield"]
        found = setting.snapshot()
        pf = canvas.playfield
        pf.left = pf.left - 123                  # another module's leftover
        left_behind = setting.snapshot()
        try:
            with ProgramRun("input_probe", probes={"pf": lambda p: setting.snapshot()}) as run:
                run.step(1)
                self.assertEqual(run.trace.end("pf"), (0.25, None))   # the default: auto edges
            self.assertEqual(setting.snapshot(), left_behind)
            self.assertEqual(run.leftovers(), {})
        finally:
            setting.restore(found)

    def test_probes_read_the_live_namespace(self):
        # A global the program rebinds during frames (``global frames_seen``)
        # is what the probe reads: the namespace is the program's own, not a copy.
        with ProgramRun("input_probe", probes={"n": lambda p: p.frames_seen}) as run:
            run.step(3)
            self.assertEqual(run.trace.values("n"), [1, 2, 3])

    def test_the_program_is_main_for_the_whole_run(self):
        main_before = sys.modules["__main__"]
        cwd = os.getcwd()
        with ProgramRun("examples/pegar_estrelas.py") as run:
            run.step(1)
            self.assertEqual(sys.modules["__main__"].__file__, run.path)
            from scena.sprite import _resolve_image_path
            self.assertIsNotNone(_resolve_image_path("k-rolling-ball/star.png"))
        self.assertIs(sys.modules["__main__"], main_before)
        self.assertEqual(os.getcwd(), cwd)

    def test_the_program_must_call_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "norun.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("from scena import *\n")
            run = ProgramRun(path)
            with self.assertRaises(AssertionError):
                run.start()
            run.close(strict=False)


def _trace(values):
    t = Trace()
    t.samples = [Sample(i + 1, (i + 1) / 60, {"v": v}) for i, v in enumerate(values)]
    return t


class TestDrawReachesThePixels(unittest.TestCase):
    """HV1 (game system tests, 2026-10-10): a program's ``init()`` rebuilt the
    canvas the engine paints on, so every ProgramRun draw went elsewhere: the
    screen read back blank, and ``program_oracles.cull_pixels`` compared two
    blank images (vacuous for every program, all of which call ``init``)."""

    PROGRAM = (
        "from scena import *\n"
        "init(width=1000, height=700)\n"
        "c = Circle(center=(200, 500), radius=40, color='red')\n"
        "run()\n"
    )

    def _run(self, draw_steps):
        import tempfile
        import numpy as np
        import skia
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hv1_prog.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.PROGRAM)
            with ProgramRun(path, draw=True) as run:
                draw_steps(run)
                a = np.asarray(run.world.surface.makeImageSnapshot().toarray(
                    colorType=skia.kRGBA_8888_ColorType))
                sx, sy = run._to_screen(200, 500)
                return a[int(sy), int(sx)][:3].tolist()

    def test_a_drawn_frame_shows_the_program(self):
        r, g, b = self._run(lambda run: run.step(2))
        self.assertGreater(r, 150, "the program's red circle is not in the drawn frame")

    def test_a_checkpoint_draw_shows_the_program(self):
        def steps(run):
            run.step(3, draw=False)
            run.step(1, dt=0.0, draw=True)
        r, g, b = self._run(steps)
        self.assertGreater(r, 150)

    def test_cull_pixels_is_not_vacuous(self):
        import program_oracles
        from program_support import Scenario
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hv1_blank.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("from scena import *\ninit(width=400, height=300)\nrun()\n")
            ns = {"SCENARIOS": {"s": Scenario(steps=[("wait", 2)])}, "PROBES": {}}
            msgs = program_oracles.cull_pixels(path, ns, "s")
        self.assertTrue(msgs and "nothing was drawn" in msgs[0], msgs)


class TestSpecVocabulary(unittest.TestCase):
    def test_checks(self):
        t = _trace([1, 2, 3, 3, ProbeError("X", "boom")])
        self.assertIsNone(always("v", lambda v: v >= 1, until=4)(t))
        self.assertIn("frame 5", always("v", lambda v: v >= 1)(t))
        self.assertIsNone(never("v", lambda v: v == 9, until=4)(t))
        self.assertIsNone(eventually("v", lambda v: v == 3, within=3)(t))
        self.assertIsNotNone(eventually("v", lambda v: v == 3, within=1)(t))
        self.assertIsNone(steady("v", after=3)(_trace([1, 2, 3, 3])))
        self.assertIsNotNone(at_end("v", lambda v: v == 3)(t))     # a ProbeError fails
        self.assertTrue(close((1.0, 2.0), (1.0, 2.0 + 1e-9), 1e-6))
        self.assertFalse(close((1.0,), (1.0, 2.0)))


class TestTierC(unittest.TestCase):
    def test_every_program_has_group_names_to_rename(self):
        import ast
        import program_oracles as O
        from program_support import program_path
        for prog in ("bouncing_balls", "snake_chain", "examples/naves_1.py",
                     "examples/pegar_estrelas.py", "examples/cadeia_de_bolas.py",
                     "platformer", "galaga_acts"):
            with self.subTest(prog=prog):
                with open(program_path(prog), encoding="utf-8") as fh:
                    self.assertTrue(O._group_names(ast.parse(fh.read())), "vacuous rename")

    def test_a_rename_leaves_cell_and_field_keys_alone(self):
        # cadeia_de_bolas: "linhas" is a group and an st cell. Since 0.8.0 the
        # checkbox takes st["linhas"], and renaming that key asked for a cell
        # the program never made (gate, 2026-10-11).
        import program_oracles as O
        src = ('st.linhas = True\n'
               'Line(p1=(0, 0), p2=(1, 1), group="linhas")\n'
               'group["linhas"].destroy()\n'
               'CheckBox(st["linhas"], label="Linhas")\n'
               'bola["linhas"] @= lambda: 1\n')
        out = O.rename_groups(src)
        self.assertIn("group='linhas_r'", out)
        self.assertIn("group['linhas_r']", out)
        self.assertIn("st['linhas']", out)
        self.assertIn("bola['linhas']", out)
        src = ('Circle(radius=1, layer="fundo")\n'
               'canvas.layers["fundo"].visible = False\n'
               'st["fundo"] = 1\n')
        out = O.rename_layers(src)
        self.assertIn("layer='fundo_r'", out)
        self.assertIn("canvas.layers['fundo_r']", out)
        self.assertIn("st['fundo']", out)

    def test_a_broken_rewrite_is_caught(self):
        # Canary: renaming group= but not group["..."] changes the program.
        import ast
        from unittest import mock
        import program_oracles as O
        from program_support import load_spec

        def half_rename(src):
            tree = ast.parse(src)

            class R(ast.NodeTransformer):
                def visit_keyword(self, node):
                    if node.arg == "group" and isinstance(node.value, ast.Constant):
                        node.value = ast.Constant(node.value.value + "_r")
                    return node
            return ast.unparse(R().visit(tree))
        with mock.patch.dict(O.TIER_C, {"half": half_rename}):
            msgs = O.tier_c("bouncing_balls", load_spec("bouncing_balls", "a"), "start", "half")
        self.assertTrue(msgs, "a rewrite that changes the program went unnoticed")


class TestLedger(unittest.TestCase):
    def test_entries_are_well_formed(self):
        for key, (verdict, cause, note) in program_ledger.OPEN.items():
            with self.subTest(key=key):
                self.assertEqual(len(key), 3)
                self.assertIn(verdict, program_ledger.VERDICTS)
                self.assertIn(cause, program_ledger.CAUSES)
                self.assertRegex(note, r"PM\d+")

    def test_revised_expectations_name_a_cause(self):
        from program_support import PROGRAMS, load_spec
        from source_support import iter_files
        for path in iter_files(PROGRAMS, ".py", recursive=False):
            name = os.path.basename(path)
            if "_spec_" not in name:
                continue
            program, letter = name[:-3].split("_spec_")
            for e in load_spec(program, letter)["EXPECT"]:
                if e.revised:
                    with self.subTest(spec=name, expect=e.id):
                        self.assertIn(e.revised.split(":")[0], program_ledger.CAUSES)


if __name__ == "__main__":
    unittest.main()
