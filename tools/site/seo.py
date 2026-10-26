"""The search and link-preview tags of every page in docs/, and docs/sitemap.xml.

Each page gets, right after its ``<title>`` (which this tool also writes), a
marked block::

    <!-- site head (tools/site/seo.py) -->
    <meta name="description" …>, <link rel="canonical" …>,
    <link rel="alternate" hreflang=…> (absolute, both twins and x-default),
    og:* and twitter:card (the link preview: title, text, image)
    <!-- /site head -->

Everything in it is made from the page, so the block is rewritten, never
edited by hand:

- **Tutorial pages:** the title is the page's ``Tutorial.mount`` title plus a
  tail ("Ships — Scena tutorial · 2D games in Python"); the description is the
  page's card text in its language's index plus one sentence.
- **Indexes, Guides and the docs home:** fixed text in ``FIXED`` below.
- **Twins:** a tutorial page's twin is the page its relative ``<link
  rel="alternate">`` names (``tutorial_parity.py --publish`` writes that line;
  ``tutorial.js`` draws it as the language switch, so it stays relative and
  first). The two Guides are each other's twins.
- **Hidden pages** (``noindex``) get the title and the preview tags but no
  canonical, no hreflang, and stay out of the sitemap. The two redirect pages
  (``docs/<lang>/index.html``) are left alone.

The block and the ``<title>`` line are left out of the translation hashes
(``guia_parity.digest``), so rewriting them changes no translation state.

There is no robots.txt: crawlers read it only at the host root
(``accmota.github.io/robots.txt``), which this project site does not own. The
sitemap is submitted in Google Search Console.

Commands (run from the repository root)::

    python tools/site/seo.py            # write the head blocks and docs/sitemap.xml
    python tools/site/seo.py --check    # list the files that differ; exit 1 if any
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOCS = REPO / "docs"
SITE = "https://accmota.github.io/Scena/"
SITEMAP = DOCS / "sitemap.xml"
# The link preview image (1200 × 630), made by make_og_image.py.
OG_IMAGE = "assets/og/scena.png"
OG_IMAGE_ALT = {
    "en": "Scena: 2D games and creative graphics in Python. A racing game and a space duel made with it.",
    "pt": "Scena: jogos 2D e gráficos criativos em Python. Uma corrida e um duelo espacial feitos com ele.",
}
LOCALE = {"en": "en_US", "pt": "pt_BR"}
HREFLANG = {"en": "en", "pt": "pt-BR"}

OPEN = "<!-- site head (tools/site/seo.py) -->"
CLOSE = "<!-- /site head -->"
_BLOCK = re.compile(r"^" + re.escape(OPEN) + r"\n.*?^" + re.escape(CLOSE) + r"\n", re.M | re.S)
_TITLE = re.compile(r"^<title>[^\n]*</title>\n", re.M)

# Tutorial pages: "<mount title> — <tail>"; description: "<card text> <sentence>".
TUTORIAL_TAIL = {
    "en": "Scena tutorial · 2D games in Python",
    "pt": "tutorial do Scena · jogos 2D em Python",
}
TUTORIAL_SENTENCE = {
    "en": "A step-by-step Scena tutorial: 2D games in Python.",
    "pt": "Um tutorial passo a passo do Scena: jogos 2D em Python.",
}
# Pages whose title and description are written here: path under docs/ ->
# (title, description).
FIXED = {
    "index.html": (
        "Scena — 2D games and creative graphics in Python",
        "Scena is a Python framework for 2D games and creative graphics, built for learning "
        "to program: a first program is three lines and a whole game fits on one screen. "
        "Tutorials and API guide in English and Portuguese."),
    "en/guide/index.html": (
        "Scena API Guide — 2D games and graphics in Python",
        "Everything a Scena script can call, with examples that run: shapes, sprites, text, "
        "colors, effects, backgrounds, collisions, timers, sound and input."),
    "pt/guide/index.html": (
        "Guia da API do Scena — jogos 2D e gráficos em Python",
        "Tudo o que um script Scena pode chamar, com exemplos que rodam: formas, sprites, "
        "texto, cores, efeitos, fundos, colisões, timers, som e entrada."),
    "en/tutorial/index.html": (
        "Scena tutorials — learn Python by making 2D games",
        "Step-by-step tutorials that build real Python games with Scena, from a first script "
        "to a space shooter, a platformer, Connect Four and a racing game. For readers who "
        "know basic Python."),
    "pt/tutorial/index.html": (
        "Tutoriais do Scena — aprenda Python fazendo jogos 2D",
        "Tutoriais passo a passo que constroem jogos de verdade em Python com o Scena, do "
        "primeiro script a um jogo de naves, um de plataforma, Ligue 4 e uma corrida. Para "
        "quem já conhece o básico de Python."),
}
GUIDE_TWINS = {"en/guide/index.html": "pt/guide/index.html",
               "pt/guide/index.html": "en/guide/index.html"}

_HTML_LANG = re.compile(r'<html lang="([a-z]+)')
_MOUNT_TITLE = re.compile(r'^  title: "((?:[^"\\]|\\.)*)",?$', re.M)
_CARD = re.compile(r'<a class="card[^"]*" href="([^"]+)"[^>]*>.*?<p>(.*?)</p>', re.S)
_TWIN = re.compile(r'^<link rel="alternate" hreflang="[^"]+" href="([^"]+)">$', re.M)


# ── Pages ──────────────────────────────────────────────────────────────────

def rel(path: Path, docs: Path = DOCS) -> str:
    return path.relative_to(docs).as_posix()


def url(relpath: str) -> str:
    """The page's public address; an ``index.html`` is its folder."""
    return SITE + re.sub(r"(^|/)index\.html$", r"\1", relpath)


def is_redirect(text: str) -> bool:
    return 'http-equiv="refresh"' in text


def is_hidden(text: str) -> bool:
    return 'name="robots" content="noindex"' in text


def site_pages(docs: Path = DOCS) -> dict:
    """``{relpath: text}`` of every page this tool writes, sorted (the home first)."""
    out = {}
    for p in sorted(docs.rglob("*.html"), key=lambda p: (p.parent != docs, rel(p, docs))):
        text = p.read_text(encoding="utf-8")
        if not is_redirect(text):
            out[rel(p, docs)] = text
    return out


def page_lang(text: str) -> str:
    m = _HTML_LANG.search(text)
    if not m or m.group(1) not in LOCALE:
        raise ValueError("page without <html lang=\"pt…\"> or \"en\"")
    return m.group(1)


def bare(text: str) -> str:
    """``text`` without the block this tool writes."""
    return _BLOCK.sub("", text)


def _js_string(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def _plain(fragment: str) -> str:
    """Card HTML as one line of text."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def cards(index_text: str) -> dict:
    """``{file name: card text}`` of a tutorial index."""
    return {href: _plain(p) for href, p in _CARD.findall(index_text)}


# ── Head ───────────────────────────────────────────────────────────────────

def title_and_description(relpath: str, text: str, pages: dict) -> tuple[str, str]:
    if relpath in FIXED:
        return FIXED[relpath]
    lang = page_lang(text)
    folder, name = relpath.rsplit("/", 1)
    m = _MOUNT_TITLE.search(text)
    if not folder.endswith("tutorial") or not m:
        raise ValueError(f"{relpath}: no title in FIXED and no Tutorial.mount title")
    index = pages.get(f"{folder}/index.html")
    card = cards(index).get(name) if index else None
    if not card:
        raise ValueError(f"{relpath}: no card in {folder}/index.html")
    return (f"{_js_string(m.group(1))} — {TUTORIAL_TAIL[lang]}",
            f"{card} {TUTORIAL_SENTENCE[lang]}")


def twin(relpath: str, text: str, pages: dict) -> str | None:
    """The published page in the other language, or None."""
    if relpath in GUIDE_TWINS:
        other = GUIDE_TWINS[relpath]
    else:
        m = _TWIN.search(text)
        if not m:
            return None
        other = (Path(relpath).parent / m.group(1)).as_posix()
        parts = []
        for part in other.split("/"):
            if part == "..":
                parts.pop()
            elif part != ".":
                parts.append(part)
        other = "/".join(parts)
    if other not in pages or is_hidden(pages[other]) or is_hidden(text):
        return None
    return other


def head_block(relpath: str, text: str, pages: dict) -> tuple[str, str]:
    """``(title line, block)`` for the page."""
    lang = page_lang(text)
    title, desc = title_and_description(relpath, text, pages)
    a = lambda s: html.escape(s, quote=True)  # noqa: E731
    lines = [OPEN, f'<meta name="description" content="{a(desc)}">']
    if not is_hidden(text):
        lines.append(f'<link rel="canonical" href="{url(relpath)}">')
        other = twin(relpath, text, pages)
        if other is not None:
            pair = {lang: relpath, page_lang(pages[other]): other}
            for code in ("en", "pt"):
                lines.append(f'<link rel="alternate" hreflang="{HREFLANG[code]}" href="{url(pair[code])}">')
            lines.append(f'<link rel="alternate" hreflang="x-default" href="{url(pair["en"])}">')
    lines += [
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Scena">',
        f'<meta property="og:title" content="{a(title)}">',
        f'<meta property="og:description" content="{a(desc)}">',
        f'<meta property="og:url" content="{url(relpath)}">',
        f'<meta property="og:locale" content="{LOCALE[lang]}">',
        f'<meta property="og:image" content="{SITE + OG_IMAGE}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{a(OG_IMAGE_ALT[lang])}">',
        '<meta name="twitter:card" content="summary_large_image">',
        CLOSE,
    ]
    return f"<title>{html.escape(title, quote=False)}</title>\n", "\n".join(lines) + "\n"


def with_head(relpath: str, text: str, pages: dict) -> str:
    """``text`` with its title and block rewritten (the block right after the title)."""
    title, block = head_block(relpath, text, pages)
    text = bare(text)
    m = _TITLE.search(text)
    if not m:
        raise ValueError(f"{relpath}: no <title>…</title> line")
    return text[:m.start()] + title + block + text[m.end():]


# ── Sitemap ────────────────────────────────────────────────────────────────

def sitemap(pages: dict) -> str:
    """Every page a search engine may list, one ``<url>`` each."""
    locs = "".join(f"  <url><loc>{url(r)}</loc></url>\n" for r, t in pages.items() if not is_hidden(t))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- Written by tools/site/seo.py: every page of docs/ without noindex. -->\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{locs}</urlset>\n")


def plan(docs: Path = DOCS) -> dict:
    """``{path: text}`` of every file this tool writes."""
    pages = site_pages(docs)
    out = {docs / r: with_head(r, t, pages) for r, t in pages.items()}
    out[docs / SITEMAP.name] = sitemap(pages)
    return out


def stale(docs: Path = DOCS) -> list[Path]:
    """Files whose text differs from the plan."""
    return [p for p, t in plan(docs).items()
            if not p.is_file() or p.read_text(encoding="utf-8") != t]


def write(docs: Path = DOCS) -> list[Path]:
    changed = stale(docs)
    planned = plan(docs)
    for p in changed:
        p.write_text(planned[p], encoding="utf-8", newline="\n")
    return changed


def main(argv: list[str]) -> int:
    if "--check" in argv:
        bad = stale()
        for p in bad:
            print(f"{rel(p)}: out of date: run python tools/site/seo.py")
        print("site ok" if not bad else f"{len(bad)} file(s) out of date")
        return 1 if bad else 0
    changed = write()
    print(f"{len(changed)} file(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
