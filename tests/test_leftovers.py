"""
A test module destroys what its tests made (tests/leftovers.py).

Isolation hygiene (Testing Design, "Harness pitfalls"): Scena keeps one canvas
per process, so actors a module leaves alive sit on the draw lists of every
later module in the deep tier's serial pass. ``test_shapes`` left ~720 drawn
(1905 roster items), ``test_reactive_matrix`` ~25 700. ``module_sweep`` destroys
what a module registered; ``tests/run_tiers.py`` runs a ``LeftoverCheck`` after
every module of every tier.

Run headless:

    python -m unittest tests.test_leftovers -v
"""

import io
import os
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from hypothesis_support import boot, registry  # noqa: E402
from scena import Circle, Line, Polygon  # noqa: E402
from scena.entity import is_part  # noqa: E402
from tests import leftovers  # noqa: E402
from tests.test_run_tiers import rt  # noqa: E402


class TestSweep(unittest.TestCase):
    def setUp(self):
        boot()

    def test_destroys_what_came_after_the_mark_and_only_that(self):
        before = Circle(center=(10, 10), radius=5)
        self.addCleanup(before.destroy)
        at = leftovers.mark()
        made = [Circle(center=(20, 20), radius=5), Line(p1=(0, 0), p2=(10, 10)),
                Polygon(points=[(0, 0), (10, 0), (5, 8)])]
        parts = [p for p in leftovers.made_since(at) if is_part(p)]
        self.assertTrue(parts)                      # vertex / end / center Points
        leftovers.sweep(at)
        self.assertTrue(before.is_alive)
        self.assertFalse(any(o.is_alive for o in made))
        self.assertEqual(leftovers.made_since(at), [])  # the parts left with their owners

    def test_on_destroy_does_not_run(self):
        # A handler could spawn: the sweep must not leave what it caused.
        at = leftovers.mark()
        c = Circle(center=(20, 20), radius=5)
        c.on_destroy = lambda: Circle(center=(1, 1), radius=1)
        leftovers.sweep(at)
        self.assertEqual(leftovers.made_since(at), [])

    def test_module_hooks(self):
        set_up, tear_down = leftovers.module_sweep()
        set_up()
        c = Circle(center=(20, 20), radius=5)
        tear_down()
        self.assertFalse(c.is_alive)

    def test_a_replaced_canvas_counts_whole(self):
        at = (object(), registry()._next_key)       # a mark taken on another registry
        c = Circle(center=(20, 20), radius=5)
        self.addCleanup(c.destroy)
        self.assertIn(c, leftovers.made_since(at))


class TestChecksBetweenModules(unittest.TestCase):
    """``run_tiers.with_leftover_checks``: one check after each module."""

    @staticmethod
    def _suite(module, n=1):
        cls = type("T", (unittest.TestCase,), {"test_a": lambda self: None,
                                               "__module__": module})
        return unittest.TestSuite([cls("test_a") for _ in range(n)])

    def test_one_check_per_run_of_a_module(self):
        suites = [self._suite("m1"), self._suite("m1"), self._suite("m2"),
                  unittest.TestSuite(), self._suite("m1")]
        out = rt.with_leftover_checks(
            suites, lambda m: unittest.FunctionTestCase(lambda: None, description=f"check:{m}"))
        flat = [t.shortDescription() if isinstance(t, unittest.FunctionTestCase)
                else type(t._tests[0]).__module__ if t._tests else "empty" for t in out]
        self.assertEqual(flat, ["m1", "m1", "check:m1", "m2", "empty",
                                "check:m2", "m1", "check:m1"])

    def test_nothing_loaded(self):
        self.assertEqual(list(rt.with_leftover_checks([], str)), [])


class TestChildRun(unittest.TestCase):
    """Real child processes (``run_tiers.py --child``) on a module that leaks."""

    BODY = """
        import unittest
        from scena import Circle, init
        {sweep}
        KEEP = []

        class T(unittest.TestCase):
            def test_makes(self):
                init(width=100, height=100)
                KEEP.extend(Circle(center=(i, i), radius=2) for i in range({n}))
    """

    def _run(self, n, sweep):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        line = ("from tests.leftovers import module_sweep\n"
                "        setUpModule, tearDownModule = module_sweep()") if sweep else ""
        with open(os.path.join(tmp, "leaky_mod.py"), "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(self.BODY.format(sweep=line, n=n)))
        runner = rt.Runner(os.path.join(tmp, "logs"), timeout=120, workers=1,
                           stream=io.StringIO())
        (res,) = runner.run([rt.Job("leaky", ["leaky_mod"], {"PYTHONPATH": tmp})])
        with open(res.log, encoding="utf-8") as fh:
            return res, fh.read()

    def test_a_module_over_the_limit_fails_and_names_what_it_left(self):
        res, log = self._run(leftovers.LIMIT + 10, sweep=False)
        self.assertFalse(res.ok, log)
        self.assertIn("leftovers of leaky_mod", log)
        self.assertIn(f"{leftovers.LIMIT + 10} Circle", log)
        self.assertEqual(res.ran, 1)                # the check is not one of its tests

    def test_the_sweep_passes_it(self):
        res, log = self._run(leftovers.LIMIT + 10, sweep=True)
        self.assertTrue(res.ok, log)
        self.assertEqual(res.ran, 1)

    def test_a_few_are_tolerated(self):
        res, log = self._run(3, sweep=False)
        self.assertTrue(res.ok, log)


if __name__ == "__main__":
    unittest.main()
