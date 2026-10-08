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
        for prog in ("bouncing_balls", "snake_chain", "examples/naves.py",
                     "examples/pegar_estrelas.py", "examples/cadeia_de_bolas.py",
                     "platformer", "galaga_acts"):
            with self.subTest(prog=prog):
                with open(program_path(prog), encoding="utf-8") as fh:
                    self.assertTrue(O._group_names(ast.parse(fh.read())), "vacuous rename")

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
