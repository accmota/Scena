"""A field write keeps Python's identity: ``h.f = new`` makes ``h.f`` the new object.

SV13 (Testing Design): an ``st`` cell compared the new value with ``!=`` and
kept the old object when they were equal. ``old = st.skies; st.skies = []``
with ``st.skies`` already empty left ``old is st.skies``, so a crossfade that
appended the new layers and then faded out everything in ``old`` faded out
the layers it had just made. An Entity ink field had the same bug (E7) and was
fixed alone; the cell kept its own copy of the check.

Bug class guarded here: **a write door that keeps the old object when an
equal new one arrives**. Each door (``st.f = …``, ``st.create``, a bound
widget's write, an ink field) runs the same script as a plain Python namespace, for every
mutable kind (empty and not), and must end in the same contents and the same
identities. Immutable values still compare by value: a repeated ``st.n = 3``
re-runs nothing (the no-op saving the check exists for).

Run headless:

    python tests/run_tiers.py focused test_state_write_identity
"""
from __future__ import annotations

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

import scena  # noqa: E402
from scena import Vec2, st  # noqa: E402
from scena.state import bound_cell  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class _AlwaysEqual:
    """An author object whose ``==`` says yes to anything of its kind."""

    def __init__(self):
        self.tag = 0

    def __eq__(self, other):
        return isinstance(other, _AlwaysEqual)

    __hash__ = None

    def __repr__(self):
        return f"_AlwaysEqual({self.tag})"


def _set_x(v):
    v.x = 5


def _set_tag(o):
    o.tag = 7


# (label, make, mutate): ``make()`` returns a fresh object, equal to the last.
KINDS = (
    ("empty list", list, lambda v: v.append(1)),
    ("list", lambda: [5], lambda v: v.append(1)),
    ("empty dict", dict, lambda v: v.__setitem__("k", 1)),
    ("dict", lambda: {"a": 1}, lambda v: v.__setitem__("k", 1)),
    ("empty set", set, lambda v: v.add(1)),
    ("set", lambda: {5}, lambda v: v.add(1)),
    ("bytearray", bytearray, lambda v: v.append(1)),
    ("Vec2", lambda: Vec2(1, 2), _set_x),
    ("object with value ==", _AlwaysEqual, _set_tag),
)


def _snap(v):
    """What an author can see of a value (Vec2 by its axes)."""
    if isinstance(v, Vec2):
        return ("Vec2", v.x, v.y)
    return repr(v)


class _Door:
    """One way to write field ``f``: ``get`` / ``put`` / ``drop``."""

    label = "?"

    def get(self):
        raise NotImplementedError

    def put(self, value):
        raise NotImplementedError

    def drop(self):
        pass


class _Plain(_Door):
    label = "plain Python"

    def __init__(self):
        self.ns = types.SimpleNamespace()

    def get(self):
        return self.ns.f

    def put(self, value):
        self.ns.f = value


class _CellDot(_Door):
    label = "st.f = …"

    def get(self):
        return st.swi_f

    def put(self, value):
        st.swi_f = value

    def drop(self):
        if st.exists("swi_f"):
            st.remove("swi_f")


class _CellCreate(_CellDot):
    label = 'st.create("f", …)'

    def put(self, value):
        st.create("swi_f", value)


class _CellWidget(_CellDot):
    label = "widget write (cell.value = …)"

    def put(self, value):
        if st.exists("swi_f"):
            bound_cell(st["swi_f"]).value = value   # what a bound widget runs
        else:
            st.swi_f = value


class _Ink(_Door):
    label = "ink field"

    def __init__(self):
        self.c = scena.Circle(center=(0, 0), radius=3)

    def get(self):
        return self.c.swi_f

    def put(self, value):
        self.c.swi_f = value

    def drop(self):
        self.c.destroy()


DOORS = (_CellDot, _CellCreate, _CellWidget, _Ink)


def _run(door, make, mutate, *, equal):
    """``f = a; old = f; f = b; mutate(f)``; ``b`` equals ``a`` when ``equal``."""
    first = make()
    door.put(first)
    old = door.get()
    if equal:
        second = make()
    else:
        second = make()
        mutate(second)              # unequal to ``first``
    door.put(second)
    now = door.get()
    mutate(now)
    return (_snap(old), _snap(door.get()), old is door.get(),
            now is door.get())


class TestWriteKeepsIdentity(unittest.TestCase):
    """Every door against plain Python, for every mutable kind."""

    def test_alias_taken_before_the_write(self):
        for equal in (True, False):
            for label, make, mutate in KINDS:
                plain = _run(_Plain(), make, mutate, equal=equal)
                for door_cls in DOORS:
                    door = door_cls()
                    with self.subTest(kind=label, door=door.label, equal=equal):
                        try:
                            got = _run(door, make, mutate, equal=equal)
                        finally:
                            door.drop()
                        self.assertEqual(got, plain)

    def test_the_crossfade(self):
        """The game that found it: fade out what ``old`` held, not the new layers."""
        try:
            st.swi_skies = []
            old = st.swi_skies
            st.swi_skies = []
            st.swi_skies.append("tunnel")
            self.assertEqual(old, [])
            self.assertIsNot(old, st.swi_skies)
        finally:
            st.remove("swi_skies")

    def test_a_new_object_is_stored(self):
        """Not an equal copy kept in its place: the stored object is the new one
        (a Vec2 the cell must copy, one another holder holds, is copied)."""
        for label, make, _mutate in KINDS:
            with self.subTest(kind=label):
                try:
                    st.swi_f = make()
                    second = make()
                    st.swi_f = second
                    self.assertIs(st.swi_f, second)
                finally:
                    st.remove("swi_f")


class TestDependentsFollowTheNewObject(unittest.TestCase):
    """A formula that hands the object on reads the new one after the write."""

    def test_linked_cell_holds_the_new_object(self):
        for label, make, _mutate in KINDS:
            if label == "Vec2":
                continue            # a cell holds a Vec2 by value (copies it)
            with self.subTest(kind=label):
                try:
                    st.swi_src = make()
                    st["swi_dst"] @= lambda: st.swi_src
                    self.assertIs(st.swi_dst, st.swi_src)
                    second = make()
                    st.swi_src = second
                    self.assertIs(st.swi_dst, second)
                finally:
                    st.remove("swi_dst")
                    st.remove("swi_src")

    def test_vec2_alias_is_free_after_the_write(self):
        """The old payload leaves the cell: changing it changes nothing there."""
        runs = []
        try:
            st.swi_p = Vec2(1, 2)
            st["swi_seen"] @= lambda: runs.append(1) or st.swi_p.x
            self.assertEqual(st.swi_seen, 1)
            old = st.swi_p
            st.swi_p = Vec2(1, 2)
            self.assertEqual(st.swi_seen, 1)
            n = len(runs)
            old.x = 9
            self.assertEqual((st.swi_p.x, st.swi_seen), (1, 1))
            self.assertEqual(len(runs), n)
            st.swi_p.x = 4                  # the new payload still tells the cell
            self.assertEqual(st.swi_seen, 4)
        finally:
            st.remove("swi_seen")
            st.remove("swi_p")


class TestImmutableValuesStayNoOps(unittest.TestCase):
    """The no-op saving: an equal immutable value re-runs nothing."""

    def test_repeated_equal_write_runs_no_formula(self):
        values = (3, 2.5, "a", (1, 2), None, True)
        for value in values:
            with self.subTest(value=value):
                runs = []
                try:
                    st.swi_n = value
                    st["swi_seen"] @= lambda: runs.append(1) or st.swi_n
                    self.assertEqual(st.swi_seen, value)
                    n = len(runs)
                    for _ in range(3):
                        st.swi_n = (value[0], value[1]) if type(value) is tuple else value
                        self.assertEqual(st.swi_seen, value)
                    self.assertEqual(len(runs), n)
                finally:
                    st.remove("swi_seen")
                    st.remove("swi_n")

    def test_a_flag_and_a_number_differ(self):
        try:
            st.swi_n = True
            st.swi_n = 1
            self.assertIs(type(st.swi_n), int)
        finally:
            st.remove("swi_n")


if __name__ == "__main__":
    unittest.main()
