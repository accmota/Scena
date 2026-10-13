# Canvas Design

Design space, canvas, camera, layers, wallpaper / background attachment,
offscreen cull, and the scene draw walk. **Happy path for this subsystem** —
pick one row; do not read the rest. Looks / post / quality:
[Effect System Design.md](Effect%20System%20Design.md). Hub:
[Scena Design.md](Scena%20Design.md). Author calls:
[Guia da API](../docs/pt/guide/index.html#mundo).

Today’s baseline, not a freeze — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Design space / HUD / `ui` | [Run loop and design space](#run-loop-and-design-space) |
| Camera (timed) / `frame_to(None)` | [Timed camera](#timed-camera) |
| Follow sugar (`chase` / `deadzone`) | [Follow math](#follow-math-chase--deadzone) |
| Offscreen cull | [Offscreen culling](#offscreen-culling) |
| Leave bounds | [Playfield leave bounds](#playfield-leave-bounds) |
| Measuring Box / views | [Box Design.md](Box%20Design.md) |
| Layers / registry | [Registry and layers](#registry-and-layers) |
| Background attachment | [Background engine](#background-engine) |
| Parallax (architecture) | [Parallax layers](#parallax-layers-decoration-only) |
| Background kinds / cost | [Effect System Design.md §3.1e](Effect%20System%20Design.md#31e-backgroundfields-scenabackgroundpy-scenabackground_kindspy) |

## Use

1. Pick one jump-box row.
2. Read that section only (search; do not read the rest of this file). Treat fences there as current constraints.
3. Open **Start** only if the section is not enough.
4. Open **Also** / another Design doc only if Start is not enough.
5. Stop. Do not ingest `scripts/`, `_sksl_*`, or the private archive / proposals unless the shader or a named campaign is the task.

## Router

| Need | Start | Also |
| --- | --- | --- |
| `run()` / window / frame order | `orchestration.py` | [Scena Design.md — Datapath](Scena%20Design.md#datapath) |
| Camera, layers, cull, draw walk | `canvas.py` | `registry.py` |
| `chase` / `deadzone` (follow math) | `easing.py` | `scenamath.py` (`_as_xy`), `canvas.py` |
| Parallax layer CTM | `camera_response.py` | `registry.py`, `canvas.py` |
| Wallpaper / background stack | `background.py` | `background_kinds.py` (kinds) |
| HUD `Text` | `text.py` | `uiwidget.py` |
| `@leave_playfield` | `bounds.py` | [Box Design.md](Box%20Design.md) |
| `Endless` (fill what the camera sees) | `endless.py` | `canvas.py` (`layer_view`), [Endless fill](#endless-fill) |

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| Registry / `group` | `registry.py` | draw/camera (`canvas.py`) or the loop (`orchestration.py`) |
| `canvas.follow` | does not exist | `chase` / `deadzone` + `pan_to` in `update` |
| Background **kind** | `background_kinds.py` | stack/attachment (`background.py`) |
| HUD `Text` | `text.py` | `uiwidget.py` |
| `canvas.playfield` | leave-area config (`bounds.py`) | camera frustum / `game_view` |
| `canvas.game_view` | world frustum as a fresh `Box` | HUD `ui_view` / playfield |
| `layer.view` | that layer's window in its own coordinates (parallax lags the camera) | `canvas.game_view` (world, gameplay layers) |
| `Endless` | discrete actors built per slot, by distance | `Wallpaper(tile)` (repeated pixels) / `every` (spawn by time) |
| `layer=10` (int) | numeric position sugar; frozen z; own namespace | `canvas.layers.create(10, …)` → `TypeError` (string-only); `"10"` is a different key |

## Not in this doc

- Shape / Sprite draw envelopes and filter batching → [Effect System Design.md](Effect%20System%20Design.md)
- Collision / hit-test on world space → [Collision Design.md](Collision%20Design.md)
- Process tick and Entity park → [Actors Design.md](Actors%20Design.md)
- Groups / formula `@=` → [Actors Design.md](Actors%20Design.md#fleet-helpers-groups)
- Background kinds inventory / cost → [Effect System Design.md §3.1e](Effect%20System%20Design.md#31e-backgroundfields-scenabackgroundpy-scenabackground_kindspy)
- Author catalogs → [Guia da API](../docs/pt/guide/index.html#mundo)
- Measuring `Box` / `game_view` / `ui_view` → [Box Design.md](Box%20Design.md)


# Run loop and design space

## orchestration.py

Contains the main application class (`ScenaFramework`), the event loop, and subsystem init. Windowing uses a **design space** (authored coordinates, default 2000×1200, **y-up**, origin at bottom-left) mapped into the OS window via `view_scale`, letterbox pads (maximized / fullscreen), and a Y-flip into Skia/GLFW y-down, plus Retina `pixel_ratio` into the framebuffer. The OS window is derived at `open_window()` from design aspect, the monitor **work area**, real frame insets, and `window_scale` (default 0.8 of the largest windowed fit), always centered. `init(width=, height=)` is design space, not OS pixels. `canvas.display` is `"windowed"` / `"maximized"` / `"fullscreen"` — maximize fills the work area; fullscreen covers the monitor; both letterbox (never stretch). Mouse and widgets work in the same y-up design coordinates.

Canonical frame order: [Scena Design.md — Datapath](Scena%20Design.md#datapath).
Scene-specific after `flush()`: tick transients / SpatialFx / cover, then wallpaper +
background fields, camera + world layers, optional post, then the **view pass**
(`ui` Graphics + widgets), then cover. Looks / post: [Effect System Design.md](Effect%20System%20Design.md).
Background and the camera CTM are applied inside `_draw_frame`, after `update` /
flush, on both the direct window path and the post path (the scene never paints
under the previous frame's camera).

**Letterbox bands stay black.** In maximized / fullscreen the framebuffer is wider
or taller than the design rectangle. The background clears it black and paints
the wallpaper inside the design rectangle only. The world pass is not clipped:
the scene, the post compose (Grain / Scanlines / Fog / Vignette draw over the
whole framebuffer), the `top` layer and the debug overlays all draw past the
rectangle. So `_draw_frame` paints the bands black once
(`_mask_letterbox_bands`), after the world pass and before the view pass.
Without it, a body half outside the design rectangle showed its outer half in the
bands (LB1; `cull_offscreen` only drops bodies wholly outside). The view pass
(`ui` Graphics, widgets) and the cover are not masked. A `clipRect` on the world
pass was measured first: about +1 % per frame in letterbox, a scissor on every
world draw. The two band rects cost nothing measurable. Pinned by
`tests/test_diff_pipeline.py` (`TestLetterboxBands`, with a canary).

Widgets and Graphics on the reserved **`ui`** layer draw last (before canvas cover), in **view** space (camera-immune HUD). Decorative `Text` captions are
unboxed by default (`color=` is ink only). ``font=`` is a family name or a
``.ttf`` / ``.otf`` file (same search as images); omitted uses ``ui.font``.
A missing font warns and falls back to the default typeface. ``.font`` is that
spec, not a Skia object. Assigning it remeasures. `Text(..., background=)` paints an
opaque rounded plate behind the **layout box** — visual only. Omit `width=` and
the box follows the string (Label contract); with `width=` the box is fixed and
overflow **clips** (no wrap). `\n` (and `\r` / `\r\n`) is a hard break: height
is n × line metrics.

**Text placement is one point.** `top_left=` / `top_center=` / `top_right=`
(Rect's own part names) pin that point of the layout box; the string grows
**away** from it — always downward, and right / both ways / left. So a caption
near the top of the screen never needs its own height, and a line added later
(formula text) or a bigger `font_size` keeps the first line where it was. Layer
omitted → `ui` (HUD); a world `layer=` makes an anchored world caption (never in
the HUD column). `center=` is the pose itself (the box grows around it). `box=`
is `center=` the region's centre on `ui` with `width=` the region width; like
`center=` it does **not** join the HUD column. No placement keyword → the next
HUD column slot (anchor `top_left`). There are no scalar placement keywords
(`x1=` / `y1=` / `x=` / `pos=` raise with a hint naming the point spellings).
A line-count change after construct does **not** reflow the HUD column.

`align=` (`"left"` / `"center"` / `"right"`) places **each line inside the box**
(`width=` or the widest line) and never moves the anchor. Its default follows
the anchor (`top_left` → left, `top_center` / `center=` / `box=` → center,
`top_right` → right). Every anchor × align combination is legal, with or
without `width=`: a multi-line block justifies its shorter lines (a
`top_right=` block of left-aligned stats lines), and a single line has nothing
to justify *yet* — formula text can gain lines, so validity cannot depend on
the current string (the old "left/right needs `width=`" `TypeError` wrongly
refused left-justified multi-line world captions). The framework
**SCENA WARNING** banner is a `top_left=` caption lifted by its own height:
light ink on a solid plate, just above the FPS line; **Ctrl+Shift+E** dismisses
it. (Author errors raise; the banner only carries warnings such as a missing
sound.)

**Anchors and parts.** Text has four Point parts — `center`, `top_left`,
`top_center`, `top_right` — all readable, each the current layout box as drawn: turned
and scaled about `center` (a read re-lays-out first). The anchor is the pin of the drawn
corner, so `text.top_left` is `text.box.top_left` at any rotation or scale. `rotate_by` /
`scale_by` pivot on `center` (or `about=`) and move a snapshot anchor with the drawing; a
linked anchor cannot move, so they raise `LinkedAttributeError` like `move_by`
(`force=True` unlinks). HUD captions (never turned) are unchanged. Text cannot be
flipped: `flip_x` / `flip_y = True` raises `TypeError` (mirrored text is unreadable). Which are Defining follows the placement, like a Rect
model: the anchor (and `center` too, for a snapshot anchor); `center` alone for
`center=` / `box=`. The others are Derivate: writing them raises
`DerivedAttributeError`. A placement link changes this while it links (see
"one placement link" below): the linked part is the only Defining placement
part. The anchor follows the usual construction rule:
**bare values copy, callables link** — `top_left=lambda: panel.top_left`, or a
tuple with a callable component (`(lambda: x * 2 + 10, 50)` links x only).
A `Point` passed as a value is copied, exactly like `Rect(top_left=p)`. With a
**linked** anchor the anchor is the only Defining pose: `center` is Derivate
(like `Rect(top_left=lambda: …).center`), every pose writer (`move_by`,
`move_to`, timed moves, drag, `resolve()`) raises `LinkedAttributeError`
naming the anchor, and `t["top_left"].unlink()` frees it (`center` stays
derived: move with the verbs). `graphic.box` works on Text (the layout box,
scaled and turned). Box edges are internal (`_x1 _y1 _x2 _y2`, min / max,
y-up) — never an author attribute.

**Clone.** `text.clone()` keeps the placement form and the pose: an anchored
caption's copy is anchored by the same part, pinned at the source's pin (a
snapshot — a linked anchor is not copied), with the same `angle` / `scale`,
so a longer string grows from the same corner; a pose caption's copy is placed
by `center`. A world caption's copy stays in the world (an anchor alone would
default to the HUD); a HUD caption's copy stays in the HUD but does not join the
stack column (`stack=False`). `clone(center=)` places the copy by its center.

**Moving an anchored caption.** On an anchored caption the anchor point is the
placement and `center` is the midpoint of the box, derived from it; on a pose
caption (`center=` / `box=`) the midpoint is the pose and a longer string grows
around it. Every pose writer translates an anchored caption's pin: `move_by` /
`move_to` (instant or `time=`), `move_along`, `confine`, a `resolve()` nudge,
drag, `tween` on `center` or on the anchor, `center =`, and an absolute anchor
write (`t.top_left = P`). `move_to(x, y)` still means "the midpoint goes to
`(x, y)`", like any graphic, never "the anchor goes there"; `align` does not
change. How (`scena/text.py`): the box `_x1.._y2`, the pin `_pin` and the last
published centre `_center_rec` are the record of the last layout.
`_refresh_layout` takes the pin from the anchor part when it links or was
written (`anchor ≠ _pin`); otherwise it shifts the pin by
`center − _center_rec` (a `center` write since the last layout is a
translation). A linked `center` is not a translation: it is the pin itself,
and the box is laid around it. Then it re-lays-out the box away from the pin for the current
string and publishes the parts (`_publish_parts`). Move verbs write the anchor
(`_shift_anchor`). Text's cull box (`_domain_aabb`) bounds the caption as drawn — turned and scaled about its center (it ignored rotation, G13). Layout runs on draw, cull, hit-test, and **every outside
read of a part** (`_TextPartSlot`; `center` only on anchored captions), so each
verb, `tween` start, formula and author read sees the string showing now.
**Why the read hook:** a string change never notifies — formula text is pull
(the cell is only marked dirty), and `flash_text`, `font_size`, `ui.font`, and
a shader fill also change the width — so without it a part lags the string,
and a move built from that stale midpoint jumped by half the width. **Invariants
for Text code:** the anchor (or `center` for a pose caption) is the only pose
input; the box and the other parts are output, written only by
`_publish_parts` under the layout scope (`_in_text_layout`), which also records
`_center_rec` — write `center` outside it and the next refresh reads a
translation. `center` must exist before the first layout (the constructor
reads it): created later it would start at `(0, 0)` and read as a jump. An
anchored caption takes one placement link — its anchor or its `center`, in any
spelling (`t["center"] @=`, `t.center @=`, a leaf `t.center["x"] @=`) — and
the second link raises (`LinkedAttributeError` from the bracket,
`DerivedAttributeError` from a part: both were accepted and disagreed, GX13
in Testing Design). **A linked part is the pin while it links**, so it holds
its formula whatever the string does. A linked anchor: as above. A linked
`center`: the box is laid around it (a longer string grows both ways, like a
pose caption), the anchor follows as output (a write raises
`DerivedAttributeError`), and the move verbs raise `LinkedAttributeError`
naming `center`. A string change used to keep the anchor and move a linked
centre off its formula (GX20). Unlinking restores the construction model: the
anchor, where it is now, is the pin again. How: `Text._sync_placement_model`,
run by the `Container._note_part_link_changed` hook on every link install and
unlink, retypes the placement parts (`_field_type`, `_defining_part_names`;
the bare-write cache is dropped); a `Text(top_left=lambda: …)` caption stays
anchor-only after an unlink, as its construction model says.
**Constructor anchors are tops; `_y1` is the min (bottom) edge — never feed one
into the other without the height** (that was bug A: `box=` put the region
centre on the bottom edge). **Limit:** a formula that *reads* `placar.center`
is re-pulled only when a part is published, i.e. at the next layout (draw or
any outside read), so it can lag a string change by one frame. Tests:
`tests/test_text.py` (`TestTextAnchors`, `TestTextAnchorLinks`,
`TestViewPinMotion`, the Hypothesis properties in
`TestViewPinMotionProperty`), `tests/test_box.py` (`box=` centring).

**HUD column.** View `Text` (layer `ui`, no `center=`) and `UIWidget` share one
construct-time column on `WidgetManager`. A widget is an Entity (`group=`,
`visible`, `destroy()`, timers) drawn here, not on a registry layer. `visible=False`
skips draw and input. A modal widget (see Menu) is the only pointer target;
misses are consumed, and `keyp` / `mouse.press` read False until it closes. `group["opts"].visible` / `.destroy()` covers widgets and
HUD `Text` in that group together. Every item is placed by its visual
top-left: omit `top_left=` to stack downward (y-up, default origin
`(20, design_h - 40)`); an explicit `top_left=` (or a Text anchor on `ui`)
still advances the cursor so the next omitted item continues below. A widget's
`top_left=` is a snapshot point-like (widgets have no pose graph: a callable
raises). World `Text` (`center=`, a world-layer anchor) and `Text(box=)` never
touch the column. `stack=False` opts out (FPS / error captions; an unplaced
`stack=False` caption takes the next slot without consuming it).
`widget.box` is a fresh read-only view-space `Box` of the widget's rectangle,
for placing things next to it.
`ui.gap()` inserts a theme gap. `ui.stack_origin(x, y)` also takes one point
(`ui.stack_origin(slider.box.top_right + (16, 0))`), like `move_to`.
`ui.stack_reset()` / `ui.stack_origin(x, y)` /
`ui.stack_from(item)` / `ui.stack_column()` move the cursor and start a fresh
column list. Destroying the last live item of the **current** column rewinds
the cursor to that column's x and visual top and drops a pending `ui.gap()`.
A partial destroy does not rewind. Items left behind by a stack move are not
tracked, so destroying them does not move the cursor. A constructor that
raises after taking its slot is not a destroy. It puts the cursor back exactly
where it found it, even when other items stay in the column:
`begin_hud_item` records the cursor and the construct rollback
(`place._drop_failed_construct`) restores it, whatever raised (A39 in
[Testing Design](Testing%20Design.md#bug-catalogue)). `ui.stack_column()` starts a new column at this
column’s visual top, with x past the max participating `x2` plus the theme
gap (`gap=` overrides). An empty column uses origin x + default widget
width + gap. Pending `ui.gap()` is cleared (it does not fatten the column
gap). `Text` is not enrolled in the widget hit/draw lists.

Widget pointer callbacks follow the Graphic rules ([Shapes Design —
Decorators](Shapes%20Design.md#decorators-scenainteraction), [Hover](Shapes%20Design.md#hover-pointer_hover-hover--hover_exit)):
only `Button` has `on_click` (`fn()` or `fn(button)`, via `call_truncated`; a
parameter with a default gets nothing — [payload rule](Shapes%20Design.md#decorators-scenainteraction);
`@click(button)` works); a value widget's `on_click` write raises and names
`@on_change(widget.data)`. Every widget has `on_hover` / `on_hover_exit` and a
read-only `pointer_hover`: a widget under the cursor is *the* hover target
(it clears Graphic hover). `WidgetManager` still tracks `mouse_over_widget`
from move events (widgets sit still in view space); `ScenaFramework._step_hover`
hands it (or the pressed widget) to the per-frame hover resolver.

Chrome (`ui.scale`, `ui.font`, `ui.min_label_space`) is construct-time.
``ui.font`` is a family name or a font file, same as ``Text.font``.
`init()` does not wipe it. `min_label_space` is the unscaled floor for a
Slider label column (default 86; theme × `ui.scale`). Consecutive omitted-y
labeled Sliders at the same stack `x` share one column width: the run uses
`max` of each widget’s needed width (measured text + pad, floored at that
min). `ui.gap()`, HUD `Text`, a widget that is not in the run (Button,
CheckBox, unlabeled Slider, a Slider placed with `top_left=`), or a stack
cursor move (`stack_reset` / `stack_origin` / `stack_from` / `stack_column`)
starts a new run. Later `.label` writes are not a layout API.

**`enabled`.** `widget.enabled = False` (or `enabled=False` on Button, CheckBox,
Slider, DropDown, TextInput) draws the widget at `theme.disabled_alpha` (one
`saveLayerAlpha` in `WidgetManager.draw`) and makes it inert: a press on it is
swallowed (the game does not get it, nor the matching up), scroll is consumed,
it cannot take focus and Tab skips it. It stays the hover target, so `on_hover`
/ `pointer_hover` still work (a "why is this off" hint), but `_is_mouse_over`
stays False (no highlight). Disabling a focused widget releases it, which
commits a TextInput and closes a DropDown. `visible = False` hides instead.
`Menu` refuses `enabled` (a disabled modal Menu would block all input). `SpriteButton` (a Sprite, not a widget) has the same `enabled` meaning — faded + gray, inert, still the hover target — through the shape manager's swallowed press ([Sprite — SpriteButton](Sprite%20Design.md#spritebutton)).

**DropDown** hangs its list below the button. When the list does not fit below
(view bottom is y = 0) and there is more room above (up to `design_height`), it
opens upward; rows keep the same top-to-bottom order and the open arrow points
down. One helper, `DropDown._list_span()`, feeds the hit test, the row lookup
and the drawing — never compute the list rectangle in a second place. Too tall
for either side, it takes the larger side and runs off screen (no scrolling;
fence).

### TextInput

`scena/uiwidget.py`. One line. `.text` is the edit buffer (a `str`), not a
graph alias; `.data` / the bound cell is the value.

- **Commit.** Enter, Tab, a click elsewhere, or disabling the box converts
  `.text` to the cell's type (`int`, `float`, else the stripped text) and writes
  it. A box whose text equals the cell's own text at focus time writes nothing:
  clicking in and out never changes a value (`0.125` stays `0.125`; floats show
  as `format(v, ".15g")`). A failed conversion leaves the cell alone, keeps the
  typed text on screen, and sets `is_valid = False` (red) until the user edits,
  presses Esc, or the cell changes. A bool cell raises at construction (use
  CheckBox).
- **Following the cell.** While not focused, the box re-reads the cell only when
  the cell's `(type, value)` changed since the last sync, so a `.text` write
  persists until then and is committed like typing on the next Enter / focus
  loss. `_on_focus_gained` checks the cell directly: `set_focus` sets
  `_has_focus` **before** the hook runs, so a "skip while focused" guard there
  would edit stale text (bug A31).
- **Esc** puts back the cell's value, clears the red state and drops focus;
  nothing is written, `on_submit` does not run. With nothing focused, Esc
  reaches the game as before.
- **`on_submit=`** `fn()` or `fn(value)` (the converted value), validated like
  `Button.on_click`, called with `call_truncated`. Enter commits, drops focus,
  then calls it — even when the text did not change; not on click-away, Esc, or
  a failed conversion; not on a linked (formula) cell. Enter always drops focus:
  a console calls `box.text = ""; box.focus()` inside the handler.
- **`focus()` / `focused`.** `focus()` gives the box the keyboard with the text
  selected. It raises `DestroyedError` on a destroyed box and `RuntimeError`
  when hidden, parked, disabled, or while a modal Menu is open.
- **Tab** (`WidgetManager.focus_next`) cycles live, enabled widgets with
  `_tab_stop` (TextInput only) in creation order; Shift+Tab goes back; it wraps;
  alone, focus stays. Focus via Tab or `focus()` selects all; a click places
  the cursor.
- **Keys** come from `_on_key(name)`; modifiers come from
  `WidgetManager._key_mods`, set by `ScenaFramework._handle_key` before any
  widget hook. Primary = Cmd on macOS, Ctrl elsewhere (A / C / X / V); word =
  Option on macOS, Ctrl elsewhere (arrows, Backspace, Del); Cmd+Left / Right
  are Home / End on macOS. Shift extends from `_anchor`. Shift+click reads the
  physical Shift key (`glfw.get_key`), not `_key_mods`. Drag extends the
  selection (left button only); double-click selects the word. Paste turns line
  breaks into spaces and drops control characters.
- **Which keys the game still gets.** `ScenaFramework._handle_key` asks
  `WidgetManager.claims_key(key, mods)` once per press / repeat; the focused
  widget answers with `_claims_key` (a pure function of key + modifiers,
  separate from acting on the key). A TextInput claims: its editing keys
  (arrows incl. Up / Down, Home / End, Backspace / Del, Enter, Tab, Esc) with
  any modifiers; every key that types text when Primary is not held (letters,
  digits, `K1`–`K12`, Space — with Shift, Option on macOS, or Windows AltGr,
  which GLFW reports as Ctrl+Alt); and Primary + A / C / X / V / Z / Y (Z / Y
  claimed as no-ops so a document undo never runs mid-edit). Everything else
  goes to `keyp` and `on_key_*` as if nothing were focused: Primary + any other
  key (Cmd+S), F1–F12, Page Up / Down, Insert. Modifier keys alone are never
  claimed — they are held-down state, so `keyp("CMD+S")` works. Before an
  unclaimed key (not a modifier alone) reaches the game, the box commits its
  pending text and keeps focus (`_before_key_leaves`), so the shortcut reads
  the committed cell; a failed conversion stays red and the key still passes.
  The rule for authors: **a key that reaches the game first applies what you
  typed** — like Enter, but focus stays and `on_submit` does not run. What the
  box shows is what the program reads. (Rejected: passing the key through
  with the text still pending plus an explicit `box.commit()` — a save
  shortcut that forgets the call writes the old value while the box shows the
  new one, silently.)
  A release goes where its press went (`WidgetManager._claimed_down`) and
  always reaches `keyp`. The decision is by modifiers because the key event
  arrives before the char event: Scena cannot know yet whether a character
  will follow. `delivers` (play key reaches `on_key` only unmodified) is read
  **after** `keys._press` — it reads the held state.
- **Clipboard** goes through `_clipboard_get` / `_clipboard_set`
  (`glfw.get/set_clipboard_string`); with no window (headless tests) they use
  a module buffer.
- **Scrolling.** Nothing is dropped: the text scrolls so the cursor stays inside
  the box (`_scroll_x`, clamped so no blank tail shows), resets to the start on
  focus loss, and drawing is clipped to the box. `_index_at_x` measures
  prefixes (kerning-correct, binary search) and adds the scroll.
- **`max_length=`** limits typing and paste (replacing a selection makes room);
  a longer value from code or the cell is shown whole.
- **`label=`** draws a caption to the left; `width` covers label + box. A
  stacked labeled TextInput joins the Slider label column
  (`_needed_label_space` / `_update_track_layout`), so labeled Sliders and
  TextInputs line up.
- **Hiding drops focus.** `visible = False` (and `enabled = False`) releases a
  focused box, committing it. Code that rebuilds a panel must not hide and
  re-show a box that stays visible — set visibility only when it changes.
- **Linked cell** (`@=` formula): read-only. Selection and copy work; typing,
  cut, paste and delete do nothing; no commit, no `on_submit`.

Fences: no multi-line, no undo inside the box, no password mask, no IME
pre-edit, no validators beyond int / float, no right-click menu.

Tests: `tests/test_text_input.py` (also `enabled` and the DropDown flip).

### Menu

`scena/menu.py`. One question, shown when it is created. It does not join the HUD column (`stack=False`). `options=` is the only required argument: a non-empty iterable, labels drawn with `str()`. The optional first argument is a bound cell (`st.nave`); the pick writes it. `on_choose(option)` runs on every pick, including the same option twice. `await menu` returns the choice, or `None` if the menu closed without one. It never raises `Cancelled`. The object does not have to be awaited. If the awaiting script is closed, the menu is destroyed with it. `menu.choice` is read-only.

On a pick, in order: the menu closes (modal mask drops; the picking button stays hidden until it goes up), `clock.paused` is restored when `pause=True`, the bound value is written, awaiters receive the choice, the menu is destroyed, then `on_choose` runs. `destroy()` without a pick completes awaiters with `None` and does not call `on_choose`. A handler error propagates only after the menu is fully closed, so another menu may be opened inside `on_choose`.

`modal=True` (the default) paints a dimmed backdrop over the game view after ordinary widgets, and it is the only pointer target. `keyp`, `mouse.press`, and `click_pos` read as not pressed; physical state still tracks, so nothing sticks. Opening it drops a shape press still held (`push_modal` → `ShapeInteractionManager._drop_press`), so the press cannot steal a release after the menu closes — [Shapes — Press lifecycle](Shapes%20Design.md#press-lifecycle-pointer_pressed). A second modal menu raises, naming the one already open. `modal=False` has no backdrop. A new non-modal menu replaces the open one; the old one closes with `None`. A modal menu may open over a non-modal one, which is then blocked like the rest of the game. `pause=True` is allowed with `modal=False`. It saves `clock.paused` and restores that saved value (it does not change `clock.scale`). Open a pause menu with `keyp.once`, not a level check: a key held across the menu does not count as a new press when it closes.

No placement: the panel sizes to the wider of the title and the option grid, plus padding, and is centered in the game view, not in the HUD column. A title longer than the options widens the panel; the grid stays centered. The title is centered in a header band — a lighter, opaque strip across the top (a light veil when `background=` is a `Gradient` or `Texture`). Title size is `menu_title_size` (default equal to `menu_font_size`). The option grid is centered in the area under that band, so the space from the header to the first option matches the space from the last option to the bottom of the panel. That inset is `menu_option_pad`. With no title, the grid is centered in the panel. `box=` keeps that centering: the header stays on the top edge and the options sit in the middle of the remaining area. `center=` is a point or a lambda link in **view** coordinates, followed every frame, then the panel is clamped fully on screen. `box=` fills that box. The font shrinks from `font_size` down to the theme minimum so the title and the options fit; below that, drawing clips to the panel and a SCENA WARNING is shown. `center=` and `box=` together raise. There is no `near=` and no `top_left=`.

`center=` does not follow the camera. A link such as `center=lambda: hero.center` is a view point. It stays on the hero only while the camera is identity. `canvas.to_view(point)` does not exist yet.

`font=` is a family name or a `.ttf` / `.otf` file, same search as images; omitted uses `ui.font`. `color=` is the label ink. The highlight is derived from `color`, else from `background` (see below); with neither it is the theme highlight. `background=` paints the panel (`Color`, `Gradient`, or `Texture`), checked at construction: an animated `ProceduralFill` (`WaterFill` …) or a non-color raises `TypeError` there, not on the first draw. A material fits the panel the way it fits a Shape host — an auto-size `Gradient` ends at the rim, `size=` is measured from the panel center, a `Texture` covers/contains/stretches to the panel and keeps its `alpha` and `shift`. It goes through `style._material_paint_for_rect`; never paint `material._skia_shader` directly (that shader sits at the view origin, so the panel shows one end stop — bug A29). Without `color=`, the highlight takes the panel tone: a solid color, `Gradient.mean_color()`, or `Texture.color`. `color=` is a color only; a `Gradient` there raises and points to `background=`. `cols=` is the grid (`1` vertical, `len(options)` horizontal). `icons=` is a list of image files, one per option, drawn above the label and scaled with the fitted font. The chosen value is still the option. A length mismatch raises. A missing file is the checkerboard plus a warning.

Fences (keep):

- No keyboard navigation, Esc, or `on_cancel`. Mouse only.
- No `canvas.to_view`.
- No submenus, scrolling, disabled items, or a dict of options.
- An option string is never treated as an image. Icons are only `icons=`.
- No `bold=` or `italic=`.

Tests: `tests/test_menu.py`. Look: `scripts/smoke/menu.py`.

Full frame order: [Scena Design.md — Datapath](Scena%20Design.md#datapath).

# Canvas and camera

## canvas.py

Defines internal `ScenaCanvas` (Skia surface, camera matrix, owns a
`Registry`), and the author-facing `Canvas` facade (design size,
background, zoom/pan/rotate / `frame_to`, and `canvas.layers`). The global
`canvas` wraps the engine.

Camera: one cached `_camera_matrix` for the world → design transform
(`_sync_camera` on mutation). `apply_camera` concats it after the view
transform. Scene draw walks layers bottom→top (compacting tombstones first);
when any layer has a
non-neutral `CameraResponse`, that layer wraps its objects in
`concat(inv(full_camera) · partial_camera(+scroll))` so each depth plane
can lag/lead pan/zoom/rotation. A layer stack with no parallax layers takes a
fast path identical to a single global CTM (`_layer_ctm_swaps == 0`).
Scroll on a parallax layer is world state: `advance_layer_scroll(clock.time)`
integrates it once per frame in the frame body, right after the clock tick
(before `update` and the process tick), and `draw` only reads the accumulated
offset. So `update` sees this frame's offset, a headless run that never draws
still scrolls, and painting twice (post FX) never double-counts. A custom frame
loop (bench harnesses) calls it after its own clock tick. Every non-neutral
layer advances, hidden or not: `visible` is paint, scroll is world state (a
hidden layer that froze would jump when shown again, and an Endless on it
would stop filling). A gap in world time is integrated in full; the run loop
already caps a frame at `MAX_FRAME_DT` (the old 1.5 s "tab resume" skip left a
layer lagging for good). A non-finite `t` is skipped. Non-finite scroll rates raise at the setter. Same-z layers are legal; among equal z, draw order is first-seen
(stable sort).
Non-neutral layers are exempt from `cull_offscreen` (bounds live under a
different matrix). Graphics with no `.visual`, no fill/line filters, and no
transients set a sticky `_plain_blit` flag and skip the effect envelope via
`_blit_plain` (Sprite: textured quad; Shape: `_geometry_draw`). Both pull
linked `angle` / `scale` PropertyAnchors first — the fast path skips
`Graphic.draw`, which is otherwise the only place that refreshes those
slots. When `cull_offscreen` is on, cull still runs for plain blits; when
off (default), the draw walk never calls `_passes_cull` (visible-only list).
`flash()` / `.visual` leave and re-enter the plain path. When
`batch_shared_filters` is on, consecutive shapes that share one interned
stroke Recipe (Laser / Neon / Ink) emit pass-major on that layer (z relaxed
only among those peers); emit buckets are kind-pure (`_world_stroke_kind`:
line / circle / path) so mixed Circle+Rect peers do not demote the world
`drawCircle` / `drawPoints` fast path. Consecutive interned ElectricField /
ElectricBolt **high** PE-glows share one overlay Plus plate.
`fx_quality="max"` keeps per-shape painter order. `Graphic.draw` skips
stamp/transient probes when those instance slots are unset. Recipe CPU/GPU
draw wins and reject list: [Effect System Design.md §5.6](Effect%20System%20Design.md#56-recipe-draw-hot-path--lessons).
Plain Shape/Sprite blit: [Sprite Design.md — Plain blit](Sprite%20Design.md#plain-blit--draw-list-compact),
[Shapes Design.md — Plain draw](Shapes%20Design.md#plain-draw-_blit_plain).

### Timed camera

Author `Canvas` mutators (`pan_to` / `pan_by` / `zoom_to` / `zoom_by` /
`rotate_to` / `rotate_by` / `set_origin` / `frame_to` / `reset_view`) take the
same pose suite as Graphic: omit `time=` → snap, return `canvas`; pass `time=`
→ tween, return a `Handle` (`ease=` / `then=` / `on_done=` / `loops=` / `yoyo=`).
`ScenaCanvas` stays instant; writers live next to the camera in `canvas.py` and
call `_start_tween`. Destinations (`about=`, `pan_to` / `pan_by` point-likes,
`frame_to` target) freeze at call time. `pan_to` / `pan_by` take two floats **or**
one point-like (`(x, y)` / Point / Vec2 / Graphic `.center` / mouse);
`about=` on `zoom_*` / `rotate_*` uses the same location grammar. `pan_by` rejects
a Point, Graphic, or mouse (those are locations — use `pan_to`). Iris
`canvas.fade_out` / `fade_in` `center=` is the same point-like, snapshotted
(omit it for the frame center). `loops=` / `yoyo=` share
the Entity pose mechanism (odd-lap `u → 1 − u`);
see [Actors Design.md](Actors%20Design.md).

Three tween channels on the one global camera (later write on a channel
cancels the earlier Handle; different channels run together):

| Channel | Occupied by |
| --- | --- |
| pan | `pan_to` / `pan_by` / `set_origin`; also zoom/rotate when `about=` is set |
| zoom | `zoom_to` / `zoom_by` |
| rotation | `rotate_to` / `rotate_by` |
| all three | `frame_to` / `reset_view` |

An act change restores the camera pose and **cancels the handle on every
channel**, whatever its owner: a camera move started from a game actor's mode
(owned by that actor, so it outlives the act) would otherwise write the camera
again on the next frame and undo the restore (review 2026-10-09 S9-5;
`act._restore_camera`, `test_act.TestActOwnsItsRegistries`).

`about=` keeps a world point glued to the same design pixel by rewriting look
each tick through the existing mutator — that **is** pan, so the Handle claims
the pan key too. `rotate_to(time=)` uses shortest arc (CCW+) and ends exactly
on the target (`canvas.rotation` reads `θ`, as after the instant form; same rule
as a shape's timed `rotate_to`, Actors Design); `rotate_by(time=)`
is signed as written. Timed `set_origin` / `reset_view` keep rest look = look
for the whole tween (`_anchor_rest`) so parallax offset stays 0. Not follow-cam:
tracking a moving actor stays in `update` / `on_update`. Compose `chase` /
`deadzone` with `canvas.pan_to` each tick — [Follow math](#follow-math-chase--deadzone).
There is no `canvas.follow`.

`frame_to(None)` holds the current view: untimed returns `canvas`; timed is an
identity Handle for the full `time=` (still claims all three camera channels, still
fires `on_done` / `then` / `await`). A collapsed `Box` (width=0 and/or height=0)
is a real frame — tight zoom, size clamped by `_MIN_ZOOM`. Wrong types still raise
`TypeError`. That is why `canvas.frame_to(group["fleet"].box, pad=…)` needs
no empty-group guard. `None` is not an author mistake here: it is the
documented "nothing to report" of `group[...].box` / `.centroid` / `.nearest`,
and raising (even only when timed) would make every `await` / `on_done` site
branch on an empty group; holding the last framing is also the right picture. `pad` is a fraction of the target on each side
(`size × (1+2p)`); negative `pad` tightens the frame (still floored by
`_MIN_ZOOM`). World-unit air is `frame_to(box.outset(n))`, not `pad=`. Negative
or non-finite frame width/height raises `ValueError`; a zero side stays legal.
Timed `frame_to(..., rotate=True)` turns the camera along the shortest arc,
same rule as `rotate_to(time=)`. `pan_*` / `zoom_*` / `rotate_*` reject
non-finite numbers at the call (`ValueError`). A finite zoom ≤ 0 still clamps
to `_MIN_ZOOM` — including mid-tween: `zoom_to(time=)` stores the clamped
value (not the raw target) so `canvas.zoom` never reads exactly `0.0`, and
the timed-camera `zoom` channel (`frame_to` / `reset_view` too) interpolates
**geometrically** (`za * (zb/za)**u`), not linearly — a bouncy/elastic `ease=`
that overshoots `u` outside `[0, 1]` cannot drive zoom negative or through
zero mid-tween (linear `za + (zb-za)*u` could). Timed `frame_to(None)` is “frame the current view,” not “pretend the call never
happened” — it still cancels in-flight pan/zoom/rotate. Do not snap-complete
(`time=0` semantics): wait the full `time=` so `await` / `on_done` / `then=` keep
their pacing. `frame_to` on a target with no `.width`/`.height` (Circle, Line,
Polygon, Text, …) falls back to `_oriented_frame()` then to
`_approx_draw_aabb()` (same geometry as draw cull) for the frame's
center/size/angle — it is not limited to Box-like `width`/`height` shapes.

Tests: `tests/test_canvas.py` (`TestFrameTo`, `TestTimedCamera`), `tests/test_easing.py`
(`chase` / `deadzone`), multi-key cancel in `tests/test_process.py`. Visual:
`scripts/smoke/camera.py` (timed); keep `world_view.py` for parallax / cull.

### Follow math (`chase` / `deadzone`)

Two small generic functions in `scena/easing.py`, exported next to `lerp` /
`remap`. Same citizen as `Graphic.confine`: stateless math — the author calls them
in `update`; they do not register, do not run later, and do not arbitrate against
camera tweens. Not camera-specific (health-bar width, zoom factor, turret aim, a
leashed pet are in scope). Point/`Vec2`/`(x, y)` coercion for `deadzone` lives in
`scenamath.py` (`_as_xy`).

| Helper | Contract |
| --- | --- |
| `chase(current, target, rate, dt=None)` | Exponential ease: `lerp(current, target, 1 - exp(-rate * dt))`. `rate` is a 1/time constant (required). Omitted `dt` uses this frame's world `clock.dt`; pass `dt=` for entity `time_scale` or a made-up step. Shape-polymorphic like `lerp` (numbers, tuples, `Vec2`, `Color`, Point → plain `(x, y)`). `dt <= 0` or `rate <= 0` returns `current` unchanged. Non-finite `rate` or `dt` raises `ValueError`. |
| `deadzone(current, target, size)` | Nudge `target` only enough to keep it within `size` of `current`. `size` is a number (square: `160` ≡ `(160, 160)`) or `(w, h)`. `float("inf")` on an axis locks it (return stays at `current` on that axis). `nan` or a negative width/height raises `ValueError` (checked on the raw `w`/`h`, not the derived half-extents — a negative size must not silently become "always inside"). Inside the box returns `current` — composing with `chase` does not oscillate at rest. Bad `size` raises `TypeError`. |

Genre rules stay inline (e.g. ignore Y while grounded). Destinations of timed
`pan_to(..., time=)` still freeze at call time — lag follow is the untimed
`pan_to(chase(...))` every tick.
Author catalog: [Guia da API](../docs/pt/guide/index.html#util-chase).

| Not taken | Why not |
| --- | --- |
| `canvas.follow(target, lag=, deadzone=)` / persistent `pan_toward` | A camera-owned per-frame process (same reject as group-scoped `every`) that would have to arbitrate the pan tween (`pan_to(time=)` / `set_origin` / `about=`) every tick. And a flat `lag=` / `deadzone=` config cannot hold the genre hatches (axis lock, ignore Y while grounded, lookahead), so it would not even replace the hand-written body. Genre hatches stay in the author’s `if`. |
| A `FollowCamera(...)` object, or camera-only variants of the helpers | Two functions, not a new concept; a camera-only signature would lose their best case (health bar, zoom factor, turret aim). |
| Upright-follow sugar (camera turns to keep a ship upright) | `canvas.rotate_to(-ship.angle, about=ship.center)` already expresses it; rarer than follow, and a spinning view can disorient the player. |

**Bar to revisit:** several taught games copy-paste the *exact same unmodified*
`deadzone` + `chase` + `pan_to` — then a still-stateless, still-explicit-per-call
`canvas.pan_toward(...)` might be worth it. Not before.

### Offscreen culling

**Offscreen culling** (`canvas.cull_offscreen`, default **on** since
2026-10-12, with the backoff below; it was opt-in). Draw-only
AABB skip against `visible_bounds` (rotated camera uses the AABB of the four
view corners — over-inclusive, never under). Pad is the largest of the filter
`_batch_outset`, the visual `_cull_outset`, and the glow `_cull_outset`, then
half the stroke **times its reach** (`_stroke_reach_factor`: 1 for smooth
closed outlines and round joins; sqrt(2) for Rect / Square miter corners and
square caps; Skia's miter limit 4 for other miter-joined outlines — a miter
tip pokes past the corner, D9 in [Testing Design](Testing%20Design.md#bug-catalogue)),
then +80 design units when the visual is multipass, then +80
when a tail is attached. The draw path then adds `transient_cull_pad`.
A larger outset does not erase the stroke or the 80s. Sprite Shield: dest AABB stays the bitmap; cull unions the costume oval only when
dest+pad would clip it (same gate as filter `saveLayer` bounds — [Effect System
Design.md §5.5](Effect%20System%20Design.md#55-changing-the-effect-system-without-regressing-hot-paths)).
Geometry prefers Defining parts (Polygon vertices, Line `_segment_xy()` —
checked before the generic `center` branch, since Line `center` is a cold
Derivate) so cull and filter-batch bounds do not wake cold Derivates (a wake
pushes the host's motion off the pose fast path for good —
[Reactive Design.md](Reactive%20Design.md)). Unknown boxes **fail-open** (keep drawing);
batching still uses a small origin hint. Tick, formulas, collision, and
SpatialFx simulation are not gated. Widgets, background fields, and canvas
post are not on this path.

**Cost, measured (2026-10-12).** The per-object test is not free: `_cull_keeps`
costs ~3.7 µs per Sprite (`_approx_draw_aabb` → `_oriented_frame` is about
half, `_filter_outset` a quarter) — about what *recording the draw* of a
plain sprite or shape costs. So culling only wins when the skipped objects are
expensive to draw. `scripts/bench/perf_cull_level.py` (camera sweep, in-process
A/B): the tutorial 21 level (4000 wide in a 1000 window, 129 drawn, 87
skipped) is **+8 %** frame work with cull on; 130 plain circles **+30 %**; the
same circles with `.glow` **−18 %**; with `Neon` −7 % (fixed-side runs — flipping
the flag every block moves GPU latency between sides, so check a GPU-heavy
A/B with `--only on|off`). The default stays off, and author text must not
call it "faster" without that condition (the Guia did, until 2026-10-12). A
cheaper test (a cached box per pose revision, nothing at all for STATIC
bodies) would move the crossover; any such change must be measured with this
bench.

**The cache (2026-10-12, B4).** `_cull_box(obj)` keeps the padded box on the
object (`_cull_cache`) keyed by its pose revision (Collision Design, "Pose
revision"), its look revision (`_look_rev`, bumped after every paint write by
the `style._refuse_on_dead` wrapper every paint property and method goes
through), and for a Sprite the sheet layout epoch.

No cache:
- an untrusted pose (links, Polygons, Lines, Text, SpatialFx);
- an active transient or a custom `_cull_pad` (they change with time and move
  the shield gate);
- a playing clip (the cell and pivot follow time).

A still body's test is then a dict read and three compares. A body that moved
since its cached key takes the plain path and is not re-cached until its
revision holds for one frame (`_cull_seen`). Without that, a mover paid a key
and a store every frame.

The draw loop reads the view edges once and compares inline. Verify mode
(`SCENA_VERIFY_POSE_REV=1`) recomputes every cached box and raises on a
difference. `_CULL_CACHE = False` is the plain path.

Measured (draw ms, `game_bench.py --cull ab`, M4):

| Scene | Cull off | Cull on, plain path | Cull on, cache |
|---|---:|---:|---:|
| 130 still circles, world 4× the window | 0.43 | 0.60 | 0.16 |
| 130 circles moving every frame | 0.41 | 0.54 | 0.57 |
| tutorial 21 level (129 objects) | 0.50 | — | 0.39 (frame −7 %) |
| mundo (1950 objects, 1820 off view) | 8.2 | — | 3.0 |

Culling pays off when much of the world is still (scenery, platforms).

**Moving bodies: the shifted box (2026-10-12; `_CULL_SHIFT`).** A body that
only moved keeps its cached box, shifted by how far its center moved.

- **"Only moved" is counted, not guessed.** The pose cell has a fifth slot,
  `moves`. A center Point the cull marked (`_pose_mover`) adds one there on
  each x / y write, in the A1 funnel (`_takein_xy_float`) and in
  `Point._takein_impl`. Every other pose write moves only the revision. When
  the revision and `moves` advanced by the same amount since the box was
  built, every change was a move of that center.
- **Marked only where a center write is a translation** (`_cull_mover`): a
  root Sprite, and the center models of Circle (`CENTER_RADIUS`), Rect /
  Square and Ellipse (`CENTER_WH`). The model is stored with the box and
  checked on use. A Circle by center and perimeter point changes its radius
  when the center moves, so it is not marked.
- **Rounding.** The shift starts from the box as built, with the total move,
  so rounding does not pile up. The result is padded out by
  `_CULL_SHIFT_EPS` (1e-6 DU). Verify mode checks that it holds the fresh
  box and stays within 4 pads of it.
- **When a body's shape changes** (turn, resize, look), it recomputes. It
  caches again after a frame whose changes were only moves.
- **Cost.** A marked body pays one more dict probe and an add per center
  write: `move_by` 1.34 → 1.39 µs. Whole games with the cull off: unchanged
  (ninja, corrida, horda, measured old vs new code in separate processes).

Draw with the cull on, shift off → on (in-process A/B):

| Game | Draw (ms) |
|---|---:|
| bolas | 0.41 → 0.33 |
| pegar_estrelas | 0.076 → 0.050 |
| naves | 0.28 → 0.26 (its 24 enemies pulse their scale: a real shape change) |
| festa | 7.9 → 6.7 (work 35.0 → 32.3; B5 reads the same boxes) |

**On by default, with a backoff (2026-10-12).** The cache and the shift made
the test cheap, but a one-screen game still paid for testing bodies that were
all in view. A layer whose cull skipped less than 1/`_CULL_BACKOFF_RATIO`
(16) of what it tested draws the next 1, 2, 4 … up to `_CULL_BACKOFF_MAX`
(32) frames without testing (`layer.__dict__["_cull_wait"]` /
`["_cull_backoff"]`; Layer guards `setattr`). A cull that skips more resets
it.
- "Less than 1/16" includes nothing at all and also a stray shot below the
  screen (naves: 1 of 29).
- The decision is a counter per layer per frame.
- It is safe whatever it decides: a frame that skips the test only draws
  more. The cost of a wrong guess is a few bodies (under 1/16) drawn off
  screen for at most 32 frames.

`_CULL_BACKOFF = False` tests every frame; the tests that count culled
bodies, and the cull-conservative differentials, run that way.

Two older gaps were fixed on the way, since a default-on cull draws every
game through them:
- **Clip cells and tilt.**
  - A Sprite's box came from `_oriented_frame`: `width` / `height` as set at
    `play()`. A clip whose cells differ in size (a mixed strip, a trimmed
    atlas) drew past it: a 91 px cell in a box sized for a 9 px one.
  - It also left out the paint tilt and seat.
  - `Sprite._draw_aabb` now maps the cell on show through the paint
    transform (cell size, trim and pivot, `offset`, flips, heading, tilt,
    seat), in float64. `_approx_draw_aabb` reads it before
    `_oriented_frame`, and the filter-batch bounds use it too.
- **Tilt writes and the cache.**
  - `tilt =` now bumps the pose revision.
  - An `"auto_ground"` tilt (it leans with the live contacts) is never
    cached.
  - A playing clip keys its cached box on the cell on show
    (`_CULL_CLIP_CELL`): an animated body reuses its box, and its shift,
    until the cell changes.

Measured, cull on vs off (in-process A/B, work ms):

| Game | Off (ms) | On (ms) |
|---|---:|---:|
| naves | 1.18 | 1.23 |
| naves_escudo | 1.60 | 1.60 |
| ninja (one screen) | 0.464 | 0.468 |
| ligue4 | 0.365 | 0.366 |
| bolas | 1.333 | 1.334 |
| pegar_estrelas | 0.264 | 0.268 |
| horda | 13.61 | 13.45 (animated enemies now cache) |
| corrida | 1.92 | 1.71 |
| tutorial 22 level | 2.83 | 2.58 |
| festa | 34.8 | 32.3 |
| mundo | 24.3 | 18.8 |

Tests:
- `tests/test_cull_cache.py`:
  - random pose and paint operations: the box used holds the computed one,
    within 4 shift pads;
  - a still body reads the cache;
  - a mover is shifted, never recomputed, near and far;
  - a turn or resize after moves recomputes;
  - a perimeter circle is not shifted;
  - canaries: a key without the look revision, and a resize counted as a
    move.
- `tests/test_cull_cache.py`, playing clips: a clip of mixed cell sizes
  keys on the cell, the box is reused while the cell holds, and a check that
  ignores the cell is caught.
- `tests/test_cull_cache.TestSpriteDrawBox`: every pixel a Sprite paints
  lies in `_draw_aabb` (mixed cells, flips, heading, tilt, scale, offset).
  The box sized at `play()` is caught.
- `tests/test_cull.py`: `TestDefault` (a fresh process reads `True`), and
  `TestBackoff` (waits 1, 2, 4 … 32 when all in view; a stray body still
  backs off; something truly off screen is tested every frame; a body
  leaving is culled within the wait).
- `tests/test_diff_draw.py`: its canary also plants the draw loop's
  `_cull_box`.

### GPU memory

Skia keeps GPU resources in its cache until a 256 MiB budget, and the driver
turns that budget into far more process memory. A look that makes a new
resource for every position (Neon's blur mask on a moving shape) filled it
with one-use masks: RSS 270 MiB → 1.3 GB in ~4 s, then a plateau (games.md
D9 / M1). The run loop now frees resources unused for `GPU_PURGE_IDLE_S`
(1 s), checked every `GPU_PURGE_EVERY_S` (0.5 s) of wall time
(`ScenaFramework._purge_idle_gpu`, after the present; 0 turns it off).
Textures drawn in the last second are never touched.

Measured (M4):
- moving Neon: 1.3 GB → 0.77 GB;
- festa: stays near 255 MiB (it grew to 877 MiB over 40 s);
- ninja, aviao_paisagem, mundo: unchanged in time and memory.

A lower `setResourceCacheLimit` was rejected: at 64 MiB festa's frame grows
~10 %, because masks are reused within a second. A shorter idle age (250 ms)
costs festa ~18 %. The remaining cost is the mask per position, and the fix
belongs in the look, not in the cache. Test: `tests/test_gpu_purge.py`
(cadence, the `timedelta` unit, headless and failing contexts).

**Draw-walk hoist (2026-09-10):** when `cull_offscreen` is False, `ScenaCanvas.draw`
builds the per-layer list from `visible` only — it does **not** call
`_passes_cull` (whose first line would `return True`). `_cull_kept` still
counts visibles; `_cull_skipped` stays 0. When the flag is True, the layer
exemptions run once per layer (`_layer_never_culled`: debug zoom, parallax,
`ui`) and `visible_bounds` once per draw; per object only `_cull_keeps(obj, vb)`
runs (AABB, pads, fail-open). `_passes_cull` is the same two steps for one
object. Optional names are probed per class (`_probe`), so an actor's ink
`__getattr__` miss (~0.5 µs each, five or six per object) is not paid. Before
2026-10-09 the per-object call recomputed the view window, ran two imports and
the layer checks: culling drew 2–3× slower than drawing everything (review
S9-10). Now: 1000 cheap rects, 865 off screen, ~1.1× the no-cull cost in the
headless raster bench (computing a Rect's AABB costs about one plain raster
blit); 1000 `Text` labels draw 2.5× faster with culling on.

Test hooks: `_cull_kept` / `_cull_skipped` (reset each `draw()`, same spirit as
`_layer_ctm_swaps`). Trade-off: false skip (popping glow) is the failure mode —
keep the default off; large worlds opt in. Residual: huge halos just off-screen
may pop; canvas Bloom of culled heroes will not bleed in. Per-layer parallax
cull (invert partial CTM) is deferred. Tests: `tests/test_cull.py`. Visual:
`scripts/smoke/world_view.py`.

When `canvas.effects` is active (or a custom `post_draw` is set), the scene
is snapshotted to an offscreen GPU RT and composed through `PostFxStack`;
the `top` layer may opt out (`set_post_fx`). An empty inactive stack is
identity (scene draws to the window framebuffer). Shared shape ImageFilters
batch by `_batch_key` into one saveLayer / low-res RT. Large sparse same-key
unions still pay a near-full-frame plate (cost tracks union AABB). Prefer
clustered fleets and canvas Bloom for atmosphere. See [Effect System Design.md](Effect%20System%20Design.md).

### Playfield leave bounds

**`canvas.playfield`** — world-fixed playfield for [`@leave_playfield`](../docs/pt/guide/index.html#reagir-bounds).
Default pad 0.25 (1.5× design rect). Negative `pad` shrinks inside the design
rect; `pad <= -0.5` collapses to a point at the design center (does not invert
edges). Not the camera frustum. `canvas.bounds` is an alias. `.inset` /
`.outset` / `.grid` / `.beside` / `.strip` return measuring [`Box`](Box%20Design.md) copies and do not
write `.pad`. Validation: a non-finite `pad` or edge raises `ValueError` at the
assignment. Edge **order** (`left <= right`, `bottom <= top`) is checked at use
(the leave step), because edges are set one at a time and may cross between two
assignments; `playfield.set(...)` checks it at the call. `set` takes one
positional `Box` (a snapshot of its edges) or the four keywords
`left=, bottom=, right=, top=`; mixing them, or a positional non-Box, raises
`TypeError` naming the keyword form, and a non-finite edge raises `ValueError`
(the keyword form used to store NaN). A camera-moves game follows the view with
one explicit line per frame, `canvas.playfield.set(canvas.game_view.outset(m))`:
the playfield stays world-fixed by design (playfield ≠ frustum), the author
chooses to move it. An enrolled item whose `center` is not a point / `(x, y)` or is non-finite
raises naming the item; a bare `Entity` (no `center`) is skipped.

**`canvas.game_view`** — world AABB of the current **view** as a fresh `Box`
(rotated camera uses the AABB of the four view corners). Placement parent for
game objects. The engine still culls against its internal frustum AABB.

**`canvas` is a formula source** (2026-10-09, RX1): the author facade is a
`Container` like `mouse` / `clock` / `keyp`. A formula that reads `canvas.zoom`
/ `pan_x` / `pan_y` / `rotation`, `canvas.game_view…` or
`canvas.layers[name].view…` registers `canvas` as its source, and the engine
notifies it (`ScenaCanvas._notify_view_changed`, from `_sync_camera` and from
the per-frame scroll advance) so the formula follows every camera move and
every scroll. The measured `Box` met in the chain is a value, never the source
(Reactive Design, Deferred trees): nothing throwaway joins the graph. Engine
readers (draw walk, cull, hit test, `screen_to_world_coords`) keep reading the
raw camera fields. Cost: an unlinked canvas has no graph node and the notify
returns after two attribute reads (A/B: `pan_to` 2.12 vs 2.11 µs); with a
dependent it is the `mark_dirty` the author asked for (+1.3 µs per camera
move).

**`canvas.ui_view`** — `[0, width] × [0, height]` in **view** units as a fresh
`Box`. HUD / `layer="ui"` / view `Text`. Camera-immune; it changes only with
the design size (`init`), so a formula on it is accepted and stays constant
through every camera move.

**Inspect overlay (Ctrl+Shift+7 / debug zoom):** gold quad = design-view /
player frustum; cyan stroke = playfield when `@leave_playfield` is enrolled.
Never the same geometry.

Class `@leave_playfield` methods: every one on the class runs (not only the
last). Top-level handlers too: every `@leave_playfield("tag")` on a tag runs,
in registration order, like `@collide`; an act's handlers leave at the act
change (decided 2026-10-09, review S4-10; before, a second top-level handler
silently replaced the first). The registry stores the **plain function** per instance and calls
`fn(item)` — never a bound method: `_instance_handlers` is a
`WeakKeyDictionary`, and a bound method as its value would hold its own key, so
the actor could never be collected (system-test finding S1). `destroy()` drops
the entry (`BoundsSystem.forget_item`).

Arguments are checked at the decorator: group names are strings only.
`ANYTHING` raises, naming the tag form and the bare class method (decided
2026-10-09): in `@collide` it means every collision participant, but here it
would mean every actor (the player, the camera target, backgrounds, `Text`),
so a `destroy()` handler would remove them too; `ui`-layer items (view space)
would need an exemption, and the step would scan every live actor. Tags or a
class method say what is watched. `group["x"]` and a class raise with the
right spelling. A handler that needs more positional arguments than it gets
(`item` / `self, item`) raises there, as `@collide` does.

Leave-playfield step runs after collision, before flush. Center vs AABB only —
not object AABB, not cull pads, not sentinel colliders. Implementation:
`scena/bounds.py`. Tests: `tests/test_leave_playfield.py`. Placement:
[Box Design.md](Box%20Design.md).


# Camera response (layers)

## camera_response.py

Shared camera-response math for **shape layers** (affine, not SkSL UV):
frozen `CameraResponse`, `partial_camera_matrix`, and `ScrollState`.
Deliberately separate from `background.py` so procedural background paths
stay untouched.


# Registry and layers

## registry.py

Registry bookkeeping split from the old monolithic layer manager:


| Piece                           | Role                                                                                                      |
| ------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `LayerStack`                    | Draw layers keyed by str name or int position; z-order (higher z on top), enable flags, `CameraResponse`, `has_parallax_layers` cache; built-ins `default` / `top` / **`ui`** |
| `Layer`                         | Draw list + frozen `response`; read-only `name` (registry key; no rename); `_is_neutral_response`; tombstone + compact (painter order). `objects` keeps a `None` hole per removal until `compact()`: count with `live_count`, never `len(objects)` (D1 in [Testing Design](Testing%20Design.md#bug-catalogue)) |
| `ParallaxLayerError`            | Raised when interactive/collidable content meets a non-neutral layer (a group's member there is skipped instead: Collision Design, S9-1) |
| `UiLayerError`                  | Raised when collision (or move-while-collidable) meets the reserved view-space **`ui`** layer             |
| `Registry`                 | Ids, groups, `register` / `unregister_draw` / `destroy`                                                   |
| `LayersFacade`                  | Author API behind `canvas.layers` (`create(..., pan_response=…)`)                                             |
| `GroupOperator` | Global `group`. Lookup is `group["name"]` (call form raises). There is no `obj("id")` ([Actors — No author ids](Actors%20Design.md#no-author-ids)); `in` / `.index` take actors, a string raises. Named-tag walks are join-order (ordered weak registry, not a raw `WeakSet`); already-a-member `add_to_group` is a no-op; re-tag after untag goes to the end. `count` / `empty` O(1) on tags, O(n) on formula groups. Formula: `group["name"] @= lambda: …` (recompute-on-read; a formula name cannot also hold tagged members). Every member walk copies at enter; queries (`any` / `filter` / `nearest` / `centroid` / `.box` / `.index` / `.first` / `.last` / `[i]` / …); bulk `destroy` / `tag`. Not a process owner. |
| `above` / `below`               | Bare helpers (`from scena import above, below`): return `require(name).z ± 1` as an `int` for `layer=`. Anchor may be str or int and must exist. `above()` raises `ValueError` when the result would sit on or above reserved `top` (`z >= 101`). `below()` does not check the floor; other invalid ints still fail at register. |


Soft remove (`unregister_draw` / `Shape.undraw`) vs hard
(`destroy` / `Shape.destroy` → `clean_up()`).

**Layer argument types.** `layer=` takes a `str`, an `int`, or `None`; anything
else raises `TypeError` (`layer=3.0` suggests `layer=3`). An unknown string name
raises `ValueError` with did-you-mean, the existing layer names, and the
`canvas.layers.create(...)` spelling.

**Numeric layers.** `layer=<int>` (not `bool`) is a separate namespace from string
names (`10` ≠ `"10"`). First use auto-creates a neutral visible layer whose
identity *is* its frozen `z` (no `.z` setter; no camera-response knobs).
`canvas.layers.create()` stays string-only (`TypeError` on an int or bool name).
`z=` must be a number (`TypeError` on a bool or a string such as `"10"`).
A blank/whitespace-only name raises `ValueError` (a `" "` name would otherwise
silently normalize to the *default* undrawn layer, `normalize_layer_name`'s
blank→`None` rule); a padded name (`" hud "`) is stripped before use, same as
lookup. `pan_response` / `zoom_response` / `rotation_response` must be finite
(`ValueError` on `nan` / `inf` — non-finite would otherwise reach the parallax
CTM math silently). Authors who need parallax, a readable name, or movable z
graduate to a named layer. Bounds match author z (`≤ MAX_LAYER_Z`).

**`Layer.name` is read-only on every layer** (named, numeric, built-in). It is
the `canvas.layers` key *and* the key each member shape caches in `_layer`
(also what `layers.default`, hit/collision layer checks and `list()` report),
so there is no rename: a write raises `AttributeError` naming the fix
(`canvas.layers.create(new, ...)` then `shape.layer = new`, then
`old.delete()`). Earlier `name` was a plain dataclass field and the write was
accepted silently — the handle said `"zz"` while the registry and every
member still said `"far"`. The same pattern applies to any handle field that
doubles as a registry key: expose it as a property whose setter raises, never
as a writable field (siblings fixed together: `Handle.name` / `.owner`, `shape.group`, interned looks, the old `Entity.id` (removed with ids: the roster now keys by a private serial) — [Testing Design](Testing%20Design.md#bug-catalogue) K1–K5). Tests: `tests/test_registry_layers.py` (`test_name_*`).

**A layer handle is a closed surface.** `visible` takes a flag (`"no"` is
refused, as on a shape), and `z` a whole number (`5.5` was drawn at 5: review
2026-10-09 S9-9). The author writes `visible`, `z`,
`post_fx` and `scroll` (the last three through their setters, which keep their
own checks; `scroll` only on a non-neutral layer, see
[Parallax layers](#parallax-layers-decoration-only)). `view` is read-only.
`Layer.__setattr__` passes dataclass fields (the private ones the stack, the
draw walk and `object.__setattr__` in `create` / `__post_init__` write) and
properties; any other name raises `AttributeError` (A34 in
[Testing Design](Testing%20Design.md#bug-catalogue)). A typo gets a did-you-mean
(`visable` → `visible`); the frozen camera-response knobs (`pan_response`,
`zoom_response`, `rotation_response`, `response`) name
`canvas.layers.create(...)`, where they are set once; a numeric layer points to a
named one. Before, `layer.scroll = (0, 0)` stored a dead attribute and did
nothing; now it is the live rate. A new internal field on `Layer` must be a dataclass field (or a
property), or the guard refuses it. `Layer` keeps its own allow-list (it is a
dataclass) but its sentence comes from the shared builder,
`scena.closed.unknown_name_message`, like every other closed surface — `canvas`,
`canvas.playfield`, `canvas.effects`, `canvas.background` and `ui` included
([Scena Design](Scena%20Design.md#entity-ink-vs-st)).

**`destroy_all()` (backing `Layer.delete(destroy_shapes=True)` / hard `Layer.clear()` /
`Registry.reset_layers()`) drains each layer to a fixed point**, not one
pass: an `on_destroy` handler that spawns a new object onto the very layer
being cleared has that new object destroyed too, in a follow-up pass. Without
this, `Layer.delete()` would immediately raise "still has objects" on the
spawn its own cleanup caused, and `reset_layers()` — which replaces
`self.layers` outright afterward — would silently orphan it (alive and
registered, but on a layer that no longer exists, so never drawn or
hit-tested again). Capped at `Registry._DESTROY_ALL_MAX_PASSES` passes;
exceeding it raises `RuntimeError` (a handler spawning forever is an author
bug, not something to hang on).

**Built-in `ui`:** view-space Graphics pass (drawn with widgets after post; skipped by `iter_draw_order` / world hit). Interactive Graphics are allowed; collision and SpatialFx are forbidden. Not a z-fight with `top` — `top` remains the uppermost *world* layer.

**Parallax-layer invariant:** a layer with a non-neutral response is
decoration only. Hit-testing and collision operate solely in world space
under the global camera; allowing interactive members on a parallax
layer would make screen position diverge from the inverse they use.
Guards live on `Entity` / interactive setters and in
`Collider` construction — the hit/collision systems themselves need no
special paths because forbidden members never register. Hover handlers
(`on_hover` / `on_hover_exit`, `@hover`) are interaction too: refused on a
parallax shape, and a shape with them cannot move into a parallax layer. A
parallax item never fires `@leave_playfield` (it moves with its layer; the
bounds step skips it, `test_parallax_layers`).


# Background engine

## background.py / background_kinds.py / `_sksl_ambient.py` / `_sksl_backdrop.py`

**Engine** (`background.py`): `BackgroundField`, `CameraSample`, `BackgroundStack`,
parallax math, wallpaper coercion. **Author kinds** (`background_kinds.py`): all
constructors (`Wallpaper`, `SkyGradient`, `Stars`, `Tunnel`, …) including kit kinds
(`ChurningClouds`, `FilamentField`) merged into one catalog. Shaders compile SkSL
**once at import** in `_sksl_ambient.py`, `_sksl_ambient_kit.py`, `_sksl_backdrop.py`;
per frame only uniforms change. Authors never write SkSL. All value-noise shaders
share the exact-lattice hash (`n = dot(floor(p), (127, 311)/1024)`, corners `n + c`),
so cells never seam on drivers that reassociate (Windows/Intel) — see
[Effect System Design §9 rule 23](Effect%20System%20Design.md#9-known-rules--gaps).

`Lattice` **(approach A — mega-shader DSL).** One RuntimeEffect covers the soft
geometric catalog. Author surface is a closed mix-and-match of enums + floats:


| Knob             | Role                                                                   |
| ---------------- | ---------------------------------------------------------------------- |
| `fold`           | `square`                                                               |
| `edge`           | `outline`                                                              |
| `color`          | motif colour (transparent field — no `bg`)                             |
| `spacing`        | pitch (center-to-center distance)                                      |
| `size`           | shape extent within cell (`1.0` = reference; max `1.7`; centers fixed) |
| `layers`         | 1–3; square/tri densify ×2 UV; hex places children on parent vertices  |
| `layer_scale`    | child layer size (`1..2`; `1` = natural)                               |
| `angle`          | in-plane rotate (degrees, CCW)                                         |
| `line` / `alpha` | edge softness / opacity                                                |


Invalid `fold`/`edge` raise at construct or setattr (`ValueError`; canonical names only — `square`/`hex`/`tri`, no `grid` alias). Continuous
knobs clamp (`layers` 1–3; `size` 0.05–1.7; `layer_scale` 1–2). Defaults make
`Lattice()` and `Lattice(fold="hex")` look good. Sugars like `Grid`/`Hexes` are intentionally **not**
provided — one concept, one class. Expanding the catalog later means editing the
shared SkSL + enum tables, not shipping N near-duplicate fields.


Background *kinds* inventory, why not a giant Shape, and stack cost:
[Effect System Design.md §3.1e](Effect%20System%20Design.md#31e-backgroundfields-scenabackgroundpy-scenabackground_kindspy).
Attachment / mutate-hide-remove: [Effect Handles.md](Effect%20Handles.md).

**Image wallpapers (decode + GPU texture).** `Wallpaper("bg.png")` loads through
`style._load_image` → process-wide `_IMAGE_CACHE` (shared with Sprite), which holds
the **lazy** `skia.Image.open` result. The GPU texture is cached by Skia under that
image's `uniqueID`, so only draws of *that same image object* reuse the decode.
`build_background_fill` (`style.py`) returns a `BackgroundFill` rebuilt per
(framebuffer size, design size, camera rest, fit knobs) key; `Wallpaper.draw` calls
`fill.fill(canvas, rect)` for the plain and the camera-CTM paths:

- **cover / contain / stretch, `tile_mode="decal"`** (the omitted default) →
  `drawImageRect` on the shared cached image (nearest sampling, same placement
  as the former DECAL shader); the letterbox underlay shows around the dst rect
  and past the image edge under a panning / zoomed-out camera.
- **cover / contain / stretch, `tile_mode` clamp / repeat / mirror** → the tile
  path below with the fit's image → dst matrix: the image continues past its
  edge, so a camera with `pan_response` / `zoom_response` never reaches the
  underlay. Linear sampling (as tile); at rest with a 1:1 fit it matches decal.
- **tile** → one **template Paint per image + mode** (`_image_template_paint`,
  identity local matrix, shader set once) copied with `skia.Paint(template)`;
  the tile matrix goes on the canvas (`concat`) and the fill rect is
  inverse-mapped. `style._uses_template` picks this path (and the matching
  prewarm draw).

`tile_mode` omitted resolves per fit, as on `Texture`: `"repeat"` for tile,
`"decal"` otherwise; `"clamp"` on tile becomes `"repeat"`. Every image fit
honours an explicit `tile_mode` — a fit that ignores it is the bug of 2026-10
(`Wallpaper("BG.png", tile_mode="mirror", pan_response=0.1)` went black once
the camera passed the image; only `fit="tile"` covered). Decal stays the
default: extending the image is the author's choice, not something the
framework adds (scale < 1 or a zoom-out would show copies nobody asked for);
the Guia tells a panning author to pass `tile_mode="mirror"`. Guard:
`tests/test_background_image.py` (`TestFittedImagePastEdge`: every fit ×
every extending mode × far pan / zoom-out / rotation leaves no underlay pixel).
`tile_size=` belongs to `fit="tile"`: with another fit it raises naming the fix
(`style._parse_tile_size`, shared with `Texture`; before 2026-10-12 it was taken
and ignored, KN4). Every image knob × fit is swept for pixels by
`tests/test_knobs_take_effect.py`.
- Gradient / solid → plain `drawRect` with the paint.

Construct **prewarms** the texture (`prewarm_background_image`: draw the same
image / template into a 1×1 GPU target). Before `run()` opens the window there is
no context, so the job is queued and `prewarm_pending_images()` runs right after
`_init_skia()`. Net: decode is paid once per file per process, at construct or at
window open — a `Wallpaper.temp(...)` built in setup and swapped in mid-game, a
swap back to an earlier wallpaper, a resize, or a camera-rest change do not
re-decode. No author knob.

Fences (keep):

- **No per-build `Paint.setShader` of an image shader** on this path. skia-python
  deep-copies the shader (serialize → deserialize) into a *new* `skia.Image`: new
  ID → GPU cache miss → the lazy PNG decodes again (~35 ms for 2669×1782); a raster
  or GPU image is PNG-re-encoded inside `setShader` (~0.8 s at that size). Same
  hazard for any image shader elsewhere — see
  [Effect System Design.md §5.5](Effect%20System%20Design.md#55-changing-the-effect-system-without-regressing-hot-paths).
- **Do not rasterize into the shared cache.** Eager `makeRasterImage()` /
  `makeTextureImage()` stored in `_IMAGE_CACHE` turns every later image-shader
  `setShader` (the tile template) into a PNG encode; `makeTextureImage()` of a lazy
  image does not populate the ID-keyed cache either. Prewarm by *drawing*.

Tests: `tests/test_background_image.py` (`TestWallpaperImageIdentity`). Bench:
`scripts/bench/perf_assets.py` (`wall_png` warm 36.5 → 0.25 ms,
[assets.md](../scripts/bench/assets.md)).

Field `pan_response` / `zoom_response` sample **look delta vs camera rest look**
(`set_origin` / `reset_view` re-anchor rest). Timed forms keep rest = look for
the whole tween. Author `scroll` on every field is independent of camera.

Tests: `tests/test_background.py`. Visual proof only: `scripts/smoke/background.py`.


# Parallax layers (decoration only)

**Shape / SpatialFx layers with a frozen** `CameraResponse` (same knob vocabulary
as BackgroundFields: `pan_response`, `zoom_response`, `rotation_response`, `scroll`).
Drawn under the camera pass with a **per-layer partial affine matrix**, not
SkSL UVs. Default response is neutral `(1, 1, 1, (0, 0))` — full camera tracking,
identical to today's single CTM.

#### Permanent invariant: no hit-test / no collision

Non-neutral layers are **decoration only**. Interactive flags (`clickable` /
`draggable` / `droppable` / `wheel_rotate`) and collision enrollment are
structurally forbidden (`ParallaxLayerError`). This is not a v1 gap — it is a
permanent architectural choice so:

- `screen_to_world_coords`, hit-testing, and the entire collision system stay
world-space under one global camera (no per-layer inverse math). The pointer
and overlay maps (`screen_to_world_coords`, `world_to_view_coords`) are float64
closed forms (`ScenaCanvas._view_to_world_xy` / `_world_to_view_xy`); the
float32 Skia inverse put the pointer 0.05 units off at x ~ 1e6 (review
2026-10-09 S9-11). The draw CTM stays float32.
- World-position vs apparent-screen-position never diverge for interactive
bodies.

Enforced at three choke points: interactive setters, `Entity.layer` move,
and `Collider.__init__` / `@collide` pre-validation (all-or-nothing).

Reactive graph / formulas are **unrestricted**: links still use plain world
coordinates; visual divergence between a parallax shape and a gameplay shape
is expected and correct.

#### Camera response (frozen at create)


| Knob                | Default  | Meaning                                                                              |
| ------------------- | -------- | ------------------------------------------------------------------------------------ |
| `pan_response`          | `1`      | Look-delta fraction (`0` = screen-locked, `1` = full, `>1` = foreground over-scroll) |
| `zoom_response`     | `1`      | Zoom lerp toward rest (`1 + (zoom−1)·zr`)                                            |
| `rotation_response` | `1`      | Fraction of camera rotation                                                          |
| `scroll`            | `(0, 0)` | Author scroll rate design units/sec (y-up); accumulated each frame. **Rate is live** (`layer.scroll`) |


Set via `canvas.layers.create(..., pan_response=…, …)`. **No live response
classification:** whether a layer is neutral is decided at create and never
changes (`CameraResponse` is a frozen dataclass; `pan_response`,
`zoom_response`, `rotation_response` stay frozen). The scroll **rate** is live,
as on backgrounds: `layer.scroll = (x, y)` on a layer created non-neutral
changes the speed from now on, with no jump (`ScrollState.rate`; `(0, 0)` stops,
`chase(layer.scroll, (0, 0), 3)` eases). Scroll counts from the layer's birth
(`ScrollState._last_t` is seeded with `clock.time` when the layer is made): the
first frame's time was lost, 75 of 100 DU when that frame was a 0.25 s hitch
(review 2026-10-09 W-T7). On a neutral layer the write raises
`ValueError` naming `canvas.layers.create(name, scroll=(…))`: a neutral layer
may hold collidable bodies and must never turn into decoration. A layer meant to
start stopped is created at running speed, then stopped — an explicit
`scroll=(0, 0)` at create stays neutral (making it non-neutral would silently
remove collision from layers already written that way). One validator for every
scroll write: `validate.scroll_rate` (pair, finite, scalar → `TypeError`).
Reserved `default` / `top` are always neutral (created via `reset_builtins`,
never via author `create` with knobs).

**How `pan_response` and `scroll` combine: they add.** A layer point `p` shows
at (zoom 1, no rotation)

```
screen = center + (p + scroll_accum) − look_eff
look_eff = rest + (look − rest) · pan_response
```

Camera motion moves the content by `−pan_response · Δlook`; scroll moves it by
`rate · t` whatever the camera does. Clouds with `pan_response=0.2,
scroll=(-20, 0)` drift 20 DU/s under a still camera, 0.2·200 + 20 = 60 DU/s
while the camera runs at 200 DU/s. The scroll offset is in layer units, so
`zoom_response` scales it on screen too; `layer.view` includes both.

| Combination | Use |
| --- | --- |
| `pan_response=0`, `scroll≠0` | screen-locked conveyor: shmup scenery under a fixed camera |
| `0 < pan_response < 1`, `scroll=0` | classic parallax |
| `0 < pan_response < 1`, `scroll≠0` | parallax plus wind |
| `pan_response=1`, `scroll≠0` | drifting fog over the gameplay (decoration only) |
| `pan_response > 1` | foreground passing faster than the world |

#### Draw path / cost

- The layer stack has **zero** non-neutral layers → `has_parallax_layers` False → draw
loop is today's code path (one cheap flag check; `_layer_ctm_swaps == 0`).
- Non-neutral layer → once per such layer: compute
`partial = partial_camera_matrix(+scroll accum)` (the scroll was advanced in the
frame tick, not here),
`concat(inv(full_camera) · partial)` around that layer's objects.
- `cull_offscreen` never culls objects on non-neutral layers (global
`visible_bounds` is wrong under a partial CTM; same policy spirit as
BackgroundFields).

Test hook: `ScenaCanvas._layer_ctm_swaps` (reset each `draw()`).

#### Layer view

`canvas.layers[name].view` → the view window in **that layer's own coordinates**,
as a fresh measured `Box` (same contract as `canvas.game_view`: a snapshot, off
the reactive graph, rotated camera → AABB of the four view corners,
over-inclusive). Read-only (a write raises naming `canvas.pan_to`). In a
formula its source is `canvas`, notified by the scroll advance as well as by
the camera, so `lambda: canvas.layers["bg"].view.left` follows the scroll.
`ScenaCanvas.layer_view(layer)`:

| Layer | `.view` |
| --- | --- |
| Neutral (`default`, `top`, author layers without knobs) | `canvas.game_view` |
| Non-neutral (parallax / scroll) | inverse of `_layer_partial_matrix(layer)` (response + scroll accum) applied to the design-view corners (`_inverse_view_aabb`, shared with `visible_bounds`) |
| `ui` | `canvas.ui_view` (by name: `ui` is camera-immune) |

Why: a parallax layer with `pan_response=0.3` shows a window that moved only 30%
as far as the camera (800-wide view, camera x 10000, rest 400 → the layer shows
x ∈ [2880, 3680]). Spawning scenery "ahead of the camera" in world coordinates
puts it where the layer will not show it for a long time; `layer.view.right`
is the right edge. Cost: one invert + four point maps per read, nothing when
unread. With scroll integrated in the frame tick, a read in `update` matches
the matrix that frame draws with. `Endless` fills against it
([Endless fill](#endless-fill)).

#### Deferred (not v1)

- Live-mutable layer response classification after create (the scroll rate is
  live; neutral ↔ parallax never changes).
- Per-shape camera response override.
- Tiling / repeat sugar for finite background art → answered by
  [Endless fill](#endless-fill) (discrete pieces, not draw copies).
- Per-layer offscreen cull: the inverse is there now (`layer_view`); culling
  parallax layers against it is not wired.

Tests: `tests/test_camera_response.py`, `tests/test_parallax_layers.py`,
`tests/test_layer_scroll_view.py` (scroll in the frame tick, `layer.view`, live
`layer.scroll`) (+ extensions in `tests/test_registry_layers.py`). Visual proof
only: `scripts/smoke/world_view.py`.


# Endless fill

`Endless(layer, pieces, *, axis="x", step=None, gap=0, start=None, seed=None,
bottom=None, left=None, group=None, height=None, width=None, size=None)` — `scena/endless.py`. Answers the Parallax
"Tiling / repeat sugar" deferral and the per-game "build the next chunk, destroy
the old one" bookkeeping of runners, flappy games and shooters.

**Model.** `Endless` manages **discrete objects placed along an axis** (or a
grid). It is not image tiling: pieces are real actors (they collide, carry
groups, animate, can be destroyed). The axis is cut into **slots**; each frame
`Endless` reads `layer.view` and builds the slots near it, ahead of the view,
and destroys slots far behind. **The tool owns *when* and *where*; the author
owns *what*.** `Wallpaper(tile)` stays the tool for repeated pixels (one image,
no spacing, no variation, nothing to collide with).

**Pieces.** An image path, a list of paths (one picked per slot from the slot
stream), or a builder `fn(slot)` returning a Graphic, a list / tuple of
Graphics, or `[]` (empty slot). `None` or a non-Graphic raises `TypeError`
naming the slot. No mixed list: variation inside a builder is
`slot.rng.choice(...)` (one spelling). The builder runs with
`canvas.layers.default` set to the Endless layer, so pieces are born there (a
piece made collidable by name on a parallax layer raises `ParallaxLayerError`
at construction, unchanged; a piece that is only a group's member, such as
`Rect(..., group="chao")` under a standing `resolve(hero, "chao")`, has no
body there and is skipped silently, Collision Design S9-1, so a hero falls
through ground built on a `pan_response=` / `scroll=` layer: the collidable
world goes on a neutral layer, tutorial 23); a returned piece the author put on another layer is
moved. `Endless` **never moves** its pieces.

**Image size.** An image piece is `Sprite(path)`, so it takes Sprite's
size: 48 units on its longer side unless `height=` / `width=` / `size=` are
given (passed to every piece and to the measuring probe, so the slot width
always equals the built width). A band of background art wants
`height=` of the screen (`Endless("montes", "montes.png", height=360)`); the
first draft of tutorial 12 got a row of 48-unit thumbnails from the bare form
(2026-10-09), and the Guia's own `predios` example had the same gap. With a
builder the three raise `TypeError` (the builder sizes its own pieces), like
`bottom=` / `group=`.

**`slot`** (`Slot`, not exported; reached only through the builder): `i` (`j`
for `"xy"`), the edges along the endless axes in **absolute** world coordinates
(layer coordinates on a parallax layer) — `left`/`right` for `"x"`,
`bottom`/`top` for `"y"`, all four plus `box` for `"xy"`; an edge the axis does
not have raises `AttributeError` with the fix. `rng` is a `random.Random`
seeded from the run seed and the index; `chance(p)` draws from it (same
validation as the global `chance`, `_chance_probability`).

*Why absolute and no shift.* Building in a local frame and shifting into place
breaks everything the builder creates with absolute coordinates: `move_to` /
`move_along` targets, `every` patrols, `@when` constants, anchored Track points.
With absolute coordinates there is nothing to shift, and slot positions never
depend on building.

**Randomness and determinism.** Slot stream = `random.Random(_mix(run_seed, i[, j]))`
— `_mix` is a splitmix64 chain over ints (tuples are not valid seeds, and
integer arithmetic gives the same stream on every Python version; values
pinned in tests). Inside a slot the engine draws first (the image pick, then
the gap draw, or the `step(slot)` width), then the builder continues the same
stream. Walking back rebuilds **the same** piece. The global `random` would
silently give a revisited slot a different piece; the Guia teaches `slot.rng`.
`seed=None` draws one run seed from the global `random` at creation (`.seed`
reports it; `random.seed(n)` makes it reproducible too).

**Positions.** Slot edges are computable without building: a fixed `step`
(`start + i·step`, no cache), a `step(slot)` function (widths drawn from each
slot's stream before the builder), or measured image extents plus gaps. The
extent of an image is measured **once per path** from a throwaway
`Sprite(path, layer=None)` (destroyed at once), so it always equals the width
of the pieces actually built (Sprite sizing has sheets, patterns and
`pixel_size`; a second sizing path would drift). Variable edges are cached per
index, filled outward from known neighbours, so a revisit lands on the same
coordinates and a long jump costs a walk over widths, never a build of each
slot in between. A `step(slot)` function must be pure (it is called more than
once per slot). Builders require `step=`: a width known only after building
would make backward fill and jumps build every slot in between.

**Fill rule.** Each process tick (the Entity's `on_update`; no new datapath
step), against `layer.view`, with `extent` the view's size on the axis:
build every slot overlapping `[near − ahead, far + ahead]`, nearest the view
centre first; destroy (release) every slot entirely outside
`[near − behind, far + behind]`. `ahead = 0.5·extent`, `behind = 1.0·extent`,
internal (no knob in v1). `"xy"`: the same per axis on cells. The first frame
is filled in the constructor. A camera moved later in the same frame (a later
actor's `on_update`, a timer) is caught by a second fill right after the process
tick (`endless.refill_after_tick`), which runs only when the view moved since the
instance's own fill: `ahead` alone did not cover a long frame (a 0.25 s hitch at
1500 DU/s left an empty strip: review 2026-10-09 W-T6).

**Thrash.** The band between the margins (half a view) is spatial hysteresis:
to rebuild the same slot repeatedly the camera must swing more than half a view
back and forth, and a rebuild costs a few constructors. No cooldown: a
time-based lifetime is not deterministic and keeps more pieces alive. The real
issue in free roaming is state (respawn) — author-keyed by `slot.i`.

**Cap.** At most `_SLOT_CAP` (256) live slots / cells per Endless (extreme
zoom-out over small slots; cells grow quadratically in `"xy"`). Filling stops
there (nearest-first, so what is on screen stays) and warns once
(`report_author_warning`). No raise mid-game.

**Ownership.** What the builder **returns** is owned: destroyed when its slot
is released, by slot position, not by where the piece is now. Graphics the
builder creates but does not return belong to the author (`@leave_playfield`,
`destroy`). A live slot keeps its key while it is inside the keep window even
when its pieces are gone: a piece the author destroyed (a collected coin,
`layer.clear()`, `@leave_playfield`) is **consumed** until its slot leaves the
window and comes back. A rebuilt slot is a fresh build: persistence is the
author's (`set` keyed by `slot.i`).

**Composability.**

- `Endless` only touches what it built; other objects on its layer are never
  moved or destroyed. Several `Endless` on one layer are independent.
- **A layer of its own.** Draw order inside a layer is creation order
  (`Registry._append_object`): pieces made during play on `default` would paint
  over the player. `default` / `top` / `ui` raise `ValueError` with
  `canvas.layers.create('pista', below='default')`.
- Collision is by group or actor, not by layer (apart from the parallax ban):
  pieces on a neutral `pista` below `default` still hit the player.
- **Lifetime.** `Endless` is an `Entity` with `layer=None`. The roster is weak
  and a one-line `Endless("pista", ...)` has no author variable and no draw
  slot, so the registry holds it strongly (`Registry.hold` / `release`, the
  `_held` set) until its teardown. `_clean_up` (reached by `destroy()` and by
  Act teardown's `registry.destroy`) releases every live slot and the hold. A
  constructor that raises (a builder error on the first fill) releases what it
  built and is never held. `active = False` freezes the fill (pieces stay).
- **Acts.** Created in an Act → torn down by `change_act`, pieces included.
  Create it, and its layer, in the Act that uses it (an act-created layer
  leaves with the act, so a restart works): a top-level `Endless` survives the change,
  but pieces it built during the Act leave with the Act and count as consumed.

**Hazard: fixed camera on a gameplay layer.** A neutral layer's window never
moves under a fixed camera, so `Endless` fills the first screen and stops. An
author with the treadmill habit then moves the pieces: they slide off screen,
their slots still count as in view, nothing new comes. The engine cannot raise
(the camera may start moving later). Mitigation: Guia gotcha, plus a one-time
warning — on a neutral layer, while the layer's view has not moved since
creation, a live owned piece farther than one view extent from its slot centre
fires *"pieces are being moved away from their slots … move the camera instead
of the pieces"*. The first time the view moves, the check switches off for
good (silent under a moving camera).

**Terrain.** Anything that must line up across slot borders is a function of
world coordinates (heights from a sum of sines, or a future seeded `noise`);
`slot.rng` is only for decisions inside the slot. Collidable ground = convex
pieces per sample (trapezoids).

**Errors** (at the call, or at the build with the slot named): reserved layer →
`ValueError`; builder without `step=` → `TypeError`; `step` and `gap` →
`TypeError`; `"xy"` without a pair step, or with `gap` / a function step →
`TypeError`; `bottom=` with `"y"` / `left=` with `"x"` → `TypeError` naming the
other; `bottom` / `left` / `group` / `height` / `width` / `size` with a builder
→ `TypeError` (the builder places, tags and sizes its own pieces; no silent
no-op); measured extent + gap ≤ 0 →
`ValueError` "Pass step="; `step(slot)` ≤ 0 / non-finite → `ValueError`,
non-number → `TypeError`; builder `None` / non-Graphic → `TypeError`.

**Why this is not `canvas.follow` again.** The `canvas.follow` reject (Follow
math) is a camera-owned process that **writes** the pan. `Endless` only **reads**
the window and never touches the camera; genre rules stay in author code (the
builder).

**The two frames (teaching model).** Every endless game has a world frame
(terrain, pipes, coins) and a screen frame (a shooter's ship, formations). The
camera decides which holds still; things in the other frame cost one carry line
per frame (`group[...].move_by`, travel drivers add up —
`test_driver_composition.TestCarry`). Camera moves (runner, platformer, flappy,
cave shooter): world things are built once at slot coordinates; `Endless` on
gameplay and decoration layers; `canvas.playfield.set(canvas.game_view.outset(m))`
per frame. Camera fixed (choreography shmup): world things carry; `Endless` on
decoration layers only (layer `scroll`, live via `layer.scroll`); gameplay
arrives by time (`every`). No "rides the camera" sugar: it would be a persistent
group-scoped driver (Actors Design reject) and the line is one call.

Rejected (v1): `repeat_x=` on layers (periodic only; `Endless` with one image
covers it), a local-frame builder plus shift, measured builders, mixed lists,
`Endless` on any layer, build cooldowns, flat random helpers on `slot`,
`Endless(flow=…)` moving its own pieces, camera-owned chunk streaming, floating
origin / `canvas.rebase` (float32 jitter only after hours of travel), a
playfield that follows the view by itself, draw-copy tiling of a parallax layer.

Tests: `tests/test_endless.py` (fill / seams / hysteresis / revisit / seeds /
`step(slot)` / images / ownership / cap / drift / Acts / GC / parallax, scroll
and `"xy"` long runs). Visual proof only: `scripts/smoke/endless.py`.

