#!/usr/bin/env python3
"""Validate Guia catalogs + public surface, and emit the search index.

Source of truth for "what is public":
  - ``scena.__all__`` minus INTERNALS (leaked engine types).
  - Catalog items in guia-api-catalogs.js (author-facing looks / fx).

``symbols.json`` and ``guia-api-symbols.js`` are generated here, next to the
Guide page (``docs/pt/guide/``). Run from the repository root:
``python tools/guide/validate_guia.py``.

Checks:
  - catalog shape (families, parameter names, types) and anchors;
  - catalog parameters against the real Python signatures (a documented
    knob that does not exist, a wrong default, a wrong positional slot);
  - every ``<pre>`` example and catalog ``code:`` compiles.

``--examples`` also executes the examples statement by statement (see
``run_examples``); run it in a fresh process — it builds real actors.
``--gaps`` lists public constructor parameters the catalogs omit.
"""
from __future__ import annotations

import ast
import builtins
import html as _html
import inspect
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # tools/guide (this script)
REPO = ROOT.parent.parent
DOCS = REPO / "docs"
# The Guide the catalogs, the search index and these checks read. The English
# Guide (docs/en/guide/) will mirror it.
LANG = "pt"
GUIDE = DOCS / LANG / "guide"
CATALOGS = GUIDE / "guia-api-catalogs.js"
SYMBOLS_JSON = GUIDE / "symbols.json"
SYMBOLS_JS = GUIDE / "guia-api-symbols.js"
# Thumbnails are shared by every language (pictures have no words).
THUMBS_JS = DOCS / "assets" / "thumbs" / "guia-api-thumbs.js"
HTML = GUIDE / "index.html"

KNOWN_FAMILIES = {
    "visual", "spatial", "post", "impact", "field", "filter", "stamp",
    "life", "knock", "exit", "enter", "hit", "pulse", "pop", "spark", "cover",
}

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Exported names still waiting on a Guia card. Empty: exported ⇒ documented.
INTERNALS: set[str] = set()

FAMILY_CHAPTER = {
    "visual": ("aparencia", "aparencia-visual", "Aparência", "Visual"),
    "stamp": ("aparencia", "aparencia-selos", "Aparência", "Complementos"),
    "filter": ("aparencia", "aparencia-filtros", "Aparência", "Filtros"),
    "life": ("aparencia", "aparencia-transientes", "Aparência", "Transientes"),
    "knock": ("aparencia", "aparencia-transientes", "Aparência", "Transientes"),
    "hit": ("aparencia", "aparencia-transientes", "Aparência", "Transientes"),
    "pulse": ("aparencia", "aparencia-transientes", "Aparência", "Transientes"),
    "pop": ("aparencia", "aparencia-transientes", "Aparência", "Transientes"),
    "spark": ("aparencia", "aparencia-transientes", "Aparência", "Transientes"),
    "exit": ("aparencia", "aparencia-transientes", "Aparência", "Transientes"),
    "enter": ("aparencia", "aparencia-transientes", "Aparência", "Transientes"),
    "spatial": ("desenhar", "desenhar-spatial", "Desenhar", "SpatialFx"),
    "post": ("mundo", "mundo-post", "Mundo", "Post"),
    "impact": ("mundo", "mundo-impactos", "Mundo", "Impactos"),
    "field": ("mundo", "mundo-background", "Mundo", "Background"),
    "cover": ("mundo", "mundo-impactos", "Mundo", "Impactos"),
}

# Hand-authored public symbols the catalogs do not cover.
# State is public (STATE_EXPORTS). Attribute is public. The *Fill factories
# are public too (Guia: Cor / Gradient / Texture → Procedural).
CORE_SYMBOLS = [
    {"name": "st", "kind": "singleton", "chapter": "reativo", "section": "reativo-entity",
     "anchor": "globais", "oneLiner": "Saco global de estado do app."},
    {"name": "canvas", "kind": "singleton", "chapter": "mundo", "section": "mundo-camera",
     "anchor": "globais", "oneLiner": "A janela: câmera, post, background, views."},
    {"name": "clock", "kind": "singleton", "chapter": "frame", "section": "frame-clock",
     "anchor": "frame-clock", "oneLiner": "Tempo do mundo. Nomeie-o num lambda."},
    {"name": "keyp", "kind": "singleton", "chapter": "frame", "section": "frame-teclado",
     "anchor": "frame-teclado", "oneLiner": "Teclado: nível, não borda."},
    {"name": "mouse", "kind": "singleton", "chapter": "frame", "section": "frame-mouse",
     "anchor": "frame-mouse", "oneLiner": "Ponteiro. Nomeie mouse num lambda."},
    {"name": "audio", "kind": "singleton", "chapter": "som", "section": "som-audio",
     "anchor": "som-audio", "oneLiner": "Bus mestre: volume, mute, espectro."},
    {"name": "ui", "kind": "singleton", "chapter": "ui", "section": "ui-widgets",
     "anchor": "ui-widgets", "oneLiner": "Pilha de widgets, ui.gap e ui.stack_column."},
    {"name": "group", "kind": "singleton", "chapter": "mundo", "section": "mundo-grupos",
     "anchor": "mundo-grupos", "oneLiner": "Coleções vivas por tag."},
    {"name": "collision", "kind": "singleton", "chapter": "colisao", "section": "colisao-aux",
     "anchor": "colisao-aux", "oneLiner": "Consultas: ponto, círculo, setor, raio."},
    {"name": "ready", "kind": "singleton", "chapter": "agendar", "section": "agendar-ready",
     "anchor": "agendar-ready", "oneLiner": "Cooldown nomeado."},
    {"name": "recently", "kind": "function", "chapter": "agendar", "section": "agendar-recently",
     "anchor": "agendar-recently", "oneLiner": "Lembra um instante por uma janela."},
    {"name": "State", "kind": "class", "chapter": "reativo", "section": "reativo-entity",
     "anchor": "reativo-state", "oneLiner": "Saco nomeado de células Attribute, como o st."},
    {"name": "Attribute", "kind": "class", "chapter": "reativo", "section": "reativo-fontes",
     "anchor": "reativo-fontes", "oneLiner": "Célula reativa avulsa."},
    {"name": "init", "kind": "function", "chapter": "comecar", "section": "script-minimo",
     "anchor": "init", "oneLiner": "Espaço de design, window_scale e display. Sem janela OS."},
    {"name": "run", "kind": "function", "chapter": "comecar", "section": "script-minimo",
     "anchor": "script-minimo", "oneLiner": "Entra no loop. run(Titulo) começa pela classe Titulo(Act)."},
    {"name": "Circle", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "circle", "oneLiner": "Disco preenchido."},
    {"name": "Rect", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-rect", "oneLiner": "Retângulo. Rect desenha. Box só mede."},
    {"name": "Square", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-square", "oneLiner": "Quadrado. Lado único."},
    {"name": "Ellipse", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-ellipse", "oneLiner": "Elipse preenchida."},
    {"name": "Line", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-line", "oneLiner": "Segmento. Comprimento é length=."},
    {"name": "Polygon", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-polygon", "oneLiner": "Polígono livre. Vértices não mudam depois."},
    {"name": "RegularPolygon", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-regular", "oneLiner": "Polígono regular. n= não muda depois."},
    {"name": "Triangle", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-triangle", "oneLiner": "Triângulo isósceles; equilátero por padrão (base_ratio=1)."},
    {"name": "Point", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-point", "oneLiner": "Ponto. Point(pt) copia — não acompanha a fonte."},
    {"name": "Anchor", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "shape-point", "oneLiner": "Ponto livre, visível e arrastável."},
    {"name": "Shape", "kind": "class", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "desenhar-shapes", "oneLiner": "Corpo geométrico. Construtor já coloca."},
    {"name": "Sprite", "kind": "class", "chapter": "desenhar", "section": "desenhar-sprite",
     "anchor": "desenhar-sprite", "oneLiner": "Imagem / atlas. Arquivo ao lado ou em media/."},
    {"name": "Svg", "kind": "class", "chapter": "desenhar", "section": "sprite-extras",
     "anchor": "spr-svg", "oneLiner": "SVG como sprite."},
    {"name": "Sheet", "kind": "class", "chapter": "desenhar", "section": "desenhar-sprite",
     "anchor": "desenhar-sprite", "oneLiner": "Atlas de clips. Não se coloca sozinho."},
    {"name": "Hitbox", "kind": "class", "chapter": "desenhar", "section": "spr-hit",
     "anchor": "spr-hit-partes", "oneLiner": "Parte só de detecção. sprite.add_hitbox(group=…)."},
    {"name": "showing", "kind": "method", "chapter": "desenhar", "section": "spr-hit",
     "anchor": "spr-hit-ataque", "oneLiner": "O frame na tela é um destes? sprite.showing(frames)."},
    {"name": "Text", "kind": "class", "chapter": "desenhar", "section": "desenhar-text",
     "anchor": "desenhar-text", "oneLiner": "Texto no mundo. HUD: camada ui."},
    {"name": "Entity", "kind": "class", "chapter": "desenhar", "section": "desenhar-entity",
     "anchor": "desenhar-entity", "oneLiner": "Ator: tinta, mode, on_update. Sem desenho próprio."},
    {"name": "Track", "kind": "class", "chapter": "desenhar", "section": "desenhar-track",
     "anchor": "desenhar-track", "oneLiner": "Curva. move_along viaja; cursor coloca."},
    {"name": "History", "kind": "class", "chapter": "desenhar", "section": "desenhar-history",
     "anchor": "history", "oneLiner": "Sequência limitada de carimbos. Não desenha."},
    {"name": "Contrail", "kind": "class", "chapter": "desenhar", "section": "desenhar-history",
     "anchor": "contrail", "oneLiner": "History + polilinha com fade opcional."},
    {"name": "Box", "kind": "class", "chapter": "colocar", "section": "colocar-box",
     "anchor": "colocar-box", "oneLiner": "Só mede. Rect desenha."},
    {"name": "Grid", "kind": "class", "chapter": "colocar", "section": "colocar-grid",
     "anchor": "colocar-grid", "oneLiner": "Divisão de um Box. Use .cell(col, row)."},
    {"name": "Level", "kind": "class", "chapter": "colocar", "section": "colocar-fase",
     "anchor": "colocar-fase", "oneLiner": "Lê uma fase do editor. Não cria nada; make() cria."},
    {"name": "Endless", "kind": "class", "chapter": "mundo", "section": "mundo-sem-fim",
     "anchor": "mundo-sem-fim", "oneLiner": "Enche a tela de peças, vaga por vaga, sem fim."},
    {"name": "Color", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "aparencia-cor", "oneLiner": "Cor imutável, salvo .alpha."},
    {"name": "Gradient", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-grad", "oneLiner": "Rampa. Precisa ir em .fill / set_color / background."},
    {"name": "Palette", "kind": "class", "chapter": "aparencia", "section": "aparencia-paletas",
     "anchor": "aparencia-palette", "oneLiner": "Amostras discretas de uma rampa. Índice cíclico."},
    {"name": "Texture", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-tex", "oneLiner": "Imagem como material. Busca: Arquivos de imagem."},
    {"name": "Wallpaper", "kind": "class", "chapter": "mundo", "section": "mundo-background",
     "anchor": "mundo-background", "oneLiner": "Imagem de fundo. Mesma busca de Sprite."},
    {"name": "Vec2", "kind": "class", "chapter": "geometria", "section": "geo-vec2",
     "anchor": "geo-vec2", "oneLiner": "Vetor 2D."},
    {"name": "Handle", "kind": "class", "chapter": "agendar", "section": "agendar-handle",
     "anchor": "agendar-handle", "oneLiner": "Tween, timer, som, move_along."},
    {"name": "Sound", "kind": "class", "chapter": "som", "section": "som-play",
     "anchor": "som-play", "oneLiner": "Material de áudio. Não toca sozinho."},
    {"name": "Microphone", "kind": "class", "chapter": "som", "section": "som-mic",
     "anchor": "som-mic", "oneLiner": "Captura. Sem gravação para Sound."},
    {"name": "distance", "kind": "function", "chapter": "geometria", "section": "geo-helpers",
     "anchor": "geo-helpers", "oneLiner": "Distância entre dois pontos."},
    {"name": "heading", "kind": "function", "chapter": "geometria", "section": "geo-helpers",
     "anchor": "geo-helpers", "oneLiner": "Ângulo de a → b, em graus."},
    {"name": "middle_point", "kind": "function", "chapter": "geometria", "section": "geo-helpers",
     "anchor": "geo-helpers", "oneLiner": "Ponto médio."},
    {"name": "closest_point", "kind": "function", "chapter": "geometria", "section": "geo-helpers",
     "anchor": "geo-helpers", "oneLiner": "Ponto no corpo preenchido mais perto de p."},
    {"name": "vec_from_angle", "kind": "function", "chapter": "geometria", "section": "geo-vec2",
     "anchor": "geo-vec2", "oneLiner": "Vec2 a partir de graus."},
    {"name": "nearest", "kind": "function", "chapter": "geometria", "section": "geo-helpers",
     "anchor": "geo-helpers", "oneLiner": "Item mais perto da origem."},
    {"name": "resolve", "kind": "function", "chapter": "colisao", "section": "colisao-resolve",
     "anchor": "colisao-resolve", "oneLiner": "Parede / chão: varre o caminho."},
    {"name": "unresolve", "kind": "function", "chapter": "colisao", "section": "colisao-resolve",
     "anchor": "colisao-resolve", "oneLiner": "Tira o par do resolve."},
    {"name": "test_collision", "kind": "function", "chapter": "colisao", "section": "colisao-aux",
     "anchor": "colisao-aux", "oneLiner": "Consulta: colidem agora?"},
    {"name": "query_point", "kind": "method", "chapter": "colisao", "section": "colisao-aux",
     "anchor": "colisao-aux", "oneLiner": "Quem contém este ponto."},
    {"name": "raycast", "kind": "method", "chapter": "colisao", "section": "colisao-aux",
     "anchor": "colisao-aux", "oneLiner": "Raio até a primeira parede."},
    {"name": "set_defaults", "kind": "function", "chapter": "desenhar", "section": "desenhar-shapes",
     "anchor": "desenhar-shapes", "oneLiner": "Padrões de cor / traço do jogo."},
    {"name": "unregister_event", "kind": "function", "chapter": "reagir", "section": "reagir-when",
     "anchor": "reagir-when", "oneLiner": "Tira @when / @on_change da função."},
    {"name": "play_sound", "kind": "function", "chapter": "som", "section": "som-play",
     "anchor": "som-play", "oneLiner": "Toca path, Sound ou Microphone. Devolve Handle."},
    {"name": "move_to", "kind": "method", "chapter": "mover", "section": "mover-pose",
     "anchor": "pose-move-to", "oneLiner": "Lugar absoluto. x/y, Vec2 ou Point. Sem time= nem speed= coloca; com um deles viaja."},
    {"name": "move_by", "kind": "method", "chapter": "mover", "section": "mover-pose",
     "anchor": "pose-move-by", "oneLiner": "Delta: dx/dy, Vec2 ou angle=/distance=. Sempre viagem; time= ou speed=."},
    {"name": "pan_to", "kind": "method", "chapter": "mundo", "section": "mundo-camera",
     "anchor": "mundo-camera", "oneLiner": "Coloca o mundo no centro: x/y, (x,y), Vec2, Point ou Graphic."},
    {"name": "pan_by", "kind": "method", "chapter": "mundo", "section": "mundo-camera",
     "anchor": "mundo-camera", "oneLiner": "Desloca o conteúdo: dx/dy, (dx,dy) ou Vec2. Não Point."},
    {"name": "<<", "kind": "operator", "chapter": "reativo", "section": "reativo-liga",
     "anchor": "reativo-liga", "oneLiner": "Substitui o conteúdo no mesmo objeto. A << B copia por dentro; não liga."},
    {"name": "move_along", "kind": "method", "chapter": "mover", "section": "mover-move-along",
     "anchor": "mover-move-along", "oneLiner": "Viaja uma curva. time= é uma volta; ou speed= (unidades por segundo)."},
    {"name": "rotate_to", "kind": "method", "chapter": "mover", "section": "mover-pose",
     "anchor": "pose-rotate-to", "oneLiner": "Rumo absoluto; speed= em graus/s. Em Box: muta no lugar, sem time=."},
    {"name": "rotate_by", "kind": "method", "chapter": "mover", "section": "mover-pose",
     "anchor": "pose-rotate-by", "oneLiner": "Delta assinado; speed= em graus/s. Em Box: muta no lugar, sem time=."},
    {"name": "scale_to", "kind": "method", "chapter": "mover", "section": "mover-pose",
     "anchor": "pose-scale-to", "oneLiner": "Escala uniforme absoluta."},
    {"name": "scale_by", "kind": "method", "chapter": "mover", "section": "mover-pose",
     "anchor": "pose-scale-by", "oneLiner": "Multiplica a escala atual."},
    {"name": "tween", "kind": "function", "chapter": "mover", "section": "mover-tween",
     "anchor": "mover-tween", "oneLiner": "Interpola um Attribute / Point."},
    {"name": "after", "kind": "function", "chapter": "agendar", "section": "agendar-timers",
     "anchor": "agendar-timers", "oneLiner": "Uma vez, daqui a N segundos."},
    {"name": "every", "kind": "function", "chapter": "agendar", "section": "agendar-timers",
     "anchor": "agendar-timers", "oneLiner": "Repete a cada N segundos."},
    {"name": "flush", "kind": "function", "chapter": "reagir", "section": "reagir-when",
     "anchor": "reagir-when", "oneLiner": "Roda o pendente de @when / @on_change agora."},
    {"name": "Button", "kind": "class", "chapter": "ui", "section": "ui-button",
     "anchor": "ui-button", "oneLiner": "Botão. 1º argumento é bind."},
    {"name": "SpriteButton", "kind": "class", "chapter": "ui", "section": "ui-sprite-button",
     "anchor": "ui-sprite-button", "oneLiner": "Botão de jogo feito da sua arte (hover, aperto, desligado)."},
    {"name": "Slider", "kind": "class", "chapter": "ui", "section": "ui-slider",
     "anchor": "ui-slider", "oneLiner": "Controle deslizante ligado a um Attribute."},
    {"name": "CheckBox", "kind": "class", "chapter": "ui", "section": "ui-checkbox",
     "anchor": "ui-checkbox", "oneLiner": "Liga/desliga um Attribute bool."},
    {"name": "TextInput", "kind": "class", "chapter": "ui", "section": "ui-textinput",
     "anchor": "ui-textinput", "oneLiner": "Campo de texto. Focado come a tecla."},
    {"name": "DropDown", "kind": "class", "chapter": "ui", "section": "ui-dropdown",
     "anchor": "ui-dropdown", "oneLiner": "Lista de opções."},
    {"name": "Menu", "kind": "class", "chapter": "ui", "section": "ui-menu",
     "anchor": "ui-menu", "oneLiner": "Pergunta de jogo. Fecha ao escolher."},
    {"name": "Clock", "kind": "class", "chapter": "comecar", "section": "globais",
     "anchor": "globais", "oneLiner": "Tipo do singleton clock."},
    {"name": "Mouse", "kind": "class", "chapter": "frame", "section": "frame-mouse",
     "anchor": "frame-mouse", "oneLiner": "Tipo do singleton mouse."},
    {"name": "KeyPressed", "kind": "class", "chapter": "comecar", "section": "globais",
     "anchor": "globais", "oneLiner": "Tipo do singleton keyp."},
    {"name": "Collider", "kind": "class", "chapter": "colisao", "section": "colisao-corpo",
     "anchor": "colisao-collider", "oneLiner": "Vários shapes que colidem como um corpo só."},
    {"name": "CollisionInfo", "kind": "class", "chapter": "colisao", "section": "colisao-info",
     "anchor": "colisao-info", "oneLiner": "O que o contato te conta."},
    {"name": "SpatialFx", "kind": "class", "chapter": "desenhar", "section": "desenhar-spatial",
     "anchor": "desenhar-spatial", "oneLiner": "Efeito no espaço: Fire, Rain, Sparks…"},
    {"name": "chance", "kind": "function", "chapter": "util", "section": "util-chance",
     "anchor": "util-chance", "oneLiner": "Sim/não. 0 a 1."},
    {"name": "chase", "kind": "function", "chapter": "util", "section": "util-chase",
     "anchor": "util-chase", "oneLiner": "Persegue o alvo com atraso exponencial."},
    {"name": "approach", "kind": "function", "chapter": "util", "section": "util-approach",
     "anchor": "util-approach", "oneLiner": "Anda até o alvo a velocidade constante e chega exato."},
    {"name": "deadzone", "kind": "function", "chapter": "util", "section": "util-deadzone",
     "anchor": "util-deadzone", "oneLiner": "Folga: só empurra o alvo fora da caixa."},
    {"name": "lerp", "kind": "function", "chapter": "util", "section": "util-lerp",
     "anchor": "util-lerp", "oneLiner": "Mistura a → b em t."},
    {"name": "remap", "kind": "function", "chapter": "util", "section": "util-remap",
     "anchor": "util-remap", "oneLiner": "Leva um intervalo no outro."},
    {"name": "click", "kind": "function", "chapter": "reagir", "section": "reagir-pointer",
     "anchor": "reagir-pointer", "oneLiner": "Clique no drawable ou no Button."},
    {"name": "hover", "kind": "function", "chapter": "reagir", "section": "reagir-pointer",
     "anchor": "ptr-hover", "oneLiner": "O cursor entrou: virou o alvo de hover."},
    {"name": "hover_exit", "kind": "function", "chapter": "reagir", "section": "reagir-pointer",
     "anchor": "ptr-hover", "oneLiner": "Deixou de ser o alvo de hover."},
    {"name": "collide", "kind": "function", "chapter": "colisao", "section": "colisao-collide",
     "anchor": "colisao-collide", "oneLiner": "Decorator: overlap neste tick."},
    {"name": "above", "kind": "function", "chapter": "mundo", "section": "mundo-camadas",
     "anchor": "mundo-camadas", "oneLiner": "Camada acima de outra."},
    {"name": "below", "kind": "function", "chapter": "mundo", "section": "mundo-camadas",
     "anchor": "mundo-camadas", "oneLiner": "Camada abaixo de outra."},
    {"name": "amp_db", "kind": "function", "chapter": "som", "section": "som-audio",
     "anchor": "som-audio", "oneLiner": "Linear → altura de barra em dB."},
    {"name": "STATIC", "kind": "constant", "chapter": "colisao", "section": "colisao-resolve",
     "anchor": "colisao-resolve", "oneLiner": "Massa infinita: parede."},
    {"name": "ANYTHING", "kind": "constant", "chapter": "colisao", "section": "colisao-collide",
     "anchor": "colisao-collide", "oneLiner": "Casa com qualquer collider."},
    {"name": "show_tracks", "kind": "function", "chapter": "atalhos", "section": "debug-metodos",
     "anchor": "debug-metodos", "oneLiner": "Debug: overlay das trilhas ativas de move_along."},
    {"name": "collision.show_colliders", "kind": "method", "chapter": "atalhos", "section": "debug-metodos",
     "anchor": "debug-metodos", "oneLiner": "Debug: overlay dos hitboxes inscritos (verde detecção, dourado resolve)."},
    {"name": "when", "kind": "function", "chapter": "reagir", "section": "reagir-when",
     "anchor": "reagir-when", "oneLiner": "@when: borda no mundo."},
    {"name": "on_change", "kind": "function", "chapter": "reagir", "section": "reagir-on-change",
     "anchor": "reagir-on-change", "oneLiner": "@on_change: valor novo != anterior."},
    {"name": "leave_playfield", "kind": "function", "chapter": "reagir", "section": "reagir-bounds",
     "anchor": "reagir-bounds", "oneLiner": "@leave_playfield: o centro saiu."},
    {"name": "Act", "kind": "class", "chapter": "atos", "section": "atos-classe",
     "anchor": "atos-classe", "oneLiner": "Um ato do jogo (título, fase, fim): class Fase(Act). O que ele cria sai com ele."},
    {"name": "change_act", "kind": "function", "chapter": "atos", "section": "atos-trocar",
     "anchor": "atos-trocar", "oneLiner": "Sai do ato atual e entra em outro, na hora. Sempre novo (recomeçar)."},
    {"name": "on_mode", "kind": "function", "chapter": "mode", "section": "mode-enter",
     "anchor": "mode-enter", "oneLiner": "Decorator: este método é um mode."},
    {"name": "exit_mode", "kind": "function", "chapter": "mode", "section": "mode-cancela",
     "anchor": "mode-cancela", "oneLiner": "@exit_mode: limpeza ao sair do capítulo."},
    {"name": "wait", "kind": "function", "chapter": "mode", "section": "mode-async",
     "anchor": "mode-async", "oneLiner": "Espera N segundos no mode async."},
    {"name": "until", "kind": "function", "chapter": "mode", "section": "mode-async",
     "anchor": "mode-async", "oneLiner": "Espera a condição / Handle."},
    {"name": "parallel", "kind": "function", "chapter": "mode", "section": "mode-async",
     "anchor": "mode-async", "oneLiner": "Espera todos."},
    {"name": "race", "kind": "function", "chapter": "mode", "section": "mode-async",
     "anchor": "mode-async", "oneLiner": "Espera o primeiro."},
    {"name": "LowPass", "kind": "class", "chapter": "som", "section": "som-fx",
     "anchor": "som-fx", "oneLiner": "Filtro passa-baixa no Handle de som."},
    {"name": "HighPass", "kind": "class", "chapter": "som", "section": "som-fx",
     "anchor": "som-fx", "oneLiner": "Filtro passa-alta no Handle de som."},
    {"name": "Echo", "kind": "class", "chapter": "som", "section": "som-fx",
     "anchor": "som-fx", "oneLiner": "Eco. A cauda entra no bake."},
    {"name": "Reverb", "kind": "class", "chapter": "som", "section": "som-fx",
     "anchor": "som-fx", "oneLiner": "Reverb. A cauda entra no bake."},
    {"name": "Distortion", "kind": "class", "chapter": "som", "section": "som-fx",
     "anchor": "som-fx", "oneLiner": "Distorção no Handle de som."},
    {"name": "Wavefold", "kind": "class", "chapter": "som", "section": "som-fx",
     "anchor": "som-fx", "oneLiner": "Wavefold no Handle de som."},
    {"name": "Cancelled", "kind": "exception", "chapter": "agendar", "section": "agendar-handle",
     "anchor": "agendar-handle", "oneLiner": "Handle ou espera cancelada. BaseException — except Exception não pega."},
    {"name": "FxQuality", "kind": "class", "chapter": "mundo", "section": "mundo-apresentacao",
     "anchor": "mundo-apresentacao", "oneLiner": "Preset de fidelidade dos FX. String também vale."},
    {"name": "canvas.framerate", "kind": "property", "chapter": "mundo", "section": "mundo-apresentacao",
     "anchor": "mundo-apresentacao", "oneLiner": "Cadência: vsync60 (padrão), vsync30, vsync, max ou um fps fixo."},
    {"name": "set_fx_auto", "kind": "function", "chapter": "mundo", "section": "mundo-apresentacao",
     "anchor": "mundo-apresentacao", "oneLiner": "Liga/desliga o auto de fidelidade dos FX."},
    {"name": "canvas.display", "kind": "property", "chapter": "mundo", "section": "mundo-apresentacao",
     "anchor": "mundo-apresentacao", "oneLiner": "Modo da janela: windowed, maximized ou fullscreen."},
    {"name": "canvas.fx_quality", "kind": "property", "chapter": "mundo", "section": "mundo-apresentacao",
     "anchor": "mundo-apresentacao", "oneLiner": "Qualidade dos efeitos: low, medium, high (padrão) ou max."},
    {"name": "canvas.cull_offscreen", "kind": "property", "chapter": "mundo", "section": "mundo-apresentacao",
     "anchor": "mundo-apresentacao", "oneLiner": "True: não desenha o que está fora da vista. Padrão False. Só compensa com objetos caros de desenhar."},
    {"name": "canvas.background", "kind": "property", "chapter": "mundo", "section": "mundo-background",
     "anchor": "mundo-background", "oneLiner": "O fundo do mundo: cor, gradiente ou um campo de fundo."},
    {"name": "canvas.effects", "kind": "property", "chapter": "mundo", "section": "mundo-post",
     "anchor": "mundo-post", "oneLiner": "Efeitos de tela (Post) aplicados ao quadro inteiro."},
    {"name": "canvas.layers", "kind": "property", "chapter": "mundo", "section": "mundo-camadas",
     "anchor": "mundo-camadas", "oneLiner": "As camadas do canvas, pelo nome."},
    {"name": "canvas.layers.create", "kind": "method", "chapter": "mundo", "section": "mundo-camadas",
     "anchor": "mundo-camadas", "oneLiner": "Cria uma camada com nome (parallax, esconder tudo de uma vez)."},
    {"name": "collide_stay", "kind": "function", "chapter": "colisao", "section": "colisao-collide",
     "anchor": "colisao-collide", "oneLiner": "Decorator: ainda sobrepostos neste tick."},
    {"name": "collide_exit", "kind": "function", "chapter": "colisao", "section": "colisao-collide",
     "anchor": "colisao-collide", "oneLiner": "Decorator: acabaram de separar."},
    {"name": "collide_with", "kind": "function", "chapter": "colisao", "section": "colisao-collide",
     "anchor": "colisao-collide", "oneLiner": "Método: este objeto × o outro lado."},
    {"name": "collide_with_stay", "kind": "function", "chapter": "colisao", "section": "colisao-collide",
     "anchor": "colisao-collide", "oneLiner": "Método: ainda sobrepostos."},
    {"name": "collide_with_exit", "kind": "function", "chapter": "colisao", "section": "colisao-collide",
     "anchor": "colisao-collide", "oneLiner": "Método: acabaram de separar."},
    {"name": "drag_to", "kind": "function", "chapter": "reagir", "section": "reagir-pointer",
     "anchor": "reagir-pointer", "oneLiner": "Soltou o arraste deste shape."},
    {"name": "drag_over", "kind": "function", "chapter": "reagir", "section": "reagir-pointer",
     "anchor": "reagir-pointer", "oneLiner": "Arraste passando por cima."},
    {"name": "drop_by", "kind": "function", "chapter": "reagir", "section": "reagir-pointer",
     "anchor": "reagir-pointer", "oneLiner": "Algo foi solto neste alvo."},
    {"name": "until_empty", "kind": "function", "chapter": "mode", "section": "mode-async",
     "anchor": "mode-async", "oneLiner": "Espera o grupo esvaziar. Não use until(group.empty)."},
    {"name": "set_watchdog", "kind": "function", "chapter": "mode", "section": "mode-async",
     "anchor": "mode-async", "oneLiner": "Liga/desliga o watchdog de freeze."},
    {"name": "intersection", "kind": "function", "chapter": "geometria", "section": "geo-intersecoes",
     "anchor": "geo-intersecoes", "oneLiner": "Primeiro cruzamento de dois contornos."},
    {"name": "intersections", "kind": "function", "chapter": "geometria", "section": "geo-intersecoes",
     "anchor": "geo-intersecoes", "oneLiner": "Todos os cruzamentos de dois contornos."},
    {"name": "set_extrude_focus", "kind": "function", "chapter": "aparencia", "section": "aparencia-visual",
     "anchor": "aparencia-visual", "oneLiner": "Ponto de luz do Extrude no mundo."},
    {"name": "LinkedAttributeError", "kind": "exception", "chapter": "reativo", "section": "reativo-liga",
     "anchor": "reativo-liga", "oneLiner": "Escreveu com = num campo ligado. Unlink, ou force=True no verbo."},
    {"name": "DerivedAttributeError", "kind": "exception", "chapter": "comecar", "section": "erros-catalogo",
     "anchor": "erros-catalogo", "oneLiner": "Tentou gravar num campo derivado."},
    {"name": "CallableAssignError", "kind": "exception", "chapter": "comecar", "section": "erros-catalogo",
     "anchor": "erros-catalogo", "oneLiner": "Atribuiu uma função com =. Use ['campo'] @= …."},
    {"name": "DestroyedError", "kind": "exception", "chapter": "comecar", "section": "erros-catalogo",
     "anchor": "erros-catalogo", "oneLiner": "O ator já foi destruído."},
    {"name": "ParallaxLayerError", "kind": "exception", "chapter": "comecar", "section": "erros-catalogo",
     "anchor": "erros-catalogo", "oneLiner": "Clique ou colisão numa camada de parallax."},
    {"name": "UiLayerError", "kind": "exception", "chapter": "comecar", "section": "erros-catalogo",
     "anchor": "erros-catalogo", "oneLiner": "Colisão ou SpatialFx na camada ui."},
    {"name": "Visual", "kind": "class", "chapter": "aparencia", "section": "aparencia-visual",
     "anchor": "aparencia-visual", "oneLiner": "Base dos looks (Neon, Glow, …)."},
    {"name": "Recipe", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-paint", "oneLiner": "Base dos looks de várias passadas (Neon, Metal, …)."},
    {"name": "Paint", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-paint", "oneLiner": "Visual de cor completo (fill + contorno)."},
    {"name": "Fill", "kind": "function", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-paint", "oneLiner": "Visual só de preenchimento sólido."},
    {"name": "Stroke", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-paint", "oneLiner": "Visual só de contorno."},
    {"name": "ProceduralFill", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-proc", "oneLiner": "Preenchimento animado (base das fábricas *Fill)."},
    {"name": "WaveFill", "kind": "function", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-proc", "oneLiner": "Fill animado: líquido de qualquer cor."},
    {"name": "AuroraFill", "kind": "function", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-proc", "oneLiner": "Fill animado: faixas de aurora."},
    {"name": "FlameFill", "kind": "function", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-proc", "oneLiner": "Fill animado: fogo."},
    {"name": "WaterFill", "kind": "function", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-proc", "oneLiner": "Fill animado: água (lado ou de cima)."},
    {"name": "SwellFill", "kind": "function", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "mat-proc", "oneLiner": "Fill animado: fluxo abstrato."},
    {"name": "Colormap", "kind": "class", "chapter": "aparencia", "section": "aparencia-paletas",
     "anchor": "aparencia-colormap", "oneLiner": "Amostra contínua de uma paleta."},
    {"name": "ColorSpace", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "aparencia-cor", "oneLiner": "Conversão de espaço de cor."},
    {"name": "ColorNames", "kind": "class", "chapter": "aparencia", "section": "aparencia-cor",
     "anchor": "aparencia-cor", "oneLiner": "Nomes de cor que o Scena reconhece."},
    {"name": "XPos", "kind": "class", "chapter": "desenhar", "section": "desenhar-text",
     "anchor": "desenhar-text", "oneLiner": "Lado horizontal (esquerda, centro, direita)."},
    {"name": "AUTO_GROUND", "kind": "constant", "chapter": "desenhar", "section": "sprite-orientar",
     "anchor": "sprite-orientar", "oneLiner": "Chão automático do sprite."},
    {"name": "TouchingContact", "kind": "class", "chapter": "colisao", "section": "colisao-touching",
     "anchor": "colisao-touching", "oneLiner": "Contato que ainda está tocando."},
]


_ITEM_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)"\s*,\s*kind:\s*"(?P<kind>[^"]+)"\s*,\s*'
    r'family:\s*"(?P<family>[^"]+)"\s*,\s*name:\s*"(?P<name>[^"]+)"',
)
_FIELD_RE = re.compile(
    r'(idea|code|search|thumb|variants):\s*"((?:\\.|[^"\\])*)"',
)
# Thumbnail knobs (make_guia_thumbs.py): ``thumb: "…"`` overrides the snippet
# the thumbnail runs; ``anim: true|false`` overrides the animated default.
_ANIM_RE = re.compile(r'\banim:\s*(true|false)\b')
_NOTHUMB_RE = re.compile(r'\bthumb:\s*false\b')
THUMB_FAMILIES = ("visual", "spatial", "post", "impact", "field",
                  "life", "hit", "pulse", "pop", "knock", "spark", "exit", "enter")
_P_RE = re.compile(
    r'P\(\s*"(?P<name>(?:\\.|[^"\\])*)"\s*,\s*"(?P<def>(?:\\.|[^"\\])*)"\s*,\s*'
    r'"(?P<meaning>(?:\\.|[^"\\])*)"\s*'
    r'(?:,\s*(?P<pos>\d+))?'
    r'(?:,\s*"(?P<typ>(?:\\.|[^"\\])*)")?\s*\)',
)
_BAGS = (
    ("LOOKS", "const LOOKS"),
    ("STAMPS", "const STAMPS"),
    ("TRANSIENTS", "const TRANSIENTS"),
    ("SPATIAL", "const SPATIAL"),
    ("POST", "const POST"),
    ("IMPACTS", "const IMPACTS"),
    ("BACKGROUNDS", "const BACKGROUNDS"),
    ("FILTERS", "const FILTERS"),
)
_FIELDCAM = [
    {"name": "pan_response", "def": "", "meaning": "0 = colado na tela. 1 = 1:1 com o mundo", "pos": 0, "typ": "número"},
    {"name": "zoom_response", "def": "", "meaning": "Quanto o zoom da câmera afeta o padrão", "pos": 0, "typ": "número"},
    {"name": "rotation_response", "def": "", "meaning": "Fração da rotação da câmera", "pos": 0, "typ": "número"},
    {"name": "scroll", "def": "(0, 0)", "meaning": "Deriva em unidades de design / s", "pos": 0, "typ": "ponto"},
    {"name": "enabled", "def": "True", "meaning": "Esconde o desenho sem tirar da pilha", "pos": 0, "typ": "bool"},
]


def _unescape(s: str) -> str:
    return s.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")


def load_catalogs() -> dict:
    src = CATALOGS.read_text(encoding="utf-8")
    out: dict[str, list] = {}
    for bag, marker in _BAGS:
        start = src.find(marker)
        if start < 0:
            raise SystemExit(f"bag {bag} não encontrada")
        nxt = len(src)
        for _, m2 in _BAGS:
            p = src.find(m2, start + 1)
            if 0 <= p < nxt:
                nxt = p
        chunk = src[start:nxt]
        items = []
        matches = list(_ITEM_RE.finditer(chunk))
        for i, m in enumerate(matches):
            block = chunk[m.start(): matches[i + 1].start() if i + 1 < len(matches) else len(chunk)]
            # The last card of a bag must not absorb helpers defined after the array.
            block = re.split(r"\n\s*\];", block, maxsplit=1)[0]
            item = {
                "id": m.group("id"),
                "kind": m.group("kind"),
                "family": m.group("family"),
                "name": m.group("name"),
                "idea": "",
                "code": "",
                "search": "",
                "params": [],
            }
            for fm in _FIELD_RE.finditer(block):
                item[fm.group(1)] = _unescape(fm.group(2))
            am = _ANIM_RE.search(block)
            if am:
                item["anim"] = am.group(1) == "true"
            if _NOTHUMB_RE.search(block):
                item["thumb"] = False
            params = []
            for pm in _P_RE.finditer(block):
                params.append({
                    "name": pm.group("name"),
                    "def": _unescape(pm.group("def")),
                    "meaning": _unescape(pm.group("meaning")),
                    "pos": int(pm.group("pos") or 0),
                    "typ": pm.group("typ") or "",
                })
            if "...fieldCam" in block:
                params.extend(_FIELDCAM)
            item["params"] = params
            items.append(item)
        out[bag] = items
    return out


# ── Strict JS check ────────────────────────────────────────────────────────
# ``load_catalogs`` reads the catalog with tolerant regexes: a file the
# browser rejects (one stray ``)``) still "loads" here while the page shows
# no catalog at all. These checks read the file the way a JS parser does.

_JS_PAIR = {"(": ")", "[": "]", "{": "}"}
_JS_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_JS_REGEX_WORDS = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new"}


def _js_where(src: str, pos: int) -> str:
    line = src.count("\n", 0, pos) + 1
    col = pos - (src.rfind("\n", 0, pos) + 1) + 1
    return f"{line}:{col}"


def js_brackets(src: str, label: str = "js") -> tuple[list[str], dict, dict]:
    """Bracket structure of a JS source, skipping strings, comments, regex
    literals and template text (``${…}`` inside templates is code).

    Returns ``(errors, pairs, depth)``: ``pairs`` maps each opener offset to
    its closer offset, ``depth`` maps each opener offset to its nesting depth.
    """
    errors: list[str] = []
    pairs: dict[int, int] = {}
    depth: dict[int, int] = {}
    stack: list[tuple[str, int]] = []   # (opener, offset); "$" = template ${
    n = len(src)
    prev = ""                           # last significant token (regex vs division)

    def scan_template(i: int) -> tuple[int, str]:
        while i < n:
            c = src[i]
            if c == "\\":
                i += 2
                continue
            if c == "`":
                return i + 1, "end"
            if src.startswith("${", i):
                return i + 2, "expr"
            i += 1
        return n, "eof"

    def template(start: int, i: int) -> int:
        i, how = scan_template(i)
        if how == "eof":
            errors.append(f"{label}:{_js_where(src, start)}: template sem fechar")
        elif how == "expr":
            depth[i - 2] = len(stack)
            stack.append(("$", i - 2))
        return i

    i = 0
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                errors.append(f"{label}:{_js_where(src, i)}: comentário sem fechar")
                break
            i = j + 2
            continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            if j >= n or src[j] != c:
                errors.append(f"{label}:{_js_where(src, i)}: string sem fechar")
            i = j + 1
            prev = '"'
            continue
        if c == "`":
            i = template(i, i + 1)
            prev = '"'
            continue
        if c == "/" and (prev == "" or prev in _JS_REGEX_AFTER or prev in _JS_REGEX_WORDS):
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if in_class:
                    in_class = ch != "]"
                elif ch == "[":
                    in_class = True
                elif ch == "/":
                    break
                j += 1
            if j >= n or src[j] != "/":
                errors.append(f"{label}:{_js_where(src, i)}: regex sem fechar")
            j += 1
            while j < n and (src[j].isalpha()):
                j += 1
            i = j
            prev = '"'
            continue
        if c in _JS_PAIR:
            depth[i] = len(stack)
            stack.append((c, i))
            prev = c
            i += 1
            continue
        if c in ")]}":
            if not stack:
                errors.append(f"{label}:{_js_where(src, i)}: {c!r} sem abertura")
                break
            op, at = stack.pop()
            pairs[at] = i
            if op == "$":
                if c != "}":
                    errors.append(f"{label}:{_js_where(src, i)}: {c!r} fecha o ${{ de "
                                  f"{_js_where(src, at)}")
                    break
                i = template(at, i + 1)
                prev = '"'
                continue
            if _JS_PAIR[op] != c:
                # The first mismatch is the bug; everything after it cascades.
                errors.append(f"{label}:{_js_where(src, i)}: {c!r} fecha o {op!r} de "
                              f"{_js_where(src, at)}")
                break
            prev = c
            i += 1
            continue
        m = re.match(r"[A-Za-z_$][\w$]*|\d[\w.]*", src[i:i + 64])
        if m:
            prev = m.group(0)
            i += len(m.group(0))
            continue
        prev = c
        i += 1
    if not errors:
        for op, at in stack:
            errors.append(f"{label}:{_js_where(src, at)}: {op!r} sem fechar")
    return errors, pairs, depth


def check_catalog_js(path: Path = CATALOGS, bags: dict | None = None) -> list[str]:
    """The catalog file must be valid JS *and* hold the cards the loader sees.

    A JS error leaves the Guia with no catalog at all; a card the regex loader
    misses is unchecked. ``bags`` defaults to ``load_catalogs()``.
    """
    src = path.read_text(encoding="utf-8")
    errors, pairs, depth = js_brackets(src, path.name)
    if errors or path != CATALOGS:
        return errors
    bags = load_catalogs() if bags is None else bags
    for bag, _marker in _BAGS:
        m = re.search(rf"\bconst {bag}\s*=\s*\[", src)
        if not m:
            errors.append(f"{path.name}: bag {bag} sem 'const {bag} = ['")
            continue
        start = m.end() - 1
        end = pairs.get(start, start)
        d = depth.get(start, 0)
        cards = sum(1 for at, dd in depth.items()
                    if start < at < end and dd == d + 1 and src[at] == "{")
        seen = len(bags.get(bag, []))
        if cards != seen:
            errors.append(f"{path.name}: {bag} tem {cards} card(s) em JS e {seen} no "
                          "leitor do validador (ordem id/kind/family/name?)")
    return errors


def _js_engine() -> list[str] | None:
    import shutil
    node = shutil.which("node")
    if node:
        return [node]
    jsc = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc")
    return [str(jsc)] if jsc.exists() else None


def check_catalog_js_engine(bags: dict | None = None) -> list[str] | None:
    """Run the catalog in a real JS engine (node / jsc) and compare bag sizes.

    ``None`` when no engine is installed (the tokenizer check still runs).
    """
    import subprocess
    import tempfile
    engine = _js_engine()
    if engine is None:
        return None
    bags = load_catalogs() if bags is None else bags
    src = CATALOGS.read_text(encoding="utf-8")
    probe = (
        "var window = {};\n" + src + "\n;(function () {\n"
        "  var c = window.ScenaGuideCatalogs || {}, out = {};\n"
        "  for (var k in c) if (Array.isArray(c[k])) out[k] = c[k].length;\n"
        "  (typeof print === 'function' ? print : console.log)(JSON.stringify(out));\n"
        "})();\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(probe)
        tmp = f.name
    try:
        out = subprocess.run(engine + [tmp], capture_output=True, text=True, timeout=60)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if out.returncode != 0:
        return [f"{CATALOGS.name}: o motor JS rejeita o arquivo: "
                f"{(out.stderr or out.stdout).strip()[:400]}"]
    try:
        got = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [f"{CATALOGS.name}: saída inesperada do motor JS: {out.stdout[:200]!r}"]
    errors = []
    for bag, _marker in _BAGS:
        want = len(bags.get(bag, []))
        if got.get(bag) != want:
            errors.append(f"{CATALOGS.name}: {bag} exporta {got.get(bag)} card(s) no "
                          f"navegador e {want} no leitor do validador")
    return errors


def read_thumbs_js() -> dict | None:
    """``window.ScenaGuideThumbs`` as a dict (``None`` when the file is absent)."""
    if not THUMBS_JS.exists():
        return None
    src = THUMBS_JS.read_text(encoding="utf-8")
    m = re.search(r"window\.ScenaGuideThumbs\s*=\s*(\{.*\})\s*;\s*$", src, re.S)
    if not m:
        raise ValueError(f"{THUMBS_JS.name}: sem 'window.ScenaGuideThumbs = {{…}};'")
    return json.loads(m.group(1))


def guide_choices(meaning: str) -> list[str]:
    """The options a parameter row lists: ``"camp · soft · plume"`` (prose after
    an option, ``"spark = impacto"`` / ``"heat. Só…"``, is ignored)."""
    text = strip_tags(meaning)
    out = []
    for part in text.split("·"):
        m = re.match(r"\s*([a-z_]+)\b", part)
        if m:
            out.append(m.group(1))
    return out


def check_variant_choices(bags: dict) -> list[str]:
    """A card with ``variants: "style"`` shows one picture per value the code
    accepts. The Guia's own list for that parameter must be the same list."""
    import make_guia_thumbs as mt
    errors = []
    for items in bags.values():
        for it in items:
            for vp in mt.variant_params(it):
                try:
                    code = mt.probe_choices(it, vp)
                except ValueError as e:
                    errors.append(str(e))
                    continue
                row = next((p for p in it.get("params") or [] if p["name"] == vp), None)
                listed = guide_choices(row["meaning"]) if row else []
                if sorted(listed) != sorted(code):
                    errors.append(f"{it['id']}.{vp}: o Guia lista {' · '.join(listed) or '—'}; "
                                  f"o código aceita {' · '.join(code)}")
    return errors


def check_thumbs(bags: dict) -> tuple[list[str], list[str]]:
    """Catalog thumbnails (make_guia_thumbs.py): ``(errors, warnings)``.

    Errors: the page data is not JS / JSON, names a card that does not exist,
    or points at a missing file. Warnings: in-scope cards with no thumbnail or
    a stale one (its inputs changed since it was rendered).
    """
    errors: list[str] = []
    warnings: list[str] = []
    if THUMBS_JS.exists():
        errors.extend(js_brackets(THUMBS_JS.read_text(encoding="utf-8"), THUMBS_JS.name)[0])
    try:
        data = read_thumbs_js()
    except ValueError as e:
        return errors + [str(e)], warnings
    if data is None:
        warnings.append(f"sem {THUMBS_JS.name}: python make_guia_thumbs.py")
        return errors, warnings
    ids = {it["id"] for items in bags.values() for it in items}
    for iid, e in data.items():
        if iid not in ids:
            errors.append(f"{THUMBS_JS.name}: {iid} não é card de catálogo")
        for key in ("src", "anim"):
            f = e.get(key)
            if f and not (GUIDE / f).exists():   # f is relative to the page
                errors.append(f"{THUMBS_JS.name}: {iid}.{key} aponta para {f}, que não existe")
    import make_guia_thumbs as mt
    state = mt.status(mt.select(bags), mt.load_manifest())
    stale = sorted(k for k, v in state.items() if v == "stale")
    missing = sorted(k for k, v in state.items() if v == "missing")
    if stale:
        warnings.append(f"{len(stale)} prévia(s) desatualizada(s) ({', '.join(stale[:6])}"
                        f"{'…' if len(stale) > 6 else ''}) → python make_guia_thumbs.py")
    if missing:
        warnings.append(f"{len(missing)} card(s) sem prévia → python make_guia_thumbs.py")
    return errors, warnings


_INFER_BY_NAME = {
    "color": "cor", "to": "cor", "color2": "cor", "color3": "cor", "underlay": "cor",
    "top": "cor", "middle": "cor", "bottom": "cor", "sky": "cor", "space": "cor",
    "key": "cor",
    "live": "bool", "only_int": "bool", "show_value": "bool", "centered": "bool",
    "use_center": "bool", "enabled": "bool", "rings": "bool", "border": "bool",
    "into": "bool", "reflect": "bool", "flash": "bool",
    "edges": "bool", "shock": "bool", "shake": "bool", "recipe": "str",
    "on_done": "() → None",
    "at": "ponto / (() → ponto)",
    "style": "str", "preset": "str", "kind": "str", "fit": "str", "tile_mode": "str",
    "wrap": "str", "family": "str", "palette": "str", "source": "str", "label": "str",
    "name": "str", "axis": "str", "fold": "str", "roll": "str", "filename": "str",
    "colors": "sequência",
    "center": "ponto", "p1": "ponto", "p2": "ponto", "origin": "ponto", "focus": "ponto",
    "offset": "número / ponto", "scroll": "ponto", "target": "ponto",
    "n": "int", "points": "int", "cols": "int", "rows": "int", "layers": "int",
    "count": "int", "segments": "int", "spokes": "int",
    "outer": "filtro", "inner": "filtro", "image": "Image",
}
_INFER_NUM = re.compile(
    r"^(radius|sigma|amount|speed|width|height|length|intensity|duration|fps|scale|"
    r"angle|min_value|max_value|density|rate|spread|glow|phase|soft_edge|x|y|x1|y1|"
    r"x2|y2|pan_response|zoom_response|rotation_response|alpha|size|tile_size|"
    r"opacity|fade|zoom|spin|fall|trail|horizon|twinkle|band|detail|drift|rise|"
    r"spacing|layer_scale|line|contrast|grid|fog|streak|bright|relief|seed|"
    r"res_scale|flicker|darken|gap|fill_scale|depth|range|soft|scale_end|distance|"
    r"dx|dy|twist|core|hue_speed|saturation|thickness|cell|weight|decay|exposure|"
    r"ambient|specular|brightness|bias|cone_angle|softness|bloom|sigmaX|sigmaY|"
    r"radiusX|radiusY)$"
)


def infer_type(p: dict) -> str:
    if p.get("typ"):
        return p["typ"]
    n = p.get("name") or ""
    if n in _INFER_BY_NAME:
        return _INFER_BY_NAME[n]
    if _INFER_NUM.match(n):
        return "número"
    return ""


def validate_catalogs(bags: dict) -> list[str]:
    errors = []
    for bag, items in bags.items():
        kinds = {it.get("kind") for it in items}
        for it in items:
            iid = it.get("id", "?")
            fam = it.get("family")
            if fam not in KNOWN_FAMILIES:
                errors.append(f"{iid}: family desconhecida {fam!r}")
            if ("thumb" in it or "anim" in it or "variants" in it) and fam not in THUMB_FAMILIES:
                errors.append(f"{iid}: thumb / anim / variants só em {', '.join(THUMB_FAMILIES)}")
            for vp in [v.strip() for v in str(it.get("variants") or "").split(",") if v.strip()]:
                if vp not in {p.get("name") for p in it.get("params") or []}:
                    errors.append(f"{iid}: variants: {vp!r} não é parâmetro do card")
            if isinstance(it.get("thumb"), str) and it.get("thumb"):
                try:
                    compile(_prepare(it["thumb"]), f"{iid}.thumb", "exec")
                except SyntaxError as e:
                    errors.append(f"{iid}.thumb: {e.msg} (linha {e.lineno})")
            params = it.get("params")
            if params is None:
                errors.append(f"{iid}: sem campo params")
                continue
            # Métodos sem knobs (ex.: clear_transients) são válidos com [].
            for p in params:
                name = p.get("name") or ""
                if not IDENT.match(name):
                    errors.append(f"{iid}: nome de parâmetro inválido {name!r}")
                typ = infer_type(p)
                if not typ:
                    errors.append(f"{iid}.{name}: tipo não declarado")
        if bag == "STAMPS" and len(kinds) > 1:
            pass  # chips expected
    return errors


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    return re.sub(r"\s+", " ", text).strip()


def catalog_symbols(bags: dict) -> list[dict]:
    out = []
    for items in bags.values():
        for it in items:
            fam = it.get("family") or ""
            ch, sec, ch_title, sec_title = FAMILY_CHAPTER.get(
                fam, ("aparencia", "aparencia", "Aparência", fam)
            )
            out.append({
                "name": it["name"],
                "public": True,
                "kind": "class" if it["name"][:1].isupper() else "method",
                "chapter": ch,
                "chapterTitle": ch_title,
                "section": sec,
                "sectionTitle": sec_title,
                "anchor": it["id"],
                "oneLiner": strip_tags(it.get("idea") or ""),
                "search": it.get("search") or "",
                "family": fam,
                "catalog": True,
                "params": [
                    {"name": p["name"], "pass": p.get("pos") or "kw",
                     "type": p.get("typ") or "", "def": p.get("def") or "",
                     "doc": p.get("meaning") or ""}
                    for p in (it.get("params") or [])
                ],
            })
    return out


def core_symbols() -> list[dict]:
    titles = {
        "comecar": "Começar", "reativo": "Reativo", "desenhar": "Desenhar",
        "aparencia": "Aparência", "mundo": "Mundo", "colocar": "Colocar",
        "frame": "Frame", "mover": "Mover", "agendar": "Agendar", "mode": "Mode",
        "atos": "Atos",
        "som": "Som", "reagir": "Reagir", "colisao": "Colisão",
        "geometria": "Geometria", "ui": "UI", "util": "Utilitários", "atalhos": "Debug",
    }
    section_title = {
        "reativo-liga": "Ligar", "globais": "Objetos globais únicos",
        "script-minimo": "Script mínimo", "desenhar-shapes": "Shapes",
        "desenhar-sprite": "Sprite", "desenhar-text": "Text",
        "spr-hit": "Hitbox do Sprite", "sprite-extras": "Recursos adicionais do Sprite",
        "desenhar-entity": "Entity", "desenhar-track": "Track",
        "desenhar-history": "History / Contrail",
        "desenhar-spatial": "SpatialFx", "desenhar-drawable": "Todo drawable",
        "colocar-box": "Box", "colocar-grid": "Grid", "colocar-fase": "Level",
        "aparencia-cor": "Cor / Gradient / Texture", "mundo-background": "Background",
        "mundo-camera": "Câmera", "mundo-grupos": "Grupos", "mundo-sem-fim": "Mundo sem fim", "mundo-post": "Post",
        "mundo-impactos": "Impactos",
        "frame-clock": "clock", "frame-teclado": "Teclado", "frame-mouse": "Mouse",
        "mover-pose": "move / rotate / scale", "mover-tween": "tween",
        "mover-move-along": "move_along", "suite": "Suíte time=", "colisao-corpo": "O que colide",
        "agendar-handle": "Handle", "agendar-timers": "after / every",
        "agendar-ready": "ready", "agendar-recently": "recently",
        "som-play": "play_sound", "som-audio": "audio", "som-mic": "Microphone",
        "som-fx": "efeitos",
        "geo-vec2": "Vec2", "geo-helpers": "Pontos",
        "geo-intersecoes": "Cruzamentos",
        "colisao-resolve": "Tornar sólido", "colisao-aux": "Consultas",
        "colisao-collide": "Detectar",
        "reagir-when": "@when", "reagir-pointer": "Clique / arraste",
        "ui-widgets": "Widgets", "ui-sprite-button": "SpriteButton",
        "reativo-state": "State", "reativo-entity": "Guardar valores",
        "mundo-apresentacao": "Apresentação",
        "mundo-camadas": "Camadas",
        "aparencia-visual": "Visual", "aparencia-paletas": "Paletas e rampas",
        "mode-async": "async / wait",
        "atos-classe": "Act", "atos-trocar": "change_act",
        "debug-metodos": "Métodos",
        "erros-catalogo": "Catálogo de erros", "reativo-fontes": "O que pode ser ligado",
        "sprite-orientar": "Orientar sprites", "colisao-touching": "Tocando",
    }
    out = []
    for s in CORE_SYMBOLS:
        ch = s["chapter"]
        out.append({
            **s,
            "public": True,
            "chapterTitle": titles.get(ch, ch),
            "sectionTitle": section_title.get(s["section"], s["section"]),
            "search": s["name"].lower(),
            "catalog": False,
            "params": s.get("params") or [],
        })
    return out


def write_symbols(symbols: list[dict]) -> None:
    payload = {
        "internals": sorted(INTERNALS),
        "symbols": symbols,
    }
    SYMBOLS_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    slim = []
    for s in symbols:
        slim.append({
            "name": s["name"],
            "kind": s["kind"],
            "chapter": s["chapter"],
            "chapterTitle": s.get("chapterTitle") or s["chapter"],
            "section": s["section"],
            "sectionTitle": s.get("sectionTitle") or s["section"],
            "anchor": s["anchor"],
            "oneLiner": s.get("oneLiner") or "",
            "search": s.get("search") or "",
        })
    SYMBOLS_JS.write_text(
        "/* Generated by validate_guia.py — do not edit. */\n"
        "(function (w) {\n"
        f"  w.ScenaGuideSymbols = {json.dumps(slim, ensure_ascii=False)};\n"
        "})(window);\n",
        encoding="utf-8",
    )


def check_public_vs_all() -> list[str]:
    """scena.__all__ minus INTERNALS should be reachable as a symbol name."""
    sys.path.insert(0, str(REPO))
    try:
        import scena  # type: ignore
    except Exception as exc:
        return [f"não deu para importar scena: {exc}"]
    exported = set(scena.__all__)
    warnings = []
    # Singletons live on builtins after init, not all are in __all__ as names
    # of the instance. `st` is in FRAMEWORK_EXPORTS.
    documented = {s["name"] for s in CORE_SYMBOLS}
    # catalogs cover the rest of looks/fx
    bags = load_catalogs()
    for items in bags.values():
        for it in items:
            documented.add(it["name"])
    missing = []
    for name in sorted(exported - INTERNALS):
        if name in documented:
            continue
        # methods on canvas.flash etc. appear as catalog names "canvas.flash"
        if any(name in re.split(r"[^A-Za-z0-9_]+", d) for d in documented):
            continue
        missing.append(name)
    if missing:
        warnings.append(
            "exportados e públicos sem entrada de símbolo (ok se forem "
            f"kwargs/enums): {', '.join(missing[:40])}"
            + ("…" if len(missing) > 40 else "")
        )
    leaked = sorted(INTERNALS & documented)
    if leaked:
        warnings.append(f"interno aparece no índice: {', '.join(leaked)}")
    return warnings


def known_html_ids(bags: dict) -> set[str]:
    """Static HTML ids plus catalog item ids (injected at runtime)."""
    html = HTML.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    for items in bags.values():
        for it in items:
            ids.add(it["id"])
    return ids


def check_anchors(symbols: list[dict], bags: dict) -> list[str]:
    ids = known_html_ids(bags)
    missing = []
    for s in symbols:
        anchor = s.get("anchor") or ""
        if not anchor:
            missing.append(f"{s['name']}: sem anchor")
            continue
        if anchor not in ids:
            missing.append(f"{s['name']}: âncora #{anchor} não existe no HTML/catálogo")
    return missing


# --- signatures -------------------------------------------------------------

# Construction plumbing and look-hooks that are not author knobs.
_SIG_SKIP = frozenset({"self", "cls", "attr_name", "owner", "register"})


def _scena():
    sys.path.insert(0, str(REPO))
    import scena  # type: ignore
    return scena


def resolve_catalog_symbol(name: str):
    """Python object behind a catalog name (``Glow``, ``canvas.flash``, ``fade_out``)."""
    scena = _scena()
    head, _, rest = name.partition(".")
    if head in scena.__all__:
        obj = getattr(scena, head)
        for part in filter(None, rest.split(".")):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj
    return getattr(scena.Shape, name, None)


def real_parameters(obj) -> tuple[dict, bool, bool]:
    """``({name: Parameter}, accepts_extra_kwargs, accepts_extra_positionals)``.

    Classes merge a custom ``__new__`` (style dispatch, e.g. ``Fire``) with
    ``__init__``. Wrapper signatures come from ``__wrapped__`` / ``__signature__``.
    """
    fns = []
    if isinstance(obj, type):
        # The class's own signature first: ``cls.__signature__`` (published by
        # dispatching kinds such as ``Fire``) lists knobs that ``__new__`` /
        # ``__init__`` only take through ``**kwargs``. Without it a card could
        # omit ``Fire(angle=)`` and the gap check saw nothing.
        try:
            fns.append(obj)
            inspect.signature(obj)
        except (TypeError, ValueError):
            fns.pop()
        for base in obj.__mro__:
            if "__new__" in base.__dict__ and base.__module__.split(".")[0] == "scena":
                fns.append(base.__dict__["__new__"])
                break
        fns.append(obj.__init__)
    else:
        fns.append(obj)
    params: dict = {}
    var_kw = var_pos = False
    for fn in fns:
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            var_kw = var_pos = True
            continue
        for p in sig.parameters.values():
            if p.kind is p.VAR_KEYWORD:
                var_kw = True
            elif p.kind is p.VAR_POSITIONAL:
                var_pos = True
            elif p.name not in _SIG_SKIP:
                params.setdefault(p.name, p)
    return params, var_kw, var_pos


def _same_default(doc: str, real) -> bool:
    doc = doc.strip()
    if not doc or doc in ("—", "-", "auto", "obrigatório", "required"):
        return True
    if real is inspect.Parameter.empty or real is None:
        return True  # required, or derived at run time ("segue o objeto")
    if isinstance(real, bool):
        return doc in (repr(real), str(real))
    if isinstance(real, (int, float)):
        try:
            return math.isclose(float(doc), float(real), rel_tol=1e-9, abs_tol=1e-12)
        except ValueError:
            return True  # prose default ("theme", "canvas center")
    if isinstance(real, str):
        quoted = len(doc) >= 2 and doc[0] == doc[-1] and doc[0] in "'\""
        return doc[1:-1] == real if quoted else True
    if isinstance(real, tuple):
        try:
            return tuple(ast.literal_eval(doc)) == real
        except (ValueError, SyntaxError, TypeError):
            return True
    return True


# Knobs every card's host takes, documented once in the section, not per card:
# ``layer=`` / ``group=`` in "Todo objeto na tela", ``soft_edge=`` in SpatialFx.
_CARD_SHARED = frozenset({"layer", "group"})
_FAMILY_SHARED = {"spatial": frozenset({"soft_edge"})}


def check_catalog_signatures(bags: dict) -> tuple[list[str], list[str]]:
    """(errors, gaps): wrong knobs/defaults, and public knobs the card omits."""
    errors: list[str] = []
    gaps: list[str] = []
    for items in bags.values():
        for it in items:
            obj = resolve_catalog_symbol(it["name"])
            if obj is None or not callable(obj):
                continue
            real, var_kw, var_pos = real_parameters(obj)
            documented = {p["name"] for p in it["params"]}
            positional = [
                n for n, p in real.items()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
            for p in it["params"]:
                name = p["name"]
                rp = real.get(name)
                if rp is None:
                    if not var_kw:
                        errors.append(f"{it['id']}: parâmetro {name!r} não existe em {it['name']}")
                    continue
                if not _same_default(p.get("def") or "", rp.default):
                    errors.append(
                        f"{it['id']}.{name}: default no Guia {p['def']!r}, no código {rp.default!r}"
                    )
                pos = p.get("pos") or 0
                if pos and not var_pos and (pos > len(positional) or positional[pos - 1] != name):
                    errors.append(
                        f"{it['id']}.{name}: Guia diz posição {pos}, código tem "
                        f"{positional[:4]}"
                    )
            shared = _CARD_SHARED | _FAMILY_SHARED.get(it.get("family"), frozenset())
            for name, rp in real.items():
                if name.startswith("_") or name in documented or name in shared:
                    continue
                gaps.append(f"{it['id']}: {it['name']} aceita {name}= (não documentado)")
    return errors, gaps


def param_skeleton(obj) -> list[tuple[str, str, int]]:
    """Structural catalog rows from the live signature.

    Each item is ``(name, default text, positional index or 0)``. Portuguese
    ``meaning`` stays hand-written; ``check_catalog_signatures`` diffs only
    these three fields.
    """
    import inspect
    real, _, _ = real_parameters(obj)
    positional = [
        n for n, p in real.items()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    rows = []
    for i, name in enumerate(positional, 1):
        p = real[name]
        shown = "" if p.default is inspect.Parameter.empty else repr(p.default)
        rows.append((name, shown, i))
    for name, p in real.items():
        if name in positional or name.startswith("_"):
            continue
        if p.kind == p.VAR_KEYWORD or p.kind == p.VAR_POSITIONAL:
            continue
        shown = "" if p.default is inspect.Parameter.empty else repr(p.default)
        rows.append((name, shown, 0))
    return rows


# --- examples ---------------------------------------------------------------

# A statement whose line says it fails on purpose ("# TypeError", "# erro").
_EXPECT_ERROR = re.compile(
    r"#.*(\b\w*Error\b|\braise|\blevanta|\berro\b|\bfalha|\bproibido|✗|não vale|não funciona)",
    re.I,
)
# Level reads a file the example does not have; the prelude provides `fase`.
_SKIP_CALLS = frozenset({"run", "init", "input", "sleep", "Level"})


def collect_examples(bags: dict) -> list[tuple[str, str]]:
    src = HTML.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"<pre>(.*?)</pre>", src, re.S):
        line = src.count("\n", 0, m.start()) + 1
        code = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        out.append((f"html:{line}", code))
    for items in bags.values():
        for it in items:
            if it.get("code"):
                out.append((f"catalog:{it['id']}", it["code"]))
    return out


def _prepare(code: str) -> str:
    return code.replace("…", "...")


def check_examples_compile(examples) -> list[str]:
    errors = []
    for loc, code in examples:
        try:
            compile(_prepare(code), loc, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        except SyntaxError as e:
            errors.append(f"{loc}+{e.lineno}: SyntaxError: {e.msg} :: {(e.text or '').strip()}")
    return errors


def _free_names(node: ast.AST) -> set:
    """Names a top-level statement reads when it runs (def bodies do not run)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        roots = list(node.decorator_list)
        if isinstance(node, ast.ClassDef):
            roots += node.bases
        else:
            roots += node.args.defaults + [d for d in node.args.kw_defaults if d]
    else:
        roots = [node]
    loads, binds = set(), set()
    for root in roots:
        for sub in ast.walk(root):
            if isinstance(sub, ast.Name):
                (loads if isinstance(sub.ctx, ast.Load) else binds).add(sub.id)
            elif isinstance(sub, ast.arg):
                binds.add(sub.arg)
    return loads - binds


def _skip_statement(node: ast.AST) -> bool:
    if isinstance(node, (ast.While, ast.Import, ast.ImportFrom)):
        return True
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            return True
        if isinstance(sub, ast.Constant) and sub.value is Ellipsis:
            return True  # placeholder (``points=[...]``, ``f(…)``)
        if isinstance(sub, ast.Call):
            f = sub.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name in _SKIP_CALLS:
                return True
    return False


_SAMPLE_LEVEL: list = []


def _sample_level() -> str:
    """A level file with the names the Guia's Level examples use (made once)."""
    if not _SAMPLE_LEVEL:
        import os
        import tempfile
        items = [
            {"kind": "rect", "name": "chao", "groups": ["plataforma"],
             "center": [400, 20], "width": 800, "height": 40},
            {"kind": "rect", "name": "elevador", "groups": ["plataforma"],
             "center": [1300, 90], "width": 120, "height": 20, "angle": 10},
            {"kind": "rect", "name": "arena", "center": [400, 300], "width": 800, "height": 600},
            {"kind": "ellipse", "name": "lago", "center": [500, 60], "width": 300, "height": 80},
            {"kind": "point", "groups": ["estrela"], "center": [330, 320]},
            {"kind": "point", "groups": ["estrela"], "center": [450, 240]},
            {"kind": "point", "name": "inicio", "center": [120, 70]},
            {"kind": "track", "name": "rota_drone", "points": [[900, 600], [1300, 600]]},
            {"kind": "image", "name": "fundo", "file": "fundo.png",
             "center": [400, 300], "width": 800, "height": 600},
        ]
        doc = {"format": "scena-level", "version": 1, "size": [3600, 1500], "items": items}
        path = os.path.join(tempfile.mkdtemp(prefix="guia_level_"), "fase1.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        _SAMPLE_LEVEL.append(path)
    return _SAMPLE_LEVEL[0]


def run_examples(examples, stats: dict | None = None) -> list[str]:
    """Execute each example statement whose names are all defined.

    Fragments lean on context (``c``, ``player``); a statement that reads a
    name the block never defines is skipped, not failed. Lines marked as
    failing on purpose are skipped. Everything else must run.
    ``stats`` (optional) receives ``ran`` / ``skipped`` statement counts.
    """
    import contextlib
    import io
    counts = {"ran": 0, "skipped": 0, "sections": {}}
    section_at = []
    current = "intro"
    for i, line in enumerate(HTML.read_text(encoding="utf-8").splitlines(), 1):
        m = re.search(r'id="([^"]+)"', line)
        if m and ("section" in line or "article" in line or "chapter" in line):
            current = m.group(1)
        section_at.append(current)
    scena = _scena()
    import warnings
    warnings.simplefilter("ignore")
    base = {n: getattr(scena, n) for n in scena.__all__}
    # Shared names examples assume (player, c, ship, …). Rebuilt per block.
    def _prelude():
        scena.canvas.layers.clear(hard=True)
        ns = dict(base)
        ns["c"] = scena.Circle(center=(0, 0), radius=40, color="cyan")
        ns["player"] = scena.Sprite("player.png", center=(0, 0), group="player")
        ns["player"].hp = 10
        ns["ship"] = scena.Circle(center=(0, 0), radius=16, color="white")
        ns["ship"].hp = 10
        ns["ball"] = scena.Circle(center=(10, 10), radius=12)
        ns["dot"] = scena.Circle(center=(0, 0), radius=4)
        ns["planet"] = scena.Circle(center=(0, 0), radius=80)
        ns["marker"] = scena.Point(0, 0, visible=True)
        ns["wall"] = scena.Rect(center=(0, -40), width=200, height=16)
        ns["rect"] = ns["wall"]
        ns["sprite"] = ns["player"]
        ns["earth"] = ns["planet"]
        ns["moon"] = scena.Circle(center=(120, 0), radius=12)
        ns["track"] = scena.Track.line(length=200)
        ns["x"] = 0
        ns["y"] = 0
        ns["dt"] = 1 / 60
        ns["fase"] = scena.Level(_sample_level())
        scena.st.pulse = 0.0
        return ns
    known_builtins = set(dir(builtins))
    failures = []
    import linecache
    for loc, code in examples:
        code = _prepare(code)
        try:
            tree = compile(code, loc, "exec", flags=ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        except SyntaxError:
            continue
        lines = code.splitlines()
        # Formula links read the lambda's source, as they would from a file.
        linecache.cache[loc] = (len(code), None, code.splitlines(True), loc)
        ns = _prelude()
        for node in tree.body:
            seg = "\n".join(lines[node.lineno - 1: node.end_lineno])
            sec = "catalog"
            if loc.startswith("html:"):
                n = int(loc.split(":")[1])
                sec = section_at[min(n, len(section_at)) - 1]
            bucket = counts["sections"].setdefault(sec, {"ran": 0, "skipped": 0})
            if (_EXPECT_ERROR.search(seg) or _skip_statement(node)
                    or _free_names(node) - ns.keys() - known_builtins):
                counts["skipped"] += 1
                bucket["skipped"] += 1
                continue
            counts["ran"] += 1
            bucket["ran"] += 1
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(ast.Module([node], []), loc, "exec"), ns)
            except Exception as e:  # noqa: BLE001 — report every failure
                first = seg.strip().splitlines()[0]
                failures.append(f"{loc}+{node.lineno}: {type(e).__name__}: {e} :: {first}")
    if stats is not None:
        stats.update(counts)
    return failures


# Portuguese words that used to stand in for the real keyword (ready(nome=) fails).
_PT_PARAM = re.compile(
    r"\b(nome|nomes|intervalo|alvo|tecla|botão|ângulo|ligado|condição|outro|parte|ponto|cor)\b"
)


# Members the Guia must name, and the card (section or tab) that owns them.
# Engine names kept public on purpose (draw, undraw, update, owner, parts) are
# not required in these cards; the surface test allowlists them.
MEMBER_CARDS = {
    "Vec2": ("geo-vec2", ("cross", "project_onto", "reflect_about", "perp_left", "perp_right", "clamp_length", "to_tuple")),
    "Color": ("aparencia-cor", ("triadic", "analogous", "shades", "contrast_color", "muted_version")),
    "Circle": ("circle", ("from_points", "from_corners", "tangent_lines_from")),
    "Rect": ("shape-rect", ("corners",)),
    "Polygon": ("shape-polygon", ("signed_area", "perimeter_length")),
    "group": ("mundo-grupos", ("union", "as_set", "is_live")),
    "st": ("reativo-state", ("keys", "exists")),
    "clock": ("frame-clock", ("real_time",)),
    "Slider": ("ui-slider", ("percentage",)),
    "DropDown": ("ui-dropdown", ("selected_index",)),
    "TextInput": ("ui-textinput", ("on_submit", "focus", "focused", "max_length", "is_valid")),
}


def _element_by_id(src: str, element_id: str) -> str:
    """HTML of the element that carries ``id``, including nested tags of the same name."""
    m = re.search(rf'<([a-zA-Z0-9]+)[^>]*\bid="{re.escape(element_id)}"', src)
    if not m:
        return ""
    tag = m.group(1)
    depth = 1
    token = re.compile(rf"</?{tag}\b[^>]*>")
    for t in token.finditer(src, m.end()):
        if t.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                return src[m.start():t.end()]
        elif not t.group(0).endswith("/>"):
            depth += 1
    return src[m.start():]


def check_member_cards() -> list[str]:
    """Each listed member must appear inside its own card, not elsewhere in the Guia."""
    src = HTML.read_text(encoding="utf-8")
    errors = []
    for owner, (element_id, names) in MEMBER_CARDS.items():
        card = _element_by_id(src, element_id)
        if not card:
            errors.append(f"{owner}: card #{element_id} não existe")
            continue
        for name in names:
            if not re.search(rf"\b{re.escape(name)}\b", card):
                errors.append(f"{owner}.{name} não aparece em #{element_id}")
    return errors


def check_parameter_keywords() -> list[str]:
    """A Parâmetros: token outside the meaning parentheses must be the real keyword."""
    src = HTML.read_text(encoding="utf-8")
    errors = []
    for m in re.finditer(r"Parâmetros: ([^<]+)", src):
        head = re.sub(r"\([^)]*\)", " ", m.group(1).split(".")[0])
        hits = []
        for piece in head.split(","):
            tok = re.match(r"\s*([A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ0-9_]*)", piece)
            if tok and _PT_PARAM.fullmatch(tok.group(1)):
                hits.append(tok.group(1))
        if hits:
            line = src.count("\n", 0, m.start()) + 1
            errors.append(
                f"html:{line}: Parâmetros usa {hits} no lugar da palavra-chave real"
            )
    return errors


# Objects reachable from ``from scena import *`` whose methods have rows.
_ROW_OBJECTS = (
    "canvas", "group", "ui", "audio", "collision", "st", "clock", "mouse",
    "keyp", "ready", "recently",
)

def _callable_index() -> dict:
    """``name -> [(owner, callable)]`` over the author surface.

    Exported functions and classes, methods of exported classes, methods of
    the global objects and of their public attributes (``canvas.layers``).
    """
    import inspect as _inspect

    scena = _scena()
    index: dict = {}

    def add(name, owner, fn):
        index.setdefault(name, []).append((owner, fn))

    def add_members(owner, obj):
        klass = obj if isinstance(obj, type) else type(obj)
        for name in dir(klass):
            if name.startswith("_"):
                continue
            try:
                attr = _inspect.getattr_static(klass, name)
            except AttributeError:
                continue
            fn = attr.__func__ if isinstance(attr, (staticmethod, classmethod)) else attr
            if _inspect.isfunction(fn):
                add(name, owner, getattr(klass, name))

    for name in scena.__all__:
        obj = getattr(scena, name)
        if _inspect.isroutine(obj):
            add(name, None, obj)
        elif isinstance(obj, type):
            add(name, None, obj)
            add_members(name, obj)
    for oname in _ROW_OBJECTS:
        obj = getattr(scena, oname, None)
        if obj is None:
            continue
        add_members(oname, obj)
        for aname in dir(type(obj)):
            if aname.startswith("_"):
                continue
            try:
                sub = getattr(obj, aname)
            except Exception:
                continue
            if type(sub).__module__.split(".")[0] == "scena" and not _inspect.isroutine(sub):
                add_members(f"{oname}.{aname}", sub)
    layers = getattr(getattr(scena, "canvas", None), "layers", None)
    if layers is not None:
        add_members("canvas.layers[...]", layers["default"])
    return index


def _row_doc_names(text: str) -> list[str]:
    """Leading identifiers of a Parâmetros list: ``a (x), b=1; c`` → a, b, c."""
    text = re.sub(r"\([^)]*\)", " ", text)
    names = []
    for piece in re.split(r"[,;]| ou | e ", text):
        tok = re.match(r"\s*\*{0,2}([a-z_][a-z0-9_]*)\s*(?:=[^,;]*)?\s*$", piece)
        if tok:
            names.append(tok.group(1))
    return names


def check_parameter_rows(src: str | None = None) -> list[str]:
    """Each ``Parâmetros:`` name in a method row is a real parameter.

    The row's first ``<code>`` names the call (``Color.interpolate(…)``,
    ``.reset(…)``). The name must be a keyword of some callable with that
    name on the author surface (restricted to the owner when the row spells
    it). A ``**kwargs`` / ``*args`` callable accepts any name (a positional
    placeholder cannot break a keyword call).
    ``src`` defaults to the Guia (tests pass a planted row).
    """
    if src is None:
        src = HTML.read_text(encoding="utf-8")
    index = _callable_index()
    errors = []
    units = []   # (offset, call html, Parâmetros html or "", names in the call)
    for row in re.finditer(r"<tr>(.*?)</tr>", src, re.S):
        body = row.group(1)
        pm = re.search(r'class="params">Parâmetros:\s*(.*?)</span>', body, re.S)
        cm = re.search(r"<td><code>(.*?)</code>", body, re.S)
        if pm and cm:
            units.append((row.start(), cm.group(1), pm.group(1), False))
    # Signature lines: <p class="sig"><code>remap(value, in_min=0, …)</code></p>
    # and the Parâmetros hint under them. Names inside the call count too.
    for m in re.finditer(
        r'<p class="sig"><code>(.*?)</code></p>\s*'
        r'(?:<p class="sig-hint">Parâmetros:\s*(.*?)</p>)?',
        src, re.S,
    ):
        units.append((m.start(), m.group(1), m.group(2) or "", True))
    for offset, call_html, params_html, is_sig in units:
        call = _html.unescape(strip_tags(call_html))
        m = re.match(r"@?([\w.\[\]\"']*?)\.?(\w+)\(", call)
        if not m:
            continue
        owner, name = m.group(1).split(".")[0].split("[")[0], m.group(2)
        cands = index.get(name, [])
        if owner and any(o == owner for o, _ in cands):
            cands = [(o, f) for o, f in cands if o == owner]
        if not cands:
            continue
        hint = _html.unescape(strip_tags(params_html)).split(". Retorna")[0]
        doc = [d for d in _row_doc_names(hint) if d != "self"]
        if is_sig:
            inside = call[call.index("(") + 1:].split(")")[0]
            doc += [d for d in _row_doc_names(inside) if d != "self"]
        real: set = set()
        loose = False
        for _o, fn in cands:
            params, var_kw, var_pos = real_parameters(fn)
            real |= set(params)
            # **kwargs takes any keyword; *args names are positional
            # placeholders (Color(nome), set_color(cores)) — no keyword to break.
            loose = loose or var_kw or var_pos
        bad = [d for d in doc if d not in real]
        if bad and not loose:
            line = src.count("\n", 0, offset) + 1
            errors.append(
                f"html:{line}: {call[:50]} — Parâmetros cita {bad}, "
                f"que não são parâmetros (reais: {', '.join(sorted(real)) or 'nenhum'})"
            )
    return errors


# Constructor keywords documented once for a whole family (the "todo Shape" /
# "todo widget" / "todo objeto na tela" tables), not in each class's table.
_ROW_SHARED_ALL = frozenset({"layer", "group"})
_ROW_SHARED_SHAPE = frozenset({"color", "visual", "line_width"})
_ROW_SHARED_WIDGET = frozenset({"top_left"})
# Keywords a class publishes only to refuse them with the fix (none today:
# ``Triangle`` refuses ``n=`` without publishing it).
_ROW_REFUSED: dict = {}


def _row_shared(scena, name: str, obj) -> frozenset:
    shared = set(_ROW_SHARED_ALL) | _ROW_REFUSED.get(name, frozenset())
    if isinstance(obj, type):
        bases = {b.__name__ for b in obj.__mro__}
        if issubclass(obj, scena.Shape):
            shared |= _ROW_SHARED_SHAPE
        if "UIWidget" in bases:
            shared |= _ROW_SHARED_WIDGET
        if issubclass(obj, scena.Sprite) and obj is not scena.Sprite:
            # SpriteButton: "Mais os parâmetros do Sprite" — the Sprite table.
            shared |= set(real_parameters(scena.Sprite)[0])
    return frozenset(shared)


def check_constructor_rows(src: str | None = None) -> list[str]:
    """Every keyword of a documented constructor has a row in its section.

    For each ``<p class="sig"><code>Name(…)</code></p>`` naming an exported
    class or function, each public keyword of the real signature must appear
    in the first cell of some row (parameter table or "Modelos de construção")
    between the signature and the end of its section — or be documented once
    for the family (``_row_shared``). The signature line itself does not count:
    ``Texture(…, scale=, tile_size=, …)`` listed knobs the table never explained.
    """
    if src is None:
        src = HTML.read_text(encoding="utf-8")
    scena = _scena()
    errors = []
    # The first <code> of a signature line, never past its </p>.
    for m in re.finditer(r'<p class="sig"><code>((?:(?!</p>).)*?)</code>', src, re.S):
        call = _html.unescape(strip_tags(m.group(1)))
        head = re.match(r"([A-Za-z_]\w*)\(", call)
        if not head or head.group(1) not in scena.__all__:
            continue
        name = head.group(1)
        obj = getattr(scena, name)
        if not callable(obj):
            continue
        real, _kw, _pos = real_parameters(obj)
        end = src.find("</section>", m.end())
        block = src[m.end():end if end > 0 else len(src)]
        cells = re.findall(r"<tr><td[^>]*>(.*?)</td>", block, re.S)
        tokens = set()
        for cell in cells:
            tokens |= set(re.findall(r"[A-Za-z_]\w*", _html.unescape(strip_tags(cell))))
        shared = _row_shared(scena, name, obj)
        missing = [
            p for p in real
            if not p.startswith("_") and p not in tokens and p not in shared
        ]
        if missing:
            line = src.count("\n", 0, m.start()) + 1
            errors.append(f"html:{line}: {name}(…) sem linha para {missing}")
    return errors


_CATALOG_SECTIONS = {sec for _ch, sec, _t, _s in FAMILY_CHAPTER.values()}


def check_symbols_described(symbols: list[dict], bags: dict) -> list[str]:
    """Each non-catalog symbol is named inside the element its anchor points at.

    ``symbols.json`` sends the search box to ``anchor``; a symbol whose anchor
    never spells it (``WaterFill`` → the Visual catalog) was "documented" only
    in the index. The anchor element, or the section around it, must contain
    the name as a word.
    """
    src = HTML.read_text(encoding="utf-8")
    errors = []
    for sym in symbols:
        if sym.get("catalog") or not IDENT.match(sym["name"]):
            continue
        anchor = sym["anchor"]
        block = _element_by_id(src, anchor)
        m = re.search(rf'id="{re.escape(anchor)}"', src)
        if m:
            start = src.rfind("<section", 0, m.start())
            end = src.find("</section>", m.end())
            if start >= 0 and end > 0:
                block += src[start:end]
        text = _html.unescape(strip_tags(block))
        if anchor in _CATALOG_SECTIONS:
            text += CATALOGS.read_text(encoding="utf-8")   # the section renders the catalog
        if not re.search(rf"\b{re.escape(sym['name'])}\b", text):
            errors.append(f"{sym['name']}: a âncora #{anchor} não menciona o nome")
    return errors


def check_spec_blocks_indexed(symbols: list[dict]) -> list[str]:
    """Each ``<summary>canvas.x</summary>`` spec block has a search entry.

    Bug class: ``canvas.fx_quality`` / ``canvas.cull_offscreen`` were
    documented (a spec block, a table row) but missing from ``symbols.json``:
    the search box found nothing for them.
    """
    src = HTML.read_text(encoding="utf-8")
    names = {s["name"] for s in symbols}
    return [
        f"{m}: bloco <summary> sem entrada no índice de busca (CORE_SYMBOLS)"
        for m in sorted(set(re.findall(r"<summary>(canvas\.[a-z_.]+)</summary>", src)))
        if m not in names
    ]


def check_confuse_rows() -> list[str]:
    """Each "Não confundir" row names a real confusion.

    Parece is the mistaken reading, É the correction, Não é the wrong model.
    A note with nothing to confuse belongs in ``<p class="gotcha">``, not in a
    row with Parece "—". Parece must not repeat the start of É, and Não é must
    not be a fragment cut from É (both were left by an old bulk rewrite).
    """
    src = HTML.read_text(encoding="utf-8")
    errors = []

    def plain(x: str) -> str:
        return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", x))).strip()

    for table in re.finditer(r'<table class="confuse">(.*?)</table>', src, re.S):
        for row in re.finditer(r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>", table.group(1), re.S):
            a, b, c = (plain(x) for x in row.groups())
            line = src.count("\n", 0, table.start(1) + row.start()) + 1
            if a in ("—", "-", ""):
                errors.append(f"html:{line}: Não confundir sem Parece — use <p class=\"gotcha\">")
            elif len(a) > 25 and b.startswith(a[:40]) and not a.endswith("…"):
                errors.append(f"html:{line}: Parece repete o começo de É ({a[:40]!r})")
            if c not in ("—", "") and len(c) > 12 and c in b:
                errors.append(f"html:{line}: Não é é um pedaço de É ({c!r})")
    return errors


_NO_PROBE = object()


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def probe_value(value):
    """A value of the same kind as ``value`` but **different**, or ``_NO_PROBE``.

    Writing the current value back is not a test: a setter that skips a
    same-value write passes while refusing every real one (``Entity.id``
    read "lê / escreve" for that reason). Colours flip RGB (stay in 0–1);
    point-likes (``.x`` / ``.y``) shift by one.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0 if math.isfinite(value) else 0.0
    if isinstance(value, str):
        return value + "_probe" if value else "probe"
    if isinstance(value, (set, frozenset)) and all(isinstance(v, str) for v in value):
        return frozenset(value) | {"_probe"}
    if isinstance(value, tuple) and value and all(_is_num(v) for v in value):
        return tuple(v + 1 for v in value)
    rgb = getattr(value, "rgb", None)
    if isinstance(rgb, tuple) and len(rgb) in (3, 4) and all(_is_num(c) for c in rgb):
        return tuple(1.0 - c for c in rgb[:3]) + tuple(rgb[3:])
    x, y = getattr(value, "x", None), getattr(value, "y", None)
    if _is_num(x) and _is_num(y):
        return (x + 1, y + 1)
    composite = _composite_probe(value)
    if composite is not None:
        return composite[0]
    return _NO_PROBE


# A solid colour no background base starts as (default black; guide examples
# use named colours): the probe for a gradient / image / texture base.
_BASE_PROBE_RGBA = (1.0, 0.0, 1.0, 1.0)


def _composite_probe(value):
    """``(probe, restore)`` for Scena composites with no scalar form, else None.

    - ``canvas.background`` reads the live ``BackgroundStack`` but assigning
      replaces its **base**: probe a colour unlike the base, restore the
      original base field (a field written back is kept as-is, identity too).
    - ``.base`` (a ``BackgroundField``): probe a colour unlike its ``source``.
    """
    from scena.background import BackgroundField, BackgroundStack
    if isinstance(value, BackgroundStack):
        base = value.base
        return _composite_probe(base)[0], base
    if isinstance(value, BackgroundField):
        probe = probe_value(getattr(value, "source", None))
        if probe is _NO_PROBE or isinstance(probe, str):
            probe = _BASE_PROBE_RGBA
        return probe, value
    return None


def _restore_value(value):
    """What to write back afterwards: a point-like may be live (``c.center is``
    the shape's own Point), so the probe write moves it — keep its coordinates.
    A background stack is live too — keep its base field."""
    x, y = getattr(value, "x", None), getattr(value, "y", None)
    if _is_num(x) and _is_num(y) and getattr(value, "rgb", None) is None:
        return (x, y)
    composite = _composite_probe(value)
    if composite is not None:
        return composite[1]
    return value


def probe_writable(obj, name):
    """True: ``obj.name`` takes writes. False: read-only. None: cannot tell.

    Writes a *different* value (``probe_value``), then restores the original
    so shared objects (``clock``, ``canvas``) stay as they were. A value with
    no known different form falls back to writing itself back (none left in
    the Guia's pool; ``TestGuiaAccessProbe`` keeps it that way).
    """
    try:
        value = getattr(obj, name)
    except Exception:
        return None
    if value is None or (callable(value) and not isinstance(value, (int, float))):
        return None
    probe = probe_value(value)
    if probe is _NO_PROBE:
        probe = value
    restore = _restore_value(value)
    try:
        setattr(obj, name, probe)
    except Exception as exc:
        # AttributeError / DerivedAttributeError = read-only. Anything else
        # (TypeError / ValueError on this value, LinkedAttributeError) means
        # the field takes writes and only this value or state was refused.
        # A setter that refuses with "read-only" in a TypeError (Handle.u) is
        # read-only too, whatever the exception class.
        return not (isinstance(exc, AttributeError) or type(exc).__name__ == "DerivedAttributeError"
                    or "read-only" in str(exc))
    if probe is not value:
        try:
            setattr(obj, name, restore)
        except Exception:
            pass
    return True


# Section (or tab) id -> the object its "Neste …" tables describe.
_ACCESS_SECTION_OBJECTS = {
    # Several models where a field is writable in one and derived in another.
    "shape-rect": ("Rect(center=(0, 0), width=10, height=10)", "Rect(top_left=(0, 0), width=10, height=10)",
                   "Rect(p1=(0, 0), p2=(10, 10))"),
    "shape-square": ("Square(center=(0, 0), length=10)", "Square(top_left=(0, 0), length=10)"),
    "shape-line": ("Line(p1=(0, 0), p2=(10, 0))", "Line(center=(0, 0), length=10, angle=0)"),
    "shape-ellipse": ("Ellipse(center=(0, 0), width=10, height=6)",),
    "shape-polygon": ("Polygon(points=[(0, 0), (10, 0), (0, 10)])",),
    "shape-regular": ("RegularPolygon(n=5, center=(0, 0), radius=10)",),
    "shape-triangle": ("Triangle(center=(0, 0), radius=10)",),
    "shape-point": ("Point(0, 0)",),
    "desenhar-track": ("Track.circle(radius=50)", "Track(points=[(0, 0), (50, 0), (50, 50)])"),
    "desenhar-text": ("Text('hi')", "Text('hi', top_left=(10, 10))"),
    "desenhar-history": ("History(max_points=3)",),
    "contrail": ("Contrail(max_points=3)",),
    "agendar-handle": ("Circle(center=(0, 0), radius=5).move_along('circle', time=1)",),
    "colocar-box": ("Box(center=(0, 0), width=10, height=10)",),
    "geo-vec2": ("Vec2(1, 2)",),
}


def check_access_column(src: str | None = None) -> list[str]:
    """A property the Guia marks "lê / escreve" must accept a write.

    Builds one object of each author type, then for every row whose access
    cell is "lê / escreve" writes a different value of the same kind
    (:func:`probe_writable`) on each object that has the field, and restores
    it. If every such object refuses, the row should say "leitura"
    (``canvas.zoom`` once read "lê / escreve" while the engine said
    "read-only; use zoom_to"). Methods (a ``(`` in the name cell) and
    parameters (``name=``) are not fields and are skipped.
    """
    scena = _scena()
    import warnings
    warnings.simplefilter("ignore")
    ns = {n: getattr(scena, n) for n in scena.__all__}
    if src is None:
        src = HTML.read_text(encoding="utf-8")

    def plain(x: str) -> str:
        return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", x))).strip()

    def make(expr):
        try:
            return eval(expr, dict(ns))
        except Exception:
            return None

    scena.canvas.layers.clear(hard=True)
    named = {k: ns[k] for k in ("canvas", "clock", "mouse", "audio", "keyp", "st", "collision", "ui") if k in ns}
    exprs = [
        "Circle(center=(0, 0), radius=10)", "Rect(center=(0, 0), width=10, height=10)",
        "Square(center=(0, 0), length=10)", "Line(p1=(0, 0), p2=(10, 0))",
        "Ellipse(center=(0, 0), width=10, height=6)", "Polygon(points=[(0, 0), (10, 0), (0, 10)])",
        "RegularPolygon(n=5, center=(0, 0), radius=10)", "Triangle(center=(0, 0), radius=10)",
        "Point(0, 0)", "Sprite('x.png')", "Track.circle(radius=50)", "Text('hi')", "Entity()",
        "History(max_points=3)", "Contrail(max_points=3)", "Box(center=(0, 0), width=10, height=10)",
        "Color('red')", "Gradient('sunset')", "Palette('plasma')", "Vec2(1, 2)",
        "Circle(center=(0, 0), radius=5).move_to(5, 5, time=1)", "Sprite('x.png').add_hitbox(group='zz')",
        "canvas.layers", "canvas.background", "canvas.effects", "canvas.playfield", "Attribute(0.0)",
    ]
    pool = [o for o in (make(e) for e in exprs) if o is not None] + list(named.values())

    # A row inside one of these sections speaks of that section's object only:
    # ``.length`` in Track's table is Track.length, not "any object with a
    # length". Probing the whole pool let a read-only row pass because some
    # other type (Line.length) accepted the write.
    section_objs = {}
    for sec, exprs_ in _ACCESS_SECTION_OBJECTS.items():
        objs_ = [o for o in (make(e) for e in exprs_) if o is not None]
        if objs_:
            section_objs[sec] = objs_
    anchors = [(m.start(), m.group(1)) for m in re.finditer(r'\bid="([^"]+)"', src)
               if m.group(1) in section_objs]

    def section_obj(offset):
        owner = None
        for pos, sec in anchors:
            if pos > offset:
                break
            owner = section_objs[sec]
        return owner

    errors = []
    row_re = re.compile(r'<tr><td>((?:(?!</td>).)*)</td><td class="type">(?:(?!</tr>).)*?</td><td>lê / escreve</td>', re.S)
    for m in row_re.finditer(src):
        cell = plain(m.group(1))
        if "(" in cell or cell.rstrip().endswith("="):
            continue
        head = cell.split("=")[0]
        verdicts = []
        owner_objs = None   # ``mouse.x / .y``: ``.y`` belongs to mouse too
        local = section_obj(m.start())
        for path in re.findall(r"\.?[A-Za-z_][A-Za-z0-9_.]*", head)[:4]:
            shorthand = path.startswith(".")
            parts = [p for p in path.split(".") if p]
            if not parts:
                continue
            nm = parts[-1]
            if parts[0] in named:
                if len(parts) == 1:
                    continue
                obj = named[parts[0]]
                try:
                    for p in parts[1:-1]:
                        obj = getattr(obj, p)
                except Exception:
                    continue
                objs = [obj]
                owner_objs = objs
            elif shorthand and owner_objs is not None:
                objs = owner_objs
            elif local is not None and any(hasattr(o, nm) for o in local):
                objs = local
            else:
                objs = pool
            seen = [w for w in (probe_writable(o, nm) for o in objs) if w is not None]
            if seen:
                verdicts.append(all(w is False for w in seen))
        if verdicts and all(verdicts):
            line = src.count("\n", 0, m.start()) + 1
            errors.append(f"html:{line}: {cell[:50]!r} está como lê / escreve, mas nenhum objeto aceita escrita — use leitura")
    scena.canvas.layers.clear(hard=True)
    return errors


def main() -> int:
    bags = load_catalogs()
    # First: a catalog the browser cannot parse leaves the Guia with no catalog.
    errors = check_catalog_js(CATALOGS, bags)
    errors.extend(check_catalog_js_engine(bags) or [])
    errors.extend(validate_catalogs(bags))
    thumb_errors, thumb_warnings = check_thumbs(bags)
    errors.extend(thumb_errors)
    errors.extend(check_variant_choices(bags))
    symbols = catalog_symbols(bags) + core_symbols()
    # de-dupe by (name, anchor)
    seen = set()
    uniq = []
    for s in symbols:
        key = (s["name"], s["anchor"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    write_symbols(uniq)
    warnings = check_public_vs_all() + thumb_warnings
    anchor_errors = check_anchors(uniq, bags)
    errors.extend(anchor_errors)
    errors.extend(check_symbols_described(uniq, bags))
    errors.extend(check_spec_blocks_indexed(uniq))
    sig_errors, gaps = check_catalog_signatures(bags)
    errors.extend(sig_errors)
    errors.extend(check_parameter_keywords())
    errors.extend(check_parameter_rows())
    errors.extend(check_member_cards())
    errors.extend(check_confuse_rows())
    examples = collect_examples(bags)
    errors.extend(check_examples_compile(examples))
    # A public knob the card omits is an undocumented parameter: an error.
    errors.extend(f"lacuna: {g}" for g in gaps)
    errors.extend(check_constructor_rows())
    if "--examples" in sys.argv:
        stats: dict = {}
        errors.extend(run_examples(examples, stats))
        errors.extend(check_access_column())
        ran, skipped = stats["ran"], stats["skipped"]
        total = ran + skipped
        pct = 100 * skipped / total if total else 0
        print(f"exemplos: {ran} instruções executadas, {skipped} puladas ({pct:.0f}%)")
        worst = sorted(
            stats.get("sections", {}).items(),
            key=lambda kv: kv[1]["skipped"],
            reverse=True,
        )[:8]
        for sec, bucket in worst:
            print(f"  {sec}: {bucket['ran']} ran, {bucket['skipped']} skipped")
    print(f"{len(uniq)} símbolos → {SYMBOLS_JSON.name}, {SYMBOLS_JS.name}")
    for w in warnings:
        print("aviso:", w)
    if errors:
        print(f"{len(errors)} erro(s):")
        for e in errors:
            print(" ", e)
        return 1
    print("catálogo ok; âncoras ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
