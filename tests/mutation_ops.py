"""Mutation operators and the import hook for ``tests/mutation_run.py``.

Not a test module. A *site* is one place in a module's AST where one operator
applies; sites are enumerated in a fixed order, so ``(module, index)`` names a
mutant across processes. Operators (classic, small, mostly non-equivalent):

  cmp     < <-> <=, > <-> >=, == <-> !=, is <-> is not, in <-> not in
  binop   + <-> -, * <-> /  (also augmented assignment)
  bool    and <-> or
  not     `not x` -> `x`
  if      `if c:` -> `if not c:` (also while / ternary tests)
  const   int n -> n + 1, float f -> f + 1.0, True <-> False
  return  `return <expr>` -> `return None`
  call    a bare call statement `f(...)` -> `pass`
"""
from __future__ import annotations

import ast
import copy
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

_CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
        ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
        ast.In: ast.NotIn, ast.NotIn: ast.In}
_BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}


@dataclass(frozen=True)
class Site:
    index: int
    line: int
    op: str
    detail: str


def _is_docstring(node, parent) -> bool:
    return (isinstance(parent, ast.Expr) and isinstance(node, ast.Constant)
            and isinstance(node.value, str))


def _walk(tree: ast.AST):
    """Deterministic pre-order walk yielding (node, parent)."""
    stack = [(tree, None)]
    while stack:
        node, parent = stack.pop()
        yield node, parent
        children = list(ast.iter_child_nodes(node))
        for c in reversed(children):
            stack.append((c, node))


def _candidates(node, parent) -> List[Tuple[str, str]]:
    out = []
    if isinstance(node, ast.Compare):
        for i, o in enumerate(node.ops):
            if type(o) in _CMP:
                out.append(("cmp", f"{i}:{type(o).__name__}->{_CMP[type(o)].__name__}"))
    elif isinstance(node, (ast.BinOp, ast.AugAssign)) and type(node.op) in _BIN:
        out.append(("binop", f"{type(node.op).__name__}->{_BIN[type(node.op)].__name__}"))
    elif isinstance(node, ast.BoolOp):
        out.append(("bool", "and<->or"))
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        out.append(("not", "drop not"))
    elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
        out.append(("if", "negate test"))
    elif isinstance(node, ast.Constant) and not _is_docstring(node, parent):
        v = node.value
        if isinstance(v, bool):
            out.append(("const", f"{v}->{not v}"))
        elif isinstance(v, int):
            out.append(("const", f"{v}->{v + 1}"))
        elif isinstance(v, float):
            out.append(("const", f"{v}->{v + 1.0}"))
    elif isinstance(node, ast.Return) and node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None):
        out.append(("return", "-> None"))
    elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        out.append(("call", "-> pass"))
    return out


def sites(source: str) -> List[Site]:
    tree = ast.parse(source)
    out = []
    for node, parent in _walk(tree):
        for op, detail in _candidates(node, parent):
            out.append(Site(len(out), getattr(node, "lineno", 0), op, detail))
    return out


def mutate(source: str, index: int) -> Tuple[ast.Module, Site]:
    tree = ast.parse(source)
    k = 0
    for node, parent in _walk(tree):
        for op, detail in _candidates(node, parent):
            if k == index:
                site = Site(index, getattr(node, "lineno", 0), op, detail)
                _apply(node, parent, op, detail)
                ast.fix_missing_locations(tree)
                return tree, site
            k += 1
    raise IndexError(f"no mutation site {index}")


def _apply(node, parent, op: str, detail: str) -> None:
    if op == "cmp":
        i = int(detail.split(":")[0])
        node.ops[i] = _CMP[type(node.ops[i])]()
    elif op == "binop":
        node.op = _BIN[type(node.op)]()
    elif op == "bool":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif op == "not":
        # `not x` -> `not not x` (== bool(x)): the node stays where it is.
        node.operand = ast.UnaryOp(op=ast.Not(), operand=node.operand)
    elif op == "if":
        node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
    elif op == "const":
        v = node.value
        node.value = (not v) if isinstance(v, bool) else (v + 1 if isinstance(v, int) else v + 1.0)
    elif op == "return":
        node.value = ast.Constant(value=None)
    elif op == "call":
        node.value = ast.Constant(value=None)      # an expression statement doing nothing


class _MutantLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, fullname, path, index):
        super().__init__(fullname, path)
        self.index = index

    def get_code(self, fullname):
        with open(self.path, encoding="utf-8") as fh:
            src = fh.read()
        tree, _site = mutate(src, self.index)
        return compile(tree, self.path, "exec", dont_inherit=True)


class _MutantFinder(importlib.abc.MetaPathFinder):
    def __init__(self, module: str, index: int):
        self.module = module
        self.index = index

    def find_spec(self, fullname, path, target=None):
        if fullname != self.module:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None and spec.origin and spec.origin.endswith(".py"):
                spec.loader = _MutantLoader(fullname, spec.origin, self.index)
                return spec
        return None


def install(spec: str) -> None:
    module, index = spec.rsplit(":", 1)
    sys.meta_path.insert(0, _MutantFinder(module, int(index)))


def describe(module_path: str, index: int) -> Optional[Site]:
    with open(module_path, encoding="utf-8") as fh:
        src = fh.read()
    for s in sites(src):
        if s.index == index:
            return s
    return None
