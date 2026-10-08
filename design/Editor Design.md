# Editor Design

Level files and the level editor. **The editor places geometry; code decides
what it becomes.** Two parts:

- **`Level`** (framework, `scena/level.py` + `scena/level_format.py`): reads a
  level file. Creates nothing.
- **The level editor** (companion app, `scena_editor/`, `python -m scena_editor`):
  draws rects, ellipses, circles, lines, polygons, regular polygons, tracks,
  points and images on
  a level area, names and groups them, saves the file. Not part of the
  framework (see [Boundary](#boundary)).

Hub: [Scena Design.md](Scena%20Design.md). Regions: [Box Design.md](Box%20Design.md).
Author catalog: [Guia da API](../docs/pt/guide/index.html#colocar-fase).

Today’s baseline — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| What a level file holds | [File format](#file-format) |
| `Level` / `LevelItem` / `make()` / `.box` | [Reading a level](#reading-a-level) |
| Copy as code | [One constructor table](#one-constructor-table) |
| Install, start, launcher icon, error log | [Starting the editor](#starting-the-editor) |
| What the editor does (v1) | [Editor](#editor-companion-app) |
| Why the editor is not in `scena/` | [Boundary](#boundary) |
| Settled nos | [Fences](#fences) |
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
| Editor window: drawing the document | `scena_editor/view.py` | `tools.py` | [Editor](#editor-companion-app) |
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

# File format

`*.json`, one level per file. Scena design units, **y up**, centers, `angle`
in degrees counter-clockwise — the numbers an author writes in code; no
conversion anywhere.

```json
{"format": "scena-level", "version": 1, "size": [3600, 1500], "items": [
  {"kind": "rect",    "groups": ["plataforma"], "center": [1000, 150], "width": 220, "height": 24, "angle": 20},
  {"kind": "ellipse", "name": "lago", "center": [500, 60], "width": 300, "height": 80},
  {"kind": "circle",  "center": [10, 10], "radius": 16},
  {"kind": "line",    "p1": [0, 0], "p2": [10, 10]},
  {"kind": "polygon", "name": "morro", "points": [[0, 0], [100, 0], [50, 80]]},
  {"kind": "regular_polygon", "name": "favo", "center": [700, 400], "radius": 30, "n": 6, "angle": 90},
  {"kind": "track",   "name": "rota_drone", "points": [[900, 600], [1300, 600]], "smooth": 0.5},
  {"kind": "point",   "groups": ["estrela"], "center": [330, 320]},
  {"kind": "image",   "name": "fundo", "file": "arte/fase1.png", "center": [1800, 750],
                      "width": 3600, "height": 1500, "locked": true}
]}
```

- `format` / `version` are plumbing: a JSON that is not a level fails clearly
  ("not a Scena level file"); a newer version is refused ("Update Scena").
  `Level` exposes neither.
- `items` order is the draw order.
- Common keys: `name` (optional, unique in the file), `groups` (optional list,
  no repeats), `locked` (editor-only).
- Per kind (required, then optional with default): rect / ellipse
  `center, width, height` · `angle=0`; circle `center, radius`; line
  `p1, p2`; polygon `points` (≥ 3); regular_polygon `center, radius, n`
  (sides, a whole number ≥ 3) · `angle=0` (toward vertex 0, as
  `RegularPolygon`); track `points` (≥ 2) · `closed=false`
  · `smooth=0` (0 to 1, `Track.smooth`: 0 straight segments, 1 a curve);
  point `center`; image `file, center, width, height` · `angle=0`,
  `guide=false`. Sizes are magnitudes (≥ 0).
- Image `file` is a POSIX path **relative to the level file**.
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
  `serialize` is canonical (`TestFormatProperties`).

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
- `level.names`, `level.groups` (first-use order), `level.size`, `level.box`
  (fresh, `(0, 0)` → `size`), `level.path`, iteration, `len`, `in`.
- **`LevelItem`** — `kind`, `name`, `groups`, `center` (a line's midpoint, a
  polygon's / track's bounding-box middle — of its points, not of a smooth
  curve), and per kind `width` / `height` /
  `angle`, `radius`, `n`, `p1` / `p2`, `points` (new list of `Vec2`),
  `closed`, `smooth`,
  `image` (absolute). A field of another kind raises `AttributeError`
  listing what the item has. Every read is a copy.
- **`item.box`** — fresh oriented `Box(center, width, height, angle)` for
  rect / ellipse / image; a circle's square. Lines, polygons, regular
  polygons, tracks and points raise (only those four kinds are regions).
- **`item.make(**kwargs)`** — builds the shape as drawn: rect → `Rect`,
  ellipse → `Ellipse`, circle → `Circle`, line → `Line`, polygon → `Polygon`,
  regular_polygon → `RegularPolygon(n, center, radius, angle)`,
  track → `Track(points, smooth, closed)` (`smooth` always written: the
  file's default is 0, `Track`'s own is 1), point → `Point`, image →
  `Sprite(file, center, width, height, angle)` — every field is a
  constructor keyword. The item's groups are applied; `group=` **adds**; other
  keywords pass through (`layer=`, `color=`, `visual=`); a geometry keyword
  raises (`TypeError`, "remove center="). A guide raises.

## One constructor table

`level_format.constructor_for(item)` → `(class name, args, kwargs, settings)`
is the only kind → constructor mapping. `LevelItem.make()` calls the class;
`level_format.code_for(item)` prints it — the editor's **Copy as code**
(`moeda = Circle(center=(1, 2), radius=3)`; named items get a variable; a
rotated item gets `angle=`: `Sprite("a.png", center=…, width=…, height=…,
angle=30)`). `settings` (attributes set after construction) is empty today;
it stays in the table for a class that lacks a keyword. Copied lines name the
image as the file does (relative); `make()` passes the absolute path.
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
  Polygon (G), Regular polygon (N), Track (A), Point (P), Image (I). Point
  has P because it is used most; T is left free for a Text tool. Panel: name, groups
  (comma-separated), numeric geometry, locked, guide; Copy as code,
  Duplicate, Delete, Front / Back. Status bar: cursor in Scena units, zoom,
  file and unsaved mark.
- **Layout:** the left toolbar holds only what you create — Rect, Ellipse,
  Circle, Line, Polygon, Regular polygon, Track, Point, a gap, Image (it
  opens a file dialog).
  The top bar: New / Open / Save / Save as │ Undo / Redo │ Snap, grid step │
  Select, Pan, Fit, 100%. Undo / Redo are text Buttons, faded (`enabled`)
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
  height, width from the new picture's proportions.
- **Select:** click; Shift+click adds / removes; drag a shape moves the
  selection; handles resize (8; images 4 corners, aspect kept) and rotate (1);
  click again cycles overlaps. Shift+**press** only adds — a selected shape
  is removed on release of a Shift+**click** — so Shift+drag of a selected
  shape still moves it (snap off). On a small shape the handles cover its
  middle: a handle wins only when the pointer is nearer to it than to the
  shape's center. Locked shapes select but show no handles and do not move
  or delete.
- **Creating:** rect / ellipse / line by dragging (a shape flat after
  snapping is dropped), circle from the center out, point by click, polygon /
  track by clicks then Enter or double-click (Esc cancels). **A click** (no
  drag) with rect / ellipse / circle / line makes a default shape at the
  snapped click (Figma's rule): rect / ellipse 100 × 100 with the top-left
  there, circle radius 50 centered there, line 100 long to the right
  (`tools.DEFAULT_SIZE`; every grid step divides it, so the corners stay on
  the grid). v1 drew nothing on a click, which read as broken. The tool
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
  Cmd+Shift+Z / Ctrl+Y (Ctrl+Shift+Z is Scena's reserved quit).
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
- **Smooth tracks:** the panel's Smooth field (tracks only; 0–1, refused
  outside with the format's message) is `Track.smooth`. The view draws the
  item with it; hit tests follow the drawn curve (`geometry.track_curve`,
  Scena's own sampling through `_engine.track_curve`), while bounds, X / Y
  and snapping stay on the points — the curve runs through every point, and
  `LevelItem.center` is the points' box middle too. `points` of a smooth
  track are its control points: `move_along(item.make())` follows the curve.
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
the GLFW window for title / clipboard / focus / cursors, and
`keyp._swallow_edges()` after a dialog. Scena has no tooltip or icon-button
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
| Behavior or numbers in the file (speed, hp, custom fields) | A taught game needs per-item numbers that a name and a dict in code cannot express | here |
| Layers in the file / editor | A taught level needs per-layer hide or lock that groups, `locked`, guides and z-order cannot give | here |
| Several levels per file | A taught game needs shared items across levels that one file per level cannot express | here |
