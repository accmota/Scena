"""A formula's reads inside the arguments of a call in the middle of a chain.

Regression for 2026-10-21 (found writing ``examples/affinity.py``):
``liquido["fill"] @= lambda: TONS.get_color(st.calor).with_alpha(0.35)``
raised "@= formula has no reactive sources". The source extractor walks a
chain (``a.b(...).c``) down to its base name and stepped from each call to
its function, dropping the call's arguments: ``st.calor`` was never seen.
Alone it was a refusal with a wrong message (``str(st.n).upper()``,
``Color.from_hsv(st.h, 1, 1).lighter()``); next to another source it was
silent: ``lambda: a.value + float(str(st.n).strip())`` linked on ``a`` only
and kept its first ``st.n`` for good.

Fix: ``SourceExtractor._visit_call_arguments`` (``scena/state.py``) visits
the positional and keyword arguments of every call inside an attribute or
subscript chain.

Bug class: **a read the source pass walks past**. Guarded by: the chain
shapes (call then attribute, call then subscript, keyword arguments, calls
nested in arguments, a call deep in a longer chain), each one checked to
update when the read changes, and the silent shape (another source beside
it) checked to update on the hidden read alone.

    python tests/run_tiers.py focused test_formula_chain_args
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena  # noqa: F401 — installs builtins (group, st, …)
from scena.color import Color, Colormap
from scena.state import Attribute, State

# Rebuilt in setUp: other suites reset the scena system, and a State made at
# import time would then belong to a dead graph.
ST = None
TONS = Colormap.from_colors("red", "blue")


def fresh_state():
    global ST
    ST = State(name="formula_chain_args")
    ST.n = 3
    ST.t = 0.0


class TestChainArguments(unittest.TestCase):
    def setUp(self):
        fresh_state()

    def check(self, formula, first, change, then):
        sink = Attribute(None)
        sink @= formula
        self.assertEqual(sink.value, first)
        change()
        self.assertEqual(sink.value, then)

    def test_call_then_method(self):
        self.check(lambda: str(ST.n).upper(), "3", lambda: setattr(ST, "n", 7), "7")

    def test_engine_object_call_then_method(self):
        """The example's shape: a Colormap colour, then ``with_alpha``."""
        self.check(lambda: TONS.get_color(ST.t).with_alpha(0.5).rgb,
                   TONS.get_color(0.0).with_alpha(0.5).rgb,
                   lambda: setattr(ST, "t", 1.0),
                   TONS.get_color(1.0).with_alpha(0.5).rgb)

    def test_class_call_then_method(self):
        self.check(lambda: Color.from_hsv(ST.t, 1, 1).lighter().rgb,
                   Color.from_hsv(0.0, 1, 1).lighter().rgb,
                   lambda: setattr(ST, "t", 0.5),
                   Color.from_hsv(0.5, 1, 1).lighter().rgb)

    def test_call_then_subscript(self):
        self.check(lambda: str(ST.n)[0], "3", lambda: setattr(ST, "n", 9), "9")

    def test_keyword_argument(self):
        self.check(lambda: dict(x=ST.n).get("x"), 3,
                   lambda: setattr(ST, "n", 42), 42)

    def test_call_nested_in_an_argument(self):
        self.check(lambda: str(abs(ST.n)).zfill(2), "03",
                   lambda: setattr(ST, "n", -8), "08")

    def test_call_deep_in_a_longer_chain(self):
        self.check(lambda: str(ST.n).strip().upper().zfill(2), "03",
                   lambda: setattr(ST, "n", 5), "05")

    def test_beside_another_source_it_is_not_stale(self):
        """The silent shape: the link had ``a`` only and kept the first n."""
        a = Attribute(1.0)
        sink = Attribute(0.0)
        sink @= lambda: a.value + float(str(ST.n).strip())
        self.assertEqual(sink.value, 4.0)
        ST.n = 5
        self.assertEqual(sink.value, 6.0, "the read inside the call was not a source")
        a.value = 2.0
        self.assertEqual(sink.value, 7.0)


if __name__ == "__main__":
    unittest.main()
