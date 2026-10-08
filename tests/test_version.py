"""The release number has one source and every release has a changelog entry.

Bug class: two places hold the version and drift apart (pyproject said 0.1
while the code had moved on; an editable install's metadata stays stale
until a reinstall), or a release ships with no line telling authors what
changed. Policy: design/Scena Design.md, "Compatibility and versions".
"""

import pathlib
import re
import tomllib
import unittest

import scena

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestVersion(unittest.TestCase):
    def test_version_is_major_minor_patch(self):
        self.assertRegex(scena.__version__, r"^\d+\.\d+\.\d+$")

    def test_pyproject_reads_the_version_from_the_package(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertNotIn("version", project["project"],
                         "a second copy of the version; keep it in scena/_version.py")
        self.assertIn("version", project["project"]["dynamic"])
        self.assertEqual(
            project["tool"]["setuptools"]["dynamic"]["version"],
            {"attr": "scena._version.__version__"},
        )

    def test_changelog_has_a_section_for_this_version(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        heading = rf"^## {re.escape(scena.__version__)} — \d{{4}}-\d{{2}}-\d{{2}}$"
        self.assertRegex(changelog, re.compile(heading, re.MULTILINE))

    def test_version_is_not_star_imported(self):
        # `from scena import *` is the author namespace; the version is not a verb.
        self.assertNotIn("__version__", scena.__all__)


if __name__ == "__main__":
    unittest.main()
