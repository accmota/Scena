# Shapes Design

Multi-model geometry, geometric transforms, and how drawing relates to the
reactive graph. **Happy path for this subsystem** — pick one row; do not read
the rest. Registry identity (`Entity`, internal `Graphic`) lives in `entity.py`;
`shapes.py` re-exports them and hosts `_publish_graphic_api()`. Hub:
[Scena Design.md](Scena%20Design.md). Pull graph:
[Reactive Design.md](Reactive%20Design.md). Author calls:
[Guia da API](../docs/pt/guide/index.html#desenhar-shapes).

Today’s baseline, not a freeze — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Status / which shape has models | [Status](#status) |
| Defining vs Derivate / CTM | [Defining vs Derivate](#defining-vs-derivate-multi-model), [Lazy Derivates](#lazy-derivates-and-ctm-draw) |
| Plain draw (no visual) | [Plain draw](#plain-draw-_blit_plain) |
| Per-shape models | [Point](#point) … [RegularPolygon](#regularpolygon--equilateraltriangle), [Track](#track) |
| Which point is `top_right` (names vs points, flips) | [Named points](#named-points) |
| What every kind / verb must satisfy | [Geometry contract](#geometry-contract) |
| Transforms / clone | [Transform API](#transform-api-shape) |
| Pointer / hit-test | [Pointer interaction](#pointer-interaction-click--drag--drop); press state: [Press lifecycle](#press-lifecycle-pointer_pressed) |
| Outline crossings | [Geometry queries](#geometry-queries) |
| Measuring `Box` / `box=` | [Box Design.md](Box%20Design.md) |

## Use

1. Pick one jump-box row.
2. Read that section only (search; do not read the rest of this file). Treat fences there as current constraints.
3. Open **Start** only if the section is not enough.
4. Open **Also** / another Design doc only if Start is not enough.
5. Stop. Do not ingest `scripts/`, other companions, or the private archive / proposals.

## Router

| Need | Start | Also |
| --- | --- | --- |
| `Circle` / models / Graphic draw API | `shapes.py` | `entity.py` (`Graphic` ABC) |
| `Track` / `move_along` | `track.py` | `curves.py`, `process.py` |
| Outline crossings | `geom.py` | — |
| `Box` / `box=` / `graphic.box` | `box.py` | [Box Design.md](Box%20Design.md) |
| `@click` / `@drag_*` | `interaction.py` | `input.py` |

**Do not slurp:** `shapes.py`.

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| Graphic pose API | published from `shapes.py` | defined on `Graphic` in `entity.py` |
| Outline crossing | `geom.py` | collision contact (`collision.py`) |
| `isinstance(x, Shape)` | geometric models | Sprite / Svg / Text |

## Not in this doc

- Pull graph / takein / A1–A3 → [Reactive Design.md](Reactive%20Design.md)
- Collision pipeline → [Collision Design.md](Collision%20Design.md)
- Sprite body / hitbox → [Sprite Design.md](Sprite%20Design.md)
- `Track` / `move_along` → [Tracks Design.md](Tracks%20Design.md)
- Author catalogs → [Guia da API](../docs/pt/guide/index.html#desenhar-shapes)
- Measuring `Box` / `box=` / `game_view` → [Box Design.md](Box%20Design.md)


# Status
========

| Shape | ContainerSlot + models | Geometric move / rotate / scale | Draw |
|-------|------------------------|----------------------------------|------|
| **Point** | yes (`x`,`y`) | yes | handle glyph when `visible` |
| **Line** | yes (multi-model, incl. 5 cross-shape relational models) | yes | world `p1`→`p2` |
| **Rect** | yes (multi-model; lazy Derivate corners/mids/end-squares) | yes | CTM local frame |
| **Square** | yes (`Rect` subclass; `length` Defining, `width`/`height` Derivate) | yes | CTM (inherited) |
| **Circle** | yes (multi-model, optional arc window) | yes | world center/radius |
| **Ellipse** | yes (multi-model) | yes | CTM local frame |
| **Polygon** | yes (dynamic-arity Defining vertices) | yes | world vertices |
| **RegularPolygon** | yes (dynamic-arity Derivate vertices, multi-model) | yes | CTM local frame |
| **EquilateralTriangle** | yes (`RegularPolygon` subclass, `n=3`) | yes | CTM (inherited) |
| **Track** | yes (`FREE` / `CIRCLE` / `SHAPE`; `center`, `u`, `begin`/`end`; `length`/`cursor` Derivate) | yes (`move_along` on every Graphic) | local polyline + CTM pose; invisible by default; `begin`/`end` stroke window (draw + hit-test + collision); stroke-tube collision; Rect/Square outline honors `corner_radius` |
| **Anchor** | `Point` sugar (`handle=True`, always free pose) | yes | hover ring when pressable |

All shapes are **geometric-first** for *canonical* geometry: transforms write Defining parts; `_update_impl` refreshes **live** Derivate world Attributes (linked or accessed); cold Derivate slots stay unregistered until needed. `draw` may paint from the local frame via Skia CTM (`translate`/`rotate`/`drawRect` or a local-path n-gon) so painting does not force world corners/vertices hot — the same pose as `_oriented_frame()` / `_apply_oriented_corners`. Ellipse pioneered the pattern; Rect/Square/RegularPolygon follow it. Line/Circle/Polygon still draw from the Attributes they need for paint (endpoints, disk, free vertices).

**Reactive `angle` / `scale`:** `shape["angle"] @=` and `shape["scale"] @=` are linkable on every Graphic. Where `angle` is a model input (`Rect` / `Ellipse` / `Square` / `RegularPolygon` / `EquilateralTriangle` / `Line` / `Circle`), it is the primitive geometry `ScalarSlot` (same mechanics as `width` / `center`: the placement point stays). Elsewhere (`Point`, `Sprite`, `Svg`, `Text`, `Track`, free `Polygon`, derived headings, and `scale` on every class) writes go through `rotate_to` / `scale_to` via `_PropertyAnchor` — those kinds are placed by their center (an anchored `Text` by its anchor). Other pivots stay imperative (`rotate_to(θ, about=…)`). `wheel_rotate=True` still raises `LinkedAttributeError` **synchronously at `@=`**. A derived heading and a linked part it rewrites are exclusive the same way: `line["angle"] @=` on a `p1,p2` Line raises at the `@=` when `p1` or `p2` is linked, and linking `p1` afterwards raises (`_heading_driven_parts`, D17). Linked ink and models where `angle` is an input are not affected. See [Reactive Design.md](Reactive%20Design.md).


# Architecture
==============

```
Shape(Entity, ABC, PaintState)
├── Entity          # layer / groups / collidable (shared with SpatialFx)
├── PaintState          # stroke / fill / filters
├── Container           # parts, links, FieldType, update
└── transform API       # move_*, rotate_*, scale_* (subclass implements geometry)
```

Parts are declared with `ContainerSlot`. Multi-model shapes call `_set_defining_parts(...)` in each constructor path so FieldTypes and structural edges match the active model.

```
Defining parts  →  Shape._update_impl  →  live Derivate world parts  →  links / queries
                      ↓
                 CTM draw from local frame (Defining pose; corners stay lazy)
```


# Defining vs Derivate (multi-model)
====================================

`ContainerSlot(..., FieldType.Derivate)` on the class is only the **initial default** when the part is first created. For multi-model shapes the **constructor** (via `_set_defining_parts`) is the source of truth.

Recommended pattern:

1. Declare flip-prone parts as Derivate by default (safe until the model is chosen).
2. In every constructor path, set `self.model` and call `_set_defining_parts(...)`.
3. `_set_defining_parts` stores `_defining_part_names` and only rewires **already materialized** parts — cold Derivate names stay unregistered until first access or link. **Never `getattr` Derivate names here** — that materializes them, flags `_needs_pull_invalidate`, and defeats the unlinked pose fast path (A2). See [Reactive Design.md](Reactive%20Design.md) (Difficult / bug-prone areas).
4. `_takein` / `_move_*` / `rotate_*` / `scale_*` only write **Defining** inputs; Derivate parts are written only inside `_update_impl`, and only when live. Unlinked center-model shapes may use A1 absolute fast paths (`_requires_pull_invalidate()` false) — see [Reactive Design.md](Reactive%20Design.md) (Pose performance A1–A3).

Class-level Derivate still matters for parts that never flip (e.g. `Line.center`, `Rect.top_right`) as the default when a slot is first created without a defining-set override.

A subclass can **narrow** a parent's model by forcing a part that's Defining-capable on the parent to always be Derivate on the child (see `Square` and `RegularPolygon`/`EquilateralTriangle` below) — this is how the design resolves the classic "is-a" size/shape LSP issue: the child adds its own Defining part (`length`, or a fixed `n`) and mirrors it into the parent's Derivate outputs inside an overridden `_update_impl`, reusing the parent's corner/vertex math unchanged.


# Lazy Derivates and CTM draw
=============================

## Liveness

A Derivate part is **live** when `_derivate_live` is set (first access via `ContainerSlot`) or when it has external graph dependents (formula/`@=` source — maintained on link install/unlink). `_update_impl` helpers (e.g. `_takein_live_derivate`, `_apply_oriented_corners`) skip unregistered and cold parts. Under pull reactivity, `_update_impl` runs when a dirty Derivate root is read (or when an effect / linked consumer pulls it).

First access calls `_materialize_derivate_part(name)` (shape-specific) so `print(rect.right_center)` is correct without having kept that midpoint hot on every prior frame.

## Draw vs Attributes

| Role | Source of truth |
|------|-----------------|
| Links, queries, `print(part)` | World Attributes (Defining + live Derivates) |
| Pixels for local-frame shapes | Defining pose → CTM (`_oriented_frame` / equivalent) |

CTM is a **presentation** of the same local frame `_update_impl` would use for corners — not a second stored pose. Linking `Line(p1=lambda: rect.right_center)` still materializes and refreshes that Point every cycle.

## Plain draw (`_blit_plain`)

When a Shape has no `.visual`, no fill/line ImageFilter, and no active transient,
the sticky `_plain_blit` flag is True and the canvas draw walk calls
`Shape._blit_plain` instead of `Graphic.draw`:

1. `_pull_property_anchors()` — linked `angle` / `scale` PropertyAnchors
2. `_geometry_draw` — same CTM / paint path as the full envelope’s body

Pixel-identical to `draw` with all ceremony probes false. Sprite has its own
`_blit_plain` (textured quad). Shared contract and pitfalls:
[Sprite Design.md — Plain blit](Sprite%20Design.md#plain-blit--draw-list-compact).
Scene walk: [Canvas Design.md](Canvas%20Design.md). Bench gate:
`scripts/bench/perf_shape_draw.py --suite --no-sweep-quality` (plain `draw_ms`
down; Laser / Neon / Ink / Electric* flat).


# Construction: copy vs link
============================

Construction rule: **bare values copy, callables link** (per component for a
2-tuple). A Point or part passed as a value is a snapshot of its current
position — wrap it in a lambda to follow it:

```python
Line(p1=rect.top_left, p2=c1.center)            # copies today's points
Line(p1=lambda: rect.top_left, p2=c1.center)    # p1 follows the rect
Rect(top_left=(10, 20), width=100, height=50)   # scalars taken in
Rect(top_left=(lambda: p.x, 20), width=100, height=50)  # x links, y copies
Text("Menu", top_left=lambda: panel.top_left)   # same rule for Text anchors
```

Signatures are matched with `_CONSTRUCTOR_SIGNATURES` + `_extract_common_params_and_signature`.
A multi-model Shape constructor is legal in **exactly three** forms:

1. **Empty** — `Circle()`, `Rect()`, `Line()`, … Default pose at the design-space center.
2. **`center=` only** — place that default (optionals may tag along; see clarifications).
3. **Exact signature** — every required key of one constructor path. Includes **home minus
   `center`** when that remainder is complete: `Circle(radius=)`, `Rect(width=, height=)`,
   `Square(length=)`, `Line(length=, angle=)`.

Anything else raises `ValueError` naming the started path and missing keys. Unknown or
wrong-family keywords raise `TypeError`. Non-signature flags (`use_center`,
`corner_radius`) and required disambiguators that are part of a signature key set
(`side` on Line, `anchor` on Rect SPINE) never affect home-fill eligibility when listed
in `_CTOR_EXTRA_KEYS` (Circle `angle` / `spread` included); `anchor` is a required signature key, not an extra.

**Not legal** (do not invent missing size / endpoints): `Line(p1=…)`, `Rect(center=…, width=…)`,
`Rect(width=40)`, `Line(center=…, length=…)`, `Circle(p1=…)`.

### Clarifications

1. **Optionals do not kick you out of “center only.”** Rect/Ellipse/Square/RegularPolygon
   `angle`; Circle `angle` / `spread` (either may be given alone); RegularPolygon `n`; flags
   `use_center` / `corner_radius`. So `Rect(center=, angle=45)` fills width **and** height
   together. Line’s home does **not** treat `angle` as optional: `length` and `angle` are a
   pair (one requires the other).
2. **“Minus center” applies only to the home signature.** Do not subtract `center` from
   every model that happens to include it (`Circle(perimeter_point=)` stays incomplete).
   Expert paths stay exact (`Rect(top_left=)` needs `width`+`height`; `Line(p1=)` needs the
   rest of that signature).
3. **Class defaults fill before the completeness check.** `class Brick(Rect, width=90,
   height=36)` then `Brick(width=180)` is legal (class supplies `height`). Bare
   `Rect(width=180)` raises. Size defaults apply on the **home** path only
   (`Shot(p1=…, p2=…)` does not inject class `radius=` / Line `length=`).

## Empty constructors (visible defaults)

Empty / `center=` / complete home-minus-center fill from class size defaults, then
`_default_pose()` (`Circle()`, `Circle(radius=50)`, `Circle(center=(x, y))`,
`Rect(width=, height=)`, `Line(center=…)`, `Line(length=, angle=)`).
Unknown or wrong-family keywords (`Circle(aaa=1)`, `Rect(radius=5)`, `Circle(frame=…)`)
raise ``TypeError`` with a family hint — same fail-loud rule as Sprite. Incomplete expert
paths (`Circle(p1=…)`, `Line(p2=…)`, `Rect(p1=…, width=…)`, `Line(p1=…)`) raise ``ValueError``.
Per-class extras stay legal (`use_center` on Circle, `corner_radius` on Rect, `n` on RegularPolygon).
Constructors are **keyword-only**: a positional value (`Circle(10)`, `Rect(10, 20)`,
`Line((0, 0), (1, 1))`, `Polygon([...])`) raises `TypeError` with a keyword example
(`_reject_positional_shape_args`) — before, `*args` was accepted and silently dropped.
The shape's `@overload`s must not reintroduce a positional slot.
`anchor` on Rect SPINE and `side` on Line `TANGENT_POINT` are required signature keys, not extras.

**Class style / size defaults** (Sprite-like): `class Bolt(Circle, radius=8, color="gold", group="bolt")`.
Allowed: `color`, `visual`, `group`, plus that class’s home **size** keys (`radius` on Circle;
`width`/`height`/`angle` on Rect/Ellipse; `length`/`angle` on Square and `length`/`angle` on Line;
`radius`/`angle`/`n` on RegularPolygon). **Not** placement (`center` / `layer`).
Style/group apply on every path; size defaults apply on the home path only (so
`Shot(p1=…, p2=…)` keeps diameter geometry and does not inject class `radius=`).

Every drawable multi-model shape accepts `ShapeName()` with no geometry kwargs. That path picks the simplest free model and builds a **visible**, medium-sized shape at the **design-space center** (not a degenerate zero-extent object).

**Collapsed geometry** (zero extent after construct or parametric size) is legal and **silent** — no warning / HUD. Read `.is_collapsed` (`True` when there is no interior): Rect/Square via oriented frame (`w == 0 or h == 0`); Ellipse either axis `0`; Circle / RegularPolygon `radius == 0`; Line `length == 0`. Point, free Polygon, and Track stay `False` (intentionally dimensionless ≠ collapsed). Same name and rule on `Box` — [Box Design.md — Remainder](Box%20Design.md#remainder). Empty constructors above still build a medium **non-collapsed** shape.

Size comes from `_default_pose()`: `unit = 0.06 * min(design_width, design_height)` (≈72 on the default 2000×1200 canvas).

| Call | Model | Geometry |
|------|--------|----------|
| `Line()` / `Line(center=…)` / `Line(length=, angle=)` | `CENTER_LENGTH_ANGLE` | horizontal unless `angle=`; length `2*unit` unless given; through / at center |
| `Circle()` / `Circle(center=…)` / `Circle(radius=…)` | `CENTER_RADIUS` | radius `unit` unless given; center = canvas center unless given |
| `Rect()` / `Rect(center=…)` / `Rect(width=, height=)` | `CENTER_WH` | `2*unit` × `1.25*unit` unless both given |
| `Square()` / `Square(center=…)` / `Square(length=…)` | `CENTER_LENGTH` | length `1.5*unit` unless given |
| `Ellipse()` / `Ellipse(center=…)` / `Ellipse(width=, height=)` | `CENTER_WH` | same extents as default `Rect` |
| `Polygon()` | free vertices | irregular quad (centroid at center) |
| `RegularPolygon()` / `(n=k)` / `(center=…)` / `(radius=…)` | `CENTER_RADIUS` | hexagon if `n` omitted; radius `unit` unless given |
| `EquilateralTriangle()` | `CENTER_RADIUS` | radius `unit` |
| `Track()` | `FREE` eight (same as `Track.eight()`) | lemniscate; **invisible**; `closed=True`; floating |

`Point()` stays at `(0, 0)` (undrawn by default). Placement is **not** offset from the last shape — several empties overlap until the author moves them.


# Cross-shape relational constructors
=====================================

Some models build a shape whose Defining parts are formula-linked to *another*, already-existing shape (not a value copied at construction time) — e.g. `Line`'s `PARALLEL_POINT` / `PARALLEL_DIST` / `PERPENDICULAR_POINT` / `TANGENT_ANGLE` / `TANGENT_POINT`, or `Ellipse`'s `FROM_RECT`. Pattern:

- Store the foreign shape in a private, non-reactive field (e.g. `self._ref`), plus any disambiguating plain value (`self._tangent_side`, a fixed `padding` float captured in a closure).
- Wire Defining parts with `self.<part> @= (lambda: ...)`, **not** `self.<part>.assign_formula(lambda: ...)` — see the gotcha below.
- Add module-level helpers (`_parallel_offset_point`, `_circle_point_at_angle`, `_circle_tangent_touch_point`, …) for the geometry so the lambda body stays a one-liner.

## Pose verbs on a relational shape

A pose verb either keeps the relation or refuses (`LinkedAttributeError`, nothing changed); it never ignores an argument. `force=True` frees the shape first (`_drop_relational`) and the verb runs on its free twin. Graphics review SB1 / SB4 / SA16; pinned by `test_shapes.TestRelationalVerbs` and the shape-specific tests.

| Model | `move_*` | `rotate_*` / `angle =` | `scale_*` | flip |
| --- | --- | --- | --- | --- |
| `PARALLEL_POINT` / `PERPENDICULAR_POINT` | moves `p1` | refuses (the heading follows the reference) | about any pivot | refuses |
| `PARALLEL_DIST` | across the reference: the move's normal component goes to `dist`, the along-track part is dropped (documented, `test_move_by_adjusts_dist`) | refuses | refuses | refuses |
| `TANGENT_ANGLE` | refuses (`force=True` frees it) | orbits the circle's center (the default pivot; `about=` must be that center) | the length, about the pinned touch point (`about=` must be that point) | refuses |
| `TANGENT_POINT` | refuses (moving the from-point re-solves the tangent: not a rigid move) | orbits the circle's center, as above | refuses | refuses |
| `FROM_RECT` (Ellipse) | refuses (every input follows the Rect) | refuses | refuses | refuses |

`angle` and the pose heading read the same value on every model (`TANGENT_ANGLE`: `at_angle + 90`, `Line._rotation_value`; SB4: they read 290 and -70, so `rotate_to(line.angle)` added a full turn). The contract sweeps skip exactly these documented meanings (`geometry_support.CONTRACT_EXEMPT`, each with its reason) and hold every other verb to rigid motion.

## Gotcha: `@=` vs `assign_formula(lambda: ...)` for internal wiring

`FormulaLink._extract_sources` locates the exact `ast.Lambda` for the callable (by line/column when several share a statement). It also treats default-arg captures (`lambda h=host: …`) and simple subscripts (`items[0].radius`) as sources. User-facing constructor kwargs (`Circle(center=lambda: …, radius=lambda: …)`) go through `_init_composite` / `_init_scalar` and are safe with multiple lambdas on one line.

**A constructor validates only concrete values, and never rewrites an input it has stored.** A check that calls `float()` / `get_xy()` on the raw kwarg rejects a lambda with Python's message, and a later `_takein` that "normalizes" `p1` cannot run on a link — so a plain value and a lambda of that value would build different shapes. Use `_concrete_float` / `_concrete_xy` (links return `None` and skip the check) and leave the store to `_init_scalar` / `_init_composite`. Guard: `tests/test_ctor_links.py`.

For **in-`__init__` model-relation wiring** written as `self.<part>.assign_formula(lambda: …)` on the same line as the receiver, prefer `self.<part> @= (lambda: …)` anyway — keeps the statement shape clear and matches the rest of the relational constructors. The historical footgun (AST walking the whole line and treating `self.p1` as a source) is fixed by exact-lambda matching; the `@=` spelling remains the house style for internal formula wiring.


# Point
=======

- Parts: Defining `x`, `y`.
- Constructors:
  - `Point(x, y)` — beginner scalars (`Point(3)` → `(3, 0)`; `Point()` → `(0, 0)`).
  - `Point(point_like)` — **copy** from Point / Vec2 / `(x, y)` / Graphic (via
    `.center`) / mouse-like (`.x`/`.y`). Same family as `distance` / `heading`.
    Snapshot, not a live link — `Point(canvas.game_view.center)` pins the
    frustum center at construct time.
  - `Point(lambda: …)` — whole-point formula (callable must return a
    point-like); same as `Circle(center=lambda: …)`. Link one axis with two
    args: `Point(lambda: mouse.x, 0)`. A 2-tuple of mixed callables/values
    (`Point((lambda: src.x, 10))`) still goes through `_init_composite`
    per-component.
  - `takein` / `center @=` / `Circle(center=lambda: …)` / `move_to` / `about=` /
    `Contrail.stamp` / `closest_point` use that same family. The `mouse`
    singleton stands in for a Point. `Circle(center=lambda: mouse)` and
    `center @= mouse` follow the pointer. `Circle(center=mouse)`, `Point(mouse)`,
    `move_to(mouse)`, and `stamp(mouse)` snapshot (script body is still `(0, 0)`
    before the window). A whole Graphic works the same way (`lambda: player`
    reads `.center`). `move_by` / `pan_by` reject mouse — those are deltas.
- `center` property aliases `self` (for `set_center` / default pivot).
- Default: `layer=None`, `visible=False` (off the draw list).
- `color=` → `set_color` + show as a **guide** (visible, not a handle), unless
  `visible=False` is also passed. No `visual=` (markers are fill-only dots).
  Constructor `line_width=` is rejected for the same reason: the glyph radius
  is fixed and the hover ring is `StrokeWidth=1.0`. `.line_width` stays a property.
- `visible=True` → promote to layer `top` (save/restore prior layer on hide).
- `handle=True` → visible + draggable (Point-facing name for the grab role;
  uses the same `_draggable` flag as `Shape.draggable`).
- Marker draw / hover ring reuse former Anchor visuals.
- `rotate_*` / `scale_*` move the point about `about` (default: self → no-op for position).
  The heading still turns: `rotate_by(a)` about itself adds `a` to `angle`, as
  `rotate_to` sets it (raycast's default `angle` reads it). Bug G1.
- Arithmetic uses `Point.temp` under `ephemeral_creation` (never linked, not on canvas).
- `shape.show_handles()` / `no_handles()` bulk-opt free Defining Points.
- `shape.show_points()` / `hide_points()` — debug: all Point parts (incl. Derivates);
  materializes cold Derivates while shown; hide releases liveness if unused.


# Line
======

## Models

| Model | Defining | Typical constructor |
|-------|----------|---------------------|
| `CENTER_LENGTH_ANGLE` | `center`, `angle`, `length` | `Line()` / `Line(center=…)` / `Line(length=, angle=)` / full |
| `POINT_POINT` | `p1`, `p2` | `Line(p1=…, p2=…)` (scalar `x1=`…`y2=` raise with a hint: points only) |
| `POINT_VEC` | `p1`, `vec` | `Line(p1=…, vec=…)` |
| `POINT_DX_DY` | `p1`, `dx`, `dy` | `Line(p1=…, dx=…, dy=…)` |
| `POINT_ANGLE_LENGTH` | `p1`, `angle`, `length` | `Line(p1=…, angle=…, length=…)` |
| `PARALLEL_POINT` | `p1`, `angle` (linked to `parallel_to.angle`), `length` | `Line(p1=…, parallel_to=other, length=…)` — direction tracks `other.angle` |
| `PERPENDICULAR_POINT` | `p1`, `angle` (linked to `parallel_to.angle + 90`), `length` | `Line(p1=…, perpendicular_to=other, length=…)` |
| `PARALLEL_DIST` | `dist`, `angle`/`length` (linked to `parallel_to`), `p1` (linked, offset by `dist`) | `Line(dist=…, parallel_to=other)` — full-length parallel copy of `other`, shifted along its left-normal by signed `dist` (positive = left of the reference's `p1→p2`) |
| `TANGENT_ANGLE` | `p1` (linked to a point on `circle`), `at_angle`, `length` | `Line(circle=c, at_angle=…, length=…)` — `at_angle` is the touch point's *position* around the circle in **degrees** (matching `Circle.point_at_angle`); the heading `angle` is the Derivate `at_angle + 90`. `Line(circle=, angle=)` raises `TypeError` naming `at_angle=`. Not `at=`: `Track.at(u)` takes a fraction |
| `TANGENT_POINT` | `p1`, `p2` (linked, tangent touch point) | `Line(from_point=…, circle=c, side='left'\|'right')` — `p2` = tangent touch point on `circle` as seen from `p1`, disambiguated by `side`; degenerates to `p1` itself if `p1` is inside/on the circle |

A source shape (`parallel_to=` / `perpendicular_to=` a Line, `circle=` a Circle, `Ellipse(from_rect=)` a Rect or Square) must be that kind and alive: another type raises `TypeError` naming the parameter, a destroyed one raises `DestroyedError` (A7 / A11 in [Testing Design](Testing%20Design.md#a--api-surface)).

Always present (role flips with model): `vec`, `angle`, `length`, `center`, `dx`, `dy`, `dist`. Home `CENTER_LENGTH_ANGLE` keeps `center` Defining and `p1`/`p2` Derivate (do not use `Line(p1=)` for placement — that locks what should stay Defining on endpoint models).

On models that take `length` as a free input (`CENTER_LENGTH_ANGLE`, `POINT_ANGLE_LENGTH`, `PARALLEL_POINT`, `PERPENDICULAR_POINT`, `TANGENT_ANGLE`), `length` is a magnitude. Construction and assignment raise `ValueError` unless it is finite and ≥ 0 (a formula link is not checked until it writes a number). `angle` on those free inputs must be finite. `POINT_POINT` / `POINT_DX_DY` still derive `length` as a hypot, which is already ≥ 0.

`Line.angle` is the **geometric direction** of the segment (not a separate visual spin) — except for `TANGENT_ANGLE`, noted above.

Relational models store the foreign shape in `self._ref` (and `self._tangent_side` for `TANGENT_POINT`) — see "Cross-shape relational constructors" above. Note that a part can be `FieldType.Defining` yet still be formula-linked to a foreign shape (e.g. `angle`/`length`/`p1` in `PARALLEL_DIST`) — "Defining" means "not computed from this shape's *own* other parts by `_update_impl`", not "a free, unlinked input"; only `dist` is actually free there. `Circle.tangent_line_from_angle` / `tangent_lines_from` are one-shot wrappers that delegate to `TANGENT_ANGLE` / `TANGENT_POINT`.

## Transforms

- `_move_by`: translate Defining position inputs only (`center` for `CENTER_LENGTH_ANGLE`; `p1`+`p2`, or just `p1` for the point-based models). `PARALLEL_DIST` projects `(dx, dy)` onto the reference's left-normal and adds that to `dist` (motion along the reference is ignored, because `p1` stays linked). A zero-length reference is a no-op. Drag claims `dist`, not `p1`. `TANGENT_ANGLE` raises `LinkedAttributeError`: the touch point is pinned to the circle; slide it with `at_angle=` / `angle=` / `rotate_by`. `force=True` unlinks `p1` on that model only.
- `rotate_by` / `scale_by`: model-aware updates of Defining parts about `about` (default center). One exception: on `TANGENT_ANGLE` the touch point is pinned to the circle, so the default turn orbits the circle's center (`at_angle += d`), and `rotate_to` measures from the heading (`at_angle + 90`; it used to measure from the position and read back 90° off). `scale` is a magnitude: a negative factor raises. Length is multiplied by the geometry factor (never a signed length). Mirror with `flip_x` / `flip_y`.
- `draw`: world-space `p1` → `p2` (Defining endpoints, or live Derivates for the home model; mirrors like `center`/`vec` stay lazy unless linked / Defining).


# Rect
======

## Models

| Model | Defining | Notes |
|-------|----------|-------|
| `CORNER_CORNER` | `p1`, `p2`, `angle` | `p1`/`p2` are opposite corners, exactly where the author put them (a value or a link — nothing is re-sorted). `angle` is the direction of the width side. `width = L·|cos(φ−θ)|`, `height = L·|sin(φ−θ)|` where `L` is the diagonal length and `φ` its angle; both read 0 when the diagonal lies along a side (a legal collapsed box, same y is not special). `Box` uses the same rule (`angle` instead of `angle`). Which corner is `bottom_left` is decided at first use ([Named points](#named-points)) |
| `TOP_LEFT_WH` | `top_left`, `width`, `height`, `angle` | `top_left` = **world** position of local `(-w/2, +h/2)` |
| `CENTER_WH` | `center`, `width`, `height`, `angle` | Same corner math as `TOP_LEFT_WH`, anchored on `center` instead of `top_left`. Derivate `p1`/`p2` are the named `bottom_left` / `top_right` |
| `POINT_VEC` | `p1`, `vec`, `angle` | `p1` stays where the author put it. `vec` is the signed local `(width, height)` along the rotated sides — not a world-axis delta (`Line(p1=, vec=)` is that). `p2 = p1 + R(angle) @ vec`. The drawn frame uses `abs` of each component. A negative component at first use names `p1` as another corner (`vec=(-100, 50)`: `p1` is `bottom_right`); after that the names stay with their points ([Named points](#named-points)). At `angle=0` the two spellings agree |
| `SPINE` | `p1`, `p2`, `height` | No separate `angle` — orientation comes from `p1 → p2`. Required plain `anchor` selects how the points sit: `"cap"` — midpoints of the short walls (same loci as Derivate `left_center` / `right_center`); `"square"` — centers of the `height×height` end squares (same loci as Derivate `left_square_center` / `right_square_center`; axis length = `\|p2−p1\| + height`); `"side_left"` / `"side_right"` — corners of one long edge, box extends left/right of `p1→p2`. `height` is a non-negative cross-axis magnitude. Derivate `width` is the along-axis extent (`\|p2−p1\|` for cap/side_*; `\|p2−p1\| + height` for square) — same width=local-x / height=local-y rule as the frame-anchored models. When `p1 == p2` (`d == 0`): `cap` / `side_left` / `side_right` collapse (`width == 0`, `is_collapsed`). `anchor="square"` is a `height×height` square centered on that point (`width = height`), so it is not collapsed |

Local frame (y up, matching Scena). Until something mirrors the names, the top-left local offset from center is `(-w/2, +h/2)`; in general it is the named offset `(−a, b)` below.

```text
center = top_left - R(angle) @ (−a, b)
world_point(local) = center + R(angle) @ local
```

Derivate points (lazy until accessed or linked; local offsets about center, then oriented). `a, b` are the signed **name half-extents** ([Named points](#named-points)); unmirrored, `a = w/2`, `b = h/2`:

| Part | Local `(x, y)` | Notes |
|------|----------------|-------|
| `center` | `(0, 0)` | Role flips with model |
| `top_left` / `top_right` / `bottom_left` / `bottom_right` | `(∓a, ±b)` | Corners |
| `top_center` / `bottom_center` | `(0, ±b)` | Long-edge midpoints |
| `left_center` / `right_center` | `(∓a, 0)` | Short-wall midpoints (`anchor="cap"`) |
| `left_square_center` / `right_square_center` | `(∓(a − copysign(\|b\|, a)), 0)` | Centers of the `height×height` end squares (`anchor="square"`) |
| Derivate `p1` / `p2` | `(−a, −b)` / `(a, b)` | The named `bottom_left` / `top_right` |
| Derivate `vec` | — | `p2 − p1` in the rect's frame, so `p2 == p1 + R(angle) @ vec` on every model (like `POINT_VEC`). `CORNER_CORNER`: signed `R(−θ)(p2 − p1)`; others `(2a, 2b)`. `SPINE`: `(2a, 2b)` too — its `p1`/`p2` are axis points, not corners |

Model-dependent `p1`/`p2` (and sometimes `top_left` / `center`) may be Defining instead. Two frames, one pose:

- `_oriented_frame()` returns `(cx, cy, w, h, ang)` with **non-negative** drawn extents. Paint, hit test, collision, `is_collapsed`, geometry queries and `region_frame` read it; they do not depend on names.
- The name frame (`_RectNames` mixin, shared with `Box`): `_name_half_extents(w, h)` → `(a, b)`; `_name_frame()` → `(cx, cy, a, b, ang)`; `_effective_name_signs()` → the signs of `(a, b)`.
- The frame model (`_RectFrame` mixin, shared with `Box`): the construction models (`_init_model`, one signature table), `_oriented_frame`, `_top_left_offset`, Derivate materialization and the five `_update_impl_*`. Hooks: `_publish_heading(ang)` (Rect writes its pose store; Box has none) and `_pull_heading` (Rect's derived-heading link). Box overrides only `_oriented_frame`, to read a snapshot's center as floats. Do not copy these methods back into Box or Rect: `tests/test_rect_frame.py` fails (Box carried a near-copy that ignored mirrored names on its `top_left` model, D23).

`_apply_oriented_corners(cx, cy, w, h, ang)` writes only live Derivate named points, Derivate `p1`/`p2` and `vec` (skips Defining and cold/unregistered slots). It names nothing unless a named point is live: naming happens at first use, never at the first update. Every `_update_impl_*` refreshes a live Derivate `vec` through it (`_refresh_live_vec`); `_update_impl_*` uses `_takein_live_derivate` for the other optional mirrors (`width`/…).

## Named points

**Rule: a rect names its corners the first time one is used. From then on each name stays with its point** — through drags, link updates, tweens, rotations, scales and flips. The names are the box's own parts, named in its own rotated frame.

- **First use** = the first read or link of a named point (`top_right`, `left_center`, `corners`, `show_points`, …), the first flip, the first `Track` outline, a `clone()` / `_takein`, or (Box) the first layout verb (`strip` / `beside` / `grid` / `inset` / `outset` / `Box(box)`). At that moment the names are the visual ones (in the rect's frame): the corner that looks top-right is `top_right`, however `p1` / `p2` were ordered.
- **Why first use, not construction.** `Rect(p1=(200, 150), p2=(500, 250))` followed by `caixa["p1"] @= …` / `caixa["p2"] @= …` is a common spelling: the constructor values are placeholders. Naming at construction would pin `top_right` to `p2` whatever the links do. Naming again on every `@=` would rename under a consumer that already follows `top_right`. Before the first use nobody can observe a name, so nothing can see it change; after it, nothing renames. The cost: a debug `print(caixa.top_right)` before the links names the corners from the placeholders.
- **Only `CORNER_CORNER` and `POINT_VEC` can cross.** They wait for the first use. `CENTER_WH`, `TOP_LEFT_WH`, `SPINE` and Square have magnitude sizes: their names start visual and change only when a flip mirrors them.
- **Storage.** `_name_signs = (sx, sy)` (plain, per instance): the signs that made `a = sx·lx/2`, `b = sy·ly/2` non-negative at first use, where `(lx, ly)` is the signed local extent (`CORNER_CORNER`: `R(−θ)(p2 − p1)`; `POINT_VEC`: `vec`; others: `(w, h)`). `top_right` is `(a, b)` whatever the signs later become — e.g. drag `p1` past `p2` and `bottom_left` is still `p1`.
- **Flips are true mirrors** (`_mirror_geometry` override): every named point lands on its mirror about `center`. `angle` keeps the flip convention (`flip_x`: `180 − θ`, `flip_y`: `−θ`); under it a mirror keeps `a` and negates `b`. `CORNER_CORNER` gets that by mirroring `p1`/`p2`; `POINT_VEC` negates `vec.y` (both axes); the size-defined models flip the stored `sy` (and `TOP_LEFT_WH` mirrors `top_left` as a point); `SPINE` also swaps `side_left` ↔ `side_right` (a mirror changes handedness). Flip twice is the identity. After a flip that writes no changed Defining value (`flip_y` at `rotation = 0`), the batch's closing `update()` still refreshes linked named points.
- **Copies carry names — and so does every Box made from a Graphic.** `clone()`, `_takein`, `Box(some_box)`, Box layout children, `graphic.box` / `Box(graphic)` and `box=` placement of a Rect / Square all keep the source's names (a size-defined copy takes `_effective_name_signs()` as its own signs; `box.region_name_signs` reads them from any frame-like Graphic, including a flipped Sprite / Svg / Ellipse / Text). So `rect.box.top_right` is `rect.top_right`, a board's `rect.box.grid(8, 8).cell(0, 0)` stays the same square through turns and flips, and a flipped sprite's `box.top_center` is still over its head. A Box is a Rect that does not draw.
- **The screen question goes to the screen-aligned edges.** `box.left` / `.bottom` / `.right` / `.top` are the only readings that ignore names: "above the sprite on screen" is `(box.center.x, box.top)` whatever its rotation or flips.
- **Indexed vertices follow the same rule.** A free `Polygon` mirrors its Defining vertices in place; a `RegularPolygon` / `EquilateralTriangle` reverses its winding on each flip. Either way `points[k]` stays the same vertex, so a link on it never jumps ([RegularPolygon](#regularpolygon--equilateraltriangle)).
- **Track.** A `Track(rect)` / `move_along(rect)` outline starts (`u = 0`) at `bottom_left` — after its fillet when rounded — and still travels CCW.

Guard: `tests/test_rect_names.py` (first use, identity through crossings / rotation writes / pivots, a linked observer, the flip mirror property over every model, the fresh-twin Derivate check, copies, Box, Track, canaries).

Optional AABB scalars (`left`/`right`/`top`/`bottom`) are deferred — oriented rects expose Points.

## Transforms

- `_move_by`: Defining positions only (`p1`+`p2`, `top_left`, `center`, or `p1` for `POINT_VEC`; both `p1`+`p2` for `SPINE`).
- `rotate_by` about center: `CORNER_CORNER` rotates Defining `p1`/`p2` and updates `angle`; `CENTER_WH` updates `angle` only (Derivate corners including `p1`/`p2` follow); `POINT_VEC` rotates `p1` and updates `angle`; `TOP_LEFT_WH` also rewrites world `top_left` so the center stays fixed; `SPINE` has no free `angle` (Derivate, recomputed from rotated `p1`/`p2`).
- `rotate_by` about another pivot: orbit geometry about the pivot while updating Defining parts + `angle` (or just `p1`/`p2` for `SPINE`).
- `scale_by`: uniform about pivot; updates Defining size/corners. A negative factor raises. `SPINE` `height` stays a magnitude.
- `angle` is the geometry field itself. `rect.angle += dθ` writes that field (keeping the model's other inputs: `top_left`, `p1`, …); `rotate_to` / `rotate_by` still pivot on `center` by default. On `CORNER_CORNER` those are different operations: `rotate_to` / `rotate_by` turn the box **with** its corners; writing or linking `angle` keeps `p1`/`p2` pinned and changes the size (the box leans and slims, and collapses every 90° when the diagonal lies on a side). `angle=90` is the same box as `angle=0` with width and height swapped. To spin a box of fixed size, use `CENTER_WH` (`center` / `width` / `height` / `angle`) or `rotate_by`. Named points keep their points through the collapse: `bottom_left` stays `p1` (the box turns inside out instead).
- `flip_x` / `flip_y`: a true mirror of every named point about `center` ([Named points](#named-points)). `POINT_VEC` negates `vec.y` on either axis (it used to negate `vec.x` on `flip_x`, which on top of `180 − θ` moved the box — G3); `SPINE` side anchors swap (they used to move the box across `p1→p2` — G4).
- `draw`: CTM — `save` → `translate(cx,cy)` → `rotate(degrees(ang))` → `drawRect(-w/2…)` when `corner_radius==0`, else `drawRRect` with radius clamped to `min(r, w/2, h/2)` → `restore`, using `_oriented_frame()`. World corners are **not** required for paint. `_oriented_frame` returns **non-negative** `w`/`h` for `CENTER_WH` and `TOP_LEFT_WH` (`abs` of the stored size) so `scale_by(-1)` stays visible and hittable; Defining `width`/`height` may remain signed on frame-anchored Rect models. Square `length` stays a non-negative magnitude (`scale_by` multiplies it by `abs(factor)`). `SPINE` Defining `height` is non-negative by construction; Derivate `width` is the positive along-axis extent. `POINT_VEC` / `CORNER_CORNER` already used `abs`.
- `corner_radius` is a plain (non-reactive) extra, default `0`, copied on clone / `_takein`, live-settable. Paint and the pointer use the rounded fill (same clamp as `drawRRect`). Collision stays the oriented box; linked corners stay the sharp vertices. Does not scale with `scale_by`. Square inherits the property, the draw branch, and the pointer test. A callable (`corner_radius=lambda: …`, `.corner_radius = lambda: …`, or `rect["corner_radius"] @=`) raises — paint stays outside the graph (`CallableAssignError` / the reserved-name `AttributeError`).


# Square
========

`Square(Rect)` — narrows `Rect` to `width == height == length`, using `CENTER_WH`/`TOP_LEFT_WH` under the hood.

| Model | Defining | Notes |
|-------|----------|-------|
| `CENTER_LENGTH` | `center`, `length`, `angle` | Built on `Rect`'s `CENTER_WH` corner math |
| `TOP_LEFT_LENGTH` | `top_left`, `length`, `angle` | Built on `Rect`'s `TOP_LEFT_WH` corner math |

`Square.__init__` does **not** call `Rect.__init__` (it has its own signatures; it calls `Shape.__init__` directly). Anything `Rect.__init__` sets on the instance (`_anchor`, the corner radius, …) must be set in `Square.__init__` too: `test_shapes.TestSquare.test_init_sets_what_rect_init_sets` builds both the same way and fails on any instance attribute one has and the other lacks, apart from the size parts (`width`/`height` vs `length`).

`width`/`height` are always Derivate mirrors of `length` (even though they're Defining on a plain `Rect` for these same models) — setting them directly raises `DerivedAttributeError`. Enforced in `Square._set_defining_parts`: `_defining_part_names` **includes** `length` (so the slot is created Defining with a downward edge), while `width`/`height` are forced Derivate. Do not strip `length` before storing the defining set — that would create `length` as Derivate and break `length → Square` dirtying.

Named points follow Rect's rule ([Named points](#named-points)): visual until a flip mirrors them; `clone()` / `_takein` copy the name signs (a `TOP_LEFT_LENGTH` copy needs them to place its center from `top_left`).

`_update_impl` mirrors `length` into `width`/`height` (inside `@batch_update_attrs('width', 'height')`, to bypass the Derivate write-guard) and then calls `Rect._update_impl` unchanged. `move_by`/`rotate_by`/`draw` are inherited from `Rect` (CTM draw, including `corner_radius`). Only `scale_by` is overridden: it delegates to `Rect.scale_by` for the geometry, then multiplies Defining `length` by the same non-negative geometry factor.


# Circle
========

## Models

| Model | Defining | Notes |
|-------|----------|-------|
| `CENTER_RADIUS` | `center`, `radius`, `angle` | |
| `CENTER_PERIMETER` | `center`, `perimeter_point` | `radius` = distance between them; `angle` = direction to `perimeter_point` |
| `TWO_POINTS` | `p1`, `p2` | Diameter endpoints; `center` = midpoint, `radius` = half the distance; `angle` = direction to `p1` |

Always present (mirrored across models so cross-model reads work regardless of which is Defining): `center`, `radius`, `perimeter_point`, `p1`, `p2`. Alternate-model mirrors are written only when live (lazy).

**Rim points** (Named points): one reference rim point, `p1 ≡ perimeter_point`, and `p2` opposite it. Placed by `center=` + `radius=` they sit on the heading `angle` — the circle's frame — so they turn with `rotate_by` and mirror on flips (they used to stay at world ±x); placed by `perimeter_point=` or `p1=, p2=` they are those points, and **the heading is theirs**: `angle` is a Derivate, the direction center → `p1` (`_arc_angle`, unwrapped to the accumulated turn so `rotate_by(400)` reads +400, like Line). One heading per circle: `angle`, `circle.box` (the diameter square turned to `p1`, so `circle.box.right_center` is `circle.p1`) and the arc's opening all agree. Before G17 a rim-placed circle read `angle` 0 (the default arc `angle`) while its box turned to `p1`. Setting the derived heading follows the rule for a derived heading (`_DerivedRotationRoute`, heading field `angle`): `angle =` / `["angle"] @=` turn the rim about the center, and `Circle(perimeter_point=, angle=)` / `Circle(p1=, p2=, angle=)` turns the rim to `angle` at construction — the arc opens where `angle=` always put it; only the rim point moves onto it. With a **linked** rim point, `angle=` raises `TypeError` (it would have to move the linked point); without `angle=` the arc opens toward the rim point. `clone()` keeps the model. Placed by `perimeter_point=`, a linked `angle` and a linked `center` are exclusive (refused at the second `@=`): the heading is measured from the center, so each center move would turn the rim again, and the radius would follow whichever moves had been read (GR18). To drive both, place it by `center=` + `radius=`, where `angle` is an input.

Optional arc on every model: `angle`, `spread` (**degrees**). `angle` is the heading (0 = +x, counterclockwise); on `CENTER_RADIUS` it is an input and defaults to `0`, placed by the rim it is the direction to `p1`. `spread` is the full opening and defaults to `360` (a full circle). The arc covers `[angle − spread/2, angle + spread/2]`. Either keyword may be given alone. Author `spread` must be in `[0, 360]` (negative raises; above 360 raises). A linked or tweened value outside that range is clamped when the arc is drawn or outlined. `0` draws nothing. `360` is the full circle. `.angle` is the heading field (`rotate_by` / `rotate_to` turn it; `scale_by` leaves `spread` alone). Outline seam: a full circle starts at `angle` (so the default keeps `u=0` on +x); a partial arc starts at `angle − spread/2`. This is the same heading and opening as `collision.query_sector`. Plain (non-reactive) `use_center` defaults to true: a partial arc draws as a pie (radii included). `use_center=False` draws an open arc stroke and a chord-closed segment for the fill. Collision follows that filled region, not the stroke width: a full turn is one circle primitive (circle–circle and circle–box tests unchanged); the default pie uses the same wedges as `query_sector`; `use_center=False` is one convex chord segment; `spread` of 0 emits no prims. The broad-phase proxy stays the circumdisk. Pointer `contains_point` follows that same filled region. `intersections` / `closest_point` stay the full circumference. A filled pie that must grow from a fixed anchor is a `Track` `end` window, not a second Circle spelling.

`Circle.from_limits` was removed (redundant with `TWO_POINTS`, and its `(min, max)` semantics didn't match a circle's diameter-endpoint framing). `tangent_line_from_angle` / `tangent_lines_from` remain as one-shot classmethod wrappers, but now delegate entirely to `Line`'s `TANGENT_ANGLE` / `TANGENT_POINT` relational models.

## Transforms

- `_move_by` / `rotate_by` / `scale_by`: model-aware; live alternate-model points stay consistent after transforms. `rotate_by` / `rotate_to` turn `angle` (the heading). `scale_by` leaves `angle` and `spread` unchanged.
- `draw`: world-space `center`/`radius`, the arc `[angle − spread/2, angle + spread/2]` when `spread` is not a full turn. Hit-test, draw, `point_at_angle`, and tangent touch points use `abs(radius)`: a negative stored radius is the same disk, and tangent `side` does not flip. Derivate `p1`/`p2` still place from the signed radius (a negative value lands on the opposite point of that same circle).


# Ellipse
=========

## Models

| Model | Defining | Notes |
|-------|----------|-------|
| `CENTER_WH` | `center`, `width`, `height`, `angle` | Foci (`fp1`/`fp2`) and `major_axis` use `abs(width)` / `abs(height)`, so `scale_by(-1)` (or a negative stored axis) keeps the same ellipse. Defining `width`/`height` may stay signed |
| `FOCAL_POINTS` | `fp1`, `fp2`, `major_axis` | `center` = midpoint, `angle` = direction `fp1→fp2` (Derivate: setting or linking it turns the ellipse about its center, like `rotate_to`). All three inputs take a lambda (same rule as every other Defining geometry kwarg). Construction raises `ValueError` if `major_axis` is not finite, or if `major_axis < distance(fp1, fp2)` (equal is a legal collapsed ellipse — the segment `fp1`–`fp2`, or a point at zero size, like a zero-width Rect; it used to raise), **only when every input is a concrete number** — a link cannot be snapshotted (`_concrete_xy` / `_concrete_float`). A later write or a formula that shrinks `major_axis` below the focal distance collapses onto the segment joining the foci (`a = c`, `b = 0`) instead of a shorter oval with the foci outside it |
| `FROM_RECT` | *(none — all formula-linked)* | `center`/`width`/`height`/`angle` are each linked to a foreign `Rect`'s corresponding fields. `width`/`height` are `max(0, host − 2 * padding)`; `padding` is a fixed, non-reactive value captured at construction. Padding that overflows the host is a collapsed ellipse (`is_collapsed`, miss on hit-test). Reuses `CENTER_WH`'s derived-attribute math |

Always present (mirrored): `center`, `width`, `height`, `angle`, `fp1`, `fp2`, `c` (focal distance), `major_axis`.

## Transforms

- `_move_by`: `center` (or a `_ensure_writable` guard + `center` write for `FROM_RECT`, since it's normally linked) or both foci for `FOCAL_POINTS`.
- `rotate_by` / `scale_by`: model-aware; `FOCAL_POINTS` rotates/scales both foci directly (recomputing `angle` from the result) rather than bumping a free `angle` attribute, since `angle` is Derivate for that model.
- `draw`: `save` → `translate(cx, cy)` → `rotate(degrees(ang))` → `drawOval` local rect → `restore`, via `_oriented_frame()` (non-negative extents; Defining/`FROM_RECT`-linked pose; foci stay lazy unless live). `Track(ellipse)` uses the same frame.


# Polygon
=========

Unlike the other shapes, `Polygon` has a single constructor signature (`Polygon(points=[...])`, or `Polygon()` for a default irregular quad) but a **dynamic number of Defining parts**: N vertex `Point`s, owned directly (`Point(attr_name=f"v{i}", owner=self)`, not via `ContainerSlot`) rather than a fixed model list. Vertex count is fixed at construction (not reactive); each vertex follows the same construction rule as other fields — bare values copy, callables link (`Polygon(points=[lambda: rect.top_left, (0, 0), (5, 0)])` links vertex 0 only). Common kwargs `color=` / `visual=` / `line_width=` / `id=` / `layer=` / `group=` match other Shapes; class style defaults for `color` / `visual` / `group` apply the same way as `_extract_common_params_and_signature` (`line_width` is not a class default).

Derivate: `centroid` (`Point`, **vertex average** — not the true area centroid, documented as such), `signed_area` (shoelace formula; positive = counter-clockwise winding), `perimeter_length`. These are materialized on first access (`_materialize_derivate_part`); RegularPolygon skips rewriting them when cold.

`center` is a plain `@property` aliasing `centroid` (uniform pivot API, matching `Point`/`Rect`/`Circle`/`Ellipse`).

Construction pitfall: all N vertices must be created and registered as parts (`owner=self`) *before* any of them are wired with `assign_formula`, otherwise the first `assign_formula` call triggers a premature `_update_impl` against a partial (or empty) vertex list. See the two-pass loop in `Polygon.__init__`.

## Transforms

- `_move_by`: translate every vertex by `dx`/`dy`.
- `rotate_by` / `scale_by`: `_rotate_xy`/`_scale_xy` applied per-vertex about the pivot (with an `_ensure_writable` guard per vertex, since individual vertices are commonly linked).
- `draw`: `moveTo`/`lineTo` through world-space vertices, closed.


# RegularPolygon / EquilateralTriangle
=======================================

`RegularPolygon(Polygon)` — an equilateral, equiangular n-gon whose N vertices are always **Derivate** (computed from `center`/`radius`-or-`side`/`angle` + a fixed vertex count `n`), unlike the plain `Polygon`'s Defining vertices.

`angle` is always the direction from `center` to `vertex[0]` (**degrees**, 0 = `+x` axis); vertices proceed counter-clockwise from there (`vertex[i]` at `angle + w · i · 360/n`, winding `w = +1`), matching `Polygon`'s positive-`signed_area` convention. Each flip reverses the winding (`w = −1`: clockwise, negative `signed_area`, like a flipped free `Polygon`) so every `vertex[k]` lands on the mirror of the old `vertex[k]` — vertices follow their points ([Named points](#named-points)). The stored `_vertex_winding` is copied by `clone()` / `_takein`. Only the numbering changes: paint, collision, geometry queries and `Track` build their own CCW vertex set from `_placement_params()`, so they never see the winding (a Track outline still starts at `vertex[0]` and runs CCW). `radius` is the **circumradius** (center-to-vertex distance — the project's chosen convention for "radius" on a regular polygon, as opposed to the inradius/apothem).

## Models

| Model | Defining | Notes |
|-------|----------|-------|
| `CENTER_RADIUS` | `center`, `radius`, `angle` | `side` (chord length) is derived: `2 · abs(radius) · sin(π/n)` |
| `CENTER_SIDE` | `center`, `side`, `angle` | `radius` is derived: `abs(side) / (2 · sin(π/n))` |
| `VERTEX_SIDE` | `vertex` (= `vertex[0]`'s world position), `side`, `angle` | `center` is derived from the positive circumradius: `vertex - abs(radius) · (cos(angle), sin(angle))` |

`n` must be an `int` ≥ 3 (`TypeError` for bools and other non-integers — `5.9` is not truncated to 5; `ValueError` for `n < 3`). It is a fixed, non-reactive constructor argument, like `Polygon`'s vertex count — it never changes over the shape's life. Omitting `n` defaults to 6 (`RegularPolygon()` / `RegularPolygon(center=…)` → hexagon; `EquilateralTriangle()` pins `n=3` and rejects any other `n`, including `3.9`). Placement uses `abs(radius)` and `abs(side)`, so a negative stored Defining radius or side is the same polygon as the positive magnitude (same convention as Circle's disk). Derived `side` / `radius` are non-negative. A non-finite `radius` or `side` raises `ValueError` at construction and on assignment.

`centroid` (inherited from `Polygon`) is numerically identical to `center` for a regular polygon by symmetry; `center` is declared as a real `ContainerSlot` on `RegularPolygon`, which **shadows** `Polygon`'s `center`-aliases-`centroid` property (Python attribute lookup favors the subclass's own descriptor).

Vertices are registered at construction (dynamic `_vertices` list) but stay **cold** until indexed, iterated, or linked — `_place_vertices` only `takein`s live verts (or all verts when centroid/area/perimeter are live). `.points` is a lazy sequence: `len` is free; `__getitem__` materializes that index. Named Derivate slots (`side` / `radius` / …) follow the same ContainerSlot laziness as Rect. `_move_by`/`rotate_by`/`scale_by` update Defining `center`/`radius`/`side`/`angle`/`vertex` directly instead of per-vertex. `move_to`'s default always targets the geometric center (via `_pivot_xy` / `_move_by` composition, including `VERTEX_SIDE`). `about=` reaches any Defining point directly (including `vertex`) when asked. Collision pose extra is `(rot, scale, rotation, radius, side)` from those Defining slots — it does not walk Derivate verts (freeform `Polygon` still does).

`draw` is **overridden**: CTM translate to center, build an n-gon path in local polar coordinates from `radius`/`angle`/`n`, stroke/fill, restore — paint does not require reading `_vertices`.

`EquilateralTriangle(RegularPolygon)` pins `n=3` (raising if the caller passes a conflicting `n`, including a non-integer such as `3.9`) and otherwise exposes the same three models. Replaces the legacy, non-reactive `EqTriangle`.

**Angle convention:** `angle` is where vertex[0] (the apex) points, as for every heading in Scena (0 = `+x`, CCW): `EquilateralTriangle` is exactly `RegularPolygon(n=3)`. `angle=0` points right; `angle=90` is the upright pose with a flat base. That keeps `face=True` motion apex-first and makes a triangle ship's `angle` its heading, like a Sprite's. (Until 2026-09-30 the triangle added +90°, so `angle=0` was upright and `face=True` flew it sideways.)

**Flips** (`RegularPolygon._mirror_geometry`, inherited by the triangle) mirror the vertex-0 heading (`_geometric_angle`), not the raw `angle`, and `VERTEX_SIDE` also mirrors its Defining `vertex`: the polygon stays in place and becomes its mirror image. With no offset between `angle` and the vertex-0 heading (every kind today) that is the usual `180 − θ` / `−θ`; the heading form keeps a future offset kind correct (G6). The flip also reverses the winding, so every `vertex[k]` lands on the mirror of the old one. Guards: `test_flip_mirror.TestFlipMirrorsEveryKind` (every kind: drawn geometry is the mirror, center fixed, twice = identity), `TestVerticesFollowTheirPoints` (every index, a linked vertex, clone), `TestRegularPolygonStatsMatchAFreePolygon` (`signed_area` / `perimeter_length` / `centroid` on the first read equal a free `Polygon` on the same vertices — G8).

# Track
======

Drawable curve and motion track — one `Shape`, invisible by default (like `Point`).
Models `FREE` (`points=` / presets), `CIRCLE` (`radius=` / `Track.circle` / `Track.arc`),
and `SHAPE` (`Track(other)` live outline). Flattened polyline + arc-length in `curves.py`;
pose applied at sample time. Circle/arc `radius` is inside the bake: assigning it
after the first sample rebuilds the polyline (`center` / `angle` / `scale` do not).
`Track.arc` takes its angles from the spec and its radius from the live `radius`
attribute, so `arc.radius = …` updates `at(u)`.
`reversed()` is a live view of the host tables — hit-test, draw, and the stroke
collider follow the host after each rebake, including the host's `begin`/`end`
window in host parameter space (the view does not own a second window). Rect/Square outlines follow
`corner_radius` whenever it is positive after clamping to half the sides, including
radii below half a pixel (`r == 0` stays the sharp 4-gon). Filled Rect collision
stays the sharp box. `Track(ellipse)` uses `Ellipse._oriented_frame`.
`begin` / `end` (0..1) are a **stroke** window (draw + hit-test + collision) —
not geometry (`length` / `at` / `move_along` stay the full curve).
Collision matches the pointer family: a **stroke tube** (chain of thin OBBs along
the bake, thickness `line_width`) — closed = ring, not a disk; not a `Circle` arc.
`move_along` is on every Graphic. Depth:
[Tracks Design.md](Tracks%20Design.md). Author: [Guia da API](../docs/pt/guide/index.html#shape-track).

Live stamp buffers (growing / expiring samples, fading stroke recipe) are
`History` / `Contrail` — not a Track. See [History Design.md](History%20Design.md).

# Geometry contract
===================

One contract for every Graphic kind and constructor model, checked by `tests/test_geometry_contract.py` (families C1–C8; registry `tests/geometry_support.py`). Violations known today are listed, shrink-only, in `tests/geometry_known.py` (the sweep fails on a new violation *and* on a listed one that passes); Testing Design lists them under Open.

- **Conventions.** Angles are degrees, 0 = `+x`, counter-clockwise. The default pivot is `center`. `scale` is uniform and a magnitude (negative raises). `flip_x` turns a heading to `180 − θ`, `flip_y` to `−θ`.
- **`angle` is the heading** on every kind — the one name for where a Graphic points: a Line's is its direction `p1 → p2`, a Circle's its arc heading, a Rect's its width axis, a RegularPolygon's the direction to `vertex[0]`, a Sprite's where the painted front points. A derived heading keeps full turns (unwrapped to the pose store, so `rotate_by(400)` reads `+400`, not `40`: Line `p1=, p2=`, Rect spine, Ellipse foci, a rim-placed Circle; G14). Only verbs move that turn reference; a point write reads the new direction unwrapped to it, and so does an update (a Rect spine's update used to write its heading back, so the same writes read a different turn depending on what had been read: GR17). A flip mirrors it by the convention, including a heading kept only as pose (Point, Polygon), which used to stay put. Engine code reads it with `_rotation_value()` (Defining inputs only; `.angle` would wake a Derivate).
- **Setting `angle` — fields keep the placement point; verbs turn the whole shape.** `angle` is a field like `width`: setting it (`=`, `@=`, the constructor keyword or a `tween` — all the same) keeps the model's other inputs, so the point the shape was placed by stays (center, `top_left`, `p1`, `vertex`, a Text's anchor; a `p1=, p2=` Rect leans). If the heading is derived from the placement points (Line `p1=, p2=` / `vec=` / `dx=, dy=`, Rect spine, Ellipse foci, a Circle placed by its rim, a free Polygon), setting it is `rotate_to` about the center. Kinds with no heading input (Point, Sprite, Svg, Track, centered Text) are placed by their center, so setting it is `rotate_to`. The verbs `rotate_to` / `rotate_by` always turn the whole shape about the center (or `about=`). So `angle = θ` and `rotate_to(θ)` differ exactly where `top_left =` and `move_to` differ: on a shape placed by something other than its center. Guard: `tests/test_angle_field.py`.
- **Why one name, and why it is not `rotation`.** A field write keeps the placement point (`=`, `@=`, the constructor keyword and `tween` must agree, and the constructor never moves a `top_left=` it was given); a name paired with `rotate_to` must mean the verb, a rigid turn about the center (`scale = v` ≡ `scale_to(v)`). On a shape placed by a corner, end or vertex these give different geometry, so they cannot share a name — and the field keeps the placement point because a linked placement point plus a linked heading (a sword held in a hand: `Rect(p1=lambda: hand…, vec=…)` with `["angle"] @= …`) works only as a field; `rotate_to` on that rect raises `LinkedAttributeError`. Not taken:

  | Idea | Why not |
  | --- | --- |
  | `rotation` as the field on every kind (the 2026-09 state) | The noun of `rotate_to` that does not mean `rotate_to`: `rect.rotation = 30` kept `top_left`, `rect.rotate_to(30)` turned about the center. And `rect.angle = 30` silently became ink while Line / Circle / Box used `angle`. |
  | Setting the heading ≡ `rotate_to` | A linked placement point plus a linked heading becomes impossible, and the `p1=, p2=` lean is unreachable. |
  | The placement point as the verbs' default pivot | What a call does would depend on how the shape was built; `scale_by` / flips / `move_to` would have to follow, and a mixed group would turn inconsistently. |
  | Both: `rotation` (pose, ≡ `rotate_to`) and `angle` (field) | Two writable names for one number, and they drifted (`p1=, p2=` Line after `rotate_by(400)`: `angle` 40, `rotation` 400). |

  Cost accepted: `angle` is now a reserved ink name (`_INK_RESERVED`), so `self.angle` in a Sprite subclass turns the sprite — visible, not silent.
- **`rotation` is retired on Graphics** (it named the heading until 2026-10). `Graphic._RETIRED_ATTRS` makes a read, a write and `x["rotation"]` raise `AttributeError` with the hint (`_ROTATION_RETIRED`), and `rotation=` in any constructor raises `TypeError` (`validate._FAMILY_KWARG_HINTS`); a one-edit typo of it (`rotaton`) raises too. Never let a retired or reserved pose name become ink: that is the bug class `rect.angle = 30` had before (an accepted write that did nothing). Guard: `test_angle_field.TestRotationIsRetired` (every kind × every spelling; every `_INK_RESERVED` name). The camera keeps `canvas.rotation` (read-only, written by `canvas.rotate_to` / `rotate_by`; no placement models, so noun and verb agree).
- **Two scale models.** Shapes bake `scale` into their sizes (`width`, `radius`, … follow `scale_by`). Sprite, Svg, Text and Track keep `scale` as a pose zoom on top of their size knobs: `sprite.width` / `height` (Sprite Design — "One scale per sprite"), `text.width`, `track.radius` stay; their measurements (`.box`, `track.length`) follow `scale`.
- **C1 Point stability.** A pose verb (`move_by`, `move_to`, `rotate_by` / `rotate_to` about the center or a pivot, `angle =`, `scale_by` / `scale_to`, `flip_x` / `flip_y`, the timed forms) is a similarity or a mirror about its pivot, and every point part follows it: named points, Defining and Derivate slots, `points[k]`, the named points of `.box` ([Named points](#named-points)).
- **C2 Transform algebra.** The drawn geometry follows the same transform; verbs invert (`a`, `−a`; `k`, `1/k`; a flip twice) and compose (`a` then `b` = `a + b`; scales multiply; `flip_x` + `flip_y` = a half turn); `rotate_to` / `scale_to` agree with `rotate_by` / `scale_by`; `angle` and `scale` read back the convention.
- **C3 Invariance.** Lengths are unchanged by move / rotate / flip and scale by `k`; areas by `k²`; one flip negates `signed_area`.
- **C4 Read-back.** Every Derivate equals an independent computation from the Defining values (a free `Polygon` on the vertices, radius from the rim, width from the corners, `c² = a² − b²`, `p2 = p1 + R @ vec`), after a pose change too, whatever order the parts are read in.
- **C5 Model equivalence.** Every constructor model of the same shape draws the same shape with the same named parts (role parts such as a spine's `p1` / `p2` excepted).
- **C6 Cross-view agreement.** Hit test, collision prims, the `geom` outline, `.box`, the cull AABB and `is_collapsed` all see the drawn geometry.
- **C7 Copies.** `clone()` / `_takein` reproduce the drawn geometry, every point part and the pose (`angle`, `scale`, flip flags). A copy across construction models takes the source's model and the target's own Defining set for it (`_adopt_model_of`, `_defining_names_for`: a Rect that takes in a Square uses width / height); a Track copy is a free points track with the source's pose, a `reversed()` view refuses a copy, Box copies only a Box, and a Square only a Square (a Rect's sides can differ; the TypeError shows `Square(center=rect.center, length=rect.width, angle=rect.angle)`) (D20, D21). Every copy door — `clone()`, `<<`, `absorb`, a whole `@=` pull — runs one pose tail after the geometry (`Container._takein_pose`, Shape: `_clone_pose_from`), so a copy that reads alike also acts alike (SC7 / SB7). A copy has no links, so a relational source (Line `parallel_to=` / `perpendicular_to=` / `circle=`, Ellipse `from_rect=`) arrives as its free twin (`_free_model`: POINT_ANGLE_LENGTH, POINT_POINT for a tangent from a point, CENTER_WH) and drops `_ref`; `force=True` that unlinks a relational shape turns it free the same way, keeping its current values (`Shape._drop_relational`; SB5). `clone()` keeps a free model and builds through the same takein (SB6), and a clone of a parked actor shows on its own (E9). Guard: `sweep_c7` runs `clone`, `<<` and `absorb`, then the same verbs on source and copy.
- **C8 Extremes.** Far coordinates (±1e6), zero sizes, collapse and recovery, tiny scales: same geometry, no NaN, no raise.

A new kind, model or verb joins `KINDS` / `VERBS` in the same change.

**Formulas that name `angle` stay fresh.** A formula's sources come from its source text, so `lambda: …shape.angle…` depends on the `angle` anchor, which the pose verbs mark dirty (`_pose_rotation_set` / `_pose_rotation_add`). Where `angle` is derived from the geometry — Line (`p1 → p2`), a Circle placed by its rim — its anchor is a property anchor that also depends on the shape (`_HeadingFromGeometry`), so a written or dragged endpoint or a flip re-runs those formulas; a Defining `angle` is a plain slot whose own writes notify it; a `center=, radius=` Circle also keeps its pose value in step with `angle` (`_sync_rotation_to_angle`). G18: a heading arrow linked to a Circle's heading stayed put on `flip_x`. Guard: `test_angle_field.TestAngleFormulasStayFresh` (every registry kind × every heading change, read bare as draw reads — a pulled read re-evaluates and hides it).

Visual smoke: `scripts/smoke/geometry.py` — one page per family (pins linked to
named points, an unflipped twin beside each flipped shape, heading arrows, clones
beside their sources), each with live ✓ / ✗ checks.


# Transform API (Shape)
=======================

**Angles are degrees in the public API** (`angle`, `spread`, `angle`,
`rotate_by` / `rotate_to`, `Vec2.angle` / `vec_from_angle`). Positive angles are
**counterclockwise** in authoring (y-up) space. Trig and Skia convert at the
boundary (`_rad` / `_deg` helpers). Prefer `angle=45`, `rotate_by(90)`.

Every Shape exposes **`center`** (a `Point` or Point-like) as the default pivot
for transforms, drag grab-offset, and `set_center`.

| API | Meaning |
|-----|---------|
| `move_to(x, y, *, about=None, …)` | Place a point at an absolute position. Default (`about=None`): the shape's true geometric center lands on `(x, y)`. `about=` names the point that lands on the target instead (rigid translation; orientation/size untouched). Same `GeneralPoint` types as `rotate_*` / `scale_*`. Combined with `face=True`, the face-rotation pivots about that same point. |
| `move_along(target, *, time=, …)` | Travel a `Track` / Shape outline / preset string. Always motion. Slide to a point: `move_to(..., time=)`. [Tracks Design.md](Tracks%20Design.md) |
| `rotate_to(θ, *, about=None, force=False)` | Absolute orientation about pivot (**degrees**) |
| `rotate_by(dθ, *, about=None, force=False)` | Relative rotation (**degrees**) |
| `scale_to(s, *, about=None, force=False)` | Absolute uniform scale factor |
| `scale_by(f, *, about=None, force=False)` | Multiply scale about pivot |
| `angle` / `scale` setters | `angle` is the heading field (Geometry contract — "Setting `angle`"). Where it is one of the model's inputs (`Rect` / `Square` / `Ellipse` placed by center / `RegularPolygon` / `EquilateralTriangle` / `Line` placed by `center` or `p1` + `angle` / `Circle` placed by center), it **is** the geometry slot: `=`, `@=` and the constructor keyword agree, and setting it keeps the model's other inputs (center, `top_left`, `p1`, `vertex`; a `p1=, p2=` Rect leans). Where the heading is derived from the placement points (Line `p1=, p2=`, Rect spine, Ellipse foci, a Circle placed by its rim, a free Polygon), setting it is `rotate_to` about the center and `@=` drives `rotate_to` through a `_PropertyAnchor` (`_DerivedRotationRoute`, `_HEADING_FIELD = "angle"`; it used to raise `DerivedAttributeError`). Kinds with no heading input (Point, Sprite, Svg, Track) alias `rotate_to` about center through the Graphic `angle` property; `Text.angle` turns about its anchor when it has one. `scale` everywhere aliases `scale_to` **about center** via `_PropertyAnchor` (no `about=`). Constructor `angle=` exists on every kind with a heading input and on Sprite / Svg / Text / Track (`Graphic._init_heading`: a number sets, a function links); not on free Polygon or derived models (it would rewrite the given points, K5). `Track.line` / `Track.shuttle` build the segment along +x and take `angle=` as the heading. A field write to a property-backed name (`Graphic._write_field` — e.g. a `tween(shape["angle"], …)` tick) goes through the property setter too; `_resolve_field` still reports the ink-shaped slot for linking, so the ink write path must never see these names (system-test finding S10: every such tween crashed on its first tick) |
| `rest_heading` / `reset_rotation()` | `rest_heading` is `0`; `reset_rotation()` → `rotate_to(0)` |
| `clone(*, scale=1.0, layer=…, group=…)` | Free value+style copy (no formula links); optional uniform scale about center. Omit `group=` to copy source groups; omit `layer=` for the class default; `layer=None` is undrawn |

Default pivot (`about=None`) is `shape.center` (Point: self). For `rotate_*` / `scale_*` that point stays fixed; for `move_to` that point lands on the target. Override with any `GeneralPoint` (`about=rect.top_left`, a tuple, a `Vec2`, mouse). `move_to` also takes one point-like in place of `(x, y)` (Point, Vec2, tuple, Graphic, mouse). `move_to(x)` with a number still sets x only. `move_by` does not take a location.

**Reading a point-like (one rule).** Every entry that takes a point reads it through `shapes._xy_of` / `_read_xy`: exactly two numbers (a tuple or a list; a bool is not a coordinate), a Point, a Vec2, a state cell (read fresh, then the same rules), a Graphic's `center`, or any object with `.x` / `.y` (mouse). A delta (`p + v`, `Track(vectors=)`) refuses a Graphic (`_read_xy(…, graphic_center=False, duck=False)`). A Vec2 refuses a Point where it would mean a displacement (`v << p`) and says why. `get_xy` (draw path) applies the same pair rules. Do not add a private `_as_xy`: `tests/test_pair_reading.py` holds every entry to these rules (D24).

### Point arithmetic

`p + (dx, dy)` and `p + vec` return a new detached `Point`. `(dx, dy) + p` is the same translation. `p - (dx, dy)` translates by the negated delta (a `Point`). `p - other_point` is the `Vec2` between them. `p + other_point` raises — the midpoint is `middle_point`, the vector is `a - b`. The result is not registered and not linked. A formula `bullet.center @= lambda: ship.center + (0, 10)` still follows `ship`, because the formula reads `ship.center`.

`+=` / `-=` on a Point raise `TypeError`. `ship.center += (dx, dy)` would be unswept placement (walls do not stop it) and, on a free marker, would rebind the name to a new point. Move with `move_by(dx, dy)`. Place with `ship.center = ship.center + (dx, dy)`.

### Fence — no `.x` / `.y` on Graphics

Graphics and SpatialFx have no `.x` / `.y`. Position is `.center`. A write, a read, `["x"] @=`, or a link raises `AttributeError` and does not create ink. `Point` keeps real axis slots (the route hits first, so the guard never runs). A bare Entity still stores `x` / `y` as ink.

**Revisit:** taught scripts still decompose `center` into `.x` / `.y` after point arithmetic (`center + (dx, dy)`) landed. Index: [Fences.md](Fences.md).

### `clone`

Shared with Sprite — author usage in [Guia da API](../docs/pt/guide/index.html#spr-clone). Architecture: [Sprite Design.md — Sprite spawn & clone](Sprite%20Design.md#sprite-spawn--clone).

```python
c2 = circle.clone()           # same size, new identity, style copied
c3 = circle.clone(scale=1.2)  # 120% about center
```

- Snaps relational / linked constructions to free geometry (e.g. `FROM_RECT`
  Ellipse → `CENTER_WH` values; linked Line endpoints → bare `POINT_POINT`).
  A free model is kept (Rect `p1=, p2=` / `p1=, vec=` / `top_left=` / spine,
  Square, Circle, RegularPolygon), so every Defining part keeps its identity —
  a copy's `p1` is the source's `p1`, not whichever corner a `CENTER_WH` rebuild
  would name `p1`.
- Keeps the **pose** (`Graphic._clone_pose_from`): `angle` (the accumulated
  turn count too), `scale`, flip flags and winding, copied as state after the
  geometry — nothing is mirrored or turned twice. `clone(scale=)` multiplies.
  Track copies freeze the drawn table in the track's own frame and keep the pose
  as pose ([Tracks Design](Tracks%20Design.md)); Text copies keep their anchor
  form ([Canvas Design](Canvas%20Design.md)).
- Does **not** copy interaction callbacks / flags (except Anchor, which is
  always draggable by construction).
- Omit `group=` copies the source's current groups; `group=` replaces (not a merge).
- `layer` is spawn placement: omit → class constructor default; `clone(layer=None)`
  is undrawn.
- Ephemeral arithmetic copies remain `Point.temp(...)` — not `clone`.

## Linked parts

If a transform must write a Defining part that is linked:

- **Default:** raise `LinkedAttributeError`.
- **Escape:** `force=True` → warn + `unlink_all()` on that part subtree.

Outbound links *to* a part (e.g. `Line(p1=lambda: rect.top_left)`) are fine: the Rect writes its Defining geometry; dependents re-evaluate through the graph.

Pivot attributes that are not written may stay linked.

`_ensure_writable(part, operation, *, force=False, pivot=None)` is the write gate, one function for every kind and verb (graphics review R1):

- It walks `part._iter_subtree()` for any linked node, so it catches a link set on a whole `Point` (e.g. `Polygon`'s vertex linked via `assign_formula(other_point)`) as well as one set on a single leaf `Attribute`. **Always check the whole part** (`_ensure_writable(self.p1, ...)`, not `_ensure_writable(self.p1.x, ...)`) — checking only a leaf misses links set at the parent level.
- It hops **up**: a whole-object link on an owner (`shape @= other`) drives every part, so it refuses too (SA1: the verb ran and the link snapped it back).
- It skips **property-backed pose anchors** (`["angle"]` / `["scale"]` on a Sprite, Point, Polygon, Text, Track): they are not position parts. A linked heading does not block a move (SA3).
- **`pivot=(x, y)`**: a point sitting on the verb's pivot is not moved by a turn, scale or mirror about it, so it is not written and may stay linked. Rotate / scale / mirror callers pass their pivot (SB3 / SC8: `Circle(center=lambda: ship.center, ...).rotate_by(5)` raised).
- It returns at once when the ownership tree's sticky `_needs_pull_invalidate` is off (no `@=` anywhere in the tree), which is cheaper than the old subtree walk on every call.

Property-backed pose fields have their own writers (`_pose_rotation_set` / `_pose_rotation_add` / `_pose_scale_set`): a linked `_PropertyAnchor` refuses there, so a verb never drops the write silently (SA2 = E6 = PB2); the anchor's own pull passes (`_writing`). Slot-backed headings are gated by `_ensure_writable(self["angle"])` in their verbs, and their link echoes into `_rotation` through the same writers, so the backstop checks property anchors only. Verbs check before they write: `_resolve_scale_apply` (every `scale_by`) and `_gate_pose_anchor` (the rotate entry of property-backed kinds) refuse a linked pose field, and a **whole-object link** on the actor, up front, and pass `force`.

A whole-object link drives whatever a copy carries: a Shape's geometry and pose (C7), a Point's position only (`_whole_link_carries_pose = False`: `dst @= src` follows the source and may still turn on itself).

A destroyed point refuses `_takein` (`c.center = …`, `p << xy` on a destroyed shape raised nothing and moved it; SA10).

**Check, then write** (graphics review R2). A verb runs every gate it needs before it writes anything, so a refusal leaves the actor exactly as it was: a Polygon gates every vertex before it moves one; `_mirror_geometry` gates every point and scalar first (Rect names its corners after the checks); RegularPolygon / Circle / Ellipse check the center or heading before writing a size; `point.handle = True` / `draggable = True` check before they show the point; `rect << box` reads the source before it adopts the model; `tag("a", 5)` checks every name before it claims one. A flip refuses a dead actor and a linked pose up front; its flag is set first (mirror code reads it) and put back if the mirror refuses. `show_handles()` skips every point of a shape linked as a whole (they are all driven). Guards: `test_refusal_atomic` (every public call × dead / junk / linked refusal, all reads and the registry before and after) and `TestLinkWriteGate` (no "half-applied" row).

Guard: `test_diff_link_write.TestLinkWriteGate` (every kind × link target × pose verb, judged by an unlinked twin: the parts the twin's verb changes are the parts it writes).

All geometric transforms (`move_by` / `move_to` / `rotate_*` / `scale_*`) use `_ensure_writable` on the Defining parts they write. Raw `Attribute` assignment (`=`) may still warn+unlink on its own; shape transforms do not rely on that path.

## Persistent drivers vs linked pose

Persistent drivers write pose every frame (or for a duration, or on every pointer event) without the author calling a one-shot transform each time. **Only a formula is exclusive; everything else composes, in either declaration order.** The rule it replaced ("at most one persistent driver per part") was enforced one way only: `resolve()` refused a clone's timed move started first, yet the same two lines swapped ran — and that order is the designed case (standing `resolve()` sweeps exactly the motion channel). Three pairs were order-dependent (timed move or tween vs `resolve()`, vs drag; timed rotate vs `wheel_rotate`). What decides this is *how* each driver writes:

| Kind | Drivers | Declared by | Parts it writes | How it writes |
|------|---------|-------------|-----------------|---------------|
| **Exclusive** | Formula | `field @=` | the linked node | computed — nothing else may write it |
| **Push** | Scheduler motion (timed `move_by` / `move_to` / `move_along`, timed rotate / scale), standing resolve nudges, pointer wheel | `…(time=)` / `resolve(a, b)` / `wheel_rotate=True` | claimed for the Handle's lifetime / `_parts_written_by_resolve()` (usually `center`) / `_parts_written_by_wheel_rotate()` (includes `self["angle"]` even when PropertyAnchor-backed) | adds a delta to whatever is there |
| **Placement** | `tween` on a part (`tween(c.center, …)`, `tween(c["angle"], …)`), pointer drag (`move_to(mouse + grab)` per pointer event), `=`, instant `move_to`, `confine` | `tween(...)` / `draggable=True` (or `on_drag_to` / `on_drag_over`) | claimed for the Handle's lifetime / `_parts_written_by_drag()` | sets an absolute value |

Pushes add up (a timed move under standing `resolve()` is swept and stops at the wall). A placement that runs every tick wins that tick (`tween(hero.center, …)` under `resolve()` goes through walls — placement). A formula is the only real exclusion: a linked node can be neither pushed nor placed.

**Policy** (order-independent by construction — the only check left is the formula check, eager at the call site in both directions):

| Case | Response |
|------|----------|
| Formula vs any other driver on overlapping parts (`@=` vs drag / wheel / tween / timed pose verb / `move_along` / resolve), either order | **Hard error** (`LinkedAttributeError`) at the second call. Timed rotate probes rotation at the call (`_probe_rotate_writable`), not on the first tick |
| Any two non-formula drivers (drag + motion, resolve + motion, wheel + timed rotate, …), either order | **Compose** — no refusal. `_PROCESS_CLAIM_REFUSING_OPS` is gone; do not reintroduce a one-way refusal (the bug class it created: outcome depended on which line ran first) |
| Same-kind re-declaration (`@=` over `@=`, second motion on the same pose key) | **Warn + replace** (or no-op if unchanged) |

`force=True` stays on **one-shot** transform calls (`move_to`, `rotate_by`, `tween(...)` creation, timed pose verbs) only — it is **not** accepted on persistent declarations (`draggable=`, `wheel_rotate=`, `resolve()`; `_PERSISTENT_DECLARATION_OPS`). Escape: explicit `unlink()` / `draggable=False` / `handle.cancel()` / `unresolve()`.

**Pointer hold.** The one pair that fights is a pointer hold vs a motion in flight: drag places only on pointer events, the motion writes every tick in between. So a hold **holds** the motion on the parts it writes: when the drag threshold is crossed (drag parts) or on the first wheel tick of the hold (wheel parts), every Handle claiming those parts (`process_claims_on` — all claims, not the first) is held, and so is a motion claimed on a held part later in the same hold (`claim_process_driver` → `_hold_if_on_held_part`). The hold ends — every held Handle runs again from where the shape is — on release **before** `on_drag_to` / `on_drop_by` (so a snap-back `move_to(home, time=)` there works; it replaces the shape's own motion with the usual same-kind warning), on `draggable = False` (immediately; release then fires no drag callbacks), and on destroy. The whole Handle is held, including a `face=True` rotation.

- **Why hold, not the alternatives.** Refusing in both orders breaks snap-back (`move_to(home, time=)` in `on_drag_to`); cancelling on grab destroys a patrol the author wrote; letting them fight is the silent drift (the shape wanders off the still cursor, the next pointer event snaps it back). Holding keeps what the author wrote and does what the screen suggests: a grabbed patrol stops while held and resumes from where it is dropped.
- **Held is not paused.** The gate is private (`Handle._held`, checked next to `_paused` in `_prepare_timed_handle`); `Handle.paused` / `pause()` / `resume()` stay the author's switch and never report or undo a hold. An author `resume()` during the hold takes effect at release; an author `pause()` during the hold survives it. Reusing `pause()` would let a pause-menu toggle (`if h.paused: h.resume()`) restart a held patrol under the cursor, undo the author's own `pause()` on release, and need bookkeeping of which pauses were the hold's.
- **State lives on the shape** (`_hold_parts` / `_hold_handles` in its `__dict__`; `hold_claims_on` / `release_hold` in `process.py`), so the `draggable` setter and registry destroy teardown can end the hold without the pointer manager. Destroy must end it itself: a held Handle never reaches `_claimed_target_dead()` in `_tick_tween`, so waiting for the next pointer event would leave it frozen.
- **Standing `resolve()` during a hold is unchanged:** drag is placement, so it is not swept (one pointer event can carry a body through a thin wall) and floor snap pulls a grounded held body back (an 8 DU lift is undone in one step). Only settle recovers overlap. Do not document "a held body stays out of walls". Follow-up, not implemented: skip floor snap for a held body; decide whether drag under `resolve()` should use the motion channel.

**Carry (motion + per-frame `move_by`).** A one-shot `move_by` in `update` while a `move_along` is in flight adds to the ride, in either order within the frame: the travel driver moves by its own per-tick delta and never overwrites the shape's position. This is the "carry" idiom of a camera-moves game (`group["tela"].move_by(dx, 0)` keeps a formation's path on screen while the camera travels). Do not make a motion Handle re-anchor to its start pose each tick: that would silently cancel every carry.

Tests: `tests/test_driver_composition.py` (every driver pair both orders; hold edges; messages; `TestCarry`: carried rider − uncarried twin == summed carry every frame, floating / anchored / forever-preset paths, both orders in the frame).

Shared wording: `driver_conflict_message(new=, subject=, part=, existing=, undo=)` in `state.py` (`motion_conflict_message` for a motion Handle). The subject is the actor that already owns the part, named by `entity_label` (`entity.py`): the line that made it (there are no author ids) (`the Sprite made at app.py:151`, `_site` captured in `_construct` for top-level actors by a `sys._getframe` walk — parts are named through their owner; ~0.5 µs per actor against ~6.7 µs for `traceback.extract_stack` and ~145 µs to construct a `Circle`, 2026-09-26 micro-bench), plus `(a clone of the one from line 121)` for a `clone()`. Never the class name alone, never `_auto_sprite2` (it appears nowhere in the author's file). A motion is named by the call as written (`Handle._claim_label`: `move_by(time=2, loops="forever") pushes it`, `tween(time=1) sets it`); a forever motion drops "or wait for the motion to finish". Resolve refusals name the group (`, group "heroi"`) and every pair (`resolve_calls_for` → `unresolve("heroi", ["plataforma", "parede"])`); `resolve()` checks every member of every side before registering any pair (all-or-nothing). Overlap uses `_link_overlaps_part` (whole subtree + owner chain). Property-anchored `angle` / `scale` are listed as FieldRefs in `_parts_written_by_*` — no per-family special case. **Anchor** is just a permanently-draggable Point (`_parts_written_by_drag() == (self,)`); inbound links fall out of the generic check.

**Scheduler-motion Handle vs its target's death.** A tween/`move_along`
Handle's `owner` (who *scheduled* the work — may be a Director/mode-context
actor) and its **target** (the shape whose part is actually being written)
can differ, e.g. `wasp.move_to(..., time=)` called from inside a Director's
mode is mode-scoped on the Director but writes `wasp`'s pose. `Handle._tick_tween`
already auto-cancels when its `owner` dies (`_live_owner()`); it separately
carries a `weakref` to the **target** captured at tween-creation time
(`Handle._target_ref`, set from `_start_tween(..., target=shape)` — plumbed
through `timed_move_to` / `timed_move_by` / `timed_rotate_to` / `timed_rotate_by`
/ `timed_scale_to` / `timed_scale_by` / the `move_along` ride) and cancels on
the next tick if that target is destroyed, even when `owner` is someone else
(or `None` / script-scoped) and is still alive. Do **not** try to resolve the
target by walking a claimed Container's `._owner` chain instead — `destroy()`
clears a Point's `._owner` back-reference to `None` (to break GC cycles), so
that walk always fails once destroy has already happened; the weakref must be
captured *before* any possible destroy. If a mode is `await`ing that Handle,
this cancellation raises `Cancelled` into it — see [Actors Design.md —
Silent-death gap](Actors%20Design.md#mode-enter--exit). Tests:
`tests/test_process.py` (`test_other_owned_tween_cancels_when_target_destroyed`,
`test_other_owned_forever_tween_stops_when_target_destroyed`).

**Scheduler-motion claim vs a cold `center` Derivate.** `timed_move_to` /
`timed_move_by` / `timed_move_along` need (a) a stable dict key to name the
tween-key slot they claim (for same-kind-replace / conflict detection) and
(b) the actual Defining part(s) to hand to `claim_process_driver` so a
concurrent `@=` on them raises. Both used to just read `shape.center`
(`id(getattr(shape, "center", shape))`). That is wrong whenever `.center` is
a **cold Derivate** for the shape's current model — e.g. any point-based
`Line` model (`POINT_POINT`, `POINT_VEC`, …; only the home
`CENTER_LENGTH_ANGLE` model keeps `center` Defining) or a free `Polygon`
(`.center` is a read-only alias for `.centroid`, always Derivate — vertices
are Defining). Two separate bugs from that one read:

1. **Wakes a Derivate that was never touched.** Reading `.center` on a cold
   Derivate materializes it (`_derivate_live = True`, `_flag_pull_consumers()`,
   `_materialize_derivate_part()` — Reactive Design A1-A3), permanently
   costing the shape its pose fast path just to compute a dict key, even
   though the move never reads or writes `.center` at all.
2. **Protects the wrong part.** Claiming `.center` does not stop a
   concurrent `line.p1 @= ...` (or `poly.points[0] @= ...`) during the
   tween — that write silently fights the tween instead of raising the
   loud `LinkedAttributeError` every other persistent driver gets, because
   the part actually written (`p1`/`p2`, a vertex) was never claimed.

Fixed by two helpers in `process.py`, used at all `timed_move_*` call sites:

- **`_center_pose_key(shape)`** resolves the tween-key identity without ever
  triggering the descriptor protocol on a not-yet-materialized name. It
  walks `type(shape).__mro__` and inspects `klass.__dict__.get("center")` —
  a plain dict lookup — to classify `.center` as a `ContainerSlot` (normal
  case) or a `property` (the Polygon-family `center`/`centroid` alias),
  then only reads it live if either the Container already exists in
  `shape.__dict__` (a prior touch — free to read) or it is Defining for
  this instance right now (`_defining_part_names`, or the class-level
  `ContainerSlot.field_type` when the shape has no dynamic model).
  Otherwise it keys on `id(shape)` instead of waking the Derivate — the
  accepted trade is that a same-tick `tween(shape.center, ...)` targeting a
  still-untouched `center` will not share this key with a same-tick
  `move_to(...)` (rare).

  **Pitfall this avoided:** `hasattr(shape, "center")` /
  `hasattr(type(shape), "centroid")` look like safe existence probes but
  are not. `hasattr`/`getattr`-with-default swallow *any* `AttributeError`
  raised inside `__get__` — including the one `ContainerSlot.__get__`
  raises internally when called with `instance=None` (i.e. probed on the
  *class*, since `None.__dict__` fails) — so `hasattr(type(shape),
  "centroid")` returns `False` even though `Polygon` unconditionally
  declares `centroid = ContainerSlot(...)`. And `hasattr(instance, name)`
  on an instance where the Container is not yet materialized *is* the
  descriptor `__get__` call that materializes it — the exact hazard this
  fix exists to avoid. Never probe a `ContainerSlot`-backed name with
  `hasattr`/`getattr` on an instance or its class; walk `__mro__.__dict__`
  instead.
- **`_move_claim_targets(shape)`** reuses `shape._parts_written_by_drag()`
  (the same "what does `_move_to`/`_move_by` actually write" answer already
  used to guard `draggable=True`) to compute `claim_targets`, falling back
  to `(getattr(shape, "center", shape),)` only for shapes without that
  override (e.g. `SpatialFx` — not a `Shape` — unchanged from before).

Caveat not fixed by this change: `Polygon._move_to` (its own one-shot-move
implementation, unrelated to the scheduler-motion path above) reads
`get_xy(self.centroid, bare=True)` directly, so a free `Polygon`'s
`centroid` still materializes on the *first* `move_to`/`move_by` call
regardless of whether it went through a timed tween — a separate,
pre-existing gap in `Polygon`'s geometry, not introduced or widened here.
Tests: `tests/test_process.py`
(`test_move_to_point_line_never_wakes_cold_center`,
`test_link_mid_move_to_raises_on_line_p1_not_center`,
`test_move_to_center_length_angle_line_still_claims_center`,
`test_link_mid_move_to_raises_on_polygon_vertex_not_centroid`,
`test_move_along_point_line_never_wakes_cold_center`).

Only the parts each driver would write are protected (e.g. a linked `radius` does not block dragging a `Circle`). Outbound links *to* the shape remain fine.

One-shot transforms (`move_by` / `move_to` / `rotate_*` / `scale_*`) still use `_ensure_writable` (raise by default; `force=True` warns+unlinks). That helper also refuses an active process claim on the part.


# Batching and external dependents
==================================

`@batch_update_self` / `@batch_update_attrs` suppress per-leaf `update()` cycles. Leaf Attribute writes during batch still **`mark_dirty`**, so dependents are invalidated; a later read pulls fresh values. Under the run-loop frame batch, effects still wait for `flush()`.

Under an outer `no_update` (as in `_resolve_structural` / `_resolve_link`), `@batch_update_attrs` must **not** `getattr` every named attr — that would force-create cold Derivate slots. Nested decorators skip the redundant subtree walk when the owner is already suppressing.

Parts created *during* a batch inherit `_in_batch_update=True`; restore clears those orphans so Defining inputs created inside constructor `with self.batch_update():` do not stay stuck suppressing `update()` forever.

`.takein(...)` (as opposed to `=` / `ContainerSlot.__set__`) never raises `DerivedAttributeError`, regardless of `field_type` — it's the mechanism every `_update_impl_*` uses to write Derivate outputs. The author operator `<<` is not that mechanism: it refuses a computed part like `=` does (`rect.top_right << (1, 2)` used to overwrite the point and leave the rect where it was).

**Refusing a computed field.** Every refusal (`=`, `.x =`, `@=`, `<<` on a
computed field or below one) goes through one hook,
`Container._derived_field_message(name, operation, value, part)`, which says
what the field is computed from — this instance's model inputs, placement
points first (`_model_inputs`), or a class's `_derived_from` (`"path"` on
Track, `"points"` on a free Polygon; RegularPolygon resets it) — and a fix
that works:

- a computed **point** of an actor: move the actor so the point lands where
  the author wrote it — `rect.move_to(1, 2, about=rect.top_right)` (one axis:
  `rect.move_to(1, rect.top_right.y, about=rect.top_right)`);
- anything else: change the inputs, or build with the field as a keyword when
  the constructor takes it (`Line(..., length=...)`; checked against the
  signature, never guessed);
- a link: link one of the inputs instead.

Classes word their own case: `Vec2` (`v << vec_from_angle(...)`), Track
`cursor` (moves with `u`). A derived `angle` is not refused (it turns the
actor), and a reversed Track view forwards its writes to the host. Guard:
`test_derivate_readonly.TestDerivedFieldMessages` — every model, field and
form raises with this wording and changes nothing, and each suggested
`move_to` is run and must land the point.


# Draw policy
=============

| Approach | Use when |
|----------|----------|
| **CTM local frame** (Rect, Square, Ellipse, RegularPolygon) | Shape has a clear center/size/rotation (or equivalent) pose; world Derivates are only for links/queries |
| **World Attributes** (Line, Circle, free Polygon) | Paint naturally reads Defining endpoints / disk / vertices |

Rules:

1. Attributes remain canonical for links and materialize-on-access.
2. CTM must be driven by the same numbers `_oriented_frame` / model math would use for Derivates — never a divergent cached matrix.
3. Linking or reading a Derivate keeps it live; draw alone must not force the full Derivate set hot.


# Pointer interaction (click / drag / drop)
==========================================

Pointer is a **Graphic** API (Shape and Sprite, including Svg). Implementations
live on `Shape` and are published onto `Graphic` so Sprite shares them.
`SpatialFx` and bare `Entity` do not opt in (`@click(rain)` is a `TypeError`).
Hit order for press / scroll:

1. **Capturing UI widgets** (Sliders, Buttons, …)
2. **Interactive Graphics on reserved ``ui``** (view space, after widgets)
3. **World Graphics** (camera space; layers high-z→low-z, reverse draw order
   within each layer), then script-level `CanvasManager` callbacks

Decorative HUD captions are ``Text`` on ``ui`` (not widgets) — they do not
enter the widget hit list. ``Text(..., background=)`` is visual only.
Optional ``width=`` fixes the layout box (overflow clips; no wrap). ``\n`` is a
hard break (height is n × line metrics). ``align=`` pins HUD ``x1`` / places
glyphs in a fixed box. Content-sized (no ``width=``) is the default Label
contract. The HUD column does not reflow when the line count changes after
construct.
Only Graphics registered as interactive are hit-tested (cost scales with
interactive count, not total registry size).

## Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `clickable` | `False` | Eligible for click press/release |
| `draggable` | `False` | Eligible to be dragged with left button |
| `droppable` | `False` | Eligible as a drop target under another dragged Graphic |
| `wheel_rotate` | `False` | While mouse is **held** on this Graphic, wheel rotates it about its center |

Assigning a callback also sets the matching flag; clearing the callback to
`None` clears the flag:

| Callback | Sets |
|----------|------|
| `on_click` | `clickable` |
| `on_drag_to` / `on_drag_over` | `draggable` (True if either is set) |
| `on_drop_by` | `droppable` |
| `on_hover` / `on_hover_exit` | no flag — joins the interactive list as a **hover-only** target (see [Hover](#hover-pointer_hover-hover--hover_exit)) |

Every pointer handler is validated where it is set (setter, constructor,
decorator: `validate.check_pointer_handler`): callable, and needing at most the
positional payload Scena passes. It is called through `call_truncated`, so it
may declare fewer (`def f():` is fine; `def f(*args)` gets everything).

**Payload rule (every author hook):** Scena passes a value only to a parameter
with **no default** (`validate.payload_arity`). A default means the author
supplies it: `lambda tool=tool: choose(tool)` in a loop, `app.save(then=None)`,
`jump(height=10)` and `functools.partial(choose, tool)` all get nothing;
`def pressed(b):` gets the target. The cost: `def pressed(b=None):` gets
nothing either. Pointer handlers, `@collide`, `on_done`, timers, `on_update`,
`@on_change` and the module-level frame callbacks all share this one counter;
do not add another (three drifted apart: PH5).

`wheel_rotate` is independent (set explicitly). Interactive registry membership is
`clickable or draggable or droppable`.

Setting `draggable` / `wheel_rotate` when the parts those gestures would write are
linked raises `LinkedAttributeError`; linking those parts afterward on a Graphic
that already has the flag raises the same way. Standing `resolve()` and in-flight
`tween` / `move_along` join the same persistent-driver rule. See
[Persistent drivers vs linked pose](#persistent-drivers-vs-linked-pose).

## Hit-testing

`contains_point(x, y)` **or** `contains_point(p)` is design-space coords (same
space as `mouse.x` / `mouse.y`). `p` is Point, Vec2, `(x, y)`, mouse, or an
object with `.center` / `.x`/`.y`. This is **pointer / draw geometry** — the
same test `@click` / `pointer_hover` use — not the collision hitbox
(`collision.query_point`). Subclasses implement `_hit_test_xy`; the public
method unpacks author args. Sprite samples the **current frame's alpha**
(oriented visual rect first; a transparent texel misses), not the baked
hitbox. Circle's pointer test follows the filled arc (pie or chord);
`intersections` stays the full circumference. Rect `corner_radius` rounds
the pointer fill; collision stays the oriented box.

| Kind | Test |
|------|------|
| Rect / Square | Inverse-rotate into local frame via `_oriented_frame()`. `corner_radius == 0`: box, with `1e-6` slack. Positive: the rounded fill (inner cross or a fillet), same clamp as paint. Collision stays the box |
| Circle | Filled arc (`abs(radius)`): full disk, pie, or chord segment. `spread` of 0 misses. Collision matches. Outline queries ignore `angle`/`spread` |
| Ellipse | Inverse-rotate + unit-ellipse inequality |
| Line | Distance to segment ≤ `max(line_width/2, HIT_PADDING)` |
| Track | Distance to stroked window ≤ `max(4, line_width/2 + 3)` (`begin`/`end` trim) |
| Polygon / RegularPolygon / EquilateralTriangle | Point-in-polygon over `.points` |
| Point | Disk of radius `HANDLE_HOVER_RADIUS` when handle/draggable, else `HIT_PADDING` |
| Anchor | Same as Point handle (subclass) |
| Sprite / Svg | Current-frame alpha inside the oriented visual rect (tilt included). Not the hitbox |
| Base `Shape` | Always miss |

Z-order: capturing widgets first; then ``ui`` Graphics (view); then world
layers high-z→low-z (`top` before `default`; disabled layers skipped); within a
layer, reverse of the **draw** list (`objects`), so later-drawn Graphics win.
Invisible Graphics are skipped at hit time. `move_to_front()` / `move_to_back()`
reorder within a layer. HUD ``Text`` is not a widget — only interactive
Graphics enroll in the hit lists.

Press hits only `clickable` or `draggable` Graphics. Drop / drag-over hits only
`droppable` Graphics (the dragged Graphic is excluded). Hover hits pressable
Graphics **and** Graphics with a hover handler; a hover-only Graphic is
transparent to presses.

Hit order per layer sorts the layer's `_interactive` members by `_draw_index`
(O(k log k), k = interactive members) instead of walking every object on the
layer. `_draw_index` must stay truthful: `Graphic.__init__` must not reset it
after registration (it did, silently sending every hit order and every O(1)
tombstone through the slow path).

## Click

A click fires only when press **and** release both land inside the same Graphic
(same rule as widgets). Handler: `on_click(shape)`, run through the engine hook
`_fire_click()` (a subclass adds behavior there, e.g. a click sound).

### Press lifecycle (`pointer_pressed`)

`pointer_pressed` (Graphic and widget, read-only) is **held on this target and
the pointer over it** — exactly "a release here would click". It flips False
when the pointer leaves, True when it comes back; a drag keeps it True (the
shape follows the pointer). Hook: `_on_pointer_pressed_changed()`.

`ShapeInteractionManager._set_pressed` is the **only writer** of
`_pressed_shape` and the press bit. A press ends on release and is **dropped
eagerly** (no release callbacks, hold ended, `_drop_press`) when the held
shape:

- is destroyed (`forget_destroyed`, synchronous in registry teardown);
- is hidden, parked, or stops being pressable — `_sync_interactive_registry`
  (every flag / visibility / park change) calls
  `forget_pointer_target(shape)` on every pointer manager; it runs **no author
  code** (the hover exit waits for the next `step_hover`);
- loses `draggable` mid-drag;
- or a modal widget opens (`WidgetManager.push_modal` drops it).

> **Warning — a press must not outlive its target.** Before 2026-10-02 the
> press was only noticed on the next pointer event: a modal opened mid-press
> left a stale `_pressed_shape` that kept hover and stole the next release (a
> click on a shape the pointer merely crossed, the script's click eaten).
> New press state goes through `_set_pressed`; new ways to hide / disable a
> Graphic must reach `_sync_interactive_registry`. Tests:
> `tests/test_shape_interaction.py` (`TestPointerPressed`),
> `tests/test_script_callbacks.py` (`TestModalDropsShapePress`).

**Swallowed press.** A Graphic whose engine hook `_accepts_press()` returns
False (a disabled `SpriteButton`) still takes the press — nothing underneath,
nor the script, gets it or its release — but there is no press bit, no drag,
no wheel and no click. `_accepts_press()` is checked again at release, so
disabling between press and release cancels the click. Same contract as a
disabled widget (`_SWALLOWED_PRESS`).

## Drag and drop

State machine (left button):

1. Press on a pressable Graphic → pending
2. Move past a small Manhattan threshold **and** `draggable` → dragging (`move_to` with grab offset). The grab offset is taken from the shape's center **at the crossing** (`center_now − press_xy`), not at the press: a motion may have carried the shape meanwhile, and the press-time offset would snap it back. At the crossing the hold starts: motion on the drag parts is held ([Pointer hold](#persistent-drivers-vs-linked-pose)). A wheel tick while pressed holds motion on the wheel parts
3. Release without having dragged → click if `clickable` and still inside
4. Release while dragging → the hold ends first, then `on_drag_to` on the dragged Graphic; if a droppable is under the pointer, also `on_drop_by` on that target
5. `draggable = False` or destroy mid-drag → the drag ends there (hold ended at once, the shape stops following, release fires no drag callbacks). Before this, the drag kept going after `draggable = False` and the next pointer event after a destroy raised `DestroyedError` (`ShapeInteractionManager._press_lost` / `_drop_press`)

While dragging, each move calls `on_drag_over` on the dragged Graphic with the
current droppable under the pointer (or `None`).

Shared callback signature for drag/drop events:

```text
(from_shape, to_shape, pos)
```

| Event | Fires on | When |
|-------|----------|------|
| `drag_to` | dragged Graphic (`from_shape`) | mouse release after a drag |
| `drag_over` | dragged Graphic (`from_shape`) | each move during a drag |
| `drop_by` | drop target (`to_shape`) | mouse release over a droppable |

`pos` is `(x, y)` in design space at the event. `to_shape` may be `None` for
`drag_to` / `drag_over` when nothing droppable is under the pointer.

## Decorators (`scena.interaction`)

Sugar over the callback attributes. Accept individual Graphics (`Shape` or
`Sprite`), widgets where the gesture makes sense, and/or `group['name']`
(`GroupOperator` live view — **members present at decoration time** are
registered). Last registration wins per target.

Widget policy — one rule for direct arguments and group members, checked for
every target **before** any is touched (no half-applied decorator):

| Decorator | Graphic | `Button` | other widgets |
|---|---|---|---|
| `@click` | yes | yes (`button.on_click`) | `TypeError` naming `@on_change(widget.data)` |
| `@hover` / `@hover_exit` | yes | yes | yes |
| `@drag_to` / `@drag_over` / `@drop_by` | yes | `TypeError` | `TypeError` |

Before this, `@click(group)` silently skipped widgets and `@click(button)`
raised. `on_click` lives on `Button` only: `checkbox.on_click = f` raises (it
used to be stored and never called). Button calls `call_truncated(fn,
button)` — the same rule as Graphics — so one handler serves both. The
payload is positional, never passed by keyword: `button` already means the
mouse button (`mouse.press(button)`).

```python
@click(c1, c2, reset_button)   # or @click(group['buttons'])
def on_click(target): ...

@hover(group['cards'])
def lit(card): ...

@hover_exit(group['cards'])
def unlit(card): ...

@drag_to(token)
def on_dragged(from_shape, to_shape, pos): ...

@drag_over(token)
def on_hovering(from_shape, to_shape, pos): ...

@drop_by(zone)
def on_receive(from_shape, to_shape, pos): ...
```

## Autorotate

```python
shape.wheel_rotate = True
```

**Hold to rotate, drag to move.** While the left button is held on a
`wheel_rotate` Graphic (pending press *or* mid-drag), the mouse wheel rotates it
about its center — no need to move the pointer first. Scroll-up rotates
counter-clockwise (`rotate_by(+yoffset * degrees(0.04))` ≈ 2.3° per typical GLFW notch).
Widgets with ``captures_pointer`` still consume scroll first when under the
cursor; HUD ``Text`` is not a widget.

If the user scrolls while holding and then releases without having dragged,
`on_click` is not fired (wheel = rotate interaction, not a click).

## Hover (`pointer_hover`, `@hover` / `@hover_exit`)

**One hover target**, exclusive across spaces, in hit order: widget (view) →
`ui` Graphic (view) → world Graphic. A Graphic is eligible when it is drawn
and pressable (`clickable` / `draggable`) or carries a hover handler
(`on_hover` / `on_hover_exit`). Decoration with none of these is transparent
and its `pointer_hover` stays False — a label on a button never steals hover.
Droppable-only does not get hover. A modal widget clears every hover. While a
Graphic is pressed or dragged it keeps hover (affordance).

`pointer_hover` (Graphic and widget) is the level; `on_hover(target)` /
`on_hover_exit(target)` are the edges. Every enter is followed by exactly one
exit — pointer left, hidden, destroyed, no longer a target, covered by a
widget, modal opened. Destroy fires the exit synchronously, while the object
still exists (registry teardown → `ShapeInteractionManager.forget_destroyed`,
next to collision's `forget_destroyed_item`). The target is committed before
handlers run; a raising handler propagates with the edge consumed.

**Hover-only targets are click-transparent.** A Graphic with only hover
handlers joins hover resolution, but presses fall through to the pressable
below (or to the script's `on_mouse_click`). Adding a tooltip never breaks a
click. The cost: where a hover-only shape overlaps a clickable one, the top one
is hovered while the click goes below.

**When it is resolved (tiered, once per frame).** Mouse moves only record the
pointer (`note_pointer`); `_sync_pointer_level` records view + world every
frame (so a camera pan under a still cursor counts as motion).
`ScenaFramework._step_hover` → `step_hover(widget, modal)` runs after
`@leave_playfield`, before `flush` (same window as collision handlers):

- a **full hit test** when the view/world pointer, `registry._pointer_epoch`
  (bumped by every `set_interactive` — i.e. every flag / visibility / handler
  change — interactive removal, `move_to_front` / `move_to_back`) or
  `registry.pointer_layers_signature()` (layer order + visibility) changed, or
  the current target stopped being valid;
- otherwise **one `contains_point`** on the current target (still alive, drawn,
  eligible, under the pointer); with no target, nothing.

Measured (headless, 2026-09-30): a still frame costs 1–3 µs even with 1200
clickable cells; a frame where the pointer moved runs one full test, ≈ 3 µs
per interactive shape (1200 cells ≈ 4 ms — mostly `contains_point` and flag
reads, the same cost the old code paid on *every* move event). Many move
events in one frame cost one hit test. A spatial broad phase for the full test
is the next lever if big clickable grids matter.

> **Warning — the accepted trade-off.** Exits are always immediate; **entries
> wait for pointer motion**. A *different* shape sliding under a still cursor
> (or on top of the hovered one) is not hovered until the pointer next moves,
> or the target set changes. Do not "fix" this by resolving every frame
> unconditionally without re-measuring big grids; do not move hover back into
> the mouse-move callback either — that is how hover went stale (bug class
> "event-driven level state goes stale", Testing Design).

`Anchor` uses the same bit for grab affordance (enlarge + ring) only when a
click/drag would actually hit that Anchor. Tests: `tests/test_pointer_hover.py`,
`tests/test_hyp_hover.py` (state machine: exit guarantee, tiered == brute
force, edges alternate), `tests/test_sys_hover.py` (the real frame body: hover
before `flush`, widget hand-off).

## Anchor

`Anchor(x, y, color=…)` — sugar for a Point with `handle=True`:

- Same marker glyph as a visible Point (radius 8, alpha 0.5, fill only)
- `color=` forwards to Point (author tint); omit → role-auto handle red
- Always `handle` / draggable, on layer `top` while shown
- Pose stays free via the generic persistent-driver rule (always `draggable`;
  inbound `@=` overlaps `_parts_written_by_drag() == (self,)`)
  — outbound links *to* the Anchor remain fine
- `center` aliases self (Point); `x` / `y` are the Point slots
- When it is the topmost pressable under the cursor (hover or held): thin
  outer ring in a lighter tone of the fill (`Color.lighter`)

```python
a = Anchor(100, 100)
b = Anchor(200, 150, color="cyan")
Line(p1=lambda: a.center, p2=lambda: b.center)  # OK — links *to* the Anchors
# Line(p1=a.center, …) copies once: the line does not follow the drag

line = Line(p1=(0, 0), p2=(100, 0))
line.show_handles()  # drag endpoints in place
```

## Z-order helpers

```python
shape.move_to_front()   # end of layer._objects (topmost within layer)
shape.move_to_back()    # start of layer._objects
```

## Smoke test / unit tests

See `scripts/smoke/interact.py` for an interactive smoke of click, group
registration, token→zone drag/drop, drag gallery (with `wheel_rotate`), Anchors,
and `move_to_front`.

Headless coverage lives in `tests/test_shape_interaction.py` (hit-test, click/
drag/drop state machine, hover, decorators, Anchor) and
`tests/test_shapes.TestInteractiveLinkInvariant` (draggable/wheel_rotate vs
linked pose).


# Author math helpers
=====================

Standalone helpers in [`scena/shapes.py`](../scena/shapes.py) (exported next to
geometry queries). These take **positions**, not Shape methods:

| Function | Returns | Role |
|----------|---------|------|
| `distance(p1, p2)` | `float` | Euclidean distance (also `Point.distance` / `Vec2.distance`) |
| `heading(origin, target)` | `float` | Bearing in degrees, 0 = +x, −180…180 (also `Point.heading`) |
| `middle_point(p1, p2, weight=0.5)` | `(x, y)` | Weighted midpoint tuple |
| `nearest(origin, items, *, within=, where=)` | item or `None` | Closest item by center / `.x`/`.y`; not a Shape method |

`distance` / `heading` / `middle_point` / `nearest` accept Point, Vec2, `(x, y)`,
mouse, or entities with `.center` (Shape, Sprite). `heading` is from → to;
coincident positions → `0`. Do not confuse with `Handle.heading` (tween travel
this tick) or `Vec2.angle_to` (signed angle between two direction vectors).
Items for `nearest` may be a list, `group["wasp"]`, or `poly.points`. Ties:
first wins. Fleet spelling: `group["wasp"].nearest(origin, where=, within=)` —
same metric, implemented via the standalone helper. Do not confuse with
`closest_point` (filled-body projection — see Geometry queries below).


# Geometry queries
==================

Author helpers in [`scena/geom.py`](../scena/geom.py) (exported next to
`middle_point` / `distance` / `heading` / `nearest`):

| Function | Returns | Role |
|----------|---------|------|
| `intersections(a, b)` | `list[(x, y)]` | Outline crossings **now** (empty if none) |
| `intersection(a, b, i=0)` | always `(x, y)` | Slot for constructors / `@=` |
| `closest_point(shape, p)` | always `(x, y)` | Filled-body projection toward `p` |

**Allowlist:** `Line`, `Circle`, `Ellipse`, `Rect`, `Square`, `Polygon`, `RegularPolygon`, `EquilateralTriangle`, `Box`.
Anything else → `TypeError`. Out of scope: `Point` (no outline), `Track` (a path, not one closed outline), Sprite (pixel silhouette), SpatialFx (not geometry), arcs, stroke-aware hits.

Adding a type to `_allowlist_types()` requires the matrix test to pass and both doc lists to match (enforced by `TestAllowlistDocs`).

**Outline vs overlap vs hit-test**

- Contours cross → `intersections` (a circle *inside* a square with no touch → `[]`).
- Filled bodies overlap → `@collide` / `CollisionInfo` ([Collision Design.md](Collision%20Design.md)).
- Pixel inside (pointer / draw geometry)? → `contains_point` (same test as `@click`). Hitbox at a point → `collision.query_point`.
- Nearest point on the filled body → `closest_point` (inside → `p` itself, except `Line`). `p` is the same position family as `distance` (Point, Vec2, `(x, y)`, Graphic, mouse).

`Line` is the segment `p1→p2` (ignore `line_width`). `Circle` is the full
circumference (ignore `angle`/`spread`). `Ellipse` is the full rotated outline
from `_oriented_frame`; a collapsed ellipse (either axis `0`) is its major-axis
segment. Rect/Square/Box use the oriented box edges (the outline ignores
`corner_radius`; the pointer follows it).

**Order.** A `Line` in the pair sorts hits along that segment (`p1→p2`; if both
are lines, along the first). Two circles keep left-then-right of the centre
axis. Otherwise, if the first shape is a `Circle` or `Ellipse`, hits run from
its local +x toward local +y (the same sense as `angle`). Otherwise hits
run along the first shape's vertices from `verts[0]`. A circle has no vertex
list, so `intersections(circle, polygon)` used to stay in the polygon's edge
order; it now follows θ on the circle.

**Method.** A conic (circle or ellipse) against a segment is exact in the
ellipse's unit frame (the segment stays a segment; reuse the circle–segment
kernel). Circle × circle stays closed-form. Circle × ellipse and ellipse ×
ellipse sample θ (~96 steps) on the smaller outline and refine sign changes;
a tangency (no sign change) is one point when it falls within `_DEDUP_EPS`.
At most four real points — the same list as any other pair. `closest_point`
on an ellipse bisects the point-to-ellipse distance (inside, including the
centre, returns `p` itself). A collapsed ellipse is its major-axis segment,
so the unit-frame divide never sees a zero axis.

`intersection` never throws for a missing crossing: index into the current list,
or the last hit (tangent fills slots 0 and 1), or a stand-in near the pair.
Live chord pattern:

```python
Line(p1=lambda: intersection(c1, c2, 0), p2=lambda: intersection(c1, c2, 1))
```

`Shape.visible` is a plain property, not an Attribute — hide a vanishing chord in
`update` (`chord.visible = len(intersections(...)) == 2`), not with `@=`.

Tests: `tests/test_geom.py`. Smoke: `scripts/smoke/geom.py`. Author: [Guia da API](../docs/pt/guide/index.html)#comecar-geom.


# Deferred
===========================

- Non-uniform scale (`scale_x` / `scale_y`) — watch stroke under non-uniform CTM if added
- Non-left mouse buttons for shape click/drag
- `Polygon`/`RegularPolygon` self-intersection / convexity validation (currently unchecked)
- Rounded corners on `Polygon` / `RegularPolygon` / `EquilateralTriangle` (Rect/Square pointer follows `corner_radius`; collision stays the box)
- Further laziness for RegularPolygon vertices (today eagerly placed; CTM already avoids reading them for paint)
- Freeform `Polygon` O(n) `rotate_by` / `scale_by` via home-vertices + Derivate world verts — independent of reactive `angle` / `scale`; same family as the RegularPolygon flat-cost rotate already shipped
- Collision pipeline → [Collision Design.md](Collision%20Design.md)


