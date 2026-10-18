# Actors Design

Identity (`Entity`), behaviour (process: timers, modes, tweens, async), groups,
ink, and modes. **Happy path for this subsystem** — pick one row; do not read
the rest. Sprite body / hitbox / clone: [Sprite Design.md](Sprite%20Design.md).
Collision engine: [Collision Design.md](Collision%20Design.md). Hub:
[Scena Design.md](Scena%20Design.md). Author calls:
[Guia da API](../docs/pt/guide/index.html#agendar).

Today’s baseline, not a freeze — [Scena Design.md](Scena%20Design.md#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Entity / `active` / ink | [Architecture](#architecture), [Ink](#ink), [`active`](#active-park) |
| Groups / fleet | [Groups are tags](#groups-are-tags), [Fleet helpers](#fleet-helpers-groups), [Group fences](#group-fences) |
| Formula groups | [Formula groups](#formula-groups) |
| Modes / `@on_mode` / `@exit_mode` | [Mode enter / exit](#mode-enter--exit) |
| Async wait / helpers | [Process semantics](#process-semantics) |
| Method decorators | [Method decorators](#method-decorators-every--after--collide_with--when--on_change) |
| Ownership / tracks | [Tracks](#tracks), [Ownership](#ownership-no-on) |
| Frame order | [Frame order](#frame-order) (canonical: [Scena Design.md — Datapath](Scena%20Design.md#datapath)) |
| Maintainer notes | [Implementation notes](#implementation-notes-maintainers) |

## Use

1. Pick one jump-box row.
2. Read that section only (search; do not read the rest of this file). Treat fences there as current constraints.
3. Open **Start** only if the section is not enough.
4. Open **Also** / another Design doc only if Start is not enough.
5. Stop. Do not ingest `scripts/`, Sprite Design, or the private archive / proposals unless the body/hitbox is the task.

## Router

| Need | Start | Also |
| --- | --- | --- |
| `Entity`, ink, construct | `entity.py` | `place.py` |
| `group["name"]` / formula `@=` | `registry.py` (`GroupOperator`) | `process.py` (`until_empty`) |
| `after` / `every` / tween / modes | `process.py` | `easing.py` |
| `@when` / `@on_change` | `events.py` | `state.py` |
| `@collide*` **sugar** | `interaction.py` | `collision.py` (engine) |

## Do not confuse

| Looks like | Is actually | Not |
| --- | --- | --- |
| `@when` | `events.py` (flush) | `process.py` (timers/tweens) |
| Groups | tags and queries | process owners (`every` / `on_update`) |
| `group("name")` | migration `TypeError` | `group["name"]` |
| `group["name"] @=` | `GroupOperator` (`registry.py`) | Attribute / `FieldRef` (`state.py`) |
| Ink (`ship.hp`) | Entity field | `.visual` / paint |
| Sprite body | [Sprite Design.md](Sprite%20Design.md) | this file |

## Not in this doc

- Class tree (full) → [Scena Design.md](Scena%20Design.md#class-tree-selected)
- Sprite / Sheet / hitbox / clone / mass path → [Sprite Design.md](Sprite%20Design.md)
- Collision engine → [Collision Design.md](Collision%20Design.md)
- Measuring `group[...].box` → [Box Design.md](Box%20Design.md#bridge)
- Follow math (`chase` / `approach` / `deadzone`) → [Canvas Design.md](Canvas%20Design.md#follow-math-chase--deadzone)
- Author catalogs → [Guia da API](../docs/pt/guide/index.html#agendar) (process), [Guia da API](../docs/pt/guide/index.html#desenhar-entity) (Entity)


# Actors (Entity, Process)

===============================

Identity (`Entity`) and behaviour (process: timers, modes, tweens, async).
Rejected process names (`state`, `on_hit`, `remove`) are **not** Scena API.
Taught fleet sample: `examples/app_galaga.py`. Smoke scripts are visual
tests, not idiomatic references.

## Architecture

```
Container
  └── Entity              identity, groups/tags, layer, visible, destroy,
                          process host, ink, active
        ├── Graphic       pose, filters, transients, .visual, stamps   (ABC, not constructed)
        │     ├── Shape   geometric models, path, handles
        │     ├── Sprite  sheet, frames, play, image body
        │     └── Text    caption (HUD ``ui`` or world); ``\n`` is a hard break (no wrap); optional ``width=`` / ``align=``; glow= only (no .visual)
        ├── SpatialFx     no Graphic; full process surface still (timed Rain)
        └── UIWidget      HUD control (Button, Slider, …); drawn by WidgetManager,
                          not a registry layer. ``layer=`` and ``collidable=True`` raise
```

**Entity is the registry citizen.** `Shape` and `Sprite` are entities that draw. Bare
`Entity()` is the same object with no visual (`layer=None`). Do not invent a parallel
Entity type that also has layer / groups / destroy. `UIWidget` is an Entity
(not a Graphic), same idea as `SpatialFx`: groups, `visible`, `destroy()`, timers.
It always draws in the HUD. `visible=False` also drops pointer and key input.

Prepared for multi-body later (an Entity may own children with offsets). Today: one
costume `.visual` per Graphic (or none). Appearance stamps (`.glow` / `.shadow` /
`.hue` / `.tail`) compose around that costume.

| Check | Meaning |
|-------|---------|
| `isinstance(x, Entity)` | Registry citizen (Circle, Sprite, SpatialFx, UIWidget, bare Entity) |
| `isinstance(x, Graphic)` | Can flash, glow, tween pose |
| `isinstance(x, Shape)` | **False** for Sprite. `@click` accepts Graphic (Shape and Sprite), not SpatialFx, UIWidget, or bare Entity. A group passed to `@click` skips widget members. `@collide` accepts Entity but skips widgets (`collidable=True` raises) |

SpatialFx stays an Entity so `rain.after` / `rain.every` / `rain.destroy` / groups / tags
work. It does not grow HP / hitbox / look APIs.

## Current design choices

These are today’s choices, not irrevocable commitments. Challenge them when a better design is worth the cost ([open design](Scena%20Design.md#design-documents-are-descriptions-not-locks)).

| Topic | Choice |
|-------|--------|
| Registry citizen | **`Entity`** (layer, groups, visible, destroy, process host, ink) |
| Shape / Sprite share | Internal ABC **`Graphic`**. Not a public constructor. Not named Looks. |
| Body-less entity | Bare **`Entity()`** — no draw, `layer=None`. Spawners, directors. |
| Vocabulary | **Entity** = registry citizen; **Graphic** = drawable pose body. Do not use "actor" as jargon. |
| Tags | **Groups.** Lookup is `group["name"]` (`group("name")` raises). `tag` / `untag` / `tagged` are sugar. No second hashtag system. |
| Identity | **No author ids.** The Python variable is the handle; a tag is the only lookup by name ([No author ids](#no-author-ids)). |
| Formula groups | `group["name"] @= lambda: …` — recompute-on-read on `GroupOperator`, **not** an Attribute edge. `|` / `.filter()` stay snapshots. |
| Fleet | One loop / one timer / one Director. Groups have queries + bulk verbs, **not** `every` / `on_update`. |
| Entity data | **Ink:** `ship.hp = 3` is a bare scalar on the Entity. No `ship.state.hp`. Reserved names stay properties. |
| FSM name | **`mode`** (callable). Not `state` (`st` and “visual state” already exist). |
| Completion | **`then=`** = enter that mode. Positional **`fn`** / **`on_done=`** = call it (same channel). Not both with `then=`. |
| Ownership | **One ambient rule** for bare `after` / `every` / `wait` / `tween` / timed pose / `play_sound`: started in a mode body → mode-scoped. Explicit `e.after` / `e.every` / `e.tween` / `e.play_sound` → entity-scoped. No public `on=`. |
| Four rungs | All first-class **parallel styles**, not a one-way ladder. |
| Async | Sequence form (`await`). Same handles. Not hidden; not the first tutorial. |
| Per-frame hook | **`on_update`**. `Container.update()` stays graph recalculation; an author `def update(self, dt)` in a class body is refused at the class line, naming `on_update` (PA3). |
| Teardown hook | **`on_destroy`**. Fixed name, like `on_update`. Fires from `destroy()` only, before cancellation. |
| Mode marker / exit | **`@on_mode`** (tag, no runtime effect). **`@exit_mode(enter_fn)`** (optional cleanup on leave). Mode identity stays a callable. |
| Clock | `clock.scale` / `paused`; `dt`/`time` scaled; `real_dt`/`real_time` wall; `ready` / `recently` use `clock.time`. |
| Timed pose | Suite `time=` / `ease=` / `then=` / `on_done=` / `loops=` / `yoyo=` on `move_to` / `move_by` / `move_along` / `rotate_to` / `rotate_by` / `scale_to` / `scale_by` / `tween()`. `speed=` instead of `time=` on the verbs that cover a distance (`move_to` / `move_by` / `move_along` / `rotate_to` / `rotate_by` / `reset_rotation`, camera `pan_to` / `pan_by`): see [Rate instead of duration](#rate-instead-of-duration-speed). `ease=`/`then=`/`on_done=`/`loops=`/`yoyo=` require `time=` or `speed=` (an instant `rotate_by(10, ease="in_out")` raises: it had no curve and ignored `ease=`; guard `test_value_validation.TestEaseNeedsTime`, every verb with `time=` and `ease=`, camera included; the message names `speed=` only on a verb that takes it). `yoyo=` and `force=` are real bools. `yoyo=True` needs `loops` > 1 (or `"forever"`). `face=True` on `move_to` / `move_by` / `move_along` aims `.angle` at travel direction (works instant too on `move_to` / `move_by`; zero delta holds). `reset_rotation` has no `loops=`/`yoyo=` (single fixed destination). `move_along` is always motion; `time=` is one lap (`loops="forever"` has no finite whole-run); it needs `time=` or `speed=`. Same suite on canvas camera (`pan_*` / `zoom_*` / `rotate_*` / `frame_to` / `set_origin` / `reset_view`) — not Entity pose; channels in [Canvas Design.md](Canvas%20Design.md#timed-camera). `start=` is **`tween()` only** (optional initial value, same shape as `to`); not on pose verbs — place then travel stays two lines (`center = …` then `move_to(..., time=)`). |
| Timed `rotate_to` | Shortest arc (degrees, CCW+). Exact 180° → CCW. When it finishes it stores exactly the target: a finished `rotate_to(θ, time=)` reads `θ`, like the instant form (from `400`, `rotate_to(30, time=…)` ends at `30`, not `390`; Q2 of the geometry campaign). `rotate_by(dθ, time=)` signed as written. Camera `rotate_*` matches. A flip during a running rotation does not mirror the motion: the rest of the turn runs as written (`rotate_by(90, time=1)` with `flip_x = True` halfway ends at `171`, not `90`; Q4). |
| Missing sprite file | Legal. Magenta/black checker, warn once, **do not crash**. |
| Missing atlas / unknown frame | Same: warn once, checker placeholder, still a full Entity. |
| Unexpected Sprite kwargs | `TypeError` listing valid keys (`radius=` is Circle). |
| Unexpected Shape / SpatialFx kwargs | Same: `TypeError` with family hint (`frame=` is Sprite). Gradual: empty / `center=` / complete size — not arbitrary home subsets. |
| Sprite size | Design units (`height` / `width` / `size`). `scale` = pose zoom. |
| Sprite flip | `flip_x` / `flip_y` bools on every Graphic except Text (mirrored text is unreadable: `True` raises `TypeError`, `False` is a no-op). Mirror about `center`. Shapes rewrite geometry; Sprite mirrors in the draw transform. |
| Sprite `art_angle` | Bitmap nose in degrees (0 = +x, 90 = +y). Draw / hit-test / colliders use `angle − art_angle`. Construct seeds `angle` so the sprite appears as drawn and `.angle` is world heading. One value per sprite (clips share it). Omit / 0 = today's blit. Not per frame; not packed-atlas `rotated`. |
| Sprite class defaults | `class X(Sprite, source=…, height=…)` omit-able look fills; instance wins. Not placement (`center`/`layer`). |
| Shape class defaults | `class X(Circle, radius=…, color=…, group=…)` style/group + home size; instance wins. Not placement. Size fills home path only. Every kind reads them, `Track` included (it bypassed them until AC15). |
| SpatialFx class defaults | `class X(Orb, radius=…, color=…, group=…)`: the kind's knobs, `group`, `soft_edge`; instance wins; not placement, not `style` ([Effect System Design](Effect%20System%20Design.md), 3.1d; AC2). |
| Text class defaults | `class X(Text, font_size=…, color=…, group=…)`: the look (`font_size`, `font`, `color`, `background`, `glow`, `align`, `width`, `group`); instance wins; not the text, not placement (`center`, `top_*`, `box`, `layer`, `stack`, `angle`). `Text.__init__` reads `_class_defaults`; validation shared with SpatialFx in `scena/class_defaults.py` (`take_class_defaults`: placement / unknown / bad values raise on the class line, an author mixin's own `__init_subclass__` still gets its keywords). |
| Other families | The widgets, `Entity`, `Endless` take no class keywords (decided 2026-10-10: their arguments are content, behaviour or layout): `Entity._refuse_class_keywords` raises an author error naming the fix (pass them on the instance), and lets an author mixin's own `__init_subclass__` take its keywords (AC15). Guard over every family: `tests/test_subclass_parity.py`. |
| Author `__init__` | Build in `setup(self)` (Scena calls it once the object is built). An `__init__` of the author's own is allowed — the way to take constructor parameters of one's own — and must take `**kwargs` and call `super().__init__(**kwargs)`. One that never does raises `TypeError` at construction naming both fixes (CB1): `_construct` sets `_actor_constructed`, so `_finish_actor_construct` (the one funnel after every construction) finds it unset. Not refused at class definition, unlike `Act`: a correct `__init__` with `super()` is legitimate author code, and whether it calls `super()` is only known when it runs. Scena keywords against an `__init__` that does not take them (`Bolha(center=…)` with `def __init__(self)`) name the same fix (`_explain_author_init_keywords`); a typo of the author's own parameter keeps the near-miss rewrite. Using `self` before `super().__init__` (`self.radius`, `self.move_by(…)`) raises `AttributeError` with the same fix: `_ink_read_slow` on an object with neither `_ink` nor `_actor_constructed` (a cold branch: normal construction never reaches it). Before: an empty object, never in the game, silently; or `no attribute 'radius'` / `'_owner'`. |
| Class-body values | A value in an author class body (or an author mixin) under a name Scena owns on the kind — every name in the kind's `_setattr_route` (`radius`, `height`, `visible`, `center`, `group`, `vel`, a method name, a size word the kind lacks) — raises `TypeError` on the class line (CB2, `_refuse_class_body_values`). The fix: the class keyword when the family takes it (`Entity._class_keywords()`, overridden by Shape, Sprite, Text, SpatialFx; the suggested line keeps the class's own keywords), else `setup(self)`; a refused route (method, read-only, missing word) says why. Methods, properties and other descriptors stay the author's; so do fields of the author's own (`velocidade = 100`). Before: never read (`radius` read the default; `visible` read `False` while the shape drew). |
| Sprite clips | Wrap on the **clip** (`clip(..., yoyo=)` / `strip(..., yoyo=)`), not on `play`. `play(..., next=)` is a clip name. |
| Sprite hitbox kinds | `"auto"` (default), `"rect"`, `"ellipse"`, `"circle"`, `"hull"`. `source` (`"clip"`, `"all"` = registered clips, tuple of clips) / numeric `hitbox_anchor` / per-axis `hitbox_scale`. No author `hitbox_accuracy` / `may_rotate`. No `hurtbox=` kwarg set: extra detect-only colliders are hitbox parts (`add_hitbox(group=…)`, [Sprite Design.md](Sprite%20Design.md#hitbox-parts)). |
| `hitbox_shape="auto"` | Bake the reference set on collision enroll; frozen while animating unless `hitbox_source="each"`. Utility = quality − λ×cost; rotation-safe (never multi-rect). Walkers: `hitbox_shape="rect"`. |
| Sprite spawn | **Construct again** is the default (and the taught shooter path). Track-only `Sprite("shot.png")` interns one single-frame `Sheet` + process-wide decode cache + cached auto-hitbox *fit*. Each call still pays Entity / Attribute / registration. `Sheet` is clips / atlas, not a fire-rate prerequisite. |
| `clone()` | One verb on **Graphic** (Sprite + Shape). Birth: constructor + `setup()`, then `look_like`. Same cost class as warm construct — **not cheaper** than constructing the same path again. Copies art/style/groups, not process state. Layer is placement (omit → class default; `None` → undrawn); a HUD `Text` clone stays on `ui`, a world `Text` clone takes the class default. Copies `visible` (not park). Subclass clone returns the subclass (`Sting` / `Bolt`). No `Template` / pool / `spawn_like`. Not on bare `Entity`. |
| Electric* / Shield on sprites | **ElectricField / ElectricBolt:** live silhouette path (all qualities). **Shield** (incl. plasma): frozen silhouette-union ellipse (per-frame alpha AABBs → design-unit union × ``shield_scale``, default 1.4); baked on look assign via ``_AUTO_CACHE`` bbox; independent of hitbox. **`Halo()` / `Halo(style="fill")` / `Laser()` on Sprite:** SDF glow/beam + blit + smoothed `path_v2` rim (no ImageFilter). **Shape** Halo/Laser stay on GPU primitives / the compiled filter package. Other path shells / Rim / Metal·Flame·Swell·Aurora·Wave / Extrude / MultiBorder·Organic·Tracer prefer cached silhouette path at **all** qualities. FrameFx bakes at **look assign** (all sheet cells) or via `prepare_fx(*looks)`; bare `Sprite()` / stamp Glow never bake. ``_replaces_sprite_body`` materials hide the bitmap. `InsetRim` is Shape-only. |
| `@when` lifetime | Method `@when` / `@on_change`: `destroy()` drops the registration immediately (`drop_owner`). A dead owner still retires the watch on the next poll if it was not dropped. Park does **not** suppress — watches stay live. Classless watches whose source was destroyed (`DestroyedError` / `ReferenceError`) retire quietly; any other error (typo, missing ink) raises. No `on=` on `@when`. |
| `@when` on methods | Condition takes `self`; wrap to zero-arg FormulaLink at construct (after `setup()`). Classless stays zero-arg. |
| `@collide` arity | Truncated: `hit()`, `hit(me)`, `hit(me, other)`, `hit(me, other, info)`. Only parameters with no default receive a value (`validate.payload_arity`, one counter for every hook). |
| `@collide_with` | Method-only; `self` is left side. Same target kinds as one `@collide` side. No `SELF` sentinel. |
| Transient `on_done` | Payload `(shape,)`, same truncation. Exceptions propagate; the transient finishes first (hide applied) and `on_done` does not re-run. |
| Timers | One API: ignore handle → hold handle → `name=` **slot**. Decorators attach **`fn.handle`**. Method `@every` tags; construct arms `every_on`. |
| `@collide` after respawn | Prefer **group tags**. Object refs are **dropped** on `destroy()` (no handler leak). |
| Park | **`active`** (not soft-destroy). Orthogonal to `destroy` / `mode`. |
| Drop owned process (keep Entity) | **`cancel_process()`**. Cancels all owned Handles + mode script (same path as `destroy`), quietly clears `mode` to `None` without `@exit_mode` / `on_destroy`. Not ink, tags, `on_update`, `@when`, or transients. No global author `reset_all`. |

## Groups are tags

Keep `group=`, `add_to_group`, `group["enemy"]`, `@collide("bullet", "enemy")`. Sugar:
`ship.tag(...)` / `untag` / `tagged`. `add_to_group` / `remove_from_group` / `tagged`
take one name; a list raises `TypeError` and names `tag(...)` / `untag(...)`.
Behaviour depends on tags the same way collision
already does. Named-group lookup is **only** `group["name"]` — `group("name")` raises
`TypeError` with a brackets hint. No silent alias and no dual spelling. There is no
`obj("id")` (see [No author ids](#no-author-ids)). String keys work on the root
`group` only; `group["wasp"]["other"]` raises (index members with an int:
`group["wasp"][0]`). Plain `group["name"] = …` raises — bind with `@=`.

**Parts have no tags.** `line.p1.tag(…)`, `untag`, `add_to_group`, `remove_from_group`
and `part.group = …` raise `TypeError` naming the owner (`p1 is a part of the Line made
at app.py:12 … Tag the Line itself`); `tagged` reads False. Groups are actor-level:
`@collide` auto-enrolls a group's members as bodies and bulk verbs move them, so a
tagged `center` would collide as a Point or reshape its owner, and it would sit in a
group its owner's lifetime controls. For a set of handles, keep a Python list or tag
the owners. `Act` refuses tags the same way. Guard: `test_part_lifecycle.TestPartsHaveNoTags`.

Unchanged (not lookup): constructor / clone `group=`, `.tag` / `.untag` / `.tagged`,
and string-tag APIs (`@collide("bolt", "wasp")`, `until_empty("wasp")`,
`@leave_playfield("bolt")`).

<a id="group-names"></a>**Group names (the typo guard).** `group["name"]` on a name with no members
warns `No group 'x'. Did you mean 'y'?` only when the name is **unknown** and
near-misses a known one. Known = live now, ever had a member (the registry drops a
bucket with its last member but keeps the name in `_group_gen`), a formula group, or
**declared by a rule**: `@collide` / `@collide_stay` / `@collide_exit`, `@collide_with`
(and stay / exit), `resolve`, `@leave_playfield` record their string names at
registration (`registry.declare_group_names`). So `group["tiros_inimigos"]` before the
first shot, or `group["inimigos"]` after the fleet is cleared, reads quietly as an empty
view; `group["inimgos"]` still warns at the line that typed it. A name used only in
`group[...]` reads, before its first member, with a near-miss elsewhere still warns.
A formula-group declaration (`group["coluna0"] @= lambda: ...`) does not warn: Python
reads `group["coluna0"]` before the `@=` runs, so when a hint would be shown the guard
first checks the caller's bytecode for an in-place `@=` stored back into the same
subscript (`registry._declares_group_formula`, AC9).
Guard: `tests/test_group_name_guard.py` (Testing Design GN1; `TestDeclaringAFormulaIsNotATypo`).

Groups resolve **live** each frame. Object literals do not. Prefer
`@collide("player", "star")` over `@collide(basket, "star")` after destroy/recreate.
Destroy **drops** object-literal pair handlers (no leak / warning flood); recreate still
needs a new registration. Resolve also skips inactive / `collidable=False`. Prefer tags,
or park with `active=False` and keep the same instance.

## Fleet helpers (groups)

Groups grow **verbs** (`destroy`, `tag`) and **queries** (`count`, `empty`, `any`, …) at
the same DSL level as `move_by` / `len`. They are **not** a new process owner.
`every` / `on_update` keep attaching where they already attach (script, or an `Entity`).
Author surface: [Guia da API](../docs/pt/guide/index.html#mundo-grupos).

### Principles

1. **Same vocabulary.** `group`, `every`, `on_update`, `until` stay the words. Shared
   timing is author-written (`every(2.4, volley)` looping the group, or a Director).
2. **Gradual.** Per-entity APIs stay; group APIs are optional sugar for fleets.
3. **Framework does not invent the formation.** Helpers move / query; the author still
   chooses who is in the group and what happens.
4. **One owner story for timers, not two.** Script-scoped `every(2.4, volley, name="fire")`
   and `director.every(2.4, volley, name="fire")` already cover O(1) fleet timing.
   `name=` stays per Entity / per script.
5. **No reactive-graph changes.** Pose writes still go through existing A1–A3 / Attribute
   paths.

### Taught pattern (Director / one loop)

Do not put 80 timers on 80 wasps. Loop the group from **one** place: `update(dt)`, script-level
`every`, or a Director `Entity`. Individuals keep dive / death modes.

`examples/app_galaga.py` is the showcase of that beginner-idiomatic shape (one Director
sway loop, `await until_empty("wasp")`, per-wasp dive/death). Fire in that sample is
per-wasp `@every(2.4, name="fire")` plus `@collide_with("bolt")` so class-method
decorators have a live home; the O(1) fleet clock remains `every(2.4, volley)` as
below. Most other `scripts/` remain visual smokes, not author references.

Equally fine for one fleet: skip the Director class and put sway in `update(dt)` plus a
script-level `every`. A `sway_x` group verb is **parking lot** (see **Deferred**).

`group["wasp"].move_along(track, time=4)` is ordinary `__getattr__` broadcast (list of
handles). Per-wasp `phase=` is an author `for` loop (`enumerate` / `.index(w)`).
Broadcast itself has no per-member argument, and join-order rank is not a formation
slot. Wait on a fleet with `parallel(*handles)` /
`until(lambda: all(h.done for h in handles))`. There is no `Group.move_along`.
Hover-on-a-path: [Tracks Design.md](Tracks%20Design.md).

### Member walks copy

Live `group["wasp"]` is a **view**: `.count`, `.empty`, and the **next** walk see
join/leave. Walk order is **join order** (the sequence members tagged into this
name) — not left-to-right, not draw order, not a formation. Already a member:
`tag` / `add_to_group` is a no-op (does not move to the end). Re-tag after untag
appends at the end. For a spatial lineup, the author sorts:
`sorted(group["wasp"], key=lambda w: float(w.center.x))` or ink + `phase=` in a
`for`. Join order is still not a formation.

Every walk that yields members copies at enter: `for`, `any` / `all` /
`count_where` / `filter` / `nearest` / `centroid` / `box` / `index` /
`.first` / `.last` / `[i]`, bulk `destroy` / `tag` / `untag`, and
attribute-forwarding (`group["wasp"].move_by(...)`).
`destroy()` /
`tag()` / spawn / GC during that walk cannot raise
`RuntimeError: Set changed size during iteration` (the registry map is an ordered
weak registry). Joiners during that walk wait until the next call. Destroyed
members that were present at enter are still yielded this pass.

That is not a snapshot `GroupOperator`. `group["a"] | group["b"]` and the **result** of
`.filter(pred)` freeze the operator until discarded. A walk only freezes **this**
call. Do not iterate the registry store directly — one copy rule, not a mix of live
walks and `list()`.

`count` / `empty` stay O(1) on a named tag — do not `list()` just to count.
Formula groups (below) recompute on read, so `count` / `empty` are O(n).

Regression: script `update` destroying off-screen group members while iterating.
Tests: `tests/test_registry_layers.py` (`test_iter_survives_destroy_in_loop`,
`test_iter_does_not_see_joiners_mid_loop`, `test_next_iter_sees_joiners`,
`test_queries_survive_membership_change_in_pred`, `TestGroupJoinOrder`).

### `count` / `empty` / `until_empty`

`group["wasp"].count` and `.empty` are O(1) sync reads (`len` of the live tag
registry; do not `list()` just to count). Formula-backed names recompute, so those
reads are O(n). `until_empty(group_or_id)` is the **only** async-wait
spelling for emptiness — a thin wrapper over `until(lambda: ...)`. It accepts a
tag string, a live `group["name"]`, or a formula name / formula-backed operator.
A tag string is checked once, at the call (`group[name]`'s near-miss warning
catches a typo there); the per-frame poll reads the registry directly
(`process._live_group_empty`, no lookup cost per frame). The emptied-group warning
that once motivated it (Testing Design SC4) is now closed for every lookup: a name
that ever had a member is known ([Group names](#group-names)).

Do not write `until(group["wasp"].empty)`: `until(pred)` calls `pred()`; `.empty` is
already a bool by the time `until` sees it. A competing `.is_empty` method would work as
an unbound predicate but would be a second spelling for one concept.

### Bulk & query helpers

Immediate broadcasts (`destroy`, `tag` / `untag`) match `move_by` — a for-loop with nicer
syntax; already reachable via `__getattr__`, listed so the pattern is discoverable.

**An empty group.** A method does nothing and returns `None` (with `time=`, a Handle).
A field read (`center`, `angle`, `hp`, any member field) raises `AttributeError`
naming the group and the fix: `group['boss'] is empty: there is no member to read
.center from. Check group['boss'].empty first, or read .centroid / .box (None when
empty).` It used to read a `Blank` built for the purpose: an invented `(0, 0)`, a
registered actor per read (~0.1 ms), and `.hp` raised naming `Blank` (SC12). The
group's own reads (`centroid`, `box`, `empty`, `count`) answer. Guard:
`test_noop_cost.TestEmptyGroupFieldReadsRaise` (every field of every exported kind).
A write of a plain value to an author field (`group["tiros"].hp = 3`) is a no-op:
the first write of a name asks a `Blank` what it means (a new field, a typo, a
callable), and later writes of that name build nothing. A timed verb (`time=`)
returns a timer Handle with the verb's duration and `on_done`, not a tween on a
stand-in (`then=` / `loops=` / `yoyo=` keep the stand-in). Both built and
registered a `Blank` per call, ~0.3 ms (review 2026-10-09 S9-8; guard
`test_noop_cost.TestEmptyGroupWritesAndTimedVerbsBuildNothing`).
`.filter(pred)` returns a **snapshot** `GroupOperator` (same kind as `group["a"] | group["b"]`).
Set algebra (`|` / `&` / `-` / `^`) and `.filter` keep join order (first-seen wins). They stay
snapshots — not live — unless the author names the expression under `group["name"] @=`
(see **Formula groups**).

| Op | Member order |
| --- | --- |
| `A \| B` | A's join order, then B's members not already seen |
| `A & B` | A's join order, keeping those also in B |
| `A - B` | A's join order, dropping those in B |
| `A ^ B` | `(A - B)` then `(B - A)` in those orders |
| `.filter(pred)` | Source join order, keeping matches |

Short-circuit / aggregate reads: `any` / `all` / `count_where` / `nearest` / `centroid` /
`box` / `index`. Predicate shape is uniform: `pred(member) -> bool`. Empty `centroid` / `box`
/ `nearest` return `None`. `.box` is a fresh measuring `Box` over members' AABB
(angle 0), or `None`; a single-member group may be a collapsed Box. Safe to pass
to `canvas.frame_to` with no empty-group guard.
`.nearest(point, where=None, *, within=None)` caps distance
with optional `within=` (same metric as the standalone `nearest(origin, items)` helper
in `shapes.py` — use that for arbitrary lists / vertices / mix). All of these share the
member-walk copy (see **Member walks copy**); a mutating pred is well-defined (members
present at the call), not a crash.

`.index(item)` is the inverse of `group["wasp"][i]`: 0-based **join-order rank** of an
Entity. A string (in `index` or `in`) raises `TypeError` naming `tagged(...)` — members
are actors, never names. Missing member raises `ValueError` with an
`in` hint — not `-1` / `None` (`-1` looks like a number; membership is already `in`).
Root `group.index(...)` raises `TypeError`. Rank is live: destroy / untag of an earlier
member closes the gap. Not a sticky formation slot — stamp ink at birth
(`w.slot = i`) for a number that must not move. Prefer `enumerate` when already
looping. Tests: `tests/test_registry_layers.py` (`TestGroupIndex`).

`group["wasp"][i]` is Python sequence indexing on join order: `0` is first, `[-1]`
is last, `[-2]` the one before that. Out of range / empty raises `IndexError` with
the group name (not a silent `None`). A **slice** (`group["wasp"][1:3]`, `[-2:]`)
returns a `list` of those members — a copy, not a live `GroupOperator`. An empty
slice is `[]` (no error). `.first` / `.last` are the named ends (`[0]` / `[-1]`):
same join-order meaning, same empty `IndexError`. Root `group.first` / `group[0]`
raises `TypeError`. No `.second` / `.nth` — use `[i]`. Tests:
`tests/test_registry_layers.py` (`TestGroupFirstLast`).

No `.set(attr, value)` bulk-write helper — attribute-forwarding already does
`group["wasp"].hp = 3` (honest `AttributeError` on mixed membership).

### Formula groups

Named live combinations use the same brackets as tag lookup:

```python
group["enemies"] @= lambda: group["wasp"] | group["boss"]
until_empty("enemies")          # or until_empty(group["enemies"])
group["enemies"].unlink()
```

Recompute-on-every-read (no cache, no Attribute / `FieldRef` edge). Every access
re-invokes the callable. Do not memoize on `Registry._group_gen` — that counter
is per-tag (collision re-enrollment); nested formulas would need a recursive version
vector. Revisit a cache only if profiled. Destroy already evicts from the tag map, so
recompute never sees dead members (unlike a frozen snapshot’s strong-ref list). Nested
formulas are legal. `|` / `&` / `.filter()` stay snapshots; liveness is the `@=` name.
Lambda is required for a computed RHS; a bare live group or tag string is an alias; a
bare snapshot raises with a hint to wrap in `lambda:`. A held `g = group["enemies"]`
stays formula-backed after `@=` (the operator mutates — there is no `GroupFieldRef`).
Namespace collision with tagged members raises both ways (`add_to_group` on a formula
name raises; `@=` on a name that already has tagged members raises); re-`@=` on an
existing formula warns (`RuntimeWarning`) and overrides. Cycles are detected at first
read (re-entrancy stack), not at `@=` — weaker than the Attribute graph; the error is
`RuntimeError` with the chain, not `RecursionError`.

**Acts.** The seal records the formulas (`ActManager._game_formulas`); an act
change puts that set back. A formula an act bound leaves with it (a restart
binds it again without the "overrides" warning, a lambda reading the act's
`self` no longer pins the dead act, and the name is free for tagging), and a
game formula the act re-bound comes back (review 2026-10-09 S4-3; Act Design
"Removed").

`@collide` / `resolve` live re-enrollment keys on `_group_id` (string tags). Formula
groups fall through like snapshots (decoration-time membership). Prefer the source tag
strings for collision.

`.unlink()` / `.is_linked` live on a **named** `GroupOperator`. After unlink, the name
is an empty tag view again. Snapshots and the root `group` cannot `@=` / unlink.

Tests: `tests/test_registry_layers.py` (`TestGroupFormula`); `tests/test_process.py`
(`test_until_empty_formula_name_and_operator`). Smoke: `scripts/smoke/group_formula.py`.

### Group fences

Groups are tags, not process owners. Do not add `group["wasp"].every` /
`.on_update` / `every(..., group=)` — script-level `every` + Director already cover O(1)
fleet timing. Revisit only if a script cannot express that. Two fleets wanting
`name="fire"` is two Directors (or two script-level names), not a group timer.

Do not silently merge per-entity `every` handles. A denser scheduler tick is
allowed; merging timers is not. Optional later: `SCENA HINT` (see **Deferred**).

`|` / `&` / `.filter()` stay snapshots. Live combinations are
`group["name"] @=`. Walk order is join order, not spatial. `group("name")` raises.

Also not on the surface: `group.mode`, auto-formation layout, a second bulk-write
spelling beyond attribute-forwarding. Snapshot groups cannot host a live sway.

Why these hold:

| Idea | Why not |
| --- | --- |
| Group-scoped `every` / `after` / `on_update` | For one fleet the effect equals script `every` / a Director; the only gain is a `name=` namespace on the group. Costs: two spellings for one concept; broadcast vs host on one object (`move_by` means N members, `every` would mean **one** timer); a third arity rule (`fn()` on a group, `fn(x)` on an entity); an invisible process host |
| Silent merge of equal per-entity timers | Bookkeeping-only payoff (each member still runs its callback); sound only for identical interval / name / function / phase, so staggered spawns gain nothing; two code paths that must agree under cancel / `name=` / exceptions / watchdog; hides the "one owner" lesson the Director teaches |
| Live `\|` / `&` / `.filter()` by default | Breaks `=` copy vs `@=` link: a live combination must be named under `@=` |
| `group("…")` beside `group["…"]` | Two spellings on one token, a skim hazard; the call form raises with the fix |
| `union_of(...)` / `group.formula(...)` / plural `groups[...]` | A second idiom or noun with no `@=` marker |
| Spatial or left-to-right walk order by default | Invents a formation; the author sorts |

Index: [Fences.md](Fences.md).

## No author ids

Scena has no `id=` keyword, no `.id` field, and no `obj("id")` lookup (removed
2026-09-29). **The Python variable is the handle.** To reach an actor where the
variable does not reach (another function, an act class, a spawn helper), tag it and
read the group: `Sprite("heroi.png", group="heroi")` … `group["heroi"].first`. Error
messages and `repr` name an actor by its construction line (`entity_label` /
`made_at`: `the Circle made at app.py:40`), which a beginner can click.

Why it went: nobody called `obj()` (no script, no taught sample); the taught samples
already reach a singleton through `group[...]`. It was a third way to reach an object
(variable, `obj`, `group`), stringly typed and global. It also carried beginner traps:
`id="bullet"` in a spawn helper crashed on the second call (ids were unique), a typo
returned `None` (then Python's `NoneType` error), and the weak map lost an undrawn
Entity known only by its id. Five bug-catalogue rows were id bookkeeping (H1, H3,
H8, R2/R4, K5).

- `X(id=…)` raises `TypeError` with the hint "keep the actor in a variable, or tag
  it with `group=`" (`validate._FAMILY_KWARG_HINTS["id"]`). Same on class lines
  (`class Heroi(Circle, id=…)`).
- `"nome" in group["wasp"]` / `group["wasp"].index("nome")` raise `TypeError`: a
  group holds actors; a tag test is `ship.tagged("wasp")`.
- `ship.id = 3` is plain ink (the name is no longer reserved).
- Internally the registry keeps a weak, ordered **roster** (`Registry.live`, keyed by
  a serial that is never reused; `is_live` / `live_objects`). A stale second
  `destroy()` therefore cannot drop a newer actor (the H3 class is gone by
  construction). Tests that check "a rejected call registered nothing" compare
  keys newer than a mark (`hypothesis_support.roster_mark` / `new_in_roster`), never
  `len(live)` — the roster is weak, so unrelated garbage can shrink it. Parts are
  in the roster too and leave with their owner ([Parts](#parts-leave-with-their-owner)).
  An undrawn engine actor that must work from a one-line call with no author
  variable (`Endless("pista", ...)`) is held strongly by `Registry.hold` (the
  `_held` set) and leaves it in its own `_clean_up`; an author `Entity()` with
  no variable is still collected (keep it in a variable).

Fence: see [Fences](Fences.md) (`id=` / `obj()` / a name registry).

## `active` (park)

- `active = False` — stash then force `visible` / `collidable` off; **pause** owned
  timers / tweens / `on_update` / async mode resume (`elapsed` frozen). An owned
  **sound** keeps playing (park does not stop audio; pause the Handle for that)
  and its Handle keeps reporting the voice, but its `on_done` waits for the
  resume: park runs no owned callback (decided 2026-10-09, review X-life-4).
  Script-scoped timers keep running. `@when` / `@on_change` still run (they watch facts, they are
  not owned process — so `@when(lambda self: not self.active and keyp("R"))` can
  revive). Shape transients (`flash` / `blink` / `dissolve_out` / …) also keep
  ticking: they are presentation on wall clock, not actor process time. Prefer
  `dissolve_out(..., on_done=self.park)` so the FX finishes while still visible;
  park forces `visible=False`, so parking first hides the FX. Use
  `clear_transients()` when the FX must stop; use `clock.paused` for a global
  freeze, not fleet-wide park.
- **Parts park with the owner.** Each Entity part (a shape's `center` / `p1` /
  vertex) runs the same park / resume step (`Entity._park_self` / `_resume_self`):
  shown handles leave their layer and the pointer list (a parked shape cannot be
  dragged by a handle), `part.active` reads False, a part's own timers pause.
  `show_handles()` / `no_handles()` / `part.visible = …` while parked update the
  part's stash; resume restores it. Before, a parked Line's handles kept drawing and
  dragging one moved the parked shape. Guards: `test_part_lifecycle.TestPartParksWithOwner`,
  `test_hyp_canvas` invariant `parts_follow_their_owner`.
- **Park then resume is an identity** on placement: `layer`, `visible`, the draw
  list and the pointer list read as before. Park and resume write `visible` only
  when it changes. Writing `False` to an item that is already hidden is not a no-op
  everywhere: a hidden Point on a layer leaves it. Writing it took such a Point off
  `'default'` for good (O5 in [Testing Design](Testing%20Design.md#bug-catalogue)).
  Guard: `test_process.TestParkRoundTripKeepsPlacement`.
- **A linked `visible` follows its formula on resume**, not the stash: the formula may
  have changed while parked (the refreshes skip a parked host, L4). Park still hides it
  (`_engine_flag_write` passes the linked-field refusal). Guard:
  `test_paint_flag_links.TestFrames.test_park_and_resume_follow_the_formula`.
- While parked, a `visible` / `collidable` **write updates the stash** that resume
  restores; the actor stays hidden and out of collision. Reads report the current
  state (False while parked). Engine draw / hit-test walks read the drawn flag
  (`_drawn`), never the stash. A `blink` / `flash` on a parked actor therefore
  cannot show it (D7 in [Testing Design](Testing%20Design.md#bug-catalogue)).
- **Collision state belongs to the actor, not to its Collider.** The engine's
  Collider is dropped by park and by `collidable = False` and rebuilt when the
  actor rejoins; `on_collide` / `on_collide_stay` / `on_collide_exit` (a
  function or a class-body method) live on the actor and survive both. While
  parked, `on_collide = f` stores the callback and stashes `collidable = True`
  (a callback opts in on resume, as it does when active); `resolve_now` returns
  `[]` (a parked actor is out of collision; nothing is built). Park and resume
  never write the author's opt-out: only `collidable = False` does, parked or
  not, enrolled or not (before, a `collidable = False` written before any
  `@collide` was dropped, so the result depended on statement order). A
  stashed `collidable = True` is validated when written: on the `ui` /
  parallax layer it raises then, and `layer = "ui"` is refused while it is
  stashed (before, both raised on resume and left the actor half resumed).
  Graphics review E1 / E2 / E3 / E11; guard `test_collision_lifecycle` (every
  sequence of up to three lifecycle statements vs a twin built in the final
  state).
- `active = True` — restore stashed flags and resume process time. When the
  restored state is collidable, the actor rejoins through the same path as
  `collidable = True` and `on_collide = f` (`Entity._enter_collision`): its
  callbacks come back and it enrolls in every pair group declared so far,
  including groups declared while it was parked.
- Orthogonal to `mode` and to hard `destroy()` (`is_alive`) **while alive**.
  `destroy()` marks `is_alive` False **and** `active` False (direct flag, not the
  park setter). `active = True` on a destroyed leftover is a no-op — it does not
  revive.
- `.enable` / `.enabled` on an Entity raise `AttributeError` and name `.active`
  (`True` / `False`, park / unpark). They are not one edit from `active`, so they
  are explicit ink aliases, not reserved properties. Widgets, post effects,
  backgrounds, and audio effect stacks keep a real `.enabled`: skip that
  contribution; the object stays in its list. Park does more than that mute.

Use park for death blink / restart-the-same-ship. Use destroy for one-shot debris.

## `cancel_process` (drop owned process)

Keep the Entity; drop its scheduled work. Author surface for the cancel step
`destroy()` already runs internally — without teardown.

```
e.cancel_process():
    1. cancel every Handle / mode script owned by e (all scopes — same as destroy).
    2. quietly set mode = None (no @exit_mode, no on_destroy).
    3. Entity stays is_alive; ink, tags, groups, active, on_update untouched.
```

| Want | Call |
|------|------|
| Pause **one** job, keep pending | `h.pause()` / `h.resume()` |
| Pause all owned timers (park Entity) | `e.active = False` |
| Drop owned timers / tweens / sounds / mode | `e.cancel_process()` |
| Hard remove | `e.destroy()` |
| Mode leave + exit hooks only | `e.mode = None` (mode-scoped cancel; entity-scoped survive) |
| Clear flash / blink / dissolve | `e.clear_transients()` |

Held `Handle` instances that are still running become `.cancelled`. Calling
`cancel()` on a handle that already finished is a no-op and does **not** set
`.cancelled`. Does **not** unregister `@when` / `@on_change` (those stay until
`destroy()`, which drops method watches). Does **not** fire `@exit_mode` — same
rule as `destroy()`. Author who needs exit-hook cleanup first:

```python
e.mode = None          # exit hooks; mode-scoped cancel
e.cancel_process()     # entity-scoped leftovers
```

**Restart while keeping objects.** Destroy disposable actors (`group["wasp"].destroy()`);
on persistent singletons call `cancel_process()`, reset ink by hand, then
`goto_mode(...)` to re-arm behaviour (same-mode `e.mode = …` is a no-op).

```python
group["wasp"].destroy()
player.cancel_process()
player.clear_transients()
player.hp = 3
player.active = True
player.goto_mode(player.playing)
director.goto_mode(director.directing)
```

No author-facing global `reset_all` / `reset_process_scheduler` (tests only). Groups
forward the method: `group["wasp"].cancel_process()`.

## Ink

`st` is the **app** bag. The per-Entity bag is the Entity itself (`ship.hp = 3`).
Unknown public names on an Entity are values in `ink`. Entity is the only
author object that holds ad-hoc author data: every other one is a closed
surface (a write to a name it does not have raises —
[Scena Design](Scena%20Design.md#entity-ink-vs-st)).

> **Ink holds any value except a function.** Numbers, text, points, other
> objects (`self.aviso = Text(...)`). Only numbers, bools and points can be
> linked (`@=`). A stored object that was destroyed reads falsy (`if self.aviso:`).
> A group view is callable, so `self.inimigos = group["inimigo"]` raises
> `CallableAssignError` with its own sentence — "A group is looked up, not
> stored. Write group['inimigo'] where you need it" (`entity._ink_callable_message`).
> Store an object only when a later method uses it; a banner shown and removed
> inside one async mode stays a local. Scenes use the same rule
> ([Act Design.md](Act%20Design.md#act-memory-on-self-ink-rule)).

**A formula reads the field, not what it holds.** `lambda: nave.center + nave.desvio`
depends on the field `desvio` (its anchor), whatever it holds, so a new value
re-runs the formula; a Vec2 there also notifies the field on every in-place
change (`<<`, `+=`, `.x =`, `do_rotation`), and a list or dict on `+=` / `|=`.
Mechanism and the options weighed: [Reactive Design — A formula that reads an ink
field follows the field](Reactive%20Design.md#a-formula-that-reads-an-ink-field-follows-the-field).

**Reading ink is a miss.** An ink field is not an attribute, so every read
(`self.rumo`) misses normal lookup and runs `Entity.__getattr__`. Its first
branch returns `ink[name]` when the full path (`_ink_read_slow`: the destroyed
check, the `x` / `y` refusal, the retired-name hint, then ink) would return it
too. That is when the name is in ink, the actor is not destroyed, the name is
not `x` / `y`, and the class's merged retired map does not list it. A linked
ink field is pulled first, as in the full path. Games read ink thousands of
times a frame; this cuts a read from about 0.38 to 0.26 µs (M4).
`_INK_READ_FAST = False` is the full path. Tests:
`tests/test_ink_read_fast.py`: names × states give the same value or error
both ways, and a linked field read inside a frame batch is pulled. A change to
the refusals belongs in `_ink_read_slow` **and** in the fast branch's
conditions.

**Writes create; reads must exist.** `ship.hp = 3` (copy) and
`ship["hp"] @= lambda: …` (link) both materialize a missing ink field (default `0`).
Reading `ship.hpt` when only `hp` exists raises `AttributeError` — typos between two
ink names surface on **read**, not on assign/link (`ship.hpt = 1` would create `hpt`,
same as plain `=`). The one write-time guard is the **near-miss of a real property**:
creating ink whose name is one edit (or one adjacent swap) from a public
property/slot of that class (`rotaton`, `visable`, `radious`), or a known spelling
(`colour`, `centre`, `velocity`), raises `AttributeError` naming the property.
`enable` / `enabled` are explicit aliases of `.active` (the error says
`.active = True` / `False`, park / unpark) — not one edit from `active`, and not
`_INK_RESERVED`. The edit-distance check fires for candidates ≥ 6 letters
with the same first letter, and for candidates ≥ 5 letters one **adjacent swap**
away at any position (`anlge`, `widht`, `aplha`, `lyaer`, `gruop`, `nagle` →
`angle`; `scena.closed.transposed`). Never for `on_*` or plurals, and checked
once per (class, name) — so `hp`, `player`, `flame`, `weight` stay ink, and so do
plain deletions on short names (`coor`, `laer`) unless the value rule catches them.
**The value rule** (2026-10-16) covers the short properties a beginner writes most,
whose one-edit neighbours are real field names (`laser` / `layer`, `owned` / `owner`,
`modo` / `mode`, `nome`, `tempo`): a new name one edit (same first letter, not a
plural, not the name plus digits) from `color` / `fill` / `line` refuses when its
value is a colour (an exact colour name, `#hex`, an `(r, g, b[, a])` tuple, a
Color / Gradient / Paint / Texture), and from `alpha` / `angle` / `scale` / `width`
when its value is an `int` / `float` (`bool` is not). `bola.colr = "red"` raises
"Did you mean 'color'?"; `self.laser = Rect(…)`, `self.owned = True`,
`self.lime = 3` stay ink (`_TYPO_VALUE_KINDS`, `_is_paint_value`). Only where the kind
has the name as a property: a bare `Entity` stores `color` plain (`_SET_OBJECT`), so
`e.colr = "red"` stays ink. The cache entry is then the candidates, and `=` tests
the value at each creation (+60 ns; a rewrite never enters the guard). Known misses:
a bracket `@=` creation (the value is a formula), two-edit typos (`clr`), glued or
fuzzy colour names as values (no fuzzy lookup there: 40–240 µs per string). Known
false positive: a number field one edit from `scale` (`item.sale = 10`). Why a value
test and not a lower threshold: across the examples, every tutorial step and the
tests, a 5-letter one-edit rule hits `laser`, `later`, `owned`, `modal`, and a
4-letter one adds `modo`, `fonte`, `trail`, `lime`; with the value test, none.
Guard: `tests/test_ink_typo_value.py`. **An exact name of the class
is never ink** (PC2): a method (`c["move_to"] @=`), a read-only property
(`tri["points"] @=`, `poly["pointer_hover"] @=`, `rect["box"] @=`), a settable
property `@=` cannot link (`track["is_floating"] @=`), or a size / point word
the kind lacks (`circle["top_left"] @=`) refuses the bracket with the message
`=` gives (`_ink_exact_name_message`, read from the route table, before the
near-miss rules; strict kinds `Point` / `Line` too). A class can name its own
near-fields first (`_ink_name_refusal`: Polygon `points` / `v0`…`vN` point to
`poly.points[i] @=`). Before, `=` refused through the route (R8) but `@=` made
a dead ink field beside the method or property. Guard:
`test_fieldref.TestBracketRefusesWhatAssignRefuses` (every kind × every refused
route name). **Look-family** names that belong to another kind (`circle.alpha`,
`text.alpha`, `entity.line_width`) raise too: they would otherwise land on a dead
attribute (`_LOOK_MISSING` route). **Any other reserved name a Graphic kind
does not define** refuses `=` too (RN1, 2026-10-15): `rect.text = "hi"`,
`rect.frame = 3`, `circle.collider = 1`, `text.model = …` stored a plain
attribute nothing reads, because every `_INK_RESERVED` name without a
descriptor routed to a plain `object.__setattr__` (`_SET_OBJECT`). Now
`_install_setattr_route` gives it an `absent` `_RouteRefusal`, and `=` and `@=`
answer with the same words, built once (`_absent_reserved_text`: `Rect has no
field 'text' (a Text field). A field of your own needs another name.`; `@=`
adds ", so @= has nothing to link"). The E13 size words and the look family
use the same builder (`Circle has no field 'width'. Size it with radius.`).
"Defines" is read from the MRO, so a property of the author's own under the
name is theirs. On a Graphic, the only reserved plain field set in `__init__`
is `group` (routed apart); a field set in `__init__` under a reserved name must
be declared on the class (a slot or property), or its own write refuses. Guard:
`test_fieldref.TestReservedWriteRefusalPerKind` (every exported Graphic kind ×
every reserved name, oracle read from the MRO). **The closed non-Graphic
kinds** (UI widgets, every SpatialFx; class flag `_scena_reserved_strict`)
refuse the same way (RN2, 2026-10-15): `button.text = "Play"`, `slider.color`,
`fire.color`, `jet.center`, `checkbox.frame` stored a field nothing drew.
Unlike a Graphic, they keep some reserved names as plain fields set in
`__init__` (`button.width` / `height`, `checkbox.size`, every effect's
`soft_edge`, Rain / Jet `model`, Orb / Warp / Portal `glow`, Portal `angle` /
`tilt`), which the MRO cannot see: each kind lists them in `_reserved_fields`
(merged along the MRO), and a new one set in `__init__` must be listed there,
or its own write refuses. `_absent_hints` (merged, a subclass wins) adds the
kind's own fix in place of the Graphic hints: ``Button has no field 'text' (a
Text field). Its caption is `.label`.``; a widget's `center` → placed by
`top_left=`; a point effect's `width` / `height` / `size` → `radius`; Jet's
`center` → `p1=` / `p2=`. The `=` and `@=` words are built together
(`_RouteRefusal.link`). A descriptor attached to a class after it is made
(`Menu.center = ContainerSlot(Point)`, in `menu.py`) needs the route table
built again (`_install_setattr_route(Menu)`), or the table built at creation
refuses the name. A bare `Entity`, `Act` and `Endless` keep storing these
names as plain fields (`e.angle = 12`: the author's own data). Guard:
`test_fieldref.TestReservedWriteRefusalClosedKinds` (every closed kind and Fire
style × every reserved name; route at creation == a fresh one, every kind). **`x` / `y` on a Graphic or SpatialFx** raise
`AttributeError` and do not become ink — position is `.center` (`ship.center.x`,
`move_to` / `move_by`). `Point` keeps real axis slots. A bare Entity still
stores `e.x` as ink. `obj.group = "a"` / `{"a", "b"}` replaces the tag
set and keeps `group[...]` in sync (non-str / non-iterable raises `TypeError`).
Reading `obj.group` gives a **read-only snapshot** (`GroupTags`, a `frozenset`
subclass): `.add` / `.discard` / … raise `AttributeError` naming `tag` / `untag`,
because an in-place edit would skip `group_map` and collision tags; `obj.group |= {"b"}`
rebinds, so it syncs. The registry swaps a new snapshot on every tag / untag — never
mutate it in place. There is no `id` field (it would be ink like any other name); the
registry roster keys by a private serial (`_reg_key`), so no author field doubles as a
registry key. Tests: `test_registry_key_fields` (`TestGroupSnapshot`, `TestNoEntityIdKey`).
Reserved names stay properties. Geometry leaves (`Point`, `Line`, `Vec2`) do not
auto-materialize ink on bracket access — typos stay `AttributeError`. Plain
`ship.hp = lambda: …` is **not** a link — it raises `CallableAssignError` (a
`TypeError` + `AttributeError` + `ValueError` subclass) naming the `ship['hp'] @=`
spelling, for every field kind: ink, `ScalarSlot`, `ContainerSlot`, pose property,
`vel`, reserved look, `st` cell; `@=` is the only operator that installs a formula
(taught form: [Reactive Design — Link attribution](Reactive%20Design.md#link-attribution-)).
Why not let `=` sense a lambda (ink once did): one syntax shape (`x = lambda: …`)
meant link on ink but raised on `Attribute` / `st`; a distinct operator shows "this
line wires the graph" at a glance in a diff or a stranger's file; and `@=` fails
loud on a non-linkable target, where `=` would store a dead function or link by
accident.

**Paint / appearance is not ink.** Costume and stamp properties (`.visual`, `.fill`,
`.line`, `.line_width`, `.blend`, filters, `.glow`, `.shadow`, `.hue`, `.tail`, …)
are plain Python properties — not `Attribute` graph cells. Bracket `@=`
(`ship["line_width"] @= …`) and callable assign (`ship.line_width = lambda: …`)
raise with a field-specific hint: use `=` for the look, and `on_update` /
`@on_change` / `@when` when appearance should follow game state. Link custom ink
(`ship.hp`) or geometry (`rect.width`, `line.p1.x`) instead. See
[Scena Design.md — Entity ink vs `st`](Scena%20Design.md#entity-ink-vs-st).

Dot `@=` (`ship.grounded @= …`) is **not** the bracket equivalent: Python evaluates
`ship.grounded` before `@=`. On a composite that returns a Container this can work
if the field already exists; on a scalar leaf (`ship.hp`, `p.x`) it is a bare
`float` with no `__imatmul__`, so Python raises its own `TypeError` — Scena cannot
intercept that without wrapping every scalar read. Always write
`ship["grounded"] @= lambda: …`.

`Shape`/`Sprite`/`Entity` use `__slots__` (no `__dict__`), so ink is the only place to
hold ad-hoc author data on them. Paint channels are **not** ink: `color`, `fill`,
`line`, `line_width`, `visible`, the flips (and Text `background`, Sprite `alpha`) link
with `@=` as targets that write through their setter, never into ink; looks, stamps and
filters do not link ([Reactive Design — Appearance links](Reactive%20Design.md#appearance-paintstate-internal)).
`@when`/`on_change`/`until` poll whatever they're given every frame regardless
of source.

## Four rungs (parallel)

| Rung | Surface | Best at |
|------|---------|---------|
| 1 | `update(dt)`, `@collide`, `@when`, transients | Continuous motion, reactions |
| 2 | `after`, `every`, `ready`, `recently` | Time, no modes |
| 3 | `mode` + `then=` | One chapter, one completion |
| 4 | `async` / `await`, optional class | A **sequence** of waits; per-object `on_update` |

Teach: zero or one completion → `then=` (or ignore the handle). Two or more waits, or a
value that must survive a wait → `async` mode (helpers that mode `await`s count). `then=`
inside an async body: don’t; warn if a transition cancelled a still-running script.

## Process semantics

Cooperative scheduler owned by the engine, driven by `clock.dt`. Handles are awaitable
so async is not a retrofit. Effective step for an Entity: `clock.dt * e.time_scale`.
Script-level `after` / `every` use `clock.dt` (pause with the world). No per-group scale
in v1.

`e.time_scale = value` and `clock.scale = value` both raise `ValueError` for
non-finite (`nan` / `inf`) or negative values — previously both setters did a
bare `max(0.0, float(value))`, which silently mapped `nan` to `0.0`
(`max(0.0, nan)` is `nan` in Python but the *comparison* `nan >= 0` used
elsewhere reads `False`, so behavior around a `nan` scale was inconsistent
rather than a clean reject) and mapped any negative value to `0.0` instead of
telling the author their delta was wrong. `0.0` (freeze) stays legal.

### every is seconds, not frames

`every(interval, fn)` counts world seconds. The interval must be > 0.
A frame that covers several intervals fires several times (in that frame), so
the rate does not depend on the frame rate and a hitch loses no fires; one tick
fires at most `MAX_FRAME_DT / interval` times, so a stall cannot spiral
(debt beyond that, from an uncapped `clock.advance` or a time scale above 1,
keeps only its phase). Before 2026-10-09 it fired at most once per frame and
dropped the debt: `every(0.02)` gave 50 fires a second at 60 FPS and 30 at
30 FPS ([Scena Design — Clocks](Scena%20Design.md#clocks)).
`every(0, …)` and a sentinel such as `EVERY_FRAME` are not a per-frame hook.
Per-frame work is `on_update` (Entity) or script `update(dt)`, both of which
receive `dt`. The `on_update` fleet runs in **creation order** (the owners are
an insertion-ordered weak set; a `WeakSet` walked memory-address order, which
changed from run to run: review 2026-10-09 S2-9), and an `on_update` cleared or
replaced by an earlier one in the same frame does not run later in that frame:
the setter swaps the frame snapshot's entry (`watch_update` while
`_update_running`), so the loop pays nothing per actor (S2-10). A non-positive interval stays `ValueError` and names those hooks.
Revisit only if a script needs per-frame work that is cancellable, mode-scoped,
or named, and `on_update` + `update(dt)` cannot express it.
Index: [Fences.md](Fences.md).

**A running script is any script on the stack.** `Script.cancel` defers the
throw / close when the coroutine is executing (`cr_running`), not only when it
is the innermost script: a mode that set another actor's mode, whose body
ended the first mode, threw into a coroutine still on the stack ("coroutine
already executing", review 2026-10-09 S2-11). `_advance` closes it when its
`send` returns.

**Due on the exact frame.** A timer fires on the first frame whose summed time reaches its deadline; the first `every` call is one interval in. Time is summed frame by frame, so a deadline that is a whole number of frames can land a hair short by rounding (15 × 1/60 < 0.25): every "is it due" comparison (after / every / tween end / ready / recently / transient progress) goes through `process.reached` (1e-9 relative). At fixed 1/60, `after(0.5)` is frame 30, not 31 (bug PM8; `test_process.TestDueOnTheExactFrame`).

**Handle clock.** `.elapsed` is world seconds since start (or since the last `every`
fire); on a finite `loops=` verb it counts the whole run, and `.remaining` counts to
the run's end (both read the current lap only on `loops="forever"`: review 2026-10-09
W-T4). A frame longer than a lap advances every whole lap it covers, capped by the
laps left, so a finite run ends at `loops × time` and a yoyo keeps its phase under a
hitch (W-T1); `every` past its per-tick budget keeps its phase without one extra fire
(a `%` remainder a hair under the interval is the boundary, W-T3). `.remaining` is the dual: seconds left until `after` / `wait` / `tween` finish,
or until the next `every` fire. `0` when done or cancelled. `until` / `parallel` /
`race` have no clock duration → `0`. Read-only: assigning `.remaining` is a
`TypeError`. Refresh a buff with `after(..., name=)` (named slot replaces); do not
write the countdown.

**Handle slot key.** `.name` and `.owner` are read-only (`TypeError`). Together they
are the scheduler slot `(id(owner), name)` (`_named`, `_by_owner`), recomputed on
forget — a write used to park a cancelled handle in the old slot, or detach the job
from its owner's destroy. Re-schedule instead (`other.after(…, name=…)` + `cancel()`).
Internal writers use `_name` / `_owner`. Tests: `test_registry_key_fields.TestHandleSlotKey`.

**Handles are made by the engine.** `Handle(...)` in any call form raises one
author `TypeError` ("not built by hand", naming `after` / `every` / `tween` /
`wait` / `move_to(..., time=)` / `play_sound` and `h = after(2.0, fn)`), never
Python's `__init__()` complaint. Engine code builds through `Handle._make(**fields)`
(`object.__new__` + `_init`); every construct site in `process.py`, `audio.py`,
`audio_capture.py` and `menu.py` uses it. `__del__` reads its slots with
`getattr`, so a handle whose `_init` raised dies without an unraisable error.
Tests: `test_process.TestHandleConstruction`.

**Pause one job.** `h.pause()` / `h.resume()` freeze a clocked Handle in place
(`.elapsed` / `.remaining` / tween pose / sound cursor stay). Methods return the
Handle (chainable). `.paused` is read-only (`True` only while alive and frozen);
assigning it is `TypeError`. Idempotent; no-op on done / cancelled (does not revive).
`cancel()` clears the flag. Kinds: `every` / `after` / `wait` / `tween` (timed pose
included) / `sound`. `until` / `parallel` / `race` raise `TypeError` — pause the
member Handles yourself. Stacks with `clock.paused`, `e.active = False`, and
`e.time_scale = 0`; clearing one freeze does not clear `.paused`. `name=` and tween
driver claims stay held while paused. A pointer hold freezes motion through a
separate private gate (`Handle._held`), never through `.paused`: `.paused` is the
author's switch only and never reports or undoes a hold ([Shapes Design.md —
Persistent drivers](Shapes%20Design.md#persistent-drivers-vs-linked-pose)). `then=` / `on_done=` do not run on pause.
Author surface: [Guia da API — Handle](../docs/pt/guide/index.html#agendar-handle).

**First tick next frame.** A Handle created during `Scheduler.tick()` — including
one re-armed from its own `after` / `every` fire callback or `tween(..., on_done=...)`
— is not eligible until the *next* `tick()`. The same rule already holds for
`update`, collision, flush, `on_update`, and async resume. Re-arming
`after(0.5, self._hop)` from `_hop` itself is the natural spelling of “and then
again”; a hitch or `delay=0` must not spin inside one pass.

**Async wait.** `wait` / `until` / `until_empty` / `parallel` / `race` suspend a
coroutine the engine is driving. The **entry** is an async mode (`e.mode = diving`).
Helpers that mode `await`s are the same script — `await pause(0.4)` from the mode
body is legal. They are **not** an entry in `update` / `on_update` / `@collide` /
`@when` / a sync mode: calling them with no running script is `TypeError` (use
`after(...)`). A must-await Handle must be `await`ed or passed to `parallel` /
`race` **before the script yields or returns**; otherwise `TypeError` naming the
call site and `await …` (the Handle is cancelled and the script aborted). A Handle
the author already `cancel()`ed is not a forgotten await. `__del__` remains a backstop. Bare `wait(0.4)` does not block.

#### Rate instead of duration (`speed=`)

`speed=` is the author's other way to say how long a trip takes: units per
second on a translation (`move_to` / `move_by` / `move_along`, camera `pan_to` /
`pan_by`), degrees per second on a turn (`rotate_to` / `rotate_by` /
`reset_rotation`). The verb turns it into a duration **once, at the call**:
`time = distance / speed`, with the distance the verb already freezes — the
`move_to` travel from the point that lands (a `None` axis is a zero delta;
`about=` measures from that pivot), the `move_by` delta, the `rotate_to` short
arc, `|angle|` on `rotate_by` (an orbit too: the rate is the turn's), the
camera look-at delta, and on `move_along` `track.length × |span1 − span0|`
(`phase=` does not change it). From there it is the tween `time=` builds, so
`ease=` (then `speed` is the average), `loops=` / `yoyo=` (per leg), `then=`,
`pause()`, `time_scale` and the motion readout need no code of their own; with
`ease="linear"` `h.speed` reads the rate asked for. Rules:

- **Frozen like the target.** A target that moves later, or a track that grows
  later, does not change the duration (the same rule as the snapshot of a
  `move_to` target). Pursuit at a rate is per-frame work in `update(dt)`:
  `approach(current, target, speed)` (`easing.py`), the Guia's answer.
- **One of the two.** `time=` and `speed=` together raise `TypeError`;
  `move_along` with neither raises naming both.
- **A rate is a positive finite number** (`validate.fixed_magnitude`,
  `positive=True`): `0`, negative, NaN / inf, bool, text or a function raise
  naming `<verb> speed=`. It is checked before the verb touches the job in
  flight (`_check_speed` runs first in every timed helper; the distance is read
  without writing), so a refused rate leaves no trace.
- **Zero distance** is a zero duration: done on the next tick with `on_done`,
  and a zero-length `loops="forever"` finishes instead of spinning (the
  `time=0` path of `Handle._tick_tween`). An empty group's verb is the same
  zero-length timer.
- **Not on ratios.** `scale_*`, `zoom_*`, `tween()`, camera `rotate_*` /
  `frame_to` / `set_origin` / `reset_view` have no `speed=`: a scale or zoom is
  a ratio, not a distance, and the others move several channels at once. The
  subclass pose wrapper (`entity._install_timed_pose`) refuses `speed=` on a
  scale with a sentence; an explicit signature lets Python's unknown-keyword
  error stand (no refuse-only keyword in `help()`).
- **Messages quote the call.** A claim conflict names `move_to(speed=50)`, not
  the derived duration (`_motion_label`).

Guard: `tests/test_timed_speed.py` — contract per verb and kind, refusals,
and `TestEveryTimedVerbIsClassified`, which walks every public method with
`time=` (camera included) and fails until a new one is in `SPEED_VERBS` (and
takes `speed=`) or in `NO_SPEED` (and refuses it).

**Motion readout.** Translation motion tweens (`move_along`, `move_to(..., time=)`,
`move_by(..., time=)`, and the same with `speed=`) stash this tick’s pose delta as three floats. `.velocity` /
`.speed` / `.heading` compute on read (`Vec2.temp` / hypot / atan2, or the track
tangent — same quantity as `face=`). Ride handles also expose `.u` (mapped track
parameter) and `.lap` (0-based; `loops="forever"` keeps counting). Non-motion
handles (`after` / `every` / `wait` / rotate / scale / `tween`) raise
`AttributeError` with a hint. Done or cancelled freezes the last tick (so
`on_done` can still read exit speed). Movers never write `Graphic.vel` — the
author copies if they want (`crate.vel = h.velocity` for a body let go of the platform; a body standing on it is already carried by `resolve()`, Collision Design "Riders", so copying the rate there moves it twice).

**`loops=` / `yoyo=`.** Shared by timed pose, `tween()`, and the camera suite
(`1`, int `N`, or `"forever"` — same spelling as `move_along` / `play_sound`).
`yoyo=True` swaps start/end each odd lap (same named `ease` applied forward on
every leg — not a time-mirrored curve). Implemented once in `Handle._tick_tween`
as `u → 1 − u` on odd laps (affine writes make that equivalent to swapping
endpoints / flipping `span`). Finite `loops=N` with yoyo: rests at start if `N`
is even, at end if `N` is odd. `loops="forever"` never fires `on_done` / `then=`.
`yoyo=True` with `loops=1` raises. `loops=` must be an int ≥ 1, an integral
float (`2.0`), or `"forever"`. `True` / `False` and non-integral floats (`1.5`)
raise `ValueError` (bool is an `int` subclass and must not become one lap).
On `move_along`, yoyo flips the effective
`span` direction; `phase=` stays the conga-line offset and is unaffected.
`face=True` flips heading 180° when travel is reverse (yoyo odd lap or
`span=(1, 0)` on `move_along`). The same `face=` lives on `move_to` /
`move_by` (instant or timed): heading is `atan2(dy, dx)` of the frozen
travel delta; zero delta holds rotation. `move_by(distance=)` without
`angle=` (the delta *is* the heading) refuses `face=True` — see
[Shapes — move_by](Shapes%20Design.md). Multi-key tween
(`id(center)` + `(id(shape), "angle")`) matches `move_along` so a
concurrent `rotate_*` cancels the face ride.

**`tween` / `lerp`.** `tween(target, to, time=…)` writes a bracket handle
(`FieldRef`), a live `Attribute`, or a pose Container (`Point` / `x`+`y`
`takein`). Scalar / multi-value Attribute paths call free `lerp` from
`easing.py` each tick; pose keeps the allocation-free 2-float write.
`lerp(a, b, t)` is also author-facing (`from scena import lerp`): numbers,
flat tuples/lists, types with `.lerp(other, t)` (`Vec2`, `Color`), and pose
→ plain `(x, y)` (never allocates a Point). `t` is not clamped (elastic
overshoot). Incompatible shapes raise at `tween()` call time, not mid-run.
`Color.interpolate` / `Color.lerp` default to `ColorSpace.OKLAB`. Documented
contract for sequences is depth-1; deeper nesting may work but is not promised.
Author surface: [Guia da API — tween](../docs/pt/guide/index.html#mover-tween),
[lerp](../docs/pt/guide/index.html#util-lerp).

### Mode enter / exit

The mode function **is** enter. `@on_mode` is an optional visual marker (no runtime
effect on assign / `then=` / `==`). `@exit_mode(enter_fn)` is optional cleanup for
that mode. There is no `on_enter`. Mode identity stays a callable, compared with `==`.

Assigning `e.mode = diving`:

1. Reject non-callables (fail loud — see Protections).
2. If `value == e.mode` already (including both `None`), **no-op** — do not exit, do not
   re-enter, do not reset `mode_time`. Defensive guards (`if x: e.mode = e.formation`)
   are safe.
3. Otherwise cancel work **scoped to the previous mode** (timers / tweens / timed pose /
   mode script started in that body). Do **not** cancel: transients, `sprite.play()`,
   entity-scoped timers (`e.after` / `e.every` / `e.tween`), event-track scripts.
4. Run the outgoing mode's `@exit_mode` hook if one is attached — with **no**
   ambient owner (`process.no_owner`), so work it starts is entity-scoped by
   default even when the change was made from another actor's mode body.
   An exception — a watchdog trip too — still completes the transition, then
   re-raises. Cleanup must not block the next mode. Inside its own exit hook
   `self.mode = …` / `goto_mode` raises `TypeError` (the change is already
   under way; it used to re-run the hook until `RecursionError`), and a hook
   that destroys the actor ends the transition there: no next body runs on a
   dead actor (review 2026-10-09 S2-1, S2-3, S2-4, S2-12).
5. Store the callable; `mode_time = 0`.
6. Inspect **once**: `async` → exclusive mode script; plain `def` → call **once**.
7. `e.mode = None` → cancel scoped work, run the exit hook, no body.

To force exit+enter even when the target equals the current mode, use
`e.goto_mode(diving)`. Same validation and transition steps as assignment, always.

Compare with `==`, never `is` (bound methods are recreated). Body finished is **not** an
exit — a sync `formation` that only arms `every(...)` is the normal idle mode.
Frozen-mode warning only if nothing is pending past `FROZEN_MODE_S` (2s) — idle time,
not the mode's age: an async body that waited 2 s and then started a cover fade
before `change_act` is not frozen (AC7). Idle counts from the mode time at
which its last work ended (the async body, the last owned timer or tween; the
scheduler writes it on the owner, `_mode_idle_from`, when that work leaves;
entering a mode resets it),
or from the mode's start when nothing ended. A mode younger than
`FROZEN_MODE_S` is not looked at (the cheap exit). Guard:
`test_process.TestFrozenModeWarning`.

A mode with no exit hook is unchanged from enter-only. `@exit_mode` attaches to the
enter *callable* (no class/module registry) — the same way `@every` attaches `fn.handle`.

#### Cancelling pending work when leaving a mode

**One rule:** anything you start while a mode body is running — `after`, `every`,
`wait`, `until`, `parallel`, `race`, `tween`, timed `move_*` / `rotate_*` / `scale_*`,
`move_along` — belongs to that mode and dies when you leave. Use `e.after` /
`e.every` / `e.tween` when the job must survive the mode change (and still dies on
`destroy()` / `cancel_process()`).

```python
@on_mode
def formation(self):
    every(2.0, self.shoot)                 # dies when leaving formation
    after(3.0, then=self.diving)           # idem
    self.move_along(track, time=2.4, loops="forever")  # idem

@on_mode
def charging(self):
    self.glow = True
    after(0.5, then=self.diving)           # timer auto-cancels on leave

@exit_mode(charging)
def charging_exit(self):
    self.glow = False                      # not a Handle — needs the hook
```

`@exit_mode` is for **non-Handle** cleanup (looks, ink). Do not use it only to
cancel timers — those cancel automatically. Sync or async enter functions may both
attach an exit hook.

Work the exit hook itself schedules has **no** ambient mode context:

- `self.foo(...)` / `after(0.4, self.ping)` → entity-scoped (survives next mode).
- Bare `after(0.5, then=...)` with no inferable owner → existing `TypeError`.
- A fire-and-forget free function → script scope.

`destroy()` does **not** fire `@exit_mode`. Async modes may still use `try`/`finally`
for rare non-Handle cleanup that must sit next to setup; `Cancelled` is a
`BaseException`, so `finally` still runs. Cleanup that must run no matter how the
Entity ends is `on_destroy` (below).

Async cancellation raises **`Cancelled` as a `BaseException`**; `finally` still runs.
Waiting on a dead entity ends the script silently. Assigning `e.mode = …` from *inside*
the running script does not throw (coroutine on the stack); script is marked done and
closed after `send()` returns.

**Silent-death gap (only when the *mode's own owner* is torn down).** The rule
above — dead owner, no warning — covers `destroy()` on the entity the mode is
running on, or an explicit mode switch: both go through `Script.cancel()`
throwing `Cancelled` in *before or after* `Script._advance` runs the
coroutine, so an uncaught `Cancelled` never has to bubble out of `_advance`
itself. A **different** situation reaches `_advance`'s own `except Cancelled:`
handler: the mode's owner is still alive, but something it is `await`ing
(a tween on itself or on a *different* entity, `until()`, `wait()`, …) gets
cancelled out from under it — another tween claims the same property key
([Shapes Design.md — Persistent drivers](Shapes%20Design.md#persistent-drivers-vs-linked-pose)),
or the entity that Handle was tweening (not necessarily the mode's owner —
e.g. a Director awaiting `wasp.move_to(..., time=)`) is destroyed mid-flight,
or an `until()` predicate's subject is destroyed (the "retires quietly" rule
above is about the `until()` *Handle* not raising `DestroyedError`; the
`Cancelled` it still raises into anything awaiting it is a separate signal).
If the author's `async def` does not catch `Cancelled` around that `await`,
the mode stops running for good while `.mode` keeps reporting the now-dead
function — previously with **zero** signal. This now emits a `RuntimeWarning`
("async mode … was silently cancelled") naming the mode and owner, so the gap
is visible instead of a mode that just quietly stops advancing. Wrap the
`await` in `try: ... except Cancelled: ...` if the cancellation is expected
and the warning is not wanted. Tests: `tests/test_process.py`
(`test_awaited_tween_preempted_by_key_warns_and_stops_mode`,
`test_awaited_tween_target_destroyed_warns_and_stops_mode`).

**A rejected timed verb replaces nothing.** Every timed pose verb and
`tween()` runs the checks `_start_tween` makes (`time=` a finite number ≥ 0,
`ease=`, `then=` / `on_done=`) in `_validate_timed`, before the same-property
replace cancels the job in flight and before `face=True` snaps the heading.
Before 2026-10-09, `c.move_to(0, 300, time=-1)` raised after it had already
cancelled the move in flight (review S2-5; guard
`tests/test_rejected_calls_leave_no_trace.py`).

### `@on_mode`

Pure annotation: `fn._is_mode = True`; returns `fn` unchanged. Lets a reader tell a
mode body from an event handler (`on_hit`) or a helper (`shoot`) at the definition
site, matching `@every` / `@after` / `@collide`. Classless usage is the same tag:
`@on_mode` / `w.mode = entering`.

The tag is the source for a later modes inventory (debug overlay, runtime-recorded
transition trace). That overlay is not required to ship the decorator. `@on_mode` does
not require its target to be assigned to `.mode` somewhere — a static check cannot see
`self.mode = choice([...])` and a sometimes-wrong warning is worse than none.

Strings as mode names (`e.mode = "diving"`, `modes = [...]`) stay rejected: redundant
source of truth, typo safety only as loud as a registry, worse editor tooling, and
classless scripts would need a registry that does not exist. Callables keep rename /
jump-to-definition for free.

### Method decorators (`@every` / `@after` / `@collide_with` / `@when` / `@on_change`)

Classless `@every` / `@after` / `@collide` / `@when` / `@on_change` register **immediately**, against a concrete
owner / pair / condition that already exists. On a method the same decorator **tags**
(zero runtime effect at class body) and `_finish_actor_construct` performs the
identical registration once per instance — the same “tag now, bind later” rule as
fixed hooks and `@on_mode`. No second scheduler, collision registry, or group-scoped
timer. Decorators return the original function (no wrapper) so class and module
stacking rules stay identical.

Class-body detection (`process._in_executing_class_body`) rules out function
frames from `f_code.co_flags` (`CO_OPTIMIZED`) **before** reading `f_locals`:
on CPython ≤ 3.12, reading a function frame's `f_locals` caches a snapshot on
the frame, pinning every local — a destroyed `shot` decorated with
`@collide(shot, wall)` inside a long-lived async mode stayed alive after `del`
(system-test finding S7). Do not add `f_locals` reads of author frames.

**Roles (fail loud):** each callable has at most one role family. `@collide` /
`@collide_with*` and stacked `@when` (or stacked `@on_change`) may append on the
same function. `@every` / `@after` (timer), `@on_mode`, `@exit_mode`, and
`@leave_playfield` are exclusive — a second timer or a cross-family mix is a
`TypeError`. Decorating a discovered hook name (`on_update`, `setup`, `on_destroy`, …) is also a `TypeError`.
Script-level `@collide*` in a class body is a `TypeError` (use `@collide_with*`).
Script-level `@leave_playfield("…")` in a class body is a `TypeError` (use bare
`@leave_playfield` on the method). Group names are checked at the decorator:
`ANYTHING`, `group["x"]` and a class each raise with the right spelling. They
are callable (or `@collide` sides), so the bare-form test (`callable` and not a
`str`) must exclude `GroupOperator` and `type`, or they are taken for the
handler. Handler arity is checked there too (`check_handler_arity`: `item` at
script level, `self, item` on a method), as for `@collide`.

| Decorator | Class body | Construct |
|-----------|------------|-----------|
| `@every(interval, name=)` | Store `_every_spec`; do not arm | `every_on(item, …)` entity-scoped. Dies on `destroy()` / `cancel_process()`. |
| `@after(delay, name=)` | Store `_after_spec`; do not arm | `after_on(item, …)` entity-scoped. Dies on `destroy()` / `cancel_process()`. |
| `@collide_with(target)` / `_stay` / `_exit` | Append `_collide_with_specs`; `TypeError` on a free function | `add_pair_handler(item, target, adapter)` |
| `@leave_playfield` | Tag `_leave_playfield_method`; no group names | `add_instance_handler(item, fn)`: the plain function, called `fn(item, item)` (never a bound method; [Canvas Design](Canvas%20Design.md#playfield-leave-bounds)) |
| `@when(lambda self: …)` | Append `_when_specs`; condition takes **one** arg | After `setup()`, wrap `lambda: condition_fn(item)` into existing `EventSystem` |
| `@on_change(lambda self: …)` | Append `_when_specs` with `kind=ON_CHANGE`; target takes **one** arg | Same wrap / register as `@when`; callback may take the new value |

`__init_subclass__` cancels any mistaken script-scope `@every` / `@after` handle if class-body detection
missed. Module-level `@every` / `@after` / `@when` / `@on_change` / `@collide` are unchanged aside from
role checks and stacked-`@when` / `@on_change` list registration.

`@collide_with` adapter: pair dispatch is `(me, other, info)` but a bound method
already has `me` as `self`, so the author writes `def fn(self, other, info)`.
`@collide_with(ANYTHING)` plus a discovered `on_collide*` warns once per class
(double-dispatch). Object-literal pair handlers (classless `@collide(player, …)` or
per-instance `@collide_with`) are **swap-removed** on `destroy()` so short-lived
Entities do not leak `_pair_handlers` or flood dead-target warnings. Tag × tag
handlers are untouched.

Not included: class-/group-scoped `@every`; `self.collide_with` imperative twin
(deferred); `@collide(SELF, target)` (rejected); string `@when("hp <= 0")`.
A bare cell `@on_change(st["x"])` in a class body is a `TypeError` (callable
only, same as `@when`).

Polling in `on_update` with an explicit guard stays a documented alternative
to method `@when` / `@on_change` — zero API, no edge-trigger.

### `@exit_mode`

Optional. Declare "undo my own setup" once so every path that leaves that mode gets
it — instead of every mode reachable *from* it repeating the same cleanup line.

```python
@on_mode
def charging(self):
    self.glow = True
    after(0.5, then=self.diving)

@exit_mode(charging)
def charging_exit(self):
    self.glow = False
```

Protections at decoration / run time:

| Failure | Detection | Message |
|---------|-----------|---------|
| `@exit_mode` on an `async def` exit hook | `_is_async_callable` at decoration | `TypeError`: exit hooks must be a plain function; use `try`/`finally` in the async body if cleanup must sit next to setup |
| `@exit_mode` twice on the same enter function | `getattr(enter_fn, "_exit_mode")` | Warn: replaces an existing exit hook — remove the duplicate `@exit_mode` if this wasn't intentional |
| Exception inside the hook | `try/except Exception` around `_invoke` in the mode setter | Warn with entity, hook, **mode being entered**, traceback; transition continues |

`@exit_mode` on an **async** enter function is allowed — use it for looks / ink the same
way as on a sync mode. Mode-scoped Handles already cancel; the hook is not competing
with `try`/`finally` for timer cleanup.

Same-mode reassignment calls **both** halves (exit then enter). Skipping both would
reopen the silent-no-op failure enter already rejected; skipping one half would be a
new asymmetric rule. "Exit runs whenever mode-scoped work is cancelled" is one
sentence, and cancellation already happens on restart today. A caller who wants a
no-op still writes `if self.mode != self.charging: ...` — that guard now protects
both halves.

### `on_destroy`

Fixed-name lifecycle hook, the sixth member of the name-discovered family
(`on_update`, `on_click`, `on_collide`, `on_collide_stay`, `on_collide_exit`,
`on_destroy`). Not a decorator — the name has one canonical spelling. Class form
auto-discovered; classless is `e.on_destroy = fn`. Arity-truncated via `_invoke`.

```
destroy():
    1. if on_destroy is set, call it — self is still fully alive (ink, groups,
       layer intact). An exception propagates after the teardown completes
       (steps 2–3 run in a ``finally``), as Protections says: author errors
       raise. (This line said "warn and are swallowed" until 2026-10-09,
       which the code never did; review X-life-10.)
    2. mark it dying (a destroy() from its own hooks is a no-op) and take it
       out of its group buckets (a survivor's handler counting the group sees
       it gone); then fire the collision and pointer exits — the dying
       object's own exit hooks run while it still reads alive.
    3. mark is_alive = False and active = False (not via the park setter);
       cancel every handle / script owned by this item; retire classless
       @when / @on_change whose condition reads it (a field that stays
       readable after destroy never raised, so the watch never retired).
    4. retire every Entity part (see below), then drop its tags, the roster
       entry and the layer. An exit-hook error re-raises here, after the
       whole teardown (review 2026-10-09 X-life-5, S9-2, S2-8).
```

A broadcast (`group["mine"].blast()`) skips a member an earlier member's call
destroyed during that broadcast (a chain reaction the author cannot guard);
a member dead before the broadcast still raises (S9-3). Every `tween()` door
(`tween(x["field"])`, `tween(x.center)`) has the timed pose verbs' dead-target
rule: the target dies mid-flight → quiet cancel, no write, no `on_done` (S2-2).
`setup()`, `on_destroy` and `@exit_mode` run with no ambient mode owner even
when called from inside another actor's mode body (S2-1).

#### Parts leave with their owner

A shape's Point parts (a Circle's `center`, a Line's `p1` / `p2`, Polygon vertices,
a Track's `center`) are Entities and register like actors: roster, and — once shown
by `show_handles()` / `part.visible = True` — a draw layer and its pointer list.
`destroy()` retires them with the owner (`Registry.retire_part`, deepest first, after
the owner's `on_destroy`): off every layer, pointer list, group and the roster;
`is_alive` False; their timers already end with the host (W4). A part is not an
actor: it gets no `on_destroy` of its own. The failed-constructor rollback
(`place._drop_failed_construct`) retires parts built before the raise the same way.

Afterwards a part behaves exactly like any destroyed actor: pose reads stay
(`dead.center.x`, `Point(dead.center)` copies the value); `if dead.center:` is False;
writes (`move_by`, `.x =`, `visible =`, `@=`, `tag`) raise `DestroyedError` whose note
names the owner (`— a part of the Circle made at app.py:5, which was destroyed at
app.py:9`). Before (P1) a part stayed alive and ownerless; a shown handle kept
drawing and could still be dragged forever (the layer list held it), and a dead
part could be shown again. Guards: `test_part_lifecycle` (every family × hidden /
handles / visible), invariant `parts_follow_their_owner` in `test_hyp_canvas`,
canary `test_p1_part_outlives_its_owner`.

#### A part is not an actor

A part is geometry of its owner. It keeps what handles need — `visible`, `handle`,
`draggable` / `clickable` on a shown handle, reads, moves while the owner lives, and
its own timers (they end with the host, W4). It refuses the actor-only verbs, each
with a `TypeError` naming the owner (`entity.refuse_part_as_actor`, `is_part`):

| Verb on a part | Why refused | Spelling instead |
|---|---|---|
| `tag` / `untag` / `add_to_group` / `remove_from_group` / `group =` | Groups are actor-level (collision enrollment, bulk verbs) | Tag the owner; a Python list of parts |
| `collidable = True`, `on_collide* =`, a part as a `@collide` / `@collide_stay` / `@collide_exit` / `resolve` / `unresolve` side, `Collider([part])` | A part as its own body hands handlers a Point instead of the actor, `resolve` pushes one point (a Circle's disc overlaps the wall, a Line stretches), one shape becomes two bodies, and every actor rule (park, `collidable`, destroy, scenes) would need owner propagation | `@collide(owner, …)` + `info.point`; `wall.contains_point(line.p2)`; an author-owned follower `tip = Point(lambda: line.p2)` |
| `destroy()`, `active =` | A live Circle on a dead centre; a parked point of a live shape | `owner.destroy()` / `owner.active = False` — the owner's park parks its parts ([`active` (park)](#active-park)) |

Allowed: `collidable = False` and `on_collide = None` (the state a part is in), and
queries that enroll nothing (`test_collision(part, x)`, `part.collides_with()`, which
use an unregistered probe collider; `ensure_collider` refuses a part as a backstop).
A hard layer clear (`Layer.clear(hard=True)` / `delete(destroy_shapes=True)` /
`reset_layers`) destroys the **actors** on the layer; a shown handle whose owner is
elsewhere is only undrawn (`Registry._drain_layer`).

Part collision, if a script ever needs it, is a separate design built on the
[Sprite hitbox-part contract](Sprite%20Design.md#hitbox-parts): detect-only, the
owner answers (`me` / `other` is the actor, `info` names the part), park /
`collidable` / destroy apply to owner and parts together. Not Points as bodies.
Guards: `test_part_lifecycle` (`TestPartsHaveNoTags`, `TestPartIsNotABody`,
`TestPartLivesWithItsOwner`).

If the hook reassigns `.mode` or arms a timer, step 2 sweeps it. That is why
`on_destroy` is safe on destroy where `@exit_mode` is not: cancellation runs
*after* this hook, *before* an exit hook (the outgoing mode's scope must be
cleared before anything new claims it).

- Fires **exactly once**, only from `destroy()` — never from a mode change, never
  from `active = False`, never from `cancel_process()`.
- Independent of `mode` — works for a bare `Entity()`, a bullet, anything that
  never touches `.mode`.
- Not a replacement for `@exit_mode`: "this entity is gone" vs. "I'm leaving
  *this mode* for another one." An Entity can use either, both, or neither.
  Dying via a mode transition fires `@exit_mode` only; dying via `destroy()` fires
  `on_destroy` only.

No auto-attach-to-next-constructed-Entity convenience: `e.on_destroy = fn` is already
the same typing as `e.on_update = fn`, and implicit attach would silently hit the
wrong instance in a spawner loop.

### Tracks

| Track | Policy |
|-------|--------|
| Mode script | One per Entity; a new mode cancels it |
| Event handler (`@collide`, `@when`, `on_click`) | One running instance; re-entry **ignored** (async event-track later) |
| `on_update` | Every frame, including during `await` |
| `on_destroy` | Once, from `destroy()` only, before teardown |

A hit-flash handler must not abort a dive. Cosmetic FX are not modes (use transients).

### Ownership (no `on=`)

**One rule for all process Handles** (`after` / `every` / `wait` / `until` /
`parallel` / `race` / `tween` / timed pose / `move_along` / `play_sound`):

| Where you write it | Owner | Scope |
|-----------------------------------|-------|--------|
| Inside a mode body (sync or async), bare call | that Entity | **mode** (dies on leave; a sound that ends by itself finishes — [Sound Design](Sound%20Design.md#when-the-owner-ends)) |
| `e.after(...)` / `e.every(...)` / `e.tween(...)` / `e.play_sound(...)` | `e` | **entity** (survives mode; dies on `destroy` / `cancel_process` — on `destroy` a sound that ends by itself finishes) |
| Bound method of a *different* Entity — `after(0.4, bomb.destroy)` from wasp's mode | that other Entity | **entity** |
| Plain `after(2, drop)` at script level (lambda / free fn, no mode running) | none | **game** before the top level ends; **act** after it (ends on the next act change) — [Act Design](Act%20Design.md#lifetime-the-game-and-the-act) |
| `setup` / `on_update` / `@collide` / `@when` | receiver or script | **entity** or script — no ambient mode |
| A lambda / nested def / `functools.partial` whose closure holds the method's `self` (`after(0.1, lambda: self.set_color("red"))` in `on_update`) | that Entity, exactly as the bound method `after(0.1, self.piscar)` | **entity** (from inside its own mode body: **mode**). Only the closure cell named `self` counts: `lambda: alvo.destroy()` keeps the row above. Inside the actor's own `on_destroy` the closure keeps the plain rule (work "after I am gone" runs after the death). Before 2026-10-14 the closure was act work: it outlived the actor and raised DestroyedError, or made a dead enemy shoot (review PA4) |

`destroy()` and `cancel_process()` both cancel **all** handles owned by the item —
get the owner right at schedule time. `destroy()` also drops the owner from the
scheduler's mode / `on_update` sets at once, and an idle frame (no timers, modes
or `on_update` left) still clears the dense owner snapshots and pumps an offline
mixer — the last destroyed actor must not stay in memory, and its cancelled voice
must actually stop (system-test findings S2 / S4). Work scheduled on an actor that
is already destroyed is never registered (S9). Lifetime is checked end to end by
`tests/test_sys_lifetime.py` and `tests/test_sys_hyp_world.py`. Prefer `fx.after(0.55, fx.destroy)` for debris
teardown. Use `cancel_process()` when the Entity must stay alive (restart / re-arm).

`@collide` does **not** set a current owner. From a script handler, use `wasp.after(...)`
or a bound method.

### Frame order

Canonical frame order lives in [Scena Design.md — Datapath](Scena%20Design.md#datapath).

1. `clock._tick` / input (poll events; sample world pointer)
2. User script `update(dt)`
3. Process tick (tweens, due timers, async resume, `on_update`)
4. Collision
5. `flush` `@when` / `@on_change` / `@collide` (handlers may start processes; first tick next frame is fine)
6. Transients
7. Draw

Details of process ownership and mode cancellation relative to that order: this document.

### Layers vs looks (do not mix)

| Thing | Job | Cancelled by mode change? |
|-------|-----|---------------------------|
| Mode script + mode-scoped timers / tweens / waits / timed pose | *What this Entity is doing* | Yes |
| `e.after` / `e.every` / `e.tween` / `e.play_sound` | *Entity-owned jobs* | No (dies on `destroy` / `cancel_process`; a finite sound finishes after `destroy`) |
| `@collide` / `@when` handlers | *Reactions* | No (event track) |
| Shape transients, canvas shake | *How it looks for a moment* | **No** |
| `.visual`, stamps (`.glow` / …), background fields | *Sticky costume / pigment / world* | No |
| `sprite.play("walk")` | *Which frames* | No (it’s a look) |

Do not add a second flash/shake/tint API. Process “effects” **are** existing transients.

### Protections

Raise immediately. Name the Entity, the call, the line, and **what to write instead**.
Silent freeze is the failure to prevent.

**Omit vs junk.** Gradual params means **omission** of known keys fills defaults
(`Circle()`, `Circle(radius=50)`). Unknown or wrong-family keywords raise
`TypeError` with a family hint (`Circle(aaa=1)`, `Sprite(radius=5)`). Missing
image / atlas assets stay legal (checker + warn once). Missing / corrupt
**sound** files stay legal too (silence + warn once) — because there is no
visual checker, the warning also shows on the on-canvas banner as
**SCENA WARNING** (amber), same Ctrl+Shift+E dismiss. The banner carries
warnings only.

**Author errors are loud.** The framework does not isolate author code. An
exception in any author hook — `update`, `setup`, `on_update`, `every` / `after`
fire, tween `on_done`, async mode bodies, `@when` / `@on_change`,
`@collide*`, `@leave_playfield`, transient / cover `on_done`, `@exit_mode`,
`on_destroy`, SpatialFx `tick` — propagates with its original traceback, and
`run()` releases the window / GPU / audio on the way out. The framework keeps
itself consistent first (`finally`), so a caught error (tests, a manual
`flush()` in a `try`) leaves sane state: the fired timer / edge / leave is
consumed, a mode transition completes, `destroy()` finishes teardown. Only
environment conditions are handled and continued: the freeze watchdog (tight
loop → warn + skip / disable), missing assets (checker / SCENA WARNING), no
audio device, clock hitches.

| Author wrote | Message intent |
|--------------|----------------|
| `e.mode = diving()` / `"diving"` | Must be a function; drop `()` / don’t use a string |
| `fn` / `on_done=` and `then=` both | Use one channel, not both |
| `wait(0.4)` with no running async script | `TypeError`: only inside an async mode (or a helper that mode awaits); use `after(...)` |
| `wait(0.4)` without `await` inside an async mode | `TypeError` with call site and `await wait(0.4)`; Handle cancelled, script aborted |
| Unknown `ease=` | `ValueError` listing catalog |
| A class-body method the engine never calls: `def update(self, dt)`; a top-of-file input name (`on_key_down`, `on_mouse_click`, …); one edit or one swap from a hook (`on_colide`, `on_updat`, `on_destory`; the pool is the hooks plus every `on_*` name of the engine bases); another engine's spelling (`on_collision`, `on_mouse_enter`); a plain method named `collide_with` | `TypeError` at the class line naming the hook (`entity._check_class_hook_names`, author classes only; decorated rule methods and names an author base defines pass). `update` overrode the graph recalculation and crashed the construction in `state._batch_update`; the rest was dead code (review 2026-10-14 PA3 / PC5). Guard: `tests/test_class_hook_names.py` (every exported family) |
| Every named `ease=` curve | `f(0) == 0.0` and `f(1) == 1.0` exactly (endpoint-exact) — a tween must start at its `from` and land exactly on `to`, even for curves that overshoot in between (`elastic`, `bounce`). `elastic` previously used a mis-transcribed formula (wrong overshoot period/phase, and not endpoint-exact); `sigmoid` / `erratic` previously landed a few ULP off `1.0` at `x=1`. Fixed in `easing.py`; regression coverage in `tests/test_easing.py` checks every named curve's `f(0)`/`f(1)` (`bounce`'s piecewise constants leave it ~3e-9 off at `places=6`, not a real bug — float precision, not asked to be "fixed" further). |
| `after` / `every` / `wait` non-finite, or `after` delay < 0, or `every` interval ≤ 0 | `ValueError` at the call. `after(0)` stays legal (fires next tick). `every` ≤ 0 names `on_update` / `update(dt)` — not a frame sentinel. |
| `canvas.framerate = 0` / negative / NaN / a non-number that is not a token (`"vsinc"` → did-you-mean `"vsync"`) | `ValueError` / `TypeError` at the assignment, before anything changes (FX Auto stays as it was) |
| `tween` / `lerp` type or length mismatch | `TypeError` / `ValueError` at call time (before the first tick) |
| `while True` with no await / return | Watchdog cancels mode / disables `on_update` / skips script `update` (`WATCHDOG_RESUME_S`, default 0.5s wall) |
| Re-arm `after` / `every` / `tween(on_done=)` from its own fire | New handle waits for the next tick — no same-pass spin on hitch or `delay=0` |
| Timer flood from `on_update` | `name=` replaces and is not a flood; unnamed same owner+site still warn if >N/sec |
| `h.remaining = …` | `TypeError`: read-only; restart with `after(..., name=)` or `h.cancel()` |
| `after(1, fn).velocity` | `AttributeError` with a hint: velocity is on `move_along` / timed `move_to` / `move_by` |
| `after(1, fn).volume` / `.level` | `AttributeError` with a hint: those are on `play_sound` handles |
| Exception in a **mode body** / `then=` (sync enter) | Raise. Name the Entity, the mode, the line. Do not leave a frozen idle mode. |
| Exception in an **async mode** body | Raise. The body's task ends (coroutine closed, task handle cancelled, `_mode_task` cleared); work the body started stays (as a timer's error leaves its siblings). |
| Async mode `await`s something that is not a Handle | `TypeError`: await a Handle (`wait` / `until` / `move_to(time=)` / `after`); script aborted |
| Exception in an **exit hook** (`@exit_mode`) | Raise after the transition completes (the new mode is entered; an error entering it chains onto the exit error). |
| Exception in **`on_destroy`** | Raise after `destroy()` completes teardown. Same for a partner's `on_collide_exit` fired by the destroy: every exit of the body and of each hitbox part fires, each with its own error, and the first is raised after the cleanup (a raising body exit skipped the part exits and left their keys: review 2026-10-09 S8-10). |
| Exception in a GLFW input callback (`on_key_down`, `@click`, a widget) | Raise. pyGLFW drops the rest of that poll's events after a raise, so the frame re-reads held keys and mouse buttons from the OS before the error leaves (`_resync_input_from_os`): a caught error does not leave `keyp("SPACE")` stuck on a key the OS reports up (review 2026-10-09 S1-9). |
| Exception in a **handler** (`every`/`after` fire, `on_update`, tween `on_done`, `setup`) | Raise. The fire is consumed first (`after` is done, `every` restarted its interval). `until` predicates and tween writes cancel their Handle, then raise. |
| Exception in **`@when` / `@on_change`** | Raise (condition or callback). The edge is consumed before the callback runs, so a caught error does not refire; later watches run on the next poll. A non-bool `@when` is a `TypeError` — at registration when the seed value is already non-bool, else at the write that makes it so. Handler arity is checked at the decorator: `@when` handlers take `()` (methods `(self)`), `@on_change` `()` or `(value)`, `@collide` up to `(me, other, info)`; a non-condition (`@when(5)`, `@when("hp <= 0")`) raises. A source destroyed under the watch (`DestroyedError` / `ReferenceError`) retires it quietly; any other error — including a typo `AttributeError` — raises, at registration if the first evaluation already fails. |
| `@when` already True at registration | Rising edge: it does not fire until the condition goes False, then True again. |
| Exception in **`@collide` / `on_collide*`**, `@leave_playfield` | Raise (a leave edge is consumed first). |
| `@exit_mode` on an `async def` **exit hook** | `TypeError` at decoration: use a plain function; put async cleanup in `try`/`finally` if it must sit next to setup |
| `async def` anywhere Scena **calls** a function (only a mode is driven as a script) | `TypeError` with the fix (plain `def`; waits go in an async mode started with `self.mode = self.intro`). Each funnel refuses it, so the body cannot silently never run (Python only prints "coroutine … was never awaited"): class-body hooks (`setup`, `on_update`, `on_click`, `on_collide*`, `on_destroy` …) at the class statement (`_cache_actor_lookups`); every decorator but `@on_mode` (`_claim_decorator_role`); `on_update =` / `on_destroy =` / `on_collide* =` / pointer handlers / `expect_callable` slots at the assignment; script hooks (`update`, `on_key_down` …) when `run()` binds them; predicates, conditions and formulas at the call (`group.filter` / `any` / `all` / `count_where` / `group.nearest(where=)`, the free `nearest(where=)`, `until`, the `@when` condition, the `@on_change` target, `resolve(only=)`, an `@=` formula): their coroutine is truthy, so before 2026-10-12 a filter kept every member, `until` ended at once, `@on_change` fired every frame (AH2). `after` / `every` / `on_done=` are hot calls and skip the registration check: `_invoke` refuses at the fire. Backstop at the call (`_invoke`, `call_truncated`): a sync callback that returns a coroutine (`lambda: self.intro()`) raises naming both, coroutine closed. An async function called without `await` in author code (`self.intro()` as a statement) is reported where it happens: importing Scena replaces `warnings._warn_unawaited_coroutine` (`process.install_unawaited_hook`), so the dropped coroutine becomes a SCENA WARNING (banner + console) at the dropping line that names the function, that line, and the fix (`await intro()` in async code; an async mode from a plain def). Coroutines of the engine, the stdlib and site-packages keep Python's own text and location; a hook failure falls back to it; an interpreter that does not call the hook (checked once with a probe coroutine) keeps Python's warning. The hook turns coroutine origin tracking on (depth 1, ~40 ns per coroutine made: mode entries and helper calls only). `then=` takes an async mode. Tests: `tests/test_async_hooks.py`; `TestEveryCallbackDoor` enumerates every callback door from the public surface (a new one needs a case). |
| Frozen mode | Warn once naming Entity + mode |
| `@when` after `destroy` | Inert: registration dropped, don’t fire, don’t traceback |
| `e.mode = fn` / `e.goto_mode(fn)` on a destroyed actor | `DestroyedError` — the body never runs (it used to run and arm work for a dead actor). `e.mode = None` stays a quiet no-op. |
| Instant change on a destroyed actor: `move_by` / `move_to` / `rotate_*` / `scale_*` without `time=`, `confine`, `visible`, `collidable`, `play`, `set_color`, slot write (`dead.radius =`, `dead.x =`), and every other public setter (`time_scale`, `mass`, `clickable`, `corner_radius`, paint …: teardown gives the instance a route map in which every name refuses, `_mark_routes_dead`, so a live write pays nothing; graphics review E14) except the quiet ones (`active = True`, `mode = None`, `on_update`) | `DestroyedError`. The message names the verb, where `destroy()` ran (History's own note is kept when it already set one), the call site, and `if nave:` when the source line looks like `nave.move_by`. Pose reads (`.center` once it exists) stay. Ink reads still raise. `active = True` stays a no-op (must not revive). A missed verb must not surface as `NotImplementedError`. Slot check is one dict hop (`scripts/bench/perf_guards.py` stays in the same band). The refusal comes before any argument or value check, whatever the value (DV1 in Testing Design): `dead.move_to((nan, 0))`, `dead.rotate_to("a")`, `dead.add_to_group(5)`, `dead.radius = lambda: 3` raise `DestroyedError`, not the bad value's error. A verb's first statement is `if self._destroyed:` (a class default on Entity, so a living call pays one attribute read); the subclass pose overrides get it from `_install_timed_pose`'s wrapper and do not repeat it. |
| `if actor:` | Same check as `is_alive`. Boolean context means "usable", the same way an empty group is falsy — not a second lifetime API. `actor or other` skips a dead actor. |
| `e.after` / `every` / `tween` / timed pose / `move_along` / `play_sound` / `on_update` / a transient on a destroyed actor (e.g. from a dying body’s own `@collide_exit`) | Quiet no-op: the Handle comes back **already cancelled** and is never registered; nothing fires, nothing holds the dead actor. Exception today (DV3, open): a timed `scale_to` / `scale_by` and a Point's timed `move_to` / `move_by` / `move_along` raise `DestroyedError` from their call-time writability probe; they do so before checking an argument (`_refuse_dead_verb`). |

Watchdog uses `sys.monitoring` LINE and JUMP events (Python 3.12+); non-author code
(`scena.*`, stdlib) returns `DISABLE` after first touch so bulk `Sprite(...)` waves stay
lean. JUMP is for a loop on one line (`while not st.pronto: pass`, `while n < 10**9:
n += 1`): it emits no new LINE event, only its back jump, and escaped the guard
(review 2026-10-14 PA2). Only a back jump that lands on its own line counts; a forward
jump, or a back jump to another line (LINE already fires every iteration), returns
`DISABLE` on first touch, so a multi-line loop pays the JUMP callback once
(`_watchdog_on_jump`; interleaved A/B of 400 async-mode actors, half running a
20-step loop per frame: within noise, best frames 21.0–21.7 ms either way). Async mode resume is guarded by default; script `update(dt)` and `on_update`
require `scena.process.set_sync_watchdog(True)` (engine tooling, not in `scena.__all__`; off by default — ~10–15% frame cost when on).
`set_watchdog(False)` for benchmarks.

**One watchdog window per task walk.** `sys.monitoring.set_events` re-instruments
every function on the stack (the tick, the run loop: cost grows with their size), so
turning the events on and off around each resume cost ~25 µs per resume (300 async
modes: 2.0 s with the watchdog, 0.5 s without). The task walk opens one window at the
first task ready to resume (`_watchdog_window_open`) and closes it after the walk;
inside it `_run_with_watchdog` only resets the deadline and the line counter for each
resume, and leaves an infinite deadline between resumes (a `finally` a cancel throws
there never trips). Same 300 modes: 0.53 s (`test_process.TestWatchdogWindow`). A first
step (mode entry) still toggles around itself; its rare endings live out of
`Script._advance` (`_cancelled_under_it`, `_tripped_watchdog`) to keep that frame small.



## Implementation notes (maintainers)

- `Entity` has exactly **one** `__init_subclass__` (mixin `__init__` adoption → rollback wrap →
  actor-init wrap → setattr route → deferred `@every` / `@after` → cached lookups). The actor-init
  wrap runs the finish step inside the rollback; the rollback is `Registry._destroy_teardown`
  (one teardown, never a hand-kept copy). A second `def __init_subclass__` in the
  class body silently replaces the first (2026-09-25 regression: `Rect.rotation =` recursed,
  `setup()` stopped running). Extend the existing hook; `tests/test_entity_hooks.py` scans
  `scena/` for any duplicate `def` in one class body.
- **Dispatch by kind, never by class name.** Authors subclass (`class Pad(Rect)`,
  `class Ship(Sprite)`) and Scena subclasses Sprite (`Svg`, `SpriteButton`). Engine code
  asks `entity.scena_kind(obj)` (nearest Scena class in the MRO: `Pad` → `"Rect"`) or
  `entity.is_sprite_family(obj)`; `type(obj).__name__ == "…"` refused every subclass
  (Testing Design SB2). `tests/test_kind_dispatch.py` scans `scena/` for new name
  comparisons; a deliberate exact-type check carries `# exact-type: <reason>`.
- Tests: `reset_process_scheduler()` in `setUp`; `clock.advance(dt)` then `tick_processes()`.
  Motion readout: `tests/test_handle_motion.py`.
- Mode body runs inside `owning(e, scope="mode")`. Mode transition:
  `cancel_owner(obj, scopes=("mode",))`, then the outgoing `@exit_mode` hook (no
  owning context), then store and run the new body. Entity-scoped handles left alone.
- **An async mode's body is a task.** `Scheduler.start_task(owner, coro, scope="mode",
  mode=True)` makes a `Handle(kind="task")` (owner, scope, `_by_owner`, the `_tasks`
  bucket) whose `_task` is the `Script` driving the coroutine; `owner._mode_task`
  names it while it runs. So the mode's leave cancels the body with the mode's timers
  (`cancel_owner(scopes=("mode",))` — tasks after the other handles, so a `finally`
  in the body sees its timers already gone), and `destroy` / `cancel_process` / part
  teardown need no script special case. `Handle.cancel` on a task throws `Cancelled`
  into the body (`Script.cancel`, deferred while on the stack); a body that ends by
  itself (`Script._end`) completes the handle (its return value is `_result`) or, on
  an error, the watchdog or an awaited handle cancelled under it, leaves it cancelled
  without cancelling what the body started. The handle drops `_task` when it ends
  (no handle ↔ script cycle). The mode policy (same-mode no-op, `goto_mode`,
  `@exit_mode`, `mode_time`, the frozen-mode check, `then=`) stays on the Entity.
- `wait` / `until` / `until_empty` / `parallel` / `race` call `_require_running_script`.
  `Script._advance` reports leftover must-await Handles created this resume.
- `Shape.__slots__` must list `_time_scale`, `_on_update`, `_on_destroy`, `_mode_task`,
  `_frozen_warned`, `_actor_constructed` (forgetting → `AttributeError` on `Circle()`).
  `Entity` / `SpatialFx` have no those slots.
- Star-export: `after`, `every`, `tween`, `wait`, `until`, `until_empty`, `parallel`,
  `race`, `Handle`, `Cancelled`, `ReadyManager`, `RememberedManager`, `Entity`, `on_mode`, `exit_mode`,
  `lerp` (with `remap` / `MappingFunctions` from `easing.py` via `state`).
  Not `tick_processes` / `owning` / `reset_process_scheduler` (tests import from
  `scena.process`).
- `Clock.time` accumulates scaled `dt` (not wall-since-construct). Background / post FX that
  sample `clock.time` pause when `clock.scale=0`.
- `ready(name, interval)` keeps a steady cadence: a True moves the window by one
  interval from when it was due, not from the frame that noticed it (the overshoot
  was dropped, so the rate depended on the frame rate), and after a pause in polling
  it reopens one interval from now: no burst (review 2026-10-09 W-T2, decided). A
  self re-arming `after` or an `await wait(p)` loop starts each period at the frame
  that noticed the last one: "at least `p` apart", not a rate. Use `every` for a rate.
- `ready.reset(name)` sets `last_called = now - interval` so the next poll is True.
  Every `ready.*` / `recently.*` method checks the name (`_require_poll_name`)
  before the dict lookup (a list raised Python's "unhashable"), and
  `ready.disable(name)` on a name never polled is not a no-op: it makes a
  disabled slot, so "no shooting until the intro ends" written before the first
  shot holds; the first `ready(name, interval)` stores the interval and returns
  False until `enable` (review 2026-10-09 S2-15).
  `ready(name, interval)` / `e.ready(...)` validate `interval` (`_validate_ready_interval`):
  non-finite raises `ValueError` — `now - last_called >= nan` is always `False`,
  which used to mean "never ready again" with no error; a negative interval
  raises too — `>=` a negative number is always `True`, which used to mean
  "always ready," silently defeating the cooldown. Checked both when a timer
  is first created and when an existing one's interval is updated on recall.
- `recently(name, value, hold=)` / `e.recently(...)` validate `hold` the same
  way: non-finite or negative raises `ValueError` (a negative `hold` made
  `(now - last_true) <= hold` false even on the call that just set
  `last_true = now`, so a value that was truthy *right now* read back `False`).
- `recently(name, value, hold=)` / `e.recently(...)` share `_remembered_poll` (global
  `RememberedManager._slots` vs per-instance `_recently_state`). Level query: True every
  frame inside the window. Entity poll state (`_ready_state` / `_recently_state`) lives in
  instance `__dict__` (Container has no `__slots__`, so `Shape`/`Sprite` `__slots__` still
  allow private attrs) — dies with the instance; not a scheduler Handle.
- `e.ready(name, interval)` uses `_ready_poll` on `_ready_state` — independent cooldown
  per Entity (global `ready` stays the flat namespace).
- Collision runs **after** processes; handlers’ `after(...)` first tick next frame.
  Same rule for a handle created from a fire callback (`after` re-arm, `every`
  named replace, `tween(on_done=...)`): `Scheduler.tick()` copies **all four**
  buckets (`every`, `once`, `tween`, `await`) into lists **before any loop**.
  Copying one bucket at a time would let an `after()` created inside an `every`
  fire run in the same tick. The sound bucket is copied later, after `tick_audio`.
  Enroll / lazy hull / plain blit: [Sprite Design.md — Mass sprite hot path](Sprite%20Design.md#mass-sprite-hot-path).
- Arity (`_argcount`, event `_callback_npos`): both are
  `validate.payload_arity` — parameters with no default, a bound method's `self`
  not counted, `*args` gets everything. Functions and bound methods read
  `__code__` / `__defaults__` each call (no cache). Other callables
  (`partial`, `__call__` objects) cache in their **own** `__dict__`. Never cache
  on a bound method — `setattr` falls through to `__func__`, so a function used
  both plain and bound would see the wrong count — nor on a class (subclasses
  inherit it). `@on_change` arity is computed once per `EventRegistration`
  (`_npos`), not on the callable.
- Scheduler buckets (`_every`, `_once`, `_tween`, `_await_family`, `_sound`,
  and the union `_handles`) are insertion-ordered dicts (value unused), plus
  `_by_owner` keyed by `id(owner)`. Removal is O(1). `destroy`, mode change,
  and the frozen-mode check walk only that owner's handles. `EventSystem._events`
  is the same shape, with its own `_by_owner`, so `drop_owner` does not scan
  every `@when` / `@on_change`. Do **not** reintroduce tombstones or deferred
  removal: a finished Handle holds the Entity strongly, and a destroyed Entity
  must be collectable immediately after `destroy()` (no tick in between).
  Tasks are the `_tasks` bucket, walked after every other bucket and the sound
  tick, before `on_update`: a snapshot, then the tasks started during the walk
  (`_task_walk_extras`), so a mode entered from another task's step is visited in
  the same tick, as when scripts were a live list.
- Groups / formula `@=`: `registry.py` (`GroupOperator`, `Registry._group_formulas`).
  Formula eval uses a re-entrancy stack (`_group_formula_stack`); do not cache on
  `_group_gen`. `until_empty` resolves formula names through the same live path.
- Subclass `__init__` wrapping so `setup` runs after the most-derived `__init__`, once. An author `__init__` must call `super().__init__(**kwargs)`; one that does not is refused when the object is made (CB1, [Author `__init__`](#current-design-choices)).
- Performance and fail-loud, IDE-friendly author APIs remain constraints for all Entity work.

## Deferred

- Multi-body attach (turret / compound) — when a script needs it.
- Debug overlay (mode name, `mode_time`, active handles, `@on_mode` inventory).
  Runtime-recorded transition trace first if added; a static `then=` scan would
  silently under-report dynamic targets.
- Async event-track handlers (`@collide` / `@when` / `on_click`) — one running instance,
  re-entry ignored; modes are the async surface today.
- Edge-map silhouette FX on sprites — landed (FrameFx path + SDF; assign-time / `prepare_fx` warmup; Sprite Halo/Laser/Rim SDF).
- Pixel-crisp (`nearest`) sprite sampling flag.
- Auto hitbox follow-ups — see [Sprite Design.md — Deferred (auto hitbox)](Sprite%20Design.md#deferred-auto-hitbox).
- `group.sway_x` — parking lot / maybe. Formation stays author-side (`sorted` /
  `slot_x` / `phase=`). A group verb that invents layout is the same “framework
  invents the formation” reject as spatial walk order.
- Optional `SCENA HINT` when N Entities each own an identical `every` (not a silent merge).
- `self.collide_with(target)` imperative twin of `@collide_with` — decorator shipped first; add the method only if scripts need late/dynamic pair enrollment.
