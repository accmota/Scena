"""``@=`` with named functions, and the full-visibility check (``formula_check``).

A formula's sources are read from its code once, at link time. Anything the
static pass cannot see would leave the link silently stale, so ``@=`` refuses
it instead. Headless.

    python -m unittest tests.test_formula_functions -v
"""
import ast
import json  # noqa: F401 — stdlib call allowed inside a formula
import math
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena  # noqa: F401 — installs builtins (group, st, …)
from scena import formula_check
from scena.shapes import Point
from scena.state import Attribute, State
from scena.easing import lerp
from tests.test_progress import new_state  # another module: not followed

# Rebuilt in setUp: other suites reset the scena system, and a State made at
# import time would then belong to a dead graph. Helpers read the global.
ST = None


def rotulo():
    return f"vidas {ST.vidas}"


def nivel_0():
    return nivel_1()


def nivel_1():
    return nivel_2()


def nivel_2():
    return nivel_3()


def nivel_3():
    return nivel_4()


def nivel_4():
    return ST.pontos


def ciclo(n):
    if n > 99:
        return ciclo(n - 1)
    return ST.pontos


class Caixa:
    pass


class Painel:
    def __init__(self, alvo):
        self.alvo = alvo

    def texto(self):
        return self.alvo.value * 3


def fresh_state():
    global ST
    ST = State(name="formula_functions")
    ST.vidas = 3
    ST.morto = False
    ST.pontos = 0


class FormulaFunctionTest(unittest.TestCase):
    def setUp(self):
        fresh_state()


class TestNamedFunction(FormulaFunctionTest):
    def test_def_tracks_every_branch(self):
        def texto():
            if ST.morto:
                return "fim"
            return f"vidas {ST.vidas}"

        sink = Attribute("")
        sink @= texto
        self.assertEqual(sink.value, "vidas 3")
        ST.vidas = 2
        self.assertEqual(sink.value, "vidas 2")
        ST.morto = True
        self.assertEqual(sink.value, "fim")

    def test_local_assignment_source_is_recorded(self):
        a = Attribute(2.0)

        def dobro():
            x = a.value
            return x * 2

        sink = Attribute(0.0)
        sink @= dobro
        self.assertEqual(sink.value, 4.0)
        a.value = 5.0
        self.assertEqual(sink.value, 10.0)

    def test_default_arg_capture_still_works(self):
        def texto(s=ST):
            return s.vidas * 10

        sink = Attribute(0)
        sink @= texto
        ST.vidas = 4
        self.assertEqual(sink.value, 40)

    def test_bound_method_sees_its_receiver(self):
        a = Attribute(2.0)
        painel = Painel(a)
        sink = Attribute(0.0)
        sink @= painel.texto
        self.assertEqual(sink.value, 6.0)
        a.value = 3.0
        self.assertEqual(sink.value, 9.0)


class TestHelpers(FormulaFunctionTest):
    def test_lambda_calling_helper_links(self):
        sink = Attribute("")
        sink @= lambda: rotulo()
        ST.vidas = 1
        self.assertEqual(sink.value, "vidas 1")

    def test_helpers_three_levels_deep_are_followed(self):
        sink = Attribute(0)
        sink @= nivel_1
        ST.pontos = 7
        self.assertEqual(sink.value, 7)

    def test_helpers_four_levels_deep_refuse(self):
        sink = Attribute(0)
        with self.assertRaises(TypeError) as ctx:
            sink @= nivel_0
        self.assertIn("levels deep", str(ctx.exception))
        self.assertIsNone(sink._link)

    def test_recursive_helper_is_read_once(self):
        sink = Attribute(0)
        sink @= lambda: ciclo(0)
        ST.pontos = 5
        self.assertEqual(sink.value, 5)


class TestAllowedCalls(FormulaFunctionTest):
    def test_builtins_scena_helpers_stdlib_and_methods(self):
        a = Attribute(1.0)
        p = Point(3, 4)
        sink = Attribute(0.0)
        sink @= lambda: round(min(a.value, 9) + lerp(0, 2, 0.5) + math.sin(0) + p.distance((0, 0)), 3)
        self.assertAlmostEqual(sink.value, 7.0)
        a.value = 2.0
        self.assertAlmostEqual(sink.value, 8.0)

    def test_stdlib_python_function_allowed(self):
        sink = Attribute("")
        sink @= lambda: json.dumps(f"{ST.vidas}")
        ST.vidas = 8
        self.assertEqual(sink.value, "\"8\"")

    def test_constant_index_into_scena_objects_allowed(self):
        items = [Attribute(1.0), Attribute(2.0)]
        sink = Attribute(0.0)
        sink @= lambda: items[-1].value
        items[-1].value = 6.0
        self.assertEqual(sink.value, 6.0)


class TestRefusals(FormulaFunctionTest):
    def assertRefused(self, formula, needle, error=TypeError):
        sink = Attribute(0)
        with self.assertRaises(error) as ctx:
            sink @= formula
        self.assertIn(needle, str(ctx.exception))
        self.assertIsNone(sink._link)
        return str(ctx.exception)

    def test_for_loop(self):
        def total():
            t = 0
            for _ in range(3):
                t = t + ST.pontos
            return t

        msg = self.assertRefused(total, "for loop")
        self.assertIn("update()", msg)

    def test_while_loop(self):
        def total():
            while ST.pontos > 100:
                return 1
            return ST.pontos

        self.assertRefused(total, "while loop")

    def test_comprehension(self):
        self.assertRefused(lambda: sum(ST.pontos for _ in range(2)), "comprehension")

    def test_write_inside_formula(self):
        a = Attribute(1.0)

        def escreve():
            a.value = 2.0
            return ST.pontos

        self.assertRefused(escreve, "writes")

    def test_global(self):
        def g():
            global ST
            return ST.pontos

        self.assertRefused(g, "global")

    def test_nested_def(self):
        def f():
            def dentro():
                return 1
            return ST.pontos + dentro()

        self.assertRefused(f, "defines a function")

    def test_lambda_inside(self):
        def f():
            g = lambda: 1  # noqa: E731
            return ST.pontos + g()

        self.assertRefused(f, "lambda inside")

    def test_try(self):
        def f():
            try:
                return ST.pontos
            except Exception:
                return 0

        self.assertRefused(f, "try")

    def test_getattr_on_plain_object(self):
        painel = Painel(Attribute(1.0))
        self.assertRefused(lambda: getattr(painel, "alvo").value + ST.pontos, "getattr")

    def test_call_to_local_value(self):
        def f():
            g = rotulo
            return g()

        self.assertRefused(f, "local value")

    def test_call_to_other_module(self):
        self.assertRefused(lambda: new_state(a=ST.pontos), "new_state")

    def test_author_class_construction(self):
        self.assertRefused(lambda: (Caixa(), ST.pontos), "creates a Caixa")

    def test_group_read(self):
        self.assertRefused(lambda: len(group["formula_functions_x"]) + ST.pontos, "reads a group")

    def test_variable_index_into_scena_objects(self):
        items = [Attribute(1.0), Attribute(2.0)]
        self.assertRefused(lambda: items[ST.pontos].value, "changing index")

    def test_missing_field_is_an_error_not_a_warning(self):
        p = Point(1, 2)
        # The object's own AttributeError, at link time — not a warning.
        self.assertRefused(lambda: p.nao_existe + ST.pontos, "nao_existe", AttributeError)

    def test_getattr_on_scena_object_allowed(self):
        p = Point(1, 2)
        sink = Attribute(0.0)
        sink @= (lambda s=p, nome="x": getattr(s, nome) * 2)
        p.x = 5
        self.assertEqual(sink.value, 10)

    def test_plain_python_write_allowed(self):
        calls = {"n": 0}

        def conta():
            calls["n"] += 1
            return ST.pontos

        sink = Attribute(0)
        sink @= conta
        ST.pontos = 4
        self.assertEqual(sink.value, 4)
        self.assertGreaterEqual(calls["n"], 2)


class TestParseCache(unittest.TestCase):
    def test_same_lambda_linked_many_times_parses_once(self):
        formula_check.clear_formula_caches()
        cells = [Attribute(float(i)) for i in range(50)]
        sinks = [Attribute(0.0) for _ in range(50)]
        with mock.patch.object(formula_check.ast, "parse", wraps=ast.parse) as parse:
            for cell, sink in zip(cells, sinks):
                sink @= (lambda c=cell: c.value * 2)
        self.assertEqual(parse.call_count, 1)
        cells[7].value = 10.0
        self.assertEqual(sinks[7].value, 20.0)

    def test_named_function_without_source_explains(self):
        ns = {}
        exec("def f():\n    return 1\n", ns)
        sink = Attribute(0)
        with self.assertRaises(TypeError) as ctx:
            sink @= ns["f"]
        self.assertIn("source", str(ctx.exception))


class TestStaleSourceFile(FormulaFunctionTest):
    """Bug PM14: the @= checker read a formula's sources from the script file
    on disk. Edited and saved while the program runs, the file no longer
    matched the running code: a formula built afterwards was looked up at
    stale positions -> "no reactive sources" (misleading) or another
    lambda's names. Now a located node is checked against the code object;
    a mismatch falls back to the code itself (exact for lambdas), and an
    error that remains says the file changed on disk."""

    SRC = (
        "from scena import Circle\n"
        "a = Circle(center=(0, 0), radius=5)\n"
        "b = Circle(center=(0, 0), radius=1)\n"
        "def later():\n"
        "    b['radius'] @= lambda: a.radius * 2\n"
        "def nome():\n"
        "    return a.radius + 1\n"
    )
    EDITED = (
        "from scena import Circle\n"
        "a = Circle(center=(0, 0), radius=5)\n"
        "b = Circle(center=(0, 0), radius=1)\n"
        "TOTAL = 3\n"
        "def later():\n"
        "    b['radius'] @= lambda: TOTAL * 2\n"
        "def nome():\n"
        "    return TOTAL\n"
    )

    def _load(self, src):
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "jogo_pm14.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        ns = {"__name__": "jogo_pm14", "__file__": path}
        exec(compile(src, path, "exec"), ns)
        formula_check.clear_formula_caches()
        return path, ns

    def _edit(self, path, src):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        st_ = os.stat(path)
        os.utime(path, (st_.st_atime, st_.st_mtime + 5))

    # A different lambda now sits on the running lambda's line (line 5).
    SAME_LINE = (
        "from scena import Circle\n"
        "a = Circle(center=(0, 0), radius=5)\n"
        "TOTAL = 3\n"
        "def later():\n"
        "    b['radius'] @= lambda: TOTAL * 2\n"
    )

    def test_lambda_after_an_edit_links_the_running_code(self):
        path, ns = self._load(self.SRC)
        self._edit(path, self.SAME_LINE)
        a, b = ns["a"], ns["b"]
        try:
            ns["later"]()                      # the running code reads a.radius
            self.assertEqual(float(b.radius), 10.0)
            a.radius = 7
            self.assertEqual(float(b.radius), 14.0)
        finally:
            for o in (a, b):
                o.destroy()

    def test_named_function_after_an_edit_says_the_file_changed(self):
        path, ns = self._load(self.SRC)
        self._edit(path, "\n\n" + self.EDITED)
        a, b = ns["a"], ns["b"]
        try:
            with self.assertRaises(TypeError) as ctx:
                b["radius"] @= ns["nome"]
            self.assertIn("changed on disk", str(ctx.exception))
        finally:
            for o in (a, b):
                o.destroy()


if __name__ == "__main__":
    unittest.main()
