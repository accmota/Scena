"""A count of graph nodes is taken settled (O1, O9 in Testing Design).

``DependencyGraph.nodes`` is weak and every Container tree is a reference
cycle, so an earlier test's garbage stays in the count until the cyclic GC
runs. A GC pass between a test's baseline and its final read purges those
nodes, and a "did not grow" check fails in some orders only:
``test_reactive_edge_cases.TestFailedLinkInstallsNothing`` read ``15 != 17``
when its module ran alone and passed when its class did (O9), as
``test_change_gated_update`` had (O1) and two geometry-campaign tests after it.
The rule lived in "Harness pitfalls" and was missed each time a test was
written without it, so it is checked here:

* **Static**: every ``len(<…>.nodes)`` / ``len(list(<…>.nodes))`` in a test
  file follows a settle in its function (or an enclosing one):
  ``full_collect()`` / ``settled_graph_size()`` / ``gc_paused()`` /
  ``gc.disable()`` (``tests/graph_support.py``), or a call to a helper of the
  same module that settles; or its class's ``setUp`` settles. One bare
  ``gc.collect()`` is not a settle: GC-backstop finalizers free more on a
  later pass.
* **Dynamic**: ``run_with_collections`` plants garbage that holds graph nodes
  and forces a full collection at each ``assertRaises`` / ``assertEqual``;
  the O9 test passes under it, and O9's original shape fails (canary).
"""
from __future__ import annotations

import ast
import gc
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.graph_support import full_collect, gc_paused, settled_graph_size  # noqa: E402
from tests.source_support import iter_files  # noqa: E402

TEST_DIRS = [os.path.join(ROOT, "tests"), os.path.join(ROOT, "scena_editor", "tests")]

# Calls that settle the graph before a count (by name, with or without a
# module prefix: ``full_collect`` / ``system_support.full_collect``).
_SETTLE_NAMES = frozenset({"full_collect", "settled_graph_size", "gc_paused"})
# A line that reads a raw count on purpose (this module's canary).
_CANARY = "unsettled on purpose (canary)"


def _is_count(node: ast.AST) -> bool:
    """``len(X.nodes)`` or ``len(list(X.nodes))``."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "len" and len(node.args) == 1):
        return False
    arg = node.args[0]
    if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
            and arg.func.id == "list" and len(arg.args) == 1):
        arg = arg.args[0]
    return isinstance(arg, ast.Attribute) and arg.attr == "nodes"


def _callee(call: ast.Call):
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _is_gc_disable(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "disable"
            and isinstance(f.value, ast.Name) and f.value.id == "gc")


def _own_nodes(fn: ast.AST):
    """Nodes of ``fn``'s body, not of functions nested in it."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def _settle_lines(fn: ast.AST, settlers: set):
    for node in _own_nodes(fn):
        if isinstance(node, ast.Call) and (
                _callee(node) in settlers or _is_gc_disable(node)):
            yield node.lineno


def unsettled_counts(source: str, filename: str = "<src>"):
    """``(line, function)`` of every graph count no settle precedes."""
    tree = ast.parse(source, filename)
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    settlers = set(_SETTLE_NAMES)
    while True:     # a helper that calls a settler is a settler
        more = {f.name for f in funcs
                if f.name not in settlers and any(True for _ in _settle_lines(f, settlers))}
        if not more:
            break
        settlers |= more

    parents = {}
    for fn in funcs:
        for child in ast.walk(fn):
            if child is not fn and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parents.setdefault(child, fn)
    set_up = {}     # a method -> its class's setUp, when that settles
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        methods = [m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
        hook = next((m for m in methods if m.name in ("setUp", "asyncSetUp")
                     and any(True for _ in _settle_lines(m, settlers))), None)
        if hook is not None:
            for m in methods:
                if m is not hook:
                    set_up[m] = hook

    out = []
    for fn in funcs:
        for node in _own_nodes(fn):
            if not _is_count(node):
                continue
            chain, f = [], fn
            while f is not None:
                chain.append(f)
                f = parents.get(f)
            if set_up.get(chain[-1]) is not None:
                continue
            if not any(line <= node.lineno for c in chain for line in _settle_lines(c, settlers)):
                out.append((node.lineno, fn.name))
    return sorted(out)


class TestGraphCountsAreSettled(unittest.TestCase):
    def test_every_graph_count_in_the_tests_is_settled(self):
        bad = []
        for root in TEST_DIRS:
            if not os.path.isdir(root):
                continue
            for path in iter_files(root, ".py", recursive=True):
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
                if ".nodes" not in source:
                    continue
                rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                lines = source.splitlines()
                bad += [f"{rel}:{line} in {fn}()" for line, fn in unsettled_counts(source, path)
                        if _CANARY not in lines[line - 1]]
        self.assertEqual(bad, [], "a graph count with no settle before it (call "
                         "tests.graph_support.settled_graph_size() / full_collect() "
                         "first; Testing Design, Harness pitfalls, O9):\n  " + "\n  ".join(bad))

    def test_the_scan_tells_settled_from_unsettled(self):
        """The guard is not vacuous: the O9 shape fails, the fixed shapes pass."""
        flagged = unsettled_counts(
            "def test(self):\n"
            "    before = len(graph.nodes)\n"
            "    self.assertEqual(len(list(g.nodes)), before)\n")
        self.assertEqual([line for line, _ in flagged], [2, 3])
        self.assertEqual(len(unsettled_counts(          # one bare collect is not a settle
            "import gc\n"
            "def test(self):\n"
            "    gc.collect()\n"
            "    before = len(graph.nodes)\n")), 1)
        self.assertEqual(len(unsettled_counts(          # a settle after the read is too late
            "def test(self):\n"
            "    before = len(graph.nodes)\n"
            "    full_collect()\n")), 1)
        for ok in (
            "def test(self):\n    full_collect()\n    n = len(g.nodes)\n",
            "def test(self):\n    with gc_paused():\n        n = len(g.nodes)\n",
            "import gc\ndef test(self):\n    gc.disable()\n    n = len(g.nodes)\n",
            # a module helper that settles, called first; and the helper itself
            "def _count(g):\n    full_collect()\n    return len(g.nodes)\n"
            "def _settle():\n    _count(None)\n"
            "def test(self):\n    _settle()\n    n = len(g.nodes)\n",
            # a nested function under a settled test
            "def test(self):\n    full_collect()\n    def read():\n        return len(g.nodes)\n",
            # a method of a class whose setUp settles
            "class T:\n    def setUp(self):\n        full_collect()\n"
            "    def check(self):\n        return len(g.nodes)\n",
        ):
            with self.subTest(source=ok):
                self.assertEqual(unsettled_counts(ok), [])


class _Garbage:
    """An earlier test's leftovers: a reference cycle that holds graph nodes."""

    def __init__(self, n: int = 8):
        from scena.state import Attribute
        self.cells = []
        for i in range(n):
            a = Attribute(float(i))
            b = Attribute(0.0)
            b @= (lambda a=a: a.value + 1)     # registers both
            float(b)
            self.cells.append((a, b))
        self.me = self                          # unreachable only to the cyclic GC


class TestSettledCountsIgnoreEarlierGarbage(unittest.TestCase):
    """O9's repro, made deterministic: plant garbage that only the cyclic GC
    frees, then force collections inside the test."""

    def _plant(self) -> int:
        full_collect()
        from scena.state import get_scena_system
        graph = get_scena_system().dependency_graph
        before = len(graph.nodes)
        with gc_paused():
            _Garbage()
            planted = len(graph.nodes) - before
        self.addCleanup(full_collect)
        return planted

    def test_planted_garbage_holds_graph_nodes(self):
        """Not vacuous: the garbage is in an unsettled count and leaves at a settle."""
        from scena.state import get_scena_system
        graph = get_scena_system().dependency_graph
        with gc_paused():
            planted = self._plant()
            self.assertGreater(planted, 0)
            raw = len(graph.nodes)
            self.assertEqual(settled_graph_size(), raw - planted)

    def test_failed_link_test_survives_a_collection_mid_test(self):
        from tests import test_reactive_edge_cases as m
        result = run_with_collections(
            m.TestFailedLinkInstallsNothing("test_rejected_formula_leaves_no_cell_and_no_node"),
            self._plant)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.failures + result.errors, [],
                         "the O9 test moved with earlier garbage")

    def test_an_unsettled_count_fails_under_the_harness(self):
        """Canary: O9's original shape (baseline read raw) fails here."""
        class Unsettled(unittest.TestCase):
            def test_count(self):
                from scena.state import get_scena_system
                graph = get_scena_system().dependency_graph
                before = len(graph.nodes)  # unsettled on purpose (canary)
                with self.assertRaises(AttributeError):
                    object().nope
                self.assertEqual(len(graph.nodes), before)  # unsettled on purpose (canary)
        result = run_with_collections(Unsettled("test_count"), self._plant)
        self.assertEqual(len(result.failures), 1, "the harness did not move an unsettled count")


def run_with_collections(test: unittest.TestCase, plant) -> unittest.TestResult:
    """Run ``test`` with an earlier test's garbage pending (``plant()``, the
    cyclic GC off so nothing frees it early) and a full collection forced at
    each ``assertRaises`` / ``assertEqual`` the test calls: what a GC pass that
    lands mid-test does, made deterministic."""
    for name in ("assertRaises", "assertEqual"):
        real = getattr(test, name)

        def collecting(*args, _real=real, **kwargs):
            full_collect()
            return _real(*args, **kwargs)
        setattr(test, name, collecting)
    result = unittest.TestResult()
    with gc_paused():
        plant()
        test.run(result)
    return result

if __name__ == "__main__":
    unittest.main()
