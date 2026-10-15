"""box=<formula>: a shape whose region is a formula follows it (box-linked).

``Rect(box=lambda: hero.box.beside("right"))`` is the box= fit, done again
whenever the formula's sources change: one evaluation per change, the shape's
inputs read the fitted values, verbs refuse like on any linked input, and the
relation goes as a whole (no hybrid). Box Design, "Fit"; Shapes Design,
"Cross-shape relational constructors".

Run headless:

    python -m unittest tests.test_box_formula -v
"""
import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scena  # noqa: E402
from scena import (  # noqa: E402
    Box, Circle, Concave, Ellipse, Rect, RegularPolygon, Square, Text, Triangle,
    canvas, init,
)
from scena.box import BOX_FORMULA_KINDS  # noqa: E402
from scena.scenamath import Vec2  # noqa: E402
from scena.shapes import Point, Shape  # noqa: E402
from scena.state import LinkedAttributeError  # noqa: E402


# One builder per kind and per box= family variant. Keys are labels; the
# first word is the class name (TestEveryBoxKindTakesAFormula checks it).
BUILDERS = {
    "Rect": lambda region: Rect(box=region),
    "Square": lambda region: Square(box=region),
    "Square length": lambda region: Square(box=region, length=7),
    "Concave": lambda region: Concave(box=region, scoop="top_left"),
    "Ellipse": lambda region: Ellipse(box=region),
    "Circle": lambda region: Circle(box=region),
    "Circle radius": lambda region: Circle(box=region, radius=3),
    "RegularPolygon": lambda region: RegularPolygon(n=6, box=region),
    "RegularPolygon radius": lambda region: RegularPolygon(n=5, box=region, radius=4),
    "Triangle": lambda region: Triangle(box=region),
    "Triangle ratio": lambda region: Triangle(box=region, base_ratio=0.5),
    "Triangle side": lambda region: Triangle(box=region, side=9),
}


def _inputs(shape):
    """Every Defining input as plain numbers, plus the names it took."""
    out = {}
    for name in shape.__dict__.get('_defining_part_names') or ():
        value = getattr(shape, name)
        if isinstance(value, (Point, Vec2)):
            out[name] = (float(value.x), float(value.y))
        else:
            out[name] = float(value)
    out['_names'] = shape.__dict__.get('_name_signs')
    return out


class BoxFormulaCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        self._owned = []

    def tearDown(self):
        for s in reversed(self._owned):
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()

    def own(self, obj):
        self._owned.append(obj)
        return obj

    def assertSameInputs(self, a, b, msg=""):
        ia, ib = _inputs(a), _inputs(b)
        self.assertEqual(set(ia), set(ib), msg)
        for k in ia:
            va, vb = ia[k], ib[k]
            if isinstance(va, tuple) and va and isinstance(va[0], float):
                for x, y in zip(va, vb):
                    self.assertAlmostEqual(x, y, places=6, msg=f"{msg} {k}")
            elif isinstance(va, float):
                self.assertAlmostEqual(va, vb, places=6, msg=f"{msg} {k}")
            else:
                self.assertEqual(va, vb, f"{msg} {k}")


class TestEveryBoxKindTakesAFormula(BoxFormulaCase):
    """Bug class: a kind that takes box= but not box=<formula>."""

    def test_builders_cover_every_box_kind(self):
        region = Box(center=(0, 0), width=20, height=10)
        takes_box = set()
        for name in scena.__all__:
            cls = getattr(scena, name)
            if not (isinstance(cls, type) and issubclass(cls, Shape)):
                continue
            try:
                kw = {'n': 6} if cls is RegularPolygon else {}
                self.own(cls(box=region, **kw))
            except TypeError:
                continue
            takes_box.add(name)
        self.assertEqual(takes_box, set(BOX_FORMULA_KINDS))
        self.assertEqual({k.split()[0] for k in BUILDERS}, set(BOX_FORMULA_KINDS))


class TestFollowsTheRegion(BoxFormulaCase):
    """A box-linked shape always equals the same kind built from the region now."""

    def test_every_kind_matches_a_fresh_fit(self):
        for label, build in BUILDERS.items():
            with self.subTest(kind=label):
                hero = self.own(Rect(center=(100, 100), width=40, height=20, angle=10))
                region = lambda: hero.box.beside("right", gap=5)  # noqa: E731
                shape = self.own(build(region))
                steps = (
                    lambda: hero.move_by(30, -12),
                    lambda: setattr(hero, 'width', 70),
                    lambda: hero.rotate_by(35),
                    lambda: setattr(hero, 'height', 3),
                    lambda: hero.move_to(-50, 400),
                )
                self.assertSameInputs(shape, self.own(build(region())), label)
                for step in steps:
                    step()
                    self.assertSameInputs(shape, self.own(build(region())), label)

    def test_explicit_size_stays_the_authors(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        c = self.own(Circle(box=lambda: hero.box, radius=3))
        hero.move_by(10, 5)
        self.assertEqual((c.center.x, c.center.y), (10.0, 5.0))
        c.radius = 8                       # not linked: the author's to write
        hero.width = 100
        self.assertEqual(c.radius, 8.0)

    def test_a_graphic_as_the_region(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        e = self.own(Ellipse(box=lambda: hero))
        hero.move_by(7, 0)
        hero.width = 60
        self.assertEqual((e.center.x, e.width, e.height), (7.0, 60.0, 20.0))

    def test_camera_region(self):
        bar = self.own(Rect(box=lambda: canvas.game_view.strip("top", 40)))
        canvas.pan_to(300, 200)
        self.assertSameInputs(bar, self.own(Rect(box=canvas.game_view.strip("top", 40))))

    def test_state_cell_selects_the_cell(self):
        st = scena.State(name="box_formula_test")
        st.i = 0
        cells = Box(center=(0, 0), width=300, height=100).grid(3, 1)
        dot = self.own(Circle(box=lambda: cells.cell(st.i)))
        st.i = 2
        self.assertAlmostEqual(dot.center.x, cells.cell(2).center.x)


calls = {"n": 0}


class TestOneEvaluationPerChange(BoxFormulaCase):
    def test_the_formula_runs_once_per_change(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20, angle=5))

        def region():
            calls["n"] += 1
            return hero.box.inset(2)

        for label, build in BUILDERS.items():
            with self.subTest(kind=label):
                shape = self.own(build(region))
                hero.move_by(1, 0)
                n0 = calls["n"]
                _inputs(shape)              # reads every fitted input
                _inputs(shape)
                self.assertEqual(calls["n"] - n0, 1, label)


class TestNoGraphGrowth(BoxFormulaCase):
    """A per-frame change must not leave nodes behind (class D11: a measured
    Box built inside the formula stays off the graph). Counted with the
    cyclic GC off, so refcounting alone must keep the graph flat."""

    def test_changes_keep_the_graph_flat(self):
        from tests.graph_support import full_collect, gc_paused
        from scena.state import get_scena_system
        self.enterContext(gc_paused())
        full_collect()
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        shapes = [self.own(build(lambda: hero.box.beside("top").inset(1)))
                  for build in BUILDERS.values()]
        graph = get_scena_system().dependency_graph

        def frame():
            hero.move_by(1, 1)
            for s in shapes:
                _inputs(s)

        frame()
        before = len(graph.nodes)
        for _ in range(30):
            frame()
        self.assertEqual(len(graph.nodes), before)


class TestTheRelationGoesAsAWhole(BoxFormulaCase):
    def _fitted_links(self, shape):
        fit = shape.__dict__.get('_box_fit')
        return [n for n in shape._iter_subtree()
                if n._link is not None and fit is not None
                and fit in n._link.sources]

    def assertFree(self, shape):
        self.assertIsNone(shape.__dict__.get('_box_fit'))
        self.assertEqual(
            [n for n in shape._iter_subtree() if n._link is not None], [])

    def test_verbs_refuse_naming_box(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        r = self.own(Rect(box=lambda: hero.box))
        for verb in (lambda: r.move_by(5, 0), lambda: r.rotate_by(10),
                     lambda: r.scale_by(2), lambda: setattr(r, 'flip_x', True)):
            with self.assertRaises(LinkedAttributeError) as cm:
                verb()
            self.assertIn("follows its box= formula", str(cm.exception))
        c = self.own(Circle(box=lambda: hero.box))
        c.rotate_by(30)                     # its angle is the arc, not fitted
        self.assertIsNotNone(c.__dict__.get('_box_fit'))

    def test_force_frees_and_keeps_values(self):
        for label, build in BUILDERS.items():
            with self.subTest(kind=label):
                hero = self.own(Rect(center=(0, 0), width=40, height=20))
                shape = self.own(build(lambda: hero.box))
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    shape.move_by(5, 0, force=True)
                self.assertFree(shape)
                before = _inputs(shape)
                hero.move_by(50, 50)
                self.assertEqual(_inputs(shape), before)

    def test_unlinking_one_input_frees_all(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        e = self.own(Ellipse(box=lambda: hero.box))
        e.center.unlink()
        self.assertFree(e)
        e.move_by(3, 0)                     # a free shape: verbs work
        self.assertEqual(e.center.x, 3.0)

    def test_unlink_all_frees(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        sq = self.own(Square(box=lambda: hero.box))
        sq.unlink_all()
        self.assertFree(sq)

    def test_source_destroyed_frees_with_last_values(self):
        hero = Rect(center=(0, 0), width=40, height=20)
        c = self.own(Circle(box=lambda: hero.box))
        hero.move_by(11, 0)
        node = c.__dict__['_box_fit']
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            hero.destroy()
        self.assertFree(c)
        self.assertIsNone(node._link)
        self.assertEqual(c.center.x, 11.0)
        msgs = [str(w.message) for w in caught]
        self.assertEqual(sum("Circle.box" in m for m in msgs), 1, msgs)
        c.move_by(1, 0)
        self.assertEqual(c.center.x, 12.0)

    def test_shape_destroyed_lets_go_of_the_source(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        r = Rect(box=lambda: hero.box.outset(4))
        node = r.__dict__['_box_fit']
        r.destroy()
        self.assertIsNone(node._link)
        ss = hero._scena_system
        nid = getattr(node, '_node_id', None)
        if nid is not None:
            self.assertEqual(ss.dependency_graph.dependencies.get(nid, set()), set())

    def test_a_copy_is_free(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        r = self.own(Rect(box=lambda: hero.box))
        c = self.own(r.clone())
        self.assertFree(c)
        other = self.own(Rect(center=(5, 5), width=1, height=1))
        other << r
        self.assertFree(other)


class TestRefusals(BoxFormulaCase):
    def test_a_region_that_is_not_a_frame(self):
        with self.assertRaises(TypeError):
            Rect(box=lambda: 5 + scena.clock.time * 0)

    def test_mixing_raises_at_construction(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        with self.assertRaisesRegex(TypeError, "cannot mix"):
            Rect(box=lambda: hero.box, width=3)

    def test_a_formula_with_no_sources(self):
        with self.assertRaisesRegex(TypeError, "no reactive sources"):
            Rect(box=lambda: Box(center=(0, 0), width=3, height=3))

    def test_kinds_without_formula_name_the_ones_with(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        with self.assertRaisesRegex(TypeError, "only by a shape's box="):
            Text("hi", box=lambda: hero.box)
        with self.assertRaisesRegex(TypeError, "only by a shape's box="):
            hero.confine(lambda: hero.box)


if __name__ == "__main__":
    unittest.main()
