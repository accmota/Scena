"""Sentinel: runtime invariants of the geometry and graph, checked test-side (H2).

Not a test module. ``install()`` wraps the engine's entry points — the pose
verbs, the flip / angle / scale setters, the slot ``__set__`` doors,
``_takein``, ``_assign_formula`` / ``_link_field``, ``unlink`` /
``unlink_all``, ``clone``, ``<<``, ``absorb``, ``destroy`` and the collision
reader ``snapshot_shape`` — and after the **outermost** call returns (never
inside a batch) checks the touched object's ownership tree:

========  ==================================================================
I-fast    the fast path is legal: a tree that writes skip-notify
          (``_needs_pull_invalidate`` False) has no link, no live Derivate, no
          ``_pull_owner``, no linked anchor and no outside dependent
I-bare    a bare-read flag (``_scalar_bare_ok[name] is True``) only on a node
          with no link and no ``_pull_owner`` (a field anchor is pulled by
          ``ScalarSlot.__get__`` before the flag is read, so it may coexist)
I-graph   ``dependencies`` / ``dependents`` are symmetric; no edge names a
          purged node; a clean link never has a dirty source
I-clean   a clean tree's live Derivates equal a recomputation from its
          Defining values (the owner's ``_update_impl`` is idempotent)
I-heading a Defining ``angle`` and the pose store ``_rotation`` agree once the
          angle is clean (GR17, through every door)
I-names   frozen name signs change only through a flip, a copy, a clone or
          ``box =``
I-epoch   a pose-keyed collision cache hit equals an uncached rebuild (R7)
I-atomic  a call that raised left the tree's raw state as it found it
========  ==================================================================

Zero engine cost: nothing here ships; the checks read raw ``__dict__`` state
(no pulls, no Derivate warmed, no Entity built), so a run under the sentinel
takes the same paths as a run without it (Testing Design — "Invariants and
assertions in code": the test-side oracle is the runtime check).

Switch: ``SCENA_SENTINEL=log`` records each violation (one JSON line per
violation in ``.scena_test_runs/sentinel/<pid>.jsonl``); ``SCENA_SENTINEL=1``
also raises ``SentinelViolation`` from the call (unless the key matches
``geom_campaign_known.SENTINEL``). ``tests/sentinel_site/sitecustomize.py``
installs it in every process; ``python tests/run_tiers.py gate --sentinel``
runs the whole suite under it and prints ``report()``.

    python tests/geom_sentinel.py --report        # aggregate the last run's logs
"""
from __future__ import annotations

import fnmatch
import functools
import json
import math
import os
import sys
import threading
import traceback
import weakref
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, ".scena_test_runs", "sentinel")

MODE = os.environ.get("SCENA_SENTINEL", "")


class SentinelViolation(AssertionError):
    """An engine invariant failed right after an engine call."""


_state = threading.local()
_installed: List = []
_names_seen: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_violations: List[dict] = []
_counts: Dict[str, int] = {}
_raise = MODE == "1"
_log_path: Optional[str] = None


def _known(key: str) -> bool:
    try:
        sys.path.insert(0, HERE)
        import geom_campaign_known as K
        return any(fnmatch.fnmatch(key, p) for p in getattr(K, "SENTINEL", {}))
    except Exception:  # noqa: BLE001
        return False


def _where() -> str:
    """The innermost test-side frame, and the test method that runs it."""
    inner = method = None
    for fr in reversed(traceback.extract_stack()[:-3]):
        if os.sep + "tests" + os.sep not in fr.filename or "geom_sentinel" in fr.filename:
            continue
        if inner is None:
            inner = f"{os.path.basename(fr.filename)}:{fr.lineno} {fr.name}"
        if method is None and fr.name.startswith("test"):
            method = f"{os.path.basename(fr.filename)}::{fr.name}"
    if inner is None:
        return "?"
    return inner if method is None or method.split("::")[1] in inner else f"{inner} [{method}]"


def _report(inv: str, obj, call: str, detail: str) -> None:
    kind = type(obj).__name__
    model = getattr(getattr(obj, "__dict__", {}).get("model"), "name", None)
    key = f"{inv} | {kind}{' ' + model if model else ''} | {call}"
    _counts[key] = _counts.get(key, 0) + 1
    rec = {"key": key, "detail": detail[:300], "where": _where()}
    _violations.append(rec)
    if getattr(_state, "memory_only", False):
        if _raise and not _known(key):
            raise SentinelViolation(f"{key}: {detail}")
        return
    global _log_path
    try:
        os.makedirs(OUT, exist_ok=True)
        if _log_path is None:
            _log_path = os.path.join(OUT, f"{os.getpid()}.jsonl")
        with open(_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass
    if _raise and not _known(key):
        raise SentinelViolation(f"{key}: {detail}")


# ---------------------------------------------------------------------------
# Raw reads
# ---------------------------------------------------------------------------

def _d(o) -> dict:
    try:
        return object.__getattribute__(o, "__dict__")
    except AttributeError:
        return {}


def _root(obj):
    from scena.state import Container
    if not isinstance(obj, Container):
        return None
    try:
        return obj._ownership_root()
    except Exception:  # noqa: BLE001
        return None


def _nodes(root) -> list:
    try:
        return list(root._iter_subtree())
    except Exception:  # noqa: BLE001
        return []


def _graph():
    from scena.state import get_scena_system
    ss = get_scena_system()
    return None if ss is None else ss.dependency_graph


def _deferring() -> bool:
    from scena.state import get_scena_system
    ss = get_scena_system()
    return bool(ss is not None and ss.update_manager.deferring)


def _num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 9) if math.isfinite(float(v)) else repr(v)
    return None


_POSE_KEYS = ("_rotation", "_scale", "_flip_x", "_flip_y", "_name_signs", "model")


def raw_state(root) -> tuple:
    """The tree's raw values: slot fields, pose stores, links (identity)."""
    out = []
    # A caption whose layout waits for the next read refreshes its parts there
    # (T1): nothing in it is settled until then.
    pending_layout = "_layout_ready" in _d(root) and not _d(root).get("_layout_ready")
    caption = hasattr(type(root), "_refresh_layout")
    for n in _nodes(root):
        d = _d(n)
        slots = ()
        try:
            slots = n._field_slots().keys()
        except Exception:  # noqa: BLE001
            pass
        row = []
        for k in list(slots) + list(_POSE_KEYS):
            if k in d:
                v = d[k]
                nv = _num(v)
                row.append((k, nv if nv is not None else (getattr(v, "name", None) if k == "model" else
                                                           (tuple(v) if isinstance(v, tuple) else type(v).__name__))))
        row.append(("_link", id(d.get("_link")) if d.get("_link") is not None else None))
        # A node a pull may still refresh (dirty, linked, pull-owned, or with a
        # dirty anchor) can change its raw value without any write: not compared.
        # A caption's center is reconciled with its string at the read (T1).
        lazy_center = caption and d.get("_attr_name") == "center"
        settled = not (pending_layout or lazy_center or d.get("_dirty") or d.get("_link") is not None or "_pull_owner" in d
                       or any(_d(a).get("_dirty") or _d(a).get("_link") is not None
                              for a in (d.get("_field_anchors") or {}).values()))
        out.append((d.get("_attr_name"), settled, tuple(row)))
    return tuple(out)


def atomic_diff(before: tuple, after: tuple) -> list:
    """Nodes that were settled before a refused call and changed during it."""
    if len(before) != len(after):
        return ["(parts added or removed)"]
    def strip_first_freeze(row_b, row_a):
        # Corner names freeze at their first use, a read: None -> signs is not a write.
        db, da = dict(row_b), dict(row_a)
        if db.get("_name_signs") is None and "_name_signs" in da:
            da.pop("_name_signs")
        return db, da
    out = []
    for b, a in zip(before, after):
        if not b[1]:
            continue
        rb, ra = strip_first_freeze(b[2], a[2])
        if b[0] != a[0] or rb != ra:
            out.append(b[0])
    return out


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def check_fast(root, call) -> None:
    rd = _d(root)
    if rd.get("_needs_pull_invalidate", False):
        return
    nodes = _nodes(root)
    ids = {id(n) for n in nodes}
    g = _graph()
    for n in nodes:
        d = _d(n)
        what = None
        if d.get("_link") is not None:
            what = "a link"
        elif d.get("_derivate_live"):
            what = "a live Derivate"
        elif "_pull_owner" in d:
            what = "a pull owner"
        elif d.get("_link_source"):
            what = "a link reads it"
        else:
            anchors = d.get("_field_anchors") or {}
            if any(getattr(a, "_link", None) is not None for a in anchors.values()):
                what = "a linked anchor"
        if what is None and g is not None and d.get("_node_id") is not None:
            for dep in g.dependents.get(d["_node_id"], ()):
                c = g.nodes.get(dep) if hasattr(g.nodes, "get") else None
                if c is not None and id(c) not in ids and _d(c).get("_link") is not None:
                    what = "an outside link depends on it"
                    break
        if what is not None:
            _report("I-fast", root, call, f"fast-path tree holds {what} at {d.get('_attr_name')}")
            return


def check_bare(root, call) -> None:
    for n in _nodes(root):
        d = _d(n)
        cache = d.get("_scalar_bare_ok")
        if not cache:
            continue
        true = [k for k, v in cache.items() if v is True]
        if not true:
            continue
        if d.get("_link") is not None:
            _report("I-bare", root, call, f"{d.get('_attr_name')}: bare flag on a linked node")
        elif "_pull_owner" in d:
            _report("I-bare", root, call, f"{d.get('_attr_name')}.{true}: bare flag on a pull-owned node")


def _gc_backstop() -> bool:
    st = sys.modules.get("scena.state")      # the module (``scena.state`` may be a facade)
    return bool(getattr(st, "_graph_gc_backstop", False))


def check_graph(root, call) -> None:
    g = _graph()
    if g is None:
        return
    for n in _nodes(root):
        d = _d(n)
        nid = d.get("_node_id")
        if nid is None:
            continue
        for dep in g.dependencies.get(nid, ()):
            if nid not in g.dependents.get(dep, ()):
                _report("I-graph", root, call, f"{d.get('_attr_name')}: dependency {dep} has no back edge")
                return
            if dep not in g.nodes and not _gc_backstop():
                # Under the GC backstop a collected node's edges wait for its
                # finalizer (test_graph_gc_backstop): a dangling id is legal then.
                _report("I-graph", root, call, f"{d.get('_attr_name')}: edge to purged node {dep}")
                return
        for dep in g.dependents.get(nid, ()):
            if nid not in g.dependencies.get(dep, ()):
                _report("I-graph", root, call, f"{d.get('_attr_name')}: dependent {dep} has no back edge")
                return
        link = d.get("_link")
        if link is not None and not d.get("_dirty", False):
            # A derived source (itself linked) not yet recomputed while this
            # reader is clean is D13. A written plain cell keeps ``_dirty``
            # with nothing to recompute: not a staleness signal.
            for src in getattr(link, "sources", ()) or ():
                sd = _d(src)
                if sd.get("_dirty", False) and sd.get("_link") is not None and sd.get("_node_id") is not None:
                    _report("I-graph", root, call,
                            f"{d.get('_attr_name')}: clean link over a dirty source")
                    return


def _derivate_values(root) -> list:
    from scena.state import FieldType
    out = []
    for n in _nodes(root):
        d = _d(n)
        if d.get("_field_type") is FieldType.Derivate and d.get("_derivate_live"):
            for k in ("x", "y"):
                if k in d:
                    out.append((d.get("_attr_name"), k, _num(d[k])))
    return out


def _close(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-7 * max(1.0, abs(a), abs(b))
    return a == b


def check_clean(root, call) -> None:
    """A clean tree's live Derivates are what its Defining values give."""
    upd = getattr(type(root), "_update_impl", None)
    if upd is None or getattr(root, "_scena_is_entity", False) is False:
        return
    if hasattr(type(root), "_refresh_layout") or type(root).__name__ in ("Track", "_ReversedTrack"):
        return              # Text / Track: parts (layout, cursor) are computed at the read (T1)
    nodes = _nodes(root)
    if any(_d(n).get("_dirty", False) or _d(n).get("_in_batch_update", False) for n in nodes):
        return
    for n in nodes:
        for a in (_d(n).get("_field_anchors") or {}).values():
            if _d(a).get("_dirty", False):
                return
    if any(_d(n).get("_link") is not None for n in nodes):
        return              # a linked input is pulled on read, not recomputed here
    before = _derivate_values(root)
    if not before:
        return
    prev: dict = {}
    root._push_batch_update_subtree(prev)       # recompute without notifying anyone
    try:
        upd(root)
    except Exception:  # noqa: BLE001
        return
    finally:
        root._restore_batch_update_subtree(prev)
    after = {(n, k): v for n, k, v in _derivate_values(root)}
    diff = [((n, k), v, after[(n, k)]) for n, k, v in before
            if (n, k) in after and not _close(v, after[(n, k)])]
    if diff:
        _report("I-clean", root, call, f"clean Derivate differs from a recompute: {diff[:3]}")


def check_heading(root, call) -> None:
    d = _d(root)
    defining = d.get("_defining_part_names") or ()
    if "angle" not in defining or "angle" not in d:
        return
    try:
        rot_raw = d["_rotation"] if "_rotation" in d else object.__getattribute__(root, "_rotation")
    except AttributeError:
        return
    a = (d.get("_field_anchors") or {}).get("angle")
    if a is not None and _d(a).get("_dirty", False):
        return              # a pending pull: the value itself is not current yet
    try:
        ang, rot = float(d["angle"]), float(rot_raw)
    except (TypeError, ValueError):
        return
    if abs(ang - rot) > 1e-6 * max(1.0, abs(ang)):
        _report("I-heading", root, call, f"angle {ang} vs pose store {rot}")


_NAME_DOORS = ("flip_x", "flip_y", "flip_x =", "flip_y =", "box =", "_takein", "__lshift__",
               "clone", "absorb", "__imatmul__", "_assign_formula", "_link_field")


def check_names(root, call, pre=None) -> None:
    """Signs frozen before this call changed during it, through a non-naming door."""
    prev = (pre or {}).get("signs")
    signs = _d(root).get("_name_signs")
    if prev is not None and signs is not None and prev != signs and not call.endswith(_NAME_DOORS):
        _report("I-names", root, call, f"name signs {prev} -> {signs}")


CHECKS = (check_fast, check_bare, check_graph, check_heading, check_names, check_clean)


def check_tree(obj, call: str, pre=None) -> None:
    root = _root(obj)
    if root is None or _deferring() or _d(root).get("_in_batch_update", False):
        return
    # The checks call the engine (I-clean recomputes): never check inside a
    # check (``_finish`` sets ``_state.checking``).
    for fn in CHECKS:
        if fn is check_names:
            fn(root, call, pre)
        else:
            fn(root, call)


# ---------------------------------------------------------------------------
# Hooks: sys.monitoring (PEP 669) on the entry points' code objects
# ---------------------------------------------------------------------------
#
# A function wrapper would add a frame between the author and the engine,
# and the engine reads that stack: author sites (``made at …``,
# ``destroyed at …``) and ``stacklevel`` warnings would name the wrapper.
# Start / return / unwind events on the code objects add no frame.

TOOL = 4                    # sys.monitoring tool id (0 debugger, 1 coverage, 2 profiler, 5 optimizer)

_REFUSABLE = {"move_by", "move_to", "rotate_by", "rotate_to", "scale_by", "scale_to",
              "flip_x", "flip_y", "angle", "scale", "__set__", "_assign_formula", "_link_field",
              "__lshift__", "absorb", "__imatmul__"}
_NOT_REFUSABLE_SETS = {"visible", "active", "layer", "group", "color", "line_width", "alpha",
                       "z", "collidable", "on_collide", "mode", "on_destroy", "on_update"}

# Engine modules whose calls are top-level for the graph: the scheduler's
# tween ticks and the frame loop write between frames, not inside an update.
_TOP_LEVEL_ENGINE = ("scena.process", "scena.orchestration", "scena.events")

ENTRY_POINTS = ("move_by", "move_to", "rotate_by", "rotate_to", "scale_by", "scale_to",
                "flip_x", "flip_y", "angle", "scale", "clone", "absorb", "unlink", "unlink_all",
                "__lshift__", "__imatmul__", "_takein", "_assign_formula", "_link_field",
                "__setattr__")

_codes: Dict = {}           # code object -> (label, subject parameter, kind)


def _external(frame) -> bool:
    """A call from outside the engine (or from the scheduler / frame loop).

    Read paths are not hooked, so an engine write made inside a pull would
    look outermost; the caller's module tells it apart."""
    mod = frame.f_globals.get("__name__", "") if frame is not None else ""
    return not (mod == "scena" or mod.startswith("scena.")) or mod.startswith(_TOP_LEVEL_ENGINE)


def _subject(obj):
    """A link handle (``shape["angle"]``) stands for the object it names."""
    if type(obj).__name__ == "FieldRef":
        return getattr(obj, "owner", None)
    return obj


def _stack() -> list:
    st = getattr(_state, "stack", None)
    if st is None:
        st = _state.stack = []
    return st


def _depth() -> int:
    return sum(1 for r in _stack() if r is not None) + (1 if getattr(_state, "checking", False) else 0)


def _on_start(code, offset):
    info = _codes.get(code)
    st = _stack()
    if info is None:
        return
    try:
        frame = sys._getframe(1)
        label, param, kind = info
        if kind == "snapshot":
            st.append(None)
            return
        if _depth() > 0 or not _external(frame.f_back):
            st.append(None)
            return
        loc = frame.f_locals
        name = label.rsplit(".", 1)[-1]
        call = label
        if kind == "setattr":
            name = loc.get("name") or loc.get("key") or ""
            if not isinstance(name, str) or name.startswith("_"):
                st.append(None)
                return
            call = f"{label.split('.')[0]}.{name} ="
        subject = _subject(loc.get(param))
        r = _root(subject)
        before = None
        if r is not None and (name in _REFUSABLE or (kind == "setattr" and name not in _NOT_REFUSABLE_SETS)):
            before = raw_state(r)
        st.append((subject, r, call, before, _d(r).get("_name_signs") if r is not None else None))
    except Exception:  # noqa: BLE001  (the sentinel never breaks a run on its own error)
        st.append(None)


def _finish(rec, exc=None):
    subject, r, call, before, signs = rec
    _state.checking = True
    try:
        if exc is not None:
            if before is not None and r is not None and isinstance(exc, Exception) \
                    and not isinstance(exc, SentinelViolation):
                changed = atomic_diff(before, raw_state(r))
                if changed:
                    _report("I-atomic", r, call, f"{type(exc).__name__} left {changed[:4]} changed")
            return
        check_tree(subject, call, {"signs": signs})
    finally:
        _state.checking = False


def _on_return(code, offset, retval):
    info = _codes.get(code)
    if info is None:
        return
    st = _stack()
    rec = st.pop() if st else None
    if info[2] == "snapshot":
        _check_snapshot(code, retval)
        return
    if rec is None:
        return
    try:
        _finish(rec)
    except SentinelViolation:
        raise
    except Exception:  # noqa: BLE001
        pass


def _on_unwind(code, offset, exc):
    if code not in _codes:
        return
    st = _stack()
    rec = st.pop() if st else None
    if rec is None:
        return
    try:
        _finish(rec, exc)
    except Exception:  # noqa: BLE001  (never replace the exception in flight)
        pass


def _check_snapshot(code, out):
    """I-epoch: a pose-keyed cache hit equals an uncached rebuild."""
    if getattr(_state, "checking", False):
        return
    try:
        frame = sys._getframe(2)
        loc = frame.f_locals
        shape, owner = loc.get("shape"), loc.get("cache_owner")
    except Exception:  # noqa: BLE001
        return
    if owner is None or shape is None:
        return
    C = sys.modules["scena.collision"]
    cs = C.get_collision_system()
    builds = getattr(cs, "_debug_hull_builds", None)
    _state.checking = True
    try:
        fresh = C._snapshot_shape_uncached(shape, cache_owner=None)
    except Exception:  # noqa: BLE001
        return
    finally:
        _state.checking = False
        if builds is not None:
            cs._debug_hull_builds = builds      # tests count real rebuilds

    if not _same_prims(out, fresh):
        _report("I-epoch", shape, "collision.snapshot_shape",
                "a cached hull differs from an uncached rebuild under the same key")


def _same_prims(a, b, tol=1e-6) -> bool:
    def rows(ps):
        out = []
        for p in ps:
            vals = [float(v) for v in tuple(p.aabb) + tuple(p.params)]
            for v in (p.verts or ()):
                vals.extend(float(c) for c in v)
            out.append((p.kind.name, vals))
        return sorted(out, key=lambda r: (r[0], len(r[1]), [round(v, 3) for v in r[1]]))
    ra, rb = rows(a), rows(b)
    if len(ra) != len(rb):
        return False
    for (ka, va), (kb, vb) in zip(ra, rb):
        if ka != kb or len(va) != len(vb):
            return False
        scale = max([1.0] + [abs(v) for v in va])
        if any(abs(x - y) > tol * scale for x, y in zip(va, vb)):
            return False
    return True


def _classes():
    import importlib
    import inspect
    import pkgutil
    import scena
    seen = []
    for m in pkgutil.iter_modules(scena.__path__):
        if m.name.startswith("_sksl") or m.name in ("__main__",):
            continue
        try:
            mod = importlib.import_module("scena." + m.name)
        except Exception:  # noqa: BLE001
            continue
        for obj in vars(mod).values():
            if inspect.isclass(obj) and obj.__module__ == mod.__name__ and obj not in seen:
                seen.append(obj)
    return seen


def _hook(fn, label, param, kind):
    code = getattr(fn, "__code__", None)
    if code is None or code in _codes:
        return
    if param is None:
        names = code.co_varnames[:code.co_argcount]
        param = names[0] if names else None
    _codes[code] = (label, param, kind)
    E = sys.monitoring.events
    sys.monitoring.set_local_events(TOOL, code, E.PY_START | E.PY_RETURN)


def install() -> None:
    """Hook every entry point (idempotent)."""
    if _installed:
        return
    import importlib
    from scena.state import ContainerSlot, ScalarSlot
    mon = sys.monitoring
    if mon.get_tool(TOOL) is None:
        mon.use_tool_id(TOOL, "scena-sentinel")
    E = mon.events
    mon.register_callback(TOOL, E.PY_START, _on_start)
    mon.register_callback(TOOL, E.PY_RETURN, _on_return)
    mon.register_callback(TOOL, E.PY_UNWIND, _on_unwind)
    mon.set_events(TOOL, E.PY_UNWIND)       # not a local event in 3.12: filtered by code
    for cls in _classes():
        for name in ENTRY_POINTS:
            raw = cls.__dict__.get(name)
            if raw is None or isinstance(raw, (staticmethod, classmethod)):
                continue
            fn = raw.fset if isinstance(raw, property) else raw
            if fn is None or not callable(fn):
                continue
            _hook(fn, f"{cls.__name__}.{name}", None, "setattr" if name == "__setattr__" else "call")
    for slot in (ScalarSlot, ContainerSlot):
        _hook(slot.__dict__["__set__"], f"{slot.__name__}.__set__", "instance", "call")
    importlib.import_module("scena.collision")
    _hook(sys.modules["scena.collision"].snapshot_shape, "collision.snapshot_shape", "shape", "snapshot")
    _installed.append(True)


def uninstall() -> None:
    if not _installed:
        return
    mon = sys.monitoring
    for code in list(_codes):
        mon.set_local_events(TOOL, code, 0)
    mon.set_events(TOOL, 0)
    _codes.clear()
    E = mon.events
    for ev in (E.PY_START, E.PY_RETURN, E.PY_UNWIND):
        mon.register_callback(TOOL, ev, None)
    mon.free_tool_id(TOOL)
    _stack().clear()
    _installed.clear()


class active:
    """Context manager: sentinel on (raising, known keys ignored) inside the block."""

    def __init__(self, raise_: bool = True):
        self.raise_ = raise_

    def __enter__(self):
        global _raise
        self._prev = (_raise, bool(_installed), getattr(_state, "memory_only", False))
        _raise = self.raise_
        _state.memory_only = True       # a test's own run never reaches the tier's log
        install()
        del _violations[:]
        return _violations

    def __exit__(self, *exc):
        global _raise
        _raise, was, _state.memory_only = self._prev
        if not was:
            uninstall()
        return False


def report(path: str = OUT) -> Dict[str, dict]:
    """Aggregate the JSON-line logs: key -> {count, where (first few), detail}."""
    agg: Dict[str, dict] = {}
    if not os.path.isdir(path):
        return agg
    sys.path.insert(0, HERE)
    from source_support import iter_files
    for full in iter_files(path, ".jsonl", recursive=False):
        with open(full, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                a = agg.setdefault(rec["key"], {"count": 0, "where": [], "detail": rec["detail"]})
                a["count"] += 1
                if rec["where"] not in a["where"] and len(a["where"]) < 5:
                    a["where"].append(rec["where"])
    return agg


def clear_logs(path: str = OUT) -> None:
    if os.path.isdir(path):
        sys.path.insert(0, HERE)
        from source_support import iter_files
        for full in iter_files(path, ".jsonl", recursive=False):
            os.remove(full)


if __name__ == "__main__":
    agg = report()
    for key, a in sorted(agg.items(), key=lambda kv: -kv[1]["count"]):
        mark = " (known)" if _known(key) else ""
        print(f"{a['count']:6d}  {key}{mark}\n        {a['detail'][:160]}\n        {', '.join(a['where'])}")
    print(f"{len(agg)} distinct violations")
