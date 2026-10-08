"""Starting the editor: the command, the launcher icons, the error log, packaging.

The shortcut builders write into a temporary home; system tools (PowerShell,
iconutil) are faked, except iconutil on macOS where it is real.

Run: python -m unittest scena_editor.tests.test_editor_launch
"""
import contextlib
import io
import os
import plistlib
import shutil
import stat
import struct
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from scena_editor import log, shortcut  # noqa: E402
from scena_editor.__main__ import _parse, main  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n"


class TempHome(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="scena_editor_home_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.calls = []

    def fake_run(self, cmd, env):
        self.calls.append((cmd, env))


class TestIcon(unittest.TestCase):
    def test_png_sizes(self):
        import skia
        for size in (16, 256):
            data = shortcut.icon_png(size)
            self.assertTrue(data.startswith(PNG))
            image = skia.Image.MakeFromEncoded(skia.Data.MakeWithCopy(data))
            self.assertEqual((image.width(), image.height()), (size, size))

    def test_ico_wraps_one_png(self):
        png = shortcut.icon_png(256)
        ico = shortcut.icon_ico(png)
        reserved, kind, count = struct.unpack("<HHH", ico[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 1))
        size, offset = struct.unpack("<II", ico[14:22])
        self.assertEqual((size, offset), (len(png), 22))
        self.assertEqual(ico[22:], png)


class TestShortcuts(TempHome):
    def test_linux_desktop_entry(self):
        os.makedirs(os.path.join(self.home, "Desktop"))
        python = os.path.abspath("/opt/py/bin/python3")   # create() resolves it on the host
        made = shortcut.create("linux", python=python, home=self.home, env={},
                               run=self.fake_run)
        menu = os.path.join(self.home, ".local", "share", "applications", "scena-editor.desktop")
        self.assertEqual(made, [menu, os.path.join(self.home, "Desktop", "scena-editor.desktop")])
        with open(menu, encoding="utf-8") as f:
            entry = f.read()
        self.assertIn(f'Exec="{python}" -m scena_editor %f', entry)
        self.assertIn("Terminal=false", entry)
        icon = [line.split("=", 1)[1] for line in entry.splitlines() if line.startswith("Icon=")][0]
        with open(icon, "rb") as f:
            self.assertTrue(f.read().startswith(PNG))
        if os.name != "nt":   # Windows has no exec bit: st_mode follows the extension
            self.assertTrue(os.stat(menu).st_mode & stat.S_IXUSR)
        self.assertEqual(self.calls, [])

    def test_windows_shortcuts_through_powershell(self):
        bindir = os.path.join(self.home, "Python", "Scripts")
        os.makedirs(bindir)
        python = os.path.join(bindir, "python.exe")
        open(os.path.join(bindir, "pythonw.exe"), "w", encoding="utf-8").close()
        env = {"APPDATA": os.path.join(self.home, "Roaming"),
               "LOCALAPPDATA": os.path.join(self.home, "Local")}
        made = shortcut.create("win32", python=python, home=self.home, env=env, run=self.fake_run)
        (cmd, values), = self.calls
        self.assertEqual(cmd[0], "powershell")
        self.assertIn("CreateShortcut", cmd[-1])
        self.assertIn("-m scena_editor", cmd[-1])
        self.assertEqual(values["SCENA_LNK_TARGET"], os.path.join(bindir, "pythonw.exe"))
        self.assertTrue(values["SCENA_LNK_MENU"].endswith(os.path.join("Programs", "Scena Editor.lnk")))
        with open(values["SCENA_LNK_ICON"], "rb") as f:
            self.assertEqual(struct.unpack("<HHH", f.read(6)), (0, 1, 1))
        self.assertEqual(made[0], values["SCENA_LNK_MENU"])

    def fake_mac_tools(self, cmd, env):
        """osacompile / iconutil / codesign, faked: write what they would."""
        self.calls.append((cmd, env))
        if cmd[0] == "osacompile":
            app = cmd[cmd.index("-o") + 1]
            res = os.path.join(app, "Contents", "Resources")
            os.makedirs(os.path.join(app, "Contents", "MacOS"))
            os.makedirs(os.path.join(res, "Scripts"))
            open(os.path.join(res, "Assets.car"), "wb").close()
            open(os.path.join(res, "applet.icns"), "wb").close()
            with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
                plistlib.dump({"CFBundleExecutable": "applet", "CFBundleIconFile": "applet",
                               "CFBundleIconName": "applet", "CFBundleName": "x"}, f)
        elif cmd[0] == "iconutil":
            with open(cmd[cmd.index("-o") + 1], "wb") as f:
                f.write(b"icns-from-iconutil")

    def test_macos_applet(self):
        python = os.path.abspath("/opt/py 3/bin/python3")  # the space: quoted form of py
        made = shortcut.create("darwin", python=python, home=self.home, env={},
                               run=self.fake_mac_tools)
        app = os.path.join(self.home, "Applications", "Scena Editor.app")
        self.assertEqual(made, [app])
        tools = [cmd[0] for cmd, _env in self.calls]
        self.assertEqual(tools, ["osacompile", "iconutil", "codesign"])   # signed last
        script = self.calls[0][0][-1]
        self.assertIn('set py to "' + python.replace("\\", "\\\\") + '"', script)
        self.assertIn("quoted form of py", script)
        self.assertIn("-m scena_editor", script)
        self.assertTrue(script.rstrip('"').endswith("&"))          # starts it and quits
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            info = plistlib.load(f)
        self.assertEqual((info["CFBundleName"], info["CFBundleIdentifier"]),
                         ("Scena Editor", shortcut.BUNDLE_ID))
        self.assertNotIn("CFBundleIconName", info)                 # applet.icns is used
        res = os.path.join(app, "Contents", "Resources")
        self.assertFalse(os.path.exists(os.path.join(res, "Assets.car")))
        with open(os.path.join(res, "applet.icns"), "rb") as f:
            self.assertEqual(f.read(), b"icns-from-iconutil")
        # Running it again replaces the app (a reinstalled Python).
        new = os.path.abspath("/new/python3")
        shortcut.create("darwin", python=new, home=self.home, env={},
                        run=self.fake_mac_tools)
        self.assertIn(shortcut._applescript_string(new), self.calls[3][0][-1])

    @unittest.skipUnless(sys.platform == "darwin", "osacompile / codesign are macOS tools")
    def test_macos_applet_with_the_real_tools(self):
        """A native universal executable (no Rosetta prompt on Apple Silicon),
        a valid signature after our edits, and our icon."""
        import subprocess
        shortcut.create("darwin", python=sys.executable, home=self.home, env={})
        app = os.path.join(self.home, "Applications", "Scena Editor.app")
        arch = subprocess.run(["lipo", "-archs", os.path.join(app, "Contents", "MacOS", "applet")],
                              capture_output=True, encoding="utf-8").stdout.split()
        self.assertIn("arm64", arch)
        self.assertIn("x86_64", arch)
        verify = subprocess.run(["codesign", "--verify", "--deep", "--strict", app],
                                capture_output=True, encoding="utf-8")
        self.assertEqual(verify.returncode, 0, verify.stderr)
        with open(os.path.join(app, "Contents", "Resources", "applet.icns"), "rb") as f:
            self.assertEqual(f.read(4), b"icns")


class TestLegacyLaunchers(TempHome):
    """``scena-editor --shortcut`` removes the launchers ``stage-editor
    --shortcut`` made before 0.6.0, and nothing else."""

    def _touch(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()

    def test_macos_removes_the_old_app(self):
        old = os.path.join(self.home, "Applications", "Stage Editor.app")
        os.makedirs(os.path.join(old, "Contents"))
        keep = os.path.join(self.home, "Applications", "Scena Editor.app")
        os.makedirs(keep)
        self.assertEqual(shortcut.remove_legacy("darwin", home=self.home, env={}), [old])
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(keep))

    def test_windows_removes_links_and_icon_but_keeps_old_logs(self):
        env = {"APPDATA": os.path.join(self.home, "R"), "LOCALAPPDATA": os.path.join(self.home, "L")}
        paths = shortcut.legacy_paths("win32", self.home, env)
        for p in paths:
            self._touch(p)
        old_log = os.path.join(self.home, "L", "Stage Editor", "editor.log")
        self._touch(old_log)
        self.assertEqual(shortcut.remove_legacy("win32", home=self.home, env=env), paths)
        self.assertFalse(any(os.path.exists(p) for p in paths))
        self.assertTrue(os.path.exists(old_log))

    def test_linux_removes_desktop_entries_and_icon(self):
        paths = shortcut.legacy_paths("linux", self.home, {})
        for p in paths:
            self._touch(p)
        self.assertEqual(shortcut.remove_legacy("linux", home=self.home, env={}), paths)
        self.assertFalse(any(os.path.exists(p) for p in paths))

    def test_nothing_to_remove(self):
        for platform in ("darwin", "win32", "linux"):
            self.assertEqual(shortcut.remove_legacy(platform, home=self.home, env={}), [])

    def test_the_command_reports_what_it_removed(self):
        out = io.StringIO()
        with mock.patch.object(shortcut, "create", return_value=["/x/Scena Editor.app"]), \
                mock.patch.object(shortcut, "remove_legacy", return_value=["/x/Stage Editor.app"]), \
                contextlib.redirect_stdout(out):
            self.assertEqual(main(["--shortcut"]), 0)
        self.assertIn("/x/Stage Editor.app", out.getvalue())
        self.assertIn("old Stage Editor launcher", out.getvalue())


class TestLog(TempHome):
    def test_paths_per_system(self):
        self.assertEqual(log.log_path("darwin", self.home, {}),
                         os.path.join(self.home, "Library", "Logs", "Scena Editor", "editor.log"))
        self.assertEqual(log.log_path("win32", self.home, {"LOCALAPPDATA": "L"}),
                         os.path.join("L", "Scena Editor", "editor.log"))
        self.assertEqual(log.log_path("linux", self.home, {}),
                         os.path.join(self.home, ".local", "state", "scena-editor", "editor.log"))

    def test_write_append_and_start_over_when_big(self):
        path = os.path.join(self.home, "logs", "editor.log")
        try:
            raise ValueError("first")
        except ValueError as e:
            self.assertEqual(log.write_error(e, "here", path), path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("ValueError: first", text)
        self.assertIn("here", text)
        with open(path, "a", encoding="utf-8") as f:
            f.write("x" * (log.MAX_BYTES + 1))
        log.write_error(RuntimeError("second"), "", path)
        with open(path, encoding="utf-8") as f:
            self.assertIn("second", f.read())
        self.assertTrue(os.path.exists(path + ".1"))

    def test_an_unwritable_log_never_raises(self):
        blocker = os.path.join(self.home, "file")
        open(blocker, "w", encoding="utf-8").close()
        log.write_error(RuntimeError("x"), "", os.path.join(blocker, "sub", "editor.log"))


class TestCommand(unittest.TestCase):
    def test_arguments(self):
        self.assertEqual(_parse([]).level, None)
        self.assertEqual(_parse(["fase.json"]).level, "fase.json")
        self.assertTrue(_parse(["--shortcut"]).shortcut)

    def test_shortcut_prints_what_it_made_and_opens_no_window(self):
        out = io.StringIO()
        with mock.patch.object(shortcut, "create", return_value=["/x/Scena Editor.app"]), \
                mock.patch.object(shortcut, "remove_legacy", return_value=[]), \
                mock.patch("scena.init") as init, contextlib.redirect_stdout(out):
            self.assertEqual(main(["--shortcut"]), 0)
        init.assert_not_called()
        self.assertIn("/x/Scena Editor.app", out.getvalue())

    def test_a_failed_shortcut_is_reported(self):
        err = io.StringIO()
        with mock.patch.object(shortcut, "create", side_effect=OSError("no access")), \
                contextlib.redirect_stderr(err):
            self.assertEqual(main(["--shortcut"]), 1)
        self.assertIn("no access", err.getvalue())


class TestPackaging(unittest.TestCase):
    """`pip install scena` brings the editor, its dialogs and the command."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            cls.project = tomllib.load(f)

    def test_command_and_dependency(self):
        project = self.project["project"]
        self.assertEqual(project["scripts"]["scena-editor"], "scena_editor.__main__:main")
        self.assertIn("crossfiledialog", project["dependencies"])
        self.assertNotIn("editor", project.get("optional-dependencies", {}))

    def test_packages_ship_without_the_editor_tests(self):
        self.assertEqual(self.project["tool"]["setuptools"]["packages"], ["scena", "scena_editor"])

    def test_one_package_definition(self):
        # A setup.py next to pyproject.toml could define the package twice.
        self.assertFalse(os.path.exists(os.path.join(ROOT, "setup.py")))


if __name__ == "__main__":
    unittest.main()
