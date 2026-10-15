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
    Box, Circle, Concave, Ellipse, Rect, RegularPolygon, Sprite, SpriteButton,
    Square, Svg, Text, Triangle, canvas, init,
)
from scena.box import BOX_FORMULA_KINDS  # noqa: E402
from scena.scenamath import Vec2  # noqa: E402
from scena.box import region_frame  # noqa: E402
from scena.entity import Graphic  # noqa: E402
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


_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="20">'
        '<rect width="10" height="20"/></svg>')
_PNG = "missing_box_formula.png"     # the placeholder art: 10 × 10 px

# The Sprite family: ``box=`` contains (keeps the art's aspect).
SPRITE_BUILDERS = {
    "Sprite": lambda region: Sprite(_PNG, box=region),
    "Sprite flipped": lambda region: Sprite(_PNG, box=region, flip_x=True),
    "Sprite art_angle": lambda region: Sprite(_PNG, box=region, art_angle=90),
    "Sprite height": lambda region: Sprite(_PNG, box=region, height=6),
    "Sprite angle": lambda region: Sprite(_PNG, box=region, angle=15),
    "Svg": lambda region: Svg(_SVG, box=region),
    "SpriteButton": lambda region: SpriteButton(_PNG, box=region),
}


def _frame(g):
    """What is drawn, through the public measure (pulls linked pose)."""
    cx, cy, w, h, ang = region_frame(g)
    return (cx, cy, w, h, ang % 360.0)


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
            if not (isinstance(cls, type) and issubclass(cls, Graphic)):
                continue
            try:
                kw = {'n': 6} if cls is RegularPolygon else {}
                self.own(cls(box=region, **kw))
            except TypeError:
                continue
            takes_box.add(name)
        # Text takes box= but not a formula (its width is layout): it refuses.
        self.assertEqual(takes_box, set(BOX_FORMULA_KINDS) | {"Text"})
        built = {k.split()[0] for k in BUILDERS} | {k.split()[0] for k in SPRITE_BUILDERS}
        self.assertEqual(built, set(BOX_FORMULA_KINDS))


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


class TestSpriteFollowsTheRegion(BoxFormulaCase):
    """A box-linked Sprite / Svg draws where the same kind built from the
    region now draws: center, size (by the pose scale) and heading."""

    def assertSameFrame(self, a, b, msg=""):
        fa, fb = _frame(a), _frame(b)
        for x, y in zip(fa, fb):
            self.assertAlmostEqual(x, y, places=5, msg=f"{msg}: {fa} vs {fb}")
        self.assertAlmostEqual(float(a.angle) % 360.0, float(b.angle) % 360.0,
                               places=5, msg=msg)

    def test_every_sprite_kind_matches_a_fresh_fit(self):
        for label, build in SPRITE_BUILDERS.items():
            with self.subTest(kind=label):
                hero = self.own(Rect(center=(100, 100), width=40, height=20, angle=10))
                region = lambda: hero.box.beside("right", gap=5)  # noqa: E731
                sprite = self.own(build(region))
                steps = (
                    lambda: hero.move_by(30, -12),
                    lambda: setattr(hero, 'width', 70),
                    lambda: hero.rotate_by(35),
                    lambda: setattr(hero, 'height', 3),
                )
                self.assertSameFrame(sprite, self.own(build(region())), label)
                for step in steps:
                    step()
                    self.assertSameFrame(sprite, self.own(build(region())), label)

    def test_the_size_is_the_pose_scale(self):
        """width / height (the size per pixel the hitbox bake keys on) stay
        as built; the region's growth is the pose scale."""
        hero = self.own(Rect(center=(0, 0), width=40, height=40))
        s = self.own(Sprite(_PNG, box=lambda: hero.box))
        size0 = (s.width, s.height, s._du_per_px())
        hero.width = hero.height = 120
        self.assertAlmostEqual(s.scale, 3.0)
        self.assertEqual((s.width, s.height, s._du_per_px()), size0)
        self.assertAlmostEqual(s.box.height, 120.0)
        self.assertTrue(s.contains_point(50, 50))     # the hit area grew too

    def test_a_collapsed_first_region_grows(self):
        hero = self.own(Rect(center=(0, 0), width=0, height=0))
        s = self.own(Sprite(_PNG, box=lambda: hero.box))
        self.assertAlmostEqual(s.box.height, 0.0)
        hero.width = hero.height = 30
        self.assertAlmostEqual(s.box.height, 30.0)

    def test_explicit_size_and_angle_stay_the_authors(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20, angle=20))
        h = self.own(Sprite(_PNG, box=lambda: hero.box, height=6))
        hero.move_by(5, 0)
        self.assertAlmostEqual(h.center.x, 5.0)
        h.scale_to(2)                       # not linked: the author's
        h.rotate_to(45)
        a = self.own(Sprite(_PNG, box=lambda: hero.box, angle=15))
        hero.rotate_by(30)
        self.assertAlmostEqual(float(a.angle), 15.0)
        a.rotate_to(60)

    def test_one_evaluation_per_change(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20, angle=5))

        def region():
            calls["n"] += 1
            return hero.box.inset(2)

        for label, build in SPRITE_BUILDERS.items():
            with self.subTest(kind=label):
                s = self.own(build(region))
                hero.move_by(1, 0)
                n0 = calls["n"]
                _frame(s)
                _frame(s)
                self.assertEqual(calls["n"] - n0, 1, label)

    def test_the_relation_goes_as_a_whole(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        for undo in ("scale", "angle", "center", "force", "source"):
            with self.subTest(undo=undo):
                src = Rect(center=(0, 0), width=40, height=20) if undo == "source" else hero
                s = self.own(Sprite(_PNG, box=lambda: src.box))
                with self.assertRaisesRegex(LinkedAttributeError, "follows its box= formula"):
                    s.move_by(1, 0)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    if undo == "force":
                        s.rotate_by(10, force=True)
                    elif undo == "source":
                        src.destroy()
                    elif undo == "center":
                        s.center.unlink()
                    else:
                        s[undo].unlink()
                self.assertIsNone(s.__dict__.get('_box_fit'))
                anchors = s.__dict__.get('_field_anchors') or {}
                self.assertEqual(
                    [n for n in [*s._iter_subtree(), *anchors.values()] if n._link is not None], [])
                s.move_by(1, 0)             # free: verbs work

    def test_destroy_lets_go_of_the_source(self):
        hero = self.own(Rect(center=(0, 0), width=40, height=20))
        s = Svg(_SVG, box=lambda: hero.box)
        node = s.__dict__['_box_fit']
        s.destroy()
        self.assertIsNone(node._link)


class TestSpriteBoxHeading(BoxFormulaCase):
    """SF1: a Sprite placed by box= in a turned region draws turned by the
    region's angle, whatever its flips and art_angle. The region angle was
    written as the heading, so a flipped sprite (rest heading 180) drew
    upside down unless the angle was exactly 0. Class: turning the region
    turns the result (equivariance), including across 0."""

    def test_turning_the_region_turns_the_sprite(self):
        base = dict(center=(30, -20), width=60, height=24)
        for flips in ({}, {"flip_x": True}, {"flip_y": True},
                      {"flip_x": True, "flip_y": True}):
            for art in (0, 90, -30):
                s0 = self.own(Sprite(_PNG, box=Box(**base), art_angle=art, **flips))
                for a in (1e-6, 30.0, -90.0, 180.0):
                    with self.subTest(flips=flips, art=art, angle=a):
                        sa = self.own(Sprite(_PNG, box=Box(angle=a, **base),
                                             art_angle=art, **flips))
                        ca = math.cos(math.radians(a))
                        sn = math.sin(math.radians(a))
                        for name in ("top_center", "right_center"):
                            x0, y0 = getattr(s0.box, name)
                            dx, dy = x0 - 30, y0 + 20
                            want = (30 + dx * ca - dy * sn, -20 + dx * sn + dy * ca)
                            gx, gy = getattr(sa.box, name)
                            self.assertAlmostEqual(gx, want[0], places=4)
                            self.assertAlmostEqual(gy, want[1], places=4)


class TestSvgBoxRaster(BoxFormulaCase):
    """SF2: Svg(box=) rasterized at the 128 default whatever the region, and
    drew a big box blurred. It rasters like Svg(height=) of the same size."""

    def test_box_rasters_at_the_region_size(self):
        big = Box(center=(0, 0), width=400, height=400)
        for region in (big, lambda: big):
            boxed = self.own(Svg(_SVG, box=region))
            sized = self.own(Svg(_SVG, center=(0, 0), height=boxed.height))
            fb, fs = boxed._sheet._frame_at(0), sized._sheet._frame_at(0)
            self.assertEqual((fb.src_w, fb.src_h), (fs.src_w, fs.src_h))


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
        with self.assertRaisesRegex(TypeError, "only by box= on"):
            Text("hi", box=lambda: hero.box)
        with self.assertRaisesRegex(TypeError, "only by box= on"):
            hero.confine(lambda: hero.box)


if __name__ == "__main__":
    unittest.main()
