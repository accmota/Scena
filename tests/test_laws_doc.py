"""The constitution (design/Laws.md) stays short, checked and in step.

* It fits in a head: at most ``MAX_LAWS`` laws and ``MAX_LINES`` lines.
* Every law has a status (``holds`` / ``open``) and a checker; an open law
  cites the finding that breaks it.
* Both directions with the model: every ``model `area.LAW` `` checker names
  a law the area checks, and every law a model area checks is on the page.
* F3, the snapshot rule, cites only laws that are on the page.

    python -m unittest tests.test_laws_doc -v
"""
from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laws import model  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAWS_MD = os.path.join(ROOT, "design", "Laws.md")
MAX_LAWS = 45
MAX_LINES = 250
ROW = re.compile(r"^\|\s*([A-Z]\d+)\s*\|(.*)\|\s*$")
MODEL_CHECKER = re.compile(r"model `(\w+)\.([A-Z]\d+)`")
FINDING = re.compile(r"\b[A-Z]{1,3}\d+\b")


def _rows():
    with open(LAWS_MD, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    rows = {}
    for line in lines:
        m = ROW.match(line)
        if m:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[cells[0]] = cells
    return lines, rows


class TestConstitution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines, cls.rows = _rows()

    def test_it_fits_in_a_head(self):
        self.assertLessEqual(len(self.lines), MAX_LINES)
        self.assertLessEqual(len(self.rows), MAX_LAWS)
        self.assertGreater(len(self.rows), 0)

    def test_every_law_has_a_status_and_a_checker(self):
        bad = []
        for law, cells in self.rows.items():
            if len(cells) != 5:
                bad.append(f"{law}: {len(cells)} cells, want 5")
                continue
            _id, _text, status, checkers, _detail = cells
            if not (status == "holds" or status.startswith("open")):
                bad.append(f"{law}: status {status!r}")
            if status.startswith("open") and not FINDING.search(status[4:]):
                bad.append(f"{law}: an open law cites its finding id")
            if not checkers or checkers == "-":
                bad.append(f"{law}: no checker")
        self.assertEqual(bad, [])

    def test_model_checkers_name_laws_the_area_checks(self):
        areas = {a.__name__.rsplit(".", 1)[-1]: a for a in model.AREAS}
        bad = []
        for law, cells in self.rows.items():
            for area, named in MODEL_CHECKER.findall(cells[3] if len(cells) > 3 else ""):
                if named != law:
                    bad.append(f"{law}: names model {area}.{named}")
                elif area not in areas or law not in areas[area].LAWS:
                    bad.append(f"{law}: model area {area!r} does not check it")
        self.assertEqual(bad, [])

    def test_the_snapshot_rule_cites_laws_on_the_page(self):
        """F3 names the laws that are its cases: a merge or a rename must not
        leave it citing a law that is gone."""
        self.assertIn("F3", self.rows)
        cited = set(re.findall(r"\b([CLTFIVP]\d+)\b", self.rows["F3"][1])) - {"F3"}
        self.assertGreater(len(cited), 5)
        self.assertEqual(sorted(cited - set(self.rows)), [])

    def test_every_law_the_model_checks_is_on_the_page(self):
        missing = sorted(model.laws_checked() - set(self.rows))
        self.assertEqual(missing, [], "add the law to design/Laws.md")


if __name__ == "__main__":
    unittest.main()
