#!/usr/bin/env python3
"""Keep the English Guide in step with the Portuguese one.

The Guia is written in Portuguese first (``docs/pt/guide/``); the English
Guide (``docs/en/guide/``, page ``validate_guia.PAGES["en"]``) mirrors it
**unit by unit**. Units of the page: ``head``, ``style`` (never translated: it always
comes from Portuguese), ``body`` (up to the sidebar), ``nav``
(the sidebar), ``top``, one ``chapter:<id>`` per chapter head, one unit per
``<section id>``, ``tail`` (the scripts). Units of the catalog file:
``js:head``, ``js:<BAG>`` / ``js:<BAG>:end`` around each bag, one
``card:<id>`` per card, ``js:render`` (the rendering code).

A unit is either **pending** — the English file carries the Portuguese text
verbatim — or **translated**: ``guia_en_state.json``
records the hash of the Portuguese text it was translated from.

Checks (no option; ``tests/test_guia_parity.py`` runs them):

  - the same units in the same order, and the same ids in the same order
    (links, the language switch and the Design docs use them);
  - per unit, the same shape: ``<pre>`` blocks, ``details``, table rows,
    "Não confundir" rows, headings; each ``<pre>`` uses the same Scena names
    (variables and strings may be translated, the API may not);
  - per card, the same id / kind / family / name / variants / thumb / anim,
    parameter names and slots, literal defaults, and Scena names in ``code``;
  - pending units are read from the Portuguese file (the English file on
    disk may lag; ``--sync`` writes them out and the check only warns);
  - a translated unit's Portuguese text has not changed since it was
    translated (fix: translate the change — ``--diff U`` shows it — then
    ``--mark U``);
  - a translated unit has no Portuguese left outside code.

Commands (run from the repository root)::

    python tools/guide/guia_parity.py                 # check
    python tools/guide/guia_parity.py --status        # translated / pending per chapter
    python tools/guide/guia_parity.py --sync          # pending units ← Portuguese
    python tools/guide/guia_parity.py --mark U [U…]   # U translated from the current pt
    python tools/guide/guia_parity.py --diff U        # pt change since U was translated
    python tools/guide/guia_parity.py --init          # create the English files (all pending)
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import html as _html
import json
import keyword
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import validate_guia as vg  # noqa: E402

REPO = vg.REPO
PT_DIR = vg.DOCS / "pt" / "guide"
EN_DIR = vg.DOCS / "en" / "guide"
FILES = {   # kind -> (pt file, en file)
    "page": (PT_DIR / vg.PAGES["pt"], EN_DIR / vg.PAGES["en"]),
    "js": (PT_DIR / "guia-api-catalogs.js", EN_DIR / "guia-api-catalogs.js"),
}
STATE = ROOT / "guia_en_state.json"


# ── Units ──────────────────────────────────────────────────────────────────

def _cut(text: str, cuts: list[tuple[int, str]]) -> list[tuple[str, str]]:
    cuts = sorted(cuts)
    out = []
    for i, (pos, name) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(text)
        out.append((name, text[pos:end]))
    return out


def page_units(text: str) -> list[tuple[str, str]]:
    """``[(name, text)]`` covering the whole page, in order."""
    cuts = [(0, "head")]
    # The stylesheet has no words: never marked, it always comes from pt.
    style = text.find("<style>")
    style_end = text.find("</style>", style)
    if style < 0 or style_end < 0:
        raise ValueError("página sem <style>")
    cuts.append((style, "style"))
    cuts.append((style_end + len("</style>"), "body"))
    nav = text.find('<nav class="sidebar"')
    nav_end = text.find("</nav>", nav)
    if nav < 0 or nav_end < 0:
        raise ValueError("página sem <nav class=\"sidebar\">")
    cuts.append((nav, "nav"))
    cuts.append((nav_end + len("</nav>"), "top"))
    for m in re.finditer(r'<article class="chapter[^"]*" id="([^"]+)"', text):
        cuts.append((m.start(), f"chapter:{m.group(1)}"))
    for m in re.finditer(r'<section class="[^"]*" id="([^"]+)"', text):
        cuts.append((m.start(), m.group(1)))
    end = text.rfind("</main>")
    if end < 0:
        raise ValueError("página sem </main>")
    cuts.append((end, "tail"))
    return _cut(text, cuts)


_BAG_RE = re.compile(r"^[ \t]*const (" + "|".join(b for b, _ in vg._BAGS) + r") = \[", re.M)


def js_units(text: str) -> list[tuple[str, str]]:
    """``[(name, text)]`` covering the whole catalog file, in order."""
    cuts = [(0, "js:head")]
    bags = list(_BAG_RE.finditer(text))
    render = re.search(r"^[ \t]*function esc\(", text, re.M)
    if not bags or not render:
        raise ValueError("catálogo sem bags ou sem function esc(")
    for i, b in enumerate(bags):
        cuts.append((b.start(), f"js:{b.group(1)}"))
        stop = bags[i + 1].start() if i + 1 < len(bags) else render.start()
        cards = [m for m in vg._ITEM_RE.finditer(text, b.end(), stop)]
        for m in cards:
            cuts.append((m.start(), f"card:{m.group('id')}"))
        close = re.compile(r"\n[ \t]*\];").search(text, cards[-1].end() if cards else b.end(), stop)
        if close:
            cuts.append((close.start() + 1, f"js:{b.group(1)}:end"))
    cuts.append((render.start(), "js:render"))
    return _cut(text, cuts)


def units_of(kind: str, text: str) -> list[tuple[str, str]]:
    return page_units(text) if kind == "page" else js_units(text)


# The head lines tools/site/seo.py writes (the <title> and its marked block of
# search tags) are made from each page, never translated: no hash sees them,
# so rewriting them leaves every unit as it was.
_SITE_HEAD = re.compile(r"^<title>[^\n]*</title>\n|^<!-- site head [^\n]*-->\n.*?^<!-- /site head -->\n",
                        re.M | re.S)


def digest(text: str) -> str:
    """Hash of a unit's text without the site head lines; whitespace runs
    count as one space."""
    text = _SITE_HEAD.sub("", text)
    return hashlib.sha1(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()[:12]


def read_state(path: Path = STATE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_state(state: dict, path: Path = STATE) -> None:
    path.write_text(json.dumps(dict(sorted(state.items())), ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")


# ── Shape of a unit ────────────────────────────────────────────────────────

_SURFACE: set | None = None


def surface() -> set:
    """Names an example may only spell one way: exports and their public members."""
    global _SURFACE
    if _SURFACE is None:
        scena = vg._scena()
        names = set(scena.__all__)
        for n in scena.__all__:
            obj = getattr(scena, n, None)
            names |= {a for a in dir(obj) if not a.startswith("_")}
        _SURFACE = names - set(keyword.kwlist)
    return _SURFACE


def code_names(code: str) -> list[str]:
    """Scena names a code block uses, comments and strings removed, sorted."""
    code = _html.unescape(re.sub(r"<[^>]+>", "", code))
    code = re.sub(r"#[^\n]*", "", code)
    code = re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', '""', code)
    return sorted(set(re.findall(r"[A-Za-z_]\w*", code)) & surface())


def page_shape(text: str) -> dict:
    return {
        "pre": [code_names(c) for c in re.findall(r"<pre>(.*?)</pre>", text, re.S)],
        "details": text.count("<details"),
        "rows": text.count("<tr"),
        "confuse": len(re.findall(r'<table class="confuse">', text)),
        "headings": len(re.findall(r"<h[1-4]\b", text)),
        "sig": len(re.findall(r'<p class="sig">', text)),
    }


def _literal(value: str) -> bool:
    try:
        ast.literal_eval(value)
        return True
    except (ValueError, SyntaxError):
        return False


def card_shape(card: dict) -> dict:
    return {
        "head": [card.get(k) for k in ("id", "kind", "family", "name", "variants", "thumb", "anim")],
        "params": [(p["name"], p.get("pos") or 0, p["def"] if _literal(p["def"]) else "…")
                   for p in card.get("params") or []],
        "code": code_names(card.get("code") or ""),
    }


def _cards(text: str) -> dict:
    """Catalog cards by id, read with the validator's own reader."""
    return {c["id"]: c for items in vg.load_catalogs(text=text).values() for c in items}


# ── Portuguese left in a translated unit ───────────────────────────────────

# Words that do not occur in English prose. A Portuguese term an English
# sentence must quote goes in <span lang="pt">…</span>, which is skipped.
_PT_WORDS = re.compile(
    r"\b(você|não|também|então|quando|porque|para|uma|são|está|isso|esse|essa|"
    r"pelo|pela|já|até|só|mas|muito|cada|sem|onde|outro|outra|quem|depois|"
    r"Parâmetros|Retorna|lê / escreve|leitura|Parece|Veja|exemplo)\b",
    re.I,
)


def portuguese_left(text: str, name: str) -> list[str]:
    """Portuguese words outside code in a translated unit (empty: clean)."""
    if name.startswith("card:"):   # the prose fields (code may hold strings like "pontos")
        prose = " ".join(re.findall(r'(?:idea|search):\s*"((?:\\.|[^"\\])*)"', text))
        prose += " " + " ".join(m.group("meaning") + " " + m.group("def")
                                for m in vg._P_RE.finditer(text))
    elif name.startswith("js:"):   # rendering code and glue: its string literals
        strings = re.findall(r'"((?:\\.|[^"\\])*)"|`((?:\\.|[^`\\])*)`', text)
        prose = " ".join(a or b for a, b in strings)
    else:
        prose = re.sub(r"<(pre|code|script|style)\b.*?</\1>", " ", text, flags=re.S)
        prose = re.sub(r'<(\w+)[^>]*\blang="pt[^"]*"[^>]*>.*?</\1>', " ", prose, flags=re.S)
        attrs = " ".join(re.findall(r'\b(?:aria-label|placeholder|title|alt|data-search)="([^"]*)"', prose))
        prose = re.sub(r"<[^>]+>", " ", prose) + " " + attrs
    prose = re.sub(r"<code>.*?</code>", " ", prose, flags=re.S)
    return sorted({m.group(0) for m in _PT_WORDS.finditer(_html.unescape(prose))})


# ── Check ──────────────────────────────────────────────────────────────────

def merged(kind: str, pt_text: str, en_text: str, state: dict) -> tuple[str, list[str]]:
    """The English file as it should be: translated units from ``en_text``,
    every pending unit from ``pt_text``, in the Portuguese order.

    The check reads this, not the file on disk: a Portuguese edit to a pending
    unit is not an error anywhere (``--sync`` writes it out when convenient).
    """
    eu = dict(units_of(kind, en_text))
    out, errors = [], []
    for name, ptext in units_of(kind, pt_text):
        if name in state and name not in eu:
            errors.append(f"{name}: marcada como traduzida, mas não existe no en")
        out.append(eu[name] if name in state and name in eu else ptext)
    return "".join(out), errors


def _texts(pt: dict | None, en: dict | None) -> tuple[dict, dict]:
    pt = pt if pt is not None else {k: f[0].read_text(encoding="utf-8") for k, f in FILES.items()}
    if en is None:
        en = {}
        for k, (_p, e) in FILES.items():
            if not e.exists():
                raise SystemExit(f"{e.relative_to(REPO)} não existe: rode guia_parity.py --init")
            en[k] = e.read_text(encoding="utf-8")
    return pt, en


def check(pt: dict | None = None, en: dict | None = None, state: dict | None = None) -> list[str]:
    """Every parity error. ``pt`` / ``en``: ``{kind: text}`` (tests plant them)."""
    pt, en = _texts(pt, en)
    state = read_state() if state is None else state
    errors: list[str] = []
    for kind in pt:
        etext_all, errs = merged(kind, pt[kind], en[kind], state)
        errors.extend(errs)
        pu, eu = units_of(kind, pt[kind]), units_of(kind, etext_all)
        if [n for n, _ in pu] != [n for n, _ in eu]:
            # A translated unit that cuts its own text wrong (a lost </section>).
            diff = list(difflib.unified_diff([n for n, _ in pu], [n for n, _ in eu],
                                             "pt", "en", lineterm="", n=0))[2:10]
            errors.append(f"{kind}: unidades diferentes: {' '.join(diff)}")
            continue
        if kind == "page":
            pid = re.findall(r'\sid="([^"]+)"', pt[kind])
            eid = re.findall(r'\sid="([^"]+)"', etext_all)
            if pid != eid:
                diff = list(difflib.unified_diff(pid, eid, "pt", "en", lineterm="", n=0))[2:8]
                errors.append(f"page: ids diferentes (mesma ordem, mesma grafia): {' '.join(diff)}")
        else:
            pcards, ecards = _cards(pt[kind]), _cards(etext_all)
        for (name, ptext), (_n, etext) in zip(pu, eu):
            recorded = state.get(name)
            if recorded is None:
                continue
            if recorded != digest(ptext):
                errors.append(f"{name}: o pt mudou desde a tradução — traduza a mudança "
                              f"(guia_parity.py --diff {name}) e rode --mark {name}")
            if kind == "page":
                ps, es = page_shape(ptext), page_shape(etext)
                for key in ps:
                    if ps[key] == es[key]:
                        continue
                    if key == "pre" and len(ps[key]) == len(es[key]):
                        for i, (a, b) in enumerate(zip(ps[key], es[key])):
                            if a != b:
                                errors.append(f"{name}: <pre> {i + 1} usa outros nomes da API "
                                              f"(só pt {sorted(set(a) - set(b))}, só en {sorted(set(b) - set(a))})")
                    else:
                        a, b = (len(x) if key == "pre" else x for x in (ps[key], es[key]))
                        errors.append(f"{name}: {key} difere (pt {a}, en {b})")
            elif name.startswith("card:"):
                cid = name[5:]
                a, b = card_shape(pcards[cid]), card_shape(ecards.get(cid, {}))
                for key in a:
                    if a[key] != b[key]:
                        errors.append(f"{name}: {key} difere (pt {a[key]}, en {b[key]})")
            left = portuguese_left(etext, name)
            if left:
                errors.append(f"{name}: traduzida, mas ainda tem português: {', '.join(left[:8])}")
    known = {n for k in pt for n, _ in units_of(k, pt[k])}
    for name in sorted(set(state) - known):
        errors.append(f"{name}: está no {STATE.name}, mas a unidade não existe mais no pt — tire a linha")
    return errors


def out_of_sync(pt: dict | None = None, en: dict | None = None, state: dict | None = None) -> list[str]:
    """Kinds whose English file on disk lags the Portuguese pending units."""
    pt, en = _texts(pt, en)
    state = read_state() if state is None else state
    return [k for k in pt if merged(k, pt[k], en[k], state)[0] != en[k]]


# ── Commands ───────────────────────────────────────────────────────────────

def sync() -> int:
    """Write the English files with every pending unit copied from Portuguese."""
    state = read_state()
    pt, en = _texts(None, None)
    for kind, (_pf, ef) in FILES.items():
        text, errors = merged(kind, pt[kind], en[kind], state)
        for e in errors:
            print("erro:", e)
        if text != en[kind]:
            ef.write_text(text, encoding="utf-8", newline="\n")
            print(f"{ef.relative_to(REPO)}: unidades pendentes copiadas do pt")
    return 0


def mark(names: list[str]) -> int:
    state = read_state()
    all_units = {}
    for kind, (pf, ef) in FILES.items():
        for n, t in units_of(kind, pf.read_text(encoding="utf-8")):
            all_units[n] = (kind, t)
    bad = [n for n in names if n not in all_units]
    if bad:
        print(f"unidade(s) desconhecida(s): {', '.join(bad)}")
        return 1
    for n in names:
        state[n] = digest(all_units[n][1])
    write_state(state)
    print(f"{len(names)} unidade(s) marcada(s) como traduzida(s)")
    return 0


def diff(name: str) -> int:
    """What changed in the pt text of ``name`` since its translation was marked."""
    state = read_state()
    if name not in state:
        print(f"{name}: pendente (sem tradução marcada)")
        return 1
    kind = "js" if name.startswith(("js:", "card:")) else "page"
    pf = FILES[kind][0]
    now = dict(units_of(kind, pf.read_text(encoding="utf-8"))).get(name, "")
    rel = pf.relative_to(REPO).as_posix()
    revs = subprocess.run(["git", "log", "--format=%H", "--", rel], cwd=REPO,
                          capture_output=True, text=True).stdout.split()
    for rev in revs:
        old = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=REPO,
                             capture_output=True, text=True).stdout
        try:
            text = dict(units_of(kind, old)).get(name)
        except ValueError:
            continue
        if text is not None and digest(text) == state[name]:
            sys.stdout.writelines(difflib.unified_diff(
                text.splitlines(True), now.splitlines(True), f"{name} @ {rev[:8]}", f"{name} (agora)"))
            return 0
    print(f"{name}: o texto traduzido não está no histórico do git (marcado sem commit?)")
    return 1


def status() -> int:
    state = read_state()
    pf = FILES["page"][0]
    chapter, counts = "página", {}
    for name, _t in units_of("page", pf.read_text(encoding="utf-8")):
        if name.startswith("chapter:"):
            chapter = name[8:]
        elif name == "tail":
            chapter = "página"
        done, total = counts.get(chapter, (0, 0))
        counts[chapter] = (done + (name in state), total + 1)
    for ch, (done, total) in counts.items():
        print(f"{ch:12} {done:3}/{total}")
    cards = units_of("js", FILES["js"][0].read_text(encoding="utf-8"))
    done = sum(n in state for n, _ in cards)
    print(f"{'catálogo':12} {done:3}/{len(cards)}")
    return 0


def init() -> int:
    for kind, (pf, ef) in FILES.items():
        if ef.exists():
            print(f"{ef.relative_to(REPO)} já existe; nada feito")
            return 1
    for kind, (pf, ef) in FILES.items():
        ef.write_text(pf.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    write_state({})
    print("arquivos em inglês criados (tudo pendente)")
    return 0


def main(argv: list[str]) -> int:
    if "--init" in argv:
        return init()
    if "--sync" in argv:
        return sync()
    if "--status" in argv:
        return status()
    if "--mark" in argv:
        return mark(argv[argv.index("--mark") + 1:])
    if "--diff" in argv:
        return diff(argv[argv.index("--diff") + 1])
    errors = check()
    for e in errors:
        print(" ", e)
    for kind in out_of_sync():
        print(f"aviso: {FILES[kind][1].relative_to(REPO)} tem pendentes antigas (rode --sync)")
    print(f"{len(errors)} erro(s) de paridade" if errors else "paridade ok")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
