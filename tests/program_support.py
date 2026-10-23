"""Program model harness: run a whole author program headless, record a trace, check a spec.

Not a test module (no ``test_`` prefix). Strategy and the divergence protocol:
design/Testing Design.md, "Program model tests".

A **program** is an author script in ``tests/programs/<name>.py``, written the way
authors write (``from scena import *``, top-level code, ``update(dt)``, ``on_key``,
widgets, ``run()``). It may read two injected globals, both optional so the
script also runs on its own:

* ``PARAMS`` — a dict of fuzzable choices (counts, sizes, seeds). Read it with
  ``PARAMS.get("count", 30)``; it is ``{}`` when the script runs standalone.
* ``mark(name, **data)`` — records an event in the trace (a no-op standalone).

A **spec** (``tests/programs/<name>_spec_<x>.py``) is written from the docs, not
from the engine. It declares:

* ``PROBES`` — ``{name: fn(p)}``: author-level reads evaluated after every frame.
  ``p`` exposes the program's globals as attributes (``p.group["ball"]``,
  ``p.roda.center``, ``p.st.count``). A probe that raises records a ``ProbeError``.
* ``SCENARIOS`` — ``{name: Scenario(params=…, steps=[…])}``: steps are
  ``wait(n)``, ``wait_s(t)``, ``click_widget(label)``, ``click(x, y)``,
  ``key(name, frames=1)``, ``key_down`` / ``key_up``, ``move(x, y)``,
  ``scroll(dy)``, ``set_cell(path, value)``. Coordinates are view (design) units, y up.
* ``EXPECT`` — a list of ``Expect(id, level, cite, check, scenarios=…, guess=False)``.
  ``check(t)`` receives the ``Trace`` and returns ``None`` (pass) or a message
  (fail); the helpers below (``always``, ``never``, ``at``, ``eventually``, …)
  return exactly that.

Levels: L0 exact discrete, L1 analytic (with a tolerance), L2 invariant/bound,
L3 metamorphic (``program_oracles``).

Input goes through the same handlers GLFW callbacks call
(``ScenaFramework._handle_key`` / ``_handle_mouse_button`` / …), delivered from
inside the frame's ``glfw.poll_events`` — the point where a windowed run sees it.
"""
from __future__ import annotations

import inspect
import math
import os
import random
import runpy
import weakref
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import quiet, registry  # noqa: E402
from surface_support import CURSOR_KEYS, census_diff, reset_background_base, surface_census  # noqa: E402
from system_support import FRAME, SystemWorld, reset_input_state, reset_world_settings  # noqa: E402

import glfw  # noqa: E402
import scena  # noqa: E402
import scena.orchestration as orch  # noqa: E402
from scena import clock, stall  # noqa: E402
from scena.input import _GLFW_NAMED_KEYS  # noqa: E402
from scena.state import Attribute, get_scena_system  # noqa: E402

PROGRAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "programs")

_KEY_CODES: Dict[str, int] = {name: code for code, name in _GLFW_NAMED_KEYS.items()}


class PressedTwice(AssertionError):
    """The run was asked to send a key press for a key already down."""


def note_press(held: set, code: int, name: str) -> None:
    """A press of ``code`` joins ``held``; a second press with no release
    raises: a window never sends one (GLFW turns it into a REPEAT), and the
    I1 model would read it as an engine fault (``key-down-twice``, chaos
    caverna/volta: a pilot that tapped two keys in one frame)."""
    if code in held:
        raise PressedTwice(f"key {name}: a second press with no release; a window sends "
                           "REPEAT here: the pilot or the script pressed twice")
    held.add(code)

# The ``mods`` bit of each modifier key.
_MOD_BITS: Dict[int, int] = {
    glfw.KEY_LEFT_SHIFT: glfw.MOD_SHIFT, glfw.KEY_RIGHT_SHIFT: glfw.MOD_SHIFT,
    glfw.KEY_LEFT_CONTROL: glfw.MOD_CONTROL, glfw.KEY_RIGHT_CONTROL: glfw.MOD_CONTROL,
    glfw.KEY_LEFT_ALT: glfw.MOD_ALT, glfw.KEY_RIGHT_ALT: glfw.MOD_ALT,
    glfw.KEY_LEFT_SUPER: glfw.MOD_SUPER, glfw.KEY_RIGHT_SUPER: glfw.MOD_SUPER,
}
for _c in range(glfw.KEY_A, glfw.KEY_Z + 1):
    _KEY_CODES[chr(_c)] = _c
for _c in range(glfw.KEY_0, glfw.KEY_9 + 1):
    _KEY_CODES[chr(_c)] = _c

_INPUT_CALLBACKS = (
    "on_key_down", "on_key_up", "on_key", "on_char",
    "on_mouse_down", "on_mouse_up", "on_mouse_click", "on_mouse_double_click",
    "on_mouse_move", "on_mouse_drag", "on_mouse_scroll",
)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def program_path(name: str) -> str:
    """``"bouncing_balls"`` -> tests/programs/; ``"examples/naves_1.py"`` -> repo-relative
    (a taught example runs in place, next to its ``media/``); absolute stays."""
    if not name.endswith(".py"):
        name += ".py"
    if os.path.isabs(name):
        return name
    if "/" in name:
        return os.path.join(ROOT, *name.split("/"))
    return os.path.normpath(os.path.join(PROGRAMS, name))


# --------------------------------------------------------------------------
# Probe values
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ProbeError:
    """A probe read raised: an author read failing mid-run is itself a finding."""
    kind: str
    message: str

    def __repr__(self) -> str:
        return f"ProbeError({self.kind}: {self.message})"


def _plain(v: Any) -> Any:
    """Freeze a probe value so later frames cannot mutate it (Vec2 -> tuple,
    a cell -> its value)."""
    if isinstance(v, Attribute):
        v = v.value
    if isinstance(v, (bool, int, float, str, type(None), ProbeError)):
        return v
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        out = [_plain(x) for x in v]
        return tuple(sorted(out, key=repr)) if isinstance(v, (set, frozenset)) else tuple(out)
    x, y = getattr(v, "x", None), getattr(v, "y", None)
    if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not callable(x):
        return (float(x), float(y))
    try:
        return float(v)
    except Exception:
        return repr(v)


_SERIALS = {"map": weakref.WeakKeyDictionary(), "next": 0}


def serial(obj) -> int:
    """A per-run identity for ``obj`` (0, 1, 2… in first-seen order).

    Use it in probes instead of ``id()``: an id is reused once an object is
    freed (a rebuilt ball can carry a dead ball's id) and differs between
    runs, so the replay / twin oracles could not compare it. Numbers are never
    reused within a run; ``ProgramRun.start`` resets them.
    """
    m = _SERIALS["map"]
    if obj not in m:
        m[obj] = _SERIALS["next"]
        _SERIALS["next"] += 1
    return m[obj]


class ProgramView:
    """``p`` in a probe: the program's globals as attributes."""

    def __init__(self, ns: Dict[str, Any]) -> None:
        object.__setattr__(self, "_ns", ns)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._ns[name]
        except KeyError:
            raise AttributeError(f"program has no global {name!r}") from None

    def __setattr__(self, name, value):
        raise AttributeError("probes are read-only")


# --------------------------------------------------------------------------
# Trace
# --------------------------------------------------------------------------

@dataclass
class Sample:
    frame: int            # frames stepped since the game began (1 = after the first frame)
    time: float           # clock.time after that frame
    values: Dict[str, Any]


@dataclass
class Event:
    frame: int
    time: float
    name: str
    data: Dict[str, Any]


class Trace:
    """What a run did: one ``Sample`` per frame plus ``mark`` events and input steps."""

    def __init__(self) -> None:
        self.samples: List[Sample] = []
        self.events: List[Event] = []
        self.inputs: List[Tuple[int, str]] = []    # (frame delivered, description)
        self.scenario: str = ""
        self.params: Dict[str, Any] = {}

    # -- reads ----------------------------------------------------------
    def series(self, name: str) -> List[Tuple[int, float, Any]]:
        return [(s.frame, s.time, s.values.get(name)) for s in self.samples]

    def values(self, name: str) -> List[Any]:
        return [s.values.get(name) for s in self.samples]

    def end(self, name: str) -> Any:
        return self.samples[-1].values.get(name) if self.samples else None

    def at_frame(self, frame: int, name: str) -> Any:
        for s in self.samples:
            if s.frame == frame:
                return s.values.get(name)
        raise KeyError(f"no sample at frame {frame}")

    def at_time(self, t: float, name: str) -> Any:
        """Value at the first sample whose time is >= t."""
        for s in self.samples:
            if s.time >= t - 1e-9:
                return s.values.get(name)
        raise KeyError(f"run ended before t={t}")

    def input_frame(self, prefix: str, nth: int = 0) -> int:
        hits = [f for f, d in self.inputs if d.startswith(prefix)]
        if len(hits) <= nth:
            raise KeyError(f"no input {prefix!r} #{nth}; inputs: {self.inputs}")
        return hits[nth]

    def press_frame(self, name: str, nth: int = 0) -> int:
        """Frame the nth press of key ``name`` (``"R"``, ``"SPACE"``) or mouse
        button (``"left"``) was delivered. Releases are not counted."""
        return self._edge_frame(name, nth, glfw.PRESS)

    def release_frame(self, name: str, nth: int = 0) -> int:
        """Frame the nth release of key or mouse button ``name`` was delivered."""
        return self._edge_frame(name, nth, glfw.RELEASE)

    def _edge_frame(self, name: str, nth: int, action: int) -> int:
        button = _BUTTONS.get(name)
        hits = []
        for f, d in self.inputs:
            kind, _, rest = d.partition(" ")
            if kind == "key" and rest == repr((name.upper() if len(name) == 1 else name, action)):
                hits.append(f)
            elif kind == "button" and button is not None and rest == repr((button, action)):
                hits.append(f)
        if len(hits) <= nth:
            raise KeyError(f"no {'press' if action == glfw.PRESS else 'release'} #{nth} "
                           f"of {name!r}; inputs: {self.inputs}")
        return hits[nth]

    def marks(self, name: str) -> List[Event]:
        return [e for e in self.events if e.name == name]

    def errors(self) -> List[Tuple[int, str, ProbeError]]:
        out = []
        for s in self.samples:
            for k, v in s.values.items():
                if isinstance(v, ProbeError):
                    out.append((s.frame, k, v))
        return out


# --------------------------------------------------------------------------
# Spec vocabulary
# --------------------------------------------------------------------------

@dataclass
class Scenario:
    steps: Sequence[Tuple] = ()
    params: Dict[str, Any] = field(default_factory=dict)
    seed: int = 0
    dt: float = FRAME


def wait(n: int = 1):
    return ("wait", int(n))


def wait_s(t: float):
    return ("wait_s", float(t))


def click_widget(label: str):
    return ("click_widget", label)


def click(x: float, y: float, button: str = "left"):
    return ("click", float(x), float(y), button)


def drag(x0: float, y0: float, x1: float, y1: float, frames: int = 5, button: str = "left"):
    """Press at (x0, y0), move to (x1, y1) over ``frames`` frames, release there."""
    return ("drag", float(x0), float(y0), float(x1), float(y1), int(frames), button)


def key(name: str, frames: int = 1):
    return ("key", name, int(frames))


def key_down(name: str):
    return ("key_down", name)


def key_up(name: str):
    return ("key_up", name)


def move(x: float, y: float):
    return ("move", float(x), float(y))


def scroll(dy: float, dx: float = 0.0):
    return ("scroll", float(dx), float(dy))


def set_cell(path: str, value: Any):
    """Write an author cell between frames, as a widget would (``"st.count"``)."""
    return ("set_cell", path, value)


def drive(factory: Callable[[], Callable[["ProgramRun"], None]], frames: int):
    """Run ``frames`` frames under a pilot: ``factory()`` builds a fresh pilot
    per run (replay oracles run the scenario twice), and ``pilot(run)`` is
    called before each frame to queue input from what it reads. A pilot that
    holds keys lists them in ``pilot.held``; they are released at the end.
    Deterministic as long as the pilot is (no clock, no ``id()``)."""
    return ("drive", factory, int(frames))


@dataclass
class Expect:
    id: str
    level: str                      # "L0" | "L1" | "L2"
    cite: str                       # doc anchor, or a sentence for GUESS
    check: Callable[[Trace], Optional[str]]
    scenarios: Sequence[str] = ("*",)
    guess: bool = False
    revised: str = ""               # cause code when changed after seeing the engine
    text: str = ""                  # the claim in words

    def applies(self, scenario: str) -> bool:
        return "*" in self.scenarios or scenario in self.scenarios


def _fmt(v: Any) -> str:
    s = repr(v)
    return s if len(s) < 200 else s[:200] + "…"


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def close(a: Any, b: Any, tol: float = 1e-6) -> bool:
    """Structural approximate equality (numbers within ``tol``, tuples element-wise)."""
    if _numeric(a) and _numeric(b):
        return math.isclose(a, b, rel_tol=tol, abs_tol=tol)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    return a == b


def always(name: str, pred: Callable[[Any], bool], *, after: int = 0,
           until: Optional[int] = None) -> Callable[[Trace], Optional[str]]:
    """``pred(value)`` holds at every sample with ``after <= frame`` (``<= until``)."""
    def check(t: Trace):
        for s in t.samples:
            if s.frame < after or (until is not None and s.frame > until):
                continue
            v = s.values.get(name)
            if isinstance(v, ProbeError) or not pred(v):
                return f"{name} at frame {s.frame} (t={s.time:.3f}) = {_fmt(v)}"
        return None
    return check


def never(name: str, pred: Callable[[Any], bool], **kw) -> Callable[[Trace], Optional[str]]:
    return always(name, lambda v: not pred(v), **kw)


def at(frame_or_fn, name: str, pred: Callable[[Any], bool]) -> Callable[[Trace], Optional[str]]:
    """``pred`` holds at one frame; ``frame_or_fn`` may be ``fn(trace) -> frame``."""
    def check(t: Trace):
        f = frame_or_fn(t) if callable(frame_or_fn) else frame_or_fn
        v = t.at_frame(f, name)
        return None if not isinstance(v, ProbeError) and pred(v) else \
            f"{name} at frame {f} = {_fmt(v)}"
    return check


def at_end(name: str, pred: Callable[[Any], bool]) -> Callable[[Trace], Optional[str]]:
    def check(t: Trace):
        v = t.end(name)
        return None if not isinstance(v, ProbeError) and pred(v) else \
            f"{name} at end (frame {t.samples[-1].frame}) = {_fmt(v)}"
    return check


def eventually(name: str, pred: Callable[[Any], bool], *, after: int = 0,
               within: Optional[int] = None) -> Callable[[Trace], Optional[str]]:
    """Some sample with frame in ``[after, after + within]`` satisfies ``pred``."""
    def check(t: Trace):
        a = after(t) if callable(after) else after
        last = None
        for s in t.samples:
            if s.frame < a:
                continue
            if within is not None and s.frame > a + within:
                break
            last = s
            v = s.values.get(name)
            if not isinstance(v, ProbeError) and pred(v):
                return None
        lv = None if last is None else last.values.get(name)
        return f"{name} never satisfied after frame {a}" + \
            (f" within {within} frames" if within is not None else "") + f"; last = {_fmt(lv)}"
    return check


def steady(name: str, *, after: int = 0, tol: float = 0.0) -> Callable[[Trace], Optional[str]]:
    """The value does not change from frame ``after`` on."""
    def check(t: Trace):
        a = after(t) if callable(after) else after
        ref = None
        for s in t.samples:
            if s.frame < a:
                continue
            v = s.values.get(name)
            if ref is None:
                ref = (s.frame, v)
            elif not close(v, ref[1], tol):
                return f"{name} changed: frame {ref[0]} = {_fmt(ref[1])}, frame {s.frame} = {_fmt(v)}"
        return None
    return check


def all_of(*checks) -> Callable[[Trace], Optional[str]]:
    def check(t: Trace):
        for c in checks:
            m = c(t)
            if m:
                return m
        return None
    return check


def custom(fn: Callable[[Trace], Any]) -> Callable[[Trace], Optional[str]]:
    """Wrap ``fn(trace)`` that returns True/None (pass) or False/str (fail)."""
    def check(t: Trace):
        r = fn(t)
        if r is True or r is None:
            return None
        return r if isinstance(r, str) else f"{getattr(fn, '__name__', 'check')} failed"
    return check


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

class ProgramRun:
    """Run one program in a ``SystemWorld``; feed input; sample probes per frame.

    ``with ProgramRun("bouncing_balls", params) as run: run.step(60)``.
    """

    def __init__(self, program: str, params: Optional[Dict[str, Any]] = None, *,
                 probes: Optional[Dict[str, Callable]] = None, seed: int = 0,
                 dt: float = FRAME, draw: bool = False,
                 source: Optional[str] = None) -> None:
        self.path = program_path(program)
        self.name = os.path.splitext(os.path.basename(self.path))[0]
        self.params = dict(params or {})
        self.probes = dict(probes or {})
        self.seed = seed
        self.dt = dt
        self.draw = draw
        # Tier C: run rewritten source as if it were the program file (same
        # path for media, cwd and made_at).
        self.source = source
        # Metamorphic oracles: a callable run after the world reset and before
        # the program's first line (a camera move, a clock scale), as if the
        # process had started that way.
        self.prelude: Optional[Callable[["ProgramRun"], None]] = None
        # Chaos doors (tests/laws/chaos.py): an AST rewrite of the program
        # (``tree -> tree``, every node keeps its line) compiled under the
        # program's own path, and names put in its namespace before it runs.
        self.transform: Optional[Callable[[Any], Any]] = None
        self.inject: Dict[str, Any] = {}
        self.trace = Trace()
        self.trace.params = dict(self.params)
        self.ns: Dict[str, Any] = {}
        self.view: Optional[ProgramView] = None
        self._pending: List[Tuple[str, tuple]] = []
        self._held_keys: set = set()      # GLFW codes down (the ``mods`` they carry)
        self._cursor = [0.0, 0.0]
        self._patches: List[Any] = []
        self.world: Optional[SystemWorld] = None
        self.frames = 0
        # play(): every frame count is multiplied by ``stretch`` (with dt divided
        # by it, inputs land at the same times — the dt-split oracle).
        self.stretch = 1

    # -- lifecycle --------------------------------------------------------
    def __enter__(self) -> "ProgramRun":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close(strict=exc_type is None)

    def start(self) -> None:
        try:
            self._start()
        except BaseException:
            self.close(strict=False)     # never leave __main__ / cwd / patches behind
            raise

    def _start(self) -> None:
        _SERIALS["map"] = weakref.WeakKeyDictionary()
        _SERIALS["next"] = 0
        random.seed(self.seed)
        # Leftovers from other modules are parked only after census_before:
        # teardown resumes them before census_after, so both censuses must
        # see them active (else every parked drawn actor reads as a leak).
        self.world = SystemWorld(draw=self.draw, quarantine=False)
        fw = self.world.fw
        self._roster_before = set(registry().live.keys())
        # The program starts with an empty ``st``, as in its own process: the
        # cells other modules left are parked and given back at close. A
        # program that wrote ``st.pontos`` over a leftover cell reused it, and
        # the node it gave that cell (a link, a lazy registration) outlived
        # the run as a graph leftover (deep serial pass 2026-10-22).
        self._st_parked = dict(scena.st._data)
        scena.st._data.clear()
        self._st_before = set()
        reg = registry()
        # Group names are remembered process-wide (did-you-mean hints): one
        # program per process in real use, so each run starts from the names
        # known before it and gives back the ones it taught.
        self._groups_before = (set(reg._group_gen), set(reg._declared_groups))
        # A fresh keyboard, mouse, pointer and HUD cursor (SystemWorld's
        # reset ran it too; once more right before the census is cheap).
        reset_input_state()
        # Every world setting an act change restores (camera, playfield,
        # background, effects, clock, collision, audio …): a program sets them
        # for the whole process, so give the next run the values from before
        # this one (the playfield of one run leaked into the next, unnoticed
        # until a spec read it on the frame before the program set its own).
        from scena.act import WORLD_SETTINGS
        self._settings_before = [(w, w.snapshot()) for w in WORLD_SETTINGS]
        # ... and start from the framework defaults, as a fresh process would:
        # a playfield pad or paint default another suite left is not this
        # program's world (test_prog_isolation, dirty predecessors).
        reset_world_settings()
        # Given back at close: the pointer and the design size (init()).
        self._pointer_before = (fw.mouse._x, fw.mouse._y)
        self._size_before = (fw.design_width, fw.design_height)
        self.census_before = surface_census()
        ss = get_scena_system()
        self._graph_before = set(ss.dependency_graph.nodes) if ss is not None else set()
        self.world.quarantine()
        cm = fw.canvas_manager
        self._saved_input = {n: getattr(cm, n, None) for n in _INPUT_CALLBACKS}
        self._saved_run = scena.run
        self._saved_cwd = os.getcwd()
        run = self

        def headless_run(first_act=None):
            # The real run() ends the top-level stall phase: left at "top"
            # (reported), the next program's init() could not begin it, and
            # its own slow loading went unreported.
            stall.top_level_end()
            caller = inspect.currentframe().f_back.f_globals
            fw._first_act = first_act
            fw.set_auto_callbacks(caller)
            fw._begin_game(first_act)
            run._began = True

        self._began = False
        scena.run = headless_run
        for target, attr, new in (
            (orch.glfw, "get_cursor_pos", lambda _w: (self._cursor[0], self._cursor[1])),
            (orch.glfw, "poll_events", self._deliver),
        ):
            p = mock.patch.object(target, attr, new=new)
            p.start()
            self._patches.append(p)
        # The program is __main__ for the whole run, with its folder as cwd:
        # media resolve next to the script (sprite._script_dir) also for art
        # loaded during frames, and the namespace probes read is the live one
        # (runpy.run_path would hand back a copy and restore __main__).
        import types
        mod = types.ModuleType("__main__")
        mod.__file__ = self.path
        mod.__dict__.update(PARAMS=dict(self.params), mark=self._mark)
        mod.__dict__.update(self.inject)
        self._saved_main = sys.modules.get("__main__")
        sys.modules["__main__"] = mod
        if self.source is not None:
            source = self.source
        else:
            with open(self.path, encoding="utf-8") as fh:
                source = fh.read()
        # "# harness: cwd=examples/media" in a copied draft: its art lives in the
        # taught media folder (resolved from the cwd, the last image candidate).
        cwd = os.path.dirname(self.path)
        for line in source.splitlines()[:40]:
            if line.startswith("# harness: cwd="):
                cwd = os.path.join(ROOT, *line.split("=", 1)[1].strip().split("/"))
        exec_path = self.path
        if self.source is not None:
            # Rewritten source runs from a temporary file with the same base
            # name: tools that read a function's text from disk (the @=
            # formula checker parses the file) must see the rewritten lines.
            # Art resolves from the cwd: the original's media/ folder.
            import tempfile
            self._tmpdir = tempfile.TemporaryDirectory(prefix="tier_c_")
            exec_path = os.path.join(self._tmpdir.name, os.path.basename(self.path))
            with open(exec_path, "w", encoding="utf-8") as fh:
                fh.write(source)
            # Data files that sit next to the program (a game's level file)
            # travel with it: "next to the script" must still find them.
            import shutil
            from source_support import iter_files
            for data in iter_files(os.path.dirname(self.path), ".json", recursive=False):
                shutil.copy(data, os.path.join(self._tmpdir.name, os.path.basename(data)))
            media = os.path.join(os.path.dirname(self.path), "media")
            if cwd == os.path.dirname(self.path) and os.path.isdir(media):
                cwd = media
            mod.__file__ = exec_path
        os.chdir(cwd)
        if self.prelude is not None:
            self.prelude(self)
        if self.transform is not None:
            import ast
            code = compile(self.transform(ast.parse(source, exec_path)), exec_path, "exec")
        else:
            code = compile(source, exec_path, "exec")
        self.ns = mod.__dict__
        exec(code, self.ns)
        if not self._began:
            raise AssertionError(f"{self.name}: the program never called run()")
        self.view = ProgramView(self.ns)
        self.trace.inputs.clear()

    def close(self, strict: bool = True) -> None:
        """Undo the program: destroy what it made, drop its cells and background.

        ``self.census_after`` is then comparable with ``census_before``
        (``leftovers()``): a program that leaves state behind is a finding.
        """
        try:
            if self.world is not None:
                # Acts end only through the act manager (destroying the
                # current act directly raises ActUsageError): end them first.
                from scena.act import Act, _reset_act_manager
                with quiet():
                    _reset_act_manager()
                # Everything else the program registered: the tracker destroys
                # the owners (parts go with them).
                for k, obj in list(registry().live.items()):
                    if (k not in self._roster_before and getattr(obj, "_owner", None) is None
                            and not isinstance(obj, Act)):
                        self.world.track(obj)
                self.world.teardown(strict=strict)
                with quiet():
                    for k in set(scena.st.keys()) - self._st_before:
                        try:
                            scena.st.remove(k)
                        except Exception:
                            pass
                # The program's world settings go (framework defaults, as at
                # start); what the process had before the run comes back
                # after the census below, so a restored value is never
                # counted as a leftover.
                with quiet():
                    reset_world_settings()
                reg = registry()
                gen, declared = self._groups_before
                for name in set(reg._group_gen) - gen:
                    if name not in reg.group_map:
                        del reg._group_gen[name]
                reg._declared_groups.intersection_update(declared | set(reg.group_map))
                fw = self.world.fw
                fw.mouse._sync_position(*self._pointer_before)
                if (fw.design_width, fw.design_height) != self._size_before:
                    fw.bootstrap(width=self._size_before[0], height=self._size_before[1])
        finally:
            had_world = self.world is not None
            stall.top_level_end()           # a program that never reached run()
            for p in self._patches:
                p.stop()
            self._patches.clear()
            scena.run = self._saved_run
            tmp = getattr(self, "_tmpdir", None)
            if tmp is not None:
                tmp.cleanup()
                self._tmpdir = None
            if getattr(self, "_saved_main", None) is not None:
                sys.modules["__main__"] = self._saved_main
            os.chdir(self._saved_cwd)
            if self.world is not None:
                cm = self.world.fw.canvas_manager
                for n, v in self._saved_input.items():
                    setattr(cm, n, v)
            self._give_back_st()
            self.world = None
            self.ns = {}
            self.view = None
        if had_world:
            # Last: the program's namespace (and the callbacks holding it) is
            # gone, so a value it still referenced (a Box and its Points) is
            # not counted as a leak.
            self.census_after = surface_census()
            with quiet():
                for w, value in getattr(self, "_settings_before", ()):
                    try:
                        w.restore(value)
                    except Exception:
                        pass
            # A Box is a value (canvas.game_view builds one per read); its
            # named Points sit in the live roster while any cache still holds
            # the Box. Not something the program made and failed to destroy.
            values = sum(1 for k, o in list(registry().live.items())
                         if k not in self._roster_before
                         and type(getattr(o, "_owner", None)).__name__ == "Box")
            if values:
                self.census_after = dict(self.census_after)
                self.census_after["registry.live"] -= values
            # A global object (clock, mouse, keyp, st …) joins the dependency
            # graph the first time any formula reads it, once per process.
            ss = get_scena_system()
            if ss is not None:
                globals_ = {id(getattr(scena, n)) for n in scena.__all__
                            if not inspect.isclass(getattr(scena, n, None))
                            and not callable(getattr(scena, n, None))}
                globals_ |= {id(scena.clock), id(scena.mouse), id(scena.keyp), id(scena.st)}
                firsts = sum(1 for k in ss.dependency_graph.nodes
                             if k not in self._graph_before and k in globals_)
                if firsts:
                    self.census_after = dict(self.census_after)
                    self.census_after["graph.nodes"] -= firsts
                # The same Box values in the dependency graph (the Box and the
                # Points it owns, with the edges between them): a value a cache
                # still holds is not a node the program failed to release. Found
                # by the game system tests (a formation Box, read through a
                # Grid, still held at the close of a run that ended mid-act;
                # whether it was depended on GC timing).
                g = ss.dependency_graph
                box_ids = set()
                for k in list(g.nodes):
                    if k in self._graph_before:
                        continue
                    o = g.nodes.get(k)
                    if o is not None and (type(o).__name__ == "Box"
                                          or type(getattr(o, "_owner", None)).__name__ == "Box"):
                        box_ids.add(k)
                if box_ids:
                    self.census_after = dict(self.census_after)
                    self.census_after["graph.nodes"] -= len(box_ids)
                    for key, table in (("graph.dependencies", g.dependencies),
                                       ("graph.dependents", g.dependents)):
                        self.census_after[key] -= sum(len(table.get(k, ())) for k in box_ids)
                    self.census_after["graph.dep_keys"] -= sum(
                        1 for k in box_ids if g.dependencies.get(k))

    def _give_back_st(self) -> None:
        """Put back the ``st`` cells parked at start (over any the program left)."""
        parked = getattr(self, "_st_parked", None)
        if parked is None:
            return
        self._st_parked = None
        data = scena.st._data
        with quiet():
            for k, cell in parked.items():
                mine = data.get(k)
                if mine is not None and mine is not cell:
                    try:
                        scena.st.remove(k)
                    except Exception:
                        data.pop(k, None)
                data[k] = cell

    def leftovers(self) -> Dict[str, Tuple[Any, Any]]:
        """Census keys that moved between program start and ``close()``.

        Layout cursors advance on placement and are not rewound by destroy
        (``surface_support.CURSOR_KEYS``): not a leak.
        """
        return {k: v for k, v in census_diff(self.census_before, self.census_after).items()
                if v[0] != v[1] and k not in CURSOR_KEYS}

    # -- events -----------------------------------------------------------
    def _mark(self, name: str, **data) -> None:
        self.trace.events.append(Event(self.frames + 1, clock.time, name, dict(data)))

    def _deliver(self, *_a) -> None:
        """Called as ``glfw.poll_events`` inside ``_simulate_frame``."""
        pending, self._pending = self._pending, []
        fw = self.world.fw
        for kind, args in pending:
            self.trace.inputs.append((self.frames + 1, f"{kind} {args}"))
            if kind == "key":
                name, action = args
                code = _KEY_CODES[name]
                # The event carries the modifiers held, as the OS sends them.
                if action == glfw.PRESS:
                    note_press(self._held_keys, code, name)
                elif action == glfw.RELEASE:
                    self._held_keys.discard(code)
                mods = 0
                for held in self._held_keys:
                    mods |= _MOD_BITS.get(held, 0)
                fw._handle_key(None, code, 0, action, mods)
                if action == glfw.PRESS and len(name) == 1 and name.isalnum():
                    fw._handle_char(None, ord(name.lower()))
            elif kind == "move":
                sx, sy = self._to_screen(*args)
                self._cursor[:] = [sx, sy]
                fw._handle_mouse_move(None, sx, sy)
            elif kind == "button":
                button, action = args
                mods = 0
                for held in self._held_keys:
                    mods |= _MOD_BITS.get(held, 0)
                fw._handle_mouse_button(None, button, action, mods)
            elif kind == "scroll":
                fw._handle_mouse_scroll(None, *args)
            elif kind == "cell":
                path, value = args
                obj, attr = self._resolve_cell(path)
                setattr(obj, attr, value)

    def _to_screen(self, vx: float, vy: float) -> Tuple[float, float]:
        fw = self.world.fw
        vs = fw.view_scale or 1.0
        return (vx * vs + fw._letterbox_pad_x,
                (fw.design_height - vy) * vs + fw._letterbox_pad_y)

    def _resolve_cell(self, path: str):
        head, *rest = path.split(".")
        obj = self.ns[head]
        for part in rest[:-1]:
            obj = getattr(obj, part)
        return obj, rest[-1]

    # -- input API (queued; delivered in the next frame's poll) -----------
    def key_down(self, name: str) -> None:
        self._pending.append(("key", (name.upper() if len(name) == 1 else name, glfw.PRESS)))

    def key_up(self, name: str) -> None:
        self._pending.append(("key", (name.upper() if len(name) == 1 else name, glfw.RELEASE)))

    def move(self, x: float, y: float) -> None:
        self._pending.append(("move", (x, y)))

    def press(self, x: float, y: float, button: str = "left") -> None:
        self.move(x, y)
        self._pending.append(("button", (_BUTTONS[button], glfw.PRESS)))

    def release(self, button: str = "left") -> None:
        self._pending.append(("button", (_BUTTONS[button], glfw.RELEASE)))

    def scroll(self, dx: float, dy: float) -> None:
        self._pending.append(("scroll", (dx, dy)))

    def set_cell(self, path: str, value: Any) -> None:
        self._pending.append(("cell", (path, value)))

    def widget(self, label: str):
        """The one live, active widget labelled ``label``.

        A widget another module left behind is parked by the ``SystemWorld``
        quarantine (``active = False``) and cannot be clicked, so it does not
        make the label ambiguous (test_prog_isolation, ``stale_widget``).
        """
        hits = [w for w in self.world.fw.widget_manager.widgets
                if getattr(w, "label", None) == label
                and getattr(w, "is_alive", True) and getattr(w, "active", True)]
        if len(hits) != 1:
            raise AssertionError(f"{len(hits)} widgets labelled {label!r}")
        return hits[0]

    def widget_center(self, label: str) -> Tuple[float, float]:
        """Centre of the widget labelled ``label`` or, failing that, of the
        option ``label`` of an open Menu (view units)."""
        from scena.menu import Menu
        wm = self.world.fw.widget_manager
        if not any(getattr(w, "label", None) == label and getattr(w, "active", True)
                   for w in wm.widgets):
            for m in wm.widgets:
                if isinstance(m, Menu) and label in m._labels:
                    m._sync_anchor()
                    i = m._labels.index(label)
                    gx, gy = m._grid_origin()
                    row, col = divmod(i, m._cols)
                    return (gx + (col + 0.5) * m._cell_w,
                            gy + (m._rows - 1 - row + 0.5) * m._cell_h)
        w = self.widget(label)
        return ((w._x1 + w._x2) / 2.0, (w._y1 + w._y2) / 2.0)

    # -- stepping ---------------------------------------------------------
    def step(self, n: int = 1, dt: Optional[float] = None,
             draw: Optional[bool] = None) -> None:
        """``draw=None`` follows the run's ``draw``; True / False draws (or
        not) these frames only (a game draws at checkpoints)."""
        d = self.dt if dt is None else dt
        if draw or (draw is None and self.world.draw_default):
            self._wire_surface()
        for _ in range(int(n)):
            self.world.step(1, dt=d, draw=draw)
            self.frames += 1
            self.sample()

    def _wire_surface(self) -> None:
        """Point the draw engine at the world's raster surface.

        The program's ``init()`` rebuilds the drawing canvas the engine paints
        on, so after it the engine painted elsewhere and every draw of a
        program read back blank (and ``program_oracles.cull_pixels`` compared
        two blank images). Re-wired before each draw (a program may call
        ``init`` again)."""
        fw = self.world.fw
        surf = self.world.surface
        if fw._drawing_surface is not surf or fw._scena_draw.skia_canvas is not fw._drawing_canvas:
            fw._drawing_surface = surf
            fw._drawing_canvas = surf.getCanvas()
            fw._scena_draw.skia_canvas = fw._drawing_canvas

    def sample(self) -> None:
        values = {}
        for name, fn in self.probes.items():
            try:
                values[name] = _plain(fn(self.view))
            except Exception as e:     # an author read that raises is recorded
                values[name] = ProbeError(type(e).__name__, str(e)[:160])
        self.trace.samples.append(Sample(self.frames, clock.time, values))

    def play(self, steps: Iterable[Tuple]) -> None:
        """Run scenario steps (see ``wait`` / ``click_widget`` / ``key`` …)."""
        for st in steps:
            kind = st[0]
            if kind == "wait":
                self._pstep(st[1])
            elif kind == "wait_s":
                self.step(int(math.ceil(st[1] / self.dt - 1e-9)))
            elif kind == "click_widget":
                # Each half of a click is its own frame, as with a real mouse.
                x, y = self.widget_center(st[1])
                self.press(x, y)
                self._pstep(1)
                self.release()
                self._pstep(1)
            elif kind == "click":
                _k, x, y, button = st
                self.press(x, y, button)
                self._pstep(1)
                self.release(button)
                self._pstep(1)
            elif kind == "drag":
                _k, x0, y0, x1, y1, n, button = st
                self.press(x0, y0, button)
                self._pstep(1)
                for i in range(1, max(1, n) + 1):
                    f = i / max(1, n)
                    self.move(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)
                    self._pstep(1)
                self.release(button)
                self._pstep(1)
            elif kind == "key":
                _k, name, frames = st
                self.key_down(name)
                self._pstep(frames)
                self.key_up(name)
                self._pstep(1)
            elif kind == "key_down":
                self.key_down(st[1])
                self._pstep(1)
            elif kind == "key_up":
                self.key_up(st[1])
                self._pstep(1)
            elif kind == "move":
                self.move(st[1], st[2])
                self._pstep(1)
            elif kind == "scroll":
                self.scroll(st[1], st[2])
                self._pstep(1)
            elif kind == "set_cell":
                self.set_cell(st[1], st[2])
                self._pstep(1)
            elif kind == "drive":
                # A pilot: a fresh one per run (the factory), called before
                # every frame with the run; it reads the world and queues
                # input like a player. Keys it holds are released at the end.
                _k, factory, frames = st
                pilot = factory()
                for _ in range(int(frames) * self.stretch):
                    pilot(self)
                    self.step(1)
                for name in sorted(getattr(pilot, "held", ())):
                    self.key_up(name)
                self.step(1)
            else:
                raise ValueError(f"unknown step {st!r}")


    def _pstep(self, n: int) -> None:
        self.step(int(n) * self.stretch)

_BUTTONS = {"left": glfw.MOUSE_BUTTON_LEFT, "right": glfw.MOUSE_BUTTON_RIGHT,
            "middle": glfw.MOUSE_BUTTON_MIDDLE}


# --------------------------------------------------------------------------
# Spec evaluation
# --------------------------------------------------------------------------

@dataclass
class Divergence:
    program: str
    spec: str
    expect: str
    scenario: str
    level: str
    guess: bool
    message: str

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.program, self.spec, self.expect)

    def __str__(self) -> str:
        g = " GUESS" if self.guess else ""
        return f"{self.program}/{self.spec} {self.expect} [{self.level}{g}] ({self.scenario}): {self.message}"


def spec_base(program: str) -> str:
    """Spec files are named after the program's basename (``naves_1_spec_a.py``)."""
    return os.path.splitext(os.path.basename(program))[0]


def load_spec(program: str, spec: str) -> Dict[str, Any]:
    path = os.path.join(PROGRAMS, f"{spec_base(program)}_spec_{spec}.py")
    return runpy.run_path(path, run_name=f"spec_{program}_{spec}")


def run_scenario(program: str, spec_ns: Dict[str, Any], scenario: str, *,
                 draw: bool = False, dt: Optional[float] = None,
                 params: Optional[Dict[str, Any]] = None,
                 steps: Optional[Sequence[Tuple]] = None) -> Trace:
    sc: Scenario = spec_ns["SCENARIOS"][scenario]
    p = dict(sc.params)
    if params:
        p.update(params)
    with ProgramRun(program, p, probes=spec_ns["PROBES"], seed=sc.seed,
                    dt=sc.dt if dt is None else dt, draw=draw) as run:
        run.trace.scenario = scenario
        run.play(sc.steps if steps is None else steps)
        return run.trace


def evaluate(program: str, spec: str, spec_ns: Dict[str, Any], scenario: str,
             trace: Trace) -> List[Divergence]:
    out = []
    for e in spec_ns["EXPECT"]:
        if not e.applies(scenario):
            continue
        try:
            msg = e.check(trace)
        except Exception as ex:      # a check that cannot read the trace is a divergence too
            msg = f"check raised {type(ex).__name__}: {ex}"
        if msg:
            out.append(Divergence(spec_base(program), spec, e.id, scenario, e.level, e.guess, msg))
    return out


def check_program(program: str, spec: str) -> Tuple[List[Divergence], Dict[str, Trace]]:
    """Every scenario of one spec; returns divergences and the traces."""
    ns = load_spec(program, spec)
    divs, traces = [], {}
    for name in ns["SCENARIOS"]:
        tr = run_scenario(program, ns, name)
        traces[name] = tr
        divs.extend(evaluate(program, spec, ns, name, tr))
    return divs, traces


# --------------------------------------------------------------------------
# Test-module factory
# --------------------------------------------------------------------------

L3_DEFAULT = ("replay", "probe_neutral", "reactive_config", "teardown")


def program_test_case(program: str, specs: Sequence[str] = ("a", "b"), *,
                      l3: Sequence[str] = L3_DEFAULT,
                      l3_scenarios: Optional[Dict[str, Sequence[str]]] = None,
                      dt_split: Optional[Dict[str, Dict[str, float]]] = None,
                      cull_scenarios: Sequence[Tuple[str, str]] = (),
                      tier_c: Sequence[Tuple[str, str]] = ()):
    """Build a ``unittest.TestCase`` for one program.

    * one test per (spec, scenario): every divergence fails, except the ones
      in ``program_ledger.OPEN``, which must still diverge (shrink-only);
    * one test per L3 oracle and (spec, scenario) in ``l3_scenarios``
      (``{spec: [scenario, ...]}``; default: every scenario of the first spec);
    * ``dt_split``: ``{"<spec>/<scenario>": {probe: tol}}``;
    * ``cull_scenarios``: ``[(spec, scenario)]`` drawn with cull on vs off;
    * ``tier_c``: ``[(spec, scenario)]`` re-run as rewritten programs
      (``program_oracles.TIER_C``: group names renamed, defs reordered).
    """
    import unittest
    import program_ledger
    import program_oracles

    def spec_test(letter, scenario):
        def test(self):
            ns = load_spec(program, letter)
            trace = run_scenario(program, ns, scenario)
            divs = evaluate(program, letter, ns, scenario, trace)
            known = {k for k in program_ledger.OPEN if k[0] == spec_base(program) and k[1] == letter}
            new = [d for d in divs if d.key not in known]
            if new:
                self.fail("divergences (triage per tests/program_ledger.py):\n"
                          + "\n".join(f"  {d}" for d in new))
        return test

    def ledger_test(self):
        for letter in specs:
            ns = load_spec(program, letter)
            open_ = {k for k in program_ledger.OPEN if k[0] == spec_base(program) and k[1] == letter}
            if not open_:
                continue
            seen = set()
            for scenario in ns["SCENARIOS"]:
                trace = run_scenario(program, ns, scenario)
                seen |= {d.key for d in evaluate(program, letter, ns, scenario, trace)}
            fixed = open_ - seen
            self.assertFalse(fixed, f"ledger entries that no longer diverge; remove them: {sorted(fixed)}")

    def oracle_test(name, letter, scenario, extra=None):
        def test(self):
            ns = load_spec(program, letter)
            fn = getattr(program_oracles, name)
            msgs = fn(program, ns, scenario, extra) if extra is not None else fn(program, ns, scenario)
            self.assertFalse(msgs, "\n".join(msgs))
        return test

    attrs = {"maxDiff": None, "test_ledger_shrinks": ledger_test}
    for letter in specs:
        ns = load_spec(program, letter)
        for sc in ns["SCENARIOS"]:
            attrs[f"test_spec_{letter}_{sc}"] = spec_test(letter, sc)
    if l3_scenarios is None:
        l3_scenarios = {specs[0]: list(load_spec(program, specs[0])["SCENARIOS"])}
    for letter, scs in l3_scenarios.items():
        for sc in scs:
            for name in l3:
                attrs[f"test_l3_{name}_{letter}_{sc}"] = oracle_test(name, letter, sc)
    for key, tols in (dt_split or {}).items():
        letter, sc = key.split("/")
        attrs[f"test_l3_dt_split_{letter}_{sc}"] = oracle_test("dt_split", letter, sc, tols)
    for letter, sc in cull_scenarios:
        attrs[f"test_l3_cull_pixels_{letter}_{sc}"] = oracle_test("cull_pixels", letter, sc)
    for letter, sc in tier_c:
        for name in program_oracles.TIER_C:
            attrs[f"test_tier_c_{name}_{letter}_{sc}"] = oracle_test("tier_c", letter, sc, name)
    return type(f"TestProgram_{spec_base(program)}", (unittest.TestCase,), attrs)
