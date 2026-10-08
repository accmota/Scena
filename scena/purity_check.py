"""Read-only checks for author code the collision solver calls (``only=``).

A ``resolve(..., only=fn)`` function runs inside the collision step, several
times a frame (each slide, settle, floor snap). It must only read and answer
the same way all frame. Two layers keep that honest, and neither costs
anything on a hot path:

* **Static, at ``resolve()`` time** (``check_read_only``): read the function's
  code once (same locator as ``@=`` formulas) and refuse writes to Scena
  objects, Scena verbs that change the world or consume state, spawning, and
  ``global`` / ``nonlocal``. Plain functions it calls are followed when their
  source can be read.
* **Runtime lock** (``solver_reading`` / ``refuse_if_solver_reading``): while
  the function runs, cold choke points (collision registrations, tag changes,
  ``destroy()``, spawning, scheduling, sound, ``keyp.once``, ``recently`` /
  ``ready``, ``st`` writes) raise. Pose writes are not locked at runtime —
  they are the engine's hottest path — so the static pass is what refuses them.

Loops, local variables, and writes to the author's own plain objects (a dict,
a list) are allowed: they cannot change the world the solver is reading.
"""
from __future__ import annotations

import ast
import builtins
import inspect
from typing import Any, Callable, Dict, List, Optional, Set

from .formula_check import (
    _MISSING,
    _is_scena_callable,
    _is_scena_object,
    _param_names,
    _resolve_chain,
    _unwrap_function,
    formula_context,
    locate_formula_node,
)

__all__ = ["check_read_only", "solver_reading", "refuse_if_solver_reading"]

# --- runtime lock ------------------------------------------------------------

# Stack of the functions running inside the solver (normally 0 or 1 deep).
# Choke points test its truth: one global read, only on cold paths.
_READING: List[Any] = []


def fn_label(fn: Any) -> str:
    """``name`` or ``<lambda>``, with ``file:line`` when the code is known."""
    func = _unwrap_function(fn)
    name = getattr(func, "__name__", None) or type(fn).__name__
    code = getattr(func, "__code__", None)
    if code is None:
        return name
    path = code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
    return f"{name} ({path}:{code.co_firstlineno})"


class solver_reading:
    """``with solver_reading(fn): fn(...)`` — refuse cold-path writes meanwhile."""

    __slots__ = ("_fn",)

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def __enter__(self) -> None:
        _READING.append(self._fn)

    def __exit__(self, *exc: Any) -> None:
        _READING.pop()


def refuse_if_solver_reading(what: str) -> None:
    """Raise when author code inside the solver tries ``what`` (a cold write)."""
    if _READING:
        raise RuntimeError(
            f"{what} ran inside resolve(..., only={fn_label(_READING[-1])}). "
            "An only= function runs inside the collision step, several times a "
            "frame, and must only read. Do the change in update() or in an "
            "@collide handler (which still fires while the pair passes)."
        )


# --- static check --------------------------------------------------------------

# Scena functions that change the world, schedule, or consume per-frame state.
# ``chance`` rolls the RNG (a second call answers differently); ``recently`` /
# ``ready`` advance keyed timers; ``flush`` runs reactive updates mid-solve.
_SCENA_WRITER_FUNCS = frozenset({
    "after", "every", "tween", "play_sound", "recently", "ready", "chance",
    "resolve", "unresolve", "change_act", "flush", "init", "run",
    "collide", "collide_exit", "collide_stay", "collide_with",
    "collide_with_exit", "collide_with_stay", "on_change", "when",
    "unregister_event", "exit_mode", "drag_to", "drop_by", "drag_over",
    "set_defaults", "set_extrude_focus", "set_fx_auto",
    "set_watchdog", "show_tracks", "clear_author_error",
    "wait", "until", "until_empty", "race", "parallel",
})

# Scena method names that change the world or consume state. Checked by name
# when the receiver is a Scena object or cannot be resolved (``c.other``).
# ``once`` is ``keyp.once`` (the edge is consumed: a second call is False).
_SCENA_WRITER_METHODS = frozenset({
    "absorb", "add_hitbox", "add_to_group", "after", "bake", "blink",
    "bounce_apart", "bubbles_at", "burn_out", "burst_at", "cancel",
    "cancel_process", "clear_transients", "clone", "confine", "debris_at", "destroy",
    "dissolve_in", "dissolve_out", "every", "explosion_at", "fade_in",
    "fade_out", "fade_to", "fireworks_at", "flash", "flash_text", "frame_to",
    "glitch", "goto_mode", "hit_at", "implode", "knock", "move_along", "move_by",
    "move_to", "move_to_back", "move_to_front", "no_drag", "no_drop",
    "no_handles", "no_points", "no_wheel_rotate", "once", "orbit", "pan_by",
    "pan_to", "pause", "play", "play_sound", "prepare_fx", "pulse_outline",
    "push_apart", "ready", "recently", "release", "remove_from_group",
    "remove_hitbox", "reset_rotation", "reset_view", "resolve", "resolve_now",
    "restore_visual", "resume", "ripple_at", "rotate_by", "rotate_to",
    "save_visual", "scale_by", "scale_to", "set_alpha", "set_color",
    "set_defaults", "set_fly", "set_origin", "shake", "show_colliders",
    "show_handles", "show_points", "show_tracks", "shuttle", "spark_burst",
    "stop", "tag", "tween", "undraw", "unlink", "unlink_all", "untag",
    "wander", "wave_at", "zap_at", "zoom_by", "zoom_to",
})

# Scena classes that are plain values: building one does not spawn anything.
_SCENA_VALUE_CLASSES = frozenset({"Vec2", "Color"})

# Builtins that write attributes or run code the check cannot read. ``print``
# is fine (debugging a predicate is normal); it does not touch Scena.
_WRITER_BUILTINS = frozenset({
    "setattr", "delattr", "exec", "eval", "compile", "__import__", "globals",
    "vars",
})

# A local is the function's own object only when every assignment builds a
# fresh plain value; ``h = heroi`` is an alias, and writes through it refuse.
_FRESH_NODES = (
    ast.Dict, ast.List, ast.Set, ast.Tuple, ast.Constant, ast.ListComp,
    ast.DictComp, ast.SetComp, ast.JoinedStr,
)
_FRESH_BUILTINS = frozenset({"dict", "list", "set", "tuple", "str", "int", "float", "bool"})

_MAX_DEPTH = 4

_HINT = (
    "It runs inside the collision step, several times a frame, and must only "
    "read. Do the change in update() (store the result, then read it here) or "
    "in an @collide handler."
)


def _owner_label(fn: Any) -> str:
    return f"only={fn_label(fn)}"


def check_read_only(fn: Callable[..., Any]) -> None:
    """Refuse an ``only=`` function whose code writes (see module doc).

    A callable without readable source (a builtin, a C function, code typed in
    a REPL) is not checked here; the runtime lock still applies to it.
    """
    node = locate_formula_node(fn)
    if node is None:
        return
    try:
        ctx = formula_context(fn)
    except (TypeError, ValueError):
        return
    _Visitor(fn, fn, node, ctx, depth=0, seen=set()).run()


def _is_author_function(value: Any) -> bool:
    func = _unwrap_function(value)
    if not inspect.isfunction(func):
        return False
    return not _is_scena_callable(func)


class _Visitor(ast.NodeVisitor):
    def __init__(self, root_fn, fn, node, ctx, *, depth, seen):
        self.root_fn = root_fn
        self.fn = fn
        self.node = node
        self.ctx = ctx
        self.depth = depth
        self.seen = seen
        args = getattr(node, "args", None)
        self.params: Set[str] = set()
        if isinstance(args, ast.arguments):
            names = _param_names(args)
            # A default-captured object resolves through ctx at the root
            # (``def f(c, b=branch)``); a bound method's receiver resolves at
            # any depth (``rules.lands``). The rest are arguments.
            receiver = names[0] if names and getattr(fn, "__self__", None) is not None else None
            self.params = {
                n for n in names
                if not (n in ctx and (depth == 0 or n == receiver))
            }
        body = node.body if isinstance(node.body, list) else [node.body]
        self.assigned: Set[str] = set()
        fresh: Dict[str, bool] = {}
        for stmt in body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    self.assigned.add(sub.id)
                    fresh.setdefault(sub.id, False)
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.assigned.add(sub.name)
        # Second pass: a name stays "own" only if every plain ``name = value``
        # builds a fresh value and it is bound no other way (loop, with, :=).
        plain: Dict[str, List[ast.AST]] = {}
        other_binds: Set[str] = set()
        for stmt in body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            plain.setdefault(t.id, []).append(sub.value)
                        else:
                            for n in ast.walk(t):
                                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                                    other_binds.add(n.id)
                elif isinstance(sub, (ast.For, ast.AsyncFor, ast.comprehension)):
                    for n in ast.walk(sub.target):
                        if isinstance(n, ast.Name):
                            other_binds.add(n.id)
                elif isinstance(sub, (ast.With, ast.AsyncWith)):
                    for item in sub.items:
                        if item.optional_vars is not None:
                            for n in ast.walk(item.optional_vars):
                                if isinstance(n, ast.Name):
                                    other_binds.add(n.id)
                elif isinstance(sub, ast.NamedExpr):
                    other_binds.add(sub.target.id)
                elif isinstance(sub, (ast.AugAssign, ast.AnnAssign)) and isinstance(sub.target, ast.Name):
                    if isinstance(sub, ast.AnnAssign) and sub.value is not None:
                        plain.setdefault(sub.target.id, []).append(sub.value)
        self.own: Set[str] = {
            name for name, values in plain.items()
            if name not in other_binds and name not in self.params
            and all(_is_fresh(v) for v in values)
        }
        self.local = self.params | self.assigned

    def run(self) -> None:
        body = self.node.body if isinstance(self.node.body, list) else [self.node.body]
        for stmt in body:
            self.visit(stmt)

    # -- refusal -------------------------------------------------------------
    def refuse(self, node: ast.AST, what: str) -> None:
        line = getattr(node, "lineno", None)
        where = ""
        if self.fn is not self.root_fn:
            where = f" (in {getattr(_unwrap_function(self.fn), '__name__', '?')}()"
            where += f", line {line})" if line else ")"
        elif line:
            where = f" (line {line})"
        raise TypeError(f"{_owner_label(self.root_fn)}{where} {what}. {_HINT}")

    # -- statements ----------------------------------------------------------
    def visit_Global(self, node):
        self.refuse(node, "uses global/nonlocal (a write to shared state)")

    visit_Nonlocal = visit_Global

    def visit_Assign(self, node):
        for target in node.targets:
            self._check_target(target, node)
        self.visit(node.value)

    def visit_AugAssign(self, node):
        self._check_target(node.target, node, augmented=True)
        self.visit(node.value)

    def visit_AnnAssign(self, node):
        self._check_target(node.target, node)
        if node.value is not None:
            self.visit(node.value)

    def visit_Delete(self, node):
        for target in node.targets:
            self._check_target(target, node)

    def _check_target(self, target, stmt, augmented: bool = False) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._check_target(elt, stmt)
            return
        if isinstance(target, ast.Starred):
            self._check_target(target.value, stmt)
            return
        if isinstance(target, ast.Name):
            return  # a local
        if not isinstance(target, (ast.Attribute, ast.Subscript)):
            return
        if isinstance(stmt, ast.AugAssign) and isinstance(stmt.op, ast.MatMult):
            self.refuse(stmt, f"links {ast.unparse(target)} with @=")
        written = target.value
        if self._is_own_object(written):
            self.visit(written)
            return
        self.refuse(stmt, f"writes {ast.unparse(target)}")

    def _is_own_object(self, expr: ast.AST) -> bool:
        """True when ``expr`` is the function's own plain object (not Scena).

        A local built inside the function, or a module / closure value that is
        not a Scena object (the author's dict, list, or plain class).
        """
        root = expr
        while isinstance(root, (ast.Attribute, ast.Subscript)):
            root = root.value
        if not isinstance(root, ast.Name):
            return False
        if root.id in self.own:
            return True
        if root.id in self.local:
            return False  # the contact, a helper's argument, or an alias
        value, _is_local = _resolve_chain(expr, self.ctx, self.local)
        if value is _MISSING:
            value = self.ctx.get(root.id, _MISSING)
            if value is _MISSING:
                return False
            return not _is_scena_object(value) and not _holds_scena(value)
        return not _is_scena_object(value)

    # -- expressions ---------------------------------------------------------
    def visit_NamedExpr(self, node):
        self.visit(node.value)  # binds a local

    def visit_Call(self, node):
        self._check_callee(node)
        self.generic_visit(node)

    def _check_callee(self, call: ast.Call) -> None:
        func = call.func
        if isinstance(func, ast.Name):
            name = func.id
            if name in self.local:
                return
            value = self.ctx.get(name, _MISSING)
            if value is _MISSING:
                # Scena injects ``st`` / ``keyp`` / ``recently`` / ``ready`` into
                # builtins, so a script may use them without importing.
                value = getattr(builtins, name, _MISSING)
            if value is _MISSING:
                return
            self._check_value_call(call, name, value)
            return
        if isinstance(func, ast.Attribute):
            method = func.attr
            recv = func.value
            value, _is_local = _resolve_chain(func, self.ctx, self.local)
            if value is not _MISSING:
                if _is_author_function(value):
                    self._follow(call, value)
                    return
                if method in _SCENA_WRITER_METHODS and _is_scena_callable(
                    _unwrap_function(value)
                ):
                    self.refuse(call, f"calls {ast.unparse(func)}()")
                return
            if method in _SCENA_WRITER_METHODS and not self._is_own_object(recv):
                self.refuse(call, f"calls {ast.unparse(func)}()")

    def _check_value_call(self, call: ast.Call, name: str, value: Any) -> None:
        # Scena first: Scena's own names can also live in builtins.
        if not _is_scena_callable(value) and value is getattr(builtins, name, _MISSING):
            if name in _WRITER_BUILTINS:
                self.refuse(call, f"calls {name}()")
            return
        if inspect.isclass(value):
            if _is_scena_callable(value) and value.__name__ not in _SCENA_VALUE_CLASSES:
                self.refuse(call, f"creates a {value.__name__}")
            return
        if _is_scena_callable(value):
            if getattr(value, "__name__", name) in _SCENA_WRITER_FUNCS or name in _SCENA_WRITER_FUNCS:
                self.refuse(call, f"calls {name}()")
            return
        if _is_author_function(value):
            self._follow(call, value)

    def _follow(self, call: ast.Call, value: Any) -> None:
        func = _unwrap_function(value)
        code = getattr(func, "__code__", None)
        if code is None or code in self.seen or self.depth >= _MAX_DEPTH:
            return
        self.seen.add(code)
        node = locate_formula_node(value)
        if node is None:
            return
        try:
            ctx = formula_context(value)
        except (TypeError, ValueError):
            return
        _Visitor(self.root_fn, value, node, ctx, depth=self.depth + 1, seen=self.seen).run()

    # Nested definitions are only followed when called.
    def visit_FunctionDef(self, node):
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node):
        return


def _is_fresh(value: ast.AST) -> bool:
    if isinstance(value, _FRESH_NODES):
        return True
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in _FRESH_BUILTINS
    )


def _holds_scena(value: Any) -> bool:
    if isinstance(value, dict):
        items = value.values()
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = value
    else:
        return False
    return any(_is_scena_object(v) for v in items)
