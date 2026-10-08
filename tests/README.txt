Strategy, harnesses, bug loop and bug catalogue: design/Testing Design.md

Running tests: use the tiered runner (one process per module, in parallel).
Tiers and why: design/Testing Design.md, "Test tiers".

  python tests/run_tiers.py focused test_shapes     # after every edit (seconds)
  python tests/run_tiers.py quick                   # before calling a change done (~25 s)
  python tests/run_tiers.py gate                    # bug-loop gate: all modules, ci, canaries
  python tests/run_tiers.py deep                    # nightly / milestone (2 h +)
  python tests/run_tiers.py gate --plan             # show the jobs, run nothing

Two roots: tests/ (framework) and scena_editor/tests/ (level editor, a
companion app). Name either kind the same way:
  python tests/run_tiers.py focused test_editor_tools test_level

Avoid "python -m unittest discover -s tests" as a routine check: in one process
the suite takes ~24 min instead of ~2 (the heap grows module after module and
every census walks it). The deep tier still runs one such pass, to catch a
module that leaves state behind for the next one; it lists every module of
both roots (tests/ then scena_editor/tests/) in one process. Every module must also pass alone:
python -m unittest tests.test_<area>

Env switches: SCENA_HYPOTHESIS_PROFILE (dev / ci / deep / replay),
SCENA_CANARIES=0 (skip canaries and vacuity guards; default on),
SCENA_SOAK=1 (endurance), SCENA_HYPOTHESIS_DB=0 (no example database; the
mutation runner sets it). run_tiers.py sets the first three per tier.

Copied trees (Windows, USB stick, SMB share): macOS leaves an AppleDouble
"._<name>" file next to every file on volumes without extended attributes.
Tests skip them (every directory scan goes through tests/source_support.py),
and run_tiers.py prints a warning with their count. To clean a tree:

  macOS, before copying:   dot_clean -m <dir>   or   COPYFILE_DISABLE=1 tar ...
  Windows, after copying:  Get-ChildItem -Recurse -Force -Filter '._*' -File | Remove-Item -Force

The copy can also mark files Hidden (the old .scena_test_runs/ logs and
timings.json arrived Hidden on Windows). Windows refuses open(path, "w") on an
existing Hidden file, so run_tiers.py deletes a stale log before writing it
(open_fresh; guard test_run_tiers.TestOpenFresh). Better: do not copy
.scena_test_runs/ and .hypothesis/ at all; they are per-machine output.

Pixels: always toarray(colorType=skia.kRGBA_8888_ColorType) and
Image.fromarray(px, colorType=skia.kRGBA_8888_ColorType). The default kN32 is
BGRA on Windows. Guards: tests/test_platform_portability.py.

Text files: always open(p, encoding="utf-8") / read_text(encoding="utf-8") /
write_text(s, encoding="utf-8"). The default is the locale, cp1252 on Windows.
Child processes too: subprocess.run(..., text=True) decodes with the locale.
A Python child: encoding="utf-8", errors="replace", and
env={**os.environ, "PYTHONIOENCODING": "utf-8"}. An external tool:
errors="replace". Sort paths with source_support.path_key ("/" form; "\"
sorts after letters). Guard: tests/test_platform_portability.py.

Paths: an expected path that went through abspath / realpath / Path.resolve /
os.path.join is built the same way in the test, never written as a POSIX
literal. Windows turns /a/b into C:\a\b. A relpath used as a label is
compared in "/" form: os.path.relpath(p, ROOT).replace(os.sep, "/").
A helper that takes a path in "/" form (png("ninja/a.png")) normalizes its
join: os.path.normpath(os.path.join(root, rel)). Plain os.path.join gives
C:\t\ninja/a.png on Windows, unequal to the C:\t\ninja\a.png the code
returns. Guard: tests/test_platform_portability.py.

File modes: Windows has no exec bit (os.chmod only toggles read-only; st_mode's
execute bits follow the extension). Assert S_IXUSR / X_OK only under
if os.name != "nt":. Guard: tests/test_platform_portability.py.

Timing: never assert an absolute ms budget sized on one machine. Compare against
a reference path in the same process (a ratio), or keep the absolute number as a
loose catastrophe guard only. Best of N drops spikes, not a loaded tier.
Time the two sides of a ratio in interleaved short blocks (alternate which
goes first) and keep each side's best block; two back-to-back samples see
different load.
A test that sets a transient's progress from one _now() read and then draws
pins the clock: transients.set_now_fn(lambda: now), with
addCleanup(set_now_fn, None). A subprocess timeout is a hang detector: size it
for a loaded tier, not for an idle run.

The ScenaFramework singleton (and canvas.effects / post_draw on it) persists
across test modules. A test that drives run() with a mocked GL context must
clear canvas.effects and install a no-op post_draw. An active stack takes the
GPU scene-RT path, which a Mock context cannot create.

Property-based tests (Hypothesis)
---------------------------------

tests/test_hyp_*.py use Hypothesis (pip install -e ".[test]"; the same extra
brings Pillow for the Guia's animated thumbnails in test_guia_thumbs_render.py):

  test_hyp_api.py     author calls: Numbers rule on slots / verbs / constructors,
                      "author errors only" (no Python builtin message leaks),
                      failed calls do not half-apply, pose algebra (vertex-level
                      rotation for every kind: TestRotationGeometry), flags, ink,
                      keyp names, durations, chance, and a @= link state machine.
  test_hyp_canvas.py  scene state machine: create / destroy / undraw / layer= /
                      tag / clone / park / layer create-delete-clear / group
                      destroy / on_destroy spawns, checked against a model after
                      every step (draw lists, painter order, groups, ids).
  test_hyp_events.py  @when / @on_change state machine (frame batches, flushes,
                      relays, destroyed sources, unregister), glitch-freedom,
                      method-watch lifetime.

  test_hyp_surface.py signature fuzz of every scena.__all__ export: no-arg
                      construction, junk in any one keyword (author error, no
                      trace), unknown keyword, construct -> remove baseline,
                      every method / setter on a destroyed Entity (P6),
                      junk into every author method of a live instance
                      (surface_support.REPRESENTATIVES for classes with no
                      no-arg form), flags must be real bools, global
                      setters inside global_snapshot / global_restore,
                      coverage guards, canaries.
                      Helpers: tests/surface_support.py. ~100 s at dev,
                      ~7 min at ci (one generated test per export).

  test_diff_pose.py       pose fast path vs batched twin; engine readers / verbs
                          that knock shapes off the fast path (shrink-only list).
  test_diff_reactive.py   lazy + GC backstop + cached reads vs eager + strong +
                          uncached, plus a link model; owner index vs scan.
  test_diff_collision.py  cached vs uncached prims, proxy contains exact,
                          closed form vs SAT, sweeps vs a sampled sweep,
                          incremental @collide enroll vs rebuild.
  test_diff_draw.py       sticky plain-blit flag, plain vs full draw, cull on vs
                          off, shared-filter batching on vs off (apart).

  Differential helpers: tests/diff_support.py (make_twins, fingerprint,
  assert_fast, assert_catches for canaries).
  SCENA_HYPOTHESIS_PROFILE=ci python -m unittest discover -s tests -p "test_diff_*.py"

Geometry properties living in unit modules (Hypothesis, same profiles):
  test_box.TestGridCoversBoxProperty          cells tile the Box; cell_at = layout
  test_canvas.TestScreenWorldRoundTripProperty world -> screen -> world, pan point,
                                               game_view = window corners
  test_easing.TestChaseProperties             chase is frame-rate independent

Shared infrastructure: tests/hypothesis_support.py (profiles, strategies,
WorldTracker reset, assert_author_error). Every module that uses @given or a
state machine imports it at module level (or system_support, which does):
without it Hypothesis runs on its defaults (200 ms deadline, no example
database, SCENA_HYPOTHESIS_PROFILE ignored). Guard:
test_run_tiers.TestHypothesisProfileGuard.

  python -m unittest tests.test_hyp_api tests.test_hyp_canvas tests.test_hyp_events
  SCENA_HYPOTHESIS_PROFILE=ci   python -m unittest discover -s tests -p "test_hyp_*.py"
  SCENA_HYPOTHESIS_PROFILE=deep python -m pytest tests/test_hyp_canvas.py   # minutes

Profiles: dev (default, 40 examples), ci (200), deep (2000), replay (only the
saved failures). Failures are saved in .hypothesis/examples and replayed
first on the next run. pytest shows the shrunk "Failing test case" steps
most readably:

  python -m pytest tests/test_hyp_canvas.py -p no:cacheprovider --tb=short

Writing new properties:
- Wrap each example in `with fresh_world() as w:` (or a WorldTracker in a
  state machine) and `w.track(obj)` everything you construct. Scena keeps one
  ScenaFramework per process; an example that leaks state makes Hypothesis
  report "Flaky" instead of the bug.
- teardown() is strict: a tracked Entity still alive after destroy raises
  AssertionError naming it (fresh_world / system_world skip the check when the
  body already failed, so the real error is never masked). An object that
  cannot be destroyed outlives its module and crashes an unrelated test in the
  deep tier's serial pass. teardown(strict=False) only for deliberate zombies.
- Hypothesis reports one failure per raise site. Give each independent
  contract its own test (see TestVerbsRejectJunk: one generated test per
  verb) or one broken verb hides the others.
- Use pool names (GROUP_POOL, LAYER_POOL) so collisions happen.

System / sub-system tests
-------------------------

tests/test_sys_*.py drive the REAL frame body headless and deterministic:
ScenaFramework._simulate_frame(dt=...) (the method run() calls: clock,
update, processes, collision, leave playfield, flush, pre-draw ticks) and
optionally _draw_frame() onto a CPU raster surface. GLFW polling and
glViewport are patched; the mixer runs offline. Harness:
tests/system_support.py.

  test_sys_lifetime.py     destroy from every context (timer, mode, on_update,
                           collision, @when, on_destroy, transient / cover
                           on_done, group / layer drain, parked, leaving), a
                           spawn / destroy churn, drop-without-destroy, clone
                           isolation, park across subsystems, modes, caches.
  test_sys_frame_order.py  phase order in one frame, handoffs (timer from a
                           handler, pre-draw write -> next flush, same-frame
                           spawn collides), glitch-free handlers, recovery from
                           an author error mid-frame, run() vs driver drift.
  test_sys_hyp_world.py    Hypothesis session state machine (spawn circle / rect /
                           sprite + hitbox part / text / entity / sparks; destroy
                           now or from inside another subsystem / park / clone /
                           mode / link / collidable / move / layer = / custom
                           layers create-delete-clear / on_destroy spawner /
                           poke verbs on dead actors / step): no dead calls, no
                           zombies, collision index = alive+active+collidable,
                           draw lists and groups = shared model (hyp_models.py),
                           links consistent, census and collection at teardown.
                           TestWorldMachineReach (vacuity), TestSystemCanaries
                           (H3, S1, S6, S9, destroy-skips-collision, W2; ~12 s).
  test_sys_hyp_scheduler.py  after / every / tween / park time algebra over
                           random dt sequences; clock clamp.
  test_sys_hyp_collision.py  contacts vs exact circle geometry and vs pairwise
                           test_collision; enter / exit alternate; synchronous
                           exit on destroy / collidable = False; contacts
                           unchanged when the whole world is shifted far away
                           (built there, or moved there with move_by).
  test_sys_hyp_audio.py    sound ownership machine vs the offline mixer.
  test_hyp_events.py       TestLinksUnderFrames: links written from every phase.
  test_sys_soak.py         opt-in endurance (SCENA_SOAK=1, SCENA_SOAK_FRAMES).

  python -m unittest tests.test_sys_lifetime tests.test_sys_frame_order -v
  SCENA_HYPOTHESIS_PROFILE=ci   python -m unittest discover -s tests -p "test_sys_hyp_*.py"
  SCENA_HYPOTHESIS_PROFILE=deep python -m pytest tests/test_sys_hyp_world.py   # ~15-20 min (M4 rules)
  SCENA_SOAK=1 python -m unittest tests.test_sys_soak -v

Harness pieces:
- SystemWorld / system_world() / SystemTestCase: a WorldTracker that also
  resets collision, bounds, cover, FX registries, clock, ready / recently,
  camera and post stack; pins transient / SpatialFx / cover time to
  clock.time; parks ("quarantines") live actors other modules left behind and
  restores them at teardown. world.step(n, dt, draw), step_until, seconds.
- census() / diff_census(): sizes of every registry that can hold an actor
  (graph, events, scheduler, collision, bounds, scene, FX, mixer, widgets).
  full_collect() runs gc until nothing is freed (GC-backstop finalizers free
  more on a later pass). id_snapshot() / describe_new_ids() name leftovers.
- zombies() / world.zombies(): destroyed objects a registry still references.
- Probe: author hooks record (frame, tag, owner_alive); dead_calls() is the
  use-after-destroy check (collide_exit of the dying body is documented).
- assert_collected(): the referrer chain names the holder on failure.
- kitchen_sink(): one actor wired into every subsystem.

Program model tests
-------------------

tests/test_prog_*.py run whole author programs (tests/programs/<name>.py)
headless, with input through the real window handlers, and check them against
specs written from the docs by independent spec-only authors
(tests/programs/<name>_spec_a.py / _spec_b.py; prompt in
tests/programs/spec_agent_prompt.txt). Protocol, levels and the divergence
ledger: design/Testing Design.md, "Program model tests".

  python tests/run_tiers.py focused test_prog_bouncing_balls test_program_support

  Harness: tests/program_support.py (ProgramRun, Trace, spec vocabulary,
  program_test_case). L3 oracles: tests/program_oracles.py. Open divergences:
  tests/program_ledger.py (shrink-only).

  Class guards from the campaign's lessons (Testing Design, "What the
  program-model campaign taught"): test_cells_as_numbers (cells in every
  exported function), test_collision_doors (one CollisionInfo view per pair),
  test_sys_frame_contracts (each Guia frame promise in real frames, with a scan
  of the Guia), test_noop_cost (no-ops build nothing).

  Coverage (which exports the programs reach; guard in test_program_coverage):
  python tests/program_coverage.py --json

  API-first programs (geometry_lab, toybox, runner_story) cover exports the
  drafts and examples never touch; Tier B composer: test_prog_compose.py.

  Value metric (slow; one quick tier per mutant):
  python tests/mutation_run.py --modules scena.collision scena.uiwidget \
      --programs test_prog_bouncing_balls --n 40
  python tests/mutation_run.py ... --no-baseline     # program suite only

Pitfalls, the bug loop (what to run after every fix), and the catalogue of
findings (H / R / S / A / D / W / O series) live in design/Testing Design.md.
Read its "Harness pitfalls" before trusting a leak failure, and follow its
"Bug loop" for every finding: regression test in the owning test_<area>.py,
fix, then "python tests/run_tiers.py gate".
