#!/usr/bin/env python3
"""Idempotent HTML normalizer for Guia da API.html (phase 2 form)."""
from __future__ import annotations

import re
from pathlib import Path

HTML = Path(__file__).resolve().parents[2] / "docs" / "pt" / "guide" / "index.html"

MORE = {
    "comecar": [
        ("#reativo", "Reativo"),
        ("#desenhar", "Desenhar"),
        ("#frame", "Frame"),
        ("#reagir-callbacks", "Callbacks do script"),
    ],
    "reativo": [
        ("#frame", "Frame"),
        ("#reagir", "Reagir"),
        ("#mover", "Mover"),
        ("#ui", "UI"),
    ],
    "desenhar": [
        ("#colocar", "Colocar"),
        ("#aparencia", "Aparência"),
        ("#mover", "Mover"),
        ("#geometria", "Geometria"),
    ],
    "aparencia": [
        ("#desenhar", "Desenhar"),
        ("#mundo", "Mundo"),
        ("#som", "Som"),
    ],
    "mundo": [
        ("#colocar", "Colocar"),
        ("#aparencia", "Aparência"),
        ("#frame", "Frame"),
        ("#mover", "Mover"),
    ],
    "colocar": [
        ("#desenhar", "Desenhar"),
        ("#mundo", "Mundo"),
        ("#geometria", "Geometria"),
    ],
    "frame": [
        ("#reativo", "Reativo"),
        ("#reagir", "Reagir"),
        ("#mover", "Mover"),
    ],
    "mover": [
        ("#agendar", "Agendar"),
        ("#colisao", "Colisão"),
        ("#desenhar", "Desenhar"),
        ("#suite", "Suíte time= / yoyo="),
    ],
    "agendar": [
        ("#mover", "Mover"),
        ("#mode", "Mode"),
        ("#reagir", "Reagir"),
        ("#som", "Som"),
    ],
    "mode": [
        ("#agendar", "Agendar"),
        ("#desenhar-entity", "Entity"),
        ("#reagir", "Reagir"),
    ],
    "som": [
        ("#agendar-handle", "Handle"),
        ("#mode", "Mode"),
        ("#reativo", "Reativo"),
    ],
    "reagir": [
        ("#frame", "Frame"),
        ("#colisao", "Colisão"),
        ("#mode", "Mode"),
        ("#reativo", "Reativo"),
    ],
    "colisao": [
        ("#mover", "Mover"),
        ("#reagir", "Reagir"),
        ("#geometria", "Geometria"),
    ],
    "geometria": [
        ("#colocar", "Colocar"),
        ("#colisao", "Colisão"),
        ("#desenhar", "Desenhar"),
        ("#util", "Utilitários"),
    ],
    "ui": [
        ("#reativo", "Reativo"),
        ("#mundo", "Mundo"),
        ("#colocar-pais", "ui_view"),
    ],
    "util": [
        ("#mover", "Mover"),
        ("#geometria", "Geometria"),
        ("#frame", "Frame"),
    ],
    "atalhos": [
        ("#mundo-apresentacao", "Apresentação"),
        ("#frame", "Frame"),
    ],
}

OPEN_SUMMARIES = {
    "play(clip, …)",
    "Anchor",
    "Svg",
    "Sheet",
    "init",
    "canvas.display",
    "set_framerate",
    "canvas.fx_quality",
    "set_fx_auto",
    "Wallpaper",
    "SkyGradient",
    ".rotation / .scale / reset_rotation",
}

SUITE_DEFAULTS = {
    "suite-time": ("número ou None", "None"),
    "suite-ease": ("nome da curva ou função", '"linear"'),
    "suite-loops": ('1, N ou "forever"', "1"),
    "suite-yoyo": ("bool", "False"),
    "suite-face": ("bool", "False"),
    "suite-then": ("função do capítulo", ""),
    "suite-on-done": ("função ou None", "None"),
    "suite-about": ("ponto ou None", "None"),
    "suite-force": ("bool", "False"),
}


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def cells(tr: str) -> list[tuple[str, str]]:
    return re.findall(r"<td([^>]*)>(.*?)</td>", tr, re.S)


def rebuild_row(tr_open: str, parts: list[tuple[str, str]]) -> str:
    body = "".join(f"<td{attrs}>{inner}</td>" for attrs, inner in parts)
    m = re.match(r"(<tr[^>]*>)", tr_open)
    start = m.group(1) if m else "<tr>"
    return start + body + "</tr>"


def passar_of(first_inner: str) -> str:
    text = strip_tags(first_inner)
    if "=" in text or "suite-" in first_inner:
        return "nome="
    return "posição"


def clean_ret(text: str) -> str:
    t = strip_tags(text).strip()
    t = re.sub(r"^Retorna\s+", "", t)
    if t.lower().startswith("não retorna"):
        return "—"
    return t or "—"


def infer_rw(meaning: str) -> str:
    t = strip_tags(meaning).lower()
    if "só leitura" in t or t.startswith("leitura") or ">leitura<" in meaning.lower():
        return "leitura"
    if "imutável" in t:
        return "leitura"
    return "lê / escreve"


def split_sig(inner: str) -> tuple[str, str]:
    pm = re.search(r'<span class="params">(.*?)</span>', inner, re.S)
    rm = re.search(r'<span class="ret">(.*?)</span>', inner, re.S)
    params = pm.group(1) if pm else inner
    ret = clean_ret(rm.group(1) if rm else "")
    if pm:
        sig = f'<span class="params">{params}</span>'
    else:
        sig = inner
        ret = ret if rm else "—"
    return sig, ret


def convert_table(thead: str, tbody: str) -> tuple[str, str] | None:
    cols = tuple(
        strip_tags(c).strip()
        for c in re.findall(r"<th[^>]*>(.*?)</th>", thead, re.S)
    )
    rows = re.findall(r"(<tr[^>]*>.*?</tr>)", tbody, re.S)
    if not rows:
        return None

    def map_rows(fn):
        out = []
        for tr in rows:
            parts = cells(tr)
            if not parts:
                out.append(tr)
                continue
            new = fn(tr, parts)
            out.append(new)
        return "<tbody>\n" + "\n".join(out) + "\n          </tbody>"

    if cols == ("Parâmetro", "Tipo", "Significado"):
        new_head = (
            "<thead>\n            <tr><th>Parâmetro</th><th>Passar</th>"
            "<th>Tipo (default)</th><th>Significado</th></tr>\n          </thead>"
        )

        def add_pass(tr, parts):
            if len(parts) != 3:
                return tr
            (a0, i0), (a1, i1), (a2, i2) = parts
            pass_cell = passar_of(i0)
            return rebuild_row(tr, [(a0, i0), ("", pass_cell), (a1, i1), (a2, i2)])

        return new_head, map_rows(add_pass)

    if cols in (
        ("Nome", "Assinatura", "Significado"),
        ("Nome", "Assinatura", "Quando"),
        ("Método", "Assinatura", "Significado"),
    ):
        new_head = (
            "<thead>\n            <tr><th>Método</th><th>Assinatura</th>"
            "<th>Retorna</th><th>Significado</th></tr>\n          </thead>"
        )

        def split_method(tr, parts):
            if len(parts) == 4:
                return tr
            if len(parts) != 3:
                return tr
            (a0, i0), (a1, i1), (a2, i2) = parts
            if 'class="sig"' in a1 or "class=\"params\"" in i1 or "span class=\"ret\"" in i1:
                sig, ret = split_sig(i1)
                return rebuild_row(tr, [(a0, i0), (' class="sig"', sig), ("", ret), (a2, i2)])
            return rebuild_row(tr, [(a0, i0), (a1, i1), ("", "—"), (a2, i2)])

        return new_head, map_rows(split_method)

    if cols == ("Método", "Assinatura", "Retorna", "Significado"):
        def fix_four(tr, parts):
            if len(parts) != 3:
                return tr
            (a0, i0), (a1, i1), (a2, i2) = parts
            if "span class=\"ret\"" in i1 or 'class="sig"' in a1:
                sig, ret = split_sig(i1)
                return rebuild_row(tr, [(a0, i0), (' class="sig"', sig), ("", ret), (a2, i2)])
            return tr

        new_body = map_rows(fix_four)
        return thead, new_body

    if cols == ("Nome", "Tipo", "Significado"):
        new_head = (
            "<thead>\n            <tr><th>Propriedade</th><th>Tipo (valor típico)</th>"
            "<th>Leitura/Escrita</th><th>Significado</th></tr>\n          </thead>"
        )

        def add_rw(tr, parts):
            if len(parts) != 3:
                return tr
            (a0, i0), (a1, i1), (a2, i2) = parts
            return rebuild_row(tr, [(a0, i0), (a1, i1), ("", infer_rw(i2)), (a2, i2)])

        return new_head, map_rows(add_rw)

    if cols == ("Nome", "Tipo (valor típico)", "Leitura/Escrita", "Significado"):
        new_head = thead.replace(">Nome<", ">Propriedade<")
        return new_head, tbody

    if cols == ("Parâmetro", "Passar", "Tipo", "Significado"):
        new_head = thead.replace(">Tipo<", ">Tipo (default)<")
        return new_head, tbody

    return None


def normalize_tables(html: str) -> str:
    n = 0

    def repl(m):
        nonlocal n
        table_open, thead, tbody = m.group(1), m.group(2), m.group(3)
        if 'class="confuse"' in table_open:
            return m.group(0)
        converted = convert_table(thead, tbody)
        if not converted:
            return m.group(0)
        n += 1
        new_head, new_body = converted
        return f"{table_open}\n          {new_head}\n          {new_body}\n        </table>"

    html = re.sub(
        r"(<table(?:\s[^>]*)?>)\s*(<thead>.*?</thead>)\s*(<tbody>.*?</tbody>)\s*</table>",
        repl,
        html,
        flags=re.S,
    )
    print(f"tabelas convertidas/ajustadas: {n}")
    return html


def link_suite_locals(html: str) -> str:
    def face_row(m):
        if 'href="#suite-face"' in m.group(0):
            return m.group(0)
        rest = m.group(1)
        # keep type cell, replace meaning with local pointer
        return (
            '<tr><td><a href="#suite-face"><code>face=</code></a></td>'
            + rest.rsplit("<td", 1)[0]
            + '<td class="suite-local"><em>Aqui:</em> rumo na direção da viagem. '
            '<a href="#suite-face">suite</a>.</td></tr>'
        )

    html = re.sub(
        r"<tr><td><code>face=</code></td>(.*?)</tr>",
        face_row,
        html,
        flags=re.S,
    )

    def about_row(m):
        if 'href="#suite-about"' in m.group(0) or 'id="suite-about"' in m.group(0):
            return m.group(0)
        rest = m.group(1)
        local = strip_tags(rest.split("<td")[-1] if "<td" in rest else rest)
        local = re.sub(r"\s+", " ", local).strip()
        if len(local) > 140:
            local = "Pivô ou ponto que chega no destino."
        return (
            '<tr><td><a href="#suite-about"><code>about=</code></a></td>'
            + rest.rsplit("<td", 1)[0]
            + f'<td class="suite-local"><em>Aqui:</em> {local} '
            '<a href="#suite-about">suite</a>.</td></tr>'
        )

    html = re.sub(
        r"<tr><td><code>about=</code></td>(.*?)</tr>",
        about_row,
        html,
        flags=re.S,
    )
    return html


def fix_suite_defaults(html: str) -> str:
    def repl(m):
        rid = m.group(1)
        row = m.group(0)
        if rid not in SUITE_DEFAULTS:
            return row
        typ, default = SUITE_DEFAULTS[rid]
        ex = f'<span class="ex">{default}</span>' if default else ""
        row = re.sub(
            r'<span class="t">.*?</span>(?:<span class="ex">.*?</span>)?',
            f'<span class="t">{typ}</span>{ex}',
            row,
            count=1,
            flags=re.S,
        )
        return row

    return re.sub(
        r'<tr id="(suite-[^"]+)"><td>.*?</tr>',
        repl,
        html,
        flags=re.S,
    )


def open_signature_details(html: str) -> str:
    def repl(m):
        attrs, summary = m.group(1), m.group(2)
        plain = strip_tags(summary).strip()
        if "open" in attrs:
            return m.group(0)
        if plain in OPEN_SUMMARIES or plain.startswith("play("):
            return f'<details class="spec" open>\n      <summary>{summary}</summary>'
        return m.group(0)

    return re.sub(
        r'<details class="spec"([^>]*)>\s*<summary>(.*?)</summary>',
        repl,
        html,
        flags=re.S,
    )


def add_more_links(html: str) -> str:
    parts = list(re.finditer(r'<article class="chapter[^"]*"[^>]*id="([^"]+)"', html))
    if not parts:
        return html
    rebuilt = html[: parts[0].start()]
    n = 0
    for i, m in enumerate(parts):
        start = m.start()
        ident = m.group(1)
        end = parts[i + 1].start() if i + 1 < len(parts) else len(html)
        chunk = html[start:end]
        close = chunk.rfind("</article>")
        if close >= 0 and ident in MORE and 'class="more"' not in chunk:
            items = " · ".join(
                f'<a href="{href}">{label}</a>' for href, label in MORE[ident]
            )
            block = f'  <p class="more"><strong>Onde mais procurar</strong> — {items}</p>\n'
            chunk = chunk[:close] + block + chunk[close:]
            n += 1
        rebuilt += chunk
    print(f"rodapés Onde mais procurar: {n}")
    return rebuilt


def add_more_css(html: str) -> str:
    if ".more {" in html:
        return html
    css = """
  .more {
    margin-top: 2.75rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: var(--fs-secondary);
  }
"""
    return html.replace("  .page-mode {", css + "\n  .page-mode {", 1)


def search_empty_focus(html: str) -> str:
    old = """  q.addEventListener("input", () => {
    const v = q.value.trim();
    if (!v) {
      closeSearch();
      applyFilters();
      return;
    }
    runSymbolSearch(v, false);
    applyFilters();
  });
  q.addEventListener("focus", () => {
    if (q.value.trim()) runSymbolSearch(q.value, false);
  });"""
    new = """  q.addEventListener("input", () => {
    const v = q.value.trim();
    if (!v) {
      runSymbolSearch("", true);
      applyFilters();
      return;
    }
    runSymbolSearch(v, false);
    applyFilters();
  });
  q.addEventListener("focus", () => {
    runSymbolSearch(q.value, !q.value.trim());
  });"""
    if old not in html:
        print("aviso: bloco de busca não encontrado (já alterado?)")
        return html
    return html.replace(old, new, 1)


def main() -> None:
    html = HTML.read_text(encoding="utf-8")
    html = add_more_css(html)
    html = normalize_tables(html)
    html = link_suite_locals(html)
    html = fix_suite_defaults(html)
    html = open_signature_details(html)
    html = add_more_links(html)
    html = search_empty_focus(html)
    HTML.write_text(html, encoding="utf-8")
    print("gravado", HTML.name, "chars", len(html))


if __name__ == "__main__":
    main()
