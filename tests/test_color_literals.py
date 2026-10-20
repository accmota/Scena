"""Color names written in scripts and in the Guia's code exist in Scena.

Bug class: a CSS / X11 name that Scena does not know (``"slategray"``,
``"mediumseagreen"``, ``"slate gray"``) only warns and paints magenta. Smoke
scripts run with warnings ignored (``tests/script_harness.py``), and a name
in a click-only swatch or in a Guia card's second line never runs at all, so
nothing failed until someone saw magenta on screen. This reads the literals
statically instead: keyword values of color knobs and ``*SWATCH*`` tuples in
scripts, ``color=\\"…\\"`` in the Guia catalogs, page, and tutorials.

    python -m unittest tests.test_color_literals -v
"""
from __future__ import annotations

import ast
import os
import re
import unittest
import warnings

from tests.source_support import iter_files
from tests import repo_layout as layout  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Knobs that take one color.
COLOR_KWARGS = frozenset({
    "color", "color2", "fill", "line_color", "tint", "base", "glow_color",
    "outline", "background",
})
_DOC_RE = re.compile(
    r'\b(?:%s)\s*=\s*\\?"([^"\\]+)\\?"' % "|".join(sorted(COLOR_KWARGS))
)


def is_known_color(name: str) -> bool:
    """True when ``Color(name)`` resolves without the unknown-name fallback."""
    from scena.color import Color
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            Color(name)
        except (RuntimeWarning, ValueError, TypeError):
            return False
    return True


def script_paths():
    found = iter_files(os.path.join(ROOT, "scripts", "smoke"), ".py")
    found += iter_files(os.path.join(ROOT, "examples"), ".py", recursive=True,
                        skip_dirs={"media"})
    found += iter_files(os.path.join(ROOT, "tests", "loads"), ".py")
    found += iter_files(os.path.join(ROOT, "tests", "games"), ".py")
    return found


def doc_paths():
    found = [layout.GUIDE_CATALOGS, layout.GUIDE_HTML]
    found += iter_files(layout.TUTORIAL, ".html")
    return found


def script_literals(path):
    """``(line, name)`` for each string literal a script passes as a color."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    out = []
    for node in ast.walk(tree):
        values = []
        if isinstance(node, ast.keyword) and node.arg in COLOR_KWARGS:
            values = [node.value]
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and "SWATCH" in t.id.upper() for t in node.targets
        ):
            values = list(getattr(node.value, "elts", []))
        for v in values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append((v.lineno, v.value))
    return out


# A wrong name on purpose: appendix A presses SPACE to paint "laranja" and show
# the SCENA WARNING banner it raises (the step test never presses SPACE).
_DELIBERATE = {("A-depuracao.html", "laranja")}


def _in_html_tag(line: str, at: int) -> bool:
    """The match sits inside an HTML/SVG tag (``<path fill="none" …>``), not in code."""
    return line.rfind("<", 0, at) > line.rfind(">", 0, at)


def doc_literals(path):
    out = []
    page = os.path.basename(path)
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            out.extend((i, m.group(1)) for m in _DOC_RE.finditer(line)
                       if not _in_html_tag(line, m.start())
                       and (page, m.group(1)) not in _DELIBERATE)
    return out


class TestColorLiterals(unittest.TestCase):
    def test_detector_is_not_vacuous(self):
        self.assertTrue(is_known_color("dim gray"))
        self.assertTrue(is_known_color("#ff8800"))
        self.assertFalse(is_known_color("vermilion"))
        self.assertFalse(is_known_color("cerulean"))
        src = 'Circle(color="red")\n_HIT_SWATCHES = (None, "cyan")\n'
        tree_names = sorted(n for _l, n in script_literals_from_source(src))
        self.assertEqual(tree_names, ["cyan", "red"])
        self.assertEqual(
            [n for _l, n in doc_literals_from_text('code: "Fog(color=\\"dim gray\\")"')],
            ["dim gray"],
        )
        self.assertTrue(_in_html_tag('<path class="ray" fill="none" d="M 0 0"/>', 17))
        self.assertFalse(_in_html_tag('r.fill = "none"', 2))

    def test_script_color_names_exist(self):
        seen, bad = 0, []
        for path in script_paths():
            for line, name in script_literals(path):
                seen += 1
                if not is_known_color(name):
                    bad.append(f"{os.path.relpath(path, ROOT)}:{line}: {name!r}")
        self.assertGreater(seen, 100, "found too few color literals to trust the scan")
        self.assertEqual(bad, [], "unknown color names (they paint magenta):\n" + "\n".join(bad))

    def test_guia_and_tutorial_color_names_exist(self):
        seen, bad = 0, []
        for path in doc_paths():
            for line, name in doc_literals(path):
                seen += 1
                if not is_known_color(name):
                    bad.append(f"{os.path.relpath(path, ROOT)}:{line}: {name!r}")
        self.assertGreater(seen, 50, "found too few color literals to trust the scan")
        self.assertEqual(bad, [], "unknown color names (they paint magenta):\n" + "\n".join(bad))


def script_literals_from_source(src: str):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(src)
    try:
        return script_literals(fh.name)
    finally:
        os.unlink(fh.name)


def doc_literals_from_text(text: str):
    return [(1, m.group(1)) for m in _DOC_RE.finditer(text)]


if __name__ == "__main__":
    unittest.main()
