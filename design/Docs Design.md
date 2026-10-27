# Docs Design

How the author site is written and kept in step: the API Guide
(`docs/en/guide/`), the Portuguese Guia it mirrors (`docs/pt/guide/`, written
first), the English tutorials and their Portuguese twins, and the checks that
hold them. Hub: [README.md](README.md). The landing page, its clips and videos:
[README Media.md](README%20Media.md).

| Goal | Go to |
| --- | --- |
| Section shape, ids, vocabulary, Leitura/Escrita, parameter rows, catalogs, thumbnails | [Editing the Guia](#editing-the-guia) |
| Keep the English Guide in step with the Guia | [The English Guide](#the-english-guide) |
| Keep an English tutorial in step with its Portuguese twin | [The English tutorials](#the-english-tutorials) |
| Titles, descriptions, hreflang, sitemap, link preview image | [Search and link previews](#search-and-link-previews) |

## Editing the Guia

- **Section shape.** Concrete code first, then the reference (`details` tables). A
  subject with several questions gets one section per question ("Como fazer"),
  in the order an author meets them — basic before advanced. Parameters shared by
  many verbs live in one place (e.g. [Time parameters (`time=`)](../docs/en/guide/index.html#suite));
  a verb's table lists only its own knobs.
- **Ids are stable.** Other chapters, the Design docs and `validate_guia.py`
  (search index) link them. Moving content keeps the old id on the new home
  (a section, a tab panel, a `details`); the Guia opens the tab that holds it.
  Per-subject layouts: [Sprite Design.md — Guia layout](Sprite%20Design.md#author-surface-guia-layout).
- **"Não confundir" rows** are Parece (the wrong reading) · É (the fix) · Não é
  (the wrong model). A note with nothing to confuse is `<p class="gotcha">`.
  `validate_guia.py` rejects a row with Parece "—", a Parece that repeats the
  start of É, and a Não é cut out of É.
- **Vocabulary (English, `you`).** The English Guide uses the same canonical
  terms as the Guia, defined once in its
  [Vocabulary](../docs/en/guide/index.html#vocabulario) section (the same
  `#vocabulario` id):
  *design units* / *units* (never "DU", "pixels" or "points"), *frame*,
  *Entity*, *Graphic*, *object* (never "drawable" / "actor"), *pose*, *point*
  (any place the API takes; never "point-like"; `Point` in code is the class),
  *field* (never "cell"), *link* / *linked* (`@=`), *task* (never "job"),
  *held* / *on the frame it is pressed* (never "edge"), *channel* only for
  transients, *stage* (palco; always lowercase — capitalized "Stage" is the old
  package name, which `test_message_vocabulary` refuses), *a world with a floor*, *place* × *travel*.
  Engine messages use the same words, since the Guide quotes them exactly:
  `test_message_vocabulary` refuses "actor" and a field called "cell" in
  `scena/` (sheet, grid and Endless cells are real cells).
  "Qual usar" says code runs as a *formula*, a *check* (pergunta) or an
  *event* (aviso); work that takes time is a *process* with an *owner*. A stamp
  is an *add-on* (section "Add-ons"). Jargon gets plain English: bake → *compute*
  (a computed hitbox), sugar → *shortcut*, knob → *parameter* / *setting*, ink →
  *own field*, no-op → *does nothing*, interned → *shared*; *park*, *one-shot*
  and *escape hatch* stay. Fixed labels: `Parameters:`, `Returns`,
  `read / write` · `read` · `read-only`, "Don't confuse" (Looks like · It is ·
  It is not), "How to", "Reading the parameters", "See X" / "More in X",
  "<X> reference" (the `<summary>Neste X</summary>` tables), "Constructor",
  "Construction models", "Call", "Contract", "Topic / Rule", "Signature",
  "No parameters", "Waits (use await)", "Where else to look".
  Spelling is American, matching the API (`color`, `center`, `gray`; but
  *cancelled*, like `Cancelled` and `.cancelled`). Example
  code is translated (variables, strings, comments); API names and API string
  values (`"cyan"`, `style="fade"`) are not.
- **Vocabulary (PT-BR, `você`).** Keep dev jargon Brazilians use (frame, sprite,
  clip, hitbox, slot, preset, HUD, zoom); do not calque English. Bake → *calcular*
  (hitbox calculado), sugar → *atalho*, knob → *parâmetro* / *ajuste*, ink →
  *campo próprio*, park → *estacionar*, no-op → *não faz nada*, overlap →
  *sobreposição*, one-shot → *pontual*, escape hatch → *recurso de exceção*,
  interned → *compartilhado*, stamp (`.glow` / `.shadow` / `.hue` / `.tail`) →
  *complemento*, costume (`.visual`) → *visual*. API names stay as written
  (`Sound.bake`); ids stay too (`#aparencia-selos` holds "Complementos").
  The canonical terms are defined once in the Guia's
  [Vocabulário](../docs/pt/guide/index.html#vocabulario) section; use them and
  nothing else: *unidades (de design)* (never "DU"; not "pontos" — *ponto* is a
  place), *frame* (never "tick"), *Entity* (any game object), *Graphic* (Shape,
  Sprite, Text — the error messages' word), *objeto* in plain prose (never
  "drawable" / "ator"), *ponto* (any place the API accepts: tuple, Point, Vec2,
  Graphic, `mouse`; never "ponto-like"), *campo* (never "célula" for an
  Attribute), *tarefa* (never "job"), *segurando* / *no frame do aperto* (never
  "borda" for a key edge), *canal* only for transients, *palco* (the top of the
  file, which lasts the whole game). Engine words a beginner
  cannot know (MTV, AABB, EMA, SDF, manifold, blit, broad-phase, Derivate,
  Container) are explained in plain words, not used as labels.
- **Open with what it is.** A section's first sentence says what the feature is
  and what it is for, in words a first-time reader knows ("A câmera escolhe que
  parte do mundo aparece na janela…"). Negations and contrasts with other
  features come after, never first. Catalog sections carry a "Como ler os
  parâmetros" note (what `amount` / `speed` / `color` mean there) so each card's
  meaning column can stay short without being a bare noun.
- **Leitura/Escrita column** says what the author may do. A field the engine
  refuses to write is *leitura*; a method is *método*; a keyword is *parâmetro*.
  `validate_guia.check_call_access_rows` rejects a row that names a call
  (`.spectrum(bins=8)`) and says "lê / escreve" (it skips nothing else, so it
  runs without `--examples`).
  `validate_guia.py --examples` writes a **different** value of the same kind
  on real objects (`probe_value`: bool flipped, number +1, colour inverted,
  point shifted), restores the original, and rejects a "lê / escreve" row that
  nothing accepts. Writing the current value back proved nothing: the old `.id` passed
  that way while every real write raised, because its setter skipped same-value
  writes. `AttributeError` (or `DerivedAttributeError`) on the probe means
  read-only; any other error (`ValueError`, `TypeError`, a linked field) still
  counts as writable — the field takes writes, just not that value.
  Composites get a real probe too (`_composite_probe`): `canvas.background`
  and `.base` get a colour unlike the current base, and the original base field
  is restored (same object). A value with no known "different" form would fall
  back to writing itself back; none is left in the audit's pool, and
  `test_api_robustness.TestGuiaAccessProbe` fails if one appears — add a probe
  for the new kind rather than accepting the fallback.
- **Parâmetros names are keyword names.** A `Parâmetros:` row and a
  `<p class="sig">` line spell the real parameter (`remap(value, in_min, …)`,
  `with_alpha(alpha)`), not a Portuguese placeholder: an author copies them
  as keywords. `validate_guia.check_parameter_rows` compares each against the
  signature; only `*args` callables may use a placeholder (`Color(nome)`).
  `check_parameter_keywords` also rejects the placeholder words in
  `validate_guia.WORDS` (`segundos`, `nome`, `cor`…; English `seconds`,
  `name`…) unless the call that same row names really takes that keyword
  (`keyp(key)`): `Parâmetros: segundos` stood for `wait(delay)` while a
  keyword-loose `after` hid it from the signature check.
- **Every keyword has a row.** `validate_guia.check_constructor_rows`: each
  public keyword of a documented constructor (`<p class="sig"><code>Name(…)`)
  needs a row in that section, unless the family documents it once (`layer=` /
  `group=` in "Todo objeto na tela", `color=` / `visual=` / `line_width=` in
  "todo Shape", `top_left=` in "todo widget"). The signature line alone does not
  count — `Texture(…, scale=, tile_size=, shift=)` once listed knobs no row
  explained. Catalog cards: a public knob the card omits is an **error**
  (`check_catalog_signatures` gaps; shared `layer` / `group`, and `soft_edge` on
  SpatialFx, are documented in the section). `real_parameters` reads the
  class's published `__signature__` too — `Fire(angle=, rate=, tongues=)` was
  invisible to the gap check before.
- **Code in `<pre>` runs.** `python tools/guide/validate_guia.py --examples` executes every
  block; make each one self-contained (create the group members, clips, `st`
  cells, … it reads). Each block gets a fresh `st`, so a fragment never leans
  on a cell an earlier chapter made: chapters can move. The page highlighter
  handles quotes inside comments.
- **Catalog JS must parse.** `guia-api-catalogs.js` is data the page runs: one
  stray bracket makes the file invalid and the Guia shows **no catalog at all**
  (the page has no error UI). `validate_guia.check_catalog_js` reads it as a JS
  parser would (first mismatch as `file:line:col`, card count per bag vs the
  checker's own reader) and, when `node` / `jsc` is installed, runs it.
  Keep card fields in the order `id, kind, family, name`.
- **Catalog thumbnails are generated, never drawn.** `python tools/guide/make_guia_thumbs.py`
  renders each Visual / SpatialFx / Post / Impactos / Backgrounds / Transientes card from
  its own `code:` (in `docs/assets/thumbs/`: `<id>.webp` poster; `<id>.anim.webp` 2 s loop when the
  card *moves* — measured, not guessed from its kind; `<id>.card.webp` gallery
  picture; `guia-api-thumbs.js` for the pages of every language).
  - **Same pixels as the screen.** It draws on the GPU through a hidden window
    (the `run()` context); `--cpu` is the raster fallback for machines without a
    display. Post / background scenes are a normal window (1000×625 design) drawn
    at 1440×900 and reduced 3:1: post FX run at ½–¼ of the framebuffer, so a
    thumbnail-sized one is blocky. Reductions never use a cubic filter (it skips
    1–2 px stars): post / looks average each block, SpatialFx keep small lights
    ("detail"), fields keep each block's brightest pixel ("max") — a star field
    averaged down is a flat dark plate.
  - **Scenes.** Post and Impactos: `examples/media/images/bg1.jpeg` as a cover
    wallpaper and nothing else (effects act on a real picture; a shake of a flat
    color changes nothing). Looks / transients: the hero's outline is
    `fill.darker(0.35)`. One-shot verbs (Transientes, Impactos) fire 0.25 s into
    the loop and are captured at 30 fps — a 0.12 s flash falls between two 12 fps
    frames. A transient's poster is the peak when the peak shows something, else
    the middle of the action (blink off, burn / dissolve / fade).
  - **Real scale, then zoom.** Glow sigma, rims and strokes are design units.
    A look is shown on a shape of the size authors use (radius 26,
    `line_width` 2, a vivid color — the smoke scripts' range) in a 128×80 design,
    zoomed; a big shape in a wide frame turns every look into a thin line.
    SpatialFx sizes are absolute too: a first pass renders the effect zoomed out
    on its `_domain_aabb` (a directed fire is width × length, not `radius`) and
    records the box of every pixel it touches; the real pass frames that box. A
    box taller than 1.25× its width gets the portrait preset (300×480) — flames
    and jets are not cropped — measured again in the portrait design, because an
    effect placed by default sits at *that* design's center.
  - **Gallery pictures** are reduced from the full render (the browser shrinking
    the 480 px poster to a 160 px card erased stars again). Ambient fields'
    gallery pictures lift the light above the base color (≤ 2.5×) until the
    brightest detail reads; base fields (sky, wallpaper) are never lifted, and
    the panel poster is never lifted. Portrait pictures keep their shape in the
    panel and sit inside the 16:10 gallery / variant tiles.
  - **Staleness** hashes the inputs (snippet, scene preset, render settings,
    parameter defaults, the source of the class the card names) in
    `docs/assets/thumbs/manifest.json`; `validate_guia.py` warns about stale / missing ones
    and errors only when the page data names a card or file that does not exist.
    Shared engine code is not in the hash: after an engine fix that changes looks,
    run with `--force`. Changing a scene → bump its `"v"` in `SCENES`; size /
    timing → `RENDER_VERSION`.
  - **Card knobs:** `thumb: "…"` (the snippet to render when the first statement
    of `code:` is a bad picture; scene names `x`, `y`, `W`, `H` keep it relative),
    `thumb: false` (nothing to see: `clear_transients`), `anim: false` (keep a
    still for a card that moves) / `anim: true` (fail unless it moves), and
    `variants: "style"` (or `"fold, edge"`): one picture per value of that
    parameter, shown as a strip in the card's panel. The values come from the
    **code** — the card's call is made with a value nobody uses and the friendly
    `ValueError` lists the real choices — and `validate_guia.check_variant_choices`
    fails when the card's `P(...)` row lists a different set. A variant equal to
    the card's own snippet shares its files.
  - **Guards:** a card that renders nothing visible fails; hit cards
    (`canvas.flash`, `zap_at`, …) use their peak frame as the poster.
  - **Page:** each such catalog has a **Galeria / Abas** toggle (remembered per
    catalog, in the browser's storage); a link to a card, or a click on a
    gallery card, opens Abas *for now* — only the toggle is remembered, or one
    card read hides that catalog's gallery on every later visit in that
    browser. A loop plays by itself in the active
    panel (or under the pointer in the gallery) unless the system asks for
    reduced motion; its ▶ / ❚❚ button always works — reduced motion stops
    autoplay, not an animation the reader asked for. Attribute values go
    through `escAttr` (a variant's code has quotes).

## The English Guide

The English Guide mirrors the Portuguese one **unit by unit**, and
`tools/guide/guia_parity.py` keeps the two in step (`tests/test_guia_parity.py`
runs its check in `quick`).

- **Where.** `docs/en/guide/index.html` next to its own
  `guia-api-catalogs.js` (it was written as `draft.html` with `noindex` until
  every unit was translated, and published on 2026-10-22). Thumbnails are
  shared, and their freshness is always asked of the Portuguese cards (the
  English cards translate prose defaults, which are inputs of the picture's
  hash). Each page's sidebar has a `.lang-switch` link to the other language
  that carries the hash over: the ids are the same, so the reader stays on the
  section (`tests/test_guia_parity.py`, `TestPublishedGuides`).
- **Units.** For the page: `head`, `style`, `body`, `nav`, `top`, one
  `chapter:<id>` per chapter head, one unit per `<section id>`, and `tail` (the
  scripts). For the catalog file: `js:head`, `js:<BAG>` / `js:<BAG>:end`, one
  `card:<id>` per card, and `js:render`. A unit is **pending** (the English file
  holds the Portuguese text) or **translated**: `tools/guide/guia_en_state.json`
  records the hash of the Portuguese text it was translated from. `style` is
  never marked, so CSS always comes from Portuguese.
- **A Portuguese edit to a translated unit fails the check** until the English
  follows. `guia_parity.py --diff <unit>` shows what changed; translate it, then
  `--mark <unit>`. An edit to a pending unit is never an error: the check
  reads pending units from the Portuguese file, and `--sync` writes them into
  the English file.
- **What must match.** Ids, in the same order: links, the language switch and
  these docs use them, so ids stay Portuguese in both pages. Per unit: the
  `<pre>` blocks and the Scena names each one uses, `details`, table rows,
  "Não confundir" tables, headings, signature lines. Per card: id, kind,
  family, name, variants, thumb, parameter names and slots, literal defaults,
  and the Scena names in `code`. Variable names, strings and comments in
  examples are translated (`nave` → `ship`). `--examples` runs each page's
  code with its own names: the sample level is written per language
  (`validate_guia._LEVEL_NAMES_EN`: `fase1.json` / `level1.json`,
  `"elevador"` / `"elevator"`…), so an English example reads English names.
  A new name that is a Scena name (`level`, `wave`, `box`) fails the parity
  check; pick another word.
- **No Portuguese left.** A translated unit may not hold Portuguese prose. A
  term quoted on purpose goes in `<span lang="pt">…</span>`.
- **The validator in English.** `python tools/guide/validate_guia.py --lang en`
  runs the same checks on the English page. The words they match (`Parameters:`,
  `Returns`, `read / write`, list joins, placeholder names) live in
  `validate_guia.WORDS`. The English search index text (chapter and section
  titles, type words, the core symbols' one-liners) lives in
  `tools/guide/guia_text_en.json`. A missing one-liner is left empty, never
  Portuguese, and the validator lists it.
- **Vocabulary.** "Vocabulary (English, `you`)" above. A term a chapter needs
  that the list lacks is added there first, then used.

## The English tutorials

Each English tutorial page mirrors one Portuguese page **step by step**, and
`tools/tutorial/tutorial_parity.py` keeps the two in step
(`tests/test_tutorial_parity.py` runs its check in `quick`). Every check of
`tests/test_tutorials.py` and every step run of `tests/test_tutorial_steps.py`
covers the English pages too (`TestStepsEn05` is page 05 in English).

- **Two programs, one design.** The Portuguese code keeps Portuguese names
  (they tell a beginner what is theirs and what is Scena's); the English code
  is the same program with English names, not a second design.
  `code_parity` pairs every code block of a page with its twin under **one
  one-to-one rename for the page**: names, and word-like strings (group, clip
  and act names). Comments, docstrings and the text of display strings
  (`f"Pontos: {n}"` → `f"{n} points"`) are free; numbers, structure, imports
  and file names are not (an English file name must be a file that exists:
  the English level files). An English name may not land on a Scena export or
  a builtin, nor, for a `def` or an attribute, on a member of the API
  (`def atualiza` → `def update` would turn into a hook; `self.pontos` →
  `self.points` on a Sprite would hide a member). A field of `st` is free.
- **Where.** Pages live in `docs/en/tutorial/`, paired by the key before the
  first `-` of the file name (`05-naves.html` ↔ `05-ships.html`), and listed
  in `docs/en/tutorial/index.html` (published 2026-10-24, 0.10.0). **The head
  follows the state:** a page whose units are all translated has no
  `noindex`, and the twins name each other with `<link rel="alternate"
  hreflang=…>`, which `tutorial.js` draws as the language switch (it keeps
  the step: `#n`); a page with a pending unit keeps `noindex` and its
  Portuguese twin does not link to it; the two indexes name each other.
  `--mark` and `--publish` write those lines (`sync_heads`), the check fails
  when a page disagrees (`head_errors`), and the unit hashes leave them out,
  so publishing changes no translation state. A new page goes through
  `--draft` (pending, hidden) like the first 44. The English examples sit **next to the
  Portuguese ones in `examples/`** under English names (the engine finds media
  next to the script or in its `media/`, so an `examples/en/` folder would
  need a second search place, a link or a copy of the media); an English page
  whose `example:` keeps the Portuguese file name fails the check.
- **Level files are made, not written.** `names_en.json` "levels" pairs each
  Portuguese level file with its English twin (`levels/ninja.json` ↔
  `levels/ninja_world.json`) and the page whose glossary renames it.
  `tutorial_parity.py --levels` writes the twin: the Portuguese file with its
  groups, item names and sheet names renamed, in the editor's own layout
  (`scena.level_format.dumps`, which round-trips the files byte for byte). The
  check fails while a twin lags its Portuguese file or a level word has no
  English; `--draft` renames the `Level("levels/…")` paths.
- **The engine's own words** (buttons, box titles: "Your turn", "What we
  covered") come from `WORDS` in `docs/assets/tutorial/tutorial.js`, chosen
  by the page's `<html lang>`; an English page must say `lang="en"`.
- **Units.** `<key>:head` (up to the steps), one `<key>:<n>` per step object,
  `<key>:tail`. A unit is **pending** or **translated**
  (`tools/tutorial/tutorial_en_state.json` records the hash of the Portuguese
  text it was translated from). The code parity and the step shape (fields,
  code blocks, notes, snippets, items, recap and explore items, the same Guia
  links) hold for pending units too; a translated unit must also have no
  Portuguese left (prose, comments, docstrings) and its Portuguese must not
  have changed since (`--diff <unit>`, translate, `--mark <unit>`).
- **Glossary.** `tools/tutorial/names_en.json`: `pages` (key → English page
  file), `examples` (Portuguese example → English example), `titles` (key →
  English title), `series` (pages that share one English name per Portuguese
  name: `nave` → `ship` in every Naves tutorial; the `core` series, pages
  `"*"`, holds the names many pages share, and a later series overrides it for
  its pages). The page's rename must agree with it. `--names` leaves out what
  the engine owns (keys, colors, members, and any word the engine's code
  spells in quotes, `"ease_out"`) and the text of f-strings, which is free.
- **Method.** `--names <key>` lists the names and word-like strings a page
  needs (once the page exists, its rename); the glossary gets them, series by
  series. `--draft <key>` writes the English page from the Portuguese one with
  `lang="en"`, `noindex`, the English example name, and every code block,
  snippet, note anchor, `focus` / `replaces` anchor and inline `<code>`
  renamed by the glossary (one scanner for all of them, so a note still finds
  its line; inside a quoted field, `\"` quotes are read as quotes). Then the
  prose, comments, docstrings and player-facing text are translated,
  `--ready <key>` checks the page as if marked, and the units are marked.
  Translating finds Portuguese that is wrong (tutorial 01 said "about seventy"
  color names; there are over a hundred): fix the Portuguese, then mark.

## Search and link previews

Every page's `<title>` and a marked block right after it (`<!-- site head
(tools/site/seo.py) -->` … `<!-- /site head -->`) are written by
`tools/site/seo.py`, never by hand; so is `docs/sitemap.xml`. Run
`python tools/site/seo.py` after adding, renaming or publishing a page, or
after changing a tutorial's title or its card in the index; `test_site_seo`
fails while one lags.

- **What the block holds.** A description, the canonical address (a folder's
  `index.html` is the folder: `…/Scena/en/guide/`), absolute `hreflang` links
  to both twins plus `x-default` (the English page), and the link preview
  (`og:*`, `twitter:card`, the image `docs/assets/og/scena.png`, 1200 × 630,
  made by `tools/site/make_og_image.py` from two README clips).
- **Where the text comes from.** A tutorial's title is its `Tutorial.mount`
  title plus a tail ("Ships — Scena tutorial · 2D games in Python"), its
  description its card in the language's index plus one sentence. The home,
  the indexes and the Guides have fixed text in `FIXED` (in `seo.py`).
  `tutorial.js` keeps the head's title.
- **Two writers, one head.** `tutorial_parity.py --publish` owns the relative
  twin link right after `<meta charset>` (which `tutorial.js` draws as the
  language switch, picking the first alternate link that is not absolute);
  `seo.py` owns the absolute ones. Each tool leaves the other's lines alone
  (they once both matched every `hreflang` line).
- **Hashes.** The translation hashes (`guia_parity.digest`, used by both
  parity tools) leave out the `<title>` line and the block: the title is made
  from the mount title, which is hashed, and the rest is made from the page.
  Without that, rewriting the heads marked every English tutorial pending.
- **Hidden pages** (`noindex`) get a title and a preview but no canonical, no
  `hreflang`, and no sitemap entry; the twin of a hidden page names none
  either. The two redirect pages (`docs/<lang>/index.html`) are left as they
  are.
- **No robots.txt.** Crawlers read it only at the host root
  (`accmota.github.io/robots.txt`), which this project site does not own; a
  copy in `docs/` would be ignored. With none, everything may be crawled. The
  sitemap is submitted in Google Search Console and Bing Webmaster Tools.
