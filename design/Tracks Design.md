# Tracks Design

`Track` is one `Shape`: a drawable curve (invisible by default, like `Point`) and
the motion track for `move_along`. **Happy path** — pick one row. Hub:
[Scena Design.md](Scena%20Design.md). Geometry models:
[Shapes Design.md](Shapes%20Design.md). Tweens:
[Actors Design.md](Actors%20Design.md). Collision channel:
[Collision Design.md — Motion vs placement](Collision%20Design.md#motion-vs-placement). Author catalog:
[Guia da API](../docs/pt/guide/index.html#shape-track) and
[Mover](../docs/pt/guide/index.html#mover-move-along).

Today’s baseline — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| What a Track is / anchored vs floating | [One class](#one-class), [Anchored vs floating](#anchored-vs-floating) |
| Construction / presets / `Track()` | [Construction](#construction) |
| Bake + pose | [Representation](#representation) |
| `move_along` | [Travel](#travel) |
| Draw window (`begin` / `end`) | [Draw window](#draw-window-begin--end) |
| Stroke collision (arc wall / ring) | [Collision](#collision) |
| Modifiers / overlay / `cursor` | [Modifiers](#modifiers), [Overlay](#overlay), [cursor / u](#cursor--u) |
| Locating code | [Router](#router) |

## Use

1. Pick one jump-box row.
2. Read that section only. Treat fences there as current constraints.
3. Open **Start** in the router if the section is not enough.
4. Stop.

## Router

| Need | Start | Also | Design (if needed) |
| --- | --- | --- | --- |
| `Track` / presets / `at(u)` / `begin`/`end` | `track.py` | `curves.py` (`subpolyline`) | this file |
| Flatten / arc-length / `smooth=` | `curves.py` | — | this file |
| `move_along` / `loops=` / `face=` | `process.py` (`timed_move_along`) | `shapes.py` (`Shape.move_along`) | [Actors Design.md](Actors%20Design.md) |
| Stroke collision / arc wall | `collision.py` (`_track_stroke_prims`) | `track.py` (`_collision_pose_extra`) | [Collision](#collision), [Collision Design.md](Collision%20Design.md) |
| Debug overlay | `track.py` (`show_tracks`, `draw_track_overlay`) | `orchestration.py` | this file |
| Motion vs walls | `process.py` (deltas) | `collision.py` (`note_collider_motion`) | [Collision Design.md — Motion vs placement](Collision%20Design.md#motion-vs-placement) |

**Do not slurp:** `track.py`, `process.py`.

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| Anchored vs floating Track | where the **track** lives | collision placement vs motion |
| `move_along` | always **motion** (`_move_by` + `note_collider_motion`) | `center @= cursor` (placement) |
| `path.reversed()` | O(1) view of the host tables and of the host `begin`/`end` window (hit, draw, and collision follow each rebake; same ink as the host) | `span=(1, 0)` (this trip only) |
| `begin` / `end` | **stroke** window (draw + hit-test + collision) | `move_along(..., span=)` / `Circle(angle, spread)` / `.length` / `at(u)` / overlay |
| Track collider | stroke tube (thin OBBs, `line_width`) | filled disk / `Circle(angle, spread)` |
| Motion-only Track | not enrolled (default) | enrolled wall (`@collide` / `resolve` / `collidable=True`) |
| `zigzag()` / `orbit()` / `wander()` | in-place, return `self` | a new Track (`reversed()` is the view) |
| `Track()` | `Track.eight()` | a unique zigzag default |
| `points=` | world-space positions | `vectors=` (relative steps) |
| `center=` on a centered preset | focal / middle pose | `p1=` / `start=` (started presets) |
| `p1=` on `Track.line` | plants `u=0` | `.center` (geometric middle) |
| `time=` on `move_along` | **one lap** | whole-run duration when `loops="forever"` |
| `speed=` on `move_along` | units per second along the track; one lap lasts `length × \|span1 − span0\| / speed`, read at the call | a live rate that follows a growing track |
| `move_along(point)` | TypeError — slide with `move_to(..., time=)` | a Track / Shape / preset string |
| `History` / `Contrail` | live stamp buffer (+ optional polyline) | a Track / `points=` path definition |

# One class

`Track(Shape)` is the missing “path” in the class tree. There is no second
motion-track type and no `Shape.path` property — `Track(hexagon)` is the
conversion. Any `Shape` is travelable: `bug.move_along(hexagon, time=4)`.

Invisible until styled (`color=` / `visual=` / `line_width=` / `visible=True`), same as `Point`.
Those are constructor keywords: a style set after construction (`t.color = …`)
does not put an invisible track on a layer (the lifetime rule below); the Guia's
`color` row says to write `t.visible = True` (showcase A1, 2026-10-23).
Styling decides the lifetime, `visible` only the drawing: a styled track that
is hidden (`visible = False`, or `visible=False` in the constructor) stays on
its layer like a hidden `Rect` — an invisible collision band (a road asked
with `query_point`, a sensor) is held by the canvas. Only a track that
`visible = True` promoted goes back to a bare motion path when hidden.

# Anchored vs floating

Two independent knobs:

| Question | Owner |
| --- | --- |
| Does this track's position bind future `move_along` riders? | `Track.is_floating` — a property of the **target** |
| Where does this one floating ride's `u0` sample land? | `move_along(..., at=)` — a property of **this ride**; default = the rider |

Every Track has a real `center` (never `None`). Floating only says that position is not load-bearing for riders. A floating track still draws at `center` when visible.

`is_floating` said by the author — constructor `floating=True`/`False`, or `track.is_floating = …` — is never flipped by anything else: moving a declared-floating track only moves its drawing.

**A placement after construction anchors an inferred float.** A track that floats only because it was made without a placement keyword is anchored the first time its center gets a place: a link (`track["center"] @= …`, `track.center @= p`, a link on `center.x` / `.y`), `track.center = …`, `move_to` (even onto the spot it has), or any move of the center (`move_by`, `center.x =`, `center << p`, a tween, a drag, a push). That is the placement the inference found missing, given late, so the rule is still "placement given → anchored". Rotate / scale / flip about its own center, `angle`, `u`, `begin` / `end` are pose or window, not placement (a turn about another pivot moves the center, so it places). Rides that began while it floated switch to the track's place at once (the rider moves onto it; motion, like the first step of any anchored ride). Until 2026-10 the placement was taken and ignored — `orbit = Track.circle(radius=120); orbit["center"] @= lambda: earth.center` left the moon circling its own start (KN9 in [Testing Design](Testing%20Design.md)).

How it is seen, at no per-tick cost (`scena/track.py`, "placement anchors an inferred float"): a link fires `_part_link_changed`; `center =` (the `_TrackCenterSlot`) and `move_to` call `_note_placed`; any other write changes the center from the value kept at construction (`_float_mark`), read when a ride starts, on `is_floating`, and — for a track being ridden, which takes a pull consumer so a write dirties it — in the refresh that write causes (`_update_impl`). Running floating rides are listed weakly on the host (`_list_floating_ride`) and switched by `_pull_floating_rides`; a ride never checks per tick. A preset string (`move_along("eight")`) is not inferred: the author has no handle to place it.

Inference when `floating=` is omitted:

- **Placement given → anchored.** Centered presets: `center=`. Started presets: `p1=` (`line`) or `start=` (`wave`, `vectors=`). Also `points=` (world coords), `Track(hexagon)`, `Track.line(p1=, p2=)`.
- **Sizes only → floating.** `Track()`, `Track.eight(width=90)`, `Track.line(length=200)`, `Track.circle(radius=50)` with no `center=`, `Track(vectors=[…])` with no `start=`.
- **`floating=` explicit always wins**, with or without a placement point. `Track.eight(center=(400, 300), floating=True)` is a positioned template; riders still root at themselves.

Rider travel is **always motion** for collision, on either kind of track.

# Construction

```python
Track()                                          # Track.eight(); floating
Track(points=[(60, 80), (200, 300), (420, 120)]) # smooth curve (default smooth=1)
Track(points=[p1, p2], smooth=0)                 # world polyline / n-point path
Track(vectors=[Vec2(50, 0), (0, 80)], smooth=0)  # turtle deltas; floating unless start=
Track(hexagon)                                   # live outline; clone() to freeze
Track(sprite)                                    # live silhouette outline (not a hurtbox: see add_hitbox)
Track(ellipse, floating=True)                    # live outline, position does not bind riders
Track.line / .circle / .arc / .eight / .star / .spiral / .wave / .shuttle
```

Two preset families, two placement keywords:

- **Centered** (`circle`, `arc`, `star`, `eight`, `spiral`, `shuttle`) — `center=` is the focal / middle (same point `Shape.center` / `move_to` already mean).
- **Started** (`line`, `wave`, `vectors=`) — `p1=` on `line`, `start=` on `wave` / `vectors=`. That keyword plants **`u=0`**, not the geometric middle, at any `angle=`: the pose turns the track about its middle, so the middle is placed along the angle (`_line_center_from_p1`; `Track.wave` placed it as if the angle were 0 until showcase A3, 2026-10-23). `.center` stays the midpoint.
- A preset's size keywords are the size it draws: `eight(width=, height=)` spans width × height (it drew height/2 until showcase F; `test_track.TestPresetSizes`).

`Track.line` has two constructors, mirroring `Line`:

```python
Track.line(p1=(0, 0), p2=(200, 0))            # anchored, u=0 at p1; center is Derivate
Track.line(length=200, angle=30, p1=None)     # sizes; p1 optional (plants u=0)
Track.line(vec=Vec2(120, -40), p1=None)       # sizes; p1 optional
```

`length=`/`angle=` or `vec=` are mutually exclusive (`TypeError` if both). `Track(points=[p1, p2], smooth=0)` still works as a general n-point path; `Track.line(p1=, p2=)` is the named front door (floating inference, modifiers, Line-name parity). `center=` on `Track.line` / `Track.wave` / `vectors=` raises — use `p1=` / `start=`.

`Track.shuttle(length=, angle=0, center=None)` (or `vec=`) is a closed 1-D dash: `u=0` at `center`, out both ways, back. Arc-length per lap is `2 * length`. Floating riders start in the middle of the range. `angle=` is the initial heading (pose) on every Track constructor (not baked into the polyline).

`points=` is **world-space absolute** (`Point` / tuple / linked Container). `Vec2`
elements there are positions, not deltas — a list of relative moves is
`vectors=` (`Vec2` or `(dx, dy)`). `vectors=` expands to an absolute point list
(origin `(0, 0)`); `start=` given → anchored with `u=0` at that point, omitted → floating.
`p1=` (sizes-form line), `start=`, and `move_along(..., at=)` take any point-like
and snapshot it. `vec=` / `vectors=` stay deltas: a Graphic there raises, same
rule as `move_by`. A Graphic inside `points=` is a Container, so it takes the
vertex path, but that path still copies `.center` once — it does not follow.
`points=[lambda: ship.center, …]` is the live form. `points=` / `vectors=` /
`radius=` (and a Shape source) are exclusive — passing more than one raises
`TypeError`. Linked `points=` make `center` **Derivate** (centroid); `linked.center = …` raises `DerivedAttributeError`.

`angle=` is the initial heading (pose) on every Track constructor (not baked into the polyline; a function links it). `Track.line` / `Track.shuttle` build the segment along local +x and take `angle=` (or the direction of `vec=`) as that heading, so `Track.line(angle=30).angle == 30` and `local_at(u)` lies on the x axis (until 2026-10 the spec was built at the angle and the heading read 0). `clone()` copies `is_floating`; `clone(floating=…)` overrides.

`clone()` freezes the path as a free `points=` track (links, modifiers and the
live source dropped; smooth 0) whose points are the **vertices of the drawn
table in the track's own frame** (a `reversed()` view in its travel order, the
mirror undone), local to the source's pose origin (`_ctrl_local`, not the
samples' centroid). The pose is copied as pose (`_clone_pose_from`: `angle`,
`scale`, flips), so the copy draws the same polyline, `at(u)` agrees exactly,
and later verbs turn and scale both about the same center. It used to bake the
posed world points and reset the pose (rotation 0, scale 1, no flips), and
resampled at uniform `u`, so a curved preset drifted by up to ~0.2 % of its size.

`u=0` at the first vertex (angle 0 for round shapes), travelling CCW. A Rect /
Square outline starts at its named `bottom_left` (after that fillet when rounded),
so the start stays with that corner when the rect's corners cross or it is
flipped ([Shapes Design — Named points](Shapes%20Design.md#named-points)); travel
is still CCW (`track._start_at_bottom_left`).
`Track(hexagon)` and `Track(sprite)` are live outlines (anchored: riders follow
the host). `Track(sprite)` is the largest island of the painted FrameFx contour, normalized on mask-cell centres, and follows pose and the current cell. Smaller islands are dropped, and the outline sits half a mask cell from the old `(x - 1)` normalization. It is not collidable until the author
says so, and it is not taught as a hurtbox: its collider is the stroke ring (empty
inside). A per-frame hurtbox is a hitbox part — [Sprite Design.md](Sprite%20Design.md#hitbox-parts).
`sprite.silhouette` was removed (second spelling). Source death freezes the last sample table — see below. `clone()` to
freeze a copy that no longer tracks the host.
`quality="high"` (default) or `"low"` — opt-in, never auto-selected by a link.

Linked `points=` follow the usual copy-vs-link rule. Pose (`center` / `angle`
/ `scale`) stays off the baked table. Circle and arc `radius` is part of the
polyline: assigning it after the first sample rebuilds the bake, so `at`,
hit-test, and the stroke collider see the new size. `Track.arc` keeps
`from_angle` / `to_angle` in its spec and reads the **live** `radius` when it
flattens — `arc.radius = …` changes `at(0)`, it does not keep the radius frozen
at construction. Sweep is `to_angle − from_angle`, signed and not wrapped
(`350°` → `10°` is −340°, midpoint on −x, not a +20° arc across 0).
`reversed()` does not keep a private copy of the point lists — hit-test, draw,
and collision read the host tables after each rebake. The stroke window is the
host's `begin`/`end` in host parameter space, so a reversed view of a trimmed
track hits and draws the same ink. The view's own `begin`/`end` slots are not
a second window; assigning them does not change the stroke. **A view has no
pose or size of its own** (`_ReversedTrack`, named `Track`): `center` (the host's
Point itself), `angle`, `scale`, the flips, `radius` and `length` are the
host's — reads, writes, `view["name"]` links (`_HostField`) and formula sources (a formula that names `view.angle` depends on the host's node, `_ensure_scalar_anchor`; G18) — and every pose
verb (`move_by` / `move_to` / `rotate_*` / `scale_*`, flips) acts on the host
and returns the view (a timed verb returns the host's Handle). So what a view
reports is what it draws. Its own parts are `u` and `cursor`, in travel order;
the view is outside the update graph, so its `cursor` is refreshed by the host's
update (and sampled fresh on read — the host is flagged as pulled). Its own
`_rotation` / `_scale` slots stay at identity; everything that draws or samples
reads the host through `_pose_host()`. Before (G16) the verbs wrote those view
slots, which nothing drew, `view.center` was a copy that went stale after a move,
`radius` read 0, a view's outline was empty, and its `cursor` raised.
`_travel_vertices()` is the host's table in the view's travel order — the one
source for `shape_outline`, `clone()` and `_takein` (a view's own `_xs` is a
stale construction-time alias). A destroyed view is not handed out again:
`reversed()` builds a new one. `move_along` / `face=` and the snapshot kept after
the track is destroyed all read that host pose, once per rider per tick.
`clone()` copies that effective host window.

Rect and Square outlines follow `corner_radius` whenever it is positive after
clamping to half the sides, including radii below half a pixel. `corner_radius == 0`
stays the sharp 4-gon. `Track(ellipse)` uses `Ellipse._oriented_frame`
(non-negative axes).

# Draw window (`begin` / `end`)

How much of the **stroke** is painted, clickable, and collidable. Defaults `0` / `1`
(the whole curve). Finite values outside `[0, 1]` clamp. Non-finite `begin` /
`end` (and non-finite `radius`, `Track.line` length/angle, or point coordinates)
raise `ValueError` at construction or assignment — NaN is not clamped, and the
check is not on the sample/hit/draw path. Not in the bake key: unused
or `[0, 1]` is the current cached path (two float compares). Trimmed stroke
extracts a sub-polyline from the existing arc-length table (`curves.subpolyline`)
in host parameter space. A `reversed()` view uses the host window as-is (it does
not mirror `[begin, end]` onto the opposite arc).

Does **not** change `.length`, `at(u)`, `move_along`, or the magenta overlay.
Collision and pointer hit-test follow the stroked window (same tube as the ink —
thickness `line_width`). `move_along(..., span=)` is a **trip** window, not this.
`Circle(angle, spread)` and `Track.arc(from_angle, to_angle)` are geometry.
`Track.arc` keeps start/end angles: a path has a direction (travel, trim). A
region does not — that is `Circle`'s `angle` / `spread`, the same pair as
`query_sector`.

Fill is skipped while the window is not full (a trimmed closed path is a poor
fill). A visual's fill pass (the GearShell wash, the force-field family) is
skipped on an open track too: an open curve has no interior, and Skia would
fill it closed along its chord (a translucent triangle over a game's road).
The author's own `.fill` on an open track keeps its old meaning. Open tracks with `begin >= end` draw nothing (and emit no stroke prims).
Closed tracks wrap: `begin=0.8`, `end=0.2` strokes `[0.8, 1]` then `[0, 0.2]`
(two open chains — no chord across the invisible gap).

Tween / link like `u`: `tween(track["end"], 1, time=1.2)`,
`track["end"] @= lambda: ship.hp / ship.hp_max`.

A shorter **curve** (so `at` / `length` / travel follow it) is a different
object: `Track(points=src.sample_span(a, b), smooth=0)` — not `begin`/`end`.

Tests: `tests/test_track.py` (`TestDrawWindow`), `tests/test_curves.py` (`TestSubpolyline`).

# Collision

Track is a **stroke** collider (same family as `Line`), not a filled area.

- Snapshot: one thin OBB per baked polyline segment (`line_width` half-thickness;
  degenerate dots → circle). Closed tracks wrap the last→first segment → **ring**
  (interior empty). Open `Track.arc` → curved wall.
- Proxy AABB: union of world samples padded by half-width (windowed when trimmed).
- `begin` / `end` **trim** the hitbox to the stroked window (same as hit-test /
  draw). Full `[0, 1]` keeps today's ring/line walk (no `subpolyline` copy).
  Pose extra includes clamped `begin`/`end` so a live tween rebuilds the tube
  without flattening.
- Enrollment stays opt-in. Motion-only rails (`Track.eight`, unstyled orbits) leave
  `collidable` off so riders do not fight their own path.

Author spelling for an arc wall:

```python
wall = Track.arc(
    center=(400, 300), radius=80, from_angle=0, to_angle=90,
    color="gold", line_width=8, group="wall",
)
resolve(player, "wall", bounce=0.0)
```

`Circle(angle, spread)` remains a **disk** collider — use Track when the hitbox
must match the stroke. Depth: [Collision Design.md](Collision%20Design.md).
Tests: `tests/test_collision.py` (`TestTrackStrokeCollision`).
Smoke: `scripts/smoke/collide.py`, `scripts/smoke/colliders.py`.

# Representation

**Flips** mirror the path in place: the heading turns (`flip_x`: `180 − θ`, `flip_y`:
`−θ`) and local y is negated in the tables when they are flattened (`_local_mirror`, part
of the bake key), so draw, `at`, tangents, collision, riders and `cursor` all see a true
mirror about `center` (they used to change only the flag, G12). **Control-point tracks**
(`Track.line(p1=, p2=)`, `points=`): `center` is the Derivate centroid of the world points,
published on every refresh and at construction (it read (0, 0), G11); a pivot `rotate_by`
/ `scale_by` turns / scales the path about the center and moves the points by the center's
orbit. **Cull**: `_domain_aabb` bounds the path with the pose applied (four corners of the
cached local bounds, per bake) plus half the stroke.

Every Track flattens to a local polyline + arc-length table (`curves.py`).
`at(u)` / `angle_at` / `tangent_at` / `spaced_points(n)` apply pose at sample time. `u` is a fixed number (a function raises); `n` is a whole number in `1..1,000,000`. A `reversed()` view reads its host's tables and pose; when the host is destroyed a rider freezes the reversed tables (`frozen_rev`), and a new `reversed()` of a dead track raises `DestroyedError`.
`spaced_points` is closed-aware (no duplicate wrap on loops; open tracks include
both ends). Rebuild is a
cold Derivate: unread dynamic paths cost nothing; several readers still flatten
once per dirty frame.

Tests: `tests/test_curves.py`, `tests/test_track.py`.

# Travel

```python
shape.move_along(target, time=None, speed=None, ease="linear", span=(0, 1), phase=0,
                 loops=1, yoyo=False, face=False, at=None, then=, on_done=)
```

`target` is a `Track`, any `Shape` outline, or a **preset name string** (1:1 alias
for a zero-arg floating Track constructor). Slide to a point:
`move_to(..., time=)` — not `move_along(point)`.

| String | Same as |
| --- | --- |
| `"circle"` | `Track.circle()` |
| `"eight"` | `Track.eight()` |
| `"star"` | `Track.star()` |
| `"wave"` | `Track.wave()` |
| `"spiral"` | `Track.spiral()` |
| `"arc"` | `Track.arc()` |
| `"line"` | `Track.line()` |
| `"shuttle"` | `Track.shuttle()` |

Exact lowercase only. `"zigzag"` raises with a hint pointing at `"eight"`. Custom size: graduate to `Track.eight(width=…)` — swapping
the string for the classmethod with the same kwargs must not change the ride.
Defaults stay shared: **`time=` or `speed=` required** (one of the two;
`speed=` makes the lap `track.length × |Δspan| / speed`, frozen at the call —
a track that is scaled or rebaked later keeps that duration; see
[Actors Design.md — Rate instead of duration](Actors%20Design.md#rate-instead-of-duration-speed)),
**`loops=1`** (one lap, then stop).
Forever is always explicit (`loops="forever"`). Open presets (`wave` / `spiral` /
`arc` / `line`) with forever need author `yoyo=True` (otherwise the open path
snaps at the seam); do not auto-yoyo. Closed `shuttle` needs no `yoyo=` for forever.

A ride reads `is_floating` when it starts. A floating ride whose track is anchored later — a placement on an inferred float, or `is_floating = False` — joins the track at its place on the next sample; `is_floating = True` on an anchored ride's track leaves that ride on the track (it binds future riders).

`at=` on a **floating** target plants that ride's `u0` sample on the given point (same formula as natural floating, parameterized by the point instead of the rider). `at=` on a non-floating target **raises** (`TypeError`; wrap as `Track(source, floating=True)`). Raw `Shape` outlines stay anchored; floating a shape's outline is `Track(shape, floating=True)` first. Do not add `floating=` to `move_along`.

Shares `tween_key=id(shape.center)` with `move_to` / `move_by` (and `(id(shape),
"rotation")` when `face=True`). While the Handle runs, those parts carry a
**process claim**: `@=` on the claimed center / rotation raises immediately at
the link site (same persistent-driver rule as `tween` / `draggable`). Claim
releases on finish, `handle.cancel()`, or entity destroy. A second
`move_along` / timed move on the same key warns and replaces the earlier Handle.
See [Shapes Design.md — Persistent drivers vs linked pose](Shapes%20Design.md#persistent-drivers-vs-linked-pose).
`face=` is shared with timed/instant
`move_to` / `move_by` (there: travel direction instead of path tangent).
`loops="forever"` never fires `on_done`;
`handle.cancel()` or entity destroy stops it. Ease is **per lap**.
`yoyo=True` swaps start/end each odd lap (flips the effective `span` direction;
`phase=` is unchanged — it stays the conga-line offset). `yoyo=True` needs
`loops` > 1 (or `"forever"`). Same `loops=` / `yoyo=` suite as timed pose /
`tween()` / camera — see [Actors Design.md](Actors%20Design.md).

Groups: plain broadcast, list of handles. Conga line = author `for` + `phase=`.
No `Group.move_along`. Fleet wait: `parallel(*handles)` / `until(...)`.

The ride Handle reports this tick’s rate without writing `.vel`: `.velocity` /
`.speed` / `.heading` (heading is the path tangent, flipped 180° when travel is
reverse — same quantity as `face=`).
`.u` is the mapped track parameter; `.lap` is 0-based (`loops="forever"` keeps
counting). Ignore them when you only need the hover. Detail: [Actors Design.md](Actors%20Design.md)
(Handle clock) and [Guia — Handle](../docs/pt/guide/index.html#agendar-handle).

Source death on a live outline: freeze the last sample table, keep travelling.
Cancel only if nothing was baked yet.

# Modifiers

`path.zigzag(amount, waves, kind="sine"|"saw")`, `.orbit(radius, laps)`,
`.wander(amount, seed)` mutate in place and return `self`. `clone()` first if
you need the unmodified copy.

- A call with the values the track already has is a no-op (no re-bake): a
  modifier called every frame with the same values re-baked the whole table
  (~140 µs a track; showcase D8).
- The bake samples each loop / wave by a chord tolerance
  (`_samples_per_loop`: ≤ 0.25 design units off the curve, 8 … 64 a loop),
  not a fixed 8: `orbit(laps=40)` and `zigzag(waves=50)` drew octagons
  (showcase E). `test_track.TestModifiers`.

# Overlay

`show_tracks(True)` — immediate-mode stroke of **active rides** (and idle Track
objects on a layer). Does **not** flip `Track.visible`. Also on inspect overlay
(Ctrl+Shift+7). Debug zoom (Ctrl+Shift+8) is zoom only — no path overlay.
Distinct magenta. Off → zero extra work in the frame path.

**Reclaim:** a bare movement Track (`Track.eight(...)`, `Track(points=[...])`,
`Track(vectors=[...])` with no stroke / fill / `visible=True` / explicit `layer=`)
stays **off** the draw list — rideable, reclaimable when nothing holds it. Styled
/ shown / explicitly layered Tracks stay on the canvas as drawing Shapes, also
while hidden (until 2026-10-21 hiding one took it off its layer, and an unheld
hidden band was collected under the author: `test_track.TestHiddenStyledTrackIsKept`).
Active rides still appear in the overlay via the scheduler, layer or not.

# cursor / u

Cold-Derivate `cursor` Point + Defining `u`. `ship.center @= track.cursor` is
**placement**. Swept following uses `move_along`.

**Pose and the cursor.** `cursor` is the world point at `u` with the pose applied; it
refreshes after `move_by` / `rotate_by` / `scale_by` / a flip (it used to keep its old
world spot until something else re-sampled). It samples the tables the refresh just
built — never `at()` from inside `_update_impl` (that re-entered `_ensure_samples` and
recursed forever on a control-point track, G11).

# Implementation status

**Implemented.** Tests: `tests/test_track.py` (`TestTrackLinePreset`, `TestTrackVectors`, `TestFloatingInference`, `TestPlacementAnchorsInferredFloat`, `TestShuttle`, `TestMoveAlongAt`). `tests/test_curves.py`, `tests/test_handle_motion.py`.
Smoke: `scripts/smoke/tracks.py`, `scripts/smoke/tracks_collide.py`.
Draw window (`begin` / `end`): stroke window (draw + hit-test + collision);
`TestDrawWindow` / `TestSubpolyline` / `TestTrackStrokeCollision`; smoke ring in
`scripts/smoke/tracks.py`. Rounded Rect outline: `TestRoundedRectOutline`.
Stroke collision: `TestTrackStrokeCollision`; smoke arc/ring in `scripts/smoke/collide.py`, `scripts/smoke/colliders.py`.

# Deferred

- **`moon.orbit(earth, …)` sugar** — `move_along(Track.circle(center=lambda: earth.center, …))` already expresses it. Revisit only after real scripts show a verb is worth teaching.
- **Group `stagger=` / `Group.move_along`** — parked with `group.sway_x` ([Actors — Deferred](Actors%20Design.md#deferred)). Broadcast has no per-member argument; join order is not a formation. Conga line stays `for i, w in enumerate(…): w.move_along(…, phase=i * step)`. Live rank of one member is `group["wasp"].index(w)` (shifts when someone ahead leaves).
- **Parametric `Track(fn=lambda u: (x, y))`** — breaks arc-length reparameterization; not beginner material. Not ruled out forever.
- **Auto `quality="low"`** (link-presence heuristic, per-path flatness, or the `fx_quality` Auto ladder) — `quality=` stays an explicit opt-in. Revisit only with target-machine evidence that manual `high`/`low` is insufficient.
- **General path algebra** (`path_a + path_b`) — modifiers cover orbit-on-orbit / zigzag-on-anything. No second composition vocabulary until those fail.

# Not taken

Settled nos, with the reason. Reopen only with a script the current surface cannot express.

| Idea | Why not |
| --- | --- |
| Two types (a drawable curve and a non-drawing motion track) | One `Shape` already plays both roles (the `Point` precedent: invisible until styled); two types would double presets, modifiers and drawing |
| A public `Shape.path` next to `Track(shape)` | Two spellings for one conversion |
| A `relative=` flag, or a second "template" type, for absolute vs relative | Already inferred the way `move_to` / `move_by` draw that line (placement given or not); see [Anchored vs floating](#anchored-vs-floating) |
| `floating=` on `move_along` | `at=` already owns the per-ride root |
| Inferring floating from usage (one rider vs several), or flipping a **declared** float on `move_to` / `center=` | What the author said (`floating=` / `is_floating =`) changes only by the author. An inferred float is different: the late placement is the missing placement, and taking it while riders ignored it was the bug (KN9) |
| Raising on a placement of an inferred float ("give `center=` when you make it") | Breaks drawing a sizes-only track and moving it (`Track.wave(color=…)` then `move_to`), where floating does not matter; anchoring costs that author nothing and gives the rider what the link said |
| `center` as `Optional[Point]` for a floating track | Pose code (`_center_xy`, `rotate_to`, `scale_to`) assumes every Shape has a center |
| `center=` and `p1=` / `start=` on one preset, or one placement keyword for every preset | A started path plants `u=0`, which is not its middle; `.center` / `move_to` stay the geometric middle everywhere |
| Catmull-Rom `alpha` (uniform / chordal) as a parameter | Centripetal (`scena/curves.py`) is the "always works" default; the others ask a beginner to understand parameterization to avoid a problem the default avoids |
| `skia.PathMeasure` for sampling | A `skia.Path` rebuild on every reactive change, no per-sample modifier math, a C++ object in a Python hot loop |
| A large preset catalog ("flies", "fuzzy", …) | That is the `wander` modifier, composable over any path |
| Tween `ease=` as zigzag smoothing | `ease` maps time to `u`; the corners stay. Rounding is `smooth=` or the `zigzag` modifier |
| Cancel the rider when a live source shape is destroyed | The rider owns the handle; destroying the circled platform is gameplay. The ride freezes the last samples instead |
| Debug overlay by flipping `Track.visible`, or a new Ctrl+Shift chord | `visible` is authorship; the overlay is inspection (`show_tracks`), like `show_colliders` |
| Modifiers that return a new Track | A second identity; `clone()` already copies. In place + `return self` matches `move_by` and keeps live links on the same object |
