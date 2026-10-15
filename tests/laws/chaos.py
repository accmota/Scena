"""Chaos doors: one author command fired at an author callback door (S7, law F3).

At the return of every author function the engine called (a door: a handler,
a timer, ``on_update``, a hover edge, a ``@when``, a widget callback, an act
or actor ``setup`` …), the chaos runtime may run one command an author could
write there — destroy, park, untag, a group change, ``collidable = False``,
``change_act``, a clone, a timer, a pose or velocity write — and the run is
then checked against the laws (design/Laws.md, F3: the snapshot rule).

How the command gets there (Testing Design, "Laws and equations", S7):

* **An AST rewrite compiled under the program's own path.** Every plain
  ``def`` (not a generator or coroutine) gets ``return X`` →
  ``return __chaos__.ret(X)`` and a trailing ``__chaos__.ret(None)``, every
  lambda ``lambda: __chaos__.ret(body)``; new
  nodes take the location of the node they replace, so every code object
  keeps its file and lines. The chaos trace compares to the plain trace with
  no line map, and tools that read the file from disk read the original.
* Not ``sys.monitoring``: no monitoring event fires while a monitoring
  callback runs, so a command run from a PY_RETURN callback would be
  invisible to the recorder (probe on CPython 3.12 and 3.14, 2026-10-15).
* ``__chaos__.ret`` asks ``trace.door_of`` whether this return closes a door
  (the recorder's own rule) and counts doors; a plan names ``(door, n)``.
  This module is laws machinery, not author code: the recorder neither
  records it nor lets it hide a door.

Rules (the recorder's): no reference held across calls (a target is found
again by its label), raw reads (``trace._field``), a command's own exception
is caught and classified (a refusal with a fix, or an engine-internal
error), one command per door, none inside a command's own nested doors.

    python tests/laws/chaos.py tests/laws/fixtures/s5_doors --plan enter:0:destroy.self
"""
from __future__ import annotations

import ast
import linecache
import os
import random
import sys
import traceback
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from laws import model, trace  # noqa: E402
from laws.attach import attach  # noqa: E402

NAME = "__chaos__"


# ---------------------------------------------------------------------------
# The rewrite
# ---------------------------------------------------------------------------

def _ret_call(value: ast.expr, where: ast.AST) -> ast.Call:
    call = ast.Call(func=ast.Attribute(value=ast.Name(id=NAME, ctx=ast.Load()),
                                       attr="ret", ctx=ast.Load()),
                    args=[value], keywords=[])
    for node in (call, call.func, call.func.value):
        ast.copy_location(node, where)
    return call


class _Scope(ast.NodeVisitor):
    """Does one function's own body yield (nested scopes excluded)?"""

    def __init__(self) -> None:
        self.yields = False

    def visit_Yield(self, node):
        self.yields = True

    visit_YieldFrom = visit_Yield
    visit_Await = visit_Yield

    def visit_FunctionDef(self, node):
        pass

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


class _Returns(ast.NodeTransformer):
    """``return X`` → ``return __chaos__.ret(X)`` in one function's own body."""

    def visit_Return(self, node):
        value = node.value if node.value is not None else \
            ast.copy_location(ast.Constant(value=None), node)
        node.value = _ret_call(value, value)
        return node

    def visit_FunctionDef(self, node):
        return node

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


class _Rewrite(ast.NodeTransformer):
    def __init__(self) -> None:
        self.count = 0

    def visit_FunctionDef(self, node):
        self.generic_visit(node)               # nested functions first
        scope = _Scope()
        for stmt in node.body:
            scope.visit(stmt)
        if scope.yields:
            return node                        # a generator: out of scope (v1)
        ret = _Returns()
        node.body = [ret.visit(stmt) for stmt in node.body]
        last = node.body[-1]
        tail = ast.Expr(value=_ret_call(ast.Constant(value=None), last))
        # On the body's last line: the fall-through return of the function.
        for n in ast.walk(tail):
            n.lineno = n.end_lineno = last.end_lineno or last.lineno
            n.col_offset = n.end_col_offset = 0
        node.body.append(tail)
        self.count += 1
        return node

    def visit_AsyncFunctionDef(self, node):
        self.generic_visit(node)
        return node

    def visit_Lambda(self, node):
        # ``on_done=lambda: ...`` is a door like a def; a formula or a
        # condition lambda is a pull door ``ret`` sees and never samples.
        self.generic_visit(node)
        node.body = _ret_call(node.body, node.body)
        self.count += 1
        return node


def rewrite(tree: ast.Module) -> ast.Module:
    """Route every plain ``def``'s returns through ``__chaos__.ret``."""
    out = _Rewrite().visit(tree)
    ast.fix_missing_locations(out)
    return out


# ---------------------------------------------------------------------------
# Targets (found at use, never held)
# ---------------------------------------------------------------------------

def _registry():
    from scena.canvas import ScenaCanvas
    return ScenaCanvas.get_current().registry


def _alive(obj) -> bool:
    return obj is not None and not trace._field(obj, "_destroyed", False) \
        and not trace._field(obj, "_dying", False)


def _is_act(obj) -> bool:
    from scena.act import Act
    return isinstance(obj, Act)


def _is_part(obj) -> bool:
    """A part (a shape's ``center``, a hitbox piece) answers to its owner."""
    return trace._field(obj, "_owner") is not None


def _live_targets() -> List[Any]:
    """Live labelled objects in label order (deterministic across runs)."""
    rec = trace._rec
    out = []
    for obj in _registry().live_objects():
        lab = rec.label_of(obj) if rec is not None else None
        if lab is not None and _alive(obj) and not _is_act(obj) and not _is_part(obj):
            out.append((lab, obj))
    out.sort(key=lambda t: t[0])
    return [o for _, o in out]


def _find(label: str):
    rec = trace._rec
    for obj in _registry().live_objects():
        if rec.label_of(obj) == label:
            return obj
    return None


def _tags(obj) -> List[str]:
    g = trace._field(obj, "group")
    return sorted(g) if isinstance(g, (set, frozenset)) else []


def _groups() -> List[str]:
    return sorted(k for k, b in _registry().group_map.items() if len(b))


def _act_classes(globs) -> List[type]:
    from scena.act import Act
    out = [v for v in globs.values() if isinstance(v, type) and issubclass(v, Act) and v is not Act]
    return sorted(out, key=lambda c: c.__name__)


def _act_running() -> bool:
    from scena import act as _act
    m = _act.get_act_manager()
    return m is not None and trace._field(m, "current") is not None \
        and not trace._field(m, "changing", False)


def _noop(*_a) -> None:
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    """What a command sees at its door."""
    door: str
    frame: Any                      # the author function's frame
    me: Any                         # the method's self, else the first labelled argument
    partner: Any                    # a contact door's other side
    rng: random.Random
    chaos: "Chaos"

    @property
    def globs(self):
        return self.frame.f_globals


def _target(ctx: Ctx, which: str):
    if which == "self":
        return ctx.me
    if which == "partner":
        return ctx.partner
    live = _live_targets()
    return ctx.rng.choice(live) if live else None


def _graphic(obj) -> bool:
    from scena.entity import Graphic
    return isinstance(obj, Graphic) and _alive(obj)


def _entity(obj) -> bool:
    from scena.entity import Entity
    return isinstance(obj, Entity) and _alive(obj) and not _is_act(obj) and not _is_part(obj)


class Command:
    """``applies(ctx) -> target or None``; ``run(ctx, target)``; ``check``:
    the immediacy rule (L1, F3's first half) read raw right after."""
    neutral = False

    def __init__(self, name: str, applies: Callable, run: Callable,
                 check: Optional[Callable] = None, neutral: bool = False) -> None:
        self.name, self.applies, self.run, self.check, self.neutral = \
            name, applies, run, check, neutral


def _in_any_group(obj) -> List[str]:
    return [g for g, b in _registry().group_map.items() if obj in b]


def _destroyed_check(ctx, obj, before):
    if before.get("dying"):
        return None                            # a second destroy does nothing (L2)
    if not trace._field(obj, "_destroyed", False):
        return "destroy returned and the object is not dead"
    left = _in_any_group(obj)
    return f"destroy returned and the object is still in {left}" if left else None


def _destroy(which):
    def applies(ctx):
        t = _target(ctx, which)
        return t if _entity(t) else None

    def run(ctx, t):
        ctx.chaos.before["dying"] = bool(trace._field(t, "_dying", False))
        t.destroy()
    return Command(f"destroy.{which}", applies, run,
                   lambda ctx, t: _destroyed_check(ctx, t, ctx.chaos.before))


def _park(resume_now: bool):
    def applies(ctx):
        t = _target(ctx, "self") if ctx.rng.random() < 0.6 else _target(ctx, "other")
        return t if _entity(t) and trace._field(t, "_active", True) else None

    def run(ctx, t):
        t.active = False
        if resume_now:
            t.active = True
        else:
            ctx.chaos.later.append((trace._rec.frame + 2, trace._rec.label_of(t)))

    def check(ctx, t):
        want = resume_now
        got = bool(trace._field(t, "_active", True))
        return None if got == want else f"active reads {got} right after the write"
    return Command("park.resume" if resume_now else "park", applies, run, check)


def _untag():
    def applies(ctx):
        for t in (ctx.me, ctx.partner):
            if _entity(t) and _tags(t):
                return t
        return None

    def run(ctx, t):
        tag = ctx.rng.choice(_tags(t))
        ctx.chaos.before["tag"] = tag
        t.untag(tag)

    def check(ctx, t):
        tag = ctx.chaos.before["tag"]
        b = _registry().group_map.get(tag)
        return f"untag({tag!r}) returned and the object is still in it" if b and t in b else None
    return Command("untag", applies, run, check)


def _regroup():
    def applies(ctx):
        t = ctx.me if _entity(ctx.me) else None
        return t if t is not None and [g for g in _groups() if g not in _tags(t)] else None

    def run(ctx, t):
        g = ctx.rng.choice([g for g in _groups() if g not in _tags(t)])
        ctx.chaos.before["tag"] = g
        t.add_to_group(g)

    def check(ctx, t):
        g = ctx.chaos.before["tag"]
        b = _registry().group_map.get(g)
        return None if b is not None and t in b else f"add_to_group({g!r}) returned, not in it"
    return Command("group", applies, run, check)


def _uncollide():
    def applies(ctx):
        for t in (ctx.me, ctx.partner):
            if _entity(t) and trace._field(t, "_collidable", False):
                return t
        return None

    def run(ctx, t):
        t.collidable = False
    return Command("uncollide", applies, run)


def _act():
    def applies(ctx):
        if not _act_running():
            return None
        acts = _act_classes(ctx.globs)
        return ctx.rng.choice(acts) if acts else None

    def run(ctx, a):
        from scena import change_act
        change_act(a)
    return Command("act", applies, run)


def _sibling():
    def applies(ctx):
        t = _target(ctx, "self") if ctx.rng.random() < 0.7 else _target(ctx, "partner")
        return t if _graphic(t) else None

    def run(ctx, t):
        t.clone()
    return Command("sibling", applies, run)


def _timer():
    def applies(ctx):
        return ctx.me if _entity(ctx.me) else True

    def run(ctx, t):
        from scena import after, every
        d = ctx.rng.choice((0.0, 1 / 60, 0.25))
        kind = ctx.rng.choice(("after", "every"))
        if kind == "every" and d == 0.0:
            d = 1 / 60
        if t is True:
            (after if kind == "after" else every)(d, _noop)
        else:
            getattr(t, kind)(d, _noop)
    return Command("timer", applies, run)


def _pose():
    def applies(ctx):
        t = ctx.me if _graphic(ctx.me) else (ctx.partner if _graphic(ctx.partner) else None)
        return t if t is not None and hasattr(t, "move_by") else None

    def run(ctx, t):
        t.move_by(ctx.rng.uniform(-40, 40), ctx.rng.uniform(-40, 40))
    return Command("pose", applies, run)


def _vel():
    def applies(ctx):
        for t in (ctx.me, ctx.partner):
            if _graphic(t) and "_vel" in trace._raw(t):
                return t
        return None

    def run(ctx, t):
        from scena import Vec2
        t.vel = Vec2(ctx.rng.uniform(-300, 300), ctx.rng.uniform(-300, 300))
    return Command("vel", applies, run)


# -- neutral commands (E0-style: the trace does not change) ------------------

def _neutral_timer():
    def run(ctx, t):
        from scena import after
        after(1e6, _noop).cancel()
    return Command("neutral.timer", lambda ctx: True, run, neutral=True)


def _neutral_untag():
    def applies(ctx):
        return ctx.me if _entity(ctx.me) and _groups() else None

    def run(ctx, t):
        absent = [g for g in _groups() if g not in _tags(t)]
        if absent:
            t.untag(ctx.rng.choice(absent))
    return Command("neutral.untag", applies, run, neutral=True)


def _neutral_tag():
    def applies(ctx):
        return ctx.me if _entity(ctx.me) and _tags(ctx.me) else None

    def run(ctx, t):
        t.tag(ctx.rng.choice(_tags(t)))
    return Command("neutral.tag", applies, run, neutral=True)


# -- groups (family G) ---------------------------------------------------------

def _group_of(ctx) -> Optional[str]:
    for t in (ctx.me, ctx.partner):
        if _entity(t) and _tags(t):
            return ctx.rng.choice(_tags(t))
    gs = _groups()
    return ctx.rng.choice(gs) if gs else None


def _members(g) -> List[Any]:
    b = _registry().group_map.get(g)
    return [o for o in (r() for r in list(b._order.values())) if o is not None] if b else []


def _group_destroy():
    def run(ctx, g):
        from scena import group
        ctx.chaos.before["members"] = [o for o in _members(g) if _alive(o)]
        group[g].destroy()

    def check(ctx, g):
        alive = [trace._rec.label_of(o) for o in ctx.chaos.before["members"]
                 if not trace._field(o, "_destroyed", False)]
        return f"group[{g!r}].destroy() returned, alive: {alive}" if alive else None
    return Command("group.destroy", _group_of, run, check)


def _group_untag_all():
    def run(ctx, g):
        from scena import group
        group[g].untag(g)

    def check(ctx, g):
        left = _members(g)
        return f"group[{g!r}].untag({g!r}) returned, {len(left)} still in" if left else None
    return Command("group.untag_all", _group_of, run, check)


def _group_tag_all():
    def run(ctx, g):
        from scena import group
        others = [h for h in _groups() if h != g]
        h = ctx.rng.choice(others) if others else g + "_chaos"
        ctx.chaos.before["tag"] = h
        ctx.chaos.before["members"] = _members(g)
        group[g].tag(h)

    def check(ctx, g):
        h = ctx.chaos.before["tag"]
        b = _registry().group_map.get(h)
        miss = [o for o in ctx.chaos.before["members"] if _alive(o) and (b is None or o not in b)]
        return f"group[{g!r}].tag({h!r}) returned, {len(miss)} not in it" if miss else None
    return Command("group.tag_all", _group_of, run, check)


def _group_churn():
    def applies(ctx):
        t = ctx.me if _entity(ctx.me) and _tags(ctx.me) else None
        return t

    def run(ctx, t):
        tag = ctx.rng.choice(_tags(t))
        ctx.chaos.before["tag"] = tag
        if ctx.rng.random() < 0.5:
            t.untag(tag)
            t.tag(tag)                          # A → ∅ → A in one door
        else:
            others = [h for h in _groups() if h not in _tags(t)]
            t.untag(tag)                        # A → B
            if others:
                t.tag(ctx.rng.choice(others))
            ctx.chaos.later.append((trace._rec.frame + 1, ("retag", trace._rec.label_of(t), tag)))
    return Command("group.churn", applies, run)


def _group_join_rule():
    def applies(ctx):
        t = ctx.me if _entity(ctx.me) else None
        if t is None or not _graphic(ctx.partner):
            return None
        return t if [g for g in _tags(ctx.partner) if g not in _tags(t)] or _groups() else None

    def run(ctx, t):
        gs = [g for g in _groups() if g not in _tags(t)]
        if gs:
            g = ctx.rng.choice(gs)
            ctx.chaos.before["tag"] = g
            t.tag(g)
    return Command("group.join_rule", applies, run)


def _group_walk():
    def run(ctx, g):
        from scena import group
        seen = []
        before = _members(g)
        for m in group[g]:
            seen.append(m)
            if ctx.rng.random() < 0.5:
                m.destroy()
            elif _graphic(m):
                m.clone()
        ctx.chaos.before["walk"] = (before, seen)

    def check(ctx, g):
        before, seen = ctx.chaos.before["walk"]
        same = len(before) == len(seen) and all(a is b for a, b in zip(before, seen))
        return None if same else (f"a walk over group[{g!r}] saw {len(seen)} members, "
                                  f"{len(before)} at its start")
    return Command("group.walk", _group_of, run, check)


COMMANDS: Dict[str, Command] = {c.name: c for c in (
    _destroy("self"), _destroy("partner"), _destroy("other"),
    _park(False), _park(True), _untag(), _regroup(), _uncollide(), _act(),
    _sibling(), _timer(), _pose(), _vel(),
    _neutral_timer(), _neutral_untag(), _neutral_tag(),
    _group_destroy(), _group_untag_all(), _group_tag_all(), _group_churn(),
    _group_join_rule(), _group_walk(),
)}

NEUTRAL = tuple(n for n, c in COMMANDS.items() if c.neutral)

# Doors where a writer is refused by design (pull doors: formulas and
# conditions are lambdas the rewrite does not touch; a def used as one is
# still a pull) and doors that are not the author's callbacks.
UNSAMPLED = frozenset({"formula", "condition", "history"})


# ---------------------------------------------------------------------------
# Exceptions: a refusal with a fix, or the engine's own error
# ---------------------------------------------------------------------------

def _engine_dir() -> str:
    import scena
    return os.path.normcase(os.path.dirname(os.path.abspath(scena.__file__)))


def classify(exc: BaseException) -> Tuple[str, str]:
    """``("refusal" | "internal" | "author", where)``: a ``raise`` statement in
    ``scena/`` is a refusal (the engine telling the author what to write);
    anything else raised inside the engine is internal; an exception from
    author code is the author's."""
    tb = exc.__traceback__
    last = None
    while tb is not None:
        last = tb
        tb = tb.tb_next
    if last is None:
        return "internal", "?"
    code = last.tb_frame.f_code
    where = f"{os.path.basename(code.co_filename)}:{last.tb_lineno}:{code.co_name}"
    fname = os.path.normcase(os.path.abspath(code.co_filename))
    if not fname.startswith(_engine_dir()):
        if os.path.dirname(fname) == trace._TESTS_DIR:
            return "harness", where          # a game's ledger, a strict close's census
        return ("author" if trace._is_author_file(code.co_filename) or not trace.installed()
                else "internal"), where
    line = linecache.getline(code.co_filename, last.tb_lineno).strip()
    return ("refusal" if line.startswith("raise") else "internal"), where


# ---------------------------------------------------------------------------
# The runtime
# ---------------------------------------------------------------------------

@dataclass
class Fired:
    door: str
    n: int
    command: str
    frame: int
    index: int                      # len(events) when the command started
    target: Optional[str]
    outcome: str = "ran"            # ran / skipped / refusal / internal / author
    detail: str = ""
    end: int = 0                    # len(events) when the command returned


class Chaos:
    """The ``__chaos__`` object a rewritten program calls."""

    def __init__(self, plan: Sequence[Tuple[str, int, str]] = (), *, seed: int = 0,
                 listing: bool = False) -> None:
        self.plan: Dict[Tuple[str, int], str] = {(d, n): c for d, n, c in plan}
        self.seed = seed
        self.listing = listing
        self.counts: Counter = Counter()
        self.doors: List[Tuple[str, int, int, int, str]] = []   # (door, n, frame, index, fn)
        self.fired: List[Fired] = []
        self.findings: List[str] = []
        self.later: List[Tuple[int, Any]] = []
        self.before: Dict[str, Any] = {}
        self._depth = 0

    def ret(self, value=None):
        if self._depth or not trace.installed():
            return value
        rec = trace._rec
        frame = sys._getframe(1)
        try:
            door = trace.door_of(frame.f_code, frame)
        except Exception as e:  # noqa: BLE001
            self.findings.append(f"CHAOS|door_of: {type(e).__name__}: {e}")
            return value
        if door is None:
            return value
        n = self.counts[door]
        self.counts[door] = n + 1
        index = len(rec.events)
        if self.listing:
            code = frame.f_code
            self.doors.append((door, n, rec.frame, index,
                               f"{os.path.basename(code.co_filename)}:{code.co_firstlineno}:"
                               f"{code.co_qualname}"))
        if self.later:
            self._run_later(rec)
        name = self.plan.get((door, n))
        if name is not None:
            self._depth += 1
            try:
                self._fire(door, n, name, frame, rec, index)
            finally:
                self._depth -= 1
                if self.fired:
                    self.fired[-1].end = len(rec.events)
        return value

    def _context(self, door, frame, n) -> Ctx:
        code = frame.f_code
        loc = frame.f_locals
        argn = code.co_argcount
        names = code.co_varnames[:argn]
        objs = [loc.get(a) for a in names]
        rec = trace._rec
        labelled = [o for o in objs if o is not None and rec.label_of(o) is not None]
        me = loc.get("self") if names[:1] == ("self",) else (labelled[0] if labelled else None)
        partner = None
        if door.split(">")[0] in ("enter", "stay", "exit"):
            rest = [o for o in labelled if o is not me]
            partner = rest[0] if rest else None
        rng = random.Random(f"{self.seed}:{door}:{n}")
        return Ctx(door, frame, me, partner, rng, self)

    def _fire(self, door, n, name, frame, rec, index) -> None:
        cmd = COMMANDS[name]
        ctx = self._context(door, frame, n)
        self.before = {}
        target = cmd.applies(ctx)
        label = rec.label_of(target) if target not in (None, True) and not isinstance(target, (str, type)) \
            else (target.__name__ if isinstance(target, type) else target)
        f = Fired(door, n, name, rec.frame, index, label if isinstance(label, str) else None)
        self.fired.append(f)
        if target is None:
            f.outcome = "skipped"
            return
        try:
            cmd.run(ctx, target)
        except Exception as e:  # noqa: BLE001
            kind, where = classify(e)
            f.outcome = kind
            f.detail = f"{type(e).__name__} at {where}: {str(e).splitlines()[0][:160]}"
            if kind == "internal":
                self.findings.append(f"X1|{name}@{door}: {f.detail}\n"
                                     + "".join(traceback.format_exception(e)[-6:]))
            return
        if cmd.check is not None:
            try:
                bad = cmd.check(ctx, target)
            except Exception as e:  # noqa: BLE001
                bad = f"check raised {type(e).__name__}: {e}"
            if bad:
                self.findings.append(f"L1|{name}@{door}#{n}: {bad}")

    def _run_later(self, rec) -> None:
        due = [x for x in self.later if x[0] <= rec.frame]
        if not due:
            return
        self.later = [x for x in self.later if x[0] > rec.frame]
        self._depth += 1
        try:
            for _, what in due:
                try:
                    if isinstance(what, tuple) and what[0] == "retag":
                        obj = _find(what[1])
                        if obj is not None and _alive(obj):
                            obj.tag(what[2])
                    else:
                        obj = _find(what)
                        if obj is not None and _alive(obj):
                            obj.active = True
                except Exception as e:  # noqa: BLE001
                    kind, where = classify(e)
                    if kind == "internal":
                        self.findings.append(f"X1|later@{rec.frame}: {type(e).__name__} at {where}")
        finally:
            self._depth -= 1


# ---------------------------------------------------------------------------
# Running a program
# ---------------------------------------------------------------------------

S5 = "tests/laws/fixtures/s5_doors"


def _hover_pass():
    return [("move", 520, 320), ("step", 3), ("move", 520, 240), ("step", 3),
            ("move", 300, 60), ("step", 2)]


def _click(x, y):
    return [("press", x, y), ("step", 1), ("release",), ("step", 1)]


def _key(k):
    return [("key_down", k), ("step", 1), ("key_up", k), ("step", 1)]


# The S5 drive (``laws.harness.drive`` steps): hover twice, the Button, a
# TextInput submit, two Menu picks, two act changes, the ball's run.
S5_STEPS = (
    [("step", 8)] + _hover_pass() + _click(50, 375)
    + _click(150, 375) + _key("A") + _key("ENTER") + _click(300, 300)
    + _key("M") + _click(300, 200) + [("step", 10)]
    + _hover_pass() + _click(50, 375) + _key("M") + _click(300, 200)
    + [("step", 20)] + _key("N") + [("step", 20)] + _hover_pass()
    + _key("N") + [("step", 25)]
)

@dataclass
class Result:
    events: List[tuple]
    chaos: Chaos
    report: Any
    error: Optional[BaseException] = None
    error_kind: Optional[str] = None
    error_where: str = ""
    zombies: List[str] = field(default_factory=list)
    leftovers: List[str] = field(default_factory=list)
    state: Dict[str, Any] = field(default_factory=dict)

    @property
    def fired(self) -> Optional[Fired]:
        return self.chaos.fired[0] if self.chaos.fired else None


class _Closed:
    """A run whose start raised (``ProgramRun.start`` closed it already)."""

    def __init__(self, prun) -> None:
        self.laws = prun.laws


def run(program: str, *, frames: Optional[int] = None, steps=None,
        plan: Sequence[Tuple[str, int, str]] = (), seed: int = 0, listing: bool = False,
        rewrite_it: bool = True, params: Optional[Dict[str, Any]] = None,
        patches: Sequence[Tuple[Any, str, Any]] = (), motion: bool = True,
        transform: Optional[Callable] = None) -> Result:
    """Run ``program`` (``frames`` of ``ProgramRun``, or OS-level ``steps`` as
    ``laws.harness.drive`` takes them) with the recorder and the chaos
    rewrite. An exception out of a frame ends the run and is classified."""
    from system_support import zombies
    chaos = Chaos(plan, seed=seed, listing=listing)
    error = None
    state: Dict[str, Any] = {}
    zs: List[str] = []
    with ExitStack() as stack:
        for target, attr, new in patches:
            stack.enter_context(mock.patch.object(target, attr, new))
        if steps is not None:
            from game_harness import GameRun
            prun = GameRun(program, params or {}, probes={})
            prun.os_level = True
        else:
            from program_support import ProgramRun
            prun = ProgramRun(program, params or {}, probes={})
        if rewrite_it:
            prun.transform = transform or rewrite
            prun.inject = {NAME: chaos}
        attach(prun, motion=motion)
        try:
            prun.start()                 # the top level and the first act build run here
        except Exception as e:  # noqa: BLE001  (start() already closed the run)
            error = e
            prun = _Closed(prun)
        try:
            try:
                if isinstance(prun, _Closed):
                    pass
                elif steps is not None:
                    for st in steps:
                        if st[0] == "step":
                            prun.step(st[1])
                        else:
                            getattr(prun, st[0])(*st[1:])
                else:
                    prun.step(frames)
            except Exception as e:  # noqa: BLE001
                error = e
            st_cell = prun.ns.get("st") if not isinstance(prun, _Closed) else None
            state = {k: getattr(st_cell, k) for k in st_cell.keys()} if st_cell is not None else {}
            zs = [] if isinstance(prun, _Closed) else [f"{where}: {trace._rec.label_of(o) if trace._rec else type(o).__name__}"
                  for where, o in zombies()]
        finally:
            if trace.installed():
                trace.uninstall()
            if not isinstance(prun, _Closed):
                prun.close(strict=False)
    events = prun.laws.events
    res = Result(events, chaos, model.check(events), error=error, zombies=zs, state=state)
    if error is not None:
        res.error_kind, res.error_where = classify(error)
    if prun.laws.errors:
        chaos.findings.append(f"E0|recorder: {prun.laws.errors[:3]}")
    return res


def run_family(kind: str, name: str, scenario: str, *, spec_ns=None,
               plan: Sequence[Tuple[str, int, str]] = (), seed: int = 0,
               listing: bool = False, rewrite_it: bool = True,
               patches: Sequence[Tuple[Any, str, Any]] = ()) -> Result:
    """A game scenario (``kind="game"``) or a program scenario (``"program"``,
    with its spec) under the chaos rewrite, through the families' own runners
    (``game_harness.run_game``, ``program_oracles._run``)."""
    chaos = Chaos(plan, seed=seed, listing=listing)
    box: Dict[str, Any] = {}

    def hook(prun):
        if rewrite_it:
            prun.transform = rewrite
            prun.inject = {NAME: chaos}
        attach(prun, motion=True)
        box["run"] = prun

    error = None
    with ExitStack() as stack:
        for target, attr, new in patches:
            stack.enter_context(mock.patch.object(target, attr, new))
        try:
            if kind == "game":
                import game_harness as gh
                gh.run_game(name, scenario, before_start=hook)
            else:
                import program_oracles as po
                po._run(name, spec_ns, scenario, before_start=hook)
        except Exception as e:  # noqa: BLE001
            error = e
        finally:
            if trace.installed():
                trace.uninstall()
    events = box["run"].laws.events if "run" in box else []
    res = Result(events, chaos, model.check(events), error=error)
    if error is not None:
        res.error_kind, res.error_where = classify(error)
    if "run" in box and box["run"].laws.errors:
        chaos.findings.append(f"E0|recorder: {box['run'].laws.errors[:3]}")
    return res


def run_script(path: str, frames: int, *, plan: Sequence[Tuple[str, int, str]] = (),
               seed: int = 0, listing: bool = False, timeout: float = 240) -> Result:
    """An example or a tutorial step, headless in a subprocess
    (``script_harness.py --chaos``): the trace and the chaos log come back as
    files; no zombie census (the process is gone)."""
    import json
    import subprocess
    import tempfile
    from laws.families import load_trace
    from laws.neutrality import HARNESS, ROOT
    with tempfile.TemporaryDirectory(prefix="chaos_") as tmp:
        spec = os.path.join(tmp, "plan.json")
        out = os.path.join(tmp, "trace.jsonl")
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"plan": [list(p) for p in plan], "seed": seed, "listing": listing,
                       "log": os.path.join(tmp, "chaos.json")}, fh)
        # ``--fingerprint`` as the plain run (``neutrality.run_script``) does:
        # the end world's fingerprint reads (and makes) objects in frame N.
        cmd = [sys.executable, HARNESS, path, str(frames), "--fingerprint", "--laws", out,
               "--chaos", spec]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, cwd=ROOT)
        events = load_trace(out) if os.path.exists(out) else []
        log = {}
        if os.path.exists(os.path.join(tmp, "chaos.json")):
            with open(os.path.join(tmp, "chaos.json"), encoding="utf-8") as fh:
                log = json.load(fh)
    meta = events.pop() if events and events[-1][0] == "meta" else None
    chaos = Chaos(plan, seed=seed, listing=listing)
    chaos.doors = [tuple(d) for d in log.get("doors", [])]
    chaos.fired = [Fired(**f) for f in log.get("fired", [])]
    chaos.findings = list(log.get("findings", []))
    res = Result(events, chaos, model.check(events))
    if meta is not None and meta[2]:
        chaos.findings.append(f"E0|recorder: {meta[2][:3]}")
    if log.get("error"):
        res.error = RuntimeError(log["error"])
        res.error_kind, res.error_where = log.get("error_kind"), log.get("error_where", "")
    elif p.returncode != 0 and not log:
        chaos.findings.append(f"RUN|exit {p.returncode}: {p.stderr[-400:]}")
    return res


def script_main(script: str, spec_path: str, run_it: Callable[[], None]) -> None:
    """``script_harness.py --chaos``: run ``script`` rewritten as ``__main__``
    (what ``runpy.run_path`` does) and write the chaos log."""
    import json
    import types
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    chaos = Chaos([tuple(p) for p in spec["plan"]], seed=spec["seed"], listing=spec["listing"])
    with open(script, encoding="utf-8") as fh:
        source = fh.read()
    code = compile(rewrite(ast.parse(source, script)), script, "exec")
    mod = types.ModuleType("__main__")
    mod.__file__ = script
    mod.__dict__[NAME] = chaos
    saved = sys.modules.get("__main__")
    sys.modules["__main__"] = mod
    log: Dict[str, Any] = {}
    try:
        run_it(lambda: exec(code, mod.__dict__))
    except Exception as e:  # noqa: BLE001
        kind, where = classify(e)
        log.update(error=f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}",
                   error_kind=kind, error_where=where)
    finally:
        sys.modules["__main__"] = saved
        log.update(doors=chaos.doors, findings=chaos.findings,
                   fired=[f.__dict__ for f in chaos.fired])
        with open(spec["log"], "w", encoding="utf-8") as fh:
            json.dump(log, fh, default=repr)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _drop_handles(events: Sequence[tuple], own: set) -> List[tuple]:
    """``events`` without the records of the handles in ``own``, and with
    the later handles of each kind renumbered as if those were never made
    (labels are ``kind@site#n``: one more handle shifts the ordinals)."""
    if not own:
        return list(events)
    rename: Dict[str, str] = {}
    seen: Counter = Counter()
    for e in events:
        if e[0] == "H" and e[1] == "add" and e[2] not in own:
            prefix = e[2].rsplit("#", 1)[0]
            rename[e[2]] = f"{prefix}#{seen[prefix]}"
            seen[prefix] += 1
    out = []
    for e in events:
        if e[0] == "H":
            if e[2] in own:
                continue
            e = e[:2] + (rename.get(e[2], e[2]),) + e[3:]
        out.append(e)
    return out


def neutral_diff(base: Sequence[tuple], other: Sequence[tuple], *, limit: int = 4,
                 own_handles: Sequence[str] = ()) -> List[str]:
    """The two traces per frame as multisets (``equations.project`` plus the
    timer records), different frames listed; ``[]``: the same run. A handle
    only one run made (a neutral command's own ``after(...).cancel()``) is
    that command's record, not a change of the run."""
    from laws.equations import compare, project
    own = set(own_handles)
    other = _drop_handles(other, own)
    a, b = project(base), project(other)
    for events, out in ((base, a), (other, b)):
        frame = 0
        for e in events:
            if e[0] == "F":
                frame = e[1]
            elif e[0] == "H" and e[1] in ("fire", "cancel") \
                    and not str(e[2]).startswith("Handle:sound"):
                # A sound ends by the audio clock (real time), not the frame:
                # under load its end moves a frame (S7, gate).
                out.setdefault(frame, Counter())[("H", e[1], e[2])] += 1
    return compare(a, b, limit=limit)


def _phase_span(events: Sequence[tuple], index: int) -> Tuple[Optional[str], int]:
    """The innermost phase open at ``index`` and the index where it closes."""
    stack: List[Tuple[str, int]] = []
    for i, e in enumerate(events[:index]):
        if e[0] == "P":
            stack.append((e[1], i))
        elif e[0] == "p" and stack and stack[-1][0] == e[1]:
            stack.pop()
        elif e[0] == "F":
            stack = []
    if not stack:
        return None, index
    name = stack[-1][0]
    depth = 0
    for j in range(index, len(events)):
        e = events[j]
        if e[0] == "P" and e[1] == name:
            depth += 1
        elif e[0] == "p" and e[1] == name:
            if depth == 0:
                return name, j
            depth -= 1
        elif e[0] == "F":
            return name, j
    return name, len(events)


CONTACT_DOORS = ("enter", "stay", "exit")
# Commands that can end the contact they run in (C5: its exit still runs).
ENDERS = frozenset({"destroy.self", "destroy.partner", "park", "park.resume", "untag",
                    "uncollide", "group.destroy", "group.untag_all", "group.churn",
                    "group.walk"})
# The loop a door belongs to: what a command makes waits for the next run of
# *that* loop (a pass is one loop over its snapshot). A clone made in a timer
# fire gets its ``on_update`` this tick: the fleet's loop starts after the
# timers' (as an actor made in ``update`` does).
LOOP = {"enter": "contacts", "stay": "contacts", "exit": "contacts",
        "after": "timers", "every": "timers", "on_update": "fleet",
        "leave": "leave", "hover": "hover", "hover_exit": "hover"}
# Doors that run where they are called (F2): a creation's setup, a destroy's
# hooks, an act build, a nested door (a mode a handler started).
_SYNC_DOORS = ("setup", "act-build", "act-teardown", "on_destroy", "exit-of", "exit-keys")


def owed(base: Sequence[tuple], got: Sequence[tuple], fired: Fired) -> List[str]:
    """The snapshot rule (F3) on the pass the command ran in, against the same
    pass of the idle run (identical up to ``fired.index``).

    * owed and paid: the rest of the injected contact's handlers run (C3),
      unless the command changed the act (it cancels what the act owed);
    * new waits: nothing the command made gets a door of this pass, but the
      doors that run where they are called (``setup``, ``on_destroy``, …)
      and flush (it runs to quiet).
    """
    out: List[str] = []
    if fired.outcome != "ran":
        return out
    i = fired.index
    phase, end_got = _phase_span(got, i)
    _, end_base = _phase_span(base, i)
    if phase is None:
        return out
    door = fired.door.split(">")[0]
    x = next((e for e in reversed(got[:i]) if e[0] == "X"), None)
    here = tuple(sorted(a for a in x[4][:2] if a)) if x is not None and x[1].split(">")[0] \
        in CONTACT_DOORS else ()
    if phase == "collision":
        # Removed starts nothing: after the command, an enter or stay handler
        # that receives a body the command (or its cascade) destroyed belongs
        # to the contact it was in (C3, owed) — and to none after an act change.
        # Only what the command removed: a body a later handler destroys owes
        # its own contact's handlers (S7: a Mine's second method).
        dead = {e[1] for e in got[i:fired.end] if e[0] == "d" and e[2]}
        for e in got[fired.end:end_got]:
            if e[0] == "X" and e[1] in ("enter", "stay") and dead.intersection(e[4][:2]):
                pair = tuple(sorted(a for a in e[4][:2] if a))
                if fired.command == "act" or pair != here:
                    out.append(f"F3|{fired.command}@{fired.door}#{fired.n}: {e[1]} {e[3]} "
                               f"ran with a removed body {sorted(dead.intersection(e[4][:2]))}"
                               + (" after the act changed" if fired.command == "act" else ""))
                    break
    if here and phase == "collision" and fired.command != "act":
        removed = {e[1] for e in got[i:fired.end] if e[0] == "d" and e[2]} & set(here)
        step_base = base[i:end_base]
        resolved = any(e[0] == "M" and e[1] == "post" and here in e[3] for e in step_base)
        if removed and resolved and not any(e[:2] == ("S", "ghost") for e in got[i:end_got]):
            out.append(f"C8|{fired.command}@{fired.door}#{fired.n}: {sorted(removed)} left "
                       f"the step with no ghost contact (the survivor's response)")
        if fired.command in ENDERS and door != "exit":
            # (Inside the contact's own exit, that exit is the one running.)
            # The window: this step and the next (an untag in a handler is
            # matched by the next step's exit, PB1). Later the runs part ways.
            def window(evs):
                ends = [j for j in range(i, len(evs)) if evs[j][:2] == ("p", "collision")][:2]
                return evs[i:ends[-1] + 1] if ends else evs[i:]

            def exits(evs):
                return sum(1 for e in evs if e[0] == "X" and e[1].startswith("exit")
                           and tuple(sorted(a for a in e[4][:2] if a)) == here)
            w_got = window(got)
            ended = any(e[0] == "C" and here in e[3] for e in w_got) or removed
            ever = any(e[0] == "X" and e[1].startswith("exit")
                       and tuple(sorted(a for a in e[4][:2] if a)) == here for e in base)
            if ever and ended and not exits(w_got):
                out.append(f"C5|{fired.command}@{fired.door}#{fired.n}: the contact {here} "
                           f"ended and its exit never ran")
    if door in CONTACT_DOORS and phase == "collision" and fired.command != "act":
        # The injected contact: the pair of the X event that opened this door.
        x = next((e for e in reversed(base[:i]) if e[0] == "X" and e[1].split(">")[0] == door), None)
        pair = tuple(sorted(a for a in x[4][:2] if a)) if x is not None else ()
        if len(pair) == 2:
            def rest(evs, lo, hi):
                c = Counter()
                for e in evs[lo:hi]:
                    if e[0] == "X" and e[1].split(">")[0] == door \
                            and tuple(sorted(a for a in e[4][:2] if a)) == pair:
                        c[(e[1], e[3], e[4])] += 1
                    elif e[0] == "S":
                        break           # the step's handlers are over
                return c
            want, have = rest(base, i, end_base), rest(got, i, end_got)
            hidden = want - have
            if hidden:
                out.append(f"C3|{fired.command}@{fired.door}#{fired.n}: the contact's "
                           f"handlers {sorted(hidden.elements())[:3]} did not run")
    if phase != "flush":
        made = {e[1] for e in got[i:end_got] if e[0] == "N"}
        loop = LOOP.get(door)
        handles = {e[2] for e in got[i:end_got] if e[0] == "H" and e[1] == "add"}
        for e in got[i:end_got]:
            if e[0] == "X":
                d = e[1].split(">")[0]
                if ">" in e[1] or d in _SYNC_DOORS:
                    continue
                if loop is not None and LOOP.get(d) == loop and e[4] and e[4][0] in made:
                    out.append(f"F3|{fired.command}@{fired.door}#{fired.n}: {e[1]} of "
                               f"{e[4][0]}, made this pass, ran in it ({phase})")
                    break
            elif e[0] == "H" and e[1] == "fire" and e[2] in handles:
                out.append(f"F3|{fired.command}@{fired.door}#{fired.n}: timer {e[2]} made "
                           f"in {phase} fired in it")
                break
    return out


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def menu(doors: Sequence[Tuple[str, int, int, int, str]]) -> List[Tuple[str, int, int]]:
    """``(door, n, frame)`` of each sampled door return (pull doors excluded)."""
    return [(d, n, f) for d, n, f, _i, _fn in doors if d.split(">")[0] not in UNSAMPLED]


def draw(doors, seed: int, k: int, commands: Sequence[str] = tuple(COMMANDS)) \
        -> List[Tuple[str, int, str]]:
    """``k`` single-fault plans, each door drawn with weight 1 / (its door's
    count), so rare doors (hover, leave, flush, on_done) are not drowned."""
    rng = random.Random(seed)
    items = menu(doors)
    if not items:
        return []
    freq = Counter(d for d, _n, _f in items)
    weights = [1.0 / freq[d] for d, _n, _f in items]
    out = []
    for _ in range(k):
        d, n, _f = rng.choices(items, weights)[0]
        out.append((d, n, rng.choice(list(commands))))
    return out


def every_door(doors, commands: Sequence[str], *, per_door: int = 1, seed: int = 0) \
        -> List[Tuple[str, int, str]]:
    """Every door kind × every command, at ``per_door`` occurrences of it."""
    rng = random.Random(seed)
    by: Dict[str, List[int]] = {}
    for d, n, _f in menu(doors):
        by.setdefault(d, []).append(n)
    out = []
    for d in sorted(by):
        ns = by[d]
        picks = sorted(set([ns[0]] + rng.sample(ns, min(len(ns), per_door))))[:per_door]
        for n in picks:
            for c in commands:
                out.append((d, n, c))
    return out


def ddmin(plan: List[Tuple[str, int, str]], fails: Callable[[List], bool]) -> List:
    """The smallest sub-plan that still fails (classic delta debugging)."""
    n = 2
    while len(plan) >= 2:
        chunk = max(1, len(plan) // n)
        subsets = [plan[i:i + chunk] for i in range(0, len(plan), chunk)]
        reduced = False
        for i, sub in enumerate(subsets):
            rest = [x for j, s in enumerate(subsets) if j != i for x in s]
            if fails(sub):
                plan, n, reduced = sub, 2, True
                break
            if rest and fails(rest):
                plan, n, reduced = rest, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(plan):
                break
            n = min(len(plan), n * 2)
    return plan


# ---------------------------------------------------------------------------
# One verdict per run
# ---------------------------------------------------------------------------

def verdict(base: Result, got: Result, *, known: Sequence[str] = ()) -> List[str]:
    """Every finding of a single-fault run (``[]``: clean)."""
    out = list(got.chaos.findings)
    out += [f.sig for f in got.report.findings if f.sig not in known]
    if got.error is not None and got.error_kind == "internal":
        out.append(f"X2|escaped: {type(got.error).__name__} at {got.error_where}: "
                   f"{str(got.error).splitlines()[0][:160] if str(got.error) else ''}")
    out += [f"L3|zombie {z}" for z in got.zombies if z not in base.zombies]
    # The owed and neutral checks compare with the idle run, which is the
    # same run only up to the first command: they judge that one.
    for f in got.chaos.fired[:1]:
        out += owed(base.events, got.events, f)
        if COMMANDS[f.command].neutral and f.outcome == "ran" and got.error is None \
                and len(got.chaos.fired) == 1:
            own = [e[2] for e in got.events[f.index:f.end] if e[0] == "H" and e[1] == "add"]
            diff = neutral_diff(base.events, got.events, own_handles=own)
            if diff:
                out.append(f"E0|{f.command}@{f.door}#{f.n}: {diff[0]}")
    return out


def repro(program: str, plan: Sequence[Tuple[str, int, str]], seed: int) -> str:
    spec = ",".join(f"{d}:{n}:{c}" for d, n, c in plan)
    return f"python tests/laws/chaos.py {program} --plan {spec} --seed {seed}"


def main(argv: Sequence[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("program")
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--plan", default="")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    plan = []
    for item in filter(None, a.plan.split(",")):
        d, n, c = item.rsplit(":", 2)
        plan.append((d, int(n), c))
    steps = S5_STEPS if os.path.basename(a.program).startswith("s5_doors") else None
    base = run(a.program, frames=a.frames, steps=steps, seed=a.seed, listing=True)
    got = run(a.program, frames=a.frames, steps=steps, plan=plan, seed=a.seed)
    for f in got.chaos.fired:
        print(f"fired {f}")
    if got.error is not None:
        print(f"error ({got.error_kind}): {got.error!r} at {got.error_where}")
    found = verdict(base, got)
    print("\n".join(found) if found else "clean")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
