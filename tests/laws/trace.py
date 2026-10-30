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
  ``("C", entered, stayed, exited, gained, lost)``  a collision step commits its contacts,
                                               before any handler: sorted label pairs
                                               (``entered`` in dispatch order); ``gained`` /
                                               ``lost``: touching pairs a rule began / stopped
                                               matching (an enter / an exit while they stay)
  ``("S", "ghost" | "resolve")``               the step's ghost response / resolve starts
  ``("I", kind, name, action, doors)``         an OS key / char / button event and the
                                               doors it reached (S3)
  ``("O", "abandon", button, widget)``         a leaving widget gave up its press
  ``("H", "add", h, kind, delay, interval, owner, scope, refused, phase, parent)``
                                                ``parent``: the task it is work of
  ``("H", "tick", h, world_dt, scale, active, alive, paused, held, over)``
  ``("H", "fire" | "pause" | "resume", h)``     a timed handle (S4)
  ``("H", "cancel", h, live)``                  ``live``: it ended a running job
  ``("H", "step", h, active, alive, phase)``    a task's step (``Script._advance``)

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
import weakref
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
        # id(obj) -> a weak reference to it, where the type allows one: an id
        # is reused once its object is freed, and an unlabelled object of the
        # same type at that address read as the dead one (S7 found it: a
        # history door's Point took a freed Point's label). A weak reference
        # keeps nothing alive.
        self._refs: Dict[int, Any] = {}
        self._ordinal: Dict[Tuple[str, str], int] = {}
        self.counts = {"frames": 0, "author_calls": 0}
        self.input_doors: List[set] = []     # one set per OS input event being handled
        # ``M`` events (S6): every resolve body's pose before and after each
        # resolve. Off by default (one record per body per frame); the motion
        # laws and their twins turn it on.
        self.motion = False
        # Files under tests/ the harness treats as author code for this
        # recording (the World machine's hooks live in its test module).
        self.author_files: set = set()

    # -- labels -----------------------------------------------------------
    def label_of(self, obj) -> Optional[str]:
        got = self.labels.get(id(obj))
        if got is None:
            return None
        t = type(obj)
        if id(t) != got[1] or t.__qualname__ != got[2]:
            return None
        ref = self._refs.get(id(obj))
        if ref is not None and ref() is not obj:
            return None
        return got[0]

    def _new_label(self, obj, kind: str, site: str) -> str:
        key = (kind, site)
        n = self._ordinal.get(key, 0)
        self._ordinal[key] = n + 1
        label = f"{kind}@{site}#{n}"
        t = type(obj)
        self.labels[id(obj)] = (label, id(t), t.__qualname__)
        try:
            self._refs[id(obj)] = weakref.ref(obj)
        except TypeError:
            # Without a weak reference a freed object's id passes its label to
            # the next object of the type at that address: a cancel of a
            # Handle the probe never labelled read as an old handle's, in one
            # run of a pair and not the other (WP35).
            self._refs.pop(id(obj), None)
            msg = f"labels a {t.__qualname__}, which has no weak reference: add __weakref__"
            if msg not in self.errors:
                self.errors.append(msg)
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


def _field(obj, name, default=None):
    """An instance field as stored — the instance dict or a slot — never a
    property (a property read can pull the graph). S4 found the trap: an
    owner's ``_active`` lives in a slot on some classes, and a dict-only read
    saw every parked owner as active."""
    d = _raw(obj)
    if name in d:
        return d[name]
    desc = getattr(type(obj), name, None)
    if type(desc).__name__ == "member_descriptor":
        try:
            return desc.__get__(obj, type(obj))
        except AttributeError:
            return default
    return default


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
_author_extra: set = set()


def _is_author_file(filename: str) -> bool:
    """Author code: not the engine, not Python itself, not the test harness.

    ``tests/games/*.py``, ``tests/programs/*.py`` and the laws fixtures and
    twins are author code; the helpers directly in ``tests/`` (and the
    laws machinery) are not."""
    got = _author_cache.get(filename)
    if got is not None:
        return got
    f = os.path.normcase(os.path.abspath(filename)) if not filename.startswith("<") else ""
    if f in _author_extra:
        _author_cache[filename] = True
        return True
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


def _materializing_site(frame):
    """The site of the shape filling a Derivate part on first access (an
    Ellipse's ``fp1`` when another shape first links to its ``center``), or
    None. The part's own ``_site`` is the line that read it first: swap two
    readers and the shape's parts change lines (E3 on loom.py). The engine
    names a part through its owner (``made_at``), so the label does too."""
    f = frame.f_back
    for _ in range(24):
        if f is None:
            return None
        if f.f_code.co_name == "_materialize_derivate_part":
            return _field(f.f_locals.get("self"), "_site")
        f = f.f_back
    return None


def _register_end(frame, retval):
    obj = retval
    if obj is None:
        return
    owner = _field(obj, "_owner")
    site = _site_text(_materializing_site(frame) or _field(obj, "_site"))
    label = _rec._new_label(obj, type(obj).__name__, site)
    _rec.events.append(("N", label, type(obj).__name__, site,
                        _rec.label_of(owner) if owner is not None else None))


def _destroy_start(frame):
    obj = frame.f_locals.get("obj")
    label = _rec.label_of(obj)
    if label is not None:
        _rec.events.append(("D", label, bool(_field(obj, "_dying", False))))


def _destroy_end(frame, retval):
    obj = frame.f_locals.get("obj")
    label = _rec.label_of(obj)
    if label is not None:
        _rec.events.append(("d", label, bool(_field(obj, "_destroyed", False))))


def _owner_label(obj):
    """A part's owner, read when it acts (``_owner`` is set after register)."""
    owner = _field(obj, "_owner")
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
    # Touching pairs whose rules changed at this commit (CD3): a gained rule
    # enters, a lost one exits, while the pair stays.
    cs = loc.get("self")
    gp = getattr(cs, "_gain_pending", None) or {}
    lp = getattr(cs, "_lost_pending", None) or {}
    entered = [_pair_labels(k, ids) for k in loc.get("entered_order") or () if k not in gp]
    stayed = sorted(_pair_labels(k, ids) for k in loc.get("stayed") or ())
    exited = sorted(_pair_labels(k, ids) for k in loc.get("exited") or ())
    gained = sorted(_pair_labels(k, ids) for k in gp)
    lost = sorted(_pair_labels(k, ids) for k in lp)
    _rec.events.append(("C", tuple(entered), tuple(stayed), tuple(exited),
                        tuple(gained), tuple(lost)))


def _ghosts(frame):
    _rec.events.append(("S", "ghost"))


def _bodies(ids) -> tuple:
    """Pose, velocity and mass of each resolve body (Circle / Rect identities
    only), from raw fields: ``(label, kind, x, y, vx, vy, mass, a, b, angle,
    has_vel)`` with ``a, b`` the radius (Circle) or width, height (Rect);
    ``has_vel``: ``.vel`` is set (a body without one is infinite mass in an
    impulse, Collision Design)."""
    out = []
    for c in ids.values():
        if not _slot(c, "_in_resolve", False):
            continue
        ident = _slot(c, "_identity_shape")
        shape = ident() if ident is not None else None
        if shape is None:
            continue
        d = _raw(shape)
        ctr = d.get("center")
        if ctr is None:
            continue
        # Only a real Circle / Rect collides as its own outline: a Sprite
        # collides as its hitbox, not its width x height (P1 abstains there).
        geometric = isinstance(shape, _GEOM_KINDS) and ("radius" in d or "width" in d)
        p = _raw(ctr)
        v = d.get("_vel")
        vd = _raw(v) if v is not None else {}
        try:
            mass = float(d.get("_mass", 1.0))
        except (TypeError, ValueError):
            continue
        if not geometric:
            a, b, ang, kind = 0.0, 0.0, 0.0, "other"
        elif "radius" in d:
            a, b, ang = float(d["radius"]), 0.0, 0.0
            kind = "circle"
        else:
            a, b, ang = float(d["width"]), float(d.get("height", 0.0)), float(d.get("angle", 0.0))
            kind = "rect"
        out.append((_rec.label_of(shape), kind, float(p.get("x", 0.0)), float(p.get("y", 0.0)),
                    float(vd.get("x", 0.0)), float(vd.get("y", 0.0)), mass, a, b, ang,
                    v is not None))
    return tuple(out)


_GEOM_KINDS: tuple = ()


def _resolve_start(frame):
    global _GEOM_KINDS
    if not _GEOM_KINDS:
        from scena.shapes import Circle, Rect
        _GEOM_KINDS = (Circle, Rect)
    _rec.events.append(("S", "resolve"))
    if _rec.motion:
        # The world's floor (``collision.floor``): P5 and P6 are laws of a
        # world with one (V10).
        floor = bool(_slot(frame.f_locals.get("self"), "_floor", True))
        _rec.events.append(("M", "pre", _bodies(_live_ids(frame)), floor))


def _live_ids(frame) -> dict:
    """The resolve's colliders by id, read live (``CollisionSystem._colliders``),
    not from the step's ``id_to_collider`` snapshot: that one is built before
    the handlers, and a body a handler makes (a clone) is resolved this step
    (the resolve pass chooses its bodies at its start, F3). Unnamed, it read
    ``?`` and the motion model took a three-body solve for a pair (P3 on
    tutorial 32, chaos ``enter:2:sibling``)."""
    cs = frame.f_locals.get("self")
    cols = _slot(cs, "_colliders", None)
    if cols is None:
        return frame.f_locals.get("id_to_collider") or {}
    return {id(c): c for c in cols}


def _resolve_end(frame, retval):
    if _rec.motion:
        ids = _live_ids(frame)
        solved = _slot(frame.f_locals.get("self"), "_solve_contacts", None) or {}
        pairs = tuple(sorted(_pair_labels(k, ids) for k in solved))
        _rec.events.append(("M", "post", _bodies(ids), pairs))


# -- timers (S4): a handle's life, from raw slots (Handle has __slots__) ----

def _slot(obj, name, default=None):
    try:
        return object.__getattribute__(obj, name)
    except AttributeError:
        return default


def _handle_add_end(frame, retval):
    h = retval
    if h is None:
        return
    kind = _slot(h, "kind")
    owner = _slot(h, "_owner")
    label = _rec._new_label(h, f"Handle:{kind}", _site_text(_slot(h, "_site")))
    _rec.events.append(("H", "add", label, kind, float(_slot(h, "delay", 0.0) or 0.0),
                        float(_slot(h, "interval", 0.0) or 0.0),
                        _rec.label_of(owner) if owner is not None else None,
                        str(_slot(h, "scope")), bool(_slot(h, "_cancelled", False)),
                        _rec.phases[-1] if _rec.phases else None,
                        _rec.label_of(_slot(h, "_task_parent"))))


def _task_step(frame):
    """A task's step (``Script._advance``): its owner's flags and the phase."""
    script = frame.f_locals.get("self")
    if script is None or _slot(script, "done", False):
        return
    h = _slot(script, "handle")
    label = _rec.label_of(h)
    if label is None:
        return
    owner = _slot(h, "_owner")
    _rec.events.append(("H", "step", label,
                        bool(_field(owner, "_active", True)) if owner is not None else True,
                        not _field(owner, "_destroyed", False) if owner is not None else True,
                        _rec.phases[-1] if _rec.phases else None))


def _handle_cancel(frame):
    """``Handle.cancel``: the 4th field says whether it ended a live job (a
    cancel of a finished one changes nothing)."""
    h = frame.f_locals.get("self")
    label = _rec.label_of(h)
    if label is not None:
        live = not (_slot(h, "_done", False) or _slot(h, "_cancelled", False))
        _rec.events.append(("H", "cancel", label, live))


def _handle_tick(frame):
    loc = frame.f_locals
    h = loc.get("handle")
    label = _rec.label_of(h)
    if label is None:
        return
    owner = _slot(h, "_owner")
    # The owner's flags may live in slots, not __dict__: read them as the
    # instance holds them (no property runs either way).
    _rec.events.append(("H", "tick", label, float(loc.get("world_dt", 0.0)),
                        float(_field(owner, "_time_scale", 1.0)) if owner is not None else 1.0,
                        bool(_field(owner, "_active", True)) if owner is not None else True,
                        not _field(owner, "_destroyed", False) if owner is not None else True,
                        bool(_slot(h, "_paused", False)), bool(_slot(h, "_held", False)),
                        bool(_slot(h, "_cancelled", False)) or bool(_slot(h, "_done", False))))


def _handle_event(name):
    def ev(frame):
        label = _rec.label_of(frame.f_locals.get("self"))
        if label is not None:
            _rec.events.append(("H", name, label))
    return ev


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
    ("scena.collision", "CollisionSystem._apply_auto_resolve", _resolve_start, _resolve_end),
    # Timers (S4).
    ("scena.process", "Scheduler.add", None, _handle_add_end),
    ("scena.process", "Scheduler._tick_once", _handle_tick, None),
    ("scena.process", "Scheduler._tick_every", _handle_tick, None),
    ("scena.process", "Scheduler._tick_tween", _handle_tick, None),     # T1's order
    ("scena.process", "Handle._fire_once", _handle_event("fire"), None),
    ("scena.process", "Handle._fire_every", _handle_event("fire"), None),
    ("scena.process", "Handle.cancel", _handle_cancel, None),
    ("scena.process", "Script._advance", _task_step, None),
    ("scena.process", "Handle.pause", _handle_event("pause"), None),
    ("scena.process", "Handle.resume", _handle_event("resume"), None),
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

def door_of(code, frame) -> Optional[str]:
    """The door an author function came through, or None when no engine code
    called it (an author helper called by author code). ``frame`` is the
    author function's own frame, ``code`` its code. The recorder labels each
    author call with it at start; the chaos runtime (``laws.chaos``) asks it
    again at the return, so both agree on what a door is."""
    caller = frame.f_back
    if caller is None or not _is_engine_code(caller.f_code):
        return None
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
    return site


def _author_call(code, frame, resume: bool) -> None:
    r = _rec
    site = door_of(code, frame)
    if site is None:
        return
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
            _drop_locals_cache(loc)
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


def _drop_locals_cache(loc) -> None:
    """Drop the snapshot a read of ``f_locals`` left on a frame that lives on.

    CPython 3.12 caches a dict on the frame: empty it. From 3.13 (PEP 667)
    ``f_locals`` is a write-through proxy with no cache and no ``clear``;
    emptying it would delete the frame's own variables, so leave it alone.
    """
    if isinstance(loc, dict):
        loc.clear()


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
    _author_extra.clear()
    _author_extra.update(os.path.normcase(os.path.abspath(f)) for f in _rec.author_files)
    _author_cache.clear()
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
    if _author_extra:
        _author_extra.clear()
        _author_cache.clear()
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
