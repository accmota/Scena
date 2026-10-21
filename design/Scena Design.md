# Scena Design

Architecture hub for the Scena reactive graphics framework. **Happy path only** —
subsystems, the data model, and the datapath. Depth lives in companion `* Design.md`
files (see [Where to go next](#where-to-go-next) — a menu, not a reading list).
Author surface: [Guia da API](../docs/pt/guide/index.html). Map of this folder:
[README.md](README.md).

This is **today’s baseline**, not a freeze — see [Design documents are descriptions, not locks](#design-documents-are-descriptions-not-locks).

| Goal | Go to |
| --- | --- |
| Locating code | [Appendix: module map](#appendix-module-map) |
| How a frame works | [Subsystems](#subsystems), [Datapath](#datapath) |
| The laws of time, lifetime, contacts, input and timers (short; read whole before changing them) | [Laws.md](Laws.md) |
| Author calls | [Guia da API](../docs/pt/guide/index.html) — do not start in `scena/` |
| Product intent | [Context](#context) |
| Changing or removing author API; releases | [Compatibility and versions](#compatibility-and-versions) |
| Testing, harnesses, bug catalogue | [Testing Design.md](Testing%20Design.md) |


# Context

Scena is a framework for creative graphical coding. It’s a reactive framework that allows links and formulas between attributes. It’s built in Python and runs over GLFW and Skia.

## Design documents are descriptions, not locks

These documents record **how things currently are** (or how we currently intend them). They do **not** freeze the design. Wording like “locked,” “final,” or “decided” elsewhere in older notes was a bad choice of words — treat it as “current understanding,” not a commitment.

Since **0.6.0 (2026-10-06)** the API is **published**: authors outside the project write code against it. We are no longer in the pure design phase. The design can still change, but a change to the author surface now has a cost, and that cost is borne by people we cannot see. See [Compatibility and versions](#compatibility-and-versions).

**A change is made when it is worth what it costs.** The criteria:

1. **Is the new design better** for our intended audience and goals (beginners, gradual params, authorship kept with the author, simplicity for ~10s–100s of objects)?
2. **What does the change cost us** — a small, low-risk edit vs. rewriting a large swath of the codebase?
3. **What does it cost authors** — does it break code that works today? How much (a rare keyword vs. a verb every tutorial uses)? Does the old code fail loudly with the fix in the message, or keep running and do something else?

Internal changes (engine modules, `_` names, performance work, the datapath) cost authors nothing; criteria 1–2 are enough, as before. Additive changes (a new verb, a new keyword with a default) are cheap. A **breaking** change is not forbidden — Scena is 0.x and the bar is still low — but it needs a payoff that clearly beats its author cost, and it follows the rules below. Large reversals need a clear payoff; small, scattered breaks are worse than one well-announced one.

When a doc says something “is” a certain way, read it as **today’s baseline**, open to challenge under these criteria.

The taught samples (`examples/`, `docs/pt/tutorial/`) and the Guia are now what authors copy. A change that forces edits there is a sign of author cost, not just a script to update. `scripts/` (smoke, bench) remain test scripts, not author code: change them freely.

## Compatibility and versions

The release number lives in `scena/_version.py` (`scena.__version__`); `pyproject.toml` reads it. What changed for authors is in [`CHANGELOG.md`](../CHANGELOG.md). Guard: `tests/test_version.py` (one source; a changelog section for the current version).

**What is public (the author surface):** the names in `scena.__all__` and what the [Guia](../docs/pt/guide/index.html) documents about them — keywords, defaults, fields, and behaviour. Level files (`"format": "scena-level", "version": 2`, [Editor Design.md](Editor%20Design.md)) are author data: a file saved today must still load. **Not public:** `_` names, engine modules imported by path (`scena.orchestration.set_leak_detector`, bench knobs), anything the Guia does not document, and SCENA WARNING / error message wording.

**Version numbers (0.x):**

| Change | Release |
| --- | --- |
| Bug fix; internal change; docs | patch (0.5.1) |
| New verb, keyword, kind, preset (old code runs unchanged) | minor (0.6.0) |
| Breaking change to the author surface | minor (0.6.0), listed under **Breaking** |

1.0 is the point where breaking changes stop being routine; it is not scheduled.

**Before releasing:** nothing left on a branch, a worktree or a stash; every CHANGELOG entry checked against its code, its test, the Guia and the design docs, with a probe at the last tag for each "before" claim ([Testing Design — RA](Testing%20Design.md#ra--080-release-audit-2026-10-11)); the Guia, tutorials, `examples/` and README read for the changed spellings; `python tools/guide/validate_guia.py --examples`, `python tools/guide/make_guia_thumbs.py --check`, `python tools/readme/make_readme_media.py --check` and `python tools/release/make_examples_zip.py --check` clean.

**Releasing:** rename `## Unreleased (X.Y.Z)` in the CHANGELOG to `## X.Y.Z — YYYY-MM-DD`, set `__version__`, run the `gate` tier, commit, then `git tag vX.Y.Z && git push origin main vX.Y.Z`. The tag starts `.github/workflows/release.yml`: it refuses a tag that disagrees with `_version.py` or has no dated changelog section, builds, runs `twine check`, and publishes to PyPI through Trusted Publishing (no token; configured on pypi.org for this workflow and the `pypi` environment). After PyPI, its `examples` job creates the tag's GitHub Release with `scena-examples.zip` (the README's examples download; [README.md, "Editing the README"](README.md#editing-the-readme)); a failure there leaves PyPI as is, and the zip can be attached by hand. A published version cannot be uploaded again: a bad release is fixed by the next patch.

**Rules for a breaking change:**

- **Loud, never silent.** A renamed or removed name, keyword, or field raises with the new spelling in the message — the existing pattern (`_RETIRED_ATTRS` on Sprite, `hitbox._RETIRED_KNOBS`, the `group("name")` migration `TypeError`; a retired top-level name answers `stage.<old>` / `from scena import <old>` with a raising stub through the module `__getattr__` — `act.RETIRED_NAMES` for the 0.6.0 Act rename, `shapes.RETIRED_NAMES` for `EquilateralTriangle` → `Triangle` in 0.9.0, merged in `scena/__init__.py` — star-import code gets a plain `NameError`). The old spelling does **not** keep working as an alias: [Fences.md](Fences.md) still allows one spelling, and the retired-name error is the migration path. Keep that error at least until 1.0.
- **Same spelling, new meaning is the most expensive kind.** Old code keeps running and does something else, with nothing to tell the author. Prefer a new name (and retire the old one loudly); if the meaning must change in place, the case for it has to be strong and the changelog entry says exactly what behaves differently.
- **Level files** keep loading: a format change bumps the file's `version` and the loader reads the older versions. A rename of the `format` tag alone is not a format change: the loader reads the old tag too and the version stays (`level_format.LEGACY_FORMATS`: `"stage-level"`, from before the 0.6.0 rename to Scena; the editor writes the new tag).
- **A package rename** (Stage → Scena, 0.6.0) has no alias package: a `stage` shim would hide the unrelated `stage` on PyPI. The old import fails with `ModuleNotFoundError`, and the CHANGELOG gives the fix (`from scena import *`; `pip uninstall stage`). Names the code keeps for old data or old installs say so (`level_format.LEGACY_FORMATS`, `shortcut.LEGACY_APP_NAME`); `test_message_vocabulary.TestNoStageBrand` keeps the old brand from coming back.
- **In the same change:** update the Guia, `docs/pt/tutorial/`, and `examples/`; add the changelog entry (before → after, and the error the old spelling now raises); test that the old spelling raises with the fix.
- **A bug fix is not a breaking change**, even if someone relied on the bug. If authors could plausibly have relied on it, say so in the changelog under **Fixed**.

See also [Guia da API](../docs/pt/guide/index.html) and this file for the current surface and architecture.

## Product principles

The framework idea is to use gradual params: the most basic call should produce something. E.g. `Circle()` produces a valid visible circle. `Gradient` produces a usable ramp from only the color, but also allows finer control (from/to, angle, linear/radial, etc). Initial usage stays easy. Shape stroke default is `line_width=1.5`; assigning `visual = Gradient(…)` (or `set_color` / `Paint` with a Gradient) also adds a darker mean-stop outline without changing width. For multi-model shapes, gradual means **empty**, **`center=` only**, or a **complete** constructor (including home-minus-center size: `Circle(radius=)`, `Rect(width=, height=)`); partial pairs like `Rect(width=40)` or `Line(p1=…)` raise. **Unknown** or wrong-family keywords raise `TypeError` (with a family hint when possible). Missing image / atlas assets stay legal (checker + warn).

It’s a beginner framework, so little or no boilerplate in the API is fundamental.

Scena philosophy is gradual parameters and low-to-none boilerplate, balanced with another principle: **the framework should not create in place of the author**. That’s why, for example, backgrounds insist on composition (instead of inventing a full sky with sun, clouds, mountains from no parameters). If an author requests a `Circle`, the framework provides a standard circle — a basic element; it only fills unspecified style. High-level control (`@collide`, `@when`, formulas, and so on) is a kind of DSL, but still programming. The framework must not invent the scene. Authors should feel they are programming and creating. The two principles pull apart only when sugar hides authorship. Defaults on a primitive, helpers, geometry, animations, and a pre-built effects library are fine; inventing a scene is not. Think of Scena as a high-level language for describing a game or visual scene — the author still describes it. The language provided by Scena should be very expressive, but not magical. No hidden cleverness — no behavior the author didn't ask for.

Taught samples live in top-level `examples/` (beginner games and scenes). Their art and
sound is `examples/media/`: tracked packs, one license file per folder, credited in
`examples/media/CREDITS.md` (guards: `tests/test_media_licenses.py`; every media path in
examples, smoke, bench and tutorial resolves: `tests/test_media_refs.py`). Tests take real
media from there through `tests/media_support.py`, never a skip-if-missing. Other scripts
are organized by audience: `scripts/smoke/` (visual proof), `scripts/bench/` (performance +
soak), `scripts/tools/`. They are not, as a set, representative
of what author code should look like — `examples/` is. `examples/app_galaga.py`
**is** the taught beginner fleet sample (one Director, one volley timer, per-wasp
dive/death). API shape and idiomatic Scena otherwise remain open to discussion, under [the criteria above](#design-documents-are-descriptions-not-locks).

Considerations:

- This machine is ~3–8× faster than the target machine (let's use 4x as param for calculations), so timing here is not the arbiter.
- We don’t know which games will be made. This is a framework, not an engine tuned only for the samples we already have.
- Scope is games / creative coding with on the order of tens to hundreds of screen objects — not 500+.

We accept a tradeoff: keep simple 2D games simple and straightforward, even if that means less power for very complex titles.

This is a framework for beginner authors. The framework's goal is learning (teaching programming), not professional, optimization-focused, machine-centered practice. Writing performant code shouldn't be a priority for the author, who already has plenty of concepts to learn and master. So the more the framework can handle good performance automatically, the better.

Principles:

- Simple things should be really simple.
- No boilerplate.
- Gradual parameters. 
- But the framework should not create in place of the author. The framework shall provide high level very expressive vocabulary, but not magical (no behavior the author didn't ask for). The author can ask for an animation, for a event trigger, etc, and the framework will handle every detail of it (animation over time, releasing resources, etc). But the framework will not create things the author didn't ask for.
- Expressive DSL. Authors can create, combine, remix. But concepts are simple to understand.
- Simplicity is king. Keep it simple.
- No suprises. Framework does what code look like it does. No need to read a manual about semantics, special rules. If code looks like it will do A, author will expect A, so framework should do A.

# Subsystems

Scena is several cooperating parts. They meet on the **Entity** (registry citizen) and on
the **frame** (see [Datapath](#datapath)).


| Subsystem | Job |
| --- | --- |
| **Run loop** | `ScenaFramework`: clock, input poll, user `update(dt)`, process tick, collision, `flush`, draw. Design space (y-up) maps to the OS window (`window_scale`, `canvas.display`, letterbox in maximized/fullscreen). Product defaults: system HUD off; FX Auto on (`high` @ 60 fps). |
| **Reactive core** | `Container` / `Attribute`, ownership tree + dependency graph, pull recompute, `@when` / `@on_change` on `flush`. |
| **Canvas** | Registry, layers, camera, wallpaper / background fields, cull, draw walk. |
| **Entities** | Identity, groups/tags, layer, visible, destroy, process host, ink, `active`. |
| **Graphics** | `Graphic` → `Shape` (geometry) / `Sprite` (image body). Pose, filters, transients, `.visual`, appearance stamps (`.glow` / `.shadow` / `.hue` / `.gray` / `.tail`). Sprite `.blend` / `.alpha` bake into the body blit at set-time (plain-blit eligible). |
| **Collision** | Shared enroll → proxy AABB → exact on overlap → handlers in the flush window. |
| **Leave playfield** | Opt-in `@leave_playfield` + world-fixed `canvas.playfield`; center vs AABB after collision. `playfield.set(box)` follows the view in one explicit line. |
| **Endless fill** | `Endless(layer, pieces, step=)` builds author pieces per slot near `layer.view` and destroys them far behind; per-slot seeded `slot.rng`; read-only on the camera. [Canvas Design.md — Endless fill](Canvas%20Design.md#endless-fill). |
| **Placement** | Measuring `Box` / `Grid`; `canvas.game_view` / `ui_view`; `box=` on frame-like Graphics; `graphic.box` / `group[...].box`; `Graphic.confine`. |
| **Level files** | `Level` reads a level file made by the level editor (companion app `scena_editor/`); creates nothing. `item.make()` builds the shape as drawn; `item.box` is the region. An image item is a whole picture or a frame of a spritesheet (`level.sheet(name)`). |
| **Scheduler / events** | Cooperative process (`after` / `every` / modes / tweens); formula-driven `@when` / `@on_change`. Author cancel of owned work is per-Entity `cancel_process()` (not a global reset). |
| **Effects** | Looks, shape transients, SpatialFx, backgrounds, canvas post, quality. Orthogonal to the graph unless the author links Attributes into paint or domain pose. |
| **Input / widgets** | `keyp` / `mouse` / `clock`; widgets + HUD `Text` share a view-space column (immune to camera). |
| **Audio** | `play_sound` / `Sound` / `audio` bus; numpy mixer + miniaudio device; analysis; optional `Microphone` (monitor, dry `record` / `stop`) + named FX catalog. Same `Handle` as `after`. OS default input and output. |

**How they fit.** Construction registers most kinds (materials do not).
An `Entity` may host processes and enroll in collision. A `Graphic` draws in a layer
under the camera. Writes during `update` / process tick store immediately; pure
derived data pulls fresh on read; effect handlers wait for `flush`. Draw ticks
transients and SpatialFx, then paints background → scene → post → widgets → cover.

```
                    ┌──────────── run loop ────────────┐
  input/clock ──► update(dt) ──► process ──► collision ──► bounds ──► flush ──► draw
                       │              │            │          │        │        │
                       ▼              ▼            ▼          ▼        ▼        ▼
                 reactive writes   scheduler   proxy AABB   leave    @when    scene + FX
                 (pull later)      handles     + narrow     playfield  @collide
```


# Data model

## Class tree (selected)

```
Container
  ├── Box                 measuring region (inset / outset / grid / beside / strip). Not an Entity; does not draw
  └── Entity              identity, groups/tags, layer, visible, destroy,
                          process host, ink, active
        ├── Graphic       pose, filters, transients, .visual, stamps   (ABC, not constructed)
        │     ├── Shape   geometric models, path, handles
        │     ├── Sprite  sheet, frames, play, image body
        │     │     └── Svg  SVG body (markup or file; still; private sheet)
        │     └── Text    HUD / world caption (anchor `top_left=`/`top_center=`/`top_right=`, or `center=` pose)
        ├── SpatialFx     no Graphic; full process surface still (timed Rain)
        └── UIWidget      HUD control; WidgetManager draws it (not a registry layer)
```

**Entity is the registry citizen.** `Shape` and `Sprite` are entities that draw. Bare
`Entity()` is legal (`layer=None`) — directors, spawners. `SpatialFx` is an Entity
ambient emitter (domain pose + tick/draw); it does not grow HP / hitbox / look APIs.
`UIWidget` is an Entity with no pose: `group` / `visible` / `destroy` / timers.
`layer=` and `collidable=True` raise. `visible=False` also turns off widget input;
`enabled=False` keeps it drawn (faded) but inert (Menu refuses `enabled`).

| Check | Meaning |
| --- | --- |
| `isinstance(x, Entity)` | Registry citizen (Circle, Sprite, SpatialFx, UIWidget, bare Entity) |
| `isinstance(x, Graphic)` | Can flash, glow, tween pose (Shape, Sprite, Text) |
| `isinstance(x, Shape)` | **False** for Sprite / Svg / Text |
| `isinstance(x, Sprite)` | **True** for Svg |

## Selected classes


| Class | Role |
| --- | --- |
| **Container** | Tree node: ownership, takein, formulas, graph participation |
| **Box** | Measuring region (`inset` / `outset` / `grid` / `beside` / `strip`); shares Rect geometry; not a Shape / Entity |
| **Grid** | Division of a Box into cells (accessor, not a Container) |
| **Attribute** | Leaf value cell (scalar / typed payload) — or bracket/`FieldRef` link surface after the bare-leaf redesign; see [Reactive Design.md](Reactive%20Design.md) |
| **Entity** | Registry citizen: layer, groups, process, ink, soft/hard remove. No author ids: the variable is the handle, `group["tag"]` the lookup ([Actors](Actors%20Design.md#no-author-ids)) |
| **Graphic** | Internal ABC: pose body, filters, transients, `.visual`, stamps |
| **Shape** | Geometry + PaintState; Defining / Derivate parts (`Track` is a Shape) |
| **Sprite** | Image body / Sheet (`clip` / `strip`) / play / hitbox specs / hitbox parts |
| **Hitbox** | Every collider a Graphic answers with. `g.hitbox` is the main one (stands, `resolve()`); `sprite.add_hitbox` adds detection-only parts that answer for the groups they claim and never resolve. Same knobs on all: `shape` / `source` / `anchor` / `scale` / `active` / `box`. Not an Entity |
| **Svg** | Sprite subclass: SVG source (markup or filename) → private raster; `.svg` replaces body |
| **Text** | HUD / world caption Graphic placed by one point (`top_left=` / `top_center=` / `top_right=` grow away from it; `center=` / `box=` grow around it); shares the widget column on layer `ui` |
| **SpatialFx** | Soft-domain ambient emitter on world layers |
| **ScenaSystem** | Global facade: register, edges, frame batch, flush |
| **DependencyGraph** / **UpdateManager** | Edges + dirty cone; pending effects |
| **Registry** / **Layer** | Live roster, groups, draw lists, camera response |
| **GroupOperator** | Named-group view (`group["wasp"]`); formula `@=`; join-order walks; queries (`.index`, `.first` / `.last`, `nearest`, …) / bulk. Not a process owner — [Actors Design.md](Actors%20Design.md#fleet-helpers-groups) |
| **Canvas** | Design size, camera (instant + timed pose suite), background, layers, post stack |
| **Handle** | Process timer / tween / awaitable / **playing sound** / **task** (`run_task`; `await` returns its value); `.elapsed` / `.remaining` (read-only); translation motion also `.velocity` / `.speed` / `.heading`; sound also `.volume` / `.pan` / `.pitch` / `.level` |
| **Sound** | Audio material (path, defaults). Does not play. Interned decode / stream heuristic. A recording is a `Sound` still being made until the take ends |
| **Microphone** | Explicit capture opt-in; `.level` / `.spectrum`; `play_sound(mic)` monitors; `record` / `stop` keep a dry clip. OS default input |

Not listed here: Shape subclasses, effect kinds, widgets — see companion docs / API.

## Two graphs

| Graph | Edges | Role |
| --- | --- | --- |
| **Ownership tree** | `owner` / `parts` | Composition and naming (`line1.p1.x`) |
| **Dependency graph** | structural + formula | Computation order; dirty / pull |

Identity is **stable**: assignment and formula results `takein` into existing Containers;
they do not replace instances that others point at.

## Values vs links

```python
point1.x = 10                    # copy now
point1["x"] @= c1["radius"]      # live link (DirectLink via FieldRef)
point1["x"] @= (lambda: c1.radius)  # same, as FormulaLink
```

`=` copies. `@=` installs a formula edge. Writing a linked field raises until
`unlink`. A `FormulaLink` must name at least one Container source (geometry,
ink, `State` cell, `Attribute`, or input Container — including default-arg
captures and simple `items[i]` subscripts); otherwise `@=` raises
`TypeError` — it does not freeze silently. A bracket `FieldRef`
(`c1["radius"]`) is also a valid DirectLink RHS. Bare floats (`c1.radius`) are
not — Python evaluates them before `@=` sees them. Details: [Reactive Design.md — What may be linked](Reactive%20Design.md#what-may-be-linked-sources-and-targets). Author surface: [Guia — O que pode ser ligado](../docs/pt/guide/index.html#reativo-fontes).

### Entity ink vs `st`

| Surface | Create on write/link | Typo guard |
|---------|----------------------|------------|
| `st.key = …` / `st["key"] @=` | `=` and bracket `@=` create the cell (default `0`) | reserved names raise; a read of a missing cell raises with a did-you-mean |
| `ship.field = …` | yes (ink field) | read raises if missing; a new name one edit from a real property raises (`rotaton`, `visable`, `colour`), and so does one adjacent swap of a 5+ letter property (`anlge`, `widht`, `lyaer`), or one edit from `color` / `fill` / `line` holding a colour or from `alpha` / `angle` / `scale` / `width` holding a number (`colr = "red"`, `angl = 45`; the value rule, [Actors — Ink](Actors%20Design.md#ink)); a method name (`c.tag = …`), a read-only property (`is_alive`, `box`) and, on a Graphic, a size word, point or relation the kind lacks (`circle.width`, `text.size`, `circle.top_left`, `rect.fp1`, `circle.dist`: `_SIZE_WORDS` / `_POINT_WORDS` / `_RELATION_WORDS`) raise with a hint (route table, graphics review R8). Generic words an author may use for a field of their own (`x`, `u`, `text`, `begin`, `end`, `cursor`) are not reserved |
| `ship["field"] @= …` | yes (same as `=`) | read raises if missing; a new name one edit from a real property raises, same as `=` |
| `ship.field @= …` | field must exist (Python reads first) | use bracket `ship["field"] @= …` |
| `ship.field = lambda: …` | never — raises `CallableAssignError` naming `ship["field"] @=` | — |

Entity ink: **writes and bracket `@=` may create**; **reads** fail on unknown names.
Both surfaces **read the value** (`ship.hp`, `st.score`: `st.mic is None` works) and
name the field with brackets (`ship["hp"]`, `st["score"]`): the handle that links,
binds (`Slider(st["volume"])`, `Text(st["score"])`) and watches (`@on_change(st["wave"])`).
`st` read the cell itself before 0.8.0 ([Reactive Design — State bag](Reactive%20Design.md#state-bag)).
**Inside a lambda, the dot**: the lambda keeps its reads live, so a bracket there is a
handle used as a value and raises with the dot spelling (at link time for a formula, at
registration for an event lambda, and on any value use of the handle: `bool`, `+`, an
f-string). A widget binds the cell (it edits it); `Text(st["score"])` links one way, so
a write to its text raises naming the cell ([Reactive Design — The handle is not the value](Reactive%20Design.md#the-handle-is-not-the-value)).
Creation has a near-miss guard (once per class and name) and look properties
that belong to another actor kind (`circle.alpha`, `text.alpha`) raise instead of
landing in a dead attribute. `enable` / `enabled` are explicit aliases of
`.active` (park / unpark): not one edit from `active`, and not reserved names
(a reserved name with no property would store a plain attribute nothing reads).
See [Actors Design.md](Actors%20Design.md#ink).

**Every other author object is a closed surface.** Only Entity (ink) and `st`
(cells) create names on write. Effects (`Bloom`, backgrounds, audio effects,
non-interned looks and filters, `canvas.effects`, `canvas.background`), the
global objects (`canvas`, `ui`, `audio`, `clock`, `mouse`, `keyp`, `collision`,
`ready`, `recently`, `canvas.playfield`, layers) and values / materials (`Vec2`,
`Box`, `Grid`, `Color`, `Palette`, `Colormap`, `Gradient`, `Texture`, `Sheet`,
`History`, `Level`, `Sound`, `st` cells) accept writes only to names they
already have: `bloom.itnensity = 2` raises `AttributeError: Bloom has no
'itnensity'. Did you mean 'intensity'? Writable on Bloom: …`. Before, each such
write stored a dead attribute and nothing happened. One helper,
`scena/closed.py` (`ClosedSurface`, `seal_after_init`), does it: any write
passes until the outermost constructor returns (so a subclass `__init__` may
create fields), then a public name must be in the instance `__dict__` or be a
class property / descriptor / non-callable default. Engine-built values
(`CollisionInfo`, `ContainerSet`) are slotted instead. **Open on purpose:**
Entity and its subclasses (ink), `st`, `group[...]` (broadcasts to Entities)
and `ColorNames` (never instantiated). A closed `__setattr__` is a Python call
on every write, private ones included, so a hot class closes only when its
construction makes no such call: `Vec2` (the hottest value class) fills its
fields through `__dict__` and seals with a `__dict__` mark, so `v + w` costs
what the open Vec2 did and only a direct `v.x = 5` pays ~100 ns (Reactive
Design, Vec2). The class-wide guard is `tests/test_closed_surfaces.py`
(Testing Design family CS).

**Paint / appearance is not ink.** Costume channels (`.visual`, `.fill`, `.line`,
`.line_width`, filters, `.glow`, `.shadow`, …) are plain properties on
`Graphic` — they do not enter the dependency graph. Bracket `@=` and
`field = lambda: …` on those names raise with a hint to use `=` plus
`on_update` / `@on_change` / `@when` when looks should follow game state.
**`.vel` is not linkable either**: the engine writes it (`resolve(bounce=)`,
`confine(action="bounce")`) and so does the taught `vel.y -= g * dt`, so a link
would make those raise far from the `@=` line. `ship.vel @= f`,
`ship.vel["x"] @= f` and `ship["vel"] @= f` raise the same message, naming
`ship.vel = …` in `on_update`. `ship.vel @= f` runs the owned Vec2's
`__imatmul__` before the setter, so the refusal lives on the part
(`_link_refused`, checked in `state._refuse_link_on_dead`), not in the setter —
an early return there would have installed the link.
Custom ink (`ship.hp`) and geometry slots (`rect.width`, `line.p1.x`, `shape["angle"]`,
`shape["scale"]`) remain linkable. **The heading is `angle` on every Graphic** — a field:
setting it (`=`, `@=`, the constructor keyword, a `tween`) keeps the point the actor was
placed by, like `width`; the verbs `rotate_to` / `rotate_by` turn the whole actor about its
center (or `about=`). Where `angle` is a model input (Rect / Ellipse / Square / Concave /
RegularPolygon / Triangle / Line / Circle) it is a plain geometry `ScalarSlot`;
on Point / Sprite / Svg / Text / Track / free Polygon and derived headings it is
property-backed (`_PropertyAnchor` → `rotate_to`), as `scale` is on every Graphic (→
`scale_to`). `rotation` is retired on Graphics: every spelling raises with a hint
(`Graphic._RETIRED_ATTRS`); `canvas.rotation` stays the camera's turn.
[Shapes Design — Geometry contract](Shapes%20Design.md#geometry-contract).
Detail: [Reactive Design.md — Appearance](Reactive%20Design.md#appearance-paintstate-internal).

**Groups participate in `=` / `@=` outside the Container graph.**
`group["enemies"] @= lambda: group["wasp"] | group["boss"]` names a live derived
group (recompute-on-read on `GroupOperator`, not an Attribute edge). Plain
`alive = group["a"] | group["b"]` stays a snapshot. See [Actors Design.md — Formula groups](Actors%20Design.md#formula-groups).

## Numbers and signs

Coordinates, vectors, offsets, and angles keep their sign: the sign is the opposite direction. Sizes (`radius`, `width`, `height`, `length`, `line_width`, margins, `scale`, camera `zoom`) are magnitudes. A negative value you write raises `ValueError`. A negative value from a formula (`@=`) or a tween reads as 0. NaN and inf always raise. Zero is a legal collapsed size, except Text wrap `width`, `Gradient(size=)`, collision `mass`, and a timed verb's `speed=` (a rate: zero would never arrive), which must be greater than 0.

A value that is not a number (`"big"`, `None`, a tuple where a scalar goes, an object) raises `TypeError` naming the parameter — on every constructor knob (shapes, SpatialFx, post, backgrounds, audio, looks, filters, widgets), every `ScalarSlot` write (`rect.rotation = "x"`), every verb (`rotate_by`, `canvas.shake`, `ready`), every duration (`after`, `every`, `wait`, `time=`, transient `duration` — `validate.seconds`; a function is not a duration), every rate (`speed=` on the timed pose verbs — `validate.fixed_magnitude`, `positive=True`), and `volume` (≥ 0). `bool` is never a number. A number is finite: NaN, inf and an int too big for a float (`10**400`) raise `ValueError` (`validate.finite` bounds its exact-int fast path; so do the plain slots and `_finite_deg`). A point is two finite numbers, and so is a vector: every door of a `Vec2` (constructor, axis writes, `+=` / `-=` / `do_rotation`, `<<`, a link's pull) refuses NaN / inf, a free one included (VB4, 2026-10-17). The point readers (`_xy_of`, `get_xy`, `_read_xy`) refuse `(nan, 0)` wherever a point enters — `center =`, `move_to`, `about=`, `contains_point`, a formula's tuple (graphics review SA6; guard `tests/test_value_validation.py`, which walks every setter of every export by the value it reads). A function is a live formula only where the knob is reactive (a declared field such as a pad's `width`, or a knob the class lists): `Rain(width=lambda: r.width)` links, `Bloom(intensity=lambda: 1)` raises (`validate.formula_knobs`). A pair knob (`offset`, `scroll`, `radius=(rx, ry)`) takes two numbers; a dict is not a pair. Method arguments follow the same rule (`set_alpha`, `lighter`, `Track.at(u)`, `Vec2.dot`, `Box.inset`): a Vec2 operand also takes an `(x, y)` pair; a grid index takes a whole number (`2` or `2.0`, not `1.7`); a sample count is ≤ 1,000,000. List- and dict-like objects keep Python's container contract: `History.pop()` on empty raises `IndexError`, `State.remove("missing")` raises `KeyError`, each with a sentence. Flags (`visible`, `flip_x`, `set_fx_auto`, every constructor knob that defaults to `True` / `False` such as a background's `enabled`, and method flags: `force=` on every pose verb, `play(resume=)`, `clip(yoyo=)`) take a real bool (or 0/1), not `"no"` or `None` — `force="no"` unlinked (GR11). A flag never goes through `bool()`. Probabilities are `[0, 1]`: `chance(30)` raises with a percent hint.

These checks run on every call, including per-frame verbs (`move_by`, `angle =`), so each validator tests `type(v) is float` / `int` first and only takes the general path (formula probe, Attribute payload, `numbers.Real`) for anything else — same results, a fraction of the cost (`tests/test_hot_validators.py`).

A pose verb with no target at all (`move_to(None)`, `move_to()`, `move_by(None)`, `move_by()`) raises `TypeError` — usually a location that turned out missing; one `None` axis is a per-axis move (`move_to(None, 5)` keeps x), and `time=None` means instant.

If the direction is in the name (`inset`, `outset`, `beside(side=)`, `strip(side=)`), the number is a magnitude. If it is not (`move_by`, `rotate_by`, `dist`, camera or playfield `pad`), the number is a signed delta.

`flip_x` / `flip_y` on every Graphic mirror about `center` — except Text, which cannot be mirrored (`True` raises `TypeError` with a hint to turn it instead; `False` is a no-op). `Rect(p1=, p2=)` and `Rect(p1=, vec=)` keep `p1` / `p2` / `vec` where you put them (a value or a lambda — the constructor does not rewrite a stored input). A rect (or Box) names its corners the first time one is used, as they look then; from then on each name (`bottom_left`, `top_center`, …) stays with its point through drags, links, rotations and flips ([Shapes Design — Named points](Shapes%20Design.md#named-points)). Amounts in `[0, 1]` (alpha, `Track.begin` / `end`) are clamped; that is the only silent change of a value you write. A colour name is read the same with or without spaces, case or hyphens, and so are its `dark` / `light` / `faded` prefixes (`"lightcyan"` is `"light cyan"`, as `"deepskyblue"` is `"deep sky blue"`; a table name wins over peeling a prefix); a near typo resolves to the closest name with a warning whose suggestion keeps the prefix (`"lightcyna"` → `light cyan`). An unknown colour name, and a malformed hex string (`"#"`, `"#000:00"`), warns and falls back to magenta (including FX and look constructors) — the result is visibly wrong, and the warning is the signal. `chase` rate and `approach` speed are magnitudes (`< 0` raises); a zero rate / speed and `dt == 0` stay still; `dt < 0` raises.

## Public means author-facing

On a class or object exported by `scena.__all__`, a name without a leading underscore is author API: the Guia spells it, or `tests/test_api_surface.py` lists it in `SURFACE_NOT_IN_GUIA` with a reason (bench knobs such as `canvas.shape_fx_scale`). Engine hooks — look `_apply(host)` / `_batch_key`, post `_draw_shader` / `_fx_cache_key`, background `_advance_scroll`, SpatialFx `_domain_aabb` / `_sample_pad`, audio-fx `_process`, widget state `_has_focus` / `_pressed` — are underscored, including the class defaults that keep them off the ink bag. **Docstrings are the hover docs** (English; the Guia is the PT-BR reference): every export, every public member of an exported class or reachable object, and every public parameter has text — a one-line summary, optional prose, then `Args:` (`Attributes:` for engine-built records such as `CollisionInfo`) naming each parameter in signature order. Refusal stubs say what to write instead. `test_api_docs.TestEverythingHasHoverDocs` enforces it. `test_api_surface` walks every exported class, constructible instance, and object, **and the objects reached through them** (`canvas.layers["far"]`, `canvas.effects`, `canvas.background`, `canvas.playfield`, a Handle, `group["x"]`, `shape.group`), so a new public hook fails there, and the fuzzer (`test_hyp_surface`) treats only these names as author verbs. The Guia word bag is not enough on its own: `render`, `tick` and `step` are ordinary Guia words, so the walk also refuses engine vocabulary outright (`HOOK_WORDS`: draw-walk `_render`, frame `_tick`, `_skia_shader` / `_skia_filter`, `_replaces_sprite_body`, post-stack `_hit_feedback` / `_invalidate` / `_release_surfaces`, Layer `_objects` / `_append_object` / `_compact` …; widget dispatch is `_on_mouse_*` / `_on_key*` / `_on_char`, and the input feeds are `keyp._press` / `keyp._release` — `mouse.press(button)` stays the author's query), and checks looks / post effects / background fields / audio effects / filters against their **own** family's Guia sections.

## Debug tooling

Engine probes are not on `scena.__all__`. Import them from `scena.debug`: `set_leak_detector`, `set_sync_watchdog`, `set_extrude_focus`, `get_extrude_focus`, `set_metal_light`, `get_metal_light`. They stay importable from the modules that define them. `scripts/bench/perf_guards.py` times a `ScalarSlot` write and a `keyp()` lookup so a new guard can be compared against that row.

## Defining vs Derivate

Multi-model shapes mark parts **Defining** (inputs) or **Derivate** (outputs of
`_update_impl`, demand-driven). Cold Derivates stay cheap; linking or reading one
makes it live. Geometry detail: [Shapes Design.md](Shapes%20Design.md).

## Construct-to-place

Construction attaches by family and returns the instance: shapes, sprites, SpatialFx,
widgets, post effects, background fields. **Materials do not place** (`Gradient`,
`Color`, `Palette`, `Blur`, `Neon`, `Sheet`, …) — assign them onto something that does.
`Palette` / `Colormap` only hand back `Color` values (they do not paint). There is no `id=` (it raises `TypeError` pointing at `group=`). A constructor that raises leaves nothing behind (`Registry.register` resolves the layer before claiming anything; `Entity.__init_subclass__` wraps each subclass `__init__` to roll back a later raise). The rollback is the real teardown (`Registry._destroy_teardown`, without `on_destroy`): a Collider, timers, watches and parts made before the raise leave too. It also covers the finish step (`setup()`, method `@every` / `@after` / `@when`, group enrollment), so a `setup()` that raises leaves no live actor ticking. A subclass whose `__init__` comes from a mixin (`class Enemy(Damageable, Circle)`) is wrapped the same way, so its `setup()` and hooks run and a raise rolls back (graphics review E4 / E5; guard `tests/test_construct_failure.py`). `destroy()` is idempotent, and roster keys are never reused, so a second call cannot touch a later actor. A shape's Point parts (`center`, `p1`, vertices, shown handles) leave with it: off every layer, pointer list, group and the roster; they then read and refuse writes like any destroyed actor. A part is not an actor: tags, collision (`collidable`, `@collide`, `resolve`, `on_collide`), `destroy()` and `active` on a part raise `TypeError` naming the owner; queries (`contains_point`, `test_collision`) accept it — [Actors](Actors%20Design.md#a-part-is-not-an-actor). A rejected `layer=` keeps the previous layer. The Python name you still hold is not freed. `if actor:` is `is_alive` (false after `destroy()`). Pose reads (`.center`) stay, and so do ink reads (the own fields as they were at the destroy: a plain copy, `_dead_ink`, since 2026-10-20, persona probes R3-1: a second handler of the contact, C3, reads the dead body); a name it never had raises `DestroyedError`, and every write refuses. An instant change (`move_by` / `move_to` / `rotate_*` / `scale_*` without `time=`, `confine`, `visible`, `collidable`, `play`, `set_color`, `layer`, `tag`, `mode = fn`, `dead.radius =`) raises `DestroyedError` naming where `destroy()` ran and the guard `if nave:`. `active = True` on a dead actor stays a no-op. Scheduling (`after`, `every`, `tween`, timed pose, `move_along`, `play_sound`, transients, `on_update`) does nothing — a cancelled Handle, never registered. `resolve_now`, `absorb`, `add_hitbox`, `remove_hitbox`, `show_handles` / `show_points`, a new `reversed()` view, and building a shape from a dead source (`Line(circle=dead)`, `Ellipse(from_rect=dead)`) raise `DestroyedError`. A dead actor is falsy, so engine code tests an Entity-or-None slot with `is not None`, never `x or fallback`.


# Datapath

## Frame order

Canonical order inside `run()` — one frame body, `ScenaFramework._simulate_frame`
(steps 1–7; headless drivers and `tests/system_support.py` call the same method),
then `_draw_frame` (8):

1. `clock._tick`, then layer scroll (`advance_layer_scroll`: world state, integrated here so `update` and `layer.view` see this frame's offset; draw only reads it — [Canvas Design.md — Parallax layers](Canvas%20Design.md#parallax-layers-decoration-only)), then input (poll events; **sample** world pointer; keys/buttons via callbacks; mouse moves only *record* the pointer), then the audio levels a formula links (`sample_level_sources`, only when one is linked — [Sound Design.md — Levels as formula sources](Sound%20Design.md#levels-as-formula-sources))  
2. User script `update(dt)`  
3. Process tick, in this order: tweens, due timers (`every`, then `after` / `wait`), awaits (`until` / `parallel` / `race`), sound-finished poll, task steps (async resume), `on_update`. Tweens come first since R4-1 (Laws T1), so a timer as long as a tween sees it finished.  
4. Collision  
5. Leave playfield (`@leave_playfield`; after collision, before flush), then **hover** (`step_hover`: one hover target, `@hover` / `@hover_exit` edges — [Shapes Design.md — Hover](Shapes%20Design.md#hover-pointer_hover-hover--hover_exit))  
6. `flush` `@when` / `@on_change` (collision pair and hover handlers already ran in steps 4–5)  
7. Transients  
8. Draw  
9. Pace + present (`pacer.wait_for_present` → swap; [Frame pacing and GC](#frame-pacing-and-gc))  

Linked appearance fields and flags (`rect["fill"] @=`, `visible`, `alpha`, … — [Reactive Design.md — Appearance links](Reactive%20Design.md#appearance-paintstate-internal)) are pulled at the head of the draw (`refresh_linked_channels`, before culling and look grouping), and `visible` also at the start of hover (step 5), so hover and clicks see a write made in update or a collision handler. Pulls where they are called, not a phase (Laws F2); parked and destroyed hosts are skipped. A linked flip is pose: pulled with `angle` / `scale` before collision, draw and hit-test.

`init()` has no OS window. `@=` formulas linked in the script body evaluate with
`mouse` at `(0, 0)` and `keyp` empty — honest: there is no pointer yet. When
`open_window()` runs, the engine **seeds level** from the OS (pointer position,
keys already down) without manufacturing edges (`mouse.dx`, `keyp.once`,
`on_mouse_move`). Linked consumers re-pull before `setup()` and first draw.
Each frame, after `poll_events`, world `mouse.x` / `.y` are sampled again so a
still cursor stays current if the camera moves, and once more after the process
tick when `update` or a timed camera verb moved the camera (W-P1). A **point-like** is a `Point`,
a `Vec2`, an `(x, y)` tuple, a Graphic (its `.center`), or `mouse`. A location
argument takes any of those (`move_to(mouse)`, `about=mouse`,
`Circle(center=lambda: mouse)`, `Contrail.snapshot(mouse)`,
`collision.query_point(mouse)`, `canvas.fireworks_at(ship)`). A bare value
snapshots; `lambda:` / `@=` follow. A **delta** (`move_by`, `pan_by`, Track
`vec=` / `vectors=`) rejects a location.

Graphics and SpatialFx have no `.x` / `.y`. That name would become ink the
actor never reads. Position is `.center` (`ship.center.x` to read;
`move_to` / `move_by` to move). `Point` still has real `.x` / `.y`. A bare
Entity still stores `e.x` as ink. `ship.center + (dx, dy)` is a new point
(placement, not motion). `ship.center += …` raises — use `move_by`.

**Modifier filter.** A bare play key (`keyp("RIGHT")`, `keyp.once("SPACE")`,
`in keyp`, and the `on_key_down` / `on_key` delivery) reads False while Ctrl,
Alt or Cmd is held — they make shortcuts — but **Shift does not block it**:
"hold Shift to run" keeps walking and jumping (bug PD6, 0.8.1; before, any
modifier hid it). So with Shift and R held, `keyp("R")` and `keyp("SHIFT+R")`
are both True; `keyp.only("R")` stays exclusive (no other physical key, Shift
included). A spec that lists a modifier is an exact chord: an unlisted family,
Shift included, makes it False, so `keyp("CMD+Z")` is not Cmd+Shift+Z.
`keyp.held` ignores every modifier. Shift going down under a held play key
does not latch its `once` (it is not a new press, and lifting it fires
nothing); Ctrl / Alt / Cmd still do (`KeyPressed._press`).

Key specs are validated on every query (`keyp`, `.once`, `.only`, `keyp.held`,
`in keyp`): a non-str raises `TypeError`; an unknown or empty name raises
`ValueError` with the Scena spelling (`"ESCAPE"` → `"ESC"`, `"RETURN"` →
`"ENTER"`, `"CONTROL"` → `"CTRL"`, `"OPTION"` → `"ALT"`, `"COMMAND"` /
`"SUPER"` / `"WIN"` / `"META"` → `"CMD"`, `"LALT"` → `"LEFT_ALT"`) or
did-you-mean. Each key has **one** name: no aliases, modifiers included. An
alias cannot hold on the `on_key` side — `KeyName` equal to `"ESCAPE"` but
hashing as `"ESC"` would break `in {…}` / dict lookup — and `"DELETE"` names
Backspace on a Mac keycap. New spellings go in `_KEY_SPELLINGS` (`input.py`)
as hints; `test_every_spelling_hint_*` checks each one points at a real,
deliverable key. Punctuation keys are **numbered by position**, `K1`–`K12`
in reading order (US caps `` ` - = [ ] \ ; ' ``, the ISO key left of Z,
`, . /`; table in the Guia, *Teclado*). A glyph or US word cannot be the
name: the cap differs per layout (ABNT2's `K7` is Ç), GLFW names keys by
their US position, and `+` is the chord separator. `"."` / `"PERIOD"` are
spelling hints that raise with `K11`. Row/column names (`R3C10`) were
rejected: they need the table anyway and invite a second spelling for
letters. `K9` is GLFW `WORLD_1` (macOS, X11) or `WORLD_2` (Windows). Known
limits of GLFW's codes: `K6` is one code for the key above Enter (ANSI) and
the key left of Enter (ISO); Apple ISO keyboards report the keys left of 1
and left of Z swapped (`K9` ↔ `K1`); ABNT2's `/?` key has no code. A key
Scena cannot name (numpad, Caps Lock, `KEY_UNKNOWN`) is dropped at the GLFW
callback — `get_glfw_key_name` returns `None`, never a raw code such as
`"46"` that no query could spell. Case is free and combos use `+` (`"ctrl+s"`); a
checked spec is cached, so the per-frame cost is one set lookup. That check
runs when the query runs — there is no scan of code that has not run yet.
`keyp["A"]` / `keyp.held["A"]` is not a query: a known name raises `TypeError`
telling the author to call `keyp("A")` or `keyp.once("A")`; an unknown name
still raises the query `ValueError`.
`on_key_down` / `on_key` / `on_key_up` receive a `KeyName` (`str` subclass, not
on `scena.__all__`). `==` / `!=` match `str` for every name those handlers can
deliver (`"A"`, `"SPACE"`, `"SHIFT"`). A name they cannot deliver raises
`ValueError` instead of comparing false: `"ESCAPE"` → `"ESC"`, `"space"` →
`"SPACE"`, `"LEFT_SHIFT"` / `"LSHIFT"` / `"LEFT_OPTION"` → the family
(`"SHIFT"` / `"ALT"`; `keyp("LEFT_SHIFT")` still queries that side),
`"CTRL+S"` → a chord is `keyp(...)`, anything else did-you-mean.
Widgets keep a plain `str`. Dict lookup and `key.lower()` are plain `str`
compares and do not raise. The loud compare is for the handler's argument,
not for data: a **field stores the key as a plain `str`** (`st` cell, `Text.text`,
an ink field, `Button.label`, `TextInput.text` — `Attribute._takein_impl`,
`Entity.__setattr__`, the ink `_write_field` path unwrap `state._KEY_NAME`).
Otherwise the write's own change check (`"x" != key`) raised, and so did a
later `st.nome != "nenhuma"` (IN2). A key nested in a tuple / list / dict is not
unwrapped (no deep scan per write); the compare raises `KeyNameMismatch`
(a `ValueError`, only when the strings differ), which `_value_changed` and
`Attribute` read as "changed". A new engine change check on author values
catches `KeyNameMismatch` the same way; a new field that stores author text
unwraps the key (`test_key_name_fields` sweeps every public `str` field).
A module global (`ultima = key`) keeps the `KeyName` — it is the author's
variable, not a field.
`mouse.press(button)` takes an int `0–7` (`Mouse.BTN_LEFT`); `"left"` raises
with that hint.

`glfw.poll_events()` can flush a
press **and** its matching release in one poll (a hitch while the previous
frame was busy). Bare `keyp()` stays a live level sample — already-up is
False. `keyp.once` / `keyp.held.once` latch that rising edge (`_pending_edges`)
so the press is still reported exactly once — in that frame only: the end of
the frame body drops unread edges (`KeyPressed._expire_edges`), so a late
first reader sees nothing (bug PM3). A latched chord counts only if
its keys were down together at that press (Cmd tap, then O tap, is not
`CMD+O`). `clock.mark_play_start()` after
`setup()` makes frame-1 `dt` a real step, not construct time. World `dt` is
clamped to `[0, MAX_FRAME_DT]` (0.25 s, `input.py`) before `scale`: a hitch
(breakpoint, window drag, GC) advances the world at most that much, so
`clock.time` can fall behind wall time; `real_dt` / `real_time` stay raw.
`clock.advance(dt)` (tests / drivers) is not capped. Unused input still
pays A2.

Writes during (2)–(3) store immediately. Pure derived reads are always current by
construction (pull). Effect handlers stay deferred until (6). The frame batch
stays open through (7): writes from the pre-draw ticks (an author transient /
cover `on_done`, SpatialFx) reach `@when` at the **next** frame's flush — no
eager poll per write, no second flush. Draw (8) samples the post path once and
applies background + camera after all of the above, so the scene, background
parallax and camera always show this frame's camera (no one-frame lag).

### Commands during a pass (the snapshot rule)

[Laws.md](Laws.md) F3. A command — `destroy`, park, `untag`, a group change,
`collidable`, `change_act`, a creation, a timer, a pose write — takes effect
for the author when it returns (L1): `brick.destroy(); if not bricks:
change_act(Win)` sees the brick gone. An engine pass already running (a
collision step, the timer buckets, the `on_update` fleet, a flush round, the
leave and hover checks, one OS input event) finishes against what it chose at
its start:

- **What it owed is paid.** Every handler of the contact being dispatched
  runs, chosen before the first one (C3); a resolve partner a handler removed
  still answers the survivor as a ghost (C8, PE5); an exit the command caused
  runs after that contact's handlers (C2); an input event delivers to the
  doors it chose before the command (an `on_key_down` that changes the act
  still gets the same press's `on_key`).
- **What was removed starts nothing.** A destroyed or parked body joins no
  other contact of the step (C4) and none of its own hooks runs later (L3, L4,
  T3); the per-item re-checks (alive, active, registered) are that rule.
- **What was made waits for its loop's next pass.** A timer made in the tick
  first counts in the next one (T2); a body made in a handler enters next
  step. A clone made in a timer fire gets its `on_update` this tick: the
  fleet's pass starts after the timers'. Flush is the one pass that runs to
  quiet: a watch a callback *affected* fires in the same flush, a watch it
  *made* takes its baseline at registration and waits for a change. An
  author's walk over a group (`for m in group["x"]`, bulk `destroy` / `tag`)
  copies its members at entry.
- **An act change cancels what the ending act owed**: its contact handlers
  (the dispatch's act epoch, S4-1), its exits (C6), its ghosts. The game's own
  pairs, timers and watches go on in the new world.

A command buffer (Unity, Bevy: apply at the end of the frame) was weighed and
rejected (2026-10-15). It would remove the bugs this rule took to converge
(PB3, PB5, PE5, S8-2: each fixed and guarded by a law), but it adds a state no
author expects, "condemned but still visible": `brick.destroy(); if not
bricks: change_act(Win)` would never fire, the classic deferred-destroy trap.
[Act Design — `change_act`](Act%20Design.md#change_act) rejected a deferred act
change for the same reason. The chaos doors (Testing Design, "Laws and
equations", S7) fire every command at every door and check this rule.

## Frame pacing and GC

Two things made "runs at 60 but judders now and then" (measured on macOS and a
Windows laptop: [longrun.md](../scripts/bench/longrun.md#findings-2026-09-29-the-fix-display-locked-pacing--gc-freeze)):
a free 60 Hz timer **beating** against the display refresh (bursts of doubled /
dropped frames every few seconds), and **gen-2 GC passes** (8–54 ms).

**Pacing** (`scena/pacing.py`, `FramePacer`). The loop is: simulate + draw →
`pacer.wait_for_present()` → `swap_buffers` → `pacer.presented()`.

The author picks the mode with **`canvas.framerate`** (string tokens, like
`canvas.display` / `canvas.fx_quality`; one spelling — there is no enum and no
`set_framerate`):

| `canvas.framerate` | Meaning | 60 Hz | 120 Hz | 144 Hz |
|---|---|---|---|---|
| `"vsync60"` (**default**; FX Auto's 60 rungs) | locked, vblank divisor nearest 60 (never below 50 Hz) | 60 | 60 | 72 |
| `"vsync30"` (FX Auto's 30 rungs: survival low@30, and high@30 / medium@30 for a sim-bound frame) | locked, twice that interval | 30 | 30 | 36 |
| `"vsync"` | locked, every vblank (full refresh) | 60 | 120 | 144 |
| `60`, `30`, any fps | fixed-rate timer | 60 | 60 | 60 |
| `"max"` | uncapped (benchmarks) | — | — | — |

Named by rate, not divisor, so a token means the same on every panel ("half"
would be 30 on 60 Hz but 60 on 120 Hz). Bad values raise before anything
changes (did-you-mean for tokens); assigning turns FX Auto off; while Auto is
on, the property reads the rung's token. Ctrl+Shift+4 cycles `"vsync"` →
`"vsync60"` → `"vsync30"` → `60` → `30` → `"max"`, with the real rate in the
HUD ("VSync 60 (72 Hz)"). A number is honoured as written — no silent switch
to a locked token — but it is a free clock: its phase against the display is
random per run and, now that it does not drift, can sit near the latch for a
long time (measured: 0 and 129 held frames/min in two 25 s runs of the same
scene). Teach the default.

| Mode | Strategy | How |
|---|---|---|
| `"vsync…"` tokens | `NATIVE` (Windows, Linux) | `swap_interval(n)`; the swap blocks. A self-check (first ~60 short frames) falls back to `TIMER` with one `SCENA` warning if the swap does not block (driver override). |
| | `DISPLAY_LINK` (macOS) | `swap_interval(0)` + a CoreVideo display link for the window's display (`_display_link.py`). Sleep until just after a vblank (+1 ms), then swap: the present sits a period away from the compositor latch. macOS GL `swap_interval` is unreliable (GLFW #1990 / #2249); SDL2 does the same. |
| a number | `TIMER` | Absolute schedule (`target += period`; resync after > 1 period late). Sleep, then spin only the last ~0.2–1 ms (adaptive). Windows + Python < 3.11 only: `timeBeginPeriod(1)` for the run. |
| `"max"` | `UNCAPPED` | no wait |

FX Auto rungs carry their token (`Rung.framerate`, `Rung.interval` on this
display); nothing below `"vsync30"` (an overloaded frame slips to a later
vblank). Locked pacing turns a late frame into a visible held frame, so FX
Auto reads two pacer signals after each present: **overruns**
(`FramePacer.last_overran`: the present missed its vblank because the frame did
not fit — a late wake of the pacer itself is excused; a sustained rate steps
down even when CPU work looks fine, and blocks climbs) and the **present
overhead** (`present_overhead()`), which makes its budget
`interval × period − overhead` instead of the full frame time. The loop also
passes the draw share of the work (`_draw_frame` + `flushAndSubmit`), so a
frame bound by game logic halves the rate at its fidelity instead of walking
fidelity down. It steps down only on a sustained problem and climbs back on a
predicted cost, slowly
([Effect System Design — FX Auto](Effect%20System%20Design.md)).

**World `dt` follows the display** when locked: an interval within 20 % of *k*
vblank periods becomes exactly *k* periods (`DtSmoother`); the difference is a
debt paid back only past ¼ period, so `clock.time` stays within a few ms of
wall time. `real_dt` / `real_time` stay raw; `MAX_FRAME_DT` still clamps.
Under `TIMER` / `UNCAPPED`, `dt` is raw.

**GC** (`scena/gc_policy.py`). `_begin_game` ends with `gc.collect();
gc.freeze()` (before the clock origin, so it is not a frame); an act change
thaws at its start and asks for one collect + freeze, which runs at the end of
`_simulate_frame` (one pause, in the transition frame: a collect inside the
handler that changed act froze the bodies its stack still held, review
2026-10-09 S4-7); `run()` cleanup thaws. Same on every Python
(3.14.5+ is generational again). **Cost:** Scena objects sit in reference
cycles, so a frozen object destroyed during play is reclaimed at the next
act change or exit. It was alive at the freeze, so memory is bounded by the
built world and never grows. `set_gc_freeze(False)` turns it off; headless
`SystemWorld` does (a frozen heap would hide real leaks from the census).
The same cycles mean a Container dropped during play leaves the reactive graph
only at a full collection; the leak detector therefore runs one `gc.collect()`
(play objects only, ~1 ms) before it warns, and only then
([Reactive Design — Deferred trees](Reactive%20Design.md#deferred-trees-measured-boxes)).

## Clocks

Three clocks feed the frame. **World time** (`clock.time` / `clock.dt`) is
scaled by `clock.scale`, stops while `clock.paused`, and a frame feeds it at
most `MAX_FRAME_DT` (0.25 s). **Presentation time** (`clock._ui_time`) is the
same capped step, unscaled: pause and slow motion do not stop it. **Wall
time** (`perf_counter`) is raw. A consumer reads one of them on purpose; a new
timed mechanism picks its row here and compares deadlines through
`process.reached`.

| Consumer | Clock | Why |
| --- | --- | --- |
| `update(dt)`, `after` / `every` / `tween` / timed verbs / modes / `move_along` | world | game time; `every` keeps its debt, so its rate is frame-rate independent (catch-up bounded by `MAX_FRAME_DT / interval` fires per tick) |
| `ready` / `recently`, History / Contrail, sprite playhead and `min_hold` | world | game time; `ready` carries its overshoot like `every` (a steady cadence at any fps; after a pause in polling it reopens one interval later, no burst: review 2026-10-09 W-T2; a gap of even one frame restarts the cadence at the True that ends it, so a release and a press one frame late carry no overshoot into the next held shot: PG-RD1). A self re-arming `after`, an `await wait(p)` loop or a chain of timed moves each started from the last one's `on_done` starts each period at the frame that noticed the last one: "at least `p` apart", not a rate; use `every` for a rate, `move_along` on a Track for a steady multi-step path (persona probes R5-8, R6-4) |
| SpatialFx tick and shader phases | world | world actors: pause freezes the rain; their own `after` already counted world seconds. A frame feeds them at most `MAX_FRAME_DT`, the world's cap, cut into steps of at most 0.1 s for the integrators; the first tick advances by the time since birth (W-T9) |
| Layer scroll (`advance_layer_scroll`, every non-neutral layer, hidden or not), background-field scroll (`BackgroundStack._advance_scroll_all`, every field, enabled or not) | world | scroll is world state; `visible` / `enabled` is paint; both count from birth (W-T7, W-T8) |
| Canvas cover (`fade_in` / `fade_out`), post `shake` / `flash` / `glitch` decay (`PostFxStack._render`), shape transients (`dissolve_out`, `fade_out`, `flash`, `pop`, … and their `on_done`), SpriteButton eases | presentation | a screen transition or a hit effect runs while the world is paused (a game-over `fade_out(on_done=change_act)` after `clock.paused = True` finishes; a shake under the pause menu ends: X-writers-2) |
| Double click, FPS, frame pacing | wall | input and the display |

Tests: `SystemWorld` pins no clock: transients, SpatialFx and the cover read
the frame clock in production, so the harness tests the shipped clock (review 2026-10-09, S1-6 / S1-7):
`tests/test_cover.py` (`TestCoverRunsOnPresentationTime`),
`tests/test_transients.py` (`TestTransientsRunOnPresentationTime`; LW6: they
read the wall clock until 2026-10-16, so a stall jumped them to their end),
`tests/test_spatial_fx.py` (`TestSpatialFxRunOnWorldTime`),
`tests/test_process.py` (`TestEveryCountsWorldSeconds`),
`tests/test_layer_scroll_view.py` (`test_hidden_layer_keeps_scrolling`).

## Pull reactivity

When the ownership tree has **pull consumers** (outbound `@=` / `@when`, or live
Derivates), a write marks itself and dependents **dirty** (no recompute yet). Reading
`Attribute.value` (or anything that goes through it) pulls and memoizes. Unlinked
shapes with cold Derivates skip the dirty walk (pose fast path). `@when` /
`@on_change` stay push-scheduled and run on `flush()`. A read stores the recomputed value; it never invalidates again (the write already walked the cone — "Pull stores raw"). Depth: [Reactive Design.md](Reactive%20Design.md).

## Scheduler

Cooperative (not `asyncio`): `after` / `every` / `tween` / `play_sound` / modes / `on_update` /
`ready` / `recently` (poll APIs; not Handles).
`wait` / `until` run inside a **task** the engine is driving: an async mode's body, or
`run_task(fn)` / `e.run_task(fn)` (an async sequence beside the modes; helpers they `await`
count; they await only Scena Handles — `asyncio.sleep(0)` or any other awaitable raises at the
`await`, [Actors Design — Tasks](Actors%20Design.md#tasks)). Those are the async entries: an `async def` hook, decorated handler or callback
raises `TypeError` naming `run_task` (its body would never run), and an async function
called without `await` is a SCENA WARNING at the calling line. Ownership: work started inside a mode body is **mode-scoped** (dies on leave);
work a task starts is the task's (dies when the task is cancelled; a finished task leaves it);
`e.after` / `e.every` / `e.tween` / `e.play_sound` / `e.run_task` are **entity-scoped** (survive mode change);
a sound that ends by itself finishes when its owner ends ([Sound Design](Sound%20Design.md#when-the-owner-ends));
`e.ready` / `e.recently` are per-instance poll memory (not Handles — die with the instance).
No public `on=`. Groups are tags and queries, **not** process owners. Event-track
handlers and looks do not cancel on mode leave. Depth:
[Actors Design.md](Actors%20Design.md). Sound mixer: [Sound Design.md](Sound%20Design.md).

## Collision

Enroll by tag → refresh proxy AABB → broad phase → exact prims only for overlaps →
narrow. Standing `resolve()` sweeps **motion** (`move_by` / `time=` ticks); instant
`*_to` / `=` / `@=` are **placement** (no swept teleport). Detection also sweeps a
body that travels more than half its thickness in a frame, so a fast `@collide` shot
does not pass through its target; slow bodies pay one compare
([Swept detection](Collision%20Design.md#swept-detection-fast-bodies)). An orbit
(`rotate_by(..., about=)`) is motion along its chord; a spin is not swept
([Orbit chord](Collision%20Design.md#orbit-chord)). Handlers share the flush
window with `@when`. One engine for Shape, Sprite, and SpatialFx. Depth:
[Collision Design.md](Collision%20Design.md). Sprite bake policy:
[Sprite Design.md](Sprite%20Design.md).

## Rendering pipeline

After flush:

1. Tick shape **transients**, **SpatialFx**, and **canvas cover**  
2. **Wallpaper** + **background fields** (pre-scene)  
3. View transform + **camera**; world layers bottom→top (`default` / author / `top` / parallax; parallax layers use a partial CTM; decoration only — no hit/collision). The reserved **`ui`** layer is **skipped** here.  
4. Per drawable: Shape/Sprite envelope (filters / `.visual` / geometry) or SpatialFx domain draw; optional filter batching. Graphics with sticky `_plain_blit` (no visual / filters / active transient) use `_blit_plain` — Sprite textured quad, Shape `_geometry_draw` — and skip the effect envelope; both pull linked `rotation` / `scale` first. When `cull_offscreen` is off (default), the layer list is visible-only (no per-object `_passes_cull`). Multipass Recipes paint from a 4-slot `Paint` pool; stroke/fill color is a Skia `Color4f` from the RGBA tuple (interned seed tints bake RGB and pulse via `setAlphaf` — no `Color()` per stroke). Consecutive interned stroke Recipes (Laser / Neon / Ink) on one layer emit **pass-major** (all halos, then mids, then cores) when `batch_shared_filters` is on — z relaxed only among that interned look; `fx_quality="max"` restores per-shape order. ElectricField / ElectricBolt **high** PE-glow shares one overlay Plus `Blur` plate among those peers (thin cores stay unfiltered). `Graphic.draw` skips stamp/transient probes when those slots are unset.  
5. If `canvas.effects` is active: scene → offscreen RT → **post stack**; else scene → window  
6. **View pass**: Graphics on reserved **`ui`** (camera=False), then **widgets** (HUD). `ui` always sits after post (sharp); `top` may opt out of post but still pans with the world.  
7. **Canvas cover** (`fade_in` / `fade_out`; after HUD; does not pay the scene RT)

Hit order for pointer: widgets (view) → `ui` Graphics (view) → world Graphics (world). Hover follows the same order and is **exclusive**: one hover target at a time (a widget under the cursor clears Graphic hover; a modal clears all), resolved once per frame; a Graphic with only hover handlers is a hover target but click-transparent. A modal widget (a modal `Menu`) swallows every pointer event and makes `keyp` / `mouse.press` read False; physical presses are still tracked, and a button that is down when the mask lifts stays hidden until it goes up. The mask is a level, re-checked once per frame: a hidden or parked modal stops masking, and shown again it masks again (review 2026-10-09 S3-2). Every script `on_key_down` / `on_mouse_down` gets its up, even when a modal opened in between or the act changed in between, and the script gets no up for a down it never saw (a consumed shortcut, a press a widget or Graphic took); `mouse.click_pos` does not record a click made under the mask or on a widget; an act change ends what continues an old script press — no click, no `on_mouse_drag`, no `on_key` repeat, no last click for a double click — but its up still comes (S3-7, S1-10, X-life-3, S3-11, S3-8, PD7). The key and mouse hooks are top-level script functions (an act has none), so the handler that saw the down is the one that gets the up in the new act: walking right into the door that changes level, `on_key_up("RIGHT")` still resets the walk (`CanvasManager.forget_act_input` marks old-act keys and presses in `_old_act_keys` / `_old_act_presses` instead of dropping them; a test harness that wants a clean slate calls `clear_input`). A press a HUD widget takes (dragging a Slider, holding a Button, a disabled widget's swallowed press) is hidden from `mouse.press` / `click_pos` until that button goes up, as a focused TextInput hides its keys from `keyp`: a paint app reading `mouse.press(Mouse.BTN_LEFT)` does not paint under the slider; a press on a Graphic (the author's own drag or click target) stays visible, except on a `SpriteButton`, which is a HUD button (PD2, `Mouse._widget_buttons`, `SpriteButton._hides_press`). A widget that leaves while it holds a press lets go of what the press set, with no click: a hold-to-fire `Button(st["firing"])` destroyed mid-hold, or by an act change, writes `value_off` (`UIWidget._abandon_press`, from `remove_widget` and the lost-release recovery; PD1). `mouse.dx` / `.dy` are this frame's pointer motion: the sum of the motion events since the previous frame, 0 on a still frame, a camera move under a still cursor not counted (S1-1). A world drag follows the sampled world pointer, so a dragged shape stays under a still cursor while the camera pans (S3-4). The pointer is sampled once after the poll and again after the process tick when the camera moved in `update` or by a timed camera verb, so drag, hover and `mouse` links follow the camera the frame is drawn with; `update` itself reads the pre-move pointer, which is what the user saw (review 2026-10-09 W-P1). Script `on_key` (press and repeats) follows the same door as `on_key_up`: a key the script never saw go down sends no repeats when a modal mask lifts (W-P4). Widget hover re-resolves under a still cursor when a widget is added, removed, shown, hidden or enabled (S3-6), and a pressed widget keeps its hover until the pointer leaves it (S3-5). Widget hover also follows the per-frame pointer sample, as Graphic hover does: when the sampled view point differs from the last one hover was resolved at (`WidgetManager._ptr_seen`) — the cursor left the window, so no motion event came — `refresh_hover` runs and the Button gets its `on_hover_exit` (PD4). A still cursor costs one tuple compare; a camera pan does not move the view point. GLFW's cursor-enter callback is not needed: `get_cursor_pos` reports the cursor outside the window too. A drag finds its drop target in either space, `ui` first (Shapes Design, Drag and drop; PD5). Collision and SpatialFx are forbidden on `ui`.

Empty inactive post stack is identity. Depth: [Canvas Design.md](Canvas%20Design.md),
[Effect System Design.md](Effect%20System%20Design.md).


# Where to go next

Menu, not a reading list — open **one** companion, then pick **one** jump-box row
in that file. Locating code: [Appendix: module map](#appendix-module-map).


| Doc | When you need… |
| --- | --- |
| [Guia da API](../docs/pt/guide/index.html) | Author calls, catalogs, examples |
| [Reactive Design.md](Reactive%20Design.md) | Container graph, takein, A1–A3, hazards |
| [Shapes Design.md](Shapes%20Design.md) | Models, transforms, CTM draw |
| [Tracks Design.md](Tracks%20Design.md) | `Track`, `move_along`, presets, overlay |
| [History Design.md](History%20Design.md) | `History` add / snapshot, `Contrail` stroke recipe |
| [Actors Design.md](Actors%20Design.md) | Process, modes, groups, ink |
| [Act Design.md](Act%20Design.md) | `Act` / `change_act` / `run(Titulo)`: what an act change removes / restores / keeps; the world-settings table; where the top level ends |
| [Sprite Design.md](Sprite%20Design.md) | Sheet, play, clone, auto hitbox, mass path |
| [Collision Design.md](Collision%20Design.md) | Shared collision pipeline |
| [Canvas Design.md](Canvas%20Design.md) | Canvas, camera, `chase` / `approach` / `deadzone`, layers, cull, backgrounds |
| [Effect System Design.md](Effect%20System%20Design.md) | Looks, transients, SpatialFx, post, quality; **§5.5** before changing filters / draw bounds |
| [Effect Handles.md](Effect%20Handles.md) | Post / background mutate-hide-remove |
| [Sound Design.md](Sound%20Design.md) | `play_sound`, mixer, mic, audio FX |
| [Box Design.md](Box%20Design.md) | `Box` / `Grid`, `box=`, `game_view` / `ui_view`, `group[...].box` |
| [Editor Design.md](Editor%20Design.md) | Level files, `Level` / `make()`, the level editor (companion app) and its boundary |
| [Testing Design.md](Testing%20Design.md) | Test strategy, harnesses (`hypothesis_support`, `system_support`), the **bug loop** after a fix, bug catalogue and recurring bug classes |
| [Fences.md](Fences.md) | Settled nos — **only** when proposing sugar / a second spelling / a silent rewrite |


# Appendix: module map

Router for `scena/` (flat package). Match one row; open **Start**.
Do not read this appendix as a license to open the whole cluster.

## Use

1. Pick one row below.
2. Open **Start** only (search; do not read fat files end-to-end).
3. Open **Also** only if Start is not enough.
4. Open **Design** only if invariants / datapath are unclear. Treat fences in that section as current constraints.
5. Stop. Do not ingest other subsystems, the private `workbench/archive/` / `workbench/proposals/`, or `_sksl_*`.
6. [Fences.md](Fences.md) only when proposing new surface / a second spelling / a silent rewrite.

## Router


| Need | Start | Also | Design (if needed) |
| --- | --- | --- | --- |
| `from scena import …` | `__init__.py` | — | [Guia da API](../docs/pt/guide/index.html) |
| `run()` / window / frame order | `orchestration.py` | — | [Datapath](#datapath) |
| Frame pacing / VSync / world `dt` from the display | `pacing.py` | `_display_link.py` (macOS), `orchestration.py` (`_run_loop`, `set_glfw_fps`), `fx_auto.py` (ladder) | [Frame pacing and GC](#frame-pacing-and-gc) |
| GC freeze after build | `gc_policy.py` | `orchestration.py` (`_begin_game`, `_cleanup`), `act.py` (`change`) | [Frame pacing and GC](#frame-pacing-and-gc) |
| `Act` / `change_act` / `run(Titulo)` | `act.py` | `orchestration.py` (`_begin_game`), `registry.py` | [Act Design.md](Act%20Design.md) |
| Camera, layers, cull, draw walk | `canvas.py` | `registry.py`, `easing.py` (`chase` / `approach` / `deadzone`) | [Canvas Design.md](Canvas%20Design.md) |
| `chase` / `approach` / `deadzone` | `easing.py` | `scenamath.py` (`_as_xy`) | [Canvas Design.md](Canvas%20Design.md#follow-math-chase--deadzone) |
| Parallax layer CTM | `camera_response.py` | `registry.py`, `canvas.py` | [Canvas Design.md](Canvas%20Design.md) |
| Wallpaper / background fields | `background_kinds.py` | `background.py` | [Canvas Design.md](Canvas%20Design.md), [Effect System Design.md](Effect%20System%20Design.md) |
| Cover fade/wipe | `cover.py` | `orchestration.py` (draw slot) | [Effect System Design.md](Effect%20System%20Design.md) |
| `Entity`, ink, construct | `entity.py` | `place.py` | [Actors Design.md](Actors%20Design.md) |
| `group["name"]` / formula `@=` | `registry.py` (`GroupOperator`) | `process.py` (`until_empty`) | [Actors Design.md](Actors%20Design.md#fleet-helpers-groups) |
| `Circle` / models / Graphic draw API | `shapes.py` | `entity.py` (`Graphic` ABC) | [Shapes Design.md](Shapes%20Design.md) |
| `Box` / `Grid` / `box=` | `box.py` | `shapes.py`, `canvas.py` | [Box Design.md](Box%20Design.md) |
| `Level` / level file / `make()` | `level.py` | `level_format.py` | [Editor Design.md](Editor%20Design.md) |
| Level editor (companion app) | `scena_editor/` | `scena_editor/_engine.py` | [Editor Design.md](Editor%20Design.md#editor-companion-app) |
| `group[...].box` | `registry.py` (`GroupOperator.box`) | `box.py` | [Box Design.md](Box%20Design.md#bridge) |
| `Graphic.confine` | `confine.py` | `entity.py` (`Graphic.confine`) | [Box Design.md](Box%20Design.md) |
| `Track` / `move_along` / `show_tracks` | `track.py` | `curves.py`, `process.py` | [Tracks Design.md](Tracks%20Design.md) |
| `History` / `Contrail` | `history.py` | `orchestration.py` (pre-draw tick) | [History Design.md](History%20Design.md) |
| Outline crossings | `geom.py` | — | [Shapes Design.md](Shapes%20Design.md) |
| `Sprite` / `Sheet` / `Svg` / play | `sprite.py` | `atlas.py` (sheet + auto hitbox bake) | [Sprite Design.md](Sprite%20Design.md) |
| HUD `Text` | `text.py` | `uiwidget.py` (shared HUD column) | [Canvas Design.md](Canvas%20Design.md) |
| Widgets | `uiwidget.py` | `orchestration.py` (`WidgetManager`) | [Canvas Design.md](Canvas%20Design.md) (HUD column) |
| `SpriteButton` | `sprite_button.py` | `orchestration.py` (press), `canvas.py` (solo draw) | [Sprite Design.md](Sprite%20Design.md#spritebutton) |
| `@=` / Attribute / pull graph | `state.py` | — | [Reactive Design.md](Reactive%20Design.md) |
| `@=` formula source reading (cache, named functions, refusals) | `formula_check.py` | `state.py` (`FormulaLink._extract_sources`) | [Reactive Design.md](Reactive%20Design.md#formula-visibility-named-functions-helpers-refusals) |
| Process overlay (Ctrl+Shift+6, `show_processes`) | `process_overlay.py` | `orchestration.py` (chord, draw after the cover), `process.py` (`Script.waiting_since`) | [Actors Design.md — Process overlay](Actors%20Design.md#process-overlay) |
| `after` / `every` / tween / modes / `run_task` / `ready` / `recently` | `process.py` | `easing.py` (`ease=`, `remap`, `lerp`, `chase`, `approach`, `deadzone`) | [Actors Design.md](Actors%20Design.md) |
| `play_sound` / `Sound` / `audio` | `audio.py` | `audio_mixer.py` | [Sound Design.md](Sound%20Design.md) |
| Microphone | `audio_capture.py` | `audio.py` | [Sound Design.md](Sound%20Design.md) |
| `@= lambda: mic.level` / `audio.level` / `h.level` | `level_source.py` | `state.py` (`_formula_source_of`), `orchestration.py` (frame step 1) | [Sound Design.md — Levels as formula sources](Sound%20Design.md#levels-as-formula-sources) |
| Audio FX (`LowPass`, …) | `audio_effects.py` | `audio_mixer.py` | [Sound Design.md](Sound%20Design.md) |
| `@when` / `@on_change` | `events.py` | `state.py` (dirty / flush) | [Reactive Design.md](Reactive%20Design.md) |
| `@click` / `@hover` / `@drag_*` | `interaction.py` | `orchestration.py` (`ShapeInteractionManager.step_hover`), `registry.py` (hit order, `_pointer_epoch`) | [Shapes Design.md — Hover](Shapes%20Design.md#hover-pointer_hover-hover--hover_exit) |
| `@collide*` **sugar** | `interaction.py` | `collision.py` (engine) | [Collision Design.md](Collision%20Design.md) |
| Collision **engine** / `resolve` | `collision.py` | `entity.py` (enroll) | [Collision Design.md](Collision%20Design.md) |
| `resolve(..., only=)` read-only guard | `purity_check.py` | `formula_check.py` (locator), `collision.py` (`_OnlyGate`) | [Collision Design.md — One-way pairs](Collision%20Design.md#one-way-pairs-only) |
| Sprite hitbox **bake** | `atlas.py` | `sprite.py` | [Sprite Design.md](Sprite%20Design.md) |
| `add_hitbox` / `Hitbox` (parts) | `hitbox.py` | `sprite.py` (`_HitboxBakeMixin`), `collision.py` (`_tag_item`) | [Sprite Design.md](Sprite%20Design.md#hitbox-parts) |
| `px_rect` / `px_circle`, `sprite.showing()`, linked `hb["active"] @=` | `hitbox.py` (`_px`, `_ActiveRef`, `_LINKED_PARTS`) | `sprite.py` (`_parse_frame_selector`), `collision.py` (`step`, `_query_collider`) | [Sprite Design.md — round 2](Sprite%20Design.md#pixel-shapes-and-linked-active-round-2) |
| `@leave_playfield` | `bounds.py` | `canvas.py` (`playfield`) | [Canvas Design.md](Canvas%20Design.md), [Box Design.md](Box%20Design.md) |
| `floor_below` (ledge / will I fall) | `collision.py` (`CollisionSystem.floor_below`) | `entity.py` (`Graphic.floor_below`) | [Collision Design.md](Collision%20Design.md#floor-ahead-floor_below) |
| Paint / Gradient / Texture / Palette | `style.py` | `color.py` (`Palette`, `Colormap`, `Color`) | [Effect System Design.md](Effect%20System%20Design.md) |
| ImageFilters (`Blur`, …) | `filters.py` | `style.py` | [Effect System Design.md](Effect%20System%20Design.md) ([§5.5](Effect%20System%20Design.md#55-changing-the-effect-system-without-regressing-hot-paths) before edits) |
| `.visual` compiled looks | `visuals.py` | — | [Effect System Design.md](Effect%20System%20Design.md) ([§5.5](Effect%20System%20Design.md#55-changing-the-effect-system-without-regressing-hot-paths) before edits) |
| `Neon` / multipass costumes | `recipes.py` | `visuals.py` | [Effect System Design.md](Effect%20System%20Design.md) |
| `.glow` / `.shadow` / `.hue` / `.gray` / `.tail` | `stamps.py` | `style.py` | [Effect System Design.md](Effect%20System%20Design.md) |
| Transients (`flash`, `pop`, …) | `transients.py` | — | [Effect System Design.md](Effect%20System%20Design.md) |
| `SpatialFx` host | `spatial_fx.py` | `spatial_fx_effects.py` (kinds) | [Effect System Design.md](Effect%20System%20Design.md) |
| Canvas post stack | `postfx.py` | `effects.py` (built-ins) | [Effect System Design.md](Effect%20System%20Design.md), [Effect Handles.md](Effect%20Handles.md) |
| Quality / Auto | `fx_quality.py` | `fx_auto.py` | [Effect System Design.md](Effect%20System%20Design.md) |
| Look/FX type errors | `validate.py` | — | [Effect System Design.md](Effect%20System%20Design.md) |
| `Vec2` / `chance` | `scenamath.py` | — | — |
| Writing tests / a test found a bug | `tests/README.txt` | `tests/hypothesis_support.py`, `tests/system_support.py` | [Testing Design.md](Testing%20Design.md) |
| Running tests (which tier, when) | `tests/run_tiers.py` | `tests/README.txt` | [Testing Design.md — Test tiers](Testing%20Design.md#test-tiers) |

## Do not confuse


| Looks like | Is actually | Not |
| --- | --- | --- |
| `@collide` on a script | sugar in `interaction.py` | the sweep/AABB engine (`collision.py`) |
| `@when` | `events.py` (flush) | `process.py` (timers/tweens) |
| Graphic pose API | published from `shapes.py` | defined on `Graphic` in `entity.py` |
| Registry / `group` | `registry.py` | draw/camera (`canvas.py`) or the loop (`orchestration.py`) |
| `group("name")` | migration `TypeError` | `group["name"]` |
| `group["name"] @=` | `GroupOperator` (`registry.py`) | Attribute / `FieldRef` (`state.py`) |
| `canvas.follow` | does not exist | `chase` / `approach` / `deadzone` + `pan_to` (`easing.py`) |
| Background **kind** | `background_kinds.py` | stack/attachment (`background.py`) |
| SpatialFx **kind** | `spatial_fx_effects.py` | host/registration (`spatial_fx.py`) |
| Post **kind** | `effects.py` | stack (`postfx.py`) |
| `.visual = Glow()` | `visuals.py` | `recipes.py` (`Neon`, …) or `stamps.py` (`.glow =`) |
| HUD `Text` | `text.py` | `uiwidget.py` |
| `Palette("plasma")` | discrete swatches from the shared preset table (`color.py`) | `Gradient("plasma")` (paint) or `Colormap.get_color(t)` (continuous) |
| `ui.gap()` | HUD column verb (`uiwidget.py`) | a measuring `Box` (`box.py`) |
| `ui.stack_column()` | next HUD column, same visual top (`uiwidget.py`) | `ui.stack_origin(x, y)` (absolute) |
| `Text(top_right=)` | right edge pinned; the string grows left (`text.py`) | `align="right"` (only places lines inside the box) |
| `widget.box` | read-only view-space `Box` snapshot of a widget (`uiwidget.py`) | `Text(box=)` / `Menu(box=)` (placement) |
| `Box` / `graphic.box` | `box.py` | a `Rect` (`shapes.py`) or `canvas.playfield` (`bounds.py`) |
| `group[...].box` | `registry.py` (`GroupOperator.box`) | `graphic.box` (`box.py`) |
| `Graphic.confine` | `confine.py` | `@leave_playfield` (`bounds.py`) or `resolve()` (`collision.py`) |
| `canvas.game_view` | world frustum `Box` (`canvas.py`) | `ui_view` (HUD) or `playfield` (leave area) |
| `hitbox_shape="auto"` bake | `atlas.py` | runtime pairs (`collision.py`) |
| `Hitbox` (from `add_hitbox`) | detect-only part (`hitbox.py`) | the body's `hitbox_shape=` kind, or a `Track(sprite)` outline |

## Clusters (subsystem-wide change only)

Same names as [Subsystems](#subsystems). Open the cluster only when the change spans it.

- **Surface:** `__init__.py`
- **Run loop:** `orchestration.py`
- **Reactive:** `state.py`, `formula_check.py` → [Reactive Design.md](Reactive%20Design.md)
- **Canvas:** `canvas.py`, `registry.py`, `camera_response.py`, `background.py`, `background_kinds.py`, `cover.py` → [Canvas Design.md](Canvas%20Design.md)
- **Entities:** `entity.py`, `place.py` → [Actors Design.md](Actors%20Design.md)
- **Graphics:** `shapes.py`, `box.py`, `confine.py`, `track.py`, `history.py`, `curves.py`, `geom.py`, `sprite.py`, `hitbox.py`, `atlas.py`, `text.py`, `style.py`, `color.py`, `gradient_presets.py`, `level.py`, `level_format.py` → [Shapes Design.md](Shapes%20Design.md), [Tracks Design.md](Tracks%20Design.md), [History Design.md](History%20Design.md), [Sprite Design.md](Sprite%20Design.md), [Box Design.md](Box%20Design.md), [Editor Design.md](Editor%20Design.md)
- **Collision:** `collision.py` → [Collision Design.md](Collision%20Design.md)
- **Bounds:** `bounds.py` → [Canvas Design.md](Canvas%20Design.md), [Box Design.md](Box%20Design.md)
- **Scheduler:** `process.py`, `process_overlay.py`, `events.py`, `easing.py` → [Actors Design.md](Actors%20Design.md), [Reactive Design.md](Reactive%20Design.md)
- **Audio:** `audio.py`, `audio_mixer.py`, `audio_capture.py`, `audio_effects.py` → [Sound Design.md](Sound%20Design.md)
- **Input / HUD:** `input.py`, `interaction.py`, `uiwidget.py`
- **Looks:** `filters.py`, `visuals.py`, `recipes.py`, `stamps.py`, `validate.py`, `transients.py`
- **Scene FX:** `spatial_fx.py`, `spatial_fx_effects.py`, `postfx.py`, `effects.py`, `fx_quality.py`, `fx_auto.py` → [Effect System Design.md](Effect%20System%20Design.md) (file roles: [§12](Effect%20System%20Design.md#12-file-map))
- **Helpers:** `scenamath.py`
- **Shaders (task = shader only):** `_sksl_shape.py`, `_sksl_effects.py`, `_sksl_ambient.py`, `_sksl_ambient_kit.py`, `_sksl_backdrop.py` — value noise must use the exact-lattice hash ([Effect System Design §9 rule 23](Effect%20System%20Design.md#9-known-rules--gaps))

## Do not slurp

Search these; do not read end-to-end unless the hunk is already known:
`shapes.py`, `recipes.py`, `sprite.py`, `collision.py`, `state.py`, `orchestration.py`, `style.py`, `visuals.py`, `canvas.py`, `box.py`.

## Do not open

`workbench/archive/` and `workbench/proposals/` — private, not published, may be
absent in a checkout ([README — Private folders](README.md#private-folders)). Not canon: the
companions hold every conclusion and its reason; open them only when the task names one,
`scripts/` (unless visual/bench proof), `_sksl_*` (unless the shader is the task).
[Fences.md](Fences.md) is **not** this list — open it only when proposing new surface.
Tests follow `tests/test_<area>.py` — not a second map. Strategy and the bug loop: [Testing Design.md](Testing%20Design.md).


# Implementation status

Current baseline — not a freeze.


| Area | Status |
| --- | --- |
| Pull reactivity (invalidate on write, recompute on read) | **Implemented** — `@when` / `@on_change` stay push + batched |
| Lazy Container graph registration (bare Vec2/Attribute) | **Implemented** — non-Entity Containers stay off-graph until first edge; Entities always register; `Graphic.vel` mutates in place; leak sampler → SCENA WARNING (`scena.orchestration.set_leak_detector` — bench/tooling only, not in `scena.__all__`) only on sustained unbounded climb (wall-clock cadence; spawn bursts / slot warmup stay quiet); tests: `tests/test_graph_lifecycle.py` (`TestLazyContainerRegistration`), `tests/test_leak_detector.py` |
| GC DependencyGraph backstop (weak nodes + finalize purge) | **Implemented** — `WeakValueDictionary` + per-node `weakref.finalize` purge; dead-id filter in `topological_sort`; `set_graph_gc_backstop` default on; root-coalescing deferred (measured construct-only). [Reactive Design.md](Reactive%20Design.md); tests: `tests/test_graph_gc_backstop.py` |
| Reactive invalidation micro-opt (Tier 1) | **Implemented** — cheaper `mark_dirty`, change-gated pose notify, cached `_iter_subtree`, leaf `_resolve_link` / `Point.takein`, clean linked `ScalarSlot` reads; no dirty-walk short-circuit. [Reactive Design.md](Reactive%20Design.md); tests: `tests/test_reactive_tier1_characterization.py` |
| Epoch / version change-gating | **Deferred** — graph flush measured ≈ 0 on the CPU probes, and a boolean short-circuit of the dirty walk is unsound under conditional formulas — [Reactive Design.md — Honest tradeoff](Reactive%20Design.md#honest-tradeoff) |
| `@=` named functions + formula visibility check + parse cache | **Implemented** — [Reactive Design.md — Formula visibility](Reactive%20Design.md#formula-visibility-named-functions-helpers-refusals); `scena/formula_check.py`; tests: `tests/test_formula_functions.py` |
| Appearance links (`color` / `fill` / `line` / `line_width`, Text `background`, Sprite `alpha`, `visible`, flips) | **Implemented** 2026-10-15 — link targets that write through the setter; draw-head + hover-start refresh — [Reactive Design.md — Appearance links](Reactive%20Design.md#appearance-paintstate-internal); tests: `tests/test_paint_flag_links.py` (canaries) |
| One scale per sprite, `Sheet(anchor=)`, `Sheet(pixel_size=)`, `clip(offset=)`, construct cell = first clip | **Implemented** — [Sprite Design.md — Scale and registration](Sprite%20Design.md#scale-and-registration); snapshot cache keyed on sprite `center` ([Collision Design.md](Collision%20Design.md#snapshot-cache-anchor-translate-fast-path)); tests: `tests/test_sheet_scale_anchor.py` |
| Pose fast path A1–A3 (unlinked motion) | **Implemented** — [Reactive Design.md](Reactive%20Design.md) |
| Float pose + Attribute promotion (B1) | **Deferred** — [Reactive Design.md](Reactive%20Design.md) |
| Mass sprite hot path | **Implemented** — [Sprite Design.md](Sprite%20Design.md) |
| CPU hot-path campaign | **Implemented** — [Reactive Design.md](Reactive%20Design.md) |
| Leave playfield | **Implemented** — `@leave_playfield`, `canvas.playfield` (`set(box)` since 0.7.0); tests: `tests/test_leave_playfield.py` |
| Infinite scroll: `Endless`, `layer.view`, live `layer.scroll`, scroll in the frame tick | **Implemented (0.7.0)** — [Canvas Design.md — Endless fill](Canvas%20Design.md#endless-fill), [Layer view](Canvas%20Design.md#layer-view); Guia: [Mundo sem fim](../docs/pt/guide/index.html#mundo-sem-fim); tests: `tests/test_endless.py`, `tests/test_layer_scroll_view.py`; smoke: `scripts/smoke/endless.py` |
| Hitbox model: every hitbox is a `Hitbox`; `box` / `hitbox.box` / `art_box` | **Implemented** — [Sprite Design.md — Hitboxes: one type](Sprite%20Design.md#hitboxes-one-type), [Measuring a sprite](Sprite%20Design.md#measuring-a-sprite); main-hitbox switch: [Collision Design.md](Collision%20Design.md#main-hitbox-switch); lazy measured boxes: [Box Design.md](Box%20Design.md); tests: `tests/test_hitbox_model.py`, `tests/test_sprite_measure.py`, `tests/test_box_snapshot.py` |
| `floor_below` | **Implemented** — hitbox march (lift / across / drop) against `resolve()` partners or `group=`, solver floor rule and snap reach; [Collision Design.md — Floor ahead](Collision%20Design.md#floor-ahead-floor_below); Guia: [Chão à frente](../docs/pt/guide/index.html#colisao-floor); tests: `tests/test_floor_below.py`; comparison smoke: `scripts/smoke/ledge_probe.py` |
| Box / placement | **Implemented** — [Box Design.md](Box%20Design.md); tests: `tests/test_box.py` |
| `Graphic.confine` | **Implemented** — [Box Design.md — Confine](Box%20Design.md#confine); tests: `tests/test_confine.py` |
| Collision proxy AABB (rotation) | **Implemented** — [Collision Design.md](Collision%20Design.md#runtime-cost-mass-sprite-related) |
| Swept detection for fast bodies (`@collide`) | **Implemented (2026-10-05)** — a body whose `move_by` travel exceeds half its thickness is detected along its path (resolve's TOI, relative motion), enters run in time-of-impact order (nearest hit first), payload depth 0 at the impact point; hitbox parts travel with their host; resolve pairs too (a fast body pushed into a thin resolve wall now fires `@collide`); no author flag; slow scenes pay one multiply + compare per moving collider (perf contract test, interleaved A/B vs the previous tree within noise). [Collision Design.md — Swept detection](Collision%20Design.md#swept-detection-fast-bodies); tests: `tests/test_collision.py` (`TestSweptDetection`), `tests/test_sys_fast_shots.py`, `tests/test_sys_hyp_collision.py` (`TestFastMotionAgainstSweptOracle`); bench: `scripts/bench/perf_collision_fast.py`; bugs CT1–CT4 in [Testing Design](Testing%20Design.md#ct--continuous-detection-2026-10-05). An orbit (`rotate_by(..., about=)`, timed or instant) notes its anchor's chord as motion (2026-10-05, CT4; `TestOrbitMotion`); spin stays parked ([Spin (not swept)](Collision%20Design.md#spin-not-swept)) |
| One-way pairs `resolve(..., only=)` | **Implemented (2026-09-29)** — sides of the first argument (`touching_sides` words), a list/tuple/set, or a function of the contact; S1 (contact normal at first contact); a rejected contact makes the pair pass until they separate; registration conflicts raise; zero cost unless some pair has `only=` (per-body dispatch); read-only guard for `only=` functions (static at `resolve()`, runtime lock on cold choke points — `purity_check.py`). [Collision Design.md — One-way pairs](Collision%20Design.md#one-way-pairs-only); Guia: [Mão única](../docs/pt/guide/index.html#res-only); tests: `tests/test_resolve_only.py`, `tests/test_sys_resting_contact.py` (`TestOneWayTilesHold`), `tests/test_act.py` (`test_act_change_restores_resolve_only`) |
| Effect system (v1) | **Implemented** — [Effect System Design.md](Effect%20System%20Design.md) |
| Recipe paint / color hot path | **Implemented** — tuple→`Color4f` (no per-stroke `Color()`); interned-seed bake + `setAlphaf` — [Effect System Design.md §3.1b](Effect%20System%20Design.md#31b-shape-visuals-shapevisual) · [§5.6](Effect%20System%20Design.md#56-recipe-draw-hot-path--lessons) |
| Recipe look-pass grouping | **Implemented** — consecutive interned Laser / Neon / Ink emit pass-major; buckets kind-pure by `_world_stroke_kind`; `fx_quality="max"` / `batch_shared_filters=False` escapes — [Effect System Design.md §3.1b](Effect%20System%20Design.md#31b-shape-visuals-shapevisual) · [§5.6](Effect%20System%20Design.md#56-recipe-draw-hot-path--lessons) |
| Graphic.draw ceremony | **Implemented** — hoisted stamp import; skip unset transient/stamp slots — [Effect System Design.md §3.1b](Effect%20System%20Design.md#31b-shape-visuals-shapevisual) |
| Plain Shape/Sprite `_blit_plain` | **Implemented** — Shape `_geometry_draw` + Sprite textured quad; both `_pull_property_anchors` (linked `angle`/`scale`); canvas sticky `_plain_blit` — [Sprite Design.md](Sprite%20Design.md#plain-blit--draw-list-compact), [Shapes Design.md](Shapes%20Design.md#plain-draw-_blit_plain), [Canvas Design.md](Canvas%20Design.md) |
| Cull-off draw-walk hoist | **Implemented** — when `cull_offscreen` is False, skip per-object `_passes_cull` (visible-only list) — [Canvas Design.md — Offscreen culling](Canvas%20Design.md#offscreen-culling) |
| Electric* overlay-glow batch | **Implemented** — ElectricField / ElectricBolt high PE-glow shares one Plus `Blur(σ=2.2)` plate; max escapes — [Effect System Design.md §3.1b](Effect%20System%20Design.md#31b-shape-visuals-shapevisual) |
| Neon HSV / look-pass center hoist | **Implemented** — `_vivid_rgb` / `_energy_*` float HSV (no `Color()`); hoist `_center_radius` across passes — [Effect System Design.md §3.1b](Effect%20System%20Design.md#31b-shape-visuals-shapevisual) · [§5.6](Effect%20System%20Design.md#56-recipe-draw-hot-path--lessons) |
| Live recolor of seeded looks | **Implemented** — `set_color` / `.color=` on a look made with `color=` de-seeds it to its interned unseeded sibling (Neon / Halo 2026-09-10, every other look 2026-10-13); `set_color(X)` gives what `color=X` gives under every look, an outline look follows the shape's outline, `.fill` / `.line` and the stroke knobs (`line_width`, `blend`, `dash`, …) under a look re-apply it (2026-10-13) — [Effect System Design.md §3.1b](Effect%20System%20Design.md#31b-shape-visuals-shapevisual) · [§9](Effect%20System%20Design.md#9-known-rules--gaps) |
| Actors (Entity, process, Sprite) | **Implemented** — [Actors Design.md](Actors%20Design.md); API in [Guia da API](../docs/pt/guide/index.html) |
| Sprite `hitbox_shape="auto"` | **Implemented** — frozen reference-set bake; `"rect"` / `"ellipse"` / `"circle"` / `"hull"`; `source` (`"clip"`, `"all"` = registered clips, tuple of clips) / numeric `hitbox_anchor` / per-axis `hitbox_scale`; kind lock under `"auto"` + `"each"` / `"clip"`; extra detect-only colliders via `add_hitbox` (hitbox parts; follow paint incl. tilt; `Track(sprite)` stays an outline, `.silhouette` removed); round 2 (2026-09-28): hand-placed `px_rect` / `px_circle` parts, `sprite.showing()`, and a linked `hb["active"] @=` — [Sprite Design.md](Sprite%20Design.md#hitbox-parts); tests: `tests/test_hitbox_parts.py`, `tests/test_hitbox_round2.py` |
| Sprite spawn / `Graphic.clone` | **Implemented** — [Sprite Design.md](Sprite%20Design.md) |
| Tracks / `move_along` | **Implemented** — [Tracks Design.md](Tracks%20Design.md); tests: `tests/test_track.py` |
| Process overlay (tasks, modes, loose timers; Ctrl+Shift+6, `show_processes`) | **Implemented (2026-10-20)** — [Actors Design.md — Process overlay](Actors%20Design.md#process-overlay); tests: `tests/test_process_overlay.py` |
| `speed=` on timed pose verbs (rate instead of duration) | **Implemented (2026-10-13)** — `move_to` / `move_by` / `move_along` / `rotate_to` / `rotate_by` / `reset_rotation` and camera `pan_to` / `pan_by`; duration = distance ÷ speed read once at the call, then the same tween as `time=`; `time=` + `speed=` raises; `move_along` needs one of the two; scale / zoom / `tween` refuse it — [Actors Design.md — Rate instead of duration](Actors%20Design.md#rate-instead-of-duration-speed); tests: `tests/test_timed_speed.py` |
| History / Contrail | **Implemented** — [History Design.md](History%20Design.md); tests: `tests/test_history.py`; smoke: `scripts/smoke/history.py` |
| Audio / `play_sound` | **Implemented** — [Sound Design.md](Sound%20Design.md); tests: `tests/test_audio.py` |
| Live groups (brackets, join-order walks, formula `@=`) | **Implemented** — [Actors Design.md](Actors%20Design.md#fleet-helpers-groups); tests: `tests/test_registry_layers.py`; smoke: `scripts/smoke/group_formula.py` |
| Camera follow sugar / `group.box` / `frame_to(None)` | **Implemented** — oriented group AABB (Line ends included); timed `frame_to` rotation uses the shortest arc. [Canvas Design.md — Timed camera](Canvas%20Design.md#timed-camera), [Follow math](Canvas%20Design.md#follow-math-chase--deadzone), [Box Design.md](Box%20Design.md); tests: `tests/test_easing.py`, `tests/test_canvas.py`, `tests/test_registry_layers.py` |
| `recently()` / entity-scoped `ready()` / `e.recently()` | **Implemented** — [Actors Design.md](Actors%20Design.md); Guia: [recently](../docs/pt/guide/index.html#agendar-recently), [ready](../docs/pt/guide/index.html#agendar-ready); tests: `tests/test_process.py` (`TestRecently`, `TestEntityReadyRecently`). Jump buffer / coyote time use `recently()`, not a keyboard-only `keyp.buffered`. |
| Multi-body attach (turret / compound) | **Deferred** — only when a script needs it |
| `SpriteButton` (game button from art) + `pointer_pressed` + `sprite.gray` | **Implemented** (2026-10-02) — a Sprite subclass: draw-time hover / press / disabled feel, breathing, `on_click`, sounds, a `Text` label part (shrink-to-fit, relative pose), state art, linkable `enabled`, click area = convex hull of the rest art. [Sprite Design.md — SpriteButton](Sprite%20Design.md#spritebutton); press lifecycle: [Shapes — Press lifecycle](Shapes%20Design.md#press-lifecycle-pointer_pressed); Guia: [SpriteButton](../docs/pt/guide/index.html#ui-sprite-button), [Complementos](../docs/pt/guide/index.html#aparencia-selos) (`.gray`); tests: `tests/test_sprite_button.py`, `tests/test_shape_interaction.py` (`TestPointerPressed`), `tests/test_kind_dispatch.py`, `tests/test_sprite.py` (`TestSpriteGrayStamp`) |
| Level files (`Level`, `item.make()`, `item.box`) | **Implemented** (2026-10-01) — [Editor Design.md](Editor%20Design.md); `scena/level.py`, `scena/level_format.py`; Guia: [Level](../docs/pt/guide/index.html#colocar-fase); tests: `tests/test_level.py` (reader, errors, format round-trip and one-bad-edit properties), `tests/test_level_codegen.py` (copied code = `make()` = item), `tests/test_level_sheets.py` (spritesheets, version 2, 2026-10-20; editor: `test_editor_sheets`, `test_editor_sheet_pick`). The level editor (`scena_editor/`, companion app, `python -m scena_editor`) — v1 built (2026-10-01), tests in `scena_editor/tests/` (second test root) |
| Acts (`Act`, `change_act`, `run(Titulo)`) | **Implemented** (2026-09-28) — [Act Design.md](Act%20Design.md); `scena/act.py`; Guia: [Atos](../docs/pt/guide/index.html#atos); tests: `tests/test_act.py` (incl. the settings-classification guard and a census soak). Ownerless scope: `"game"` (top level) / `"act"` |
| Numeric layers (`layer=<int>`) + `above()` / `below()` | **Implemented** — [Canvas Design.md — Registry and layers](Canvas%20Design.md#registry-and-layers); Guia: [Camadas](../docs/pt/guide/index.html#mundo-camadas); tests: `tests/test_registry_layers.py` (`TestNumericLayers`, `TestAboveBelow`) |
| Persistent drivers (formula / drag / wheel / tween / `move_along` / standing `resolve`) | **Implemented** — only a formula is exclusive (formula vs any driver raises, either order); drag / wheel / motion / resolve compose in either order; a pointer hold holds motion on the parts it writes; same-kind warn+replace; messages name the actor by its construction line — [Shapes Design.md — Persistent drivers vs linked pose](Shapes%20Design.md#persistent-drivers-vs-linked-pose); Guia: [Drivers persistentes](../docs/pt/guide/index.html#reativo-drivers); tests: `tests/test_driver_composition.py`, `TestInteractiveLinkInvariant`, `TestTweenAndTimedPose` claim cases, `TestResolution.test_resolve_blocks_linked_center_eagerly` |
| API robustness guards | **Implemented** — Numbers rule on every public constructor / slot / verb; keyword-only shape constructors; `obj.field = lambda` → `CallableAssignError` for every field kind; ink near-miss / look-family / `enable`·`enabled` → `.active` / key-name / mouse-button / layer typos raise with the fix; `@when` bool + handler arity checked at registration; engine tooling (`set_leak_detector`, `set_sync_watchdog`, `sky_palette`, `get_extrude_focus`, `set/get_metal_light`, the SCENA WARNING banner's `last_author_error` / `clear_author_error`) out of `scena.__all__`. Unknown keyword / missing argument on any exported class → `Did you mean` + `Valid:` + call shape, never `X.__init__()` (`validate.install_friendly_constructor`; A16). Signatures read well in `help()` / autocomplete: placeholder defaults are named `Unset` values (`layer=<default layer>`, `scena/_defaults.py`), no exported signature ends in `**kwargs` (typo-only catch-alls moved to `_call_hints`; forwarding kinds publish `__signature__`), multi-model shapes publish every model keyword as optional plus per-model `@overload`s (incl. `cls()` / `cls(center=…)`), and `scena/py.typed` ships (A24). Guia checked by `tools/guide/validate_guia.py` (catalog JS parses and holds the cards the checker reads, look-catalog thumbnails present / fresh (`make_guia_thumbs.py` renders them from each card's code), catalog params vs signatures, every `Parâmetros:` row and signature line vs the real keyword names, examples compile + run). Tests: `tests/test_api_robustness.py`, `tests/test_api_docs.py` |
| Property-based tests (Hypothesis) | **Experimental (2026-09-25)** — `tests/test_hyp_api.py` (Numbers rule on slots / verbs / constructors; "author errors only": a bad call raises `TypeError` / `ValueError` with a Scena message, never a Python builtin message; failed calls do not half-apply; pose algebra; `@=` link state machine), `tests/test_hyp_canvas.py` (registry state machine: construct / destroy / `layer =` / tags / clone / park / layer create-delete-clear / `on_destroy` spawns vs. a model of draw lists, painter order, groups, ids), `tests/test_hyp_events.py` (`@when` / `@on_change` model: frame batches, relays, destroyed sources, owner lifetime). Shared infra: `tests/hypothesis_support.py`; profiles via `SCENA_HYPOTHESIS_PROFILE` (`dev` / `ci` / `deep` / `replay`); how-to in `tests/README.txt`. Strategy, bug loop and findings (H1–H9, R1–R5, all fixed): [Testing Design.md](Testing%20Design.md#bug-catalogue) |
| Signature fuzz of the public surface | **Implemented (2026-09-26)** — `tests/test_hyp_surface.py` (helpers `tests/surface_support.py`): one generated test per export of `scena.__all__` — no-argument construction, junk in any one keyword is an author error that leaves no trace, unknown keywords name themselves, construct → remove returns every registry to baseline, every public method and setter on a destroyed Entity raises `DestroyedError` or leaves no trace, junk as the first argument of every author method (live instance; representatives for classes with no no-argument form) is an author error; coverage guards (a new export must be fuzzed or listed in `EXCLUDED`); canaries (H1 rollback, S9). Findings A3–A9, R8–R9: [Testing Design.md](Testing%20Design.md#a--api-surface) |
| `Concave` (a box with a scoop) | **Implemented (2026-10-14)** — Rect's models through the private `_RectBody` (not a `Rect`); `scoop=` (a named point, fixed) and `rim=` (a linkable pair); true-arc draw, exact pointer, convex-piece collision within 0.25 DU; sets swept pair by pair (CV1); level kind `"concave"` and editor tool U — [Shapes Design.md — Concave](Shapes%20Design.md#concave); Guia: [Concave](../docs/pt/guide/index.html#shape-concave); tests: `tests/test_concave.py` |
| Differential tests (fast vs slow paths) | **Implemented (2026-09-25)** — `tests/test_diff_pose.py`, `test_diff_reactive.py`, `test_diff_collision.py`, `test_diff_draw.py` (helpers `tests/diff_support.py`; every suite has canaries). Findings D1–D9 and R7, all fixed (D3: shapes no longer drop off the pose fast path once drawn or collidable) — [Testing Design.md](Testing%20Design.md#bug-catalogue) |
| System / sub-system tests | **Implemented (2026-09-25)** — real frames headless and deterministic via `ScenaFramework._simulate_frame` + raster draw (`tests/system_support.py`: `SystemWorld`, `census`, `zombies`, `Probe`, `kitchen_sink`). `tests/test_sys_lifetime.py` (destroy from every context, churn, drop-without-destroy, clone, park, modes, intern caches), `tests/test_sys_frame_order.py` (datapath order, handoffs, glitch-freedom, error recovery, `run()` drift guard), `tests/test_sys_hyp_world.py` (session state machine: no dead calls, no zombies, baseline census, collected actors), `tests/test_sys_hyp_scheduler.py`, `tests/test_sys_hyp_collision.py` (brute-force oracles; contacts at exact tangency are "either" — G2), `tests/test_sys_resting_contact.py` (resting / tile-seam contact vs frame pacing; F1 fixed by the resolve contact skin, F2 accepted limitation), `tests/test_sys_hyp_audio.py`, `tests/test_hyp_events.py` (`TestLinksUnderFrames`), opt-in `tests/test_sys_soak.py` (`SCENA_SOAK=1`). Findings S1–S10 (all fixed, regression tests in the owning files): [Testing Design.md — Bug catalogue](Testing%20Design.md#bug-catalogue) World machine extended (M4, 2026-09-26): shared registry model `tests/hyp_models.py`, layers / `layer =` / drain with an `on_destroy` spawner, Sprite hitbox parts, Text, checked link outcomes, collision-index and draw-list invariants, reach counters, system canaries; findings W2–W3 in [Testing Design.md](Testing%20Design.md#w--world-machine-extensions). |
| Author errors raise (no isolation) | **Implemented** — author hooks propagate with the original traceback; framework commits state first (fire / edge / leave consumed, mode transition + `destroy()` teardown complete); `run()` cleans up in `finally` (and forgets the terminated window, so a second `run()` in a REPL opens a new one: review 2026-10-09 S1-11); `@when` retires only on `DestroyedError` / `ReferenceError`; banner is SCENA WARNING only — [Actors Design.md — Protections](Actors%20Design.md#protections); tests: `tests/test_process.py`, `tests/test_reactive_edge_cases.py`, `tests/test_run_cleanup.py` |
