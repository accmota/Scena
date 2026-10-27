"""
Search and link-preview tags of the author site (``tools/site/seo.py``).

Bug classes guarded:

* **A page or its card changes and the head lags** (a new tutorial without a
  description, a renamed page left out of the sitemap): the committed docs
  are what the tool would write.
* **Twins that do not name each other**, or name a hidden page: hreflang is
  reciprocal and only between published pages.
* **The sitemap lists what search engines may not** (a ``noindex`` draft, a
  redirect page) or misses a page.
* **The two head writers undo each other**: ``tutorial_parity --publish``
  owns the relative twin link, ``seo.py`` the absolute ones; each keeps the
  other's lines.
* **The search tags change translation state**: rewriting the title or the
  block left every English tutorial pending (its Portuguese head unit's hash
  moved); the hashes leave both out.

Run:

    python tests/run_tiers.py focused test_site_seo
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "site"))
sys.path.insert(0, os.path.join(ROOT, "tools", "tutorial"))

import seo  # noqa: E402
import tutorial_parity as tp  # noqa: E402

_CANONICAL = re.compile(r'<link rel="canonical" href="([^"]+)">')
_ALT = re.compile(r'<link rel="alternate" hreflang="([^"]+)" href="(https://[^"]+)">')
_LOC = re.compile(r"<loc>([^<]+)</loc>")


def _page(lang: str, title: str, twin: str | None = None, hidden: bool = False) -> str:
    head = ('<meta name="robots" content="noindex">\n' if hidden else "") + (
        f'<link rel="alternate" hreflang="{seo.HREFLANG["pt" if lang == "en" else "en"]}" href="{twin}">\n'
        if twin else "")
    return (f'<!DOCTYPE html>\n<html lang="{"pt-BR" if lang == "pt" else lang}">\n<head>\n'
            f'<meta charset="UTF-8">\n{head}<title>{title} — Scena</title>\n</head>\n<body>\n'
            f'<script>\nTutorial.mount({{\n  n: "01",\n  title: "{title}",\n  steps: [\n'
            f'    {{\n      title: "x",\n    }},\n  ]\n}});\n</script>\n</body>\n</html>\n')


def _index(lang: str, href: str, card: str) -> str:
    return (f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="UTF-8">\n'
            f'<title>Tutoriais — Scena</title>\n</head>\n<body>\n'
            f'<a class="card" href="{href}">\n<h2>x</h2>\n<p>{card}</p>\n</a>\n</body>\n</html>\n')


class TestCommittedSite(unittest.TestCase):
    """The docs in the repository are what the tool writes."""

    @classmethod
    def setUpClass(cls):
        cls.pages = seo.site_pages()
        cls.sitemap = seo.SITEMAP.read_text(encoding="utf-8")

    def test_heads_and_sitemap_are_current(self):
        self.assertEqual([str(p) for p in seo.stale()], [],
                         "run: python tools/site/seo.py")

    def test_every_page_has_one_description_and_preview(self):
        for r, text in self.pages.items():
            with self.subTest(page=r):
                self.assertEqual(text.count('<meta name="description"'), 1)
                self.assertEqual(text.count('property="og:image"'), 1)
                self.assertEqual(text.count("<title>"), 1)

    def test_canonicals_are_unique_and_match_the_sitemap(self):
        canon = {r: _CANONICAL.findall(t) for r, t in self.pages.items() if not seo.is_hidden(t)}
        for r, found in canon.items():
            self.assertEqual(found, [seo.url(r)], r)
        urls = [c[0] for c in canon.values()]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(sorted(_LOC.findall(self.sitemap)), sorted(urls))

    def test_every_sitemap_entry_is_a_page(self):
        for loc in _LOC.findall(self.sitemap):
            path = loc.removeprefix(seo.SITE)
            path = path + "index.html" if path.endswith("/") or not path else path
            self.assertIn(path, self.pages, loc)

    def test_twins_name_each_other(self):
        by_url = {seo.url(r): r for r in self.pages}
        for r, text in self.pages.items():
            alts = dict(_ALT.findall(text))
            if not alts:
                continue
            with self.subTest(page=r):
                self.assertIn(seo.url(r), alts.values(), "a page names itself among its twins")
                for code, href in alts.items():
                    other = by_url[href]
                    self.assertFalse(seo.is_hidden(self.pages[other]))
                    self.assertEqual(dict(_ALT.findall(self.pages[other])), alts)

    def test_published_tutorials_and_guides_have_twins(self):
        for r, text in self.pages.items():
            if r != "index.html" and not seo.is_hidden(text):
                self.assertTrue(_ALT.search(text), f"{r}: no hreflang")

    def test_the_language_switch_link_stays_first_and_relative(self):
        # tutorial.js takes the first relative alternate link as the switch.
        for r, text in self.pages.items():
            if "/tutorial/" in r:
                first = re.search(r'<link rel="alternate"[^>]*href="([^"]+)"', text)
                if first:
                    self.assertFalse(first.group(1).startswith("http"), r)

    def test_the_home_keeps_the_search_console_verification(self):
        # Google re-checks the tag; without it the property loses verification.
        self.assertIn('<meta name="google-site-verification" content="',
                      self.pages["index.html"])

    def test_the_preview_image_exists(self):
        self.assertTrue((seo.DOCS / seo.OG_IMAGE).is_file())


class TestTool(unittest.TestCase):
    """The rules on a small site in a temporary folder."""

    def site(self, en_hidden: bool) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        docs = Path(tmp.name)
        files = {
            "index.html": _index("en", "en/tutorial/index.html", "x"),
            "pt/index.html": '<html lang="pt"><head><meta http-equiv="refresh" content="0; url=../index.html">'
                             "</head></html>\n",
            "pt/tutorial/index.html": _index("pt", "01-primeiro.html", "Janela &amp; <code>init</code>."),
            "en/tutorial/index.html": _index("en", "01-first.html", "Window and <code>init</code>."),
            "pt/tutorial/01-primeiro.html": _page("pt", "Primeiro",
                                                  None if en_hidden else "../../en/tutorial/01-first.html"),
            "en/tutorial/01-first.html": _page("en", "First", "../../pt/tutorial/01-primeiro.html",
                                               hidden=en_hidden),
        }
        for r, t in files.items():
            (docs / r).parent.mkdir(parents=True, exist_ok=True)
            (docs / r).write_text(t, encoding="utf-8")
        return docs

    def fixed(self):
        # The tiny site's indexes and home are not in FIXED: give them text.
        saved = dict(seo.FIXED)
        seo.FIXED.update({r: ("T", "D") for r in ("index.html", "pt/tutorial/index.html",
                                                  "en/tutorial/index.html")})
        self.addCleanup(lambda: (seo.FIXED.clear(), seo.FIXED.update(saved)))

    def test_title_and_description_come_from_the_page_and_its_card(self):
        self.fixed()
        docs = self.site(en_hidden=False)
        seo.write(docs)
        en = (docs / "en/tutorial/01-first.html").read_text(encoding="utf-8")
        self.assertIn(f"<title>First — {seo.TUTORIAL_TAIL['en']}</title>", en)
        self.assertIn(f'content="Window and init. {seo.TUTORIAL_SENTENCE["en"]}"', en)
        pt = (docs / "pt/tutorial/01-primeiro.html").read_text(encoding="utf-8")
        self.assertIn('content="Janela &amp; init.', pt)

    def test_a_hidden_page_gets_no_canonical_no_twins_no_sitemap(self):
        self.fixed()
        docs = self.site(en_hidden=True)
        seo.write(docs)
        en = (docs / "en/tutorial/01-first.html").read_text(encoding="utf-8")
        pt = (docs / "pt/tutorial/01-primeiro.html").read_text(encoding="utf-8")
        self.assertNotIn("canonical", en)
        self.assertFalse(_ALT.search(en))
        self.assertFalse(_ALT.search(pt))
        self.assertIn('name="description"', en)
        sitemap = (docs / "sitemap.xml").read_text(encoding="utf-8")
        self.assertNotIn("01-first", sitemap)
        self.assertIn("01-primeiro", sitemap)

    def test_redirect_pages_are_left_alone_and_writing_twice_changes_nothing(self):
        self.fixed()
        docs = self.site(en_hidden=False)
        before = (docs / "pt/index.html").read_text(encoding="utf-8")
        self.assertTrue(seo.write(docs))
        self.assertEqual(seo.write(docs), [])
        self.assertEqual((docs / "pt/index.html").read_text(encoding="utf-8"), before)
        self.assertNotIn("/pt/index", (docs / "sitemap.xml").read_text(encoding="utf-8"))

    def test_the_two_head_writers_keep_each_others_lines(self):
        self.fixed()
        docs = self.site(en_hidden=False)
        seo.write(docs)
        path = docs / "en/tutorial/01-first.html"
        text = path.read_text(encoding="utf-8")
        again = tp.with_head(text, noindex=False, twin_lang="pt",
                             twin_href="../../pt/tutorial/01-primeiro.html")
        self.assertEqual(again, text, "tutorial_parity dropped or moved seo.py's lines")
        self.assertEqual(seo.with_head("en/tutorial/01-first.html", text, seo.site_pages(docs)), text)

    def test_translation_hashes_ignore_the_title_and_block(self):
        self.fixed()
        docs = self.site(en_hidden=False)
        path = docs / "pt/tutorial/01-primeiro.html"
        before = {n: tp.digest(t) for n, t in tp.units("01", path.read_text(encoding="utf-8"))}
        seo.write(docs)
        after = {n: tp.digest(t) for n, t in tp.units("01", path.read_text(encoding="utf-8"))}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
