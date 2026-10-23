# History Design

`History` is a bounded, expiring sequence. `Contrail` is one recipe on top:
a single stroke through the sampled points (Catmull-Rom cubic by default), with
an optional alpha fade from tail to head. Hub: [Scena Design.md](Scena%20Design.md).
Author catalog: [Guia da API](../docs/pt/guide/index.html#history).

Today’s baseline — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| What / why | [Problem](#problem), [Two pieces](#two-pieces) |
| `History` API | [History](#history) |
| `Contrail` recipe | [Contrail](#contrail) |
| Sampling cadence / no `record` sugar | [Sampling](#sampling) |
| Locating code | [Router](#router) |

## Use

1. Pick one jump-box row.
2. Read that section only.
3. Open **Start** in the router if the section is not enough.
4. Stop.

## Router

| Need | Start | Also | Design (if needed) |
| --- | --- | --- | --- |
| `History` / `Contrail` / duration tick | `history.py` | `orchestration.py` (pre-draw) | this file |
| Ease catalog for `fade=` | `easing.py` (`resolve_ease`) | — | this file |
| Contrail Catmull-Rom cubics | `curves.py` (`catmull_rom_to_bezier`, `_phantom_open`) | `history.py` (`_Stroke`) | this file |
| Point snapshot / `_xy_of` | `shapes.py` | — | [Shapes Design.md](Shapes%20Design.md) |
| Private stroke paint | `history.py` (`_Stroke`) | `style.py` (`STROKE_TYPE_NAMES`) | this file |

**Do not slurp:** `history.py`, `shapes.py`.

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `History` | plain sequence + hooks | a reactive `Container` / `@=` |
| `Contrail` | `History` + one private stroke | a `Track` / per-segment `Line`s |
| `Track` | placed curve for draw + `move_along` | a live sample buffer |
| `shape.tail` | faded copies from host velocity | exact stamped samples |
| `MotionTrail` | screen-wide frame ghosting | per-object count/age trail |
| `History.add(shape)` | keeps that object and destroys it on leave | a copy of `.center` |
| `History.snapshot(shape)` | a detached `Point` of its position | ownership of the shape |
| `Contrail.snapshot(dst)` | always a detached `Point` | a live link to `.center` |

# Problem

Authors sample a moving thing over time and want a visible trace. Hand-rolling
`last_point` + `Line` + `after(...).destroy()` is real boilerplate. A single
`Trail` that only draws a fading polyline would be one feature for one picture.
Scena splits the job:

# Two pieces

1. **`History`** — keeps what you `add` and destroys it when it leaves. `snapshot` keeps a position instead. Does not draw.
2. **`Contrail`** — one recipe: a single stroke through the sampled points (Catmull-Rom cubic by default), optional alpha ramp oldest → newest.

# History

```python
h = History(max_points=100, duration=2.0, on_leave=..., destroy_on_leave=True)
h.add(thing)            # keep this object; returns it
h.snapshot(tip)         # keep this position (Point / Graphic / mouse / tuple)
h.snapshot(x, y)        # keep this position (bare floats)
```

One sentence: a History keeps what you add and destroys it when it leaves — `snapshot` keeps a position instead.

## `add` — ownership

Leave (cap, age, `discard`, `clear`, lowering a bound) is one sequence:

1. Remove from storage.
2. `on_leave(thing)` if set — `thing` is still alive.
3. If `destroy_on_leave` and `thing` is an alive non-ephemeral `Entity`: destroy now, unless its `life` slot is playing a death verb (`hide_on_finish`: `dissolve_out`, `fade_out`, `implode`, `burn_out`). Then destroy when that slot next stops being a death verb.

Step 3 runs even if `on_leave` raises (`try` / `finally`). An object already destroyed elsewhere is skipped. `on_leave` is additive: it does not replace the destroy.

`destroy_on_leave=False` (constructor only, read-only after) keeps and forgets without destroying — tapped cards owned elsewhere. Re-adding the same object is legal only in that mode.

| Value | Kept as | On leave (default) |
| --- | --- | --- |
| Standalone `Entity` | Owned | `on_leave`, then destroyed (deferred while a death verb plays) |
| Number, string, tuple, dict | Value | `on_leave`; nothing to destroy |
| Ephemeral `Point` (`Point.temp`, arithmetic) | Value | `on_leave`; not a registry citizen |
| Part of another object (`tip.center`, `line.p1`) | — | raises — use `snapshot` |
| Live non-Entity (`mouse`, `Vec2`, `Attribute`) | — | raises — `snapshot` or copy the value |
| Same owned `Entity` twice (`destroy_on_leave=True`) | — | raises |

`add` returns `thing`. An extra object that should die with the entry uses `entry.on_destroy = extra.destroy` — no payload map inside `History`.

Death verbs are published on `Graphic` (`Shape`, `Sprite`, `Text`), so the same `life` slot and deferral apply to each. A spawn verb (`dissolve_in`, `fade_in`) does not defer: leaving is final. `clear_transients()` while a deferred destroy is waiting destroys now. `pop` does not leave: the caller gets the object alive, with no `on_leave` and no destroy.

When History destroys an object it records a breadcrumb. Later ink access on that dead object appends `destroyed by History when it left (added at t=…)`. Pose writes (`dead.x =`, `dead.move_by`) raise `DestroyedError` with that same note — History's text is not replaced by the generic destroy-site line.

Age eviction runs in `tick_all_histories`. An author `on_leave` that raises propagates; it is not swallowed.

## Bounds

`max_points=` and `duration=` are independent, live-writable. Raising never
evicts. Lowering **evicts immediately** (oldest first, full leave each).
`duration=` registers for the pre-draw tick (`tick_all_histories`, next to
`tick_all_transients`). Count-only / unbounded histories are inert until
`add` / `snapshot` / `pop` / `discard` / `clear`.

A growing trail (snake body) is `history.max_points += 1` on the eat event.

## Hooks

`on_leave` is one argument, `thing`. Set it in the constructor or later as `h.on_leave = fn`. A subclass may define `def on_leave(self, thing)` instead. Constructor callback and subclass method do **not** stack — `TypeError` if both. There is no `on_add`.

A History is a closed surface ([Scena Design](Scena%20Design.md#entity-ink-vs-st)): `h.lenght = 5` raises with a did-you-mean. A subclass keeps its own data by creating it in its `__init__` (before or after `super().__init__()`); a new name created later in a method raises, and the message says "create it in `__init__`". `Contrail`, which calls `super().__init__` last, is sealed when its own constructor returns.

## `snapshot`

Always a fresh detached `Point` (off the registry and the reactive graph). `(x, y)` uses `Point.temp`; one point-like argument copies under `ephemeral_creation`. `on_leave` still receives that Point. Nothing to destroy. No public `Point.snapshot`.

A destroyed Entity, or a part of one (`circle.center`, `line.p1`), raises `DestroyedError`. `destroy()` detaches `owner`, so parts are stamped with the dead host in `Container.clean_up` and the error still names that host. The message tells the author to start the sampler as `host.every(...)` (it stops on `destroy` and pauses when `active` is False) or to cancel the handle. `mouse`, tuples, and bare floats are not Entities and are unchanged. `add` of a destroyed Entity raises the same way — there is nothing left to keep.

## Reading / removing

| Surface | Meaning |
| --- | --- |
| `history[i]` / `history[a:b]` | Index; slice is a plain list snapshot |
| `history.first` / `.last` | `[0]` / `[-1]` |
| `len` / iterate / `bool` | Oldest → newest |
| `pop(index=-1)` | Take it out alive; no `on_leave`, no destroy |
| `discard(value)` | Identity remove; full leave; no error if missing |
| `clear()` | Full leave, oldest first |

Dropping a `History` does not clear it — call `clear()` when the scene ends, or owned objects stay on stage.

# Contrail

```python
contrail = Contrail(max_points=100, duration=2.0, fade=True, ease="ease_out",
                    visual=Laser("red"))
dst.every(0.05, lambda: contrail.snapshot(dst))
```

- One private `_Stroke` Shape (world-space float arrays + cached `skia.Path`),
  mutated in place — not a `Track`, not one `Line` per segment.
- `smooth=1` (default) builds an open Catmull-Rom cubic through the samples
  (`catmull_rom_to_bezier` + `path.cubicTo` — not `flatten_controls`; no densify,
  no arc-length table). `smooth=0` / `False` is a straight polyline. Same
  tangent scale as `Track.smooth`. Live-writable.
- `fade=True` multiplies alpha along the stroke: oldest → `0`, newest → `1`
  (relative to the stroke’s own base alpha). Default ease is linear. Paint is
  a fixed cap of constant-alpha subpaths (≤16 bands by stamp index), not a
  per-segment gradient shader — joins stay on the cubic path. Tail and head
  bands keep the host `line_cap`; interior bands are butt so ADD recipes do
  not bead at every sample.
- `color=` / `visual=` / `line_width=` / `line_join=` (default `"round"`) are
  constructor keywords and stay live-writable on the Contrail (proxied to the stroke).
  `line_join` is the corner style for `smooth=0` (and any real cusp); it is not
  the curve. `line_cap` is a live property (framework default `"round"`), not a
  constructor keyword.
- `snapshot` always stores an ephemeral `Point` (not a registry citizen, not a graph node) — Graphic / live center / tuple / Point / mouse / `(x, y)` all copy. `add` raises: Contrail keeps positions.
- Author `on_leave=` is a side effect when the tail recedes; stroke always trims itself. `destroy_on_leave=` is not a Contrail keyword.
- Path rebuild is dirty-flagged on store / remove and flushed once per
  mutation (`snapshot` / tick / `pop` / `discard` / `clear` / `smooth` / `fade` / `ease`).
- **One span table a rebuild (2026-10-21).** `history._span_table` computes each
  span's Catmull-Rom cubic once (the point list and the phantom ends once a
  rebuild); the stroke and every fade band replay it. Before, each span rebuilt
  the point list and the phantom ends (O(n²) a rebuild) and the bands computed
  every span a second time: three comets with a 40-point faded trail spent
  ~0.7 ms a frame in `snapshot` (`examples/constelacao.py`). The path bytes are
  the same. Measured (HEAD vs HEAD + this, eight alternating processes): a
  40-point faded rebuild 158 → 57 µs, unfaded 72 → 36; `snapshot` 40 faded
  231 → 131 µs, 8 points 88 → 77, 200 points 1978 → 358. Guard:
  `tests/test_contrail_rebuild.py` (byte-identical stroke, bands, alphas and
  centre against the pre-change rebuild over random trails, through
  `snapshot` too; a spy: one curve per span, one `_phantom_open` a rebuild).
  What remains of a snapshot is mostly the detached `Point` (~43 µs, a full
  Shape build even through `Point.temp`) and reading the points back.
- No `stroke=` (stroke-only shape → `color=` is enough). Sampling stays `every` + `snapshot` — see [Sampling](#sampling).
- Snapshot for travel: `Track(points=list(contrail), smooth=0)`.

`Contrail.destroy()` clears without `on_leave` and destroys the private stroke. It is idempotent. Afterwards every mutator (`snapshot`, `add`, `pop`, `discard`, `clear`, and the live setters) raises `DestroyedError` — a timer is probably still feeding it; cancel that handle. Reads stay legal (`len`, index, `first` / `last`, getters). Plain `History` has no `destroy()`.

## Sampling

Cadence stays separate from storage. `every` + `snapshot` is the only sampler: a condition, an offset, or a mode-scoped timer stays ordinary Python. A method that only ever records one center would close those off.

**Fence.** No `sample(...)`, no `History.record(source, every=)`, no `Graphic.contrail(...)`.

**Revisit** only if several taught samples copy the same unmodified `e.every(..., lambda: c.snapshot(e))` after the destroyed-source raise is in place, and `e.every` plus that raise is still not enough.

The timer belongs to what it reads:

```python
heroi.every(0.1, lambda: rastro.snapshot(heroi))
```

That timer stops when `heroi` is destroyed and pauses while `heroi.active` is False, so a parked hero stops feeding the trail. A module-level `every` keeps firing: after `destroy` the next sample raises `DestroyedError` (it does not retire quietly, unlike `@when`), and a parked hero keeps sampling the hidden position. Use a plain `every` when that lifetime is what you want — `mouse`, or a timer started inside a mode body so it dies on leave.

A teleport is not a path. Clear the trail next to the placement, or the next sample draws a streak from the old position:

```python
heroi.center = spawn
rastro.clear()
```

# Author patterns on History alone

Dots:

```python
dots = History(max_points=40, on_leave=lambda dot: dot.dissolve_out(0.3))

def drop_dot():
    dot = dots.add(Circle(center=tip.center, radius=4))
    dot.visual = Halo("cyan")
```

Per-segment lines (only when each segment needs its own look or collision; otherwise `Contrail(smooth=0)`):

```python
segments = History(max_points=100, duration=2.0)

def sample():
    start = segments.last.p2 if segments else tip.center
    segment = segments.add(Line(p1=start, p2=tip.center))
    segment.visual = Laser("red")
```

The first segment is zero-length. When the history empties, the next segment starts at the tip.

A follower:

```python
path = History(duration=0.4)
player.every(0.02, lambda: path.snapshot(player))
```

Remembered, not owned:

```python
picked = History(max_points=2, destroy_on_leave=False, on_leave=lambda card: card.flip_down())
```

# Deferred

- **Contrail `visible`.** The private stroke cannot hide with its source. Revisit when a sample needs that. (`layer=` landed 2026-10-23: the showcase builds needed trails behind their sources; `Contrail(layer=)` and `contrail.layer` pass to the private stroke, a bad name raises before anything registers; `test_history.TestContrailLayer`.)
