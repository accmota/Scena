"""File dialogs: backend choice, cancel, extension, one at a time (mocked).

Run: python -m unittest scena_editor.tests.test_editor_dialogs
"""
import os
import shutil
import sys
import threading
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from scena_editor import dialogs  # noqa: E402


class OsascriptException(Exception):
    pass


def fake_cfd(**fns):
    module = types.SimpleNamespace(open_file=lambda **k: None, save_file=lambda **k: None)
    for name, fn in fns.items():
        setattr(module, name, fn)
    return module


class TestBackends(unittest.TestCase):
    """crossfiledialog's Open path (Windows / Linux); macOS: TestMacOpen."""

    def setUp(self):
        patcher = mock.patch.object(dialogs, "MACOS", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_crossfiledialog_result_is_absolute(self):
        cfd = fake_cfd(open_file=lambda **k: "rel/fase.json")
        with mock.patch.object(dialogs, "_crossfiledialog", return_value=cfd):
            self.assertEqual(dialogs.open_level("/x"), os.path.abspath("rel/fase.json"))

    def test_macos_cancel_is_none_not_an_error_and_no_fallback(self):
        def cancel(**k):
            raise OsascriptException("execution error: User canceled. (-128)")
        cfd = fake_cfd(open_file=cancel, save_file=cancel)
        with mock.patch.object(dialogs, "_crossfiledialog", return_value=cfd), \
                mock.patch.object(dialogs, "_tk") as tk:
            self.assertIsNone(dialogs.open_level("/x"))
            self.assertIsNone(dialogs.save_level_as("/x"))
            self.assertIsNone(dialogs.choose_image("/x"))
        tk.assert_not_called()

    def test_missing_or_broken_crossfiledialog_falls_back_to_tk(self):
        with mock.patch.object(dialogs, "_crossfiledialog", return_value=None), \
                mock.patch.object(dialogs, "_tk", return_value="/a/b.json") as tk:
            self.assertEqual(dialogs.open_level("/start", "Open"), os.path.abspath("/a/b.json"))
        tk.assert_called_once_with("open", "Open", "/start")

        def broken(**k):
            raise RuntimeError("zenity crashed")
        with mock.patch.object(dialogs, "_crossfiledialog",
                               return_value=fake_cfd(open_file=broken)), \
                mock.patch.object(dialogs, "_tk", return_value="/a/c.png") as tk:
            self.assertEqual(dialogs.choose_image("/s"), os.path.abspath("/a/c.png"))

    def test_env_forces_tk(self):
        with mock.patch.dict(os.environ, {"SCENA_EDITOR_DIALOGS": "tk"}):
            self.assertIsNone(dialogs._crossfiledialog())

    def test_save_adds_json_when_missing(self):
        cfd = fake_cfd(save_file=lambda **k: "/levels/fase1")
        with mock.patch.object(dialogs, "_crossfiledialog", return_value=cfd):
            self.assertEqual(dialogs.save_level_as("/levels"),
                             os.path.abspath("/levels/fase1.json"))
        cfd = fake_cfd(save_file=lambda **k: "/levels/fase2.JSON")
        with mock.patch.object(dialogs, "_crossfiledialog", return_value=cfd):
            self.assertEqual(dialogs.save_level_as("/levels"),
                             os.path.abspath("/levels/fase2.JSON"))

    def test_tk_command_line(self):
        out = types.SimpleNamespace(stdout="/p/x.json\n")
        with mock.patch.object(dialogs.subprocess, "run", return_value=out) as run:
            self.assertEqual(dialogs._tk("save", "T", "/d", "a.json"), "/p/x.json")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[1:], ["-m", "scena_editor._tkdialog", "save", "T", "/d", "a.json"])
        empty = types.SimpleNamespace(stdout="")
        with mock.patch.object(dialogs.subprocess, "run", return_value=empty):
            self.assertIsNone(dialogs._tk("open", "T", "/d"))

    def test_tk_child_output_is_utf8_on_every_os(self):
        # The child prints the chosen path. Windows pipes default to the locale
        # (cp1252): a path outside it crashed the child, and an inherited
        # PYTHONIOENCODING=utf-8 garbled it on the way back. Both ends pin UTF-8.
        out = types.SimpleNamespace(stdout="/níveis/日本.json\n")
        with mock.patch.object(dialogs.subprocess, "run", return_value=out) as run:
            self.assertEqual(dialogs._tk("open", "T", "/d"), "/níveis/日本.json")
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["env"]["PYTHONIOENCODING"], "utf-8")


class TestMacOpen(unittest.TestCase):
    """macOS Open dialogs are our AppleScript with UTIs: crossfiledialog's
    ``of type {"json"}`` (an extension) matched no file — all grayed out."""

    def setUp(self):
        for target, value in ((dialogs, "MACOS"), ):
            patcher = mock.patch.object(target, value, True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cfd = fake_cfd(open_file=mock.Mock(side_effect=AssertionError("not on macOS")))
        patcher = mock.patch.object(dialogs, "_crossfiledialog", return_value=self.cfd)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _types(script):
        inner = script.split("of type {", 1)[1].split("}", 1)[0]
        return [t.strip().strip('"') for t in inner.split(",")]

    def test_every_open_dialog_filters_by_uti_never_by_extension(self):
        scripts = []
        def run(script):
            scripts.append(script)
            return "/levels/fase1.json"
        with mock.patch.object(dialogs, "_osascript", side_effect=run):
            self.assertEqual(dialogs.open_level("/levels", "Open level"),
                             os.path.abspath("/levels/fase1.json"))
            dialogs.choose_image("/art")
            dialogs.choose_atlas("/art")
        self.assertEqual(len(scripts), 3)
        self.assertEqual(self._types(scripts[0]), ["public.json"])
        # The Image tool takes a picture or a spritesheet's atlas.
        self.assertEqual(self._types(scripts[1]), ["public.image", "public.xml", "public.json"])
        self.assertEqual(self._types(scripts[2]), ["public.xml", "public.json"])
        for script in scripts:
            for uti in self._types(script):
                # A UTI has a dot; "json" / "png" are extensions and match nothing.
                self.assertIn(".", uti, script)
                self.assertNotIn(uti, dialogs.IMAGE_TYPES + dialogs.ATLAS_TYPES)
        self.assertIn('default location POSIX file "/levels"', scripts[0])
        self.cfd.open_file.assert_not_called()

    def test_cancel_is_none_and_no_fallback(self):
        err = RuntimeError("execution error: User canceled. (-128)")
        with mock.patch.object(dialogs, "_osascript", side_effect=err), \
                mock.patch.object(dialogs, "_tk") as tk:
            self.assertIsNone(dialogs.open_level("/x"))
            self.assertIsNone(dialogs.choose_image("/x"))
        tk.assert_not_called()

    def test_quotes_and_backslashes_are_escaped(self):
        script = dialogs.choose_file_script('Open "a"', '/U/x\\y', ("public.json",))
        self.assertIn('prompt "Open \\"a\\""', script)
        self.assertIn('POSIX file "/U/x\\\\y"', script)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("osacompile"),
                         "macOS AppleScript compiler")
    def test_script_compiles_with_the_real_applescript(self):
        """Syntax only: osacompile builds the script without running it."""
        import subprocess
        import tempfile
        for utis in (dialogs.LEVEL_UTIS, dialogs.IMAGE_UTIS):
            script = dialogs.choose_file_script('Open "level"', "/tmp", utis)
            with tempfile.TemporaryDirectory() as d:
                out = subprocess.run(["osacompile", "-o", os.path.join(d, "s.scpt"),
                                      "-e", script], capture_output=True, encoding="utf-8")
            self.assertEqual(out.returncode, 0, out.stderr)


class TestRunner(unittest.TestCase):
    def test_threaded_result_arrives_through_poll_with_after(self):
        gate = threading.Event()
        got, after = [], []
        r = dialogs.Runner(threaded=True, after=lambda: after.append(1))
        self.assertTrue(r.start(lambda: gate.wait(2) and "/x.json", got.append))
        self.assertTrue(r.busy)
        r.poll()
        self.assertEqual(got, [])                     # still open
        self.assertFalse(r.start(lambda: "/y.json", got.append))   # one at a time
        gate.set()
        for _ in range(200):
            r.poll()
            if got:
                break
            time.sleep(0.005)
        self.assertEqual(got, ["/x.json"])
        self.assertEqual(after, [1])
        self.assertFalse(r.busy)

    def test_inline_runner_and_a_crashing_dialog_is_a_cancel(self):
        got = []
        r = dialogs.Runner(threaded=False)
        r.start(lambda: 1 / 0, got.append)
        self.assertEqual(got, [None])
        self.assertFalse(r.busy)


if __name__ == "__main__":
    unittest.main()
