"""Vec2 door matrix: every kind × door × operand × context, one generic oracle.

Testing Design, "Vec2 battery". Each Vec2 bug so far sat on a door the tests
never sent that operand through (VI1–VI3, SV10, GX15), so this module crosses
the axes ``vec2_support`` names and checks every cell with the same
invariants: a refusal is Scena's and changes nothing; an accepted write leaves
two finite floats, a length / angle that agree with them, formulas reading the
holder in step, a copy saved elsewhere unmoved, and the value a free twin
written the plain way has. Nothing predicts a value per cell.

* ``quick``: the full product in the plain context, a 2-wise array over the
  four contexts, and every kind × door × context × read with one good operand
  (the 2-wise array missed VB16, which needs a kind, a context and a read).
* ``gate`` / ``deep``: the full product in every context, plus the stale
  check on ``vec2_known``.

    python -m unittest tests.test_vec2_doors -v
"""
from __future__ import annotations

import contextlib
import fnmatch
import inspect
from unittest import mock
import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math  # noqa: E402

from scena import Circle, State, Vec2, init, on_change  # noqa: E402

import covering  # noqa: E402
import hypothesis_support  # noqa: E402
import vec2_known as KNOWN  # noqa: E402
import vec2_support as V  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the cells made

DEEP = hypothesis_support.PROFILE in ("ci", "deep")


def _run(rows):
    """Run ``rows``; return ({key: detail}, reach) for every violation."""
    found = {}
    reach = {"accepted": set(), "refused": set()}
    for row in rows:
        kind, door, operand, context, read = (
            row["kind"], row["door"], row["operand"], row["context"], row["read"])
        violations = V.run_cell(kind, door, operand, context, read)
        for inv, detail in violations.items():
            found[f"{kind}|{door}|{operand}|{context}/{read}|{inv}"] = detail
        reach["accepted" if operand in V.NEVER_REFUSED else "refused"].add((kind, door))
    return found, reach


def _known(key):
    return next((pat for pat in KNOWN.DOORS if fnmatch.fnmatchcase(key, pat)), None)


def _unknown(found):
    return sorted(k for k in found if _known(k) is None)


def _fmt(keys, found):
    return "\n  ".join(f"{k}  {found[k]}"[:260] for k in keys[:40]) + (
        f"\n  … {len(keys) - 40} more" if len(keys) > 40 else "")


def _full_rows(contexts):
    return [dict(kind=k, door=d, operand=o, context=c, read=r)
            for k, d, o, c, r in itertools.product(V.KINDS, V.DOORS, V.OPERANDS,
                                                   contexts, V.READS)
            if V.door_valid(k, d)]


class TestDoorMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=800, height=600)

    def assertNoNewViolations(self, found):
        new = _unknown(found)
        self.assertFalse(new, f"{len(new)} Vec2 door violations (triage, then fix or "
                              f"list in vec2_known):\n  {_fmt(new, found)}")

    def test_full_product_plain(self):
        found, reach = _run(_full_rows(["plain"]))
        self.assertNoNewViolations(found)
        # Not vacuous: every valid (kind, door) ran with good and bad operands.
        pairs = {(k, d) for k in V.KINDS for d in V.DOORS if V.door_valid(k, d)}
        self.assertEqual(reach["accepted"], pairs)
        self.assertEqual(reach["refused"], pairs)

    def test_contexts_pairwise(self):
        rows = covering.covering_array(V.axes(), 2, V.valid)
        self.assertFalse(covering.uncovered_tuples(rows, V.axes(), 2, V.valid))
        found, _ = _run(rows)
        self.assertNoNewViolations(found)

    def test_every_context_one_operand(self):
        # kind × door × context × read with one good operand: the triple
        # (free, callback, warm) that the 2-wise array missed held VB16.
        rows = [r for r in _full_rows(list(V.CONTEXTS)) if r["operand"] == "(3, 4) ints"]
        found, _ = _run(rows)
        self.assertNoNewViolations(found)

    def test_full_product_every_context(self):
        if not DEEP:
            self.skipTest("the full product in every context runs in gate and deep")
        found, _ = _run(_full_rows(list(V.CONTEXTS)))
        self.assertNoNewViolations(found)
        stale = [pat for pat in KNOWN.DOORS
                 if not any(fnmatch.fnmatchcase(k, pat) for k in found)]
        self.assertFalse(stale, f"vec2_known entries nothing matches (fixed: remove "
                                f"them): {stale}")


class TestOracleBites(unittest.TestCase):
    """The oracle reports what it claims to (Testing Design, lessons 10, 11, 19)."""

    @classmethod
    def setUpClass(cls):
        init(width=800, height=600)

    def test_each_invariant_can_fire(self):
        """One planted bug per invariant; each must be reported (lesson 19)."""
        from scena.state import Attribute, _HeldPayloadUpdate, _HeldPayloadWrite
        stale = lambda *a, **k: None    # noqa: E731
        store_xy = Vec2._store_xy
        takein = Attribute._takein_impl
        lshift_impl = Vec2._takein_impl

        def write_then_check(self, x, y, bare=False):   # pre-4c5c2aa: write first
            self.__dict__["x"] = x
            store_xy(self, x, y, bare)

        def no_check(self, x, y, bare=False):
            self.__dict__.update(x=x, y=y)
            self._sync_computed()

        def owned_off_by_one(self, x, y, bare=False):
            store_xy(self, x + (1.0 if self.__dict__.get("_owner") else 0.0), y, bare)

        def alias(self, new_value):     # undo VB2's copy: the cell shares
            changed = takein(self, new_value)
            if isinstance(new_value, Vec2):
                self.__dict__["_raw_value"] = new_value
            return changed

        def always_refuse(self, name, value):
            raise AttributeError("planted: the guard refuses in a batch too")

        def none_is_zero(self, other):
            return lshift_impl(self, (0, 0) if other is None else other)

        def leaky_mul(self, k):
            raise TypeError("unsupported operand type(s) for *: 'Vec2' and 'x'")

        cases = {
            # invariant: (kind, door, operand, plants)
            "number": ("free", "+=", "(3, 4) ints", [(Vec2, "_store_xy", lambda self, x, y,
                       bare=False: self.__dict__.update(x=10 ** 400, y=y))]),
            "derived": ("free", "<<", "(3, 4) ints", [(Vec2, "_sync_computed", stale),
                                                      (Vec2, "_update_impl", stale)]),
            "partial": ("free", "+=", "(inf, 0)", [(Vec2, "_store_xy", write_then_check)]),
            "finite": ("free", "+=", "(inf, 0)", [(Vec2, "_store_xy", no_check)]),
            "follow": ("st", "<<", "(3, 4) ints", [(_HeldPayloadUpdate, "changed", stale),
                                                   (_HeldPayloadUpdate, "__call__", stale)]),
            "kept": ("st_saved", "+=", "(3, 4) ints", [(Attribute, "_takein_impl", alias)]),
            "refused": ("st", "+=", "(3, 4) ints", [(_HeldPayloadWrite, "__call__", always_refuse)]),
            "twin": ("vel", "+=", "(3, 4) ints", [(Vec2, "_store_xy", owned_off_by_one)]),
            "leak": ("vel", "*=", "(3, 4) ints", [(Vec2, "__mul__", leaky_mul)]),
            "bad": ("free", "<<", "None", [(Vec2, "_takein_impl", none_is_zero)]),
            "accepted": ("line_derived", "+=", "(3, 4) ints",
                         [(Vec2, "_refuse_derived_axes", stale),
                          (Vec2, "_refuse_author_write", stale)]),
        }
        self.assertEqual(set(cases), set(V.INVARIANTS), "an invariant without a canary")
        for inv, (kind, door, operand, plants) in cases.items():
            with self.subTest(invariant=inv), contextlib.ExitStack() as stack:
                for owner, attr, plant in plants:
                    stack.enter_context(mock.patch.object(owner, attr, plant))
                found = V.run_cell(kind, door, operand, "plain", "warm")
                self.assertIn(inv, found, f"the planted bug went unseen: {found}")


class TestFoundByTheMatrix(unittest.TestCase):
    """One minimal repro per row the matrix found (Testing Design, VB)."""

    def setUp(self):
        init(width=800, height=600)
        self.owned = []

    def tearDown(self):
        for obj in reversed(self.owned):
            try:
                obj.destroy()
            except Exception:  # noqa: BLE001
                pass

    def circle(self, **kw):
        c = Circle(radius=5, **kw)
        self.owned.append(c)
        return c

    def test_vb1_an_int_axis_does_not_slip_past_the_check(self):
        # ``w.x = 4`` keeps an int; ``4 + 10**400`` is an int whose x - x is 0.
        def vel():
            c = self.circle(center=(0, 0))
            c.vel = (1, 2)
            return c.vel

        for make in (lambda: Vec2(1, 2), vel):
            w = make()
            w.x = 4
            with self.assertRaises(ValueError):
                w += (10 ** 400, 0)
            self.assertEqual((w.x, w.y), (4, 2.0))
            self.assertEqual(w.length, math.hypot(4, 2))
            w += (1, 1)                     # an int result is stored as a float
            self.assertIs(type(w.x), float)

    def test_vb2_a_cell_copies_a_vector_another_cell_holds(self):
        st = State(name="vb2")
        st.pos = Vec2(1, 2)
        st.start = st.pos                   # save where it started
        st.pos += (5, 0)
        self.assertEqual(tuple(st.start), (1.0, 2.0))
        st.start = Vec2(9, 9)               # the guard stays on st.pos
        with self.assertRaises(AttributeError):
            st.pos.x = 5

    def test_vb2_a_cell_copies_an_ink_fields_vector(self):
        for watched in (False, True):
            with self.subTest(watched=watched):
                ship = self.circle(center=(0, 0))
                ship.aim = Vec2(1, 2)
                if watched:
                    self.circle(center=lambda: ship.aim)
                st = State(name="vb2b")
                st.v0 = ship.aim            # a snapshot
                ship.aim.x = 9              # ink takes in-place writes
                ship.aim += (1, 1)
                self.assertEqual(tuple(st.v0), (1.0, 2.0))
                self.assertEqual(tuple(ship.aim), (10.0, 3.0))

    def test_vb3_an_st_vector_refuses_an_axis_link(self):
        st = State(name="vb3")
        st.k = 1.0
        st.pos = Vec2(0, 0)
        with self.assertRaises(TypeError) as cm:
            st.pos["x"] @= lambda: st.k
        self.assertIn('vb3["pos"] @= lambda: Vec2(x, y)', str(cm.exception))
        self.assertIsNone(st.pos.__dict__.get('_field_anchors'))

    def test_vb3_an_ink_vectors_later_pulls_reach_its_readers(self):
        src = State(name="vb3_src")
        src.k = 1.0
        for spelling in ("whole", "axis", "linked before held"):
            with self.subTest(spelling=spelling):
                ship = self.circle(center=(0, 0))
                if spelling == "linked before held":
                    v = Vec2(0, 0)
                    v @= lambda: Vec2(src.k, 2)
                    ship.aim = v
                else:
                    ship.aim = Vec2(1, 2)
                mira = self.circle(center=lambda: ship.aim)
                if spelling == "whole":
                    ship.aim @= lambda: Vec2(src.k, 2)
                elif spelling == "axis":
                    ship.aim["x"] @= lambda: src.k
                for k in (3.0, 4.5):
                    src.k = k
                    self.assertEqual((mira.center.x, mira.center.y), (k, 2.0))
                ship.aim = Vec2(7, 7)       # the field lets go: its edges go too
                src.k = 8.0
                self.assertEqual((mira.center.x, mira.center.y), (7.0, 7.0))

    def test_vb3_a_cell_takes_a_linked_vector_by_value(self):
        # Found by the machine (ci profile): a free vector linked first, then
        # put in a cell; its pulls never reached what reads the cell.
        src = State(name="vb3c_src")
        src.k = 1.0
        for whole in (False, True):
            with self.subTest(whole=whole):
                src.k = 1.0
                v = Vec2(1, 2)
                if whole:
                    v @= lambda: Vec2(src.k, 2)
                else:
                    v["x"] @= lambda: src.k
                st = State(name="vb3c")
                st.pos = v
                mira = self.circle(center=lambda: st.pos)
                src.k = 5.0
                self.assertEqual(tuple(st.pos), (1.0, 2.0))     # the value then
                self.assertEqual((mira.center.x, mira.center.y), (1.0, 2.0))
                self.assertEqual(v.x, 5.0)                      # v still follows

    def test_vb16_an_in_place_op_in_a_callback_refreshes_length(self):
        # Found by the gate's full product: in a flush callback the batch exit
        # marked the vector dirty by node id, and a free vector has none.
        st = State(name="vb16")
        st.go = 0
        v = Vec2(1, 2)
        v.length, v.angle                   # read: cached
        seen = {}

        def cb(value):
            v.__iadd__((3, 4))
            seen["read"] = (v.length, v.angle)
            v.do_rotation(90)
            seen["turned"] = v.angle

        on_change(st["go"])(cb)
        st.go = 1
        self.assertEqual(seen["read"], (math.hypot(4, 6), math.degrees(math.atan2(6, 4))))
        self.assertEqual(seen["turned"], math.degrees(math.atan2(v.y, v.x)))

    def test_vb4_every_door_refuses_nan_and_inf(self):
        src = State(name="vb4_src")
        src.p = (1.0, 2.0)
        for bad in ((math.nan, 0.0), (0.0, math.inf), (-math.inf, 1.0)):
            with self.subTest(bad=bad):
                v = Vec2(1, 2)
                with self.assertRaises(ValueError) as cm:
                    v << bad
                self.assertIn("a vector takes two finite numbers", str(cm.exception))
                self.assertEqual((v.x, v.y), (1.0, 2.0))
                # A pull raises on the read while the source is bad, and
                # the next read recovers (as a number slot's link does).
                w = Vec2(0, 0)
                src.p = (1.0, 2.0)
                w @= lambda: src.p
                src.p = bad
                with self.assertRaises(ValueError):
                    w.x
                src.p = (5.0, 6.0)
                self.assertEqual((w.x, w.y), (5.0, 6.0))
                # Held by a cell, the bad write is refused at the write, not
                # in a formula that reads the cell later.
                st = State(name="vb4")
                st.pos = Vec2(1, 2)
                mira = self.circle(center=lambda: st.pos)
                with self.assertRaises(ValueError):
                    st.pos << bad
                self.assertEqual((mira.center.x, mira.center.y), (1.0, 2.0))

    def test_vb5_overflow_is_a_scena_error(self):
        v = Vec2(1, 2)
        for call in (lambda: v + (10 ** 400, 0), lambda: v - (0, 10 ** 400),
                     lambda: v * 10 ** 400):
            with self.assertRaises(ValueError) as cm:
                call()
            self.assertIn("a vector takes two finite numbers", str(cm.exception))

    def test_vb15_a_part_refuses_nan_in_a_vectors_words(self):
        ship = self.circle(center=(0, 0))
        ship.vel = (1, 2)
        for bad in ((math.nan, 0), (0, math.inf), [-math.inf, 1]):
            with self.assertRaises(ValueError) as cm:
                ship.vel << bad
            self.assertIn("a vector takes two finite numbers", str(cm.exception))
            self.assertEqual((ship.vel.x, ship.vel.y), (1.0, 2.0))

    def test_vb15_a_dead_write_names_the_field(self):
        # The dead route refused every name as "Circle.set" (_DeadSetter).
        from scena.state import DestroyedError
        dead = self.circle(center=(0, 0))
        dead.vel = (1, 1)
        dead.destroy()
        writes = {"vel": (5, 5), "mass": 3, "time_scale": 2, "center": (1, 1),
                  "radius": 9, "pontos": 4}
        for name, value in writes.items():
            with self.assertRaises(DestroyedError) as cm:
                setattr(dead, name, value)
            self.assertIn(f"Circle.{name} cannot change a destroyed actor",
                          str(cm.exception))
            self.assertNotIn("Circle.set", str(cm.exception))

    def test_vb15_a_dead_in_place_op_says_destroyed_before_finite(self):
        from scena.state import DestroyedError
        dead = self.circle(center=(0, 0))
        dead.vel = (1, 2)
        held = dead.vel
        dead.destroy()
        ops = (lambda v: v.__iadd__((math.inf, 0)),
               lambda v: v.__iadd__((0, math.nan)),
               lambda v: v.__isub__((math.inf, 0)),
               lambda v: v.__iadd__((10 ** 400, 0)),
               lambda v: v.__isub__((0, 10 ** 400)),
               lambda v: v.__iadd__(("a", 1)),
               lambda v: v.__isub__("zz"),
               lambda v: v.do_rotation(math.nan),
               lambda v: v.do_rotation("a"),
               lambda v: v.do_rotation(30),
               lambda v: v.__iadd__((1, 0)))
        for op in ops:
            for cold in (False, True):
                if cold:                    # the non-bare branch of _store_xy
                    held.__dict__.pop("_scalar_bare_ok", None)
                with self.assertRaises(DestroyedError):
                    op(held)
                self.assertEqual((held.x, held.y), (1.0, 2.0))

    def test_vb8_a_list_compares_like_a_tuple(self):
        v = Vec2(3, 4)
        self.assertTrue(v == [3, 4])
        self.assertFalse(v != [3, 4])
        self.assertFalse(v == [3, 5])
        self.assertFalse(v == [3, 4, 0])
        self.assertTrue([3, 4] == v)        # reflected: list defers to Vec2
        self.assertEqual(v == [3, 4], v == (3, 4))

    def test_vb11_no_x_only_constructor_is_advertised(self):
        import typing
        for kw in ({"x": 1}, {"y": 2}):
            with self.assertRaises(ValueError) as cm:
                Vec2(**kw)
            self.assertIn("Vec2 takes x and y together", str(cm.exception))
        for sig in typing.get_overloads(Vec2.__new__):
            names = set(inspect.signature(sig).parameters) - {"cls", "kwargs"}
            self.assertFalse(names == {"x"}, "an x-only overload is advertised")
        self.assertNotIn("not all parameters are required", Vec2.__doc__)


if __name__ == "__main__":
    unittest.main()
