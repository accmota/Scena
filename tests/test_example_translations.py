"""Each English example is its Portuguese example renamed (WP33).

The English tutorials keep their endpoints in ``examples/`` beside the
Portuguese ones (``naves_1.py`` / ``ships_1.py``), paired in the glossary
(``tools/tutorial/names_en.json``). The laws checks run every example a few
hundred times; below ``deep`` they run only the Portuguese one of a pair
(``test_scripts_run.law_scripts``). That holds only while the English file is
the same program: ``tutorial_parity.code_parity`` passes, every name and
word-like string renamed one to one, numbers, structure and imports equal.
A fix made in one language and not the other fails here.

    python tests/run_tiers.py focused test_example_translations
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "tutorial"))

import tutorial_parity as tp  # noqa: E402
from tests.test_scripts_run import translation_pairs  # noqa: E402


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _rename_errors(pt_src: str, en_src: str, where: str):
    return tp.code_parity(pt_src, en_src, where=where).errors


class TestEnglishExamplesAreRenames(unittest.TestCase):

    def test_every_pair_is_the_same_program(self):
        pairs = translation_pairs()
        self.assertGreater(len(pairs), 20)
        bad = []
        for pt, en in pairs:
            errors = _rename_errors(_read(pt), _read(en), os.path.basename(pt))
            bad += [f"{os.path.basename(en)}: {e}" for e in errors[:3]]
        self.assertEqual(bad, [], "fix the twin so it is the other renamed:\n" + "\n".join(bad))

    def test_a_drifted_twin_is_caught(self):
        pt, en = translation_pairs()[0]
        pt_src, en_src = _read(pt), _read(en)
        self.assertEqual(_rename_errors(pt_src, en_src, "pair"), [])
        lines = en_src.splitlines()
        k = next(i for i, line in enumerate(lines)
                 if line.strip() and not line.lstrip().startswith(("#", "from", "import")))
        drifted = "\n".join(lines[:k] + ["x_extra = 1"] + lines[k:])
        self.assertTrue(_rename_errors(pt_src, drifted, "pair"), "an added statement")


if __name__ == "__main__":
    unittest.main()
