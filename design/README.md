# Scena design docs

How the framework works and why: architecture, invariants, fences, the test
strategy. For contributors (people and agents). Authors read the Guia and the
tutorials in [`docs/`](../docs/index.html).

Reading order:

1. **[Scena Design.md](Scena%20Design.md)** — start here. Jump box first (code map / frame / API / intent), then product **Context**, then architecture (subsystems, data model, datapath). Happy path only. Companions are a menu, not a reading list.
2. **[Guia da API](../docs/pt/guide/index.html)** — author-facing API reference (PT-BR; the English Guide will sit in `docs/en/guide/`).
3. Named `* Design.md` companions — subsystem depth when you need it. Open **one**.

Design docs describe **current understanding**, not a freeze. Full statement: [Design documents are descriptions, not locks](Scena%20Design.md#design-documents-are-descriptions-not-locks). The API is published (since 0.6.0): a change that breaks author code is weighed against its cost and follows [Compatibility and versions](Scena%20Design.md#compatibility-and-versions).

## Use (agents)

Same protocol as [Scena Design.md — Appendix](Scena%20Design.md#appendix-module-map):

1. Open Scena Design. Pick one router row.
2. Open **Start** only (search; do not slurp fat files).
3. Open the matching companion **only if** invariants are unclear — then pick **one** jump-box row in that companion; do not read the rest.
4. Treat **fences in that section** as current constraints (same weight as invariants).
5. Stop. Do not ingest other companions, `scripts/`, `_sksl_*`, or the private `workbench/` unless that is the task.
6. **[Laws.md](Laws.md)** is short: read it **whole** before changing frame order, lifetime, contacts, input ownership or timers. A change that breaks a law is a design change: the law, its model (`tests/laws/model/`) and the companion doc change with it.
7. **[Fences.md](Fences.md)** is not a reading list. Open it only when proposing API sugar, a second spelling, or a silent rewrite. Do not invent API a fence forbids without evidence matching the revisit bar.

## Live docs


| Doc | Role |
| --- | --- |
| [Scena Design.md](Scena%20Design.md) | Context + architecture hub |
| [Guia da API](../docs/pt/guide/index.html) | Author API (reference). Look catalogs (Visual, SpatialFx, Post, Backgrounds) carry generated thumbnails. |
| [Shapes Design.md](Shapes%20Design.md) | Shape geometry, models, CTM draw |
| [Tracks Design.md](Tracks%20Design.md) | `Track`, `move_along`, presets, overlay |
| [History Design.md](History%20Design.md) | `History` add / snapshot, `Contrail` stroke recipe |
| [Reactive Design.md](Reactive%20Design.md) | Container / Attribute / pull graph |
| [Actors Design.md](Actors%20Design.md) | Entity, process, groups, ink, modes |
| [Act Design.md](Act%20Design.md) | Acts (`Act`, `change_act`, `run(Titulo)`): title → level → game over without a reset list; what an act change removes / restores / keeps |
| [Sprite Design.md](Sprite%20Design.md) | Sprite body, Sheet, clone, auto hitbox |
| [Collision Design.md](Collision%20Design.md) | Shared collision pipeline |
| [Canvas Design.md](Canvas%20Design.md) | Canvas, camera, layers, background, cull |
| [Effect System Design.md](Effect%20System%20Design.md) | Looks, transients, SpatialFx, post, quality |
| [Effect Handles.md](Effect%20Handles.md) | Post / background mutate-hide-remove |
| [Sound Design.md](Sound%20Design.md) | `play_sound`, `Sound`, mixer, mic, audio FX |
| [Box Design.md](Box%20Design.md) | Measuring `Box` / `Grid`, `box=`, `game_view` / `ui_view` |
| [Editor Design.md](Editor%20Design.md) | Level files, `Level` / `make()`, the level editor (companion app) |
| [Laws.md](Laws.md) | The constitution: short, checked laws of the frame, lifetime, contacts, input ownership and timers (today's behaviour). Read it whole before changing any of them |
| [Testing Design.md](Testing%20Design.md) | Test strategy, harnesses, bug loop, bug catalogue |
| [Fences.md](Fences.md) | Settled nos (index). Open **only** when proposing sugar / a second spelling / a silent rewrite |

## Repository layout

Folder map only — not a hop list. Open **only** if that folder is the task.

| Folder | What | Audience |
| --- | --- | --- |
| `design/` | These docs | Contributors |
| `docs/` | The author site, published with GitHub Pages: `docs/<lang>/guide/` (the Guia), `docs/<lang>/tutorial/`, `docs/assets/` (thumbnails, tutorial css/js — shared by every language). `pt` is written first; `en` mirrors it | Authors |
| `tools/guide/` | The Guia's generators and checks: `validate_guia.py` (catalog checks, search index; `--lang en`), `make_guia_thumbs.py` (thumbnails), `guia_parity.py` (the English Guide mirrors the Portuguese, unit by unit; state in `guia_en_state.json`, English index text in `guia_text_en.json`) | Contributors |
| `tools/readme/` | `make_readme_media.py`: the clips `README.md` shows (`docs/assets/readme/`), recorded from the programs they show; `editor_ninja.py`, the level editor's clip program | Contributors |
| `tools/video/` | `record_game.py`: gameplay videos with sound (60 fps, any size) for YouTube, rendered offline with the README tool's pilots; output in `recordings/` (git-ignored) | Contributors |
| `tools/release/` | `make_examples_zip.py`: `scena-examples.zip` (the examples and only the media they use), zipped on a release from the list `examples_zip.txt` | Contributors |
| `examples/` | Published beginner games; each tutorial ends in one of them | Authors |
| `drafts/` | Private: game examples in development (a `media` link to `examples/media` lets them run). A game moves to `examples/` when it is ready | The maintainer |
| `workbench/` | Private (below) | The maintainer |

Tests read these paths from one module, `tests/repo_layout.py`: a folder move
edits that file, not every test.

## Private folders

`workbench/` is the private workbench (and `drafts/` holds unpublished game
examples). They are **not published**: git ignores them
(they are kept outside the public history), so a checkout does not have them,
and nothing published points into them.

- `workbench/proposals/` — plans and sketches not yet built. **Not canon.**
- `workbench/archive/` — landed or dropped proposals, deliberation (rejected
  tables, old rounds), frozen snapshots; `archive/notes/` holds the dated lab
  and bench logs, `archive/scripts/` the retired labs. **History only.**
- `workbench/guides/` — how to write a tutorial and an example (tone, step
  rules, names). The rules the tests enforce are restated where the tests are
  (`tests/test_tutorials.py`, `tests/test_tutorial_steps.py`, `examples/README.md`).

**The living docs are self-contained.** When a proposal lands, its conclusion
goes into the matching `* Design.md` **with its reason**: a fence row says why the
alternative lost; a performance rule carries the one number it rests on (scene,
machine, before → after). Author-facing changes get a `CHANGELOG.md` entry. Then
the proposal moves to `workbench/archive/` with no link back. A doc, a code comment, a test
docstring or a script never cites a file in these folders:
`tests/test_doc_links.py` fails on such a citation and on any relative link whose
file does not exist.

## Editing the Guia

- **Section shape.** Concrete code first, then the reference (`details` tables). A
  subject with several questions gets one section per question ("Como fazer"),
  in the order an author meets them — basic before advanced. Parameters shared by
  many verbs live in one place (e.g. [Suíte `time=`](../docs/pt/guide/index.html#suite));
  a verb's table lists only its own knobs.
- **Ids are stable.** Other chapters, the Design docs and `validate_guia.py`
  (search index) link them. Moving content keeps the old id on the new home
  (a section, a tab panel, a `details`); the Guia opens the tab that holds it.
  Per-subject layouts: [Sprite Design.md — Guia layout](Sprite%20Design.md#author-surface-guia-layout).
- **"Não confundir" rows** are Parece (the wrong reading) · É (the fix) · Não é
  (the wrong model). A note with nothing to confuse is `<p class="gotcha">`.
  `validate_guia.py` rejects a row with Parece "—", a Parece that repeats the
  start of É, and a Não é cut out of É.
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
- **Vocabulary (English, `you`).** The English Guide uses the same canonical
  terms, defined once in its Vocabulary section (the same `#vocabulario` id):
  *design units* / *units* (never "DU", "pixels" or "points"), *frame*,
  *Entity*, *Graphic*, *object* (never "drawable" / "actor"), *pose*, *point*
  (any place the API takes; never "point-like"; `Point` in code is the class),
  *field* (never "cell"), *link* / *linked* (`@=`), *task* (never "job"),
  *held* / *on the frame it is pressed* (never "edge"), *channel* only for
  transients, *stage* (palco), *a world with a floor*, *place* × *travel*.
  "Qual usar" says code runs as a *formula*, a *check* (pergunta) or an
  *event* (aviso); work that takes time is a *process* with an *owner*. A stamp
  is an *add-on* (section "Add-ons"). Jargon gets plain English: bake → *compute*
  (a computed hitbox), sugar → *shortcut*, knob → *parameter* / *setting*, ink →
  *own field*, no-op → *does nothing*, interned → *shared*; *park*, *one-shot*
  and *escape hatch* stay. Fixed labels: `Parameters:`, `Returns`,
  `read / write` · `read` · `read-only`, "Don't confuse" (Looks like · It is ·
  It is not), "How to", "Reading the parameters", "See X" / "More in X".
  Spelling is American, matching the API (`color`, `center`, `gray`). Example
  code is translated (variables, strings, comments); API names and API string
  values (`"cyan"`, `style="fade"`) are not.
- **Open with what it is.** A section's first sentence says what the feature is
  and what it is for, in words a first-time reader knows ("A câmera escolhe que
  parte do mundo aparece na janela…"). Negations and contrasts with other
  features come after, never first. Catalog sections carry a "Como ler os
  parâmetros" note (what `amount` / `speed` / `color` mean there) so each card's
  meaning column can stay short without being a bare noun.
- **Leitura/Escrita column** says what the author may do. A field the engine
  refuses to write is *leitura*; a method is *método*; a keyword is *parâmetro*.
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

### The English Guide

The English Guide mirrors the Portuguese one **unit by unit**, and
`tools/guide/guia_parity.py` keeps the two in step (`tests/test_guia_parity.py`
runs its check in `quick`).

- **Where.** It is written in `docs/en/guide/draft.html` (with `noindex`) next
  to its own `guia-api-catalogs.js`. `index.html` keeps telling readers the Guide
  is being written until every unit is translated. At that point the draft
  becomes `index.html` (`validate_guia.PAGES`) and `noindex` is removed.
  Thumbnails are shared.
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
  examples are translated (`nave` → `ship`).
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

## Editing the README

`README.md` is the landing page on GitHub **and** on PyPI (`readme` in
`pyproject.toml`). Guards: `tests/test_readme.py`.

- **Absolute URLs only.** Links point at
  `github.com/accmota/Scena/(blob|tree)/main/…`, images at
  `github.com/accmota/Scena/raw/main/…`: PyPI renders the same file, where a
  relative path is dead. Each one must map to a file in the checkout. Not
  `raw.githubusercontent.com`: it answers 404 while the repository is private,
  where `github.com/…/raw/…` redirects with a token for a signed-in viewer.
- **Clips are recorded, never captured by hand.** `python tools/readme/make_readme_media.py`
  plays each program headless on the GPU (`ProgramRun`: the frame body and
  input handlers of a windowed run) while a *pilot* reads the game's globals
  and holds keys / moves the mouse, then writes `docs/assets/readme/<id>.webp`.
  Clips are animated WebP at 30 fps (`FPS` in the tool; the game steps at 60).
  Staleness is by input hash (program text, clip spec, pilot source, render
  settings), never pixels; `--check` lists stale clips. Edit an example or a
  pilot → render again. A pilot that clicks menus sets `game.cursor = True`
  and the tool draws the pointer (the window has none to capture). A
  *montage* (`segments` in `CLIPS`, e.g. "And many more") plays several
  programs, one short take each, fitted into one size (letterboxed when the
  aspect differs) with the file name in a corner; its hash covers every
  take.
- **The code on the page is the code of its picture.** The block right after
  `<!-- clip: <id> -->` is that clip's program (run as a file in `examples/`, so
  its art resolves from `examples/media`). The level editor's clip is no
  exception: `tools/readme/editor_ninja.py` starts the editor the way
  `scena-editor` does, with Ninja IV's level open, and a pilot zooms, box-selects
  and drags in it.
- **A pilot plays like a player.** It reads the game's globals each frame and
  holds keys or moves the mouse; places it acts on are world points of the
  level (`run_jump_and_throw`, `edit_a_level`), put on screen through the
  game's own camera. A clip that shows a death, a stuck hero or an idle
  screen is a pilot bug: look at frames from the clip before keeping it.
- **Videos are rendered the same way, with sound.** `python tools/video/record_game.py`
  plays a program headless with a README pilot (or `pilots.py:function`) and
  encodes MP4 (H.264, BT.709, AAC 48 kHz) or ProRes through ffmpeg, or writes
  PNG frames + WAV. The recorder is the sound card: it takes the mixer off
  `offline` (as `Mixer.start_device` does, so the engine's world-time pump is a
  no-op) and pulls one frame of samples (44100 / 60 = 735) right after each
  step, so a sound starts in the block of the frame that shows its cause.
  Pulling before the step puts every sound one frame late; pumping by world
  time as well plays sounds at double speed (guards: `tests/test_record_game.py`).
- **Code on the page runs.** A complete program (`from scena import *` …
  `run()`) plays 2 s headless and must not warn. A fragment must use exported
  names, accepted keywords and existing attributes of scena globals. A block
  inside a list item (indented fences) is read dedented. The fragment check is
  static: before writing a fragment, run it once inside a program. A check
  that only reads names passed `bar["color"] @= …`, and appearance cannot be
  linked (`color`, `visual`, `glow`: [Reactive Design.md](Reactive%20Design.md)).
- **The pitch says what Scena is, not what it does for you.** The author writes
  the game; Scena gives the vocabulary and runs the machinery (loop, drawing,
  timers, cleanup). Avoid lines that read as the framework making the game
  ("Scena does every detail"); performance is "enough for typical games at
  60 fps on an ordinary computer", never "fast".
- **The examples download is a release asset.** The README links
  `releases/latest/download/scena-examples.zip`. The release workflow's
  `examples` job (after PyPI) zips the files in `tools/release/examples_zip.txt`
  with the standard library and attaches the zip to the tag's GitHub Release.
  The list is made here by `python tools/release/make_examples_zip.py --update`
  (the media scanner of `tests/test_media_refs`, level files followed to their
  images, each used folder's license, `CREDITS.md`); `tests/test_examples_zip.py`
  fails while it is stale and plays the level examples from the unzipped folder.
- **Claims match the code.** "Mistakes explain themselves" is true only where
  the near-miss message exists; check a claim before writing it.
- **Docs links go to `pt`** until the English tutorial and Guia exist; the
  page says so.
