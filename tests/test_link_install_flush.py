"""A watch that fires while a formula is being installed (CD6).

Outside a frame (the top of the file, the first act's ``setup``) installing
a formula writes its first value at once, and that write flushes
``@when`` / ``@on_change``. A callback there can destroy a source of the
formula, destroy the field's own object, or relink or unlink the field. Each
of those clears the link being installed; ``FormulaLink.evaluate_and_update``
went on with ``self.owner`` gone and raised Python's own ``AttributeError``
(law X2: an engine error never reaches the author as Python's own error).
Found by the chaos doors: ``oficina/parado``, a ``group.destroy`` in the
first watch callback.

Bug class guarded here: **a callback flushed by a link install changes that
link** (every kind of link owner x ``@on_change`` / ``@when`` x every command
that ends or replaces the link). The outcome must be the one the same command
has between frames: a destroyed source freezes the field at its last value
with the unlink warning, a relink follows the new formula, an unlink keeps
the value.
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Circle, Rect, State, Text, group, init, on_change, when  # noqa: E402
from scena.state import get_scena_system  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class _Owner:
    """One kind of link owner: how to make it, install, relink, unlink, read."""

    def __init__(self, kind):
        self.kind = kind
        self.obj = None
        if kind == "state_cell":
            self.st = State(name="cd6")
            self.st.p = 0.0
        elif kind == "actor_field":
            self.obj = Rect(center=(300, 300), width=20, height=20)
            self.obj.hp = 0.0
        elif kind == "shape_scalar":
            self.obj = Circle(center=(300, 300), radius=5)
        elif kind == "whole_point":
            self.obj = Rect(center=(0, 300), width=20, height=20)
        elif kind == "text":
            self.obj = Text("0", top_left=(10, 10))

    def read(self):
        k = self.kind
        if k == "state_cell":
            return self.st.p
        o = self.obj
        if k == "actor_field":
            return o.hp
        if k == "shape_scalar":
            return o.radius
        if k == "whole_point":
            return o.center.x
        return float(o.text)

    def install(self, a):
        k, o = self.kind, self.obj
        if k == "state_cell":
            self.st["p"] @= lambda: a.v + 1
        elif k == "actor_field":
            o["hp"] @= lambda: a.v + 1
        elif k == "shape_scalar":
            o["radius"] @= lambda: a.v + 1
        elif k == "whole_point":
            o["center"] @= lambda: (a.v + 1, 300)
        else:
            o["text"] @= lambda: f"{a.v + 1:.0f}"

    def relink(self, b):
        k, o = self.kind, self.obj
        if k == "state_cell":
            self.st["p"] @= lambda: b.v * 2
        elif k == "actor_field":
            o["hp"] @= lambda: b.v * 2
        elif k == "shape_scalar":
            o["radius"] @= lambda: b.v * 2
        elif k == "whole_point":
            o["center"] @= lambda: (b.v * 2, 300)
        else:
            o["text"] @= lambda: f"{b.v * 2:.0f}"

    def unlink(self):
        k, o = self.kind, self.obj
        name = {"actor_field": "hp", "shape_scalar": "radius",
                "whole_point": "center", "text": "text"}.get(k)
        if k == "state_cell":
            self.st["p"].unlink()
        else:
            o[name].unlink()


OWNERS = ("state_cell", "actor_field", "shape_scalar", "whole_point", "text")
WATCHES = ("on_change", "when")
COMMANDS = ("destroy_source", "destroy_group", "destroy_owner", "relink", "unlink")


class TestACallbackFlushedByAnInstallChangesThatLink(unittest.TestCase):

    def setUp(self):
        init(width=800, height=600)

    def _cell(self, kind, watch, command):
        init(width=800, height=600)
        owner = _Owner(kind)
        a = Rect(center=(100, 100), width=10, height=10, group="cd6_fontes")
        a.v = 50.0
        b = Rect(center=(200, 100), width=10, height=10)
        b.v = 5.0
        ran = []

        def act(*_):
            if ran:
                return
            if command == "destroy_source":
                a.destroy()
            elif command == "destroy_group":
                group["cd6_fontes"].destroy()
            elif command == "destroy_owner":
                owner.obj.destroy()
            elif command == "relink":
                owner.relink(b)
            else:
                owner.unlink()
            ran.append(command)

        if watch == "on_change":
            reg = on_change(lambda: owner.read())(act)
        else:
            reg = when(lambda: owner.read() > 40)(act)
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                owner.install(a)          # CD6: AttributeError escaped here
                get_scena_system().flush()
            msgs = [str(w.message) for w in caught]
            self.assertEqual(ran, [command], "the callback ran to its end, once")
            if command in ("destroy_source", "destroy_group"):
                self.assertFalse(a.is_alive)
                self.assertEqual(owner.read(), 51, "the field keeps the formula's last value")
                self.assertTrue(any("unlinked because a formula source" in m for m in msgs), msgs)
            elif command == "destroy_owner":
                self.assertFalse(owner.obj.is_alive)
                self.assertTrue(a.is_alive)
            elif command == "relink":
                self.assertEqual(owner.read(), 10, "the new formula holds")
                b.v = 30.0
                self.assertEqual(owner.read(), 60, "and follows its source")
                a.v = 0.0
                self.assertEqual(owner.read(), 60, "the old formula is gone")
            else:
                self.assertEqual(owner.read(), 51)
                a.v = 0.0
                self.assertEqual(owner.read(), 51, "unlinked: keeps its value")
        finally:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for x in (a, b, owner.obj):
                    if x is not None and x.is_alive:
                        x.destroy()
            cancel = getattr(reg, "cancel", None)
            if cancel is not None:
                cancel()

    def test_every_owner_watch_and_command(self):
        for kind in OWNERS:
            for watch in WATCHES:
                for command in COMMANDS:
                    if command == "destroy_owner" and kind == "state_cell":
                        continue
                    with self.subTest(owner=kind, watch=watch, command=command):
                        self._cell(kind, watch, command)

    def test_oficina_shape_a_when_destroys_the_group_the_formula_reads(self):
        """The chaos finding in plain author code: a State cell summed from
        two generators; the first ``@on_change`` destroys their group."""
        init(width=800, height=600)
        st = State(name="cd6_oficina")
        st.potencia = 0.0
        ga = Rect(center=(100, 100), width=90, height=60, group="cd6_gerador")
        gb = Rect(center=(300, 100), width=90, height=60, group="cd6_gerador")
        ga.saida = 20.0
        gb.saida = 30.0
        seen = []

        def mudou(valor):
            seen.append(valor)
            group["cd6_gerador"].destroy()

        reg = on_change(lambda: st.potencia)(mudou)
        try:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                st["potencia"] @= lambda: ga.saida + gb.saida
            self.assertEqual(seen, [50.0])
            self.assertFalse(ga.is_alive or gb.is_alive)
            self.assertEqual(st.potencia, 50.0)
        finally:
            for x in (ga, gb):
                if x.is_alive:
                    x.destroy()
            cancel = getattr(reg, "cancel", None)
            if cancel is not None:
                cancel()


if __name__ == "__main__":
    unittest.main()
