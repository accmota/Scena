# Reactive Design

Pull reactivity, `Container` / `Attribute`, ownership vs dependency graph, takein,
pose fast path (A1–A4), and maintainer hazards. **Happy path for this subsystem** —
pick one row; do not read the rest. Hub: [Scena Design.md](Scena%20Design.md).
Shape geometry: [Shapes Design.md](Shapes%20Design.md). Author calls:
[Guia da API](../docs/pt/guide/index.html#reativo).

Today’s baseline, not a freeze — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| `=` vs `@=` / takein | [Values vs live links](#values-vs-live-links), [takein](#takein) |
| What may be linked | [What may be linked](#what-may-be-linked-sources-and-targets) |
| Defining vs Derivate | [Lazy Derivates](#lazy-derivates-liveness) |
| Measured Box off the graph / GC-only nodes | [Deferred trees](#deferred-trees-measured-boxes) |
| Pull / dirty / flush | [Pull reactivity](#pull-reactivity-engine-contract), [`@when`](#events-when--on_change) |
| Pose fast path A1–A4 | [Pose performance](#pose-performance-a1a4) |
| Maintainer hazards | [Difficult / bug-prone areas](#difficult--bug-prone-areas) |
| Paint is not ink | [Appearance](#appearance-paintstate-internal) |

## Use

1. Pick one jump-box row.
2. Read that section only (search; do not read the rest of this file). Treat fences there as current constraints.
3. Open **Start** only if the section is not enough.
4. Open **Also** / another Design doc only if Start is not enough.
5. Stop. Do not ingest `scripts/`, other companions, or the private archive / proposals.

## Router

| Need | Start | Also |
| --- | --- | --- |
| `@=` / Attribute / pull graph | `state.py` | — |
| `@when` / `@on_change` | `events.py` | `state.py` (dirty / flush) |
| Bracket handle used as a value (`st["x"]` in a lambda) | `formula_check.py` (`_refuse_handle_as_value`) | `state.py` (`FieldRef`, `field_ref_value_message`) — [The handle is not the value](#the-handle-is-not-the-value) |
| Defining / Derivate geometry | [Shapes Design.md](Shapes%20Design.md) | `shapes.py` (search; do not slurp) |

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `@when` | `events.py` (flush) | `process.py` (timers/tweens) |
| `Container.update()` | graph recalculation | `on_update` (per-frame actor hook) |
| `.visual` / `.fill` | paint properties (`fill` links as a target: [Appearance links](#appearance-paintstate-internal)) | ink / formula sources |
| `st["score"]` | the handle (link, bind, watch) | the value — inside a lambda write `st.score` |

## Not in this doc

- Class tree / datapath → [Scena Design.md](Scena%20Design.md)
- Shape models / CTM draw → [Shapes Design.md](Shapes%20Design.md)
- Process / modes → [Actors Design.md](Actors%20Design.md)
- Formula groups (`group["name"] @=`) → [Actors Design.md](Actors%20Design.md#formula-groups) (not an Attribute / `FieldRef` edge)
- Linked hitbox switch (`hb["active"] @=`) → [Sprite Design.md — round 2](Sprite%20Design.md#pixel-shapes-and-linked-active-round-2) (a polled link, not a graph edge)
- Author catalogs → [Guia da API](../docs/pt/guide/index.html#reativo)


# Reactive model

================

Scena is a **reactive scene graph**: values live in **Attributes**, geometry and drawable objects are **Shapes** / **Sprites** (and other **Containers**), and relationships between them are either **copied values** (`=`) or **live links** (`@=`).

```
Attribute          leaf value cell (scalar / typed payload)
    ↑ parts
Container          ownership tree + graph participation
    ↑
Entity             canvas roster / layer / groups / collidable / active / process / ink
    ↑
Graphic            pose, filters, transients, .visual   (ABC)
    ├── Shape      Entity + PaintState + ContainerSlot geometry
    └── Sprite     Entity + image body / Sheet / play / hitbox
SpatialFx          Entity ambient emitter (domain pose + tick/draw; no Graphic)
```

Two graphs coexist:


| Graph                | Edges                | Role                                  |
| -------------------- | -------------------- | ------------------------------------- |
| **Ownership tree**   | `owner` / `parts`    | Composition and naming (`line1.p1.x`) |
| **Dependency graph** | structural + formula | Computation order for updates         |


Changing a value does **not** fan out via classic observers. When the ownership
tree has **pull consumers** (outbound `@=` / `@when`, or live Derivates), the
writer marks itself and transitive dependents **dirty** (O(cone), no recompute).
Pure derived data is **recomputed on read** (pull, memoized). Effects
(`@when` / `@on_change`) stay push-scheduled and run on `flush()`. Unlinked
shapes with cold Derivates skip `mark_dirty` entirely (A2) — see
**Pose performance** below.

The programming model the author sees:

```python
# Copy: take the current number, no ongoing relationship
point1.x = 10
point1.y = c1.radius          # copies the current float, no ongoing relationship

# Link: keep identity; stay in sync when the source changes
point1["x"] @= lambda: c1.radius      # FormulaLink (canonical form)
point1["y"] @= lambda: c1.radius * 2  # FormulaLink
```

Links are first-class: they register formula edges in the dependency graph, rewire structural edges under the linked subtree, and re-evaluate during update cycles. Objects that participate in links **must keep stable identity** — you never replace a part Container with another object; you update its contents in place (`takein`). That is the key invariant behind assignment and formula evaluation.

# Authoring model (user code ↔ architecture)

============================================

This section explains the framework **through the code an author writes**. It is not a tutorial; the snippets show how the public surface maps onto the architecture above.

## Stable identity and takein

A Shape’s fields are real objects with fixed identity, not replaceable values:

```python
line = Line(p1=(0, 0), p2=(100, 50))
p = line.p1          # always the same Point instance
line.p1 = (10, 20)   # does NOT replace line.p1 — calls line.p1.takein((10, 20))
```

`ContainerSlot.__set__` and `Attribute.value` both end in **takein**: copy scalars (or nested values) into the existing Container. That is why links, ownership names (`line.p1.x`), and DependencyGraph edges stay valid across assignment. Formula evaluation uses the same path: evaluate → `_takein(result)` into the linked owner.

## Values vs live links

```python
# Copy now (no graph edge from this write alone)
line.p1.x = other.x          # plain float copy — no live relationship
st.t = 0.5                   # State creates/writes an Attribute

# Stay in sync (formula edge + re-eval on update cycles)
line.p1["x"] @= lambda: other.x              # canonical form (always works)
line["p1"] @= lambda: rect.right_center      # same form at Point level
st["b"] @= lambda: st.a * 2                  # FormulaLink; AST finds sources
twin["angle"] @= lambda h=host: h.angle      # default-arg capture is a source
sat["radius"] @= lambda: items[0].radius    # simple subscript chains resolve
Line(p1=lambda: rect.top_left, p2=c.center)  # constructor: callable links, bare value copies (p2 is a snapshot)
```

`=` on a linked field raises `LinkedAttributeError` — call `obj["field"].unlink()` first. That includes writing a parent when a child is linked (`c.center = (0, 0)` after `c.center["x"] @= …`) and writing a child when a parent is linked (`c.center.x = 10` after `c["center"] @= …`). `@=` installs `DirectLink` / `FormulaLink`, rewires the linked subtree upward, registers formula edges, and evaluates once. Competing formulas on an ownership ancestor↔descendant chain are rejected (`LinkedAttributeError`). A formula is the only **exclusive** persistent driver: `@=` and any other driver (`draggable`, `wheel_rotate`, in-flight `tween` / timed pose verb / `move_along`, standing `resolve()`) on overlapping parts raise in both directions; the non-formula drivers never refuse each other (they compose) — see [Shapes Design.md — Persistent drivers vs linked pose](Shapes%20Design.md#persistent-drivers-vs-linked-pose). Named groups use the same `=` / `@=` words **outside** this graph: `group["enemies"] @=` is `GroupOperator` recompute-on-read — [Actors Design.md — Formula groups](Actors%20Design.md#formula-groups). The second link outside the graph is a hitbox part's switch, `hb["active"] @= fn`: a **polled link**. It needs no Container source (`sprite.showing(…)` reads the clock-driven cell), and its source is not parsed. It is evaluated where it is used: at the start of every collision `step()`, by every collision query, and on every read of `hb.active`. Otherwise it follows the link rules: `=` while linked raises `LinkedAttributeError`, `hb["active"].unlink()` drops it, and `hb.active = lambda: …` raises `CallableAssignError`. It opens the category "a flag linked by polling" for `Hitbox.active` only; other flags (`visible`, `collidable`) stay plain — [Sprite Design.md — round 2](Sprite%20Design.md#pixel-shapes-and-linked-active-round-2).

### What may be linked (sources and targets)

`@=` is graph-backed. Invalidation only happens when a **Container** (or ink `ScalarAnchor`) in the formula's source set is written. Plain Python names (`int`, `float`, lists, ordinary objects) never call `Container.update()`, so they cannot drive a link.

| Side | Rule |
| --- | --- |
| **Target (LHS)** | A linkable Scena field: geometry / pose slots (`radius`, `center`, `angle`, …), Entity ink (`ship["hp"]`), `State` cells (`st["score"]`), or a standalone `Attribute`. Paint / appearance channels are **not** linkable. A reserved name (`_INK_RESERVED`) that does not link refuses `@=` and `= lambda` with one of three answers, read from the kind's route table so every kind gives the same one (`_ink_link_forbidden_message`): **absent** — the kind lacks it (`Rect has no field 'text' (a Text field)`; a missing size word adds `Size it with radius`; on a Graphic, a UI widget or a SpatialFx, `=` raises the same words, a widget or effect with its own fix (`button.text`: "Its caption is .label") — [Actors Design — Ink](Actors%20Design.md#ink), RN1 / RN2); **property** — set it with `=` (plus the field's hint: `.set_color(…)`, `Sprite-only`, …); **read-only** — computed for you (`name`, `is_alive`, `touching_sides`). A `_RouteRefusal` carries its `kind` (`read_only` / `method` / `absent`) for this. Before, only the `_ink_strict` kinds (Line, Point) consulted the route; the others said "appearance and built-in properties" even for a field they lack. Guard: `test_fieldref.TestReservedLinkRefusalPerKind` (every exported Graphic kind × every reserved name, oracle read from the MRO). |
| **Source (RHS)** | A `lambda` — or a named function (`def`) — whose code names at least one Container (`FormulaLink`). Input Containers (`clock`, `keyp`, `mouse`) count, and so do audio levels (`mic.level`, `audio.level`, a sound `h.level`, their `.spectrum()`): not Containers, they name a per-frame-sampled stand-in node through `_formula_source` — [Sound Design — Levels as formula sources](Sound%20Design.md#levels-as-formula-sources). Another Container or a bracket `FieldRef` (`obj["field"]` → DirectLink) is also legal, just not the taught-first form. Bare floats (`host.angle`) are **not** sources — Python evaluates them before `@=` runs; wrap with `lambda: host.angle`. |

**Auto-reactive cells.** Creating Entity ink (`ship.hp = 100`) or a State cell (`st.wave = 1`, `State(name="hud").level = 0`) allocates an `Attribute` (or ink anchor) in the dependency graph. Reading either back (`ship.hp`, `st.wave`) gives the value; the bracket (`st["wave"]`) is the cell ([State bag](#state-bag)). Manual cells: `Attribute(0.0)`.

#### A formula that reads an ink field follows the field

`_collect_from_chain` makes the field's anchor a source whenever a chain reads an Entity ink field (`_ink_field_source`), whatever the field holds (2026-10-16). Before, a field holding a Container made the formula depend on that object instead, so `mira = Circle(center=lambda: nave.center + nave.desvio)` with `nave.desvio` a Vec2 followed the vector of link time: one from arithmetic (`Vec2.temp`, `vec_from_angle`) is never on the graph, so nothing it did reached the formula, and a new value (`nave.desvio = …`, or `nave.desvio *= 2`, which builds a new vector) was never heard. A Vec2 in the field stops the chain at the anchor, as `st.pos.x` stops at the cell: the vector is the field's value, not a source of its own. An object (`nave.alvo.radius`) is followed below: the one the field holds now (next paragraph).

**Through a holder, the object held now (2026-10-17).** A chain that reads through a holder, an ink field or an st cell holding an object (`nave.alvo.radius`, `st.alvo.radius`, `nave.alvo[0].radius`, `nave.alvo.alvo.radius`), depends on the holder and on what it reads in the object held now. Before, sources were learned once, at link: after `nave.alvo = b` the formula re-ran once (the field is a source) but heard `a.radius`, not `b.radius`; an `st.alvo` chain stopped at the cell, so it followed neither. Mechanism: `_collect_from_chain` records a hop per holder it reads through, `(store, key, held)` (the ink dict and field name, or the cell's `__dict__` and `'_raw_value'`), and the link becomes a `_HolderFormulaLink`, whose `evaluate` checks after each run that every holder still holds the same object (one dict probe per hop). A holder that moved re-ran the formula (it is a source), so that run is where `_follow_holders` re-learns: `_extract_sources` again with the link-time parse (`_source_parts`: the same names and helpers; only what the holders hold is read again), in lenient mode (a chain that no longer resolves, `nave.alvo` now None or lacking `radius`, stops at its holder, which stays a source), then moves only the edges that changed (`remove_dependency` / `add_dependency`, `_note_became_link_source`, `_refresh_link_source_liveness`). Dirty is sticky until the pull, so a write to the new object between the holder's write and the pull is not lost: the formula is already dirty and reads it. A holder that holds a value (a Vec2, a number, a string) records `_A_VALUE`: another value changes nothing (`nave.desvio = vec_from_angle(…)` every frame does not re-learn), an object later does. Link time is unchanged where it refused: an ink field holding None at link still raises "… is None when the formula is linked" (the unguarded `g.mic.level` would otherwise fail inside the first evaluation with Python's bare message); an st cell holding None links and stops at the cell, as before, and now follows the object it gets later. A new object that reads the formula's own value (`nave.alvo = r` under `r.radius = nave.alvo.radius * 2`) is not followed and warns once (`report_author_warning`): raising from a pull would land far from the write. Plain Python holders (a list in a global, an object's plain attribute) are not holders: nothing notifies when they change, so they are learned at link, as before.

Weighed (2026-10-17): keep it a documented limit (the author has to know that a field read in a formula pins its object, and the st form never worked: silent, and the natural spelling for "the current target"); re-extract on every evaluation (~25 µs per pull of such a formula, every frame for a tweened radius); re-point from the write side (the ink write or cell write marks the formulas that read through it: a cost on every write of a watched field and a walk of its dependents to find them, against one probe on a pull); make the holder's anchor depend on the held object in the graph (an edge moved, and the graph re-sorted, on every write of the field; a change of the object would also dirty every formula that reads only the field). Cost, in-process interleaved A/B (2026-10-17, write + pull): a formula that reads no object through a holder evaluates exactly as before (its class keeps the plain `evaluate`; +0.2 %, noise); one that does pays one probe per hop, +1.3 to +1.6 % (~80 ns); a new value in a value hop +1.4 %; a re-point (the held object changed) ~27 µs including the write and the pull. Guard: `tests/test_formula_follows_holder.py` (holder × kind of read × write, plus None and back, value hops that never re-learn, the cycle, unlink, a destroyed old object).

#### A held Vec2 tells its holder

Every in-place change of a Vec2 ends in its `update()`: `<<` (`_takein`), `+=` / `-=` / `do_rotation` (the batch's exit), `v.x = …` when its ownership root has `_needs_pull_invalidate`. The Vec2 an st cell holds, and the Vec2 an ink field holds while something reads the field (the field has an anchor), get a per-instance `update` (`state._HeldPayloadUpdate`, weak references; holders `(cell, None)` / `(host, name)`, so a vector held twice tells both) that runs the class's and then notifies each holder that holds it now: `cell._changed_in_place()`, or the field's anchor as an ink `=` does (`_notify_ink_anchor`). For an ink field it also sets the vector's pull flag, so `v.x = …` reaches `update()`; a free vector that stops being held gets the flag back. In a flush callback a batch skips `update()` (`um.is_updating`), so `Container._batch_update` asks the hook in that branch. `_ensure_scalar_anchor` installs it on the field's value when the anchor is made, the ink write moves it (`_hold_ink_value`, only when the field has an anchor), `_rehold_payload` moves a cell's, `_drop_scalar_anchor` removes it. The Vec2 class code is unchanged, so other vectors pay nothing. Every spelling reaches the formula: `nave.desvio << v`, `+=`, `-=`, `*=`, `.x =`, `.x +=`, `do_rotation`, and `+=` through another name (`v = nave.desvio; v += w`). A list, dict or object in an ink field takes `+=` / `|=` as a cell does: the same object assigned back notifies the anchor (`Container._write_field`, the `old is value` branch, only when the field has an anchor; a Vec2 told it already); `ship.items.append(x)` stays silent, as `st.items.append(x)` does (write `ship.items += [x]`).

Weighed (2026-10-16): refusing `.x =` / `<<` on an ink-held Vec2, as the cell does, breaks code that writes a field's vector in place (`self.dir.x *= -1`, with no formula anywhere), raises far from the formula that needs it, and still needs the source fix; notifying only on a same-object write (`+=`) leaves `.x =`, `<<` and `do_rotation` silent; making the anchor depend on the held vector in the graph re-points an edge, and re-sorts the graph, on every write of the field. Cost: the source change is link time; a watched field moves the hook to each new vector (a path that was stale before); an unchanged ink write pays one identity test. Guard: `tests/test_ink_held_payload.py` (payload kind × in-place spelling × holder, with a completeness check over Vec2's in-place methods and operators).

**Known limit: an own field cannot read its object's size (AC14, 2026-10-10).** `r["dano"] @= lambda: r.width` (and `c.radius`, `r.top_left`, a Polygon's `center`) raises `CircularReferenceError`: a scalar-slot read names the whole object as the source, and a Derivate part depends on the shape's root, which depends on every child, the new field anchor included. Fixing it would mean per-slot source nodes and Derivate parts wired to Defining parts only, on the hottest reactive paths; the need is narrow and a class `@property` (or `update(dt)`) is the clean idiom, so it stays a limit. `check_circular_reference` recognises the case (`_own_size_read_message`: the owner is a field anchor, the source a non-formula node of the same object) and says so, naming the idiom; a real cycle between two of the object's formulas keeps the generic message. Guia: reactive sources, "Não confundir". Guards: `test_fieldref.TestOwnSizeReadIsAKnownLimit`, `test_subclass_parity.KNOWN_SELF_READ`.

**Refuse empty FormulaLink sources.** `_extract_sources` keeps only Containers. It resolves free variables (closure / globals), **default-arg captures** (`lambda h=host: h.angle` — the usual loop-binding idiom: the body's `h` resolves to the default's value; the default *expression* is not a read, it ran once at creation, so `lambda g=g: g.ganho` reads `g.ganho`, never the whole `g` — reading it made a shape's own field "read itself" and raise `CircularReferenceError`, AC8; `test_formula_functions.TestDefaultArgIsNotARead`), and simple **subscript** chains (`items[0].radius`). A bracket handle read inside a formula (`st["score"]`, `c["radius"]`, `st["x"].value`) is refused before extraction, with the dot spelling (see [The handle is not the value](#the-handle-is-not-the-value)); it used to link a bare `lambda: st["score"]` (leaf `_takein` unwrapped the handle) while any use of it as a number broke. If the set is empty (constant lambda, only plain Python vars, or unparsable lambda with no Container defaults), `FormulaLink.__init__` raises `TypeError` — it does **not** install a one-shot frozen link. A named function is read exactly like a lambda (its body, plus default-arg captures); see [Formula visibility](#formula-visibility-named-functions-helpers-refusals) for what the static pass follows and refuses. A named function whose source cannot be read (`exec`) links only through Container defaults. When the lambda has no AST (REPL / `python -c` / `exec`), closure cells and referenced globals are used the same way — and a `State` among them (`st`) contributes every cell the code object reads, so `ship["shield"] @= lambda: st.lives * 10` links from an `exec` string too. A chain that reads a **missing** `st` cell (`st.livse`) raises the State's own "has no cell … Create it first" error instead of the generic "formula has no sources". Author `=` of a non-number onto any `ScalarSlot` raises `TypeError` (magnitude slots also refuse negatives); a formula / batch refresh is not re-checked. Mixed formulas (`lambda: plain_x + c.radius`) are fine: the Container source dirties the sink and the whole lambda re-runs (re-reading the plain name). If `set_owner` raises after the link is installed, `assign_formula` rolls the link, edges, structural rewire, and pull-invalidate flags back to the pre-install snapshot. Author surface: [Guia — O que pode ser ligado](../docs/pt/guide/index.html#reativo-fontes).

### Formula visibility (named functions, helpers, refusals)

Sources are learned **once, at link time**, by reading the formula's code (a chain
through a holder re-reads that chain, with the same parse, when the holder holds
another object: [Through a holder](#a-formula-that-reads-an-ink-field-follows-the-field)). Nothing
is traced while the game runs (a per-read hook would tax every `Attribute` read, and
the A1–A4 pose fast paths read raw floats that bypass it). So the contract is: **if
`@=` accepts a formula, the static pass saw every read.** Anything it cannot see
raises `TypeError` at the `@=` (naming the construct and the line) instead of
linking a formula that would go silently stale. Code: `scena/formula_check.py`
(`check_formula`), used by `FormulaLink._extract_sources` (`state.py`).

| Allowed | Refused |
| --- | --- |
| `lambda` or `def`; `if` / `elif` / `else`, `return`, local `x = expr` (the right side is read, so `alvo = heroi.center` records `heroi`) | `for` / `while`, comprehensions, generator expressions (a loop's items are only known at run time — use `update()` or a group formula) |
| Builtins (`len`, `min`, `round`, `str`, …), Scena helpers (`distance`, `lerp`, …), the standard library (`math.sin`, `json.dumps`) — they only see their arguments, which are read at the call site | `getattr` / `setattr` / `eval` / `exec` / `globals` … (`getattr(obj, name)` is allowed when `obj` is a Scena object: the whole object is a source) |
| Methods of Scena objects (`p.distance(q)` reads `p`); author methods on a Scena subclass are followed | Calls to code Scena cannot read: another module's functions, a callable held in a local or picked from a collection, constructing an author class |
| Plain functions **from the same file**, followed up to 3 helper levels (recursion is read once): `lambda: texto()` links through the helper | Writes to a Scena object (or to a local it cannot identify) during evaluation; `global` / `nonlocal`; `del`; `import`; `try`; `with`; `match`; `yield` / `await`; `:=` |
| Writes to plain Python data (`calls["n"] += 1`) — they hide no read | Nested `def` / `class` / `lambda` inside the formula |
| Constant indexes (`items[0]`, `items[-1]`, `conf["k"]`) | A changing index into a collection of Scena objects (`balls[st.i].radius` — the link sees the list, not the item) |
| The dot read (`st.score`, `c.radius`) | A bracket handle read as a value (`st["score"] * 2`, `f"{st['score']}"`, `lambda: st["score"]`, `st["score"].value`): the formula would get the handle each run. Refused naming the dot (`_Checker._refuse_handle_as_value`) |
| Bound methods: `hud["text"] @= self.texto` (the receiver resolves as `self`) | Reading `group[...]` — membership is not a graph input (use a group formula) |

A field that does not exist when the formula is linked raises the object's own
error (`AttributeError` with its did-you-mean hint) at link time; it used to be a
`RuntimeWarning`.

**Source must match the running code (bug PM14).** The file on disk can differ from the code that runs: the author saves an edit while the program runs, and a formula is built afterwards (a later act's `setup`). A position lookup would then read another lambda's names, or none ("no reactive sources"). `_locate_uncached` checks the node it found against the code object (`_node_matches_code`: same parameters, and every name the node's body mentions is one the compiled code uses, nested code included); a mismatch, or no node in a file modified after the program started, counts as **no source**: a lambda then links from the code object itself (globals, closure, `st` cells by name — exact), and an error that remains adds "the script file changed on disk … restart the program" (`source_is_stale`). Guard: `test_formula_functions.TestStaleSourceFile`.

**Parse cache.** The script file is parsed once per `(path, mtime)`, and the located
`ast.Lambda` / `ast.FunctionDef` is cached per code object. Linking the same lambda
from a spawn loop no longer re-parses the script (measured: 7.6 ms → 0.1 ms per link
in a 1500-line file). Name resolution (closure, globals, defaults) still runs per link,
because each link captures different objects.

`@when` / `@on_change` are **not** part of this: they poll any zero-arg callable
every flush (`events.py`) and never needed the static pass. (A lambda there that
returns a bracket handle is refused once, at registration; see
[The handle is not the value](#the-handle-is-not-the-value).)

Tests: `tests/test_formula_functions.py`.

## Shape data model

Multi-model shapes declare parts once; the active model marks which are **Defining** (inputs) vs **Derivate** (outputs of `_update_impl`):

```python
rect = Rect(top_left=(0, 0), width=100, height=50)
# Defining: top_left, width, height, angle
# Derivate (lazy): center, right_center, corners, … — not registered until accessed or linked

line = Line(p1=lambda: rect.right_center, p2=(200, 25))  # materializes right_center; marks it live
rect.move_by(10, 0)   # Defining write → mark dirty (pull consumers exist)
# line.p1 / rect.right_center are fresh on the next read (pull)
print(line.p1.x)      # pulls: Rect._update_impl → then DirectLink into line.p1
flush()               # only needed for @when / @on_change mid-frame (or wait for pre-draw flush)
```

During `update(dt)` under `run()`, Defining writes store scalars immediately. If the shape’s ownership root has pull consumers, they also `mark_dirty`; otherwise A2 skips the graph walk. Reading any pure derived value (own Derivate or linked `@=` target) pulls a fresh result. Effects stay deferred until the automatic pre-draw `flush()`. Call `flush()` when you must run `@when` / `@on_change` handlers before the frame ends.

Outbound links *to* derivate parts are the supported pattern: accessing or linking a Derivate materializes it and marks `_derivate_live` (and `_needs_pull_invalidate` on the ownership root). The source shape's `_update_impl` keeps live parts fresh; dependents track them through the graph. Cold Derivates stay unregistered (or skip recalc) so spinning scenes do not pay for unused corners/midpoints.

## Lazy Derivates (liveness)

Derivate parts are **demand-driven**:


| State            | Meaning                                                                                                                                              |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Unregistered** | Slot never `__get__`'d — not in the ownership tree or graph                                                                                          |
| **Cold**         | Materialized but `_derivate_live` is false and no external dependents — `_update_impl` skips writing; dirty visits do not force pass-through fan-out |
| **Live**         | Linked as a formula source, or accessed (first `__get__` sets `_derivate_live`) — owner writes it on structural resolve                              |


`has_external_dependents()` (ownership-subtree filter on graph dependents; the same subtree rule keeps `_clean_up` quiet for an Entity's own field that reads the Entity — `hero["grounded"] @= lambda: "bottom" in hero.touching_sides` dies with `hero` without the "was unlinked because a formula source was removed" warning, AC11; `test_graph_lifecycle.TestOwnFieldLinksDieQuietly`) and link install/unlink (`_note_became_link_source` / `_refresh_link_source_liveness`) keep the live bit accurate. `_note_became_link_source` also calls `_flag_pull_consumers()` so A2 starts paying for invalidation. `ContainerSlot.__get__` resolves `field_type` from the owner's `_defining_part_names` when present, inherits batch flags if the owner is mid-`no_update`, and calls `_materialize_derivate_part(name)` so the first read is fresh. On a **destroyed** owner the first read returns a detached temp (the slot's default, never in the graph): wiring the owner edge would put the dead actor back in the dependency graph (A7 in Testing Design).

`_x_impl` hooks (`_takein_impl`, `_update_impl`) chain with `super()._x_impl(...)`, never `super()._x(...)`: `_x` is the dispatcher and calls `self._x_impl` again (infinite recursion; `Square << Square` did this until A7).

**Cold-safe** `_set_defining_parts` **(required):** only `getattr` Defining names. Never loop Derivate names through `getattr` at construction — that materializes them, sets `_derivate_live` / `_needs_pull_invalidate`, and defeats A2 for the whole shape lifetime. Circles/Lines/Ellipses historically broke scene demos this way; Rect/Square already used cold `__dict__.get`. A rejected author write or bracket `@=` on a Derivate Container part raises **before** `__get__`, so the slot stays unregistered and the pull flag stays clear. Batched `_update_impl` writes are unchanged.

Canonical geometry for links/queries is still Attributes. Draw for Rect / Square / Ellipse / RegularPolygon may use **Defining pose + Skia CTM** so painting does not force world corners live — see [Shapes Design.md](Shapes%20Design.md).

## State bag

`State` is a named bag of standalone `Attribute`s (not itself a Container). Dot/`create`/`set` put variables into the same DependencyGraph as geometry. Removal is `State.remove(key)` → `Attribute.clean_up()` + drop from `_data` (see Destroy and teardown below).

`State(name=…)` is a diagnostic label for `FieldRef` / `LinkedAttributeError` text (same role as `Container.name`). Unlabeled `State()` uses `"State"`. The builtin bag is `State(name="st")` so messages say `st['score']`. Extra bags that should read as themselves pass a name: `hud = State(name="hud")`. `.name` is reserved (not a cell). So are the bag methods `keys`, `exists`, `create`, and `remove` — assigning or `create`-ing those names raises `AttributeError`. `st.x = …` and `st["x"] @= …` create the cell (default `0` when the link creates it). A read (`st.x`, `st["x"].value`, `.unlink()`, `@on_change`) of a missing cell still raises. Dot `@=` needs the cell because Python reads the name first.

**Dot reads the value; the bracket is the cell (0.8.0).** `st.key` returns the payload (`State.__getattr__`, pull-resolving a linked cell; an unlinked cached leaf returns `_raw_value` inline), the same as an Entity ink field. `st["key"]` is a `FieldRef`, the handle that links, binds and watches. Before 0.8.0 the dot read returned the `Attribute` itself, which emulated its value through ~60 dunders and still leaked wherever Python compares by identity or type: `st.mic is None` was always False (Python cannot overload `is`), `match st.mic: case None` never matched, `type(st.n)` / `isinstance(st.n, int)` named the cell, `best = st.score` and `history.append(st.score)` kept the live cell (they followed later writes), and a cell could not be a dict key. Each was silent. The flip removes the whole class; a used read is also ~50 % faster (no dunder hop), and a bare unused read pays ~40 ns more. Alternatives weighed and rejected (2026-10-10): return the payload only for `None` (fixes `is None` only; `st.x` would change type with its value, silently unbind `Menu(st.nave)` while `nave` is `None`, and cost ~55 % on every use); keep the cell and document it (the trap stays for every author who does not read that row).

What needs the cell takes the bracket, and refuses the value loudly with the bracket spelling (`state.bound_cell`, `state.unbound_value_hint`): the widgets' `cell` (`Slider(st["volume"])`; `uiwidget._require_bound`), `Text(st["score"])` (one way, below), `SpriteButton(label=st["lives"])`, `@on_change` / `@when`, `until`, `tween`, and a DirectLink RHS (`c["r"] @= st["r"]`). Only a `State` cell (or a standalone `Attribute`, such as another widget's `.data`) binds; a `FieldRef` on an object's field does not. Three old spellings would have changed meaning silently, so each has a guard: `Text(<number>)` raises (`Text(st.score)` would have been a snapshot); a widget's explicit `None` raises (the `cell` default is the `_NO_CELL` sentinel; `Menu(st.nave)` with `nave` still `None` would have built an unbound menu); `@on_change(<free Vec2>)` raises (`@on_change(st.pos)` would have watched a Vec2 the next `st.pos = …` replaces). A `Vec2` is a Container, so every door that takes a Container also accepted `st.pos` (the held Vec2) where it needs the cell, and went stale at the next `st.pos = …`: `st.pos @= …` (`Container.__imatmul__`), `… @= st.pos` (`_normalize_link_rhs`), `tween(st.pos, …)` (it moved the payload inside a batch, past the guard below) and `until(st.pos)`. Each calls `state.refuse_held_payload(obj, call)`, which raises with the bracket spelling when `state.held_cell(obj)` finds the cell that holds `obj` now (release audit 2026-10-11, RA1); a free Vec2 pays one class check. One old spelling cannot be guarded: `Text(st.nome)` on a text cell is a string, indistinguishable from `Text("Ana")`, so it shows the text of now (the Guia's Text row and State table say so). `st.x @= …` on a number never reaches Scena: Python raises `unsupported operand type(s) for @=` itself. `_extract_sources` resolves `st.<name>` in a formula to the cell (`State._resolve_cell`). A value stops the chain there: `st.pos.x` depends on the cell, not on the Vec2 it holds now. An object does not (2026-10-17): `st.alvo.radius` depends on the cell and on the object the cell holds now, re-pointed when it holds another ([A formula that reads an ink field follows the field](#a-formula-that-reads-an-ink-field-follows-the-field)); before, the chain stopped at the cell and `st.alvo.radius = 7` was never heard. `lambda: st.alvo.r if st.alvo else 0` links while `st.alvo` is `None`, and follows the object it gets. A held object written off the graph (`st.mic.level`, `_formula_source_of`) adds its stand-in node as a source, or the formula would hear only a new `st.mic` (RA2; an Entity holder already hopped).

**`Text(st["score"])` links one way (2026-10-13).** It is `t["text"] @= st["score"]`: a DirectLink from the cell, so the text shows and follows it, and `t.text = …` / `t.value = …` raise `LinkedAttributeError`, whose message names the cell and the write that changes it (`_follows_cell_hint`: "It shows st['score'] (one way): … write st.score = …"). Before, the Text *was* the cell (`__dict__["text"] = cell`), so a write to the text wrote `st.score`: a display that edited game state, and a later `st.score + 1` raised far from the line. A widget (`Slider`, `CheckBox`, `TextInput`, …) still binds the cell itself, because editing it is its job; a display only shows. `SpriteButton(label=st["lives"])` builds its label through `Text`, so it follows one way too. Guards: `test_text.TestTextCell.test_cell_text_links_one_way`, `test_handle_not_value.TestTextCellIsOneWay`.

**The payload changes by whole-value assignment.** Since `st.pos` is the held object, two in-place paths need care. `st.pos += v` / `st.items += [x]` mutate the held object (`Vec2.__iadd__`, `list.__iadd__`) and assign the same object back; `_takein` would see no change, so `State.__setattr__` sends a same-object non-value (`type not in _VALUE_TYPES`) write to `Attribute._changed_in_place()`, which notifies as a changed write does. A Vec2 tells the cell itself, from its own `update()`, on every in-place change (`<<`, `+=`, `do_rotation`, `+=` through another name for it): [A held Vec2 tells its holder](#a-held-vec2-tells-its-holder); `st.pos << v` and `st.pos.do_rotation(a)` were silent before 2026-10-16. `st.pos.x = 5` (no assignment back) raises, as it did before 0.8.0 (CS4): the Vec2 a cell holds gets a per-instance `_write_field` (`state._HeldPayloadWrite`, weak references, no cycle) that refuses an author write outside a batch and names `st.pos = Vec2(..., st.pos.y)`; `_rehold_payload` moves it when the cell takes another value, so other Vec2s pay nothing (`state._HELD_BY_VALUE`, set by `scenamath`). A cell holds a Vec2 **by value**: `_takein_impl` copies one that has an `_owner` (`st.v0 = ball.vel`), or the guard would sit on the object's field and refuse its next write (`ball.vel = …` writes into the existing Vec2), naming `st.v0` (RA3). The copy is inside the branch that already handles a Vec2, so other writes pay nothing; a free Vec2 is held as is (`st.v = v` keeps `v`, and `v.x = 3` then raises, naming `st.v`). An object payload (`st.alvo = circle`) is edited in place as usual, and `st.items.append(x)` changes the list without notifying links (write `st.items += [x]`). An Entity ink field holding a Vec2 takes every in-place spelling, `ship.aim.x = …` included, and each one reaches the formulas that read the field ([A formula that reads an ink field follows the field](#a-formula-that-reads-an-ink-field-follows-the-field)); refusing them as the cell does would break code that writes a field's vector in place. `State.__setattr__` calls `cell._assign_value` directly (what `cell.value = …` runs, minus the closed-surface hop), which pays for the same-object check: an `st.x = …` write is ~5 % faster than before. Guards: `tests/test_state_reads_value.py` (every payload kind reads back as itself in every bag and matches an ink field; the binding matrix, with a completeness check over public classes whose first parameter is a data `cell`; in-place rules).

### The handle is not the value

`st.score` is the value; `st["score"]` is the handle (`FieldRef`). A lambda keeps its reads live (the static pass finds `st.score` and links the cell), so inside one the dot is the only spelling, and the brackets go where nothing wraps the argument: a widget, `Text`, `@on_change` / `@when`, `tween`, `until`, either side of a lone `@=`. Before 2026-10-13 a handle used as a value was silent: `f"{st['score']}"` showed the repr, `if st["alive"]:` was always true, `@when(lambda: st["score"] == 5)` never fired (a fresh handle per `[]`, compared by identity), and `st["score"] * 2` raised Python's bare "unsupported operand". Three layers now refuse it, each with the dot spelling:

1. **Link time** (`formula_check._Checker._refuse_handle_as_value`): a constant-string subscript that resolves to a `FieldRef` in a formula or a helper it follows raises `TypeError` with the line. That covers `@=`, `Text(lambda)` and every constructor link. `st["x"].value` is refused too (the reader followed `.value` to the number and found no source, and it is a second spelling).
2. **Registration** (`EventRegistration.__init__`): a `@when` / `@on_change` lambda whose seed evaluation returns a handle raises. Checked once, so a poll pays nothing; the bare handle (`@on_change(st["wave"])`) still watches.
3. **The handle** (`FieldRef`): every value protocol (`__bool__`, `__str__`, `__format__`, comparisons, arithmetic both sides, `__int__` / `__float__` / `__index__` / `__round__`, `__iter__` / `__len__` / `__contains__`, bitwise, unary, `math.floor` / `ceil` / `trunc`) raises `TypeError` (`state.field_ref_value_message`), a subscript (`st["pos"]["x"]`) names `st.pos['x']`, and an unknown public attribute (`st["pos"].x`) raises `AttributeError` naming `st.pos.x`. `__repr__` stays for debugging and `__hash__` is the identity one. This catches what is never parsed: a `@when` comparison, the REPL, `print`, `st["score"] += 1`. No engine path uses a handle as a value (they test `isinstance` and read `.value`), so nothing hot pays.

Rejected (2026-10-13, with the user): making the bracket read the value inside a formula. A rewrite of the lambda would run code the author did not write (and miss helpers, `@when` lambdas and the REPL); a "formula context" flag in `State.__getitem__` would make the same helper return a handle or a number depending on its caller and tax every formula evaluation; a handle that imitates its value is the pre-0.8.0 leak (`is None`, `type`, `isinstance`). Each would give one spelling two meanings, the confusion this removes. Guards: `tests/test_handle_not_value.py` (each layer, plus a completeness check that every number / text protocol of `float` / `str` is defined on `FieldRef`).

## Shape and the canvas

Non-ephemeral construction registers the Shape with `ScenaCanvas`. Each frame, enabled layers call `draw()`. Visibility and layer membership are orthogonal to reactivity: an invisible or soft-removed shape can still drive formulas.

```python
guide = Line(p1=a, p2=b)
guide.undraw()   # stop drawing; keep graph + links
guide.destroy()              # canvas + clean_up (full teardown)
```



# Attribute

===========

`Attribute` is a **leaf Container**: it holds a single `_raw_value` and has no parts. It is the unit that formulas, arithmetic, and most Shape fields ultimately read and write.

## Assignment: `=` vs `@=`



### Normal attribution (`=`)

Handled through `Attribute.value` → `assign_value` → `takein` / `_takein`.

```python
point1.x = 10
point1.y = c1.radius      # Attribute on the RHS
```

When the RHS is another `Attribute`, `_takein` **unwraps** it to `.value` and stores a **copy of the scalar**. The objects are not aliased; there is no ongoing dependency from this assignment alone. Propagation to owners/dependents goes through `update()` → DependencyGraph / UpdateManager.

Shape fields declared with `ContainerSlot` follow the same idea on `__set__`: assignment never replaces the part object; it calls `part.takein(value)`.

**One set of rules per field, on the slot.** A `ScalarSlot` declares its rules:
`magnitude` (finite, >= 0; `positive` for > 0), `minimum` / `maximum`,
`out_of_range` (`"raise"`: Circle `spread` = 400 raises; `"clamp"`: Track
`begin` = 3 reads 1) and `label` (the name an error gives: `Line.angle`). One
coercion applies them on every path: author `=` (`_coerce_magnitude_slot`,
raise), constructor (`_init_scalar`, same as `=`), batch refresh (clamp), link
pull (`ScalarAnchor._takein_impl`, clamp; NaN / inf, a bool and an int no
float holds raise, named by the slot's label, as on `=`: GX14). A link whose
source holds such a value refuses at the read and stores nothing; `unlink()`
(and destroy, which unlinks) then keeps the last good value instead of
raising. A cell or field holding `True` takes `1.0` (`True == 1.0`, but a flag
and a number are different values: `_value_changed`, `Attribute._takein_impl`). `_kind` (0 plain,
1 size, 2 ranged) is computed once, so a plain or size write costs what it did
before the rules moved. Do not add a value check to a `_write_field` override:
only the author path runs it (D14, D16, a NaN constructor angle).
`test_reactive_matrix.TestOneCoercionForEveryPath` lists the remaining
overrides and why each exists.

### Link attribution (`@=`)

Handled by `Container.__imatmul__` → `assign_formula`.

Canonical form is always `target['field'] @= lambda: expression`, even when the expression is a bare reference — this is deliberate, not defensive; terser forms exist and remain legal but are not shown here.

```python
circle["radius"] @= lambda: player.hp * 10   # FormulaLink (AST sources extracted)
circle["center"] @= lambda: other.center     # same form for a composite field
line["p1"] @= lambda: rect.top_left          # same form at Point level
```

- Builds a `DirectLink` or `FormulaLink` on the addressed field
- **FormulaLink:** the lambda / `def` must pass the [visibility check](#formula-visibility-named-functions-helpers-refusals) and yield ≥1 Container source (free vars, default-arg captures, simple subscripts, followed helpers); otherwise `TypeError` (no silent one-shot link). See [What may be linked](#what-may-be-linked-sources-and-targets).
- **FieldRef RHS** (legal, not taught first): `dst["x"] @= src["x"]` resolves to the source field's graph node (`ScalarAnchor` / part Container) and installs a `DirectLink`
- Forbids competing formulas on the same ownership ancestor↔descendant chain
- Rejects cycles via the dependency graph
- Installs `_link` on a `ScalarAnchor` (bare scalars, and a Defining `angle` on Rect/Ellipse/Square/RegularPolygon/Triangle/Line/Circle), `_PropertyAnchor` (`Graphic.scale` everywhere; `angle` on Point/Sprite/Svg/Text/Track/free Polygon and on derived headings), or the part `Container`

`=` on a linked field raises `LinkedAttributeError`. Use `obj["field"].unlink()` / `unlink_all()` to drop formulas deliberately.

## Leaf behavior

- `_update_impl` is a no-op — leaves have no structural derivation
- If `_link` is set, `_recalculate_formula` evaluates the link and `_takein`s the result
- Arithmetic and comparisons on a cell (widget `.data`, a standalone `Attribute`; `st.score` reads the value itself since 0.8.0) operate on `.value`
  and return a **plain value**, never a cell — the whole numeric protocol, so a cell reads
  like its number: `+ - * / // % **`, `divmod`, three-argument `pow`, `& | ^ ~`, unary
  `- + abs`, `round` (with `ndigits`), `math.trunc` / `floor` / `ceil`, `float` / `int` /
  `complex` / `index`, and all six comparisons, each from either side (`2 ** st.f`). The result is the
  payload's own (`round(st.f)` is an `int`, `st.word * 2` repeats a string); a payload that
  cannot take the operator raises `TypeError` as the bare value would. Augmented writes
  (`st.f **= 2`) have no `__i*__`: Python falls back to `st.f = st.f ** 2`, which takes the
  number into the **same** cell (identity kept; a `Slider` bound to it stays bound).
  **Fence:** no `<<` / `>>` and no `@` on a cell — `Container.__lshift__` is takein
  (`cell << 3` writes 3) and `@` reads as a link (`@=`), so a shift or matmul would give one
  spelling two meanings. Guard: `tests/test_attribute_operators.py` (completeness check
  against `float` / `int` / `complex`; a new or dropped dunder fails it).
- Geometry/ink scalars are already plain numbers; they need no unwrap



# Shape

=======

Geometry, multi-model Defining/Derivate, and CTM draw live in [Shapes Design.md](Shapes%20Design.md). Reactive graph behaviour for shape parts is covered above and in Container architecture below.


# takein

========

## Why it exists

Containers and their parts are **linked by identity** in the ownership tree and dependency graph. Replacing `line.p1` with a different `Point` instance would break owners, dependents, names, and edges.

So Scena never swaps part objects for assignment. `takein` **copies values into the existing object**, preserving references:

```text
target.takein(source)   # target keeps identity; values updated in place
A << B                  # sugar for A.takein(B)
shape.absorb(other)     # takein + destroy other (remove from canvas)
```

External entry: `assign_value` / `=` / slot `__set__` / formula evaluation all funnel into takein (or `_takein` during a cycle).

## Recursive by nature

Composite containers implement `_takein` by delegating to parts:

```python
# Point
self.x = x; self.y = y          # → Attribute takein

# Vec2
self.x = x; self.y = y

# Circle
self.center.takein(other.center)
self.radius.takein(other.radius)

# Line (model-aware: only defining parts)
self.p1.takein(other.p1)
self.p2.takein(other.p2)
# …
```

So takein is **recursive down the ownership tree** until leaf Attributes store scalars. Leaves unwrap an Attribute RHS to `.value` so the stored payload is never another Attribute object.

Composite `takein` usually batches the part subtree so intermediate leaf writes do not each start an update cycle; one `update()` runs if anything changed.

## Contract


| Layer     | Responsibility                                                                    |
| --------- | --------------------------------------------------------------------------------- |
| `takein`  | Public entry; batching / change check / optional `update()`                       |
| `_takein` | Subclass: assimilate value; return whether outputs changed (when used for gating) |


During `_recalculate_formula`, takein runs under `no_update()` so leaf writes stay silent; the cycle itself schedules dependents.

# as_payload

==========

O(1) helpers in `state.py` for APIs that need **plain Python values**, not Attribute wrappers.

```python
def as_payload(obj):
    return obj.value if isinstance(obj, Attribute) else obj

def as_payload_all(*values):
    return tuple(as_payload(v) for v in values)
```

**Rule:** unwrap at the **leaf gate** that actually needs a bare payload (`isinstance` dispatch, dict/set key, enum/string compare, hash). Do not blanket-rewrite every parameter of every call.

Most math and drawing code needs **no** unwrap at all: Attribute already defines `__float__` / `__int__` / arithmetic / comparisons, and `__getattr__` delegates to the raw value. Prefer deleting a former `@unwrap_attributes` site over replacing it when those dunders already cover the body.

Use `as_payload` when a parameter hits a gate that Attribute cannot satisfy (e.g. `ColorNames.get(name)` — Attribute is unhashable). Use `as_payload_all` at the top of variadic constructors that dispatch on argument shape (`Color`, `Gradient`, `PaintState.set_color`). Nested Attribute-in-tuple cases unwrap at the point each element is consumed (e.g. inside `_validate_color_components`), not via a recursive walker.

**What for:** the dual of takein’s “store bare values” rule — write path takeins; read path peels one Attribute cell when a plain Python API demands a payload. Binding params that must stay as Attributes (e.g. UI `bounded`) are left alone on purpose.

# update and `_update_impl`

===========================

Two layers of “update” answer different questions.

## Frame-consistent effects (the authoring contract)

Scena promises **per-frame** consistency for *effects* (`@when` / `@on_change`), not per-assignment. Pure derived data is **always current on read** (pull).


| When                                      | Defining / State leaf writes                                     | Pure derived (Derivate, `@=` targets) | Effects `@when` / `@on_change`                      |
| ----------------------------------------- | ---------------------------------------------------------------- | ------------------------------------- | --------------------------------------------------- |
| Outside `run()` (construction, tests)     | Immediate scalar store; `mark_dirty` only if pull consumers (A2) | Fresh on next read                    | Flush immediately after write (when dirty walk ran) |
| Inside `run()` during tick / `update(dt)` | Same                                                             | Fresh on next read                    | Deferred until `flush()` before `draw()`            |
| After `flush()` / explicit `flush()`      | —                                                                | —                                     | Caught up                                           |


```
run() frame:
  begin_frame_batch()          # UpdateManager.deferring = True (effects only)
  clock._tick / poll / sample pointer / update(dt)
       # Defining writes → store scalars
       # if ownership root needs pull invalidate → mark_dirty
       # else skip graph (A2 — unlinked animation)
       # reads of derived / linked values → pull-resolve
  tick_processes()             # after / every (clock.dt, already scaled)
  collision system step()
  flush()                      # run pending @when / @on_change
  end_frame_batch()
  draw()                       # reads pull fresh geometry as needed (or bare Defining)
```

**Do:** write Defining inputs and State in `update(dt)`; read any derived or linked value whenever you need it — it is current. Let `@when` resolve on flush.

**Don't:** assume `@when` handlers have already run mid-`update` — call `flush()` first if you need side effects before the frame ends.

`flush()` is public (`from scena import flush`) for escape hatches and for batching effect firing outside the run loop.

## `update()` — invalidate (with A2 skip)

Public entry after an external mutation:

1. No-op if `_in_batch_update`
2. Ephemeral / unregistered → local resolve only
3. If ownership root `_needs_pull_invalidate` **is false** → return (**A2**: no `mark_dirty`)
4. Else `UpdateManager.mark_dirty(self)` — flags self + transitive dependents. Outside a frame batch, that also polls `@when` / `@on_change` when any are registered (they are not graph nodes). A write still inside `batch_update` / `no_update` does not poll; the batch's closing `update()` does, once. Inside `run()`, `deferring` skips the poll — the pre-draw `flush()` is the only event pass. The frame `mark_dirty` walk itself is unchanged.

Sticky flag `_needs_pull_invalidate` lives on the **ownership root**. It becomes true when any node in the tree becomes a link source, gains a live Derivate, or receives an inbound `@=` (`_flag_pull_consumers`). It does not clear when the last consumer unlinks (sticky by design — rare; avoids tracking refcounts).

## `_ensure_fresh()` / `_resolve_*` — pull on read

`Attribute.value` calls `_ensure_fresh()` before returning:


| Kind                                     | Action                                                           |
| ---------------------------------------- | ---------------------------------------------------------------- |
| Has `_link` (or formula-driven ancestor) | `_resolve_link()` — evaluate formula → `_takein`                 |
| Derivate-rooted                          | `_local_refresh_root()._resolve_structural()` — `_update_impl()` |
| Plain Defining leaf                      | no-op (already sync-fresh)                                       |


Plain Defining reads must **not** walk to the shape root just because the Shape was marked dirty — gate on Derivate-rooted / formula ancestry. That keeps unlinked Defining pose reads cheap even when siblings are Derivates.

**A structural Derivate part pulls its owner first.** `_local_refresh_root()` stops at the nearest node with its own `_update_impl`, and a Derivate `Vec2` (`Line.vec`, `Rect.vec`, `Box.vec`) is such a node: it derives `length` / `angle` from its own `x` / `y`. But its `x` / `y` are written by the owning shape's `_update_impl`. So `_resolve_structural()` on a dirty Derivate part first resolves the owner's refresh root, then runs its own `_update_impl`. Before this, a read of `rect.vec` after a corner moved returned the `x` / `y` of the last owner update (G5 in [Testing Design](Testing%20Design.md)). A Point part is passthrough (no own `_update_impl`), so it always resolved through the owner.

If formula evaluation or `_update_impl` raises, `_dirty` stays set and `_resolving` is cleared, so the next read retries. A successful resolve still clears dirty on that node (and, for a structural resolve, its subtree).

## `_update_impl()` — structural derivation

Subclass hook for “given Defining parts, refresh **live** Derivate parts.” Leaves (`Attribute`) no-op. Runs on read of a dirty Derivate root (or when an effect / linked consumer pulls), not on every write.

```
external write / takein
  → update()
  → [A2: maybe skip] mark_dirty (self ∪ transitive dependents)
  → [if not deferring and any @when / @on_change registered: flush()]
read Attribute.value / get_xy(…, bare=True)
  → _ensure_fresh()  (or A3 bare _raw_value when safe)
  → resolve link or structural _update_impl if dirty
  → return value
flush()
  → run pending EventRegistration._recalculate_formula (effects only)
```



# Container architecture

========================

## Big picture

The reactive core is a **tree of Containers** whose relationships are also registered as edges in a **directed dependency graph**. Value changes do not use a classic observer “notify owner / notify children” cascade. Instead:

1. A container may mark itself and transitive dependents dirty (`update()` → `mark_dirty`), **unless** A2 skips because the ownership root has no pull consumers. Effects are collected for `flush()`; pure data is not recomputed yet.
2. A read of `Attribute.value` (or anything that goes through it) pulls: resolve formula / `_update_impl` if dirty, then return. Hot pose paths may read bare `_raw_value` (A3) when safe.
3. `flush()` runs pending `@when` / `@on_change` only (those evaluations pull pure data as needed).

```
ScenaSystem (global singleton)
├── DependencyGraph   # nodes + edges + cached topo order (cycle checks / tooling)
└── UpdateManager     # mark_dirty + flush (polls the event list)

Container
├── owner / parts     # composition tree (`parts`: read-only property over `_parts`)
├── field_type        # Defining vs Derivate (read-only property over `_field_type`)
├── _link             # DirectLink | FormulaLink | None
├── _dirty / _resolving
├── _needs_pull_invalidate  # ownership-root sticky; A2 skip when false
├── _derivate_live / _bare_ok
├── _subtree_cache    # Tier 1.3: flattened ownership list for `_iter_subtree`;
│                     # busted on `add_parts` / `remove_parts` (incl. lazy Derivate materialize)
├── _ephemeral        # True → value carrier only, never in the graph
└── update() → [A2?] mark_dirty; value read → _ensure_fresh → _resolve_*

Shape(Entity)
└── fields via ContainerSlot (Point, Attribute, Vec2, …)
    └── _update_impl() syncs Defining inputs → **live** Derivate outputs (on pull)

SpatialFx(Entity)
└── domain pose (center/radius, pad, beam) + tick/draw; optional collidable

EventRegistration (events.py)
└── polled on flush(); not a dependency-graph node
```

`init_scena_system()` runs on `state` module import. Every non-ephemeral `Container.__init__` grabs the singleton, establishes `owner` (which calls `add_parts`), then `register_container()`.

## Roles of the main classes


| Class                 | Responsibility                                                                                                                                            |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Container**         | Tree node: ownership, value intake, formulas, graph participation, teardown                                                                               |
| **Attribute**         | Leaf Container holding a scalar / typed value (`value` / `takein`)                                                                                        |
| **Entity**        | Registry citizen: layer, groups, soft/hard remove, collidable, process host                                                                              |
| **Shape**             | Entity + PaintState; declares parts with `ContainerSlot`; implements `_update_impl`                                                                   |
| **SpatialFx**         | Entity ambient emitter; domain pose + tick/draw; no PaintState (see `spatial_fx.py`)                                                                  |
| **ContainerSlot**     | Descriptor that lazily creates a part, sets `field_type` (from `_defining_part_names` when set), wires owner, materializes live Derivates on first access |
| **ScalarAnchor**      | Graph node for a linked bare-scalar / ink field, and the node formulas that read that field depend on. Created on first `obj["field"] @=` (or when a formula reads the field), destroyed on unlink **unless another formula still reads it** — then it is only unlinked and stays a source (dropping it unlinked every reader: AC12, `test_fieldref.TestUnlinkKeepsReaders`). `_takein` writes `__dict__` / `_ink`. |
| **_PropertyAnchor**   | `ScalarAnchor` subclass for property-backed pose (`Graphic.scale` everywhere; `angle` on Point/Sprite/Svg/Text/Track/free Polygon and on derived headings — not where `angle` is a model input, a real `ScalarSlot`). `_takein` calls `setattr` so `rotate_to` / `scale_to` run. **Private** — do not promote to a general property-link primitive until a second use case appears. |
| **ScenaSystem**       | Facade: register/unregister, edges, begin_frame_batch / flush / end_frame_batch                                                                           |
| **DependencyGraph**   | `dependencies[A] = {B, C}` means A depends on B and C (B and C update first)                                                                              |
| **UpdateManager**     | `mark_dirty` (invalidate cone), `flush()` for `@when`/`@on_change`                                                                                        |
| **EventRegistration** | Polled `@when` / `@on_change` handler. Not a dependency-graph node; `flush()` walks the event list |




## Ownership tree vs dependency graph

These are related but not the same:

- **Ownership tree** (`owner` / `parts`): composition and naming (`line1.p1.x`). Managed only through the `owner` property, which calls `add_parts` / `remove_parts`. The setter validates before it mutates: an owner that is not a Container (`circle.owner = 1.0`) raises `TypeError` and leaves `_owner` untouched (storing it first once made the object read as a part, so `destroy()` refused it forever). `parts` and `field_type` are read-only properties over `_parts` / `_field_type` on every Container: rebinding `parts` (`scene.parts = [...]`, `v.parts = …`) raises `TypeError` — it would orphan the real parts — and `ship.field_type = 3` raises `AttributeError` (it silently corrupted the part's graph edges). Engine code reads and writes the private names directly, so the invalidation paths pay no property cost; a new engine site must do the same. `Container.__init__` writes its private fields with one `__dict__` update when the class's `__setattr__` is marked `_scena_private_passthrough` (closed surfaces, Entity, Point, Vec2), no slot or descriptor holds those names, and the class keeps Container's `owner` property and `_refresh_name` (`state._container_dict_init`, cached per class); on that path an ownerless object skips the `owner` setter, which would store None over None and rebuild the same name. Shape (slotted `_in_batch_update`) and classes with no Python `__setattr__` keep plain writes (a C-level write is already the cheapest). A new `__setattr__` on a Container subclass that must see private writes simply leaves the marker off. A refused write never changes the object (`tests/test_angle_field.py`, `TestRefusedWritesChangeNothing`: every kind, every reserved name, stays destroyable).
- **Dependency graph**: computation order. It includes:
  - **Structural edges** between owner and part (direction can flip)
  - **Formula edges** from a linked container (or event) to its sources

`register_container()` only adds a node. Edges are added elsewhere (structural via parts, formula via links).  
`unregister_container()` removes the node, strips all its edges, and clears it from the dirty set.

## Two kinds of dependency edges



### 1. Structural (owner ↔ part)

Entry points: `add_parts` **/** `remove_parts` **only** (also invoked by `owner` setter). Ephemeral containers skip graph edges.

Direction is **not fixed**:


| Direction    | Graph edge            | Meaning                                         | Typical when                    |
| ------------ | --------------------- | ----------------------------------------------- | ------------------------------- |
| **Downward** | owner depends on part | Part updates first, then owner’s `_update_impl` | Defining parts                  |
| **Upward**   | part depends on owner | Owner (or formula) updates first, then part     | Derivate parts; linked subtrees |


Helpers:

- `_clear_structural_edge(owned)` — remove either direction
- `_set_structural_edge(owned, upward)` — clear, then install one direction
- `_should_use_upward_edge(owned)` — decide direction from `FieldType` + formula ancestry
- `_rewire_subtree_structural_edges(upward=…)` — walk the part tree and reset edges  
  - `upward=True/False` forces that direction for the whole subtree  
  - `upward=None` chooses per edge via `_should_use_upward_edge`



### 2. Formula (linked container → sources)

Created by `assign_formula` / `@=`:

- `DirectLink(source)` — direct reference to another Container (no AST); `FieldRef` RHS resolves to that field's graph node first
- `FormulaLink(lambda)` — parses the lambda, extracts outermost Container sources (closure, default-arg captures, simple subscripts)

`FormulaLink.set_owner(owner)` registers `add_dependency(owner, source)` for each source, marks sources live (`_note_became_link_source`), and evaluates once.  
`clear()` / `unlink()` removes those edges and refreshes source liveness (`_refresh_link_source_liveness`).

## FieldType vs DependencyState

They answer different questions. Only **FieldType** and `_link` decide structural edge direction now.


|               | **FieldType**                                         | **DependencyState** (derived)                              |
| ------------- | ----------------------------------------------------- | ---------------------------------------------------------- |
| **Question**  | What is this field’s *role* in the owner’s model?     | Where does this container’s *value currently come from*?   |
| **Scope**     | Structural / declarative (slot identity)              | Introspection only — computed from `_link` + owner chain   |
| **Stability** | Mostly fixed; Line can flip via `_set_defining_parts` | Follows link install/remove automatically                  |
| **Values**    | `Defining`, `Derivate`                                | `DEPENDENT_DOWNWARD`, `DEPENDENT_UPWARD`, `LINKED_OUTWARD` |


**FieldType** = “Am I an input or an output of my owner’s `_update_impl`?”  
`_link` = “Do I have an external formula?”  
**DependencyState** = derived view (`LINKED_OUTWARD` if `_link`; else `DEPENDENT_UPWARD` if an ancestor has `_link`; else `DEPENDENT_DOWNWARD`). Prefer asserting on `_link` / graph edges in new code.

### How `_should_use_upward_edge` decides

Upward if **any** of:

1. owned `field_type == Derivate`
2. owner `field_type == Derivate` (subtree under a derived field)
3. owner has `_link`, or any ancestor of owner has `_link`



### On link / unlink

**Link (**`assign_formula`**):**

1. Build `DirectLink` or `FormulaLink`
2. **Forbid** if any ancestor or descendant already has `_link` (`LinkedAttributeError`) — at most one formula driver per ownership chain. Call `unlink_all()` first if needed.
3. Graph cycle check (`would_create_cycle`) before committing
4. Replace existing self-link with a warning if present
5. Set `_link`, `_rewire_subtree_structural_edges(upward=True)`
6. `set_owner` registers formula edges and evaluates. If that raises, the install is rolled back (`_link`, formula edges, structural rewire, and the pull-invalidate flags from before the attempt).

**Unlink:**

1. Clear formula edges via `FormulaLink.clear()`
2. `_rewire_subtree_structural_edges(upward=None)` — FieldType + remaining ancestor links decide again

`unlink_all()`**:** `unlink()` every node in `self`’s subtree that has a formula (clears the object for a parent link).

### Cycle detection

Uses the **DependencyGraph**: adding `owner → source` is rejected if `source` can already reach `owner` along dependency edges (`DependencyGraph.would_create_cycle`). Same structure the UpdateManager walks — no parallel enum walk.

## Value assignment API


| Operation                                              | Meaning                                                                                                |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `=` / `assign_value` / `<<` / `absorb`                 | Set a concrete value; raises `LinkedAttributeError` if this node, an ancestor, or a descendant is linked. `takein` is the ungated engine copy. |
| `@=` / `assign_formula`                                | Bind to another Container or a lambda; creates a link (forbids competing ancestor/descendant formulas) |
| `unlink()`                                             | Remove this node’s formula and restore structural wiring                                               |
| `unlink_all()`                                         | Remove formulas on self and all descendants                                                            |
| `clear_owner()`                                        | Detach from owner; clears structural edge; node stays registered                                       |
| `clean_up()` / `Shape.destroy()` / `State.remove(key)` | Tear down from the reactive system (see Destroy and teardown below)                                    |




## Destroy and teardown

Two different goals: stop drawing vs leave the reactive system. Mixing them up leaves dangling graph nodes or unexpectedly live links.

### Soft removal (Entity)

`Entity.undraw()` (Shape and SpatialFx) removes the object from layers so it is not drawn. The object (and its part subtree) **stays registered** in the DependencyGraph; formulas that read or write it keep working. SpatialFx also stays on the tick registry. Valid use: invisible guides, construction geometry kept only as a link source.

### Park (`active`)

`Entity.active = False` parks an Entity without teardown: no draw, no collision, owned process time pauses. `@when` / `@on_change` keep polling (watches, not owned process). Shape transients keep ticking (presentation time — finish FX with `on_done=` before park, or `clear_transients()`). Prefer park over destroy/recreate for temporary off-scene (death / restart). See [Actors Design.md — `active` (park)](Actors%20Design.md#active-park).

### Full removal


| Entry point                                                        | What it covers                                                                                                                                                                                           |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Entity.destroy()` / `Shape.destroy()` / `SpatialFx.destroy()` | Run `on_destroy` (if set) while still alive · cancel **all** process handles owned by this item (`after` / `every` / tweens / mode script) — no carve-outs for “destroy callbacks” · cancel shape transients (when applicable, no pending `on_done`) · `is_alive = False` and `active = False` (direct flags, not the park setter) · canvas undraw · id/groups · SpatialFx tick unregister · `clean_up()`. Does **not** fire `@exit_mode` |
| `Container.clean_up()`                                             | Reactive teardown only (Attribute, Point, non-Entity Containers, or when canvas is irrelevant)                                                                                                       |
| `State.remove(key)`                                                | `Attribute.clean_up()` for that variable, then drop the key from `_data`                                                                                                                                 |


`destroy()` is the author-facing “delete this drawable.” Standalone Attributes and State variables have no canvas role — use `clean_up()` / `State.remove`.

**Links and a destroyed actor.** `@=` is a write: onto a destroyed actor — an ink cell (`dead["hp"] @=`), a slot (`dead["radius"] @=`), a property anchor (`angle` / `scale`) or a part the author still holds (`dead.center @=`) — it raises `DestroyedError` and registers nothing (destroy marks the part subtree `_host_destroyed`; W2 in [Testing Design](Testing%20Design.md#w--world-machine-extensions)). Every other write on a held part refuses too: an Entity part (`center`, `p1`) is retired (`retire_part` sets `_destroyed`), and a part that is not an Entity (`ship.vel`, a Vec2) gets `_destroyed` and `_destroyed_with_host` at the same teardown step, so `held.x = 3` (`ScalarSlot.__set__`), `held += …`, `held << …` (`Vec2._takein`) and `held.do_rotation(…)` raise before they change anything, and `dead.vel += (1, 0)` refuses in the op, not after it (VI3). The refusal builds its breadcrumb (`a part of the Circle made at …`) from `_destroyed_with_host` only when it raises. Reads stay, as for any dead actor; copying from a dead part with `<<` raises (GX12), as for its `center`. A formula that names a destroyed source raises `DestroyedError` at install. A formula that raises on its first evaluation installs **nothing**: no new ink cell, no scalar anchor, no graph node (W3).

`Shape.is_alive`**:** True from construction until hard `destroy()`. Independent of `visible` and of soft `undraw()` / park (`active = False`) — those leave `is_alive` True. After `destroy`, leftover refs read `is_alive` False **and** `active` False (`active = True` does not revive). Remaining Python references are not deleted but must not be treated as live Scena objects.

### What `clean_up()` does

Order:

1. Snapshot the part subtree’s `node_id`s.
2. **External dependents**: any graph dependent *outside* the subtree whose `_link.sources` include a node being removed is **auto-unlinked** (`RuntimeWarning`). The dependent keeps its **last value** — the value of the source's *final* state (destroy pulls outside dependents after `on_destroy`, before the source reads as dead; an explicit `unlink()` also pulls first, so the frozen value never depends on who read in between — D8 in [Testing Design](Testing%20Design.md#bug-catalogue)) and remains in the graph as an ordinary (unlinked) node.
3. Recursively `clean_up()` each part.
4. `unlink()` self if linked.
5. `clear_owner()` (structural edges via `remove_parts`).
6. `unregister_container()` and clear `node_id`.

Ephemeral temps skip registration; `clean_up` only clears ownership if any.

Events use `EventRegistration.cleanup()` analogously (clear link + unregister).

### Consequences for linked scenes

```python
line = Line(p1=lambda: rect.right_center, p2=(200, 25))  # Point-level link into line.p1
rect.destroy()
# → RuntimeWarning; line.p1 unlinked; p1.x/y frozen at last takein
# → rect subtree gone from the graph; line remains drawable with frozen p1
```

- Dependents do **not** adopt the deleted object’s identity; they always owned their own parts and only copied via takein while linked.
- A **multi-source** formula (`a @= lambda: r1.x + r2.x`) is cleared **entirely** if any source is removed — not surgically rewritten. Remaining sources no longer drive `a` (same warning + last value).
- A **relational shape** (Line `parallel_to=` / `perpendicular_to=` / `circle=`, Ellipse `from_rect=`) whose reference is destroyed, or that loses its relation by `unlink_all()` / unlinking a linked part / `force=True`, becomes its free twin with its current values (`Shape._drop_relational`; [Shapes Design.md — Cross-shape relational constructors](Shapes%20Design.md#cross-shape-relational-constructors)). A **box-linked shape** (`box=lambda: …`) drops the same ways, plus its own destroy: every fitted input unlinks with its value and the fit node lets go of the region (`Shape._drop_box_fit`).



### What exclusion does *not* do

- It does not invalidate Python references you still hold; after `destroy`/`clean_up`, those objects are unregistered (`node_id is None`) and must not be treated as live graph citizens.
- It does not equal “hide” — exit transients only set `visible=False` unless the author’s `on_done` calls `destroy()`.
- `State` has no `destroy()` — naming is reserved for canvas-aware Shapes. Use `remove(key)`.



### What hard exclusion *does* for shape transients

- Cancels all active shape-transient channels on that shape with **no** remaining `on_done` callbacks.
- Sets `shape.is_alive` to False (beginner check: still a live Scena citizen?) and `active` to False.
- Soft `undraw` and `visible=False` do **not** cancel channels or flip `is_alive`.



## Update flow

**Frame batch (inside** `run()`**):** many writes → (A2: maybe) many `mark_dirty` → reads pull pure data as needed → one `flush()` for `@when` / `@on_change`.

**Eager effects (outside** `run()`**, or after** `end_frame_batch`**):** a write that `mark_dirty`s polls `@when` / `@on_change` immediately, unless it is still inside `batch_update` (one poll when the batch closes). Pure data still pulls on read. Unlinked Defining writes that skip `mark_dirty` (A2) do not poll; boxed-cell and ink writes still do, via `maybe_poll_events`.

```
value change / takein
  → Container.update()
  → [if _needs_pull_invalidate] mark_dirty(self)   # self ∪ transitive dependents
  → [if not deferring and not mid-batch: poll @when / @on_change]

Attribute.value / get_xy(bare=True) / formula evaluate
  → _ensure_fresh()  (or A3 bare path)
  → _resolve_link or _resolve_structural if dirty
  → return value   # on exception, _dirty stays set

flush()
  → poll every active @when / @on_change
       → evaluate condition (pulls sources) → maybe fire callback
```

- Unused derived work is never recomputed (cold Derivate laziness; unread linked formulas stay idle until read or an effect pulls them).
- `UpdateManager.is_updating` prevents nested effect flushes; writes during flush only `mark_dirty`.
- `@when` callbacks run during flush; `flush` re-polls the event list while anything fired, so a cascade (A's callback changes what B watches) settles in the same flush. A chain with no cycle never fires one watch twice, so it settles in the same flush however long it is. Only rounds in which a watch fires *again* count: after `FLUSH_MAX_ROUNDS` (8) such rounds, `flush` warns ("re-triggering each other") and leaves the rest for the next flush — a ping-pong cycle cannot spin. (Before 2026-10-09 every round counted, so an acyclic relay chain longer than 8 links warned "a cycle?" and its tail lagged a frame.)
- `mark_dirty` **always re-walks the cone** (cycle `seen` only). Do not short-circuit when the seed is already dirty — a prior pull may have cleared dependents. A **pull** never walks: resolvers store through `_takein_impl`, not the `_takein` dispatcher ("Pull stores raw").



## Ephemeral containers

Arithmetic temps (`Point.temp()`, `Vec2` ops, etc.) are created under `with ephemeral_creation()` (an exact `Vec2` from two finite floats gets the same state written directly: [Vec2](#vec2-scenamathpy), "Arithmetic results skip the constructor"):

- `_ephemeral = True`, `node_id = None` — never registered
- no structural or formula edges
- `update()` / recalculate stay local

This keeps the graph stable under math and keypress-driven formulas.

## Deferred trees (measured Boxes)

A measured Box (`Box._snapshot` / `Box._from_aabb`: `graphic.box`, layout
children, grid cells, `canvas.game_view` / `ui_view`, `group[...].box`,
`widget.box`, playfield copies) is a real, mutable, linkable Container that is
almost always read once and dropped. Its root carries `_graph_deferred`; while
it does, the **whole part tree stays off the graph**:

- Parts materialized under it (`ContainerSlot.__get__`) are built inside
  `_deferred_registration()` — no node, even for a Point (an Entity, which
  otherwise always registers) — and `_set_structural_edge` is a no-op
  (`_in_deferred_graph_tree()`).
- Reads pull through ownership as usual (`_ensure_fresh` needs no edge).
- Writes take `update()`'s off-graph branch: the node recomputes locally, and
  a part of a deferred tree then calls `owner.update()` — the job the
  structural edge + `mark_dirty` walk would have done (a written `box.center`
  re-derives the live corners).
- The **first registration of any node in the tree** — a link from or into it
  (`check_circular_reference` / `add_dependency` register), a `ScalarAnchor`
  on `box["width"] @=` — calls `root._join_dependency_graph()` from
  `register_container`: the flag is dropped, the root registers, and
  `_wire_structural_tree` sets every structural edge as eager materialize
  would have (per `_should_use_upward_edge`; forced upward under a Derivate
  part). From then on the tree is an ordinary one.

Why: every Container tree is a reference cycle (`_owner` ↔ `parts`, a
self-inclusive `_subtree_cache`), so refcounting never frees it; the GC
backstop below drops its nodes only at a full collection (rare once
`freeze_world` has run). Registered parts of a per-frame `graphic.box.top_left`
therefore piled up between collections and tripped the leak detector (D11 in
[Testing Design](Testing%20Design.md#d--differential-fast-vs-slow-paths)).
Weak `_owner` references were ruled out (every owner walk on the hot path,
and a held point would orphan). The Point itself is still built (~45 µs: it is
a Graphic); only the graph work is skipped.

A deferred tree is a **value in a formula chain**, never the source: the
dependency walk (`state._is_durable_source`) keeps the Container *before* it
(`canvas` for `canvas.game_view.center`, the graphic for `graphic.box.right`).
Depending on the measured Box froze the formula at the value it was linked
with and joined the throwaway into the graph on every pull (RX1, interaction
campaign class 8; `test_canvas.TestCanvasIsAFormulaSource`). The owner of a
measurement is what notifies: `canvas` (a Container since 2026-10-09) from
`_sync_camera` and the scroll advance, a Graphic from its pose writes.

Hazards: a new write path on a Container must end in `update()` (or
`mark_dirty` guarded by `_node_id`), never assume the owner has a node; a new
path that adds graph state for a node without `register_container` would skip
the join. Author `Box(center=…, …)` stays eager. Tests:
`test_box_snapshot.TestMeasuredPointsStayOffGraph` (node count flat with the
cyclic GC off) and `TestDeferredTreeStaysCorrect`.

## About @batch_update_attrs / batch_update / no_update

These flags apply to the **named container and its entire part subtree**, so leaf Attribute writes (`vec.x = …`) are suppressed too.

- `@batch_update_attrs('vec', 'center', …)` — batch those subtrees; under an outer `no_update` / already-batching owner, runs the body **without** `getattr` on named attrs (avoids force-creating cold Derivate slots). Flush `update()` on named attrs in reverse order **only if no cycle is already running** and this decorator was the outermost suppressor.
- `batch_update_self()` / `with container.batch_update()` — same for self’s subtree; one `update()` at the end
- `with container.no_update()` — suppress without flushing (used by `_recalculate_formula`)

`_restore_batch_update_subtree` restores recorded flags and clears `_in_batch_update` on nodes created during the block (lazy slots) so they match the owner’s restored flag.

Example:

```python
@batch_update_attrs('vec', 'center', 'length', 'angle', 'dx', 'dy')
def _update_impl_pointpoint(self) -> None:
    # Writes only live Derivate parts (see shapes.py)
    ...
```



## Initialization checklist

1. `init_scena_system()` — auto on import
2. `Container.__init__` — bind `_scena_system`, set `owner` (structural edges), `register_container` (skipped if ephemeral)
3. Shape / slot construction — set `field_type`, rewire Derivate / defining parts as needed
4. Optional `@=` — formula edges + forced upward rewire of the linked subtree
5. Optional `@when` / `@on_change` — EventRegistration nodes + formula edges
6. Teardown via `destroy()` / `clean_up()` — unlink, detach, unregister



# Supporting pieces (lighter)

=============================

These matter for a complete picture of the framework but are not the reactive core.

## State

`State` (`state.py`) is a dict-like bag of named standalone `Attribute`s used for app-level variables (`st.t`, constraints, formulas). It is **not** a Container and does not participate in ownership trees. Each created Attribute is registered in the DependencyGraph like any other leaf. Diagnostic label: `State(name="st")` for the builtin; unlabeled `State()` uses `"State"` so a second bag does not impersonate `st`.


| API                          | Role                                                               |
| ---------------------------- | ------------------------------------------------------------------ |
| `State(name=…)`              | Diagnostic label in linked-write errors (`hud['score'].unlink()`) |
| `st.key = …` / `create`      | Create or write the Attribute (identity stable once created). `name`, `keys`, `exists`, `create`, and `remove` are reserved. A function or method (a `lambda`, a `def`, a bound method, a builtin) raises `CallableAssignError`, like a Shape field: `=` copies a value, `st["key"] @= fn` links (Q5 of the geometry campaign; a named `def` used to be stored) |
| `st.key`                     | Read the value (pull-resolves a linked cell); same as an ink field (0.8.0) |
| `st["key"]`                  | `FieldRef`: link (`@=`), bind (widgets, `Text`), watch (`@on_change`, `@when`), `tween`, `until`; `.value` reads, `.unlink()` |
| `exists` / `keys`            | Bag introspection                                                  |
| `remove(key)`                | `clean_up()` the Attribute + drop the key (full reactive teardown) |




## Events (`@when` / `@on_change`)

`EventRegistration` is polled on `flush`. `@when` requires a bool and fires on the rising edge (False → True). A condition that is already True when the watch is registered does not fire until it goes False and then True again. `@on_change` fires whenever the watched value changes (a callback with a parameter that has no default receives the new value, a `*args` callback does too; `def f(v=None)` does not — `validate.payload_arity`). Comparison uses the payload: an `Attribute` or `FieldRef` unwraps to its value, and a `Point` / `Vec2` compares as `(x, y)`. `NaN` matches `NaN`, so a watch fires once per change, not on every poll. Equal values that differ in bool-ness are a change (`1 → True`, `0 → False`: Python's `True == 1` hid a flag that became a count; review 2026-10-09 S2-14); `10 → 10.0` is not. Errors are loud: an exception from a condition or a callback propagates out of `flush` (or out of the write that flushed, outside a frame batch); later watches run on the next poll. The edge is consumed before the callback runs, so a caught error does not refire. A non-bool `@when` is a `TypeError`, raised at registration when the seed evaluation is already non-bool (so `@when(lambda: st.lives)` fails at the decorator, not frames later); handler arity is checked there too (`check_handler_arity`). Only a destroyed source retires the watch quietly (`DestroyedError` — an `AttributeError` subclass raised by reads of a destroyed Entity — or `ReferenceError`); a typo `AttributeError` raises, at registration when the seed evaluation already fails.

Class-form `@when(lambda self: …)` / `@on_change(lambda self: …)` tags the method; construct (after `setup()`) wraps a zero-arg closure over the instance and registers with the same `EventSystem` (`kind=WHEN` / `ON_CHANGE`, `owner=` the Entity). `destroy()` drops those registrations immediately. On a later poll, a registration whose `owner.is_alive` is False still retires — so method events stay inert after `destroy()` even when the condition still reads plain Python state. Park (`active = False`) does **not** suppress firing. Class body requires a callable (no bare Attribute).

**`condition` must be a live reference, not a bare value** — `@when(True)` /
`on_change(some_attr.value)` read the value **once**, at the decoration call,
and freeze it forever (Python evaluates the argument before the decorator
ever runs); that condition can never change, so `@when` never fires and
`@on_change` fires at most never. `_validate_condition` rejects this at
registration time (`TypeError`) unless `condition` is: a callable (zero-arg,
re-evaluated every poll); a `FieldRef` (`obj["field"]`, re-reads `.value`
live); or an `Attribute` / leaf-composite `Container` (`Point`, `Vec2` —
compared by coordinates). A non-leaf `Container` (anything else with graph
structure) is also rejected — there is no live scalar to compare.

**Mutable watched values are snapshotted, not aliased.** If the watched value
is a `list` / `dict` / `set`, `EventRegistration` used to keep `self._old_value`
as the *same object* the condition returns — mutating that list/dict/set
in place (`items.append(...)`) changed `_old_value` too, so `@on_change`
compared the object against itself and never fired for in-place mutation
(only for reassignment to a new object). `_snapshot_value` makes a shallow
copy of list/dict/set values before storing them as the "old" baseline, so
in-place mutation is detected like any other change.

**A numpy bool is accepted where a Python `bool` is required** (`@when`'s
condition result). `numpy` 2.x renamed its boolean scalar type from `bool_` to
literally `bool` — a distinct class from the builtin, but with the same
`__name__` — so version-pinned `type(value).__name__ == "bool_"` checks broke
on newer numpy. The check is `type(value).__module__ == "numpy"` plus
`.item()` coercion to a real Python `bool`, which is stable across numpy
versions. Tests: `tests/test_reactive_edge_cases.py` (`TestEvents`).

## Input

`input.py` bridges OS / engine state into Scena **Containers** — `Clock`,
`KeyPressed` (`keyp`), and `Mouse`. Mutations call `Container.update()` so
dependent `@=` formulas re-pull through the same graph as geometry. Fields stay
plain properties / methods (not Attributes): authors write
`campo @= lambda: clock.time`, `lambda: keyp("D")`, or `lambda: mouse.x` —
never a raw number RHS. A **point** slot may link the Mouse container itself
(`center @= mouse`, or `Circle(center=lambda: mouse)`); `.x` / `.y` still need
a lambda. Edge / delta queries (`keyp.once`, `mouse.dx` /
`.dy`) must not drive `@=`; use `update` or `@when` instead. Unused input
Containers pay A2 (no `mark_dirty`) until something links to them.

**Level vs edge.** The datapath step `clock._tick / input` is a **sample**, not
“wait for a delta event.” GLFW move / press callbacks remain the edge path
(`update_position`, `press` / `release`, `on_mouse_move`). Separately:

- **`open_window()`** seeds OS pointer and currently-down keys into the
  Containers (`Mouse._sync_position`, `KeyPressed.seed_held`) — `dx`/`dy` stay
  0, `once` does not fire, author `on_mouse_move` does not fire. Widget / `ui`
  hover is dispatched once so HUD under the cursor is current. Script-body `@=`
  that evaluated at `(0, 0)` re-pulls here (eager, before `setup()`).
- **Each frame** after `poll_events`, world mouse is sampled again
  (change-gated) so a still cursor stays correct if the camera pans.
- **`keyp.once` / `held.once`:** a rising edge is latched in
  `_pending_edges` on `press()` (false→true) and consumed by `.once()`, even
  if `release()` already ran in the same poll. An edge lives for one frame:
  the end of `_simulate_frame` drops every unread edge (`_expire_edges`), and
  `.once()` needs a pending edge even while the keys are held, so a first read
  in a later frame is False (bug PM3). Each latched edge keeps the
  keys that were down at that press: a released chord fires only if one of
  its own keys rose while the whole chord was down, never pieced from taps
  at different moments (bug IN1). One read consumes every latched press
  that completed the chord (Cmd-L and Cmd-R tapped under a held O fire
  once, as two taps of one key do). Bare `keyp()` is level-only —
  no latch, no stickiness past an actual release. `seed_held` still does not
  manufacture an edge.
- **`Clock.mark_play_start()`** after `setup()` origins wall time so frame-1
  `dt` is a real step, not construct / window-open backlog. `tick()` still
  publishes to the graph; there is no extra “notify all consumers” pass.

**Modal mask.** A modal widget (`Menu` by default) sets `keyp` and `mouse` masked. `keyp(...)`, `keyp.once`, `keyp.held`, `mouse.press`, and `mouse.click_pos` read False / None. `press` / `release` still update the real sets, and `update()` runs when the mask toggles so an `@=` that reads `keyp` re-pulls. Lifting the mask clears edges that rose while it was on and marks keys still held as already reported (`once` does not fire). A mouse button still down stays hidden until that button goes up. Pointer position (`.x` / `.y`) is not masked. `init_scena_system()` rebinds every long-lived Container in `builtins` (`keyp`, `mouse`, `clock`, the `canvas` facade) onto the new graph. They are created once; without that rebind, `keyp.update()` would still dirty the discarded graph and a later formula would not re-pull. The rebind walks `builtins`, not a hand list: the list named three and missed `canvas` when it became a formula source, so after a graph reset every `lambda: canvas.game_view` link froze (deep serial pass, 2026-10-09; `test_reactive_edge_cases.TestGraphResetRebindsEverySource`).

A one-shot `Circle(center=(mouse.x, mouse.y))` or `Circle(center=mouse)` in
the script body is still `(0, 0)` — no window yet. Live follow is
`Circle(center=lambda: mouse)` or `center @= mouse`. Live `@=` is current
from the first drawn frame.
Author catalog: [Guia — Frame](../docs/pt/guide/index.html#frame).

## Vec2 (`scenamath.py`)

2D vector Container with Defining `x` / `y` and Derivate `length` / `angle`.
Used heavily as Shape parts and arithmetic results (`Vec2.temp`: ephemeral,
built without the constructor; below). Same takein / `@=` / `_update_impl` patterns as other
composites — Derivate `length` / `angle` refresh on read when dirty (pull).
`abs_angle_to` on a zero-length vector is `0` (no division). `reflect_about`,
`project_onto`, and `reject_from` normalize with `normalize()`. `takein` accepts
a `Vec2`, a 2-tuple, or a 2-list; a coordinate may be an `Attribute` or a
scalar anchor.

**Closed surface at no arithmetic cost.** `v.lenght = 5` raises with a
did-you-mean (Scena Design, "Entity ink vs `st`"); `length` / `angle` are
offered as near misses but not listed as writable (computed). Every arithmetic
result is a new Vec2, so the construction path must make **no `__setattr__`
call**: `Container.__init__` takes the `__dict__` path (`_container_dict_init`,
ownerless setter skip), `__new__` hands `_processed_params` through `__dict__`,
and `__init__` seals with a `__dict__` mark (unless a subclass `__init__`
wrapped by `seal_after_init` is still running; that one seals). The axes are
the setter's fast names, so `v.x = 5` pays only the Python call (~100 ns over
the open class). Measured against the open Vec2 (interleaved A/B, pristine
HEAD, 2026-10-07): `Vec2.temp`, `v + w`, `v * 2` 4–6% faster; `v.x = 5` 446 →
549 ns; frame medians of the platformer, bouncing-balls stress and `naves.py`
within noise (−1.9%, −0.2%, +0.2%; A/A ±0.5%). Guard:
`test_closed_surfaces.TestClosedVec2.test_construction_makes_no_setattr_call`.
A new engine write on the construction path goes through `__dict__`.

**Arithmetic results skip the constructor.** Author games build vectors every
frame (`vec_from_angle(a, k * dt)`, `(b - a).normalize() * speed`), so the
cost of one result is frame time. The general constructor spent ~3.2 µs on a
result that is always the same shape: `__new__`'s argument parsing, the kwargs
merge, the signature-set matching (`_extract_common_params_and_signature`
rebuilds its key sets per call), the friendly-constructor wrapper, the
`ephemeral_creation` context manager, `Container.__init__` and two
`_init_scalar` slot lookups. `Vec2.temp` now builds an exact `Vec2` from two
finite floats in one `__dict__` update from `scenamath._TEMP_STATE` (the
general path's dict, key order included; fresh `_parts`, the current
`_scena_system`, `x`, `y`). Everything else (a subclass such as `_RimPair`,
NaN / inf, no scena system) still takes the general constructor and its
errors. The first `length` / `angle` read on a free vector (no `_node_id`, no
owner, no field anchor, exact `Vec2`) stores the computed value directly when
it is finite. The general write stores the same value, but it also builds a
pose cell and queues it for the collision drain, and nothing reads that cell
for a vector with no root collider (~3.5 µs per first read). A registered,
owned or anchored vector keeps the general write. `normalize` /
`clamp_length` read `length` once. `+`, `-`, `+=`, `-=` import `Point` only off
the Vec2 branch. Measured 2026-10-16 (in-process interleaved A/B, 12 rounds,
the pristine HEAD module and the new one both loaded as fresh copies):

| Spelling | Before | After |
| --- | --- | --- |
| `Vec2.temp(1, 2)` | 3.26 µs | 0.40 µs |
| `v + w` / `v - w` | 4.28 µs | 0.96 µs |
| `v * 2` / `-v` | 3.59 µs | 0.69 µs |
| `vec_from_angle(30, 5)` | 4.11 µs | 1.12 µs |
| `v.normalize()` | 5.09 µs | 1.20 µs |
| `(v + w).length` | 9.74 µs | 2.38 µs |
| `Vec2(1, 2)` (general path, control) | 2.56 µs | 2.57 µs |

Author spellings on a `Circle` (HEAD tree against this one, three alternating
processes, median): `(b - a).normalize() * 3` 19.1 → 4.9 µs; the Duelo Warp
pull (`c.vel += vec_from_angle(heading(c, hole), k / d**3 * dt)`) 17.3 →
13.2 µs. What remains there is the owned `c.vel += …`: `__iadd__` writes
`x` / `y`, then the `Graphic.vel` setter gets the same vector back and writes
both axes again (four guarded field writes, ~8 µs). Whole game
(`game_bench.py --ab` on a temporary switch over both fast paths, 30 s,
machine under peer load, load average 4–8): `horda` work 16.4 → 13.9 ms per
frame; the Duelo draft idle on its menu (no lasers) +0.9 %, within noise.
The template is a second
copy of what the general path writes: a new private field in
`Container.__init__` or `Vec2.__init__` goes into `_TEMP_STATE` too.
`test_ephemeral_math.TestVec2TempFastPath` fails otherwise (it compares both
dicts key by key). It also checks that the first read stores what the general
write stores, minus the pose cell and the subtree cache, and that results
used in formulas and links behave as before.

**`length` / `angle` are read-only; the in-place spelling is `<<`.** A write
or link raises `DerivedAttributeError` worded by `Vec2._derived_field_message`
(an override of the `Container` hook every computed field uses — Shapes
Design, "Refusing a computed field"): `v.length = 5` names `v << vec_from_angle(v.angle, 5)`, `v.angle = 30`
names `v << vec_from_angle(30, v.length)`, `v["length"] @= …` names
`v @= lambda: vec_from_angle(angle, length)`. No `set_length` / `set_polar`
method and no writable polar fields (decided 2026-10-07): `<<` +
`vec_from_angle` already does it in place; a setter would be a second
spelling, and polar setters lose the heading at length 0 (`v.length = 0;
v.angle = 30`). A vector linked whole keeps `length` / `angle` current
("Pull stores raw").

**In-place ops check, then write.** `v += …`, `v -= …` and `v.do_rotation(…)`
compute both axes, then store them through `Vec2._store_xy`, which runs the
refusals of a plain `v.x = …` before either axis changes: a non-finite result
raises the same `ValueError` (`Circle.vel x must be a finite number` for an
actor's velocity), a computed vector (`Line(p1, p2).vec`) raises
`DerivedAttributeError`, a part of a destroyed actor raises `DestroyedError`.
The two axes are then written in one `_batch_update`, and a batched axis write
checks nothing (`_coerce_magnitude_slot(clamp=True)`, no Derivate walk under
`_in_batch_update`): before, `w += (inf, 0)` stored inf and `ship.vel += (inf,
0)` raised with x already written (VI1, VI2 in Testing Design). The finite test
is `x - x != 0.0`. The checks are paid for by the op's own reads: when the A3
cache (`_scalar_bare_ok`) holds `x` and `y` as bare Defining leaves and no
field anchor sits on them, the op reads both from `__dict__` (what
`ScalarSlot.__get__` returns there, ~12 ns against ~100 ns through the
descriptor) and `_store_xy(…, bare=True)` skips the Derivate walk; otherwise it
reads through the descriptor, which seeds the cache, and `_store_xy` reads it.
Measured against the main with the Vec2.temp fast path and the vel same-object
return (in-process interleaved A/B, 12 rounds, 2026-10-17): `c.vel += w` and
`c.vel += vec_from_angle(…)` 1.00×, `st.pos += w` 1.00×, `c.vel -= (x, y)`
0.91×, `v -= (x, y)` 0.90×, `v.do_rotation(1)` 0.94×, `v.x = …` control 1.00×.
An overflowing `int` operand raises `ValueError`, not Python's `OverflowError`
(GX15's words). A new self-modifying Vec2 method reads and stores the same way.
Engine stores of `length` / `angle` (`_update_impl`, the graph path of
`_materialize_derivate_part`) call `_write_field`, not the descriptor, so they
pass the author door's destroyed check: reading a dead actor's `vel.length`
stays legal (a dead `vel` is ownerless and off the graph, so its first read
takes the free-vector store into `__dict__`).

**Lazy graph registration.** A bare `Vec2` / `Attribute` constructed without an
`owner=` and without an inbound `@=` stays **off** the dependency graph until
it becomes an owned part or a formula source/target. Registry citizens (`Entity`
and subclasses — Shape, Sprite, SpatialFx, free `Point`) always register.
Arithmetic results still use `Vec2.temp` (ephemeral). Do not reconstruct
vectors every frame on a plain Python attribute — mutate in place (`v.x = …`,
`v.y = …`, or `v << (x, y)`). `Graphic.vel = …` always mutates the owned slot
(tuple or `Vec2` RHS). Replacing `holder.vel = Vec2(…)` each tick used to leak
graph nodes; with lazy registration those orphans never enter the graph, but
mutating remains the taught idiom.

**`ship.vel += w` writes each axis once.** `Vec2.__iadd__` / `__isub__` write
both axes (guarded, in one batch) and hand the held Vec2 back to the
`Graphic.vel` setter, which returns early on its own object. It used to write
both axes again: four guarded field writes per `+=`, all same-value no-ops.
The early return keeps the finite check, the one check a batched `+=` write
skips (`ship.vel += (inf, 0)` raises `Circle.vel x must be a finite number`;
the axis is already written when it raises, as before). The destroyed refusal
runs before the setter (the dead route map), `@=` stays refused
(`_link_refused`), and links reading `vel`, pose revisions and `@on_change`
see the same values (probe diffed against HEAD, byte-identical). Interleaved
A/B, 12 rounds, 2026-10-16: `c.vel += Vec2(…)` 7.78 → 5.68 µs, `-=` 7.76 →
5.65, the Duelo Warp line `c.vel += vec_from_angle(…)` 13.46 → 11.22,
`c.vel = c.vel` 3.20 → 1.18; `c.vel = (x, y)` 3.06 → 3.07 and
`c.vel.x += 0.001` 0.97 → 0.97 (no other path pays). Whole games, game_bench
`--ab` (horda does not write `vel`; entropia bounces and falls through it):
horda work within noise (two runs, the gap follows the pair count), entropia
5.53 → 5.52 ms. The other held parts (`center`, `rim`, Text parts) were
already free: `Container._assign_value` returns on its own object. Guard:
`tests/test_held_part_assign_back.py` (every exported Entity kind, every held
part a route assigns, assigned back to itself makes no field write; `vel +=`
semantics pinned).

**GC graph backstop (durability).** Lazy registration only defers *entry*. Once
a Container is linked or owned, it used to stay in `DependencyGraph.nodes`
forever unless the author called `destroy()` / `clean_up()`. The backstop
closes that class: `nodes` is a `weakref.WeakValueDictionary`, and each
registered Container arms a `weakref.finalize` that purges
`dependencies` / `dependents` / `order_index` when Python
reclaims the object. A Container dropped without `destroy()` / `clean_up()` is
therefore **eventually removed from the graph once Python's own GC would have
reclaimed it — no author action required**. "Eventually" means the next full
cyclic collection: a Container tree is a reference cycle, so refcounting alone
never frees it. Between collections, per-frame throwaways look like growth; the
leak detector recounts after one `gc.collect()` before it warns
(`LeakSampler.sample(recount=)`), and engine snapshots stay off the graph
([Deferred trees](#deferred-trees-measured-boxes)). Explicit `clean_up()` remains the
immediate path and detaches the finalizer. Escape hatch:
`set_graph_gc_backstop(False)` then `init_scena_system()` (mirrors
`set_lazy_container_registration`). `topological_sort` also ignores stale int
ids missing from `nodes` (defense-in-depth against dangling edge bookkeeping).
Tests: `tests/test_graph_gc_backstop.py`.

Cost: `WeakValueDictionary.get` is ~2× `dict.get` (49 vs 24 ns, Apple M4) and
sits on the `mark_dirty` walk, yet `graph-1` sierpinski depth 5 stayed inside
noise (backstop off → on, median `work_ms` ~6.6 → ~6.7 ms, same M4).

Not taken (the leak fix):

| Idea | Why not |
| --- | --- |
| Weak `nodes` alone, no finalizer purge | Dead ids stay in `dependencies` / `dependents`; in-degree goes wrong → false `CircularDependencyError` or perturbed order. The purge is what makes weak storage safe. |
| Strong `nodes` dict + finalizer | The dict entry is itself the strong reference; the finalizer can never fire. |
| `__del__` | Every Container subclass must chain `super().__del__()` forever — one missed override silently stops cleanup for that subtree; no second independent finalizer. |
| Poll-and-diff / periodic mark-and-sweep | Needs the same weak storage, adds staleness and an O(n) diff, and dangling ids between sweeps can raise a wrong `CircularDependencyError`. |
| `WeakKeyDictionary` / `WeakSet` on Containers | Containers are unhashable on purpose (`Attribute.__hash__ = None`, value `__eq__`) — the reason the graph keys by `id()`. |
| Skip registering throwaway `@=` sources (refcount heuristic) | `sink @= Vec2(…)` is a real link; whether it will be mutated is unknowable at `@=`. `sys.getrefcount` is CPython-specific and skewed by `DirectLink`'s own `lambda s=source` default. |
| Snapshot spelling at `@=` / "always call `destroy()`" | The author must remember something extra forever or it leaks — the footgun the backstop removes. |
| Tiered storage (strong for Entities, weak for the rest) | Fallback in case the weak dict cost the hot path; the gate above passed, so it would only add moving parts and drop the backstop for Entities. |

Root-coalesced finalizers (one per ownership tree instead of per node) were
measured and **deferred** — registration-time only, not on the Tier 1
`mark_dirty` path; `graph-1` stayed inside the noise band with per-node
finalizers. Construct cost (M4): 500 `Rect`s touching all 14 slots (7,500
finalizers) ~387 → ~510 ms; realistic center + vel only ~107 → ~112 ms (~4%).
Revisit only if a real scene shows material finalizer pressure.

## Appearance (`PaintState` internal)

Internal mixin on Shape: stroke/fill materials, caps/joins, blend, filters, Skia paint cache,
and the `.visual` handle. **Authors use shape properties** (`.visual`, `.fill`,
`.line_width`, `look_like`) — not the class name.

**Defaults (Shape):** `line_width` prototype is **1.5** (`DEFAULT_LINE_WIDTH` in
`style.py`; canvas bootstrap and Recipe host-width fallbacks share it). Text keeps
its own thinner default; transients keep their local fallbacks.

**Primary paint package** (`_apply_primary_paint` / `Paint` / `set_color`):

| Material | Area shape (`contrast_stroke=True`, default) | Stroke type (Line, …) |
| --- | --- | --- |
| Solid `Color` | fill + `contrast_tone` line | line only |
| `Gradient` | fill + `mean_color().darker(0.2)` line (`line_width` unchanged) | line = gradient |
| `Texture` / `ProceduralFill` | fill only | line = material |

`Paint(g, line=False)` / `Fill` skip the outline. Direct `.fill = Gradient(...)`
does not invent a stroke.

`Gradient.mean_color()` / `.darker(n)` / `.lighter(n)`: weighted stop mean, and
stop-wise tone maps returning a **new** ramp (type / size / angle preserved).

**Appearance links (since 0.9.0).** A built-in field links (`@=`) when its value is a
plain value an author derives from state: `color`, `fill`, `line`, `line_width` (Shape,
Text), Text `background`, Sprite `alpha`, `visible`, `flip_x` / `flip_y`. It stays out
when it is identity (`name`, `owner`, `parts`, `collider`), an object with a lifetime or
caches (`.visual`, `.glow`, `.shadow`, `.hue`, `.tail`, filters), an enum or stroke knob
(`dash`, `blend`, `line_cap`, `align`), physics state the engine updates (`vel`, `mass`),
or a lifecycle switch (`active`, `mode`). Those still raise with a hint to use `=` and,
when they should track state, `on_update` / `@on_change` / `@when`. Point / Anchor take
none of the new links (the engine styles a marker and shows a handle through these
setters), Track no `visible` (it moves the track between layers), Text no flip.

* **Meaning.** `obj["color"] @= f` is `obj.color = f()` re-run when the formula's
  sources change: the link writes through the setter (`_ChannelAnchor`, `state.py`),
  so a linked color under a look is exactly `set_color` under that look, and its look
  identity follows. Values are coerced as `=` coerces them; a size (`line_width`)
  reads 0 below zero and an amount (`alpha`) clamps to [0, 1], as formulas do (Scena
  Design — Numbers). The anchor compares with the value it wrote last, never the
  getter: a `Color` has no value equality (it compares by RGBA, alpha included) and a
  parked actor's `visible` reads `False`.
* **Link targets only.** A formula that reads `a.color` / `a.visible` follows `a` as
  before (formula source extraction skips `_TARGET_ONLY_LINKS`); `b["color"] @=
  a["color"]` raises with "link both fields to the same formula". As a source, no paint
  writer would dirty the field.
* **Exclusive.** A plain write to a linked field raises `LinkedAttributeError` before
  anything is written (`_refuse_linked_channel`): `.color =`, `set_color`, `.fill =` /
  `.line =`, Shape `set_alpha`, a look that brings its own color (`Paint` / `Fill` /
  `Stroke`, a seeded `Neon("red")`), Text `color` / `background`, Sprite `alpha`,
  `visible`, the flips, `SpriteButton.enabled`. Engine writes pass: the link's own
  (`_writing`), a look applying itself (`_in_visual_apply`), park
  (`_engine_flag_write`). `color` writes the fill package, so it excludes a linked
  `fill` / `line` at link time in both orders (`_paint_fields`; on Text, `fill` only).
* **When the value is taken.** Getters pull on read. The draw-head refresh
  (`refresh_linked_channels`, head of `_draw_frame`) pulls every linked field before
  culling, list building and look grouping read them, so a write anywhere in the frame
  (update, a handler, flush, a pre-draw `on_done`) is drawn that frame. `visible` is
  also refreshed at the start of hover, so hover and clicks see a write made in update
  or a collision handler. A look going on (`visual =`, `_reapply_visual`) pulls first;
  nothing pulls inside a look's apply (the identity would miss the write). Flips are
  pose: `_pull_property_anchors` pulls them before draw, collision and hit-test. The
  refreshes skip parked and destroyed hosts (Laws L3, L4). These are pulls where they
  are called, not a phase (Laws F2).
* **Copies.** `look_like` / `restore_visual` write under a linked field, then the link
  writes it back; `clone()`, `look_like(other)` and `save_visual` pull the source
  first. The copy has no link (Shapes Design — A copy has no links). An act's link on
  a game object leaves with the act and gives back the field's value (PA1).
* **Lifetime.** On resume a linked `visible` takes its formula's value, not the stash.
  A verb that shows or hides at its end (`fade_in` / `fade_out`, `dissolve_in` /
  `dissolve_out`, `implode`) refuses a linked `visible` at the call: its finish
  swallows errors, so a refusal there would leave the shape shown with no word.
  Linking `visible` while one runs refuses too.
* **Not tweened.** `tween(shape["color"])` / `["visible"]` / a flip raise with the
  pattern: tween a color cell and link the color to it (`st.c = Color("red");
  tween(st["c"], Color("blue"), time=1); shape["color"] @= lambda: st.c`). `line_width`
  and `alpha` tween like any number.
* **Cost.** An unlinked object pays one slot read in the setters and getters
  (`self._alinks`, a `PaintState` slot set when an appearance link is made, sticky:
  ≈2 ns, where `self.__dict__.get("_field_anchors")` cost ≈18 ns, +60 % on a bare
  getter — measured 2026-10-15) and nothing on the draw path; the refresh walks only
  the hosts that have a link (`_LINKED_CHANNEL_HOSTS`). A linked field that changes
  every frame costs what a formula costs: 1000 shapes whose `fill` follows one cell
  changing every frame draw in ≈21.8 ms/frame, ≈17.7 ms when `update()` writes each
  shape's color itself, ≈10.6 ms when `update()` computes one color for all (this
  machine, 2026-10-15) — a link evaluates per shape.

Guard: `tests/test_paint_flag_links.py` (every wrong implementation above has a
canary). Custom entity ink (`ship.hp`) and geometry slots (`rect.width`,
`line.p1.x`, `rect["angle"]`) link as before. `scale` (every Graphic) and `angle` on
Point/Sprite/Svg/Text/Track/free Polygon (and derived headings) stay property-backed via
`_PropertyAnchor` (the heading turns about the center — a Text's anchor);
where `angle` is a model input it is a plain `ScalarSlot` that keeps the placement point.
`rotation` is retired on Graphics ([Shapes Design — Geometry contract](Shapes%20Design.md#geometry-contract)).
Full inventory, quality ladder, and cost model:
[Effect System Design.md](Effect%20System%20Design.md).

## MovementController

**Removed** (Reactive Model Redesign, Decision 11). `Attribute.cycle` / `sway` / `span` and `ConstraintType` are gone, not shimmed. Widgets no longer write through that helper.

# Pull reactivity (engine contract)

==================================

Implemented as an atomic swap in `state.py` (no feature flag). Author rule:
**if you read it, it's current**; `@when` / `@on_change` still fire once per
frame before draw inside `run()`.

## Why the engine stays small

1. Every Attribute arithmetic/comparison already goes through `.value`. If
  `.value` pull-resolves first, formulas and `@when` conditions become
   pull-correct without rewriting `FormulaLink` / shapes.
2. The **existing structural dependency graph** is the invalidate cone:
  Defining edges make the owner a dependent of the part; Derivate edges make
   the part a dependent of the owner. Walking `dependents` from a written leaf
   reaches live Derivates and external `@=` targets.



## Per-node / manager state


| Field             | Role                                                              |
| ----------------- | ----------------------------------------------------------------- |
| `_dirty`          | Something upstream may have changed since last resolve            |
| `_resolving`      | Re-entrancy guard during `_resolve_link` / `_resolve_structural`  |




## `mark_dirty` must re-walk

Do **not** early-return the whole walk when the seed is already `_dirty`. A
prior pull may have cleared dirty on some dependents while an ancestor stayed
dirty; the next write must re-invalidate the cone (`seen` only prevents
cycles). Otherwise second writes fail to refresh already-resolved linked sinks.

The walk is still **unconditional and full** (Tier 1 did not change that fence).
Tier 1 only makes each visited node cheaper: `_dirty` is written via
`__dict__` (bypass Entity / Point `__setattr__`) and graph maps are hoisted
into locals. Semantics unchanged.

## Pull stores raw

The re-walk above is affordable because it happens **once per write**. A pull
(`_resolve_link`, and the container branch of `DirectLink.evaluate_and_update`)
must store its result through `_takein_impl` — the raw hook — never the
`_takein` dispatcher. The write that dirtied the node already walked its cone;
the dispatcher (`Point._takein` → `update()`, or the nested-batch
`mark_dirty`) would walk it again on **every read**: O(cone) per pull, ~2×
draw on deep `@=` trees (B1 in Testing Design: sierpinski 7 → 15 ms after the
`takein` → `_takein` rename silently re-pointed these calls).

A raw store must still keep the node's **own** Derivates in step: it skips
`_update_impl`, which is where they are normally recomputed. After a raw x / y
store, `Vec2._sync_computed` rewrites a computed `length` / `angle` (computed =
read once, in `_derivate_state`, or stored by `_update_impl`); it runs from
`Vec2._takein_impl` (a link on the whole vector) and from
`ScalarAnchor._takein_impl` (a link on one field) through the
`Container._sync_computed` hook (None on classes with nothing to sync). A
Derivate of a linked leaf never read yet is computed on its first read
(`_refresh_scalar`). Without that, a vector linked whole read `length` 0.0
(D12 in Testing Design). The pulled value also obeys the slot's
`minimum` / `maximum` (Track `begin` / `end` 0..1, Circle `spread` ≤ 360): a
link clamps where `=` would clamp or raise (D14), and a float that is NaN or
infinite raises `ValueError` on a scalar field as `=` does (D16; a pair store
is not checked, like `<<`).

**A refresh never marks a linked part clean.** After an owner refreshes
(`_resolve_structural`, `_resolve_link`, `DirectLink.evaluate_and_update`) it
clears `_dirty` on its subtree through `Container._clear_subtree_dirty`, which
skips any part with its own `_link` (a `ScalarAnchor` of `ship["hp"] @= …`, a
part linked on its own): such a part pulls only when dirty, and the owner's
`_update_impl` does not necessarily read it. Clearing it froze the old value
until the next source change (`r.width` read before `r.hp`, D13). Guard:
`tests/test_diff_link_write.py` (every model × Defining field, linked vs
written, plus linked ink).

**A whole-object pull refreshes the Derivates already read.** `d @= s` (a
DirectLink) and `d @= lambda: s` store through `_takein_impl`, which writes
only the Defining inputs, inside `_no_update`; the caller then clears the
subtree's dirty bits. `Container._refresh_after_raw_store` runs the node's own
`_update_impl` between the two, so a live Derivate (`d.top_right` read
before) follows (D19). Only nodes with parts reach it: Point / Vec2 /
ScalarAnchor sinks keep the leaf fast path.

**A linked heading is pulled before the points it rewrites are read.** Where
`angle` is derived (a `p1,p2` Line, a Circle by its rim, an Ellipse by its
foci, a Rect spine), `shape["angle"] @=` drives `rotate_to` through a
`_PropertyAnchor`: the points move only when the anchor is pulled. Three rules
keep a read fresh (D18): `_pull_heading` runs before a structural resolve and
before a Derivate is materialized, never inside the shape's own update batch
(there `angle` is stored, not applied); the points the turn rewrites carry
`_pull_owner`, which keeps them off the bare-read fast path so a read of them
resolves the owner first (`_pull_owner_first`; classification is once per node,
so a plain Defining read stays free); a Derivate with its own structure
(`vec`) asks its owner too. The same parts are why the heading link and a link
on one of them are exclusive, refused at the second `@=` (D17,
`_heading_driven_parts`). So is a part the heading is measured from that the
turn does not rewrite (`_heading_pivot_inputs`: a rim-placed Circle's
`center`). Linked with the heading, each move of that part turned the shape
again from wherever it was last read, so the result depended on which frames
read it: the radius followed the center's path as far as reads had seen it
(45.8 unread vs 28.0 read, same final cell; GR19). The engine applies a
part's own link before the turn that reads it, so the turn uses the current
pivot. Guard: `tests/test_heading_link.py` (finds the inputs by writing each
one and watching `angle`).

Not covered by this rule: Derivate-part refreshes (`_refresh_*` in shapes /
box under `_no_update`) call the dispatcher on purpose — a refreshed part must
notify its own outbound consumers ("Dirty fan-out level mismatch" in Difficult areas).
Guard: `tests/test_pull_no_invalidate.py`.

## Honest tradeoff

Write-time `mark_dirty` is a coarse "maybe stale" flag — it over-marks versus
hop-by-hop change-gated push. Scena formula chains are shallow, so redundant
recomputes stay cheap. **Epoch / version change-gating (v2) is deferred** —
the over-mark is not where time goes (graph flush ≈ 0: `graph-1` sierpinski
depth 5, 0.003 ms of 7.2 ms `work_ms`, Apple M4, after the Tier 1 micro-opts),
and a boolean short-circuit of the dirty walk is unsound under conditional
formulas: a pull resolves only the branch the formula read, so a still-dirty
node can sit above clean sinks, and stopping the walk there leaves them stale
(the case [`mark_dirty` must re-walk](#mark_dirty-must-re-walk) guards). Real
v2 would need dynamic dependency versioning, not a patch on the boolean flag.

# Pose performance (A1–A4)

==========================

## Problem

Unlinked motion (`move_to` / `rotate_by` with **zero** `@=` consumers) still paid
Attribute write/read and `mark_dirty` tax. Isolation
(`scripts/bench/isolat.py`, 200 rects / 100 movers) showed reactive ~5–6×
slower than float `SimpleRect` / raw Skia — cost was graph machinery, not
formula evaluation. Separately, `Line(p1=…, p2=…)` `move_to` spiked
`work_ms` (~3.3 ms at n=80) while `draw_ms` stayed flat — pose write tax, not
draw (pose write tax, not draw — A4 below).

## Solution (author API unchanged)


| Path   | Mechanism                                                                                                                                                                 |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A1** | Absolute pose writes; when `_requires_pull_invalidate()` is false, skip `batch_update` / link scans and write Defining leaves via `_takein_xy_float` / `_translate_point_float` (float-only; no Attribute unpack). `MovementController` is allocated on first `cycle` / `sway` / `span` / constraints |
| **A2** | Sticky `_needs_pull_invalidate` on ownership root; `Container.update()` / `Attribute.takein` skip `mark_dirty` until flagged                                              |
| **A3** | `_bare_attr` / `_bare_num` / `get_xy(..., bare=True)` read Defining `_raw_value` when `_bare_ok` (no formula ancestor / Derivate root); cache invalidated on link changes |
| **A4** | Extend A1 to **multi-point / non-canonical models** and **Sprite**: shared `_pose_fast_ok` + `_translate_points_float`; `_move_to` applies both axes in **one** translate (not two sequential `_move_by` calls). When the pull flag is set, fall back to batched `Point.takein` so outbound `@=` stays fresh |


Fast paths cover:

- Center models: `Rect`/`Square` `CENTER_WH`, `Circle` `CENTER_RADIUS`,
  `RegularPolygon`/`Triangle` center models, `Ellipse`
  `CENTER_WH`/`FROM_RECT`, `Line` `CENTER_LENGTH_ANGLE`, **`Sprite.center`**
- Two-point models: `Line` `POINT_POINT`, `Circle` `TWO_POINTS` /
  `CENTER_PERIMETER`, `Ellipse` `FOCAL_POINTS`, `Rect` `CORNER_CORNER` /
  `SPINE`
- One-point models: `Line` `POINT_VEC` / `POINT_ANGLE_LENGTH` / `POINT_DX_DY`
  / parallel·perp·tangent-point, `Rect` `TOP_LEFT_WH` / `POINT_VEC`,
  `RegularPolygon` `VERTEX_SIDE`

Helpers live in `shapes.py`: `_pose_fast_ok`, `_takein_xy_float`,
`_translate_point_float`, `_translate_points_float`. Linked / Derivate-live
shapes use the batched Attribute path. Unlinked mass motion also uses lazy
`MovementController` — **Mass sprite hot path**. Tests:
`tests/test_pose_fast_path.py`, `tests/test_pose_link_contract.py`.

**Cold `_center_xy` (required for A4):** public `Shape.move_to` always reads
`_center_xy()` before `_move_to`. Line / Circle `TWO_POINTS` / Ellipse
`FOCAL_POINTS` / RegularPolygon `VERTEX_SIDE` override `_center_xy` to use
Defining geometry (`_segment_xy`, foci midpoint, `_placement_params`) so the
read does **not** materialize Derivate `center`. Ellipse `FOCAL_POINTS` and
Rect `SPINE` ctors seed `_pose_rotation` from Defining foci / p1→p2 instead of
`_bare_num(self.angle)`. Rect also exposes `_collision_pose_extra` from
`_oriented_frame` so cold Derivate `width`/`angle` do not poison pose keys.

**Engine readers stay cold (draw / FX / cull, 2026-09):** the first `getattr`
of a cold Derivate part (Line `center` / `length` / `vec`, Square `width` /
`height`, …) materializes it and sets `_needs_pull_invalidate` on the
ownership root **for good** — every later `move_to` / `rotate_by` takes the
batched path (`mark_dirty` per write). Engine helpers that only need numbers
must read Defining geometry instead: `_segment_xy()` (Line), `_center_xy()`
(any Shape), `_oriented_frame()` (Rect / Square / Ellipse). Gate
`_oriented_frame` on `_defining_part_names` — Sprite also has it, but its
frame is scaled, not `width`/`height`. Keep the `getattr` path only as the
fallback for hosts without those methods. Covered today:
`canvas._approx_draw_aabb`, `visuals._aura_anchor`, `CheapGlow._host_radius`,
`transients.shape_pivot` (→ `recipes._center_radius`),
`style._local_half_extents`; since 2026-09-26 also every collision reader (proxy, snapshot, pose key via `_center_xy`), Circle / Line draw, the Ellipse hit test, and the pose verbs (`_rotation_value`, `Rect._wh_signed`, Line `rotate_to`, Polygon `_move_to`); since 2026-10-08 the pointer hit test and `is_collapsed` of Line / Circle / Ellipse / RegularPolygon (one hover had woken a RegularPolygon for good: `move_by` + `rotate_by` 2.8 → 58 µs; graphics review SC6 / SB8). RegularPolygon hit-tests closed-form vertices from `_placement_params()` (its `points` builds a Point per vertex). Cold helpers: `_center_xy` (Polygon: vertex average), `Circle._radius_value`, `Shape._rotation_value`, Ellipse focal `_oriented_frame`. Guard: `tests/test_diff_pose.TestEngineReadersStayCold` (readers include the hit test and `is_collapsed`; models include every fresh-fast kind of `geometry_support.KINDS`) fails on any reader or verb that warms a fresh shape of any model, and `test_write_path_guards.TestEngineReadersReadDefiningInputs` refuses a public Derivate read in a `_hit_test*` / `is_collapsed` statically (D3 in [Testing Design](Testing%20Design.md#bug-catalogue)). Symptom when violated: idle FPS steps down
once after a look is shown and never recovers, although inventory (visuals,
filters, post stack) is clean — shape_fx lost ~15% after cycling visuals
(12 Lines). Diagnose by profiling idle frames before/after: `mark_dirty` and
`_move_by_batched` / `_rotate_by_batched` call counts rise per frame. Test:
`tests/test_pose_fast_path.py` (`TestDrawHelpersKeepDerivatesCold`).

## Results (dev machine; target is ~3–10× slower)

Isolat reactive moving: ~354 → ~**840** fps (~2.2× raw, was ~5.8×). Profile:
update ~0.27 ms, `mark_dirty` **0**/frame. Scene demo baseline / default `post`
are update-cheap; **GlowFilter** remains GPU-bound when enabled. Product **60 fps
is on the target machine** — use these benches as *ratios*, not absolute headroom.
Re-bench: `python scripts/bench/isolat.py --bench --suite`,
`python scripts/bench/historical/scene_demo.py --bench --suite`.
A4 gate: `perf_shape_draw.py` `line_plain_move` `work_ms` should drop toward
`circle_plain_move` (pose, not draw).

## Batched leaf writes must still notify consumers

`Point` / pose code often write `x`/`y` under `batch_update`. Silent
`Attribute._takein` **without** leaf `mark_dirty` breaks outbound `@=`
(`sink["x"] @= lambda: rect.center.x`) and Point-level links (`Line(p1=lambda: rect.center)`),
because `mark_dirty(Rect)` does **not** reach dependents of `center.x` / `center`.

**Invariant:** when `_requires_pull_invalidate()` is true, leaf writes use
`Attribute.takein` / `Point.takein` (batched path still `mark_dirty`s the leaf),
and nested `Point.takein` under an outer batch also `mark_dirty`s the Point.
Unlinked A1/A4 fast paths may keep raw `_takein_xy_float` — they **only** run
when `_pose_fast_ok` is true (`not force and not _requires_pull_invalidate()`).

**A field read by a link (`q["x"] @= p["x"]`).** `p["x"]` used as a link
source is a source-only `ScalarAnchor`, a part of `p`. On a **Defining**
field it keeps the downward edge (`p` depends on it; a part's own formula may
read its owner's Defining field — PARALLEL_DIST `p1` reads `dist` — so an
upward edge would be a cycle), so `mark_dirty(p)` does not reach it: every
writer that stores the field raw notifies it, as `=` (`_write_field`) does.
The write dispatchers do it — `Point._takein`, `Vec2._takein`, and
`Container._takein` (`<<`, `absorb`, a part `=`) for every node of the copied
subtree — through `state._notify_source_anchors`, never a pull (pulls store
raw). Text's raw publish writers treat a point with field anchors as read by
a link (`text._read_by_a_link`). On a **Derivate** field
(`k["radius"] @= line["length"]`) the anchor depends on its owner (upward
edge; `ScalarAnchor._derivate_field`), and a read of the field through a
dirty source-only anchor recomputes it. Before 2026-10-09 only `=` notified:
62 of 108 writer × kind cells left the link stale, and a link on a Derivate
froze the field for every reader (review S5-1, S5-2, S6-5). Guard:
`tests/test_diff_link_write.py` (`TestFieldRefSourceFollowsEveryWriter`).

**One storage per flag.** A name in a `__slots__` of Shape's MRO
(`_in_batch_update`, `_active`, …) is read and written as an attribute
(`getattr` / `object.__setattr__`), never through `__dict__`: a dict write is
shadowed by the slot, a dict read misses it. The batch flag read from
`__dict__` made handlers flush mid-batch outside a frame and see a pose that
never existed (S5-4). Guard: `tests/test_write_path_guards.py`
(`TestNoDictAccessToASlot`, names from the classes).

**Unlink never fails on its own link.** `unlink()` (and `destroy()`, which
unlinks) pulls first and keeps the last good value on **any** error from the
pull — a refused value or a formula that raises (`KeyError`, …); the anchor
is cleaned up in a `finally` (S5-5). A property-backed anchor's pull
(`angle`, `scale`) applies the Numbers rule like `=` (S5-3).

**Sprite hazard (fixed in A4):** `Sprite._move_by` / `_move_to` once always used
`_takein_xy_float`, so outbound `sink["center"] @= lambda: sprite.center` went stale after the
first move. Sprite must use the same `_pose_fast_ok` split as Circle/Rect.

**Pose rotation / scale notify (Tier 1.2):** `_pose_rotation_set` /
`_pose_scale_set` skip `_notify_property_anchor` when the stored `_rotation` /
`_scale` value is unchanged (common when `_update_impl` echoes Defining
rotation into the CTM field). Notify **must** still fire whenever the value
could differ — author `rotate_to` / `scale_to`, SPINE Derivate rotation, etc.
Tests: `tests/test_change_gated_update.py` (`TestPoseRotationNotifyChangeGate`),
`tests/test_reactive_tier1_characterization.py`.

# Difficult / bug-prone areas

=============================

These edges caused real regressions. Treat them as design constraints.

### 1. Accidental Derivate materialization

Any `getattr(shape, derivate_name)` at ctor / `_set_defining_parts` /
transform setup materializes the slot, marks it live, and **flags the whole
ownership tree for pull invalidate**. Symptoms: A2 ineffective, `mark_dirty`
every frame, scene FPS collapses while Rect-only isolat stays fine.
**Rule:** only materialize Defining parts in setup; use `__dict__.get` or
explicit Defining name lists. A rejected `part = …` / `obj["part"] @=` on a
Derivate must not be the thing that materializes it.

### 2. Wrong pivot for `move_to` (RegularPolygon)

Irregular `Polygon._move_to` reads Derivate `centroid`. `RegularPolygon`
inherits that unless overridden — materializing `centroid` every move.
**Rule:** center-model regular polys move/rotate about Defining `center`.

### 3. Dirty fan-out level mismatch

Graph dependents hang off the **node that was linked** (often `center.x` or
`center`), not the Shape. Batched pose that only `update()`s the Shape leaves
outbound sinks stale.
**Rule:** leaf/`Point` `mark_dirty` when pull consumers exist (see Pose
performance).

### 4. Cold vs live Derivate after `show_points` / `no_points`

Debug markers set `_derivate_live`; clearing visibility must not freeze
geometry if an external link still depends on the part. Reshow must revive
liveness for named markers.

### 5. Sticky `_needs_pull_invalidate`

Once true, stays true for the root's lifetime (no consumer refcount). First
accidental materialize permanently pays graph cost. Prefer preventing false
flags over an "unflag" API.

### 6. `force=True` unlinks

`move_to(..., force=True)` may drop inbound links (`RuntimeWarning`). Tests
should `assertWarns`; authors treat force as an escape hatch, not a hot path.

### 7. Effects vs data timing

Pure data is pull-fresh; `@when` is not. Mid-`update` side effects need an
explicit `flush()` while a frame batch is open. Outside `run()`, a
pull-invalidating write polls watches itself. Do not reintroduce "data waits
for flush" (old push contract). A failed pull leaves the node dirty so the
next read retries; do not clear `_dirty` in a `finally` that also runs on
exception.

### 8. Bare-float pose without a pull-invalidate gate

`_takein_xy_float` / `_translate_point_float` skip `mark_dirty`. Using them
when an outbound `@=` (or live Derivate) already set
`_needs_pull_invalidate` leaves sinks stale with **no error** — the Sprite
pre-A4 bug. **Rule:** every pose fast path gates on `_pose_fast_ok` (or the
equivalent `not force and not _requires_pull_invalidate()`); linked motion
must `Point.takein` under batch. A writer that skips the graph for a reason
of its own (Text's lazy layout, which publishes its points as floats) gates on
the per-node `_link_source` flag instead: `_note_became_link_source` sets it
when a link first reads the node, `_refresh_link_source_liveness` clears it
when the last outside reader unlinks. Text's moves wrote raw with no gate, and
a direct link to a centred caption's `center` stayed put (D25). An anchored caption's `center` is written by the layout itself: when a link first reads it, it gets an edge on the caption and `_pull_owner` (Text `_part_became_link_source`, the D18 pattern), so a move or a new string dirties its readers and a read re-lays out first (D26).
**Guard:** `tests/test_write_path_guards.py` — every raw pose write sits behind
one of these gates; every raw `__dict__` store of a field, every `_dirty`
write and every point reader is allowlisted with its reason.

### 9. The write paths stay separate (by design)

Plain `=` (fast and full branch), constructor, batch refresh, link pull, copy
(`_takein_impl`) and the pose fast paths are separate on purpose: each fast
path exists for per-frame cost. Merging them was evaluated (Track C item 5)
and declined: the bugs came from rules or refreshes living on one path, not
from the paths being separate. Instead the rules are on the slot (one
coercion, D22), refreshes are hooks (`_sync_computed`,
`_refresh_after_raw_store`, `_pull_heading`), and the static guards above make
a new bypass fail a test. Revisit a merge only if a bug traces to the split.

# Deferred: float pose + promotion (B1)

======================================

**Not implemented.** Idea: store unlinked pose as plain floats; promote parts
into Attributes on first real demand (`@=` either way, ctor capture,
`show_handles()`, …). Acceptance would be isolat within ~1.2× simple/raw.

**Why deferred:** A1–A4 keep a **single** Attribute representation and already
closed most of the motion gap. [Sprite Design.md — Mass sprite hot path](Sprite%20Design.md#mass-sprite-hot-path) then made unlinked
Attributes cheaper (`_takein_float`, lazy `MovementController`) without dual
storage. B1 is philosophically "pay for the graph only when used," but as a
bolt-on it adds dual storage and a promotion boundary — the same bug class as
above, multiplied. Dev-machine headroom is large; on the slower **target**,
GlowFilter / GPU / author `on_update` usually dominate before Attribute object
tax. Contract oracle: `tests/test_pose_fast_path.py` (`TestB1PromotionContract`).
Do not land B1 without a target-machine scene that is demonstrably
**update-bound** after A and the mass-sprite work. Index: [Fences.md](Fences.md).
Concretely: `type(sprite.center.x)` would change after the first link, `move_by` /
draw / collision / clone would each need two implementations, and an accidental
promotion (`print(sprite.center)`) keeps the slow path for life. The other
mass-sprite rejects (second Sprite type, pool / SoA, forced rect hitbox) and their
reasons: [Sprite Design.md — Sprite fences](Sprite%20Design.md#sprite-fences).
