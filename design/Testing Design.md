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
| What GitHub runs on a push or pull request, and what it leaves out | [Continuous integration](#continuous-integration) |
| Harness helpers (world reset, census, probe) | [Harness map](#harness-map) |
| A test found a bug — what now | [Bug loop](#bug-loop) (mandatory) |
| Whole programs against a spec written from the docs; a divergence to triage | [Program model tests](#program-model-tests) |
| Whole games written to be tested: side models inside the game, under a real load | [Game system tests](#game-system-tests) |
| The laws trace, the reference model, the equations; triage of what they find | [Laws and equations](#laws-and-equations) |
| Games written by personas (beginner, Scratch kid, Unity refugee, copy-paster), the probe runner, the freeze signal | [Persona probes](#persona-probes) |
| A leak test fails but the engine looks right | [Harness pitfalls](#harness-pitfalls) |
| Do the smoke / example scripts still run? | `tests/test_scripts_run.py` (examples, quick) and `tests/test_smoke_scripts.py` (`scripts/smoke`, benches; `SLOW`) ([Recurring bug classes](#recurring-bug-classes): a script left on a retired spelling) |
| Is this bug a known class? | [Recurring bug classes](#recurring-bug-classes), [Bug catalogue](#bug-catalogue) |
| Is the engine converging? Findings per campaign, by verdict and by how common the pattern is | [Yield ledger](#yield-ledger) |
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
| Property | One call over a whole input space: Numbers rule, "author errors only", round trips, algebra (`move_by` undoes), invariance (shift the world, contacts stay) | Hypothesis `@given` | `test_hyp_api.py`; geometry: `test_hyp_api.TestRotationGeometry`, `test_box.TestGridCoversBoxProperty`, `test_canvas.TestScreenWorldRoundTripProperty`, `test_sys_hyp_collision.TestTranslation`, `test_easing.TestChaseProperties`, `test_easing.TestApproachProperties` (canaries: a per-axis step, an unclamped step) |
| State machine | **Sequences** and **failure paths**: lifecycle, registries, what a rejected or destroyed thing leaves behind | Hypothesis `RuleBasedStateMachine` + a small model | `test_hyp_canvas.py`, `test_hyp_events.py`, `test_sys_hyp_world.py` |
| System scenario | A cross-subsystem contract over real frames (destroy from every context, frame order, handoffs) | `unittest` + `SystemWorld` | `test_sys_lifetime.py`, `test_sys_frame_order.py` |
| Oracle / differential | An optimization vs a reference: brute force, the uncached path, the batched path, `force=True`, a model | Hypothesis + a twin (`diff_support.make_twins`), a config toggle, or an oracle | `test_sys_hyp_collision.py` (brute force), `test_diff_pose.py` (fast twin vs forced-slow twin), `test_diff_reactive.py` (configs + link model), `test_diff_collision.py` (cached vs uncached, closed form vs SAT, sweeps vs sampling), `test_diff_draw.py` (plain blit, cull, batching), `test_blit_plan.py` (cached blit plan vs a fresh blit, pixel for pixel) |
| Program model | Whole author programs (widgets, input, physics, camera, acts) over many frames, against expectations written **from the docs** by spec-only authors; feature interactions; doc gaps | `program_support.ProgramRun` + per-frame author-level probes + a temporal check vocabulary; L3 oracles (`program_oracles`) | `test_prog_*.py` ([Program model tests](#program-model-tests)) |
| Game system | Many features at once under a real load (acts, modes, timers, collision, level files, audio, widgets, draw) over thousands of frames; white-box: the game carries its own side models | `game_support.Ledger` + side models inside the game; `game_harness` pilots, `run_game`, the L3 oracles, canaries | `test_game_*.py` ([Game system tests](#game-system-tests)) |
| Signature fuzz | The whole public surface against generic contracts: junk in any one keyword is an author error with no trace, unknown keywords name themselves, construct → remove returns to baseline, every verb on a destroyed actor raises `DestroyedError` or leaves no trace, junk as the first argument of every author method is an author error | Hypothesis, one generated test per export (`scena.__all__`) | `test_hyp_surface.py` |
| Dead first | A verb or setter that refuses a destroyed actor refuses it whatever the arguments (DV1): every Entity kind × every refusing verb and setter × each parameter × ten junk values | Deterministic walk over P6's enumeration, one test per kind | `test_dead_verb_order.py` |
| Structural guard | A whole bug class that is visible in the source or the surface (duplicate `def`, every export fuzzed, member allowlist, `float(finite(…))`, Entity-or-None as an `or` operand, a hook calling its dispatcher) | `unittest` over `ast` / `scena.__all__` | `test_entity_hooks.py`, `test_api_surface.py`, `test_api_robustness.TestNoFloatAroundFormulaValidators`; every family asked the same subclass questions (`test_subclass_parity.py`); every warning with both sides (`test_warning_contracts.py`); every look × style × knob reaches the pixels (`test_knobs_take_effect.py`); every callback door refuses an `async def` (`test_async_hooks.TestEveryCallbackDoor`) |
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
  back by monkeypatch and assert the suite fails. A plant must reach the code the
  test runs: `obj.x = v` on an Entity goes through the class route table
  (`_setattr_route`), which caches the property it found, so patching the property on
  the class changes nothing — patch the method or module function the setter calls
  (`_apply_flip`, `entity._refuse_linked_channel`). And a plant must be wrong
  *behaviour*: removing one of two redundant pulls (a clone's pre-pull, when
  `look_like` pulls the source too) is not a bug the test should see
  (`tests/test_paint_flag_links.py`, `TestCanaries`, 2026-10-15).


# Harness map

| Module | Offers |
| --- | --- |
| `tests/hypothesis_support.py` | Profiles `dev` / `ci` / `deep` / `replay` (`SCENA_HYPOTHESIS_PROFILE`); example DB in `.hypothesis/`; `WorldTracker` / `fresh_world` (reset the process-wide singletons per example); `scrub_pools`; strategies (`junk`, `not_numbers`, `not_points`, `magnitudes`, `angles`, pool names `GROUP_POOL` / `ID_POOL` / `LAYER_POOL`); `AUTHOR_ERRORS`, `assert_author_error`, `call_as_author`, `leak_message`; `fresh_interns` (empties the look intern caches `_INTERN_CACHES` for a canary's plant and gives the old entries back: `assert_catches`, `game_harness.run_patched`; O11). |
| `tests/system_support.py` | `SystemWorld` / `system_world()` / `SystemTestCase`: real frames headless via `ScenaFramework._simulate_frame` (the body `run()` calls) + raster `_draw_frame` (post FX included: with no GL context the scene / FX render targets are raster surfaces); resets the act manager first (its teardown restores game rules: S4-8), then collision, bounds, cover, FX registries, clock, `ready` / `recently`, camera, post stack, and input (`reset_input_state`: keys, mouse, hover, press, widget focus, HUD cursor; X-life-8); pins pre-draw clocks to `clock.time`; quarantines (parks) live actors other modules left, resumed at teardown (`quarantine=False` defers it to `world.quarantine()`, for a census taken before parking: O4); gives back every `act.WORLD_SETTINGS` entry at teardown (O8); turns the GC freeze off (`gc_policy.set_gc_freeze(False)`: a frozen heap would hide a real leak from `census` / `assert_collected`; the policy itself is tested in `test_gc_freeze.py`). `census()` / `diff_census()` / `full_collect()`; `id_snapshot()` / `describe_new_ids()`; `zombies()`; `Probe` (`dead_calls()`); `assert_collected()` (referrer chain names the holder); `kitchen_sink()` (one actor wired into every subsystem); `tone()` (in-memory Sound). |
| `tests/diff_support.py` | `make_twins` / `force_slow` / `is_fast` (twin B via `_flag_pull_consumers`), `fingerprint` (pose + uncached collision prims read with cold engine readers), `assert_same` (tolerant structural diff naming the field), `assert_same_prims` (collision prims as a multiset: nearest-match pairing, never a raw-float sort — D10), `assert_fast` (**no vacuous pass**: fails if twin A left the fast path), `module_flag`, `assert_catches` (canary runner: patches a module name or a class, runs a fresh private copy of the target test under the `canary` profile, on empty look intern caches: `hypothesis_support.fresh_interns`, O11). |
| `tests/surface_support.py` | Inventory of `scena.__all__` by family (`family_of`, `constructor_names`, `ctor_params`); `EXCLUDED` (name → reason; the coverage guard fails on an export that is neither fuzzed nor listed); `surface_census()` (`census()` + post stack, background items / base kind, HUD cursors, hitbox parts, cover, capture devices); `census_diff`; `CURSOR_KEYS`; `remove(obj)` (destroy / remove / `reset_base`); `settle()`. |
| `tests/script_harness.py` | Runs one script headless in its own process (`python tests/script_harness.py <script> [frames]`): `scena.run` → a loop of `ScenaFramework._simulate_frame` (no window, no draw), the script's directory as cwd, `sys.argv = [script]` (a bench takes its argparse defaults); prints `SCRIPT OK <frames>`. Used by `test_scripts_run.py` |
| `tools/guide/make_guia_thumbs.py` | Render probe for every look in the Guia catalogs (Visual, SpatialFx, Post, Backgrounds): each card's snippet runs in a `SystemWorld` (GPU render target behind a hidden window; `--cpu` / the tests use raster) at its scene's design size (`init` *after* the world: its reset puts the tests' 400×300 back — the same 400×300 whose center hid the SpatialFx default-placement bug, see `TestDefaultPlacementFollowsDesign`) and is compared with the bare scene. A look that draws nothing fails; `anim: true` on a card that does not change over 2 s fails. Style variants read their choices from the engine's own `ValueError` (a probe value), so the Guia's option list is checked against code (`check_variant_choices`). Tests: `tests/test_guia_thumbs.py` (snippet choice, input hash, page data, variants and Guia/code drift, reductions, gallery lift, scenes) and `tests/test_guia_thumbs_render.py` (real renders: guards, measured loops, SpatialFx framing and a tall blaze measuring tall, transients, an impact shake on the photo; ~30 s, in `SLOW`) |
| `tools/readme/make_readme_media.py` | Records the README's clips: each program (an example, or the README block after `<!-- clip: id -->`) runs in a `ProgramRun` with `draw=True` on a GPU target (the Guia's `_gpu_surface`; `--cpu` raster), its `init` size kept (the target is set *after* the program runs, like the Guia's `init`-after-world). A pilot drives input through `ProgramRun`'s queue (`hold` keys, `mouse`, `press`, `drag_slider`), so the clip shows play. A clip that does not change fails. A montage (`segments`) renders each take in its own child (`fit` into the clip size), then letterboxes and captions them (`compose`). Tests: `tests/test_readme.py` (README programs play 2 s without a warning; fragments use exported names / accepted keywords / existing global attributes — `st` is open; repo URLs resolve; no relative links (PyPI); clip ↔ marker ↔ CLIPS; design aspect; every take an existing example with an existing pilot; montage hash per take; letterbox and caption; hash and status) |
| `tests/reactive_matrix_support.py` | Reactive matrix (also whole-object links, `run_whole_cell`, and cross-model copies in the test module): field × write path (`obj[f] @= lambda`, a cell, `part @= fn`) × read order (cold, self, all, all reversed) × construction model (`SUBJECTS`). Fields come from the `ScalarSlot` / `ContainerSlot` descriptors; the oracle is a plain-write twin read at the same moments (a Rect names its corners at first use). Checks I1 freshness, I5 unlink freezes, I6 two reads agree, I2 limits (`run_range_cell`: below / above / NaN). Used by `test_reactive_matrix.py` (in quick: the guards, canaries and the canary targets) and `test_reactive_matrix_cells.py` (`SLOW`: every cell) (guard: every exported reactive class has a subject or a `NOT_DRIVEN` reason; canaries for D12 / D13 / D14); complements `test_diff_link_write`. |
| `tests/test_hyp_reactive_matrix.py` | Hypothesis state machine over the same subjects: new subject (with a plain-write twin) / new cell / link / move cell / unlink / read some names on both sides in one order. Formulas are closures `a*cell.v + b`: the formula checker reads the lambda's source and refuses helpers such as `getattr`. A canary narrows the pool to Vec2 (`_Vec2Only`); the full pool is too diffuse for the canary profile's 150 examples. Where two plain writes do not commute but a link holds both, the twin re-puts every linked value until a pass changes nothing, the heading last (`_Pair.settle_twin`; it replaced `_reassert_heading` / `_reassert_pin`); a set that never settles fails (the engine must refuse it, GR19). Found D17, D18, GX13, GX20, GR18 and GR19. |
| `tests/test_heading_link.py` | Derived headings (a `p1,p2` / `p1,vec` / `p1,dx,dy` Line, Circle by rim, Ellipse by foci, Rect spine): the heading link and a link on a part its turn rewrites, or on a part the heading is measured from (found by writing each input and watching `angle`), are refused at the second `@=` and install nothing (D17, GR19); `_heading_driven_parts` equals what `rotate_by` refuses, both directions, so it cannot drift from the verb; every name read first is fresh after the source moves (D18). |
| `tests/test_write_path_guards.py` | Static guards (AST) on the write paths: raw `__dict__` stores of a field, `_dirty` writes, raw pose writes without a gate (`_pose_fast_ok` / `_requires_pull_invalidate` / `_link_source`), point readers that do not delegate to `_xy_of`. Each allowlist entry carries its reason; a stale entry fails too. Track A item 6; closes Track C item 5 (the write paths stay separate). |
| `tests/geometry_support.py` | Geometry contract registry: `KINDS` (every Graphic kind × constructor model, plus Box, built from a pose dict `{x, y, s, r}`); `point_parts` (every Point slot, `points[k]`, Text parts, `.box` named points), `vector_parts`, `scalar_parts`, `drawn` (the point set that fixes the paint), transform oracles (`turned` / `scaled` / `mirrored`), `safe` (a read that raises becomes a recorded `ReadError`), `settle` (run timed verbs). Used by `test_geometry_contract.py`; known violations in `geometry_known.py` (shrink-only). |
| `tests/program_support.py` | Program model harness: `ProgramRun(program, params, probes=)` runs `tests/programs/<name>.py` in a `SystemWorld` (`run()` replaced by the startup it does, the process-wide bookkeeping included: it ends the stall watch's top-level phase, and `close()` ends one a program left open; left at "top, reported", the next program's slow loading went unreported, so a top-level stall test failed after another one; `PARAMS` / `mark()` injected), feeds input through the real GLFW handlers **inside the frame's poll** (`key_down` / `press` / `move` / `scroll` / `set_cell`, `widget_center(label)`), samples author-level probes after every frame into a `Trace`, and on `close()` destroys what the program made (census back to `census_before`: `leftovers()`). A program starts with an empty `st`: cells other modules made are parked and given back at close (a reused cell kept the run's link node alive). Spec vocabulary: `Scenario`, step builders (`wait`, `click_widget`, `key`, `drag`, `set_cell`, `drive` — a pilot called before each frame, …), `Expect`, `serial(obj)` (per-run identity), checks (`always`, `never`, `at`, `at_end`, `eventually`, `steady`, `custom`). `program_test_case(...)` builds a test module. |
| `tests/program_oracles.py` | L3 oracles over whole programs: `replay`, `probe_neutral` (probes do not change the world), `dt_split` (dt/2, twice the frames), `reactive_config` (lazy + backstop vs eager + strong), `cull_pixels`, `teardown` (census + zombies). Tier C: `tier_c` re-runs a rewritten program (`TIER_C`: `rename_groups` — every group name suffixed; `reorder_defs` — runs of undecorated defs reversed; `rename_layers` — every author layer name suffixed) and requires the same world (`world_fingerprint` minus `made_at`). Metamorphic ([Interaction campaign](#interaction-campaign), class 3): `camera_moved` (the camera set before the first line through `ProgramRun.prelude`: the same trace minus the probes that read the camera, the same world), `time_scaled` (`clock.scale = k`, frames of `dt / k`: the same trace). |
| `tests/test_prog_invariance.py` | The metamorphic oracles over every program (exclusion tables with reasons: programs that place by the view or chase the mouse leave the camera oracle, a program that sets `clock.scale` leaves the time oracle), `rename_layers` on every program, canaries. One generated class per program (`TestPlatformer`: `test_camera_moved` / `test_time_scaled` / `test_rename_layers`), so the gate runs one job per program. `SLOW`, `SPLIT`. |
| `tests/program_coverage.py` | Which exports the programs reach: a `sys.monitoring` hook (PY_START / PY_RESUME; code outside `scena` is `DISABLE`d) records calls from a program's own code into `scena` (and the class of `self` / `cls`, since exported constructors are wrapped), mapped onto `scena.__all__`; global objects by name in the source. Guard: `test_program_coverage` (every export reached or in `PROGRAM_EXCLUDED` / a look family; `SLOW`). |
| `tests/program_ledger.py` | Open divergences (shrink-only), verdicts and cause codes. |
| `tests/game_support.py` | In-game instrumentation for `tests/games/` (light: no Hypothesis, no glfw): `Ledger` (`frame()` as the first line of `update`, reach counters, `check` / `equal` / `within` that **record** a failure with frame, time and scope, `invariant`, lifetimes by serial, `finish`, a plain-data `report()`, `digest()`), side models (`TimerModel`, `TweenModel`, `EdgeModel`, `ChangeModel`, `CoverModel`, `SoundModel`) and `geom` (closed-form intersections, point-in-shape, closest points, swept circles, Grid cells, `amp_db`). Tests: `test_game_support`. |
| `tests/test_subclass_parity.py` | Every exported `Entity` family subclassed in an author module and asked the same questions: a class keyword is applied or refused with an author error, `on_collide` methods get `(other, info)`, an own field that reads the object (a part too) dies without a warning, the subclass is collected. Tables with reasons: `NOT_SUBCLASSED`, `NO_CONTACT`, `NO_INK_LINK`, `KNOWN_SELF_READ` (shrink-only). |
| `tests/test_warning_contracts.py`, `tests/warning_sites.py`, `tests/warnsite_site/` | Every `warnings.warn` / `report_author_warning` site of `scena/` (by `ast`, module:qualname) has a `CONTRACTS` row: `fires=` (test module) or `untested=` reason, `silent=` (the test of its legitimate twin) or `twin=` reason; named tests must exist. `warning_sites.py` runs a tier with a recording `sitecustomize` and prints the rows the measurement contradicts (measurement only: the hook breaks stacklevel tests). |
| `tests/test_documented_patterns.py` | The Guia's patterns that sit next to a warning, each a small program in real frames with every warning recorded (director wave, ground flag, formula group, named tween refresh, loop-default formulas, collide method, SpatialFx class keywords, a HUD over an unlinked field, an act soundtrack). |
| `tests/game_harness.py` | The game drivers: `GAMES` (`GameSpec`: scenarios, probes, reach minimums, checks that must run, claimed exports, `spec_ns()` for `program_oracles`), pilots (`Pilot`, one class per game, deterministic, reading only the game's state), sending only a stream a window could send (every tap goes up the next frame, several taps in one frame included; `ProgramRun` refuses a second PRESS of a held key, which GLFW sends as REPEAT — an injected one read as an engine I1 finding, chaos caverna/volta 2026-10-22), `run_game` (a `ProgramRun` with the `drive` step; reads `G.report()` before `close()`; records SCENA warnings), `problems` / `assert_game_clean`, `KNOWN` and `WARN_OK` (shrink-only, with reasons), `run_patched` / `assert_canary`. |
| `tests/test_sys_holders.py` | Holder × ender ([Interaction campaign](#interaction-campaign), class 2): `scan(target)` (every engine path to an object, with its reference kind), `HOLDERS` classification guard, `Wired` subject, gone enders (no strong path may remain; `KEEPS` with reasons), partial enders (`EXPECT` per documented contract; `UNSETTLED` shrink-only), canaries (a pointer manager or a pair list that keeps a destroyed body); a left collider (`TestALeftColliderIsLetGo`: no path reaches a collider after destroy / park / `collidable = False`, alone in collision or beside a full step), canary: a per-step set that keeps a left collider. ~0.4 s. |
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
| `tests/leftovers.py` | Module isolation: `module_sweep()` → `setUpModule, tearDownModule` that destroy every actor the module registered (roster keys after the module's mark, newest first; parts leave with their owners; `on_destroy` cleared; raises when one survives); `mark()` / `made_since()` / `sweep()`; `LeftoverCheck` (fails a module that leaves one live actor it made, naming each with its site, or more than `LIMIT` = 50 live parts; the canvas's `canvas_rect` and framework singletons never count). `run_tiers.py` runs every job through `--child` (`python -m unittest` plus one check after each module, not counted in "Ran N"). Tests: `test_leftovers.py`. |
| `tests/floor_support.py` | A world with a floor for the tests of gravity scenes (`collision.floor`, off in a fresh world since 2026-10-21, EX2): `@with_floor` on a TestCase class, or `setUpModule, tearDownModule = floor_module()` for a module. Both set the default a new collision system takes (`collision._FLOOR_DEFAULT`), so a `reset_collision_system()` in a `setUp` starts with a floor too, and give it back after. **A test of walkers, ramps, lifts, seams or resting piles uses it**; without it the test passes and measures a world without gravity's rules. A program (a game, a smoke or bench scene) writes `collision.floor = True` itself, as an author does. |
| `tests/vec2_support.py`, `tests/vec2_known.py` | The [Vec2 battery](#vec2-battery)'s axes, read from the code where they can be: `KINDS` (every way an author holds a Vec2: free, an arithmetic result, an actor's `vel`, an st cell's vector alone or saved into a second cell, an ink field's vector watched, saved into a cell, saved unwatched, every `ContainerSlot(Vec2)` part as `PART_KINDS`, a Derivate `vec`, whole / one-axis linked, a dead actor's `vel`), `DOORS` (every spelling that writes x / y), `OPERANDS`, `CONTEXTS` (plain, frame batch, `on_change` callback, frame), `READS` (cold / warm); `run_cell(kind, door, operand, context, read)` returns the generic oracle's violations (`INVARIANTS`), with `DESIGNED_REFUSALS` / `DESIGNED_ACCEPTS` / `DESIGNED_OPERAND_REFUSALS` naming each designed exception and its doc. `vec2_known.DOORS`: open violations by glob, shrink-only, stale entries fail the gate run. |
| `tests/test_vec2_doors.py` | The door matrix: the full product in the plain context (quick, ~0.7 s for 2.5k cells), a 2-wise array over the contexts and every kind × door × context × read with one good operand (quick), the full product in every context plus the stale check (gate); `TestOracleBites` plants one bug per invariant; `TestFoundByTheMatrix` holds one minimal repro per VB row. ~7 s dev, ~9 s ci. |
| `tests/test_vec2_algebra.py` | Black-box Hypothesis properties: exact identities on integer-valued vectors, ULP-bounded identities, inequalities (triangle, Cauchy–Schwarz, ranges of `angle` / `angle_to`, `clamp_length` bounds), aliases bit-equal, the Guia's own examples, degenerate bases, and "author errors only" for every operation × junk operand (completeness over Vec2's public methods). |
| `tests/test_vec2_metamorphic.py` | Twins: one Hypothesis sequence of author writes on every kind at once (free cold / warm / slow / A3 cache cleared, `vel`, st, watched ink, Defining parts), bit-equal after every step, formulas read at chosen moments; four spellings of one displacement; rotation / translation / scaling / mirror invariances. |
| `tests/test_hyp_vec2_machine.py` | State machine over holders (three st cells, two ships' `vel` and ink fields, free vectors), copies between holders, links (whole, one axis) and their source, watchers, destroy; invariants: finite numbers with agreeing length / angle, formulas show their holder, no two cells share a vector and each keeps its guard, a refused step moved nothing. ~6 s dev, ~22 s ci. |
| `tests/test_vec2_guards.py` | Static guards: every raw x / y store in `Vec2` named with its guards (`RAW_XY_WRITERS`), `DOOR_METHODS` ↔ Vec2's in-place spellings, `PART_KINDS` ↔ every `ContainerSlot(Vec2)`, the Guia's Vec2 table ↔ the class (`UNDOCUMENTED`, shrink-only). |

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
  canary helpers. A game with `os_level` (`GameSpec`) runs in a `GameRun`
  that also plays the OS side of input, as `tests/input_driver.py` does for
  system tests: a window (so the per-frame pointer sample runs: a camera
  that moves under a still cursor moves `mouse`, a cursor that leaves with no
  motion event ends widget hover), `glfw.get_key` / `get_mouse_button`
  reporting what is held, the modifier bits of held modifiers on every key
  (Shift held: `MOD_SHIFT`), `key_repeat` (an OS auto-repeat) and `place`
  (the cursor moved with no motion callback). The program oracles run a plain
  `ProgramRun`, so they take only an `os_level` game's static scenario.
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
  through closures and drop them in `release()` (no reference outlives the run;
  `Handle` takes a weak reference since WP35).
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
  harness releases pilots before `close()`. A pilot may tell the game what
  only the player knows (Canteiro's `CURSOR`: where the cursor is in view
  units, what owns the press): that is the truth a pointer model compares
  `mouse` with, never a value read back from the engine.
- **Time, not frames, where pacing is a variable.** A pilot that acts by the
  act's clock plays the same session at any `dt`, so one scenario runs at
  30, 60, 144 and 240 Hz (`canteiro_scenario(hz)`; [lesson 3 of the
  game-behaviour probes](#what-the-game-behaviour-probes-taught-2026-10-14)).
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
  hover step skipped, `amp_db` skewed, a stale pull (Oficina); every PG fix
  Canteiro guards, through the engine's own switch where the fix has one
  (`_RIDER_CARRY`, `_SKIN_ALONG_MOTION`, `_SETTLE_MIN_OVERLAP`,
  `_SETTLE_STATIC_CLAMP`, `_SWEEP_INHERIT_CLAMP`) and the old behaviour by
  `mock` otherwise (no carry opening, no ghost contact, a left tag
  forgotten, the first exit rule hiding the rest, a dead side stopping the
  dispatch, a closure over `self` not owned, `clone` ignoring `center=`, a
  destroyed Button left on, a widget press visible, hover only on motion,
  drops only in the press space, Shift blocking a bare key, an act change
  dropping the up, no pointer resample).

**L3 oracles.** `spec_ns()` gives `program_oracles` what it reads, so replay,
`probe_neutral`, `dt_split`, `reactive_config`, `teardown`, `tier_c`,
`camera_moved` and `time_scaled` run unchanged. Exclusions carry reasons:
`dt_split` on continuous probes only, with tolerances (input lands half a
coarse frame earlier); `time_scaled` not on Armada (the cover runs on
presentation time); `camera_moved` on Oficina only (the others place by the
view); Canteiro's oracles run its static scenario only (`os_level`, above).

**The three games (2026-10-10).**

| Game | Load | Models |
| --- | --- | --- |
| Armada (shooter) | Acts title → hangar → sector → arena → end through one iris; sheet atlas and clip, `collide` / `_stay` / `_exit`, hitbox parts and a weak point, `Collider`, modes with `race` / `parallel` / `until_empty`, named `every` / `after`, a custom-ease tween, Jet / Portal / Orb / Sparks / Fire, four posts, widgets and a pause `Menu`, music crossfade and handle effects | population, shot conservation, timers, tween (exact), edges / changes, act and cover, `ready` cadence, CCD no-tunnel (swept circles), sounds |
| Caverna (platformer) | `caverna.json` Level (platforms, a ramp, a polygon, tracks, points, images), `resolve`, slopes, coyote time and a jump buffer, a lift by `move_along` carrying its rider, camera deadzone + chase, parallax, Endless, clips, History checkpoints, death → iris → respawn | Level vs plain JSON, grounded ⇔ geometry, rider displacement, coyote / buffer twin, camera bound, parallax view, Endless slot determinism, clip frame formula |
| Oficina (reactive workshop) | Grid board, drag / drop / hover / click, State cells and `@=` chains, group formulas, every widget kind, materials (Fill / Stroke / Paint, Gradient / Texture), a laser against shapes, raycast / `query_point`, `Collider`, Track probe, baked fx chain, spectrum, Microphone (NULL backend), pixel checks | a plain-Python reactive twin, widget mappings, pointer geometry, laser closed forms, audio stack, pixels at checkpoints |

Together they reach 123 of 249 exports, 28 that no program reaches (Level,
Microphone, the audio effects, SpatialFx, Fill / Stroke / Paint, Chroma / Wash
/ Crt / Pixelate …).

**The fourth game (2026-10-14): Canteiro.** The [PG](#pg--game-behaviour-probe-campaign-2026-101314)
probes found ~35 bugs at seams none of the three games crossed, and each fix
left a per-bug regression test only. Canteiro keeps those seams under load,
each against an independent model:

| Seam (PG id) | Load | Model (its truth) |
| --- | --- | --- |
| Riders (PB2, PB4) | a STATIC lift sliding across a pit, one climbing a shaft with rests at both ends (`move_by` in the act's `on_update`); the hero rides a full cycle, walking on the sliding one | displacement = the lift's + the hero's own step unless it jumped (Guia, "Tornar sólido"); bottom on a lift ⇒ the `@collide` contact is open; the foot on the top through the descent |
| Idle slope (PE2) | a ramp (`ramp_angle`), the hero stopped on it a second | no displacement between frames (1e-6) |
| Settle (PE1) | bubble pairs spawned 5 units into each other moving apart; a stone spawned inside a 4-unit wall moving into the room | sides kept, apart in 8 frames; the stone leaves into the room |
| STATIC holds (PE3, PE4) | crates of mass 1, 5, 20 and a light ball under a mass-30 one on 10-unit shelves, the heavy ones re-dropped every 3 s; a light ball (made first) rammed at 6000 units/s into a 2-unit wall | nothing sits deeper than the slop in a shelf; the light ball's face never passes the wall, the ram never passes it |
| Bounce off a removed partner (PE5) | a ball in a brick box, `@collide` destroys the brick | the velocity along the swept contact normal (`geom.sweep_circle_box`) leaves the brick |
| Every enter / exit rule (PB5, PB3, PB1) | a turret whose shot and target are made in alternating order, each with its own `@collide_with` method; parcels through a scale with two exit rules, the first destroying; spikes whose enter untags the hero | both rules count each hit and the score is the targets hit; the second exit rule runs every time; after the untag no contact is open |
| Ownership (PA4, PD1) | a bubble's `after(…, lambda: self…)`; the Jato Button destroyed while held | the bubble's timer is cancelled with it; `st.segurando` reads `value_off` |
| Input streams (PD2, PD3, PD4, PD5, PD6, PD7) | the Zoom Slider dragged, the Jato held; Enter held with repeats in Nome, whose `on_submit` focuses Nota; the cursor placed outside the window; the crate icon (ui) dropped on the plot (world) and a crate on the trash (ui); Shift held while walking and jumping; RIGHT held through the door into the shed | `mouse.press` False under a widget's press; Nota stays empty; the Jato unhovered; `pos` is the camera map of the release point in the target's space; `keyp` / `keyp.once` agree with the hooks; every down gets its up, across the act change |
| Pointer under a moving camera (PC8, PB6, PC1) | the camera chases the hero, zooms with the Slider and turns (`giro`); the pilot wanders and clicks | `mouse` = the float64 camera map of the cursor (Canvas Design); `mouse.x` unchanged after a pan in the same update; a stake lands at the pointer; `clone(center=)` places the crate |

Building it found no engine bug; it found one model error worth keeping:
a brick's `info.normal` is the detection normal, and where two bricks meet
(or a slot is empty) it can be a face's while the bounce uses the corner of
the swept path. At 30 Hz the ball "did not flip along the normal" while it
bounced correctly. The model now sweeps the ball's circle itself. Two
canaries first missed their bug and made the game stronger: `self.after`
is owned by the call (PA4 was the module `after` with a closure over
`self`), and the settle and thin-wall bugs needed the exact setups of their
regression tests' canaries (a stone inside a wall; a light ball made before
its 6000 units/s pusher), not merely similar ones.

**Value so far.** Writing and running the first three games found eight engine bugs
(AC1, AC3, AC6–AC9, AC11, AC13; AC12 came from an existing suite during the same work; [AC](#ac--game-system-tests-2026-10-10)), a
harness vacuity (HV1: every `ProgramRun` draw painted a surface nobody read,
so `cull_pixels` compared two blank frames), a doc sentence that over-promised
(AC4), and three API questions (AC2, AC5, AC10). Most were met by the game's
own code before any model ran: a pattern the Guia shows, used in a real game,
broke (a coyote flag that reads its owner, a formula group declared with `@=`,
an `on_collide` method, a long `until_empty` wave, a named tween refreshed).


# Laws and equations

A campaign (from 2026-10-14) that gives the engine's discrete semantics a
written, checked form. The bugs the earlier campaigns kept finding sit in
three concerns no feature owns: **time** (what runs in which phase, when an
effect becomes visible), **identity and lifetime** (create, park, destroy,
act change), and **authority** (who owns a press, a contact, a write). Three
instruments, all test-side (nothing in `scena/` changes, so real games pay
nothing):

1. **A constitution** of short laws, each stating today's behaviour within a
   perceptual budget, with its checkers (one per stage, from S1).
2. **A reference model**: pure functions over a recorded trace that predict
   what an author sees (which callbacks run, with what, in which phase) and
   report violations, abstentions and witness counts.
3. **Equations**: pairs of programs an author believes equivalent (another
   frame rate, another spawn order, a handler declared another way, the
   world mirrored) whose traces must agree. They answer the oracle problem:
   no expected value is needed, only agreement.

**Triage: real bugs, not academic ones.** The instruments find candidates.
Every divergence is investigated to its mechanism, whatever its size (a
small one can be the symptom of a wrong calculation); the budget decides
whether a test fails and how urgent it is, not whether we look. Verdicts:
**BUG** (wrong behaviour in a realistic game: a game-level repro, then the
bug loop), **LATENT** (a plainly wrong calculation a plausible game would
expose: fixed only if local, perf-neutral and invisible to existing games
beyond budget), **ACADEMIC** (legitimate approximation: float order, solver
iteration, absolute constants; listed with the reason, the engine is not
touched), **DECISION** (the engine is consistent, the law is in question:
to the maintainer). No "precision" fixes.

**The recorder** (`tests/laws/trace.py`). `sys.monitoring` tool 5 (fallback
0; never 3, the engine watchdog takes it over, or 4, the sentinel):

- local return events on a table of engine code objects (frame body, phase
  functions, `Registry.register` / `destroy`, `Entity.destroy`, park /
  resume, `ActManager._change`), and one global start / resume event that
  keeps author functions the engine calls — every callback, whatever door —
  and returns `DISABLE` everywhere else (never on a hooked code object:
  DISABLE silences the location for the tool, local events included);
- the door of an author call is the nearest labelled engine frame
  (`contact`, `exit`, `after`, `every`, `on_destroy`, `update`, `key`, …);
- labels `kind@file:line#n` keyed by `id()`, re-bound at each creation;
  raw `__dict__` reads only; the callbacks swallow their own errors and
  count them (`Recorder.errors`).

Attach: `laws.attach.attach(run)` (`run_game(before_start=)`,
`program_oracles._run(before_start=)`): installs in the run's prelude (the
program's first line), uninstalls before `close()` (teardown is the
harness's, not the program's). Scripts: `script_harness.py --laws out.jsonl`;
`--fingerprint` prints the end world. Author code is everything that is not
the engine, Python, a helper directly in `tests/` or the laws machinery
(`tests/games`, `tests/programs`, `examples/`, `tests/laws/fixtures` and
`twins` are author code).

**E0, neutrality** (`tests/laws/neutrality.py`): the run with the recorder is
the run without it — probe samples frame by frame, the end world, the game
ledger and warnings, leftovers, and **survivors** (engine objects alive as
Python objects after a full collection: the registries forget a destroyed
actor even while something holds it, so only this count sees a recorder that
keeps references); plus a self-check (every frame seen, no recorder error,
nothing left installed). Quick: `test_laws_quick` (the fixture
`tests/laws/fixtures/s0_basic.py`, one program, canaries: a DISABLEd frame
hook, a recorder that keeps its objects). Gate: `test_laws_neutrality`
(every program, game and example; canary: a recorder that holds author
classes).

**Overhead** where attached: canteiro `curta` 3.9 s → 4.7 s (+19 %), from
~12 author calls a frame; a real run is unaffected (not installed).

**What S0 taught** ([LW](#lw--laws-campaign-2026-10-14)): the recorder
itself failed E0 twice before it held — once by holding author classes in
its label table (an author class can own graph nodes: a leftover node in
oficina), and the harness failed it once (LW1: two runs in one process did
not start from the same presentation clock). An observer is code with bugs
of its own; E0 stays on for every later stage.

**The model** (`tests/laws/model/`): `check(events)` → `Report` (findings
with a dedup signature, witness counts per law, abstentions). One module per
law group; each lists its `LAWS`, and `test_laws_doc` holds them and
[Laws.md](Laws.md) in step both ways (and the page under 45 laws / 250
lines). The model never calls the engine function it checks; it abstains on
a frame an exception cut short.

**S1 — frame and lifetime (F1–F2, L1–L6).** Fixture
`tests/laws/fixtures/s1_lifetime.py` (acts, a destroy twice, a park, an act
change whose hooks read siblings) witnesses every law; synthetic traces test
each rule both ways; canaries (`tests/laws/plants.py`, gate) plant a bug of
each law's class through the engine — the tick skipped, timers ticked from
the collision step, a destroy deferred to the end of the frame, `on_destroy`
fired twice, an `on_update` fleet that keeps dead actors, a park that leaves
the actor active, act hooks fired during the teardown, a doomed list that
takes top-level objects — and each is named by its law. Every `PLANTS`
canary runs twice, pose-revision verify off and on (`both_verify_modes`, a
subtest each): a plant must bite in a hand run and in gate. `test_laws_families`
(SLOW + SPLIT) runs the model on every program scenario (both specs), every
game scenario and every example at 600 frames; deep adds every tutorial
step. Result: no engine finding for F and L.

**What S1 taught.** Every first finding was the model's: a law wrongly
worded is as loud as a broken engine. "Its own hook" first meant any call
whose first argument is the object, which counted a module
`@collide_exit` handed a dead `me` (the deferred exit, PB5) — now a method
whose `self` is the object; the act's own teardown is the first of the
change (Act Design), not a member of its batch; the top level ends at the
first act build, not at the first frame; the public `flush()` called from a
drop handler (toybox) is the author's, not a frame phase (the recorder marks
whether the frame body called a phase function). Each fix moved a rule
toward the sentence in the companion doc, which is where the law's wording
comes from.

**S2 — contacts (C1–C8) and the first equations (E3, E4, E8).** The
recorder adds each step's commit (`C`: entered / stayed / exited as label
pairs), the resolve markers, and the doors `enter` / `stay` / `exit` /
`hover` / `hover_exit`; a door is found by qualified name in the engine's
files (a plant wrapping the labelled function cannot hide it), and engine
code between an author function and its door that is not a call helper
makes a nested door (`enter>Entity._enter_mode`: a mode a handler started).
Fixture `tests/laws/fixtures/s2_contacts.py`; canaries for C1, C2, C4, C5,
C7, C8 (`plants.py`). C3 and C6 need the handler table, so their checkers
are the unit tests and the equations. Equations (`tests/laws/equations.py`,
`test_laws_equations`): a projection per frame (multisets of normalized
events; formula and condition pulls are not compared), transforms that
return a line map, twins in `tests/laws/twins/`. E3 swaps adjacent
independent constructions (not those that draw random numbers) on the
shooter twin, every program and every example; E4 runs one rule in three
homes; E8 breaks a brick in its handler or between frames. Results: no
engine finding for C1–C8 on the families and every tutorial step; LW2
(a decision: simultaneous contacts are answered one at a time; fixed
2026-10-15), LW3 and LW4 (ACADEMIC). E15 (2026-10-16, after CD3) adds a
no-op `@collide_stay` between two tags the program's top-level rules already
name (enrollment, queries and `collidable` unchanged) and compares every
other author call, contacts left out (a rule that pairs new bodies adds
contacts: they are per pair, the law is per rule); twin
`tests/laws/twins/shield.py` (a tag joined, left, blinked, flicked and given
by a handler mid-contact), every program and every example; canary: the old
per-pair rule.

**What S2 taught.** A plant can hide behind a second guard: a parked body
leaves collision *and* fails the in-play check; a destroyed body's contacts
are ended, its collider dropped *and* pruned at the next step. A canary that
does not bite says how many guards the class has. An equation's twin can be
wrong in ways the engine is not: the first script twin ran from a folder
without the example's art (a placeholder hit box moved every collision), and
the first `on_collide` twin had a partner that was never registered. Before
blaming the engine for a divergence, run the twin twice, and run the program
in the other harness.

**S3 — input ownership (I1–I5; I6 by its unit tests).** One record per OS
key, character and button event, with the doors it reached while it was
handled: the script's (`callback_if_exists` for `on_key_down` /
`on_key_up` / `on_key` / `on_char` / `on_mouse_*`, the delivery point
whether or not the author wrote the hook), the widgets' and shapes', plus a
widget giving up its press. Fixture `tests/laws/fixtures/s3_input.py`,
driven at OS level (`laws.harness.drive`: held keys, auto-repeat,
characters) across an act change, a focus change and a held Button
destroyed; canaries are regressions of PD7, X-life-3, W-P4, LW5 and a
widget side claiming a given-up release. Result: LW5 (a bug, fixed); no
other finding on every program and game scenario.

**What S3 taught.** Mark the delivery point, not the entry point:
`CanvasManager.handle_mouse_up` is entered for a press the script never got
and returns at once (X-life-3), so "entered" read as a stray up until the
marker moved to the hook call. A fixture driven like a player finds what
unit tests of each stream did not: the key that focuses a box typing itself
into it took one keystroke to show.

**S4 — timers (T1–T4, T6; T5 by E6) and the equations E1, E5, E6.** The
recorder adds each handle's `add` (kind, delay / interval, owner, the phase
it was made in), its `tick` records (world dt, the owner's time scale,
parked, dead, paused) and its fires and cancels. The model replays `after`
and `every` in exact rational time (each number at its rational intent:
1/60, 1/2), so PM8 has an oracle that shares no rounding with `reached`.
Fixture `tests/laws/fixtures/s4_timers.py` (an exact-frame `after`, an
`every` across a 0.5 s hitch frame, chained, parked, dead and half-speed
owners, work on a destroyed actor). Equations: E1 pacing (`script_harness
--pace 30 | 144 | uneven`, the same game time; edge events matched in game
time within a frame of each pacing; per-frame doors are not compared), E5
act vs top level (`twins/act_home.py`), E6 bound method vs closure over
`self` (an in-place rewrite of every `after` / `every` callback on every
program and example). Results: the T laws hold on every family; E5, E6
hold; E1 holds on 32 of 36 examples and the one-ball twin — LW6, LW7
(decisions; LW7 fixed 2026-10-15, when the one-ball twin turned out to have
movable walls, LW9) and two ACADEMIC exclusions (an author's Euler step, a
self re-arming chain).

**What S4 taught.** An instance field may live in a slot: the first
recorder read `__dict__` only and saw every parked owner as active (the
model then "found" a missed fire); `trace._field` reads the dict or the
slot, never a property. A pacing equation needs a pinned clock for every
consumer it compares (the shape transients' wall clock made a headless run
depend on the machine's load, until LW6 moved them to presentation time) and a pairing, not a count, at the horizon. A
plant must be the bug class, not its caricature: zeroing `every`'s elapsed
on each tick silenced the timer; dropping the debt after a fire is the
class.

**S6 — motion (P1–P5; P6, P7 by their tests) and E10–E14.** With
`Recorder.motion` on (the family sweeps and script runs turn it on), each
resolve is bracketed by `M` records: every resolve body's raw pose,
velocity, mass and outline (real `Circle` / `Rect` only; a Sprite collides
as its hitbox, so its overlap abstains) and the pairs the solver answered.
The motion model checks bounds: overlap ≤ slop, no energy gained against
still STATIC partners, momentum kept between two movables, STATIC unmoved,
no sideways creep of an idle body (resting after the last resolve, below
`REST_SPEED`, not riding, no sideways motion of its own). The motion twin
(`tests/laws/twins/motion_world.py`: idle on a ramp, a stack, a head-on hit,
a rider on a lift, a ball in a box) runs transformed copies: E10 translation,
E11 mirror, E12 mass ×10, E14 world ×2 within the position budget, E13 at
30 / 144 Hz within one frame of travel. Canaries through the engine's own
switches (`_SKIN_ALONG_MOTION`, `_RIDER_CARRY`), a bounce that ignores mass
(P3) and a one-sided bounce loss (E11). Results: E10–E12 exact to the last
bit on every scene; E14 within 0.08 DU; the P laws hold on every program,
game and example (P2 checked ~20 000 times, P3 ~2 000).

**What S6 taught.** Every first motion finding was the model's: a Sprite's
picture is not its hitbox (38 DU "overlaps"); a rider's carry happens inside
resolve; a body still falling onto a ramp's corner slides there; a walker
that moves by `move_by` keeps `vel.x` at 0. Each fix narrowed a law to the
sentence in Collision Design. A canary plant can be mirror-symmetric by
accident (a "leftward bounce loses 2 %" hit one bounce in each world); an
asymmetry is a property of the contact (its normal), not of the outcome.

**S7 — chaos doors (F3, the snapshot rule).** F3 names the hybrid the engine
already was (commands immediate for the author, a running pass keeps what it
chose; Scena Design, "Commands during a pass"); the chaos doors check it by
firing, at an author callback door, one command an author could write there.

- **Injection** (`tests/laws/chaos.py`): an AST rewrite compiled under the
  program's own path. Every plain `def` and lambda routes its returns through
  `__chaos__.ret(value)`; new nodes reuse the replaced node's location, so
  labels, `fn` fields and the file on disk are the plain run's (no line map).
  `ret` asks `trace.door_of` (the recorder's own site walk, factored out)
  whether this return closes a door and counts `(door, n)`. Not
  `sys.monitoring`: no monitoring event fires while a monitoring callback
  runs (probe, CPython 3.12 and 3.14), so a command run from a PY_RETURN
  callback would be invisible to the recorder. Not a wrapper: it puts a frame between
  the engine and the author function. Generators and coroutines are not
  rewritten (v1). Runners: `ProgramRun.transform` / `.inject`,
  `script_harness.py --chaos plan.json`.
- **Commands** (`chaos.COMMANDS`, each with an applicability test and, where
  it has one, an immediacy check read raw right after it returns): destroy
  self / partner / another, park (resumed by label two frames later), park
  and resume in one door, `untag`, a group join, `collidable = False`,
  `change_act`, a clone, a timer, a pose or velocity write; the group family
  (`group[g].destroy()` from the group's own handler, bulk tag / untag, churn
  across steps, joining a rule mid-contact, a walk that
  destroys and clones); neutral ones (an absent untag, a held tag, `after`
  then `cancel`). Pull doors (formula, condition) are not sampled.
- **Passes.** Pass 0, the plain run; pass 1, the idle rewrite, which must
  equal pass 0 (E0 for the machinery) and lists every door return; then
  single-fault runs drawn with a weight of 1 / (that door's count), so a
  hover or a Menu pick is drawn as often as `on_update`. Examples run one
  multi-fault plan, shrunk by ddmin on a finding. A finding prints its repro
  (`python tests/laws/chaos.py <program> --plan door:n:command`).
- **Checks** (`chaos.verdict`): the law models; no engine-internal exception
  (a `raise` in `scena/` is a refusal, recorded; an error the author's own
  later code meets on a body the command destroyed is the C3 trade-off,
  recorded); no zombie; **owed work** against pass 1 from the injection
  point — the injected contact's remaining handlers run (C3: the first trace
  checker it has), its ghost when the partner left (C8), its exit when the
  command ended it (C5), no enter / stay with a removed body outside it, and
  none at all after an act change; **new waits**, per loop (a clone made in a
  timer fire runs its `on_update` this tick: the fleet starts after the
  timers); a neutral command leaves the trace as pass 1 (its own handle
  records aside, later handle ordinals renumbered).
- **Fixtures.** `s5_doors.py` opens every door the other fixtures leave
  closed (hover, leave, two `@when` in one flush and owned ones, tween and
  Track `on_done`, a sound's end, Button, TextInput submit, Menu, script
  keys and mouse, a two-contact step with two handlers each), driven at OS
  level (`chaos.S5_STEPS`). `s7_cells.py`: the directed cells, one scene per
  suspect.
- **Canaries** (`plants.F3_PLANTS`, gate): handlers re-checked before each
  call (pre-PB5), no ghost (pre-PE5), an act change that does not move the
  dispatch's act epoch (S4-1), a destroy that does not retire its owner's
  watches, a tick that walks its buckets live, a group walk over the live
  membership, tag changes forgotten at the step (PB1, CD3-x); each caught by the
  check named for it. A rewrite that loses a return value fails pass 1.
- **World machine (M5)**, the messy complement: single faults cannot reach
  compound states (several commands in one pass, a command inside another's
  hooks, dense contacts). In the `ci` and `deep` profiles,
  `test_sys_hyp_world` records its whole session (the recorder's
  `author_files` makes the machine's hooks author code) with the law models
  as an invariant, and `command_later` fires a command (destroy, park, park
  and resume, untag, tag, `collidable = False`, a clone, a timer, a move, a
  group destroy) from the seven callbacks `destroy_later` uses; a dead pick
  is replaced by a fresh actor and `settle` lets the callback come due at
  once, else most armed commands find their actor gone (reach guard
  `REQUIRED_M5`). No baseline, so no owed check: its oracles are the laws,
  the machine's invariants and the census. Acts are not in the machine yet.
  Its own `no_dead_calls` invariant excuses the rest of the contact an actor
  died in (C3 / L3, PB5): a handler that destroys both sides
  (`group[...].destroy()`) is followed by the contact's remaining enter
  handlers, the dead bodies' own `@collide_with` included, which `HypActor.hit`
  records as `collide_rest` (`TestRestOfContactExemption` bites both ways;
  deep tier 2026-10-22: before 5f2e226 the same case failed as L3 on the
  second side's exit, which hid it).
- **Tiers.** `test_laws_chaos` (quick, ~6 s): the machinery, the fixture, a
  seeded slice of 40 single-fault runs, the cells; canaries in gate.
  `test_laws_chaos_families` (SLOW + SPLIT): the laws fixtures, the four
  games, the programs, the examples, runs per member by profile, seed
  `SCENA_CHAOS_SEED`; deep adds every door × every command twice, every
  scenario and the tutorial steps.

Results (on the joint-response engine, 2026-10-15): the idle rewrite is the
plain run on every fixture, game, program and example; about 1 500 single-fault runs (every door × every command on
`s5_doors`, seeded slices on the laws fixtures and the four games) and a
two-fault run per example found no engine-internal error and no broken model
law at a sampled door; the M5 machine at `ci` found none either. The first
findings were the instruments' own: a "new waits" check that took a phase for
a pass, an exit check that looked past the command's step, and the recorder
reading a freed object's label at a reused `id()` (now a weak reference per
label confirms the object; a labelled type without one is a recorder error,
WP35), P3 counting a body with no `.vel` as movable
(it is infinite mass in the impulse; the recorder now records `has_vel`),
and C5 reading "once per contact" as "consecutive" (a destroy in one
contact's exit runs the other contact's exits inside it; now: each exit
handler once per contact). The gate's `ci` runs added three of the checker's
own: a sound's end compared across runs (it follows the audio clock, real
time: a frame later under load), an exit "owed" to the contact whose exit was
the one running, and a later handler's own destroy counted as the command's. The directed cells found two bugs,
both fixed: CD1 (L4: a hover target parked by the old target's exit still
lit) and CD2 (F3: the act's own `on_collide` already chosen for a contact ran
after the act ended); a decision (CD3), a documented rule (CD4) and a
message (CD5, fixed); [CD](#cd--chaos-doors-2026-10-15).

**What S7 taught.** A pass is a loop, not a phase: the first "new waits"
findings were the checker's, which took the whole tick as one pass. The
classes have more guards than one reads off the code: a watch whose owner
died is stopped by the round's drop test, its own drop test, the owner test
and the callback released at destroy, so a canary breaks the two a destroy
relies on. Single faults at sampled doors were all kept; every finding came
from a cell built from a suspect the code reading named — the random sweep
proves coverage, the directed cell finds the bug. A cell is a twin too
(lesson 4): the first CD2 cell's hook did not close over the act, so it was
the game's and ran on by design; only a hook the engine counts as the act's
shows the bug. Read the ownership rule before writing the cell.


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

**LB1 (2026-10-12): the bands.** The class 6 cells set the pads but left the
display windowed, and they checked only where the bright pixel lands, never what
lies outside the design rectangle. So a body half outside the rectangle spilling
into the maximized / fullscreen bands passed. Confirmed on a real window, then
fixed (Canvas Design, "Letterbox bands stay black"). `TestLetterboxBands`: red
bodies straddle the four edges on a world and a parallax layer, zoomed out, with
pads from `letterbox_view` (pad x and pad y), display maximized / fullscreen,
post off / on (`Grain` draws over the whole framebuffer). Every pixel outside
the rectangle must be black. The inner halves must draw, and the same frame
windowed must reach outside (not vacuous). Canary: the band mask removed. Lesson:
a pixel oracle for a transform also checks the region the transform must leave
untouched, and display cells set the display mode, not only its pads.

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



# Vec2 battery

Found 2026-10-17, after five fixes in a row (VI1–VI3, SV10, SV11) each sat on
a door the tests never sent that operand through. The battery crosses the
axes once, from the code, and checks every cell with invariants that need no
expected value ([Harness map](#harness-map): `vec2_support`).

**Axes.** Kind (how the author holds the vector, 16 kinds, every
`ContainerSlot(Vec2)` part pinned by a guard) × door (12 spellings that write
x / y, the in-place ones pinned to the class) × operand (15: good, `-0.0`,
`1e308`, `10**400`, inf, NaN, bool, list, a 3-tuple, a Vec2 holding NaN, a
Point, None, a string) × context (plain, frame batch, `on_change` callback,
frame) × read (cold, or length / angle read before the door). A cell costs
~0.3 ms in the plain context, so the full product runs in `quick`; contexts
cost more, so `quick` runs them 2-wise plus every kind × door × context × read
with one good operand, and `gate` runs everything.

**Invariants** (`vec2_support.INVARIANTS`, each with a planted bug that must
be reported): a refusal is Scena's (`leak`) and changed nothing (`partial`); an
accepted write leaves numbers a float holds (`number`: an int is legal, a
`10**400` is not), finite (`finite`), with length / angle that agree
(`derived`); a formula reading the holder shows what it holds, also after a
link's source changes (`follow`); a copy saved elsewhere did not move
(`kept`); a free twin written the plain way agrees (`twin`); a bad operand was
not taken (`bad`); a writable kind did not refuse a good operand outside the
designed refusals (`refused`), and a derived, linked or dead vector did not
take one (`accepted`). Designed exceptions are tables with their doc
(`DESIGNED_REFUSALS`, `DESIGNED_ACCEPTS`); open findings are globs in
`vec2_known` (shrink-only, stale entries fail `gate`).

**Layers.** The matrix (`test_vec2_doors`); black-box algebra with
inequalities and "author errors only" over every method
(`test_vec2_algebra`); twins and invariances (`test_vec2_metamorphic`); a state
machine for what needs a history — two holders and one vector, a link
installed before or after the vector is held (`test_hyp_vec2_machine`);
static guards (`test_vec2_guards`). Yield: [VB](#vb--vec2-battery-2026-10-17).

**Extending.** A new way to hold a vector is a `KINDS` entry (a new
`ContainerSlot(Vec2)` fails `test_vec2_guards` until it has one); a new
in-place spelling is a `DOORS` entry (the guard finds `__i*__`, `__lshift__`
and `do_*`); a new rule is an invariant with its canary in `TestOracleBites`.

# Persona probes

The earlier campaigns found bugs because each brought a new model of how
the engine should behave. Their probe writers had read the Guia closely, so
their expectations were the engine's own. A persona probe brings
expectations from elsewhere: a beginner who changes things by trial and
error, a Scratch kid (forever loops, broadcasts, clones), a Unity or Pygame
refugee (dt by hand, collisions by polling, managers), a copy-paster (Guia
snippets stitched across sections), an ambitious hobbyist (500 entities,
pause, save/load, an hour of play). The persona reads only what an author
can read (`docs/` and `examples/`), never `design/`, `tests/` or `scena/`.
Being unlike Unity or Pygame is not a finding when Scena is consistent and
logical; a habit the Guia encouraged is (DOC), and so is a message that does
not steer the author to the fix (ERROR).

**A probe** is a pair: `<name>.py`, the game as the persona writes it, and
`<name>.expect.py`, written before the game ever ran and never changed after
a run: `PLAY` (input steps in game seconds), `CHECKS` (`(label, seconds or
"end", predicate)` on the program's namespace), and optionally `SECONDS`,
`PARAMS`, `HZ`, `TIMEOUT`, `LAWS`, `MOTION`, `EXPECT_ERROR` (the error the
persona expects and what its message should say), `MIRROR` (E11).

**The runner** (`tests/laws/probe.py`, `python tests/laws/probe.py <folder>`)
runs each probe at 60, 30 and 144 Hz, each rate in its own process (a crash
or a hang stays there), under OS-level input (`game_harness.GameRun`
`os_level`, plus typed characters that have no alphanumeric key) with the
laws recorder attached. It raises flags, not verdicts:

- `ERROR`: the exception, its innermost frame (author or engine), the author
  line and the engine line; `HANG`: no result within the timeout, with the
  stack where it hung (a `while True` in `update` hangs a real game: the sync
  watchdog is off by default); `CRASH`: the process died;
- `CHECK`: a stated expectation that did not hold; `PACE`: a check, or the
  error, that differs between rates; `EXPECT_ERROR`: the expected error
  did not come;
- `LAWS`: a model finding not in `known.KNOWN`; `E1`: an edge event not
  within a frame of the 60 Hz run's (`equations.compare_paced`); `E11`: the
  bodies of a hand-written `<name>.mirror.py` (x mirrored about the design
  width) are not within 0.5 DU of the game's once mapped back, under
  mirrored input (LEFT↔RIGHT, A↔D, x → W − x). No transform mirrors an
  arbitrary program, so E11 runs only where the triage wrote a mirror;
- `WARN`: every warning the 60 Hz run raised; `GROWTH`: past 300 game
  seconds the run samples the live object count and the wall time per game
  minute instead of recording laws, and flags either one growing.

Frame counting in author code trips E1 and PACE by design (the runner's own
test uses it): the triage decides whether the author or the engine is at
fault. `test_laws_probe` (quick, ~7 s) runs one probe of each flag.

**Triage.** The verdicts of [Laws and equations](#laws-and-equations) (BUG,
LATENT, ACADEMIC, DECISION) plus DOC (the Guia led the persona astray),
ERROR (the message did not name the fix, or it pointed into the engine),
NOT-ENGINE (the persona's habit; the engine is consistent, and the row says
why) and PROBE (the probe's own mistake). Every flag is read to its
mechanism.

**Protocol and the freeze signal** (fixed 2026-10-19, before the first
round). A round is two campaigns written blind on one frozen commit, by
different models with different personas; neither sees the other's results
or the bug catalogue until both are triaged, and fixes land only after
both. The overlap estimates what is left (capture–recapture, Chapman:
N̂ = (n₁ + 1)(n₂ + 1)/(m + 1) − 1, remaining = N̂ − distinct found). The
agents share training and blind spots, so the overlap reads high and the
estimate low. A 1.0 candidate needs two rounds in a row with:

| Condition | Value |
| --- | --- |
| BUG findings per campaign of n probes | ≤ ⌈3n/40⌉ |
| BUG findings in law-governed areas (frame, lifetime, contacts, input, timers) | 0 |
| Remaining BUG estimate | below 5 |

**Round 1 (2026-10-19 / 20).** Commit b5054b0; A (Opus) 44 probes, B
(Sonnet) 40. BUG: A 2 (limit 4), B 0 (limit 3); law-governed BUG 0;
remaining BUG estimate 0 (no overlap on two captures: no information).
Round 1 meets the table, the first of two. Broad estimate (BUG, ERROR,
DOC, DECISION): n₁ = 13, n₂ = 10, m = 2, N̂ ≈ 50, about 29 unfound. The
runner's own errors were fixed before round 2 (`test_laws_probe`), and the
fixes landed after both campaigns were triaged ([PP](#pp--persona-probes-round-1-2026-10-20)).

**Round 2 (2026-10-20).** Commit 4220f07, models swapped. A (Sonnet:
tinkering teen, teacher) 31 probes; B (Opus: Godot / Processing refugee,
game-jam crammer) 22. BUG: A 1 (limit 3), B 1 (limit 2), but B's is in a
law-governed area (contacts, R2-2), so **round 2 does not meet the table:
the streak is 0**, and a 1.0 candidate needs rounds 3 and 4. BUG estimate
≈ 1 remaining (1 + 1, no overlap); broad estimate n₁ = 4, n₂ = 7, m = 1,
N̂ ≈ 19, about 9 unfound (round 1: about 29). **Every round also re-runs
the previous rounds' probes on the new commit** (the runner, same flags
diffed): round 2's re-run found three regressions of round 1's own fixes
(PP4-R, PP10-R, PP18-R) that neither blind campaign reported.

**Round 3 (2026-10-20).** Commit fe00fda, models swapped again. A (Opus:
deadline student, puzzle designer) 20 probes; B (Sonnet: web developer,
physics tinkerer) 24. BUG: A 0, B 1 (R3-2, resolve motion: not a freeze
area). R3-1 (an author's own field raised on a destroyed actor, against the
Guia) was the engine's documented rule, so a DECISION (user, 2026-10-20:
the rule changed, reads now work). **Round 3 meets the table: streak 1**;
round 4 decides the freeze. BUG estimate 0 remaining. Broad estimate
n₁ = 10, n₂ = 7, m = 1, N̂ ≈ 43, about 27 unfound (round 2: 9): each persona
brings its own vocabulary (`addEventListener`, `friction=`, a half rename),
so the message surface is the open part. The re-run of rounds 1 and 2
found no regression.

**Round 4 (2026-10-21).** Commit c7e8626 (VB17 merged), models swapped
again:
- A (Sonnet: animator, level builder): 20 probes.
- B (Opus: two players on one keyboard, simulation builder): 23 probes.

Both triagers reported 0 BUG. The coordinating triage read A3 again: the
tick ran due timers before tweens against Scena Design's own order. The
user scored it a BUG in the timers area (R4-1), so **round 4 fails the
table and the streak is 0**: a 1.0 candidate needs rounds 5 and 6.

- BUG estimate: 0 remaining.
- Broad estimate: n₁ = 4, n₂ = 3, m = 0, N̂ ≈ 19, about 12 unfound (round 3: 27). With no overlap it is the loosest form.
- The re-run of rounds 1–3 found no regression. It did find a round-3 E1 flag that the campaign's triage had listed as absent; it is ACADEMIC (V1).

Lesson:
- A triager's verdict on a rule question is read again by the coordinator against the design docs, not only against the Guia.
- A3's triager saw the behaviour and the bucket order. It did not see that Scena Design named the other order.

**Round 5 (2026-10-21).** Commit 872a78c, models swapped again:
- A (Opus: UI / menu designer, rhythm-game maker): 22 probes.
- B (Sonnet: procedural generator, arcade cloner): 28 probes.

Each brief now told its triager to check a "that is the rule" verdict against the design docs. That is the round-4 lesson.

- BUG: A 1–2 (R5-1, a crossfade ran a replaced `forever` loop's `on_done`, against Sound Design; R5-2, `CheckBox.checked` was the cell, the PP2 class in one more widget), B 0. None in a law area.
- **Round 5 meets the table: streak 1**; round 6 decides.
- BUG estimate: 0 remaining.
- Broad estimate: n₁ = 5, n₂ = 3, m = 0, N̂ ≈ 23, about 15 unfound (round 4: 12).
- The re-run of rounds 1–4 found no regression.

**Round 6 (2026-10-21).** Commit bbc094e, models swapped again:
- A (Sonnet: interactive-fiction writer, parent with a small child): 26 probes.
- B (Opus: game-feel polisher, board / card maker): 22 probes.

- BUG: A 0, B 0; none in a law area.
- **Round 6 meets the table. With round 5, two rounds in a row: the freeze signal is met (2026-10-21).**
- BUG estimate: 0 remaining.
- Broad estimate: n₁ = 1, n₂ = 5, m = 0, N̂ ≈ 11, about 5 unfound. The six rounds gave about 29, 9, 27, 12, 15 and 5: the message surface narrows but does not close. Every round still finds a few messages and Guia lines.
- The re-run of rounds 1–5 found no regression.
- What the signal means: authors of these kinds, writing from the Guia, no longer meet wrong behaviour often enough for two blind campaigns to find it. It says nothing about kinds of game no persona wrote.
- The signal is necessary for 1.0, not sufficient. The maintainer decided (2026-10-21) to stay on 0.9 until tests with real users: imagined personas share the models' blind spots, which the independence caveat above names.


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
| **quick** (T1) | Before calling any change done | Every module except `SLOW`, `dev`, canaries off | ~50 s (2026-10-10: 214 jobs, ~410 s summed; it was ~25 s at 107 modules; not timed on the Mac since the tier grew). Windows laptop (i5-1245U: 2 performance + 8 efficiency cores, 10 workers): ~11 min (2026-10-27, 0.10.1: 348 jobs, 686 s wall, ~6 840 s summed; 0.9.0: 623 s) |
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

Measured on the Windows laptop, 2026-10-27 (0.10.1, 348 quick jobs: 686 s wall, ~6 840 s
summed; a second run 717 s, so not a cold cache):

- **The `SLOW` line is read on the Mac.** Alone on the laptop, 38 quick modules pass
  15 s (~1 265 s together; `test_background` 147 s, `test_prog_bouncing_balls` 58 s
  against 12.5 s on the Mac), and the same module alone varies 2–3× between runs (its
  process lands on a performance or an efficiency core). Moving them would take most
  pixel and example checks out of quick on every machine, so `SLOW` stays as the Mac
  measures it.
- **Pure Python runs near the Mac's speed; pixels do not.** `test_vec2_doors` is 8–9 s
  alone (~7 s on the Mac). The skia wheel there (144.1) is built with MSVC, and its CPU
  raster pipeline costs ~100 ns a pixel for a plain translucent fill and ~14 µs a pixel
  for `Embers` (`scripts/bench/perf_raster.py`; on the Mac ~1.4 ns and ~360 ns): a module that draws 2000 × 1200
  headless frames is slow there for that reason alone (WP50). The fix is the frame's
  size (rule below), not the tier.

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
  ~440 s CPU); tutorials 17–26 doubled it and it timed out the quick tier (2026-10-10).
  A suite that grows with content (one program per tutorial step, per example) is
  generated **one TestCase class per unit of content** in its own `SLOW` + `SPLIT`
  module, so the gate runs one job per unit and a new unit needs no edit; the cheap
  checks of the same content stay in a quick module.
- **Tutorials.** `test_tutorials` (the pages, no run: extraction, endpoints, recaps,
  focus, syntax; ~1 s) is in quick. `test_tutorial_steps` runs every step and `try`
  box for 600 frames; it is `SLOW` and `SPLIT`, one class per page (`TestSteps05` is
  `05-naves.html`, `TestStepsA` the appendix `A-depuracao.html`: an appendix page
  is named by one capital letter, its fragments run like steps, and it has no
  `examples/` file and no recap — `test_tutorials.is_appendix`), so gate and deep
  run every step as ~30 jobs (each under ~45 s;
  all of them ~45 s wall / ~320 s CPU on 8 workers with the runner's bytecode cache
  (Portuguese only; with the English pages, 2026-10-22: ~216 s wall / ~840 s CPU in one
  process pool, still one job per page in the gate),
  ~64 s / ~500 s without; 2026-10-10). Quick still runs each tutorial's last
  step, as its `examples/` file (`test_scripts_run`, 30 frames), and `test_tutorials`
  holds the file equal to the step. Guard: `test_run_tiers` (one gate job per page,
  none in quick). The English pages (`docs/en/tutorial/`) get the same page checks
  and one step class each (`TestStepsEn05`); `test_tutorial_parity` (quick, ~2 s)
  pairs every English code block with its Portuguese twin under one rename per
  page, so a fix that lands in one language only fails before any run
  (design/Docs Design.md, "The English tutorials").
- **A module destroys what its tests made.** A leftover with a group fails at any
  count: group names are process-wide, so one tagged actor answers every later
  `group[...]` and moves under every later `resolve` on its name (deep serial pass
  2026-10-22: test_collision_floor's `heroi` / `chao` Rects broke test_concave and the
  Ninja / caverna games; guard `test_leftovers.TestChildRun.test_one_tagged_leftover_fails`).
  A reset must reach every long-lived holder of graph nodes, not only Containers:
  `init_scena_system()` left the cells of `st` (a `State`) on the discarded graph, so
  every later link reading a cell an earlier module made froze (~30 serial failures;
  `state._rehome_state_cells`, guard `TestGraphResetRebindsEverySource`). Leftovers live on in the serial pass: every
  later `census()` / `full_collect()` walks them and every `SystemWorld` parks and
  resumes them (`test_shapes` left 1905 roster items, `test_reactive_matrix` ~163 000).
  A module that builds actors without destroying them declares
  `setUpModule, tearDownModule = module_sweep()` (`tests/leftovers.py`). Every tier
  enforces it: `run_tiers.py` runs a `LeftoverCheck` after each module, which fails on
  one live actor the module made (WP43; it was `LIMIT` = 50 roster items until 2026-10-24,
  and 26 untagged actors under it broke three later modules, WP42) and names each with
  the line that made it. Only parts may stay (up to `LIMIT`): the lazy parts of an
  actor the module made at import, before its mark. Measured on the serial pass
  (2026-10-09, 48 modules swept): 45 failures → 6 (the program-run censuses that saw
  other modules' shapes), 7854 s → 2883 s of CPU. Counts can grow with the
  budget: `test_construct_failure` left 2 at `dev` and 216 with canaries on, so the gate
  is where such a module shows. Leftovers once exposed an engine bug (a hidden Point on a
  layer, through the serial pass): when a leftover state matters, build it inside an
  isolated test rather than relying on a neighbour to leak it.
- A module that starts and ends its own global state (new singleton, new registry)
  needs no runner change; a new **env switch** goes in `Tier` / `tier_env`.

## Continuous integration

`.github/workflows/tests.yml` runs on every push to `main`, on every pull request,
on a push to a `ci/<anything>` branch (CI without a pull request) and by hand
(`workflow_dispatch`). It checks the README's promise: Python 3.12–3.15 on Windows,
macOS and Linux. Release builds are a separate workflow (`release.yml`, [Scena
Design.md, "Compatibility and versions"](Scena%20Design.md#compatibility-and-versions)).

| Cell | Python | Runs |
| --- | --- | --- |
| `ubuntu-latest` ×3 | 3.14 | the wheel import, then the whole **quick** tier in three parts (`quick --part K/3 -j 4`, one part per runner job) |
| `ubuntu-latest` | 3.12, 3.13, 3.15 | the wheel import, then the **smoke** modules (`SMOKE` in the workflow, `focused -j 4`) |
| `macos-latest`, `windows-latest` | 3.12, 3.13, 3.14, 3.15 | the same: the wheel import and the smoke modules |

Python 3.15 has no miniaudio wheel (1.71), so its cells also check the install
left miniaudio out (the `pyproject.toml` marker, [Sound Design.md, "No
miniaudio"](Sound%20Design.md#no-miniaudio)) after the wheel import, then build it
from source for the tests. The silent path itself runs on every cell
(`test_audio.TestWithoutMiniaudio` blocks the import).

Why this shape (first runs, 2026-10-26). The runners are slow next to the Mac:
quick took 151 s wall on the Mac (8 workers, 1 150 s summed) and 505–700 s on one
4-vCPU Ubuntu runner (2 000–2 750 s summed), ~11–12 min with setup, for each
Python. Quick on all three Pythons found nothing the 3.14 run did not (the same
two failures, the same numbers), so quick runs once, on the corner the Mac never
runs (Linux, the newest Python), split over three runner jobs. `run_tiers.py
--part K/N` takes the K-th part of the plan: jobs go slowest first to the
least-loaded part, label breaking ties, so the N runners that plan the same tree
agree (`test_run_tiers.TestPart`). The CI has no `timings.json`, so there the
parts balance by count: 116 jobs each, 150–243 s wall (580–930 s summed), 9 563
tests in all, the Mac's count; the whole run took 4 min 48 s. Smoke took ~30 s on macOS and 70–80 s on Windows (a job
there is ~2.3× its macOS time): quick on Windows would take ~11 min a cell.

Every cell builds the wheel (out of the checkout: setuptools' `build/` would
otherwise hold a second copy of `scena` for the source scans), installs it with the
`test` extra, and imports `scena` and `scena_editor` **from site-packages**, with
the working folder outside the checkout, plus `scena-editor --help`. A file the
wheel leaves out, or a native dependency (skia-python, glfw, numpy) with
no wheel for that Python and OS, fails there (miniaudio is left out where it has none). The tests themselves then run from the
checkout (`run_tiers.py` puts the repo root first on the children's path), so they
test the source, not the wheel.

Everything runs headless: no window (GLFW is never initialised), no GL context
(post FX take the CPU path, `orchestration`'s "No context = headless"), audio
through the offline mixer. No display server or GPU is needed. The one system
dependency: skia-python's Linux wheel loads `libEGL.so.1` / `libGL.so.1` at
import, which a desktop Linux has and the bare runner image does not (the first
run failed `import skia` there), so the Ubuntu cells install `libegl1` and `libgl1`
(the README's install section tells Linux users the same).
Linux's GLFW (pyGLFW's wheel) is also built with C asserts on: a GLFW call with
no window aborts the process (rc -6) where macOS and Windows return quietly
(WP48). Never hand GLFW `fw._window` without checking it for `None`.

The smoke set is one module per area that differs between platforms: the API
surface, a frame, shapes, collision, drawing, text and fonts (`font_support` finds a
system face on each OS), audio, level files, the editor's launch and strings, every
example played headless (`test_scripts_run`), and the static Windows / Linux
portability guards (`test_platform_portability`, the WP rows). A module that guards a
platform difference belongs in `SMOKE`.

What CI does **not** cover:

- **gate and deep.** Canaries, the `ci` / `deep` Hypothesis profiles, `SLOW`
  modules and the serial pass stay local (bug loop steps 5 and 8): their budget
  (gate 4–14 min on 8 workers of a 10-core Mac, deep 2 h +) does not fit a push check, and the
  Windows gate needs `-j 4` for memory (WP30).
- **The whole quick tier on macOS and Windows.** Only `SMOKE` runs there; quick
  runs locally on macOS before every change, and on Windows by hand.
- **A real window, GPU, audio device or input device.** No cell opens a window or a
  GL context, plays to a device or reads a gamepad; the live window, the GPU
  scene-RT path, vsync and frame pacing are checked by hand.
- **The Guia and tutorial pages in a browser**, and the Pages build (GitHub builds
  Pages from `main:/docs` on its own).
- **Timing.** A runner is slower and noisier than a dev machine: perf ratios
  (`scripts/bench`) and wall budgets stay local; a test's absolute ms budget is a
  catastrophe guard only (`tests/README.txt`, "Timing").

A red cell is a finding like any other: the bug loop applies, and a platform-only
failure gets a WP row (or its own class) in the [Bug catalogue](#bug-catalogue).


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

- **An `@on_change` a test registers outlives the test.** A per-cell context
  that ran its step in a callback left one handler per cell: each kept its
  subject alive (381 shapes over the leftover limit) and every later poll
  walked them all (the Vec2 door matrix took 155 s at `ci`, 9 s once each cell
  called `unregister_event(cb)` in a `finally`). Unregister what a cell arms.

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
  first) and keep each side's best block (WP18). An absolute bound sized on
  the Mac failed on a slower Windows machine even alone (WP22: 0.08 s, read
  0.12-0.17 s): the reference is a Python loop timed beside the code. When
  the bug is work (a search that grows with the atoms), count the work and
  read no clock: an example's test that held a 0.1 s frame under 1 s read
  1.12 s under the quick tier (WP49). Example and game tests read no clock.
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
  unequal to the `C:\t\a\b` the code returns. The `/` part may come through
  a name: a loop or comprehension over `("scripts/smoke", ...)`, a module tuple
  of `/` paths (`EXTRA`), `rel = "a/b"` (WP23). Guard:
  `test_platform_portability.TestJoinedPathsUseOneSeparator` (WP19, WP23).
- **A hang budget starts after the imports.** A child that compiles Scena
  (`PYTHONDONTWRITEBYTECODE`, a cold machine, a loaded tier) can spend most of
  a few seconds importing; a timer armed before that dumps the import, not
  the hang. Arm it once the imports are done; the parent's own timeout is a
  backstop sized for the imports too. Guard:
  `test_laws_probe.TestHangClockStartsAfterImports` (WP25).
- **A tool's piped output is cp1252 on Windows**, with `errors="strict"`: a
  `print` of `→` crashes it. A tool that prints such text calls
  `sys.stdout.reconfigure(errors="backslashreplace")` at its entry. Guard:
  `test_platform_portability.TestToolsPrintOnACp1252Stdout` (WP28).
- **A symlink needs a privilege on Windows** (Developer Mode or an
  administrator; else WinError 1314). Link with `source_support.link_entry`:
  a junction for a folder and a hard link for a file need none, and a
  temporary folder's cleanup removes them without touching the target. Guard:
  `test_platform_portability.TestLinksNeedNoPrivilege` (WP29).
- **Workers × children must fit the commit limit.** The laws, scripts and
  tutorial modules start their own pools of Python children (up to 8 each)
  under every tier worker. Windows commits each child's heap: on a 16 GB
  machine the gate's default `-j` (CPUs − 2) passed RAM + page file, and
  native code aborted (`0xC0000409`) or paged past its timeouts. Run the
  gate there with `-j 4` (WP30).
- **A gate job's work is a count, sized for a slow machine.** A job that
  loops over a growing folder grows with it, and a fast Mac hides how close
  it is to its timeout: a job that takes half its budget here times out on a
  machine 2.5× slower. Size a job by what it does, not by a time measured on
  the Mac: the laws' example checks are split into classes of at most
  `test_laws_equations.RUNS_PER_JOB` runs (48: 600-frame runs at ~25 s on a
  machine 3× slower, ~2 cores' worth per job in a busy gate, a third of the
  1 800 s timeout), and the number of classes follows the folder
  (`_shard_plan`). Their program halves run serially in one process (one
  engine per process): classes of program × scenario units of at most
  `PROGRAM_RUNS_PER_JOB` runs (120: ~2 s a run in the Mac's loaded gate,
  ~5 s 2.5× slower). Below `deep` the laws run one of each translated example
  pair (`test_scripts_run.law_scripts`; the pair is one program:
  `test_example_translations`). Guard: `TestShardPlan` (no example alone past
  the cap) (WP33). The same for every job past a third of its timeout: the
  E1 / E6 example checks are shard classes too, the chaos families one class
  per fixture, per game and per group of S5 commands (`COMMANDS_PER_JOB`;
  `TestS5Jobs`), and a class of heavy tests gets a smaller runner chunk
  (`run_tiers.CHUNKS`: `TestMethodJunk`, 40 examples a test, 20 tests a job)
  (WP34). A long job measured in a loaded gate may be contention, not work:
  measure it alone before splitting (`TestMethodJunk`: 216 s alone, 1 433 s
  in the gate).
- **A headless frame is 2000 × 1200.** With no window, `init()` sets the
  design size but the framebuffer keeps the framework's default, and
  `SystemWorld` draws into a raster surface of `fb_width × fb_height`. A test
  that runs heavy passes on it (post effects, background fields, any SkSL: it
  runs on the CPU) pins a small framebuffer for its world
  (`mock.patch.object(fw, "fb_width", 200)`), or its time follows the machine's
  speed at 2.4 Mpx a frame (WP27). The machines differ most here: on the
  Windows laptop one `Embers` frame at 2000 × 1200 is ~34 s, a plain fill
  ~0.2 s (WP50; `python scripts/bench/perf_raster.py` prints this machine's rows).
- **A venv's `python.exe` is a launcher on Windows**: `Popen(sys.executable)`
  starts it, and it starts the interpreter as its own child. `kill()` and
  `wait()` end the launcher; the interpreter goes a moment later, still holding
  the files it wrote. A temporary folder around a killed child is
  `TemporaryDirectory(ignore_cleanup_errors=True)` (WP26).
- **A skia call that borrows a buffer keeps no reference to it**
  (`Pixmap`, `Data.MakeWithoutCopy`, `MakeRasterDirect`, `installPixels`,
  `fromarray(copy=False)`): a temporary passed there may be freed before skia
  reads it. The Mac allocator left the freed bytes alone; the Windows one
  wrote into them (engine bug WP21). Guard:
  `test_platform_portability.TestSkiaBorrowedBuffersStayNamed`.
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
  bundle values. So does the engine's: a thread that reads another thread's
  frame into a local of its endless loop keeps that whole stack (WP20, the
  stall watch). In state machines keep int handles into a pool the machine owns.
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
- **So does a census taken without a collect.** The roster (`registry.live`)
  is a `WeakValueDictionary` like the graph: a throwaway an author drops
  without `destroy()` (a measuring Box, whose center Point registers; a
  reference cycle) stays in it until a full GC pass. A `census(collect=False)`
  pair compared for "the call moved nothing" takes both censuses inside one
  `gc_paused()` block, or a pass that lands between them moves
  `registry.live` (O12). Pausing is stricter, not looser: garbage the call
  itself registers stays in the second count. Same guard
  (`census(collect=False)` / `surface_census(collect=False)` follow a settle).
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
- **A plant does not reach a look interned before it, and a look built under
  it stays interned after it.** Looks are interned per constructor key and
  bake some state in `__init__` (`Metal(color)` resolves its rim once from
  `_metal_edge`). A canary that plants a function a look calls at
  construction misses the instance an earlier test built (the knob sweep
  still sees the real rim), and the plant-built instance poisons every later
  test (O11). `assert_catches` and `game_harness.run_patched` run the plant on
  empty intern caches (`hypothesis_support.fresh_interns`) and put the old
  entries back. A new intern cache joins `_INTERN_CACHES`
  (`test_knobs_take_effect.TestCanaryPlantsReachInternedLooks` fails
  otherwise). A canary written outside these runners (a bare `mock.patch`
  around a render) wraps its plant in `fresh_interns()` itself.
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
| A store set, a cached reader stale (GX2, GX21, GR17-link, GX18) | Flip and link tests read once, after the verb | A cold cache recomputes on the read; the stale value shows only when it was read before | Sentinel I-heading on every outermost call; probes that read first |
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
   that moves no point recomputes nothing (GX2) — and "no point moves" is not
   only a degenerate shape: a placement on the mirror axis is one too (GX21).
   A probe reads the value before the verb (twice: the first read makes the
   Derivate live and leaves the shape dirty), or the cold cache hides the bug.
   Nor is "the store turns" the only input: a Derivate that reads the flip
   flags themselves changes at a heading the flip leaves in place (GX22), so
   sweep the fixed points of each verb's map (0 under `flip_y`, 90 under
   `flip_x`) as well as a generic pose.
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
| H1 shadow (degenerate bases) | 6 | GX1, GX2, GX3, GX5, GX22 |
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

## What the fixes of 2026-10-10 / 11 taught (review of 2026-10-12)

A review of every bug fixed in those two days (AC, SV, RA, SU, AL, O9, O10,
R10, G20, TU7, AH1, KN1, KN2) against this catalogue: most had their entry and
guard; AH1, KN1 and KN2 had none. Writing the class guard for each found more
members (AH2, KN3, KN4).

1. **A fix that lists its funnels by hand misses some.** AH1 refused an
   `async def` at every door its author thought of (hooks, decorators,
   `on_done=`, script hooks); the predicates, conditions and formulas were
   not on the list, and there a coroutine is worse than ignored — it is
   truthy (AH2). The guard enumerates the doors from the public surface
   (`TestEveryCallbackDoor`: every parameter named like a callback or
   annotated `Callable`, every such setter, inherited doors once) and a new
   door fails until it has a case or a reason. A plain slot is not a setter,
   so the scan cannot see it: `Collider.on_collide` was a slot written through
   a class-wide `__setattr__` hook, and it took an `async def` unseen until
   the perf campaign (2026-10-12) turned the three callbacks into properties
   and the guard listed them. A callback the author can set is a property.
2. **A knob is tested on the path where it works.** `Metal(color)` (KN1) and
   `tile_mode` on a fitted Wallpaper (KN2) were accepted on every path and
   reached the pixels on none, or one. Each test had used the one style or
   fit where the knob mattered. The guard sweeps every exported look × every
   `style` × every knob, and every Wallpaper fit × every image knob, and asks
   for different pixels (`test_knobs_take_effect`). Its first run found the
   knobs that are documented for one style only and accepted on the others
   (KN4, now refused) and a style where the same knob raised Python's own error
   (KN3).
3. **Run a new guard on the pre-fix engine, case by case.** On the code
   before AH2, the `resolve(only=)` case passed: its arm ran no frame, so
   `only=` was never asked (and once asked, the call backstop refused it
   anyway). A case that cannot fail is found only by watching it on the bug.
4. **A pixel cell needs a clock and a backdrop that can show the knob.**
   The first sweep advanced the clock between the two draws of a cell (every
   animated look "changed"), then held it at zero (no `speed` could show);
   the cell now runs at one clock time past zero, checks two draws of the
   default agree, and clears to a colour no default look uses (`Stroke()` is
   black on black).
5. **A changed meaning turns tests vacuous quietly.** SV5 (a helper that
   returned the number after the 0.8.0 flip), HV1 (two blank frames compared)
   and O10 (shards that ran a quarter of the cells) all passed. Canaries and
   the gate catch them; `quick` skips canaries. See [Recurring bug
   classes](#recurring-bug-classes), "A test turns vacuous".
6. **"Some pixels changed" is not "the knob showed"** (2026-10-13, KN5). The
   first seeded `set_color` sweep counted changed pixels: Rim, Ink and the
   other outline looks passed, because `set_color` repaints the body while
   the seeded outline stays. Compare with what the knob should produce (the
   look worn on the new colour, or the look given it), not with the frame
   before.

### Class guards written from this review

| Guard | Lesson | Found (would have caught) |
| --- | --- | --- |
| `test_async_hooks.TestEveryCallbackDoor` (doors from the surface; each refuses an `async def` at the call or when it fires, with no "never awaited"; canary: the group predicates without the check) | 1, 3 | AH1, AH2 |
| `test_knobs_take_effect` (every look × style × knob, every Wallpaper fit × knob, every Wallpaper fit × `Texture` knob: different pixels or a listed reason; shrink-only lists; canaries: `Metal` without its tint, a fitted image that ignores `tile_mode`, a Wallpaper that drops a Texture's angle / shift / alpha) | 2, 4 | KN1, KN2, KN3, KN4, SK4 |
| `test_visual_color_param.TestSetColorShowsWhereColorIsTaken` (every wearable look × style: takes `color=` ⇔ `set_color` shows and no warning; seeded looks must draw like the shape-following look worn on a shape made with `color=` the new colour, or sit in the shrink-only `SEED_WINS`, empty since 2026-10-13; `test_deseed_keeps_every_knob`: the sibling keeps every non-colour knob; canaries: `Metal._unseed` → `None`, `Rim` / `Laser._unseed` → `None`, a `Rim._unseed` that drops `width=`) | 2, 6 | KN5 |
| `test_visual_color_param.TestSetColorIsColorParam` (every look × style, seeded and not: `set_color(X)` draws and leaves what `color=X` gives; `.fill` / `.line` before or after `visual =` draw the same; `line_width` / `blend` / `dash` / `line_cap` / `line_join` likewise, kept by `visual = None` (Shape and Sprite blit), and the constructor's `line_width=` is written before the look; a write on a seed's channel beats it; an outline seed is the outline only; no draw at any quality re-applies; canaries: exact-line set_color, raw channel write, raw knob write, outline seed dyeing the body) | 2, 6 | KN7, KN8 |

## What the game-behaviour probes taught (2026-10-14)

The [PG](#pg--game-behaviour-probe-campaign-2026-101314) findings: 34 ids in
32 rows, none of them caught by an existing test except RD1 (the armada
random pilot in gate).

1. **Author-shaped probes under real input find what white-box games miss.**
   `test_scripts_run` gives every example 30 idle frames, and a smoke
   script's on-screen checks are never asserted, so no test released a key
   held across an act change, dragged a HUD item onto the world, or let a
   lift carry a rider down. The probes were games an author writes, played with held keys,
   drags and focus changes for hundreds of frames; most findings sit at a
   seam between two systems (a handler and `resolve`, a widget and
   `mouse.press`, an act change and a held key).
2. **What a handler does is part of the input space.** A destroy, an
   `untag` or group change, a park, a focus change or a `change_act` inside a
   handler changed what the rest of the same dispatch saw: who scored
   depended on spawn order (PG-PB5), the ball stopped bouncing (PG-PE5), exit
   handlers vanished (PG-PB1, PG-PB3), an auto-repeat reached a new box
   (PG-PD3). Test every side effect a handler can have against the rest of
   its frame, in both creation orders.
3. **Run motion at 30, 60, 144 and 240 Hz.** The lift rider lost its contact
   from 60 units/s at 60 Hz but from 30 units/s at 144 Hz (PG-PB4); the
   bounce off a removed brick is guarded at 30 / 60 / 144 Hz because the
   normal it uses (the swept TOI one or the detection one) depends on how far
   a frame moves the ball (PG-PE5). A rider on a sideways lift was carried
   97 % of the lift's motion at 30 fps and 1 % at 240 (PG-PB2), and an idle
   body crept down a ramp by one skin's sideways part per frame, so faster
   at a higher frame rate (PG-PE2). A rule tested at one pacing is a rule
   about that pacing.
4. **A name the engine looks up needs a guard where it is written.** A hook
   is found by name, so `def update(self, dt)` in an act, `on_colide` on a
   shape or `on_key_down` in a class was silently never called (PG-PA3,
   PG-PC5). The guard runs at the class line, against the engine's own hook
   list, with the near-miss rule the ink guard already used for writes.
5. **A tolerance in a test is a claim about the bug it lets through.**
   `test_collision.test_walk_speed_holds_and_idle_slope_does_not_creep`
   allowed an idle body 3 units of drift in 40 frames, and the creep was 1.2
   (PG-PE2): green, and still a visible slide over a minute of standing (24
   units in 10 s on a 30° ramp). It is now tightened to 1e-6. Set a
   tolerance from what an author would see over the length of a game, not
   from what one run happened to produce.

## What the laws campaign taught (2026-10-14 / 15)

A written constitution ([Laws.md](Laws.md)), a model of the discrete layer
and equations, run over every program, game, example and tutorial step
(details: [Laws and equations](#laws-and-equations)). Engine findings: LW5
(a bug, fixed), LW2, LW7 (decisions, fixed 2026-10-15 with LW8), LW6 (a
decision, applied 2026-10-16), LW3, LW4 (academic); harness: LW1, LW9. S7, the chaos doors
(2026-10-15 / 16): CD1, CD2 (bugs, fixed), CD3 (a bug, fixed by per-rule
contacts after a design session), CD4 (today's rule), CD5 (a message);
[CD](#cd--chaos-doors-2026-10-15).

1. **A model's first findings are its own.** In every stage the first
   divergences were wrong laws, not engine bugs: "its own hook", the act's
   own teardown, the seal, an explicit `flush()`, a Sprite's hitbox, a
   carried rider, a walker without `vel.x`. Each fix moved a law to the
   sentence in a companion doc. A law worded from the code agrees with the
   code; worded from the doc, it finds where they part.
2. **An observer is code with bugs of its own.** The recorder held author
   classes, kept generator locals alive, read slots as missing, read an entry
   point as a delivery. E0 (neutrality, survivors included) and the
   self-checks found each one; they stay on.
3. **A canary that does not bite counts the guards.** A parked body leaves
   collision and fails the in-play check; a destroyed body's contacts are
   ended, its collider dropped and pruned. A plant must break every guard of
   the class, or it proves nothing; a plant must also be the class (a debt
   dropped after a fire), not its caricature (a timer silenced). A plant
   that keeps what the engine drops must also mark it for the engine's
   skips: the C7 plant kept a destroyed body's collider registered, its
   shapes emptied with no pose bump (a live engine unregisters it), so the
   step snapshot skipped it and `SCENA_VERIFY_POSE_REV` raised before the
   model saw the contact. The canary passed by hand (`python -m unittest`,
   verify off) and failed in gate (canaries run only in gate and deep,
   where `run_tiers` turns verify on). The plant now marks the kept
   collider stale, and both modes refresh it alike. Run a new canary with
   verify on and off.
4. **An equation is only as good as its twin.** A twin without the example's
   art, a partner never registered, a scene by chance mirror-symmetric, a
   wall clock nobody pinned, two draws from one random stream: each looked
   like an engine divergence. Run the twin twice, run it in the other
   harness, and pin every clock it compares.
5. **Agreement beats prediction.** E10–E12 hold to the last bit with no
   expected value written; E3 found that ties go by creation order; E1 and
   E13 measured a frame-rate dependence (LW7) no unit test had a reason to
   look for; E8 found LW2 by comparing two ways an author breaks a brick.
6. **Triage by cause, not by size.** A 0.1 px mirror asymmetry from a sign
   error would be LATENT; a 1 px difference from an author's Euler step is
   ACADEMIC; a character typed into a box is a BUG at one keystroke. Every
   divergence was traced to its mechanism before its verdict.

7. **A change to what identifies a thing reaches every checker's keys.**
   CD3 made a contact per rule. The C5 check still keyed "this handler
   already exited" by the pair and the function, so one class method that
   both bodies run, each under its own rule (`A.unhit(B)`, `B.unhit(A)`),
   read as one handler running twice. The engine was right; `quick` and the
   focused modules passed; only the world machine at `ci` (a tag gained
   mid-contact, then a group destroyed) found it, in the merge gate. A
   handler is now the function **and** the side it runs for. When a change
   moves an identity (a contact, a handler, an owner, a press), search the
   models and the equations for keys built from the old one, and add a
   synthetic case for each direction.



## What the persona probes taught (2026-10-20)

Round 1 ([Persona probes](#persona-probes), [PP](#pp--persona-probes-round-1-2026-10-20)):
84 blind probes found 2 BUGs, 10 messages, 1 DOC and 8 decisions, and no
law-model or E11 finding. Five lessons:

1. **The bugs were in the author-facing surface, not the engine's core.**
   Every instrument before this one asked whether the engine does what it
   says; personas asked whether an author can tell what it says. Ten of
   21 findings were messages or silent no-ops (a name nobody calls, a
   `while` with no word), and both BUGs were value semantics (`==` on a
   colour, a field that read as its cell). Both bug classes are now guarded:
   a value type with identity `==`, and engine code reading a slot by its
   descriptor.
2. **Write the second try.** A message is tested by the author's next
   attempt from the message alone: 33 second tries found that `clock.tick`,
   `Destroy(x, t)` and `transform` messages led nowhere, while the
   `DestroyedError` one led straight to the fix.
3. **A runner is an observer with bugs of its own.** Five runner errors
   (a drag a frame late, a shared save file, a missing key name, modifier
   bits never set, a cut stack) produced E1 and CHECK flags before any
   engine finding. The fixes landed first, each with its test failing on the
   old runner (`test_laws_probe`).
4. **Blind, two models, overlap small.** A and B shared 2 of 21 findings.
   The broad estimate (Chapman, all real verdicts) is about 50, so about 29
   message and rule defects remain unfound. The BUG estimate (2 + 0, no
   overlap) carries no information. Two campaigns that share so little
   say the surface is wide, not that the engine is clean.
5. **Personas probe habits, not features.** The refugee's `self.vel = speed`
   (three probes), `cooldown -= dt` timers, `Update` hooks and the copy-
   paster's renamed `run` came from habit, and the Guia's "De outro motor"
   table now answers them before they become messages.

## What the Vec2 battery taught (2026-10-17)

1. **A link is two doors: the install and every later pull.** SV10's matrix
   read the formula right after each write; a link installed on a held vector
   showed its first value and never another (VB3). A cell that checks a link
   checks it again after the link's source changes.
2. **Every way an object gets a second holder is an axis.** RA3 copied an
   owned vector into a cell; a vector another cell held, one an ink field
   held (watched or not), and one already linked took the old path (VB2,
   VB3c). Name each route to a second holder (cell → cell, field → cell,
   linked → cell) and give each a kind.
3. **Check the refusals both ways.** An oracle that only judges accepted
   writes passes a door that refuses what it should take (`ship.aim.x = 9`
   refused because a cell snapshotted the vector) and one that takes what it
   should refuse. `refused` and `accepted` are invariants of their own, with
   the designed exceptions as tables that name their doc.
4. **Read the contract before writing the invariant.** The first oracle
   wanted x / y stored as floats; the engine keeps an int by design (`v.x = 4`)
   and promises floats only on read (`__iter__`). The real bug was a
   `10**400` int (VB1): `number` asks for "a number a float holds".
5. **When a cell is cheap, run the product; a covering array covers pairs.**
   2.5k cells cost 0.7 s, so the plain context runs every combination in
   `quick`. The contexts ran 2-wise there, and VB16 needed three values at
   once (a free vector, a callback, a warm read): `gate`'s full product found
   it. `quick` now also runs every kind × door × context × read with one good
   operand (1.5k cells, ~4 s): the operand is the axis that pairs well.
6. **The operand's inside is an axis.** A18 covered `v + "a"`; `v + ("a", 1)`
   leaked Python's message (VB13). Junk goes in as the operand, inside a pair,
   and as each scalar argument, for every public method (the completeness
   check makes a new method join).
7. **Some bugs need a history.** VB3c (a vector linked, then put in a cell,
   then its source moved) needs three steps in that order; the one-write
   matrix cannot reach it, and the machine found it only at `ci`. Plan the
   machine with the matrix, not after it.
8. **A pin with no reason keeps an accident.** GX15 fixed vectors that
   shapes own and left "a free Vec2 is a value and may hold NaN / inf" as a
   side note; two tests then pinned the store, and no one had argued it.
   Nothing could use such a vector (every reader refuses it), so the error
   surfaced far from the write (VB4). A test that pins a permissive
   behaviour says why in its docstring, or it is a candidate for review.

### Class guards written from the Vec2 battery

| Guard | Class | How | Found |
| --- | --- | --- | --- |
| `test_vec2_doors` | a door that skips a rule other doors run | kind × door × operand × context × read, generic oracle, a canary per invariant | VB1, VB2, VB3a/b, VB5, VB16 (gate) |
| `test_hyp_vec2_machine` | holder histories | holders, copies, links, sources, destroy, in any order | VB3c |
| `test_vec2_algebra` (junk table) | an engine message reaching the author | every public method × junk (completeness by `inspect`) | VB13 |
| `test_vec2_algebra` (twins) | two formulas for one quantity | `abs(angle_to) == abs_angle_to`, aliases bit-equal | VB14 |
| `test_vec2_guards` | a new raw store, part, or spelling outside the battery | AST and class introspection, both directions | — |

## Yield ledger

Whether the engine converges is a curve, not a feeling. One row per campaign,
added when it closes, with the same columns. **Catalogued** counts the rows of
its series in the [Bug catalogue](#bug-catalogue): a row may hold a class
with several members (PG: about 35 bugs in 32 rows), so rows are an order of
magnitude, not a bug count. The verdict columns exist from the laws campaign
on (its triage: BUG / LATENT / ACADEMIC / DECISION); earlier rows show `—`.
**Where, how common** names the layer and the most common author pattern
that reaches the bug: a taught pattern (the tutorials' games), a plausible
one, or a rare combination.

| Campaign | Dates | Instrument | Catalogued | Engine bugs | Decisions / messages | Not engine | Where, how common |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Hypothesis batch 1, system suites | 2026-09-25 | properties, state machines, scenarios | H 9, S 11 | — | — | — | |
| API surface | 2026-09 | signature fuzz | A 40 | — | — | — | |
| Geometry properties, differential | 2026-09-28 → | properties, fast vs slow twins | G 21, D 26 | — | — | — | |
| Program model | 2026-10-08 | whole programs against specs from the docs | PM 20 | — | — | — | |
| Graphics review | 2026-10-08 | white-box review | GR 49 | — | — | — | |
| Geometry campaign | 2026-10-08 | axes, shadow oracle, sentinel | GX 21 | — | — | — | |
| Systems review | 2026-10-09 | review, deep serial pass | RV–RV9 87, DS2 4 | — | SY 17 | — | |
| Interaction campaign | 2026-10-09 / 10 | seam matrices | HD 5, RX 1, AL 1 | — | — | — | seams between subsystems |
| Game system tests | 2026-10-10 | four white-box games | AC 17 | — | — | — | |
| Performance campaign | 2026-10-12 | benches, A/B | PF 11 | — | — | — | |
| Game-behaviour probes | 2026-10-13 / 14 | author-shaped probes under real input | PG 32 | — | — | — | collision, input, acts: taught and plausible patterns |
| Laws, S0–S6 | 2026-10-14 / 15 | laws model, equations | LW 9 | 3 (LW2, LW5, LW8) | LW7, LW6 (both applied) | LW3, LW4 academic; LW1, LW9 harness; the instruments' own errors outnumbered the engine's (lessons 1, 2) | resolve: Breakout, a taught game (LW2, LW7, LW8); input: a plausible pattern (LW5) |
| Laws S7, chaos doors | 2026-10-15 / 16 | a command injected at every door; directed cells | CD 5, CD3 3 | 3 (CD1, CD2, CD3 with CD3-x, CD3-b) | CD4 (today's rule), CD5 (message) | about six instrument fixes, then C5's key at the merge (lesson 7) | seams: hover × park, act change × dispatch, rule × contact; rare combinations, except CD3 (plausible: a shield gained while touching). Random single faults at sampled doors found none |
| Vec2 battery | 2026-10-17 | kind × door × operand × context × read with a generic oracle; algebra properties; twins; holder machine; static guards. Mutation sample of `scenamath` (60 sites the battery runs): 45 killed by the battery alone, 1 more after adding the `/` identities, the other 14 equivalent or message-only | VB 17 | 8 (VB1, VB2, VB3 a/b/c, VB5, VB13, VB14, VB16; VB17 by the machine on 2026-10-20, after SV12) | VB4, VB6, VB7, VB9, VB10 decided and applied (2026-10-17); VB15 messages (fixed) | the first oracle asked for floats where the contract allows ints (lesson 4); five harness slips (a cell given a tuple, a closure rebinding `v` with `@=`, a formula naming no source) | holders: `st.start = st.pos` (a plausible save-the-spawn pattern) and a linked vector in an ink field (plausible); arithmetic and messages: rare operands |
| Persona probes, round 1 | 2026-10-19 / 20 | two blind campaigns on one frozen commit (b5054b0): A, Opus, beginner + Scratch kid, 44 probes + 14 second tries; B, Sonnet, Unity / Pygame refugee + copy-paster + hobbyist, 40 probes + 19 second tries; the probe runner (stated checks, errors, laws model, E1 at 30 / 60 / 144 Hz, 22 hand mirrors for E11) | PP 22 | 2 (PP1 `Color` identity `==`, PP2 `Text.text` a stale cell) | 10 messages fixed (PP4–PP12, PP13 DOC); decisions PP3, PP17, PP18 applied, PP14–PP16, PP19, PP20 kept with a Guia note, PP21 kept | the runner's own: 5 (a drag released a frame late, a save file shared between rates, `SHIFT` not a key, Ctrl / Cmd modifier bits never set, a HANG flag that cut the author frame) | the author-facing surface: messages and silently ignored names (other engines' hooks, a top-level `on_click`, `run` as a callback), value semantics (`==` on colours, a field that read as its cell); all plausible patterns (a memory game, a HUD, a rebuilt board, Unity habits). Laws model and E11: no finding |
| Persona probes, round 2 | 2026-10-20 | two blind campaigns on 4220f07, models swapped: A Sonnet (teen, teacher) 31 probes + 9 second tries + 8 mirrors; B Opus (Godot / Processing refugee, game-jam crammer) 22 + 2 + 7; plus the round-1 probes re-run on the same commit | R2 10 (+3 R rows of round 1) | 2 (R2-1 floor snap glues a soft bounce at 144 Hz; R2-2 phantom contacts behind a fast body at 30 Hz) | 6 messages fixed (R2-4–R2-9), 1 DOC (R2-3, the round-1 Guia rows on `vel`: both campaigns), 1 decision (R2-10, applied: the Guia documents act inheritance) | triager mirrors (E11 keys flipped twice), probe timing | resolve and swept detection under frame-rate change (the E1 / PACE flags found both BUGs); messages for other engines' words. Laws model: no finding |
| Persona probes, round 3 | 2026-10-20 | two blind campaigns on fe00fda, models swapped again: A Opus (deadline student, puzzle designer) 20 probes + 8 second tries + 8 mirrors; B Sonnet (web developer, physics tinkerer) 24 + 8 + 6; plus rounds 1 and 2 re-run | R3 16 | 1 (R3-2 a resting movable partner answered as a wall at 60 Hz) | 12 messages fixed, 2 DOC, decisions R3-1 (applied: dead own-field reads), R3-3 (applied: pose retarget quiet), R3-11 (kept, Guia note); B2 LATENT (stacks, P1 non-goal) | runner timeout under load (one HANG); triager mirrors | messages for other worlds' words and half-done edits; resolve's skin answer. Laws model and E11: no finding |
| Persona probes, round 4 | 2026-10-21 | two blind campaigns on c7e8626, models swapped again: A Sonnet (animator, level builder) 20 probes + 11 second tries + 10 mirrors; B Opus (two players, simulation builder) 23 + 10 + 6, two long runs; plus rounds 1–3 re-run | R4 7 | 1 (R4-1, timers before tweens against the documented order; the triager's DECISION, re-read by the coordinator) | 2 messages (R4-2, R4-4), 2 DOC (R4-3, R4-7), decisions R4-5 (applied: act-owned names set the stage's aside), R4-6 (kept, Guia note); ACADEMIC A5, B4, B5 | triager format slips (`HZ` an int); a missed E1 in round 3's triage | tick order and act slots, where two documented rules met; laws model and E11: no finding |
| Persona probes, round 5 | 2026-10-21 | two blind campaigns on 872a78c, models swapped again: A Opus (UI designer, rhythm maker) 22 probes + 7 second tries + 6 mirrors; B Sonnet (procedural generator, arcade cloner) 28 + 5 + 9; plus rounds 1–4 re-run | R5 8 | 2 (R5-1 crossfade fate, R5-2 `.checked` a cell) | 3 messages (R5-5, R5-6, R5-7 a new warning), 2 DOC (R5-4, R5-8), decision R5-3 (kept) | probe timing at check instants, mirrors naming widgets | the audio slot's fade path, a widget alias, `on_collide`'s enrolled-only reach; laws model and E11: no finding |
| Persona probes, round 6 | 2026-10-21 | two blind campaigns on bbc094e, models swapped again: A Sonnet (interactive fiction, parent and small child) 26 probes + 5 second tries + 8 mirrors; B Opus (game feel, board / card games) 22 + 5 + 7; plus rounds 1–5 re-run | R6 6 | 0 (the freeze signal is met: rounds 5 and 6) | 3 messages (R6-1 callback arity at the call, R6-5, R6-6), R6-2 a warning and a Guia fix, decisions R6-3 and R6-4 documented | probe timing (taps) | messages at the doors that keep a callback for later; documented rules the Guia half-said (S9-1, T2 for chained moves); laws model and E11: no finding |

**Reading it.** A falling yield across *different* instruments says the
shallow bugs are gone, not that no deep ones remain: each new kind of
instrument has found something real so far. Compare an instrument with its
own earlier rounds, read the "where" column for the layer that keeps
producing (resolve, every campaign since CT), and count the instruments'
own errors too: when they outnumber the engine's, the instrument is the
less mature side.

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
| **A solver tolerance below authoring precision** | SU1–SU3 (a seam lip above `_RESOLVE_SLOP`), F1 (a resting gap against one frame's sink), PG-PB4 (a resting gap against a moving floor's drop), PG-PE2 (the skin backed off along a slope's normal moved a resting body sideways: every frame's skin was a ratchet) | Put the author's imprecision in the input space (lips, rotations, pacings), not only aligned geometry: `tests/test_seam_step.py`, `tests/test_sys_resting_contact.py`; `test_sys_resting_contact.TestRiderOnAMovingLift` (descending and yoyo lifts at every pacing); `test_resolve_solver.TestIdleSlope` (slopes × pacings, under 1e-6 DU) |
| **A solver result depends on the frame rate** (the step size sets the time of impact `t`, whether a gravity step clears the skin, or which hit comes first) | PG-PB2 (a rider's carry was the leftover `1 − t` of its platform's motion: 97 % at 30 fps, 1 % at 240), PG-PE2 (a creep per frame), SU3 (the one-way lip threshold), F1 (a resting gap against one frame's sink), PG-PB4 (a lift's drop per frame against a fixed skin) | Every resolve rule that involves a moving partner or gravity is tested at 30 / 60 / 144 / 240 Hz: `test_resolve_solver`, `tests/test_seam_step.py`, `tests/test_sys_resting_contact.py`. Open member: a side or head contact against a moving partner still rides `1 − t` of its motion (Collision Design, Riders, "Not done") |
| **A movable body's share is placed into a STATIC one** (a solver push, settle share or inherited leftover moves a body without sweeping it against its own `STATIC` partners) | MS1's push clamp (`_push_reach`: a light ball shoved past a thin wall), PG-PE3 (settle's mass split pressed a light crate into the floor under a heavy one), PG-PE4 (the inherited leftover placed a light body through a floor or past a thin wall) | Every solver push of a movable body is swept against its `STATIC` partners (`_push_reach`, `_travel_to_walls`), or goes into its motion channel when its own sweep is still to come (`_push_partner`): `test_resolve_solver.TestStaticHolds` (both creation orders), `test_collision.TestSweepMassSplit` |
| **A verb on a dead actor registers work or revives it** | H2 (`layer =`, `tag`), S5 (`mode =`), S8 (transient replace), S9 (`after` / `every` / `tween` / `play_sound` / `on_update`), W2 (`@=` onto a dead actor or a part it left behind), A6 (`resolve_now` re-enrolled the collider), A7 (a first read wired a dead widget into the graph; `Line(circle=dead)`; `Track.reversed()`), HB1 (hitbox writes on a dead or removed hitbox), SA10 (`center =` moved a dead shape), E14 (dead setters stored, flips), HP7 / HP9 (dead paint and hitbox reads), HP12 (`remove_hitbox` silent), GR3 / GR4, PG-PA4 (work scheduled before the death outlived it through a closure over `self`) | `test_sys_hyp_world` poke rule; `test_hyp_surface.TestDeadEntityVerbs` (P6: every public method and setter of every Entity kind; canary S9); `test_refusal_atomic` (dead source: nothing changes, reads stable); teardown's `_DeadRoute` refuses every routed write; `test_process.TestClosureOverSelfIsOwnedLikeTheBoundMethod` |
| **A registry keeps a dead owner** | H3 (id map; retired with ids), S1 (bound method in a `WeakKeyDictionary` value), S3 (`id(owner)` keys), S4 (dense snapshots), S6 (`_pair_targets`) | `census` / `zombies` / `assert_collected` in the system suites; `test_act.TestNoLeaks` (a busy scene — `kitchen_sink` plus timers, effects and rules made in the scene — changed N times: stable census, no zombies; 200 cycles with `SCENA_SOAK=1`) |
| **State leaks from one act into the next** | SC1 (an unread `keyp.once` edge fired in the next act; generalized by PM3), a new canvas / clock / collision setter that an act change neither restores nor keeps on purpose, PG-PA1 (an act's `@=` on a game object outlived the act) | `test_act.TestSettingsClassification` (walks every settable name on `canvas` / `clock` / `collision` / `audio` / playfield / layers / effects / background and the exported `set_*` / `show_*`; each must be in `WORLD_SETTINGS`, `KEPT_SETTINGS` or the test's `NOT_SETTINGS`); `TestWorldSettings.test_the_test_changes_every_restored_setting` (guards the guard); rule: **anything the author can change globally is classified when it is added**; `test_act.TestActLinksOnGameObjects` |
| **A deadline compared on summed frame time** | PM8 (`after` / `every` / tween end / `ready` / `recently` / transient progress fired a frame late or on time by rounding), PB3 (the clip playhead), PB4 (one-shot end, `next=`), GR6 (SpriteButton state art) | `process.reached` for every "is it due" comparison; `test_process.TestDueOnTheExactFrame` (any fps, any whole number of frames). A new timed mechanism compares through `reached` |
| **A cheap-looking read or no-op builds a registered Entity** | PM7 (a verb on an empty group built a `Blank` Shape per call); PM16 (a non-Shape method on an empty group raised); `canvas.game_view.center` builds a Point (~70 µs) per read (by design: a Box is a value, a Point an entity) | `test_noop_cost` (every Entity method through an empty group, every world setting written back); `program_oracles.probe_neutral` (a run with probes vs without: GC-timed roster entries show up) |
| **A cell is refused where a number is accepted** | PM12 (`deadzone`), PM15 (`amp_db`) | `test_cells_as_numbers` (every exported function, every number argument); `test_hyp_surface` (slots, verbs, constructors) |
| **One payload, two doors, two views** | PM11 (`test_collision` vs handlers), PB7 / PB8 / HP10 (plain blit vs full draw), SC7 / SB7 (`clone` vs `<<` / whole `@=`), SA7 / E12 (slot setters validated, property setters not), GR13 (a pivot read past the point reader), PG-PC2 (the route table refused `obj.name = …`; the bracket `obj["name"] @= …` made an unread field) | `test_collision_doors`; `test_draw_doors`; `sweep_c7` over every copy door; `test_value_validation`; `test_fieldref.TestBracketRefusesWhatAssignRefuses` (every kind × every refused name through the other door) |
| **An unread edge outlives its frame** | SC1 (act change), PM3 (any later first reader of `keyp.once`) | `KeyPressed._expire_edges` at the end of every frame; `test_keyp.TestOnceChordProperty` with frame boundaries |
| **A rejected call half-applies** | H1 (constructor registers then raises), H4 (`layer =` unregisters then fails), R4 (register auto-created a layer before the id check; retired with ids), A10 (`fade_in` shows before validating; `tangent_lines_from` keeps the first line), W3 (a raising formula left its ink cell and anchor), PG-PC3 (`tri.points[1] @= f` linked the vertex, then the tuple refused the store-back: Python runs the in-place operator on the item before the store, so a view a property returns must take its item back or refuse in the operator), CK1 (a copy across kinds adopted the source's model, then raised: the target kept a `RectModel` on an Ellipse / Circle) | constructor census in `test_hyp_api`; "claim nothing before every check passes" in `Registry.register`; `test_fieldref.TestPolygonVertexLink`; `test_copy_kinds` (every refused copy leaves the target as it was) |
| **Routing picks the wrong writer** | S10 (`_write_field` ink path on a property-backed field), R1 (a second `__init_subclass__` replaced the first, so `Rect.rotation` routed to `Shape.rotation` and recursed) | `test_entity_hooks` (no duplicate `def`; every subclass has its own route) |
| **An engine error reaches the author** | verb `float()` leaks, `chance(True)`, `line_width`, H7 (`int(…, 16)`), A1 (unhashable key in `keyp` / `ready` / `recently` / `obj` (removed) / `canvas.layers[]`: **validate the type before any dict / set lookup**), A3–A5, A7 (`float(finite(fn))`), A8 (`finite` at a fixed site; `** 2` overflow), HB2 (Python's "property has no setter" on hitbox fields), CK1 (`circle << box`, `ellipse << rect`, `triangle << box`: AttributeError / "Unknown ellipse model" through every copy door) | `leak_message` in every property; `test_copy_kinds` (every kind × every source kind × every copy door); `test_hyp_surface` (P2 on every export); AST guard `TestNoFloatAroundFormulaValidators` |
| **A dead Entity is falsy** (`Entity.__bool__`) | R9 (`self._alias_of or self` fell back to a reversed view's empty tables once the host died) | `test_entity_hooks.TestNoTruthinessFallbackOnEntities` (AST: no Entity-holding attribute as an `or` operand); rule: `is not None` for Entity-or-None |
| **A raw-store site calls the dispatcher** (`_x` is the dispatcher, `_x_impl` the hook — a rename flips what an old `_x` call means) | A7 (`Square._takein_impl` → `super()._takein` → `self._takein_impl` … recursed), B1 (pull resolvers kept `_takein` after the rename: every read re-walked the cone), B9 (a structural pull's Derivate refresh re-walked: n × depth on a tree of linked Lines) | `test_entity_hooks.TestHooksDoNotCallTheirDispatcher`; `test_pull_no_invalidate.TestPullResolversStoreRaw`, `TestStructuralPullDoesNotRewalk`. On any rename of a dispatcher / hook pair, re-map **every** old call site by meaning, not by spelling |
| **A guard lands on a per-frame path** (correct check, general-case cost paid every frame) | B2 (`validate.finite` / `_finite_deg` ABC path on every `move_by` / `rotation =`), PG-PA2 (avoided: the watchdog's JUMP listener returns `DISABLE` on the first touch of a jump it does not need; interleaved A/B within noise) | `tests/test_hot_validators.py` (`TestHotPathsStayHot`). Rule: a validator on a verb tests the exact common type first; the bench pulses catch what the unit suite cannot |
| **A per-frame write takes the general verb** (the common case pays for pivots, links and parts it does not have) | D28 (every `scale =` and scale tween ran the pivot-general `scale_by`: the center re-derived twice, rewritten unchanged, the part subtree batched; ~10× a size write) | `tests/test_scale_center_fast.py` (the general verb patched to raise; differential against the switch off; canary). Rule: a field an author writes every frame (`=` on a pose field, a tween tick) has a fast path for its common case, taken only where the general path would write nothing else, with a module switch as the oracle |
| **Engine code calls an author-facing lookup that guards or warns** | SC4 (`until_empty` polled `group[name]`; its near-miss typo warning fired on an emptied, dropped bucket) | Rule: engine internals read the registry / engine state directly; author guards (typo / near-miss warnings, `DestroyedError` hints) run once, at the author's call site, never in a per-frame poll |
| **A hand-kept list drifts from the code** | R8 (`_formula_knobs` missed reactive pad fields), SK1 (`SCENIC_PRESET_NAMES` / `_SKY_ALIASES` named ramps the table lacked), SK2 (smoke preset strings no preset has) | `validate.formula_knobs(cls)` derives from field slots; `TestReactiveKnobsTakeFormulas` walks every export; `test_gradient_presets.TestSkyPresetNamesResolve` (every advertised / aliased / suggested sky name builds a sky; smoke literals scanned). Rule: an error message lists only names that resolve — filter the list through the same lookup the call uses |
| **A cache hands out objects callers mutate** | D2 (`_poly_cache` Prims shifted in place by `_translate_prims`), K4 (interned looks: `Neon("red").color = …` repainted every user and poisoned the intern cache) | `TestPolygonCacheAliasing.test_no_cache_hands_out_the_prims_it_keeps`; `test_registry_key_fields.TestInternedLooksFrozen` (every exported interned look / filter); rule: a cache returns clones, or what it hands out refuses writes |
| **A handle field doubles as a registry key** | K1 (`Layer.name` vs `canvas.layers`), K2 (`Handle.name` / `.owner` vs the scheduler slot `(id(owner), name)`), K3 (`shape.group` returned the live set; in-place `add` skipped `group_map`), K4 (interned look fields vs the intern key), K5 (`Entity.id` vs `id_map`) | `tests/test_registry_key_fields.py`, `test_registry_layers` (`test_name_*`); rule: a field a registry is keyed by (or mirrors) is a **property whose setter raises** with the create-and-move / re-schedule spelling, or a read-only snapshot (`GroupTags`, `frozenset`) that the registry swaps — never a plain attribute or a live container. Internal writers set the private slot |
| **A per-frame throwaway enters the graph** (a value built to be read and dropped registers nodes; its tree is a reference cycle, so only a full GC frees them) | D11 (a measured Box's point part; views, group box and widget box were eager Boxes) | `test_box_snapshot.TestMeasuredPointsStayOffGraph` (count with the cyclic GC off); `test_leak_detector.TestGcChurnIsNotALeak`. Rule: an engine read that hands out a fresh Container every call (a snapshot, a measurement) keeps it off the graph until linked — a measured Box is `Box._snapshot` / `Box._from_aabb`, never `Box(p1=, p2=)`; its test counts graph nodes with `gc.disable()` |
| **A fast path or cache disagrees with its reference** | D2 (poly cache), D4 (intersection GJK reused as a distance), D5 (support = first vertex within tie_eps) | `test_diff_*` + canaries |
| **An oracle is stricter than the contract** (false positive) | D10 (prims compared in a raw-float sort order; the engine promises neither order nor bit-exact translation), G2 (contacts compared exactly across a world shift; the engine promises no answer at exact tangency), the C5 key after CD3 (a checker kept the old identity of a handler: lesson 7 of the laws campaign), `time_scaled` after LW6 (an equation on world time asserted that a transient's `on_done` scales with `clock.scale`; it never did in production, only under the harness pin) | `test_diff_collision.TestPrimsOracle` (drift + shuffle + built ties, every model); canary `test_oracle_guard_catches_a_sorted_compare`; `test_sys_hyp_collision.TestTangencyTolerance`. Rule: before calling a property failure an engine bug, check that the documented contract promises that exact answer; a float boundary (tangency, ties) needs an ε "either" band |
| **Pull reactivity: a value depends on who read first** | D8 (`unlink` froze the unpulled value; destroy auto-unlink too) | `test_diff_reactive` link model + `chain` op; `TestUnlinkFreezesTheCurrentValue` |
| **A mirror is applied as a rotation (or twice)** (a flip moves the shape, or relabels its parts as if turned) | G3 (`POINT_VEC` `flip_x`: `180 − θ` plus `vec.x`), G4 (`SPINE` side anchor kept its side), G6 (triangle mirrored `rotation`, not its heading; `vertex=` polygons turned about the vertex), G7 (`.box` of a flipped Graphic kept the turned angle but dropped the mirror), the pre-2026-09-29 Rect flip (`flip_x` sent `top_right` to the bottom left: names rotated 180°, not mirrored) | `test_rect_names.TestFlipMirrorsNamedPoints` + `test_flip_mirror.TestFlipMirrorsEveryKind` (every kind, drawn geometry) + canaries. Rule: a flip is checked on **every named / Defining point** (lands on its mirror about `center`) and on the region (does not move) — not on one read-back |
| **A Derivate is missing from the update's write list** (filled on first read, then stale) | G5 (`vec` on Rect / Box / Line — also not pulled through its owner), G8 (RegularPolygon stats on their first read) | `test_rect_names.TestDerivatesMatchAFreshTwin` + canary. Rule: a new Derivate part is added to every `_update_impl_*` that owns it, and the fresh-twin check covers it |
| **A kind implements a shared verb its own way** (flip, clone, `rotation`, a Derivate refresh: each kind hand-rolls it, and siblings drift) | G3 / G4 / G6 (flips moved or relabelled shapes), G5 / G8 (Derivates missing from a kind's write list), the 2026-09-30 contract sweep (Track flips change nothing; clones drop pose on every kind; Line `rotation` ≠ its heading) | `test_geometry_contract` (C1–C8 over every kind × model × verb × part, shrink-only `geometry_known.py`, canaries). Rule: a new kind, model or verb joins `geometry_support.KINDS` / `VERBS` in the same change — the sweep then checks it against the whole contract |
| **An engine reader warms a cold Derivate** (performance) | D3 (per-frame readers / pose verbs knock 12 of 24 shape models off the pose fast path for good) | `test_diff_pose.TestEngineReadersStayCold` (shrink-only allowlist) |
| **A count reads a structure with holes** | D1 (`len(layer._objects)` counts tombstones) | structural guard in `test_registry_layers`; `Layer._live_count` |
| **A doc cites a test that does not exist** | Six design docs cited `tests/test_registry_layers.py` (written ahead of the Scene-rename step 2) while the file was still `test_scene_layers.py`. **Rename a test file and its citations in the same change** | `test_doc_citations.TestDocCitations` (every cited test file and dotted test name in live docs; the private `archive/` and `proposals/` exempt) |
| **A published file cites a private folder** (a design doc, code comment, test docstring or script names a file in the unpublished `archive/` / `proposals/`; those folders are not published, so the link dies and the reason it pointed at goes with it), a design doc sends the reader to unpublished material for evidence (a review report, repros), or a relative link points at a moved file | DL1 (2026-10: ~45 citations in 14 design docs, 6 tests and code, and 5 bench pages; 8 of them already dead because the proposal had moved to `archive/` or never existed); DL2 (2026-10-26: two "kept privately" pointers left after DL1) | `test_doc_links.TestDocLinks` (every published `.md` / `.py` / `.html` / `.txt`, including paths joined in code; DL2: `TestDesignPrivatePointers` over `design/`) + `TestScanner`. Rule: the living doc carries the conclusion and its reason — see [README — Private folders](README.md#private-folders) |
| **Bundled media without its license or credit** (a file Scena redistributes, but an author cannot tell how to use it) | ML1 (`examples/media/images/`, then `backgrounds/`, had no license file; `audio/laser4.wav` / `laser7.wav` were marked CC-BY 3.0 with no author, so no credit could be copied) | `test_media_licenses.TestMediaLicenses` (every media folder has a `license.txt`; every top folder is in `examples/media/CREDITS.md`; every file that a notice puts under CC-BY / CC-BY-SA has a credit block under "Attribution required", and every credited file exists) + `TestCodeLicense` (MIT `LICENSE` declared in `pyproject.toml`). Rule: add media only with its notice, never NC / ND / unlicensed |
| **A media path is dead and nothing says so** (a missing image or sound is a `SCENA WARNING` and a placeholder; the script still builds and plays) | MR1 (the `scripts/examples` → `examples` move and the media reorganization left ~170 paths dead in examples, smoke, bench and tutorial), MR2 (media-backed tests `skipTest` on a missing file: the suite stayed green), MR3 (`test_scripts_run` scanned the old `scripts/examples` and found nothing), MR4 (2026-10-23: `guardiao.py` keeps its pill images in a dict, `PILULAS = {"duplo": "space/pill_blue.png", …}`; the scanner read only loader arguments, so the release zip list left the four pills out and the zipped game would have shown placeholders — the scanner now reads string values of a dict) | `tests/test_media_refs.py` (every literal media path in `examples/`, `scripts/smoke/`, `scripts/bench/` resolves like the engine resolves it; `_media.py` lists exist; every media name in the tutorial exists under `examples/media/`). Rule: tracked media → `tests/media_support.media()`, no skip-if-missing; a move or rename of a media folder runs `test_media_refs` and updates `CREDITS.md` |
| **A program fails only after time passes** (a check runs a few frames, or skips the collision pass; the bug needs a hit, a timer or a destroyed actor) | TU1 (tutorial 05: the ship is destroyed by a shot, `update` keeps steering it) | `test_tutorial_steps` runs every step 600 frames through the real frame body with `random` seeded. Rule: a script check runs long enough for its timers and collisions to fire, and deterministically |
| **A program only works at a fixed frame time** (the harness steps a constant `dt = 1/60`; a real run has hitches) | TU5 (tutorial 05: the fleet bounce `if past_edge: v = -v` sticks at the edge after one short frame) | `test_tutorial_steps.TestFleetBounce`: a driver gives the frame after the first turn a 1 ms `dt` and counts turns over 20 s, for every tutorial step and example that moves the fleet by `st.velocidade`. Rule: a bounce sets the direction (`v = -80` past the right edge), never flips the sign |
| **A check only looks where a body ends** (a per-frame sample misses what happened between frames; how much it misses depends on the frame rate) | CT1 (fast `@collide` shots tunnelled), CT2 (a fast body pushed into a resolve wall never fired `@collide`) | `tests/test_sys_fast_shots.py` (the same hit set at every pacing), `test_sys_hyp_collision.TestFastMotionAgainstSweptOracle`. Rule: a contact rule is tested at 30 Hz and uneven pacing with movers that cross a target within one frame, not only at 60 Hz with slow movers |
| **A script is left on a retired spelling** (the engine moved on, the script never ran) | SR1 (`smoke/colliders.py`: `shape.group.add`), SR2 (`bench/historical/galaga.py`: `Text(x1=, y1=)`, `set_framerate`), SR3 (five smokes: `keyp.once(",")` / `"."`; `app_glowspot`: `"["` / `"]"`) | `tests/test_scripts_run.py` (**Scripts run headless**: every `examples` script builds and plays 30 frames in its own process) and `tests/test_smoke_scripts.py` (every `scripts/smoke` script, plus listed benches and every pulse scene, B6; `SLOW`). Rule: an API rename or removal runs both modules in the same change; a script that drives its own loop (not `run()`) is not covered |
| **An example reads a resolve body's pose in `update` to decide an event** (the floor pushes back later in the frame; a hitch makes the unresolved pose cross the line) | NJ1 (`ninja_2_mundo` … `ninja_4_perigos`: `if self.center.y < 30: perder()` after `move_by`; a first `visual = Aura()` / `ElectricField` stall sent a standing hero back to the start, 2026-10-21) | `tests/test_ninja_examples.py` (each ninja example, headless in its own process: one 0.25 s frame while standing keeps the lives; a real fall into the water costs one). Rule: an event on a resolve body's pose goes in `@when` / `@leave_playfield` (checked after collision), [Collision Design — Frame order](Collision%20Design.md#frame-order) |
| **A color name Scena does not know** (CSS / X11 habit; warns and paints magenta, so nothing fails) | SR4 (`"slategray"`, `"mediumseagreen"`, `"medium turquoise"`, `"slate gray"`) | `tests/test_color_literals.py` reads the literals statically, so click-only paths and Guia snippets that never run are covered too |
| **A message uses a word reserved for an author concept, or the concept's old name** | "Scene-level after(..., then=)" (meant script level), "not scene bodies" (meant world space), "scene objects rising" (meant registered objects) — all wrong once the author concept existed (named Scene from 2026-09-28, `Act` since 2026-10-06); after the 2026-10-06 rename, any "scene change" / "current scene" left in a message or doc | `test_message_vocabulary.TestMessagesDoNotSayScene` (AST scan of raise / warn / error / message literals in every `scena/` module, `act.py` included; allowlist only for the rendered-frame sense and the retired-name error); `TestDocsDoNotUseRetiredSceneTerms` (live design docs: the registry / script-scope terms of the 2026-09-28 rename); `TestDocsDoNotUseSceneForAct` (live design docs: the old class and verb names, "scene change", old doc links; `Act Design.md` keeps the naming history); `TestGuiaDoesNotSayCena` (Guia sources + generated index: no "cena" at all; the old names only in the 0.6.0 rename note) |
| **The old brand survives a rename** | After Stage → Scena (0.6.0): a string like `"stage.x"` in `mock.patch` / `sys.modules` (a regex on `stage.` missed the ones not followed by a letter), a no-dot `startswith("stage")` that also matched the editor, a guard regex still looking for `stage._x` (it passed by scanning nothing), a relative link `../stage/…`, a local variable named `stage` that a module rename would have broken, a message or sentence naming Stage | `test_message_vocabulary.TestNoStageBrand` (AST: no `stage` / `stage_editor` import or module string in code; no Stage / STAGE in messages; no Stage, `stage/`, `stage_editor`, `stage-editor`, `from stage` in published text). Allowed: lines naming 0.6.0 or a `LEGACY` name, the `"stage-level"` tag, the old `Stage Editor` launchers, `PostEffectStage` / pipeline stages, Act Design's Naming section. Package-name checks go through `scena/_pkg.is_framework_module` (no literal to rename next time) |
| **A derived pose lags an input that never notifies** | T1 (view `Text.center` vs the string: formula text is pull, and `font_size` / `flash_text` / fill material are not graph nodes) | Refresh at the read, not at the write: `_TextCenterSlot` + reconcile in `_refresh_layout`; `TestViewPinMotionProperty` (random string changes interleaved with every pose writer) |
| **A link is read as a one-shot write** (a model that keeps its own pin re-derives a linked input from that pin, so the link holds only until another input moves; or the model's Defining set is fixed at construction, so a runtime link leaves a sibling input writable against it) | GX20 (anchored Text: a linked `center` moved when the string changed; the anchor stayed writable) | `test_text.TestLinkedCenterIsThePin`; the reactive-matrix oracle (`test_hyp_reactive_matrix`: a linked field reads its formula after every move, whatever else links). Rule: while a part links it is an input the model keeps, never one it recomputes; the parts that would fight it turn Derivate for as long as it links |
| **A test depends on what ran before it** | O1, O9 (graph-node baseline taken with an earlier test's garbage still pending); O12 (the same on the roster: a census pair without a collect, a GC pass between them) | `run_tiers.py` gate runs every module in its own process (a test that needs a predecessor fails there); deep's serial pass catches the reverse (a module that breaks its successors); graph counts: `test_count_baselines` (static: every `len(<…>.nodes)` and every `census(collect=False)` in the tests follows a settle; dynamic: garbage planted, a collection forced at each assert). Rule: settle garbage before count baselines, or pause the GC across an unsettled pair ([Harness pitfalls](#harness-pitfalls)) |
| **A contact is judged on a pose that is never drawn** (frame-time dependent) | F1 (resolve skin read as a gap by the pre-resolve snapshot), F2 (accepted limitation: the pre-resolve pose sinks by g·dt² against a corner) | `tests/test_sys_resting_contact.py` (every kind × pacing incl. uneven 5 / 28 ms × far offset). Rule: a contact rule on a resolved pair must hold at 60 Hz, 200 Hz and uneven pacing; test with alternating short / long frames, not only 60 Hz |
| **Event-driven level state goes stale** (a level recomputed only on an input event misses every other way it changes) | PH1 (`pointer_hover` recomputed only on mouse moves: stayed True after hide / `clickable = False` / moving away, a new target on top never took it, a widget did not clear it), PG-PD4 (widget hover recomputed only on motion events: kept when the cursor left the window) | `tests/test_pointer_hover.TestStaleness` (every way out, pointer still) + `tests/test_hyp_hover` (exit guarantee; tiered == brute force; edges alternate; a never-exit mutation fails it). Rule: a level is re-validated **per frame** at O(1) and fully recomputed when any of its inputs changes (pointer, an epoch the writers bump, layer stack) — never only in one input's callback; `test_input_streams.TestWidgetHoverFollowsThePointerSample` |
| **A test passes only on the Mac** (it relies on a platform default or on a clean tree) | WP1 (scans read AppleDouble `._*` files), WP2 (pixels read in `kN32` order), WP3 / WP7 / WP18 (wall-clock budgets and ratios under load), WP5 / WP8 (text in the locale encoding), WP6 / WP11 (POSIX literals as expected paths or labels), WP9 (a gate test needs a package the `test` extra lacked), WP10 (old runner logs copied Hidden), WP12 (the exec bit asserted on Windows), WP13 (a Hypothesis module on Hypothesis defaults), WP14 / WP15 (a clock read twice, a hang timeout sized for an idle machine), WP16 (child output decoded with the locale), WP17 (paths sorted with the host separator; a test that needs a Mac font), WP19 / WP23 (a `/` path joined onto a `\` root, directly or through a name), WP22 / WP49 (an absolute time bound; WP49 in an example's test), WP24 (a `relpath` label read in `/` form), WP25 (a hang timer armed before the imports), WP26 (a venv launcher's child still holding a file), WP27 (a headless test drawing at the default 2000 × 1200), WP28 (a tool printing `→` to a piped cp1252 stdout), WP29 (`os.symlink` without the Windows privilege), WP30 (a gate past the Windows commit limit: aborts and timeouts); engine bugs only Windows showed: WP20 (a watcher thread kept a stack), WP21 (a skia buffer freed before it was read) | `tests/test_platform_portability.py` (AST: no bare directory scan in `tests/`; every `toarray` / `fromarray` in `scena/` and `tests/` names `colorType=`; every text `open` / `read_text` / `write_text` in `scena/`, `scena_editor/`, `tests/` names `encoding=`; every `S_IX*` / `X_OK` in a test names the platform; a test that writes a transient's `t0` pins the clock; every text-mode subprocess names `encoding=` / `errors=`; a test helper's `os.path.join` of a parameter, a `/` literal or a name holding one is normalized; every buffer a skia call borrows is a name; no `test_example_*` / `test_game_*` reads a clock), `test_run_tiers.TestHypothesisProfileGuard`. Rule: never rely on a default that differs by platform — name the byte order and the encoding, scan through `source_support`, build expected paths with the same path function, time as a ratio (or count the work) |
| **State lives on an object a transition throws away** | E1 (`on_collide*` on the Collider that park and `collidable = False` drop), E2 / E3 / E11 (park stash written on one path only) | `test_collision_lifecycle` (every sequence of up to three lifecycle statements vs a twin in the final state). Rule: state that must outlive park / opt-out / resume lives on the actor |
| **A shared default is mutable** | HP1 (`Color.alpha =` faded every default shape), K4 (interned looks) | `test_material_isolation` (every paint write × every relative). Rule: a shared default is immutable; a write gives the writer a new object |
| **A cache key misses an input, or a hit skips a check** | PA2 / GR7 (trim offset, `rotated`), PB10 / PB11 (envelope, source rect), PA7 (`True` hit `1`'s entry) | `test_cache_keys` (a warm hit equals a cold bake per field; every module cache listed). Rule: the key holds every input of the bake; a hit is reached only after the type check |
| **A fast path skips a refusal the slow path makes** | GR12 (`10**400` through every exact-int fast path), B2's inverse | `test_value_validation` (`10**400`, NaN, `True`, `"x"` on every setter). Rule: a type fast path keeps every refusal of the slow path (an int is bounded like a float) |
| **A second store of one value lags** (a cache of a field written on some paths only) | GR17 (`_rotation` vs a Defining `angle` slot), T1 (Text center vs its string) | `TestPoseStoreFollowsTheHeading` (store vs value after any two verbs). Rule: a second store is written on every path that writes the value, or not kept at all |
| **A guard enumerates from the fix's own list** | GR14 (the route guard read `_SIZE_WORDS`) | `test_route_table` enumerates every field slot of every kind. Rule: a guard's source of truth is outside the code it checks |
| **A measured value satisfies the no-sources guard** (a formula's dependency walk lands on a fresh snapshot Container, so the guard sees a source that nothing updates) | RX1 (`canvas.game_view`, `layer.view`, `graphic.box` in a formula) | `state._is_durable_source` (a deferred tree is a value; the Container before it is the source); `test_canvas.TestCanvasIsAFormulaSource`. Rule: whatever hands out a measured snapshot is itself a Container that notifies when the measurement changes |
| **An off-graph value satisfies the no-sources guard through its holder** (the chain reaches the value through a Container that never changes when the value does, so the guard sees a source and the formula freezes) | AL1 (`lambda: self.mic.level` inside an Entity; the same through the source-less `exec` path) | `state._formula_source_of` asked at every step of a chain and one attribute hop from a Container in the source-less fallback; `test_audio_level_source`. Rule: a value written off the graph (an audio thread) names a stand-in node the frame notifies; the holder is never its source |
| **A copied pair side keeps a destroyed body** (a list or snapshot taken at registration time is pruned on destroy only where someone remembered it) | HD1 (group-operator snapshot), HD2 (the sealed `resolve` pairs), HD3 (the act-level handler list), S6 / D6 (`_pair_targets`) | `test_sys_holders` (`scan` finds every path, no list is named by hand); rule: every list that holds pair sides is pruned by **one** function, `CollisionSystem._prune_dead_side`, from `drop_pair_handlers_for` |
| **A close path lives in a `destroy` override that `registry.destroy` bypasses** (an act change, a layer drain and a group destroy call the registry primitive) | HD5 (`Menu.destroy`) | `test_menu.TestRegistryDestroySettlesTheMenu`; rule: per-kind teardown goes in a hook the registry teardown reaches (`_settle_on_remove` from `remove_widget`), never in an override of the public verb |
| **A manager field is cleared on some removals only** | HD4 (`last_click`), PH1 (hover target), E1, HW1 (a per-step set left out of `_forget_step_sets`) | `test_sys_holders` partial and gone enders; rule: `remove_widget` / `forget_destroyed` clear **every** field of the manager that can name a widget or shape |
| **A constructor touches a raw input before linking it** | C1 (`Line` home `length` / `angle` via `number()`), C2 (Ellipse focal `get_xy` / `float`), C3 (Box spine `height = float()`), C4 (rotated-corner `_takein` rewrite), C5 (`corner_radius` storing a function), C6 (fixed knobs with a raw or generic message) | `tests/test_ctor_links.py` (every signature, every geometry key: a lambda follows, and a lambda of the same numbers builds the same shape) |
| **A knob is accepted and changes nothing** (on every path, or on every style / fit but the one its test used) | KN1 (`Metal(color)` never reached the shader), KN5 (`set_color` under `Metal`, silent), KN6 (the rim of a tinted Metal), KN2 (`tile_mode` on a fitted Wallpaper), SK4 (a `Texture`'s `angle` / `shift` / alpha on a Wallpaper), KN4 (`Shield(color)` on fixed-hue styles, `Halo(rings=, speed=)` off `pulse`, `Bolt(amount=)` on `core`, `tile_size=` off `fit="tile"`: now refused), AC2 (a Fire subclass ignored `style=`), AC15 (Track class keywords dropped), AC16 (`Anchor.draggable = False`), KN9 (a placement on a sizes-only Track: now anchors it) | `tests/test_knobs_take_effect.py` (every look × style × knob, every Wallpaper fit × knob, every Wallpaper fit × `Texture` knob: different pixels, or a listed reason; shrink-only); `test_subclass_parity` (class keywords). Rule: a value the engine will not use raises with the fix (or, when its meaning is clear and nothing it could mean is lost, the engine uses it: KN9); a knob that only one style or fit reads is tested on every style or fit |
| **An `==` that is silently always False on a type authors read as a value** | PE1 (`c.center == (400, 120)`: a Point is an object, compared by identity) | `tests/test_point_equality.py` (every spelling: both operand orders, `!=`, a list, a `Vec2`, another Point on the same spot, `in`, through a cell; results and hash stay identity; engine compares stay silent). Rule: when identity is load-bearing and value `==` cannot be had, author code that compares the object with a value warns with the spelling that works; engine compares stay silent (IN2: a loud `==` must not turn every engine compare into a typo check) |
| **A function Scena calls is `async`** (a coroutine nobody drives: the body never runs, and as a predicate it counts as True) | AH1 (`async def setup` / `on_update` / handlers / `on_done=`), AH2 (filters, `nearest(where=)`, `until`, `@when`, the `@on_change` target, `resolve(only=)`, `@=` formulas) | `test_async_hooks.TestEveryCallbackDoor` (doors enumerated from the public surface; a new door needs a case or a reason). Rule: every door that takes a function calls `validate.refuse_async` where it takes it (or relies on the `_invoke` / `call_truncated` backstop when it is a hot call) |
| **A doc promises a refusal no test makes** (a CHANGELOG or Guia sentence "the old spelling raises", "X now follows") | RA1 (four doors took a held `Vec2`), RA2, RA4, RA5, AC4, SV2 | One case per door the sentence names × every payload kind the door takes (`test_state_reads_value.TestHeldVec2IsNotTheCell`); the release audit (Scena Design checklist). Rule: a sentence of that form is a test to write, not a summary to trust |
| **A test turns vacuous** (it keeps passing while it no longer reaches what it checks: a changed spelling, a blank frame, a shard list, a case that runs no frame) | SV5 (a cell helper returned the number after the 0.8.0 flip), HV1 (two blank frames compared), O10 (gate shards ran ~50 of ~190 cells), the first `resolve(only=)` case of `TestEveryCallbackDoor` (no frame ran, so `only=` was never asked) | Canaries (`diff_support.assert_catches`, gate only), `TestDrawReachesThePixels`, `test_every_split_module_really_shards`, the `> 100` reach checks of the surface sweeps. Rule: a new guard is run on the pre-fix engine and each case is seen to fail; after a change to what a spelling means, run `gate` |
| **An input stream loses or outlives its press owner** (repeats, drags and the release must reach the receiver that got the press — script, widget or shape — and nobody else; what the press set must be undone when its owner goes away) | S3-7 (a modal ate the up), W-P4 (repeats after a modal), X-life-3 (an up without its down), S3-8 (an old-act press clicked), PG-PD1 (a destroyed held Button never wrote `value_off`), PG-PD3 (a repeat reached a newly focused box), PG-PD7 (the up lost across `change_act`), LW5 (a typed character carries no key: it went to whatever box had focus after the key's handler moved it) | `tests/test_input_streams.py` (`TestStreamOwnershipMatrix`: owner × interruption — focus change, focus loss, destroy, act change, modal; `TestACharFollowsItsKey`); laws I1–I5 over every program and game (`tests/laws/model/input.py`). Rule: an event that carries no owner (a character) follows the event that made it, never the focus as it is now |
| **Simultaneous things answered one at a time** (two contacts of one body in one step, or a bounce and the rest of its frame, resolved in sequence: the result depends on which came first, and on the frame rate) | LW2 (a ball on the seam of two bricks: creation order sets the deflection; breaking in the handler vs a frame later differed by up to 46°), LW7 (a bounce dropped the frame's leftover travel: a ball in a box ran 3–6 % slow by frame rate), LW8 (a skin contact the handlers saw and resolve did not answer), PG-PB5 (the dispatch side of the same shape, fixed) | Fixed 2026-10-15: the joint stop, the bounce sub-step, a removed partner as a still wall, the skin answer ([Collision Design — Joint stop](Collision%20Design.md#joint-stop-simultaneous-contacts)). Guards: `tests/test_joint_response.py` (a class and a canary per rule), `test_laws_equations` (`test_two_bricks_at_once_agree`, `test_two_wall_twin`, `test_e1_catches_the_dropped_leftover`). Left: ties with movable partners. Rule: what one step owes a body is gathered before any of it is applied; and a contact the handlers saw is a contact resolve answers |
| **A handler's side effect hides the rest of the frame from the same contact** (a destroy, park, `untag` or group change inside a handler changes what the rest of that contact's dispatch, or `resolve`, sees) | PG-PB5 (a destroy hid the contact's other enter handlers: scoring depended on spawn order), PG-PE5 (a destroy hid the contact from `resolve`: no bounce), PG-PB3 (an exit handler's destroy / untag hid the other exit handlers), PG-PB1 (an `untag` mid-contact hid the exit) | `test_collision.TestEveryEnterHandlerOfAContactRuns` (both spawn orders), `TestAContactsExitComesAfterItsHandlers`, `TestBounceOffAPartnerAHandlerRemoved`, `TestExitAfterGroupChange`; every door, not only handlers: `test_laws_chaos` / `test_laws_chaos_families` (the owed check after a command at any door) and the `F3_PLANTS` canaries. Rule: the snapshot rule ([Laws](Laws.md) F3): choose what a pass owes (a contact's handlers, its resolve response, its exit) before the first author call runs; what a command removed starts nothing new, what it made waits for that loop's next pass; only an act change cancels what the ending act owed, its own hooks on game bodies included (CD2, fixed) |
| **A rule's outcome depends on another rule** (state kept per pair of bodies, or per contact, read as if it were per rule: a rule that begins or stops matching while the pair stays takes the pair's phase) | CD3 (a tag joined mid-contact: enter only if nothing else paired the bodies), CD3-x (a tag left while another rule keeps the pair: no exit ever), CD3-b (a blink: an exit with no enter) | Equation E15 (a no-op rule beside every program's and example's rules changes no other call; canary: the per-pair rule); `test_collision.TestARuleAContactGainsOrLosesMidContact` runs each case alone and beside four other pairings. Rule: a rule's phase is read per rule at the commit, not inherited from the pair |
| **A name the engine looks up is silently never called** (a class-body hook misspelled, a top-of-file name written in a class, a hook name that shadows an engine method) | PG-PA3 (`def update(self, dt)` / `on_key_down` in an act; `update` on a Shape replaced the graph's recalculation), PG-PC5 (`on_colide`, `on_updat`, a plain `collide_with`); sibling of AH1 (an `async` hook) | `tests/test_class_hook_names.py` (every exported family; the near-miss pool follows `_ACTOR_HOOK_NAMES`, the top-level list follows `set_auto_callbacks`). Rule: every name the engine discovers by name is checked where it is written (the class line), against the engine's own list, and the author's own helper names stay legal |
| **A value protocol added to a type that is also an argument** (`__iter__`, `__len__`, `__eq__` on a type the engine takes as an argument change every entry that decides "is this a sequence?" or compares by protocol) | PE1 (value `==` on a Point weighed and refused: registry scans and weak keys rely on identity), PG-PB6 (`__iter__` on Point / `Vec2` / `mouse`: every link / copy entry reads a point by type; the entries that take a list of points refuse one point first) | `test_point_unpack.TestPointKeepsItsMeaning` (link rows still follow after the source moves) + `TestNotAList`. Rule: entries read by type, never by protocol; an entry that takes "a list of X" refuses one X first |


# Bug catalogue

Series: **H** Hypothesis batch 1 (`test_hyp_*`), **R** regressions caused by fixes,
**S** system suites (`test_sys_*`), **A** API surface, **D** differential, **W** world
machine extensions (M4), **O** order / isolation (a test that depends on what ran before it), **G** geometry properties (transform algebra, round trips, invariance), **F** contact flicker (what a player sees across real frames), **SU** seam lips (a walker meeting the side face of the next tile), **AH** async functions where Scena calls one, **KN** knobs that change nothing, **CT** continuous detection (fast bodies between frames), **CS** closed surfaces (a write to a name the object does not have), **GR** graphics review (2026-10-08: Shape / Sprite / Graphic / Entity; the review's own IDs SA / SB / SC / E / HP / PA / PB are kept, members its class guards found are GR1…). "Guard" is the regression test in the owning file.

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
| R10 | `test_hyp_events` (gate, 2026-10-11, also on `4bd79ad`): a cycle of three `@on_change` relays fired 27 times where the model expected 24 | SY5 made only rounds where a watch fires *again* count toward `FLUSH_MAX_ROUNDS`; the Hypothesis model kept counting every round, so a cycle whose first round is all first fires runs one round more | Hypothesis, once, in a gate run | Model updated (`EventMachine._poll_model` counts repeat rounds, reads `FLUSH_MAX_ROUNDS`); `test_hyp_events.TestRelayCycleRounds` replays the shrunk case. Rule: a fix that changes a documented rule updates every model of that rule (`grep` the constant or the rule's name in `tests/`) |

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
| T5 | Latent (2026-10-27, found moving shader Text to the glyph atlas): `uiwidget._paint_for_upright_string` shifted a shader by twice the baseline height; drawn through it, a vertical Gradient on a Text slid down by 2 × its baseline | `Text("RING", center=(300, 200)); t.fill = Gradient("red", "blue", angle=-90)` drawn with `draw_string_upright` → the letters a single colour from the gradient's far end | The local matrix was `translate(-x, -y) · scale(1, -1)`; undoing the draw's `translate(x, y) · scale(1, -1)` needs `scale(1, -1) · translate(-x, -y)`. No caller passed a shader (widgets draw solid colours; shader Text drew paths), so nothing saw it | `test_text_shader_ink.TestShaderInkFrame` (inside the letters a shader Text paints what a Rect of its box with the same material paints, in five poses; p99 127–241 with the old order). Rule: a pixel test of a material compares against a Shape of the same box, inside the letters (edge pixels shrunk away: Skia sets glyph edge coverage by the paint's luminance) |

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
| O11 | `test_knobs_take_effect.test_canary_metal_without_its_tint` failed after `test_visual_color_param` in one process (on `787297d` too) and passed alone; after the canary, `Metal("deepskyblue")` drew a chrome rim in every later test | `SCENA_CANARIES=1 python -m unittest tests.test_visual_color_param tests.test_knobs_take_effect` | `Metal.__init__` bakes its rim (`self._edge = _metal_edge(...)`) and the look is interned per key: the seeded sweep had interned `Metal("deepskyblue")` with the real rim, so the `_metal_edge` plant never reached the knob sweep (the `_metal_tint` half is read per draw and did); the instance the plant built, when none was interned yet, kept the planted rim after `mock.patch` stopped | `hypothesis_support.fresh_interns` (empty `_RECIPE_CACHE` / `_VISUAL_CACHE` / `_FILTER_CACHE` for the plant, old entries back after) in `assert_catches` and `game_harness.run_patched`; the canary interns its Metal first and checks it comes back unchanged; `test_knobs_take_effect.TestCanaryPlantsReachInternedLooks` (both directions; every interned exported look sits in a cache the helper clears). Swept: no other canary plants a function an interned look reads at construction (the others patch per-draw helpers, per-call methods such as `Metal._unseed`, or engine classes) |
| O12 | `test_refusal_atomic.test_every_kind_call_and_source` reported a new violation whose only moved census key was `registry.live`, on a different case each run (`Rect spine side_left \| dead \| p2 =`, `RegularPolygon center_side \| linked \| reset_rotation()`, `Svg \| dead \| recently()`): 2 of 3 runs with 6 copies in parallel, once in a gate; alone it usually passed | Deterministic: the probe with `gc.set_threshold(100, 10, 10)` fails every run (`Anchor \| dead \| show_points()`, `registry.live` 3 → 2; at 50, 11 cases); `TestCensusWindowIgnoresEarlierGarbage` plants the garbage and collects inside the call | O9's class on the roster. The probe takes `surface_census(collect=False)` before and after each call (a collect per case costs minutes), and `registry.live` is weak. Earlier cases leave measuring Boxes (reference cycles, never destroyed: they are throwaways) whose center Points hold roster entries until a gen-2 pass; under load another allocation pattern put that pass between the two censuses. The engine was right: a gc callback showed only those Points leaving, and with the GC paused no case moves the roster | `_probe_once` takes both censuses and the call inside one `gc_paused()` (the clone refusal test too). Regression: `TestCensusWindowIgnoresEarlierGarbage` (garbage alive at the baseline, unreachable in the call, a collection where an automatic pass may land; canary: the pause patched out). Class guard: `test_count_baselines` also flags a `census(collect=False)` / `surface_census(collect=False)` with no settle before it (`test_hyp_surface._trace` marked: its baseline is collected and a move is re-checked settled) |
| O13 | Latent (review 2026-10-27): `test_audio.TestStreamsCloseBeforeExit.test_both_exits_close_the_streams` called `atexit._run_exitfuncs()` to prove `close_open_streams` is an exit handler | `atexit.register(f); atexit._run_exitfuncs(); atexit._ncallbacks()` is 0 | `_run_exitfuncs` runs **every** handler of the process (logging, the microphones, the display link, `stall`'s ended-without-`run()` check) and then clears them all; the test put back only its own. In one process (`unittest discover`, the deep serial pass) every later test lost its exit handlers. It also proved nothing: it re-registered the function itself. Counting does not work either: `atexit.unregister` empties the slot and leaves `_ncallbacks()` unchanged | The test now runs the exit in a fresh process: a fake stream in `_OPEN_STREAMS` must print from its `close()` at exit (fails with the `atexit.register` line removed). Rule: a test of an exit hook exits a child process; never `atexit._run_exitfuncs()` in the test process |

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
| G18 | A formula that names `shape.rotation` went stale when the heading changed without a pose verb: a `center=, radius=` Circle on a flip, `angle =` or an `angle` link; a Line when an endpoint was written or dragged; a `reversed()` Track view on every change (its formula bound the view's own, never-notified node) | Geometry smoke, Heading page: `flip_x` → the arc flips, its heading arrow (`p2=` a function reading `arc.rotation`) stays | Formula sources come from the source text, so the formula depends on the `rotation` property anchor, which only `_pose_rotation_set` / `_pose_rotation_add` mark dirty; Line and Circle read `rotation` from their geometry, and a Circle flip writes `angle`, not the pose value | The checks re-read `rotation` (a pulled read re-evaluates); the unit repros used stdin lambdas, whose source cannot be read, so they took the broad path. Found by the maintainer on the visual smoke | `test_angle_field.TestAngleFormulasStayFresh` (every registry kind × heading change, plus endpoint writes and links, read bare); the smoke's `arrows follow rotation` check (fails on the old engine). Fix: `_HeadingFromGeometry` (Line, Circle: the `rotation` anchor depends on the shape), `Circle._sync_rotation_to_angle`, `_ReversedTrack._ensure_scalar_anchor` → the host's node. Class: **A check reads through the path it is meant to test** — verify a linked consumer by what it holds (read bare), not by re-reading the source |
| G19 | One heading, two names: Rect / Square / Ellipse / RegularPolygon / EquilateralTriangle called it `rotation`, Line / Circle / Box / Jet `angle`. `rect.angle = 30` was accepted as a custom ink field and the rect did not turn; a p1/p2 Line read `angle` 40 and `rotation` 400 after `rotate_by(400)`; the tangent Line read `rotation` 240 after `rotation = 150`; and `rotation = θ` / `rotate_to(θ)` gave different geometry under one name on shapes placed by a corner, an end or a vertex | `Rect(center=(0, 0), width=4, height=2).angle = 30` → `rotation` 0; `Line(circle=c, angle=0, length=20).rotation = 150` → 240 | Unify Phase 1 merged `angle` into `rotation` on five kinds and deferred Line; the noun of `rotate_to` became a field whose write keeps the placement point; the ink near-miss check only catches names of 6+ letters one edit from a real property; `Line.rotate_to` measured from the tangent model's *position* `angle` | Each kind was tested in its own spelling; nothing wrote the other kind's name and checked that the shape turned | `test_angle_field` (`TestRotationIsRetired`: every kind × every `rotation` spelling, and every `_INK_RESERVED` name never becomes ink; `TestAngleWorksOnEveryKind`: `x.angle = v` reads back and `rotate_by(400)` reads `+400` on every kind; `TestLineTangent`). Fix: the heading is `angle` on every Graphic ([Shapes Design — Geometry contract](Shapes%20Design.md#geometry-contract)); `rotation` in `Graphic._RETIRED_ATTRS`; tangent input `at_angle`. Class: **A kind implements a shared verb its own way** — and its sibling: **a retired or reserved name becomes ink** |
| G9 | `sprite.box` sat half a height low under `Sheet(anchor="bottom")` and ignored `scale` | `Sprite(Sheet(p, anchor="bottom"), center=(100, 100), width=64, height=64).box` → bottom 68, top 132; the art spans 100..164. `s.scale_by(1.5)` left `box.width` at 64 | `region_frame` built a Sprite's box from `center` + `width` / `height`. `center` is the **pivot** (at the feet under `anchor="bottom"`) and `width` is the size knob (no `scale`). It now uses the drawn rect (`Sprite._oriented_frame`) and keeps the heading as the angle (G7's names) | `.box` tests used centre-anchored, unscaled sprites, where pivot = middle and knob = drawn size | `test_sprite_measure.TestSpriteBoxIsTheDrawnCell` (anchor, scale, offset, flips, rotation about the pivot, the hitbox inside the box — independent expected numbers). Class: **A measurement read from the pose knob instead of the drawn geometry** |
| G20 | `confine` lifted a Sprite under `Sheet(anchor="bottom")`: a ninja walking into the screen edge climbed ~1900 units/s to the top (tutorial 18, 2026-10-09) | `s = Sprite(Sheet(p, anchor="bottom"), center=(990, 300), …)`; each frame `s.move_by(5, -5); s.confine(canvas.game_view)` → `center.y` rises instead of falling | `confine` compared `_center_xy()` (the **drawn** middle, G9) and wrote the result with `_move_to` (the **pivot**, at the feet): every clamp moved the pivot up to where the middle was. Now `by="center"` compares the pivot and `"box"` / `"overlap"` the drawn box, and the correction is applied to the pivot as a delta | confine tests used shapes and centre-anchored sprites, where pivot = middle; the platformer tutorials were the first anchored sprites to touch an edge | `test_confine.TestAnchoredSprite` (center / bottom / top anchors, every `by=`, wrap and bounce; verified to fail on the pre-fix code). Class: **A pose writer fed a point measured in another frame** (drawn box vs pivot) |

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

### SK — sky / gradient preset names and direction (2026-09-30, 2026-10-13)

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| SK1 | `SkyGradient("space")` raised "neither a sky preset nor a color. Did you mean 'space'?", and its "Sky presets" list named `space`; `toxic`, `forest` and the aliases `void` / `cosmos` / `alien` / `radioactive` failed the same way. `Gradient("toxic")` / `Gradient("forest")` fell back to magenta with a warning | `SCENIC_PRESET_NAMES` and `_SKY_ALIASES` listed names `GRADIENT_PRESETS` had no ramp for (the forest ramp was keyed `tgreen`). The error built its list and suggestions from the name set, not from what resolves. The preset test exempted the missing names as "reserved / retired" | `test_gradient_presets` (`test_every_scenic_name_has_a_ramp`, `TestSkyPresetNamesResolve`). Fix: `space` / `toxic` ramps added, `tgreen` renamed `forest`; `_resolving_sky_names()` feeds the message |
| SK2 | `scripts/smoke/shape_fx.py` drew its `viridis` and `toxic` swatches magenta | Preset strings that are not preset keys (viridis is `vrds`) fall through to a color lookup, which warns and returns magenta | `TestSkyPresetNamesResolve.test_smoke_script_sky_and_preset_strings_resolve` (scans `SkyGradient("…")` and one-name recipe tuples in `scripts/smoke/*.py`) |
| SK3 | `Gradient("red", "blue", angle=90)` was red at the bottom as a shape fill and red at the **top** as a `Wallpaper` / `canvas.background` (a sweep wallpaper turned clockwise); the Guia says 90 = bottom → top (user, 2026-10-13) | `build_background_fill` builds the wallpaper paint in device pixels (y down) and scaled the gradient's local frame by `+h/design_height`; a shape gets the y flip from the canvas. `SkyGradient` (stops top-first, `angle=90`) and the tutorials' space and sky backgrounds were written against the flipped frame, so nothing looked wrong | `test_gradient_direction` (every surface that draws a Gradient: shape fill, `size=`, Circle, Menu panel, Wallpaper, Wallpaper `size=`, `canvas.background =`; sweep direction shape vs wallpaper; SkyGradient zenith on top; canaries: a reversed ramp reads "down", a sky on `angle=90` is upside down). Decided (user, 2026-10-13): Wallpaper follows y-up, listed under **Fixed** for 0.8.1 with a "relied on it" note (the Guia already said bottom → top); tutorials and examples swap their two colors so every picture stays; `SkyGradient` uses `angle=-90`. Fix: [Canvas Design](Canvas%20Design.md) (Gradient / solid). Found in passing: a Wallpaper ignores a `Texture`'s `angle` (SK4) |
| SK4 | `Wallpaper(Texture("x.png", fit="tile", angle=30))` (every fit) drew the image unturned; the same Texture on a shape turns counter-clockwise. The class sweep then found `shift=` (`HueShift` / `Recolor`) and `set_alpha` dropped the same way (2026-10-13) | `build_background_fill` built the image matrix and paint from `fit` / `scale` / `tile_size` / `tile_mode` only; the Wallpaper knob sweep covered `Wallpaper(...)` keywords, never the knobs of a `Texture` passed as the source | Decided: honour all three, as on a shape (cost baked into the cached fill; `Wallpaper.draw` A/B flat). `angle` is y-up CCW about the frame center, about world `(0, 0)` on tile; listed under **Fixed** (the code it changes was taken and ignored). `test_gradient_direction.TestTextureAngleTurnsTheSameWay` (shape vs Wallpaper, ±90°, every fit and draw path, tiles; canaries: angle dropped, tile turned clockwise); class guard `test_knobs_take_effect` Texture sweep (every `Texture` knob from the signature + `set_alpha` × every fit; `color=` listed: a proxy hue, no look on a Wallpaper; canary: `_texture_turn` → 0 and `_texture_knobs_paint` → identity), `test_set_alpha_after_the_wallpaper_drew`. Fix: [Canvas Design](Canvas%20Design.md) (wallpaper images) |

### IN — keyboard input (2026-10-01, 2026-10-13, 2026-10-21)

Found while spiking the level editor (Cmd+S / Cmd+O polled with `keyp.once`).

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| IN1 | `keyp.once("CMD+O")` fired for keys that were never down together. Pressing Cmd alone opened the dialog if O had been typed earlier; tapping Cmd and then O did too. A fast Cmd+S (S down and up within one poll, Cmd held and already read) did **not** fire | `update`: `if keyp.once("CMD+O"): …`. Tap O, then press Cmd | Unread rising edges stay in `_pending_edges` until a `once` reads them (by design). The same-poll fallback merged **every** pending edge with the keys down now, so presses from different moments made a chord. It also required the modifier's own edge to be unread | `test_keyp.TestOnceChordNeedsKeysDownTogether` (each repro); `TestOnceChordProperty` (random taps / toggles / reads: `once(spec)` fires only if the spec's keys were down together, with no extra modifier, since it last fired) with canary `TestOnceChordCanaries`. Fix: each pending edge keeps the keys that were down at that press. The fallback fires only when a pending press of one of the spec's keys had the whole chord down (`_pending_rises`). One read consumes **every** pending press that completed the chord (deep-tier find: O held, Cmd-L and Cmd-R tapped in one poll fired twice), as two taps of one key collapse into one edge — `test_left_and_right_modifier_taps_under_a_held_key_are_one_read` |
| IN2 | A key written into a field raised: `st.nome = key` over `"x"` ("on_key receives 'X', not 'x'"), `t.text = key` on `Text("Aperte")` ("unknown key"); also a key inside a tuple / list / dict cell (user, 2026-10-13) | `st.nome = "x"`; `def on_key_down(key): st.nome = key` | `KeyName.__eq__` raises on a string `on_key` cannot deliver, to catch `key == "ESCAPE"`. The engine's change check (`old != new`) is such a compare, and Python asks the `str` subclass first even with the old value on the left. The strictness was tested only in the handler, never with the key as data | `test_key_name_fields`: every field kind × old values `"x"` / `"Aperte"` / `""` (st cell, bound st cell, `Text.text` direct and linked, ink first and later write, `Button.label`, `TextInput.text` / `.placeholder`), nested keys, a real key press; class guard `TestEveryStrFieldTakesAKey` (every public `str` field of Text, shapes, Sprite, widgets); canaries for each half. Fix: fields unwrap the key to `str` (`state._KEY_NAME`); the compare raises `KeyNameMismatch`, which change checks read as "changed" ([Scena Design](Scena%20Design.md), key specs). Lesson: a value with a loud `==` must not outlive the call it was made for, or every engine compare becomes its typo check |
| IN3 | After a screenshot no key worked: `examples/affinity.py` ignored UP, DOWN, SPACE and 1 2 3 R T, also after a click on the window (user, 2026-10-21) | macOS: Cmd+Shift+4, take the shot, come back. Or press Cmd, then release it in another app's hotkey | The OS grabbed the keyboard while Cmd was down and the window never got Cmd's release. `keyp` held Cmd for good, and a held Cmd hides every bare play key (`keyp`, `once`, `on_key_down`). GLFW holds the key too, so `glfw.get_key` (the resync seed) agreed: no test sent an event whose `mods` disagreed with the held keys (the drivers sent `mods=0` under a held Ctrl) | `test_lost_modifier_release`: the repro (held and `once` keys, ups once, a click frees them); class guard `TestEveryModifierEveryEvent` (8 modifiers × play key press / repeat / release, unnamed key, button down / up; still-held modifiers stay; another family's event drops nothing); the macOS next press (a release with the flag set) and the X11 orphan release. Fix: `_drop_lost_modifiers(mods)` on every non-modifier key and button event, through the normal up (`_key_up`). The input drivers (`input_driver`, `program_support`) now send the held modifiers as `mods`, as the OS does. Lesson: a fake input source must carry the redundant state the OS sends (`mods`), or the engine's use of it is never tested |

### WP — Windows / platform portability (2026-10-01, 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08, 2026-10-22, 2026-10-26, 2026-10-27)

WP1–WP4: found by the quick tier on Windows 11 (12 jobs failed; the Mac passed the same tree). Tests only: the engine rendered correctly. WP5–WP9: the quick and gate tiers on the same machine, five days later. One shipped fix (the editor's Linux `.desktop` writer); the rest is tests and the runner. WP10–WP15: the next gate runs on that machine (2026-10-06); tests and the runner, plus one engine bug, A33. WP16–WP17: latent, found by a read-only audit of the suite for platform defaults after those fixes (nothing failed yet). WP18: the quick tier on the Mac (2 of 7 runs on 2026-10-07); the test only. WP19: the quick tier on Windows (2026-10-08, 1 of 182 jobs); tests only. WP20–WP26: the quick tier of the 0.9.0 release on a clean Windows 11 install (fresh clone, new venv, Python 3.12, skia-python 144.1; 5 of 311 jobs, on a slower machine: 623 s wall); two engine bugs (WP20, WP21, fixed in 0.9.1), the rest tests and test tooling. WP27: the next quick run there, with those fixes (1 of 311 jobs); the test only. WP28: a release check (`validate_guia.py --examples`) run with its output piped, before the 0.9.1 gate. WP29–WP30: the 0.9.1 gate on that machine (5 of 456 jobs: 16 GB, 12 threads). WP31: the next gate there, `-j 4` (1 of 456). WP32: the review of WP20's leftover (the message), on the Mac: the effects' cost measured, 2026-10-22. WP33: the review of WP31, on the Mac: run counts, 2026-10-22. WP34–WP35: the gate's other long jobs, on the Mac, 2026-10-23. WP36: the quick tier of the 0.9.1 merge into main, on the Mac, 2026-10-23. WP47–WP48: the first CI runs on GitHub's Ubuntu runners, 2026-10-26. WP49: the 0.10.1 quick tier on the Windows laptop (10 workers), 2026-10-27; the test only. WP50: the quick tier of 0.10.1 on the Windows machine (fresh clone; every job passed, 686 s wall), 2026-10-27. WP51: by ear, `examples/pendulums.py` at `canvas.framerate = "max"` on the Windows laptop, 2026-10-27; an engine bug.

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
| WP20 | `test_game_oficina` (all 3): `LEFTOVERS {'graph.nodes': (5, 3), 'registry.live': (8, 2), …}` after `SCENA ERROR: the script has run for 8 s without reaching run(), stuck at oficina.py:65` (a top-level `SINO.bake(...)` with Reverb, cold run); passed warm | **Engine.** The stall watch (`stall._watch`) read the main thread's frame into a local of its endless loop and kept it after the report: the stack and its locals' values (five free `Point`s) stayed alive. Reproduced by lowering `TOP_LEVEL_STALL_S` to 0.5 s: the same leftovers, gone with the fix | `test_stall.test_a_report_keeps_no_frame_of_the_main_thread` (reads the watch thread's own locals: no frame after a report); the class: `test_stall.TestNoFrameKeptByALoop` (AST over `scena/`: no `sys._current_frames` / `_getframe` in a `while` body). Fix: each look is `stall._poll`, so the frame dies on return. The message blamed an author loop when the slow line was an engine bake: WP32 |
| WP21 | `test_atlas.test_sdf_image_bytes_unchanged`: 4 of 9 000 bytes differ, `[0, 0..3]`, different on every run (`32 231 192 231`, then `208 202 240 202`) | **Engine.** `_mask_to_sdf_image` passed `skia.Pixmap` a temporary (`bytearray(rgba.tobytes())`); a Pixmap borrows its buffer without a reference, so it was freed before `MakeRasterCopy` read it, and the Windows allocator wrote its bookkeeping into the first bytes. 4 distinct images in 50 bakes, 1 after the fix. The Mac allocator left the bytes alone | `test_atlas.test_sdf_bakes_agree_with_each_other` (20 bakes with allocator churn, byte-equal); `test_platform_portability.TestSkiaBorrowedBuffersStayNamed` (AST over `scena/`, `scena_editor/`, `tests/`: the buffer of `Pixmap`, `MakeWithoutCopy`, `MakeRasterDirect`, `installPixels`, `fromarray` / `frombuffer(copy=False)` is a name). Fix: the array is bound to a name until the copy |
| WP22 | `test_atlas.test_bake_of_a_large_cell_is_fast`: `0.117 not less than 0.08` in quick, 0.165 alone | One sample against an absolute bound sized on the Mac (WP7's rule); this machine is slower | Best block of four interleaved rounds, as a ratio to the scalar EDT on a 64 × 64 mask (~0.6 there; the old hot loops would read ~3; limit 1.5) |
| WP23 | `test_scripts_run.test_the_two_halves_cover_every_script_once`: every `scripts/smoke` file missing from the set (`…\scena\scripts/smoke\audio.py` vs `…\scripts\smoke\audio.py`) | `os.path.join(ROOT, folder)` with `folder` from `for folder in ("scripts/smoke", "tests/loads")`; `EXTRA` joined the same way. WP19's guard read only literals and parameters in the join | The guard follows names bound to `/` literals (`_slash_names`: assignments, loops and comprehensions over a literal collection or a name holding one); it found three more joins (file creation in `test_platform_portability`, `test_run_tiers`), normalized too. Fix: `os.path.normpath` on each |
| WP24 | `test_laws_probe.test_an_engine_raised_error_is_told_apart`: `engine scena\input.py:297` where the test reads `engine scena/` | `probe._where` built the engine line with a bare `relpath` (WP11's rule) | The test itself, now that it runs on Windows. Not guarded statically: the other bare `relpath` calls in `tests/` are failure text nobody reads back. Fix: the label in `/` form |
| WP25 | `test_laws_probe.test_a_hang_is_a_flag_with_its_stack`: the dump showed `importlib` and `hypothesis_support.py` (importing `scena`), not `hang.py`; failed alone, passed under load once | The child armed `faulthandler.dump_traceback_later(timeout - 2)` before importing Scena; with `PYTHONDONTWRITEBYTECODE` every child compiles it, past 6 s on that machine | `test_laws_probe.TestHangClockStartsAfterImports` (a `sitecustomize` makes the import take 3 s against a 4 s budget; fails on the old order). Fix: the child imports the support modules (which import Scena) first; the parent's timeout, a backstop, gets 60 s for the imports |
| WP26 | `test_run_tiers.test_timeout_is_a_failure`: `PermissionError: [WinError 32]` on `slow.log` at `TemporaryDirectory` cleanup, in quick; passed alone and 10 times in parallel | A venv's `python.exe` is a launcher: `Popen` gets its pid, the interpreter is its child. `kill()` + `wait()` end the launcher; the interpreter, holding the log, ends a moment later (checked: gone 0.15 s after). Not reproduced on demand | `ignore_cleanup_errors=True` on that folder and on the probe's (`probe._spawn`, whose backstop kills too). No guard: two sites |
| WP27 | `test_postfx`: `TIMEOUT after 300 s` in quick (290 s in the run before, 178 s alone) | `TestPostFxHeadless.test_every_post_effect_draws_without_gl` took 180 s of it: with no window the framework keeps its default 2000 × 1200 framebuffer (`init()` sets the design size, not `fb_width`), so `SystemWorld`'s raster surface and every post pass ran 2.4 Mpx of SkSL on the CPU, 25 effects × 3 frames (CosmicBloom 17 s a frame). The Mac pays the same pixels, faster | The test pins `fb_width` / `fb_height` to 200 × 150 for its world: 3.7 s, the same 25 effects each change the frame. Rule below ("A headless frame is 2000 × 1200") |
| WP28 | `python tools/guide/validate_guia.py --examples | tail`: `UnicodeEncodeError: 'charmap' codec can't encode character '→'`; the checks themselves passed | A stdout redirected on Windows encodes with the locale (cp1252) and `errors="strict"`; the tool printed `303 símbolos → symbols.json`. `_transform_guia.py` the same. A console prints UTF-8, so only a pipe or a file showed it | `test_platform_portability.TestToolsPrintOnACp1252Stdout` (AST over `tools/`: a `print` of text cp1252 lacks needs a `.reconfigure(...)` in the module). Fix: `sys.stdout.reconfigure(errors="backslashreplace")` at the entry, as `run_tiers.py` does. Also seen: the same tool wrote `symbols.json` / `guia-api-symbols.js` with `write_text`, so CRLF on Windows (`.gitattributes` stores LF: `git status` listed them, no diff). Fixed in 0.9.1: every text write in `tools/` names `newline="\n"`; guard `test_platform_portability.TestToolsWriteLf` (AST over `tools/`: `write_text`, `open(…, "w"/"a"/"x")`, `Path.open("w")`) |
| WP29 | `test_laws_equations.TestRuleNeutrality.test_examples` and `TestSpawnOrder` (every example), `TestBoundOrClosure`: `OSError: [WinError 1314] O cliente não tem o privilégio necessário: '…\examples\README.md' -> '…\laws_eq_…\twin\README.md'` | The twin's folder mirrored the original's with `os.symlink` per entry; on Windows a symlink needs Developer Mode or an administrator. `probe._stage` linked `media` the same way (no quick fixture has one). `test_tutorial_steps` already fell back to a copy | `source_support.link_entry` (symlink, else a junction for a folder, a hard link for a file, else a copy) at the three sites; `test_platform_portability.TestLinksNeedNoPrivilege` (symlinks refused by a mock: the twin still reads the files; cleaning the twin keeps the target; no bare `symlink` in `tests/` outside the helper) |
| WP30 | Gate: `test_laws_neutrality.TestGames` and `test_laws_families.TestPrograms` died with `rc=3221227274` (`0xC0000409`, a native abort; the first with an empty log) within a minute of each other; `TestBoundOrClosure` timed out on `constelacao.py` at 240 s (47 s alone). All five failed jobs pass together with `focused` | Memory, not code. The gate's 10 workers each ran a laws module whose own pool starts up to 8 Python children: ~80 processes. Windows commits each process's heap (no overcommit, unlike macOS): with only those five jobs (46 processes) committed memory peaked at 18.84 GB against an 18.82 GB limit (RAM + page file). A failed allocation in native code aborts (`0xC0000409` is `abort()` on Windows); paging slowed the rest past their timeouts | None in code yet. Rule below ("Workers × children must fit the commit limit"); the gate on that machine runs with `-j 4`. Open: a default `-j` (and inner pools) sized by memory as well as CPUs |
| WP31 | Gate `-j 4`: `test_laws_equations.TestRuleNeutrality`: `TIMEOUT after 1800 s` (159 s at the `dev` profile); `TestSpawnOrder` 1580 s | At `ci`, `test_examples` runs every candidate (`limit=None`), and once WP29 let the twins run, `ninja_5_espada.py` alone had 37 E15 runs of 600 frames (~10 s each idle). The pool mapped over scripts, so those ran one after another in one slot while the others idled: a long tail past the job's timeout on a slower machine | `equations.e3_script_runs` / `e15_script_runs` split a check into its base run and one run per twin (`e3_script` / `e15_script` run them in order, as before); `test_laws_equations._spread_runs` puts every run of every script on the pool, longest scripts first, and judges each script with its own results (`TestSpreadRuns`: order kept, an error stays its script's). Both `test_examples` at `ci`, alone: 623 s |
| WP32 | WP20's run: `SCENA ERROR: the script has run for 8 s without reaching run(), stuck at oficina.py:65` (a top-level `SINO.bake(...)` with Reverb); the message told the author "a game needs no loop of its own" | **Engine.** Every effect stepped through its numpy array a row at a time (`for i in range(x.shape[0])`), paying numpy's call cost per sample: per second of stereo on the Mac Reverb 0.53 s, Distortion 0.52 s, Echo 0.10 s, LowPass 0.07 s; ~2.5× that on the Windows machine, so a live Reverb voice there needed more than real time on the mixer thread. And the stall watch had no way to tell engine work from an author loop | `test_audio_effects.TestEffectsMatchTheSampleLoop` (the 0.9.0 per-sample loops as the reference: the same bytes, mono and stereo, in any block sizes); the class: `TestNoSampleLoopOverRows` (AST over `audio_effects.py`: no `range` over `.shape` / `.size` / `len`). `test_stall.TestEngineWork` (a slow top-level or in-frame bake is a note; its time is not the phase's; a loop after it is still the error). Fix: delay lines a run of `n` samples per step (`_delay_line`), one-pole filters over Python floats: Reverb ~65×, Echo ~600×, Distortion ~15× faster, bit for bit (Sound Design, Effects). `stall.busy` marks engine work (Actors Design, the stall watch). Found on the way: a Reverb comb outputs what it writes, not what it reads (the old read was a view of the slot it overwrote); kept, it is the sound authors have |
| WP33 | WP31's fix spread the runs over a job's pool, but the job still held every example: on the Mac, recorded `ci` times of 1 824 s (`TestSpawnOrder`) and 2 046 s (`TestRuleNeutrality`) under a loaded gate | A job's work grew with `examples/`: 333 E3 and 183 E15 runs at `ci`, ~8 s each on the Mac. The English tutorials added 37 English examples, each the Portuguese one renamed: 124 E3 and 67 E15 runs that repeated the same programs (and every other laws module ran both too) | `test_example_translations` (every glossary pair in `examples/` passes `tutorial_parity.code_parity`; a drifted twin fails); `test_laws_equations.TestShardPlan`. Fix: `law_scripts` leaves the English twin out below `deep` (E1, E3, E6, E15, families, chaos families, neutrality); the E3 / E15 example checks are classes of at most `RUNS_PER_JOB` runs, one job each (`ci`: 5 E3 jobs of 41–43 runs, 3 E15 jobs of 38–39; the Mac's gate at load ~100: 31–237 s each, against 1 824 / 2 046 s for the one job before). The program halves were then the longest jobs (E3 1 010 s, E15 848 s, 511 and 392 serial runs): program × scenario classes of at most `PROGRAM_RUNS_PER_JOB` runs (`ci`: 5 E3 jobs of 102–103, 4 E15 jobs of 98). Rule above ("A gate job's work is a count") |
| WP34 | The gate on `feed6ed` (Mac, load ~100): `test_hyp_surface.TestMethodJunk[1/2]` 1 130 s, `test_laws_chaos_families`'s games job 663 s and its fixtures job 507 s, `test_laws_equations.TestBoundOrClosure` 528 s | Each job held a whole family: E6 ran every example with a bound-method timer serially (18 runs), E1 pooled per script (148 runs); the chaos fixtures (4 × 32 runs and the S5 sweep, 19 door kinds × 22 commands = 418 runs) and games (4 × 8 runs) one after another; `TestMethodJunk` 40 tests of 40 examples a job. Alone, `TestMethodJunk` is 216 s for all 59 tests: most of the gate's time was contention | `TestShardPlan` (every E1 / E3 / E6 / E15 example within the cap), `TestS5Jobs` (the command groups are the sweep, each within `S5_RUNS_PER_JOB`), `test_run_tiers.TestShard.test_a_heavy_class_gets_its_own_chunk`. Fix: `e1_script_runs` / `e6_script_runs` and their shard classes (`ci`: 4 E1 jobs of 36–40 runs, 1 E6 job of 18); `TestFixture_<name>`, `TestGame_<name>`, `TestEveryDoorEveryCommand<k>` (6 commands each); `run_tiers.CHUNKS`. Alone at `ci`: every new job 16–200 s, S5 34–42 s |
| WP35 | `focused test_laws_chaos_families` (dev), once in four: `s4_timers: idle rewrite frame 24: only in the program [('H', 'cancel', 'Handle:wait@s4_timers.py:107#2')]; only in the twin [('H', 'cancel', 'Handle:after@-#5')]` | The recorder's labels are checked by a weak reference (S7), but `Handle` had none (`__slots__` without `__weakref__`): the check was skipped. `after(0.1, doomed.boom)` on a destroyed actor is cancelled inside `Scheduler.add`, before the probe labels it; its cancel read a freed handle's label whenever the new handle landed at that address, which depends on the process's allocation history | `test_laws_quick.TestLabelsFollowTheObject.test_a_reused_handle_id_does_not_inherit_a_label`; the class: a labelled type without a weak reference is a recorder error (every laws check fails on it). Fix: `__weakref__` in `Handle.__slots__` (8 bytes; create + free 103 → 104 ns) |
| WP36 | `test_pacing_corevideo.TestLiveCoreVideo.test_pacer_uses_display_link_on_macos`: `Items in the first set but not the second: 2` in quick; passed 3 of 3 alone | The test held every one of 17 presents to exactly one vblank apart in wall time; under the tier's load a tick missed a vblank and the locked pacer waited for the next (a step of 2, correct) | The test itself: no step of 0 (two presents in one vblank) and a median step of 1. The class is WP3 / WP7 / WP18's (a wall-clock check under load) |
| WP37 | The same test in a loaded gate (load average 12–16): `0 unexpectedly found in [1, 1, 1, 1, 5, 0, 1, …]`; passed alone | The "no step of 0" check (WP36) read the clock after each present: a thread stalled past its vblank presented late for one already gone (4.6 periods on), then on time for the next (5.0), 0.4 period apart on the clock. Every wait targets a later vblank than the last (`_wait_display_link`: the scheduled one, or the first at or after now), so no two presents share one | The test itself: "never two presents for one vblank" reads the vblank each present targeted (`pacer._slot`); the median step stays on the clock. The class is WP36's |
| WP38 | Deep: E1 failed on `plane.py` and `balls.py` (`TestPacingExamples2`, `6`) | `E1_EXCLUDED` names the Portuguese examples (`aviao.py`, `bolas.py`, `naves_5_modos.py`); below `deep` their English twins are left out (WP33), so only deep ran a twin, unexcluded: the same program and the same known limit | An English twin is excluded with its example (`_e1_excluded_names`, from `translation_pairs`); guard `TestPacing.test_an_english_twin_is_excluded_with_its_example`. A list keyed by file name names one program once |
| WP39 | Deep: `TestS5Jobs` `210 not less than or equal to 150` | Deep picks two S5 runs per door, so a group of 6 commands held twice ci's count (the jobs took 42 s on the Mac, but the count is sized for a slower machine, WP33) | `COMMANDS_PER_JOB = 6 // S5_PER_DOOR`: deep has 8 S5 jobs within the count |
| WP40 | Deep: `test_hyp_events` model 54 fires, engine 27 (three relays in a cycle, a capped flush, then a write outside a batch) | The author's write stored the value the cycle's last relay had just written: a same-value write invalidates nothing, so outside a batch nothing polls and the leftover waits for the next flush (the engine's rule). The model polled after every write | The model polls only after a write that changes the value; guard `TestRelayCycleRounds.test_a_same_value_write_leaves_the_rest_for_the_next_flush` |
| WP41 | Deep serial pass: `test_color_link_paint` read black where its rect is, `test_look_group_body` lost a Neon fill, `test_post_targets_camera` missed its target; all pass alone | `boot()` sets 400 x 300 once per process; about 40 modules `init()` their own size in `setUp` and keep it. A later module's pixels at fixed points read under it: after `test_attribute_payload`'s `init(800, 600)` a rect at y 150 drew 300 px low (the y-up flip of a 600-high design) | `SystemWorld` starts at `BOOT_SIZE` and gives the size it found back at teardown (`init()` resizes the canvas in place); a test that sets framework metrics by hand sets the design size with them (`test_view_to_fb_counts_the_letterbox`). Probe: each module after an `init` at 800 x 600 and 1000 x 800 |
| WP42 | Deep serial pass: `test_example_string_theory` (163 chords, 99 strings), `test_example_pulse` (bar lengths), `test_record_game` (37 circles, not 8); all pass alone | `test_diff_pose.test_start_slow_is_not_stale` destroyed each linked shape but not the reference it builds with it (a Rect, a Line, a Circle): 26 actors left, under the leftover check's 50. `ProgramRun` parks another module's leftovers but they stay in `registry().live`, and the example tests counted a kind there | Source: `test_diff_pose` declares `module_sweep`. Class: `program_support.run_registry()` is the running program's roster (registered since its start); the example tests and `test_record_game` count through it; guard `test_prog_isolation.TestRunRoster`. The ~60 modules that still left a few untagged actors under `LIMIT`: WP43 |
| WP43 | The leftover check let a module leave up to 50 live roster items (WP42: 26 untagged actors broke three later modules); made strict, quick failed 53 modules and gate one more | 33 modules left their own actors (a reference shape, a fixture of one test, a `kitchen_sink`; `test_fuzz_corpus` only with canaries on, so only the gate saw it); the other 21 left only what was not theirs: the new canvas's `canvas_rect` (14 modules that made a canvas: a replaced canvas counts whole), or the framework's two HUD labels, built once per process by whichever module first called `begin_game` (`_scena_internal`) | Source: the 33 modules declare `module_sweep`. Class: `LeftoverCheck` fails on one live actor and names each with its site (`leftovers.sites`); only parts may stay, up to `LIMIT`; `made_since` (and so `sweep`, which could have destroyed them) skips the canvas's `canvas_rect` and framework singletons. Guards `test_leftovers` `test_one_untagged_leftover_fails`, `test_lazy_parts_of_an_import_time_actor_are_tolerated`, `test_the_canvas_boundary_rect_is_the_canvas_s`, `test_a_framework_singleton_is_the_framework_s` |
| WP44 | Deep serial pass, every run: `test_rotated_path_draw` "nothing drawn" (2 of 7 scenes once, all 7 since), `test_sys_frame_contracts` `Vignette` / `GlowSpot.amount` "did not change the next frame"; now and then `test_post_targets_camera` pan (the dot's mapped pixel grey, an edge); all pass alone, in quick and in gate | `tools/video/record_game.record()` sets the framework's framebuffer metrics (`fb_width` / `fb_height` 320 x 180, `pixel_ratio` 2, `view_scale`, the letterbox pads), rebinds the canvas at that pixel ratio and pins its surface by an instance `_create_drawing_surface`, inside a `ProgramRun` world, and nothing gave them back: after `test_record_game` every `SystemWorld` drew at 2x into a 320 x 180 surface (shapes at (200, 150) land at (400, 300), off it). Found by the frame report below ("surface=(320, 180)", design 400 x 300 at ratio 2), after a bisect-free probe had blamed run-to-run order. The pan case runs before `test_record_game`: not this cause, still open | Class: `SystemWorld` gives back the framebuffer metrics (`system_support._FB_METRICS`), the canvas's pixel ratio and the `_create_drawing_surface` hook it found, as it does the design size (WP41); guards `test_prog_isolation.TestWorldGivesBackTheFramebuffer`, `test_record_game.TestSync.test_a_take_leaves_the_framework_as_it_found_it`. Evidence for the rest: `system_support.frame_report(world, *objs)` (camera, design and letterbox, surface, post stack, cover, cull, live and quarantined actors, layers, handles, each object's site, state and cull box, `PYTHONHASHSEED`) is in the failure message of the first two tests; guard `test_sys_frame_contracts.TestFrameReport`. Open: the pan case (add the report to `test_post_targets_camera` if it fails again) |
| WP45 | WP43's gate (load average 55): `test_process.TestAsyncAwait.test_set_watchdog_off_skips_guard` `False is not true : []` (no SCENA ERROR); passed alone at `dev` and `ci` | The guarded half spun 80 ms against a 20 ms budget, but the watcher thread (`process._wd_watch`, polls every 5 ms) only trips once it runs: under that load it woke after the spin ended | The guarded spin lasts up to 5 s; the trip ends it at ~20 ms, so the cost is the same and the margin is no longer one the load can eat |
| WP46 | Gate: `test_game_armada_deep.TestRandomPilots` `ccd.no_tunnel @frame 455 shot path (572.0, 310.0) -> (572.0, 410.0) crossed an enemy` (`vel_tiro` 6000, seed 2355); replays on the release tree, so not the change under test | The oracle tested the shot's path against the enemy's pose now. The enemy was diving (21 px a frame, (546.4, 316.2) -> (564.6, 304.7)) into the place the shot had just left: with both moving, their centres never came closer than 24.3 px (the enemy's radius 20.5, the deep threshold 10.25). The engine was right | `tests/games/armada.py` `_ccd` tests the shot's path relative to each enemy's own motion over the frame (its pose at the last check). The canary `test_swept_detection_off` (`_swept_contacts` planted empty) still fails on `ccd.no_tunnel` alone |
| WP47 | First CI run on Ubuntu (Python 3.12, 3.13, 3.14 alike): `test_example_revoada.test_birds_turn_back_at_the_edges` `-24.18 not greater than -20`; the Mac reads +0.66 for the same seed | Not the engine. The flock is chaotic and Linux's libm rounds differently from the Mac's, so seed 2 flies another path. The turn back is a spring inside `MARGEM`, so a bird in a crowd overshoots the edge before it turns: seeds 1–28 on the Mac reach −46 px (seed 5). The −20 bound fitted one seed on one platform | The bound is 60 px (`OVERSHOOT`), from the seed sweep. A bird that never turns back is thousands of px out in 30 s. Class: a tolerance on a chaotic run is set from a sweep of seeds, not from one seed's value |
| WP48 | First CI run on Ubuntu: `test_frame_probe` died with rc −6, `glfwSetWindowShouldClose: Assertion 'window != NULL' failed`; it passes on macOS and Windows | `scripts/bench/frame_probe.py` ended a timed run with `glfw.set_window_should_close(fw._window, True)`, and the test runs headless (`_window` is `None`). pyGLFW's Linux library is built with asserts on: a NULL window aborts the process, so no `except` catches it. The engine's own GLFW calls run only with a window (nothing in quick reached one headless) | The probe stops the loop itself when there is no window. Guard: the CI's Ubuntu cells run `test_frame_probe` (quick). Rule in [Continuous integration](#continuous-integration) |
| WP49 | Quick, 10 workers: `test_example_affinity.test_a_recipe_switch_does_not_freeze_the_window` `recipe 2 took 1.12 s` (bound 1.0 s); passes alone | WP22's class in an example's test: one frame timed against an absolute bound sized on an idle machine (~0.1 s a switch). The switch is mostly actor creation, and under load the frame stretched past the bound. The bug it guards (a draft that looked for a free spot at random among every atom: seconds a switch, a frozen window) is work, not time | The test counts the example's own lines that a switch runs (`receita` / `elementos_novos` / `mistura` and what they call, through `sys.settrace`; not the world's step) per atom placed: the lattice spends 33–40, a search among every atom 165–640 even when it rarely collides; limit 100. Load-free: 3 s idle, 17 s beside 12 busy processes, same count. Canary `test_the_switch_check_catches_a_random_search` plants the search back (compiled under the example's file name). Class: an example's or a game's test counts work, never reads a clock; guard `test_platform_portability.TestExampleTestsReadNoClock` |
| WP50 | Quick on 0.10.1, every job passed: 686 s wall (717 s the run before), ~6 840 s summed, against the Mac's ~50 s; `test_background` 147 s alone, 100 s of it `TestEmbersDefaultIsVisible.test_defaults_light_the_sky` (two drawn frames) | Not the engine's GPU path: a game draws through GL. With no window, `SystemWorld` draws into a 2000 × 1200 raster surface (WP27), and the machine's skia-python 144.1 wheel is linked by MSVC (a Rich header in the `.pyd`), whose CPU raster pipeline costs ~100 ns a pixel for a plain translucent fill, ~80 ns for a trivial SkSL shader and ~14 µs for `Embers` (9 cells × ~9 `sin` / `exp` a pixel): 34 s a frame. The test does not pin its frame (WP27's rule named post effects only). Python-only modules run near the Mac's speed (`test_vec2_doors` 8–9 s alone, ~7 s) | `scripts/bench/perf_raster.py` (the rows per machine: plain fill, gradient, trivial SkSL, the real `Embers.draw`) and its guard `test_perf_raster` (each case draws pixels). The Mac's rows at 800 × 500 (2026-10-27, skia 144.0.post2): fill 1.4, gradient 0.8, trivial SkSL 1.1 ns a pixel, `Embers` 358 ns (143 ms a frame): the laptop is 40–90× slower on every case. Rule widened: any SkSL on a headless frame pins a small framebuffer. Open: pinning the frame in `TestEmbersDefaultIsVisible`; checking the other slow pixel tests there for the same cause (`test_diff_pipeline.TestPixelOracle` `*_post_on` ~15 s each, `test_prog_bouncing_balls` `test_l3_cull_pixels_a_zoom` ~8 s) |
| WP51 | By ear: `examples/pendulums.py` stutters and clicks at `canvas.framerate = "max"` on the Windows laptop. A probe on the device callback: 267–300 calls in 20 s where 500 are due (40 ms blocks), gaps up to 325 ms; at vsync 37 late calls (that machine fills its vsync budget, ~50 fps) | The mix runs in Python on miniaudio's thread and numpy gives the GIL up inside its calls on a block; each take-back waited the switch interval for a main thread that never sleeps, 15.6 ms on Windows (CPython waits in whole milliseconds; 1 ms was as bad as 5 ms). A block's ~1 ms of CPU took 37 ms of wall at the median, 270 ms at p99, and the device played silence. Headless, beside a busy Python thread: ~2.5 s a block | `Mixer.start_device` lowers the interval to `AUDIO_SWITCH_INTERVAL` (0.5 ms) and `stop_device` restores it ([Sound Design](Sound%20Design.md#mixer)): 505 of 505 calls on time, fps unchanged. Guard `test_audio.TestAudioThreadGil.test_mix_keeps_up_with_a_busy_thread` (13 voices beside a busy thread). As first written it asked for faster than real time, and failed on the Mac (review 2026-10-27): there the 0.5 ms wait is exact, ~120 GIL take-backs a block, ~70 ms (~590 ms at 5 ms), while Windows rounds it to 0. Real games on the Mac were on time at both intervals (`pendulums.py` 501 of 501 callbacks at `"max"`, 153 fps; Ring Guardian the same), so the engine kept 0.5 ms and the guard became a ratio: blocks at CPython's 5 ms and at the device's interval, interleaved, the device's over 3× faster (Mac ~8×, Windows ~350×; 1× with the fix off). Class: work on the audio thread is measured beside a main thread that never sleeps, as a ratio |

### MR — media migration (2026-10-02)

`scripts/examples/` moved to the top-level `examples/`; the gitignored root `media/` and `scripts/examples/media/` were replaced by licensed packs in `examples/media/`; `scripts/smoke/sounds/` (license unknown) was removed. Nothing failed.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| MR1 | ~170 media paths pointed at files that no longer existed (examples, smoke, bench, tutorial, Guia thumbs) | A missing file only warns; no test read the paths | `test_media_refs.TestMediaRefs` |
| MR2 | 30+ media-backed tests (`test_sprite`, `test_atlas`, `test_svg`, `test_level*`, `test_audio`) would have skipped | `if not os.path.isfile(...): self.skipTest(...)` on files that are now tracked | `tests/media_support.media()` asserts; the skips are gone |
| MR3 | `test_scripts_run`, the stamp lint and the AppleDouble count no longer covered the examples | They listed `scripts/examples` / `scripts/` by path | `test_scripts_run` scans `examples/`; `test_stamps` and `run_tiers.SOURCE_DIRS` include it |
| MR4 | A forwarding-stub example (it ran a bench script) raised `FileNotFoundError` | It ran `../bench/perf_resolve_balls.py` relative to its own folder; one level up is now the repo root | `test_scripts_run` (it runs `examples/` again, MR3) |

### DL — docs pointing at private folders (2026-10-06)

The code is about to be published without `proposals/` and `archive/` (bench notes included; [README — Private folders](README.md#private-folders)). Nothing failed: no test read link targets.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| DL1 | ~45 citations of private files in 14 design docs, 6 test docstrings, one code comment and 5 bench pages; 8 already dead (a proposal cited where it was before it moved to the archive, files that never existed) | Docs linked deliberation instead of carrying the reason; `test_doc_citations` checked test names only | `test_doc_links.TestDocLinks` (all citations removed 2026-10-06; a test that read an archived runbook through `os.path.join` and always skipped (the runbook-copy check in `tests/test_win_bench.py`), was deleted) |
| DL2 | (2026-10-26, audit of the published design docs) Two findings still pointed at unpublished evidence in prose: the 2026-10-09 systems review's report and its repros. Seven companions and Scena Design told readers not to open folders a checkout does not have, and the design README's folder map listed them | DL1's scan reads paths (a file inside a private folder) and links; a sentence that names the material without a path, or a folder named alone, passed | `test_doc_links.TestDesignPrivatePointers`: in `design/*.md`, no phrase that calls the evidence private (the pattern `_PRIVATE_POINTER`) and no private folder named at all (agents learn the folders from `CLAUDE.md`). The pointers were replaced by what they pointed at (the RV rows' tests are the repros) or dropped |

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
| TU7 | Adding `heroi.tilt = "ground"` to tutorial 27 (the ninja on the 15° plank) looked like enough, but the ninja keeps the default `hitbox_anchor="center"`: the art leaned about the collider's middle, 44 DU above the feet, so on the slope the feet slid ~11 DU sideways and still floated ~5 DU (the seat applies only with the bottom anchor) | Nothing tied the two: `"ground"` with any other anchor is legal (Collision Design, "Ramps") and runs without a warning, and a tutorial run cannot see where the art is drawn | `test_tutorials.TestGroundLeanHasBottomAnchor`: every tutorial step and `examples/` file that writes `tilt = "ground"` / `AUTO_GROUND` (in a class or on a named sprite) declares `hitbox_anchor="bottom"` or `(0, -1)`; verified to flag the tilt-only version. Fix: both lines, taught together in 22 "A tábua inclinada" (gap after the fix −0.6 DU, inside the resting slop) |
| TU8 | The dying ninja (tutorials 18, 24, 25) played `"morto"` the moment the last life went, in mid air; moved to `on_update` so the ninja falls first, `if on the ground: play("morto", loops=1)` replayed the death every 0.8 s. Tutorial 28's crashed robot already did (`if not st.correndo: play("caindo", loops=1)`) | `play` of the same clip is a no-op only while it runs (Sprite Design, "Clips"); a finished `loops=1` clip starts over. A step run presses no key, so no life is lost and nothing crashes; the Guia said "o mesmo clip de novo não faz nada" without the "while it plays" | `test_tutorials.TestOneShotClipPlaysOnce`: in `update` / `on_update`, a `play(clip, loops=1)` with no `next=` sits under an `if` that asks `showing(clip)` (every step and example; it found 23). `test_example_rules.TestNinjaFallsThenDies` loses the last life in the air and checks the fall, then a still last cell. Both verified on the pre-fix code. Guia and Sprite Design now say it |
| TU9 | A second kunai on a robot already breaking (15, 21, 22) broke it again: the explosion, the clip and a second `after(2, destroy)` | `untag("robo")` stops the hero's rule, not the robot's own `@collide_with("kunai")`; a step run throws no kunai | `test_example_rules.TestNinjaRobotBreaksOnce` (two kunais, one break, every ninja endpoint; verified on the pre-fix code). Fix: `if self.showing("quebrado"): return` at the top of `atingido` |
| TU10 | Ligue 4 (19) named "quatro em linha" and checked rows and columns only: a diagonal four did not win. The diagonal sat in a "Para continuar" box | Nothing played the rule; the runs only drop no ball | `test_example_rules.TestLigue4FourInARow`: every direction wins, and a board where `coluna[-1]` / `[-2]` would make a false four (the diagonal going down without `l < 0`) does not; verified on the pre-fix code |
| TU11 | Found while writing tutorial 25's "Pausa" step (2026-10-22): with only `clock.paused = not clock.paused` in the act, Space still fired during the pause, a shot appearing frozen in the air, and the hero's keys were still read | `clock.paused` makes `dt` 0 but keeps calling every `on_update` (Guia, `clock.paused`); a step run presses no key | `test_example_rules.TestNavesPause`: P freezes the fleet and Space fires nothing, P resumes, R during the pause starts the next act unpaused. Fix in the tutorial: `if clock.paused: return` at the top of the hero's `on_update` |

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
| CS4 | `st.pos.x = 5` (`st.pos` holding a Vec2) stored `x` on the cell: reads returned 5, the payload stayed `Vec2(1, 2)`, links never updated | `Attribute.__getattr__` falls through to the instance `__dict__` before the payload, and the cell had no `__setattr__` | `TestEngineValueRegressions.test_cell_object_payload_write_raises_with_the_fix` (the cell object: `cell.x = 5`). Fix: `Attribute._closed_hint`. Since 0.8.0 `st.pos` is the Vec2 itself; the guard moved to the held Vec2 (SV3), and since 2026-10-19 `st.pos.x = 5` writes into it and tells the cell (SV12) |
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
| PM4 | `isinstance(st.n_bolas, int)` was False: `st.n` reads the cell. The Guia said both "`st.score` lê o valor" and "`st.key` Lê o Attribute" | SPEC-GAP / DOC-AMBIG (spec A of `cadeia_de_bolas` trusted the first row) | Guia: `st.score` reads the cell, which does arithmetic like its value; `st.score.value` is the plain value (for `isinstance` / `type` / a copy) Superseded by SV1 (0.8.0): `st.n` reads the value |
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
| PM17 | (2026-10-15) The gate's `test_program_coverage` failed on `Concave`: the export landed (b66da20) with unit tests only, and the guard is `SLOW`, so `quick` never saw it | A new export with no program; the session ran `quick`, not `gate` | `bouncing_balls` gained a quarter-pipe in each corner (group `"corner"`, STATIC, `resolve(bounce=1)`); both spec authors extended their specs from the docs (spec a E35–E47, spec b E34–E44: membership, reads, named points, `contains_point` on the exact arc, no ball inside the solid, speed kept, bounce normal and contact at the drawn curve). No divergence. Canary `test_specs_catch_a_concave_colliding_as_one_hull` (CV1's shape: both specs fail). Gaps both authors reported (`.scoop` read-back, `contains_point` on the curve, which side of the curve the chords lie on): the Guia's Concave row now states them; the chord side is pinned by `test_concave.test_the_chords_cut_into_the_scoop_not_the_solid`. Rule: a new export ships with a program that uses it (or a `PROGRAM_EXCLUDED` reason), checked with `focused test_program_coverage` |
| PM17 | `Handle.velocity` keeps the last frame's value after the motion ends (by design: `on_done` reads the arrival speed); the Guia said only "neste frame" | SPEC-GAP / DOC-SILENT (found by `test_sys_frame_contracts`) | Guia `Handle.velocity` row |
| PM18 | `canvas.background = canvas.background` raised TypeError: the read is the live stack, a write expected a material for the base. Found writing `test_noop_cost` (every world setting written back) | BUG / read and write of one name did not round-trip | Writing the stack itself keeps it; the Guia says to keep `.base` to restore later. Guards: `test_background.TestBackgroundRoundTrip`, `test_noop_cost` (no special case) |
| PM19 | `#util-approach` left open, for both `snake_chain` spec authors (farejador, 2026-10-13): what happens at a gap of exactly one step ("menos que um passo" vs the code's `<=`), whether `move_to(pos)` stores the centre bit-exactly (the `==` promise on arrival rests on it), and whether omitted `dt` is the `dt` that `update(dt)` receives. No expectation diverged. Settling it surfaced that `Point == (x, y)` is always False (identity `__eq__`), so `elevador.center == PARADA` never fires | SPEC-GAP / DOC-SILENT (both authors) | Guia: "um passo ou menos", `move_to(pos)` lands exactly, compare the returned value (a Point never equals a tuple), omitted `dt` = `update`'s `dt`. Guard: `test_easing.TestApproach.test_move_to_lands_the_center_bit_exactly`. Point equality left for a separate decision |

### FC — formula source from memory (2026-10-21)

Found while adding `collision.floor = True` above the Guia's
"Tocando" snippet: `validate_guia` (which runs snippets from memory, the text
registered in `linecache`) refused `player["grounded"] @= lambda: "bottom" in
player.touching_sides` once it was no longer the first line. The same code in a
`.py` file linked.

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| FC1 | A formula run from memory (`exec` of registered text, a notebook cell, IDLE, the Guia validator) below its text's first line raised `CircularReferenceError` "cannot read that object's own size", even reading only a custom field (`r["d"] @= lambda: r.hp * 10`) | `exec(compile(src, "<snippet>", "exec"))` with `src` in `linecache`, the formula on line 2+ | No file to parse, so `_locate_uncached` parsed `inspect.getsource(fn)` alone: the lambda sat on line 1 of that snippet but was looked up on `co_firstlineno` → no node → the sourceless fallback took the whole object as a source, and a whole object reading itself is the own-size cycle. A second fault hid the fix from a naive repro: `_NODE_CACHE` was keyed by the code object, and code objects compare equal across files (CPython leaves `co_filename` out of `==`), so a sourceless run's `None` stood in for an identical lambda with source | `formula_check._memory_tree` parses the whole text from `linecache` (with the module's loader, so zipped modules count); the getsource snippet is shifted to its real line and its first line's columns; the node cache keys on `(co_filename, code)`; a refusal that remains without source says the source is missing, not a size read. Guard: `test_formula_functions.TestInMemorySource` (lambda and `def` below line 1, two names, the cache across files, the snippet fallback's line and columns) |

Why earlier tests missed it: source availability was tested as on/off (a
file, or `exec` with no text at all, PM14's row); "text available, no file" is
a third case, the one notebooks and the Guia validator live in, and every
existing `exec` test put its formula on line 1 or had no text registered.

### SU — seam lips (2026-10-11)

Found by an author: in `examples/ninja_perigos.py` a platform of three tiles,
rotated 15° by hand, dropped the ninja into its third tile. Measured headless
with the real hulls (tile 3 starts 0.34 DU above tile 2), then swept over flat
rows: any lip above the resting skin was a failure. Fixed by the seam step
([Collision Design — Seam lips](Collision%20Design.md#seam-lips-step-up)).

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| SU1 | One-way row (`only="bottom"` or a function): the walker fell into the next tile at a seam whose top was a hair higher | Three 80 DU tiles, the third 0.34 DU higher (or the ninja hulls at 15°), walker 38 × 70 at 250 DU/s: at the seam a pass starts, the walker rides tile 2's corner flat, then drops into tile 3 | The walker rests `_RESOLVE_SLOP` (0.08) above its floor, so its leading corner meets the next tile's side face; the sweep's normal is horizontal, `only=` rejects it, and a rejected hit before any accepted one starts a pass (S1) | `tests/test_seam_step.py` (`TestFlatLips`, `TestRotatedRows`) |
| SU2 | Solid row: the walker stopped dead at a seam lip of 0.1 DU | Same row, `resolve(..., bounce=0)` without `only=`: `"right"` in `touching_sides`, `vel.x` zeroed every frame | Same side-face contact; a solid pair stops on it | `TestFlatLips`, `TestTallLip` (a lip above `_SEAM_STEP` still stops) |
| SU3 | The one-way threshold depended on the frame rate: a 0.05 DU lip held at 60 Hz and dropped at 144 Hz | Flat row, lip 0.05, 144 Hz | Whether the floor hit precedes the side hit in a slide depends on that frame's fall (g·dt²) | Every case runs at 30 / 60 / 144 / 240 Hz and 5 / 28 ms |

Why earlier tests missed it: `TestTileSeams` and the resting-contact walks used
exactly aligned tiles, the one geometry an author rarely produces. The new
module puts the lips in the input space (flat 0.1–1.9, rotated rows with random
seams) and checks that `_SEAM_STEP = 0` brings the bug back.

Two test-design traps found on the way (not engine bugs): a lip measured across
a rotated row is a rise of `d / cos(angle)` (the step is vertical), and a walker
that reverses on a slope keeps the slope's rise in `vel.y` and launches — the
tests turn around from rest.

### MS — mass split in the sweep (2026-10-13)

Found writing `examples/entropia.py`: walls of mass 50 held by a spring and
moved by `move_by` gained energy from ball hits, and balls leaked through the
corners. Fixed by the mass split ([Collision Design — Mass split between two
movable bodies](Collision%20Design.md#mass-split-between-two-movable-bodies)).

| ID | Bug | Repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| MS1 | Between two non-`STATIC` bodies the position outcome depended on enrollment order: a crate pushed at full player speed (crate first, even at mass 50) or never (player first); a mass-1 floor sank 457 DU in 1 s under a falling rider (floor first) or held (rider first); a spring-held wall gained 45 % energy in 10 s (wall first) | Two bodies enrolled in each order (`collidable = True` sets `_collider_index`), the same `move_by` script | The body swept first stopped and absorbed the whole approach; settle and `velocity_split` weighed the masses, the sweep's conversion did not | `test_collision.TestSweepMassSplit`: each case in both orders must agree; a canary turns `_SWEEP_MASS_SPLIT` off and sees the energy gain |

Why earlier tests missed it: every resolve test of a moving partner used a
`STATIC` one (elevators, walls), or one creation order. The order of creation
is an input: a test of two movable bodies runs both.

A trap found on the way: the first version pushed the partner without a
sweep, and a light ball shoved toward a 2 DU wall was placed past it (the
pusher followed). `_push_reach` sweeps the share against the partner's
`STATIC` partners; `test_push_into_a_thin_wall_stops_at_it` fails without it.

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
| AC14 | An own custom field cannot read its object's size fields or computed points (`r["d"] @= lambda: r.width`, `c.radius`, `r.top_left`, a Polygon's `center`): `CircularReferenceError` saying the field "would read the Rect, which already reads d", a cycle the author never wrote. Fails on the earlier code too | `test_subclass_parity` (an own field reading a part on every family), then a survey | A scalar-slot read names the whole object as the source; a Derivate part depends on the root, and the root on every child, the new field included | Own-field formulas in tests read ink fields or placement points | Decided (2026-10-10): a documented limitation. `_own_size_read_message` names it and the idiom (a class `@property`, or `update(dt)`); a real cycle keeps the generic message. Guia: reactive sources. Guards: `test_fieldref.TestOwnSizeReadIsAKnownLimit`; `test_subclass_parity.KNOWN_SELF_READ` (fails if it ever starts working). Showcase B5 (2026-10-23): a part owner (`t["center"]`) and a built-in field (`p["radius"]`) now get the limit too, with "read one part, or update(dt)" instead of the property idiom |
| AC15 | Class keywords across families: `class Hud(Text, group="hud")` (and the six widgets, `Entity`, `Endless`) raised Python's "takes no keyword arguments"; `class Rota(Track, color="gold", group="rotas")` was accepted and both were dropped | `test_subclass_parity` on its first run | Only Shape, Sprite (and now SpatialFx) consume class keywords; `Entity.__init_subclass__` passed the rest to `object`. `Track.__init__` never read `_shape_defaults` | Each family's tests asked about its own way | `Entity._refuse_class_keywords`: an author error naming the fix ("pass them when you make one"), passing through to an author mixin's `__init_subclass__`; `Track.__init__` applies `color` / `visual` / `group` defaults. Then decided (2026-10-10): Text takes class keywords (the look), through `scena/class_defaults.py` shared with SpatialFx; the widgets, `Entity` and `Endless` keep the error. Guards: `test_subclass_parity`, `test_text.TestClassKeywords` |
| AC16 | `anchor.draggable = False` / `handle = False` were accepted and ignored (documented only in a docstring); a link on any Anchor field was refused with "set draggable = False first", which an Anchor cannot do | `test_subclass_parity` (an own-field link on every family) | The Anchor overrode the setters as no-ops; the generic driver-conflict message assumed a switchable drag | — | Decided (2026-10-10): raise, naming `Point(x, y, visible=True)`; the Anchor's own link refusal says it takes no links. Engine writes that follow a drag callback go through `_draggable_from_callbacks` (an Anchor keeps its handle). Guard: `test_shape_interaction.TestAnchorInteraction.test_always_draggable_on_top` |
| HV1 | Harness vacuity: every `ProgramRun` draw painted a surface nobody read (a program's `init()` rebuilt the canvas), so `cull_pixels` compared two blank frames for every program | `run.step(1, draw=True)` then read `run.world.surface` → one flat colour | The framework's drawing canvas was re-created by `init()`; the run kept reading the world's | The oracle compared two images and never asked whether either showed anything | `ProgramRun._wire_surface()` before each draw; `cull_pixels` refuses a flat frame. Guard: `test_program_support.TestDrawReachesThePixels` |
| AC4 | The Guia's `ready` row promised "at most once per interval"; the engine carries the overshoot (Scena Design, "Clocks"), so two calls can be closer than the interval when it is not a whole number of frames (`clock.scale = 0.8`: 0.1467 s apart for 0.15) | Armada's cadence model under `clock.scale` | Engine right by design; the sentence over-promised | — | Guia `ready` row: exact on average, the leftover carried, so two `True` can come a little closer than the interval |

Two harness notes from the same work: a Tier C run copies data files next to
the program (a level `.json`) into its temporary folder; a value `Box` (read
through `Grid.cell_at`) can still be alive at the census by GC timing, so
`ProgramRun.close()` discounts Box values in the graph counters as it already
did in `registry.live`.

### SV — State reads the value (2026-10-10)

Reported by the maintainer: `if st.mic is None:` was silently always False. Root of the class: the dot read returned the cell (`Attribute`), which emulated its value through dunders, and Python compares by identity and by type without asking the object. Decision and alternatives: [Reactive Design — State bag](Reactive%20Design.md#state-bag). Guard for the class: `tests/test_state_reads_value.py` (fails 48 ways with the old read).

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| SV1 | `st.mic is None`, `st.alvo is c` and `match st.x: case None` never matched; `type(st.n)` / `isinstance(st.n, int)` named the cell; `best = st.score` and `history.append(st.score)` followed later writes; a cell could not be a dict key. An ink field (`ship.hp`) read the value, so the two disagreed | `State.__getattr__` returned the `Attribute` | `TestDotReadIsTheValue` (every payload kind in every bag reads back as itself and matches an ink field). Fix (breaking, 0.8.0): the dot read is the value; `st["x"]` is the cell |
| SV2 | After the flip, three old spellings would have changed meaning silently: `Text(st.score)` a snapshot, `Menu(st.nave)` with `nave` still `None` an unbound menu, `@on_change(st.pos)` (a Vec2) a watch that never fires | A binding site cannot tell a value from "no cell" | `TestBindingSitesTakeTheCell` (each site refuses the value naming `st["…"]`; completeness check over public classes whose first parameter is a data `cell`). Fix: `Text(<number>)` raises, a widget's explicit `None` raises (`_NO_CELL` default), `@on_change(<free Vec2>)` raises |
| SV3 | (caught in review, before release) `st.pos += Vec2(1, 0)` left links on `st["pos"]` stale; `st.items += [x]` too; `st.pos.x = 5` mutated the payload silently (CS4 came back) | `+=` on the held object mutates it in place and assigns the same object back, and `_takein` sees no change | `TestInPlaceChanges`. Fix: `State.__setattr__` sends a same-object non-value write to `Attribute._changed_in_place()`; the held Vec2 gets a per-instance `_write_field` guard (`_HeldPayloadWrite`) |
| SV4 | (caught by the A/B, before release) The same-object check cost +1.6–2.6 % on every `st.x = …` write | One more `__dict__.get` on the write path | Interleaved A/B (16 rounds). Fix: read `cell._raw_value` directly and call `cell._assign_value` (skips the closed-surface `__setattr__` and the property): writes −5 to −10 %, used reads −50 % |
| SV5 | (caught by the gate on landing, 2026-10-11) `test_cells_as_numbers` stopped passing cells: its `_cell` helper returned `getattr(st, name)`, now the number, so every "cell" case compared a number with itself. The canary (a helper refusing cells) was no longer caught | A test that obtains a cell through the dot read; the session that made the change ran `quick`, which skips canaries | `_cell` returns the bag's `Attribute` (`bound_cell(st[name])`): `st[name]` is a FieldRef, a handle that binds and is not a number (passing it made all 54 cases raise). Canary: `TestCellsCanary`. Rule: after a change to what a spelling *means*, run `gate`: canaries and Tier C oracles catch tests that turned vacuous, `quick` does not |
| SV6 | (same gate) Tier C `rename_groups` on `cadeia_de_bolas`: "st has no cell 'linhas_r'". `"linhas"` is a group and an `st` cell; `CheckBox(st["linhas"])` made the cell name a string, and the oracle renamed every whole string | A source transform that renames string literals did not tell a group key from a cell or field key | `program_oracles._RenameStrings`: a subscript key is renamed only on the namespace itself (`group[...]`, `….layers[...]`). `test_program_support.TestTierC.test_a_rename_leaves_cell_and_field_keys_alone` |
| SV7 | (same gate) `test_program_coverage`: `Attribute` reached by no program. It had counted only because `st.x + 1` called `Attribute.__add__` | Coverage by side effect of the old dot read | `Attribute` in `PROGRAM_EXCLUDED` with the reason (programs pass `st["x"]`; members: `test_state_reads_value`) |
| SV8 | (reported by the maintainer, 2026-10-13) A bracket handle used as a value was silent: `Text(lambda: f"Pontos: {st['score']}")` showed `<field …['score']>`, `if st["vivo"]:` was always true, `@when(lambda: st["score"] == 5)` never fired; `st["score"] * 2` raised Python's bare "unsupported operand" | `FieldRef` inherited `object`'s `__str__` / `__bool__` / `__eq__`; the formula reader accepted `st["score"]` as a source; events unwrapped a returned handle | `tests/test_handle_not_value.py`: every value protocol × three handle kinds, a completeness check (every number / text protocol of `float` / `str` is on `FieldRef`), formulas (lambda, `def`, helper, constructor), event lambdas. Fix: link-time refusal in `formula_check`, registration refusal in `events`, raising dunders on `FieldRef` ([Reactive Design — The handle is not the value](Reactive%20Design.md#the-handle-is-not-the-value)) |
| SV9 | (same report) `Text(st["score"])` then `placar.text = "oi"` wrote `st.score = "oi"`; `st.score + 1` raised far from the write | `Text` stored the cell itself as its `text` part (an identity bind, like a widget's) | `test_text.TestTextCell.test_cell_text_links_one_way`, `test_handle_not_value.TestTextCellIsOneWay`. Fix: a DirectLink; the `LinkedAttributeError` names the cell (`_follows_cell_hint`) |
| SV10 | (found 2026-10-16, while weighing live arithmetic results) `mira = Circle(center=lambda: nave.center + nave.desvio)`: a new `nave.desvio` (`=`, `*=`) never moved `mira`, and a vector from arithmetic (`a + b`, `vec_from_angle`, `Vec2.temp`) in the field was never followed (`<<`, `+=`, `.x =` all silent); `nave.itens += [x]` silent; `st.pos << v`, `st.pos.do_rotation(a)` and `p = st.pos; p += v` silent | The source extractor took the object an ink field held at link time, not the field (an ephemeral vector is never on the graph); the same object assigned back is "no change"; a cell heard only the write that assigns back | `tests/test_ink_held_payload.py` (payload kind × in-place spelling × holder: ink formula, ink DirectLink, st cell; a flush callback; length / angle after each; a completeness check over Vec2's in-place methods and operators; fails 67 ways before). Fix: `_ink_field_source` (the field's anchor is the source), `_HeldPayloadUpdate` (a held Vec2's per-instance `update`), the ink `old is value` branch |
| SV11 | (found 2026-10-17, while closing SV10) `nave.alvo = a; r = Circle(radius=lambda: nave.alvo.radius * 2)`: after `nave.alvo = b`, `b.radius = 7` was not heard and `a.radius` still was; `lambda: st.alvo.radius` never heard `st.alvo.radius = 7`; a replaced mic (`g.mic = other`) left the formula on the old level | Sources were learned once, at link: the chain followed the object of link time, and an st chain stopped at the cell | `tests/test_formula_follows_holder.py` (holder: ink, st × read: size, ink field, point, `[0]`, holder in holder × write: new object, its change, old object's change, back, same again, unlink; None and back; value hops never re-learn; the cycle; a destroyed old object), `test_audio_level_source.test_a_replaced_mic_is_followed`. Fix: hops recorded at link, `_HolderFormulaLink.evaluate` probes them, `_follow_holders` re-learns with the link-time parse |
| SV12 | (found 2026-10-19, while lifting the CS4 refusal on `st.pos.x = 5`) A cell with a formula (`st["pos"] @= f`) took `st.pos << v`, `+=`, `-=`, `*=`, `/=` and `do_rotation` silently: the formula's output changed, nothing linked heard it, the next pull put it back; only `.x =` refused, with the unlinked cell's "assign a whole value" message | The held-payload guard covered `_write_field` only, and checked "held", not "linked"; the other spellings check the vector's own links (`_refuse_author_write`), and a cell's link is on the cell | `test_ink_held_payload.TestLinkedCellRefusesInPlace` (every in-place spelling of the matrix on a linked cell: `LinkedAttributeError`, value unchanged), `TestCellVec2InPlace` (every spelling × payload kind on an unlinked cell reaches a formula, a direct link and a watcher). Fix: `_HeldPayloadWrite` refuses only while the cell is linked, and is also the payload's `_refuse_author_write`; `Vec2._takein` asks it for `<<` |

### RA — 0.8.0 release audit (2026-10-11)

Before tagging 0.8.0, read-only agents checked every CHANGELOG entry against the
code (a probe at HEAD and at v0.7.1), the Guia, the tutorials and the design
docs. All tiers had passed: every finding below is a claim no test made. Lesson
for the class: **a CHANGELOG or Guia sentence of the form "the old spelling
raises" / "X now follows" is a test to write, not a summary to trust.** Each
door the sentence names gets a case, and every payload kind the door can take
(a number, a text, a `Vec2`, an object) gets one too: the SV2 guards covered
numbers, and the `Vec2` (a Container) walked through four doors.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| RA1 | With a `Vec2` cell, `st.pos @= …`, `c["center"] @= st.pos`, `tween(st.pos, …)` and `until(st.pos)` were accepted: each took the held Vec2 and went stale at the next `st.pos = …` (the tween moved it inside a batch, past the in-place guard). The CHANGELOG said the old spelling raises | A Vec2 is a Container, and each door accepts a Container | `TestHeldVec2IsNotTheCell` (every door × the bracket spelling; a named bag). Fix: `state.refuse_held_payload` / `held_cell` in `Container.__imatmul__`, `_normalize_link_rhs`, `tween`, `_start_until` |
| RA2 | A formula on `st.mic.level` (a mic kept in a State cell) linked and stayed at 0 while the level moved, the case the 0.8.0 CHANGELOG used as its example; `g.mic.level` with `g.mic` still `None` raised Python's bare `'NoneType' object has no attribute 'level'`, and Sound Design said the guarded form linked | `_extract_sources` stops a State chain at the cell, so the off-graph level source was never asked | `test_audio_level_source`: `test_a_mic_held_in_a_state_cell_follows` (fails without the fix), `test_a_mic_not_opened_yet_names_the_read_and_the_fix`, `test_on_change_hears_the_level` |
| RA3 | `st.v0 = ball.vel`, then `ball.vel = Vec2(3, 3)`, raised "st.v0.x = … would change the Vec2 that st.v0 holds" (the vel setter writes into the existing Vec2); a `confine(action="bounce")` write would too | The cell kept the object's own Vec2 and the SV3 guard went onto it | `TestCellCopiesAnObjectsVec2`. Fix: a cell copies an owned Vec2 (`_takein_impl`, inside the Vec2 branch: other writes pay nothing) |
| RA4 | `if canvas.effects:` was True during a `shake` with no author effect, while `len()` was 0 (AC3 fixed `__iter__` / `__len__` only) | `PostFxStack.__bool__` returned `_is_active`, which counts the internal `_hit` | `test_postfx.test_truth_agrees_with_len_during_an_impact` |
| RA6 | Two weak points of one `Collider` (`torso.collidable`, `head.collidable`, `Collider([torso, head])`) collided with each other every frame; `query_sector` (a wedge, or `spread=0`) still answered by statement order while Collision Design and the Guia said every query puts the body first | AC10's `kin` set held body ↔ own piece only; `_prim_hits` / `_segment_hits` returned identities in candidate order | `TestPieceThatIsAlsoABody.test_two_weak_points_of_one_body_never_touch`, `test_queries_name_the_body_first_in_either_order` (sector cases); both fail without the fix |
| RA5 | Docs drift: tutorial 07 said `st.vidas` and `st["vidas"]` are the same thing; Guia rows promised errors that did not happen (`@=` on a number, `@on_change(c.radius)` "never sees a change" — it raises), named `ready` "at most once per N seconds", said every visual takes the object's colour (`Metal()` is chrome); the CHANGELOG named `.tile_mode` (it is `.source.tile_mode`) and missed `query_circle` / `query_shape` order, `until(<field>)`, `Text(True)`, and the `contain` band fill; 21 Guia thumbnails were stale | Prose changed in one place and not in the others | Fixed in the docs; `make_guia_thumbs.py --check` before a release (the release checklist in Scena Design) |

### RA2 — 0.9.0 release audit (2026-10-21)

Same method as RA: nine read-only agents checked every 0.9.0 CHANGELOG bullet
against the code, a probe at HEAD and at v0.8.1, the tests, the Guia and the design
docs; one swept the author material for old spellings (none found; every "the old
spelling raises" of Breaking held). About 75 findings: a dozen engine bugs, the rest
CHANGELOG sections, quotes and numbers, doc drift and missing tests. Before the audit,
the `### Added` heading had been lost (901d2b0), so about 25 additions read as
Breaking. Lessons for the class, beyond RA's:

- **A "before" claim needs a probe at the last tag, not at the commit before the fix.**
  Three Fixed entries described bugs born and fixed inside the cycle (an LW8
  regression, an ink-field Vec2 link, a dead-vel order); several numbers compared
  intermediate commits (a colour write "+5 %", `st.pos += v` "40 %" that is 4× against
  0.8.1).
- **A message's fix must itself work.** The worst finds were messages that named a fix
  which fails: `if vel:` after a destroy (a part stays truthy), `+= [x]` for a dict,
  `run_task(flash)` in a method, `text.flip_x = …` for a Text, `concave.rim @= …` for
  a computed corner. Guards now evaluate the fix the message names.
- **A new door inherits the old door's refusals only if a guard enumerates it.** The
  appearance links reached `_assign_formula`, which took a plain number as a one-time
  write; `angle` and `scale` had the same hole before 0.9.0.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| A2 | `x["visible"] @= box.checked` (any plain number / bool on `visible`, `alpha`, flips, `angle`, `scale`, `line_width`) copied once and linked nothing | `Container._assign_formula` took a Number as `_takein` | `test_paint_flag_links.TestPlainValueRefuses` (every kind × linked field × constant, cell value, bool, int) |
| G5 | A linked cell holding a formula-made `Point` accepted `<<`, `.x =`, `move_by` silently | the held-payload guard covered Vec2 only | `test_ink_held_payload.TestLinkedCellRefusesInPlacePoint` (every Point mover; a completeness check) |
| G2 | A write through a destroyed actor's part said `Vec2.x … if vel:` | `_refuse_if_destroyed` named the receiver | `test_vec2_inplace_guards.TestADeadPartNamesItsOwner` (the named guard is falsy; the named field reads that part) |
| A1 | 0.8.1 cell spellings (`@on_change(t.text)`, `until(box.checked)`, `x["text"] @= t.text`) got generic messages naming `TextValue` | the doors saw a value, not the moved cell | `test_text.TestMovedCellDoors` |
| C1 | Computed-field refusals suggested an input that does not move the field (`concave.rim`, `center` for `rect.vec`) | `_model_inputs` listed every model input | `test_concave.TestComputedFieldRefusalNamesAnInput` (writing the suggested input moves the field) |
| B2 / B5 / B7 / B6m | Fixes that fail: `+= [x]` for a dict / set, `run_task(flash)` in a method, `text.flip_x =`, `Circle['color']` as a variable | one hint text for every case | `test_formula_functions.TestContainerItemLinks`, `test_async_hooks.TestNeverAwaitedHook`, `test_paint_flag_links.TestFlagRefusalNamesAWorkingFix`, `test_process.TestTweenRefusesALinkOnlyField` |
| D2 | Quick effects, `flash_text`, `canvas.fade_out`, `mic.record` took an `on_done` that needs arguments and crashed when it fired | they call through `call_truncated`, outside the refusal | `test_async_hooks.TestEveryLaterDoorRefusesAnOverfullCallback` (every `(on_done)` door in CASES) |
| D3 / D4 / D5 | A class attribute opened `obj.position = …`; `self.mode = self.phase2()` passed for a plain method; the other-engine hook warning pointed into scena | class body unchecked; the check knew `@on_mode` only; `stacklevel` | `test_read_hints` (class values, plain-method mode), `test_class_hook_names` (filename and line) |
| A3 / A7 | `isinstance(x, EquilateralTriangle)` silently False; `tri.n = 5`, `sprite.model = …` accepted and ignored | the stub raised only when called; no route for `n` / `model` | `test_triangle.TestRetiredName` (every retired class × call, subclass, isinstance), `TestNIsNotAField`, `test_sprite.TestNoGeometryModel` |
| F12 | `heading()` / `Line.angle` read −180 (and −0.0) where `Vec2.angle` reads 180 | three normalisations | `test_vec2_algebra.TestHeadingReadersAgree` |
| B1 | The frozen-frame watch was armed only by the script's `init()` | armed in `init` only | `test_stall` (armed by `run()`, not by a test module) |

Decided with the maintainer: `x.position =`, `v * True`, `st.pos["x"] @=` and the
short-property typo rule are Breaking; `Color == "red"` is Fixed, with a static
warning for a colour looked up in a set or dict of names (`color.warn_color_keys`).
Open after the audit, fixed after 0.9.0 (`tests/test_held_value_doors.py`,
`test_hitbox_parts.TestFlatHitboxNamesOnShapes`): `tween` on an axis of a linked
cell's vector (or on its Point) started and then raised from the frame loop; `copy.copy`
of a held vector kept the cell's hooks, and any Scena object's copy shared its graph
node; `st.pos += …` on a held Point, `s.mira.x = …` on a linked ink Vec2 and `v <<
dead.vel` named the wrong subject; `hitbox_scale` on a Rect became ink. Two lessons:
a door that writes later (a tween, a timer) must ask at the call the guard its first
tick will meet, or the refusal reaches the author from the frame loop; and a class
that installs per-instance hooks owns what `copy` does with them (Python's default
copies `__dict__`, hooks and node id included). The two design questions, decided
by the maintainer (2026-10-22): an undrawn `Entity()` with no variable was collected unless
an async mode or a timer held it — it now lives until its destroy or its act's end
(Laws L1); `obj["field"] @= f` on a Vec2 ink field refused — it now links the
vector, as `obj.field @= f` does.

The 0.9.0 gate's one failure under load (oficina random pilots, `LEFTOVERS
{registry.live: (8, 2), graph.nodes: (5, 3), …}`, passing idle) was the stall
watch, not the engine's lifetime: under load every run's `SINO.bake(…)` passed the
8 s top-level watch, and `stall._watch` kept the main thread's frame it reported in
its locals until the next stall. The frame's globals were the run's namespace, so the
finished run's `TABULEIRO = Box(…)` and its six named Points stayed alive into the
next run's census and were freed during it (the counts went **down**). Reproduced at
idle with `TOP_LEVEL_STALL_S = 0.05` (the same diff, every run after the first); fixed
by building the report in `stall._report`, so the frame lives only in that call.
Guard: `test_stall.TestStallWatch.test_a_report_keeps_nothing_of_the_program_alive`
(both phases; canary: a report that keeps the frame). Lessons: a thread that reads
another thread's frames (`sys._current_frames()`) holds them, and all they reach,
while a local names them; and a census that goes down is something the run before
left alive, so look at what holds the earlier run, not at the run that failed.

### RA3 — 0.10.0 release audit (2026-10-24)

Same method as RA and RA2: four read-only agents, one per slice of the 0.10.0
CHANGELOG (Breaking + Added, Fixed in two halves, Documentation), each probing
the "before" claim at v0.9.1 (a detached checkout) and the "after" one on the
release branch, and running each named test against the v0.9.1 engine to see
it fail. Every bullet described a bug or a feature that v0.9.1 really had or
lacked (none born inside the cycle, none listed twice with 0.9.1). Findings:

| ID | Finding | Fix / guard |
| --- | --- | --- |
| RA3-1 | A destroyed shape's `move_along` on an anchored track snapped it to the track's start, and a destroyed Point raised there (the DV3 fix skipped the probe, not the start snap) | `timed_move_along` returns the cancelled Handle before the ride or snap; `test_dead_verb_order` adds anchored tracks (time and speed) and checks the dead do not move |
| RA3-2 | `copy.copy(st)` / `copy.deepcopy(st)` ended in `RecursionError` (`State` is no Container, so the copy refusal did not reach it); the CHANGELOG said "every other Scena object refuses" | `State.__copy__` / `__deepcopy__` refuse naming the value copy (`test_held_value_doors…test_a_state_bag_refuses_and_names_the_value_copy`); the bullet names the objects of the world |
| RA3-3 | Gradient resize: the "same paint" assertion had been dropped, and an `id()` set of freed paints would have passed anyway (Python reuses the id) | `test_gradient.TestGradientFit.test_a_growing_shape_keeps_one_paint` holds the paints; fails at v0.9.1 (30 paints) |
| RA3-4 | Lamp / Spotlight lengths: only `_length_to_fb` was tested, so a lamp back on raw pixels passed; the post effects' mouse default (fixed with the targets) had no test | `test_post_targets_camera`: the uniforms a draw sets are the mapped lengths (zoom 2, post image ×1 and ×0.5); the mouse default maps like a target under every camera |
| RA3-5 | CHANGELOG claims: Lamp "divide by more at a low `post_fx_scale`" (it is less: pixel ratio × `post_fx_scale`); "a History filling slowly" warned (it did not at v0.9.1; the test guards nothing there); "five" CC-BY tracks (four); the showcases' speed "about `revoada.py`" (never measured); the Guia cards line under Fixed (moved to Documentation); `hitbox_from` and `local_at` missing from lists; the music move and the new font unlisted | CHANGELOG reworded |
| RA3-6 | Doc drift: the Guia's `cull_offscreen` row and Effect System Design said parallax layers are never culled (they are, against their own view, since the showcase fixes); Canvas Design said keep culling off (on since 2026-10-12); Effect System Design spelled `"project"` caps; the Guia had no word on `ship["aim"] @=` on a Vec2 field | Guia (pt and en, parity marked) and design docs updated |
| RA3-7 | Two `line_cap="project"` doors (`set_defaults`, `Contrail`) and a string written before `super().__init__()` raised / linked but had no test | `test_showcase_messages.TestLineCapNames.test_project_raises_at_the_other_doors`, `test_fx_knobs.TestBracketOnPlainValue.test_a_string_written_before_super_init_links` |

Left as they are: `@e.every` on an object at the top of a file is told to
write `@self.every(1.5)` (the fix it names, parentheses, is right); the
Polygon-angle and per-frame colour speedups are sourced in Shapes Design and
SH-D4 but have no failing-without-fix guard (a timing, not a behaviour).
Lesson for the class, beyond RA2's: **a fix for one door of a rule leaves the
rule's other doors** (DV3 fixed the probe; the start snap of an anchored ride
was a second write on the dead), and **an identity test over objects nobody
holds proves nothing** (`id()` of a freed object is reused).

The release gate then failed once, under load ~25 (a peer's six-hour unittest
run beside it): law E1 on `string_theory.py` saw the 30 Hz twin make three
Lines fewer at 3.5 s. Mechanism: the freeze watchdog's wall-clock budget for
one async step (`WATCHDOG_RESUME_S`, 0.5 s) cut the 160-line build (~0.1 s
idle) mid-loop in one twin (confirmed: the child run with a 0.01 s budget
built 26 Lines of 160). The example's own test already lifted the budget;
the harnesses did not. Fix, in both harnesses that play a program frame by
frame: `ProgramRun` lifts the default budget to 5 s for its run and gives it
back (a test that sets its own keeps it), and `tests/script_harness.py`, the
child process the laws' example scripts run in (E1, E3, E15), lifts it too.
The first fix was the `ProgramRun` half alone, and the next gate failed the
same way: the example scripts never go through `ProgramRun`. Guards:
`test_program_support…test_the_freeze_budget_is_no_wall_clock_in_a_run`,
`…test_a_harness_run_lifts_the_freeze_budget_too`. Same rule as the gate's
job sizes: **a frame-stepped test's outcome is a count, never a wall-clock
time**; and a fix for "the harness" names which harness ran the failing job.

The deep tier then failed the chaos idle twin of `platformer` (spec b,
`shoot`): about one run in three, the program and its idle-rewrite twin
disagreed on a ball's contact with the floor, a frame apart; v0.9.1 never did
(bisect: aeb75fa, which only changed the memory layout). Mechanism, traced
through the recorder's motion events: two dissolves ended in the same tick
(a ball's and a "tchau" sprite's) and `tick_all_transients` walked
`_active_shapes`, a `weakref.WeakSet`, in address order, so their
`on_done=destroy` ran in a different order per run; the swap-remove of the
collision list then left the two balls in a different order, and the solver,
which takes bodies in list order, split a ball-on-ball correction differently
(10 px apart). Fix: every engine weak set that is walked iterates in
insertion order (`scena._weakset.OrderedWeakSet`, the scheduler's class moved
and made cheaper: one shared callback, a list built in one pass; the
transients tick with 200 shapes measured 349 vs 343 µs, within noise): the
transients, SpatialFx, Endless fill, linked hitbox parts and appearance
channels, an act's game entities, pointer managers, track rides. Guard:
`test_weak_set_order` (every `WeakSet(...)` in `scena/` is listed with why it
is never walked; transients ending in one tick call `on_done` in start order
under shifted addresses; canary: the plain WeakSet fails all six trials). Same
class as S2-9 (the `on_update` fleet), which had fixed one site. Lesson:
**iteration over an id-hashed container is a source of run-to-run
difference; a container that is walked keeps insertion order.**

The same deep run's `test_sys_hyp_world` broke law L3: `GroupOperator.destroy`
walks a copy of its members and called `destroy()` on one that an earlier
member's `destroy` override had taken; the engine's second destroy is a no-op
(L2), but the override ran again on the dead (since v0.9.1 at least). The
broadcast (`group[...].verb()`) already skipped such a member (S9-3); the
explicit `destroy` now does too. Guard:
`test_registry_layers…test_destroy_skips_members_an_earlier_destroy_took`
(fails without the fix).

Open (seen while tracing, not changed): with the list order fixed, which body
the solver takes first still decides how a ball-on-ball overlap is split
(in the traced step one order moved both balls 10 px, the other moved one
ball 20 px). Deterministic now; whether the split should be order-free is a
solver question (Collision Design, "Mass split between two movable bodies").

### AH — async functions where Scena calls one (2026-10-10, 2026-10-12)

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| AH1 | `async def setup`, `async def on_update`, an async `@every` / `@when` / `@collide` / `on_click` / `on_done=`, or `after(1, lambda: self.anda())` with `anda` async: the body never ran; Python only printed "coroutine … was never awaited" (d017e2d, 2026-10-10) | Only a mode is driven as a script; every other door calls the function and drops the coroutine | `tests/test_async_hooks.py` (class hooks from `_HOOK_LOOKUP_NAMES`, decorator roles from `_ROLE_LABELS`, hook setters, script hooks, the `_invoke` / `call_truncated` backstop). Written with a hand list of the other doors: AH2 |
| AH2 | An async predicate, condition or formula was taken: `group["g"].filter(async_fn)` kept every member (also `any` / `all` / `count_where` / `group.nearest(where=)` and the free `nearest(where=)`), `await until(async_fn)` ended on its first poll, `@on_change(async_fn)` fired every frame with a coroutine, `@when(async_fn)` raised "must evaluate to bool, got coroutine" and left the warning, an `@=` formula raised "expected a number, got coroutine". Found 2026-10-12 by the surface guard written for AH1 | A coroutine is truthy. AH1's funnels were listed by hand; these doors call the function and read its answer | `test_async_hooks.TestEveryCallbackDoor` (11 of its doors fail on the code before; canary `test_canary_group_predicates_without_the_check`). Fix: `validate.refuse_async` in `registry._require_pred`, `shapes.nearest`, `process._start_until`, `events.when` / `on_change`, `collision._normalize_only`, `state._extract_sources` (A/B: `filter` / `count_where` / `nearest(where=)` within ±1 %). `resolve(only=)` was already refused at the first contact by the `call_truncated` backstop; it now raises at the call |

### KN — knobs that change nothing (2026-10-09, 2026-10-10, 2026-10-12, 2026-10-13)

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| KN1 | `Metal("gold")` drew chrome: every Metal was silver whatever its color (tutorial 28, 2026-10-09; 8e9244c) | The tint was stored on the Recipe and never set as a shader uniform | `test_visuals.test_metal_color_tints_the_metal`; class guard `test_knobs_take_effect` (canary: `_metal_tint` returning zeros). Fix: `u_tint` in the metal SkSL, `recipes._metal_tint` ([Effect System Design](Effect%20System%20Design.md)) |
| KN2 | `Wallpaper("BG.png", tile_mode="mirror", pan_response=0.1)` went black once the camera passed the image: `fit="cover"` / `"contain"` / `"stretch"` ignored `tile_mode` (5628654, 2026-10-10) | Fitted images drew with `drawImageRect`; only `fit="tile"` used the shader that honours the mode | `test_background_image.TestFittedImagePastEdge`; class guard `test_knobs_take_effect.TestWallpaperKnobsReachThePixels` (canary: `_uses_template` back to tile-only). Fix: [Canvas Design](Canvas%20Design.md) (`style._uses_template`) |
| KN3 | `Halo(style="line", rings=5)` (or `speed=`) raised Python's own "HaloLine.__init__() got an unexpected keyword argument 'rings'" (found 2026-10-12 by `test_knobs_take_effect`) | `Halo.__new__` returns a `HaloLine`; Python then calls `HaloLine.__init__` with every keyword, and it took only `style` | `test_visuals.TestHaloTintRoles.test_halo_pulse_knobs_raise_off_pulse`; `REFUSED_ON_STYLE` in the guard. Fix: `Halo.__new__` refuses non-default `rings` / `speed` on `line` naming `style="pulse"`; `HaloLine.__init__` takes the defaults |
| KN4 | Knobs documented for one style or fit, taken and ignored on the others: `Shield(color)` on bubble / nebula / ember / void / molten / cracks / frost; `Halo(rings=, speed=)` on hollow / fill / soft; `Bolt(amount=)` on core; `Wallpaper(tile_size=)` / `Texture(tile_size=)` off `fit="tile"` (found 2026-10-12 by `test_knobs_take_effect`) | Each knob was read by the style or fit that needs it and dropped by the others; nothing refused it | Decided (2026-10-12, user): raise with the fix, naming the style or fit that reads the knob; listed under **Fixed** for 0.8.1, not Breaking (user, 2026-10-12): the code it stops already did nothing. `test_visuals` (`test_halo_pulse_knobs_raise_off_pulse`, `test_shield_color_raises_on_fixed_hue_styles`, `test_bolt_amount_raises_on_core`), `test_background_image.TestTileSizeNeedsTile`; `REFUSED_ON_STYLE` / `REFUSED_ON_FIT` in the guard |
| KN5 | `Metal()` and `Metal("gold")` ignored `set_color`: the shape's color changed, the metal did not, and no warning said so; `Shield(style="bubble")` could not be tinted at all (found 2026-10-13 while deciding what an omitted color means) | Metal was labelled Role A (set_color shows) but drew from its own palette or its constructor seed; the role test only rendered zero-arg Role D / E looks on the default style | Decided (2026-10-13, user): a look that takes `color=` shows `set_color`; a look that takes none warns. Palette looks (`Metal`, bubble Shield) swap to a shape-following sibling ([Effect System Design](Effect%20System%20Design.md), "Omitted color, and set_color"). Class guard `test_visual_color_param.TestSetColorShowsWhereColorIsTaken` (every wearable look × style, unseeded and seeded; canary: `Metal._unseed` back to `None`); `TestPaletteLooks`. The seeded sweep listed 24 more looks × styles where the seed still wins (`SEED_WINS`, the open Phase 2 of the de-seed) |
| KN6 | `Metal("gold")` drew gold metal inside a chrome outline (user, 2026-10-13) | The tint reached the body shader (KN1) but the rim stroke kept the constant `_METAL_EDGE` | `test_visuals.test_metal_color_tints_the_rim`; the `test_knobs_take_effect` canary now plants body and rim together (with a tinted rim, a body without its tint still changes the pixels there). Fix: `recipes._metal_edge` |
| KN7 | One colour, three pictures (user, 2026-10-13): `Circle(color="red")` + `Rim()` drew a pinkish rim, `Rim("red")` and `Rim()` + `set_color("red")` a red one; after `visual = None` the recolored shape kept an outline no `color=` gives, and `Rim("red")` left a red body; `.line = "red"` after `visual = Rim()` drew a third rim (the look's alpha lost) | Role B `set_color` wrote the exact line (`_recolor_outline_look`), an outline seed dyed identity as a body colour, and the `.fill` / `.line` setters wrote raw paint under a look (the look's package skipped). The sweeps compared with one reference each and never with `color=` | Decided (user): an outline look follows the outline; `set_color(X)` ≡ `color=X` (derived outline); `.fill` / `.line` under a look re-apply it; an outline seed is the outline only (HaloSoft keeps the body, ElectricBolt reads the seed). Guard `TestSetColorIsColorParam` (above). Same order bug for `line_width` / `blend` / `dash`: KN8. Found in passing: the `test_knobs_take_effect` Metal canary failed when `test_visual_color_param` ran earlier in the same process: fixed as O11 |
| KN8 | Stroke knobs depended on write order (order sweep, 2026-10-13): `visual = Rim()` then `line_width = 3` drew a thin rim, `line_width = 3` then `Rim()` Rim's own wide one; same for `blend` under Halo / Bolt / Shield / Flame / Swell and `dash` under Shield / Flame / Swell (23 / 18 / 11 of 42 look × style cells); and a `line_width` / `blend` / `dash` / `line_cap` / `line_join` written under any look was dropped by `visual = None` (every cell, Shape and Sprite) | The knob setters wrote the live value only: the identity snapshot kept the pre-look value and the look's package was skipped. KN7 routed `.fill` / `.line` and left these knobs. `Circle(visual=, line_width=)` wrote the width after the look | Decided (user): re-apply, the look wins — a look that sets the knob keeps its own (`Rim(width=)` is how to change it), one that reads it follows, and the value shows after `visual = None`. The setters patch identity and call `_look_channel_written`; `_construct` writes `line_width` before the look. Guards `TestSetColorIsColorParam.test_knob_write_order_does_not_matter` (every look × style × knob, plus `visual = None`), `test_knob_in_the_constructor_is_written_before_the_look`, `test_sprite_knob_write_survives_the_look`, canary `test_canary_raw_knob_write_again`. Perf: no-look setters flat (A/B, 12 rounds, ±0.4 %); a write under a look costs the re-apply (~57 µs under Rim), as `.fill` / `.line` |
| KN9 | A placement on a track made without one was taken and ignored (confirmed 2026-10-13; it was the Guia's own example at the top of `#shape-track`): `orbit = Track.circle(radius=120); orbit["center"] @= lambda: earth.center; moon.move_along(orbit, …)` left the moon circling its own start, `is_floating` still `True`; the same for `orbit.center = …`, `move_to`, `move_by`, `center.x =`, `center << p`, on every sizes-only preset, before or after the ride began | Floating was inferred once, at construction, from the missing placement keyword, and the design said a later `move_to` / `center =` never flips it; a floating ride reads only its own root, so the track's center was read by nothing but the drawing | Decided (2026-10-13): a placement on an **inferred** float anchors it (the missing placement, given late); `floating=` / `is_floating =` said by the author never flip; running floating rides join the track. Raising instead was weighed and dropped: it breaks drawing a sizes-only track and placing it ([Tracks Design](Tracks%20Design.md), "Anchored vs floating"). Class guard `test_track.TestPlacementAnchorsInferredFloat` (every sizes-only preset × every placement spelling, link and write; onto the spot it has; after the ride began; declared floats stay). Perf: no per-tick check (rides are listed on the track; a ridden inferred float takes a pull consumer so a write refreshes it): 200 hover rides A/B 40 rounds, flat (0.866 vs 0.874 ms / tick) |

### PF — performance campaign (2026-10-12)

Found while measuring whole games for speed (`scripts/bench/game_bench.py`, the
benchmark games, [games.md](../scripts/bench/games.md)). Lesson for the class:
**a cache keyed on "what can change this answer" must be invalidated on the way
in as well as on the way out.** A cache cleared when a member leaves but not
when one joins answers correctly in every test that only removes. Each cache's
test runs a random sequence of joins, leaves and retags against a fresh build
after every operation.

| ID | Bug | Root cause | Guard |
| --- | --- | --- | --- |
| PF1 | A body under `resolve(hero, ANYTHING)` fell through a crate spawned in the same frame as an earlier spawn, when a query (`floor_below`) ran between them, and kept ignoring the crate after the frame | `_resolve_cache` (the step's `ANYTHING` / object expansions) was cleared when a collider left (`_swap_remove_collider`) but not when one enrolled. The query between the spawns rebuilt partner lists from the stale expansion, and the partner-identity cache keeps a list across frames (`step()` clears only the expansions) | `tests/test_partner_cache.py`: `TestAnythingSeesNewcomers` (the public repro), `TestCachedEqualsFresh` (random enroll / destroy / tag / untag / `collidable` / pair edits on every side kind; cached lists equal a fresh build, in order). Fix: `register` clears `_resolve_cache` |
| PF2 | A playing Sprite whose clip cells differ in size (a mixed strip, a trimmed atlas) drew past its cull box: a 91 px cell in a box sized for a 9 px one. The box also ignored the paint tilt and seat. With `cull_offscreen` on, the body could vanish while partly in view, and B5's overlap test could move a draw over it | The box came from `_oriented_frame` (`width` / `height`, set at `play()`), not from the cell the blit draws. Found while making the cull default on | `tests/test_cull_cache.TestSpriteDrawBox` (every painted pixel lies in `Sprite._draw_aabb`; the `play()`-sized box is the canary), `TestPlayingClip`. Fix: `_draw_aabb` maps the cell on show through the paint transform |
| PF3 | A `Rect(p1=, vec=)` resized by `vec =` / `vec <<` kept its old hull: no `@collide`, no query hit | `Vec2._takein` overrides the funnel that bumps the pose revision (the gap B1 had fixed for `Point`) | `tests/test_cache_gaps.py` `TestPoseWriters`. Fix: `Vec2._takein_impl` bumps on a part |
| PF4 | A linked hitbox `active` (`hb["active"] @= …`) and a move made by an exit handler the step's prune fires took effect one step late | `step()` drained the moved set before `_prune_dead` and the linked hitbox refresh, which write poses too | `tests/test_cache_gaps.py` `TestStepDrain`. Fix: drain just before the snapshot |
| PF5 | `floor_below(group=)` missed a `"clip"` hitbox that time had switched (a clip ending with `next=`) | queries refreshed moved and untrusted bodies, not `_timed` ones; a clip switch by time has no write | `tests/test_cache_gaps.py` `TestQueriesSeeEveryBody`. Fix: `_fresh_proxies` refreshes `_timed` |
| PF6 | After `Collider([shape])` on an enrolled shape, the shape's own collider (still registered) stopped moving: its `@collide` never fired | the moved set reaches a body through `root._collider`, which the explicit Collider took | same class. Fix: `_unbound`, visited by every query and step |
| PF7 | A formula group as a `resolve()` side (`group["x"] @= lambda: group["a"]`) ignored a body that joined or left it by a tag change | H1's selective drop (A3) dropped lists only for tags that are resolve sides; a formula side reads other tags | `tests/test_cache_gaps.py` `TestPartnerLists`. Fix: any tag event drops the lists while a side is a formula group |
| PF8 | A still scene flickered (up to 239/255) with the cull on, and a culled object changed how its neighbours batched (mixed segments, reach merges) | the cull removed objects before planning the units; the backoff toggled it frame by frame | `tests/test_cache_gaps.py` `TestCullPlan`. Fix: culled objects stay in the plan, not drawn (`_CULL_IN_PLAN`) |
| PF9 | Culled while in view: Extrude slabs (up to 165 px), Rim / Halo on Sprites, CheapGlow on a playing clip; stale cached boxes after `shield_scale =`, a lazy bake under tilt, and a move of a contact-seated Sprite | boxes short of the paint (pre-existing, exposed by the default-on cull); writers with no revision bump; a shift where the move is not a translation | `tests/test_cache_gaps.py` `TestCullBoxes`. Fixes in [Canvas Design, "Offscreen culling"](Canvas%20Design.md#offscreen-culling) |
| PF10 | Verify mode passed scenes with stale cull boxes | the draw loop fails open on any exception, so the verify `AssertionError` was swallowed and the frame drew correctly | `tests/test_cache_gaps.py` `TestCullBoxes.test_verify_mode_raises_inside_a_frame`. Fix: under verify mode an `AssertionError` propagates |
| PF11 | `untag` of the last member of a group a formula group reads raised `KeyError` after a step | the nested `notify_group_remove` had already dropped the emptied entry | `tests/test_cache_gaps.py` `TestPartnerLists.test_leaving_the_formula_by_an_untag`. Fix: `remove_from_group` pops with a default |

Found by the review of groups A and B (2026-10-12): four adversarial reviewers
with throw-away old-vs-new differentials ([games.md](../scripts/bench/games.md)).
Lessons for the class:
- **A verify mode sees only what a test exercises.** `SCENA_VERIFY_POSE_REV`
  ran the whole gate green while PF3–PF6 stood: no test wrote `vec`, linked
  `active`, or switched a clip by time between a step and a query. A skip
  needs a writer census (every override of a funnel), not only a verify run.
- **A check inside a fail-open path must escape it** (PF10).
- **A cache that drops items also drops their effect on the neighbours**
  (PF8): planning, signatures and overlap tests read the dropped item too.
- **A test that counts a layer must not assume it empty.** The deep tier's
  serial pass ran `test_cull.TestBackoff` after `test_audio_level_source`,
  which left 19 Rects and Recorders on the default layer: one off-screen
  body fell under the backoff's 1/16 and the test failed only there. The
  module now sweeps (`module_sweep`), and the test hides what it did not
  make. A pixel test compares two draws of one frame, not a frame with an
  earlier one (an earlier module may leave a sky that moves).

**A tolerance can be a hidden tie-break.** Swapping an approximate algorithm
for an exact one (GJK advancement, which stops 1e-3 short, for the closed-form
swept SAT) changed which of two floors a drop meets first only where both are
met at the same instant: a foot corner exactly on a plateau–ramp joint. The
skin had made the polygon win by ~1e-5, and
`test_floor_below.test_walkable_slopes_are_floor` pinned the polygon at two
joint positions (dx=20 and, falling, dx=40) without saying so. Before trusting
an identity assertion, check that the fixture is not on an exact joint. When
it is, assert the set of valid answers and say why
([Collision Design, "Polygon sweeps"](Collision%20Design.md#polygon-sweeps)).

### CB — author class body and constructor (2026-10-13)

Found writing tutorial 06 (classes): two ways an author class looks right in
Python and is silently not what it says. Both fixed for every family at once
([Actors Design, "Current design choices"](Actors%20Design.md#current-design-choices)).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| CB1 | An author `__init__` that never called Scena's own built an empty object: never registered, nothing drew, `on_update` never ran, no warning even in strict mode. With `on_click` defined, an internal `AttributeError: no attribute '_clickable'`. `Bolha(center=…)` against it said "Write Bolha()" — straight into the silent case | `class Bolha(Circle, radius=30): def __init__(self): self.velocidade = 100`, then `Bolha()` | The actor wrapper runs the finish step (hooks, `setup`) after the most-derived `__init__` whether or not `_construct` ran; the keyword rewrite took the author's `__init__` signature as the whole truth | Every test `__init__` called `super().__init__(**kw)` (rollback, mixin adoption, class defaults); no test wrote the beginner's version | `_finish_actor_construct` refuses an object whose `_actor_constructed` was never set (`getattr` default `None`: same cost on the built path), naming `setup` and `super().__init__(**kwargs)`; `_explain_author_init_keywords` names the same fix for Scena keywords; a read of `self` before the build (`self.radius`, a method's `'_owner'`) does too (`_ink_read_slow`, a branch normal construction never reaches). Not refused at class definition: `__init__` + `super()` is legitimate (parameters of one's own). Guard: `test_subclass_parity.TestAuthorInit` (every exported family: refused, census unchanged; with `super()` it takes its own parameter and `setup` runs once; an author mixin's `__init__` is named; `self` used before `super()` is named, every family; a typo keeps the near-miss) |
| CB2 | A class-body value under a property's name was never read: `class Bolha(Circle): radius = 30` gave the default radius, `class Tiro(Sprite, source=…): height = 28` gave 48, `visible = False` read `False` while the shape drew, `center = (1, 2)` crashed with an internal error. The Guia said it "esconde a propriedade" | as written | Construction writes Scena's field through its setter; the class value only shadows some reads | Nothing looked at an author class body; the Guia's warning described a guess, not a run | `Entity.__init_subclass__` → `_refuse_class_body_values`: every non-descriptor value in an author class (or author mixin) whose name is in the kind's `_setattr_route` raises on the class line, with the class keyword (`_class_keywords()`, keeping the class's own keywords) or `setup(self)`. Guard: `test_subclass_parity.TestClassBodyValues` (every family × every Scena-owned name, ~4,400 classes in 0.3 s; the class-keyword table agrees with what the class line takes; own fields, methods and properties stay) |

Lesson: a pattern from general Python (`__init__`, class attributes as
defaults) that the framework handles differently needs a test written the way
a newcomer writes it, not the way the framework's own tests do.

### PE — Point equality (2026-10-13)

Found adding `approach`: an author steps an object onto a stop and tests
`elevador.center == PARADA`, which never becomes true. Decided with the maintainer
after weighing value `==` ([Shapes Design, "Point"](Shapes%20Design.md#point)).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| PE1 | `==` on a Point was identity, silently: `c.center == (5, 5)`, `== (5.0, 5.0)`, `== Vec2(5, 5)`, `Vec2(5, 5) == c.center` and `== Point(5, 5)` were all False with the circle there; `!=` always True (a `while c.center != alvo:` never ends) | `c = Circle(center=(5, 5), radius=1); c.center == (5, 5)` | A Point is an Entity: it inherits `object.__eq__`. `Vec2` has value `==` and Points read like `Vec2`s. `Vec2.__eq__` answered `False` (not `NotImplemented`) for a Point | No test compared a Point with a value the way an author does; engine tests compared positions with `.x` / `.y` | Value `==` weighed and refused: measured on the quick tier, the registry scans `layer._interactive` (`in` / `remove`) and the debug-point lists with distinct Points on one spot ~22k times (value `==` removes the wrong handle), and `act._game_entities`, `spatial_fx`, `bounds` key weak sets / dicts on Points (`__hash__ = None` raises there; a position hash breaks when the point moves). Value `==` against tuples only was refused too: the Point-vs-Point trap stays silent and `==` stops being transitive. Fix: `Point.__eq__` keeps identity (`__hash__ = object.__hash__`, restated: a class that defines `__eq__` loses its hash) and warns once per line when **author** code compares a Point with a tuple / list / `Vec2` (either side; `Vec2.__eq__` hands a Point back) or with another Point on the same spot, naming `distance(a, b) == 0` and `a is b`. Author = the comparing frame is outside `scena/` (a cell's `__eq__` is looked through); engine compares stay silent. Accepted price: an author `p in pontos` with another Point on the same spot warns. `Point.eq` / `get_hash` (undocumented) removed. Guard: `test_point_equality` (every spelling warns at the author line, once; identity, hash, weak containers kept; handles on one spot keep the right one; cell writes silent). Perf: no `Point.__eq__` call in the four benchmark games' real loop (horda, mundo, corrida, festa, counted); a non-identical Point compare costs ~130 ns instead of ~24 |

### CH — class gesture hooks (2026-10-14)

Found writing the tutorial interlude "Ganchos na classe": every top-of-file
hook was mapped to its class form, and the drag rows did not work.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| CH1 | In a class, `def on_click(self)` made the shape clickable, but `def on_drag_to(self, alvo, pos)` / `on_drag_over` / `def on_drop_by(self, peca, pos)` turned nothing on; with `draggable = True` set by hand, `on_drag_to` received `(self, alvo)` | `class Bola(Circle): def on_drag_to(self, alvo, pos): …` — `bola.draggable` is `False`; drag it anyway: `alvo is bola` | The drag names were not in `entity._ACTOR_HOOK_NAMES` (never installed through the setter), and dispatch read the attribute, which the class method shadows, and called it with the instance payload `(from, to, pos)` | Drag tests used the decorators or the instance assignment; the class-hook tests checked names, not behaviour | The three names are discovered hooks, installed through the setter with `entity._drag_method_adapter` (drops the side `self` already is); dispatch reads the slots (Shapes Design, "As a class method"). Guard: `tests/test_class_gesture_hooks.py` (every pointer property of a Graphic is a discovered hook; each method sets the instance form's flag on Shape, Sprite and Text; the payload; the top-level signature raises) |
| BD1 | A decorator that takes arguments, written bare, did nothing: `@every` / `@after` / `@when` / `@on_change` / `@exit_mode` / `@collide_with*` / the six pointer verbs above a `def` (and `@self.every` in a method). `@click()` wired nothing. `@click(group["x"])` above a method made a rule of the whole tag at the class line, with the target as `self` (on an act, the button) | An author asking whether a class may use `@click` instead of `def on_click(self)`: `class Bola(Circle): @click() def tocou(self)` → `clickable` False, no message | A bare decorator gets the function as its argument and returns its inner decorator, which nothing calls; the name is rebound to that closure. The pointer factory accepted zero targets, and only `@collide` checked for a class body | Tests used decorators the right way; no test enumerated the decorator factories against their misspellings | Refused at the line where the argument can never be a function (`validate.refuse_bare_decorator`); `@when` / `@on_change` / `@exit_mode` mark the returned decorator and the class line and `run()` refuse a name bound to it (`bare_decorator_message`); pointer verbs refuse no targets and a class body (Shapes Design, "Decorators"; Actors Design, failure table). Guard: `tests/test_bare_decorators.py` (every public decorator factory, found by its source, is classified; each bare form at the top of the file, in an Entity and an Act class body; the forms that look alike still work) |

### CV — concave partners in the sweep (2026-10-14)

Found building `Concave` (a box with a scoop): a ball rolled into a
quarter-pipe and flew off at 45°, peaking at half the height its speed
allows. The same ball rolled into a `Polygon` with the same outline did the
same, while the outline's pieces as separate Polygons were fine.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| CV1 | A body swept against a concave multi-prim partner (an ear-clipped concave `Polygon`, a `Concave`, any set whose union is not convex) stopped on the partner's **convex hull**: a ball could not ride into a scoop (thrown off the hull's chord) nor drop into a U notch (it rested on the hull's top) | `Concave(top_left=(0, 200), width=200, height=200)` + floor, `resolve`, a ball at 500 DU/s → velocity (250, 250) at the foot, peak 80 (ideal 149); a ball over a U `Polygon` stops 50 above the notch's floor | `_toi_prim_sets` sent multi-prim sets to `_toi_advance` as sets; `_gjk_distance` on a set is the distance between the sets' convex hulls (the support function runs over the union). Collision Design said "GJK on a set sweeps the hull of the union", kept as it was | Sweep tests used one prim per side or convex sets; the Polygon tests checked detection and settle, not a body entering a notch; the multi-prim test in `test_sweep_sat` pinned the hull path (it asserted SAT was never used on a set) | Sets are swept pair by pair (`collision._toi_prim_pairs`), each pair by the single-pair rules, earliest wins, swept-box pruning ([Collision Design — Polygon sweeps](Collision%20Design.md#polygon-sweeps)). Guards: `test_sweep_sat` (`test_multi_prim_sets_sweep_pair_by_pair`, `test_a_body_enters_a_concave_set` under both `_SWEEP_SAT` values), `test_concave.TestRides` (quarter-pipe ride and return, half-pipe swing, U polygon drop); all fail on the old set sweep. Class: **A set is treated as its hull** |

### PG — game-behaviour probe campaign (2026-10-13/14)

Probes written as real author games and apps, each played under real input
(held keys, drags, focus changes) for hundreds of frames and across act
changes: a shooter, Breakout, a platformer with a lift, a paint app, a farm
with a HUD inventory, forms, physics-style worlds (ramps, piles, bounces),
and timing, camera and geometry scripts. Groups: PA acts, processes and class
hooks; PB collision; PC shapes, field links and value protocols; PD input and
widgets; PE physics. Every finding was fixed (or decided and documented) in a
worktree branch and merged into main. The ids are local to this series: the
graphics review's PA / PB ([GR](#gr--graphics-review-2026-10-08)) and Point
equality's PE1 are other findings; elsewhere in this document these are
cited as PG-PB5 and so on.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| PA1 | An act's `@=` on a game object survived the act change: each restart warned "Attribute Text.text received a formula that overrides its previous link", the next act's `hud.text = "NAVES"` raised `LinkedAttributeError`; a formula reading an act object or the act's `self` was dropped with a SCENA WARNING (decided 2026-09-28) | `hud = Text("")` at the top; `class Fase(Act): def setup(self): hud["text"] @= lambda: f"Pontos {st.pontos}"`; `change_act(Fase)` | The seal recorded group formulas (S4-3) but not field links; the change only unlinked links whose source died | `TestBatchTeardown` pinned the drop-with-warning case; no test restarted an act that linked a game HUD | `FieldRef.__imatmul__` / `Container.__imatmul__` call `state._ACT_LINK_HOOK` (set at the seal of a game with acts; nothing per frame) → `act._note_act_link` records the field's game link or value before the act's first link; `ActManager._undo_act_links` (change step 2c) unlinks it and gives it back; `_unlink_notice` is silent for those nodes. The override warning became a SCENA WARNING naming the unlink. Guard: `test_act.TestActLinksOnGameObjects` (restart silent, act-object and act-`self` sources, game link restored, point field restored, `c.center @=` spelling) |
| PA2 | A one-line busy loop in an async mode (`while not st.pronto: pass`; `while n < 10**9: n += 1`) escaped the watchdog: 3 s, 15 s, until it ended | as written | `sys.monitoring` LINE fires on a change of line; a loop on one line has none, only its back jump | Watchdog tests spun `while True:` on two lines | The tool also listens to JUMP (`_watchdog_on_jump`): a back jump onto its own line counts; forward jumps and back jumps to another line return `DISABLE` on first touch (weak per-code cache of one-line jumps, AC1-safe). Perf: interleaved A/B, 400 async actors (half with a 20-step loop per frame), within noise. Guard: `test_process.TestAsyncAwait.test_watchdog_stops_a_loop_on_one_line`, `test_sync_watchdog_stops_a_loop_on_one_line` |
| PA3 | `def update(self, dt)` / `def on_key_down(self, key)` / `def on_mouse_click(...)` in an Act class were never called, silently; on a Shape / Sprite `def update(self, dt)` replaced `Container.update` and construction crashed in `state._batch_update` ("missing 1 required positional argument: 'dt'") | `class Fase(Act): def update(self, dt): ...`; `class Ship(Circle): def update(self, dt): ...` | Hooks are found by name; the top-of-file names are read from the module only; `update` is the graph's recalculation | Every test class used the right names | `entity._check_class_hook_names` in `Entity.__init_subclass__` (author classes): `TypeError` naming `on_update`, and for an act `keyp.once` / `mouse.press()`; on an actor `on_click` / `on_hover` / `draggable`. Guard: `tests/test_class_hook_names.py` (every exported family; the pool follows `_ACTOR_HOOK_NAMES`; the top-level list follows `set_auto_callbacks`) |
| PA4 | `after(0.1, lambda: self.set_color("red"))` in `on_update` outlived the actor and raised `DestroyedError`; `after(0.1, lambda: self.atirar())` made a destroyed enemy shoot. `after(0.1, self.atirar)` was fine | as written, then destroy the actor before the timer | `_infer_owner` read a bound method's `__self__` only; a closure was ownerless act work | Ownership tests used bound methods or closures without `self` | Decided 2026-10-14: a closure cell named `self` holding an Entity (and a partial's bound method) owns the work like the bound method (`process._closure_self`); inside that actor's own `on_destroy` the plain rule stays (`run_on_destroy` stack). Guard: `test_process.TestClosureOverSelfIsOwnedLikeTheBoundMethod` (lambda, nested def, partial, every, on_done=; another actor's closure unchanged; mode scope; on_destroy) |
| PA5 | The watchdog named an act `<__main__.Fase object at 0x…>`; the act-change link warning said "the Fase made at system_support.py:364" (the framework's construction line) | a one-line loop in an act's mode; a link that read the act, dropped at `change_act` | An act had no `__repr__`; `entity_label` used the construction site | No test read the text of those two messages | `Act.__repr__` / `entity_label` → "act Fase"; a dropped link that read the act says "read act Fase, which ended when the game changed to …". Guard: `test_act.TestMessagesNameTheAct` |
| PB1 | `heroi.untag("heroi")` (or a group change) while touching a spike: the spike–hero `@collide_exit` never ran, so an "on the spike" flag or an enter / exit counter stayed on; also with class `@collide_with_exit` | a spike and a hero touching; `hero.untag("hero")`; step; `hero.tag("hero")` | The exit matched handlers against the tags the sides had at the exit; the left tag no longer matched | Exit tests ended a contact by moving or destroying a side, never by a tag change | `notify_group_remove` → `_note_left_tag` records the partners touching then; `_exit_matches` counts the left tag as a member for those contacts only (two step generations, replaced 2026-10-16 by the per-commit record of CD3; a contact begun later does not match); untag + retag in one frame is no change; a destroyed body drops its record. Guard: `test_collision.TestExitAfterGroupChange` (module and class handlers, flick, untag then destroy gives one exit, a later contact does not match) |
| PB2 | A rider on a sideways moving platform was carried by a frame-rate dependent fraction of the platform's motion: 97 % at 30 fps, 87 % at 60, 2–24 % at 144, ~1 % at 240 (tutorial 27's sideways elevator slid out from under the ninja) | `STATIC` lift `move_by(200*dt, 0)` (or a timed yoyo, `move_along`), hero with gravity, `resolve(hero, "lift", bounce=0)` | The only carry was the relative sweep's leftover `d_other × (1 − t)`, with `t` the share of the gravity step spent closing the 0.08 DU skin; at a high frame rate the step is under the skin, so `t` → 1 or there is no hit | Rider tests used vertical lifts (the part along the normal, which the relative sweep and floor snap handle) and 60 Hz | Decided (2026-10-14): full carry. `_carry_riders` moves a body grounded at frame start with its `"bottom"` partner's displacement, as motion, before the sweeps ([Riders](Collision%20Design.md#riders-a-body-standing-on-a-moving-partner)). Guard: `test_resolve_solver.TestRiderCarry` (30 / 60 / 144 / 240 Hz, STATIC and mass-50 lifts, a walk adds, a jump ends it, a wall on the path, stacked riders in both orders, a pushed crate is not a carrier, a paddle bounce is not dragged, `_RIDER_CARRY` canary), `TestRiderCarryTimedMovers`. Traps found on the way: stacked riders on one lift double-counted the carry through the partner's inherited leftover; a clamped unswept travel must slide along the wall, or a rider's carry along its floor was lost; the first-slide flag was "the body has not moved yet" (`ox == 0`), so a stop whose unswept travel a wall cut to nothing made the next slide relative again (the pool / list SameFrames test caught it; now the slide index) |
| PB3 | An exit handler that destroys or untags a side hid the contact's other exit handlers | two `@collide_exit("ball", "zone")`; the first destroys the ball (or the zone) | Exit handlers were matched one by one while they ran, so the next one no longer matched a side the first had removed | S8-2's tests covered enter / stay; no test had two exit handlers on one contact | Exit handlers are chosen before the first runs (`_exit_matches`); a handler removed meanwhile is skipped. Guard: `test_collision.TestExitAfterGroupChange.test_destroy_in_one_exit_handler_keeps_the_others` (either victim) |
| PB4 | A rider on a descending `STATIC` lift got no `@collide_stay` while `touching_sides` said `"bottom"` (60 DU/s at 60 Hz: stay 0 / 60; 30 DU/s at 144 Hz); a yoyo lift exited at the top and never re-entered | rider on a `STATIC` lift doing `move_by(0, -v * dt)`; count `@collide_stay` while `touching_sides` has `"bottom"`; a yoyo lift | Detection is pre-resolve: the gap was the slop + the lift's drop − the rider's fall, past the fixed `_CONTACT_SKIN`; floor snap then kept the rider grounded | F1 tests rest on still floors; lift tests read `touching_sides`, not `@collide` | The resting skin widens by a carry: an immovable side's motion-channel travel along a floor gap normal, only when the movable side was grounded at frame start (snap's precondition): `_carry_opening`, `_skin_contact`. Guard: `test_sys_resting_contact.TestRiderOnAMovingLift` (descending 30–200 DU/s and yoyo at every pacing, jump off exits, guard-for-the-guard with the carry off) |
| PB5 | Whether a shot scored depended on spawn order: `Tiro.bateu` (`self.destroy()`) and `Inimigo.atingido` (`self.destroy(); st.pontos += 1`), both `@collide_with`; also a module `@collide` next to a class method | spawn an enemy before the shot and one after it; 1 point instead of 2 | S8-2 stopped a contact's remaining enter / stay handlers once one destroyed a side, and per-instance handlers are appended at construction, so the first-made body's handler ran first | S8-2's tests asserted the stop (one handler per contact or mutual kill), never two independent rules on one contact in both spawn orders | Decided (2026-10-14): every enter / stay handler of a contact runs (`_dispatch_contact` lists the matches before the first runs); a body destroyed there enters no other pair; an act change still stops (`_act_change_epoch`). Guards: `test_collision.TestEveryEnterHandlerOfAContactRuns` (shooter in both spawn orders, module + method either order, two methods of the dying body, one shot one enemy, stay), `TestDispatchSeesWhatHandlersDid` updated. Follow-up: the contact's exit is deferred to after its remaining handlers (`_deferred_exit`; the dying body's own exit hooks still run at the destroy): `TestAContactsExitComesAfterItsHandlers` (zone counter in both orders, park, class methods in both spawn orders, other pairs exit at the destroy) |
| PB6 / PD8 / PC4 | `x, y = ship.center`, `tuple(mouse)`, `x, y = Vec2(1, 2)` raised "field name must be a str, got int" | `x, y = Circle(center=(1, 2), radius=1).center` | No `__iter__`: Python's legacy iteration called `p[0]` through the field-bracket `__getitem__` (`Container._resolve_field`) | No test unpacked a point; every engine path reads a point by type | Decided (2026-10-14): Point / Vec2 / Mouse `__iter__` yields the two floats now (a snapshot); `p[0]` raises naming `p.x` (`_point_index_refusal`); a non-string bracket on any Container names the field form, and on a Graphic `x, y = ship.center` (`_field_key_refusal`). Audit: every link / copy entry reads a point with `isinstance` (`_read_xy`, `get_xy`, `_init_composite`, `lerp`, `_pair_numbers`); the two that iterate "a list of points" (`Polygon(points=)`, `nearest(items)`) test `_scena_point_value` first. Point is iterable but not a `Sequence` (no `__len__`). Guard: `test_point_unpack` (unpack, snapshot, index refusal, a handle does not iterate, nine link rows still follow after the source moves, five copy rows still copy, one point is not a list) |
| PC1 | `shape.clone(center=(300, 50))` ignored `center=` on Circle, Rect, Square, Ellipse, Polygon, RegularPolygon, Line, Point, Track (Sprite / Svg / Text honoured it); the Guia showed the stamp pattern with `center=` and said shapes follow the same rule | `Circle(center=(100, 100), radius=10).clone(center=(300, 50)).center` → `(100, 100)` | `Shape._clone_recipe` dropped `center=` / `frame=` (docstring said so); the Guia's shape `clone()` row said "Sem parâmetros" | Clone tests were per kind (Sprite with `center=`, shapes without) | `Graphic.clone` reads `center=` before the copy exists (`_clone_center_xy`: a point-like snapshot; a function refuses) and, on kinds that do not place through the constructor (`_clone_places_center`: Shape), `move_to`s the copy after its pose, before `scale=`; `frame=` refuses on kinds without frames (`_clone_takes_frame`: Sprite only). Guard: `test_shapes.TestShapeClone.test_clone_center_places_every_kind` (13 kinds) + point-likes × `scale=` + refusals build nothing |
| PC2 | `obj["name"] @= f` made a new ink field — a link nothing reads — when `name` is a method (`c["move_to"]`), a read-only property (`tri["points"]`, `poly["pointer_hover"]`, `rect["box"]`), a settable property, a size / point word the kind lacks, or a Polygon vertex name (`tri["v1"]`); `=` on the same names raised. `tri["v1"] @= lambda: B.center` raised "scalar field Polygon.v1 cannot take a Anchor" | `Circle(radius=5)["move_to"] @= lambda: b.center.x` | The route table (R8) refuses `=` only; the bracket path checks near-misses, not the exact name | The R8 guard walked `=`; `TestVelIsNotLinkable` skipped every name the bracket accepted | `_ink_exact_name_message` (before the near-miss rules, cached per class × name): a `_RouteRefusal` gives the `=` message, a settable descriptor names `=`; a class names its own near-fields first (`Polygon._ink_name_refusal`: `points` / `vN` → `poly.points[i] @=`); strict kinds (Point, Line) too. Guard: `test_fieldref.TestBracketRefusesWhatAssignRefuses` (every exported kind × every refused route name; no ink made) |
| PC3 | `tri.points[1] @= f` raised "'tuple' object does not support item assignment", but the link was installed (a refused statement that changed state; W3) | `tri.points[1] @= lambda: B.center` | Python runs `v = points[i]; v @= f; points[i] = v`: the `@=` linked the vertex, then the plain tuple refused the store-back | No test linked a vertex through `points[i]` | `Polygon.points` is a `_VertexTuple` (tuple subclass) whose `__setitem__` takes its own vertex back (as `line.p1 @= f` stores `p1` through its route) and refuses any other store with `points[i].move_to` / `@=`; `_LazyRegularPolygonPoints.__setitem__` names center / radius / angle (its `@=` raises `DerivedAttributeError` first). Guard: `test_fieldref.TestPolygonVertexLink` |
| PC5 | Near misses of a hook (`on_colide`, `on_updat`) and a plain method named `collide_with` were accepted and never called | `class Rock(Circle): def on_colide(self, other): ...` | No class-body name check (the ink near-miss guard covers writes, not methods) | Every test class used the right names | The PA3 guard: one edit or one swap from a hook or an engine base's `on_*` name, other engines' spellings (`on_collision`, `on_mouse_enter`), `collide_with`; decorated rule methods and author-base names pass; the repo's helper names (`on_hit`, `on_frame`, `on_exit`, …) stay legal (`TestEveryFamily.test_hooks_engine_names_and_helpers_stay_legal`) |
| PC6 | Under a turned camera `canvas.game_view` is the axis-aligned box around the view: `confine(canvas.game_view)` and grid cells land off screen; the Guia did not say so | `canvas.rotate_to(30)`; `confine(ship, canvas.game_view)` | Documented in Canvas Design only | Docs | Guia rows (`game_view` in Mundo and Colocar) + gotcha with the turned `Box(center=, width=W/zoom, height=H/zoom, angle=-canvas.rotation)` (checked against the view corners) |
| PC7 | A `layer="ui"` shape's `contains_point(mouse)` is False under a zoomed / panned camera although `@click` / `pointer_hover` work; the Guia rows called it "o mesmo teste do clique" | `Rect(..., layer="ui")`, `canvas.zoom_to(3)`, pointer over it | `mouse` is world coordinates; the pointer walk gives ui shapes the view pointer | Docs | Docs, not code: reading the view pointer when the argument is the `mouse` object would make `contains_point(mouse)` and `contains_point(mouse.x, mouse.y)` differ (a silent rewrite by argument identity). Fence row (Shapes — Hit-testing); Guia rows say "no mundo" and point to `pointer_hover` |
| PC8 | `mouse.x` read right after `canvas.pan_by` in the same update holds the pre-pan world value until the next frame | `update`: `canvas.pan_by(10, 0); print(mouse.x)` | The pointer is sampled once per frame (intended) | Docs | Guia `mouse.x` row. Guard: `test_sys_frame_contracts.TestPointerFrames` (mapped in `FRAME_PROMISES`) |
| PD1 | A hold-to-fire `Button(st["firing"])` destroyed while held (or by `change_act`) never wrote `value_off`: `st.firing` stuck `True` into the next act | hold the Button, `fire.destroy()` (or `change_act`), release | `WidgetManager.remove_widget` replaced the press record's widget with `None`, so `Button._on_mouse_up` never ran; the S1-9 lost-release recovery popped the record the same way | Widget lifetime tests checked focus / hover / click records, not what the press itself wrote | `UIWidget._abandon_press(button)` (Button: `value_off`, no click), called from `remove_widget` and `_resync_input_from_os`. Guard: `test_input_streams.TestAHeldButtonThatLeavesLetsGo` (destroy, act change, lost release, custom `value_off`, a released button writes nothing) |
| PD2 | `mouse.press(Mouse.BTN_LEFT)` read True while a widget owned the press: a paint app painted under a dragged Slider | `Slider` + `if mouse.press(...): Circle(center=mouse)` in `update`, drag the handle | `Mouse._button_down` ran for every press before the widget dispatch; only a modal hid buttons | No test read `mouse.press` while a widget held the press | Decided (2026-10-14): `Mouse._widget_buttons` hides a widget-taken press from `press` / `click_pos` until it goes up (a shape press stays visible). Guard: `test_input_streams.TestAWidgetPressIsHiddenFromMousePress` Follow-up 2026-10-14: a `SpriteButton` (a Sprite, not a widget) hides its press the same way, enabled or not, ui or world; a plain Sprite with `on_click` stays visible (`test_input_streams.TestASpriteButtonPressIsHiddenToo`). |
| PD3 | Holding Enter: `on_submit` focuses another TextInput (or `change_act` to an act whose setup focuses one) and the OS auto-repeat submits that box empty | `nome = TextInput(..., on_submit=lambda v: resp.focus())`, Enter press + REPEAT | A REPEAT went to whatever box was focused; `_claimed_down` was a set of keys, not key → widget | W-P4 guarded the script door only; no test sent a REPEAT after a focus change | `_claimed_down` maps a key to the widget that got its press; repeats and the release go to it only while it keeps focus; a repeat of a key pressed before focus stays with the script door. Guard: `test_input_streams.TestARepeatFollowsItsPress` + `TestStreamOwnershipMatrix` |
| PD4 | The cursor leaves the window with no last motion event: a hovered Button stays hovered (`pointer_hover` True, no `on_hover_exit`); shapes did get the exit | hover a Button, cursor to outside (no motion callback), step | Widget hover was resolved only on motion events and widget-list changes (S3-6); Graphic hover already followed the per-frame sample | `input_driver.place` existed, but no test placed the cursor off a widget | `_sync_pointer_level` calls `WidgetManager.refresh_hover` when the sampled view point differs from the last one resolved (`_ptr_seen`; a tuple compare per still frame). Guard: `test_input_streams.TestWidgetHoverFollowsThePointerSample` (also: a pressed widget keeps hover until release, then loses it) |
| PD5 | A `layer="ui"` item dragged onto a world droppable gave `on_drag_to(to=None)` and no `@drop_by`; a world piece onto a HUD droppable got nothing | HUD seed → world plot; world rock → HUD bin | `handle_mouse_move` / `handle_mouse_up` hit-tested only the press space (`hit_test_ui if _press_in_ui else hit_test`) | Drag tests stayed in one space | Decided (2026-10-14): `_drop_target` = topmost droppable, ui first, then world, any start space; `pos` in the space of the handler's own shape; the framework records both pointers before a move / release. Guard: `test_input_streams.TestDropsCrossSpaces` (both directions under a panned camera, ui over world) |
| PD6 | `keyp("RIGHT")`, `keyp.once("SPACE")`, `on_key_down("SPACE")` were False / not delivered while Shift was held: a "hold Shift to sprint" platformer stopped and could not jump | `speed = 250 if keyp("SHIFT") else 100; if keyp("RIGHT"): ...` | Intended rule ("a bare key, no modifier"), surprising for Shift | The rule was tested as intended (`test_shift_does_not_satisfy_bare_play`) | Decided (2026-10-14): a spec that lists no modifier ignores Shift; Ctrl / Alt / Cmd still hide it; chords exact; `keyp.only` exclusive; Shift down no longer latches `once`. Level editor: `App.on_key` handles Shift+arrow. Guard: `test_keyp` (rule rows, `TestOnceChordProperty` oracle updated), `test_input_streams.TestShiftDoesNotBlockABareKey`, `test_editor_system` (`test_shift_arrow_nudges_by_the_grid_once`, in `scena_editor`). Perf: `keyp()` interleaved A/B within noise (+2 % / −7 %, run to run) |
| PD7 | A key held across `change_act` never got its `on_key_up` (nor a button its `on_mouse_up`), against Scena Design ("Every script `on_key_down` … gets its up") and the Guia `on_key_up` row | `on_key_down`/`on_key_up` set and clear `st.dir`; hold RIGHT, `change_act`, release | `CanvasManager.forget_act_input` cleared `_keys_down` / `_presses` (S3-8 wanted no click / repeat; it also dropped the up) | S3-8 tested the click only; no test released a key after an act change | Old-act keys and presses are marked (`_old_act_keys` / `_old_act_presses`), not dropped: the up comes (the key hooks are top-level, so the handler that saw the down is still there), no repeat / drag / click. `clear_input()` for harnesses. Guard: `test_input_streams.TestUpsCrossAnActChange` + matrix |
| PE1 | Settle pushed two overlapping bodies that moved apart through each other: balls spawned overlapping swapped sides in 6 frames (stuck forever without `bounce=`); a ball spawned in a 4 DU wall and moving into the room escaped outside; a `STATIC` paddle placed onto a ball lost it below; a three-ball wedge resolved by creation order | `Circle((100,100),10)` vel (−60,0) and `Circle((115,100),10)` vel (60,0), `resolve("ball", "ball", bounce=1)` | With no remembered normal, `_settle_normal` flipped the SAT axis when the relative velocity separated along it (a guess that the body entered from the far side); each 0.5 × depth correction then deepened the overlap | No test spawned an overlapping pair with velocities apart; the one deep-overlap test pinned the velocity guess as a feature | Settle separates along the minimum overlap ([Settle direction and STATIC under a stack](Collision%20Design.md#settle-direction-and-static-under-a-stack)). Guard: `test_resolve_solver.TestSettleIgnoresVelocity` (the class guard: random overlapping pairs settle to the same poses with random velocities as with none; `_SETTLE_MIN_OVERLAP` canary); `test_collision.test_settle_of_a_body_placed_past_floor_midpoint_ignores_its_velocity` (turned around: the old test pinned the guess) |
| PE2 | An idle hero on a `STATIC` ramp crept downhill `_RESOLVE_SLOP × sin θ` per frame (30°: 24 DU in 10 s at 60 Hz, 57.6 at 144), against Collision Design's "an idle body on a slope does not creep" | ninja idiom: `vel.x = 0; vel.y -= 2200*dt; move_by(...)`, ramp `rotate_by(30)`, `bounce=0` or position-only | After a vertical stop the sweep backed off the skin along the slope normal, and floor snap did too; the next vertical fall kept the sideways part: a ratchet | `test_collision.test_walk_speed_holds_and_idle_slope_does_not_creep` allowed 3 DU in 40 frames (the creep was 1.2) | A body that stops on a floor backs its skin off along its own motion (`_skin_back_off`; Collision Design, Resolution step 3). Guard: `test_resolve_solver.TestIdleSlope` (10 / −22 / 30 / 40° × 60 / 144 / 240 Hz × `bounce=0` / position-only, under 1e-6 DU in 2 s; `_SKIN_ALONG_MOTION` canary); the `test_collision` test tightened from 3 DU to 1e-6 |
| PE3 | `STATIC` floors gave way under stacks: a light crate under a mass-5 crate sank to y = 11.6 (rest 20.08), under mass 20 almost fully in; a 100-ball bin on a 10 DU floor lost 5 balls | `STATIC` floor 40 thick, crate (mass 1) on it, crate mass 5 on top, gravity, `bounce=0` | Settle split a correction between two movable bodies by mass without the lower body's `STATIC` contacts (the sweep's `_push_reach` clamp had no settle counterpart); and a share given to a partner not yet swept was placed, which moved the start of its own sweep into the floor | The stack and mass-split tests had no movable body between a heavy one and a `STATIC` floor | `_nudge_pair_along` casts each share against its body's `STATIC` partners (`_push_reach`), cuts it at the wall and gives the rest to the other body; a partner still to sweep takes its share in its motion channel (`_push_partner`) ([Settle direction and STATIC under a stack](Collision%20Design.md#settle-direction-and-static-under-a-stack)). Guard: `test_resolve_solver.TestStaticHolds` (stacks of mass 1–100 × floors 2 / 16 / 40 DU × both orders; a 40-ball bin on a 10 DU floor; `_SETTLE_STATIC_CLAMP` canary) |
| PE4 | A light ball resting on a 10 DU floor went through it under a mass-30 ball dropped from 110 DU (light one created first); a light body swept before its fast pusher was placed 116 DU past a 2 DU wall (Collision Design's open "Mass split → Limits" item, closed) | light ball first, heavy ball `mass=30` above it, `resolve("ball", ["floor", "ball"])` | The relative sweep's inherited leftover `d_other × (1 − t)` (and the skin, the follow) was placed, not swept, against the body's own walls; also with no closing gap | MS1's thin-wall test (`test_push_into_a_thin_wall_stops_at_it`) swept the pusher first; no test had a movable body between a heavy one and a `STATIC` floor | A sweep stop's unswept travel is swept against the body's `STATIC` partners (`_travel_to_walls`; Collision Design, Mass split, row "Body's walls"). Guard: `test_resolve_solver.TestStaticHolds.test_light_ball_under_a_falling_heavy_one_stays_on_the_floor`, `test_fast_push_into_a_thin_wall_with_the_light_body_first`, `_SWEEP_INHERIT_CLAMP` canary |
| PE5 | Breakout: `resolve(ball, "brick", bounce=1)` + `@collide` that destroys the brick: the ball never bounced and ploughed through every brick | a 40-brick Breakout: 39 of 40 hits unreflected | Handlers run before resolve (Frame order); the destroyed brick left the partner list, so the solver had nothing to bounce off | Resolve tests never removed a partner from a handler; handler tests never used `bounce=` | Decided (2026-10-14): a resolve partner a handler of this step removes leaves a ghost contact (`_note_ghost_contacts` in `_end_contacts_of`; `_apply_ghost_contacts` before resolve): velocity response on the survivor only, no push; TOI normal when reached on the frame's path, else the detection normal; `only=` gated. Guard: `test_collision.TestBounceOffAPartnerAHandlerRemoved` (30 / 60 / 144 Hz, park, no push, `bounce=0` landing, skin contact, jump along a removed wall keeps its speed, one-way, finite mass, position-only) Revised 2026-10-15 (G2, with LW2 / LW8): the removed partner is a still wall for the survivor's sweep that step, so the ball bounces where it touched instead of going on into the brick's space for the rest of the frame; guard `tests/test_joint_response.py` `TestGhostWalls` |
| PE6 | No friction: with `bounce=0` the sideways velocity stays (balls slide off ramps, piles never rest) | ball on a ramp, `resolve(..., bounce=0)` | By design (inelastic normal only) | Docs | Guia gotcha in Tornar sólido with the frame-rate-independent idiom `self.vel.x *= 0.5 ** dt` |
| RD1 | Hold fire, let go, press again one frame after the cooldown: the next held shot came one frame early (8 frames for a 0.15 s cadence at 60 Hz); found by the armada random pilot in gate (`ready.cadence`), present since W-T2 | `ready("tiro", 0.15)` polled while SPACE is held; release for 7 frames; hold again | `_ready_poll` re-anchored only when the overshoot reached a whole interval, so the reopen True carried its one-frame lateness into the next shot | `test_ready_after_a_pause_in_polling_does_not_burst` paused for a whole second; no test let go for less than one interval | `_ready_poll` notes the frame of each poll; a gap of a frame or more restarts the cadence at the True that ends it. Guard: `test_uneven_pacing.TestDecidedClocks.test_ready_after_a_short_gap_restarts_the_cadence`; the armada model (`modelo_ready`) checks it under random pilots |

Lesson: see [What the game-behaviour probes taught](#what-the-game-behaviour-probes-taught-2026-10-14).
Kept under load, beside the per-finding guards, by the fourth game system
test, Canteiro ([Game system tests](#game-system-tests), "The fourth game"),
with a canary per fix.

### LW — laws campaign (2026-10-14)

Findings of the laws instruments ([Laws and equations](#laws-and-equations)),
with the triage verdict.

| ID | Finding | Verdict | Cause | Fix / guard |
| --- | --- | --- | --- | --- |
| LW1 | Two runs of one game in one process differed in a fade's `canvas.covered` in the last bits (0.9333333333333333 vs …371), growing each frame; E0 saw it as the recorder's doing, but two bare runs differed the same way | ACADEMIC for the engine (a real game is one process, its presentation clock starts at 0); a harness isolation gap | `SystemWorld`'s reset zeroed `clock._time`, `_real_time`, `_frame` but not `_ui_time` (presentation time, added later): the second run's fade read `(t - t0) / d` on another base | `system_support` reset sets `clock._ui_time = 0.0` (a hand-kept reset list drifted from the clock; [Recurring bug classes](#recurring-bug-classes), "A hand-kept list drifts from the code"). Guard: `test_laws_neutrality` (E0 compares runs in one process) |
| LW2 | Breakout: a ball that touches two bricks in one step (the seam between them) leaves in a direction that depends on how the bricks are broken and on which was made first. Straight up into a 4 DU seam: 29° off vertical with plain `resolve` (7° at 1 DU, 60° at 8); the E8 twin (STATIC bricks) left 156° by creation order with plain `resolve`, 134° breaking in `@collide`. One brick at a time agreed. (The "no bounce at gap 2" of the first measure was LW8.) | **BUG**, fixed 2026-10-15 (the maintainer: design first, 2026-10-14) | Both answers resolved simultaneous contacts one at a time: the sweep kept the earliest hit (a tie by partner order) and the next slide met an already turned velocity; `_apply_ghost_contacts` ran one `velocity_split` per removed partner along the frame's original path, so it also answered bricks the ball would never reach after the first bounce | The joint stop: ties within the skin (parallel normals dropped, mutual blocking for internal edges), answered by the cone projection (`_cone_response`: order-free, no energy gain); removed partners are still walls of the survivor's sweep (G2), so live and dead partners answer together. Guards: `tests/test_joint_response.py` (`TestJointAlgebra`, `TestSeams`, `TestInternalEdges`, `TestGhostWalls`; canaries `_JOINT_RESPONSE`, `_GHOST_WALLS`), `test_laws_equations.TestBreakInHandlerOrLater.test_two_bricks_at_once_agree` (velocity and path) |
| LW3 | E3 (spawn order): a shot touching two enemies in one step hits the first-made one; a drone landing on two overlapping pads enters the first-made one | ACADEMIC | Below the fast gate, a body that enters two partners in one step reached both within half its thickness (a tie); the documented tie-break is collider order ([Collision Design — Swept detection](Collision%20Design.md#swept-detection-fast-bodies), "Order"). No program or example showed it outside the fixture's deliberate ties | V3 states the exception |
| LW4 | E3 on an example swapped two `Endless(...)` lines and the scenery changed | ACADEMIC | `Endless` without `seed=` draws its seed from the author's global `random` at construction: two swapped constructions trade their numbers (no less random, no less reproducible) | E3 counts `Endless` among the calls that draw random numbers (`equations._RANDOM_NAMES`) |
| LW5 | "Press T to chat": `on_key_down` focuses a `TextInput` when T is pressed, and the box starts with a "t" in it; a game key held while a box takes focus auto-repeats its character into the box (the PD campaign's "left open" note) | **BUG**, fixed | Characters carry no key: `_handle_char` gave each one to whatever box had focus *now*, after the key's handler had moved the focus | `WidgetManager._char_to_script` (set by a press / repeat the box did not get, cleared by the box's own press / repeat and by any release): that character goes to `on_char`. Input path only (a store per key event), no frame cost. Guard: `test_input_streams.TestACharFollowsItsKey` (the opening key, a held game key, typing / Shift / composed text, a released game key does not eat later text); law I4 (`model/input.py`), canary `plants.i4_chars_to_the_focused_box`. The first version also ate the first character of text with no key event after any unclaimed key (two editor tests): the flag ends at the key's release |
| LW6 | E1 at 144 Hz destroyed `orbitas`' trail dots that the 60 Hz run kept, and a second run did not: shape transients (`dissolve_out`) ended by the machine's speed in headless runs | **DECISION**, applied 2026-10-16 (the maintainer: transients on presentation time) | Shape transients read the wall clock (`transients._now_fn = perf_counter`; Scena Design, Clocks, then: "wall … presentation, documented: a paused menu still animates"). The presentation clock (`clock._ui_time`: unscaled, capped, runs while paused) already served that intent for the cover and post-fx. Beyond headless runs: a stall (a drag, a GC pause, a load) jumped a running transient to its end, its `on_done` at a moment the machine chose, and a shape's `fade_out` and `canvas.fade_out` started together ended apart; `SystemWorld` pinned transients to world time, so the tests ran a clock production did not read | `transients._now` reads `clock._ui_time` (the framework class bound once: +4 ns a read, the 500-shape tick + compose A/B within noise); SpriteButton eases follow (they read `transients._now`). Neither harness pins transients any more. Guard: `test_transients.TestTransientsRunOnPresentationTime` (paused, slowed, a 5 s stall through `Clock._tick`, a run with the wall clock made to raise, a shape fade and the cover ending on one frame); all six fail on the wall clock. The gate then failed `time_scaled` (program oracles) on platformer and galaga_acts: a `dissolve_out(0.4, on_done=bola.destroy)` lasts 0.4 real seconds in slow motion, so the ball left k times as many frames later. The equation had passed only on the harness pin; it now reads world time for the presentation consumers in both runs (they are out of its scope; their own clock has its own tests) |
| LW7 | E1 (pacing): a ball bouncing between two walls has a longer period at a lower frame rate — at 700 DU/s the ideal 0.520 s gap is 0.553 s at 30 Hz, 0.545 at 60, 0.535 at 144 (a ball in a box runs 6 % slow at 30 Hz, 3 % at 144); bolas / entropia drift by frames over a run | **BUG**, fixed 2026-10-15 (with LW2) | The sweep stopped at the contact, answered the velocity, and projected the leftover along the surface (Collision Design, Resolution step 3): a head-on bounce has no along-surface part, so `(1 − t) × d` was dropped at every bounce (5.2 DU a bounce at 30 and 60 Hz, 1.4 at 144, at 700 DU/s); a `bounce=1` ball dropped from 200 came back to 190 / 195 / 198 at 30 / 60 / 144 Hz | The bounce sub-step: the closing part of the leftover gets the restitution the velocity got (`bounce=0`: the slide, unchanged), the mass split shares `(1 + e) × gap`, no sub-step off its floor for a body grounded at the frame's start (rest). Lag 0.08 DU a bounce (the skin) at every rate. Guards: `tests/test_joint_response.py` `TestBounceSubstep` (canary `_BOUNCE_SUBSTEP`), `test_laws_equations.TestPacing.test_two_wall_twin`, canary `test_e1_catches_the_dropped_leftover`. `E1_EXCLUDED` keeps bolas / entropia with another reason (many-body contacts, ACADEMIC) |
| LW8 | E8 at other phases: a ball that ended a frame within the resting skin of a brick (gap ≤ 0.16 DU) got its `@collide`, the author broke the brick the next frame, and the ball flew through it (0 of 200 phases at 30 Hz, 4 at 60, 10 at 144); breaking in the handler was safe | **BUG**, fixed 2026-10-15 | The handlers saw a skin contact; the sweep had not reached the brick, so resolve answered nothing, and the next frame's sweep found no brick | `_answer_unreached`: a skin contact (or a removed partner) the sweep never reached is answered for velocity that step, for an airborne body on a `bounce > 0` pair, along a cast along the velocity, and recorded. Restrictions measured: the detection gap normal at a seam is wrong (a walker got `(54.9, +7.5)`), and `bounce=0` turned an idle hero's fall into a ramp slide (canteiro 240 Hz, P5). Guard: `tests/test_joint_response.py` `TestSkinAnswer` (canary `_SKIN_ANSWER`) |
| LW9 | The one-ball twin's walls and the breakout twin's bricks had the default mass 1: the ball pushed the floor away and left the box at uneven pacing (x = 1338 at 7.9 s), so E1 compared nothing after that, and passed; with STATIC walls E1 failed (LW7) | **harness** | A twin built from `Rect(...)` without `mass = STATIC`: no `.vel` makes a body immovable for the velocity, but the mass split still pushes it | Both twins STATIC (the Guia: walls, floors, platforms and bricks are `STATIC`); a two-wall twin (`twins/two_walls.py`, 700 DU/s) joins E1. A twin is checked against the game it stands for, not only against itself |
| LW10 | E1 (pacing) on the examples of 2026-10-23 (gate): `old_school`, `credits_roll`, `demo100`, `guardiao`, `loom` and `pulse` made their objects at other game times at 30, 144 Hz or uneven pacing, the gap growing over the run (`old_school`'s letters 0.2333 s apart at 60 Hz, 0.2222 at 144) | ACADEMIC (five); **harness** (`pulse`) | The five are shows written as chains: `await wait(p)` loops, and `loom`'s throw → `move_along` → `on_done` → `after` → throw. Each link starts at the frame that noticed the last one end (T2; Laws V1 known limits; Clocks: "at least `p` apart", R5-8 / R6-4), so a link lasts `ceil(p / dt)` frames. `pulse` hears its beats in `audio.spectrum`: headless, the offline mixer renders one block per frame (`pump_dt`), so the analysis window is the frame time (7 ms at 144 Hz holds no bass period) and a beat lands frames apart or is missed; a live device's blocks do not follow the frame rate | `E1_EXCLUDED` names each with its reason; its rule now reads: it grows only by a divergence traced to a known limit of V1. No engine change (the chain rule is a decision; a rate is `every`, a steady path `move_along`) |
| LW11 | E3 on `loom.py` swapped the shuttle's two followers (lines 174 and 177): frame 0 had two Points at line 174 in the program, at 177 in the twin | **harness** | The first shape to link to an Ellipse's `center` fills that Ellipse's foci (`fp1`, `fp2`, a Derivate part made on first access, `_materialize_derivate_part`). A part made later takes `_site` from the stack, the reader's line; the recorder labelled `N` events by that raw `_site`. Author text was right: `made_at` and `entity_label` name a part through its owner | The recorder labels a part filled by `_materialize_derivate_part` at the filling shape's site (`laws/trace.py` `_materializing_site`). Guard: `test_laws_quick.TestLazyPartsAreTheirShapes`, canary `test_foci_labelled_at_their_reader_are_caught` |
| LW12 | E3 on `pendulums.py` (gate, 2026-10-26) swapped the loop that fills `bobs` (line 71) with `Track(points=[… for b in bobs])` (line 82): the twin raised `Track(points=) needs at least 2 points` | **harness** | `swap_candidates` counted a statement's writes by name binding only; `bobs.append(bob)` fills the list without binding `bobs`, so the two statements looked independent | `_names_written` also counts a container mutator call on a name (`append`, `extend`, `insert`, `add`, `update`, `setdefault`, `remove`, `discard`, `clear`) and a subscript store (`box[k] = …`). Over the 60 law scripts it drops this one swap and keeps the other 244 (counting every method call or attribute store would have dropped 6, among them `grade.cell(0, 0)` and two `shuttle.x =` attachments). Guard: `test_laws_equations.TestSwapCandidates` |

### CK — copies across kinds (2026-10-15)

Found weighing `Shape(box=lambda: ...)`: a probe copied `hero.box` into every
kind.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| CK1 | A whole copy into a kind that cannot take the source leaked Python's error through `<<`, `absorb` and a whole `@=`: `Circle << box` AttributeError (`width`), `Ellipse << box` ValueError "Unknown ellipse model: RectModel.CENTER_WH", `Triangle << box` AttributeError (`_n`); the same for most cross-kind pairs (`line << rect`, `rect << circle`, `polygon << rect`, `regular_polygon << triangle`), and the target was left with the source's model | `Circle(center=(0, 0), radius=3) << Rect(center=(100, 100), width=40, height=20).box` | Only Square, Box and Track checked the source's kind; every other `_takein_impl` adopted the source's model first, then read parts the source does not have | `sweep_c7` and `TestCopyAcrossModels` copy within a kind; the Square / Box refusals were tested one pair at a time | Shapes Design C7: a kind takes only what it can be, and an Ellipse fills a Box (as `Ellipse(box=)`); every other pair refuses before any write with a TypeError naming the fix (`_copy_kind_refusal`: `Circle(box=box)`, `rect << ellipse.box`). Guard: `test_copy_kinds`, every kind (every model) × every Box model and one source per kind × every copy door, from the kind registry (which must cover every exported kind) |

### SF — Sprite / Svg `box=` (2026-10-15)

Found adding `box=lambda: …` to the Sprite family: the probe compared a
box-linked sprite with a fresh `Sprite(box=region)` across flips and turns,
and an Svg's raster with `Svg(height=)` of the same size.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| SF1 | A flipped Sprite / Svg placed by `box=` in a turned region drew upside down: at region angle `0` it kept its rest heading (drawn `0`), at `1e-6` it drew at `-180` (`box.top_center` below the center), at `30` at `-150`. `art_angle` sprites were off the same way | `Sprite("x.png", box=Box(center=(0, 0), width=40, height=20, angle=1e-6), flip_x=True).box.top_center` → `(0, -10)` | `_init_sprite_body` did `if inherit_angle: rotate_to(inherit_angle)`: the region angle replaced the heading instead of turning it from rest (`180` for `flip_x`), and `0` skipped the write, so the result jumped at 0 | No test placed a flipped (or `art_angle`) sprite with `box=`; the fit tests used plain sprites, whose rest heading is 0 | The heading is the rest heading plus the region angle (the contain fit lies the art along the region's axes). Guard: `test_box_formula.TestSpriteBoxHeading` — turning the region turns the result (named points rotate about the center), every flip × `art_angle` × angles across 0 (40 failures with the old line) |
| SF2 | `Svg(box=region)` rasterized at the 128-unit default whatever the region, so a big box drew it upscaled and blurred (64 × 128 px drawn at 200 × 400) | `Svg(markup, box=Box(center=(0, 0), width=400, height=400))._sheet._frame_at(0).src_w` → 64; with `height=400` → 200 | The first raster size comes from `width=` / `height=` / `size=` only (`_svg_dest_longer_from_kwargs`); `box=` was resolved later, in the Sprite body | `test_svg` has no `box=` case, and the drawn size (what `box=` tests read) was right — only the raster behind it was small | `box=` alone rasters at the region's longer side (a formula region: its first value). Guard: `test_box_formula.TestSvgBoxRaster` (same raster as `Svg(height=)` of the drawn size) |

### CD — chaos doors (2026-10-15)

Findings of the chaos doors ([Laws and equations](#laws-and-equations), S7),
with the triage verdict. Directed cells: `tests/laws/fixtures/s7_cells.py`,
pinned by `test_laws_chaos.TestCells`.

| ID | Finding | Verdict | Cause | Fix / guard |
| --- | --- | --- | --- | --- |
| CD1 | A card's `on_hover_exit` locks (parks) the card next to it; the pointer moves straight from one to the other, and the locked card still lights: its `on_hover` runs while parked (L4). Hiding it (`visible = False`) did the same | **BUG**, fixed | `ShapeInteractionManager._set_hover_target` fired the new target's enter after the old one's exit, checking only that the target was still the same object (a destroyed one is cleared by `forget_destroyed`; a parked or hidden one was not) | After an author exit handler ran, the new target is re-checked with the hit test's own rule (`_hover_target_still_valid`: alive, drawn, hover-eligible; widgets and the pressed shape keep theirs); one that fails gets no enter and the next frame resolves again. Guard: `test_pointer_hover.TestEdges.test_exit_that_parks_or_hides_the_next_target_gives_it_no_enter`; cell `hover_park`. Cost: nothing when no exit handler runs; with one, +1.1 % of a hover-change frame (~0.4 µs per change, in-process interleaved A/B) |
| CD2 | Two game bodies whose `on_collide` the act set as a closure over the act (the act's own hook) touch; the first hook changes the act; the second still runs, once, on the act that is gone (a write to it raises `DestroyedError`). Same for the stay and exit hooks | **BUG**, fixed | `_dispatch_contact` chose a contact's runs up front; after an act change it re-checked a tag rule's registration (S4-1) but never a side's own `on_collide*` (`ta is None`), which `_drop_act_callables` had cleared; `_run_exit` had the same gap | After the act epoch moved, a side's own hook runs only if it is still that side's hook (`_run_exit` takes the epoch its runs were chosen at). Guards: `test_act.TestChangeInsideADispatch` (`test_an_act_hook_on_a_game_body_stops_on_enter`, `…_on_stay`, `…_on_exit`); cell `act_callable`. Cost: inside the act-changed branch, plus one compare per side-hook exit run: −0.8 / −0.1 % on 60 pairs entering and exiting every other frame (A/B, noise). The first cell was the instrument's error: its hook did not close over the act, so it was the game's and ran on by design ("closest owner wins") |
| CD3 | A body gains a tag while touching a partner a rule pairs it with: the rule's enter runs if nothing paired the two before, and never if another rule already did (only stays) | **BUG**, fixed (2026-10-16, per-rule contacts; a design session) | A contact was per pair of colliders, not per rule | [CD3](#cd3--a-rule-a-contact-gains-or-loses-mid-contact-2026-10-16) (with CD3-x and CD3-b); equation E15. Cell `join_rule`: `test_laws_chaos.TestCells.test_cd3_a_tag_gained_while_touching_enters_whatever_other_rules` |
| CD4 | A game-level ball breaks an act's brick in a handler that also changes the act: the ball passes on, no bounce | today's rule (F3: an act change cancels what the ending act owed, ghosts included) | `drop_act_pair_handlers` clears `_ghost_contacts` | Documented in F3 and Scena Design, "Commands during a pass". Pinned: `test_laws_chaos.TestCells.test_cd4_an_act_change_drops_the_ending_acts_ghost` |
| CD5 | `change_act` in an act's own `setup`, then a write to `self`: `DestroyedError` "Guard the call: if actor:" | message, fixed | The act ended inside its own setup (immediate, Act Design); objects made after the change join the new act, as documented; the refusal gave the actors' fix | `_refuse_if_destroyed` names the act change for an act: "act Fase ended when the game changed act … Write change_act(...) last, or return right after it." Guard: `test_act.TestMessagesNameTheAct.test_a_write_to_an_act_after_its_change_act_names_the_change` |
| CD6 | A formula installed outside a frame (oficina's first act `setup`) fires an `@on_change` whose callback destroys the group its sources are in: `AttributeError: 'NoneType' … '_dirty'` escapes (X2; deep tier 2026-10-22) | **BUG**, fixed | `FormulaLink.evaluate_and_update` kept writing `self.owner` after `owner.update()` flushed watches that unlinked the link (`clear()` sets the owner to None) | Re-check the owner after each flushing call and stop if the link was cleared. Guard: `test_link_install_flush` (5 owners × `@on_change` / `@when` × destroy source / group / owner, relink, unlink). Cost: install only; −0.2 % (A/B, noise) |

### CD3 — a rule a contact gains or loses mid-contact (2026-10-16)

Set aside by the chaos-doors campaign for a design session; the maintainer chose
per-rule contacts (Collision Design, Pipeline, "A contact is per rule").

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| CD3 | A body gains a tag while it touches a partner a rule pairs with that tag: the rule entered if nothing else paired the two, and never (only stays) when another rule already did. The same for a pair handler declared, or an `on_collide` set, mid-contact | a Circle `hero` inside a Rect `lava`; `@collide` / `@collide_stay("shield", "lava")`; `hero.tag("shield")`; with and without `@collide_stay("hero", "lava")` | Enter / stay / exit were decided per pair of colliders (`entered = contact_keys - prev`); a rule that began matching an existing contact was dispatched as a stay | Every enter test began a contact by moving a body or making one; no test changed a rule while a pair touched, and none compared a rule alone and beside another | Per-rule contacts read at the commit (`_note_flux`, `_note_new_rule`, `_rule_changes`, `_gain_pending`, `_stay_skip`); a gained rule enters in a new contact's order. Guards: `test_collision.TestARuleAContactGainsOrLosesMidContact`, equation E15 |
| CD3-x | A tag left while another rule keeps the pair touching never ran the left tag's exit, not even at the separation: an enter / exit counter stayed +1 | as CD3, `hero.untag("shield")` while `@collide_stay("hero", "lava")` keeps the pair | PB1's left-tag record served only an exit of the whole contact; the contact went on, and the record expired after two steps | PB1's tests ended the contact with the untag (the only rule naming the tag) | `_rule_changes` lists the lost exit rules (`_lost_pending`), run after the step's exits, or at a destroy before them |
| CD3-b | A tag joined and left between two steps (a blink) ran that tag's exit, never entered, when the pair separated | as CD3 with the other rule, `hero.tag("shield"); hero.untag("shield")` and a move apart in one frame | `_note_left_tag` did not ask whether the tag was held at the last step | Untag-then-retag (a flick) was tested, not tag-then-untag | Each change records the membership at the last commit (the first change sets it): a blink and a flick are no change |

### VI — in-place Vec2 ops and the parts of a dead actor (2026-10-16)

Found while proving the `Graphic.vel` same-object early return equivalent
(the setter was the only guard left for `ship.vel += (inf, 0)`).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| VI1 | `w += (inf, 0)` / `w -= (nan, 0)` / an overflowing sum / `do_rotation` past `1.8e308` stored a non-finite axis on a free vector, a part vector (`Line(p1, vec=).vec`) or `ship.vel`, while `w.x = inf` raised; `ship.vel += (inf, 0)` raised from the vel setter with `vel.x` already inf; `w += (10**400, 0)` leaked Python's `OverflowError` | `w = Vec2(1, 2); w += (math.inf, 0)` | The op wrote both axes inside `_batch_update`, and a batched `_write_field` coerces with `clamp=True` (no finite check) | Finite tests wrote one axis with `=`; the in-place ops were tested with finite operands | `Vec2._store_xy`: compute both axes, check (`x - x != 0.0` on the fast path), then write. `test_vec2_inplace_guards.TestInPlaceOpsRefuseNonFinite` (every op × every non-finite operand × every kind of vector) |
| VI2 | `line.vec += (1, 0)` / `do_rotation` on a `Line(p1, p2)` (a computed `vec`) changed `vec` and not the line, while `line.vec.x = 5` raised `DerivedAttributeError` | `line = Line(p1=(0, 0), p2=(3, 4)); v = line.vec; v += (1, 0)` | The same batch skips the Derivate refusal too (`_write_field` under `_in_batch_update`) | Derivate tests used `=` and `@=` | The op reads x / y from `__dict__` when the A3 cache (`_scalar_bare_ok`) says both are bare (no walk due), else through the descriptor; not bare → `_refuse_derived_axes`. `TestInPlaceOpsOnADerivedVector` |
| VI3 | The `vel` of a destroyed actor took writes: `held.x = 3`, `held += …`, `held << …`, `held.do_rotation(…)` were stored, and `dead.vel += (1, 0)` changed the vector before the dead route refused, while `dead.center.x = 3` raised | `ship.vel = (2, 3); held = ship.vel; ship.destroy(); held.x = 3` | Teardown retires Entity parts (`retire_part` sets `_destroyed`); a Vec2 part only got `_host_destroyed`, which the `@=` check reads and `ScalarSlot.__set__` does not | W2 tested `@=` on a held part; the axis doors were tested on Points, which are Entities | Teardown marks every non-Entity part `_destroyed` with `_destroyed_with_host` (the refusal builds the breadcrumb lazily); `Vec2._takein` refuses a dead vector; engine stores of `length` / `angle` use `_write_field`, so reads stay legal. `TestDestroyedActorParts` (every write door; every held part of each kind; reads) |


### VB — Vec2 battery (2026-10-17)

Found by the [Vec2 battery](#vec2-battery) and its review. Verdicts by
mechanism; DECISION rows wait for the author-facing call.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| VB1 | An in-place op on a vector holding an int stored an int no float holds, then raised: `w += (10**400, 0)` left `w.x` a 401-digit int and every later read of `length` raised `OverflowError` (free vector and `ship.vel`). ACADEMIC operand, but it broke VI1's "check before write" | `w = Vec2(1, 2); w.x = 4; w += (10**400, 0)` | `v.x = 4` keeps an int (the Numbers rule allows it); `4 + 10**400` is an int whose `x - x` is 0, so `_store_xy`'s finite test passed | VI1's operands met float axes only | `_store_xy` sends a non-float result through `finite()` (refuses, or stores the float). Guard: the matrix's `number` invariant, `test_vb1_…` |
| VB2 | A cell that took a vector another holder held shared it: `st.start = st.pos` then `st.pos += v` moved the saved start, and `st.start = …` later removed `st.pos`'s guard (`st.pos.x = 5` then passed silently, and nothing linked to `st.pos` heard it). `st.v0 = ship.aim` put the cell's guard on the ink field's vector: `ship.aim.x = 9` raised naming `st.v0`, and `ship.aim += d` moved the snapshot | `st.pos = Vec2(1, 2); st.start = st.pos; st.pos += (5, 0); st.start` | `Attribute._takein_impl` copied only an owned vector (RA3); one guard slot per vector, so the second cell's guard replaced the first's | No test gave one vector a second holder | The cell copies a vector another cell holds (`_held_payload`) or an ink field took (`_ink_held`, a sticky mark set where ink stores a Vec2). Guard: `kept` / `refused` invariants on the `st_saved`, `ink_saved`, `ink_saved_unwatched` kinds; the machine's "no two cells share a vector" |
| VB3 | A linked vector in a holder: (a) `st.pos["x"] @= f` was accepted while `st.pos @= f` is refused, and its pulls never reached what reads `st.pos` (the link stayed on the old payload after `st.pos = …`); (b) an ink field's vector linked whole or per axis (`ship.aim @= f`, `ship.aim["y"] @= f`): formulas reading `ship.aim` kept the value at link time; (c) a cell given a vector already linked (`v["y"] @= f; st.pos = v`) held it, and the pulls never reached the cell's readers | `ship.aim = Vec2(1, 2); mira = Circle(center=lambda: ship.aim); ship.aim @= lambda: Vec2(st.k, 2); st.k = 5` | A pull stores raw and calls no `update()`, so the held-vector hook (SV10) never ran for it; a formula reading the holder depends on the holder's node, not on the link's | SV10's matrix checked the value right after each write, never after a link's source changed; (c) needs three steps | (a) refused with the cell spelling; (b) while held and linked, each ink holder's field node depends on the link's node(s) (`_HeldPayloadUpdate.sync_link_edges`, edges only for linked held vectors, removed when the holder lets go); (c) the cell copies a linked vector. Guard: `follow` re-checked after the source changes; machine (c was found by it at `ci`) |
| VB4 | Decided 2026-10-17: refuse. A free vector took NaN / inf through `<<` and a pull (`v @= lambda: …`), while the constructor, `.x =`, `+=` and every arithmetic result refused it; held in a cell or an ink field, it made every formula reading the holder raise "a point takes two finite numbers" far from the write. No consumer could use such a vector (`_xy_of` refuses it, arithmetic raises) | `st.pos = Vec2(0, 0); mira = Circle(center=lambda: st.pos); st.pos << (math.nan, 0); mira.center` | GX15 refused a non-finite pair on a part only and left "a free Vec2 is a value and may hold NaN / inf" as a side note; `_takein_impl` checked finiteness only for an owned vector | a test in `test_reactive_matrix` and GX15's own test in `test_value_validation` pinned the store, with no reason given | `_takein_impl` refuses a non-finite pair on every Vec2 ("a vector takes two finite numbers"); a linked one raises on the read while its source is bad and recovers on the next good read, as a number slot's link does. A/B: free `<<` 1.01×, a link pull 1.00×, `vel <<` 0.88× (no `_finite_xy` call). Guard: `test_vb4_…`, both pins now assert the refusal (`test_reactive_matrix.TestNonFiniteScalarLink.test_a_pair_store_is_checked`); `vec2_known` lost its VB4 entries |
| VB5 | Arithmetic overflow leaked Python's `OverflowError`: `v + (10**400, 0)`, `v - …`, `v * 10**400`, `ship.vel *= 10**400` (while `+=` / `<<` raised Scena's `ValueError`) | `Vec2(1, 2) * 10**400` | The float operation overflows inside the operator, before `Vec2.temp` | The value sweeps reached `+=` and `<<`, not the pure operators | Operators and `temp` turn it into GX15's words. Guard: `leak` invariant, `test_vb5_…`, the algebra's junk table |
| VB6 | Decided 2026-10-17: refuse. `v * True` scaled by 1 (and `* False` by 0, `/ True` by 1) while `v + (True, 0)`, `rotate(True)`, `vec_from_angle(30, True)` and `lerp(w, True)` refuse a bool (Scena Design: "bool is never a number") | `Vec2(1, 2) * True` | `__mul__` multiplied whatever Python multiplies | The junk table fed `True` to the operators and took a finite result as success | `*`, `/`, `*=`, `/=` refuse a bool with the scale message; the test sits behind the float check, and `Vec2.temp` is called positionally, which pays for it (in-process A/B 1.00×). Guard: `test_vb6_…` |
| VB7 | Decided 2026-10-17: normalise. `(-Vec2(1, 0)).angle` was −180 while `Vec2(-1, 0).angle`, `ship.vel = -ship.vel` and `rotate(180)` read 180: negating stored a y of −0.0, and `atan2(-0.0, -1)` is −180; one direction read two values depending on the door | `(-Vec2(1, 0)).angle` | `atan2` keeps the sign of a zero | The twins compared bits, not the sign of zero; nothing compared `angle` across doors | `angle` (every place it is computed) and `angle_to` read in (−180, 180]: `+ 0.0` turns −0.0 into 0, −180 reads 180. Guard: `test_vb7_…`, `test_angle_range` (open at −180), the metamorphic mirrors modulo 360 |
| VB8 | LATENT. `v == (3, 4)` is True but `v == [3, 4]` is False (`+` takes both); the docstring says `__eq__` takes an Attribute, which compares False | `Vec2(3, 4) == [3, 4]` | `__eq__` tests `tuple` only | — | `__eq__` takes a list as a tuple; the docstring names what compares (Vec2, pair, a Point answering for itself). Guard: `test_vb8_…` |
| VB9 | Decided 2026-10-17: in place (CHANGELOG Breaking). `v += w` changed the vector (aliases followed), `v *= 2` rebound the name to a new one (aliases kept the old value); a linked or computed vector was replaced by `*=` instead of refusing | `a = v; v *= 2; a` | Vec2 had no `__imul__` / `__itruediv__` | The ink matrix listed `*=` as "a new vector, assigned back" | `__imul__` / `__itruediv__` through `_scale_in_place` and `_store_xy` (refusals, then one store). The store on a vector off the graph became direct (sync, or the holder hook), which made the in-place ops on free and held vectors 2–14× cheaper. Guard: `test_vb9_…`, the door matrix's `*=` / `/=` rows, `TestInPlaceSpellingsComplete` |
| VB10 | Decided 2026-10-17: refuse (CHANGELOG Breaking). `v += point` / `v -= point` took a Point as a displacement and `v - point` gave a Point at v − p, while `v << point` refuses ("a Point is a place") and `v + point` is the place moved | `v = Vec2(1, 2); v += Point(3, 4)` | `__iadd__` / `__isub__` / `__sub__` had Point branches; `_vec_operand_message`'s Point words were unreachable | `test_vec2_inplace_guards` and `test_ephemeral_math` pinned the Point operand | `+=`, `-=`, `-` raise with the place-vs-displacement words (`p - v` for subtract); `v + p` and `p + v` stay. Guard: `test_vb10_…`, both pins now assert the refusal |
| VB11 | LATENT. API edges: `clamp_length(10, 1)` (min > max) is not refused; `lerp` refuses a pair where `dot` / `cross` / `angle_to` take one; the docstring and an `@overload` advertise `Vec2(x=1)`, which raises; `v / 0` is Python's `ZeroDivisionError`; `reflect` about a zero normal returns the vector unchanged, silently | `Vec2(3, 4).clamp_length(10, 1)` | — | — | `Vec2(x=1)` fixed: the x-only `@overload` and the docstring's hint are gone, and the refusal says "Vec2 takes x and y together" with both spellings (no new spelling; guard `test_vb11_…`). The rest open (API edges). `v / 0` pinned in `test_vec2_algebra` |
| VB12 | ACADEMIC. `length` overflows past `1.3e154` (`sqrt(x*x + y*y)`): `Vec2(1e200, 0).length` is inf and `normalize()` gives (0, 0); below `1e-154` a non-zero vector has length 0 | `Vec2(1e200, 0).length` | No `hypot` | Strategies stay within `1e6` | Open: `math.hypot` changes the last bit of many lengths (A/B and the exact twins first) |
| VB13 | Python messages from the operand's inside and from scalar arguments: `v + ("a", 1)`, `v += ("a", 1)`, `v.lerp(w, "a")`, `v.clamp_length(None, 5)`, `vec_from_angle(30, 1, (1, 0))` (`AttributeError`: no `.angle` on a tuple) | `Vec2(1, 2) + ("a", 1)` | The operators checked the pair's shape and bools, not its numbers; `lerp` / `clamp_length` used `float()` / comparisons; `reference_vec` was read as a Vec2 | A18 covered `v + "a"`, not a pair holding a string | Scena's words; `reference_vec` takes a pair (as `dot` does). Guard: the algebra's junk × every operation, with a completeness check over the public methods |
| VB14 | `abs_angle_to` read 1.2e-6° between a vector and itself, while `angle_to` read 0 | `v = Vec2(971385, 511321); v.abs_angle_to(v)` | `acos(dot / (‖a‖ ‖b‖))` is ill-conditioned near 0 and 180 | No property compared the two | `abs_angle_to` is `atan2(abs(cross), dot)`: one formula with `angle_to`. Guard: `test_angle_to` (`abs(angle_to) == abs_angle_to`) |
| VB15 | Messages. `ship.vel << (nan, 0)` says "a point takes…"; `dead.vel = (5, 5)` says "Circle.set cannot change…"; a dead `vel += (inf, 0)` raises the finite `ValueError` before `DestroyedError` | `dead.vel = (5, 5)` | `_finite_xy` speaks for points; the dead route's setter passes `"set"`; `_store_xy` reached the finite check before the x write's dead check, and `+=`'s operand errors and `do_rotation`'s angle check come before it too | Nothing read a refusal's words on these doors | `<<` refuses NaN / inf in a vector's words (`_vec_overflow_message`; every vector since VB4, a part before); `_DeadRoute.get` gives a `_DeadSetter` carrying the name; `_refuse_if_dead` runs first on every refusal branch of `+=`, `-=`, `do_rotation` and `_store_xy` (a living finite store pays nothing). Guard: `test_vb15_…` (every op × warm / cold cache; a sweep of routed names) |
| VB16 | Inside an `@on_change` / `@when` callback, `v += w`, `v -= w` and `v.do_rotation(a)` left a `length` / `angle` already read stale on every vector off the graph (free, arithmetic result, an st cell's or ink field's vector): `v.length` read the value from before the op | `v = Vec2(1, 2); v.length`; in a callback `v += (3, 4); v.length` → 2.236 | In a flush the batch exit skips `update()` and marks the vector dirty by node id (`mark_dirty(self._node_id)`); off the graph that id is None, so nothing was marked | The quick tier's 2-wise array covered every pair of (kind, context, read), never the triple (free, callback, warm); the gate's full product found it | Off the graph, the batch exit syncs the computed fields (`_sync_computed`). Guard: `test_every_context_one_operand` (every kind × door × context × read, quick), `test_vb16_…` |
| VB17 | (found 2026-10-20 by `test_hyp_vec2_machine` in the gate, after SV12) A vector a holder let go of kept a `length` / `angle` read while it was held: after `v.x = 0` they disagreed with x, y. Since 2f97547 for every st cell, before that for a watched ink field | `st.a = v; v.length; st.a = Vec2(1, 3); v.x = 0; v.length` → 2.236 | `_hold_payload` sets the pull flag and records that it did (`hook.flagged`); `_unhold_payload` cleared it when the vector had no link, node or link source, but the `length` read had made the flag sticky (`_flag_pull_consumers`) and stored the value, which only `update()` re-syncs | The door matrix writes on a fresh subject; the let-go needs a history (hold, read, let go, write). The machine found it once SV12 put the flag on every cell | `_unhold_payload` keeps the flag while `_derivate_state` is set (unhold path only; `st.pos.x =` A/B +0.5 %, within noise). Guard: `test_ink_held_payload.TestLetGoVectorKeepsLengthInStep` (cell and watched ink field × `.x =` / `.y =` / `.x +=`), `test_hyp_vec2_machine` |

### PP — persona probes, round 1 (2026-10-20)

Found by the [persona probes](#persona-probes) (two blind campaigns on
b5054b0; merged by mechanism: A and B shared PP3 and PP4). Fixed on main
after both campaigns were triaged (0aa24d4, 6e4cfaa, 4bf362d, 6c10428).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| PP1 | BUG. `Color` had identity `==`: `Color("red") == Color("red")` False, `c.color == "red"` False; a memory game or a shop comparing colours never matched; `print(c.color)` showed an address | `card.color == Color("red")` | No `__eq__` / `__hash__` / `__repr__` on an "immutable RGBA" value | Every test compared `.rgb` tuples | Value equality and hash at the name table's precision (3 decimals), the other side any `color=` spelling, a near typo warns once, repr = str. `test_color.TestColorEquality` |
| PP2 | BUG. `Text.text` was the cell: `t.text.endswith("1")` False in the frame `t.text == "Pontos 1"` was True; not hashable, not joinable | `t["text"] @= lambda: f"Pontos {st.p}"`; `st.p += 1`; `t.text.endswith("1")` | `ContainerSlot(Attribute)`; `Attribute.__getattr__` read `_raw_value` (stale until `.value`) | A test pinned `isinstance(hud.text, Attribute)`; reads always went through `==` | `ValueSlot`: `t.text` reads a str (`TextValue`, old spellings raise with the bracket fix; Breaking); `slot.cell()` for the engine; cell methods read fresh. `test_text.TestTextReadsAsStr`, `TestCellMethodsReadFresh`, class guard `TestEngineReachesCellsThroughTheSlot` |
| PP3 | DECISION, applied. `@click(group["x"])` wired the members of the moment; `@collide` on the same tag follows it, so a rebuilt board and an act's own objects were dead | top-level `@click(group["bichos"])`, members made in `Act.setup` | `_collect_targets` snapshot | Tests decorated after making the members | Tag rules (`interaction._TAG_RULES`, registry hook, act scope). `test_shape_interaction.TestGroupDecoratorsFollowTheTag`, `test_act.TestPointerTagRulesLeaveWithTheAct` |
| PP4 | ERROR. An unknown read gave Python's bare words, or `Did you mean: '_tick'?` | `chave.hide()`, `bola.transform`, `clock.tick(60)` | `_ink_read_slow` raised plain; Clock had no `__getattr__` | Writes had near-miss hints; reads none | `_UnknownRead` (lazy), `_FOREIGN_READS`, `Clock._FOREIGN`. `test_read_hints` |
| PP5 | ERROR. Shape `.alpha` refused without `set_alpha`, inviting an ignored own field | `circle.alpha = 0.5` | Generic reserved-name tail | Message tests checked the family only | `_OTHER_KIND_API`. `test_read_hints.TestEntityReads.test_a_field_another_kind_owns` |
| PP6 | ERROR. `move_to(1, 200, 100)` (Scratch's glide) gave "takes from 1 to 3 positional arguments", counting `self` | as written | Python's arity check runs first | — | `*extra` on the six pose verbs and the timed wrapper, `_time_by_name`. `test_read_hints.TestPositionalTime` |
| PP7 | ERROR. A `while` in `update` froze the window, no message | `while not keyp("SPACE"): pass` | Sync line watchdog off by default (cost) | The Actors Design row said the watchdog skips `update` | `scena/stall.py` (frame stamp + thread). `test_stall` |
| PP8 | ERROR. A script with no `run()` exited silently | no `run()` line | Nothing checks | — | `stall.note_script_import` (atexit). `test_stall.TestEndedWithoutRun` |
| PP9 | ERROR. A top-level `def on_click(x, y)` was never called, silently | as written | Only exact top-level names are hooks | — | `_top_level_near_misses` at `run()`. `test_class_hook_names.TestTopLevelNearMisses` |
| PP10 | ERROR. Unity hooks in a class (`Update`, `OnTriggerEnter2D`) were helpers to the check | `class Hero(Circle): def Update(self, dt)` | The foreign table was snake_case only | — | `_FOREIGN_ENGINE_HOOKS`: a warning, silent when the file calls the method (the first fix refused, and broke the refugee's `player.Start()` games: R row PP10-R). `test_class_hook_names.TestOtherEnginesHookNames` |
| PP11 | ERROR. `TextInput(on_submit=run)` said "Write run(bola)" | a renamed snippet function | The act check ran first | — | `run()` refuses inside the game first. `test_act.TestRunInsideTheGame` |
| PP12 | ERROR. Several wrong hook names cost a run each | `update` + `on_key_down` in one act | The check raised on the first | — | One error, every name, its line. `test_class_hook_names.TestEveryOffenderAtOnce` |
| PP13 | DOC. `@on_change` compares once per flush; the Guia said "every time the value changes" | `st.msg = ""; st.msg = "go"` | By design (F1 / F3) | Untested promise | Guia note; `test_reactive_edge_cases.TestOnChangeComparesOncePerFrame` in `FRAME_PROMISES` |
| PP14 | DECISION, kept. Equal cells edge to edge touch (a snake's head and neck on frame 1) | two 30-wide Rects 30 apart | Strict AABB test; resting contact needs it | — | Guia note (Colisão: make grid cells 1–2 units smaller) |
| PP15 | DECISION, kept. A bulk op on a tag nobody joined is a silent no-op | rename a tag in one place | Any name is a valid empty group | — | Guia note (Grupos); the near-name warning already exists |
| PP16 | DECISION, kept. `await wait(p)` in a loop runs at least `p` apart, frame-rate dependent (law T2) | Scratch "forever: move; wait 0.02" | `wait` starts at the next tick on a whole frame | — | Guia note (Tarefas): `dt` or `@every` for speed |
| PP17 | DECISION, applied. CSS names went to the nearest name or magenta | `"beige"`, `"midnight blue"` | Short table | SR4's literal scan covers the repo only | CSS base names; Guia swatches held to the table (`test_color.TestCssNames`) |
| PP18 | DECISION, applied. A formula reading inside a container in `st` misses in-place changes | `f"Gemas {st.inv['gemas']}"`; `st.inv["gemas"] += 1` | One object per cell | Documented only | Link-time warning (`formula_check._warn_container_read`), once per cell and only when the file changes it in place (PP18-R). `test_formula_functions.TestContainerItemLinks` |
| PP19 | DECISION, kept. The frozen-mode warning fires for a rest mode waiting for a click and for a director whose body ended | a card in `fechada` waiting for `on_click` | Idle = nothing pending (AC7) | — | Guia note (the warning explained) |
| PP20 | DECISION, kept. The leak detector warns on legitimate spawn ramps, repeatedly | survivors-style ramp, cap + destroy | A climb heuristic; wall-time samples | Harness runs faster than real time (over-counts) | Guia note. `set_leak_detector` is not exported |
| PP21 | DECISION, kept. Formula refusals of a `for` helper and `len(group)` | idle-game number format | Link-time static reads (by design) | — | Messages name the fix; kept |
| PP22 | ACADEMIC. A grazing rotating contact flickers at one rate; author timers drop their remainder | — | Per-frame rotation sampling; author code | — | None (Guia row on `cooldown -= dt`) |
| PP4-R | R (of PP4). An unknown read printed as `_UnknownRead (scena.entity)` in a traceback, and `nivel` got "Did you mean 'vel'?" | `chave.hide()`; an own field never set | The lazy error class kept its own name; cutoff 0.75 | The tests read `str(e)`, never the traceback | The class reports as `AttributeError` (builtins); cutoff 0.8. `test_read_hints.TestEntityReads.test_a_traceback_names_attribute_error`. Found by re-running the round-1 probes on the round-2 commit |
| PP10-R | R (of PP10). The Unity-name refusal broke working games that call `Start()` / `Update(dt)` themselves | `def Start(self)`; `player.Start()` | A refusal where the name may be a helper | No test called the method by hand | Warning, silent when the file calls it. `TestOtherEnginesHookNames.test_a_method_the_file_calls_itself_is_a_helper` |
| PP18-R | R (of PP18). The container warning fired for code that only reassigns (four times, one per button) | `label=lambda i=i: st.rotulos[i]`; `st.rotulos = novos` | Link time cannot see how the cell is written | The test changed the cell by reassigning | Only when the file changes the cell in place; once per cell. `TestContainerItemLinks.test_a_list_only_reassigned_says_nothing` |

### R2 — persona probes, round 2 (2026-10-20)

Found by the [persona probes](#persona-probes), round 2 (blind, 4220f07;
A and B shared R2-3). The re-run of round 1's probes on the same commit
found PP4-R, PP10-R and PP18-R ([PP](#pp--persona-probes-round-1-2026-10-20)).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| R2-1 | BUG. A `bounce=0.5` ball with sideways speed was glued to the floor at ≥ 144 Hz after its first bounce, sliding at y = 120 with `vy` +210 | ball `vel=(300, 0)`, gravity by hand, `resolve(ball, floor, bounce=0.5)`, 144 Hz | The walker leave gate needs 2 DU of separation per frame (`vy · dt`) or a step 0.85 straight off; sideways speed lowers the second. The elastic rule (`> 0.5`) trusted speed only above 0.5 | Bounce tests ran at 60 Hz or with `vx = 0`; the high-FPS fix covered `bounce > 0.5` | A body a real bounce (`bounce × approach > 8`) just sent off leaves, at any rate (`_note_bounce` in every velocity response; Collision Design, leave gate). `test_resolve_solver.TestBounceLeavesAtEveryRate` (30–240 Hz; a soft walker on a slope stays grounded) |
| R2-2 | BUG (contacts). A body placed right behind a fast traveller got `@collide` enters and exits every other frame at 30 Hz, none at 60 | `a.move_by(0, 450 * dt)`; `b.center = a.center + Vec2(0, -25)` (or `@=`) | The pair sweep used motion only: the placed side stood at its end pose all frame, where the traveller had been | Swept tests moved the partner by `move_by` or not at all | A placement on the scale of a frame's travel is the partner's motion in the pair sweep (`_placement_of`, end centers stored for moved colliders); a teleport stays unswept. `test_collision.TestSweptAgainstAPlacedPartner` |
| R2-3 | DOC (both campaigns). The Guia's "De outro motor" rows (round 1) said `obj.vel = (vx, vy)` makes Scena move the object | `ball.vel = Vec2(400, 0)`, no `update` | Written from the round-1 note "vel is every actor's velocity" without checking the engine: nothing integrates `vel` | A Guia row is prose | Rows corrected (`move_by(vel.x * dt, vel.y * dt)`; `vel` is what `bounce=` reads) |
| R2-4 | ERROR. `Button("Contar")` was told to pass a cell | as written | `_require_bound` had no caption hint | — | Names `Button(label="Contar")` (also CheckBox, Slider). `test_state_reads_value.TestBindingSitesTakeTheCell.test_a_caption_given_as_the_cell_names_label` |
| R2-5 | ERROR. `intersections(line, track)` gave no route for a curve | a plotted parabola as a Track | The allow-list message only | — | Names `spaced_points` and a Line per pair. `test_read_hints.TestIntersectionsOfACurve` |
| R2-6 | ERROR. Godot's `_process` / `_ready` in a class were silently never called | `def _process(self, delta)` | `_FOREIGN_ENGINE_HOOKS` listed Unity only | — | Godot names in the table (a warning, as Unity's) |
| R2-7 | ERROR. `paddle.position = …` became an own field while the read named `.center` | `r.position = Vec2(40, 300)` | The write table had no pose words | — | `position` / `global_position` / `rotation` / `rotation_degrees` refuse on a kind with a pose (a bare Entity keeps them). `test_read_hints.TestForeignPoseWrites` |
| R2-8 | ERROR. `every(0.6, spawn())` returned the decorator silently | as written | `None` was the decorator sentinel | — | `NO_FN` default; an explicit `None` raises. `test_read_hints.TestTimerGivenACall` |
| R2-9 | ERROR. `self.mode = self.phase2()` ran the body as a helper and left the mode `None` | a boss's phase change | `@on_mode` was a pure marker | — | A sync body runs only when the engine enters it. `test_read_hints.TestModeBodyCalledByHand` |
| R2-10 | DECISION, applied (2026-10-20). The Guia said an act never subclasses an act; the engine accepts it, and it works | `class Chefe(Fase)` | An unenforced "never" | — | The Guia and Act Design document what runs once; `test_act.TestAnActMaySubclassAnAct` |

### R3 — persona probes, round 3 (2026-10-20)

Found by the [persona probes](#persona-probes), round 3 (blind, fe00fda;
A and B shared R3-3).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| R3-1 | DECISION, applied (user, 2026-10-20). A destroyed actor's own field raised on read (`inimigo.valor`), while built-in fields read and the Guia said "dá para ler": a second handler of the contact (C3) crashed | two `@collide` handlers, the first destroys, the second reads | The documented rule "Ink reads still raise"; teardown clears the ink | `test_api_robustness` pinned the raise | A plain copy at teardown (`_dead_ink`) reads; writes refuse; a `@when` made on a dead source retires (`events._condition_reads_dead`). `test_collision.TestASecondHandlerReadsTheDeadBody` |
| R3-2 | BUG. At 60 Hz a mover ending a frame in the resting skin of a resting movable box bounced off it as off a wall; the box never moved, masses ignored | equal 60×60 boxes, `a.vel = (200, 0)`, `resolve(a, b, bounce=1)`, start x 100 | `_answer_unreached` (LW8) skipped a partner only when it moved | LW8's tests used bricks with no `.vel` | A partner with a `.vel` and a finite mass is the next sweep's (the mass split). `test_resolve_solver.TestARestingMovablePartnerIsNotAWall` |
| R3-3 | DECISION, applied (both campaigns). A pose retarget warned "replaces a previous in-flight handle", located in `shapes.py` | `move_to(cell, time=0.06)` on each fast key; a hover lift and exit | `_preempt_tween_keys` warned on every same-kind replace | — | Timed pose verbs quiet; a tween still warns, at the author line, naming `name=`. `test_driver_composition.TestPoseRetargetIsQuiet` |
| R3-4 | ERROR. `change_act` after a plain `run()` said "start with run(Fase)": the title screen was lost | a title at the top, `change_act(Fase)` on ENTER | The hint named the target | — | Names a first act (`run(Titulo)`). `test_act.TestRestrictions.test_change_act_after_plain_run` |
| R3-5 | ERROR. A missing `st` cell after a half rename said "create it first"; the second try made a dead cell | `st.placar` renamed, `st.pontos += 1` left | No close name, no list | — | Lists the cells; "if renamed, use its new name". `test_read_hints.TestMissingCellAfterARename` |
| R3-6 | ERROR. A false "Did you mean 'tiros_inimigos'?" for a class keyword group before its first member | `class Inimigo(Rect, group="inimigos")`, `@when(lambda: group["inimigos"].empty)` | The near-miss guard did not know class keywords | — | `group_name_known` scans class defaults on a miss. `test_read_hints.TestAClassKeywordGroupIsKnown` |
| R3-7 | ERROR. `self.vel = 150` said "physics motion" | as written | Generic text | — | Names another name and that nothing moves by vel. `test_read_hints.TestVelGivenANumber` |
| R3-8 | ERROR. `box=None` did not say None | `Rect(box=grid.cell_at(0, 0))` | Fixed text | — | Says None, names `grid.cell`. `test_read_hints.TestBoxGivenNone` |
| R3-9 | ERROR. `"#222"` lost the reason | as written | The parser's reason dropped | — | 6 or 8 digits, spelled out. `test_color.TestShortHexWarning` |
| R3-10 | ERROR. `Level()` on one's own JSON led toward forging an editor file | a hand map | Field-by-field checks | — | Names `json.load`; a format tag with no version says "not an editor file". `test_read_hints.TestRoundThreeMessages` |
| R3-11 | DECISION, kept. A pause set during a frame starts at the next | `clock.paused = True` in `update` | This frame's dt is taken | — | Guia note; `test_reactive_edge_cases.TestPauseStartsNextFrame` |
| R3-12–15 | ERROR. `addEventListener` / `apply_impulse` reads; `Circle(mass=, bounce=)`; `resolve(friction=)`; `Text(lambda)` named `@=` | as written | No table for these words | — | `_FOREIGN_READS`, `_FAMILY_KWARG_HINTS`, `resolve` with a published signature, the no-sources text. `test_read_hints.TestRoundThreeMessages` |
| R3-16 | DOC. Stacks of 3+ movable boxes are outside what resolve promises (P1); the Guia did not say | `phys_stack1` | — | — | Guia note (Colisão, resolve) |

### R4 — persona probes, round 4 (2026-10-21)

Found by the [persona probes](#persona-probes), round 4 (blind, c7e8626;
no overlap between A and B).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| R4-1 | BUG (user, 2026-10-21; the triager said DECISION). A timer as long as a tween made with it saw the tween one step short (295 / 297.5 / 298.96 at 30 / 60 / 144 Hz); a same-field move started in it replaced the first in flight, whose `on_done` never ran | `move_to(300, 100, time=2, on_done=…)`; `after(2, nxt)`; `nxt` moves the same field | `Scheduler.tick` walked `_every`, `_once`, `_tween`, `_await`; Scena Design's frame order said tweens first | No test made a tween and a timer of one length together; the timers model abstained on tweens | Tweens tick first; Laws T1 says so, its model checks the order (the recorder hooks `_tick_tween`; plant `t1_timers_before_tweens`). `test_process.TestATweenEndsBeforeATimerOfItsLength` (move / rotate / st tween × after / every × 4 rates × lengths), `test_laws_timers` (fixture, traces, canary) |
| R4-2 | ERROR. `Rect(visible=False)` named no fix | as written | No hint for `visible` | — | The hint names `obj.visible = False` on the next line. `test_read_hints.TestRoundFourMessages` |
| R4-3 | DOC. The Guia said "Crie no topo com visible=False" and listed `visible=` among constructor keywords | the Atos table; the constructor note | — | — | Both sentences say `obj.visible = False` |
| R4-4 | ERROR. A `move_by` game with `resolve(…, bounce=0)` was told to set `.vel`, on its STATIC wall too | hero by `move_by`, STATIC wall | `_warn_missing_vel_once` named both bodies, any bounce | — | Silent for STATIC and for `bounce=0`; otherwise "Drop bounce=, or set .vel". `TestRoundFourMessages` (fires and silent twin) |
| R4-5 | DECISION, applied (user, 2026-10-21). An act's own named work (`self.every(…, name=)`, `self.play_sound(…, name=)`, a loose `every` with an act method) ran beside the stage's same-named handle; two tracks played | stage `every(1, f, name="relogio")`; act `every(0.5, self.tic, name="relogio")` | The act object is the owner, so another slot; the shadow step ran only for ownerless act work | Each rule was tested alone | `Scheduler._shadow_game_slot` pauses the game handle, and the act change gives it back (`setdefault` keeps the author's pause). `test_act.TestNamedSlotsAcrossTheSeal` (four doors, music, author pause) |
| R4-6 | DECISION, kept. `on_update` runs at dt = 0 while paused, so `keyp.once` there acts during a pause | `clock.paused = True`; a key read in `on_update` | Pause scales time, not input | — | Guia note on the `clock.paused` row: `if clock.paused: return` |
| R4-7 | DOC. The Guia's st table wrote `st.keys` without the call | `for k in st.keys` | — | — | `st.keys()` |

### R5 — persona probes, round 5 (2026-10-21)

Found by the [persona probes](#persona-probes), round 5 (blind, 872a78c;
no overlap between A and B).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| R5-1 | BUG. A `crossfade=` replace ran the old named sound's `on_done`, even on a `forever` loop; without `crossfade=` nothing ran | `play_sound(A, name="m", loops="forever", on_done=f)`, then `play_sound(B, name="m", crossfade=1)` | The crossfade ramped the old voice with the public `fade_out`, whose end is natural | `test_crossfade_two_ramps` asserted the old voice `done`, not cancelled | `Handle._ramp_out(natural=False)` ends it as a slot cut (`_R_NAME`). `test_audio.TestFades.test_crossfade_ends_the_old_voice_as_a_cut` (forever and finite × crossfade 0 / 0.3 / 1) |
| R5-2 | BUG (Breaking fix, user 2026-10-21). `CheckBox.checked` returned the `Attribute`: `json.dumps` raised, `is True` was False | a settings screen saving its boxes | `_DataAlias` returned `data` on purpose, for `@=`; every other widget name reads the value (PP2's rule) | The alias test asserted the identity | `_ValueAlias` reads the value; the cell is `box["checked"]`; the old spellings raise from an AST scan of the author file. `test_uiwidget.TestCheckBox` (value, JSON, cell link, old spellings, class guard over every widget alias) |
| R5-3 | DECISION, kept. A formula with a generator over a list cell is refused | `"\n".join(… for n, p in st.ranking)` | Reactive Design refuses comprehensions | — | The message names `update()` |
| R5-4 | DOC. `Menu(box=)` "Preenche a caixa": the options stay text-sized in the middle | a click in the left third | — | — | The Guia row says the panel takes the box |
| R5-5 | ERROR. Limits did not name the value they got | `every(60 // 120, f)`, a one-level `Slider` | Fixed texts | — | "got 0" and the `//` hint; `test_read_hints.TestRoundFiveMessages` |
| R5-6 | ERROR. `RegularPolygon(sides=5)` offered `side=`, the edge length (following it was silently wrong) | as written | The spelling matcher | — | A family hint names `n=`; `TestRoundFiveMessages` |
| R5-7 | ERROR (a new warning, user 2026-10-21). `on_collide` never met a plain `Rect` bullet, silently | an Alien class with `on_collide`, plain bullets | `ANYTHING` reaches enrolled bodies only (design) | — | `CollisionSystem._check_on_collide_alone`, once, a second in; Guia line. `test_read_hints.TestOnCollideWithNoPartner` (fires and silent twin) |
| R5-8 | DOC. A self re-arming `after` drifts; the Guia promised a rate | invaders that speed up | Laws T2 ("at least p") | — | The Guia's timers paragraph names the exception and `every(…, name=)` |

### R6 — persona probes, round 6 (2026-10-21)

Found by the [persona probes](#persona-probes), round 6 (blind, bbc094e;
no overlap between A and B; no BUG).

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| R6-1 | ERROR. A timer, `every` or `on_done=` callback that needs arguments was accepted, then failed at the fire inside the engine, with no author line | `after(0.8, ia_joga)`, `def ia_joga(peca, casas)` | Hot calls skipped the registration check that decorated handlers have (`check_handler_arity`) | No test gave a timer a callback with more parameters than its payload | `_refuse_overfull_callback` in `Handle._init` (the kinds whose `fn` is a callback, and every `on_done`), naming the lambda; A/B within noise. `test_process.TestACallbackThatNeedsArgumentsRaisesWhereItIsGiven` (5 doors, plus what fits) |
| R6-2 | DOC + ERROR (user, 2026-10-21: warn). A group member on a parallax layer never collided, silently; the Guia's error table said it raised | coins with `group="moeda", layer="frente"` (parallax) and `@collide("heroi", "moeda")` | S9-1 skips the member, order-independent | — | `CollisionSystem._warn_member_skipped`, once per (tag, layer), either order; the Guia row tells naming apart from a group. `test_read_hints.TestAGroupMemberWithNoBodyIsNamed` |
| R6-3 | DECISION, documented. A 2-parameter `@drag_to` function gets `(from, to)`, so a parameter named `pos` holds the target | `def soltou(carta, pos)` | Positional payload (documented) | — | Guia line in the `@drag_to` row |
| R6-4 | DECISION, documented. Moves chained by `on_done` lose each overshoot; a hop chain's pace depends on the rate | `move_by(…, time=0.12, on_done=next_hop)` × 5 | T2: work made in the tick counts from the next | — | Laws V1 known limits, the Clocks row, the Guia's timers paragraph (`move_along` on a Track) |
| R6-5 | ERROR. An unknown layer offered only `below="default"` (behind), for a card meant to be on top | `carta.layer = "cima"` | Fixed template | — | Both placements; `test_read_hints.TestRoundSixMessages` |
| R6-6 | ERROR. `Text(wrap=True)` listed `width` as valid and never said Text does not wrap | as written | No hint for layout words | — | `wrap` / `word_wrap` / `max_width` / `multiline` hints; `TestRoundSixMessages` |

### DV — a destroyed actor refuses first (2026-10-17)

Found after VB15 (the same order bug on Vec2's in-place ops): a probe of the
shape verbs, then the sweep `tests/test_dead_verb_order.py`. The rule: a verb
or setter that refuses a destroyed actor with good arguments refuses it with
any arguments; the death is the author's first problem.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| DV1 | On a destroyed actor, a bad argument or value raised its own error before `DestroyedError`: `move_to` / `move_by` (also with no argument), `rotate_to` / `scale_to` / `rotate_by` / `scale_by` (`force=`, the value, the timing keywords), `reset_rotation`, `move_along`, `add_to_group`, `goto_mode`, `tangent_lines_from`, every subclass pose override, and every setter given a function (`dead.radius = lambda: 3` said "use @="). The author chased the number when the actor was gone | `c = Circle(); c.destroy(); c.move_to((math.nan, 0))` → "a point takes two finite numbers" | The verbs parsed their arguments, then called `_refuse_if_destroyed`; `__setattr__` refused a callable before the dead route map | P6 accepts any author error from a dead verb (it asks for no trace, not for the order) and calls each verb with good arguments only | `if self._destroyed:` as each verb's first statement (`_refuse_dead_verb`: instant → refuse; timed → on to its cancelled Handle, DV3) and at the head of `_install_timed_pose`'s wrapper (the overrides' own checks removed); `__setattr__`'s callable branch skips a dead actor. A/B vs HEAD, 12 interleaved rounds: moves 3–6 % faster (one call fewer), turns and scales flat or faster. Guard: `test_dead_verb_order` (every Entity kind × every refusing verb and setter × each parameter × ten junk values; a parameter that picks a path that does not refuse, such as `time=` on a turn, is P6's) |
| DV2 | A read on a destroyed Track refused: `at`, `local_at`, `tangent_at`, `angle_at`, `sample_span`, `spaced_points` raised "Track.length cannot change a destroyed object" while reads stay legal elsewhere | `t = Track(); t.destroy(); t.at(0.5)` (a track whose tables were never built, or were dirtied before the destroy) | The first read builds the tables, and the refresh published `length` through the public setter, which the dead route map refuses (`_refresh_length`) | P6 accepts `DestroyedError` from any method; DV1's sweep excluded these reads by name | Fixed: on a dead track the refresh stores `length` in the instance (nothing listens to it), so every read, `length` included, matches a live twin. Guard: `test_dead_verb_order.TestADeadTrackStillReads` (cold and dirtied, three kinds of track); the sweep's exclusion is gone |
| DV3 | Timed pose on a destroyed actor: Actors Design said a cancelled Handle (law T6), and so did the timed moves and turns, but every timed `scale_to` / `scale_by` and a Point's timed `move_to` / `move_by` / `move_along` raised `DestroyedError` | `c.destroy(); c.scale_to(2, time=1)` raised; `c.move_to(5, 5, time=1)` was a cancelled Handle | `_refuse_dead_verb` ran the timed helper's call-time probe, and the probes (`_probe_scale_writable` → `_scale_gate_at_call`, a dead Point's `_move_by(0, 0)`) refuse a dead subject | DV1 kept today's split on purpose; nothing asked the timed verbs for the documented Handle | Fixed (the doc's rule, 2026-10-24): `_refuse_dead_verb` refuses only an instant call; the timed helpers skip the probe (and the scale's claim targets) for a dead subject, and the scheduler returns the Handle cancelled (`_R_DEAD_AT_START`), never registered; `move_along` returns it before an anchored track's start snap (RA3-1). Guard: `test_dead_verb_order.TestATimedVerbOnTheDeadComesBackCancelled` (every Entity kind and Point × every timed verb; an instant call still refuses) |

### EX — building the Corrida example (2026-10-21)

Found while writing `examples/corrida.py`: the road is the track's centre line
made thick (`line_width=112`, `group="asfalto"`) and hidden, asked with
`collision.query_point`. Bug class: **hiding a shape changes its lifetime**.

| ID | Finding | Repro | Cause | Why tests missed it | Fix / guard |
| --- | --- | --- | --- | --- | --- |
| EX2 | Seen from above, `resolve` glued a body to a wall under it, carried it on a barrier sliding under it and slid it less down a slanted wall under it: five rules of a world with gravity (floor snap, rider carry, seam step, stop-on-slope, no bounce off the starting floor) read the `"bottom"` side as feet in every world. The race's cars felt "grabbed" by walls | `resolve(car, wall)`, wall under the car, `car.vel = Vec2(200, 40)` each frame: `y` stays put; a barrier under a body sliding 120 DU takes it 116, at its side 97; a 30° wall under a ball slides it 33 DU, at its side 47 | The rules were written for walkers (Collision Design, Floor snap) and the engine cannot see an author's gravity | Every resolve test had gravity or a ball with `bounce=`; no law said a world without gravity has no down | Decided and applied 2026-10-21: `collision.floor`, default `False` (a world with gravity writes `True`; Breaking in CHANGELOG); `floor_below` / `tilt = "ground"` without a floor say so once. Class guard: law V10's rotation half, equation E16 on `tests/laws/twins/topdown_world.py` (five scenes x 90 / 180 / 270 degrees, the floor as its canary); `test_collision_floor`. The gravity tests run with a floor (`tests/floor_support.py`) |
| EX3 | A `GearShell` on an open Track (a strip around a curve) painted a translucent triangle along the chord, over the road | `Track(points=quarter_arc, closed=False, visual=GearShell())` → the chord's inside is tinted | The force-field family has no "open polyline" kind (only `Line` is a line), so the Track took the closed-shape path, whose wash is a fill pass on the host geometry, and Skia fills an open path as if it were closed | Visual tests drew closed shapes, Lines and Sprites; no visual had been put on an open Track with a fill pass | `Track._geometry_draw` skips a visual's fill paint (an explicit `fill_paint=`) when the track is open; the author's `.fill` is unchanged. Guard: `test_track.TestOpenTrackHasNoWash` (pixel inside the chord: open → clear, closed → filled, GearShell end to end) |
| EX4 | A `SpriteButton` with `.glow` or `.shadow` on the `ui` layer (the default) drew no label and no hover / press feel: the chosen track's button glowed with no name on it | `b = SpriteButton(art, label="OK"); b.glow = True` → the button glows, the label is gone | `_draw_ui_objects` (orchestration) sent every object with a fill / line ImageFilter to `_draw_fill_only`, which paints the body alone; the world layers ask `_must_solo_draw` first and call `obj.draw` | `TestDrawRoutes.test_glow_takes_the_filtered_route` drove `_draw_layer_batched` (a world pass) only; no test drew a filtered button through the ui pass | The ui pass sends a `_must_solo_draw` object with filters to `o.draw` (with the engine's canvas pointed at the ui canvas, so `_draw_filtered_one` still renders the glow). Guard: `test_sprite_button.TestDrawRoutes.test_ui_layer_draws_a_glowing_or_shadowed_button_whole` |
| EX1 | A hidden styled Track was collected: its group emptied and every query missed, so every car drove at grass speed on the asphalt. A hidden `Rect` / `Circle` / `Line` stays. When it went depended on the collector (the track sits in a reference cycle), so the same game worked in one run and not in another | `t = Track(points=[(0, 0), (500, 0)], line_width=50, group="g"); t.visible = False; del t; gc.collect()` → `group["g"]` empty | `Track.visible = False` took a track built on a layer off it ("so the idle overlay does not scan it"), and the constructor put a styled `visible=False` track on no layer: off its layer, nothing holds a Track (the bare motion path rule) | The reclaim tests covered bare tracks and shown styled ones, never a hidden styled one; a game that keeps the track in a variable never sees it | A styled track keeps its layer while hidden (the setter only undoes a `visible = True` promotion; the constructor counts styling for the layer). Guards: `test_track.TestHiddenStyledTrackIsKept` (both ways of hiding; a forced `gc.collect()`; the query still hits), `test_example_corrida` (the asphalt, after a `gc.collect()`) |

### SH — showcase builds (2026-10-23)

Found while building fourteen showcase programs (the twelve in `examples/`,
`guardiao.py` and one more); every item was verified headless or in a
GL window (interleaved A/B, no perf regression) before a
change. Bug classes: **a value the bracket cannot reach**, **a world point used
on the picture without the camera's map**, **a draw cost that only a turned or
moving picture pays**, **a refusal that names no fix**. Commits on main
2026-10-23 ("Showcase findings, batch 1" … "Guia: Track points copy a Point").

| ID | Finding | Outcome | Cause / reason | Guard |
| --- | --- | --- | --- | --- |
| SH-A1 | A Track styled after construction stays invisible | By design; Guia `color` row says `visible = True` | Only constructor styling puts a track on a layer (its lifetime, [Tracks](Tracks%20Design.md)) | Guia |
| SH-A2 | Post `target=` / `center=` / `origin=` and the mouse ignored the camera and the letterbox | Fixed | Design coords mapped straight to the framebuffer (`_world_to_view`, `_view_to_fb`) | `test_post_targets_camera` |
| SH-A3 | `Track.wave(start=, angle=)` turned about its middle | Fixed | `start=` ignored the angle (`_line_center_from_p1`); a test had pinned the bug | `test_track.TestRotationCtor` |
| SH-A4 | `Track(points=callable)` said "needs at least 2 points" | Refused like Polygon; Guia row reworded | The list is fixed; each point links | `test_track` |
| SH-A5 | Shapes without `center=` ignore `set_origin("center")` | By design; Guia says "centre of the world" | The default is the design centre, in world coords ([Shapes](Shapes%20Design.md)) | Guia |
| SH-A6 | `fill_filter=Blur` dropped `.blend` | Fixed | The filter layer composited with srcOver | `test_filter_blend` |
| SH-A7 | Leak warning on parts that grow (a polygon given a side each wave) | Fixed | Graph counted parts, objects did not; now the live roster, and a roster-only climb warns only off screen ([Scena Design](Scena%20Design.md)) | `test_leak_detector` |
| SH-A8 | Scrolling / parallax layers never culled | Fixed | Exempt; now culled against `layer.view` | `test_cull.TestParallaxAndScrollLayers`, `test_diff_draw.TestCullIsConservative` |
| SH-A9 | A camera verb retargeted in flight warned (and a second `fade_to`) | Fixed | `_camera_tween` and sound fades never preempted their keys | `test_canvas.TestTimedCamera`, `test_audio.TestFades` |
| SH-A10 | Objects a pre-`run()` task makes survive `change_act` | By design (F2, L6); Guia and [Actors — Tasks](Actors%20Design.md#tasks) say so | | Guia |
| SH-A11 | A sound Handle's `.level` ignored `.volume` | Fixed | The voice meter read the source before its gains | `test_audio.TestAnalysis` |
| SH-A12 | Neon on two closed Tracks filled the disks | Fixed | The grouped pass filled every non-Line host | `test_look_group_body` |
| SH-B1 | `fx["amount"] @=` silently dead; `tween` raised "the field itself" (tutorial 23) | Fixed: SpatialFx float knobs and `Portal.angle` are ScalarSlots; a bracket moves a plain pre-construction value into ink | [Reactive — the bracket reaches the value](Reactive%20Design.md) | `test_fx_knobs` |
| SH-B2–B8 | Post / background brackets, `lerp` tuple vs Vec2, `Fire(color=)`, a read after a call in a formula, `await canvas.fade_out`, `change_act` in a pre-run task | Fixed (messages; `lerp` and the formula walk now work) | | `test_showcase_messages`, `test_lerp`, `test_formula_functions`, `test_act` |
| SH-B5 | A formula reading its own object gave the generic circular message | Fixed: parts and built-in fields get the AC14 limit with the right way out | | `test_fieldref.TestOwnSizeReadIsAKnownLimit` |
| SH-C | `line_cap="project"` drew butt | Breaking: `round` / `butt` / `square`, `"project"` raises | Reverse of Processing's PROJECT | `test_showcase_messages.TestLineCapNames` |
| SH-C | `Contrail(layer=)`, `mic.available` | Added | Parked until a sample needed it | `test_history.TestContrailLayer`, `test_audio_capture` |
| SH-C | `Plasma(res_scale=)` | Not added; the Guia note scoped to the backgrounds that take it | | Guia |
| SH-C | Declined requests (see [Fences](Fences.md)) | Track `visible @=`, shape `alpha` link, `Polygon(angle=)`, `fill=None` / `line=None` keywords, posts and backgrounds as fields, `.after()` on posts, `SpatialFx.fade_in`, Rect / Text bottom anchors, a `move_along` handle's `.u` as a source, a Track window reading its own `u` (AC14) | Each refusal names the spelling that works | `test_showcase_messages` |
| SH-C | `Track.star` radius link, `Contrail.visible` | Deferred until a program needs them | | |
| SH-D1, D2, D3 | Turned concave / thick paths slow (pose or camera); rotating Polygon ~10× | Fixed for paths ≥ 200 px on screen (`entity._draw_path` bakes the matrix); Polygon's vertex turn inlined; spinning thick strokes stay Skia's cost (MSAA parked) | Skia's slow route under a non-axis-aligned matrix ([Shapes](Shapes%20Design.md)) | `test_rotated_path_draw`, `test_polygon_turn` |
| SH-D4, D5 | A colour formula rebuilt both paints a frame; a resized gradient rebuilt its paint | Fixed: recolour / reshade in place (19 % a frame for 126 triangles) | [Effect System](Effect%20System%20Design.md) | `test_color_link_paint`, `test_gradient` |
| SH-D6 | Glowing captions off screen built a Glow a cull | Fixed (memo per glow); on-screen glyph glow ~20 µs a letter in GL, not the 1 ms reported | | `test_text.TestGlowMetricsFollowTheGlow` |
| SH-D7 | Track windows / lambda points | Windowed circles not reproduced (0.26 ms for 12 moving); window span by bisection; a Track built from Points cost 3× a tuple one (fixed: unlinked vertices keep their read cache). A growing `end` redraws a new path each frame (Skia's cost); lambda points re-read their formula every read (~3.5 µs a point a frame), by design: it catches fast-path moves, and a cache would need a write epoch on every write path | | `test_track` |
| SH-D8 | Track modifiers re-baked on the same values | Fixed | | `test_track.TestModifiers` |
| SH-D9 | Internal `getattr` probes took the slow ink path | Fixed (`state.probe_private`) | [Actors — Ink](Actors%20Design.md) | |
| SH-D10 | "Function-call formulas re-pulled every frame; a live Point in `points=` links" | Not reproduced: no re-run while still; a Point / Vec2 in `points=` is a snapshot (Guia row says so) | | |
| SH-D11 | Looks: Tracer on 16 big circles 4.6 ms (7.2 at zoom 2), ElectricBolt on one big circle 3.4 ms, ElectricField on a long track 2.3 ms; Rim / Gel cheap | Documented cost | A new path effect every frame (dash phase, jitter): Skia re-dashes and re-tessellates the outline; cost ∝ outline length on screen. Candidate fixes change the look (a cached dashed circle turned instead of a moving phase) | |
| SH-D12 | Other costs (a post ~1–2 ms at 2×, full-screen multiply, Rain, `.tail`, Starburst, hover while the camera moves, link creation ~130 µs a link) | Documented cost | Hover must re-test while the camera moves (what is under the pointer changes); link creation parses the formula once | |
| SH-E | GodRays defaults washed the picture out | Defaults 0.08 / 0.9 / 0.8 | 8 taps over the whole way to the light repeat bright objects ([Effect System](Effect%20System%20Design.md)) | |
| SH-E | Large `orbit` / `zigzag` faceted | Fixed: samples a loop by chord tolerance | | `test_track.TestModifiers` |
| SH-E | `wave_at` drew a hard grey line across the whole screen that read as a glitch on line art, and the line sat on nothing: the warp's crests moved *toward* the origin, on both sides of it, while the line marched one way | Fixed (2026-10-26): one front, `effects._wave_front(u, w, h)`, gives the warp ridge and the band their distance, width and length. The warp is one refracting ridge on the front (one-sided, outward, slowing); the band is soft light on it, faded at both ends. The shader runs only on the strip around the front (−70 % CPU raster) | The ripple shader's phase term `48·d − 18·(1 − p)` puts a crest at a *smaller* `d` as `p` grows; the band had its own formula. Lesson: an accent drawn over a shader warp takes its position from the function that places the warp | `test_postfx`: `test_wave_at_band_rides_the_warp_front` (old engine: warp centred on the source, half of it behind, band 60–125 px ahead), `test_wave_front_moves_out_and_slows` |
| SH-E | `zap_at(style="corona")`: a notch at the ring's seam; the small ring of the first frames came out mangled | Fixed (2026-10-26): `_corona_ring_points` gives each of the `n` vertices once; jitter is a share of the ring's current radius | The loop ran to `i == n` and drew vertex 0 again with another hash before `close()`; jitter was a share of the final radius (24 % of the young ring). The flat inner wash and the 12 facets (a "grey disk") are a look note, still open | `test_postfx.test_corona_ring_has_no_seam` |
| SH-E | Under Bloom, `"gold"` and `"orange"` read as yellow; `"deep sky blue"` reads cyan, a green lime | Open: look decision for the author | Bloom adds its glow inside the shape too, and the sum is clipped per channel: gold (255, 215, 0) → (255, 255, 0). Tone mapping is not needed: a clip that keeps the channel ratios (a runtime blender in place of Plus) kept every hue in a prototype | |
| SH-F | `Track.eight` drew height / 2 | Fixed: spans `width` × `height`; showcase eights halved | | `test_track.TestPresetSizes` |
| SH-F | `"x" in st` | Refuses naming `st.exists("x")` | One spelling | `test_showcase_messages` |
| SH-F | Transients only hide; the watchdog trips on a long building step; an `st` tween from a game task outlives `change_act`; a Text anchor read adds a Point | By design; Guia notes; the watchdog message names "build in pieces" | | Guia |
| SH-L | `Lamp(radius=, range=)` were post-image pixels (changed with screen and `post_fx_scale`); `Spotlight(range=)` ignored zoom | Fixed: design units mapped like positions (`_length_to_fb`) | | `test_post_targets_camera` |

### SL — a linked pose read before the geometry it rewrites (2026-10-26)

Found while moving the `xyz2` showcase into `examples/`: its claims test read
each square's `length` once the vortex had opened and got 21 where 300 was
due. Bug class: **a lazy value needs a dirty edge *and* a pull on read**
(lesson 6), on every name the pulled verb writes, not only the one D18 fixed.

| ID | Finding | Cause | Fix | Guard |
| --- | --- | --- | --- | --- |
| SL1 | `sq["scale"] @= lambda: st.k`; `st.k = 2`; `sq.length` read 50 (the last pull), `sq.scale` then 2 and `sq.length` 200. The same on every kind with a structural model: Rect / Square / Concave sizes and corners, Circle `radius` / `p1`, Ellipse foci, Line points, Polygon `perimeter_length` / `signed_area`, RegularPolygon / Triangle `radius` / `side` / `vertex`, Track `length` / `cursor`, Text corners. A formula reading `sq.width` stayed stale (`probe.radius` 5 where 20) until something read `scale` (draw, collision, `box`). A tangent Line with a linked `angle` had the same hole on `at_angle` / `p1` / `p2`. | A pose link drives `scale_to` / `rotate_to` through a `_PropertyAnchor` that writes only when pulled. D18 routed reads through the owner for a derived heading's driven parts only; a scale link had no route, and a source-only or relational anchor (`at_angle`, the tangent `p1`) returned before the route | One pull for the whole linked pose on Graphic (`_pull_pose_links`, replacing `_pull_heading`) before a structural resolve or Derivate materialization; a pose link marks the shape and its parts `_pull_owner`; the read cache holds the pose anchor to check; source-only anchors pull, relational parts get a dirty edge and `_resolve_link` pulls first ([Reactive Design](Reactive%20Design.md)) | `test_scale_link` (every kind × every name read first, for `scale`, `angle`, `flip_x`, `flip_y`; 615 failures on the old engine) |

Perf (interleaved A/B against a HEAD copy, 8 rounds): plain, linked, anchored
and point reads, `perf_fields` and plain draws within ±2 %; 24 scale-linked
squares +2.0 % a draw, +2.6 % on reads. A first version that sent every read of
a pose-linked shape down `_refresh_scalar` cost +82 %, and pulls on the hot
linked-node paths +11 %: the read cache holding the anchor to check and a
dirty edge for relational parts took both off the hot paths.

### Open (found, not yet fixed)

| Found in | Issue | Planned |
| --- | --- | --- |
| Showcase review | SH-E: hues under Bloom (a ratio-keeping clip), the corona's flat wash and facets | The author's look decision |
| SH-E (wave_at fix) | `ripple_at` and the `explosion_at` shock: the radial warp's crests move toward the centre while the accent ring expands (the cause `wave_at` had) | Same treatment as `wave_at`: one front for the ring and the warp |
| RA3 (0.10.0 deep) | The solver's split of a ball-on-ball overlap depends on which body it takes first (10 px each, or 20 px for one) | Solver question; deterministic since the ordered weak sets |

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
| HW1 | A destroyed actor named by a shapeless body's collision rule was never collected (deep tier 2026-10-22, `test_sys_hyp_world`) | `@collide_with("prey")` on a Hunter; `Text(group="prey")`; `hunter.collidable = False`; steps; destroy both → `_moved_now` → the Text's Collider → `_pair_targets` → Hunter | the `n_proxy == 0` early return skipped `_store_end_centers` (the only place that clears `_moved_now`), and `_forget_step_sets` did not drop a collider from `_moved_now` | `test_sys_holders.TestALeftColliderIsLetGo` (found by `scan`, not a list) + canary. Fix: both paths clear it |

### RX — reactive sources across subsystems (interaction campaign, class 8; 2026-10-09)

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| RX1 | A formula that read only `canvas.game_view` (or `layer.view`, or `graphic.box`) never re-evaluated: `c["center"] @= lambda: canvas.game_view.center` stayed where the camera was when linked; the no-sources guard did not fire | `c["center"] @= lambda: canvas.game_view.center`; `canvas.zoom_to(2)` → `c.center` unchanged | The dependency walk took the last Container in the chain, which was the measured Box (`Box._from_aabb`, a fresh value off the graph: D11), so the guard was satisfied by a throwaway and the formula depended on an object nothing ever updated; each pull also joined that Box into the graph | `test_canvas.TestCanvasIsAFormulaSource` (every camera move, a layer's scroll, `ui_view`, `graphic.box`, graph node count flat); `test_reactive_cross_matrix` (every sink from `canvas.game_view`). Fix (user decision 2026-10-09): `canvas` is a `Container` (like `mouse`) notified by `_sync_camera` and the scroll advance; `state._is_durable_source` keeps a deferred tree out of the chain's sources. Cost: an unlinked canvas returns after two attribute reads (A/B 2.12 vs 2.11 µs per `pan_to`) |

### AL — audio levels as formula sources (2026-10-10)

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| AL1 | A formula that read a microphone held by an object was accepted and never changed; `@=` on a bare `mic.level` raised "no reactive sources" | `class G(Entity)` holding `g.mic`; `r["width"] @= lambda: 300 * g.mic.level`; level moves, `r.width` stays 0 | The chain's last Container was the holder (`g`), which nothing updates when the capture thread writes the level; a level was not a source at all | `test_audio_level_source` (mic, `audio`, sound `Handle`, an Entity chain, the source-less `exec` path, `@when`, close, graph reset, nothing sampled when unlinked). Fix (user decision 2026-10-10): `level_source.py` — a stand-in node per reader, dirtied in frame step 1 when the capture / mix published (Sound Design, "Levels as formula sources"). A/B: frame body unchanged (12.03 vs 11.93 µs, no mic) |

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
| GX21 | A rim-placed Circle (`p1=, p2=` or `perimeter_point=`), foci Ellipse or p1/p2 / p1+vec / dx-dy Line whose placement lies on the mirror axis (a vertical diameter under `flip_x`, a horizontal one under `flip_y`) keeps a warm `angle` through the flip: 450 while the pose store and a clone read −270 (C7 `clone then flip_x`, deep profile, pose `r = 153`; fails on `67dd91b` too) | no point moves, so nothing refreshes the derived heading; the store turns. GX2's fix covered a zero-length Line only. The clone's points sat 1e-15 off the axis, so they moved and it read the new value | GX2's test collapsed a Line; the sweeps' poses rarely land a placement exactly on an axis, and the bug needs `angle` read twice before the flip (the first read makes the Derivate live and leaves the shape dirty) | `test_flip_mirror.TestFlipHeadingEdges` (`test_a_flip_that_moves_no_point_rewrites_a_warm_heading`: every derived-heading kind × axis × full turns; `test_a_clone_flips_its_heading_like_its_source`), `SWEEP_POSES` pose `r = 153` | Fixed: `Shape._mirror_geometry` runs `update()` when the store turned and no point moved (Line's zero-span special case folded into it). The raw heading follows the convention even when unchanged mod 360 (`450` → `−270`), as a fresh shape and a Sprite already did. A batch around every flip did it too but cost 3–7 µs per flip (1.1–1.6×); the targeted update A/B is noise |
| GX22 | A tall `center=` Ellipse (height > width) at heading 0 kept warm foci through `flip_y` (at 90, through `flip_x`): `fp1` read (3, −8) where the mirror is (3, 4) (H1 `TestShadowMachine`, degenerate base: width 0, no `angle=`; fails on `92fdcb4` too) | the tall foci read the flip parity (GX1's fix), not only the Defining values. At a fixed point of the heading map (`−0 = 0`, `180 − 90 = 90`) the flip writes the same angle and the center is its pivot, so no write refreshed the foci. GX21 covered a store that turns with no point moving; here nothing turns and nothing moves, yet a derived value changes | the arrays build at `P0`'s 17°; only a noangle row (heading 0) reaches a fixed point, and only by a single `flip_y` (the pinned GX1 cell runs `flip_x` first, which turns the heading to 180); a cold read recomputes with the new flags | `test_flip_mirror.TestFlipHeadingEdges.test_a_tall_ellipse_mirrors_warm_foci_where_the_flip_keeps_the_heading`; class: `test_geom_sequences.TestFlipAtHeadingFixedPoints` (every kind × fresh / degenerate × heading 0, 90 and the near misses 180, 270, parts read warm, against the shadow); PINNED cell | Fixed: `Ellipse._mirror_geometry` runs `update()` after a flip that left the heading in place (`_apply_flip`'s own `turned != rot` test, on the pose store) on a tall ellipse with derived foci. The shadow was right. No other shape derives a cached part from the flip flags (Track re-bakes on every flip; a Sprite's collision key and `.box` names read the flags each time). A/B per Ellipse flip, in one process: noise (9.17 vs 9.16 µs) |


### SY — systems review, design decisions (2026-10-09)

A review of the frame body, scheduler, input, acts, reactive core, shapes,
sprites, box, collision, registry and canvas confirmed about 90 interaction bugs; 17 of its items needed a
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
   implementation; keep it only where production is non-deterministic, and
   test the production clock at least once. (Shape transients, pinned
   because they read the wall clock, moved to presentation time in LW6: no
   pin is left.)

### RV — systems review fixes, batch 1: crashes and dead subjects (2026-10-09)

Root causes R2 (author code on a subject the engine already killed; exit
without enter) and the act-change crashes of the systems review. Each row's
test is its repro.

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
| F2 | **Accepted limitation, engine unchanged (by design).** A circle walking over touching tiles with alternating 5 / 28 ms frames enters / exits the *next* tile every other frame while within ~2 DU of the seam. Rects, resting bodies and steady 60 / 144 / 200 Hz are clean after F1 | Circle r=8 hero, 12 touching 16×16 `STATIC` tiles, `resolve(..., bounce=0.0)`, `vx = 60`, `dt` alternating 0.005 / 0.028 | `@collide` reads the pre-resolve pose, which sinks by g·dt² (0.6 DU on 28 ms, none on 5 ms); against the next tile's corner the gap swings across any fixed skin. Fixing it means judging resolved pairs on the resolved pose: splits the frame-order rule, drops the enter `depth`, breaks same-frame policy in `@collide_stay`. Needs four conditions at once (curved body, seam, uneven pacing, per-tile enter / exit); the standing tile keeps its contact | `TestCollideDoesNotFlicker.test_curved_body_on_seams_with_uneven_frames` stays `expectedFailure` as a tripwire. Mitigation: the Guide teaches `touching_contacts` for "which tile am I on" ([Touching](../docs/en/guide/index.html#colisao-touching), "Don't confuse" row); fence in [Collision Design — Resting contact (skin)](Collision%20Design.md#resting-contact-skin) |

### W — world machine extensions (M4)

M5 (2026-10-15) adds the laws as an invariant and commands from callbacks:
[Laws and equations](#laws-and-equations), S7.

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
| D27 | One `vel.angle` read put the whole actor off the pose fast path **for good** (performance) | `b = Triangle(center=(0, 0), radius=9)`; `b.vel = (3, 4)`; `b.angle = b.vel.angle` → `b._requires_pull_invalidate()` True, every `move_by` / `angle =` batched (120 birds ~250 → ~150 fps) | `_ensure_derivate_scalar` flagged the ownership root for any Derivate scalar, though Vec2 `length` / `angle` read only the vector's own axes | `test_scoped_pull_flag` (every fast model × every pose verb after reading `vel` and its Defining vectors, values checked against x / y; every `vel` write door; a cell letting go; links and `@when`; canary on the unscoped check). Fix: `_scalar_pull_scoped` (Vec2): the read flags the vector only, `Vec2._requires_pull_invalidate` sees it (a holder letting go keeps it: VB17). Vector writes 0–4 % faster (cached root); the `vel.angle` flock 4.7 → 3.7 ms work (Reactive Design, Scoped pull flag) |
| D28 | `scale =` / `scale_to` / a scale tween cost ~10× a size write (performance; values were right) | `r = Rect(width=20, height=20, corner_radius=5)`; `r.scale = x` ~14 µs, `r.width = x` ~1.4 µs; 2500 rounded Rects pulsing `scale` spent 41 ms a frame in the process tick (a Game of Life draft switched to tweening `Square.length`) | Every scale went through the kind's general `scale_by`: `_pivot_xy` and `_center_xy` each re-derived the center through `_oriented_frame`, the unchanged center was written back, and `batch_update_self` pushed and restored the whole part subtree, though about its own center a center-placed model changes only its sizes | `test_scale_center_fast`: census (the kinds that opt in = the center-placed size models of `geometry_support.KINDS`), cost class (the kind's `scale_by` never runs for `scale =` / `scale_to` / a tween), differential against the switch off (random scale / pose sequences: pose, collision prims, pose-revision bumps, errors, public reads; a nested batch; no vacuous pass), links keep the general path's behaviour (linked `scale` / size, `force=`, `box=` formula, outbound links, Square mirrors), canary (a 0.1 % size error). Fix: `_scale_about_center_fast` + `_center_scale_sizes()` (Reactive Design, Scale about the center); switch `shapes._SCALE_CENTER_FAST`. In-process A/B per write: Rect 13.3 → 6.9 µs, Square 17.6 → 4.8, Circle 8.8 → 4.8, Ellipse 10.1 → 6.7, RegularPolygon 14.3 → 4.6, Triangle 12.4 → 4.7; 2500 pulsing cells: Rect 41 → 21 ms, Square 52 → 16, Circle 28 → 16 ms of process tick. Other scale paths flat or faster (two per-call imports gone) |

### B — bench pulse findings

| ID | Bug | Shrunk repro | Root cause | Guard |
| --- | --- | --- | --- | --- |
| B1 | Every **read** of a linked Point re-walked its whole dependent cone (performance; values stayed correct). `graph-1` sierpinski 7.07 → 14.64 ms, draw 5.0 → 12.6 ms; landed between 09-24 and 09-26 | `a → m @= f(a)`; `a.move_to(…)`; reading `m.x` calls `mark_dirty` once (should be 0); ×729 Lines per frame at depth 5 | The `takein` → `_takein` / `_takein` → `_takein_impl` rename: `Container._resolve_link` (both branches) and `DirectLink.evaluate_and_update` (container branch) kept calling `_takein`, which now names the invalidating dispatcher, not the raw store. `TestDeepBinaryTree` ceilings had been raised 46 → 107 to fit it | `tests/test_pull_no_invalidate.py`: `mark_dirty` count during reads per sink kind (0), one walk per write on a midpoint tree, downstream-fresh twins, AST guard `TestPullResolversStoreRaw` (resolvers and `_no_update` blocks in `evaluate_and_update` never call `_takein`; vacuity-guarded); `DEEP_MARK_DIRTY_CEILING` back to 46. Mutation-checked: reverting the fix fails 6 of 10 |
| B2 | Per-frame verbs paid the full validator path for a plain `float` (performance). `balanced-2` cpu_mix tick 1.10 → 1.40 ms (scheduler `_tick_on_update`: author `on_update` bodies); `move_by` 1.19 → 2.25 µs, `rotation =` 0.86 → 1.21 µs | `c.move_by(0.1, -0.1)` in a loop; `validate.finite` ×2 per call, `_finite_deg` ×3 per `rotation =` | A3–A8 correctly routed verbs through `validate.finite` / `_finite_deg`, but a plain float took two `callable` probes, `as_payload` and an ABC `isinstance(numbers.Real)` (Python-level `__instancecheck__`); plus a function-local import per `move_by` | `tests/test_hot_validators.py`: contract table (float / int / subclasses / Fraction / NaN / inf / bool / non-numbers) for both validators; `TestHotPathsStayHot` patches the slow-path helpers to raise and drives `move_by` / `rotation =` / `rotate_by`. Fix: exact-type fast path first (as `_coerce_magnitude_slot` already did); `finite` imported at module level in shapes. Mutation-checked |
| B3 | **Harness bug, no engine change.** Auto-diff reported `gpu −25%` / heroes `+7%` as "candidate real move" — the window had opened on another display, so the GPU cells ran at FB 1200×800 (1×) instead of 2400×1600 (2×), a different workload. The same code at 2× measured flat (heroes 6.18 ms, draw 2.35 ms vs 2.27–2.35 on 09-22…24) | `balanced-2` on the evening of 2026-09-28 | `§` = 1× was a hand convention in `balanced.md`: the runner neither wrote nor read it, and `autodiff` compared across scales | `tests/test_bench_pulse.py`: scale tags round-trip, the runner stamps 1× cells, previous-row lookup matches FB per GPU cell (fallback / not-compared notes), older fallback rows never claim "same fingerprint → noise", dashboard headline says FB. Mutation-checked |
| B4 | **Probe bug, no engine change.** Every `jitter_probe` / `longrun` / Windows-wrapper run with `--seconds` hung forever (the window never closed); post-FX time was silently unmeasured | `jitter_probe.py app_first.py --seconds 4 --present keep` never returns (bisected to the author-API audit commit) | The author-API audit renamed engine hooks `Clock.tick` → `_tick` and `PostFxStack.render` → `_render`. `FrameProbe._patch` skipped a missing attribute silently, so the probe saw no frame start and never asked the window to close | `tests/test_frame_probe.py`: install on the real engine (every target exists, `_tick` / `_render` wrapped, uninstall restores), a missing target raises at install, a timed run requests the stop, every `--present` choice maps to a `canvas.framerate` value. `_patch` now raises instead of skipping. Same rename also broke `perf_spatial_fx.py` (patched `clock.tick`) |
| B5 | FX Auto **unstable**: any minor system load stepped it down (often to low@30) and it never stepped back up | 30 s of +30 % work with a 25 ms spike every ~0.5 s cascaded high → low@30 in ~7 s and parked at low@60; after a real overload ended it never returned to high although high fit with ~50 % headroom | Down: period *mean* (dragged by spikes), one bad eval enough (`t_down_s` 1 s), a 3 % slip line hit by spike slips, the pacer's own late wakes counted. Up: climbs needed *current* work under 32–42 % of the budget — out of reach for a scene that fits | `tests/test_fx_auto.py` `TestStability` (production params, simulated frames: minor load → no step; one bad second → no step; overload → down fast, back to high slowly; parks at the rung that fits; GPU-bound slips walk down; external slips at most one step; learned cost ratio; failed-climb backoff) and `test_pacing` oversleep-vs-overrun. Fix: median, 2 s, overruns only, 10 % in window and latest period, predicted-cost climbs with learned ratios, external-slip hold, doubling failed-climb lock |
| B6 | **Bench rot, no engine change.** `run_balanced` (and so `run_all`) crashed in `gpu_mix` before measuring any GPU cell | `python scripts/bench/run_balanced.py` → `TypeError: Shield(style="bubble") paints its own colors and takes no color` | f20ca3b (KN) made the style-only `color=` a refusal; `gpu_mix.py` still passed it (it had always been ignored). The pulse scenes were not in the headless script guard, and nobody runs the battery daily | `tests/test_scripts_run.EXTRA` now lists every scene a pulse builds (`cpu_mix`, `gpu_mix`, `live_mix`, the two resolve scenes, `perf_text`, `perf_background`, `sched`), run by `test_smoke_scripts`. Canary: the old spelling fails it. Fix: drop `color=` (same pixels: it was ignored) |
| B7 | **Harness bug, no engine change; B3's class again in a new pulse.** `games-1` (`run_games.py`, 2026-10-12) recorded no framebuffer scale. festa (GPU-bound) logged 36.2 ms at FB 1×; the next run opened at FB 2× (a 4K display) and read 44.7–46.3 ms, submit 19.6 → 26.3 ms, which its auto-diff would have reported as a +25 % candidate move. One run per game also left horda and mundo at ±10–15 % with the machine load, the size of the 15 % threshold | `games-1` on 2026-10-13, window on the 4K display | The FB guard of `balanced-2` (B3) lived in that runner; the new runner copied its row layout but not the guard | `games-2`: festa's framebuffer in pixels per row (the window is fitted to the display, so fb / design width is no scale: the first attempt read 2.006×, 2.236× and 2.506× for games on one display), festa's cells compared only with a row at the same framebuffer (`mixed` never compared), median of three interleaved rounds. `tests/test_bench_pulse.TestGamesPulse` (median, mixed scale, cell round trip, same-FB lookup, autodiff end to end, dashboard). Rule: **a new pulse that opens a window stamps its framebuffer and gates its GPU-bound cells on it**; a ratio to the design size is a scale only when the window is not auto-fitted |
| B8 | FX Auto spent the look on frames bound by game logic | `examples/constelacao.py` at 818072e, real window, 60 Hz: simulate 11.0 + draw 4.4 + submit 0.5 ms walked high@60 → medium@60 → low@60 → low@30 in 15 s (48 fps average, p95 34 ms); lowering quality saved ~1 ms of draw | FX Auto saw only total CPU work, so every step down was a fidelity step until the survival rate rung | `tests/test_fx_auto.py` `TestSimBound` (the measured stream → one step to high@30; the same stream without the split → the old walk; draw-bound streams take identical steps with and without the split; over-the-line-but-fitting holds at 60; sim-bound at 30 holds; draw growing at 30 steps within the 30 row; climb back by rate; a wrong draw prior costs one rung; the loop passes the draw share). Fix: draw share from the loop, sim-bound test (sim ≥ ½ of work and cheapest fidelity predicted over the line), rate rungs that keep fidelity (Effect System Design — Auto policy) |
| B9 | A tree of formula-linked Lines cost n × depth per frame (performance; values stayed correct). 1023 branches: ~106k `mark_dirty` visits, ~51 ms per drawn frame vs ~15 ms for the same tree in a recursive `update()`; found 2026-10-25 writing a showcase (a fractal tree of light) | `Line(p1=…, length=1, angle=0)` per branch; `line["p1"] @= lambda: parent.p2`, `line["angle"] @= lambda: parent.angle + …`; one `st` write per frame, read every branch: visits per branch 46 at depth 4, 104 at depth 9 (a chain of n links: n²/2) | A structural pull (`_resolve_structural` → `_update_impl`) writes the owner's live Derivates through the dispatcher (`p2._takein`, `setattr` of `dx` / `dy`, which marks the Line): three walks of the branch's whole subtree per branch, all of it already dirty from the frame's write. B1 had fixed the link resolvers; the AST guard covers only them, and the doc called the Derivate refresh's walk "on purpose" (it is, outside a pull) | `test_pull_no_invalidate.TestStructuralPullDoesNotRewalk` (walk visits per node flat from depth 3 to 6 and from 8 to 32 chain links; values against an analytic tree with partial pulls), `TestStructuralPullKeepsSinksFresh` (conditional sink, scalar Derivate sink, a part made live while the owner is dirty, eager refresh). Fix: `UpdateManager._refreshing` / `_pull_refreshed` (Reactive Design, "A structural pull does not re-walk"); 4 visits per branch, depth 7 11.3 → 5.7 ms headless, other graphs within noise (in-process A/B). Mutation: removing the fix fails both cost tests; skipping every walk inside the window passes all guards (`_update_impl` writes only Derivates) |
