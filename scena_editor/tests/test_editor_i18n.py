"""Every UI string key exists in every language table, and no key is empty.

Run: python -m unittest scena_editor.tests.test_editor_i18n
"""
import os
import re
import unittest

from scena_editor import i18n
from tests.source_support import iter_files

EDITOR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def keys_used_in_source():
    used = set()
    for path in iter_files(EDITOR, ".py", recursive=True, skip_dirs={"tests"}):
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        used.update(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", src))
        # t(f"hint.{tool}") — every tool has its hint
        if 'f"hint.{' in src:
            from scena_editor.tools import TOOLS
            used.update(f"hint.{tool}" for tool in TOOLS)
    return used


class TestStrings(unittest.TestCase):
    def test_every_table_has_every_key(self):
        base = set(i18n.STRINGS["en"])
        for lang, table in i18n.STRINGS.items():
            self.assertEqual(set(table), base, lang)

    def test_no_empty_strings(self):
        for lang, table in i18n.STRINGS.items():
            for key, text in table.items():
                self.assertTrue(text.strip(), f"{lang}:{key}")

    def test_every_key_used_in_the_editor_exists(self):
        used = keys_used_in_source()
        self.assertTrue(used)          # the scan is not vacuous
        missing = sorted(used - set(i18n.STRINGS["en"]))
        self.assertEqual(missing, [])

    def test_formatting(self):
        self.assertEqual(i18n.t("panel.selected", count=3), "3 selected")
        with self.assertRaises(KeyError):
            i18n.t("no.such.key")


if __name__ == "__main__":
    unittest.main()
