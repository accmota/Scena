"""
A test module destroys what its tests made (tests/leftovers.py).

Isolation hygiene (Testing Design, "Harness pitfalls"): Scena keeps one canvas
per process, so actors a module leaves alive sit on the draw lists of every
later module in the deep tier's serial pass. ``test_shapes`` left ~720 drawn
(1905 roster items), ``test_reactive_matrix`` ~25 700. ``module_sweep`` destroys
what a module registered; ``tests/run_tiers.py`` runs a ``LeftoverCheck`` after
every module of every tier: one live actor a module made fails it (WP43).

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

    def test_the_canvas_boundary_rect_is_the_canvas_s(self):
        # A replaced canvas counts whole, but its own ``canvas_rect`` is not
        # what a module left, and ``sweep`` (which destroys ``made_since``)
        # would have destroyed it (WP43: test_readme and 13 more "left 1 Rect").
        from scena.canvas import ScenaCanvas
        own = ScenaCanvas.get_current().canvas_rect
        at = (object(), 0)                          # every key on the registry is newer
        self.assertTrue(own.is_alive)
        self.assertNotIn(own, leftovers.made_since(at))

    def test_a_framework_singleton_is_the_framework_s(self):
        # The HUD labels the first begin_game builds (once per process) are
        # marked _scena_internal: they were "2 Text" of whichever module
        # began a game first (WP43), and a sweep would destroy them.
        at = leftovers.mark()
        label = Circle(center=(20, 20), radius=5)
        self.addCleanup(label.destroy)
        object.__setattr__(label, "_scena_internal", True)
        self.assertNotIn(label, leftovers.made_since(at))
        leftovers.sweep(at)
        self.assertTrue(label.is_alive)


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
                KEEP.extend(Circle(center=(i, i), radius=2{group}) for i in range({n}))
    """

    def _run(self, n, sweep, group=None):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        line = ("from tests.leftovers import module_sweep\n"
                "        setUpModule, tearDownModule = module_sweep()") if sweep else ""
        with open(os.path.join(tmp, "leaky_mod.py"), "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(self.BODY.format(
                sweep=line, n=n, group=f", group={group!r}" if group else "")))
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

    def test_one_untagged_leftover_fails(self):
        """A later test that counts a kind on the roster counts it: test_diff_pose's
        26 untagged actors (under the old limit of 50) read as string_theory's
        strings in the deep serial pass (2026-10-24, WP42, WP43)."""
        res, log = self._run(1, sweep=False)
        self.assertFalse(res.ok, log)
        self.assertIn("left 1 live actors (1 Circle; Circle made at leaky_mod.py:", log)
        res, log = self._run(1, sweep=True)
        self.assertTrue(res.ok, log)

    def test_lazy_parts_of_an_import_time_actor_are_tolerated(self):
        """An actor made at import is the module's fixture (made before the
        mark); a test that links to its center fills its foci, two parts made
        after the mark, which leave with it."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        with open(os.path.join(tmp, "fixture_mod.py"), "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent("""
                import unittest
                from tests.leftovers import module_sweep
                from scena import Ellipse
                SHUTTLE = Ellipse(center=(50, 50), width=40, height=10)
                setUpModule, tearDownModule = module_sweep()

                class T(unittest.TestCase):
                    def test_links(self):
                        Ellipse(center=lambda: SHUTTLE.center, width=4, height=2)
            """))
        runner = rt.Runner(os.path.join(tmp, "logs"), timeout=120, workers=1,
                           stream=io.StringIO())
        (res,) = runner.run([rt.Job("fixture", ["fixture_mod"], {"PYTHONPATH": tmp})])
        with open(res.log, encoding="utf-8") as fh:
            log = fh.read()
        self.assertTrue(res.ok, log)

    def test_one_tagged_leftover_fails(self):
        """A group name is process-wide: one leftover ``group="heroi"`` answered
        every later game's ``group["heroi"]`` and moved bodies under every
        later ``resolve`` on its name (deep serial pass 2026-10-22)."""
        res, log = self._run(1, sweep=False, group="heroi")
        self.assertFalse(res.ok, log)
        self.assertIn("with a group", log)
        self.assertIn("'heroi'", log)
        res, log = self._run(1, sweep=True, group="heroi")
        self.assertTrue(res.ok, log)


if __name__ == "__main__":
    unittest.main()
