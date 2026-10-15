# Box Design

Measuring regions for placement. **`Rect` draws. `Box` only measures.** Happy
path for this subsystem — pick one row. Hub:
[Scena Design.md](Scena%20Design.md). Camera / playfield:
[Canvas Design.md](Canvas%20Design.md). Shape models:
[Shapes Design.md](Shapes%20Design.md). Author catalog:
[Guia da API](../docs/pt/guide/index.html#colocar).

Today’s baseline — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Constructors / inset / outset / grid / beside / strip | [Surface](#surface) |
| Too-small inset / grid (line / point) / `is_collapsed` | [Remainder](#remainder) |
| `outset` (grow twin) | [Surface](#surface), [Remainder](#remainder) |
| `box=` fill vs inscribe | [Fit](#fit) |
| `game_view` / `ui_view` / `playfield` | [Parents](#parents) |
| `graphic.box` | [Bridge](#bridge) |
| `group[...].box` | [Bridge](#bridge) |
| `graphic.confine` | [Confine](#confine) |
| Not an Entity | [Architecture](#architecture) |
| Rejected alternatives (why not) | [Not taken](#not-taken) |
| Locating code | [Router](#router) |

## Use

1. Pick one jump-box row.
2. Read that section only. Treat fences there as current constraints.
3. Open **Start** in the router if the section is not enough.
4. Stop.

## Router

| Need | Start | Also | Design (if needed) |
| --- | --- | --- | --- |
| `Box` / `Grid` / `box=` | `box.py` | `shapes.py`, `sprite.py`, `text.py` | this file |
| Too-small inset / grid / `is_collapsed` | `box.py` (`inset`, `outset`, `Grid.__init__`, `is_collapsed`) | `sprite.py`, `text.py` | this file, [Remainder](#remainder) |
| `canvas.game_view` / `ui_view` | `canvas.py` | `box.py` | this file, [Canvas Design.md](Canvas%20Design.md) |
| `canvas.playfield` / `@leave_playfield` | `bounds.py` | `canvas.py` | [Canvas Design.md](Canvas%20Design.md) |
| `graphic.box` | `entity.py` (`Graphic.box`) | `box.py` (`box_from_graphic`) | this file |
| `group[...].box` | `registry.py` (`GroupOperator.box`) | `box.py` | this file, [Canvas Design.md](Canvas%20Design.md#timed-camera) |
| `graphic.confine` | `confine.py` | `entity.py` (`Graphic.confine`), `box.py` | this file, [Confine](#confine) |
| Outline vs a Box | `geom.py` | `box.py` (`_oriented_frame`) | [Shapes Design.md](Shapes%20Design.md) |

**Do not slurp:** `box.py`, `shapes.py`, `canvas.py`.

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `Box` | a `Container` that measures | a `Rect` / `Shape` / `Entity` |
| `canvas.game_view` | window in **world** (fresh `Box`) | playfield / HUD |
| `canvas.ui_view` | window in **view** (fresh `Box`) | world frustum |
| `canvas.playfield` | mutable leave-area config | a `Box` (`.inset` / `.outset` / `.grid` / `.beside` / `.strip` return copies) |
| `box.outset(n)` | world-unit larger copy | `frame_to(pad=)` / `playfield.pad` (fraction) or `confine(by="overlap")` |
| `box.strip(side, t)` | fixed-thickness band **inside** one edge | `beside` (outside) or `grid(1, n)` (fractional cells) |
| `box.beside(side, …)` | neighbor **outside** one edge | `strip` (inside) or AABB corner math |
| `frame_to(..., pad=)` | fraction of the framed target | `box.outset(n)` (design units) |
| `canvas.bounds` | alias of `playfield` | layout parent |
| `graphic.box` | snapshot of a frame-like Graphic | a live link; not on `Line` / free `Polygon` |
| `group[...].box` | fresh AABB snapshot (`None` if empty) | a live link; not `graphic.box`; there is no `.bounds` tuple |
| `graphic.confine` | synchronous pose math helper | `@leave_playfield` / `resolve()` / a registration |
| `Ellipse(from_rect=…)` | live pose link to a **Rect** | `box=` (one-shot fit) |
| `@click` on a region | click a **Graphic**, or `grid.cell_at` | `@click` / `on_click` on `Box` |
| `g[col, row]` | reserved TypeError | `.cell(col, row)` |
| `ui.gap()` | extra HUD-column gap | a measuring `Box` |
| `ui.stack_column()` | next HUD column, same visual top | `ui.stack_origin(x, y)` |

## Not in this doc

- Camera timed verbs / cull frustum math → [Canvas Design.md](Canvas%20Design.md)
- Rect models / CTM draw → [Shapes Design.md](Shapes%20Design.md)
- Sprite body / hitbox → [Sprite Design.md](Sprite%20Design.md)
- Author catalogs → [Guia da API](../docs/pt/guide/index.html#colocar)


# Surface

```python
zone = Box(center=(400, 300), width=800, height=200)
inner = zone.inset(24)
halo = zone.outset(24)
fleet = inner.grid(8, 3, gap=16)          # or gap=(gx, gy)
cell = fleet.cell(0, 0)                   # col, row — row 0 is the top edge
wasp = Sprite(box=cell, height=40)
hit = fleet.cell_at(mouse.x, mouse.y)     # None in a gap or outside
hud = zone.strip("top", 40)               # inside band
sidebar = zone.beside("right", width=120) # outside neighbor
```

Same geometry constructors as `Rect` (`CENTER_WH`, `TOP_LEFT_WH`,
`CORNER_CORNER`, `POINT_VEC`, `SPINE` + `anchor=`). **No empty `Box()`.** No
`color` / `layer` / `group`. No four positionals (`Box(100, 100, 500, 300)`
raises). `Box(graphic)` / `Box.from_graphic(graphic)` is the same snapshot as
`graphic.box`.

**A Box is a Rect that does not draw: named points and sides follow Rect's
rule** ([Shapes Design — Named
points](Shapes%20Design.md#named-points)). A box names its corners the first
time one is used (a named point, or a layout verb below), as they look then;
from then on `top_left` / `top_center` / … and the sides `"top"` / `"left"` /
… stay with their points. Every Box made from something else keeps its
names: layout children (`inset` / `outset` / `strip` / `beside` / grid
cells), `Box(some_box)`, and `graphic.box` / `Box(graphic)` (a flipped Sprite
/ Svg / Ellipse / Text included — `box.region_name_signs`). A board built on
`board.box.grid(8, 8)` keeps cell (0, 0) on the same square through turns
and flips; a fleet slot `leader.box.beside("right")` stays on the leader's
right when it flips. `left` / `bottom` / `right` / `top` are the
screen-aligned bounds and never follow names — the way to ask "above it on
screen".

Layout verbs:

- **`inset(margin)`** — uniform shrink. Returns a new `Box`. Each axis clamps
  to `>= 0` (line or point — [Remainder](#remainder)). Negative margin raises.
  Air around a stamp is `box=region.inset(n)`, not constructor `padding=`.
- **`outset(margin)`** — uniform grow. Returns a new `Box`. Same center and
  angle. Negative margin raises. `outset(0)` is a same-size new object. A
  collapsed source (line / point) gains interior. Twin of `inset` — not
  `frame_to(pad=)` / `playfield.pad` (those are fractions).
- **`grid(cols, rows, gap=0)`** — divide the box. `gap` is space *between*
  cells (`n` or `(gx, gy)`). Default `0`. Unsatisfiable gap → zero-size cells,
  same placement math (may sit outside the parent).
- **`strip(side, thickness)`** — fixed-thickness band flush to one **inside**
  named edge (`"left"` / `"right"` / `"top"` / `"bottom"`). Full span on the
  long axis. Overshoot clamps to the source extent (full-axis band) —
  [Remainder](#remainder). Negative thickness / unknown side raise. Not
  `beside` (outside) and not `grid(1, n)` (fractional cells).
- **`beside(side, *, width=None, height=None, gap=0)`** — new box flush
  **outside** one named edge. Omitted sizes inherit; both omitted → same
  size. `gap` is air between edges. Negative size / gap / unknown side raise.
  Collapsed sources are legal. Opposite of `strip`.
- **`contains_point`** — hit geometry. No `@click` on Box. Zero-area boxes
  have no interior (`False`).
- **`is_collapsed`** — `True` when at least one oriented extent is `0`
  (line or point — [Remainder](#remainder)). Same predicate as no-interior /
  `contains_point` False. Read-only; silent (no warning).

`Grid` is a multi-mode accessor, not a container:

| Call | Meaning |
| --- | --- |
| `for cell in g` | row 0 first (the named top edge — the visual top unless the corners crossed), named left → right |
| `g.cell(col, row)` | col-major, matches `(x, y)` |
| `g.cell(n)` | flat: `col = n % col_count`, `row = n // col_count` |
| `g.rows` / `g.cols` | lists of lists |
| `g.row_count` / `g.col_count` | counts (not `.rows` / `.cols`) |
| `g.cell_at(x, y)` | reverse lookup; **oriented** (inverse-transform first); `None` in a gap |
| `cell.col_index` / `cell.row_index` | ints on cells; `None` on a freestanding `Box(...)` |
| `g[col, row]` | TypeError: use `.cell` |

No parent-grid back-reference on a cell. Neighbor: `g.cell(cell.col_index + 1, cell.row_index)`.

Oriented boxes keep `angle`. A grid over a rotated zone stamps rotated cells;
`cell_at` works in that local frame.

Cells tile the Box: in order, `gap` apart, none outside, none overlapping; `cell_at`
agrees with the placement (`test_box.TestGridCoversBoxProperty`). Placement and
lookup are separate code, so a point exactly on a cell edge may resolve one ulp
either way.


# Remainder

Insufficient space is a remainder, not an error. No warning. Negative margin /
gap and `cols`/`rows` `< 1` still raise.

`inset(m)` per axis: `max(0, size - 2m)`. Same center and angle.
`outset(m)` per axis: `size + 2m` — never a remainder. A collapsed box is a
legal *source*: outset gives it interior. `outset(m).inset(m)` always recovers;
`inset(m).outset(m)` recovers only when inset did not clamp.
`strip(side, t)` clamps thickness to the source extent on that axis and pins
the center as a filled band when overshooting — same silent remainder spirit.

| Remainder | What it is | `.is_collapsed` |
| --- | --- | --- |
| both axes `> 0` | normal inner box | `False` |
| one axis `0` | **line** (spine through the center) | `True` |
| both `0` | **point** (a pin) | `True` |

`.is_collapsed` is `True` when **at least one** oriented extent is `0` — the
same rule as “no interior” for `contains_point` / `cell_at`. Authors who need
the pin specifically still write `width == 0 and height == 0`. Graphics born
from `box=` into a remainder may be invisible; they expose the same property
(see [Shapes Design.md](Shapes%20Design.md), [Sprite Design.md](Sprite%20Design.md)).

`inset(4)` on `59.2×3.84` → `51.2×0`. `inset(12)` on `20×20` → `0×0`. Nested
air (`cell.inset(pad)` after a grid) is the same verb.

`grid`: `cell_w = max(0, usable_w / cols)` (same for height). Do not squeeze
the author’s gap. A `0×0` parent with `gap=0` is `cols×rows` coincident point
cells at that center; indices still work. Address degenerate cells by index —
`cell_at` misses zero-area cells.

`box=` into a remainder never raises: fill/inscribe may be invisible; Sprite
contain is size `0` at the center; explicit `height=` / `radius=` still pins.
`Text(box=)` on a zero-width region is a content-sized pin (does not pass
`width=0`).


# Fit

`box=` is its own constructor family. Mixing with other geo kwargs (`center=`,
`width=` on a fill shape, …) raises. Compatible Graphics only — not `Line`,
free `Polygon`, `Track`, `Point`.

| Kind | `box=` alone | with explicit size |
| --- | --- | --- |
| `Rect` / `Ellipse` | **fill** the region (pose + size + rotation) | mix raises |
| `Circle` / `Square` / regular N-gon | **inscribe** (min side; Circle does not take the region angle) | **center only** (`radius=` / `length=` / `side=`) |
| `Triangle` | **contain**: the largest triangle of its `base_ratio`, outline centered, apex along the region's +x (inherits the region angle) | **center only** (`radius=` / `side=`; the centroid on the region center) |
| `Sprite` / `Svg` | uniform **contain** (keep pixel aspect; inherit region angle) | **center only** (`height=` / `width=` / `size=`; no inherited angle) |
| `Text` | `center = region.center` (layer `ui` unless `layer=`), `width=region.width` if omitted (a zero-width region: the box follows the string), default `align="center"`; not in the HUD column | mix with `center=` / `top_left=` / `top_center=` / `top_right=` raises |

Breathing room: `Graphic(box=cell.inset(8))`. No constructor `padding=` on this
path. Zero-size region: fill/inscribe are invisible; Sprite contain is size
`0`; explicit size still pins. No warning.


# Parents

Three objects, two types:

| Parent | Space | Type | Job |
| --- | --- | --- | --- |
| `canvas.game_view` | **world** (camera frustum) | fresh **`Box`** each read | Place ships, formations, “top of the screen” |
| `canvas.ui_view` | **view** (`[0, W] × [0, H]`) | fresh **`Box`** each read | HUD / `layer="ui"` / view `Text` |
| `canvas.playfield` | **world**, often larger | **`Playfield`** (mutable) | `@leave_playfield`; `.inset` / `.outset` / `.grid` / `.beside` / `.strip` return `Box` copies and never write `.pad` |

`canvas.bounds` is an alias of `playfield`. Prefer the new name. There is no
`canvas.center`, no `canvas.screen` / `canvas.view`.

World Boxes carved at setup stay put as the camera pans — usually a feature for
formations. Re-read `game_view` in `update` if the layout must follow the
frustum. `Point(canvas.game_view.center)` is the same kind of snapshot (copy at
construct time — follow with `Point(lambda: canvas.game_view.center)` or `@=`).
HUD must not feed world `game_view` into view / `ui` after pan;
`ui_view` is camera-immune.

Cull still uses the engine frustum AABB internally — not the author
`canvas.game_view` object.


# Bridge

`graphic.box` on **Rect, Square, Ellipse, Circle, Sprite, Svg, Text** returns a fresh
measuring `Box` (Circle → the diameter square turned to its rim point `p1`). Snapshot: move the Graphic, read
again, get a new Box. Unsupported types raise `TypeError` (not
`AttributeError`). Layout verbs live on that Box (`panel.box.inset(8).grid(8, 8)`,
`panel.box.outset(12)`), not on Shape. For a Sprite, `.box` is the **drawn frame**
rectangle where it is really drawn — pivot, `offset`, flips and `scale`
applied (`Sprite._oriented_frame`) — not a silhouette fit. `sprite.center` is
the **pivot**, not the middle of the drawing: with `Sheet(anchor="bottom")`
the box sits *on* the pivot. Building the box around `center` (and from the
`width` / `height` size knob) put it half a height low and ignored `scale`
(G9, `tests/test_sprite_measure.py`). Do not measure a Sprite from `center`
+ `width` / `height`. The box angle is the heading (`angle`, `180 − θ`
after a flip): the same region as the drawn angle, and the frame its names
are read in. For **Text**, `.box` is the layout box (`width=` or
the string) re-laid-out for the string showing now, scaled and turned about
`center`. A HUD widget is not a Graphic, but `widget.box` is the same kind of
snapshot: its view-space rectangle (`ui.stack_origin(slider.box.top_right + (16, 0))`).

**Measured boxes are lazy.** `graphic.box`, `Box(graphic)` / `Box(box)`,
layout children (`inset` / `outset` / `strip` / `beside`) and grid cells are
`Box._snapshot`s: the center stays two floats until `center` is read or
written (`_SnapshotCenterSlot`); scalars, edges, derived corners and layout
verbs answer from `_oriented_frame`. A full center Point (a Shape part) cost
~60 µs, so `sprite.box.width` went from ~75 µs to ~12 µs. Same Box, same
model (`CENTER_WH`), same answers — `tests/test_box_snapshot.py` compares
every read and verb against an eager Box and guards that a measurement builds
no Point. Author `Box(center=…, …)` is unchanged.

A measured Box also **stays off the reactive graph until something links into
it** ([Reactive Design — Deferred trees](Reactive%20Design.md#deferred-trees-measured-boxes)).
A point read (`graphic.box.top_left`) builds a Point part, but no graph node:
a Box and its parts are a reference cycle, so registered parts left the graph
only at a full cyclic GC, and a point read every frame climbed the node count
until the leak detector warned (D11 in Testing Design). Writes re-derive
eagerly; a link from or into the Box (`dot @= b.top_right`,
`b["width"] @= …`) wires the whole tree first. The engine's other fresh
measurements are the same kind of Box — `canvas.game_view` / `ui_view`,
`group[...].box`, a HUD `widget.box` and playfield layout copies are built
with `Box._from_aabb` (same answers as `Box(p1=, p2=)` for an ordered AABB).
Do not build a per-read measurement with `Box(p1=, p2=)`: that is an author
Box, and it registers. `tests/test_box_snapshot.py` counts graph nodes over
repeated point reads of every measured Box with the cyclic GC off.

`.box` copies the Graphic's frame **with its names**: `rect.box.top_right` is
`rect.top_right`, and a flipped sprite's `box.top_center` is still over its
head (it used to land at its feet — G7). For the screen, read the
screen-aligned edges: `(sprite.box.center.x, sprite.box.top)`.

`group["wasp"].box` is the same measurement, as a `Box`: a fresh axis-aligned
snapshot of live members (the Box's own angle is always 0), or `None` if the
group is empty or none of the members expose measurable geometry. Per member
this delegates to `canvas._approx_draw_aabb` — the **same** geometry draw/cull
use (`_domain_aabb`, `_oriented_frame`, vertices, `p1`/`p2`, `center`+`radius`
or `center`+`width`+`height`) — falling back to a degenerate point at
`.center`/`.x,.y` only when that returns nothing (`.centroid` / `.nearest`
keep the simpler `.center`-or-`.x,.y` rule; they do not need extent). This
means Sprite scale/rotation, Polygon vertices, and Text/SpatialFx extent are
measured correctly (a second, independently-maintained AABB routine here had
drifted: it ignored Sprite `.scale` entirely and collapsed Polygon/Text to a
single point, so `frame_to(group.box)` cropped a scaled sprite and zoomed to
~`_MIN_ZOOM` on a framed Polygon/Text group — see `tests/test_registry_layers.py`
`test_group_box_accounts_for_scale` / `test_group_box_polygon_and_text_not_a_point`).
Rotated width/height members contribute their oriented AABB, not the
unrotated frame. A single member (or all coincident) is a legal collapsed Box
(`width` and/or `height` 0) — not an error. Safe to pass to `canvas.frame_to`
every frame — `None` holds the view (see [Canvas Design.md — Timed
camera](Canvas%20Design.md#timed-camera)). Snapshot per read, matching
`game_view` / `ui_view` / `graphic.box` — **not** a live link that tracks
membership. There is no `group[...].bounds` tuple form.


# Confine

Stateless pose helper on Graphic. Call after your own `move_by` (same phase).
The correction it writes reaches collision like the public verbs' writes: a
clamp or bounce joins the frame's pending motion, so the sweep ends where the
body stopped (it kept the full `move_by` sweep and fired a ghost `@collide`
behind the wall: review 2026-10-09 S7-4); a wrap is a placement (no sweep
across the field).
Any `Box` or frame-like Graphic as `region` — **any angle** (math runs in the
region's local frame, same pattern as `inset` / `grid` / `beside` / `strip` /
`contains_point`).

```python
sides = ship.confine(play_area)                       # by="center", action="clamp"
sides = enemy.confine(platform, by="box")             # own .box stays inside
sides = ball.confine(arena, action="bounce")          # needs ball.vel
sides = ship.confine(canvas.game_view, action="wrap")
if "left" in sides:
    canvas.shake(2)
```

| Knob | Values | Meaning |
| --- | --- | --- |
| `by=` | `"center"` (default) | Check `self.center` only |
| | `"box"` | Shrink region by self's projected half-extents — self's `.box` stays fully inside. Too-big object → remainder pin at region center (not an error) |
| | `"overlap"` | Grow region by those half-extents — act only once self's `.box` has **fully left** |
| `action=` | `"clamp"` (default) | Stop the checked reference at the effective edge |
| | `"bounce"` | Clamp + flip `self.vel` along the crossed **local** axis. Requires `self.vel` set |
| | `"wrap"` | Teleport to the opposite edge, carrying overshoot |

Returns a `frozenset` of region-**local** edges acted on this call
(`"left"` / `"right"` / `"top"` / `"bottom"`), or empty if nothing happened.
A rotated region's `"left"` is its own local left — same orientation contract as
`Grid` / `Box`.

**A Sprite with a sheet anchor** (`Sheet(anchor="bottom")`, an atlas pivot,
`clip(offset=)`): `center` is the pivot (the feet), not the middle of the
drawing. `by="center"` checks that pivot; `"box"` / `"overlap"` measure the
drawn `.box` about its own middle; either way the correction moves the pivot
by the same amount (the pose writer places `center`). Before 2026-10-09 the
drawn middle was written back as the pivot, so every clamp lifted an anchored
sprite by half its height, a frame at a time (a ninja walking into the screen
edge climbed to the top; tutorial 18). Guard: `tests/test_confine.py`
`TestAnchoredSprite`. The pose point is read from the class
(`type(g)._move_to_xy`), so a shape pays one type lookup.

`by="box"` / `by="overlap"` on a Graphic with no `.box` (`Line`, free `Polygon`,
`Track`, `Point`) raises the same `TypeError` as `graphic.box`.

**Not** a registration, **not** a datapath step, **not** collision. Do not drive
the same axis with a tween / `move_along` / `resolve()` wall and `confine` —
those are separate authorities over pose with no defined precedence. Cleanup
when something *leaves* the world stays `@leave_playfield` (notify), not
`confine` (hold in). Implementation: `scena/confine.py`. Tests:
`tests/test_confine.py`. Visual: `scripts/smoke/confine.py`.


# Architecture

Option **(d)**: `Box` is a `Container` with Rect’s geometric core (constructors,
corners, angle, links, `_oriented_frame`). It is **not** a `Rect` / `Shape` /
`Entity`. No draw, layer, paint, or registration. `isinstance(box, Entity)`
is false. Grid cells are ordinary Boxes with `col_index` / `row_index` set.

Why not the other three:

| Option | Why not |
| --- | --- |
| (a) independent AABB-only `Box` with its own narrower vocabulary | A second dialect next to `Rect`; orientation, links and `intersections` would be a retrofit, and it drifts from Rect's constructors. |
| (b) no `Box`; an invisible `Rect` as the probe | An Entity in disguise: `set_color` on a probe, an Entity (and its cost) per grid cell. |
| (c) `Box(Rect)` subclass that never draws | Same Entity baggage by inheritance; `isinstance(box, Rect)` lies (Liskov). |

A Box (and a `Grid`) is a closed surface ([Scena Design](Scena%20Design.md#entity-ink-vs-st)): `box.widht = 3` raises with a did-you-mean, and a read-only name is suggested too (`box.topp` → `top`). The measured boxes `Box._snapshot` builds through `__new__` (`graphic.box`, `canvas.game_view`, grid cells) call `scena.closed.seal()` at the end, and fill their own fields with one `__dict__` update. The guard cannot see a write to a real name on a throwaway snapshot (`canvas.game_view.width = 5` changes a copy) — a separate issue.

`geom.py` treats Box like an oriented rect for `intersections` / `closest_point`.
Playfield stays the special mutable animal in `bounds.py`. `rotate_to` /
`rotate_by` `about=` takes a point-like (tuple, Point, Vec2, Graphic `.center`,
mouse), same as Shape, snapshotted. Default pivot is the box center.

# Deferred

Do not re-open without a smoke that the named surface cannot express:

- Per-side / per-axis `inset` (uniform first; authored `Box(center=…, width=…, height=…)` covers unusual bands when `strip` is not enough)
- Live `box=` / `graphic.box` that tracks pose or the camera (v1 is a fresh snapshot each read; opt-in `@=` on Box parts remains the escape)
- 9-point `align` / `place` — `grid(3, 3)` already covers corner cells
- Chess-file `.cell("a1")` sugar
- Thin `pad=` on the `box=` path (air is `box=region.inset(n)`)
- Real `Grid.__getitem__` (`g[col, row]` stays a reserved TypeError until `.cell` / `.rows` / `.cell(n)` are the only door authors know)
- Neighbor sugar on Grid that does not store a parent on the cell

# Not taken

Rejected outright (not deferred). Re-open only with a smoke the current
surface cannot express.

| Idea | Why not |
| --- | --- |
| Public `canvas.rect` (the engine's `canvas_rect`) as "the screen" | A live Shape whose writes do not resize the window, and after `set_origin("center")` it is not the screen. Measuring reads return a fresh `Box`. |
| `canvas.center` / `canvas.top_left` / … beside `width` / `height` | Ambiguous after `set_origin` (design centre or the world point under the window centre?). Corners live on the box: `game_view.center`, `ui_view.center`. |
| `canvas.screen` / bare `view` / `abs_view` aliases | "screen" or "view" alone invites the wrong half of the pair. One parallel pair, `game_view` / `ui_view`, no synonyms. |
| Fold `playfield` into `game_view`, or make `Playfield` a `Box` | Playfield is padded, world-fixed and mutable (`.pad`, `.set`); the frustum moves with the camera. One class cannot be both a mutable singleton and a copy-on-op value, so its layout verbs return `Box` copies. |
| `canvas.playfield.set(...)` to define a layout region | It moves the `@leave_playfield` edges. A layout region is `Box(...)`. |
| `game_view` / `ui_view` / `graphic.box` as their own duck types | Two vocabularies again; being a snapshot is *when* the value was made, not a different type. |
| Layout helpers that return undrawn `Rect`s | A snapshot wearing a Shape costume; it looks linkable but follows nothing. |
| `Box(100, 100, 500, 300)` | Corners or `x, y, w, h`? Beginners guess wrong. Keywords only. |
| Empty `Box()` | Empty `Rect()` means "draw a medium rectangle"; an empty measuring region means nothing. |
| `b.top(80)` / bare `left()` as band methods | `.top` / `.left` are edge scalars and stay so. |
| `place(align, w, h)` / 9-point `align` / corner sides on `beside` | A mini layout engine with nine strings. Corners are `grid(3, 3)` cells or an authored `Box`. |
| `beside` spelled `at_left` / `at_top` | Reads as "the top *of* me" (inside) and collides with the edge scalars. |
| Four methods `to_left` / `to_right` / … | Runner-up; one verb plus a side string matches `confine`. |
| A default `strip` thickness | A band without thickness is not a region (unlike `beside()`, which can copy the size). |
| `inset` / `grid` directly on `Rect` / Shape | Blurs "Rect draws, Box measures"; `panel.box` is the on-ramp. |
| `.box` (or `box=`) on every Graphic, one silent AABB | `Line` (AABB or spine?), free `Polygon` (AABB or OBB?), `Point` have no honest frame. Frame-like Graphics only. |
| A cached, mutable `graphic.box` identity | It goes stale while looking live. Each read is a fresh Box. |
| `group[...].bounds` tuple kept beside `group[...].box` | Two accessors for one measurement; `box.width` reads better than `bounds[2] - bounds[0]`. A cheap tuple only for groups would be an inconsistency — the fix for per-read cost is a cheaper Box everywhere (the lazy `_from_aabb` snapshot, [Bridge](#bridge)). |
| A live `group[...].box` that tracks membership | Same snapshot rule as `game_view` / `ui_view` / `graphic.box`; no exception for groups. |
| Constructor `padding=` beside `inset` | A third name next to widget padding and `gap`; air is `box=region.inset(n)`. |
| Stretch a Sprite / Circle to fill a non-square cell | Breaks aspect. Inscribe / contain, or `height=` to pin. |
| `.rows` / `.cols` as counts | Bare plurals read as collections; counts are `.row_count` / `.col_count`. |
| Cell belonging as `cell.col` / `cell.row` | Too close to `g.cols` / `g.rows`; `col_index` / `row_index`. |
| A parent-Grid reference on each cell | Lifetime and equality footgun; the author already holds `g`. |
| `@click(box)` / click enrollment on `Box` | Re-opens Entity, hit-test and z-order; clicks stay on Graphics, `cell_at` covers the board. |

`strip` and `beside` themselves were once held back as "a 1×N grid is a
strip". They landed because the units differ: `grid(1, 8).cell(0, 0)` is the
top *eighth*, not "80 tall", and an outside neighbour by AABB corner math
(`Box(top_left=(panel.right, panel.top), …)`) breaks once `angle ≠ 0`. Both
are local-frame edge math: `beside` puts the new centre `(w + nw) / 2 + gap`
out along the named axis, `strip` puts it `(h − t) / 2` in (with `t` clamped
to the extent).
