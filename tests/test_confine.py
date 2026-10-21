"""Graphic.confine — clamp / bounce / wrap against a Box (any angle).

Run headless:

    python -m unittest tests.test_confine -v
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Box, Circle, Line, Rect, Vec2, canvas, init
from scena.confine import _confine_point, _effective_half_extents, _projected_half


class ConfineTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        self._owned = []

    def tearDown(self):
        for s in list(self._owned):
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestClampCenter(ConfineTestCase):
    def test_galaga_style_horizontal_clamp(self):
        # Hand-written pattern from a Galaga game: keep center.x in [40, W-40]
        ship = self.track(Circle(center=(10, 70), radius=20))
        play = Box(center=(500, 400), width=920, height=800)  # inset(40) of 1000×800
        sides = ship.confine(play)
        self.assertAlmostEqual(float(ship.center.x), 40.0)
        self.assertAlmostEqual(float(ship.center.y), 70.0)
        self.assertEqual(sides, frozenset({"left"}))

        ship.center = (990, 70)
        sides = ship.confine(play)
        self.assertAlmostEqual(float(ship.center.x), 960.0)
        self.assertEqual(sides, frozenset({"right"}))

    def test_noop_when_inside(self):
        c = self.track(Circle(center=(400, 300), radius=10))
        box = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(box)
        self.assertEqual(sides, frozenset())
        self.assertAlmostEqual(float(c.center.x), 400.0)
        self.assertAlmostEqual(float(c.center.y), 300.0)

    def test_defaults_are_center_clamp(self):
        c = self.track(Circle(center=(0, 300), radius=5))
        box = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(box)
        self.assertAlmostEqual(float(c.center.x), 300.0)
        self.assertEqual(sides, frozenset({"left"}))


class TestByBox(ConfineTestCase):
    def test_keeps_own_frame_inside(self):
        # Circle radius 20 → box is 40×40; region 200×100 → effective ±80 x, ±30 y
        c = self.track(Circle(center=(500, 300), radius=20))
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, by="box")
        # center at 500: local x = 100; effective hw = 100-20 = 80 → clamp to 480
        self.assertAlmostEqual(float(c.center.x), 480.0)
        self.assertAlmostEqual(float(c.center.y), 300.0)
        self.assertEqual(sides, frozenset({"right"}))

    def test_too_big_pins_to_region_center(self):
        # Object wider than region → remainder half-extent 0 → pin on that axis
        c = self.track(Circle(center=(100, 300), radius=80))  # diameter 160
        region = Box(center=(400, 300), width=100, height=200)  # width 100 < 160
        sides = c.confine(region, by="box")
        self.assertAlmostEqual(float(c.center.x), 400.0)
        self.assertAlmostEqual(float(c.center.y), 300.0)
        self.assertIn("left", sides)

    def test_line_is_measured_by_its_ends(self):
        # A Line has no .box; by="box" keeps both ends inside (before
        # 2026-10-20 it raised; tests/test_per_object_costs.py).
        line = self.track(Line(p1=(-80, 0), p2=(20, 10)))
        region = Box(center=(50, 0), width=200, height=100)
        self.assertEqual(line.confine(region, by="box"), frozenset({"left"}))
        self.assertAlmostEqual(float(line.p1.x), -50.0)
        self.assertAlmostEqual(float(line.p2.x), 50.0)
        self.assertAlmostEqual(float(line.p2.y), 10.0)
        with self.assertRaises(TypeError) as cm2:
            _ = line.box
        self.assertIn("unsupported", str(cm2.exception))


class TestByOverlap(ConfineTestCase):
    def test_allows_hanging_out(self):
        # Circle r=20 at x=490, region right edge 500 → still overlaps (span 470..510)
        c = self.track(Circle(center=(490, 300), radius=20))
        region = Box(center=(400, 300), width=200, height=100)  # right=500
        sides = c.confine(region, by="overlap")
        self.assertEqual(sides, frozenset())
        self.assertAlmostEqual(float(c.center.x), 490.0)

    def test_acts_only_when_fully_outside(self):
        # center at 521 → circle spans 501..541, fully past right=500
        # effective right for overlap = 500+20 = 520; center 521 → clamp to 520
        c = self.track(Circle(center=(521, 300), radius=20))
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, by="overlap")
        self.assertAlmostEqual(float(c.center.x), 520.0)
        self.assertEqual(sides, frozenset({"right"}))

    def test_touching_one_pixel_of_overlap_is_noop(self):
        # center at 520 → circle left edge exactly at 500 (touching)
        c = self.track(Circle(center=(520, 300), radius=20))
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, by="overlap")
        self.assertEqual(sides, frozenset())
        self.assertAlmostEqual(float(c.center.x), 520.0)


class TestWrap(ConfineTestCase):
    def test_carries_overshoot(self):
        c = self.track(Circle(center=(515, 300), radius=5))
        region = Box(center=(400, 300), width=200, height=100)  # right=500, left=300
        # overshoot past right by 15 → appear 15 past left → 315
        sides = c.confine(region, action="wrap")
        self.assertAlmostEqual(float(c.center.x), 315.0)
        self.assertEqual(sides, frozenset({"right"}))

    def test_wrap_from_left(self):
        c = self.track(Circle(center=(285, 300), radius=5))
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, action="wrap")
        self.assertAlmostEqual(float(c.center.x), 485.0)
        self.assertEqual(sides, frozenset({"left"}))


class TestBounce(ConfineTestCase):
    def test_flips_vel_axis_aligned(self):
        c = self.track(Circle(center=(510, 300), radius=5))
        c.vel = Vec2(100, 40)
        region = Box(center=(400, 300), width=200, height=100)
        sides = c.confine(region, action="bounce")
        self.assertAlmostEqual(float(c.center.x), 500.0)
        self.assertEqual(sides, frozenset({"right"}))
        self.assertAlmostEqual(float(c.vel.x), -100.0)
        self.assertAlmostEqual(float(c.vel.y), 40.0)

    def test_requires_vel(self):
        c = self.track(Circle(center=(510, 300), radius=5))
        region = Box(center=(400, 300), width=200, height=100)
        with self.assertRaises(TypeError) as cm:
            c.confine(region, action="bounce")
        self.assertIn("vel", str(cm.exception))

    def test_bounce_on_rotated_region_reflects_local_axis(self):
        # Region rotated 90°: local +x is world +y. Hit "right" in local → flip local vx.
        c = self.track(Circle(center=(400, 510), radius=5))
        c.vel = Vec2(0, 100)  # moving +world y = +local x for 90° region
        region = Box(center=(400, 300), width=200, height=100, angle=90)
        # After 90°: local width 200 is along world y; local height 100 along -world x
        # Region center 400,300; local +x (along width) maps to world +y.
        # World (400, 510) → local x = 210, hw=100 → clamp local x to 100 → world y=400
        sides = c.confine(region, action="bounce")
        self.assertIn("right", sides)
        self.assertAlmostEqual(float(c.center.x), 400.0, places=5)
        self.assertAlmostEqual(float(c.center.y), 400.0, places=5)
        # Local vx was +100 (world +y), flipped to -100 → world vel (0, -100)
        self.assertAlmostEqual(float(c.vel.x), 0.0, places=5)
        self.assertAlmostEqual(float(c.vel.y), -100.0, places=5)


class TestRotatedRegion(ConfineTestCase):
    def test_center_clamp_30_deg(self):
        region = Box(center=(400, 300), width=200, height=100, angle=30)
        # Point far along region's local +x
        rad = math.radians(30)
        far = 200.0
        wx = 400 + far * math.cos(rad)
        wy = 300 + far * math.sin(rad)
        c = self.track(Circle(center=(wx, wy), radius=5))
        sides = c.confine(region)
        self.assertEqual(sides, frozenset({"right"}))
        # Should land at local x = 100
        nx, ny = float(c.center.x), float(c.center.y)
        expect_x = 400 + 100 * math.cos(rad)
        expect_y = 300 + 100 * math.sin(rad)
        self.assertAlmostEqual(nx, expect_x, places=5)
        self.assertAlmostEqual(ny, expect_y, places=5)

    def test_by_box_on_rotated_region(self):
        region = Box(center=(400, 300), width=200, height=100, angle=0)
        c = self.track(Rect(center=(480, 300), width=40, height=20))
        sides = c.confine(region, by="box")
        # hw_eff = 100 - 20 = 80 → clamp to 480 is exactly on edge → noop if already 480
        self.assertEqual(sides, frozenset())
        c.center = (490, 300)
        sides = c.confine(region, by="box")
        self.assertAlmostEqual(float(c.center.x), 480.0)
        self.assertEqual(sides, frozenset({"right"}))


class TestErrorsAndDegenerate(ConfineTestCase):
    def test_unknown_by(self):
        c = self.track(Circle(center=(400, 300), radius=5))
        region = Box(center=(400, 300), width=100, height=100)
        with self.assertRaises(TypeError):
            c.confine(region, by="silhouette")

    def test_unknown_action(self):
        c = self.track(Circle(center=(400, 300), radius=5))
        region = Box(center=(400, 300), width=100, height=100)
        with self.assertRaises(TypeError):
            c.confine(region, action="destroy")

    def test_degenerate_region_from_inset_remainder(self):
        # inset past size → point remainder; clamp pins to center, no crash
        region = Box(center=(400, 300), width=20, height=20).inset(12)  # 0×0
        c = self.track(Circle(center=(450, 350), radius=5))
        sides = c.confine(region)
        self.assertAlmostEqual(float(c.center.x), 400.0)
        self.assertAlmostEqual(float(c.center.y), 300.0)
        self.assertTrue(sides)  # corrected somehow

    def test_region_accepts_rect_graphic(self):
        wall = self.track(Rect(center=(400, 300), width=200, height=100))
        c = self.track(Circle(center=(600, 300), radius=5))
        sides = c.confine(wall)
        self.assertAlmostEqual(float(c.center.x), 500.0)
        self.assertEqual(sides, frozenset({"right"}))


class TestAnchoredSprite(ConfineTestCase):
    """A Sprite whose sheet has an anchor: ``center`` is the pivot, not the
    middle of the drawing (anchor="bottom" puts it at the feet).

    Bug (2026-10-09, tutorial 18): confine compared the drawn middle and wrote
    it back as the pivot, so every clamp lifted the sprite by half its height.
    A ninja walking into the screen edge climbed ~1900 units/s to the top.
    Bug class: a pose writer fed a point measured in another frame (drawn box
    vs pivot). Every by= and action= is checked against the anchor.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from tests.test_sprite import _write_padded_png
        cls._td = tempfile.TemporaryDirectory()
        cls.png = os.path.join(cls._td.name, "bar.png")
        _write_padded_png(cls.png, canvas_w=64, canvas_h=64, blob=(24, 8, 16, 48))

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def sprite(self, anchor, center):
        import warnings
        from scena import Sheet, Sprite
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.track(Sprite(Sheet(self.png, anchor=anchor), center=center,
                                     width=64, height=64))

    def test_clamp_keeps_the_pivot_off_the_edge_and_does_not_lift(self):
        play = Box(center=(500, 400), width=1000, height=800)
        for anchor in ("center", "bottom", "top"):
            with self.subTest(anchor=anchor):
                s = self.sprite(anchor, (990, 300))
                for _ in range(30):
                    s.move_by(5, -5)
                    s.confine(play)
                self.assertAlmostEqual(float(s.center.x), 1000.0)
                self.assertAlmostEqual(float(s.center.y), 150.0)      # kept falling

    def test_by_box_and_overlap_measure_the_drawn_box(self):
        play = Box(center=(500, 400), width=1000, height=800)
        for anchor in ("center", "bottom"):
            for by, right in (("box", 1000.0), ("overlap", 1064.0)):
                with self.subTest(anchor=anchor, by=by):
                    s = self.sprite(anchor, (1200, 300))
                    s.confine(play, by=by)
                    self.assertAlmostEqual(float(s.box.right), right)
                    self.assertAlmostEqual(float(s.center.y), 300.0)

    def test_by_box_at_the_floor_puts_the_feet_on_it(self):
        s = self.sprite("bottom", (500, -40))
        s.confine(Box(center=(500, 400), width=1000, height=800), by="box")
        self.assertAlmostEqual(float(s.box.bottom), 0.0)
        self.assertAlmostEqual(float(s.center.y), 0.0)                # the feet

    def test_wrap_and_bounce_move_the_pivot_by_the_correction(self):
        from scena import Vec2
        play = Box(center=(500, 400), width=1000, height=800)
        s = self.sprite("bottom", (1010, 300))
        self.assertEqual(s.confine(play, action="wrap"), frozenset({"right"}))
        self.assertAlmostEqual(float(s.center.x), 10.0)
        self.assertAlmostEqual(float(s.center.y), 300.0)
        b = self.sprite("bottom", (500, 820))
        b.vel = Vec2(0, 100)
        self.assertEqual(b.confine(play, action="bounce"), frozenset({"top"}))
        self.assertAlmostEqual(float(b.center.y), 800.0)
        self.assertAlmostEqual(float(b.vel.y), -100.0)


def _outline_samples(shape):
    """Points on the shape's outline, built from its geometry (the oracle:
    the drawn curve, not confine's extents)."""
    from scena.box import region_frame
    from scena.confine import _outline_points
    from scena.box import oriented_xy
    kind = type(shape).__mro__
    if any(k.__name__ in ("Circle", "Ellipse") for k in kind):
        cx, cy, w, h, ang = region_frame(shape)
        a, b = abs(w) / 2, abs(h) / 2
        return [oriented_xy(cx, cy, a * math.cos(t), b * math.sin(t), ang)
                for t in (2 * math.pi * i / 720 for i in range(720))]
    if any(k.__name__ in ("Rect", "Square", "Concave") for k in kind):
        cx, cy, w, h, ang = region_frame(shape)
        return [oriented_xy(cx, cy, sx * w / 2, sy * h / 2, ang)
                for sx in (-1, 1) for sy in (-1, 1)]
    return _outline_points(shape)


def _local(points, region):
    from scena.box import region_frame
    rcx, rcy, _rw, _rh, rang = region_frame(region)
    rad = math.radians(-rang)
    c, s = math.cos(rad), math.sin(rad)
    return ([(x - rcx) * c - (y - rcy) * s for x, y in points],
            [(x - rcx) * s + (y - rcy) * c for x, y in points])


class TestOutlineEveryKind(ConfineTestCase):
    """``by="box"`` keeps the whole outline inside and touches each side it
    acted on; ``by="overlap"`` leaves it just outside. Every kind, shape angle
    and region angle (a rotated Circle / Ellipse stopped short of the wall
    before 2026-10-20: its frame turned with it; Triangle / Polygon / Line /
    Track / Point refused)."""

    def _kinds(self):
        from scena import Concave, Ellipse, Point, Polygon, RegularPolygon, Square, Track, Triangle
        return {
            "Rect": lambda c, a: Rect(width=60, height=24, center=c, angle=a),
            "Square": lambda c, a: Square(length=40, center=c, angle=a),
            "Concave": lambda c, a: Concave(width=60, height=30, center=c, angle=a,
                                            scoop="top_center"),
            "Circle": lambda c, a: Circle(radius=25, center=c).rotate_to(a),
            "Ellipse": lambda c, a: Ellipse(width=70, height=26, center=c, angle=a),
            "Triangle": lambda c, a: Triangle(radius=30, center=c, angle=a),
            "Triangle wide": lambda c, a: Triangle(radius=20, base_ratio=1.8, center=c, angle=a),
            "RegularPolygon": lambda c, a: RegularPolygon(n=5, radius=25, center=c, angle=a),
            "Polygon": lambda c, a: Polygon(points=[(c[0] - 30, c[1]), (c[0] + 25, c[1] - 10),
                                                    (c[0] + 5, c[1] + 35)]),
            "Line": lambda c, a: Line(p1=(c[0] - 30, c[1] - 5), p2=(c[0] + 25, c[1] + 20)),
            "Track": lambda c, a: Track(points=[(c[0] - 30, c[1]), (c[0], c[1] + 30),
                                                (c[0] + 30, c[1] - 10)]),
            "Point": lambda c, a: Point(c[0], c[1]),
        }

    def test_box_keeps_the_outline_inside_and_touching(self):
        import random
        rng = random.Random(11)
        eps = 1e-6
        for name, make in self._kinds().items():
            for _ in range(12):
                rang = rng.choice((0.0, 0.0, 15.0, -40.0, 90.0))
                region = Box(center=(500, 400), width=600, height=400, angle=rang)
                c = (500 + rng.uniform(-420, 420), 400 + rng.uniform(-320, 320))
                shape = self.track(make(c, rng.uniform(-180, 180)))
                sides = shape.confine(region, by="box")
                lxs, lys = _local(_outline_samples(shape), region)
                tol = 1e-2 if name in ("Circle", "Ellipse") else eps   # sampled curve
                msg = f"{name} region {rang} sides {sides}"
                self.assertLessEqual(max(lxs), 300 + eps, msg)
                self.assertGreaterEqual(min(lxs), -300 - eps, msg)
                self.assertLessEqual(max(lys), 200 + eps, msg)
                self.assertGreaterEqual(min(lys), -200 - eps, msg)
                if "right" in sides:
                    self.assertAlmostEqual(max(lxs), 300, delta=tol, msg=msg)
                if "left" in sides:
                    self.assertAlmostEqual(min(lxs), -300, delta=tol, msg=msg)
                if "top" in sides:
                    self.assertAlmostEqual(max(lys), 200, delta=tol, msg=msg)
                if "bottom" in sides:
                    self.assertAlmostEqual(min(lys), -200, delta=tol, msg=msg)

    def test_overlap_acts_only_once_the_outline_has_left(self):
        import random
        rng = random.Random(5)
        for name, make in self._kinds().items():
            for _ in range(8):
                rang = rng.choice((0.0, 25.0))
                region = Box(center=(500, 400), width=600, height=400, angle=rang)
                c = (500 + rng.uniform(-500, 500), 400 + rng.uniform(-380, 380))
                shape = self.track(make(c, rng.uniform(-180, 180)))
                lxs0, lys0 = _local(_outline_samples(shape), region)
                sides = shape.confine(region, by="overlap")
                lxs, lys = _local(_outline_samples(shape), region)
                tol = 1e-2 if name in ("Circle", "Ellipse") else 1e-6
                msg = f"{name} region {rang} sides {sides}"
                if not sides:      # still overlapping (or touching) on both axes
                    self.assertTrue(min(lxs0) <= 300 + tol and max(lxs0) >= -300 - tol, msg)
                    self.assertTrue(min(lys0) <= 200 + tol and max(lys0) >= -200 - tol, msg)
                if "right" in sides:
                    self.assertAlmostEqual(min(lxs), 300, delta=tol, msg=msg)
                if "left" in sides:
                    self.assertAlmostEqual(max(lxs), -300, delta=tol, msg=msg)
                if "top" in sides:
                    self.assertAlmostEqual(min(lys), 200, delta=tol, msg=msg)
                if "bottom" in sides:
                    self.assertAlmostEqual(max(lys), -200, delta=tol, msg=msg)

    def test_rect_and_square_answer_as_before(self):
        # Frame kinds keep the frame math (projected half-extents, unchanged).
        r = self.track(Rect(width=40, height=10, center=(5, 200), angle=30))
        r.confine(Box(center=(500, 400), width=1000, height=800), by="box")
        self.assertAlmostEqual(float(r.center.x), 20 * math.cos(math.radians(30)) + 5 * 0.5)


class TestPureHelpers(unittest.TestCase):
    def test_projected_half_axis_aligned(self):
        pw, ph = _projected_half(20, 10, 0, 0)
        self.assertAlmostEqual(pw, 20.0)
        self.assertAlmostEqual(ph, 10.0)

    def test_projected_half_90_swaps(self):
        pw, ph = _projected_half(20, 10, 90, 0)
        self.assertAlmostEqual(pw, 10.0)
        self.assertAlmostEqual(ph, 20.0)

    def test_effective_center_unchanged(self):
        hw, hh = _effective_half_extents(200, 100, "center", None, 0)
        self.assertAlmostEqual(hw, 100.0)
        self.assertAlmostEqual(hh, 50.0)

    def test_confine_point_clamp(self):
        nx, ny, sides, vel = _confine_point(
            600, 300, 400, 300, 100, 50, 0, "clamp",
        )
        self.assertAlmostEqual(nx, 500.0)
        self.assertEqual(sides, frozenset({"right"}))
        self.assertIsNone(vel)


if __name__ == "__main__":
    unittest.main()
