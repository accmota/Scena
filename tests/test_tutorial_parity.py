"""
The English tutorials mirror the Portuguese ones (``tools/tutorial/tutorial_parity.py``).

Bug classes guarded:

* **The English code drifts from the Portuguese** (a fix lands in pt only, or
  a translator changes a number): ``code_parity`` pairs every block under one
  rename for the page.
* **A rename changes what the program does**: two Portuguese names become one
  English name; ``def atualiza`` becomes ``def update`` (now a hook);
  ``self.pontos`` becomes ``self.points`` on a Sprite; a module or a file name
  is translated.
* **A translated step goes stale**: the Portuguese step changes after its
  translation was marked.
* **Portuguese left in a translated step** (prose, comments, docstrings).
* **The draft breaks a page**: ``--draft`` renames code, snippets and anchors
  the same way, so a note still points at its line (checked on every real page).

Run:

    python tests/run_tiers.py focused test_tutorial_parity
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "tutorial"))

import tutorial_parity as tp  # noqa: E402
from tests.source_support import iter_files  # noqa: E402
from tests import test_tutorials as pages  # noqa: E402


def errors_of(pt: str, en: str) -> list:
    return tp.code_parity(textwrap.dedent(pt), textwrap.dedent(en)).errors


class TestCodeParity(unittest.TestCase):
    PT = '''\
        """Pegar estrelas."""
        from random import uniform
        from scena import *

        # A barra
        barra = Rect(center=(500, 60), width=120, height=20, color="crimson")
        st.pontos = 0

        def soltar_estrela():
            Sprite("k-rolling-ball/star.png", size=32, center=(uniform(40, 960), 780), group="estrelas")

        @collide(barra, "estrelas")
        def pegou(barra, estrela):
            estrela.destroy()
            st.pontos += 1

        placar = Text(text="", top_right=(980, 780))
        placar.text @= lambda: f"Pontos: {st.pontos}"
        run()
        '''
    EN = '''\
        """Catch the stars."""
        from random import uniform
        from scena import *

        # The paddle
        paddle = Rect(center=(500, 60), width=120, height=20, color="crimson")
        st.score = 0

        def drop_star():
            Sprite("k-rolling-ball/star.png", size=32, center=(uniform(40, 960), 780), group="stars")

        @collide(paddle, "stars")
        def caught(paddle, star):
            star.destroy()
            st.score += 1

        board = Text(text="", top_right=(980, 780))
        board.text @= lambda: f"{st.score} points"
        run()
        '''

    def test_a_faithful_translation_pairs(self):
        rn = tp.code_parity(textwrap.dedent(self.PT), textwrap.dedent(self.EN))
        self.assertEqual(rn.errors, [])
        self.assertEqual(rn.names["barra"], "paddle")
        self.assertEqual(rn.strings["estrelas"], "stars")
        self.assertNotIn("Rect", rn.names, "Scena names kept do not take part in the rename")

    def test_the_same_program_pairs_with_itself(self):
        self.assertEqual(errors_of(self.PT, self.PT), [])

    def test_a_changed_number_or_structure_is_caught(self):
        self.assertTrue(errors_of(self.PT, self.EN.replace("width=120", "width=150")))
        self.assertTrue(errors_of(self.PT, self.EN.replace("st.score += 1", "st.score += 1\n    st.score += 1")))
        self.assertTrue(errors_of(self.PT, self.EN.replace("from random import uniform", "from random import random")))

    def test_one_name_one_translation(self):
        self.assertTrue(errors_of("a = 1\nb = a\n", "x = 1\nb = y\n"), "a → x and a → y")
        self.assertTrue(errors_of("vidas = 1\npontos = 2\n", "score = 1\nscore = 2\n"),
                        "two pt names become one English name")
        self.assertTrue(errors_of('group("estrelas")\ngroup("pedras")\n', 'group("rocks")\ngroup("rocks")\n'))

    def test_an_english_name_may_not_land_on_a_scena_name(self):
        self.assertTrue(errors_of("def atualiza(dt):\n    pass\n", "def update(dt):\n    pass\n"),
                        "a plain function becomes a hook")
        self.assertTrue(errors_of("class Nave(Sprite):\n    def setup(self):\n        self.cor_viva = 1\n",
                                  "class Ship(Sprite):\n    def setup(self):\n        self.color = 1\n"),
                        "an attribute of the user's Sprite lands on a Sprite member")
        self.assertTrue(errors_of("maximo = 3\n", "max = 3\n"), "a builtin is shadowed")
        self.assertTrue(errors_of("texto = 3\n", "Text = 3\n"), "an export is shadowed")

    def test_free_words_stay_free(self):
        # A local named like a keyword argument of the API, a field of st,
        # comments, docstrings and the text of a display string.
        self.assertEqual(errors_of('cor = "red"\nRect(color=cor)\nst.cor = 1\n',
                                   'color = "red"\nRect(color=color)\nst.color = 1\n'), [])
        self.assertEqual(errors_of('x = 1  # um\n"""Doc."""\nt = f"Vidas: {x}"\n',
                                   'x = 1  # one\n"""Doc, longer."""\nt = f"{x} lives"\n'), [])
        self.assertTrue(errors_of('t = f"{a} de {b}"\n', 't = f"{a}"\n'))

    def test_a_file_name_stays_unless_the_english_file_exists(self):
        self.assertTrue(errors_of('Level("levels/ninja.json")\n', 'Level("levels/ninja_en.json")\n'))
        self.assertEqual(errors_of('Level("levels/ninja.json")\n', 'Level("levels/ninja.json")\n'), [])
        self.assertEqual(errors_of('Level("levels/ninja.json")\n', 'Level("levels/ninja_perigos.json")\n'), [],
                         "an existing file (an English level file will be one)")

    def test_text_with_a_star_is_not_a_file(self):
        # Tutorial 14i shows code on screen: Text("campo.angle += 45 * dt").
        self.assertEqual(errors_of('Text("campo.angle += 45 * dt")\n', 'Text("field.angle += 45 * dt")\n'), [])
        self.assertTrue(errors_of('Sheet("plane/Fly*.png")\n', 'Sheet("plane/Voa*.png")\n'))

    def test_a_function_body_box_pairs(self):
        self.assertEqual(errors_of("return Neon(color=cor)", "return Neon(color=colour)"), [])


class TestPageNames(unittest.TestCase):
    """``--names`` lists what a page's English twin must rename, and nothing the engine owns."""

    def test_engine_values_are_left_out_and_group_tags_stay(self):
        names, strings = tp.page_names(tp.pages(tp.PT_DIR)["02"].read_text(encoding="utf-8"))
        self.assertIn("estrela", names)
        self.assertIn("heroi", strings)
        # "forever" is a value the engine reads; a quoted word in an engine
        # docstring ("heroi" in an example) does not make it an engine word.
        for word in ("forever", "LEFT", "crimson"):
            self.assertNotIn(word, strings)
        self.assertFalse(tp._engine_word("heroi"))
        # The text of an f-string is free to translate (f"{lugar}º" → f"P{spot}"),
        # so a piece of it is not a string the glossary must rename.
        _names, race = tp.page_names(tp.pages(tp.PT_DIR)["32"].read_text(encoding="utf-8"))
        self.assertNotIn("º", race)
        self.assertTrue(tp._engine_word("ease_out"))
        for key in ("SPACE", "UP", "ESC", "ESCAPE", "A", "F1"):
            self.assertTrue(tp._engine_word(key), key)
        # A word in capitals is not a key: "RELÂMPAGO" is a track's name on screen.
        self.assertFalse(tp._engine_word("RELÂMPAGO"))

    def test_an_error_is_reported_once_per_page(self):
        pt = SAMPLE.replace("run()\n`", "def atualiza(dt):\n    pass\nrun()\n`")      # in both steps
        en = pt.replace("def atualiza", "def update").replace('lang="pt-BR"', 'lang="en"')
        errs = [e for e in tp.check_page("99", pt, en, {}, {}) if "update" in e]
        self.assertEqual(len(errs), 1, errs)


class TestRename(unittest.TestCase):
    NAMES = {"barra": "paddle", "estrela": "star", "pontos": "score"}
    STRINGS = {"estrelas": "stars"}

    def ren(self, src):
        return tp.rename_code(src, self.NAMES, self.STRINGS)

    def test_names_strings_holes_and_untouched_text(self):
        src = ('barra = Rect()  # a barra\n"""A barra."""\nSprite(group="estrelas")\n'
               'st.pontos = 1\nt = f"barra: {st.pontos:.1f}"\nx = "uma barra"\n')
        self.assertEqual(self.ren(src),
                         'paddle = Rect()  # a barra\n"""A barra."""\nSprite(group="stars")\n'
                         'st.score = 1\nt = f"barra: {st.score:.1f}"\nx = "uma barra"\n')

    def test_a_fragment_is_renamed_like_its_line(self):
        line = '    @collide(barra, "estrelas")'
        self.assertIn(self.ren('collide(barra, "estrelas'), self.ren(line))
        self.assertEqual(self.ren("estrela.destroy("), "star.destroy(")


SAMPLE = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
</head>
<body>
<script>
Tutorial.mount({
  n: "99",
  title: "Amostra",
  steps: [
    {
      title: "Um",
      body: `<p>Você cria a <code>barra</code>.</p>`,
      code: `from scena import *

barra = Rect(center=(500, 60), width=120, height=20)  # a barra
run()
`,
      notes: [
        {
          at: "barra = Rect(",
          text: "A barra, <code>group[\\"heroi\\"]</code>."
        }
      ]
    },
    {
      title: "Dois",
      example: "amostra.py",
      code: `from scena import *

barra = Rect(center=(500, 60), width=120, height=20)  # a barra
barra.move_by(1, 0)
run()
`,
      recap: `<ul><li><code>Rect</code> — uma forma.</li></ul>`
    }
  ]
});
</script>
</body>
</html>
'''
NAMES = {"pages": {"99": "99-sample.html"}, "examples": {"amostra.py": "sample.py"},
         "series": {"amostra": {"pages": ["99"], "names": {"barra": "paddle"}, "strings": {"heroi": "hero"}}}}


class TestDraftAndCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.pt, self.en = base / "pt", base / "en"
        self.pt.mkdir()
        (self.pt / "99-amostra.html").write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, state):
        return tp.check(self.pt, self.en, state, NAMES)

    def test_units_cover_the_page(self):
        us = tp.units("99", SAMPLE)
        self.assertEqual([n for n, _ in us], ["99:head", "99:1", "99:2", "99:tail"])
        self.assertEqual("".join(t for _, t in us), SAMPLE)

    def test_a_draft_is_a_pending_twin(self):
        out = tp.draft("99", self.pt, self.en, NAMES)
        text = out.read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', text)
        self.assertIn('noindex', text)
        self.assertIn('paddle = Rect(center=(500, 60)', text)
        self.assertIn('at: "paddle = Rect("', text)
        self.assertIn('example: "sample.py"', text)
        self.assertIn("<code>paddle</code>", text, "inline code names what the code names")
        self.assertIn('<code>group[\\"hero\\"]</code>', text, "inline code inside a quoted field")
        self.assertIn("# a barra", text, "comments are the translator's")
        self.assertEqual(self.check({}), [], "a draft passes while its units are pending")

    def test_a_marked_step_must_be_translated_and_stay_fresh(self):
        out = tp.draft("99", self.pt, self.en, NAMES)
        state = {n: tp.digest(t) for n, t in tp.units("99", SAMPLE)}
        errs = self.check(state)
        self.assertTrue(any("ainda tem português" in e for e in errs), errs)
        text = (out.read_text(encoding="utf-8")
                .replace("Você cria a <code>paddle</code>.", "You make the <code>paddle</code>.")
                .replace("# a barra", "# the paddle")
                .replace("A barra, ", "The paddle, ")
                .replace("uma forma.", "a shape.")
                .replace('title: "Amostra"', 'title: "Sample"'))
        out.write_text(text, encoding="utf-8")
        errs = self.check(state)
        self.assertTrue(errs and all("--publish" in e for e in errs),
                        f"a finished page is still hidden until --publish: {errs}")
        tp.sync_heads(self.pt, self.en, state)
        self.assertEqual(self.check(state), [])
        (self.pt / "99-amostra.html").write_text(SAMPLE.replace("width=120", "width=150"), encoding="utf-8")
        errs = self.check(state)
        self.assertTrue(any("o pt mudou" in e for e in errs), errs)
        self.assertTrue(any("width" in e or "120" in e for e in errs), "the code drift is reported too")

    def test_links_to_other_pages_go_to_english_when_it_exists(self):
        names = {"pages": {"99": "99-sample.html", "98": "98-other.html"}}
        (self.pt / "98-outra.html").write_text(SAMPLE.replace('n: "99"', 'n: "98"'), encoding="utf-8")
        text = '<a href="98-outra.html">x</a> <a href=\'A-depuracao.html\'>y</a>'
        self.assertEqual(tp.cross_links(text, names, self.pt, self.en),
                         '<a href="../../pt/tutorial/98-outra.html">x</a> '
                         "<a href='../../pt/tutorial/A-depuracao.html'>y</a>")
        self.en.mkdir(parents=True)
        (self.en / "98-other.html").write_text("", encoding="utf-8")
        self.assertEqual(tp.cross_links('<a href="../../pt/tutorial/98-outra.html">', names, self.pt, self.en),
                         '<a href="98-other.html">')

    def test_a_portuguese_name_left_in_inline_code_or_a_figure_is_caught(self):
        # A draft miss (tutorial 05, 2026-10-22): <code>tiros_inimigos</code> as a
        # bare group word, and st.velocidade drawn in an SVG <text>.
        gn, gs = {"barra": "paddle"}, {"heroi": "hero"}
        self.assertEqual(tp.names_left('<p>The <code>barra</code> and <code>group[\\"heroi\\"]</code>.</p>'
                                       '<svg><text x="1">barra.x = 3</text></svg>', gn, gs),
                         ['"heroi"', "barra"])
        self.assertEqual(tp.names_left("<code>paddle</code> <text>paddle</text>", gn, gs), [])
        # A file keeps its name (tutorial 22: audio/nota.ogg is a real file).
        self.assertEqual(tp.names_left("<code>audio/barra.wav</code>", gn, gs), [])
        # ...but an attribute is not a file with an extension (tutorial 19: self.meio).
        self.assertEqual(tp.names_left("<code>self.barra</code>", gn, gs), ["barra"])
        self.assertFalse(tp._is_file_name("self.barra"))
        self.assertTrue(tp._is_file_name("barra.png"))
        out = tp.draft("99", self.pt, self.en, NAMES)
        self.assertNotIn("<code>barra</code>", out.read_text(encoding="utf-8"))
        self.assertEqual(tp.rename_code("audio/barra.wav", gn, gs), "audio/paddle.wav",
                         "the scanner alone would rename it: the draft guards file names")

    def test_the_glossary_and_the_page_agree(self):
        out = tp.draft("99", self.pt, self.en, NAMES)
        out.write_text(out.read_text(encoding="utf-8").replace("paddle", "bar"), encoding="utf-8")
        self.assertTrue(any("glossário" in e for e in self.check({})))

    def test_an_english_page_without_a_twin_and_a_lost_lang(self):
        tp.draft("99", self.pt, self.en, NAMES)
        (self.en / "98-orphan.html").write_text(SAMPLE.replace('n: "99"', 'n: "98"'), encoding="utf-8")
        errs = self.check({})
        self.assertTrue(any("98-orphan.html" in e for e in errs))
        path = self.en / "99-sample.html"
        path.write_text(path.read_text(encoding="utf-8").replace('lang="en"', 'lang="pt-BR"'), encoding="utf-8")
        self.assertTrue(any('lang=\\"en\\"' in e or 'lang="en"' in e for e in self.check({})))


class TestPublishedHeads(unittest.TestCase):
    """The heads follow the translation state.

    Bug class: a finished page stays hidden (it kept ``noindex``, and the
    Portuguese twin had no link to it: the 44 English pages sat unpublished
    behind a stub index after their last unit was marked), or an unfinished
    page goes live. ``--mark`` and ``--publish`` write the lines; the check
    fails when a page disagrees; the lines never count as a change of the
    Portuguese text.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.pt, self.en = base / "pt", base / "en"
        self.pt.mkdir()
        self.ppage = self.pt / "99-amostra.html"
        self.ppage.write_text(SAMPLE, encoding="utf-8")
        self.epage = tp.draft("99", self.pt, self.en, NAMES)
        self.done = {n: tp.digest(t) for n, t in tp.units("99", SAMPLE)}

    def tearDown(self):
        self.tmp.cleanup()

    def heads(self):
        return self.ppage.read_text(encoding="utf-8"), self.epage.read_text(encoding="utf-8")

    def test_a_pending_page_is_hidden_and_its_twin_does_not_point_at_it(self):
        pt, en = self.heads()
        self.assertIn('content="noindex"', en)
        self.assertIn('hreflang="pt-BR" href="../../pt/tutorial/99-amostra.html"', en)
        self.assertNotIn("alternate", pt)
        self.assertEqual(tp.head_errors(self.pt, self.en, {}), [])

    def test_a_finished_page_is_published_both_ways(self):
        self.assertEqual(len(tp.head_errors(self.pt, self.en, self.done)), 2, "both twins disagree")
        tp.sync_heads(self.pt, self.en, self.done)
        pt, en = self.heads()
        self.assertNotIn("noindex", en)
        self.assertIn('<link rel="alternate" hreflang="en" href="../../en/tutorial/99-sample.html">', pt)
        self.assertEqual(tp.head_errors(self.pt, self.en, self.done), [])
        # A unit unmarked again (a new step to translate) hides the page again.
        partial = {k: v for k, v in self.done.items() if k != "99:2"}
        self.assertEqual(len(tp.head_errors(self.pt, self.en, partial)), 2)
        tp.sync_heads(self.pt, self.en, partial)
        self.assertEqual(self.heads()[1].count("noindex"), 1)

    def test_head_lines_change_no_unit(self):
        tp.sync_heads(self.pt, self.en, self.done)
        pt, _ = self.heads()
        self.assertNotEqual(pt, SAMPLE)
        self.assertEqual({n: tp.digest(t) for n, t in tp.units("99", pt)}, self.done)

    def test_relink_keeps_the_twin_link(self):
        tp.sync_heads(self.pt, self.en, self.done)
        en = self.heads()[1]
        self.assertEqual(tp.cross_links(en, NAMES, self.pt, self.en), en)

    def test_indexes_name_each_other(self):
        index = "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"UTF-8\">\n</head>\n</html>\n"
        (self.pt / "index.html").write_text(index, encoding="utf-8")
        (self.en / "index.html").write_text(index, encoding="utf-8")
        self.assertEqual(len(tp.head_errors(self.pt, self.en, {})), 2)
        tp.sync_heads(self.pt, self.en, {})
        self.assertIn('hreflang="en" href="../../en/tutorial/index.html"',
                      (self.pt / "index.html").read_text(encoding="utf-8"))
        self.assertIn('hreflang="pt-BR" href="../../pt/tutorial/index.html"',
                      (self.en / "index.html").read_text(encoding="utf-8"))


class TestIndexOutline(unittest.TestCase):
    """The two indexes keep one outline: wordmark, picture, cards, section headings.

    Bug class: one language's index drifts from the other's (the English
    index had no appendix heading while the Portuguese one had).
    """

    PT = ('<p class="wordmark"><a href="../../index.html">Scena</a></p>\n'
          '<img class="index-banner" src="b.webp" alt="x">\n'
          '<a class="card" href="01-primeiro.html"></a>\n'
          '<a class="card interlude" href="01i-grupos.html"></a>\n'
          '<h2 class="index-section" id="apendices">Apêndices</h2>\n'
          '<a class="card" href="A-depuracao.html"></a>\n')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.pt, self.en = base / "pt", base / "en"
        self.pt.mkdir()
        self.en.mkdir()
        (self.pt / "index.html").write_text(self.PT, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def en_index(self, text):
        (self.en / "index.html").write_text(text, encoding="utf-8")
        return tp.index_errors(self.pt, self.en)

    def test_twins_with_their_own_words_agree(self):
        en = (self.PT.replace("primeiro", "first").replace("grupos", "groups")
              .replace("apendices", "appendixes").replace("Apêndices", "Appendixes")
              .replace("depuracao", "debug-keys"))
        self.assertEqual(self.en_index(en), [])

    def test_a_missing_section_heading_fails(self):
        en = self.PT.replace('<h2 class="index-section" id="apendices">Apêndices</h2>\n', "")
        errors = self.en_index(en)
        self.assertEqual(len(errors), 1)
        self.assertIn("título de seção", errors[0])

    def test_a_missing_wordmark_picture_card_or_interlude_mark_fails(self):
        for en in (self.PT.replace('<p class="wordmark"><a href="../../index.html">Scena</a></p>\n', ""),
                   self.PT.replace('<img class="index-banner" src="b.webp" alt="x">\n', ""),
                   self.PT.replace('<a class="card" href="A-depuracao.html"></a>\n', ""),
                   self.PT.replace("card interlude", "card")):
            self.assertEqual(len(self.en_index(en)), 1, en)

    def test_the_real_indexes_agree(self):
        self.assertEqual(tp.index_errors(), [])


class TestRealPages(unittest.TestCase):
    """The tool reads every real page, and its draft keeps every page whole."""

    def test_the_repository_is_in_parity(self):
        self.assertEqual(tp.check(), [])

    def test_every_page_drafts_to_a_twin_that_passes(self):
        # An empty glossary keeps the code as it is: the draft must still pass
        # the parity check and the page checks of ``test_tutorials`` (notes,
        # snippets, focus and replaces anchors, steps).
        pt_pages = tp.pages(tp.PT_DIR)
        self.assertGreater(len(pt_pages), 30)
        examples = {os.path.basename(e): "en_" + os.path.basename(e)
                    for e in iter_files(os.path.join(ROOT, "examples"), ".py")}
        names = {"pages": {k: f"{k}-x.html" for k in pt_pages}, "examples": examples}
        with tempfile.TemporaryDirectory() as folder:
            en = Path(folder) / "docs" / "en" / "tutorial"
            for key in pt_pages:
                with self.subTest(page=key):
                    out = tp.draft(key, tp.PT_DIR, en, names)
                    text = pt_pages[key].read_text(encoding="utf-8")
                    self.assertEqual(tp.check_page(key, text, out.read_text(encoding="utf-8"), {}, names, en), [])
                    steps = pages.extract_steps(str(out))
                    self.assertEqual([s.code for s in steps],
                                     [s.code for s in pages.extract_steps(str(pt_pages[key]))])
                    for (ats, snips), step in zip(pages.step_notes(str(out)), steps):
                        for at in ats:
                            self.assertEqual(sum(at in ln for ln in step.code.split("\n")), 1, at)

    def test_the_glossary_drafts_every_page_cleanly(self):
        # names_en.json renames every page without merging two names or landing
        # on a Scena name: a Portuguese edit that adds a clashing name, or a
        # glossary edit, fails here before any page is translated by hand.
        names = tp.read_names()
        with tempfile.TemporaryDirectory() as folder:
            en = Path(folder) / "docs" / "en" / "tutorial"
            for key, path in tp.pages(tp.PT_DIR).items():
                with self.subTest(page=key):
                    out = tp.draft(key, tp.PT_DIR, en, names)
                    self.assertEqual(tp.check_page(key, path.read_text(encoding="utf-8"),
                                                   out.read_text(encoding="utf-8"), {}, names, en), [])
                    out.unlink()

    def test_english_level_files_follow_the_portuguese(self):
        names = tp.read_names()
        self.assertEqual(tp.check_levels(names), [])
        level = "levels/duelo.json"
        page = names["levels"][level]["page"]
        trimmed = {**names, "series": {k: {**v, "strings": {w: e for w, e in (v.get("strings") or {}).items()
                                                           if w != "parede"}}
                                       for k, v in names["series"].items()}}
        text, missing = tp.level_twin(level, trimmed)
        self.assertEqual(missing, ["parede"], f"page {page}: a level word with no English is named")
        self.assertTrue(any("parede" in e for e in tp.check_levels(trimmed)))

    def test_a_renaming_draft_keeps_notes_on_their_lines(self):
        # Tutorial 02 with a real glossary: every note and snippet still hits
        # its renamed line.
        key = "02"
        pt_path = tp.pages(tp.PT_DIR)[key]
        names, strings = tp.page_names(pt_path.read_text(encoding="utf-8"))
        gloss = {"pages": {key: "02-x.html"}, "examples": {"pegar_estrelas.py": "catch_stars.py"},
                 "series": {"t": {"pages": [key], "names": {n: f"{n}_en" for n in names},
                                  "strings": {s: f"{s}_en" for s in strings}}}}
        with tempfile.TemporaryDirectory() as folder:
            out = tp.draft(key, tp.PT_DIR, Path(folder) / "docs" / "en" / "tutorial", gloss)
            self.assertEqual(tp.check_page(key, pt_path.read_text(encoding="utf-8"),
                                           out.read_text(encoding="utf-8"), {}, gloss, out.parent), [])
            steps = pages.extract_steps(str(out))
            self.assertIn("estrela_en", steps[-1].code)
            for (ats, snips), step in zip(pages.step_notes(str(out)), steps):
                for at in ats:
                    self.assertEqual(sum(at in ln for ln in step.code.split("\n")), 1, at)
                for snip in snips:
                    self.assertEqual(pages.snippet_strays(step.code, snip), [], snip)


if __name__ == "__main__":
    unittest.main()
