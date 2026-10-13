"""A bracket handle (``st["score"]``, ``c["radius"]``) is never used as its value.

``st.score`` is the value; ``st["score"]`` is the field itself, the handle that
links, binds and watches. A lambda already keeps its reads live, so inside one
the dot is the only spelling. Before, a handle used as a value was silent or
far from its line:

* ``Text(lambda: f"Pontos: {st['score']}")`` showed ``<field State(...)['score']>``;
* ``if st["vivo"]:`` was always true (0 included);
* ``@when(lambda: st["score"] == 5)`` never fired (a fresh handle per ``[]``,
  compared by identity);
* ``st["score"] * 2`` raised Python's bare "unsupported operand".

And ``Text(st["score"])`` shared the cell, so ``placar.text = "oi"`` wrote
``st.score``: a display that changed the game state.

Bug class guarded here: **a handle that acts as a value without saying so**.
Three layers: the formula reader refuses a handle read at link time, with the
line (``@=``, ``Text(lambda)``, constructor links); ``@when`` / ``@on_change``
refuse a lambda that returns a handle at registration; and the handle's own
value protocols raise with the dot spelling everywhere else (REPL, ``print``,
a ``@when`` comparison). The completeness check fails when a value protocol
of ``float`` / ``str`` is missing from ``FieldRef``.
"""
from __future__ import annotations

import math
import operator
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (  # noqa: E402
    Circle, State, Text, init, on_change, st, when,
)
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.state import Attribute, FieldRef, LinkedAttributeError  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class EngineCase(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        self.wm = ScenaFramework.get_instance().widget_manager
        self._owned = []

    def tearDown(self):
        for obj in reversed(self._owned):
            try:
                obj.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def assertNamesDot(self, ctx, dot):
        self.assertIn(dot, str(ctx.exception))


# ---------------------------------------------------------------------------
# The handle's own value protocols
# ---------------------------------------------------------------------------

_UNARY = {
    "bool": bool, "str": str, "format": lambda r: f"{r}", "int": int,
    "float": float, "round": round, "iter": iter, "len": len,
    "neg": operator.neg, "pos": operator.pos, "abs": abs,
    "invert": operator.invert, "index": operator.index,
    "%s": lambda r: "%s" % r, "floor": math.floor, "ceil": math.ceil,
    "trunc": math.trunc, "in": lambda r: 1 in r,
}
_BINARY = {
    name: getattr(operator, name)
    for name in ("eq", "ne", "lt", "le", "gt", "ge", "add", "sub", "mul",
                 "truediv", "floordiv", "mod", "pow", "and_", "or_", "xor",
                 "lshift", "rshift")
}
_BINARY["divmod"] = divmod


class TestHandleRefusesValueUse(EngineCase):
    def handles(self):
        bag = State(name="hud")
        bag.score = 3
        st.hnv_alive = 0
        c = self.track(Circle(radius=5))
        return [
            (bag["score"], "hud.score"),
            (st["hnv_alive"], "st.hnv_alive"),
            (c["radius"], "circle.radius"),
        ]

    def test_every_value_protocol_raises_with_the_dot(self):
        for ref, dot in self.handles():
            for name, op in _UNARY.items():
                with self.subTest(handle=dot, op=name):
                    with self.assertRaises(TypeError) as ctx:
                        op(ref)
                    self.assertNamesDot(ctx, dot)
            for name, op in _BINARY.items():
                for args in ((ref, 2), (2, ref)):
                    with self.subTest(handle=dot, op=name, right=args[1] is ref):
                        with self.assertRaises(TypeError) as ctx:
                            op(*args)
                        self.assertNamesDot(ctx, dot)

    def test_augmented_write_through_a_handle_raises(self):
        # ``st["score"] += 1`` reads the handle as a number first.
        bag = State(name="hud")
        bag.score = 3
        with self.assertRaises(TypeError) as ctx:
            bag["score"] += 1
        self.assertNamesDot(ctx, "hud.score")
        self.assertEqual(bag.score, 3)

    def test_a_value_member_names_the_dotted_read(self):
        bag = State(name="hud")
        bag.score = 3
        with self.assertRaises(AttributeError) as ctx:
            bag["score"].real
        self.assertNamesDot(ctx, "hud.score.real")
        with self.assertRaises(AttributeError):
            bag["score"]._private          # plain, for hasattr probes

    def test_handle_members_still_work(self):
        bag = State(name="hud")
        bag.score = 3
        ref = bag["score"]
        self.assertEqual(ref.value, 3)
        self.assertFalse(ref.is_linked)
        self.assertIn("score", repr(ref))
        self.assertIsInstance(hash(ref), int)
        self.assertIsNot(ref, None)
        self.assertIsInstance(ref, FieldRef)

    # Type machinery a value class defines that is not a way to *use* a value.
    _NOT_A_VALUE_USE = {
        "__getattribute__", "__getformat__", "__getnewargs__",
        "__init_subclass__", "__new__", "__sizeof__", "__subclasshook__",
    }

    def test_completeness_every_number_and_text_protocol_is_guarded(self):
        # A protocol ``int`` / ``float`` / ``str`` define and ``FieldRef``
        # inherits from ``object`` (or lacks) acts silently or with Python's
        # bare message: ``__eq__`` by identity, ``__str__`` as the repr,
        # ``__bool__`` as True, ``"%s" % ref`` as the repr.
        wanted = set()
        for cls in (int, float, str):
            for name in dir(cls):
                if (name.startswith("__") and name not in self._NOT_A_VALUE_USE
                        and getattr(cls, name) is not getattr(object, name, None)):
                    wanted.add(name)
        wanted |= {"__bool__", "__eq__", "__ne__", "__str__", "__format__"}
        for name in sorted(wanted):
            with self.subTest(protocol=name):
                self.assertIn(name, FieldRef.__dict__,
                              f"FieldRef.{name} is missing: a handle would act "
                              "as a value, or fail without the dot spelling")

    def test_subscript_on_a_handle_names_the_value_bracket(self):
        bag = State(name="hud")
        bag.score = 3
        with self.assertRaises(TypeError) as ctx:
            bag["score"]["x"]
        self.assertNamesDot(ctx, "hud.score['x']")


# ---------------------------------------------------------------------------
# Formulas: refused at link time, with the line
# ---------------------------------------------------------------------------

def _score_via_helper():
    return st["hnv_score"] * 2


class TestFormulaRefusesHandleRead(EngineCase):
    def setUp(self):
        super().setUp()
        st.hnv_score = 3

    def test_text_formula_with_bracket_in_fstring(self):
        with self.assertRaises(TypeError) as ctx:
            Text(lambda: f"Pontos: {st['hnv_score']}")
        msg = str(ctx.exception)
        self.assertIn("st.hnv_score", msg)
        self.assertIn("line", msg)

    def test_link_rhs_arithmetic_and_bare_return(self):
        sink = Attribute(0.0)
        for fn in (lambda: st["hnv_score"] * 2, lambda: st["hnv_score"],
                   lambda: 1 if st["hnv_score"] else 0):
            with self.subTest(fn=fn):
                with self.assertRaises(TypeError) as ctx:
                    sink @= fn
                self.assertNamesDot(ctx, "st.hnv_score")

    def test_named_function_and_helper(self):
        sink = Attribute(0.0)

        def twice():
            return st["hnv_score"] * 2

        for fn in (twice, lambda: _score_via_helper()):
            with self.subTest(fn=fn):
                with self.assertRaises(TypeError) as ctx:
                    sink @= fn
                self.assertNamesDot(ctx, "st.hnv_score")

    def test_object_field_and_constructor_link(self):
        c = self.track(Circle(radius=5))
        d = self.track(Circle(radius=1))
        with self.assertRaises(TypeError) as ctx:
            d["radius"] @= lambda: c["radius"] * 2
        self.assertNamesDot(ctx, "c.radius")
        with self.assertRaises(TypeError):
            self.track(Circle(radius=1, center=lambda: (c["radius"], 0)))

    def test_handle_value_member_inside_a_formula_is_refused(self):
        # One spelling inside a formula: the dot. (``.value`` also never
        # linked: the reader followed it to the number and found no source.)
        sink = Attribute(0.0)
        with self.assertRaises(TypeError) as ctx:
            sink @= lambda: st["hnv_score"].value * 2
        self.assertNamesDot(ctx, "st.hnv_score")

    def test_dot_formula_and_lone_bracket_rhs_link(self):
        a = Attribute(0.0)
        a @= lambda: st.hnv_score * 2
        b = Attribute(0.0)
        b @= st["hnv_score"]
        t = self.track(Text(lambda: f"Pontos: {st.hnv_score}"))
        st.hnv_score = 5
        self.assertEqual((a.value, b.value, t.value), (10, 5, "Pontos: 5"))

    def test_plain_dict_subscript_is_not_a_handle(self):
        conf = {"k": 2}
        sink = Attribute(0.0)
        sink @= lambda: conf["k"] * st.hnv_score
        self.assertEqual(sink.value, 6)


# ---------------------------------------------------------------------------
# Events: a lambda returning a handle is refused at registration
# ---------------------------------------------------------------------------

class TestEventLambdaReturningHandle(EngineCase):
    def setUp(self):
        super().setUp()
        st.hnv_wave = 1
        st.hnv_flag = False

    def test_on_change_and_when(self):
        cases = (
            (on_change, lambda: st["hnv_wave"], "st.hnv_wave"),
            (when, lambda: st["hnv_flag"], "st.hnv_flag"),
        )
        for deco, cond, dot in cases:
            with self.subTest(deco=deco.__name__):
                with self.assertRaises(TypeError) as ctx:
                    deco(cond)(lambda *a: None)
                self.assertNamesDot(ctx, dot)

    def test_when_comparison_on_a_handle_raises_not_silent(self):
        with self.assertRaises(TypeError) as ctx:
            when(lambda: st["hnv_wave"] == 5)(lambda: None)
        self.assertNamesDot(ctx, "st.hnv_wave")

    def test_bare_handle_still_watches(self):
        got = []
        on_change(st["hnv_wave"])(lambda v: got.append(v))
        fired = []
        when(st["hnv_flag"])(lambda: fired.append(1))
        st.hnv_wave = 2
        st.hnv_flag = True
        self.assertEqual((got, fired), ([2], [1]))


# ---------------------------------------------------------------------------
# Text(st["x"]) shows the cell one way
# ---------------------------------------------------------------------------

class TestTextCellIsOneWay(EngineCase):
    def test_write_raises_naming_the_cell_and_leaves_it(self):
        st.hnv_pts = 3
        placar = self.track(Text(st["hnv_pts"]))
        self.assertEqual(placar.value, 3)
        with self.assertRaises(LinkedAttributeError) as ctx:
            placar.text = "oi"
        self.assertNamesDot(ctx, "st.hnv_pts = ")
        self.assertEqual(st.hnv_pts, 3)
        st.hnv_pts = 7
        self.assertEqual(placar.value, 7)

    def test_standalone_attribute_too(self):
        cell = Attribute("a")
        t = self.track(Text(cell))
        cell.value = "b"
        self.assertEqual(t.value, "b")
        with self.assertRaises(LinkedAttributeError):
            t.text = "c"
        self.assertEqual(cell.value, "b")


if __name__ == "__main__":
    unittest.main()
