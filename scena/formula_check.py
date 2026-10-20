"""Static side of ``@=`` formulas: find the source node, refuse what it hides.

``FormulaLink`` learns its sources once, at link time, by reading the
formula's code (``state._extract_sources``). Nothing is traced while the game
runs, so a read the static pass cannot see would leave the link silently
stale. This module keeps that contract honest:

* ``locate_formula_node(fn)`` — the ``ast.Lambda`` / ``ast.FunctionDef`` for a
  formula. Cached: the script file is parsed once per ``(path, mtime)`` and the
  node is remembered per code object, so linking the same lambda from a spawn
  loop does not re-parse the script each time.
* ``check_formula(fn, node)`` — refuses shapes whose reads cannot be seen
  (loops, comprehensions, writes, nested functions, calls into code Scena
  cannot read, group reads, variable indexes into collections of Scena
  objects, a bracket handle read as a value: ``st["score"] * 2``). Returns the helper functions the formula calls, so the extractor
  can collect their sources too.

Only link time pays for this. Evaluating a formula is a plain call.
"""
from __future__ import annotations

import ast
import builtins
import inspect
import os
import sys
import time
import types
import weakref

from ._pkg import is_framework_module
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

__all__ = [
    "locate_formula_node",
    "formula_context",
    "formula_locals",
    "check_formula",
    "FormulaPart",
    "clear_formula_caches",
    "source_is_stale",
]

# --- source location (cached) ------------------------------------------------

_FILE_AST: Dict[str, Tuple[float, ast.Module]] = {}
_NODE_CACHE: Dict[types.CodeType, Optional[ast.AST]] = {}
_NODE_CACHE_MAX = 4096


def clear_formula_caches() -> None:
    """Drop parsed files and located nodes (tests; long sessions)."""
    _FILE_AST.clear()
    _NODE_CACHE.clear()


def _file_tree(path: str) -> Optional[ast.Module]:
    """Parsed module for ``path``, re-parsed only when the file changes."""
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return None
    hit = _FILE_AST.get(path)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None
    _FILE_AST[path] = (mtime, tree)
    return tree


def _snippet_tree(fn: Callable[..., Any]) -> Optional[ast.Module]:
    """Parse ``inspect.getsource(fn)`` when the file itself cannot be read.

    ``@when`` / ``@on_change``: getsource may include the decorator; peel the
    argument expression so a lone lambda parses cleanly.
    """
    try:
        source_code = inspect.getsource(fn).strip()
        for deco, deco_len in (("@when", 5), ("@on_change", 10)):
            when_start = source_code.find(deco)
            if when_start == -1:
                continue
            paren_start = when_start + deco_len
            while paren_start < len(source_code) and source_code[paren_start].isspace():
                paren_start += 1
            if paren_start >= len(source_code) or source_code[paren_start] != "(":
                continue
            paren_count = 0
            paren_start += 1
            for i, char in enumerate(source_code[paren_start:], paren_start):
                if char == "(":
                    paren_count += 1
                elif char == ")":
                    if paren_count == 0:
                        source_code = source_code[paren_start:i].strip()
                        break
                    paren_count -= 1
            break
        return ast.parse(source_code)
    except (OSError, TypeError, SyntaxError, IndexError):
        return None


def _pos_in_lambda(node: ast.Lambda, line: int, col: int) -> bool:
    end_line = node.end_lineno if node.end_lineno is not None else node.lineno
    if not (node.lineno <= line <= end_line):
        return False
    end_col = node.end_col_offset
    if node.lineno == end_line:
        if end_col is None:
            return col >= node.col_offset
        return node.col_offset <= col < end_col
    if line == node.lineno:
        return col >= node.col_offset
    if line == end_line:
        return end_col is None or col < end_col
    return True


def _first_body_col(code: types.CodeType) -> Optional[int]:
    target = code.co_firstlineno
    for line, _end_line, col, _end_col in code.co_positions():
        if line == target and col is not None and col > 0:
            return col
    return None


def _find_lambda(tree: ast.AST, code: types.CodeType) -> Optional[ast.Lambda]:
    """The lambda for ``code``, even when several share a line.

    Constructor kwargs like ``Circle(center=lambda: a, radius=lambda: b)`` put
    several lambdas in one statement. Matching by ``co_firstlineno`` plus the
    ``co_positions`` column picks the right node so sibling bodies do not merge.
    """
    target_line = code.co_firstlineno
    lambdas = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Lambda) and n.lineno == target_line
    ]
    if not lambdas:
        lambdas = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Lambda)
            and n.lineno <= target_line <= (n.end_lineno or n.lineno)
        ]
    if not lambdas:
        return None
    if len(lambdas) == 1:
        return lambdas[0]
    col = _first_body_col(code)
    if col is None:
        return None
    covering = [n for n in lambdas if _pos_in_lambda(n, target_line, col)]
    if not covering:
        return None
    # Innermost match when lambdas nest on the same line.
    return min(
        covering,
        key=lambda n: (
            (n.end_col_offset or n.col_offset) - n.col_offset,
            n.col_offset,
        ),
    )


def _find_def(tree: ast.AST, code: types.CodeType, *, by_line: bool):
    """The ``def`` for ``code`` (decorated defs start at the first decorator)."""
    target_line = code.co_firstlineno
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if n.name != code.co_name:
            continue
        if not by_line:
            return n
        first = min([n.lineno] + [d.lineno for d in n.decorator_list])
        if n.lineno == target_line or first == target_line:
            return n
    return None


def _unwrap_function(fn: Any) -> Any:
    """Plain function behind a bound method (``obj.formula``)."""
    return getattr(fn, "__func__", fn)


def locate_formula_node(fn: Callable[..., Any]) -> Optional[ast.AST]:
    """``ast.Lambda`` / ``ast.FunctionDef`` for ``fn``, or ``None`` without source."""
    func = _unwrap_function(fn)
    code = getattr(func, "__code__", None)
    if code is None:
        return None
    try:
        return _NODE_CACHE[code]
    except KeyError:
        pass
    node = _locate_uncached(func, code)
    if len(_NODE_CACHE) >= _NODE_CACHE_MAX:
        _NODE_CACHE.clear()
    _NODE_CACHE[code] = node
    return node


def _locate_uncached(func: Any, code: types.CodeType) -> Optional[ast.AST]:
    is_lambda = code.co_name == "<lambda>"
    tree = None
    from_file = False
    try:
        path = inspect.getsourcefile(func) or inspect.getfile(func)
    except TypeError:
        path = None
    if path and not path.startswith("<"):
        tree = _file_tree(path)
        from_file = tree is not None
    if tree is None:
        tree = _snippet_tree(func)
    if tree is None:
        return None
    if is_lambda:
        node = _find_lambda(tree, code)
    else:
        node = _find_def(tree, code, by_line=from_file)
    if node is None and from_file and _edited_while_running(path):
        _STALE_CODES.add(code)
        return None
    if node is not None and not _node_matches_code(node, code):
        # The file on disk is not the source this code was compiled from (it
        # was edited and saved while the program runs): reading it would link
        # the formula to another lambda's names, or to none (bug PM14). No
        # node: lambdas fall back to the code object itself, and errors say
        # the file changed.
        _STALE_CODES.add(code)
        return None
    return node


# --- stale source (bug PM14) ---------------------------------------------------

_STALE_CODES: "weakref.WeakSet" = weakref.WeakSet()


def source_is_stale(fn: Callable[..., Any]) -> bool:
    """True when ``fn``'s file changed on disk since its code was compiled."""
    code = getattr(_unwrap_function(fn), "__code__", None)
    return code is not None and code in _STALE_CODES


# Scena is imported before the script's own code runs: a file modified after
# that was edited while the program runs.
_STARTED = time.time()


def _edited_while_running(path: str) -> bool:
    try:
        return os.stat(path).st_mtime > _STARTED
    except OSError:
        return False


def _code_names(code: types.CodeType) -> Set[str]:
    """Every name the compiled code uses, nested code objects included."""
    names: Set[str] = set()
    stack = [code]
    while stack:
        c = stack.pop()
        names.update(c.co_names, c.co_varnames, c.co_freevars, c.co_cellvars)
        stack.extend(k for k in c.co_consts if isinstance(k, types.CodeType))
    return names


def _node_names(node: ast.AST) -> Set[str]:
    """Names the source of ``node`` mentions inside its own code: parameters
    and the body (not defaults, decorators or annotations, which run outside)."""
    roots: List[ast.AST] = []
    args = node.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    if args.vararg is not None:
        params.append(args.vararg)
    if args.kwarg is not None:
        params.append(args.kwarg)
    names = {a.arg for a in params}
    roots.extend(node.body if isinstance(node.body, list) else [node.body])
    for root in roots:
        for n in ast.walk(root):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Attribute):
                names.add(n.attr)
    return names


def _node_matches_code(node: ast.AST, code: types.CodeType) -> bool:
    """The located source can be this code: same parameters, and every name it
    mentions is one the compiled code uses (a stale file almost never passes)."""
    if not isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
        return True
    n_params = code.co_argcount + code.co_kwonlyargcount
    a = node.args
    if [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)] != list(code.co_varnames[:n_params]):
        return False
    return _node_names(node) <= _code_names(code)


# --- resolution context --------------------------------------------------------

def formula_context(fn: Callable[..., Any]) -> Dict[str, Any]:
    """Names the formula can see: globals, closure, default-arg captures, ``self``.

    Default args are how a loop binds one object per lambda
    (``lambda h=host: h.angle``) and how a named function names a wide fan-in
    (``def f(b=branch): ...``). A bound method (``hud["text"] @= self.texto``)
    sees its receiver under the first parameter's name.
    """
    func = _unwrap_function(fn)
    closure = inspect.getclosurevars(func)
    ctx: Dict[str, Any] = {**closure.globals, **closure.nonlocals}
    code = func.__code__
    positional = code.co_varnames[: code.co_argcount]
    defaults = func.__defaults__ or ()
    if defaults:
        for name, value in zip(positional[-len(defaults):], defaults):
            ctx.setdefault(name, value)
    for name, value in (func.__kwdefaults__ or {}).items():
        ctx.setdefault(name, value)
    receiver = getattr(fn, "__self__", None)
    if receiver is not None and positional:
        ctx[positional[0]] = receiver
    return ctx


def _param_names(args: ast.arguments) -> List[str]:
    names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def formula_locals(node: ast.AST, ctx: Dict[str, Any], *, params_resolved: bool) -> Set[str]:
    """Names bound inside the formula: assignments, and unresolved parameters.

    A parameter with a default (or a bound ``self``) resolves through ``ctx``
    when ``params_resolved`` is True (the root formula). A helper's parameters
    are always locals: their values come from argument expressions, which are
    visited at the call site.
    """
    local: Set[str] = set()
    args = getattr(node, "args", None)
    if isinstance(args, ast.arguments):
        for name in _param_names(args):
            if params_resolved and name in ctx:
                continue
            local.add(name)
    body = node.body if isinstance(node.body, list) else [node.body]
    for stmt in body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                local.add(sub.id)
    return local


# --- the check ---------------------------------------------------------------

_MISSING = object()
_MAX_HELPER_DEPTH = 3

# Builtins that reach around the static pass (dynamic reads) or have effects.
_DENIED_BUILTINS = {
    "getattr", "setattr", "delattr", "eval", "exec", "compile", "__import__",
    "globals", "locals", "vars", "open", "input", "breakpoint",
}

_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))


class FormulaPart:
    """One function whose body the extractor reads (the formula or a helper)."""

    __slots__ = ("fn", "node", "context", "locals")

    def __init__(self, fn, node, context, locals_):
        self.fn = fn
        self.node = node
        self.context = context
        self.locals = locals_


def _is_scena_object(value: Any) -> bool:
    """A Scena value (includes author subclasses of Sprite / Entity / …)."""
    for cls in type(value).__mro__:
        mod = getattr(cls, "__module__", "") or ""
        if is_framework_module(mod):
            return True
    return False


def _module_of(value: Any) -> str:
    return getattr(value, "__module__", "") or ""


def _is_scena_callable(value: Any) -> bool:
    mod = _module_of(value)
    return is_framework_module(mod)


def _is_group_operator(value: Any) -> bool:
    return type(value).__name__ == "GroupOperator" and is_framework_module(_module_of(type(value)))  # exact-type: lazy import guard


def _label(fn: Any) -> str:
    func = _unwrap_function(fn)
    name = getattr(func, "__name__", repr(func))
    return "lambda" if name == "<lambda>" else f"{name}()"


def _refuse(fn: Any, node: ast.AST, what: str, hint: str) -> None:
    line = getattr(node, "lineno", None)
    where = f" (line {line})" if line else ""
    raise TypeError(
        f"@= formula {_label(fn)}{where} {what}. "
        f"Scena reads a formula once, when it is linked, to learn what it depends on — "
        f"{hint}"
    )


_HINT_LOOP = (
    "a loop's items are only known while it runs, so the link would miss them. "
    "Compute it in update() (or an @every), or use a group formula "
    "(group['all'] @= lambda: group['a'] | group['b'])."
)
_HINT_PURE = "a formula must only read values and return one; do the change in update() or a handler."
_HINT_CALL = (
    "Scena can follow plain functions written in this file, Scena helpers, "
    "builtins (len, min, round, …) and the standard library."
)


def _constant_key(node: ast.AST):
    """Literal subscript key (``0``, ``-1``, ``"name"``) or ``_MISSING``."""
    if isinstance(node, ast.Constant):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
    ):
        return -node.operand.value
    return _MISSING


def _resolve_chain(node: ast.AST, ctx: Dict[str, Any], local: Set[str]):
    """Statically resolve ``a.b[0].c`` → value, or ``_MISSING``.

    Returns ``(_MISSING, True)`` when the base is a local (value unknown at
    link time), ``(_MISSING, False)`` when the chain simply cannot be read.
    """
    steps = []
    cur = node
    while True:
        if isinstance(cur, ast.Attribute):
            steps.insert(0, ("attr", cur.attr))
            cur = cur.value
        elif isinstance(cur, ast.Subscript):
            key = _constant_key(cur.slice)
            if key is _MISSING:
                return _MISSING, False
            steps.insert(0, ("sub", key))
            cur = cur.value
        else:
            break
    if not isinstance(cur, ast.Name):
        return _MISSING, False
    if cur.id in local:
        return _MISSING, True
    value = ctx.get(cur.id, _MISSING)
    if value is _MISSING:
        value = getattr(builtins, cur.id, _MISSING)
    if value is _MISSING:
        return _MISSING, False
    for kind, key in steps:
        try:
            value = getattr(value, key) if kind == "attr" else value[key]
        except Exception:
            return _MISSING, False
    return value, False


def _holds_scena_objects(value: Any) -> bool:
    if isinstance(value, dict):
        items = value.values()
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return False
    return any(_is_scena_object(v) for v in items)


class _Checker(ast.NodeVisitor):
    def __init__(self, root_fn, fn, node, ctx, local, depth, seen, parts, containers=None):
        # ``(state, cell)`` read while it holds a list / dict / set (persona
        # probes PP): ``check_formula`` warns once per cell.
        self.containers = containers if containers is not None else set()
        self.root_fn = root_fn
        self.fn = fn
        self.node = node
        self.ctx = ctx
        self.local = local
        self.depth = depth
        self.seen = seen
        self.parts = parts
        self.root_globals = getattr(_unwrap_function(root_fn), "__globals__", None)

    def run(self) -> None:
        if isinstance(self.node, ast.Lambda):
            self.visit(self.node.body)
        else:
            for stmt in self.node.body:
                self.visit(stmt)

    # statements ------------------------------------------------------------
    def _refuse(self, node, what, hint):
        _refuse(self.fn, node, what, hint)

    def visit_For(self, node):
        self._refuse(node, "uses a for loop", _HINT_LOOP)

    visit_AsyncFor = visit_For

    def visit_While(self, node):
        self._refuse(node, "uses a while loop", _HINT_LOOP)

    def visit_With(self, node):
        self._refuse(node, "uses `with`", _HINT_PURE)

    visit_AsyncWith = visit_With

    def visit_Try(self, node):
        self._refuse(node, "uses try/except", "an error inside a formula should surface, not be hidden.")

    visit_TryStar = visit_Try

    def visit_FunctionDef(self, node):
        self._refuse(node, f"defines a function inside it ({node.name})",
                     "define it outside the formula and call it.")

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._refuse(node, f"defines a class inside it ({node.name})", "define it outside the formula.")

    def visit_Global(self, node):
        self._refuse(node, "uses global/nonlocal", _HINT_PURE)

    visit_Nonlocal = visit_Global

    def visit_Delete(self, node):
        self._refuse(node, "uses del", _HINT_PURE)

    def visit_Import(self, node):
        self._refuse(node, "imports inside it", "import at the top of the file.")

    visit_ImportFrom = visit_Import

    def visit_Match(self, node):
        self._refuse(node, "uses match", "write it with if / elif.")

    def _check_target(self, target):
        if isinstance(target, ast.Name):
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._check_target(elt)
            return
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            # Writing plain Python data (a counter dict, a list) hides no
            # read. Writing a Scena object mid-evaluation would change the
            # graph while it is being read; a local might be one — refuse.
            owner, _is_local = _resolve_chain(target.value, self.ctx, self.local)
            if owner is not _MISSING and not _is_scena_object(owner):
                self.visit(target.value)
                return
        self._refuse(target, "writes to a Scena object (or a value it cannot identify)", _HINT_PURE)

    def visit_Assign(self, node):
        for t in node.targets:
            self._check_target(t)
        self.visit(node.value)

    def visit_AnnAssign(self, node):
        self._check_target(node.target)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node):
        self._check_target(node.target)
        self.visit(node.value)

    # expressions -------------------------------------------------------------
    def _comprehension(self, node):
        self._refuse(node, "uses a comprehension (for … in …)", _HINT_LOOP)

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension

    def visit_Lambda(self, node):
        self._refuse(node, "has a lambda inside it", "call a named function instead.")

    def visit_Yield(self, node):
        self._refuse(node, "uses yield", "a formula returns one value.")

    visit_YieldFrom = visit_Yield

    def visit_Await(self, node):
        self._refuse(node, "uses await", "a formula returns one value, now.")

    def visit_NamedExpr(self, node):
        self._refuse(node, "uses :=", "assign on its own line inside a def.")

    def visit_Name(self, node):
        if node.id in self.local or not isinstance(node.ctx, ast.Load):
            return
        value = self.ctx.get(node.id, _MISSING)
        if value is _MISSING:
            value = getattr(builtins, node.id, _MISSING)
        if value is not _MISSING and _is_group_operator(value):
            self._refuse(
                node, "reads a group",
                "group membership is not a formula source. Count or scan the group in "
                "update(), or use a group formula (group['all'] @= lambda: …).",
            )

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name) \
                and node.value.id not in self.local:
            held = self.ctx.get(node.value.id, _MISSING)
            if held is _MISSING:
                held = getattr(builtins, node.value.id, _MISSING)
            from .state import State
            if isinstance(held, State):
                cell = held.__dict__.get("_data", {}).get(node.attr)
                if cell is not None and isinstance(cell.__dict__.get("_raw_value"),
                                                   (list, dict, set)):
                    self.containers.add((held._name, node.attr,
                                         type(cell.__dict__["_raw_value"]).__name__))
        self.generic_visit(node)

    def visit_Subscript(self, node):
        key = _constant_key(node.slice)
        if isinstance(key, str) and isinstance(node.ctx, ast.Load):
            self._refuse_handle_as_value(node, key)
        if key is _MISSING:
            coll, _is_local = _resolve_chain(node.value, self.ctx, self.local)
            if coll is not _MISSING and _holds_scena_objects(coll):
                self._refuse(
                    node, "picks a Scena object with a changing index",
                    "the link only sees the collection, not which item is read. "
                    "Name the object directly, or choose it in update().",
                )
        self.generic_visit(node)

    def _refuse_handle_as_value(self, node: ast.Subscript, key: str) -> None:
        """``lambda: f"{st['score']}"``: inside a formula the bracket gives the
        handle, not the number, so the formula would show its repr, compare
        False, or raise a bare TypeError each time it runs. Refused at link time,
        with the line; the handle's own dunders catch what is never parsed
        (``@when`` lambdas, the REPL). ``st["x"].value`` is refused too: the
        reader follows ``.value`` to the number and finds no source, and the
        dot is the one spelling inside a formula."""
        value, _is_local = _resolve_chain(node, self.ctx, self.local)
        from .state import FieldRef, FIELD_REF_USES
        if not isinstance(value, FieldRef):
            return
        bracket = ast.unparse(node)
        base = ast.unparse(node.value)
        dot = f"{base}.{key}" if key.isidentifier() else f"{bracket}.value"
        line = getattr(node, "lineno", None)
        where = f" (line {line})" if line else ""
        raise TypeError(
            f"formula {_label(self.fn)}{where} reads {bracket}: inside a formula "
            f"the brackets give the field itself (the handle), not its value, "
            f"so the formula would get the handle each time it runs. Write "
            f"{dot}: the lambda already keeps it live (Scena reads its code and "
            f"follows {dot}). {FIELD_REF_USES}"
        )

    def visit_Call(self, node):
        self._check_callee(node)
        self.generic_visit(node)

    # calls -----------------------------------------------------------------
    def _check_callee(self, call: ast.Call) -> None:
        func = call.func
        if isinstance(func, ast.Name):
            if func.id in self.local:
                self._refuse(call, f"calls {func.id}, a local value", _HINT_CALL)
            value = self.ctx.get(func.id, _MISSING)
            if value is _MISSING:
                value = getattr(builtins, func.id, _MISSING)
            if value is _MISSING:
                return  # NameError at evaluation — not our job
            self._check_callable(call, value, func.id)
            return
        if isinstance(func, ast.Attribute):
            receiver, is_local = _resolve_chain(func.value, self.ctx, self.local)
            if receiver is _MISSING:
                # Method on a local value (a string, a Point read into a local),
                # or a chain the extractor will report.
                return
            if isinstance(receiver, types.ModuleType):
                value = getattr(receiver, func.attr, _MISSING)
                if value is not _MISSING:
                    self._check_callable(call, value, f"{receiver.__name__}.{func.attr}")
                return
            if _is_group_operator(receiver):
                self._refuse(
                    call, "reads a group",
                    "group membership is not a formula source. Count or scan the group "
                    "in update(), or use a group formula.",
                )
            method = getattr(receiver, func.attr, _MISSING)
            if method is _MISSING:
                return
            if _is_scena_object(receiver) or type(receiver).__module__ == "builtins":
                # Scena methods read their receiver (already a source). Author
                # methods on a Scena subclass may read more — follow them.
                if self._is_author_code(method):
                    self._follow(call, method)
                return
            self._check_callable(call, method, func.attr)
            return
        self._refuse(call, "calls a value computed while it runs", _HINT_CALL)

    def _is_author_code(self, value: Any) -> bool:
        func = _unwrap_function(value)
        return (
            isinstance(func, types.FunctionType)
            and self.root_globals is not None
            and func.__globals__ is self.root_globals
        )

    def _check_callable(self, call: ast.Call, value: Any, name: str) -> None:
        if value is getattr(builtins, name.split(".")[-1], None) and name in _DENIED_BUILTINS:
            if name == "getattr" and call.args:
                # ``getattr(shape, side)``: the object itself is a source, so
                # any field read from it is covered.
                target, _is_local = _resolve_chain(call.args[0], self.ctx, self.local)
                if target is not _MISSING and _is_scena_object(target):
                    return
            self._refuse(call, f"calls {name}", "name the object and field directly.")
        if isinstance(value, (types.BuiltinFunctionType, types.BuiltinMethodType)):
            return  # C code: sees only its arguments (visited here)
        if isinstance(value, type):
            mod = _module_of(value)
            if mod == "builtins" or is_framework_module(mod) or mod.split(".")[0] in _STDLIB:
                return
            self._refuse(call, f"creates a {value.__name__}", _HINT_CALL)
        if _is_scena_callable(value) or _is_scena_object(value):
            return
        if self._is_author_code(value):
            self._follow(call, value)
            return
        func = _unwrap_function(value)
        mod = _module_of(func)
        if isinstance(func, types.FunctionType) and mod.split(".")[0] in _STDLIB:
            return
        self._refuse(call, f"calls {name}" + (f" from {mod}" if mod else ""), _HINT_CALL)

    def _follow(self, call: ast.Call, value: Any) -> None:
        func = _unwrap_function(value)
        code = func.__code__
        if code in self.seen:
            return  # recursion: already being read
        if self.depth >= _MAX_HELPER_DEPTH:
            _refuse(
                self.fn, call,
                f"calls helpers more than {_MAX_HELPER_DEPTH} levels deep",
                "flatten the helpers so Scena can read them.",
            )
        node = locate_formula_node(value)
        if node is None or not isinstance(node, (ast.FunctionDef, ast.Lambda)):
            _refuse(self.fn, call, f"calls {func.__name__}(), whose source Scena cannot read",
                    "define it in the script file.")
        ctx = formula_context(value)
        local = formula_locals(node, ctx, params_resolved=False)
        if getattr(value, "__self__", None) is not None:
            # Bound method: the receiver resolves; the rest are call arguments.
            first = code.co_varnames[:1]
            local.difference_update(first)
        part = FormulaPart(value, node, ctx, local)
        self.parts.append(part)
        self.seen.add(code)
        _Checker(self.root_fn, value, node, ctx, local, self.depth + 1, self.seen, self.parts,
                 self.containers).run()


def check_formula(fn: Callable[..., Any], node: ast.AST) -> List[FormulaPart]:
    """Refuse hidden reads; return the formula plus every helper it calls.

    ``node`` is the formula's ``ast.Lambda`` / ``ast.FunctionDef``. Raises
    ``TypeError`` naming the construct the static pass cannot see through.
    """
    ctx = formula_context(fn)
    local = formula_locals(node, ctx, params_resolved=True)
    root = FormulaPart(fn, node, ctx, local)
    parts: List[FormulaPart] = [root]
    seen: Set[types.CodeType] = {_unwrap_function(fn).__code__}
    checker = _Checker(fn, fn, node, ctx, local, 0, seen, parts)
    checker.run()
    for state, cell, kind in sorted(checker.containers):
        _warn_container_read(fn, state, cell, kind)
    return parts


def _warn_container_read(fn, state: str, cell: str, kind: str) -> None:
    """A formula reads inside a list / dict / set a cell holds: an in-place
    change writes nothing to the cell, so the formula keeps its old value
    (persona probes PP: a HUD over ``st.inv["gemas"] += 1``)."""
    from .process import report_author_warning
    name = f"{state}.{cell}"
    whole = (f'{name} = {{**{name}, "chave": valor}}' if kind == "dict"
             else f"{name} = {name} + [x]" if kind == "list" else f"{name} = {name} | {{x}}")
    report_author_warning(
        "@=",
        f"formula {_label(fn)} reads inside {name} (a {kind}). A change made in "
        f"place ({name}[…] = …, {name}[…] += 1, .append, .pop) does not reach it, "
        f"so it keeps showing the old value. Write the whole value ({whole}; "
        f"{name} += [x] also tells it), or keep each number in a cell of its own "
        f"({state}.gemas).",
    )
