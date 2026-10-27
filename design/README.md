# Scena design docs

How the framework works and why: architecture, invariants, fences, the test
strategy. For contributors (people and agents). Authors read the
[API Guide](../docs/en/guide/index.html) and the
[tutorials](../docs/en/tutorial/index.html) (Portuguese:
[Guia](../docs/pt/guide/index.html), [tutoriais](../docs/pt/tutorial/index.html)).

Reading order:

1. **[Scena Design.md](Scena%20Design.md)** — start here. Jump box first (code map / frame / API / intent), then product **Context**, then architecture (subsystems, data model, datapath). Happy path only. Companions are a menu, not a reading list.
2. **[API Guide](../docs/en/guide/index.html)** — author-facing API reference (it mirrors the Portuguese [Guia da API](../docs/pt/guide/index.html), which is written first).
3. Named `* Design.md` companions — subsystem depth when you need it. Open **one**.

Design docs describe **current understanding**, not a freeze. Full statement: [Design documents are descriptions, not locks](Scena%20Design.md#design-documents-are-descriptions-not-locks). The API is published (since 0.6.0): a change that breaks author code is weighed against its cost and follows [Compatibility and versions](Scena%20Design.md#compatibility-and-versions).

## Use (agents)

Same protocol as [Scena Design.md — Appendix](Scena%20Design.md#appendix-module-map):

1. Open Scena Design. Pick one router row.
2. Open **Start** only (search; do not slurp fat files).
3. Open the matching companion **only if** invariants are unclear — then pick **one** jump-box row in that companion; do not read the rest.
4. Treat **fences in that section** as current constraints (same weight as invariants).
5. Stop. Do not ingest other companions, `scripts/` or `_sksl_*` unless that is the task.
6. **[Laws.md](Laws.md)** is short: read it **whole** before changing frame order, lifetime, contacts, input ownership or timers. A change that breaks a law is a design change: the law, its model (`tests/laws/model/`) and the companion doc change with it.
7. **[Fences.md](Fences.md)** is not a reading list. Open it only when proposing API sugar, a second spelling, or a silent rewrite. Do not invent API a fence forbids without evidence matching the revisit bar.

## Live docs


| Doc | Role |
| --- | --- |
| [Scena Design.md](Scena%20Design.md) | Context + architecture hub |
| [API Guide](../docs/en/guide/index.html) | Author API (reference; mirrors the Portuguese [Guia](../docs/pt/guide/index.html)). Look catalogs (Visual, SpatialFx, Post, Backgrounds) carry generated thumbnails. |
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
| [Docs Design.md](Docs%20Design.md) | Writing the API Guide and the Guia, and keeping the English Guide and tutorials in step with the Portuguese |
| [README Media.md](README%20Media.md) | The landing page (`README.md`), its clips, gameplay and build-up videos, the examples download |

## Repository layout

Folder map only — not a hop list. Open **only** if that folder is the task.

| Folder | What | Audience |
| --- | --- | --- |
| `design/` | These docs | Contributors |
| `docs/` | The author site, published with GitHub Pages: `docs/<lang>/guide/` (the API Guide; the Guia in `pt`), `docs/<lang>/tutorial/`, `docs/assets/` (thumbnails, tutorial css/js — shared by every language). `en` mirrors `pt`, which is written first ([Docs Design.md](Docs%20Design.md)) | Authors |
| `tools/guide/` | The Guide's generators and checks: `validate_guia.py` (catalog checks, search index; `--lang en`), `make_guia_thumbs.py` (thumbnails), `guia_parity.py` (the English Guide mirrors the Portuguese, unit by unit; state in `guia_en_state.json`, English index text in `guia_text_en.json`) | Contributors |
| `tools/tutorial/` | The English tutorials' checks: `tutorial_parity.py` (each English page mirrors a Portuguese one, step by step, and its code is the Portuguese code renamed; state in `tutorial_en_state.json`), `names_en.json` (the glossary: English page and example names, one English name per Portuguese name in a series) | Contributors |
| `tools/site/` | `seo.py`: the search and link-preview tags in every page's head (title, description, canonical, absolute hreflang, og/twitter) and `docs/sitemap.xml`, made from the pages; `make_og_image.py`: the preview image `docs/assets/og/scena.png`; `make_tutorial_banner.py`: the picture on the tutorial indexes, `docs/assets/tutorial/banner.webp` ([Docs Design.md](Docs%20Design.md), "Search and link previews") | Contributors |
| `tools/readme/` | `make_readme_media.py`: the clips `README.md` shows (`docs/assets/readme/`), recorded from the programs they show; `editor_ninja.py`, the level editor's clip program | Contributors |
| `tools/video/` | `record_game.py`: gameplay videos with sound (60 fps, any size) for YouTube, rendered offline; `takes.py`, the shot list; `pilots.py`, pilots that play whole runs; `buildup.py`, a tutorial's steps one after another; output and review sheets in `recordings/` (git-ignored) | Contributors |
| `tools/release/` | `make_examples_zip.py`: `scena-examples.zip` (the examples and only the media they use), zipped on a release from the list `examples_zip.txt` | Contributors |
| `tools/media/` | `convert_music.py`: a folder of downloaded music to OGG Vorbis (~96 kbps, sample-exact) with plain file names, the originals kept outside the repository; needs `pip install soundfile` | Contributors |
| `examples/` | Published beginner games and showcases; each tutorial ends in one of them | Authors |

Tests read these paths from one module, `tests/repo_layout.py`: a folder move
edits that file, not every test.

## Private folders

The maintainer keeps plans, deliberation, dated bench logs, the authoring
guides and games in development outside the published tree (git ignores
those folders, so a checkout does not have them).

**The published docs are self-contained.** When a plan lands, its conclusion
goes into the matching `* Design.md` **with its reason**: a fence row says why the
alternative lost; a performance rule carries the one number it rests on (scene,
machine, before → after); a finding carries its repro or the test that holds
it. Author-facing changes get a `CHANGELOG.md` entry. A doc, a code comment, a
test docstring or a script never cites a private file, and a design doc never
sends the reader to unpublished material for evidence (a review report, repros,
a bench log) or names the private folders: `tests/test_doc_links.py` fails on
either, and on any relative link whose file does not exist. People are named
by role: the maintainer, an author, a player.
