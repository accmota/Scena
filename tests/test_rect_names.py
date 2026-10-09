"""Rect / Square / Box named points follow their points (point stability).

The rule (Shapes Design — Rect, Named points): a rect names its corners the
first time one is used. From then on every name stays with its point through
drags, link updates, rotations, scales and flips. p1/p2 and p1+vec rects
(and boxes) are named at first use; the other models can never cross, so
their names are the visual ones until a flip mirrors them.

Class guards:

* ``TestFlipMirrorsNamedPoints`` — "a mirror applied as a rotation (or twice)":
  every named point lands on its mirror, the region does not move
  (Testing Design G3 / G4).
* ``TestDerivatesMatchAFreshTwin`` — "a Derivate missing from the update's
  write list": after any Defining write every Derivate reads what a freshly
  built twin reads (G5, the stale ``vec``).

    python -m unittest tests.test_rect_names -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import example, given, strategies as hst  # noqa: E402

from scena import Circle, Line, Rect, Square, Track  # noqa: E402
from scena.box import Box  # noqa: E402
from scena.track import shape_outline  # noqa: E402
from tests.test_shapes import ShapeTestCase  # noqa: E402

NAMED = (
    "top_left", "top_right", "bottom_left", "bottom_right",
    "top_center", "bottom_center", "left_center", "right_center",
)
TOL = 1e-6

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def xy(p):
    return (float(p.x), float(p.y))


def close(a, b, tol=TOL):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def named(obj, extra=()):
    return {n: xy(getattr(obj, n)) for n in NAMED + tuple(extra)}


def turned(v, ang):
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def signed_area(pts):
    return 0.5 * sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
        for i in range(len(pts))
    )


class NamesTestCase(ShapeTestCase):
    def assertXY(self, got, want, msg=None, tol=TOL):
        self.assertTrue(close(got, want, tol), msg or f"{got} != {want}")


# ---------------------------------------------------------------------------
# Named at first use
# ---------------------------------------------------------------------------

class TestNamedAtFirstUse(NamesTestCase):
    def test_p1_at_top_left_still_names_the_visual_corners(self):
        # The y-down habit: p1 upper-left, p2 lower-right.
        r = Rect(p1=(0, 50), p2=(100, 0))
        self.assertXY(xy(r.top_right), (100, 50))
        self.assertXY(xy(r.bottom_left), (0, 0))
        self.assertXY(xy(r.top_left), (0, 50))

    def test_negative_vec_names_the_visual_corners(self):
        r = Rect(p1=(0, 0), vec=(-100, 50))
        self.assertXY(xy(r.bottom_left), (-100, 0))
        self.assertXY(xy(r.top_right), (0, 50))

    def _geom_scene(self, spelling):
        c1 = Circle(center=(300, 500), radius=60)
        c2 = Circle(center=(600, 350), perimeter_point=(620, 400))
        if spelling == "ctor":
            caixa = Rect(p1=lambda: c1.center, p2=lambda: c2.center)
        else:
            caixa = Rect(p1=(200, 150), p2=(500, 250))   # placeholders
            if spelling == "field":
                caixa["p1"] @= lambda: c1.center
                caixa["p2"] @= lambda: c2.center
            else:
                caixa.p1 @= lambda: c1.center
                caixa.p2 @= lambda: c2.center
        c2["perimeter_point"] @= lambda: caixa.top_right   # first use
        return c1, c2, caixa

    def test_placeholder_then_link_names_after_the_links(self):
        # A geometry example's links: every link spelling.
        for spelling in ("ctor", "field", "part"):
            with self.subTest(spelling=spelling):
                c1, c2, caixa = self._geom_scene(spelling)
                self.assertXY(xy(caixa.top_right), (600, 500))
                self.assertNumAlmost(c2.radius, 150.0)
                # c1 goes below and right of c2: top_right stays (c2.x, c1.y).
                c1.move_to(700, 200)
                self.assertXY(xy(caixa.top_right), (600, 200))
                self.assertNumAlmost(c2.radius, 150.0)
                c1.move_to(900, 900)
                self.assertXY(xy(caixa.top_right), (600, 900))
                self.assertNumAlmost(c2.radius, 550.0)

    def test_an_early_read_names_from_the_values_then(self):
        # The documented cost: a read before linking freezes the placeholders.
        c1 = Circle(center=(300, 500), radius=5)
        c2 = Circle(center=(600, 350), radius=5)
        caixa = Rect(p1=(200, 150), p2=(500, 250))
        self.assertXY(xy(caixa.top_right), (500, 250))   # names now: p2 is top_right
        caixa["p1"] @= lambda: c1.center
        caixa["p2"] @= lambda: c2.center
        self.assertXY(xy(caixa.top_right), (600, 350))   # still p2

    def test_models_that_cannot_cross_start_visual(self):
        for r in (
            Rect(center=(0, 0), width=40, height=20),
            Rect(top_left=(-20, 10), width=40, height=20),
            Square(center=(0, 0), length=20),
            Rect(p1=(-20, 0), p2=(20, 0), height=20, anchor="cap"),
        ):
            with self.subTest(model=r.model):
                tl, br = xy(r.top_left), xy(r.bottom_right)
                self.assertLess(tl[0], br[0])
                self.assertGreater(tl[1], br[1])


# ---------------------------------------------------------------------------
# Names stay with their points
# ---------------------------------------------------------------------------

class TestNamesStayWithTheirPoints(NamesTestCase):
    def _corner_rect(self):
        r = Rect(p1=(0, 0), p2=(100, 50))
        named(r)   # first use: p1 is bottom_left, p2 is top_right
        return r

    def assert_identity(self, r):
        p1, p2 = xy(r.p1), xy(r.p2)
        self.assertXY(xy(r.bottom_left), p1)
        self.assertXY(xy(r.top_right), p2)

    def test_crossing_in_x_y_and_both_keeps_every_name(self):
        for new_p1 in ((150, 0), (0, 80), (150, 80)):
            with self.subTest(p1=new_p1):
                r = self._corner_rect()
                r.p1._takein(new_p1)
                self.assert_identity(r)
                p1, p2 = xy(r.p1), xy(r.p2)
                self.assertXY(xy(r.top_left), (p1[0], p2[1]))
                self.assertXY(xy(r.bottom_right), (p2[0], p1[1]))
                self.assertXY(xy(r.top_center), ((p1[0] + p2[0]) / 2, p2[1]))
                self.assertXY(xy(r.left_center), (p1[0], (p1[1] + p2[1]) / 2))

    def test_rotating_and_swapping_by_drag_agree(self):
        a = self._corner_rect()
        a.rotate_by(180)
        b = self._corner_rect()
        b.p1._takein((100, 50))
        b.p2._takein((0, 0))
        self.assertXY(xy(a.p1), xy(b.p1))
        self.assertXY(xy(a.top_right), xy(b.top_right))
        self.assert_identity(a)
        self.assert_identity(b)

    def test_rotation_write_through_the_collapse_keeps_identity(self):
        r = self._corner_rect()
        for deg in range(0, 361, 1):
            r.angle = deg
            self.assert_identity(r)

    def test_move_scale_and_rotate_about_a_pivot_keep_identity(self):
        r = self._corner_rect()
        r.p1._takein((150, 80))   # crossed
        r.move_by(7, -3)
        self.assert_identity(r)
        r.scale_by(1.5, about=(0, 0))
        self.assert_identity(r)
        r.rotate_by(33, about=(10, 10))
        self.assert_identity(r)

    def test_point_vec_names_stay_when_vec_changes_sign(self):
        r = Rect(p1=(0, 0), vec=(100, 50))
        self.assertXY(xy(r.bottom_left), (0, 0))
        r.vec.x = -100
        self.assertXY(xy(r.bottom_left), (0, 0))    # p1 keeps its name
        self.assertXY(xy(r.top_right), (-100, 50))  # p2 keeps its name


class TestObserverNeverSeesARename(NamesTestCase):
    def test_a_link_on_top_right_follows_one_point_forever(self):
        anchor = Circle(center=(0, 0), radius=5)
        r = Rect(p1=(0, 0), p2=(100, 50))
        line = Line(p1=(0, 0), p2=lambda: r.top_right)   # first use
        self.assertXY(xy(line.p2), (100, 50))
        # A later @= on a corner does not rename anything.
        r["p1"] @= lambda: anchor.center
        self.assertXY(xy(line.p2), xy(r.p2))
        for pos in ((300, 0), (300, 300), (-50, 300), (-50, -50)):
            anchor.move_to(*pos)
            self.assertXY(xy(line.p2), xy(r.p2), f"anchor at {pos}")


# ---------------------------------------------------------------------------
# Flips are true mirrors (class guard: a mirror applied as a rotation / twice)
# ---------------------------------------------------------------------------

def _build(label, rot):
    if label.startswith("Rect spine"):
        r = Rect(p1=(0, 0), p2=(40, 10), height=12, anchor=label.split()[-1])
        if rot:
            r.rotate_by(rot)
        return r
    return FLIP_MODELS[label](rot)


FLIP_MODELS = {
    "Rect center_wh": lambda rot: Rect(center=(10, 20), width=40, height=16, angle=rot),
    "Rect top_left_wh": lambda rot: Rect(top_left=(-5, 30), width=40, height=16, angle=rot),
    "Rect corner_corner": lambda rot: Rect(p1=(0, 0), p2=(40, 16), angle=rot),
    "Rect corner_corner reversed": lambda rot: Rect(p1=(40, 0), p2=(0, 16), angle=rot),
    "Rect point_vec": lambda rot: Rect(p1=(3, 4), vec=(40, 16), angle=rot),
    "Rect point_vec negative": lambda rot: Rect(p1=(3, 4), vec=(-40, 16), angle=rot),
    "Rect spine cap": None,
    "Rect spine square": None,
    "Rect spine side_left": None,
    "Rect spine side_right": None,
    "Square center_length": lambda rot: Square(center=(0, 0), length=20, angle=rot),
    "Square top_left_length": lambda rot: Square(top_left=(0, 20), length=20, angle=rot),
}


def _cross(r):
    """Make p1/p2 (or p1+vec) cross after the names are fixed."""
    from scena.shapes import RectModel
    if r.model == RectModel.CORNER_CORNER:
        x1, y1 = xy(r.p1)
        x2, y2 = xy(r.p2)
        r.p1._takein((2 * x2 - x1, y1))
    elif r.model == RectModel.POINT_VEC:
        r.vec.x = -float(r.vec.x)


def _points(r):
    extra = ("p1", "p2", "left_square_center", "right_square_center")
    return named(r, extra)


def _region(r):
    cx, cy, w, h, ang = r._oriented_frame()
    corners = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        ox, oy = turned((sx * w / 2, sy * h / 2), ang)
        corners.append((round(cx + ox, 6) + 0.0, round(cy + oy, 6) + 0.0))
    return (round(cx, 6) + 0.0, round(cy, 6) + 0.0), sorted(corners)


class TestFlipMirrorsNamedPoints(NamesTestCase):
    @given(
        label=hst.sampled_from(sorted(FLIP_MODELS)),
        rot=hst.integers(-180, 180),
        crossed=hst.booleans(),
        axis=hst.sampled_from(["x", "y"]),
    )
    # G3: POINT_VEC flip_x moved the box. G4: SPINE side anchors moved it.
    @example(label="Rect point_vec", rot=0, crossed=False, axis="x")
    @example(label="Rect spine side_left", rot=0, crossed=False, axis="x")
    @example(label="Rect spine side_right", rot=0, crossed=False, axis="y")
    def test_flip_mirrors_every_named_point(self, label, rot, crossed, axis):
        r = _build(label, rot)
        before = _points(r)       # first use
        if crossed:
            _cross(r)
            before = _points(r)
        region = _region(r)
        cx, cy = r._oriented_frame()[:2]
        setattr(r, "flip_" + axis, True)
        after = _points(r)
        for name, (x, y) in before.items():
            want = (2 * cx - x, y) if axis == "x" else (x, 2 * cy - y)
            self.assertXY(after[name], want, f"{label} flip_{axis}: {name}", tol=1e-6)
        self.assertEqual(_region(r)[0], region[0], f"{label}: the box moved")
        setattr(r, "flip_" + axis, False)
        again = _points(r)
        for name, p in before.items():
            self.assertXY(again[name], p, f"{label}: flip twice is not the identity ({name})")

    def test_point_vec_flip_x_keeps_the_box_in_place(self):
        # G3 repro.
        r = Rect(p1=(0, 0), vec=(100, 50))
        r.flip_x = True
        cx, cy, w, h, _ang = r._oriented_frame()
        self.assertXY((cx, cy), (50, 25))
        self.assertXY((w, h), (100, 50))

    def test_spine_side_flip_keeps_the_box_in_place(self):
        # G4 repro.
        for anchor in ("side_left", "side_right"):
            for axis in ("x", "y"):
                with self.subTest(anchor=anchor, axis=axis):
                    r = Rect(p1=(0, 0), p2=(100, 0), height=20, anchor=anchor)
                    before = r._oriented_frame()[:2]
                    setattr(r, "flip_" + axis, True)
                    self.assertXY(r._oriented_frame()[:2], before)

    def test_flip_y_at_rotation_zero_refreshes_linked_points(self):
        # flip_y writes no changed Defining value at rotation 0; the names still move.
        r = Rect(center=(0, 0), width=40, height=20)
        line = Line(p1=(0, 0), p2=lambda: r.top_right)
        self.assertXY(xy(line.p2), (20, 10))
        r.flip_y = True
        self.assertXY(xy(line.p2), (20, -10))


class TestFlipCanary(unittest.TestCase):
    def test_a_rotation_only_flip_is_caught(self):
        from diff_support import assert_catches

        def rotation_only(self, axis, *, force=False):
            # The old mistake: turn the box to the mirrored heading.
            ang = float(self._oriented_frame()[4])
            target = (180.0 - ang) if axis == "x" else -ang
            self.rotate_by(target - ang, force=force)

        assert_catches(
            self,
            "test_rect_names.TestFlipMirrorsNamedPoints.test_flip_mirrors_every_named_point",
            [(Rect, "_mirror_geometry", rotation_only)],
            "Rect flip applied as a rotation",
        )


# ---------------------------------------------------------------------------
# Derivates match a fresh twin (class guard: a Derivate missing from the
# update's write list — G5, the stale vec)
# ---------------------------------------------------------------------------

TWIN_CASES = [
    (Rect, dict(p1=(0, 0), p2=(100, 50)), "p1", (20, -10)),
    (Rect, dict(p1=(0, 0), p2=(100, 50)), "p2", (300, 50)),
    (Rect, dict(p1=(0, 0), p2=(100, 50), angle=20), "angle", 35.0),
    (Rect, dict(top_left=(0, 50), width=100, height=50), "top_left", (10, 60)),
    (Rect, dict(top_left=(0, 50), width=100, height=50), "width", 30.0),
    (Rect, dict(top_left=(0, 50), width=100, height=50, angle=10), "height", 70.0),
    (Rect, dict(center=(0, 0), width=100, height=50), "center", (5, 5)),
    (Rect, dict(center=(0, 0), width=100, height=50), "width", 30.0),
    (Rect, dict(center=(0, 0), width=100, height=50, angle=10), "angle", 40.0),
    (Rect, dict(p1=(0, 0), vec=(100, 50)), "p1", (20, -10)),
    (Rect, dict(p1=(0, 0), vec=(100, 50), angle=15), "vec", (60, 20)),
    (Rect, dict(p1=(0, 0), p2=(100, 0), height=20, anchor="cap"), "p1", (20, -10)),
    (Rect, dict(p1=(0, 0), p2=(100, 0), height=20, anchor="square"), "height", 30.0),
    (Square, dict(center=(0, 0), length=20), "length", 35.0),
    (Square, dict(top_left=(0, 20), length=20, angle=10), "angle", 25.0),
    (Box, dict(p1=(0, 0), p2=(100, 50)), "p1", (20, -10)),
    (Box, dict(p1=(0, 0), p2=(100, 50), angle=20), "p2", (300, 60)),
    (Box, dict(center=(0, 0), width=100, height=50), "width", 30.0),
    (Box, dict(top_left=(0, 50), width=100, height=50), "height", 70.0),
    (Box, dict(p1=(0, 0), vec=(100, 50)), "vec", (60, 20)),
    (Box, dict(p1=(0, 0), p2=(100, 0), height=20, anchor="cap"), "p2", (150, 30)),
]


def _read(obj, name):
    v = getattr(obj, name)
    if hasattr(v, "x"):
        return (float(v.x), float(v.y))
    return float(v.value if hasattr(v, "value") else v)


def _write(obj, name, value):
    if isinstance(value, tuple):
        getattr(obj, name)._takein(value)
    else:
        setattr(obj, name, value)


class TestDerivatesMatchAFreshTwin(NamesTestCase):
    def test_every_derivate_matches_a_twin_after_a_defining_write(self):
        for cls, kwargs, key, value in TWIN_CASES:
            with self.subTest(cls=cls.__name__, kwargs=kwargs, key=key):
                obj = cls(**kwargs)
                parts = [n for n in cls._PART_NAMES if n != "length"]
                for n in parts:
                    _read(obj, n)                  # every Derivate live
                _write(obj, key, value)
                twin = cls(**{**kwargs, key: value})
                twin.__dict__["_name_signs"] = obj.__dict__.get("_name_signs")
                for n in parts:
                    got, want = _read(obj, n), _read(twin, n)
                    if isinstance(got, tuple):
                        self.assertXY(got, want, f"{cls.__name__}.{n} stale after {key}")
                    else:
                        self.assertAlmostEqual(got, want, places=6,
                                               msg=f"{cls.__name__}.{n} stale after {key}")

    def test_vec_is_p2_minus_p1_in_the_local_frame(self):
        samples = [
            Rect(p1=(0, 50), p2=(100, 0), angle=30),
            Rect(center=(0, 0), width=40, height=20, angle=25),
            Rect(top_left=(0, 0), width=40, height=20, angle=-10),
            Rect(p1=(1, 2), vec=(-30, 10), angle=40),
            Square(center=(0, 0), length=10, angle=5),
            Box(p1=(0, 50), p2=(100, 0), angle=30),
            Box(center=(0, 0), width=40, height=20, angle=25),
        ]
        for r in samples:
            with self.subTest(r=type(r).__name__, model=r.model):
                ang = float(r.angle) if isinstance(r, Rect) else float(r.angle)
                p1, p2, vec = xy(r.p1), xy(r.p2), xy(r.vec)
                off = turned(vec, ang)
                self.assertXY((p1[0] + off[0], p1[1] + off[1]), p2)

    def test_vec_follows_a_corner_move(self):
        # G5 repro.
        r = Rect(p1=(0, 0), p2=(100, 50))
        self.assertXY(xy(r.vec), (100, 50))
        r.p2.x = 300
        self.assertXY(xy(r.vec), (300, 50))


class TestFreshTwinCanary(unittest.TestCase):
    def test_a_skipped_vec_refresh_is_caught(self):
        from diff_support import assert_catches
        assert_catches(
            self,
            "test_rect_names.TestDerivatesMatchAFreshTwin.test_every_derivate_matches_a_twin_after_a_defining_write",
            [(Rect, "_refresh_live_vec", lambda self: None)],
            "Rect update skips the Derivate vec",
        )


# ---------------------------------------------------------------------------
# Copies carry names; measurements name afresh
# ---------------------------------------------------------------------------

class TestCopiesCarryNames(NamesTestCase):
    def _crossed(self):
        r = Rect(p1=(0, 0), p2=(100, 50))
        named(r)
        r.p1._takein((150, 80))
        return r

    def test_clone_keeps_every_named_point(self):
        r = self._crossed()
        c = r.clone()
        for n, p in named(r).items():
            self.assertXY(xy(getattr(c, n)), p, n)

    def test_clone_of_a_flipped_rect_keeps_every_named_point(self):
        for r in (Rect(center=(0, 0), width=40, height=20, angle=10),
                  Square(top_left=(0, 20), length=20)):
            r.flip_y = True
            c = r.clone()
            for n, p in named(r).items():
                self.assertXY(xy(getattr(c, n)), p, f"{type(r).__name__}.{n}")

    def test_clone_keeps_the_model_and_its_placement_points(self):
        # A CENTER_WH rebuild turned p1 / p2 into Derivates on other corners.
        for r in (Rect(p1=(0, 0), p2=(40, 20)), Rect(p1=(40, 20), p2=(0, 0)),
                  Rect(p1=(3, 4), vec=(-30, -12)), Rect(top_left=(3, 4), width=30, height=12)):
            r.flip_x = True
            r.rotate_by(20)
            r.scale_by(1.25)
            c = r.clone()
            self.assertEqual(c.model, r.model)
            for n in ("p1", "p2", "center", *named(r)):
                self.assertXY(xy(getattr(c, n)), xy(getattr(r, n)), f"{r.model}: {n}")
            for attr in ("angle", "scale", "flip_x", "flip_y"):
                self.assertEqual(getattr(c, attr), getattr(r, attr), attr)

    def test_takein_keeps_every_named_point(self):
        r = self._crossed()
        other = Rect(p1=(0, 0), p2=(1, 1))
        other._takein(r)
        for n, p in named(r).items():
            self.assertXY(xy(getattr(other, n)), p, n)

    def test_box_of_a_rect_keeps_its_names(self):
        r = self._crossed()          # p1=(150,80), p2=(100,50): top_right is p2
        self.assertXY(xy(r.top_right), (100, 50))
        b = r.box
        for n, p in named(r).items():
            self.assertXY(xy(getattr(b, n)), p, f"box.{n}")
        # The screen question goes to the screen-aligned edges.
        self.assertAlmostEqual(b.top, 80.0)
        self.assertAlmostEqual(b.right, 150.0)


# ---------------------------------------------------------------------------
# A Box made from a Graphic is its frame, names included
# ---------------------------------------------------------------------------

class TestBoxCarriesNames(NamesTestCase):
    def test_flipped_rect_box_keeps_its_names(self):
        for flip in ("flip_x", "flip_y"):
            with self.subTest(flip=flip):
                r = Rect(center=(0, 0), width=40, height=20)
                setattr(r, flip, True)
                for n, p in named(r).items():
                    self.assertXY(xy(getattr(r.box, n)), p, f"{flip}: box.{n}")
                    self.assertXY(xy(getattr(Box(r), n)), p, f"{flip}: Box(r).{n}")

    def test_flipped_sprite_box_top_is_still_over_its_head(self):
        import warnings
        from scena import Sprite
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = Sprite("diff_missing.png", center=(100, 100))
        top = xy(s.box.top_center)
        self.assertGreater(top[1], 100.0)
        s.flip_x = True
        self.assertXY(xy(s.box.top_center), top)         # was at its feet
        left = xy(s.box.left_center)
        s.flip_x = False
        self.assertXY(xy(s.box.right_center), left)      # the front swapped sides

    def test_text_cannot_be_flipped(self):
        # Mirrored text is unreadable: flips raise; False stays a no-op.
        from scena import Text
        t = Text("hello", center=(0, 0))
        with self.assertRaises(TypeError):
            t.flip_x = True
        with self.assertRaises(TypeError):
            t.flip_y = True
        t.flip_x = False
        self.assertFalse(t.flip_x)
        t.destroy()

    def test_board_cell_follows_the_board_through_turns_and_flips(self):
        board = Rect(center=(0, 0), width=80, height=80)

        def a1():
            return xy(board.box.grid(8, 8).cell(0, 0).center)

        start = a1()                                   # top-left cell
        board.rotate_by(90)
        self.assertXY(a1(), turned(start, 90), tol=1e-6)
        board.rotate_by(-90)
        board.flip_x = True
        self.assertXY(a1(), (-start[0], start[1]), tol=1e-6)
        board.flip_y = True
        self.assertXY(a1(), (-start[0], -start[1]), tol=1e-6)

    def test_fleet_slot_stays_on_the_leaders_side(self):
        leader = Rect(center=(0, 0), width=60, height=30)
        slot = lambda: xy(leader.box.beside("right", width=20).center)  # noqa: E731
        self.assertXY(slot(), (40, 0))
        leader.rotate_by(90)
        self.assertXY(slot(), (0, 40), tol=1e-6)
        leader.rotate_by(-90)
        leader.flip_x = True
        self.assertXY(slot(), (-40, 0), tol=1e-6)      # mirrored with the leader

    def test_box_placement_takes_the_regions_names(self):
        r = Rect(center=(0, 0), width=40, height=20)
        r.flip_y = True
        placed = Rect(box=r.box)
        for n, p in named(r).items():
            self.assertXY(xy(getattr(placed, n)), p, f"Rect(box=).{n}")
        sq = Square(center=(0, 0), length=20)
        sq.flip_x = True
        inside = Square(box=sq.box)
        self.assertXY(xy(inside.top_left), xy(sq.top_left))


# ---------------------------------------------------------------------------
# Box: same rule; layout sides follow the names
# ---------------------------------------------------------------------------

class TestBoxNames(NamesTestCase):
    def _crossed_box(self):
        b = Box(p1=(0, 0), p2=(100, 50))
        named(b)                          # first use
        b.p1._takein((0, 100))            # cross in y: named top is now y=50
        return b

    def test_box_names_stay_with_their_points(self):
        b = self._crossed_box()
        self.assertXY(xy(b.bottom_left), (0, 100))
        self.assertXY(xy(b.top_right), (100, 50))
        self.assertXY(xy(b.top_center), (50, 50))

    def test_layout_sides_follow_the_named_edges(self):
        b = self._crossed_box()
        strip = b.strip("top", 10)
        self.assertXY(xy(strip.center), (50, 55))
        self.assertXY(xy(strip.top_center), (50, 50))       # child inherits the names
        beside = b.beside("top", height=10)
        self.assertXY(xy(beside.center), (50, 45))
        g = b.grid(1, 2)
        self.assertXY(xy(g.cell(0, 0).center), (50, 62.5))  # row 0 = named top

    def test_box_copy_inherits_and_aabb_is_visual(self):
        b = self._crossed_box()
        copy = Box(b)
        self.assertXY(xy(copy.top_center), xy(b.top_center))
        self.assertAlmostEqual(b.top, 100.0)
        self.assertAlmostEqual(b.bottom, 50.0)


# ---------------------------------------------------------------------------
# Track: u = 0 at bottom_left, CCW
# ---------------------------------------------------------------------------

class TestTrackStartsAtBottomLeft(NamesTestCase):
    def test_sharp_rect_start_follows_bottom_left_through_a_crossing(self):
        r = Rect(p1=(0, 0), p2=(40, 20))
        t = Track(r)
        self.assertXY(t.at(0.0), xy(r.bottom_left), tol=1e-4)
        r.p1._takein((60, 0))
        self.assertXY(t.at(0.0), xy(r.bottom_left), tol=1e-4)
        self.assertXY(xy(r.bottom_left), (60, 0))
        self.assertGreater(signed_area(shape_outline(r)[0]), 0.0)

    def test_flipped_rect_starts_at_bottom_left_and_stays_ccw(self):
        r = Rect(center=(0, 0), width=40, height=20)
        r.flip_y = True
        self.assertXY(xy(r.bottom_left), (-20, 10))
        outline, _closed = shape_outline(r)
        self.assertXY(outline[0], (-20, 10), tol=1e-6)
        self.assertGreater(signed_area(outline), 0.0)

    def test_rounded_rect_starts_after_the_bottom_left_fillet(self):
        r = Rect(center=(0, 0), width=40, height=20, corner_radius=4)
        r.flip_y = True
        outline, _closed = shape_outline(r)
        # CCW from the (visual top-left) bottom_left corner runs down the left side.
        self.assertXY(outline[0], (-20, 10 - 4), tol=1e-6)
        self.assertGreater(signed_area(outline), 0.0)


if __name__ == "__main__":
    unittest.main()
