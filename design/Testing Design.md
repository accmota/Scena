# Testing Design

How Scena is tested, what the test harnesses offer, and what the bugs found so far
teach. Companion to [Scena Design.md](Scena%20Design.md). **Today's baseline**, not a
freeze. Commands and suite lists live in `tests/README.txt`; this file keeps the
strategy, the rules, and the bug catalogue.

## Use

| Need | Go to |
| --- | --- |
| Which kind of test to write | [Strategy](#strategy) |
| Which tests to run, and when | [Test tiers](#test-tiers) |
| Harness helpers (world reset, census, probe) | [Harness map](#harness-map) |
| A test found a bug — what now | [Bug loop](#bug-loop) (mandatory) |
| Whole programs against a spec written from the docs; a divergence to triage | [Program model tests](#program-model-tests) |
| Whole games written to be tested: side models inside the game, under a real load | [Game system tests](#game-system-tests) |
| A leak test fails but the engine looks right | [Harness pitfalls](#harness-pitfalls) |
| Do the smoke / example scripts still run? | `tests/test_scripts_run.py` (examples, quick) and `tests/test_smoke_scripts.py` (`scripts/smoke`, benches; `SLOW`) ([Recurring bug classes](#recurring-bug-classes): a script left on a retired spelling) |
| Is this bug a known class? | [Recurring bug classes](#recurring-bug-classes), [Bug catalogue](#bug-catalogue) |
| Why the rules are what they are | [Lessons learned](#lessons-learned) |
| Planning a new test: axes, oracle, invariants, layers | [Lessons for test planning](#lessons-for-test-planning) |
| Geometry hardening: axes, shadow oracle, sentinel, laws, fuzzer | [Geometry campaign](#geometry-campaign) |
| Bugs between subsystems: the seams, the matrices, what is still missing | [Interaction campaign](#interaction-campaign) |

Tests follow `tests/test_<area>.py`. The property / system suites are `test_hyp_*`,
`test_sys_*`, `test_diff_*` (fast vs slow paths). Regression tests for a
finding live in the **owning** `test_<area>.py`, not in the suite that found it.


# Strategy

Pick the test shape from where the bug would live, not from the feature.

| Shape | Use for | Tool | Examples |
| --- | --- | --- | --- |
| Unit | One contract, one call, a fixed example (the regression test of every finding) | `unittest` | most `test_<area>.py` |
| Property | One call over a whole input space: Numbers rule, "author errors only", round trips, algebra (`move_by` undoes), invariance (shift the world, contacts stay) | Hypothesis `@given` | `test_hyp_api.py`; geometry: `test_hyp_api.TestRotationGeometry`, `test_box.TestGridCoversBoxProperty`, `test_canvas.TestScreenWorldRoundTripProperty`, `test_sys_hyp_collision.TestTranslation`, `test_easing.TestChaseProperties` |
| State machine | **Sequences** and **failure paths**: lifecycle, registries, what a rejected or destroyed thing leaves behind | Hypothesis `RuleBasedStateMachine` + a small model | `test_hyp_canvas.py`, `test_hyp_events.py`, `test_sys_hyp_world.py` |
| System scenario | A cross-subsystem contract over real frames (destroy from every context, frame order, handoffs) | `unittest` + `SystemWorld` | `test_sys_lifetime.py`, `test_sys_frame_order.py` |
| Oracle / differential | An optimization vs a reference: brute force, the uncached path, the batched path, `force=True`, a model | Hypothesis + a twin (`diff_support.make_twins`), a config toggle, or an oracle | `test_sys_hyp_collision.py` (brute force), `test_diff_pose.py` (fast twin vs forced-slow twin), `test_diff_reactive.py` (configs + link model), `test_diff_collision.py` (cached vs uncached, closed form vs SAT, sweeps vs sampling), `test_diff_draw.py` (plain blit, cull, batching) |
| Program model | Whole author programs (widgets, input, physics, camera, acts) over many frames, against expectations written **from the docs** by spec-only authors; feature interactions; doc gaps | `program_support.ProgramRun` + per-frame author-level probes + a temporal check vocabulary; L3 oracles (`program_oracles`) | `test_prog_*.py` ([Program model tests](#program-model-tests)) |
| Game system | Many features at once under a real load (acts, modes, timers, collision, level files, audio, widgets, draw) over thousands of frames; white-box: the game carries its own side models | `game_support.Ledger` + side models inside the game; `game_harness` pilots, `run_game`, the L3 oracles, canaries | `test_game_*.py` ([Game system tests](#game-system-tests)) |
| Signature fuzz | The whole public surface against generic contracts: junk in any one keyword is an author error with no trace, unknown keywords name themselves, construct → remove returns to baseline, every verb on a destroyed actor raises `DestroyedError` or leaves no trace, junk as the first argument of every author method is an author error | Hypothesis, one generated test per export (`scena.__all__`) | `test_hyp_surface.py` |
| Structural guard | A whole bug class that is visible in the source or the surface (duplicate `def`, every export fuzzed, member allowlist, `float(finite(…))`, Entity-or-None as an `or` operand, a hook calling its dispatcher) | `unittest` over `ast` / `scena.__all__` | `test_entity_hooks.py`, `test_api_surface.py`, `test_api_robustness.TestNoFloatAroundFormulaValidators`; every family asked the same subclass questions (`test_subclass_parity.py`); every warning with both sides (`test_warning_contracts.py`) |
| Soak | Slow growth over many frames | opt-in (`SCENA_SOAK=1`) | `test_sys_soak.py` |

Rules of thumb:

- **Check what is left, not only what is returned.** After a rejected call, a
  destroy, or a teardown, compare a census of every registry with the baseline. Most
  lifetime bugs are invisible to the call's return value.
- **One contract per raise site.** Hypothesis reports one failure per exception type
  and line. A shared assertion across many verbs lets the first broken verb hide the
  rest — generate one test (or one `@invariant`) per contract.
- **Model small, check often.** The model holds only what the contract talks about
  (draw lists, join order, roster membership, `on_destroy` counts) and is checked after every step.
- **A generic oracle beats per-call expectations.** "The message is not a Python
  builtin message" (`hypothesis_support.leak_message`) checks "the error names the
  fix" across the whole API with no per-call knowledge.
- **Prove the test can fail.** A new property suite gets a canary: put a known bug
  back by monkeypatch and assert the suite fails.


# Harness map

| Module | Offers |
| --- | --- |
| `tests/hypothesis_support.py` | Profiles `dev` / `ci` / `deep` / `replay` (`SCENA_HYPOTHESIS_PROFILE`); example DB in `.hypothesis/`; `WorldTracker` / `fresh_world` (reset the process-wide singletons per example); `scrub_pools`; strategies (`junk`, `not_numbers`, `not_points`, `magnitudes`, `angles`, pool names `GROUP_POOL` / `ID_POOL` / `LAYER_POOL`); `AUTHOR_ERRORS`, `assert_author_error`, `call_as_author`, `leak_message`. |
| `tests/system_support.py` | `SystemWorld` / `system_world()` / `SystemTestCase`: real frames headless via `ScenaFramework._simulate_frame` (the body `run()` calls) + raster `_draw_frame` (post FX included: with no GL context the scene / FX render targets are raster surfaces); resets the act manager first (its teardown restores game rules: S4-8), then collision, bounds, cover, FX registries, clock, `ready` / `recently`, camera, post stack, and input (`reset_input_state`: keys, mouse, hover, press, widget focus, HUD cursor; X-life-8); pins pre-draw clocks to `clock.time`; quarantines (parks) live actors other modules left, resumed at teardown (`quarantine=False` defers it to `world.quarantine()`, for a census taken before parking: O4); gives back every `act.WORLD_SETTINGS` entry at teardown (O8); turns the GC freeze off (`gc_policy.set_gc_freeze(False)`: a frozen heap would hide a real leak from `census` / `assert_collected`; the policy itself is tested in `test_gc_freeze.py`). `census()` / `diff_census()` / `full_collect()`; `id_snapshot()` / `describe_new_ids()`; `zombies()`; `Probe` (`dead_calls()`); `assert_collected()` (referrer chain names the holder); `kitchen_sink()` (one actor wired into every subsystem); `tone()` (in-memory Sound). |
| `tests/diff_support.py` | `make_twins` / `force_slow` / `is_fast` (twin B via `_flag_pull_consumers`), `fingerprint` (pose + uncached collision prims read with cold engine readers), `assert_same` (tolerant structural diff naming the field), `assert_same_prims` (collision prims as a multiset: nearest-match pairing, never a raw-float sort — D10), `assert_fast` (**no vacuous pass**: fails if twin A left the fast path), `module_flag`, `assert_catches` (canary runner: patches a module name or a class, runs a fresh private copy of the target test under the `canary` profile). |
| `tests/surface_support.py` | Inventory of `scena.__all__` by family (`family_of`, `constructor_names`, `ctor_params`); `EXCLUDED` (name → reason; the coverage guard fails on an export that is neither fuzzed nor listed); `surface_census()` (`census()` + post stack, background items / base kind, HUD cursors, hitbox parts, cover, capture devices); `census_diff`; `CURSOR_KEYS`; `remove(obj)` (destroy / remove / `reset_base`); `settle()`. |
| `tests/script_harness.py` | Runs one script headless in its own process (`python tests/script_harness.py <script> [frames]`): `scena.run` → a loop of `ScenaFramework._simulate_frame` (no window, no draw), the script's directory as cwd, `sys.argv = [script]` (a bench takes its argparse defaults); prints `SCRIPT OK <frames>`. Used by `test_scripts_run.py` |
| `tools/guide/make_guia_thumbs.py` | Render probe for every look in the Guia catalogs (Visual, SpatialFx, Post, Backgrounds): each card's snippet runs in a `SystemWorld` (GPU render target behind a hidden window; `--cpu` / the tests use raster) at its scene's design size (`init` *after* the world: its reset puts the tests' 400×300 back — the same 400×300 whose center hid the SpatialFx default-placement bug, see `TestDefaultPlacementFollowsDesign`) and is compared with the bare scene. A look that draws nothing fails; `anim: true` on a card that does not change over 2 s fails. Style variants read their choices from the engine's own `ValueError` (a probe value), so the Guia's option list is checked against code (`check_variant_choices`). Tests: `tests/test_guia_thumbs.py` (snippet choice, input hash, page data, variants and Guia/code drift, reductions, gallery lift, scenes) and `tests/test_guia_thumbs_render.py` (real renders: guards, measured loops, SpatialFx framing and a tall blaze measuring tall, transients, an impact shake on the photo; ~30 s, in `SLOW`) |
| `tools/readme/make_readme_media.py` | Records the README's clips: each program (an example, or the README block after `<!-- clip: id -->`) runs in a `ProgramRun` with `draw=True` on a GPU target (the Guia's `_gpu_surface`; `--cpu` raster), its `init` size kept (the target is set *after* the program runs, like the Guia's `init`-after-world). A pilot drives input through `ProgramRun`'s queue (`hold` keys, `mouse`, `press`, `drag_slider`), so the clip shows play. A clip that does not change fails. Tests: `tests/test_readme.py` (README programs play 2 s without a warning; fragments use exported names / accepted keywords / existing global attributes — `st` is open; repo URLs resolve; no relative links (PyPI); clip ↔ marker ↔ CLIPS; design aspect; hash and status) |
| `tests/reactive_matrix_support.py` | Reactive matrix (also whole-object links, `run_whole_cell`, and cross-model copies in the test module): field × write path (`obj[f] @= lambda`, a cell, `part @= fn`) × read order (cold, self, all, all reversed) × construction model (`SUBJECTS`). Fields come from the `ScalarSlot` / `ContainerSlot` descriptors; the oracle is a plain-write twin read at the same moments (a Rect names its corners at first use). Checks I1 freshness, I5 unlink freezes, I6 two reads agree, I2 limits (`run_range_cell`: below / above / NaN). Used by `test_reactive_matrix.py` (in quick: the guards, canaries and the canary targets) and `test_reactive_matrix_cells.py` (`SLOW`: every cell) (guard: every exported reactive class has a subject or a `NOT_DRIVEN` reason; canaries for D12 / D13 / D14); complements `test_diff_link_write`. |
| `tests/test_hyp_reactive_matrix.py` | Hypothesis state machine over the same subjects: new subject (with a plain-write twin) / new cell / link / move cell / unlink / read some names on both sides in one order. Formulas are closures `a*cell.v + b`: the formula checker reads the lambda's source and refuses helpers such as `getattr`. A canary narrows the pool to Vec2 (`_Vec2Only`); the full pool is too diffuse for the canary profile's 150 examples. Where two plain writes do not commute but a link holds both, the twin re-puts every linked value until a pass changes nothing, the heading last (`_Pair.settle_twin`; it replaced `_reassert_heading` / `_reassert_pin`); a set that never settles fails (the engine must refuse it, GR19). Found D17, D18, GX13, GX20, GR18 and GR19. |
| `tests/test_heading_link.py` | Derived headings (a `p1,p2` / `p1,vec` / `p1,dx,dy` Line, Circle by rim, Ellipse by foci, Rect spine): the heading link and a link on a part its turn rewrites, or on a part the heading is measured from (found by writing each input and watching `angle`), are refused at the second `@=` and install nothing (D17, GR19); `_heading_driven_parts` equals what `rotate_by` refuses, both directions, so it cannot drift from the verb; every name read first is fresh after the source moves (D18). |
| `tests/test_write_path_guards.py` | Static guards (AST) on the write paths: raw `__dict__` stores of a field, `_dirty` writes, raw pose writes without a gate (`_pose_fast_ok` / `_requires_pull_invalidate` / `_link_source`), point readers that do not delegate to `_xy_of`. Each allowlist entry carries its reason; a stale entry fails too. Track A item 6; closes Track C item 5 (the write paths stay separate). |
| `tests/geometry_support.py` | Geometry contract registry: `KINDS` (every Graphic kind × constructor model, plus Box, built from a pose dict `{x, y, s, r}`); `point_parts` (every Point slot, `points[k]`, Text parts, `.box` named points), `vector_parts`, `scalar_parts`, `drawn` (the point set that fixes the paint), transform oracles (`turned` / `scaled` / `mirrored`), `safe` (a read that raises becomes a recorded `ReadError`), `settle` (run timed verbs). Used by `test_geometry_contract.py`; known violations in `geometry_known.py` (shrink-only). |
| `tests/program_support.py` | Program model harness: `ProgramRun(program, params, probes=)` runs `tests/programs/<name>.py` in a `SystemWorld` (`run()` replaced by the startup it does; `PARAMS` / `mark()` injected), feeds input through the real GLFW handlers **inside the frame's poll** (`key_down` / `press` / `move` / `scroll` / `set_cell`, `widget_center(label)`), samples author-level probes after every frame into a `Trace`, and on `close()` destroys what the program made (census back to `census_before`: `leftovers()`). Spec vocabulary: `Scenario`, step builders (`wait`, `click_widget`, `key`, `drag`, `set_cell`, `drive` — a pilot called before each frame, …), `Expect`, `serial(obj)` (per-run identity), checks (`always`, `never`, `at`, `at_end`, `eventually`, `steady`, `custom`). `program_test_case(...)` builds a test module. |
| `tests/program_oracles.py` | L3 oracles over whole programs: `replay`, `probe_neutral` (probes do not change the world), `dt_split` (dt/2, twice the frames), `reactive_config` (lazy + backstop vs eager + strong), `cull_pixels`, `teardown` (census + zombies). Tier C: `tier_c` re-runs a rewritten program (`TIER_C`: `rename_groups` — every group name suffixed; `reorder_defs` — runs of undecorated defs reversed; `rename_layers` — every author layer name suffixed) and requires the same world (`world_fingerprint` minus `made_at`). Metamorphic ([Interaction campaign](#interaction-campaign), class 3): `camera_moved` (the camera set before the first line through `ProgramRun.prelude`: the same trace minus the probes that read the camera, the same world), `time_scaled` (`clock.scale = k`, frames of `dt / k`: the same trace). |
| `tests/test_prog_invariance.py` | The metamorphic oracles over every program (exclusion tables with reasons: programs that place by the view or chase the mouse leave the camera oracle, a program that sets `clock.scale` leaves the time oracle), `rename_layers` on every program, canaries. One generated class per program (`TestPlatformer`: `test_camera_moved` / `test_time_scaled` / `test_rename_layers`), so the gate runs one job per program. `SLOW`, `SPLIT`. |
| `tests/program_coverage.py` | Which exports the programs reach: a `sys.monitoring` hook (PY_START / PY_RESUME; code outside `scena` is `DISABLE`d) records calls from a program's own code into `scena` (and the class of `self` / `cls`, since exported constructors are wrapped), mapped onto `scena.__all__`; global objects by name in the source. Guard: `test_program_coverage` (every export reached or in `PROGRAM_EXCLUDED` / a look family; `SLOW`). |
| `tests/program_ledger.py` | Open divergences (shrink-only), verdicts and cause codes. |
| `tests/game_support.py` | In-game instrumentation for `tests/games/` (light: no Hypothesis, no glfw): `Ledger` (`frame()` as the first line of `update`, reach counters, `check` / `equal` / `within` that **record** a failure with frame, time and scope, `invariant`, lifetimes by serial, `finish`, a plain-data `report()`, `digest()`), side models (`TimerModel`, `TweenModel`, `EdgeModel`, `ChangeModel`, `CoverModel`, `SoundModel`) and `geom` (closed-form intersections, point-in-shape, closest points, swept circles, Grid cells, `amp_db`). Tests: `test_game_support`. |
| `tests/test_subclass_parity.py` | Every exported `Entity` family subclassed in an author module and asked the same questions: a class keyword is applied or refused with an author error, `on_collide` methods get `(other, info)`, an own field that reads the object (a part too) dies without a warning, the subclass is collected. Tables with reasons: `NOT_SUBCLASSED`, `NO_CONTACT`, `NO_INK_LINK`, `KNOWN_SELF_READ` (shrink-only). |
| `tests/test_warning_contracts.py`, `tests/warning_sites.py`, `tests/warnsite_site/` | Every `warnings.warn` / `report_author_warning` site of `scena/` (by `ast`, module:qualname) has a `CONTRACTS` row: `fires=` (test module) or `untested=` reason, `silent=` (the test of its legitimate twin) or `twin=` reason; named tests must exist. `warning_sites.py` runs a tier with a recording `sitecustomize` and prints the rows the measurement contradicts (measurement only: the hook breaks stacklevel tests). |
| `tests/test_documented_patterns.py` | The Guia's patterns that sit next to a warning, each a small program in real frames with every warning recorded (director wave, ground flag, formula group, named tween refresh, loop-default formulas, collide method, SpatialFx class keywords, a HUD over an unlinked field, an act soundtrack). |
| `tests/game_harness.py` | The game drivers: `GAMES` (`GameSpec`: scenarios, probes, reach minimums, checks that must run, claimed exports, `spec_ns()` for `program_oracles`), pilots (`Pilot`, one class per game, deterministic, reading only the game's state), `run_game` (a `ProgramRun` with the `drive` step; reads `G.report()` before `close()`; records SCENA warnings), `problems` / `assert_game_clean`, `KNOWN` and `WARN_OK` (shrink-only, with reasons), `run_patched` / `assert_canary`. |
| `tests/test_sys_holders.py` | Holder × ender ([Interaction campaign](#interaction-campaign), class 2): `scan(target)` (every engine path to an object, with its reference kind), `HOLDERS` classification guard, `Wired` subject, gone enders (no strong path may remain; `KEEPS` with reasons), partial enders (`EXPECT` per documented contract; `UNSETTLED` shrink-only), canaries (a pointer manager or a pair list that keeps a destroyed body). ~0.4 s. |
| `tests/test_diff_pipeline.py` | Rendering composition pixel oracle ([Interaction campaign](#interaction-campaign), class 6): the brightest rastered pixel vs the transform chain, per display × camera × layer kind × post FX; canary. ~7 s. |
| `tests/test_sys_pointer_pipeline.py` | Pointer pipeline under every transform ([Interaction campaign](#interaction-campaign), class 5): `Rig` (display, camera, the three targets, a cursor the GLFW handlers read), the forward map as oracle, the untransformed pixel as the not-vacuous check, precedence, canary (a pointer map that drops the letterbox pad). ~0.3 s. |
| `tests/test_reactive_cross_matrix.py` | Reactive source × sink across subsystems ([Interaction campaign](#interaction-campaign), class 8): `SOURCES` (plain reader functions the formula checker follows, an install and a drive per source), `SINKS` (make a linked subject and a plain-write twin), three read points per frame × read order, the guard over every global on `scena.__all__`, `KNOWN` shrink-only, canary (a scalar link whose pull stores nothing). ~0.4 s. |
| `tests/test_sys_art_contact.py` | Art change × trigger phase × contact frame (class 12): `TRIGGERS`, the strike cells read at draw time as the oracle. ~0.2 s. |
| `tests/test_sys_error_sites.py` | Author error × callback site ([Interaction campaign](#interaction-campaign), class 7): `SITES` (every author callback armed to raise once), one recovery contract, `EXCUSED` and `KNOWN` tables, the coverage guard over `scena.__all__` and `on_*` attributes, canary (a batch left open). ~0.3 s. |
| `tests/test_sys_phase_matrix.py` | Phase × mutation × observer ([Interaction campaign](#interaction-campaign), class 1): `PhaseClock` (the frame body's phase entry points patched to name the current phase), `Cell` (X over Y under the pointer, every observer wired, the mutation armed in one phase of frame N), the frame-order rule as oracle, `NOT_OBSERVED` reasons, `SYNCHRONOUS` mutations, `KNOWN` shrink-only, canaries (a hover step or a collision step that never runs). ~1 s. |
| `tests/test_prog_isolation.py` | Program isolation ([Interaction campaign](#interaction-campaign), class 4): B after A reads like B alone for every ordered program pair (a chain at `dev`, every pair and every scenario at `ci`); B after a dirty process (`DIRTY`: live drawn shapes, shapes with work, a stale widget with B's own label, learned group names, a junk pointer with a held key, kept settings, every world setting); a run gives the process back (`process_snapshot`: world and kept settings, learned names, input, clock, census); `reset_world_settings` reaches every `WORLD_SETTINGS` row and the dirty cell changes every one; `KNOWN` shrink-only; canaries (a pointer reset dropped). One generated class per program read (`TestNaves`: `test_after_<A>`, `test_with_<cell>`, `test_given_back`), so the gate runs one job per program and B's alone traces are taken once in it. `SLOW`, `SPLIT`. |
| `tests/mutation_run.py`, `tests/mutation_ops.py`, `tests/mutant_site/` | Sampled mutation run (value metric): mutate engine lines a suite executes (`SCENA_MUTANT=<module>:<site>` through `sitecustomize`, `SCENA_HYPOTHESIS_DB=0`), compare kill sets of the program suite and the quick tier. `--pool-programs` fixes the sampled pool (the lines those programs execute), so two runs with one seed test the same mutants and the gain of added suites can be measured. From zsh, split a list held in a variable (`${=progs}`): an unquoted `$progs` is one argument, and the run stops at the control. Report in `.scena_test_runs/mutation/`. |
| `tests/graph_support.py` | `full_collect()` (gc until a pass frees nothing), `settled_graph_size(ss=None)` (graph node count once pending garbage is gone), `gc_paused()` (cyclic GC off for a block; `gc.collect()` still works). **Every graph count in the tests settles first** (guard: `test_count_baselines.TestGraphCountsAreSettled`; `run_with_collections(test, plant)` replays a test with garbage planted and a collection at each assert: O9). |
| `tests/source_support.py` | `iter_files(root, *suffixes, recursive=, skip_dirs=)`: sorted real files, skipping OS metadata (`is_junk`: AppleDouble `._*`, `.DS_Store`, `Thumbs.db`, `desktop.ini`), hidden dirs and `__pycache__`. **Every directory scan in `tests/` uses it** (guard: `test_platform_portability.TestSourceScansUseTheHelper`). |
| `tests/font_support.py` | `system_font_file()`: a monospace `.ttf` every OS installs (explicit candidate paths, no scan), for tests of `font="….ttf"` (WP4) |
| `tests/media_support.py` | `MEDIA` (`examples/media/`), `SMOKE` (`scripts/smoke/`), `media(*parts)` / `smoke(*parts)`: absolute path of a tracked media file, **asserting** it exists. Tests read real images, sheets, sounds and SVGs only through it, never with a skip-if-missing (MR2) |
| `tests/input_driver.py` | `input_driver(world)`: a mutable OS cursor and a sentinel window, events through `_handle_mouse_move` / `_handle_mouse_button` / `_handle_key` between steps (they land in the next frame, as poll events do). Used by `tests/test_input_frames.py` |
| `tests/hyp_models.py` | `RegistryModel`: placement (painter order per layer), group join order and liveness of tracked objects; `track` / `place` / `move` / `restack` / `join` / `leave` / `destroy` / `drain` / `forget_dead`; `check_draw_lists(registry)`, `check_groups(pool, group_of)`. Exact in `test_hyp_canvas.RegistryMachine`; in `test_sys_hyp_world.WorldMachine` (deaths happen inside frames) call `forget_dead` before checking. Holds strong references: `clear()` before a leak check. |
| `tests/geom_axes.py` | The geometry campaign's axes, read from the code: **K** kind × model × constructor row (`geometry_support.KINDS` + `EXTRA_KINDS`; `signature_reach` spies on the signature matcher), **B** base state (flipped, turned past a full turn, scaled, `MIN_SCALE`, degenerate, names crossed, cross-model copy, clone, mid-tween, parked, collidable, drawn), **W** warmth, **L** link configuration (field, part, whole, source of another link, chain), **R** read order, **X** execution twin (forced slow, caches dropped, inside a batch); `Reach` counters. Guard: `test_geom_axes` (every constructor row, every public pose verb and every axis value has a case or a reason). |
| `tests/covering.py` | `covering_array(axes, t, valid)`: deterministic, constraint-aware t-wise covering arrays (IPOG); `uncovered_tuples` checks one. 2-wise in `quick`, 3-wise in `gate`. |
| `tests/geom_shadow.py` | H1: the **affine shadow** of a subject (the composed map of its steps since the base state) and `run_cell` / `run_step`: after every step every point part, the drawn set, heading (full turns), scale, flip flags, hit test, collision prims, `.box` and the cull AABB must equal the shadow; a refused step changes nothing. Relational constraint cells (`CONSTRAINT_MAPS`) are affine too. Used by `test_geom_sequences`; known violations in `geom_campaign_known.SHADOW` (patterns, shrink-only). |
| `tests/geom_coverage.py` | Branch-coverage ledger (H9): runs suites under `coverage.py` (`branch=True`) over the geometry engine modules, one process per module; writes `.scena_test_runs/coverage/<tag>.json`, reports LOST arcs against the previous ledger and, with `--report`, the unreached branch arcs per function. Measurement only, never in a tier. |
| `tests/geom_sentinel.py` | H2 **sentinel**: runtime invariants checked test-side after every outermost engine entry point (pose verbs, flip / angle / scale setters, slot `__set__`, public `__setattr__`, `_takein`, `@=`, `unlink`, `clone`, `<<`, `absorb`, `collision.snapshot_shape`): I-fast, I-bare, I-graph, I-clean, I-heading, I-names, I-epoch, I-atomic. Hooks are `sys.monitoring` events on the code objects, so no frame is added (author sites and `stacklevel` warnings stay right) and nothing is replaced; reads are raw `__dict__` (no pull, no warm Derivate, no Entity built). `SCENA_SENTINEL=log` / `1`; `tests/sentinel_site/sitecustomize.py` installs it right after `import scena`; `run_tiers.py <tier> --sentinel` runs a tier under it and prints `report()`. Self-test: `test_geom_sentinel` (four canaries). |
| `tests/geom_laws.py` | H3 law table (`LAWS`): two programs on twin subjects that must read alike (algebra, timed = instant, spellings); `run_law`, `observe`, `differ` (Q6: points exactly, `angle` modulo 360 unless the law is about turns, flags only where the law says). Used by `test_geom_laws`; the fuzzer's rewrites reuse it. |
| `tests/fuzz/` | H10 **metamorphic fuzzer**: `geom_gen.py` (seeded JSON programs over the whole K pool, parameterized verbs, reads, clones, unlinks; `run` returns a trace and checks every call against its own affine shadow), `geom_rewrite.py` (stacked semantics-preserving rewrites from the law table, kept as one group per original op so traces stay aligned), `geom_fuzz.py` (triple oracle P vs P′ / shadow / sentinel; multi-process volume runner with `sys.monitoring` branch-coverage guidance; signatures with tags that map a divergence to a known finding; `--canary`; `--build-corpus`), `reduce.py` (ddmin to a `unittest` repro in `found/`), `corpus/` (a greedy coverage set replayed in `gate` by `test_fuzz_corpus`). |
| `tests/leftovers.py` | Module isolation: `module_sweep()` → `setUpModule, tearDownModule` that destroy every actor the module registered (roster keys after the module's mark, newest first; parts leave with their owners; `on_destroy` cleared; raises when one survives); `mark()` / `made_since()` / `sweep()`; `LeftoverCheck` (fails a module that leaves more than `LIMIT` = 50 live roster items). `run_tiers.py` runs every job through `--child` (`python -m unittest` plus one check after each module, not counted in "Ran N"). Tests: `test_leftovers.py`. |

Scena keeps **one** `ScenaFramework` per process. Every example and every system test
must undo what it did; an example that leaks state makes Hypothesis report *Flaky*
instead of the bug.


# Program model tests

Unit, property and system suites check one contract at a time. A **program model
test** checks a whole author program — the way authors write it — against what
the **documentation** says it must do. It finds what lives between features
(widgets × cells × groups × physics × camera over hundreds of frames) and, as
often, places where the docs do not say what the engine does.

**Pieces.** A program (`tests/programs/<name>.py`: `from scena import *`, top-level
code, `update`, callbacks, `run()`; `PARAMS.get(...)` for fuzzable choices). Two
specs (`<name>_spec_a.py`, `_spec_b.py`) written by **independent spec-only
authors** (agents) from the Guia, the tutorial, `examples/` and `design/` — never
`scena/` or `tests/` — before the engine runs (prompt:
`tests/programs/spec_agent_prompt.txt`). A spec declares author-level `PROBES`
(read after every frame), `SCENARIOS` (params, seed, input steps) and `EXPECT`
(each with a level, a doc citation, and `guess=True` when the docs did not
settle it). `tests/test_prog_<name>.py` = `program_test_case(...)`: one test
per spec scenario, L3 oracles on chosen scenarios, the ledger guard, canaries.

**Levels.** L0 exact discrete (counts, membership, events, cell values). L1
analytic with a stated tolerance (motion, rotation, zoom). L2 invariants and
bounds (inside the walls, no deep overlap, energy). L3 model-free
(`program_oracles`: replay, probe neutrality, dt split, reactive config twin,
cull pixels, teardown census). Physics is never mirrored step by step: a second
engine would be wrong in the same places; bounds and conservation are enough.

**Rules.**

- Spec authors list `FILES_READ` and the passages they found **silent or
  ambiguous**. The same gap reported by both authors is a SPEC-GAP even when
  no expectation diverges: settle what the engine does, write it into the Guia,
  pin it with a unit test in the owning module (PM1).
- Every divergence gets a verdict and a cause code (`tests/program_ledger.py`):
  BUG (bug loop, then generalize), SPEC-GAP (fix the docs), SURPRISE (engine
  right, a reasonable author expects otherwise: doc, warning, clearer error or
  an API change under [Compatibility and versions](Scena%20Design.md#compatibility-and-versions)),
  SPEC-ERROR / TOLERANCE (revise the spec with `revised="<CAUSE>: <why>"`).
  Only open items stay in `OPEN`; an entry that stops diverging fails the guard.
- A cause that recurs (3+) gets a systemic action (doc structure, an error
  pattern, a structural guard), not one more local fix.
- Spec authors never see the ledger or earlier findings: their independence is
  what makes a divergence informative.
- Value is measured, not assumed: canaries (`TestBouncingBallsCanaries`) prove
  a spec fails on a planted bug; `tests/mutation_run.py` compares the mutants the
  program suite kills with those the quick tier kills.
- Input is delivered inside `glfw.poll_events` of the next frame, through the
  real handlers (`_handle_key`, `_handle_mouse_button`, …); `click_widget` is a
  press frame then a release frame (also a Menu option by its text). Probes
  are author reads, so `probe_neutral` checks that reading does not change the
  world. Anchor on `t.press_frame("R")` / `release_frame`, not on the n-th
  input of a kind.

**Harness lessons (2026-10-08).** Each was a false divergence before it was a
rule:

- Run the program as its own `__main__` for the whole run (not `runpy.run_path`,
  which hands back a copy of the globals and restores `__main__`): a global the
  program rebinds is then what probes read, and art loaded during a frame
  resolves next to the script.
- One program per process in real use: reset what is process-wide between runs
  (keyboard and mouse state, group names learned for did-you-mean, background
  items, acts through `_reset_act_manager`). A SPACE from one program skipping
  the next program's title is how PM3 surfaced.
- Take the teardown census after the program's namespace is gone, collect
  before comparing worlds (`world_fingerprint`), and do not count the Points of
  a value Box (`canvas.game_view` builds one per read) as a program leak.
- Identity across frames is `program_support.serial(obj)`, never `id()`: ids
  are reused after a free and differ between runs (PM revisions of
  `cadeia_de_bolas`).
- A cell reads as an `Attribute`; probe values unwrap it.
- Restore every act-level world setting between runs (`act.WORLD_SETTINGS`
  snapshot at start, restore at close): `canvas.playfield` set by one run
  leaked into the next, unseen until a spec read it on the frame before the
  program set its own.
- A rewritten program (Tier C) runs from a temporary file, not under the
  original name: the `@=` formula checker parses the file on disk (PM14).
- A global object (`clock`, `mouse`) joins the dependency graph the first time
  any formula reads it, once per process: not a program leak.
- Start every run with no pointer (no position, hover target or press): the
  previous run's cursor hovered a toy that spawned under it on frame 1.
- Reset what another suite in the same process can leave behind: the mouse
  position (test_api_robustness leaves it at junk), the widget layout cursor
  (`ui.stack_reset()`: a program's widgets were placed at 1e200), the
  background base (restore the world setting; do not force the default).
  Each surfaced only when a program module ran after that suite in one
  process, as the deep tier's serial pass does.
- A run starts from the **framework defaults** of every world setting
  (`system_support.reset_world_settings`: camera, background base and
  fields, post effects, playfield, clock, resolve, default layer, paint
  defaults through `PaintState._reset_defaults`, the one call the canvas
  itself makes) and gives the process back at `close()`: the settings it
  found, the pointer where it was, the design size `init()` had. Found by
  `test_prog_isolation`'s dirty cells (2026-10-09): a playfield pad another
  test left changed which enemy shots survived in `naves`, and a snapshot
  restored at close before the census was counted as a background leftover.
  The census is taken first, then the pre-run settings come back.
- Take both censuses in the same quarantine state. `SystemWorld` parks the
  live actors other modules left (`active = False`) and teardown resumes them;
  `ProgramRun` builds its world with `quarantine=False`, takes `census_before`,
  then calls `world.quarantine()`. With the census taken after parking, every
  parked drawn actor read as the program's leak (O4).

**Value so far.** Seven Tier A programs (14 specs, ~520 expectations) and the
Tier B composer (12 behaviours, 1000 compositions at `deep`) found three engine
bugs (PM3, PM7, PM8), one API question settled by documenting it (PM5) and
seven doc gaps (PM1, PM4, PM6, PM9, PM10 and the timer rule in PM8); 12 spec revisions, each with a cause
(INTUITION 4, SPEC-LOGIC 4, MISREAD 1, HARNESS 1, DOC-AMBIG 1, DOC-SILENT 1).
On random mutants of engine lines the programs execute, the bouncing-balls
suite killed 11 of 39 and the quick tier 36, none killed by the program alone.
Re-measured with all eleven programs and the composer (2026-10-08, 30 mutants
over ten engine modules, a control run first): programs 10, quick tier 20,
programs only 0, neither 10. Mutants measure local contracts, where the unit
suites are strong; the program tests pay off on interaction, timing,
isolation and documentation findings no mutant models (PM3, PM7, PM8, PM11,
PM12, PM14 and the doc gaps). A mutation run without the control is not
evidence: an earlier run counted three "program-only" kills that were a spec
failing on its own while the run went (`mutation_run` now refuses to start
unless both suites pass unmutated).


# Game system tests

A program model test is black-box: the program is an author's, the spec is
written from the docs by someone who never saw the engine. A **game system
test** is white-box: a whole game written **to be tested**, carrying its own
instrumentation and side models, run for thousands of frames under a real load
(many features at once: acts, modes, timers, collision, a level file, audio,
widgets, posts, draw). It finds what lives between features when they all run
together, and checks each one against an independent model while they do.
Games are not examples or tutorials, and are never copied into either.

**Pieces.**

- `tests/games/<name>.py` (with data files next to it, `caverna.json`): `from
  scena import *` like an author, plus `from game_support import ...`.
  `# harness: cwd=examples/media` on the first line: art resolves from there
  (the media guards read the header). `PARAMS.get(...)` for sizes, god mode,
  speeds; seeded `random` only.
- `tests/game_support.py`: the `Ledger` (`G`) and the side models. The game
  calls `G.frame()` as the first line of `update`, `G.check(...)` /
  `G.equal(...)` where it knows the answer, `G.born` / `G.died` (from
  `on_destroy`), `G.event(...)` for reach, and the models' hooks where it
  schedules, fires, cancels.
- `tests/game_harness.py`: `GAMES` (scenarios, probes, reach minimums, checks
  that must run, claims), one pilot class per game, `run_game`, `problems`,
  canary helpers.
- Drivers flat in `tests/`: `test_game_<name>.py` (quick: a short scripted run,
  a static run, teardown) and `test_game_<name>_deep.py` (`SLOW` + `SPLIT`: the
  long run, L3 oracles, random pilots, canaries); `test_game_support.py` (the
  oracles' own tests); `test_game_coverage.py` (`SLOW`: each game reaches the
  exports it claims, through `program_coverage.collect_runs`). Not
  `tests/programs/` (doc-spec'd, black-box: the isolation, invariance and
  coverage tables assume specs there) and not `test_prog_*` (those tables
  would need rows).

**Rules.**

- **An independent source.** A model never calls the engine function it
  checks. Its truth is a Guia sentence (quoted in its docstring), closed-form
  math (`geom`), or the game's own bookkeeping (what it spawned, scored,
  destroyed). A model built from the engine's own answer agrees with every bug.
- **Record, never raise.** A check fails inside engine callbacks; raising there
  would end the frame as an author error and hide the rest of the run. Checks
  record frame, time, scope and context; the driver fails the test with the
  list. `SCENA_GAME_CHECKS=raise` raises at the site, for a debugger.
- **Plain data out, serials not ids.** `report()` holds no engine object (read
  before `close()`, so the census sees nothing of the game); models hold handles
  through closures and drop them in `release()` (`Handle` has no weakref slot).
- **No vacuous pass.** Every scenario names reach minimums (`G.event` /
  `G.hit` counters: the boss died, the lift carried the rider, the act changed)
  and the checks that must have run at least once; `test_game_coverage` holds
  each game to its `claims`.
- **The phase rule for reactive sources.** Models sample at `G.frame()` (frame
  step 2). A value written by input (a widget, a click callback) lands in the
  poll **before** that sample; one written in update, collision or a callback
  lands after. So `EdgeModel` / `ChangeModel` settle an edge first seen at
  frame N one frame later: one fire in frame N-1 or N. `TimerModel` takes
  `early=` (made in update: counts that frame's `dt`; made later in the frame:
  counts from the next).
- **Pilots are deterministic** and read only the game's state and their own
  counters (`drive(factory, frames)`: `pilot(run)` before each frame, input
  through the real handlers). A pilot's generator holds the namespace: the
  harness releases pilots before `close()`.
- **Draw at checkpoints only.** `run.step(1, dt=0.0, draw=True)` and a pixel
  read: the drawing surface is re-pointed first (HV1).
- **`KNOWN` is shrink-only** (`game_harness.KNOWN`, `WARN_OK`): an entry
  carries its reason and a finding ID; an entry no run hits fails
  (`known_still_fail`).
- **Prove the models can fail.** Each game's deep driver plants known bugs by
  `mock.patch` and requires the named check to fail (`assert_canary`): PM8's
  timer rounding back, a custom ease ignored, CCD off, AC3 and AC6 put back
  (Armada); PM8 through a plain `every`, a Level angle negated, `deadzone`
  and `recently` broken, `floor_below` off (Caverna); `intersections` dropping a point, the
  hover step skipped, `amp_db` skewed, a stale pull (Oficina).

**L3 oracles.** `spec_ns()` gives `program_oracles` what it reads, so replay,
`probe_neutral`, `dt_split`, `reactive_config`, `teardown`, `tier_c`,
`camera_moved` and `time_scaled` run unchanged. Exclusions carry reasons:
`dt_split` on continuous probes only, with tolerances (input lands half a
coarse frame earlier); `time_scaled` not on Armada (the cover runs on
presentation time); `camera_moved` on Oficina only (the others place by the
view).

**The three games (2026-10-10).**

| Game | Load | Models |
| --- | --- | --- |
| Armada (shooter) | Acts title → hangar → sector → arena → end through one iris; sheet atlas and clip, `collide` / `_stay` / `_exit`, hitbox parts and a weak point, `Collider`, modes with `race` / `parallel` / `until_empty`, named `every` / `after`, a custom-ease tween, Jet / Portal / Orb / Sparks / Fire, four posts, widgets and a pause `Menu`, music crossfade and handle effects | population, shot conservation, timers, tween (exact), edges / changes, act and cover, `ready` cadence, CCD no-tunnel (swept circles), sounds |
| Caverna (platformer) | `caverna.json` Level (platforms, a ramp, a polygon, tracks, points, images), `resolve`, slopes, coyote time and a jump buffer, a lift by `move_along` carrying its rider, camera deadzone + chase, parallax, Endless, clips, History checkpoints, death → iris → respawn | Level vs plain JSON, grounded ⇔ geometry, rider displacement, coyote / buffer twin, camera bound, parallax view, Endless slot determinism, clip frame formula |
| Oficina (reactive workshop) | Grid board, drag / drop / hover / click, State cells and `@=` chains, group formulas, every widget kind, materials (Fill / Stroke / Paint, Gradient / Texture), a laser against shapes, raycast / `query_point`, `Collider`, Track probe, baked fx chain, spectrum, Microphone (NULL backend), pixel checks | a plain-Python reactive twin, widget mappings, pointer geometry, laser closed forms, audio stack, pixels at checkpoints |

Together they reach 123 of 249 exports, 28 that no program reaches (Level,
Microphone, the audio effects, SpatialFx, Fill / Stroke / Paint, Chroma / Wash
/ Crt / Pixelate …).

**Value so far.** Writing and running the three games found eight engine bugs
(AC1, AC3, AC6–AC9, AC11, AC13; AC12 came from an existing suite during the same work; [AC](#ac--game-system-tests-2026-10-10)), a
harness vacuity (HV1: every `ProgramRun` draw painted a surface nobody read,
so `cull_pixels` compared two blank frames), a doc sentence that over-promised
(AC4), and three API questions (AC2, AC5, AC10). Most were met by the game's
own code before any model ran: a pattern the Guia shows, used in a real game,
broke (a coyote flag that reads its owner, a formula group declared with `@=`,
an `on_collide` method, a long `until_empty` wave, a named tween refreshed).


# Geometry campaign

A white-box campaign (2026-10-08) over the whole geometric model before
release: every Shape kind and model, Box, Anchor, Vec2, Sprite / Svg, Text,
Track (with `reversed()` views), Hitbox parts and collision frames. It applies
[Lessons for test planning](#lessons-for-test-planning) to the cross-product
the reactive campaign and the graphics review sampled: field × write path ×
what was read before × construction model × link kind × base state × verb
sequence. Cadence: discover first (each harness logs into a shrink-only known
list), then fix by class, one root cause per change, each with an A/B.

**Axes** (`geom_axes.py`), each read from the code: K kind × model ×
constructor row, B base state, W warmth, L link configuration, V step,
R read order, X execution twin. The full product is far too large; a 2-wise
covering array (`covering.py`) runs in `quick`, a 2-wise array over every
kind plus a 3-wise array over the family-level axes in `gate`, and seeded
random cells in `deep`. Reach counters assert every axis value ran.

**Oracles with no model of their own:**

| Harness | Oracle | Module |
| --- | --- | --- |
| H1 shadow | the composed affine map of the steps since the base state (a constraint cell's own map on a relational shape); refusals change nothing | `test_geom_sequences` |
| H7 structure | the code against itself: one `update()` per verb, model adopted before a copy writes, one Defining set per model (tables, `_defining_names_for`, constructors, cross-model copies), timed verbs refuse where instant ones do, no swallowed errors in pose verbs, the relational verb table (doc ↔ `CONTRACT_EXEMPT` ↔ shadow ↔ behaviour) | `test_geom_structure` |
| Probes | one deterministic probe per drift candidate and per finding, written from the contract; known-broken probes listed shrink-only (`geom_campaign_known.PROBES`) | `test_geom_probes` |
| H2 sentinel | invariants on raw state after every outermost engine call (the whole suite becomes a probe: `run_tiers.py <tier> --sentinel`) | `test_geom_sentinel` (canaries), `geom_sentinel` |
| H3 laws | two roads, one shape: the law table over kind × base × warmth × execution; copy and clone commute with every verb (act then copy); a verb on the source of `d @= s` reaches `d`; a clone made after any history acts like its source (bisimulation); a shape built at `p` then moved / scaled / turned is the shape built there | `test_geom_laws` |
| H4 influence | each Defining input and pose quantity changed on a cold twin and on a warm one (every cache filled): the warm reads equal the cold ones; the collision key changes whenever the prims do; every Defining input moves something | `test_geom_influence` |
| H5 twins | one random step program, six executions (normal, forced slow, caches dropped, in a batch, in a frame, eager graph): the same fingerprint after every step | `test_geom_twins` |
| H8 values | the geometric edges (0, −0.0, ±180, 360k, 1e6, `MIN_SCALE`) and `test_value_validation`'s junk pools on every path (`=`, a link, a batch, `part << xy`): every path refuses alike (an author error that changes nothing) or stores alike; a link whose source turns bad refuses at the read, keeps the raw state, and follows again; a refusal inside a batch or a scheduled callback changes nothing | `test_geom_values` |
| H10 fuzzer | stacked laws at volume: a program P and P′ (P rewritten by laws) must read alike after every original operation, P must match its shadow, and the sentinel must hold through both | `tests/fuzz/`, `test_fuzz_corpus` |
| H6 families | Sprite, Svg and Text (centred and anchored) are reactive-matrix subjects; an Anchor refuses every inbound link and keeps nothing; Sprite / Text / Track constructor keywords link; sheet-anchored sprites join K; a sprite's art (rendered) and prims stay inside `.box`; hitbox parts follow their host's composed map; a new string keeps a caption's anchor and its links; a `reversed()` view reads its host backwards after every verb | `test_geom_families`, `test_reactive_matrix`, `test_ctor_links` |

**Contract decisions the oracles encode** (written into the owning docs first):
Q1 a flip applies `180 − θ` / `−θ` to the unwrapped heading on every kind
(Shapes Design, Conventions); Q2 a finished timed `rotate_to` stores the
target (Actors Design, Canvas Design); Q3b a relational shape that loses its
relation becomes its free twin (Shapes Design); Q4 a flip does not mirror a
running rotation (Actors Design); Q5 State refuses a function on `=`
(Reactive Design); Q6 a law compares drawn geometry and points exactly,
`angle` modulo 360 unless the law is about the turn count, and flip flags only
in laws about them.

**Baselines (phase 0, on `1ec7001`):** branch arcs reached by the existing
geometry and reactive suites (`geom_coverage.py`): shapes 1610 / 2028, entity
462 / 658, state 794 / 1222, box 145 / 166, sprite 973 / 1334, text 205 / 278,
track 432 / 598, hitbox 126 / 248, geom 36 / 236, scenamath 59 / 154. Deleted
calls (`mutation_run.py --ops call`, 80 sampled sites in shapes / state / box /
entity, seed 1): the geometry suites kill 50, 30 survive.

**Phase 2 (sentinel).** `quick` runs green under it (6 590 tests, except the
modules in `run_tiers.SENTINEL_EXCLUDE`;
`python tests/run_tiers.py quick --sentinel`, ~2.5 min wall). Building it
taught three rules of its own: a check runs only for a call made from outside
the engine (read paths are not hooked, so an engine write inside a pull would
look outermost; the scheduler and the frame loop count as outside), a check
never runs inside a check, and a refused call is compared only on nodes that
were settled before it (a pull may still refresh a dirty, linked, pull-owned or
lazily laid-out part; a first name freeze is a read). Its findings: GR17-link
(I-heading), GX7 (I-bare), GX11 (I-atomic). Two hits were the harness: dangling
graph ids after `program_oracles.reactive_config` swaps the scena system
mid-process (a module singleton keeps its old node id), and a canary's planted
state reaching the shared log through a later teardown (canary runs now log in
memory only).

**Phases 3–5 (shadow, laws, twins, influence).** The laws found GX9, GX10 and
GX12 and re-found Q2 and GX3; every other law holds on every kind. The twins
agree on every kind under every execution, and the influence matrix is clean:
every geometry cache follows every input it reads (its canary, a collision
key keyed on nothing, fires). Oracle lessons: a law between twins cannot see a
bug both twins share (a scale about the origin still inverts), so each law
canary breaks the law itself; corner names freeze at first use, so a law that
copies or links compares against the source or freezes both twins first;
`center =` is a field write (it keeps a rim-placed Circle's
`perimeter_point`), a move only where the center is the sole point input.

**Phase 5b (family parity, H6).** The new subjects shifted the draws of
`test_hyp_reactive_matrix`, which then found GX13 (an anchored caption takes
links on its anchor and its center) and an oracle that was stricter than the
contract: on a model whose heading is derived (a rim-placed Circle), `angle`
and `center` do not commute as writes, and a linked heading holds its formula
whichever source moves, so the plain-write twin re-applies a linked derived
heading after any other write (then `_reassert_heading`; now `_Pair.settle_twin`). Sprites with a sheet
anchor hold the shadow, the laws and the influence matrix; the rendered art
stays inside `.box`; hitbox parts follow their host.

**Phase 6 (value edges, then the fuzzer).** H8 found GX14 and GX15. The
fuzzer runs about 55 programs a second on 8 workers (13 000 in four
minutes); each canary is found within 1–6 programs (a rotation-only flip,
a scale that forgets its pivot, a 0.1 % fast-path translate error, headings
that lose their turns). It found GX16 and GX17 and re-found GX2, GX3, GX4,
GX5 and Q3b under other signatures (its tags map them back). Lessons from
building it, each an oracle that was wrong first:

- The sentinel's I-clean recompute changed the stores it checked, so a run
  under the sentinel diverged from one without it: a check that runs engine
  code must put back every value it wrote (coordinates, slot scalars, pose
  stores) and nothing else (restoring flags tripped I-fast).
- A cold twin (observed only through cold readers) is the only way to keep
  the pose fast path under a fuzzer: a shadow or a public read puts the
  subject on the slow path for good, and the fast-path canary went unseen.
  Cold reads compare only free subjects (a linked one holds values its next
  pull refreshes) and read a `reversed()` view through its host.
- Twin pools must fall back alike when a base state or a link does not
  apply, or the two sides build different subjects.
- A rewrite that mutates the program before it is accepted leaks into P′
  (two reorders, one excused row); an OBB is the same box turned by π; a
  refused factor cannot be split into one that runs.

**Phase 7 (fix waves; one root cause per fix, each with the bug loop and an
A/B of its hot rows).** Wave 1: GX8, GX9, GX11, GX12, GX13 and Q5 (the
copy doors, placement links, State callables). Wave 2, headings under flips:
Q1 (the spine mirrors its unwrapped heading), GX1, GX2, GX3 and GR17-link
(a link pull on a Defining `angle` publishes `_rotation`, as `=` does).
Dropping the broad `I-heading | *` sentinel pattern uncovered GX18 and GX19,
fixed in the same wave. The A/B on the flip rows needed compensation, and got
more: `Shape._mirror_geometry` gated the scalar parts twice and looked its
points up through `getattr` (Circle, Ellipse and Polygon flips are now 11–24 %
faster), and a `ScalarAnchor` looks its slot up once, not on every pull.
Lessons:

- A store that a verb sets is half the fix when a cached Derivate reads it:
  a verb that moves no point (a zero-length segment) recomputes nothing, so
  the reader keeps its old value. A probe must read the value once before
  the verb, or the cache is cold and the bug hides.
- A gate exemption reasons about one write; the verb may make others. The
  pivot exemption is right for the points a mirror leaves in place, and
  wrong for the heading it turns where a relation owns the heading.
- A broad known pattern hides the next finding of the same invariant: list
  the finding's own signature (`I-heading | Rect | Container.__lshift__`),
  not the invariant.
- An observer must put back what it adds, not only what it changes: I-clean
  restored the stores it found and left the cold slots its recompute filled
  (a RegularPolygon's `side`), which a raw reader of the pose key then saw.
  Tests that assert engine internals (mark_dirty counts, cold Derivates) do
  not run under the sentinel (`run_tiers.SENTINEL_EXCLUDE`, with reasons).
- A harness that runs inside `@given` must not import a test module: the
  import builds that module's `@given` tests, and Hypothesis fails the
  nested-given health check (shared helpers live in `geometry_support`).
- The shadow machine settled the other subjects' turns before a timed step
  that then did not run (a parked subject); it now settles them only when
  the clock moved.
- `perf_geometry.py --ab HEAD --tree COPY` measures the noise floor (two
  copies of one tree): about ±2 % per row, so a one-run delta under 3 % is
  not a finding until it repeats.

Wave 3, timed verbs: GX4, GX17 (`TestTimedVerbsGateLikeInstant` holds in
both directions; `GATE_PARITY` is empty), GX16, Q2 (shape and camera) and
GX6. Every kind's scale checks moved into one `_scale_gate` that the instant
`scale_by` and the timed probe share, so the two cannot drift; the instant
verb skips it when nothing in the tree is linked, which made `scale_by` 6–27 %
faster. The move probe used to be `_move_to` to the current pivot: on a
sheet-anchored Sprite that placed the center on the art frame, a jump at the
call that the law (end state only) could not see. Lessons:

- A probe that calls the instant verb with "no change" is not a probe: the
  verb returns before its gate (`_move_to` to where it is, `scale_by(1)`), or
  is not a no-op on every kind (a sheet sprite's center is not its pivot).
  Share the gate itself.
- A claim must cover what the motion writes, from the same gate, or a link
  on an unclaimed written part is accepted and the motion raises later.

Wave 4, values and caches: GX14, GX15, GX5, GX7, GX10. Removing the
broad VALUES patterns showed two oracle and engine edges: a link pull that
clamps a negative size where `=` refuses is the contract (the oracle now
allows it), and destroying a shape whose link source holds a refused value
raised from the final pull of `unlink()` (fixed: the last good value stays).
The value harness also met `True == 1.0`: a cell holding `True` kept it
through `= 1.0`. Lessons:

- A broad known pattern (`* | * | link vs = | ok vs refused`) hid a
  contract difference and a bug under one key; the harness keeps the last
  value per key, so a pattern can be satisfied by the wrong cell.
- Equality is not "unchanged" across types that compare equal: a flag and a
  number, like a list and a new list (E7).

Wave 5, relations: Q3b. One hook does it for every door: `Container.unlink`
tells the shape a part's link went, and a link that read the reference turns
the shape into its free twin, unlinking the rest of the relation with it.
The first version also ran while the relational shape itself was being
destroyed (its teardown unlinks its parts) and raised from `destroy()`; the
hook now leaves a destroyed shape alone. The sentinel then found the free
twin of a tangent line with a linked `at_angle` holding the old heading in
its pose store (the pull moved the heading, not the store); the conversion
publishes the store when `angle` becomes an input.

**Phase 8 (re-measure, 2026-10-09).** Every known list is empty but one
harness entry (`SENTINEL` `I-graph`: a test swaps the scena system
mid-process). Branch arcs reached (`geom_coverage.py --campaign`), phase 0 →
now: shapes 1610 / 2028 → 1726 / 2146, entity 462 / 658 → 466 / 660, state
794 / 1222 → 814 / 1242, text 205 / 278 → 209 / 282, track 432 / 598 → 435 /
596, scenamath 59 / 154 → 63 / 158; box, sprite, hitbox and geom unchanged.
The harnesses widen combinations (state × path × history), which a branch
ledger barely sees. Deleted calls (`mutation_run.py --ops call`, seed 1, one
pool for both runs: `--pool-programs` = the phase-0 geometry suites, 80 of
1 312 sites in shapes / state / box / entity): the phase-0 suites kill 53,
with the campaign's modules 55. The quick tier then killed 10 of the 25
survivors; of the 15 it missed, four were untested refusals (Box's turn gate,
`Blank.rotate_to(nan)`, `Anchor.draggable = "yes"`, RegularPolygon's timed
scale with a linked `radius`), now pinned, two are equivalent (a later write
refuses anyway: Circle's turn gate on `angle`; the cycle check runs twice),
and nine are bookkeeping, caches, warm-up flags or message text, not
triaged one by one. The RegularPolygon survivor showed the gate-parity guard
linked one picked field per kind; it now links every Defining part alone
(`geom_axes.linkable_parts`), which found that an anchored Text's timed
turn or scale with a linked pin was accepted and raised from a tick (its
pin is now in `_parts_written_by_wheel_rotate` and `Text._scale_gate`).
Two node-count tests were order-dependent under the mutation control (a
collection mid-test); they collect before counting.

**Phase 1 findings (static sweep and probes; H1 found the first ones while it
was being built).** Catalogue [GX](#gx--geometry-campaign-2026-10-08). The
drift list's suspects, triaged: the `_scalar_bare_ok` seed without the
`_pull_owner` check is a real bug (GX7); an anchor type swap on a cross-model
copy keeps outside `angle` readers fresh (cleared, probe kept); a reversed
Track view's own `_rotation` is a dead store the collision key never reads
(cleared, probe kept); every heading reader agrees on every kind after every
verb, except through a link (GR17-link; fixed in wave 2); `Box._takein_impl` copies a
linked source's value, not its link (cleared). The Defining tables, the
constructors and every cross-model copy name one Defining set per model.


# Interaction campaign

Four campaigns found their bugs in combinations inside one subsystem
([Lessons for test planning](#lessons-for-test-planning)). Across subsystems the
suite samples: `test_sys_lifetime` (destroy from every context on `kitchen_sink`),
`test_sys_frame_order` (four handoffs), `test_sys_hyp_world` (random sessions,
registry invariants), `test_act` (a change from seven contexts), the program model,
`test_prog_compose` (behaviours that share nothing: non-interference, not
interaction), `test_driver_composition` (ten pose drivers pairwise). A verification
pass over twelve candidate seams (2026-10-09) found two with no test and eight with
hand-picked cells and no guard. The campaign applies the same discipline to the seams:

1. **Enumerate the seam from the code.** Subsystems meet on the frame (phases of
   `_simulate_frame` / `_draw_frame`), the Entity (every engine container that holds
   one), shared fields (pose, `visible`, `layer`, `active`, groups, world settings)
   and transforms (window scale, letterbox, camera, layer response). A class is a
   product of two such axes, each read from a source of truth.
2. **Cover pairwise, guard the axes** (`covering.py`; a guard fails when a new phase,
   holder, driver, source or export has no cell and no reason).
3. **Oracles with no model**: metamorphic invariance over a whole program (camera
   moved, time scaled, layers renamed, another program first → the same trace); a twin
   with the subsystem absent; a transition observed from every later phase
   (`PhaseRig`); the same event through every door.
4. Three layers per class (matrix in `quick`, rules on the existing `WorldMachine`,
   a static guard); reach counters and a canary per catalogued interaction bug;
   real frames, the author's `dt`, a predecessor in the process; an unknown cell is
   a SPEC-GAP for the owning doc first.

| # | Class | Seam | Status |
| --- | --- | --- | --- |
| 1 | Phase × mutation × observer | a write in one frame phase, seen by every later phase of that frame and the next | **done** (`test_sys_phase_matrix`, see below) |
| 2 | Holder × ender | every engine attribute that can reference an Entity × every way it ends or moves (destroy, park, `layer =`, clear, untag, `change_act` mid-hover / drag / focus) | **done** (`test_sys_holders`, HD1–HD5 fixed, see below) |
| 3 | Metamorphic program oracles | camera moved, time scaled, layers renamed → the same world trace | **done** (`program_oracles.camera_moved` / `time_scaled` / `rename_layers`, `test_prog_invariance`, see below) |
| 4 | Program order pairs and dirty predecessors | B after A, B after a test module's leftovers, a run gives the process back | **done** (`test_prog_isolation`, see below) |
| 5 | Pointer pipeline under every transform | one OS pixel through window scale × letterbox × camera × layer kind to the handler that fires | **done** (`test_sys_pointer_pipeline`, 54 cells + precedence, see below) |
| 6 | Rendering composition pixel oracle | a bright actor at the predicted screen pixel across camera × layer response × post FX × scale × letterbox | **done** (`test_diff_pipeline`, 108 cells, see below) |
| 7 | Author error × callback site | every dispatcher that runs author code: the frame finishes, the next is clean | **done** (`test_sys_error_sites`, 31 sites, see below) |
| 8 | Reactive source × sink across subsystems | engine-owned sources (`mouse`, `clock`, `keyp`, views, boxes, a widget's cell) × sinks in other subsystems | **done** (`test_reactive_cross_matrix`; RX1 found and fixed, see below) |
| 9 | Pose writers beyond `DRIVERS` | `confine`, a leave teleport, an Endless piece, a Level item, a timed camera | **closed, no cell** (instant writes, not drivers: see below) |
| 10 | Parallax silent skips | `@leave_playfield` skips parallax items silently; `on_hover` has no parallax refusal | **done** (`test_parallax_layers`, one contract tightened, one pinned) |
| 12 | Art change × trigger phase × contact frame | mostly covered; one small matrix | **done** (`test_sys_art_contact`, six triggers) |

**Class 6 (2026-10-09).** `test_diff_pipeline`: one white square on black
on a world layer, a parallax layer (`pan_response` 0.4) or `ui`, under three
displays × six cameras × post FX off / on (a `Vignette`), rastered through
the real draw; the brightest pixel must sit where the engine's own maps put
it (`world_to_view_coords`, `_layer_partial_matrix`, the design point, then
`pad + view_scale · flipY`). Every cell agrees within 3 px. Canary: a scene
drawn without the letterbox offset.

**Class 5 (2026-10-09).** `test_sys_pointer_pipeline`: three displays
(window scale and letterbox pads) × six cameras (identity, zoom, pan,
rotation, origin, all three) × three targets (a world shape, a shape on
`ui`, a Button) × three verbs (hover, click, drag), the pixel computed with
the engine's own forward map and delivered through the real GLFW handlers;
the verdict is the handler that fires (a drag of 40 px moves a world shape
by the world delta the inverse map gives), plus a not-vacuous check (the
pixel computed without the transform misses) and widget-over-shape
precedence under every camera. Every cell agrees. Harness lesson: cells in
one test method must destroy their targets, or a later cell's pointer lands
on an earlier cell's identical shape and logs into the wrong rig (the first
run reported 39 misses that were the harness).

**Class 8 (2026-10-09).** `test_reactive_cross_matrix`: six engine-owned
sources (`mouse`, `clock.time`, `keyp(...)`, `canvas.game_view`, a state
cell, another actor's part; `group["…"].box` is excused: the formula checker
refuses a formula that reads a group) × five sinks in other subsystems (a
shape's centre and radius, a caption's string and centre, a SpatialFx
placement; appearance knobs refuse `@=` by design and widgets bind a cell),
each read first or second against a plain-write twin written with the
source as it reads now, at three points of every frame. Every cell agreed
except one source: **RX1** — `canvas.game_view` is a measured Box off the
graph, so a formula that read only it never re-evaluated (the no-sources
guard was satisfied by the throwaway Box). Fixed the same day (user decision):
`canvas` is a formula source, and a deferred tree met in a chain is a value
([RX](#rx--reactive-sources-across-subsystems-interaction-campaign-class-8-2026-10-09)).
Harness lessons: formulas
must be plain (`pair()[0]` is refused by the checker: give a source a scalar
reader), and the twin is written at the read point, never earlier (a source
that moves at the frame start, the clock, left a twin written last frame one
tick stale).

**Class 12 (2026-10-09).** `test_sys_art_contact`: a clip started from six
author hooks (update, a timer, a tween `on_done`, another pair's collision
handler, a `@when`, a transient `on_done`), a flash and a stamp alive on the
sprite; the enter edge fires in the first frame whose drawn cell is a strike
cell and the exit edge in the first frame after the last (both read at draw
time). Every trigger agrees.

**Classes 9 and 10 (2026-10-09).** Class 9 closed without a cell: `confine`,
a teleport in a leave handler and the placement of an Endless piece or a
Level item are instant writes, not persistent drivers. Added to `DRIVERS`,
`confine` × `formula_center` depended on order at once, by design: the
instant write refuses a linked part (`TestLinkWriteGate` is that contract)
and claims nothing afterwards, so a formula installed later is fine. A timed
camera pan reads a body and writes none. The reasoning sits next to the table.
Class 10 settled two contracts in Canvas Design (parallax-layer invariant):
hover handlers are interaction, so `on_hover` / `on_hover_exit` on a parallax
shape now raise `ParallaxLayerError` like `clickable`, and a shape with them
cannot move into a parallax layer (before: accepted and silently never
hovered); a parallax item never fires `@leave_playfield` (pinned: the bounds
step skips decoration, which moves with its layer).

**Class 7 (2026-10-09).** `test_sys_error_sites`: thirty-one author
callback sites (update, timers, `every`, tween / transient / cover / sound
`on_done`, sync and async mode bodies, `@exit_mode`, `on_update`,
`on_destroy`, collision enter / stay / exit, a leave handler, hover and
hover-exit, click, drag and drop, a widget's click and submit, `@when`,
`@on_change`, a formula, an `until` predicate, an act's `setup`, `on_update`
and `on_destroy`, an Endless builder), each armed to raise once in a frame
and checked for the same contract (the error reaches the frame exactly once,
the batch is closed and the dirty stack empty, a bystander's `every` keeps
ticking, no registry holds a destroyed object, no pointer state names one).
Every site recovers. A guard requires every callback-taking export and every
`on_*` attribute of a Graphic to be covered by a site or excused. Harness
lessons: a formula cannot raise through a helper (the formula checker refuses
a body that "creates a Boom": divide by a cell that is zero for one read
instead), and an `until` predicate is checked eagerly at the call (a
predicate that raises there is "not awaited"; raise from the engine's poll).

**Class 3 (2026-10-09).** `program_oracles.camera_moved` (zoom, pan,
rotation, origin set before the program's first line, through
`ProgramRun.prelude`), `time_scaled` (`clock.scale = k` with frames of
`dt / k`: the same world time per frame, so the same trace: anything that
reads the real dt or wall time shows) and `rename_layers` (a Tier C rewrite,
like `rename_groups`), run over every program by `test_prog_invariance`.
First run: every eligible scenario agrees. The camera oracle applies to the
four programs that do not look at the camera: the others place by the view on
purpose (`confine(canvas.game_view)` every frame in `naves` and
`snake_chain`, the head at the view's centre, Endless in `runner_story`) or
chase the mouse (a view point), and are excluded with that reason. Probes that
read the camera (`zoom`, `pan`) are ignored per program. `runner_story` sets
`clock.scale` itself, so it leaves the time oracle. An "observer off" oracle
(cull, post FX, shared-filter batching off → the same trace) is not needed:
`test_prog_isolation`'s `kept_settings` cell runs every program with those
preferences changed. Canaries: a world clock that reads the zoom, a clock
whose dt ignores `clock.scale`.

**Class 2 (2026-10-09).** `test_sys_holders`: the holders are **found**, not
listed. `scan(target)` walks the engine's object graph from its roots (the
framework and its managers, the collision, scheduler, bounds and event
systems, the registry, the act manager, the reactive graph, the module
singletons) through attributes, containers, weak containers, bound methods and
closures and returns every path that reaches the subject with its reference
kind (0.3 s for the whole module). A path seen on a live, fully wired subject
(`kitchen_sink` plus the pointer in a drag, a resting contact with `resolve`,
a group-operator pair side; in act cells an object-literal pair handler and
widgets with focus, a click and an open menu) must be classified in `HOLDERS`;
after a **gone** ender (destroy, destroy after the seal, destroy inside an act,
act change, hard clear, layer delete, group destroy, an Endless recycle, a
destroyed widget) no strong path may remain; after a **partial** ender (park,
hide, undraw, collidable off, untag) each holder keeps or drops per the
documented contract (`EXPECT`, written from Actors Design "park": pair
declarations are reactions on the actor and survive, the Collider and the
survivor's contact go, a parked or hidden shape stays in its layer list and
leaves the pointer lists). First run, five engine findings, all strong
references to a destroyed object that census and `zombies()` never looked at:
HD1 a group-operator side (`group["a"] | group["b"]`) copies its members at the
call and kept a destroyed one in every pair list; HD2 the resolve pairs
remembered at the seal kept a destroyed game-level side forever; HD3 an
act-level object-literal pair handler kept a destroyed side until the act
change; HD4 `WidgetManager.last_click` kept a destroyed widget; HD5 an act
change (and any `registry.destroy` path) bypassed `Menu.destroy`, so the dead
modal menu stayed open: the next act's widgets could not take focus. One root
cause each: `drop_pair_handlers_for` now prunes every pair list (the act-level
list, the sealed pairs, now owned by the collision system, and every snapshot
side) through one `_prune_dead_side`; `remove_widget` clears the last click and
settles a menu through `Menu._settle_on_remove`, the teardown hook `destroy()`
also calls. Regression tests sit in `test_collision`, `test_act`, `test_menu` and
`test_uiwidget`; catalogue [HD](#hd--holders-interaction-campaign-class-2-2026-10-09);
three Recurring bug classes rows. The census and `zombies()` now walk every
layer (`system_support.all_layers`): hidden layers and `ui` were invisible to
both.

**Class 1 (2026-10-09).** `test_sys_phase_matrix`: seven phases where author
code runs (update, an actor's `on_update`, a pair handler, a leave handler, a
hover handler, a `@when`, a transient `on_done`) × thirteen mutations of one
subject (destroy, park, resume, hide, show, collidable off / on, untag / tag,
move onto / off / far from its partner, an ink write) × six observers reading
from their own phase (the actor's tick, the X–Y contact, the leave edge, the
hover level by its own enter / exit edges, a `@when`, the drawn flag). The
documented frame order is the oracle: a later phase sees the change in frame
N, the same phase in N or N+1, an earlier phase in N+1, and nothing moves that
the mutation does not name. Every arming is checked against a phase clock
patched onto the frame body (a mutation that ran in the wrong phase or frame
fails before any verdict). First run, 91 cells: every cell agrees with the
rule once two engine facts were written into the tables rather than found as
bugs: a shape sliding under a still pointer waits for pointer motion
(`TestTradeOff`, documented), and a destroy is synchronous (its exit edges
fire from the call, so a later phase's reading flips in N). Harness lessons:
a helper that must *leave* the playfield has to start inside it (the first
leave-phase arming sat outside the 400 × 300 test playfield and never
fired; the arming guard caught it), and the hover level is read through the
hover step's own handlers, not through `pointer_hover` at draw time (a guard
on a dead subject made the observer flip early).

**Class 4 (2026-10-09).** `test_prog_isolation`: every program after a
neighbour (`dev`) or after every program (`ci`), after seven dirty predecessors,
and a given-back snapshot. First run: every pair and every dirty cell agreed
with the alone trace except the world-settings cell, which changed `naves`
(a playfield pad left in the process decided which enemy shots survived) and
`runner_story` (its `pf` probe read the pad). Not an engine bug: one program
per process in real use. Two harness contracts came out of it, now in
`ProgramRun` ([Program model tests](#program-model-tests), harness lessons): a
run starts from the framework defaults of every world setting and gives the
process back at close (settings, pointer, design size), and the census is
taken before the pre-run settings return (a restored background field was
counted as a leftover). The engine gained `PaintState._reset_defaults` so the
harness and the canvas install the same prototype (no hand copy of the
literal). The dirty cells did **not** reproduce the deep serial failures
([Open](#open-found-not-yet-fixed)): 300 live drawn shapes and shapes with
work in the process leave every program's trace unchanged under the
`SystemWorld` quarantine, so the cause lies elsewhere (the act reset, or a
module that leaves state the quarantine does not park). The systems review
(2026-10-09, [RV4](#rv4--systems-review-fixes-batch-4-what-an-act-change-owns-2026-10-09))
found and fixed both leads: `reset_system_globals` ran the act reset **after**
resetting collision and bounds, and the reset's teardown wrote the sealed
game's leave handlers and resolve pairs back into the fresh singletons
(S4-8); and `SystemWorld` reset no input, hover, press or HUD cursor state
between worlds (X-life-8; `reset_input_state`, shared with `ProgramRun`).
Rerun the deep tier to see whether the serial failures are gone.


# Test tiers

Run the smallest tier that answers the question. `tests/run_tiers.py` runs **one
process per test module** (big modules sharded by class), in parallel, slowest
first; logs in `.scena_test_runs/<tier>/`, timings in `.scena_test_runs/timings.json`.
One log per job, named after its label; a label too long for a file name
(NAME_MAX is 255 bytes) is shortened to its first word, a count, and a hash
(`log_name`). One argument may hold several space-separated module names
(zsh does not word-split an unquoted `$mods`); the runner splits it into jobs.
Two test roots: `tests/` (the framework) and `scena_editor/tests/` (the level
editor, a companion app — [Editor Design.md](Editor%20Design.md#boundary)).
Module names are unique across roots (`test_editor_*`, `test_boundary`); the
runner maps each to its package (`run_tiers.TEST_ROOTS`, `package_of`). The
deep tier's serial pass runs both roots in one process (`serial_names`).

| Tier | When | Runs | Wall (10-core Mac: 4 performance + 6 efficiency cores; 8 workers) |
| --- | --- | --- | --- |
| **focused** (T0) | After every edit | The named modules, `dev`, canaries off | seconds |
| **quick** (T1) | Before calling any change done | Every module except `SLOW`, `dev`, canaries off | ~50 s (2026-10-10: 214 jobs, ~410 s summed; it was ~25 s at 107 modules) |
| **gate** (T2) | Bug loop step 5; before a milestone | Every module, `ci`, canaries on, `SPLIT` modules sharded (`test_hyp_surface` by class and chunk, `test_prog_invariance` / `test_prog_isolation` one class per program, `test_tutorial_steps` one class per page, the game deep modules) | ~3.7 min idle (2026-09-28, 8 workers). Loaded by peer sessions (2026-10-10): 687 s wall / 5494 s summed with `test_prog_invariance` (653 s) as the floor; after the split 838 s / 6698 s at load ~75, longest job a `test_hyp_surface.TestConstructorJunk` shard (~300 s). Wall ≈ CPU sum / 8 |
| **deep** (T3) | Nightly; bug loop step 8 (milestone close) | Every module at `deep`, soak on, **then one serial pass** over both test roots (`dev`) | 2 h + |

```
python tests/run_tiers.py focused test_collision test_diff_collision
python tests/run_tiers.py quick
python tests/run_tiers.py gate
python tests/run_tiers.py deep
python tests/run_tiers.py gate --plan                 # jobs and estimates, runs nothing
python tests/run_tiers.py focused test_x --profile replay
python tests/run_tiers.py quick --sentinel             # every job under the geometry sentinel
```

Why this shape (measured 2026-09-28, 5001 tests):

- **One process for everything is super-linear.** `python -m unittest discover -s tests`
  took 23 min 38 s; the same tests as one process per module took 2 min 08 s on 8
  workers (281 s summed). The single `ScenaFramework` keeps what every earlier module
  left, the heap grows (460 MB vs ~110 MB), and every `census()` / `full_collect()`
  (up to six full `gc.collect()` passes) walks all of it.
- **The time is in a few modules.** 104 of 107 modules take < 10 s at `dev`.
  `test_hyp_surface` is 121 s (`dev`) / 434 s (`ci`); `test_sys_hyp_world` 34 s;
  canaries ~50 s of `test_hyp_surface` alone. Those are the `SLOW` set and the
  `SCENA_CANARIES` switch.
- **The serial pass stays, in deep only.** Process-per-module cannot see one module's
  leftovers breaking the next; a single `discover` can. Conversely, only
  process-per-module sees a test that passes **only** because an earlier module ran
  (O1). Gate and deep together cover both directions. A serial-only failure is
  usually one of two things: the harness measured another module's leftovers
  (O4), or a test leaned on process state an earlier module set (O6), or a
  module leaked actors into a group a later program counts (O7), or a world
  setting (O8). A lucky leftover can also hide one: O8 passed for months
  because the pinned edges happened to match. Some find
  real engine bugs that the isolated run hides because its world is empty: a
  live item in the HUD column (A39), a leftover hidden Point (O5). When you fix
  one, put the missing condition (a leftover actor, a live column item) into the
  isolated test, so the next one is caught without the serial pass.

Measured again 2026-10-10 (217 quick jobs: 118 s wall, 943 s summed; today ~50 s):

- **Quick is bound by throughput, not by its slowest job.** Its wall is about the
  summed job time over the workers (~410 s / 8 ≈ 51 s); the slowest job is ~20 s. Every
  job pays a fixed start (a process, `import scena`, the test helpers): ~1.2 s of CPU
  for a module with nothing in it. More modules cost quick even when each is small.
- **A job is ~1.5–2.5× slower under a tier than alone** (`test_reactive_matrix` 77 s
  under quick, 32 s alone): 8 workers share 4 performance cores with 6 efficiency
  cores. `timings.json` records the job's wall under its tier, so the `SLOW` rule
  reads the module alone (`focused`), where the number holds from run to run.
- **Bytecode is cached for the children.** A host that sets `PYTHONDONTWRITEBYTECODE`
  (Claude Code does) made every child compile `scena` from source: ~0.7 s more CPU per
  process, and per script a test starts (`test_scripts_run` 83 → 34 s of CPU).
  `run_tiers.child_env` drops the switch for the children and caches under
  `.scena_test_runs/pycache` (`PYTHONPYCACHEPREFIX`), so the tree stays free of
  `__pycache__`; a host that writes bytecode keeps its own. Quick went 767 → 390 s of
  CPU with this and the moves below.
- **Decisions (alone, at `dev`, cache on).** `SLOW`: `test_geometry_contract` (18 s;
  the C1–C8 sweeps at fixed poses are 95 % of it), `test_refusal_atomic` (17 s; one
  test enumerates every kind × call × refusal source). Split: `test_reactive_matrix`
  (32 s) → its every-cell matrix in `test_reactive_matrix_cells` (`SLOW`, 22 s) and the
  guards, canaries and canary targets in quick (6 s; the targets are the D12–D21
  subjects, quick's sample of the matrix); `test_scripts_run` (83 s of CPU in parallel
  children) → the examples in quick (11 s of CPU; the tutorials' endpoints) and
  `scripts/smoke` + benches in `test_smoke_scripts` (`SLOW`, 22 s; SR1–SR3 were there).
  Kept: `test_prog_bouncing_balls` (12.5 s) and `test_prog_toybox` (10 s): under the
  line alone, ~20 s / 16 s under quick. Every other quick module is under ~9 s alone.

Rules:

- **Every module must pass alone** (`python -m unittest tests.test_<area>`). The tiers
  depend on it. A test that fails alone but passes in `discover` is an O-series bug.
- **Canaries are tests of the tests** (`diff_support.assert_catches`, the
  `TestWorldMachineReach` vacuity guard). They run at a fixed budget whatever the
  profile, so the quick tiers skip them (`SCENA_CANARIES=0`; default on, so a plain
  `unittest` run still includes them). Run `gate` after changing a suite, a canary, or
  the engine path a canary patches.
- **Keep `SLOW` / `SPLIT` data-driven.** A module past ~15 s of CPU at `dev`, measured
  alone (`python tests/run_tiers.py focused <mod>`; the CPU of the child processes it
  starts counts), joins `SLOW`, or splits a fast part off into a quick module when that
  part is a real sample (the cheap guards, the subjects of past bugs, the examples).
  `timings.json` points at candidates, but it holds the wall under a tier, ~2× the
  alone number. A gate job that dominates the wall time joins `SPLIT`. A split's
  halves cite each other in their docstrings. `tests/test_run_tiers.py` fails on a
  stale name, on a module no tier runs, on a `SPLIT` module whose real `ci` ids do not
  shard (each in one job, more than two jobs, none holding half the module), and on ids
  listed outside the tier's env (O10).
- **`SPLIT` shards by TestCase class, so look at the classes first.** Measure the
  candidate alone (`focused <mod> --profile ci`, wall and CPU) and read its test
  durations: a loop over every program inside one test, or every oracle in one class,
  stays one job whatever `SPLIT` says. Restructure it so the weight sits in many
  classes: one generated class per program (`test_prog_invariance`: `TestPlatformer`
  holds its camera, time and rename oracles; `test_prog_isolation`: `TestNaves` holds
  every cell where `naves` is the program read, so its alone traces are taken once per
  job), or one test per kind in a class that `CHUNK` cuts (`TestDeadEntityVerbs`:
  `test_Circle_methods`, `test_Circle_setters`). A guard over a union cannot shard
  (`test_program_coverage`: every export reached by *some* program); make it cheaper
  instead. Sharding is not free: each job pays ~1 s of start-up and any per-process
  warm-up, so compare the CPU sum, not only the longest job. Measured 2026-10-10,
  alone at `ci` with canaries, load ~5, one job each before → after (wall ≈ CPU):

  | Module | Before | After: jobs, CPU sum, longest job |
  | --- | --- | --- |
  | `test_prog_invariance` | 176 s | 12 jobs, 163 s, 46 s (`TestPlatformer`) |
  | `test_prog_isolation` | 124 s | 13 jobs, 122 s, 18 s |
  | `test_hyp_surface.TestDeadEntityVerbs` | 75 s | 2 shards, 76 s, 43 s |
  | `test_program_coverage` | 91 s | 1 job, 59 s (`sys.monitoring` hook, not a profile hook: identical report) |

  A loaded gate multiplies every job by ~3–5 (the 2026-10-10 gate, 8 workers with peer
  sessions on the machine, saw these four at 653 / 446 / 308 / 290 s). With no job
  dominating, the gate wall is the CPU sum over the workers: 687 s for 5494 s summed
  before the split (= 5494 / 8), 838 s for 6698 s after it at load ~75 (the longest
  job a `TestConstructorJunk` shard, ~300 s; ours at most 231 s). Past that point only
  a cheaper job, or a quieter machine, shortens the gate.
- **Budget a job by its CPU, not its wall time alone.** Each job gets the tier's
  timeout (quick 300 s, gate 1800 s). A module that runs child processes in parallel
  looks fast alone and is not under a tier: its children share the cores with the
  other workers. `test_tutorials` ran every tutorial step in one test (~118 s wall alone,
  ~440 s CPU); tutorials 14–23 doubled it and it timed out the quick tier (2026-10-10).
  A suite that grows with content (one program per tutorial step, per example) is
  generated **one TestCase class per unit of content** in its own `SLOW` + `SPLIT`
  module, so the gate runs one job per unit and a new unit needs no edit; the cheap
  checks of the same content stay in a quick module.
- **Tutorials.** `test_tutorials` (the pages, no run: extraction, endpoints, recaps,
  focus, syntax; ~1 s) is in quick. `test_tutorial_steps` runs every step and `try`
  box for 600 frames; it is `SLOW` and `SPLIT`, one class per page (`TestSteps05` is
  `05-naves.html`), so gate and deep run every step as ~25 jobs (each under ~45 s;
  all of them ~45 s wall / ~320 s CPU on 8 workers with the runner's bytecode cache,
  ~64 s / ~500 s without; 2026-10-10). Quick still runs each tutorial's last
  step, as its `examples/` file (`test_scripts_run`, 30 frames), and `test_tutorials`
  holds the file equal to the step. Guard: `test_run_tiers` (one gate job per page,
  none in quick).
- **A module destroys what its tests made.** Leftovers live on in the serial pass: every
  later `census()` / `full_collect()` walks them and every `SystemWorld` parks and
  resumes them (`test_shapes` left 1905 roster items, `test_reactive_matrix` ~163 000).
  A module that builds actors without destroying them declares
  `setUpModule, tearDownModule = module_sweep()` (`tests/leftovers.py`). Every tier
  enforces it: `run_tiers.py` runs a `LeftoverCheck` after each module, which fails above
  `LIMIT` (50) live roster items and names their kinds. Measured on the serial pass
  (2026-10-09, 48 modules swept): 45 failures → 6 (the program-run censuses that saw
  other modules' shapes), 7854 s → 2883 s of CPU. Counts can grow with the
  budget: `test_construct_failure` left 2 at `dev` and 216 with canaries on, so the gate
  is where such a module shows. Leftovers once exposed an engine bug (a hidden Point on a
  layer, through the serial pass): when a leftover state matters, build it inside an
  isolated test rather than relying on a neighbour to leak it.
- A module that starts and ends its own global state (new singleton, new registry)
  needs no runner change; a new **env switch** goes in `Tier` / `tier_env`.


# Bug loop

Every finding — from any suite, at any profile — goes through these steps. None is
optional. The loop exists because fixes cause regressions: the H1 fix broke every
`Entity` subclass (R1), and only a re-run of the suites caught it.

1. **Reproduce.** Turn the shrunk example into a deterministic repro.
2. **Triage.** Model error, engine bug, or doc gap? If the design docs are silent or
   ambiguous, write the contract into the owning companion **first**, then encode it.
   A raise-vs-no-op choice is a design decision: ask.
3. **Regression test first**, in the owning `tests/test_<area>.py`; it must fail on
   the unfixed code. Add `@example(...)` of the shrunk case to the property.
4. **Fix.**
5. **Verification gate** — all green, in order (while iterating on the fix, use
   `focused` / `quick`; the gate is for the finished fix — [Test tiers](#test-tiers)):
   ```
   python tests/run_tiers.py focused test_<area> <finding suite>
   python tests/run_tiers.py focused <finding suite> --profile replay
   python tests/run_tiers.py gate          # every module, ci, canaries (replaces the
                                           # serial full suite + ci hyp / sys_hyp runs)
   ```
   Hot-path fixes (pose, draw, collision, `_write_field`) also run the matching
   `scripts/bench` row ([Effect System Design §5.5](Effect%20System%20Design.md#55-changing-the-effect-system-without-regressing-hot-paths)).
   A new failure here is a **regression of the fix**: fix it before moving on and give
   it an `R` row.
6. **Bug-class guard.** If one structural test would stop the whole class, add it.
7. **Document.** A row in the [Bug catalogue](#bug-catalogue); a one-line warning in
   the owning companion when the bug exposes a design hazard.
8. **Milestone close.** Run the suite that found it once at `deep`
   (`python tests/run_tiers.py focused <suite> --profile deep`); the whole
   `deep` tier nightly or at the milestone.


# Harness pitfalls

Each of these produced a false leak or a false pass. Check them before blaming the
engine.

- **`kN32` is the platform's byte order**: RGBA on the Mac, **BGRA on Windows**.
  `skia.Image.fromarray` defaults to it; `Image.toarray` defaults to the image's own
  type, which is N32 for `skia.Surface(w, h)` / `MakeRasterN32Premul`. A test reading
  `px[..., 0]` as red passes on the Mac and reads blue on Windows. Always pass
  `colorType=skia.kRGBA_8888_ColorType` to both (engine code too). Guard:
  `test_platform_portability.TestPixelsNameTheirByteOrder` (WP2).
- **A tree copied from macOS holds `._<name>` next to every file** (AppleDouble, on
  exFAT / FAT / SMB volumes). `._foo.py` ends in `.py`; `Path.glob` / `rglob` match it.
  Scan with `tests/source_support.iter_files`, never `os.listdir` / `os.walk` / `glob`
  (WP1). `run_tiers.py` prints a warning when it finds them; cleanup in `tests/README.txt`.
- **A single wall-clock sample is noise under the parallel tiers**: time best of N
  (`min`) against the budget (WP3). Best of N drops spikes, not sustained load: with
  10 workers on a slower machine every sample is slow (WP7). Never size an absolute
  ms budget on one machine; compare against a reference path timed in the same
  process (a ratio), or keep the absolute number only as a loose catastrophe guard.
  A ratio of two samples timed one after the other still moves with the load
  between them: interleave short blocks of both paths (alternating which goes
  first) and keep each side's best block (WP18).
- **Text I/O without `encoding=` uses the locale**: UTF-8 on the Mac, cp1252 on
  Windows (`—` reads as `â€”`). Every text `open` / `read_text` / `write_text` passes
  `encoding="utf-8"`. Guard: `test_platform_portability.TestTextIoNamesItsEncoding`
  (WP5). `run_tiers.py` pins the children's `PYTHONIOENCODING=utf-8` and reads logs
  with `errors="replace"` (WP8); do not set `PYTHONUTF8`, which would hide WP5.
  The same holds for a test's own children: `subprocess.run(..., text=True)` decodes
  with the locale. A Python child gets `encoding="utf-8", errors="replace"` and
  `PYTHONIOENCODING=utf-8` in its env. Guard:
  `test_platform_portability.TestSubprocessTextNamesItsEncoding` (WP16).
- **Path functions follow the host**: `os.path.abspath("/a/b")` is `C:\a\b` on
  Windows. An expected path that went through `abspath` / `realpath` /
  `Path.resolve` / `os.path.join` is built the same way in the test, never written
  as a POSIX literal (WP6). A `relpath` used as a label is compared in `/` form:
  `os.path.relpath(p, ROOT).replace(os.sep, "/")` (WP11). A helper that joins a
  path given in `/` form (`png("ninja/Run__000.png")`) wraps the join in
  `os.path.normpath`: `os.path.join(root, "a/b")` is `C:\t\a/b` on Windows,
  unequal to the `C:\t\a\b` the code returns. Guard:
  `test_platform_portability.TestJoinedPathsUseOneSeparator` (WP19).
- **Windows has no exec bit**: `os.chmod` only toggles read-only, and `st_mode`'s
  execute bits follow the extension (`.exe`, `.bat`), so a `.desktop` file is never
  "executable". Assert `S_IXUSR` / `X_OK` only when `os.name != "nt"`. Guard:
  `test_platform_portability.TestExecBitIsPosixOnly` (WP12).
- **A Hypothesis module imports `hypothesis_support`** (or `system_support`) at
  module level. Without it Hypothesis runs on its defaults: a 200 ms deadline
  (`DeadlineExceeded` under a loaded tier), no example database, and
  `SCENA_HYPOTHESIS_PROFILE` ignored. Guard:
  `test_run_tiers.TestHypothesisProfileGuard` (WP13).
- **Pin the clock when a test places a transient and then draws**: a test that sets a
  fade's progress from one `_now()` read and then calls `draw()` / `step()` lets the
  engine read the clock again, later by however long the test took under load. Pin it
  with `transients.set_now_fn(lambda: now)` and `addCleanup(set_now_fn, None)`. Guard:
  `test_platform_portability.TestTransientClockIsPinned` (WP14).
- **A runner output file may be Hidden or read-only**: a tree copied from macOS can
  arrive with its old `.scena_test_runs/` logs Hidden, and Windows refuses
  `open(path, "w")` on an existing Hidden file. `run_tiers.open_fresh` deletes the old
  file first. Guard: `test_run_tiers.TestOpenFresh` (WP10).
- **Parking changes the census.** A world that parks leftovers (`SystemWorld`'s
  quarantine) moves `registry.draw_live` and friends; a before / after pair must
  both be taken parked or both released, never one of each (O4).
- **A module that never calls `init()` inherits the last module's design size.**
  `boot()` inits 400×300 once per process; alone that is the size a module
  sees, in the serial pass it is whatever ran last. A test whose numbers follow
  the view (slot counts, culling, wrap) pins it in `setUpClass` (O6).
- **A same-value write can change a world setting's meaning.**
  `playfield.left = playfield.left` pins the auto playfield to the current
  view. A test that writes world settings runs inside a `system_world()`,
  which gives every `act.WORLD_SETTINGS` entry back at teardown (O8).
- **Your own references keep actors alive**: loop variables, handle sets (a `Handle`
  holds its owner), a sink's handle list, a teardown loop's local, and Hypothesis
  bundle values. In state machines keep int handles into a pool the machine owns.
- **The collision system keeps the last step's snapshot** (`_last_prims`) for one
  frame: step once before asserting collection.
- **GC-backstop finalizers free more on a later pass**: use `full_collect()` (gc until
  nothing is freed; `tests/graph_support.py`, re-exported by `system_support`), not
  one `gc.collect()`.
- **A graph count races the cyclic GC.** `dependency_graph.nodes` is weak, so an
  earlier test's garbage is in a raw `len(graph.nodes)` until a collection purges
  it, which may land between a baseline and the final read (O1, O9). Read counts
  with `graph_support.settled_graph_size()`, inside `gc_paused()` when the body
  must leave nothing behind. Guard: `test_count_baselines` (every
  `len(<…>.nodes)` in the tests follows a settle).
- **Reading a linked value outside a frame batch is eager**, like the script body: a
  pull recompute polls `@when` at once. Read inside the frame when edges matter.
- **The `every()` flood detector keys on wall time**: headless runs are faster than
  real time, so `sched.every_sites` is not a baseline key.
- **Unlinked Defining writes do not poll events outside a frame** (A2 fast path):
  `c.radius = 5` at top level does not fire `@on_change` until the next flush. Models
  of eager mode must poll only after ink / boxed-cell writes
  ([Reactive Design — Eager effects](Reactive%20Design.md)).
- **Empty numeric layers are not a leak**: `layer=<int>` auto-creates on first use;
  censuses ignore empty int layers.
- **A list of suspects keeps the suspects alive.** The roster is weak, so it lists garbage
  until a GC pass; collect *after* dropping your own list of the items, or the list is
  what keeps them. The first `LeftoverCheck` called `gc.collect()` with its list in hand
  and reported 192 Points that were garbage.
- **`import scena.collision as col` is the facade, not the module.** `scena/__init__`
  exports `audio`, `canvas` and `collision` objects that shadow those submodules, so
  a monkeypatch on `col` silently patches the facade and a canary "passes". Patch
  `sys.modules["scena.collision"]` (or `from scena.collision import …` for reads).
  The first D2 canary passed for exactly this reason.
- **A canary must corrupt a path-specific helper, patched where it is CALLED.**
  Skewing `_pose_rotation_set` (shared by both paths) moved both twins alike, so
  the differential still agreed. `shapes.py` imports helpers by name: patch
  `scena.shapes._x`, not `scena.entity._x`.
- **Run canaries on a fresh copy of the test module.** Running the same `@given`
  function from a second TestCase instance trips Hypothesis's
  `differing_executors` check on the suite's own later run (`assert_catches`
  does this for you).
- **Derandomized canaries explore different examples per function identity.**
  A canary that passes in one import and fails in another means the property
  is weak for that bug class — strengthen the generator (see ABA below), do
  not raise `max_examples` until it happens to pass.
- **Generate the round trip on purpose (A → B → A).** Caches keyed by a past
  state are wrong only when the state comes back; random walks almost never
  revisit exact vertices (D2 was found only with an explicit "excursion" op).
  Same for pull reactivity: "link → write source → read target" (D8's class).
- **Geometry properties: check the pose, not the counter.** The heading `angle`
  accumulates (a full turn reads `+360`), so "rotate 360° is the identity" and
  "undo" hold on world vertices and the heading, not on the number. A property
  that only reads the heading missed G1.
- **Keep sample points off exact edges.** `Grid` placement and `cell_at` compute
  the same edge in two frames; exactly on it they may disagree by one ulp (both
  include the edge). Sample strictly inside, `_EDGE = 1e-6` away
  (`test_box.TestGridCoversBoxProperty`), or the property fails on rounding.
- **Screen ↔ world is float32.** `screen_to_world_coords` inverts a Skia matrix,
  so a round trip at coordinates in the thousands drifts ~1e-4 world units.
  Scale the tolerance with world, pan and screen magnitudes
  (`test_canvas.TestScreenWorldRoundTripProperty._tol`); a slip in the chain
  is O(1) or more.
- **Invariance under a shift needs exact arithmetic.** Shift by whole numbers
  and keep generated vertices dyadic (`size * 0.25`, not `* 0.6`); split a
  shift into 1, 2 or 4 `move_by` steps, never 3. Otherwise a body that exactly
  touches another lands an ulp in or out after the shift, and the property
  reports rounding as a collision bug.
- **Never canonicalize float data by sorting it.** An order-free compare that sorts
  raw floats breaks as soon as two items tie on the first sort field: an ulp of
  drift reorders them and the diff pairs different items, a false "fast and slow
  paths diverge" on correct output (D10: two arc wedges, `-8.94 vs 0.0`). Pair by
  nearest match within the tolerance (`assert_same_prims`). If a failing diff shows
  values that exist on the other side at another index, suspect the pairing first.
  A guard for this class must build the tie itself: at construction pose no model
  has tied prims, so a sort-based oracle passes a guard that only shuffles.
- **Headless frames draw at scale 1 into the top-left design rectangle** of a
  framebuffer-sized surface (y-up), and `glViewport` is mocked, so geometry past
  the view spills into the rest of the surface. Compare only
  `surface[:height, :width]` (`test_diff_draw._screen`).
- **A differential varies ONE switch.** Cull on/off with shared-filter batching
  on differs by a level at batched blur-layer edges (the batching trade-off),
  not because culling is wrong; pin every other switch to its reference.
- **Formula sources must be captured directly** as default arguments
  (`lambda o=obj: o.v`). A source behind another lambda is not found, `@=`
  raises TypeError — and a generator that only produces such formulas tests
  nothing (the first `test_diff_reactive` passed with every link failing).
  Keep a fixed-program "not vacuous" test next to every generated program.
- **`fx_quality="max"` is not "batching off"**: it also changes `post_scale` and
  detail. To compare batched vs per-shape draw, flip `canvas.batch_shared_filters`.
- **Check a caught exception AFTER the `except` block.** The traceback keeps the
  half-built object alive while the handler runs, so a census taken inside it
  reports the rolled-back actor as a leak (`test_hyp_surface` stores the verdict
  and asserts after).
- **Unbound methods have `self`.** An argument guesser reading
  `inspect.signature(Class.method)` saw `self` as an unknown required parameter
  and skipped every method: P6 passed while calling nothing. Drop the receiver,
  and keep a call-count floor next to every generated loop.
- **Optional parameters can decide whether work happens.** `after(0.1)` without
  `fn` returns a decorator and schedules nothing; P6 must always pass `fn`
  (`_ALWAYS_PASS`). The S9 canary exposed this.
- **Layout cursors are not registries.** The HUD column (`_stack_x`, …) advances
  when a widget is placed and `destroy()` does not rewind it. Only a *rejected*
  call must leave it unchanged (`CURSOR_KEYS`). Check that with a live item
  already in the column: alone in the column, a rejected item is rewound by
  the "last item leaves" rule and a cursor move is hidden (A39).
- **Compare the base background by kind, not identity.** Removing a base installs
  a fresh default; `remove()` of a base is `reset_base()`.
- **Python's "missing N required argument" is an author error** when it names a
  real parameter of the call (a zero-argument call of a required knob).
- **A canary that disables cleanup must undo its own leak.** The H1 rollback
  canary left half-built Circles (no `model`) registered; eight tests in later
  modules then crashed drawing them. Record what the patched no-op received
  and run the real cleanup afterwards.
- **A sweep needs a per-call timeout.** The first deterministic method sweep
  ran 33 minutes at 100 % CPU: `spaced_points(1e308)` looped. Wrap each call in
  `signal.alarm` and report a hang as a finding.
- **"Constructible with no arguments" is not "covered".** The methods phase
  skipped `Color`, `Box`, `Menu` because `Kind()` raises; the whole Color amount
  family leaked unseen. `TestMethodCoverage` fails unless each such class has a
  representative or is engine-built.
- **Public is not author-facing.** `advance_scroll`, look `apply(host)`,
  `sample_pad` were engine hooks without an underscore, so the methods phase
  fuzzed them as author verbs. The sweep underscored every such hook (~110
  names: look / filter / post / background / SpatialFx / audio-fx protocols,
  widget interaction state) and `test_api_surface` now walks **every** class,
  constructible instance, and exported object in `scena.__all__`: a public
  name must be spelled in the Guia or listed in `SURFACE_NOT_IN_GUIA`. The
  methods phase still fuzzes only those names. A protocol hook dispatched by
  string (`getattr(look, "_render_sprite_body")`) must be renamed in the
  string too; check for an existing private name before choosing the new one
  (Laser's own `_render_sprite` would have become the dispatch target).
- **A failing rule makes teardown lie.** Hypothesis runs `teardown()` in a
  `finally` while the rule's exception propagates; its traceback pins the
  actors, so the residue check reported two `Point`s instead of the real
  `TypeError` (`obj.group` was a set; now a `GroupTags` frozenset — K3). `WorldMachine.teardown` skips its leak
  asserts when `sys.exc_info()` is set.
- **Rules are collected at class creation.** Monkeypatching a rule method after
  the class exists does not change what Hypothesis calls. Count reach from
  inside the rules (`HITS`) and assert it in a separate test
  (`TestWorldMachineReach`).
- **Random rule order rarely lines up a multi-step scenario.** "Create a
  layer → move an actor onto it → drain it (with an `on_destroy` that spawns
  back onto it)" never happened in 80 examples; a composite rule
  (`drain_occupied_layer`, `link_then_kill_source`) makes it routine. Keep the
  single-step rules too (they explore orderings). A composite rule must not
  `return` on a dead or repeated bundle pick: spawn a fresh stand-in instead.
- **A `derandomize=True` reach guard is only as robust as its weakest
  counter.** The seed is the digest of the machine's source, so any edit
  (renaming a lambda parameter) draws a new stream. `link_then_kill_source`
  used to return when a pick was dead. Because `destroy_group` removes half the
  world at a time, most picks were dead, and across 10 seeds `link_installed`
  ranged from 0 to 108 (`link_source_died` was 0 in three of them). One rename
  flipped the guard (`link_installed=0`, `link_refused_dead=23`). Fix: the rule
  replaces dead or repeated picks, and after killing the source it retries `@=`
  from the dead source, which must be refused (W2). Now the lowest count over
  20 pinned seeds is 9 (`drain_nonempty`) and links stay ≥ 17. The guard keeps
  `derandomize=True` (80 examples, 50 steps), so each edit still samples a new
  stream. It asserts a floor of `MIN_HITS = 3` per counter, not only
  > 0, so a counter drifting toward marginal fails before an edit flips it. **Do not fix a marginal counter with `@seed` or a larger
  `max_examples`**: a pinned seed hides the low rate until the rule set changes,
  and more examples only shrink the odds. Make the path common, then measure
  the lowest count per counter over about 20 `@seed(n)` runs on a subclass of
  the machine.
- **A canary may be caught by another layer.** S1's bound-method variant only
  pins an actor dropped without `destroy()`; the machine always destroys, and
  `bounds.forget_item` covers the rest. Aim the canary at the defence the
  machine exercises and name the unit test that guards the other.
- **Canaries do not need shrinking.** The `canary` profile runs without the
  shrink phase: six world canaries went from > 10 min to 12 s.
- **An accepted junk value is invisible to "author errors only".** P2 checks
  what a *raise* looks like; `Stars(enabled="no")` did not raise at all (A12).
  Where the contract says a value must be refused (flags, enum names), walk
  those parameters with a "must raise" test.
- **Global setters run inside a snapshot.** `surface_support.global_snapshot()`
  / `global_restore()` cover the framework FX-Auto / framerate / quality
  fields, the canvas scales, the `fx_quality` globals, `WATCHDOG_ENABLED`,
  `_show_tracks`, `_EXTRUDE_FOCUS` and the `PaintState` prototype;
  `TestGlobalSetters` proves each setter's effect is captured and undone. A
  new global setter goes in `GLOBAL_SETTERS` with a valid call.
- **Census deltas cascade.** Refresh the baseline in `finally` after every
  subtest, or one leak fails every later verb of the same actor.
- **Settle garbage before a count baseline.** A "did not grow" check on
  `dependency_graph.nodes` (or any registry a GC-backstop finalizer prunes) must
  collect until nothing is freed **before** the baseline and before the final read.
  Otherwise an earlier test's garbage is purged mid-loop, the count drops, and the
  test fails only when its module runs alone (O1). The geometry campaign met it
  twice more in tests written without it (`test_history`, the Anchor refusal in
  `test_reactive_matrix`): any count of graph nodes or registry entries collects
  first. It came back a fourth time (O9) and an audit found nine more unsettled
  counts, so the prose rule became a static guard
  (`test_count_baselines.TestGraphCountsAreSettled`). A graph count goes through
  `tests/graph_support.py`: `settled_graph_size()` for the baseline, and
  `gc_paused()` around the body when the test also claims "installs nothing"
  (D11: with the GC on, the test's own cyclic throwaways vanish before the
  final read, or race it).
- **A rule that is broken again belongs in a guard, not in more prose.** O1's
  rule was written down, then missed in three new tests. "Run the module alone"
  (the gate tier) is not a class guard for a GC race either: whether a
  collection lands between two reads depends on allocation counts, so the same
  module passed in one run and failed in the next. A GC-timing bug is made
  deterministic by planting the garbage and forcing the collection
  (`test_count_baselines.run_with_collections`).
- **An observer puts back what it adds, not only what it changes.** The
  sentinel's I-clean restored the stores it found and left the cold slots its
  recompute filled (a RegularPolygon's `side`), which a raw reader of the pose
  key saw. Tests that assert engine internals (mark_dirty counts, cold
  Derivates) do not run under an observer that runs engine code
  (`run_tiers.SENTINEL_EXCLUDE`, with reasons).
- **A harness that runs inside `@given` must not import a test module.** The
  import builds that module's `@given` tests, and Hypothesis fails the
  nested-given health check; the failure shows only when the import happens
  first inside the machine. Shared helpers live in `geometry_support`.
- **A shadow advances only when the clock does.** The shadow machine settled
  every other subject's turn before a timed step that then did not run (a
  parked subject); compare the clock before and after the step.
- **A harness that keeps the last value per key reports one cell per key.**
  A known pattern can then be satisfied by a different cell than the one it
  names; dump the cells when a pattern is removed.
- **Measure the A/B noise floor before reading a delta.** Two copies of one
  tree (`perf_geometry.py --ab A --tree B`) differ by up to about ±2 % per row;
  a hunk that never runs cannot cost 3 %. Bisect a delta by applying each hunk
  alone on top of HEAD, tree against tree.
- **A mutation sample depends on its pool.** Adding suites widens the lines
  executed, so the same seed samples other mutants; compare suites with one
  pool (`mutation_run.py --pool-programs`).
- **zsh does not split an unquoted `$var`.** A program list held in a variable
  reached `mutation_run.py` as one name: the control failed and no line was
  collected. Write `${=var}`.


# Lessons learned

1. **Bugs live in sequences and in what failure leaves behind.** None of H1–H7 is a
   one-line call: destroy → reuse id → destroy the stale reference (H3); construct →
   register → raise (H1). Example tests covered happy paths and single bad inputs.
2. **A small model checked after every step catches classes, not instances.**
   "A destroyed object is nowhere" found H2, H3 and H4 without targeting any of them.
3. **Python's own error messages are a free oracle.** `could not convert…` or
   `float() argument…` reaching the author means a value got past the validators.
4. **Settle the contract in the docs before encoding it.** About half the first
   failures were model errors (`Text(layer="default")` needs `center=`; `clone()`
   copies `visible`; `time=None` means instant). Two agents disagreed on `None` in pose
   verbs until Effect System Design's "`move_to(None)` (pose still errors)" settled it.
5. **One failure per raise site.** A shared "accepted" assertion hid `move_to(nan)`
   behind `move_by(None)`.
6. **Flaky means leak.** The first *Flaky* report was a zombie from one example
   leaking into the next (H2).
7. **Fixes cause regressions.** Five of the first fixes needed follow-ups (R1–R5); all
   were caught by re-running the full suite and the property suites.
8. **Search depth matters.** Blank `id=""` appeared only at the `deep` profile.
9. **Test-owned references are the main source of false leaks** (System campaign; see
   [Harness pitfalls](#harness-pitfalls)).
10. **Passing is not proof.** A property that never failed may be weak; canaries
    (re-introduced known bugs) measure it.
11. **Guard against vacuous passes explicitly.** The first reactive
    differential compared two runs in which every link had failed; the first
    pose differential would have compared slow against slow for Polygon.
    `assert_fast` and a fixed-program "not vacuous" test are cheap insurance.
12. **Verify the mechanism before fixing.** A 1-pixel cull difference looked
    like a missing antialias margin; a fix and a test were written, then a
    direct experiment (disable the margin → no difference) showed the cause was
    batched blur-layer bounds. The fix was reverted. Isolate by minimal repro
    AND by switching the suspected cause off.
13. **A fix can change a contract other tests encoded.** D8 (unlink pulls
    first) made `test_sys_lifetime` fail: it asserted the stale value. Decide
    which contract is right, write it in the design doc, then update the test —
    never loosen the new fix to satisfy the old test.
14. **A slow path can mask a correctness bug.** R7's cache key was blind to
    Defining inputs from the start; warm Derivates bumped the collision epoch
    and hid it. Removing the waste (D3) exposed it — only because the gate
    re-ran the differential suites. After a performance fix, re-run the
    correctness suites, not only the benchmarks.
15. **Canaries test the harness too.** The P6 canary for S9 did not fail: the
    fuzzer had skipped every method (unbound `self`), then called `after`
    without `fn`. Fixing the harness found A6 / A7 at once. When a canary does
    not bite, suspect the property before the engine.
16. **A list kept by hand drifts from the code it describes.** The A3 guard
    rejected functions everywhere except an opt-in list; reactive pad knobs were
    not on it and `Rain.from_rect` broke (R8). Derive such lists from the class
    (declared field slots) and guard with a test that walks every class.
17. **`dev` green is not `ci` green for per-class generated tests.** 200 tests ×
    8 examples leave most (knob, junk) pairs untried; `ci` found four more
    leaks. Run `ci` before closing a milestone.
18. **Methods had no guard at all.** Constructors got the numeric guard in A3;
    the methods phase found 64 leaks from nine causes on its first run and one
    infinite loop. A contract enforced at one entry point says nothing about
    its siblings — fuzz each entry kind (constructor, method, setter, function).
19. **Prove the machine reaches what it claims to check.** The first M4
    world machine passed at `dev` in 3 s; a reach counter showed the drain of
    an occupied layer and a link whose source dies never happened. An
    invariant over a state the generator never builds is decoration.


# Lessons for test planning

From the reactive campaign (2026-10-07/08, D12–D26): fifteen bugs, none exotic.
Each sat in a combination no test reached, or behind a rule that was written but
not checked. Complements [Lessons learned](#lessons-learned) (canaries, vacuity,
reach counters: items 10, 11, 19).

## What the campaign taught

1. **Bugs live in the cross-product; point tests sample it after the fact.** Every
   bug was one cell of field × write path × what was read before × construction
   model × link kind. Enumerating those axes from the slot metadata
   (`reactive_matrix_support`) found them mechanically.
2. **Read order is an axis of its own.** D18 hid because a sorted read put `angle`
   first; D26 because tests read the caption before the link; corner names depend
   on the first read. "Read the link first" found two bugs.
3. **The oracle can be wrong too.** Five harness bugs: listing fields read the
   subject (and named its corners) before the link; `_takein` on a Derivate
   bypassed its guard; default-argument lambdas hid the source (the machine
   installed zero links); two points on one formula made a zero-length spine; an
   assumption that corner names are path-independent. The plain-write twin read at
   the same moments, or the source object itself, held up.
4. **Rules on one path are bugs on the others.** Validation in `_write_field`
   overrides ran on `=` only; links, constructors and batches skipped it (D14,
   D16, D22). Rules on the slot, one coercion, removed the class.
5. **Duplicated code drifts silently.** Box carried ~300 lines of Rect and missed
   Rect's later fix (D20, D23); twenty point readers each had their own rules (D24).
6. **A lazy value needs a dirty edge *and* a pull on read.** D18, D19 and D26 each
   had one of the two. Clean means recomputed (D13, D19).
7. **Refuse where the mistake is made.** D17 accepted two exclusive links and
   failed on every later read.
8. **Copies need cross pairs.** Copies were tested within one construction model;
   every ordered pair of models found 129 of 186 broken (D21).
9. **A documented rule without a check decays.** Hazard #8 (Reactive Design) had a
   rule and no guard; the first static guard on it found D25.
10. **Performance is part of the fix.** Five first attempts regressed (+9 % to
    +45 %: magnitude writes, Box `rotate_by`, Text layout, `get_xy`, `_xy_of`).
    Separate runs drifted 3–5 % with the machine's load; alternating runs against a
    pristine HEAD copy were reliable. An extra Python call, extra keyword defaults
    or a `super()` proxy is measurable on these paths.

## What the program-model campaign taught (2026-10-08)

Eleven whole programs, 19 specs written from the docs by authors who never saw
the engine, model-free oracles, and three programs written API-first. Findings:
PM1–PM14 (catalogue). The suite had 6 300 tests and a strong mutation score, and
still missed every one of them. Why each slipped through:

| Finding | What the existing tests did | Why they missed it | The test that catches the class now |
| --- | --- | --- | --- |
| PM3 `keyp.once` fired for an old unread press | `test_keyp` pressed and read **with no frames in between**; the IN1 property modelled "since the last fire" | The contract is frame-scoped ("só no frame do aperto"); a test without frames cannot see a frame boundary. SC1 had been fixed as an act-change symptom | Frame-boundary steps in `TestOnceChordProperty`; `TestOnceIsFrameScopedInFrames` (real frames) |
| PM7 empty-group verb built a Shape per call (~0.3 ms) | `census` before / after, with a full collect | Garbage collection erased the evidence; nothing measured the **cost** of a no-op, and benches use populated groups | A constructor spy around the no-op; `probe_neutral` (a run with observers vs one without differs by GC timing) |
| PM8 timers a frame late by float rounding | Timer tests stepped `dt=0.1` / `0.2` and asserted with slack | Never the author's regime: `dt = 1/60` summed to a deadline that is a whole number of frames | `TestDueOnTheExactFrame`: 6 frame rates × 11 frame counts × 6 mechanisms |
| PM11 `test_collision` returned engine colliders, reversed normal | Handler tests checked `info.a is me`; query tests checked "overlap or None" | The same `CollisionInfo` reached authors by two doors and only one was checked against the documented view | `TestQueryInfoIsTheAuthorView` (query equals what a handler sees) |
| PM12 `deadzone(size=st.x)` refused a cell | The Numbers rule (cells count as numbers) is fuzzed on slots, verbs and constructors | Free helper functions were outside the fuzzed surface | Unit pin; the class guard is still to write (below) |
| PM14 formula read the edited file at stale positions | Formula tests define lambdas in the test file, which never changes | Source availability was tested (REPL, `exec`), source **staleness** was not: an environment fact no unit test varies | `TestStaleSourceFile`; found by Tier C rewrites |
| PM1, PM4, PM6, PM9, PM10, PM13 doc gaps; PM5 decided | Tests pin what the engine does | No test can notice that the docs are silent or wrong; only a reader who depends on the docs can | Spec-only authors; the same gap reported by two of them is a finding even with no divergence |

1. **Tests written from the implementation inherit its blind spots.** PM3's
   "an edge stays pending until read" and PM11's raw payload were what the code
   did, and the tests agreed. The spec authors, reading only the Guia, expected
   what the Guia says. Write the test for a documented sentence from the
   sentence, not from the code.
2. **A contract with "frame" in it needs real frames.** Calling the internals
   back to back (`_press`, `once`) skips the boundary where the bug lives. Use
   `SystemWorld` / `ProgramRun` for frame-scoped behaviour (edges, timers,
   `@when`, pause, act changes).
3. **Use the author's numbers.** `dt = 1/60`, deadlines like `0.25` and `0.5`,
   60-frame seconds. Round test values (`0.1`, `0.2`) are kinder to floating
   point than real programs are.
4. **One payload, several doors: check them against each other.** `CollisionInfo`
   from a handler and from a query; `.color` before and after a write; a value
   read through a probe and through a fingerprint. A differential between doors
   needs no model.
5. **Cost is a contract too, and GC hides it.** A no-op that allocates passes
   every correctness and leak test. Spy on constructors around no-ops, and
   compare runs with and without observers.
6. **Isolation bugs hide until order changes.** The harness alone found nine:
   keyboard edges, group names learned for typo hints, background items, acts,
   world settings (the playfield), pointer state, the mouse position, the
   widget layout cursor, the program namespace held at census time. Each showed
   only when one program ran after another (or after `test_api_robustness`) in
   one process. Assume a global setting leaks until a test proves otherwise;
   the deep tier's serial pass is the backstop, not the first line.
7. **Writing realistic code against the docs is a test.** The three API-first
   programs found PM11, PM12 and PM13 while being *written*, before any spec
   ran. A program author is the first user of an API nobody had combined.
8. **Two independent readers find doc gaps by agreeing.** Six gaps were reported
   by both authors of one program without any divergence; six of twelve authors
   could not predict the frame a timer fires (PM8). Agreement on an ambiguity is
   a stronger signal than one divergence.
9. **The spec authors' errors are worth reading too.** 12 revisions: INTUITION 4
   (class names, a ball's path), SPEC-LOGIC 4 (a percentage standing in for an
   exclusion, a miscomputed bound, `id()` reused after a free, a phase flipping
   mid-frame), MISREAD 1, HARNESS 1, DOC-AMBIG 1, DOC-SILENT 1. The recurring
   ones became generic check-writing rules in the spec prompt, never engine
   facts (the authors' independence is the point).
10. **Mutation score measures local contracts, not this.** Random mutants of the
    lines the programs run: the quick tier killed 20 of 30, the programs 10, the
    programs alone none. Every bug of this campaign is a *missing* contract or
    one encoded wrongly, which no mutant of the existing code represents. A
    mutation run also needs a control: one without it reported three false
    "program-only" kills.

### Class guards written from these lessons

Each found a new member of its class on the first run (PM15–PM17):

| Guard | Lesson | Covers | Found |
| --- | --- | --- | --- |
| `test_cells_as_numbers` | the Numbers rule on free functions (PM12) | every exported function in `CASES` (a canonical call) or `NO_NUMBERS` (a reason); each number, and each number in a pair, given as a cell, must give the same result | PM15 `amp_db(st.x)` raised |
| `test_collision_doors` | one payload, several doors (PM11) | random circle / rect / polygon pairs: `@collide`, `on_collide`, `@collide_stay` and `test_collision` give the same `CollisionInfo`; reversed arguments reverse the normal when the centres differ along it | — (level centres have a fallback direction in argument order; documented in the test) |
| `test_sys_frame_contracts` | frame promises in frames (PM3) | each Guia sentence that promises a frame ("só no frame", "no próximo frame", "no mesmo frame", "cada frame seguinte" …) maps to a real-frame test or a reason; a new sentence fails the scan | PM17 `Handle.velocity` after the end (doc gap) |
| `test_noop_cost` | no-op cost (PM7) | every public method of every Entity kind through an empty group, every writable world setting written back: nothing joins the live roster | PM16 a Sprite / Text / Track method on an empty group raised |

## What the graphics review taught (2026-10-08)

A code review of Shape, Sprite, Graphic and Entity confirmed about 100 bugs
(catalogue: [GR](#gr--graphics-review-2026-10-08)). The suite had 6 300 tests,
and most had a point test near them. Each class guard was written before its
fix and failed on HEAD; together they found GR1–GR14 and about 1 000 more
cases the review had not listed (most of them one cause: a huge int, GR12). The
review is a sample; the guard is the census.

| Finding class | What the existing tests did | Why they missed it | The test that catches the class now |
| --- | --- | --- | --- |
| R1 write gate (a linked part written, or a free one refused) | `test_diff_link_write` linked slot fields one at a time | Property-backed pose (`angle` / `scale` on Sprite, Point, Polygon, Text), whole-object links and pivots were outside the list | `TestLinkWriteGate`: every kind × link target × pose verb against an **unlinked twin**: the parts its verb changes must refuse, the rest must succeed |
| R2 half-applied refusals | Tests asserted that a bad call raised | Nothing looked at the state after the raise | `test_refusal_atomic`: a full snapshot (geometry, pose, flags, groups, paint, registry census) before and after every dead / junk / link refusal (391 cases, then GR4, GR10) |
| R3 lifecycle state on a throwaway object | One transition per test (`active = False`, then `True`) | Callbacks lived on the Collider that park drops; the bug needed two transitions in a row, or another statement order | `test_collision_lifecycle`: every sequence of up to three statements vs a twin built in the final state (GR8, GR9) |
| R4 construction failure | Construction tests raised before `super().__init__` | The finish step (`setup()`, hooks, enroll) and a mixin's `__init__` ran outside the rollback | `test_construct_failure`: base × raise point × mixin layout, census and zombies |
| R5 shared mutable paint; caches keyed on less than they read | Paint tests used one shape; cache tests warmed and read one frame | `Color` was shared by every default shape; a warm hit for a different frame was never compared with a cold bake | `test_material_isolation` (every paint write × every relative); `test_cache_keys` (a warm hit equals a cold bake, for each `AtlasFrame` field; a new cache must be listed) (GR7) |
| R6 engine readers warm Derivates | `TestEngineReadersStayCold` with a hand list of readers and models | Hit tests and `is_collapsed` were not in the list; KINDS lacked models | KINDS for models, hit test and `is_collapsed` as readers; AST guard on the cold methods (GR5 triaged) |
| R7 copies | `sweep_c7` over `clone` | `<<`, whole `@=` and `absorb` were other doors; a copy that reads alike can diverge on its next verb | `sweep_c7` over every copy door, **copy then act** (both run the same verbs and must read alike) |
| R8 writes to names that are not fields | Typo guard for near misses | Methods, read-only properties and foreign geometry names were exact names, not near misses; batch 9a's guard enumerated the fix's own word list (GR14) | `test_route_table`: every method, read-only property and every field slot of any kind, from the instances |
| Clip playhead on summed time (PB3) | `TestDueOnTheExactFrame` covered timers | The playhead used its own `int(t * fps)` | AST guard: no `int(… * fps)` outside `reached` (GR6) |
| Two draw paths (PB7, PB8, HP10) | Draw tests rendered each knob once | The plain blit and the full draw read knobs differently | `test_draw_doors`: the same pixels on both paths, and every knob changes the picture |
| Numbers rule leaks (SA6, SA7, E12, …) | `test_hyp_surface` fuzzed constructors and slots; flags were walked by bool default | Property setters, point fields, verbs' `about=`, method flags and flags typed `Any` were outside the walk; no pool held `10**400` | `test_value_validation`: every setter by the value it reads, points through verbs, every flag found by default, annotation or bool property (GR11–GR13) |
| Slow paths on hot verbs (E15, SC10, SB11, …) | Benches measured scenes; unit tests checked results | A result test passes on the slow path | `test_hot_paths`: the fast path is taken on a free shape **and** lands where the slow path lands |

1. **A sweep is only as wide as its enumeration list.** KINDS lacked the
   relational models; the reader list lacked hit tests; the copy sweep had one
   door; the flag walk had one kind of flag. Enumerate from what the instance
   exposes (slots, `dir`, signatures, model enums) and add a coverage test that
   fails when something new has no case.
2. **Never enumerate from the fix's own list.** Batch 9a's route guard read
   `_SIZE_WORDS`, the list the fix had just added, so it could only confirm the
   fix (GR14). A guard's source of truth is outside the code it checks.
3. **A contract on one door is not a contract.** `clone` vs `<<`; the plain blit
   vs the full draw; slot setters vs property setters (`scale`, `mass`); the
   point reader vs a pivot read by hand (GR13). Put the rule in the one place
   every door passes, then test each door against the others.
4. **A refusal is a write path.** Test the state after the raise, not only the
   raise: gather, check, then write.
5. **State that must outlive a transition cannot live on an object the
   transition throws away** (E1: callbacks on the Collider).
6. **A shared default must be immutable,** or one mutation is global (HP1).
7. **A cache key covers every input of its bake, and a hit must not skip a
   check.** `showing(True)` hit `showing(1)`'s entry because `True == 1` shares
   a hash (PA7). Validate before the lookup, or key by exact type.
8. **Python's equalities cross types.** `True == 1 == 1.0`, `"no"` is truthy
   (`force="no"` unlinked: GR11), an int has no range (`10**400` passed every
   exact-int fast path: GR12). A fast path for a type must keep every refusal
   the slow path makes.
9. **Construction failure and statement order are lifecycle paths.**
   Enumerate the raise point and the order, not one happy sequence.
10. **A fast path needs two pins:** that it is taken (a spy on the slow path
    on a free shape), and that it lands where the slow path lands (a twin
    pushed onto the slow path by a Derivate read).
11. **Check a removal by its diff.** Deleting a function by text search ran
    into the next one twice in batch 10 (`get_xy`, the `Anchor` header); the
    import failed at once, but a diff shows the overshoot before anything runs.
12. **A test value equal to the current one hides the write.** The matrix
    linked a SPINE Rect's `angle` to the value it already had, so the refused
    heading publish was an unchanged no-op (GR15). Drive each field to values
    away from construction; the gate's Hypothesis machine found it, the
    deterministic matrix now sweeps three values.
13. **Tightening a leak pattern is a new guard run.** Counting "unhashable
    type" as a leak (batch 9b) failed three exports in the next gate (GR16).
    Run the slow fuzz after changing what it counts as a failure.

### Class guards written from the graphics review

| Guard | Lesson | Found beyond the review |
| --- | --- | --- |
| `TestKindsCoverEveryModel` | 1 | the relational models' sweeps: GR1 (documented), SB1 / SB4 confirmed |
| `TestLinkWriteGate` (unlinked twin) | 3 | 689 cases before batch 4 |
| `test_refusal_atomic` | 4 | GR3, GR4, GR10 |
| `test_collision_lifecycle` | 5, 9 | GR8, GR9 |
| `test_construct_failure` | 9 | — |
| `test_material_isolation` | 6 | — |
| `test_cache_keys` | 7 | GR7 |
| `TestEngineReadersStayCold` + AST | 1 | GR5 (by design) |
| `sweep_c7` (every door, copy then act) | 3 | — |
| `test_route_table` | 1, 2 | GR14 |
| `TestFrameCountsGoThroughReached` | 3 | GR6 |
| `test_draw_doors` | 3 | — |
| `test_value_validation` (+ `TestEaseNeedsTime`) | 1, 8 | GR11, GR12, GR13; `ease=` ignored by instant verbs |
| `test_hot_paths` | 10 | — |
| `TestLinkValuesAwayFromConstruction` | 8 (a value equal to the default hides a refused write) | GR15 |

## What the geometry campaign taught (2026-10-09)

A white-box campaign over the geometric model ([Geometry campaign](#geometry-campaign);
catalogue [GX](#gx--geometry-campaign-2026-10-08)) found 19 GX bugs, settled six
contract questions (Q1–Q6) and fixed them in five waves. Its harnesses have no
model of their own (shadow, laws, twins, influence, sentinel, value edges, a
fuzzer), so most findings were cells nobody had thought to write.

| Finding class | What the existing tests did | Why they missed it | The test that catches the class now |
| --- | --- | --- | --- |
| Timed and instant forms of a verb disagree (GX4, GX17) | Timed tests ran on free shapes; gate tests used the instant verb | The timed probe called the instant verb with "no change", which returns before its gate, and the rotate probe lacked the pivot rule | `TestTimedVerbsGateLikeInstant`, both directions, every Defining part linked alone |
| A motion's claim misses what it writes (GX6) | Link-conflict tests linked the claimed field | A turn claimed `angle`; the points it moves and a whole `@=` were not claimed | `test_process.TestTimedVerbsGateAtTheCall` (claims from the gate in record mode) |
| A store set, a cached reader stale (GX2, GR17-link, GX18) | Flip and link tests read once, after the verb | A cold cache recomputes on the read; the stale value shows only when it was read before | Sentinel I-heading on every outermost call; probes that read first |
| A gate exemption too wide (GX3) | Refusal tests used lengths away from 0 | At length 0 every point sits on the pivot, but the flip still turns a heading the relation owns | H1 degenerate bases (width 0, zero-length segments) |
| One coercion missing on one path (GX14, GX15) | Value sweeps reached `=` and slot fields | The link pull and the `vec` part read their values through another function | `test_geom_values`: every field × value × path, including a source that turns bad and then good |
| A relation left half-gone (Q3b) | Relational tests unlinked with `force=True` | `unlink_all`, a part's `unlink` and a destroyed reference were other doors | `TestARelationThatGoesLeavesTheFreeTwin`: every relational kind × every door |
| A copy applies a pose twice (GX10) | Copy tests used symmetric tracks | A mirror of a circle or a figure eight is itself | `TestCopyCommutes` (act then copy) over every kind, a flipped asymmetric track |

1. **A probe that calls the verb with "no change" is not a probe.** The verb
   returns before its gate (`_move_to` to where it is, `scale_by(1)`), or the
   call is not a no-op on every kind (it jumped a sheet-anchored sprite).
   Share the gate itself: one `_scale_gate` that the instant verb and the
   timed probe both run.
2. **A gate exemption reasons about one write; the verb makes others.** The
   pivot rule is right for the points a mirror leaves in place and wrong for
   the heading it turns where a relation owns it (GX3).
3. **Setting a store is half the fix when a cached Derivate reads it.** A verb
   that moves no point recomputes nothing (GX2). A probe reads the value once
   before the verb, or the cold cache hides the bug.
4. **A claim covers what the motion writes, from the same gate** (GX6), or a
   link on an unclaimed written part is accepted and the motion raises later.
5. **Link every part alone.** A matrix that links one picked field per kind
   tests one part; gates hold per part. The per-part parity guard found a
   timed turn of an anchored Text with a linked pin, which the picked field
   never reached.
6. **Degenerate bases are their own cells.** Width 0, length 0, scale
   `MIN_SCALE` and 0, a tall shape where every test used a wide one (GX1, GX2,
   GX3, GX5).
7. **A broad known pattern hides the next finding of the same invariant.**
   `I-heading | *` was listed for GR17-link and matched GX18; `* | * | link vs
   = | ok vs refused` covered GX14 and a contract difference (a link clamps a
   size where `=` refuses) under one key. List each finding's own signature,
   and re-triage the cells a removed pattern uncovers.
8. **Equal is not unchanged across types.** A cell holding `True` kept it
   through `= 1.0` (`True == 1.0`), so a link stayed refused. (Graphics review
   lesson 8 for change detection.)
9. **Removing a link must not fail on the link it removes.** `unlink()` and
   `destroy()` pulled a source that held a refused value and raised; the last
   good value stays.
10. **Run the sentinel after every fix wave.** Each wave's fixes uncovered the
    next layer: GX18 and GX19 after wave 2, a free twin's stale pose store
    after wave 5.
11. **Compensate perf at the site you change.** Moving each kind's scale checks
    into a shared gate cost up to 18 % until the instant verb skipped the gate
    when nothing in the tree was linked, which made `scale_by` faster than
    before; removing a duplicate gate paid for a new flip override.
12. **Coverage barely moves under combination harnesses.** Branch arcs grew by
    about 1 % on shapes; the findings were in states, paths and histories a
    branch ledger does not see. Measure suites with mutation on one pool, then
    run the survivors against the whole quick tier: the survivors it also
    missed were untested refusals.

### Class guards written from the geometry campaign

| Guard | Lesson | Found |
| --- | --- | --- |
| `TestTimedVerbsGateLikeInstant` (every part linked alone) | 1, 5 | GX4 (584 cells), GX17, the anchored Text pin |
| `test_process.TestTimedVerbsGateAtTheCall` | 1, 4 | GX6 |
| Sentinel (`run_tiers.py <tier> --sentinel`) | 3, 10 | GR17-link, GX7, GX11, GX18, GX19, the free twin's store |
| H1 shadow (degenerate bases) | 6 | GX1, GX2, GX3, GX5 |
| `test_geom_values` (every path; a source that turns bad) | 7, 8, 9 | GX14, GX15, `True` kept through `1.0`, unlink on a bad source |
| `TestARelationThatGoesLeavesTheFreeTwin` | — | Q3b |
| `TestCopyCommutes` (act then copy) | — | GX9, GX10 |
| H10 fuzzer (`test_fuzz_corpus`) | — | GX16, GX17 |

## What the game system tests taught (2026-10-10)

1. **A Guia pattern used in a real game is a test the unit suites do not
   write.** Six of the eight engine bugs (AC6, AC7, AC8, AC9, AC11, AC13)
   broke a pattern the Guia shows: a ground flag that reads its owner, a
   formula group declared with `@=`, a collide method, a long `until_empty`
   wave, the loop-variable default, a named tween refreshed. Each unit test
   had used the feature in the shape that worked; the game used it the way an
   author would. Run the pattern itself, as a small program, in real frames
   (`test_documented_patterns`; 7 of its 9 programs fail on the code before
   the fixes).
2. **A warning has two sides, and the tests held one.** AC7 and AC13 were not
   untested warnings: measured with a recording hook (`tests/warning_sites.py`),
   both fired in existing tests (`test_frozen_mode_warns_once`, the driver
   composition suite). What no test ran was the legitimate pattern next to
   the warning. Every warning site now has a row that names the test that
   fires it and the test that keeps its twin silent, or says why it has no
   twin (`test_warning_contracts`). A first draft of this lesson said "no
   test covered the warning"; the measurement corrected it. Measure the
   coverage claim before writing the guard for it.
3. **A feature shared by families is asked of every family.** AC2 (class
   keywords) and AC6 (collide methods) each worked on some families and
   failed on others, and each family's tests asked only about its own way.
   Asking all 34 exported Entity classes the same questions
   (`test_subclass_parity`) found, on its first run, nine more families that
   answered a class keyword with Python's own error (Text, the widgets,
   Entity, Endless), a Track that accepted `color=` / `group=` on the class
   line and dropped them, a Fire subclass that ignored `style=`, and a
   Polygon whose own field cannot read its centre (AC14, a documented limit).
4. **Silent acceptance is the worst answer.** The Track class keywords and
   the Fire subclass `style=` were taken and ignored: no error, no effect. A
   value the engine will not use raises with the fix. `Anchor.draggable =
   False` was a no-op documented only in a docstring; it raises now (AC16).
5. **Check the check reaches what it compares.** HV1: the pixel oracle passed
   for every program while comparing two blank frames. An oracle that
   compares two outputs also checks that one of them shows something.
6. **What a program defines must die with it.** AC1: module-level caches keyed
   by an author class kept the class, its module and every global. Per-class
   data lives on the class; the parity guard collects a subclass of every
   family.
7. **White-box models need the frame phase.** The first edge and change models
   failed on correct engine behaviour: a widget's write lands before the
   frame's sample, an update write after it. The phase rule (see
   [Game system tests](#game-system-tests)) is part of the model, not a
   tolerance.
8. **A fix gets the quick tier before the gate, and a perf A/B.** The AC7 fix
   failed twice in `quick` (a mode idle from birth warned late; a weak-keyed
   record held a dead act through its bound-method mode), and its A/B showed
   the cost moved to the owner write. Each fix here was measured against the
   pristine tree with an interleaved best-of run.
9. **An existing suite keeps finding things while the code moves.** AC12
   (unlink cut the readers of a field) came from `test_hyp_api`'s state
   machine during this work, on an example that fails on the earlier code too.
   A Hypothesis failure that also fails on HEAD is a finding, not noise.

### Class guards written from the game system tests

| Guard | Lesson | Found (would have caught) |
| --- | --- | --- |
| `test_documented_patterns` (each Guia pattern next to a warning, in real frames, warnings recorded) | 1, 2 | AC2, AC6, AC7, AC8, AC9, AC12, AC13 |
| `test_warning_contracts` (every warning site: the test that fires it and the test of its silent twin, or a reason); `tests/warning_sites.py` measures the `fires` column | 2 | AC7, AC9, AC11, AC13 (a new warning cannot land without its silent side) |
| `test_subclass_parity` (every exported Entity family: class keywords applied or an author error, collide methods get `(other, info)`, an own field that reads the object dies quietly, the subclass is collected) | 3, 4, 6 | AC1, AC2, AC6, AC11, AC15; pins AC14 |
| `test_author_class_lifetime` (the caching paths) | 6 | AC1 |
| `test_fieldref.TestUnlinkKeepsReaders` | 9 | AC12 |
| `test_program_support.TestDrawReachesThePixels`; `cull_pixels` refuses a flat frame | 5 | HV1 |
| `game_harness.problems` (an unexpected SCENA warning fails a game run) | 2 | — |

## Planning a new test

1. **Enumerate from the source of truth**, not a hand list: slots, `__all__`,
   models. Add a coverage test that fails when a new class has no subject
   (`TestEveryReactiveClassIsDriven`).
2. **Name the axes before writing a case:** write path (`=`, constructor, link on
   a field, on a part, on the whole object, copy, batch, pose verb); read order
   (cold, warm, source first, link first, reversed); source value (NaN, out of
   range, bool, list, state cell, longer sequence, `10**400`, `"no"` for a flag);
   construction model, and every ordered pair of models for copies; lifecycle
   (install, change, unlink, relink, destroy, park and resume); **refusal source**
   (dead, junk, linked, parked); **copy door** (`clone`, `<<`, whole `@=`,
   `absorb`); **draw door** (plain blit, full draw); **statement order**; a
   **read before the verb** (it can move a shape off its fast path); **base
   layout** (a mixin first or last) and **raise point** for construction;
   **instant vs timed** form of a verb (refused at the call, never from a
   tick); **each Defining part linked alone**, not one picked field;
   **degenerate bases** (size 0, length 0, `MIN_SCALE`, a tall shape).
3. **Pick an oracle with no model of its own:** a plain-write twin read at the
   same moments, or the source itself. For a gate, an **unlinked twin**: run the
   verb on it and record which parts changed; on the linked subject exactly
   those parts must refuse (`TestLinkWriteGate`). For a lifecycle, a twin built
   directly in the final state. For a cache, a cold bake. For a fast path, a
   twin pushed onto the slow path. For a timed verb, its instant form. For
   a relational shape that loses its relation, its free twin. Build the
   oracle's setup apart from the subject; list fields from a throwaway
   instance.
4. **State the invariants** the cells check: linked reads like written in any read
   order; one rule set on every path; unlink freezes; two reads agree; a conflict
   is refused at install and installs nothing; clean means recomputed; a copy
   reproduces its source; one reading of a point.
5. **Make the test check itself** ([Lessons learned](#lessons-learned) 10, 11, 19):
   a not-vacuous assertion, activity counters, a canary per known bug, the probe
   fails on HEAD before the fix, shrink-only known lists with reasons.
6. **Use three layers:** a deterministic matrix in `quick`; a Hypothesis machine in
   `gate` / `deep` (composite rules, so the budget reaches the interesting state;
   a narrowed pool for a canary); static guards that turn each documented rule
   into a check (`test_write_path_guards`, `TestOneCoercionForEveryPath`,
   `test_rect_frame`).
7. **Pin derived tables to their source in both directions**:
   `_heading_driven_parts` equals what `rotate_by` refuses (`test_heading_link`).
   A table the engine reads is not its own oracle: the exclusive inputs are
   found by writing each one and watching the heading (GR19).
8. **Every fix gets an A/B against HEAD** (alternating or in-process; noise is
   about ±2 %), with the same weight as its test.
9. **Write the documented sentence as the oracle** before reading the
   implementation; when the docs are silent, settle the contract first
   ([What the program-model campaign taught](#what-the-program-model-campaign-taught-2026-10-08)).
10. **Run frame-scoped behaviour in frames**, with the author's `dt`, and in a
    process where something else ran first.

## Invariants and assertions in code

- **One home per rule:** slot metadata or one function, never an override that one
  path runs.
- **Static guards for structure, runtime checks for values:** an AST guard costs
  nothing per frame. A runtime "recompute and compare on every read" mode was
  weighed and dropped: the test-side oracle is that check. Its whole-suite form
  is the sentinel (`tests/geom_sentinel.py`, `run_tiers.py <tier> --sentinel`):
  invariants checked after every engine entry point through `sys.monitoring`,
  with nothing in the engine.
- **Allowlists carry reasons, and a stale entry fails.**


# Recurring bug classes

Findings from different suites keep landing in the same few classes. A fix for one
member should ask whether the siblings share the cause.

| Class | Members | Guard |
| --- | --- | --- |
| **A verb on a dead actor registers work or revives it** | H2 (`layer =`, `tag`), S5 (`mode =`), S8 (transient replace), S9 (`after` / `every` / `tween` / `play_sound` / `on_update`), W2 (`@=` onto a dead actor or a part it left behind), A6 (`resolve_now` re-enrolled the collider), A7 (a first read wired a dead widget into the graph; `Line(circle=dead)`; `Track.reversed()`), HB1 (hitbox writes on a dead or removed hitbox), SA10 (`center =` moved a dead shape), E14 (dead setters stored, flips), HP7 / HP9 (dead paint and hitbox reads), HP12 (`remove_hitbox` silent), GR3 / GR4 | `test_sys_hyp_world` poke rule; `test_hyp_surface.TestDeadEntityVerbs` (P6: every public method and setter of every Entity kind; canary S9); `test_refusal_atomic` (dead source: nothing changes, reads stable); teardown's `_DeadRoute` refuses every routed write |
| **A registry keeps a dead owner** | H3 (id map; retired with ids), S1 (bound method in a `WeakKeyDictionary` value), S3 (`id(owner)` keys), S4 (dense snapshots), S6 (`_pair_targets`) | `census` / `zombies` / `assert_collected` in the system suites; `test_act.TestNoLeaks` (a busy scene — `kitchen_sink` plus timers, effects and rules made in the scene — changed N times: stable census, no zombies; 200 cycles with `SCENA_SOAK=1`) |
| **State leaks from one act into the next** | SC1 (an unread `keyp.once` edge fired in the next act; generalized by PM3), a new canvas / clock / collision setter that an act change neither restores nor keeps on purpose | `test_act.TestSettingsClassification` (walks every settable name on `canvas` / `clock` / `collision` / `audio` / playfield / layers / effects / background and the exported `set_*` / `show_*`; each must be in `WORLD_SETTINGS`, `KEPT_SETTINGS` or the test's `NOT_SETTINGS`); `TestWorldSettings.test_the_test_changes_every_restored_setting` (guards the guard); rule: **anything the author can change globally is classified when it is added** |
| **A deadline compared on summed frame time** | PM8 (`after` / `every` / tween end / `ready` / `recently` / transient progress fired a frame late or on time by rounding), PB3 (the clip playhead), PB4 (one-shot end, `next=`), GR6 (SpriteButton state art) | `process.reached` for every "is it due" comparison; `test_process.TestDueOnTheExactFrame` (any fps, any whole number of frames). A new timed mechanism compares through `reached` |
| **A cheap-looking read or no-op builds a registered Entity** | PM7 (a verb on an empty group built a `Blank` Shape per call); PM16 (a non-Shape method on an empty group raised); `canvas.game_view.center` builds a Point (~70 µs) per read (by design: a Box is a value, a Point an entity) | `test_noop_cost` (every Entity method through an empty group, every world setting written back); `program_oracles.probe_neutral` (a run with probes vs without: GC-timed roster entries show up) |
| **A cell is refused where a number is accepted** | PM12 (`deadzone`), PM15 (`amp_db`) | `test_cells_as_numbers` (every exported function, every number argument); `test_hyp_surface` (slots, verbs, constructors) |
| **One payload, two doors, two views** | PM11 (`test_collision` vs handlers), PB7 / PB8 / HP10 (plain blit vs full draw), SC7 / SB7 (`clone` vs `<<` / whole `@=`), SA7 / E12 (slot setters validated, property setters not), GR13 (a pivot read past the point reader) | `test_collision_doors`; `test_draw_doors`; `sweep_c7` over every copy door; `test_value_validation` |
| **An unread edge outlives its frame** | SC1 (act change), PM3 (any later first reader of `keyp.once`) | `KeyPressed._expire_edges` at the end of every frame; `test_keyp.TestOnceChordProperty` with frame boundaries |
| **A rejected call half-applies** | H1 (constructor registers then raises), H4 (`layer =` unregisters then fails), R4 (register auto-created a layer before the id check; retired with ids), A10 (`fade_in` shows before validating; `tangent_lines_from` keeps the first line), W3 (a raising formula left its ink cell and anchor) | constructor census in `test_hyp_api`; "claim nothing before every check passes" in `Registry.register` |
| **Routing picks the wrong writer** | S10 (`_write_field` ink path on a property-backed field), R1 (a second `__init_subclass__` replaced the first, so `Rect.rotation` routed to `Shape.rotation` and recursed) | `test_entity_hooks` (no duplicate `def`; every subclass has its own route) |
| **An engine error reaches the author** | verb `float()` leaks, `chance(True)`, `line_width`, H7 (`int(…, 16)`), A1 (unhashable key in `keyp` / `ready` / `recently` / `obj` (removed) / `canvas.layers[]`: **validate the type before any dict / set lookup**), A3–A5, A7 (`float(finite(fn))`), A8 (`finite` at a fixed site; `** 2` overflow), HB2 (Python's "property has no setter" on hitbox fields) | `leak_message` in every property; `test_hyp_surface` (P2 on every export); AST guard `TestNoFloatAroundFormulaValidators` |
| **A dead Entity is falsy** (`Entity.__bool__`) | R9 (`self._alias_of or self` fell back to a reversed view's empty tables once the host died) | `test_entity_hooks.TestNoTruthinessFallbackOnEntities` (AST: no Entity-holding attribute as an `or` operand); rule: `is not None` for Entity-or-None |
| **A raw-store site calls the dispatcher** (`_x` is the dispatcher, `_x_impl` the hook — a rename flips what an old `_x` call means) | A7 (`Square._takein_impl` → `super()._takein` → `self._takein_impl` … recursed), B1 (pull resolvers kept `_takein` after the rename: every read re-walked the cone) | `test_entity_hooks.TestHooksDoNotCallTheirDispatcher`; `test_pull_no_invalidate.TestPullResolversStoreRaw`. On any rename of a dispatcher / hook pair, re-map **every** old call site by meaning, not by spelling |
| **A guard lands on a per-frame path** (correct check, general-case cost paid every frame) | B2 (`validate.finite` / `_finite_deg` ABC path on every `move_by` / `rotation =`) | `tests/test_hot_validators.py` (`TestHotPathsStayHot`). Rule: a validator on a verb tests the exact common type first; the bench pulses catch what the unit suite cannot |
| **Engine code calls an author-facing lookup that guards or warns** | SC4 (`until_empty` polled `group[name]`; its near-miss typo warning fired on an emptied, dropped bucket) | Rule: engine internals read the registry / engine state directly; author guards (typo / near-miss warnings, `DestroyedError` hints) run once, at the author's call site, never in a per-frame poll |
| **A hand-kept list drifts from the code** | R8 (`_formula_knobs` missed reactive pad fields), SK1 (`SCENIC_PRESET_NAMES` / `_SKY_ALIASES` named ramps the table lacked), SK2 (smoke preset strings no preset has) | `validate.formula_knobs(cls)` derives from field slots; `TestReactiveKnobsTakeFormulas` walks every export; `test_gradient_presets.TestSkyPresetNamesResolve` (every advertised / aliased / suggested sky name builds a sky; smoke literals scanned). Rule: an error message lists only names that resolve — filter the list through the same lookup the call uses |
| **A cache hands out objects callers mutate** | D2 (`_poly_cache` Prims shifted in place by `_translate_prims`), K4 (interned looks: `Neon("red").color = …` repainted every user and poisoned the intern cache) | `TestPolygonCacheAliasing.test_no_cache_hands_out_the_prims_it_keeps`; `test_registry_key_fields.TestInternedLooksFrozen` (every exported interned look / filter); rule: a cache returns clones, or what it hands out refuses writes |
| **A handle field doubles as a registry key** | K1 (`Layer.name` vs `canvas.layers`), K2 (`Handle.name` / `.owner` vs the scheduler slot `(id(owner), name)`), K3 (`shape.group` returned the live set; in-place `add` skipped `group_map`), K4 (interned look fields vs the intern key), K5 (`Entity.id` vs `id_map`) | `tests/test_registry_key_fields.py`, `test_registry_layers` (`test_name_*`); rule: a field a registry is keyed by (or mirrors) is a **property whose setter raises** with the create-and-move / re-schedule spelling, or a read-only snapshot (`GroupTags`, `frozenset`) that the registry swaps — never a plain attribute or a live container. Internal writers set the private slot |
| **A per-frame throwaway enters the graph** (a value built to be read and dropped registers nodes; its tree is a reference cycle, so only a full GC frees them) | D11 (a measured Box's point part; views, group box and widget box were eager Boxes) | `test_box_snapshot.TestMeasuredPointsStayOffGraph` (count with the cyclic GC off); `test_leak_detector.TestGcChurnIsNotALeak`. Rule: an engine read that hands out a fresh Container every call (a snapshot, a measurement) keeps it off the graph until linked — a measured Box is `Box._snapshot` / `Box._from_aabb`, never `Box(p1=, p2=)`; its test counts graph nodes with `gc.disable()` |
| **A fast path or cache disagrees with its reference** | D2 (poly cache), D4 (intersection GJK reused as a distance), D5 (support = first vertex within tie_eps) | `test_diff_*` + canaries |
| **An oracle is stricter than the contract** (false positive) | D10 (prims compared in a raw-float sort order; the engine promises neither order nor bit-exact translation), G2 (contacts compared exactly across a world shift; the engine promises no answer at exact tangency) | `test_diff_collision.TestPrimsOracle` (drift + shuffle + built ties, every model); canary `test_oracle_guard_catches_a_sorted_compare`; `test_sys_hyp_collision.TestTangencyTolerance`. Rule: before calling a property failure an engine bug, check that the documented contract promises that exact answer; a float boundary (tangency, ties) needs an ε "either" band |
| **Pull reactivity: a value depends on who read first** | D8 (`unlink` froze the unpulled value; destroy auto-unlink too) | `test_diff_reactive` link model + `chain` op; `TestUnlinkFreezesTheCurrentValue` |
| **A mirror is applied as a rotation (or twice)** (a flip moves the shape, or relabels its parts as if turned) | G3 (`POINT_VEC` `flip_x`: `180 − θ` plus `vec.x`), G4 (`SPINE` side anchor kept its side), G6 (triangle mirrored `rotation`, not its heading; `vertex=` polygons turned about the vertex), G7 (`.box` of a flipped Graphic kept the turned angle but dropped the mirror), the pre-2026-09-29 Rect flip (`flip_x` sent `top_right` to the bottom left: names rotated 180°, not mirrored) | `test_rect_names.TestFlipMirrorsNamedPoints` + `test_flip_mirror.TestFlipMirrorsEveryKind` (every kind, drawn geometry) + canaries. Rule: a flip is checked on **every named / Defining point** (lands on its mirror about `center`) and on the region (does not move) — not on one read-back |
| **A Derivate is missing from the update's write list** (filled on first read, then stale) | G5 (`vec` on Rect / Box / Line — also not pulled through its owner), G8 (RegularPolygon stats on their first read) | `test_rect_names.TestDerivatesMatchAFreshTwin` + canary. Rule: a new Derivate part is added to every `_update_impl_*` that owns it, and the fresh-twin check covers it |
| **A kind implements a shared verb its own way** (flip, clone, `rotation`, a Derivate refresh: each kind hand-rolls it, and siblings drift) | G3 / G4 / G6 (flips moved or relabelled shapes), G5 / G8 (Derivates missing from a kind's write list), the 2026-09-30 contract sweep (Track flips change nothing; clones drop pose on every kind; Line `rotation` ≠ its heading) | `test_geometry_contract` (C1–C8 over every kind × model × verb × part, shrink-only `geometry_known.py`, canaries). Rule: a new kind, model or verb joins `geometry_support.KINDS` / `VERBS` in the same change — the sweep then checks it against the whole contract |
| **An engine reader warms a cold Derivate** (performance) | D3 (per-frame readers / pose verbs knock 12 of 24 shape models off the pose fast path for good) | `test_diff_pose.TestEngineReadersStayCold` (shrink-only allowlist) |
| **A count reads a structure with holes** | D1 (`len(layer._objects)` counts tombstones) | structural guard in `test_registry_layers`; `Layer._live_count` |
| **A doc cites a test that does not exist** | Six design docs cited `tests/test_registry_layers.py` (written ahead of the Scene-rename step 2) while the file was still `test_scene_layers.py`. **Rename a test file and its citations in the same change** | `test_doc_citations.TestDocCitations` (every cited test file and dotted test name in live docs; the private `archive/` and `proposals/` exempt) |
| **A published file cites the private workbench** (a design doc, code comment, test docstring or script names a file in the private `archive/` / `proposals/`; those folders are not published, so the link dies and the reason it pointed at goes with it), or a relative link points at a moved file | DL1 (2026-10: ~45 citations in 14 design docs, 6 tests and code, and 5 bench pages; 8 of them already dead because the proposal had moved to `archive/` or never existed) | `test_doc_links.TestDocLinks` (every published `.md` / `.py` / `.html` / `.txt`, including paths joined in code) + `TestScanner`. Rule: the living doc carries the conclusion and its reason — see [README — Private folders](README.md#private-folders) |
| **Bundled media without its license or credit** (a file Scena redistributes, but an author cannot tell how to use it) | ML1 (`examples/media/images/`, then `backgrounds/`, had no license file; `audio/laser4.wav` / `laser7.wav` were marked CC-BY 3.0 with no author, so no credit could be copied) | `test_media_licenses.TestMediaLicenses` (every media folder has a `license.txt`; every top folder is in `examples/media/CREDITS.md`; every file that a notice puts under CC-BY / CC-BY-SA has a credit block under "Attribution required", and every credited file exists) + `TestCodeLicense` (MIT `LICENSE` declared in `pyproject.toml`). Rule: add media only with its notice, never NC / ND / unlicensed |
| **A media path is dead and nothing says so** (a missing image or sound is a `SCENA WARNING` and a placeholder; the script still builds and plays) | MR1 (the `scripts/examples` → `examples` move and the media reorganization left ~170 paths dead in examples, smoke, bench and tutorial), MR2 (media-backed tests `skipTest` on a missing file: the suite stayed green), MR3 (`test_scripts_run` scanned the old `scripts/examples` and found nothing) | `tests/test_media_refs.py` (every literal media path in `examples/`, `scripts/smoke/`, `scripts/bench/` resolves like the engine resolves it; `_media.py` lists exist; every media name in the tutorial exists under `examples/media/`). Rule: tracked media → `tests/media_support.media()`, no skip-if-missing; a move or rename of a media folder runs `test_media_refs` and updates `CREDITS.md` |
| **A program fails only after time passes** (a check runs a few frames, or skips the collision pass; the bug needs a hit, a timer or a destroyed actor) | TU1 (tutorial 05: the ship is destroyed by a shot, `update` keeps steering it) | `test_tutorial_steps` runs every step 600 frames through the real frame body with `random` seeded. Rule: a script check runs long enough for its timers and collisions to fire, and deterministically |
| **A program only works at a fixed frame time** (the harness steps a constant `dt = 1/60`; a real run has hitches) | TU5 (tutorial 05: the fleet bounce `if past_edge: v = -v` sticks at the edge after one short frame) | `test_tutorial_steps.TestFleetBounce`: a driver gives the frame after the first turn a 1 ms `dt` and counts turns over 20 s, for every tutorial step and example that moves the fleet by `st.velocidade`. Rule: a bounce sets the direction (`v = -80` past the right edge), never flips the sign |
| **A check only looks where a body ends** (a per-frame sample misses what happened between frames; how much it misses depends on the frame rate) | CT1 (fast `@collide` shots tunnelled), CT2 (a fast body pushed into a resolve wall never fired `@collide`) | `tests/test_sys_fast_shots.py` (the same hit set at every pacing), `test_sys_hyp_collision.TestFastMotionAgainstSweptOracle`. Rule: a contact rule is tested at 30 Hz and uneven pacing with movers that cross a target within one frame, not only at 60 Hz with slow movers |
| **A script is left on a retired spelling** (the engine moved on, the script never ran) | SR1 (`smoke/colliders.py`: `shape.group.add`), SR2 (`bench/historical/galaga.py`: `Text(x1=, y1=)`, `set_framerate`), SR3 (five smokes: `keyp.once(",")` / `"."`; `app_glowspot`: `"["` / `"]"`) | `tests/test_scripts_run.py` (**Scripts run headless**: every `examples` script builds and plays 30 frames in its own process) and `tests/test_smoke_scripts.py` (every `scripts/smoke` script, plus listed benches; `SLOW`). Rule: an API rename or removal runs both modules in the same change; a script that drives its own loop (not `run()`) is not covered |
| **A color name Scena does not know** (CSS / X11 habit; warns and paints magenta, so nothing fails) | SR4 (`"slategray"`, `"mediumseagreen"`, `"medium turquoise"`, `"slate gray"`) | `tests/test_color_literals.py` reads the literals statically, so click-only paths and Guia snippets that never run are covered too |
| **A message uses a word reserved for an author concept, or the concept's old name** | "Scene-level after(..., then=)" (meant script level), "not scene bodies" (meant world space), "scene objects rising" (meant registered objects) — all wrong once the author concept existed (named Scene from 2026-09-28, `Act` since 2026-10-06); after the 2026-10-06 rename, any "scene change" / "current scene" left in a message or doc | `test_message_vocabulary.TestMessagesDoNotSayScene` (AST scan of raise / warn / error / message literals in every `scena/` module, `act.py` included; allowlist only for the rendered-frame sense and the retired-name error); `TestDocsDoNotUseRetiredSceneTerms` (live design docs: the registry / script-scope terms of the 2026-09-28 rename); `TestDocsDoNotUseSceneForAct` (live design docs: the old class and verb names, "scene change", old doc links; `Act Design.md` keeps the naming history); `TestGuiaDoesNotSayCena` (Guia sources + generated index: no "cena" at all; the old names only in the 0.6.0 rename note) |
| **The old brand survives a rename** | After Stage → Scena (0.6.0): a string like `"stage.x"` in `mock.patch` / `sys.modules` (a regex on `stage.` missed the ones not followed by a letter), a no-dot `startswith("stage")` that also matched the editor, a guard regex still looking for `stage._x` (it passed by scanning nothing), a relative link `../stage/…`, a local variable named `stage` that a module rename would have broken, a message or sentence naming Stage | `test_message_vocabulary.TestNoStageBrand` (AST: no `stage` / `stage_editor` import or module string in code; no Stage / STAGE in messages; no Stage, `stage/`, `stage_editor`, `stage-editor`, `from stage` in published text). Allowed: lines naming 0.6.0 or a `LEGACY` name, the `"stage-level"` tag, the old `Stage Editor` launchers, `PostEffectStage` / pipeline stages, Act Design's Naming section. Package-name checks go through `scena/_pkg.is_framework_module` (no literal to rename next time) |
| **A derived pose lags an input that never notifies** | T1 (view `Text.center` vs the string: formula text is pull, and `font_size` / `flash_text` / fill material are not graph nodes) | Refresh at the read, not at the write: `_TextCenterSlot` + reconcile in `_refresh_layout`; `TestViewPinMotionProperty` (random string changes interleaved with every pose writer) |
| **A link is read as a one-shot write** (a model that keeps its own pin re-derives a linked input from that pin, so the link holds only until another input moves; or the model's Defining set is fixed at construction, so a runtime link leaves a sibling input writable against it) | GX20 (anchored Text: a linked `center` moved when the string changed; the anchor stayed writable) | `test_text.TestLinkedCenterIsThePin`; the reactive-matrix oracle (`test_hyp_reactive_matrix`: a linked field reads its formula after every move, whatever else links). Rule: while a part links it is an input the model keeps, never one it recomputes; the parts that would fight it turn Derivate for as long as it links |
| **A test depends on what ran before it** | O1, O9 (graph-node baseline taken with an earlier test's garbage still pending) | `run_tiers.py` gate runs every module in its own process (a test that needs a predecessor fails there); deep's serial pass catches the reverse (a module that breaks its successors); graph counts: `test_count_baselines` (static: every `len(<…>.nodes)` in the tests follows a settle; dynamic: garbage planted, a collection forced at each assert). Rule: settle garbage before count baselines ([Harness pitfalls](#harness-pitfalls)) |
| **A contact is judged on a pose that is never drawn** (frame-time dependent) | F1 (resolve skin read as a gap by the pre-resolve snapshot), F2 (accepted limitation: the pre-resolve pose sinks by g·dt² against a corner) | `tests/test_sys_resting_contact.py` (every kind × pacing incl. uneven 5 / 28 ms × far offset). Rule: a contact rule on a resolved pair must hold at 60 Hz, 200 Hz and uneven pacing; test with alternating short / long frames, not only 60 Hz |
| **Event-driven level state goes stale** (a level recomputed only on an input event misses every other way it changes) | PH1 (`pointer_hover` recomputed only on mouse moves: stayed True after hide / `clickable = False` / moving away, a new target on top never took it, a widget did not clear it) | `tests/test_pointer_hover.TestStaleness` (every way out, pointer still) + `tests/test_hyp_hover` (exit guarantee; tiered == brute force; edges alternate; a never-exit mutation fails it). Rule: a level is re-validated **per frame** at O(1) and fully recomputed when any of its inputs changes (pointer, an epoch the writers bump, layer stack) — never only in one input's callback |
| **A test passes only on the Mac** (it relies on a platform default or on a clean tree) | WP1 (scans read AppleDouble `._*` files), WP2 (pixels read in `kN32` order), WP3 / WP7 / WP18 (wall-clock budgets and ratios under load), WP5 / WP8 (text in the locale encoding), WP6 / WP11 (POSIX literals as expected paths or labels), WP9 (a gate test needs a package the `test` extra lacked), WP10 (old runner logs copied Hidden), WP12 (the exec bit asserted on Windows), WP13 (a Hypothesis module on Hypothesis defaults), WP14 / WP15 (a clock read twice, a hang timeout sized for an idle machine), WP16 (child output decoded with the locale), WP17 (paths sorted with the host separator; a test that needs a Mac font), WP19 (a `/` path joined onto a `\` root) | `tests/test_platform_portability.py` (AST: no bare directory scan in `tests/`; every `toarray` / `fromarray` in `scena/` and `tests/` names `colorType=`; every text `open` / `read_text` / `write_text` in `scena/`, `scena_editor/`, `tests/` names `encoding=`; every `S_IX*` / `X_OK` in a test names the platform; a test that writes a transient's `t0` pins the clock; every text-mode subprocess names `encoding=` / `errors=`; a test helper's `os.path.join` of a parameter or of a `/` literal is normalized), `test_run_tiers.TestHypothesisProfileGuard`. Rule: never rely on a default that differs by platform — name the byte order and the encoding, scan through `source_support`, build expected paths with the same path function, time as a ratio |
| **State lives on an object a transition throws away** | E1 (`on_collide*` on the Collider that park and `collidable = False` drop), E2 / E3 / E11 (park stash written on one path only) | `test_collision_lifecycle` (every sequence of up to three lifecycle statements vs a twin in the final state). Rule: state that must outlive park / opt-out / resume lives on the actor |
| **A shared default is mutable** | HP1 (`Color.alpha =` faded every default shape), K4 (interned looks) | `test_material_isolation` (every paint write × every relative). Rule: a shared default is immutable; a write gives the writer a new object |
| **A cache key misses an input, or a hit skips a check** | PA2 / GR7 (trim offset, `rotated`), PB10 / PB11 (envelope, source rect), PA7 (`True` hit `1`'s entry) | `test_cache_keys` (a warm hit equals a cold bake per field; every module cache listed). Rule: the key holds every input of the bake; a hit is reached only after the type check |
| **A fast path skips a refusal the slow path makes** | GR12 (`10**400` through every exact-int fast path), B2's inverse | `test_value_validation` (`10**400`, NaN, `True`, `"x"` on every setter). Rule: a type fast path keeps every refusal of the slow path (an int is bounded like a float) |
| **A second store of one value lags** (a cache of a field written on some paths only) | GR17 (`_rotation` vs a Defining `angle` slot), T1 (Text center vs its string) | `TestPoseStoreFollowsTheHeading` (store vs value after any two verbs). Rule: a second store is written on every path that writes the value, or not kept at all |
| **A guard enumerates from the fix's own list** | GR14 (the route guard read `_SIZE_WORDS`) | `test_route_table` enumerates every field slot of every kind. Rule: a guard's source of truth is outside the code it checks |
| **A measured value satisfies the no-sources guard** (a formula's dependency walk lands on a fresh snapshot Container, so the guard sees a source that nothing updates) | RX1 (`canvas.game_view`, `layer.view`, `graphic.box` in a formula) | `state._is_durable_source` (a deferred tree is a value; the Container before it is the source); `test_canvas.TestCanvasIsAFormulaSource`. Rule: whatever hands out a measured snapshot is itself a Container that notifies when the measurement changes |
| **A copied pair side keeps a destroyed body** (a list or snapshot taken at registration time is pruned on destroy only where someone remembered it) | HD1 (group-operator snapshot), HD2 (the sealed `resolve` pairs), HD3 (the act-level handler list), S6 / D6 (`_pair_targets`) | `test_sys_holders` (`scan` finds every path, no list is named by hand); rule: every list that holds pair sides is pruned by **one** function, `CollisionSystem._prune_dead_side`, from `drop_pair_handlers_for` |
| **A close path lives in a `destroy` override that `registry.destroy` bypasses** (an act change, a layer drain and a group destroy call the registry primitive) | HD5 (`Menu.destroy`) | `test_menu.TestRegistryDestroySettlesTheMenu`; rule: per-kind teardown goes in a hook the registry teardown reaches (`_settle_on_remove` from `remove_widget`), never in an override of the public verb |
| **A manager field is cleared on some removals only** | HD4 (`last_click`), PH1 (hover target), E1 | `test_sys_holders` partial and gone enders; rule: `remove_widget` / `forget_destroyed` clear **every** field of the manager that can name a widget or shape |
| **A constructor touches a raw input before linking it** | C1 (`Line` home `length` / `angle` via `number()`), C2 (Ellipse focal `get_xy` / `float`), C3 (Box spine `height = float()`), C4 (rotated-corner `_takein` rewrite), C5 (`corner_radius` storing a function), C6 (fixed knobs with a raw or generic message) | `tests/test_ctor_links.py` (every signature, every geometry key: a lambda follows, and a lambda of the same numbers builds the same shape) |


# Bug catalogue

Series: **H** Hypothesis batch 1 (`test_hyp_*`), **R** regressions caused by fixes,
**S** system suites (`test_sys_*`), **A** API surface, **D** differential, **W** world
machine extensions (M4), **O** order / isolation (a test that depends on what ran before it), **G** geometry properties (transform algebra, round trips, invariance), **F** contact flicker (what a player sees across real frames), **CT** continuous detection (fast bodies between frames), **CS** closed surfaces (a write to a name the object does not have), **GR** graphics review (2026-10-08: Shape / Sprite / Graphic / Entity; the review's own IDs SA / SB / SC / E / HP / PA / PB are kept, members its class guards found are GR1…). "Guard" is the regression test in the owning file.

### H — Hypothesis batch 1 (2026-09-25)

| ID | Bug | Shrunk repro | Root cause | Why earlier tests missed it | Guard |
| --- | --- | --- | --- | --- | --- |
| H1 | Failed constructor left a registered zombie | `Circle(color=False)`; `Circle(layer="missing", id="a", group="g")` | `register()` ran before later validation; nothing rolled back | Tests asserted the raise, never the registry after it | `test_api_robustness.TestLifecycleContracts.test_failed_constructor_leaves_no_roster_or_draw`; `test_entity_hooks.TestConstructionIsAtomic` |
| H2 | Verbs on a destroyed Entity revived it | `c.destroy(); c.layer = "top"` / `c.tag("g")` | Placement / tag verbs had no dead check (ink writes did) | No test touched a dead reference after destroy | `…test_dead_actor_rejects_layer_and_tag` |
| H3 | Stale double `destroy()` dropped a live object's id | `a=Circle(id="x"); a.destroy(); b=Circle(id="x"); a.destroy()` | `remove_id` deleted by key without an identity check | Needs a three-step sequence with id reuse | Class retired with ids (2026-09-29): roster keys are serials, never reused. `…test_second_destroy_does_not_drop_a_newer_actor`, `test_registry_layers.TestNoIds.test_roster_keys_never_reused` |
| H4 | Rejected `layer =` half-applied | `c.layer = "missing"` → raises, `c` undrawn | `change_layer` unregistered before resolving the target | Tests checked the raise only | `…test_rejected_layer_keeps_the_old_one` |
| H5 | Parking a bare Entity crashed | `Entity().active = False` | Park read `visible`, which bare Entity lacks | Park was tested on shapes only | `…test_bare_entity_can_park` |
| H6 | `Text.clone()` crashed | `Text("x").clone()` | `clone()` passed `frame=` to every recipe | Clone tested on Shape / Sprite only | `…test_text_clone` |
| H7 | Malformed hex colour raised (one with an `int()` message) | `Circle(color="#")`, `"#000:00"` | Hex parse outside the unknown-colour policy | Colour tests used names, not broken hex | `…test_bad_hex_warns_and_is_magenta`; `test_color.TestColorStillStrict` |
| H8 | Blank id registered, collided, never removed | `Circle(id="")` twice | Registry tests `if obj.id`; `""` is falsy | Found only at `deep` | Retired with ids (2026-09-29): any `id=` is a `TypeError` (`test_api_robustness.TestInkGuards.test_id_keyword_is_refused`, `test_registry_layers.TestNoIds`) |
| H9 | `move_to(None)` / `move_by()` silently did nothing | `c.move_to(None)` | All-`None` target treated as "keep every axis" | Doc said it errors; no test | `test_hyp_api.TestVerbsRejectJunk.test_no_target_is_type_error_not_a_silent_no_op` |

### R — regressions introduced by fixes

| ID | Regression | Caused by | Caught by | Guard |
| --- | --- | --- | --- | --- |
| R1 | Every `Entity` subclass lost its setattr route, `setup()`, method watches, deferred `@every` / `@after`; `Rect.rotation =` / `flip_x` recursed | H1 rollback added a **second** `Entity.__init_subclass__`, which replaced the first | Re-running `test_hyp_api` (RecursionError) | `test_entity_hooks` (AST scan: no duplicate `def` in any class body; every subclass has its own route; `setup()` runs) |
| R2 | Bare `Entity(layer="missing", id=…)` still leaked id / group | H1 wrapped subclass `__init__` only | Direct repro while verifying H1 | `test_entity_hooks.TestConstructionIsAtomic` |
| R3 | `Text.clone(layer=…)` raised "multiple values for keyword 'layer'"; clone copied the layer | H6 fix passed `layer=self._layer` | `test_hyp_canvas` painter-order invariant | `test_entity_hooks.TestTextClonePlacement` |
| R4 | A taken id with `layer=<int>` left an empty auto-created layer | R2 fix resolved the layer before the id check | `test_hyp_canvas` census | Retired with ids (2026-09-29): `register` resolves the layer first and nothing after it can refuse |
| R5 | `test_color` still required `Color('#ff')` to raise | H7 changed the policy; old test not updated | Full suite | `test_color.test_invalid_hex_warns_and_falls_back_to_magenta` |
| R6 | `destroy()` raised `DestroyedError` when an outside `@=` dependent existed | D8's `unlink` pull ran during teardown, after the source was marked dead | Direct probe of the auto-unlink sibling while verifying D8 | `test_reactive_edge_cases.TestUnlinkFreezesTheCurrentValue.test_destroyed_source_leaves_its_final_value` |
| R7 | After D3, focal Ellipses / two-point and perimeter Circles kept a **stale collision hull** after `flip_x`, a `major_axis` write, or a Defining point write (tilted focal ellipse flipped: collided at 30° instead of 150°) | D3 kept them cold; their pose-key extra read Derivate slots from `__dict__` (stale while cold). Before D3 it only worked because warm Derivates made `_update_impl` bump `_collision_epoch` | `test_diff_collision.TestSnapshotCaches` in the D3 gate | `test_collision.TestPoseKeyCoversDefiningInputs`; `defining_point` op + canary `test_snapshot_suite_catches_a_stale_pose_key`. Fix: Circle / Ellipse `_collision_pose_extra` from Defining inputs — **the canary went blind after G14** (flips now turn the pose heading, so the random ops stopped reaching the bug through a flip); the R7 cases are now pinned as `@example`s (`major_axis` write, two-point / perimeter Circle point write). Lesson: when a fix changes a path a random suite used to reach a bug through, pin the reproducer |

| R8 | `Rain.from_rect(r)` (and any `width=lambda: …` on a reactive field) raised "expected a number, got a function" | A3 guard rejected functions unless listed in `_formula_knobs`; reactive pad fields were not listed | Full suite (`test_spatial_fx`, Guia example run) | `test_api_robustness.TestReactiveKnobsTakeFormulas` (every export, every numeric knob that is a field slot, takes a formula); fix derives the list: `validate.formula_knobs(cls)` |
| R9 | A rider on `path.reversed()` jumped to the origin when `path` was destroyed | Not a fix regression: found while triaging the gate (`test_track.TestFace`). `self._alias_of or self` — a destroyed host is falsy, so the view read its own empty tables; `freeze_last` also dropped the reversal | Full suite | `test_track.TestFace.test_reversed_rotated_freeze_does_not_jump`; class guard `test_entity_hooks.TestNoTruthinessFallbackOnEntities`. Fix: `Track._table_host()`, `_path_alive` checks the host, `frozen_rev` |

### S — system suites (2026-09-25)

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| S1 | Class `@leave_playfield` pinned its actor forever; with several such methods only the last ran | Bound method stored as the value of a `WeakKeyDictionary` (value holds the key) | `test_leave_playfield.py:300` |
| S2 | Cancelled voice of a destroyed owner stayed | An idle scheduler never pumped the offline mixer | `test_audio.test_destroyed_owner_voice_stops_when_scheduler_goes_idle` |
| S3 | `every()` flood-site memory grew one key per actor | Keys were `id(owner)` | `test_process.py` (S3–S5 block) |
| S4 | Dense mode / `on_update` snapshots kept the last destroyed owner alive while idle | Snapshot not cleared when empty | `test_process.py` |
| S5 | `e.mode = fn` on a destroyed actor ran the mode body | No dead check | `test_process.py` |
| S6 | `@collide_with` / object-literal / `resolve` pairs left destroyed bodies in the survivor's `_pair_targets` | Handler dropped, target list not pruned | `test_collision.py:2116` |
| S7 | Class-body probe pinned a destroyed local | Read `frame.f_locals` (CPython ≤ 3.12 caches the snapshot on the frame) | `test_process.py` |
| S8 | A transient whose replaced occupant's `on_done` destroyed the shape re-registered the dead shape | No dead check after `on_done` | `test_transients.py:331` |
| S9 | `after` / `every` / `tween` / `play_sound` / `on_update` on a destroyed actor registered live work | No dead check at registration | `test_process.py` |
| S10 | `tween(shape["rotation"] / ["scale"])` on a property-backed Graphic crashed on the first tick | `_write_field` took the ink path | `test_process.py` |
| S11 | `play_sound("boom"); change_act(…)` / `self.play_sound("death"); self.destroy()` / a mode-body sound before a mode switch were cut silent (design bug, 2026-09-28) | Every implicit owner end cancelled all owned sounds, not only the ones that leak | `test_audio.TestSoundRingsOut` (fate matrix: every implicit and explicit ending × every sound state — a new ending path or state that skips `_rings_out` fails a cell); `test_act.TestActSoundsRingOut`; owner-end invariant in `test_sys_hyp_audio`; `test_audio.TestDeclick` for the cut itself |

### A — API surface

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| A1 | Unhashable key leaked Python's `unhashable type` from a name lookup (found on `keyp`; siblings found by checking the class) | `keyp(["A"])`; `ready(["a"], 1)`, `recently({…}, True)`, `e.ready` / `e.recently`, `obj(["a"])` (removed with ids), `canvas.layers[["a"]]` | Dict / set lookup ran before the type check (`keyp` spec cache, poll slot dicts, `id_map`, layer dict) | `test_keyp.TestKeySpecTypes`, `test_process.TestPollNameTypes`, `test_registry_layers.TestLookupKeyTypes` |
| A2 | Three constructor knobs leaked Python's `float()` errors | `Line(length="x", angle=0)`, `Ellipse(from_rect=r, padding="x")`, `Rect(p1=, p2=, height="", anchor="cap")` | Raw `float(kwargs[...])` in Line's home values, the Ellipse `from_rect` branch and the Rect spine branch | `test_api_robustness.TestConstructorKnobsNeverLeakFloat`. Fix: `validate.finite` / `magnitude`. Found by `test_hyp_api` constructor fuzz at `ci` after a parallel Line API change added the home path |
| A3 | Numeric constructor guard had loopholes: `None`, `bool`, tuples, objects and functions reached `float()`; interned looks built their key in `__new__` before the guard; filters had no guard; `None`-default knobs annotated as numbers were skipped | `Bloom(intensity=None)`, `Stars(twinkle=True)`, `Metal(speed=object())`, `SkyGradient(fade=(1, 2))`, `Kaleidoscope(segments=fn)`, `ProceduralFill(seed=None)` | `check_numeric_params` only rejected strings / NaN; `__new__` ran first | `test_api_robustness.TestSurfaceFuzzFindings`; `validate.guard_new_numbers`; a function passes only for `formula_knobs(cls)` (see R8). `validate.number` = fixed number (rejects functions); `finite` lets formulas through. Cost: the guard runs on every construct (interned looks too); `_numbers_fast_ok` skips `bind_partial` for plain in-range numbers (`Neon("red", amount=0.5)` 11.4 → 8.1 µs; unguarded 6.7), and `TestNumericGuardFastPath` proves it never accepts what the full check rejects |
| A4 | Structured knobs and pure functions leaked Python's messages; `ready("new")` with no interval raised `KeyError` | `Dilate(radius=object())`, `DropShadow(offset="")`, `Blur(input=object())`, `Colormap(colors="00")`, `Lattice(scroll={…})` (dict has `len` and `[]`), `remap(None)`, `ready("x")` | Pairs / inputs / counts parsed with bare `float()` / indexing | `TestSurfaceFuzzFindings`; `validate.pair` (rejects mappings and sets), `filter_input`, `count`; `test_ready_without_interval_on_a_new_name_is_a_type_error` |
| A5 | Widget geometry leaked, and a rejected widget moved the HUD layout cursor | `Button(top_left="")` (then `x1=""`), `DropDown(width=object())`, `Text("a", top_left="")`, `CheckBox(size="")` | Geometry validated after `begin_hud_item` (or never) | `TestSurfaceFuzzFindings.test_rejected_widget_does_not_move_the_layout_cursor`, `test_rejected_top_left_does_not_move_the_layout_cursor` (every widget + Text × bad points); `_geom_point` / `_geom_size` / Text `_anchor_xy` before any layout call |
| A6 | `resolve_now` on a destroyed actor re-enrolled it in the collision index | `c.destroy(); c.resolve_now("g")` | `ensure_collider` had no dead check | `TestDeadVerbFindings.test_resolve_now_does_not_reenroll_a_dead_actor`; `ensure_collider` raises `DestroyedError` (every caller) |
| A7 | Dead-verb batch once P6 really ran: `absorb(None)` leaked; `Square << Square` recursed forever (also live); `add_hitbox` on a dead sprite raised `RuntimeError`; `show_handles` / `show_points` built markers on a dead shape; a first read on a dead widget (`displayed_text`) put it back in the graph; `Line(circle=dead)`, `Ellipse(from_rect=dead)`, `dead_track.reversed()` linked new shapes to a dead source; `Gradient(size=fn)` and five other `float(finite(…))` sites leaked | see `TestDeadVerbFindings` | No dead / type checks; `super()._takein` (dispatcher) inside `_takein_impl`; lazy `ContainerSlot.__get__` wired the owner edge; `float()` around formula-passing validators | `test_api_robustness.TestDeadVerbFindings`, `TestNoFloatAroundFormulaValidators`; `test_entity_hooks.TestHooksDoNotCallTheirDispatcher`; P6 |
| A8 | `ci` round after A7: fixed-number knobs and verbs still took a function through `finite` / `magnitude` (`Slider(min_value=fn)`, `ready(n, fn)`, `recently(hold=fn)`, `chase(dt=fn)`, `amp_db(floor=fn)`, `canvas.shake(fn)` / `glitch`, camera `pan` / `rotation`); `ColorSweep(axis=nan)`; `Text(width=fn)` (found at `deep`); `Track(rotation=fn)` leaked `float()` (now links, like every shape); `(x - hx) ** 2` raised `OverflowError` for a huge-but-finite coordinate (Slider handle, `Ellipse` / `Track.contains_point`) | `Slider(top_left=(1e200, 1e200)).on_mouse_move(1, 1)` (then `x1=1e200`); `Ellipse(...).contains_point((1e200, 1e200))` | `finite` passes formulas by design (reactive writes); float `**` overflows where `*` saturates | `TestSurfaceFuzzFindings` cases; `TestNoFloatPowerSquares` (AST: no `expr ** 2` in engine geometry; `_sq`); `validate.seconds` / `number` / `fixed_magnitude` at fixed sites; after `deep` also found `Text(width=fn)`, the fixed class was closed with `TestBareMagnitudeOnlyOnReactivePaths` (AST: a bare `magnitude(` only at allowlisted reactive sites; ~20 sites converted — timed `scale_to(fn)`, `canvas.zoom(fn)`, `Rect(corner_radius=fn)` had stored the function and crashed later in a frame) |
| A9 | Methods phase (junk as the first argument of every author method on a live instance): 64 leaks from 9 causes — `set_alpha(None)` on every shape / Gradient / Texture / Sprite, `look_like(None)`, filter `compose(None)`, `clock.advance`, `Palette.reset`, `History.pop(None)`, `State.remove(None)` (`KeyError: None`), Track `at` / `local_at` / `tangent_at` / `angle_at` / `orbit` / `wander` / `zigzag` / `spaced_points`, Vec2 operands (`dot(None)`, `project_onto(object())`); then with representatives: the whole Color amount family (`lighter(None)`, `with_alpha("x")`, `jitter(1e308)` → NaN), `Box.inset`, `Grid.cell(None)` / `cell(1.7)` (silently truncated); `track.spaced_points(1e308)` **hung** | `scena.Color("red").lighter(None)`; `track.spaced_points(10**9)` | No argument checks on methods (constructors had the guard); Color not constructible without arguments, so the fuzzer skipped it | `test_api_robustness.TestMethodJunkFindings`; `test_hyp_surface.TestMethodJunk` + `TestMethodCoverage` (a class with author methods must be fuzzed: no-arg, `surface_support.REPRESENTATIVES`, or `ENGINE_BUILT`). Fixes: `validate.alpha01`, `number`; `scenamath._vec_arg` (a Vec2 or an `(x, y)` pair); `track._u_arg` / `_sample_count` (≤ 1,000,000); `box._cell_index` |
| A10 | A rejected call half-applied: `fade_in("slow")` / `dissolve_in(...)` showed a hidden shape before validating `duration`; `tangent_lines_from(p, id2=<taken>)` left the first Line alive; `Contrail(duration=-1)` left its private stroke Line registered (a helper actor the H1 rollback does not know about) | `Point(visible=False).fade_in("slow")` → raises, Point now drawn | Side effect (`visible = True`, first construction) before the check that can fail | `TestMethodJunkFindings.test_rejected_fade_in_does_not_show_a_hidden_shape`, `test_tangent_lines_from_is_all_or_nothing`, `test_rejected_contrail_leaves_no_stroke`. Rule: a constructor that builds helper actors destroys them if it raises later; found by the methods phase's no-trace check (Point starts hidden, so only it exposed the class) |
| A11 | A construct-time source shape of the wrong type leaked Python's `AttributeError` (`'bool' object has no attribute 'center'`) — found by the surface fuzzer at `deep` after M3 closed | `Ellipse(from_rect=False)`, `Ellipse(from_rect=Circle(...))`, `Line(circle=Rect(...))`, `Line(p1=, parallel_to=None)` | `_live_ref` (A7) checked "destroyed" but not the kind | `TestSurfaceFuzzFindings` cases. Fix: `_live_ref(ref, owner, kind, param)` requires a live `Line` / `Circle` / `Rect` (subclasses count) and names the parameter |
| A12 | 36 flag knobs accepted any value through `bool()`: `"no"` is truthy, so `Stars(enabled="no")` switched the background **on** (also every background `enabled`, `Circle(use_center=)`, `Contrail(fade=)`, `Slider(show_value= / only_int=)`, `Text(stack=)`, `Sheet(yoyo=None)`, `set_watchdog`, `show_tracks`); `set_extrude_focus("x", 0)` leaked `float()` | `Stars(enabled="no")` | Flags were coerced, not checked; P2 cannot see an *accepted* junk value; the callable fuzzer only passed the first argument (`set_extrude_focus` stopped at "missing y") | `test_hyp_surface.TestFlagsTakeARealBool` (every flag of every export × `"no"`, `2`, `None`, `object()`); `TestSurfaceFuzzFindings.test_flags_take_a_real_bool`. Fix: the constructor guard checks bool-default knobs with `expect_bool` (fast path accepts only a real bool); `expect_bool` in the setters and the unguarded classes; the fuzzer fills the other required arguments (`_fill_required`) |
| A13 | `ColorSweep(axis="banana")` silently meant radial; `axis=7` silently meant horizontal (`% 3`) | `ColorSweep(axis="horizontl")` | `_AXIS_ALIASES.get(key, 0)`; numeric codes wrapped | `test_color_sweep_axis_is_strict`. Decision: names + short aliases, or codes 0 / 1 / 2; anything else raises (`ValueError` with did-you-mean, `TypeError` for other types). A wrong axis looks plausible, so it gets no colour-style "warn and fall back" |
| A14 | SpatialFx dual-model Derivates read stale; placement had a second spelling | `Rain(p1=(10, 20), p2=(110, 70)).width` → `0.0`; `Rain(center=…).p1` → origin; `Jet(p1=x)` silently became `origin=x`; `Fire(200, 150)` / `Sparks(at=p)` next to `center=` | Pad / beam domains lacked `_materialize_derivate_part` (Shapes have it); `Rain` corners were positional-only; `_init_point_fire_args` accepted four spellings of one point | `test_spatial_fx.TestDualModelDerivates`, `TestKeywordOnlyPlacement` (walks every exported kind + Fire style: positional, `at=`, scalar keywords raise with the point keyword; nothing registered), `TestRainCorners`, `TestJetPairs` |
| A15 | `resolve()` / `unresolve()` accepted any side: `resolve(c, 5)`, `resolve(c, None)`, `resolve(c, Vignette())` registered a pair nothing could match; `@collide` refused numbers but let a post effect through | `resolve(Circle(), 5)` → silent no-op | Each pair verb had its own (or no) side check; `@collide`'s was a deny-list | `test_pair_sides`. Fix: one allow-list `collision._check_pair_sides` (actor, tag, `group['tag']`, `ANYTHING`, `Collider`, `Hitbox`) for all five verbs |
| A16 | Python's binding message reached authors from ~25 exported constructors: `Polygon.__init__() got an unexpected keyword argument 'pionts'`, `Grid.__init__() missing 2 required positional arguments`; the looks' "Valid:" list printed `cls` | `Polygon(pionts=…)`, `Entity(gruop="a")`, `Neon(amout=1)` | No keyword check on classes without `**kwargs`; `check_numeric_params` listed every non-`self` name | `test_api_docs.TestUnknownKeywordMessages` (walks every exported class with a junk keyword; `Did you mean` cases; author `Entity` subclasses too; setup still runs once). Fix: `validate.install_friendly_constructor` on every export (`scena/__init__.py`) and the same rewrite inside `entity._wrap_actor_init`; acts only after a failed call and only on Python's own `X.__init__()` message. Exported *functions* keep Python's arity text: a wrapper frame would shift `_call_site(depth)` in the scheduler |
| A17 | Guia parameter names were not the keyword names: `remap(v, in0, in1, out0, out1)`, `heading(de, para)`, `nearest(origem, itens)`, `Color.interpolate(a, b, t)`, `lighter(n)`, `with_alpha(a)`, `Palette.reset(i=0)`, `.dot(v)`, `play_sound(src)`, widgets' `attr` (code: `bounded`) … — a keyword call copied from the Guia raised | `remap(v=5, in0=0, in1=10)` | `check_parameter_keywords` only rejected a fixed list of Portuguese words | `validate_guia.check_parameter_rows` (every `Parâmetros:` row and `<p class="sig">` line vs the real signature, owner-aware; `*args` / `**kwargs` accept placeholders); `test_api_docs.TestGuiaParameterRows` with planted-row canaries. Code renames where the code name was worse: `Colormap.get_color(t)`, `Entity.goto_mode(fn)`, widgets / `Menu(cell)` |
| A18 | `Vec2` operators leaked Python text: `Cannot add Vec2 and <class 'int'>`, `v * "a"` → `can't multiply sequence by non-int of type 'float'` | `Vec2(1, 2) * "a"` | `{type(other)}` in f-strings; `__mul__` / `__truediv__` unchecked | `test_api_docs.TestVec2OperatorMessages`. Fix: `_vec_operand_message` / `_vec_scale_message` (name the type, the accepted forms, `v + (5, 5)`, `v.dot(w)`) |
| A19 | Engine hooks stayed public because their names are ordinary Guia words: `render` on every look (the word came from an Svg example), `tick` on every SpatialFx / PostEffect / ProceduralFill / `clock`, `shader`, `replaces_sprite_body`, `PostEffect.stage`, `collision.step`, `canvas.effects.hit_feedback` / `invalidate` / `release_surfaces` / `render`; objects reached through an export were never walked, so `canvas.layers["far"]` exposed `objects`, `append_object`, `tombstone_object`, `compact`, `live_count`, `response`, … and `canvas.fx_quality` exposed `from_value` | `Neon().render`, `canvas.layers["default"].append_object` | `test_api_surface` allowed any word found anywhere in the Guia, and walked only `scena.__all__` | `test_api_surface`: `_reachable_objects` walk, `TestEngineHooksAreUnderscored.HOOK_WORDS` (with a canary), `test_family_members_are_documented_in_their_family`. Fix: underscore every hook (`_render`, `_tick`, `_skia_shader`, `_replaces_sprite_body`, `_stage`, Layer `_objects` …); the dead `PostEffect.tick` removed |
| A20 | `Menu(background=Gradient(…))` / `Texture(…)` crashed on the first draw | `Menu(options=["A"], background=Gradient("red", "blue"))` | `_panel_paint` called the material's `shader` **property** as a function (`bg.shader()`) | `test_api_docs.TestMenuMaterialBackground`. Found while renaming `shader` → `_skia_shader` (A19): a hook nobody documented was also a call site nobody ran |
| A21 | `SpatialFx` on the `ui` layer raised plain `TypeError`, while `UiLayerError`'s docstring (and the error catalog) promise `UiLayerError` for exactly that case | `Fire(layer="ui")`, `fx.layer = "ui"` | Two raise sites predated `UiLayerError` | `test_ui_layer.TestUiSpatialFxForbidden` (now `UiLayerError`) |
| A22 | Exports "documented" only in the search index: `WaterFill` / `FlameFill` / `SwellFill` / `WaveFill` / `AuroraFill` / `Stroke` / `ParallaxLayerError` / `UiLayerError` / `last_author_error` … pointed at a section that never named them; `validate_guia.py` said "\*Fill is not public" while `__all__` exported them | search "WaterFill" → Visual catalog, no WaterFill | `check_public_vs_all` only required an index entry | `validate_guia.check_symbols_described` (the anchor, or its section, names the symbol; catalog sections include the catalog text) + `test_api_docs.TestGuiaSymbolsAreDescribed` with a canary. Fix: Guia tabs *Procedural* and *Paint / Fill / Stroke*; the error catalog gained `CircularReferenceError`, `ParallaxLayerError`, `UiLayerError`, `ActUsageError`, `Cancelled`; the banner helpers left `__all__` |
| A23 | The circular-link error said `linking Circle.radius to Circle would create a cycle in the dependency graph` — neither object identified, no fix; its docstring described a different error | `a["radius"] @= lambda: b.radius`, then `b["radius"] @= lambda: a.radius` | Message built from `.name` only | `test_api_docs.TestCircularLinkMessage`. Fix: `state._cycle_label` (field + `entity_label`), "Link one direction only …" |
| A24 | Autocomplete / `help()` showed the wrong API: `width=<object object at 0x106d31cf0>` on Sprite / Svg / Text / Track / Point / Paint …; `Sprite` had one lone `@overload` `(source=None, **kwargs)` so static tools hid all twenty keywords; SpatialFx kinds hid `layer=` / `id=` / `group=` / `soft_edge=` behind `**kwargs`; Text / widgets / Track / Contrail ended in `**kwargs` only to reject typos; shape model keywords were "required" (`Circle(radius: float, …)`) and the gradual overload let `layer` be positional with no `center=`-only form; `Handle` showed 20 engine knobs | `help(Sprite)`, `inspect.signature(Circle)` | Bare `object()` sentinels; catch-all `**kwargs` for friendly errors; published union kept the first overload's "required" | `test_api_docs.TestSignaturesReadWell` (no `at 0x` in any exported signature; no exported `**kwargs`; no lone overload; shapes all-optional + gradual overload; SpatialFx published keywords accepted; named varargs; `py.typed`). Fix: `_defaults.Unset`; `_call_hints` on the class (actor wrapper / friendly constructor pass them to `reject_unexpected_kwargs`); `_publish_fx_signatures`, `_publish_svg_signature`, `set_defaults` / `change_act` `__signature__` |
| A25 | `soft_edge=` on SpatialFx leaked `float()` for junk (`Orb(soft_edge="")`), and the first published signature showed `0.15` for every kind while each class used its own literal (Rain 0.18, GlowSpot 0.85 …) | `Jet(soft_edge=object())` | Not a guarded knob (hidden in `**kwargs`, so the surface fuzzer never reached it); defaults were literals inside each `__init__` | Found by `test_hyp_surface` once A24 published the keyword. Fix: `fixed_magnitude` in `SpatialFx._construct` and the Rain / Jet paths; per-class `_soft_edge` attribute is both the default and the published value (`test_spatial_fx_published_keywords_are_accepted`) |
| A26 | Messages with no fix or a Python repr: `above("x")` / `below` / `layers.using` / `layers.default =` said only `Layer 'x' not found` (the `.layer =` path already listed layers + the create call); `Cannot convert <class 'object'> to Color` (a `ValueError` for a wrong type); `Cannot convert <class ...> to Point`; `geom._shape_center` raised `TypeError("Foo")`; presets dumped 94 names with no suggestion; `set_defaults(colr=)` had no hint; `Microphone(backends=5)` was swallowed into "no input device"; `window_frac` lived on as a deprecated second spelling of `window_scale` | see `test_api_docs.TestMessagesNameTheFix` | One-off `raise` sites predating the message rules | `test_api_docs.TestMessagesNameTheFix`, `test_color.test_invalid_type_still_raises` (now `TypeError` with the forms), `test_window_geom.test_window_frac_second_spelling_is_gone`. Fix: `LayerStack._missing` for every lookup; `did_you_mean` on presets / `set_defaults`; the Guia's unknown-colour rule corrected (near miss → closest name, else magenta) |
| A27 | Found while writing the hover docs: `Track.eight / star / spiral / wave` passed knobs straight to `float()` / `int()` (`Track.eight(width="x")` leaked Python's message; `star(points=2.5)` truncated); `ProceduralFill.amount` / `.speed` setters used `float()`; `FilterEffect.filter` handed authors the raw `skia.ImageFilter`; widgets exposed WidgetManager dispatch (`on_mouse_down`, `on_key`, `on_char` …) as public methods; `keyp.press(k)` / `keyp.release(k)` injected input while `mouse.press(b)` is a query — one verb, two meanings; `Text.flash_text` returned an engine channel while the widget version returned `self` | `Track.eight(width="x")`, `keyp.press("A")` | No docstring had to describe them, so nobody read them | `test_api_docs.TestSignaturesReadWell` / `TestEverythingHasHoverDocs`, `test_api_surface.TestEngineHooksAreUnderscored` (widget hooks). Fix: `validate.number` / `count` in the presets and setters; `_skia_filter`; `_on_*`; `keyp._press` / `_release`; `flash_text(…, on_done=)` returns the caption / widget |
| A28 | The Guia described two behaviors wrongly: `Button(cell)` was "a toggle" (the code is momentary — `value_on` while held, `value_off` on release; the example `Button(st.paused)` would pause only while pressed), and `Vec2.reflect_about(axis)` "mirrors about an axis" (it bounces off a surface with that **normal**: `(1, -1)` about `(0, 1)` → `(1, 1)`). The unknown-colour rule said "magenta" while a near miss uses the closest name | `Button(st.paused, value_on=True)` | Prose written from intent, not from the code | Guia fixed (Button one-liner, `cell` row, example; `reflect_about(normal)` row with the worked example; colour one-liner). Docstrings now state the same behavior (A27 pass) |
| A29 | `Menu(background=Gradient(…))` drew a solid panel (the last stop); `Texture(…)` drew a 48-unit sprite fit at the view origin and dropped `alpha` / `shift`; a bad `background=` (`42`, `WaterFill()`) raised only on the first draw | `Menu(options=["A"], background=Gradient("red", "yellow"))` | `_panel_paint` used `material._skia_shader`, an origin-centered local-frame shader, in view coordinates with no host fit. The A20 test asserted `isinstance(paint, skia.Paint)` — a type, not pixels — so the half-fix passed | `test_menu.MenuBackgroundTest` (pixel samples at the panel edges, off-center panel, angle / radial / `size=`, Texture stretch + alpha, construction-time `TypeError`); bug class: `test_api_docs.TestMaterialShadersStayInTheirFrame` (only `style.py` / `recipes.py` may read `_skia_shader` / `_shader_for_scale` / `_shader_for_local`, with a canary). Fix: `style._material_paint_for_rect` (host fit + translate to the rect center) and `style._coerce_panel_material`. Lesson: a regression test for a rendering bug samples the output |
| A30 | A float `TextInput` changed the cell when clicked in and out (`0.125` → `0.12`); a bool cell became the string `'1'`; typing past the box width dropped characters | `TextInput(st.f)` with `st.f = 0.125`, focus then unfocus | The box showed `f"{v:.2f}"` and wrote back on every focus loss; `isinstance(True, int)` routed bools to the int display while the commit fell through to "store the text"; `_on_char` refused characters that did not fit | `test_text_input.TestCommitRules` (incl. a Hypothesis property over floats), bug class `TestFocusInOutNeverChangesAValue` (every value widget × focus in / out with no edit). Fix: commit only when `.text` differs from the cell's own text at focus; floats shown with `.15g`; bool cells refused at construction; the box scrolls instead of dropping |
| A31 | Focusing a `TextInput` right after its cell changed (no draw in between) edited the stale text, and the commit wrote it back over the new value | `st.t = "new"; box.focus()` | "Follow the cell unless focused" ran inside `_on_focus_gained`, where focus is already set | `test_text_input.TestCommitRules.test_focus_right_after_a_cell_write_edits_the_new_value`. Lesson: `set_focus` flips `_has_focus` before the widget hook runs — a hook must not gate on it |
| A32 | The Guia showed no catalog at all (Visual, SpatialFx, Post, Backgrounds, filters, transients, complementos): one stray `)` in a `P(...)` list made `guia-api-catalogs.js` invalid JS, so `window.ScenaGuideCatalogs` never existed and every `cat.fill` was skipped | `P("color", "None", "…"))]` in the `Rain` card | `load_catalogs` reads the file with tolerant regexes: it saw every card, checked every parameter and reported ok | `validate_guia.check_catalog_js` (a JS bracket tokenizer that skips strings, comments, regex and template text; first mismatch as `file:line:col`; card count per bag vs the loader) runs first in `main()`; `check_catalog_js_engine` re-runs the file in node / jsc when one is installed; `test_api_robustness.TestGuiaMatchesCode` with planted-error cases. Rule: every hand-edited `.js` data file of the Guia passes the strict check |
| A33 | `Collider` accepted any weak-referenceable piece and registered a body with no geometry that nothing could unregister (`Collider` has no `destroy`) | `Collider(lambda: 0)` | No type check on pieces; the parallax / part checks are no-ops for non-entities | `test_collision.TestCompoundCollider.test_non_shape_pieces_are_refused_before_registration`; `test_hyp_surface` P3/P5 at `ci` (found there). Fix: every piece must be an `Entity` or a `Hitbox` part, checked before any mutation |
| A34 | A write to an unknown `Layer` attribute was stored and did nothing: typos (`layer.visable = False`), the frozen camera-response knobs (`layer.scroll = (0, 0)`, `layer.pan_response = 0.5`), a method name | `canvas.layers.create("far").scroll = (5, 0)` → no scroll, no error | `Layer` was a plain `@dataclass` with no `__setattr__`; only `name` / `z` / `post_fx` were properties | `test_registry_layers.TestLayerWriteGuard` (every layer kind, typos, frozen knobs incl. numeric layers, every dataclass field and setter still writable). Fix: allow-list `Layer.__setattr__` (dataclass fields + properties); others raise `AttributeError` with did-you-mean, the writable list, or the `canvas.layers.create(...)` hint. Later (P3), `scroll` became the live rate on non-neutral layers (`Layer.scroll` setter; neutral layers raise `ValueError` with the create fix) |
| A35 | `v.length = 5` on a Vec2 said "derived (computed) attribute for the shape's current model … Construct the shape with a different model instead": a Rect message, and no way to set a length or heading in place was named | `Vec2(3, 4).length = 5`; `v["angle"] @= lambda: 30` | One Derivate message for every Container, worded for shapes | `test_derivate_readonly.TestVec2ComputedFieldMessages` (every Derivate slot of Vec2, `=` and `@=`). Fix: `Container._derived_field_message` hook; Vec2 names `v << vec_from_angle(v.angle, 5)` / `v << vec_from_angle(30, v.length)` and, for `@=`, `v @= lambda: vec_from_angle(angle, length)` |
| A36 | Every computed field of every shape said "derived (computed) attribute for the shape's current model … Construct the shape with a different model instead": wrong for Text (no models), Track and Box, and it named no way to move a computed point. `rect.top_right << (1, 2)` did not raise at all: it overwrote the point and the rect stayed | `Text("a", center=(0, 0)).top_left = (1, 2)`; `rect.top_right << (1, 2)` | One shape-worded message at five sites; `Container.__lshift__` had no Derivate check | `test_derivate_readonly.TestDerivedFieldMessages` (every model × computed field × `=` / `.x =` / `@=` / `<<`; runs each suggested `move_to`). Fix: one hook, `Container._derived_field_message` (Shapes Design, "Refusing a computed field"); `<<` calls `_ensure_not_derivate` |
| A37 | A parallax layer's `scroll` moved only when something painted: `update` read last frame's offset, a headless run never scrolled | `canvas.layers.create("nuvens", scroll=(0, -60))`, step frames without drawing → offset stays 0 | `ScrollState.advance(t)` ran inside `ScenaCanvas.draw` (world state advanced by paint) | `test_layer_scroll_view.TestScrollInFrameTick` (no draw, `update` sees this frame's offset, `clock.scale = 0` pauses), `test_parallax_layers.TestRenderEndToEnd.test_draw_does_not_advance_scroll`. Fix: `ScenaCanvas.advance_layer_scroll` once per frame right after the clock tick; draw only reads the accum. Rule: world state never advances in the draw walk; a custom frame loop calls the tick hooks after its own clock tick |
| A38 | `ship.vel @= lambda: vec_from_angle(st.a * 30, 10)` raised `LinkedAttributeError: Circle.Circle_vel is linked — call Circle['Circle_vel'].unlink() first`; `ship.vel["x"] @= …` linked silently, so the next `resolve(bounce=)`, `confine(action="bounce")` or `vel.y -= g * dt` raised; `ship["vel"] @= …` already refused | `c.vel = (1, 0); c.vel @= lambda: (st.a, 0)` | Python runs `c.vel = c.vel.__imatmul__(f)`: the link landed on the owned Vec2, then the setter wrote into it. The bracket refusal lived on the Entity, which the part paths never reach | `test_fieldref.TestVelIsNotLinkable`; bug class `test_attribute_and_bracket_link_agree_on_every_actor_part` (every exported actor kind: a property handing out a Container that bracket `@=` refuses must refuse `part @= …` too and link nothing). Fix (decision: refuse, not link — the engine writes `.vel`): the owned Vec2 carries `_link_refused = "vel"`, checked in `state._refuse_link_on_dead` before any link; one message for all four spellings. An early return in the setter on `value is self._vel` would have kept the link |
| A39 | Deep serial pass (2026-10-09): `Text(glow=[])` raised but moved `widgets._stack_bottom`; `Text(angle="x")` too | `keeper = Text("k"); Text(glow=[])` → the cursor stays one slot lower | `Text.__init__` applies `glow` and `angle` after `begin_hud_item` / `finish_auto_layout`. The rollback only rewinds the column when the failed item was its last live participant, so the A5 guards, which start from an empty column, could not see it; the serial pass had leftover HUD items in the column. Class: "validate before the slot" is a hand-kept order | `test_api_robustness.TestSurfaceFuzzFindings.test_a_rejected_hud_item_leaves_the_column_exactly` (every exported HUD class × every keyword × four junk values, with a live item in the column); `test_hyp_surface.TestConstructorJunk` now keeps a live item in the column too. Fix for the class: `begin_hud_item` records the cursor it found (`_hud_cursor_before`), `_drop_failed_construct` restores it whatever raised, and the actor wrapper drops it once the object is built ([Canvas Design](Canvas%20Design.md)) |
| A2 | Instant pose on a destroyed actor was not one rule | `Sprite.destroy(); sprite.move_by(1, 0)` raised `NotImplementedError`; `Circle.destroy(); circle.move_by(1, 0)` moved the husk | `destroy()` drops the graph node; the batched path called `_update_impl`, and the fast path wrote pose with no dead check | `test_api_robustness.TestLifecycleContracts.test_dead_instant_verbs_leave_pose_unchanged` (Sprite, Circle, Rect, Text, Point, Line × move / rotate / scale / confine) |

### C — constructor links (2026-09-26)

A value copies; a lambda links. These failed that rule because the constructor touched the raw argument before `_init_scalar` / `_init_composite`.

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| C1 | `Line(length=lambda: …, angle=0)` rejected the home form; every other Line form accepted `length=` | `Line(length=lambda: src.x, angle=0)` | `_home_pose_values` ran `number()` on keys the author passed. Home fill only needs defaults for omitted keys | `test_ctor_links.test_line_home_length_and_angle_link` |
| C2 | `Ellipse(fp1=, fp2=, major_axis=)` rejected a lambda on any of the three | `Ellipse(fp1=lambda: sun, fp2=(0, 0), major_axis=100)` | The `major > distance` check called `get_xy` / `_bare_num` on the raw kwargs | `test_every_geometry_key_links`; `test_linked_focal_ellipse_may_collapse` (a link may collapse; a written value still raises) |
| C3 | Rect spine `height` linked, but `Box` spine `height=lambda` leaked `float()` | `Box(p1=…, p2=…, height=lambda: src.x, anchor="cap")` | `height = float(kwargs["height"])` before `_init_scalar` | `test_every_geometry_key_links` (Box spine) |
| C4 | `Rect(p1=lambda: s, p2=(100, 50), rotation=30)` was a different rectangle from the plain call | plain corners moved to the rotated box; the link stayed at `s`, and `p2` was still rewritten | `_promote_aabb_diagonal_to_oriented_corners` / `_promote_point_vec_aabb_to_oriented` rewrote stored inputs. Runtime `_oriented_frame` already treated corners as pinned | `test_plain_and_linked_build_the_same_shape`; `test_shapes.test_construct_with_angle_pins_corners`. Same removal in `box.py` |
| C5 | `corner_radius=lambda` used to be stored and crash at draw (A8 made it `fixed_magnitude`). Bracket `@=` still created dead ink | `rect["corner_radius"] @= lambda: 4` | Not a reserved name, so the link landed in ink the painter never reads | `test_ctor_links.test_corner_radius_assign_is_callable_assign_error`; `test_api_robustness` field-kind case. `corner_radius` is reserved; `=` of a callable is `CallableAssignError` |
| C6 | Fixed knobs (`padding`, `Polygon(points=lambda)`, Sprite `width`/`height`/`size`, Text `width`, `Track(start=)`) raised Python's message or a generic "got a function" with no alternative | `Sprite(width=lambda: 3)` | The value was fed to aspect math / `len` / `float` | `test_fixed_keys_reject_with_scena_message` (each message names the linkable alternative). `Track(rotation=lambda)` links, same as a shape |
| C7 | Docs taught the copy as a link (2026-10-05): the `Anchor` docstring said `Line(p1=a.center, …)` linked (its Example too), and Shapes / Reactive Design called `Line(p1=rect.top_left)` / `Line(p1=rect.right_center)` a link or DirectLink; the line stayed where it was built | `a = Anchor(100, 100); l = Line(p1=a.center, p2=(300, 100)); a.move_to(150, 120)` → `l.p1` still `(100, 100)` | Prose written before construction became always-copy, never updated; no test read docstring or design-doc claims. Runtime was right | `test_shapes.test_anchor_bare_center_is_a_snapshot`, `test_anchor_docstring_example_follows_the_drag` (runs the Example); class guard `test_api_docs.TestLinkClaimsUseLambda` (a bare dotted point keyword on a line that says link / liga / follows, with no copy word and no `lambda`, in `scena/*.py`, design docs, Guia, tutorials; canary). Heuristic: a claim split across lines escapes it |

### T — Text / HUD (2026-09-26)

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| T1 | Any motion on a view caption recentered it on its pin; a `center` write drew moved but snapped back on the next string change | `t = Text(text="", top_left=(16, 560)); t["text"] @= …; t.move_by(0, 0)` → left edge `16 − w/2` (then spelled `x1=16, y1=560`) | `center` stayed the old string's midpoint until the next layout, and `_move_by` / `_move_to` rebuilt the box around it with the world rule. Found again during the fix: a reconcile alone misread an *absolute* stale write (`center = P`, `tween`) as a translation, so reads refresh too | `tests/test_text.py` `TestViewPinMotion` (every verb × three anchors, stale and fresh), `TestViewPinMotionProperty` |
| T2 | `Text(box=cell)` sat half its height above the cell centre (bug A); with `align="left"` / `"right"` the region-wide box shifted half a width sideways (bug B); and it silently advanced the HUD column | cell centre `(200, 150)`, 60 high → text centre y `161.8`; `align="left"` → box x `200..360` for a `120..280` cell | The region centre was fed to the bottom-left **edge** `x1, y1` (a centre is not a corner), and `align` doubled as the horizontal pin. Class: converting between a top / centre anchor and the min edge `y1` without the height | `tests/test_box.py` `test_text_box_is_centred_in_the_region` (every align × one and three lines), `test_text_box_does_not_join_the_hud_column`. Fix by design: `box=` is `center=` (pose) and `align` only places lines; anchors are named points (`top_left=` …), edges are private `_x1.._y2` |
| T3 | A HUD caption near the top grew **upward**: a second line (formula text) pushed its first line off screen; `font_size` moved the top edge | tutorial `placar = Text(x1=20, y1=760)` on an 800-high screen; `"…\nVidas 3"` → top `807` | Placement was the bottom-left corner in y-up, so growth went up | `test_text.TestTextAnchors.test_growth_is_downward_and_away_from_the_anchor`; `TestViewPinMotionProperty` (every anchor × string / hard breaks / `width` / `align` / `font_size` / moves / anchor writes: pin fixed, top fixed) and `test_linked_anchor_tracks_its_source`. Guard against the scalar spelling coming back: `TestTextAnchors.test_no_public_scalar_edges` |
| T4 | Tutorial steps had drifted from the API: `quadrado.visual = Aura()` (Aura is sprite-only), `keyp.once("escape")` (the key is `"ESC"`), `barra["rotation"] @= lambda b=barra: … b.nivel` (`CircularReferenceError`; also `examples/barras_girando.py`), `SkyGradient("space")` (no such preset) | open `docs/pt/tutorial/04-ui-widgets.html`, press Esc | Nothing executed the tutorial HTML; the API moved underneath (Aura scope, key names, default-arg formula sources) | `tests/test_tutorials.py`: every step's `code:` runs in a child process with `run()` as a few `update(dt)` calls; each `try` box runs appended to its step, or (a function-body fragment) compiles and resolves its calls. Verified to fail on the pre-fix HTML. Fix: `Rim()`, `"ESC"`, `lambda n=nivel: …`, `SkyGradient("dusk")` |

### K — handle fields that double as registry keys (2026-09-28)

A write changed the field; the registry kept the old key. Nothing raised.

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| K1 | Renaming a layer desynced the registry | `l = canvas.layers.create("far"); l.name = "zz"` → `"zz" in canvas.layers` False, `"far"` True | `Layer.name` was a plain dataclass field and the `canvas.layers` key (also every member's `_layer`) | `test_registry_layers` (`test_name_is_read_only`, every layer kind, members in sync). Fix: read-only property, `AttributeError` naming `create` + `shape.layer =` |
| K2 | A renamed / re-owned `Handle` orphaned its scheduler slot | `h = after(10, fn, name="spawn"); h.name = "x"; h.cancel()` → dead `h` still in `_named["spawn"]`; `h.owner = d; c.destroy()` → job survives its owner | `_forget` rebuilds `(id(owner), name)` from the **current** fields; `name` / `owner` were public slots | `TestHandleSlotKey`. Fix: `_name` / `_owner` slots + properties raising `TypeError` (same family as `h.remaining` / `h.paused`); `audio._unbind_named` writes `_name` |
| K3 | In-place group edits skipped the group index | `c.group.add("boss")` → `c.group` says boss, `group["boss"]` lacks `c` (collision tags too) | `shape.group` returned the live `set` the registry mirrored; only `c.group = …` was routed | `TestGroupSnapshot` (every `set` mutator, enumerated from `set` itself). Fix: `GroupTags` (frozenset subclass, mutators raise with the `tag` / `untag` spelling); `Registry.add_to_group` / `remove_from_group` swap snapshots; `c.group \|= {…}` rebinds through the synced setter |
| K4 | Writing a field on an interned look changed every shape using it | `a = Recolor("blue"); a.key = "red"` → `Recolor("blue").key == "red"`; `_key_hsv` still blue | Same-argument looks are one cached object (intern key = ctor args); public fields were plain attributes | `TestInternedLooksFrozen` (44 exported looks and filters, known and new field names). Fix: `_interned_setattr` on `Visual` / `FilterEffect` refuses public writes once `_ready` on `_interned` instances; hot private cursors (`_rp_stroke_i`) write `__dict__` directly |
| K5 | `Point.temp(...).id = "x"` was accepted and `obj("x")` found nothing; the guide said `.id` was writable though every registered item raised `ValueError` | `p = Point.temp(1, 2); p.id = "ghost"` | The setter allowed the first write while `_id is None` — reachable only on never-registered items | Retired with ids (2026-09-29): `id` is plain ink now (`test_registry_key_fields.TestNoEntityIdKey`). Original fix: setter always raised `AttributeError` (was `ValueError`) with the `id=` / `tag` spelling; `register` writes `_id`. The Guia audit missed the row because it wrote the current value back (the setter's same-value early return); it now writes a different value and restores (`validate_guia.probe_value`, `test_api_robustness.TestGuiaAccessProbe`) |
| K6 | `sprite.gray = 0` left the sprite gray after another module had built `Grayscale(0.00001)` (deep-tier serial pass: `test_off_spellings` failed, passed alone) | `Grayscale(0.00001); s.gray = 0` → `s.gray` is a Grayscale | The intern key is `round(amount, 4)` but `__init__` stored the raw amount, so the **first** caller decided what every later same-key call read; `coerce_gray` turns gray off only when `amount == 0` | `test_sprite.TestSpriteGrayStamp` (`test_off_spelling_after_a_tiny_amount_was_interned`, `test_interned_amount_does_not_depend_on_creation_order`). Fix: store the rounded key value. Rule: an interned look whose key rounds a field stores the rounded value. Still first-caller-wins, cosmetic only (nothing branches on the exact value): `HueShift.amount`, recipe `_intern_extra` knobs |

### O — order / isolation (2026-09-28)

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| O2 | `test_run_loop.TestCameraAfterUpdate` crashed in the deep tier's serial pass (`'_DummyLabel' object has no attribute 'is_alive'`) and passed alone | `python -m unittest tests.test_framework_debug tests.test_run_loop` | `test_framework_debug` put a stub on the process-wide `fw._system_label` and never restored it; the scene build's idempotent `_build_system_labels` then read `.is_alive` on it | Fix: the test restores the real label (`addCleanup`); the guard is `getattr(label, "is_alive", False)` for both labels (anything that is not a live Scena label is replaced). Class guard: the deep tier's serial pass. Rule: a test that assigns onto the `ScenaFramework` singleton restores it |
| O3 | Every editor system test failed in one process after `test_ui_layer` (`Text.visible cannot change a destroyed actor … destroyed at test_ui_layer.py:36 in setUp`) and passed alone | `python -m unittest tests.test_ui_layer scena_editor.tests.test_editor_system` | `test_ui_layer`'s setUp wipes the registry (`destroy_all`), which also destroys the framework's HUD labels; the frame body's `_refresh_system_label` / `_refresh_error_label` then wrote to the dead labels. Hidden until a module after it stepped real frames — the deep serial pass started covering `scena_editor/tests/` | Fix: `ScenaFramework._live_label` — a dead HUD label is skipped (rebuilt at the next game start); `test_ui_layer` rebuilds the labels after itself. Guard: `tests/test_hud_labels.py` (frames with both labels destroyed, system info on, a pending warning). Rule as O2: a test that wipes or patches framework singletons restores them |
| O4 | Deep serial pass (2026-10-09, also on `1ec7001`): 43 program-run teardown checks reported `registry.draw_live` moving (1608 → 1610) | `python -m unittest tests.test_shapes tests.test_program_support.TestProbesAndTeardown.test_a_run_leaves_nothing_behind` (draw 583 → 720) | Harness: `SystemWorld.__init__` parked the leftovers before `ProgramRun` took `census_before`, and teardown resumed them before `census_after`; a parked Point leaves its layer, so each parked drawn leftover read as the program's leak. Not an act reset: the program touched nothing | `test_program_support.TestProbesAndTeardown.test_leftovers_from_another_module_are_not_the_programs` (a shown Point, a Circle, a hidden Point on a layer left alive). Fix: `SystemWorld(quarantine=False)` + `world.quarantine()` after `census_before`. Rule: [Harness pitfalls](#harness-pitfalls), "Parking changes the census" |
| O5 | With O4 fixed, `draw_live` still moved by one: a Point that `test_shapes` left hidden on `'default'` came back on `layer=None` after the quarantine | `p = Point(0, 0); p.layer = "default"; p.active = False; p.active = True` → `p.layer is None` | Engine: `_park_self` wrote `visible = False` to an item already hidden, and `_resume_self` wrote `False` again. On a hidden Point that sits on a layer, that write is not a no-op: it takes the point off the draw list (`_layer_while_hidden`), so the round trip was not an identity | `test_process.TestParkRoundTripKeepsPlacement` (ten kinds, shown and hidden, layer / visible / draw list / pointer list, two round trips). Fix: park and resume write `visible` only when it changes ([Actors Design](Actors%20Design.md#active-park)) |
| O6 | `test_endless.TestOtherLayers.test_xy_grid_free_roam`: `256 not less than 256`, serial pass only | `boot(); init(width=800, height=600)`, then the test | Test isolation: the slot counts follow the view area, and the module never set the design size. Alone it ran at `boot()`'s 400×300 (peak 97 slots); in the serial pass it ran at the last module's 800×600 and an xy grid with `step=(120, 90)` reached `_SLOT_CAP`, as designed (cap + warning) | `EndlessCase.setUpClass` pins `init(width=400, height=300)`. Rule: [Harness pitfalls](#harness-pitfalls), "A module that never calls `init()`" |
| O7 | With O4 fixed, the serial pass failed the galaga program specs (`heroi_n = 2` on frame 1; no shot past y 900). It had passed before only because other leftovers masked it | `python -m unittest tests.test_driver_composition tests.test_prog_galaga_acts.TestGalagaActs.test_spec_a_idle` (also on `d9abd91`) | Test isolation: `TestCloneMotionThenResolve` called `self.setUp()` mid-test to run a second case, and `setUp` resets the tracking list, so the first case's wall and its two Rects in group `"heroi"` were never destroyed. Parked leftovers stay in their groups, and the program's `group["heroi"]` counted them. `test_process`'s PM8 frame-count loop leaked the same way | `test_run_tiers.TestSetUpAgainTearsDownFirst` (AST: every `self.setUp()` inside a test follows `self.tearDown()` / `self.w.teardown()`). Fix: tear down first in both modules |
| O8 | With O4 and O7 fixed, naves and galaga specs still failed in the serial pass: enemy shots vanished at y ≈ −150 ("inside the playfield") and no player shot passed y 900 | `python -m unittest tests.test_noop_cost tests.test_prog_naves.TestNaves.test_spec_b_idle` | Test isolation. `test_noop_cost` writes every world setting back to itself inside `system_world()`, and `playfield.left = playfield.left` turns the auto playfield into fixed edges for the current 400×300 view. `SystemWorld` never gave world settings back, and `ProgramRun` started each program from whatever it found, so the program's `init(1000, 800)` kept the stale edges. It had passed on `d9abd91` by luck: the last `init()` before it was 1000×800, so the pinned edges matched naves. The O6 fix changed that size. A module-by-module audit found `test_closed_surfaces` pinning it too, and four modules leaving the background base / fields / paint defaults | `test_sys_lifetime.TestWorldGivesBackItsSettings` (a world restores every `act.WORLD_SETTINGS` entry it does not reset); `test_program_support.TestProbesAndTeardown.test_a_program_starts_from_fresh_world_settings`. Fix: `SystemWorld` snapshots the settings at start and restores them at teardown; `ProgramRun` starts every program from the framework defaults (`system_support.reset_world_settings`, landed in parallel from `test_prog_isolation`), as a real program starts in a fresh process, and gives back the old ones at close |
| O1 | `test_change_gated_update.test_point_temp_does_not_link_attributes` failed when its module ran alone (`28 != 38` graph nodes) and passed inside `discover` | `python -m unittest tests.test_change_gated_update` | The baseline was read while the previous test's garbage was still pending; a GC pass mid-loop ran the GC-backstop finalizers and purged 10 nodes. Earlier modules in `discover` shifted the GC timing and hid it | `_settled_nodes` (collect until nothing is freed) before each baseline and final read in that module; class guard: the gate tier runs every module alone |
| O9 | `test_reactive_edge_cases.TestFailedLinkInstallsNothing` failed when its module ran alone (`15 != 17` graph nodes; `12 != 17` on the next run) and passed when its class ran alone | `python -m unittest tests.test_reactive_edge_cases` | O1 again, in a test written after O1's rule: the baseline was a raw `len(graph.nodes)`. `TestEvents` and `TestDerivateWriteStaysCold` (earlier in the module) leave Attributes / Points in reference cycles; the weak graph keeps their nodes until a GC pass, which landed between the baseline and the final read. The engine was right: settled with the GC paused, the rejected link installs nothing. An audit found the same raw count in `TestNoLinkOntoADestroyedActor` and nine other modules (`test_api_robustness`, `test_box_snapshot`, `test_graph_gc_backstop`, `test_graph_lifecycle` and `test_ephemeral_math` with one bare `gc.collect()`, `test_history`, `test_hyp_surface`, `test_input_reactive`, `test_shapes`) | `tests/graph_support.py` (`settled_graph_size`, `gc_paused`); every site moved to it. Class guard: `test_count_baselines` — static (every `len(<…>.nodes)` in `tests/` and `scena_editor/tests/` follows a settle in its function, its caller chain or its class's `setUp`) and dynamic (`run_with_collections`: garbage planted, a full collection at each assert; the O9 test passes, its original shape fails as canary) |
| O10 | Found while sharding `test_prog_isolation` (2026-10-10): its gate shards would have run ~50 of its ~190 `ci` cells and passed | `run_tiers.list_ids_subprocess("test_prog_isolation")` from a shell without `SCENA_HYPOTHESIS_PROFILE` | Runner: `plan` lists a `SPLIT` module's test ids in a child started with the **parent's** environment, and the parent has no tier env. A module that generates its tests from the profile (`test_prog_isolation`: every ordered pair at `ci`, a chain at `dev`) gave its `dev` ids to a `ci` gate. Unseen while `test_hyp_surface` was the only `SPLIT` module: its ids do not depend on the profile | `test_run_tiers.TestShard.test_split_ids_are_listed_with_the_tiers_env` (gate, deep, `--profile`) and `test_every_split_module_really_shards` (real ids through the same lister). Fix: `main` lists through `ids_lister(tier_env(...))` |

### SC — scenes (2026-09-28)

Found while building [Act Design.md](Act%20Design.md).

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| SC1 | A key press from one act fired `keyp.once` in a later one | Hold SPACE to shoot in `Fase` (read only as `keyp("SPACE")`), lose → `FimDeJogo.on_update`'s `keyp.once("SPACE")` is True on its first frame and skips the game-over screen | An unread rising edge stays in `KeyPressed._pending_edges` until the first `once` reader — even long after release (by design: a same-poll press + release must still be seen). Nothing dropped it on an act change | `test_act.TestScopesAndScriptRules.test_a_key_press_does_not_carry_into_the_next_act`. Fix: `KeyPressed._swallow_edges()` (shared with the modal-mask lift) runs on every change. Generalized by PM3: unread edges now expire every frame |
| SC2 | An undrawn entity kept only by the act's ink could skip its `on_destroy` | `class F(Act): setup: self.d = Diretor()`; GC between the act's own teardown (clears ink) and the batch drain | The registry holds undrawn entities weakly; the batch was only held from the drain on | `test_act.TestStartAndChange.test_undrawn_entity_held_only_by_act_ink_still_gets_on_destroy` (forces the GC at that point). Fix: `SceneManager.change` holds the whole batch strongly for the change |
| SC4 | `until_empty("inimigo")` warned "No group 'inimigo'. Did you mean 'tiro_inimigo'?" the moment the fleet was cleared (found running the Act sample game; not act-specific) | A group `"inimigo"` and a group `"tiro_inimigo"`; `await until_empty("inimigo")`; destroy the last enemy | The per-frame poll went through the author lookup `group[name]`, whose near-miss guard warns for a name missing from `group_map` — and the registry deletes a bucket when it empties | `test_process` (`test_until_empty_does_not_warn_when_the_group_empties`, `test_until_empty_typo_still_warns_at_the_call`). Fix: check the name once at the call; poll `Registry.group_live_count` / the formula view |
| SC3 | (design) "Stop the collision step after a change in a handler" would lose a surviving pair's `enter` and a game body's `exit` | `@collide` handler calls `change_act`; a game pair later in the same step | The existing dead-pair rules already drop every old-act pair; stopping the step also drops the survivors | `test_act.TestScopesAndScriptRules.test_change_act_in_a_collide_handler_drops_the_old_acts_pairs` (game pair dispatched after the change). Fix: no act guard in `CollisionSystem.step`; design doc corrected |

### G — geometry properties (2026-09-28)

Found by the transform / round-trip / invariance properties (grid tiling, camera
round trip, collision under a world shift, chase frame-rate independence, vertex-level
rotation algebra for every kind). G1 was an engine bug; G2 was the property being
stricter than the contract; the rest held. G3–G8 were found while making Rect
named points follow their points (2026-09-29 / 30), G9 onwards by the geometry contract sweep: all engine bugs.

| ID | Bug | Shrunk repro | Root cause | Why earlier tests missed it | Guard |
| --- | --- | --- | --- | --- | --- |
| G1 | `Point.rotate_by` about the point itself left `rotation` unchanged (`rotate_to` set it; every other kind adds). `collision.raycast(p, length=)` reads that heading | `p = Point(5, 5); p.rotate_by(60)` → `p.rotation == 0` | Early return when the pivot equals the point ("no-op for position") skipped `_pose_rotation_add` | `TestPoseAlgebra` covered Shape kinds only; the Point test checked position only | `test_shapes.TestPoint.test_rotate_by_about_self_still_turns_the_heading` (+ linked point); class guard `test_hyp_api.TestRotationGeometry` (every kind with its own `rotate_by`, vertices + heading, `@example` of the repro) |
| G2 | **Test fix, engine unchanged (by design).** Deep tier: `TestTranslation.test_moving_the_world_keeps_contacts` saw a contact appear after `move_by(0, 1)` of every body | Rect `(1, 2)` 10×5 (group `hb`), Polygon `(1, -6.5)–(39, -1.75)–(24.75, 22)` (group `ha`), four r=3 circles at the origin; `dx=0, dy=1, steps=1` → contact (5, 4) only in the moved world | The rect corner `(6, -0.5)` lies exactly on the polygon edge `(1, -6.5)–(24.75, 22)`. SAT projects world coordinates onto a normalized (irrational) edge axis; the corner is 1 ulp outside at `y`, 1 ulp inside at `y + 1`. Contract decided (user, 2026-09-29): touching counts, but at exactly zero gap either answer is allowed ([Collision Design — Touching and tangency](Collision%20Design.md#touching-and-tangency)); a translation-invariant narrow phase is not worth its cost for a game | The property compared contact sets exactly; only the `deep` profile found a dyadic polygon whose corner lands exactly on an edge | `test_sys_hyp_collision.TestTranslation` (both properties: contacts may differ only on pairs within `TANGENT_EPS` = 1e-6 of zero gap in either world; `@example` of the repro); `TestTangencyTolerance` (the repro is tangent at `dy` 0 / 1 / 4096; a 1e-3 gap or overlap is not, so the hatch cannot pass vacuously). Class: **An oracle is stricter than the contract** |
| G3 | `flip_x` on a `POINT_VEC` rect moved the box | `Rect(p1=(0, 0), vec=(100, 50)).flip_x = True` → frame center (50, 25) → (150, −25) | The generic `Shape._mirror_scalars` turned `rotation` to `180 − θ` **and** negated `vec.x` — two mirrors, i.e. a displacement. Under the flip convention a mirror negates `vec.y` on either axis | Flip tests checked Line / Circle / Square read-backs and flip-twice identity, never that the region stayed put, and never `POINT_VEC` | `test_rect_names.TestFlipMirrorsNamedPoints` (every named point lands on its mirror; region unchanged; twice = identity; every Rect/Square model × rotation × crossed × axis; `@example` of the repro; canary: a rotation-only flip is caught). Class: **A mirror is applied as a rotation (or twice)** |
| G4 | `flip_x` / `flip_y` on a `SPINE` `side_left` / `side_right` rect moved the box across `p1→p2` | `Rect(p1=(0, 0), p2=(100, 0), height=20, anchor="side_left").flip_x = True` → center y 10 → −10 | Mirroring `p1`/`p2` reverses the handedness of `p1→p2`; the anchor kept its side, so the box landed on the other one. The anchor now swaps | Same as G3 | Same property (`@example`s for both anchors and axes) + `test_spine_side_flip_keeps_the_box_in_place`. Class: **A mirror is applied as a rotation (or twice)** |
| G5 | Derivate `vec` went stale on every model where it is Derivate (Rect, Box, Line): filled on first read, never refreshed | `r = Rect(p1=(0, 0), p2=(100, 50)); r.vec; r.p2.x = 300` → `r.vec` still (100, 50) | Two causes. (1) No `_update_impl_*` wrote `vec` (it was missing from the write lists). (2) Pull resolution: a Derivate `Vec2` has its own `_update_impl` (length / angle), so `_local_refresh_root()` stopped at it and never asked the owner to rewrite `x` / `y`. `_resolve_structural` now pulls a Derivate part's owner first ([Reactive Design](Reactive%20Design.md#_ensure_fresh--_resolve_--pull-on-read)) | Derivate tests read each part once, right after construction; nothing wrote a Defining part and read the Derivate again | `test_rect_names.TestDerivatesMatchAFreshTwin` (Rect / Square / Box, every model: read every Derivate, write a Defining part, compare every part with a freshly built twin; `p2 == p1 + R @ vec`; canary: an update that skips `vec` is caught). Class: **A Derivate is missing from the update's write list** |
| G6 | `EquilateralTriangle.flip_x` / `flip_y` drew a different triangle; `RegularPolygon` / `EquilateralTriangle` `vertex=` flips moved the shape | `EquilateralTriangle(center=(0, 0), radius=10, rotation=10).flip_x = True` → apex down, not mirrored; `RegularPolygon(vertex=(3, 4), side=6, n=5, rotation=10).flip_x = True` → center (−2.0, 3.1) → (8.0, 3.1) | The generic flip mirrored `rotation` (`180 − θ`), but the triangle's vertex-0 heading is `rotation + 90`, so the heading was not mirrored. It also never touched the Defining `vertex` of `VERTEX_SIDE`, so the polygon turned about it. `RegularPolygon._mirror_geometry` now mirrors the heading and the vertex | The G3 property covered Rect / Square only; the earlier kind sweep compared one read-back, not the drawn vertex set | `test_flip_mirror.TestFlipMirrorsEveryKind` (every kind and model: drawn geometry is the mirror, center fixed, twice = identity; `@example`s of both repros; canary: the generic rotation mirror is caught). Class: **A mirror is applied as a rotation (or twice)** |
| G7 | A flipped Sprite's `box.top_center` sat at its feet; `rect.box` / `Box(graphic)` of any flipped frame lost the mirror | `Sprite(…, center=(100, 100)).flip_x = True; sprite.box.top_center` → (100, 64), was (100, 136) | `flip_x` turns a Sprite's heading to `180 − θ` and draws the art mirrored. `.box` copied the angle (180) but not the mirror, so its frame was the sprite turned upside down. `.box` now carries the source's name signs (`box.region_name_signs`): a Box made from a Graphic is its frame, names included | `.box` tests used unflipped graphics | `test_rect_names.TestBoxCarriesNames` (flipped Rect / Sprite / Text boxes, board cell through turns and flips, fleet slot, `box=` placement). Class: **A mirror is applied as a rotation (or twice)** |
| G8 | `RegularPolygon` / `EquilateralTriangle` `signed_area` read 0 (always, until a Defining write) and `perimeter_length` read 0 on its first read | `RegularPolygon(center=(0, 0), radius=5, n=4).signed_area` → 0.0, not 50 | The first read materializes the stat slot, then asks `_update_impl` to fill it — but `_stats_live()` cannot see a slot that is still being created, so the stats were skipped and the slot kept its default. Nothing re-dirtied it. The materialize path now computes the stats itself | Stats tests read `centroid` first (which placed every vertex) or used a free `Polygon` | `test_flip_mirror.TestRegularPolygonStatsMatchAFreePolygon` (every model, each stat as the first read, against a free `Polygon` on the same vertices — an independent oracle, so a stale default cannot pass). Class: **A Derivate is missing from the update's write list** |
| G9 | RegularPolygon / EquilateralTriangle Derivate `vertex` read (0, 0) in the `center=` models; the G8 stats fix was incomplete — `signed_area` / `perimeter_length` read 0 when `side` / `radius` was read first | `RegularPolygon(center=(3, 4), radius=6, n=5).vertex` → (0, 0); read `.side`, then `.signed_area` → 0 | No `_update_impl_center_*` wrote `vertex`. `_stats_live()` looked for a stat's value in `__dict__`; on a first read of a dirty polygon the slot is registered (`_derivate_state`) but has no value yet, so the stats were skipped | Found by the geometry contract sweep (C1 / C4 / C5); the G8 test read each stat on a fresh polygon only | `test_flip_mirror.TestRegularPolygonStatsMatchAFreePolygon` (`test_stats_do_not_depend_on_what_was_read_first`, `test_vertex_is_points_zero_in_every_model`); `test_geometry_contract` C4 read order. Class: **A Derivate is missing from the update's write list** |
| G10 | `Square(top_left=).scale_by` moved the square (both pivots) | `Square(top_left=(3, -2), length=20, rotation=15).scale_by(1.5)` → center drifts | `Rect.scale_by` (TOP_LEFT_WH) wrote the new size, then placed `top_left` from a re-read `_wh_signed()` — a Square's `length` is scaled only after `super().scale_by`, so the old side placed the corner | Square scale tests used `center=` | `test_shapes.TestSquare.test_top_left_scale_keeps_the_pivot`; `test_geometry_contract` C1 / C2 |
| G11 | `Track.line(p1=, p2=)`: once `cursor` was read every read recursed; `.center` read (0, 0) and then lagged a move by one refresh; `move_by` / pivot `rotate_by` / `scale_by` did not move it (the documented `ship.center @= track.cursor` crashed) | `Track.line(p1=(0, 0), p2=(40, 10)).cursor` → RecursionError | `_refresh_cursor` called `at()` → `_ensure_samples` → `_update_impl` → `_refresh_cursor`. The Derivate centroid was initialised to (0, 0), written only at flatten (a translation keeps the centroid-relative key, so no reflatten), and the track was never flagged pull-live. The shared pivot verbs wrote the Derivate `center` | Track tests used presets whose `center` is Defining; nothing read `cursor` on a control-point track | `test_track.TestTrackGeometryContract`; `test_geometry_contract` C1 / C2 / C4. Class: **A kind implements a shared verb its own way** |
| G12 | Track flips changed only the flag; `cursor` kept its world spot after `rotate_by` / `scale_by` | `Track.eight(center=(3, 4)).flip_x = True` → `at(0.1)` unchanged | Track had no `_mirror_geometry` (its heading is a pose, not a Defining part); the pose verbs never dirtied the track, so `cursor` was not refreshed | No flip test on Track | `test_track.TestTrackGeometryContract` (`test_flip_mirrors_the_path_in_place`, `test_cursor_follows_rotate_and_scale`). Class: **A mirror is applied as a rotation (or twice)** |
| G13 | The cull box ignored rotation for Text and Track: a turned caption or path near the edge could be culled while visible | `Text("a long caption").rotate_by(90)` → cull box still wide and short | Text's `_domain_aabb` returned the unturned layout box; Track had none, so `_approx_draw_aabb` fell back to a guess | Cull tests used unrotated actors | `test_track.TestTrackGeometryContract.test_cull_box_contains_a_turned_track_and_text`; `test_geometry_contract` C6 |
| G14 | Line `rotation` was a counter that started at 0 whatever the line's direction (after `rotate_to(50)` it read 33); flips left a pose heading unchanged on Point / Anchor / Polygon / Line | `Line(p1=(0, 0), p2=(38, 12)).rotate_to(50); line.rotation` → 33 | Line kept only the pose accumulator `_rotation`, never synced to its segment; the generic `_mirror_geometry` mirrored Defining `rotation` / `angle` only | Rotation tests compared deltas, not the reading against the geometry | `test_angle_field.TestAngleIsTheHeading`; `test_geometry_contract` C2 (pose conventions). Class: **A kind implements a shared verb its own way** |
| G15 | `clone()` dropped the pose: `scale`, flip flags and a pose heading reset on every Shape; Sprite / Svg / Text copies faced the rest heading at scale 1; Text copies were re-placed by `center`; Track copies baked the pose into their points (rotation 0, scale 1) and resampled a curve at uniform `u`; Rect `p1=, p2=` / `p1=, vec=` copies named other corners `p1` / `p2` | `r = Rect(p1=(0, 0), p2=(40, 20)); r.rotate_by(20); r.scale_by(1.25); r.clone().scale` → 1 | Each recipe rebuilt geometry and left the pose stores at their construct defaults; Rect rebuilt every model as `CENTER_WH` (its `p1` / `p2` become Derivates on fixed corners); Sprite reseeded its heading on purpose (old contract) | Clone tests compared geometry, not the pose readings or part identities | `test_geometry_contract` C7 (canary: `test_c7_catches_a_clone_that_drops_the_pose`); `test_rect_names.TestCopiesCarryNames`, `test_track.TestTrackGeometryContract`, `test_text.TestTextFrame`, `test_sprite.TestSpriteArtAngle`. Fix: `Graphic._clone_pose_from` (Sprite adds `tilt`, Track reads the host pose), Rect clone keeps its model, Text clone keeps its anchor form, Track clone freezes its table in its own frame. Class: **A kind implements a shared verb its own way** |
| G16 | A `reversed()` Track view's pose disagreed with its drawing: `rotate_by` / `scale_by` / flips wrote view slots nothing drew (`view.rotation` read 30, the path did not turn); `view.center` was a copy that went stale after `move_by`; `radius` read 0; `shape_outline(view)` was empty (so the contract's drawn checks were blind to views); the view's `cursor` raised on first read, then went stale; a destroyed view was handed out again by `reversed()` | `v = Track.eight().reversed(); v.rotate_by(30); v.at(0.1)` → unchanged | The view was a bare `Track` sharing tables by alias: drawing read the host via `_pose_host()`, but the fields and verbs were the view's own; `object.__setattr__(view, "center", root.center)` went through `ContainerSlot.__set__` and copied the value; the view's `_xs` was a construction-time alias | Views were not in the geometry registry; the view tests checked `face=` and rider snapshots only | `test_geometry_contract` (KINDS: `Track eight / circle / line point_point reversed`); `test_track.TestTrackGeometryContract` (`test_a_reversed_view_shares_the_host_pose`, `…link_on_a_view_writes_the_host`, `…view_cursor_follows_the_host_pose`, `…destroyed_view_is_not_handed_out_again`). Fix: `_ReversedTrack` with `_HostField`s and forwarding verbs; `_travel_vertices()`. Class: **A kind implements a shared verb its own way** |
| G17 | A circle placed by its rim (`perimeter_point=` / `p1=, p2=`) had two headings: `rotation` read the arc `angle` (0 by default) while its frame — `p1`, `circle.box` — pointed elsewhere, so the arc opened away from its own rim point | `Circle(p1=(1070, 400), p2=(1250, 520))` → `rotation` 0, `box.angle` −146 | `angle` stayed a free Defining input on every model; the rim models' frame came from `_rim_heading` | The contract compared a Circle's `rotation` with its `angle`, never with its frame — found by the visual smoke (`scripts/smoke/geometry.py`, Circle rim page) | `test_geometry_contract` C6 (`box.angle is not rotation`, every kind with a frame); `test_shapes.TestCircleRimPoints` (`…rotation_is_the_direction_to_p1`, `…moving_the_rim_point_turns_the_heading`, `…angle_at_construction…`, `…writing_the_heading…`, `…linked_rim_point_is_refused`). Fix (decided 2026-09-30): on rim models `angle` is a Derivate — the direction to `p1` (`_arc_angle`, unwrapped to the turn count); writes / links / `angle=` turn the rim about the center (`_DerivedRotationRoute`, heading field `angle`). Class: **A kind implements a shared verb its own way** |
| G18 | A formula that names `shape.rotation` went stale when the heading changed without a pose verb: a `center=, radius=` Circle on a flip, `angle =` or an `angle` link; a Line when an endpoint was written or dragged; a `reversed()` Track view on every change (its formula bound the view's own, never-notified node) | Geometry smoke, Heading page: `flip_x` → the arc flips, its heading arrow (`p2=` a function reading `arc.rotation`) stays | Formula sources come from the source text, so the formula depends on the `rotation` property anchor, which only `_pose_rotation_set` / `_pose_rotation_add` mark dirty; Line and Circle read `rotation` from their geometry, and a Circle flip writes `angle`, not the pose value | The checks re-read `rotation` (a pulled read re-evaluates); the unit repros used stdin lambdas, whose source cannot be read, so they took the broad path. Found by the user on the visual smoke | `test_angle_field.TestAngleFormulasStayFresh` (every registry kind × heading change, plus endpoint writes and links, read bare); the smoke's `arrows follow rotation` check (fails on the old engine). Fix: `_HeadingFromGeometry` (Line, Circle: the `rotation` anchor depends on the shape), `Circle._sync_rotation_to_angle`, `_ReversedTrack._ensure_scalar_anchor` → the host's node. Class: **A check reads through the path it is meant to test** — verify a linked consumer by what it holds (read bare), not by re-reading the source |
| G19 | One heading, two names: Rect / Square / Ellipse / RegularPolygon / EquilateralTriangle called it `rotation`, Line / Circle / Box / Jet `angle`. `rect.angle = 30` was accepted as a custom ink field and the rect did not turn; a p1/p2 Line read `angle` 40 and `rotation` 400 after `rotate_by(400)`; the tangent Line read `rotation` 240 after `rotation = 150`; and `rotation = θ` / `rotate_to(θ)` gave different geometry under one name on shapes placed by a corner, an end or a vertex | `Rect(center=(0, 0), width=4, height=2).angle = 30` → `rotation` 0; `Line(circle=c, angle=0, length=20).rotation = 150` → 240 | Unify Phase 1 merged `angle` into `rotation` on five kinds and deferred Line; the noun of `rotate_to` became a field whose write keeps the placement point; the ink near-miss check only catches names of 6+ letters one edit from a real property; `Line.rotate_to` measured from the tangent model's *position* `angle` | Each kind was tested in its own spelling; nothing wrote the other kind's name and checked that the shape turned | `test_angle_field` (`TestRotationIsRetired`: every kind × every `rotation` spelling, and every `_INK_RESERVED` name never becomes ink; `TestAngleWorksOnEveryKind`: `x.angle = v` reads back and `rotate_by(400)` reads `+400` on every kind; `TestLineTangent`). Fix: the heading is `angle` on every Graphic ([Shapes Design — Geometry contract](Shapes%20Design.md#geometry-contract)); `rotation` in `Graphic._RETIRED_ATTRS`; tangent input `at_angle`. Class: **A kind implements a shared verb its own way** — and its sibling: **a retired or reserved name becomes ink** |
| G9 | `sprite.box` sat half a height low under `Sheet(anchor="bottom")` and ignored `scale` | `Sprite(Sheet(p, anchor="bottom"), center=(100, 100), width=64, height=64).box` → bottom 68, top 132; the art spans 100..164. `s.scale_by(1.5)` left `box.width` at 64 | `region_frame` built a Sprite's box from `center` + `width` / `height`. `center` is the **pivot** (at the feet under `anchor="bottom"`) and `width` is the size knob (no `scale`). It now uses the drawn rect (`Sprite._oriented_frame`) and keeps the heading as the angle (G7's names) | `.box` tests used centre-anchored, unscaled sprites, where pivot = middle and knob = drawn size | `test_sprite_measure.TestSpriteBoxIsTheDrawnCell` (anchor, scale, offset, flips, rotation about the pivot, the hitbox inside the box — independent expected numbers). Class: **A measurement read from the pose knob instead of the drawn geometry** |
| G20 | `confine` lifted a Sprite under `Sheet(anchor="bottom")`: a ninja walking into the screen edge climbed ~1900 units/s to the top (tutorial 14, 2026-10-09) | `s = Sprite(Sheet(p, anchor="bottom"), center=(990, 300), …)`; each frame `s.move_by(5, -5); s.confine(canvas.game_view)` → `center.y` rises instead of falling | `confine` compared `_center_xy()` (the **drawn** middle, G9) and wrote the result with `_move_to` (the **pivot**, at the feet): every clamp moved the pivot up to where the middle was. Now `by="center"` compares the pivot and `"box"` / `"overlap"` the drawn box, and the correction is applied to the pivot as a delta | confine tests used shapes and centre-anchored sprites, where pivot = middle; the platformer tutorials were the first anchored sprites to touch an edge | `test_confine.TestAnchoredSprite` (center / bottom / top anchors, every `by=`, wrap and bounce; verified to fail on the pre-fix code). Class: **A pose writer fed a point measured in another frame** (drawn box vs pivot) |

### SR — scripts on retired spellings (2026-09-30)

Found when a headless pass ran every smoke / example script after the hitbox rename. Each failed the same way on the commit before it: pre-existing, invisible until someone opened the window.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| SR1 | `scripts/smoke/colliders.py` raised at construction | `obj.group.add("lab")` on the read-only `GroupTags` snapshot (K3 closed that door) | `test_scripts_run` (since 2026-10-10 `test_smoke_scripts`). Fix: `obj.tag("lab")` |
| SR2 | `scripts/bench/historical/galaga.py` raised at construction, then at `set_framerate` | `Text(x1=, y1=)` (placement is one point since the Text rework) and `set_framerate(FrameRateControl.NONE)` (now `canvas.framerate`) | `test_scripts_run` (since 2026-10-10 `test_smoke_scripts`) (listed in `EXTRA`, all six ablations checked by hand). Fix: `top_left=(20, H - 36)` — `x1` / `y1` was the top-left corner; `canvas.framerate = "max"` |
| SR3 | Five smokes (`background`, `box`, `camera`, `confine`, `world_view`) and `app_glowspot` raised on the first frame | Punctuation key names (`","`, `"."`, `"["`, `"]"`) are not Scena keys; the smoke convention is A / S (primary), Q / W (paired), E (quality) | `test_scripts_run` (since 2026-10-10 `test_smoke_scripts`). Fix: drop the punctuation alternates; glowspot: E quality, Q / W count |
| SR4 | Four color names that Scena does not know painted magenta: `"slategray"` (`shape_fx` debris swatch), `"mediumseagreen"` (`smoke/tracks`), `"medium turquoise"` (`smoke/collide`), `"slate gray"` (Guia `Fog` card) | An unknown name only warns and falls back to magenta. The harness ignores warnings, and a click-only swatch or a card's second line never runs; Scena's 67 names are not CSS / X11 (`"dim gray"`, `"sea green"`, `"turquoise"`) | `test_color_literals` (static: color-knob keywords and `*SWATCH*` tuples in scripts, `color="…"` in the Guia catalogs / page / tutorials; vacuity check on the detector). Fix: the nearest Scena name |

### HB — hitbox lifecycle and read-only fields (2026-09-30)

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| HB1 | Writes on a dead or removed hitbox behaved three ways: part `shape` / `anchor` / `scale` / `active` wrote silently, `source` / `px_*` / group claims raised `RuntimeError`, and `sprite.hitbox.active = False` did nothing | Each writer had (or lacked) its own alive check | `test_hitbox_model.TestDeadAndReadOnly` (writable set discovered from the classes; canary: dropping one check fails it). Fix: one `_refuse_dead` → `DestroyedError`, reads stay |
| HB2 | `hb.box = …`, `hb.host`, `hb.is_alive`, `hb.layer`, `hb.group`, `sprite.hitboxes = …` raised Python's "property … has no setter" | Read-only properties with no setter | Same class (`test_read_only_fields_speak_scena`). Fix: `_read_only` setters with the Scena spelling. Other Entity read-only properties (`is_alive`, `touching_sides`, `rest_heading`, …) still use Python's text — not yet swept |

### PH — pointer hover and pointer callbacks (2026-09-30)

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| PH1 | `pointer_hover` stale: True after `visible = False`, `clickable = False` or the shape moving away from a still cursor; a new clickable on top never took hover; a Button over a shape left both hovered; a modal left the shape hovered | Hover recomputed only in the mouse-move callback, per space, never exclusive with widgets | `test_pointer_hover.TestStaleness` / `TestPress` / `TestWidgets`, `test_hyp_hover`. Fix: tiered `ShapeInteractionManager.step_hover` once per frame + `registry._pointer_epoch` + `pointer_layers_signature` ([Shapes Design — Hover](Shapes%20Design.md#hover-pointer_hover-hover--hover_exit)) |
| PH2 | Every Graphic's `_draw_index` was −1: `Graphic.__init__` reset it after registration had set it | Default written after `super().__init__` registered | `test_pointer_hover.TestHitOrder.test_draw_index_set_at_construction`. Every hit order walked whole layers and every destroy took the `objs.index()` fallback |
| PH3 | `checkbox.on_click = f` (any non-Button widget) stored `f` and never called it; `@click(group)` skipped widgets silently; `@click(button)` raised; Button called `on_click()` with no payload while Graphics pass the target | `on_click` on the `UIWidget` base; a separate widget skip in `_iter_targets` | `test_pointer_hover.TestWidgets`, `test_widget_entity.WidgetEntityTest.test_click_takes_buttons_in_a_group`. Fix: `on_click` only on `Button` (`call_truncated(fn, button)`), one per-verb widget policy checked before any target is touched |
| PH4 | Pointer setters (`on_click`, `on_drag_*`, `on_drop_by`) took any value; a two-parameter handler failed at the click, frames later | No registration check | `test_pointer_hover.TestEdges.test_handler_arity`. Fix: `validate.check_pointer_handler` in every setter and decorator. `call_truncated` also passes everything to `def f(*args)` (it passed nothing) |
| PH5 | A parameter with a default received a payload the author never asked for: `lambda tool=tool: …` got the Button as `tool`, `app.save(then=None)` got it as `then`, `after(1, f)` with `f(who=None)` got the owner, `@on_change` `f(v=None)` got the value | Three counters (`call_truncated`, `process._argcount`, `events._callback_npos`) counted every positional parameter; the registration check (`required_positional_count`) counted only required ones, so registration and call disagreed | `test_payload_arity` (one test per hook kind: Button, shape click, `call_truncated`, timers, `on_update`, `@on_change`, plus partial / callable objects / classes). Fix: one counter, `validate.payload_arity` — only parameters with no default receive a value |

### SK — sky / gradient preset names (2026-09-30)

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| SK1 | `SkyGradient("space")` raised "neither a sky preset nor a color. Did you mean 'space'?", and its "Sky presets" list named `space`; `toxic`, `forest` and the aliases `void` / `cosmos` / `alien` / `radioactive` failed the same way. `Gradient("toxic")` / `Gradient("forest")` fell back to magenta with a warning | `SCENIC_PRESET_NAMES` and `_SKY_ALIASES` listed names `GRADIENT_PRESETS` had no ramp for (the forest ramp was keyed `tgreen`). The error built its list and suggestions from the name set, not from what resolves. The preset test exempted the missing names as "reserved / retired" | `test_gradient_presets` (`test_every_scenic_name_has_a_ramp`, `TestSkyPresetNamesResolve`). Fix: `space` / `toxic` ramps added, `tgreen` renamed `forest`; `_resolving_sky_names()` feeds the message |
| SK2 | `scripts/smoke/shape_fx.py` drew its `viridis` and `toxic` swatches magenta | Preset strings that are not preset keys (viridis is `vrds`) fall through to a color lookup, which warns and returns magenta | `TestSkyPresetNamesResolve.test_smoke_script_sky_and_preset_strings_resolve` (scans `SkyGradient("…")` and one-name recipe tuples in `scripts/smoke/*.py`) |

### IN — keyboard input (2026-10-01)

Found while spiking the level editor (Cmd+S / Cmd+O polled with `keyp.once`).

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| IN1 | `keyp.once("CMD+O")` fired for keys that were never down together. Pressing Cmd alone opened the dialog if O had been typed earlier; tapping Cmd and then O did too. A fast Cmd+S (S down and up within one poll, Cmd held and already read) did **not** fire | `update`: `if keyp.once("CMD+O"): …`. Tap O, then press Cmd | Unread rising edges stay in `_pending_edges` until a `once` reads them (by design). The same-poll fallback merged **every** pending edge with the keys down now, so presses from different moments made a chord. It also required the modifier's own edge to be unread | `test_keyp.TestOnceChordNeedsKeysDownTogether` (each repro); `TestOnceChordProperty` (random taps / toggles / reads: `once(spec)` fires only if the spec's keys were down together, with no extra modifier, since it last fired) with canary `TestOnceChordCanaries`. Fix: each pending edge keeps the keys that were down at that press. The fallback fires only when a pending press of one of the spec's keys had the whole chord down (`_pending_rises`). One read consumes **every** pending press that completed the chord (deep-tier find: O held, Cmd-L and Cmd-R tapped in one poll fired twice), as two taps of one key collapse into one edge — `test_left_and_right_modifier_taps_under_a_held_key_are_one_read` |

### WP — Windows / platform portability (2026-10-01, 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08)

WP1–WP4: found by the quick tier on Windows 11 (12 jobs failed; the Mac passed the same tree). Tests only: the engine rendered correctly. WP5–WP9: the quick and gate tiers on the same machine, five days later. One shipped fix (the editor's Linux `.desktop` writer); the rest is tests and the runner. WP10–WP15: the next gate runs on that machine (2026-10-06); tests and the runner, plus one engine bug, A33. WP16–WP17: latent, found by a read-only audit of the suite for platform defaults after those fixes (nothing failed yet). WP18: the quick tier on the Mac (2 of 7 runs on 2026-10-07); the test only. WP19: the quick tier on Windows (2026-10-08, 1 of 182 jobs); tests only.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| WP1 | 7 jobs (`test_registry_layers`, `test_api_docs`, `test_stamps`, `test_gradient_presets`, `test_message_vocabulary`, `test_doc_citations`, `test_audio`) raised `UnicodeDecodeError … 0xb0` or `DecodeError` | The tree was copied from macOS: 9 642 AppleDouble `._<name>` files. `os.listdir` + `endswith(".py")`, `os.walk` + `.md` and `Path.glob` / `rglob` handed them to `open(…, "utf-8")`, `ast.parse` and miniaudio | `test_platform_portability.TestSourceScansUseTheHelper` (AST over `tests/*.py`) + `TestIterFiles`; `test_run_tiers.TestAppleDoublePreflight`. Fix: all 19 scans go through `source_support.iter_files`; `run_tiers.py` warns on `._*` files |
| WP2 | `test_visuals` (4), `test_looks` (same 4), `test_text` (2), `test_menu` (1) read exact red / blue swaps | `kN32` is BGRA on Windows. `toarray()` on an N32 surface returned BGRA; `fromarray(px)` read an RGBA array as BGRA | `test_platform_portability.TestPixelsNameTheirByteOrder` (AST over `scena/*.py` and `tests/*.py`). Fix: every call passes `colorType=skia.kRGBA_8888_ColorType`, engine sites (`atlas.py`, `style.py`, `effects.py` Grain) included though they were safe |
| WP3 | `test_atlas` `TestSimplifyHull` round-mask budget (`test_round_mask_bake_stays_under_budget`, replaced in WP7) read 101 ms against a 40 ms budget | One `perf_counter` sample with 10 workers busy; the call takes ~22 ms alone | Best of 5 against the same budget. Not enough on a slower machine under sustained load: see WP7 |
| WP4 | `test_text.TestFontSpec` (2), `test_menu.test_font_file_changes_measure` failed once the local file went away | They read `media/fonts/Tiny5-Regular.ttf`, which was never tracked: they passed only on the machine that had it | Nothing checked that a test's data file is in the repo | `tests/font_support.system_font_file()`: a monospace `.ttf` installed with every OS (Courier New on macOS / Windows, DejaVu Sans Mono / Liberation Mono on Linux), explicit paths only; the tests skip with a reason when none exists. Rule: a test reads tracked files or OS files, never a local one. Open: tests reading a root `media/` folder (laser sprites, `media/svg/*.svg`) still *skip* because it is not tracked |
| WP5 | `test_version.test_changelog_has_a_section_for_this_version` did not find `## 0.5.0 — …` | `read_text()` with no encoding decodes as cp1252 on Windows: `—` became `â€”`. 12 more sites in `scena_editor/` (one shipped: the `.desktop` writer, which freedesktop requires in UTF-8) and 12 in `tests/` were latent | `test_platform_portability.TestTextIoNamesItsEncoding` (AST over `scena/`, `scena_editor/`, `tests/`, recursive; builtin `open` / `io.open`, `.read_text`, `.write_text`). Fix: every site passes `encoding="utf-8"`; `scripts/bench` and `scripts/tools` too (not guarded) |
| WP6 | `test_editor_dialogs` (3), `test_editor_launch` (2): `'C:\\a\\b.json' != '/a/b.json'` | Expected values were POSIX literals; `os.path.abspath` in `dialogs._absolute` / `shortcut.create` follows the host (correct: a dialog on Windows returns Windows paths) | Rule (Harness pitfalls, `tests/README.txt`): expected paths are built with the same path function. Fix: the tests use `os.path.abspath(...)`; the AppleScript assertion escapes backslashes |
| WP7 | `test_atlas` round-mask budget (`test_round_mask_bake_stays_under_budget`): best of 5 read 59 ms (`quick`) and 162 ms (`gate`) against 40 ms | Sustained contention (10 workers on 12 CPUs) slows every sample; WP3's best of 5 only drops spikes | `test_atlas.TestSimplifyHull.test_round_mask_simplify_is_not_the_cubic_recheck`: production `_simplify_hull` must be > 20× faster than the cubic reference in the same process (~215× measured on the Mac and on Windows). The absolute budget on `_choose_auto_collider` is dropped |
| WP8 | `gate` printed no summary: `UnicodeDecodeError: 'charmap' … 0x9d` in `run_tiers.py` | The child writes its log in its stdio encoding (UTF-8 under `PYTHONIOENCODING=utf-8`, set by Claude Code and many IDE / CI shells); the parent read it with `open(log)` in cp1252 | `test_run_tiers.TestLogEncoding` (a child failing with `— ” → ×`: round-trips with an ASCII parent; a cp1252 child does not crash the runner). Fix: children get `PYTHONIOENCODING=utf-8`; logs are read with `encoding="utf-8", errors="replace"`; the script's stdout uses `errors="backslashreplace"` |
| WP9 | `test_guia_thumbs_render` (4) failed: "animated thumbnail needs Pillow" | Pillow was only in the `docs` extra; the gate runs the module; the tests asserted instead of skipping | Pillow in the `test` extra; the 4 animated tests `skipUnless(PIL)` with the install command, before the ~50 s render starts |
| WP10 | `gate` crashed before any test ran: `PermissionError` opening `.scena_test_runs/gate/<job>.log` | The copied tree's old logs (and `timings.json`) were Hidden; Windows refuses `open(path, "w")` on an existing Hidden file | `test_run_tiers.TestOpenFresh` (missing, read-only, Hidden on Windows). Fix: `run_tiers.open_fresh` deletes the old file first (clearing read-only), for logs and `timings.json` |
| WP11 | `TestFleetBounce` (today in `test_tutorial_steps`): `'examples/naves.py' not found in ['examples\\naves.py', …]` | A `relpath` label compared with a `/` literal | Rule (`tests/README.txt`, Paths): a relpath label is compared in `/` form. Fix: `.replace(os.sep, "/")` |
| WP12 | `test_editor_launch` `test_linux_desktop_entry`: `S_IXUSR` not set | Windows has no exec bit (`st_mode` follows the extension) | `test_platform_portability.TestExecBitIsPosixOnly`. Fix: assert only when `os.name != "nt"` |
| WP13 | `test_collision_queries.TestCollisionQueries.test_circle_wedge_matches_query_sector`: `DeadlineExceeded` 262 ms > 200 ms | The module never imported `hypothesis_support`: Hypothesis defaults (200 ms deadline, no DB, profile ignored); `test_shapes`, `test_text_input` too | `test_run_tiers.TestHypothesisProfileGuard` |
| WP14 | `test_sprite.TestSpriteBlitBlendAndAlpha.test_alpha_composes_with_fade_out`: one channel 9 off (limit 8) | Fade progress set from one clock read; `draw()` read the clock again later, under load | `test_platform_portability.TestTransientClockIsPinned` (a test module that writes `_tx_state.<kind>.t0` calls `set_now_fn`; the other sites, in `test_transients` and `test_text`, already pinned it). Fix: clock pinned with `transients.set_now_fn`; the duplicated draw block was dropped |
| WP15 | `test_scripts_run`: `scripts/smoke/hitbox.py` timed out at 120 s (7.8 s alone) | The module's own 8-worker pool on top of the tier's 10 workers, on a loaded run | `TIMEOUT` 300 s (a hang detector, not a budget). Not chosen: fewer inner workers inside a tier, which would make the module the slowest `quick` job on the Mac |
| WP16 | Latent: 11 `subprocess.run(..., text=True)` sites in `tests/` (plus `make_guia_thumbs.py`, which `test_guia_thumbs_render` runs) and `scena_editor/dialogs._tk` (shipped: the file dialog's child prints the chosen path) | `text=True` decodes with the locale (cp1252 on Windows); a Python child under `PYTHONIOENCODING=utf-8` (set by `run_tiers` and inherited) writes UTF-8: garbled failure text, or `UnicodeDecodeError` on a byte cp1252 lacks (`Á` is `C3 81`); `_tk` would garble or crash on a path outside cp1252 | `test_platform_portability.TestSubprocessTextNamesItsEncoding` (AST over `scena/`, `scena_editor/`, `tests/`: a text-mode call names `encoding=` or `errors=`); `test_editor_dialogs` `test_tk_child_output_is_utf8_on_every_os`. Fix: Python children get `encoding="utf-8", errors="replace"` and `PYTHONIOENCODING=utf-8`; external tools (`powershell`, `osascript`, `lipo`) name their decoding. `scripts/bench` not swept (not guarded, as in WP5) |
| WP17 | Latent: `iter_files` order differed by OS; `scena_editor/tests` scans and `scripts/smoke/audio.py` were outside the AppleDouble guard; `test_uiwidget.test_missing_glyph_falls_back` ran only on the Mac | `sorted()` on host paths: `"\\"` sorts after letters, `"/"` before (`sub/x.py` vs `subA.py`). The scan guard read `tests/*.py` only. The glyph test needed Helvetica | `TestIterFiles.test_order_does_not_depend_on_the_separator` (`source_support.path_key`, checked with `"\\"` on any host); `TestSourceScansUseTheHelper` now recursive over `tests/` and `scena_editor/tests/`. Fix: sort key in `/` form; editor scans use `iter_files`; the smoke skips `._*`; the glyph test uses `font_support.system_font_file()` and the first candidate character that font lacks |
| WP18 | `test_regular_polygon_perf.TestPerfSmoke.test_rotate_by_cost_flat_in_n`: `n=6=1.2us n=200=6.6us ratio=5.62x` (limit 4×) in `quick`; always passed alone; the failing runs did not touch `rotate_by` | A ratio, but of two single samples taken one after the other (all n=6 calls, then all n=200 calls, ~4 ms each): load that rose between them, or one preemption inside one of them, moved the ratio. Under 14 busy processes on 10 CPUs the old test read 0.36×–3.65× over 20 runs | Both sizes timed in 25 interleaved blocks of 320 calls (the order alternates), each side keeps its best block, GC off while timing: 0.99×–1.01× under the same load. Limit unchanged (4×). Mutation-checked: a per-vertex `__dict__` read injected into `rotate_by` reads ~7.8× and fails; a bare `for v in vertices: pass` (~1.5×) is below the limit, as it was before |
| WP19 | `test_sheet_patterns.TestMatching.test_absolute_pattern_is_that_folder_only`: `'C:\…\elsewhere\Run__000.png' != 'C:\…\elsewhere/Run__000.png'` | The helper `png(rel)` built the expected path as `os.path.join(root, rel)` with `rel` in `/` form: mixed separators on Windows. `_pattern_matches` returns `abspath` forms (correct). The other tests compared basenames and passed. Five more helpers (`program_support.program_path`, `test_level`, `test_sprite`, `test_sprite_button`, `test_tutorials`) joined a parameter the same way, latent | `test_platform_portability.TestJoinedPathsUseOneSeparator` (AST over `tests/` and `scena_editor/tests/`: an `os.path.join` taking a parameter of the enclosing function, or a literal holding `/`, is wrapped in `normpath` / `abspath` / `realpath` or splits on `/`; `ntpath` shows the Windows spelling on any host). Fix: the six helpers wrap the join in `os.path.normpath` |

### MR — media migration (2026-10-02)

`scripts/examples/` moved to the top-level `examples/`; the gitignored root `media/` and `scripts/examples/media/` were replaced by licensed packs in `examples/media/`; `scripts/smoke/sounds/` (license unknown) was removed. Nothing failed.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| MR1 | ~170 media paths pointed at files that no longer existed (examples, smoke, bench, tutorial, Guia thumbs) | A missing file only warns; no test read the paths | `test_media_refs.TestMediaRefs` |
| MR2 | 30+ media-backed tests (`test_sprite`, `test_atlas`, `test_svg`, `test_level*`, `test_audio`) would have skipped | `if not os.path.isfile(...): self.skipTest(...)` on files that are now tracked | `tests/media_support.media()` asserts; the skips are gone |
| MR3 | `test_scripts_run`, the stamp lint and the AppleDouble count no longer covered the examples | They listed `scripts/examples` / `scripts/` by path | `test_scripts_run` scans `examples/`; `test_stamps` and `run_tiers.SOURCE_DIRS` include it |
| MR4 | A forwarding-stub example (it ran a bench script) raised `FileNotFoundError` | It ran `../bench/perf_resolve_balls.py` relative to its own folder; one level up is now the repo root | `test_scripts_run` (it runs `examples/` again, MR3) |

### DL — docs pointing at the private workbench (2026-10-06)

The code is about to be published without `proposals/` and `archive/` (bench notes included; [README — Private folders](README.md#private-folders)). Nothing failed: no test read link targets.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| DL1 | ~45 citations of private files in 14 design docs, 6 test docstrings, one code comment and 5 bench pages; 8 already dead (a proposal cited where it was before it moved to the archive, files that never existed) | Docs linked deliberation instead of carrying the reason; `test_doc_citations` checked test names only | `test_doc_links.TestDocLinks` (all citations removed 2026-10-06; a test that read an archived runbook through `os.path.join` and always skipped (the runbook-copy check in `tests/test_win_bench.py`), was deleted) |

### GN — group-name typo guard (2026-10-02)

Found running `examples/naves.py` after the media migration. Sibling of SC4, which had fixed only the `until_empty` path.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| GN1 | `group["tiros_inimigos"]` warned "No group 'tiros_inimigos'. Did you mean 'inimigos'?" every run, before the first enemy shot; the script names that group in `@collide` and `@leave_playfield` | The near-miss guard treated "not in `group_map`" (no live member) as unknown, and rules registered names nowhere the guard read | `test_group_name_guard.TestNotFilledYet`: the `@collide` family, `collide_with`, `resolve`, `@leave_playfield` declare their names (`registry.declare_group_names`) |
| GN2 | Clearing a fleet made any `group["inimigos"]` read warn "Did you mean 'tiros_inimigos'?" while a shot was alive | The registry drops a bucket with its last member; SC4 had routed only `until_empty` around it | `test_group_name_guard.TestEmptied`: a name that ever had a member (`_group_gen`) is known |

### TU — tutorial endpoints (2026-10-02)

Found in the post-migration tutorial review. Rule: every tutorial step runs for 10 s of game time with no warning, and the last step of each tutorial is a file in `examples/` (its code plus a docstring).

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| TU1 | Tutorial 05's last step (`A nave explode`) raised `DestroyedError` the first time an enemy shot hit: `@collide` destroyed the ship and `update` kept calling `nave.confine(...)` | `test_tutorials` ran each step as three `update(dt)` calls from the repo root: no collision pass, so no shot ever landed (and the draw of `choice()` decided whether one would) | The run test of `test_tutorials` (since 2026-10-10 `test_tutorial_steps`, one class per page): every step and `try` runs through `tests/script_harness.py --strict` for 600 frames of the real frame body (collisions, processes); the harness seeds `random` (0), so the crash reproduces. Verified to fail on the pre-fix HTML. Fix: `if nave:` around movement and shots |
| TU2 | A tutorial step could print a warning (missing media, near-miss group name) and pass | The child run ignored warnings and resolved media from the repo root, where the reader's `media/` paths do not exist | `script_harness.py --strict` turns any warning into exit 3; steps run from a temporary folder with `media/` → `examples/media` |
| TU3 | The examples named as tutorial endpoints had drifted from the last step: `pegar_estrelas.py` (glow, yoyo), `naves.py` (`Sheet`, shield), `cadeia_de_bolas.py` (`GearShell`, `rate`), `barras_girando.py` (`Palette`); tutorials 01 and 04's pause menu had no file at all | Nothing compared them; the README allowed the example to be "more than the tutorial" | `test_tutorials.TestTutorialEndsInAnExample`: the last step must declare `example:`; the file minus its docstring equals the step. Variants moved out of `examples/` (or into a `try` box) |
| TU4 | The tutorial media check flagged `Sheet` frame names as missing files (tutorials from 03 on may use `Sheet`) | It matched every quoted `*.png` in the HTML | `test_media_refs.tutorial_paths` reads each step as a script (`literal_paths`: `frame=` is not a path) |
| TU5 | Tutorial 05's fleet (`Vai e volta` onward, `naves.py`, and a shield variant) could stick at an edge, flipping direction every frame (1091 turns in 20 s) | The bounce flipped the sign (`st.velocidade = -st.velocidade`) whenever a ship was past 40 / 960. After one frame shorter than the overshoot, the edge ship was still past the edge, so the next frame flipped back outward, and from then on it oscillated there at a normal `dt` | `TestFleetBounce` (1 ms hitch after the first turn). Verified to fail on the pre-fix code. Fix: say the side, `st.velocidade = -80` past 960 and `80` below 40; repeating it is harmless. Also fixed in a learner's game outside `examples/` (not under the guard: its `update` stops once the ship dies) |
| TU6 | A tutorial box meant to replace lines (11, "no lugar das três linhas da folha": `Sheet("plane/Fly*.png", fps=12)`) passed the test and broke in place: its one clip is named `"default"`, and the step's `play("voando")` raised | `test_tutorials` appends every box to the end of its step, where the step's own lines have already run; a replacement is never tried where it goes | A box declares the lines it replaces (`replaces: [...]`, anchors like `focus`); `run_all` runs it in place (`in_place`), method-body boxes included. `TestTryInPlace` (the run half now `test_tutorial_steps.TestRunCatches`) shows the bad box passing appended and failing in place. Fix: `name="voando"` |

### SB — SpriteButton groundwork (2026-10-02)

Found while designing `SpriteButton` (a Sprite subclass with a press state).

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| SB1 | A press outlived its shape: a modal Menu opened mid-press left a stale `_pressed_shape` that kept hover after the menu closed and took the next release (a click on a shape the pointer merely crossed; the script's click eaten). Hiding, parking or destroying the held shape left the press until the next pointer event | `_pressed_shape` was written in three places and only `_press_lost` (dead, or undraggable mid-drag) checked it, lazily, on the next move / release | `test_script_callbacks.TestModalDropsShapePress` (canary-verified), `test_shape_interaction.TestPointerPressed`. Fix: `_set_pressed` is the only writer; `forget_destroyed`, `forget_pointer_target` (from `_sync_interactive_registry`) and `push_modal` drop it eagerly ([Shapes — Press lifecycle](Shapes%20Design.md#press-lifecycle-pointer_pressed)) |
| SB2 | Engine dispatch by `type(obj).__name__` refused every subclass: `class Pad(Rect)` / `class Ball(Circle)` / `class Ship(Sprite)` raised on `.box` and `confine(by="box")`; `Svg` and Sprite subclasses raised on `.hue` and on Sprite-only looks; force-field looks lost their sprite outline; a `Text` subclass skipped the Text refusals | A dozen `== "Sprite"` / `in ("Rect", "Square")` checks across `box`, `confine`, `style`, `recipes`, `stamps`, `visuals`, `filters`, `transients`, `canvas`, `track` | `test_kind_dispatch` (every verb with author and Scena subclasses) plus a static scan of `scena/` that fails on a new `type(x).__name__` comparison unless marked `# exact-type: <reason>`. Fix: `entity.scena_kind` (nearest Scena class in the MRO) and `entity.is_sprite_family` |

### CT — continuous detection (2026-10-05)

Found with a test game whose shots were sped up to 5000 DU/s to test an extreme case. Fixed by swept detection ([Collision Design — Swept detection](Collision%20Design.md#swept-detection-fast-bodies)).

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| CT1 | A fast `@collide` shot passed through its target: a 28-tall laser at 83 DU/frame through 40-tall enemies hit ~85 % of them at 60 Hz and under half at 30 Hz. Same game, different hits by machine and FX load | Detection-only pairs were tested at the end-of-frame pose only (the broad phase widened start ∪ end for `resolve()` bodies alone) | `test_collision.TestSweptDetection` (laser tunnel, threshold edge, nearest-first, payload, placement not swept, start overlap, `on_collide`, `resolve_enabled = False`, canary with the gate off); `test_sys_fast_shots` (same hits at 30 / 60 / 120 Hz and 5 / 28 ms, offsets 0 / 65536; fails with the gate off); `test_sys_hyp_collision.TestFastMotionAgainstSweptOracle` (exact swept circle oracle; fails with the gate off) |
| CT2 | A fast body pushed into a thin `resolve()` wall never fired `@collide`, while resolve stopped it correctly | `@collide` reads the pre-resolve pose, which was always past the wall; resolve then parked the body short of it, beyond the skin | `TestSweptDetection.test_fast_body_pushed_into_resolved_wall_fires_collide` (failed before the fix), `test_sys_fast_shots.TestFastBodyIntoResolvedWall` |
| CT3 | A fast sprite's hitbox part (`add_hitbox`) carried no motion, so it could not be swept | `note_collider_motion` marked only the body's collider | `TestSweptDetection.test_fast_sprite_hitbox_part_is_swept`. Fix: the host's delta is added to each part's collider |
| CT4 | An orbiting body (`rotate_by(20, about=pivot)`, r = 200: ~69 DU per frame for a 10-wide body) passed through a target between two poses, and a `resolve()` body orbited through a thin shelf. The same travel as `move_by` was swept | `rotate_by` moved `center` without noting it, so an orbit was placement. The motion/placement split was keyed to the verb's name (`_by` = travel) only for `move_*`; a turn's side effect on the position was never classified | `test_collision.TestOrbitMotion` (every kind notes its anchor chord exactly once — catches an override that notes twice; placement turns and spin note nothing; timed `rotate_by` / `rotate_to`; hitbox parts; resolve shelf; all fail with noting off). Fix: `entity._rotate_as_motion` / `_rotate_as_placement`. Rule: any verb whose side effect moves the pose anchor states whether that move is motion or placement, and has a test that reads `_pending_motion_*` after it |

Lesson for the benches: the uncapped benches (`cpu_mix`, resolve) run at 300–500 FPS, so per-frame travel depends on the machine, and a slower run can cross the fast gate. `last_stats["fast"]` / `["swept"]` say whether it did. A before / after comparison on a shared machine is an interleaved A/B against a pristine copy of the previous tree, not two runs minutes apart (during this change, other sessions' test runs moved single numbers from 10 % up to 3×).

### CS — closed surfaces (2026-10-07)

Found by an audit probe: build every export and global object, write a junk name and a swapped-letter typo of each writable name. About 90 classes stored both. Rule: only Entity (ink) and `st` create names on write ([Scena Design](Scena%20Design.md#entity-ink-vs-st)); everything else is a closed surface (`scena/closed.py`). The class-wide guard is `test_closed_surfaces.TestEveryAuthorObjectIsClosed`: it walks every export, the global objects, every layer kind and reachable public attributes two levels deep; a new class must refuse a junk write or sit in `EXEMPT` with its reason.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| CS1 | Effects stored typos and did nothing: `bloom.itnensity = 2`, `stars.pna_response = 0.5`, `echo.enabeld = False`, `canvas.effects.enabeld`, `Tail().lenght` | Plain classes; `Visual` / `FilterEffect` guarded interned instances only | `TestEveryAuthorObjectIsClosed` (junk, swapped-letter typo, write-back of every writable name). Fix: `ClosedSurface` on PostEffect / BackgroundField / AudioEffect and their stacks; `_interned_setattr` calls `check_closed_write` |
| CS2 | Global objects stored typos: `audio.vloume = 0`, `clock.puased = True`, `canvas.zom = 2`, `ui.scael`, `collision.gravtiy`, `keyp.held.x` | Plain classes / Containers with no `__setattr__` | Same walk. Fix: `ClosedSurface` with `_closed_who` (`"audio"`, `"clock"`, …) |
| CS3 | Values and materials stored typos: `box.widht`, `color.aplha`, `history.lenght`, `sheet.fps2`; snapshot boxes too (`graphic.box`, `canvas.game_view`) | Plain classes; `Box._snapshot` builds through `__new__`, so no constructor wrapper could seal it | Same walk, `TestEngineValueRegressions.test_snapshot_boxes_are_sealed`. Fix: `ClosedSurface`; `closed.seal()` at the end of every `__new__` fast path (`Box._snapshot`, `_sheet_from_image`). Rule: a construction path that skips `__init__` must call `seal()` |
| CS4 | `st.pos.x = 5` (`st.pos` holding a Vec2) stored `x` on the cell: reads returned 5, the payload stayed `Vec2(1, 2)`, links never updated | `Attribute.__getattr__` falls through to the instance `__dict__` before the payload, and the cell had no `__setattr__` | `TestEngineValueRegressions.test_cell_payload_write_raises_with_the_reactive_fix`. Fix: `Attribute._closed_hint` names `st.pos = Vec2(..., st.pos.y)` |
| CS5 | `ship.field_type = 3` corrupted the part's graph edges; `v.parts = …` orphaned the parts of any non-Entity Container | Plain public attributes on `Container` | `TestContainerPlumbing`. Fix: read-only properties over `_parts` / `_field_type`; engine code uses the private names |
| CS6 | Entity ink took `anlge`, `widht`, `aplha`, `lyaer`, `gruop`, `nagle` as new ink | The near-miss guard needed 6+ letters and the same first letter | `TestInkTranspositionGuard`. Fix: a 5+ letter property one adjacent swap away raises (`closed.transposed`) |
| CS7 | (caught in review, before release) A seal keyed on `type(self).__init__ is wrapped` would never have fired on an exported class | `scena/__init__.py` wraps every export's `__init__` again (`install_friendly_constructor`) after the class body ran, so the seal wrapper is never outermost | `TestClosedSubclasses.test_seal_survives_friendly_constructor_wrapper` / `test_seal_survives_any_outer_wrapper`, `TestEveryAuthorObjectIsClosed.test_exported_closed_classes_are_sealed`. Fix: the seal marks the outermost *sealed* call per instance (`__dict__` mark), independent of wrapper order |
| CS8 | (caught in review) The planned write check called `inspect.getattr_static` per sealed public write (~350 ns); a closed `__setattr__` also made every private write pay a Python call (~100 ns): `graphic.box` +29 %, Vec2 arithmetic +60 % in a prototype | A Python `__setattr__` is paid by every write, private ones included | Per-class cached name sets (`closed.class_names`); `Container.__init__` writes its private fields with one `__dict__` update where safe (`state._container_dict_init`, `TestContainerFastInit`); Vec2 closed once its construction made no `__setattr__` call (CS9). Measure a new closed class's hot writes and constructions against the open baseline (interleaved A/B, pristine copy) |
| CS9 | Vec2 stayed open: `v.lenght = 5` stored a dead attribute. Closing it naively cost +60% on arithmetic, then +23% with the `__dict__` init | Each arithmetic result is a new Vec2; after the dict init three Python `__setattr__` calls remained per construction (the `owner` setter with `owner=None`: `owner`, `_owner`, `_name`) | `TestClosedVec2` (`test_construction_makes_no_setattr_call` spies the class `__setattr__` over `temp`, `Vec2(...)`, `a + b`, `a * 2`), `TestContainerFastInit.test_ownerless_skip_leaves_what_the_owner_setter_left`. Fix: the dict path skips the setter for an ownerless object; `_processed_params` and the seal go through `__dict__`. Arithmetic 4–6% faster than open, frames within noise; `v.x = 5` +100 ns |

### PM — program model (2026-10-08)

First program: bouncing balls (walls, a spinning STATIC bar, `resolve(bounce=1)`,
two Sliders bound to `st`, a Start button, wheel zoom). Two spec authors, 67
expectations, 17 scenarios. No engine bug; one SPEC-LOGIC revision; six doc
gaps that **both** authors reported on their own.

| ID | Finding | Verdict / cause | Action |
| --- | --- | --- | --- |
| PM1 | When `Button.on_click` fires; `zoom_by` / `zoom_to` anchor without `about=`; who keeps the wheel (`on_mouse_scroll` order); `.angle` after `rotate_by` (wraps or accumulates); a Slider whose cell is out of range or not an int; when a destroyed object leaves its groups | SPEC-GAP / DOC-SILENT (all six reported by both spec authors) | Guia: on release over the button, release elsewhere cancels; no `about=` = view centre, pan unchanged; the widget under the pointer keeps the wheel (a Slider steps), a shape only while held with `wheel_rotate`; `.angle` accumulates (compare `% 360`); the Slider never rewrites its cell, drag / wheel write in range; destroyed leaves groups at once. Guards: `test_uiwidget` (`test_release_outside_cancels_the_click`, `test_out_of_range_cell_is_not_corrected`, `TestWheelRouting`), `test_canvas.test_zoom_without_about_keeps_pan`, `test_registry_layers.test_destroy_leaves_its_groups_at_once` |
| PM3 | `keyp.once` fired for a press made long before, released, and never read: True on its first read, however late. Found by the harness: a SPACE in one program skipped the next program's title (no act change between them); inside one act the Guia's own `if flag1 and flag2 and keyp.once("SPACE")` fired seconds late | BUG / the Guia says "só no frame do aperto"; unread edges stayed in `_pending_edges` until a reader came (a side effect of the same-poll guarantee). SC1 had dropped them at act changes only — the symptom, not the class | `KeyPressed._expire_edges()` at the end of `_simulate_frame` (after every reader); `_once` needs a pending edge while the keys are held. Guards: `test_keyp.TestOnceIsFrameScoped`, `TestOnceIsFrameScopedInFrames`, and a frame-boundary step in `TestOnceChordProperty` (the whole class: no `once` without the keys going down together **in this frame**) |
| PM2 | Spec A E21 failed: "free balls keep their drawn speed" was checked as "80% of balls", and one pair spawned touching at count = 8 (the engine conserved energy and momentum of that pair exactly) | SPEC-ERROR / SPEC-LOGIC | Check rewritten to its own claim (skip balls within one frame's travel of another). Lesson for spec authors: a statistical threshold standing in for a precise exclusion fails on small counts |
| PM4 | `isinstance(st.n_bolas, int)` was False: `st.n` reads the cell. The Guia said both "`st.score` lê o valor" and "`st.key` Lê o Attribute" | SPEC-GAP / DOC-AMBIG (spec A of `cadeia_de_bolas` trusted the first row) | Guia: `st.score` reads the cell, which does arithmetic like its value; `st.score.value` is the plain value (for `isinstance` / `type` / a copy) |
| PM5 | `.color` under a look read the look's live paint, not the colour the author set: `Halo` (a translucent wash: lightness ±0.2, alpha 0.12), `Rim`, `ElectricField`, and alpha / hue drift on `Line` under ~10 looks; Role D looks (Flame, Swell, Water) read the colour given. Spec b of `cadeia_de_bolas` guessed the colour given | SPEC-GAP / DOC-SILENT. Decision (2026-10-08): `.color` is the **current** colour — what the shape paints now (a breaking alternative, the colour given for every look, was declined) | Guia `.color` row states the rule and the Role D exception; keep your own colour in a variable or `st`. Guard: `test_visuals.TestColorReadsTheCurrentPaint` |
| PM6 | `sprite.height` stayed 40 under `scale_to(1.08)`; spec A of `naves` expected 43.2 | SPEC-GAP / DOC-SILENT (both `naves` authors flagged it) | Guia pose table: `.scale` multiplies drawing and collider; `.width` / `.height` stay the size given; the drawn size is `.box`. Guard: `test_sprite.TestScaleKeepsTheGivenSize` |
| PM7 | A verb on an empty group built a full `Blank()` Shape per call: ~0.3 ms (one-member group: 16 µs), every frame in `group["tiros"].move_by(...)` with no shot alive; the Blank sat in the live roster until GC, so two identical runs differed in roster size | BUG (perf) / found by the `probe_neutral` oracle: a run with probes and one without differed only by GC timing | `registry._empty_group_attr`: a method is a no-op returning `None` (Guia: "não faz nada"; with `time=` the Handle path stays); reads and unknown names keep the Blank path. 1.4 µs. Guard: `test_registry_layers.TestEmptyGroupVerbsBuildNothing` (spy on `Blank.__init__`) |
| PM8 | Timers fired one frame late or on time by float rounding: at 60 FPS `after(0.5)` on frame 31, `every(0.25)` first on 16, `every(0.9)` on 54 (on time). 15 × (1/60) = 0.24999999999999997 | BUG / the class: every "is it due" comparison on summed frame time. Six of twelve spec authors could not predict the frame from the docs | `process.reached(elapsed, target)` (1e-9 relative) in `after` / `every` / tween end / `ready` / `recently` / transient progress. Guia: first `every` call one interval in, `after(0.5)` = frame 30 at 1/60. Guard: `test_process.TestDueOnTheExactFrame` (property over 6 fps × 11 frame counts × 6 mechanisms) |
| PM9 | The Guia's coyote-time example re-applied the jump each frame of the `recently` windows: jump 151 high instead of ~115; its gotcha said re-setting `vel.y = PULO` "dá no mesmo" | SPEC-GAP / DOC-WRONG (both `platformer` authors computed the higher jump) | Guia example consumes the windows (`recently.reset("pulo")`, `recently.reset("no_chao")`); the gotcha now says an action that changes motion does not repeat harmlessly |
| PM10 | Small gaps several authors hit: `e.after(d, fn)` passes the entity to a one-parameter `fn`; another plain key held does not change `keyp("A")`; `game_view` at the start is `(0, 0)`–`(width, height)`; `confine` clamps exactly to the edge; `Color.darker` / `lighter` move HSL lightness | SPEC-GAP / DOC-SILENT | Guia rows. Guards: `test_keyp.test_another_play_key_held_does_not_matter`, `test_color.TestLighterDarkerAreHslLightness` (the rest already pinned) |
| PM11 | `test_collision(a, b)` returned the raw narrow-phase payload: `info.a` / `info.b` were engine Collider objects (a probe for a non-enrolled shape) and the normal / side followed canonical `id()` order, so half the pairs got the other body's normal | BUG / the Guia says a / b are the bodies, normal from a to b. Found writing the `toybox` API-first program | Query goes through `_oriented_info` (as handlers do) and names the body a probe stands for. Guard: `test_collision.TestQueryInfoIsTheAuthorView` (identities, both orders, same as the handler, a piece of a Collider) |
| PM12 | `deadzone(size=st.x)` raised "expected a number … got Attribute"; every other number argument takes a cell (surveyed: `lerp`, `remap`, `chase`, `vec_from_angle`, `chance`, verbs, timers, `ready`, `recently`, constructors) | BUG / found writing `geometry_lab` | `as_payload` on `size` and its pair. Guard: `test_easing.TestDeadzoneTakesCells` |
| PM13 | Two layers made with `below="default"` share a z; equal z draws in creation order (the newer on top), so "below default" twice puts the second *in front* of the first | SPEC-GAP / DOC-SILENT (found writing `runner_story`). The ordering an author would expect is debatable — left as documented behaviour | Guia layers.create row; chain `below=` to stack. Guard: `test_registry_layers.TestEqualZDrawsInCreationOrder` |
| PM14 | The `@=` formula checker located a lambda by its position in the script file **on disk**. Edited and saved while the program runs, the file no longer matched the running code: a formula built afterwards read another lambda's names, or none ("formula has no reactive sources", misleading) | BUG / found by Tier C (rewritten programs ran under the original file name) | `formula_check._node_matches_code` checks the located node against the code object; a stale source counts as none (lambdas link from the code object, exact); errors say the file changed on disk. Guard: `test_formula_functions.TestStaleSourceFile` |
| PM15 | `amp_db(st.level)` raised TypeError: `x` was type-checked by hand while `floor` went through `number()` | BUG / found by `test_cells_as_numbers` on its first run | `as_payload(x)`. Guard: the cells guard |
| PM16 | A method that only some member kinds have (`play`, `showing`, `add_hitbox`, `flash_text`, `focus`, `at` …), called on an **empty** group, raised AttributeError: the stand-in for "no member" is a Shape. `group["inimigos"].play("andar")` crashed once the last enemy died | BUG / found by `test_noop_cost` (the Guia: the method does nothing on an empty group) | `_empty_group_attr` treats any public method of any Entity kind as a no-op; a typo still raises. Guard: `test_noop_cost.TestEmptyGroupVerbsBuildNothing` |
| PM17 | `Handle.velocity` keeps the last frame's value after the motion ends (by design: `on_done` reads the arrival speed); the Guia said only "neste frame" | SPEC-GAP / DOC-SILENT (found by `test_sys_frame_contracts`) | Guia `Handle.velocity` row |
| PM18 | `canvas.background = canvas.background` raised TypeError: the read is the live stack, a write expected a material for the base. Found writing `test_noop_cost` (every world setting written back) | BUG / read and write of one name did not round-trip | Writing the stack itself keeps it; the Guia says to keep `.base` to restore later. Guards: `test_background.TestBackgroundRoundTrip`, `test_noop_cost` (no special case) |

### AC — game system tests (2026-10-10)

Found writing and running the three games of [Game system tests](#game-system-tests).
Each fixed one has its regression test in the owning module; the games keep
the pattern under load.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| AC1 | Author classes (and with them the program's whole namespace: every module global, every shape) outlived the program: a census after `close()` saw the game alive | A program defines `class Nave(Sprite)` and builds one; after the run, `gc.get_referrers(Nave)` names a module dict | Class-keyed module caches (`entity._DEAD_ROUTES`, `_SCENA_KIND_CACHE`, `_PROPERTY_LINK_BY_CLASS`, `collision._extra_slots_for_cls`) held the class strongly | Program tests define few classes, and their censuses count actors, not classes | The tables are per-class attributes set once in `Entity.__init_subclass__` (`_cache_class_tables`); dies with the class. Guard: `test_author_class_lifetime` (author subclasses of Circle, Rect, Sprite and Entity through every caching path, collected after use). Perf: same hot-path cost (a class attribute read replaces a dict lookup) |
| AC3 | `list(canvas.effects)` / `len(canvas.effects)` showed an internal `HitFeedback` after any `shake` / `flash` / `*_at`, and it came back on an act restore; the Guia says impacts never enter the stack | `canvas.shake(5); list(canvas.effects)` → `[HitFeedback]` | `PostFxStack.__iter__` / `__len__` walked the internal list that also holds the impacts' post | Tests read the stack only through `_effects` or before any impact | The author views skip `_hit`. Guard: `test_postfx.TestPostFxStack.test_impacts_never_join_the_authors_stack` |
| AC6 | `on_collide` / `on_collide_stay` / `on_collide_exit` written as a **class method** got `other` = itself and `info` = the other body, on every family | `class Nave(Sprite): def on_collide(self, other, info): ...` → `other is self` | The bound method was stored as the `fn(me, other, info)` property callback and called by arity: `self` was passed twice | Existing tests defined such methods but never checked the arguments | `_install_subclass_hooks` wraps the collide hooks in `collision._pair_method_adapter`. Guard: `test_collision.TestOnCollideMethodArguments` (Shape, Sprite, SpatialFx × the three hooks) |
| AC7 | The frozen-mode warning fired on the Guia's own pattern: a director awaiting `until_empty` for a long wave, then `fade_out(on_done=change_act)`, warned on the first idle frame | A mode that waits 4 s, then has nothing pending | The warning measured the mode's age; Actors Design says "nothing pending past `FROZEN_MODE_S`" | `test_frozen_mode_warns_once` fired the warning; no test ran the documented pattern next to it | When an owner's async body or last owned handle ends in a mode, the scheduler writes the mode time on the owner (`_mode_idle_from`, a slot next to `_frozen_warned`; reset on mode entry); idle counts from there, or from the mode's start; the cheap exit for young modes stays. Cost: ~0.1 µs per such end (interleaved A/B; the rest of the timer cycle unchanged). A first version started the idle clock only once the mode was 2 s old (a mode idle from birth warned at 4 s), and a second held the mode, a bound method of an Act, in a weak-keyed record (a dead act stayed alive): the quick tier caught both Guard: `test_process.TestFrozenModeWarning`. [Actors Design](Actors%20Design.md) sentence updated |
| AC8 | `for g in gens: g["saida"] @= (lambda g=g: g.ganho * 2)` raised `CircularReferenceError`; `lambda g=h:` worked | as written | The formula's source extractor visited the lambda's default expressions (evaluated once, at creation) as reads: `g` resolved to the shape, a whole-object source, so the shape's own field "read itself" | Formula tests used closures, never the loop-variable default idiom | Sources come from the body only (lambda and def). Guard: `test_formula_functions.TestDefaultArgIsNotARead` |
| AC9 | `group["coluna0"] @= lambda: ...` (the Guia's formula-group declaration) warned "No group 'coluna0'. Did you mean 'col0'?" | a group `col0` exists, then the declaration | Python evaluates `group[name]` before `@=`; the near-miss guard saw a read of an unknown name | Group formula tests used names far from any existing group | The warning branch reads the caller's bytecode for a subscript `@=` store (no hot-path cost). Guard: `test_group_name_guard.TestDeclaringAFormulaIsNotATypo` |
| AC11 | Destroying an Entity whose own field reads the Entity (the Guia's `hero["grounded"] @= lambda: "bottom" in hero.touching_sides`) warned "Attribute … was unlinked because a formula source was removed", every time | as written, then `hero.destroy()` | `state._clean_up` counted the Entity's own scalar anchors as external dependents | Lifecycle tests linked fields to other objects | No warning for an anchor whose parent is in the dying subtree (or already gone). Guard: `test_graph_lifecycle.TestOwnFieldLinksDieQuietly` |
| AC12 | Unlinking an ink field that another formula reads (`e["v"].unlink()` with `t @= lambda: e.v * 10`) unlinked the reader ("a formula source was removed") and froze it at a stale value | the sequence `test_hyp_api.ReactiveLinksMachine` found: link `e["v"]`, link `t` to `e.v`, unlink `e["v"]`, write `e.v` → `t` stale; write `t` → accepted | `_unlink_field` dropped the field's scalar anchor, which is also the node readers depend on | Found by the existing state machine during this work (its example fails on the pre-change HEAD too); no unit test unlinked a field that something reads | `_unlink_field` keeps an anchor that has external formula dependents (unlinks it only). Guard: `test_fieldref.TestUnlinkKeepsReaders` (ink and slot fields; an unread field still drops its anchor) |
| AC2 | `class Energia(Orb, radius=16)` raised Python's own "takes no keyword arguments": SpatialFx subclasses had no class keywords, while Shape and Sprite do; and an author `Fire` subclass ignored `style=` silently | as written | `SpatialFx.__init_subclass__` passed every keyword up to `object` | Class keywords were tested per family where they existed; nothing asked every subclassable family the same question | Decided (2026-10-10): accept them like shapes, for consistency. `_class_defaults` (shared with Text: `scena/class_defaults.py`) + a wrapper on each kind's `__init__`; placement / unknown / bad values / `style` refused on the class line; a Fire subclass refuses another style. Guard: `test_spatial_fx.TestClassKeywords`, and the family-parity guard `test_subclass_parity` |
| AC5 | A loose `play_sound(name="musica")` in an act's `setup` and another loose one in the act's mode are two slots: both tracks play. The same holds for `after` / `every` / `tween` | Armada's music | A slot is keyed by its place: the owner of the call, or for a loose call the actor whose mode body runs, else the game / act. The Guia said "solto no mesmo lugar" without saying what a place is | — | Decided (2026-10-10): documented, not changed (authors often want separate sounds; only a soundtrack wants one slot per act, and the engine cannot tell). Guia: vocabulário "slot" and the `play_sound` section (a soundtrack: `self.play_sound(…, name=)` in the act). Pinned: `test_act.TestNameSlotsAreByPlace` |
| AC10 | A shape both a body of its own and a piece of `Collider([torso, head])`: the boss collided with its own torso (and would push it in a `resolve`), and `raycast` / `query_point` answered by statement order | a piece made `collidable`, or a rule naming its group, inside a multi-piece Collider | Nothing kept a body from pairing with its pieces' own bodies; queries walked registration order with a strict nearest test | Collider tests used pieces that were never bodies | Decided (2026-10-10): two boundaries, made coherent (the weak-point pattern stays). The broad phase skips body / own-piece pairs (`_multi_bodies`, `kin`); queries name multi-piece bodies first and a ray tie goes to them; `query_shape(piece)` skips its own body. An `ANYTHING` rule seeing both is documented. Guard: `test_collision.TestPieceThatIsAlsoABody` (both statement orders) |
| AC13 | A second `tween(st["escudo"], 0, time=3, name="escudo")` while the first ran warned "tween/move_along on the same property replaces a previous in-flight tween"; the Guia says a tween in the same `name=` slot replaces the old one | Armada's random pilots (gate): two shield pickups within 3 s | The same-property preempt ran before the name slot and warned for a replacement the author asked for | Driver-composition tests fired the warning; none refreshed a named slot | `_preempt_tween_keys(slot=)` cancels a handle in the new call's own slot quietly. Guard: `test_process.TestNamedTweenSlotReplacesQuietly` (cell, field; unnamed and other slots still warn) |
| AC14 | An own custom field cannot read its object's size fields or computed points (`r["d"] @= lambda: r.width`, `c.radius`, `r.top_left`, a Polygon's `center`): `CircularReferenceError` saying the field "would read the Rect, which already reads d", a cycle the author never wrote. Fails on the earlier code too | `test_subclass_parity` (an own field reading a part on every family), then a survey | A scalar-slot read names the whole object as the source; a Derivate part depends on the root, and the root on every child, the new field included | Own-field formulas in tests read ink fields or placement points | Decided (2026-10-10): a documented limitation. `_own_size_read_message` names it and the idiom (a class `@property`, or `update(dt)`); a real cycle keeps the generic message. Guia: reactive sources. Guards: `test_fieldref.TestOwnSizeReadIsAKnownLimit`; `test_subclass_parity.KNOWN_SELF_READ` (fails if it ever starts working) |
| AC15 | Class keywords across families: `class Hud(Text, group="hud")` (and the six widgets, `Entity`, `Endless`) raised Python's "takes no keyword arguments"; `class Rota(Track, color="gold", group="rotas")` was accepted and both were dropped | `test_subclass_parity` on its first run | Only Shape, Sprite (and now SpatialFx) consume class keywords; `Entity.__init_subclass__` passed the rest to `object`. `Track.__init__` never read `_shape_defaults` | Each family's tests asked about its own way | `Entity._refuse_class_keywords`: an author error naming the fix ("pass them when you make one"), passing through to an author mixin's `__init_subclass__`; `Track.__init__` applies `color` / `visual` / `group` defaults. Then decided (2026-10-10): Text takes class keywords (the look), through `scena/class_defaults.py` shared with SpatialFx; the widgets, `Entity` and `Endless` keep the error. Guards: `test_subclass_parity`, `test_text.TestClassKeywords` |
| AC16 | `anchor.draggable = False` / `handle = False` were accepted and ignored (documented only in a docstring); a link on any Anchor field was refused with "set draggable = False first", which an Anchor cannot do | `test_subclass_parity` (an own-field link on every family) | The Anchor overrode the setters as no-ops; the generic driver-conflict message assumed a switchable drag | — | Decided (2026-10-10): raise, naming `Point(x, y, visible=True)`; the Anchor's own link refusal says it takes no links. Engine writes that follow a drag callback go through `_draggable_from_callbacks` (an Anchor keeps its handle). Guard: `test_shape_interaction.TestAnchorInteraction.test_always_draggable_on_top` |
| HV1 | Harness vacuity: every `ProgramRun` draw painted a surface nobody read (a program's `init()` rebuilt the canvas), so `cull_pixels` compared two blank frames for every program | `run.step(1, draw=True)` then read `run.world.surface` → one flat colour | The framework's drawing canvas was re-created by `init()`; the run kept reading the world's | The oracle compared two images and never asked whether either showed anything | `ProgramRun._wire_surface()` before each draw; `cull_pixels` refuses a flat frame. Guard: `test_program_support.TestDrawReachesThePixels` |
| AC4 | The Guia's `ready` row promised "at most once per interval"; the engine carries the overshoot (Scena Design, "Clocks"), so two calls can be closer than the interval when it is not a whole number of frames (`clock.scale = 0.8`: 0.1467 s apart for 0.15) | Armada's cadence model under `clock.scale` | Engine right by design; the sentence over-promised | — | Guia `ready` row: exact on average, the leftover carried, so two `True` can come a little closer than the interval |

Two harness notes from the same work: a Tier C run copies data files next to
the program (a level `.json`) into its temporary folder; a value `Box` (read
through `Grid.cell_at`) can still be alive at the census by GC timing, so
`ProgramRun.close()` discounts Box values in the graph counters as it already
did in `registry.live`.

### Open (found, not yet fixed)

| Found in | Issue | Planned |
| --- | --- | --- |
| Geometry campaign GX1–GX17 | Found by the campaign's harnesses ([GX](#gx--geometry-campaign-2026-10-08)) | Campaign phase 7 |

### HD — holders (interaction campaign, class 2; 2026-10-09)

Found by `tests/test_sys_holders.py` (`scan`: every engine path to a destroyed
subject). All strong references to a destroyed object that the census and
`zombies()` never looked at. Fixed by class: one `_prune_dead_side` for every
pair list; one teardown hook for a menu.

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| HD1 | A group-operator pair side (`group["a"] | group["b"]`) kept a destroyed member in every pair list (`@collide`, `resolve`) for good | `@collide(group["a"] | group["b"], "rock")`; `a.destroy()` → `_pair_handlers[i][0]._snapshot` still holds `a` | `GroupOperator` copies its members at the call (`_snapshot`); `drop_pair_handlers_for` compared sides by identity and never looked inside one | `test_collision.TestDestroyedSidesLeaveEverySnapshotSide`; `test_sys_holders` gone enders. Fix: `CollisionSystem._prune_dead_side` drops the identity out of every snapshot side it walks |
| HD2 | The `resolve` pairs remembered at the seal kept a destroyed game-level side forever | `resolve(player, wall)`; `run(Titulo)`; `player.destroy()` → `ActManager._game_resolve_pairs` holds `player` | The act manager copied `_resolve_pairs` at the seal and only skipped dead sides at the restore; nothing pruned the copy | `test_act.TestDestroyedSidesLeaveTheActPairLists.test_sealed_resolve_pair_forgets_a_destroyed_game_side`. Fix: the collision system owns the sealed copy (`seal_resolve_pairs` / `restore_sealed_resolve_pairs`) and prunes it with the other lists |
| HD3 | An act-level object-literal pair handler kept a destroyed side until the act change | inside an act: `@collide(a, rock)`; `a.destroy()` → `_act_pair_handlers` holds `a` | `drop_pair_handlers_for` pruned `_pair_handlers` and `_resolve_pairs` only | `…test_act_pair_handler_forgets_a_destroyed_side_before_the_change`. Fix: the same prune on `_act_pair_handlers` |
| HD4 | `WidgetManager.last_click` kept a destroyed widget (a new widget at the spot could read as a double click) | click a Button; `destroy()` → `wm.last_click.widget` is the dead Button | `remove_widget` cleared focus, press and hover, not the double-click memory | `test_uiwidget.TestDestroyedWidgetLeavesTheLastClick`. Fix: `remove_widget` clears it |
| HD5 | An act change (and every `registry.destroy` path: a layer drain, a group destroy) left a destroyed modal Menu open: the manager kept it, the modal mask stayed, the clock pause it set stayed, `await menu` hung, and the next act's `TextInput.focus()` raised "A modal Menu is open" | `Menu(..., pause=True)` in act A; `change_act(B)`; `TextInput(...).focus()` | The close logic lived in a `Menu.destroy` override; `ActManager._destroy_one` and `_drain_layer` call `registry.destroy(obj)` directly | `test_act…test_a_modal_menu_open_at_the_change_closes_with_its_act`, `test_menu.TestRegistryDestroySettlesTheMenu`. Fix: `Menu._settle_on_remove`, a teardown hook `WidgetManager.remove_widget` runs on every path (`destroy()` calls it too) |

### RX — reactive sources across subsystems (interaction campaign, class 8; 2026-10-09)

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| RX1 | A formula that read only `canvas.game_view` (or `layer.view`, or `graphic.box`) never re-evaluated: `c["center"] @= lambda: canvas.game_view.center` stayed where the camera was when linked; the no-sources guard did not fire | `c["center"] @= lambda: canvas.game_view.center`; `canvas.zoom_to(2)` → `c.center` unchanged | The dependency walk took the last Container in the chain, which was the measured Box (`Box._from_aabb`, a fresh value off the graph: D11), so the guard was satisfied by a throwaway and the formula depended on an object nothing ever updated; each pull also joined that Box into the graph | `test_canvas.TestCanvasIsAFormulaSource` (every camera move, a layer's scroll, `ui_view`, `graphic.box`, graph node count flat); `test_reactive_cross_matrix` (every sink from `canvas.game_view`). Fix (user decision 2026-10-09): `canvas` is a `Container` (like `mouse`) notified by `_sync_camera` and the scroll advance; `state._is_durable_source` keeps a deferred tree out of the chain's sources. Cost: an unlinked canvas returns after two attribute reads (A/B 2.12 vs 2.11 µs per `pan_to`) |

### GR — graphics review (2026-10-08)

A review of Shape, Sprite, Graphic and Entity confirmed about 100 bugs from 8
root causes: write gate, check-then-write, lifecycle state, construction
wrappers, shared materials and caches, cold readers, copy contract, and
route-table refusals. Each finding had a repro, but the suite had missed
them all, so the guards were written before any fix (batch 0). Each guard
enumerates its class from the source of truth, uses an oracle with no model
of its own, and fails on HEAD. Today's failures are listed shrink-only in
`tests/graphics_known.py` (and `geometry_known.py` for C1–C8), each tagged
with its finding and the batch that removes it.

| Guard | Class | Oracle |
| --- | --- | --- |
| `test_geometry_contract.TestKindsCoverEveryModel` | sweeps miss models (relational Line models and Ellipse FROM_RECT were outside KINDS) | every model enum value is built by KINDS or listed with a reason |
| `test_diff_link_write.TestLinkWriteGate` | R1 write gate, under- and over-strict | an unlinked twin: the parts its verb changes are the parts the verb writes |
| `test_refusal_atomic` | R2 half-applied refusals; reads that change by themselves | every public read and the registry census, before and after a dead / junk / link refusal |
| `test_construct_failure` | R4 construction (rollback, mixin `__init__`) | census and zombies before and after; the actor's timer and update never run |
| `test_material_isolation` | R5 shared mutable paint | each relative's paint reads and pixels |
| `test_cache_keys` | R5 caches keyed on less than their inputs | a warm hit equals a cold bake, for each `AtlasFrame` field |
| `test_diff_pose.TestEngineReadersStayCold` (+ hit test, `is_collapsed`, KINDS); `test_write_path_guards.TestEngineReadersReadDefiningInputs` | R6 cold readers | the shape stays on the fast path; no public Derivate read in a hit test |
| `test_geometry_contract.sweep_c7` (`clone`, `<<`, `absorb`, then verbs) | R7 copies | source and copy run the same verbs and read alike |
| `test_route_table` | R8 writes to methods, setter-less properties, foreign geometry words (every field slot of any KINDS kind, minus a reasoned `GENERIC` list; it first enumerated the engine's own `_SIZE_WORDS`, the fix's list, and missed `circle.top_left = …`) | a Scena error with a hint, the instance unchanged |
| `test_value_validation` | the Numbers rule on every value door: setters (properties and slots, classified by the value they read), points through verbs (`move_to`, `about=`), constructor and method flags (by bool default, a `bool` annotation, or a keyword that names a bool property) | an author error, never Python's own (`hypothesis_support._LEAK_PATTERNS` gained `unhashable type`, `has no len()`, `int too large`, `codec can't decode`, `[<>]=? not supported`) |
| `test_sprite.TestClipOnTheExactFrame`; `test_write_path_guards.TestFrameCountsGoThroughReached` | PM8 class: the clip playhead | the clip frame due on a whole game frame shows on it; no `int(t * fps)` |
| `test_draw_doors` | plain blit vs full draw; knobs a path ignores | the same pixels on both paths; every knob changes the picture |

Members the guards found beyond the review (all fixed or triaged by batch 10):

| ID | Bug | Root cause | Why earlier tests missed it | Guard |
| --- | --- | --- | --- | --- |
| GR1 | A PARALLEL_DIST Line's `move_by` / `move_to` moved it the wrong distance | **documented design** (triaged in batch 8): the move's normal component becomes `dist`, the along-track part is dropped (`test_shapes.TestLineParallelDist.test_move_by_adjusts_dist`) | relational models were not in KINDS | the sweeps skip it with its reason (`geometry_support.CONTRACT_EXEMPT`) |
| GR2 | The DerivedAttributeError on a tangent-angle Line / FROM_RECT Ellipse suggests `move_to(...)`, which the linked input refuses | the hint does not know the model is relational | same | `test_derivate_readonly` (fixed, batch 9b: `KNOWN_BAD_HINT` empty) |
| GR3 | A destroyed focal-points Ellipse's `box` raises twice, then returns a 0 × 0 box | `box.region_frame` read the public Derivates `width` / `height`: each dead read built one more part before raising | no test read a dead actor three times | `test_refusal_atomic.test_reads_are_stable` (fixed, batch 9b) |
| GR4 | `no_drag()` / `no_handles()` on a destroyed Point repaint it | no dead check on those verbs | P6 checks registrations, not the actor's own state | `test_refusal_atomic` dead source (fixed, batch 9a) |
| GR5 | A free `Track.line(p1=, p2=)` starts on the slow pose path | **not a bug** (triaged in batch 6): a control-point Track keeps its centroid as a live Derivate so `center` never lags a move (G11) | the reader matrix had a hand list of models | `test_diff_pose.START_SLOW` (reason recorded) |
| GR6 | SpriteButton state art truncates summed time (`int(t * fps)`), like PB3 | PM8 rule not applied | same as PB3 | `TestFrameCountsGoThroughReached` (batch 8) |
| GR7 | `frame.rotated` is missing from the auto-hitbox, silhouette and union cache keys | key built by hand from some frame fields | no test varied a frame field against a warm cache | `test_cache_keys` (batch 6) |
| GR8 | An `@collide` group declared while an actor was parked never enrolled it on resume | resume enrolled only an actor that was collidable before park | lifecycle tests ran one transition at a time | `test_collision_lifecycle` (fixed, batch 1) |
| GR9 | `on_collide = f` opted the actor back in but did not enroll its pair groups | the callback path built a Collider without the enroll step `collidable = True` has | same | `test_collision_lifecycle` (fixed, batch 1) |
| GR10 | `show_handles()` registered the handles, then a whole-object link refused the call | check after write | the registration was not part of any snapshot | `test_refusal_atomic` (fixed, batch 5) |
| GR11 | `rotate_by(force="no")` (every pose verb) unlinked the parts it wrote: `"no"` is truthy | `force` never validated; flags were walked on constructors only | `TestFlagsTakeARealBool` walked constructor flags whose default is a bool | `test_value_validation` FLAGS (fixed, batch 9b) |
| GR12 | `angle = 10**400` (about 600 setter cases) leaked `OverflowError`, or stored the int | the exact-int fast paths of `finite()`, `_finite_deg` and plain slots skip the range a float has | no pool held a huge int | `test_value_validation` VALUES (fixed, batch 9b) |
| GR13 | `Track.rotate_by(about=(nan, 0))` turned the points to NaN | `_orbit_points` read a tuple pivot raw, past `get_xy` | the NaN pool reached setters, not pivots | same (fixed, batch 9b) |
| GR15 | A SPINE Rect with `angle` linked raised `LinkedAttributeError` on every read once the link moved the heading | batch 4's backstop in `_pose_rotation_set` also refused the update publishing the heading it derived (the link's own echo); `Rect._publish_heading` now uses `_pose_rotation_publish` (a SPINE update no longer publishes at all: GR18) | the deterministic matrix links each field with one value, which for this model equals the construction heading, so the publish was an unchanged no-op | `test_reactive_matrix.TestLinkValuesAwayFromConstruction` (every subject × linkable field × three values; found by the gate's `test_hyp_reactive_matrix`; fixed, batch 11) |
| GR16 | `Texture(filename=[])`, `mouse.click_pos([])`, `State().create([])` / `exists([])` raised Python's "unhashable type" | a dict lookup before the type check (A1 class) | `leak_message` did not count "unhashable type" until batch 9b | `test_hyp_surface` P2 (fixed, batch 11: one `_state_key` check for every State verb; `_check_button`; the image loader checks the name first) |
| GR17 | After `angle =`, the pose store `_rotation` kept the old heading on every kind whose `angle` is a Defining slot (Rect, Square, Ellipse, Line by length, RegularPolygon), and Ellipse / Line flips left it behind too (268 two-verb cases) | only verbs published the store; a plain slot write did not | no test compared the store with the heading; nothing drew wrong, because each verb rereads `angle` | `test_heading_link.TestPoseStoreFollowsTheHeading` (fixed, batch 12; canary) |
| GR18 | A SPINE Rect's `angle` after point writes depended on what had been read in between: the same `p2`, `p1` writes read 204.78 on a rect whose `angle` was read first and -155.22 on a cold one | `_update_impl_spine` unwrapped the heading to the pose store and wrote it back (`_publish_heading`), so the store counted turns only across the updates that ran; a p1/p2 Line keeps the store as the turn reference that only verbs move | point tests read once at the end, cold; the matrix's twin and subject differ in warmth only when two ends are linked and the heading crosses ±180 | `test_angle_field.TestAngleIsTheHeading.test_derived_heading_does_not_depend_on_what_was_read` (every DERIVED_MODELS kind × every read pattern; found by the gate's `test_hyp_reactive_matrix`; fixed after batch 11: the SPINE update does not publish) |
| GR19 | A Circle placed by its rim accepted `angle` and `center` both linked; its radius then depended on which frames read it (45.8 unread vs 28.0 read, same final cell) | batch 4 dropped `center` from `_heading_driven_parts` (the turn pivots on it, so `rotate_by` must not refuse a linked center), and with it the refusal of the pair; but the heading is measured from the center, so each center move made the heading link turn the rim point again | the exclusivity guard enumerated `_heading_driven_parts`, the engine's own list (lesson 2); the reactive machine's twin got one write per link and failed about 1 run in 8, read as an oracle gap | `test_heading_link.test_every_input_the_heading_is_measured_from_is_exclusive` (inputs found by writing each one and watching `angle`); the machine's twin now re-puts every linked value until they hold, and a set that never settles fails (fixed after batch 11: `_heading_pivot_inputs`) |
| GR20 | A SPINE Rect's flip kept the nearest turn, not the convention: `flip_x` of -690 read -570 (every other kind: 870) | Rect's `_mirror_geometry` stored the heading unwrapped to the old turn reference instead of mirroring the reference | flip tests compared headings mod 360 | `test_angle_field.test_flips_keep_the_turns_on_every_kind`. Fixed in parallel on main by the geometry campaign's Q1 (the store is mirrored before the points move); this branch's own fix (mirroring the SPINE turn reference in `_mirror_geometry`) was dropped at the merge, since on top of Q1 it mirrored twice (`flip_x` after `rotate_by(400)` read 500) |
| GR14 | `circle.top_left = …`, `fp1`, `vertex`, `dist` on a kind that lacks them were dead attributes | E13 reserved the size words only | the route guard enumerated the engine's own word list | `test_route_table` (fixed, batch 9b) |

Fixed so far (each batch removes its entries from the known lists):

| Batch | Findings | One-place fix | Guard |
| --- | --- | --- | --- |
| 12 decided leftovers | SC12 (Breaking), GR17; Box / Rect near-copies decided (merge on next change) | an empty group's field read raises with the group and the fix (`_empty_group_attr`; methods stay no-ops); the slot write publishes `_rotation` inline when `angle` is Defining (`Container._write_field`, `Shape._publish_angle_input`), and Circle's own sync runs only in a batch; the Line fast path no longer adds the turn after the write. A/B: non-angle scalar writes unchanged; an `angle =` write 1.19 → 1.35 µs; 160 shapes turned per frame with collision and draw 1.534 → 1.558 ms (+1.5 %, inside the ±2 % band) | `TestEmptyGroupFieldReadsRaise` (162 cases fail on HEAD), `TestPoseStoreFollowsTheHeading` (3 518 cases, 268 fail on HEAD; canary) |
| after 11: heading turn reference | GR18, GR19, GR20 | a SPINE update no longer publishes its heading: the pose store is the turn reference only verbs move, as on a p1/p2 Line (one call removed from a per-update path); `_heading_pivot_inputs` refuses a heading link with a part the heading is measured from (rim Circle `center`; link-time only) | `test_derived_heading_does_not_depend_on_what_was_read` (fails on HEAD for Rect spine), `test_point_writes_keep_the_turns_the_verbs_counted`, `test_flips_keep_the_turns_on_every_kind`, `test_every_input_the_heading_is_measured_from_is_exclusive`; `test_hyp_reactive_matrix` 96 of 96 runs pass (was 4–8 failures) |
| 11 lessons and gate findings | GR15, GR16 | `_pose_rotation_publish` for a derived heading (no linked-pose refusal: the update is the link's echo); `_state_key` / `_check_button` / the image loader check the type before a lookup | `TestLinkValuesAwayFromConstruction` (fails on HEAD), `test_hyp_surface` P2 |
| 10 performance and leftovers | E15, E16, SA14, SC10, SB11, HP14, PA-note; E17, E18 (`made_at`, strict ink by class, `ease=` without `time=`), PA14, SA19 / SC13 dead code, PB-note | class defaults `_main_hitbox_off` / `_touching_sides` / `_blit_plain` (45 `__getattr__` misses per frame → 0); `_frame_outside_scena` walks `sys._getframe`; instant `move_to` skips the pivot; free Polygon `move_by` and Line about-center `rotate_by` take bare float writes (`_move_by_batched` / `_rotate_by_batched` otherwise); retired Hitbox names are `_RetiredKnob` class descriptors; file-list strips shared by decoded images (`_PACK_CACHE`); per-class caches stored on the class; `_ink_strict` on Point / Line; `_require_timed_completion(ease=)` on every timed verb, camera included; `_require_loop_kwargs` checks `yoyo`; `skip_file_prefixes=_WARN_SKIP` in sprite / atlas; `get_point`, `_hitbox_px_scale` and EquilateralTriangle's clone copy removed. A/B (in-process, interleaved, best of 14): 120 moving colliders 0.839 → 0.830 ms / frame; `destroy()` 56.1 → 31.2 µs; instant `move_to` 2.96 → 1.88 µs; Polygon `move_by` 14.0 → 1.9 µs; Line `rotate_by` 8.0 → 3.2 µs; 40 animated sprites with parts 6.27 → 6.14 ms (median); a second file-list Sheet 9.7 → 0.44 ms | `test_hot_paths` (each fast path taken on a free shape, equal to the slow path after a Derivate read; no `__getattr__` miss in a frame; 6 of 9 fail on HEAD), `TestEaseNeedsTime` (39 timed verbs), `TestSheetWarningsPointAtTheAuthor` (+ AST: no `stacklevel=` in sprite / atlas), `TestClipClockUnderPark` |
| 9b validation, hitbox claims, sheet frames | SA6, SA7, SA12, SA15, SB10, SC9, SC11, E10, E12, PA3, PA4, PA6, PA7, PA8, PA9, PA10, PA11, PA13, PB13, PB15, HP6, HP8, HP12, HP13 (decision 5), GR2, GR3, GR11–GR14 | one point reader refuses NaN / inf / a huge int (`shapes._finite_xy`, inline in `_xy_of` / `get_xy`); `validate.finite` and the slot / `_finite_deg` int fast paths bound the int; hand-rolled `float()` setters call `validate.number` (`scale`, `mass`, `clock.scale`, `ui.scale`, Sprite `tilt` / `offset` / `art_angle`, Portal, Warp, Lattice); `force` checked where the pose verbs start; `expect_bool` for every flag that called `bool()`; a claim records the groups it added (`Hitbox._added`); a Sheet keeps each frame's file (`_frame_paths`), names that two frames share are ambiguous, per-clip offsets are recomputed (`_clip_offsets`), `showing()` caches by exact type, a path is spelled as on disk (`_true_case_path`); the relational move hint (`_move_writes_a_link`, `Line._relational_move_hint`); `region_frame` reads the Ellipse's cold frame; `_POINT_WORDS` / `_RELATION_WORDS` route refusals. A/B (per-frame tuple moves, linked tuple formulas, pose verbs, `showing`): 2.738 → 2.758 ms best, medians equal (noise) | VALUES 894 → 0, FLAGS 49 → 0 (`test_value_validation`, canary), UNSTABLE_READS 1 → 0, `KNOWN_BAD_HINT` 4 → 0, `TestNamedLeaks`, `TestSheetFrames` (7), hitbox HP12 / HP13 tests |
| 9a route table | E8, E12 / SA17, E13, E14 class, GR4 | `_install_setattr_route` maps methods, setter-less properties and missing size words (`_SIZE_WORDS`) to `_RouteRefusal`; a setter anywhere in the MRO wins over a method (`Track.line`); teardown installs `_DeadRoute` per instance (`_mark_routes_dead`) so live writes pay nothing. A/B (400 routed writes): 1.515 → 1.512 ms | ROUTE 110 → 0 (+ canary), ATOMIC 256 → 0; `test_hyp_canvas` model and `test_process` follow E9 / the quiet `on_update`; the `world_view` smoke HUD no longer writes into Texts its scene destroyed |
| 8b sprite timing and draw | PB3, GR6, PB4, PB5, PB6, PB7, PB8, PB9, PB14, SA9, SA13 | `process.whole_steps` (inlined in the playhead), boundary `next=`, `play()` settles, `_adopt_clip` resets the frozen phase, `entity._time_scale_value`, no style costume without a look, Recolor through `_apply_blit_paint_extras`, `size` / `svg` refit to the cell aspect, `wheel_rotate` in `_sync_interactive_registry`, Point remembers the layer it was hidden from. A/B (150 animated sprites): 1.237 → 1.248 ms (inside the ±2 % noise; the extra compare is the fix) | CLIP_DUE 28 → 0 (the test had reset the clock between cases; fixed), TRUNCATED_TIME 2 → 0, DRAW_DOORS 5 → 0 (blend now judged over a gray backdrop), `TestClipTimingAndSize`, `TestPointKeepsItsLayer` (7 cases that fail on HEAD) |
| 8a relational geometry | SB1, SB4, SA4, SA16; GR1 triaged (documented) | `Line._gate_tangent` (one table of what a tangent line's verbs do; default pivot = the circle's center), `Line._rotation_value` for TANGENT_ANGLE, Point `rotate_to` = `rotate_by(θ − angle)`, `move_by` / `move_to` refuse a dropped second argument; C2 gains `rotate_to about`; `CONTRACT_EXEMPT` for the documented relational meanings | `geometry_known` empty (C1–C8), `KNOWN_HEADING` empty, `TestRelationalVerbs` (4 cases that fail on HEAD) |
| 7 copy contract | SC7, SB7, SB6, SB5, SC2, SB9 (Breaking), E9 (visible) | `Container._takein_pose` hook in `_takein` and the whole-link pull; `Shape._takein_pose` → `_clone_pose_from`; `_free_model` + `_defining_names_for` (Line, Ellipse) in `_adopt_model_of`; `Shape._drop_relational` on a forced unlink; Line / Ellipse `_clone_geometry` build then take in; Polygon takes `other.points`; `from_points` passes points to the constructor; `clone` reads the park stash for `visible` | C7 sweep (238 → 6, all source bugs of batch 8; a refused source verb now ends the comparison), `test_shapes.TestCopyContract` (6 cases that fail on HEAD), `test_reactive_matrix` (relational copies skip `dist` / `at_angle`) |
| 6 cold readers and caches | SC6, SB8, PA1, PA2, PA12, PB10, PB11, E7, GR7; GR5 triaged (by design, G11) | hit tests / `is_collapsed` read `_segment_xy` / `_center_xy` / `_radius_value` / `_oriented_frame` / `_placement_params`; `atlas._auto_key` and the silhouette / union keys hold every bake input; live-sheet bakes exempt from the LRU, `_UNION_CACHE` bounded and purged (`_key_tokens`); `Sheet._layout_epoch` keys the blit's source rect and the Shield envelope (with `_du_per_px`); `state._value_changed`. A/B (150 sprites drawn + 300 ink writes): 1.487 → 1.494 ms (noise) | `TestEngineReadersStayCold` (KNOWN_WARM 25 → 0), COLD_READS 10 → 0, CACHE_KEYS 5 → 0, five cache tests that fail on HEAD, `TestInkStoresNewObjects` |
| 5 check-then-write | SA5, SC3, SB2a / b / c, E14 (flips), SC4, SC5, SA11, SC1, PB1, PB12, PA5, E9, E10, HP11, GR10; Polygon `scale_by` batch decorator | gates before writes in every verb named; `_mirror_geometry` / `_mirror_scalar_parts` gate first; `_apply_flip` refuses dead / linked pose up front and restores the flag; `_tag_names`; `_iter_free_defining_points` skips a whole-linked shape; `Sprite._gate_clip_size`; `clone` validates `scale` and refuses a dead source | `TestLinkWriteGate` (183 → 0), `test_refusal_atomic` (ATOMIC 391 → 302, all batch 9) + `TestRefusedSpriteCallsChangeNothing` |
| 4 write gate | SA1, SA2 = E6 = PB2, SA3, SB3, SC8, SA10 | `_ensure_writable` hops to a linked owner, skips property pose anchors, takes `pivot=`, exits on the sticky tree flag; `_refuse_linked_pose` in the pose writers (backstop) and in the verbs' up-front gates (`_resolve_scale_apply`, `_gate_pose_anchor`, with `force`); `_whole_link_carries_pose` (Point: position only); `Point._takein` refuses a dead point; Circle `_heading_driven_parts` drops the center (the turn pivots on it). A/B (100 sprites rotate + scale, 100 polygons rotate, 100 centre writes): 1.362 → 1.355 ms | `TestLinkWriteGate` (689 → 183, all batch 5 flips / check-then-write) |
| 3 paint materials | HP1 (Breaking: `Color.alpha` read-only), HP2, HP3, HP4, HP9, HP10, GR4 | `Color` immutable; `PaintState.set_alpha` assigns faded copies (`with_alpha`, `Gradient._map_stops`, a shallow Texture copy); `Gradient.set_alpha` replaces its stop Colours; one table of paint writes wrapped with the dead check after `PaintState` (`_PAINT_WRITE_PROPERTIES` / `_METHODS`); the ghost fill paint is a copy; the sprite-only look check runs before any write; Sprite save / restore carry `alpha`; width ≤ 0 builds no stroke paint (checked on a build only: `line_width =` clears the cache, so no per-draw cost) | `test_material_isolation` (113 → 0, plus `TestPaintWritesStayPut`), `test_draw_doors` (hairline), `test_refusal_atomic` (dead paint) |
| 2 construction | E4 (both causes), E5, E18 (swallowed enroll) | the finish step runs inside the rollback (`_wrap_actor_init`); the rollback is `Registry._destroy_teardown` (`place._drop_failed_construct`); `__init_subclass__` adopts a mixin's `__init__` (`_adopt_mixin_init`); the enroll `except` narrowed to the ui / parallax refusals | `test_construct_failure` (base × raise point × layout; every finish hook runs) |
| 1 collision lifecycle | E1, E2, E3, E11, HP5, GR8, GR9; E12 for `on_collide*` | callbacks live on the actor (`Entity._collide_cbs`, copied by `ensure_collider`); one join path `Entity._enter_collision` (`collidable = True`, callback opt-in, resume) and one leave path `_leave_collision` (park never writes the opt-out); the opt-out recorded on every author `collidable = False`; stash validated when written (`_wants_collision` in the layer guards); `_item_in_play` reads the stored `_active` | `test_collision_lifecycle` (every sequence of up to three lifecycle statements vs a twin in the final state; method callback; ui while stashed); `test_hitbox_round2.TestLinkedActive.test_link_runs_once_per_step_not_per_contact` |

### GX — geometry campaign (2026-10-08)

White-box harnesses over the whole geometric model ([Geometry campaign](#geometry-campaign)).
Contract questions settled first (Q1–Q5); the engine bugs they exposed and the
new findings below are listed shrink-only in `tests/geom_campaign_known.py`
until their fix wave (phase 7).

| ID | Bug | Root cause | Why earlier tests missed it | Guard |
| --- | --- | --- | --- | --- |
| GX1 | A tall Ellipse (height > width) swaps `fp1` / `fp2` on a flip | the foci are derived along the heading's major axis; `180 − θ` reverses that axis when it is the height | KINDS builds wide ellipses only; C1 checks one verb from one pose | H1 (degenerate base: width 0), `test_geom_probes` GX1 Fixed, wave 2: the foci turn by `−90°` when exactly one flip is set (`Ellipse._update_impl_center_wh`; `test_flip_mirror.TestFlipHeadingEdges`). |
| GX2 | A zero-length Line keeps its heading on a flip | a collapsed segment's heading lives in the pose store, which the flip does not mirror | no sweep collapses a Line before a flip | H1 (degenerate base), probe GX2 Fixed, wave 2: the flip mirrors the pose store before the points move, and a zero-length Line recomputes its derived heading (no point moved to do it; same test class). |
| GX3 | A zero-length TANGENT_ANGLE Line accepts a flip it refuses at any other length | the refusal depends on a write happening | same | H1, probe GX3 Fixed, wave 2: a tangent Line's points get no pivot exemption on a flip (`Line._mirror_geometry`), since the flip also turns a heading the relation owns (same test class). |
| GX4 | Timed `move_to` / `scale_by` / `scale_to` (and a tangent line's `move_by`, a Line with a linked center's turn) are accepted at the call where the instant verb refuses; the refusal comes from a later tick, after part of the motion ran (584 cells) | the timed doors (`timed_*`) skip the instant verbs' up-front gate | `TestLinkWriteGate` and the relational tests call instant verbs | `test_geom_structure.TestTimedVerbsGateLikeInstant`, H1 (`refusal changed` on timed steps), probe GX4 Fixed, wave 3: the timed verbs run the instant gate at the call (`_probe_rotate_writable`, `_scale_gate_at_call`, `_move_by` probe; `test_process.TestTimedVerbsGateAtTheCall`). |
| GX5 | Below `MIN_SCALE`, a pose-zoom kind (Sprite, Svg) moves its center by the clamped factor and its size by the exact one | the pivot math reuses the Shapes clamp | no sequence scaled from `MIN_SCALE` with a pivot | H1 (`min_scale` base), probe GX5 Fixed, wave 4: a pose zoom orbits its center by the drawn ratio (`Shape.scale_by`; 0 counts as `MIN_SCALE`; `test_shapes.TestPoseZoomStaysSimilar`). |
| GX6 | A whole `@=` (or a point-part link) installed during a running timed verb is accepted; the next tick raises | the "pushes it" check runs for field links only | link tests start from idle shapes | H1 (`mid_tween` base × link), probe GX6 Fixed, wave 3: timed turns and scales claim every part they write (`_pose_claim_targets`), and a whole `@=` checks claims under it (same test class). |
| GX7 | With a linked heading, a write to `p1.x` before any read makes later reads of `p1.x` skip the pull (reads 1.0; `p1.y` and a twin read the turned point) | `_write_field` seeds the bare-read cache without the `_pull_owner` check `__get__` makes | D18's tests read before writing | probe GX7 Fixed, wave 4: the write seed checks `_pull_owner` like the read (`test_heading_link.TestWriteBeforeReadKeepsThePull`). |
| GX8 | `Track._move_by` swallows every exception from its fast path and retries on the slow one | a broad `except Exception: pass` | — | `test_geom_structure.TestNoBareExceptInPoseVerbs` Fixed, wave 1: the fast path is gated, with no `try`. |
| GX9 | `sprite << other`, `svg << other`, `text << other` raise Python's `NotImplementedError("Subclasses must implement takein")` | no `_takein_impl` and no refusal for these kinds | `sweep_c7` skips `<<` for them | `test_geom_laws.TestCopyCommutes` Fixed, wave 1: `Graphic._takein_impl` refuses with the fix (`test_shapes.TestCopyDoorsRefuseWhatClonesRefuse`). |
| GX10 | `track << flipped_track` draws the unflipped points | the free-points copy carries the flip flag but not the mirror | same | `TestCopyCommutes` Fixed, wave 4: the takein un-mirrors the source's table, as `clone()` does (`test_track.TestCopyOfAFlippedTrack`). |
| GX11 | A `@=` refused for `wheel_rotate` (Polygon, Sprite `["angle"] @=`) leaves a new `angle` anchor part and a graph node (W3: a refused link installs nothing) | the anchor is made before the conflict check | `test_refusal_atomic` never meets a `wheel_rotate` conflict | sentinel I-atomic on `test_shapes` Fixed, wave 1: the property-anchor path drops the anchor it made (same test class). |
| GX12 | `dst << dead` copies a destroyed shape (every kind), while `dead.clone()` refuses with `DestroyedError` | `_takein` checks the destination, not the source | refusal tests use dead destinations | sentinel triage; probe in phase 7 Fixed, wave 1: `Container.__lshift__` refuses a destroyed source (same test class; A/B `Point << tuple` within noise). |
| GX14 | A link pull accepts a `bool` (`True` reads as 1.0) that `=` refuses, leaks Python's `OverflowError` for `10**400`, and names the field "magnitude" in its message | the pull's coercion (`ScalarAnchor._takein_impl`) skips the slot's exact-type checks | `TestOneCoercionForEveryPath` checks NaN / limits, not a bool or a huge int through a pull | `test_geom_values` (every field × value × path) Fixed, wave 4: the pull applies the Numbers rule with the slot's label; a cell in a pair is read as stored; a bool and a number differ on change; unlink keeps the last good value (`test_value_validation.TestLinkPullsKeepTheNumbersRule`). |
| GX15 | A shape's `vec` part (Rect / Line point-vec) stores `(0, inf)` on every path; every later read of `p2` / `width` raises; `10**400` leaks `OverflowError`; a Line moves its center before refusing | the Vec2 part's takein reads its pair past the point reader (`_xy_of`), so the Numbers rule does not run (D24 class) | the value sweeps reached point slots, not the `vec` part | `test_geom_values` (ci: every kind) Fixed, wave 4: `Vec2._takein_impl` refuses a non-finite pair on a part and an overflowing int on any Vec2 (same test class). |
| GX16 | After one allowed `scale_by` about a linked center, a CENTER_LENGTH_ANGLE Line's end midpoint drifts 8.9e-16 from the linked center and every later `scale_by` is refused | the gate compares the pivot to the linked part exactly, and `_center_xy()` recomputes the center from the ends instead of reading the Defining center | one verb per test; nothing ran two | H10 (`identity_scale` rewrite) Fixed, wave 3: the home model's pose center is its Defining center (`Line._collision_pose_anchor`; `test_shapes.TestLinkedCenterStaysThePivot`). |
| GX17 | A timed `rotate_by` / `rotate_to` on a Circle whose center is linked is refused while the instant turn about that center runs | the timed door gates the center the instant door knows is the pivot (GX4 reversed) | gate tests asked "instant refuses ⇒ timed refuses" only | H10 (`timed_to_instant`), `TestTimedVerbsGateLikeInstant` (both directions) Fixed, wave 3: the rotate probe takes the pivot rule (`test_process.TestTimedVerbsGateAtTheCall`). |
| GX18 | `rect << box` keeps the rect's old pose store while `angle` takes the box's (0 vs 17) | a Box has no pose, and `_takein_pose` carried a pose only from a Graphic | `I-heading | *` was listed for GR17-link and matched it too | sentinel I-heading on `test_refusal_atomic` Fixed, wave 2: a copy from a pose-less source publishes its own Defining heading (`Shape._takein_pose`; `test_shapes.TestCopyDoorsRefuseWhatClonesRefuse`). |
| GX19 | `dead_rect << box` writes the source's name signs into the destroyed rect, then raises `DestroyedError` (a flipped dead rect's `top_right` moved) | `Rect._takein_impl` stores the signs raw before its first guarded write | the refusal sweep's subjects are unflipped, so the signs were equal | sentinel I-atomic Fixed, wave 2: the takein refuses a destroyed rect first (same test class). |
| GX13 | An anchored Text (`top_left=` / `top_right=`) accepts a link on its anchor and another on `center`; the two then disagree (the center follows its source, the anchor stays), and in the other order the center link does not hold its formula. Rect refuses the analogue (`center` is a Derivate there) | the caption's center is an input on every placement | Text was not a reactive-matrix subject | `test_hyp_reactive_matrix` (H6 subjects), probe GX13 Fixed, wave 1: `Text._link_field` (`test_text.TestOnePlacementLink`). |
| GX20 | An anchored Text whose `center` links lost its formula when the string changed (a write, formula text, `width`, `font_size`): the layout kept the anchor and moved the centre by half the width change, then published that over the link (`text` and `center` linked to one cell: center x −16.95 for a formula of −16.0; `top_left` / `top_center` / `top_right` off by the same 0.95). Also: a write to the other placement part while one linked was accepted and the two disagreed (`t.top_left = P` under a linked center; `t.center = P` after a runtime `t["top_left"] @= f`), and the whole-part spelling `t.center @= f` got past the GX13 refusal | `_refresh_layout_now` read every `center` change as a translation of the anchor's pin, so a linked center was a one-shot input, not a pin. Defining-ness was fixed at construction, so a runtime link left the other part writable. The GX13 refusal lived in the bracket path (`Text._link_field`) only | GX13's tests linked `center` and read it without changing the string. Found by the deep serial pass of `test_hyp_reactive_matrix` (2026-10-09; deterministic, fails on `d9abd91` too) | `test_text.TestLinkedCenterIsThePin` (every anchor × every width input; one cell for `text` and `center`; anchor writes in every spelling refused; unlink in both directions; a turned caption), `TestOnePlacementLink.test_every_link_spelling_takes_one_placement`; `test_hyp_reactive_matrix` (`_Pair.settle_twin`: `text` and `center` do not commute as plain writes, and the link holds `center`, so the twin re-puts every linked value until nothing changes). Fix: a linked part is the pin while it links ([Canvas Design](Canvas%20Design.md), Text). `Text._sync_placement_model`, run by the `Container._note_part_link_changed` hook on every link install and unlink, makes the other placement part Derivate, and the layout lays the box around a linked center. A/B per caption layout, in one process: noise (changing string 18.36 vs 18.27 µs, steady 5.12 vs 5.22 µs) |


### SY — systems review, design decisions (2026-10-09)

A review of the frame body, scheduler, input, acts, reactive core, shapes,
sprites, box, collision, registry and canvas (report in the private
workbench) confirmed about 90 interaction bugs; 17 of its items needed a
design decision. The decisions and their guards:

| # | Decision | Guard |
| --- | --- | --- |
| SY1 | The fade cover runs on presentation time (`clock._ui_time`: unscaled, capped like the world) | `test_cover.TestCoverRunsOnPresentationTime` |
| SY2 | SpatialFx tick and shader phases run on world time; `SystemWorld` no longer pins their clock | `test_spatial_fx.TestSpatialFxRunOnWorldTime` |
| SY3 | `every` keeps its debt (bounded catch-up) | `test_process.TestEveryCountsWorldSeconds`; `test_sys_hyp_scheduler.TestEvery` (new contract) |
| SY4 | Hidden layers keep scrolling; no 1.5 s skip on world time | `test_layer_scroll_view.test_hidden_layer_keeps_scrolling`, `test_camera_response.test_integrates_a_long_gap` |
| SY5 | Only rounds where a watch fires again count toward `FLUSH_MAX_ROUNDS` | `test_reactive_edge_cases.TestEvents.test_long_acyclic_chain_settles_in_one_flush` |
| SY6 | An act's ownerless named timer suspends the game's same-name timer until the change | `test_act.TestNamedSlotsAcrossTheSeal` |
| SY7 | Act-created layers leave with the act | `test_act.TestActLayers` |
| SY8 / SY10 | Act teardown in two phases; objects born in teardown run no `on_destroy`; cap 100 passes | `test_act.TestTeardownPhases` |
| SY9 | An act's callables handed to game objects leave with the act | `test_act.TestActCallablesOnGameObjects` |
| SY11 | Top-level `@leave_playfield` handlers accumulate | `test_leave_playfield.test_second_registration_adds`, `test_act` (act handler leaves) |
| SY12 | Park holds an owned sound's `on_done` until resume | `test_process.TestParkHoldsSoundOnDone`; `test_sys_hyp_audio` (held end has no voice) |
| SY13 | `contains_point` is False on a destroyed actor | `test_shape_interaction.TestContainsPointOnADeadActor` |
| SY14 | `clone()` copies `hitbox.active = False` | `test_sprite.TestSpriteClone` |
| SY15 | Atlas cache keyed by path + file stamp; cached frames frozen | `test_atlas.TestAtlasFileCache` |
| SY16 | `Text(fn)` links | `test_text.TestTextTakesAFunction` |
| SY17 | Actors Design: `on_destroy` errors raise after teardown | doc only |

Two lessons from implementing them:

1. **A reset that swallows errors hides a broken call.** `_reset_act_manager`
   (test isolation) calls `ActManager._teardown` inside `except Exception:
   pass`; a signature change made that call raise `TypeError`, the reset did
   nothing, and the next test module saw a leftover actor in its group
   count. The failure surfaced two modules away from its cause. A swallow on
   a cleanup path needs its own test that the cleanup happened.
2. **The harness pinned a clock production did not read.** `SystemWorld`
   pinned SpatialFx and the cover to world time, so every system test ran
   a clock the shipped code never used (SY1, SY2). A harness pin is a second
   implementation; keep it only where production is non-deterministic (shape
   transients on wall time), and test the production clock at least once.

### RV — systems review fixes, batch 1: crashes and dead subjects (2026-10-09)

Root causes R2 (author code on a subject the engine already killed; exit
without enter) and the act-change crashes of the systems review. Repros:
private workbench, "2026-10-09 systems review/repro".

| ID | Finding | Fix | Test |
| --- | --- | --- | --- |
| X-life-5 | `destroy()` fired the dying object's own hover / collide exit after `is_alive` turned False: the taught un-highlight raised out of `destroy()` and `change_act` (the title menu crashed) | teardown marks `_dying`, fires the exits, then marks dead; a re-entrant `destroy()` is a no-op | `test_pointer_hover.test_destroy_exit_sees_a_live_shape` (was a weak oracle: it passed with a dead shape), `test_collision.TestDyingBodyExits`; `Probe.TEARDOWN_TAGS` emptied |
| S9-2 | the survivor's exit counted the dying partner in its group | the dying object leaves its group buckets before any exit | `TestDyingBodyExits.test_survivor_exit_sees_the_group_without_the_dying` |
| S8-2 | later handlers of one dispatch ran on a side an earlier one destroyed | dispatch epoch checked after each handler that ran | `test_collision.TestDispatchSeesWhatHandlersDid` |
| S8-3, X-life-2 | exit for a pair whose enter never ran; exits on dead bodies after a mid-step `change_act` | the step's pending enters / exits: a leaving body drops pending enters and fires pending exits at once | same class; `test_act.TestChangeInsideADispatch` |
| S4-1 | the leaving act's `@collide` / `@leave_playfield` ran after `change_act` in one dispatch | epoch → registration re-check; leave handlers re-checked against the live table | `test_act.TestChangeInsideADispatch` |
| S4-2 | an act's `fade_out(on_done=)` fired in the next act | the change drops an act-made cover `on_done`, keeps the fade | `test_act.TestCoverOnDoneLeavesWithTheAct` |
| S2-2 | `tween(x["field"])` / `tween(x.center)` wrote a dead actor or crashed the frame | every tween door resolves the Entity it writes (`_entity_written_by`) | `test_process.TestTweenDoorsOnADeadTarget` |
| S6-3 | timed verbs on a `reversed()` view tweened the view (summed with the host's, outlived it) | the view's forwarding verbs skip the timed wrapper | `test_track.TestReversedViewTimedVerbs` |
| S2-1 | a mode body's ambient owner leaked into `setup()` / `on_destroy` / `@exit_mode` | `process.call_without_owner` / `no_owner` | `test_process.TestHooksHaveNoAmbientOwner` |
| S2-3, S2-4, S2-12 | exit hook: `self.mode =` recursed; destroy ran the next body on a dead actor; a watchdog trip froze the mode | `mode =` in its own exit hook raises `TypeError`; a destroyed actor ends the transition; any exception completes it | same class |
| S2-8 | a classless `@when` over a field readable after destroy never retired (kept the actor) | destroy retires classless watches whose condition holds the actor (index of classless watches: no scan of all) | `test_process.TestWatchOnADestroyedSourceRetires` |
| S9-3 | a broadcast called members an earlier member destroyed | skip on `DestroyedError` when a destroy happened during the broadcast | `test_registry_layers.test_broadcast_skips_members_an_earlier_call_destroyed` |
| S1-2 | `on_drop_by` ran on a target `on_drag_to` destroyed | liveness re-check | `test_shape_interaction.test_no_drop_by_on_a_target_drag_to_destroyed` |
| S1-4 / S3-10 | hover exit for a target whose enter never ran | `_hover_entered`: exit only after its enter | `test_pointer_hover.test_exit_that_destroys_the_next_target_gives_it_no_exit` |
| X-life-1 | park fired exits while `active` read True; a `visible` write left a parked actor drawn | park marks parked before leaving collision | `test_collision.TestParkExitSeesAParkedActor` |
| X-life-3 | a release whose press a parked / destroyed shape or widget took reached the script's `on_mouse_up` | no script up without its down (an old test pinned the opposite; the doc said otherwise) | `test_script_callbacks.test_up_without_script_press_reaches_nothing` |
| S1-5 | `last_click` kept a Button that destroyed itself in its `on_click` (HD4 cleared it before it was stored) | nothing stored when the click killed its widget | `test_uiwidget.TestDestroyedWidgetLeavesTheLastClick` |

Lessons:

1. **A liveness check on a hot loop costs, unless it is gated.** The first
   versions cost 1–5 % (a property read per broadcast member, a check per
   handler). Gating with a counter (dispatch epoch, registry destroy count)
   or an exception that is free until raised (a `DestroyedError` skip in the
   broadcast) brought every bench back to noise (alternating runs against a
   HEAD export; A/A noise ~1 %).
2. **`getattr(entity, "_new_flag", default)` reaches the ink `__getattr__`.**
   A missing attribute on an Entity runs the ink lookup (it builds an error
   with hints) before the default applies: 2.5 µs per destroy. A new private
   flag read on a hot path gets a class default.
3. **A test can pin the implementation against the doc.** The canvas test for
   "up without a script press" asserted the up was delivered; Shapes Design
   said a swallowed press gives the script nothing. The doc won (Lessons
   learned 13). So did a hover test whose oracle (`is_alive or center`)
   passed for a dead shape.

### RV2 — systems review fixes, batch 2: field-reference links and the reactive core (2026-10-09)

| ID | Finding | Fix | Test |
| --- | --- | --- | --- |
| S5-1, S6-5 | `q["x"] @= p["x"]` followed only `=`: 62 of 108 writer × kind cells stale (copies, pose verbs, flips, tweens, Text moves) | write dispatchers notify source-only field anchors (`_notify_source_anchors`); Text treats a field anchor as a link reader | `test_diff_link_write.TestFieldRefSourceFollowsEveryWriter` |
| S5-2 | a link reading a Derivate scalar froze it for every reader | the anchor of a Derivate field depends on its owner; a dirty read recomputes | same class |
| S5-3 | a property-anchor pull took `True` as 1.0, leaked `OverflowError` | `validate.number` on the pull | `test_reactive_edge_cases.TestReactiveCoreDoors` |
| S5-4 | `_in_batch_update` (a Shape slot) read through `__dict__`: handlers flushed mid-batch; a retired part read `active` True | attribute access everywhere | same class; `test_write_path_guards.TestNoDictAccessToASlot` |
| S5-5 | `unlink()` / `destroy()` raised on a formula raising `KeyError`, orphaning the anchor | keep the last value on any pull error; clean the anchor in `finally` | `TestReactiveCoreDoors` |
| S5-6 | `clone(scale=-1 / 1e308)` registered the copy, then raised; `scale=True` accepted | validate first; destroy the copy if the scale cannot apply | `test_construct_failure.TestCloneScaleIsAtomic` |

Lessons:

1. **An edge that looks natural can be a cycle in another model.** Making
   every source-only anchor depend on its owner fixed the matrix and broke
   every PARALLEL_DIST line (its `p1` reads its own `dist`). Notify from the
   writers for Defining fields; keep the upward edge for Derivates, which a
   part cannot read without a real cycle.
2. **A same-work A/B, not a work-changing one.** The first A/B showed +19 %:
   the base did no work because its links were stale. Compare a workload both
   trees compute (writers that notified before too); that A/B found a real
   +10 % (a refresh on every read of a Defining field), fixed to noise.
3. **The class guard found members the review did not list.** Scanning every
   slot name read through `__dict__` found `retire_part` writing `_active`
   into the dict (a retired part read active).

### RV3 — systems review fixes, batch 3: leave paths and input (2026-10-09)

| ID | Finding | Fix | Test |
| --- | --- | --- | --- |
| S8-5 | `touching_sides` stayed `"bottom"` after park / opt-out; rejoin floor-snapped mid-air | `_leave_collision` clears it | `test_collision.TestLeavePathsForgetWhatTheyLeave` |
| S8-6 | `_contact_memory` / `_passing` survived with no resolve pair | cleared at the resolve pass's early return | same class |
| S8-9 | a compound Collider pruned silently (no exit, handlers leaked) | compound: exits + `drop_pair_handlers_for` | same class |
| S8-8 | queries in `update()` used the last step's object cache | cache cleared at step end and on a leave | same class |
| S3-2 | a hidden / parked modal left keys and mouse masked | `sync_modal_mask` once per frame (a level) | `test_input_frames.TestModalInput` |
| S1-1 = S3-1 | `mouse.dx` was the last callback's step, never reset | per-frame accumulator, reset at frame end | `test_input_frames.TestMouseDeltaIsPerFrame` |
| S3-4 | a drag did not follow a camera pan under a still cursor | drag step from the sampled pointer | `TestDragFollowsTheWorldPointer` |
| S3-5 = S1-3, S3-6 | widget highlight stuck after press-drag-off; widget hover only on moves | pressed widget keeps hover; widget epoch → `refresh_hover` | `TestWidgetHover` |
| S3-7, S1-10 | a modal ate the script's up; a shortcut sent an up without a down | `_keys_down` / the script's own press decide who gets the up | `TestModalInput`, `TestKeyEdges` |
| S3-8, S3-11 | an old act's press clicked in the new act; `click_pos` reported a masked click | `forget_act_input`; masked clicks not recorded | `TestActChangeForgetsPointerInput`, `TestModalInput` |
| S3-9 | `keyp.once` lost when a modifier was tapped in the same poll | a pending play key keeps its edge | `TestKeyEdges` |

Harness: `tests/input_driver.py` delivers GLFW-shaped events through the
framework's own handlers between `SystemWorld` steps (the world stubs
`poll_events`, so no system test had run an input callback in a frame).

### RV4 — systems review fixes, batch 4: what an act change owns (2026-10-09)

Root cause R3: the seal recorded a hand-picked set of registries, and the
settings guard walked a hand-picked set of objects. Each row is a registry an
act could write that neither list named.

| ID | Finding | Fix | Test |
| --- | --- | --- | --- |
| S4-3 = S9-4 | an act's `group["x"] @=` survived: restart warning, pinned act, name blocked for tagging | the seal records `_group_formulas`; the change puts that set back | `test_act.TestActOwnsItsRegistries` |
| S8-4 | `unresolve(x, ANYTHING)` and an act's `ANYTHING` rule left `x` pairing with every body | `_prune_pair_targets` re-derives `ANYTHING`; `unresolve` prunes both sides | same class; `test_collision.TestAnythingInterestLifecycle` |
| S8-7 | a tag no rule named any more kept enrolling members (act change, `unresolve`, destroy of an object side) | `retire_unused_pair_tags` at every door; a body enrolled only by the tag leaves, an author `collidable = True` stays | same classes |
| S9-5 | a game actor's camera tween undid the restored camera | the camera restore cancels every camera channel | same class |
| S4-5 | the act's HUD stacked lower on every restart | the HUD column cursor is a `WORLD_SETTINGS` row (`hud_stack`) | same class; `TestWorldSettings` |
| S4-6 | the settings guard never walked `ui` | the guard walks every exported instance; the rest are excused by name (`NOT_WALKED`); `ui.scale` / `font` / `min_label_space` kept as preferences | `TestSettingsClassification` |
| S4-7 = S1-8 | a change from a handler froze the old act's bodies until the next change | the change requests the collect + freeze; the end of `_simulate_frame` runs it | `test_gc_freeze` |
| S4-9 | a runaway teardown raised before the restore and the script-level drop | both run in a `finally` | `test_act.TestTeardownPhases` |
| S4-8 | the test reset re-installed the game's leave handlers and resolve pairs | `reset_system_globals` resets the act manager first | `test_sys_lifetime.TestWorldsAreIsolated` |
| X-life-8 | `SystemWorld` kept keys, hover, press and the HUD cursor between worlds | `reset_input_state` in every world and in `ProgramRun` | same class |

Guard for the class: `TestNoLeaks.test_one_act_gives_back_every_registry`.
The busy act uses every verb above once, and the registries with no lazy
warm-up must read the same after one act as before it. The census gained
`collision.pair_tags`, `collision.anything_targets` and `registry.layers`. A
warmed census comparison cannot see a registry that leaks once and then
stays flat, so this test compares against the census taken before the first
act.

### RV5 — systems review fixes, batch 5a: a rejected call leaves no trace (2026-10-09)

Root cause R6: a refusal checked after part of the work was done.

| ID | Finding | Fix | Test |
| --- | --- | --- | --- |
| S2-5 | a rejected timed verb (`time=-1`, a bad `ease=`) cancelled the job in flight; `face=True` turned the shape | `_validate_timed` before the replace and the face snap | `test_rejected_calls_leave_no_trace.TestRejectedTimedVerbs` |
| S8-1 | `@collide([hero, hud], b)` / `resolve([...], b)` left the earlier pairs live | the layer check and `bounce=` for every member first; rollback on a late failure | `TestRejectedListSides` |
| S7-5 / S7-6 | `size =` wrote `width` before a linked `height` refused; `frame =` stopped the clip before a linked width refused | both slots checked first; `frame =` gates like `play()` | `TestRejectedSpriteSize` |
| S7-7 | a `next=` switch raised `LinkedAttributeError` from the draw, half-applied | the switch settles in the simulation (`settle_clip_ends`); a linked size keeps its link | `TestDeferredClipSwitch` |
| S2-13 | a raising sound `on_done` lost every other sound that ended that frame | the unprocessed ids carry to the next tick | `TestRaisingSoundDone` |

Not fixed here: S9-1 (a `ui` / parallax member joining a pair group raises
or is skipped depending on statement order). Both outcomes are documented
somewhere (decoration refuses; E18 construct and the query rule skip), so
making the two orders agree is a design decision, not a fix.

### RV6 — systems review fixes, batch 5b: doors that agree, order that holds (2026-10-09)

Root causes R7 (one payload, several doors; each door had its own test, none
compared them) and R8 (a key or an order that depends on something unrelated).

| ID | Finding | Fix | Test |
| --- | --- | --- | --- |
| S6-6 | `contains_point` used the stale pose of a linked angle / scale | it pulls, as draw and the query do | `test_doors_agree.TestHitTestPullsTheLinkedPose` |
| S6-1 | `force=True` scale / rotate computed from the last pulled pose | `_fresh_pose` before the delta | `TestForceUsesTheFreshPose` |
| S6-2 | `move_along(view)` read the view's stale copies | reads the host | `TestReversedViewRidesLikeItsHost` |
| S6-4 | one pivot: exact in the gates, 1e-12 in the verbs | `_near_pivot` everywhere | `TestOnePivotRule` |
| S7-3 | Box `rotate_by` drifted from Rect's (no `pivot=`) | merged into `_RectFrame` (`_rotate_frame`, `_take_frame_parts`) | `TestOnePivotRule` (Box vs Rect, every model) |
| S7-4 | `confine` kept the full sweep (ghost `@collide`) | the correction joins the pending motion; wrap is a placement | `TestConfineSweepsLikeMoveTo` |
| S9-7 | `unresolve(a, group["t"])` matched nothing | tag sides compare by tag | `TestSideSpellingsAgree` |
| S9-9, S2-15 | `layer.visible = "no"`, `z = 5.5`; `ready.*` names unchecked, `disable` before a poll a no-op | flag / whole number; name first; a disabled slot | `TestSmallRefusals` |
| S7-2 | `min_hold` a frame late | `reached` | `TestMinHoldIsDueByReached` |
| S2-7 | the move replace key changed once `.center` was read | `(id(shape), "center")`, shared by `tween(shape.center)` | `test_scheduler_order.TestMoveReplaceKey` |
| S2-9, S2-10 | `on_update` in address order; a cleared one ran later that frame | ordered weak set; the snapshot entry is swapped | `TestUpdateFleetOrder` |
| S2-11 | cancel of an outer running script threw into it | any executing coroutine defers | `TestOuterScriptCancel` |
| S2-14 | `@on_change` missed `1 → True` | bool-ness is a change | `TestOnChangeSeesBoolVersusNumber` |

S7-1 (a yoyo end missed the "each" hitbox part) no longer reproduced on this
tree. Perf: the first S2-10 fix (one attribute read per actor in the fleet
loop) cost about 2 % of a 400-actor frame; the shipped fix swaps the frame
snapshot's entry from the setter instead, and the loop is unchanged.

### RV7 — systems review fixes, batch 6: perf (2026-10-09)

| ID | Finding | Fix | Measured | Test |
| --- | --- | --- | --- | --- |
| S9-10 | `cull_offscreen` drew 2–3× slower than no culling | layer checks once per layer, view window once per draw, optional names probed per class (`_probe`), stroke reach without double reads | 1000 cheap rects: 2.8× → 1.1× of no-cull; 1000 `Text`: culling 2.5× faster | `test_cull.TestCullDrawLoop` |
| S9-8 | an empty group built a registered `Blank` per field write and per timed verb | field names remembered after the first write; a timed verb is a timer | 0.16 → 0.03 ms/frame, no roster churn | `test_noop_cost.TestEmptyGroupWritesAndTimedVerbsBuildNothing` |
| perf | `_dispatch` copied and matched every handler per contact | phase snapshot; tag prefilter; act manager and phase map hoisted | 31 handlers, 150 stay contacts: 4.45 → 3.0 ms/frame | `test_collision.TestDispatchHandlerIndex` |
| S9-11 | pointer → world and world → view in float32 (0.05 units at 1e6) | float64 closed forms | error 0 in the repro | `test_doors_agree.TestPointerMapsInFloat64` |

Leftovers closed in the same batch: S8-10 (a raising body exit skipped the
part exits: `test_hitbox_parts.TestDestroyExitsEveryPart`), S1-9 (a raising
GLFW callback lost the rest of the poll: the frame re-reads keys and buttons
from the OS, `test_input_frames.TestARaisingPollKeepsInputTrue`) and S1-11
(cleanup forgets the terminated window: `test_run_cleanup`).

Lessons:
- A cache keyed on a list must not outlive the list's entries: the first phase
  snapshot held the dropped handlers' sides until the next dispatch, and the
  holders scan (`test_sys_holders`) caught it. Clear it where the list loses
  entries.
- A precision test needs a tolerance tighter than the bug: 1e-6 relative passed
  the float32 path (0.05 at 1e6); 1e-9 does not.
- A canary plants a bug by disabling one function. When a fix adds a second
  path to the same result, the plant stops biting: the S6 canary disabled
  `_forget_pair_target`, and the new tag retirement pruned the dead side anyway;
  the cull canary patched `_passes_cull`, and the draw loop now calls
  `_cull_keeps`. A refactor that moves or duplicates a guarded step runs the gate
  canaries and plants on every door.
- A census key that counts a by-design keeper (an auto-created numeric layer)
  must be excused, with its reason, in the traces that build and remove things.

### RV8 — writers × time (2026-10-09)

The cross-cutting pass the review had to stop, finished by three reviewers
(geometry writers, pointer composition, uneven pacing). The collision cache
held (123 kind × writer cases); every finding is a reader that ran before a
writer later in the frame, or a total that depended on the frame cut.

| ID | Finding | Fix | Test |
| --- | --- | --- | --- |
| W-T1 | a frame longer than a lap dropped laps (`%`) | every whole lap counts, capped by the laps left | `test_uneven_pacing.TestTweenLaps` |
| W-T3 | `every` fired one past its budget after `%` | a remainder a hair under the interval is the boundary | `TestEveryBound` |
| W-T4 | `Handle.elapsed` / `.remaining` lap-local on `loops=N` | run totals | `TestHandleClockCountsTheRun` |
| W-T6 | Endless fell behind a camera moved after its fill | a second fill after the tick when the view moved | `TestScrollAndFill` |
| W-T7 | a scrolling layer lost its first frame | the scroll clock starts at the layer's birth | same class |
| W-G1 | a handler's respawn was invisible to that step's resolve | movable bodies refresh after author code ran | `test_same_frame_writers.TestHandlerWritesReachResolve` |
| W-G2 | queries did not poll a linked `hb["active"]` (declared tag, `ANYTHING`, main hitbox) | every query polls | `TestQueriesPollLinkedHitboxes` |
| W-G3 / X-w-5 | cull and `.box` measured a stale linked pose | `_approx_draw_aabb` and `region_frame` pull | `TestMeasuringReadersPull` |
| W-G4 | Portal's collision key missed `tilt` / `angle` | `Portal._point_frame` | `TestPortalKey` |
| X-w-3 | timed zoom was linear (doc: geometric) | `_zoom_lerp` | `TestTimedZoomIsGeometric` |
| X-w-4 | `center =` / `.x =` / `<<` after `move_by` kept the sweep | author placement clears pending motion | `TestPlacementEndsTheSweep` |
| W-P1 | pointer sampled before a camera move in `update` / a tween | sampled again after the tick when the camera moved | `TestPointerFollowsTheCamera` |
| W-P4 | `on_key` repeats for a key pressed under a modal | `on_key` follows the script-down door | `test_input_frames.TestKeyStreamsFollowTheScriptDown` |
| W-P5 | after a lost release the drag went on | the S1-9 recovery ends every press owner | `TestALostReleaseEndsTheDrag` |

New class: **a level sampled before a writer later in the same frame** (W-P1,
W-G1, W-G2, W-G3, W-T6). Guard: every reader of a level the frame can still
change (pointer, proxies, linked switches, measured poses, a fill) either runs
after the last writer or re-reads when the writer ran; the tests above write in
`update()`, in a handler and in a timer, then read in the same frame.

Perf: the first W-G1 fix refreshed every resolve side after any handler (+42 %
with 200 static tiles and a stay handler); the shipped one refreshes only the
movable bodies resolve already lists. The placement hook costs ~37 ns per author
point write (`center.x +=`), ~0.6 % of a frame with 400 such writes; a detector
at commit time cannot tell a placement after a move from one before it.

Decisions left to the author (report section 8): W-P3, W-T2, W-T5, W-T8, W-T9,
X-writers-2.

### RV9 — decisions applied (2026-10-09)

The seven open items of the review, decided by the author and applied.

| ID | Decision | Implementation | Test |
| --- | --- | --- | --- |
| S9-1 | a group's member on `ui` / parallax is skipped in both orders; a named actor raises | `_assert_named_sides_not_parallax`; `_try_enroll_item` / `_colliders_for_shapes` skip | `test_parallax_layers.TestGuardsCollisionAllOrNothing` |
| W-P3 | the drag is a level | `ShapeManager.reapply_drag` after the tick | `test_input_frames.TestTheDragIsALevel` |
| W-T2 | `ready` carries its overshoot, no burst; `after` / `wait` re-arms documented | `_ready_poll` | `test_uneven_pacing.TestDecidedClocks` |
| W-T5 | a turn over 16° is swept as an arc | `_note_orbit_path`, `_toi_along_paths` | same class |
| W-T8 | background-field scroll is world state | `BackgroundStack._advance_scroll_all` in the frame body | same class |
| W-T9 | SpatialFx: the world's `MAX_FRAME_DT`, sub-stepped at 0.1 s | `tick_all_spatial_fx` | same class |
| X-writers-2 | shake / flash / glitch decay on presentation time | `PostFxStack._render` | same class |

### DS2 — deep serial pass after the systems review (2026-10-09)

The parallel half of the deep tier passed (244 jobs); the serial pass (every
module in one process) failed 12 tests in three groups. All three are order
effects the per-module processes cannot see.

| Failure | Cause | Fix |
| --- | --- | --- |
| 10 `canvas.game_view` cells of `test_reactive_cross_matrix` | `init_scena_system()` (called by `test_diff_reactive`) rebound a hand list of formula sources (`keyp`, `mouse`, `clock`); the `canvas` facade, a source since RX1, kept the discarded graph | the rebind walks every Container in `builtins` (`state._rebind_input_singletons`); `test_reactive_edge_cases.TestGraphResetRebindsEverySource` |
| `test_hyp_reactive_matrix` Vec2 canary | the machine's steps depend on object addresses, not only on the seed: after other imports (`tools/guide` modules) it missed the plant at 150 examples; at 300 it missed it in a bare process | `assert_catches(profile=(...))` tries 150, 300, then 600 examples; the plant must be caught at one of them |
| `test_cull.TestCullDrawLoop` (new in RV7) | the draw counted leftovers other modules left on `default` | the test draws a layer of its own |

Lessons:
- A rebind (or reset) list of "the long-lived ones" is a hand-kept list:
  walk the place they live.
- A test that counts what a draw or a query sees must own the space it
  counts (its own layer or group), or the serial pass's leftovers change it.
- A canary on a Hypothesis machine whose path depends on addresses needs
  an escalating budget, or it is green or red by import order.

### F — contact flicker (2026-09-29)

Found by `tests/test_sys_resting_contact.py`, written after G2 to test what a
player sees (a resting or walking body) instead of float tangency. F1 fixed; F2
accepted as a limitation (user decision 2026-09-29).

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| F1 | `@collide` on a pair that is also `resolve()`d flickered with frame time. 60 Hz: steady. 200 Hz: a resting body read as not touching after landing. Alternating 5 / 28 ms: enter / exit every other frame (238 events in 240 frames); walking re-entered every tile. Same at offset 65536 (not precision). `touching_sides` was steady throughout | `Rect` hero on a `STATIC` tile, `resolve("hero", "tile", bounce=0.0)` + `@collide` / `@collide_exit`, gravity by `move_by`, `dt = 0.005` | `@collide` reads the detection snapshot, taken before resolve; the sweep parks the body `_RESOLVE_SLOP` (0.08) short of the floor, so it overlapped only when that frame's fall g·dt² beat the slop. The `_RESOLVE_SLOP` comment even claimed it was residual *overlap* that prevented stay / exit flicker | `test_sys_resting_contact.TestCollideDoesNotFlicker` (rect and circle × 60 / 144 / 200 Hz and 5 / 28 ms × offsets 0 / 65536, resting and walking 12 tiles; `test_skin_is_what_keeps_the_resting_contact` patches the skin to 0 and expects the flicker back); `test_collision.TestRestingContactSkin` (inside / beyond the skin, exit past it, sensors and `resolve_enabled = False` strict, payload, true gap vs AABB on a 45° box, `_prim_gap` closed forms vs GJK). Fix (user decision 2026-09-29): a standing resolve pair within `_CONTACT_SKIN` = 2 × slop is a contact ([Collision Design — Resting contact (skin)](Collision%20Design.md#resting-contact-skin)) |
| F2 | **Accepted limitation, engine unchanged (by design).** A circle walking over touching tiles with alternating 5 / 28 ms frames enters / exits the *next* tile every other frame while within ~2 DU of the seam. Rects, resting bodies and steady 60 / 144 / 200 Hz are clean after F1 | Circle r=8 hero, 12 touching 16×16 `STATIC` tiles, `resolve(..., bounce=0.0)`, `vx = 60`, `dt` alternating 0.005 / 0.028 | `@collide` reads the pre-resolve pose, which sinks by g·dt² (0.6 DU on 28 ms, none on 5 ms); against the next tile's corner the gap swings across any fixed skin. Fixing it means judging resolved pairs on the resolved pose: splits the frame-order rule, drops the enter `depth`, breaks same-frame policy in `@collide_stay`. Needs four conditions at once (curved body, seam, uneven pacing, per-tile enter / exit); the standing tile keeps its contact | `TestCollideDoesNotFlicker.test_curved_body_on_seams_with_uneven_frames` stays `expectedFailure` as a tripwire. Mitigation: the Guia teaches `touching_contacts` for "which tile am I on" ([Tocando](../docs/pt/guide/index.html#colisao-touching), "Não confundir" row); fence in [Collision Design — Resting contact (skin)](Collision%20Design.md#resting-contact-skin) |

### W — world machine extensions (M4)

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| W2 | `@=` onto a destroyed actor was accepted and put it back in the dependency graph (4 nodes) — ink cell, slot, property anchor (`rotation` / `scale`) and a held part (`dead.center @=`) | `c.destroy(); c["mirror"] @= (lambda: 1)` | No dead check on the link entry points; destroy cut the part's owner edge, so a part could not see its dead host | `test_reactive_edge_cases.TestNoLinkOntoADestroyedActor`; `test_hyp_surface.TestDeadEntityLinks` (P6 for `@=`, every kind × every field); world `link` rule asserts the outcome; canary `test_w2_link_onto_a_dead_actor`. Fix: `state._refuse_link_on_dead` in `Container.__imatmul__`, `Container._link_field`, `Graphic._link_field`; destroy marks parts `_host_destroyed` |
| W3 | A formula that raised on its first evaluation still created the ink cell (`a.mirror` read `0.0` afterwards) and a scalar anchor node | `a["mirror"] @= (lambda: b.hp + 1)` with no `b.hp` | Cell / anchor created before `_assign_formula` evaluated | `test_reactive_edge_cases.TestFailedLinkInstallsNothing`. Fix: roll back the anchor (`Container._link_field`) and the ink cell (`Entity._link_field`; `_ink` is a slot, not `__dict__`) |
| W4 | A part's work outlived its host: `line.p1.play_sound(x, loops="forever")` / `p1.after` / `p1.every` kept running after `line.destroy()`, and after an act change (parts are not in the doomed batch) (2026-09-29) | `l = Line(); l.p1.every(0.1, f); l.destroy()` | Destroy keeps parts as readable values (W2) but only ended the host's own scheduler work | `test_audio.TestSoundRingsOut` ("host destroy" row of the fate matrix; `test_part_work_ends_with_its_host`); `test_act.TestActSoundsRingOut.test_a_part_loop_of_an_act_object_stops_on_the_change`. Fix: `Registry._destroy_teardown_body` runs `cancel_owner(part, release=True)` for every part in the subtree that owns work |
| P1 | A part outlived its destroyed owner in every registry list: `line.show_handles(); line.destroy()` left `p1` / `p2` alive, ownerless, drawn on `top` and draggable forever (the layer list held them); hidden parts stayed in the roster until GC; a tagged part stayed in its group; a dead part could be shown again; a failed constructor left its parts registered (2026-09-29) | `ln = Line(); ln.show_handles(); ln.destroy()` | `Registry.destroy` and the rollback took only the owner out; `Container._clean_up` walked parts for the graph only. Hidden behind ids: the old census skipped `_auto_` ids | `test_part_lifecycle` (every family × hidden / handles / visible; rollback; tags refused); `test_hyp_canvas` invariant `parts_follow_their_owner` + `show_handles` rule; canary `test_p1_part_outlives_its_owner`. Fix: `Registry.retire_part` from `_destroy_teardown_body` and `place._drop_failed_construct`. Design change with it: parts have no tags (`Entity._refuse_part_tags`) |
| P2 | A part acted as an actor (design bug, 2026-09-29): `c.center.collidable = True` / `@collide(c.center, …)` / `resolve(line.p2, wall)` made a Point body (handlers got the Point; `resolve` kept only the centre out, so the disc overlapped the wall, and stretched a Line; owner and part fired twice; a parked owner's part kept colliding); `c.center.destroy()` left a live Circle moving on a dead centre; `top.clear(hard=True)` destroyed shown handles the same way | `c = Circle(); c.center.destroy(); c.move_by(5, 0)` | Parts are Entities, so every actor verb applied to them; `_drain_layer` destroyed whatever was drawn | `test_part_lifecycle.TestPartIsNotABody` (every family × every body verb, incl. list sides and `Collider([...])`; queries stay allowed), `TestPartLivesWithItsOwner` (`destroy` / `active`; hard clear undraws a foreign owner's handles, retires its own). Fix: `entity.refuse_part_as_actor` at each entry point (`_check_pair_sides`, `collidable`, `on_collide*`, `destroy`, `active`, registered `Collider`), backstop in `ensure_collider`; `_drain_layer` undraws parts |
| P3 | A parked owner's shown handles kept drawing and stayed draggable: dragging one moved the parked shape; a part's own timers kept running (2026-09-29) | `ln = Line(); ln.show_handles(); ln.active = False` | Park stashed and hid only the owner | `test_part_lifecycle.TestPartParksWithOwner` (every family × handles / visible part; handle changes while parked; timers; destroy while parked); `test_hyp_canvas` invariant `parts_follow_their_owner` (part `active` follows the owner; a parked owner's parts are on no layer or pointer list). Fix: `Entity.active` runs `_park_self` / `_resume_self` on the owner and each part |

W1 (a Sprite's hitbox part outliving its host) was withdrawn: the probe script's own variable held the sprite (the "your own references" pitfall); the engine skips dead-host parts (`hb.is_alive`). The machine now checks it (`hitbox_parts_die_with_their_host`).

Reach guard (`TestWorldMachineReach`, 2026-09-28): `link_then_kill_source` replaces dead or repeated picks with fresh Circles, and after the source dies it re-links from it to check the W2 refusal. Every `REQUIRED` counter stayed ≥ 9 on each of the 20 measured seeds. The guard asserts each is ≥ `MIN_HITS` (3). The guard runs `derandomize=True` without a pinned seed. See [Harness pitfalls](#harness-pitfalls) ("A `derandomize=True` reach guard…") for the measurements and why neither `@seed` nor a larger `max_examples` was used.

### D — differential (fast vs slow paths)

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| D1 | Object counts included tombstones (also inflated the leak detector's entity count) | 3 circles on a layer, destroy 1, undraw 1 → `layers.list()` says 3 | `list_info` counted `len(layer.objects)`; `_count_registry_objects` counted `None` (not a `Point`); both keep holes until `compact()` | `test_registry_layers.TestLiveCountsIgnoreTombstones` (incl. structural guard: no `len(<x>.objects)` outside `Layer`; use `Layer._live_count`), `test_leak_detector.TestRegistryObjectCount` |
| D2 | A `Polygon` collided **where it had been**, not where it was | Collider sees polygon at A; translate to B (fast path); move back to A and rotate +10 / −10 (forces a rebuild) → engine reports it at B | `_translate_prims` shifts prims **in place**; `_poly_cache` stored the same Prim objects under the old vertex key, so a rebuild that landed on A returned the shifted prims. Reachable from `snapshot_shape` and `_world_prims` | `test_collision.TestPolygonCacheAliasing` (unit, engine-level, and the class guard: no returned Prim is an object a cache keeps). Fix: `_poly_cache` stores and returns clones (`_clone_prims`); worst case +1.5 % step time with 200 polygons rebuilt every frame |
| D3 | Drawn / collidable shapes lost the pose fast path **for good** (performance) | 12 of 24 models: e.g. `Polygon`, `Circle(p1=, p2=)`, `Ellipse(fp1=, fp2=)` warmed by draw / cull / collision; `Square` / `Rect` spine / `Line` by pose verbs | Engine readers and verbs read cold Derivates (`center`, `radius`, `rotation`, `width`, `angle`, `p1`/`p2`), which materializes them and sets the sticky `_needs_pull_invalidate` | `test_diff_pose.TestEngineReadersStayCold` (reader × model and verb × model matrices; allowlists now empty). Fix: every engine reader / verb goes through Defining helpers — `_center_xy` (+ Polygon vertex average), `_radius_value`, `_rotation_value`, `Rect._wh_signed`, Ellipse focal `_oriented_frame`, Line `_segment_xy`; collision pose position via `_center_xy`. Move + rotate + draw of those shapes: 26–40 % less per frame; CENTER_RADIUS circles keep a direct fast branch in the collision proxy (no regression) |
| D4 | Conservative-advancement sweeps stopped **inside** the obstacle | unit box moving −3 in x into an axis-aligned OBB: first contact t = 0.667, sweep said 0.903 (0.7 deep) | `_gjk_distance` reused the intersection GJK, which returns as soon as separation is proven; the closest point of that unfinished simplex overestimates the gap (3.07 vs 2.0), and advancement trusts it as a lower bound | `test_collision.TestGjkDistanceIsAMinimum`; `test_diff_collision.TestSweepsAgainstSampling` (brute-force sampled sweep oracle). Fix: `_gjk_refine_closest` runs the GJK distance loop to convergence |
| D5 | OBB / POLY support points were up to 0.5 short of the furthest vertex | box sweeping up into a circle: t = 0.533 vs 0.500 | `_prim_support_ex` kept the FIRST vertex within `tie_eps = 0.5` of the running best (meant only to COUNT face ties) and returned it as the support; GJK, EPA, projections and bisection read it | `test_collision.TestSupportIsTheTrueArgmax`. Fix: `_support_and_ties` returns the true argmax, ties still counted within `tie_eps`; all 268 collision tests (resolve, ramps) unchanged |
| D6 | Leaving a group kept the pair targets that group implied | `@collide("a","b")`; body in `a` untags `a` → `_pair_targets` still `['b']` | `notify_group_remove` dropped the tag-list entry, never revisited targets (S6's class via untag). No wrong fire; wasted narrow phase if later tagged into the stale target's group | `test_collision.TestUntagPrunesPairTargets`; `test_diff_collision.TestIncrementalEnroll` (targets vs the set the registered pairs imply). Fix: `_prune_pair_targets` on untag |
| D8 | `unlink()` froze a **stale** value (and so did destroy's auto-unlink) | `b @= a`; `a = 1` (unread); `b.unlink()` → `b` is 0 | pull reactivity: the write only marked `b` dirty; unlink cleared the link without pulling | `test_reactive_edge_cases.TestUnlinkFreezesTheCurrentValue`; `test_diff_reactive` (`chain` op + link model). Fix: `unlink` pulls first; `destroy()` pulls outside dependents after `on_destroy`, before the source reads as dead (formula errors re-raise after teardown). R6: the first version pulled during teardown and raised `DestroyedError`; `test_sys_lifetime` encoded the stale value and was updated (Reactive Design — External dependents). No measurable destroy-churn cost |
| D7 | Park → `collidable = True` while parked → resume: body active + collidable + tagged but absent from the `@collide` tag index (handlers never fired again); `visible = True` while parked drew a parked actor | spawn in `a`; `active = False`; `collidable = True`; `active = True` → no `@collide` | Resume restored a flag that was already True (setter no-op → no re-enroll); flag writes during park applied immediately | `test_diff_collision.TestIncrementalEnroll` (index vs rebuild) found it; `test_process.TestParkStashesFlagWrites`. Fix: resume re-enrolls (landed in parallel) + **contract (user decision 2026-09-26): writes while parked update the stash**; reads report the current state; draw / hit walks use `_drawn` |
| D9 | Culling dropped visible corners of thick-stroked sharp shapes | Rect rotated 20°, `line_width=3`, just left of the view: half-stroke pad ends 0.04 outside, the miter corner is 0.4 inside | The cull pad added half the stroke; a miter join reaches `hw / sin(θ/2)` past a corner (sqrt(2) on a rectangle; up to the miter limit 4 on polygons — sharper tips are beveled and reach less); square caps sqrt(2) | `test_cull.TestCullCoversMiterJoins`; `test_diff_draw.TestCullIsConservative`. Fix: `_stroke_reach_factor`. Mechanism verified against Skia's stroked bounds before fixing (lesson 12) |
| D10 | **Harness bug, no engine change.** `TestSnapshotCaches` reported a Circle arc's cached prims diverging from uncached (`-8.94 vs 0.0`) | `Circle(center=(1, 2), radius=9, angle=110, spread=180)`; `move_by(-27, 3, face=True)`; `move_to(0, 0)` | The cache was right: the translate path matched a rebuild to 1 ulp. The oracle sorted prims by raw floats; the two wedges tie on `aabb` min-x (shared split vertex), the ulp flipped their order, and `assert_same` compared wedge A with wedge B. The suspected A→B→A key bug was not there: `move_face` changes the angle, which is in the pose key extra | `test_diff_collision.TestPrimsOracle` (fails on the sorted compare; class guard over every model with built ties; canary `test_oracle_guard_catches_a_sorted_compare`); `@example` on the property; engine pin `test_collision.TestArcSnapshotAfterFaceMove` (translate path serves `move_to`, multiset match). Fix: `diff_support.assert_same_prims` |
| D11 | A point read off a fresh measuring Box entered the reactive graph, and only the cyclic GC took it out: read every frame, the node count climbed until the leak detector warned "reactive graph rising … possible orphaned Container" | `r = Rect(center=(0, 0), width=10, height=5)`; 50 × `r.box.center` → +22 graph nodes, 0 after `gc.collect()`. `scripts/smoke/box.py` Stamp page: +11 400 nodes in 300 frames (grid cells, `panel.box.center`); Parents page (`canvas.game_view.center`): +3 000 | A materialized Point part registers a node, and its structural edge registers the Box. Every Container tree is a reference cycle (`_owner` ↔ `parts`, a self-inclusive `_subtree_cache`), so the WeakValueDictionary graph drops those nodes at a full collection only — rare after `freeze_world`. Scalars (`box.width`) build no part, so they never showed it. Two fixes: a measured Box (`Box._snapshot`, now also `game_view` / `ui_view` / `group[...].box` / `widget.box` / playfield copies via `Box._from_aabb`) keeps its part tree off the graph until something links into it ([Reactive Design — Deferred trees](Reactive%20Design.md#deferred-trees-measured-boxes)); and the leak detector recounts after one `gc.collect()` before it warns (churn one collection gives back is not a leak — an author's per-frame `Point(...)` or `Box(center=…)` still churns) | `test_box_snapshot.TestMeasuredPointsStayOffGraph` (every named point of Rect / Circle / Sprite / Text boxes, layout children, grid cells, views, group box, playfield copies: node count flat with the cyclic GC **off**); `TestDeferredTreeStaysCorrect` (writes after corner reads match an eager twin; a link from / into a measured Box wires it and follows); `test_leak_detector.TestGcChurnIsNotALeak` (per-frame author `Box` churn does not warn; held Boxes still do) + `TestLeakSampler.test_recount_*`. The `scripts/smoke/geometry.py` workaround (rebuild points from box scalars) was reverted. Class: **A per-frame throwaway enters the graph** |
| D12 | A Vec2 linked whole read a stale `length` / `angle`: 0.0 (never computed) or the value from before the link, and so did a link reading it. Same for an owned Vec2 linked per axis (`rect.vec["x"] @= …`) once the owner refreshed, and for the Derivate `vec` of a `corner_corner` Rect / Box after a `p2` write | `v @= lambda: vec_from_angle(st.a, 10)` → `v.length` 0.0; `z = Vec2(lambda: (w.length, 0))` stayed 0 | The pull stores x / y through `_takein_impl` ("Pull stores raw"), which skips `_update_impl`; the linked-clean read shortcut (`ScalarSlot.__get__`, Tier 1.6) returned the stored Derivate or the slot default | `test_derivate_readonly.TestLinkedVec2ComputedFieldsFollow` (lambda → Vec2 / tuple, read before / after the link, a chained link). Fix: `Vec2._sync_computed` after every raw x / y store (`Vec2._takein_impl`, and `ScalarAnchor._takein_impl` through the `Container._sync_computed` hook); the shortcut needs the name stored; `_refresh_scalar` computes a Derivate of a linked leaf on first read. A raw store must keep the node's own Derivates in step. Class guard: `test_diff_link_write` |
| D13 | A linked field froze until its next source change when a Derivate was read first: `r["hp"] @= lambda: st.x`; `st.x = 2`; `r.width` → `r.hp` still the old value (Rect, Square, Line, Ellipse, Polygon, Track, Circle `spread`) | `c["spread"] @= …`; change; `c.p1.x` → `c.spread` old | An owner's refresh (`_resolve_structural`, `_resolve_link`, `DirectLink.evaluate_and_update`) cleared `_dirty` on its whole subtree, the `ScalarAnchor` of a linked field included; a linked node pulls only when dirty, and the owner's `_update_impl` never read that field | `test_diff_link_write.TestLinkedInkFollows` (every kind × a Derivate read), `TestLinkReadsLikeWrite`. Fix: `Container._clear_subtree_dirty` leaves a part with its own link dirty |
| D14 | A link on Track `begin` / `end` stored values outside 0..1 (`t.begin` read 3.25; `=` clamps to 1.0); drawing clamped again, so only reads differed | `t["begin"] @= lambda: st.b`; `st.b = 3.25` | `Track._write_field` clamps; the link path (`ScalarAnchor._takein_impl`) only knew a slot's `maximum` | `test_diff_link_write.TestLinkedTrackWindowClamps`. Fix: `ScalarSlot(minimum=, maximum=)` clamps a pulled value; Track `begin` / `end` declare 0..1 |
| D15 | `v @= lambda: st.pos` and `v << st.pos`, with `st.pos` holding a tuple or a Vec2, raised `TypeError` on a Vec2, a Point and a shape's point part | `st.pos = (1, 2)`; `Vec2(0, 0) << st.pos` | `Vec2._takein_impl` / `Point._takein_impl` read the pair from the cell itself; scalar fields already unwrapped a cell | `test_diff_link_write.TestCellHoldingAPair`. Fix: both unwrap an `Attribute` to its value |
| D16 | A link into a field with no magnitude limit (`x`, `y`, `angle`, Track `begin` / `end` / `u`) stored NaN / inf: `=` raises `ValueError` "must be a finite number", a magnitude field's link already refused it | `st.a = float('nan')`; `p = Point(0, 0)`; `p["x"] @= lambda: st.a`; `p.x` → nan | `ScalarAnchor._takein_impl` applied the slot's magnitude and min / max limits but no finiteness check to non-magnitude slots | Tests linked finite values and out-of-range values; none linked a non-finite one | `test_reactive_matrix` (`run_range_cell` below / above / nan over every scalar field of every subject). Fix: one `-inf < v < inf` test on a float in the pull (A/B in one process: −0.3 %, noise). A pair store (`p << (nan, 0)`, `v @= lambda: pair`) stays unchecked on purpose, like `=` on a pair: vector math produces NaN legitimately |
| D17 | On a `Line(p1, p2)` (or `p1,vec`, `p1,dx,dy`), `ln["angle"] @= f` then `ln["p1"] @= g` installed both; every later read of `angle` raised `LinkedAttributeError` ("Cannot rotate_by … its p1 has an @= formula"), and unlinking raised too. The refusal came at the read, not at the `@=` | `ln = Line(p1=(0, 0), p2=(3, 4))`; `ln["angle"] @= lambda: st.a`; `ln["p1"] @= lambda: (st.b, 0)`; `ln.angle` | A derived heading links through a property anchor that drives `rotate_to`; `rotate_to` refuses a part with its own formula, but nothing told the link install about the parts it rewrites (draggable / `wheel_rotate` / `resolve()` are checked at install) | The generated machine was the first code to link `angle` and a point on one Line | `test_heading_link` (both orders refused at the `@=`, the failed link installs nothing, and `Line._heading_driven_parts` equals what `rotate_by` refuses, in both directions). Fix: `_DerivedRotationRoute` refuses the second link (`_refuse_heading_link_over_linked_parts`, `_ensure_can_link_attribute`) from `Line._heading_driven_parts`. Circle-by-rim, Ellipse-by-foci and Rect-spine headings return `()` until they have a subject |
| D18 | A shape with a linked, derived heading (`ln["angle"] @= f` on a `p1,p2` / `p1,vec` Line, a Circle by its rim, an Ellipse by its foci, a Rect spine) read stale geometry when the points were read BEFORE `angle` after the source moved: `p2` still (5, 0) where `ln.angle = -180` gives (0, 0), and so did `vec`, `dx`, `center` | `ln = Line(p1=(0, 0), p2=(5, 0))`; `ln["angle"] @= lambda: 360 * st.t - 180`; `st.t = 0`; `ln.p2` | The link drives `rotate_to` through a property anchor that only runs when pulled. `p1` / `p2` are Defining, and a clean Defining read does not walk to the shape (Reactive Design, "Difficult areas"); Derivates built from them were read from a clean owner. Reading `angle` first (a sorted read) hid it. The first fix attempt pulled inside the shape's own update batch, where `angle` is stored and not applied, and marked the anchor clean on top | The matrix read names in sorted order, so `angle` always came first; the generated machine reads in any order | `test_heading_link` (`TestDerivedHeadingLinkIsFresh`: every name read first, on every derived-heading kind), `test_reactive_matrix_cells` (reversed post-move reads), `test_reactive_matrix` (canary on `_pull_heading`). Fix: `_pull_heading` applies a pending heading before a structural resolve or a Derivate materialization, never inside the batch; the points the turn rewrites carry `_pull_owner`, so their reads (classified once, off the bare fast path) pull their owner. No cost on a plain Defining read. Class: **a Derivate read before the Defining field that drives it** |
| D19 | A whole-object link (`d @= s` or `d @= lambda: s`, every shape kind) refreshed `d`'s Defining inputs but not the Derivates already read: after `s.width = 10`, `d.top_right` stayed where it was. A Track copy also dropped `u` | `s = Rect(center=(0, 0), width=4, height=2)`; `d = Rect(…)`; `d @= s`; `d.top_right`; `s.width = 10`; `d.top_right` → (2, 1), want (5, 1) | The pull stores through `_takein_impl` (Defining parts only, inside `_no_update`) and then marks the whole subtree clean; no `_update_impl` ran, so live Derivates kept their values | The matrix linked fields and parts, never a whole shape | `test_reactive_matrix_cells.TestWholeObjectLink` (every subject × field × direct / formula × read order; canary on `_refresh_after_raw_store`). Fix: `Container._refresh_after_raw_store` runs the node's own `_update_impl` after the raw store, in `_resolve_link` and `FormulaLink.evaluate_and_update`, only for nodes with parts (leaf sinks keep their fast path) |
| D20 | `box << other_box` and `box @= other_box` raised `NotImplementedError`: Box had no `_takein_impl` | `Box(center=(0, 0), width=4, height=2) << Box(p1=(0, 0), p2=(6, 3))` | Box copies Rect's model code but not its copy hook; `Container._takein_impl` is a plain method, so the missing override was silent until called | No test copied a Box | `test_reactive_matrix.TestCopyAcrossModels` (every pair of Box models, `test_box_takes_only_a_box`). Fix: `Box._takein_impl` (model, Defining set and names, like Rect); a non-Box source raises TypeError naming `Box(shape)` |
| D21 | A copy across construction models (`d << s` where `d` and `s` were built differently) set `model` but kept `d`'s old Defining set: 129 of 186 cross-model copies read wrong (stale sizes, centers, points) and refused writes to the new inputs (`dst.p2 = …` raised DerivedAttributeError). A Track copy kept drawing its own preset / circle and dropped the pose; `reversed_view << t` changed nothing | `dst = Rect(center=(10, 10), width=2, height=2)`; `dst << Rect(p1=(0, 0), p2=(4, 3))`; `dst.width` → 2, want 4 | Six `_takein_impl` wrote `self.model = other.model` and nothing else about the model; the parts that turned Derivate had been built as inputs, so the update never refreshed them | Copies were tested within one model (`clone()`, C7) | `test_reactive_matrix.TestCopyAcrossModels` (every ordered pair of models of each kind; canary on `_adopt_model_of`). Fix: `Container._adopt_model_of` sets the model and the target's own Defining set for it (`_defining_names_for`: a Rect taking a Square uses width / height), marks parts that turned Derivate live, and drops the bare-read caches. A Track copy becomes a free points track (no preset, no live source) with the source's pose; a `reversed()` view refuses a copy. RegularPolygon still refuses a different `n` |
| D22 | The same field obeyed different rules on different paths: a constructor stored NaN in a non-size field (`Rect(…, angle=nan)`, `Line(dx=nan)`, `Point(nan, 0)`) where `=` raised; Line `length` raised inside a batch where every other size clamped; `track.begin = fn` and a derived heading's `angle = fn` raised a plain TypeError instead of CallableAssignError | `Rect(center=(0, 0), width=2, height=2, angle=float('nan')).angle` → nan | Rules lived in per-class `_write_field` overrides (Line, Circle, RegularPolygon, Track) that only author writes ran; `_init_scalar` checked only sizes; min / max were honoured only by links | Each path was tested on its own | `test_reactive_matrix.TestOneCoercionForEveryPath` (constructor refuses what `=` refuses, a function assigned names the link, a batch clamps a negative size, every `_write_field` override allowlisted). Fix: rules on `ScalarSlot` (`label`, `out_of_range`, `_kind`) and one coercion for `=`, constructor, batch and link (Track C item 1). Writes of Line / RegularPolygon fields got 10 % faster (no override) |
| D23 | A Box placed by `top_left` ignored mirrored corner names (a copy or a flip's): its center, every named point and a `rotate_by` came out where an unmirrored box would be, while a Rect with the same names was right | `b = Box(top_left=(0, 0), width=4, height=2, angle=30)`; names `(-1, 1)`; `b.rotate_by(10)`; `b.top_left` ≠ Rect's | Box carried a near-copy (~300 lines) of Rect's frame model; Rect's later fix (`_top_left_offset`) never reached the copy | Box and Rect were tested apart | `test_rect_frame` (Box reads like Rect over every model × name signs, before and after a turn; neither class re-defines the shared methods). Fix: `_RectFrame` mixin (Track C item 4); Box's `rotate_by` uses the named offset. Box's `rotate_by` stays unbatched: `@batch_update_self` cost +45 % there |
| D24 | About twenty private helpers turned a value into `(x, y)` with their own rules: `p << [1, 2]` raised while `v << [1, 2]` worked; tween destinations, Track, group and collision queries read the first two items of `(1, 2, 3)`; `(True, 0)` was a point in `get_xy` and `v + (True, 0)`; `v << ("1", "2")` parsed text; a state cell holding a pair worked in `p << st.c` but not in `p + st.c`; the Vec2 operand error offered a Point that it then refused | `Point(0, 0) << [1, 2]` → TypeError; `Vec2(0, 0) << ("1", "2")` → Vec2(1, 2) | Each module kept its own `_as_xy` (the `scenamath` copy even said "not a package-wide unification") | Each entry was tested with its own module's inputs | `test_pair_reading` (every entry × tuple / list / cell accepted, three items / bool / one item / text refused; Vec2 and Point messages; a delta refuses a Graphic). Fix: `_xy_of` / `_read_xy` / `_pair_numbers` are the one reading (Track C item 3); the copies delegate. Tuple reads got 20–50 % faster (an exact-number fast path) |
| D25 | A direct link to a centred Text's `center` (`q @= text.center`) stayed put after `text.move_by` / `move_to`: Text wrote its centre with the raw float pose path and no gate | `t = Text("hi", center=(10, 10))`; `q @= t.center`; `t.move_by(5, 7)`; `q` → (10, 10) | Hazard #8 (Reactive Design) had a rule and no check: Text's moves, anchor shift and layout publish called `_takein_xy_float` unconditionally | Pose-link tests covered shapes and Sprite, not Text | `test_write_path_guards` (every raw pose write is gated; `TestTextLinksFollowAMove`). Fix: Text notifies when the point is a link source (`_link_source`, set by `_note_became_link_source`); the raw path stays for unlinked captions (A/B within noise) |
| D26 | A direct link to an *anchored* caption's `center` (`Text("hi", top_left=…)`; `q @= t.center`) read the old centre after a move, `text =` or a formula string change, until something read the caption (10 of 64 placement × part × change cases) | `t = Text("hi", top_left=(10, 10))`; `q @= t.center`; `t.move_by(5, 7)`; `q` → old centre | The layout is lazy (width inputs never notify; it runs on draw and on reads through `_TextPartSlot`); the anchored centre is written by it, not by a source of `q`, and a DirectLink copies the Point without reading through the caption | The pose-link and Text tests read the caption before the link | `test_write_path_guards.TestTextLinksFollowAMove` (every placement × part × change, the link read first). Fix: when an anchored caption's `center` first becomes a link source (`_part_became_link_source`, called by `_note_became_link_source`), it depends on the caption and its reads pull the caption first (`_pull_owner`), as a derived heading does (D18). Unlinked captions are unchanged |

### B — bench pulse findings

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| B1 | Every **read** of a linked Point re-walked its whole dependent cone (performance; values stayed correct). `graph-1` sierpinski 7.07 → 14.64 ms, draw 5.0 → 12.6 ms; landed between 09-24 and 09-26 | `a → m @= f(a)`; `a.move_to(…)`; reading `m.x` calls `mark_dirty` once (should be 0); ×729 Lines per frame at depth 5 | The `takein` → `_takein` / `_takein` → `_takein_impl` rename: `Container._resolve_link` (both branches) and `DirectLink.evaluate_and_update` (container branch) kept calling `_takein`, which now names the invalidating dispatcher, not the raw store. `TestDeepBinaryTree` ceilings had been raised 46 → 107 to fit it | `tests/test_pull_no_invalidate.py`: `mark_dirty` count during reads per sink kind (0), one walk per write on a midpoint tree, downstream-fresh twins, AST guard `TestPullResolversStoreRaw` (resolvers and `_no_update` blocks in `evaluate_and_update` never call `_takein`; vacuity-guarded); `DEEP_MARK_DIRTY_CEILING` back to 46. Mutation-checked: reverting the fix fails 6 of 10 |
| B2 | Per-frame verbs paid the full validator path for a plain `float` (performance). `balanced-2` cpu_mix tick 1.10 → 1.40 ms (scheduler `_tick_on_update`: author `on_update` bodies); `move_by` 1.19 → 2.25 µs, `rotation =` 0.86 → 1.21 µs | `c.move_by(0.1, -0.1)` in a loop; `validate.finite` ×2 per call, `_finite_deg` ×3 per `rotation =` | A3–A8 correctly routed verbs through `validate.finite` / `_finite_deg`, but a plain float took two `callable` probes, `as_payload` and an ABC `isinstance(numbers.Real)` (Python-level `__instancecheck__`); plus a function-local import per `move_by` | `tests/test_hot_validators.py`: contract table (float / int / subclasses / Fraction / NaN / inf / bool / non-numbers) for both validators; `TestHotPathsStayHot` patches the slow-path helpers to raise and drives `move_by` / `rotation =` / `rotate_by`. Fix: exact-type fast path first (as `_coerce_magnitude_slot` already did); `finite` imported at module level in shapes. Mutation-checked |
| B3 | **Harness bug, no engine change.** Auto-diff reported `gpu −25%` / heroes `+7%` as "candidate real move" — the window had opened on another display, so the GPU cells ran at FB 1200×800 (1×) instead of 2400×1600 (2×), a different workload. The same code at 2× measured flat (heroes 6.18 ms, draw 2.35 ms vs 2.27–2.35 on 09-22…24) | `balanced-2` on the evening of 2026-09-28 | `§` = 1× was a hand convention in `balanced.md`: the runner neither wrote nor read it, and `autodiff` compared across scales | `tests/test_bench_pulse.py`: scale tags round-trip, the runner stamps 1× cells, previous-row lookup matches FB per GPU cell (fallback / not-compared notes), older fallback rows never claim "same fingerprint → noise", dashboard headline says FB. Mutation-checked |
| B4 | **Probe bug, no engine change.** Every `jitter_probe` / `longrun` / Windows-wrapper run with `--seconds` hung forever (the window never closed); post-FX time was silently unmeasured | `jitter_probe.py app_first.py --seconds 4 --present keep` never returns (bisected to the author-API audit commit) | The author-API audit renamed engine hooks `Clock.tick` → `_tick` and `PostFxStack.render` → `_render`. `FrameProbe._patch` skipped a missing attribute silently, so the probe saw no frame start and never asked the window to close | `tests/test_frame_probe.py`: install on the real engine (every target exists, `_tick` / `_render` wrapped, uninstall restores), a missing target raises at install, a timed run requests the stop, every `--present` choice maps to a `canvas.framerate` value. `_patch` now raises instead of skipping. Same rename also broke `perf_spatial_fx.py` (patched `clock.tick`) |
| B5 | FX Auto **unstable**: any minor system load stepped it down (often to low@30) and it never stepped back up | 30 s of +30 % work with a 25 ms spike every ~0.5 s cascaded high → low@30 in ~7 s and parked at low@60; after a real overload ended it never returned to high although high fit with ~50 % headroom | Down: period *mean* (dragged by spikes), one bad eval enough (`t_down_s` 1 s), a 3 % slip line hit by spike slips, the pacer's own late wakes counted. Up: climbs needed *current* work under 32–42 % of the budget — out of reach for a scene that fits | `tests/test_fx_auto.py` `TestStability` (production params, simulated frames: minor load → no step; one bad second → no step; overload → down fast, back to high slowly; parks at the rung that fits; GPU-bound slips walk down; external slips at most one step; learned cost ratio; failed-climb backoff) and `test_pacing` oversleep-vs-overrun. Fix: median, 2 s, overruns only, 10 % in window and latest period, predicted-cost climbs with learned ratios, external-slip hold, doubling failed-climb lock |
