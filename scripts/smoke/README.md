# Smoke tests

Visual / behavioural proof. One primary question per script. **No `--bench`.**

## Shared UI

Chrome comes only from [`_hud.py`](_hud.py) (top of the window):

| Line | Role |
|------|------|
| title | Suite + current item |
| expect | What “pass” looks like |
| keys | Controls |
| status | Live feedback |
| aux | Optional 2nd live line (e.g. clock) |

Framework FPS / objs stays at **bottom-left** — never put Text below `SAFE_BOTTOM` (48).

### Navigation

| Key | Meaning |
|-----|---------|
| Arrows | Pan camera / move something on screen |
| Shift+← / → | Rotate camera |
| Shift+↑ / ↓ | Zoom in / out |
| A / S | Previous / next **primary** (mode, page, focus, effect) |
| Q / W | Previous / next **secondary**, or paired −/+ (e.g. clock scale) |
| E | Cycle FX quality (when relevant) |
| SPACE | Pause **or** clear/baseline (stated in keys) |

Do **not** use `[` / `]` or bare ←/→ for catalog cycling.

Keep `background.py` and `world_view.py` **separate**: fields catalog vs camera / parallax / cull.

## Coverage

| Script | Question |
|--------|----------|
| `shape_catalog.py` | Every shape family + constructor models (A/S pages): Line, Circle, Ellipse, Rect, Square / RegularPolygon, Triangle (`base_ratio` static + live, `box=`), Concave (every `scoop=`, `rim`), Track (models + presets), Polygon |
| `shape_class.py` | Shape class defaults, home fill, subclass `clone()` (A/S) |
| `shape_fx.py` | Shape looks + canvas post (A/S · Q/W) |
| `sprite_fx.py` | Sprite looks, atlas clips, flip / class defaults, hitbox kinds, Svg file reload |
| `level_sheets.py` | A level file's image items in every form — whole `file`, a sheet cut by `cols` × `rows`, by `cell`, by `atlas` — made with `item.make()`: each fills its box, each drawn number = its label, the status checks center / size / angle / frame against `level_sheets.json` (open it in the editor to compare); SPACE plays a clip registered on `level.sheet("grade")` |
| `hitbox.py` | Auto-hitbox overlays (A/S pages) |
| `hitbox_round2.py` | Hitbox parts round 2: `px_rect` / `px_circle` follow the drawing, where the pixel numbers come from, `sprite.showing()`, linked `hb["active"] @=` attack box, plain `.active` i-frames (A/S pages, Z slow motion) |
| `transients.py` | Life mutex + hit channels (A/S effect; H = HitStack) |
| `background.py` | Wallpaper + ambient + fly fields (A/S · arrows pan) |
| `camera.py` | Timed camera: `time=` pan/zoom/rotate/frame/`about=` / channels (A/S · SPACE replay) |
| `world_view.py` | Camera, parallax layers, cull (A/S · arrows pan) |
| `endless.py` | `Endless` fills what the camera sees: runner (camera moves), fixed camera + live `layer.scroll`, `"xy"` grid (A/S · SPACE · Q/W · arrows) |
| `spatial.py` | Every SpatialFx + param sliders + probe |
| `interact.py` | Click / drag / drop / z-order |
| `hover.py` | Hover: one per-frame target, `@hover` / `@hover_exit` edges (balanced counter), every way out under a still cursor, the still-cursor trade-off + camera pan, hover-only click transparency, `@click` shared by Shape + Button, widget / modal / `ui`-layer exclusivity (A/S pages) |
| `collide.py` | group-pool vs named pairs + shape×sprite×shape; Track arc/ring stroke walls |
| `contact.py` | `info.point` VFX placement (burst / marker at hit) |
| `colliders.py` | Hitbox outlines vs rotate / scale / atlas-frame size; Track.arc stroke tube |
| `geom.py` | Same-color outline crossings (dots) + cyan chord + `closest_point` bead |
| `geometry.py` | Geometry contract: pins linked to named points stay on them (Rect p1/p2 crossing, flips as true mirrors vs an unflipped twin, `angle` = heading on every kind, `angle =` keeps the placement point (`rotation` is retired and raises), scale pivots and the two scale models, Circle rim points + `.box`, Text parts = drawn frame / no flips / linked anchor refuses, Track `reversed()` views share the host pose, clones keep pose, edge cases); live ✓/✗ checks on the aux line (A/S pages) |
| `box.py` | `Box` / `Grid` / `box=` / `graphic.box` / `game_view`·`ui_view`·`playfield` (A/S pages) |
| `smoke-process.py` | Scheduler, modes, async, `active`, clock, author-error keep-alive |
| `mistakes.py` | Construct mistakes: checker vs `TypeError` Text (A/S families) |
| `nearest.py` | Standalone `nearest` + `group.nearest` + `within=` + vertex snap (A/S) |
| `ledge_probe.py` | Patrol turns at ledges, two ways side by side: `floor_below(dx=)` vs a hidden `Rect` linked with `@=` + `collides_with(group=)` (tile join, 10 DU steps, 12 DU gap, 40°/30° ramps, wall, cliff; A/S floor_below depth · Q/W sensor depth · C probes · V sensors · SPACE restart) |
| `queries.py` | `query_point` / `query_circle` / `query_shape` / `query_sector` / `raycast` (A/S · SPACE pauses the sweep) |
| `group_formula.py` | Formula groups `@=` (union / filter / nested / frozen); SPACE/Q spawn, W kill, U unlink |
| `ui_layer.py` | Reserved `ui` view layer vs world; fail buttons for forbidden features |
| `text.py` | `Text` paint catalog + ui/world placement, `align=` / `width=` (+ Glow) |
| `UI and reactive.py` | Widgets + `@=` / `@when` / unlink; TextInput `label=` / `max_length=` / `on_submit` console / Tab / N → `focus()` / Esc, keys that pass while typing (Cmd/Ctrl+S, F5); `enabled=False` controls; DropDown opening upward near the bottom |
| `mix.py` | Author-style mix: widgets, shapes, sprites, camera, bg/post, transients, SpatialFx, `@=`; click `save_visual` / `restore_visual` overlay |
| `tracks.py` | `Track` presets, `move_along` (orbit / phase / zigzag / Anchor-linked), `begin`/`end` draw window, Track-as-Shape `ElectricBolt`, `show_tracks` overlay (SPACE) |
| `tracks_collide.py` | Many `move_along` riders + track/free obstacles; `resolve(..., bounce=1)` everywhere |
| `audio.py` | `play_sound` + master bus + fades + FFT bars + effects (human listen) |
| `audio_mic.py` | `Microphone` monitor + bars (needs a real mic / OS permission) |
| `audio_record.py` | Record a dry clip, play it back with live effects or `bake` (needs a real mic / OS permission) |

```bash
python scripts/smoke/shape_fx.py
python scripts/smoke/spatial.py
python scripts/smoke/mix.py
```
