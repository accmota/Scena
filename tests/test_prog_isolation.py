"""Program isolation: a program reads the same whatever ran before it.

Interaction campaign, class "program order pairs" (design/Testing Design.md,
"Interaction campaign"). The program model runs one author program per
``ProgramRun``; in real use a program has the process to itself, in a test
process something always ran first. The deep tier's serial pass is the only
place that seam was checked, and its failures (Testing Design, "Open") were
found by accident. Here the seam is a matrix:

* **order pairs** — program B after program A (A's most stateful scenario)
  reads, sample by sample, like B alone: the trace, the ``mark()`` events and
  the census. ``dev``: one chain over every program (each program after its
  neighbour), B's first scenario; ``ci`` / ``deep``: every ordered pair, B's
  every scenario;
* **dirty predecessors** — B after what a test module leaves behind (live
  drawn shapes, shapes with work, a stale widget with B's own label, learned
  group names, a junk pointer with a held key, kept settings, world settings)
  reads like B alone;
* **given back** — a run leaves the process as it found it, by a snapshot of
  the process-wide state (world and kept settings, learned names, input,
  clock, census). A new leak channel shows as a key.

Oracle: the trace of the same scenario taken first in the process
(``program_oracles._diff_samples``); a divergence that also shows against a
second alone run is a replay failure, reported as such. Known findings are
listed shrink-only in ``KNOWN`` (a listed cell must still fail in the full
run). Canaries plant a dropped harness reset and expect the pair to fail.

One class per program B (``TestNaves``: ``test_after_<A>``, ``test_with_<cell>``,
``test_given_back``): ``run_tiers.SPLIT`` gives each B its own gate job.

    python -m unittest tests.test_prog_isolation -v
    SCENA_HYPOTHESIS_PROFILE=ci python -m unittest tests.test_prog_isolation
"""
from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402  (profile; also resets the globals' module)
from diff_support import assert_catches  # noqa: E402
from program_oracles import _diff_samples, _run  # noqa: E402
from program_support import Trace, load_spec, registry  # noqa: E402
from surface_support import CURSOR_KEYS, surface_census  # noqa: E402
from system_support import quiet  # noqa: E402

import scena  # noqa: E402
from scena import Button, Circle, Rect, canvas, clock, every, mouse  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import get_scheduler  # noqa: E402

FULL = hypothesis_support.PROFILE in ("ci", "deep")     # every ordered pair, every program
DEEP = hypothesis_support.PROFILE == "deep"              # ... and B's every scenario

# program -> the spec-a scenario that leaves the most behind (input, pointer,
# widgets, acts); it is the predecessor A. B runs its spec-a scenarios.
PROGRAMS: Dict[str, str] = {
    "bouncing_balls": "start",
    "examples/cadeia_de_bolas": "mouse",
    "galaga_acts": "start_space",
    "geometry_lab": "pins",
    "examples/naves_1": "atira",
    "examples/pegar_estrelas": "direita",
    "platformer": "jump",
    "runner_story": "skip",
    "snake_chain": "up_max",
    "toybox": "hover",
}

# Shrink-only: "cell | program | scenario" -> reason (a finding id). A listed
# cell must still fail in the full run; never list to make a failure pass.
KNOWN: Dict[str, str] = {
}


def _ident(name: str) -> str:
    return name.replace("examples/", "").replace("/", "_").replace(".", "_")


# --------------------------------------------------------------------------
# Alone traces (lazy: the canary runs a private module copy without fixtures)
# --------------------------------------------------------------------------

_ALONE: Dict[Tuple[str, str], Trace] = {}
_SPECS: Dict[str, Dict[str, Any]] = {}
_WARM = [False]


def spec(program: str) -> Dict[str, Any]:
    ns = _SPECS.get(program)
    if ns is None:
        ns = _SPECS[program] = load_spec(program, "a")
    return ns


def b_scenarios(program: str) -> List[str]:
    """B's scenarios: every spec-a scenario at deep, the first two at ci, the
    first at dev (every pair at ci took 14 min with every scenario)."""
    names = list(spec(program)["SCENARIOS"])
    return names if DEEP else (names[:2] if FULL else names[:1])


# Dirty predecessors at dev run against the programs with widgets, a pointer
# scenario and acts; the full run takes every program.
DIRTY_PROGRAMS_DEV = ("bouncing_balls", "galaga_acts", "toybox", "examples/naves_1")


def warm() -> None:
    """One short run first: globals join the graph once per process, caches fill."""
    if not _WARM[0]:
        _WARM[0] = True
        _run("bouncing_balls", spec("bouncing_balls"), "idle")


def trace_of(program: str, scenario: str) -> Trace:
    t, _ = _run(program, spec(program), scenario)
    return t


def alone(program: str, scenario: str) -> Trace:
    key = (program, scenario)
    if key not in _ALONE:
        warm()
        _ALONE[key] = trace_of(program, scenario)
    return _ALONE[key]


def _events(t: Trace) -> List[Tuple[int, str, str]]:
    return [(e.frame, e.name, repr(e.data)) for e in t.events]


def compare(program: str, scenario: str, after: Trace, label: str, *,
            classify: bool = True) -> List[str]:
    """Messages when ``after`` differs from the alone trace (empty = same)."""
    base = alone(program, scenario)
    out = _diff_samples(base, after)
    if _events(base) != _events(after):
        out.append(f"events: {_events(base)[:6]} vs {_events(after)[:6]}")
    if after.leftovers:
        out.append(f"leftovers after {label}: {after.leftovers}")
    if out and classify:
        # Replay or isolation? A second alone run tells them apart.
        again = trace_of(program, scenario)
        if _diff_samples(base, again) or _events(base) != _events(again):
            out.insert(0, "NOT REPLAYABLE: the scenario differs from itself with no "
                          "predecessor (program_oracles.replay), so the pair cannot be judged")
    return [f"{label} -> {program}/{scenario}: {m}" for m in out]


# --------------------------------------------------------------------------
# Process snapshot: what one run can leave for the next
# --------------------------------------------------------------------------

def _resolve(path: str) -> Any:
    obj: Any = scena
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def process_snapshot(*, collect: bool = True) -> Dict[str, str]:
    """Process-wide state as ``repr`` strings, keyed by what it is.

    ``collect=False`` skips the census's full collection (context for a pair
    failure; the given-back guard collects).
    """
    from scena.act import KEPT_SETTINGS, WORLD_SETTINGS
    fw = ScenaFramework.get_instance()
    reg = registry()
    out: Dict[str, str] = {}
    for w in WORLD_SETTINGS:
        try:
            out["world." + w.name] = repr(w.snapshot())
        except Exception as e:
            out["world." + w.name] = f"<{type(e).__name__}>"
    for name in KEPT_SETTINGS:
        try:
            v = _resolve(name)
        except AttributeError:
            continue
        if not callable(v):
            out["kept." + name] = repr(v)
    out["groups.known"] = repr(sorted(reg._group_gen))
    out["groups.declared"] = repr(sorted(reg._declared_groups))
    out["keys.pressed"] = repr(sorted(fw.keys._pressed_keys))
    out["keys.pending_edges"] = repr(sorted(map(repr, fw.keys._pending_edges)))
    out["keys.masked"] = repr(fw.keys._input_masked)
    out["mouse.buttons"] = repr(sorted(fw.mouse._pressed_buttons))
    out["mouse.masked"] = repr(fw.mouse._input_masked)
    out["mouse.pos"] = repr((round(mouse.x, 6), round(mouse.y, 6)))
    out["clock"] = repr((clock.scale, clock.paused))
    out["sched.every_sites"] = repr(len(get_scheduler()._every_sites))
    sm = fw.shape_manager
    out["pointer.hover"] = repr(sm._hover_target is not None)
    out["pointer.dragging"] = repr(bool(sm._dragging))
    census = dict(surface_census(collect=collect))
    # A global (clock, mouse, keyp, st ...) joins the graph the first time a
    # formula reads it, once per process: count the other nodes.
    from scena.state import get_scena_system
    ss = get_scena_system()
    if ss is not None and "graph.nodes" in census:
        import inspect
        globals_ = {id(getattr(scena, n)) for n in scena.__all__
                    if not inspect.isclass(getattr(scena, n, None))
                    and not callable(getattr(scena, n, None))}
        globals_ |= {id(clock), id(mouse), id(scena.keyp), id(scena.st)}
        census["graph.nodes"] -= sum(1 for k in ss.dependency_graph.nodes if k in globals_)
    for k, v in census.items():
        if k not in CURSOR_KEYS:
            out["census." + k] = repr(v)
    return out


def snapshot_diff(a: Dict[str, str], b: Dict[str, str]) -> Dict[str, Tuple[str, str]]:
    # A census key absent on one side is an empty registry (a system reset to None).
    return {k: (a.get(k, "0"), b.get(k, "0")) for k in sorted(set(a) | set(b))
            if a.get(k, "0") != b.get(k, "0")}


# --------------------------------------------------------------------------
# Dirty predecessors: what a test module can leave in the process
# --------------------------------------------------------------------------

Undo = Callable[[], None]


def _destroy_all(objs) -> None:
    with quiet():
        for o in objs:
            try:
                if getattr(o, "is_alive", False):
                    o.destroy()
            except Exception:
                pass


def live_shapes() -> Undo:
    """Drawn shapes nobody destroyed (test_shapes leaves ~700)."""
    objs = [Circle(center=(20 * i % 400, 7 * i % 300), radius=5, group="sombra")
            for i in range(300)]
    return lambda: _destroy_all(objs)


def shapes_with_work() -> Undo:
    """Live shapes with timers, a tween, a link from the mouse, a collision pair."""
    from scena import collide, tween
    objs = [Rect(center=(50 + 30 * i, 150), width=20, height=20, group="trabalho")
            for i in range(10)]
    for o in objs:
        o.collidable = True
    for o in objs[:5]:
        o.every(0.1, lambda: None)
    tween(objs[5]["angle"], 360, time=5.0, loops="forever")
    objs[6]["center"] @= (lambda: (mouse.x, mouse.y))
    collide("trabalho", "trabalho")(lambda info: None)
    return lambda: _destroy_all(objs)


def stale_widget() -> Undo:
    """A live Button with a label a program's spec clicks (``Start``)."""
    objs = [Button(label="Start", on_click=lambda: None)]
    return lambda: _destroy_all(objs)


def learned_group_names() -> Undo:
    """Group names near the programs' own, learned for did-you-mean, then gone."""
    objs = [Circle(radius=1, group=g) for g in
            ("estrela", "tiros", "inimigo", "bola", "plataforma", "player")]
    _destroy_all(objs)
    return lambda: None


def junk_pointer() -> Undo:
    """The pointer where a fuzzer left it, a button down, a key held, input masked."""
    fw = ScenaFramework.get_instance()
    fw.mouse._sync_position(1e200, -1e200)
    fw.mouse._pressed_buttons[0] = True
    fw.keys._pressed_keys["SPACE"] = True
    fw.keys._input_masked = True

    def undo():
        fw.mouse._pressed_buttons.pop(0, None)
        fw.keys._pressed_keys.pop("SPACE", None)
        fw.keys._input_masked = False
        fw.mouse._sync_position(0.0, 0.0)
    return undo


def kept_settings() -> Undo:
    """Preferences an act change keeps: quality, cull, framerate, mute."""
    saved = (canvas.fx_quality, canvas.cull_offscreen, canvas.framerate, scena.audio.muted)
    canvas.fx_quality = "low"
    canvas.cull_offscreen = False
    canvas.framerate = 30
    scena.audio.muted = True

    def undo():
        canvas.fx_quality, canvas.cull_offscreen, canvas.framerate, scena.audio.muted = saved
    return undo


def world_settings() -> Undo:
    """Settings an act change restores, left changed by an earlier test."""
    from scena.act import WORLD_SETTINGS
    from scena import Vignette, set_defaults
    from scena import Stars
    saved = [(w, w.snapshot()) for w in WORLD_SETTINGS]
    canvas.zoom_to(2.0)
    canvas.pan_by(30, -20)
    clock.scale = 2.0
    set_defaults("red", line_width=3.0)
    canvas.playfield.pad = 50
    canvas.effects.add(Vignette())
    canvas.effects.enabled = False
    canvas.background = "maroon"
    canvas.background.add(Stars())
    canvas.background.enabled = False
    scena.collision.resolve_enabled = False
    scena.collision.floor = True
    canvas.layers.create("suja", below="default")
    canvas.layers.default = "suja"
    scena.ui.stack_origin(321, 123)

    def undo():
        with quiet():
            for w, v in saved:
                try:
                    w.restore(v)
                except Exception:
                    pass
            canvas.layers["suja"].delete()
    return undo


DIRTY: Dict[str, Callable[[], Undo]] = {
    "live_shapes": live_shapes,
    "shapes_with_work": shapes_with_work,
    "stale_widget": stale_widget,
    "learned_group_names": learned_group_names,
    "junk_pointer": junk_pointer,
    "kept_settings": kept_settings,
    "world_settings": world_settings,
}


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def _check(tc: unittest.TestCase, cell: str, program: str, scenario: str, msgs: List[str]) -> None:
    key = f"{cell} | {program} | {scenario}"
    if msgs:
        reason = KNOWN.get(key)
        if reason is None:
            tc.fail("\n".join(msgs))
        tc.skipTest(f"known: {reason}")
    elif key in KNOWN and FULL:
        tc.fail(f"KNOWN entry no longer fails; remove it: {key!r}")


def _pairs() -> List[Tuple[str, str]]:
    names = list(PROGRAMS)
    if FULL:
        return [(a, b) for a in names for b in names]
    n = len(names)
    return [(names[i], names[(i + 1) % n]) for i in range(n)]


def _after(tc: unittest.TestCase, a: str, b: str) -> None:
    """B after A reads like B alone."""
    for sc in b_scenarios(b):
        alone(b, sc)                      # taken before A ran
    before = process_snapshot(collect=False)
    _run(a, spec(a), PROGRAMS[a])
    after_a = process_snapshot(collect=False)
    for sc in b_scenarios(b):
        with tc.subTest(scenario=sc):
            t = trace_of(b, sc)
            msgs = compare(b, sc, t, f"after {a}/{PROGRAMS[a]}")
            moved = snapshot_diff(before, after_a)
            if msgs and moved:
                msgs.append(f"process state {a} left changed: {moved}")
            _check(tc, f"after {a}", b, sc, msgs)


def _dirty(tc: unittest.TestCase, cell: str, program: str) -> None:
    """B with a test module's leftovers in the process reads like B alone."""
    for sc in b_scenarios(program):
        alone(program, sc)
    undo = DIRTY[cell]()
    try:
        for sc in b_scenarios(program):
            with tc.subTest(scenario=sc):
                t = trace_of(program, sc)
                _check(tc, cell, program, sc,
                       compare(program, sc, t, f"with {cell}", classify=False))
    finally:
        undo()
        with quiet():
            from scena.act import _reset_act_manager
            _reset_act_manager()


def _given_back(tc: unittest.TestCase, program: str) -> None:
    """A run leaves the process-wide state as it found it (snapshot keys)."""
    warm()
    before = process_snapshot()
    _run(program, spec(program), PROGRAMS[program])
    moved = snapshot_diff(before, process_snapshot())
    _check(tc, "given_back", program, PROGRAMS[program],
           [f"{k}: {v[0]} -> {v[1]}" for k, v in moved.items()])


def program_case_name(program: str) -> str:
    """``examples/cadeia_de_bolas`` → ``TestCadeiaDeBolas``."""
    return "Test" + "".join(w.capitalize() for w in _ident(program).split("_"))


def _program_case(b: str) -> type:
    """Every cell where ``b`` is the program read: ``test_after_<a>`` (order
    pairs: every A at ci, the chain neighbour at dev), ``test_with_<cell>``
    (dirty predecessors) and ``test_given_back``. One class per program, so
    the gate's SPLIT runs each as its own job and B's alone traces are taken
    once per job (the module was one ~150 s job)."""
    body: Dict[str, Any] = {
        "__doc__": f"``{b}`` reads the same whatever ran before it, and gives the process back.",
        "__module__": __name__,
        "PROGRAM": b,
        "maxDiff": None,
    }
    for a, b2 in _pairs():
        if b2 == b:
            body[f"test_after_{_ident(a)}"] = (lambda a_: lambda self: _after(self, a_, b))(a)
    if FULL or b in DIRTY_PROGRAMS_DEV:
        for cell in DIRTY:
            body[f"test_with_{cell}"] = (lambda c: lambda self: _dirty(self, c, b))(cell)
    body["test_given_back"] = lambda self: _given_back(self, b)
    return type(program_case_name(b), (unittest.TestCase,), body)


PROGRAM_CASES = [_program_case(p) for p in PROGRAMS]
globals().update({case.__name__: case for case in PROGRAM_CASES})


class TestAxes(unittest.TestCase):
    """The tables name real programs and scenarios; the pair set covers them."""

    def test_every_program_module_has_a_row(self):
        from source_support import iter_files
        here = os.path.dirname(os.path.abspath(__file__))
        mods = sorted(os.path.basename(f)[len("test_prog_"):-3]
                      for f in iter_files(here, ".py", recursive=False)
                      if os.path.basename(f).startswith("test_prog_"))
        rows = {_ident(p) for p in PROGRAMS}
        missing = [m for m in mods if m not in rows and m not in ("compose", "isolation", "invariance")]
        self.assertFalse(missing, f"program modules with no isolation row: {missing}")

    def test_predecessor_scenarios_exist(self):
        for p, sc in PROGRAMS.items():
            self.assertIn(sc, spec(p)["SCENARIOS"], p)

    def test_pairs_cover_every_program_as_a_and_as_b(self):
        pairs = _pairs()
        self.assertEqual({a for a, _ in pairs}, set(PROGRAMS))
        self.assertEqual({b for _, b in pairs}, set(PROGRAMS))

    def test_every_program_has_its_own_class(self):
        self.assertEqual([case.PROGRAM for case in PROGRAM_CASES], list(PROGRAMS))
        names = [case.__name__ for case in PROGRAM_CASES]
        self.assertEqual(len(set(names)), len(names), "two programs share a class name")
        fixed = {"TestAxes", "TestResetWorldSettings", "TestCanaries"}
        for case in PROGRAM_CASES:
            self.assertIs(globals()[case.__name__], case)
            self.assertNotIn(case.__name__, fixed)
        pairs = sum(1 for case in PROGRAM_CASES for n in dir(case) if n.startswith("test_after_"))
        self.assertEqual(pairs, len(_pairs()))

    def test_known_keys_name_real_cells(self):
        cells = {f"after {p}" for p in PROGRAMS} | set(DIRTY) | {"given_back"}
        for key in KNOWN:
            cell, program, _sc = [s.strip() for s in key.split("|")]
            self.assertIn(cell, cells, key)
            self.assertIn(program, PROGRAMS, key)


class TestResetWorldSettings(unittest.TestCase):
    """``system_support.reset_world_settings`` reaches every act-restored
    setting (a new ``WORLD_SETTINGS`` row without a reset fails), and the
    dirty cell changes every one of them (the guard guards itself)."""

    def test_every_setting_is_dirtied_and_reset(self):
        from scena.act import WORLD_SETTINGS
        from system_support import reset_world_settings
        def key(v, depth=4):
            # A default is a fresh object each reset: compare its fields
            # (``__dict__`` and slots, a few levels down), not its identity.
            if isinstance(v, (int, float, str, bool, type(None))):
                return repr(v)
            if isinstance(v, (tuple, list)):
                return "[" + ", ".join(key(x, depth) for x in v) + "]"
            if depth == 0:
                return type(v).__name__
            fields = {}
            fields.update(getattr(v, "__dict__", {}))
            for cls in type(v).__mro__:
                for name in getattr(cls, "__slots__", ()):
                    if name != "__dict__" and hasattr(v, name):
                        fields[name] = getattr(v, name)
            if not fields:
                return type(v).__name__
            inner = ", ".join(f"{n}={key(x, depth - 1)}" for n, x in sorted(fields.items()))
            return f"{type(v).__name__}({inner})"

        warm()
        reset_world_settings()
        clean = {w.name: key(w.snapshot()) for w in WORLD_SETTINGS}
        undo = DIRTY["world_settings"]()
        try:
            dirty = {w.name: key(w.snapshot()) for w in WORLD_SETTINGS}
            same = [n for n in clean if clean[n] == dirty[n]]
            self.assertFalse(same, f"the dirty cell leaves these settings unchanged: {same}")
            reset_world_settings()
            back = {w.name: key(w.snapshot()) for w in WORLD_SETTINGS}
            self.assertEqual(back, clean)
        finally:
            undo()


class TestCanaries(unittest.TestCase):
    """The cells fail when a reset is dropped (prove they can fail). The
    engine samples the pointer every frame, so a planted pointer leak cannot
    reach a trace; the plants are on the resets the harness owns."""

    def test_dirty_cell_catches_world_settings_that_are_not_reset(self):
        assert_catches(self, "test_prog_isolation.TestNaves.test_with_world_settings",
                       [("program_support", "reset_world_settings", lambda: None)],
                       "a playfield pad left by an earlier test (it decides which shots survive)")

    def test_given_back_catches_a_pointer_that_is_not_given_back(self):
        from scena.input import Mouse
        assert_catches(self, "test_prog_isolation.TestCadeiaDeBolas.test_given_back",
                       [(Mouse, "_sync_position", lambda self, x, y: None)],
                       "the pointer left where the program moved it")

if __name__ == "__main__":
    unittest.main()
