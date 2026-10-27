#!/usr/bin/env python3
"""Keep the English tutorials in step with the Portuguese ones.

The tutorials are written in Portuguese first (``docs/pt/tutorial/``); each
English page (``docs/en/tutorial/``) mirrors one Portuguese page, paired by the
key before the first ``-`` of the file name (``05``, ``05i``, ``A``), **step by
step**. Units of a page: ``<key>:head`` (up to the steps), one ``<key>:<n>``
per step object, ``<key>:tail``. A unit of an English page is **pending** (it
may still hold Portuguese prose: ``--draft`` wrote it) or **translated**:
``tutorial_en_state.json`` records the hash of the Portuguese text it was
translated from. A Portuguese page with no English twin is pending whole.

The code of an English page is the Portuguese code renamed (``code_parity``):
the same program once every name and every word-like string goes through one
one-to-one rename for the whole page. Comments, docstrings and the text of a
display string are free; numbers, structure, imports and file names are not;
an English name must not take a Scena name or a builtin that the Portuguese
code did not use there (``def atualiza`` → ``def update`` would become a
hook). ``names_en.json`` is the glossary: a series of pages
(Naves, Ninja…) uses one English name per Portuguese name.

Checks (no option; ``tests/test_tutorial_parity.py`` runs them):

  - every English page has one Portuguese twin, the same units, ``n:`` and
    ``<html lang="en">``;
  - per step, the same shape: fields, code blocks, notes, snippets, ``try`` and
    ``dive`` items, recap and explore items, the same Guia links;
  - every code block pairs with its twin under the page's rename
    (``code_parity``), and the rename agrees with the glossary;
  - a translated unit's Portuguese text has not changed since it was
    translated (fix: translate the change — ``--diff U`` shows it — then
    ``--mark U``), and it has no Portuguese left (prose, comments, docstrings);
  - the heads follow the state (``head_errors``): an English page with every
    unit translated is published (no ``noindex``; its Portuguese twin links
    to it), one with pending units keeps ``noindex``; each English page and
    each index names its twin.

Commands (run from the repository root)::

    python tools/tutorial/tutorial_parity.py               # check
    python tools/tutorial/tutorial_parity.py --status      # translated / pending per page
    python tools/tutorial/tutorial_parity.py --names 05    # names page 05 still needs (or its rename)
    python tools/tutorial/tutorial_parity.py --draft 05    # English page 05 from pt, code renamed by the glossary
    python tools/tutorial/tutorial_parity.py --ready 05    # page 05 checked as if every unit were marked
    python tools/tutorial/tutorial_parity.py --mark U [U…] # U translated from the current pt (05 = whole page)
    python tools/tutorial/tutorial_parity.py --diff U      # pt change since U was translated
    python tools/tutorial/tutorial_parity.py --levels      # write the English level files from the Portuguese
    python tools/tutorial/tutorial_parity.py --relink      # links to Portuguese pages that now have an English twin
    python tools/tutorial/tutorial_parity.py --publish     # head lines: noindex while pending, twins name each other

The English level files (``names_en.json`` "levels") are made, not written:
the Portuguese file with its groups, item names and sheet names renamed by
the glossary of the page that reads it. The check fails while one lags.
"""
from __future__ import annotations

import ast
import builtins
import difflib
import hashlib
import io
import json
import keyword
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / "tools" / "guide"))
import guia_parity  # noqa: E402

PT_DIR = REPO / "docs" / "pt" / "tutorial"
EN_DIR = REPO / "docs" / "en" / "tutorial"
EXAMPLES = REPO / "examples"
STATE = ROOT / "tutorial_en_state.json"
NAMES = ROOT / "names_en.json"

_PAGE = re.compile(r"(\d\di?|[A-Z])-.*\.html")


# ── Pages and units ────────────────────────────────────────────────────────

def page_key(name: str) -> str:
    return name.split("-", 1)[0]


def pages(folder: Path) -> dict:
    """``{key: path}`` of the tutorial pages in ``folder``."""
    out = {}
    if folder.is_dir():
        for p in sorted(folder.iterdir()):
            if _PAGE.fullmatch(p.name):
                if page_key(p.name) in out:
                    raise ValueError(f"{folder.name}: two pages for {page_key(p.name)}")
                out[page_key(p.name)] = p
    return out


_STEP_OPEN = re.compile(r"^    \{$", re.M)
_TAIL = re.compile(r"^  \]\s*\n\}\);", re.M)


def units(key: str, text: str) -> list[tuple[str, str]]:
    """``[(name, text)]`` covering the whole page, in order."""
    opens = [m.start() for m in _STEP_OPEN.finditer(text)]
    tails = list(_TAIL.finditer(text))
    if not opens or not tails:
        raise ValueError(f"{key}: a página não tem passos (Tutorial.mount com steps)")
    cuts = [(0, f"{key}:head")] + [(pos, f"{key}:{i + 1}") for i, pos in enumerate(opens)]
    cuts.append((tails[-1].start(), f"{key}:tail"))
    return [(name, text[pos:(cuts[i + 1][0] if i + 1 < len(cuts) else len(text))])
            for i, (pos, name) in enumerate(cuts)]


def digest(text: str) -> str:
    return guia_parity.digest(bare(text))


# ── Publishing: the head lines this tool owns ──────────────────────────────
#
# An English page is published when every unit of its Portuguese twin is
# marked translated. Then it has no ``noindex``, and the twins name each other
# (``<link rel="alternate" hreflang=…>``, which tutorial.js draws as the
# language switch); a page with pending units keeps ``noindex`` and its
# Portuguese twin does not point at it. The two indexes name each other too.
# These lines are written by ``sync_heads`` (``--mark``, ``--draft``,
# ``--publish``) and left out of the unit hashes, so publishing changes no
# translation state.

_NOINDEX = '<meta name="robots" content="noindex">'
# Only the relative twin link is this tool's: the absolute ones (with the
# canonical, for search engines) are tools/site/seo.py's.
_MANAGED = re.compile(r'^(?:<meta name="robots" content="noindex">|<link rel="alternate" hreflang="[^"]*" href="(?!https?:)[^"]*">)\n',
                      re.M)
_LANG_TAG = {"pt": "pt-BR", "en": "en"}


def bare(text: str) -> str:
    """``text`` without the head lines ``sync_heads`` owns."""
    return _MANAGED.sub("", text)


def complete(key: str, pt_text: str, state: dict) -> bool:
    """Every unit of the Portuguese page ``key`` is marked translated."""
    return all(name in state for name, _ in units(key, pt_text))


def with_head(text: str, *, noindex: bool, twin_lang: str | None, twin_href: str | None) -> str:
    """``text`` with exactly the managed head lines asked for, right after
    ``<meta charset="UTF-8">``."""
    lines = (_NOINDEX + "\n" if noindex else "") + (
        f'<link rel="alternate" hreflang="{_LANG_TAG[twin_lang]}" href="{twin_href}">\n'
        if twin_href else "")
    text = bare(text)
    at = text.index('<meta charset="UTF-8">\n') + len('<meta charset="UTF-8">\n')
    return text[:at] + lines + text[at:]


def head_plan(pt_dir: Path = PT_DIR, en_dir: Path = EN_DIR, state: dict | None = None) -> dict:
    """``{path: text with the right head}`` for every page and index whose
    managed lines this tool decides."""
    state = read_state() if state is None else state
    pt, en = pages(pt_dir), pages(en_dir)
    out = {}
    for key, ppath in pt.items():
        ptext = ppath.read_text(encoding="utf-8")
        epath = en.get(key)
        done = epath is not None and complete(key, ptext, state)
        out[ppath] = with_head(ptext, noindex=False, twin_lang="en",
                               twin_href=f"../../en/tutorial/{epath.name}" if done else None)
        if epath is not None:
            out[epath] = with_head(epath.read_text(encoding="utf-8"), noindex=not done,
                                   twin_lang="pt", twin_href=f"../../pt/tutorial/{ppath.name}")
    pi, ei = pt_dir / "index.html", en_dir / "index.html"
    if pi.is_file() and ei.is_file():
        out[pi] = with_head(pi.read_text(encoding="utf-8"), noindex=False, twin_lang="en",
                            twin_href="../../en/tutorial/index.html")
        out[ei] = with_head(ei.read_text(encoding="utf-8"), noindex=False, twin_lang="pt",
                            twin_href="../../pt/tutorial/index.html")
    return out


def head_errors(pt_dir: Path = PT_DIR, en_dir: Path = EN_DIR, state: dict | None = None) -> list[str]:
    """A finished English page still hidden, a pending one live, or twins that
    do not name each other: the fix is ``--publish``."""
    errors = []
    for path, text in head_plan(pt_dir, en_dir, state).items():
        if path.read_text(encoding="utf-8") != text:
            errors.append(f"{path.parent.parent.name}/tutorial/{path.name}: o cabeçalho (noindex / "
                          f"link para a outra língua) não corresponde ao estado — rode --publish")
    return errors


def sync_heads(pt_dir: Path = PT_DIR, en_dir: Path = EN_DIR, state: dict | None = None) -> list[Path]:
    """Write the managed head lines; the paths that changed."""
    changed = []
    for path, text in head_plan(pt_dir, en_dir, state).items():
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8", newline="\n")
            changed.append(path)
    return changed


def read_state(path: Path = STATE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_state(state: dict, path: Path = STATE) -> None:
    path.write_text(json.dumps(dict(sorted(state.items())), ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")


def read_names(path: Path = NAMES) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def glossary_for(key: str, names: dict) -> tuple[dict, dict]:
    """``(names, strings)`` the glossary gives page ``key`` (every series it is in)."""
    n, s = {}, {}
    for series in (names.get("series") or {}).values():
        if key in series.get("pages", []) or "*" in series.get("pages", []):
            n.update(series.get("names") or {})
            s.update(series.get("strings") or {})
    return n, s


# ── The fields of a step ───────────────────────────────────────────────────

def _unescape(src: str) -> str:
    return src.replace("\\`", "`").replace("\\$", "$").replace("\\\\", "\\")


_CODE = re.compile(r"\bcode:\s*`((?:\\.|[^`\\])*)`", re.S)
_SNIP = re.compile(r"\bsnip:\s*`((?:\\.|[^`\\])*)`", re.S)
_AT = re.compile(r'^\s*at:\s*"((?:[^"\\]|\\.)*)"', re.M)
_FIELD = re.compile(r"^      (\w+):", re.M)
_HREF = re.compile(r'href="(\.\./guide/[^"]*)"')


def _field_text(chunk: str, field: str) -> str:
    m = re.search(rf"^      {field}:\s*`((?:\\.|[^`\\])*)`", chunk, re.M | re.S)
    return m.group(1) if m else ""


def step_shape(chunk: str) -> dict:
    """What an English step keeps from its Portuguese twin."""
    return {
        "fields": _FIELD.findall(chunk),
        "code blocks": len(_CODE.findall(chunk)),
        "notes": len(_AT.findall(chunk)),
        "snippets": len(_SNIP.findall(chunk)),
        "items (notes, try, dive)": len(re.findall(r"^        \{$", chunk, re.M)),
        "recap items": _field_text(chunk, "recap").count("<li>"),
        "explore items": _field_text(chunk, "explore").count("<li>"),
        "Guia links": _HREF.findall(chunk),
        "example": bool(re.search(r"^      example:", chunk, re.M)),
    }


def code_blocks(chunk: str) -> list[str]:
    return [_unescape(c) for c in _CODE.findall(chunk)]


# ── Code parity ────────────────────────────────────────────────────────────

# Fields that hold a name the translation may rename (one rename per page).
_NAMES = {
    ast.Name: ("id", "name"), ast.Attribute: ("attr", "attr"),
    ast.FunctionDef: ("name", "def"), ast.AsyncFunctionDef: ("name", "def"),
    ast.ClassDef: ("name", "def"), ast.arg: ("arg", "arg"), ast.keyword: ("arg", "arg"),
    ast.alias: ("asname", "name"), ast.ExceptHandler: ("name", "name"),
}
_LIST_NAMES = {ast.Global: "names", ast.Nonlocal: "names"}
_WORD = re.compile(r"^\w+$")
# A file name or pattern: no spaces ("45 * dt" on screen is text, not a glob).
_EXT = r"\.(?:png|jpe?g|gif|webp|svg|xml|json|wav|ogg|mp3|flac|ttf|otf|txt|py)"
_PATH = re.compile(r"^\S*(?:[/\\*]\S*|" + _EXT + r")$", re.I)   # self.meio is not a file

_SHADOW: set | None = None


def shadowed() -> tuple[set, set]:
    """``(top-level names, member names)`` an English rename may not land on:
    Scena's exports and Python's builtins; any public member of an export or of
    a builtin type (``.append``)."""
    global _SHADOW
    if _SHADOW is None:
        scena = guia_parity.vg._scena()
        top = set(scena.__all__) | set(dir(builtins)) | set(keyword.kwlist)
        types = {a for t in (list, dict, str, set, tuple, int, float) for a in dir(t) if not a.startswith("_")}
        _SHADOW = (top, guia_parity.surface() | top | types)
    return _SHADOW


_ENGINE_STRINGS: set | None = None


def _engine_word(s: str) -> bool:
    """A string the engine reads as a word of its own: a key (``"LEFT"``), a colour
    (``"crimson"``), a member name (``"text"``), a value the engine's own source
    spells in quotes (``"plasma"``, ``"ease_out"``, ``"ground"``). Kept as it is."""
    global _ENGINE_STRINGS
    if _ENGINE_STRINGS is None:
        words = set()
        for path in (REPO / "scena").rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            docs = {id(n.value) for n in ast.walk(tree) if _is_doc(n)}   # docstrings quote examples
            words |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
                      and isinstance(n.value, str) and id(n) not in docs and re.fullmatch(r"[a-z_][a-z0-9_]*", n.value)}
        _ENGINE_STRINGS = words
    from scena.color import ColorNames
    from scena.input import _KEY_SPELLINGS, _KEY_WORDS
    key = s in _KEY_WORDS or s in _KEY_SPELLINGS or re.fullmatch(r"[A-Z0-9]|F\d{1,2}", s) is not None
    return key or s.lower() in ColorNames._COLORS or s in shadowed()[1] or s in _ENGINE_STRINGS


def _st_members() -> set:
    scena = guia_parity.vg._scena()
    return {n for n in dir(scena.st) if not n.startswith("_")}


def _media_file(name: str) -> bool:
    return (EXAMPLES / "media" / name).is_file() or (EXAMPLES / name).is_file()


class Rename:
    """The page's rename, gathered pair by pair: ``names`` and word-like ``strings``."""

    def __init__(self):
        self.names: dict[str, str] = {}
        self.strings: dict[str, str] = {}
        self.errors: list[str] = []

    def _pair(self, table: dict, what: str, pt: str, en: str) -> None:
        if table.get(pt, en) != en:
            self.errors.append(f"{what} {pt!r} vira {table[pt]!r} e {en!r} (um nome, uma tradução)")
            return
        if pt not in table:
            for other, word in table.items():
                if word == en and other != pt:
                    self.errors.append(f"{what}s {other!r} e {pt!r} viram os dois {en!r}")
                    return
        table[pt] = en

    def name(self, role: str, pt: str, en: str, on_st: bool) -> None:
        top, members = shadowed()
        if pt == en and pt in members:
            return      # a Scena or Python name, kept: ``color=`` does not own the word ``color``
        self._pair(self.names, "o nome", pt, en)
        if pt == en:
            return
        if role in ("name", "arg") and en in top:
            self.errors.append(f"{pt!r} → {en!r}: {en!r} é um nome do Scena ou do Python")
        elif role == "def" and en in members:
            self.errors.append(f"{pt!r} → {en!r}: {en!r} é um nome do Scena (um gancho, um membro)")
        elif role == "attr" and en in (_st_members() if on_st else members):
            self.errors.append(f".{pt} → .{en}: {en!r} já é um membro do Scena")

    def string(self, pt: str, en: str) -> None:
        if _PATH.search(pt) or _PATH.search(en):
            if pt != en and not ("*" not in en and _media_file(en)):
                self.errors.append(f"arquivo {pt!r} → {en!r}: o nome de arquivo é o mesmo "
                                   "(ou um arquivo em inglês que existe em examples/)")
        elif _WORD.match(pt) and _WORD.match(en):
            self._pair(self.strings, "a string", pt, en)


def _is_doc(node) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
        and isinstance(node.value.value, str)


def _walk(a, b, rn: Rename, where: str) -> bool:
    """Pair ``a`` (pt) with ``b`` (en); ``False`` at the first structural difference."""
    if type(a) is not type(b):
        rn.errors.append(f"{where}: {type(a).__name__} no pt, {type(b).__name__} no en")
        return False
    if _is_doc(a):
        return True                                   # a docstring is free text
    if isinstance(a, ast.JoinedStr):                  # f-string: the holes, in order
        ha = [v for v in a.values if isinstance(v, ast.FormattedValue)]
        hb = [v for v in b.values if isinstance(v, ast.FormattedValue)]
        if len(ha) != len(hb):
            rn.errors.append(f"{where}: f-string com {len(ha)} campos no pt, {len(hb)} no en")
            return False
        return all(_walk(x, y, rn, where) for x, y in zip(ha, hb))
    if isinstance(a, ast.Constant):
        if isinstance(a.value, str) and isinstance(b.value, str):
            rn.string(a.value, b.value)
            return True
        if (type(a.value), a.value) != (type(b.value), b.value):
            rn.errors.append(f"{where}: {a.value!r} no pt, {b.value!r} no en")
            return False
        return True
    line = getattr(a, "lineno", None)
    here = f"{where} (linha {line} do pt)" if line else where
    role = _NAMES.get(type(a))
    for field in a._fields:
        va, vb = getattr(a, field, None), getattr(b, field, None)
        if role and field == role[0]:
            if (va is None) != (vb is None):
                rn.errors.append(f"{here}: {field} {va!r} no pt, {vb!r} no en")
                return False
            if va is not None:
                on_st = isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) and a.value.id == "st"
                rn.name(role[1], va, vb, on_st)
            continue
        if _LIST_NAMES.get(type(a)) == field:
            if len(va) != len(vb):
                rn.errors.append(f"{here}: {field} difere")
                return False
            for x, y in zip(va, vb):
                rn.name("name", x, y, False)
            continue
        if isinstance(va, list):
            if not isinstance(vb, list) or len(va) != len(vb):
                n = len(vb) if isinstance(vb, list) else "?"
                rn.errors.append(f"{here}: {field} tem {len(va)} itens no pt, {n} no en")
                return False
            for x, y in zip(va, vb):
                if isinstance(x, ast.AST):
                    if not _walk(x, y, rn, where):
                        return False
                elif x != y:
                    rn.errors.append(f"{here}: {field} {x!r} no pt, {y!r} no en")
                    return False
        elif isinstance(va, ast.AST):
            if not _walk(va, vb, rn, where):
                return False
        elif field not in ("lineno", "col_offset", "end_lineno", "end_col_offset", "type_comment") \
                and va != vb:
            rn.errors.append(f"{here}: {field} {va!r} no pt, {vb!r} no en "
                             "(módulos e nomes importados não se traduzem)")
            return False
    return True


def code_parity(pt: str, en: str, rn: Rename | None = None, where: str = "código") -> Rename:
    """Pair two programs (or fragments) under one rename; ``rn.errors`` lists what breaks it."""
    rn = rn if rn is not None else Rename()
    try:
        ta, tb = ast.parse(pt), ast.parse(en)
    except SyntaxError:
        try:                                          # a function-body box (a bare return)
            ta = ast.parse("def _():\n" + "\n".join("    " + ln for ln in pt.split("\n")))
            tb = ast.parse("def _():\n" + "\n".join("    " + ln for ln in en.split("\n")))
        except SyntaxError:                           # a piece of a block (``if x:`` alone)
            _token_parity(pt, en, rn, where)
            return rn
    _walk(ta, tb, rn, where)
    return rn


_SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
         tokenize.ENDMARKER, tokenize.FSTRING_MIDDLE}


def _tokens(src: str) -> list:
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in _SKIP:
                out.append(tok)
    except (tokenize.TokenError, SyntaxError):
        pass
    return out


def _token_parity(pt: str, en: str, rn: Rename, where: str) -> None:
    """``code_parity`` for a fragment that does not compile: token by token."""
    ta, tb = _tokens(pt), _tokens(en)
    if len(ta) != len(tb):
        rn.errors.append(f"{where}: {len(ta)} tokens no pt, {len(tb)} no en")
        return
    for a, b in zip(ta, tb):
        if a.type == tokenize.NAME and b.type == tokenize.NAME and not keyword.iskeyword(a.string):
            on_st = False
            rn.name("name", a.string, b.string, on_st)
        elif a.type == tokenize.STRING and b.type == tokenize.STRING:
            try:
                rn.string(ast.literal_eval(a.string), ast.literal_eval(b.string))
            except (ValueError, SyntaxError):
                pass
        elif (a.type, a.string) != (b.type, b.string):
            rn.errors.append(f"{where} (linha {a.start[0]} do pt): {a.string!r} no pt, {b.string!r} no en")
            return


# ── Portuguese left in a translated unit ───────────────────────────────────

def _comments_and_docs(code: str) -> str:
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type == tokenize.COMMENT:
                out.append(tok.string)
    except (tokenize.TokenError, SyntaxError):
        pass
    try:
        for node in ast.walk(ast.parse(code)):
            if _is_doc(node):
                out.append(node.value.value)
    except SyntaxError:
        pass
    return "\n".join(out)


def _is_file_name(text: str) -> bool:
    """``audio/nota.wav`` or ``"plane/Fly*.png"`` alone in inline code."""
    bare = text.replace('\\"', '"').strip().strip('"\'')
    return re.fullmatch(r"[\w.*/-]+", bare) is not None and _PATH.search(bare) is not None \
        and not _WORD.match(bare)


def names_left(unit: str, gn: dict, gs: dict) -> list[str]:
    """Portuguese names of the glossary still in a unit's inline code or figure
    text (a draft miss): ``<code>tiros_inimigos</code>``."""
    found = set()
    for chunk in re.findall(r"<code>(.*?)</code>|<text\b[^>]*>(.*?)</text>", unit, re.S):
        piece = (chunk[0] or chunk[1]).replace('\\"', '"')
        if _is_file_name(piece):
            continue                          # a file name keeps its name
        piece = re.sub(r"&\w+;", " ", piece)
        for word in re.findall(r"[A-Za-zÀ-ÿ_]\w*", re.sub(r'"[^"]*"', " ", piece)):
            if gn.get(word, word) != word:
                found.add(word)
        for word in re.findall(r'"([^"]+)"', piece):
            if gs.get(word, word) != word:
                found.add(f'"{word}"')
    return sorted(found)


def portuguese_left(unit: str) -> list[str]:
    """Portuguese words in a unit's prose, comments and docstrings (empty: clean)."""
    code = "\n".join(_comments_and_docs(c) for c in code_blocks(unit))
    prose = _CODE.sub(" ", unit)
    prose = _SNIP.sub(" ", prose)
    prose = _AT.sub(" ", prose)
    prose = re.sub(r"^\s*(focus|replaces|example):.*$", " ", prose, flags=re.M)
    return sorted(set(guia_parity.portuguese_left(prose, "page")) |
                  {m.group(0) for m in guia_parity._PT_WORDS.finditer(code)})


# ── Level files ────────────────────────────────────────────────────────────

MEDIA = EXAMPLES / "media"


def level_twin(pt_rel: str, names: dict) -> tuple[str, list[str]]:
    """The English level file for ``pt_rel`` (``"levels/ninja.json"``), as text,
    and the words the glossary has no English for. Same layout as the editor
    writes (``scena.level_format.dumps``)."""
    from scena import level_format
    entry = (names.get("levels") or {})[pt_rel]
    _gn, gs = glossary_for(entry["page"], names)
    data = json.loads((MEDIA / pt_rel).read_text(encoding="utf-8"))
    missing = []

    def en(word):
        if word not in gs:
            missing.append(word)
        return gs.get(word, word)

    for item in data.get("items", []):
        if "groups" in item:
            item["groups"] = [en(g) for g in item["groups"]]
        for key in ("name", "sheet"):
            if key in item:
                item[key] = en(item[key])
    for sheet in data.get("sheets", []):
        sheet["name"] = en(sheet["name"])
    return level_format.dumps(data), sorted(set(missing))


def check_levels(names: dict) -> list[str]:
    errors = []
    for pt_rel, entry in (names.get("levels") or {}).items():
        text, missing = level_twin(pt_rel, names)
        for word in missing:
            errors.append(f"{pt_rel}: o glossário (página {entry['page']}) não tem inglês para {word!r}")
        target = MEDIA / entry["en"]
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            errors.append(f"{entry['en']}: difere do {pt_rel} traduzido — rode tutorial_parity.py --levels")
    return errors


def write_levels(names: dict | None = None) -> list[Path]:
    names = read_names() if names is None else names
    out = []
    for pt_rel, entry in (names.get("levels") or {}).items():
        text, missing = level_twin(pt_rel, names)
        if missing:
            raise SystemExit(f"{pt_rel}: sem inglês no glossário para {', '.join(missing)}")
        target = MEDIA / entry["en"]
        target.write_text(text, encoding="utf-8", newline="\n")
        out.append(target)
    return out


# ── Check ──────────────────────────────────────────────────────────────────

def page_rename(pt_text: str, en_text: str, key: str) -> tuple[Rename, list[str]]:
    """The page's rename and the shape errors of its steps."""
    rn, errors = Rename(), []
    pu, eu = units(key, pt_text), units(key, en_text)
    if [n for n, _ in pu] != [n for n, _ in eu]:
        return rn, [f"{key}: {len(pu) - 2} passos no pt, {len(eu) - 2} no en"]
    for (name, ptext), (_n, etext) in zip(pu, eu):
        if name.endswith((":head", ":tail")):
            continue
        ps, es = step_shape(ptext), step_shape(etext)
        for field in ps:
            if ps[field] != es[field]:
                errors.append(f"{name}: {field} difere (pt {ps[field]}, en {es[field]})")
        pb, eb = code_blocks(ptext), code_blocks(etext)
        for i, (a, b) in enumerate(zip(pb, eb)):
            code_parity(a, b, rn, f"{name} bloco {i + 1}")
    return rn, errors


def check_page(key: str, pt_text: str, en_text: str, state: dict, names: dict,
               en_dir: Path = EN_DIR) -> list[str]:
    errors = []
    if not re.search(r'<html lang="en"', en_text):
        errors.append(f"{key}: a página em inglês precisa de <html lang=\"en\"> (o motor escreve no idioma da página)")
    n = lambda t: re.search(r'^\s*n:\s*"([^"]*)"', t, re.M)  # noqa: E731
    if (n(pt_text) and n(pt_text).group(1)) != (n(en_text) and n(en_text).group(1)):
        errors.append(f"{key}: n: difere")
    try:
        rn, shape = page_rename(pt_text, en_text, key)
    except ValueError as e:
        return errors + [str(e)]
    errors += shape + [f"{key}: {e}" for e in dict.fromkeys(rn.errors)]   # once per page
    gn, gs = glossary_for(key, names)
    for table, gloss, what in ((rn.names, gn, "nome"), (rn.strings, gs, "string")):
        for pt, en in table.items():
            if pt in gloss and gloss[pt] != en:
                errors.append(f"{key}: o glossário traduz o {what} {pt!r} por {gloss[pt]!r}, a página por {en!r}")
    pex = re.findall(r'^\s*example:\s*"([^"]*)"', pt_text, re.M)
    eex = re.findall(r'^\s*example:\s*"([^"]*)"', en_text, re.M)
    for a, b in zip(pex, eex):
        if a == b:
            errors.append(f"{key}: o exemplo em inglês tem nome em inglês (não {b}: examples/ guarda os dois)")
    # The body's links (the head's twin link names the Portuguese page on purpose).
    for href in re.findall(r"""href=["']\.\./\.\./pt/tutorial/((?:\d\di?|[A-Z])-[^"'#/]*\.html)""", bare(en_text)):
        twin = pages(en_dir).get(page_key(href))
        if twin is not None:
            errors.append(f"{key}: o link para ../../pt/tutorial/{href} já tem página em inglês ({twin.name})")
    eu = dict(units(key, en_text))
    for name, ptext in units(key, pt_text):
        recorded = state.get(name)
        if recorded is None:
            continue
        if recorded != digest(ptext):
            errors.append(f"{name}: o pt mudou desde a tradução — traduza a mudança "
                          f"(tutorial_parity.py --diff {name}) e rode --mark {name}")
        left = portuguese_left(bare(eu.get(name, ""))) + names_left(bare(eu.get(name, "")), gn, gs)
        if left:
            errors.append(f"{name}: traduzida, mas ainda tem português: {', '.join(left[:8])}")
    return errors


def check(pt_dir: Path = PT_DIR, en_dir: Path = EN_DIR, state: dict | None = None,
          names: dict | None = None) -> list[str]:
    """Every parity error (tests plant the folders, the state and the glossary)."""
    state = read_state() if state is None else state
    names = read_names() if names is None else names
    pt, en = pages(pt_dir), pages(en_dir)
    errors = []
    for key, epath in en.items():
        if key not in pt:
            errors.append(f"{epath.name}: nenhuma página em português com a chave {key}")
            continue
        errors += check_page(key, pt[key].read_text(encoding="utf-8"),
                             epath.read_text(encoding="utf-8"), state, names, en_dir)
    known = {n for k, p in pt.items() for n, _ in units(k, p.read_text(encoding="utf-8"))}
    for name in sorted(set(state) - known):
        errors.append(f"{name}: está no {STATE.name}, mas a unidade não existe mais no pt — tire a linha")
    for name in sorted(set(state) & known):
        if name.split(":", 1)[0] not in en:
            errors.append(f"{name}: marcada como traduzida, mas a página em inglês não existe")
    errors += head_errors(pt_dir, en_dir, state)
    if pt_dir == PT_DIR:                      # the repository's own level files
        errors += check_levels(names)
    return errors


# ── Draft: the English page from the Portuguese, code renamed ──────────────

def rename_code(src: str, names: dict, strings: dict) -> str:
    """``src`` (a program or a piece of one) with the glossary's renames.

    A scanner, not the tokenizer, so a fragment (a note's ``at``, a snippet)
    is renamed the same way as the program it comes from: names everywhere
    outside comments and strings, word-like strings whole, the holes of an
    f-string, docstrings and comments untouched.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == "#":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(src[i:j])
            i = j
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            if j < n and src[j] in "\"'" and word.lower() in ("f", "r", "b", "rb", "br", "fr", "rf", "u"):
                out.append(word)
                i = j
                k = _string_end(src, i)
                out.append(_rename_string(src[i:k], "f" in word.lower(), names, strings))
                i = k
                continue
            out.append(names.get(word, word))
            i = j
        elif c in "\"'":
            k = _string_end(src, i)
            out.append(_rename_string(src[i:k], False, names, strings))
            i = k
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _string_end(src: str, i: int) -> int:
    q = src[i:i + 3] if src[i:i + 3] in ('"""', "'''") else src[i]
    j = i + len(q)
    while j < len(src):
        if src[j] == "\\":
            j += 2
            continue
        if src.startswith(q, j):
            return j + len(q)
        if len(q) == 1 and src[j] == "\n":
            return j
        j += 1
    return len(src)


def _rename_string(lit: str, fstring: bool, names: dict, strings: dict) -> str:
    q = lit[:3] if lit[:3] in ('"""', "'''") else lit[:1]
    if len(q) == 3:
        return lit                                    # a docstring: translated by hand
    body = lit[1:-1] if lit.endswith(q) and len(lit) > 1 else lit[1:]
    close = q if lit.endswith(q) and len(lit) > 1 else ""
    if not fstring:
        return q + strings.get(body, body) + close
    parts = re.split(r"(\{[^{}]*\})", body)            # the holes are code
    return q + "".join(rename_code(p, names, strings) if p.startswith("{") and not p.startswith("{{") else p
                       for p in parts) + close


_CROSS = re.compile(r"""(href=["'])(?:\.\./\.\./pt/tutorial/)?((?:\d\di?|[A-Z])-[^"'#/]*\.html)""")


def cross_links(text: str, names: dict, pt_dir: Path = PT_DIR, en_dir: Path = EN_DIR) -> str:
    """Links to another tutorial page: its English twin when it exists, else
    the Portuguese page (``../../pt/tutorial/…``)."""
    en = pages(en_dir)
    slugs = names.get("pages") or {}

    def fix(m):
        key = page_key(m.group(2))
        if key in en:
            return m.group(1) + en[key].name
        if m.group(2) == slugs.get(key):          # an English link whose page is not there yet
            return m.group(1) + "../../pt/tutorial/" + pages(pt_dir)[key].name
        return m.group(1) + "../../pt/tutorial/" + m.group(2)
    # The head's twin link names the Portuguese page on purpose (sync_heads).
    return "".join(line if _MANAGED.fullmatch(line) else _CROSS.sub(fix, line)
                   for line in text.splitlines(keepends=True))


def _escape(src: str) -> str:
    return src.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def draft(key: str, pt_dir: Path = PT_DIR, en_dir: Path = EN_DIR, names: dict | None = None) -> Path:
    """Write the English page ``key``: the Portuguese page, ``lang="en"``,
    ``noindex``, every code block, snippet, note anchor, focus / replaces
    anchor and inline ``<code>`` renamed by the glossary. The prose stays
    Portuguese (pending)."""
    names = read_names() if names is None else names
    slug = (names.get("pages") or {}).get(key)
    if not slug or page_key(slug) != key:
        raise SystemExit(f"names_en.json: pages[{key!r}] precisa do nome da página em inglês ({key}-….html)")
    pt = pages(pt_dir)
    if key not in pt:
        raise SystemExit(f"nenhuma página {key} em {pt_dir}")
    if key in pages(en_dir):
        raise SystemExit(f"a página {key} em inglês já existe; nada feito")
    gn, gs = glossary_for(key, names)
    levels = {a: e["en"] for a, e in (names.get("levels") or {}).items()}
    gs = {**gs, **levels}                     # Level("levels/…")
    text = bare(pt[key].read_text(encoding="utf-8"))
    ren = lambda s: rename_code(s, gn, gs)  # noqa: E731
    text = re.sub(r'<html lang="[^"]*">', '<html lang="en">', text, count=1)
    # Pending: hidden from search, and naming its Portuguese twin (sync_heads).
    text = with_head(text, noindex=True, twin_lang="pt", twin_href=f"../../pt/tutorial/{pt[key].name}")
    text = re.sub(r"\b(code|snip):(\s*)`((?:\\.|[^`\\])*)`",
                  lambda m: f"{m.group(1)}:{m.group(2)}`{_escape(ren(_unescape(m.group(3))))}`", text, flags=re.S)
    text = re.sub(r'^(\s*at:\s*)"((?:[^"\\]|\\.)*)"',
                  lambda m: m.group(1) + json.dumps(ren(json.loads(f'"{m.group(2)}"')), ensure_ascii=False),
                  text, flags=re.M)
    def anchors(m):
        items = re.sub(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'',
                       lambda a: (json.dumps(ren(json.loads(f'"{a.group(1)}"')), ensure_ascii=False)
                                  if a.group(1) is not None else "'" + ren(a.group(2)) + "'"),
                       m.group(2))
        return m.group(1) + items
    text = re.sub(r"^(\s*(?:focus|replaces):\s*)(.*)$", anchors, text, flags=re.M)
    # Inline code in the prose names the same things as the code it explains.
    # Inside a double-quoted field (a note's text) its quotes are escaped: \"bolas\".
    # A bare word may be a group tag (<code>tiros_inimigos</code>): strings too.
    def inline(m):
        tag, body = m.group(1), m.group(2)
        if _is_file_name(body):               # a file name stays, unless it has an English twin
            for pt_file, en_file in levels.items():
                body = body.replace(pt_file, en_file)
            return f"<{tag}>{body}</{tag}>"
        if re.fullmatch(r"\w+", body) and body not in gn and body in gs:
            return f"<{tag}>{gs[body]}</{tag}>" if tag == "code" else m.group(0)
        if '\\"' in body:
            return f"<{tag}>" + ren(body.replace('\\"', '"')).replace('"', '\\"') + f"</{tag}>"
        return f"<{tag}>{ren(body)}</{tag}>"
    text = re.sub(r"<(code)>(.*?)</code>", inline, text, flags=re.S)
    # Code drawn in a figure (<text …>st.velocidade = -80</text>); a caption
    # in words ("a moldura: o tamanho da fase") is left to the translator.
    text = re.sub(r"(<text\b[^>]*>)(.*?)(</text>)",
                  lambda m: m.group(1) + (ren(m.group(2)) if re.search(r"[=(\[.]", m.group(2)) else m.group(2))
                  + m.group(3), text, flags=re.S)
    text = cross_links(text, names, pt_dir, en_dir)
    for pt_ex in re.findall(r'^\s*example:\s*"([^"]*)"', text, re.M):
        en_ex = (names.get("examples") or {}).get(pt_ex)
        if en_ex:
            text = re.sub(rf'^(\s*example:\s*)"{re.escape(pt_ex)}"', rf'\1"{en_ex}"', text, flags=re.M)
    en_dir.mkdir(parents=True, exist_ok=True)
    out = en_dir / slug
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


# ── Names a page needs ─────────────────────────────────────────────────────

def page_names(text: str) -> tuple[dict, dict]:
    """``({name: uses}, {word string: uses})`` of a Portuguese page's own code:
    what its English twin has to rename (Scena, Python and imported names left out)."""
    top, members = shadowed()
    names, strings, imported, params, kwargs = {}, {}, set(), set(), set()
    for chunk in _STEP_OPEN.split(text)[1:]:
        for code in code_blocks(chunk):
            try:
                tree = ast.parse(code)
            except SyntaxError:
                continue
            in_fstring = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
            for node in ast.walk(tree):
                if id(node) in in_fstring:
                    continue                  # the text of an f-string is free (code_parity)
                if isinstance(node, ast.alias):
                    imported.add(node.asname or node.name.split(".")[0])
                if isinstance(node, ast.arg):
                    params.add(node.arg)
                if isinstance(node, ast.keyword) and node.arg:
                    kwargs.add(node.arg)
                    continue                  # an API call's keyword unless a def has it
                role = _NAMES.get(type(node))
                word = getattr(node, role[0], None) if role else None
                if isinstance(word, str):
                    names[word] = names.get(word, 0) + 1
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and _WORD.match(node.value) and not _PATH.search(node.value) \
                        and not _engine_word(node.value):
                    strings[node.value] = strings.get(node.value, 0) + 1
    names = {k: v for k, v in names.items() if k not in members and k not in imported
             and k not in ("self", "dt", "_") and (k not in kwargs or k in params)}
    return names, strings


# ── Commands ───────────────────────────────────────────────────────────────

def status() -> int:
    state = read_state()
    pt, en = pages(PT_DIR), pages(EN_DIR)
    for key, path in pt.items():
        us = units(key, path.read_text(encoding="utf-8"))
        done = sum(n in state for n, _ in us)
        where = en[key].name if key in en else "—"
        print(f"{key:4} {done:3}/{len(us):<3} {where}")
    return 0


def mark(items: list[str]) -> int:
    state = read_state()
    pt = pages(PT_DIR)
    all_units = {n: t for k, p in pt.items() for n, t in units(k, p.read_text(encoding="utf-8"))}
    chosen = []
    for item in items:
        if ":" in item:
            chosen.append(item)
        else:
            chosen += [n for n in all_units if n.split(":", 1)[0] == item]
    bad = [n for n in chosen if n not in all_units] or ([] if chosen else items)
    if bad:
        print(f"unidade(s) desconhecida(s): {', '.join(bad)}")
        return 1
    for n in chosen:
        state[n] = digest(all_units[n])
    write_state(state)
    print(f"{len(chosen)} unidade(s) marcada(s) como traduzida(s)")
    for path in sync_heads(state=state):     # a page whose last unit this marked goes live
        print(f"{path.relative_to(REPO)}: cabeçalho atualizado")
    return 0


def diff(name: str) -> int:
    state = read_state()
    if name not in state:
        print(f"{name}: pendente (sem tradução marcada)")
        return 1
    key = name.split(":", 1)[0]
    pf = pages(PT_DIR)[key]
    now = dict(units(key, pf.read_text(encoding="utf-8"))).get(name, "")
    rel = pf.relative_to(REPO).as_posix()
    revs = subprocess.run(["git", "log", "--format=%H", "--follow", "--", rel], cwd=REPO,
                          capture_output=True, text=True).stdout.split()
    for rev in revs:
        files = subprocess.run(["git", "ls-tree", "--name-only", rev, f"{PT_DIR.relative_to(REPO).as_posix()}/"],
                               cwd=REPO, capture_output=True, text=True).stdout.split()
        old_rel = next((f for f in files if page_key(Path(f).name) == key), rel)
        old = subprocess.run(["git", "show", f"{rev}:{old_rel}"], cwd=REPO,
                             capture_output=True, text=True).stdout
        try:
            text = dict(units(key, old)).get(name)
        except ValueError:
            continue
        if text is not None and digest(text) == state[name]:
            sys.stdout.writelines(difflib.unified_diff(
                text.splitlines(True), now.splitlines(True), f"{name} @ {rev[:8]}", f"{name} (agora)"))
            return 0
    print(f"{name}: o texto traduzido não está no histórico do git (marcado sem commit?)")
    return 1


def names_cmd(key: str) -> int:
    pt, en = pages(PT_DIR), pages(EN_DIR)
    if key not in pt:
        print(f"nenhuma página {key}")
        return 1
    ptext = pt[key].read_text(encoding="utf-8")
    if key in en:
        rn, _ = page_rename(ptext, en[key].read_text(encoding="utf-8"), key)
        for table, what in ((rn.names, "nomes"), (rn.strings, "strings")):
            print(f"{what}:")
            for a, b in sorted(table.items()):
                if a != b:
                    print(f"  {a} → {b}")
        return 0
    gn, gs = glossary_for(key, read_names())
    names, strings = page_names(ptext)
    for table, gloss, what in ((names, gn, "nomes"), (strings, gs, "strings")):
        print(f"{what} sem tradução no glossário:")
        for word, uses in sorted(table.items(), key=lambda kv: (-kv[1], kv[0])):
            if word not in gloss:
                print(f"  {word} ({uses})")
    return 0


def ready(key: str) -> int:
    """Page ``key`` checked as if all its units were marked translated: what
    ``--mark`` would leave failing (Portuguese left, shape, code)."""
    pt, en = pages(PT_DIR), pages(EN_DIR)
    if key not in en:
        print(f"nenhuma página {key} em inglês")
        return 1
    ptext = pt[key].read_text(encoding="utf-8")
    state = {**read_state(), **{n: digest(t) for n, t in units(key, ptext)}}
    errors = check_page(key, ptext, en[key].read_text(encoding="utf-8"), state, read_names())
    for e in errors:
        print(" ", e)
    print(f"{len(errors)} erro(s)" if errors else f"{key}: pronta para --mark {key}")
    return 1 if errors else 0


def main(argv: list[str]) -> int:
    if "--status" in argv:
        return status()
    if "--mark" in argv:
        return mark(argv[argv.index("--mark") + 1:])
    if "--diff" in argv:
        return diff(argv[argv.index("--diff") + 1])
    if "--ready" in argv:
        return ready(argv[argv.index("--ready") + 1])
    if "--names" in argv:
        return names_cmd(argv[argv.index("--names") + 1])
    if "--relink" in argv:
        names = read_names()
        for path in pages(EN_DIR).values():
            text = path.read_text(encoding="utf-8")
            new = cross_links(text, names)
            if new != text:
                path.write_text(new, encoding="utf-8", newline="\n")
                print(f"{path.relative_to(REPO)}: links atualizados")
        return 0
    if "--publish" in argv:
        for path in sync_heads():
            print(f"{path.relative_to(REPO)}: cabeçalho atualizado")
        return 0
    if "--levels" in argv:
        for path in write_levels():
            print(f"{path.relative_to(REPO)}: escrita")
        return 0
    if "--draft" in argv:
        out = draft(argv[argv.index("--draft") + 1])
        print(f"{out.relative_to(REPO)}: escrita (prosa em português, código renomeado pelo glossário)")
        return 0
    errors = check()
    for e in errors:
        print(" ", e)
    print(f"{len(errors)} erro(s) de paridade" if errors else "paridade ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")   # piped on Windows: cp1252, strict
    raise SystemExit(main(sys.argv[1:]))
