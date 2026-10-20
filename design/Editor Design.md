# Editor Design

Level files and the level editor. **The editor places geometry; code decides
what it becomes.** Two parts:

- **`Level`** (framework, `scena/level.py` + `scena/level_format.py`): reads a
  level file. Creates nothing.
- **The level editor** (companion app, `scena_editor/`, `python -m scena_editor`):
  draws rects, ellipses, circles, lines, polygons, triangles, regular polygons,
  tracks, concaves, points and images (a whole picture, or a frame of a
  spritesheet) on a level area, names and groups them, saves the file. Not part of the
  framework (see [Boundary](#boundary)).

Hub: [Scena Design.md](Scena%20Design.md). Regions: [Box Design.md](Box%20Design.md).
Author catalog: [Guia da API](../docs/pt/guide/index.html#colocar-fase).

Today’s baseline — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| What a level file holds | [File format](#file-format) |
| Spritesheets in a level (`sheets`, frame images) | [Sheets](#sheets) |
| The frame picker, Choose frame… | [Editor](#editor-companion-app) ("Frames of a sheet") |
| `Level` / `LevelItem` / `make()` / `.box` | [Reading a level](#reading-a-level) |
| Copy as code | [One constructor table](#one-constructor-table) |
| Install, start, launcher icon, error log | [Starting the editor](#starting-the-editor) |
| What the editor does (v1) | [Editor](#editor-companion-app) |
| Why the editor is not in `scena/` | [Boundary](#boundary) |
| Settled nos | [Fences](#fences) |
| Why no per-item values (hp, speed) in the file | [Why no values](#why-no-values-in-the-file) |
| Locating code | [Router](#router) |

## Use

1. Pick one jump-box row.
2. Read that section only. Treat fences there as current constraints.
3. Open **Start** in the router if the section is not enough.
4. Stop.

## Router

| Need | Start | Also | Design (if needed) |
| --- | --- | --- | --- |
| Parse / check / write a level file | `level_format.py` (`parse`, `serialize`) | `validate.py` (`did_you_mean`) | [File format](#file-format) |
| `Level`, `LevelItem`, `make()` | `level.py` | `level_format.py` (`constructor_for`), `sprite.py` (`_resolve_image_path`) | [Reading a level](#reading-a-level) |
| Copy as code | `level_format.py` (`code_for`) | `level.py` (`make`) | [One constructor table](#one-constructor-table) |
| Editor gestures / commands | `scena_editor/tools.py` (`Editor`) | `geometry.py`, `doc.py`, `undo.py` | [Editor](#editor-companion-app) |
| Editor window: drawing the document | `scena_editor/view.py` | `tools.py`, `sheets.py` | [Editor](#editor-companion-app) |
| Frame picker, a level's sheets in the editor | `scena_editor/sheet_pick.py` | `sheets.py`, `doc.py` (`ensure_sheet`), `app.py` (`choose_frame`) | [Editor](#editor-companion-app) |
| Editor panels, status, prompts | `scena_editor/panel.py`, `app.py` | `i18n.py` | [Editor](#editor-companion-app) |
| File dialogs | `scena_editor/dialogs.py` | `_tkdialog.py` | [Editor](#editor-companion-app) |
| Scena privates the editor uses | `scena_editor/_engine.py` | `scena/orchestration.py` (`_close_guard`) | [Boundary](#boundary) |
| `scena-editor` command, `--shortcut`, error log | `scena_editor/__main__.py` | `shortcut.py`, `log.py`, `pyproject.toml` | [Starting the editor](#starting-the-editor) |

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `Level("fase1.json")` | a reader: items by name / group | a scene builder; nothing appears |
| `item.make()` | the shape **as drawn**, in the item's groups | the region (`item.box`) |
| `item.box` | a fresh oriented `Box` (area kinds) | a link to the file; changing it changes nothing |
| `level.group("g")` | items in the file with group `g` | `group["g"]` (live registry); it raises on an unknown group |
| item groups | editor labels, applied by `make()` | live groups until something is made |
| guide image | editor-only tracing reference | part of the level (`Level` skips it) |
| `locked` | editor-only: selectable, not movable | a game flag (`Level` ignores it) |
| `level.sheet("terreno")` | the one `Sheet` every frame of that sheet uses (built on first use) | a fresh catalog per call; the author's own `Sheet(...)` |
| `item.image` of a frame | refused: the sheet's file would show every frame | the frame's picture (`item.make()`, or `item.sheet` + `item.frame`) |

# File format

`*.json`, one level per file. Scena design units, **y up**, centers, `angle`
in degrees counter-clockwise — the numbers an author writes in code; no
conversion anywhere.

```json
{"format": "scena-level", "version": 2, "size": [3600, 1500], "sheets": [
  {"name": "terreno", "file": "tiles/terrain.png", "cell": [16, 16]},
  {"name": "bola", "file": "k-rolling-ball/rollingBall_sheet.png", "atlas": "k-rolling-ball/rollingBall_sheet.xml"}
], "items": [
  {"kind": "rect",    "groups": ["plataforma"], "center": [1000, 150], "width": 220, "height": 24, "angle": 20},
  {"kind": "ellipse", "name": "lago", "center": [500, 60], "width": 300, "height": 80},
  {"kind": "concave", "name": "rampa", "center": [1600, 100], "width": 200, "height": 200, "scoop": "top_right", "rim": [20, 0]},
  {"kind": "circle",  "center": [10, 10], "radius": 16},
  {"kind": "line",    "p1": [0, 0], "p2": [10, 10]},
  {"kind": "polygon", "name": "morro", "points": [[0, 0], [100, 0], [50, 80]]},
  {"kind": "regular_polygon", "name": "favo", "center": [700, 400], "radius": 30, "n": 6, "angle": 90},
  {"kind": "triangle", "name": "nave", "center": [800, 300], "radius": 20, "angle": 90, "base_ratio": 0.6},
  {"kind": "track",   "name": "rota_drone", "points": [[900, 600], [1300, 600]], "smooth": 0.5},
  {"kind": "point",   "groups": ["estrela"], "center": [330, 320]},
  {"kind": "image",   "name": "fundo", "file": "arte/fase1.png", "center": [1800, 750],
                      "width": 3600, "height": 1500, "locked": true},
  {"kind": "image",   "groups": ["chao"], "sheet": "terreno", "frame": 37, "center": [8, 8],
                      "width": 16, "height": 16},
  {"kind": "image",   "name": "saida", "sheet": "bola", "frame": "block_large.png",
                      "center": [900, 120], "width": 64, "height": 64}
]}
```

- `format` / `version` are plumbing: a JSON that is not a level fails clearly
  ("not a Scena level file"); a newer version is refused ("Update Scena").
  `Level` exposes neither. **Version 2** (0.9.0) added `sheets`; the editor
  always writes the current version (author's decision 2026-10-20: no editor
  users yet, so a 0.9 file need not open in 0.8.x), and every older version
  is still read (a version-1 file is a version-2 file without `sheets`; the
  shipped `examples/media/levels/*.json` are version 1).
- `items` order is the draw order.
- Common keys: `name` (optional, unique in the file), `groups` (optional list,
  no repeats), `locked` (editor-only).
- Per kind (required, then optional with default): rect / ellipse
  `center, width, height` · `angle=0`; concave `center, width, height` ·
  `angle=0`, `scoop="top_left"` (a named point of the box, as
  `Concave(scoop=)`; a near miss names the fix), `rim=[0, 0]` (a pair ≥ 0;
  Copy as code writes one number when both agree); circle `center, radius`; line
  `p1, p2`; polygon `points` (≥ 3); regular_polygon `center, radius, n`
  (sides, a whole number ≥ 3) · `angle=0` (toward vertex 0, as
  `RegularPolygon`); triangle `center, radius` · `angle=0` (toward the apex),
  `base_ratio=1` (above 0, below 2, as `Triangle`); track `points` (≥ 2) · `closed=false`
  · `smooth=0` (0 to 1, `Track.smooth`: 0 straight segments, 1 a curve);
  point `center`; image `center, width, height` and **either** `file` (a
  whole picture) **or** `sheet` + `frame` (one frame of a sheet, below) ·
  `angle=0`, `guide=false`. Sizes are magnitudes (≥ 0).
- Image `file` (and a sheet's `file` / `atlas`) is a POSIX path **relative
  to the level file**.
- `angle` was `rotation` until 2026-10-01 (renamed with `Graphic.angle`); a
  file with `"rotation"` is refused with the new name, never rewritten.
- The kind `track` was `path` until 2026-10-02 — renamed so every kind is
  its class's name (Copy as code already printed `Track(…)`; the editor
  said "Path"). `"kind": "path"` is refused naming `track`; no alias.
- Reading refuses, with `LevelFormatError` (a `ValueError`) naming the file
  and the item: unknown kinds and keys (did-you-mean), missing fields, wrong
  types, negative sizes, too few points, duplicate names or groups. Never a
  silent skip, never a half-read file.
- Writing (`serialize`) leaves out fields at their default and writes
  integral floats as ints; `parse(serialize(doc))` is the identity and
  `serialize` is canonical (`TestFormatProperties`, `TestSheetFormatProperties`).

## Sheets

A packed picture — a tileset, a Kenney or TexturePacker atlas — is one image
cut into frames. The engine reads it with `Sheet`; a level names it once in
`sheets` and each image item says which frame it shows. *Which picture* is
appearance, already in the file as `file`: a frame only narrows it. **Time
stays in code** (clips, fps: `level.sheet(name).clip(...)`), as values do
([Why no values](#why-no-values-in-the-file)).

- `sheets` is a **list** (JSON objects drop a repeated key silently; a list
  lets the reader refuse a repeated name, as for items). An entry: `name` (a
  Python identifier, not a keyword — it is also the variable in Copy as code
  and the key of `level.sheet()`; unique), `file`, and **exactly one layout**,
  `Sheet`'s single-image ones: `cols` (whole ≥ 1, with optional `rows`,
  default 1; `rows` alone is refused, as `Sheet(rows=)`), `cell` (`[w, h]`,
  whole pixels ≥ 1) or `atlas` (Kenney / TexturePacker XML, TexturePacker JSON
  hash or array — what `scena.atlas.load_atlas` reads). Count and cell size
  are both kept: they are `Sheet`'s two spellings of one grid, and a pack's
  documentation gives one or the other. Not carried: lists of files and
  patterns (loose files are one image item each), `strip` (several backing
  images: two entries) and `Sheet("x.xml")` alone (the entry names both
  `file` and `atlas`).
- **Refused with the reason:** `fps`, `yoyo`, `clip(s)` (time: code),
  `anchor` (an item's `center` is its box's center; the level's sheets use the
  default anchor), `pixel_size` (every item carries `width` / `height`).
- An image item with `sheet` + `frame`: `frame` is what `Sprite(frame=)`
  takes — a whole number ≥ 0 or a non-empty string. The editor writes a
  **name on an atlas** (stable when the atlas is repacked; indices are not)
  and an **index on a grid** (row-major from the top-left, as the engine).
  `file` with `sheet` / `frame`, neither, or one of the pair is refused with
  the fix; `sheet` must name an entry (did-you-mean).
- **Frames are checked when the sheet is first built**, not at `Level()`:
  the frame needs the atlas or the image, and `Level` reads only (a script
  that uses a level for geometry does not decode its art). Building it checks
  the frame of every item cut from it (`sheet.frame_index`) and raises
  `LevelFormatError` naming the file and the item. This matters: `Sprite(sheet,
  frame="typo")` only warns and shows a placeholder; a level must not. A
  missing image or atlas file warns and shows the checker, as for a plain
  image.
- `center` means what it means for a plain image: the Sprite's `center`, and
  `width` / `height` size the frame's **untrimmed** box (the engine sizes a
  trimmed atlas frame against its source size), so trimmed frames need
  nothing special. **Known limit:** a frame with an *authored* pivot
  (TexturePacker `pivotX/Y` ≠ 0.5; the packs in `examples/media` have none)
  draws off its box, because a Sprite's center is its pivot; the game and the
  editor agree (both build the same Sprite), only the editor's selection box
  does not wrap the art.

# Reading a level

```python
fase = Level("fase1.json")               # reads only; creates nothing
for p in fase.group("plataforma"):
    bloco = p.make()                      # Rect as drawn, in group "plataforma"
    bloco.mass = STATIC
for e in fase.group("estrela"):
    criar_estrela(e.center)               # a point is a location
fase["fundo"].make(layer="fundo")         # image → Sprite at that size and angle
area = fase["arena"].box                  # the region: Sprite(box=), confine, grid…
drone.move_along(fase["rota_drone"].points, time=6)
```

- **`Level(path)`** — the path resolves like Sprite images (absolute, next to
  the script, its `media/`, the cwd). A missing file raises `ValueError` at
  the call (a level is data the code depends on; unlike a missing image there
  is no placeholder that keeps the game honest). Guide images are dropped.
- **`level["name"]`** — one item; unknown names raise with did-you-mean, and
  with `level.group(...)` when the name is a group.
- **`level.group("g")`** — items with `g` among their groups, file order.
  **Raises** when no item has `g` (a typo must not become an empty loop).
- **`level.sheet("name")`** — the `Sheet` of that entry: one per entry per
  `Level`, built on first use (`level.sheet`, `item.sheet`, `item.make()`),
  default anchor; every frame of that sheet uses it, so a clip registered
  on it plays on what `make()` builds. Unknown name: did-you-mean.
  `level.sheets` — the names, file order. Two `Level`s of one file get two
  catalogs; the decode is shared (`_IMAGE_CACHE`).
- `level.names`, `level.groups` (first-use order), `level.size`, `level.box`
  (fresh, `(0, 0)` → `size`), `level.path`, iteration, `len`, `in`.
- **`LevelItem`** — `kind`, `name`, `groups`, `center` (a line's midpoint, a
  polygon's / track's bounding-box middle — of its points, not of a smooth
  curve), and per kind `width` / `height` /
  `angle`, `scoop` / `rim` (a `Vec2`), `radius`, `n`, `base_ratio`, `p1` / `p2`
  (a line's `length` and `angle` too: computed from its ends as `make()`
  reads them; `angle` runs from -180 up to 180), `points` (new list of `Vec2`),
  `closed`, `smooth`,
  `image` (absolute; a whole picture), `sheet` / `frame` (a frame of a sheet).
  A field of another kind raises `AttributeError` listing what the item has;
  so do `image` on a frame (`Sprite(item.image, …)` would show the whole
  sheet: a silent wrong picture) and `sheet` / `frame` on a whole picture.
  Every read is a copy.
- **`item.box`** — fresh oriented `Box(center, width, height, angle)` for
  rect / ellipse / concave / image; a circle's square. Lines, polygons, regular
  polygons, triangles, tracks and points raise (only those four kinds are regions).
- **`item.make(**kwargs)`** — builds the shape as drawn: rect → `Rect`,
  ellipse → `Ellipse`, concave → `Concave(center, width, height, angle, scoop, rim)`,
  circle → `Circle`, line → `Line`, polygon → `Polygon`,
  regular_polygon → `RegularPolygon(n, center, radius, angle)`,
  triangle → `Triangle(center, radius, angle, base_ratio)`,
  track → `Track(points, smooth, closed)` (`smooth` always written: the
  file's default is 0, `Track`'s own is 1), point → `Point`, image →
  `Sprite(file, center, width, height, angle)` (a frame:
  `Sprite(level.sheet(name), frame=…, center, …)`; `make(frame=)` is a
  geometry clash) — every field is a constructor keyword. The item's groups are applied; `group=` **adds**; other
  keywords pass through (`layer=`, `color=`, `visual=`); a geometry keyword
  raises (`TypeError`, "remove center="). A guide raises.

- **Another model.** `make()` builds the file's model (a rect by its
  center, a line by its ends). For another, the author writes the
  constructor with the item's numbers: `item.box` has every named point
  (`Rect(top_left=b.top_left, width=b.width, height=b.height, angle=b.angle)`,
  `Rect(p1=b.left_center, p2=b.right_center, height=b.height, anchor="cap")`),
  a line has `length` / `angle` (`Line(p1=item.p1, angle=item.angle,
  length=item.length)`). No `make(model=…)` and no shape-as-source
  constructor: [Shapes — A shape is not a source of another model](Shapes%20Design.md#a-shape-is-not-a-source-of-another-model).
  Guard: `test_level.TestLineLengthAngle`.

## One constructor table

`level_format.constructor_for(item)` → `(class name, args, kwargs, settings)`
is the only kind → constructor mapping. `LevelItem.make()` calls the class;
`level_format.code_for(item)` prints it — the editor's **Copy as code**
(`moeda = Circle(center=(1, 2), radius=3)`; named items get a variable; a
rotated item gets `angle=`: `Sprite("a.png", center=…, width=…, height=…,
angle=30)`). `settings` (attributes set after construction) is empty today;
it stays in the table for a class that lacks a keyword. Copied lines name the
image as the file does (relative); `make()` passes the absolute path. A frame
image's source is the `Sheet` in `make()` and a `SheetVar` (printed bare) in
Copy as code; `code_for_items` prints each sheet's line once, first
(`terreno = Sheet("tiles.png", cell=(16, 16))`, from `sheet_call`, the one
entry → `Sheet` table, which `Level.sheet` uses too).
Guard: `tests/test_level_codegen.py` evals the copied code and compares it with
`make()` and with the item, for every kind and for random items.

# Editor (companion app)

**Status:** v1 built (2026-10-01). Checked on a platformer sample game (in development): its level file builds the scene identical to the hand-coded one (48 shapes, same kind / pose / size / groups / layer / mass). Level files are written one item per line (`level_format.dumps`). History: Core built (2026-10-01): `doc.py`
(document, files, `.bak`, image paths rebased on Save As), `undo.py`,
`geometry.py`, `tools.py` (the `Editor` controller), `i18n.py`; tests in
`scena_editor/tests/` (`test_editor_tools` incl. an undo-all / redo-all
property, `test_editor_geometry`, `test_editor_i18n`, `test_boundary`).
Window built (2026-10-01): `view.py` (`LevelView` mirrors the document into
Scena Graphics by item id; `ScenaViewport` is the camera through the public
canvas API; pooled grid lines, coarsened so at most ~140 are on screen),
`panel.py` (toolbar, top bar, properties, status), `app.py` (callbacks,
commands, unsaved-changes prompt), `dialogs.py` + `_tkdialog.py`,
`__main__.py`; tests `test_editor_system` (real frames: view = document
through edit / undo cycles, panel commit target, save → `Level`, close
guard, no zombies) and `test_editor_dialogs`. v1:

- `python -m scena_editor [fase1.json]`, a Scena program (1280×800 design
  units). English UI through `t(key)` (one table per language).
- Tools: Select (V), Pan (H), Rect (R), Ellipse (E), Circle (C), Line (L),
  Polygon (G), Triangle (D), Regular polygon (N), Track (A), Concave (U), Point (P),
  Image (I). Point has P because it is used most; T is left free for a Text
  tool, so Triangle has D (Δ). Panel: name, groups
  (comma-separated), numeric geometry, locked, guide; Copy as code,
  Duplicate, Delete, Front / Back; several selected: shared groups, X / Y,
  Row / Column. Status bar: cursor in Scena units, zoom,
  file and unsaved mark.
- **Layout:** the left toolbar holds only what you create — Rect, Ellipse,
  Circle, Line, Polygon, Triangle, Regular polygon, Track, Concave, Point, a gap,
  Image (it opens a file dialog): the common shapes first, the three polygon
  tools together, Concave (a special-purpose piece) after Track. Each icon is
  drawn with the shape its tool makes; the Polygon icon is an irregular,
  notched outline, so it does not read as the Regular polygon tool's hexagon
  (`test_toolbar_order_and_icons`).
  The top bar: New / Open / Save / Save as │ Undo / Redo │ Snap, grid step │
  Select, Pan, Fit, 100% │ Select group [▾]. Undo / Redo are text Buttons, faded (`enabled`)
  when there is nothing to undo / redo.
- **Tool buttons are icons** (`scena_editor/toolbar.py`): each drawn with the
  Scena shape the tool makes (the Polygon button is a `Polygon`; Select an
  arrow, Pan four-way arrows), the shortcut letter in the bottom-right corner
  (left toolbar), the current tool on the accent color. The letters come
  from `tools.KEY_OF` (one source).
- **Tooltips** (`toolbar.Tooltip`, `attach_tip`) — only where they add
  something: every icon button (its name and key), and every Button with a
  shortcut — New, Open, Save, Save as, Undo, Redo, Fit, 100%, Duplicate,
  Delete ("Save (Cmd+S)", "Ctrl" off macOS) — plus the Snap checkbox ("Hold
  Shift while dragging: no snap"). Copy as code, Front, Back, Change image and
  the grid step get none: the label says it all. **Timing as desktop
  toolkits do it:** a tooltip appears after the pointer rests 0.6 s; once one
  has shown, the next button's is immediate ("warm") until the pointer has
  been off the buttons 0.3 s; a click hides it until the pointer leaves that
  button (`Panel.refresh` calls `tick()` each frame). Widgets draw over the
  `ui` layer, so a tooltip never goes on them: below the top bar, right of
  the left toolbar, left of the right panel as a whole (`edge=`) — the test
  `test_every_tooltip_stays_in_the_window_and_off_the_widgets` checks every
  one. No `?` shortcut sheet: with the shortcuts on the buttons and the per-
  tool status-bar hints, it would repeat what the screen already shows.
- **Keys for Select and Pan stay** (V, H) although Esc already returns to
  Select and Space+drag pans: V is universal muscle memory; H is a mode that
  stays on, Space pans only while held — different jobs, not two spellings.
- **Primary held = temporary Select** (Illustrator's convention): in Pan or
  a drawing tool, a press with Cmd (macOS) / Ctrl held is a Select press —
  click, Shift+click, move, handles, box — and the tool stays. Decided at the
  press (`Editor.select_held`, set by the host from `keyp(PRIMARY)`): a drag
  finishes as it began whatever Primary does meanwhile; a polygon / track in
  progress keeps its points (a Primary+click adds none, a Primary+double-
  click does not close it). While held with no gesture
  (`Editor.select_standby`) the cursor and status-bar hint are Select's and
  the Select button gets an accent outline. Symmetric with Space: in Select,
  Space pans; elsewhere, Primary selects. Not Shift+drag in Pan (Shift
  already means "add" and "no snap"; no common app does it) and not Ctrl on
  macOS (Ctrl+click is a right-click there). Pressing Primary between H and
  the drag must not pan: the Pan check yields to it.
- **Choosing the Select tool** (button or V) clears the selection.
- **Selected points** get a ring (a fixed screen size), not only a color.
- **Images:** "Change image…" picks another file — same center, angle and
  height, width from the new picture's proportions (a frame of a sheet
  becomes a whole picture).
- **Frames of a sheet** (0.9.0). The Image tool's dialog also takes an atlas
  (`.xml` / `.json`): the **frame picker** opens on its frames, and the
  picked one is placed at the view's middle at its untrimmed pixel size. A
  PNG is placed whole, as before (the fast path did not change). **Choose
  frame…** (beside Change image, one image selected) opens the picker on the
  item's file and keeps **center, angle and scale** (design units per
  pixel): a tileset placed whole at 1:1 becomes a 1:1 tile, and frames of
  different sizes keep their relative size (Change image keeps its shipped
  rule, same height). One undo step.
  - **The picker borrows the canvas and the camera** (`sheet_pick.py`): an
    opaque backdrop on its own world layer above the items, the sheet at
    1 px = 1 unit, the overlay layer (handles) hidden. Planned as a modal box
    (proposal 2026-10-19); built this way because Scena does not clip a layer
    to a region, so a zoomed sheet in a box spilled over the panels — the
    panels drawn over the world are the clip — and the canvas gestures come
    free: the wheel zooms, a drag / Space+drag / middle button pans, F fits,
    Primary+0 is 100%. `top` cannot have a layer above it (Scena reserves it),
    so the picker's layers sit above `default` and `top` is hidden while it is
    up. A click without a drag picks; Esc or Cancel closes; the camera comes
    back either way.
  - **The right panel holds the cut**: *Whole image · Columns × rows · Cell
    size · Atlas* (a drop-down), its fields, Change atlas…, a name filter on
    atlases (frames that do not match are dimmed), the frame count, Use whole
    image, Cancel. The status bar names the frame under the pointer
    (`block_large.png · 65 × 128 px`, `37 · 16 × 16 px`) or gives `Sheet`'s
    message for a cut it refuses (`cell` that does not divide, the cell cap):
    the cut is built through `Sheet` (`sheets.sheet_for`), so the editor never
    disagrees with the game. Every other widget is disabled while it is up
    (`_engine.live_widgets`). Opens with: the item's sheet; an atlas with the
    PNG's stem beside it; a cell size in the file name (`Terrain (16x16).png`);
    else the whole image. Columns × rows starts at the strip's square frames
    (`544 × 32` → 17 × 1). Shown, then written explicitly: nothing is inferred
    at read time.
  - **Document:** `LevelDoc.sheets` holds the entries with **absolute** paths
    (written relative, so an undo across a Save As restores paths that still
    point at the art). Only sheets an item uses are saved or kept by undo
    snapshots; an unused one yields its name. `ensure_sheet` reuses an entry
    with the same file and cut, else adds one named after the file
    (`Terrain (16x16).png` → `Terrain_16x16`; `_2` on a clash). Copy carries
    the entries the items use; a paste into another level reuses the same cut
    or renames a clash. Not yet: a stamp tool (pick once, click many), arrow
    keys between frames, a frame for several items at once, renaming a sheet.
- **Select:** click; Shift+click adds / removes; drag a shape moves the
  selection; handles resize (8; images 4 corners, aspect kept) and rotate (1);
  click again cycles overlaps. **Alt / Option+drag** moves copies made where
  the originals are (names get `_2`); the originals stay. Copy and move are
  one undo step; a click copies nothing; locked items are not copied (a
  common convention, no new UI). Alt on Windows and Linux; on many Linux
  desktops (GNOME, KDE, Xfce) the window manager takes Alt+drag to move the
  window and the editor sees a plain move — change the desktop's
  window-move key, or Duplicate (Ctrl+D) and drag. No second copy key.
  **Primary held during a move (Cmd / Ctrl) keeps it straight**: the move
  keeps to the axis the pointer has gone furthest along, and the other axis
  stays exactly where it was, even off the grid — so an Alt+drag copy lines
  up with its original. Read every event: it can start or stop mid-drag; it
  combines with snap (applied first) and Shift. Inkscape's split (Shift: no
  snap; Ctrl: constrain), not Figma's Shift: here Shift already means "no
  snap" and "add". While a move runs, the status bar says what the keys do
  (`hint.move`). Shift+**press** only adds — a selected shape
  is removed on release of a Shift+**click** — so Shift+drag of a selected
  shape still moves it (snap off). On a small shape the handles cover its
  middle: a handle wins only when the pointer is nearer to it than to the
  shape's center. Locked shapes select but show no handles and do not move
  or delete.
- **Group handles** (two or more selected): a frame around the items that
  **move** (the unlocked ones, the same set a drag moves), 4 corner handles
  and a rotate knob. **Corners scale evenly** about the opposite corner: an
  uneven stretch cannot be stored for a circle (it would be an ellipse), a
  regular polygon, a rotated rect / ellipse / image (a parallelogram) or an
  image (aspect kept), so there are no edge handles. The corner you drag
  lands on the grid on the axis that stretches most (`geometry.group_scale`);
  dragging past the anchor never mirrors (`MIN_SCALE`). The knob turns every
  item about the frame's center (centers and points turn, `angle` adds up),
  15° steps, Shift free; the frame turns with them and becomes the new
  upright box on release. Every kind stays its kind (`scale_item`,
  `rotate_item`). No frame when the box is a single point. `Editor.handles()`
  is cached per (doc, version, selection, zoom, turn): the view and the
  cursor ask every frame.
- **Row / Column** (panel, two or more selected): edge to edge, no gaps.
  Row sorts the items by their box's left edge, keeps the first where it is
  and puts each next box's left edge on the previous right edge; Column does
  the same upward from the lowest item (y up). The other axis does not move;
  boxes are bounding boxes (rotated items, a smooth track's points); locked
  items stay out (`geometry.pack`). For tiles whose size is off the grid
  (images) — grid-sized rects already butt with snapping. Not named "Fit":
  Fit frames the level.
- **Creating:** rect / ellipse / line by dragging (a shape flat after
  snapping is dropped), circle from the center out, point by click, polygon /
  track by clicks then Enter or double-click (Esc cancels). **A click** (no
  drag) with rect / ellipse / circle / line makes a default shape at the
  snapped click (Figma's rule): rect / ellipse 100 × 100 with the top-left
  there, circle radius 50 centered there, line 100 long to the right
  (`tools.default_size(grid)`: 100, or the nearest grid multiple where the
  grid does not divide 100 — 96 on 8 / 16 / 32, 128 on 64 — so the corners
  stay on the grid). v1 drew nothing on a click, which read as broken. The tool
  returns to Select with the new item selected. Images come in at their
  pixel size (1 px = 1 design unit).
- **Empty canvas (Select tool):** drag draws a selection box (items fully
  inside); Shift+drag adds to the selection. **Panning:** the Pan tool (H),
  Space+drag or the middle button, in any tool. (The spike panned on an
  empty-canvas drag; with a Select tool that read as "Select does not
  work".) The wheel zooms about the cursor. **Fit** (button + F) frames the whole level; **100%** (button +
  Primary+0) zooms to actual size about the middle of the view. (A first
  "Reset view" that jumped to the level's center at 100% read as random on
  levels wider than the screen.)
- **Snap:** on by default; **Shift** turns it off for move, handles, turning
  and drawing (not Ctrl: Ctrl+click is a right-click on macOS). One rule —
  **the corner you hold lands on the grid**: drawing / resizing snap the
  dragged corner; moving snaps the corner of the selection's bounding box
  nearest the press (`geometry.nearest_corner`, chosen once at the press so
  it never jumps; a tie → bottom-left). Grab an image by its feet and the feet
  land on the ledge. It matters only for sizes off the grid (images, circles,
  rotated shapes) — otherwise every corner lands anyway. (v1 always snapped
  the bottom-left; top-left is only "natural" in y-down tools.) Rotation snaps
  to 15°.
- **Cursors:** move over a shape and while panning; a resize cursor per
  handle that follows the item's angle; a custom rotate cursor; crosshair
  while drawing.
- **Undo / redo:** whole-document snapshots; one step per finished gesture
  (a drag, a resize, a committed field). Pan and selection are not steps.
  `app.undo` / `app.redo` (buttons and shortcuts) run `panel.poll()` first: a
  click on Undo takes focus from a field, and that field's edit must become
  its own step **before** the undo — else Undo takes back the step before it
  and the edit lands afterwards
  (`test_undo_button_lands_a_pending_field_edit_first`).
- **Shortcuts:** Primary = Cmd on macOS, Ctrl elsewhere. Redo is
  Cmd+Shift+Z / Ctrl+Y (Ctrl+Shift+Z is Scena's reserved quit). Arrows nudge
  the selection 1 unit, Shift+arrow one grid step, on the press and its
  repeats (`App.on_key`). Scena delivers a Shift+key to `on_key` (Shift does
  not block a bare key since 0.8.1), so `on_key` reads `keyp("SHIFT")`
  itself and ignores other Shift+keys
  (`test_shift_arrow_nudges_by_the_grid_once`).
- **Dialogs:** `crossfiledialog` (a Scena dependency; osascript on
  macOS, COM on Windows, zenity / kdialog on Linux), tkinter in a child
  process as the fallback, behind `scena_editor/dialogs.py`. Run in a worker
  thread (macOS / Linux) so the window keeps drawing; one at a time; the
  editor ignores canvas input meanwhile and says so in the status bar (a
  centered "finish it first" banner read as noise). macOS Cancel raises
  `OsascriptException (-128)` → treat as "no file"; the macOS save panel adds
  no extension → append `.json`; afterwards `keyp._swallow_edges()` and
  `glfw.focus_window` (the spike once came back unfocused). Confirmations
  ("unsaved changes") are in-editor `Menu`s.
  **macOS Open dialogs are our own AppleScript** (`dialogs.choose_file_script`):
  `choose file of type` takes Uniform Type Identifiers — `public.json` for
  levels, `public.image` for pictures — and `crossfiledialog` passes bare
  extensions (`{"json"}`), which match no file: every file showed grayed out
  (seen 2026-10-02; not a permissions problem). Windows / Linux keep
  `crossfiledialog`. Mocked tests never see a native panel, so
  `TestMacOpen` checks the script names UTIs (a dot, never an extension) and
  compiles it with `osacompile`; tests of the other backends pin
  `dialogs.MACOS = False` so they never open a real dialog.

- **Status bar:** file (• unsaved) and the current note or tool hint on the
  left; at the right end grid step (and "lines every N" when the drawn lines
  are thinned out), zoom (right-aligned), then the cursor in its **own
  left-aligned** Text, so nothing shifts as the numbers change width.
- **Copy / paste:** Primary+C copies the selected items inside the editor
  (images by absolute path, so they survive Open) **and** puts their Copy-as-
  code on the system clipboard; Primary+V pastes, one grid step further each
  time, names made unique; Primary+X cuts. The panel's "Copy as code" copies
  only the code.
- **Numbers:** the editor stores two decimals (`doc.tidy`); `level_format`
  rounds float noise off what it writes and prints (`239.99999999999994` →
  `240`).
- **Regular polygons** (2026-10-02): its own kind, not a Polygon generator —
  a generated `polygon` stops being regular when a point moves, and Copy as
  code would print six decimal points instead of `RegularPolygon(n=6, …)`.
  Drawn from the center out like Circle (radius snaps); a click makes a
  hexagon of radius 50; new ones have `angle=90` (a vertex on top: a
  triangle or pentagon points up). Handles: radius on vertex 0, the rotate
  knob further out on the same spoke (`geometry.heading_toward`: the angle
  is that spoke's direction, not "the top" as for rects). Panel: Sides,
  Radius, Angle. `geometry.regular_vertices` places the corners as
  `RegularPolygon` does (`test_regular_polygon_matches_scena_and_sides_field`).
- **Triangle** (2026-10-15): the `"triangle"` kind is `Triangle`
  (isosceles, `base_ratio`), not a regular polygon with `n=3`: a
  `regular_polygon` cannot hold `base_ratio`, and Copy as code should print
  `Triangle(…)`. It behaves as a regular polygon in the editor
  (`geometry.RADIAL`): drawn from the center to the apex (a click makes radius
  50), new ones point up (`angle=90`), the radius handle on the apex and the
  rotate knob beyond it. Panel: Radius, Angle and **Base ratio** (in the Sides
  row, a slider + number — see below; a typed value outside (0, 2) is refused
  with the format's message, no step).
  `geometry.triangle_vertices` places the corners as `Triangle` does (center =
  centroid, the base half a radius behind it), checked against Scena on random
  poses (`test_triangle_matches_scena_and_base_ratio_field`); group scale
  scales the radius and keeps the ratio. Guards: `test_editor_tools` (draw,
  field, handles, hit test), `test_level` / `test_level_codegen` (the kind,
  `make()`, `LevelItem.base_ratio`, copied code).
- **Concave** (2026-10-14): a box with a scoop, its own kind (`Concave`,
  [Shapes Design — Concave](Shapes%20Design.md#concave)). Drawn like a rect
  (a click makes 100 × 100, top-left there), scooped at its top left, no rim;
  the rect's handles (it is in `geometry.AREA`). Panel: **Scoop** (a drop-down
  of the eight names, in the Radius row — a concave has no radius) and **Rim**
  (text: `20` for both axes or `20, 0`, `tools._rim_text`; a bad value or a
  negative axis is refused with a message, no step). Each commit is one undo
  step (the fields commit before the drop-down in the same frame). The scoop
  is part of the view's shape key (`Concave.scoop` is fixed: a change makes a
  new shape); the rim is set on the live shape. Hit tests follow the scoop
  (`geometry.concave_scoop`, the same radii as `Concave`); the group scale
  scales the rim with the box, as `Concave.scale_by` does. Key U (for the U
  of a half-pipe; Q, K were free too). Guards: `test_editor_tools`
  (draw, panel fields, undo, hit test, group scale, Copy as code),
  `test_editor_system` in `scena_editor/tests/` (`TestConcaveOnFrames`: the real panel on frames),
  `test_level` / `test_level_codegen` (the kind, `make()`, copied code).
- **Slider + number** (2026-10-15): a bounded ratio with no unit, tuned
  by how it looks — Smooth (0–1) and Base ratio (0–2) — is a Scena `Slider`
  with a number box beside it (`panel._Slide`); lengths, positions and
  angles stay text fields (they have canvas handles, and exact values
  matter). The file is unchanged: the control shows and sets the same
  number, checked by the same format rules. A drag is **one undo step**, as
  a canvas drag is: each move updates the document unrecorded
  (`set_field(…, record=False)`, the view redraws live, the box follows),
  and letting go of the handle records it (`history.commit()`); a click on
  the track or a wheel turn records at once. Scena's `Slider` has no public
  drag-ended signal, so `_engine.slider_dragging` reads it. The slider's
  range is inside the format's (Base ratio: 0.05–1.95, the format refuses 0
  and 2), so a drag is never refused; the box takes any accepted value and
  commits like every field. Guards: `test_smooth_slider_drag_is_live_and_one_undo_step`,
  `test_base_ratio_slider_stays_inside_the_format` (real presses through
  Scena's widget manager).
- **Smooth tracks:** the panel's Smooth control (tracks only; 0–1, refused
  outside with the format's message) is `Track.smooth`. The view draws the
  item with it; hit tests follow the drawn curve (`geometry.track_curve`,
  Scena's own sampling through `_engine.track_curve`), while bounds, X / Y
  and snapping stay on the points — the curve runs through every point, and
  `LevelItem.center` is the points' box middle too. `points` of a smooth
  track are its control points: `move_along(item.make())` follows the curve.
- **Groups field, one item or several:** the same field and parsing (split
  on commas **or semicolons**, trimmed, no empties or repeats; any other
  character is legal — Scena takes any non-empty name, accents and spaces
  included). ";" separates too because it is the list separator where "," is
  the decimal one (pt-BR spreadsheets); taken as part of a name it made a
  group nobody meant. The field then shows the result with commas, even when
  the edit changed nothing. Cost, accepted: a hand-written file's group
  `"a;b"` (the format still reads it) splits if edited in the field. One item:
  its groups become the typed list. Several: the field shows the groups
  **every** item has; a typed name is added to all, a deleted one removed
  from all, and groups only some items have stay — they are listed read-only
  under the field (`Some: …`, cut to fit, the whole list in its tooltip). It
  replaced "Add group" / "Remove group" inputs, where you typed a name to
  remove and saw nothing happen. After an edit the status bar says what
  changed (`Groups: chao, «moving enemies»` — a name with a space in « » so
  it reads as one group; `Added "x" to 5 items`), and a name new to the level
  that is close to an existing group gets a did-you-mean (`validate.did_you_mean`,
  case-insensitive) — a hint, never a refusal; it leads the note, since a
  long note is cut at the status bar's end (`Editor.set_groups`).
- **Several selected, panel:** Groups, X / Y of the box of the items that
  move (typing moves them, `Editor.move_selection_to`), Row / Column, and
  the item buttons; the title adds the group when the selection is one
  ("4 selected · robo").
- **Select group [▾]** (top bar, after 100%): a selection command beside the
  Select tool — where the reference editors keep "select by …" (Illustrator
  Select ▸ Same, Figma "Select matching layers"), not in the inspector; fixed,
  so it never moves with the panel. The list: None and the level's groups A–Z
  (faded when there are none; a group named "None" keeps its name and the
  entry becomes "(None)"). **The control mirrors the selection:** choosing a
  group selects its items in file order; choosing None while a group shows
  selects nothing (while None shows, it changes nothing). **Its value is
  computed from the selection, never remembered** (`Editor.selected_group`):
  the group's name while the selection is exactly that group's items, else
  None. A remembered pick would lie the moment a Shift+click changed the
  selection. The last pick is only a tie-breaker: when two groups have the
  same items it shows the one you chose ("xyz", not "abc"), else the first
  A–Z. No tooltip: the label says it, and a tip that popped up while the
  list was open got in the way. (A first version lived in the panel, showed
  "Select group…" always and reset after a pick: no feedback, and it jumped
  between two rows.) A long list scrolls (Scena's DropDown stops at the
  window edge and scrolls with the wheel).
- **Panel:** a line shows X1 / Y1 / X2 / Y2 (other kinds X / Y = center); an
  image path is shortened in the middle to fit; the unsaved-changes prompt
  uses a lighter panel and a smaller font than the Menu default.
- **Button callbacks are the app's methods** (`app.save`,
  `_safe(app.choose_tool, tool)`). Scena passes the Button only to a parameter
  with no default, so `save(then=None)` gets nothing. (Before that rule,
  `panel._action` wrapped every callback: Scena gave the Button to optional
  parameters too.) `test_every_button_clicks_through_scena` clicks each Button
  through Scena's widget dispatch; `test_every_tool_button_clicks_through_scena`
  clicks each icon button through Scena's `ui` shape dispatch (center and
  letter corner).
- **A callback error does not close the editor** (`app.guarded`): the gesture
  is dropped, the traceback printed, the status bar says so. The wrapper trims
  arguments with Scena's own counter (`validate.payload_arity`): Scena hands a
  `*args` wrapper every argument.
- **Panel fields** commit like any Scena `TextInput` (Enter or focus loss).
  Editor shortcuts with Primary (Cmd+S, Cmd+O, Cmd+D …) still work while a
  field is focused: Scena commits the field first, and `panel.poll()` runs
  before `_shortcuts()` in `update`, so Save writes the edit. Primary + A / C /
  X / V / Z stay in the field (its own select all / clipboard; undo is a no-op
  there), plain keys type.
- **Panel refresh** decides every element's visibility first and then changes
  only the ones that differ (`panel._set_visible`). A field commit bumps
  `doc.version`, which triggers a refresh; hiding and re-showing a field that
  stays visible drops its keyboard focus, which broke Tab between fields and
  dropped focus after Cmd+S (`test_editor_system`:
  `test_tab_between_panel_fields_commits_and_keeps_focus`,
  `test_save_shortcut_in_a_focused_field_saves_the_edit`).
  `Panel.poll` applies a commit to the item the field **was showing**, not the
  current selection: clicking the canvas commits the field in the same event
  that selects something else.

### Spike lessons

- Holding a button, Scena calls **both** `on_mouse_move` and `on_mouse_drag`
  for each event (`orchestration.py`, `CanvasManager.handle_mouse_move`).
  Handle pointer motion in **one** of them: anything that accumulates (a pan
  step) would run twice.
- `canvas.pan_by(d)` moves the **content** by `d`. A grab-pan is
  `pan_by(current − grabbed)`; recomputing `current` per event keeps the
  grabbed world point under the cursor with no accumulated drift (traced:
  error returns to 0 on the next event).
- `keyp.once("CMD+O")` used to fire for keys never down together (bug IN1,
  [Testing Design.md](Testing%20Design.md)); fixed in `input.py`.
- **Widgets draw after the whole `ui` layer** (`orchestration.py`,
  `_draw_ui_layer` then `widget_manager.draw`), so no Graphic can sit on a
  `Button`: an icon there is hidden under it. An icon button is therefore a
  `ui` Rect holding `on_click` / `on_hover` / `on_hover_exit`, with the icon
  and letter as handler-less Graphics — Scena leaves those out of hit tests
  (`Shape._sync_interactive_registry`), so the pointer reaches the Rect.
  `Text(center=…)` without `layer=` is a **world** caption; HUD text takes an
  anchor (`top_left=` …) or `layer="ui"`.

## Starting the editor

**Install.** `pip install scena` brings everything: the framework, the
editor (package `scena_editor`) and its native file dialogs
(`crossfiledialog`, a plain dependency — no extra). `pyproject.toml` is the
only package definition (`setup.py` is gone); the editor's tests do not ship
(`[tool.setuptools] packages = ["stage", "scena_editor"]`).

**Two ways to start it from a terminal** — the same program:

| Command | When |
| --- | --- |
| `scena-editor [fase.json]` | pip puts this command next to Python's own scripts; works wherever that folder is on the PATH (a virtual environment, the python.org installers, conda) |
| `python -m scena_editor [fase.json]` | always: the Python that runs your games runs the editor (Windows without "Add to PATH", `pip install --user`) |

The file is opened, or created on the first Save.

**A launcher icon, once:** `scena-editor --shortcut` (or
`python -m scena_editor --shortcut`). pip cannot make icons — a package runs
no code when it is installed — so the author runs this once after
`pip install scena`:

| System | What it makes |
| --- | --- |
| Windows | "Scena Editor" in the Start menu and on the desktop (`.lnk` through PowerShell), running `pythonw -m scena_editor` (no console window) |
| macOS | `~/Applications/Scena Editor.app` (Launchpad, Spotlight, the Dock): an AppleScript applet (`osacompile`) that starts `python -m scena_editor` and quits, our icon, re-signed ad hoc (`codesign -s -`) |
| Linux | `scena-editor.desktop` in the applications menu, and on the desktop when there is one |

**macOS: not a shell-script app.** A bundle whose executable is a shell script
has no architecture LaunchServices can read; on Apple Silicon it asks to
install Rosetta (seen 2026-10-01). The applet's executable is Apple's
universal binary (arm64 + x86_64). Editing the bundle (icon, name) breaks the
seal `osacompile` signed, and arm64 code must be signed: hence `codesign`
after the edits. Guard: `test_macos_applet_with_the_real_tools` (`lipo`
architectures, `codesign --verify`). While the editor runs, the Dock shows
Python's icon (the applet has already quit).

The launcher holds the absolute path of the Python that ran the command:
run it again after reinstalling Python. The icon is drawn with Skia when the
command runs (no image files in the package). Only through the command — the
editor never offers or makes icons by itself.

`scena-editor` is a **console** command on purpose: as a Windows GUI command
it would have no console, and `--shortcut` could not say what it made. The
icons start the editor with no console window.

**Error log.** Started from an icon there is no terminal, so every error the
editor reports is appended (with its traceback) to a per-user log, and the
status bar names it: macOS `~/Library/Logs/Scena Editor/editor.log`, Windows
`%LOCALAPPDATA%\Scena Editor\editor.log`, Linux
`~/.local/state/scena-editor/editor.log` (past 1 MB it starts over, one old
copy kept). A crash while starting is logged too. Callback errors
(`app.guarded`) and Button errors (`toolbar._safe`) keep the editor running.

## Boundary

The editor is a companion app: top-level package `scena_editor/` in this repo,
shipped in the same distribution. **One-way dependency:** nothing in `scena/`
imports `scena_editor`; the editor uses the public API, and every Scena
private it needs goes through `scena_editor/_engine.py`: the close guard
(`ScenaFramework._close_guard`, the one hook added to `scena/` for the editor —
asked on a window close request and on Ctrl+Shift+Z; `tests/test_close_guard.py`),
the GLFW window for title / clipboard / focus / cursors, the live widgets
(the frame picker disables the rest), a sheet's per-frame rects and sizes
(`sheet_frames`: `Sheet` has no public per-frame size) and an atlas's listed
image,
`keyp._swallow_edges()` after a dialog, and whether a `Slider`'s handle is
held (`slider_dragging`: the panel records a drag when it is let go). Scena has no tooltip or icon-button
widget: the editor builds both from Graphics (`toolbar.py`) — a public-API
candidate if a second program needs them. A gap that
piles up there is a public-API candidate. The level **format** and the
**reader** are framework (games need them at runtime); the editor only writes
through `level_format.serialize`.

## Fences

| Don't | Revisit | Where |
| --- | --- | --- |
| `Level(...)` creating anything at load; a bulk `level.make_all("g")` | A taught script needs a group made with no per-item change, and a two-line loop over `level.group(...)` is the friction | here |
| `Rect(box=item)` — a `LevelItem` as a `box=` input | Never — second spelling of `item.box` | here |
| Behavior or numbers in the file (speed, hp, custom fields) — see [Why no values](#why-no-values-in-the-file) | A taught game needs non-geometric per-item numbers (time, hp, worth) on many unnamed items, where naming each one to key a dict in code is the friction | here |
| Layers in the file / editor | A taught level needs per-layer hide or lock that groups, `locked`, guides and z-order cannot give | here |
| Several levels per file | A taught game needs shared items across levels that one file per level cannot express | here |
| Clips, fps, `anchor` or `pixel_size` in the `sheets` table | A taught level needs animated scenery that `level.sheet(name).clip(...)` in code cannot express | [Sheets](#sheets) |
| A tile layer (a grid of frame indices) or Tiled `.tmx` import | A taught level needs thousands of tiles that one item per tile cannot carry | [Sheets](#sheets) |
| `flip_x` / `flip_y` on image items | A taught level needs a mirrored decoration or tile that rotation cannot give | here |

### Why no values in the file

Weighed 2026-10-14 (per-item `hp`, speed, text). Values split an item's
meaning between the file and the script: the reader of the game no longer
sees every rule in the code. Free-form keys have no schema, so a typo turns
silent (`item.get("velocidade", 90)` against a key `velocida` gives 90),
against the format's rule that refuses unknown keys and `level.group`'s that
a typo must not become an empty loop. And most per-item "numbers" are
something the editor already holds better:

| Looks like a value | Is really | Home |
| --- | --- | --- |
| an elevator's travel, a patrol range, a trigger area | a distance or a region | geometry: draw the zone (a tall rect, `item.box`), a line, a track |
| fast / slow robots, a red door and its key | a category | groups (`robo` + `rapido`) |
| the one boss, the start | a unique item | a name, and a dict in code keyed by it |

What is left — numbers that are not distances (a delay, a phase, hp, a
coin's worth) varying item by item over many unnamed items — is the revisit
trigger in the table above. **If it fires:** never one value per item (the
panel would show `Value: 120` with its meaning only in code; an item in two
groups has one slot; the first item needing two numbers forces a second
format). Instead a flat `name → number | string` dict, edited in one field
parsed like Groups (`hp=3, speed=120`), a strict reader (a key no item in
the level uses raises with did-you-mean, even through a default), ignored by
`make()` and Copy as code, and a format version bump.

