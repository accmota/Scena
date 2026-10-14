"""
Concave: a box with a scoop (Shapes Design — Concave).

Covers:
  - the shape: inside the box, outside the ellipse centered on the ``scoop``
    named point, radii = the box's reach minus ``rim`` (an independent model
    built from the public API only: named point, width, height, angle, rim)
  - a square box gives a circle (corner), a 2:1 box a circle (edge)
  - every Rect model places the same box as a Rect with the same arguments
  - validation: scoop names (near miss), rim (number / pair, >= 0), no
    corner_radius, scoop fixed, other kinds refuse ``.scoop``
  - flips / rotation / p1-p2 crossing keep the scoop on its named point
  - clone, ``<<`` (Concave and Rect sources), box=, ``.box``
  - rim: links, ``@=``, scale_by scales it, a linked rim refuses scale_by
  - every consumer agrees with the model: draw path, collision pieces (within
    0.25 DU), Track outline and geom queries (within 0.01 DU), bounds
  - caches: a rim write or a flip alone redraws and re-collides
  - collision: a ball rides a quarter-pipe and comes back; a ball drops into
    a half-pipe; the convex pieces split an outer face at most once
  - Concave is not a Rect (it does not collide as a box)

Run:
    python tests/run_tiers.py focused test_concave
"""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena  # noqa: E402
from scena import Box, Concave, Polygon, Rect, State, Track  # noqa: E402
from scena.collision import (  # noqa: E402
    STATIC, get_collision_system, reset_collision_system, resolve,
)
from scena.scenamath import Vec2  # noqa: E402
from scena.shapes import Circle, _point_in_polygon  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made

SCOOPS = ("top_left", "top_right", "bottom_left", "bottom_right",
          "top_center", "bottom_center", "left_center", "right_center")
CORNERS = SCOOPS[:4]


def xy(p):
    return (float(p.x), float(p.y))


def model_of(c):
    """``(cx, cy, w, h, ang, (sx, sy), (rx, ry))``: the shape from public reads.

    ``(sx, sy)`` is the scoop center in the box's local frame, ``rx`` / ``ry``
    the curve's radii along the local x / y axes.
    """
    cx, cy = xy(c.center)
    w, h, ang = float(c.width), float(c.height), float(c.angle)
    px, py = xy(getattr(c, c.scoop))
    a = math.radians(ang)
    dx, dy = px - cx, py - cy
    sx = dx * math.cos(a) + dy * math.sin(a)
    sy = -dx * math.sin(a) + dy * math.cos(a)
    mx, my = (max(0.0, float(v)) for v in xy(c.rim))
    edge_x = abs(sx) < 1e-6 * max(1.0, w)          # top / bottom center
    edge_y = abs(sy) < 1e-6 * max(1.0, h)          # left / right center
    rx = (0.5 * w if edge_x else w) - mx
    ry = (0.5 * h if edge_y else h) - my
    return cx, cy, w, h, ang, (sx, sy), (max(rx, 0.0), max(ry, 0.0))


def local_of(m, x, y):
    cx, cy, _w, _h, ang = m[:5]
    a = math.radians(ang)
    dx, dy = x - cx, y - cy
    return (dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a))


def world_of(m, lx, ly):
    cx, cy, _w, _h, ang = m[:5]
    a = math.radians(ang)
    return (cx + lx * math.cos(a) - ly * math.sin(a), cy + lx * math.sin(a) + ly * math.cos(a))


def boundary_distance(m, x, y):
    """Approximate distance from (x, y) to the shape's outline (box or curve)."""
    _cx, _cy, w, h, _ang, (sx, sy), (rx, ry) = m
    lx, ly = local_of(m, x, y)
    d_box = min(abs(abs(lx) - 0.5 * w), abs(abs(ly) - 0.5 * h))
    if rx <= 0 or ry <= 0:
        return d_box
    u, v = (lx - sx) / rx, (ly - sy) / ry
    rho = math.hypot(u, v)
    d_curve = abs(rho - 1.0) * min(rx, ry)        # a lower bound off the curve
    return min(d_box, d_curve)


def inside(m, x, y):
    _cx, _cy, w, h, _ang, (sx, sy), (rx, ry) = m
    lx, ly = local_of(m, x, y)
    if abs(lx) > 0.5 * w or abs(ly) > 0.5 * h:
        return False
    if rx <= 0 or ry <= 0:
        return True
    return ((lx - sx) / rx) ** 2 + ((ly - sy) / ry) ** 2 >= 1.0


def samples(m, n, rng, margin=1.2):
    _cx, _cy, w, h = m[:4]
    for _ in range(n):
        yield world_of(m, rng.uniform(-margin * w / 2, margin * w / 2),
                       rng.uniform(-margin * h / 2, margin * h / 2))


def random_concave(rng):
    scoop = rng.choice(SCOOPS)
    w, h = rng.uniform(10, 300), rng.uniform(10, 300)
    rim = (rng.choice([0.0, rng.uniform(0, 0.6 * w)]), rng.choice([0.0, rng.uniform(0, 0.6 * h)]))
    pos = (rng.uniform(-400, 400), rng.uniform(-400, 400))
    ang = rng.uniform(-180, 180)
    model = rng.choice(("center", "top_left", "p1p2", "spine"))
    if model == "center":
        c = Concave(center=pos, width=w, height=h, angle=ang, scoop=scoop, rim=rim)
    elif model == "top_left":
        c = Concave(top_left=pos, width=w, height=h, angle=ang, scoop=scoop, rim=rim)
    elif model == "p1p2":
        a = math.radians(ang)
        p2 = (pos[0] + w * math.cos(a) - h * math.sin(a), pos[1] + w * math.sin(a) + h * math.cos(a))
        c = Concave(p1=pos, p2=p2, angle=ang, scoop=scoop, rim=rim)
    else:
        a = math.radians(ang)
        c = Concave(p1=pos, p2=(pos[0] + w * math.cos(a), pos[1] + w * math.sin(a)),
                    height=h, anchor="cap", scoop=scoop, rim=rim)
    return c


class TestShape(unittest.TestCase):
    def test_default(self):
        c = Concave()
        r = Rect()
        self.assertEqual(c.scoop, "top_left")
        self.assertEqual(xy(c.rim), (0.0, 0.0))
        self.assertEqual(c._oriented_frame(), r._oriented_frame())
        self.assertFalse(isinstance(c, Rect), "a Concave is not a Rect (it is no box)")
        c.destroy()
        r.destroy()

    def test_hit_test_is_the_model(self):
        rng = random.Random(5150)
        for _ in range(80):
            c = random_concave(rng)
            m = model_of(c)
            for x, y in samples(m, 60, rng):
                if boundary_distance(m, x, y) < 1e-3 * max(1.0, m[2], m[3]):
                    continue
                with self.subTest(scoop=c.scoop, model=c.model, rim=xy(c.rim)):
                    self.assertEqual(c.contains_point((x, y)), inside(m, x, y))
            c.destroy()

    def test_square_box_is_a_circle_and_the_tips_are_knife_thin(self):
        c = Concave(top_left=(0, 200), width=200, height=200)
        # Every point of the quarter circle about top_left (0, 200), radius 200, is the edge.
        for k in range(1, 10):
            t = math.radians(-90 + 9 * k)
            x, y = 200 * math.cos(t), 200 + 200 * math.sin(t)
            self.assertTrue(c.contains_point((x + 0.01 * math.cos(t), y + 0.01 * math.sin(t))))
            self.assertFalse(c.contains_point((x - 0.01 * math.cos(t), y - 0.01 * math.sin(t))))
        self.assertFalse(c.contains_point((0.5, 0.5 + 1.0)))   # the foot tip is knife-thin
        c.destroy()

    def test_edge_scoop_two_to_one_is_a_half_circle(self):
        c = Concave(center=(0, 0), width=200, height=100, scoop="bottom_center")
        for k in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17):   # the top is a pinch
            t = math.radians(10 * k)
            x, y = 100 * math.cos(t), -50 + 100 * math.sin(t)
            self.assertTrue(c.contains_point((x * 1.001, -50 + (y + 50) * 1.001)))
            self.assertFalse(c.contains_point((x * 0.999, -50 + (y + 50) * 0.999)))
        c.destroy()

    def test_rim_leaves_flats(self):
        # Quarter-pipe with a deck: rim=(20, 0) — the top is flat for 20, the foot has no step.
        c = Concave(top_left=(0, 200), width=200, height=200, rim=(20, 0))
        self.assertTrue(c.contains_point((190, 199)))          # deck
        self.assertFalse(c.contains_point((170, 199)))         # curve, just under the lip
        self.assertFalse(c.contains_point((0.5, 1.0)))         # foot: no step
        c.destroy()
        # Half-pipe with a floor: the bottom 50 stay solid.
        h = Concave(center=(0, 0), width=400, height=250, scoop="top_center", rim=(0, 50))
        self.assertTrue(h.contains_point((0, -125 + 49)))
        self.assertFalse(h.contains_point((0, -125 + 51)))
        h.destroy()

    def test_a_rim_past_the_reach_leaves_the_box(self):
        c = Concave(center=(0, 0), width=40, height=40, rim=(50, 0))
        self.assertTrue(c.contains_point((-19, 19)))
        self.assertEqual(len(c._world_pieces()), 1)
        c.destroy()


class TestModels(unittest.TestCase):
    def test_every_rect_model_places_the_same_box(self):
        forms = [
            dict(center=(10, 20), width=60, height=30, angle=15),
            dict(top_left=(10, 20), width=60, height=30, angle=-25),
            dict(p1=(0, 0), p2=(40, 30)),
            dict(p1=(0, 0), p2=(40, 30), angle=20),
            dict(p1=(5, 5), vec=Vec2(30, -20), angle=10),
            dict(p1=(0, 0), p2=(50, 10), height=20, anchor="side_left"),
            dict(p1=(0, 0), p2=(50, 10), height=20, anchor="square"),
        ]
        for kw in forms:
            with self.subTest(**{k: str(v) for k, v in kw.items()}):
                r = Rect(**kw)
                c = Concave(**kw, scoop="bottom_right", rim=2)
                for a, b in zip(r._oriented_frame(), c._oriented_frame()):
                    self.assertAlmostEqual(a, b, places=9)
                for name in ("top_left", "bottom_right", "top_center", "p1", "p2"):
                    self.assertEqual(tuple(round(v, 9) for v in xy(getattr(r, name))),
                                     tuple(round(v, 9) for v in xy(getattr(c, name))))
                r.destroy()
                c.destroy()

    def test_box_and_frame(self):
        b = Box(center=(0, 0), width=50, height=30, angle=20)
        c = Concave(box=b, scoop="left_center")
        self.assertEqual((round(float(c.width), 9), round(float(c.height), 9)), (50.0, 30.0))
        frame = c.box
        self.assertAlmostEqual(float(frame.angle), 20.0)
        r = Rect(box=c)
        self.assertAlmostEqual(float(r.width), 50.0)
        for s in (c, r):
            s.destroy()

    def test_class_defaults(self):
        class Ramp(Concave, scoop="top_right", rim=(0, 10)):
            pass
        r = Ramp(center=(0, 0), width=40, height=40)
        self.assertEqual(r.scoop, "top_right")
        self.assertEqual(xy(r.rim), (0.0, 10.0))
        r.destroy()


class TestValidation(unittest.TestCase):
    def test_scoop(self):
        with self.assertRaises(ValueError) as cm:
            Concave(scoop="top_lefft")
        self.assertIn("top_left", str(cm.exception))
        with self.assertRaises(ValueError):
            Concave(scoop="center")                    # a hole: not a scoop
        with self.assertRaises(TypeError):
            Concave(scoop=1)
        c = Concave(scoop="Top_Right")                  # names read like color names
        self.assertEqual(c.scoop, "top_right")
        with self.assertRaises(AttributeError):
            c.scoop = "top_left"
        c.destroy()

    def test_rim(self):
        for bad, err in ((-1, ValueError), ((0, -2), ValueError), ((1, 2, 3), TypeError),
                         (True, TypeError), ("5", TypeError), (float("nan"), ValueError)):
            with self.subTest(rim=bad), self.assertRaises(err):
                Concave(rim=bad)
        c = Concave()
        c.rim = 4
        self.assertEqual(xy(c.rim), (4.0, 4.0))
        c.rim = (1, 2)
        self.assertEqual(xy(c.rim), (1.0, 2.0))
        with self.assertRaises(ValueError):
            c.rim = -3
        c.destroy()

    def test_no_corner_radius(self):
        with self.assertRaises(TypeError) as cm:
            Concave(center=(0, 0), width=10, height=10, corner_radius=2)
        self.assertIn("Rect(corner_radius", str(cm.exception))

    def test_other_kinds_refuse_scoop(self):
        r = Rect()
        with self.assertRaises(AttributeError) as cm:
            r.scoop = "top_left"
        self.assertIn("Concave", str(cm.exception))
        r.destroy()


class TestTransforms(unittest.TestCase):
    def assert_region(self, c, pred, rng, n=200):
        m = model_of(c)
        for x, y in samples(m, n, rng):
            if boundary_distance(m, x, y) < 1e-3 * max(m[2], m[3]):
                continue
            self.assertEqual(c.contains_point((x, y)), pred(x, y))

    def test_flips_mirror_the_shape(self):
        rng = random.Random(77)
        for scoop in SCOOPS:
            for axis in ("x", "y"):
                with self.subTest(scoop=scoop, axis=axis):
                    c = Concave(center=(30, -10), width=80, height=50, angle=25, scoop=scoop, rim=(6, 3))
                    before = Concave(center=(30, -10), width=80, height=50, angle=25, scoop=scoop, rim=(6, 3))
                    setattr(c, "flip_" + axis, True)
                    if axis == "x":
                        self.assert_region(c, lambda x, y: before.contains_point((60 - x, y)), rng)
                    else:
                        self.assert_region(c, lambda x, y: before.contains_point((x, -20 - y)), rng)
                    setattr(c, "flip_" + axis, False)
                    self.assert_region(c, lambda x, y: before.contains_point((x, y)), rng)
                    c.destroy()
                    before.destroy()

    def test_rotate_turns_the_shape(self):
        rng = random.Random(78)
        c = Concave(center=(0, 0), width=80, height=50, scoop="right_center", rim=(0, 5))
        ref = Concave(center=(0, 0), width=80, height=50, scoop="right_center", rim=(0, 5))
        c.rotate_by(70)
        a = math.radians(-70)
        self.assert_region(
            c, lambda x, y: ref.contains_point((x * math.cos(a) - y * math.sin(a),
                                                x * math.sin(a) + y * math.cos(a))), rng)
        c.destroy()
        ref.destroy()

    def test_scoop_stays_on_its_point_when_corners_cross(self):
        c = Concave(p1=(0, 0), p2=(100, 100))          # scoop at top_left (0, 100)
        self.assertTrue(c.contains_point((95, 5)))
        c.p1.move_to(200, 0)                            # p1 (bottom_left) is now the drawn right
        self.assertEqual(tuple(round(v, 9) for v in xy(c.top_left)), (200.0, 100.0))
        self.assertTrue(c.contains_point((105, 5)))     # the solid corner faces the scoop
        self.assertFalse(c.contains_point((195, 95)))
        c.destroy()

    def test_clone_and_copy(self):
        c = Concave(center=(5, 5), width=60, height=40, angle=10, scoop="bottom_center", rim=(3, 7))
        c.flip_x = True
        k = c.clone()
        rng = random.Random(9)
        self.assert_region(k, lambda x, y: c.contains_point((x, y)), rng)
        self.assertEqual((k.scoop, xy(k.rim)), ("bottom_center", (3.0, 7.0)))
        d = Concave(center=(0, 0), width=10, height=10, scoop="top_right")
        d << c
        self.assert_region(d, lambda x, y: c.contains_point((x, y)), rng)
        # From a Rect: the box travels, the scoop and the rim stay.
        e = Concave(center=(0, 0), width=10, height=10, scoop="top_right", rim=1)
        e << Rect(center=(50, 50), width=30, height=20)
        self.assertEqual((e.scoop, xy(e.rim)), ("top_right", (1.0, 1.0)))
        self.assertAlmostEqual(float(e.width), 30.0)
        for s in (c, k, d, e):
            s.destroy()


class TestRim(unittest.TestCase):
    def test_links(self):
        st = State()
        st.r = 10
        c = Concave(center=(0, 0), width=100, height=100, rim=lambda: (st.r, 0))
        self.assertEqual(xy(c.rim), (10.0, 0.0))
        st.r = 30
        self.assertEqual(xy(c.rim), (30.0, 0.0))
        self.assertTrue(c.contains_point((-50 + 75, 49)))     # deck now 30 wide
        d = Concave(center=(0, 0), width=100, height=100)
        d.rim @= lambda: st.r
        self.assertEqual(xy(d.rim), (30.0, 30.0))
        st.r = -5                                              # a link below 0 counts as 0
        self.assertEqual(d._rim_xy(), (0.0, 0.0))
        c.destroy()
        d.destroy()

    def test_scale_by_scales_the_rim(self):
        c = Concave(center=(0, 0), width=100, height=60, rim=(10, 4))
        c.scale_by(2)
        self.assertEqual(xy(c.rim), (20.0, 8.0))
        self.assertAlmostEqual(float(c.width), 200.0)
        st = State()
        st.r = 3
        d = Concave(center=(0, 0), width=100, height=60, rim=lambda: (st.r, st.r))
        with self.assertRaises(scena.LinkedAttributeError if hasattr(scena, "LinkedAttributeError")
                               else Exception):
            d.scale_by(2)
        c.destroy()
        d.destroy()


def _ring_on_outline(test, c, tol):
    m = model_of(c)
    for x, y in c._world_ring():
        test.assertLess(boundary_distance(m, x, y), tol + 1e-6)


class TestEveryConsumerAgrees(unittest.TestCase):
    """Draw path, collision pieces, Track outline, geom and bounds all read the
    same shape (the bug class "a consumer still treats it as a box")."""

    def test_random_shapes(self):
        import skia
        from scena.canvas import _approx_draw_aabb
        from scena.collision import _proxy_aabb_for_shape
        rng = random.Random(4242)
        for _ in range(50):
            c = random_concave(rng)
            if rng.random() < 0.4:
                c.flip_y = True
            if rng.random() < 0.5:                      # the pieces follow every verb
                c.scale_by(rng.uniform(0.3, 2.5))
            if rng.random() < 0.5:
                c.rotate_by(rng.uniform(-120, 120))
            if rng.random() < 0.3:
                c.move_by(rng.uniform(-50, 50), rng.uniform(-50, 50))
            m = model_of(c)
            pieces = c._world_pieces()
            ring = c._world_ring()
            cx, cy, w, h, ang = c._oriented_frame()
            path = c._local_path(w, h, c._scoop_layout(w, h))
            for x, y in samples(m, 80, rng):
                want = inside(m, x, y)
                d = boundary_distance(m, x, y)
                ctx = dict(scoop=c.scoop, model=c.model, rim=xy(c.rim))
                if d > 0.3:
                    with self.subTest(consumer="collision", **ctx):
                        self.assertEqual(any(_point_in_polygon(x, y, p) for p in pieces), want)
                if d > 0.02:
                    with self.subTest(consumer="outline", **ctx):
                        self.assertEqual(_point_in_polygon(x, y, ring), want)
                    lx, ly = local_of(m, x, y)
                    with self.subTest(consumer="draw path", **ctx):
                        self.assertEqual(path.contains(lx, ly), want)
                    with self.subTest(consumer="closest_point", **ctx):
                        q = scena.closest_point(c, (x, y))
                        self.assertEqual(q == (x, y), want)
            _ring_on_outline(self, c, 0.011)
            for name, box in (("canvas", _approx_draw_aabb(c)), ("broad-phase", _proxy_aabb_for_shape(c))):
                x0, y0, x1, y1 = box
                for x, y in ring:
                    with self.subTest(bounds=name):
                        self.assertTrue(x0 - 1e-6 <= x <= x1 + 1e-6 and y0 - 1e-6 <= y <= y1 + 1e-6)
            c.destroy()

    def test_pieces_are_convex_and_counter_clockwise(self):
        from scena.collision import _convex_ring, _signed_area
        rng = random.Random(31)
        for _ in range(40):
            c = random_concave(rng)
            for p in c._world_pieces():
                self.assertTrue(_convex_ring(p) or len(p) == 3, p)
                self.assertGreater(_signed_area(p), 0.0)
            c.destroy()

    def test_an_outer_face_is_split_at_most_once(self):
        # Seams between pieces stay inside the solid: a body sliding on an
        # outer face crosses at most one seam (at the scoop box's far corner).
        for scoop in SCOOPS:
            for rim in ((0, 0), (15, 0), (0, 15), (15, 15)):
                c = Concave(center=(0, 0), width=120, height=80, scoop=scoop, rim=rim)
                pieces = c._world_pieces()
                faces = {"bottom": lambda x, y: abs(y + 40) < 1e-9, "top": lambda x, y: abs(y - 40) < 1e-9,
                         "left": lambda x, y: abs(x + 60) < 1e-9, "right": lambda x, y: abs(x - 60) < 1e-9}
                for face, on in faces.items():
                    touching = 0
                    for p in pieces:
                        n = len(p)
                        if any(on(*p[i]) and on(*p[(i + 1) % n]) and p[i] != p[(i + 1) % n]
                               for i in range(n)):
                            touching += 1
                    limit = 4 if scoop.endswith("_center") else 2
                    with self.subTest(scoop=scoop, rim=rim, face=face):
                        self.assertLessEqual(touching, limit)
                c.destroy()

    def test_track_starts_where_the_curve_begins(self):
        c = Concave(top_left=(0, 200), width=200, height=200)
        t = Track(c)
        self.assertEqual(tuple(round(v, 6) for v in t.at(0)), (200.0, 200.0))   # the lip
        x, y = t.at(0.2)                                                        # on the curve
        self.assertAlmostEqual(math.hypot(x, y - 200), 200.0, delta=0.02)
        t.destroy()
        c.destroy()

    def test_intersections(self):
        c = Concave(top_left=(0, 200), width=200, height=200)
        line = scena.Line(p1=(-10, 100), p2=(210, 100))
        hits = scena.intersections(c, line)
        self.assertEqual(len(hits), 2)
        self.assertAlmostEqual(hits[0][0], math.sqrt(200 ** 2 - 100 ** 2), delta=0.02)
        self.assertAlmostEqual(hits[1][0], 200.0, delta=1e-9)
        line.destroy()
        c.destroy()


class TestCaches(unittest.TestCase):
    def test_a_rim_write_alone_rebuilds_draw_and_collision(self):
        import skia
        from scena.collision import snapshot_shape
        c = Concave(center=(300, 300), width=100, height=100)
        surface = skia.Surface(64, 64)
        c._geometry_draw(surface.getCanvas())
        key0 = c._geom_path_key
        c.collidable = True
        owner = c._collider
        snapshot_shape(c, cache_owner=owner)
        c.rim = (30, 0)
        c._geometry_draw(surface.getCanvas())
        self.assertNotEqual(c._geom_path_key, key0)
        got = snapshot_shape(c, cache_owner=owner)
        # The curve meets the top edge 70 from the scoop (top_left, x 250): the lip.
        self.assertTrue(any(abs(v[1] - 350) < 1e-9 and abs(v[0] - 320) < 1e-9
                            for p in got for v in p.verts), "the lip moved with the rim")
        c.move_by(25, -10)       # the translate fast path must not slide the old hull
        got = snapshot_shape(c, cache_owner=owner)
        self.assertTrue(any(abs(v[1] - 340) < 1e-9 and abs(v[0] - 345) < 1e-9
                            for p in got for v in p.verts))
        c.collidable = False
        c.destroy()

    def test_a_flip_with_the_same_angle_moves_the_hull(self):
        from scena.collision import snapshot_shape
        c = Concave(center=(0, 0), width=100, height=100, angle=90)
        c.collidable = True
        owner = c._collider
        before = sorted(v for p in snapshot_shape(c, cache_owner=owner) for v in p.verts)
        c.flip_x = True                  # 180 - 90 = 90: the angle does not change
        self.assertAlmostEqual(float(c.angle), 90.0)
        after = sorted(v for p in snapshot_shape(c, cache_owner=owner) for v in p.verts)
        self.assertNotEqual(before, after)
        c.collidable = False
        c.destroy()


class CollisionCase(unittest.TestCase):
    def setUp(self):
        reset_collision_system()
        self.owned = []

    def tearDown(self):
        for s in self.owned:
            try:
                s.destroy()
            except Exception:
                pass
        reset_collision_system()

    def static(self, shape):
        shape.mass = STATIC
        self.owned.append(shape)
        return shape

    def ball(self, center, vel, r=10.0):
        b = Circle(center=center, radius=r, group="bola")
        b.mass = 1.0
        b.vel = Vec2(*vel)
        self.owned.append(b)
        return b

    @staticmethod
    def frame(b, dt=1 / 60, g=900.0):
        b.vel.y -= g * dt
        b.move_by(float(b.vel.x) * dt, float(b.vel.y) * dt)
        get_collision_system().step()


class TestRides(CollisionCase):
    def test_a_ball_rides_the_quarter_pipe_and_comes_back(self):
        """CV1: the sweep met the hull of the pieces (the 45° chord from the
        foot to the lip) and threw the ball off at 45°; it peaked at half the
        height its speed allows."""
        R = 200.0
        self.static(Concave(top_left=(0, R), width=R, height=R, group="chao"))
        self.static(Rect(top_left=(-600, 0), width=600, height=40, group="chao"))
        b = self.ball((-300, 10.1), (500, 0))
        resolve("bola", "chao", bounce=0.0)
        peak = -1e9
        worst = 0.0
        for _ in range(140):
            self.frame(b)
            x, y = xy(b.center)
            peak = max(peak, y)
            if 0 < x < R:
                worst = max(worst, math.hypot(x, y - R) - (R - 10))   # into the solid
        ideal = 10 + 500 ** 2 / (2 * 900)
        self.assertGreater(peak, 0.85 * ideal)
        self.assertLess(worst, 0.3)                                    # chords: 0.25 DU
        self.assertLess(float(b.vel.x), -400, "it comes back down the curve")
        self.assertLess(xy(b.center)[0], 0)

    def test_a_ball_swings_in_the_half_pipe(self):
        # Box x -200..200, y -25..225; the curve: center (0, 225), radius 200,
        # bottom at y 25 (the 50-deep floor). Frictionless: the ball swings.
        self.static(Concave(center=(0, 100), width=400, height=250, scoop="top_center",
                            rim=(0, 50), group="chao"))
        b = self.ball((-150, 300), (0, 0))
        resolve("bola", "chao", bounce=0.0)
        sides = set()
        landed = False
        for _ in range(600):
            self.frame(b)
            x, y = xy(b.center)
            d = math.hypot(x, y - 225)
            if d > 185:
                landed = True
            if landed:
                self.assertLess(d, 190 + 0.3, "never into the solid")
                self.assertLess(y, 300, "no energy made")
                self.assertGreater(y, 25 + 10 - 0.3)
                sides.add(x > 0)
        self.assertEqual(sides, {True, False}, "it swings through the bottom")

    def test_a_ball_drops_into_a_concave_polygon(self):
        """The same bug class for any multi-prim partner: a U polygon."""
        self.static(Polygon(points=[(0, 0), (100, 0), (100, 80), (70, 80), (70, 20),
                                    (30, 20), (30, 80), (0, 80)], group="chao"))
        b = self.ball((50, 120), (0, 0))
        resolve("bola", "chao", bounce=0.0)
        for _ in range(120):
            self.frame(b)
        self.assertAlmostEqual(xy(b.center)[1], 30.0, delta=0.5)


class TestQueries(CollisionCase):
    def test_the_scoop_is_empty(self):
        self.static(Concave(center=(0, 0), width=100, height=100, group="wall"))
        self.assertEqual(scena.collision.query_circle((-40, 40), radius=5, group="wall"), [])
        self.assertEqual(len(scena.collision.query_circle((40, -40), radius=5, group="wall")), 1)


if __name__ == "__main__":
    unittest.main()
