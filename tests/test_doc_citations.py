"""Design docs must cite test files and test names that exist.

Bug class: a doc cites ``tests/test_x.py`` or ``test_x.TestY`` written ahead
of a rename (or after a move) and the citation silently rots — six design
docs once pointed at a ``tests/test_registry_layers.py`` that did not exist.
The "scene registry → Registry" rename then created it, so both directions
(cite before rename, rename without re-citing) are caught here.

Checked: every ``*.md`` under ``design/`` except the private
historical / speculative folders (``archive/``, ``proposals/``), which may name
files as they were or will be.

* ``tests/test_x.py`` — the file exists;
* ``test_x.Name`` / ``test_x.Name.member`` (dotted, as in guard columns) — the
  file exists and defines ``Name`` (class, function or assignment) and, when
  given, ``member`` somewhere in the file.

    python -m unittest tests.test_doc_citations -v
"""
from __future__ import annotations

import os
import re
import unittest

from tests.source_support import iter_files
from tests import repo_layout as layout  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = layout.DESIGN
TESTS = os.path.join(ROOT, "tests")
SKIP_DIRS = {"archive", "proposals"}

_FILE_REF = re.compile(r"\btests/(test_\w+)\.py\b")
_DOTTED_REF = re.compile(r"(?<![\w/.])(test_\w+)\.([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?")


def _live_docs():
    yield from iter_files(DOCS, ".md", recursive=True, skip_dirs=SKIP_DIRS)


def _defines(src: str, name: str) -> bool:
    return re.search(
        rf"^\s*(?:class|def|async def)\s+{re.escape(name)}\b|^\s*{re.escape(name)}\s*=",
        src, re.M,
    ) is not None


def _citations():
    """Yield ``(doc, line_no, module, name, member)``; ``name`` may be None."""
    for path in _live_docs():
        rel = os.path.relpath(path, DOCS)
        with open(path, encoding="utf-8") as fh:
            for no, line in enumerate(fh, 1):
                for m in _FILE_REF.finditer(line):
                    yield rel, no, m.group(1), None, None
                for m in _DOTTED_REF.finditer(line):
                    if m.group(2) == "py":
                        continue  # ``test_x.py`` without the ``tests/`` prefix
                    yield rel, no, m.group(1), m.group(2), m.group(3)


class TestDocCitations(unittest.TestCase):
    def test_docs_have_citations(self):
        # Guard the guard: a regex that matches nothing would pass vacuously.
        self.assertGreater(sum(1 for _ in _citations()), 20)

    def test_cited_tests_exist(self):
        sources = {}
        missing = []
        for doc, no, module, name, member in _citations():
            path = os.path.join(TESTS, module + ".py")
            if module not in sources:
                sources[module] = None
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as fh:
                        sources[module] = fh.read()
            src = sources[module]
            where = f"{doc}:{no}"
            if src is None:
                missing.append(f"{where}: tests/{module}.py does not exist")
            elif name is not None and not _defines(src, name):
                missing.append(f"{where}: {module}.{name} is not defined in tests/{module}.py")
            elif member is not None and not _defines(src, member):
                missing.append(
                    f"{where}: {module}.{name}.{member} — {member} is not defined in tests/{module}.py"
                )
        self.assertEqual(missing, [], "\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
