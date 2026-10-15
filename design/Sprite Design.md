# Sprite Design

Image bodies (`Sprite` / `Sheet` / `Svg` / `SpriteButton`), spawn / `clone`, sprite hitbox bake,
and the mass-sprite hot path. **Happy path for this subsystem** — pick one row;
do not read the rest. Registry citizen / process: [Actors Design.md](Actors%20Design.md).
Collision engine: [Collision Design.md](Collision%20Design.md). Hub:
[Scena Design.md](Scena%20Design.md). Author calls:
[Guia da API](../docs/pt/guide/index.html#desenhar-sprite).

Today’s baseline, not a freeze — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Path resolve / play / flip / `art_angle` / Svg | [Sprite design notes](#sprite-design-notes) |
| Size across clips / `Sheet(anchor=)` / `clip(offset=)` | [Scale and registration](#scale-and-registration) |
| Sheet / clip / strip ladder | [Author ladder](#author-ladder-sheet-vs-sprite) |
| File patterns (`strip("run", "ninja/Run__*.png")`) | [File patterns](#file-patterns) |
| FrameFx silhouette | [FrameFx](#framefx-sprite-silhouette) |
| Shield costume envelope | [Costume envelope](#costume-envelope-shield-on-sprite) |
| Spawn / `clone` | [Sprite spawn & clone](#sprite-spawn--clone) |
| Auto hitbox bake | [Auto hitbox](#auto-hitbox-shapeauto) |
| Every hitbox is a `Hitbox` (`sprite.hitbox`, knobs, `.active`, roles) | [Hitboxes: one type](#hitboxes-one-type) |
| `box` / `hitbox.box` / `art_box` / `width` — which to read | [Measuring a sprite](#measuring-a-sprite) |
| Hitbox parts (`add_hitbox`) | [Hitbox parts](#hitbox-parts) |
| `px_rect` / `px_circle`, `sprite.showing()`, `hb["active"] @=` | [Pixel shapes and linked active](#pixel-shapes-and-linked-active-round-2) |
| Mass-sprite hot path | [Mass sprite hot path](#mass-sprite-hot-path) |
| Where a feature goes in the Guia | [Author surface (Guia layout)](#author-surface-guia-layout) |
| `SpriteButton` (game button: feel, label, state art, hull click area) | [SpriteButton](#spritebutton) |

## Use

1. Pick one jump-box row.
2. Read that section only (search; do not read the rest of this file). Treat fences there as current constraints.
3. Open **Start** only if the section is not enough.
4. Open **Also** / another Design doc only if Start is not enough.
5. Stop. Do not ingest `scripts/` or the private archive / proposals unless visual/bench proof is the task.

## Router

| Need | Start | Also |
| --- | --- | --- |
| `Sprite` / `Sheet` / `Svg` / play | `sprite.py` | `atlas.py` (sheet + bake) |
| `hitbox_shape="auto"` **bake** | `atlas.py` | `sprite.py` |
| `add_hitbox` / `Hitbox` | `hitbox.py` | `sprite.py` (`_HitboxBakeMixin`, `_emit_baked_specs`), `collision.py` (`_tag_item`, `_ensure_part_collider`) |
| Runtime collision pairs | `collision.py` | [Collision Design.md](Collision%20Design.md#sprite-colliders) |
| `Graphic.clone` | `shapes.py` (`_publish_graphic_api`) | `sprite.py` (`_clone_recipe`) |
| `box=` / `sprite.box` | `box.py` | `sprite.py` (`sprite_size_from_box`) |
| `SpriteButton` | `sprite_button.py` | `orchestration.py` (press lifecycle), `canvas.py` (`_draws_solo`, `_draw_filtered_one`), `transients.py` (`_draw_attached`) |

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `hitbox_shape="auto"` bake | `atlas.py` | runtime pairs (`collision.py`) |
| `Graphic.clone` | look snapshot + interned sheet | a pool |
| FrameFx path/SDF | silhouette bake in `atlas.py` | auto-hitbox fitters |
| `Hitbox` (from `add_hitbox`) | detection-only part owned by a Sprite (`hitbox.py`) | the body's `hitbox_shape=` kind, or an Entity |
| `SpriteButton` click area | convex hull of the **rest** art (`_rest_hull_local`) | the collision hitbox, or the current frame's alpha (`Sprite` pointer test) |
| `Button` (HUD widget, theme chrome) | `uiwidget.py`, no pose | `SpriteButton` (a Sprite made of game art) |

## Not in this doc

- Entity / process / fleet Director → [Actors Design.md](Actors%20Design.md)
- Collision pipeline / `resolve` → [Collision Design.md](Collision%20Design.md)
- Looks / stamps / §5.5 AABB → [Effect System Design.md](Effect%20System%20Design.md)
- Author catalogs → [Guia da API](../docs/pt/guide/index.html#desenhar-sprite)

## Author surface (Guia layout)

The Guia teaches Sprite in six sections, API first, then one "Como fazer" per
question. A new Sprite feature goes in the section that answers its question,
not in a new tab on the API section. Keep the ids: `validate_guia.py`
(symbols), this file, and other chapters link them.

| Guia section | id | Holds |
| --- | --- | --- |
| Sprite | `desenhar-sprite` | Sheet / Sprite mental model, simplest code, constructor, properties / methods by theme, `play`, `Sheet` |
| Carregar sprites | `sprite-carregar` | The six load cases (`spr-png` … `spr-still`) — loading only |
| Animar sprites | `sprite-animar` | `spr-clip`, `spr-once`, `spr-plat`, `spr-size` ([Scale and registration](#scale-and-registration), `Sprite(offset=)`) |
| Orientar sprites | `sprite-orientar` | `spr-art-angle`, `spr-flip`, `spr-tilt` |
| Hitbox do Sprite | `spr-hit` | Body vs parts, the four knobs, then `spr-hit-corpo`, `-ajuste`, `-troca` (runtime writes), `-partes`, `-atlas`, `-ataque`; `spr-hit-ref` = `Hitbox` reference |
| Recursos adicionais | `sprite-extras` | `spr-clone`, `spr-class`, `spr-svg`, `spr-look` |

`spr-hit-ataque` teaches the attack box, using [pixel shapes and linked `active`](#pixel-shapes-and-linked-active-round-2):
`px_rect=` / `px_circle=`, `sprite.showing()`, and `hb["active"] @=`.


## Scale and registration

Packs are either drawn on one shared canvas (every cell the same size — most
strips) or **cropped per animation** (each clip's PNGs trimmed to that clip's art:
a short slide, a wide fall — e.g. the ninja pack in `examples/media/ninja`).
Two rules make both work with no processing:

| Rule | Contract |
| --- | --- |
| **One scale per sprite** | `height=` / `width=` / `size=` (or `box=`; a `box=lambda: …` region drives the pose `scale` on top, never this — [Box Design — Fit](Box%20Design.md#fit)) fixes design units per pixel against the **construct cell** (`frame=`, else the first cell of the sheet's first clip, else cell 0) — the PNG, or the atlas `sourceSize` for a trimmed atlas (the trim only places pixels inside it). Every other cell draws at its own size × that scale: a 351 px slide next to a 439 px idle at `height=70` is 56 tall, not 70. `_du_per_px()` derives the scale from the live `width` / `height` and the cell they were fitted to (`_ref_src_w/h`), so writes rescale every clip; stretch (both given) keeps a per-axis scale. Scale is per sprite, not per PNG: two sprites of one sheet with different `height=` differ on screen. Within a clip, cells of different sizes also draw at their own size (`width` / `height` report the clip's first cell). |
| **`Sheet(pixel_size=)`** | The pack's scale, set once on the art: design units per PNG pixel (`pixel_size=3` → one pixel is 3 units; a float, `0.5` → two pixels per unit; must be > 0). A Sprite of that sheet with **no** `height=` / `width=` / `size=` / `box=` draws every cell at canvas px × `pixel_size`, so sprites of one pack keep their relative sizes (a 16 px tile and a 32 px character stay 1:2) with no per-sprite sizing. An explicit size on a Sprite still wins for that sprite (it sets that sprite's own scale). `sprite.scale` multiplies on top; a trimmed atlas uses `sourceSize`. Read-only `sheet.pixel_size`; `None` (default) keeps the per-sprite default size. Direction is "size of one pixel" — not Unity's pixels-per-unit — because that is the number pixel-art authors already say ("3×"). A loose PNG has no Sheet of its own: `Sprite(Sheet("tree.png", pixel_size=3))`. A global default (`init(pixel_size=)`) is **deferred** — revisit when a taught game sizes many loose PNGs of one pack. |
| **Registration: the pivot** | `sprite.center` is the current cell's **pivot** (already true for atlas pivots). Precedence: an **authored atlas pivot** (`AtlasFrame.pivot_authored`, JSON `pivot` / `anchor` / `origin` / `pivotX…`, XML `pivotX` / `pivotY`) → else **`Sheet(anchor=)`** → then the clip's **`offset=`**. The anchor uses the `hitbox_anchor` vocabulary (`"center"` default, `"bottom"`, `"top"`, `"left"`, `"right"`, or a y-up `(ax, ay)` pair, not clamped) mapped to a y-down source fraction `(0.5 + ax/2, 0.5 − ay/2)`. With `anchor="bottom"` the canvas bottom-centre of every cell sits on `center`: a shorter cell keeps its feet on the floor. |
| **`clip(..., offset=(dx, dy))` / `strip(..., offset=)`** | Art pixels, y-up, right = +x in the unflipped art; moves that clip's art relative to `center` (`pivot_x −= dx/src_w`, `pivot_y += dy/src_h`). Mirrors with `flip_x` / `flip_y` (flips mirror about the pivot). An offset belongs to the cell: one cell registered in two clips with different offsets raises `ValueError`; the same offset twice is fine. The escape path when a pack's clips do not line up. (The ninja pack needs none: with `anchor="bottom"` its clips already register on the PNG rect — checked frame by frame on `Dead`.) |

Implementation. `Sheet._frame_at(i)` returns the shared atlas frames when the anchor
is `"center"` and no offsets exist (`_plain_frames`, one bool check on the draw
path); otherwise a per-Sheet tuple of `AtlasFrame.with_pivot` copies built lazily
(`_eff_frames`, reset by `strip()` / `clip(offset=)`). Atlas frames are cached and
shared (`_ATLAS_CACHE`, keyed by path and the file's modification time and
size, so a rewritten atlas is parsed again; the cached frames refuse writes),
so a Sheet never mutates one. Every pivot reader (blit,
`_visual_local_center`, hitbox bake and union, flip, tilt, parts) goes through
`_frame_at`; the union cache key already includes pivots (`_frame_set_signature`),
and single-frame bakes live in pixel space (pivot-independent). Interned stills
(`Sprite("file.png")`) take no anchor (centre).

Hitboxes. The body maps baked locals through `_hitbox_pose_wh()` = baked cell ×
`_du_per_px` × `scale` — independent of the clip playing, so a frozen walker body
does not grow or shrink when a taller / wider clip plays. The collision snapshot
cache is keyed on the sprite's **`center`** (`Sprite._collision_pose_anchor`), not
on the drawn box centre: with a non-centre pivot (anchor, authored pivot, offset)
the drawn box moves when the cell changes while the body does not, and a key on
the box centre made the cache's translate fast path slide the body by that visual
shift — a resting walker floated (slide) or **sank** (dead) under `resolve()`.
Regression: `TestRestingBodyAcrossClips` in `tests/test_sheet_scale_anchor.py`. Union scales are
identity (`_hitbox_px_scale`): every cell's pixels land at the same size, aligned
by pivot — with `anchor="bottom"` the union of `hitbox_source=("idle", "slide")` shares
the feet line. `hitbox_source="each"` parts map through the baked cell, so a slide
cell's part is as short as the slide art.

**Deferred: alignment from visible pixels** (align clips by their alpha bounds
instead of the PNG rect). On the ninja pack it differs from `anchor="bottom"` by
0.6 du, and per-frame alpha alignment would erase in-clip motion (a run's lifted
feet). Revisit bar: a real pack whose PNG padding misleads and `offset=` is too
tedious.

The **size reference** is the construct cell: `frame=` names it (an index or a
name); without it, the first cell of the sheet's first clip; else cell 0. There is no
`clip=` constructor keyword (a second spelling of `play()`) and no separate
`size_from=` — `frame=` already is "the cell `height=` measures", and a sheet with
`pixel_size` needs no reference at all.

Author surface: [Guia — Tamanhos diferentes](../docs/pt/guide/index.html#spr-size).
Tests: `tests/test_sheet_scale_anchor.py`.

## Sprite design notes

A Sprite is a **Graphic**, not a `Rect` with `Texture` fill and not a `Shape`. The bitmap
**is** the body — the framework does not replace it.


### Author ladder (Sheet vs Sprite)

`Sheet` is the catalog (pixels, layout / atlas, named clips). It does **not** place.
`Sprite` is the registry citizen (pose, size, Graphic, `play` / `frame`). One catalog
type. Author surface:
[Guia da API — Carregar sprites](../docs/pt/guide/index.html#sprite-carregar).

| Case | Catalog | Actor |
| --- | --- | --- |
| 1. One still PNG | none | `Sprite("potion.png", height=48, center=(x, y))` |
| 2. Several files, one frame each | `Sheet("robot/Run (*).png", fps=12)` (a [file pattern](#file-patterns)), `Sheet(["Idle_0.png", "Idle_1.png"])` or `Sheet("Idle_0.png", "Idle_1.png")`; then `clip` | `Sprite(sheet).play("run")` |
| 3. Packed atlas + clips | `Sheet("sheet.png", atlas="sheet.xml")`; then `clip` | `Sprite(sheet).play("green")` |
| 4. Regular grid | `Sheet("hero.png", cols=4, rows=3)` or `cell=(w, h)`. One loop: `Sheet("pixel_adv/Cherries.png", cols=17, fps=20)` registers `"default"` | `Sprite(sheet)` autoplays when the sheet has exactly one clip |
| 5. Several strip files | `Sheet("idle.png", cols=4, fps=6, name="idle")` then `strip`. Loose frames per animation: `Sheet(anchor=…)` then `strip("run", "ninja/Run__*.png", fps=12)` per clip | `Sprite(sheet).play("walk")` |
| 6. Atlas stills (fleet / items) | same packed `Sheet` as case 3 | `Sprite(sheet, frame="playerShip1_blue.png")` — still, no `play` |

Positionals are in order. Everything after them is keyword-only.

| Call | Positionals | Keywords |
| --- | --- | --- |
| `Sheet` | `source` (`str`, `list[str]`, or further filenames; any may be a pattern) | `cols`, `rows`, `cell`, `atlas`, `fps`, `name`, `yoyo`, `anchor`, `pixel_size` |
| `sheet.clip` | `name`, `frames` (optional) | `fps`, `yoyo`, `offset` |
| `sheet.strip` | `name`, `source` (`str` image or pattern, or `list[str]`) | `cols`, `rows`, `cell`, `fps`, `yoyo`, `offset` |
| `Sprite` | `source` (`str` still, or `Sheet`) | `frame`, `center`, `box`, `height` / `width` / `size`, hitbox knobs, `group`, `layer`, flips, `art_angle`, … |
| `sprite.play` | `clip` | `loops`, `next`, `min_hold`, `resume` |
| `sprite.showing` | `frames` (clip name, index, frame name, or a tuple / list) | — |

```python
hero.clip("walk", [3, 4, 5, 6], fps=12)
hero.strip("walk", "walk.png", cols=8, fps=12)
ninja.strip("correndo", "ninja/Run__*.png", fps=12)
sprite.play("walk", loops=1, next="idle")
```

**Load.** Case 2 is one file → one frame. A list and extra positionals are the same
catalog. Several files together with `cols=` / `rows=` / `cell=` / `atlas=` is
`TypeError` and points at `strip`. `source=[…]` plus extra positionals is
`TypeError` (the list is the whole catalog). `Sheet(source="a.png", "b.png")` is
illegal Python.

Grid layout is `cols=` alone (one row), `cols=` with `rows=`, or `cell=(w, h)` in
pixels. `rows=` without `cols=` is `TypeError` (`cols=1` is a vertical strip).
`cell=` does not combine with `cols=` / `rows=`. Layout does not combine with
`atlas=`.

Taught packed load names the image and the atlas. `Sheet("file.xml")` /
`Sheet("file.json")` alone is a convenience: the PNG comes from atlas metadata.
When `source=` and the listing name different files, the author's `source=` wins
and a warning fires once (the same resolved path stays silent). A missing
`source` warns, then tries the listed PNG; if that file is missing too, the
catalog stays a placeholder.

`fps=` on a grid or a multi-file `Sheet` registers one clip over every cell the
constructor just loaded. Omit `name=` → `"default"`. Case 5's first strip passes
`name=` so it matches later `strip` names. `name=` or `yoyo=` without `fps=` is
`TypeError`. On a packed atlas, `fps=` / `name=` / `yoyo=` is `TypeError`.

`Sheet()` with no files is an escape filled only by `strip`. `Sprite` on a sheet
with no frames is `ValueError`. A bare `Sheet("x.png")` with no layout is a
one-cell catalog; the still happy path is `Sprite("x.png")` (case 1), which interns.

**Clips.** `clip` names cells **already** on the sheet. Omit `frames` →
`range(nframes)` at that call. A file not loaded yet belongs in `strip`.
No frames yet, or an empty `frames` list, is an error; an index past the
cells is an error on an empty `Sheet()` too (PA4: it was accepted and the draw
wrapped it). `frames` are indices or atlas names. `yoyo=False` wraps;
`yoyo=True` ping-pongs. Omitted `fps` defaults to 8. A cell's `offset=` belongs
to the clip that set it (`_clip_offsets`): re-registering a clip replaces its
offset, and dropping `offset=` drops it (PA6). `cell=` takes whole pixels
(`16` or `16.0`; PA10). A missing file loaded with `cell=` alone has an unknown
cell count, so every index shows the checker, as a missing atlas does (PA13).
An image path that matches only because the disk ignores letter case warns
once and resolves to the disk's spelling (`_true_case_path`; PA9).

`strip(name, source, …)` appends more frames as their own backing image and
registers that name as a clip. The source is one image (a grid with the same
keywords as `Sheet`, or one frame), a file pattern, or a list of files (one
frame each, packed like case 2; frames named by file stem). The packed strip is shared by every Sheet over the same decoded images (`sprite._PACK_CACHE`), so a second Sheet of the same files reuses the first one's auto-hitbox fits (PA-note: about 10 ms per instance); each Sheet stays the author's own (clip / strip still work). Each frame keeps the file that loaded it (`_frame_paths`): that path, or a tail of it (`"idle/1.png"`), names the frame. A stem two files share (`idle/1.png`, `run/1.png`) names neither and raises listing both (PA3: the last one won, even for the exact path). Layout keywords with
a pattern or with 2+ files are `TypeError`; a one-item list without a pattern is
that file. Packed atlases stay on `Sheet(..., atlas=)`.

<a id="file-patterns"></a>**File patterns.** A filename containing `*` is a
list of files written short: legal exactly where a list of files is (`Sheet`
source, its extra positionals and list items, `strip` source) and it means that
list, expanded in place. That rule is what keeps it from being a second spelling:
it is a value form (a list of files written short), not a new verb or keyword, so
code that looks like it loads the frames does. Rules:

- `*` is the only wildcard (any run, empty included); `?` / `[` are literal. In
  the file name only — a `*` in a folder part is `ValueError`. A pattern of
  atlas files (`*.xml`) is `TypeError`.
- Natural order: digit runs compare as numbers (`Run (2)` before `Run (10)`).
- Case-sensitive on every OS. Names starting with `.` match only a pattern
  starting with `.` (keeps macOS `._*` AppleDouble files out). Folders never match.
- Search: the image-file folders below, in order; the pattern is matched in the
  **first folder with a match** only, never mixed across folders.
- Zero matches is legal: one placeholder cell (checker labelled with the
  pattern) and one warning naming the pattern and every folder searched (plus
  names that differ only in case). The clip still registers.
- Layout keywords (`cols=` / `rows=` / `cell=`) or `atlas=` with a pattern:
  `TypeError`, decided from the call — a pattern that matches one file is
  still one file per frame.
- `Sprite("…*.png")` (and a class `source=` default) is `TypeError` pointing at
  `Sprite(Sheet("…*.png", fps=8))`; `SpriteButton` state art (one file per
  state) refuses a pattern too. One-image loaders (`Texture`, `Wallpaper`,
  `Svg`) read `*` literally (a miss is the usual checker).
- Code: `_pattern_matches` / `_expand_file_list` in `scena/sprite.py`. Tests:
  `tests/test_sheet_patterns.py`; `tests/test_media_refs.py` requires every
  pattern in examples / tutorials to match at least one file.

Define clips on the `Sheet` before or while building actors. A sheet shared by a
fleet stays as built; one `Sprite` does not grow clips for the others. Interned
`Sprite("file.png")` catalogs **refuse** `clip` / `strip` (`TypeError`, no
copy-on-write). Build a `Sheet` first. Catalog verbs stay on `Sheet`.

**Playback.** `frame=` / `.frame` is the current cell (index or atlas name) on
any multi-cell sheet. Default is `0`. Writing `.frame` stops playback. Until
`play`, the sprite shows that still.

`.play` takes a clip name already registered (`clip`, `strip`, or constructor
`fps=`). Tempo lives on that clip; another tempo is another clip. `loops`,
`next`, `min_hold`, and `resume` stay keyword-only. The same clip again is a
no-op **while it runs** (see below). A `loops=1` clip that has finished is not
running: `play` of it again restarts it (a hit or throw clip must replay on
every trigger). So a `play(..., loops=1)` written every frame from a state that
lasts (a death pose in `on_update`) loops the clip; the taught guard is
`if not self.showing("morto"): self.play("morto", loops=1)` (tutorials 18, 24,
22; the dying ninja replayed its death every 0.8 s before 2026-10-13).

`Sprite(sheet)` with **0** clips stays on `frame` (default `0`). With clips and
no `frame=`, the sprite starts on the **first cell of the sheet's first registered
clip** — the construct cell `height=` / `size=` measure ([Scale and registration](#scale-and-registration)),
so a packed atlas's arbitrary cell 0 (a laser next to the ships) never sets the scale.
Clips registered after the Sprite do not count. **1** clip
autoplays. **2+** clips stay still until `.play`. An explicit `frame=` wins over
one-clip autoplay.

**Author surface does not include** catalog kwargs on `Sprite` (`atlas=` /
`cols=` / `rows=` / `cell=` / `fps=` / `name=` / `yoyo=` → `TypeError` pointing
at `Sheet`; an atlas filename as `source` is the same error), `sheet.cycle`,
`sheet.add_clip`, a second catalog type, or `clip` with a file index / per-file
`cols=`.

- Placeholder / missing file / missing atlas / unknown atlas frame: magenta/black checker; warn once; stay valid. Unexpected Sprite constructor keywords raise `TypeError`.
- **Image files** — `Sprite` / `Sheet` / `Svg` filenames, and `Texture` / `Wallpaper` image files, share `_resolve_image_path`. No basename walk. First existing file wins, path used as written:

  1. Absolute path (that file only — exist or miss).
  2. Folder of the running script (`__main__.__file__`).
  3. `media/` next to that script (`Sprite("hero.png")` → `script/media/hero.png`; `Sprite("sprites/ship.png")` → `script/media/sprites/ship.png`).
  4. Current working directory.

  REPL / `python -c` skip to cwd. A file pattern searches the same folders, first folder with a match ([File patterns](#file-patterns)). Atlas PNG: name listed in the atlas, then a sibling of the resolved atlas file. Author surface: [Guia da API — Arquivos de imagem](../docs/pt/guide/index.html#arquivos-imagem).
- Size: design units. With no size keyword: the sheet's `pixel_size` if set (each PNG pixel = `pixel_size` units), else a default longer side = `max(48, 0.06 * min(design_w, design_h))` on the construct cell. `frame=` names the construct cell — the size reference ([Scale and registration](#scale-and-registration)).
- `play` uses world `clock.time` × `time_scale` (pauses with the world). The clip clock is world time, not a timer: a parked sprite (`active = False`) is not drawn, but its clip keeps advancing, so on resume it shows the cell world time has reached (parking pauses the actor's `after` / `every` / tweens, not the playhead). To hold the cell across a park, write `time_scale = 0` before parking. Writing `time_scale` rebases the playhead so the elapsed time does not jump; `0` freezes that elapsed time. Same clip again is a no-op. Size is **one scale per sprite** — every cell draws at its own PNG size times that scale ([Scale and registration](#scale-and-registration)); `play()` / `frame=` move `width` / `height` to the new cell, they do not refit it to the construct size. `size =` / `width =` / `height =` rescale every clip. `clone()` passes the knob kind of the size intent (`size`, `width`, `height`, or both) with the value of the cloned cell at the same scale.
- `flip_x` / `flip_y` — Sprite-only pose bools. Mirror about the pivot **before**
  rotation (`world = T · R(draw) · M · local`). Toggling a flip **rewrites**
  `.angle` (`flip_x` → `180 − θ`, `flip_y` → `−θ`) so the painted front stays
  aligned with the mirror. Idempotent re-assign is a no-op. Reflect baked local
  hitbox prims at emit; do not rebake. Not negative `scale` (blit already takes
  `abs(scale)`).
- `.is_collapsed` — `True` when the **drawn** frame has no interior (`w == 0 or
  h == 0` from `_oriented_frame`, including pose `scale → 0`). Same name/rule as
  `Box` / Shape. Constructor still rejects non-positive explicit `height=` /
  `width=` / `size=`; collapse after construct (scale, assignment) is legal and
  silent.
- `art_angle` — Sprite-only look default (constructor / class kwargs / property). Degrees,
  same convention as the world (`0` = +x, `90` = +y): the nose of the **pixels**,
  before flip. **`.angle` is world heading** (where the painted front points).
  Blit, `_oriented_frame`, hit-test, and collision prims use
  `draw_angle = angle − art'` where `art'` is `art_angle` reflected by the
  current `flip_*` (`flip_x` → `180 − a`, then `flip_y` → `−a`). Pointer
  `contains_point` / `@click` sample the **current cell's alpha** (inside the
  oriented visual rect, tilt included), not the PNG rectangle and not the
  baked hitbox (`collision.query_point`). Construct seeds
  `_rotation = rest_heading` (epoch stays clean) so the sprite appears as drawn;
  constructor `angle=` (Sprite and Svg) sets the world heading instead — a number,
  or a function that links it (`Graphic._init_heading`).
  Live `art_angle = …` does **not** rewrite `.angle`. One value per sprite,
  shared by every frame of a clip (`clip` / `strip` / constructor `fps=`,
  including `yoyo=`). Packed-atlas
  `AtlasFrame.rotated` is packing, not this. 8-dir sheets still pick a frame from
  heading. `clone()` passes live `art_angle` through `_clone_recipe` and copies the
  live `angle` (the copy faces where the source faces).
- `rest_heading` — **Graphic** property (Shape default `0`; Sprite override). Heading
  at rest for this body (`draw_angle == 0` on sprites). Sprite:
  `rest_heading = art'` (same reflection chain as draw). Nave `art_angle=90` → `90`;
  ninja `art_angle=0` + `flip_x` → `180`. **`reset_rotation()`** →
  `rotate_to(rest_heading)` on any Graphic; does not clear flip.
- Class look defaults — `class Bolt(Sprite, source=…, height=…)` stores omit-able fills on
  `_sprite_defaults` (MRO merge, child wins). Instance kwargs win. Not class attributes
  named `frame` / `height` (those shadow descriptors). `center` / `layer` rejected
  as placement. `clone()` still passes the resolved sheet + live pose (including flip /
  `art_angle`).
- `hitbox` — Sprite collider. Four knobs: `hitbox_shape=` (primitive), `hitbox_source=` (which art), `hitbox_anchor=` / `hitbox_scale=` (shaping). Default `"auto"` is a rotation-safe utility pick, baked from the **reference set** on collision enroll and **frozen** while the clip plays unless `hitbox_source="each"` (every cell) or `"clip"` (once per clip switch). Under `"auto"` those two lock **kind** on the first bake and refit params only. Walkers should pick `"rect"`. Extra detection-only colliders are **hitbox parts** (`sprite.add_hitbox(group=…)`) — see [Hitbox parts](#hitbox-parts). Full contract: **Auto hitbox** below. Author surface: [Guia da API](../docs/pt/guide/index.html#spr-hit). Collision: [Collision Design.md](Collision%20Design.md#sprite-colliders).
- Appearance stamps — `.glow` / `.shadow` / `.hue` / `.gray` / `.tail` (Sprite family: Sprite, Svg, SpriteButton, author subclasses — dispatch is `entity.is_sprite_family`, never the class name); Shape drops `.hue` / `.gray`; Text `.glow` only. Sugar `True` / color / number / object; Tail `True` follows motion.
- Overlay / path / material looks via `Visual._allows_sprite` (see [Guia da API](../docs/pt/guide/index.html#aparencia-visual)). Pixel looks on `.visual` (`Recolor`, `Aura`, `EmissiveBloom`) are `_sprite_only`. **HueShift** is a stamp (`.hue`) or `Texture(..., shift=HueShift(...))` — not `.visual`. Remaining body looks (`Neon`, `Water`, `Gel`, …) and `Paint` / Gradient as `.visual` → **`TypeError`**. `_replaces_sprite_body` materials (`Metal`, `Flame`, `Swell`, `Aurora`, `Wave`) fill the silhouette instead of blitting.
- **`Svg`** — Sprite subclass whose body is rasterized from SVG. First positional `source` is markup if it contains `<`, otherwise a filename (same resolve as Sprite). `.svg` always stores markup (file contents after load, never the path). Writing `.svg` uses the same rule; same stored markup → no-op. Missing file / parse failure: warn once, checker, stay valid (setter keeps last good body). `svg = None` clears to the checker, as `Svg(None)` builds it. Private single-frame sheet (never interned — live unique strings would leak). Still only: catalog kwargs (`cols=` / `atlas=` / `fps=`), `play`, and `strip` raise `TypeError` (`frame=` other than `0` too). Same hitbox knobs as Sprite (`"all"` / `"each"` are one-frame no-ops). `clone()` recopies markup into a new private sheet (later writes do not affect the source). Bitmap body: camera zoom softens; no live `SVGDOM.render` each frame. Author surface: [Guia da API — Svg](../docs/pt/guide/index.html#spr-svg). Smoke: `scripts/smoke/sprite_fx.py` (compass/car cell). Tests: `tests/test_svg.py`.
- Interned **FrameFx** cache (silhouette path + optional SDF, max side 96) shared like auto hitbox. Assigning `.visual` warms the **current clip or cell**. `prepare_fx(*looks)` bakes every cell. See **FrameFx** below.
- `SPRITE_BODY` fill sentinel so filter batching sees a fill channel; draw always blits the bitmap.
- Tail on Sprite ghosts the **current frame**.
- Edge-map silhouette FX: landed (FrameFx path / SDF). `Halo()` / `Laser()` / `Rim()` on Sprite use SDF + `path_v2`; Shape keeps v1. Bake at look assign or `prepare_fx(*looks)`.

### FrameFx (sprite silhouette)

Interned bake in `atlas.py`, keyed by the image token (shared by every live sheet over that decoded image) plus the frame rect (not `id(image)`). Entries drop when the last holding sheet dies. Assigning `.visual` warms the current clip or cell; `prepare_fx(*looks)` bakes every cell. Used by Aura, Sprite Halo/fill, Sprite Laser, Rim, and path-shell strokes. The contour is the **largest** island, normalized on cell centres (`(x - 0.5) / size`), so `Track(sprite)` sits half a mask cell from the old top-left normalization and ignores smaller islands. A rotated atlas frame is un-rotated before the contour with the same 90° turn the blit uses (`Canvas.rotate(-90)` in y-down, and the same branch in hue / recolor SkSL). `Sprite._is_sprite_body` is true for `Svg` and author subclasses, so Halo and other looks call `_render_sprite_body` instead of a shape ellipse.

| Asset | What | Who uses it |
|-------|------|-------------|
| `path` | Dense marching-squares polyline (capped ~160–200 verts) | Leftover v1 silhouette strokes; body materials; Electric* silhouette preference |
| `path_v2` | Visvalingam–Whyatt cap 72, then quadratic-smoothed closed path; local-pixel cache (8 dst rects) | Sprite Halo rim, Laser fallback, other v2 strokes |
| `sdf` | Distance field (`_FX_SDF_PAD` 20 so Aura fringe / outer glow can fall off); **lazy** — path-only looks skip the EDT | Aura; Sprite Halo/fill glow; Sprite Laser / Rim bands (`sprite_sil_v2`) |

**When it bakes**

| Trigger | What |
|---------|------|
| Bare `Sprite()` / stamps (`Glow` / `CheapGlow` / `Shadow` / `HueShift` / `Tail`) / `Beat` / `Shield` / `Halo(style="soft"\|"line")` | Nothing |
| `visual = Halo` / `Halo(style="fill")` / `Rim` / `Laser` / `Aura` | Path **+ SDF**, current clip or cell |
| `visual = DashRing` / `Ink` / Electric* / Extrude / MultiBorder / Organic / Tracer / body materials (`_replaces_sprite_body`) | Path only, current clip or cell |
| `sprite.prepare_fx(Halo, Aura)` | Union of listed looks, **every** sheet cell; does not assign `.visual` |
| `prepare_fx()` no args | Current `.visual` if it needs path/SDF; else no-op |
| `entity.prepare_fx(...)` on Shape / SpatialFx / bare Entity | No-op (never raises) |
| First draw miss | Lazy fallback (`_frame_fx(sdf=…)`) |

Path and SDF are independent: `DashRing` warms contour only; later `Aura` upgrades `fx.sdf` in place from the retained mask. Flags: `Visual._needs_sprite_path` / `_needs_sprite_sdf` (plus `_replaces_sprite_body`).

Beginners: assign the costume — that is the warmup. Advanced: `prepare_fx(*looks)` on a load screen when art is not spawned yet or several costumes will be used later. Smoke A/B: `scripts/smoke/look_fx.py` (`PREPARE_FX = True/False`).

Alpha cutoff `_FX_ALPHA = 16` (0–255, ~6%) — **same floor as** `_AUTO_ALPHA`. AA fringe can sit slightly outside the perceived art edge; do not raise this independently of hitbox auto-bake.

**Host split (no public `HaloV2` / `LaserV2`):** authors write `Halo()` / `Halo(style="fill")` / `Laser()`. Interned instances are shared, so `_is_multipass` cannot differ per host. `_apply()` skips ImageFilter on Sprite for hollow/fill Halo; `Graphic.draw` (and transients) call `_render_sprite_body` when present. **Shape** Halo stays GlowRim (medium filterless ADD; high batched Blur + deferred rim) — faster and sharper on GPU primitives. **Shape** Laser stays the original ADD stroke ladder. `Halo(style="soft")` / `Halo(style="line")` stay HostGlow on both hosts (`_render_sprite_body = None` on HaloSoft / HaloLine; no FrameFx bake).

Sprite Laser beam is slightly thicker than Shape Laser (SDF bands + a modest core vs the thin Shape white stroke). Tune `_LASER_SPRITE_THICK` / `_LASER_SPRITE_CORE` in `recipes.py`; SkSL core falloff in `_sksl_shape.py` (`sprite_sil_v2`).

Author surface: [Guia da API — Aparência e clique](../docs/pt/guide/index.html#spr-look). Smoke: `scripts/smoke/look_fx.py`. Tests: `tests/test_atlas.py` (`TestSilhouettePathV2`), `tests/test_sprite.py` (FrameFx assign / `prepare_fx` / destroy-recreate).

### Costume envelope (Shield on Sprite)

Shield (including `style="plasma"`) sizes from a **frozen silhouette-union ellipse**, not the playhead sprite rect and not the hitbox.

| Rule | Detail |
|------|--------|
| Bake | On `.visual = Shield` (lazy). Bare `Sprite()` / Glow pay nothing. No FrameFx. |
| Geometry | Per-frame alpha AABB via `auto_collider_for_frame(..., force_kind="bbox")` → `_AUTO_CACHE` / `_MASK_CACHE` (same downsample as hitbox). Atlas bake keys hold every input of the bake (`atlas._auto_key`: packed rect, `rotated`, trim; the silhouette and union keys carry `rotated` too), so aliased or rotated frames never share a bake (PA2 / GR7, guard `test_cache_keys`). A live sheet's bakes stay until the sheet is released; only bakes of unregistered images share the 128-entry LRU (PA1: a ~200-cell "each" sheet re-fitted every frame advance). `Sheet._layout_epoch` also keys a sprite's cached source rect, so a later `clip(offset=)` moves the blit too (PB11). Map each box to this sprite’s design units (`height=` / `width=` / `size=` intent), then **union**. Oval inscribed in the union × `shield_scale` (default 1.4). |
| Stability | `play()` / clip ticks do **not** rebake. Clip switches do not pop the shell. The bake key is the sheet, its pivot layout (`Sheet._layout_epoch`) and the design units per pixel on each axis (`_du_per_px`), never the size intent: a height-sized sprite stretched with `width *= 2` rebakes (PB10). |
| Isolation | Does not call `_ensure_auto_baked` or write `_hitbox_*`. Hitbox knobs do not change the envelope. |
| Filter layer / cull | Dest `_approx_draw_aabb` is **not** the oval. `_layer_bounds_for` / cull union dest with the oval **only when** dest + filter `_batch_outset` would clip it (vortex HostGlow). GlowFilter styles and `style="bands"` keep today’s dest+outset plate — they already cover the oval; growing them would tax shared interned filters (bands HostGlow == HaloLine). Shape Shield is a no-op. See [Effect System Design.md §5.5](Effect%20System%20Design.md#55-changing-the-effect-system-without-regressing-hot-paths). |
| ProceduralFill UV | Sprite: `_uses_shield_envelope` → `_shield_envelope_half()`. **Shape** (Circle / Ellipse / …): `_center_radius` only. The predicate requires the envelope method **and** a Shield/plasma visual — never visual type alone. A bare `except` that falls back to fixed-res `ProceduralFill.tick()` empties bubble/nebula interiors on Shape fleets (2026-09 regression; §5.5 lesson). |
| Electric* | Unchanged — live silhouette path (`_needs_sprite_path`). |

Tests: `tests/test_sprite.py` (`TestShieldEnvelope`, `TestShieldFilterBounds`); Shape UV: `tests/test_visuals.py` (`test_shield_shape_not_sprite_envelope`).

Author spawn / `clone()` usage: [Guia da API — Clone](../docs/pt/guide/index.html#spr-clone). Architecture below.

## Sprite spawn & clone

Beginners start with `Sprite("file.png")` (**no** `Sheet`). That path must stay simple
and get the same construct / reuse wins. `Sheet` is the advanced catalog (clips, atlas,
strips). Fleet motion (`update(dt)` / Director looping `group[...]`) is
**orthogonal** — see [Actors Design.md — Fleet helpers](Actors%20Design.md#fleet-helpers-groups). This section is **birth** of Entities, not process.

**Cost.** Galaga fire creates a new `Sprite` per shot. Warm construct+destroy ≈ **165 µs**
per shot (`scripts/bench/perf_sprite_spawn.py`, path intern or shared atlas `Sheet`). At ~30
shots/s that is ~0.2 ms/frame — **not** the Glow / live-N cliff. Constructing
`Bolt("laser.png", …)` every shot is the intended path and is **not worse than
`clone()`** (warm clone is ~1.02× path / ~1.07× atlas — `look_like` tax). `clone()` is
ergonomic sugar for “like this instance”; it is **not** a fire-rate requirement and
**not** a pool. Galaga constructs shots
(`Bolt(space, frame=..., center=..., group="bolt")`). The `space` Sheet is the packed
Kenney atlas, not because shots spawn often. A single-file `Bolt("laser.png", …)` would
intern the catalog.

What intern **cannot** skip: per-Entity / Attribute / registry registration. Every
live projectile is an independent registry citizen. `clone()` pays that same scaffolding.
A clone collides like its source: the main-hitbox knobs (`hitbox_shape` /
`source` / `anchor` / `scale`) and a switched-off `hitbox.active = False` are
copied, as `collidable = False` is (decided 2026-10-09, review S7-8).

### Invisible caches (path-only ctor)

- Process-wide **image decode** (`_IMAGE_CACHE`, keyed by resolved abspath). Sprite
  entries are an eager `makeRasterImage()` so the PNG is decoded at load, not on the
  first GPU draw. `style._IMAGE_CACHE` (Texture / Wallpaper) keeps the **lazy**
  `Image.open` result — never a raster copy, because an image shader passed to
  `Paint.setShader` is copied and misses the cache (
  [Effect System Design.md §5.5](Effect%20System%20Design.md#55-changing-the-effect-system-without-regressing-hot-paths)).
  Sprite draws never `setShader` the image: the body blit is `drawImageRect`, and
  hue / recolor / SDF looks pass it as a runtime child (`setChild` +
  `Paint(Shader=…)`), which shares the sprite raster. Texture and Wallpaper stay
  on the lazy image so `setShader` does not encode a second copy. A tiled
  Wallpaper holds its own copy.
  Repeated paths do not re-decode. Missing files, missing atlas catalogs, and unknown
  atlas frame names warn once and share a placeholder catalog.
- Process-wide **hitbox bake** (`atlas.auto_collider_for_frame` /
  `auto_collider_for_frames`, image token + frame rect or frame-set signature).
  Independent of display size; decorative sprites never pay (bake on collision enroll).
  Masks are cached by region so switching `hitbox_shape=` on the same cell does not re-decode.
  Keyed by the **decoded image**, not the `Sheet` object: every live `Sheet` over one
  image shares one token (see [Cache keys](#pipeline)), so a fresh `Sheet(path)` per
  spawn hits the first sheet's bake.
- Path-only **interned single-frame `Sheet`** (`Sheet._intern`, key `("single",
  abspath)`). `Sprite("shot.png")` × N share one catalog object (`_shared` /
  `_interned`). Layout strips (`cols=` / `fps=`), packed atlases, and multi-file sheets
  are **not** interned — they may register clips. Author `Sheet("x.png")` is a separate
  catalog (may be mutated with `clip` / `strip`).
- `clip` / `strip` on an interned catalog **refuse** (`TypeError`) rather than
  copy-on-write. Shared stills stay stills; authors who need clips build a `Sheet`
  first. Catalog verbs stay on `Sheet`; Sprite does not forward them.
- Default blit paint is a shared immutable `skia.Paint`.

**Repeated `Sprite("shot.png")`:** decode, interned Sheet, and auto-hitbox *fit* run
once (fit on first collision enroll of that image frame). Later constructors reuse
those caches — they do not refit the mask. Each call still allocates a new Entity /
Attributes / registry registration. Copying the cached bake into that sprite’s local
coords is cheap. Decorative sprites never enroll, so they never bake.

That first fit runs **inside the frame** when the sprite is spawned during play
(the platformer's first `Sprite("ball.png")`). Hull simplification therefore
checks only the replacement chord, and only against the convex hull of the
occupied cell centres. Re-testing every cell against the whole trial polygon is
cubic in the vertex count: a round 32×32 mask (the bake's max side) stalls the
frame, and the next `dt` jumps the actor. `TestSimplifyHull` in
`tests/test_atlas.py` locks the vertex choice against that full re-check and
bounds `_choose_auto_collider` on a 32×32 disk.

**Repeated `Sprite(Sheet("atlas.xml"), frame=…, hitbox_shape="auto")`:** each call builds a new
(non-interned) `Sheet`, but the decode and the atlas parse are shared, and so is the
fit: the second construct+enroll is ≈ 1 ms, not the ≈ 30 ms first fit
(`scripts/bench/perf_assets.py`, `hitbox` warm). Holding one `Sheet` and passing it is
still cheaper (no catalog rebuild), not required for the bake to hit.

Passing an existing `Sheet` to `Sprite(sheet, …)` already shares atlas pixels and clips
(advanced path; marks `_shared`).

### `Graphic.clone`

One verb, same contract on Sprite and Shape: **a new Entity that looks like this one.**
Thin wrapper over the **normal constructor** (Shape `_clone_geometry` snaps free
geometry; Sprite `_clone_recipe` passes `self._sheet` + current frame / size / hitbox /
offset / `flip_x` / `flip_y` / `art_angle`), then `look_like()`. Passing the resolved `Sheet` skips filename / atlas
re-parse. Hitbox re-bake is a cache hit when `frame` is unchanged. Same cost class as
constructing the same path again — `clone()` is not a cheaper spawn. Class look defaults
do **not** re-bind a clone: the instance sheet and live flip / `art_angle` win.
`center=` places the copy on every kind (Sprite / Svg / Text through the
constructor; a Shape is moved there after its pose — [Shapes — clone](Shapes%20Design.md#clone));
`frame=` is Sprite-only and refuses elsewhere (`_clone_takes_frame`).

Does **not** own the source. No `Template` type, no registry, no “first live instance is
the proto.” Not on bare `Entity` (no visual/geometry worth cloning; `scale=` / style do
not apply). Subclass clone returns the subclass (`Sting.clone` → `Sting`).

Birth order:

1. Construct via the normal constructor (`setup()` **always**, if the subclass defines it).
2. `look_like(source)` — snapshot of **current** appearance (overwrites whatever `setup()`
   just assigned to look). `visual` is the **same interned object** (by reference).
3. `_clone_pose_from(source)` — the live **pose**: `angle`, `scale`, flip flags
   (Sprite also `tilt`, in whichever form it holds: angle, contact lean, `AUTO_GROUND`).
   A clone is drawn where and how the source is, and reads the same pose.
4. Copy `visible`. Apply `scale=` about center if ≠ 1 — it multiplies the copied scale.

Ink / mode come from `setup()` (`hp = 3`). Appearance is a snapshot of the source right
now (cloning a shielded ship copies Shield, not the `setup()` Glow). Playhead starts
**clean** (current frame may snap as a still).

| Copied (snapshot) | Fresh |
| --- | --- |
| Sheet / image binding (shared ref) | New registry identity (roster entry) |
| Frame / size / offset / hitbox kind+scale (Sprite); snapped free geometry (Shape, same model) | `setup()` always |
| Pose: `angle`, `scale`, flips, Sprite `tilt` | |
| Paint + interned `visual` via `look_like` | `mode`, timers, click/drag callbacks |
| Current groups (including tags), unless `group=` | Ink empty until `setup()` writes it |
| `visible` | Playhead time |

**Layer is placement, not a copy.** Omit → class constructor default
(`canvas.layers.default` for Sprite / Circle / Rect; Point stays undrawn). Explicit
`layer=None` → undrawn. Same `_USE_LAYER_DEFAULT` path as `Graphic.__init__` — do not
hardcode `"default"`. **Groups copy** unless `group=` is passed (full replacement, not a
merge). Tags are groups, so a tagged-shielded ship copies `"shielded"` — clone a clean
stamp, not a mutated hero.

**Stamp** (`layer=None`) is a docs recipe, not a framework type. Safe when `setup()` is
cosmetic / ink only. If the subclass has `on_update` / `mode` / `every`, **park**
(`active = False`) so the hidden Entity does not tick or `@collide`-enroll. Do not stamp
a `Wasp` whose `setup()` starts AI.

Warm clone vs warm construct: path **1.02×**, atlas **~1.07×** (`look_like` tax). If a
large multiplier shows up, intern sharing is broken — fix that layer, do not special-case
`clone`.

### Current choices / not doing

1. `setup()` always runs — clone is birth, not a photocopy of a running life.
2. `visual` by reference via existing `look_like()`. Do not deep-copy compiled looks
   (would fight GlowFilter batching). Authors replace stamps (`shot.glow = CheapGlow(...)`);
   they do not mutate interned instances in place.
3. No template ownership in the API.
4. `group=` copies unless passed. `layer=` is placement.
5. **No Entity pool.** Explicit acquire/release fights the beginner model; reuse behind
   `destroy()` cannot match `is_alive` / stale refs / `@collide` object targets /
   subclass `setup` without a leaky second lifetime.
6. **No bullet field / SoA** here — different product (“shots aren’t Sprites”). Defer.
7. **No requiring Sheet for performance.** **No `spawn_like` / `Template`.**

Birth intern is not the live-N cliff. That work is [Mass sprite hot path](#mass-sprite-hot-path) below
(one Sprite, no pool, B1 still deferred). Interning layout strips (`cols=` / `fps=`)
is optional later.

Tests: `tests/test_sprite.py` (`TestSpriteClone`, intern / `strip` refusal),
`tests/test_shapes.py` (`TestShapeClone` group/layer). Bench:
`scripts/bench/perf_sprite_spawn.py`. `group["name"]` `__contains__` accepts Sprite (not
Shape-only).

## Auto hitbox (`shape="auto"`)

Code: `scena/atlas.py` (mask + fitters + utility), `scena/sprite.py` (baked local
specs, freeze, shaping, reference-cell mapping), `scena/collision.py` (runtime prims,
proxy). Labs: `scripts/smoke/hitbox.py`, `scripts/bench/perf_sprite_hitbox.py`.
Tests: `tests/test_atlas.py`,
`tests/test_sprite.py`, `tests/test_collision.py`. Collision-facing summary:
[Collision Design.md — Sprite colliders](Collision%20Design.md#sprite-colliders).

A Sprite's collider is a property of the **object**, not of the current animation
cell — unless the author opts in with `hitbox_source="each"`. The fitter policy for
`"auto"` is unchanged (precision-first utility). What changed is **what** it is
pointed at, **how often** it runs, and **which design box** maps locals to world.

### Purpose

`hitbox_shape=` chooses a primitive; `hitbox_source=` chooses the art. The result is baked
on collision enroll (once per reference set, cached) and stays put across `play()`
and playhead ticks. `"auto"` tries several primitives — one circle, inscribed
circles, one ellipse, **two ellipses**, a convex hull, or an axis-aligned
rectangle — and picks the highest **utility**:

```text
utility = quality − λ × runtime_cost
```

**Phantom hits (overshoot) are worse than misses (undershoot).** Quality rewards
a tight fit; precision is raised to 1.5 and clamped to ≤ 1. Runtime cost is the
estimated narrow-phase cost of the baked primitives, so a hull that covers every
leftover pixel still loses to one AABB that is almost as good.

Fitting runs on a downsampled boolean mask (max side 32 px). The chosen shape is
converted to source pixel space, then to pivot-relative local fractions on the
`Sprite` (anchor + scale already folded in), and finally to world-space collision
specs each frame via `Sprite._collision_specs()` × the **reference cell's** design
box (`_hitbox_pose_wh`), not the current blit size.

**Runtime AABB filtering is not sprite-only.** Auto hitbox only chooses *which*
primitives a Sprite bakes. Every enrolled collider (Shape, Sprite, SpatialFx)
already runs through the shared pipeline in `scena/collision.py`:

```text
proxy AABB (cheap closed-form when possible) → broad phase
  → lazy world prims (exact) → prim AABB reject → narrow
```

Non-rect shapes (`Circle`, `Line`, `Ellipse`, `Polygon`, …) each store a world
AABB on their prim and are rejected there before circle math or SAT — the same
prim-AABB gate sprite circles / ellipses / hulls use. Broad-phase proxy may use a
conservative closed-form bound under rotation (circumradius; for a sprite, its local extent box turned by the heading) so spinning bodies
do not rebuild full prims every frame just for the proxy
([Collision rotation / proxy AABB](#collision-rotation--proxy-aabb-2026-08-21)).
That proxy is **not** a classic fat AABB (permanent radius pad) — see the
decision table there. Author API: [Guia da API — Colisão](../docs/pt/guide/index.html#colisao).

### Author contract (current)

All four knobs are constructor kwargs, class look defaults (`_SPRITE_DEFAULT_KEYS`),
live properties, copied by `clone()`, and reserved against `@=` (`_INK_RESERVED`).
`Svg` accepts the same knobs; `"all"` / `"each"` / `"clip"` are degenerate (one frame) and
do not raise.

| Knob | Values | Default | Job |
|------|--------|---------|-----|
| `hitbox_shape=` | `"auto"`, `"rect"`, `"ellipse"`, `"circle"`, `"hull"` | `"auto"` | which primitive |
| `hitbox_source=` | frame index/name, clip name, `"all"`, `"each"`, `"clip"`, or a tuple of clip names | construct frame | which art defines it |
| `hitbox_scale=` | scalar or `(sx, sy)` | `(1.0, 1.0)` | margin; getter always a pair |
| `hitbox_anchor=` | `"center"`, `"bottom"`, `"top"`, `"left"`, `"right"`, or `(ax, ay)` | `"center"` | fixed point on the baked hitbox for scale, pin, and `.tilt` |

**Naming:** naming a shape means **cover the art with that shape** (recall-first).
`"auto"` is the precision-first utility fitter. Multi-prim kinds (`circles`,
`ellipses`, `boxes`) stay internal — `"auto"` may still emit them when they win.

| Kind | Fit | Notes |
|------|-----|-------|
| `"auto"` | `_choose_auto_collider` utility | Unchanged policy/constants; may emit multi-circle / two-ellipse / hull / 1-rect |
| `"rect"` | Silhouette AABB (`fit_bbox`) | Recall 1.0; flat bottom; **not** inscribed `greedy_rects`. Platformer workhorse |
| `"ellipse"` | Ellipse in the silhouette bbox | Tightening of a design-box ellipse; near-square demotes to circle (`max/min ≤ 1.08`) |
| `"circle"` | `fit_circle` (`best_effort=True`) | For roundish things; a bbox-derived circle is ambiguous for tall art |
| `"hull"` | `fit_hull` | Rasterized recall (not hardcoded 1). Hulls are the corners of occupied cells, so they are slightly larger and win less often. The old 257/375 hull count is stale; regenerate with `scripts/smoke/hitbox.py` |

| Topic | Choice |
|-------|--------|
| Bake timing | On collision enroll; frozen across `play()` unless `hitbox_source="each"` (every cell) or `"clip"` (once per clip switch). Cached per `(image token, frame set, force_kind, blit scales)` — shared by every live `Sheet` over that image |
| Multi-rect | **Never** in auto. Cheap static AABB → `hitbox_shape="rect"` |
| Kind lock | `"auto"` + `"each"` / `"clip"`: full utility competition once per reference set (first cell, or each clip switch). Later cells call that fitter only. Cleared when `hitbox` / `source` / the sheet changes. Named kinds are already fixed |
| Atlas override | Frame `hitboxes` in JSON/XML used when hitbox is omitted or `"auto"`, including a locked `"boxes"` refit. Explicit `"circle"` / `"ellipse"` / `"hull"` / `"rect"` ignore them. A once-only multi-frame bake uses the **first** frame of the set; `"each"` uses that cell's boxes |
| Scale / anchor | Folded into the baked locals (not per-frame emit). Circles and ellipses scale as separate families. Circle + `sx≠sy` → axis-aligned ellipse, concatenated with any ellipses already baked; rotated ellipse uses an affine/SVD |
| Platformer recipe | `hitbox_shape="rect", hitbox_source="all", hitbox_anchor="bottom", hitbox_scale=(0.55, 1.0)` |
| Second collider | `sprite.add_hitbox(group=…)` — detection-only [hitbox part](#hitbox-parts): same four knobs, `hitbox_source="each"` default, follows the paint (tilt too). No `hurtbox=` kwarg set on Sprite |
| Lab-only | `force_kind` (`circle` / `circles` / `ellipse` / `ellipses` / `poly` / `box` / `boxes` / `bbox` / `bbox_ellipse`) — not author API |

### Reference frames (`source`)

One rule: **one frame means that frame; several frames mean their union.**

| Value | Meaning |
|-------|---------|
| omitted | the sprite's **construct frame** (`frame=` kwarg, else 0) |
| `3` / `"Idle__004"` | that one frame |
| `"correndo"` | union of that clip's frames |
| `("walk", "run")` | union of those clips only (empty tuple raises; unknown name raises) |
| `"clip"` | union of the **currently playing** clip; rebake on clip switch only. No clip playing → construct frame (the still key is that frame, not the live `frame`). Opt-in, not the default |
| `"all"` | union of every frame in this Sheet's **registered clips**. No clips (fleet stills) → construct frame. Not every cell of a shared atlas |
| `"each"` | re-fit on every playhead tick (old per-frame behaviour) |

Defaulting to the construct frame (not "whatever is showing at enroll") keeps the
bake deterministic if `play()` runs before `collidable`.

`source` is checked when it is written. If the sheet later drops that clip
or frame, bake (`_ensure_auto_baked`, and the pin target) catches `ValueError` /
`IndexError` / `KeyError` and uses the construct frame. One `RuntimeWarning`
per sprite. It does not raise out of `CollisionSystem.step()`.

**Union** (`union_mask_for_frames`): hole-filled masks aligned by **pivot in source
space**, then fitted **once**. Not a union of fitted shapes. Authored atlas boxes
bypass the fitter, including a locked `"boxes"` refit under `"each"` / `"clip"`.
A multi-frame `source` that bakes once uses the first frame of the set
(unioning authored multi-box sets would produce multi-rect, which auto bans).
`"each"` uses the current cell's boxes. Explicit `"circle"` / `"ellipse"` /
`"hull"` / `"rect"` ignore authored boxes.

Runtime writes are supported (`heroi.hitbox.source = "pulando"` then back to `0`).

### Anchor, scale, and world mapping

`hitbox_anchor` names a point on the fitted local AABB **before rotation and flip**.
Strings are presets. A numeric pair uses the same y-up mapping and is **not**
clamped to `[-1, 1]` (extrapolation is the point past the edge). Preset writes
round-trip as the string; numeric writes round-trip as `(ax, ay)`.
`nan` / `inf` raise `ValueError` (same finite rule as `hitbox_scale` and
`art_angle`). `offset=(dx, dy)` is finite the same way.

| Anchor | Pair | Point |
|--------|------|-------|
| `"center"` | `(0, 0)` | `(cx, cy)` |
| `"bottom"` | `(0, -1)` | `(cx, ymin)` |
| `"top"` | `(0, 1)` | `(cx, ymax)` |
| `"left"` | `(-1, 0)` | `(xmin, cy)` |
| `"right"` | `(1, 0)` | `(xmax, cy)` |
| — | `(-0.5, 0.2)` | left of center, slightly high |

`.tilt` rotates about this point (the resolved pair, not the spelling). It does not
move `center`. The pivot is the anchor on the **baked** local AABB (after pin
and `hitbox_scale`), mapped through the hitbox pose box — the same point the
collider uses. It is not a point on the PNG rectangle. The pivot is the anchor
**as drawn**: paint flips the cell first (innermost `scale(fx, -fy)`) and tilts
after, so under `flip_x` / `flip_y` the pivot mirrors with the emitted collider
(`_tilt_pivot_local` applies `_apply_local_flip`). An unmirrored pivot leaned a
flipped sprite with a side anchor or `offset` about a point inside its box
(fixed 2026-09-24; `test_tilt_pivot_is_collider_anchor_under_flip`). Transparent padding around
the art stays in the file; Scena does not crop it on load, and `height=` / `width=`
/ `size=` still mean that canvas.

Three jobs:

1. **`hitbox_scale` scales about the anchor**, so `(0.55, 1.0)` + `"bottom"` narrows
   without lifting the feet.
2. **The anchor is pinned to the alpha AABB of this bake's frames** (`source`:
   the construct frame, a named clip, `"clip"`, `"each"`, `"all"`, or a clip tuple).
   Not every cell in the sheet, and not a wider clip the bake did not use.
   When the reference frame has authored boxes, the pin target is those boxes
   (`boxes_to_local`), not the mask bbox, so `"bottom"` sits on the authored
   box. No authored boxes → mask bbox. `"center"` does not translate either
   way. A rect of those same frames barely moves; a circle or ellipse still
   lines its anchor up with that target. Feet stay put across clip changes
   only when the bake itself does not change (`"all"` or a fixed clip name).
   `"clip"` refits per clip, so the foot line follows that clip.
   A rebake that grows or shifts the collider into a previously clear partner is
   pushed back across that face ([Collision Design.md — Unswept bounds](Collision%20Design.md#unswept-bounds)).
   That is not a walker: `"each"` still flickers `"bottom"` as cells change.
   Platformers keep `hitbox_source="all"`.
3. **`.tilt` rotates the art about that baked point** and leaves `center` where
   the solver put it. A bare number only rotates. `"ground"` and
   `tilt = <TouchingContact>` with `side == "bottom"`, when the anchor is the
   bottom face (`"bottom"` or `(0, -1)`), also move the paint along
   `contact.normal` until that anchor lies on the plane through `contact.point`.
   The tangential part is dropped, so a hull toe does not slide the art
   sideways, and on flat ground the shift is zero. On a slope it closes the
   gap between the floating bottom-centre and the ramp. `"center"`, `"top"`,
   and the side anchors are not seated. `"ground"` is angle `0` and no shift
   with no bottom contact.

`hitbox_scale`: write a scalar (broadcasts) or a pair; read is always `(sx, sy)`;
both components `>= 0` — `0` collapses that axis of the collider, a negative value raises `ValueError` (also reject `bool` / `None` / 1- or 3-tuples).

Shaping is folded into the bake (`_apply_hitbox_shaping`), not `_collision_specs`
emit — a rotated ellipse under non-uniform scale needs an SVD once, not per frame.
Circles and ellipses are shaped independently. Uniform scale keeps circles as
circles and still scales ellipses that were baked beside them. Non-uniform
scale turns circles into axis-aligned ellipses and concatenates those with the
scaled original ellipses. One family is never written over the other.

**World mapping.** Locals are fractions of the reference cell (`_hitbox_ref_src_w/h`).
`_collision_specs` and the proxy multiply by `_hitbox_pose_wh()` — **that** cell at
the sprite's one scale (`_du_per_px`, plus pose `scale`) —
**not** `_pose_source_wh()` (the current cell). `play()` / `frame=` move drawn
`width`×`height` to the new cell; the collider does not.
`"each"` rebakes every cell and refreshes the ref. `"clip"` does that once per
clip switch. With nothing playing, the `"clip"` key is
`("still", construct_frame)`, so a still `frame=` write does not rebake.

A baked circle stores `nr = r / src_w`. Emit uses `rx = |nr|·w` and
`ry = |nr|·h·(src_w/src_h)`. When the design box matches the cell aspect,
`rx == ry` and the prim stays a circle (including a zero radius). When
`width=` and `height=` stretch the box, the prim is an ellipse aligned with
that box, rotated with the sprite. Axes within `_AUTO_ELLIPSE_CIRCLE_RATIO`
(1.08) demote back to a circle via `ellipse_as_circle`.

The local AABB of a rotated ellipse uses the pose aspect `w/h`
(`_hitbox_pose_wh`), so the pin matches that emit under stretch. A circle's
local AABB still uses the reference-cell aspect, because `nr` is a width
fraction. Collapsed pose (`w` or `h` near 0) keeps the reference-cell aspect.

If the bake yields no prims (fully transparent, or a placeholder), emit falls
back to the design box. `hitbox_shape="circle"` is an inscribed circle
`r = min(w, h) / 2`. `hitbox_shape="ellipse"` stays an ellipse (or a circle when
near-square). `hull`, `auto`, and `rect` stay the design-box AABB — a
placeholder stays conservative. Non-empty bakes return before this fallback.

### Hitboxes: one type

Every collider a Graphic answers with is a `Hitbox` (`hitbox.py`). The **main**
hitbox is `graphic.hitbox` — the *body* in engine words: it stands, meets
walls, and is pushed by `resolve()`. **Parts** (`add_hitbox`) are detect-only
extras. All of them read the same knobs:

```python
hero = Sprite(ninja, hitbox_shape="rect", hitbox_source="all",
              hitbox_anchor="bottom", hitbox_scale=(0.55, 1))   # Sprite(hitbox_X=) → hero.hitbox.X
hurt = hero.add_hitbox(group="hurt", scale=(0.6, 0.9))          # add_hitbox(X=)  → hurt.X
hero.hitbox.scale = (0.55, 0.6)      # crouch
hero.hitbox.box.width                # measure any hitbox
hero.hitbox.active = False           # main off, parts on (ghost); collidable = all off
hero.hitboxes                        # (hero.hitbox, hurt)
```

| Topic | Rule |
|-------|------|
| Knobs | `shape` / `source` / `anchor` / `scale` / `active` / `box` on every hitbox. The Sprite constructor spells the main ones `hitbox_shape=` / `hitbox_source=` / `hitbox_anchor=` / `hitbox_scale=` (a Sprite has its own `scale` / `anchor`): one rule, the prefix names *which* hitbox. `add_hitbox(shape=, source=, anchor=, scale=)` has none |
| Main view | `_MainHitbox`, made once per Graphic and cached (`_main_hitbox_of`). A view: knobs forward to the host's `_hitbox_*` state (`Sprite._set_hitbox`, `_set_hitbox_source` / `_anchor` / `_scale`). Not a part: `_is_hitbox_part = False`, never in `_LIVE_PARTS` |
| Roles | The main hitbox answers for the Graphic's own groups (`sprite.tag`). `hitbox.group` reads them — the Graphic's groups **minus** those a part claims (the part answers for those) — and `hitbox.tagged(name)` is `name in hitbox.group`; `tag` / `untag` / `add_to_group` / `remove_from_group` raise (one spelling for writes: `sprite.tag`). No `px_rect` / `px_circle` (fence below). `remove_hitbox(sprite.hitbox)` raises (points at `.active`). Parts never resolve (unchanged). `@collide(hero.hitbox, …)` / `resolve(hero.hitbox, …)` raise: name the actor — one spelling (`_check_pair_sides`) |
| `.active` (main) | Off → the host's prims are `[]` (`_snapshot_shape_uncached` checks `_main_hitbox_off`; `_proxy_aabb_for_shape` returns `None`), so the proxy goes invalid: no pairs (exits fire), unnamed queries skip it, `resolve` skips it, `touching_*` clears, `floor_below` → `None`. Parts keep their own colliders. Epoch bump on change. Linked `hitbox["active"] @=` reuses `_LINKED_PARTS`. `collidable` stays the master switch (every hitbox) |
| Shapes | `rect.hitbox` is the geometry: `.shape` reads the kind (`"rect"`, `"circle"`, …); `source` / `anchor` / `scale` raise ("its own geometry"). `.box` and `.active` work; with one hitbox `rect.hitbox.active` coincides with `collidable` — the one-hitbox case of the rule, not a second spelling. `Text` has no hitbox (`_has_no_hitbox`): `.hitbox` raises |
| `hitboxes` | All of them, main first: `(sprite.hitbox, *parts)` |
| Dead / removed | Reads keep answering (knobs, `is_alive` False, `host` None, `box` None) — like a dead actor's pose. **Every write** (knob setters, `active`, `px_*`, group verbs, `["active"] @=`) raises `DestroyedError` through one check (`Hitbox._refuse_dead` → `_dead_hitbox_error`): a removed part says so; a destroyed host names the destroy site (the main hitbox reuses `_refuse_if_destroyed`). Before, part knobs wrote silently, `source` / `px_*` raised `RuntimeError`, and the main hitbox's `active` did nothing. `TestDeadAndReadOnly` discovers the writable set, so a new setter that skips the check fails |
| Read-only fields | `box`, `host`, `is_alive`, `layer`, `group`, and `sprite.hitboxes` refuse with a Scena sentence naming what to write instead (`_read_only`), not Python's "property … has no setter" |
| Old names | `Sprite(hitbox=)` / `hitbox_from=` (and class keywords) raise with the new keyword (`_SPRITE_CATALOG_HINTS`). `sprite.hitbox_scale` / `_anchor` / `_from` / `_shape` / `_source` raise on read **and** write (`Sprite._RETIRED_ATTRS`, checked in `Entity.__setattr__` / `__getattr__` before ink — they would otherwise become ink and do nothing). `add_hitbox(hitbox_scale=)` and `hb.hitbox_*` / `hb.width` raise with the new spelling (`hitbox._RETIRED_KNOBS`) |
| Cost | Pay when used: the view is lazy and cached; the only per-step addition is one attribute check in the prim snapshot and the proxy |

Tests: `tests/test_hitbox_model.py`.

### Measuring a sprite

Every read is a `Box` snapshot of the **current frame at the current pose** —
no frame argument. The frame question answers itself: stable sizes come from
the main hitbox (its default `source` is frozen), visual sizes follow the cell.

| Read | Measures | Frame |
|------|----------|-------|
| `sprite.width` / `height` | The size knob (construct cell × scale intent; writes rescale) | fixed |
| `sprite.box` | The drawn cell, transparent padding included, where it is drawn (pivot, `offset`, flips, `scale`: `_oriented_frame`) | the one on screen |
| `sprite.hitbox.box` | The main collider as the engine uses it: screen-aligned bounds of `snapshot_shape` prims (`include_off=True`: measured even when inactive) | its `source` (default: frozen) |
| `hb.box` | That part's collider; `None` on a frame with no collider | its `source` (default: the one on screen) |
| `sprite.art_box` | Opaque pixels of the cell on screen: the cached per-cell alpha bbox (`auto_collider_for_frame(force_kind="bbox")`) placed like the drawing | the one on screen |

`box` and `art_box` carry the heading as their angle and the sprite's names
(like `.box`, G7); hitbox boxes are screen-aligned (a hull or circle has no
orientation). None of them enroll the sprite. `floor_below(dx=)` wants
`hitbox.box.width`, not `box.width`. Tests: `tests/test_sprite_measure.py`.

### Hitbox parts

The Sprite's main hitbox (`sprite.hitbox`, set with `hitbox_shape=` …) is the
**body**: one stable collider for standing, walls, and `resolve()`. Extra
colliders are **parts** — detection-only, owned by the Sprite:

```python
hero = Sprite(
    ninja, group="hero",
    hitbox_shape="rect", hitbox_source="all",
    hitbox_anchor="bottom", hitbox_scale=(0.55, 1.0),
)
hurt = hero.add_hitbox(group="hurt")   # shape="auto", source="each"

resolve(hero, "floor")                 # the body
@collide("bullet", "hurt")             # the part answers
def shot(bullet, target, info):        # target is hero; info.b_hitbox is hurt
    ...
```

| Topic | Rule |
|-------|------|
| Object | `Hitbox` (`hitbox.py`): not an Entity / Graphic, no pose, no draw, no ink. `Hitbox(...)` raises — `add_hitbox` makes one. `sprite.hitboxes` (read-only tuple, main first), `sprite.remove_hitbox(hb)`. Round 1 hosts: Sprite and Svg |
| Knobs | Same four as the body, same parsers: `shape=` (`"auto"`), `source=` (**`"each"`** default), `anchor=`, `scale=`; live properties (`hb.shape`, …), plus `hb.box`. Plus `active=` / `.active` (author switch, or linked: `hb["active"] @= fn`), and `px_rect=` / `px_circle=` in place of the art knobs ([round 2](#pixel-shapes-and-linked-active-round-2)). Unknown kwargs raise `TypeError` |
| Bake | The body's own methods: `_HitboxBakeMixin` holds them, `Sprite` and `Hitbox` both inherit it. A part holds its own `_hitbox_*` state and forwards the read-only host protocol (`_sheet`, play state, size intent). Frame mapping is the body's for the same `source` |
| Empty bake | No collider on that frame (`[]`) — no design-box fallback. A transparent cell or an `"each"` frame without art makes the part absent; `@collide` / `@collide_exit` fire as it appears / disappears |
| Follows the paint | Pose, heading / `art_angle`, flips, `scale`, `offset`, current cell, **and `tilt`** (the `"ground"` / contact seat too). The body stays upright. Paint is a rotation by `draw + tilt` plus a translation (pivot, seat), so `_emit_baked_specs` places part locals exactly as it places the body's. Transients and looks do not move parts |
| Groups | `group=` names the groups the part **claims**. The host joins them (`tagged`, `group[...]`, `until_empty` unchanged); collision lists the part's collider under a claimed tag instead of the body's (`_tag_item` in `_try_enroll_item` / `notify_group_remove`). One answer per `(host, group)`: two parts claiming one group raise. The claim persists: `hero.untag("hurt")` takes the part out of play (i-frames), `hero.tag("hurt")` brings it back. `hb.remove_from_group` / `remove_hitbox` drop the claim, and the host's membership only where the claim added it (`Hitbox._added`): a boss built with `group="enemy"` stays in `"enemy"` when a weak spot claiming `["enemy", "weak"]` is removed (graphics review HP13, decision 5). `remove_hitbox` on a destroyed host raises `DestroyedError` (HP12). `hb.group` is the claim set; `add_to_group` / `remove_from_group` / `tag` / `untag` / `tagged` mirror Entity |
| Sides | Naming the Sprite (`@collide(x, hero)`), `ANYTHING`, and `on_collide*` mean the **body**. A part is reached by a group it claims or by the `Hitbox` object (`@collide("bullet", hurt)`). Handlers always get the host; `info.a_hitbox` / `info.b_hitbox` name the part (`None` = body). A sprite never collides with its own parts, and two parts of one sprite never pair |
| Detect only | `resolve()` / `resolve_now()` raise `TypeError` for a `Hitbox` side. A **group** a part claims is a legal resolve side: `resolve` moves the members' **bodies** (weak-spot boss + walking wasps in one `"enemy"` group), while `@collide` on that group uses the part. `info.push_apart()` / `bounce_apart()` / `resolve()` raise on a part contact (`normal`, `point`, `depth` stay readable). Parts never feed `touching_*`. Tags couple detection and resolution: `boss.untag("enemy")` leaves both — toggle detection (i-frames) on a group that is not a resolve side |
| Lifetime | Host `destroy()` fires `@collide_exit` for part contacts and kills the parts (`is_alive` False, `host` None); handlers naming a dead part drop with the host. Park (`active = False`) and `collidable = False` switch body **and** parts off; resume re-enrolls them. `hb.active = False` switches one part off (exits fire). A sprite with a part in play is collidable: its body registers too |
| Clone | Parts come from `setup()` (like ink); `clone()` does not copy them, and leaves claimed groups out of the copied `group` so the clone's body does not answer for them |
| Queries | No group (`query_point`, `query_circle`, `query_sector`, `raycast(group=None)`, `collides_with()`) → bodies only. `raycast(group="hurt")` / `query_sector(..., group="hurt")` / `collides_with("hurt")` hit parts. A Graphic origin is the caster and is skipped, parts included. `ignore=` adds a body, a tag, or a live group (a tag skips the host and its parts). A probe never hits its own parts |
| Cost | ~11–12 µs per part per `step()` on this machine (~4× on the target): 20 animated sprites with a silhouette part add ~0.26 ms, 100 add ~1.2 ms (`scripts/bench/perf_hitbox_parts.py`). Fine for heroes, bosses, and a squad; a 100-sprite fleet that only needs one collider should keep the body. Proxy: body extents placed by paint (no prims until overlap) — [Collision Design.md — Hitbox parts](Collision%20Design.md#hitbox-parts) |
| Debug | `show_colliders` draws parts **cyan**; resolve bodies gold, other detect-only colliders green (`_debug_color_for`) |

`Track(sprite)` stays the live **outline** (riders, drawing). It is a Track —
its collider is the stroke ring — and is not taught as a hurtbox.
`sprite.silhouette` is gone: it was a second spelling of `Track(sprite)` that
hid a cached registered Track on the sprite.

#### Pixel shapes and linked `active` (round 2)

Attack boxes, weak spots, a sword tip: a part whose shape the author places
by hand, switched on by the animation. Three additions, each usable alone:

```python
GOLPE = quadros("Attack")[4:7]         # the frames where the sword is out

espada = heroi.add_hitbox(group="ataque", px_rect=(430, 180, 90, 80))
espada["active"] @= lambda: heroi.showing(GOLPE)

nucleo = chefe.add_hitbox(group="inimigo", px_circle=(64, 40, 12))   # weak spot, always on

@collide("ataque", "inimigo")          # enter on frame 4, exit after frame 6
def golpe(atacante, alvo, info): ...
```

A part answers three questions, each with one spelling:

| Question | Answer | Default |
|----------|--------|---------|
| Who does it answer for? | `group=` (round 1) | nothing |
| Where is it? | The art (`hitbox_shape=`, `hitbox_source=`, `hitbox_anchor=`, `hitbox_scale=`) **or** one hand-placed shape (`px_rect=` / `px_circle=`) | the art, per frame (`"each"`) |
| When is it on? | `.active`: a bool the author writes, or a function linked with `hb["active"] @=` | on |

Dropped from the first draft: `clips=` (the art already follows clips through
`source`, and a clip-level switch is state the author already holds),
per-clip shape dicts, frame positions inside a clip, and pixel coordinates
measured from the pivot. Pixel shapes are for parts only: the body gets its
stability from its four knobs.

**`px_rect=` / `px_circle=` — one shape in the frame's pixels.**

| Topic | Rule |
|-------|------|
| Units | Pixels of the frame as the image editor shows it: origin top-left, x right, y **down**. `px_rect=(x, y, w, h)` with `(x, y)` the top-left corner (the atlas `hitboxes` format); `px_circle=(x, y, r)` with `(x, y)` the centre. These are addresses in an image, not Scena coordinates. World and sprite space stay y-up; the `px_` prefix marks the image space |
| Which frame | The cell on screen. One file per frame, or an Aseprite frame: the numbers the editor shows. A grid sheet (`cols=` / `rows=` / `cell=`) opened as one image: subtract the cell's origin (column × cell width, row × cell height). A packed atlas: the original, untrimmed frame; the engine undoes trim and rotation |
| Fixed to the drawing | Converted through the current cell's pivot (`boxes_to_local` / `circle_to_local`), then placed like any part. Everything that moves the drawing moves the box: `Sheet(anchor=)`, an atlas pivot, `clip(offset=)` (already folded into the pivot), `Sprite(offset=)`, size / `pixel_size` / `scale`, flips, rotation, and `tilt`. The author never adds an offset |
| Cells of other sizes | The same numbers point at another spot in a cell of another size (ninja Idle is 232 px wide, Attack 536). A px part is meant for the frames where it is on, so link `active` to them. There is no size check: the switch is a function, not a declared set of cells. `show_colliders` shows a misplaced box |
| Not clamped | May pass the cell's edge (a blade past the art, a box bigger than the PNG) |
| One shape | `px_rect=` **or** `px_circle=`, one per part. Another shape is another part |
| Errors | Both px kwargs → `TypeError`. A px shape with `hitbox_shape=`, `hitbox_source=`, `hitbox_anchor=`, or `hitbox_scale=` → `TypeError` ("a px shape is placed by hand; drop hitbox_source="). Wrong length or a non-number → `TypeError`; `nan` / `inf` → `ValueError`; negative `w` / `h` / `r` → `ValueError`; 0 is a collapsed size (the Scena size rule) |
| Live | `hb.px_rect` / `hb.px_circle` read the tuple or `None`. Writing one sets it and clears the other. Writing `None` to the one in use returns the part to the art (`hitbox_shape="auto"`, `hitbox_source="each"`). Writing an art knob while a px shape is set → `TypeError` naming `px_rect = None` |
| Hosts | Sprite sheets. An `Svg` host raises `TypeError` (its units are the viewBox's; deferred) |
| Cost | Converted once per distinct `(src_w, src_h, pivot)`; a new cell with the same geometry reuses it. No fitter, no mask |

**`sprite.showing(frames)` — is one of these frames on screen?**

| Topic | Rule |
|-------|------|
| Value | The `source` selector grammar without its keywords: a clip name, a frame index, a frame name (file or atlas name), or a tuple / list mixing them. A clip name means that clip's cells. `"each"` / `"clip"` / `"all"` → `ValueError` (bake modes, not frames). Unknown names and out-of-range indices raise with the `source` wording |
| Answer | `True` when the current cell is in the set. It goes by cell identity, so it stays right after `yoyo`, `resume=`, `next=`, and an interrupted clip. A cell shared by two clips counts in both. A still sprite answers for its `frame` |
| Cost | The resolved set is cached per `(sheet, selector)`; a call is one set lookup |
| Scope | A plain read, not hitbox-only: a footstep sound on frames 3 and 7, dust on landing frames. It replaces `heroi.frame in {ninja.frame_index(n) for n in …}` |

**Linked `active` — `hb["active"] @= fn`.**

| Topic | Rule |
|-------|------|
| Spelling | `hb["active"] @= lambda: …` (bracket, like every Scena `@=`). `hb["active"].unlink()` removes it; the switch keeps its last value. `hb.active = x` while linked → `LinkedAttributeError` naming `unlink()`. `hb.active = lambda: …` → `CallableAssignError` naming `hb["active"] @=`. `add_hitbox(active=lambda: …)` → `TypeError` (one spelling). Only `active` links: `hb["hitbox_scale"] @= …` → `TypeError` naming `active` |
| Machinery | A **polled link**, not a graph edge, in the same family as group formulas (`group["x"] @=`, recomputed on read). No Container source is needed (`heroi.frame` comes from the clock) and the source is not parsed. The function runs where the value is used: at the start of each collision `step()`, before proxies (so collision sees this frame's value, after `update`, `on_update`, and any `play()`), and on every read of `hb.active`. A query that names a claimed group (`collides_with("hurt")`, `raycast(group=…)`, `query_*(group=…)`) refreshes the part it reaches, the same way it refreshes the pose; `resolve` never uses parts, so it needs none. It also runs once at `@=`, so a broken function fails on that line (and a failed `@=` links nothing) |
| Result | A flag: a bool, or 0 / 1, like every Scena flag; anything else → `TypeError` naming the part's `add_hitbox` line. A change goes through the `active` setter: off fires `@collide_exit`, on fires `@collide` |
| Errors | An exception in the function propagates from `step()` with a note naming the part and its `add_hitbox` line (as `@when` names its handler). A function that reads its own `hb.active` raises `ValueError` ("the formula reads itself") |
| Purity | Read, don't write: the function runs inside the collision step. Writing pose or groups there is an author bug (documented, not policed) |
| Skipped | Not called while the host is parked, `collidable = False`, or destroyed (the part is out anyway). The first step after resume calls it again. A destroyed host's parts leave the link index at once |
| Cost | One Python call per linked part per step, plus enroll work only when the value changes. Measured with 100 animated sprites, each a `px_rect` part linked to half the cells: +0.48 ms/step over body-only (~4.8 µs per part here, ~×4 on the target), cheaper than an `"each"` silhouette part (~11 µs; `perf_hitbox_parts.py --mode all`). No links: one empty-set check per step |
| Clone | `clone()` copies no parts (round 1), so no links |

**Recipes.**

- **Attack frames:** the example above.
- **I-frames:** `dor.active = False`, then `heroi.after(1.5, religar)` sets it back. A plain write; time, not animation, decides.
- **Not `@when` / `@on_change`:** they run in the flush after collision, so the box turns on one frame late and off one frame late.
- **An `update` line** (`espada.active = heroi.showing(GOLPE)`) works, with two traps the link removes: a `play()` later in that frame (or in `on_update`) lags it a frame, and if the line lives in a mode the hero leaves mid-attack (hit, death), nothing writes `active` again and the box can stay on.

**Fences.**

- `add_hitbox(active=fn)`: never; the link is `hb["active"] @=`.
- `clips=` / a data frame gate on `add_hitbox` (`showing=`): only if `showing()` formulas prove heavy in real scripts.
- Pixel shapes on the body: only if the four knobs cannot express a real pack's body.
- Pixel coordinates from the pivot: never; the numbers are the editor's.
- Polled links on other flags: `visible` decided 2026-10-15 — it links as an appearance link, pulled where it is used (start of hover, head of the draw; [Reactive Design — Appearance links](Reactive%20Design.md#appearance-paintstate-internal)). `collidable` stays out (contacts laws). The sheet `frame` is deferred (a hot path; `play()` would be exclusive with it).

**Implementation.**

- **px bake** (`scena/hitbox.py`): a `_px` slot (`("rect", t)` / `("circle", t)` / `None`). While it is set, the art slots hold their defaults (`"auto"` / `"each"` / `"center"` / `1`) so the per-cell sync path runs.
  - `Hitbox._ensure_auto_baked` bakes through `boxes_to_local` / `circle_to_local` against `_sheet._frame_at(cell)`, the pivot-applied cell (anchor, atlas pivot, `clip(offset=)` folded in).
  - The bake is keyed by `_px_geometry_key` = `(src_w, src_h, pivot_x, pivot_y)`.
  - `Hitbox._sync_auto_hitbox_frame` bumps the part epoch only when that key changes, so same-size cells keep the pose cache warm.
  - Shaping, `_emit_baked_specs`, paint placement and the proxy are unchanged.
- **Explicit art knobs:** `add_hitbox`'s art knobs default to the `_ADD_HITBOX_UNSET` sentinel (`scena/sprite.py`, shared as `hitbox._UNSET`), so a px shape refuses even an explicit `hitbox_source="each"`. `Sprite.add_hitbox.__signature__` shows the readable defaults.
- **Linked `active`:**
  - `hb["active"]` returns `_ActiveRef` (`__imatmul__`, `unlink()`, `.linked`). `Hitbox.__setitem__` accepts only that ref (Python's `@=` write-back, as `GroupOperator.__setitem__` does).
  - The setter internals are `_apply_active`; the formula runs in `_refresh_link` under the `_link_busy` re-entry guard.
  - Sites for the error notes come from `_author_site()`: `_site` at `add_hitbox`, `_link_site` at `@=`.
- **Link index:** module-level `hitbox._LINKED_PARTS` (a WeakSet; it survives `reset_collision_system()`).
  - `CollisionSystem.step()` calls `_refresh_linked_parts()` right after `_prune_dead()`. It drops dead parts and refreshes the rest.
  - `forget_destroyed_item` removes a destroyed host's parts.
  - `_query_collider` calls `_refresh_part_link(item, tag)` before `_tag_item`.
- **`showing()`:** `_parse_frame_selector` (`scena/sprite.py`) resolves a selector to a frozenset of cells, cached in `Sheet._selector_cache`; `Sheet.clip()` clears the cache.

**Tests.** `tests/test_hitbox_round2.py`:
- `TestPxShapeApi`, `TestPxShapePlacement` (the oracle: a `px_rect` equals an atlas box with the same numbers, also on a trimmed frame), `TestPxShapeCache`.
- `TestPxShapeProperty`: Hypothesis over rotation, flips, tilt, offset and scale; the proxy holds the prims. Atlases are cached by path and file stamp; each example still writes its atlas under a new file name (two rewrites within the file system's timestamp resolution can share a stamp).
- `TestShowing`, `TestLinkedActive`.
- `TestLinkedActiveFrames`: real frames through `SystemWorld`. It checks enter on the first strike cell, no lag when `play()` runs in `on_update`, and that switching clips mid-swing turns the box off.

World machine (`tests/test_sys_hyp_world.py`):
- sprites carry a linked part;
- invariant `linked_hitbox_parts_are_alive`;
- census key `hitbox.linked_parts`.

**Still deferred:** named per-part atlas boxes (Aseprite slices,
`box="fist"`; today's atlas boxes are flat and unnamed), Svg px shapes, Shape
hosts, polled links on other flags. Round 1 already guarantees what these build
on: an empty bake means absent, `.active` is the switch, enter / exit fire as a
part appears or disappears, and unknown kwargs raise.

**Atlas-authored boxes are per sprite, not per part.** Per-frame `hitboxes` in
the atlas JSON / XML are flat and unnamed, and every `"auto"` bake on the
sprite uses them — the body included (`hitbox_shape="auto"` is the default). An
explicit kind (`"rect"` / `"ellipse"` / `"circle"` / `"hull"`) ignores them.
So today one data-driven box set per sprite is practical: give the body an
explicit kind (`"rect"` for walkers) and let one `"auto"` + `"each"` part read
the authored boxes. Named per-part boxes are deferred. Hand-placed boxes are
`px_rect=` / `px_circle=`, and a frame-accurate attack box is one of those with
`hb["active"] @= lambda: sprite.showing(...)` (round 2, above;
`test_atlas_boxes_feed_auto_bakes_only`).

Tests: `tests/test_hitbox_parts.py`, `tests/test_hitbox_round2.py`. Smoke:
`scripts/smoke/hitbox_refinements.py` (page 5) and `scripts/smoke/hitbox_round2.py`
(round 2, five pages). Pattern (from a platformer sample in development): body `hitbox_source=` a tuple
of standing clips so the wide `Dead` cells do not widen the walker; hurtbox part
`group="dor"` answers robots and `Line` rays; `untag("dor")` = i-frames.

### Invalidation

| Event | Re-bake? |
|-------|----------|
| `play()` / playhead tick | **only if** `source == "each"` (every cell) or `"clip"` (clip name changed, not every tick) |
| `frame=` write | `"each"`. `"clip"` rebakes when playback stops (the key leaves the playing clip). A still `frame=` write does not: the still key is the construct frame |
| `shape` / `source` write | yes (cache hit after first time); clears the locked auto kind |
| `hitbox_scale` / `hitbox_anchor` write | no — re-derive locals, recompute proxy radius, bump epoch |
| `width` / `height` / `scale` | no — normalized coords; mapping uses the sprite's scale (`_du_per_px`) + reference cell |
| `play()` / `frame=` to a cell of another size | no — only `width` / `height` follow the cell; the scale and the body mapping do not change |
| sheet / `Svg.svg` swap | yes; clears the locked auto kind |
| another `Sheet` over the same image | no — shares the image token and its bakes |
| last `Sheet` holding an image dies | bakes for that token drop (`release_sheet_token`); a reused `id(image)` cannot hit them |

`_sync_auto_hitbox_frame` is a no-op outside `"each"` and `"clip"`. `"auto"` +
those two lock kind after the first competition of the reference set. The proxy
is the AABB of the extent box `(ex · w, ey · h)` turned by `_draw_angle()`, plus
`hypot(offset)`: a circle contributes `nr` along x and `nr * src_w / src_h` along
y, so a wide source drawn into a square is not dropped by the broad phase. A
near-square pair that emits as a circle contributes the mean radius, and an
ellipse its turned-box AABB; both depend on the pose aspect, so the extents
rebuild when the hitbox pose box changes (`_hitbox_extents_for_pose`). A non-uniform `hitbox_scale` on a circle keeps that
source aspect in the stored `nry`. `_collision_specs` emits every baked family
(a circle does not hide an ellipse). An empty bake uses `_collision_frame` for
both the proxy and the emitted box.
That box is the broad-phase proxy only. Unswept recovery compares
collision-prim bounds and requires the prims to overlap — a side slide must
not treat the disk past the hitbox as a floor, ceiling, or wall
([Collision Design.md — Unswept bounds](Collision%20Design.md#unswept-bounds)).

### Pipeline

```
source → ordered frame indices
        │
        ▼
union of hole-filled masks (blit placement, reference cell)   or a single frame
        │
        ▼
_downsample_alpha() via mask cache   nearest-neighbour → bool mask
        │
        ▼
fitter for hitbox_shape=  (auto = utility pick; rect = fit_bbox; …)
        │
        ▼
*_to_local() on Sprite       pivot-relative, y-up  (reference cell src_w/src_h)
        │
        ▼
fold hitbox_anchor + hitbox_scale into baked locals
        │
        ▼
_collision_specs()           world-space prims × _hitbox_pose_wh()  (no extra scale at emit)
```

**Cache keys:** single-frame `(image token, frame.x, frame.y, frame.w, frame.h, force_kind)`;
union `(image token, frame-set signature, force_kind)`. Masks are cached separately
by region so a second kind on the same cell does not re-decode. The image token is the
first live `Sheet` token bound to that decoded image, so a fresh `Sheet(path)` per spawn
reuses the bake. It is reference-counted: bakes drop when the last holding `Sheet`
dies (safe against `id(image)` reuse).

Forced `"ellipses"` uses `fit_two_ellipses(..., strict=False)` and falls back
through ellipse → circle → hull → rect so the lab never shows an empty bake.
Forced `"circle"` / `"ellipse"` use `best_effort=True` (quality-maximizing below
the 0.90 precision floor) instead of baking `none`.

### Mask extraction

**Downsample** (`_downsample_alpha`): longer side ≤ `_AUTO_MAX_SIDE` (32);
**nearest-neighbour** (bilinear smears alpha into transparent corners);
`True` where alpha ≥ `_AUTO_ALPHA` (16).

**Hole fill** (`fill_holes`): flood from the mask border. Enclosed transparent
pockets (donut, ring) become opaque; open concavities (U, cross gap, robot
legs) stay empty — matches gameplay intent.

**Union** (`union_mask_for_frames`): hole-filled masks aligned by pivot, at one
scale (every cell's pixels land at the same size — [Scale and registration](#scale-and-registration)),
rasterized to max side `_AUTO_MAX_SIDE`, then fitted **once**. Not a union of fitted
shapes. The `scales=` parameter stays for raw overlays; sprite bakes pass identity.

Soft / anti-aliased edges often explain “looks covered but recall is 0.80–0.90”:
fringe pixels are opaque in the mask but outside a precision-capped fit.

### Candidate fitters

Each returns geometry in **mask space** (y-down) plus `(precision, recall)`.

| Fitter | Idea | Notes |
|--------|------|-------|
| `fit_circle` | Trimmed-mean centroid; percentile radii; max recall among precision ≥ 0.90 | Analytic area `πr²` |
| `greedy_circles` | Largest inscribed disks; prefixes 1…cap are separate candidates | `k≥2` need recall ≥ `_AUTO_CIRCLE_GATE` (0.75); cheapest rotated prim |
| `fit_ellipse` | PCA angle + grid `(ru,rv)`; same precision floor | `ellipse_to_local` **negates** mask angle (y-up) |
| `fit_two_ellipses` | H+V arm split, diagonal nearest-line split, residual | Cost 4; plus/T/X; strict recall floors + redundant-pair reject |
| `fit_bbox` | Occupied AABB of the mask | Author `"rect"`; recall 1.0 |
| `fit_hull` | Convex hull ≤ 8 verts; cheapest vertex whose chord still covers every occupied centre | Rasterized recall. Bridges notches; concavity guard |
| `greedy_rects` | Largest **inscribed** opaque AABB prefixes | Auto offers **1-rect only** if recall ≥ 0.90; **not** author `"rect"` |

### Metrics and selection

Ground truth = opaque pixels in the hole-filled mask.

| Metric | Formula | Penalizes |
|--------|---------|-----------|
| **Precision** | opaque inside shape ÷ shape area (**clamped ≤ 1**) | Overshoot (phantom hits) |
| **Recall** | opaque inside shape ÷ total opaque | Undershoot |

Circle / ellipse / two-ellipse / greedy-circle sets use **analytic** area
(`πr²`, `π·rx·ry`, overlap-adjusted for pairs). Hull uses polygon area. Rects
have precision 1.0 by construction.

```text
quality = clamp(precision, 0, 1) ** _AUTO_PRECISION_EXP × min(1, recall / _AUTO_QUALITY_BAR)
utility = quality − λ × runtime_cost
```

With `_AUTO_PRECISION_EXP = 1.5`, `_AUTO_QUALITY_BAR = 0.90`, `_AUTO_COST_LAMBDA = 0.05`.
Ties break to lowest cost. Hulls with precision &lt; 0.92 get an extra quality
penalty (`_hull_quality`).

**Hard rails:** multi-rect never a candidate; 1-rect needs recall ≥ 0.90;
multi-circle (`k≥2`) needs recall ≥ 0.75; if any candidate has recall and
precision ≥ 0.90, discard winners with recall &lt; `_AUTO_RECALL_FLOOR` (0.75).

**Policy history (why utility won):** cheapest-with-recall-gate favored bad
hulls; quality-then-near-tie-cost still let hulls edge out cheap rects; current
unified utility + multi-rect ban + prefixes + two-ellipse + recall rail.

### Runtime cost model

Heuristic weights in utility (calibrated from `perf_sprite_hitbox.py`; AABB×AABB
and circle×circle are fast paths; OBB / POLY / ELLIPSE use SAT):

| Candidate | Cost |
|-----------|------|
| 1 circle | 1 |
| k circles | k |
| Ellipse | 2 |
| Two ellipses | 4 |
| Hull (poly) | `2 + 0.1 × max(0, verts − 4)` |
| 1 rect (auto, if recall ≥ bar) | 3 (as OBB) |

Lab `force_kind="boxes"` can still emit multi-rect for ablation; auto never does.

### Coordinate spaces

| Space | Axes | Used for |
|-------|------|----------|
| Mask | y-down, origin top-left of downsampled array | Fitting |
| Source | y-down, origin top-left of `sourceSize` / trim rect | `AutoCollider` cache, atlas boxes |
| Local (sprite) | y-up, origin at pivot, normalized by the **reference cell** `src_w`/`src_h` | Baked on `Sprite` (`_hitbox_*`); scale/anchor already folded in |
| World | y-up, design units | `_collision_specs()` output. Baked locals map through the reference pose box (`_hitbox_pose_wh`: the reference cell × `_du_per_px`, pose zoom via `_scale`). `hitbox_source="each"` maps through the baked cell (each cell draws at its own size). The drawn sprite moves `width`×`height` to the cell on `play()` / `frame=`; a frozen collider does not. |

`AutoCollider.kind`: `"circle"`, `"circles"`, `"ellipse"`, `"ellipses"`, `"poly"`,
`"boxes"`, or `"none"`. Unrotated rects emit AABB; rotated rects emit OBB.
Circle / ellipse / hull transform with the sprite pose.

### Design rationale

1. **Reference-set bake, frozen while animating** — numpy on a tiny mask; simple prims at runtime.
   World copies of auto hulls are **lazy** (proxy AABB every frame, SAT verts only
   when AABBs overlap) — [Mass sprite hot path](#mass-sprite-hot-path). Playhead ticks do **not**
   rebake unless `hitbox_source="each"`. Locals map through the **reference cell** at
   the sprite's one scale, so `play()` can change the drawn cell without resizing the collider.
2. **Multiple candidates** — no single primitive fits disks, bars, L, crosses, and X.
3. **Precision over recall** — phantom collisions hurt more than a sliver of missed alpha.
4. **Coverage via analytic prims** — two ellipses (H+V / diagonal) for T/plus/X instead of multi-OBB; multi-circle when utility says so.
5. **Hole fill before fit** — outline / ring art feels solid without manual boxes.
6. **Adaptive counts + prefixes** — “one cheap circle” can beat “perfect hull”.
7. **Utility, not quality-then-cost** — runtime cost is in the primary score.
8. **Always rotation-safe** — no author `may_rotate`; multi-rect never in auto.
9. **One internal policy** — λ / gates / two-ellipse are fixed constants in `atlas.py`.
10. **Cap at 5** — greedy multi-circle (and lab multi-rect) never emit more than five prims.
11. **Atlas JSON/XML boxes** — author override when auto is wrong or already authored.
12. **Proxy broad phase** — one AABB per collider, then prim narrow. Under rotation,
    that proxy prefers a cheap closed-form bound (never tighter than exact) over
    rebuilding world prims every frame — [Collision Design.md](Collision%20Design.md#runtime-cost-mass-sprite-related).
    Spatial grid deferred (object budget is tens–hundreds).

### Lessons from the lab (fixed)

| Failure | Fix |
|---------|-----|
| Tall lasers reported precision 1.0 while covering 3× width | Analytic shape area for circle/ellipse metrics |
| Tilted ellipses mirrored | Negate PCA angle in `ellipse_to_local` |
| Hulls bridged concave gaps (robot chin, crosses) | `precision^1.5`, hull guard, utility, rect/circle prefixes |
| Multi-rect exploded under spin (~4×) | Ban multi-rect in auto; cost 1-rect as OBB |
| Precision &gt; 1 inflated quality | Clamp precision to `[0, 1]` |
| T / plus / X undershoot with one ellipse | Two-ellipse (H+V + diagonal + residual); softer circle gate; recall rail |
| Forced empty bake → full-rect outline | `strict=False` / `best_effort=True` on forced paths |
| X got two overlapping central blobs | Diagonal arm split + redundant-pair reject |
| Stretched `hitbox_shape="circle"` stayed a circle (`ry` phantom) | Emit `rx = \|nr\|·w`, `ry = \|nr\|·h·(src aspect)`; near-square demotes via `ellipse_as_circle` |
| Rotated-ellipse pin used the source aspect under stretch | Local AABB uses pose `w/h` |
| Mixed circle+ellipse scale dropped or skipped a family | Shape each family, then concatenate |
| Empty `hitbox_shape="circle"` fell back to the design-box AABB | Inscribed circle; `hull` / `auto` stay the box |
| Locked `"boxes"` refit ignored per-frame authored boxes | Authored boxes win when `force` is `None` or `"boxes"` |
| `"clip"` still keyed on the live `frame` | Still key is the construct frame |
| `hitbox_anchor` / `offset` accepted `nan` / `inf` | Finite check, `ValueError` |
| Stale `source` raised inside `step()` | Fall back to the construct frame; one warning |
| Pin target ignored authored boxes | Pin uses `boxes_to_local` when the reference frame has boxes |
| Proxy comment said `max(w, h)` | Comment matches `hypot(w, h)` (Cauchy bound). No radius change |
| Fresh `Sheet(path)` per spawn refit every time (~27 ms warm in `assets-1`) | Cache token is per decoded image (first live sheet's token, refcounted holders), not per `Sheet` |

### Known limitations

| Topic | Behavior |
|-------|----------|
| Concave silhouettes | No arbitrary concave polygon; hull bridges notches unless circles / rects / two ellipses win |
| Cross / plus | Under auto, **two ellipses** (H+V) usually win |
| X / × flares | Diagonal arm split covers most; open V / chevron may still prefer hull |
| Thin diagonal scratches | May still get a low-precision hull |
| Downsample | ≤32 px can miss 1–2 px details on large frames |
| Utility undershoot | Cheaper shapes can sit below the 90% recall bar if quality drop &lt; `λ × Δcost` |
| Fit CPU | Greedy circles ~3–4 ms/frame load; collision runtime is the optimization target |
| Semi-transparent art | Threshold + nearest downsample define “solid” |
| Union `"all"` on a character sheet | Registered clips (walk + jump + …) still enlarge the box; narrow with `hitbox_scale` and `"bottom"`. On a shared atlas with **no** clips, `"all"` is the construct frame |
| Cause 5 — round / polygonal bottoms | An ellipse or hull is a poor walker: one contact point, slanted SAT faces. Teach `hitbox_shape="rect"` for bodies that stand. `"auto"` + `"each"` / `"clip"` locks kind so a walk cycle does not flip hull → ellipse → circle |

### Tuning constants (`scena/atlas.py`)

| Constant | Value | Role |
|----------|-------|------|
| `_AUTO_MAX_SIDE` | 32 | Max mask dimension |
| `_AUTO_ALPHA` | 16 | Alpha cutoff (0–255). FrameFx `_FX_ALPHA` matches this |
| `_AUTO_PRECISION_MIN` | 0.90 | Min precision for circle / ellipse / strict two-ellipse |
| `_AUTO_QUALITY_BAR` | 0.90 | Recall that saturates quality; 1-rect gate |
| `_AUTO_PRECISION_EXP` | 1.5 | Precision exponent in quality |
| `_AUTO_HULL_MAX_VERTS` | 8 | Max hull vertices after simplification |
| `_AUTO_HULL_PRECISION_GUARD` | 0.92 | Extra hull quality penalty below this |
| `_AUTO_RECT_CAP` / `_AUTO_CIRCLE_CAP` | 5 | Max greedy rects / circles |
| `_AUTO_TWO_ELLIPSE_MIN_GAIN` | 0.05 | Min recall gain vs single ellipse (strict) |
| `_AUTO_TWO_ELLIPSE_MIN_RECALL` | 0.75 | Absolute recall floor for two-ellipse (strict) |
| `_AUTO_RECT_TARGET` | 0.95 | Stop rects/circles when recall reaches this |
| `_AUTO_RECT_DIMINISH_FLOOR` | 0.80 | Start diminishing-gain early stop |
| `_AUTO_RECT_MIN_GAIN` | 0.02 | Min added area as fraction of bbox to continue |
| `_AUTO_COST_CIRCLE` / `_ELLIPSE` / `_HULL` | 1 / 2 / 2 | Base costs (+0.1 per hull vert above 4) |
| `_AUTO_COST_OBB` | 3 | Auto 1-rect candidate cost |
| `_AUTO_COST_LAMBDA` | 0.05 | λ in utility |
| `_AUTO_CIRCLE_GATE` / `_AUTO_RECALL_FLOOR` | 0.75 | Multi-circle gate / recall-rail floor |
| `_AUTO_ELLIPSE_CIRCLE_RATIO` | 1.08 | Ellipse → circle when axes within this ratio |

**Tuning workflow:** visual review (`app_hitbox_lab.py`, keys `0–6` force kind,
`C` outlines, `R` aggregate report) → corpus fit stats → live-app
`app_hitbox_bench.py --bench` (`--spin`, `--static`, `--all-scenes`) → headless
`perf_sprite_hitbox.py` (`--rotation 45`).

### Corpus results (sprite_tests)

**375 frames** (Kenney `sheet.png` + `rollingBall_sheet.png` + standalone PNGs).
Default auto: avg recall **0.970**, avg precision **0.972**; 46 below 90% recall,
22 below 90% precision. Pick distribution (approx.): hull8 **257**, circle **44**,
ell2 **24**, hull4–7 **40**, ellipse **10**.

Live-app bench (`app_hitbox_bench.py`, 100 overlapping sprites, full Scena loop)
illustrates **cost ordering** (earlier pass; re-run after large policy changes):

- **rect1** is the speed ceiling (one AABB / one OBB) — not a quality substitute.
- **Multi-rect** is the speed floor once anything spins (many OBB/SAT pairs).
- **Multi-circle** is middling — circle×circle stays fast, but ~5× prim count costs.
- **Default auto** lands in the cheap band (near circle/ellipse FPS), never emits
  multi-rect; two-ellipse adds at most two SAT ellipses on T/plus/X art.
- Forced modes are ablations; auto optimizes utility, not max FPS.

Headless stress (`perf_sprite_hitbox.py`, 30 sprites × 200 steps): auto ~0.29 ms
at 0°, ~0.42 ms at 45°; forced multi-rect at 45° ~1.03 ms. Prefer the live-app
bench for real FPS attribution.

### Deferred (auto hitbox)

- Recalibrate λ / OBB multiplier from larger scenes.
- Faster distance transform for greedy circles (fit time).
- Optional concave polygon decomposition / better open-V covers.
- Per-project alpha threshold or “tight / loose” preset.
- Author-facing debug overlay in games (not just the lab script).
- `attach_to` for a general second body (turret on a host). A hurtbox is not this: it is a detection-only [hitbox part](#hitbox-parts) (`add_hitbox`). The sprite's own hitbox stays the walker / resolve body.

## SpriteButton

`SpriteButton(Sprite)` (`scena/sprite_button.py`) packages a game button on one
Sprite: hover / press / disabled **feel**, optional breathing, `on_click`,
sounds, a centered **label** and optional **state art**. Default layer `ui`.
Guia: [SpriteButton](../docs/pt/guide/index.html#ui-sprite-button).

**Feel is draw-time only.** `draw` (the class is `_draws_solo`, never
`_plain_blit` — `Graphic.__init__` seeds that flag True, so the constructor
clears it) wraps the body in a CTM scale about the drawn-box centre plus one
`saveLayer` carrying a ColorFilter (lighten / darken matrix composed over a
`Grayscale` matrix) and alpha — only when not identity. It never writes
`scale`, so the author's pose, tweens and hitbox stay theirs and the click
area does not breathe (no edge flicker). Levels (`_Ease`: hover, press, off,
breathe weight) are **closed-form in time** (`transients._now`, wall clock —
a paused game's menu still animates; `set_now_fn` in tests): each state edge
stores `(v0, target, t0)`, draw evaluates. Several draws per frame paint the
same picture. Breathing is `amp · sin(2π(t − t0)/period) · weight`; the weight
eases to 0 while hovered, pressed or disabled.

**Body routes.** Inside the envelope: active transients → `draw_with_transients`
(the label rides inside through `transients._draw_body` → `_draw_attached`);
an ImageFilter `.glow` / `.shadow` → `canvas._draw_filtered_one` (the same
route a plain sprite takes; a solo `Graphic.draw` would drop it); otherwise
`Graphic.draw`, then `_draw_attached`. Cull: `_cull_pad()` (read by
`_passes_cull`) covers the growth on world layers; `ui` is never culled.

**Press.** `clickable` is always True (the feel works without a handler and a
press never falls through). `_accepts_press` is `enabled`: a disabled button
swallows the press ([Shapes — Press lifecycle](Shapes%20Design.md#press-lifecycle-pointer_pressed)).
`_fire_click` checks `enabled`, plays `click_sound` through the **global**
`play_sound` (it survives a `change_act` the click triggers) and calls the
handler; `hover_sound` is owned (`self.play_sound`). `on_click` is a property
with an fset, so `@click`, `def on_click` in a class body and assignment all
work.

**`enabled` is linkable.** `_property_link_extra = {"enabled"}` and
`_property_link_flags` make `button["enabled"] @= …` a `_FlagPropertyAnchor`
(write-through like `angle`, bool-checked); `enabled=lambda: …` links at
construction. A plain Sprite keeps the `enabled` → `active` near-miss.

**Click area: convex hull of the rest art.** `_hit_test_xy` maps the pointer to
blit-local space (`Sprite._pointer_local`: heading, tilt seat, tilt undone; then
flip) and tests a convex hull built from `_display_mask` cells of the rest
frames (the playing clip's frames, else `frame`), cached on
`(frames, sheet, pixel scale, offset)`. Holes and concave notches click; a
transparent bounding-box corner does not. State art never enters the key.

**Label = a `Text` part drawn by the button.** `Text(…, layer=None,
stack=False)`, `owner = button`, attr name `label_text`. As a part it leaves
and parks with the button and refuses `destroy()` / tags; `_draws_parts` on
the owner makes `label_text.layer = …` raise. Its pose is **relative**: the
button draws it after `translate(label box centre) · rotate(draw angle) ·
scale(|scale| · fit)` — the draw angle, not `angle`, so a flip never mirrors
or inverts the text. `label` is the string shortcut (same word as HUD
`Button.label`); `label_text` is the object. Shrink-to-fit is a draw-time
factor `min(1, 0.88 · box / glyph box)` (a margin so text never touches the rim); `font_size` reads what the author set. At
`theme.menu_min_font_size` it clamps and warns once (Menu precedent). The
label box is the drawn rect minus `label_inset` (scaled with the pose).

> **Rejected: linking the label's pose to the button** (`label["center"] @=
> lambda: button.center…`). The owner → part structural edge makes it a
> `CircularReferenceError`; linking before setting the owner slips past the
> check and leaves a cycle in the graph. Draw in the owner's frame instead.

**State art swaps the shown cell for one draw.** `hover=` / `pressed=` /
`disabled=`: with a file body the constructor builds `Sheet(body, *files)`
(rest frame 0); with a Sheet body they are frame names / indices or clip names
(`_resolve_state_art`). `_showing_state_art` saves `_frame` / `_play_frames`,
shows the state cell (a clip plays in closed form from the state's entry
time), and restores in `finally`. `sprite.frame =` is not used: it stops the
author's clip and re-sizes the body and collider. A state with art skips that
state's default effect (no stacking).

**Clone** rebuilds through `_clone_recipe` (label string snapshot, font, size,
sounds, feel knobs, state art, layer); handlers are not copied (Graphic
contract); `look_like` also copies the label's look.

Tests: `tests/test_sprite_button.py`.

## Mass sprite hot path

Make on the order of **100–200 Sprite citizens** (a 1980s-style shooter, including a
synchronized volley) cheap enough for 60 FPS on the target machine **without changing
the author model**: one `Sprite` type, `hitbox_shape="auto"` stays the beginner default,
construct-again stays spawn, `@collide("sting", "player")` still auto-opts new members
the same frame they are constructed.

Fleet *authoring* (Director / one `every` looping the group) is orthogonal — see
[Actors Design.md — Fleet helpers](Actors%20Design.md#fleet-helpers-groups). This section is fleet *runtime*. `app_galaga.py` is the taught
beginner fleet sample **and** a framework stress; `_bench_galaga.py` is instrumentation
only (may keep denser per-entity fire for `--fire-storm`). Glow on the fleet and
CheapGlow on shots stay off in the bench so looks do not mask Entity cost. Instrument:
`scripts/bench/historical/galaga.py` (match `app_galaga.py` visuals: no projectile glow, invincible
player).

### Why it exists

150 sprites on an M4 for a simple 2D blit list **should** be well under a millisecond
of GPU. Pre-work, hell (~180 stings) was ~5.5 ms of Python **ceremony per citizen per
frame** — not GPU post, not Bloom, not the reactive graph (`flush` ~0). Narrow SAT was
~0.4 tests/frame. Default `hitbox_shape="auto"` still bakes 8-vert hulls for lasers, flames,
and wasps; the waste was **copying unused hulls, re-enrolling everyone, and running the
effect draw envelope on plain images**.

This machine is ~3–8× faster than the target. Absolute FPS is not the arbiter; ratios
and phase times are. Target hardware puts a synchronized 80-shot volley on the 60 FPS
cliff unless those three taxes drop.

Pre-work hell split (~181 stings, ~268 colliders, this M4):

| Phase | ms / frame | What it actually was |
|---|---|---|
| Process tick | ~1.43 | N `on_update` + `move_by` Attribute takein + 80 `every` handles |
| Collision | ~1.42 | Snapshot 0.69 + enroll/refresh ~0.54 + broad AABB 0.18 + SAT ~0.01 |
| Scene draw | ~1.64 | Per-sprite visual/transient/filter probes + Python blit |
| Post / bg / submit | ~0.27 | Fine |
| Flush | ~0 | A1–A3 already working |
| Sprite construct | ~0.13 each | Container×N + MovementController + registry + hooks. 80-aligned `every()` → ~10 ms hitch |

### Principles

1. **One Sprite.** No `BulletSprite`, no SoA field, no pool, no “shots aren’t Sprites.”
2. **One beginner hitbox.** `hitbox_shape="auto"` stays the default. Walkers should pick `"rect"`. Do not invent per-kind defaults.
3. **Author API and semantics unchanged.** Group-tag `@collide` still auto-enrolls new members the same frame. Auto still means precision-over-recall **on actual contacts**. `on_update` / `every` / `move_by` / `.visual` / transients keep today’s meaning.
4. **Internal optimizations, not a second product.** Flags, dirty membership, lazy work, cheaper unlinked Attribute internals — not dual pose storage.
5. **Framework does not invent the scene.** Galaga is not rewritten to “be faster.” If a synchronized `every(2.4, shoot)` volley of 80 is legal author code, Scena must survive it.
6. **Measure citizens, not filters.** Glow / canvas post are out of scope here (already isolated). Do not regress filter batching or auto-hitbox *contact* quality.

### Decisions


| Decision | Choice | Rationale |
|---|---|---|
| Sprite types | **One** | Two types teach a performance caste; beginners would have to pick |
| Hitbox default | **`auto` for all Sprites** | Precision on contact; do not push `hitbox_shape="rect"` as the “real” default |
| How auto stays cheap | **Lazy world hull** — cheap proxy AABB every frame (closed-form under spin), SAT hull only when AABBs overlap | Broad phase already exists; copying 8 verts × N every frame is the waste (closed-form proxy: collision −31% on a rotating 180-body arena) |
| New `@collide` members | **Enroll at construct / group change**, not a full group walk every `step()` | Same semantics; ~0.5 ms of hell collision was this walk |
| Pose representation | **Keep Attribute / Point**; make **unlinked** Attributes cheaper | Same API; avoid B1 dual storage |
| Draw of plain shots | **Sticky `_plain_blit` flag** | 150 lasers have no visual and no transient; they must not run the effect envelope |
| Draw-list teardown | **Tombstones + compact once per draw / destroy batch** (painter order kept) | `list.remove` × 80 despawns is the hitch; swap-remove would scramble z |
| Spawn model | **Construct-again** (`clone` unchanged) | Pooling fights `is_alive` / `setup` / object-target `@collide` |
| Galaga script | **Do not change** for this work | Stress test stays the probe |
| B1 float-pose + Attribute promotion | **Deferred** | Dual representation is brittle; see **Deferred: B1** |
| Bullet SoA / Entity pool | **Deferred** | Different product; see **Sprite spawn** |

### Incremental `@collide` enroll

A sting constructed this frame with `group="sting"` must be a collider this frame.
That does **not** require listing every sting on every subsequent frame.

`CollisionSystem` keeps, for each string tag (or live `GroupOperator` id) that appears
as a `@collide` side:

```text
_tag_colliders: dict[str, list[Collider]]   # dense
_tag_index: dict[str, dict[id, int]]        # swap-remove
```

**Enroll once:** after construct (`enroll_item_groups` following `setup()`, so hitbox /
frame exist), on `add_to_group` if `_actor_constructed`, on `collidable = True`, and at
decorate-time for members already living in the tagged group. Registry hooks:
`notify_group_add` / `notify_group_remove`. `ensure_collider` on an **existing** collider
does **not** rebake — only epoch / clip-frame change does.

**Forget once:** `remove_from_group` / `destroy` / `collidable = False` / park
(`active = False`). Honour `_collision_opt_out` so a sticky opt-out is not re-enrolled
by a later group walk.

**`step()` does not scan groups.** `_declared_broad_pairs` iterates
`_tag_colliders[a] × _tag_colliders[b]` for each `@collide` / `resolve` declaration.
Colliders with `ANYTHING` in `_pair_targets` cross against the full live collider list.
`_refresh_pair_enrollments` remains an audit / desync recovery, not the hot path. Debug: `_debug_enroll_count` is membership,
not per-step.

Same-frame spawn still works because collision runs **after** `tick_processes()`;
enroll happens during construct, which is before `step()`.

### Lazy hull + in-place AABB

`hitbox_shape="auto"` still picks a precise **local** hull (8-vert poly for Kenney lasers is
fine). Runtime must **not** world-transform that hull for every sprite every frame.

Snapshot is two layers:

1. **Proxy (every enrolled collider, every frame).** Four floats on the collider
   (`_proxy`), mutated in place with `(dx, dy)` from the pose key. `Prim` is
   `@dataclass(slots=True)`; `_translate_prims` mutates. Pose key stays
   `(epoch, cx, cy)`. Translation-only mass N must not increment `_debug_hull_builds`.
2. **World prim (lazy).** Local baked spec stays on the Sprite. World verts / circle
   params are built only when that collider is in an AABB-overlapping pair, then cached
   until epoch or pose changes. Queries use proxy reject then lazy `_world_prims`.

**Wasps that animate:** `_sync_auto_hitbox_frame` rebakes only for `hitbox_source="each"`
(every cell) or `"clip"` (when the playing clip changes). Anything else stays frozen.
Still sprites skip that when `_play_frames` is empty. Bake stays **once per reference
set**, cached in `atlas.auto_collider_for_frame` / `auto_collider_for_frames`. World
mapping uses `_hitbox_pose_wh()` (reference cell), so a clip whose cells differ in
aspect does not resize the collider on `play()`.

Remaining `coll_snap_ms` after this work is pose-key / `get_xy` × N, not 8-vert copies.
`show_colliders` still draws the real prim, not a fat box pretending to be the hitbox.

### Plain blit + draw-list compact

A Graphic with no `.visual`, no fill/line ImageFilter, and no active transient is a
textured quad (Sprite) or ordinary geometry. Sticky `_plain_blit` on `Graphic`:

- **True** after construct when those are empty.
- **False** when `.visual` is set, a transient channel starts (`flash`, `fade_in`, …),
  or `fill_filter` / `line_filter` is set.
- Restored when the visual/filter is cleared and transients finish (`_refresh_plain_blit`).
  `look_like` copying a visual onto a shot must clear the flag.

Draw loop (`ScenaCanvas.draw` / `_draw_layer_batched`): if `_plain_blit`, call
`_blit_plain` and continue. Skip `_must_solo_draw`, filter-batch probes, and the
`obj.draw` envelope.

| Kind | `_blit_plain` |
| --- | --- |
| **Sprite** | `_pull_property_anchors()` then `_blit_image` (cached blit plan, [Blit plan cache](#blit-plan-cache); skip `_current_frame_index` when not playing) |
| **Shape** | `_pull_property_anchors()` then `_geometry_draw` (same paint as full `draw`, no ceremony) |

**PaintState on Sprite (blend + alpha):** `.blend` composites the **image blit**, not only silhouette fill/stroke. Read and write are the string (`sprite.blend = "add"`; `sprite.blend == "add"`); the enum is internal. Non-`NORMAL` uses a cached per-instance blit paint; the sprite stays `_plain_blit` eligible (same as static HueShift). Default `NORMAL` keeps the shared `_BLIT_PAINT` singleton — no per-draw branch on `_blend`.

`.alpha` / `set_alpha` is **Sprite-only** sticky body opacity (0–1, default 1.0), baked into `_blit_paint` at set-time, still plain-blit eligible. `sprite.alpha = 0.5` and `sprite.set_alpha(0.5)` are equivalent (the method returns `self`). Composes multiplicatively with `fade_in` / `fade_out` (`saveLayer` `alpha_mul` sits outside the blit paint). Does **not** fade `_replaces_sprite_body` fills (`Metal`, `Flame`, …) or the Shield / Electric* costume envelope. `Shape.set_alpha` is a different knob (pushes alpha into `.fill` / `.line` materials) and is unchanged. `sprite["alpha"] @= lambda: …` links it (an amount: a formula result clamps to [0, 1]); `_blit_plain` pulls before it reads `_blit_paint`, and the draw-head refresh pulls first anyway. A shape has no opacity field of its own (its alpha lives in its paint): link its `color` / `fill` with an alpha (`base.with_alpha(st.a)`).

Do not clear `_plain_blit` solely because blend ≠ NORMAL or alpha ≠ 1.0. Tests: `tests/test_sprite.py` (`TestSpriteBlitBlendAndAlpha`).

**PropertyAnchor pull (2026-09-10):** linked `angle` / `scale` are property-backed
(`_PropertyAnchor`), not pull-on-read Attributes. Raw `_rotation` / `_scale` stay
stale until something pulls. Full `Graphic.draw` always pulls; `_blit_plain` must
too — otherwise `ship["angle"] @= aim` on a plain Sprite (or Circle) renders
stuck. Unlinked cost is one `__dict__.get` miss. Tests:
`tests/test_sprite.py` (`test_plain_blit_pulls_linked_rotation_and_scale`),
`tests/test_visuals.py` (`TestPlainBlit`).

When `cull_offscreen` is **on**, cull still runs for plain blits (skip envelope
only). When **off** (default), the draw walk never enters `_passes_cull` —
[Canvas Design.md — Offscreen culling](Canvas%20Design.md#offscreen-culling).
No GPU sprite batcher (Skia still one call per image; the win is Python —
`drawAtlas` was measured and not adopted, see [Blit plan cache](#blit-plan-cache)).
Multipass recipes, GlowRim overlays, and wasps with Tail / `fade_in` keep the
envelope. Shape detail: [Shapes Design.md — Plain draw](Shapes%20Design.md#plain-draw-_blit_plain).

### Blit plan cache

A still Sprite on screen used to recompute its blit every frame:
- the center (`get_xy`, 0.46 µs);
- the pixel scale (two reactive reads of `width` / `height` in `_du_per_px`,
  0.46 µs);
- the heading, tilt and seat;
- the source and destination rects.

That is ~2.9 µs of Python per blit, before Skia.

`Sprite._blit_plan` (a slot) keeps the result of `_blit_geometry(idx)`:
`(cx, cy, ops)`, where `ops` are the steps of `_apply_paint_xform`, a packed
atlas's rotated-cell turn, and the src / dst rects. The tuple also holds
`(pose revision, moves, cell, sheet, sheet layout epoch)`.

**Key.** It is the cull cache's (Canvas Design, "Offscreen culling") minus
the look revision:
- the **trusted** pose revision (`collision._pose_rev_of`: a plain Sprite
  kind, no link, anchor or pull owner);
- the cell on show (`idx`);
- the `Sheet` object, and its `_layout_epoch` (`clip(offset=)`, `anchor`).

No plan with a transient (`_tx_state`) or a non-`"angle"` tilt mode (contact
or auto tilt and the seat lean with live contacts).

**The paint is not in the key.** `_blit_paint` (alpha, blend, hue, gray) is
passed in on every call and never cached, so a fading or recoloring sprite
keeps its plan. Only geometry is cached.

**Hit.** The cell index (as before), four compares, then `_draw_blit`:
`save`, `translate`, `rotate`, `scale`, `drawImageRect`, `restore`.
Measured: 0.99 µs instead of 2.93 µs per still blit.

**Moves.** A revision that advanced exactly as much as the pose cell's
`moves` changed only by moves of the marked center (the cull's shift). The
plan is kept, at the center read from the Point's bare floats. A shot or a
walker that only translates then costs ~1.6 µs less per frame (move + blit
4.75 → 2.9 µs). The first draw marks the center through `canvas._cull_mover`,
so a body that moves from birth is counted. A seated body (contact plane)
cannot be marked and keeps its plan per revision only.

**Store, and the cost for a body that changes every frame.** The pose cell
has a sixth slot, `draw seen`: `revision - moves` at the last blit. A plan is
stored only when `draw seen` held since the last draw, that is, when nothing
but moves happened. A body that turns or resizes every frame pays that
compare and one list store, then draws by the inline path, the code from
before the cache.

Two earlier versions were measured and rejected:
- **Concat a stored `skia.Matrix`**: +0.4 µs per blit for a turning body.
  Building a Matrix costs ~0.17 µs, plus ~0.1 µs per pre-op.
- **A store bookkeeping call per draw**: +7 % draw for 2000 turning sprites.

**One sequence of calls.** The inline path and `_draw_blit` issue the same
Skia calls, so a cached blit is bit-identical to a fresh one.
`tests/test_blit_plan.py` compares them pixel for pixel after random pose,
paint, clip, link and time operations.

`_BLIT_PLAN = False` neither reads nor stores (oracle, A/B). Verify mode
(`SCENA_VERIFY_POSE_REV=1`, on in every test tier) recomputes the geometry on
every hit and raises on a difference (`_verify_blit_plan`).

**Adding a draw input.** A new field that `_blit_image` reads must be a
bumping pose write (it moves the revision: `bump_pose_rev` or
`_bump_collision_epoch`), or part of the key. A write that does neither draws
the sprite where it was (R5 / GR7 class). The canaries in
`tests/test_blit_plan.py` drop the cell, the layout epoch, the moves check
and the pose bump of `offset` / `art_angle`. Each must fail.

Measured, `scene_draw` (in-process A/B, M4):

| Scene | Effect |
|---|---|
| 2000 still sprites | 9.7 → 4.0 ms |
| corrida | −34 to −37 % (work −7 to −10 %) |
| ninja_nivel | −26 % |
| horda | −6 to −8 % |
| mundo | −7 % |

Bodies that change every frame, against the code before (separate
processes, alternating):

| Scene | Effect |
|---|---|
| 2000 turning and moving sprites | 9.09 → 9.21 ms (noise) |
| naves | 0.221 → 0.195 ms |

**`drawAtlas`: evaluated 2026-10-13, not adopted.** One `drawAtlas` per run
of plain sprites sharing an image costs 0.05 µs per item in Skia, against
~1 µs for `drawImageRect`. But the ~3 µs of Python per sprite stays.
- Neighbours with different images make one-item calls: 4 alternating images
  drew 29 % slower, and corrida and ninja_nivel 8–13 % slower.
- `drawAtlas` also drops quad-edge AA: a rotated opaque edge aliases.

The plan cache removed the Python instead, with no change to a pixel.
Revisit only for long same-image swarms, together with shared texture pages.

**Teardown:** `layer._objects.remove` is O(n). Painter order within a layer is a contract
(append = on top), so not unordered swap-remove. Store `_draw_index` on the object;
`_tombstone_object` leaves a hole; `_compact()` restores order **in place**
(`_objects[:] = live`) so callers holding `layer._objects` stay current. Compact at
`draw()`, `destroy_all`, `clear_draw_list`, `objects_on_layer`, and before
`LayerStack.delete` emptiness checks. `layer.interactive` is a second, small list —
keep `list.remove` there.

### Cheaper unlinked Attributes (not B1)

Keep one Sprite and the full Attribute API (`center.x`, `width`, `@=`, formulas,
`when`). Make the **unlinked** case — Galaga shots — skip machinery A2 already skips
at write time.

- **Lazy `MovementController`.** Not constructed in `Attribute.__init__`. Allocate on
  first `cycle` / `span` / `set_constraints`. `_takein` skips tracking when
  `_movement is None`.
- **`_takein_xy_float` / `_translate_point_float` (A1/A4).** Pose `_move_by` /
  `_move_to` write floats only when `_pose_fast_ok` — no
  `isinstance(..., Attribute)` unpack, no `update()` / `mark_dirty` (A2).
  When `_needs_pull_invalidate` is set (outbound `@=` / live Derivate), fall
  back to batched `center.takein` so sinks stay fresh. Public `takein` still
  unwraps Attributes.
- **Entity duck flag.** `Entity._scena_is_entity = True`; process `_is_entity` is
  `getattr`, not a per-call `from .entity import Entity`.
- **Do not skip `register_container`.** Owner/part edges go through the graph; lazy
  register is B1-adjacent. Construct microbench stayed ~0.18 ms/Sprite after this work
  — graph `add_node` still dominates birth. Revisit only with new numbers.
- **No second Attribute class / no `__slots__` on Attribute** (Container MI). Sprite /
  Shape already slot privates; `Prim` is slotted.

`sprite.center` is still a `Point`; `type(sprite.center.x)` does not change after first
`@=`. **Linked / pull-consumer writes must take the slow `takein` path** once
`_needs_pull_invalidate` is set — same contract as Circle/Rect (A4). Never call
`_takein_xy_float` unconditionally from Sprite pose methods.

### Construction cost

One `Sprite("tile.png", size=64, group="chao")` costs about 240 µs on the M4
(2026-10-12; ~1 ms on the target machine). An Endless slot of ~30 pieces is
then a visible hitch ([games.md](../scripts/bench/games.md), D6). The cost is
spread out, with no single hot spot:
- about 270 private attribute writes, each through the Python-level `__setattr__`;
- the lazily built children (the center `Point` and the other containers);
- two Style objects and the role-marker style;
- the first collider bake and proxy.

Done: private fields that may not be set yet are probed with
`state.probe_private`, not `getattr(obj, name, default)`. A `getattr` miss fell
into `Entity.__getattr__`, which builds an error message for `getattr` to
swallow: 18 per Sprite, about 7 % of construction. Test:
`tests/test_probe_private.py` (same answer as `getattr` for live, destroyed
and plain objects).

**C4a (2026-10-13).** Measured inside a 228 µs `Sprite(…, group=…)`:
- the center `Point`: 60 µs (its marker style alone 22 µs);
- the group enroll: 49 µs (the hitbox bake 17 µs);
- the image path: 19 µs;
- the rest is the Sprite body, two Styles and ~440 `__setattr__`.

Two cuts that change no answer:
- **Image path.** `_image_candidates` keeps its list of places per (name,
  script folder, working directory's device, inode and change time).
  `os.getcwd()` cost ~6 µs on macOS; `os.stat(".")` costs ~0.7 µs. The change
  time is in the key because a deleted folder's inode can come back as a new
  folder's. Only the list is kept: `_resolve_image_path` still asks
  `isfile` of each place in order, so a file that appears higher up or goes
  away is seen as before. Tests: `tests/test_image_path.py`
  (`TestCandidatesMemo`; a name-only key fails two of them).
- **Point marker.** `Point._apply_role_marker_style` assigns a faded marker
  Color built once per (color, alpha) (`shapes._marker_fill`), not
  `Color(color)` then `set_alpha`. A Color is a value (immutable, shared
  like the default paint), and a paint write gives the one Point a new
  material. Tests: `tests/test_marker_fill.py` (role colors as before, a
  write on one Point leaves the others).

Result (M4, HEAD before vs after, in the same session):

| | Before | After |
|---|---:|---:|
| `Rect` | 138–145 µs | 122–129 µs (−11 %) |
| `Sprite` | 181–186 µs | 154–158 µs (−15 %) |
| `Sprite(…, group=)` | 241–250 µs | 214 µs (−12 %) |
| a `Sprite` subclass with a group | 185–194 µs | 157–158 µs (−17 %) |

Considered and left out:
- **Interning the hitbox bake.** Its ~8 µs is spread over shaping, the
  base, the radius and ~37 private writes, with no single hot spot, and a
  shared bake would key on many inputs (the GR7 class).
- **Baking the collider on the first step.** A slot built this frame is
  stepped this frame, so the cost only moves inside the frame.
- **Lazy Styles and fewer private writes.** These touch every paint reader
  (the R5 risk). Measure a profile first, if construction matters again.

Corrida's slot build is still a hitch on the target machine (~4× the M4).
Ending it would need building one slot over several frames (a generator
builder for `Endless`), which is an author-surface change. It is not
planned: corrida is a stress test, and the cost is acceptable.

### Dense tick, flood heuristic, collider swap-remove

**Dense `on_update`.** `_update_dense` is `(item, fn, form)` entries, rebuilt when membership
changes. `form` is the payload `_invoke_update` would pass (`()`, `(dt)` for a bound
method, `(owner)`, `(owner, dt)`), decided once by `_update_call_form` instead of
reading the arity every frame (`tests/test_update_call_form.py`: same call as
`_invoke_update` for every callable shape). A hook replaced mid-frame becomes
`(item, _no_update, _CALL_NONE)`. Tick skips `_is_entity` import, redundant `getattr("_on_update")`, and
`time_scale` work when `_time_scale == 1.0` (almost everyone). Parked Entities stay out
of the list. Do **not** merge 80 `every(2.4, shoot)` into one timer (see [Actors Design.md — Group fences](Actors%20Design.md#group-fences)).

**`every()` flood.** `EVERY_FLOOD_PER_SEC = 40` is **per (owner, call site)** and
**unnamed only**. Named per-entity replace slots (`every(..., name="fire")`) are not
a flood — eighty wasps each arming `"fire"` is a supported pattern. Unnamed 41/s from
the same owner and line still warns.

**Collider teardown.** `CollisionSystem.unregister` is swap-remove via `_collider_index`
(order does not matter). Pair identity stays the collider object. On `Entity.destroy()`,
`forget_destroyed_item` swap-removes every `_pair_handlers` entry whose left or right
side *is* that identity (object-literal `@collide` / `@collide_with`), then unregisters
the collider. Tag × tag handlers stay.

### Results (this M4; target ~3–8× slower)

`scripts/bench/historical/galaga.py --suite --fire-storm`, 2026-08: full "hell" scene
work 3.57 → 2.82 ms (−21%; collision 0.91 → 0.52, draw 0.92 → 0.63); ~200 live shots
5.43 → 3.90 ms. What is left is author `on_update` + blit + a thin AABB pass; spawn
hitches are graph-bound. If a later profile is GPU- or author-callback-bound, stop —
do not reach for B1 without that evidence.


### Sprite fences

One Sprite type; `hitbox_shape="auto"` stays the beginner default. Do not add a
`BulletSprite`, SoA field, or Entity pool to win a bench. Do not require
`hitbox_shape="rect"` on projectiles. Do not add a second set of hitbox kwargs on
Sprite (`hurtbox=`, `hurtbox_from=`, …) — extra colliders are
[hitbox parts](#hitbox-parts) with the same four knobs. The main hitbox has
one spelling per place: `Sprite(hitbox_X=)` at construction, `sprite.hitbox.X`
after; do not bring back flat `sprite.hitbox_scale` / `hitbox_from` properties,
a `hitbox_box` read, or `hb.width` / `hb.height` (one spelling: `hb.box.width`).
Do not let `sprite.hitbox` name a collision side (`@collide(hero.hitbox, …)`):
the actor is the side. The main hitbox claims no groups and takes no px shape. Do not let a part
resolve (revisit only if a real script needs a part to push, not just detect).
Do not bring back `sprite.silhouette` (second spelling of `Track(sprite)`).
Do not rewrite Galaga as a runtime optimization.
Do not merge N `every()` into one timer ([Actors — Group fences](Actors%20Design.md#group-fences)).
B1 dual pose stays **Deferred** until a target-machine scene is update-bound
([Reactive Design.md](Reactive%20Design.md#deferred-float-pose--promotion-b1)).

Why these hold: a second Sprite type or "non-Container bullets" would win the
Galaga bench and split the language. `hitbox_shape="rect"` on projectiles helps the
snapshot a little, fixes neither enroll nor blit, and teaches a second default —
the lazy hull makes `"auto"` cheap. An Entity pool / SoA field needs explicit
acquire / release, which fights the beginner model. Merging timers silently changes
when callbacks fire (a denser scheduler tick is allowed). B1 has the right spirit
(the author never picks a type) and the wrong mechanism now: `type(sprite.center.x)`
changes after the first link, `move_by` / draw / collision / clone get two
implementations, and an accidental promotion (`print(sprite.center)`) keeps the slow
path for life.
Index: [Fences.md](Fences.md).

### Invariants

- Collision **after** `tick_processes()`. Same-frame spawn enrolls **during construct**.
- Declared pairs only: incremental index is per tag; `ANYTHING` uses the full
  collider list.
- Park (`active=False`): no draw, no collision, process time frozen. Must drop from
  `_tag_colliders` and from `_update_dense`.
- `collidable=False` sticky opt-out: incremental enroll must honour `_collision_opt_out`.
- Auto bake **once per image frame**. Runtime must not refit masks.
- A2: `_takein_xy_float` must not `mark_dirty` / `update()` when unlinked.
- Sticky `_needs_pull_invalidate`: first `@=` still flags the ownership root.
  Sprite `_move_by` / `_move_to` must check `_pose_fast_ok` before bare-float
  writes (outbound `sink @= sprite.center` must track motion).
- **Do not intern Entity identity.** Sheet intern stays; each shot remains a new registry
  id (`is_alive`, `@collide` object targets).
- **Clip clock (graphics review, batch 8b).** The playhead counts whole frames with the
  PM8 tolerance (`process.whole_steps`, inlined in `_current_frame_index`; SpriteButton
  state art uses it too): `int(elapsed * fps)` showed each frame one game frame late.
  A one-shot's end is settled by any reader, and `play()` settles first, so a hidden or
  culled sprite can replay it; a `next=` clip starts at the boundary (the overshoot is
  carried), not at the first read; a read on a destroyed sprite changes nothing. A new
  clip while `time_scale == 0` shows its own start. `time_scale` shares Entity's check
  (`entity._time_scale_value`: alive, a number, finite, ≥ 0).
- **A clip that ends ends in the simulation (review 2026-10-09 S7-7).** A clip with a
  finite `loops=` is scheduled by the world time it ends (`_CLIP_DUE`, a heap of
  `(due, seq, weakref)`; `_schedule_clip_end` runs on `_adopt_clip` and on a
  `time_scale` write, a frozen clip has no end until it thaws). `settle_clip_ends()`
  (frame body, right after the process tick) reads the due ones, so the end and the
  `next=` switch, with its size write, happen before collision and `flush`, never
  first inside the draw. A heap, not a walk: walking 300 playing sprites cost 5 % of
  the frame. A stale entry (`sprite._play_due` moved on) is skipped, and the heap is
  compacted past twice its live size. Other readers still settle it earlier (the result is the same). The
  `next=` switch has no call site: when `width` / `height` is linked, the link keeps
  the size and the switch does not raise (`play()` and `frame =` still refuse a linked
  size at the call, PB1).
- **`min_hold=` is due by `reached`**, like every other deadline: a bare `<` held 0.25 s for 16 frames at 1/60 for most start frames (review 2026-10-09 S7-2).
- **Size writers check both slots first.** `size =` checks `width` and `height` before
  writing either, and `frame =` gates the cell's size before it stops the clip (review
  2026-10-09 S7-5 / S7-6: each refused after half its work).
- **One picture on both draw paths.** With no look (`.visual`), the full path draws what the
  plain blit draws: the bitmap (a style fill / stroke from `color =` is a look's costume;
  PB7). Every body route applies gray, blend and alpha (`_apply_blit_paint_extras`, the
  Recolor route included; PB8). Guard: `tests/test_draw_doors.py`.
- **Size after new art.** `size =` after a collapse takes the cell's own aspect (PB14);
  `svg =` keeps the side the author sized and takes the new art's aspect (PB9).

### Pitfalls

- **`ensure_collider` on an existing collider** must not re-call `_ensure_auto_baked`.
  Pair with clip-frame epoch bump or animated wasp hulls desync.
- **Ordered weak groups vs dense collider lists:** `destroy` already `remove_from_group`;
  that is the enroll-forget hook. Author/query walks of a live group must copy
  (`GroupOperator._iter_members`); never iterate the registry membership store directly.
  `count` / `empty` stay O(1) on a named tag (join order, not spatial).
- **Plain blit vs `cull_offscreen`:** when cull is **on**, still run `_passes_cull`
  (skip only the envelope). When cull is **off**, the draw walk skips the call
  entirely — do not reintroduce a per-object `_passes_cull` on the default path.
- **Plain blit vs linked `angle` / `scale`:** `_blit_plain` must
  `_pull_property_anchors()` before reading raw pose. Do not “optimize” that away.
- **Tombstone compact vs interactive list:** keep in sync; compact in place so
  `layer._objects` aliases stay valid (`move_to_front` tests hold that reference).
- **Layer delete** must compact before “still has objects” — tombstone holes are not
  live, but a list of `None` is truthy.

### Tests and benches

| Area | Where |
|---|---|
| Group live walks copy | `tests/test_registry_layers.py` — destroy/spawn in `for`, destroy/untag/spawn in `any` / `all` / `count_where` / `filter` / `nearest` |
| Lazy hull | `tests/test_collision.py` `TestLazyHull` — poly overlap, moving overlap, no-overlap skips hull |
| Park / opt-out | existing collidable tests + incremental index |
| Auto contact quality | `tests/test_atlas.py`, `tests/test_sprite.py` |
| Pose A1–A3 | `tests/test_pose_fast_path.py`, `tests/test_change_gated_update.py` |
| Transients vs plain blit | `tests/test_visuals.py` `TestPlainBlit` (Sprite + Shape; linked rotation), `tests/test_cull.py` `TestPlainBlitCull` |
| Spawn intern/clone | `tests/test_sprite.py` |
| Bake shared across `Sheet`s | `tests/test_atlas.py` `test_sheets_sharing_one_image_share_bakes` (token refcount, drop on last holder); `tests/test_sprite.py` `test_hitbox_auto_fresh_sheet_per_spawn_reuses_bake` |
| Process flood | `tests/test_process.py` `TestEveryFlood` — 80× `every(..., name="fire")` silent; unnamed 41/s still warns |

```text
python scripts/bench/historical/galaga.py --suite
python scripts/bench/historical/galaga.py --suite --fire-storm
python scripts/bench/perf_sprite_spawn.py
python scripts/bench/perf_sprite_hitbox.py
python scripts/bench/perf_assets.py --pulse   # first-use / warm spawn per asset (assets.md)
```

Report `tick_ms`, `coll_ms`, `coll_snap_ms`, `coll_broad_ms`, `draw_ms`,
`spawn_ms_frame`, `avg_stings`, `avg_narrow`. Keep `_bench_galaga.py` visually aligned
with `app_galaga.py` (no projectile glow, invincible player). Fleet *authoring* may
differ: the bench may keep denser per-entity fire for `--fire-storm`.

### Out of scope

Fleet *authoring* → [Actors Design.md — Fleet helpers](Actors%20Design.md#fleet-helpers-groups).
Canvas post / Bloom / CheapGlow / filter batching → [Effect System Design.md](Effect%20System%20Design.md).
B1 / pools / SoA → **Sprite fences** / [Reactive Design.md](Reactive%20Design.md#deferred-float-pose--promotion-b1).
Do not skip `register_container` without a construct profile that names `add_node`.
