"""Tests that pass on the Mac must pass on Windows (and on a copied tree).

Bug classes, both found on a Windows quick-tier run (2026-09-30; Testing
Design — bug catalogue, WP):

* **Directory scans read OS metadata.** A tree copied from macOS holds an
  AppleDouble ``._<name>`` next to every file; ``._foo.py`` ends in ``.py``.
  Every scan in ``tests/`` goes through ``tests/source_support.iter_files``.
* **Pixels in the platform byte order.** ``skia.kN32_ColorType`` is RGBA on the
  Mac and BGRA on Windows. ``Image.fromarray`` defaults to it, and
  ``Image.toarray`` defaults to the image's own type (N32 for
  ``skia.Surface(w, h)``). Every call names ``colorType=`` so the Mac run
  catches what only shows on Windows.

Found on a Windows gate run (2026-10-05, WP5 in Testing Design.md):

* **Text in the locale encoding.** ``open(p)`` / ``read_text()`` without
  ``encoding=`` decode with the locale: UTF-8 on the Mac, cp1252 on Windows
  (``—`` reads as ``â€”``). Every text ``open`` / ``read_text`` /
  ``write_text`` in ``scena/``, ``scena_editor/`` and ``tests/`` passes
  ``encoding=``.

Found on a Windows gate run (2026-10-06, WP12 in Testing Design.md):

* **The exec bit is POSIX.** Windows has no exec bit: ``os.chmod`` only
  toggles read-only and ``st_mode``'s execute bits follow the extension. Every
  test line reading ``S_IX*`` / ``X_OK`` names ``os.name`` or ``sys.platform``
  in the 3 lines before it.
* **A transient placed by the clock, then drawn on the real clock.** A test
  that sets ``_tx_state.<kind>.t0`` from one ``_now()`` read lets ``draw()``
  read the clock again, later under a loaded tier (WP14). Every test module
  that writes a ``t0`` pins the clock with ``transients.set_now_fn``.

Found by a read-only audit of the suite after that run (latent; WP16 / WP17):

* **Child output decoded with the locale.** ``subprocess.run(..., text=True)``
  decodes with the locale (cp1252 on Windows) while a Python child under
  ``PYTHONIOENCODING=utf-8`` writes UTF-8: garbled output, or a
  ``UnicodeDecodeError`` on a byte cp1252 does not define. Every text-mode
  subprocess call in ``scena/``, ``scena_editor/`` and ``tests/`` names
  ``encoding=`` (a Python child: ``"utf-8"`` with ``PYTHONIOENCODING`` pinned)
  or ``errors=`` (an external tool writing in the locale).
* **Sorting paths with the host separator.** ``"\\"`` sorts after letters,
  ``"/"`` before them; ``iter_files`` sorts in ``/`` form.

Found on a Windows quick-tier run (2026-10-08):

* **Joining a ``"/"`` path onto a ``"\\"`` root.** A test helper
  ``png("ninja/Run__000.png")`` built ``os.path.join(root, rel)``, i.e.
  ``C:\\t\\ninja/Run__000.png``; the code returned the ``abspath`` form
  ``C:\\t\\ninja\\Run__000.png`` and the lists compared unequal. Every
  ``os.path.join`` in the tests that takes a helper's parameter, or a literal
  holding ``"/"``, is wrapped in ``os.path.normpath`` (or splits on ``"/"``).
"""
from __future__ import annotations

import ast
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.source_support import is_junk, iter_files, path_key  # noqa: E402

TESTS = os.path.join(ROOT, "tests")
SCENA = os.path.join(ROOT, "scena")
EDITOR = os.path.join(ROOT, "scena_editor")

# Calls that list a directory: ``os.<name>`` (``walk`` alone is too common:
# ``ast.walk``), and any ``.glob`` / ``.rglob`` / ``.iterdir`` (``glob.glob``
# skips dot files but ``Path.glob`` does not; one rule keeps the guard simple).
_OS_SCANS = frozenset({"listdir", "walk", "scandir"})
_ANY_SCANS = frozenset({"glob", "iglob", "rglob", "iterdir"})
# Scans that never open what they find.
_SCAN_ALLOWED = {
    "source_support.py": "the helper itself",
    "run_tiers.py": "module discovery needs the test_ prefix; AppleDouble count",
}


def _calls(path: str):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _attr(call: ast.Call):
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _scan(call: ast.Call):
    """``"os.walk"`` / ``".rglob"`` / … when ``call`` lists a directory."""
    f = call.func
    if isinstance(f, ast.Attribute):
        if f.attr in _ANY_SCANS:
            return "." + f.attr
        if f.attr in _OS_SCANS and isinstance(f.value, ast.Name) and f.value.id == "os":
            return "os." + f.attr
    elif isinstance(f, ast.Name) and f.id in ("listdir", "scandir"):
        return f.id
    return None


def _text_io(call: ast.Call):
    """``"open"`` / ``".read_text"`` / ``".write_text"`` when ``call`` reads or
    writes text without naming its encoding. Only the builtin ``open`` and
    ``io.open``: ``.open`` on anything else is mostly ``skia.Image.open``."""
    if any(k.arg == "encoding" for k in call.keywords):
        return None
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in ("read_text", "write_text"):
        return "." + f.attr
    if not (isinstance(f, ast.Name) and f.id == "open"
            or isinstance(f, ast.Attribute) and f.attr == "open"
            and isinstance(f.value, ast.Name) and f.value.id == "io"):
        return None
    mode = next((k.value for k in call.keywords if k.arg == "mode"),
                call.args[1] if len(call.args) > 1 else None)
    if (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
            and "b" in mode.value):
        return None
    return "open"   # text mode, or a mode the guard cannot read: name the encoding


class TestIterFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        junk = b"\x00\x05\x16\x07" + b"\xb0" * 40
        files = {
            "a.py": b"x = 1\n", "._a.py": junk, ".DS_Store": junk, "b.md": b"# b\n",
            "._b.md": junk, "Thumbs.db": junk, "C.PY": b"", "sub/d.py": b"",
            "sub/._d.py": junk, "archive/e.py": b"", ".hidden/f.py": b"",
            "__pycache__/g.py": b"",
        }
        for rel, data in files.items():
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)

    def names(self, *suffixes, **kw):
        return [os.path.relpath(p, self.root).replace(os.sep, "/")
                for p in iter_files(self.root, *suffixes, **kw)]

    def test_only_real_files_come_back(self):
        self.assertEqual(self.names(".py"), ["C.PY", "a.py"])
        self.assertEqual(self.names(".md"), ["b.md"])
        self.assertEqual(self.names(".py", ".md"), ["C.PY", "a.py", "b.md"])
        self.assertEqual(self.names(), ["C.PY", "a.py", "b.md"])

    def test_recursive_prunes_skip_hidden_and_pycache(self):
        self.assertEqual(self.names(".py", recursive=True),
                         ["C.PY", "a.py", "archive/e.py", "sub/d.py"])
        self.assertEqual(self.names(".py", recursive=True, skip_dirs={"archive"}),
                         ["C.PY", "a.py", "sub/d.py"])

    def test_order_does_not_depend_on_the_separator(self):
        # "\\" (Windows) sorts after "A", "/" before it: sorted in "/" form,
        # sub/x.py comes before subA.py on every OS.
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ("sub/x.py", "subA.py", "sub2.py"):
                path = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "wb").close()
            got = [os.path.relpath(p, tmp).replace(os.sep, "/")
                   for p in iter_files(tmp, ".py", recursive=True)]
        self.assertEqual(got, ["sub/x.py", "sub2.py", "subA.py"])
        # The Windows spelling, checked on any host.
        win = ["subA.py", "sub\\x.py", "sub2.py"]
        self.assertEqual(sorted(win, key=lambda p: path_key(p, "\\")),
                         ["sub\\x.py", "sub2.py", "subA.py"])
        self.assertNotEqual(sorted(win)[0], "sub\\x.py")   # the bug: plain sort

    def test_is_junk(self):
        for name in ("._a.py", "._Scena Design.md", ".DS_Store", "Thumbs.db", "desktop.ini"):
            self.assertTrue(is_junk(name), name)
        for name in ("a.py", "_private.py", ".hypothesis", "Design.md"):
            self.assertFalse(is_junk(name), name)


class TestSourceScansUseTheHelper(unittest.TestCase):
    def test_no_bare_directory_scan_in_tests(self):
        bad = []
        for root in (TESTS, os.path.join(EDITOR, "tests")):
            for path in iter_files(root, ".py", recursive=True):
                if os.path.basename(path) in _SCAN_ALLOWED and root == TESTS:
                    continue
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                for call in _calls(path):
                    if _scan(call):
                        bad.append(f"{rel}:{call.lineno}: {_scan(call)}()")
        self.assertEqual(
            bad, [],
            "scan with tests/source_support.iter_files (skips AppleDouble '._*' "
            "and other OS metadata):\n" + "\n".join(bad),
        )

    def test_guard_sees_each_spelling(self):
        src = ("os.listdir('.')\nos.walk('.')\nos.scandir('.')\nglob.glob('*')\n"
               "Path('.').glob('*')\nPath('.').rglob('*')\nPath('.').iterdir()\n"
               "listdir('.')\nast.walk(tree)\nwalk(node)\n")
        found = [_scan(c) for c in ast.walk(ast.parse(src)) if isinstance(c, ast.Call)]
        self.assertEqual(
            sorted(x for x in found if x),
            [".glob", ".glob", ".iterdir", ".rglob", "listdir", "os.listdir",
             "os.scandir", "os.walk"],
        )


class TestTextIoNamesItsEncoding(unittest.TestCase):
    def test_text_io_passes_encoding(self):
        bad = []
        for root in (SCENA, EDITOR, TESTS):
            for path in iter_files(root, ".py", recursive=True):
                for call in _calls(path):
                    kind = _text_io(call)
                    if kind:
                        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                        bad.append(f"{rel}:{call.lineno}: {kind}()")
        self.assertEqual(
            bad, [],
            'pass encoding="utf-8": the default is the locale (cp1252 on Windows):\n'
            + "\n".join(bad),
        )

    def test_guard_sees_each_spelling(self):
        src = ("open(p)\nopen(p, 'w')\nopen(p, 'rb')\nopen(p, mode='wb')\n"
               "open(p, m)\nopen(p, encoding='utf-8')\nio.open(p)\n"
               "Path(p).read_text()\nPath(p).write_text(s, encoding='utf-8')\n"
               "p.write_text(s)\nskia.Image.open(p)\n")
        found = [(c.lineno, _text_io(c)) for c in ast.walk(ast.parse(src))
                 if isinstance(c, ast.Call) and _text_io(c)]
        self.assertEqual(sorted(found), [
            (1, "open"), (2, "open"), (5, "open"), (7, "open"),
            (8, ".read_text"), (10, ".write_text"),
        ])


def _unguarded_exec_bits(text: str):
    """Line numbers reading an exec bit (``S_IX*`` / ``X_OK``) with no
    ``os.name`` / ``sys.platform`` check in the 3 lines before."""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if "S_IX" in line or "X_OK" in line:
            window = "\n".join(lines[max(0, i - 3):i + 1])
            if "os.name" not in window and "sys.platform" not in window:
                out.append(i + 1)
    return out


class TestExecBitIsPosixOnly(unittest.TestCase):
    def test_exec_bit_checks_name_the_platform(self):
        bad = []
        for root in (TESTS, os.path.join(EDITOR, "tests")):
            for path in iter_files(root, ".py", recursive=True):
                if os.path.basename(path) == os.path.basename(__file__):
                    continue
                with open(path, encoding="utf-8") as fh:
                    lines = _unguarded_exec_bits(fh.read())
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                bad += [f"{rel}:{n}" for n in lines]
        self.assertEqual(
            bad, [],
            'Windows has no exec bit; guard with if os.name != "nt":\n' + "\n".join(bad),
        )

    def test_guard_sees_each_spelling(self):
        src = ("import os\nimport stat\n\n\n"
               "assert os.stat(p).st_mode & stat.S_IXUSR\n"          # 5: unguarded
               "\n\nif os.name != 'nt':\n"
               "    assert os.stat(p).st_mode & stat.S_IXUSR\n"      # 9: guarded
               "\n\n\n"
               "assert os.access(p, os.X_OK)\n")                     # 13: unguarded
        self.assertEqual(_unguarded_exec_bits(src), [5, 13])


_SUBPROCESS_CALLS = frozenset({"run", "Popen", "check_output", "call", "check_call"})


def _text_subprocess(call: ast.Call) -> bool:
    """True for ``subprocess.<run|Popen|…>(..., text=True)`` (or
    ``universal_newlines=True``) that names neither ``encoding=`` nor ``errors=``."""
    f = call.func
    if not (isinstance(f, ast.Attribute) and f.attr in _SUBPROCESS_CALLS
            and isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
        return False
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    if "encoding" in kw or "errors" in kw:
        return False
    return any(isinstance(kw.get(k), ast.Constant) and kw[k].value is True
               for k in ("text", "universal_newlines"))


class TestSubprocessTextNamesItsEncoding(unittest.TestCase):
    def test_text_subprocess_passes_encoding(self):
        bad = []
        for root in (SCENA, EDITOR, TESTS):
            for path in iter_files(root, ".py", recursive=True):
                for call in _calls(path):
                    if _text_subprocess(call):
                        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                        bad.append(f"{rel}:{call.lineno}")
        self.assertEqual(
            bad, [],
            'text=True decodes with the locale (cp1252 on Windows); a Python child: '
            'encoding="utf-8", errors="replace" and PYTHONIOENCODING=utf-8 in its env; '
            'an external tool: errors="replace":\n' + "\n".join(bad),
        )

    def test_guard_sees_each_spelling(self):
        src = ("subprocess.run(c, text=True)\n"
               "subprocess.Popen(c, universal_newlines=True)\n"
               "subprocess.check_output(c, text=True, encoding='utf-8')\n"
               "subprocess.run(c, text=True, errors='replace')\n"
               "subprocess.run(c, capture_output=True)\n"
               "subprocess.check_output(c, text=True)\n")
        found = [c.lineno for c in ast.walk(ast.parse(src))
                 if isinstance(c, ast.Call) and _text_subprocess(c)]
        self.assertEqual(sorted(found), [1, 2, 6])

    def test_utf8_child_round_trips(self):
        import subprocess
        out = subprocess.run(
            [sys.executable, "-c", "print('Á Í — 日本')"], capture_output=True,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(out.stdout.strip(), "Á Í — 日本")


_T0_WRITE = re.compile(r"_tx_state\.\w+\.t0\s*=[^=]")


class TestTransientClockIsPinned(unittest.TestCase):
    def test_modules_that_place_a_transient_pin_the_clock(self):
        bad = []
        for root in (TESTS, os.path.join(EDITOR, "tests")):
            for path in iter_files(root, ".py", recursive=True):
                if os.path.basename(path) == os.path.basename(__file__):
                    continue
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                if _T0_WRITE.search(text) and "set_now_fn" not in text:
                    bad.append(os.path.relpath(path, ROOT).replace(os.sep, "/"))
        self.assertEqual(
            bad, [],
            "a test that sets a transient's t0 pins the clock with "
            "transients.set_now_fn (draw() reads it again):\n" + "\n".join(bad),
        )

    def test_guard_sees_a_t0_write(self):
        self.assertTrue(_T0_WRITE.search("s._tx_state.life.t0 = now - 0.1"))
        self.assertFalse(_T0_WRITE.search("assert s._tx_state.life.t0 == now"))


_NORMALIZERS = frozenset({"normpath", "abspath", "realpath"})


def _is_path_join(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "join"
            and isinstance(f.value, ast.Attribute) and f.value.attr == "path")


def _has_slash(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and "/" in node.value
    if isinstance(node, ast.JoinedStr):
        return any(_has_slash(v) for v in node.values)
    return False


def _mixed_separator_joins(tree: ast.AST):
    """Line numbers of ``os.path.join`` calls that may glue a ``"/"`` path onto
    a ``"\\"`` root on Windows: a later part is a literal holding ``"/"``, or a
    parameter of the enclosing function (a helper called as ``png("a/b.png")``).
    Not flagged: the join wrapped in ``os.path.normpath`` / ``abspath`` /
    ``realpath``, and parts split first (``*rel.split("/")``)."""
    parent = {ch: n for n in ast.walk(tree) for ch in ast.iter_child_nodes(n)}

    def params(node):
        while node in parent:
            node = parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = node.args
                return {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs} - {"self"}
        return set()

    out = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and _is_path_join(call)):
            continue
        up = parent.get(call)
        if (isinstance(up, ast.Call) and up.args and up.args[0] is call
                and _attr(up) in _NORMALIZERS):
            continue
        names = params(call)
        if any(_has_slash(a) or isinstance(a, ast.Name) and a.id in names
               for a in call.args[1:]):
            out.append(call.lineno)
    return sorted(out)


class TestJoinedPathsUseOneSeparator(unittest.TestCase):
    """``os.path.join(root, "a/b.png")`` is ``C:\\t\\a/b.png`` on Windows, while
    the code under test returns ``abspath`` / ``normpath`` results
    (``C:\\t\\a\\b.png``): equal paths that compare unequal. Found on a Windows
    quick-tier run (2026-10-08): the ``png(rel)`` helper of
    test_sheet_patterns. A Mac run cannot see it (``os.sep`` is ``"/"``)."""

    def test_joins_in_tests_normalize(self):
        bad = []
        for root in (TESTS, os.path.join(EDITOR, "tests")):
            for path in iter_files(root, ".py", recursive=True):
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), path)
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                bad += [f"{rel}:{n}" for n in _mixed_separator_joins(tree)]
        self.assertEqual(
            bad, [],
            "wrap in os.path.normpath(os.path.join(...)) (or join *rel.split('/')): "
            "a part written with '/' keeps it on Windows, and the code under test "
            "returns '\\\\' paths:\n" + "\n".join(bad),
        )

    def test_guard_sees_each_spelling(self):
        src = ("def a(rel):\n"
               "    return os.path.join(root, rel)\n"                       # 2
               "def b(rel):\n"
               "    return os.path.normpath(os.path.join(root, rel))\n"
               "def c(rel):\n"
               "    return os.path.join(root, *rel.split('/'))\n"
               "def d(root):\n"
               "    return os.path.join(root, 'f.png')\n"
               "os.path.join(root, 'a/b.png')\n"                            # 9
               "os.path.join(root, f'{d}/x.png')\n"                         # 10
               "os.path.join(root, 'a', 'b.png')\n"
               "os.path.abspath(os.path.join(root, 'a/b'))\n"
               "f = lambda name: os.path.join(root, name)\n"                # 13
               "def e(self, rel):\n"
               "    return str(os.path.join(self.root, rel))\n")            # 15
        self.assertEqual(_mixed_separator_joins(ast.parse(src)), [2, 9, 10, 13, 15])

    def test_the_windows_spelling_on_any_host(self):
        import ntpath
        mixed = ntpath.join("C:\\t", "a/b.png")
        self.assertEqual(mixed, "C:\\t\\a/b.png")                           # the bug
        self.assertEqual(ntpath.normpath(mixed), "C:\\t\\a\\b.png")         # the fix
        self.assertEqual(ntpath.join("C:\\t", *"a/b.png".split("/")), "C:\\t\\a\\b.png")


class TestPixelsNameTheirByteOrder(unittest.TestCase):
    def test_toarray_and_fromarray_pass_color_type(self):
        bad = []
        for root, label in ((SCENA, "scena"), (TESTS, "tests")):
            for path in iter_files(root, ".py"):
                if os.path.basename(path) == os.path.basename(__file__):
                    continue
                for call in _calls(path):
                    if _attr(call) not in ("toarray", "fromarray"):
                        continue
                    if not any(k.arg == "colorType" for k in call.keywords):
                        bad.append(f"{label}/{os.path.basename(path)}:{call.lineno}: "
                                   f"{_attr(call)}()")
        self.assertEqual(
            bad, [],
            "pass colorType=skia.kRGBA_8888_ColorType: the default is kN32, which is "
            "BGRA on Windows and RGBA on the Mac:\n" + "\n".join(bad),
        )

    def test_rgba_round_trip_is_platform_independent(self):
        import numpy as np
        import skia
        px = np.zeros((2, 2, 4), dtype=np.uint8)
        px[..., 0] = 255   # red
        px[..., 3] = 255
        img = skia.Image.fromarray(px, colorType=skia.kRGBA_8888_ColorType)
        surf = skia.Surface(2, 2)  # N32: BGRA on Windows
        surf.getCanvas().drawImage(img, 0, 0)
        out = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        self.assertEqual(tuple(int(v) for v in out[0, 0]), (255, 0, 0, 255))


if __name__ == "__main__":
    unittest.main()
