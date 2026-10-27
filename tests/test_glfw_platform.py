"""pyGLFW's Linux build choice, and the error when Skia finds no GL context.

Found on Ubuntu from a live USB (2026-10-27, WP52 in Testing Design.md): in a
Wayland session pyGLFW loads its Wayland GLFW build, whose EGL context
skia-python's ``GrDirectContext.MakeGL()`` does not find (it looks for GLX on
Linux). MakeGL returned None and ``open_window`` died later with "Failed to
create Skia surface", which hid the cause.

Bug class: **glfw loaded before Scena chose the build.** The variant is read
once, when ``glfw`` is first imported, so every import path into the engine
runs ``scena._glfw_platform`` first (checked here in a child process: Linux's
choice cannot be exercised on the Mac, the import order can).
"""
from __future__ import annotations

import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from scena import _glfw_platform as gp
from scena import orchestration
from tests.source_support import iter_files

REPO = Path(__file__).resolve().parents[1]
VAR = gp.VARIANT_ENV


class TestPreferX11(unittest.TestCase):
    def test_linux_without_a_choice_gets_x11(self):
        env = {"XDG_SESSION_TYPE": "wayland"}
        self.assertTrue(gp.prefer_x11(env, "linux"))
        self.assertEqual(env[VAR], "x11")

    def test_a_variant_the_user_set_stays(self):
        for choice in ("wayland", "x11"):
            env = {VAR: choice}
            self.assertFalse(gp.prefer_x11(env, "linux"))
            self.assertEqual(env[VAR], choice)

    def test_other_platforms_untouched(self):
        for platform in ("darwin", "win32"):
            env = {}
            self.assertFalse(gp.prefer_x11(env, platform))
            self.assertNotIn(VAR, env)


class TestNoContextMessage(unittest.TestCase):
    def test_wayland_variant_named_with_the_fix(self):
        msg = gp.no_gl_context_message({VAR: "wayland"}, "linux", False)
        self.assertIn("MakeGL", msg)
        self.assertIn(f"{VAR}=x11", msg)

    def test_glfw_imported_first_names_the_import_order(self):
        msg = gp.no_gl_context_message({VAR: "x11"}, "linux", True)
        self.assertIn("import scena first", msg)

    def test_x11_build_points_at_the_driver(self):
        msg = gp.no_gl_context_message({VAR: "x11"}, "linux", False)
        self.assertIn("OpenGL 3.2", msg)
        self.assertNotIn("wayland", msg.lower())

    def test_init_skia_raises_the_cause_not_the_surface(self):
        made = []
        fake = types.SimpleNamespace(
            _context="stale",
            _create_drawing_surface=lambda: made.append(True),
        )
        fake_skia = types.SimpleNamespace(
            GrDirectContext=types.SimpleNamespace(MakeGL=lambda: None)
        )
        with mock.patch.object(orchestration, "skia", fake_skia):
            with self.assertRaises(RuntimeError) as cm:
                orchestration.ScenaFramework._init_skia(fake)
        self.assertIn("no OpenGL context", str(cm.exception))
        self.assertEqual(made, [], "the surface must not be tried without a context")


class TestImportOrder(unittest.TestCase):
    """Each entry point loads scena._glfw_platform before glfw."""

    def _order(self, statement: str):
        code = (
            f"import sys\n{statement}\n"
            "names = list(sys.modules)\n"
            "print(names.index('scena._glfw_platform'), names.index('glfw'))\n"
        )
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        first, glfw_at = map(int, out.stdout.split()[-2:])
        return first, glfw_at

    def test_entry_points(self):
        for statement in (
            "import scena",
            "from scena import *",
            "import scena.orchestration",
            "import scena.input",
            "import scena_editor._engine",
        ):
            with self.subTest(statement=statement):
                first, glfw_at = self._order(statement)
                self.assertLess(first, glfw_at)

    def test_every_glfw_import_in_the_editor_follows_the_choice(self):
        # scena/ is covered by its package __init__; scena_editor/ imports glfw
        # on its own, so each such module names the choice before it.
        for name in iter_files(REPO / "scena_editor", ".py"):
            path = Path(name)
            lines = path.read_text(encoding="utf-8").splitlines()
            glfw_lines = [i for i, l in enumerate(lines) if l.strip() == "import glfw"]
            if not glfw_lines:
                continue
            choice = [i for i, l in enumerate(lines) if "scena._glfw_platform" in l]
            with self.subTest(path=path.name):
                self.assertTrue(choice and choice[0] < glfw_lines[0])


if __name__ == "__main__":
    unittest.main()
