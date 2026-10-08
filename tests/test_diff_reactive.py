"""Differential tests: reactive fast paths vs their reference paths.

Pairs covered (fast/slow inventory, Testing Design — Strategy):

* **Graph registration** — lazy Container registration (#23) and the GC
  backstop (weak nodes + finalizers) vs eager registration with strong
  nodes. Only graph *size* may differ.
* **Clean linked reads** — ``ScalarSlot`` / ``_bare_attr`` cached "bare ok"
  reads (#5, #6) vs a read after ``_invalidate_bare_reads()`` (the full
  ``_refresh_scalar`` / ``.value`` path).
* **A2 skip-invalidate / change-gated notify / cached subtree** (#19–22) are
  exercised by the same programs (unlinked writes, relinks, unlink).

One generated author program — writes, ``@=`` links (Attribute, Entity ink,
Circle ``radius``, Rect ``width``, Point ``x``), unlinks, ``@on_change``
watches, flushes — runs once per configuration. Everything runs inside a
frame batch so ``@on_change`` fires only at ``flush()`` (outside a batch the
eager poll legitimately differs between configurations). The traces (every
read, every outcome, every fire) must be identical.

* **Owner-indexed cancel** (#24) — ``Scheduler._by_owner`` and
  ``EventSystem._by_owner`` vs a linear scan of every live handle /
  registration, after random timer / cancel / destroy / tick sequences.

    python -m unittest tests.test_diff_reactive -v
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import assert_same  # noqa: E402
from hypothesis_support import quiet, reset_globals  # noqa: E402
from hypothesis import given, note, strategies as hst  # noqa: E402

from scena import Circle, Entity, Point, Rect, clock, on_change  # noqa: E402
from scena.process import get_scheduler, reset_process_scheduler, tick_processes  # noqa: E402
from scena.state import (  # noqa: E402
    Attribute, get_scena_system, init_scena_system, set_graph_gc_backstop,
    set_lazy_container_registration,
)

KINDS = ("attr", "ink", "radius", "width", "px")
MAGNITUDE = {"radius", "width"}


class _Node:
    def __init__(self, kind, value, owned):
        self.kind = kind
        if kind == "attr":
            self.obj = Attribute(value)
        elif kind == "ink":
            self.obj = Entity()
            self.obj.v = value
        elif kind == "radius":
            self.obj = Circle(center=(0, 0), radius=value)
        elif kind == "width":
            self.obj = Rect(center=(0, 0), width=value, height=4)
        else:
            self.obj = Point(value, 0)
        owned.append(self.obj)

    @property
    def field(self):
        return {"attr": None, "ink": "v", "radius": "radius", "width": "width", "px": "x"}[self.kind]

    def get(self, slow):
        if slow and self.kind != "attr":
            self.obj._invalidate_bare_reads()
        if self.kind == "attr":
            return self.obj.value
        return float(getattr(self.obj, self.field)) if self.kind != "ink" else self.obj.v

    def set(self, value):
        if self.kind == "attr":
            self.obj.value = value
        else:
            setattr(self.obj, self.field, value)

    def link(self, fn):
        if self.kind == "attr":
            self.obj @= fn
        else:
            self.obj[self.field] @= fn

    def unlink(self):
        if self.kind == "attr":
            self.obj.unlink()
        else:
            self.obj[self.field].unlink()

    def reader(self):
        """Zero-arg read that names the Container (default-arg capture)."""
        o, f = self.obj, self.field
        if self.kind == "attr":
            return lambda o=o: o.value
        if self.kind == "ink":
            return lambda o=o: o.v
        if self.kind == "radius":
            return lambda o=o: o.radius
        if self.kind == "width":
            return lambda o=o: o.width
        return lambda o=o: o.x


def _formula(k, c, src):
    """``k + c·source``, capturing the Container itself as a default arg.

    Scena finds formula sources by inspection; a source hidden behind another
    lambda is not found and ``@=`` raises TypeError (no silent freeze).
    """
    o = src.obj
    if src.kind == "attr":
        return lambda o=o, k=k, c=c: k + c * o.value
    if src.kind == "ink":
        return lambda o=o, k=k, c=c: k + c * o.v
    if src.kind == "radius":
        return lambda o=o, k=k, c=c: k + c * o.radius
    if src.kind == "width":
        return lambda o=o, k=k, c=c: k + c * o.width
    return lambda o=o, k=k, c=c: k + c * o.x


value = hst.integers(0, 40)
PROGRAM = hst.lists(hst.one_of(
    hst.tuples(hst.just("write"), hst.integers(0, 5), value),
    hst.tuples(hst.just("link"), hst.integers(0, 5), hst.integers(0, 5),
               hst.integers(-2, 3), hst.integers(0, 10)),
    hst.tuples(hst.just("unlink"), hst.integers(0, 5)),
    hst.tuples(hst.just("watch"), hst.integers(0, 5)),
    hst.tuples(hst.just("read"), hst.integers(0, 5)),
    # link → write the source → read the target: the order that exposes a
    # write that skipped invalidation (random programs rarely line it up).
    hst.tuples(hst.just("chain"), hst.integers(0, 5), hst.integers(0, 5),
               hst.integers(1, 3), hst.integers(0, 10), value),
    hst.tuples(hst.just("flush")),
), min_size=1, max_size=20)


def run_program(kinds, program, *, slow: bool) -> list:
    """Execute ``program`` on fresh nodes; return the observable trace."""
    trace = []
    owned = []
    ss = get_scena_system()
    ss.begin_frame_batch()
    try:
        with quiet():
            nodes = [_Node(k, 10 + i, owned) for i, k in enumerate(kinds)]
        links = {}      # target index -> source index (model for cycle skip)
        formula = {}    # target index -> (source, c, k)
        stored = [10 + i for i in range(len(nodes))]   # model: unlinked values

        def model(i):
            if i in formula:
                src, c, k = formula[i]
                v = k + c * model(src)
                return max(0, v) if nodes[i].kind in MAGNITUDE else v
            return stored[i]

        def reaches(start, goal):
            seen, stack = set(), [start]
            while stack:
                n = stack.pop()
                if n == goal:
                    return True
                if n in seen:
                    continue
                seen.add(n)
                if n in links:
                    stack.append(links[n])
            return False

        def outcome(fn):
            try:
                with quiet():
                    return ("ok", fn())
            except Exception as exc:  # noqa: BLE001
                return ("raise", type(exc).__name__)

        for step, op in enumerate(program):
            kind = op[0]
            n = len(nodes)
            if kind == "write":
                i = op[1] % n
                res = outcome(lambda: nodes[i].set(op[2]))
                trace.append((step, "write", res))
                if res[0] == "ok":
                    stored[i] = op[2]
            elif kind == "link":
                t, s = op[1] % n, op[2] % n
                if t == s or reaches(s, t):
                    continue  # cycles are ReactiveLinksMachine's job
                fn = _formula(op[4], op[3], nodes[s])
                res = outcome(lambda: nodes[t].link(fn))
                trace.append((step, "link", res))
                if res[0] == "ok":
                    links[t] = s
                    formula[t] = (s, op[3], op[4])
            elif kind == "unlink":
                t = op[1] % n
                if t in links:
                    frozen = model(t)
                    trace.append((step, "unlink", outcome(nodes[t].unlink)))
                    links.pop(t, None)
                    formula.pop(t, None)
                    stored[t] = frozen
            elif kind == "watch":
                i = op[1] % n
                r = nodes[i].reader()

                def cb(v, i=i, step=step):
                    trace.append(("fire", step, i, float(v)))
                trace.append((step, "watch", outcome(lambda: on_change(r)(cb) and None)))
            elif kind == "chain":
                t, src = op[1] % n, op[2] % n
                if t == src or reaches(src, t) or t in links:
                    continue
                fn = _formula(op[4], op[3], nodes[src])
                res = outcome(lambda: nodes[t].link(fn))
                trace.append((step, "chain-link", res))
                if res[0] != "ok":
                    continue
                links[t] = src
                formula[t] = (src, op[3], op[4])
                if src not in links:
                    res = outcome(lambda: nodes[src].set(op[5]))
                    trace.append((step, "chain-write", res))
                    if res[0] == "ok":
                        stored[src] = op[5]
                trace.append((step, "chain-read", outcome(lambda: nodes[t].get(slow)),
                              ("model", model(t))))
            elif kind == "read":
                i = op[1] % n
                trace.append((step, "read", outcome(lambda: nodes[i].get(slow))))
            else:
                ss.flush()
        ss.flush()
        trace.append(("final", [outcome(lambda nd=nd: nd.get(slow)) for nd in nodes]))
        trace.append(("model", [("ok", model(i)) for i in range(len(nodes))]))
        return trace
    finally:
        ss.end_frame_batch()
        reset_globals()
        for o in owned:
            try:
                if hasattr(o, "destroy"):
                    o.destroy()
            except Exception:
                pass


class TestReactiveConfigsAgree(unittest.TestCase):
    """Lazy + GC backstop + cached bare reads ≡ eager + strong + uncached reads."""

    def _run_slow(self, kinds, program):
        set_lazy_container_registration(False)
        set_graph_gc_backstop(False)
        init_scena_system()
        try:
            return run_program(kinds, program, slow=True)
        finally:
            set_lazy_container_registration(True)
            set_graph_gc_backstop(True)
            init_scena_system()

    def test_programs_are_not_vacuous(self):
        # Guard: if links stopped installing (e.g. formula sources no longer
        # detected) the differential would compare two unlinked runs.
        prog = [("link", 1, 0, 2, 3), ("write", 0, 7), ("read", 1),
                ("link", 2, 1, 1, 0), ("write", 0, 9), ("read", 2)]
        for kinds in (["attr", "ink", "radius"], ["px", "width", "radius"]):
            with self.subTest(kinds=kinds):
                init_scena_system()
                trace = run_program(kinds, prog, slow=False)
                links = [e[2] for e in trace if len(e) > 2 and e[1] == "link"]
                self.assertEqual(links, [("ok", None), ("ok", None)])
                reads = [e[2] for e in trace if len(e) > 2 and e[1] == "read"]
                self.assertEqual([float(r[1]) for r in reads], [17.0, 21.0])

    @given(kinds=hst.lists(hst.sampled_from(KINDS), min_size=2, max_size=6), program=PROGRAM)
    def test_same_trace(self, kinds, program):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            init_scena_system()
            fast = run_program(kinds, program, slow=False)
            slow = self._run_slow(kinds, program)
        note(f"fast trace: {fast}")
        assert_same(self, fast, slow, "the same author program")
        assert_same(self, fast[-2][1], fast[-1][1], "final values vs the link model")
        for entry in fast:
            if len(entry) == 4 and entry[1] == "chain-read" and entry[2][0] == "ok":
                assert_same(self, entry[2][1], entry[3][1], f"read right after a chain (step {entry[0]})")


class TestReactiveCanaries(unittest.TestCase):
    def test_skipped_pull_invalidation_is_caught(self):
        # Every configuration shares _requires_pull_invalidate, so only the
        # model check can see this one: stale derived reads.
        from diff_support import assert_catches
        from scena.state import Container
        assert_catches(self, "test_diff_reactive.TestReactiveConfigsAgree.test_same_trace",
                       [(Container, "_requires_pull_invalidate", lambda self: False)],
                       "writes that skip pull invalidation")


# ---------------------------------------------------------------------------
# Owner-indexed cancel (#24)
# ---------------------------------------------------------------------------

OWNER_OPS = hst.lists(hst.one_of(
    hst.tuples(hst.just("after"), hst.integers(0, 3), hst.sampled_from([0.05, 0.2, 1.0])),
    hst.tuples(hst.just("every"), hst.integers(0, 3), hst.sampled_from([0.05, 0.2])),
    hst.tuples(hst.just("tween"), hst.integers(0, 3)),
    hst.tuples(hst.just("when"), hst.integers(0, 3)),
    hst.tuples(hst.just("cancel_one"), hst.integers(0, 50)),
    hst.tuples(hst.just("cancel_process"), hst.integers(0, 3)),
    hst.tuples(hst.just("destroy"), hst.integers(0, 3)),
    hst.tuples(hst.just("tick"), hst.sampled_from([0.05, 0.1, 0.5])),
), max_size=25)


from scena import when as _when  # noqa: E402


class _Watcher(Entity):
    def setup(self):
        self.hp = 1  # method watches arm after setup()

    @_when(lambda self: self.hp < 0)
    def low(self):
        pass


class TestOwnerIndexMatchesScan(unittest.TestCase):
    """``_by_owner`` indexes ≡ a linear scan of every live handle / registration."""

    def setUp(self):
        reset_process_scheduler()
        reset_globals()

    def tearDown(self):
        reset_process_scheduler()
        reset_globals()

    def _check(self, what):
        sch = get_scheduler()
        live = [h for h in sch._handles if not (h.cancelled or h.done)]
        scan = {}
        for h in live:
            if h.owner is not None:
                scan.setdefault(id(h.owner), set()).add(h)
        index = {k: {h for h in v if not (h.cancelled or h.done)}
                 for k, v in sch._by_owner.items()}
        index = {k: v for k, v in index.items() if v}
        self.assertEqual(index, scan, f"scheduler owner index vs scan after {what}")
        from scena.events import get_global_event_system
        es = get_global_event_system()
        escan = {}
        for r in es._events:
            if not r._drop and r._owner is not None:
                escan.setdefault(id(r._owner), set()).add(r)
        eindex = {k: {r for r in v if not r._drop} for k, v in es._by_owner.items()}
        eindex = {k: v for k, v in eindex.items() if v}
        self.assertEqual(eindex, escan, f"event owner index vs scan after {what}")

    @given(ops=OWNER_OPS)
    def test_index_equals_scan(self, ops):
        reset_process_scheduler()
        reset_globals()
        ents = []
        with quiet():
            for _ in range(4):
                ents.append(_Watcher())
        handles = []
        try:
            for i, op in enumerate(ops):
                kind = op[0]
                with quiet():
                    if kind in ("after", "every", "tween", "when", "cancel_process", "destroy"):
                        e = ents[op[1]]
                        if not e.is_alive:
                            continue
                        if kind == "after":
                            handles.append(e.after(op[2], lambda: None))
                        elif kind == "every":
                            handles.append(e.every(op[2], lambda: None))
                        elif kind == "tween":
                            handles.append(e.tween(e["hp"], 5, time=0.3))
                        elif kind == "when":
                            e.hp = -1 if e.hp >= 0 else 1
                        elif kind == "cancel_process":
                            e.cancel_process()
                        else:
                            e.destroy()
                    elif kind == "cancel_one":
                        if handles:
                            handles[op[1] % len(handles)].cancel()
                    else:
                        clock.advance(op[1])
                        tick_processes()
                self._check(f"step {i} {op}")
                for e in ents:
                    if not e.is_alive or kind == "cancel_process":
                        owned = [h for h in get_scheduler()._handles
                                 if h.owner is e and not (h.cancelled or h.done)]
                        if not e.is_alive:
                            self.assertEqual(owned, [], f"dead owner keeps live handles after {op}")
        finally:
            handles.clear()
            for e in ents:
                if e.is_alive:
                    e.destroy()


if __name__ == "__main__":
    unittest.main()
