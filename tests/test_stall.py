"""The stall watch (``scena/stall.py``): a frame, or the top level, that never
ends names the author line (persona probes PP).

``while not keyp("SPACE"): pass`` in ``update`` froze the window with no
message: the sync line watchdog is off by default. The watch thread reads a
per-frame stamp and prints one SCENA ERROR naming the line and the fix.

    python tests/run_tiers.py focused test_stall
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from program_support import ProgramRun  # noqa: E402
from scena import stall  # noqa: E402


def _program(body: str) -> str:
    d = tempfile.mkdtemp(prefix="stall_")
    path = os.path.join(d, "jogo.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(body).lstrip())
    return path


class TestStallWatch(unittest.TestCase):

    def setUp(self):
        for name, value in (("STALL_S", 0.3), ("TOP_LEVEL_STALL_S", 0.3), ("POLL_S", 0.02)):
            p = mock.patch.object(stall, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_a_frame_stuck_in_update_names_the_line_and_the_fix(self):
        path = _program("""
            import time
            from scena import *
            init(width=200, height=200)


            def update(dt):
                time.sleep(0.6)   # the stuck line


            run()
        """)
        err = io.StringIO()
        with redirect_stderr(err):
            run = ProgramRun(path)
            run.start()
            try:
                run.step(1)
            finally:
                run.close(strict=False)
        msg = err.getvalue()
        self.assertIn("SCENA ERROR: a frame has not finished", msg)
        self.assertIn("jogo.py:7 in update: time.sleep(0.6)", msg)
        self.assertIn("if instead of while", msg)
        self.assertEqual(msg.count("SCENA ERROR"), 1, "once per stall")

    def test_a_top_level_loop_names_its_line(self):
        path = _program("""
            import time
            from scena import *
            init(width=200, height=200)
            time.sleep(0.6)   # a loop of one's own
            run()
        """)
        err = io.StringIO()
        with redirect_stderr(err):
            run = ProgramRun(path)
            run.start()
            run.close(strict=False)
        msg = err.getvalue()
        self.assertIn("without reaching run()", msg)
        self.assertIn("jogo.py:4", msg)

    def test_a_report_keeps_nothing_of_the_program_alive(self):
        """The watch thread kept the main thread's frame it reported in its
        locals until the next stall: the frame's globals (the whole program)
        outlived the run. Under load, every game system test run hit the 8 s
        top-level watch at a sound bake, and the next run counted the last
        one's Box points as alive (oficina, ``registry.live 8 → 2``)."""
        import gc
        import weakref
        stalls = {
            "top level": "time.sleep(0.6)\nrun()",
            "frame": "def update(dt):\n    time.sleep(0.6)\n\n\nrun()",
        }
        for phase, tail in stalls.items():
            with self.subTest(phase=phase):
                path = _program(
                    "import time\nfrom scena import *\ninit(width=200, height=200)\n"
                    "QUADRO = Box(center=(50, 50), width=40, height=20)\n" + tail + "\n")
                err = io.StringIO()
                with redirect_stderr(err):
                    run = ProgramRun(path)
                    run.start()
                    try:
                        if phase == "frame":
                            run.step(1)
                        box = weakref.ref(run.ns["QUADRO"])
                    finally:
                        run.close(strict=False)
                self.assertIn("SCENA ERROR", err.getvalue())
                gc.collect()
                self.assertIsNone(box(), "a reported frame keeps the program alive")

    def test_a_quick_frame_says_nothing(self):
        path = _program("""
            from scena import *
            init(width=200, height=200)


            def update(dt):
                pass


            run()
        """)
        err = io.StringIO()
        with redirect_stderr(err):
            run = ProgramRun(path)
            run.start()
            try:
                run.step(30)
                time.sleep(0.4)          # idle between frames is not a stall
            finally:
                run.close(strict=False)
        self.assertNotIn("SCENA ERROR", err.getvalue())

    def test_a_test_modules_init_does_not_arm_the_top_level_watch(self):
        from scena import init
        stall._state[0] = None
        init(width=100, height=100)
        self.assertIsNone(stall._state[0])

    def _call_run(self, module_name):
        """``run()`` called from a namespace named ``module_name``, with the
        window and the main loop stubbed out; returns the ``arm`` mock."""
        from scena import orchestration as orch
        import scena.process as proc
        fw = orch.ScenaFramework.get_instance()
        with mock.patch.object(stall, "arm") as arm, \
                mock.patch.object(proc, "_top_level_ended", False), \
                mock.patch.object(type(fw), "run", lambda self: None), \
                mock.patch.object(type(fw), "open_window", lambda self: None), \
                mock.patch.object(type(fw), "set_auto_callbacks", lambda self, g: None), \
                mock.patch.object(fw, "_windowed", False), \
                mock.patch.object(fw, "_first_act", None):
            exec(compile("run()", "jogo.py", "exec"),
                 {"__name__": module_name, "run": orch.run})
        return arm

    def test_a_scripts_run_arms_the_frame_watch_without_init(self):
        # RA B1: a script with no init() of its own called run() and a stuck
        # frame froze the window with no message (only init() armed it).
        self.assertEqual(self._call_run("__main__").call_count, 1)

    def test_a_test_modules_run_does_not_arm(self):
        self.assertEqual(self._call_run("tests.algum").call_count, 0)



class TestEndedWithoutRun(unittest.TestCase):
    """``python jogo.py`` with no ``run()`` at the end opened no window and
    said nothing (persona probes PP). It says so at exit."""

    def run_script(self, body: str):
        import subprocess
        path = _program(body)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ, PYTHONPATH=root + os.pathsep + os.environ.get("PYTHONPATH", ""),
                   PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, path], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120,
                              cwd=os.path.dirname(path), env=env)

    def test_a_game_with_no_run_says_so(self):
        p = self.run_script("""
            from scena import *
            init(width=200, height=200)
            Circle(center=(100, 100), radius=20)
        """)
        self.assertIn("ended without run()", p.stderr)

    def test_a_crash_or_an_empty_script_says_nothing_more(self):
        p = self.run_script("""
            from scena import *
            init(width=200, height=200)
            Circle(center=(100, 100), radius=20)
            raise SystemExit(f"{undefined_name}")
        """)
        self.assertNotIn("ended without run()", p.stderr)
        p = self.run_script("""
            from scena import *
            print(Color("red"))
        """)
        self.assertNotIn("ended without run()", p.stderr)


if __name__ == "__main__":
    unittest.main()
