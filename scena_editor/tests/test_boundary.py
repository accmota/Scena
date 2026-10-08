"""The editor is a companion app: one-way dependency on the framework.

- Nothing under ``scena/`` imports ``scena_editor``.
- Inside ``scena_editor/``, Scena privates (``scena._x``, ``obj._x`` on Scena
  objects such as ``keyp._swallow_edges``) appear only in ``_engine.py``.
  Every such use is a candidate for a public API.

Run: python -m unittest scena_editor.tests.test_boundary
"""
import ast
import os
import re
import unittest

from tests.source_support import iter_files

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENA = os.path.join(ROOT, "scena")
EDITOR = os.path.join(ROOT, "scena_editor")


def _py_files(folder, skip_tests=False):
    return iter_files(folder, ".py", recursive=True,
                      skip_dirs={"tests"} if skip_tests else ())


def _imports(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


class TestOneWayDependency(unittest.TestCase):
    def test_framework_never_imports_the_editor(self):
        bad = [os.path.relpath(p, ROOT) for p in _py_files(SCENA)
               if any(m.split(".")[0] == "scena_editor" for m in _imports(p))]
        self.assertEqual(bad, [])

    def test_scena_privates_only_in_the_engine_adapter(self):
        """``from scena.x import _y`` / ``scena._y`` / ``scena.x._y`` outside
        ``_engine.py`` is a leak of an engine detail into the app."""
        bad = []
        for path in _py_files(EDITOR, skip_tests=True):
            if os.path.basename(path) == "_engine.py":
                continue
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            tree = ast.parse(source, path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and \
                        node.module.split(".")[0] == "scena":
                    if any(part.startswith("_") for part in node.module.split(".")) or \
                            any(a.name.startswith("_") for a in node.names):
                        bad.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}")
            for m in re.finditer(r"\bscena(\.\w+)*\._\w+", source):
                line = source.count("\n", 0, m.start()) + 1
                bad.append(f"{os.path.relpath(path, ROOT)}:{line} {m.group(0)}")
            for m in re.finditer(r"\b(keyp|mouse|canvas|clock)\._\w+", source):
                line = source.count("\n", 0, m.start()) + 1
                bad.append(f"{os.path.relpath(path, ROOT)}:{line} {m.group(0)}")
        self.assertEqual(bad, [], "route Scena privates through scena_editor/_engine.py")


class TestRuleCatchesALeak(unittest.TestCase):
    """The privates scan is not vacuous: it flags the spellings it means to."""

    def test_patterns(self):
        src = "from scena.sprite import _resolve_image_path\nkeyp._swallow_edges()\n"
        tree = ast.parse(src)
        flagged = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                   and any(a.name.startswith("_") for a in n.names)]
        self.assertEqual(len(flagged), 1)
        self.assertTrue(re.search(r"\b(keyp|mouse|canvas|clock)\._\w+", src))


if __name__ == "__main__":
    unittest.main()
