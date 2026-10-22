"""The English Guide mirrors the Portuguese one (tools/guide/guia_parity.py).

The Guia is written in Portuguese first; the English page and catalog mirror
it unit by unit (a section, a chapter head, a catalog card…). A translated
unit records the hash of the Portuguese text it came from.

Bug classes:

* **Silent drift** — a Portuguese section changes after its translation and
  the English page keeps the old meaning (a renamed keyword, a removed knob).
  The recorded hash no longer matches: the check names the unit and ``--diff``
  shows the change.
* **Broken mirror** — a translation loses an id (a link from the Design docs
  or the language switch lands nowhere), a ``<pre>``, a ``details``, a table
  row, or renames an API name inside an example. Variable names and strings
  may be translated; Scena names may not.
* **Half translation** — a unit marked translated still holds Portuguese.
* **Friction on Portuguese edits** — a Portuguese edit to a unit nobody has
  translated yet is never an error (the check reads pending units from pt).

The validator's English mode (``validate_guia.set_lang("en")``) is covered
here too: its checks read the English labels, and the search index never
falls back to Portuguese text.

    python -m unittest tests.test_guia_parity -v
"""
from __future__ import annotations

import re
import sys
import unittest

from tests import repo_layout as layout

sys.path.insert(0, layout.GUIDE_TOOLS)

import guia_parity as gp  # noqa: E402
import validate_guia as vg  # noqa: E402


def _englishify(unit: str) -> str:
    """The unit with every prose run replaced by English filler, code kept."""
    parts = re.split(r"(<pre\b.*?</pre>|<code\b.*?</code>|<[^>]+>)", unit, flags=re.S)
    return "".join(p if p.startswith("<") or not re.search(r"[^\W\d_]", p) else " words "
                   for p in parts)


def _unit(text: str, kind: str, name: str) -> str:
    return dict(gp.units_of(kind, text))[name]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pt = {k: f[0].read_text(encoding="utf-8") for k, f in gp.FILES.items()}
        cls.en = {k: f[1].read_text(encoding="utf-8") for k, f in gp.FILES.items()}
        cls.state = gp.read_state()

    def translated(self, name: str, kind: str = "page"):
        """pt, en, state with ``name`` translated (prose → filler) and marked."""
        ptu = _unit(self.pt[kind], kind, name)
        en = dict(self.en)
        en[kind] = en[kind].replace(_unit(en[kind], kind, name), _englishify(ptu)) \
            if name not in self.state else en[kind]
        state = {**self.state, name: gp.digest(ptu)}
        return dict(self.pt), en, state


class TestRepo(Base):
    def test_repo_in_parity(self):
        self.assertEqual(gp.check(), [])

    def test_units_cover_every_file_once(self):
        for lang in (self.pt, self.en):
            for kind, text in lang.items():
                units = gp.units_of(kind, text)
                self.assertEqual("".join(t for _n, t in units), text)
                names = [n for n, _t in units]
                self.assertEqual(len(names), len(set(names)), kind)

    def test_chrome_is_translated(self):
        for name in ("head", "body", "tail", "js:render"):
            self.assertIn(name, self.state)
        self.assertIn('<html lang="en">', self.en["page"])
        # Published (2026-10-22): indexed like the Portuguese page (TestPublishedGuides).

    def test_stylesheet_is_never_marked(self):
        # No words: it always comes from pt, so a CSS edit needs no translation.
        self.assertNotIn("style", self.state)


class TestPending(Base):
    def test_pt_edit_to_pending_unit_is_not_an_error(self):
        # Any section nobody has translated yet (none left: nothing to test).
        pending = [n for n, t in gp.units_of("page", self.pt["page"])
                   if n not in self.state and "<h2>" in t]
        if not pending:
            self.skipTest("every section is translated")
        pt = dict(self.pt)
        unit = _unit(pt["page"], "page", pending[0])
        pt["page"] = pt["page"].replace(unit, unit.replace("<h2>", "<h2>Novo ", 1))
        self.assertEqual(gp.check(pt, self.en, self.state), [])
        self.assertEqual(gp.out_of_sync(pt, self.en, self.state), ["page"])

    def test_new_pt_section_is_pending(self):
        pt = dict(self.pt)
        unit = _unit(pt["page"], "page", "outro-motor")
        extra = '  <section class="section prose" id="nova-secao"><h2>Nova</h2></section>\n'
        pt["page"] = pt["page"].replace(unit, unit + extra)
        self.assertEqual(gp.check(pt, self.en, self.state), [])


class TestTranslated(Base):
    NAME = "script-minimo"

    def test_translated_unit_passes(self):
        pt, en, state = self.translated(self.NAME)
        self.assertEqual(gp.check(pt, en, state), [])

    def test_pt_change_after_translation_is_stale(self):
        pt, en, state = self.translated(self.NAME)
        unit = _unit(pt["page"], "page", self.NAME)
        pt["page"] = pt["page"].replace(unit, unit.replace("</h2>", " novo</h2>", 1))
        errors = gp.check(pt, en, state)
        self.assertTrue(any("o pt mudou" in e and f"--diff {self.NAME}" in e for e in errors), errors)

    def _edit_en(self, en, old, new):
        unit = _unit(en["page"], "page", self.NAME)
        self.assertIn(old, unit)
        en["page"] = en["page"].replace(unit, unit.replace(old, new, 1))

    def test_api_name_changed_in_example_is_caught(self):
        pt, en, state = self.translated(self.NAME)
        unit = _unit(en["page"], "page", self.NAME)
        pre = re.search(r"<pre>.*?</pre>", unit, re.S).group(0)
        self.assertIn("init(", pre)
        self._edit_en(en, pre, pre.replace("init(", "setup_window(", 1))
        errors = gp.check(pt, en, state)
        self.assertTrue(any("<pre> 1" in e and "init" in e for e in errors), errors)

    def test_translated_variable_names_are_fine(self):
        pt, en, state = self.translated(self.NAME)
        unit = _unit(pt["page"], "page", self.NAME)
        pt["page"] = pt["page"].replace(unit, unit.replace("</pre>", "\nnave = 1</pre>", 1))
        state[self.NAME] = gp.digest(_unit(pt["page"], "page", self.NAME))
        self._edit_en(en, "</pre>", "\nship = 1</pre>")
        self.assertEqual(gp.check(pt, en, state), [])

    def test_lost_id_is_caught(self):
        pt, en, state = self.translated(self.NAME)
        self._edit_en(en, "<h2>", '<h2 id="extra">')
        self.assertTrue(any("ids diferentes" in e for e in gp.check(pt, en, state)))

    def test_lost_pre_is_caught(self):
        pt, en, state = self.translated(self.NAME)
        unit = _unit(en["page"], "page", self.NAME)
        first = re.search(r"<pre>.*?</pre>", unit, re.S).group(0)
        self._edit_en(en, first, "")
        self.assertTrue(any("pre difere" in e for e in gp.check(pt, en, state)))

    def test_portuguese_left_is_caught(self):
        pt, en, state = self.translated(self.NAME)
        self._edit_en(en, "</h2>", "</h2><p>Você pode também</p>")
        errors = gp.check(pt, en, state)
        self.assertTrue(any("ainda tem português" in e for e in errors), errors)

    def test_portuguese_quoted_on_purpose_is_fine(self):
        pt, en, state = self.translated(self.NAME)
        self._edit_en(en, "</h2>", '</h2><p>The Guia says <span lang="pt">você</span>.</p>')
        self.assertEqual(gp.check(pt, en, state), [])

    def test_translated_unit_missing_from_en_is_caught(self):
        pt, en, state = self.translated(self.NAME)
        en["page"] = en["page"].replace(_unit(en["page"], "page", self.NAME), "")
        self.assertTrue(any("não existe no en" in e for e in gp.check(pt, en, state)))

    def test_unit_gone_from_pt_is_caught(self):
        state = {**self.state, "secao-que-sumiu": "0" * 12}
        errors = gp.check(self.pt, self.en, state)
        self.assertTrue(any("secao-que-sumiu" in e for e in errors), errors)

    def test_reordered_pt_sections_carry_translations(self):
        pt, en, state = self.translated(self.NAME)
        a = _unit(pt["page"], "page", "outro-motor")
        b = _unit(pt["page"], "page", self.NAME)
        pt["page"] = pt["page"].replace(a + b, b + a)
        self.assertEqual(gp.check(pt, en, state), [])


class TestCards(Base):
    NAME = "card:stamp-glow"

    def _card(self, text):
        return dict(gp.units_of("js", text))[self.NAME]

    def translated_card(self, idea="Soft halo.", meaning="Seconds"):
        pt = dict(self.pt)
        en = dict(self.en)
        ptc = self._card(pt["js"])
        enc = re.sub(r'idea: "(?:\\.|[^"\\])*"', f'idea: "{idea}"', ptc)
        enc = re.sub(r'search: "(?:\\.|[^"\\])*"', 'search: "glow halo"', enc)
        enc = re.sub(r'(P\("\w+", "(?:\\.|[^"\\])*", )"(?:\\.|[^"\\])*"', rf'\1"{meaning}"', enc)
        enc = enc.replace('"preto"', '"black"').replace('"meio da tela"', '"screen center"')
        en["js"] = en["js"].replace(self._card(en["js"]), enc)
        return pt, en, {**self.state, self.NAME: gp.digest(ptc)}

    def test_translated_card_passes(self):
        self.assertEqual(gp.check(*self.translated_card()), [])

    def test_renamed_parameter_is_caught(self):
        pt, en, state = self.translated_card()
        en["js"] = en["js"].replace(self._card(en["js"]),
                                    self._card(en["js"]).replace('P("radius"', 'P("size"', 1))
        self.assertTrue(any(self.NAME in e and "params" in e for e in gp.check(pt, en, state)))

    def test_portuguese_meaning_is_caught(self):
        errors = gp.check(*self.translated_card(meaning="Segundos para cada volta"))
        self.assertTrue(any("ainda tem português" in e for e in errors), errors)


class TestPublishedGuides(unittest.TestCase):
    """Both Guides are published, and each switches to the other in place.

    Bug classes: the English page keeps ``noindex`` (search engines never list
    it) or is left as ``draft.html`` behind a "being written" stub; the switch
    points at a page that does not exist or drops the section the reader was
    on (the ids are the same in both pages, so the hash carries over).
    """

    _SWITCH = re.compile(r'<a class="lang-switch" href="([^"]+)" hreflang="([^"]+)" lang="([^"]+)" '
                         r'onclick="this.hash = location.hash">')

    def test_every_guide_is_index_html_without_noindex(self):
        for lang in vg.LANGS:
            with self.subTest(lang=lang):
                self.assertEqual(vg.PAGES[lang], "index.html")
                text = (vg.DOCS / lang / "guide" / "index.html").read_text(encoding="utf-8")
                self.assertNotIn("noindex", text)
                self.assertFalse((vg.DOCS / lang / "guide" / "draft.html").exists())

    def test_each_guide_switches_to_the_other_and_keeps_the_section(self):
        other = {"pt": ("en", "en"), "en": ("pt", "pt-BR")}
        for lang in vg.LANGS:
            with self.subTest(lang=lang):
                page = vg.DOCS / lang / "guide" / "index.html"
                found = self._SWITCH.findall(page.read_text(encoding="utf-8"))
                self.assertEqual(len(found), 1, "one language switch, in the sidebar")
                href, hreflang, attr_lang = found[0]
                to, code = other[lang]
                self.assertEqual(href, f"../../{to}/guide/index.html")
                self.assertTrue((page.parent / href).resolve().is_file())
                self.assertEqual((hreflang, attr_lang), (code, code))


class TestValidatorEnglish(unittest.TestCase):
    def tearDown(self):
        vg.set_lang("pt")

    def test_set_lang_moves_paths_and_words(self):
        vg.set_lang("en")
        self.assertEqual(vg.HTML, vg.DOCS / "en" / "guide" / vg.PAGES["en"])
        self.assertEqual(vg.CATALOGS.parent, vg.DOCS / "en" / "guide")
        self.assertEqual(vg.W["params"], "Parameters")
        vg.set_lang("pt")
        self.assertEqual(vg.HTML, vg.DOCS / "pt" / "guide" / "index.html")

    def test_unknown_language_refuses(self):
        with self.assertRaises(SystemExit):
            vg.set_lang("fr")

    def test_english_parameter_row_is_checked(self):
        vg.set_lang("en")
        row = ('<tr><td><code>remap(v, in0)</code></td><td class="sig">'
               '<span class="params">Parameters: v (number), in0 (number)</span></td></tr>')
        errors = vg.check_parameter_rows(row)
        self.assertEqual(len(errors), 1)
        self.assertIn("'v'", errors[0])

    def test_english_list_joins(self):
        vg.set_lang("en")
        self.assertEqual(vg._row_doc_names("value or in_min and in_max"),
                         ["value", "in_min", "in_max"])

    def test_seconds_placeholder_is_caught(self):
        # Bug: "Parâmetros: segundos (número)" stood for wait(delay).
        row = '<span class="params">Parâmetros: segundos (número)</span>'
        self.assertEqual(len(vg.check_parameter_keywords(row)), 1)
        # Bug: "Parâmetros: valor (número)" stood for zoom_to(factor) / rotate_to(angle).
        zoom = ('<tr><td><code>zoom_to</code></td><td class="sig">'
                '<span class="params">Parâmetros: valor (número), time</span></td></tr>')
        self.assertEqual(len(vg.check_parameter_keywords(zoom)), 1)
        vg.set_lang("en")
        row = ('<tr><td><code>await wait(0.4)</code></td><td class="sig">'
               '<span class="params">Parameters: seconds (number)</span></td></tr>')
        self.assertEqual(len(vg.check_parameter_keywords(row)), 1)
        self.assertEqual(vg.check_parameter_keywords(row.replace("seconds (", "delay (")), [])
        # An English word that is a real keyword elsewhere, in a callback you
        # write (nothing to resolve), is not a placeholder.
        callback = ('<tr><td><code>on_key_down</code></td><td class="sig">'
                    '<span class="params">Parameters: key (key name)</span></td></tr>')
        self.assertEqual(vg.check_parameter_keywords(callback), [])
        # A *args callable takes any name (tag(*names)).
        star = ('<tr><td><code>tag(*names)</code></td><td class="sig">'
                '<span class="params">Parameters: names (names)</span></td></tr>')
        self.assertEqual(vg.check_parameter_keywords(star), [])

    def test_call_marked_read_write_is_caught(self):
        # Bug: .spectrum(bins=8) / amp_db(x, …) said "lê / escreve".
        row = ('<tr><td><code>.spectrum(bins=8)</code></td><td class="type"><span class="t">lista</span>'
               '</td><td>lê / escreve</td><td>…</td></tr>')
        self.assertEqual(len(vg.check_call_access_rows(row)), 1)
        self.assertEqual(vg.check_call_access_rows(row.replace("lê / escreve", "método")), [])
        self.assertEqual(vg.check_call_access_rows(), [])
        vg.set_lang("en")
        self.assertEqual(len(vg.check_call_access_rows(row.replace("lê / escreve", "read / write"))), 1)
        self.assertEqual(vg.check_call_access_rows(), [])

    def test_type_words(self):
        vg.set_lang("en")
        self.assertEqual(vg.type_word("ponto / (() → ponto)"), "point / (() → point)")
        self.assertEqual(vg.infer_type({"name": "radius"}), "number")
        vg.set_lang("pt")
        self.assertEqual(vg.infer_type({"name": "radius"}), "número")

    def test_index_never_falls_back_to_portuguese(self):
        vg.set_lang("en")
        told = vg.text_en()["oneLiners"]
        for sym in vg.core_symbols():
            key = f"{sym['name']}#{sym['anchor']}"
            self.assertEqual(sym["oneLiner"], told.get(key, ""), key)
        titles = {s["chapterTitle"] for s in vg.core_symbols()}
        self.assertNotIn("Começar", titles)
        self.assertNotIn("Colisão", titles)

    def test_index_never_shows_a_section_id(self):
        # Bug: 17 sections missing from the title table showed "util-lerp"
        # as their path in the search panel; pt now falls back to the heading.
        for sym in vg.core_symbols():
            self.assertNotEqual(sym["sectionTitle"], sym["section"], sym["name"])

    def test_every_index_title_has_english(self):
        en = vg.text_en()
        chapters = {s["chapter"] for s in vg.CORE_SYMBOLS} | {v[0] for v in vg.FAMILY_CHAPTER.values()}
        sections = {s["section"] for s in vg.CORE_SYMBOLS} | {v[1] for v in vg.FAMILY_CHAPTER.values()}
        self.assertEqual(sorted(chapters - set(en["chapterTitles"])), [])
        self.assertEqual(sorted(sections - set(en["sectionTitles"])), [])


if __name__ == "__main__":
    unittest.main()
