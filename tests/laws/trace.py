"""The laws recorder: a discrete trace of one run, taken from outside the engine.

Nothing in ``scena/`` knows about it. It attaches through ``sys.monitoring``
(PEP 669), like ``tests/geom_sentinel.py``: local start / return events on a
table of engine code objects (phase functions, creation, destroy, contact
commit, ...) plus one global start / resume event that keeps only author
functions the engine calls (every callback, whatever door it came through)
and disables itself, code object by code object, everywhere else. No wrapper
frame: the engine reads its own stack for author sites and ``stacklevel``.
When it is not installed, it costs nothing; ``uninstall`` leaves no event set
(``assert_clean``).

Rules (Testing Design, "Laws and equations"):

* **Read raw state only.** ``__dict__`` / slots, never a property (a read can
  pull the reactive graph and change what the run does). E0 (neutrality)
  checks the run with the recorder is the run without it.
* **Hold no references.** Labels are keyed by ``id()`` and re-bound at each
  creation event (an id is reused once its object is freed); a label lookup
  checks the type too.
* **Never raise into the engine.** A callback swallows its own errors and
  counts them (``Recorder.errors``); a test fails on a non-zero count.
* **Never DISABLE a hooked code object.** DISABLE silences the location for
  the tool, local events included.

Events are tuples; the first item is the kind:

  ``("F", frame, dt)`` / ``("f", frame)``      frame body start / end
  ``("P", phase, body)`` / ``("p", phase)``    phase start / end (``PHASES``; ``body``:
                                               called by the frame body, not by author
                                               code such as an explicit ``flush()``)
  ``("N", label, kind, site, owner)``          registered (``owner`` is usually None:
                                               a part's ``_owner`` is set after register)
  ``("Q", label, owner)``                      ``Entity.destroy`` called (before ``on_destroy``)
  ``("D", label, dying)`` / ``("d", label, dead)``   ``Registry.destroy`` called / returned
  ``("T", label)``                             the teardown starts (after ``on_destroy``)
  ``("K", label, owner)`` / ``("R", label, owner)``  park / resume (``owner``: a part's owner)
  ``("A", act)`` / ``("a", act)``              act change start / end
  ``("B", act)`` / ``("b", act)``              an act's build (construct + ``setup``); the
                                               first one is the seal of the top level
  ``("X", site, phase, fn, args, resume, method)``  an author function the engine called
                                               (``method``: its first parameter is ``self``)
  ``("C", entered, stayed, exited)``           a collision step commits its contacts, before
                                               any handler: sorted label pairs (``entered``
                                               in dispatch order)
  ``("S", "ghost" | "resolve")``               the step's ghost response / resolve starts

Contact handler doors are ``enter`` / ``stay`` (``_dispatch_contact``'s phase)
and ``exit`` (``_run_exit``: a step's exit, a destroy's, or a deferred one).
  ``("E", where, exc)``                        a hooked engine function unwound

``site`` of an author call is the nearest labelled engine frame
(``_CALL_SITES``: ``"contact"``, ``"exit"``, ``"after"``, ``"update"`` ...),
else the caller's qualified name.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

mon = sys.monitoring
E = mon.events

TOOL_IDS = (5, 0)           # 1 coverage, 2 profiler, 3 the engine watchdog, 4 the sentinel
TOOL_NAME = "scena-laws"

_TESTS_DIR = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LAWS_DIR = os.path.normcase(os.path.dirname(os.path.abspath(__file__)))
# Author programs that live under tests/laws (fixtures, equation twins).
_LAWS_AUTHOR = tuple(os.path.join(_LAWS_DIR, d) + os.sep for d in ("fixtures", "twins"))
_STDLIB = tuple(os.path.normcase(p) for p in {
    os.path.dirname(os.__file__), sys.prefix, sys.base_prefix, sys.exec_prefix})


# ---------------------------------------------------------------------------
# What is hooked
# ---------------------------------------------------------------------------

# Phase functions of the frame body (Scena Design, "Frame order"). ``update``
# is ``callback_if_exists(fw, "update", ...)``; the poll phase is everything
# between the frame start and ``update``.
PHASES = (
    ("scena.process", "tick_processes", "tick"),
    ("scena.collision", "CollisionSystem.step", "collision"),
    ("scena.bounds", "BoundsSystem.step", "leave"),
    ("scena.orchestration", "ScenaFramework._step_hover", "hover"),
    ("scena.state", "ScenaSystem.flush", "flush"),
    ("scena.orchestration", "ScenaFramework._tick_pre_draw", "predraw"),
    ("scena.input", "KeyPressed._expire_edges", "expire"),
)

# Engine frames that name the door an author function came through.
_CALL_SITES = (
    # Pulls first: a formula read inside a handler is a formula, not the handler.
    ("scena.state", "FormulaLink.evaluate", "formula"),
    ("scena.state", "FormulaLink.evaluate_and_update", "formula"),
    ("scena.registry", "Registry.eval_group_formula", "formula"),
    ("scena.hitbox", "Hitbox._refresh_link", "formula"),
    ("scena.events", "_eval_condition", "condition"),
    ("scena.events", "_invoke_callback", "when"),
    ("scena.entity", "_finish_actor_construct", "setup"),
    ("scena.history", "History._invoke_on_leave", "history"),
    ("scena.process", "_invoke_update", "on_update"),
    ("scena.process", "_call_update", "on_update"),
    ("scena.process", "_resume_with_watchdog", "resume"),     # an async script / mode
    # The hover edges: an enter or an exit, wherever the target changes
    # (exits are immediate: a destroy, a release; Shapes Design, Hover).
    ("scena.orchestration", "ShapeInteractionManager._set_hover_target", "hover-edge"),
    ("scena.collision", "CollisionSystem._dispatch_contact", "contact"),
    ("scena.collision", "CollisionSystem._run_exit", "exit"),
    ("scena.collision", "CollisionSystem._end_contacts_of", "exit-of"),
    ("scena.collision", "CollisionSystem._emit_exit_keys", "exit-keys"),
    ("scena.process", "Handle._fire_once", "after"),
    ("scena.process", "Handle._fire_every", "every"),
    ("scena.process", "run_on_destroy", "on_destroy"),
    ("scena.process", "Scheduler.tick", "tick"),
    ("scena.orchestration", "callback_if_exists", None),     # None: the callback's name
    ("scena.orchestration", "ScenaFramework._handle_key", "key"),
    ("scena.orchestration", "ScenaFramework._handle_mouse_button", "button"),
    ("scena.orchestration", "ScenaFramework._step_hover", "hover"),
    ("scena.bounds", "BoundsSystem.step", "leave"),
    ("scena.state", "ScenaSystem.flush", "flush"),
    ("scena.act", "ActManager._build", "act-build"),
    ("scena.act", "ActManager._teardown", "act-teardown"),
    ("scena.orchestration", "ScenaFramework._tick_pre_draw", "predraw"),
)


# Engine functions that only pass an author call through (arity, owner,
# watchdog): a call reached through them still belongs to the door above.
_CALL_HELPERS = frozenset({
    "call_truncated", "_invoke", "_call_update", "_invoke_update",
    "_run_with_watchdog", "_resume_with_watchdog",
    "_pair_method_adapter.<locals>.adapter", "_pair_method_adapter.<locals>.handler",
    "call_without_owner", "_bind_when_condition.<locals>.<lambda>",
    "BoundsSystem._dispatch_leave", "CanvasCover._fire", "ShapeInteractionManager._call",
})


def _resolve(module: str, qualname: str):
    import importlib
    obj: Any = importlib.import_module(module)
    for part in qualname.split("."):
        obj = obj.__dict__[part] if isinstance(obj, type) else getattr(obj, part)
    return getattr(obj, "__func__", obj).__code__


# ---------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------

class Recorder:
    """One recording. ``install()`` starts it; ``uninstall()`` stops it."""

    def __init__(self) -> None:
        self.events: List[Tuple] = []
        self.errors: List[str] = []
        self.frame = 0
        self.phases: List[str] = []
        # id(obj) -> (label, id(type), type name): no reference to the object
        # or its class (an author class can hold graph nodes of its own: E0
        # found a leftover one while the recording held the class).
        self.labels: Dict[int, Tuple[str, int, str]] = {}
        self._ordinal: Dict[Tuple[str, str], int] = {}
        self.counts = {"frames": 0, "author_calls": 0}
        self.input_doors: List[set] = []     # one set per OS input event being handled

    # -- labels -----------------------------------------------------------
    def label_of(self, obj) -> Optional[str]:
        got = self.labels.get(id(obj))
        if got is None:
            return None
        t = type(obj)
        if id(t) != got[1] or t.__qualname__ != got[2]:
            return None
        return got[0]

    def _new_label(self, obj, kind: str, site: str) -> str:
        key = (kind, site)
        n = self._ordinal.get(key, 0)
        self._ordinal[key] = n + 1
        label = f"{kind}@{site}#{n}"
        t = type(obj)
        self.labels[id(obj)] = (label, id(t), t.__qualname__)
        return label

    def dump(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for ev in self.events:
                fh.write(json.dumps(ev, default=repr) + "\n")


def _raw(obj) -> dict:
    try:
        return object.__getattribute__(obj, "__dict__")
    except Exception:
        return {}


def _site_text(site) -> str:
    if not site:
        return "-"
    try:
        return f"{os.path.basename(site[0])}:{site[1]}"
    except Exception:
        return "-"


# Module state read by the callbacks (kept flat: the callbacks are hot).
_rec: Optional[Recorder] = None
_tool: Optional[int] = None
_main_thread = threading.main_thread().ident
_busy = [False]
_hooks: Dict[Any, Tuple[Callable, Optional[Callable]]] = {}   # code -> (on_start, on_return)
_sites: Dict[str, Optional[str]] = {}                          # engine qualname -> door label
_NO_SITE = object()
_engine_dir = ""
_author_cache: Dict[str, bool] = {}


def _is_author_file(filename: str) -> bool:
    """Author code: not the engine, not Python itself, not the test harness.

    ``tests/games/*.py``, ``tests/programs/*.py`` and the laws fixtures and
    twins are author code; the helpers directly in ``tests/`` (and the
    laws machinery) are not."""
    got = _author_cache.get(filename)
    if got is not None:
        return got
    f = os.path.normcase(os.path.abspath(filename)) if not filename.startswith("<") else ""
    ok = bool(f) and not (
        f.startswith(_engine_dir)
        or f.startswith(_STDLIB)
        or "site-packages" in f
        or os.path.dirname(f) == _TESTS_DIR
        or (f.startswith(_LAWS_DIR) and not f.startswith(_LAWS_AUTHOR))
    )
    _author_cache[filename] = ok
    return ok


def _is_engine_code(code) -> bool:
    return code.co_filename.startswith(_engine_dir) or \
        os.path.normcase(code.co_filename).startswith(_engine_dir)


# -- hook bodies (frame = the hooked function's frame) ----------------------

def _phase_start(name):
    def start(frame):
        # ``body``: called by the frame body itself, not by author code (the
        # public ``flush()`` runs pending checks now, from a handler).
        back = frame.f_back
        _rec.phases.append(name)
        _rec.events.append(("P", name, back is not None and back.f_code is _frame_code))
    return start


def _phase_end(name):
    def end(frame, retval):
        ph = _rec.phases
        if ph and ph[-1] == name:
            ph.pop()
        _rec.events.append(("p", name))
    return end


def _frame_start(frame):
    r = _rec
    r.frame += 1
    r.counts["frames"] += 1
    r.phases[:] = ["poll"]
    r.events.append(("F", r.frame, frame.f_locals.get("dt")))


def _frame_end(frame, retval):
    _rec.phases[:] = []
    _rec.events.append(("f", _rec.frame))


# A script input hook the engine delivered (whether or not the author wrote
# it: ``callback_if_exists`` is the delivery point).
_SCRIPT_DOORS = {"on_key_down": "script-down", "on_key_up": "script-up", "on_key": "script-key",
                 "on_char": "script-char", "on_mouse_down": "script-down",
                 "on_mouse_up": "script-up", "on_mouse_click": "script-click"}


def _update_start(frame):
    name = frame.f_locals.get("callback_name")
    if name == "update":
        _rec.phases.append("update")
        _rec.events.append(("P", "update", True))
    elif name in _SCRIPT_DOORS and _rec.input_doors:
        _rec.input_doors[-1].add(_SCRIPT_DOORS[name])


def _update_end(frame, retval):
    if frame.f_locals.get("callback_name") == "update":
        ph = _rec.phases
        if ph and ph[-1] == "update":
            ph.pop()
        _rec.events.append(("p", "update"))


def _register_end(frame, retval):
    obj = retval
    if obj is None:
        return
    d = _raw(obj)
    owner = d.get("_owner")
    label = _rec._new_label(obj, type(obj).__name__, _site_text(d.get("_site")))
    _rec.events.append(("N", label, type(obj).__name__, _site_text(d.get("_site")),
                        _rec.label_of(owner) if owner is not None else None))


def _destroy_start(frame):
    obj = frame.f_locals.get("obj")
    label = _rec.label_of(obj)
    if label is not None:
        _rec.events.append(("D", label, bool(_raw(obj).get("_dying"))))


def _destroy_end(frame, retval):
    obj = frame.f_locals.get("obj")
    label = _rec.label_of(obj)
    if label is not None:
        _rec.events.append(("d", label, bool(_raw(obj).get("_destroyed"))))


def _owner_label(obj):
    """A part's owner, read when it acts (``_owner`` is set after register)."""
    owner = _raw(obj).get("_owner")
    return _rec.label_of(owner) if owner is not None else None


def _destroy_request(frame):
    obj = frame.f_locals.get("self")
    label = _rec.label_of(obj)
    if label is not None:
        _rec.events.append(("Q", label, _owner_label(obj)))


def _pair_labels(key, ids) -> tuple:
    """A contact key ``(id(ca), id(cb))`` as the sorted labels of the two
    author objects (``Collider._identity``: a weakref read, no graph)."""
    out = []
    for cid in key:
        c = ids.get(cid)
        lab = None
        if c is not None:
            try:                       # a slot (Collider has no __dict__)
                ident = object.__getattribute__(c, "_identity_shape")
            except AttributeError:
                ident = None
            obj = ident() if ident is not None else c
            lab = _rec.label_of(obj if obj is not None else c)
        out.append(lab or "?")
    return tuple(sorted(out))


def _contacts_commit(frame):
    loc = frame.f_locals
    ids = loc.get("id_to_collider") or {}
    entered = [_pair_labels(k, ids) for k in loc.get("entered_order") or ()]
    stayed = sorted(_pair_labels(k, ids) for k in loc.get("stayed") or ())
    exited = sorted(_pair_labels(k, ids) for k in loc.get("exited") or ())
    _rec.events.append(("C", tuple(entered), tuple(stayed), tuple(exited)))


def _ghosts(frame):
    _rec.events.append(("S", "ghost"))


def _resolve_start(frame):
    _rec.events.append(("S", "resolve"))


# -- input: one event per OS key / button event, with the doors that got it --

def _input_start(frame):
    _rec.input_doors.append(set())


def _input_end(kind):
    def end(frame, retval):
        doors = _rec.input_doors.pop() if _rec.input_doors else set()
        loc = frame.f_locals
        if kind == "key":
            name = loc.get("key_name")
            if name is None:              # a framework shortcut, an unnamed key
                return
        elif kind == "char":
            name = loc.get("char")
        else:
            name = loc.get("button")
        _rec.events.append(("I", kind, str(name), int(loc.get("action", 1)),
                            tuple(sorted(doors))))
    return end


def _door(token, when_true=False):
    """Mark the door an input reached (``when_true``: only if it returned truthy)."""
    def mark(frame, retval=None):
        if _rec.input_doors:
            _rec.input_doors[-1].add(token)
    if when_true:
        def mark_if(frame, retval):
            if retval and _rec.input_doors:
                _rec.input_doors[-1].add(token)
        return mark_if
    return mark


def _abandon(frame):
    obj = frame.f_locals.get("self")
    _rec.events.append(("O", "abandon", str(frame.f_locals.get("button")),
                        _rec.label_of(obj)))


def _teardown_start(frame):
    label = _rec.label_of(frame.f_locals.get("obj"))
    if label is not None:
        _rec.events.append(("T", label))


def _build_start(frame):
    cls = frame.f_locals.get("cls")
    _rec.events.append(("B", getattr(cls, "__name__", repr(cls))))


def _build_end(frame, retval):
    cls = frame.f_locals.get("cls")
    _rec.events.append(("b", getattr(cls, "__name__", repr(cls))))


def _park(frame):
    obj = frame.f_locals.get("self")
    label = _rec.label_of(obj)
    if label is not None:
        _rec.events.append(("K", label, _owner_label(obj)))


def _resume(frame):
    obj = frame.f_locals.get("self")
    label = _rec.label_of(obj)
    if label is not None:
        _rec.events.append(("R", label, _owner_label(obj)))


def _act_start(frame):
    cls = frame.f_locals.get("cls")
    _rec.events.append(("A", getattr(cls, "__name__", repr(cls))))


def _act_end(frame, retval):
    cls = frame.f_locals.get("cls")
    _rec.events.append(("a", getattr(cls, "__name__", repr(cls))))


_ENGINE_HOOKS = (
    ("scena.orchestration", "ScenaFramework._simulate_frame", _frame_start, _frame_end),
    ("scena.orchestration", "callback_if_exists", _update_start, _update_end),
    ("scena.registry", "Registry.register", None, _register_end),
    ("scena.entity", "Entity.destroy", _destroy_request, None),
    ("scena.registry", "Registry.destroy", _destroy_start, _destroy_end),
    ("scena.registry", "Registry._destroy_teardown", _teardown_start, None),
    ("scena.act", "ActManager._build", _build_start, _build_end),
    ("scena.collision", "CollisionSystem._dispatch_step", _contacts_commit, None),
    ("scena.collision", "CollisionSystem._apply_ghost_contacts", _ghosts, None),
    ("scena.collision", "CollisionSystem._apply_auto_resolve", _resolve_start, None),
    # Input (S3): the OS event, and the doors it reached while it was handled.
    ("scena.orchestration", "ScenaFramework._handle_key", _input_start, _input_end("key")),
    ("scena.orchestration", "ScenaFramework._handle_mouse_button", _input_start,
     _input_end("button")),
    ("scena.orchestration", "ScenaFramework._handle_char", _input_start, _input_end("char")),
    ("scena.orchestration", "WidgetManager.handle_char", None, _door("widget-char", True)),
    ("scena.orchestration", "WidgetManager.handle_key_down", _door("widget-down"), None),
    ("scena.orchestration", "WidgetManager.handle_key_up", _door("widget-up"), None),
    ("scena.orchestration", "WidgetManager.handle_key", _door("widget-key"), None),
    ("scena.orchestration", "WidgetManager.handle_mouse_down", None, _door("widget-down", True)),
    ("scena.orchestration", "WidgetManager.handle_mouse_up", None, _door("widget-up", True)),
    ("scena.orchestration", "ShapeInteractionManager.handle_mouse_down", None,
     _door("shape-down", True)),
    ("scena.orchestration", "ShapeInteractionManager.handle_mouse_up", _door("shape-up"), None),
    ("scena.orchestration", "CanvasManager.forget_press", _door("script-forget"), None),
    ("scena.uiwidget", "UIWidget._abandon_press", _abandon, None),
    ("scena.uiwidget", "Button._abandon_press", _abandon, None),
    ("scena.entity", "Entity._park_self", _park, None),
    ("scena.entity", "Entity._resume_self", _resume, None),
    ("scena.act", "ActManager._change", _act_start, _act_end),
)


# -- the callbacks -----------------------------------------------------------

def _author_call(code, frame, resume: bool) -> None:
    r = _rec
    caller = frame.f_back
    if caller is None or not _is_engine_code(caller.f_code):
        return
    site = None
    nested = None
    f = caller
    for _ in range(12):
        if f is None:
            break
        c = f.f_code
        engine = _is_engine_code(c)
        if not engine:
            if _is_author_file(c.co_filename):
                break                  # author code called the engine: its own door below
            f = f.f_back               # a test wrapper (a canary's plant): transparent
            continue
        # Doors by qualified name in the engine's files, not by code object:
        # a wrapper (a plant) around the labelled function cannot hide it.
        label = _sites.get(c.co_qualname, _NO_SITE)
        if label is _NO_SITE and nested is None and c.co_qualname not in _CALL_HELPERS:
            # Engine code between the author function and its door that is not
            # a call helper: the engine called it on its own account while the
            # door's code ran (a mode a handler started, a setup of an actor a
            # handler made). Its door is that function, not the handler's.
            nested = c.co_qualname
        if label is not _NO_SITE:
            site = label
            if site is None:           # callback_if_exists: the hook's name
                site = f.f_locals.get("callback_name") or "callback"
            elif site == "contact":    # enter or stay of one contact
                site = f.f_locals.get("phase") or "contact"
            elif site == "hover-edge":  # its target is the new one: an enter
                first = code.co_varnames[0] if code.co_argcount else None
                arg = frame.f_locals.get(first) if first else None
                site = "hover" if arg is not None and arg is f.f_locals.get("new") \
                    else "hover_exit"
            break
        f = f.f_back
    if site is None:
        site = getattr(caller.f_code, "co_qualname", caller.f_code.co_name)
    elif nested is not None:
        site = f"{site}>{nested}"
    args = ()
    n = code.co_argcount
    if n and not resume:
        # ``f_locals`` caches a dict of the locals on the frame. A plain call's
        # frame dies at return; a generator's or coroutine's lives on, and the
        # cache would keep the objects it named alive (E0 found it: a
        # leftover graph node). Read, then drop the cache for those.
        loc = frame.f_locals
        args = tuple(r.label_of(loc.get(name)) for name in code.co_varnames[:min(n, 3)])
        if code.co_flags & _SUSPENDABLE:
            loc.clear()
    r.counts["author_calls"] += 1
    r.events.append(("X", site, r.phases[-1] if r.phases else None,
                     f"{os.path.basename(code.co_filename)}:{code.co_firstlineno}:"
                     f"{getattr(code, 'co_qualname', code.co_name)}",
                     args, resume,
                     bool(n) and code.co_varnames[0] == "self"))


def _on_start(code, offset):
    hook = _hooks.get(code)
    if hook is None:
        if not _is_author_file(code.co_filename):
            return mon.DISABLE
        if _busy[0] or _rec is None or threading.get_ident() != _main_thread:
            return None
        _busy[0] = True
        try:
            _author_call(code, sys._getframe(1), False)
        except Exception as e:  # noqa: BLE001  (never raise into the engine)
            _rec.errors.append(f"author call {code.co_name}: {type(e).__name__}: {e}")
        finally:
            _busy[0] = False
        return None
    start = hook[0]
    if start is None or _busy[0] or _rec is None or threading.get_ident() != _main_thread:
        return None
    _busy[0] = True
    try:
        start(sys._getframe(1))
    except Exception as e:  # noqa: BLE001
        _rec.errors.append(f"start {code.co_qualname}: {type(e).__name__}: {e}")
    finally:
        _busy[0] = False
    return None


def _on_resume(code, offset):
    if code in _hooks:
        return None
    if not _is_author_file(code.co_filename):
        return mon.DISABLE
    if _busy[0] or _rec is None or threading.get_ident() != _main_thread:
        return None
    _busy[0] = True
    try:
        _author_call(code, sys._getframe(1), True)
    except Exception as e:  # noqa: BLE001
        _rec.errors.append(f"resume {code.co_name}: {type(e).__name__}: {e}")
    finally:
        _busy[0] = False
    return None


def _on_return(code, offset, retval):
    hook = _hooks.get(code)
    if hook is None or hook[1] is None or _busy[0] or _rec is None \
            or threading.get_ident() != _main_thread:
        return None
    _busy[0] = True
    try:
        hook[1](sys._getframe(1), retval)
    except Exception as e:  # noqa: BLE001
        _rec.errors.append(f"return {code.co_qualname}: {type(e).__name__}: {e}")
    finally:
        _busy[0] = False
    return None


def _on_unwind(code, offset, exc):
    hook = _hooks.get(code)
    if hook is None or _rec is None or threading.get_ident() != _main_thread:
        return None
    r = _rec
    r.events.append(("E", getattr(code, "co_qualname", code.co_name), type(exc).__name__))
    # A phase or the frame body that unwinds still closes (the next frame
    # starts clean); the model abstains on an aborted frame.
    if code in _phase_codes:
        name = _phase_codes[code]
        if r.phases and r.phases[-1] == name:
            r.phases.pop()
    elif code is _frame_code:
        r.phases[:] = []
    return None


_phase_codes: Dict[Any, str] = {}
_frame_code = None

import inspect as _inspect  # noqa: E402
_SUSPENDABLE = _inspect.CO_GENERATOR | _inspect.CO_COROUTINE | _inspect.CO_ASYNC_GENERATOR


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

def install(recorder: Optional[Recorder] = None) -> Recorder:
    """Start recording into ``recorder`` (a new one by default)."""
    global _rec, _tool, _engine_dir, _frame_code
    if _rec is not None:
        raise RuntimeError("laws recorder already installed")
    import scena
    _engine_dir = os.path.normcase(os.path.dirname(os.path.abspath(scena.__file__)))
    tool = next((t for t in TOOL_IDS if mon.get_tool(t) is None), None)
    if tool is None:
        raise RuntimeError(f"no free sys.monitoring tool id among {TOOL_IDS}")
    mon.use_tool_id(tool, TOOL_NAME)
    _tool = tool
    _rec = recorder if recorder is not None else Recorder()
    _hooks.clear()
    _sites.clear()
    _phase_codes.clear()
    for module, qual, name in PHASES:
        code = _resolve(module, qual)
        _hooks[code] = (_phase_start(name), _phase_end(name))
        _phase_codes[code] = name
    for module, qual, start, end in _ENGINE_HOOKS:
        code = _resolve(module, qual)
        _hooks[code] = (start, end)
    _frame_code = _resolve("scena.orchestration", "ScenaFramework._simulate_frame")
    for module, qual, label in _CALL_SITES:
        _resolve(module, qual)                 # an engine rename fails here, loudly
        _sites[qual] = label
    # A location DISABLEd by an earlier recording stays disabled for this
    # tool id: start from a clean slate (other tools only re-pay a check).
    mon.restart_events()
    mon.register_callback(tool, E.PY_START, _on_start)
    mon.register_callback(tool, E.PY_RESUME, _on_resume)
    mon.register_callback(tool, E.PY_RETURN, _on_return)
    mon.register_callback(tool, E.PY_UNWIND, _on_unwind)
    mon.set_events(tool, E.PY_START | E.PY_RESUME | E.PY_UNWIND)
    for code in _hooks:
        mon.set_local_events(tool, code, E.PY_RETURN)
    return _rec


def uninstall() -> Optional[Recorder]:
    """Stop recording; return the recording. Leaves no event set."""
    global _rec, _tool
    rec, tool = _rec, _tool
    if tool is None:
        return rec
    if mon.get_tool(tool) != TOOL_NAME:
        # Someone took the id over (the engine watchdog does that with 3):
        # the recording is not to be trusted.
        if rec is not None:
            rec.errors.append(f"tool id {tool} taken over by {mon.get_tool(tool)!r}")
    else:
        for code in _hooks:
            mon.set_local_events(tool, code, 0)
        mon.set_events(tool, 0)
        for ev in (E.PY_START, E.PY_RESUME, E.PY_RETURN, E.PY_UNWIND):
            mon.register_callback(tool, ev, None)
        mon.free_tool_id(tool)
    _rec = None
    _tool = None
    _hooks.clear()
    _sites.clear()
    _phase_codes.clear()
    return rec


def installed() -> bool:
    return _rec is not None


def assert_clean() -> List[str]:
    """What the recorder left behind (empty = nothing): a test guard."""
    out = []
    for t in TOOL_IDS:
        if mon.get_tool(t) == TOOL_NAME:
            out.append(f"tool id {t} still held by {TOOL_NAME}")
    if _rec is not None:
        out.append("recorder still installed")
    return out


class recording:
    """``with recording() as rec: ...`` — record inside the block."""

    def __init__(self, recorder: Optional[Recorder] = None) -> None:
        self.recorder = recorder

    def __enter__(self) -> Recorder:
        return install(self.recorder)

    def __exit__(self, *exc) -> None:
        uninstall()
