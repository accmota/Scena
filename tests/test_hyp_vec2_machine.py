"""Vec2 state machine: holders, links, doors and lifetimes in any order.

Testing Design, "Vec2 battery". The door matrix (``test_vec2_doors``) runs
one write on a fresh subject; bugs that need a history — two cells and one
vector, a link installed while held, a holder that lets go, an actor that dies
— need sequences. This machine keeps a pool of vectors (free, actors' ``vel``,
st cells' and ink fields' vectors, linked ones) and formulas reading the
holders, and checks after every step, with no model of its own:

* every vector holds two finite numbers a float holds, and its length / angle
  agree with them;
* every formula reading a holder shows what the holder holds now;
* a cell's vector is its own: no other cell holds that object, and the
  cell's guard is on it (``st.pos.x = …`` raises). An ink field stores by
  reference (``ship.aim = st.pos`` aliases the cell's vector, by design);
* a refused step changed no vector.

    SCENA_HYPOTHESIS_PROFILE=ci python -m unittest tests.test_hyp_vec2_machine -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import strategies as hst  # noqa: E402
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule  # noqa: E402

import hypothesis_support as hs  # noqa: E402
import vec2_support as V  # noqa: E402
from scena import Circle, State, Vec2, init  # noqa: E402
from scena.state import held_cell  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()

exact = hst.integers(min_value=-200, max_value=200).map(float)
pair = hst.tuples(exact, exact)
CELLS = ("a", "b", "c")
FIELDS = ("aim", "dir")


class Vec2Machine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        init(width=800, height=600)
        self.owned = []
        self.st = State(name="vm")
        self.src = State(name="vm_src")
        self.src.k = 1.0
        self.src.p = (1.0, 2.0)
        for name in CELLS:
            setattr(self.st, name, Vec2(1, 2))
        self.ships = [self._circle() for _ in range(2)]
        for ship in self.ships:
            ship.vel = (1, 2)
            for f in FIELDS:
                setattr(ship, f, Vec2(1, 2))
        self.free = [Vec2(1, 2), Vec2(3, 4)]
        self.watches = []           # (label, formula reader, holder reader)
        st, (s0, s1) = self.st, self.ships
        # A formula names its sources (``getattr(obj, attr)`` names none).
        self.formulas = {
            "st.a": lambda: st.a, "st.b": lambda: st.b, "st.c": lambda: st.c,
            "ship0.aim": lambda: s0.aim, "ship0.dir": lambda: s0.dir,
            "ship1.aim": lambda: s1.aim, "ship1.dir": lambda: s1.dir,
        }

    def _circle(self, center=(100, 100)):
        c = Circle(center=center, radius=5)
        self.owned.append(c)
        return c

    def teardown(self):
        for obj in reversed(self.owned):
            try:
                obj.destroy()
            except Exception:  # noqa: BLE001
                pass

    # -- the vectors an author can reach now ------------------------------

    def holders(self):
        out = [(f"st.{n}", self.st, n) for n in CELLS]
        for i, ship in enumerate(self.ships):
            if ship:
                out.append((f"ship{i}.vel", ship, "vel"))
                out += [(f"ship{i}.{f}", ship, f) for f in FIELDS]
        return out

    def vectors(self):
        vs = list(self.free)
        for _, obj, attr in self.holders():
            v = getattr(obj, attr)
            if isinstance(v, Vec2):
                vs.append(v)
        return vs

    def snapshot(self):
        return [(id(v), V.raw_xy(v)) for v in self.vectors()]

    def run_author(self, step):
        """Run ``step``; a refusal must be Scena's and must change no vector."""
        before = self.snapshot()
        try:
            with hs.quiet():
                step()
        except V.AUTHOR_ERRORS as exc:
            assert not hs.leak_message(exc), f"leaked: {type(exc).__name__}: {exc}"
            after = dict(self.snapshot())
            for vid, xy in before:
                if vid in after:
                    assert V.same_xy(after[vid], xy), f"refused ({exc!s:.80}) but a vector moved"

    def pick_vector(self, data):
        return data.draw(hst.sampled_from(self.vectors()))

    def pick_holder(self, data):
        return data.draw(hst.sampled_from(self.holders()))

    # -- rules --------------------------------------------------------------

    @rule(data=hst.data(), o=pair, door=hst.sampled_from(["+=", "-=", "<<", "x", "rot"]))
    def write_in_place(self, data, o, door):
        v = self.pick_vector(data)

        def step():
            if door == "+=":
                v.__iadd__(o)
            elif door == "-=":
                v.__isub__(o)
            elif door == "<<":
                v << o
            elif door == "x":
                v.x = o[0]
            else:
                v.do_rotation(o[0])
        self.run_author(step)

    @rule(data=hst.data(), o=pair, door=hst.sampled_from(["+=", "= new", "*="]))
    def write_through_holder(self, data, o, door):
        _, obj, attr = self.pick_holder(data)

        def step():
            if door == "+=":
                v = getattr(obj, attr)
                v += o
                setattr(obj, attr, v)
            elif door == "= new":
                setattr(obj, attr, Vec2(*o))
            else:
                v = getattr(obj, attr)
                v *= 2
                setattr(obj, attr, v)
        self.run_author(step)

    @rule(data=hst.data())
    def copy_between_holders(self, data):
        # ``st.start = st.pos``, ``ship.aim = st.pos``, ``st.v0 = ship.aim`` …
        _, obj, attr = self.pick_holder(data)
        _, obj2, attr2 = self.pick_holder(data)
        self.run_author(lambda: setattr(obj, attr, getattr(obj2, attr2)))

    @rule(data=hst.data())
    def hold_a_free_vector(self, data):
        v = data.draw(hst.sampled_from(self.free))
        _, obj, attr = self.pick_holder(data)
        self.run_author(lambda: setattr(obj, attr, v))

    @rule(data=hst.data(), whole=hst.booleans())
    def link(self, data, whole):
        v = self.pick_vector(data)
        src = self.src

        def step():
            if whole:
                v.__imatmul__(lambda: Vec2(src.k, 2))
            else:
                v["y"].__imatmul__(lambda: src.k)
        self.run_author(step)

    @rule(k=exact)
    def move_the_source(self, k):
        self.src.k = k

    @rule(data=hst.data())
    def watch(self, data):
        label, obj, attr = self.pick_holder(data)
        if attr == "vel" or len(self.watches) > 6:
            return
        if not isinstance(getattr(obj, attr), Vec2):
            return
        w = self._circle(center=self.formulas[label])
        self.watches.append((label, w, obj, attr))

    @rule(i=hst.integers(min_value=0, max_value=1))
    def destroy_a_ship(self, i):
        ship = self.ships[i]
        if ship:
            ship.destroy()
            self.watches = [w for w in self.watches if w[2] is not ship and w[1]]

    # -- invariants --------------------------------------------------------

    @invariant()
    def vectors_are_numbers_and_agree(self):
        for v in self.vectors():
            x, y = V.raw_xy(v)
            assert V._holds_number(x) and V._holds_number(y), f"{v!r:.60}"
            assert math.isfinite(x) and math.isfinite(y), f"{v!r:.60}"
            bad = V.derived_ok(v)
            assert bad is None, bad

    @invariant()
    def formulas_follow(self):
        for label, w, obj, attr in self.watches:
            if not w or (hasattr(obj, "__bool__") and not obj):
                continue
            held = getattr(obj, attr)
            if not isinstance(held, Vec2):
                continue
            got = (w.center.x, w.center.y)
            assert got == (float(held.x), float(held.y)), f"{label}: formula {got}, holds {held!r}"

    @invariant()
    def a_cell_holds_its_own_vector(self):
        seen = {}
        for label, obj, attr in self.holders():
            v = getattr(obj, attr)
            if not isinstance(v, Vec2):
                continue
            if obj is self.st:
                assert id(v) not in seen, f"{label} shares its vector with {seen.get(id(v))}"
                assert held_cell(v) is not None, f"{label}'s vector lost its guard"
            seen.setdefault(id(v), label)


TestVec2Machine = Vec2Machine.TestCase


if __name__ == "__main__":
    unittest.main()
