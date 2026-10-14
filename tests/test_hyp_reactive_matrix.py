"""Random programs over linked fields of any reactive class (Hypothesis).

A pool of subjects (``reactive_matrix_support.SUBJECTS``), each with a twin that
only ever gets plain writes. Rules link a field to a cell, move the cell
(the twin gets every linked value written again until they all hold, the
heading last), unlink, and read some names on both sides at the same moment. Whatever the order, a read on the subject must equal
the twin's. The deterministic cross-product is ``test_reactive_matrix``; this
machine reaches orders it does not (several links on one object, a link
installed after reads, unlink then relink).

    python tests/run_tiers.py focused test_hyp_reactive_matrix
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

import hypothesis.strategies as hst  # noqa: E402
from hypothesis import assume  # noqa: E402
from hypothesis.stateful import RuleBasedStateMachine, rule, run_state_machine_as_test  # noqa: E402

import reactive_matrix_support as M  # noqa: E402
from scena import State  # noqa: E402

_FIELDS = {}     # label -> [(name, is_pair, slot)]   every readable name
_LINKABLE = {}   # label -> [(name, is_pair, slot)]   names the model lets a link drive

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def fields_of(label, factory):
    if label not in _FIELDS:
        probe = factory()
        _FIELDS[label] = [(n, p, getattr(type(probe), n, None))
                          for n, p in M.field_names(probe)]
    return _FIELDS[label]


def linkable_of(label, factory):
    """Defining fields: a throwaway instance accepts a link on them."""
    if label not in _LINKABLE:
        out = []
        for name, is_pair, slot in fields_of(label, factory):
            try:
                fn = formula(_PROBE_CELL, name, slot, is_pair)
                if name == "@self":
                    continue
                factory()[name] @= fn
            except Exception:
                continue
            out.append((name, is_pair, slot))
        if label in ("Vec2", "Point"):
            out.append(("@self", True, None))     # ``v @= lambda: (x, y)``: the whole vector
        _LINKABLE[label] = out
    return _LINKABLE[label]


def coeffs(name, slot, is_pair):
    """A cell t in 0..1 -> a value this field accepts under ``=``, as
    ((a, b), (c, d)): first = a*t + b, second = c*t + d (pairs only)."""
    if is_pair:
        # A different offset per field: two points on one formula coincide, and a
        # zero-length spine / line has no heading to compare.
        off = float(sum(map(ord, name)) % 13)
        return (40.0, -20.0 + off), (20.0, -7.0 + 2.0 * off)
    if name == "angle":
        return (360.0, -180.0), None
    if name == "spread":
        return (360.0, 0.0), None
    if name in ("begin", "end", "u"):
        return (1.0, 0.0), None
    if name == "base_ratio":                  # Triangle: 0 < base_ratio < 2
        return (0.8, 0.6), None
    if getattr(slot, "magnitude", False):
        return (49.0, 1.0), None
    return (40.0, -20.0), None


def map_value(name, slot, is_pair, t):
    (a, b), second = coeffs(name, slot, is_pair)
    if second is None:
        return a * t + b
    return (a * t + b, second[0] * t + second[1])


def formula(cell, name, slot, is_pair):
    """A closure over the cell: the formula checker reads the lambda's source,
    so it may not call helpers (``getattr``, ``map_value``); it names the cell
    and uses plain arithmetic on captured numbers."""
    (a, b), second = coeffs(name, slot, is_pair)
    if second is None:
        return lambda: a * cell.v + b
    c, d = second
    return lambda: (a * cell.v + b, c * cell.v + d)


_PROBE_CELL = State(name="hm_probe")
_PROBE_CELL.v = 0.5


def _put(obj, name, is_pair, v):
    if name == "@self":
        obj << v
    elif is_pair:
        getattr(obj, name)._takein(v)
    else:
        setattr(obj, name, v)


class _Pair:
    def __init__(self, label, factory):
        self.label = label
        self.subject = factory()
        self.twin = factory()
        self.fields = fields_of(label, factory)
        self.linkable = linkable_of(label, factory)
        self.links = {}     # field name -> (cell, whole); install order

    def settle_twin(self):
        """Write every linked value to the twin as the subject holds them.

        All links hold at once on the subject; the twin gets plain writes, and
        a later write can move a field an earlier one set. So the twin re-puts
        every linked value until a pass changes no linked read. Links that never
        settle cannot all hold, and the engine must refuse the pair: a rim
        Circle's ``angle`` and ``center`` settled nowhere (the radius followed
        whichever center moves had been read) and are refused now
        (``_heading_pivot_inputs``). The heading goes last, as the engine
        applies it: a linked turn reads its pivot through that part's own link
        first (Reactive Design, "A linked heading is pulled before the points
        it rewrites are read")."""
        names = [n for n in self.links if n != "angle"]
        if "angle" in self.links:
            names.append("angle")
        if not names:
            return
        readable = [n for n in names if n != "@self"]
        for _ in range(4):
            before = M.snapshot_names(self.twin, readable)
            for name in names:
                cell, _ = self.links[name]
                _, is_pair, slot = next(x for x in self.linkable if x[0] == name)
                try:
                    _put(self.twin, name, is_pair, map_value(name, slot, is_pair, cell.v))
                except Exception:
                    assume(False)
            if not M.diff(before, M.snapshot_names(self.twin, readable)):
                return
        raise AssertionError(f"{self.label}: links {names} never settle on the written twin")


class ReactiveMatrixMachine(RuleBasedStateMachine):
    # Indexes into SUBJECTS this machine draws from. A canary narrows it to the
    # class its bug lives in: the full pool is too diffuse for 150 examples.
    POOL = tuple(range(len(M.SUBJECTS)))

    def __init__(self):
        super().__init__()
        self.pairs = []
        self.cells = []

    @rule(i=hst.integers(0, 10_000))
    def new_subject(self, i):
        if len(self.pairs) < 6:
            label, factory = M.SUBJECTS[self.POOL[i % len(self.POOL)]]
            self.pairs.append(_Pair(label, factory))

    @rule(t=hst.floats(0.0, 1.0))
    def new_cell(self, t):
        if len(self.cells) < 4:
            st = State(name=f"hm{id(self)}_{len(self.cells)}")
            st.v = t
            self.cells.append(st)

    @rule(i=hst.integers(0, 10_000), f=hst.integers(0, 40), t=hst.floats(0.0, 1.0),
          whole=hst.booleans())
    def new_subject_linked(self, i, f, t, whole):
        """Subject, cell and link in one step: most random programs would
        otherwise spend their budget before reaching a link."""
        assume(len(self.pairs) < 6 and len(self.cells) < 4)
        self.new_subject(i)
        self.new_cell(t)
        self.link(len(self.pairs) - 1, f, len(self.cells) - 1, whole)

    @rule(p=hst.integers(0, 5), f=hst.integers(0, 40), c=hst.integers(0, 3),
          whole=hst.booleans())
    def link(self, p, f, c, whole):
        assume(self.pairs and self.cells)
        pair = self.pairs[p % len(self.pairs)]
        assume(pair.linkable)
        name, is_pair, slot = pair.linkable[f % len(pair.linkable)]
        cell = self.cells[c % len(self.cells)]
        assume(name not in pair.links)
        value = map_value(name, slot, is_pair, cell.v)
        fn = formula(cell, name, slot, is_pair)
        try:
            if name == "@self":
                pair.subject @= fn
            elif whole and is_pair:
                part = getattr(pair.subject, name)
                part @= fn
            else:
                pair.subject[name] @= fn
        except Exception:
            return            # the model refuses this link (Derivate, competing driver)
        pair.links[name] = (cell, whole and is_pair)
        try:
            _put(pair.twin, name, is_pair, value)
        except Exception:
            assume(False)
        pair.settle_twin()

    @rule(c=hst.integers(0, 3), t=hst.floats(0.0, 1.0))
    def move_cell(self, c, t):
        assume(self.cells)
        cell = self.cells[c % len(self.cells)]
        cell.v = t
        for pair in self.pairs:
            if any(src is cell for src, _ in pair.links.values()):
                pair.settle_twin()

    @rule(p=hst.integers(0, 5), f=hst.integers(0, 40))
    def unlink(self, p, f):
        assume(self.pairs)
        pair = self.pairs[p % len(self.pairs)]
        linked = sorted(pair.links)
        assume(linked)
        name = linked[f % len(linked)]
        _, whole = pair.links.pop(name)
        if name == "@self":
            pair.subject.unlink()
        else:
            (getattr(pair.subject, name) if whole else pair.subject[name]).unlink()

    @rule(p=hst.integers(0, 5), picks=hst.lists(hst.integers(0, 60), min_size=1, max_size=6))
    def read(self, p, picks):
        assume(self.pairs)
        pair = self.pairs[p % len(self.pairs)]
        names = [pair.fields[k % len(pair.fields)][0] for k in picks]
        # The same names, the same order, on both sides (a Rect names its
        # corners at first use).
        a = M.snapshot_names(pair.subject, names)
        b = M.snapshot_names(pair.twin, names)
        bad = M.diff(a, b)
        assert not bad, f"{pair.label}: linked vs written {bad} (links {sorted(pair.links)})"

    def teardown(self):
        for pair in self.pairs:
            names = [n for n, _, _ in pair.fields]
            bad = M.diff(M.snapshot_names(pair.subject, names),
                         M.snapshot_names(pair.twin, names))
            assert not bad, f"{pair.label}: at the end, linked vs written {bad}"


class TestReactiveMatrixMachine(unittest.TestCase):
    def test_links_read_like_writes_in_any_order(self):
        run_state_machine_as_test(ReactiveMatrixMachine)

    def test_vec2_stale_length_is_caught(self):
        from diff_support import assert_catches
        from scena import Vec2
        assert_catches(
            self, "test_hyp_reactive_matrix.TestCanaryTarget.test_machine",
            [(Vec2, "_sync_computed", lambda self: None)],
            "a raw store that leaves Vec2 length/angle stale",
            profile=("canary", "canary_wide", "canary_wider"))


class _Vec2Only(ReactiveMatrixMachine):
    POOL = tuple(i for i, (l, _) in enumerate(M.SUBJECTS) if l == "Vec2")


class TestCanaryTarget(unittest.TestCase):
    def test_machine(self):
        run_state_machine_as_test(_Vec2Only)


if __name__ == "__main__":
    unittest.main()
