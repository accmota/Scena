#!/usr/bin/env python3
"""Apply Guia da API.html structural edits (phases 0–2). Idempotent-ish."""
from __future__ import annotations

import re
import sys
from pathlib import Path

HTML = Path(__file__).resolve().parents[2] / "docs" / "pt" / "guide" / "index.html"

YOYO_SHORT = (
    "Voltas ímpares invertem a direção (não recomeçam). Precisa <code>loops</code> &gt; 1."
)
YOYO_CANON = (
    "Voltas ímpares invertem a direção (trocam início/fim) em vez de recomeçar. "
    "Precisa <code>loops</code> &gt; 1 (ou <code>\"forever\"</code>); com "
    "<code>loops=1</code> levanta erro. <code>loops=N</code> finito: pousa no "
    "início se N é par, no fim se N é ímpar."
)

CSS_ADD = r"""
  .sidebar a.nav-grand {
    font-size: 12px;
    padding: 0.18rem 0.55rem 0.18rem 1.85rem;
  }

  .search-panel {
    display: none;
    position: absolute;
    left: 0;
    right: 0;
    top: calc(100% + 6px);
    z-index: 40;
    max-height: min(72vh, 32rem);
    overflow-y: auto;
    background: var(--bg-elev);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: 0 16px 48px rgba(0,0,0,.5);
    padding: 0.3rem;
  }
  .search-panel.open { display: block; }

  .search-hit {
    display: block;
    padding: 0.42rem 0.55rem;
    border-radius: 6px;
    color: var(--text);
    text-decoration: none;
  }
  .search-hit:hover, .search-hit.active {
    background: var(--accent-dim);
    text-decoration: none;
    color: var(--text);
  }
  .search-hit .sym {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-weight: 500;
    font-size: 13px;
  }
  .search-hit .kind {
    font-size: 11px;
    color: var(--dim);
    margin-left: 0.45rem;
  }
  .search-hit .path {
    font-size: 12px;
    color: var(--muted);
    margin-top: 0.1rem;
  }
  .search-hit .blurb {
    font-size: 12px;
    color: var(--dim);
    margin-top: 0.12rem;
    line-height: 1.35;
  }
  .search-empty, .search-hint {
    padding: 0.65rem 0.55rem;
    color: var(--muted);
    font-size: 13px;
  }
  .search-group {
    font-size: 11px;
    color: var(--dim);
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 0.55rem 0.55rem 0.15rem;
  }
  .all-names {
    display: block;
    width: calc(100% - 0.5rem);
    margin: 0 0.25rem 0.35rem;
    background: transparent;
    border: 1px dashed var(--border);
    color: var(--muted);
    border-radius: 6px;
    padding: 0.28rem 0.5rem;
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    text-align: left;
  }
  .all-names:hover { color: var(--text); border-color: var(--accent-line); }

  .page-mode {
    display: block;
    margin: 0 0.25rem 0.85rem;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--dim);
    border-radius: 6px;
    padding: 0.28rem 0.55rem;
    font: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .page-mode:hover, body.single-page .page-mode { color: var(--text); border-color: var(--accent-line); }

  body.single-page .chapter { display: block; }

  table.confuse { font-size: var(--fs-secondary); }
  table.confuse td { vertical-align: top; }
  .confuse-wrap { margin: 1rem 0; }

  .suite-local em { color: var(--muted); font-style: italic; }
"""

SEARCH_HTML = """  <div class="side-search">
    <input type="search" id="q" placeholder="Buscar um nome" autocomplete="off" aria-label="Buscar um nome" aria-controls="search-panel">
    <kbd class="hint">/</kbd>
    <div class="search-panel" id="search-panel" hidden></div>
  </div>
  <button class="all-names" type="button" id="allNames">Todos os nomes</button>
  <button class="page-mode" type="button" id="pageMode">Página única</button>
"""

SHAPES_NAV = """    <a href="#desenhar-shapes" class="nav-child" data-chapter="desenhar" data-search="shapes circle rect polygon point is_collapsed blend">Shapes</a>
    <a href="#circle" class="nav-child nav-grand" data-chapter="desenhar" data-search="circle disco raio">Circle</a>
    <a href="#shape-rect" class="nav-child nav-grand" data-chapter="desenhar" data-search="rect retângulo">Rect</a>
    <a href="#shape-square" class="nav-child nav-grand" data-chapter="desenhar" data-search="square quadrado">Square</a>
    <a href="#shape-line" class="nav-child nav-grand" data-chapter="desenhar" data-search="line linha length">Line</a>
    <a href="#shape-ellipse" class="nav-child nav-grand" data-chapter="desenhar" data-search="ellipse elipse">Ellipse</a>
    <a href="#shape-polygon" class="nav-child nav-grand" data-chapter="desenhar" data-search="polygon polígono">Polygon</a>
    <a href="#shape-regular" class="nav-child nav-grand" data-chapter="desenhar" data-search="regularpolygon regular n">RegularPolygon</a>
    <a href="#shape-triangle" class="nav-child nav-grand" data-chapter="desenhar" data-search="triangle triângulo equilátero isósceles base_ratio">Triangle</a>
    <a href="#shape-concave" class="nav-child nav-grand" data-chapter="desenhar" data-search="concave côncavo concha scoop rim rampa quarter-pipe half-pipe pinball curva canto">Concave</a>
    <a href="#shape-point" class="nav-child nav-grand" data-chapter="desenhar" data-search="point ponto anchor">Point</a>
"""

STAMPS_CHIPS = """    <div class="chips" data-filter-group="stamps">
      <button class="chip active" type="button" data-filter="all">todos</button>
      <button class="chip" type="button" data-filter="glow">glow</button>
      <button class="chip" type="button" data-filter="shadow">shadow</button>
      <button class="chip" type="button" data-filter="hue">hue</button>
      <button class="chip" type="button" data-filter="motion">motion</button>
    </div>
"""

STATE_BLOCK = """
    <details class="spec" open id="reativo-state">
      <summary>Neste State</summary>
      <p class="one-liner"><code>st</code> é um <code>State(name="st")</code>. Dá para criar outro saco com o mesmo contrato.</p>
      <p class="sig"><code>State(name="State")</code></p>
      <p class="sig-hint">Nome com <code>=</code>: passe pelo nome. <code>name</code> é o rótulo nas mensagens de erro — não é uma chave.</p>
      <div class="tbl-wrap">
        <table>
          <thead>
            <tr><th>Parâmetro</th><th>Passar</th><th>Tipo (default)</th><th>Significado</th></tr>
          </thead>
          <tbody>
            <tr><td><code>name</code></td><td>nome=</td><td class="type"><span class="t">str</span><span class="ex">"State"</span></td><td>Rótulo de diagnóstico. O saco global é <code>State(name="st")</code>. Vazio levanta <code>ValueError</code>.</td></tr>
          </tbody>
        </table>
        <p class="name-group">Propriedades</p>
        <table>
          <thead>
            <tr><th>Propriedade</th><th>Tipo (valor típico)</th><th>Leitura/Escrita</th><th>Significado</th></tr>
          </thead>
          <tbody>
            <tr><td><code>.name</code></td><td class="type"><span class="t">str</span><span class="ex">"hud"</span></td><td>leitura</td><td>O rótulo passado no construtor.</td></tr>
            <tr><td><code>st.score = 0</code></td><td class="type"><span class="t">Attribute</span></td><td>lê / escreve</td><td>Cria (ou grava) uma célula. <code>st.score</code> lê o valor.</td></tr>
            <tr><td><code>st["hud"] @=</code></td><td class="type"><span class="t">ligação</span></td><td>escreve</td><td>Liga aquele campo. A célula precisa existir.</td></tr>
          </tbody>
        </table>
      </div>
    </details>
"""

GLOBAIS_SECTION = """  <section class="section prose" id="globais">
    <h2>Objetos globais únicos</h2>
    <p class="one-liner">Singletons depois de <code>from scena import *</code>. Classes, funções e o catálogo de efeitos entram pelo mesmo import — a busca é o índice.</p>
    <div class="tbl-wrap wrap-first">
      <table>
        <thead>
          <tr><th>Nome</th><th>Tipo (valor típico)</th><th>Leitura/Escrita</th><th>Significado</th></tr>
        </thead>
        <tbody>
          <tr><td><code>st</code></td><td class="type"><span class="t">State</span></td><td>lê / escreve</td><td>Estado do app. <a href="#reativo-liga">Reativo</a>.</td></tr>
          <tr><td><code>canvas</code></td><td class="type"><span class="t">Canvas</span></td><td>lê / escreve</td><td>Janela, câmera, post, background. <a href="#mundo">Mundo</a>.</td></tr>
          <tr><td><code>clock</code></td><td class="type"><span class="t">Clock</span></td><td>lê / escreve</td><td>Tempo do mundo. <a href="#frame-clock">clock</a>.</td></tr>
          <tr><td><code>keyp</code></td><td class="type"><span class="t">KeyPressed</span></td><td>lê</td><td>Teclado em nível. <a href="#frame-teclado">Teclado</a>.</td></tr>
          <tr><td><code>mouse</code></td><td class="type"><span class="t">Mouse</span></td><td>lê</td><td>Ponteiro. <a href="#frame-mouse">Mouse</a>.</td></tr>
          <tr><td><code>audio</code></td><td class="type"><span class="t">mixer</span></td><td>lê / escreve</td><td>Bus mestre. <a href="#som-audio">audio</a>.</td></tr>
          <tr><td><code>ui</code></td><td class="type"><span class="t">pilha</span></td><td>lê / escreve</td><td>Widgets e coluna. <a href="#ui">UI</a>.</td></tr>
          <tr><td><code>group</code></td><td class="type"><span class="t">GroupOperator</span></td><td>lê / escreve</td><td>Coleções por tag. <a href="#mundo-grupos">Grupos</a>.</td></tr>
          <tr><td><code>collision</code></td><td class="type"><span class="t">CollisionWorld</span></td><td>lê / escreve</td><td>Consultas e overlay. <a href="#colisao-aux">Colisão</a>.</td></tr>
        </tbody>
      </table>
    </div>
  </section>
"""

COMECAR_CALLBACKS = """  <section class="section prose" id="comecar-callbacks">
    <h2>Callbacks do script</h2>
    <p class="one-liner"><code>run()</code> liga estes nomes nos globais. Exemplo mínimo; a tabela completa está em <a href="#reagir-callbacks">Callbacks do script</a>.</p>
    <div class="code-panel">
      <button class="copy-btn" type="button">copiar</button>
<pre>def setup(canvas):
    canvas.fx_quality = "high"

def update(dt, canvas):
    if keyp("RIGHT"):
        player.move_by(200 * dt, 0)

def on_key_down(key):
    if key == "ESC":
        canvas.reset_view()

def on_mouse_scroll(xoffset, yoffset):
    factor = 1.1 if yoffset > 0 else 1 / 1.1
    canvas.zoom_by(factor, about=(mouse.x, mouse.y))</pre>
    </div>
    <p>O motor manda a tupla completa e corta o que a função não pede. <code>update(dt)</code> e <code>update(dt, canvas)</code> valem os dois. Catálogo: <a href="#reagir-callbacks">Callbacks do script</a> e <a href="#reagir-callbacks-entity">Callbacks da Entity</a>.</p>
  </section>
"""

JUMP = {
    "comecar": """    <p class="which">
      Script mínimo → <a href="#script-minimo">Script mínimo</a><br>
      Regras → <a href="#regras">Regras</a><br>
      Arquivo PNG / SVG → <a href="#arquivos-imagem">Arquivos de imagem</a><br>
      st / canvas / clock… → <a href="#globais">Objetos globais únicos</a><br>
      setup / update / on_key → <a href="#reagir-callbacks">Callbacks do script</a>
    </p>""",
    "reativo": """    <p class="which">
      Ligar um campo → <a href="#reativo-liga">Ligar</a><br>
      O que pode ficar à direita → <a href="#reativo-fontes">O que pode ser ligado</a><br>
      Outro saco além do st → <a href="#reativo-state"><code>State</code></a><br>
      Lambda num for → <a href="#reativo-lambda">Lambda</a>
    </p>""",
    "desenhar": """    <p class="which">
      Circle / Rect / Line… → <a href="#desenhar-shapes">Shapes</a><br>
      Imagem / atlas → <a href="#desenhar-sprite">Sprite</a><br>
      Curva → <a href="#desenhar-track">Track</a><br>
      Texto → <a href="#desenhar-text">Text</a><br>
      Fogo / chuva no mundo → <a href="#desenhar-spatial">SpatialFx</a><br>
      Ator sem desenho → <a href="#desenhar-entity">Entity</a>
    </p>""",
    "aparencia": """    <p class="which">
      Cor / Gradient / Texture → <a href="#aparencia-cor">Cor / Gradient</a><br>
      Blend → <a href="#aparencia-blend">Blend</a><br>
      .glow / .shadow / .tail → <a href="#aparencia-selos">Selos</a><br>
      Neon / Halo / … → <a href="#aparencia-visual">Visual</a><br>
      Morte / hit / knock → <a href="#aparencia-transientes">Transientes</a><br>
      Blur / DropShadow → <a href="#aparencia-filtros">Filtros</a>
    </p>""",
    "mundo": """    <p class="which">
      Fundo → <a href="#mundo-background">Background</a><br>
      Vignette / Bloom / flash → <a href="#mundo-post">Post</a><br>
      Zoom / pan / frame_to → <a href="#mundo-camera">Câmera</a><br>
      FPS / qualidade → <a href="#mundo-apresentacao">Apresentação</a><br>
      layer= → <a href="#mundo-camadas">Camadas</a><br>
      group["wasp"] → <a href="#mundo-grupos">Grupos</a>
    </p>""",
    "mover": """    <p class="which">
      move_to / rotate / scale → <a href="#mover-pose">move / rotate / scale</a><br>
      Suíte time= / yoyo= → <a href="#suite">suite</a><br>
      Segurar na região → <a href="#mover-confine">confine</a><br>
      Interpolar Attribute → <a href="#mover-tween">tween</a>
    </p>""",
    "agendar": """    <p class="which">
      after / every → <a href="#agendar-timers">after / every</a><br>
      Cooldown → <a href="#agendar-ready">ready</a><br>
      Janela de tempo → <a href="#agendar-recently">recently</a><br>
      then= / on_done= → <a href="#agendar-fim">Ao terminar</a><br>
      O retorno do tween → <a href="#agendar-handle">Handle</a>
    </p>""",
    "mode": """    <p class="which">
      Entrar num capítulo → <a href="#mode-enter">mode</a><br>
      wait / parallel / race → <a href="#mode-async">espera async</a><br>
      Cancelar o capítulo → <a href="#mode-cancela">escopo e cancelamento</a>
    </p>""",
    "geometria": """    <p class="which">
      Vetor → <a href="#geo-vec2">Vec2</a><br>
      Cruzamento de contornos → <a href="#geo-intersecoes">Interseções</a><br>
      distance / heading / closest_point → <a href="#geo-helpers">Pontos</a>
    </p>""",
    "ui": """    <p class="which">
      Todos os widgets → <a href="#ui-widgets">Widgets</a><br>
      Empilhar em coluna → <a href="#ui-stack">Coluna</a><br>
      Button / Slider / CheckBox / TextInput / DropDown → as seções seguintes<br>
      Folga na pilha → <a href="#ui-gap">ui.gap</a><br>
      Próxima coluna → <a href="#ui-stack-column">ui.stack_column</a>
    </p>""",
    "util": """    <p class="which">
      Remapear intervalo → <a href="#util-remap">remap</a><br>
      Misturar dois valores → <a href="#util-lerp">lerp</a><br>
      Perseguir com atraso → <a href="#util-chase">chase</a><br>
      Folga de câmera → <a href="#util-deadzone">deadzone</a><br>
      Sim/não → <a href="#util-chance">chance</a>
    </p>""",
    "atalhos": """    <p class="which">
      HUD / overlay / pausa → <a href="#atalhos-teclado">Atalhos</a>
    </p>""",
}


def sub1(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        print(f"  skip ({label}): padrão não encontrado")
        return text
    return text.replace(old, new, 1)


def sub_all(text: str, old: str, new: str) -> str:
    return text.replace(old, new)


def convert_gotcha(match: re.Match) -> str:
    inner = match.group(1).strip()
    # already converted
    if 'class="confuse"' in inner:
        return match.group(0)
    parece, eh, nao = "—", inner, "—"
    m = re.search(r"^(.*?)\s+[—–-]\s+(.*)$", inner)
    if m and 12 < len(m.group(1)) < 180:
        parece, eh = m.group(1).strip(), m.group(2).strip()
    m2 = re.search(r"não é\s+(.+?)(?:\.|$)", inner, re.I)
    if m2:
        nao = m2.group(1).strip().rstrip(".")
    return (
        f'<div class="tbl-wrap confuse-wrap">\n'
        f'<table class="confuse">\n'
        f'<thead><tr><th>Parece</th><th>É</th><th>Não é</th></tr></thead>\n'
        f'<tbody>\n'
        f'<tr><td>{parece}</td><td>{eh}</td><td>{nao}</td></tr>\n'
        f'</tbody>\n'
        f'</table>\n'
        f'</div>'
    )


def fix_details(text: str) -> str:
    """Signature details open; aprofundamento closed."""
    open_if = (
        "Construtor", "Assinatura", "Parâmetros", "Neste ", "Modelos de construção",
        "Neste play_sound", "Neste State", "Neste Color", "Neste Gradient",
        "Neste Texture", "Neste drawable", "Neste Shape", "Neste st",
        "Neste Grid", "Neste Box",
    )
    pattern = re.compile(
        r"<details class=\"spec\"( open)?(\s+id=\"[^\"]+\")?>\s*<summary>(.*?)</summary>",
        re.S,
    )

    def repl(m: re.Match) -> str:
        ident = m.group(2) or ""
        summary = m.group(3)
        plain = re.sub(r"<[^>]+>", "", summary)
        should_open = any(plain.startswith(s) or s in plain for s in open_if)
        # suite is aprofundamento
        if ident.strip() == 'id="suite"' or plain.startswith("time=") or "yoyo=" in plain[:40]:
            should_open = False
        if "Nomes de cor" in plain or "Presets" in plain or plain == "Regras" or plain == "Contrato":
            should_open = False
        open_attr = " open" if should_open else ""
        return f'<details class="spec"{open_attr}{ident}>\n      <summary>{summary}</summary>'

    return pattern.sub(repl, text)


def inject_jump(text: str) -> str:
    for chapter, block in JUMP.items():
        marker = f'<article class="chapter" id="{chapter}"'
        if chapter == "comecar":
            marker = '<article class="chapter active" id="comecar"'
        if marker not in text:
            print(f"  skip jump {chapter}: article not found")
            continue
        if f'data-chapter="{chapter}"' in text and block.strip()[:40] in text:
            continue
        # insert after first lede paragraph of the chapter head
        pat = re.compile(
            rf'(<article class="chapter(?: active)?" id="{chapter}"[^>]*>.*?'
            rf'<p class="lede">.*?</p>)',
            re.S,
        )
        m = pat.search(text)
        if not m:
            print(f"  skip jump {chapter}: lede not found")
            continue
        insert_at = m.end()
        text = text[:insert_at] + "\n" + block + text[insert_at:]
    return text


def language_sweep(text: str) -> str:
    repls = [
        ("Direita: Container ou callable.",
         "Direita: algo reativo do Scena ou um callable."),
        ("Cópia se for tupla; ligação se for callable / Container.",
         "Cópia se for tupla; ligação se for callable / algo reativo do Scena."),
        ("<code>clock</code> é Container. Nomeie-o num <code>lambda</code>",
         "<code>clock</code> é reativo. Nomeie-o num <code>lambda</code>"),
        ("<code>keyp</code> é Container.",
         "<code>keyp</code> é reativo."),
        ("<code>mouse</code> é Container (como <code>clock</code> / <code>keyp</code>).",
         "<code>mouse</code> é reativo (como <code>clock</code> / <code>keyp</code>)."),
        ("(fonte Container)",
         "(fonte reativa do Scena)"),
        ("Aceita um Container (atributo reativo: <code>st.wave</code>, <code>st.pos</code>) ou um <code>lambda</code>.",
         "Aceita algo reativo do Scena (<code>st.wave</code>, <code>st.pos</code>) ou um <code>lambda</code>."),
        ("Container (Attribute) ou <code>lambda</code>.",
         "Algo reativo do Scena (Attribute) ou <code>lambda</code>."),
        ("parte Defining ligada",
         "parte ligada"),
        ("Parte Defining ligada",
         "Parte ligada"),
        ("uma parte Defining ligada",
         "uma parte ligada"),
        ("(internado)",
         "(congelado no PCM)"),
        ("só settle na rotação, até haver varredura de rotate",
         "só acomodação na rotação, até haver varredura de rotate"),
        ("não varre / settle / floor snap",
         "não varre / acomoda / floor snap"),
        ("Sim (sweep / settle)",
         "Sim (varredura / acomodação)"),
    ]
    for a, b in repls:
        text = text.replace(a, b)
    return text


def suite_ids(text: str) -> str:
    old = """      <details class="spec">
        <summary>time= · ease= · loops= · yoyo= · face= · then= · on_done= · about= · force=</summary>"""
    new = """      <details class="spec" id="suite">
        <summary>time= · ease= · loops= · yoyo= · face= · then= · on_done= · about= · force=</summary>"""
    text = sub1(text, old, new, "suite details id")
    row_ids = [
        ("<tr><td><code>time=</code></td>", '<tr id="suite-time"><td><code>time=</code></td>'),
        ("<tr><td><code>ease=</code></td>", '<tr id="suite-ease"><td><code>ease=</code></td>'),
        ("<tr><td><code>loops=</code></td>", '<tr id="suite-loops"><td><code>loops=</code></td>'),
        ("<tr><td><code>yoyo=</code></td>", '<tr id="suite-yoyo"><td><code>yoyo=</code></td>'),
        ("<tr><td><code>face=</code></td>", '<tr id="suite-face"><td><code>face=</code></td>'),
        ("<tr><td><code>then=</code></td>", '<tr id="suite-then"><td><code>then=</code></td>'),
        ("<tr><td><code>on_done=</code></td>", '<tr id="suite-on-done"><td><code>on_done=</code></td>'),
        ("<tr><td><code>about=</code></td>", '<tr id="suite-about"><td><code>about=</code></td>'),
        ("<tr><td><code>force=</code></td>", '<tr id="suite-force"><td><code>force=</code></td>'),
    ]
    # Only the suite table should get ids — first occurrence after id="suite"
    idx = text.find('id="suite"')
    if idx < 0:
        return text
    head, tail = text[:idx], text[idx:]
    # limit to this details block
    end = tail.find("</details>")
    block, rest = tail[:end], tail[end:]
    for a, b in row_ids:
        block = block.replace(a, b, 1)
    return head + block + rest


SUITE_ROW = {
    "time=": (
        '<tr><td><a href="#suite-time"><code>time=</code></a></td>'
        '<td class="type"><span class="t">número ou None</span><span class="ex">None</span></td>'
        '<td class="suite-local"><em>Aqui:</em> segundos. Sem: na hora. Com: interpola. '
        'Regra completa: <a href="#suite-time">suite</a>.</td></tr>'
    ),
    "ease=": (
        '<tr><td><a href="#suite-ease"><code>ease=</code></a></td>'
        '<td class="type"><span class="t">str ou função</span><span class="ex">"linear"</span></td>'
        '<td class="suite-local"><em>Aqui:</em> curva do tween. '
        '<a href="#suite-ease">suite</a>.</td></tr>'
    ),
    "loops=": (
        '<tr><td><a href="#suite-loops"><code>loops=</code></a></td>'
        '<td class="type"><span class="t">1, N ou "forever"</span><span class="ex">1</span></td>'
        '<td class="suite-local"><em>Aqui:</em> voltas. <code>"forever"</code> nunca dispara '
        '<code>then=</code> / <code>on_done=</code>. Exige <code>time=</code>. '
        '<a href="#suite-loops">suite</a>.</td></tr>'
    ),
    "yoyo=": (
        '<tr><td><a href="#suite-yoyo"><code>yoyo=</code></a></td>'
        '<td class="type"><span class="t">bool</span><span class="ex">False</span></td>'
        '<td class="suite-local"><em>Aqui:</em> voltas ímpares invertem a direção. '
        'Precisa <code>loops</code> &gt; 1 ou <code>"forever"</code>. '
        '<a href="#suite-yoyo">suite</a>.</td></tr>'
    ),
    "then=": (
        '<tr><td><a href="#suite-then"><code>then=</code></a></td>'
        '<td class="type"><span class="t">função do capítulo</span></td>'
        '<td class="suite-local"><em>Aqui:</em> mode a entrar no fim. '
        '<a href="#suite-then">suite</a>.</td></tr>'
    ),
    "on_done=": (
        '<tr><td><a href="#suite-on-done"><code>on_done=</code></a></td>'
        '<td class="type"><span class="t">função ou None</span></td>'
        '<td class="suite-local"><em>Aqui:</em> callback no fim. '
        '<a href="#suite-on-done">suite</a>.</td></tr>'
    ),
    "force=": (
        '<tr><td><a href="#suite-force"><code>force=</code></a></td>'
        '<td class="type"><span class="t">bool</span><span class="ex">False</span></td>'
        '<td class="suite-local"><em>Aqui:</em> parte ligada: <code>False</code> levanta '
        '<code>LinkedAttributeError</code>; <code>True</code> avisa e <code>unlink</code>. '
        '<a href="#suite-force">suite</a>.</td></tr>'
    ),
}


def replace_suite_rows_in_pose(text: str) -> str:
    """In pose / tween tables, replace duplicated suite rows with links.
    Skip the canonical #suite table itself."""
    # Match a table row whose first cell is code>PARAM
    def repl_row(param: str, row_html: str, blob: str) -> str:
        pat = re.compile(
            rf"<tr><td><code>{re.escape(param)}</code></td>.*?</tr>",
            re.S,
        )

        def sub(m: re.Match) -> str:
            # don't touch suite table rows (already have id= or are inside #suite)
            return row_html

        parts = []
        last = 0
        suite_from = blob.find('id="suite"')
        suite_to = blob.find("</details>", suite_from) if suite_from >= 0 else -1
        for m in pat.finditer(blob):
            if suite_from <= m.start() < suite_to:
                continue
            # skip move_along yoyo local (mentions span) — still replace, local note covers it
            if "Ver abaixo" in m.group(0) or param in (
                "time=", "ease=", "loops=", "yoyo=", "then=", "on_done=", "force="
            ):
                parts.append(blob[last:m.start()])
                parts.append(row_html)
                last = m.end()
        parts.append(blob[last:])
        return "".join(parts) if parts else blob

    # Do it more carefully: only tables that currently have "Ver abaixo" in suite rows
    pat = re.compile(
        r"<tr><td><code>(time=|ease=|loops=|yoyo=|then=|on_done=|force=)</code></td>.*?</tr>",
        re.S,
    )
    suite_from = text.find('id="suite"')
    suite_to = text.find("</details>", suite_from) if suite_from >= 0 else -1

    def sub(m: re.Match) -> str:
        if suite_from <= m.start() < suite_to:
            return m.group(0)
        key = m.group(1)
        return SUITE_ROW.get(key, m.group(0))

    return pat.sub(sub, text)


SEARCH_JS = r'''
  function activateContainingTab(el) {
    if (!el) return;
    let node = el;
    while (node && node !== document.body) {
      if (node.tagName === "DETAILS") node.open = true;
      node = node.parentElement;
    }
    let panel = el.classList.contains("tab-panel") ? el : el.closest(".tab-panel");
    while (panel) {
      const root = panel.parentElement;
      if (!root || !root.hasAttribute("data-tabs")) break;
      const id = panel.dataset.panel;
      root.querySelectorAll(":scope > .tab-bar > .tab").forEach((t) => {
        t.classList.toggle("active", t.dataset.tab === id);
      });
      root.querySelectorAll(":scope > .tab-panel").forEach((p) => {
        p.classList.toggle("active", p === panel);
      });
      panel = root.parentElement ? root.parentElement.closest(".tab-panel") : null;
    }
  }

  const chapters = document.querySelectorAll(".chapter");
  const navLinks = document.querySelectorAll(".sidebar a[data-chapter]");
  const groupFilter = {};

  document.querySelectorAll("[data-filter-group]").forEach((row) => {
    const g = row.dataset.filterGroup;
    groupFilter[g] = "all";
    row.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        groupFilter[g] = chip.dataset.filter;
        row.querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c === chip));
        applyFilters();
      });
    });
  });

  const GRID_GROUP = {
    "visual-grid": "visual",
    "stamps-grid": "stamps",
    "transients-grid": "transients",
    "spatial-grid": "spatial",
    "post-grid": "post",
    "backgrounds-grid": "backgrounds",
    "filters-grid": "filters",
  };

  function chapterOf(el) {
    if (!el) return "comecar";
    const wrap = el.closest("article.chapter");
    return wrap && wrap.dataset.chapter ? wrap.dataset.chapter : "comecar";
  }

  function showChapter(name, scrollId) {
    chapters.forEach((c) => c.classList.toggle("active", c.dataset.chapter === name));
    const hash = "#" + (scrollId || name);
    navLinks.forEach((a) => {
      const href = a.getAttribute("href");
      a.classList.toggle("active", href === hash);
      a.classList.toggle("in-chapter", a.classList.contains("nav-top") && a.dataset.chapter === name);
    });
    const target = scrollId && document.getElementById(scrollId);
    if (target && chapterOf(target) === name && target.id !== name) {
      activateContainingTab(target);
      const scroll = () => target.scrollIntoView({ block: "start" });
      requestAnimationFrame(() => requestAnimationFrame(scroll));
    } else if (document.body.classList.contains("single-page") && target) {
      activateContainingTab(target);
      requestAnimationFrame(() => requestAnimationFrame(() => target.scrollIntoView({ block: "start" })));
    } else {
      window.scrollTo(0, 0);
    }
  }

  function applyHash() {
    let raw = (location.hash || "#comecar").slice(1);
    if (raw === "mundo-spatial") raw = "desenhar-spatial";
    if (raw === "aparencia-looks") raw = "aparencia-visual";
    if (raw === "desenhar-pose") raw = "mover-pose";
    if (raw === "mover-timers") raw = "agendar-timers";
    if (raw === "mover-mode") raw = "mode";
    if (raw === "mover-clock") raw = "frame-clock";
    if (raw === "clock-ready") raw = "agendar-ready";
    if (raw === "reagir-callbacks-script") raw = "reagir-callbacks";
    if (raw === "cb-ator") raw = "reagir-callbacks-entity";
    if (raw === "reagir-input") raw = "frame-teclado";
    if (raw === "reagir-mouse") raw = "frame-mouse";
    if (raw === "reagir-collide") raw = "colisao-collide";
    if (raw === "comecar-reativo") raw = "reativo";
    if (raw === "comecar-atalhos") raw = "atalhos";
    if (raw === "shape-track") raw = "desenhar-track";
    if (raw === "globais-mapa") raw = "globais";
    const el = document.getElementById(raw);
    const name = el ? chapterOf(el) : "comecar";
    const inner = el && el.id !== name ? el.id : null;
    showChapter(name, inner);
  }

  function fold(s) {
    return String(s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  const SYMBOLS = window.ScenaGuideSymbols || [];

  function scoreSymbol(sym, qFold) {
    if (!qFold) return { group: 4, score: 0 };
    const name = fold(sym.name);
    const line = fold(sym.oneLiner || "");
    const extra = fold(sym.search || "");
    const blob = name + " " + line + " " + extra;
    if (name === qFold) return { group: 0, score: 0 };
    if (name.startsWith(qFold)) return { group: 1, score: name.length };
    if (name.includes(qFold)) return { group: 2, score: name.indexOf(qFold) };
    if (blob.includes(qFold)) return { group: 3, score: blob.indexOf(qFold) };
    const tokens = qFold.split(/\s+/).filter(Boolean);
    if (tokens.length > 1 && tokens.every((t) => blob.includes(t))) {
      return { group: 3, score: 50 };
    }
    return null;
  }

  function levenshtein(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    const v0 = new Array(b.length + 1);
    const v1 = new Array(b.length + 1);
    for (let i = 0; i <= b.length; i++) v0[i] = i;
    for (let i = 0; i < a.length; i++) {
      v1[0] = i + 1;
      for (let j = 0; j < b.length; j++) {
        const cost = a[i] === b[j] ? 0 : 1;
        v1[j + 1] = Math.min(v1[j] + 1, v0[j + 1] + 1, v0[j] + cost);
      }
      for (let j = 0; j <= b.length; j++) v0[j] = v1[j];
    }
    return v0[b.length];
  }

  function nearbySymbols(qFold, n) {
    return SYMBOLS
      .map((s) => ({ s, d: levenshtein(fold(s.name), qFold) }))
      .filter((x) => x.d > 0 && x.d <= Math.max(2, Math.floor(qFold.length / 3)))
      .sort((a, b) => a.d - b.d || a.s.name.localeCompare(b.s.name))
      .slice(0, n)
      .map((x) => x.s);
  }

  function renderHit(sym) {
    const a = document.createElement("a");
    a.className = "search-hit";
    a.href = "#" + sym.anchor;
    a.innerHTML =
      '<div><span class="sym">' + sym.name.replace(/</g, "&lt;") +
      '</span><span class="kind">' + (sym.kind || "") + "</span></div>" +
      '<div class="path">' + (sym.chapterTitle || "") + " › " + (sym.sectionTitle || "") + "</div>" +
      (sym.oneLiner ? '<div class="blurb">' + String(sym.oneLiner).replace(/</g, "&lt;") + "</div>" : "");
    return a;
  }

  const searchPanel = document.getElementById("search-panel");
  let hits = [];
  let hitIndex = 0;

  function paintHits(list, emptyQuery) {
    searchPanel.innerHTML = "";
    hits = list;
    hitIndex = 0;
    if (!list.length) {
      const qv = (document.getElementById("q").value || "").trim();
      const msg = document.createElement("div");
      msg.className = "search-empty";
      msg.textContent = qv
        ? 'Nenhum símbolo com esse nome.'
        : "Nenhum símbolo.";
      searchPanel.appendChild(msg);
      if (qv) {
        nearbySymbols(fold(qv), 5).forEach((s) => searchPanel.appendChild(renderHit(s)));
      }
      return;
    }
    if (emptyQuery) {
      let last = "";
      list.forEach((sym) => {
        const g = sym.chapterTitle || sym.chapter || "";
        if (g !== last) {
          const h = document.createElement("div");
          h.className = "search-group";
          h.textContent = g;
          searchPanel.appendChild(h);
          last = g;
        }
        searchPanel.appendChild(renderHit(sym));
      });
    } else {
      list.forEach((sym) => searchPanel.appendChild(renderHit(sym)));
    }
    const first = searchPanel.querySelector(".search-hit");
    if (first) first.classList.add("active");
  }

  function runSymbolSearch(qRaw, forceAll) {
    const qFold = fold((qRaw || "").trim());
    searchPanel.hidden = false;
    searchPanel.classList.add("open");
    if (!qFold || forceAll && !qFold) {
      const grouped = SYMBOLS.slice().sort((a, b) => {
        const ca = (a.chapterTitle || "").localeCompare(b.chapterTitle || "");
        if (ca) return ca;
        return a.name.localeCompare(b.name);
      });
      paintHits(grouped, true);
      return;
    }
    const ranked = [];
    SYMBOLS.forEach((sym) => {
      const sc = scoreSymbol(sym, qFold);
      if (sc) ranked.push({ sym, ...sc });
    });
    ranked.sort((a, b) => a.group - b.group || a.score - b.score || a.sym.name.localeCompare(b.sym.name));
    paintHits(ranked.map((r) => r.sym), false);
  }

  function closeSearch() {
    searchPanel.classList.remove("open");
    searchPanel.hidden = true;
  }

  function applyFilters() {
    const qFold = fold((document.getElementById("q").value || "").trim());
    document.querySelectorAll(".catalog-host").forEach((host) => {
      const g = GRID_GROUP[host.id];
      const kf = groupFilter[g] || "all";
      const root = host.querySelector(":scope > .tabs");
      if (!root) return;
      const tabs = [...root.querySelectorAll(":scope > .tab-bar > .tab")];
      const panels = [...root.querySelectorAll(":scope > .tab-panel")];
      let firstVisible = null;
      tabs.forEach((tab, i) => {
        const kind = tab.dataset.kind;
        let vis = kf === "all" || kind === kf;
        if (qFold) {
          const panel = panels[i];
          const blob = fold(
            (tab.dataset.search || "") + " " + tab.textContent + " " +
            (panel ? panel.textContent : "")
          );
          vis = vis && blob.includes(qFold);
        }
        tab.classList.toggle("hidden", !vis);
        if (panels[i]) panels[i].classList.toggle("hidden", !vis);
        if (vis && !firstVisible) firstVisible = tab;
      });
      const active = tabs.find((t) => t.classList.contains("active"));
      if (firstVisible && active && active.classList.contains("hidden")) {
        firstVisible.click();
      }
    });
  }

  const q = document.getElementById("q");
  q.addEventListener("input", () => {
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
  });
  q.addEventListener("keydown", (e) => {
    const visibleHits = [...searchPanel.querySelectorAll(".search-hit")];
    if (e.key === "ArrowDown" && visibleHits.length) {
      e.preventDefault();
      hitIndex = Math.min(hitIndex + 1, visibleHits.length - 1);
      visibleHits.forEach((h, i) => h.classList.toggle("active", i === hitIndex));
      visibleHits[hitIndex].scrollIntoView({ block: "nearest" });
      return;
    }
    if (e.key === "ArrowUp" && visibleHits.length) {
      e.preventDefault();
      hitIndex = Math.max(hitIndex - 1, 0);
      visibleHits.forEach((h, i) => h.classList.toggle("active", i === hitIndex));
      visibleHits[hitIndex].scrollIntoView({ block: "nearest" });
      return;
    }
    if (e.key === "Escape") {
      closeSearch();
      q.blur();
      return;
    }
    if (e.key !== "Enter") return;
    e.preventDefault();
    const chosen = visibleHits[hitIndex] || visibleHits[0];
    if (chosen) {
      closeSearch();
      location.hash = chosen.getAttribute("href");
    }
  });

  document.getElementById("allNames").addEventListener("click", () => {
    q.value = "";
    q.focus();
    runSymbolSearch("", true);
  });

  document.getElementById("pageMode").addEventListener("click", () => {
    document.body.classList.toggle("single-page");
    const on = document.body.classList.contains("single-page");
    document.getElementById("pageMode").textContent = on ? "Um capítulo" : "Página única";
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".side-search") && !e.target.closest("#allNames")) closeSearch();
  });
'''


def replace_search_js(text: str) -> str:
    start = text.find("  function activateContainingTab(el) {")
    end = text.find("  const q = document.getElementById(\"q\");")
    if start < 0 or end < 0:
        print("  skip search js: markers not found")
        return text
    # keep from const q onward but we inlined q handling in SEARCH_JS
    # Find the original q handler end — replace through applyFilters and old q handlers
    # until document.addEventListener("keydown" for "/"
    slash = text.find('  document.addEventListener("keydown", (e) => {\n    if (e.key === "/"')
    if slash < 0:
        print("  skip search js: slash handler not found")
        return text
    return text[:start] + SEARCH_JS + "\n" + text[slash:]


def promote_fontes(text: str) -> str:
    """Turn reativo-fontes details into a real section with h2."""
    old = '''    <details class="spec" open id="reativo-fontes">
      <summary>O que pode ser ligado</summary>
      <p class="one-liner">Esquerda: campo que recebe a fórmula. Direita: algo do Scena que muda — senão a ligação não vive.</p>'''
    new = '''  </section>

  <section class="section prose" id="reativo-fontes">
    <h2>O que pode ser ligado</h2>
      <p class="one-liner">Esquerda: campo que recebe a fórmula. Direita: algo do Scena que muda — senão a ligação não vive.</p>'''
    if old not in text:
        print("  skip promote fontes")
        return text
    text = text.replace(old, new, 1)
    # close the details that used to wrap fontes: the next </details> after the section
    # originally: ... gotcha ... </details> then another gotcha then </section>
    # After promotion, drop the leftover </details> that closed the fontes details.
    marker = 'ver <a href="#reativo-fontes">O que pode ser ligado</a>. Pintura'
    # The inner gotcha still inside... let's find the closing details after fontes content
    idx = text.find('id="reativo-fontes"')
    # After replacement, id is on section. Find the first </details> after reativo-fontes section start
    # that was the details closer.
    start = text.find('<section class="section prose" id="reativo-fontes">')
    if start < 0:
        return text
    closer = text.find("</details>", start)
    nxt_section = text.find('<section class="section prose" id="reativo-lambda">', start)
    if 0 < closer < nxt_section:
        text = text[:closer] + text[closer + len("</details>"):]
    return text


def main() -> None:
    text = HTML.read_text(encoding="utf-8")
    orig_len = len(text)

    if "/* guia-search-v2 */" not in text and ".search-panel" not in text:
        text = text.replace("  .gotcha {", CSS_ADD + "\n  .gotcha {", 1)

    text = sub1(
        text,
        """  <div class="side-search">
    <input type="search" id="q" placeholder="Buscar" autocomplete="off" aria-label="Buscar">
    <kbd class="hint">/</kbd>
  </div>
""",
        SEARCH_HTML,
        "search html",
    )

    text = sub1(
        text,
        '<a href="#globais" class="nav-child" data-chapter="comecar">Globais</a>',
        '<a href="#globais" class="nav-child" data-chapter="comecar" data-search="st canvas clock keyp mouse audio ui group collision singleton">Objetos globais únicos</a>',
        "nav globais",
    )
    text = sub1(
        text,
        '<a href="#desenhar-shapes" class="nav-child" data-chapter="desenhar" data-search="shapes circle rect polygon point is_collapsed blend">Shapes</a>\n',
        SHAPES_NAV,
        "shapes nav",
    )

    # wip + temporal note
    text = sub_all(text, '    <p class="note">A API ainda muda. Fragmentos assumem <code>from scena import *</code>, <code>init</code> e <code>run</code>.</p>\n    <span class="wip">API ainda muda</span>\n',
                   '    <p class="note">Fragmentos assumem <code>from scena import *</code>, <code>init</code> e <code>run</code>.</p>\n')
    text = sub_all(text, "Linha 0 é o topo visual (y para cima). <code>g[col, row]</code> ainda não existe.",
                   "Linha 0 é o topo visual (y para cima). <code>g[col, row]</code> levanta <code>TypeError</code>. Use <code>.cell(col, row)</code>.")
    text = sub_all(text, "Não há gravação → <code>Sound</code> a partir do mic nesta versão.",
                   "Não há gravação a partir do mic — o caminho é <code>play_sound(mic)</code> ao vivo.")
    text = sub_all(text, " (após o rewrite de tile+clamp)", "")
    text = sub_all(text, " (comportamento de hoje)", "")
    text = sub_all(text, " — isto não é resolução de colisão; a porta fica aberta para modos futuros sem matriz de validação.",
                   " — isto não é resolução de colisão.")

    # repo paths
    text = sub_all(
        text,
        " Folga + atraso: <a href=\"#util-deadzone\"><code>deadzone</code></a> + <a href=\"#util-chase\"><code>chase</code></a> (receita em <code>examples/app_platformer_v2.py</code>).",
        " Folga + atraso: <a href=\"#util-deadzone\"><code>deadzone</code></a> + <a href=\"#util-chase\"><code>chase</code></a>.",
    )
    text = sub_all(
        text,
        " Receita de câmera: <a href=\"#mundo-camera\">Câmera</a> e <code>examples/app_platformer_v2.py</code>.",
        " Receita de câmera: <a href=\"#mundo-camera\">Câmera</a>.",
    )
    text = sub_all(
        text,
        " Smoke visual: <code>scripts/smoke/confine.py</code>.",
        "",
    )

    # Fills tab
    text = sub_all(text, '\n        <button class="tab" type="button" data-tab="mat-fill">Fills</button>', "")
    fills_panel = re.compile(
        r'\n      <div class="tab-panel" data-panel="mat-fill">.*?</div>\n    </div>',
        re.S,
    )
    text, n = fills_panel.subn('\n    </div>', text, count=1)
    if not n:
        print("  skip fills panel")

    # Globais section replace
    m = re.search(r'  <section class="section prose" id="globais">.*?</section>\n', text, re.S)
    if m:
        text = text[:m.start()] + GLOBAIS_SECTION + text[m.end():]
    else:
        print("  skip globais section")

    # callbacks in Começar
    m = re.search(r'  <section class="section prose" id="comecar-callbacks">.*?</section>\n', text, re.S)
    if m:
        text = text[:m.start()] + COMECAR_CALLBACKS + text[m.end():]
    else:
        print("  skip comecar-callbacks")

    # yoyo unify (before suite row rewrite)
    text = sub_all(text, YOYO_SHORT, YOYO_CANON)
    text = sub_all(
        text,
        "<code>yoyo=True</code> precisa <code>loops</code> &gt; 1.",
        "<code>yoyo=True</code> precisa <code>loops</code> &gt; 1 (ou <code>\"forever\"</code>); com <code>loops=1</code> levanta erro.",
    )

    text = suite_ids(text)
    text = replace_suite_rows_in_pose(text)

    # Box.rotate
    text = sub1(
        text,
        '<tr><td><code>rotate_to</code> / <code>rotate_by</code></td><td class="sig"><span class="params">Parâmetros: valor (número)</span><span class="ret">Retorna Box</span></td><td>Gira a região. Grade em cima herda o ângulo.</td></tr>',
        '<tr><td><code>rotate_to</code> / <code>rotate_by</code></td><td class="sig"><span class="params">valor (número); about= (ponto, opcional); force=False</span><span class="ret">Retorna o mesmo Box (muta)</span></td><td>Gira a região <strong>no lugar</strong> e devolve <code>self</code> — não é cópia (diferente de <code>inset</code> / <code>outset</code>). Sem <code>time=</code>: este não é o <a href="#pose-rotate-to"><code>rotate_to</code> de Mover</a> (lá: drawable, suíte, Handle). <code>about=</code> pivô (padrão: centro). Grade em cima herda o ângulo.</td></tr>',
        "box rotate",
    )

    # group.box out of constructors
    text = sub1(
        text,
        '''            <tr><td><code>Box(graphic)</code></td><td>Mesmo snapshot que <code>graphic.box</code></td></tr>
            <tr><td><code>group["wasp"].box</code></td><td>AABB dos membros como Box fresco, ou <code>None</code> se vazio. Ângulo 0.</td></tr>''',
        '''            <tr><td><code>Box(graphic)</code></td><td>Mesmo snapshot que <code>graphic.box</code></td></tr>''',
        "group.box ctor",
    )
    if 'group["wasp"].box' not in text:
        box_sec = text.find('id="colocar-box"')
        needle = '          <p class="name-group">Leitura</p>'
        pos = text.find(needle, box_sec) if box_sec >= 0 else -1
        if pos >= 0:
            insert = '''          <p class="name-group">Medição de grupo</p>
        <table>
          <thead>
            <tr><th>Método</th><th>Assinatura</th><th>Retorna</th><th>Significado</th></tr>
          </thead>
          <tbody>
            <tr><td><code>group["wasp"].box</code></td><td class="sig"><span class="params">sem argumentos</span><span class="ret">Box ou None</span></td><td>AABB dos membros como Box fresco, ou <code>None</code> se vazio. Ângulo 0. Não é construtor de Box.</td></tr>
          </tbody>
        </table>
'''
            text = text[:pos] + insert + text[pos:]
        else:
            print("  skip group.box measure")

    # cell_at zero area
    text = sub1(
        text,
        '''            <tr><td><code>.cell_at(x, y)</code></td><td class="sig"><span class="params">ponto ou x, y</span><span class="ret">Box ou None</span></td><td>Inverso. Grade rotacionada: transforma para o local primeiro. Vão → <code>None</code>.</td></tr>''',
        '''            <tr><td><code>.cell_at(x, y)</code></td><td class="sig"><span class="params">ponto ou x, y</span><span class="ret">Box ou None</span></td><td>Inverso. Grade rotacionada: transforma para o local primeiro. Vão → <code>None</code>. Célula de área zero continua endereçável por <code>.cell(col, row)</code>, mas é invisível para <code>cell_at</code>.</td></tr>''',
        "cell_at zero",
    )

    # som-play
    text = sub1(
        text,
        "Parâmetros: src (path, Sound ou Microphone); volume, pan (−1…1), pitch, loops (int ou \"forever\"), fade_in, crossfade (com name=), on_done, then, name",
        "Parâmetros: src (path, Sound ou Microphone); volume, pan (−1…1), pitch, loops=1 (int ou \"forever\"), fade_in, crossfade (com name=), on_done, then, name",
        "loops default",
    )
    text = sub1(
        text,
        "Arquivo em falta / corrompido: silêncio + aviso no banner (uma vez por asset).",
        "Arquivo em falta / corrompido: silêncio de duração nominal + aviso no banner (uma vez por asset). O Handle continua a correr — <code>on_done</code> e <code>loops</code> ainda se comportam.",
        "missing asset duration",
    )
    text = sub1(
        text,
        '''            <tr><td><code>.spectrum(bins=8)</code></td><td class="type"><span class="t">lista</span><span class="ex">[0.1, 0.8, …]</span></td><td>Bandas log (~40 Hz…16 kHz), cada valor 0…1 linear. Mesmo τ. Em <code>after</code> / tween: <code>AttributeError</code> com a dica.</td></tr>''',
        '''            <tr><td><code>.spectrum(bins=8)</code></td><td class="type"><span class="t">lista</span><span class="ex">[0.1, 0.8, …]</span></td><td>Bandas log (~40 Hz…16 kHz), cada valor 0…1 linear. Mesmo τ. Atributo só-de-som: num Handle que não é de som levanta <code>AttributeError</code> com a dica — o mesmo para <code>.volume</code>, <code>.pan</code>, <code>.pitch</code>, <code>.fade_to</code>, <code>.fade_out</code>, <code>.level</code>, <code>.effects</code>.</td></tr>''',
        "sound-only attrs",
    )
    # split remaining into inherited
    text = sub1(
        text,
        '''            <tr><td><code>.remaining</code></td><td class="type"><span class="t">segundos</span><span class="ex">0.4</span></td><td>Tempo até o fim audível (clip + cauda de Echo/Reverb, se houver).</td></tr>''',
        '''          </tbody>
        </table>
          <p class="name-group">Do Handle genérico</p>
        <table>
          <thead>
            <tr><th>Propriedade</th><th>Tipo (valor típico)</th><th>Leitura/Escrita</th><th>Significado</th></tr>
          </thead>
          <tbody>
            <tr><td><code>.remaining</code></td><td class="type"><span class="t">número</span><span class="ex">0.4</span></td><td>leitura</td><td>Tempo até o fim audível (clip + cauda de Echo/Reverb, se houver). Mesmo contrato do <a href="#agendar-handle">Handle</a> — não é exclusivo de som.</td></tr>''',
        "remaining inherited",
    )

    # stamps chips
    if 'data-filter-group="stamps"' not in text:
        text = sub1(
            text,
            '    <div class="catalog-host" id="stamps-grid"></div>',
            STAMPS_CHIPS + '\n    <div class="catalog-host" id="stamps-grid"></div>',
            "stamps chips",
        )

    # h2 ligar / atalhos
    text = sub1(
        text,
        '''  <section class="section prose" id="reativo-liga">
    <p class="one-liner">''',
        '''  <section class="section prose" id="reativo-liga">
    <h2>Ligar</h2>
    <p class="one-liner">''',
        "h2 ligar",
    )
    text = sub1(
        text,
        '''  <section class="section prose" id="atalhos-teclado">
    <p class="one-liner">''',
        '''  <section class="section prose" id="atalhos-teclado">
    <h2>Teclado</h2>
    <p class="one-liner">''',
        "h2 atalhos",
    )

    if 'id="reativo-state"' not in text:
        text = sub1(
            text,
            '''    <details class="spec">
      <summary>Neste st</summary>''',
            STATE_BLOCK + '''
    <details class="spec">
      <summary>Neste st</summary>''',
            "state block",
        )

    text = promote_fontes(text)
    text = language_sweep(text)

    # Ver abaixo → suite (leftovers)
    text = sub_all(text, " Ver abaixo.", " <a href=\"#suite\">suite</a>.")
    text = sub_all(text, "Ver abaixo.", '<a href="#suite">suite</a>.')

    # 4-col param tables already have Passar: rename Tipo → Tipo (default)
    text = sub_all(
        text,
        "<tr><th>Parâmetro</th><th>Passar</th><th>Tipo</th><th>Significado</th></tr>",
        "<tr><th>Parâmetro</th><th>Passar</th><th>Tipo (default)</th><th>Significado</th></tr>",
    )

    # gotchas → confuse tables (skip if already converted)
    if "table class=\"confuse\"" not in text:
        text = re.sub(
            r'<p class="gotcha">(.*?)</p>',
            convert_gotcha,
            text,
            flags=re.S,
        )

    text = fix_details(text)
    text = inject_jump(text)

    # symbols script
    if "guia-api-symbols.js" not in text:
        text = sub1(
            text,
            '<script src="guia-api-catalogs.js"></script>',
            '<script src="guia-api-catalogs.js"></script>\n<script src="guia-api-symbols.js"></script>',
            "symbols script",
        )

    text = replace_search_js(text)
    text = text.replace("  buildSearchIndex();\n", "")

    # visible=False temporal
    text = sub_all(
        text,
        "<code>visible=False</code> ainda existe. <code>destroy()</code> não.",
        "<code>visible=False</code> esconde e o objeto continua. <code>destroy()</code> remove — a referência que você guarda deixa de ser um objeto vivo.",
    )

    HTML.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {HTML.name}: {orig_len} → {len(text)} chars")


if __name__ == "__main__":
    # Prints "→": piped on Windows, stdout is cp1252 with errors="strict" (WP28).
    sys.stdout.reconfigure(errors="backslashreplace")
    main()
